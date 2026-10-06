# -*- coding: utf-8 -*-
"""웹 수집기·탐침의 로그인 보류·개인 계정(계약 v1.3 §0.8 V18 — 회사 계정이 없는 PC) · 탐침은 로그인을 기다리지 않음(V10).

  · 세션이 로그인 보류 상태에서 짧게 확인만 하고 끝났으면(``login_check == "pending"``) 상태 줄에 ``login_pending: true`` —
    연결자가 ``skipped=login_pending`` 으로 넘긴다. 개인 계정 화면을 봤으면 ``login_account: "personal"``.
  · 개인 계정의 사서함·팀즈(outlook.live.com · teams.live.com)에 닿으면 읽지 않는다 — R-LOGIN + 개인 계정, 세션에 보류.
  · 회사 사서함에 닿으면 세션에 로그인 확인(보류 해제)을 알린다.
  · 모르는 로그인 화면(회사 SSO)은 세션이 정한 대기(보류 중이면 짧게)만큼만 기다린다.
  · P-OWA·P-WEB 탐침은 첫 판정만 하고 로그인을 기다리지 않는다(세션 wait_page 0회) — 보류 사실을 web_login 값에 싣는다.
브라우저·네트워크 0(대역 세션 ``tests\\fixtures\\wp26\\cdpfake.py``).
"""
import io
import json
import unittest

from lm27.bridge.clock import VirtualClock
from lm27.bridge.session import EdgeInfo
from tests.fixtures.wp26 import webkit as K
from tests.fixtures.wp26.cdpfake import FakeSession, factory

W, T, P, PT = K.OWA, K.TW, K.POWA, K.PTW
TODO = "mail.owa:2026-09-01:2026-09-15"
EDGE_OK = EdgeInfo(path="C:/edge/msedge.exe", version="129.0.1.2")


class V18Session(FakeSession):
    """V18 훅(login_check · login_account · login_ok · mark_login_pending · note_login_account · login_wait_s)을 더한 대역."""

    def __init__(self, *, check="", wait_s=60.0, **kw):
        super().__init__(**kw)
        self.login_check = check
        self.login_account = ""
        self.wait_s = wait_s
        self.hooks: list = []
        self.wait_pages = 0

    def wait_page(self, dl=None) -> str:
        self.wait_pages += 1
        return super().wait_page(dl)

    def login_wait_s(self) -> float:
        return self.wait_s

    def login_ok(self) -> None:
        self.hooks.append("login_ok")

    def mark_login_pending(self) -> None:
        self.hooks.append("mark_login_pending")

    def note_login_account(self, account: str) -> None:
        self.login_account = account
        self.hooks.append("note:" + account)


class _Base(unittest.TestCase):
    def setUp(self):
        self.sb = K.Sandbox()
        self.addCleanup(self.sb.cleanup)

    def blanks(self):
        return str(self.sb.write_json("blanks.json", [{"todo_id": TODO, "date_range": ["2026-09-01", "2026-09-15"],
                                                       "kind_axis": "mail_in"}]))

    def owa(self, session, clock=None):
        return K.run_owa(self.sb, ["--kind", "mail", "--blanks-file", self.blanks()],
                         session_factory=factory(session), clock=clock)

    def probe(self, mod, session, environ=None):
        out, err = io.StringIO(), io.StringIO()
        mod.main([], environ=environ or {}, paths=self.sb.paths, cfg=self.sb.cfg, clock=VirtualClock(), now=K.NOW,
                 out=out, err=err, session_factory=factory(session), edge_info=lambda: EDGE_OK)
        return json.loads(out.getvalue().strip().splitlines()[-1])


