# -*- coding: utf-8 -*-
"""WP-30 보고서 화면 어휘 단일원(R §5.8 · §4.4.3 · §4.9 · §4.6 · 계약 §6.1 · §6.6 · RPT-33 · RPT-40).

- 사유 코드 문구 표의 코드 ⊂ 계약 §6.1(L-13), §6.1 의 모든 코드에 문구가 있다, 모르는 코드는 '기타'.
- 영역 이름·색·순서는 `lm27.hier.vocab.DOMAIN_META` 접근 함수 그대로(L-25 — 이 파일에 하드코딩 없음).
- 어휘 이름: 유효 레지스트리(객체·원본 dict) → 내장 순.
- 금지 표현: 화면 문구에 '개발자에게'·'재설치'(RPT-40), '대체 가능'·'절감'·'AX 가능 MM'(RPT-33) 0.
"""
from __future__ import annotations

import os
import re
import unittest
from types import SimpleNamespace

from lm27.hier import vocab as HV
from lm27.report import vocab as V
from lm27.report.analysis import quality as Q
from tests.fixtures.wp30 import world as W

RCODE = re.compile(r"(?<![A-Za-z0-9_-])R-[A-Z]{2,}(?:-[A-Z0-9]+)*(?![A-Za-z0-9_])")


def contract_codes() -> set[str] | None:
    path = os.path.join(W.ROOT, "docs", "CONTRACT.md")
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as f:
        text = f.read()
    m = re.search(r"### 6\.1 사유 코드.*?\n(.*?)\n### 6\.2", text, re.S)
    if not m:
        return None
    rows = [ln for ln in m.group(1).splitlines() if ln.startswith("| R-")]
    out = set()
    for ln in rows:
        first = ln.split("|")[1]
        out |= set(RCODE.findall(first))
    return out


def all_texts() -> list[str]:
    out = []
    for short, text in V.REASON_UI.values():
        out += [short, text]
    for name, text in V.CAUSES.values():
        out += [name, text]
    out += list(V.QUALITY_TEXT.values()) + list(V.WARN_TEXT.values()) + list(V.SUB_WHY.values())
    out += list(V.RULE_WHY.values()) + [a for a, b in V.REC_KINDS.values()] + [b for a, b in V.REC_KINDS.values()]
    out += list(V.CHARTS.values()) + list(V.EXT_CLASS_NAMES.values()) + list(V.AXIS_NAMES.values())
    return out


class ReasonTextTest(unittest.TestCase):
    def test_codes_in_contract(self):
        codes = contract_codes()
        if codes is None:
            self.skipTest("docs\\CONTRACT.md 없음")
        self.assertGreater(len(codes), 40)
        self.assertEqual(set(V.REASON_UI) - codes, set(), "계약 §6.1 에 없는 코드")
        self.assertEqual(codes - set(V.REASON_UI), set(), "화면 문구가 없는 §6.1 코드")

    def test_unknown_code(self):
        code = "R-" + "ZZTEST"                       # 부정 표본은 런타임에 조립(L-13)
        short, text = V.reason_text(code)
        self.assertEqual(short, "기타")
        self.assertEqual(text, f"{code} · 다음 수집에서 다시 확인합니다")
        self.assertEqual(V.reason_short("R-UIAEMPTY"), "팀즈 창 숨김")

    def test_spec_rows_verbatim(self):
        """R §5.8 표의 문장 그대로(대표 행)."""
        self.assertEqual(V.reason_text("R-LOGIN")[1],
                         "분석용 Edge 창에서 회사 계정으로 한 번 로그인해 주세요. 로그인하면 이어서 합니다")
        self.assertEqual(V.reason_text("R-TRANSPORT")[1],
                         "일시적인 연결·프로그램 오류입니다('불가' 판정에 쓰지 않음). 다음에 다시 시도합니다")
        self.assertEqual(V.reason_text("R-NOIDX"), ("색인 꺼짐", "Windows 검색 색인을 쓸 수 없습니다. 다른 경로로 채웁니다"))
        self.assertEqual(V.reason_text("R-NOLIC")[0], V.reason_text("R-NOCONN")[0])

    def test_forbidden_phrases(self):
        texts = "\n".join(all_texts())
        for bad in ("개발자" + "에게", "재" + "설치", "대체 " + "가능", "절" + "감", "AX 가능 " + "MM"):
            self.assertNotIn(bad, texts)


