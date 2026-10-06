# -*- coding: utf-8 -*-
"""WP-30 과정 마이닝(R §4.2 · §4.3 · §6.3.3 · RPT-15 · RPT-16 · RPT-17 · RPT-19).

- RPT-15: R §4.2.3 골든(과제A · 회로 · 해석/분석, 단위업무 4개) — 단계 5개(순서·n·중앙 소요 210·105·60), 전이 6개(되돌림 3→2),
  대기 병목 3(720분), 작업 병목 2(0.56), 버린 Run 2개(COMM 5분·DOC_PPT 8분).
- RPT-16 표본 부족 · RPT-17 단계 상한(REQ_IN·REPORT_OUT 은 늘 남김) · RPT-19 과제 인계(via doc, 근무일 1).
- 라벨 반영(R §4.10.2): 같은 구성의 답 = 그 출처, 구성이 바뀐 옛 답 = 같은 단계 코드 라벨 + rule_pending, 없으면 규칙.
"""
from __future__ import annotations

import json
import os
import unittest

from lm27.report.analysis import mining as M
from tests.fixtures.wp30 import world as W


def golden():
    with open(os.path.join(W.ROOT, "tests", "fixtures", "wp30", "golden_report.json"), encoding="utf-8") as f:
        return json.load(f)


def mine(ctx, **kw):
    return M.mine_role(list(ctx.units.values()), ctx.log, ctx.cfg, bc=ctx.bc, as_of_min=ctx.as_of_min, **kw)


class GoldenRoleTest(unittest.TestCase):
    """RPT-15 — 시제품 `mine_role_A` 와 같은 결과."""

    @classmethod
    def setUpClass(cls):
        cls.ctx = W.golden_role_a().context()
        cls.rw = mine(cls.ctx)
        cls.g = golden()["mine_role_A"]

    def test_steps(self):
        got = [(s["no"], s["code"], s["name"], s["kind"], s["n"], s["median_min"], s["wait_in_median_min"])
               for s in self.rw["steps"]]
        exp = [(s["no"], s["type"], s["name"], s["kind"], s["n"], s["median_min"], s["wait_in_median_min"])
               for s in self.g["steps"]]
        self.assertEqual(got, exp)
        self.assertEqual([s["work_share"] for s in self.rw["steps"]],
                         [s.get("work_share") for s in self.g["steps"]])

    def test_edges_bottlenecks(self):
        self.assertEqual(self.rw["edges"], self.g["edges"])
        self.assertEqual(self.rw["rework"], self.g["rework_edges"])
        self.assertEqual(self.rw["bottlenecks"], self.g["bottlenecks"])
        self.assertEqual(self.rw["dropped"], [])
        self.assertEqual(self.rw["support_threshold"], self.g["support_threshold"])
        self.assertEqual(self.rw["traces"], self.g["traces"])
        self.assertEqual(self.rw["units_n"], 4)
        self.assertEqual(self.rw["sample"], "ok")
        self.assertEqual(self.rw["short_runs_n"], 2)                       # COMM 5분 · DOC_PPT 8분
        self.assertEqual(self.rw["rework_units"], [[3, 2, 1]])

    def test_stats(self):
        st = {s["code"]: s for s in self.rw["steps"]}
        self.assertEqual(st["DOC_XLS"]["p75_min"], 120)                   # 최근순위 75 백분위(120·180·90·90 → 120)
        self.assertEqual(st["APP_CAE"]["p75_min"], 240)
        self.assertEqual(st["APP_CAE"]["obs_share"], 1.0)
        self.assertIsNone(st["REQ_IN"]["obs_share"])
        self.assertEqual(st["APP_CAE"]["freq_month"], 5.0)
        self.assertEqual(self.rw["lead_biz_median_min"], 2830)            # 1770·3420·2360·3300
        self.assertEqual(self.rw["done_ratio"], 1.0)
        self.assertEqual(self.rw["effort_min"], sum(u.effort_min for u in self.ctx.units.values()))

    def test_sentences(self):
        """R §6.3.3 규칙 문장 — 작업 병목 · 대기 병목(앞 단계 = 들어오는 전이 중 최다) · 되돌림."""
        s = M.role_sentences(self.rw)
        self.assertEqual(s[0], "해석 프로그램 작업이 이 역할 투입의 56%로 가장 큽니다.")
        self.assertEqual(s[1], "해석 프로그램을 마치고 표 계산을 시작하기까지 보통 1.5영업일을 기다립니다.")
        self.assertEqual(s[2], "1건의 단위업무에서 표 계산을 하다가 해석 프로그램으로 되돌아갔습니다.")
        self.assertEqual(len(s), 3)

    def test_max_edges(self):
        rw = mine(self.ctx.__class__(**{**self.ctx.__dict__, "cfg": W.cfg(**{"report.mining.maxEdges": 2})}))
        self.assertEqual(rw["edges"], self.g["edges"][:2])
        self.assertEqual(rw["edges_rest"], self.g["edges"][2:])
        self.assertEqual(rw["rework"], [[3, 2, 1]])                        # 그리지 않는 간선도 되돌림 표에는

    def test_deterministic(self):
        self.assertEqual(json.dumps(mine(self.ctx), sort_keys=True, ensure_ascii=False),
                         json.dumps(self.rw, sort_keys=True, ensure_ascii=False))


