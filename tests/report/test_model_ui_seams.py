# -*- coding: utf-8 -*-
"""보고서 모델 → 화면 이음매(사용자 비교 지적 B5·B6·B7) — 합성 실행(tests.fixtures.wp31)만.

- B5 [왜?] 과제 후보: 분류 라벨 ``cands``(규칙 점수 상위 3)가 단위업무에 실린다(전체판만 — 가림판 허용 목록 밖).
- B6 '관련 미귀속 회의 …(MM 미포함)': 분류 꼬리표가 과제를 가리키는 회의의 미귀속 회의 버킷(B_MEET) 분을 과제 트리 노드
  ``unattr_meet_min`` 으로(예약 과제는 주석 없음, 과제 MM 은 그대로).
- B7 분석 시각: ``inputs.analysis_time`` — run_status 끝(UTC → 근무 시간대) · 없으면 current.json. 자기완결 HTML 섬의
  ``run.built_at`` 에만 싣고 모델 파일·JSON 내보내기에는 넣지 않는다(G-R1).
"""
from __future__ import annotations

import json
import os
import re
import unittest
from datetime import UTC, datetime

from lm27.report import export as EX
from lm27.report import fmt as F
from lm27.report import inputs as I
from lm27.report import model as M
from lm27.time.calendar import SLOT
from lm27.util.fsx import atomic_write, canon_bytes
from tests.fixtures.wp30 import world as W
from tests.fixtures.wp31 import runs as R

NOW = datetime(2026, 10, 6, 1, 0, 0, tzinfo=UTC)


def no_fallback(*_a):
    return None


class ModelUiSeamsTest(unittest.TestCase):
    def setUp(self):
        self.t = R.TmpRoot()
        self.addCleanup(self.t.cleanup)
        self.cfg = W.cfg()

    def build(self, srun):
        inp = srun.inputs(self.t.paths, self.cfg)
        return inp, M.build_model(inp, self.cfg, fallback=no_fallback)

    def test_b5_unit_cands_full_only(self):
        srun = R.rich_run()
        uid = sorted(srun.w.labels)[0]
        srun.w.labels[uid]["cands"] = [["P-0007", 0.8234], ["P-9901", 0.4], ["P-0012", 0.1], ["P-0013", 0.05], ["bad"]]
        srun.write(self.t.paths)
        _inp, m = self.build(srun)
        u = next(x for x in m["units"] if x["unit_id"] == uid)
        self.assertEqual(u["cands"], [["P-0007", 0.823], ["P-9901", 0.4], ["P-0012", 0.1]])
        others = [x["cands"] for x in m["units"] if x["unit_id"] != uid]
        self.assertTrue(others and all(c == [] for c in others))
        red = M.redact_model(m, None, person_dir=srun.person_dir)
        self.assertTrue(all("cands" not in x for x in red["units"]))      # 로컬 전용(가림판·팀에 없음)
        self.assertEqual(M.check_model(m), [])

    def _meet_world(self, proj: str):
        srun = R.rich_run()
        attrib = srun.w.files()["attrib"]
        slots = sorted({int(r["slot"]) for r in attrib if r["target"] == "B_MEET"})
        self.assertTrue(slots, "합성 세계에 미귀속 회의 버킷 슬롯이 있다")
        mt = srun.ev["meets"][0]
        mt["a"], mt["b"] = slots[0] * SLOT, (slots[-1] + 1) * SLOT
        want = F.sec_min(sum(int(r["sec"]) for r in attrib if r["target"] == "B_MEET"))
        srun.write(self.t.paths)
        rows = [{"id": "msg00", "proj": None, "score": 0.0, "top2": []},
                {"id": mt["id"], "proj": proj, "score": 5.0, "top2": [[proj, 5.0]]},
                {"id": "mt_none", "proj": "P-0007", "score": 5.0, "top2": []}]       # 증거에 없는 회의 — 쓰지 않는다
        atomic_write(self.t.paths.analysis_hier_file(srun.run_id, I.TAGS_FILE), b"".join(canon_bytes(r) + b"\n" for r in rows))
        return srun, mt["id"], want

    def test_b6_unattr_meet_min_on_project_node(self):
        base_srun = R.rich_run()
        base_srun.write(self.t.paths)
        _inp0, m0 = self.build(base_srun)
        self.assertNotIn("unattr_meet_min", m0["tree"]["nodes"]["P-0007"])     # 꼬리표가 없으면 주석도 없다
        srun, mid, want = self._meet_world("P-0007")
        inp, m = self.build(srun)
        self.assertEqual(inp.hier["meet_tags"], {mid: "P-0007"})
        node = m["tree"]["nodes"]["P-0007"]
        self.assertEqual(node["unattr_meet_min"], want)
        self.assertGreater(want, 0)
        self.assertEqual(node["min_total"], m0["tree"]["nodes"]["P-0007"]["min_total"])   # MM 미포함 — 과제 투입은 그대로
        self.assertEqual(M.check_model(m), [])
        srun2, _mid, _w = self._meet_world("P-9901")                              # 예약 과제(영역 일반)는 주석 없음
        _inp2, m2 = self.build(srun2)
        self.assertNotIn("unattr_meet_min", m2["tree"]["nodes"]["P-0007"])

    def test_b7_analysis_time_only_outside_model_file(self):
        srun = R.rich_run()
        srun.write(self.t.paths)
        p = self.t.paths
        self.assertEqual(I.analysis_time(p, R.RUN_ID, 540), "2026-10-05T10:15:00+09:00")    # current.json(같은 실행)
        self.assertIsNone(I.analysis_time(p, R.RUN_ID2, 540))
        atomic_write(p.run_status_file(R.RUN_ID), canon_bytes({"schema": "lm27.runstatus/1", "run_id": R.RUN_ID,
                                                               "started": "2026-10-05T01:00:00Z",
                                                               "ended": "2026-10-05T01:20:30Z"}))
        self.assertEqual(I.analysis_time(p, R.RUN_ID, 540), "2026-10-05T10:20:30+09:00")    # run_status 끝(근무 시간대)
        out = os.path.join(self.t.root, "exp")
        res = EX.export(R.RUN_ID, ["html", "json"], ["full", "redacted"], out, paths=p, cfg=self.cfg,
                        inputs=srun.inputs(p, self.cfg), now=NOW, fallback=no_fallback)
        self.assertEqual(res.rc, 0, res.failed)
        for name in ("report_full.html", "report_redacted.html"):
            with open(os.path.join(out, name), encoding="utf-8") as fh:
                html = fh.read()
            isl = re.search(r'<script type="application/json" id="lm27-data">(.*?)</script>', html, re.S).group(1)
            self.assertEqual(json.loads(isl)["run"]["built_at"], "2026-10-05T10:20:30+09:00", name)
        with open(os.path.join(out, "report_model.json"), "rb") as fh:
            self.assertNotIn(b"built_at", fh.read())                              # 모델 바이트는 그대로(G-R1)
        with open(p.analysis_report_file(R.RUN_ID, "report_model.json"), "rb") as fh:
            self.assertNotIn(b"built_at", fh.read())


if __name__ == "__main__":
    unittest.main()
