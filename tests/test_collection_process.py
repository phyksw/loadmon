"""Real short-lived synthetic Python workers; no collectors/apps/accounts."""
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "LoadMonitor25" / "core"))
import collection_process


class CollectionProcessTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="lm25-stream-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def run_worker(self, program, timeout=2, callback=None, env=None):
        script = self.root / "synthetic_worker.py"
        script.write_text(program, encoding="utf-8")
        return collection_process.run_stream([sys.executable, "-u", str(script)], timeout,
            cwd=self.root, env=dict(os.environ, PYTHONIOENCODING="utf-8", **(env or {})),
            on_line=callback)

    def assert_reader_stopped(self):
        self.assertFalse(any(t.name == "lm25-collector-output" for t in threading.enumerate()))

    def test_lines_arrive_before_exit_and_stderr_env_returncode_are_preserved(self):
        arrived_before_exit = []
        marker = self.root / "done"

        def line(text):
            if text == "ready":
                arrived_before_exit.append(not marker.exists())
                (self.root / "ack").write_text("continue", encoding="utf-8")

        result = self.run_worker("import os,sys,time\nfrom pathlib import Path\n"
            "print('ready',flush=True)\nwhile not Path('ack').exists(): time.sleep(.01)\n"
            "print(os.environ['LM_SYNTHETIC'],file=sys.stderr,flush=True)\n"
            "Path('done').write_text('finished')\nsys.exit(7)\n", callback=line,
            env={"LM_SYNTHETIC": "synthetic stderr"})
        self.assertEqual(arrived_before_exit, [True])
        self.assertEqual(result, {"returncode": 7, "tail": ["ready", "synthetic stderr"], "timed_out": False})
        self.assert_reader_stopped()

    def test_timeout_preserves_partial_output_and_stops_only_owned_worker(self):
        started = time.monotonic()
        result = self.run_worker("import sys,time\nprint('login_required',flush=True)\n"
                                 "sys.stdout.write('pending detail');sys.stdout.flush()\ntime.sleep(10)\n", timeout=.3)
        self.assertTrue(result["timed_out"])
        self.assertNotEqual(result["returncode"], 0)
        self.assertEqual(result["tail"], ["login_required", "pending detail"])
        self.assertLess(time.monotonic() - started, 2)
        self.assert_reader_stopped()

    def test_heartbeat_is_live_but_tail_stays_bounded_to_child_output(self):
        lines = []
        def receive(line):
            lines.append(line)
            if line.startswith("[수집 진행]"):
                (self.root / "heartbeat_seen").write_text("continue", encoding="utf-8")
        with mock.patch.object(collection_process, "HEARTBEAT_SECONDS", .1):
            result = self.run_worker("import time\nfrom pathlib import Path\n"
                                     "for i in range(30): print('line'+str(i),flush=True)\n"
                                     "while not Path('heartbeat_seen').exists(): time.sleep(.01)\n", callback=receive)
        self.assertTrue(any(line.startswith("[수집 진행]") for line in lines))
        self.assertEqual(result["tail"], ['line' + str(i) for i in range(18, 30)])
        self.assertFalse(result["timed_out"])
        self.assert_reader_stopped()

    def test_long_unterminated_line_is_bounded_and_callback_failure_cleans_up(self):
        result = self.run_worker("import sys\nsys.stdout.write('x'*30000)\nsys.stdout.flush()\n")
        self.assertEqual(len(result["tail"]), 1)
        self.assertLessEqual(len(result["tail"][0]), collection_process.MAX_LINE_CHARS)
        self.assertIn("일부 생략", result["tail"][0])
        def fail(_):
            raise RuntimeError("synthetic callback failure")
        with self.assertRaisesRegex(RuntimeError, "synthetic callback failure"):
            self.run_worker("import time\nprint('ready',flush=True)\ntime.sleep(10)\n", callback=fail)
        self.assert_reader_stopped()

    def test_inherited_pipe_does_not_hold_reader_open_after_owned_worker_exits(self):
        started = time.monotonic()
        result = self.run_worker("import subprocess,sys,tempfile\n"
            "subprocess.Popen([sys.executable,'-c','import time; time.sleep(1.3)'], "
            "stdout=sys.stdout,stderr=sys.stdout,cwd=tempfile.gettempdir())\n"
            "print('owned worker finished',flush=True)\n")
        self.assertEqual(result, {"returncode": 0, "tail": ["owned worker finished"], "timed_out": False})
        self.assertLess(time.monotonic() - started, 1.1)
        self.assert_reader_stopped()


if __name__ == "__main__":
    unittest.main()
