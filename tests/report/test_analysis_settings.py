# -*- coding: utf-8 -*-
"""WP-30 설정 read-check · 섭동(R G-R9 · 계약 T-14 · L-12).

- 분석층이 소유한 `report.mining.*` · `report.review.*` · `report.peers.*` · `report.ontology.*` · `report.agentic.*` ·
  `report.subagent.*` · `report.quality.*` 키는 분석 한 번에 **전부 읽히고**(`Cfg.used()`), 키마다 값을 바꾸면 결과 바이트가
  바뀐다(죽은 키·무시되는 키 없음). 섭동 값은 레지스트리 범위 안(범위 밖이면 기본값으로 돌아가 시험이 무의미해진다).
"""
from __future__ import annotations

import unittest

from lm27.report.analysis import analyze
from lm27.util.fsx import canon_bytes
from tests.fixtures.wp30 import world as W

OWNED_PREFIX = ("report.mining.", "report.review.", "report.peers.", "report.ontology.", "report.agentic.",
                "report.subagent.", "report.quality.")
PERTURB = {
    "report.mining.minStepSec": 0, "report.mining.maxSteps": 3, "report.mining.minSupportRatio": 0.9,
    "report.mining.maxEdges": 2, "report.mining.waitBottleneckMin": 100000, "report.mining.workBottleneckShare": 0.9,
    "report.mining.minUnitsForBottleneck": 10, "report.mining.handoffWd": 0,
    "report.mining.extClassExtra": {"abc": "xls"},
    "report.review.leadOverrunRatio": 2.0, "report.review.baselineMonths": 1, "report.review.baselineMinUnits": 5,
    "report.review.lateStartWd": 1, "report.review.parallelHigh": 2.0, "report.review.scopeRatio": 1.0,
    "report.review.maxFacts": 1,
    "report.peers.minMsgs": 3, "report.peers.maxMeetingSize": 5, "report.peers.topN": 1,
    "report.ontology.weights": {"doc": 1.0, "peer": 0.0, "app": 0.0, "seq": 0.0}, "report.ontology.minRel": 0.9,
    "report.ontology.sameWorkRel": 0.1, "report.ontology.appMinMin": 300, "report.ontology.topN": 1,
    "report.ontology.maxUnits": 1,
    "report.agentic.gradeHigh": 0.5, "report.agentic.gradeMid": 0.6,
    "report.subagent.fitScore": 9, "report.subagent.condScore": 9, "report.subagent.roleFitShare": 0.1,
    "report.quality.covLow": 0.5, "report.quality.covBad": 0.9, "report.quality.estLow": 0.01,
    "report.quality.estBad": 0.01, "report.quality.unattrHigh": 0.0, "report.quality.noEvidenceDays": 40,
    "report.quality.samplerLow": 0.0,
}


def run(c):
    return canon_bytes(analyze(W.rich_context(c)))


class SettingsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = W.cfg()
        cls.base = run(cls.cfg)
        cls.owned = sorted(k for k in cls.cfg.keys() if k.startswith(OWNED_PREFIX))

    def test_all_owned_keys_read(self):
        self.assertGreaterEqual(len(self.owned), 37)
        used = set(self.cfg.used())
        self.assertEqual([k for k in self.owned if k not in used], [])
        self.assertEqual(sorted(PERTURB), self.owned, "섭동 표 = 소유 키 전부")

    def test_perturbation_changes_result(self):
        same = []
        for k, v in sorted(PERTURB.items()):
            c = W.cfg(**{k: v})
            self.assertEqual(c.config_warnings, [], k)                    # 범위 안 값이어야 한다
            self.assertEqual(c[k], v, k)
            if run(c) == self.base:
                same.append(k)
        self.assertEqual(same, [], "섭동해도 결과가 같은 키")

    def test_owner_metadata(self):
        """레지스트리 owner = 분석층 모듈(L-12 단계 적용 기준)."""
        for k in self.owned:
            owner = self.cfg.meta(k).owner
            self.assertTrue(str(owner).startswith("lm27.report.analysis."), (k, owner))


if __name__ == "__main__":
    unittest.main()
