# -*- coding: utf-8 -*-
"""로그인 보류(계약 v1.3 §0.8 V18 — 회사 계정이 없는 PC) · 개인 계정 안내 · [분석용 Edge 창 앞으로]가 띄운 Edge 이어받기(L09).

가짜 HTTP·CDP·기동기·가상 시계만(실 Edge·네트워크 0). 시나리오:
- 로그인 대기(bridge.loginWaitMin)가 로그인 없이 끝나면 health.login_pending 이 남고, 다음 세션은 30초만 확인하고 끝낸다
  (BR-LOGIN 대신 BR-LOGIN-PENDING · 창을 앞으로 띄우지 않음). 같은 세션의 다음 확인은 한 번 보기만(0초).
- 로그인 확인(ready)·front 는 보류를 지운다 → 다음 세션은 다시 다 기다린다.
- 로그인 탭이 login.live.com(개인 계정)이면 BR-LOGIN-PERSONAL 안내 한 번 + 보류에 account=personal.
- 바깥 마감에 잘린 대기(탐침 예산 등)는 보류를 남기지 않는다(사람이 기회를 다 못 받음).
- 세션의 ``recover("login_required")`` 는 보류 중이면 다시 기다리지 않는다(runner 의 단계마다 1분 복구 제거).
- front 가 띄운 Edge 에 다음 세션이 '재사용'으로 붙으면 그 세션이 띄운 것처럼 closeOnExit(Browser.close)를 적용한다.
"""
from __future__ import annotations

import unittest

from lm27.bridge import messages
from lm27.bridge import settings as S
from lm27.bridge.clock import Deadline
from lm27.bridge.session import LOGIN_PERSONAL_TEXT
from tests.bridge.fake_cdp import CHAT_URL, FakePage
from tests.bridge.fake_http import World

PERSONAL_URL = "https://login.live.com/oauth20_authorize.srf"
RUN_A, RUN_B, RUN_C = "20261006-090000-0a01", "20261006-100000-0b02", "20261006-110000-0c03"


class PersonalPage(FakePage):
    """로그인 화면이 개인(Microsoft) 계정 화면인 페이지."""

    def current_url(self) -> str:
        if self.login_until_s is not None and self.now() < self.login_until_s:
            return PERSONAL_URL
        return self.url


class Base(unittest.TestCase):
    def world(self, page_cls=FakePage, **page):
        w = World(page_factory=lambda url: page_cls(w.clock, **{"url": url, **page}))
        self.addCleanup(w.cleanup)
        return w

    def started(self, w, role="bridge", run_id=RUN_A, **kw):
        s = w.session(role, run_id, **kw)
        s.start()
        self.addCleanup(s.close)
        return s

    def pending(self, w):
        return w.session().login_pending()


