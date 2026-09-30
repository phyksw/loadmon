"""Current AI control flow with synthetic responses and virtual time; no external services."""
import ast
import contextlib
from datetime import datetime, timedelta
import io
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from types import SimpleNamespace
import unittest


ROOT = Path(__file__).resolve().parents[1] / "LoadMonitor25"


def definitions(relative, names, env=None):
    env = {} if env is None else env
    tree = ast.parse((ROOT / relative).read_text(encoding="utf-8-sig"))
    selected = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in names:
            selected.append(node)
        elif isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in names for t in node.targets):
            selected.append(node)
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(ROOT / relative), "exec"), env)
    return env


def failures():
    return definitions("core/details.py", {"explain_failure", "PHASE_TEXT", "FATAL_PHASES", "_FATAL_ERRORS"})


def judge_environment(sender):
    env = definitions("judge.py", {"judge_rows", "MIN_SPLIT", "MAX_SPLIT_DEPTH", "MIN_RETRY_ROWS",
                                   "SOFT_FAIL_CHUNKS", "ABORT_FAIL_CHUNKS"}, failures())
    env.update(copilot_send=sender, judge_prompt=lambda chunk, start, models, **kw: kw.get("idxs", []),
               taxonomy_prompt=lambda *args: [], progress=lambda *args: None, recent_details=lambda *args: [],
               note_bad_reply=lambda: None,
               parse_judgments_ex=lambda reply, idxs: ({i: {"work": True} for i in idxs}, {"json": True}))
    return env


def fresh_stats():
    return {"roundtrips": 0, "repaired": 0, "retries": 0, "failed_rows": 0, "omitted_rows": 0,
            "notes": [], "last_err": "", "soft": False, "aborted": False}


class JudgeTerminalTests(unittest.TestCase):
    def test_terminal_chunk_is_not_split(self):
        for phase in ("login_required", "edge_not_found", "launch_failed", "input_not_found"):
            with self.subTest(phase=phase):
                calls = []
                def sender(*args):
                    calls.append(args)
                    return {"ok": False, "phase": phase}
                env, stats = judge_environment(sender), fresh_stats()
                result = env["judge_rows"](range(40), [{}] * 40, [], [], "synthetic", "chunk1", 0, stats)
                self.assertEqual(result, {})
                self.assertEqual((len(calls), stats["failed_rows"]), (1, 40))
                self.assertTrue(stats["fatal"])

    def test_transient_failure_still_splits_and_recovers(self):
        calls = []
        def sender(prompt, *args):
            calls.append(prompt)
            return {"ok": False, "phase": "no_reply"} if len(calls) == 1 else {"ok": True, "reply": "valid"}
        env, stats = judge_environment(sender), fresh_stats()
        result = env["judge_rows"](range(40), [{}] * 40, [], [], "synthetic", "chunk1", 0, stats)
        self.assertEqual(len(result), 40)
        self.assertEqual([len(x) for x in calls], [40, 20, 20])
        self.assertEqual(stats["failed_rows"], 0)

    def test_terminal_failure_in_first_half_skips_second_half(self):
        calls = []
        def sender(*args):
            calls.append(args)
            return {"ok": False, "phase": "no_reply" if len(calls) == 1 else "login_required"}
        env, stats = judge_environment(sender), fresh_stats()
        env["judge_rows"](range(40), [{}] * 40, [], [], "synthetic", "chunk1", 0, stats)
        self.assertEqual((len(calls), stats["failed_rows"]), (2, 40))

    def main_loop(self, taxonomy_phase, chunk_ok):
        calls = []
        def sender(prompt, tag, name):
            calls.append(name)
            return ({"ok": False, "phase": taxonomy_phase} if name == "taxonomy" else
                    {"ok": True, "reply": "valid"} if chunk_ok else {"ok": False, "phase": "login_required"})
        env = judge_environment(sender)
        env.update(rows=[{}] * 400, models=[], tag="synthetic", hints=[], pinned=[],
                   plan=[(i * 40, 40) for i in range(10)], chunks=[None] * 10,
                   judged={}, n_fail=0, n_partial=0, last_err="", consec=0, prev_idxs=())
        tree = ast.parse((ROOT / "judge.py").read_text(encoding="utf-8-sig"))
        main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
        selected = []
        for node in main.body:
            text = ast.unparse(node)
            if (text.startswith("res = copilot_send(taxonomy_prompt")
                    or text.startswith("why0, how0, fatal0 =")
                    or text.startswith("fatal0 =") or text.startswith("st =")
                    or text.startswith("if fatal0:") or text.startswith("for ci, (start, n) in enumerate(plan):")):
                selected.append(node)
        self.assertEqual(len(selected), 6)
        with contextlib.redirect_stdout(io.StringIO()):
            exec(compile(ast.Module(body=selected, type_ignores=[]), "current_main_control", "exec"), env)
        return calls, env

    def test_taxonomy_login_failure_stops_all_400_rows_after_one_call(self):
        calls, env = self.main_loop("login_required", False)
        self.assertEqual(calls, ["taxonomy"])
        self.assertEqual(env["st"]["failed_rows"], 400)
        self.assertEqual(env["n_fail"], 10)
        self.assertTrue(env["st"]["aborted"])

    def test_taxonomy_input_delay_gets_one_confirmation_and_can_recover(self):
        calls, env = self.main_loop("input_not_found", True)
        self.assertEqual(len(calls), 11)
        self.assertEqual(len(env["judged"]), 400)
        self.assertFalse(env["st"]["aborted"])
        calls, env = self.main_loop("input_not_found", False)
        self.assertEqual(calls, ["taxonomy", "chunk1"])
        self.assertEqual(env["st"]["failed_rows"], 400)

    def test_partial_coverage_returns_partial_before_narrating_but_complete_repairs_continue(self):
        tree = ast.parse((ROOT / "judge.py").read_text(encoding="utf-8-sig"))
        main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
        index = next(i for i, n in enumerate(main.body) if ast.unparse(n).startswith("if st.get('fatal') or"))
        tail = ast.FunctionDef(name="outcome", args=ast.arguments(posonlyargs=[], args=[], kwonlyargs=[],
                               kw_defaults=[], defaults=[]), body=main.body[index:], decorator_list=[])
        for judged_n, repaired, expected in ((1, 0, 2), (399, 0, 2), (400, 3, 0)):
            calls = []
            env = {"judged": {i: {} for i in range(judged_n)}, "rows": [{}] * 400,
                   "st": dict(fresh_stats(), repaired=repaired), "chunks": [None] * 10, "n_fail": 0,
                   "json": json, "sys": SimpleNamespace(argv=["judge.py"]), "progress": lambda *a: None,
                   "kept": [{"time": "2026-01-03 09:00"}], "total_mm": 1, "tag": "synthetic", "rep": "synthetic",
                   "narrate": lambda *args: calls.append("narrate") or {}, "save_narratives": lambda *a: None}
            exec(compile(ast.fix_missing_locations(ast.Module(body=[tail], type_ignores=[])), "current_outcome", "exec"), env)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(env["outcome"](), expected)
            self.assertEqual(calls, ["narrate"] if expected == 0 else [])


class MailTerminalTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="lm25-ai-terminal-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.out = self.root / "data/outlook"
        self.out.mkdir(parents=True)
        self.calls = []
        def run(*args, **kwargs):
            self.calls.append(args)
            return SimpleNamespace(stdout=json.dumps({"ok": False, "phase": "login_required"}).encode())
        self.env = failures()
        # Exercise the production atomic writer/status helper inside the temporary root.
        state_env = {"__name__": "collection_state_for_mail_test"}
        exec(compile((ROOT / "core/collection_state.py").read_text(encoding="utf-8-sig"),
                     str(ROOT / "core/collection_state.py"), "exec"), state_env)
        self.env.update(merge_csv=state_env["merge_csv"], write_status=state_env["write_status"])
        self.env.update(ROOT=str(self.root), OUT_DIR=str(self.out),
                        UNAVAILABLE_FLAG=str(self.out / "mail_copilot_unavailable.json"),
                        datetime=datetime, timedelta=timedelta, os=os, json=json, re=re,
                        sys=SimpleNamespace(argv=["collector", "--from", "2026-01-01", "--to", "2026-09-13", "--force"],
                                            executable="synthetic"),
                        subprocess=SimpleNamespace(run=run, TimeoutExpired=subprocess.TimeoutExpired),
                        NO_WIN=0, build_prompt=lambda *args: "synthetic", _timeout=lambda: 100)
        definitions("collect/Get-MailViaCopilot.py", {"TerminalCollectionError", "arg", "main", "_one_slice",
                    "collect_kind", "_refine", "slices_of", "need_subdivide", "_span_days", "_has_data",
                    "_save", "_esc", "FULL_N", "MAIL_HDR", "CAL_HDR"}, self.env)

    def test_login_failure_stops_mail_and_calendar_without_overwriting_existing_files(self):
        old = b"previous synthetic rows\n"
        for filename in ("mail.csv", "calendar.csv", "mail_source.json"):
            (self.out / filename).write_bytes(old)
        with contextlib.redirect_stdout(io.StringIO()):
            result = self.env["main"]()
        self.assertEqual((result, len(self.calls)), (1, 1))
        for filename in ("mail.csv", "calendar.csv", "mail_source.json"):
            self.assertEqual((self.out / filename).read_bytes(), old)
        self.assertFalse((self.out / "mail_copilot_unavailable.json").exists())

    def test_terminal_failure_during_subdivision_saves_rows_and_stops(self):
        calls = []
        row = ["sent", "2026-01-03 09:00", "synthetic", "subject", "conv", "", "minute"]
        def query(*args):
            calls.append(args)
            if len(calls) == 1:
                return [row], "table"
            raise self.env["TerminalCollectionError"]("login required")
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(self.env["TerminalCollectionError"]):
            self.env["collect_kind"]("mail", "2026-01-01", "2026-09-13", True, query)
        self.assertEqual(len(calls), 2)
        self.assertIn("2026-01-03 09:00", (self.out / "mail.csv").read_text(encoding="utf-8-sig"))

    def test_partial_save_updates_source_metadata_and_still_reports_failure(self):
        calls = []
        row = ["sent", "2026-01-03 09:00", "synthetic", "subject", "conv", "", "minute"]
        def query(*args):
            calls.append(args)
            if len(calls) == 1:
                return [row], "table"
            raise self.env["TerminalCollectionError"]("login required")
        self.env["_one_slice"] = query
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.env["main"](), 1)
        source = json.loads((self.out / "mail_source.json").read_text(encoding="utf-8"))
        self.assertEqual((len(calls), source["source"], source["mail"]), (2, "copilot", 1))
        self.assertEqual(source["kinds"], ["mail"])
        self.assertEqual(source["warnings"], ["login required"])
        self.assertFalse(source["calendar_complete"])

    def test_transient_no_data_keeps_existing_subdivision_behavior(self):
        calls = []
        def query(*args):
            calls.append(args)
            return [], "other"
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.env["collect_kind"]("mail", "2026-01-01", "2026-09-13", True, query), (0, False))
        self.assertEqual(len(calls), 9)

    def test_calendar_partial_rows_are_never_marked_complete_after_terminal_failure(self):
        self.env["sys"].argv += ["--only", "cal"]
        calls = []
        row = ["2026-01-03 09:00", "2026-01-03 10:00", "False", "2", "synthetic", "", "", "", ""]
        def query(*args):
            calls.append(args)
            if len(calls) == 1:
                return [row], "table"
            raise self.env["TerminalCollectionError"]("login required")
        self.env["_one_slice"] = query
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.env["main"](), 1)
        source = json.loads((self.out / "mail_source.json").read_text(encoding="utf-8"))
        self.assertEqual((len(calls), source["calendar"]), (2, 1))
        self.assertFalse(source["calendar_complete"])
        self.assertEqual(source["warnings"], ["login required"])


