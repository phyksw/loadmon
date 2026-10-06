# -*- coding: utf-8 -*-
"""W2 검토 C00 회귀 — 분석 파이프라인이 시간 코어에 넘기는 커버리지는 원장 합성(``lm27.collect.ledger.day_axis_status``)이다.

``*.copilot`` 의 zero_ok 는 다른 출처의 미관측(blocked·transport_fail·not_attempted)을 '0건 확인'으로 바꾸지 못하고,
코파일럿만 있는 날은 미관측이다(계약 §3.11 · X-131 · B Q23⑤). 예전에는 원장 셀을 출처 없이 넘겨 시간 코어가 최선 값만
골라 코파일럿 zero_ok 가 이겼다 — 관측하지 못한 날이 '0건 확인'으로 들어가 보고서 신뢰도 카드가 '믿을 만함'으로 뒤집혔다.
합성 번들(WP-05 생성기)과 %TEMP% 임시 ROOT 만 쓴다.
"""
import json
import unittest
from datetime import date

from lm27.collect.ledger import day_axis_status
from lm27.time.evidence import normalize
from lm27.util import events
from lm27.util.fsx import atomic_write, canon_bytes
from tests.fixtures.wp32 import world as W

PC = "pc_0123456789abcdef"
PCX = "pcx_0123456789abcdef"
WORKDAYS = ("2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04", "2026-09-07", "2026-09-08", "2026-09-09",
            "2026-09-10", "2026-09-11")


def cell(d, ax, src, st, pc=PC):
    return {"date": d, "kind_axis": ax, "src": src, "pc_id": pc, "status": st}


def write_ledger(paths, cells):
    atomic_write(paths.coverage_ledger(), b"".join(canon_bytes(c) + b"\n" for c in cells))


def day_cov(w, run_id=None) -> dict:
    out = {}
    for ln in w.time_bytes("day_ledger.jsonl", run_id).decode("utf-8").splitlines():
        r = json.loads(ln)
        out[r["date"]] = r.get("coverage") or {}
    return out


def model(w, run_id=None) -> dict:
    return json.loads(w.model_bytes(run_id))


class CopilotZeroOkTest(unittest.TestCase):
    """한 세계에서 원장만 바꿔 두 번 분석한다(코파일럿 셀 있음 · 없음)."""

    @classmethod
    def setUpClass(cls):
        events.configure(mode="off")
        cls.w = W.World()
        cls.addClassCleanup(cls.w.remove)
        cls.w.put(W.rows())
        cls.w.keyring()
        base = []
        for d in WORKDAYS:
            base += [cell(d, "mail_out", "mail.com", "blocked"), cell(d, "teams", "teams.web", "transport_fail")]
        cls.base = base
        with_cp = list(base)
        for d in WORKDAYS:
            with_cp += [cell(d, "mail_out", "mail.copilot", "zero_ok", PCX), cell(d, "teams", "teams.copilot", "zero_ok", PCX)]
        with_cp += [cell("2026-09-05", "mail_in", "mail.com", "blocked"),
                    cell("2026-09-05", "mail_in", "mail.copilot", "zero_ok", PCX),
                    cell("2026-09-06", "cal", "cal.copilot", "zero_ok", PCX)]
        write_ledger(cls.w.paths, with_cp)
        cls.expect = day_axis_status(cls.w.paths)
        cls.rc_cp = cls.w.analyze()
        cls.run_cp = cls.w.last
        write_ledger(cls.w.paths, base)
        cls.rc_base = cls.w.analyze()
        cls.run_base = cls.w.last

    @classmethod
    def tearDownClass(cls):
        events.configure(mode="text")

    def test_rc(self):
        self.assertEqual((self.rc_cp, self.rc_base), (0, 0))

    def test_composite_reaches_time_core(self):
        cov = day_cov(self.w, self.run_cp)
        self.assertEqual(cov["2026-09-05"].get("mail_in"), "blocked")         # 코파일럿 0건이 막힘을 덮지 않는다
        self.assertEqual(cov["2026-09-06"].get("cal"), "not_attempted")       # 코파일럿만 있는 날 = 미관측
        self.assertEqual(cov["2026-09-03"].get("mail_out"), "blocked")
        self.assertEqual(cov["2026-09-03"].get("teams"), "transport_fail")
        for (d, ax), st in self.expect.items():                              # 원장 합성과 시간 코어 칸이 같다
            if d in cov:
                self.assertEqual(cov[d].get(ax), st, (d, ax))

    def test_copilot_cells_do_not_change_quality(self):
        a, b = model(self.w, self.run_cp)["quality"], model(self.w, self.run_base)["quality"]
        self.assertEqual((a["grade"], a["reasons"]), (b["grade"], b["reasons"]))
        self.assertIn("comms_cov_bad", a["reasons"])
        self.assertEqual(day_cov(self.w, self.run_cp)["2026-09-03"], day_cov(self.w, self.run_base)["2026-09-03"])


class TimeCoreSrcRowsTest(unittest.TestCase):
    """시간 코어 `normalize` 가 출처가 붙은 원장 셀을 직접 받아도 같은 예외를 지킨다(방어 — 합성 결과와 같아야 한다)."""

    def test_rows_with_src_match_composite(self):
        rows = [cell("2026-09-05", "mail_in", "mail.com", "blocked"),
                cell("2026-09-05", "mail_in", "mail.copilot", "zero_ok", PCX),
                cell("2026-09-06", "cal", "cal.copilot", "zero_ok", PCX),
                cell("2026-09-07", "teams", "teams.copilot", "ok", PCX),
                cell("2026-09-08", "mail_out", "mail.com", "zero_ok")]
        w = W.World()
        self.addCleanup(w.remove)
        ev, _audit = normalize([], {"d0": date(2026, 9, 1), "d1": date(2026, 9, 11), "coverage": rows}, w.cfg(),
                               W.AS_OF, None)
        got = {(d.isoformat(), ax): st for (d, ax), st in ev.coverage.items()}
        self.assertEqual(got, day_axis_status(w.paths, rows))
        self.assertEqual(got[("2026-09-06", "cal")], "not_attempted")
        self.assertEqual(got[("2026-09-07", "teams")], "ok")                # 코파일럿 기록이 있으면 ok 는 그대로


if __name__ == "__main__":
    unittest.main()
