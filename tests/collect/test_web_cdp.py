# -*- coding: utf-8 -*-
"""WP-26 실제 화면 경로 시험 — ``CdpOwaScreen`` · ``CdpTeamsScreen`` 을 EdgeSession 대역(tests\\fixtures\\wp26\\cdpfake.py)으로
돌린다(브라우저·네트워크 0). 실물 ``EdgeSession`` 은 ``LM_NO_BROWSER=1`` 로만(Edge 를 띄우지 않는다 — 계약 §11.3).

검사: 폴더 이동·검색 질의 입력(Input.insertText + Enter)·목록 되감기·**보낸 항목만 열기**(받은 메일은 열지 않는다 — X-132)·
주 보기 이동, 로그인 화면의 AADSTS 조건부 액세스 → R-CA, 알려지지 않은 로그인 호스트 → 로그인 대기 → R-LOGIN, 세션 시작
실패 상태 → rc·사유(계약 §8.1), Teams 대화 ID 로 다시 찾아 열기·위로 되감기·gone → R-ROOMGONE, 자기 탭만 정리(close)."""
import unittest
from datetime import date

from lm27.collect import rcmap
from tests.fixtures.wp26 import webkit as K
from tests.fixtures.wp26.cdpfake import FakeSession, factory

W, T = K.OWA, K.TW
R_ = "R-"
TODO = "mail.owa:2026-09-01:2026-09-15"


class _Base(unittest.TestCase):
    def setUp(self):
        self.sb = K.Sandbox()
        self.addCleanup(self.sb.cleanup)

    def blanks(self):
        return str(self.sb.write_json("blanks.json", [{"todo_id": TODO, "date_range": ["2026-09-01", "2026-09-15"],
                                                       "kind_axis": "mail_in"}]))

    def owa(self, session, *extra):
        return K.run_owa(self.sb, ["--kind", "mail", "--blanks-file", self.blanks(), *extra],
                         session_factory=factory(session))


