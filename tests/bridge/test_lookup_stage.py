# -*- coding: utf-8 -*-
"""WP-25 조회 단계(B §8.1) 단위 — 행 검사(B-T40 구간 밖 · B-T54 시각 제거 · bad_time · 열거 고침) · 가득 참·쪼개기(B-T39
3·4일) · 행 상한(메일 36·팀즈 40·일정 43) · 머리말(구간 날짜·행 상한·재질의 화법) · 어댑터 공용 도구(구간 계획·재확인 1일·
쪼갠 구간 펼치기·증인 원시 행 — 계약 §3.2·§3.4·§4.2)."""
from __future__ import annotations

import unittest
from datetime import date

from lm27.bridge import exchange as X
from lm27.bridge.stages import lookup as L
from lm27.bridge.transport import SendResult

from tests.fixtures.wp25 import kit as K

MAIL, TEAMS, CAL = (L.LookupMail(), L.LookupTeams(), L.LookupCalendar())


def win(stage="lookup_mail", d0="2026-09-01", d1="2026-09-07"):
    return K.wi(L.window_key(stage, d0, d1), {"d0": d0, "d1": d1})


class RowChecks(unittest.TestCase):
    def setUp(self):
        self.it = win()

    def test_T54_time_dropped_date_only(self):
        row, codes = MAIL.normalize_row({"t": "2026-09-02 14:30", "d": "out", "s": "회의 자료 송부"}, self.it, None)
        self.assertEqual((row["t"], codes), ("2026-09-02", ("time_dropped",)))
        row, codes = MAIL.normalize_row({"t": "2026-09-02T09:05:00", "d": "IN"}, self.it, None)
        self.assertEqual((row["t"], row["d"], codes), ("2026-09-02", "in", ("time_dropped",)))
        row, codes = MAIL.normalize_row({"t": "2026-09-02", "d": "in"}, self.it, None)
        self.assertEqual(codes, ())

    def test_T40_out_of_window_and_bad_time(self):
        self.assertEqual(MAIL.normalize_row({"t": "2026-08-31", "d": "in"}, self.it, None), (None, ("out_of_window",)))
        self.assertEqual(MAIL.normalize_row({"t": "9/2", "d": "in"}, self.it, None), (None, ("bad_time",)))
        self.assertEqual(MAIL.normalize_row({"t": "2026-02-30", "d": "in"}, self.it, None), (None, ("bad_time",)))
        row, _c = MAIL.normalize_row({"t": "2026-09-07", "d": "in"}, self.it, None)
        self.assertEqual(row["t"], "2026-09-07")                     # 양 끝 포함

    def test_mail_fields_fixed(self):
        row, codes = MAIL.normalize_row({"t": "2026-09-03", "d": "in", "who": "partner.example", "rcv": "BCC",
                                         "s": "가" * 70}, self.it, None)
        self.assertEqual((row["who"], row["rcv"]), ("@partner.example", "-"))
        self.assertIn("rcv_fixed", codes)
        self.assertLessEqual(len(row["s"]), 60)
        row, codes = MAIL.normalize_row({"t": "2026-09-03", "d": "in", "who": "김철수"}, self.it, None)
        self.assertEqual(row["who"], "-")
        self.assertIn("who_fixed", codes)
        self.assertEqual(MAIL.normalize_row({"t": "2026-09-03", "d": "both"}, self.it, None)[0], None)

    def test_teams_and_cal_fields(self):
        it = win("lookup_teams")
        row, codes = TEAMS.normalize_row({"t": "2026-09-03", "d": "out", "chat": "dm", "act": "REQUEST"}, it, None)
        self.assertEqual((row["chat"], row["act"]), ("-", "request"))
        self.assertIn("chat_fixed", codes)
        it = win("lookup_calendar")
        row, codes = CAL.normalize_row({"t": "2026-09-03", "busy": 7, "loc": "온라인", "allday": True}, it, None)
        self.assertNotIn("busy", row)
        self.assertEqual((row["loc"], row["allday"]), ("-", True))
        self.assertIn("busy_fixed", codes)


