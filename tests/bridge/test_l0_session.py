# -*- coding: utf-8 -*-
"""WP-23 L0 세션(B §4) — 가짜 HTTP·CDP·기동기·가상 시계(실 Edge 0). 시나리오 B-T10~T17·T55 + 기동·잠금·정리 경로."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from lm27.bridge import fsio
from lm27.bridge.session import classify_identity, find_edge, mask_text, read_policy, url_matches

from tests.bridge.fake_cdp import CHAT_URL, FakePage
from tests.bridge.fake_http import World, bridge_settings, policy_blocked_reg

OUTLOOK_WEB = "https://outlook.cloud.microsoft/mail/"
RUN_B = "20261005-111500-4ab1"
RUN_C = "20261006-091500-5bc2"


class Base(unittest.TestCase):
    def world(self, **kw):
        page = kw.pop("page", {})
        w = World(page_factory=lambda url: FakePage(w.clock, **{"url": url, **page}), **kw)
        self.addCleanup(w.cleanup)
        return w

    def started(self, w, role="bridge", run_id="20261005-101500-3fa2", **kw):
        s = w.session(role, run_id, **kw)
        s.start()
        self.addCleanup(s.close)
        return s


class TestScenarios(Base):
    def test_T10_never_closes_or_hijacks_other_tabs(self):
        w = self.world()
        b = w.net.add_ours(9343, w.profile_dir, urls=(OUTLOOK_WEB, CHAT_URL))
        before = [t.id for t in b.tabs]
        s = self.started(w)
        self.assertEqual(s.state, "ready")
        self.assertIn("tab_new", s.events)
        self.assertNotIn(s.info.target_id, before)
        self.assertEqual(w.net.closed_tabs, [])
        self.assertEqual([t.url for t in b.tabs[:2]], [OUTLOOK_WEB, CHAT_URL])     # 남의 탭을 옮기지도 않았다
        s.close()
        self.assertEqual([t.id for t in b.tabs], before)                             # 닫은 것은 자기 탭뿐
        self.assertEqual(b.closed_by_cdp, 0)

    def test_T11_foreign_debug_edge_skipped(self):
        w = self.world()
        w.net.add_foreign(9343)
        s = self.started(w)
        self.assertEqual((s.state, s.info.port), ("ready", 9344))
        self.assertEqual([c for c in w.net.connects if c[0] == 9343], [])
        self.assertIn("--remote-debugging-port=9344", w.net.launches[0])
        self.assertIn("skip_foreign:9343", s.events)

    def test_T12_lock_busy_live_owner(self):
        w = self.world()
        lock = Path(w.paths.edge_lock())
        fsio.write_atomic(lock, {"schema": 1, "pid": os.getpid(), "pid_ctime": 1, "role": "owa", "run_id": "x",
                                 "acquired": "2026-09-21T23:10:00+09:00", "heartbeat": "2026-09-21T23:10:00+09:00"})
        s = w.session()
        self.assertEqual(s.start(), "lock_busy")
        self.assertEqual(s.error.get("owner_role"), "owa")
        self.assertIn("BR-LOCK-BUSY", w.notices.shown)
        self.assertEqual(w.net.launches, [])
        self.assertEqual(s.events.count("lock_wait"), 3)
        s.close()
        self.assertTrue(lock.exists())                         # 남의 잠금은 지우지 않는다

    def test_T13_dead_owner_lock_taken_over(self):
        w = self.world()
        lock = Path(w.paths.edge_lock())
        fsio.write_atomic(lock, {"schema": 1, "pid": 999999, "pid_ctime": 5, "role": "bridge", "run_id": "old",
                                 "acquired": "2026-09-21T23:10:00+09:00", "heartbeat": "2026-09-21T23:10:00+09:00"})
        s = self.started(w)
        self.assertEqual(s.state, "ready")
        self.assertTrue(s.lock.took_over)
        self.assertEqual(json.loads(Path(str(lock) + ".stale").read_text(encoding="utf-8"))["pid"], 999999)
        self.assertEqual(fsio.read_json(lock)["pid"], os.getpid())

    def test_lock_stale_by_heartbeat_age(self):
        w = self.world()
        w.clock.advance(3600)
        lock = Path(w.paths.edge_lock())
        fsio.write_atomic(lock, {"schema": 1, "pid": os.getpid(), "pid_ctime": 1, "role": "bridge", "run_id": "old",
                                 "acquired": "2026-09-21T23:10:00+09:00", "heartbeat": "2026-09-21T23:10:00+09:00"})
        s = self.started(w)
        self.assertEqual(s.state, "ready")
        self.assertTrue(s.lock.took_over)

    def test_T14_login_then_continue(self):
        w = self.world(page={"login_until_s": 180})
        s = self.started(w)
        self.assertEqual(s.state, "ready")
        self.assertEqual(w.notices.shown[:2], ["BR-LOGIN", "BR-LOGIN-OK"])
        self.assertGreaterEqual(w.clock.mono(), 180)
        self.assertLess(w.clock.mono(), 200)
        self.assertTrue(s.profile.load()["health"].get("login_ok_at"))

    def test_T15_login_never_l0_part(self):
        w = self.world(page={"login_until_s": 10 ** 9})
        s = self.started(w)
        self.assertEqual(s.state, "login_required")
        self.assertEqual(w.notices.shown.count("BR-LOGIN"), 1)
        self.assertNotIn("BR-LOGIN-OK", w.notices.shown)
        self.assertGreaterEqual(w.clock.mono(), w.cfg.login_wait_min * 60)
        self.assertLess(w.clock.mono(), w.cfg.login_wait_min * 60 + 30)
        page = w.net.our_pages()[0]
        self.assertEqual(page.editor, "")                       # 로그인 화면에 아무것도 입력하지 않는다(B4)
        self.assertNotIn("Input.insertText", page.calls)

    def test_T16_input_appears_late(self):
        w = self.world(page={"input_appear_s": 40})
        s = self.started(w)
        self.assertEqual(s.state, "ready")
        self.assertNotIn("BR-INPUT", w.notices.shown)
        self.assertGreaterEqual(w.clock.mono(), 40)

    def test_input_never_dumps_diagnose(self):
        w = self.world(page={"input_appear_s": 10 ** 9})
        s = self.started(w)
        self.assertEqual(s.state, "input_not_found")
        self.assertIn("BR-INPUT", w.notices.shown)
        dumps = list(fsio.bridge_file(w.paths, "diagnose").glob("diagnose_*.json"))
        self.assertEqual(len(dumps), 1)
        d = json.loads(dumps[0].read_text(encoding="utf-8"))
        self.assertEqual(d["message_candidates"][0]["text_mask"], "가가가 xxx 000")
        self.assertNotIn("0123456789abcdef", d["url_path"])

    def test_T17_dead_profile_recreated_after_two_calls(self):
        dead = {"url": "chrome-error://chromewebdata/"}
        w = self.world(page=dead)
        first_id = None
        for run in ("20261005-101500-3fa2", RUN_B):
            s = w.session(run_id=run)
            self.assertEqual(s.start(), "dead_session")
            first_id = first_id or s.profile.profile_id()
            s.close()
        runs = [x["run"] for x in w.session().profile.load()["health"]["dead_sessions"]]
        self.assertEqual(runs, ["20261005-101500-3fa2", RUN_B])
        w.net.page_factory = lambda url: FakePage(w.clock, url=url, login_until_s=10 ** 9)
        s3 = w.session(run_id=RUN_C)
        st = s3.start()
        self.addCleanup(s3.close)
        self.assertIn("profile_recreated", s3.events)
        self.assertIn("BR-DEAD-PROFILE", w.notices.shown)
        self.assertIn("BR-LOGIN", w.notices.shown)
        self.assertEqual(st, "login_required")
        bad = list(w.profile_dir.parent.glob(w.profile_dir.name + ".bad-*"))
        self.assertEqual(len(bad), 1)
        self.assertNotEqual(s3.profile.profile_id(), first_id)
        self.assertEqual(s3.profile.load()["health"]["dead_sessions"], [])

    def test_bad_profiles_pruned(self):
        dead = {"url": "chrome-error://chromewebdata/"}
        w = self.world(page=dead)
        for i in range(4):
            for run in (f"2026100{i + 1}-101500-3fa2", f"2026100{i + 1}-111500-4ab1"):
                w.clock.advance(120)
                s = w.session(run_id=run)
                s.start()
                s.close()
        bad = list(w.profile_dir.parent.glob(w.profile_dir.name + ".bad-*"))
        self.assertEqual(len(bad), 2)                         # 세 번 재생성해도 새 .bad + 이전 1개만

    def test_T55_owa_role_blocked_by_bridge_lock(self):
        w = self.world()
        s1 = self.started(w)
        self.assertEqual(s1.state, "ready")
        n_launch = len(w.net.launches)
        s2 = w.session("owa", url=OUTLOOK_WEB)
        self.assertEqual(s2.start(), "lock_busy")
        self.assertEqual(len(w.net.launches), n_launch)        # 두 번째 기동 없음
        s2.close()
        self.assertTrue(Path(w.paths.edge_lock()).exists())     # 브리지의 잠금은 그대로


class TestLaunchPaths(Base):
    def test_launch_args(self):
        w = self.world()
        s = self.started(w)
        args = w.net.launches[0]
        self.assertEqual(args[0], w.edge_path)
        self.assertIn(f"--user-data-dir={w.profile_dir}", args)
        self.assertIn("--remote-debugging-port=9343", args)
        self.assertIn("--disk-cache-size=" + str(200 * 1048576), args)
        self.assertIn("--window-size=1150,900", args)
        self.assertEqual(args[-1], w.cfg.url)
        self.assertFalse(any(a.startswith("--remote-allow-origins") for a in args))
        self.assertFalse(any("--remote-debugging-address" in a for a in args))
        self.assertTrue(s.profile.profile_id())
        self.assertIn("tab_adopt", s.events)

    def test_no_browser_env(self):
        w = self.world()
        w.environ["LM_NO_BROWSER"] = "1"
        s = w.session()
        self.assertEqual(s.start(), "edge_not_found")
        self.assertEqual((w.net.launches, w.net.http_log, w.net.connects), ([], [], []))
        self.assertFalse(Path(w.paths.edge_lock()).exists())

    def test_edge_not_found(self):
        w = self.world(edge_path=None)
        s = w.session()
        self.assertEqual(s.start(), "edge_not_found")
        s.close()
        self.assertFalse(Path(w.paths.edge_lock()).exists())

    def test_port_exhausted(self):
        w = self.world()
        w.net.occupied = set(range(9343, 9353))
        s = w.session()
        self.assertEqual(s.start(), "port_exhausted")
        self.assertEqual(w.net.launches, [])
        s.close()

    def test_policy_blocked(self):
        w = self.world(policy_reg=policy_blocked_reg)
        w.net.launch_mode = "policy"
        s = w.session()
        self.assertEqual(s.start(), "policy_blocked")
        self.assertEqual(w.net.procs[0].killed, 1)               # 응답 없는 우리 Edge 는 정리
        self.assertTrue(s.edge.policy_blocked)
        s.close()

    def test_launch_failed(self):
        for mode in ("policy", "exit"):
            with self.subTest(mode):
                w = self.world()
                w.net.launch_mode = mode
                s = w.session()
                self.assertEqual(s.start(), "launch_failed")
                s.close()

    def test_profile_busy(self):
        w = self.world()
        w.net.launch_mode = "busy"
        s = w.session()
        self.assertEqual(s.start(), "profile_busy")
        self.assertIn("BR-PROFILE-BUSY", w.notices.shown)
        self.assertGreaterEqual(w.clock.mono(), 30)
        s.close()

    def test_slow_launch_within_20s(self):
        w = self.world()
        w.net.launch_mode = "slow:12"
        s = self.started(w)
        self.assertEqual(s.state, "ready")

    def test_reuse_own_running_edge(self):
        w = self.world()
        w.net.add_ours(9345, w.profile_dir)
        s = self.started(w)
        self.assertEqual((s.state, s.info.port, s.info.launched_by_us), ("ready", 9345, False))
        self.assertEqual(w.net.launches, [])

    def test_reuse_without_devtools_file_by_last_session(self):
        w = self.world()
        s = self.started(w)
        s.info.launched_by_us = False                            # 닫지 않고 남겨 두기
        s.close()
        os.remove(w.profile_dir / "DevToolsActivePort")
        s2 = self.started(w, run_id=RUN_B)
        self.assertEqual((s2.state, s2.info.port), ("ready", 9343))
        self.assertEqual(len(w.net.launches), 1)

    def test_origin_403_relaunch_explicit(self):
        w = self.world()
        w.net.reject_no_origin = True
        s = self.started(w)
        self.assertEqual(s.state, "ready")
        self.assertEqual(len(w.net.launches), 2)
        self.assertIn("--remote-allow-origins=http://127.0.0.1:9343", w.net.launches[1])
        self.assertEqual(s.profile.load()["health"]["origin_mode"], "explicit")
        self.assertEqual(w.net.connects[-1][3], "http://127.0.0.1:9343")
        s.close()
        s2 = self.started(w, run_id=RUN_B)                     # 다음 호출은 처음부터 explicit
        self.assertEqual(s2.state, "ready")
        self.assertIn("--remote-allow-origins=http://127.0.0.1:9343", w.net.launches[2])
        self.assertEqual(len(w.net.launches), 3)

    def test_origin_403_on_reused_browser(self):
        w = self.world()
        w.net.add_ours(9343, w.profile_dir)
        w.net.reject_no_origin = True
        s = w.session()
        self.assertEqual(s.start(), "launch_failed")
        self.assertEqual(s.error.get("why"), "origin_rejected")
        self.assertEqual(s.profile.load()["health"]["origin_mode"], "explicit")
        s.close()


class TestRobustness(Base):
    def test_unexpected_connect_error_is_phase_and_unlocks(self):
        w = self.world()

        class Broken:
            def connect(self, ws_url, *, origin=None):
                raise ConnectionResetError("fake")
        s = w.session(connector=Broken())
        self.assertEqual(s.start(), "launch_failed")
        self.assertEqual(s.error.get("why"), "ConnectionResetError")
        self.assertFalse(Path(w.paths.edge_lock()).exists())     # 붙지 못하면 잠금을 바로 놓는다
        s.close()
        self.assertIn("browser_close", s.events)                 # 우리가 띄운 Edge 는 닫기를 시도한다
        self.assertEqual(w.net.procs[0].killed, 0)                # 닫히지 않아도 강제 종료하지 않는다(B §4.9)

    def test_no_heartbeat_thread_on_virtual_clock(self):
        w = self.world()
        s = self.started(w)
        self.assertIsNone(s._hb_thread)

    def test_start_is_idempotent(self):
        w = self.world()
        s = self.started(w)
        self.assertEqual(s.start(), "ready")
        self.assertEqual(len(w.net.launches), 1)


class TestCloseAndTabs(Base):
    def test_T47_close_launched_vs_reused(self):
        w = self.world()
        s = self.started(w)
        b = w.net.browsers[9343]
        s.close()
        self.assertEqual(b.closed_by_cdp, 1)                   # 우리가 띄운 Edge → Browser.close
        self.assertFalse(Path(w.paths.edge_lock()).exists())
        w2 = self.world()
        b2 = w2.net.add_ours(9343, w2.profile_dir)
        s2 = self.started(w2)
        s2.close()
        self.assertEqual(b2.closed_by_cdp, 0)                  # 원래 떠 있던 Edge 는 건드리지 않음
        self.assertTrue(b2.alive)
        self.assertEqual(len(w2.net.closed_tabs), 1)           # 닫은 것은 자기 탭 하나

    def test_close_on_exit_false_closes_own_tab_only(self):
        w = self.world(overrides={"bridge.edge.closeOnExit": False})
        s = self.started(w)
        tid = s.info.target_id
        s.close()
        self.assertEqual(w.net.browsers[9343].closed_by_cdp, 0)
        self.assertEqual(w.net.closed_tabs, [(9343, tid)])
        s.close()                                              # 두 번 불러도 된다

    def test_browser_close_ignored_keeps_running(self):
        w = self.world()
        w.net.browser_close_works = False
        s = self.started(w)
        s.close()
        self.assertTrue(w.net.browsers[9343].alive)            # 5초 안에 안 닫혀도 강제 종료하지 않는다
        self.assertEqual(w.net.procs[0].killed, 0)

    def test_tab_reused_next_call(self):
        w = self.world(overrides={"bridge.edge.closeOnExit": False})
        s = self.started(w)
        s._close_own_tab = lambda: None                        # 탭을 남겨 둔 채 끝난 호출
        s.close()
        s2 = self.started(w, run_id=RUN_B)
        self.assertIn("tab_reuse", s2.events)

    def test_heartbeat_updates_lock(self):
        w = self.world()
        s = self.started(w)
        hb0 = fsio.read_json(w.paths.edge_lock())["heartbeat"]
        w.clock.advance(31)
        s.tick()
        self.assertNotEqual(fsio.read_json(w.paths.edge_lock())["heartbeat"], hb0)

    def test_lock_records_session(self):
        w = self.world()
        s = self.started(w)
        doc = fsio.read_json(w.paths.edge_lock())
        self.assertEqual((doc["role"], doc["port"], doc["launched_by_us"]), ("bridge", 9343, True))
        self.assertEqual(doc["targets"]["bridge"], [s.info.target_id])
        self.assertEqual(doc["browser_id"], s.info.browser_id)


class TestWebRoles(Base):
    def test_owa_role_login_wait_and_ready(self):
        w = self.world(page={"login_until_s": 60})
        s = self.started(w, role="owa", url=CHAT_URL + "/owa-like")
        self.assertEqual(s.state, "ready")
        self.assertEqual(w.notices.shown[:2], ["BR-LOGIN", "BR-LOGIN-OK"])
        self.assertIsNone(s.env)                               # Copilot 판별은 bridge 역할만

    def test_web_role_https_only(self):
        w = self.world()
        with self.assertRaises(ValueError):
            w.session("teams_web", url="http://teams.example/")
        with self.assertRaises(ValueError):
            w.session("other")

    def test_web_role_blank_then_goto(self):
        w = self.world(page={"login_until_s": 30})
        s = self.started(w, role="teams_web")
        self.assertEqual(s.state, "ready")
        self.assertEqual(w.net.launches[0][-1], "about:blank")
        self.assertEqual(s.goto(CHAT_URL + "/teams-like"), "ready")
        self.assertIn("BR-LOGIN", w.notices.shown)
        with self.assertRaises(ValueError):
            s.goto("http://teams.example/")

    def test_roles_share_profile_and_ports(self):
        w = self.world()
        s = self.started(w, role="teams_web", url=OUTLOOK_WEB)
        self.assertEqual(Path(s.info.profile_dir), w.profile_dir)
        self.assertEqual(s.info.port, 9343)
        s.close()
        s2 = self.started(w, run_id=RUN_B)
        self.assertEqual(Path(s2.info.profile_dir), w.profile_dir)


class TestModelAndWork(Base):
    def test_select_model_once_per_chat(self):
        w = self.world()
        s = self.started(w)
        page = w.net.our_pages()[0]
        n1 = s.select_model("빠른 응답")
        self.assertTrue(n1.ok)
        self.assertEqual(page.model_current, "빠른 응답")
        n2 = s.select_model("빠른 응답")
        self.assertIs(n1, n2)
        self.assertEqual(page.clicks.count("model_menu"), 1)
        s.info.chat_seq += 1
        n3 = s.select_model("빠른 응답")
        self.assertEqual(n3.note, "already")
        self.assertEqual(page.clicks.count("model_menu"), 1)

    def test_select_model_missing_item_continues(self):
        w = self.world()
        s = self.started(w)
        n = s.select_model("없는 모델 9")
        self.assertFalse(n.ok)
        self.assertEqual(n.note, "item_not_found")
        self.assertLessEqual(len(n.menu_seen), 8)
        self.assertEqual(s.select_model("").note, "untouched")


class TestPureHelpers(unittest.TestCase):
    def test_url_matches_exact_host(self):
        p = "https://m365.cloud.microsoft/chat"
        self.assertTrue(url_matches("https://m365.cloud.microsoft/chat/abc?x=1", p))
        self.assertFalse(url_matches("https://m365.cloud.microsoft.evil.example/chat", p))
        self.assertFalse(url_matches("https://evil.example/m365.cloud.microsoft/chat", p))
        self.assertFalse(url_matches("http://m365.cloud.microsoft/chat", p))
        self.assertFalse(url_matches("https://m365.cloud.microsoft/other", p))

    def test_classify_identity_table(self):
        cfg = bridge_settings(tempfile.gettempdir())
        inp = {"found": True, "aria": "Copilot에 메시지 보내기"}
        cases = [
            ({"url": "https://login.microsoftonline.com/x", "ready": "complete"}, ("login_required", "")),
            ({"url": "about:blank", "ready": "loading"}, ("loading", "")),
            ({"url": "chrome-error://chromewebdata/", "ready": "complete"}, ("dead", "")),
            ({"url": "edge://newtab", "ready": "complete"}, ("dead", "")),
            ({"url": OUTLOOK_WEB, "ready": "complete", "input": inp}, ("wrong_page", "")),
            ({"url": CHAT_URL, "ready": "interactive", "input": {"found": False}}, ("loading", "")),
            ({"url": CHAT_URL, "ready": "complete", "input": inp}, ("ready", "strong")),
            ({"url": CHAT_URL, "ready": "complete", "input": {"found": True, "aria": "입력"}}, ("ready", "weak")),
            ({"url": CHAT_URL, "ready": "complete", "input": {"found": False}}, ("no_input", "")),
        ]
        for r, want in cases:
            with self.subTest(r["url"]):
                self.assertEqual(classify_identity(r, cfg), want)

    def test_find_edge_order(self):
        reg = {("HKCU", ""): r"C:\apps\Edge\msedge.exe"}
        files = {r"C:\apps\Edge\msedge.exe", os.path.join(r"C:\PF86", "Microsoft", "Edge", "Application", "msedge.exe")}
        got = find_edge(lambda h, k, v: reg.get((h, v)), {"ProgramFiles(x86)": r"C:\PF86"}, files.__contains__)
        self.assertEqual(got, r"C:\apps\Edge\msedge.exe")
        got2 = find_edge(lambda h, k, v: None, {"ProgramFiles(x86)": r"C:\PF86"}, files.__contains__)
        self.assertTrue(got2.startswith(r"C:\PF86"))
        self.assertIsNone(find_edge(lambda h, k, v: None, {}, lambda p: False))

    def test_read_policy(self):
        self.assertEqual(read_policy(lambda h, k, v: None), ("unset", "unset"))
        self.assertEqual(read_policy(policy_blocked_reg), ("blocked", "unset"))
        self.assertEqual(read_policy(lambda h, k, v: 2 if v == "DeveloperToolsAvailability" else 1),
                         ("allowed", "blocked"))

    def test_mask_text(self):
        self.assertEqual(mask_text("가나 AbC 12-x"), "가가 xxx 00-x")
        self.assertEqual(len(mask_text("가" * 100)), 40)


if __name__ == "__main__":
    unittest.main()
