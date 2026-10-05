# -*- coding: utf-8 -*-
"""WP-21 영역·어휘 단일원 시험 — H §1.2~§1.6 · §2.3.4 · HG40 · G-H11 · G-H13 · 계약 §6.6 · X-230~X-232 · X-242.

G-H11(L-25): 영역 이름·색 문자열은 `lm27\\hier\\vocab.py` 의 DOMAIN_META 밖 제품 코드에 0.
G-H13(L-24): 저장소 기본값(내장 유효 레지스트리·설정 선언)에 과제·별칭·코드네임·키워드·규칙·카탈로그 0.
"""
import ast
import json
import re
import unittest
from pathlib import Path

from lm27.config import registry_meta
from lm27.hier import registry as R
from lm27.hier import registry_schema as RS
from lm27.hier import vocab as V
from lm27.vocab import steps as S

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "tests" / "fixtures" / "wp21"
CONTRACT = ROOT / "docs" / "CONTRACT.md"

COLORS = {"DEV": "#2a78d6", "MP": "#c47400", "EXT": "#0e8c7a", "COM": "#a61b4a", "AX": "#6c4fb8", "UNC": "#8b929b"}


class DomainMetaTest(unittest.TestCase):
    def test_codes_order_colors(self):
        self.assertEqual(set(V.DOMAIN_META), set(V.ALL_DOMAINS))
        self.assertEqual(V.DOMAINS, ("DEV", "MP", "EXT", "COM", "AX"))
        self.assertEqual(V.DOMAIN_ORDER, ("DEV", "MP", "EXT", "COM", "AX", "UNC"))
        for c, col in COLORS.items():
            self.assertEqual(V.domain_color(c), col)
        self.assertEqual([V.domain_order(c) for c in V.DOMAIN_ORDER], [0, 1, 2, 3, 4, 9])

    def test_colors_match_contract(self):
        # 계약 §6.6 영역 색 = R 대비 검증값(X-242)
        if not CONTRACT.is_file():
            self.skipTest("계약 문서 없음")
        row = next(ln for ln in CONTRACT.read_text(encoding="utf-8").splitlines() if ln.startswith("| 영역 색 |"))
        got = dict(re.findall(r"([A-Z]{2,3}) `(#[0-9a-f]{6})`", row))
        self.assertEqual(got, COLORS)
        names_row = next(ln for ln in CONTRACT.read_text(encoding="utf-8").splitlines()
                         if ln.startswith("| 업무 영역 |"))
        for c in V.ALL_DOMAINS:
            self.assertIn(f"`{c}` {V.domain_name(c)}", names_row)

    def test_unknown_code_is_unc(self):
        self.assertEqual(V.domain_name("ZZ"), V.domain_name("UNC"))
        self.assertEqual(V.domain_color(None), V.domain_color("UNC"))
        self.assertEqual(V.domain_order("ZZ"), 9)
        self.assertEqual(V.domain_keywords("ZZ"), ())

    def test_prompt_line(self):
        line = V.domain_prompt_line()
        self.assertTrue(line.startswith("[업무영역] DEV "))
        self.assertEqual(line.count(" · "), 4)
        self.assertNotIn("UNC", line)
        for c in V.DOMAINS:
            self.assertIn(f"{c} {V.domain_name(c)}", line)

    def test_snap_domain(self):
        cases = {"DEV": "DEV", "dev": "DEV", "AX": "AX", "UNC": "UNC", V.domain_name("MP"): "MP",
                 V.domain_name("EXT").replace(" ", ""): "EXT", "양산": "MP", "제조": "MP", "선행": "DEV",
                 "국책": "EXT", "공통": "COM", "ai": "AX", "자동화": "AX", "agentic": "AX",
                 "지원": "", "교육": "", "xx": "", "": "", None: "", "개발 양산": ""}
        for s, want in cases.items():
            with self.subTest(s=s):
                self.assertEqual(V.snap_domain(s), want)

    def test_reserved(self):
        self.assertEqual(V.RESERVED, {"P-9901": "DEV", "P-9902": "MP", "P-9903": "EXT", "P-9904": "COM",
                                      "P-9905": "AX"})
        for pid, dom in V.RESERVED.items():
            self.assertEqual(V.RESERVED_BY_DOMAIN[dom], pid)
            self.assertEqual(V.reserved_name(pid), f"{V.domain_name(dom)} 일반")
            self.assertEqual(V.reserved_desc(pid), f"({V.domain_name(dom)} — 과제 미지정)")
        self.assertTrue(V.is_reserved_id("P-9999"))
        self.assertFalse(V.is_reserved_id("P-0999"))
        self.assertFalse(V.is_reserved_id("P-99x1"))

    def test_keywords_and_ax_strong(self):
        self.assertIn("보안교육", V.domain_keywords("COM"))
        self.assertIn("기술지도", V.domain_keywords("EXT"))
        self.assertTrue(V.AX_STRONG <= set(V.domain_keywords("AX")))
        self.assertEqual(V.domain_desc("COM"), V.DOMAIN_META["COM"]["desc"])


