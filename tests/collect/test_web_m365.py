# -*- coding: utf-8 -*-
"""회사 PC(계정 있음) 웹 경로 위험 재현·회귀 — M365 공식 문서 대조 결과(``.wf\\m365_research.json``)의 팀즈·웹 묶음.

  · M7  Teams 딥 링크 = 문서 형식(대화: ``/l/message/<chatId>/<messageId>?context={"contextType":"chat"}``, chatId 를 %3A·%40
        으로 바꾸지 않음) · 활동 항목의 원래 링크(href)를 그대로 · 채널(@thread.tacv2)은 tenantId·groupId 없이 딥 링크를 만들지
        않고 목록에서 연다 · 이동이 안 되면 그 방만 R-ROOMGONE(경로 전체 중단 없음) · 시작 주소는 문서 주소(/v2/ 없음) ·
        현재 호스트(teams.cloud.microsoft)를 그대로 쓴다.
  · M8  방을 눌렀는데 화면이 그대로면(이전 방) 그 방 chat_id 로 이전 방 메시지를 저장하지 않고 체크포인트도 옮기지 않는다
        (R-ROOMGONE). 처음부터 열려 있던 방은 정상으로 읽는다(항목 선택 상태·주소의 대화 ID 로 확인).
  · M9  통합(Combined) 보기 — 목록 머리 항목(aria-expanded · 대화 ID 없음)을 순번으로 누르지 않는다 · 앱 막대에 '팀' 단추가
        없으면 채널 목록 순회를 건너뛰고 layout=combined · 채팅 목록 안 채널은 channel 유형.
  · M12 AADSTS50158(외부 보안 과제 — 사용 약관·타사 MFA)은 조건부 액세스 차단(R-CA)이 아니라 로그인 진행(R-LOGIN).
  · H1(웹 쪽) 장치 기반 조건부 액세스(50005·50097·53000·53001)는 Edge 프로필 로그인으로 풀 수 있다 — R-CA(구조·확정)가
        아니라 R-LOGIN + counts.aadsts_kind=device. 정책 차단(53003 등)은 R-CA 그대로.
  · L2  하이브리드 Exchange(온프레미스 사서함) — 로그인 대기가 Microsoft 밖 호스트에서 끝나면 counts.host_class=nonms ·
        login_detail=nonms_host(호스트 이름은 싣지 않음).
  · *.cloud.microsoft 도착 = 정상(outlook.cloud.microsoft · teams.cloud.microsoft) — 다음 이동은 그 호스트로.
  · L13 원격·가상 데스크톱 세션이면 counts.remote_session=1(문서상 Teams 웹은 VDI 미지원 — 진단).
브라우저·네트워크 0(대역 세션 ``tests\\fixtures\\wp26\\cdpfake.py``)."""
import unittest
from datetime import date
from urllib.parse import urlsplit

from lm27.collect import rcmap
from tests.fixtures.wp26 import webkit as K
from tests.fixtures.wp26.cdpfake import FakeSession, factory

W, T = K.OWA, K.TW
R_ = "R-"
D = date(2026, 9, 21)
TODO = "mail.owa:2026-09-01:2026-09-15"
NO_LISTS = ["--from", "2026-09-01", "--to", "2026-09-30"]
CHAT_CTX = "?context=%7B%22contextType%22%3A%22chat%22%7D"


def one(author, body, mid, *, h=10):
    return [K.tw_sep(D), K.tw_msg(author, body, h=h, d=D, iso=True, mid=mid)]


class _Base(unittest.TestCase):
    def setUp(self):
        self.sb = K.Sandbox()
        self.addCleanup(self.sb.cleanup)

    def tw(self, s, *extra):
        return K.run_tw(self.sb, [*NO_LISTS, *extra], session_factory=factory(s))

    def rows(self):
        return {r["body_masked"]: r for r in self.sb.rows("teams", "teams.web")}

    def blanks(self):
        return str(self.sb.write_json("blanks.json", [{"todo_id": TODO, "date_range": ["2026-09-01", "2026-09-15"],
                                                       "kind_axis": "mail_in"}]))

    def owa(self, s, clock=None):
        return K.run_owa(self.sb, ["--kind", "mail", "--blanks-file", self.blanks()], session_factory=factory(s),
                         clock=clock)


