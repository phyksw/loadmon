# -*- coding: utf-8 -*-
"""WP-30 표시 함수·나눗셈 단일원(R §3.1 · §3.2 · RPT-11 · RPT-14 · G-R11).

- RPT-11(파이썬 쪽): `tests\\fixtures\\wp28\\fmt_js.json`(JS 판 결과 11,530 사례)과 글자 단위로 같다. node 가 있으면
  W1a CR 의 짝 함수(fmt_num·fmt_x·pct_text·share_text·h_text·mm_text·days_text·fmt_signed)도 `web\\common\\lm27ui.js` 와 대조.
- RPT-14: 영업 분 골든 180 · 60 · 1920(2026-09 검증 달력).
- 산식 도우미: half-up·중앙값·75 백분위(최근순위)·자카드·최대잉여(동률 O 먼저).
- G-R11: WP-30 소유 보고서 모듈(fmt.py 제외)에 `round(` 호출·`/` 나눗셈 0.
"""
from __future__ import annotations

import ast
import json
import os
import random
import shutil
import subprocess
import unittest
from datetime import date
from fractions import Fraction

from lm27.report import fmt as F
from tests.fixtures.wp30 import world as W

ROOT = W.ROOT
OWNED = ("lm27/report/vocab.py", "lm27/report/analysis/__init__.py", "lm27/report/analysis/activity.py",
         "lm27/report/analysis/mining.py", "lm27/report/analysis/review.py", "lm27/report/analysis/peers.py",
         "lm27/report/analysis/ontology.py", "lm27/report/analysis/agentic.py", "lm27/report/analysis/subagent.py",
         "lm27/report/analysis/quality.py", "lm27/report/analysis/ai_items.py")


def _p(*parts) -> str:
    return os.path.join(ROOT, *parts)


class CrossJsTest(unittest.TestCase):
    """RPT-11 — 파이썬 판 = JS 판(교차 사례 파일)."""

    def test_fmt_js_cases(self):
        path = _p("tests", "fixtures", "wp28", "fmt_js.json")
        if not os.path.isfile(path):
            self.skipTest("WP-28 교차 사례 파일 없음")
        with open(path, encoding="utf-8") as f:
            js = json.load(f)
        bad, n = [], 0
        for m, v in js["h1"].items():
            n += 1
            if F.fmt_h1(int(m)) != v:
                bad.append(("h1", m))
        for k, v in js["mm2"].items():
            a, b = map(int, k.split("/"))
            n += 1
            if F.fmt_ratio(a, b, 2) != v or F.fmt_mm(a, b) != v:
                bad.append(("mm2", k))
        for k, v in js["pct0"].items():
            a, b = map(int, k.split("/"))
            n += 1
            if F.fmt_pct(a, b) != v:
                bad.append(("pct0", k))
        self.assertEqual(n, 11530)
        self.assertEqual(bad, [])

    def test_node_pair_functions(self):
        """W1a CR(WP-28) — fmtNum·fmtX·pctText·shareText 등 JS 짝과 같은 글자(node 가 있을 때만)."""
        node = shutil.which("node")
        js = _p("web", "common", "lm27ui.js")
        if not node or not os.path.isfile(js):
            self.skipTest("node 또는 lm27ui.js 없음(개발 PC 전용 교차 시험)")
        rnd = random.Random(30)
        nums = [0, 0.0, 0.5, 1, 1.8, 2.25, 2.35, 3.005, 0.0049999, -0.004, -1.25, 1e-7, 123.456789, 0.56, 0.28,
                1 / 3, 2 / 3, 1.0909090909090908, 114.28571428571428, None, "x", True]
        nums += [rnd.uniform(-50, 50) for _ in range(300)] + [rnd.randint(0, 5000) / 1000 for _ in range(300)]
        shares = [0, 0.56, 0.0005, 0.0015, 0.999, 1, 0.125, 0.3335, None] + [rnd.random() for _ in range(300)]
        pairs = [(0, 100), (1, 200), (1, 199), (5, 1000), (9480, 8880), (3, 0), (None, 5)] + \
            [(rnd.randint(0, 3000), rnd.randint(1, 3000)) for _ in range(300)]
        mins = [None, 0, 3, 59, 87, 9483] + [rnd.randint(0, 20000) for _ in range(200)]
        payload = {"nums": nums, "shares": shares, "pairs": pairs, "mins": mins}
        script = (
            "const u=require(process.argv[1]);let s='';process.stdin.on('data',d=>s+=d);"
            "process.stdin.on('end',()=>{const p=JSON.parse(s);const o={};"
            "o.num1=p.nums.map(v=>u.fmtNum(v,1));o.num2=p.nums.map(v=>u.fmtNum(v,2));o.x=p.nums.map(v=>u.fmtX(v));"
            "o.share=p.shares.map(v=>u.shareText(v));o.pct=p.pairs.map(a=>u.pctText(a[0],a[1]));"
            "o.h=p.mins.map(v=>u.hText(v));o.days=p.mins.map(v=>u.daysText(v,480));"
            "o.mm=p.pairs.filter(a=>a[0]!==null).map(a=>u.mmText(a[0],a[1]));"
            "o.signed=p.nums.filter(v=>typeof v==='number').map(v=>u.fmtSigned(u.fmtNum,v,1));"
            "process.stdout.write(JSON.stringify(o));});")
        r = subprocess.run([node, "-e", script, js], input=json.dumps(payload).encode("utf-8"), capture_output=True,
                           timeout=60, check=False)
        self.assertEqual(r.returncode, 0, r.stderr.decode("utf-8", "replace")[:500])
        o = json.loads(r.stdout.decode("utf-8"))
        self.assertEqual(o["num1"], [F.fmt_num(v, 1) for v in nums])
        self.assertEqual(o["num2"], [F.fmt_num(v, 2) for v in nums])
        self.assertEqual(o["x"], [F.fmt_x(v) for v in nums])
        self.assertEqual(o["share"], [F.share_text(v) for v in shares])
        self.assertEqual(o["pct"], [F.pct_text(a, b) for a, b in pairs])
        self.assertEqual(o["h"], [F.h_text(v) for v in mins])
        self.assertEqual(o["days"], [F.days_text(v, 480) for v in mins])
        self.assertEqual(o["mm"], [F.mm_text(a, b) for a, b in pairs if a is not None])
        nn = [v for v in nums if isinstance(v, (int, float)) and not isinstance(v, bool)]
        self.assertEqual(o["signed"], [F.fmt_signed(F.fmt_num, v, 1) for v in nn])


