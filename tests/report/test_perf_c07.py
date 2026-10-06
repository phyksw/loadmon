# -*- coding: utf-8 -*-
"""W2 검토 C07 · L11 — 보고서 성능 경로 회귀(결과는 그대로, 계산만 줄인다).

전후 측정(이 PC · 다른 작업과 함께 돈 값이라 ±30% 흔들림 · 합성 `stored_rows(density='perf', seed=7)` 3개월
2026-07-01~09-30 = 행 47,481 · 단위업무 2,736 — 실제 파이프라인 `analyze --no-ai` 뒤 새 프로세스의 `build_report(force=True)`
= cli `report build`. 파이프라인 전체 표는 tests\\pipeline\\test_perf_c07 머리):

| 항목(3개월) | 전 | 후 |
|---|---|---|
| cli `report build` | 21.3~30.6초 | 10.2~11.2초(그중 번들 적재 `load_evidence` 약 4.5초 — 이 묶음 밖) |
| 그중 `build_model` | 13.1~21.0초 | 4.0~4.3초 |
| 그중 `ontology.recommendations` | 11.1~13.1초(쌍 374만 개 훑기 · 분수 객체) | 1.5초(역색인 후보 117만 쌍 · 정수 분수) |
| 모델 바이트 | 13,047,165 | 같음(run_id 를 뺀 바이트까지 같다) |

9개월(행 140,283 · 단위업무 8,091): cli `report build` 145.9초 → 52.7초, `recommendations` 116초 → 15~18초(후보 961만 쌍 —
예전과 같은 결과를 대조했다), 모델 34,327,453B(상한 초과) → 32,172,955B(④ 주간 끝낸 일 표 얇게까지).

이 파일의 시험:
- `recommendations` 가 예전 구현(모든 쌍 훑기 + 분수 객체 — 아래 `_reference`)과 **같은 결과**(무작위 표본 · 설정 여러 벌 —
  seq 가중 ≥ 문턱이면 같은 역할만 같은 쌍도 후보, 가중 0 항, 날짜 없는 단위업무, 한 단위업무에 후보가 몰리는 경우).
- `fmt.nd_half_up` 이 예전 `float(Fraction(q, s))` 와 같은 값.
- `fit_size`(X-281): 단계마다 모델 전체를 다시 직렬화하지 않고 바뀐 절만 재어 더하는데 그 값이 실제 `model_bytes` 길이와 같다 ·
  ①~⑥ 순서(앞 단계로 상한에 들면 멈춤) · ④ 주간 리뷰 '끝낸 일' 표 얇은 행 · ⑤ 연관 추천 상위 3 · ⑥ 주간 표 비움 · 등식 그대로 ·
  다 줄여도 넘으면 `model_over_cap` 경고(사용자 문구 — 자리표시자 없이).
"""
from __future__ import annotations

import copy
import random
import unittest
from datetime import date, timedelta
from fractions import Fraction
from unittest import mock

from lm27.report import fmt as F
from lm27.report import model as M
from lm27.report.analysis import ontology as O
from tests.fixtures.wp30 import world as W
from tests.fixtures.wp31 import runs as R

STAGES = ["단위업무 구간(runs) 요약", "다른 과제 연관 그래프", "단위업무 대기·점 목록",
          "주간 리뷰 끝낸 일 표 상세(월간 리뷰에 남김)", f"연관 업무 추천(상위 {M.REC_KEEP_TRIMMED}개만)",
          "주간 리뷰 끝낸 일 표(끝낸 일 목록만)"]


def no_fallback(*_a):
    return None


