# -*- coding: utf-8 -*-
"""WP-31 성능(R RPT-46 · 계약 T-19): 1명 3개월 — 단위업무 300개 · 슬롯 7천여 개 — `report build` ≤ 10초."""
from __future__ import annotations

import time
import unittest
from datetime import UTC, datetime

import lm27.report as RP
from lm27.report import model as M
from tests.fixtures.wp30 import world as W
from tests.fixtures.wp31 import runs as R


def no_fallback(*_a):
    return None


class PerfTest(unittest.TestCase):
    def test_build_under_10s(self):
        srun = R.big_run(300)
        t = R.TmpRoot()
        self.addCleanup(t.cleanup)
        srun.write(t.paths)
        cfg = W.cfg()
        t0 = time.perf_counter()
        r = RP.build_report(R.RUN_ID, paths=t.paths, cfg=cfg, inputs=srun.inputs(t.paths, cfg, evidence=False),
                            fallback=no_fallback, now=datetime(2026, 10, 1, tzinfo=UTC))
        dt = time.perf_counter() - t0
        self.assertIn(r.rc, (0, 2), r)
        self.assertLess(dt, 10.0, f"report build {dt:.2f}s")
        m = RP.load_model(R.RUN_ID, paths=t.paths)
        self.assertEqual(len(m["units"]), 300)
        self.assertEqual(M.check_model(m), [])
        self.assertLess(len(M.model_bytes(m)), 32 * 1048576)

    def test_model_cap_setting(self):
        """X-281 · G-R9: `report.export.maxModelMb` 를 넘으면 상세를 요약하고 경고(등식은 그대로)."""
        srun = R.big_run(300)
        t = R.TmpRoot()
        self.addCleanup(t.cleanup)
        srun.write(t.paths)
        cfg = W.cfg()
        inp = srun.inputs(t.paths, cfg, evidence=False)
        full = M.build_model(inp, cfg, fallback=no_fallback)
        self.assertGreater(len(M.model_bytes(full)), 1048576)
        self.assertEqual(full["flags"]["trimmed"], [])
        cfg1 = cfg.derive({"report.export.maxModelMb": 1})
        small = M.build_model(srun.inputs(t.paths, cfg1, evidence=False), cfg1, fallback=no_fallback)
        self.assertEqual(small["flags"]["trimmed"][0], "단위업무 구간(runs) 요약")
        self.assertIn("model_trimmed", {w["code"] for w in small["flags"]["warnings"]})
        self.assertEqual(M.check_model(small), [])
        self.assertEqual(small["months"], full["months"])


if __name__ == "__main__":
    unittest.main()
