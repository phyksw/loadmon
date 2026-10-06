# -*- coding: utf-8 -*-
"""WP-26 해석 시험(순수 함수) — 날짜·시각 머리 조각(CM §11.3 '머리 조각에서만'), 메일 항목·일정 해석(CM-11 date-only),
구간 계산(빈칸·커서), 세션 상태 → rc·사유(계약 §8.1), Teams 메시지 화면 해석(CT-6 날짜 포함 키 · unknown 격리 · 작성자 상속)."""
import unittest
from datetime import UTC, date, datetime, timedelta

from tests.fixtures.wp26 import webkit as K

W, T = K.OWA, K.TW
TODAY = date(2026, 10, 1)            # 목요일
D0, D1 = date(2026, 9, 1), date(2026, 9, 30)


class TimeDateTest(unittest.TestCase):

    def test_find_times_designators_and_date_fragments(self):
        self.assertEqual(W.find_times("오후 3:24"), [(15, 24)])
        self.assertEqual(W.find_times("오전 12:30"), [(0, 30)])
        self.assertEqual(W.find_times("오후 12:05"), [(12, 5)])
        self.assertEqual(W.find_times("9:05 PM"), [(21, 5)])
        self.assertEqual(W.find_times("오후 3시 24분"), [(15, 24)])
        self.assertEqual(W.find_times("10.06.2026"), [])                 # 날짜 조각은 시각이 아니다
        self.assertEqual(W.find_times("2026. 6. 10."), [])

    def test_date_in_strong_and_weak(self):
        self.assertEqual(W.date_in("2026년 9월 1일 오전 9:05"), date(2026, 9, 1))
        self.assertEqual(W.date_in("2026-09-01"), date(2026, 9, 1))
        self.assertEqual(W.date_in("Sep 3, 2026"), date(2026, 9, 3))
        self.assertEqual(W.date_in("9월 3일 목요일", D0, D1, TODAY), date(2026, 9, 3))
        self.assertIsNone(W.date_in("과제A v1.2 검토", D0, D1, TODAY))   # 제목의 v1.2 는 날짜가 아니다
        self.assertIsNone(W.date_in("9/3", D0, D1, TODAY))
        self.assertEqual(W.date_in("9/3", D0, D1, TODAY, weak=True), date(2026, 9, 3))

    def test_parse_when_same_fragment_and_relative(self):
        self.assertEqual(W.parse_when(["2026-09-15 (화) 오후 3:24"], D0, D1, TODAY), (date(2026, 9, 15), (15, 24)))
        self.assertEqual(W.parse_when(["오전 9:05"], D0, D1, TODAY), (TODAY, (9, 5)))      # 목록: 시각만 = 오늘
        self.assertIsNone(W.parse_when(["오전 9:05"], D0, D1, TODAY, bare_today=False))     # 대화: 구분선이 날짜를 준다
        self.assertEqual(W.parse_when(["어제 오전 9:05"], D0, D1, TODAY), (date(2026, 9, 30), (9, 5)))
        self.assertEqual(W.parse_when(["월 오후 3:24"], D0, D1, TODAY), (date(2026, 9, 28), (15, 24)))
        self.assertEqual(W.parse_when(["2026-09-03"], D0, D1, TODAY), (date(2026, 9, 3), None))

    def test_parse_when_ignores_words_in_subject(self):
        # 제목 조각의 '월요일 회의'·'v1.2'·'9월 3일까지' 를 날짜로 읽지 않는다 — 날짜·시각만인 조각을 쓴다
        frags = W.frags_of("김철수, 월요일 회의 안건 v1.2, 2026-09-03")
        self.assertEqual(W.parse_when(frags, D0, D1, TODAY), (date(2026, 9, 3), None))
        self.assertIsNone(W.parse_when(["월요일 회의 안건"], D0, D1, TODAY))
        frags = W.frags_of("김철수, 9월 2일까지 회신 바랍니다, 2026-09-15")
        self.assertEqual(W.parse_when(frags, D0, D1, TODAY), (date(2026, 9, 15), None))
        self.assertIsNone(W.parse_when(["9월 2일까지 회신 바랍니다"], D0, D1, TODAY))
        self.assertEqual(W.parse_when(["보낸 날짜: 2026-09-15 오후 3:24"], D0, D1, TODAY), (date(2026, 9, 15), (15, 24)))

    def test_rel_date_separator(self):
        self.assertEqual(W.rel_date("오늘", TODAY), TODAY)
        self.assertEqual(W.rel_date("어제", TODAY), date(2026, 9, 30))
        self.assertEqual(W.rel_date("월요일", TODAY), date(2026, 9, 28))
        self.assertEqual(W.rel_date("목요일", TODAY), date(2026, 9, 24))     # 오늘과 같은 요일 = 지난주


