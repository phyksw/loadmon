# -*- coding: utf-8 -*-
"""WP-21 이름 비교 축 시험 — H §9.2 · §2.3.3 · T-H19 · X-233.

자료는 합성 이름(과제A·광센서 같은 자리표시자)만 쓴다.
"""
import unittest

from lm27.hier import names as N


class FoldUkeyTest(unittest.TestCase):
    def test_separators_become_space_then_removed(self):
        for a, b in (("방열 모듈", "방열모듈"), ("방열_모듈", "방열-모듈"), ("방열·모듈", "방열/모듈"),
                     ("방열ㆍ모듈", "방열・모듈"), ("방열–모듈", "방열—모듈"), ("방열－모듈", "방열／모듈")):
            self.assertEqual(N.ukey(a), N.ukey(b), (a, b))
            self.assertEqual(N.ukey(a), "방열모듈")

    def test_t_h19_same_proposal_name(self):
        # T-H19: 제안 '방열 모듈'·'방열모듈' 은 ukey 가 같아 같은 제안이 된다
        self.assertEqual(N.ukey("방열 모듈"), N.ukey("방열모듈"))

    def test_nfkc_and_casefold(self):
        self.assertEqual(N.ukey("ＰＲＯＪ－Ａ"), N.ukey("proj-a"))
        self.assertEqual(N.ukey("Proj A"), "proja")
        self.assertEqual(N.fold("  과제A   모듈 "), "과제a 모듈")

    def test_note_tail_kept_in_ukey_dropped_in_fold(self):
        self.assertEqual(N.ukey("열해석(양산)"), "열해석(양산)")
        self.assertNotEqual(N.ukey("열해석(양산)"), N.ukey("열해석(선행)"))
        self.assertEqual(N.fold("열해석 (양산)"), "열해석")
        self.assertEqual(N.fold("열해석（양산）", drop_note=False), "열해석(양산)")

    def test_none_and_numbers(self):
        self.assertEqual(N.ukey(None), "")
        self.assertEqual(N.fold(None), "")
        self.assertEqual(N.ukey(2026), "2026")

    def test_note(self):
        self.assertEqual(N.note("열해석(양산)"), "양산")
        self.assertEqual(N.note("열해석（Pilot）"), "pilot")
        self.assertEqual(N.note("열해석"), "")

    def test_num_tokens_and_name_toks(self):
        self.assertEqual(N.num_tokens("과제A 2세대 v3"), {"2", "3"})
        self.assertEqual(N.num_tokens("과제A"), set())
        self.assertEqual(N.name_toks("열 해석(양산)"), {"열", "해석(양산)"})

    def test_bigram_dice(self):
        self.assertEqual(N.bigram_dice("열해석", "열 해석"), 1.0)
        self.assertEqual(N.bigram_dice("열해석(양산)", "열해석"), 1.0)      # 괄호 꼬리는 떼고 비교
        d = N.bigram_dice("광학 모듈", "광학모듈 검토")
        self.assertGreater(d, 0.0)
        self.assertLess(d, 1.0)
        self.assertEqual(N.bigram_dice("가나", "다라"), 0.0)
        self.assertAlmostEqual(N.bigram_dice("과제A 일정", "과제A 회의"), N.bigram_dice("과제A 회의", "과제A 일정"))
        self.assertEqual(N.bigram_dice("", ""), 1.0)

    def test_single_source_import(self):
        # X-233: 팀 서버도 같은 함수를 import 한다(사본 금지)
        from lm27.hier.names import ukey
        self.assertIs(ukey, N.ukey)


if __name__ == "__main__":
    unittest.main()
