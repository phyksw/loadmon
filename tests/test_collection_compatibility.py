"""Capability routing/diagnostics/deadlines, with synthetic registry and files."""
import ast
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest import mock

APP = Path(__file__).resolve().parents[1] / "LoadMonitor25"
sys.path.insert(0, str(APP / "core"))
import collection_diagnostics as D  # noqa: E402
from collection_state import write_status  # noqa: E402


class FakeRegistry:
    KEY_READ, KEY_WOW64_64KEY, KEY_WOW64_32KEY = 1, 2, 4
    HKEY_CLASSES_ROOT, HKEY_CURRENT_USER = "classes", "user"

    def __init__(self, registered=True, profile_version=None, denied=False):
        self.registered, self.profile_version, self.denied = registered, profile_version, denied

    def OpenKey(self, hive, path, *args):
        if self.denied:
            raise PermissionError("synthetic permission")
        if (hive == "classes" and self.registered) or (self.profile_version and self.profile_version in path):
            return mock.MagicMock()
        raise FileNotFoundError(path)

    def EnumKey(self, key, index):
        return "DO_NOT_EXPORT_PROFILE_NAME"


class CompatibilityTests(unittest.TestCase):
    def test_capability_checks_accept_classic_365_and_older_profiles_without_activation(self):
        for version in ("16.0", "15.0", "14.0", "Windows Messaging Subsystem"):
            self.assertEqual(D.outlook_capability(FakeRegistry(profile_version=version)),
                             {"oom_registered": True, "classic_profile": True})
        self.assertEqual(D.outlook_capability(FakeRegistry(registered=False)),
                         {"oom_registered": False, "classic_profile": False})
        self.assertEqual(D.outlook_capability(FakeRegistry(denied=True)),
                         {"oom_registered": None, "classic_profile": None})

    def test_missing_com_or_profile_does_not_launch_outlook_and_unknown_still_attempts(self):
        tree = ast.parse((APP / "run.py").read_text("utf-8-sig"))
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "collect_outlook")
        with tempfile.TemporaryDirectory(prefix="lm25-native-route-") as td:
            calls = []
            ns = {"ROOT": td, "RUN": {}, "time": time, "os": os, "record": lambda *a: None,
                  "print": lambda *a, **k: None, "step": lambda *a: calls.append(a) or False,
                  "_outlook_budget": lambda *a: 30, "_mtime": lambda *a: None, "_read_json": lambda *a: {}}
            exec(compile(ast.Module(body=[node], type_ignores=[]), "synthetic-run", "exec"), ns)
            for caps, expect_call in (
                ({"oom_registered": False}, False),
                ({"oom_registered": True, "classic_profile": False, "client_probe": "observed_running_processes_only",
                  "running_clients": [{"name": "olk", "version": "1.2"}]}, False),
                ({"oom_registered": None, "classic_profile": None}, True),
                ({"oom_registered": True, "classic_profile": True}, True),
                ({"oom_registered": True, "classic_profile": False, "client_probe": "observed_running_processes_only",
                  "running_clients": [{"name": "outlook", "version": "16.0"}]}, True),
            ):
                calls.clear()
                with mock.patch.object(D, "client_snapshot", return_value=caps):
                    ns["collect_outlook"]({}, "2026-09-01", "2026-09-30", td, [], "synthetic")
                self.assertEqual(bool(calls), expect_call, caps)

    def test_diagnostics_export_contains_no_content_logs_paths_or_accounts_and_marks_stale(self):
        with tempfile.TemporaryDirectory(prefix="lm25-compat-diag-") as td:
            started = time.time()
            write_status(td, "outlook_web", "2026-09-01", "2026-09-30", "blocked",
                         reasons=["login_required", "SECRET_BODY user@example.invalid"],
                         raw_body="SECRET_BODY", account="user@example.invalid", elapsed_sec=12.5,
                         diagnostics={"mail": {"items": 7, "undated": 5, "raw_body": "SECRET_BODY"}})
            write_status(td, "teams_web", "2026-08-01", "2026-08-31", "failed", reasons=["page_timeout"], rows=7)
            run = {"started_at": started, "client_capabilities": {"oom_registered": False,
                   "running_clients": [{"name": "olk", "version": "1.2026.1"}, {"name": "private", "version": "secret"}]},
                   "stages": [{"name": "Outlook 보충 · 웹", "ok": False, "sec": 12.5, "note": "SECRET_BODY"}]}
            result = D.write_diagnostics(td, "2026-09-01", "2026-09-30", run)
            serialized = json.dumps(result)
            for secret in ("SECRET_BODY", "user@example.invalid", "private", td):
                self.assertNotIn(secret, serialized)
            mail, teams = result["routes"]
            self.assertTrue(mail["current_run"])
            self.assertFalse(teams["current_run"])
            self.assertFalse(teams["matches_period"])
            self.assertEqual(mail["counters"]["elapsed_sec"], 12.5)
            self.assertEqual(mail["counters"]["mail_items"], 7)
            self.assertEqual(mail["counters"]["mail_undated"], 5)
            self.assertIn("로그인 필요", result["summary"][0])
            self.assertNotIn("화면 준비 실패", " ".join(result["summary"]))
            self.assertFalse(result["includes_message_content"])
            self.assertEqual(D.build_diagnostics(td, "2026-09-01", "2026-09-30", {})["summary"], [])

            ui = ast.parse((APP / "ui/app.py").read_text("utf-8-sig"))
            handler_class = next(n for n in ui.body if isinstance(n, ast.ClassDef) and n.name == "H")
            get = next(n for n in handler_class.body if isinstance(n, ast.FunctionDef) and n.name == "do_GET")
            namespace = {"os": os, "json": json, "REPORT": str(Path(td) / "report")}
            exec(compile(ast.Module(body=[get], type_ignores=[]), "synthetic-diag-download", "exec"), namespace)
            replies = []
            handler = SimpleNamespace(path="/api/communication/diagnostics",
                                      _send=lambda *a, **kw: replies.append((a, kw)))
            namespace["do_GET"](handler)
            self.assertEqual(replies[0][0], (200, result))
            self.assertIn("attachment", replies[0][1]["headers"]["Content-Disposition"])
            Path(td, "report/communication_diagnostics.json").unlink()
            namespace["do_GET"](handler)
            self.assertEqual(replies[-1][0][0], 404)

    def test_edge_startup_has_absolute_budget_even_when_probe_accepts_and_stalls(self):
        spec = importlib.util.spec_from_file_location("synthetic_cdp_budget", APP / "tools/copilot_auto.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory(prefix="lm25-browser-budget-") as td:
            for budget in (20, 0.4):
                clock, waits = [0.0], []
                def probe(port, timeout=1):
                    waits.append(timeout)
                    clock[0] += timeout
                    return False
                def sleep(seconds):
                    clock[0] += seconds
                with mock.patch.dict(os.environ, {}, clear=True), \
                        mock.patch.object(module, "debugger_alive", side_effect=probe), \
                        mock.patch.object(module, "find_edge", return_value="FAKE_EDGE"), \
                        mock.patch.object(module.subprocess, "Popen") as launch, \
                        mock.patch.object(module.time, "monotonic", side_effect=lambda: clock[0]), \
                        mock.patch.object(module.time, "sleep", side_effect=sleep):
                    result = module.ensure_edge({"port": 9444, "profileDir": td, "url": "https://example.invalid",
                                                 "_collection_deadline": budget})
                self.assertIsNone(result)
                self.assertLessEqual(clock[0], budget + 0.001)
                self.assertLessEqual(max(waits), 1)
                self.assertEqual(launch.call_count, int(budget > 1))


if __name__ == "__main__":
    unittest.main()
