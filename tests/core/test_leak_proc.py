# -*- coding: utf-8 -*-
"""공용 하위층 누수 관문(W1 통합 창): 자식 프로세스 실행(``lm27.util.proc.run_child``·``spawn``+``kill_tree``)·하트비트
스레드(``lm27.util.events.Heartbeat``)·원자 쓰기(``fsx.atomic_write``)를 반복해도 자식·스레드·핸들·임시 파일·메모리가
반복 수에 비례해 늘지 않는다. 합성 입력만. 30초 이내."""
import sys
import tempfile
import unittest
from pathlib import Path

from lm27.util import events, fsx, proc
from tests.fixtures.leak import assert_bounded, child_pids


class ProcLeak(unittest.TestCase):
    def test_run_child_repeated(self):
        argv = [sys.executable, "-X", "utf8", "-B", "-c", "import sys; sys.stdout.write('ok')"]

        def step(_i):
            r = proc.run_child(argv, timeout_s=30)
            self.assertEqual((r.rc, r.out_text()), (0, "ok"))
        assert_bounded(self, step, warm=2, n=8, mem_per_iter=65536, handle_slack=12, thread_slack=0)
        self.assertEqual(child_pids(), set())

    def test_spawn_kill_tree_repeated(self):
        argv = [sys.executable, "-X", "utf8", "-B", "-c", "import time; time.sleep(60)"]

        def step(_i):
            c = proc.spawn(argv)
            try:
                self.assertTrue(c.alive())
                self.assertTrue(c.kill_tree())
                c.wait(timeout=30)
            finally:
                c.close()
        assert_bounded(self, step, warm=1, n=5, mem_per_iter=65536, handle_slack=12, thread_slack=0)
        self.assertEqual(child_pids(), set())


class EventsFsxLeak(unittest.TestCase):
    def test_heartbeat_start_stop_repeated(self):
        def step(_i):
            hb = events.Heartbeat(interval_s=30, stage="leak")
            hb.start()
            hb.stop()
        assert_bounded(self, step, warm=5, n=100, mem_per_iter=2048, thread_slack=0)

    def test_atomic_write_repeated_leaves_no_parts(self):
        with tempfile.TemporaryDirectory(prefix="lm27t_leak_") as d:
            p = Path(d) / "a.json"

            def step(i):
                fsx.atomic_write(p, fsx.canon_bytes({"i": i}), fsync=False)
            assert_bounded(self, step, warm=10, n=300, mem_per_iter=1024, handle_slack=8)
            self.assertEqual(sorted(x.name for x in Path(d).iterdir()), ["a.json"])     # .part 잔여 0


if __name__ == "__main__":
    unittest.main()
