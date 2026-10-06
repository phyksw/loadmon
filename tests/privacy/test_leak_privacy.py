# -*- coding: utf-8 -*-
"""정제·저장 누수 관문(W1 통합 창): 정제기(``sanitize``)·레코드 봉인(``sanitize_record``)·로컬 원장 쓰기(``SegmentWriter``)·
읽기(``read_store_since``)를 반복해도 메모리·핸들·임시 파일이 반복 수에 비례해 늘지 않는다(캐시 무한 증가·닫지 않은 파일
없음). 합성 입력만. 30초 이내."""
import unittest

from lm27.privacy import records as R
from lm27.privacy.detect import sanitize
from lm27.store import SegmentWriter, read_store_since
from tests.fixtures.leak import assert_bounded
from tests.fixtures.wp11 import helpers as H


def _text(i: int) -> str:
    # 반복마다 다른 글(같은 글만 되풀이하면 캐시 증가를 못 본다) — 숫자 조합은 런타임에 만든다
    d = f"{i:04d}"
    return f"과제A 견적 {i}번 검토 — 연락 010-{d}-{d[::-1]} · hong{i}@corp.example.com · 금액 {i * 1000}원"


class PrivacyLeak(unittest.TestCase):
    def test_sanitize_repeated_bounded(self):
        def step(i):
            r = sanitize(_text(i))
            self.assertNotIn("010-", r.text)
        assert_bounded(self, step, warm=200, n=1500, mem_per_iter=256)

    def test_store_write_read_cycles_bounded(self):
        sb = H.Sandbox()
        self.addCleanup(sb.cleanup)
        rc = sb.rc("pc.sampler")

        def step(i):
            o = R.sanitize_record("pc_session", H.raw_sampler(ts_utc=f"2026-10-05T{i // 60 % 24:02d}:{i % 60:02d}:00Z",
                                                             fg_title=f"보고서_{i}.docx - Word", fg_doc_name=None), rc)
            w = SegmentWriter(sb.paths, H.PC1, "pc_session", "pc.sampler", clock=lambda: "2026-10-05T03:00:00Z")
            w.append(o.row)
            w.close()
            if i % 20 == 0:
                read_store_since(sb.paths, H.PC1, "pc_session", "pc.sampler", None)
        assert_bounded(self, step, warm=20, n=150, mem_per_iter=8192, handle_slack=12)


if __name__ == "__main__":
    unittest.main()
