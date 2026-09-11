"""Completed-run reuse with synthetic TEMP inputs; no app/AI/collector starts."""
import ast
import contextlib
from datetime import date
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

APP = Path(__file__).resolve().parents[1] / "LoadMonitor25"
SPEC = importlib.util.spec_from_file_location("run_cache", APP / "core" / "run_cache.py")
CACHE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CACHE)
PERIOD = ["2026-01-01", "2026-01-31"]
TAG = "20260101-20260131"
ARGS = ["--skip-collect", "--ai", "--reuse-complete", "--from", *PERIOD[:1], "--to", PERIOD[1]]
NAMES = ["업무 로드 추출", "AI 판정", "AI 정제", "Agentic 매칭", "워크플로우 분석",
         "Agentic 실측 재계산", "보고서 생성", "팀 업로드 묶음 준비", "완료"]
AGENTIC_PROMPT = ("[계획 과제]\n· SYN-1 (Synthetic axis) Synthetic candidate — Synthetic description\n"
                  "[현재 업무 — 과제 / 세부업무 / 유형 / 신호 근거 — 설명 (수동 m/n)]  (MM 순)\n"
                  "· Synthetic project / Synthetic work / 개발 / 신호 합성 1건 — Synthetic description (수동 0/1)")


class CacheTests(unittest.TestCase):
    def setUp(self):
        # Only synthetic directories; retain TEMP artifacts for independent review.
        self.base = Path(tempfile.mkdtemp(prefix="lm25-run-cache-test-"))
        self.root = self.base / "LoadMonitor25"
        self.root.mkdir()
        self.write("core/extract.py", 'HINT_TEXT_EXTS = {".txt"}\nHINT_OOXML = (".docx",)\n')
        self.write("run.py", "# synthetic source\n")
        self.write("data/manual/work.csv", "item\nsynthetic\n")
        self.write("data/추가PC/PC2/files/files.csv", "name,folder\n")
        self.put("config/config.json", {"owner": "Synthetic"})
        self.put("config/agentic_tasks.json", {"tasks": []})
        self.put(f"report/entities_{TAG}.json", {"models": [{"name": "Synthetic"}]})
        for prefix, suffix in (("mm_meta", ".json"), ("mm_rows", ".csv"), ("mm_rows", "_refined.csv"),
                               ("refine_map", ".json"), ("pivots", ".json"), ("evidence", ".md")):
            self.write(f"report/{prefix}_{TAG}{suffix}", "{}\n")
        self.write(f"report/signals_{TAG}.csv", "time,text\n2026-01-05 09:00,synthetic\n")
        self.put(f"report/ai_narratives_{TAG}.json", {"2026-01": {"summary": "Synthetic", "projects": []}})
        self.put(f"report/ai_judgments_{TAG}.json", {
            "model": "live-model", "total": 1, "judged": 1, "items": {"0": {"work": True}}, "aborted": False,
            **dict.fromkeys(("failed_chunks", "partial_chunks", "failed_rows", "omitted_rows", "repaired", "retries"), 0)})
        self.put(f"report/agentic_{TAG}.json", {
            "tag": TAG, "model_name": "live-model", "partial": False, "rows_total": 1, "rows_analyzed": 1,
            "rows_pending": 0, "failed_chunks": 0, "salvaged_chunks": 0, "last_error": {}})
        self.put(f"report/workflow_{TAG}.json", {
            "ok": True, "tag": TAG, "model_name": "live-model", "partial": False, "rows_units": 1,
            "missing_count": 0, "failed_chunks": 0, "salvaged_chunks": 0, "dropped": [], "last_error": {}})
        made = {}
        for kind in ("word", "island", "freeze"):
            made[kind] = [str(self.write(f"report/{kind}{i}.html", f"Synthetic {kind} {i}")) for i in range(2)]
        self.frozen = {"ok": True, "partial": False, "tag": TAG, "made": made, "errors": [],
                       "files": [p for files in made.values() for p in files]}
        self.stages = [{"name": name, "ok": True} for name in NAMES]
        self.session = CACHE.Session(self.root, PERIOD)
        for stage in CACHE.STAGES:
            command = self.session.command(stage, ["--from", PERIOD[0], "--to", PERIOD[1]])
            self.assertEqual(command[2:4], ["--observe", stage])
            summary = ({"ok": True, **dict.fromkeys(("failed_chunks", "failed_items", "repaired", "retries", "bad_rows"), 0)}
                       if stage == "refine.py" else {})
            CACHE._atomic(self.session.receipts[stage], {"safe": True, "rc": 0, "calls": 1, "summary": summary})

    def write(self, relative, body):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        return path

    def put(self, relative, obj):
        return self.write(relative, json.dumps(obj, ensure_ascii=False))

    def save(self):
        ok, reason = self.session.save(self.stages, self.frozen)
        self.assertTrue(ok, reason)

    def hit(self):
        return CACHE.Session(self.root, PERIOD).lookup()[0]

    def test_identical_contents_reuse_without_ai_and_ignore_last_run(self):
        self.save()
        self.put("report/last_run.json", {"stages": []})
        self.assertTrue(self.hit())
        os.utime(self.root / "data/manual/work.csv", None)
        self.assertTrue(self.hit(), "mtime alone is neither invalidation nor proof")

    def test_each_real_input_content_change_misses_even_same_mtime(self):
        self.save()
        for relative in ("data/manual/work.csv", "data/추가PC/PC2/files/files.csv", "config/config.json",
                         "config/agentic_tasks.json", "run.py", "core/extract.py"):
            with self.subTest(path=relative):
                path = self.root / relative
                old, stat = path.read_bytes(), path.stat()
                path.write_bytes(old.replace(old[:1], b"!", 1))
                os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
                # A malformed source is also a safe miss, never an application call.
                try:
                    self.assertFalse(self.hit())
                except SyntaxError:
                    pass  # Session construction is guarded by run.main.
                path.write_bytes(old)
                os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        self.assertTrue(self.hit())

    def test_added_deleted_outputs_and_inputs_miss(self):
        self.save()
        extra = self.write("data/추가PC/PC3/activity.csv", "new\n")
        self.assertFalse(self.hit())
        extra.unlink()
        self.assertTrue(self.hit())
        output = self.root / "report/word0.html"
        old, stat = output.read_bytes(), output.stat()
        output.write_bytes(b"changed")
        self.assertFalse(self.hit())
        output.unlink()
        self.assertFalse(self.hit())
        output.write_bytes(old)
        os.utime(output, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        self.assertTrue(self.hit())
        self.write("report/new-output.json", "{}")
        self.assertFalse(self.hit())

    def test_output_selection_timestamp_change_invalidates_and_browser_state_does_not(self):
        self.save()
        self.write("data/copilot_profile/Default/Cookies", "synthetic browser state")
        self.assertTrue(self.hit())
        path = self.root / f"report/mm_rows_{TAG}.csv"
        stat = path.stat()
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1000000000))
        self.assertFalse(self.hit())

    def test_expiry_original_directory_and_invalid_cache(self):
        self.save()
        record = CACHE._json(self.session.path)
        self.assertFalse(self.session.lookup(now=record["created"] + CACHE.MAX_AGE + 1)[0])
        self.assertFalse(self.session.lookup(now=record["created"] - 1)[0])
        copied = self.base / "OtherLocation"
        shutil.copytree(self.root, copied)
        self.assertFalse(CACHE.Session(copied, PERIOD).lookup()[0])
        self.session.path.write_text("{broken", encoding="utf-8")
        self.assertFalse(self.hit())
        self.session.path.write_text(json.dumps({**record, "created": float("nan")}), encoding="utf-8")
        self.assertFalse(self.hit())

    def test_changed_alias_during_run_never_registers(self):
        self.put("config/detail_aliases.json", {"map": {"old": "new"}, "updated": "now"})
        self.assertFalse(self.session.save(self.stages, self.frozen)[0])
        self.assertFalse(self.session.path.exists())

    def test_user_data_named_pycache_is_hashed_but_code_bytecode_is_not(self):
        for area in ("data/추가PC/__pycache__/manual/worklog.csv", "config/__pycache__/overrides.json",
                     "report/__pycache__/result.json"):
            path = self.write(area, "synthetic original")
            session = CACHE.Session(self.root, PERIOD)
            session.receipts = self.session.receipts
            self.assertTrue(session.save(self.stages, self.frozen)[0])
            path.write_text("synthetic changed", encoding="utf-8")
            self.assertFalse(CACHE.Session(self.root, PERIOD).lookup()[0], area)
        self.session = CACHE.Session(self.root, PERIOD)
        self.session.receipts = session.receipts
        self.save()
        self.write("core/__pycache__/module.pyc", "synthetic bytecode")
        self.assertTrue(self.hit())

    def test_malformed_agentic_consumed_as_empty_cannot_register(self):
        # Execute only the actual pure consumers. They discard malformed values;
        # the observer must preserve their behavior while refusing completion proof.
        source = ast.parse((APP / "agentic.py").read_text(encoding="utf-8-sig"))
        names = {"_placeholder", "_clean_list", "merge_match", "merge_new", "merge_mis"}
        consumers = {"MAX_WORK": 12, "fold": lambda s: " ".join(s.split()).casefold()}
        chosen = [node for node in source.body if isinstance(node, ast.FunctionDef) and node.name in names]
        exec(compile(ast.Module(body=chosen, type_ignores=[]), "agentic-pure-consumers", "exec"), consumers)
        malformed = {"match": [123], "new": [], "misassigned": []}
        result = {"ok": True, "phase": "replied", "model": "live-model", "sentinel": True, "cut": False,
                  "reply": json.dumps(malformed)}
        sender = mock.Mock(return_value=result)
        judge = SimpleNamespace(copilot_send=sender)
        consumed = []

        def main():
            reply = judge.copilot_send(AGENTIC_PROMPT, TAG, "agentic")
            self.assertIs(reply, result)
            obj = json.loads(reply["reply"])
            best, news, mis = {}, [], []
            consumed.extend([consumers["merge_match"](best, obj, {"SYN-1": {}}),
                             consumers["merge_new"](news, obj), consumers["merge_mis"](mis, obj)])
            self.assertEqual((best, news, mis), ({}, [], []))
            return 0  # This is the existing consumer's apparent-success case.

        stage = SimpleNamespace(main=main)
        path = self.session.receipts["agentic.py"]
        with mock.patch.object(CACHE.importlib, "import_module", side_effect=lambda name: judge if name == "judge" else stage), mock.patch.object(sys, "path", list(sys.path)), mock.patch.object(sys, "argv", []):
            self.assertEqual(CACHE.observe_stage(self.root, "agentic.py", path, []), 0)
        self.assertEqual(consumed, [0, 0, 0])
        self.assertEqual(CACHE._json(path)["rc"], 0)
        self.assertFalse(CACHE._json(path)["safe"])
        self.assertFalse(self.session.save(self.stages, self.frozen)[0])
        self.assertFalse(self.session.lookup()[0])

    def test_missing_partial_stub_and_failed_evidence_never_register(self):
        for filename, field, value in (
                (f"ai_judgments_{TAG}.json", "partial_chunks", 1),
                (f"ai_judgments_{TAG}.json", "model", "stub"),
                (f"agentic_{TAG}.json", "rows_pending", 1),
                (f"agentic_{TAG}.json", "salvaged_chunks", 1),
                (f"workflow_{TAG}.json", "partial", True),
                (f"workflow_{TAG}.json", "model_name", "stub")):
            with self.subTest(file=filename, field=field):
                path = self.root / "report" / filename
                original = CACHE._json(path)
                CACHE._atomic(path, {**original, field: value})
                self.assertFalse(self.session.save(self.stages, self.frozen)[0])
                CACHE._atomic(path, original)
        self.session.receipts["judge.py"].unlink()
        self.assertFalse(self.session.save(self.stages, self.frozen)[0])
        self.assertFalse(self.session.path.exists())

    def test_partial_retained_or_missing_narrative_status_declines_registration(self):
        relative = f"report/ai_narratives_{TAG}.json"
        narrative = CACHE._json(self.root / relative)
        status = {"schema": 1, "tag": TAG, "partial": False, "expected_months": ["2026-01"],
                  "updated_months": ["2026-01"], "retained_months": [], "missing_months": []}
        for changes in ({"partial": True}, {"retained_months": ["2026-01"]}, {"missing_months": ["2026-01"]},
                        {"updated_months": []}, {"expected_months": []}, {"tag": "20250101-20250131"}):
            with self.subTest(changes=changes):
                self.put(relative, {**narrative, "_status": {**status, **changes}})
                self.assertFalse(self.session.save(self.stages, self.frozen)[0])
        self.put(relative, {**narrative, "_status": status})
        self.save()
        self.assertTrue(self.hit())
        (self.root / relative).unlink()
        self.assertFalse(self.session.save(self.stages, self.frozen)[0])
        self.assertFalse(self.hit())

    def test_complete_flags_alone_cannot_promote_old_files(self):
        self.assertFalse(self.session.lookup()[0])
        receipts = {s: CACHE._json(p) for s, p in self.session.receipts.items()}
        receipts["refine.py"]["safe"] = False
        with self.assertRaises(CACHE.Uncertain):
            CACHE.complete(self.root, PERIOD, receipts, self.frozen)
        self.stages[0]["ok"] = False
        self.assertFalse(self.session.save(self.stages, self.frozen)[0])

    def test_external_hint_only_csv_targets_deduplicated_and_budgeted(self):
        original = self.base / "hint.txt"
        original.write_text("Original title", encoding="utf-8")
        self.write("data/files/files.csv", f"name,folder\nhint.txt,{self.base}\nhint.txt,{self.base}\nimage.png,{self.base}\n")
        first = CACHE.inputs(self.root, PERIOD)
        self.assertEqual(len(first["external_hints"]), 1)
        original.write_text("Different title", encoding="utf-8")
        self.assertNotEqual(CACHE.inputs(self.root, PERIOD), first)
        with mock.patch.object(CACHE, "MAX_EXTERNAL_BYTES", 1), self.assertRaises(CACHE.Uncertain):
            CACHE.inputs(self.root, PERIOD)
        self.write("data/files/files.csv", "name,folder\nhint.txt,\\\\server\\share\n")
        with mock.patch.object(CACHE, "_digest", wraps=CACHE._digest) as digest:
            with self.assertRaises(CACHE.Uncertain):
                CACHE.inputs(self.root, PERIOD)
            self.assertFalse(any(str(c.args[0]).startswith("\\\\") for c in digest.call_args_list))

    def test_scope_collection_upload_current_period_never_skipped(self):
        self.assertEqual(CACHE.eligible(ARGS, {"owner": "Synthetic"}, PERIOD), "")
        for argv, cfg, period in (
                (["--ai", "--reuse-complete"], {"owner": "x"}, PERIOD),
                (ARGS + ["--collect-only"], {"owner": "x"}, PERIOD),
                (ARGS + ["--unknown"], {"owner": "x"}, PERIOD),
                (ARGS, {"teamUpload": {"auto": True}}, PERIOD),
                (ARGS, {"teamShareDir": "share"}, PERIOD),
                (ARGS, {"teamUpload": "broken"}, PERIOD),
                (ARGS, {"owner": "x"}, [PERIOD[0], date.today().isoformat()])):
            self.assertTrue(CACHE.eligible(argv, cfg, period))
        with mock.patch.dict(os.environ, LM_COPILOT_STUB="synthetic"):
            self.assertTrue(CACHE.eligible(ARGS, {"owner": "x"}, PERIOD))

    def test_placeholder_and_file_budget_decline_before_content_open(self):
        path = self.root / "data/manual/work.csv"
        info = SimpleNamespace(st_file_attributes=0x1000, st_size=1024)
        with mock.patch.object(CACHE, "_linked", return_value=False), mock.patch.object(Path, "stat", return_value=info), mock.patch("builtins.open", side_effect=AssertionError("must not hydrate placeholder")):
            with self.assertRaises(CACHE.Uncertain):
                CACHE._digest(path, [10, 100000])
        with mock.patch("builtins.open", side_effect=AssertionError("must not exceed budget")):
            with self.assertRaises(CACHE.Uncertain):
                CACHE._digest(path, [0, 100000])

    def test_run_main_cache_hit_zero_processes_force_and_miss_continue(self):
        self.save()
        tree = ast.parse((APP / "run.py").read_text(encoding="utf-8-sig"))
        chosen = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in ("main", "arg", "record")]
        scope = {"ROOT": str(self.root), "RUN": {"old": True}, "_ACTIVE_CACHE": None, "_CAPTURE_RESULTS": {},
                 "cfg": lambda: {"owner": "Synthetic"}, "date": date, "os": os, "time": CACHE.time,
                 "sys": sys, "json": json}
        fake_process = SimpleNamespace(Popen=mock.Mock(side_effect=RuntimeError("synthetic analysis boundary")),
                                       run=mock.Mock(side_effect=AssertionError("unexpected process")), PIPE=-1, STDOUT=-2)
        scope["subprocess"] = fake_process
        exec(compile(ast.Module(body=chosen, type_ignores=[]), "run-main-synthetic", "exec"), scope)
        with mock.patch.dict(sys.modules, {"run_cache": CACHE}), mock.patch.object(sys, "argv", ["run.py", *ARGS]), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(scope["main"](), 0)
            self.assertTrue(scope["RUN"]["reused_complete"])
            self.assertNotIn("old", scope["RUN"])
            fake_process.Popen.assert_not_called()
            fake_process.run.assert_not_called()
            sys.argv.append("--force")
            with self.assertRaisesRegex(RuntimeError, "synthetic analysis boundary"):
                scope["main"]()
            self.assertEqual(fake_process.Popen.call_count, 1)
            self.assertNotIn("reused_complete", scope["RUN"])
            sys.argv.remove("--force")
            self.write("data/new.csv", "new\n")
            with self.assertRaisesRegex(RuntimeError, "synthetic analysis boundary"):
                scope["main"]()
            self.assertEqual(fake_process.Popen.call_count, 2)

    def test_run_wires_all_four_observers_then_reuses_synthetic_completed_run(self):
        tree = ast.parse((APP / "run.py").read_text(encoding="utf-8-sig"))
        chosen = [n for n in tree.body if isinstance(n, ast.FunctionDef)
                  and n.name in ("main", "arg", "record", "run_ai_stage", "finish_run")]
        receipts = {stage: CACHE._json(path) for stage, path in self.session.receipts.items()}
        invoked = []
        scope = {"ROOT": str(self.root), "RUN": {}, "_ACTIVE_CACHE": None, "_CAPTURE_RESULTS": {},
                 "cfg": lambda: {"owner": "Synthetic"}, "date": date, "os": os, "time": CACHE.time,
                 "sys": sys, "json": json, "invalidate_ai_outputs": lambda *_: ([], []),
                 "agentic_recalc_inproc": lambda *_: True}

        def capture(command, _env):
            if "--observe" in command:
                stage, path = command[3:5]
                invoked.append(stage)
                CACHE._atomic(path, receipts[stage])
                if stage in ("agentic.py", "flow.py"):
                    self.assertIn("--redo", command)
            else:
                self.assertEqual(Path(command[1]).name, "freeze.py")
                scope["_CAPTURE_RESULTS"]["freeze.py"] = {"rc": 0, "summary": self.frozen}
            return 0, ""

        # A stand-in simulates successful child results using prepared TEMP output.
        # It never imports any product main module or starts any child process.
        fake_process = SimpleNamespace(
            Popen=mock.Mock(return_value=SimpleNamespace(stdout=[], wait=lambda: 0)),
            run=mock.Mock(return_value=SimpleNamespace(returncode=0, stdout=b"", stderr=b"")), PIPE=-1, STDOUT=-2)
        scope.update(subprocess=fake_process, _run_capture=capture)
        exec(compile(ast.Module(body=chosen, type_ignores=[]), "run-wiring-synthetic", "exec"), scope)
        with mock.patch.dict(sys.modules, {"run_cache": CACHE}), mock.patch.object(sys, "argv", ["run.py", *ARGS]), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(scope["main"](), 0)
            self.assertTrue(scope["RUN"]["complete_cache"]["saved"], scope["RUN"]["complete_cache"])
            self.assertEqual(invoked, list(CACHE.STAGES))
            self.assertEqual(scope["main"](), 0)
            self.assertTrue(scope["RUN"]["reused_complete"])
            self.assertEqual(len(invoked), 4)
            self.assertEqual(fake_process.Popen.call_count, 1)
            self.assertEqual(fake_process.run.call_count, 1)


