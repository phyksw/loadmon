"""Isolated UI request and process wiring tests; never import or start the app."""

import ast
import copy
import io
import json
import os
import runpy
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "LoadMonitor25" / "ui" / "app.py"


def definitions(names):
    names = set(names)
    tree = ast.parse(SOURCE.read_text(encoding="utf-8-sig"))
    body = [copy.deepcopy(node) for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    if names & {"do_POST", "do_DELETE"}:
        cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "H")
        body.extend(copy.deepcopy(node) for node in cls.body if isinstance(node, ast.FunctionDef)
                    and node.name in {"do_POST", "_do_POST", "do_DELETE", "_do_DELETE"})
    env = {"json": json, "os": os, "sys": sys, "time": time, "subprocess": subprocess,
           "LOCK": threading.Lock(), "JOB": {"running": False, "phase": ""}, "NO_WIN": 0,
           "REQUEST_LOCK": threading.Lock(), "SAMPLER_RESTART": {"busy": False, "at": 0},
           "threading": SimpleNamespace(), "log": lambda message: None}
    exec(compile(ast.Module(body=body, type_ignores=[]), str(SOURCE), "exec"), env)
    return env


class RunRequestTests(unittest.TestCase):
    def setUp(self):
        self.env = definitions({"validate_run_request", "do_POST", "cancel_transfer"})
        self.started = []
        self.env.update(run_job=lambda *args: None, transfer_job=lambda: None)
        self.env["threading"].Thread = lambda **kwargs: SimpleNamespace(start=lambda: self.started.append(kwargs))

    def post(self, path, value=None):
        raw = json.dumps(value).encode() if value is not None else b""
        replies = []
        handler = SimpleNamespace(path=path, headers={"Content-Length": str(len(raw))}, rfile=io.BytesIO(raw),
                                  _send=lambda *args: replies.append(args), _freezing=lambda: False)
        handler._do_POST = lambda: self.env["_do_POST"](handler)
        self.env["do_POST"](handler)
        return replies

    def test_invalid_json_shape_never_latches_busy(self):
        for payload in ([], "invalid", {"from": "2026-08-31", "to": "2026-08-01"},
                        {"from": "2026-08-01", "to": "2026-08-31", "skip": "false"}):
            with self.subTest(payload=payload):
                self.assertEqual(self.post("/api/run", payload)[0][0], 400)
                self.assertFalse(self.env["JOB"]["running"])
        self.assertEqual(self.started, [])

    def test_collected_analysis_wiring_and_busy_transfer(self):
        payload = {"from": "2026-08-01", "to": "2026-08-31", "ai": True, "skip": True,
                   "reuse_complete": True, "force": False}
        self.assertEqual(self.post("/api/run", payload)[0][0], 200)
        self.assertEqual(self.started[0]["args"], ("2026-08-01", "2026-08-31", True, True, False, True, False))
        self.assertEqual(self.post("/api/transfer")[0][0], 409)
        self.assertEqual(len(self.started), 1)

    def test_transfer_job_starts_once(self):
        self.assertEqual(self.post("/api/transfer")[0][0], 202)
        self.assertEqual(self.env["JOB"]["kind"], "transfer")
        self.assertIs(self.started[0]["target"], self.env["transfer_job"])
        self.assertIs(self.started[0]["daemon"], False)
        self.assertEqual(self.post("/api/transfer")[0][0], 409)

    def test_thread_start_failure_restores_idle(self):
        def fail():
            raise RuntimeError("synthetic thread allocation failure")
        self.env["threading"].Thread = lambda **kwargs: SimpleNamespace(start=fail)
        self.assertEqual(self.post("/api/transfer")[0][0], 503)
        self.assertFalse(self.env["JOB"]["running"])

    def test_transfer_blocks_other_mutations(self):
        self.env["JOB"].update(running=True, kind="transfer")
        for path in ("/api/owa", "/api/teamsweb", "/api/prepmove", "/api/projects", "/api/reset", "/api/diag"):
            with self.subTest(path=path):
                self.assertEqual(self.post(path)[0][0], 409)
        self.assertEqual(self.started, [])

    def test_transfer_cannot_start_during_synchronous_mutation(self):
        with self.env["REQUEST_LOCK"]:
            self.assertEqual(self.post("/api/transfer")[0][0], 409)
        self.assertFalse(self.env["JOB"]["running"])

    def test_transfer_blocks_delete_mutations(self):
        self.env["JOB"].update(running=True, kind="transfer")
        replies = []
        handler = SimpleNamespace(_send=lambda *args: replies.append(args),
                                  _do_DELETE=lambda: self.fail("delete must not run during transfer"))
        self.env["do_DELETE"](handler)
        self.assertEqual(replies[0][0], 409)

    def test_stop_transfer_signals_only_its_worker(self):
        self.env["JOB"].update(running=True, kind="transfer")
        killed = []
        self.env.update(kill_job=lambda: killed.append("process"), kill_copilot_edge=lambda: killed.append("browser"))
        replies = self.post("/api/stop")
        self.assertEqual(replies[0][1]["kind"], "transfer")
        self.assertTrue(self.env["JOB"]["transfer_cancel_requested"])
        self.assertEqual(killed, [])
        self.assertTrue(self.env["JOB"]["running"])

    def test_transfer_waits_for_already_scheduled_sampler(self):
        self.env["SAMPLER_RESTART"]["busy"] = True
        self.assertEqual(self.post("/api/transfer")[0][0], 409)
        self.assertFalse(self.env["JOB"]["running"])
        self.assertEqual(self.started, [])

    def test_all_mutations_reject_non_object_before_work(self):
        for path in ("/api/projects", "/api/sharedir", "/api/exclude", "/api/teamfolder",
                     "/api/reset", "/api/workflow", "/api/agentic", "/api/teamserver"):
            with self.subTest(path=path):
                self.assertEqual(self.post(path, ["invalid"])[0][0], 400)
                self.assertFalse(self.env["JOB"]["running"])
        self.assertEqual(self.started, [])

    def test_workflow_thread_start_failure_does_not_stick(self):
        def fail():
            raise RuntimeError("synthetic start failure")
        self.env["threading"].Thread = lambda **kwargs: SimpleNamespace(start=fail)
        self.env.update(TOOL_JOBS={"flow": ["flow.py", "flow"]}, tool_job=lambda: None)
        self.assertEqual(self.post("/api/workflow", {})[0][0], 503)
        self.assertFalse(self.env["JOB"]["running"])

    def test_prepare_move_starts_one_external_preparation_and_blocks_new_jobs(self):
        with tempfile.TemporaryDirectory(prefix="lm25-prepare-dispatch-") as directory:
            root = Path(directory)
            (root / "tools").mkdir()
            source = root / "tools" / "Prepare-Move.ps1"
            source.write_text("# Synthetic script; never executed", encoding="utf-8-sig")
            calls = []
            self.env.update(ROOT=str(root), subprocess=SimpleNamespace(Popen=lambda command, **kwargs: calls.append(command)))
            try:
                self.assertTrue(self.post("/api/prepmove")[0][1]["started"])
                self.assertEqual(len(calls), 1)
                self.assertEqual(calls[0][-2:], ["-Root", str(root)])
                script = Path(calls[0][calls[0].index("-File") + 1])
                self.assertEqual(script.read_bytes(), source.read_bytes())
                self.assertEqual(self.env["JOB"]["kind"], "prepmove")
                self.assertEqual(self.post("/api/transfer")[0][0], 409)
                self.assertEqual(self.post("/api/projects")[0][0], 409)
            finally:
                if calls:
                    script = Path(calls[0][calls[0].index("-File") + 1])
                    self.assertEqual(script.parent.resolve(), Path(tempfile.gettempdir()).resolve())
                    self.assertTrue(script.name.startswith("LM25-Prepare-Move-"))
                    script.unlink(missing_ok=True)

    def test_prepare_move_does_not_interrupt_an_analysis(self):
        self.env["JOB"].update(running=True, kind="analysis")
        self.assertEqual(self.post("/api/prepmove")[0][0], 409)
        self.assertEqual(self.env["JOB"]["kind"], "analysis")

    def test_narration_receives_the_selected_review_period(self):
        self.env["review_source"] = lambda tag: {"tag": tag, "signals_file": "synthetic.csv"}
        self.env["narrate_job"] = lambda *args: None
        self.assertEqual(self.post("/api/narrate", {"tag": "20260101-20260131"})[0][0], 200)
        self.assertEqual(self.started[0]["args"], ("20260101-20260131",))


