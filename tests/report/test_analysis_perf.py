# -*- coding: utf-8 -*-
"""WP-30 분석층 성능(R RPT-46 · 계약 T-19 의 보고서 몫).

1명 × 3개월 성능 세계(WP-20 하네스 `gen_months` — 근무일당 샘플 300 · 메시지 250 · 저장 150 · 회의 4 · 커밋 6, 의뢰 6건 —
단위업무 약 1,000개로 명세 기준 300개보다 크다)의 시간 코어 결과로 분석 문맥 만들기 + 분석층 전체가 10초 안
(report build ≤ 10초 중 분석층 몫 — 모델·내보내기 몫은 WP-31).
"""
from __future__ import annotations

import json
import time
import unittest

from lm27.report.analysis import analyze
from lm27.report.analysis.activity import make_context
from tests.fixtures.wp20 import harness as H
from tests.time import scenarios as X

LIMIT_S = 10.0


class PerfTest(unittest.TestCase):
    def test_three_months(self):
        cfg = X.base_cfg()
        w, n = H.gen_months(3)
        res, _names = H.run(w, cfg, ref_ids=False)
        fs = res.files()

        def jl(b):
            return [json.loads(x) for x in b.decode("utf-8").splitlines() if x.strip()]
        t0 = time.perf_counter()
        ctx = make_context(tasks=json.loads(fs["tasks.json"]), attrib=jl(fs["attrib.jsonl"]),
                           tables=json.loads(fs["team_tables.json"]), cal=X.calendar(), cfg=cfg,
                           env_slots=jl(fs["env_slots.jsonl"]), day_ledger=jl(fs["day_ledger.jsonl"]),
                           run_meta=json.loads(fs["run_meta.json"]))
        sec = analyze(ctx)
        dt = time.perf_counter() - t0
        self.assertGreater(n, 40000)
        self.assertGreater(len(ctx.units), 300)
        self.assertTrue(sec["workflows"]["roles"])
        self.assertLess(dt, LIMIT_S, f"분석층 {dt:.1f}초(단위업무 {len(ctx.units)}개)")


if __name__ == "__main__":
    unittest.main()