class TeamsPaneTest(_Base):
    """M8 — 화면 전환 확인."""

    def test_m8_stuck_pane_not_misattributed(self):
        a, b = K.tid(1, "group"), K.tid(2, "group")
        s = FakeSession(teams={"chats": [[K.tw_room(0, a, "과제A 설계"), K.tw_room(1, b, "과제B 양산")]],
                               "msgs": {a: [one(K.KIM, "첫 방 메시지", "1758000000001")],
                                        b: [one(K.PEER, "둘째 방 메시지", "1758000000002")]},
                               "stuck": [b], "sel": False})
        rc, st, err = self.tw(s, "--no-channels", "--no-activity")
        self.assertEqual(rc, 0, err)
        rows = self.sb.rows("teams", "teams.web")
        self.assertEqual([r["body_masked"] for r in rows], ["첫 방 메시지"],
                         "이전 방 메시지가 다음 방 chat_id 로 다시 저장되면 안 된다")
        self.assertEqual(len({r["chat_key"] for r in rows}), 1)
        self.assertIn(R_ + "ROOMGONE", st["reasons"])
        self.assertTrue(st["partial"])
        self.assertEqual((st["counts"]["rooms_gone"], st["counts"]["rooms_retried"], st["counts"]["pane_stuck"]),
                         (1, 1, 2))                                                     # 다른 방을 연 뒤 한 번 더 — 그래도 그대로
        self.assertEqual(len(self.sb.cursor("teams.web")["rooms"]), 1)                  # 둘째 방 체크포인트 없음 — 다음에 다시

    def test_m8_room_already_open_is_read(self):
        """앱이 처음부터 열어 둔 방을 누르면 화면이 안 바뀐다 — 선택 상태로 같은 방임을 확인하면 정상으로 읽는다."""
        a, b = K.tid(3, "group"), K.tid(4, "group")
        s = FakeSession(teams={"chats": [[K.tw_room(0, a, "과제A 설계"), K.tw_room(1, b, "과제B 양산")]],
                               "msgs": {a: [one(K.KIM, "열려 있던 방", "1758000000003")],
                                        b: [one(K.PEER, "두 번째 방", "1758000000004")]},
                               "start_room": a})
        rc, st, err = self.tw(s, "--no-channels", "--no-activity")
        self.assertEqual(rc, 0, err)
        self.assertEqual(set(self.rows()), {"열려 있던 방", "두 번째 방"})
        self.assertNotIn(R_ + "ROOMGONE", st["reasons"])
        self.assertEqual(st["counts"].get("pane_already"), 1)

    def test_m8_already_open_unverifiable_is_gone(self):
        """선택 상태·대화 ID·제목 어느 것으로도 같은 방임을 확인하지 못하면 읽지 않는다(오귀속보다 누락 표시)."""
        a = K.tid(5, "group")
        s = FakeSession(teams={"chats": [[K.tw_room(0, a, "과제A 설계")]],
                               "msgs": {a: [one(K.KIM, "확인 못 한 방", "1758000000005")]},
                               "start_room": a, "sel": False})
        rc, st, _ = self.tw(s, "--no-channels", "--no-activity")
        self.assertEqual(self.rows(), {})
        self.assertIn(R_ + "ROOMGONE", st["reasons"])

    def test_m8_preopened_room_read_on_second_pass(self):
        """확인 단서(선택 상태·주소·제목)가 없어도, 처음부터 열려 있던 방은 다른 방을 연 뒤 다시 눌러 바뀜으로 확인해 읽는다."""
        a, b = K.tid(31, "group"), K.tid(32, "group")
        s = FakeSession(teams={"chats": [[K.tw_room(0, a, "과제A 설계"), K.tw_room(1, b, "과제B 양산")]],
                               "msgs": {a: [one(K.KIM, "처음 열린 방", "1758000000031")],
                                        b: [one(K.PEER, "두 번째 방", "1758000000032")]},
                               "start_room": a, "sel": False})
        rc, st, err = self.tw(s, "--no-channels", "--no-activity")
        self.assertEqual(rc, 0, err)
        rows = self.sb.rows("teams", "teams.web")
        self.assertEqual(sorted(r["body_masked"] for r in rows), ["두 번째 방", "처음 열린 방"])
        self.assertEqual(len({r["chat_key"] for r in rows}), 2)
        self.assertEqual((st["counts"]["rooms_retried"], st["counts"].get("rooms_gone", 0)), (1, 0))
        self.assertNotIn(R_ + "ROOMGONE", st["reasons"])

    def test_m8_address_conversation_id_mismatch(self):
        """주소의 대화 ID 가 누른 방과 다르면(다른 방이 열림) 그 방은 gone."""
        a, b, c = K.tid(6, "group"), K.tid(7, "group"), K.tid(8, "group")
        s = FakeSession(teams={"chats": [[K.tw_room(0, a, "과제A"), K.tw_room(1, b, "과제B")]],
                               "msgs": {a: [one(K.KIM, "A", "1758000000006")], b: [one(K.KIM, "B", "1758000000007")],
                                        c: [one(K.KIM, "엉뚱한 방", "1758000000008")]},
                               "cid": True, "sel": False})
        orig = s._js_tw_open

        def wrong(expr):
            r = orig(expr)
            if s.room == b:
                s.room = c                                  # b 를 눌렀는데 c 가 열림
            return r
        s._js_tw_open = wrong
        rc, st, _ = self.tw(s, "--no-channels", "--no-activity")
        self.assertEqual(set(self.rows()), {"A"})
        self.assertEqual(st["counts"]["pane_mismatch"], 1)


    def test_m8_stale_address_id_ignored(self):
        """방을 바꿔도 갱신되지 않는 주소(늘 같은 대화 ID)는 단서로 쓰지 않는다 — 정상 방을 gone 으로 버리지 않게."""
        a, b, z = K.tid(9, "group"), K.tid(19, "group"), K.tid(29, "group")
        s = FakeSession(teams={"chats": [[K.tw_room(0, a, "과제A"), K.tw_room(1, b, "과제B")]],
                               "msgs": {a: [one(K.KIM, "A", "1758000000009")], b: [one(K.KIM, "B", "1758000000019")]},
                               "cid": "fixed:" + z, "sel": False})
        rc, st, err = self.tw(s, "--no-channels", "--no-activity")
        self.assertEqual(rc, 0, err)
        self.assertEqual(set(self.rows()), {"A", "B"})
        self.assertNotIn("pane_mismatch", st["counts"])


