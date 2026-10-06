# -*- coding: utf-8 -*-
"""RPT-42 능력 표 해당 여부(R §5.1.3) + 홈·커버리지 API 모양(R §5.1.4·§5.1.5). 합성 pc.json·원장만."""
import unittest
from datetime import UTC, date, datetime

from lm27.ui import api_home as H
from tests.fixtures.wp35.harness import PC_ID, Running, Sandbox, seed_analysis


def _pc(roles, caps):
    return {"schema": "lm27.pc/1", "pc_id": PC_ID, "label_auto": "PC1", "label_user": "", "kind": "desktop",
            "roles": roles, "capabilities": caps}


class MatrixTest(unittest.TestCase):
    def test_rpt42_applicability(self):
        caps = {"mail.com": {"verdict": "가능", "reasons": [], "value": {"items_30d": 812, "addr": "숨김"},
                             "history": [{"date": "2026-10-05", "status": "ok"}]},
                "mail.owa": {"verdict": "가능", "history": [{"date": "2026-10-05", "status": "ok"}]}}
        pc = _pc(["pc_usage", "mail_local", "teams_window"], caps)
        m = H.matrix([pc], PC_ID)
        cells = m["rows"][0]["cells"]
        for k in ("mail.owa", "teams.web", "mail.copilot", "teams.copilot"):
            self.assertEqual(cells[k]["verdict"], "해당 없음", k)
            self.assertFalse(cells[k]["applies"])
        self.assertEqual(cells["pc.events"]["verdict"], "미확인")          # pc.json 에 없는 키
        self.assertEqual(cells["teams.uia"]["verdict"], "미확인")
        self.assertEqual(cells["mail.com"]["verdict"], "가능")
        self.assertEqual(cells["mail.com"]["hist"], ["ok"])
        self.assertIn("items_30d 812", cells["mail.com"]["summary"])
        self.assertNotIn("숨김", str(cells))                               # 글자 값(원문 가능)은 싣지 않는다
        self.assertEqual(cells["env"]["verdict"], "미확인")                # 모든 PC 에 해당
        self.assertTrue(m["rows"][0]["this"])
        self.assertEqual(len(m["cols"]), len(H.MATRIX_COLS))

    def test_explain_uses_reason_text(self):
        caps = {"mail.com": {"verdict": "불가(확정)", "reasons": ["R-NEWOL"], "history": []}}
        m = H.matrix([_pc(["mail_local"], caps)], PC_ID)
        self.assertTrue(any("새 Outlook" in e for e in m["explain"]))
        self.assertIn("R-NEWOL", m["reasons"])

    def test_web_columns_apply_on_every_pc_by_default(self):
        """계약 v1.3 §0.8 V5: pc.json 바탕 역할만 있는 업무 PC 도 기본 설정이면 Outlook 웹·팀즈 웹·웹 로그인 칸이 '해당'.
        설정을 끄면 예전처럼 '해당 없음'(백필 PC 아님)."""
        from tests.fixtures.wp33.helpers import Sandbox as CSandbox
        sb = CSandbox(scripts=False)
        self.addCleanup(sb.cleanup)
        pc = _pc(["pc_usage", "mail_local", "teams_window"], {})
        on = H.matrix([pc], PC_ID, cfg=sb.cfg())
        cells = on["rows"][0]["cells"]
        for k in ("mail.owa", "cal.owa", "teams.web", "web_login", "edge_cdp_policy"):
            self.assertTrue(cells[k]["applies"], k)
        self.assertFalse(cells["mail.copilot"]["applies"])                  # 코파일럿은 클라우드PC 만
        self.assertIn("account_backfill", on["rows"][0]["roles"])
        off = H.matrix([pc], PC_ID, cfg=sb.cfg(**{"collect.webEverywhere": False}))
        self.assertFalse(off["rows"][0]["cells"]["mail.owa"]["applies"])
        self.assertFalse(H.matrix([pc], PC_ID)["rows"][0]["cells"]["mail.owa"]["applies"])   # cfg 없으면 바탕 그대로

    def test_applies_table(self):
        self.assertTrue(H.applies("web_login", ["copilot"]))
        self.assertFalse(H.applies("web_login", ["pc_usage"]))
        self.assertTrue(H.applies("bundle_location", []))

    def test_axis_ratio(self):
        comp = {("2026-10-05", "teams"): {"status": "ok", "srcs": {"teams.uia": "ok"}},
                ("2026-10-02", "teams"): {"status": "blocked", "srcs": {"teams.uia": "blocked"}}}
        r, best = H.axis_ratio(comp, "teams", date(2026, 10, 5), n=2)
        self.assertEqual(r, 0.5)
        self.assertEqual(best, [("teams.uia", None)])