def _reference(sets, cfg, *, bc=None) -> dict:
    """예전 `recommendations`(W2 검토 C07 이전 — 모든 쌍 훑기 · 분수 · 전체 연관 쌍 사전). 대조 기준."""
    c = O.onto_cfg(cfg)
    w = c["w"]
    ids = sorted(sets)
    rel = {}
    for i, a in enumerate(ids):
        u = sets[a]
        for b in ids[i + 1:]:
            v = sets[b]
            if not (u["docs"] & v["docs"] or u["peers"] & v["peers"] or u["apps"] & v["apps"]
                    or u["role"] == v["role"]):
                continue
            terms = O._jac_terms(u, v, w)
            if not F.nd_ge(*F.wsum(terms + [(w["seq"], 1, 1)]), c["min_rel"]):
                continue
            seq = O._seq(u, v, c["handoff_wd"], bc)
            n, d = F.wsum(terms + [(w["seq"], seq.numerator, seq.denominator)])
            if n > 0 and F.nd_ge(n, d, c["min_rel"]):
                rel[(a, b)] = rel[(b, a)] = (float(Fraction((2 * n * 10000 + d) // (2 * d), 10000)),
                                             F.half_up(seq, 1))
    out = {}
    for a in ids:
        cand = []
        for b in ids:
            if b == a or (a, b) not in rel:
                continue
            r, s = rel[(a, b)]
            v = sets[b]
            cand.append((r, v["start"] if v["start"] is not None else -1, b, s))
        cand.sort(key=lambda x: (-x[0], x[1], x[2]))
        if cand:
            u = sets[a]
            out[a] = [{"unit_id": b, "rel": r, "seq": s, "kind": O._rec_kind(u, sets[b], r, s, c),
                       "shared": {"docs": len(u["docs"] & sets[b]["docs"]), "peers": len(u["peers"] & sets[b]["peers"]),
                                  "apps": len(u["apps"] & sets[b]["apps"])}} for r, _st, b, s in cand[:O.REC_MAX]]
    return out


def _sets(n: int, seed: int) -> dict:
    """무작위 단위업무 관계 재료 — 작은 공유 집합(동료 몇 명·문서 여럿·앱 몇 개), 역할·과제 몇 개, 날짜 일부 없음."""
    rnd = random.Random(seed)
    d0 = date(2026, 7, 1)
    out = {}
    for i in range(n):
        start = rnd.randrange(0, 80)
        sd = d0 + timedelta(days=start)
        ed = None if rnd.random() < 0.2 else sd + timedelta(days=rnd.randrange(0, 15))
        lead = ed or d0 + timedelta(days=91)
        if rnd.random() < 0.05:
            sd = lead = None
        uid = f"u_{i:010x}"
        out[uid] = O.UnitSets(
            unit_id=uid, role=f"r{rnd.randrange(6)}", project=f"P-{rnd.randrange(3):04d}",
            docs={f"f{rnd.randrange(n // 2 + 1)}" for _ in range(rnd.choice((0, 0, 1, 2, 3)))},
            peers={f"w{rnd.randrange(8)}" for _ in range(rnd.choice((0, 1, 1, 2, 3)))},
            apps={rnd.choice(("excel", "cae", "word", "eda")) for _ in range(rnd.choice((0, 0, 0, 1, 2)))},
            start_d=sd, end_d=ed, lead_end_d=lead, start=None if sd is None else start * 1440 + rnd.randrange(600),
            effort=rnd.randrange(5, 400))
    return out


class RecommendationsEquivTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bc = F.BizCal(W.calendar())
        cls.cfg = W.cfg()

    def check(self, sets, cfg, bc):
        self.assertEqual(O.recommendations(sets, cfg, bc=bc), _reference(sets, cfg, bc=bc))

    def test_default_weights(self):
        for seed in range(6):
            with self.subTest(seed=seed):
                self.check(_sets(160, seed), self.cfg, self.bc)

    def test_without_calendar(self):
        self.check(_sets(120, 11), self.cfg, None)

    def test_same_role_only_pairs_when_seq_weight_reaches_threshold(self):
        """seq 가중 ≥ 문턱이면 아무것도 공유하지 않는 같은 역할 쌍도 후보다(역색인이 역할 열쇠를 넣는다)."""
        cfg = self.cfg.derive({"report.ontology.weights": {"doc": 0.2, "peer": 0.2, "app": 0.1, "seq": 0.5},
                               "report.ontology.minRel": 0.25})
        sets = _sets(140, 3)
        self.check(sets, cfg, self.bc)
        rec = O.recommendations(sets, cfg, bc=self.bc)
        lone = [(a, r["unit_id"]) for a, rs in rec.items() for r in rs
                if not (sets[a]["docs"] & sets[r["unit_id"]]["docs"] or sets[a]["peers"] & sets[r["unit_id"]]["peers"]
                        or sets[a]["apps"] & sets[r["unit_id"]]["apps"])]
        self.assertTrue(lone, "같은 역할만 같은 추천이 하나는 있어야 이 분기를 시험한다")

    def test_zero_weight_and_odd_threshold(self):
        cfg = self.cfg.derive({"report.ontology.weights": {"doc": 0.0, "peer": 0.35, "app": 0.15, "seq": 0.2},
                               "report.ontology.minRel": 0.333})
        self.check(_sets(150, 7), cfg, self.bc)

    def test_crowded_candidates(self):
        """한 단위업무에 후보가 몰려 상위 목록을 중간에 잘라도(`_TOP_SLACK`) 끝 결과는 같다 — 모두 같은 동료."""
        sets = _sets(90, 5)
        for s in sets.values():
            s["peers"] = {"w1"}
        self.check(sets, self.cfg, self.bc)

    def test_rpt22_fixture_unchanged(self):
        """dict 로 넘긴 재료(lead_end_d 없음)도 예전과 같다(WP-30 골든 표본 모양)."""
        u = {"u_a1": {"docs": {"f1", "f2"}, "peers": {"w1"}, "apps": {"cae"}, "role": "rA", "project": "P-0007",
                      "start_d": date(2026, 9, 1), "end_d": date(2026, 9, 4), "start": 1},
             "u_a2": {"docs": {"f2"}, "peers": {"w1"}, "apps": {"cae"}, "role": "rA", "project": "P-0007",
                      "start_d": date(2026, 9, 7), "end_d": None, "start": 2}}
        self.check(u, self.cfg, self.bc)


class HalfUpTest(unittest.TestCase):
    def test_nd_half_up_same_float(self):
        rnd = random.Random(1)
        for _ in range(20000):
            n, d = rnd.randrange(0, 10 ** 9), rnd.randrange(1, 10 ** 9)
            for digits in (0, 1, 3, 4):
                s = 10 ** digits
                self.assertEqual(F.nd_half_up(n, d, digits), float(Fraction((2 * n * s + d) // (2 * d), s)))


class FitSizeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.t = R.TmpRoot()
        cls.addClassCleanup(cls.t.cleanup)
        cls.srun = R.big_run(300)
        cls.srun.write(cls.t.paths)
        cls.cfg = W.cfg()
        cls.m = M.build_model(cls.srun.inputs(cls.t.paths, cls.cfg, evidence=False), cls.cfg, fallback=no_fallback)
        cls.full = len(M.model_bytes(cls.m))

    def fit(self, cap):
        return M._fit(copy.deepcopy(self.m), cap)

    def test_fixture_reaches_every_stage(self):
        self.assertTrue(any(r.get("lead_table") for r in self.m["reviews"]["weeks"]))
        self.assertTrue(any(len(v) > M.REC_KEEP_TRIMMED for v in self.m["ontology"]["recs"].values()))
        self.assertTrue(self.m["ontology"]["graphs"])

    def test_incremental_size_is_exact(self):
        for k in (100, 99, 90, 80, 70, 60, 50, 1):
            cap = self.full * k // 100 if k > 1 else 1
            with self.subTest(cap=cap):
                m, trimmed, size = self.fit(cap)
                self.assertEqual(size, len(M.model_bytes(m)))
                self.assertEqual(trimmed, STAGES[:len(trimmed)], "단계 순서")
                self.assertEqual(trimmed == [], cap >= self.full)
                if trimmed and len(trimmed) < len(STAGES):
                    self.assertLessEqual(size, cap, "상한에 들면 거기서 멈춘다")
                self.assertEqual(M.check_model(m), [])

    def test_all_stages(self):
        m, trimmed, _size = self.fit(1)
        self.assertEqual(trimmed, STAGES)
        self.assertTrue(all(len(v) <= M.REC_KEEP_TRIMMED for v in m["ontology"]["recs"].values()))
        for uid, v in m["ontology"]["recs"].items():
            self.assertEqual(v, self.m["ontology"]["recs"][uid][:M.REC_KEEP_TRIMMED], "앞 3개 그대로(순서 유지)")
        self.assertTrue(all(r["lead_table"] == [] for r in m["reviews"]["weeks"]))
        self.assertEqual(m["reviews"]["months"], self.m["reviews"]["months"], "월간 리뷰 표는 그대로")
        for key in ("units", "months", "days", "tables", "projects", "tree", "queue"):
            self.assertEqual(m[key], self.m[key], key)
        self.assertEqual([r["finished"] for r in m["reviews"]["weeks"]], [r["finished"] for r in self.m["reviews"]["weeks"]])

    def test_stop_after_slim_weekly_table(self):
        """④ 까지만으로 상한에 드는 캡 — 주간 표 행은 원인 코드만, 연관 추천은 그대로."""
        hit = None
        for k in range(99, 0, -1):
            m, trimmed, size = self.fit(self.full * k // 100)
            if len(trimmed) == 4:
                hit = (m, size, self.full * k // 100)
                break
        self.assertIsNotNone(hit, "④ 에서 멈추는 캡이 있어야 한다")
        m, size, cap = hit
        self.assertLessEqual(size, cap)
        for r, r0 in zip(m["reviews"]["weeks"], self.m["reviews"]["weeks"], strict=True):
            self.assertEqual([x["unit_id"] for x in r["lead_table"]], [x["unit_id"] for x in r0["lead_table"]])
            for x, x0 in zip(r["lead_table"], r0["lead_table"], strict=True):
                self.assertEqual(x, {k: x0[k] for k in M._LEAD_SLIM if k in x0})
        self.assertEqual(m["ontology"]["recs"], self.m["ontology"]["recs"])

    def test_over_cap_warning(self):
        """다 줄여도 상한을 넘으면 `model_over_cap`(숫자가 들어간 사용자 문구) — 보고서는 그대로 만든다."""
        inp = self.srun.inputs(self.t.paths, self.cfg, evidence=False)
        with mock.patch.object(M, "MB", 1000):                    # 상한 1MB → 1,000바이트(어떤 단계로도 못 든다)
            small = M.build_model(inp, self.cfg, fallback=no_fallback)
        codes = [w["code"] for w in small["flags"]["warnings"]]
        self.assertIn("model_trimmed", codes)
        w = next(x for x in small["flags"]["warnings"] if x["code"] == "model_over_cap")
        self.assertNotIn("{", w["text_ko"])
        self.assertIn("상한 32MB", w["text_ko"])
        self.assertEqual(w["cap_mb"], 32)
        self.assertEqual(M.check_model(small), [])
        self.assertEqual(small["flags"]["trimmed"], STAGES)
        self.assertNotIn("model_over_cap", [x["code"] for x in self.m["flags"]["warnings"]])


if __name__ == "__main__":
    unittest.main()
