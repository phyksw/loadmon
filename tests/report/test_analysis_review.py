# -*- coding: utf-8 -*-
"""WP-30 주간·월간 리뷰(R §4.4 · §4.10.1 · RPT-20 · RPT-28).

- RPT-20: 리드 초과 골든(기준 = u_a1·u_a2·u_a3 의 영업 리드 중앙 2360분, 문턱 3540) — u_a4 초과 아님, u_a5 초과
  WAIT·REWORK·PARALLEL·LATE_START(SCOPE 아님), 표본이 모자라면 NO_BASELINE.
- 기간 사실: 정수 분 표 합(env = 귀속 + 미귀속, 귀속 = 관측 + 추정), 시작·끝·계속·미착수, 부분 주.
- RPT-28: 리뷰 사실 상한 25 · 순서(완료 → 시작 → 진행 → 보류) · ai_in 에 시간형 숫자 0.
- 초과 근무 원인(R §4.4.4): window 기준(연장·야간·휴일 꼬리표) · daily8h 기준(일 std 초과분 최대잉여).
"""
from __future__ import annotations

import json
import os
import re
import unittest

from lm27.report.analysis import ai_items as AI
from lm27.report.analysis import mining, ontology, peers
from lm27.report.analysis import review as R
from tests.fixtures.wp30 import world as W

TIME_RX = re.compile(r"\d+(\.\d+)?\s*(MM|시간|h|분)")


def golden():
    with open(os.path.join(W.ROOT, "tests", "fixtures", "wp30", "golden_report.json"), encoding="utf-8") as f:
        return json.load(f)


def reviews(ctx):
    wf, _tr = mining.workflows(ctx)
    pidx = peers.peer_index(ctx.units.values(), ctx.evidence, ctx.person_dir, ctx.cfg)
    rels = ontology.relations(ctx, pidx, ontology.unit_set_map(ctx, pidx))
    return R.review_periods(ctx, wf=wf, pidx=pidx, rels=rels), pidx


class OverrunTest(unittest.TestCase):
    def test_golden_rpt20(self):
        g = golden()
        cfg = W.cfg()
        a4, a5 = g["overrun_u_a4"], g["overrun_u_a5"]
        r4 = R.overrun_causes(a4["unit"], (a4["baseline_biz_lead_min"], 420), cfg)
        self.assertEqual((r4["overrun"], r4["causes"]), (False, []))
        r5 = R.overrun_causes(a5["unit"], (a5["baseline_biz_lead_min"], a5["baseline_effort_min"]), cfg)
        self.assertEqual((r5["overrun"], r5["causes"]), (True, a5["result"]["causes"]))
        self.assertEqual(r5["causes"], ["WAIT", "REWORK", "PARALLEL", "LATE_START"])
        self.assertEqual(r5["baseline_biz_min"], 2360)
        self.assertEqual(R.overrun_causes(a5["unit"], None, cfg)["causes"], ["NO_BASELINE"])
        unexplained = dict(a5["unit"], cycles=1, parallel=1.0, start_to_first_wd=0, max_wait_biz_min=0)
        self.assertEqual(R.overrun_causes(unexplained, (2360, 210), cfg)["causes"], ["UNEXPLAINED"])
        data = dict(unexplained, grade="D")
        self.assertEqual(R.overrun_causes(data, (2360, 210), cfg)["causes"], ["DATA"])
        scope = dict(unexplained, effort_min=315)
        self.assertEqual(R.overrun_causes(scope, (2360, 210), cfg)["causes"], ["SCOPE"])

    def test_baseline_from_world(self):
        ctx = W.golden_role_a().context()
        units = list(ctx.units.values())
        self.assertEqual(R.baseline_of(ctx.units["u_a4"], units, ctx.cfg), (2360, 425))
        self.assertIsNone(R.baseline_of(ctx.units["u_a3"], units, ctx.cfg))   # 앞선 완료 2건뿐, 영역·기능도 2건
        o = R.unit_overrun(ctx, ctx.units["u_a4"], None)
        self.assertEqual((o["overrun"], o["causes"], o["ratio"]), (False, [], 1.4))
        o3 = R.unit_overrun(ctx, ctx.units["u_a3"], None)
        self.assertEqual(o3["causes"], ["NO_BASELINE"])
        self.assertEqual(o3["texts"], ["비교할 완료 업무가 부족합니다."])

    def test_widen_to_domain_func(self):
        """같은 역할 표본이 모자라면 같은 영역·같은 기능으로 넓힌다."""
        w = W.golden_role_a()
        for k in ("u_a1", "u_a2"):
            w.labels[k]["field"] = "MECH"
            w.labels[k]["role_id"] = W.role_id("P-0007", "MECH", "ANALYSIS")
        ctx = w.context()
        units = list(ctx.units.values())
        self.assertNotEqual(ctx.units["u_a1"].role_id, ctx.units["u_a4"].role_id)
        self.assertEqual(R.baseline_of(ctx.units["u_a4"], units, ctx.cfg), (2360, 425))
        self.assertIsNone(R.baseline_of(ctx.units["u_a4"], units, W.cfg(**{"report.review.baselineMinUnits": 4})))


class PeriodFactsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        w = W.golden_role_a()
        w.unit("u_z1", status="not_started", start=("2026-09-23", "10:00"), title="미착수 의뢰")
        w.unit("u_o1", start=("2026-09-29", "09:00"), title="진행 중 업무")
        w.run("u_o1", "DOC_DOC", "2026-09-29", "09:00", "11:00", fam="d9")
        w.run("u_o1", "DOC_DOC", "2026-09-29", "19:00", "20:00", fam="d9")
        w.bucket("B_COMM", "2026-09-29", "11:00", "11:30")
        cls.ctx = w.context()
        cls.rv, cls.pidx = reviews(cls.ctx)

    def test_periods(self):
        keys = [r["key"] for r in self.rv["weeks"]]
        self.assertEqual(keys, ["2026-W36", "2026-W37", "2026-W38", "2026-W39", "2026-W40"])
        self.assertEqual(self.rv["weeks"][0]["partial"], {"from": "2026-09-01", "to": "2026-09-06", "workdays": 4,
                                                          "of": 5})
        self.assertIsNone(self.rv["weeks"][1]["partial"])
        self.assertEqual([r["key"] for r in self.rv["months"]], ["2026-09", "2026-10"])
        self.assertEqual(self.rv["months"][1]["partial"]["to"], "2026-10-04")

    def test_identities(self):
        for r in self.rv["weeks"] + self.rv["months"]:
            self.assertEqual(r["attributed_min"] + r["unattr_min"], r["env_min"], r["key"])
            self.assertEqual(r["obs_min"] + r["est_min"], r["attributed_min"], r["key"])
            self.assertEqual(sum(r["by_tag"].values()), r["env_min"], r["key"])
        sep = self.rv["months"][0]
        self.assertEqual(sep["env_min"], sum(sum(self.ctx.env[d].values()) for d in self.ctx.env if d < "2026-10"))

    def test_sets(self):
        w40 = next(r for r in self.rv["weeks"] if r["key"] == "2026-W40")
        self.assertEqual([x["unit_id"] for x in w40["started"]], ["u_o1"])
        self.assertEqual([x["unit_id"] for x in w40["finished"]], ["u_a4"])
        w39 = next(r for r in self.rv["weeks"] if r["key"] == "2026-W39")
        self.assertEqual([x["unit_id"] for x in w39["unstarted"]], ["u_z1"])
        self.assertEqual([x["unit_id"] for x in w39["started"]], ["u_a4"])
        lt = next(r for r in self.rv["weeks"] if r["key"] == "2026-W38")["lead_table"]
        self.assertEqual([x["unit_id"] for x in lt], ["u_a2", "u_a3"])          # 09-16 · 09-18 끝
        self.assertEqual([x["biz_lead_min"] for x in lt], [3420, 2360])
        self.assertEqual([x["causes"] for x in lt], [["NO_BASELINE"], ["NO_BASELINE"]])
        self.assertEqual(w40["top_projects"][0]["key"], "P-0007")
        ot = w40["ot_units"]
        self.assertEqual(ot["basis"], "window")
        self.assertEqual(ot["units"], [{"unit_id": "u_o1", "min": 60}])

    def test_overtime_daily8h(self):
        w = W.World("2026-09-01", "2026-09-30", "2026-09-30T18:00")
        w.unit("u_d1", start=("2026-09-01", "08:00"), end=("2026-09-01", "21:00"))
        w.run("u_d1", "DOC_DOC", "2026-09-01", "08:00", "17:00")
        w.unit("u_d2", start=("2026-09-01", "08:00"), end=("2026-09-01", "21:00"))
        w.run("u_d2", "DOC_XLS", "2026-09-01", "17:00", "20:00")
        ctx = w.context(cfg=W.cfg(**{"mm.overtimeBasis": "daily8h"}))
        ot = R.overtime(ctx, ["2026-09-01"], {"2026-09-01": {"u_d1": 540, "u_d2": 180}})
        self.assertEqual(ot["basis"], "daily8h")
        self.assertEqual(ot["total_min"], 720 - 480)
        self.assertEqual(sum(x["min"] for x in ot["units"]) + ot["unattributed_min"], 240)
        self.assertEqual(ot["units"][0], {"unit_id": "u_d1", "min": 180})       # 540:180 비율로 240 → 180·60


