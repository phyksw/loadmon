# -*- coding: utf-8 -*-
"""WP-20 월 MM·초과·가용·로드(W §6 · 계약 §3.14 mm_month.json · X-209 · X-210 · X-211 · REQ-25).

W51 월 MM · 1MM 초과를 자르지 않음(합성 달 근무일 20 × 9h + 휴일 근무) · 부분월과 '오늘'(X-210) · 분모 선택(개인 표시
전용) · 추정 부재 · 연차·반차 · 보조 집계(휴일 야간·휴가 중 근무·기계 시간) · 롤업(라벨 없음 = UNC, 버킷은 과제로
옮기지 않음).
"""
from __future__ import annotations

import unittest
from datetime import date, timedelta

from lm27.time.mm import rollup
from tests.fixtures.wp20 import harness as H
from tests.time import scenarios as X


def month(res, y, m):
    return res.months[(y, m)]


class MonthMMTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = X.base_cfg()

    def run_w(self, w, **over):
        cfg = self.cfg.derive(over) if over else self.cfg
        return H.run(w, cfg, ref_ids=False)[0]

    def test_w51_month(self):
        r = self.run_w(X.SC["W51"]())
        m = month(r, 2026, 9)
        self.assertEqual(m["workdays"], 20)
        self.assertEqual(m["env_min"], 158 * 60)
        self.assertEqual(m["by_tag_min"], {"regular": 148 * 60, "extended": 4 * 60, "night": 2 * 60,
                                           "holiday": 4 * 60})
        self.assertEqual(m["mm"], 158 / 160)
        self.assertEqual(m["avail_days"], 18.5)                              # 연차 1 · 오후 반차 0.5
        self.assertEqual(m["absence_days"], 1.5)
        self.assertAlmostEqual(m["load_pct"], 158 / 148 * 100, places=9)
        self.assertEqual(m["overtime_window_min"], 10 * 60)

    def test_over_one_mm_not_clipped(self):
        """근무일 20 × 9h(점심 포함 수동 기록) + 토요일 4h → MM 1.15, 로드 115% — 자르지 않는다(상한 없음)."""
        w = X.W("OVER", "2026-10-01", "2026-10-31", "2026-11-02 09:00")
        cal = X.calendar()
        d = date(2026, 10, 1)
        while d.month == 10:
            s = d.isoformat()
            if not cal.is_holiday(d):
                w.man("work", a=f"{s} 09:00", b=f"{s} 18:00", ref="양산지원_과제B.xlsx")
            d += timedelta(days=1)
        w.man("work", a="2026-10-17 10:00", b="2026-10-17 14:00", ref="양산지원_과제B.xlsx")
        r = self.run_w(w)
        m = month(r, 2026, 10)
        self.assertEqual(m["workdays"], 20)
        self.assertEqual(m["env_min"], (20 * 9 + 4) * 60)
        self.assertGreater(m["mm"], 1.0)
        self.assertAlmostEqual(m["mm"], 184 / 160, places=12)
        self.assertGreater(m["load_pct"], 100.0)
        self.assertAlmostEqual(m["load_pct"], 115.0, places=9)
        self.assertEqual(m["overtime_window_min"], (20 + 4) * 60)            # 점심 근무 = 연장, 토요일 = 휴일
        self.assertEqual(m["overtime_daily8h_min"], (20 + 4) * 60)

    def test_partial_month_today_rule(self):
        """X-210: 오늘은 as_of 가 그날 표준창 끝을 지났을 때만 covered — 13:30 이면 7일, 18:30 이면 8일."""
        r = self.run_w(X.SC["W64"]())
        m = month(r, 2026, 10)
        self.assertEqual((m["covered_workdays"], m["avail_days"]), (7, 7.0))
        self.assertEqual(round(m["mm"], 4), 0.3708)                          # 분모는 그 달 전체(부분월 부풀림 없음)
        w = X.SC["W64"]()
        w.as_of = "2026-10-14 18:30"
        m2 = month(self.run_w(w), 2026, 10)
        self.assertEqual(m2["covered_workdays"], 8)

    def test_denominator_weekdays_personal_only(self):
        r = self.run_w(X.SC["W51"](), **{"mm.denominator": "weekdays"})
        m = month(r, 2026, 9)
        self.assertEqual(m["workdays"], 20)                                  # 팀 분모 열은 그대로
        self.assertEqual((m["denominator"], m["denom_days"]), ("weekdays", 22))
        self.assertEqual(m["mm"], 158 * 60 / (480 * 22))
        tj = r.tables.as_json()
        r0 = self.run_w(X.SC["W51"]())
        self.assertEqual(tj, r0.tables.as_json())                            # 정수 분 표는 분모와 무관

    def test_inferred_absence_mode(self):
        base = month(self.run_w(X.SC["W20"]()), 2026, 9)
        excl = month(self.run_w(X.SC["W20"](), **{"mm.inferredAbsence": "exclude"}), 2026, 9)
        self.assertEqual(base["absence_days"], 0.0)
        self.assertGreater(excl["absence_days"], 10)
        self.assertLess(excl["avail_days"], base["avail_days"])

    def test_leave_and_on_leave_minutes(self):
        r = self.run_w(X.SC["W52B"]())
        m = month(r, 2026, 10)
        self.assertEqual(m["on_leave_min"], 60)                              # 오전 반차 중 10:30~11:30 근무
        self.assertEqual(m["absence_days"], 0.5)

    def test_holiday_night_and_machine(self):
        r = self.run_w(X.SC["W53"]())
        self.assertEqual(month(r, 2026, 10)["holiday_night_min"], 60)        # 토 00:00~01:00 회의
        r = self.run_w(X.SC["W42"]())
        self.assertEqual(month(r, 2026, 10)["machine_min"], 690)             # 연산 11.5h — MM 에는 없음
        self.assertEqual(month(r, 2026, 10)["env_min"], 15 * 60)

    def test_rollup(self):
        r = self.run_w(X.SC["W18"]())
        m = month(r, 2026, 10)
        units = sorted(m["units_mm"])
        labels = {units[0]: {"domain": "DEV", "project": "P-0007", "role": "r_8412d7", "wtype": "DEV",
                             "ax_link": True}}
        ro = rollup(m, labels)
        self.assertAlmostEqual(sum(ro["domain"].values()) + ro["unattributed"], m["mm"], places=12)
        self.assertIn("UNC", ro["domain"])                                   # 라벨 없음 = 미분류(숨기지 않음)
        self.assertEqual(set(ro["domain"]), {"DEV", "UNC"})
        self.assertAlmostEqual(ro["ax_link"]["true"], m["units_mm"][units[0]], places=12)
        self.assertNotIn("B_MEET", ro["project"])                            # 버킷은 과제로 옮기지 않는다(X-211)
        empty = rollup(m, None)
        self.assertEqual(set(empty["domain"]), {"UNC"})

        class Lab:                                                           # UnitLabel 같은 속성 객체도 받는다
            domain, project, proposal_id, role_id, wtype, ax_link = "MP", None, "pr_1", "r_000001", "OFFICE", False
        ro2 = rollup(m, {units[0]: Lab()})
        self.assertIn("MP", ro2["domain"])
        self.assertIn("pr_1", ro2["project"])
        self.assertIn("r_000001", ro2["role"])


if __name__ == "__main__":
    unittest.main()
