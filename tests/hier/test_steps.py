# -*- coding: utf-8 -*-
"""WP-21 단계 유형 어휘 시험 — R §3.3 · 부록 A · 계약 §6.6 · X-241 · X-243.

`lm27.vocab.steps` 의 22종·확장자군·obs_of·도구 접근/검증 가능성 덮어쓰기를 확인한다.
"""
import re
import unittest
from pathlib import Path

from lm27.hier import registry as R
from lm27.vocab import steps as S

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "docs" / "CONTRACT.md"

EXPECT_ORDER = ("REQ_IN", "REQ_OUT", "ACK_OUT", "REPORT_OUT", "REPORT_IN", "COMM", "MEET", "REVIEW", "DOC_DOC",
                "DOC_PPT", "DOC_XLS", "DOC_PDF", "DOC_ETC", "APP_CAD", "APP_CAE", "APP_SIM", "APP_EDA", "APP_IDE",
                "APP_ENG", "COMMIT", "WEB", "OFFLINE")


class TableTest(unittest.TestCase):
    def test_22_codes_in_contract_order(self):
        self.assertEqual(tuple(S.STEP_TYPES), EXPECT_ORDER)
        self.assertEqual(S.STEP_ORDER, EXPECT_ORDER)
        self.assertEqual([S.STEP_TYPES[c].order for c in EXPECT_ORDER], list(range(22)))

    def test_matches_contract_6_6(self):
        if not CONTRACT.is_file():
            self.skipTest("계약 문서 없음")
        text = CONTRACT.read_text(encoding="utf-8")
        row = next(ln for ln in text.splitlines() if ln.startswith("| 단계 유형 step_types(22)"))
        codes = tuple(re.findall(r"`([A-Z_]+)`", row))
        self.assertEqual(codes, EXPECT_ORDER)

    def test_kinds_classes_scores(self):
        self.assertEqual(S.POINT_STEPS, {"REQ_IN", "REQ_OUT", "ACK_OUT", "REPORT_OUT", "REPORT_IN"})
        self.assertEqual(S.CLASSES, ("소통", "회의", "문서", "공학", "코드", "조사", "오프라인"))
        for c, st in S.STEP_TYPES.items():
            self.assertIn(st.cls, S.CLASSES, c)
            self.assertIn(st.tool_default, S.SCORE_RANGE, c)
            self.assertIn(st.verify_default, S.SCORE_RANGE, c)
            self.assertTrue(re.fullmatch(r"[A-Z][A-Z0-9_]{1,15}", c))
            self.assertLessEqual(len(st.name), 20)
        spot = {"REQ_IN": (2, 0), "MEET": (0, 0), "DOC_XLS": (2, 2), "DOC_ETC": (1, 1), "APP_CAE": (1, 2),
                "APP_IDE": (2, 2), "COMMIT": (2, 2), "OFFLINE": (0, 0), "WEB": (2, 1)}
        for c, (t, v) in spot.items():
            self.assertEqual((S.STEP_TYPES[c].tool_default, S.STEP_TYPES[c].verify_default), (t, v), c)


class ExtClassTest(unittest.TestCase):
    def test_table(self):
        cases = {"docx": "doc", ".HWP": "doc", "pptx": "ppt", "xlsm": "xls", "csv": "xls", "pdf": "pdf",
                 "md": "txt", "log": "txt", "sldprt": "cad", "x_t": "cad", "prt.12": "cad", "py": "code",
                 "ipynb": "code", "ps1": "code", "zmx": "", "": "", None: "", "../x": ""}
        for e, want in cases.items():
            with self.subTest(e=e):
                self.assertEqual(S.ext_class(e), want)

    def test_extra_adds_only(self):
        extra = {"zmx": "cad", ".brd": "cad", "pdf": "doc", "dat": "nope"}
        self.assertEqual(S.ext_class("zmx", extra), "cad")
        self.assertEqual(S.ext_class(".brd", extra), "cad")
        self.assertEqual(S.ext_class("pdf", extra), "pdf")          # 기본 표는 바뀌지 않는다
        self.assertEqual(S.ext_class("dat", extra), "")             # 모르는 군은 무시