class FullAndSplit(unittest.TestCase):
    def test_max_rows_by_stage(self):
        st = K.settings()
        ctx = K.ctx_for(MAIL, settings=st, pack_out=st.answer_max_chars)
        self.assertEqual((MAIL.max_rows(ctx), TEAMS.max_rows(ctx), CAL.max_rows(ctx)), (36, 40, 43))
        small = K.settings({"bridge.lookup.maxRows": 20})
        self.assertEqual(MAIL.max_rows(K.ctx_for(MAIL, settings=small, pack_out=small.answer_max_chars)), 20)
        self.assertEqual(MAIL.max_rows(None), L.FALLBACK_ROWS)

    def test_is_full(self):
        st = K.settings()
        ctx = K.ctx_for(MAIL, settings=st, pack_out=st.answer_max_chars)
        full = int(36 * 0.9)
        self.assertTrue(MAIL.is_full({"rows": [{}] * full, "more": False, "n": full}, "ok", ctx))
        self.assertFalse(MAIL.is_full({"rows": [{}] * (full - 1), "more": False, "n": full - 1}, "ok", ctx))
        self.assertTrue(MAIL.is_full({"rows": [], "more": True, "n": 0}, "ok", ctx))
        self.assertTrue(MAIL.is_full({"rows": [], "n": 0}, "truncated", ctx))

    def test_T39_split_3_4(self):
        ctx = K.ctx_for(MAIL, settings=K.settings())
        kids = MAIL.split(win(), ctx)
        self.assertEqual([k["fields"] for k in kids], [{"d0": "2026-09-01", "d1": "2026-09-03"},
                                                       {"d0": "2026-09-04", "d1": "2026-09-07"}])
        self.assertEqual(kids[0]["key"], "lookup_mail:2026-09-01:2026-09-03")
        self.assertEqual([k["fields"] for k in MAIL.split(win(d0="2026-09-01", d1="2026-09-02"), ctx)],
                         [{"d0": "2026-09-01", "d1": "2026-09-01"}, {"d0": "2026-09-02", "d1": "2026-09-02"}])
        self.assertIsNone(MAIL.split(win(d0="2026-09-03", d1="2026-09-03"), ctx))      # minWindowDays(1) — 더 못 쪼갬
        st2 = K.settings({"bridge.lookup.minWindowDays": 3})
        self.assertIsNone(MAIL.split(win(d0="2026-09-01", d1="2026-09-03"), K.ctx_for(MAIL, settings=st2)))


class Prompt(unittest.TestCase):
    def test_title_header_window_and_rows(self):
        st = K.settings()
        ctx = K.ctx_for(MAIL, settings=st, pack_out=st.answer_max_chars)
        asm = K.assemble(MAIL, [win(d0="2026-09-08", d1="2026-09-14")], ctx)
        t = asm.text
        self.assertTrue(t.startswith("[LM27 요청 R7F3QK · 메일 조회 · 구간 2026-09-08~2026-09-14]\n내 Outlook 메일"))
        self.assertIn("2026-09-08부터 2026-09-14까지(양 끝 포함)", t)
        self.assertIn("최대 36행까지만 씁니다", t)
        self.assertIn('n 에는 쓴 행 수를 씁니다. id 는 1부터 차례로 씁니다.', t)
        self.assertNotIn("[항목]", t)
        self.assertNotIn("웹 검색을 하지 말고", t)                   # 조회는 검색이 일이다(B §6.2 조회형)
        self.assertNotIn("@", t)                                    # '@도메인' 은 정제기가 멘션(사람)으로 본다
        reph = K.assemble(MAIL, [win(d0="2026-09-08", d1="2026-09-14")], ctx, rephrase=True).text
        self.assertIn("내 Outlook 메일에서 2026-09-08~2026-09-14 기간의 업무 메일을 검색해서, 찾은 것만", reph)
        self.assertIn("- 날짜만 씁니다. 시각은 쓰지 않습니다.", reph)

    def test_empty_batch_same_length(self):
        """패킹 예산 계산(빈 묶음)의 머리말 길이 = 실제 묶음 머리말 길이(자리 날짜가 같은 길이)."""
        ctx = K.ctx_for(TEAMS, settings=K.settings())
        empty = len(TEAMS.title_line("RZZZZZ", 1, [], ctx)) + len(TEAMS.header(ctx))
        real = len(TEAMS.title_line("RZZZZZ", 1, [win("lookup_teams")], ctx)) + len(TEAMS.header(ctx))
        self.assertEqual(empty, real)

    def test_classify_rows_envelope(self):
        """L2 조회 분류에 이 단계의 행 검사가 쓰인다 — n 일치면 ok, 시각 제거·구간 밖은 dropped 셈."""
        it = win()
        meta = X.AsmMeta(rid="R7F3QK", item_ids=[1], id_to_key={1: it.key}, items={1: it})
        body = ('```json\n{"rid":"R7F3QK","n":3,"more":false,"items":[{"id":1,"t":"2026-09-02 14:30","d":"out"},'
                '{"id":2,"t":"2026-08-30","d":"in"},{"id":3,"t":"2026-09-03","d":"in","s":"회의"}]}\n```\n[[END R7F3QK]]')
        status, info = X.classify(MAIL, SendResult(phase="replied", body=body), meta, K.ctx_for(MAIL))
        self.assertEqual(status, "ok")
        ans = info["answers"][1]
        self.assertEqual([r["t"] for r in ans["rows"]], ["2026-09-02", "2026-09-03"])
        self.assertEqual((info["dropped"]["time_dropped"], info["dropped"]["out_of_window"]), (1, 1))

    def test_reply_kind_marks(self):
        self.assertEqual(L.reply_kind("조회 도구가 없어 찾을 수 없습니다"), "unable")
        self.assertEqual(L.reply_kind("검색 결과가 없습니다"), "empty")
        self.assertEqual(L.reply_kind("요청하신 메일 목록입니다"), "other")
        self.assertEqual(L.reply_kind("I am not connected to Teams data."), "unable")     # 팀즈 커넥터 없음(이전 판 팀즈)
        self.assertEqual(L.reply_kind("이 기간에는 메시지가 없습니다"), "empty")
        self.assertEqual(L.reply_kind("No messages were found"), "empty")


