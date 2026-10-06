# -*- coding: utf-8 -*-
"""WP-30 보고서 분석층 골든(R 부록 B 시제품 `golden_report.json` — `lint.ps1 -Stage golden` 이 도는 이름 test_golden*.py).

시제품(`design\\reports\\proto_report.py`, 동봉 파이썬 3.11.9)이 계산한 골든 원본의 사본(`tests\\fixtures\\wp30\\golden_report.json`)과
분석층 결과를 대조한다: RPT-11(표시 함수 골든) · RPT-14(영업 분) · RPT-15(과정 마이닝 — 합성 시간 결과 파일로) ·
RPT-20(리드 초과 원인) · RPT-22(연관도) · RPT-23(서브에이전트 5기준).
"""
from __future__ import annotations

import json
import os
import unittest
from datetime import date

from lm27.report import fmt as F
from lm27.report.analysis import mining, ontology, review, subagent
from tests.fixtures.wp30 import world as W


def golden():
    with open(os.path.join(W.ROOT, "tests", "fixtures", "wp30", "golden_report.json"), encoding="utf-8") as f:
        return json.load(f)


class GoldenAnalysisTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.g = golden()
        cls.cfg = W.cfg()
        cls.bc = F.BizCal(W.calendar())

    def test_rpt11_fmt(self):
        g = self.g["fmt"]
        self.assertEqual({m: F.fmt_h1(int(m)) for m in g["h1"]}, g["h1"])
        self.assertEqual({k: F.fmt_ratio(*map(int, k.split("/")), 2) for k in g["mm2"]}, g["mm2"])
        self.assertEqual({k: F.fmt_pct(*map(int, k.split("/"))) for k in g["pct0"]}, g["pct0"])

    def test_rpt14_biz_min(self):
        g = self.g["biz_min_examples"]
        self.assertEqual(self.bc.biz_min(W.lmin("2026-09-04", "16:00"), W.lmin("2026-09-07", "10:00")),
                         g["0904_1600_to_0907_1000"])
        self.assertEqual(self.bc.biz_min(W.lmin("2026-09-23", "17:00"), W.lmin("2026-09-28", "09:00")),
                         g["0923_1700_to_0928_0900"])
        self.assertEqual(self.bc.biz_min(W.lmin("2026-09-22", "12:00"), W.lmin("2026-09-30", "13:00")),
                         g["0922_1200_to_0930_1300"])

    def test_rpt15_mining(self):
        g = self.g["mine_role_A"]
        ctx = W.golden_role_a().context()
        rw = mining.mine_role(list(ctx.units.values()), ctx.log, ctx.cfg, bc=ctx.bc, as_of_min=ctx.as_of_min)
        self.assertEqual([(s["no"], s["code"], s["n"], s["median_min"], s["wait_in_median_min"], s["work_share"])
                          for s in rw["steps"]],
                         [(s["no"], s["type"], s["n"], s["median_min"], s["wait_in_median_min"], s.get("work_share"))
                          for s in g["steps"]])
        self.assertEqual((rw["edges"], rw["rework"], rw["bottlenecks"], rw["traces"], rw["support_threshold"]),
                         (g["edges"], g["rework_edges"], g["bottlenecks"], g["traces"], g["support_threshold"]))
        self.assertEqual([d["code"] for d in rw["dropped"]], g["dropped"])

    def test_rpt20_overrun(self):
        for key, e0 in (("overrun_u_a4", 420), ("overrun_u_a5", 210)):
            o = self.g[key]
            r = review.overrun_causes(o["unit"], (o["baseline_biz_lead_min"], e0), self.cfg)
            self.assertEqual({"overrun": r["overrun"], "causes": r["causes"]}, o["result"], key)
        ctx = W.golden_role_a().context()
        self.assertEqual(review.baseline_of(ctx.units["u_a4"], ctx.units.values(), ctx.cfg)[0],
                         self.g["overrun_u_a4"]["baseline_biz_lead_min"])

    def test_rpt22_relatedness(self):
        u = {
            "u_a1": {"docs": {"f1", "f2"}, "peers": {"w1"}, "apps": {"cae", "excel"}, "role": "rA",
                     "start_d": date(2026, 9, 1), "end_d": date(2026, 9, 4)},
            "u_a2": {"docs": {"f2", "f3"}, "peers": {"w1", "w2"}, "apps": {"cae", "excel"}, "role": "rA",
                     "start_d": date(2026, 9, 7), "end_d": date(2026, 9, 16)},
            "u_b1": {"docs": {"f3"}, "peers": {"w2"}, "apps": {"eda"}, "role": "rB",
                     "start_d": date(2026, 9, 17), "end_d": date(2026, 9, 22)},
            "u_c1": {"docs": {"f9"}, "peers": {"w7"}, "apps": {"word"}, "role": "rC",
                     "start_d": date(2026, 9, 1), "end_d": date(2026, 9, 30)},
        }
        for pair, exp in self.g["relatedness"].items():
            a, b = pair.split("~")
            self.assertEqual(list(ontology.relatedness(u[a], u[b], self.cfg, bc=self.bc)), exp, pair)

    def test_rpt23_subagent(self):
        stats = [
            {"type": "APP_CAE", "weeks_active": 5, "occ": 7, "digital_share": 1.0, "structured_share": 0.2,
             "tool_class_min": {1: 900, 2: 30}, "rework_rate": 0.25, "external_share": 0.0, "money_hit": False},
            {"type": "DOC_XLS", "weeks_active": 5, "occ": 5, "digital_share": 1.0, "structured_share": 0.9,
             "tool_class_min": {2: 480}, "rework_rate": 0.25, "external_share": 0.0, "money_hit": False},
            {"type": "MEET", "weeks_active": 5, "occ": 2, "digital_share": 0.0, "structured_share": 0.0,
             "tool_class_min": {0: 120}, "rework_rate": 0.0, "external_share": 0.0, "money_hit": False},
            {"type": "REPORT_OUT", "weeks_active": 5, "occ": 4, "digital_share": 1.0, "structured_share": 0.5,
             "tool_class_min": {2: 60}, "rework_rate": 0.25, "external_share": 0.5, "money_hit": False},
            {"type": "REQ_IN", "weeks_active": 5, "occ": 4, "digital_share": 1.0, "structured_share": 0.0,
             "tool_class_min": {2: 0}, "rework_rate": 0.25, "external_share": 0.0, "money_hit": False},
        ]
        rows = [subagent.subagent_step(s, self.cfg) for s in stats]
        keys = ("type", "REP", "IO", "TOOL", "VER", "RISK", "score", "verdict", "flags", "why")
        self.assertEqual([{k: r[k] for k in keys} for r in rows],
                         [{k: r[k] for k in keys} for r in self.g["subagent_rows"]])
        rule, _share = subagent.role_verdict(rows, {"APP_CAE": 900, "DOC_XLS": 480, "MEET": 120}, self.cfg)
        exp = self.g["subagent_role"]
        self.assertEqual({"rule": rule, "final_if_ai_적합": subagent.final_verdict(rule, "적합"),
                          "final_if_ai_부분": subagent.final_verdict(rule, "부분"),
                          "final_if_ai_부적합": subagent.final_verdict(rule, "부적합")}, exp)


if __name__ == "__main__":
    unittest.main()
