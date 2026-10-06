# -*- coding: utf-8 -*-
"""WP-33 진단 리포트 모델(lm27.collect.diagnose) — PC 카드·출처 매트릭스·사유 분포·구조적 결손 경고(C §9).
원문 0(카나리아) · '개발자에게 보내라'·재설치 권유 문구 0."""
from __future__ import annotations

import json
import unittest

from lm27.collect import diagnose, ledger, rcmap
from lm27.collect import stage_result as sr
from tests.fixtures.canary import canaries
from tests.fixtures.wp33.helpers import NOW, Sandbox, hist, ident, pc_json

PC1, CLOUD = ident("PC1"), ident("CLOUD", kind="cloud")


def ob(pc, src, run, rc, reasons=(), **kw):
    o = ledger.observation(rc, reasons, ranges=[["2026-09-26", "2026-10-05"]], **kw)
    o.update(run_id=run, pc_id=pc.pc_id, src=src, stage="x", updated="2026-10-05T03:00:00Z")
    return o


class DiagnoseCase(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox(scripts=False)
        self.addCleanup(self.sb.cleanup)
        self.cfg = self.sb.cfg(**{"collect.lookbackDays": 10, "collect.webEverywhere": False, "collect.sinceYearStart": False})
        p = self.sb.paths
        cs = [c.value for c in canaries(groups=("pii",), weak=False) if c.value][:2]
        self.cs = cs
        caps = {"mail.com": hist(("2026-10-04", "fail", ["R-NEWOL"], "a1"), ("2026-10-05", "fail", ["R-NEWOL"], "a1")),
                "mail.index": hist(("2026-10-05", "ok", [], "b1"))}
        caps["mail.com"]["value"] = {"classic": False, "horizon_oldest": "2026-07-01", "mail_total": 1200}
        caps["mail.com"]["verdict"] = "불가(확정)"
        pc_json(p, PC1, caps=caps)
        pc = json.loads((p.pc_dir(PC1.pc_id) / "pc.json").read_bytes())
        pc["host_display"] = cs[0]                                   # 로컬 전용 — 카드에 실리면 안 된다
        (p.pc_dir(PC1.pc_id) / "pc.json").write_bytes(json.dumps(pc, ensure_ascii=False).encode())
        pc_json(p, CLOUD, kind="cloud", label="클라우드PC", first_seen="2026-09-02T00:00:00Z")
        obs = [ob(PC1, "mail.com", "20261005-120000-0001", 3, ["R-NEWOL"]),
               ob(PC1, "mail.index", "20261005-120000-0001", 4)]
        ledger.rebuild_coverage(p, cfg=self.cfg, now=NOW, iter_records=lambda *a, **k: iter(()), obs=obs)
        from lm27.collect import todo
        todo.plan_todo(p, self.cfg, now=NOW)
        sr.write_stage_result(p, "20261005-120000-0001", "mail_local", state="skipped", rc=3, reason="R-NEWOL",
                              reasons=["R-NEWOL"], pc_id=PC1.pc_id)
        sr.write_stage_result(p, "20261005-120000-0001", "derive", state="done", rc=0)

    def test_model(self):
        m = diagnose.diagnose_model(self.sb.paths, now=NOW)
        self.assertEqual(m["schema"], "lm27.diagnose/1")
        cards = {c["pc_id"]: c for c in m["pcs"]}
        c1 = cards[PC1.pc_id]
        self.assertEqual(c1["label_auto"], "PC1")
        com = [x for x in c1["caps"] if x["key"] == "mail.com"][0]
        self.assertEqual((com["verdict"], com["status"], com["reasons"]), ("불가(확정)", "fail", ["R-NEWOL"]))
        self.assertEqual(com["numbers"]["mail_total"], 1200)
        self.assertIn("R-NEWOL", [a["reason"] for a in c1["actions"]])
        self.assertGreater(c1["unobserved_cells"], 0)
        # 매트릭스: 메일은 색인이 읽어 zero_ok, 팀즈·일정·PC 는 관측 없음 → 경고
        rows = {(r["date"], r["axis"]): r for r in m["matrix"]["rows"]}
        self.assertEqual(rows[("2026-10-02", "mail_in")]["status"], "zero_ok")
        self.assertEqual(rows[("2026-10-02", "mail_in")]["srcs"], {"mail.com": "blocked", "mail.index": "zero_ok"})
        self.assertEqual(m["matrix"]["summary"]["mail_out"], {"zero_ok": 10})
        codes = m["reasons"]["by_code"]
        self.assertEqual(codes["R-NEWOL"]["class"], rcmap.STRUCTURAL)
        self.assertTrue(codes["R-NEWOL"]["confirmable"])
        self.assertEqual(m["last_run"]["run_id"], "20261005-120000-0001")
        self.assertEqual({s["stage"] for s in m["last_run"]["stages"]}, {"mail_local", "derive"})
        self.assertEqual(m["last_run"]["rc"], 4)
        self.assertEqual(m["warnings"], [])

    def test_no_raw_text_and_no_forbidden_phrases(self):
        m = diagnose.diagnose_model(self.sb.paths, now=NOW)
        blob = json.dumps(m, ensure_ascii=False)
        for c in self.cs:
            self.assertNotIn(c, blob)
        self.assertNotIn("host_display", blob)
        for bad in ("개발자", "재설치", "다시 설치"):
            self.assertNotIn(bad, blob)
            self.assertFalse(any(bad in t for t in diagnose.REASON_ACTIONS.values()))
        for code in diagnose.REASON_ACTIONS:
            self.assertTrue(rcmap.is_reason(code), code)

    def test_axis_unobserved_warning(self):
        cells = [c for c in ledger.load_cells(self.sb.paths) if c["src"] == "mail.com"]
        m = diagnose.diagnose_model(self.sb.paths, cells=cells, now=NOW)
        self.assertIn({"code": "axis_unobserved", "axis": "mail_in"}, m["warnings"])

    def test_pc_card_counts_any_pc_web_todos(self):
        """W2 검토 L01 · v1.3 §0.8 V5 — 웹 경로 빈칸(want_pc '*')은 어느 PC 든 채운다: 각 PC 카드의 빈칸 작업 수에 든다."""
        from lm27.collect import todo
        todos = [{"todo_id": "cal.owa:2026-10-01:2026-10-02", "want_pc": todo.WANT_ANY, "state": "assigned"},
                 {"todo_id": "teams.web:2026-10-01:2026-10-01", "want_pc": todo.WANT_ANY, "state": "open"},
                 {"todo_id": "mail.owa:2026-09-30:2026-09-30", "want_pc": PC1.pc_id, "state": "assigned"},
                 {"todo_id": "mail.copilot:2026-09-29:2026-09-29", "want_pc": CLOUD.pc_id, "state": "assigned"}]
        m = diagnose.diagnose_model(self.sb.paths, todos=todos, now=NOW)
        cards = {c["pc_id"]: c for c in m["pcs"]}
        self.assertEqual(cards[PC1.pc_id]["todos"], {"assigned": 2, "open": 1})
        self.assertEqual(cards[PC1.pc_id]["todos_any_pc"], 2)
        self.assertEqual(cards[CLOUD.pc_id]["todos"], {"assigned": 2, "open": 1})


if __name__ == "__main__":
    unittest.main()
