# -*- coding: utf-8 -*-
"""수집 단계 감시 누수 관문(W1 통합 창): 자식 하나를 끝까지 감시하는 ``lm27.collect.watch.watch`` 를 짧은 자식으로 반복해도
감시·배수 스레드·자식 프로세스·핸들·메모리가 반복 수에 비례해 늘지 않는다. 합성 자식(파이썬 한 줄)만. 30초 이내."""
import sys
import unittest

from lm27.collect import watch as W
from lm27.util import proc
from tests.fixtures.leak import assert_bounded, child_pids

CHILD = ("import sys, json\n"
         "for i in range(20):\n"
         "    sys.stdout.write(json.dumps({'ev': 'progress', 'done': i, 'total': 20}) + '\\n')\n"
         "    sys.stdout.write('{\"x\": %d}\\n' % i)\n")


class WatchLeak(unittest.TestCase):
    def test_watch_short_children_repeated(self):
        argv = [sys.executable, "-X", "utf8", "-B", "-c", CHILD]
        lines = []

        def step(_i):
            child = proc.spawn(argv)
            try:
                r = W.watch(child, W.WatchPolicy(poll_s=0.05), on_line=lines.append)
            finally:
                child.close()
            self.assertEqual((r.rc, r.stop_kind), (0, None))
            lines.clear()
        assert_bounded(self, step, warm=2, n=8, mem_per_iter=65536, handle_slack=12, thread_slack=0)
        self.assertEqual(child_pids(), set())


if __name__ == "__main__":
    unittest.main()
