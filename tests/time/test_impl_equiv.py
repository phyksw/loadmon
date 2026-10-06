# -*- coding: utf-8 -*-
"""WP-20 구현 동치(W-G7): 참조 구현과 무작위 세계 1,000건(기본 하루 1,000 + 확장 3일 1,000)에서 같은 결과.

- 참조가 있으면(`tests.fixtures.wp20.g7.find_reference` — %TEMP% 사본에서 바이트코드 없이 적재) 슬롯 집합·슬롯별 귀속·
  업무 경계를 세계마다 대조한다. 허용하는 차이는 계약 §5.3 정수 동률 규칙(단위업무 u_ 먼저 — 참조는 키 사전순)에서
  오는 ±1초뿐이며 그런 세계는 1% 이하여야 한다.
- 참조가 없으면(설계 조사 폴더는 임시 폴더 — 구현 계획 §9 위험 1) 참조로 계산해 둔 고정 서명(`g7_ref.json` — 동률에
  둔감한 서명)과 대조한다. 참조가 있을 때도 같은 고정 서명을 함께 확인한다.
- 환경 변수 LM27T_G7_N 으로 세계 수를 줄여 돌릴 수 있다(완료 판정은 기본 1,000).
"""
from __future__ import annotations

import json
import os
import unittest

from tests.fixtures.wp20 import g7
from tests.time import scenarios as X

N = int(os.environ.get("LM27T_G7_N", "1000"))


class ImplEquivTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = X.base_cfg()
        cls.frozen = json.loads(g7.FROZEN.read_text(encoding="utf-8"))

    def test_frozen_file_shape(self):
        f = self.frozen
        self.assertEqual((f["schema"], f["generator"], f["seeds"]), ("lm27t.g7/1", g7.GEN, g7.SEEDS))
        self.assertGreaterEqual(f["n"], 1000)
        for kind in ("base", "ext"):
            self.assertEqual(len(f["digests"][kind]), f["n"])

    def test_equivalence(self):
        ref = g7.find_reference()
        S = g7.load_reference(ref) if ref is not None else None
        bad, ties, frozen_bad = [], 0, []
        try:
            for kind in ("base", "ext"):
                want = self.frozen["digests"][kind]
                tie_worlds = set(self.frozen["tie_worlds"][kind])
                for i, w in enumerate(g7.worlds(kind, min(N, self.frozen["n"]))):
                    sp = g7.run_prod(w, self.cfg)
                    if S is not None:
                        sr = g7.sig_ref(S.run(g7.to_ref_world(S, w)))
                        probs, t = g7.compare(sr, sp)
                        ties += 1 if t else 0
                        if probs:
                            bad.append((kind, i, probs))
                    if g7.robust_digest(sp) != want[i] and i not in tie_worlds:
                        frozen_bad.append((kind, i))
        finally:
            if S is not None:
                g7.unload_reference(S)
        self.assertEqual(bad, [], "참조 구현과 다른 세계")
        self.assertLessEqual(ties, max(1, 2 * min(N, self.frozen["n"]) // 100), "동률 차이 세계가 1%를 넘는다")
        self.assertEqual(frozen_bad, [], "고정 서명과 다른 세계")
        if S is None:
            self.skipTest("참조 구현 없음 — 고정 서명 대조만 했다(" + g7.REF_ENV + " 로 지정)")


if __name__ == "__main__":
    unittest.main()
