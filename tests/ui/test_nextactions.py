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

    def test_web_login_needed_on_any_pc(self):
        """계약 v1.3 §0.8 V5: 웹 경로(Outlook 웹·팀즈 웹)가 로그인 때문에 못 돌았으면 어느 PC 든 N07 — 가장 최근 웹 단계 실행만 본다."""
        import json
        sb = Sandbox()
        self.addCleanup(sb.cleanup)
        app = sb.app()
        root = app.paths.collect_runs()

        def run(run_id, **stages):
            d = root / run_id
            d.mkdir(parents=True, exist_ok=True)
            for st, reasons in stages.items():
                (d / f"stage_result_{st}.json").write_text(json.dumps({"stage": st, "reasons": reasons}), encoding="utf-8")

        run("20261006-090000-aaaa", backfill_owa=["R-LOGIN"], backfill_teams_web=[])
        self.assertTrue(N.gather(app).login_needed)
        self.assertIn("N07", [a.code for a in N.next_actions(N.gather(app))])
        run("20261006-100000-bbbb", mail_local=[])                     # 웹 단계가 없는 실행은 건너뛰고 앞 실행을 본다
        self.assertTrue(N.gather(app).login_needed)
        run("20261006-110000-cccc", backfill_owa=[], backfill_teams_web=[])   # 그 뒤 로그인해서 웹 단계가 돌았다
        self.assertFalse(N.gather(app).login_needed)
        run("20261006-120000-dddd", backfill_teams_web=["R-CA"])        # 조건부 액세스도 같은 안내
        self.assertTrue(N.gather(app).login_needed)

    def test_any_pc_todo_counts_as_mine(self):
        """계약 v1.3 §0.8 V5: 웹 경로 빈칸(want_pc '*')은 어느 PC 든 채운다 — 이 PC 의 할 일(N09)로 세고, 표에는 '모든 PC'."""
        import json
        from lm27.collect import todo as T
        from lm27.ui.api_collect import _todo_rows
        sb = Sandbox()
        self.addCleanup(sb.cleanup)
        app = sb.app()
        me = "pc_" + "a" * 16
        rows = [{"todo_id": "mail.owa:2026-09-01", "account": "me", "date_range": ["2026-09-01", "2026-09-01"],
                 "kind_axis": "mail_in", "want_src": "mail.owa", "want_pc": T.WANT_ANY, "state": "assigned"},
                {"todo_id": "mail.copilot:2026-09-01", "account": "me", "date_range": ["2026-09-01", "2026-09-01"],
                 "kind_axis": "mail_in", "want_src": "mail.copilot", "want_pc": T.WANT_CLOUD, "state": "assigned"}]
        f = app.paths.todo()
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({"schema": T.SCHEMA, "todos": rows}), encoding="utf-8")
        import lm27.ui.api_home as H
        orig = H.this_pc
        H.this_pc = lambda _app: (me, {"pc_id": me})
        self.addCleanup(setattr, H, "this_pc", orig)
        self.assertEqual(N.gather(app).todo_mine, 1)                    # 클라우드PC 몫은 세지 않는다
        out = {r["want_src"]: r for r in _todo_rows(app, me)}
        self.assertEqual(out["mail.owa"]["want_pc"], "모든 PC(먼저 도는 PC)")
        self.assertTrue(out["mail.owa"]["mine"])
        self.assertEqual(out["mail.copilot"]["want_pc"], "클라우드PC")
        self.assertFalse(out["mail.copilot"]["mine"])


if __name__ == "__main__":
    unittest.main()
