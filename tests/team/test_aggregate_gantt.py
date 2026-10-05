# -*- coding: utf-8 -*-
"""WP-27 간트·드릴다운 — active 구간(gap=2)·주별 밀도·병행도·행 계층·피벗 합·단위업무 이월(TAB §4.6 · A07 · A11 · R §7.6·§7.8.2).
"""
import unittest
from collections import defaultdict
from datetime import date

from lm27.team import aggregate as A
from lm27.team import schema
from tests.fixtures.wp27 import bundles as B

PK1, PK2 = B.person_key(1), B.person_key(2)


class GanttCase(unittest.TestCase):
    def setUp(self):
        self._td = B.temp_dir()
        self.dir = self._td.__enter__()
        self.st = B.new_store(self.dir)

    def tearDown(self):
        self._td.__exit__(None, None, None)

    def put(self, obj):
        r = B.put_bundle(self.st, obj)
        self.assertTrue(r.ok, (r.code, r.detail))


def _only_days(obj, uid, days):
    """단위업무 uid 의 귀속을 주어진 날들만 남긴다(다른 업무는 그대로) + 요약 재계산."""
    keep = {d.isoformat() for d in days}
    obj["alloc_daily"]["rows"] = [r for r in obj["alloc_daily"]["rows"] if r[1] != uid or r[0] in keep]
    B.finalize(obj)
    return obj


