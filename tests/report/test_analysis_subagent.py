# -*- coding: utf-8 -*-
"""WP-30 서브에이전트 5기준(R §4.8 · RPT-23 · D-19 원장 수치 판정).

- RPT-23: R §4.8.4 골든 — 단계 판정 5개(조건부 · 적합 · 부적합 · 부적합 · 조건부), 역할 규칙 '조건부'(적합 분 비율 0.32),
  AI '적합' → 최종 조건부, '부분' → 조건부, '부적합' → 부적합.
- 단계 통계는 흔적(L3·L4 = 디지털, 정형 확장자군·반복 양식, 앱 분류 도구 점수, 되돌림)에서 계산한다.
- 코파일럿 구성안의 S 코드는 현재 단계 번호로, 규칙상 부적합 단계는 '사람 확인 필요'(지우지 않음).
"""
from __future__ import annotations

import json
import os
import unittest

from lm27.report.analysis import analyze
from lm27.report.analysis import subagent as SA
from tests.fixtures.wp30 import world as W

STATS = [
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


def golden():
    with open(os.path.join(W.ROOT, "tests", "fixtures", "wp30", "golden_report.json"), encoding="utf-8") as f:
        return json.load(f)


class GoldenTest(unittest.TestCase):
    def test_rpt23(self):
        g = golden()
        cfg = W.cfg()
        rows = [SA.subagent_step(s, cfg) for s in STATS]
        for r, gr in zip(rows, g["subagent_rows"], strict=True):
            for k in ("type", "REP", "IO", "TOOL", "VER", "RISK", "score", "verdict", "flags", "why"):
                self.assertEqual(r[k], gr[k], (r["type"], k))
        rule, share = SA.role_verdict(rows, {"APP_CAE": 900, "DOC_XLS": 480, "MEET": 120}, cfg)
        self.assertEqual((rule, share), ("조건부", 0.32))
        role = g["subagent_role"]
        self.assertEqual(rule, role["rule"])
        self.assertEqual(SA.final_verdict(rule, "적합"), role["final_if_ai_적합"])
        self.assertEqual(SA.final_verdict(rule, "부분"), role["final_if_ai_부분"])
        self.assertEqual(SA.final_verdict(rule, "부적합"), role["final_if_ai_부적합"])
        self.assertEqual(SA.final_verdict("부적합", "적합"), "부적합")       # 코파일럿이 하드 조건을 넘지 못한다
        self.assertEqual(SA.final_verdict("적합", None), "적합")
        self.assertEqual(SA.final_verdict("적합", "모름"), "적합")
        self.assertEqual(SA.flags_text(rows[1]["flags"]), "D1 R1 B1 L1 S1 T1")

    def test_thresholds(self):
        cfg = W.cfg(**{"report.subagent.fitScore": 8, "report.subagent.condScore": 9,
                       "report.subagent.roleFitShare": 0.3})
        rows = [SA.subagent_step(s, cfg) for s in STATS]
        self.assertEqual([r["verdict"] for r in rows], ["부적합", "적합", "부적합", "부적합", "부적합"])
        self.assertEqual(SA.role_verdict(rows, {"APP_CAE": 900, "DOC_XLS": 480, "MEET": 120}, cfg)[0], "적합")
        reg = {"vocab": {"step_types": [{"code": "APP_CAE", "tool_access": 2, "verifiable": 2}]}}
        cae = dict(STATS[0], tool_class_min={})
        self.assertEqual(SA.subagent_step(cae, W.cfg(), reg)["TOOL"], 2)          # 레지스트리 덮어쓰기


class LayerTest(unittest.TestCase):
    def test_stats_from_world(self):
        sec = analyze(W.golden_role_a().context())
        role = sec["subagent"]["roles"][0]
        st = {r["code"]: r for r in role["steps"]}
        self.assertEqual(st["APP_CAE"]["stats"]["weeks_active"], 5)
        self.assertEqual(st["APP_CAE"]["stats"]["occ"], 5)
        self.assertEqual(st["APP_CAE"]["stats"]["digital_share"], 1.0)
        self.assertEqual(st["MEET"]["stats"]["digital_share"], 0.0)             # L2 회의는 디지털 아님
        self.assertEqual(st["DOC_XLS"]["stats"]["structured_share"], 1.0)       # 표 계산 문서 = 정형
        self.assertEqual(st["APP_CAE"]["stats"]["rework_rate"], 0.25)           # u_a2 의 표 계산 → 해석 되돌림
        self.assertEqual(st["APP_CAE"]["TOOL"], 1)
        self.assertEqual(st["DOC_XLS"]["rule"], "적합")
        self.assertEqual(st["MEET"]["rule"], "부적합")
        self.assertIsNone(role["ai"])
        self.assertEqual(role["final"], role["rule"])
        self.assertTrue(role["chain"])
        self.assertTrue(all(c["proposal"].endswith("단계 보조") for c in role["chain"]))
        steps = {s["code"]: s for rw in sec["workflows"]["roles"].values() for s in rw["steps"]}
        self.assertEqual(steps["DOC_XLS"]["subagent"], "적합")
        self.assertIn("tool_access", steps["DOC_XLS"]["why"])

    def test_ai_opinion(self):
        ctx = W.golden_role_a().context()
        rid = W.role_id("P-0007", "ELEC", "ANALYSIS")
        ans = {"verdict": "적합", "orch": "해석 흐름 조율",
               "subs": [{"steps": ["S3", "S4"], "role": "결과 정리 서브에이전트", "io": "해석 결과→표", "check": "표 확인"},
                        {"steps": ["S9"], "role": "없는 단계", "io": "", "check": ""}], "risk": "외부 보고 주의"}
        ctx.ai = {"subagent_review": {"sa:" + rid: {"ans": ans, "by": "ai"}}}
        sec = analyze(ctx)
        role = sec["subagent"]["roles"][0]
        self.assertEqual(role["ai"]["verdict"], "적합")
        self.assertEqual(role["final"], "조건부")                                # 규칙이 더 보수적
        self.assertEqual(len(role["ai"]["subs"]), 1)                             # 낯선 S 코드 sub 는 버림
        self.assertEqual(role["ai"]["subs"][0]["steps"], [3, 4])
        self.assertEqual(role["ai"]["subs"][0]["human_check"], [4])              # S4 회의 = 규칙상 부적합
        self.assertEqual(role["chain"], [{"step_no": 3, "proposal": "결과 정리 서브에이전트"},
                                         {"step_no": 4, "proposal": "결과 정리 서브에이전트"}])
        st = {r["code"]: r for r in role["steps"]}
        self.assertEqual((st["DOC_XLS"]["rule"], st["DOC_XLS"]["final"]), ("적합", "적합"))
        self.assertEqual(st["MEET"]["final"], "부적합")
        self.assertEqual(sec["flags"]["label_sources"]["subagent_review"], {"ai": 1, "manual": 0, "rule": 0})
        ctx.ai = {"subagent_review": {"sa:" + rid: {"ans": dict(ans, verdict="부분"), "by": "manual"}}}
        role = analyze(ctx)["subagent"]["roles"][0]
        self.assertEqual(role["final"], "조건부")
        self.assertEqual({r["final"] for r in role["steps"] if r["rule"] == "적합"}, {"조건부"})


if __name__ == "__main__":
    unittest.main()
