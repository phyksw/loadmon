# -*- coding: utf-8 -*-
"""WP-30 활동 로그·분석 문맥(R §4.1 · §3.4 · RPT-18).

- 구간 단계 = 같은 obs 의 연속 슬롯(C21 — obs 는 단계 코드 문자열), 점 단계 = 차수 근거 코드(추정 경계는 점이 아님).
- obs 열이 없는 구판: L1 → OFFLINE · L2 → MEET · L4 → COMM, L3 는 단계 없음 + `mining_coarse`(RPT-18).
- O/I 나누기: (날짜, 업무, 꼬리표) 칸마다 최대잉여, 동률 O 먼저, obs + est = alloc(모델 등식).
- 단위업무 보기: 영업 리드(R §3.2) · 투입 = Σ alloc · 라벨 없음 = UNC · 제안 과제 자리.
"""
from __future__ import annotations

import unittest
from datetime import date

from lm27.report.analysis import activity as A
from tests.fixtures.wp30 import world as W


class BuildActivityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.w = W.golden_role_a()
        cls.ctx = cls.w.context()

    def test_runs_and_milestones(self):
        log = self.ctx.log
        u1 = log["u_a1"]
        kinds = [(x.kind, x.type) for x in u1]
        self.assertEqual(kinds, [("M", "REQ_IN"), ("A", "APP_CAE"), ("A", "APP_CAE"), ("A", "COMM"), ("A", "DOC_XLS"),
                                 ("A", "MEET"), ("M", "REPORT_OUT")])
        cae = u1[1]
        self.assertEqual((cae.a, cae.b), (W.lmin("2026-09-01", "10:00"), W.lmin("2026-09-01", "12:00")))
        self.assertEqual((cae.sec, cae.obs_sec, cae.minutes), (7200, 7200, 120))
        self.assertEqual(cae.apps, (("cae_x", 7200),))
        self.assertEqual(cae.fams, (("f1", 7200),))
        self.assertEqual(cae.levels, frozenset({"L3PC"}))
        self.assertEqual(u1[3].sec, 300)                       # COMM 5분 — 정리에서 버려질 짧은 Run
        meet = u1[5]
        self.assertEqual(meet.obs_sec, meet.sec)               # L2회의(전체) = O
        self.assertEqual(u1[0].t, W.lmin("2026-09-01", "09:30"))
        self.assertEqual(u1[-1].t, W.lmin("2026-09-04", "16:00"))
        self.assertFalse(self.ctx.log.coarse)

    def test_short_tail_slot(self):
        ppt = [x for x in self.ctx.log["u_a3"] if x.type == "DOC_PPT"][0]
        self.assertEqual(ppt.sec, 480)                          # 8분(300 + 180)
        self.assertEqual((ppt.a, ppt.b), (W.lmin("2026-09-17", "09:00"), W.lmin("2026-09-17", "09:10")))

    def test_boundary_codes(self):
        w = W.World("2026-09-01", "2026-09-30", "2026-09-30T18:00")
        w.unit("u_x1", cycles=[(("2026-09-01", "09:00"), "S1d", ("2026-09-03", "18:00"), "E1d")])
        w.unit("u_x2", kind="COORD", cycles=[(("2026-09-02", "10:00"), "S1o", ("2026-09-04", "11:00"), "E1i")])
        w.unit("u_x3", kind="MANUAL", cycles=[(("2026-09-07", "09:00"), "S2M", ("2026-09-08", "17:00"), "E3M")])
        w.unit("u_x4", kind="ACK", cycles=[(("2026-09-09", "09:00"), "S2a", ("2026-09-10", "17:00"), "E2h")])
        w.unit("u_x5", kind="SELF", cycles=[(("2026-09-11", "09:00"), "S2p", ("2026-09-14", "17:00"), "E3i")])
        w.unit("u_x6", start=("2026-09-15", "09:00"), end=("2026-09-18", "12:00"), flags=["수락 09-15 09:40"])
        w.tasks["u_x6"]["cycles"][0]["interim"] = [[W.lsec("2026-09-16", "15:00"), "E1p"]]
        log = A.build_activity(w.files()["tasks"], [])
        got = {u: [(m.type, sorted(m.flags)) for m in log[u]] for u in log}
        self.assertEqual(got["u_x1"], [("REQ_IN", ["date_only"]), ("REPORT_OUT", ["date_only"])])
        self.assertEqual(got["u_x2"], [("REQ_OUT", []), ("REPORT_IN", [])])
        self.assertEqual(got["u_x3"], [("REQ_IN", ["offline"]), ("REPORT_OUT", ["offline"])])
        self.assertEqual(got["u_x4"], [("ACK_OUT", [])])                   # E2h 는 점이 아님
        self.assertNotIn("u_x5", log)                                     # S2p·E3i 추정 경계는 점이 아님
        self.assertEqual(got["u_x6"], [("REQ_IN", []), ("ACK_OUT", []), ("REPORT_OUT", ["interim"]), ("REPORT_OUT", [])])
        ack = [m for m in log["u_x6"] if m.type == "ACK_OUT"][0]
        self.assertEqual(ack.t, W.lmin("2026-09-15", "09:40"))

    def test_coarse_old_core(self):
        """RPT-18 — attrib 에 obs 열이 없으면 L1·L2·L4 만 거친 단계, L3 는 단계 없음, 경고 mining_coarse."""
        w = W.golden_role_a()
        f = w.files()
        rows = [{k: v for k, v in r.items() if k != "obs"} for r in f["attrib"]]
        for r in rows:
            if r["target"] == "u_a2" and r["level"] == "L3PC":
                r["level"] = "L4앵커"
        log = A.build_activity(f["tasks"], rows)
        self.assertTrue(log.coarse)
        types = {x.type for xs in log.values() for x in xs if x.kind == "A"}
        self.assertEqual(types, {"MEET", "COMM"})
        ctx = w.context(attrib=rows)
        self.assertIn("mining_coarse", [x["code"] for x in ctx.warnings])
        from lm27.report.analysis import quality
        q = quality.quality_layer(ctx)
        self.assertIn("mining_coarse", q["reasons"])
        q2 = quality.quality_layer(w.context())
        self.assertEqual(q["by_month"], q2["by_month"])           # 등급에는 영향 없음 — 표시만


