# -*- coding: utf-8 -*-
"""커버리지 원장 재생성 비용(W2 검토 C20) — 관측이 쌓여도 재생성이 '날 × 실행'으로 늘지 않고, 결과는 예전 전수 비교와 같다.

  · 같은 결과: 무작위 관측(실행·단계·창·rc·사유·상한·예산·지평선·COM 달 상태)을 예전 판정(``ledger._cell`` — 모든 관측 ×
    모든 날)과 새 판정(``rebuild_coverage`` — 갈래별 '가장 늦은 관측' 칠하기)으로 만들어 셀을 그대로 대조한다.
  · 비용: 하루 1회 1년치(365 실행)에서 재생성이 몇 초 안에 끝나고, 관측을 두 배로 늘려도 시간이 네 배가 아니다(제곱 아님).
  · 해석 캐시: 같은 프로세스의 두 번째 재생성은 끝난 실행의 단계 결과를 다시 해석하지 않는다.
모든 쓰기는 %TEMP% 샌드박스(``Sandbox``) — 실제 data\\ 0.
"""
from __future__ import annotations

import random
import time
import unittest
from datetime import UTC, date, datetime, timedelta

from lm27.collect import ledger
from lm27.collect import stage_result as sr
from tests.fixtures.wp33.helpers import NOW, Sandbox, ident

PCS = (ident("PC1"), ident("PC2"))
SRCS = ("mail.index", "mail.com", "cal.index", "pc.events", "teams.web")
REASONS = ((), ("R-HORIZON",), ("R-NOIDX",), ("R-LOGIN",), ("R-TRANSPORT",), ("R-NOAPP",), ("R-CAP",), ("R-RECURINC",))


def _obs(rng, i, d1):
    """무작위 관측 하나(합성 — 원문 없음)."""
    span = rng.choice((1, 3, 10, 60, 120, 280))
    end = d1 - timedelta(days=rng.randrange(0, 30))
    start = end - timedelta(days=span - 1)
    rc = rng.choice((0, 0, 1, 2, 3, 4, None))
    months = {}
    if rng.random() < 0.2:
        m = (end - timedelta(days=rng.randrange(0, 60))).strftime("%Y-%m")
        months[m] = rng.choice(ledger.MONTH_STATES)
    ho = (start + timedelta(days=rng.randrange(0, span))).isoformat() if rng.random() < 0.3 else None
    o = ledger.observation(rc, rng.choice(REASONS), n=rng.randrange(0, 5), ranges=[[start.isoformat(), end.isoformat()]],
                           cap_hit=rng.random() < 0.1, budget_hit=rng.random() < 0.1,
                           stop_kind=rng.choice((None, None, "stall", "budget")), horizon_oldest=ho, months=months,
                           probe_sig=rng.choice((None, "aaaaaaaaaaaa", "bbbbbbbbbbbb")))
    run = (datetime(2026, 1, 1, tzinfo=UTC) + timedelta(hours=7 * i)).strftime("%Y%m%d-%H%M%S") + f"-{i % 65536:04x}"
    o.update(run_id=run, pc_id=rng.choice(PCS).pc_id, src=rng.choice(SRCS), stage=rng.choice(("a", "b")),
             updated=f"2026-10-0{1 + i % 5}T00:00:00Z")
    return o


def _reference_cells(cfg, obs, counts=None, sigs=None):
    """예전 판정(모든 관측 × 모든 날) — ``ledger._cell`` 그대로."""
    counts = counts or {}
    sigs = sigs or {}
    d0, d1 = ledger.ledger_window(cfg, NOW, obs)
    by_pair = {}
    for o in obs:
        by_pair.setdefault((o["pc_id"], o["src"]), []).append(o)
    out = []
    for pc, src in sorted(by_pair):
        olist = sorted(by_pair[(pc, src)], key=lambda o: o["run_id"])
        for axis in ledger.axes_of(src):
            d = d0
            while d <= d1:
                out.append(ledger._cell(pc, src, axis, d.isoformat(), counts, olist, sigs))
                d += timedelta(days=1)
    out.sort(key=lambda c: (c["date"], c["kind_axis"], c["src"], c["pc_id"]))
    return out


def _empty(*_a, **_k):
    return iter(())


class LedgerFastTest(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox(scripts=False)
        self.addCleanup(self.sb.cleanup)
        self.cfg = self.sb.cfg(**{"collect.lookbackDays": 30, "collect.sinceYearStart": False})

    def _build(self, obs):
        ledger.rebuild_coverage(self.sb.paths, cfg=self.cfg, now=NOW, iter_records=_empty, obs=obs)
        return ledger.load_cells(self.sb.paths)

    def test_same_cells_as_reference_on_random_observations(self):
        d1 = date(2026, 10, 5)
        for seed in range(6):
            rng = random.Random(seed)
            obs = [_obs(rng, i, d1) for i in range(rng.randrange(20, 90))]
            if seed == 0:                                      # 같은 실행 안 두 단계(같은 run_id) — 순서 규칙까지
                twin = dict(obs[0], stage="z")
                obs.append(twin)
            got = self._build(obs)
            ref = _reference_cells(self.cfg, obs)
            self.assertEqual(len(got), len(ref), seed)
            for a, b in zip(got, ref, strict=True):
                self.assertEqual(a, b, seed)

    def test_cost_grows_linearly_not_quadratically(self):
        def daily(n):
            obs = []
            for i in range(n):
                day = date(2026, 10, 5) - timedelta(days=n - 1 - i)
                for src in ("mail.index", "pc.events"):
                    o = ledger.observation(4, (), ranges=[["2026-01-01", day.isoformat()]])
                    o.update(run_id=day.strftime("%Y%m%d") + f"-090000-{i:04x}", pc_id=PCS[0].pc_id, src=src,
                             stage="x", updated="")
                    obs.append(o)
            return obs
        timing = {}
        for n in (180, 360):
            obs = daily(n)
            t0 = time.perf_counter()
            self._build(obs)
            timing[n] = time.perf_counter() - t0
        self.assertLess(timing[360], 20.0)
        # 실행 두 배 → 예전(날 × 실행)은 창도 함께 넓어져 약 4배 이상. 새 판정은 날 + 실행 — 넉넉히 3배 미만
        self.assertLess(timing[360], max(3.0 * timing[180], 1.0), timing)

    def test_parse_cache_reuses_finished_runs(self):
        p = self.sb.paths
        who = PCS[0]
        for i in range(3):
            run = f"2026100{i + 1}-090000-000{i}"
            with sr.stage_scope(p, run, "mail_local", pc_id=who.pc_id, run_mode="auto") as st:
                st.set(state="done", rc=0, hint="", srcs={"mail.index": ledger.observation(
                    0, (), ranges=[["2026-09-01", f"2026-10-0{i + 1}"]])})
        first = ledger.load_observations(p)
        calls = []
        orig = ledger._run_observations

        def spy(paths, rid):
            calls.append(rid)
            return orig(paths, rid)
        ledger._run_observations = spy
        try:
            again = ledger.load_observations(p)
        finally:
            ledger._run_observations = orig
        self.assertEqual(calls, [])                            # 끝난 실행은 다시 해석하지 않는다
        self.assertEqual(again, first)
        again[0]["ranges"].append(["2000-01-01", "2000-01-02"])  # 돌려준 목록을 고쳐도 캐시는 그대로
        self.assertEqual(ledger.load_observations(p), first)


if __name__ == "__main__":
    unittest.main()
