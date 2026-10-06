# -*- coding: utf-8 -*-
"""WP-32 단계 표 — 계약 §8.5 분석 단계 id 10종·순서·이름(R §5.3.2)·의존, 재분석 선택 계획(plan_run)."""
import unittest

from lm27.pipeline import stages as S

CONTRACT_IDS = ("load", "normalize", "classify", "ai:task_label", "time", "mining", "ai:workflow", "review",
                "ai:review_text", "report")
R_NAMES = {"load": "기록 읽기", "normalize": "정리·병합", "classify": "분류(규칙)", "ai:task_label": "AI 업무 이름·분류",
           "time": "근무시간·단위업무", "mining": "워크플로우 계산", "ai:workflow": "AI 단계 이름·매칭·검토",
           "review": "리뷰 사실", "ai:review_text": "AI 리뷰 문장", "report": "보고서 만들기"}


class TableTest(unittest.TestCase):
    def test_ids_order_names(self):
        self.assertEqual(S.STAGE_IDS, CONTRACT_IDS, "계약 §8.5 분석 단계 id·순서")
        self.assertEqual({s.id: s.name_ko for s in S.STAGES}, R_NAMES, "R §5.3.2 단계 이름")
        self.assertEqual(S.AI_STAGES, ("ai:task_label", "ai:workflow", "ai:review_text"))
        self.assertEqual(S.CHAIN, ("load", "normalize", "classify", "time"))
        self.assertEqual(S.QUICK_RERUN, ("classify", "time", "mining", "report"))

    def test_needs_point_backwards(self):
        seen = set()
        for s in S.STAGES:
            for n in s.needs:
                self.assertIn(n, seen, f"{s.id} 의 의존 {n} 이 앞에 있어야 한다")
            seen.add(s.id)
            self.assertTrue(S.STAGE_RX.match(s.id))

    def test_bridge_call_points(self):
        """B §2.3 호출 지점 2~5: speech_act(정규화 안) · task_label · 워크플로우 3단계 · review_text."""
        self.assertEqual(S.get("normalize").bridge, ("speech_act",))
        self.assertFalse(S.get("normalize").ai, "speech_act 는 정규화 안의 선택적 AI 보조 단계")
        self.assertEqual(S.get("ai:task_label").bridge, ("task_label",))
        self.assertEqual(S.get("ai:workflow").bridge, ("workflow_label", "agentic_match", "subagent_review"))
        self.assertEqual(S.get("ai:review_text").bridge, ("review_text",))
        from lm27.bridge.stages import STAGE_IDS as BRIDGE_IDS
        for s in S.STAGES:
            for b in s.bridge:
                self.assertIn(b, BRIDGE_IDS)

    def test_check_ids(self):
        self.assertEqual(S.check_ids(["report", "classify", "time", "classify"]), ["classify", "time", "report"])
        self.assertEqual(S.check_ids("time,mining"), ["time", "mining"])
        for bad in (["nope"], ["Time"], ["ai:nope"], [], ["a b"], "classify,,zz"):
            with self.assertRaises(ValueError):
                S.check_ids(bad)
        with self.assertRaises(ValueError):
            S.get("x")
        self.assertEqual(S.name_ko("time"), "근무시간·단위업무")


class PlanTest(unittest.TestCase):
    def test_full(self):
        p = S.plan_run(None, ai=True)
        self.assertEqual(set(p.values()), {"run"})
        p = S.plan_run(None, ai=False)
        self.assertEqual({k for k, v in p.items() if v == "skip:ai_off"}, set(S.AI_STAGES))
        self.assertEqual(list(p), list(S.STAGE_IDS))

    def test_quick_rerun(self):
        """빠른 재분석: classify,time,mining,report --no-ai — load·normalize 는 함께 돈다(auto, 응답 수동 행을 다시 읽음)."""
        p = S.plan_run(list(S.QUICK_RERUN), ai=False, rerun=True)
        self.assertEqual(p, {"load": "auto", "normalize": "auto", "classify": "run", "ai:task_label": "skip:not_selected",
                             "time": "run", "mining": "run", "ai:workflow": "skip:not_selected",
                             "review": "skip:not_selected", "ai:review_text": "skip:not_selected", "report": "run"})

    def test_chain_closure(self):
        p = S.plan_run(["time"], ai=False, rerun=True)
        self.assertEqual([k for k, v in p.items() if v in ("run", "auto")], ["load", "normalize", "classify", "time"])
        p = S.plan_run(["ai:task_label"], ai=True, rerun=True)
        self.assertEqual(p["classify"], "auto")
        self.assertEqual(p["ai:task_label"], "run")
        self.assertEqual(p["time"], "auto")

    def test_reuse_without_chain(self):
        """사슬을 고르지 않은 재분석 = 원본 실행의 시간·분류 결과를 옮겨 쓴다."""
        p = S.plan_run(["report"], ai=False, rerun=True)
        self.assertEqual(p["time"], "reuse")
        self.assertEqual({p[k] for k in ("load", "normalize", "classify")}, {"skip:reused"})
        self.assertEqual(p["report"], "run")
        self.assertEqual(p["mining"], "skip:not_selected")
        p = S.plan_run(["ai:workflow"], ai=True, rerun=True)
        self.assertEqual((p["mining"], p["ai:workflow"], p["time"]), ("auto", "run", "reuse"))
        p = S.plan_run(["ai:review_text", "report"], ai=True, rerun=True)
        self.assertEqual((p["review"], p["ai:review_text"], p["report"]), ("auto", "run", "run"))

    def test_refusals(self):
        with self.assertRaises(ValueError):
            S.plan_run(["report"], ai=False, rerun=False)         # 다시 쓸 이전 결과 없음
        with self.assertRaises(ValueError):
            S.plan_run(["ai:workflow"], ai=False, rerun=True)     # AI 만 골랐는데 --no-ai
        p = S.plan_run(["ai:workflow", "mining"], ai=False, rerun=True)
        self.assertEqual((p["mining"], p["ai:workflow"]), ("run", "skip:ai_off"))


if __name__ == "__main__":
    unittest.main()
