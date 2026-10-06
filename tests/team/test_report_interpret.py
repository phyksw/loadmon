# -*- coding: utf-8 -*-
"""WP-37 해석 문장(R §7.4.4 TI-01~TI-08) · 표시 숫자(R §3.1 = lm27ui.js) · 표시 메타(decorate) · 설정 read-check(T-14).

RPT-44: 합성 팀 8명(측정 불충분 1명, 9월 개발 비중 +8%p) → TI-01·TI-02·TI-08 골든. 자료는 tests\\fixtures\\wp37(합성)뿐.
"""
import copy
import unittest

from lm27.config import load_config
from lm27.team import report as R
from tests.fixtures.wp37 import teamdata as T


def cfg_with(**over):
    """이 트리 설정 + 덮어쓰기(키는 'teamReport_shiftPp' → 'teamReport.shiftPp')."""
    return load_config(overrides={k.replace("_", "."): v for k, v in over.items()})


GOLDEN = [
    {"code": "TI-01", "text_ko": "기간 동안 개발 프로젝트가 팀 투입의 51%(11.15 MM)로 가장 큽니다(측정 불충분 1명 포함).",
     "refs": {"domain": "DEV"}},
    {"code": "TI-02", "text_ko": "개발 프로젝트 비중이 전월보다 8%p 늘었습니다(2026-08 54% → 2026-09 62%).",
     "refs": {"domain": "DEV", "from": "2026-08", "to": "2026-09"}},
    {"code": "TI-04", "text_ko": "업무 유형으로는 개발이 66%입니다.", "refs": {"activity_type": "DEV"}},
    {"code": "TI-07", "text_ko": "외부 업무지원 단위업무의 중앙 리드타임이 41.9영업일로 가장 깁니다.", "refs": {"domain": "EXT"}},
    {"code": "TI-08", "text_ko": "1명은 측정이 불충분해 비교 집계에서 뺐습니다(합계에는 포함, 빗금).", "refs": {"people": [7]}},
]


