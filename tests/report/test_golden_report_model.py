# -*- coding: utf-8 -*-
"""WP-31 골든 — 보고서 모델에 실린 분석층 골든(R §4.2.3 · 부록 B `golden_report.json` — WP-30 사본, 읽기만)과 R §9.2.1 모양.

과제A · 회로 · 해석/분석(홍길동) 단위업무 4개(시제품 `mine_role_A`): 단계 5개(REQ_IN·APP_CAE·DOC_XLS·MEET·REPORT_OUT),
중앙 소요 210·105·60, 대기 병목 3(720분) · 작업 병목 2(0.56), 되돌림 3→2. 모델은 키를 정수 참조로 바꿔 실을 뿐 분석 수치를
바꾸지 않는다. 달·단위업무 분은 슬롯 합으로 손으로 셈한 값(9월 봉투 1575분 = u_a1 425 + u_a2 540 + u_a3 340 + u_a4 270).
"""
from __future__ import annotations

import json
import unittest

from lm27.report import model as M
from tests.fixtures.wp30 import world as W
from tests.fixtures.wp31 import runs as R

GOLDEN = R.REPO / "tests" / "fixtures" / "wp30" / "golden_report.json"


def no_fallback(*_a):
    return None


class GoldenModelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.t = R.TmpRoot()
        cls.addClassCleanup(cls.t.cleanup)          # setUpClass 가 중간에 실패해도 임시 ROOT 를 지운다(W2 검토 L12)
        cls.srun = R.golden_run()
        cls.srun.write(cls.t.paths)
        cfg = W.cfg()
        cls.m = M.build_model(cls.srun.inputs(cls.t.paths, cfg), cfg, fallback=no_fallback)
        with open(GOLDEN, encoding="utf-8") as fh:
            cls.g = json.load(fh)["mine_role_A"]

    def role(self):
        rid = next(u["role_id"] for u in self.m["units"] if u["unit_id"] == "u_a1")
        return self.m["workflows"]["roles"][rid]

    def test_mining_golden(self):
        rw, g = self.role(), self.g
        self.assertEqual([s["code"] for s in rw["steps"]], [s["type"] for s in g["steps"]])
        self.assertEqual([s["n"] for s in rw["steps"]], [s["n"] for s in g["steps"]])
        self.assertEqual([s["median_min"] for s in rw["steps"]], [s["median_min"] for s in g["steps"]])
        self.assertEqual([s["wait_in_median_min"] for s in rw["steps"]], [s["wait_in_median_min"] for s in g["steps"]])
        self.assertEqual([s.get("work_share") for s in rw["steps"]], [s.get("work_share") for s in g["steps"]])
        self.assertEqual(rw["edges"], g["edges"])
        self.assertEqual(rw["rework"], g["rework_edges"])
        self.assertEqual(rw["bottlenecks"], g["bottlenecks"])
        self.assertEqual(rw["support_threshold"], g["support_threshold"])
        self.assertEqual(rw["traces"], g["traces"])
        self.assertEqual(rw["dropped"], g["dropped"])
        self.assertEqual(rw["short_runs_n"], 2)                         # 버린 짧은 Run — COMM 5분·DOC_PPT 8분(RPT-15)
        self.assertEqual(rw["sentences"][0], "해석 프로그램 작업이 이 역할 투입의 56%로 가장 큽니다.")

    def test_minutes_golden(self):
        sep = next(x for x in self.m["months"] if x["m"] == "2026-09")
        self.assertEqual(sep["env_min"], 1575)
        self.assertEqual(sep["attributed_min"], 1573)
        self.assertEqual(sep["unattr_min"], 2)                          # DOC_PPT 꼬리 슬롯의 남은 2분
        self.assertEqual(sep["buckets"], {"B_GENERIC": 0, "B_COMM": 0, "B_MEET": 0, "B_OFFPC": 0, "B_UNKNOWN": 2})
        eff = {u["unit_id"]: u["effort_min"] for u in self.m["units"]}
        self.assertEqual(eff, {"u_a1": 425, "u_a2": 540, "u_a3": 338, "u_a4": 270})
        oct_ = next(x for x in self.m["months"] if x["m"] == "2026-10")
        self.assertEqual((oct_["env_min"], oct_["partial"]["to"]), (0, "2026-10-04"))
        self.assertEqual(M.check_model(self.m), [])

    def test_r921_shape(self):
        """R §9.2.1 의 키가 다 있다(값은 합성)."""
        m = self.m
        self.assertTrue({"m", "workdays", "covered_workdays", "denom_min", "partial", "env_min", "by_tag", "attributed_min",
                         "unattr_min", "buckets", "obs_min", "est_min", "conf_min", "avail_days", "avail_min",
                         "absence_days", "load_pct", "overtime_window_min", "overtime_daily8h_min", "holiday_night_min",
                         "on_leave_min", "units", "quality"} <= set(m["months"][0]))
        self.assertTrue({"d", "hol", "by_tag", "env_min", "conf_min", "obs_min", "est_min", "unattr_min", "leave",
                         "flags"} <= set(m["days"][0]))
        self.assertTrue({"unit_id", "title", "title_by", "role_id", "project_key", "domain", "field", "function",
                         "activity_type", "stance", "ax_link", "label_level", "kind", "cycles", "start", "end", "grade",
                         "status", "lead_min", "biz_lead_min", "effort_min", "obs_min", "est_min", "levels_min",
                         "parallel", "machine_min", "pre_request_min", "flags", "first_evidence", "last_evidence",
                         "spans", "density", "by_month", "by_tag", "steps", "step_min", "peers", "apps",
                         "apps_unknown_min", "docs", "queue"} <= set(m["units"][0]))
        self.assertTrue({"key", "project_id", "proposal_id", "label", "label_src", "domain", "mask_name",
                         "merged_from"} <= set(m["projects"][0]))
        self.assertTrue({"role_id", "project_key", "field", "field_name", "function", "function_name",
                         "label"} <= set(m["roles"][0]))
        self.assertEqual(set(m["workflows"]), {"roles", "units", "projects", "domains", "person"})
        self.assertEqual(set(m["reviews"]), {"weeks", "months"})
        self.assertTrue({"internal", "external"} <= set(m["peers"]))
        self.assertTrue({"center", "nodes", "edges", "recs", "related_projects"} <= set(m["ontology"]))
        self.assertTrue({"catalog_version", "catalog_n", "items", "matches", "needs"} <= set(m["agentic"]))
        self.assertTrue({"grade", "reasons", "by_month"} <= set(m["quality"]))
        self.assertEqual(set(m["refs"]), {"people", "docs", "apps"})


class SampleSeamTest(unittest.TestCase):
    """이음매 견본(`tests\\fixtures\\wp31\\sample_*.json` — WP-34·35·36 의 고정 모델 파일)이 지금 코드의 모델 모양과 같다.
    값이 아니라 구조 지문(키 경로 집합)을 비교한다 — 모양을 바꾸면 `runs.write_samples()` 로 견본을 다시 쓰고 소비 WP 에 알린다."""

    def test_samples_in_sync(self):
        now = R.sample_objects()
        for name in R.SAMPLE_FILES:
            with open(R.SAMPLE_DIR / name, encoding="utf-8") as fh:
                committed = json.load(fh)
            self.assertEqual(sorted(R.shape(now[name]) ^ R.shape(committed)), [], name)
        with open(R.SAMPLE_DIR / "sample_model.json", encoding="utf-8") as fh:
            full = json.load(fh)
        self.assertEqual(M.check_model(full), [])
        with open(R.SAMPLE_DIR / "sample_model_redacted.json", encoding="utf-8") as fh:
            red = json.load(fh)
        self.assertEqual(red["variant"], "redacted")
        self.assertEqual(M.redaction_violations(red, R.PERSON_DIR), [])


if __name__ == "__main__":
    unittest.main()