class ObsSplitTest(unittest.TestCase):
    def test_tie_and_sum(self):
        s0 = W.lsec("2026-09-01", "10:00") // 300
        rows = [{"slot": s0, "target": "u_1", "sec": 300, "level": "L3PC"},
                {"slot": s0 + 1, "target": "u_1", "sec": 300, "level": "L4앵커"},
                {"slot": s0, "target": "B_COMM", "sec": 0, "level": "L3PC"}]
        tags = {s0: "regular", s0 + 1: "regular"}
        out = A.obs_split({("2026-09-01", "u_1", "regular"): 10}, rows, tags)
        self.assertEqual(out[("2026-09-01", "u_1", "regular")], (5, 5))
        out = A.obs_split({("2026-09-01", "u_1", "regular"): 1}, rows, tags)
        self.assertEqual(out[("2026-09-01", "u_1", "regular")], (1, 0))          # 동률 O 먼저
        out = A.obs_split({("2026-09-02", "u_9", "regular"): 7}, rows, tags)
        self.assertEqual(out[("2026-09-02", "u_9", "regular")], (0, 7))          # 귀속 행 없음 → 추정
        out = A.obs_split({("2026-09-01", "u_1", "extended"): 3}, rows, {})       # 꼬리표 모름 → 날짜 전체 가중
        self.assertEqual(sum(out[("2026-09-01", "u_1", "extended")]), 3)

    def test_unit_identity(self):
        ctx = W.golden_role_a().context()
        for u in ctx.units.values():
            self.assertEqual(u.obs_min + u.est_min, u.effort_min, u.unit_id)
            self.assertEqual(sum(u.by_date.values()), u.effort_min)
            dens = ctx.density(u.unit_id)
            self.assertEqual(sum(w["obs"] + w["est"] for w in dens.values()), u.effort_min)
            self.assertEqual(sum(w["obs"] for w in dens.values()), u.obs_min)
        self.assertEqual(list(ctx.density("u_a1")), ["2026-W36"])
        for d in ctx.env:
            sp = ctx.day_split(d)
            self.assertEqual(sp["obs_min"] + sp["est_min"] + sp["unattr_min"], sp["env_min"])
            self.assertGreaterEqual(sp["unattr_min"], 0)
        tot = sum(m for (_d, _u, _t), m in ctx.alloc.items())
        self.assertEqual(tot, sum(sum(c) for c in ctx.cells.values()))


