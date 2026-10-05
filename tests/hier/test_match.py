# -*- coding: utf-8 -*-
"""WP-21 토큰화·키워드 매칭 시험 — H §4.3 · §8.1 · HG43 · X-050 · X-051.

입력 문장은 정제문 모양의 합성 문장(과제A·고객사A·[과제:P-0007] 자리표시자)만 쓴다.
"""
import json
import re
import unittest
from pathlib import Path

from lm27.config import load_config, registry_meta
from lm27.hier import match as M

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "tests" / "fixtures" / "wp21"
REG = ROOT / "config" / "settings_registry.json"
WORDS = ROOT / "lm27" / "hier" / "data" / "common_words.txt"


class KwHitTest(unittest.TestCase):
    def test_hg43_golden(self):
        g = json.loads((FIX / "golden_hg.json").read_text(encoding="utf-8"))
        for k, toks, mode, want in g["HG43_kw"]:
            with self.subTest(k=k, mode=mode):
                self.assertEqual(M.kw_hit(k, set(toks), mode), want)

    def test_name_mode_front_boundary_only(self):
        self.assertTrue(M.kw_hit("브라켓", {"브라켓을"}, "name"))
        self.assertFalse(M.kw_hit("해석", {"열해석"}, "name"))
        self.assertTrue(M.kw_hit("해석", {"열해석"}, "head"))
        self.assertTrue(M.kw_hit("해석", {"구조열해석"}, "head"))       # 접두 3자 — 합성어 머리
        self.assertFalse(M.kw_hit("해석", {"대구조열해석"}, "head"))    # 접두 4자 > 3 — 아님

    def test_ascii_rules(self):
        self.assertTrue(M.kw_hit("lidar", {"lidar"}, "name"))
        self.assertFalse(M.kw_hit("pcb", {"pcba"}, "name"))               # 4자 미만은 정확 일치만
        self.assertTrue(M.kw_hit("module", {"modules"}, "name"))         # 4자 이상 앞 경계
        self.assertTrue(M.kw_hit("calibration", {"calibraton"}, "name"))  # 5자 이상 유사도 0.9
        self.assertFalse(M.kw_hit("x", {"x"}, "name"))                    # 2자 미만 조각뿐 → 거짓

    def test_multi_part_all_needed(self):
        self.assertFalse(M.kw_hit("광학 모듈", {"광학"}, "name"))
        self.assertTrue(M.kw_hit("광학 모듈", {"광학", "모듈"}, "name"))

    def test_bad_mode(self):
        with self.assertRaises(ValueError):
            M.kw_hit("x", set(), "fuzzy")


class TokensTest(unittest.TestCase):
    def test_match_tokens_basic(self):
        t = M.match_tokens("RE: FW: [과제:P-0007] 브라켓 체결부 검토 부탁드립니다")
        self.assertEqual(t, {"브라켓", "체결부"})

    def test_drops_versions_digits_short_and_special(self):
        t = M.match_tokens("공차해석_v3 rev2 r1 20261005 2026 a [금액] [사람#a1b2c3] 결과정리.xlsx")
        self.assertEqual(t, {"공차해석", "결과정리", "xlsx"})

    def test_boilerplate_param(self):
        self.assertIn("광축", M.match_tokens("광축 정렬"))
        self.assertNotIn("광축", M.match_tokens("광축 정렬", boiler=frozenset({"광축"})))

    def test_name_is_not_scan_tokens_of(self):
        # X-051: 정제기 scan.tokens_of 와 이름이 겹치지 않게 match_tokens
        self.assertFalse(hasattr(M, "tokens_of"))

    def test_ent_tokens(self):
        e = M.ent_tokens("[과제:P-0007] [고객사:C01] [협력사:V01] [과제:L-0001] [사람#abcdef]")
        self.assertEqual(e, {"과제": {"P-0007", "L-0001"}, "고객사": {"C01"}, "협력사": {"V01"}})

    def test_ent_token_id_len_16(self):
        # X-050: 토큰 안 ID 는 16자 이하
        ok = "A" + "b" * 15
        bad = "A" + "b" * 16
        self.assertEqual(M.ent_tokens(f"[과제:{ok}]")["과제"], {ok})
        self.assertEqual(M.ent_tokens(f"[과제:{bad}]")["과제"], set())

    def test_ai_hit(self):
        self.assertTrue(M.ai_hit("LLM 기반 AI 분류"))
        self.assertTrue(M.ai_hit("ai-기반"))
        self.assertFalse(M.ai_hit("email 정리"))
        self.assertFalse(M.ai_hit("detail 검토"))


class BoilerplateTest(unittest.TestCase):
    def test_default_from_settings_registry(self):
        base = {str(w).lower() for w in registry_meta("episode.tokens.boilerplate").default}
        bp = M.boilerplate()
        self.assertTrue(base <= bp)
        self.assertTrue(set(M.H_BOILERPLATE) <= bp)

    def test_cfg_reads_and_add(self):
        cfg = load_config(registry_path=REG, config_path=ROOT / "tests" / "fixtures" / "wp21" / "_none.json",
                          overrides={"hier.tokens.boilerplateAdd": ["광축"]})
        bp = M.boilerplate(cfg)
        self.assertIn("광축", bp)
        self.assertIn("검토", bp)
        used = cfg.used()
        self.assertIn("episode.tokens.boilerplate", used)
        self.assertIn("hier.tokens.boilerplateAdd", used)
        self.assertNotIn("광축", M.match_tokens("광축 정렬", boiler=bp))


class CommonWordsTest(unittest.TestCase):
    def test_file_encoding_and_size(self):
        raw = WORDS.read_bytes()
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
        self.assertNotIn(b"\r", raw)
        words = M.common_words()
        self.assertGreaterEqual(len(words), 250)
        for w in ("회의", "보고", "일정", "검토", "설계", "해석", "시험", "자료", "요청", "공유"):
            self.assertIn(w, words)

    def test_neutral_words_only(self):
        # 사내 어휘·이메일·주소·코드네임 모양(영대문자+숫자)이 없다
        for w in M.common_words():
            self.assertNotIn("@", w)
            self.assertIsNone(re.fullmatch(r"[a-z]{1,8}[-_]?\d{1,4}[a-z]?", w), w)
            self.assertEqual(w, w.lower())


if __name__ == "__main__":
    unittest.main()
