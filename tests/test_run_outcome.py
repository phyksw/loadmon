"""Run outcome/collector selection with injected I/O, no actual collectors."""
import ast
import contextlib
from datetime import date
import io
import os
from pathlib import Path
from types import SimpleNamespace
import time
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "LoadMonitor25" / "run.py"


def environment():
    env = {"RUN": {"stages": [], "ai_requested": True}, "time": time, "_CAPTURE_RESULTS": {},
           "date": date, "os": os, "ROOT": "SYNTHETIC_ROOT"}
    def record(name, ok, sec=0, note=""):
        env["RUN"]["stages"].append({"name": name, "ok": ok, "note": note})
    env["record"] = record
    tree = ast.parse(SOURCE.read_text(encoding="utf-8-sig"))
    body = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in {"finish_run", "main", "arg"}]
    exec(compile(ast.Module(body=body, type_ignores=[]), str(SOURCE), "exec"), env)
    return env


class RunOutcomeTests(unittest.TestCase):
    def test_missing_configured_share_never_falls_back_or_starts_server(self):
        source = SOURCE.with_name("teamserver.py")
        tree = ast.parse(source.read_text(encoding="utf-8-sig"))
        body = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in {"_share_root", "main"}]
        selected = "SYNTHETIC_MISSING_SHARE"
        def forbidden(*args):
            self.fail("missing shared folder must not start a server")
        env = {"os": os, "ROOT": "SYNTHETIC_ROOT", "_cfg": lambda: {"teamShareDir": selected},
               "PORT": [0], "arg": lambda *args: "0", "_cfg_port": lambda: 9310,
               "ThreadingHTTPServer": forbidden}
        exec(compile(ast.Module(body=body, type_ignores=[]), str(source), "exec"), env)
        self.assertEqual(env["_share_root"](), selected)
        env["TEAMDATA"] = selected
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(env["main"](), 2)

    def test_complete_partial_failed_are_distinct(self):
        for stages, available, status, code in (([True, True], True, "complete", 0),
                                                ([True, False], True, "partial", 2),
                                                ([False, False], False, "failed", 1)):
            env = environment()
            env["RUN"]["stages"] = [{"name": str(i), "ok": value} for i, value in enumerate(stages)]
            with contextlib.redirect_stdout(io.StringIO()):
                result = env["finish_run"](available)
            self.assertEqual((result, env["RUN"]["status"]), (code, status))

    def test_ai_not_requested_is_not_a_failure(self):
        env = environment()
        env["RUN"].update(ai_requested=False, stages=[{"name": "업무 로드 추출", "ok": True},
                                                     {"name": "AI 판정", "ok": False}])
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(env["finish_run"](True), 0)

    def test_no_teams_disables_all_teams_routes_and_failed_collection_is_not_success(self):
        env = environment()
        called = []
        def step(name, command, timeout):
            called.append(command)
            env["record"](name, False)
            return False
        env.update(sys=SimpleNamespace(argv=["run.py", "--collect-only", "--no-teams"], executable="SYNTHETIC"),
                   cfg=lambda: {"graph": {"clientId": "synthetic"}, "teamsWeb": True}, step=step,
                   archive_other_pc=lambda data: True, ensure_sampler=lambda *args: None,
                   collect_outlook=lambda *args: None, mail_fallbacks=lambda *args: None)
        with contextlib.redirect_stdout(io.StringIO()):
            result = env["main"]()
        self.assertEqual(result, 1)
        self.assertEqual(env["RUN"]["status"], "failed")
        self.assertTrue(called)
        self.assertFalse(any("Teams" in str(command) for command in called))


if __name__ == "__main__":
    unittest.main()