class TestInterpretGolden(unittest.TestCase):
    def setUp(self):
        self.td, self.det = T.team8()
        self.cfg = load_config()

    def test_rpt44_golden(self):
        """RPT-44: TI-01(합계 — 측정 불충분 포함 표기)·TI-02(9월 개발 +8%p)·TI-08 문장 골든 + 나머지 조건 문장."""
        self.assertEqual(R.interpret(self.td, self.cfg), GOLDEN)

    def test_deterministic_and_pure(self):
        before = copy.deepcopy(self.td)
        a = R.interpret(self.td, self.cfg)
        b = R.interpret(copy.deepcopy(self.td), self.cfg)
        self.assertEqual(a, b)
        self.assertEqual(self.td, before)                                  # 입력을 바꾸지 않는다

    def test_unreliable_excluded_from_ratios(self):
        """측정 불충분 인원의 몫은 비율 문장(TI-02 등)에 들어가지 않는다 — 그 사람 자료를 바꿔도 같은 문장."""
        td = copy.deepcopy(self.td)
        for d in td["domains"]:
            for cell in d["by_month"].values():
                for bp in cell["by_person"]:
                    if bp[0] == 7:
                        bp[1] = bp[1] * 9                                  # 측정 불충분 사람 몫만 크게
        got = {r["code"]: r["text_ko"] for r in R.interpret(td, self.cfg)}
        self.assertEqual(got["TI-02"], GOLDEN[1]["text_ko"])
        # 같은 자료에서 측정 불충분 표식을 지우면 비율이 달라진다(제외가 실제로 효력이 있다)
        td2 = copy.deepcopy(td)
        td2["quality"]["excluded_from_comparison"] = []
        td2["people"][7]["quality"] = "reliable"
        got2 = {r["code"]: r["text_ko"] for r in R.interpret(td2, self.cfg)}
        self.assertNotEqual(got2.get("TI-02"), GOLDEN[1]["text_ko"])
        self.assertNotIn("TI-08", got2)

    def test_max_six_sentences_in_order(self):
        """모든 조건이 맞으면 R §7.4.4 순서대로 최대 6문장 — TI-07·TI-08 은 잘린다."""
        cfg = cfg_with(teamReport_concentrationShare=0.2, teamReport_officeShareNote=0.05,
                       teamReport_unattributedNote=0.04, teamReport_axLinkNote=0.01)
        rows = R.interpret(self.td, cfg)
        self.assertEqual([r["code"] for r in rows], ["TI-01", "TI-02", "TI-03", "TI-04", "TI-05", "TI-06"])
        by = {r["code"]: r["text_ko"] for r in rows}
        self.assertEqual(by["TI-03"], "회로·시험·검증 역할에 귀속 투입의 24%가 몰려 있습니다.")
        self.assertEqual(by["TI-04"], "업무 유형으로는 사무가 10%입니다.")
        self.assertEqual(by["TI-05"], "근무시간의 5%가 단위업무에 묶이지 않았습니다(근무 중 미분류) — 측정 품질 절을 확인하세요.")
        self.assertTrue(by["TI-06"].startswith("AX 연계 표시가 붙은 업무가 투입의 "), by["TI-06"])
        self.assertTrue(by["TI-06"].endswith("%입니다(개발·양산 영역에 계상)."))

    def test_t14_each_threshold_changes_result(self):
        """T-14: 해석 문턱 키 5개는 섭동하면 결과가 바뀐다(읽히는 키 — 죽은 키 아님)."""
        base = R.interpret(self.td, self.cfg)
        for key, val in (("teamReport.shiftPp", 9.0), ("teamReport.concentrationShare", 0.2),
                         ("teamReport.officeShareNote", 0.05), ("teamReport.unattributedNote", 0.04),
                         ("teamReport.axLinkNote", 0.01)):
            with self.subTest(key=key):
                self.assertNotEqual(R.interpret(self.td, load_config(overrides={key: val})), base)

    def test_ti02_needs_complete_month_and_previous(self):
        td = copy.deepcopy(self.td)
        for e in td["people"][0]["months"]:
            if e["m"] == "2026-09":
                e["partial"] = {"covered_workdays": 3, "workdays": 20}   # 9월이 부분월 → 마지막 완전한 달 = 8월
        codes = [r["code"] for r in R.interpret(td, self.cfg)]
        self.assertNotIn("TI-02", codes)                                    # 7→8월 변화는 1%p
        td["months"] = ["2026-09"]
        self.assertNotIn("TI-02", [r["code"] for r in R.interpret(td, self.cfg)])

    def test_ti02_decrease_wording(self):
        td = copy.deepcopy(self.td)
        for d in td["domains"]:                                             # 8월·9월 영역 값을 맞바꿔 감소로
            if "2026-08" in d["by_month"]:
                d["by_month"]["2026-08"], d["by_month"]["2026-09"] = d["by_month"]["2026-09"], d["by_month"]["2026-08"]
        by = {r["code"]: r["text_ko"] for r in R.interpret(td, self.cfg)}
        self.assertEqual(by["TI-02"], "개발 프로젝트 비중이 전월보다 8%p 줄었습니다(2026-08 62% → 2026-09 54%).")

    def test_ti07_needs_two_domains_with_five(self):
        td = copy.deepcopy(self.td)
        td["units_stats"]["lead_points"] = [p for p in td["units_stats"]["lead_points"] if p["domain"] == "DEV"]
        self.assertNotIn("TI-07", [r["code"] for r in R.interpret(td, self.cfg)])

    def test_empty_and_degenerate(self):
        self.assertEqual(R.interpret({}, self.cfg), [])
        self.assertEqual(R.interpret({"people": [], "months": []}, self.cfg), [])
        self.assertEqual(R.interpret(None, self.cfg), [])
        td = copy.deepcopy(self.td)
        td["quality"]["excluded_from_comparison"] = []
        td["people"][7]["quality"] = "caution"
        self.assertNotIn("TI-08", [r["code"] for r in R.interpret(td, self.cfg)])
        self.assertNotIn("측정 불충분", R.interpret(td, self.cfg)[0]["text_ko"])

    def test_names_fall_back_to_builtin_vocab(self):
        """분야·기능·업무 유형 이름: 팀 데이터 vocab_names → 내장 어휘 → 코드. 영역 이름: domains[].name → DOMAIN_META."""
        td = copy.deepcopy(self.td)
        td["domains"][0]["name"] = "개발(팀 이름)"
        by = {r["code"]: r["text_ko"] for r in R.interpret(td, self.cfg)}
        self.assertTrue(by["TI-01"].startswith("기간 동안 개발(팀 이름)이 팀 투입의 "), by["TI-01"])