class LoginPendingTest(Base):
    def test_full_wait_marks_pending_then_next_session_checks_30s(self):
        w = self.world(login_until_s=10 ** 9)                     # 로그인할 사람이 없다
        s1 = w.session(run_id=RUN_A)
        self.assertEqual(s1.start(), "login_required")
        waited = w.clock.mono()
        self.assertGreaterEqual(waited, w.cfg.login_wait_min * 60)
        self.assertEqual(s1.login_check, "wait")
        s1.close()
        p = self.pending(w)
        self.assertIsInstance(p, dict)
        self.assertEqual((p["role"], p["account"]), ("bridge", ""))
        # 다음 세션(다음 수집·분석) — 10분이 아니라 30초만 본다, BR-LOGIN 대신 BR-LOGIN-PENDING
        w.notices.shown.clear()
        t0 = w.clock.mono()
        s2 = w.session(run_id=RUN_B)
        self.assertEqual(s2.start(), "login_required")
        self.addCleanup(s2.close)
        spent = w.clock.mono() - t0
        self.assertLessEqual(spent, S.LOGIN_PENDING_CHECK_S + 10)
        self.assertEqual(s2.login_check, "pending")
        self.assertIn("BR-LOGIN-PENDING", w.notices.shown)
        self.assertNotIn("BR-LOGIN", w.notices.shown)
        self.assertIn("login_pending_check", s2.events)
        page = w.net.our_pages()[-1]
        self.assertNotIn("Page.bringToFront", page.calls)         # 보류 확인은 창을 앞으로 띄우지 않는다
        # 같은 세션의 다음 확인(단계마다 ensure_ready)은 한 번 보기만
        t1 = w.clock.mono()
        self.assertEqual(s2.ensure_ready(), "login_required")
        self.assertLess(w.clock.mono() - t1, 3)
        # 세션의 recover 는 보류 중이면 다시 기다리지 않는다(runner.recover 가 이 메서드를 쓴다)
        t2 = w.clock.mono()
        s2.recover("login_required")
        self.assertLess(w.clock.mono() - t2, 1)
        self.assertIn("recover_login_skipped", s2.events)

    def test_login_success_clears_pending(self):
        w = self.world(login_until_s=10 ** 9)
        s1 = w.session(run_id=RUN_A)
        s1.start()
        s1.close()
        self.assertIsNotNone(self.pending(w))
        # 사람이 로그인했다(다른 경로로) — 다음 세션의 짧은 확인에서 ready → 보류 해제
        w.net.page_factory = lambda url: FakePage(w.clock, url=url)
        for b in w.net.browsers.values():
            for t in b.tabs:
                t.page.login_until_s = None
        s2 = self.started(w, run_id=RUN_B)
        self.assertEqual(s2.state, "ready")
        self.assertIsNone(self.pending(w))
        self.assertTrue(s2.profile.load()["health"].get("login_ok_at"))

    def test_front_clears_pending_and_next_session_waits_full(self):
        w = self.world(login_until_s=10 ** 9)
        s1 = w.session(run_id=RUN_A)
        s1.start()
        s1.close()
        self.assertIsNotNone(self.pending(w))
        r = w.session("bridge", None).front()                      # 사람이 [분석용 Edge 창 앞으로]
        self.assertTrue(r.get("login_pending_cleared"), r)
        self.assertIsNone(self.pending(w))
        w.notices.shown.clear()
        t0 = w.clock.mono()
        s2 = w.session(run_id=RUN_B)
        self.assertEqual(s2.start(), "login_required")
        self.addCleanup(s2.close)
        self.assertGreaterEqual(w.clock.mono() - t0, w.cfg.login_wait_min * 60)   # 다시 다 기다린다
        self.assertIn("BR-LOGIN", w.notices.shown)

    def test_capped_wait_does_not_mark_pending(self):
        w = self.world(login_until_s=10 ** 9)
        s = self.started(w, role="owa", url=CHAT_URL + "/owa-like")   # 시작 대기(10분)는 보류를 남긴다 — 지우고 다시
        s.clear_login_pending("test")
        st = s.wait_page(Deadline.after(w.clock, 30))               # 탐침처럼 예산 30초에 잘린 대기
        self.assertEqual(st, "login_required")
        self.assertIsNone(self.pending(w))

    def test_web_role_pending_short_check(self):
        w = self.world(login_until_s=10 ** 9)
        s1 = w.session("owa", RUN_A, url=CHAT_URL + "/owa-like")
        self.assertEqual(s1.start(), "login_required")
        s1.close()
        self.assertEqual(self.pending(w)["role"], "owa")
        t0 = w.clock.mono()
        s2 = w.session("teams_web", RUN_B, url=CHAT_URL + "/teams-like")   # 같은 프로필 — 역할이 달라도 같은 보류
        self.assertEqual(s2.start(), "login_required")
        self.addCleanup(s2.close)
        self.assertLessEqual(w.clock.mono() - t0, S.LOGIN_PENDING_CHECK_S + 25)
        self.assertEqual(s2.login_check, "pending")

    def test_login_ok_helper_clears_once(self):
        w = self.world(login_until_s=10 ** 9)
        s = self.started(w, role="owa", url=CHAT_URL + "/owa-like")
        self.assertIsNotNone(self.pending(w))
        s.login_ok()
        self.assertIsNone(self.pending(w))
        self.assertIn("login_pending_cleared:login_ok", s.events)
        s.login_ok()                                               # 보류가 없으면 쓰지 않는다
        self.assertEqual(s.events.count("login_pending_cleared:login_ok"), 1)


