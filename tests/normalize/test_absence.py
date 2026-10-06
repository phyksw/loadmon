# -*- coding: utf-8 -*-
"""WP-18 absence — 근태 대응(X-204 · X-218 · P §12.7 R-P8 · W §2.2 · §2.5).

meet_category: abs_hint 1순위(사적 일정도 남는 힌트) · 공지형 제목 가드 · 출장·교육·외근 · 근무지 외·외부 장소.
leaves: 종일·여러 날·반차(am·pm)·시간제(부재중·바쁨 길이)·내 근태만(취소·거절·미응답·동료 공유 초대 제외)·휴일 제외·
am + pm = full·근무 시간대 오프셋·증인 행 제외. 반환값은 시간 코어 build_days 가 그대로 받는 모양."""
import unittest
from datetime import date
from pathlib import Path

from lm27.normalize.absence import LEAVE_CODES, MEET_CATEGORIES, leaves, meet_category
from tests.fixtures.wp18 import rows as R

ROOT = Path(__file__).resolve().parents[2]


def leave_day(day: str, **kw):
    """그날 종일 연차(KST 00:00 ~ 다음 날 00:00)."""
    start = R.plus(day + "T00:00:00Z", hours=-9)
    kw.setdefault("abs_hint", "leave")
    kw.setdefault("busy", "oof")
    kw.setdefault("subject", "")
    flags = kw.pop("flags", {"all_day": True, "meeting_status": 0})
    return R.cal(start, R.plus(start, days=1), flags=flags, **kw)


def timed(day: str, h0: int, h1: int, **kw):
    start = R.plus(day + "T00:00:00Z", hours=h0 - 9)
    kw.setdefault("abs_hint", "leave")
    kw.setdefault("subject", "")
    flags = kw.pop("flags", {"meeting_status": 0})
    return R.cal(start, R.plus(start, hours=h1 - h0), flags=flags, **kw)


class MeetCategoryTest(unittest.TestCase):
    def cat(self, **kw):
        return meet_category(R.cal("2026-09-01T01:00:00Z", "2026-09-01T02:00:00Z", **kw))

    def test_vocab(self):
        self.assertEqual(set(MEET_CATEGORIES), {"offsite", "edu", "trip", "leave", ""})

    def test_abs_hint_first(self):
        for h in ("leave", "sick", "half", "half_am", "half_pm", "early", "out"):
            self.assertEqual(self.cat(abs_hint=h, subject=""), "leave", h)
        self.assertEqual(self.cat(abs_hint="leave", subject="", priv_class="private"), "leave", "사적 일정도 힌트는 남는다")
        self.assertEqual(self.cat(abs_hint="trip", subject=""), "trip")

    def test_guard_announcements(self):
        self.assertEqual(self.cat(abs_hint="leave", subject="연차 사용 촉진 안내"), "")
        self.assertEqual(self.cat(abs_hint="leave", subject="휴가 현황 집계"), "")

    def test_subject_and_structure(self):
        self.assertEqual(self.cat(subject="[고객사:C01] 출장"), "trip")
        self.assertEqual(self.cat(subject="신입 안전 교육"), "edu")
        self.assertEqual(self.cat(subject="기술 세미나"), "edu")
        self.assertEqual(self.cat(subject="[고객사:C01] 방문"), "offsite")
        self.assertEqual(self.cat(subject="현장 점검"), "offsite")
        self.assertEqual(self.cat(busy="elsewhere"), "offsite")
        self.assertEqual(self.cat(location="external"), "offsite")
        self.assertEqual(self.cat(), "")
        self.assertEqual(meet_category(R.mail("2026-09-01T01:00:00Z", abs_hint="leave")), "")
        self.assertEqual(meet_category({}), "")


