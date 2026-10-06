# -*- coding: utf-8 -*-
"""WP-20 정수 분 표(W-G5 · T-05 · W §5.6 · TAB R-3): 개인 = 팀.

- 팀 서버가 정수 분 표(envelope_daily)만으로 다시 합친 월 MM = 개인 MM(완전 일치 — 같은 분자·같은 분모).
- 모든 (날짜, 꼬리표) 칸: Σalloc ≤ envelope, alloc + 버킷 = envelope(최대잉여 — Σ 정확).
- 단위업무 effort_min = Σ 그 unit 의 alloc(I6), mm_month 의 attributed + unattributed = env, Σ buckets = unattributed.
- 동률 규칙(계약 §5.3): 잉여 동률이면 단위업무(u_) 가 버킷(B_)보다 먼저 받는다.
"""
from __future__ import annotations

import unittest
from collections import Counter, defaultdict
from datetime import date

from lm27.time.calendar import SLOT, TAGS, build_days, day0
from lm27.time.ledger import task_rows
from lm27.time.mm import team_tables
from tests.fixtures.wp20 import harness as H
from tests.time import scenarios as X


def team_mm(tables_json: dict, std: int, workdays: dict) -> dict:
    """팀 서버 재합산(TAB §4.4): 월 envelope 분 ÷ (std × W)."""
    by_m: Counter = Counter()
    for row in tables_json["envelope_daily"]["rows"]:
        d = date.fromisoformat(row[0])
        by_m[(d.year, d.month)] += sum(row[1:])
    return {k: v / (std * workdays[k]) for k, v in by_m.items()}


class TeamTablesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = X.base_cfg()
        cls.res = {name: H.run(fn(), cls.cfg, ref_ids=False)[0] for name, fn in X.SC.items()}

    def test_personal_equals_team_all_scenarios(self):
        for name, r in sorted(self.res.items()):
            with self.subTest(name=name):
                tj = r.tables.as_json()
                wd = {k: v["workdays"] for k, v in r.months.items()}
                tm = team_mm(tj, 480, wd)
                for k, row in r.months.items():
                    if row["denominator"] != "workdays":
                        continue
                    self.assertEqual(tm.get(k, 0.0), row["mm"], (name, k))          # 완전 일치(같은 산식)
                    self.assertEqual(sum(sum(x[1:]) for x in tj["envelope_daily"]["rows"]
                                         if date.fromisoformat(x[0]).month == k[1]
                                         and date.fromisoformat(x[0]).year == k[0]), row["env_min"])

    def test_cell_integrity(self):
        for name, r in sorted(self.res.items()):
            with self.subTest(name=name):
                t = r.tables
                alloc: Counter = Counter()
                for (d, _u, tag), v in t.alloc.items():
                    alloc[(d, tag)] += v
                bucket: Counter = Counter()
                for (d, _b, tag), v in t.bucket.items():
                    bucket[(d, tag)] += v
                for key, em in t.env.items():
                    self.assertLessEqual(alloc[key], em, (name, key))
                    self.assertEqual(alloc[key] + bucket[key], em, (name, key))
                self.assertEqual(sum(t.env.values()), len(r.env.slots) * SLOT // 60)

    def test_effort_equals_alloc_and_month_identities(self):
        for name, r in sorted(self.res.items()):
            with self.subTest(name=name):
                eff = r.tables.effort_min()
                rows = {t["unit_id"]: t for t in task_rows(r)}
                for u, m in eff.items():
                    self.assertIn(u, rows)
                    self.assertGreater(m, 0)
                for row in r.months.values():
                    self.assertEqual(row["attributed_min"] + row["unattributed_min"], row["env_min"])
                    self.assertEqual(sum(row["buckets_min"].values()), row["unattributed_min"])
                    self.assertEqual(sum(row["by_tag_min"].values()), row["env_min"])
                    um = sum(row["units_mm"].values())
                    self.assertAlmostEqual(um * 480 * row["denom_days"], row["attributed_min"], places=6)

    def test_alloc_json_rows_valid(self):
        for name, r in sorted(self.res.items()):
            with self.subTest(name=name):
                tj = r.tables.as_json()
                self.assertEqual(tj["envelope_daily"]["cols"], ["date", *TAGS])
                self.assertEqual(tj["alloc_daily"]["cols"], ["date", "unit_id", "tag", "min"])
                dates = [x[0] for x in tj["envelope_daily"]["rows"]]
                self.assertEqual(dates, sorted(set(dates)))
                seen = set()
                for d, u, tag, m in tj["alloc_daily"]["rows"]:
                    self.assertRegex(u, r"^u_[0-9a-f]{10}$")
                    self.assertIn(tag, TAGS)
                    self.assertTrue(1 <= m <= 1440)
                    self.assertNotIn((d, u, tag), seen)
                    seen.add((d, u, tag))
                for row in tj["envelope_daily"]["rows"]:
                    self.assertTrue(all(isinstance(v, int) and 0 <= v <= 1440 for v in row[1:]))
                    self.assertLessEqual(sum(row[1:]), 1440)

    def test_tie_rule_units_first(self):
        """5분 칸에서 업무 150초 · 버킷 150초 → 2.5 + 2.5 분 — 잉여 1분은 단위업무가 받는다(계약 §5.3 · X-208)."""
        s = (day0(date(2026, 10, 14)) + 10 * 3600) // SLOT                       # 10:00 슬롯
        assign = {s: {"u_0000000001": 150, "B_GENERIC": 150}}
        days = build_days(type("E", (), {"d0": date(2026, 10, 14), "d1": date(2026, 10, 14), "leaves": {},
                                         "manual": []})(), self.cfg, X.calendar())
        t = team_tables({s}, assign, days, self.cfg)
        self.assertEqual(t.alloc, {(date(2026, 10, 14), "u_0000000001", "regular"): 3})
        self.assertEqual(t.bucket, {(date(2026, 10, 14), "B_GENERIC", "regular"): 2})

    def test_classification_does_not_change_tables(self):
        """T-06: 롤업 라벨(분류 결과)을 줘도 team_tables.json 바이트는 같다."""
        for name in ("W01", "W18", "W45", "W51"):
            a, names = H.run(X.SC[name](), self.cfg, ref_ids=False)
            labels = {t.id: {"domain": "DEV", "project": "P-0007", "role": "r_000001", "wtype": "DEV",
                             "ax_link": False} for t in a.tasks}
            b, _ = H.run(X.SC[name](), self.cfg, ref_ids=False, labels=labels)
            self.assertEqual(a.files()["team_tables.json"], b.files()["team_tables.json"], name)
            self.assertNotEqual(a.files()["mm_month.json"], b.files()["mm_month.json"], name)

    def test_month_cross_midnight_split(self):
        """W46: 9/30 23:00~10/1 01:30 → 9월 야간 60분, 10월 야간 90분(정수 분 표에서도)."""
        r = self.res["W46"]
        night: dict = defaultdict(int)
        for (d, tag), v in r.tables.env.items():
            if tag == "night":
                night[(d.year, d.month)] += v
        self.assertEqual(night[(2026, 9)], 60)
        self.assertEqual(night[(2026, 10)], 90)


if __name__ == "__main__":
    unittest.main()
