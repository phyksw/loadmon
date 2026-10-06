# -*- coding: utf-8 -*-
"""WP-30 Agentic 매칭과 새 니즈(R §4.7 · RPT-24 · D-19).

- RPT-24: 카탈로그 3개(단계 유형 일치 · 불일치 · 핵심어만) → 규칙 등급 중 · 없음 · 하, AI 가 '상' 준 불일치 칸에 disagree,
  규칙 니즈 1건(주 1~2회 · D = 1 · 서브에이전트 조건부 이상 · 등급 ≥ 중 매칭 없음), 카탈로그 이름과 같은 니즈는 버림,
  need_id 는 재분석해도 같다.
- 관련 투입은 실측 Run 분(점 단계 0), 사람 합계는 단계 유형마다 한 번만.
"""
from __future__ import annotations

import hashlib
import unittest

from lm27.hier.names import ukey
from lm27.report.analysis import agentic as G
from lm27.report.analysis import analyze
from tests.fixtures.wp30 import world as W

AGENTS = [
    {"id": "AG01", "name": "표 정리 도우미", "step_types": ["DOC_XLS"], "inputs": ["회의록"], "outputs": ["음성 요약"],
     "keywords": []},
    {"id": "AG02", "name": "발표 자료 도우미", "step_types": ["DOC_PPT"], "inputs": ["음성"], "outputs": ["영상"],
     "keywords": []},
    {"id": "AG03", "name": "전원 검토 도우미", "step_types": [], "inputs": [], "outputs": [], "keywords": ["전원부"]},
]


def run(agents=AGENTS, ai=None):
    ctx = W.golden_role_a().context(registry={"agents": agents, "catalog_version": "ag-3"}, ai=ai or {})
    return analyze(ctx), ctx


class RuleScoreTest(unittest.TestCase):
    def test_score_parts(self):
        item = {"type": "DOC_XLS", "inputs": ["디지털", "사무"], "outputs": ["표 계산", "표 계산 문서"],
                "titles": ["전원부 해석 1"]}
        self.assertEqual(G.rule_score(AGENTS[0], item), 0.5)
        self.assertEqual(G.rule_score(AGENTS[1], item), 0.0)
        self.assertEqual(G.rule_score(AGENTS[2], item), 0.1)
        full = {"id": "AGX", "step_types": ["DOC_XLS"], "inputs": ["사무 디지털"], "outputs": ["표 계산"],
                "keywords": ["해석"]}
        self.assertEqual(G.rule_score(full, item), 1.0)
        self.assertEqual(G.rule_why(full, item), ["type", "input", "output", "keyword"])
        cfg = W.cfg()
        self.assertEqual([G.rule_grade(s, cfg) for s in (1.0, 0.8, 0.7, 0.5, 0.1, 0.0)],
                         ["상", "상", "중", "중", "하", ""])
        self.assertEqual(G.freq_of(15, 5)[0], "주 3회 이상")
        self.assertEqual(G.freq_of(5, 5)[0], "주 1~2회")
        self.assertEqual(G.freq_of(1, 4)[0], "월 몇 회")
        self.assertEqual(G.freq_of(1, 5)[0], "드묾")