class DomainTest(unittest.TestCase):
    def test_accessors_follow_domain_meta(self):
        for c in HV.DOMAIN_META:
            self.assertEqual(V.domain_name(c), HV.DOMAIN_META[c]["name"])
            self.assertEqual(V.domain_color(c), HV.DOMAIN_META[c]["color"])
            self.assertEqual(V.domain_order(c), HV.DOMAIN_META[c]["order"])
        self.assertEqual([d["code"] for d in V.domains()], ["DEV", "MP", "EXT", "COM", "AX", "UNC"])
        self.assertEqual(V.domain_name("??"), HV.DOMAIN_META["UNC"]["name"])

    def test_no_hardcoded_domain_names_in_source(self):
        path = os.path.join(W.ROOT, "lm27", "report", "vocab.py")
        with open(path, encoding="utf-8") as f:
            src = f.read()
        for c, m in HV.DOMAIN_META.items():
            self.assertNotIn('"' + m["name"] + '"', src, c)
            self.assertNotIn(m["color"], src, c)


class VocabNameTest(unittest.TestCase):
    def test_builtin(self):
        self.assertEqual(V.field_name("ELEC"), "회로")
        self.assertEqual(V.func_name("ANALYSIS"), "해석·분석")
        self.assertEqual(V.wtype_name("DEV"), "개발")
        self.assertEqual(V.step_name("APP_CAE"), "해석 프로그램")
        self.assertEqual(V.field_name("X_ABC123"), "X_ABC123")

    def test_registry_dict_and_object(self):
        reg = {"vocab": {"fields": [{"code": "ELEC", "name": "전기회로"}], "step_types": [
            {"code": "APP_CAE", "name": "해석 도구", "tool_access": 2}]}}
        self.assertEqual(V.field_name("ELEC", reg), "전기회로")
        self.assertEqual(V.step_name("APP_CAE", reg), "해석 도구")
        self.assertEqual(V.func_name("ANALYSIS", reg), "해석·분석")
        obj = SimpleNamespace(vocab={"functions": {"ANALYSIS": SimpleNamespace(name="분석")}})
        self.assertEqual(V.func_name("ANALYSIS", obj), "분석")
        self.assertEqual(V.field_name("ELEC", obj), "회로")


class ClosedVocabTest(unittest.TestCase):
    def test_tables(self):
        self.assertEqual(set(V.CAUSES), {"WAIT", "REWORK", "PARALLEL", "SCOPE", "LATE_START", "DATA", "UNEXPLAINED",
                                         "NO_BASELINE"})
        self.assertEqual(V.ONTO_RELS, ("소속", "의뢰함", "보고함", "산출함", "사용함", "함께함", "선행함", "같은문서",
                                       "같은과제"))
        self.assertEqual(set(V.ONTO_NODES), {"P", "R", "U", "D", "A", "C"})
        self.assertEqual(set(Q.REASONS), set(V.QUALITY_TEXT))
        self.assertEqual(V.FREQ, ("주 3회 이상", "주 1~2회", "월 몇 회", "드묾"))
        self.assertEqual(set(V.SUB_WHY), {"repeat_weekly", "repeat_monthly", "digital_io", "structured_input",
                                          "tool_access", "verifiable", "low_accountability"})
        for k in V.CHARTS:
            self.assertRegex(k, r"^CH-[HPT]\d{2}$")
        self.assertEqual(V.LABEL_BY["manual"], "AI(붙여넣기)")
        w = V.warn("mining_coarse", n=None, unit="u_1")
        self.assertEqual(w, {"code": "mining_coarse", "text_ko": V.WARN_TEXT["mining_coarse"], "unit": "u_1"})


if __name__ == "__main__":
    unittest.main()
