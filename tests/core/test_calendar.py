# -*- coding: utf-8 -*-
"""WP-02 달력 시험 — T-13 · W-G10 · TAB A12 · W §2.5 · W §3.13 · CR-10 · CR-15 · L-04.

자료는 합성만 쓴다. 레지스트리 달력 표본의 근거 주소는 example.com 이다.
기대 월별 근무일(36개월)은 `tests\\fixtures\\wp02\\calendar_verified_counts.json`(검증표 사본)에서 읽는다.
"""
import ast
import json
import random
import re
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from lm27.time import calendar as C

ROOT = Path(__file__).resolve().parents[2]
CAL_JSON = ROOT / "config" / "calendar.json"
FIX = ROOT / "tests" / "fixtures" / "wp02"
SRC = ROOT / "lm27" / "time" / "calendar.py"

CFG = {  # 계약 §5.2 기본값
    "time.window.std": "09:00-18:00",
    "time.window.lunch": "12:00-13:00",
    "time.window.dinner": "18:00-18:30",
    "time.window.night": "22:00-06:00",
    "time.window.halfAmOff": "09:00-14:00",
    "time.window.halfPmOff": "14:00-18:00",
}
H = 3600


class RecCfg(dict):
    """읽힌 키를 기록하는 가짜 Cfg(설정 read-check 용)."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.read = set()

    def __getitem__(self, k):
        self.read.add(k)
        return super().__getitem__(k)


def cal():
    return C.Calendar(CAL_JSON)


def slot_at(s: str) -> int:
    dt = datetime.strptime(s, "%Y-%m-%d %H:%M")
    return (C.day0(dt.date()) + dt.hour * H + dt.minute * 60) // C.SLOT


def ev(d0, d1, leaves=None, manual=()):
    return SimpleNamespace(d0=d0, d1=d1, leaves=leaves or {}, manual=list(manual))


def hol(d, name="합성 휴일", kind="임시", url="https://example.com/holiday", confirmed="2026-10-05"):
    h = {"date": d, "name": name, "kind": kind, "source_url": url, "confirmed": confirmed}
    return {k: v for k, v in h.items() if v is not None}


def mk_obj(years=None, **over):
    obj = {
        "version": "test-1",
        "std_day_min": 480,
        "weekdays": [0, 1, 2, 3, 4],
        "note": "합성 달력",
        "years": years if years is not None else [{"year": 2026, "holidays": [hol("2026-10-02")]}],
        "company_off": [],
    }
    obj.update(over)
    return obj


def verified_counts() -> dict:
    return json.loads((FIX / "calendar_verified_counts.json").read_bytes().decode("utf-8"))["counts"]


# ───────────────────────────── 달력 파일 ─────────────────────────────
class CalendarFileTest(unittest.TestCase):
    def test_file_encoding(self):
        raw = CAL_JSON.read_bytes()
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"), "BOM 없음(계약 §9.2)")
        self.assertNotIn(b"\r", raw, "LF 만")
        self.assertTrue(raw.endswith(b"\n"))
        text = raw.decode("utf-8")
        bad = [c for c in text if ord(c) < 32 and c != "\n"]
        self.assertEqual(bad, [], "제어문자 0(L-01)")

    def test_shape_contract_3_21(self):
        obj = json.loads(CAL_JSON.read_bytes().decode("utf-8"))
        self.assertTrue({"version", "std_day_min", "weekdays", "years", "company_off"} <= set(obj))
        self.assertLessEqual(set(obj), {"version", "std_day_min", "weekdays", "note", "years", "company_off"})
        self.assertEqual(obj["std_day_min"], 480)
        self.assertEqual(obj["weekdays"], [0, 1, 2, 3, 4])
        self.assertEqual([y["year"] for y in obj["years"]], [2025, 2026, 2027])
        for y in obj["years"]:
            self.assertEqual(set(y), {"year", "holidays"})
            for h in y["holidays"]:
                self.assertEqual(set(h), {"date", "name", "kind", "source_url", "confirmed"}, h["date"])
                self.assertRegex(h["source_url"], r"^https?://\S+$")
                self.assertRegex(h["confirmed"], r"^\d{4}-\d{2}-\d{2}$")
                date.fromisoformat(h["confirmed"])
                d = date.fromisoformat(h["date"])
                self.assertEqual(d.year, y["year"])
                if h["kind"] == "대체":
                    self.assertLess(d.weekday(), 5, f"대체공휴일은 평일 {d}")

    def test_t13_gate(self):
        c = cal()
        self.assertEqual(c.month_workdays(2026, 9), 20)
        self.assertEqual(c.month_workdays(2026, 10), 20)
        self.assertEqual(c.month_weekdays(2026, 9), 22)
        self.assertEqual(c.month_weekdays(2026, 10), 22)

    def test_36_months_match_verified_table(self):
        c = cal()
        counts = verified_counts()
        self.assertEqual(len(counts), 36)
        got = {f"{y}-{m:02d}": c.month_workdays(y, m) for y in (2025, 2026, 2027) for m in range(1, 13)}
        self.assertEqual(got, counts)

    def test_tab_a12_2026_monthly(self):
        c = cal()
        self.assertEqual([c.month_workdays(2026, m) for m in range(1, 13)],
                         [21, 17, 21, 22, 18, 21, 22, 20, 20, 20, 21, 22])

    def test_year_totals(self):
        c = cal()
        for y, n in ((2025, 244), (2026, 245), (2027, 246)):
            self.assertEqual(sum(c.month_workdays(y, m) for m in range(1, 13)), n)
            self.assertEqual(c.wd_between(date(y, 1, 1) - timedelta(days=1), date(y, 12, 31)), n)

    def test_known_dates(self):
        c = cal()
        self.assertTrue(c.is_holiday(date(2026, 9, 24)))
        self.assertTrue(c.is_holiday(date(2026, 9, 25)))
        self.assertFalse(c.is_holiday(date(2026, 9, 28)), "9/28 대체공휴일 아님(이전 판 오류)")
        self.assertTrue(c.is_holiday(date(2026, 10, 5)), "개천절 대체")
        self.assertTrue(c.is_holiday(date(2026, 10, 9)))
        self.assertFalse(c.is_holiday(date(2026, 10, 2)))
        self.assertTrue(c.is_holiday(date(2026, 5, 1)), "2026 노동절 공휴일")
        self.assertFalse(c.is_holiday(date(2025, 5, 1)), "2025 근로자의날은 관공서 공휴일 아님(검증표)")
        self.assertTrue(c.is_holiday(date(2026, 10, 3)), "토요일")
        self.assertEqual(c.std_day_min, 480)
        self.assertEqual(c.weekdays, frozenset({0, 1, 2, 3, 4}))
        self.assertEqual(c.years, frozenset({2025, 2026, 2027}))
        self.assertTrue(c.version)
        self.assertEqual(c.source, "file")

    def test_deeply_nested_file_is_value_error(self):
        """깊은 중첩 달력 파일 — RecursionError 로 프로그램이 죽지 않고 형식 오류(ValueError, '달력 미확인'과 같은 갈래)."""
        with tempfile.TemporaryDirectory(prefix="lm27t_wp02_") as td:
            p = Path(td) / "calendar.json"
            p.write_bytes(b'{"years": ' + b"[" * 100000 + b"]" * 100000 + b"}")
            with self.assertRaises(ValueError) as cm:
                C.Calendar(p)
            self.assertNotIsInstance(cm.exception, RecursionError)

    def test_date_like_inputs(self):
        c = cal()
        self.assertTrue(c.is_holiday(datetime(2026, 9, 24, 10, 0)))
        self.assertTrue(c.is_holiday("2026-09-24"))
        self.assertEqual(c.wd_between("2026-09-30", "2026-10-02"), 2)
        with self.assertRaises(ValueError):
            c.is_holiday("2026/09/24")
        with self.assertRaises(ValueError):
            c.month_workdays(2026, 13)


class UnknownYearTest(unittest.TestCase):
    def test_is_holiday_unknown_year(self):
        c = cal()
        with self.assertRaises(C.UnknownYearError) as cm:
            c.is_holiday(date(2024, 12, 31))
        self.assertIsInstance(cm.exception, ValueError)
        self.assertIn("달력 미확인 연도", str(cm.exception))
        self.assertEqual(cm.exception.years, (2024,))
        self.assertEqual(cm.exception.reason, "달력 미확인 연도")

    def test_month_and_range_unknown_year(self):
        c = cal()
        for fn in (lambda: c.month_workdays(2028, 1), lambda: c.month_weekdays(2024, 12),
                   lambda: c.wd_between(date(2024, 12, 30), date(2025, 1, 2)),
                   lambda: c.wd_between(date(2027, 12, 1), date(2028, 1, 3))):
            with self.assertRaises(ValueError):
                fn()
        self.assertEqual(c.wd_between(date(2024, 12, 31), date(2025, 1, 2)), 1, "(d1, d2] 는 2025 만 걸침")
        self.assertEqual(c.missing_years(date(2024, 6, 1), date(2028, 2, 1)), [2024, 2028])
        self.assertEqual(c.missing_years("2026-01-01", "2026-12-31"), [])

    def test_non_contiguous_years(self):
        c = C.Calendar.from_obj(mk_obj(years=[{"year": 2025, "holidays": []}, {"year": 2027, "holidays": []}]))
        self.assertEqual(c.month_workdays(2025, 1), 23)
        with self.assertRaises(C.UnknownYearError):
            c.wd_between(date(2025, 12, 1), date(2027, 1, 5))
        with self.assertRaises(C.UnknownYearError):
            c.is_holiday(date(2026, 3, 3))


class WdBetweenTest(unittest.TestCase):
    def test_matches_brute_force(self):
        c = cal()
        lo, hi = date(2024, 12, 31), date(2027, 12, 31)
        span = (hi - lo).days
        rnd = random.Random(20261005)
        for _ in range(1500):
            a = lo + timedelta(days=rnd.randrange(span + 1))
            b = lo + timedelta(days=rnd.randrange(span + 1))
            want = 0
            d = a + timedelta(days=1)
            while d <= b:
                want += 0 if c.is_holiday(d) else 1
                d += timedelta(days=1)
            self.assertEqual(c.wd_between(a, b), want, (a, b))

    def test_semantics(self):
        c = cal()
        self.assertEqual(c.wd_between(date(2026, 10, 6), date(2026, 10, 6)), 0)
        self.assertEqual(c.wd_between(date(2026, 10, 7), date(2026, 10, 6)), 0)
        self.assertEqual(c.wd_between(date(2026, 10, 5), date(2026, 10, 6)), 1, "d1 제외·d2 포함")
        self.assertEqual(c.wd_between(date(2026, 10, 6), date(2026, 10, 9)), 2, "10/7·10/8, 10/9 한글날")

    def test_constant_time(self):
        c = cal()
        a, b = date(2025, 1, 1), date(2027, 12, 30)
        from tests.fixtures.tree import best_of                 # 부하에 민감 — 여러 번 재서 최솟값(W1 통합 창 R8)

        def run():
            for _ in range(100_000):
                c.wd_between(a, b)
        self.assertLess(best_of(run, under=3.0), 3.0, "누적합 O(1) — 날짜 순회면 수백 초")


class ArgsTest(unittest.TestCase):
    def test_company_off_arg_union(self):
        c = C.Calendar(CAL_JSON, company_off=[date(2026, 9, 30), "2026-10-02"])
        self.assertEqual(c.month_workdays(2026, 9), 19)
        self.assertEqual(c.month_workdays(2026, 10), 19)
        self.assertTrue(c.is_holiday(date(2026, 9, 30)))
        obj = mk_obj(company_off=["2026-10-06"])
        c2 = C.Calendar.from_obj(obj, company_off=[date(2026, 10, 7)])
        self.assertEqual(c2.company_off, frozenset({date(2026, 10, 6), date(2026, 10, 7)}))
        self.assertEqual(c2.month_workdays(2026, 10), 22 - 3)

    def test_weekdays_override(self):
        c = C.Calendar(CAL_JSON, weekdays=(0, 1, 2, 3, 4, 5))
        self.assertEqual(c.month_workdays(2026, 9), 23, "토 9/5·12·19 추가, 9/26 은 추석")
        self.assertEqual(c.month_weekdays(2026, 9), 26)
        self.assertFalse(c.is_holiday(date(2026, 9, 5)))
        with self.assertRaises(ValueError):
            C.Calendar(CAL_JSON, weekdays=(0, 7))

    def test_bom_file_accepted(self):
        with tempfile.TemporaryDirectory(prefix="lm27t_wp02_") as td:
            p = Path(td) / "cal.json"
            p.write_bytes(b"\xef\xbb\xbf" + json.dumps(mk_obj(), ensure_ascii=False).encode("utf-8"))
            c = C.Calendar(p)
            self.assertEqual(c.month_workdays(2026, 10), 21)
            self.assertEqual(c.version, "test-1")


class ValidationTest(unittest.TestCase):
    def bad(self, obj, msg=None):
        with self.assertRaises(ValueError, msg=msg):
            C.Calendar.from_obj(obj)

    def test_holiday_requires_source_and_confirmed(self):
        self.bad(mk_obj(years=[{"year": 2026, "holidays": [hol("2026-10-02", url=None)]}]))
        self.bad(mk_obj(years=[{"year": 2026, "holidays": [hol("2026-10-02", url="")]}]))
        self.bad(mk_obj(years=[{"year": 2026, "holidays": [hol("2026-10-02", url="example.com/x")]}]))
        self.bad(mk_obj(years=[{"year": 2026, "holidays": [hol("2026-10-02", confirmed=None)]}]))
        self.bad(mk_obj(years=[{"year": 2026, "holidays": [hol("2026-10-02", confirmed="어제")]}]))
        self.bad(mk_obj(years=[{"year": 2026, "holidays": [hol("2026-10-02", name="")]}]))
        self.bad(mk_obj(years=[{"year": 2026, "holidays": [hol("2026-10-02", kind=None)]}]))

    def test_structure_errors(self):
        self.bad(mk_obj(years=[{"year": 2026, "holidays": [hol("2027-01-01")]}]), "다른 해 날짜")
        self.bad(mk_obj(years=[{"year": 2026, "holidays": [hol("2026-10-02"), hol("2026-10-02")]}]), "중복 날짜")
        self.bad(mk_obj(years=[{"year": 2026, "holidays": []}, {"year": 2026, "holidays": []}]), "중복 해")
        self.bad(mk_obj(years=[]))
        self.bad(mk_obj(years=[{"year": "2026", "holidays": []}]))
        self.bad(mk_obj(years=[{"year": 2026, "holidays": [hol("2026-02-30")]}]), "없는 날짜")
        self.bad(mk_obj(weekdays=[0, 7]))
        self.bad(mk_obj(weekdays=[]))
        self.bad(mk_obj(weekdays=[1, 1]))
        self.bad(mk_obj(std_day_min=True))
        self.bad(mk_obj(std_day_min=0))
        self.bad(mk_obj(std_day_min=480.0))
        self.bad(mk_obj(version=""))
        self.bad(mk_obj(company_off="2026-10-02"))
        self.bad(mk_obj(company_off=["2026/10/02"]))
        self.bad([1, 2])
        obj = mk_obj()
        del obj["version"]
        self.bad(obj)

    def test_unknown_keys_tolerated(self):
        h = hol("2026-10-02")
        h["note"] = "참고"
        c = C.Calendar.from_obj(mk_obj(years=[{"year": 2026, "holidays": [h], "memo": 1}], extra=True))
        self.assertTrue(c.is_holiday(date(2026, 10, 2)))

    def test_file_level_errors(self):
        good = json.dumps(mk_obj(), ensure_ascii=False)
        cases = {
            "dup": good.replace('"version": "test-1",', '"version": "test-1", "version": "test-2",'),
            "nan": good.replace('"std_day_min": 480', '"std_day_min": NaN'),
            "syntax": good[:-1],
        }
        with tempfile.TemporaryDirectory(prefix="lm27t_wp02_") as td:
            for name, text in cases.items():
                p = Path(td) / f"{name}.json"
                p.write_bytes(text.encode("utf-8"))
                with self.assertRaises(ValueError, msg=name):
                    C.Calendar(p)
            p = Path(td) / "cp949.json"
            p.write_bytes(good.encode("cp949"))
            with self.assertRaises(ValueError):
                C.Calendar(p)


# ───────────────────────────── 원천 우선순위(CR-15) ─────────────────────────────
class FakePaths:
    def __init__(self, p):
        self._p = p
        self.calls = 0

    def calendar_json(self):
        self.calls += 1
        return self._p


class LoadCalendarTest(unittest.TestCase):
    def test_builtin_when_no_registry(self):
        for reg in (None, {}, {"calendar": None}, {"calendar": {}}, {"version": 3}):
            c = C.load_calendar(FakePaths(CAL_JSON), reg)
            self.assertEqual(c.source, "file")
            self.assertEqual(c.month_workdays(2026, 10), 20)
            self.assertEqual(c.warnings, [])

    def test_registry_calendar_wins(self):
        paths = FakePaths(CAL_JSON)
        reg = {"schema": "lm27.registry/1", "calendar": mk_obj(version="kr-team-1")}
        c = C.load_calendar(paths, reg)
        self.assertEqual(c.source, "registry")
        self.assertEqual(c.version, "kr-team-1")
        self.assertEqual(c.month_workdays(2026, 10), 21, "레지스트리 달력: 10/2 휴일 하나뿐인 합성 달력")
        self.assertEqual(paths.calls, 0, "레지스트리 달력이 있으면 내장 파일을 읽지 않는다")
        c2 = C.load_calendar(paths, SimpleNamespace(calendar=mk_obj(version="kr-team-2")))
        self.assertEqual(c2.version, "kr-team-2")

    def test_registry_whole_object_priority(self):
        c = C.load_calendar(FakePaths(CAL_JSON), {"calendar": mk_obj()})
        with self.assertRaises(C.UnknownYearError):
            c.month_workdays(2025, 5)

    def test_invalid_registry_calendar_falls_back_with_warning(self):
        bad = mk_obj(years=[{"year": 2026, "holidays": [hol("2026-10-02", url=None)]}])
        c = C.load_calendar(FakePaths(CAL_JSON), {"calendar": bad})
        self.assertEqual(c.source, "file")
        self.assertEqual(c.month_workdays(2026, 10), 20)
        self.assertEqual(len(c.warnings), 1)
        self.assertIn("팀 레지스트리 달력 형식 오류", c.warnings[0])

    def test_args_pass_through(self):
        c = C.load_calendar(FakePaths(CAL_JSON), None, company_off=[date(2026, 10, 2)], weekdays=(0, 1, 2, 3, 4))
        self.assertEqual(c.month_workdays(2026, 10), 19)

    def test_real_paths_integration(self):
        from lm27.paths import Paths          # WP-00 경로 로더(순수 — 폴더·파일을 만들지 않는다)

        p = Paths(ROOT)
        self.assertEqual(Path(p.calendar_json()).resolve(), CAL_JSON.resolve())
        c = C.load_calendar(p, None)
        self.assertEqual((c.source, c.month_workdays(2026, 9)), ("file", 20))


# ───────────────────────────── 로컬 초 ─────────────────────────────
class LsecTest(unittest.TestCase):
    def test_epoch(self):
        self.assertEqual(C.EPOCH, date(2020, 1, 1))
        self.assertEqual(C.SLOT, 300)
        self.assertEqual(C.day0(date(2020, 1, 1)), 0)
        self.assertEqual(C.day0(date(2020, 1, 2)), 86400)
        self.assertEqual(C.d_of(-1), date(2019, 12, 31))
        for d in (date(2025, 1, 1), date(2026, 9, 30), date(2027, 12, 31)):
            self.assertEqual(C.d_of(C.day0(d)), d)
            self.assertEqual(C.d_of(C.day0(d) + 86399), d)
            self.assertGreater(C.day0(d), 0, "2020 이후 자료는 음수 없음(X-174)")


# ───────────────────────────── build_days ─────────────────────────────
class BuildDaysTest(unittest.TestCase):
    def setUp(self):
        self.c = cal()
        self.leaves = {date(2026, 9, 21): "am", date(2026, 9, 22): "full", "2026-09-23": "pm",
                       date(2026, 9, 24): "full"}
        self.manual = [SimpleNamespace(kind="absence", d=date(2026, 9, 23)),
                       SimpleNamespace(kind="work", d=date(2026, 9, 21)),
                       {"kind": "absence", "d": "2026-09-25"}]
        self.days = C.build_days(ev(date(2026, 9, 21), date(2026, 9, 25), self.leaves, self.manual), CFG, self.c)

    def test_range_and_flags(self):
        self.assertEqual(sorted(self.days), [date(2026, 9, 20) + timedelta(days=i) for i in range(7)])
        self.assertFalse(self.days[date(2026, 9, 20)]["in_range"])
        self.assertFalse(self.days[date(2026, 9, 26)]["in_range"])
        self.assertTrue(all(self.days[date(2026, 9, 21) + timedelta(days=i)]["in_range"] for i in range(5)))
        self.assertTrue(self.days[date(2026, 9, 20)]["hol"])
        self.assertTrue(self.days[date(2026, 9, 24)]["hol"])
        self.assertFalse(self.days[date(2026, 9, 23)]["hol"])

    def test_windows_and_leaves(self):
        z = C.day0(date(2026, 9, 21))
        d = self.days[date(2026, 9, 21)]
        self.assertEqual(d["S"], [(z + 14 * H, z + 18 * H)], "오전 반차 = 표준창 − 09~14")
        self.assertEqual((d["leave"], d["lv"]), (0.5, "am"))
        self.assertEqual(d["lunch"], [(z + 12 * H, z + 13 * H)])
        self.assertEqual(d["dinner"], [(z + 18 * H, z + 18 * H + 1800)])
        self.assertFalse(d["confirmed_absence"])
        z = C.day0(date(2026, 9, 22))
        d = self.days[date(2026, 9, 22)]
        self.assertEqual((d["S"], d["leave"], d["lv"]), ([], 1.0, "full"))
        self.assertEqual(d["lunch"], [(z + 12 * H, z + 13 * H)])
        z = C.day0(date(2026, 9, 23))
        d = self.days[date(2026, 9, 23)]
        self.assertEqual(d["S"], [(z + 9 * H, z + 14 * H)], "오후 반차 = 표준창 − 14~18(문자열 키 허용)")
        self.assertEqual(d["leave"], 0.5)
        self.assertTrue(d["confirmed_absence"])
        d = self.days[date(2026, 9, 24)]
        self.assertEqual((d["S"], d["lunch"], d["dinner"], d["leave"], d["lv"]), ([], [], [], 0.0, "full"),
                         "휴일의 연차는 무시(부재 0), 점심·저녁 없음")
        self.assertTrue(self.days[date(2026, 9, 25)]["confirmed_absence"], "dict 수동 기록도 읽는다")
        self.assertEqual(self.days[date(2026, 9, 26)]["S"], [])

    def test_plain_workday(self):
        days = C.build_days(ev(date(2026, 10, 6), date(2026, 10, 6)), CFG, self.c)
        z = C.day0(date(2026, 10, 6))
        d = days[date(2026, 10, 6)]
        self.assertEqual(d, {"hol": False, "S": [(z + 9 * H, z + 18 * H)], "lunch": [(z + 12 * H, z + 13 * H)],
                             "dinner": [(z + 18 * H, z + 18 * H + 1800)], "leave": 0.0, "lv": None,
                             "confirmed_absence": False, "in_range": True})
        self.assertTrue(days[date(2026, 10, 5)]["hol"], "앞 여유 하루 = 개천절 대체")

    def test_cfg_keys_read(self):
        rc = RecCfg(CFG)
        C.build_days(ev(date(2026, 10, 6), date(2026, 10, 7)), rc, self.c)
        self.assertEqual(rc.read, {"time.window.std", "time.window.lunch", "time.window.dinner",
                                   "time.window.halfAmOff", "time.window.halfPmOff"})

    def test_errors(self):
        with self.assertRaises(ValueError):
            C.build_days(ev(date(2026, 10, 7), date(2026, 10, 6)), CFG, self.c)
        with self.assertRaises(ValueError):
            C.build_days(ev(date(2026, 10, 6), date(2026, 10, 7), {date(2026, 10, 6): "half"}), CFG, self.c)
        with self.assertRaises(C.UnknownYearError) as cm:
            C.build_days(ev(date(2027, 12, 30), date(2028, 1, 2)), CFG, self.c)
        self.assertEqual(cm.exception.years, (2028,))
        bad = dict(CFG, **{"time.window.std": "9-18"})
        with self.assertRaises(ValueError):
            C.build_days(ev(date(2026, 10, 6), date(2026, 10, 6)), bad, self.c)
        bad = dict(CFG, **{"time.window.std": "09:00-24:30"})
        with self.assertRaises(ValueError):
            C.build_days(ev(date(2026, 10, 6), date(2026, 10, 6)), bad, self.c)

    def test_padding_day_in_unknown_year_is_skipped(self):
        days = C.build_days(ev(date(2025, 1, 1), date(2025, 1, 3)), CFG, self.c)
        self.assertEqual(min(days), date(2025, 1, 1))
        days = C.build_days(ev(date(2027, 12, 30), date(2027, 12, 31)), CFG, self.c)
        self.assertEqual(max(days), date(2027, 12, 31))
        self.assertEqual(C.slot_tag(slot_at("2028-01-01 10:00"), days, CFG), "holiday", "정보 없는 날 = 휴일")


# ───────────────────────────── slot_tag ─────────────────────────────
class SlotTagTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        leaves = {date(2026, 9, 29): "full", date(2026, 10, 1): "am", date(2026, 10, 2): "pm"}
        cls.days = C.build_days(ev(date(2026, 9, 28), date(2026, 10, 5), leaves), CFG, cal())

    def tag(self, s, days=None, cfg=CFG):
        return C.slot_tag(slot_at(s), days or self.days, cfg)

    def test_weekday_boundaries(self):
        want = {"2026-09-28 08:55": "extended", "2026-09-28 09:00": "regular", "2026-09-28 11:55": "regular",
                "2026-09-28 12:00": "extended", "2026-09-28 12:55": "extended", "2026-09-28 13:00": "regular",
                "2026-09-28 17:55": "regular", "2026-09-28 18:00": "extended", "2026-09-28 21:55": "extended",
                "2026-09-28 22:00": "night", "2026-09-28 23:55": "night", "2026-09-29 00:00": "night",
                "2026-09-29 05:55": "night", "2026-09-29 06:00": "extended"}
        self.assertEqual({k: self.tag(k) for k in want}, want)

    def test_leave_days(self):
        self.assertEqual(self.tag("2026-09-29 10:00"), "extended", "연차 중 근무 = 연장")
        self.assertEqual(self.tag("2026-10-01 10:00"), "extended", "오전 반차 창")
        self.assertEqual(self.tag("2026-10-01 13:55"), "extended")
        self.assertEqual(self.tag("2026-10-01 14:00"), "regular")
        self.assertEqual(self.tag("2026-10-02 10:00"), "regular")
        self.assertEqual(self.tag("2026-10-02 14:00"), "extended", "오후 반차 창")

    def test_holiday_beats_night(self):
        self.assertEqual(self.tag("2026-10-03 10:00"), "holiday")
        self.assertEqual(self.tag("2026-10-03 23:00"), "holiday", "휴일 > 야간")
        self.assertEqual(self.tag("2026-10-05 10:00"), "holiday", "대체공휴일")

    def test_midnight_split_by_slot_start(self):
        self.assertEqual(self.tag("2026-09-30 23:00"), "night", "W46 9월 야간")
        self.assertEqual(self.tag("2026-10-01 00:30"), "night", "W46 10월 야간")
        self.assertEqual(self.tag("2026-10-02 23:00"), "night", "W53 금 야간")
        self.assertEqual(self.tag("2026-10-03 00:00"), "holiday", "W53 토 휴일")

    def test_codes_and_cfg_keys(self):
        rc = RecCfg(CFG)
        seen = set()
        s0, s1 = slot_at("2026-09-28 00:00"), slot_at("2026-10-05 23:55")
        for s in range(s0, s1 + 1):
            seen.add(C.slot_tag(s, self.days, rc))
        self.assertEqual(seen, set(C.TAGS))
        self.assertEqual(C.TAGS, ("regular", "extended", "night", "holiday"))
        self.assertEqual(rc.read, {"time.window.night"})

    def test_regular_requires_whole_slot(self):
        cfg = dict(CFG, **{"time.window.std": "09:00-17:58"})
        days = C.build_days(ev(date(2026, 10, 6), date(2026, 10, 6)), cfg, cal())
        self.assertEqual(self.tag("2026-10-06 17:50", days, cfg), "regular")
        self.assertEqual(self.tag("2026-10-06 17:55", days, cfg), "extended", "슬롯 ⊆ S_eff − 점심")

    def test_non_wrapping_night(self):
        cfg = dict(CFG, **{"time.window.night": "00:00-05:00"})
        self.assertEqual(self.tag("2026-09-28 23:00", cfg=cfg), "extended")
        self.assertEqual(self.tag("2026-09-29 03:00", cfg=cfg), "night")
        cfg = dict(CFG, **{"time.window.night": "00:00-00:00"})
        self.assertEqual(self.tag("2026-09-29 03:00", cfg=cfg), "extended", "빈 야간 창")

    def test_wrapping_std_window(self):
        cfg = dict(CFG, **{"time.window.std": "22:00-07:00", "time.window.lunch": "02:00-03:00",
                           "time.window.night": "05:00-05:00", "time.window.dinner": "07:00-07:30"})
        days = C.build_days(ev(date(2026, 10, 12), date(2026, 10, 16)), cfg, cal())
        want = {"2026-10-12 21:55": "extended", "2026-10-12 23:00": "regular", "2026-10-13 01:00": "regular",
                "2026-10-13 02:30": "extended", "2026-10-13 06:55": "regular", "2026-10-13 07:00": "extended",
                "2026-10-16 23:00": "regular", "2026-10-17 01:00": "holiday"}
        self.assertEqual({k: self.tag(k, days, cfg) for k in want}, want)


# ───────────────────────────── 소스 규칙 ─────────────────────────────
class SourceRulesTest(unittest.TestCase):
    def setUp(self):
        self.text = SRC.read_bytes().decode("utf-8")

    def test_l04_no_tz_database(self):
        for needle in ("zoneinfo" + ".ZoneInfo", "import " + "zoneinfo", "from " + "zoneinfo"):
            self.assertNotIn(needle, self.text)

    def test_no_builtin_holiday_table(self):
        self.assertIsNone(re.search(r"20(2[1-9]|[3-9]\d)-\d{2}-\d{2}", self.text), "공휴일 날짜를 코드에 두지 않는다(D-17)")
        self.assertIsNone(re.search(r"date\(20(2[1-9]|[3-9]\d)\s*,", self.text))

    def test_stdlib_only(self):
        tree = ast.parse(self.text)
        mods = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                mods |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                mods.add((node.module or "").split(".")[0])
        self.assertTrue(mods <= set(sys.stdlib_module_names) | {"__future__"}, mods)

    def test_no_file_writes(self):
        self.assertIsNone(re.search(r"open\([^)]*['\"][wa]", self.text))
        self.assertNotIn("write_bytes", self.text)
        self.assertNotIn("write_text", self.text)


if __name__ == "__main__":
    unittest.main()
