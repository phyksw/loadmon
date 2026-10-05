# -*- coding: utf-8 -*-
"""WP-19 토큰·문서군 키(lm27.time.tokens) — fam 재수출, 범용 판정, fam_key(계약 §4.3), raw_tokens, tok_sim(W §4.1)."""
from __future__ import annotations

import unittest

from tests.time import scenarios as X        # 가짜 계약 함수 설치(없는 WP 의 doc_fam 등)

from lm27.time import tokens as T

DK = "d" + "0123456789abcdef"
S1, S2, S3 = "s" + "1" * 16, "s" + "2" * 16, "s" + "3" * 16


class FamTest(unittest.TestCase):
    def test_fam_is_doc_fam_reexport(self):
        import lm27.privacy.keys as K
        for name in ("검토보고서_과제A_열해석_v2.pptx", "하우징_과제D.prt.12", "결과.cas.gz", "보고서 (2).pptx",
                     "도면_최종.dwg", "자료_20261014.xlsx"):
            self.assertEqual(T.fam(name), K.doc_fam(name))
        self.assertEqual(T.fam(""), "")

    def test_fam_rules_w41(self):
        self.assertEqual(T.fam("검토보고서_과제A_열해석_v2.pptx"), "검토보고서_과제a_열해석")
        self.assertEqual(T.fam("하우징_과제D.prt.12"), "하우징_과제d")
        self.assertEqual(T.fam("결과.cas.gz"), "결과")
        self.assertEqual(T.fam("도면_최종_v3.dwg"), "도면")


class GenericTest(unittest.TestCase):
    def setUp(self):
        self.cfg = X.base_cfg()

    def test_is_generic(self):
        for name in ("보고서.pptx", "보고서_v2.pptx", "새 Microsoft Excel 워크시트 (3).xlsx", "Book1.xlsx",
                     "문서 2.docx", "untitled.txt", "제목 없음.png"):
            self.assertTrue(T.is_generic(name, self.cfg), name)
        for name in ("주간보고.xlsx", "회의록_과제A.docx", "견적검토.xlsx", None, ""):
            self.assertFalse(T.is_generic(name, self.cfg), name)

    def test_generic_stems_from_cfg_list_merge(self):
        c = self.cfg.derive({"episode.docs.genericStems": {"add": ["주간보고"], "disable": ["보고서"]}})
        self.assertTrue(T.is_generic("주간보고.xlsx", c))
        self.assertFalse(T.is_generic("보고서.pptx", c))
        self.assertIn("episode.docs.genericStems", c.used())

    def test_fam_key_contract_43(self):
        cfg = self.cfg
        self.assertEqual(T.fam_key(DK, "견적검토.xlsx", [S1, S2], cfg), DK)               # 범용 아님 → doc_key
        self.assertEqual(T.fam_key(DK, "보고서.pptx", [S1, S2, S3], cfg), DK + "@" + S1 + "+" + S2)
        self.assertEqual(T.fam_key(DK, "보고서.pptx", [S1], cfg), DK + "@" + S1)
        self.assertEqual(T.fam_key(DK, "보고서.pptx", [], cfg), T.B_GENERIC)              # 폴더 없음 → B_GENERIC
        self.assertEqual(T.fam_key(DK, "보고서.pptx", None, cfg), T.B_GENERIC)
        self.assertEqual(T.fam_key(DK, None, [S1], cfg), DK)                               # 이름 모름 → 키 그대로
        self.assertEqual(T.fam_key("r" + "a" * 16, "보고서", [S1], cfg), "r" + "a" * 16)    # git 저장소 키(X-216)
        self.assertEqual(T.fam_key(None, "보고서.pptx", [S1], cfg), "")
        # 같은 범용 이름, 다른 폴더 → 다른 키(다른 폴더의 같은 이름을 가른다)
        self.assertNotEqual(T.fam_key(DK, "보고서.pptx", [S1], cfg), T.fam_key(DK, "보고서.pptx", [S2], cfg))

    def test_is_generic_key(self):
        self.assertTrue(T.is_generic_key(T.B_GENERIC))
        self.assertTrue(T.is_generic_key(DK + "@" + S1))
        self.assertTrue(T.is_generic_key(""))
        self.assertFalse(T.is_generic_key(DK))


class RawTokensTest(unittest.TestCase):
    def setUp(self):
        self.cfg = X.base_cfg()
        self.boiler = T.boilerplate(self.cfg)

    def test_split_lower_drop_short_version_boilerplate(self):
        got = T.raw_tokens(["RE 견적_검토 부탁드립니다", "v2", "Rev3 2026 x", "열해석.결과정리"], self.boiler)
        self.assertEqual(got, {"견적", "열해석", "결과정리"})

    def test_privacy_tokens_entity_kept_category_dropped(self):
        got = T.raw_tokens(["[과제:P-0001]", "샘플 [전화] [사람] [사람#a1b2c3] 결과", "[고객사:C01]_사양"], self.boiler)
        self.assertEqual(got, {"[과제:p-0001]", "샘플", "[사람#a1b2c3]", "[고객사:c01]", "사양"})

    def test_nfkc(self):
        self.assertEqual(T.raw_tokens(["ＡＢＣ"], ()), {"abc"})

    def test_boilerplate_cfg_merge(self):
        c = self.cfg.derive({"episode.tokens.boilerplate": {"add": ["사양"]}})
        self.assertNotIn("사양", T.raw_tokens(["사양 검토"], T.boilerplate(c)))
        self.assertEqual(T.min_sub_len(c), 2)


class TokSimTest(unittest.TestCase):
    def test_korean_compound_substring(self):
        self.assertEqual(T.tok_sim({"견적"}, {"견적검토"}), 1.0)                 # W23: Jaccard 였다면 0
        self.assertEqual(T.tok_sim({"원가"}, {"일정"}), 0.0)
        self.assertEqual(T.tok_sim(set(), {"x"}), 0.0)
        self.assertAlmostEqual(T.tok_sim({"모터", "사양"}, {"모터", "브라켓"}), 0.5)

    def test_min_sub_len(self):
        self.assertEqual(T.tok_sim({"ab"}, {"abc"}, 2), 1.0)
        self.assertEqual(T.tok_sim({"ab"}, {"abc"}, 3), 0.0)                   # 너무 짧은 조각은 포함으로 안 봄
        self.assertEqual(T.tok_sim({"ab"}, {"ab"}, 9), 1.0)                    # 완전 일치는 늘 일치

    def test_symmetric(self):
        a, b = {"하네스", "시험", "x"}, {"하네스시험", "결과"}
        self.assertEqual(T.tok_sim(a, b), T.tok_sim(b, a))


if __name__ == "__main__":
    unittest.main()
