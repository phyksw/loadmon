# -*- coding: utf-8 -*-
r"""WP-22 이름 병합 거버넌스 시험 — H §9(−∞ 규칙·가감·세 구간·제약 클러스터링) · G-H10(무작위 2,000회: 무리 안 −∞ 0,
크기 ≤ cap) · S1 이름 맞추기 · 병합 기록."""
import json
import random
import unittest

from lm27.hier import merge as MG
from lm27.hier.names import ukey
from tests.fixtures.wp22 import hierkit as K

NEG = MG.NEG


class PairScoreTest(unittest.TestCase):
    def test_neg_rules(self):
        ctx = MG.MergeCtx(never=frozenset({frozenset((ukey("광센서 선행"), ukey("광센서 양산")))}),
                          never_words={ukey("과제A"): ("후속",)},
                          dom={"방열 모듈": "DEV", "방열모듈 개발": "MP"},
                          dom_confirmed=frozenset({"방열 모듈", "방열모듈 개발"}))
        self.assertEqual(MG.pair_score("광센서 선행", "광센서 양산", ctx), (NEG, "never"))
        self.assertEqual(MG.pair_score("과제A", "과제A 후속", ctx)[0], NEG)          # 등록 과제의 never 낱말
        self.assertEqual(MG.pair_score("방열 모듈", "방열모듈 개발", ctx), (NEG, "영역 상이(확정)"))

    def test_evidence_terms(self):
        ctx = MG.MergeCtx(shared={"A 시험": frozenset({"d1", "d2"}), "A 시험 정리": frozenset({"d1", "d2"})},
                          cust={"A 시험": frozenset({"C01"}), "A 시험 정리": frozenset({"C01"})})
        s, why = MG.pair_score("A 시험", "A 시험 정리", ctx)
        self.assertIn("공유근거 1.00", why)
        self.assertIn("고객 일치", why)
        self.assertEqual(MG.zone(s, K.cfg()), "auto")
        ctx2 = MG.MergeCtx(shared={"가": frozenset({"d1", "d2"}), "나": frozenset({"d3", "d4"})},
                           dom={"가": "DEV", "나": "MP"}, span={"가": ("2026-01-01", "2026-01-31"),
                                                              "나": ("2026-08-01", "2026-08-31")})
        s, why = MG.pair_score("가", "나", ctx2)
        self.assertEqual(s, round(-0.8 - 0.8 - 0.6, 3))
        self.assertIn("시기 비겹침 -0.6", why)

    def test_zone_cfg(self):
        self.assertEqual(MG.zone(0.5, K.cfg()), "ask")
        self.assertEqual(MG.zone(0.5, K.cfg({"hier.merge.ask": 0.6})), "reject")
        self.assertEqual(MG.zone(NEG, K.cfg()), "reject")
        c = MG.merge_ctx_for(K.golden_reg(), K.cfg({"hier.merge.auto": 2.0, "hier.merge.spanGapDays": 30}))
        self.assertEqual((c.auto, c.span_gap_days), (2.0, 30))
        self.assertEqual(c.registry_ids[ukey("PROJ-E")], "P-0007")            # 병합된 과제 이름은 대표 ID


class ClusterTest(unittest.TestCase):
    def test_constraint_fuzz(self):
        """G-H10 — 무작위 이름 집합 2,000회: 무리 안 −∞ 쌍 0, 크기 ≤ cap."""
        r = random.Random(2210)
        base = ["열해석", "열 해석", "방열", "방열 모듈", "광학", "광학 설계", "센서", "센서 1차", "센서 2차", "A(양산)",
                "A(선행)", "A", "공차", "공차 해석", "브라켓"]
        for i in range(2000):
            names = r.sample(base, r.randint(2, 9))
            W = MG.pair_weights(names)
            for a in names:
                for b in names:
                    if a < b and r.random() < 0.15:
                        W[(a, b)] = NEG
            cap = r.randint(2, 5)
            part = MG.cluster(names, W, sorted(names), cap)
            self.assertEqual(sorted(n for g in part for n in g), sorted(names), i)
            for g in part:
                self.assertLessEqual(len(g), cap)
                for x in g:
                    for y in g:
                        if x < y:
                            self.assertNotEqual(W.get((x, y), 0.0), NEG, (i, g))

    def test_local_search_moves(self):
        W = {("a", "b"): 3.0, ("a", "c"): 3.0, ("b", "c"): -5.0}
        part = MG.cluster(["a", "b", "c"], W, ["b", "a", "c"], 5)
        self.assertTrue(all(not ({"b", "c"} <= set(g)) for g in part))