class MailItemTest(unittest.TestCase):

    def test_cm11_inbox_date_only(self):
        it = K.owa_item(K.KIM, "과제A 견적 요청", "2026-09-03", preview="검토 부탁드립니다")
        r = W.parse_mail_item(it, D0, D1, "inbox", TODAY)
        self.assertEqual((r["date"], r["hm"], r["box"], r["who"], r["subject"]),
                         (date(2026, 9, 3), None, "inbox", K.KIM, "과제A 견적 요청"))
        self.assertEqual(r["preview"], "검토 부탁드립니다")

    def test_preview_quote_date_not_used(self):
        # 미리보기의 인용 머리글 날짜(6월)를 시각으로 쓰지 않는다 — 머리 조각(aria-label·title)에서만
        it = {"key": "k1", "label": "김철수, RE: 견적, 2026-09-15",
              "titles": ["RE: 견적"], "texts": [K.KIM, "RE: 견적", "2026년 6월 12일 (금) 오전 10:00, 김철수 님이 작성:",
                                               "2026-09-15"]}
        r = W.parse_mail_item(it, D0, D1, "inbox", TODAY)
        self.assertEqual(r["date"], date(2026, 9, 15))

    def test_sent_recipients_and_box_tokens(self):
        it = K.owa_item("받는 사람 김철수, 동료B", "결과 보고", "2026-09-04")
        r = W.parse_mail_item(it, D0, D1, "sent", TODAY)
        self.assertEqual(r["box"], "sent")
        self.assertEqual(W.recipients_of(r["who"]), [K.KIM, K.PEER])
        # 화면의 폴더 조각이 읽은 폴더보다 앞선다(완전 일치만)
        it2 = K.owa_item(K.KIM, "공유", "2026-09-04", extra_texts=("보낸 편지함",))
        self.assertEqual(W.parse_mail_item(it2, D0, D1, "inbox", TODAY)["box"], "sent")
        it3 = K.owa_item(K.KIM, "Sent from my phone", "2026-09-04")
        self.assertEqual(W.parse_mail_item(it3, D0, D1, "inbox", TODAY)["box"], "inbox")

    def test_skip_folders_and_unparsed(self):
        it = K.owa_item(K.KIM, "광고", "2026-09-04", extra_texts=("정크 메일",))
        self.assertEqual(W.parse_mail_item(it, D0, D1, "inbox", TODAY), {"skip": True})
        self.assertIsNone(W.parse_mail_item({"label": "김철수, 제목만"}, D0, D1, "inbox", TODAY))

    def test_mail_raw_shape(self):
        sb = K.Sandbox()
        self.addCleanup(sb.cleanup)
        run = W.WebRun(kind="mail", src="mail.owa", pc_id=K.PC, paths=sb.paths, cfg=sb.cfg, api={}, clock=_Clock(),
                       now=K.NOW, off_fn=K.off_fn)
        r = {"date": date(2026, 9, 3), "hm": None, "box": "inbox", "who": K.KIM, "subject": "RE: 과제A 견적",
             "preview": "", "has_attach": True, "important": False}
        raw = W.mail_raw(r, run)
        self.assertEqual(raw["ts_utc"], "2026-09-03T03:00:00Z")          # 로컬 12:00 자리값
        self.assertEqual((raw["ts_precision"], raw["confidence"]), ("date", 0.4))
        self.assertEqual(raw["conversation_topic"], "과제A 견적")
        self.assertEqual(raw["sender_name"], K.KIM)
        self.assertNotIn("to", raw)                                      # 받는 사람을 모르면 rcv = unknown(C7)
        r2 = dict(r, box="sent", who="김철수; 동료B", hm=(14, 30))
        raw2 = W.mail_raw(r2, run)
        self.assertEqual((raw2["ts_utc"], raw2["ts_precision"], raw2["confidence"]),
                         ("2026-09-03T05:30:00Z", "minute", 0.8))
        self.assertEqual(raw2["to"], [{"name": K.KIM}, {"name": K.PEER}])