class CollectorTest(_Base):
    def test_pending_short_check_marks_status(self):
        rc, st, _ = self.owa(V18Session(login=True, check="pending"))
        self.assertEqual((rc, st["reasons"]), (2, ["R-LOGIN"]))
        self.assertIs(st["login_pending"], True)
        self.assertNotIn("login_account", st)

    def test_first_login_wait_not_pending(self):
        rc, st, _ = self.owa(V18Session(login=True, check="wait"))
        self.assertEqual(rc, 2)
        self.assertNotIn("login_pending", st)                       # 처음 다 기다린 것 — 연결자가 skipped 로 바꾸지 않는다

    def test_personal_mailbox_not_read(self):
        s = V18Session(host="outlook.live.com", owa={"inbox": [[K.owa_item(K.KIM, "개인 메일", "2026-09-03", key="p1")]]})
        rc, st, _ = self.owa(s)
        self.assertEqual((rc, st["reasons"], st["login_account"]), (2, ["R-LOGIN"], "personal"))
        self.assertEqual(st["counts"]["personal_account"], 1)
        self.assertIn("note:personal", s.hooks)
        self.assertIn("mark_login_pending", s.hooks)
        self.assertEqual(self.sb.rows("mail", "mail.owa"), [])       # 개인 사서함은 업무 자료로 읽지 않는다

    def test_company_mailbox_confirms_login(self):
        s = V18Session(owa={"inbox": [[K.owa_item(K.KIM, "과제A 회의", "2026-09-03", key="i1")]], "sent": [[]]})
        rc, _st, err = self.owa(s)
        self.assertEqual(rc, 0, err)
        self.assertIn("login_ok", s.hooks)                         # 보류 해제(회사 사서함 확인)

    def test_unknown_host_waits_session_login_wait(self):
        clock = VirtualClock()
        s = V18Session(host="sso.corp.example", wait_s=30.0)
        t0 = clock.mono()
        rc, st, _ = self.owa(s, clock=clock)
        self.assertEqual((rc, st["reasons"]), (2, ["R-LOGIN"]))
        self.assertLessEqual(clock.mono() - t0, 30.0 + 40)         # 세션이 정한 대기(보류 30초)만 — 10분이 아니다
        self.assertIn("mark_login_pending", s.hooks)               # 다 기다렸다 — 다음은 짧게

    def test_teams_personal_host(self):
        s = V18Session(host="teams.live.com", teams={"chats": [[]]})
        rc, st, _ = K.run_tw(self.sb, [], session_factory=factory(s))
        self.assertEqual((rc, st["reasons"], st.get("login_account")), (2, ["R-LOGIN"], "personal"))

    def test_fake_screen_login_facts(self):
        rc, st, _ = K.run_owa(self.sb, ["--kind", "cal", "--from", "2026-09-01", "--to", "2026-09-07"],
                              fake={"login": True, "login_pending": True, "login_account": "personal"})
        self.assertEqual((rc, st["login_pending"], st["login_account"]), (2, True, "personal"))


class ProbeTest(_Base):
    def test_owa_probe_does_not_wait_for_login(self):
        s = V18Session(login=True)
        res = self.probe(P, s)
        self.assertEqual(s.wait_pages, 0)                           # 첫 판정만(로그인 대기는 수집기가 한 번 — V10)
        wl = res["caps"]["web_login"]
        self.assertEqual((wl["status"], wl["reasons"]), ("fail", ["R-LOGIN"]))
        self.assertIs(wl["value"]["login_pending"], False)

    def test_owa_probe_reports_pending_and_personal(self):
        s = V18Session(login=True, check="pending")
        s.login_account = "personal"
        wl = self.probe(P, s)["caps"]["web_login"]
        self.assertEqual((wl["value"]["login_pending"], wl["value"]["account"]), (True, "personal"))

    def test_teams_probe_does_not_wait_for_login(self):
        s = V18Session(login=True, check="pending")
        res = self.probe(PT, s)
        self.assertEqual(s.wait_pages, 0)
        self.assertIs(res["caps"]["teams.web"]["value"]["login_pending"], True)


if __name__ == "__main__":
    unittest.main()
