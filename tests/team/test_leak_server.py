# -*- coding: utf-8 -*-
"""팀 서버 누수 관문(W1 통합 창): 127.0.0.1 시험 포트의 서버에 요청을 반복해도 스레드·핸들(소켓)·메모리가 요청 수에 비례해
늘지 않고, 종료하면 서버 스레드가 모두 사라진다. 합성 저장소만(실제 팀 서버·외부 네트워크 0). 30초 이내."""
import threading
import unittest

from tests.fixtures.leak import assert_bounded
from tests.fixtures.wp27 import bundles as B
from tests.fixtures.wp27.helpers import running_server


class TeamServerLeak(unittest.TestCase):
    def test_repeated_requests_bounded_and_threads_released(self):
        base_threads = threading.active_count()
        with B.temp_dir() as d:
            with running_server(d) as ts:
                def step(i):
                    code, _obj, _hdr = ts.call("GET", "/api/hello" if i % 3 else "/api/members")
                    self.assertIn(code, (200, 401, 403))
                assert_bounded(self, step, warm=20, n=150, mem_per_iter=4096, handle_slack=24, thread_slack=2)
        # 서버를 닫으면 요청·작업 스레드가 남지 않는다(데몬 스레드 누적 없음)
        for _ in range(50):
            if threading.active_count() <= base_threads:
                break
            threading.Event().wait(0.1)
        self.assertLessEqual(threading.active_count(), base_threads)


if __name__ == "__main__":
    unittest.main()