class AdapterTools(unittest.TestCase):
    def test_plan_windows(self):
        days = [date(2026, 9, d) for d in (1, 2, 3, 4, 5, 6, 7, 8, 9, 15, 16)]
        self.assertEqual(L.plan_windows(days, 7), [("2026-09-01", "2026-09-07"), ("2026-09-08", "2026-09-09"),
                                                   ("2026-09-15", "2026-09-16")])
        self.assertEqual(L.plan_windows(days, 7, recheck=True)[:3],
                         [("2026-09-01", "2026-09-01"), ("2026-09-02", "2026-09-07"), ("2026-09-08", "2026-09-09")])
        self.assertEqual(L.plan_windows(["2026-09-03"], 7, recheck=True), [("2026-09-03", "2026-09-03")])
        self.assertEqual(L.plan_windows([], 7), [])

    def test_ai_in_rows(self):
        rows = L.ai_in_rows("lookup_teams", [("2026-09-01", "2026-09-02")])
        self.assertEqual(rows, [{"key": "lookup_teams:2026-09-01:2026-09-02", "group": "", "src_ver": "collect/1",
                                 "fields": {"d0": "2026-09-01", "d1": "2026-09-02"}}])

    def test_leaves_follow_splits(self):
        items = {"lookup_mail:2026-09-01:2026-09-07": {"by": "rule", "why": "split",
                                                        "ans": {"split": ["lookup_mail:2026-09-01:2026-09-03",
                                                                          "lookup_mail:2026-09-04:2026-09-07"]}},
                 "lookup_mail:2026-09-01:2026-09-03": {"by": "ai", "ans": {"rows": []}},
                 "lookup_mail:2026-09-04:2026-09-07": {"by": "rule_pending", "ans": None}}
        got = L.leaves(items, "lookup_mail:2026-09-01:2026-09-07")
        self.assertEqual([k for k, _e in got], ["lookup_mail:2026-09-01:2026-09-03", "lookup_mail:2026-09-04:2026-09-07"])
        self.assertEqual(L.leaves({}, "lookup_mail:2026-09-01:2026-09-01"), [("lookup_mail:2026-09-01:2026-09-01", None)])
        self.assertEqual(L.parse_window_key("lookup_mail:2026-09-01:2026-09-03"), ("2026-09-01", "2026-09-03"))
        self.assertIsNone(L.parse_window_key("lookup_mail:x:y"))

    def test_witness_raw(self):
        row = {"t": "2026-09-02", "d": "in", "who": "@partner.example", "rcv": "to", "s": "견적 회신", "th": "견적 요청"}
        raw = L.witness_raw("mail.copilot", row, off_min=540, observed="2026-10-01T00:00:00Z")
        self.assertEqual((raw["ts_utc"], raw["ts_local_offset"], raw["ts_precision"], raw["confidence"]),
                         ("2026-09-01T15:00:00Z", "+09:00", "summary", 0.3))
        self.assertEqual(raw["copilot_text"], "견적 회신 / 견적 요청")
        self.assertEqual(raw["cp_row"], dict(sorted(row.items())))
        self.assertNotIn("act", raw)                                 # 원시 act 는 정제기가 거부한다(화행은 저장하지 않음)
        cal = L.witness_raw("cal.copilot", {"t": "2026-09-02", "s": "주간 회의"}, off_min=0, observed="x")
        self.assertEqual((cal["ts_utc"], cal["end_utc"]), ("2026-09-02T00:00:00Z", "2026-09-03T00:00:00Z"))
        self.assertEqual(L.witness_text("mail.copilot", {"s": "같음", "th": "같음"}), "같음")
        self.assertEqual(len(L.witness_text("teams.copilot", {"s": "가" * 300})), 200)
        self.assertEqual(L.day_start_utc("2026-09-02", -300), "2026-09-02T05:00:00Z")


if __name__ == "__main__":
    unittest.main()