class TeamsDeepLinkTest(_Base):
    """M7 — 딥 링크 공식 형식."""

    def _session(self, act_items, **teams):
        a = K.tid(10, "group")
        model = {"chats": [[K.tw_room(0, a, "과제A 설계")]], "msgs": {a: [one(K.KIM, "목록 방", "1758000000010")]},
                 "activity": [act_items]}
        model["msgs"].update(teams.pop("msgs", {}))
        model.update(teams)
        return FakeSession(teams=model)

    def test_m7_start_url_is_documented(self):
        s = self._session([])
        self.tw(s, "--no-channels", "--no-activity")
        self.assertEqual(s.gotos[0], "https://teams.microsoft.com/")                     # 문서 주소 — /v2/ 아님

    def test_m7_chat_deep_link_documented_format(self):
        x = K.tid(11, "one")
        s = self._session([{"tid": x, "mid": "1563480968434", "mention": True, "label": "김철수 멘션"}],
                          msgs={x: [one(K.KIM, "멘션 방 메시지", "1563480968434")]})
        rc, st, err = self.tw(s, "--no-channels")
        self.assertEqual(rc, 0, err)
        deep = [u for u in s.gotos if "/l/message/" in u]
        self.assertEqual(deep, [f"https://teams.microsoft.com/l/message/{x}/1563480968434{CHAT_CTX}"])
        self.assertNotIn("%3A", urlsplit(deep[0]).path)                                # 경로의 chatId 는 그대로(':'·'@')
        self.assertIn("멘션 방 메시지", self.rows())

    def test_m7_activity_href_used_as_is(self):
        x = K.tid(12, "group")
        href = f"https://teams.microsoft.com/l/message/{x}/1758000000012?context=%7B%22contextType%22%3A%22chat%22%7D"
        s = self._session([{"tid": x, "mid": "1758000000012", "href": href, "label": "활동"}],
                          msgs={x: [one(K.KIM, "링크 방", "1758000000012")]})
        self.tw(s, "--no-channels")
        self.assertEqual([u for u in s.gotos if "/l/message/" in u], [href])

    def test_m7_foreign_href_ignored(self):
        """활동 링크가 Teams 호스트가 아니면(외부 주소) 따라가지 않고 문서 형식으로 만든다."""
        x = K.tid(13, "group")
        s = self._session([{"tid": x, "mid": "1758000000013", "href": f"https://evil.example/l/message/{x}/1"}],
                          msgs={x: [one(K.KIM, "x", "1758000000013")]})
        self.tw(s, "--no-channels")
        deep = [u for u in s.gotos if "/l/message/" in u]
        self.assertEqual([urlsplit(u).hostname for u in deep], ["teams.microsoft.com"])

    def test_m7_channel_without_group_id_no_deep_link(self):
        ch = K.tid(14, "channel")
        s = self._session([{"tid": ch, "mid": "1758000000014", "label": "채널 답글"}],
                          msgs={ch: [one(K.PEER, "채널 메시지", "1758000000014")]})
        rc, st, err = self.tw(s, "--no-channels")
        self.assertEqual([u for u in s.gotos if "/l/message/" in u], [])               # tenantId·groupId 없이 만들지 않음
        self.assertIn(R_ + "ROOMGONE", st["reasons"])                                   # 목록에 없으면 그 방만
        self.assertIn("목록 방", self.rows())                                            # 경로 전체 중단 없음

    def test_m7_deep_link_lands_elsewhere_is_room_gone(self):
        """딥 링크가 다른 화면(Teams 진입 화면 등 — 로드 실패)에 닿으면 경로 전체가 아니라 그 방만."""
        x, y = K.tid(15, "group"), K.tid(16, "group")
        s = self._session([{"tid": x, "mid": "1758000000015"}, {"tid": y, "mid": "1758000000016"}],
                          msgs={x: [one(K.KIM, "x 방", "1758000000015")], y: [one(K.KIM, "y 방", "1758000000016")]},
                          deep_state="input_not_found")
        rc, st, err = self.tw(s, "--no-channels")
        self.assertEqual(rc, 0, err)
        self.assertEqual(st["counts"]["rooms_gone"], 2)
        self.assertNotIn("session", st["counts"])                                       # ScreenStop 아님
        self.assertEqual(set(self.rows()), {"목록 방"})

    def test_m7_cloud_host_kept(self):
        x = K.tid(17, "one")
        s = self._session([{"tid": x, "mid": "1758000000017"}], msgs={x: [one(K.KIM, "클라우드", "1758000000017")]})
        s.host_override = "teams.cloud.microsoft"
        rc, st, err = self.tw(s, "--no-channels")
        self.assertEqual(rc, 0, err)
        deep = [u for u in s.gotos if "/l/message/" in u]
        self.assertEqual([urlsplit(u).hostname for u in deep], ["teams.cloud.microsoft"])
        self.assertEqual(st["counts"]["app_host"], "cloud")


