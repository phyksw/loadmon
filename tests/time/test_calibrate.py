# -*- coding: utf-8 -*-
"""WP-20 보정 도구(tools\\calibrate.py — W §8.3 · 계약 §7.3 '보고서만 쓰고 자동 적용 금지').

정답 세트 분리(정답 행은 분석 입력에서 뺀다) · 목적 함수 J · ★ 키만·1~3개·2~5단계 · 가드(정답 날짜 < 10 → 자료 부족,
개선 < 5% → 바꾸지 않음, 보존·단조성 탐침) · 보고서 형(`lm27.calibration/1`, applied 는 늘 false) · 명령줄 인자 오류.
"""
from __future__ import annotations

import importlib.util
import io
import unittest
from contextlib import redirect_stderr
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

from lm27.util.fsx import canon_bytes
from tests.fixtures.wp20 import harness as H
from tests.time import scenarios as X

ROOT = Path(__file__).resolve().parents[2]


def load_tool():
    spec = importlib.util.spec_from_file_location("lm27_tools_calibrate", str(ROOT / "tools" / "calibrate.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


C = load_tool()


def truth_world(n_days: int):
    """근무일마다 문서 작업 + 정답 수동 기록(13:00~15:00, 참조 문서) — 의뢰 메일과 확인 응답 포함."""
    d0 = date(2026, 9, 1)
    cal = X.calendar()
    days, d = [], d0
    while len(days) < n_days:
        if not cal.is_holiday(d):
            days.append(d.isoformat())
        d += timedelta(days=1)
    w = X.W("CAL", days[0], days[-1], "2026-10-30 18:00")
    doc = "설계검토_과제A.docx"
    w.msg(f"{days[0]} 09:10", "in", "request", "M1", "P1", tokens=("설계검토", "과제A"))
    for s in days:
        X.office_day(w, "PC1", s, [("09:30", "12:00", "office", doc)])
        w.doc(f"{s} 11:50", "save", doc)
        w.man("work", a=f"{s} 13:00", b=f"{s} 15:00", ref=doc)
    w.man("report", a=f"{days[-1]} 17:00", ref=doc, key="Q-ans-1")
    return w


class CalibrateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = X.base_cfg()

    def prep(self, w):
        recs, profile, as_of, tags, _over = X.to_inputs(w, self.cfg)
        inputs, truth_rows = C.split_truth(recs)
        truth = C.truth_mans(inputs, truth_rows, profile, self.cfg, as_of)
        return inputs, truth_rows, truth, profile, as_of

    def test_split_truth(self):
        inputs, truth_rows, truth, _p, _a = self.prep(truth_world(3))
        self.assertEqual(len(truth_rows), 4)                                 # work 3 + report 1
        self.assertFalse([r for r in inputs if r["kind"] == "manual"])
        self.assertEqual(sorted(m.kind for m in truth), ["report", "work", "work", "work"])
        self.assertTrue(all(m.ref for m in truth))

    def test_report_and_guards(self):
        inputs, _tr, truth, profile, as_of = self.prep(truth_world(12))
        grid = {"time.envelope.preWindowMin.mail": [10, 20, 30], "episode.s2PrePadMin": [15, 30, 60]}
        rep = C.calibrate(inputs, truth, list(grid), grid, self.cfg, profile=profile, calendar=X.calendar(),
                          as_of=as_of, unit_key=H.TEST_KEY)
        self.assertEqual(rep["schema"], "lm27.calibration/1")
        self.assertIs(rep["applied"], False)                                 # 자동 적용 금지
        self.assertEqual(len(rep["candidates"]), 9)
        self.assertEqual(rep["samples"]["days"], 12)
        self.assertIn(rep["status"], ("ok", "no_gain"))
        self.assertEqual(set(rep["sensitivity"]), set(grid))
        self.assertTrue(all(row["ok"] for row in rep["candidates"]))
        b = rep["baseline"]
        self.assertIsNotNone(b["E"])
        self.assertIsNotNone(b["A"])
        if rep["recommended"]:
            self.assertGreaterEqual(rep["gain"], C.MIN_GAIN)
        else:
            self.assertEqual(rep["status"], "no_gain")
        canon_bytes(rep)                                                     # 정규 JSON 으로 쓸 수 있다

    def test_recommends_better_value(self):
        """정답 보고 시각(17:00)이 휴면 추정 끝(마지막 진행 + 30분)보다 늦다 → e3PostPadMin 을 늘리면 경계 오차가 준다.
        개선 ≥ 5% 이므로 추천하지만 적용하지는 않는다."""
        inputs, _tr, truth, profile, as_of = self.prep(truth_world(12))
        grid = {"episode.e3PostPadMin": [30, 120, 240]}
        rep = C.calibrate(inputs, truth, list(grid), grid, self.cfg, profile=profile, calendar=X.calendar(),
                          as_of=as_of, unit_key=H.TEST_KEY)
        self.assertEqual(rep["status"], "ok")
        self.assertEqual(rep["recommended"], {"episode.e3PostPadMin": 240})
        self.assertGreaterEqual(rep["gain"], C.MIN_GAIN)
        js = [x["J"] for x in rep["sensitivity"]["episode.e3PostPadMin"]]
        self.assertEqual(js, sorted(js, reverse=True))
        self.assertIs(rep["applied"], False)
        self.assertEqual(self.cfg["episode.e3PostPadMin"], 30)               # 실행 설정은 그대로

    def test_insufficient_truth(self):
        inputs, _tr, truth, profile, as_of = self.prep(truth_world(4))
        rep = C.calibrate(inputs, truth, ["episode.dormantWd"], None, self.cfg, profile=profile,
                          calendar=X.calendar(), as_of=as_of, unit_key=H.TEST_KEY)
        self.assertEqual(rep["status"], "insufficient")
        self.assertEqual(rep["candidates"], [])
        self.assertFalse(rep["recommended"])
        self.assertEqual(rep["grid"]["episode.dormantWd"], [3, 5, 7, 10])     # W §8.3 예시 격자

    def test_key_and_grid_checks(self):
        with self.assertRaises(C.CalibrationError):
            C.check_keys(["episode.giantNodes"], self.cfg)                   # ★(미보정) 키가 아님
        with self.assertRaises(C.CalibrationError):
            C.check_keys(["episode.noSuchKey"], self.cfg)
        with self.assertRaises(C.CalibrationError):
            C.check_keys(["episode.dormantWd", "episode.quietWd", "episode.splitWd", "episode.e2High"], self.cfg)
        with self.assertRaises(C.CalibrationError):
            C.check_grid({"episode.dormantWd": [1, 2, 3, 4, 5, 6]}, ["episode.dormantWd"], self.cfg)
        with self.assertRaises(C.CalibrationError):
            C.check_grid({"episode.dormantWd": [1, 9999]}, ["episode.dormantWd"], self.cfg)   # 범위 밖
        g = C.default_grid(["episode.e2High"], self.cfg)
        self.assertTrue(2 <= len(g["episode.e2High"]) <= 5)
        self.assertTrue(all(0.0 <= v <= 2.0 for v in g["episode.e2High"]))

    def test_cli_argument_errors(self):
        err = io.StringIO()
        with redirect_stderr(err):
            self.assertEqual(C.main([]), 1)
            self.assertEqual(C.main(["--keys", "episode.dormantWd", "--from", "2026-09-01", "--to", "2026-09-30",
                                     "--grid", "[1,2]"]), 1)
            self.assertEqual(C.main(["--keys", "episode.dormantWd", "--from", "2026-13-01", "--to", "2026-09-30"]), 1)
            with mock.patch.object(C.importlib.util, "find_spec", lambda name: None):
                self.assertEqual(C.main(["--keys", "episode.dormantWd", "--from", "2026-09-01",
                                         "--to", "2026-09-30"]), 1)
        self.assertIn("모듈이 아직 없습니다", err.getvalue())


if __name__ == "__main__":
    unittest.main()
