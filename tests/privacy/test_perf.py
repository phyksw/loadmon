# -*- coding: utf-8 -*-
"""WP-10 성능 시험 — P-T18 · 계약 T-19: 정제 20,000행 ≤ 5초, 병적 입력 12종 각 ≤ 50ms(반복 상한이 이차 시간 역추적을
막는지). 측정 잡음(병렬 시험·백신)을 줄이려고 행 처리는 2회 중 빠른 값, 병적 입력은 5회 중 가장 빠른 값으로 판정한다."""
import time
import unittest

from lm27.privacy import selftest
from lm27.privacy.detect import SanitizeContext, sanitize
from lm27.privacy.scan import scan

ROWS = selftest.PERF_ROWS


def _pool():
    rows = selftest.load_corpus()
    return [(r["text"], SanitizeContext(**r["ctx"]) if r.get("ctx") else SanitizeContext())
            for r in rows if r["type"] in ("pos", "neg")]


class PerfTest(unittest.TestCase):
    def test_20000_rows_within_5s_T18(self):
        pool = _pool()
        self.assertEqual(len(pool), 129)          # 양성 75 + 미끼 54(2026.10.1)
        best = None
        for _ in range(2):
            t0 = time.perf_counter()
            for i in range(ROWS):
                text, ctx = pool[i % len(pool)]
                sanitize(text, ctx=ctx)
            dt = time.perf_counter() - t0
            best = dt if best is None else min(best, dt)
        self.assertLessEqual(best, selftest.PERF_ROW_SEC, f"{ROWS}행 {best:.2f}s")

    def test_pathological_inputs_each_within_50ms_T18(self):
        for name, text in selftest.pathological_inputs():
            ms = min(self._time(lambda text=text: sanitize(text)) for _ in range(5))
            with self.subTest(name=name):
                self.assertLessEqual(ms, selftest.PERF_PATHO_MS, f"{name} {ms:.1f}ms")

    def test_pathological_outputs_are_bounded(self):
        """병적 입력도 4,000자 상한 안에서 끝나고 예외 없이 결과를 낸다."""
        for name, text in selftest.pathological_inputs():
            with self.subTest(name=name):
                r = sanitize(text)
                self.assertLessEqual(len(r.text), 4000 * 2)
                self.assertIsInstance(r.hits, dict)

    def test_large_person_dictionary(self):
        """사람 사전 3천여 명 + 고객사 60곳 문맥에서도 20,000행 ≤ 5초(사전 정규식 캐시·묶음 경계 — P §6 구현 주의)."""
        sur, giv = "김이박최정강조윤장임한오서신권황", "가나다라마바사아자차카타파하"
        persons = {s + a + b: f"{i:016x}" for i, (s, a, b) in
                   enumerate((s, a, b) for s in sur for a in giv for b in giv)}
        custs = [{"id": f"C{i:02d}", "names": [f"고객사{i:02d}", f"Cust{i:02d}"], "domains": [f"c{i:02d}.example"]}
                 for i in range(60)]
        ctx = SanitizeContext(persons=persons, customers=custs, internal_domains=["corp.example"])
        texts = [t for t, _ in _pool()]
        t0 = time.perf_counter()
        for i in range(ROWS):
            sanitize(texts[i % len(texts)], ctx=ctx)
        dt = time.perf_counter() - t0
        self.assertGreater(len(persons), 3000)
        self.assertLessEqual(dt, selftest.PERF_ROW_SEC, f"{ROWS}행 {dt:.2f}s")

    def test_long_prompt_scan(self):
        """최종 프롬프트(8,000자 기본 상한)를 scan 해도 빠르다(조각 탐지)."""
        text = ("[과제:P-0001] 시험 결과 공유 [금액] 검토\n" * 300)[:8000]
        ms = min(self._time(lambda: scan(text)) for _ in range(3))
        self.assertLessEqual(ms, 200.0, f"{ms:.1f}ms")

    @staticmethod
    def _time(fn):
        t0 = time.perf_counter()
        fn()
        return (time.perf_counter() - t0) * 1000.0


if __name__ == "__main__":
    unittest.main()