class TeamsCombinedViewTest(_Base):
    """M9 — 통합(Combined) 채팅·채널 보기."""

    def test_m9_combined_list(self):
        g, ch, one_ = K.tid(20, "group"), K.tid(21, "channel"), K.tid(22, "one")
        items = [{"label": "즐겨찾기", "texts": ["즐겨찾기"], "tid": "", "hdr": True},
                 K.tw_room(1, g, "과제A 설계"),
                 {"label": "팀 머리 자리표시자", "texts": ["팀"], "tid": "", "hdr": True},
                 K.tw_room(3, ch, "양산 채널"), K.tw_room(4, one_, K.KIM)]
        s = FakeSession(teams={"chats": [items], "nav_none": ["channels"],
                               "msgs": {g: [one(K.KIM, "그룹 메시지", "1758000000020")],
                                        ch: [one(K.PEER, "채널 메시지", "1758000000021")],
                                        one_: [one(K.KIM, "1:1 메시지", "1758000000022")]}})
        rc, st, err = self.tw(s, "--no-activity")
        self.assertEqual(rc, 0, err)
        self.assertEqual([x for x in s.opened if x[0] == "index"], [], "머리 항목을 순번으로 누르지 않는다")
        self.assertEqual(st["counts"]["layout"], "combined")
        self.assertEqual(st["counts"]["list_headers"], 2)
        self.assertNotIn("channels_listed", st["counts"])
        rows = self.rows()
        self.assertEqual(set(rows), {"그룹 메시지", "채널 메시지", "1:1 메시지"})
        self.assertEqual(rows["채널 메시지"]["chat_type"], "channel")
        self.assertFalse(any(str(r.get("chat_key", "")).startswith("web:") for r in rows.values()))

    def test_m9_separate_layout_reads_channel_list(self):
        g, ch = K.tid(23, "group"), K.tid(24, "channel")
        s = FakeSession(teams={"chats": [[K.tw_room(0, g, "과제A")]], "channels": [[K.tw_room(0, ch, "양산 채널")]],
                               "msgs": {g: [one(K.KIM, "그룹", "1758000000023")], ch: [one(K.PEER, "채널", "1758000000024")]}})
        rc, st, err = self.tw(s, "--no-activity")
        self.assertEqual(rc, 0, err)
        self.assertEqual(st["counts"]["layout"], "separate")
        self.assertEqual(set(self.rows()), {"그룹", "채널"})