class SampleAndCapTest(unittest.TestCase):
    def test_thin(self):
        """RPT-16 — 같은 역할 단위업무 2개: sample thin · 병목 없음 · 표본 문장."""
        w = W.golden_role_a()
        for k in ("u_a3", "u_a4"):
            w.tasks.pop(k)
            w.labels.pop(k)
            for s in list(w.slots):
                w.slots[s].pop(k, None)
        rw = mine(w.context())
        self.assertEqual(rw["sample"], "thin")
        self.assertEqual(rw["bottlenecks"], [])
        self.assertIn("단위업무가 2건뿐이라 병목은 판단하지 않았습니다.", M.role_sentences(rw))

    def test_step_cap(self):
        """RPT-17 — 단계 유형 11개(모두 지지도 충족): REQ_IN·REPORT_OUT 포함 8개 남기고 나머지 dropped."""
        w = W.World("2026-09-01", "2026-09-30", "2026-09-30T18:00")
        codes = ["DOC_DOC", "DOC_PPT", "DOC_XLS", "DOC_PDF", "APP_CAD", "APP_CAE", "APP_SIM", "APP_EDA", "MEET"]
        for i, day in enumerate(("2026-09-01", "2026-09-08", "2026-09-15")):
            uid = f"u_c{i}"
            w.unit(uid, start=(day, "08:00"), end=(day, "20:00"))
            for j, code in enumerate(codes):
                h = 8 + j
                w.run(uid, code, day, f"{h:02d}:00", f"{h:02d}:{20 + j:02d}", level="L2회의" if code == "MEET" else "L3PC")
        rw = mine(w.context())
        kept = [s["code"] for s in rw["steps"]]
        self.assertEqual(len(kept), 8)
        self.assertIn("REQ_IN", kept)
        self.assertIn("REPORT_OUT", kept)
        self.assertEqual(len(rw["dropped"]), 3)
        self.assertEqual({d["code"] for d in rw["dropped"]} | set(kept), set(codes) | {"REQ_IN", "REPORT_OUT"})
        self.assertTrue(all(d["n"] == 3 for d in rw["dropped"]))
        # 남긴 구간 단계 = 총 초가 큰 것(긴 Run 일수록 먼저)
        self.assertNotIn("DOC_DOC", kept)


class LabelTest(unittest.TestCase):
    def setUp(self):
        self.ctx = W.golden_role_a().context()
        self.rw = mine(self.ctx)
        self.roles = {self.rw["role_id"]: self.rw}
        self.key = "ws:" + self.rw["role_id"]

    def test_fresh_answer(self):
        ans = {"role": "해석 담당", "summary": "의뢰를 받아 해석하고 표로 정리합니다.",
               "steps": [{"s": f"S{s['no']}", "type": s["code"], "label": f"라벨{s['no']}", "desc": "설명"}
                         for s in self.rw["steps"]]}
        cnt = M.apply_labels(self.roles, {self.key: (ans, "ai")})
        self.assertEqual(cnt, {"ai": 5})
        self.assertEqual([s["label"] for s in self.rw["steps"]], [f"라벨{i}" for i in range(1, 6)])
        self.assertEqual(self.rw["ai_role"], "해석 담당")
        self.assertEqual(self.rw["ai_by"], "ai")

    def test_stale_answer_by_code(self):
        """번호가 바뀐 옛 답 → 같은 단계 코드의 라벨 + rule_pending(R §4.10.2)."""
        ans = {"role": "해석", "summary": "요약", "steps": [
            {"s": "S1", "type": "REQ_IN", "label": "접수", "desc": ""},
            {"s": "S2", "type": "DOC_XLS", "label": "결과 정리", "desc": ""}]}
        M.apply_labels(self.roles, {self.key: (ans, "manual")})
        st = {s["code"]: s for s in self.rw["steps"]}
        self.assertEqual((st["DOC_XLS"]["label"], st["DOC_XLS"]["label_by"]), ("결과 정리", "rule_pending"))
        self.assertEqual((st["REQ_IN"]["label"], st["REQ_IN"]["label_by"]), ("접수", "rule_pending"))
        self.assertEqual((st["MEET"]["label"], st["MEET"]["label_by"]), ("회의", "rule"))
        self.assertEqual(self.rw["ai_by"], "rule_pending")

    def test_no_answer(self):
        M.apply_labels(self.roles, {})
        self.assertTrue(all(s["label_by"] == "rule" and s["label"] == s["name"] for s in self.rw["steps"]))
        self.assertEqual((self.rw["ai_role"], self.rw["ai_by"]), ("", "rule"))