class TestGantt(GanttCase):
    def test_a11_active_spans_density_parallel(self):
        """A11: 빈 날 1·3일이 섞인 귀속 → active = active_spans(gap=2), 주별 밀도 합 = effort_min."""
        o = B.make_bundle(PK1, "2026-07-01", "2026-07-31", built_at="2026-08-01T09:00:00+09:00", dense=True)
        uid = o["units"][0]["unit_id"]
        days = [date(2026, 7, 1), date(2026, 7, 2), date(2026, 7, 6), date(2026, 7, 7), date(2026, 7, 13)]
        _only_days(o, uid, days)
        self.put(o)
        res = A.aggregate(self.st, 1)
        self.assertFalse([w for w in res.warnings if w.startswith("I")], res.warnings)
        units = {u["unit_id"]: u for row in res.td["gantt"] for u in row["units"]}
        u = units[uid]
        acts = [tuple(s[:2]) for s in u["spans"] if s[2] == "active"]
        want = [(a.isoformat(), b.isoformat()) for a, b in schema.active_spans(days, 2)]
        self.assertEqual(acts, want)
        self.assertEqual(acts, [("2026-07-01", "2026-07-02"), ("2026-07-06", "2026-07-07"), ("2026-07-13", "2026-07-13")])
        self.assertEqual(sum(u["density"].values()), u["effort_min"])
        self.assertEqual(sorted(u["density"]), ["2026-W27", "2026-W28", "2026-W29"])
        self.assertEqual(sum(1 for s in u["spans"] if s[2] == "lead"), 1)
        per_day = defaultdict(set)
        for d, x, _t, _m in o["alloc_daily"]["rows"]:
            per_day[d].add(x)
        want_par = sum(len(per_day[d.isoformat()]) for d in days) / len(days)
        self.assertEqual(u["parallel"], want_par)                                  # 원값(반올림 없음)

    def test_gap_setting_changes_spans(self):
        st = B.new_store(self.dir / "g0", **{"teamServer.ganttMergeGapDays": 0})
        o = B.make_bundle(PK1, "2026-07-01", "2026-07-31", built_at="2026-08-01T09:00:00+09:00", dense=True)
        uid = o["units"][0]["unit_id"]
        _only_days(o, uid, [date(2026, 7, 1), date(2026, 7, 3)])
        B.put_bundle(st, o)
        res = A.aggregate(st, 1)
        u = next(u for row in res.td["gantt"] for u in row["units"] if u["unit_id"] == uid)
        self.assertEqual([s[:2] for s in u["spans"] if s[2] == "active"],
                         [["2026-07-01", "2026-07-01"], ["2026-07-03", "2026-07-03"]])
        self.assertTrue(any("I7 gantt_mismatch" in w for w in res.warnings))      # 묶음은 gap 2 로 만들었다

    def test_a07_unit_carry_over(self):
        """A07: 같은 unit_id 가 8월(묶음 A)·9월(묶음 B) → 막대 하나, lead 띠 합침, active·밀도는 alloc 에서 재계산."""
        shared = B.unit_id("carry", 0)
        a = B.make_bundle(PK1, "2026-08-01", "2026-08-31", built_at="2026-09-01T09:00:00+09:00",
                          unit_ids=[shared, B.unit_id("a", 1)], dense=True)
        b = B.make_bundle(PK1, "2026-09-01", "2026-09-30", built_at="2026-10-01T09:00:00+09:00",
                          unit_ids=[shared, B.unit_id("b", 1)], dense=True, seed=5)
        self.put(a)
        self.put(b)
        res = A.aggregate(self.st, 1)
        bars = [u for row in res.td["gantt"] for u in row["units"] if u["unit_id"] == shared]
        self.assertEqual(len(bars), 1)
        u = bars[0]
        lead = [s for s in u["spans"] if s[2] == "lead"][0]
        la = next(x for x in a["units"] if x["unit_id"] == shared)["spans"][0]
        lb = next(x for x in b["units"] if x["unit_id"] == shared)["spans"][0]
        self.assertEqual(lead[:2], [la[0], lb[1]])
        eff = sum(next(x for x in bd["units"] if x["unit_id"] == shared)["effort_min"] for bd in (a, b))
        self.assertEqual(u["effort_min"], eff)
        self.assertEqual(sum(u["density"].values()), eff)
        self.assertEqual(u["title"], next(x for x in b["units"] if x["unit_id"] == shared)["title"])  # 가장 늦은 달 값

    def test_unstable_unit_id_warned_not_merged(self):
        """R-4 깨짐: 같은 역할·같은 제목·겹치는 기간의 다른 unit_id → 막대 둘 + '단위업무 ID 불안정 의심' 경고."""
        o = B.make_bundle(PK1, "2026-07-01", "2026-07-31", built_at="2026-08-01T09:00:00+09:00", n_units=2, dense=True)
        for u in o["units"]:
            u["title"] = "같은 제목"
        self.put(o)
        res = A.aggregate(self.st, 1)
        self.assertTrue(any("ID 불안정" in w for w in res.warnings), res.warnings)
        self.assertEqual(sum(len(r["units"]) for r in res.td["gantt"]), 2)

    def test_hierarchy_order_pivot_and_details(self):
        """기본 행 계층 담당자 → 영역 → 과제 → 역할, 피벗(영역 → 과제 → 역할 → 담당자)도 같은 합. 드릴다운 키 "<i>|<role_id>"."""
        self.put(B.make_bundle(PK1, "2026-07-01", "2026-07-31", built_at="2026-08-01T09:00:00+09:00"))
        self.put(B.make_bundle(PK1, "2026-08-01", "2026-08-31", built_at="2026-09-01T09:00:00+09:00",
                               project="P-0002", domain="MP", field="MECH", func="TEST", seed=4))
        self.put(B.make_bundle(PK2, "2026-07-01", "2026-07-31", built_at="2026-08-01T09:00:00+09:00",
                               project="P-0002", domain="MP", field="MECH", func="TEST", seed=6))
        res = A.aggregate(self.st, 1)
        td, det = res.td, res.details
        rank = {d: k for k, d in enumerate(schema.DOMAINS_ALL)}
        keys = [(r["person"], rank[r["domain"]]) for r in td["gantt"]]
        self.assertEqual(keys, sorted(keys))
        by_default = defaultdict(int)
        by_pivot = defaultdict(int)
        for r in td["gantt"]:
            for u in r["units"]:
                by_default[(r["person"], r["domain"], r["project_id"], r["role_id"])] += u["effort_min"]
                by_pivot[(r["domain"], r["project_id"], r["role_id"], r["person"])] += u["effort_min"]
            self.assertAlmostEqual(r["row_end"]["effort_h"], sum(u["effort_min"] for u in r["units"]) / 60, places=12)
            self.assertGreaterEqual(r["row_end"]["lead_days"], 1)
            d = det[f"{r['person']}|{r['role_id']}"]
            self.assertEqual(d["person"]["i"], r["person"])
            self.assertEqual([x["no"] for x in d["workflow"]["steps"]], [1, 2])
            self.assertEqual(len(d["units"]), len(r["units"]))
        self.assertEqual(sum(by_default.values()), sum(by_pivot.values()))
        mp = [x for x in td["roles"] if x["domain"] == "MP"]
        self.assertEqual(len(mp), 1)                                               # 같은 역할 2명 = role_id 하나
        self.assertEqual(sorted(i for i, _v in mp[0]["by_person"]), [0, 1])
        self.assertEqual(mp[0]["subagent"]["조건부"], 2)

    def test_biz_minutes(self):
        cal = self.st.calendar()
        # 2026-07-03(금) 10:12 ~ 07-06(월) 16:40, 표준창 09-18 · 점심 12-13
        v = A.biz_minutes("2026-07-03T10:12:00+09:00", "2026-07-06T16:40:00+09:00", 540, cal)
        self.assertEqual(v, (18 * 60 - (10 * 60 + 12) - 60) + ((16 * 60 + 40) - 9 * 60 - 60))
        self.assertEqual(A.biz_minutes("2026-07-17T09:00:00+09:00", "2026-07-17T18:00:00+09:00", 540, cal), 0)  # 제헌절
        self.assertIsNone(A.biz_minutes(None, "2026-07-17T18:00:00+09:00", 540, cal))
        self.assertEqual(A.iso_week(date(2026, 7, 6)), "2026-W28")
