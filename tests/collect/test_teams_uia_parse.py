# -*- coding: utf-8 -*-
"""WP-16 teams.uia — 줄 해석: 머리말/본문 분리 · 날짜 구분선 · 날짜 미상 격리 · 연속 메시지 상속 · 방향 · 대화 유형 ·
멘션·첨부 · 지역 시각 파서(CT §4 · §7.3 · §7.4 · CT-3 · CT-4 · CT-8 · CT-9).

기준 시각 = 2026-10-01(목) 09:00 +09:00(uia.TEST_NOW). '어제' = 9/30, '월요일' = 9/28, '오늘' = 10/1.
"""
from __future__ import annotations

import unittest

from tests.fixtures.tree import CloneTestCase
from tests.fixtures.wp16 import uia


def _room(res: uia.Result, chat_id: str) -> list[dict]:
    return [x for x in res.records if x["chat_id"] == chat_id]


def _one(res: uia.Result, needle: str) -> dict:
    got = uia.by_body(res, needle)
    if len(got) != 1:
        raise AssertionError(f"본문 '{needle}' 레코드 {len(got)}건")
    return got[0]


class _Base(CloneTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        if not uia.powershell_exe():
            raise unittest.SkipTest("powershell 없음")

    @classmethod
    def run_snap(cls, name: str, snap: dict, **kw) -> uia.Result:
        return uia.run(cls.clone, uia.write_json(cls.clone.temp / f"{name}.json", snap), **kw)

    @classmethod
    def run_lines(cls, name: str, lines: list[str], **kw) -> uia.Result:
        return uia.run(cls.clone, uia.write_lines(cls.clone.temp / f"{name}.txt", lines), **kw)


class TestRoomsAndLines(_Base):
    """창 여러 개(방마다 하나)를 한 번에 읽고 방·줄 단위로 단언한다."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        a = uia.window("채팅 | 과제A 설계 | Microsoft Teams", [
            uia.button("참가자 5명"),
            uia.sep("2026년 9월 25일 금요일"),
            uia.msg("김철수, 오후 3:00, 과제A 회로 검토 부탁드립니다 8/15 까지"),
            uia.msg("오후 3:01, 내일까지 가능할까요?"),
            uia.msg("확인했습니다, 오후 3:02, 네 반영하겠습니다"),
            uia.sep("어제"),
            uia.msg("동료B, 오전 9:00, @홍길동 자료 공유드립니다 보고_초안.pptx"),
            uia.el("설계검토.xlsx"),
            uia.msg("홍길동님, 오전 9:05, 내용 확인 완료"),
            uia.msg("You, 오전 9:06, 감사합니다"),
            uia.el("회의는 오후 3:00 에 시작합니다"),
            uia.msg("동료B, 9월 24일 오후 2:00, 지난 회의록 공유드립니다"),
            uia.sep("월요일"),
            uia.msg("김철수, 오전 11:00, 주간 보고 부탁드립니다"),
            uia.sep("오늘"),
            uia.msg("김철수, 오전 8:30, 오늘 일정 공유드립니다"),
        ])
        b = uia.window("팀 | 과제A 채널 | Microsoft Teams", [
            uia.tab("게시물"), uia.msg("동료C, 2026년 9월 30일 오전 10:00, 채널 공지 확인 바랍니다")])
        c = uia.window("채팅 | 김철수, 동료B, 동료C | Microsoft Teams", [
            uia.msg("김철수, 2026년 9월 30일 오전 10:10, 쉼표 방 안건 정리했습니다")])
        d = uia.window("채팅 | 동료D | Microsoft Teams", [
            uia.button("참가자 2명"), uia.msg("동료D, 2026년 9월 30일 오전 10:20, 일대일 질문 있습니다")])
        e = uia.window("채팅 | 홍길동 (나) | Microsoft Teams", [
            uia.msg("홍길동, 2026년 9월 30일 오전 9:30, 개인 메모 정리")])
        f = uia.window("채팅 | 주간 회의 | Microsoft Teams", [
            uia.button("모임 채팅"), uia.msg("동료E, 2026년 9월 30일 오전 10:30, 회의 안건 올립니다")])
        g = uia.window("채팅 | 과제B 협의 | Microsoft Teams", [
            uia.msg("김철수, 2026년 9월 30일 오후 1:00, 과제B 사양 협의 요청드립니다"),
            uia.msg("동료B, 2026년 9월 30일 오후 1:05, 과제B 사양 의견 드립니다")])
        h = uia.window("채팅 | 과제D 납기 | Microsoft Teams", [
            uia.msg("2026년 9월 30일 오전 11:00, 납기 일정 확인 부탁드립니다")])
        cls.res = cls.run_snap("rooms", uia.snapshot(a, b, c, d, e, f, g, h))

    def test_run_ok(self):
        self.assertEqual(self.res.rc, 0, self.res.stderr.decode("utf-8", "replace")[-2000:])
        self.assertEqual(self.res.reasons, [])

    def test_header_date_only_body_date_ignored(self):
        """날짜는 시각 앞 머리말·구분선에서만 — 본문의 '8/15 까지'는 날짜가 아니다."""
        x = _one(self.res, "회로 검토")
        self.assertEqual(x["ts_utc"], "2026-09-25T06:00:00Z")
        self.assertEqual(x["ts_precision"], "minute")

    def test_separators_today_yesterday_weekday(self):
        self.assertEqual(_one(self.res, "자료 공유드립니다")["ts_utc"], "2026-09-30T00:00:00Z")   # 어제 09:00
        self.assertEqual(_one(self.res, "주간 보고")["ts_utc"], "2026-09-28T02:00:00Z")          # 월요일 11:00
        self.assertEqual(_one(self.res, "오늘 일정")["ts_utc"], "2026-09-30T23:30:00Z")          # 오늘 08:30
        self.assertEqual(_one(self.res, "지난 회의록")["ts_utc"], "2026-09-24T05:00:00Z",
                         "머리말 날짜가 구분선 문맥보다 우선")

    def test_ct8_continuation_inherits_author(self):
        x = _one(self.res, "내일까지 가능할까요")
        self.assertEqual(x["author_name"], "김철수")
        self.assertIs(x["is_me"], False)
        self.assertEqual(x["flags"].get("author_inherited"), True)
        self.assertEqual(x["confidence"], 0.3)
        y = _one(self.res, "반영하겠습니다")
        self.assertNotEqual(y["author_name"], "확인했습니다", "짧은 본문을 작성자로 오인하지 않는다")
        self.assertEqual(y["author_name"], "김철수")
        z = _one(self.res, "회로 검토")
        self.assertNotIn("author_inherited", z["flags"])
        self.assertEqual(z["confidence"], 0.8)

    def test_unknown_author_is_not_received(self):
        x = _one(self.res, "납기 일정 확인")
        self.assertIsNone(x["author_name"])
        self.assertIsNone(x["is_me"], "작성자 불명은 수신으로 단정하지 않는다(direction unknown)")
        self.assertNotIn("author_inherited", x["flags"])

    def test_self_name_variants(self):
        self.assertIs(_one(self.res, "확인 완료")["is_me"], True)          # '홍길동님'
        self.assertIs(_one(self.res, "감사합니다")["is_me"], True)          # 고정어 'You'
        self.assertIs(_one(self.res, "자료 공유드립니다")["is_me"], False)

    def test_mentions_and_files(self):
        x = _one(self.res, "자료 공유드립니다")
        self.assertIs(x["mentions_me"], True)
        self.assertEqual(x["file_names"], ["보고_초안.pptx", "설계검토.xlsx"], "본문 파일명 + 뒤따르는 파일 카드")
        self.assertIs(_one(self.res, "회로 검토")["mentions_me"], False)

    def test_time_inside_body_fragment_is_not_a_message(self):
        self.assertEqual(uia.by_body(self.res, "에 시작합니다"), [])

    def test_ct9_group_by_structure(self):
        rows = _room(self.res, "uia:과제a 설계")
        self.assertEqual(len(rows), 9)
        for x in rows:
            self.assertEqual((x["chat_type"], x["n_participants"], x["chat_title"]), ("group", 5, "과제A 설계"))
            self.assertNotIn("n_part_est", x["flags"])
        self.assertEqual({p["name"] for p in rows[0]["participants"]}, {"김철수", "동료B"})

    def test_ct9_channel(self):
        x = _room(self.res, "uia:과제a 채널")[0]
        self.assertEqual((x["chat_type"], x["n_participants"], x["chat_title"]), ("channel", 2, "과제A 채널"))
        self.assertIs(x["flags"].get("n_part_est"), True)

    def test_ct9_comma_title_not_used(self):
        """이름 붙은 단체방 판정에 쉼표 수·방 이름을 쓰지 않는다 — 단서가 없으면 group + 2 + n_part_est, 제목 저장 안 함."""
        x = _one(self.res, "쉼표 방 안건")
        self.assertEqual((x["chat_type"], x["n_participants"]), ("group", 2))
        self.assertIs(x["flags"].get("n_part_est"), True)
        self.assertIsNone(x["chat_title"])

    def test_one_to_one_title_not_kept(self):
        x = _one(self.res, "일대일 질문")
        self.assertEqual((x["chat_type"], x["n_participants"], x["chat_title"]), ("1:1", 2, None))

    def test_self_chat(self):
        x = _one(self.res, "개인 메모")
        self.assertEqual((x["chat_type"], x["n_participants"], x["is_me"]), ("self", 1, True))
        self.assertIsNone(x["chat_title"])
        self.assertEqual(x["chat_id"], "uia:홍길동")

    def test_meeting(self):
        x = _one(self.res, "회의 안건")
        self.assertEqual((x["chat_type"], x["chat_title"]), ("meeting", "주간 회의"))

    def test_group_by_observed_authors(self):
        rows = _room(self.res, "uia:과제b 협의")
        self.assertEqual(len(rows), 2)
        for x in rows:
            self.assertEqual((x["chat_type"], x["n_participants"], x["chat_title"]), ("group", 3, "과제B 협의"))
            self.assertIs(x["flags"].get("n_part_est"), True)

    def test_chat_ids_stable_and_no_window_class(self):
        ids = {x["chat_id"] for x in self.res.records}
        self.assertEqual(ids, {"uia:과제a 설계", "uia:과제a 채널", "uia:김철수, 동료b, 동료c", "uia:동료d", "uia:홍길동",
                               "uia:주간 회의", "uia:과제b 협의", "uia:과제d 납기"})


class TestTimeFormats(_Base):
    def test_ct3_generic_retry_when_region_format_differs(self):
        r = self.run_lines("generic", ["김철수, 2026-09-30 14.10, 과제A 검토 부탁드립니다"])
        self.assertEqual(r.rc, 0)
        self.assertEqual([x["ts_utc"] for x in r.records], ["2026-09-30T05:10:00Z"])

    def test_ct3_time_regex_setting(self):
        lines = ["김철수, 2026-09-30 14h10, 과제A 검토 부탁드립니다"]
        r0 = self.run_lines("tre0", lines)
        self.assertEqual((r0.rc, r0.records), (4, []))
        r1 = self.run_lines("tre1", lines, cfg={"teams.timeRegex": r"()(\d{1,2})h(\d{2})()"})
        self.assertEqual(r1.rc, 0)
        self.assertEqual(r1.counts["cfg_regex"], 1)
        self.assertEqual([x["ts_utc"] for x in r1.records], ["2026-09-30T05:10:00Z"])
        r2 = self.run_lines("tre2", lines, cfg={"teams.timeRegex": "("})
        self.assertEqual((r2.rc, r2.counts["cfg_regex"]), (4, -1))

    def test_english_month_and_yesterday(self):
        r = self.run_lines("en", ["동료B, Sep 29 3:05 PM, please review the draft",
                                  "동료C, Yesterday 9:00 AM, status update please",
                                  "Mark, 4:00 PM, separate note without date"])
        got = {x["author_name"]: (x["ts_utc"], x["ts_precision"]) for x in r.records}
        self.assertEqual(got["동료B"], ("2026-09-29T06:05:00Z", "minute"))
        self.assertEqual(got["동료C"], ("2026-09-30T00:00:00Z", "minute"))
        self.assertEqual(got["Mark"][1], "unknown", "'Mark'·'separate' 를 월 이름으로 오인하지 않는다")

    def test_ct4_undated_without_separator_is_unknown(self):
        r = self.run_lines("undated", ["김철수, 오후 3:40, 과제A 시험계획 결과 공유드립니다",
                                       "어제",
                                       "김철수, 오후 3:41, 과제A 시험계획 첨부 확인 부탁드립니다"])
        a = _one(r, "결과 공유")
        self.assertEqual((a["ts_precision"], a["ts_utc"], a["confidence"]), ("unknown", "2026-09-30T15:00:00Z", 0.3))
        b = _one(r, "첨부 확인")
        self.assertEqual((b["ts_precision"], b["ts_utc"]), ("minute", "2026-09-30T06:41:00Z"))
        self.assertEqual(r.counts["n_unknown"], 1)
        self.assertEqual(r.cursor, {"last_ts_utc": "2026-09-30T06:41:00Z"}, "커서는 날짜 확정 줄로만")


class TestDirectionWithoutNames(_Base):
    def test_noaddr_keeps_structure_cue_only(self):
        """본인 이름 집합이 없으면(R-NOADDR) 이름 단계를 건너뛴다 — 오른쪽 정렬(구조) 단서만 남는다."""
        snap = uia.snapshot(uia.window("채팅 | 과제A 설계 | Microsoft Teams", [
            uia.sep("오늘"),
            uia.msg("김철수, 오전 8:30, 과제A 설계 검토 부탁드립니다"),
            uia.mine("오전 8:35, 넵 확인했습니다"),
            uia.msg("홍길동, 오전 8:40, 검토본 올립니다"),
        ]))
        r = self.run_snap("noaddr", snap, self_names=None)
        self.assertIn("R-NOADDR", r.reasons)
        self.assertIsNone(_one(r, "설계 검토")["is_me"])
        self.assertIsNone(_one(r, "검토본 올립니다")["is_me"])
        self.assertIs(_one(r, "넵 확인했습니다")["is_me"], True)
        r2 = self.run_snap("withnames", snap, self_names=["홍길동"])
        self.assertNotIn("R-NOADDR", r2.reasons)
        self.assertIs(_one(r2, "설계 검토")["is_me"], False)
        self.assertIs(_one(r2, "검토본 올립니다")["is_me"], True)
        self.assertEqual(r2.counts["n_self"], 2)


if __name__ == "__main__":
    unittest.main()