class GoldenTest(unittest.TestCase):
    """R §3.1 골든 표 · 시제품 `golden_report.json` 의 fmt 절."""

    def test_spec_table(self):
        self.assertEqual([F.fmt_h1(m) for m in (3, 87, 2, 9483)], ["0.1", "1.5", "0.0", "158.1"])
        self.assertEqual(F.fmt_mm(9480, 9600), "0.99")
        self.assertEqual(F.fmt_mm(11520, 10560), "1.09")
        self.assertEqual(F.fmt_mm(4799, 9600), "0.50")
        self.assertEqual(F.fmt_mm(0, 9600), "0.00")
        self.assertEqual(F.fmt_pct(9480, 8880), "107")
        self.assertEqual(F.fmt_pct(1, 200), "1")

    def test_proto_golden(self):
        with open(_p("tests", "fixtures", "wp30", "golden_report.json"), encoding="utf-8") as f:
            g = json.load(f)["fmt"]
        for m, v in g["h1"].items():
            self.assertEqual(F.fmt_h1(int(m)), v, m)
        for k, v in g["mm2"].items():
            a, b = map(int, k.split("/"))
            self.assertEqual(F.fmt_ratio(a, b, 2), v, k)
        for k, v in g["pct0"].items():
            a, b = map(int, k.split("/"))
            self.assertEqual(F.fmt_pct(a, b), v, k)

    def test_text_helpers(self):
        self.assertIsNone(F.fmt_ratio(1, 0, 2))
        self.assertIsNone(F.fmt_mm(5, 0))
        self.assertEqual(F.mm_text(5, 0), "—")
        self.assertEqual(F.fmt_days(720), "1.5")
        self.assertEqual(F.fmt_days(720, 0), "1.5")
        self.assertEqual(F.days_text(None), "—")
        self.assertEqual(F.days_text(1536), "3.2영업일")
        self.assertEqual(F.h_text(9480), "158.0h")
        self.assertEqual(F.pct_text(0, 100), "0%")
        self.assertEqual(F.pct_text(1, 200), "0.5%")
        self.assertEqual(F.pct_text(9480, 8880), "107%")
        self.assertEqual(F.pct_text(1, 0), "—")
        self.assertEqual(F.share_text(0.56), "56%")
        self.assertEqual(F.share_text(None), "—")
        self.assertEqual(F.fmt_x(1.8), "×1.8")
        self.assertEqual(F.fmt_x(None), "—")
        self.assertEqual(F.fmt_signed(F.fmt_h1, 0), "±0")
        self.assertEqual(F.fmt_signed(F.fmt_h1, 90), "+1.5")
        self.assertEqual(F.fmt_signed(F.fmt_h1, -90), "−1.5")
        self.assertEqual(F.fmt_num(-0.004, 2), "0.00")             # 0 으로 반올림되면 부호 없음
        self.assertEqual(F.fmt_num(-1.25, 1), "−1.3")
        self.assertIsNone(F.fmt_num(True, 1))
        self.assertIsNone(F.fmt_num(float("nan"), 1))


