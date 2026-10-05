# -*- coding: utf-8 -*-
"""WP-19 구간 산술·정수 배분(lm27.time.intervals) — 무차별 대조 + 보존(Σ = total) + 동률 규칙(계약 §5.3 · X-208)."""
from __future__ import annotations

import random
import unittest

from lm27.time.intervals import SLOT, SUB, I, IvIx, L, U, lr_minutes, pre_iv, pts_in, slot_cover, split_int, tie_key


def _cells(ivs) -> set[int]:
    out = set()
    for a, b in ivs:
        out |= set(range(a, b))
    return out


def _rnd_ivs(r: random.Random, n: int, span: int = 200) -> list[tuple[int, int]]:
    out = []
    for _ in range(n):
        a = r.randrange(0, span)
        out.append((a, a + r.randrange(-3, 30)))      # 길이 0·음수도 섞는다(버려져야 함)
    return out


class IntervalAlgebraTest(unittest.TestCase):
    def test_union_merges_touching_and_drops_empty(self):
        self.assertEqual(U([(5, 10), (0, 3), (3, 5), (12, 12), (20, 15)]), [(0, 10)])
        self.assertEqual(U([]), [])

    def test_ops_match_bruteforce(self):
        r = random.Random(19)
        for _ in range(400):
            A, B = _rnd_ivs(r, r.randrange(0, 8)), _rnd_ivs(r, r.randrange(0, 8))
            ca, cb = _cells(A), _cells(B)
            self.assertEqual(_cells(U(A)), ca)
            self.assertEqual(_cells(I(A, B)), ca & cb)
            self.assertEqual(_cells(SUB(A, B)), ca - cb)
            self.assertEqual(L(A), len(ca))
            for res in (U(A), I(A, B), SUB(A, B)):        # 결과는 정렬·서로소·비어 있지 않은 구간
                for (_a, b), (c, _d) in zip(res, res[1:], strict=False):
                    self.assertLess(b, c)
                self.assertTrue(all(b > a for a, b in res))

    def test_ivix_matches_bruteforce(self):
        r = random.Random(7)
        for _ in range(200):
            A = _rnd_ivs(r, r.randrange(0, 10))
            ix, ca = IvIx(A), _cells(A)
            for _ in range(20):
                t = r.randrange(-5, 240)
                self.assertEqual(ix.has(t), t in ca)
                a = r.randrange(-5, 240)
                b = a + r.randrange(1, 40)                  # 빈 창은 쓰지 않는다(호출처 모두 b > a)
                win = set(range(a, b))
                self.assertEqual(ix.hit(a, b), bool(win & ca))
                self.assertEqual(_cells(ix.clip(a, b)), win & ca)
                self.assertEqual(ix.length(a, b), len(win & ca))

    def test_pts_in_closed_range(self):
        pts = [1, 3, 3, 7, 10]
        self.assertEqual(pts_in(pts, 3, 7), [3, 3, 7])
        self.assertEqual(pts_in(pts, 8, 9), [])

    def test_pre_iv_ends_at_anchor_slot(self):
        t = 21 * 3600 + 2 * 60                           # 21:02 → 슬롯 21:00 이 끝
        self.assertEqual(pre_iv(t, 20 * 60), (21 * 3600 + 300 - 4 * SLOT, 21 * 3600 + 300))
        self.assertEqual(pre_iv(t, 0), (21 * 3600, 21 * 3600 + 300))      # 최소 1슬롯
        a, b = pre_iv(t, 45 * 60)
        self.assertEqual((b - a) // SLOT, 9)

    def test_slot_cover(self):
        cov = slot_cover([(0, 450), (600, 610)])
        self.assertEqual(cov, {0: 300, 1: 150, 2: 10})
        self.assertEqual(slot_cover([(0, 450)], only={1}), {1: 150})


class SplitIntTest(unittest.TestCase):
    def test_sum_exact_random(self):
        r = random.Random(26)
        for _ in range(2000):
            k = r.randrange(1, 7)
            w = {f"u_{i:03d}" if r.random() < 0.6 else f"B_{i}": r.choice([r.randrange(0, 400), r.random() * 3])
                 for i in range(k)}
            total = r.choice([300, 60, 1, 0, 480, 7])
            out = split_int(total, w)
            pos = {x for x, v in w.items() if v > 0}
            if total and any((round(v * 1000) if isinstance(v, float) else v) > 0 for v in w.values()):
                self.assertEqual(sum(out.values()), total)
            self.assertTrue(set(out) <= pos)
            self.assertTrue(all(isinstance(v, int) and v > 0 for v in out.values()))

    def test_tie_prefers_unit_tasks_then_key(self):
        # 같은 가중 3개에 1을 나누면 잉여 동률 — 단위업무(u_) 가 버킷(B_)보다 먼저(계약 §5.3 · X-208)
        self.assertEqual(split_int(1, {"B_GENERIC": 1, "u_b": 1, "u_a": 1}), {"u_a": 1})
        self.assertEqual(split_int(2, {"B_COMM": 1, "u_z": 1, "B_MEET": 1}), {"u_z": 1, "B_COMM": 1})
        self.assertLess(tie_key("u_x"), tie_key("B_x"))

    def test_proportional_and_floats(self):
        self.assertEqual(split_int(300, {"u_a": 2, "u_b": 1}), {"u_a": 200, "u_b": 100})
        self.assertEqual(split_int(300, {"u_a": 0.5, "u_b": 0.5}), {"u_a": 150, "u_b": 150})
        self.assertEqual(split_int(300, {"u_a": 0, "u_b": -1}), {})
        self.assertEqual(split_int(0, {"u_a": 1}), {})
        with self.assertRaises(ValueError):
            split_int(-1, {"u_a": 1})

    def test_deterministic_regardless_of_dict_order(self):
        w = {"u_c": 7, "B_GENERIC": 7, "u_a": 7, "u_b": 7}
        ref = split_int(10, w)
        for perm in ([*w][::-1], sorted(w), ["u_b", "B_GENERIC", "u_c", "u_a"]):
            self.assertEqual(split_int(10, {k: w[k] for k in perm}), ref)

    def test_lr_minutes(self):
        out = lr_minutes({"u_a": 100, "u_b": 200, "B_COMM": 0}, 5)
        self.assertEqual(sum(out.values()), 5)
        self.assertEqual(lr_minutes({}, 5), {})
        self.assertEqual(lr_minutes({"u_a": 1}, 0), {})


if __name__ == "__main__":
    unittest.main()