class HomeApiTest(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()
        self.addCleanup(self.sb.cleanup)
        seed_analysis(self.sb)
        self.app = self.sb.app()
        self.srv = Running(self.app).__enter__()
        self.addCleanup(self.srv.close)

    def test_home_shape(self):
        st, b, _ = self.srv.req("GET", "/api/home")
        self.assertEqual(st, 200, b)
        for k in ("pc", "collect", "coverage", "matrix", "next_actions", "analysis", "team", "reason_text"):
            self.assertIn(k, b)
        self.assertEqual(b["analysis"]["run_id"], "20261005-101500-3fa2")
        self.assertEqual(b["analysis"]["kpi"]["mm"], "1.00")
        self.assertEqual(b["analysis"]["kpi"]["ot_h"], "10.0")
        self.assertEqual(b["analysis"]["kpi"]["unattr_pct"], "5")
        self.assertEqual(b["analysis"]["kpi"]["quality"], "caution")
        self.assertLessEqual(len(b["next_actions"]), 8)
        st, n, _ = self.srv.req("GET", "/api/next-actions")
        self.assertEqual(st, 200)
        self.assertIsInstance(n, list)

    def test_coverage_range_rules(self):
        st, b, _ = self.srv.req("GET", "/api/collect/coverage?from=2026-09-01&to=2026-09-07")
        self.assertEqual(st, 200)
        self.assertEqual(b["axes"], ["mail_in", "mail_out", "cal", "teams", "pc"])
        self.assertEqual(len(b["days"]), 7)
        self.assertEqual(b["days"][0]["s"]["pc"], "not_attempted")         # 미관측 ≠ 0h(T-09) — 원장 없음
        st, b, _ = self.srv.req("GET", "/api/collect/coverage?from=2025-01-01&to=2026-09-07")
        self.assertEqual(st, 400)
        st, b, _ = self.srv.req("GET", "/api/collect/coverage?from=2026-09-07&to=2026-09-01")
        self.assertEqual(st, 400)


class UiTodayTest(unittest.TestCase):
    """C12 회귀: 화면 API 의 '오늘'은 근무 시간대(time.tzOffsetMin, 기본 +09:00) 날짜다. 예전에는 UTC 날짜라 한국 아침 0~9시에
    대시보드·커버리지·감사 기본 창이 하루 전에서 끝나 오늘 칸(오늘 수집 실패)이 빠졌다."""

    NOW = datetime(2026, 10, 6, 23, 30, tzinfo=UTC)                  # 근무 시간대로는 2026-10-07 08:30

    def setUp(self):
        self.sb = Sandbox()
        self.addCleanup(self.sb.cleanup)
        self.app = self.sb.app()
        self.app.deps.now = lambda: self.NOW
        self.srv = Running(self.app).__enter__()
        self.addCleanup(self.srv.close)

    def test_default_windows_end_on_work_today(self):
        from lm27.ui.server import ui_today
        self.assertEqual(ui_today(self.app), date(2026, 10, 7))
        st, b, _ = self.srv.req("GET", "/api/home")
        self.assertEqual(st, 200, b)
        self.assertEqual(b["coverage"]["to"], "2026-10-07")
        st, b, _ = self.srv.req("GET", "/api/collect/coverage")
        self.assertEqual(st, 200, b)
        self.assertEqual(b["days"][-1]["d"], "2026-10-07")
        st, b, _ = self.srv.req("GET", "/api/privacy/audit")
        self.assertEqual(st, 200, b)
        self.assertEqual(b["to"], "2026-10-07")
        st, b, _ = self.srv.req("POST", "/api/worklog", {"retract": "0123456789abcdef"})
        self.assertEqual(st, 200, b)
        self.assertEqual(self.app.deps.pipe_calls[-1]["raws"][0]["date"], "2026-10-07")
        self.app.deps.now = lambda: datetime(2026, 10, 7, 1, 0, tzinfo=UTC)          # 10:00 — 같은 날(대조)
        self.assertEqual(ui_today(self.app), date(2026, 10, 7))


if __name__ == "__main__":
    unittest.main()