class TeamCandidatesTest(unittest.TestCase):
    """T-H21 — 팀 서버 '제안 묶음 후보'(S5): 30명 × 월 300 군집 규모의 제안 모음 → 자동·질문 쌍 목록, 서버 자동 병합 0."""

    def test_30_people(self):
        import copy
        import time

        from lm27.hier.names import bigram_dice
        r = random.Random(21)
        stems = ["방열 모듈", "광센서 선행", "열해석 자동화", "레이저 모듈", "시험 지그", "공차 분석", "브라켓 개선",
                 "수율 개선", "센서 보정", "냉각 구조", "광학 정렬", "패키지 설계", "신뢰성 시험", "회로 보호", "전원 설계"]
        variants = (lambda x: x, lambda x: x.replace(" ", ""), lambda x: x + " 개발", lambda x: x + "(양산)",
                    lambda x: x + " 2차", lambda x: "신규 " + x)
        entries = []
        for i in range(30):
            pk = f"p_{i:012x}"
            for j in range(r.randint(8, 20)):
                stem = r.choice(stems)
                entries.append({"person_key": pk, "proposal_id": f"pr_{j + 1}", "label": r.choice(variants)(stem),
                                "domain_guess": r.choice(("DEV", "DEV", "MP")), "effort_min": r.randint(60, 3000)})
        snap = copy.deepcopy(entries)
        t0 = time.perf_counter()
        out = MG.team_proposal_candidates(entries, K.cfg())
        self.assertLess(time.perf_counter() - t0, 20.0)
        self.assertEqual(entries, snap)                                         # 입력을 바꾸지 않는다(합치지 않는다)
        pairs, bundles = out["pairs"], out["bundles"]
        self.assertTrue(pairs and bundles)
        self.assertEqual({p["zone"] for p in pairs} - {"auto", "ask"}, set())
        self.assertIn("ask", {p["zone"] for p in pairs})
        for p in pairs:
            self.assertGreaterEqual(p["persons"], 2)
            self.assertNotEqual(p["score"], NEG)
            self.assertEqual(MG.zone(p["score"], K.cfg()), p["zone"])
        names = {e["label"] for e in entries}
        for p in pairs:                                                         # 2-gram 색인이 빠뜨린 쌍이 없다
            self.assertIn(p["a"], names)
        reps = sorted({p["a"] for p in pairs} | {p["b"] for p in pairs})[:40]
        for i, a in enumerate(reps):
            for b in reps[i + 1:]:
                self.assertAlmostEqual(2 * len(MG.name_bigrams(a) & MG.name_bigrams(b)) /
                                       (len(MG.name_bigrams(a)) + len(MG.name_bigrams(b))), bigram_dice(a, b))
        for bd in bundles:
            self.assertLessEqual(len(bd["names"]), int(K.cfg()["hier.merge.cap"]))
            self.assertGreaterEqual(bd["persons"], 2)
            for x in bd["names"]:
                for y in bd["names"]:
                    if x < y:
                        self.assertNotEqual(MG.pair_score(x, y)[0], NEG, bd)
        same = [bd for bd in bundles if len(bd["names"]) == 1]
        self.assertTrue(all(bd["zone"] == "auto" for bd in same))               # 같은 ukey 를 여러 사람이 — 표기 동일

    def test_small(self):
        es = [{"person_key": "p_a", "proposal_id": "pr_1", "label": "방열 모듈", "domain_guess": "DEV"},
              {"person_key": "p_b", "proposal_id": "pr_3", "label": "방열모듈", "domain_guess": "DEV"},
              {"person_key": "p_c", "proposal_id": "pr_2", "label": "방열 모듈 개발", "domain_guess": "DEV"},
              {"person_key": "p_c", "proposal_id": "pr_4", "label": "방열 모듈(양산)", "domain_guess": "MP"},
              {"person_key": "p_a", "proposal_id": "pr_2", "label": "방열 모듈 2차", "domain_guess": "DEV"},
              {"person_key": "p_d", "proposal_id": "pr_1", "label": "x", "domain_guess": "DEV"}]
        out = MG.team_proposal_candidates(es, K.cfg())
        self.assertEqual([(p["a"], p["b"], p["zone"]) for p in out["pairs"]],
                         [("방열 모듈", "방열 모듈 개발", "ask")])
        bd = out["bundles"]
        self.assertEqual(bd[0]["names"], ["방열 모듈", "방열 모듈 개발"])
        self.assertEqual((bd[0]["persons"], bd[0]["zone"]), (3, "ask"))
        self.assertEqual(bd[0]["members"], [["p_a", "pr_1"], ["p_b", "pr_3"], ["p_c", "pr_2"]])
        self.assertEqual(len(bd), 1)                                            # (양산)·2차 는 −∞, 한 사람 이름 'x' 는 버림
        self.assertEqual(MG.team_proposal_candidates([], K.cfg()), {"pairs": [], "bundles": []})


class MergeTitlesTest(unittest.TestCase):
    def test_s1(self):
        items = [{"group": "g1", "role": "r_1", "title": "공차 해석", "effort_min": 300},
                 {"group": "g2", "role": "r_1", "title": "공차해석", "effort_min": 100},
                 {"group": "g3", "role": "r_1", "title": "공차 해석 정리", "effort_min": 50, "locked": True},
                 {"group": "g4", "role": "r_2", "title": "공차해석", "effort_min": 999},
                 {"group": "g5", "role": "r_1", "title": "과제A 후속", "effort_min": 10},
                 {"group": "g6", "role": "r_1", "title": "과제A", "effort_min": 20}]
        ren, asks = MG.merge_titles(items, None, K.cfg())
        self.assertEqual(ren.get("g2"), "공차 해석")                           # 투입 큰 쪽 이름
        self.assertNotIn("g4", ren)                                            # 다른 역할은 비교하지 않는다
        self.assertNotIn("g3", ren)                                            # 사용자 이름은 바꾸지 않는다
        self.assertTrue(any({a["a"], a["b"]} == {"과제A", "과제A 후속"} for a in asks))

    def test_log(self):
        with K.TmpTree() as t:
            MG.append_merge_log(t.paths, {"at": "2026-10-05T10:00:00+09:00", "scope": "S2", "a": "x", "b": "y",
                                          "score": NEG, "zone": "reject", "why": "never", "applied": False, "by": "auto"})
            line = t.paths.hier_local_file("merge_log.jsonl").read_text(encoding="utf-8").strip()
            self.assertIsNone(json.loads(line)["score"])


if __name__ == "__main__":
    unittest.main()