class UnitViewTest(unittest.TestCase):
    def test_leads_and_effort(self):
        ctx = W.golden_role_a().context()
        u4 = ctx.units["u_a4"]
        self.assertEqual(u4.biz_lead_min, 3300)                 # R §4.4.3 골든 u_a4
        self.assertEqual(u4.lead_min, W.lmin("2026-10-02", "10:00") - W.lmin("2026-09-21", "11:00"))
        self.assertEqual(u4.effort_min, 270)
        self.assertEqual(u4.by_month, {"2026-09": 270})
        self.assertEqual([ctx.units[k].biz_lead_min for k in ("u_a1", "u_a2", "u_a3")], [1770, 3420, 2360])
        self.assertTrue(u4.closed)
        self.assertEqual(u4.n_cycles, 1)
        self.assertEqual(u4.project_key, "P-0007")
        self.assertEqual(u4.role_id, W.role_id("P-0007", "ELEC", "ANALYSIS"))

    def test_open_and_labels(self):
        w = W.World("2026-09-01", "2026-09-30", "2026-09-30T18:00")
        w.unit("u_o1", start=("2026-09-01", "09:00"), label=False)
        w.unit("u_o2", project=None, proposal="pr_3", start=("2026-09-02", "09:00"), end=("2026-09-03", "12:00"),
               levels_s={"L1": 0, "L2": 0, "L3": 600, "L4": 300, "L5": 0, "L6": 0, "L7": 0})
        w.run("u_o2", "DOC_DOC", "2026-09-02", "10:00", "10:30", fam="d1")
        w.run("u_o2", "COMM", "2026-09-02", "10:30", "10:45", level="L4앵커")
        ctx = w.context()
        o1, o2 = ctx.units["u_o1"], ctx.units["u_o2"]
        self.assertIsNone(o1.end)
        self.assertIsNone(o1.lead_min)
        self.assertEqual((o1.project_key, o1.domain, o1.field, o1.func), ("UNC", "UNC", "ETC", "ETC"))
        self.assertEqual(o1.role_id, W.role_id(None, "ETC", "ETC"))
        self.assertEqual(o2.project_key, "pr_3")
        self.assertIsNone(o2.project_id)
        self.assertEqual(sum(o2.levels_min.values()), o2.effort_min)
        self.assertEqual(o2.levels_min["L3"] + o2.levels_min["L4"], 45)
        w1 = W.World("2026-09-01", "2026-09-02", "2026-09-02T18:00")
        w1.unit("u_l1", start=("2026-09-01", "09:00"))
        self.assertIn("labels_missing", [x["code"] for x in w1.context(labels={}).warnings])
        # 단위업무가 0개인 실행은 분류 결과가 빈 것이 정상 — '분류 결과 없음'으로 몰지 않는다(W2 검토 L03)
        self.assertNotIn("labels_missing", [x["code"] for x in W.World("2026-09-01", "2026-09-02", "2026-09-02T18:00")
                                            .context(labels={}).warnings])

    def test_parse_local(self):
        self.assertEqual(A.parse_local("2026-10-04T18:00:00+09:00"), W.lmin("2026-10-04", "18:00"))
        self.assertEqual(A.parse_local("2026-10-04"), W.lmin("2026-10-04", "23:59"))
        self.assertEqual(A.parse_local(date(2026, 10, 4)), W.lmin("2026-10-04", "23:59"))
        self.assertEqual(A.parse_local(W.lsec("2026-10-04", "18:00")), W.lmin("2026-10-04", "18:00"))
        self.assertIsNone(A.parse_local(None))
        with self.assertRaises(ValueError):
            A.parse_local("어제")
        self.assertEqual(A.lmin_iso(W.lmin("2026-10-04", "18:05")), "2026-10-04T18:05")
        self.assertEqual(A.grade_of("L2회의(대형분할)", "u_1"), "I")
        self.assertEqual(A.grade_of("L7버킷", "B_MEET"), "X")
        self.assertEqual(A.grade_of("L1", "u_1"), "O")

    def test_calendar_mismatch_warning(self):
        w = W.golden_role_a()
        rm = dict(w.run_meta(), calendar_version="kr-0000.v0")
        ws = w.context(run_meta=rm).warnings
        self.assertIn({"code": "calendar_mismatch", "text_ko": "달력 판이 다릅니다 — 다시 분석하면 맞춰집니다",
                       "analysis": "kr-0000.v0", "current": w.cal.version}, ws)
        self.assertNotIn("calendar_mismatch", [x["code"] for x in w.context().warnings])

    def test_context_period_and_months(self):
        ctx = W.golden_role_a().context(period=None)
        self.assertEqual(ctx.d0, date(2026, 9, 1))
        self.assertEqual(ctx.d1, date(2026, 9, 30))
        self.assertEqual(ctx.months(), ["2026-09"])
        ctx = W.golden_role_a().context()
        self.assertEqual(ctx.months(), ["2026-09", "2026-10"])
        self.assertEqual(ctx.as_of_min, W.lmin("2026-10-04", "18:00"))


if __name__ == "__main__":
    unittest.main()