class BizTimeTest(unittest.TestCase):
    """RPT-14 영업 분(R §3.2) · 근무일 · ISO 주."""

    @classmethod
    def setUpClass(cls):
        cls.bc = F.BizCal(W.calendar())

    def test_golden(self):
        bc = self.bc
        self.assertEqual(bc.biz_min(W.lmin("2026-09-04", "16:00"), W.lmin("2026-09-07", "10:00")), 180)
        self.assertEqual(bc.biz_min(W.lmin("2026-09-23", "17:00"), W.lmin("2026-09-28", "09:00")), 60)
        self.assertEqual(bc.biz_min(W.lmin("2026-09-22", "12:00"), W.lmin("2026-09-30", "13:00")), 1920)
        self.assertEqual(F.biz_min(W.lmin("2026-09-21", "11:00"), W.lmin("2026-10-02", "10:00"), W.calendar()), 3300)

    def test_edges(self):
        bc = self.bc
        a = W.lmin("2026-09-01", "10:00")
        self.assertEqual(bc.biz_min(a, a), 0)
        self.assertEqual(bc.biz_min(a + 10, a), 0)
        self.assertEqual(bc.biz_min(None, a), 0)
        self.assertEqual(bc.biz_min(W.lmin("2026-09-01", "12:00"), W.lmin("2026-09-01", "13:00")), 0)   # 점심
        self.assertEqual(bc.biz_min(W.lmin("2026-09-05", "09:00"), W.lmin("2026-09-06", "18:00")), 0)   # 주말
        self.assertEqual(bc.biz_min(W.lmin("2026-09-01", "00:00"), W.lmin("2026-09-02", "00:00")), 480)
        # 반차·연차를 빼지 않는다 — 달력만 본다(R §3.2)
        self.assertEqual(bc.biz_min(W.lmin("2026-09-24", "09:00"), W.lmin("2026-09-26", "09:00")), 0)  # 추석
        self.assertEqual(bc.wd_between("2026-09-04", "2026-09-07"), 1)
        self.assertEqual(bc.wd_between(date(2026, 10, 12), date(2026, 10, 15)), 3)
        self.assertEqual(bc.wd_between("2026-09-07", "2026-09-04"), 0)
        self.assertFalse(bc.is_workday("2026-10-09"))
        self.assertTrue(bc.is_workday("2030-01-07"))          # 달력 밖 해 — 요일로만(공휴일 정보 없음)
        self.assertFalse(bc.is_workday("2030-01-05"))

    def test_brute_force_against_reference(self):
        """누적합 구현 = 날짜를 하나씩 훑는 참조식(시제품 biz_min)."""
        bc = self.bc
        rnd = random.Random(14)
        cal = W.calendar()

        def ref(a, b):
            tot = 0
            d = a // 1440
            while d * 1440 < b:
                dd = date.fromordinal(date(2020, 1, 1).toordinal() + d)
                if dd.year in cal.years and not cal.is_holiday(dd):
                    for s, e in ((540, 720), (780, 1080)):
                        lo, hi = max(a, d * 1440 + s), min(b, d * 1440 + e)
                        tot += max(0, hi - lo)
                d += 1
            return tot
        base = W.lmin("2026-08-01", "00:00")
        for _ in range(400):
            a = base + rnd.randint(0, 120 * 1440)
            b = a + rnd.randint(0, 40 * 1440)
            self.assertEqual(bc.biz_min(a, b), ref(a, b), (a, b))

    def test_window_from_cfg(self):
        c = W.cfg()
        self.assertEqual(F.window_from_cfg(c).zones, ((540, 720), (780, 1080)))
        c2 = W.cfg(**{"time.window.std": "08:30-17:30", "time.window.lunch": "11:30-12:30"})
        w = F.window_from_cfg(c2)
        self.assertEqual(w.zones, ((510, 690), (750, 1050)))
        self.assertEqual(w.day_min, 480)

    def test_iso_week(self):
        self.assertEqual(F.iso_week(date(2026, 9, 28)), "2026-W40")
        self.assertEqual(F.iso_week("2026-10-04"), "2026-W40")
        self.assertEqual(F.week_bounds("2026-W40"), (date(2026, 9, 28), date(2026, 10, 4)))
        self.assertEqual(F.iso_week(date(2027, 1, 1)), "2026-W53")
        with self.assertRaises(ValueError):
            F.week_bounds("2026-40")


