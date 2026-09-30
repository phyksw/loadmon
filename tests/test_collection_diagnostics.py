"""Saved-result diagnostics and launcher handoff using only synthetic TEMP data."""
import ast
import csv
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest import mock


APP = Path(__file__).resolve().parents[1] / "LoadMonitor25"


class DiagnosticTests(unittest.TestCase):
    def test_saved_only_counts_multiline_rows_without_reading_accounts(self):
        with tempfile.TemporaryDirectory(prefix="lm25-saved-diag-") as td:
            root = Path(td)
            collector = root / "collect" / "Diagnose-Collectors.ps1"
            collector.parent.mkdir()
            shutil.copyfile(APP / "collect" / collector.name, collector)
            mail = root / "data" / "outlook" / "mail.csv"
            mail.parent.mkdir(parents=True)
            with mail.open("w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=["time", "subject", "context_excerpt"])
                writer.writeheader()
                writer.writerow({"time": "2026-06-03 09:00", "subject": "SECRET-SUBJECT",
                                 "context_excerpt": "SECRET-BODY\nsecond line"})
            status = root / "data" / "collection_status" / "teams_app.json"
            status.parent.mkdir()
            status.write_text(json.dumps({"status": "partial", "rows": 0,
                "requested_from": "2026-06-01", "requested_to": "2026-06-30",
                "reasons": ["date_unconfirmed"], "parsed_messages": 5,
                "period_excluded": 0, "date_unconfirmed": 5}), encoding="utf-8")
            report = root / "report"
            report.mkdir()
            (report / "last_run.json").write_text(json.dumps({"period": ["2026-06-01", "2026-06-30"],
                "stages": [{"name": "Teams 보충 · 열린 앱", "ok": False, "note": "SECRET-NOTE"}]}), encoding="utf-8")
            result = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                                     str(collector), "-SavedOnly"], capture_output=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
            output = (report / "collect_diag.txt").read_text("utf-8-sig")
            self.assertIn("mail.csv: 1건", output)
            self.assertIn("date_unconfirmed: 5", output)
            self.assertIn("Teams 보충 · 열린 앱: 미완료", output)
            self.assertNotIn("SECRET-", output)
            self.assertNotIn("[환경]", output)
            self.assertEqual(list((root / "data" / "outlook").iterdir()), [mail])

    def test_both_collect_runner_paths_forward_current_python(self):
        tree = ast.parse((APP / "run.py").read_text("utf-8-sig"))
        body = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in {"step", "_run_rc"}]
        with tempfile.TemporaryDirectory(prefix="lm25-python-handoff-") as td:
            child = mock.Mock(return_value=SimpleNamespace(returncode=0, stdout=b"OK", stderr=b""))
            streaming = mock.Mock(return_value={"returncode": 0, "tail": ["OK"], "timed_out": False})
            ns = {"subprocess": SimpleNamespace(run=child, TimeoutExpired=subprocess.TimeoutExpired),
                  "os": os, "sys": sys, "time": time, "ROOT": td, "NO_WIN": 0,
                  "record": mock.Mock(), "print": mock.Mock()}
            exec(compile(ast.Module(body=body, type_ignores=[]), "synthetic-run.py", "exec"), ns)
            with mock.patch.dict(os.environ, {"LM_PYTHON_EXE": "stale-python-path"}), \
                    mock.patch.dict(sys.modules, {"collection_process": SimpleNamespace(run_stream=streaming)}):
                self.assertTrue(ns["step"]("synthetic", ["never-started"], 10))
                self.assertEqual(ns["_run_rc"](["never-started"], 10)[0], 0)
            self.assertEqual(child.call_count, 1)
            self.assertEqual(streaming.call_count, 1)
            for call in [*child.call_args_list, *streaming.call_args_list]:
                self.assertEqual(call.kwargs["env"]["LM_PYTHON_EXE"], sys.executable)
                self.assertEqual(call.kwargs["cwd"], td)


if __name__ == "__main__":
    unittest.main()
