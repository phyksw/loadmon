# -*- coding: utf-8 -*-
"""WP-31 폴백 한 벌(R §4.10.3 · RPT-29 · G-R12): ai_out 이 없으면 보고서 모델의 라벨·문장은 **브리지 단계 정의의 `fallback()`
결과 그대로**(by = rule)이고, 보고서 쪽에 같은 규칙 문장을 다시 두지 않는다. 모델은 폴백 답을 바꾸지 않고 싣는다."""
from __future__ import annotations

import importlib
import unittest

from lm27.report import model as M
from tests.fixtures.wp30 import world as W
from tests.fixtures.wp31 import runs as R


def fake_fallback(stage, item, ns):
    """브리지 단계 폴백 흉내 — 입력 항목만 보고 답을 만든다(세션·파일 없음)."""
    f = item.get("fields") or {}
    if stage == "workflow_label":
        return {"role": "규칙 역할", "summary": "규칙 요약",
                "steps": [{"s": s[0], "type": s[1], "label": f"규칙 {s[1]}", "desc": ""} for s in f.get("steps", ())]}
    if stage == "review_text":
        return {"summary": f"{f.get('kind')} 규칙 요약", "highlights": [], "relations": [], "next": []}
    if stage == "subagent_review":
        return {"verdict": "부분", "orch": "", "subs": [], "risk": ""}
    if stage == "agentic_match":
        return {"m": [], "need": None}
    return None


class FallbackTest(unittest.TestCase):
    def build(self, fallback):
        t = R.TmpRoot()
        self.addCleanup(t.cleanup)
        srun = R.rich_run()
        srun.write(t.paths)
        cfg = W.cfg()
        return M.build_model(srun.inputs(t.paths, cfg), cfg, fallback=fallback)

    def test_labels_are_fallback_answers(self):
        m = self.build(fake_fallback)
        for rw in m["workflows"]["roles"].values():
            self.assertEqual(rw["ai_role"], "규칙 역할")
            for s in rw["steps"]:
                self.assertEqual((s["label"], s["label_by"]), (f"규칙 {s['code']}", "rule"))
        months = [r for r in m["reviews"]["months"] if r.get("ai")]
        self.assertTrue(months)
        self.assertTrue(all(r["ai"]["summary"] == "month 규칙 요약" and r["ai"]["by"] == "rule" for r in months))
        self.assertEqual(m["flags"]["copilot"], "rule_only")
        self.assertNotIn("fallback_unavailable", {w["code"] for w in m["flags"]["warnings"]})
        for r in m["subagent"]["roles"]:
            self.assertEqual(r["final"], r["rule"])                       # 규칙 답(by=rule)은 최종 판정을 바꾸지 않는다

    def test_no_fallback_marks_warning(self):
        m = self.build(lambda *_a: None)
        self.assertIn("fallback_unavailable", {w["code"] for w in m["flags"]["warnings"]})
        for rw in m["workflows"]["roles"].values():
            self.assertTrue(all(s["label_by"] == "rule" for s in rw["steps"]))

    def test_real_bridge_registry_when_present(self):
        """브리지 단계 REGISTRY 가 트리에 온전히 있으면 그 fallback 한 벌로 끝까지 만든다(없으면 건너뜀 — WP-25 통합 창)."""
        try:
            reg = importlib.import_module("lm27.bridge.stages").REGISTRY
        except (ImportError, AttributeError) as e:                       # 시험 건너뜀 사유로만 쓴다(기능을 삼키지 않음)
            self.skipTest(f"브리지 단계 REGISTRY 없음({type(e).__name__}) — WP-25 통합 뒤 실물 확인")
        if not all(st in reg for st in ("workflow_label", "review_text", "agentic_match", "subagent_review")):
            self.skipTest("브리지 단계 4종이 아직 REGISTRY 에 없다")
        m = self.build(None)
        self.assertEqual(m["flags"]["copilot"], "rule_only")
        self.assertEqual(M.check_model(m), [])


if __name__ == "__main__":
    unittest.main()