class HelperTest(unittest.TestCase):
    def test_half_up_and_ratio(self):
        self.assertEqual(F.half_up(Fraction(5, 2)), 3)
        self.assertEqual(F.half_up(Fraction(7, 3), 2), 2.33)
        self.assertEqual(F.half_up(0.125, 2), 0.13)                # 은행가 반올림이 아니다
        self.assertEqual(F.ratio(210, 375), 0.56)
        self.assertIsNone(F.ratio(1, 0))
        self.assertTrue(F.ge(7, 10, 0.7))
        self.assertFalse(F.lt(3, 10, 0.3))
        self.assertEqual(F.ceil_mul(0.3, 4), 2)
        self.assertEqual(F.ceil_mul(0.3, 10), 3)                   # 0.3 × 10 = 3 정확(부동소수 3.0000000000000004 아님)
        self.assertEqual(F.sec_min(90), 2)
        self.assertEqual(F.dec(0.3), Fraction(3, 10))

    def test_median_p75_jaccard(self):
        self.assertEqual(F.median_int([240, 360, 180, 180]), 210)
        self.assertEqual(F.median_int([120, 180, 90, 90]), 105)
        self.assertEqual(F.median_int([600, 60, 1320, 720, 1920]), 720)
        self.assertEqual(F.p75_int([120, 180, 90, 90]), 120)        # 최근순위: ceil(0.75 × 4) = 3번째
        self.assertEqual(F.p75_int([180, 180, 240, 360]), 240)
        self.assertIsNone(F.median_int([]))
        self.assertIsNone(F.p75_int([]))
        self.assertEqual(F.jaccard({"f1", "f2"}, {"f2", "f3"}), Fraction(1, 3))
        self.assertEqual(F.jaccard(set(), set()), 0)

    def test_split_largest(self):
        self.assertEqual(F.split_largest(1, {"O": 1, "I": 1}, ("O", "I")), {"O": 1})
        self.assertEqual(F.split_largest(10, {"O": 0, "I": 0}, ("O", "I")), {"O": 10})
        self.assertEqual(F.split_largest(0, {"O": 3}), {})
        rnd = random.Random(7)
        for _ in range(500):
            total = rnd.randint(0, 600)
            w = {f"k{i}": rnd.randint(0, 50) for i in range(rnd.randint(1, 6))}
            got = F.split_largest(total, w)
            if sum(w.values()) == 0:
                continue
            self.assertEqual(sum(got.values()), total)
            s = sum(w.values())
            for k, v in got.items():
                exact = Fraction(total * w[k], s)
                self.assertTrue(exact - 1 < v < exact + 1, (total, w, got))
        with self.assertRaises(ValueError):
            F.split_largest(-1, {"a": 1})


class DivisionGateTest(unittest.TestCase):
    """G-R11 · L-19 — `round(` 과 `/` 나눗셈은 lm27\\report\\fmt.py 에만(WP-30 소유 모듈 전수)."""

    def test_no_round_or_division(self):
        bad = []
        for rel in OWNED:
            path = _p(*rel.split("/"))
            with open(path, encoding="utf-8") as f:
                tree = ast.parse(f.read(), path)
            for n in ast.walk(tree):
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "round":
                    bad.append((rel, n.lineno, "round("))
                if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Div):
                    bad.append((rel, n.lineno, "/"))
                if isinstance(n, ast.AugAssign) and isinstance(n.op, ast.Div):
                    bad.append((rel, n.lineno, "/="))
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