class LoginCodesTest(_Base):
    """M12 · H1(웹 쪽) — AADSTS 번호 분류."""

    def session(self, **kw):
        return FakeSession(owa={"inbox": [[K.owa_item(K.KIM, "x", "2026-09-03", key="i1")]], "sent": [[]]}, **kw)

    def test_m12_external_challenge_is_login_not_ca(self):
        rc, st, _ = self.owa(self.session(login=True, aadsts="50158"))
        self.assertEqual((rc, st["reasons"]), (2, [R_ + "LOGIN"]))
        self.assertEqual(st["counts"]["aadsts_kind"], "interactive")
        self.assertFalse(any(rcmap.confirmable(r) for r in st["reasons"]))

    def test_h1_device_ca_is_login_not_structural(self):
        for code in ("53000", "53001", "50097", "50005"):
            rc, st, _ = self.owa(self.session(login=True, aadsts=code))
            self.assertEqual((rc, st["reasons"], st["counts"]["aadsts"], st["counts"]["aadsts_kind"]),
                             (2, [R_ + "LOGIN"], int(code), "device"), code)

    def test_policy_ca_stays_r_ca(self):
        for code in ("53003", "53002", "53004", "530032"):
            rc, st, _ = self.owa(self.session(login=True, aadsts=code))
            self.assertEqual((rc, st["reasons"], st["counts"]["aadsts_kind"]), (2, [R_ + "CA"], "policy"), code)

    def test_teams_device_ca(self):
        s = FakeSession(login=True, aadsts="53000", teams={})
        rc, st, _ = K.run_tw(self.sb, ["--no-channels"], session_factory=factory(s))
        self.assertEqual((rc, st["reasons"]), (2, [R_ + "LOGIN"]))

    def test_classifier(self):
        kinds = {c: W.aadsts_kind(c) for c in ("50158", "53000", "53003", "530032", "53099", "50076", "x", "")}
        self.assertEqual(kinds, {"50158": "interactive", "53000": "device", "53003": "policy", "530032": "policy",
                                 "53099": "policy", "50076": "other", "x": "", "": ""})