class PersonalAccountTest(Base):
    def test_personal_login_screen_notice_and_pending_account(self):
        w = self.world(PersonalPage, login_until_s=10 ** 9)
        s = w.session(run_id=RUN_A)
        self.assertEqual(s.start(), "login_required")
        s.close()
        self.assertEqual(s.login_account, "personal")
        self.assertEqual(w.notices.shown.count("BR-LOGIN-PERSONAL"), 1)
        self.assertEqual(self.pending(w)["account"], "personal")
        r = messages.render("BR-LOGIN-PERSONAL")
        self.assertIn(LOGIN_PERSONAL_TEXT, r["text_ko"])
        self.assertIn("회사(조직) 계정이 아니면 메일·팀즈 웹 수집과 AI 판정은 건너뛰고 PC 자료로 분석합니다", r["body"])

    def test_personal_host_is_a_login_host(self):
        w = self.world()
        for h in S.PERSONAL_LOGIN_HOSTS:
            self.assertIn(h, w.cfg.login_hosts)                    # 기본 bridge.loginHosts 안 — 대기 판정이 같다

    def test_org_login_screen_no_personal_notice(self):
        w = self.world(login_until_s=10 ** 9)
        s = w.session(run_id=RUN_A)
        s.start()
        s.close()
        self.assertEqual(s.login_account, "")
        self.assertNotIn("BR-LOGIN-PERSONAL", w.notices.shown)


class AnalysisFlowTest(Base):
    """분석(브리지 AI 단계) 한 번 — 회사 계정이 없는 PC: 첫 분석은 로그인을 다 기다리고(보류를 남김), 다음 분석은 30초 남짓만
    로그인 상태를 보고 단계를 끝낸다(단계마다 1분 복구·10분 대기 없음 — V18)."""

    def run_analysis(self, w, run_id):
        from lm27.bridge import runner
        from lm27.bridge.messages import Notices
        from tests.bridge.test_full_run import FullBase
        from tests.fixtures.wp24.rig import act_rows
        from tests.fixtures.wp24.stages import ActStage, LabelStage
        fb = FullBase()
        fb.write(w, "t_act", act_rows(3))
        fb.write(w, "t_label", [{"key": "grp:1", "fields": {"kinds": "메일 1", "subjects": ["회의 준비"]}}])
        notices = Notices()
        t0 = w.clock.mono()
        rt = fb.open(w, notices, run_id=run_id)
        res = runner.run_stages(rt, [ActStage(), LabelStage()])
        runner.close_runtime(rt)
        return w.clock.mono() - t0, res, notices

    def test_second_analysis_is_short(self):
        from lm27.util import events
        events.configure(mode="off")
        self.addCleanup(events.configure, "text")
        w = self.world(login_until_s=10 ** 9)
        spent1, res1, n1 = self.run_analysis(w, RUN_A)
        self.assertGreaterEqual(spent1, w.cfg.login_wait_min * 60)          # 첫 분석: 다 기다림(BR-LOGIN)
        self.assertIn("BR-LOGIN", n1.shown)
        # 다 기다렸는데 로그인되지 않음 = 로그인 보류 — 실패(2-strike 치명·rc 1)가 아니라 skipped(login_pending)(O-18 ⑤)
        for st in ("t_act", "t_label"):
            self.assertEqual((res1[st]["state"], res1[st]["reason"], res1[st]["stop_kind"], res1[st]["rc"]),
                             ("skipped", "login_pending", None, 0), st)
        self.assertEqual(res1["t_act"]["hint"], messages.render("BR-LOGIN-HELD")["title"])
        self.assertIn("BR-LOGIN-HELD", n1.shown)
        self.assertNotIn("BR-LOGIN-TIMEOUT", n1.shown)
        self.assertEqual(sum(len(p.sent_texts) for p in w.net.our_pages()), 0)
        self.assertIsNotNone(self.pending(w))
        spent2, res2, n2 = self.run_analysis(w, RUN_B)
        self.assertLessEqual(spent2, S.LOGIN_PENDING_CHECK_S + 15)         # 다음 분석: 짧게 확인만
        self.assertIn("BR-LOGIN-PENDING", n2.shown)
        self.assertNotIn("BR-LOGIN", n2.shown)
        self.assertNotIn("BR-LOGIN-TIMEOUT", n2.shown)                     # 2-strike 치명이 아니다(통합 — runner)
        for st in ("t_act", "t_label"):                                     # 단계마다 바로 skipped(login_pending)
            self.assertEqual((res2[st]["state"], res2[st]["reason"]), ("skipped", "login_pending"), st)
            self.assertIsNone(res2[st]["stop_kind"], st)
        self.assertEqual(n2.shown.count("BR-LOGIN-PENDING"), 1)            # 안내는 한 번
        self.assertIsNotNone(self.pending(w))                              # 보류는 그대로(사람이 로그인·front 로 지운다)

    def test_login_pending_helper(self):
        from lm27.bridge import runner

        class _S:
            login_check, state = "pending", "login_required"

        class _T:
            s = _S()

        class _Rt:
            transport = _T()

        self.assertTrue(runner.login_pending(_Rt()))                       # login_held 가 없는 대역 — 예전 판정
        _Rt.transport.s.state = "ready"                                    # 짧은 확인 사이 로그인됨 → 단계를 돈다
        self.assertFalse(runner.login_pending(_Rt()))
        _Rt.transport.s.state, _Rt.transport.s.login_check = "login_required", "wait"   # 이번에 다 기다림 → 2-strike 경로
        self.assertFalse(runner.login_pending(_Rt()))
        _Rt.transport = None
        self.assertFalse(runner.login_pending(_Rt()))