class ReplyTests(unittest.TestCase):
    def reply(self, obj, **extra):
        return {"ok": True, "phase": "replied", "sentinel": True, "cut": False, "model": "live-model",
                "reply": json.dumps(obj, ensure_ascii=False) + "\n[[전송끝]]", **extra}

    def test_scoped_work_ids_and_processed_acknowledgements(self):
        work = "work_" + "a" * 24
        prompt = AGENTIC_PROMPT.replace("· Synthetic project /", f"· [{work}] Synthetic project /")
        item = {"task": "SYN-1", "fit": 60, "reason": "Synthetic evidence", "work_ids": [work]}
        response = {"match": [item], "new": [], "misassigned": [], "processed_ids": [work]}
        self.assertTrue(CACHE.inspect_reply("agentic.py", prompt, "ag", self.reply(response)))
        lowercase = {**response, "match": [{**item, "task": "task-a"}]}
        self.assertTrue(CACHE.inspect_reply("agentic.py", prompt.replace("SYN-1", "task-a"), "ag", self.reply(lowercase)))
        for processed in ([], [work, work], ["work_" + "b" * 24]):
            self.assertFalse(CACHE.inspect_reply("agentic.py", prompt, "ag", self.reply({**response, "processed_ids": processed})))
        for bad in ({**item, "work_ids": ["work_" + "b" * 24]}, {**item, "task": []}, {**item, "fit": True}):
            self.assertFalse(CACHE.inspect_reply("agentic.py", prompt, "ag", self.reply({**response, "match": [bad]})))

    def test_flow_evidence_is_scoped_to_its_unit(self):
        u1, u2 = "unit_" + "a" * 24, "unit_" + "b" * 24
        s1, s2 = "sig_" + "1" * 24, "sig_" + "2" * 24
        prompt = f"## Alpha / work [unit_id={u1}]\n- [{s1}] Synthetic\n## Beta / work [unit_id={u2}]\n- [{s2}] Synthetic"
        flows = [{"unit_id": u, "steps": [{"name": "Work", "agent": "상", "evidence_ids": [s]}]} for u, s in ((u1, s1), (u2, s2))]
        response = {"flows": flows, "processed_ids": [u1, u2]}
        self.assertTrue(CACHE.inspect_reply("flow.py", prompt, "flow", self.reply(response)))
        flows[0]["steps"][0]["evidence_ids"] = [s2]
        self.assertFalse(CACHE.inspect_reply("flow.py", prompt, "flow", self.reply(response)))

    def test_exact_json_coverage_and_unknown_work_flags(self):
        prompt = "#0 | a\n#1 | b\n"
        work = [0, "y", "Synthetic", "개발", "Synthetic work"]
        self.assertTrue(CACHE.inspect_reply("judge.py", prompt, "chunk1", self.reply({"j": [work, [1, "n"]]})))
        for rows in ([[0, "y"]], [[0, "y"], [1, "UNSURE"]], [[0, "y"], [0, "n"]]):
            self.assertFalse(CACHE.inspect_reply("judge.py", prompt, "chunk1", self.reply({"j": rows})))
        valid = self.reply({"j": [work, [1, "n"]]})
        for extra in ({"cut": True}, {"phase": "stub"}, {"model": "stub"}, {"ok": False},
                      {"sentinel": False}, {"reply": '{"j":[[0,"y"]'}, {"retry": 1}):
            self.assertFalse(CACHE.inspect_reply("judge.py", prompt, "chunk1", {**valid, **extra}))

    def test_refine_missing_item_and_flow_unknown_agent_decline(self):
        prompt = "  #0 first\n  #1 second\n## #0 evidence"
        item = {"m": [0, 1], "w": True, "l1": "신제품개발", "l2": "Synthetic", "l3": "Work", "d": "Description"}
        self.assertTrue(CACHE.inspect_reply("refine.py", prompt, "x", self.reply({"items": [item]})))
        self.assertFalse(CACHE.inspect_reply("refine.py", prompt, "x", self.reply({"items": [{"m": [0], "w": True}]})))
        overlap = "  #0 (겹침·참고) first\n  #1 second"
        self.assertTrue(CACHE.inspect_reply("refine.py", overlap, "x", self.reply({"items": [{**item, "m": [1]}]})))
        self.assertFalse(CACHE.inspect_reply("flow.py", "", "flow1", self.reply({"flows": [{"steps": [{"agent": "unknown"}]}]})))
        self.assertFalse(CACHE.inspect_reply("agentic.py", "", "ag1", self.reply({"match": [], "new": []})))

    def test_agentic_valid_empty_and_populated_arrays(self):
        empty = {"match": [], "new": [], "misassigned": []}
        self.assertTrue(CACHE.inspect_reply("agentic.py", AGENTIC_PROMPT, "agentic", self.reply(empty)))
        obj = {"match": [{"task": "SYN-1", "fit": 50, "work": ["Synthetic work"], "reason": "Synthetic reason"}],
               "new": [{"name": "Candidate", "logic": "Synthetic logic", "reason": "Synthetic reason",
                        "work": ["Synthetic project/Synthetic work"]}],
               "misassigned": [{"row": "Synthetic project / Synthetic work", "reason": "Synthetic reason"}]}
        self.assertTrue(CACHE.inspect_reply("agentic.py", AGENTIC_PROMPT, "agentic", self.reply(obj)))

    def test_agentic_rejects_bad_elements_missing_values_and_unknown_references(self):
        empty = {"match": [], "new": [], "misassigned": []}
        valid = {"match": {"task": "SYN-1", "fit": 50, "work": ["Synthetic work"], "reason": "Synthetic reason"},
                 "new": {"name": "Candidate", "logic": "Synthetic logic", "reason": "Synthetic reason", "work": ["Synthetic work"]},
                 "misassigned": {"row": "Synthetic project/Synthetic work", "reason": "Synthetic reason"}}
        for kind, item in valid.items():
            for bad in (123, None, [], "text", {}, *({k: v for k, v in item.items() if k != field} for field in item)):
                with self.subTest(kind=kind, bad=bad):
                    self.assertFalse(CACHE.inspect_reply("agentic.py", AGENTIC_PROMPT, "agentic", self.reply({**empty, kind: [bad]})))
            for field in item:
                for value in (None, "", "  ", "<placeholder>", [], {}):
                    with self.subTest(kind=kind, field=field, value=value):
                        bad = {**item, field: value}
                        self.assertFalse(CACHE.inspect_reply("agentic.py", AGENTIC_PROMPT, "agentic", self.reply({**empty, kind: [bad]})))
        for field, value in (("task", "UNKNOWN"), ("fit", True), ("fit", -1), ("fit", 0), ("fit", 0.5),
                             ("fit", 101), ("fit", "50"), ("fit", float("nan")), ("fit", float("inf")),
                             ("work", [123]), ("work", ["<placeholder>"]), ("work", ["unlisted work"])):
            with self.subTest(field=field, value=value):
                bad = {**valid["match"], field: value}
                self.assertFalse(CACHE.inspect_reply("agentic.py", AGENTIC_PROMPT, "agentic", self.reply({**empty, "match": [bad]})))
        self.assertFalse(CACHE.inspect_reply("agentic.py", AGENTIC_PROMPT, "agentic", self.reply(
            {**empty, "misassigned": [{**valid["misassigned"], "row": "unlisted/work"}]})))

    def test_observer_preserves_return_stdout_and_exceptions_without_app_import(self):
        root = Path(tempfile.mkdtemp(prefix="lm25-observer-test-"))
        receipt = root / "report/.run_cache/receipts/test/judge.json"
        result = self.reply({"j": [[0, "y", "Synthetic", "개발", "Synthetic work"]]})
        sender = mock.Mock(return_value=result)
        module = SimpleNamespace(copilot_send=sender)

        def main():
            self.assertIs(module.copilot_send("#0 | synthetic", "tag", "chunk1"), result)
            print('{"ok":true}')
            return 0

        module.main = main
        out = io.StringIO()
        with mock.patch.object(CACHE.importlib, "import_module", return_value=module), mock.patch.object(sys, "path", list(sys.path)), mock.patch.object(sys, "argv", []), contextlib.redirect_stdout(out):
            self.assertEqual(CACHE.observe_stage(root, "judge.py", receipt, []), 0)
        self.assertEqual(out.getvalue(), '{"ok":true}\n')
        self.assertIs(module.copilot_send, sender)
        self.assertTrue(CACHE._json(receipt)["safe"])
        self.assertEqual(CACHE._json(receipt)["calls"], 1)
        module.main = mock.Mock(side_effect=RuntimeError("synthetic stage failure"))
        with mock.patch.object(CACHE.importlib, "import_module", return_value=module), mock.patch.object(sys, "path", list(sys.path)), mock.patch.object(sys, "argv", []):
            with self.assertRaisesRegex(RuntimeError, "synthetic stage failure"):
                CACHE.observe_stage(root, "judge.py", receipt, [])
        self.assertFalse(CACHE._json(receipt)["safe"])
        self.assertEqual(CACHE._json(receipt)["rc"], 1)


if __name__ == "__main__":
    unittest.main()