class ProbeLoginCodesTest(_Base):
    """탐침도 같은 분류 — 장치 기반 CA 는 web_login fail + R-LOGIN(사람 — '불가' 확정 근거 아님), 값에 번호·종류(숫자·열거만)."""

    def probe(self, mod, session):
        import io
        import json
        from lm27.bridge.clock import VirtualClock
        from lm27.bridge.session import EdgeInfo
        out, err = io.StringIO(), io.StringIO()
        mod.main([], environ={}, paths=self.sb.paths, cfg=self.sb.cfg, clock=VirtualClock(), now=K.NOW, out=out, err=err,
                 session_factory=factory(session), edge_info=lambda: EdgeInfo(path="C:/edge/msedge.exe", version="129.0.1.2"))
        return json.loads(out.getvalue().strip().splitlines()[-1])

    def test_owa_probe_device_ca(self):
        wl = self.probe(K.POWA, FakeSession(login=True, aadsts="53000"))["caps"]["web_login"]
        self.assertEqual((wl["status"], wl["reasons"], wl["value"]["aadsts"], wl["value"]["aadsts_kind"]),
                         ("fail", [R_ + "LOGIN"], 53000, "device"))

    def test_teams_probe_preopened_first_room(self):
        """P-WEB: 첫 방이 처음부터 열려 있어 확인되지 않으면 둘째 방으로 표본 — R-WEBSEL(구조·확정)로 오판하지 않는다."""
        a, b = K.tid(41, "group"), K.tid(42, "group")
        s = FakeSession(teams={"chats": [[K.tw_room(0, a, "과제A"), K.tw_room(1, b, "과제B")]],
                               "msgs": {a: [one(K.KIM, "a", "1758000000041")], b: [one(K.KIM, "b", "1758000000042")]},
                               "start_room": a, "sel": False})
        c = self.probe(K.PTW, s)["caps"]["teams.web"]
        self.assertEqual((c["status"], c["reasons"], c["value"]["room_opened"], c["value"]["sample_n"]), ("ok", [], True, 1))

    def test_teams_probe_no_room_confirmed_not_websel(self):
        a = K.tid(43, "group")
        s = FakeSession(teams={"chats": [[K.tw_room(0, a, "과제A")]], "msgs": {a: [one(K.KIM, "a", "1758000000043")]},
                               "start_room": a, "sel": False})
        c = self.probe(K.PTW, s)["caps"]["teams.web"]
        self.assertEqual((c["status"], c["reasons"], c["value"]["room_opened"]), ("ok", [], False))

    def test_teams_probe_policy_ca(self):
        c = self.probe(K.PTW, FakeSession(login=True, aadsts="53003", teams={}))["caps"]["teams.web"]
        self.assertEqual((c["reasons"], c["value"]["aadsts_kind"]), ([R_ + "CA"], "policy"))


class HostTest(_Base):
    """L2 · *.cloud.microsoft 도착."""

    def test_l2_on_prem_mailbox_host_class(self):
        rc, st, err = self.owa(FakeSession(host="mail.corp.example"))
        self.assertEqual((rc, st["reasons"]), (2, [R_ + "LOGIN"]))
        self.assertEqual((st["counts"]["host_class"], st["counts"]["login_detail"]), ("nonms", "nonms_host"))
        self.assertNotIn("corp.example", err)                                           # 호스트 이름은 남기지 않는다

    def test_l2_microsoft_portal_host_class(self):
        rc, st, _ = self.owa(FakeSession(host="www.office.com"))
        self.assertEqual(rc, 2)
        self.assertEqual(st["counts"]["host_class"], "ms")
        self.assertNotIn("login_detail", st["counts"])

    def test_owa_cloud_microsoft_is_normal_and_kept(self):
        s = FakeSession(host="outlook.cloud.microsoft",
                        owa={"inbox": [[K.owa_item(K.KIM, "클라우드 도착", "2026-09-03", key="i1")]], "sent": [[]]})
        rc, st, err = self.owa(s)
        self.assertEqual(rc, 0, err)
        self.assertEqual(urlsplit(s.gotos[0]).hostname, "outlook.office365.com")        # 문서 기본 주소로 시작
        self.assertEqual({urlsplit(u).hostname for u in s.gotos[1:]}, {"outlook.cloud.microsoft"})
        self.assertEqual(st["counts"]["app_host"], "cloud")


class RemoteSessionTest(_Base):
    """L13 — Teams 웹은 VDI 미지원(문서) — 진단 숫자만."""

    def test_l13_remote_session_counted(self):
        a = K.tid(30, "group")
        s = FakeSession(teams={"chats": [[K.tw_room(0, a, "과제A")]], "msgs": {a: [one(K.KIM, "m", "1758000000030")]}})
        orig = T.remote_session
        T.remote_session = lambda: True
        try:
            rc, st, err = self.tw(s, "--no-channels", "--no-activity")
        finally:
            T.remote_session = orig
        self.assertEqual(rc, 0, err)
        self.assertEqual(st["counts"]["remote_session"], 1)
        self.assertIn("VDI", err)


if __name__ == "__main__":
    unittest.main()
