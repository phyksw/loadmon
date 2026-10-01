"""Real readiness/status/diagnostic functions; TEMP code and virtual CDP only."""
import ast
import contextlib
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
from unittest.mock import patch


PRODUCT = Path(__file__).resolve().parents[1] / "LoadMonitor25"
PERIOD = ["2026-09-01", "2026-09-30"]


class BrowserStageDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory(prefix="lm25-browser-diagnostics-")))
        self.stack.enter_context(patch.object(sys, "path", list(sys.path)))
        self.stack.enter_context(patch.dict(sys.modules))
        for name in ("collection_state", "collection_diagnostics", "communication_archive", "communication_context"):
            sys.modules.pop(name, None)
            dest = self.root / "core" / (name + ".py")
            dest.parent.mkdir(exist_ok=True)
            shutil.copyfile(PRODUCT / "core" / dest.name, dest)
        sys.path.insert(0, str(self.root / "core"))
        self.diag = self.load("diagnostic_fixture", "core/collection_diagnostics.py")
        self.modules = {}
        for family, name in (("mail", "Get-OutlookWeb.py"), ("teams", "Get-TeamsWeb.py")):
            dest = self.root / "collect" / name
            dest.parent.mkdir(exist_ok=True)
            shutil.copyfile(PRODUCT / "collect" / name, dest)
            self.modules[family] = self.load("browser_" + family + "_fixture", "collect/" + name)

    def load(self, name, path):
        spec = importlib.util.spec_from_file_location(name, self.root / path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    @contextlib.contextmanager
    def virtual_clock(self, module, clock):
        with patch.object(module.time, "monotonic", side_effect=lambda: clock[0]), \
                patch.object(module.time, "sleep", side_effect=lambda sec: clock.__setitem__(0, clock[0] + sec)), \
                patch.object(module, "log"):
            yield

    def browser(self, family, clock, login_until=0, budget=180, error=None):
        module = self.modules[family]
        browser = module.Browser.__new__(module.Browser)
        browser.deadline, browser.last_diagnostic = budget, ""
        browser._ready_once = False
        url = module.MAIL_URL if family == "mail" else module.TEAMS_URL

        def evaluate(script, timeout=0):
            self.assertGreater(timeout, 0)
            self.assertLessEqual(timeout, budget - clock[0] + 1e-8)
            if script == "location.href":
                return "https://login.microsoftonline.com/PRIVATE-TENANT?token=SECRET" if clock[0] < login_until else url
            if error is not None:
                raise error
            return json.dumps({"items": [{"body": "PRIVATE-BODY"}], "chats": 1, "messages": 2})
        browser.cdp = SimpleNamespace(eval=evaluate)
        return browser

    def test_first_login_can_finish_after_old_limits_in_both_real_wait_loops(self):
        for family in self.modules:
            for delay in (40, 60):
                with self.subTest(family=family, delay=delay):
                    clock = [0.0]
                    browser = self.browser(family, clock, login_until=delay)
                    with self.virtual_clock(self.modules[family], clock):
                        self.assertEqual(browser.wait_ready(), "ok")
                    self.assertGreaterEqual(clock[0], delay)
                    self.assertLess(clock[0], delay + 1)
                    self.assertEqual(browser.last_diagnostic, "ready")
                    self.assertEqual(browser.observation["phase"], "surface_ready")
                    self.assertTrue(browser.observation["login_seen"])
                    self.assertTrue(browser.observation["ready_seen"])
                    self.assertNotIn("PRIVATE", json.dumps(browser.observation))

    def test_login_wait_never_extends_route_deadline_and_is_capped_at_120(self):
        for family in self.modules:
            for budget, expected in ((0.5, 0.5), (30, 30), (180, 120)):
                with self.subTest(family=family, budget=budget):
                    clock = [0.0]
                    browser = self.browser(family, clock, login_until=1000, budget=budget)
                    with self.virtual_clock(self.modules[family], clock):
                        self.assertEqual(browser.wait_ready(), "login")
                    self.assertAlmostEqual(clock[0], expected, places=5)
                    self.assertEqual(browser.last_diagnostic, "login_required")
                    self.assertFalse(browser.observation.get("ready_seen", False))

    def test_script_exceptions_survive_main_status_and_sanitized_export(self):
        for family, module in self.modules.items():
            with self.subTest(family=family):
                clock = [0.0]
                browser = self.browser(family, clock, budget=5, error=RuntimeError("JS PRIVATE-BODY token=SECRET"))
                browser.start = lambda: True
                browser.close = lambda: None
                browser.cdp.call = lambda *args, **kwargs: {}
                argv = ["collector", "--from", PERIOD[0], "--to", PERIOD[1], "--budget", "5"]
                if family == "mail":
                    argv += ["--only", "mail", "--exclude-body"]
                with self.virtual_clock(module, clock), patch.object(module, "Browser", return_value=browser), \
                        patch.object(sys, "argv", argv), \
                        patch.dict(os.environ, {"LM_NO_BROWSER": "", "LM_OWA_FAKE": "", "LM_TEAMSWEB_FAKE": ""}), \
                        contextlib.redirect_stdout(io.StringIO()):
                    code = module.main()
                self.assertNotEqual(code, 0)
                status = json.loads((self.root / "data/collection_status" / ("outlook_web.json" if family == "mail" else "teams_web.json")).read_text(encoding="utf-8"))
                self.assertIn("page_evaluation_failed", status["reasons"])
                self.assertEqual(status["browser"]["last_error"], "RuntimeError")
                self.assertGreater(status["browser"]["page_errors"], 0)
                output = self.diag.build_diagnostics(self.root, *PERIOD, {"started_at": 0})
                route = next(row for row in output["routes"] if row["source"] == status["source"])
                self.assertIn("page_evaluation_failed", route["causes"])
                self.assertEqual(route["browser"]["last_error"], "RuntimeError")
                self.assertFalse(route["browser"].get("ready_seen", False))
                self.assertNotIn("PRIVATE", json.dumps(output))
                self.assertNotIn("SECRET", json.dumps(output))

    def test_startup_timeout_before_route_deadline_exports_connection_failure(self):
        for family, module in self.modules.items():
            with self.subTest(family=family):
                clock = [0.0]
                browser = self.browser(family, clock, budget=180)
                browser.close = lambda: None

                def fail_start():
                    self.diag.observe_browser(browser, "starting")
                    raise TimeoutError("PRIVATE url https://example.invalid/?token=SECRET")
                browser.start = fail_start
                with self.virtual_clock(module, clock), patch.object(module, "Browser", return_value=browser), \
                        patch.object(sys, "argv", ["collector", "--from", PERIOD[0], "--to", PERIOD[1], "--budget", "180"]), \
                        patch.dict(os.environ, {"LM_NO_BROWSER": "", "LM_OWA_FAKE": "", "LM_TEAMSWEB_FAKE": ""}), \
                        contextlib.redirect_stdout(io.StringIO()):
                    self.assertNotEqual(module.main(), 0)
                output = self.diag.build_diagnostics(self.root, *PERIOD, {"started_at": 0})
                route = next(row for row in output["routes"] if row["source"] == ("outlook_web" if family == "mail" else "teams_web"))
                self.assertEqual(route["browser"]["phase"], "failed")
                self.assertEqual(route["browser"]["last_error"], "TimeoutError")
                self.assertIn("browser_unavailable", route["causes"])
                self.assertNotIn("budget_reached", route["causes"])
                self.assertNotIn("PRIVATE", json.dumps(output))
                self.assertNotIn("SECRET", json.dumps(output))

    def test_browser_observation_retains_only_labels_booleans_and_counts(self):
        browser = SimpleNamespace(observation={"url": "PRIVATE", "items": -1, "messages": True})
        self.diag.observe_browser(browser, "waiting_login", href="https://login.microsoftonline.com/PRIVATE?token=SECRET")
        self.diag.observe_browser(browser, "waiting_surface", page={"items": ["PRIVATE"] * 3,
            "chats": 2, "messages": -1, "loading": True, "html": "PRIVATE", "listboxes": True},
            error=ConnectionError("SECRET"))
        self.assertEqual(browser.observation, {"phase": "waiting_surface", "surface": "login", "login_seen": True,
            "page_checks": 1, "items": 3, "chats": 2, "loading": True, "page_errors": 1, "last_error": "ConnectionError"})
        self.diag.observe_browser(browser, "surface_ready", href="https://teams.microsoft.com/v2/?token=SECRET")
        self.assertEqual(browser.observation["surface"], "teams")
        self.assertTrue(browser.observation["ready_seen"])
        self.assertNotIn("last_error", browser.observation)
        self.assertEqual(self.diag.browser_snapshot({"phase": "PRIVATE", "surface": "PRIVATE", "last_error": "SECRET",
            "page_errors": float("nan"), "page_checks": True, "items": 10**12, "url": "PRIVATE", "empty": "yes"}), {})

    def test_evidence_period_matching_and_strict_numeric_whitelist(self):
        values = {"raw_rows": 7, "in_period_rows": 0, "unique_rows": 0, "unknown_date_rows": 2,
                  "unreadable_files": 1, "context_rows": True, "pending_rows": -1, "files": "3",
                  "web_body_observed_rows": 3, "web_body_partial_rows": 2, "subject": "PRIVATE",
                  "body": "SECRET", "source_url": "https://example.invalid/PRIVATE"}
        evidence = {"period": PERIOD, "families": {"mail": values, "teams": values}, "mail_time_offset_hours": 9}
        output = self.diag.build_diagnostics(self.root, *PERIOD, {"communication_evidence": evidence})
        self.assertEqual(output["saved_evidence"]["mail"], {"raw_rows": 7, "in_period_rows": 0, "unique_rows": 0,
            "unknown_date_rows": 2, "unreadable_files": 1, "web_body_observed_rows": 3, "web_body_partial_rows": 2})
        self.assertEqual(output["date_settings"], {"mail_time_offset_hours": 9})
        self.assertTrue(any("시간 보정" in text for text in output["summary"]))
        self.assertNotIn("PRIVATE", json.dumps(output))
        self.assertNotIn("SECRET", json.dumps(output))
        for period in (["2026-08-01", "2026-08-31"], None):
            evidence["period"] = period
            output = self.diag.build_diagnostics(self.root, *PERIOD, {"communication_evidence": evidence})
            self.assertEqual(output["saved_evidence"], {})
            self.assertEqual(output["date_settings"], {})
            self.assertFalse(any("시간 보정" in text for text in output["summary"]))

    def test_new_schema_report_downloads_through_actual_handler(self):
        tree = ast.parse((PRODUCT / "ui/app.py").read_text("utf-8-sig"))
        handler = next(item for item in tree.body if isinstance(item, ast.ClassDef) and item.name == "H")
        get = next(item for item in handler.body if isinstance(item, ast.FunctionDef) and item.name == "do_GET")
        report = self.root / "report"
        report.mkdir()
        ns = {"os": os, "json": json, "REPORT": str(report)}
        exec(compile(ast.Module(body=[get], type_ignores=[]), "real-ui-get", "exec"), ns)
        sent = []
        request = SimpleNamespace(path="/api/communication/diagnostics", _send=lambda *args, **kwargs: sent.append((args, kwargs)))
        for schema, status in ((1, 200), (2, 200), (3, 404)):
            (report / "communication_diagnostics.json").write_text(json.dumps({"schema": schema, "includes_message_content": False}))
            ns["do_GET"](request)
            self.assertEqual(sent[-1][0][0], status)
        (report / "communication_diagnostics.json").write_text(json.dumps({"schema": 2, "includes_message_content": True}))
        ns["do_GET"](request)
        self.assertEqual(sent[-1][0][0], 404)


if __name__ == "__main__":
    unittest.main()
