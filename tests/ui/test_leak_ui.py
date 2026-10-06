# -*- coding: utf-8 -*-
"""누수 시험 — 요청 200회 동안 tracemalloc·스레드·핸들(소켓 포함) 증가 없음, 작업 15개를 돌린 뒤에도 스레드·핸들이 제자리.
127.0.0.1 임시 포트, 끝나면 서버 종료·스레드 합류·모래상자 삭제."""
import gc
import os
import threading
import time
import tracemalloc
import unittest

from lm27.ui import jobs as J
from tests.fixtures.wp35.harness import Running, Sandbox, seed_analysis

N_REQ = 200
MEM_SLACK = 768 * 1024                 # 바이트 — 로그 버퍼·인터프리터 내부 캐시 여유
HANDLE_SLACK = 40


def _handles() -> int | None:
    """이 프로세스의 커널 핸들 수(소켓·파이프·스레드·프로세스 핸들 포함). Windows 가 아니면 None."""
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.GetCurrentProcess.restype = wintypes.HANDLE
    k.GetProcessHandleCount.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    n = wintypes.DWORD(0)
    if not k.GetProcessHandleCount(k.GetCurrentProcess(), ctypes.byref(n)):
        return None
    return int(n.value)


def _settle(baseline: int, timeout: float = 5.0) -> int:
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        if threading.active_count() <= baseline:
            break
        time.sleep(0.05)
    return threading.active_count()


class LeakTest(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()
        self.addCleanup(self.sb.cleanup)
        seed_analysis(self.sb)

    def _mix(self, srv, i: int):
        k = i % 8
        if k == 0:
            return srv.req("GET", "/api/hello")
        if k == 1:
            return srv.req("GET", "/")
        if k == 2:
            return srv.req("GET", "/static/app.js")
        if k == 3:
            return srv.req("GET", "/api/jobs")
        if k == 4:
            return srv.req("POST", "/api/collect/run", {"mode": "bogus"})
        if k == 5:
            return srv.req("OPTIONS", "/api/hello")
        if k == 6:
            return srv.req("GET", "/api/hello", host="evil.example:1")
        return srv.req("GET", "/api/report?variant=full")

    def test_requests_no_growth(self):
        app = self.sb.app()
        with Running(app) as srv:
            for i in range(24):                                        # 데우기(정적 캐시·모델 캐시·지연 import)
                self._mix(srv, i)
            gc.collect()
            base_threads = _settle(threading.active_count())
            base_h = _handles()
            tracemalloc.start()
            try:
                gc.collect()
                m0 = tracemalloc.get_traced_memory()[0]
                codes = set()
                for i in range(N_REQ):
                    st, _b, _h = self._mix(srv, i)
                    codes.add(st)
                gc.collect()
                m1 = tracemalloc.get_traced_memory()[0]
            finally:
                tracemalloc.stop()
            self.assertTrue({200, 400, 405, 421} <= codes, codes)
            self.assertLess(m1 - m0, MEM_SLACK, f"메모리 증가 {m1 - m0}바이트")
            self.assertLessEqual(_settle(base_threads), base_threads)
            if base_h is not None:
                self.assertLess(_handles() - base_h, HANDLE_SLACK)
            self.assertLessEqual(len(getattr(srv.httpd, "_threads", []) or []), 4)

    def test_jobs_no_thread_or_handle_growth(self):
        app = self.sb.app(behaviour={"report": {"sleep": 0}})
        base_threads = threading.active_count()
        base_h = _handles()
        with Running(app) as srv:
            for _ in range(15):
                st, b, _ = srv.req("POST", "/api/report/build", {"run_id": "20261005-101500-3fa2"})
                self.assertEqual(st, 200, b)
                jid = b["job_id"]
                t0 = time.monotonic()
                while (app.jobs.get(jid) or {}).get("state") not in J.FINISHED and time.monotonic() - t0 < 20:
                    time.sleep(0.05)
                self.assertEqual(app.jobs.get(jid)["state"], "done")
        app.close()
        gc.collect()
        self.assertLessEqual(_settle(base_threads), base_threads)
        if base_h is not None:
            self.assertLess(_handles() - base_h, HANDLE_SLACK)
        self.assertLessEqual(len(app.jobs._jobs), J.KEEP_MEMORY)
        self.assertEqual([t for t in app.jobs._threads if t.is_alive()], [])


if __name__ == "__main__":
    unittest.main()