class _Clock:
    virtual = True

    def mono(self):
        return 0.0

    def sleep(self, s):
        return None


class EventTest(unittest.TestCase):

    def test_single_event(self):
        r = W.parse_event(K.owa_event("과제A 주간 회의", date(2026, 9, 1), (9, 0), (10, 0), "3층 회의실"),
                          D0, D1, TODAY)
        self.assertEqual((r["start"], r["end"]), (datetime(2026, 9, 1, 9, 0), datetime(2026, 9, 1, 10, 0)))
        self.assertEqual((r["subject"], r["location"], r["all_day"], r["busy"]), ("과제A 주간 회의", "3층 회의실", False, "busy"))

    def test_multi_day_all_day_cancel_oof(self):
        ev = {"label": "출장, 2026년 9월 7일 ~ 2026년 9월 9일, 종일, 부재 중", "texts": ["출장"]}
        r = W.parse_event(ev, D0, D1, TODAY)
        self.assertEqual((r["start"].date(), r["end"].date(), r["all_day"], r["busy"]),
                         (date(2026, 9, 7), date(2026, 9, 9), True, "oof"))
        ev2 = {"label": "취소됨: 과제A 점검, 2026년 9월 2일 오후 2:00 - 오후 3:00", "texts": []}
        r2 = W.parse_event(ev2, D0, D1, TODAY)
        self.assertTrue(r2["canceled"])
        self.assertEqual(r2["subject"], "과제A 점검")
        ev3 = {"label": "v1.2 배포 검토, 2026년 9월 2일 오후 2:00 - 오후 3:00, Microsoft Teams 모임", "texts": []}
        r3 = W.parse_event(ev3, D0, D1, TODAY)
        self.assertEqual(r3["start"].date(), date(2026, 9, 2))         # 제목의 v1.2 가 날짜로 섞이지 않는다
        self.assertTrue(r3["online"])
        self.assertIsNone(W.parse_event({"label": "날짜 없는 요소", "texts": []}, D0, D1, TODAY))
        # 제목 속 날짜가 일정을 여러 날로 늘리지 않는다(날짜·시각만인 조각에서만)
        ev4 = {"label": "9월 3일 회고 준비, 2026년 9월 10일 오전 9:00 - 오전 10:00, 2층 회의실", "texts": []}
        r4 = W.parse_event(ev4, D0, D1, TODAY)
        self.assertEqual((r4["start"], r4["end"], r4["subject"], r4["location"]),
                         (datetime(2026, 9, 10, 9, 0), datetime(2026, 9, 10, 10, 0), "9월 3일 회고 준비", ""))
        ev5 = {"label": "과제A 점검 2026년 9월 11일 오후 1:00 - 오후 2:00", "texts": []}       # 조각으로 안 나뉜 라벨
        self.assertEqual(W.parse_event(ev5, D0, D1, TODAY)["start"], datetime(2026, 9, 11, 13, 0))