class OwaCdpTest(_Base):

    def session(self, **kw):
        inbox = [[K.owa_item(K.KIM, "과제A 견적 요청", "2026-09-03", key="i1", head=["2026년 9월 3일 오전 8:00"])],
                 [K.owa_item(K.PEER, "회의록", "2026-09-10", key="i2")]]
        sent = [[K.owa_item("받는 사람 김철수", "RE: 과제A 견적 요청", "2026-09-04", key="s1",
                            head=["2026년 9월 4일 (금) 오후 2:30"])]]
        return FakeSession(owa={"inbox": inbox, "sent": sent}, **kw)

    def test_search_scroll_and_open_sent_only(self):
        s = self.session()
        rc, st, err = self.owa(s)
        self.assertEqual(rc, 0, err)
        self.assertEqual((s.role, s.closed), ("owa", True))
        self.assertEqual([u.rsplit("/", 2)[-2:] for u in s.gotos], [["mail", "inbox"], ["mail", "sentitems"]])
        texts = [p["text"] for m, p in s.calls if m == "Input.insertText"]
        self.assertEqual(texts, ["received>=2026-09-01 received<=2026-09-15"] * 2)
        self.assertEqual(sum(1 for m, p in s.calls if m == "Input.dispatchKeyEvent" and p.get("key") == "Enter"), 6)
        self.assertEqual(s.opened, [("sent", 0)])                                       # 받은 메일은 열지 않는다
        rows = {r["subject_masked"]: r for r in self.sb.rows("mail", "mail.owa")}
        self.assertEqual(rows["[과제:P-0001] 견적 요청"]["ts_precision"], "date")        # 머리가 있어도 받은 메일은 날짜만
        self.assertEqual(rows["회의록"]["ts_precision"], "date")                         # 둘째 화면(되감기)도 읽었다
        self.assertEqual((rows["RE: [과제:P-0001] 견적 요청"]["ts_precision"], rows["RE: [과제:P-0001] 견적 요청"]["ts_utc"]),
                         ("minute", "2026-09-04T05:30:00Z"))
        self.assertEqual(st["counts"]["search"], 2)

    def test_login_conditional_access_and_plain_login(self):
        rc, st, _ = self.owa(self.session(login=True, aadsts="53003"))
        self.assertEqual((rc, st["reasons"], st["counts"]["aadsts"]), (2, [R_ + "CA"], 53003))
        rc, st, _ = self.owa(self.session(login=True))
        self.assertEqual((rc, st["reasons"]), (2, [R_ + "LOGIN"]))
        self.assertFalse(self.sb.paths.store_root().exists())

    def test_login_expires_mid_run(self):
        s = self.session(login_paths=("/sentitems",))                                  # 받은 편지함 뒤 보낸 편지함에서 만료
        rc, st, _ = self.owa(s)
        self.assertEqual((rc, st["reasons"], st["partial"], st["counts"]["session"]),
                         (2, [R_ + "LOGIN"], True, "login_required"))
        self.assertEqual(len(self.sb.rows("mail", "mail.owa")), 2)                      # 읽은 것은 저장(조각은 미완료)
        self.assertEqual(self.sb.cursor("mail.owa"), {})                                # 끝나지 않은 조각은 커서에 없다
        self.assertEqual(s.opened, [])

    def test_unknown_host_waits_then_login_required(self):
        rc, st, _ = self.owa(self.session(host="sso.corp.example"))
        self.assertEqual((rc, st["reasons"]), (2, [R_ + "LOGIN"]))                      # 회사 SSO 화면 = 로그인 대기
        self.assertEqual(st["counts"]["host_unexpected"], 1)

    def test_session_start_failures(self):
        cases = (("policy_blocked", {}, R_ + "EDGEPOL"), ("edge_not_found", {}, R_ + "NOAPP"),
                 ("edge_not_found", {"why": "no_browser"}, R_ + "TRANSPORT"), ("lock_busy", {}, R_ + "TRANSPORT"),
                 ("port_exhausted", {}, R_ + "TRANSPORT"), ("profile_busy", {}, R_ + "TRANSPORT"))
        for state, error, why in cases:
            s = self.session(start_state=state, error=error)
            rc, st, _ = self.owa(s)
            self.assertEqual((rc, st["reasons"], st["counts"]["session"]), (3, [why], state), state)
            self.assertTrue(s.closed)

    def test_edge_not_found_stage_skipped_not_transport(self):
        """W1b 회귀(계약 §0.7 C4 보강): Edge 없는 백필 PC — 수집기 rc 3 + R-NOAPP(경고) 가 수송 실패로 접히지 않고
        원장 blocked · 단계 skipped · collect rc 4(다른 단계가 저장했으면 0)가 된다(매 실행 partial·rc 2 가 아님)."""
        s = self.session(start_state="edge_not_found", error={})
        rc, st, _ = self.owa(s)
        self.assertEqual((rc, st["reasons"]), (3, [R_ + "NOAPP"]))
        self.assertEqual(rcmap.translate_cell(rc, st["reasons"], st)["status"], "blocked")
        o = rcmap.stage_outcome(rc, st["reasons"], st)
        self.assertEqual((o["state"], o["reason"], o["stop_kind"]), ("skipped", R_ + "NOAPP", None))
        self.assertEqual(rcmap.collect_rc([o]), 4)
        self.assertEqual(rcmap.collect_rc([o, {"state": "done", "items_ok": 3}]), 0)

    def test_calendar_weeks(self):
        cal = {"2026-09-01": [K.owa_event("과제A 주간 회의", date(2026, 9, 1), (9, 0), (10, 0), "3층 회의실")],
               "2026-09-09": [K.owa_event("검토 회의", date(2026, 9, 9), (14, 0), (15, 0), "Microsoft Teams 모임")]}
        s = FakeSession(owa={"cal": cal})
        rc, st, _ = K.run_owa(self.sb, ["--kind", "cal", "--from", "2026-09-01", "--to", "2026-09-13"],
                              session_factory=factory(s))
        self.assertEqual(rc, 0)
        self.assertEqual([u.split("/calendar/view/week/")[1] for u in s.gotos], ["2026/8/31", "2026/9/7"])
        self.assertEqual(len(self.sb.rows("cal", "cal.owa")), 2)

    def test_real_edge_session_no_browser(self):
        rc, st, _ = K.run_owa(self.sb, ["--kind", "mail", "--blanks-file", self.blanks()],
                              environ={"LM_NO_BROWSER": "1"})
        self.assertEqual((rc, st["reasons"], st["counts"]["session"]), (3, [R_ + "TRANSPORT"], "edge_not_found"))
        self.assertFalse(self.sb.paths.store_root().exists())