class FactsTest(unittest.TestCase):
    """RPT-28 — 한 달 단위업무 40개 → facts 25개(완료 → 시작 → 진행 → 보류), ai_in 시간형 숫자 0."""

    def test_facts_order_and_cap(self):
        w = W.World("2026-09-01", "2026-09-30", "2026-09-30T18:00")
        days = [d for d in range(1, 31) if W.calendar().is_holiday(f"2026-09-{d:02d}") is False]
        for i in range(40):
            d = f"2026-09-{days[i % len(days)]:02d}"
            uid = f"u_f{i:02d}"
            if i < 10:
                w.unit(uid, start=(d, "09:00"), end=(d, "17:00"), title=f"완료 업무 {i} 3시간 검토")
            elif i < 30:
                w.unit(uid, start=(d, "09:00"), title=f"진행 업무 {i} 2.5h")
            else:
                w.unit(uid, start=("2026-08-03", "09:00"), title=f"계속 업무 {i}")
            if i < 38:
                w.run(uid, "DOC_DOC", d, "10:00", f"{10 + (i % 5)}:30")
        w.unit("u_hold", start=("2026-08-03", "09:00"), title="오래 열린 보류 업무")
        ctx = w.context()
        rv, pidx = reviews(ctx)
        sep = rv["months"][0]
        self.assertEqual(len(sep["facts"]), 25)
        order = [f[1] for f in sep["facts"]]
        self.assertEqual(order, sorted(order, key=["완료", "시작", "진행", "보류"].index))
        self.assertEqual(order[:10], ["완료"] * 10)
        self.assertEqual(sep["facts"][0][0], "F1")
        items = AI.review_items(ctx, rv, pidx)
        blob = json.dumps([it["fields"] for it in items], ensure_ascii=False)
        self.assertIsNone(TIME_RX.search(blob), TIME_RX.search(blob))
        month = next(it for it in items if it["key"] == "review:month:2026-09")
        self.assertEqual(month["fields"]["kind"], "month")
        self.assertEqual(month["fields"]["period"], "2026-09-01~2026-09-30")
        self.assertIn("edges", month["fields"])
        self.assertLessEqual(len(month["fields"]["edges"]), 12)
        wk = [it for it in items if it["key"].startswith("review:week:")]
        self.assertTrue(wk)
        self.assertNotIn("edges", wk[0]["fields"])
        # 보류 = OPEN · 기간 분 0 · 20근무일 넘게 열림
        w2 = W.World("2026-09-01", "2026-09-30", "2026-09-30T18:00")
        w2.unit("u_h", start=("2026-08-03", "09:00"), title="보류")
        w2.unit("u_d", start=("2026-09-01", "09:00"), end=("2026-09-01", "17:00"), title="완료")
        w2.run("u_d", "DOC_DOC", "2026-09-01", "10:00", "11:00")
        rv2, _p = reviews(w2.context())
        self.assertEqual([f[1] for f in rv2["months"][0]["facts"]], ["완료", "보류"])

    def test_scrub(self):
        self.assertEqual(R.scrub_time("결과 검토 3시간 회의 2.5h · 30분"), "결과 검토 회의 ·")
        self.assertEqual(R.scrub_time("양산 2차 검토"), "양산 2차 검토")


if __name__ == "__main__":
    unittest.main()
