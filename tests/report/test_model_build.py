# -*- coding: utf-8 -*-
"""WP-31 `build_report` · `load_model` · `model_status`(R §2.4 · §11 · 계약 §7.1 · §8.3 · G-R1 · RPT-01 · RPT-02 · RPT-05).

- rc: 0 만듦 · 4 다이제스트·판·읽은 설정 값이 같음(건너뜀) · 2 입력 일부 없음(만들되 경고) · 1 시간 결과 없음·등식 실패(이전 유지).
- `model_meta.json` = {report_version, inputs{논리 이름: sha16|missing}, cfg_used, built_at} — 모델 안에는 built_at 이 없다.
- 결정성: 같은 입력이면 모델 바이트가 같고(G-R1), 행 순서·사람 사전 키 순서를 섞어도 같다(RPT-02).
"""
from __future__ import annotations

import json
import os
import random
import unittest
from datetime import UTC, datetime

import lm27.report as RP
from lm27.report import model as M
from lm27.util import fsx
from tests.fixtures.wp30 import world as W
from tests.fixtures.wp31 import runs as R


def no_fallback(*_a):
    return None


NOW = datetime(2026, 10, 5, 1, 21, 44, tzinfo=UTC)


class BuildReportTest(unittest.TestCase):
    def setUp(self):
        self.t = R.TmpRoot()
        self.addCleanup(self.t.cleanup)
        self.cfg = W.cfg()
        self.srun = R.rich_run()
        self.srun.write(self.t.paths)

    def build(self, **kw):
        args = {"paths": self.t.paths, "cfg": self.cfg, "inputs": self.srun.inputs(self.t.paths, self.cfg),
                "fallback": no_fallback, "now": NOW}
        args.update(kw)
        return RP.build_report(R.RUN_ID, **args)

    def model_path(self, name="report_model.json"):
        return self.t.paths.analysis_report_file(R.RUN_ID, name)

    def test_build_skip_force(self):
        r = self.build()
        self.assertEqual(r.rc, 0, r)
        self.assertEqual(r.path, f"data/derived/analysis/{R.RUN_ID}/report/report_model.json")
        self.assertEqual(os.fspath(r), r.path)
        meta = fsx.read_json(self.model_path("model_meta.json"))
        self.assertEqual(meta["report_version"], "report/1")
        self.assertEqual(meta["built_at"], "2026-10-05T10:21:44+09:00")
        self.assertEqual(meta["inputs"]["ai.workflow_label"], "missing")
        self.assertIn("report.export.maxModelMb", meta["cfg_used"])
        self.assertTrue(any(k.startswith("report.mining.") for k in meta["cfg_used"]))
        raw = fsx.read_bytes(self.model_path())
        self.assertNotIn(b"built_at", raw)
        self.assertEqual(meta["model_sha16"], fsx.sha256_hex(raw)[:16])
        r2 = self.build()
        self.assertEqual((r2.rc, r2.skipped), (4, True))
        r3 = self.build(force=True)
        self.assertEqual(r3.rc, 0)
        self.assertEqual(fsx.read_bytes(self.model_path()), raw)       # RPT-01: --force 두 번 = 같은 바이트

    def test_rebuild_on_input_or_cfg_change(self):
        self.assertEqual(self.build().rc, 0)
        cfg2 = self.cfg.derive({"report.mining.minSupportRatio": 0.6})
        self.assertEqual(self.build(cfg=cfg2).rc, 0)                     # 읽은 설정 값이 달라졌다
        self.assertEqual(self.build(cfg=cfg2).rc, 4)
        self.srun.w.labels["u_a1"]["title"] = "전원부 해석 1 수정"
        self.srun.write(self.t.paths)
        r = self.build(cfg=cfg2)
        self.assertEqual(r.rc, 0)
        self.assertEqual(next(u["title"] for u in RP.load_model(R.RUN_ID, paths=self.t.paths)["units"]
                              if u["unit_id"] == "u_a1"), "전원부 해석 1 수정")

    def test_partial_inputs_rc2(self):
        os.remove(self.t.paths.analysis_time_file(R.RUN_ID, "interval_ledger.jsonl"))
        r = self.build()
        self.assertEqual(r.rc, 2)
        self.assertEqual(r.missing, ["time.interval_ledger"])

    def test_refused_keeps_previous(self):
        self.assertEqual(self.build().rc, 0)
        before = fsx.read_bytes(self.model_path())
        os.remove(self.t.paths.analysis_time_file(R.RUN_ID, "team_tables.json"))
        r = self.build()
        self.assertEqual(r.rc, 1)
        self.assertIn("시간 결과", r.message)
        self.assertEqual(fsx.read_bytes(self.model_path()), before)      # 성공 전 무효화 금지

    def test_check_failure_keeps_previous(self):
        self.assertEqual(self.build().rc, 0)
        before = fsx.read_bytes(self.model_path())
        self.srun.tables["alloc_daily"]["rows"].append(["2026-09-01", "u_zzzzzzzzzz", "regular", 5])
        self.srun.write(self.t.paths)
        r = self.build()
        self.assertEqual(r.rc, 1)
        self.assertTrue(r.problems)
        self.assertIn("이전 보고서", r.message)
        self.assertEqual(fsx.read_bytes(self.model_path()), before)

    def test_load_model_and_status(self):
        with self.assertRaises(RP.ModelNotFound):
            RP.load_model(R.RUN_ID, paths=self.t.paths)
        self.assertEqual(RP.model_status(R.RUN_ID, paths=self.t.paths), "missing")
        self.build()
        self.assertEqual(RP.model_status(R.RUN_ID, paths=self.t.paths), "ok")
        full = RP.load_model(R.RUN_ID, paths=self.t.paths)
        self.assertEqual(full["variant"], "full")
        red = RP.load_model(R.RUN_ID, "redacted", paths=self.t.paths, cfg=self.cfg)
        self.assertEqual(red["variant"], "redacted")
        self.assertEqual(M.redaction_violations(red, self.srun.person_dir), [])
        meta_p = self.model_path("model_meta.json")
        meta = fsx.read_json(meta_p)
        meta["report_version"] = "report/0"
        fsx.atomic_write(meta_p, fsx.canon_bytes(meta))
        self.assertEqual(RP.model_status(R.RUN_ID, paths=self.t.paths), "stale")     # RPT-05: 화면이 다시 만든다
        self.assertEqual(self.build().rc, 0)                              # 판이 다르면 건너뛰지 않는다
        with self.assertRaises(ValueError):
            RP.load_model(R.RUN_ID, "team", paths=self.t.paths)

    def test_from_files_without_injection(self):
        """주입 없이 파일만으로(레지스트리·증거는 실제 로더 — 빈 번들)."""
        r = RP.build_report(R.RUN_ID, paths=self.t.paths, cfg=self.cfg, fallback=no_fallback, now=NOW)
        self.assertIn(r.rc, (0, 2))
        m = RP.load_model(R.RUN_ID, paths=self.t.paths)
        codes = {w["code"] for w in m["flags"]["warnings"]}
        self.assertIn("registry_missing", codes)
        self.assertIn("evidence_empty", codes)
        self.assertEqual(M.check_model(m), [])

    def test_export_attribute_is_callable(self):
        """R §2.2 재수출: `lm27.report.export` 는 import 순서와 관계없이 호출할 수 있다(하위 모듈 = 내보내기 함수)."""
        from lm27.report import export as ex
        self.assertTrue(callable(ex))
        self.assertTrue(callable(ex.export))
        self.assertIs(ex, RP.export)


