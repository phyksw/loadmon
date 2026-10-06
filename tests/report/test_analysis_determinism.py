# -*- coding: utf-8 -*-
"""WP-30 결정성·금지 표현(R G-R1 · RPT-02 · RPT-33 · 계약 T-02).

- 같은 입력이면 같은 결과 바이트(`canon_bytes`) — 시간 결과 행·라벨·사람 사전·증거·카탈로그 순서를 섞어도 같다.
- 분석층 결과(문장 포함)에 '대체 가능'·'절감'·'AX 가능 MM' 0건(RP4).
- 결과는 JSON 으로 그대로 쓸 수 있다(집합·NaN 없음 — 보고서 모델이 정규 바이트로 쓴다).
"""
from __future__ import annotations

import random
import unittest

from lm27.report.analysis import analyze
from lm27.util.fsx import canon_bytes
from tests.fixtures.wp30 import world as W


def shuffled_context(seed: int):
    rnd = random.Random(seed)
    w = W.rich_world()
    f = w.files()

    def sh(xs):
        xs = list(xs)
        rnd.shuffle(xs)
        return xs

    def shd(d):
        return dict(sh(d.items()))
    tables = f["tables"]
    tables = {"envelope_daily": {"cols": tables["envelope_daily"]["cols"], "rows": sh(tables["envelope_daily"]["rows"])},
              "alloc_daily": {"cols": tables["alloc_daily"]["cols"], "rows": sh(tables["alloc_daily"]["rows"])}}
    tasks = sh(f["tasks"])
    for t in tasks:
        t["peers"] = sh(t["peers"])
        t["docs"] = shd(t["docs"])
    pdir = {"format": W.PERSON_DIR["format"], "people": shd(W.PERSON_DIR["people"])}
    reg = dict(W.REGISTRY, agents=sh(W.REGISTRY["agents"]))
    ev = {"msgs": sh(W.EVIDENCE["msgs"]), "meets": sh(W.EVIDENCE["meets"])}
    from lm27.report.analysis.activity import make_context
    return make_context(tasks=tasks, attrib=sh(f["attrib"]), tables=tables, cal=w.cal, cfg=W.cfg(),
                        labels=shd(f["labels"]), registry=reg, env_slots=sh(f["env_slots"]),
                        day_ledger=sh(f["day_ledger"]), run_meta=f["run_meta"], period=(w.d0, w.d1),
                        person_dir=pdir, evidence=ev, fam_names=shd(W.FAM_NAMES))


class DeterminismTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = canon_bytes(analyze(W.rich_context(W.cfg())))

    def test_repeat(self):
        self.assertEqual(canon_bytes(analyze(W.rich_context(W.cfg()))), self.base)

    def test_input_order(self):
        for seed in (1, 2, 3, 4):
            self.assertEqual(canon_bytes(analyze(shuffled_context(seed))), self.base, seed)

    def test_forbidden_phrases(self):
        text = self.base.decode("utf-8")
        for bad in ("대체 " + "가능", "절" + "감", "AX 가능 " + "MM", "개발자" + "에게"):
            self.assertNotIn(bad, text)

    def test_shape(self):
        sec = analyze(W.rich_context(W.cfg()))
        self.assertEqual(set(sec), {"workflows", "reviews", "peers", "ontology", "agentic", "subagent", "quality",
                                    "flags", "team"})
        self.assertEqual(set(sec["workflows"]), {"roles", "units", "projects", "domains", "person"})
        for uid, uw in sec["workflows"]["units"].items():
            ex = uw["explained_ratio"]
            self.assertTrue(ex is None or 0 <= ex <= 1, uid)
        self.assertNotIn(b"NaN", self.base)


if __name__ == "__main__":
    unittest.main()