class VocabTest(unittest.TestCase):
    def test_builtin_sizes_and_codes(self):
        self.assertEqual(V.builtin_codes("fields"), ("MECH", "ELEC", "SW", "OPT", "THERM", "REL", "PROC", "QA", "SYS",
                                                      "ETC"))
        self.assertEqual(V.builtin_codes("functions"),
                         ("DESIGN", "IMPL", "ANALYSIS", "TEST", "OUTSRC", "PURCHASE", "DOC", "MEET", "PM", "TRANSFER",
                          "SUPPORT", "STUDY", "ADMIN", "ETC"))
        self.assertEqual(V.builtin_codes("activity_types"), ("DEV", "OFFICE", "FIELD", "PM", "PL", "SUPPORT", "EDU"))
        self.assertEqual(V.builtin_codes("step_types"), S.STEP_ORDER)               # X-243: 원천은 vocab.steps
        for kind in V.VOCAB_KINDS:
            for it in V.BUILTIN_VOCAB[kind]:
                self.assertRegex(it.code, r"^[A-Z][A-Z0-9_]{1,15}$")
                self.assertTrue(1 <= len(it.name) <= 20, it)
                self.assertLessEqual(len(it.keywords), 30)
                for e in it.exts:
                    self.assertRegex(e, RS.EXT_RX)               # 내장 값도 팀 스키마를 통과해야 한다
                for a in it.apps:
                    self.assertRegex(a, RS.APP_ID_RX)
                for k in it.keywords:
                    self.assertTrue(2 <= len(k) <= 40, k)

    def test_step_items_carry_scores(self):
        for it in V.BUILTIN_VOCAB["step_types"]:
            st = S.STEP_TYPES[it.code]
            self.assertEqual((it.tool_access, it.verifiable, it.kind, it.cls),
                             (st.tool_default, st.verify_default, st.kind, st.cls))

    def test_hg40_legacy(self):
        g = json.loads((FIX / "golden_hg.json").read_text(encoding="utf-8"))
        got = [V.legacy_code(n, k) for n, k in g["HG40_input"]]
        self.assertEqual(got, g["HG40_legacy_vocab"])

    def test_legacy_more(self):
        self.assertEqual(V.legacy_code("의뢰수신", "step_types"), "REQ_IN")     # TAB 예시 한글 값 → 코드(X-230)
        self.assertEqual(V.legacy_code("설계", "functions"), "DESIGN")
        self.assertEqual(V.legacy_code("개발", "activity_types"), "DEV")
        self.assertEqual(V.legacy_code("해석 · 분석", "functions"), "ANALYSIS")
        self.assertRegex(V.legacy_code("새 분야", "fields"), r"^X_[0-9A-F]{6}$")
        with self.assertRaises(ValueError):
            V.legacy_code("x", "domains")

    def test_all_vocab_keywords(self):
        kw = V.all_vocab_keywords()
        self.assertIn("설계", kw)
        self.assertIn("보안교육", kw)
        self.assertNotIn("", kw)


def _product_py():
    for p in sorted((ROOT / "lm27").rglob("*.py")):
        if "__pycache__" not in p.parts:
            yield p


class SingleSourceTest(unittest.TestCase):
    """G-H11 — 영역 이름·색 하드코딩 0(DOMAIN_META 밖)."""

    def test_no_domain_names_or_colors_elsewhere(self):
        names = {m["name"] for m in V.DOMAIN_META.values()}
        cols = {m["color"] for m in V.DOMAIN_META.values()}
        bad = []
        for p in _product_py():
            rel = p.relative_to(ROOT).as_posix()
            if rel == "lm27/hier/vocab.py":
                continue
            tree = ast.parse(p.read_text(encoding="utf-8"))
            for n in ast.walk(tree):
                if isinstance(n, ast.Constant) and isinstance(n.value, str):
                    v = n.value.strip()
                    if v in names or v.lower() in cols:
                        bad.append(f"{rel}:{n.lineno}")
        self.assertEqual(bad, [])


class DefaultsEmptyTest(unittest.TestCase):
    """G-H13 — 배포 기본값에 과제·별칭·코드네임·키워드·규칙·카탈로그 0."""

    def test_builtin_registry_empty(self):
        reg = R.builtin_registry()
        self.assertEqual(set(reg.projects), set(V.RESERVED))
        for p in reg.projects.values():
            self.assertEqual(p.origin, "reserved")
            self.assertEqual((p.aliases, p.codenames, p.keywords, p.never, p.mail_domains, p.customers,
                              p.partners, p.apps), ((),) * 8)
        self.assertEqual(reg.alias_ix, {})
        self.assertEqual(reg.rules, ())
        self.assertEqual(reg.agents, ())
        self.assertEqual(reg.customers, ())
        self.assertEqual(reg.partners, ())
        self.assertEqual(reg.never_pairs, frozenset())
        self.assertEqual(reg.active_ids(), [])
        self.assertEqual(R.BUILTIN_EMPTY, {"schema": "lm27.registry/1", "version": 0})
        self.assertEqual(reg.privacy_dict()["projects"], [])

    def test_settings_defaults_empty(self):
        for k in ("hier.tokens.boilerplateAdd", "privacy.customers", "privacy.partners", "privacy.internalDomains",
                  "team.offlineDir"):
            self.assertIn(registry_meta(k).default, ("", [], (), {}), k)


if __name__ == "__main__":
    unittest.main()