class ProcessWiringTests(unittest.TestCase):
    def test_sampler_rechecks_transfer_after_status_snapshot(self):
        env = definitions({"_sampler_autorestart"})
        env.update(ROOT=str(SOURCE.parents[1]), SAMPLER_STALE_MIN=10,
                   cfg=lambda: {}, _cfg_bool=lambda value, fallback: fallback,
                   _sampler_restart_worker=lambda *args: self.fail("worker must not run"))
        env["JOB"].update(running=True, kind="transfer")
        env["threading"].Thread = lambda **kwargs: self.fail("thread must not start")
        self.assertIn("이동 ZIP", env["_sampler_autorestart"](None))
        self.assertFalse(env["SAMPLER_RESTART"]["busy"])

    def test_ui_transfer_library_success_and_cancellation(self):
        create = runpy.run_path(str(SOURCE.parents[1] / "tools" / "transfer.py"))["create_transfer"]
        with tempfile.TemporaryDirectory(prefix="lm25-ui-transfer-library-") as directory:
            root = Path(directory, "app")
            root.mkdir()
            (root / "synthetic.txt").write_bytes(b"preserved")
            for cancel in (False, True):
                with self.subTest(cancel=cancel):
                    env = definitions({"transfer_job", "cancel_transfer"})
                    env["JOB"].update(running=True, kind="transfer")
                    target = Path(directory, "cancelled.zip" if cancel else "complete.zip")

                    def wrapper(app, progress, cancelled):
                        def update(item):
                            progress(item)
                            if cancel:
                                env["cancel_transfer"]()
                        return create(app, output=target, progress=update, cancelled=cancelled)

                    env.update(ROOT=str(root), create_transfer=wrapper)
                    env["transfer_job"]()
                    self.assertEqual(env["JOB"]["transfer_result"]["ok"], not cancel)
                    self.assertEqual(target.exists(), not cancel)
                    self.assertFalse(env["JOB"]["running"])
                    self.assertEqual((root / "synthetic.txt").read_bytes(), b"preserved")
                    self.assertEqual(list(Path(directory).glob(".lm25-transfer-*.tmp")), [])

    def test_collected_analysis_and_collect_only_commands(self):
        env = definitions({"run_job"})
        calls = []

        def popen(command, **kwargs):
            calls.append(command)
            return SimpleNamespace(stdout=io.BytesIO(), pid=123, returncode=0, wait=lambda: 0)
        env.update(ROOT="SYNTHETIC_ROOT", subprocess=SimpleNamespace(Popen=popen, PIPE=subprocess.PIPE, STDOUT=subprocess.STDOUT))
        env["run_job"]("2026-08-01", "2026-08-31", True, True, False, True, True)
        self.assertTrue({"--ai", "--skip-collect", "--reuse-complete", "--force"}.issubset(calls[0]))
        env["run_job"]("2026-08-01", "2026-08-31", True, True, True, True, True)
        self.assertIn("--collect-only", calls[1])
        self.assertTrue({"--ai", "--skip-collect", "--reuse-complete", "--force"}.isdisjoint(calls[1]))

    def test_transfer_reports_only_completed_existing_zip(self):
        with tempfile.TemporaryDirectory(prefix="lm25-transfer-ui-") as directory:
            root = Path(directory)
            output = root / "synthetic.zip"
            output.write_bytes(b"fixture")
            for status in ("completed", "failed", "progress"):
                with self.subTest(status=status):
                    env = definitions({"transfer_job", "cancel_transfer"})
                    data = {"status": status, "output": str(output), "file_count": 1}
                    env.update(ROOT=str(root), create_transfer=lambda *args, data=data, **kwargs: data)
                    env["transfer_job"]()
                    self.assertEqual(env["JOB"]["transfer_result"]["ok"], status == "completed")
                    self.assertFalse(env["JOB"]["running"])
                    env["JOB"].update(running=True, step="existing AI job")
                    self.assertFalse(env["cancel_transfer"]())

    def test_timings_use_only_valid_stage_seconds(self):
        with tempfile.TemporaryDirectory(prefix="lm25-timing-ui-") as directory:
            env = definitions({"run_timings"})
            env["REPORT"] = directory
            record = {"stages": [{"name": "AI", "sec": 120.3, "ok": True}, {"name": "files", "sec": 10},
                                  {"name": "broken", "sec": "NaN"}, {"name": "wrong", "sec": []}, None]}
            Path(directory, "last_run.json").write_text(json.dumps(record), encoding="utf-8")
            self.assertEqual(env["run_timings"](), [{"name": "AI", "sec": 120, "ok": True},
                                                     {"name": "files", "sec": 10, "ok": False}])


if __name__ == "__main__":
    unittest.main()
