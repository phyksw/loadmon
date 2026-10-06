# -*- coding: utf-8 -*-
"""WP-33 커버리지 원장(lm27.collect.ledger) — 미관측 ≠ 0h(T-09) · 상한·예산 partial(T-10) · 지평선(CM-9) · 출처 최선 합성 ·
코파일럿 zero_ok 예외(X-131) · R-COMGAP(X-311) · 멀티 PC 재방문(CM-19·CT-17 원장 측) · 결정성(계약 §3.11 · §8.1)."""
from __future__ import annotations

import json
import unittest

from lm27.collect import ledger, rcmap
from lm27.collect import stage_result as sr
from lm27.util import fsx
from tests.fixtures.wp33.helpers import NOW, Sandbox, ident, local_noon_utc, pc_json, stored_row, write_rows

PC1, PC2 = ident("PC1"), ident("PC2")
W0, W1 = "2026-09-26", "2026-10-05"                         # lookbackDays=10, 오늘(로컬) 2026-10-05


def ob(pc, src, run, rc, reasons=(), *, ranges=((W0, W1),), **kw):
    o = ledger.observation(rc, reasons, ranges=[list(r) for r in ranges], **kw)
    o.update(run_id=run, pc_id=pc.pc_id, src=src, stage="x", updated="2026-10-05T03:00:00Z")
    return o


def feeder(rows_by_kind):
    def it(paths, kind, d0=None, d1=None, *, cfg=None, overlay=True, off_min=None, **kw):
        for r in rows_by_kind.get(kind, ()):
            yield dict(r)
    return it


def row(kind, src, pc, day, i=0, **kw):
    r = stored_row(kind, src, pc.pc_id, local_noon_utc(day, 9 + i % 8), seq=i, **kw)
    r["_pc"] = pc.pc_id
    return r