class TestFormat(unittest.TestCase):
    """표시 숫자는 lm27ui.js(fmtNum·fmtRatio·pctText)와 글자 단위로 같다(R §3.1 · common_test.js 의 같은 사례)."""

    def test_fmt_ratio_golden(self):
        for (num, den, dg), want in (((9480, 9600, 2), "0.99"), ((11520, 10560, 2), "1.09"), ((4799, 9600, 2), "0.50"),
                                     ((0, 9600, 2), "0.00"), ((9480 * 100, 8880, 0), "107"), ((100, 200, 0), "1")):
            self.assertEqual(R.fmt_ratio(num, den, dg), want)
        self.assertIsNone(R.fmt_ratio(5, 0, 2))

    def test_fmt_num_matches_js(self):
        cases = {(1.15, 1): "1.2", (2.25, 1): "2.3", (13.3, 2): "13.30", (-0.04, 1): "0.0", (-0.06, 1): "−0.1",
                 (0.5, 0): "1", (2.5, 0): "3", (1.005, 2): "1.01", (62.499999, 0): "62", (61.5, 0): "62"}
        for (v, d), want in cases.items():
            self.assertEqual(R.fmt_num(v, d), want, (v, d))
        self.assertIsNone(R.fmt_num(None, 1))
        self.assertIsNone(R.fmt_num(float("nan"), 1))
        self.assertIsNone(R.fmt_num(True, 1))

    def test_pct_texts(self):
        self.assertEqual(R.pct_int_text(1, 300), "0.3")
        self.assertEqual(R.pct_int_text(0, 300), "0")
        self.assertEqual(R.pct_int_text(9480, 8880), "107")
        self.assertIsNone(R.pct_int_text(5, 0))
        self.assertEqual(R.pct_share_text(0.004), "0.4")
        self.assertEqual(R.pct_share_text(0.0), "0")
        self.assertEqual(R.pct_share_text(0.625), "63")
        self.assertEqual(R.days_text(720, 480), "1.5")
        self.assertEqual(R.days_text(1530.5, 480), "3.2")

    def test_josa(self):
        for w, want in (("개발 프로젝트", "가"), ("사무", "가"), ("개발", "이"), ("PM", "이"), ("PL", "이"), ("SW", "가"),
                        ("AX 프로젝트", "가"), ("3", "이"), ("2", "가"), ("현장", "이")):
            self.assertEqual(R.josa(w, "이", "가"), want, w)
        self.assertEqual(R.josa("", "이", "가"), "이(가)")
        self.assertEqual(R.josa("★", "이", "가"), "이(가)")


class TestDecorate(unittest.TestCase):
    def test_domain_meta_vocab_step_view(self):
        td, det = T.team8()
        cfg = load_config()
        out = R.decorate(td, cfg, det)
        self.assertIs(out, td)
        dev = next(d for d in td["domains"] if d["code"] == "DEV")
        self.assertEqual(dev["name"], "개발 프로젝트")
        self.assertRegex(dev["color"], r"^#[0-9a-f]{6}$")
        self.assertEqual(dev["order"], 0)
        vn = td["vocab_names"]
        self.assertEqual(vn["field"]["ELEC"], "회로")                        # 레지스트리 이름이 이긴다
        self.assertEqual(vn["field"]["SW"], "소프트웨어")                    # 내장 어휘로 채움
        self.assertEqual(vn["func"]["IMPL"], "구현")
        self.assertEqual(vn["wtype"]["OFFICE"], "사무")
        self.assertEqual(vn["step"]["DOC_XLS"], "표 계산")
        self.assertEqual((vn["step_kind"]["REQ_IN"], vn["step_kind"]["DOC_XLS"]), ("M", "A"))
        self.assertEqual(td["view"], {"small_project_mm": 0.3, "gantt_expand_rows": 150})
        steps = det["0|" + T.schema.role_id_of("P-0007", "ELEC", "DESIGN")]["workflow"]["steps"]
        self.assertEqual([(s["name"], s["kind"]) for s in steps],
                         [("의뢰 수신", "M"), ("PDF 검토", "A"), ("회로 설계 도구", "A"), ("보고 발신", "M")])
        snap = copy.deepcopy((td, det))
        R.decorate(td, cfg, det)
        self.assertEqual((td, det), snap)                                   # 여러 번 불러도 같다

    def test_original_values_untouched(self):
        td, det = T.team8()
        raw = copy.deepcopy(td)
        R.decorate(td, None, det)
        self.assertNotIn("view", td)                                        # cfg 가 없으면 view 를 만들지 않는다
        for a, b in zip(raw["people"], td["people"], strict=True):
            self.assertEqual(a, b)
        self.assertEqual(raw["gantt"], td["gantt"])


class TestReadCheck(unittest.TestCase):
    def test_all_eight_keys_read(self):
        """T-14 read-check: 해석 + 보고서 만들기 한 번에 teamReport.* 8개가 모두 읽힌다(Cfg.used)."""
        td, det = T.team8()
        cfg = load_config()
        td["interpretation"] = R.interpret(td, cfg)                      # 취합기가 부르는 순서 그대로
        island = dict(td)
        island["details"] = det
        R.render_team_report(island, cfg=cfg)
        used = set(cfg.used())
        self.assertTrue(set(R.CFG_KEYS) <= used, set(R.CFG_KEYS) - used)
        self.assertEqual(sorted(k for k in cfg.keys() if k.startswith("teamReport.")), sorted(R.CFG_KEYS))


if __name__ == "__main__":
    unittest.main()
