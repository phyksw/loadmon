# -*- coding: utf-8 -*-
"""회사 PC(회사 M365 계정이 있는 PC) 위험 — Microsoft 공식 문서 대조 결과(H1~H5·H13·M4~M6·M11·L1·L11·L12·O-18 ⑤)의 브리지 몫.

가짜 HTTP·CDP·기동기·가상 시계만(실 Edge·Outlook·Teams·네트워크·레지스트리 쓰기 0). 시나리오마다 '고치기 전에 재현된 일'을
주석으로 적고, 고친 뒤의 동작을 단언한다.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from lm27.bridge import messages, runner
from lm27.bridge import settings as S
from lm27.bridge.capability import ChatAccess
from lm27.bridge.env import derive_account
from lm27.bridge.messages import Notices
from lm27.bridge.session import aadsts_kind
from lm27.util import events

from tests.bridge.fake_cdp import CHAT_URL, LOGIN_URL, FakePage, FakeReply
from tests.bridge.fake_http import World, browser_signin_reg, policy_blocked_reg, user_data_dir_reg
from tests.bridge.test_full_run import FullBase, _act_reply
from tests.fixtures.wp24.rig import act_rows
from tests.fixtures.wp24.stages import ActStage, LabelStage

RUN_A, RUN_B, RUN_C = "20261007-090000-0a01", "20261007-100000-0b02", "20261007-110000-0c03"
ADFS = "https://sts.corp.example/adfs/ls/"


def setUpModule():
    events.configure(mode="off")


def tearDownModule():
    events.configure("text")


class SeqPage(FakePage):
    """로그인 흐름 흉내 — 시각별 URL 열 [(끝 초, url)…](끝나면 self.url). 우리 탭을 다시 열면(navigate) 흐름이 끝난다."""
    seq: tuple = ()

    def current_url(self) -> str:
        for end, u in self.seq:
            if self.now() < end:
                return u
        return super().current_url()

    def navigate(self, url):
        self.seq = ()
        super().navigate(url)


class StickyPage(FakePage):
    """다시 열어도 그 화면에 머무는 페이지(강제 Edge 로그인 edge:// 등)."""

    def navigate(self, url):
        self.reset_chat()


class Base(FullBase):
    def world(self, page=None, environ=None, overrides=None, page_cls=FakePage, policy_reg=None):
        kw = {} if policy_reg is None else {"policy_reg": policy_reg}
        w = World(page_factory=lambda url: page_cls(w.clock, **{"url": url, **(page or {})}), overrides=overrides, **kw)
        self.addCleanup(w.cleanup)
        if environ:
            w.environ.update(environ)
        return w

    def started(self, w, role="bridge", run_id=RUN_A, **kw):
        s = w.session(role, run_id, **kw)
        s.start()
        self.addCleanup(s.close)
        return s

    def analysis(self, w, run_id=RUN_A, n=3, reply=True, notices=None):
        """브리지 AI 단계 한 번(가짜 Copilot 이 답한다) → (결과, notices, 보낸 글 수)."""
        notices = notices or Notices()
        self.write(w, "t_act", act_rows(n))
        rt = self.open(w, notices, run_id=run_id)
        if reply:
            for p in w.net.our_pages():
                p.replies.extend([FakeReply(text=_act_reply, cps=2000)] * 3)
        res = runner.run_stages(rt, [ActStage()])["t_act"]
        runner.close_runtime(rt)
        return res, notices, sum(len(p.sent_texts) for p in w.net.our_pages())


# ───────────────────────── H3 · L1 — 로그인 흐름 ─────────────────────────
class LoginFlowTest(Base):
    def flow(self, mid_url, mid_s=200):
        class P(SeqPage):
            seq = ((30, LOGIN_URL), (mid_s, mid_url))
        return self.world(page_cls=P)

    def test_idp_and_auth_hosts_keep_login_wait(self):
        """고치기 전: AD FS·certauth·mysignins·login.windows.net 화면이 wrong_page → 대기가 '로그인 넘어감'으로 끝나고 wrong_tab
        (BR-TAB '창이 닫혔습니다'). 고친 뒤: 그 화면 동안 로그인 대기를 이어 가고, 우리 탭을 다른 곳으로 옮기지 않는다."""
        for mid in (ADFS, "https://certauth.login.microsoftonline.com/t/certauth",
                    "https://mysignins.microsoft.com/register", "https://login.windows.net/common/oauth2/authorize",
                    "https://autologon.microsoftazuread-sso.com/x"):
            with self.subTest(mid):
                w = self.flow(mid)
                s = self.started(w)
                page = w.net.our_pages()[0]
                self.assertEqual(s.state, "ready")
                self.assertGreaterEqual(w.clock.mono(), 200)                  # IdP 화면 내내 기다렸다
                self.assertEqual(page.calls.count("Page.navigate"), 0)         # 사람이 입력 중인 화면을 떠나지 않음
                self.assertEqual(w.notices.shown[-2:], ["BR-LOGIN", "BR-LOGIN-OK"])
                self.assertIn("org", s.login_seen)

    def test_after_login_lands_on_ms_home_then_reopens_chat(self):
        """로그인을 마치고 Copilot 이 아닌 Microsoft 화면(홈)에 닿으면 한 번 다시 연다 — wrong_tab 이 아니다."""
        class P(SeqPage):
            seq = ((30, LOGIN_URL), (10 ** 9, "https://www.microsoft365.com/"))
        w = self.world(page_cls=P)
        s = self.started(w)
        self.assertEqual(s.state, "ready")
        self.assertEqual(w.net.our_pages()[0].calls.count("Page.navigate"), 1)

    def test_wrong_tab_message_is_not_window_closed(self):
        self.assertEqual(messages.explain_phase("wrong_tab")[0], "BR-TAB-PAGE")
        self.assertNotIn("닫혔", messages.render("BR-TAB-PAGE")["title"])
        self.assertEqual(messages.explain_phase("tab_lost")[0], "BR-TAB")

    def test_sso_pass_is_silent(self):
        """L1 — 고치기 전: PRT·Seamless SSO 로 로그인 화면을 1.5초 지나가도 BR-LOGIN + 창을 앞으로. 고친 뒤: 조용히 ready."""
        w = self.world(page={"login_until_s": 1.5})
        s = self.started(w)
        page = w.net.our_pages()[0]
        self.assertEqual(s.state, "ready")
        self.assertEqual(w.notices.shown, [])
        self.assertNotIn("Page.bringToFront", page.calls)
        self.assertIn("login_passed", s.events)

    def test_login_host_suffix_rules(self):
        hosts = (".microsoftonline.com", "login.live.com")
        self.assertTrue(S.host_in("certauth.login.microsoftonline.com", hosts))
        self.assertTrue(S.host_in("LOGIN.MICROSOFTONLINE.COM", hosts))
        self.assertFalse(S.host_in("microsoftonline.com.evil.example", hosts))
        self.assertFalse(S.host_in("evilmicrosoftonline.com", hosts))      # 마디 단위 — 부분 문자열 아님
        self.assertFalse(S.host_in("live.com", hosts))
        self.assertFalse(S.host_in("", hosts))
        w = self.world()
        for h in S.PERSONAL_LOGIN_HOSTS:
            self.assertTrue(w.cfg.login_host(h))


# ───────────────────────── H1 · M6 — 브라우저(Edge) 로그인 ─────────────────────────
class EdgeLoginTest(Base):
    def test_device_ca_aadsts_guides_edge_profile_signin(self):
        """H1 — 고치기 전: AADSTS53000(장치 기반 조건부 액세스)에도 '웹 로그인' 안내뿐, 보류에 원인 없음. 고친 뒤: Edge 프로필
        로그인 안내(BR-LOGIN-EDGE) + 보류 hint=edge_profile, 다음 실행은 그 안내를 먼저."""
        w = self.world(page={"login_until_s": 10 ** 9, "aadsts_code": "53000"})
        s = w.session(run_id=RUN_A)
        self.assertEqual(s.start(), "login_required")
        s.close()
        self.assertIn("BR-LOGIN-EDGE", w.notices.shown)
        self.assertEqual((s.aadsts, s.login_hint), ("53000", "edge_profile"))
        self.assertEqual(s.login_pending()["hint"], "edge_profile")
        w.notices.shown.clear()
        s2 = self.started(w, run_id=RUN_B)
        self.assertEqual(w.notices.shown[:2], ["BR-LOGIN-EDGE", "BR-LOGIN-PENDING"])
        self.assertEqual(s2.state, "login_required")

    def test_aadsts_kinds(self):
        self.assertEqual([aadsts_kind(c) for c in ("53000", "50097", "53003", "530032", "50158", "50076", "x", "")],
                         ["device", "device", "policy", "policy", "interactive", "other", "", ""])

    def test_br_login_mentions_edge_profile(self):
        self.assertIn("프로필 단추", messages.render("BR-LOGIN", loginWaitMin=10)["body"])

    def test_edge_page_is_browser_login_not_dead_profile(self):
        """M6 — 고치기 전: edge:// 화면(강제 Edge 로그인)을 죽은 세션으로 보고 서로 다른 실행 2회 뒤 프로필을 다시 만들고
        BR-DEAD-PROFILE('로그인 정보가 손상'). 고친 뒤: 브라우저 로그인 필요(login_required · BR-LOGIN-EDGE), 재생성 없음."""
        w = self.world(page={"url": "edge://profile-signin/"}, page_cls=StickyPage)
        w.net.page_factory = lambda url: StickyPage(w.clock, url="edge://profile-signin/")
        for i, rid in enumerate((RUN_A, RUN_B, RUN_C)):
            s = w.session(run_id=rid)
            self.assertEqual(s.start(), "login_required", i)
            s.close()
            self.assertNotIn("profile_recreated", s.events)
            for b in w.net.browsers.values():
                b.shutdown()
        h = w.session().profile.load()["health"]
        self.assertEqual(h["dead_sessions"], [])
        self.assertNotIn("BR-DEAD-PROFILE", w.notices.shown)
        self.assertIn("BR-LOGIN-EDGE", w.notices.shown)
        self.assertEqual(h["login_pending"]["hint"], "edge_signin")

    def test_browser_signin_policy_skips_profile_recreate(self):
        w = self.world(policy_reg=browser_signin_reg)
        s0 = w.session()

        def put(d):
            d["health"]["dead_sessions"] = [{"run": RUN_A, "at": "x"}, {"run": RUN_B, "at": "y"}]
        s0.profile.update(put)
        s = self.started(w, run_id=RUN_C)
        self.assertIn("recreate_skipped_policy", s.events)
        self.assertNotIn("profile_recreated", s.events)
        self.assertEqual(s.edge.policy_browser_signin, "force")


# ───────────────────────── H2 · L12 — 로그인 유지·디버그 포트 Edge ─────────────────────────
class HoldTest(Base):
    def test_one_job_keeps_logged_in_edge_then_closes(self):
        """H2 — 고치기 전: 세션마다 Browser.close → 로그인 유지가 없는 회사는 수집(웹)·분석(AI)마다 다시 로그인. 고친 뒤: 작업
        보류 동안 한 Edge 를 이어 쓰고(기동 1회), 작업이 끝나면 닫는다(디버그 포트 Edge 를 남기지 않음)."""
        w = self.world()
        tok = w.session("bridge", None).begin_hold()
        s1 = self.started(w, "owa", RUN_A, url=CHAT_URL + "/owa-like")
        s1.close()
        (b,) = list(w.net.browsers.values())
        self.assertTrue(b.alive)
        self.assertEqual(b.closed_by_cdp, 0)
        self.assertIn("kept_open", s1.events)
        self.assertEqual(b.tabs[0].page.url, "about:blank")                 # 사서함 화면을 남기지 않는다
        s2 = self.started(w, "teams_web", RUN_B, url=CHAT_URL + "/teams-like")
        s2.close()
        s3 = self.started(w, "bridge", RUN_C)
        self.assertIn("adopt_kept", s3.events)
        s3.close()
        self.assertEqual(len(w.net.launches), 1)
        self.assertTrue(b.alive)
        out = w.session("bridge", None).end_hold(tok)
        self.assertEqual((out["released"], out["closed"]), (True, ["kept_launch"]))
        self.assertFalse(b.alive)
        self.assertNotIn("kept_launch", w.session().profile.load())

    def test_without_hold_closes_each_session(self):
        w = self.world()
        s1 = self.started(w, "owa", RUN_A, url=CHAT_URL + "/owa-like")
        s1.close()
        s2 = self.started(w, "bridge", RUN_B)
        s2.close()
        self.assertEqual(len(w.net.launches), 2)
        self.assertTrue(all(b.closed_by_cdp == 1 for b in w.net.browsers.values()))

    def test_dead_hold_owner_does_not_keep_edge(self):
        w = self.world()
        w.session("bridge", None).begin_hold()
        w.alive_pids.discard(__import__("os").getpid())                     # 보류 주인이 죽었다
        w.alive_pids.add(-1)
        s = w.session("bridge", RUN_A, proc_probe=lambda pid, ctime=None: False)
        s.start()
        s.close()
        self.assertEqual(next(iter(w.net.browsers.values())).closed_by_cdp, 1)

    def test_hold_expires(self):
        w = self.world()
        w.session("bridge", None).begin_hold(max_s=60)
        w.clock.advance(61)
        s = self.started(w, "bridge", RUN_A)
        self.assertFalse(s.hold_active())
        s.close()
        self.assertEqual(next(iter(w.net.browsers.values())).closed_by_cdp, 1)

    def test_nopersist_diagnosis(self):
        """로그인 확인 뒤 Edge 를 닫고 새로 띄웠더니 다시 로그인 화면 — '로그인 유지 안 됨' 안내(KMSI·Edge 프로필 로그인)."""
        w = self.world()
        s1 = self.started(w, run_id=RUN_A)
        s1.close()
        w.net.page_factory = lambda url: FakePage(w.clock, url=url, login_until_s=10 ** 9)
        w.notices.shown.clear()
        s2 = w.session(run_id=RUN_B)
        self.assertEqual(s2.start(), "login_required")
        s2.close()
        self.assertIn("BR-LOGIN-NOPERSIST", w.notices.shown)
        self.assertEqual(s2.profile.load()["health"]["login_nopersist"]["n"], 1)

    def test_front_launched_edge_swept_after_idle(self):
        """L12 — 고치기 전: [분석용 Edge 창 앞으로]가 띄운 디버그 포트 Edge 가 다음 세션 전까지 무기한. 고친 뒤: 유휴 한도가
        지나면 정리(sweep)가 그 브라우저(ID·우리 프로필 확인)만 닫는다. 한도 안이면 그대로."""
        w = self.world()
        r = w.session("bridge", None).front()
        b = w.net.browsers[r["port"]]
        w.clock.advance(S.FRONT_TTL_S / 2)
        self.assertEqual(w.session("bridge", None).sweep()["kept"], ["front_launch"])
        self.assertTrue(b.alive)
        w.session("bridge", None).front()                                   # 사람이 다시 찾음 — 시계를 다시 맞춘다
        w.clock.advance(S.FRONT_TTL_S - 10)
        w.session("bridge", None).sweep()
        self.assertTrue(b.alive)
        w.clock.advance(20)
        out = w.session("bridge", None).sweep()
        self.assertEqual(out["closed"], ["front_launch"])
        self.assertFalse(b.alive)

    def test_sweep_leaves_foreign_browser(self):
        w = self.world()
        r = w.session("bridge", None).front()
        w.net.browsers[r["port"]].shutdown()
        nb = w.net.add_ours(r["port"], w.profile_dir)                        # 같은 포트의 다른 브라우저(ID 다름)
        w.clock.advance(S.FRONT_TTL_S + 1)
        out = w.session("bridge", None).sweep()
        self.assertEqual(out["closed"], [])
        self.assertTrue(nb.alive)
        self.assertNotIn("front_launch", w.session().profile.load())

    def test_hold_context_manager(self):
        from lm27.bridge.session import edge_hold
        w = self.world()
        kw = {"clock": w.clock, "http": w.net, "connector": w.net, "proc_probe": w.probe, "pid_ctime": 1,
              "environ": w.environ}
        with edge_hold(w.paths, cfg=w.cfg, **kw):
            s = self.started(w, "bridge", RUN_A)
            s.close()
            self.assertTrue(next(iter(w.net.browsers.values())).alive)
        self.assertFalse(next(iter(w.net.browsers.values())).alive)


# ───────────────────────── H4 — 개인 Microsoft 계정 Copilot 에는 보내지 않음 ─────────────────────────
class AccountTest(Base):
    def test_personal_login_flow_sends_nothing(self):
        """고치기 전: login.live.com 을 거쳐 Copilot 이 준비되면 그대로 업무 요약을 보냄. 고친 뒤: skipped(personal_account), 0건."""
        class Live(SeqPage):
            seq = ((20, "https://login.live.com/oauth20_authorize.srf"),)
        w = self.world(page_cls=Live)
        res, n, sent = self.analysis(w)
        self.assertEqual((res["state"], res["reason"], res["rc"]), ("skipped", "personal_account", 0))
        self.assertEqual(sent, 0)
        self.assertIn("BR-LOGIN-PERSONAL", n.shown)
        self.assertEqual(w.session().saved_account(), "personal")
        # 다음 실행: 로그인 화면 없이 이미 열린 세션이어도 저장된 개인 계정 — 보내지 않는다
        res2, _n2, sent2 = self.analysis(w, run_id=RUN_B)
        self.assertEqual((res2["reason"], sent2), ("personal_account", 0))

    def test_open_session_without_work_marks_sends_nothing(self):
        """고치기 전: 로그인 화면 없이 열린 세션(회사 표시·업무 토글 없음)에도 보냄. 고친 뒤: skipped(account_unknown), 0건."""
        w = self.world(page={"work_toggle": False})
        res, n, sent = self.analysis(w)
        self.assertEqual((res["state"], res["reason"]), ("skipped", "account_unknown"))
        self.assertEqual(sent, 0)
        self.assertIn("BR-ACCOUNT-UNKNOWN", n.shown)
        self.assertIn("acct_unknown", res["env"].get("account", "") + "acct_unknown")

    def test_work_marks_allow_sending(self):
        for page in ({"work_toggle": False, "account_label": True}, {"work_toggle": False, "shield": True},
                     {"work_toggle": False, "workiq": "on"}, {}):
            with self.subTest(page):
                w = self.world(page=page)
                res, _n, sent = self.analysis(w)
                self.assertEqual((res["state"], res["env"]["account"]), ("done", "work"))
                self.assertGreater(sent, 0)

    def test_org_login_flow_marks_work_and_beats_saved_personal_only_with_marker(self):
        class Org(SeqPage):
            seq = ((20, LOGIN_URL),)
        w = self.world(page_cls=Org, page={"work_toggle": False})
        s = self.started(w)
        self.assertEqual((s.env.account, s.saved_account()), ("work", "work"))
        self.assertIn("acct_org_login", s.env.evidence)

    def test_derive_account_order(self):
        mark = {"acct": {"label": True}}
        self.assertEqual(derive_account(mark, seen={"personal"})[0], "personal")      # 개인 로그인 화면이 이긴다
        self.assertEqual(derive_account(mark, saved="personal")[0], "work")            # 회사 표시는 저장된 개인을 갈음
        self.assertEqual(derive_account({}, seen={"org"}, saved="personal")[0], "personal")
        self.assertEqual(derive_account({"toggle": {"found": True, "stateful": False}})[0], "unknown")
        self.assertEqual(derive_account({"toggle": {"found": True, "stateful": True}})[0], "work")
        self.assertEqual(derive_account({}, lookup_ok=True)[0], "work")
        self.assertEqual(derive_account({}), ("unknown", "acct_unknown"))

    def test_probe_roundtrip_allowed_but_account_check_fails(self):
        """연결 확인의 시험 낱말 왕복은 계정과 무관하게 한다(화면 조작 확인) — 계정 확인은 실패로 남고 권장은 auto 가 아니다."""
        from lm27.bridge.cli import do_probe
        from lm27.bridge.gate import GateBase, clock_iso_of
        from lm27.bridge.transport_stub import build_reply, item_ids
        from lm27.privacy.detect import SanitizeContext
        from tests.fixtures.wp24.rig import ENV_SAFE, REG, RUN, settings

        def probe_reply(prompt, rid):
            ids = item_ids(prompt)
            return build_reply("ok", rid, ids, {i: {"w": {1: "사과", 2: "바다"}.get(i, "")} for i in ids})[1]
        w = self.world(page={"work_toggle": False, "replies": __import__("collections").deque(
            [FakeReply(text=probe_reply, cps=2000)])})
        _cfg, raw = settings(w.tmp)
        gb = GateBase(SanitizeContext(), None, None, paths=w.paths, clock_iso=clock_iso_of(w.clock),
                      environ=dict(ENV_SAFE), machine_guid="")
        env = {"paths": w.paths, "environ": w.environ, "emit": None,
               "rt_kw": {"clock": w.clock, "session_factory": lambda: w.session("bridge", RUN), "registry": REG,
                         "gate_base": gb, "pc_id": "pc_0123456789abcdef", "raw_cfg": raw}}
        out = do_probe(env, roundtrip=True, lookup=True)
        by = {c["id"]: c for c in out["checks"]}
        self.assertTrue(by["roundtrip"]["ok"], by["roundtrip"])
        self.assertEqual((by["account"]["ok"], by["account"]["code"]), (False, "account_unknown"))
        self.assertEqual(by["lookup_mail"]["code"], "account_unknown")           # 조회는 보내지 않는다
        self.assertNotEqual(out["recommend"], "auto")

    def test_late_ready_session_is_gated_right_before_send(self):
        """열 때 준비되지 않았던 세션(입력창이 늦게 보임)이 단계 중 준비되면 — 판별 전이라 단계 관문을 지나도, 전송 직전 관문이
        그때 계정을 판별해 회사 계정이 아니면 아무것도 넣지 않는다."""
        w = self.world(page={"input_appear_s": 200, "work_toggle": False})
        res, _n, sent = self.analysis(w)
        self.assertEqual((res["state"], res["reason"]), ("skipped", "account_unknown"))
        self.assertEqual(sent, 0)
        w2 = self.world(page={"input_appear_s": 200})
        res2, _n2, sent2 = self.analysis(w2)
        self.assertEqual(res2["state"], "done")
        self.assertGreater(sent2, 0)

    def test_replay_refuses_without_work_account(self):
        from lm27.bridge import cli
        w = self.world(page={"work_toggle": False})
        self.write(w, "t_act", act_rows(2))
        rt = self.open(w, Notices())
        try:
            self.assertEqual(runner.send_block(rt), "account_unknown")
        finally:
            runner.close_runtime(rt)
        self.assertTrue(callable(cli.cmd_replay))


# ───────────────────────── H5 — UserDataDir 정책 ─────────────────────────
class UserDataDirTest(Base):
    def test_forced_user_data_dir_does_not_launch_and_switches_to_manual(self):
        """고치기 전: --user-data-dir 가 무시된 채 기동 → 사용자 본 Edge 를 kill_tree, launch_failed·권장 none 반복. 고친 뒤:
        띄우지 않고 policy_blocked(user_data_dir_forced) → 수동 경로(BR-POLICY-UDD), 기동·종료 0."""
        w = self.world(policy_reg=user_data_dir_reg)
        s = w.session()
        self.assertEqual(s.start(), "policy_blocked")
        self.assertEqual(s.error.get("why"), "user_data_dir_forced")
        self.assertEqual(w.net.launches, [])
        s.close()
        n = Notices()
        self.write(w, "t_act", act_rows(2))
        rt = self.open(w, n, run_id=RUN_B)
        self.assertEqual(rt.transport.kind, "manual")
        runner.close_runtime(rt)
        self.assertIn("BR-POLICY-UDD", n.shown)
        self.assertEqual(w.net.launches, [])

    def test_alive_process_not_on_our_profile_is_not_killed(self):
        w = self.world()
        w.net.launch_mode = "foreign"
        s = w.session()
        self.assertEqual(s.start(), "launch_failed")
        self.assertEqual(s.error.get("why"), "not_our_profile")
        self.assertEqual(w.net.procs[0].killed, 0)
        self.assertIn("kill_refused_not_ours", s.events)
        s.close()

    def test_front_refuses_with_forced_user_data_dir(self):
        w = self.world(policy_reg=user_data_dir_reg)
        r = w.session("bridge", None).front()
        self.assertEqual((r["state"], r["why"]), ("policy_blocked", "user_data_dir_forced"))
        self.assertEqual(w.net.launches, [])

    def test_policy_values_read_only(self):
        from lm27.bridge.session import read_edge_policies
        p = read_edge_policies(user_data_dir_reg)
        self.assertEqual(p["user_data_dir"], "forced")
        self.assertNotIn("Corp", json.dumps(p))                              # 경로 원문은 남기지 않는다
        self.assertEqual(read_edge_policies(lambda h, k, v: None)["browser_signin"], "unset")


# ───────────────────────── M4 — 정책 차단 진단 ─────────────────────────
class ProbeDiagnosisTest(Base):
    def test_policy_blocked_probe_is_not_edge_missing(self):
        """고치기 전: 정책 차단 PC 에서 probe 가 수동 전환 뒤 세션을 잃어 edge=edge_not_found(R-NOAPP). 고친 뒤: Edge 있음 ·
        launch=policy_blocked · 권장 manual."""
        from lm27.bridge.cli import do_probe
        from lm27.bridge.gate import GateBase, clock_iso_of
        from lm27.privacy.detect import SanitizeContext
        from tests.fixtures.wp24.rig import ENV_SAFE, REG, RUN, settings
        w = self.world(policy_reg=policy_blocked_reg)
        w.net.launch_mode = "policy"
        _cfg, raw = settings(w.tmp)
        gb = GateBase(SanitizeContext(), None, None, paths=w.paths, clock_iso=clock_iso_of(w.clock),
                      environ=dict(ENV_SAFE), machine_guid="")
        env = {"paths": w.paths, "environ": w.environ, "emit": None,
               "rt_kw": {"clock": w.clock, "session_factory": lambda: w.session("bridge", RUN), "registry": REG,
                         "gate_base": gb, "pc_id": "pc_0123456789abcdef", "raw_cfg": raw}}
        out = do_probe(env, roundtrip=True)
        by = {c["id"]: c for c in out["checks"]}
        self.assertTrue(by["edge"]["ok"], by["edge"])
        self.assertEqual(by["launch"]["code"], "policy_blocked")
        self.assertEqual(by["policy"]["code"], "policy_blocked_suspect")
        self.assertEqual(out["recommend"], "manual")
        self.assertEqual(w.net.procs[0].killed, 1)                           # 우리 프로필로 뜬 응답 없는 Edge 는 정리


# ───────────────────────── M5 — Copilot Chat 관리자 차단 ─────────────────────────
class ChatBlockedTest(Base):
    def test_repeated_no_input_confirms_then_skips_without_opening(self):
        """고치기 전: 입력창 없는 안내 화면에 매 분석 2분 + 진단 덤프, 확정·유예 없음. 고친 뒤: 서로 다른 날 2번이면 unavailable
        — 그동안 분석은 Edge 를 띄우지 않고 skipped(chat_unavailable), 연결 진단은 늘 다시 본다."""
        w = self.world(page={"input_appear_s": 10 ** 12})
        for rid in (RUN_A, RUN_B):
            s = w.session(run_id=rid)
            self.assertEqual(s.start(), "input_not_found")
            s.close()
            w.clock.advance(86400)
        ca = ChatAccess(w.session().profile, w.cfg, w.clock)
        self.assertEqual(ca.state(), "unavailable")
        n0 = len(w.net.launches)
        res, n, sent = self.analysis(w, run_id=RUN_C, reply=False)
        self.assertEqual((res["state"], res["reason"], res["rc"]), ("skipped", "chat_unavailable", 0))
        self.assertEqual(len(w.net.launches), n0)
        self.assertIn("BR-CHAT-BLOCKED", n.shown)
        w.clock.advance(86400 * (w.cfg.confirm_ttl_days + 1))
        self.assertEqual(ca.state(), "unknown")                              # TTL 지나면 다시 본다

    def test_seeing_input_resets(self):
        w = self.world()
        ca = ChatAccess(w.session().profile, w.cfg, w.clock)
        ca.observe_blocked()
        self.assertEqual(ca.state(), "suspect")
        self.started(w)
        self.assertEqual(ca.state(), "ok")


# ───────────────────────── H13 — Work IQ 단일 토글 ─────────────────────────
class WorkIqTest(Base):
    def test_workiq_off_is_turned_on_once(self):
        """고치기 전: 'Work IQ' 단일 토글을 업무 모드로 인식하지 못해 꺼진 채 조회. 고친 뒤: 꺼져 있으면 한 번 눌러 켠다."""
        w = self.world(page={"work_toggle": False, "workiq": "off"})
        s = self.started(w)
        page = w.net.our_pages()[0]
        self.assertEqual(s.info.work_mode, "work")
        self.assertEqual(page.clicks.count("workiq_toggle"), 1)
        self.assertEqual(s.env.work_toggle, "present")
        self.assertIn("workiq_present", s.env.evidence)

    def test_workiq_on_or_stateless_is_not_clicked(self):
        for st, mode in (("on", "work"), ("nostate", "unknown")):
            with self.subTest(st):
                w = self.world(page={"work_toggle": False, "workiq": st})
                s = self.started(w)
                page = w.net.our_pages()[0]
                self.assertEqual(s.info.work_mode, mode)
                self.assertNotIn("workiq_wrong_click", page.clicks)

    def test_workiq_switch_fails_lookup_skipped_no_nolic(self):
        w = self.world(page={"work_toggle": False, "workiq": "off", "work_switch_ok": False})
        s = self.started(w)
        self.assertEqual(s.info.work_mode, "web")
        self.assertIn("switch_failed", s.env.evidence)

    def test_workiq_off_lookup_reply_not_recorded_as_nolic(self):
        """고치기 전: Work IQ 가 꺼진 채 조회 → 거절 답이 무라이선스로 읽혀 R-NOLIC 을 계정 단위로 기록(2일 뒤 basic 확정·BR-NOLIC).
        고친 뒤: 'Work IQ' 를 말하는 답은 업무 모드 문제 — 능력 기록 없이 skipped(mode_web), 남은 조회도 보내지 않음."""
        from lm27.bridge.env import CopilotEnv
        from lm27.bridge.stages import REGISTRY
        from tests.fixtures.wp24.rig import Rig, window_rows
        env = CopilotEnv(tier="unknown", work_toggle="present", work_mode="unknown", web_grounding="unknown",
                         web_exposed=True)
        r = Rig(stages=[REGISTRY["lookup_mail"], REGISTRY["lookup_teams"]], env=env,
                script={"lookup_mail": ["workiq_off"]})
        self.addCleanup(r.cleanup)
        r.write_ai_in("lookup_mail", window_rows("lookup_mail", [("2026-09-01", "2026-09-07")]))
        r.write_ai_in("lookup_teams", window_rows("lookup_teams", [("2026-09-01", "2026-09-07")]))
        res = r.run()
        self.assertEqual((res["lookup_mail"]["state"], res["lookup_mail"]["reason"]), ("skipped", "mode_web"))
        self.assertEqual((res["lookup_teams"]["state"], res["lookup_teams"]["reason"]), ("skipped", "mode_web"))
        self.assertEqual(r.responder.count["lookup_teams"], 0)
        caps = r.rt.caps
        self.assertEqual({caps.state(s) for s in ("lookup_mail", "lookup_teams", "lookup_calendar")}, {"unknown"})
        self.assertIn("BR-WEB-MODE", r.notified())
        self.assertNotIn("BR-NOLIC", r.notified())
        self.assertIn("workiq_off", r.rt.env.evidence)

    def test_workiq_off_answer_is_not_nolic(self):
        from lm27.bridge import exchange as X
        self.assertEqual(X._lic("To use your work data, turn on Work IQ."), "workiq_off")
        self.assertEqual(X._lic("Work data isn't available"), "nolic")
        self.assertEqual(X._lic("no connected tool"), "noconn")


# ───────────────────────── L11 — 영어 화면·주소·등급 표식 ─────────────────────────
class EnglishUiTest(Base):
    def test_english_model_menu(self):
        """고치기 전: 영어 화면(Auto·Quick response·Think deeper)에서 '빠른 응답'을 못 골라 늘 경고. 고친 뒤: 별칭으로 고른다."""
        w = self.world(page={"model_menu": ("Auto", "Quick response", "Think deeper"), "model_current": "Auto"})
        s = self.started(w)
        n = s.select_model(w.cfg.model_fast)
        self.assertEqual((n.ok, n.picked), (True, "Quick response"))
        n2 = s.select_model(w.cfg.model_fallback)
        self.assertEqual((n2.ok, n2.picked), (True, "Auto"))
        self.assertEqual(S.model_names("빠른 응답|Fast"), ("빠른 응답", "Quick response", "Fast"))

    def test_m365copilot_prefix_and_tier_label(self):
        class M365CopilotPage(FakePage):                 # 접두 목록의 다른 주소(m365copilot.com)에 있는 채팅 화면
            def on_chat(self) -> bool:
                return self.current_url().startswith("https://m365copilot.com/")
        w = self.world(page_cls=M365CopilotPage, page={"tier_label": "premium"})
        w.net.page_factory = lambda url: M365CopilotPage(w.clock, url="https://m365copilot.com/chat", tier_label="premium")
        s = self.started(w)
        self.assertEqual(s.state, "ready")
        self.assertEqual(s.env.tier, "premium")
        self.assertIn("label_premium", s.env.evidence)


# ───────────────────────── M11 — 웹 검색 판별 약속 ─────────────────────────
class WebWordingTest(unittest.TestCase):
    def test_no_unkeepable_promise(self):
        for code in ("BR-WEB-STRICT", "BR-WEB-BLOCK"):
            r = messages.render(code, n=1)
            self.assertNotIn("재판별", r["action"] + r["body"])
            self.assertNotIn("확인되면", r["body"])


# ───────────────────────── O-18 ⑤ — 단계 중 로그인 보류 ─────────────────────────
class MidRunHoldTest(Base):
    def test_partial_then_login_hold_is_not_failed(self):
        """첫 묶음은 답했고 그 뒤 로그인이 풀려 로그인 대기를 다 했지만 로그인되지 않음 — 이 단계는 partial(stop login ·
        login_pending), 다음 단계는 skipped(login_pending). 실패(rc 1)·BR-LOGIN-TIMEOUT 없음."""
        w = self.world()
        self.write(w, "t_act", act_rows(30))
        self.write(w, "t_label", [{"key": "grp:1", "fields": {"kinds": "메일 1", "subjects": ["회의 준비"]}}])
        n = Notices()
        rt = self.open(w, n)
        page = w.net.our_pages()[0]

        def first_then_logout(prompt, rid):
            page.login_until_s = 10 ** 9                                     # 첫 답(일부 항목만) 뒤 로그인 풀림
            from lm27.bridge.transport_stub import build_reply, item_ids
            ids = item_ids(prompt)
            return build_reply("partial:0.5", rid, ids, {i: {"act": "info", "conf": "m"} for i in ids})[1]
        page.replies.append(FakeReply(text=first_then_logout, cps=2000))
        res = runner.run_stages(rt, [ActStage(), LabelStage()])
        runner.close_runtime(rt)
        a, b = res["t_act"], res["t_label"]
        self.assertEqual((a["state"], a["stop_kind"], a["reason"], a["rc"]), ("partial", "login", "login_pending", 2))
        self.assertGreater(a["items_ai"], 0)
        self.assertEqual((b["state"], b["reason"]), ("skipped", "login_pending"))
        self.assertNotIn("BR-LOGIN-TIMEOUT", n.shown)
        self.assertNotEqual(runner.worst_rc(res), 1)


class RegistryDefaultsTest(unittest.TestCase):
    def test_bridge_registry_defaults(self):
        reg = json.loads(Path(__file__).resolve().parents[2].joinpath("config", "settings_registry.json")
                         .read_text("utf-8"))["keys"]
        hosts = reg["bridge.loginHosts"]["default"]
        for h in ("login.windows.net", ".microsoftonline.com", "mysignins.microsoft.com", "login.live.com"):
            self.assertIn(h, hosts)
        self.assertIn("https://m365copilot.com/", reg["bridge.chatUrlPrefixes"]["default"])
        wml = reg["bridge.dom.workModeLabels"]
        self.assertEqual(sorted(wml["keys"]), sorted(wml["default"]))
        self.assertIn("Work IQ", wml["default"]["toggle"])


if __name__ == "__main__":
    unittest.main()
