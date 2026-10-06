# -*- coding: utf-8 -*-
"""WP-20 슬롯 귀속(W §5 · 계약 §3.14 attrib.jsonl · §6.4 귀속 단계 · C21 obs 형 · T-01 보존).

보존(날마다 Σ귀속 초 = 300 × 봉투 슬롯, 어기면 분석 중단) · 단계 값 = 계약 13종 · attrib 행의 obs(단계 코드 문자열 —
'' = 단계 아님)·app·fam · 다중 PC·원격 데스크톱 · 회의 혼합·불참 의심 · 공용 문서 · L5 공백·흡수 · L6 상한 · 솔버 ·
수동 기록(L1 · MANUAL 업무) · resolve 의 창 분할.
"""
from __future__ import annotations

import unittest
from collections import Counter
from unittest import mock

from lm27.time import attribute as A
from lm27.time.attribute import LEVELS, ConservationError, attribute, attribute_full, grade_of_level, resolve
from lm27.time.calendar import SLOT, d_of
from lm27.time.episodes import build_tasks
from lm27.vocab.steps import ACTIVITY_STEPS
from tests.fixtures.wp20 import harness as H
from tests.time import scenarios as X


def by_label(res, names):
    return {H.ref_label(names, t.label): t for t in res.tasks}


class AttributeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = X.base_cfg()
        cls.res = {name: H.run(fn(), cls.cfg, ref_ids=False) for name, fn in X.SC.items()}

    def test_conservation_every_day(self):
        for name, (r, _n) in sorted(self.res.items()):
            with self.subTest(name=name):
                env_day, att_day = Counter(), Counter()
                for s in r.env.slots:
                    env_day[d_of(s * SLOT)] += SLOT
                    att_day[d_of(s * SLOT)] += sum(r.assign[s].values())
                    self.assertTrue(all(isinstance(v, int) and v > 0 for v in r.assign[s].values()))
                self.assertEqual(env_day, att_day)
                self.assertEqual(set(r.assign), set(r.env.slots))

    def test_conservation_violation_stops_analysis(self):
        w = X.SC["W17"]()
        with mock.patch.object(A, "split_int", lambda total, w: dict.fromkeys(w, 1)):
            with self.assertRaises(ConservationError):
                H.run(w, self.cfg, ref_ids=False)

    def test_levels_are_contract_values(self):
        seen = set()
        for name, (r, _n) in sorted(self.res.items()):
            seen |= set(r.level.values())
            self.assertLessEqual(set(r.level.values()), set(LEVELS), name)
        self.assertEqual(len(LEVELS), 13)
        for lv in ("L1", "L2회의", "L2회의(대형분할)", "L2회의(불참의심)", "L3PC", "L4앵커", "L4솔버cap", "L5공백",
                   "L5하한근접", "L6비례", "L7버킷"):
            self.assertIn(lv, seen | {"L1"}, lv)

    def test_attrib_rows_shape_and_obs(self):
        steps = set(ACTIVITY_STEPS)
        for name, (r, _n) in sorted(self.res.items()):
            with self.subTest(name=name):
                rows = r.attribution.rows()
                self.assertEqual(sum(x["sec"] for x in rows), len(r.env.slots) * SLOT)
                for x in rows:
                    self.assertEqual(set(x), {"slot", "target", "sec", "level", "obs", "app", "fam"})
                    self.assertIsInstance(x["obs"], str)                      # C21: 단계 코드 문자열
                    self.assertTrue(x["obs"] == "" or x["obs"] in steps, x)
                    if x["target"].startswith("B_"):
                        self.assertEqual(x["obs"], "")
                    if x["level"][:2] in ("L5", "L6", "L7"):
                        self.assertEqual(x["obs"], "")
                    if x["level"] == "L1":
                        self.assertEqual(x["obs"], "OFFLINE")

    def obs_of_task(self, name, label):
        r, n = self.res[name]
        tid = by_label(r, n)[label].id
        c = Counter()
        for x in r.attribution.rows():
            if x["target"] == tid:
                c[(x["level"], x["obs"])] += x["sec"]
        return c

    def test_obs_codes_by_evidence(self):
        c = self.obs_of_task("W01", "S1:chat_kim#1")
        self.assertGreater(c[("L3PC", "DOC_PPT")], 0)                     # .pptx 문서 조각
        c = self.obs_of_task("W06", "SELF:배선도_과제c@10-12")
        self.assertGreater(c[("L3PC", "APP_CAD")], 0)                     # cad 앱
        c = self.obs_of_task("W23", "S1:M8#1")
        self.assertGreater(c[("L4앵커", "COMM")], 0)                      # 휴대폰 보고 발신 직전 창
        c = self.obs_of_task("W08", "S1:M8#1")
        self.assertGreater(c[("L2회의", "REVIEW")], 0)                    # 의뢰자 리뷰 회의(E3c)
        c = self.obs_of_task("W42B", "SELF:열해석_모델@10-19")
        self.assertGreater(c[("L4솔버cap", "APP_CAE")], 0)

    def test_app_and_fam_columns(self):
        r, n = self.res["W01"]
        tid = by_label(r, n)["S1:chat_kim#1"].id
        rows = [x for x in r.attribution.rows() if x["target"] == tid and x["level"] == "L3PC"]
        self.assertTrue(rows)
        self.assertTrue(all(x["fam"].startswith("d") and x["app"] for x in rows))

    def test_multi_pc_rdp_no_double_count(self):
        r, n = self.res["W40"]
        t = by_label(r, n)
        eff = r.effort()
        self.assertEqual(eff[t["SELF:문서a_과제a@10-14"].id], 6 * 3600)
        self.assertEqual(eff[t["SELF:문서b_과제b@10-14"].id], 2 * 3600)
        self.assertEqual(len(r.env.slots) * SLOT, 8 * 3600)

    def test_meeting_mix_and_absent(self):
        r, _n = self.res["W41"]
        self.assertIn("L2회의(대형분할)", set(r.level.values()))
        r, n = self.res["W44"]
        self.assertIn("L2회의(불참의심)", set(r.level.values()))
        self.assertEqual(len(r.attribution.absent), 1)
        self.assertTrue(any(q.code == "Q14" for q in r.queue))

    def test_shared_doc_to_generic_bucket(self):
        r, _n = self.res["W45"]
        self.assertEqual(round(r.effort()["B_GENERIC"] / 3600, 2), 8.92)
        shared = [s for s, st in r.attribution.stype.items() if st == "shared"
                  and r.level[s][:2] not in ("L1", "L2", "L3", "L4")]       # 직접 귀속이 없는 공용 문서 슬롯
        self.assertTrue(shared)
        self.assertTrue(all(r.assign[s] == {"B_GENERIC": SLOT} and r.level[s] == "L7버킷" for s in shared))

    def test_l6_proportional_cap(self):
        r, n = self.res["W56"]
        t = by_label(r, n)
        self.assertIn("L6비례", set(r.level.values()))
        lv = r.attribution.effort_levels()
        for lab in ("S1:M56a#1", "S1:M56b#1"):
            tid = t[lab].id
            direct = sum(v for k, v in lv[tid].items() if k in ("L1", "L2", "L3", "L4"))
            self.assertLessEqual(lv[tid].get("L6", 0), direct)              # 추정 ≤ 직접 × 1.0

    def test_offpc_gap_buckets(self):
        r, _n = self.res["W38"]
        self.assertGreater(r.effort()["B_OFFPC"], 0)
        self.assertIn("L5공백", set(r.level.values()))

    def test_manual_work_l1_and_manual_task(self):
        w = X.W("MAN", "2026-10-14", "2026-10-14", "2026-10-30 18:00")
        X.office_day(w, "PC1", "2026-10-14", [("09:00", "12:00", "office", "설계서_과제A.docx")])
        w.doc("2026-10-14 11:50", "save", "설계서_과제A.docx")
        w.man("work", a="2026-10-14 13:00", b="2026-10-14 14:00", ref="설계서_과제A.docx")
        w.man("work", a="2026-10-14 15:00", b="2026-10-14 15:30", ref="현장지원")
        r, n = H.run(w, self.cfg, ref_ids=False)
        t = by_label(r, n)
        selfk = t["SELF:설계서_과제a@10-14"].id
        man = [x for x in r.tasks if x.kind == "MANUAL"]
        self.assertEqual(len(man), 1)
        self.assertEqual((man[0].grade, man[0].cycles[0].sb, man[0].cycles[-1].eb), ("M", "S2M", "E3M"))
        l1 = [s for s, lv in r.level.items() if lv == "L1"]
        self.assertEqual(len(l1), 18)                                       # 13~14시 12 + 15~15:30 6
        self.assertTrue(all(set(r.assign[s]) <= {selfk, man[0].id} for s in l1))
        rows = [x for x in r.attribution.rows() if x["level"] == "L1"]
        self.assertTrue(all(x["obs"] == "OFFLINE" for x in rows))
        self.assertTrue(man[0].label.startswith("MANUAL:d"))               # 표지는 키만

    def test_resolve_window_split(self):
        r, n = self.res["W21"]
        t = by_label(r, n)
        ctx = r.tasks.ctx
        m1, m2 = t["S1:M1#1"], t["S1:M2#1"]
        t1 = m1.cycles[0].s + 600
        t2 = m2.cycles[0].s + 3600
        self.assertEqual(resolve("B_GENERIC", t1, ctx), {m1.id: 1})
        self.assertEqual(resolve("B_GENERIC", t2, ctx), {m2.id: 1})
        self.assertIsNone(resolve("dnot_a_family_key", t1, ctx))

    def test_requires_task_list(self):
        w = X.SC["W17"]()
        ev, days, env, c = X.run_env(w, self.cfg)
        tasks, _q = build_tasks(ev, env, days, c, X.calendar(), unit_key=H.TEST_KEY)
        with self.assertRaises(TypeError):
            attribute_full(ev, env, list(tasks), days, c)
        assign, level = attribute(ev, env, tasks, days, c)
        self.assertIs(tasks.ctx.attribution.assign, assign)
        self.assertEqual(set(assign), set(level))

    def test_grade_of_level(self):
        self.assertEqual(grade_of_level("L3PC", "u_0000000000"), "O")
        self.assertEqual(grade_of_level("L2회의(대형분할)", "u_0000000000"), "I")
        self.assertEqual(grade_of_level("L2회의", "B_MEET"), "X")
        self.assertEqual(grade_of_level("L6비례", "u_0000000000"), "I")


if __name__ == "__main__":
    unittest.main()