class LeavesTest(unittest.TestCase):
    def test_all_day_and_multi_day(self):
        got = leaves([leave_day("2026-09-01")])
        self.assertEqual(got, {date(2026, 9, 1): "full"})
        start = R.plus("2026-09-07T00:00:00Z", hours=-9)
        multi = R.cal(start, R.plus(start, days=3), abs_hint="leave", busy="oof", subject="",
                      flags={"all_day": True, "meeting_status": 0})
        self.assertEqual(leaves([multi]), {date(2026, 9, 7): "full", date(2026, 9, 8): "full", date(2026, 9, 9): "full"})

    def test_half_days(self):
        self.assertEqual(leaves([leave_day("2026-09-02", abs_hint="half_am")]), {date(2026, 9, 2): "am"})
        self.assertEqual(leaves([leave_day("2026-09-02", abs_hint="half_pm")]), {date(2026, 9, 2): "pm"})
        self.assertEqual(leaves([leave_day("2026-09-02", abs_hint="half", subject="오전 반차")]), {date(2026, 9, 2): "am"})
        self.assertEqual(leaves([leave_day("2026-09-02", abs_hint="half")]), {date(2026, 9, 2): "pm"})
        both = [leave_day("2026-09-03", abs_hint="half_am"), leave_day("2026-09-03", abs_hint="half_pm", msg="pm")]
        self.assertEqual(leaves(both), {date(2026, 9, 3): "full"}, "오전 + 오후 반차 = 종일")

    def test_timed(self):
        self.assertEqual(leaves([timed("2026-09-04", 9, 13, busy="oof")]), {date(2026, 9, 4): "am"})
        self.assertEqual(leaves([timed("2026-09-04", 14, 18, busy="oof")]), {date(2026, 9, 4): "pm"})
        self.assertEqual(leaves([timed("2026-09-04", 9, 18, busy="oof")]), {date(2026, 9, 4): "full"})
        self.assertEqual(leaves([timed("2026-09-04", 9, 17, busy="busy")]), {date(2026, 9, 4): "full"})
        self.assertEqual(leaves([timed("2026-09-04", 13, 17, busy="busy")]), {date(2026, 9, 4): "pm"})
        self.assertEqual(leaves([timed("2026-09-04", 15, 17, busy="busy", abs_hint="out")]), {}, "2시간 외출은 아님")
        self.assertEqual(leaves([timed("2026-09-04", 9, 18, busy="busy", abs_hint="half_am")]), {date(2026, 9, 4): "am"})

    def test_only_my_absence(self):
        cases = [leave_day("2026-09-01", flags={"all_day": True, "meeting_status": 5}),          # 취소
                 leave_day("2026-09-01", flags={"all_day": True, "meeting_status": 1, "response": 4}),   # 거절
                 leave_day("2026-09-01", flags={"all_day": True, "meeting_status": 3, "response": 5}),   # 미응답
                 leave_day("2026-09-01", busy="free", flags={"all_day": True, "meeting_status": 3}),     # 동료 공유
                 leave_day("2026-09-01", busy="free", flags={"all_day": True, "meeting_status": 1})]     # 한가함 초대
        for r in cases:
            self.assertEqual(leaves([r]), {}, r["flags"])
        mine = leave_day("2026-09-01", busy="oof", flags={"all_day": True, "meeting_status": 3})
        self.assertEqual(leaves([mine]), {date(2026, 9, 1): "full"}, "받은 초대라도 내가 부재중으로 두면 내 근태")
        no_status = leave_day("2026-09-01", busy="oof", flags={"all_day": True})
        self.assertEqual(leaves([no_status]), {date(2026, 9, 1): "full"}, "상태 열이 없는 경로(색인·OWA)")

    def test_non_leave_and_witness_ignored(self):
        trip = leave_day("2026-09-01", abs_hint="trip")
        guard = leave_day("2026-09-01", subject="연차 사용 촉진 안내")
        wit = dict(leave_day("2026-09-01"), src="cal.copilot", ts_precision="summary")
        unknown = dict(leave_day("2026-09-01"), ts_precision="unknown")
        mail = R.mail("2026-09-01T01:00:00Z", abs_hint="leave")
        self.assertEqual(leaves([trip, guard, wit, unknown, mail]), {})

    def test_holidays_removed_with_calendar(self):
        from lm27.time.calendar import Calendar
        cal = Calendar(ROOT / "config" / "calendar.json")
        start = R.plus("2026-09-23T00:00:00Z", hours=-9)                       # 9/23(수) ~ 9/28(월) — 추석·주말 사이
        r = R.cal(start, R.plus(start, days=6), abs_hint="leave", busy="oof", subject="",
                  flags={"all_day": True, "meeting_status": 0})
        got = leaves([r], cal)
        for d, code in got.items():
            self.assertFalse(cal.is_holiday(d), d)
            self.assertIn(code, LEAVE_CODES)
        self.assertIn(date(2026, 9, 23), got)
        self.assertNotIn(date(2026, 9, 24), got)
        self.assertNotIn(date(2026, 9, 26), got)
        self.assertEqual(len(leaves([r])), 6, "달력 없이는 걸친 날 전부")
        far = leave_day("2031-03-04")
        self.assertEqual(leaves([far], cal), {date(2031, 3, 4): "full"}, "달력에 없는 해는 거르지 않는다")

    def test_offset_parameter(self):
        r = R.cal("2026-09-01T00:00:00Z", "2026-09-02T00:00:00Z", abs_hint="leave", busy="oof", subject="",
                  off="+00:00", flags={"all_day": True, "meeting_status": 0})    # UTC 시간대 일정(수집 오프셋 +00:00)
        self.assertEqual(leaves([r]), {date(2026, 9, 1): "full"})
        self.assertEqual(leaves([r], off_min=540), {date(2026, 9, 1): "full"}, "자정 시작 오프셋을 고른다")
        kst = R.cal("2026-08-31T15:00:00Z", "2026-09-01T15:00:00Z", abs_hint="leave", busy="oof", subject="",
                    off="+00:00", flags={"all_day": True, "meeting_status": 0})  # KST 종일 일정을 UTC 클라우드PC 가 봄
        self.assertEqual(leaves([kst], off_min=540), {date(2026, 9, 1): "full"}, "이틀로 갈라지지 않는다")
        timed_kst = timed("2026-09-04", 9, 13, busy="oof", off="+00:00")
        self.assertEqual(leaves([timed_kst], off_min=540), {date(2026, 9, 4): "am"})

    def test_result_feeds_build_days(self):
        from types import SimpleNamespace

        from lm27.config import load_config
        from lm27.time.calendar import Calendar, build_days
        cfg = load_config(registry_path=ROOT / "config" / "settings_registry.json",
                          config_path=ROOT / "no_such_config.json")
        lv = leaves([leave_day("2026-09-01"), leave_day("2026-09-02", abs_hint="half_am")])
        ev = SimpleNamespace(d0=date(2026, 9, 1), d1=date(2026, 9, 2), leaves=lv, manual=[])
        days = build_days(ev, cfg, Calendar(ROOT / "config" / "calendar.json"))
        self.assertEqual(days[date(2026, 9, 1)]["leave"], 1.0)
        self.assertEqual(days[date(2026, 9, 2)]["leave"], 0.5)


if __name__ == "__main__":
    unittest.main()