class TeamsCdpTest(_Base):

    def test_open_by_id_scroll_up_and_gone(self):
        d = date(2026, 9, 21)
        a, b, g = K.tid(1, "group"), K.tid(2, "one"), K.tid(3, "group")
        rooms = [[K.tw_room(0, a, "과제A 설계"), K.tw_room(1, b, K.KIM)], [K.tw_room(2, g, "사라진 방")]]
        msgs = {a: [[K.tw_sep(d), K.tw_msg(K.KIM, "최근 메시지", h=10, d=d, iso=True, mid="1758000000001")],
                    [K.tw_sep(d), K.tw_msg(K.PEER, "앞선 메시지", h=9, d=d, iso=True, mid="1758000000000")]],
                b: [[K.tw_sep(d), K.tw_msg(K.ME, "1:1 회신", h=11, d=d, iso=True, mid="1758000000002")]]}
        s = FakeSession(teams={"chats": rooms, "msgs": msgs, "gone": [g]})
        rc, st, err = K.run_tw(self.sb, ["--from", "2026-09-01", "--to", "2026-09-30", "--no-channels", "--no-activity"],
                               session_factory=factory(s))
        self.assertEqual(rc, 0, err)
        self.assertEqual((s.role, s.closed), ("teams_web", True))
        self.assertTrue(s.gotos[0].startswith("https://teams.microsoft.com/"))
        self.assertEqual([x for x in s.opened if x[0] == "room"], [("room", a), ("room", b)])
        self.assertIn("tw_scroll_up", s.evals)
        self.assertEqual(st["counts"]["chats_listed"], 3)                                # 목록 두 화면(가상 스크롤)
        self.assertIn(R_ + "ROOMGONE", st["reasons"])
        rows = {r["body_masked"]: r for r in self.sb.rows("teams", "teams.web")}
        self.assertEqual(set(rows), {"최근 메시지", "앞선 메시지", "1:1 회신"})
        self.assertEqual({r["ts_precision"] for r in rows.values()}, {"exact"})
        self.assertEqual(rows["1:1 회신"]["chat_type"], "1:1")

    def test_teams_login_and_no_browser(self):
        s = FakeSession(login=True, aadsts="53003", teams={})
        rc, st, _ = K.run_tw(self.sb, ["--no-channels"], session_factory=factory(s))
        self.assertEqual((rc, st["reasons"]), (2, [R_ + "CA"]))
        s = FakeSession(start_state="policy_blocked", teams={})                          # CT-11 Edge 정책 차단
        rc, st, _ = K.run_tw(self.sb, ["--no-channels"], session_factory=factory(s))
        self.assertEqual((rc, st["reasons"], st["counts"]["session"]), (3, [R_ + "EDGEPOL"], "policy_blocked"))
        self.assertTrue(s.closed)
        rc, st, _ = K.run_tw(self.sb, ["--no-channels"], environ={"LM_NO_BROWSER": "1"})
        self.assertEqual((rc, st["reasons"], st["counts"]["session"]), (3, [R_ + "TRANSPORT"], "edge_not_found"))
        s = FakeSession(start_state="edge_not_found", teams={})                          # C4 보강 — Edge 미설치
        rc, st, _ = K.run_tw(self.sb, ["--no-channels"], session_factory=factory(s))
        self.assertEqual((rc, st["reasons"]), (3, [R_ + "NOAPP"]))
        o = rcmap.stage_outcome(rc, st["reasons"], st)
        self.assertEqual((o["state"], o["reason"]), ("skipped", R_ + "NOAPP"))
        self.assertEqual(rcmap.collect_rc([o]), 4)


class JsTest(unittest.TestCase):
    """페이지에 보내는 JS 조각: 머리 표식(가짜 CDP 처리기 선택) · 값만 돌려줌 · 쿠키·저장소 접근 0."""

    def test_markers_and_no_storage_access(self):
        snippets = [W.js_owa_list(), W.js_owa_scroll(), W.js_owa_focus_search(), W.js_owa_clear_search(),
                    W.js_owa_open(3), W.js_owa_head(), W.js_owa_cal(), W.js_aadsts(), T.js_tw_list("chats"),
                    T.js_tw_list_scroll("channels"), T.js_tw_open("chats", K.tid(1), 0), T.js_tw_msgs(),
                    T.js_tw_scroll_up(), T.js_tw_pane(), T.js_tw_nav("activity")]
        for js in snippets:
            self.assertRegex(js, r"^/\*LM27:[a-z_]+\*/\(function\(\)\{")
            low = js.lower()
            for bad in ("document.cookie", "localstorage", "sessionstorage", "indexed" + "db", "fetch(", "xmlhttprequest"):
                self.assertNotIn(bad, low)


if __name__ == "__main__":
    unittest.main()
