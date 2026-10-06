# -*- coding: utf-8 -*-
"""상주 에이전트 누수 관문(W1 통합 창): 감독 루프를 가짜 Win32·가상 시계로 수백 틱 돌려도(표본 → 버퍼 → 플러시 →
heartbeat) 스레드·핸들·메모리·임시 파일이 틱 수에 비례해 늘지 않는다. 실 PC 수집 0. 30초 이내."""
import tracemalloc
import unittest

from tests.fixtures import leak
from tests.fixtures.wp13 import helpers as H

WARM, N = 30, 240


class AgentLoopLeak(unittest.TestCase):
    def test_supervisor_ticks_bounded(self):
        sb = H.Sandbox()
        self.addCleanup(sb.cleanup)
        sb.agent_files()
        ag, _clk = H.make_agent(sb)
        snaps = {}
        orig = ag._tick
        count = {"n": 0}

        def tick(now):
            orig(now)
            count["n"] += 1
            if count["n"] in (WARM, WARM + N, WARM + 2 * N):
                snaps[count["n"]] = leak.snap()
        ag._tick = tick
        tracemalloc.start(1)
        try:
            self.assertEqual(ag.run(max_ticks=WARM + 2 * N), 0)
        finally:
            tracemalloc.stop()
        s1, s2, s3 = snaps[WARM], snaps[WARM + N], snaps[WARM + 2 * N]
        self.assertLessEqual(s3.threads - s1.threads, 0, (s1, s2, s3))
        self.assertLessEqual(s3.children - s1.children, 0, (s1, s2, s3))
        self.assertLessEqual(s3.handles - s1.handles, 16, (s1, s2, s3))
        self.assertLessEqual(s3.temp - s1.temp, 0, (s1, s2, s3))
        self.assertLess((s3.mem - s2.mem) / N, 4096, (s1, s2, s3))       # 반복당 4KB 미만(버퍼는 플러시로 비워진다)


if __name__ == "__main__":
    unittest.main()