class DeterminismTest(unittest.TestCase):
    """G-R1 · RPT-02: 같은 입력이면 같은 모델 바이트 — attrib·tasks·사람 사전 순서를 섞어도."""

    def model_bytes(self, shuffle_seed=None):
        srun = R.rich_run()
        t = R.TmpRoot()
        try:
            if shuffle_seed is not None:
                rnd = random.Random(shuffle_seed)
                orig_attrib, orig_files = srun.w.attrib_rows, srun.w.files

                def attrib_rows():
                    rows = orig_attrib()
                    rnd.shuffle(rows)
                    return rows

                def files():
                    f = orig_files()
                    rnd.shuffle(f["tasks"])
                    return f
                srun.w.attrib_rows = attrib_rows
                srun.w.files = files
                people = list(srun.person_dir["people"].items())
                rnd.shuffle(people)
                srun.person_dir["people"] = dict(people)
                rnd.shuffle(srun.ev["msgs"])
                rnd.shuffle(srun.ev["docs"])
            srun.write(t.paths)
            cfg = W.cfg()
            m = M.build_model(srun.inputs(t.paths, cfg), cfg, fallback=no_fallback)
            return M.model_bytes(m)
        finally:
            t.cleanup()

    def test_same_bytes(self):
        base = self.model_bytes()
        self.assertEqual(self.model_bytes(), base)
        for seed in (1, 2, 3, 4):
            self.assertEqual(self.model_bytes(seed), base, f"seed {seed}")
        obj = json.loads(base.decode("utf-8"))
        self.assertEqual(M.model_bytes(obj), base)                       # 정규 바이트(키 정렬·구분자)


if __name__ == "__main__":
    unittest.main()
