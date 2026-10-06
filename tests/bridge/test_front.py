# -*- coding: utf-8 -*-
"""화면 [분석용 Edge 창 앞으로](``EdgeSession.front`` · ``front_window``) — 가짜 디버그 세계(실 Edge·네트워크 없음).

- 이 프로필의 Edge 가 떠 있으면 그 창을 앞으로: 최소화면 ``Browser.setWindowBounds(normal)`` 로 되살리고, 아니면 내렸다 원래
  상태로(Windows 가 다른 프로세스 창을 앞으로 못 올릴 때) · ``Page.bringToFront`` · ``/json/activate``. 새로 띄우지 않는다.
- 없으면 브리지와 같은 방식(같은 프로필·포트·기동 인자)으로 ``bridge.url`` 을 띄우고 닫지 않는다(사람이 로그인). 잠금은 기동
  순간만 잡고 놓는다. 다음 브리지 실행이 그 탭을 제 탭으로 쓰게 지난 세션에 적는다.
- 남의 디버그 Edge 에는 붙지 않는다 · 잠금이 다른 작업에 잡혀 있으면 띄우지 않는다 · LM_NO_BROWSER 면 아무것도 하지 않는다.
"""
from __future__ import annotations

import os
import unittest

from lm27.bridge import fsio
from lm27.bridge.clock import iso_now
from lm27.bridge.session import front_window
from tests.bridge.fake_http import World


class FrontTest(unittest.TestCase):
    def setUp(self):
        self.w = World()
        self.addCleanup(self.w.cleanup)

    def front(self, **kw):
        return self.w.session("bridge", None, **kw).front()

    def test_reuse_restores_minimized_window(self):
        port = self.w.cfg.edge.port
        b = self.w.net.add_ours(port, self.w.profile_dir)
        b.window_state = "minimized"
        r = self.front()
        self.assertEqual((r["state"], r["port"], r["restored"], r["foreground"]), ("front", port, True, True))
        self.assertEqual(b.window_state, "normal")
        self.assertEqual(self.w.net.launches, [])                         # 떠 있으면 새로 띄우지 않는다
        page = b.tabs[0].page
        self.assertIn("Page.bringToFront", page.calls)
        self.assertIn((port, f"/json/activate/{b.tabs[0].id}", "GET"), self.w.net.http_log)
        self.assertEqual(page.evals, [])                                  # 탭 안 JS 0(내용을 읽지 않는다)
        self.assertFalse(os.path.exists(self.w.paths.edge_lock()))       # 잠금을 남기지 않는다

    def test_normal_window_nudged_back_to_same_state(self):
        port = self.w.cfg.edge.port
        b = self.w.net.add_ours(port, self.w.profile_dir)
        b.window_state = "maximized"
        r = self.front()
        self.assertEqual(r["state"], "front")
        self.assertFalse(r["restored"])
        self.assertEqual(b.window_log, ["minimized", "maximized"])       # 내렸다 원래 상태로(최대화 유지)

    def test_launch_when_none_running_and_leave_open(self):
        r = self.front()
        self.assertEqual(r["state"], "launched", r)
        self.assertEqual(len(self.w.net.launches), 1)
        args = self.w.net.launches[0]
        self.assertEqual(args[-1], self.w.cfg.url)                        # Microsoft 365(bridge.url) — 로그인 전이면 로그인 화면
        self.assertIn(f"--user-data-dir={self.w.profile_dir}", args)       # 브리지와 같은 전용 프로필
        port = r["port"]
        b = self.w.net.browsers[port]
        self.assertTrue(b.alive)
        self.assertEqual(b.closed_by_cdp, 0)                              # 닫지 않는다 — 사람이 로그인하도록 둔다
        self.assertFalse(os.path.exists(self.w.paths.edge_lock()))
        last = fsio.read_json(fsio.bridge_file(self.w.paths, "bridge_profile"), {})["last_session"]
        self.assertEqual(last["port"], port)
        self.assertEqual(last["targets"]["bridge"], [b.tabs[0].id])       # 다음 브리지 실행이 이 탭을 제 탭으로
        sess = self.w.session("bridge", "20261006-090000-0b1c")
        sess.start()
        self.addCleanup(sess.close)
        self.assertIn("tab_reuse", sess.events)
        self.assertEqual(len(self.w.net.launches), 1)                    # 같은 Edge 를 다시 쓴다

    def test_foreign_debug_edge_untouched(self):
        port = self.w.cfg.edge.port
        foreign = self.w.net.add_foreign(port)
        r = self.front()
        self.assertEqual(r["state"], "launched")
        self.assertNotEqual(r["port"], port)
        self.assertFalse(any(c[0] == port for c in self.w.net.connects), "남의 디버그 Edge 에 연결 시도 0")
        self.assertEqual(foreign.window_log, [])

    def test_no_browser_env_and_lock_busy(self):
        self.w.environ["LM_NO_BROWSER"] = "1"
        r = self.front()
        self.assertEqual(r["state"], "edge_not_found")
        self.assertEqual(self.w.net.launches, [])
        self.w.environ.pop("LM_NO_BROWSER")
        lock = self.w.paths.edge_lock()
        os.makedirs(os.path.dirname(lock), exist_ok=True)
        now = iso_now(self.w.clock)
        fsio.write_atomic(lock, {"schema": 1, "pid": os.getpid(), "pid_ctime": 0, "role": "owa", "run_id": "r",
                                 "port": 0, "browser_id": "", "launched_by_us": False, "targets": {},
                                 "acquired": now, "heartbeat": now})
        r = self.front()
        self.assertEqual(r["state"], "lock_busy")                         # 다른 작업이 Edge 를 여는 중 — 띄우지 않는다
        self.assertEqual(self.w.net.launches, [])
        self.assertEqual(fsio.read_json(lock, {})["role"], "owa")         # 남의 잠금은 그대로

    def test_front_window_helper_quiet_notices(self):
        port = self.w.cfg.edge.port
        self.w.net.add_ours(port, self.w.profile_dir)
        kw = {"clock": self.w.clock, "http": self.w.net, "connector": self.w.net, "launcher": self.w.net.launch,
              "can_bind": self.w.net.can_bind, "edge_finder": lambda: self.w.edge_path, "proc_probe": self.w.probe,
              "in_use": self.w.net.in_use, "environ": self.w.environ, "pid_ctime": 1}
        r = front_window(self.w.paths, cfg=self.w.cfg, **kw)
        self.assertEqual(r["state"], "front")
        self.assertEqual(r["notices"], [])


if __name__ == "__main__":
    unittest.main()