class Clock:
    def __init__(self):
        self.now = 0.0

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class DriverTests(unittest.TestCase):
    def driver(self, reply, busy=lambda seconds: False, ready_at=0):
        clock = Clock()
        env = {"re": re, "time": clock, "json": json, "os": os,
               "js_state": lambda: "state", "js_chat_text": lambda cfg: "chat",
               "js_focus": lambda cfg: "focus", "js_editor_text": lambda: "editor",
               "js_insert_fallback": lambda prompt: "insert", "js_click_send": lambda cfg: "send",
               "js_is_generating": lambda: "busy", "wait_idle": lambda *a, **kw: 0,
               "select_model": lambda *a, **kw: "synthetic", "build_anchor": lambda prompt: "anchor",
               "pick_reply": lambda text, *args: (text, "anchor"),
               "has_pledge": lambda text, *args: "[[END]]" in text,
               "strip_echo": lambda text, *args: text.replace("[[END]]", "").strip(),
               "is_cut_reply": lambda text: False}
        definitions("tools/copilot_auto.py", {"_roundtrip_once", "_reply_result", "_json_incomplete",
                                               "_reply_finished", "login_required", "_wait_rest", "_run_parts"}, env)
        class CDP:
            def __init__(self):
                self.reads = 0
                self.sent_at = None

            def eval(self, expression, **kwargs):
                if expression == "state":
                    return {"url": "https://synthetic.invalid/chat", "ready": "complete"}
                if expression == "focus":
                    return {"ok": clock.now >= ready_at}
                if expression == "editor":
                    return "synthetic prompt" if self.sent_at is None else ""
                if expression == "send":
                    self.sent_at = clock.now
                    return {"ok": True}
                if expression == "busy":
                    return busy(clock.now - (self.sent_at or 0))
                if expression == "chat":
                    self.reads += 1
                    return "" if self.reads <= 2 else reply(clock.now - (self.sent_at or 0))
                raise AssertionError(expression)

            def call(self, *args, **kwargs):
                return None
        return env, CDP(), clock

    def run_once(self, env, cdp):
        return env["_roundtrip_once"](cdp, {"replyTimeoutSec": 90, "pollSec": 3, "stablePolls": 8}, "synthetic prompt")

    def test_open_json_does_not_complete_during_a_pause_even_if_busy_selector_misses(self):
        env, cdp, clock = self.driver(lambda t: '{"j":[[0,"y"' if t < 40 else '{"j":[]}', lambda t: False)
        result = self.run_once(env, cdp)
        self.assertTrue(result["ok"])
        self.assertEqual(result["reply"], '{"j":[]}')
        self.assertGreater(clock.now - cdp.sent_at, 40)

    def test_closed_json_waits_while_generation_is_still_active(self):
        env, cdp, clock = self.driver(lambda t: '{"j":[]}', lambda t: t < 40)
        result = self.run_once(env, cdp)
        self.assertTrue(result["ok"])
        self.assertGreaterEqual(clock.now - cdp.sent_at, 40)

    def test_permanently_open_json_times_out_instead_of_success(self):
        env, cdp, clock = self.driver(lambda t: '{"j":[[0,"y"')
        result = self.run_once(env, cdp)
        self.assertFalse(result["ok"])
        self.assertEqual(result["phase"], "no_reply")
        self.assertLessEqual(clock.now - cdp.sent_at, 95)

    def test_complete_pledge_and_non_json_replies_keep_existing_success_paths(self):
        for reply in ('{"j":[]} [[END]]', "box,time,sender\nsent,2026-01-01,synthetic {team", "받았습니다"):
            with self.subTest(reply=reply):
                env, cdp, clock = self.driver(lambda t: reply)
                result = self.run_once(env, cdp)
                self.assertTrue(result["ok"])
                self.assertEqual(result["sentinel"], "[[END]]" in reply)
                if result["sentinel"]:
                    self.assertLess(clock.now - cdp.sent_at, 10)

    def test_delayed_editor_is_checked_within_existing_30_second_ready_budget(self):
        env, cdp, clock = self.driver(lambda t: '{"j":[]} [[END]]', ready_at=12)
        self.assertTrue(self.run_once(env, cdp)["ok"])
        self.assertGreaterEqual(cdp.sent_at, 12)
        self.assertLess(cdp.sent_at, 30)

    def test_json_brackets_inside_strings_and_escapes_are_supported(self):
        env, _, _ = self.driver(lambda t: "")
        for text in ('{"text":"[ ] } {"}', '{"text":"quote: \\""}', '[{"x":1}]', "없음", "설명 {미완 문구"):
            with self.subTest(text=text):
                self.assertFalse(env["_json_incomplete"](text))
        for text in ('{"text":"open', '[{"x":1}', '{"x":[1,2', '```json\n{"x":['):
            self.assertTrue(env["_json_incomplete"](text))

    def test_split_never_sends_next_part_when_completion_cannot_be_confirmed(self):
        env, cdp, _ = self.driver(lambda t: "")
        calls = []
        def once(*args):
            calls.append(args)
            return {"ok": True, "reply": "받았습니다", "sentinel": False}
        env.update(_roundtrip_once=once, _wait_rest=lambda *args: None, SENTINEL="[[END]]")
        result = env["_run_parts"](cdp, {}, ["one", "two"], False)
        self.assertFalse(result["ok"])
        self.assertEqual(len(calls), 1)

    def test_wait_rest_does_not_release_open_or_still_generating_reply_at_timeout(self):
        for reply, busy in ((lambda t: '{"x":[', lambda t: False),
                            (lambda t: '{"x":[]}', lambda t: True)):
            env, cdp, clock = self.driver(reply, busy)
            cdp.reads, cdp.sent_at = 2, 0
            self.assertIsNone(env["_wait_rest"](cdp, {}, "synthetic", secs=75))
            self.assertLessEqual(clock.now, 75)

    def test_wait_rest_still_accepts_complete_quiet_reply_and_unknown_status_waits(self):
        env, cdp, clock = self.driver(lambda t: '{"x":[]}', lambda t: False)
        cdp.reads, cdp.sent_at = 2, 0
        self.assertEqual(env["_wait_rest"](cdp, {}, "synthetic", secs=75), '{"x":[]}')
        self.assertLessEqual(clock.now, 75)
        self.assertFalse(env["_reply_finished"](SimpleNamespace(eval=lambda *a, **kw: None), '{"x":[]}'))


if __name__ == "__main__":
    unittest.main()
