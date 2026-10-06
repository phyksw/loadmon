# -*- coding: utf-8 -*-
"""WP-30 온톨로지 그래프·연관도·추천(R §4.6 · RPT-22 · D-19 닫힌 관계 어휘).

- RPT-22: 연관도 골든 0.5833 · 0.55 · 0, u_a1 의 추천 = u_a2 '이어진 일', u_a2 의 추천 = u_a1·u_b1 '이어진 일',
  u_a1~u_b1 은 문턱 0.25 미만이라 추천 없음.
- 그래프: 관계는 닫힌 어휘(소속·의뢰함·보고함·산출함·사용함·함께함·선행함·같은문서) — 같은과제는 그리지 않음, 노드 종류
  P·R·U·D·A·C, 바깥 노드 topN + 무리별 '기타', 단위업무 maxUnits + '기타', 기본 중심 = 기준 달 투입 최대 과제.
"""
from __future__ import annotations

import json
import os
import unittest
from datetime import date

from lm27.report import vocab as V
from lm27.report.analysis import ontology as O
from lm27.report.analysis import peers as P
from tests.fixtures.wp30 import world as W

U = {
    "u_a1": {"docs": {"f1", "f2"}, "peers": {"w1"}, "apps": {"cae", "excel"}, "role": "rA", "project": "P-0007",
             "start_d": date(2026, 9, 1), "end_d": date(2026, 9, 4), "start": 1},
    "u_a2": {"docs": {"f2", "f3"}, "peers": {"w1", "w2"}, "apps": {"cae", "excel"}, "role": "rA", "project": "P-0007",
             "start_d": date(2026, 9, 7), "end_d": date(2026, 9, 16), "start": 2},
    "u_b1": {"docs": {"f3"}, "peers": {"w2"}, "apps": {"eda"}, "role": "rB", "project": "P-0007",
             "start_d": date(2026, 9, 17), "end_d": date(2026, 9, 22), "start": 3},
    "u_c1": {"docs": {"f9"}, "peers": {"w7"}, "apps": {"word"}, "role": "rC", "project": "P-0011",
             "start_d": date(2026, 9, 1), "end_d": date(2026, 9, 30), "start": 0},
}


def golden():
    with open(os.path.join(W.ROOT, "tests", "fixtures", "wp30", "golden_report.json"), encoding="utf-8") as f:
        return json.load(f)["relatedness"]


class RelatednessTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from lm27.report import fmt as F
        cls.bc = F.BizCal(W.calendar())
        cls.cfg = W.cfg()

    def test_golden_rpt22(self):
        g = golden()
        for pair, exp in g.items():
            a, b = pair.split("~")
            self.assertEqual(list(O.relatedness(U[a], U[b], self.cfg, bc=self.bc)), exp, pair)
        self.assertEqual(O.relatedness(U["u_a1"], U["u_a2"], self.cfg, bc=self.bc), (0.5833, 1.0))
        self.assertEqual(O.relatedness(U["u_a2"], U["u_b1"], self.cfg, bc=self.bc), (0.55, 1.0))

    def test_recommendations(self):
        rec = O.recommendations(U, self.cfg, bc=self.bc)
        self.assertEqual([(r["unit_id"], r["kind"]) for r in rec["u_a1"]], [("u_a2", "chain")])
        self.assertEqual([(r["unit_id"], r["kind"]) for r in rec["u_a2"]], [("u_a1", "chain"), ("u_b1", "chain")])
        self.assertNotIn("u_c1", rec)
        self.assertEqual(rec["u_a2"][0]["rel"], 0.5833)
        self.assertEqual(rec["u_a2"][0]["shared"], {"docs": 1, "peers": 1, "apps": 2})

    def test_kinds(self):
        same = {**U["u_a2"], "start_d": date(2026, 9, 2), "end_d": date(2026, 9, 10), "start": 5}   # 같은 역할·겹침
        cfg = W.cfg(**{"report.ontology.sameWorkRel": 0.45})                      # rel 0.4833(seq 0.5)
        rec = O.recommendations({"u_a1": U["u_a1"], "u_x": same}, cfg, bc=self.bc)
        self.assertEqual(rec["u_a1"][0]["kind"], "same")
        ref = {**U["u_c1"], "docs": {"f1"}, "project": "P-0011"}
        rec = O.recommendations({"u_a1": U["u_a1"], "u_r": ref},
                                W.cfg(**{"report.ontology.minRel": 0.05}), bc=self.bc)
        self.assertEqual(rec["u_a1"][0]["kind"], "ref")
        self.assertEqual(O.relatedness(U["u_a1"], ref, self.cfg, bc=self.bc)[1], 0.0)

    def test_weights_setting(self):
        cfg = W.cfg(**{"report.ontology.weights": {"doc": 1.0, "peer": 0.0, "app": 0.0, "seq": 0.0}})
        self.assertEqual(O.relatedness(U["u_a1"], U["u_a2"], cfg, bc=self.bc), (0.3333, 1.0))


class GraphTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        w = W.golden_role_a()
        w.tasks["u_a1"]["peers"] = [{"who_key": "w1", "rel": "requester"}, {"who_key": "w9", "rel": "reporter"}]
        w.tasks["u_a2"]["peers"] = [{"who_key": "w1", "rel": "thread"}]
        w.unit("u_b1", func="DESIGN", start=("2026-09-17", "09:00"), end=("2026-09-22", "17:00"), docs=["f3"])
        w.run("u_b1", "APP_EDA", "2026-09-17", "10:00", "12:00", app="eda_x", fam="f3")
        w.unit("u_c1", project="P-0011", func="TEST", start=("2026-09-01", "09:00"), end=("2026-09-30", "17:00"))
        w.run("u_c1", "DOC_DOC", "2026-09-29", "09:00", "12:00", app="word_x", fam="f9")
        cls.w = w
        cls.ctx = w.context()
        cls.pidx = P.peer_index(cls.ctx.units.values(), None, None, cls.ctx.cfg)

    def test_closed_vocabulary(self):
        on = O.ontology_layer(self.ctx, self.pidx)
        rels = {e["rel"] for e in on["edges"]}
        for g in on["graphs"].values():
            rels |= {e["rel"] for e in g["edges"]}
        self.assertTrue(rels <= set(V.ONTO_RELS), rels)
        self.assertNotIn("같은과제", rels)
        self.assertTrue({n["type"] for n in on["nodes"]} <= set(V.ONTO_NODES))
        for e in on["edges"]:
            self.assertEqual(e.get("inferred", False), e["rel"] in V.ONTO_RELS_INFERRED, e)
        self.assertEqual(on["center"], "P-0007")
        self.assertEqual(on["centers"], ["P-0007", "P-0011"])
        self.assertIn("P-0011", on["graphs"])
        ids = {n["id"] for n in on["nodes"]}
        for e in on["edges"]:
            self.assertIn(e["from"], ids)
            self.assertIn(e["to"], ids)

    def test_relations_content(self):
        sets = O.unit_set_map(self.ctx, self.pidx)
        rels = O.relations(self.ctx, self.pidx, sets)
        got = {(e["from"], e["rel"], e["to"]) for e in rels}
        self.assertIn(("c:w1", "의뢰함", "u_a1"), got)
        self.assertIn(("u_a1", "보고함", "c:w9"), got)
        self.assertIn(("u_a2", "함께함", "c:w1"), got)
        self.assertIn(("u_a1", "산출함", "d:f1"), got)
        self.assertIn(("u_a1", "사용함", "a:cae_x"), got)
        self.assertIn(("u_a2", "선행함", "u_b1"), got)          # 인계 조건(문서 f3 공유, 근무일 1)
        self.assertIn(("u_a1", "같은문서", "u_a2"), got)        # f2 공유
        self.assertNotIn(("u_a3", "사용함", "a:ppt_x"), got)    # 15분 미만 앱은 '사용함' 아님

    def test_external_class_node_merge(self):
        """외부 상대는 도메인 계급 노드 하나 — 같은 단위업무의 두 고객 의뢰자는 간선 하나(w 합)."""
        w = W.golden_role_a()
        w.tasks["u_a1"]["peers"] = [{"who_key": "wc1", "rel": "requester"}, {"who_key": "wc2", "rel": "requester"}]
        pdir = {"people": {k: {"names": [k], "smtp": [f"{k}@customer-a.example"], "internal": False}
                           for k in ("wc1", "wc2")}}
        reg = {"customers": [{"id": "C01", "domains": ["customer-a.example"]}]}
        ctx = w.context(person_dir=pdir, registry=reg)
        pidx = P.peer_index(ctx.units.values(), None, pdir, ctx.cfg, registry=reg)
        rels = O.relations(ctx, pidx, O.unit_set_map(ctx, pidx))
        hits = [e for e in rels if e["to"] == "u_a1" and e["rel"] == "의뢰함"]
        self.assertEqual(hits, [{"from": "c:ext:customer", "to": "u_a1", "rel": "의뢰함", "w": 2,
                                 "h": ctx.units["u_a1"].effort_min, "inferred": False}])

    def test_limits(self):
        cfg = W.cfg(**{"report.ontology.topN": 2, "report.ontology.maxUnits": 2})
        ctx = self.w.context(cfg=cfg)
        on = O.ontology_layer(ctx, self.pidx)
        types = [n["type"] for n in on["nodes"]]
        self.assertEqual(sum(1 for n in on["nodes"] if n["type"] == "U" and not n.get("etc")), 2)
        self.assertTrue(any(n["id"] == "etc:U" for n in on["nodes"]))
        outer = [n for n in on["nodes"] if n["type"] in ("D", "A", "C") and not n.get("etc")]
        self.assertEqual(len(outer), 2)
        self.assertTrue(any(n.get("etc") for n in on["nodes"] if n["type"] in ("D", "A", "C")))
        self.assertIn("P", types)
        self.assertIn("R", types)

    def test_related_projects(self):
        w = W.golden_role_a()
        w.unit("u_c1", project="P-0011", func="TEST", start=("2026-09-01", "09:00"), end=("2026-09-30", "17:00"))
        w.run("u_c1", "DOC_XLS", "2026-09-29", "09:00", "12:00", app="excel", fam="f2")
        ctx = w.context()
        pidx = P.peer_index(ctx.units.values(), None, None, ctx.cfg)
        on = O.ontology_layer(ctx, pidx)
        self.assertEqual(on["related_projects"][0]["key"], "P-0011")
        self.assertGreater(on["related_projects"][0]["rel"], 0)
        self.assertEqual(O.ontology_layer(ctx, pidx, center="P-0011")["center"], "P-0011")


if __name__ == "__main__":
    unittest.main()
