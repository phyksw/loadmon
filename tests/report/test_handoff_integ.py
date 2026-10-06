# -*- coding: utf-8 -*-
"""통합 단계 — 묶음 사이 handoff 회귀(W2 검토 수정 통합).

- L04(분류 묶음 → 보고서): 로컬 Agentic 카탈로그(config\\agentic_tasks.json — 계약 v1.3 §0.8 V13)를 못 쓴 까닭(hier_meta.warnings 의
  ``local_catalog_*``)을 '팀 레지스트리를 받으면 채워집니다' 대신 그대로 알린다 — 모델 flags.warnings·agentic.catalog_note.
- C08(분류 묶음 → 보고서): 시간 코어 업무 표지(``SELF:…@MM-DD``·``MANUAL:t:…``·``APP:…``)·로컬 키는 단위업무 제목이 되지 않고,
  가림판 안전 제목 판정(``Resolver.title_safe``)도 표지를 막는다.
"""
from __future__ import annotations

import copy
import unittest

from lm27.hier.registry import LOCAL_CATALOG_WARNS
from lm27.report import model as M
from lm27.report.analysis import activity as A
from lm27.report.resolve import Resolver
from tests.fixtures.wp30 import world as W
from tests.fixtures.wp31 import runs as R


def no_fallback(*_a):
    return None


class LocalCatalogNoteTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.t = R.TmpRoot()
        cls.addClassCleanup(cls.t.cleanup)
        cls.srun = R.golden_run()
        cls.srun.write(cls.t.paths)
        cls.cfg = W.cfg()

    def build(self, warnings, *, agents=True):
        reg = copy.deepcopy(R.REGISTRY)
        if not agents:
            reg["agents"] = []
        inp = self.srun.inputs(self.t.paths, self.cfg, registry=reg)
        inp.hier = {**inp.hier, "meta": {**inp.hier["meta"], "warnings": list(warnings)}}
        return M.build_model(inp, self.cfg, fallback=no_fallback)

    def warn(self, m, code):
        return next((w for w in m["flags"]["warnings"] if w["code"] == code), None)

    def test_empty_catalog_explains_local_file_problem(self):
        m = self.build(["local_catalog_rejected:encoding", "server_unreachable:OSError"], agents=False)
        txt = LOCAL_CATALOG_WARNS["local_catalog_rejected:encoding"]
        w = self.warn(m, "catalog_empty")
        self.assertIsNotNone(w)
        self.assertEqual(w["text_ko"], "에이전트 목록이 없습니다 — " + txt)
        self.assertNotIn("팀 레지스트리를 받으면", w["text_ko"])
        self.assertEqual(m["agentic"]["catalog_note"], txt)
        self.assertIsNone(self.warn(m, "local_catalog"))

    def test_used_catalog_with_warning_gets_own_line(self):
        m = self.build(["local_catalog_cp949", "local_catalog_dup_id", "local_catalog_cp949"])
        want = " · ".join([LOCAL_CATALOG_WARNS["local_catalog_cp949"], LOCAL_CATALOG_WARNS["local_catalog_dup_id"]])
        self.assertEqual(self.warn(m, "local_catalog")["text_ko"], want)
        self.assertEqual(m["agentic"]["catalog_note"], want)
        self.assertIsNone(self.warn(m, "catalog_empty"))

    def test_no_local_warning_keeps_model_shape(self):
        m = self.build([])
        self.assertNotIn("catalog_note", m["agentic"])
        self.assertIsNone(self.warn(m, "local_catalog"))
        m2 = self.build([], agents=False)
        self.assertIn("팀 레지스트리를 받으면", self.warn(m2, "catalog_empty")["text_ko"])

    def test_notes_helper(self):
        self.assertEqual(M.local_catalog_notes({"warnings": ["x", 3, "local_catalog_rejected"]}),
                         [LOCAL_CATALOG_WARNS["local_catalog_rejected"]])
        self.assertEqual(M.local_catalog_notes(None), [])


class MarkerTitleTest(unittest.TestCase):
    def test_marker_fallback_title_not_shown(self):
        for label in ("SELF:rbabeca6f59162ae7@09", "MANUAL:t:1e9f7be2940441f0", "APP:ansys_mechanical@09-0",
                      "u_3fa2b1c4d5e6f708", ""):
            lf = A._label_fields(None, "u_x", label)
            self.assertEqual(lf["title"], A.GENERIC_UNIT_TITLE, label)
            lf2 = A._label_fields({"project": None, "title": label, "title_src": "rule_generic"}, "u_x", label)
            self.assertEqual(lf2["title"], A.GENERIC_UNIT_TITLE, label)       # 예전 분류 결과의 표지 제목도
        self.assertEqual(A._label_fields(None, "u_x", "회의록 정리")["title"], "회의록 정리")
        lf3 = A._label_fields({"title": "해석 보고서", "title_src": "rule_doc"}, "u_x", "SELF:rbabeca6f59162ae7@09")
        self.assertEqual(lf3["title"], "해석 보고서")

    def test_redacted_title_safe_rejects_markers(self):
        r = Resolver("redacted", {"people": {}}, None, None)
        self.assertFalse(r.title_safe("MANUAL:t:1e9f7be2940441f0"))
        self.assertFalse(r.title_safe("APP:ansys_mechanical@09-0"))
        self.assertEqual(r.unit_title("SELF:rbabeca6f59162ae7@09", "단위업무"), "단위업무")
        self.assertTrue(r.title_safe("해석 보고서 작성"))


if __name__ == "__main__":
    unittest.main()