class LevelsTest(unittest.TestCase):
    def test_unit_workflow(self):
        ctx = W.golden_role_a().context()
        uw = M.unit_workflow(ctx.units["u_a1"], ctx.log, ctx.bc, as_of_min=ctx.as_of_min)
        self.assertEqual(uw["lanes"], ["소통", "회의", "문서", "공학"])
        self.assertEqual(len(uw["runs"]), 5)                                 # 10분 미만 Run 도 근거로 보존
        self.assertEqual(uw["steps"], ["REQ_IN", "APP_CAE", "DOC_XLS", "MEET", "REPORT_OUT"])
        self.assertEqual(uw["step_min"]["APP_CAE"], 240)
        self.assertEqual(uw["boundaries"][0]["code"], "S1")
        self.assertEqual(uw["boundaries"][0]["grade_part"], "A")
        self.assertFalse(uw["boundaries"][1]["estimated"])
        self.assertEqual(uw["longest_wait"]["biz_min"], max(w["biz_min"] for w in uw["waits"]))
        self.assertLessEqual(uw["explained_ratio"], 1.0)
        self.assertEqual(uw["cycles"][0]["s"], "2026-09-01T09:30")

    def test_handoff_rpt19(self):
        """RPT-19 — u_a2(해석, 09-16 끝) → u_b1(설계, 09-17 시작, 문서군 f3 공유): 인계 1건 via doc, 근무일 1."""
        w = W.golden_role_a()
        w.unit("u_b1", func="DESIGN", start=("2026-09-17", "09:00"), end=("2026-09-22", "17:00"), docs=["f3"])
        w.run("u_b1", "APP_EDA", "2026-09-17", "10:00", "12:00", app="eda_x", fam="f3")
        w.tasks["u_a2"]["docs"] = {"f3": {"n": 2, "ops": {"save": 2, "export": 0, "attach": 0}}}
        ctx = w.context()
        wf, _tr = M.workflows(ctx)
        pw = wf["projects"]["P-0007"]
        self.assertEqual(len(pw["handoffs"]), 1)
        h = pw["handoffs"][0]
        self.assertEqual((h["from_role"], h["to_role"], h["n"]), (W.role_id("P-0007", "ELEC", "ANALYSIS"),
                                                                  W.role_id("P-0007", "ELEC", "DESIGN"), 1))
        self.assertEqual(h["via"], {"doc": 1, "peer": 0})
        self.assertEqual(h["pairs"][0][:2], ["u_a2", "u_b1"])
        self.assertEqual(ctx.bc.wd_between("2026-09-16", "2026-09-17"), 1)
        self.assertEqual(h["gap_biz_median_min"], 360)
        self.assertEqual([r["role_id"] for r in pw["roles"]][0], W.role_id("P-0007", "ELEC", "ANALYSIS"))

    def test_domain_and_person(self):
        ctx = W.golden_role_a().context()
        wf, _tr = M.workflows(ctx)
        d = wf["domains"]["DEV"]
        self.assertEqual(d["units_n"], 4)
        self.assertEqual([(p["key"], p["effort_min"]) for p in d["projects"]], [("P-0007", d["effort_min"])])
        self.assertEqual(d["projects"][0]["class_mix"], d["class_mix"])           # 과제 하나 = 영역 전체(CH-P10)
        self.assertEqual(list(d["class_mix"]), ["소통", "회의", "문서", "공학"])   # 묶음 고정 순서
        self.assertEqual(d["class_mix"]["공학"], 960)
        self.assertGreaterEqual(sum(d["class_mix"].values()) + d["none_min"], d["effort_min"])
        eff = wf["roles"][W.role_id("P-0007", "ELEC", "ANALYSIS")]["effort_min"]
        # 대기 병목은 값(분), 작업 병목은 비중 × 역할 투입(분)으로 같은 축에서 견준다(R §4.3.3)
        self.assertEqual([(b["kind"], b["score_min"]) for b in d["top_bottlenecks"]],
                         sorted([("work", int(0.56 * eff + 0.5)), ("wait", 720)], key=lambda x: -x[1]))
        self.assertEqual(wf["person"]["code"], "ALL")
        self.assertEqual(set(wf["units"]), set(ctx.units))
        self.assertEqual(list(wf["roles"]), [W.role_id("P-0007", "ELEC", "ANALYSIS")])


if __name__ == "__main__":
    unittest.main()
