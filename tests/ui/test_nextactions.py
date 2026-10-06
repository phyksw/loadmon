# -*- coding: utf-8 -*-
"""RPT-41 다음 할 일(R §5.7) — 합성 상태(에이전트 멈춤·도착 누락·로그인 필요·질문 3건·승인 대기)에서 N04·N05·N07·N11·N15 가
등급 순서(risk → improve)로, 같은 대상은 한 번만. 조건 표의 나머지 코드·문구 규칙(RPT-40 부분)과 상태 모으기의 부분 실패."""
import unittest

from lm27.ui import nextactions as N
from tests.fixtures.wp35.harness import Sandbox, seed_analysis


class NextActionsTest(unittest.TestCase):
    def test_rpt41_order_and_dedupe(self):
        s = N.UiState(this_pc="PC1", agent="stale", agent_why="마지막 틱이 15분 전입니다", arrival_missing={"PC2": 3},
                      login_needed=True, questions_open=3, questions_week="2026-W39",
                      approvals=["2026-09-01_2026-09-30", "2026-09-01_2026-09-30"])
        acts = N.next_actions(s)
        self.assertEqual([a.code for a in acts], ["N04", "N05", "N07", "N11", "N15"])
        self.assertEqual([a.level for a in acts], ["risk", "risk", "risk", "improve", "improve"])
        self.assertEqual(len({(a.code, a.target) for a in acts}), len(acts))
        n04 = acts[0].as_dict()
        self.assertEqual(n04["action"]["api"], "POST /api/agent/repair")
        self.assertEqual(n04["target"], "PC1")
        self.assertEqual(acts[1].title_ko, "PC2 의 기록 3개가 복사되지 않았습니다")

    def test_all_codes_levels(self):
        s = N.UiState(calendar_years=["2027"], bundle_readonly=True, outbox_blocked=[("2026-09", "인증 필요")],
                      agent="missing", arrival_missing={"PC2": 1}, stale_pcs={"PC3": 9}, login_needed=True,
                      confirmed_blocked=["Outlook 웹(메일)"], todo_mine=2, manual_batches=1, questions_open=1,
                      analysis_behind=True, answers_pending=2, registry_missing=True, approvals=["2026-09"],
                      config_warnings=1, location_warn=["R-BUNDLE-ONEDRIVE"], profile_trace=True, collect_days_ago=4)
        acts = N.next_actions(s)
        codes = [a.code for a in acts]
        self.assertEqual(codes, [f"N{i:02d}" for i in range(1, 20)])
        ranks = [N.LEVELS.index(a.level) for a in acts]
        self.assertEqual(ranks, sorted(ranks))
        for a in acts:
            txt = a.title_ko + a.why_ko
            self.assertNotIn("개발자" + "에게", txt)
            self.assertNotIn("재" + "설치", txt)
            self.assertNotIn("[!]", txt)
            if a.action and a.action.get("api"):
                self.assertTrue(a.action["api"].startswith(("POST /api/", "GET /api/")))

    def test_empty_state_nothing(self):
        self.assertEqual(N.next_actions(N.UiState()), [])

    def test_gather_partial_failures(self):
        sb = Sandbox()
        self.addCleanup(sb.cleanup)
        seed_analysis(sb)
        app = sb.app()
        s = N.gather(app)                                               # 번들·대기열·원장이 없어도 예외 없이
        self.assertEqual(s.questions_open, 2)
        self.assertEqual(s.agent, "missing")
        app.scratch["answered"] = {"9f2c01ab3e4d": "x"}
        app.scratch["answers_pending"] = 1
        s2 = N.gather(app)
        self.assertEqual(s2.questions_open, 1)
        codes = [a.code for a in N.next_actions(s2)]
        self.assertIn("N13", codes)
        self.assertIn("N04", codes)


if __name__ == "__main__":
    unittest.main()
