# -*- coding: utf-8 -*-
"""WP-31 보고서 입력 단일 로더(R §2.5 · 부록 A `load_inputs`, 계약 L-08 · G-R10).

- 필수 시간 결과(env_slots·tasks·team_tables·mm_month·run_meta)가 없으면 `refused`(보고서 거부 — rc 1).
- 날짜 원장·구간 원장·귀속·확인 큐가 없으면 `missing`(만들되 경고 — rc 2), 분류 결과가 없으면 `labels` + 경고.
- 형식이 깨진 파일은 조용히 삼키지 않는다(warnings + 다이제스트 'broken:').
- 분석 하위 경로는 `Paths` 메서드로만(CR) — 없으면 `PathsMethodMissing`.
- 기간: current.json(같은 실행) → 날짜 원장 날짜. 다이제스트는 논리 이름별 sha16·'missing'.
"""
from __future__ import annotations

import os
import unittest

from lm27.paths import Paths
from lm27.report import inputs as I
from lm27.util.fsx import atomic_write
from tests.fixtures.wp30 import world as W
from tests.fixtures.wp31 import runs as R


class InputsTest(unittest.TestCase):
    def setUp(self):
        self.t = R.TmpRoot()
        self.addCleanup(self.t.cleanup)
        self.run = R.rich_run()
        self.cfg = W.cfg()

    def test_full_load(self):
        self.run.write(self.t.paths)
        inp = self.run.inputs(self.t.paths, self.cfg)
        self.assertEqual(inp.refused, [])
        self.assertEqual(inp.missing, [])
        self.assertEqual(inp.period, ("2026-08-01", "2026-10-04"))
        self.assertNotIn("chosen", inp.run)                          # 화면 선택은 모델 입력이 아니다(G-R1 — C01)
        self.assertEqual(I.chosen_of(self.t.paths, R.RUN_ID), "auto")
        self.assertEqual(inp.run["as_of"], "2026-10-04T18:00")
        self.assertEqual(len(inp.time.tasks), len(self.run.w.tasks))
        self.assertIn("u_a1", inp.labels)
        self.assertEqual(inp.hier["proposals"][0]["proposal_id"], "pr_1")
        self.assertEqual(len(inp.hier["queue"]), 1)
        self.assertEqual(I.tz_offset_of(inp, self.cfg), 540)
        for k in ("time.tasks", "time.env_slots", "labels", "person_dir", "registry", "calendar", "evidence"):
            self.assertRegex(inp.digests[k], r"^[0-9a-f]{16}$", k)
        for st in I.AI_STAGES:
            self.assertEqual(inp.digests["ai." + st], I.MISSING)
            self.assertIsNone(inp.ai[st])

    def test_refused_when_required_time_missing(self):
        self.run.write(self.t.paths, skip=("tasks.json",))
        inp = self.run.inputs(self.t.paths, self.cfg)
        self.assertEqual(inp.refused, ["time.tasks"])
        self.assertTrue(any(w["code"] == "time_missing" for w in inp.warnings))
        self.assertEqual(inp.digests["time.tasks"], I.MISSING)
        self.assertEqual(inp.digests["evidence"], I.MISSING)       # 거부되면 증거를 읽지 않는다

    def test_partial_missing(self):
        self.run.write(self.t.paths, skip=("day_ledger.jsonl", "interval_ledger.jsonl", "labels.json"))
        inp = self.run.inputs(self.t.paths, self.cfg)
        self.assertEqual(inp.refused, [])
        self.assertIn("time.day_ledger", inp.missing)
        self.assertIn("time.interval_ledger", inp.missing)
        self.assertIn("labels", inp.missing)
        self.assertTrue(any(w["code"] == "labels_missing" for w in inp.warnings))
        self.assertEqual(inp.period, ("2026-08-01", "2026-10-04"))  # current.json 이 기간을 준다

    def test_broken_file_is_not_swallowed(self):
        self.run.write(self.t.paths)
        atomic_write(self.t.paths.analysis_time_file(self.run.run_id, "mm_month.json"), b'{"a": 1, "a": 2}')
        atomic_write(self.t.paths.analysis_time_file(self.run.run_id, "attrib.jsonl"), b'{"slot": 1}\nnot json\n')
        inp = self.run.inputs(self.t.paths, self.cfg)
        self.assertEqual(inp.refused, ["time.mm_month"])
        self.assertTrue(inp.digests["time.mm_month"].startswith("broken:"))
        codes = {w["code"] for w in inp.warnings}
        self.assertIn("input_broken:time.mm_month", codes)
        self.assertIn("input_broken:time.attrib", codes)
        self.assertIn("time.attrib", inp.missing)

    def test_period_from_ledger_without_current(self):
        self.run.write(self.t.paths, current=False)
        inp = self.run.inputs(self.t.paths, self.cfg)
        self.assertEqual(inp.period, ("2026-08-01", "2026-10-04"))
        self.assertIsNone(I.chosen_of(self.t.paths, R.RUN_ID))
        # 다른 실행을 가리키는 current.json 은 이 실행의 선택 정보가 아니다
        atomic_write(self.t.paths.analysis_current(), b'{"run_id": "20260101-000000-abcd", "from": "2025-01-01", '
                                                       b'"to": "2025-01-31", "chosen": "explicit"}')
        inp = self.run.inputs(self.t.paths, self.cfg)
        self.assertEqual(inp.period, ("2026-08-01", "2026-10-04"))
        self.assertIsNone(I.chosen_of(self.t.paths, R.RUN_ID))

    def test_paths_methods_missing(self):
        """경로 메서드가 없는 경로 객체(옛 판) → PathsMethodMissing(조용히 다른 경로를 조립하지 않는다 — L-08)."""
        class Old(Paths):
            analysis_time_file = None
        with self.assertRaises(I.PathsMethodMissing):
            I.load_inputs(R.RUN_ID, paths=Old(self.t.root, lad=os.path.join(self.t.root, "lad")), cfg=self.cfg,
                          evidence=False)

    def test_real_paths_has_methods_and_same_layout(self):
        """W2 통합: 실제 lm27.paths 에 분석·내보내기 하위 경로 메서드가 있고 시험용 TPaths 와 같은 곳을 가리킨다."""
        real = Paths(self.t.root, lad=os.path.join(self.t.root, "lad"))
        for m in ("analysis_time_file", "analysis_hier_file", "analysis_report_file", "out_personal_file",
                  "run_status_file"):
            self.assertTrue(callable(getattr(real, m, None)), m)
        tp = self.t.paths
        self.assertEqual(real.analysis_hier_file(R.RUN_ID, "labels.json"), tp.analysis_hier_file(R.RUN_ID, "labels.json"))
        self.assertEqual(real.analysis_report_file(R.RUN_ID, "report_model.json"),
                         tp.analysis_report_file(R.RUN_ID, "report_model.json"))
        self.assertEqual(real.out_personal_file("2026-08-01", "2026-10-04", R.RUN_ID, "csv_full/units.csv"),
                         tp.out_personal_file("2026-08-01", "2026-10-04", R.RUN_ID, "csv_full/units.csv"))
        with self.assertRaises(ValueError):
            real.out_personal_file("2026-08-01", "2026-10-04", R.RUN_ID, "../x.csv")

    def test_hier_dir_method_fallback(self):
        """WP-22 의 `analysis_hier(run_id)` 폴더 메서드만 있어도 분류 결과를 읽는다."""
        self.run.write(self.t.paths)

        class P2(Paths):                    # W2 통합: 실제 Paths 에 파일 메서드가 생겼으므로 옛 판을 흉내 내 지운다
            analysis_hier_file = None
            analysis_report_file = None
            analysis_report = None

            def analysis_time_file(self, run_id, name):
                return self.analysis(run_id) / "time" / name

            def analysis_hier(self, run_id):
                return self.analysis(run_id) / "hier"

            def calendar_json(self):
                return R.REPO / "config" / "calendar.json"
        p2 = P2(self.t.root, lad=os.path.join(self.t.root, "lad"))
        inp = I.load_inputs(R.RUN_ID, paths=p2, cfg=self.cfg, evidence=False, registry=R.REGISTRY)
        self.assertIn("u_a1", inp.labels)
        with self.assertRaises(I.PathsMethodMissing):
            I.report_file(p2, R.RUN_ID, "report_model.json")

    def test_evidence_injection_and_off(self):
        self.run.write(self.t.paths)
        inp = self.run.inputs(self.t.paths, self.cfg, evidence=False)
        self.assertIsNone(inp.evidence)
        self.assertEqual(inp.digests["evidence"], I.MISSING)
        inp = self.run.inputs(self.t.paths, self.cfg)
        self.assertTrue(inp.evidence.usable)
        self.assertEqual(inp.evidence.fam_names[R.fam_of("f2")], "전원부_검증결과.xlsx")
        d1 = inp.digests["evidence"]
        ev = self.run.evidence()
        ev.msgs = list(reversed(ev.msgs))
        inp2 = self.run.inputs(self.t.paths, self.cfg, evidence=ev)
        self.assertEqual(inp2.digests["evidence"], d1)             # 순서와 무관(G-R1)

    def test_real_loaders_on_empty_bundle(self):
        """번들이 없는 트리: 내장 레지스트리 + 근거 없음 경고 — 예외 없이 계속(R §2.5 '없을 때')."""
        self.run.write(self.t.paths)
        inp = I.load_inputs(R.RUN_ID, paths=self.t.paths, cfg=self.cfg)
        codes = {w["code"] for w in inp.warnings}
        self.assertIn("registry_missing", codes)
        self.assertIn("evidence_empty", codes)
        self.assertIsNone(inp.evidence)
        self.assertEqual(inp.registry_status["source"], "builtin")

    def test_outbox_meta_listing(self):
        self.run.write(self.t.paths)
        atomic_write(self.t.paths.outbox_file("pending", "lm27_team_bundle_2026-09_0123456789ab.meta.json"),
                     b'{"state": "pending", "attempts": 0}')
        inp = self.run.inputs(self.t.paths, self.cfg)
        self.assertEqual([o["name"] for o in inp.outbox], ["lm27_team_bundle_2026-09_0123456789ab"])
        self.assertNotIn("outbox", inp.digests)                   # 화면용 — 모델·다이제스트 밖(RP14)

    def test_bad_run_id(self):
        with self.assertRaises(ValueError):
            I.load_inputs("../x", paths=self.t.paths, cfg=self.cfg)

    def test_evidence_from_time_core_shape(self):
        """시간 코어 Evidence(Msg·Meet·DocE 속성 객체) → 보고서 증거 보기: 제목은 적재 행의 정제 열만."""
        from types import SimpleNamespace as NS
        ev = NS(msgs=[NS(id="r1", t=W.lsec("2026-09-01", "09:30"), dir="in", conv="t1", peer=R.KIM, prec="minute",
                         ch="mail", key="m" + "0" * 24, flags=frozenset())],
                meets=[NS(id="r2", a=W.lsec("2026-09-02", "10:00"), key="e" + "1" * 24, n_att=4, attendees=(R.KIM,))],
                docs=[NS(id="r3", t=W.lsec("2026-09-03", "11:00"), fam=R.fam_of("x"), kind="save", raw="사양서.docx")],
                fam_names={R.fam_of("x"): "사양서"}, leaves={W.as_of_dt("2026-09-04T00:00").date(): "full"},
                manual=[NS(kind="absence", d=W.as_of_dt("2026-09-05T00:00").date())])
        rows = [{"id": "r1", "kind": "mail", "subject_masked": "[과제:P-0007]  검증   요청"},
                {"id": "r2", "kind": "cal", "subject_masked": "주간 검토"}]
        idx = I.evidence_from(ev, rows)
        self.assertEqual(idx.lines["r1"]["title"], "[과제:P-0007] 검증 요청")
        self.assertEqual(idx.lines["r1"]["t"], "2026-09-01 09:30")
        self.assertEqual(idx.lines["r2"]["kind"], "meeting")
        self.assertEqual(idx.lines["r3"]["title"], "사양서.docx")
        self.assertEqual(idx.leaves, {"2026-09-04": "full"})
        self.assertEqual(idx.absences, ["2026-09-05"])
        self.assertTrue(idx.usable)


if __name__ == "__main__":
    unittest.main()