class RangeTest(unittest.TestCase):

    def test_merge_subtract_slices_weeks(self):
        a = [(date(2026, 7, 1), date(2026, 7, 10)), (date(2026, 7, 11), date(2026, 8, 3))]
        self.assertEqual(W.merge_ranges(a), [(date(2026, 7, 1), date(2026, 8, 3))])
        self.assertEqual(W.subtract_ranges(a, [(date(2026, 7, 5), date(2026, 7, 31))]),
                         [(date(2026, 7, 1), date(2026, 7, 4)), (date(2026, 8, 1), date(2026, 8, 3))])
        self.assertEqual(W.month_slices(a), [(date(2026, 7, 1), date(2026, 7, 31)), (date(2026, 8, 1), date(2026, 8, 3))])
        self.assertEqual(W.weeks_of([(date(2026, 9, 2), date(2026, 9, 8))]), [date(2026, 8, 31), date(2026, 9, 7)])
        self.assertTrue(W.covered([(date(2026, 7, 1), date(2026, 7, 31))], date(2026, 7, 3), date(2026, 7, 9)))
        self.assertEqual(W.ranges_from_json([["2026-07-01", "2026-07-03"], ["bad"], ["2026-07-09", "2026-07-02"]]),
                         [(date(2026, 7, 1), date(2026, 7, 3))])

    def test_session_failure_mapping(self):
        login = "R-" + "LOGIN"
        self.assertEqual(W.session_failure("login_required"), (2, login))
        self.assertEqual(W.session_failure("ca"), (2, "R-" + "CA"))
        self.assertEqual(W.session_failure("policy_blocked"), (3, "R-" + "EDGEPOL"))
        self.assertEqual(W.session_failure("edge_not_found"), (3, "R-" + "NOAPP"))
        self.assertEqual(W.session_failure("edge_not_found", {"why": "no_browser"}), (3, "R-" + "TRANSPORT"))
        for st in ("lock_busy", "port_exhausted", "launch_failed", "tab_lost", "cdp_error", "dead_session", "profile_busy"):
            self.assertEqual(W.session_failure(st), (3, "R-" + "TRANSPORT"), st)
        self.assertTrue(W.is_ca_code("53003"))
        self.assertFalse(W.is_ca_code("50058"))