class FrontAdoptTest(Base):
    def test_front_launched_edge_closed_by_next_session(self):
        w = self.world()
        r = w.session("bridge", None).front()
        self.assertEqual(r["state"], "launched")
        port = r["port"]
        b = w.net.browsers[port]
        self.assertTrue(b.alive)
        self.assertEqual(b.closed_by_cdp, 0)                       # front 는 닫지 않는다(사람이 로그인)
        s = w.session(run_id=RUN_B)
        self.assertEqual(s.start(), "ready")
        self.assertIn("adopt_front", s.events)
        self.assertTrue(s.info.launched_by_us)
        self.assertEqual(len(w.net.launches), 1)                   # 새로 띄우지 않고 재사용
        s.close()
        self.assertEqual(b.closed_by_cdp, 1)                       # closeOnExit — 디버그 포트 Edge 를 남기지 않는다
        self.assertNotIn("front_launch", s.profile.load())

    def test_other_reused_edge_not_adopted(self):
        w = self.world()
        b = w.net.add_ours(w.cfg.edge.port, w.profile_dir)          # 사람이(또는 다른 길로) 띄운 우리 프로필 Edge
        s = w.session(run_id=RUN_B)
        self.assertEqual(s.start(), "ready")
        s.close()
        self.assertNotIn("adopt_front", s.events)
        self.assertEqual(b.closed_by_cdp, 0)                       # 우리가 띄우지 않은 창은 자기 탭만 닫는다

    def test_stale_front_record_dropped(self):
        w = self.world()
        r = w.session("bridge", None).front()
        w.net.browsers[r["port"]].shutdown()                       # 사람이 그 창을 닫았다
        nb = w.net.add_ours(r["port"], w.profile_dir)              # 같은 프로필·포트의 다른 브라우저(다른 ID)
        s = w.session(run_id=RUN_C)
        self.assertEqual(s.start(), "ready")
        s.close()
        self.assertNotIn("adopt_front", s.events)
        self.assertNotIn("front_launch", s.profile.load())         # 지난 기록은 정리
        self.assertEqual(nb.closed_by_cdp, 0)


if __name__ == "__main__":
    unittest.main()