class RPT24Test(unittest.TestCase):
    def test_rule_grades(self):
        sec, _ctx = run()
        ag = sec["agentic"]
        m = {(x["agent_id"], x["step_type"]): x for x in ag["matches"]}
        self.assertEqual(m[("AG01", "DOC_XLS")]["grade"], "중")
        self.assertNotIn(("AG02", "DOC_XLS"), m)
        self.assertEqual(m[("AG03", "DOC_XLS")]["grade"], "하")
        self.assertEqual(m[("AG03", "DOC_XLS")]["why_rule"], ["keyword"])
        self.assertTrue(all(x["by"] == "rule" and not x["disagree"] for x in ag["matches"]))
        self.assertEqual(ag["catalog_n"], 3)
        self.assertEqual(ag["catalog_version"], "ag-3")
        steps = {s["code"]: s for rw in sec["workflows"]["roles"].values() for s in rw["steps"]}
        self.assertEqual(steps["DOC_XLS"]["agent_grade"], "중")
        self.assertEqual(steps["MEET"]["agent_grade"], "하")                  # 핵심어 일치는 모든 단계 유형에 걸린다
        it = {x["type"]: x for x in ag["items"]}
        self.assertEqual(it["DOC_XLS"]["freq"], "주 1~2회")
        self.assertEqual(it["DOC_XLS"]["related_min"], 480)
        self.assertEqual(it["REQ_IN"]["related_min"], 0)
        self.assertEqual(it["DOC_XLS"]["ws"], ["P-0007 해석·분석"])

    def test_ai_disagree(self):
        ai = {"agentic_match": {"items": {"ag:DOC_XLS": {"ans": {"m": [{"a": "AG02", "fit": "상", "why": "표 작성"}],
                                                                  "need": None}, "by": "ai"}}}}
        sec, _ctx = run(ai=ai)
        m = {(x["agent_id"], x["step_type"]): x for x in sec["agentic"]["matches"]}
        x = m[("AG02", "DOC_XLS")]
        self.assertEqual((x["grade"], x["by"], x["rule_grade"], x["disagree"]), ("상", "ai", "", True))
        self.assertEqual(x["why_ai"], "표 작성")
        y = m[("AG01", "DOC_XLS")]                                            # AI 가 고르지 않음 = 없음, 규칙 중 → 다름
        self.assertEqual((y["grade"], y["disagree"]), ("", True))
        self.assertNotIn(("AG03", "DOC_XLS"), m)                            # 하 ↔ 없음 은 1단계 차이 — 행 없음

    def test_rule_answer_is_not_ai(self):
        """ai_out 의 규칙 답(by rule — 브리지 폴백 접기)은 코파일럿 의견이 아니다 → 규칙 사전 점수 등급 그대로."""
        ai = {"agentic_match": {"items": {"ag:DOC_XLS": {"ans": {"m": [{"a": "AG02", "fit": "상", "why": "x"}],
                                                                  "need": None}, "by": "rule"}}}}
        sec, _ctx = run(ai=ai)
        m = {(x["agent_id"], x["step_type"]): x for x in sec["agentic"]["matches"]}
        self.assertEqual(m[("AG01", "DOC_XLS")]["grade"], "중")
        self.assertNotIn(("AG02", "DOC_XLS"), m)
        self.assertTrue(all(x["by"] == "rule" for x in m.values()))

    def test_needs(self):
        sec, _ctx = run()
        needs = sec["agentic"]["needs"]
        self.assertEqual([(n["step_type"], n["name"], n["by"]) for n in needs],
                         [("APP_CAE", "해석 프로그램 자동화", "rule")])
        n = needs[0]
        exp = "n_" + hashlib.sha1(("APP_CAE|" + ukey("해석 프로그램 자동화")).encode()).hexdigest()[:6]
        self.assertEqual(n["need_id"], exp)
        self.assertEqual(n["grade"], "중")
        self.assertEqual(n["freq_per_month"], 4.3)                            # occ_week 1.0 × 4.345
        sec2, _ctx = run()
        self.assertEqual(sec2["agentic"]["needs"][0]["need_id"], exp)        # 재분석해도 같은 ID
        dup = AGENTS + [{"id": "AG04", "name": "해석 프로그램 자동화", "step_types": [], "inputs": [], "outputs": [],
                         "keywords": []}]
        sec3, _ctx = run(agents=dup)
        self.assertEqual(sec3["agentic"]["needs"], [])                        # 카탈로그 이름과 같은 니즈는 버림
        ai = {"agentic_match": {"items": {"ag:MEET": {"ans": {"m": [], "need": {
            "name": "회의록 정리", "logic": "회의 녹취를 받아 요약", "in": "녹취", "out": "요약"}}, "by": "manual"}}}}
        sec4, _ctx = run(ai=ai)
        by = {n["name"]: n for n in sec4["agentic"]["needs"]}
        self.assertEqual(by["회의록 정리"]["by"], "manual")
        self.assertEqual(by["회의록 정리"]["grade"], "하")                      # MEET 빈도 '월 몇 회'

    def test_team_matches_and_totals(self):
        sec, _ctx = run()
        tm = sec["team"]["agentic_matches"]
        self.assertTrue(all(set(x) == {"agent_id", "role_id", "step_type", "grade", "units"} for x in tm))
        self.assertIn({"agent_id": "AG01", "role_id": W.role_id("P-0007", "ELEC", "ANALYSIS"),
                       "step_type": "DOC_XLS", "grade": "중", "units": ["u_a1", "u_a2", "u_a3", "u_a4"]}, tm)
        ag = sec["agentic"]
        self.assertEqual(ag["related_min_total"], sum(i["related_min"] for i in ag["items"]
                                                      if any(m["step_type"] == i["type"] and m["grade"]
                                                             for m in ag["matches"])))

    def test_empty_catalog(self):
        sec, _ctx = run(agents=[])
        self.assertEqual(sec["agentic"]["matches"], [])
        self.assertIn("catalog_empty", [w["code"] for w in sec["flags"]["warnings"]])
        self.assertEqual(len(sec["agentic"]["needs"]), 2)                    # 매칭이 없으니 APP_CAE·DOC_XLS 니즈


if __name__ == "__main__":
    unittest.main()
