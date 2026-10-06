# -*- coding: utf-8 -*-
"""W2 검토 회귀(분석 → 보고서 경로, 합성 번들 + %TEMP% 임시 ROOT).

- C01: 모델 `run` 에 화면 선택(`chosen`, current.json)을 싣지 않는다 — 분석 직후 [보고서 다시 만들기]는 rc 4(이미 최신)이고
  [이 결과 보기](explicit)로 바꿔도 모델·JSON 내보내기 바이트가 그대로다(G-R1).
- C02: `report ai-items` 가 시간 결과 없는 실행(없는 run_id·정리된 실행)이면 공유 `ai_in\\<stage>.jsonl` 을 빈 값으로 덮지
  않고 rc 1.
- L03: 단위업무가 0개인 정상 실행(켜짐 구간만 있는 PC)은 '분류 결과 없음' 부분(rc 2)이 아니다.
"""
import json
import os
import unittest

from lm27.cli import rc_of
from lm27.pipeline import analyze as A
from lm27.report import build_report
from lm27.report.analysis.ai_items import write_ai_items
from lm27.report.export import export
from lm27.util import events
from tests.fixtures.wp32 import world as W

MISSING_RUN = "20990101-000000-abcd"


class WebPaths(W.TPaths):
    """화면 자원(인라인 렌더러)은 저장소 원본을 읽기만 한다 — 자기완결 HTML 내보내기용."""

    def web_file(self, rel):
        return W.REPO.joinpath("web", *str(rel).split("/"))


class ChosenAndAiItemsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        events.configure(mode="off")
        cls.w = W.World()
        cls.addClassCleanup(cls.w.remove)
        cls.w.put(W.rows())
        cls.w.keyring()
        cls.rc = cls.w.analyze()
        cls.cfg = cls.w.cfg()

    @classmethod
    def tearDownClass(cls):
        events.configure(mode="text")

    def test_c01_rebuild_is_noop_and_bytes_stable(self):
        self.assertEqual(self.rc, 0)
        rid = self.w.last
        m1 = self.w.model_bytes()
        self.assertNotIn("chosen", json.loads(m1)["run"])
        br = build_report(rid, paths=self.w.paths, cfg=self.cfg)
        self.assertEqual((br.rc, br.skipped), (4, True), br.message)         # 입력이 같으면 '이미 최신'
        out1 = os.path.join(self.w.root, "exp1")
        self.assertEqual(export(rid, ["json"], ["full"], out1, paths=self.w.paths, cfg=self.cfg).rc, 0)
        A.choose_current(self.w.paths, self.cfg, rid, now=W.NOW)              # [이 결과 보기] — explicit
        self.assertEqual(self.w.current()["chosen"], "explicit")
        br = build_report(rid, paths=self.w.paths, cfg=self.cfg)
        self.assertEqual(br.rc, 4, br.message)
        self.assertEqual(self.w.model_bytes(), m1)
        out2 = os.path.join(self.w.root, "exp2")
        res = export(rid, ["json", "html"], ["full"], out2, paths=WebPaths(self.w.root, lad=self.w.lad), cfg=self.cfg)
        self.assertEqual(res.rc, 0, res.failed)
        with open(os.path.join(out1, "report_model.json"), "rb") as a, open(os.path.join(out2, "report_model.json"),
                                                                             "rb") as b:
            self.assertEqual(a.read(), b.read())
        with open(os.path.join(out2, "report_full.html"), encoding="utf-8") as fh:
            self.assertIn('"chosen":"explicit"', fh.read())                  # 화면 띠 표기는 HTML 섬에만

    def test_c02_missing_run_keeps_shared_ai_in(self):
        rid = self.w.last
        counts = write_ai_items(rid, None, paths=self.w.paths, cfg=self.cfg)
        self.assertTrue(counts and all(isinstance(v, int) for v in counts.values()))
        self.assertGreater(sum(counts.values()), 0)
        before = {st: self.w.paths.ai_in(st).read_bytes() for st in counts}
        self.assertTrue(all(before.values()))
        res = write_ai_items(MISSING_RUN, None, paths=self.w.paths, cfg=self.cfg)
        self.assertEqual(res["rc"], 1)
        self.assertIn("time.tasks", res["refused"])
        self.assertEqual(rc_of(res), 1)                                     # cli: 값이 모두 정수가 아니면 rc 키
        self.assertFalse(all(isinstance(v, int) for v in res.values()))
        self.assertEqual({st: self.w.paths.ai_in(st).read_bytes() for st in counts}, before)   # 덮지 않았다


class NoUnitsRunTest(unittest.TestCase):
    def test_l03_zero_units_is_not_partial(self):
        events.configure(mode="off")
        self.addCleanup(events.configure, mode="text")
        w = W.World()
        self.addCleanup(w.remove)
        w.put([r for r in W.rows() if r.get("src") == "pc.events"])        # 켜짐 구간만 — 단위업무 0개
        w.keyring()
        rc = w.analyze()
        self.assertEqual(json.loads(w.time_bytes("tasks.json")), [])
        self.assertEqual(w.hier_bytes("labels.json"), b"{}")
        self.assertEqual(rc, 0)
        rep = w.stage("report")
        self.assertEqual((rep["state"], rep["reason"]), ("done", None))
        br = build_report(w.last, paths=w.paths, cfg=w.cfg(), force=True)
        self.assertEqual((br.rc, br.missing), (0, []))
        self.assertNotIn("labels_missing", br.warnings)
        self.assertIn("units_empty", br.warnings)


if __name__ == "__main__":
    unittest.main()