class TeamsParseTest(unittest.TestCase):

    def parse(self, pages):
        return T.parse_pages(pages, today=TODAY, d0=D0, d1=D1, off_fn=K.off_fn)

    def test_iso_exact_and_types(self):
        self.assertEqual(T.parse_iso("2026-09-01T00:05:12.123Z"), datetime(2026, 9, 1, 0, 5, 12, tzinfo=UTC))
        self.assertEqual(T.parse_iso("2026-09-01T09:05:00+09:00"), datetime(2026, 9, 1, 0, 5, tzinfo=UTC))
        self.assertIsNone(T.parse_iso("어제"))
        self.assertEqual(T.chat_type_of(K.tid(1, "channel")), "channel")
        self.assertEqual(T.chat_type_of(K.tid(1, "one")), "1:1")
        self.assertEqual(T.chat_type_of(K.tid(1, "group")), "group")
        self.assertEqual(T.chat_type_of("19:meeting_abc@thread.v2"), "meeting")
        self.assertEqual(T.chat_type_of(K.tid(1, "plain"), "홍길동 (나)"), "self")
        self.assertEqual(T.chat_type_of(K.tid(1, "plain"), "과제A 설계"), "unknown")      # 방 이름·쉼표로 판정하지 않는다
        self.assertEqual(T.norm_name(" 홍길동 님 "), "홍길동")
        self.assertEqual(T.norm_name("홍길동/과제팀"), "홍길동")

    def test_ct6_same_text_same_time_two_days_not_merged(self):
        d1, d2 = date(2026, 9, 1), date(2026, 9, 2)
        page = [K.tw_sep(d1), K.tw_msg(K.KIM, "넵 확인했습니다", h=9, m=0),
                K.tw_sep(d2), K.tw_msg(K.KIM, "넵 확인했습니다", h=9, m=0)]
        msgs = self.parse([{"items": page}])
        self.assertEqual([(m["day"], m["hm"], m["precision"]) for m in msgs],
                         [(d1, (9, 0), "minute"), (d2, (9, 0), "minute")])
        self.assertNotEqual(msgs[0]["key"], msgs[1]["key"])

    def test_pages_overlap_dedupe_and_context_carry(self):
        d1, d2 = date(2026, 9, 1), date(2026, 9, 2)
        older = [K.tw_sep(d1), K.tw_msg(K.KIM, "a"), K.tw_msg(K.PEER, "b", h=10), K.tw_sep(d2), K.tw_msg(K.KIM, "c", h=11)]
        newer = [K.tw_msg(K.KIM, "c", h=11), K.tw_msg(K.KIM, "d", h=12)]      # 구분선 없이 이어짐(겹치는 첫 메시지)
        msgs = self.parse([{"items": newer}, {"items": older}])          # 읽은 순서 = 최신 먼저
        self.assertEqual([m["body"] for m in msgs], ["a", "b", "c", "d"])
        self.assertEqual(msgs[-1]["day"], d2)                            # 앞 회차의 구분선 날짜를 이어받는다

    def test_inherited_author_unknown_date_files(self):
        page = [K.tw_sep(date(2026, 9, 3)), K.tw_msg(K.KIM, "첫 줄"), {"t": "msg", "ts": "오전 9:06", "body": "둘째 줄",
                                                                      "texts": ["둘째 줄"], "iso": [], "titles": []}]
        msgs = self.parse([{"items": page}])
        self.assertEqual((msgs[1]["author"], msgs[1]["inherited"]), (K.KIM, True))
        nodate = self.parse([{"items": [K.tw_msg(K.KIM, "날짜 없음", files=("보고_초안.pptx",))]}])[0]
        self.assertEqual((nodate["precision"], nodate["day"]), ("unknown", None))
        self.assertEqual(nodate["files"], ["보고_초안.pptx"])

    def test_label_body_date_not_used(self):
        page = [K.tw_sep(date(2026, 9, 3)),
                {"t": "msg", "author": K.KIM, "ts": "오전 9:05", "iso": [], "titles": ["9월 1일 오후 2시 회의 링크"],
                 "label": "김철수, 9월 2일 오전 10시까지 보내 주세요, 오전 9:05", "body": "9월 2일 오전 10시까지 보내 주세요",
                 "texts": [K.KIM, "오전 9:05"]}]
        m = self.parse([{"items": page}])[0]
        self.assertEqual((m["day"], m["hm"], m["precision"]), (date(2026, 9, 3), (9, 5), "minute"))

    def test_body_time_not_used_as_message_time(self):
        page = [K.tw_sep(date(2026, 9, 3)), {"t": "msg", "author": K.KIM, "ts": "", "iso": [], "titles": [],
                                             "body": "내일 10시 회의 가능하세요?", "texts": [K.KIM, "내일 10시 회의 가능하세요?"]}]
        m = self.parse([{"items": page}])[0]
        self.assertEqual((m["precision"], m["hm"]), ("date", None))     # 본문 속 '10시' 는 메시지 시각이 아니다

    def test_mid_and_iso(self):
        d = date(2026, 9, 4)
        m = self.parse([{"items": [K.tw_msg(K.KIM, "x", d=d, h=9, m=5, iso=True, mid="1757000000000")]}])[0]
        self.assertEqual((m["precision"], m["day"], m["key"]), ("exact", d, "mid:1757000000000"))
        self.assertEqual(m["when"], datetime(2026, 9, 4, 0, 5, tzinfo=UTC))
        self.assertEqual(m["when"] - timedelta(hours=0), datetime(2026, 9, 4, 0, 5, tzinfo=UTC))


if __name__ == "__main__":
    unittest.main()
