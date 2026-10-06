# -*- coding: utf-8 -*-
"""WP-31 내보내기 크기 상한·보관 정리(R §9.4 · §9.1.1 · §10.2 · RPT-35).

- `report.export.maxHtmlMb` 를 넘으면 드릴다운 섬에서 ① 날짜 상세 → ② 단위업무 근거 줄 → ③ 단위업무 상세 순으로 빼고
  `trimmed` 에 적는다(머리 알림 줄). 모델 본체는 빼지 않는다.
- `report.export.keep` 을 넘는 `out\\personal\\` 폴더는 이 모듈이 만든 이름 형식만 오래된 것부터 지운다.
"""
from __future__ import annotations

import json
import os
import re
import time
import unittest

from lm27.report import export as EX
from tests.fixtures.wp30 import world as W
from tests.fixtures.wp31 import runs as R


def no_fallback(*_a):
    return None


def drill(n_days=40, n_units=20, ev=30):
    days = {f"2026-09-{i % 28 + 1:02d}#{i}": {"d": "2026-09-01", "intervals": [{"a": "09:00", "b": "09:05",
                                                                                "targets": [["u_x", 5, "O"]]}] * 30}
            for i in range(n_days)}
    units = {f"u_{i:010x}": {"unit_id": f"u_{i:010x}", "cycles": [], "runs": [{"type": "DOC_XLS"}] * 5,
                             "evidence": [{"id": f"e{j}", "title": "근거 제목 " * 5} for j in range(ev)], "evidence_more": 0}
             for i in range(n_units)}
    return {"units": units, "days": days, "trimmed": []}


def render(m_isl, d_isl):
    return "<html>" + m_isl + "|" + d_isl + "</html>"


class FitHtmlTest(unittest.TestCase):
    def test_order(self):
        model = {"months": [{"m": "2026-09", "env_min": 1}]}
        d = drill()
        full, tr = EX.fit_html(model, d, 10 ** 9, render)
        self.assertEqual(tr, [])
        size = len(full.encode("utf-8"))
        no_days = len(render(EX.island(model), EX.island({**d, "days": {}, "trimmed": ["x" * 30]})).encode("utf-8"))
        html, tr = EX.fit_html(model, d, no_days, render)
        self.assertEqual(tr, ["근거 › 날짜 상세"])
        self.assertLessEqual(len(html.encode("utf-8")), no_days)
        html, tr = EX.fit_html(model, d, size // 8, render)
        self.assertEqual(tr[:2], ["근거 › 날짜 상세", "단위업무 근거 줄"])
        isl = json.loads(re.search(r"\|(.*)</html>", html).group(1))
        self.assertEqual(isl["days"], {})
        if len(tr) == 2:
            self.assertTrue(all("evidence" not in u for u in isl["units"].values()))
        html, tr = EX.fit_html(model, d, 10, render)                  # 다 빼도 넘으면 그대로(모델 본체 유지)
        self.assertEqual(tr, ["근거 › 날짜 상세", "단위업무 근거 줄", "단위업무 근거 상세"])
        self.assertIn('"months"', html)
        isl = json.loads(re.search(r"\|(.*)</html>", html).group(1))
        self.assertEqual((isl["units"], isl["days"]), ({}, {}))
        self.assertEqual(isl["trimmed"], tr)

    def test_export_with_low_cap(self):
        """RPT-35: 상한을 1MB 로 낮춘 내보내기 — 섬이 상한을 넘으면 줄이고 결과에 적는다."""
        t = R.TmpRoot()
        self.addCleanup(t.cleanup)
        srun = R.rich_run()
        srun.write(t.paths)
        cfg = W.cfg().derive({"report.export.maxHtmlMb": 1})
        inp = srun.inputs(t.paths, cfg)
        big = "근거 " * 10000
        for ln in inp.evidence.lines.values():
            ln["title"] = big                                         # 근거 줄을 크게 — 단위업무 근거 섬이 1MB 를 넘게
        res = EX.export(R.RUN_ID, ["html"], ["full"], os.path.join(t.root, "o"), paths=t.paths, cfg=cfg, inputs=inp,
                        fallback=no_fallback)
        self.assertEqual(res.rc, 0, res.failed)
        self.assertIn("full", res.trimmed)
        self.assertEqual(res.trimmed["full"][0], "근거 › 날짜 상세")
        with open(os.path.join(t.root, "o", "report_full.html"), "rb") as fh:
            data = fh.read()
        self.assertLessEqual(len(data), 1048576)
        m = re.search(rb'id="lm27-drill">(.*?)</script>', data, re.S)
        self.assertEqual(json.loads(m.group(1))["trimmed"], res.trimmed["full"])


class PruneTest(unittest.TestCase):
    def test_keep_only_own_folders(self):
        t = R.TmpRoot()
        self.addCleanup(t.cleanup)
        root = os.path.join(t.root, "out", "personal")
        names = [f"2026-0{m}-01_2026-0{m}-28_{i:08x}" for i, m in enumerate((3, 4, 5, 6, 7), 1)]
        for n in names:
            os.makedirs(os.path.join(root, n))
            time.sleep(0.02)
        os.makedirs(os.path.join(root, "내 자료"))
        with open(os.path.join(root, "메모.txt"), "wb") as fh:          # 시험 자료(남의 파일 흉내)
            fh.write(b"x")
        gone = EX.prune_exports(root, 2, protect=(os.path.join(root, names[0]),))
        self.assertEqual(gone, names[1:3])
        left = sorted(os.listdir(root))
        self.assertIn("내 자료", left)
        self.assertIn("메모.txt", left)
        self.assertIn(names[0], left)                                  # 지금 내보낸 폴더는 지우지 않는다
        self.assertEqual(EX.prune_exports(os.path.join(root, "없음"), 1), [])

    def test_export_prunes_default_location(self):
        t = R.TmpRoot()
        self.addCleanup(t.cleanup)
        srun = R.rich_run()
        srun.write(t.paths)
        root = os.path.join(t.root, "out", "personal")
        for i in range(3):
            os.makedirs(os.path.join(root, f"2026-01-01_2026-01-31_{i:08x}"))
            time.sleep(0.02)
        cfg = W.cfg().derive({"report.export.keep": 2})
        res = EX.export(R.RUN_ID, ["json"], ["full"], None, paths=t.paths, cfg=cfg, inputs=srun.inputs(t.paths, cfg),
                        fallback=no_fallback)
        self.assertEqual(res.rc, 0)
        self.assertEqual(len(res.pruned), 2)
        self.assertEqual(len([n for n in os.listdir(root) if EX.FOLDER_RX.match(n)]), 2)
        self.assertTrue(os.path.isfile(os.path.join(os.fspath(t.paths.out_personal("2026-08-01", "2026-10-04", R.RUN_ID)),
                                                    "report_model.json")))


if __name__ == "__main__":
    unittest.main()
