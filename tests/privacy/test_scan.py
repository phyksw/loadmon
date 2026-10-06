# -*- coding: utf-8 -*-
"""WP-10 ``scan()``·``tokens_of()`` 시험 — P-T25(S01~S06) · P-T26(K01~K04), 값·위치를 돌려주지 않음(I8),
LM27 보강: 4,000자보다 긴 글(최종 프롬프트 등)도 끝까지 탐지."""
import dataclasses
import unittest

from lm27.privacy import selftest
from lm27.privacy.detect import MAX_SCAN, SanitizeContext, sanitize
from lm27.privacy.scan import SEAM, Hit, scan, tokens_of
from tests.fixtures.canary import canaries

CORPUS = selftest.load_corpus()
EXT = {r["id"]: r for r in CORPUS if r["type"] == "ext"}


def _ctx(d):
    return SanitizeContext(**d) if d else SanitizeContext()


def _canary(cat):
    return next(c for c in canaries() if c.cat == cat)


class ScanCorpusTest(unittest.TestCase):
    def test_S01_to_S05(self):
        for i in range(1, 6):
            r = EXT[f"S0{i}"]
            with self.subTest(rid=r["id"]):
                self.assertEqual(scan(r["arg"]), [Hit(c, n) for c, n in r["expect"]])

    def test_S06_masked_positive_scans_empty(self):
        """S06: 양성 60건(+ 2026.10.1 회귀 양성 15건)의 정제문을 다시 scan → 전부 빈 목록(멱등의 다른 표현)."""
        n = 0
        for r in (x for x in CORPUS if x["type"] == "pos"):
            ctx = _ctx(r.get("ctx"))
            with self.subTest(rid=r["id"]):
                self.assertEqual(scan(sanitize(r["text"], ctx=ctx).text, ctx), [])
            n += 1
        self.assertEqual(n, 75)

    def test_path_in_multiline_prompt_counted_2026_10_1(self):
        """W1 통합 창 결함 회귀: 줄바꿈·뒤따르는 ':'·한 줄 두 경로·'/' 경로를 최종 프롬프트 검사(scan)가 센다."""
        bs = chr(92)
        p = bs.join(("C:", "Users", "hong", "Desktop", "견적.xlsx"))
        q = bs.join(("D:", "share", "b.xlsx"))
        cases = [("목록\n" + p + "\n" + p + "\n끝", 2), (p + " 수정일: 9월 30일", 1), (p + " 와 " + q + " 비교", 2),
                 ("C:/Users/hong/Documents/a.xlsx", 1), ("file:///C:/Users/hong/a/b.xlsx", 1)]
        for text, n in cases:
            with self.subTest(n=n, size=len(text)):
                self.assertEqual(scan(text), [Hit("path", n)])
                self.assertNotIn("Users", sanitize(text).text)

    def test_no_values_in_hits(self):
        """Hit 에는 범주·건수만 — 값·위치 필드가 없다(I8)."""
        self.assertEqual([f.name for f in dataclasses.fields(Hit)], ["cat", "n"])
        c = _canary("phone")
        got = scan(c.sentence)
        self.assertEqual(got, [Hit("phone", 1)])
        self.assertNotIn(c.value, repr(got))

    def test_sorted_and_counts(self):
        a, b = _canary("phone"), _canary("account")
        got = scan(b.sentence + " / " + a.sentence + " / " + a.sentence.replace(a.value, _canary("phone_voip").value))
        self.assertEqual([h.cat for h in got], sorted(h.cat for h in got))
        self.assertIn(Hit("phone", 2), got)

    def test_credential_short_circuit(self):
        self.assertEqual(scan(EXT["S03"]["arg"]), [Hit("cred", 1)])

    def test_empty(self):
        self.assertEqual(scan(""), [])
        self.assertEqual(scan(None), [])


class LongTextScanTest(unittest.TestCase):
    """sanitize() 는 앞 4,000자만 본다 — scan() 은 긴 글(코파일럿 최종 프롬프트 8,000자 등)도 끝까지 본다."""

    def test_pii_after_4000_chars_detected(self):
        c = _canary("phone")
        text = ("가나다 업무 기록\n" * 600) + c.sentence + "\n"
        self.assertGreater(text.index(c.value), MAX_SCAN)
        self.assertEqual(sanitize(text).hits, {})                     # 한 필드 정제는 앞 4,000자만
        self.assertEqual(scan(text), [Hit("phone", 1)])

    def test_single_long_line_boundary(self):
        c = _canary("phone")
        for off in (MAX_SCAN - SEAM - 5, MAX_SCAN - 7, MAX_SCAN - 3, MAX_SCAN + 10):
            text = "가" * off + " " + c.value + " " + "나" * 3000
            with self.subTest(off=off):
                got = scan(text)
                self.assertTrue(got and got[0].cat == "phone")

    def test_long_clean_text_empty(self):
        self.assertEqual(scan("견적 [금액] 검토 요청\n" * 900), [])

    def test_long_credential(self):
        x = EXT["S03"]["arg"]
        self.assertEqual(scan("가\n" * 3000 + x), [Hit("cred", 1)])


class TokensTest(unittest.TestCase):
    def test_K01_to_K04(self):
        for k in ("K01", "K02", "K04"):
            r = EXT[k]
            with self.subTest(rid=k):
                self.assertEqual(tokens_of(r["arg"]), r["expect"])
        self.assertEqual(len(tokens_of(EXT["K03"]["arg"])), EXT["K03"]["expect"])

    def test_token_kept_whole_and_word_cut(self):
        self.assertEqual(tokens_of("[이메일@고객사:C01] 회신"), ["[이메일@고객사:C01]", "회신"])
        self.assertEqual(tokens_of("a" * 30), ["a" * 24])
        self.assertEqual(tokens_of("가 나 다", max_tokens=2), ["가", "나"])
        self.assertEqual(tokens_of(None), [])

    def test_deterministic(self):
        s = "RE: [과제:P-0001] 시험 결과 공유"
        self.assertEqual(tokens_of(s), tokens_of(s))


if __name__ == "__main__":
    unittest.main()