class LedgerCase(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox(scripts=False)
        self.addCleanup(self.sb.cleanup)
        self.cfg = self.sb.cfg(**{"collect.lookbackDays": 10})

    def build(self, rows=None, obs=()):
        n = ledger.rebuild_coverage(self.sb.paths, cfg=self.cfg, now=NOW, iter_records=feeder(rows or {}), obs=obs)
        cells = ledger.load_cells(self.sb.paths)
        self.assertEqual(n, len(cells))
        return {(c["date"], c["kind_axis"], c["src"], c["pc_id"]): c for c in cells}

    def test_unobserved_is_not_zero(self):
        rows = {"mail": [row("mail", "mail.index", PC1, "2026-10-01"), row("mail", "mail.index", PC1, "2026-10-01", 1)]}
        cells = self.build(rows)
        c = cells[("2026-10-01", "mail_in", "mail.index", PC1.pc_id)]
        self.assertEqual((c["status"], c["n"], c["n_minute"]), ("ok", 2, 2))
        # 관측 없이 레코드만 → 다른 날은 미관측(not_attempted) — 0건(zero_ok)이 아니다(T-09)
        self.assertEqual(cells[("2026-10-02", "mail_in", "mail.index", PC1.pc_id)]["status"], "not_attempted")
        self.assertEqual(cells[("2026-10-01", "mail_out", "mail.index", PC1.pc_id)]["status"], "not_attempted")

    def test_read_zero_is_zero_ok_and_blocked_is_blocked(self):
        rows = {"mail": [row("mail", "mail.index", PC1, "2026-10-01")]}
        obs = [ob(PC1, "mail.index", "20261005-120000-0001", 4),
               ob(PC1, "mail.com", "20261005-120000-0001", 3, ["R-NEWOL"])]
        cells = self.build(rows, obs)
        self.assertEqual(cells[("2026-10-02", "mail_in", "mail.index", PC1.pc_id)]["status"], "zero_ok")
        self.assertEqual(cells[("2026-10-01", "mail_in", "mail.index", PC1.pc_id)]["status"], "ok")
        b = cells[("2026-10-02", "mail_out", "mail.com", PC1.pc_id)]
        self.assertEqual((b["status"], b["reasons"]), ("blocked", ["R-NEWOL"]))
        self.assertEqual(b["run_id"], "20261005-120000-0001")
        for c in cells.values():
            self.assertIn(c["status"], rcmap.CELL_STATUSES)

    def test_records_beat_blocked_observation(self):
        rows = {"cal": [row("cal", "cal.com", PC1, "2026-09-30")]}
        cells = self.build(rows, [ob(PC1, "cal.com", "20261005-120000-0001", 3, ["R-DIALOG"])])
        self.assertEqual(cells[("2026-09-30", "cal", "cal.com", PC1.pc_id)]["status"], "ok")
        self.assertEqual(cells[("2026-10-01", "cal", "cal.com", PC1.pc_id)]["status"], "blocked")

    def test_cap_and_budget_are_partial(self):
        cells = self.build({}, [ob(PC1, "mail.index", "20261005-120000-0001", 0, cap_hit=True),
                                ob(PC1, "cal.index", "20261005-120000-0001", 0, budget_hit=True)])
        c = cells[("2026-10-03", "mail_in", "mail.index", PC1.pc_id)]
        self.assertEqual((c["status"], c["cap_hit"], c["reasons"]), ("partial", True, ["R-CAP"]))   # T-10
        c = cells[("2026-10-03", "cal", "cal.index", PC1.pc_id)]
        self.assertEqual((c["status"], c["budget_hit"], c["reasons"]), ("partial", True, ["R-BUDGET"]))

    def test_horizon_and_com_months(self):
        """CM-9 — 지평선 밖 달은 out_of_horizon(+R-HORIZON), 예산에 끊긴 달은 partial, 다 읽은 달은 0건이면 zero_ok."""
        rows = {"mail": [row("mail", "mail.com", PC1, "2026-10-02")]}
        o1 = ob(PC1, "mail.com", "20261005-120000-0001", 0, budget_hit=True, horizon_oldest="2026-09-29",
                months={"2026-10": "done", "2026-09": "partial"})
        o2 = ob(PC1, "mail.index", "20261005-120000-0001", 4, horizon_oldest="2026-09-29")
        cells = self.build(rows, [o1, o2])
        self.assertEqual(cells[("2026-10-02", "mail_in", "mail.com", PC1.pc_id)]["status"], "ok")
        self.assertEqual(cells[("2026-10-03", "mail_in", "mail.com", PC1.pc_id)]["status"], "zero_ok")
        p = cells[("2026-09-27", "mail_in", "mail.com", PC1.pc_id)]
        self.assertEqual((p["status"], p["budget_hit"]), ("partial", True))
        h = cells[("2026-09-27", "mail_in", "mail.index", PC1.pc_id)]
        self.assertEqual((h["status"], h["reasons"]), ("out_of_horizon", ["R-HORIZON"]))
        self.assertEqual(cells[("2026-09-30", "mail_in", "mail.index", PC1.pc_id)]["status"], "zero_ok")
        o3 = ob(PC1, "mail.com", "20261005-130000-0002", 0, months={"2026-09": "out_of_horizon"})
        cells = self.build(rows, [o3])
        self.assertEqual(cells[("2026-09-27", "mail_out", "mail.com", PC1.pc_id)]["reasons"], ["R-HORIZON"])

    def test_best_of_runs_keeps_observed_zero(self):
        obs = [ob(PC1, "pc.events", "20261001-090000-0001", 4, ranges=(("2026-09-26", "2026-10-01"),)),
               ob(PC1, "pc.events", "20261005-120000-0002", 3, ["R-TRANSPORT"])]
        cells = self.build({}, obs)
        self.assertEqual(cells[("2026-09-28", "pc", "pc.events", PC1.pc_id)]["status"], "zero_ok")
        t = cells[("2026-10-03", "pc", "pc.events", PC1.pc_id)]
        self.assertEqual((t["status"], t["reasons"]), ("transport_fail", ["R-TRANSPORT"]))

    def test_copilot_zero_ok_cannot_cover_other_unobserved(self):
        """X-131 · B Q23⑤ · CM-17 원장 측 — 코파일럿 zero_ok 는 다른 출처의 미관측을 '활동 없음'으로 바꾸지 못한다."""
        rows = {"mail": [row("mail", "mail.copilot", PC2, "2026-10-04", precision="date", direction="in")]}
        obs = [ob(PC1, "mail.com", "20261005-120000-0001", 3, ["R-NEWOL"]),
               ob(PC2, "mail.copilot", "20261005-130000-0002", 4, ranges=(("2026-10-01", "2026-10-04"),))]
        self.build(rows, obs)
        comp = ledger.composite(ledger.load_cells(self.sb.paths))
        self.assertEqual(comp[("2026-10-02", "mail_in")]["status"], "blocked")        # zero_ok 로 덮이지 않음
        self.assertEqual(comp[("2026-10-04", "mail_in")]["status"], "ok")             # 증인 행은 존재 증거
        cells = ledger.load_cells(self.sb.paths)
        only_cp = [c for c in cells if c["src"] == "mail.copilot" and c["date"] == "2026-10-02"]
        self.assertEqual(ledger.composite(only_cp)[("2026-10-02", "mail_in")]["status"], "not_attempted")
        st = ledger.day_axis_status(self.sb.paths)
        self.assertEqual(st[("2026-10-02", "mail_in")], "blocked")
        c4 = [c for c in cells if c["src"] == "mail.copilot" and c["date"] == "2026-10-04" and c["kind_axis"] == "mail_in"]
        self.assertEqual((c4[0]["n_date"], c4[0]["n_minute"]), (1, 0))                # date-only 는 시간 근거 아님
        # 통합(W2 C00 견고화 handoff): 출처·PC 가 없는 셀도 합성한다(출처 없음 = 코파일럿 아님) — KeyError 없음
        bare = [{"date": "2026-10-02", "kind_axis": "mail_in", "status": "zero_ok"},
                {"date": "2026-10-02", "kind_axis": "mail_in", "status": "blocked", "src": "mail.com"}]
        self.assertEqual(ledger.composite(bare)[("2026-10-02", "mail_in")]["status"], "zero_ok")
        self.assertEqual(ledger.composite(bare[:1])[("2026-10-02", "mail_in")]["srcs"], {"": "zero_ok"})

    def test_comgap(self):
        rows = {"mail": [row("mail", "mail.index", PC1, "2026-10-01", i) for i in range(4)]
                + [row("mail", "mail.com", PC1, "2026-10-01", 10)]
                + [row("mail", "mail.index", PC1, "2026-10-02", 20)]}
        obs = [ob(PC1, "mail.com", "20261005-120000-0001", 0), ob(PC1, "mail.index", "20261005-120000-0001", 0)]
        cells = self.build(rows, obs)
        self.assertIn("R-COMGAP", cells[("2026-10-01", "mail_in", "mail.com", PC1.pc_id)]["reasons"])   # 4÷1 > 1.3
        self.assertIn("R-COMGAP", cells[("2026-10-02", "mail_in", "mail.com", PC1.pc_id)]["reasons"])   # COM 0·색인 1
        self.assertNotIn("R-COMGAP", cells[("2026-10-03", "mail_in", "mail.com", PC1.pc_id)]["reasons"])
        cfg = self.sb.cfg(**{"collect.lookbackDays": 10, "ledger.mismatchRatio": 5.0})
        ledger.rebuild_coverage(self.sb.paths, cfg=cfg, now=NOW, iter_records=feeder(rows), obs=obs)
        c = [x for x in ledger.load_cells(self.sb.paths) if x["src"] == "mail.com" and x["date"] == "2026-10-01"
             and x["kind_axis"] == "mail_in"][0]
        self.assertNotIn("R-COMGAP", c["reasons"])                                     # 설정이 결과를 바꾼다(죽은 키 아님)

    def test_multi_pc_revisit_and_teams_subledger(self):
        """CM-19 · CT-17 원장 측 — PC1 → PC2 → PC1 재방문: PC 마다 따로 세고 합성은 최선 값, 팀즈 방 하위 원장."""
        chat = "h" + "a" * 16
        rows = {"teams": [row("teams", "teams.uia", PC1, "2026-10-01", chat=chat),
                          row("teams", "teams.uia", PC1, "2026-10-01", 1, precision="unknown", chat=chat),
                          row("teams", "teams.web", PC2, "2026-10-01", 2, chat=chat)]}
        obs = [ob(PC1, "teams.uia", "20261001-120000-0001", 4, ranges=(("2026-10-01", "2026-10-01"),)),
               ob(PC2, "teams.web", "20261002-120000-0002", 0),
               ob(PC1, "teams.uia", "20261005-120000-0003", 3, ["R-UIAEMPTY"], ranges=(("2026-10-05", "2026-10-05"),))]
        cells = self.build(rows, obs)
        a = cells[("2026-10-01", "teams", "teams.uia", PC1.pc_id)]
        self.assertEqual((a["status"], a["n"], a["n_unknown"]), ("ok", 2, 1))
        self.assertEqual(cells[("2026-10-05", "teams", "teams.uia", PC1.pc_id)]["status"], "blocked")
        comp = ledger.composite(ledger.load_cells(self.sb.paths))
        self.assertEqual(comp[("2026-10-05", "teams")]["status"], "zero_ok")             # 웹 백필이 읽었다
        self.assertEqual(comp[("2026-10-05", "teams")]["srcs"], {"teams.uia": "blocked", "teams.web": "zero_ok"})
        # CT-6 원장 측 — 같은 날 UIA·웹이 둘 다 읽어도 합성은 상태(최선 값)이지 건수 합이 아니다(이중 계상 0)
        self.assertEqual(comp[("2026-10-01", "teams")]["status"], "ok")
        self.assertNotIn("n", comp[("2026-10-01", "teams")])
        self.assertEqual(cells[("2026-10-01", "teams", "teams.web", PC2.pc_id)]["n"], 1)
        sub = [json.loads(x) for x in fsx.read_bytes(self.sb.paths.teams_coverage()).splitlines()]
        self.assertEqual({(s["src"], s["n"], s["n_unknown"]) for s in sub}, {("teams.uia", 2, 1), ("teams.web", 1, 0)})
        self.assertTrue(all(s["chat_key"] == chat for s in sub))

    def test_deterministic_bytes(self):
        rows = {"pc_session": [row("pc_session", "pc.sampler", PC1, "2026-10-01")]}
        obs = [ob(PC1, "pc.sampler", "20261005-120000-0001", 4, ranges=((W1, W1),))]
        self.build(rows, obs)
        a = fsx.read_bytes(self.sb.paths.coverage_ledger())
        self.build(rows, list(reversed(obs)))
        self.assertEqual(a, fsx.read_bytes(self.sb.paths.coverage_ledger()))
        line = json.loads(a.splitlines()[0])
        self.assertEqual(sorted(line), sorted(["account", "date", "kind_axis", "src", "pc_id", "status", "n", "n_minute",
                                               "n_date", "n_unknown", "horizon_oldest", "horizon_newest", "reasons",
                                               "budget_hit", "cap_hit", "probe_sig", "run_id", "observed_at"]))
        self.assertEqual(line["account"], "self")


class LedgerFromBundleCase(unittest.TestCase):
    """세그먼트(단일 로더)·단계 결과 파일·pc.json 에서 실제로 다시 만든다(주입 없음)."""

    def setUp(self):
        self.sb = Sandbox(scripts=False)
        self.addCleanup(self.sb.cleanup)
        self.cfg = self.sb.cfg(**{"collect.lookbackDays": 10})

    def test_rebuild_from_disk(self):
        p = self.sb.paths
        pc_json(p, PC1, caps={"mail.index": {"ok": True, "value": {}, "reasons": [], "verdict": "가능",
                                             "history": [{"date": "2026-10-05", "status": "ok", "reasons": [],
                                                          "probe_sig": "sig123456789"}]}})
        write_rows(p, PC1, "mail", [stored_row("mail", "mail.index", PC1.pc_id, local_noon_utc("2026-10-03", 10 + i),
                                               seq=i, box="sent" if i == 0 else "inbox") for i in range(3)])
        run = "20261005-120000-00ab"
        obs = {"mail.index": ledger.observation(4, [], n=0, ranges=[[W0, W1]])}
        sr.write_stage_result(p, run, "mail_local", state="done", rc=4, pc_id=PC1.pc_id, srcs=obs,
                              updated="2026-10-05T03:00:00Z")
        self.assertEqual(ledger.list_runs(p), [run])
        self.assertEqual(len(ledger.load_observations(p)), 1)
        ledger.rebuild_coverage(p, cfg=self.cfg, now=NOW)
        cells = {(c["date"], c["kind_axis"], c["src"]): c for c in ledger.load_cells(p)}
        self.assertEqual(cells[("2026-10-03", "mail_out", "mail.index")]["n"], 1)
        self.assertEqual(cells[("2026-10-03", "mail_in", "mail.index")]["n"], 2)
        self.assertEqual(cells[("2026-10-04", "mail_in", "mail.index")]["status"], "zero_ok")
        self.assertEqual(cells[("2026-10-04", "mail_in", "mail.index")]["probe_sig"], "sig123456789")
        self.assertEqual(cells[("2026-10-04", "mail_in", "mail.index")]["run_id"], run)


if __name__ == "__main__":
    unittest.main()


class DefaultSinceCase(unittest.TestCase):
    """계약 v1.3 §0.8 V6: 수집 기본 시작일 = 회고 기간과 올해 1월 1일 중 이른 날(단일원 default_since)."""

    def setUp(self):
        from tests.fixtures.wp33.helpers import Sandbox
        self.sb = Sandbox(scripts=False)
        self.addCleanup(self.sb.cleanup)

    def test_year_start_by_default(self):
        from datetime import date
        from lm27.collect import ledger as lg
        cfg = self.sb.cfg(**{"collect.lookbackDays": 10})
        self.assertEqual(lg.default_since(cfg, date(2026, 10, 6)), date(2026, 1, 1))

    def test_lookback_wins_when_earlier(self):
        from datetime import date
        from lm27.collect import ledger as lg
        cfg = self.sb.cfg(**{"collect.lookbackDays": 400})
        self.assertEqual(lg.default_since(cfg, date(2026, 10, 6)), date(2025, 9, 2))

    def test_off_keeps_lookback(self):
        from datetime import date
        from lm27.collect import ledger as lg
        cfg = self.sb.cfg(**{"collect.lookbackDays": 10, "collect.sinceYearStart": False})
        self.assertEqual(lg.default_since(cfg, date(2026, 10, 6)), date(2026, 9, 27))