class ObsOfTest(unittest.TestCase):
    def test_matrix(self):
        cases = [
            (("L1", None, "", None, None), "OFFLINE"),
            (("L2", None, "", None, None), "MEET"),
            (("L2", None, "", None, "review"), "REVIEW"),
            (("L3", "cad", "", None, None), "APP_CAD"),
            (("L3", "cae", "", None, None), "APP_CAE"),
            (("L3", "sim", "", None, None), "APP_SIM"),
            (("L3", "eda", "", None, None), "APP_EDA"),
            (("L3", "ide", "code", None, None), "APP_IDE"),
            (("L3", "eng", "", None, None), "APP_ENG"),
            (("L3", "office", "xls", None, None), "DOC_XLS"),
            (("L3", "office", "doc", None, None), "DOC_DOC"),
            (("L3", "pdf", "pdf", None, None), "DOC_PDF"),
            (("L3", "office", "", None, None), "DOC_ETC"),
            (("L3", "", "ppt", None, None), "DOC_PPT"),
            (("L3", "mail", "", None, None), "COMM"),
            (("L3", "chat_work", "", None, None), "COMM"),
            (("L3", "meet", "", None, None), "MEET"),
            (("L3", "browser", "", None, None), "WEB"),
            (("L3", "explorer", "", None, None), ""),
            (("L3", "other", "", None, None), ""),
            (("L4", None, "", "send", None), "COMM"),
            (("L4", None, "ppt", "save", None), "DOC_PPT"),
            (("L4", None, "", "save", None), "DOC_ETC"),
            (("L4", None, "cad", "export", None), "APP_CAD"),
            (("L4", None, "", "commit", None), "COMMIT"),
            (("L4", None, "", "submit", None), "APP_CAE"),
            (("L4", None, "", "unknown", None), ""),
            (("L5", "cad", "doc", "save", None), ""),
            (("L6", "cad", "doc", None, None), ""),
            (("L7", None, "", None, None), ""),
            (("", "cad", "", None, None), ""),
            (("L3PC", "cad", "", None, None), "APP_CAD"),
            ((3, "cad", "", None, None), "APP_CAD"),
        ]
        for args, want in cases:
            with self.subTest(args=args):
                self.assertEqual(S.obs_of(*args), want)

    def test_never_point_step(self):
        for lv in ("L1", "L2", "L3", "L4", "L5"):
            for cls in ("cad", "office", "mail", "browser", "other", ""):
                for g in ("", *S.EXT_CLASSES):
                    for a in (None, "send", "save", "commit", "submit"):
                        for mr in (None, "review"):
                            v = S.obs_of(lv, cls, g, a, mr)
                            self.assertTrue(v == "" or v in S.ACTIVITY_STEPS, (lv, cls, g, a, mr, v))


class ScoreOverrideTest(unittest.TestCase):
    def test_defaults_and_unknown(self):
        self.assertEqual(S.tool_access("APP_CAE"), 1)
        self.assertEqual(S.verifiable("APP_CAE"), 2)
        self.assertEqual(S.tool_access("NOPE"), 0)
        self.assertEqual(S.verifiable("NOPE"), 0)

    def test_registry_dict_object_list(self):
        reg = {"vocab": {"step_types": [{"code": "APP_CAE", "name": "해석 프로그램", "tool_access": 2},
                                        {"code": "MEET", "name": "회의", "verifiable": 1},
                                        {"code": "WEB", "name": "웹", "tool_access": 3}]}}
        self.assertEqual(S.tool_access("APP_CAE", reg), 2)
        self.assertEqual(S.verifiable("MEET", reg), 1)
        self.assertEqual(S.tool_access("WEB", reg), 2)          # 범위 밖 덮어쓰기는 무시 → 기본값
        self.assertEqual(S.verifiable("APP_CAE", reg), 2)

    def test_old_dict_form_ignored(self):
        # X-241 · R0-7: 옛 step_tool_access 사전 형식은 폐지 — 읽지 않는다
        reg = {"vocab": {"step_tool_access": {"APP_CAE": 2}, "step_verifiable": {"MEET": 2}}}
        self.assertEqual(S.tool_access("APP_CAE", reg), 1)
        self.assertEqual(S.verifiable("MEET", reg), 0)

    def test_effective_registry(self):
        team = {"schema": "lm27.registry/1", "version": 1,
                "vocab": {"step_types": [{"code": "APP_CAE", "name": "해석 프로그램", "tool_access": 2,
                                          "verifiable": 1}]}}
        eff = R.merge(team, None, None)
        self.assertEqual(S.tool_access("APP_CAE", eff), 2)
        self.assertEqual(S.verifiable("APP_CAE", eff), 1)
        self.assertEqual(S.tool_access("APP_SIM", eff), 1)
        builtin = R.builtin_registry()
        self.assertEqual(S.tool_access("APP_CAE", builtin), 1)


if __name__ == "__main__":
    unittest.main()
