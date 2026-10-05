# -*- coding: utf-8 -*-
r"""달력·날짜 정보·꼬리표 — 시간 코어(W 부록 A `calendar.py`, 계약 §2.9 · §3.21 · §6.4).

- 달력 원천은 `calendar.json` 하나다. 팀 레지스트리 `calendar`(같은 모양)가 있으면 그것이 우선한다
  (`load_calendar` — CR-15). 코드 안에 공휴일 표를 두지 않는다(D-17).
- 달력 `years` 에 없는 해를 물으면 `UnknownYearError`(ValueError) — 분석 거부 사유 '달력 미확인 연도'
  (fail-closed, W §2.5 · T-13).
- `std_day_min`·`weekdays` 는 달력 값만 쓴다(설정 키 없음 — X-186). 근무창은 개인 설정 `time.window.*`
  (X-187): `build_days` 가 `std`·`lunch`·`dinner`·`halfAmOff`·`halfPmOff`, `slot_tag` 가 `night` 를 읽는다.
- 로컬 초(lsec)·로컬 분의 기준점 = 2020-01-01 00:00 로컬(계약 §3.14 · X-174). 슬롯 300초(계약 §5.3).
- 꼬리표는 계약 코드 `regular` `extended` `night` `holiday` — 배타, 휴일 > 야간 > 연장 > 정규
  (계약 §6.4 · W §3.13 · CR-10).

표준 라이브러리만 쓴다. 이 모듈은 파일을 쓰지 않는다.
"""
from __future__ import annotations

import functools
import json
import re
from collections.abc import Iterable, Mapping
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import TypedDict

__all__ = [
    "DAY",
    "EPOCH",
    "SLOT",
    "TAGS",
    "Calendar",
    "DayInfo",
    "UnknownYearError",
    "build_days",
    "d_of",
    "day0",
    "load_calendar",
    "slot_tag",
]

EPOCH = date(2020, 1, 1)            # 로컬 초 0 = 이 날 00:00 로컬
SLOT = 300                          # 5분 슬롯(설정 아님)
DAY = 86400
TAGS = ("regular", "extended", "night", "holiday")
REASON_UNKNOWN_YEAR = "달력 미확인 연도"
LEAVE_CODES = ("full", "am", "pm")

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_WIN_RE = re.compile(r"^(\d{1,2}):(\d{2})-(\d{1,2}):(\d{2})$")


class UnknownYearError(ValueError):
    """달력에 없는 해 — 분석 거부(사유 '달력 미확인 연도')."""

    def __init__(self, years: Iterable[int]):
        self.years = tuple(sorted(set(years)))
        self.reason = REASON_UNKNOWN_YEAR
        super().__init__(f"{REASON_UNKNOWN_YEAR} {', '.join(str(y) for y in self.years)} — "
                         "calendar.json(또는 팀 레지스트리 달력)에 그 해를 넣기 전에는 분석하지 않는다")


class DayInfo(TypedDict):
    """`build_days` 의 날짜 하나(W §2.5). 구간은 로컬 초 `[a, b)` 목록."""

    hol: bool                          # 주말·공휴일·회사 휴무(달력)
    S: list[tuple[int, int]]           # S_eff — 표준창에서 연차·반차 창을 뺀 것(휴일이면 빈 목록)
    lunch: list[tuple[int, int]]       # 휴일이면 빈 목록
    dinner: list[tuple[int, int]]      # 휴일이면 빈 목록
    leave: float                       # 1.0 연차 · 0.5 반차 · 0.0
    lv: str | None                     # 근태 원값 full|am|pm|None
    confirmed_absence: bool            # 사용자 확인 부재(수동 absence)
    in_range: bool                     # 분석 기간 [d0, d1] 안


# ───────────────────────────── 로컬 초 ─────────────────────────────
def day0(d: date) -> int:
    """그 날 00:00 의 로컬 초."""
    return (_as_date(d) - EPOCH).days * DAY


def d_of(t: int) -> date:
    """로컬 초 → 그 시각의 달력 날짜(슬롯은 시작 시각의 날짜에 속한다)."""
    return EPOCH + timedelta(days=int(t) // DAY)


# ───────────────────────────── 달력 ─────────────────────────────
class Calendar:
    """`Calendar(path, company_off=(), weekdays=None)` — weekdays None = 달력 파일 값.

    회사 휴무는 파일의 `company_off` 와 인자 `company_off` 의 합집합이다.
    """

    version: str
    std_day_min: int
    weekdays: frozenset[int]
    years: frozenset[int]
    holidays: dict[date, str]
    company_off: frozenset[date]
    note: str
    source: str
    warnings: list[str]

    def __init__(self, path: Path | str, company_off: Iterable[date | str] = (),
                 weekdays: Iterable[int] | None = None):
        obj = _strict_json(Path(path).read_bytes())
        self._setup(obj, company_off, weekdays, "file")

    @classmethod
    def from_obj(cls, obj: Mapping, company_off: Iterable[date | str] = (),
                 weekdays: Iterable[int] | None = None, *, source: str = "registry") -> Calendar:
        """이미 읽은 달력 객체(팀 레지스트리 `calendar` 등, 계약 §3.21 모양)로 만든다(CR-15)."""
        cal = cls.__new__(cls)
        cal._setup(obj, company_off, weekdays, source)
        return cal

    def _setup(self, obj, company_off, weekdays, source: str) -> None:
        v = _validate(obj)
        self.version = v["version"]
        self.std_day_min = v["std_day_min"]
        self.note = v["note"]
        self.years = frozenset(v["years"])
        self.holidays = v["holidays"]
        self.company_off = frozenset(v["company_off"]) | frozenset(
            _as_date(x, "company_off") for x in (company_off or ()))
        self.weekdays = v["weekdays"] if weekdays is None else _weekdays(list(weekdays), "weekdays 인자")
        self.source = source
        self.warnings = []
        self._lo = date(min(self.years), 1, 1)
        hi = date(max(self.years), 12, 31)
        cum = [0]
        d = self._lo
        while d <= hi:                                   # 누적합 — wd_between O(1)
            cum.append(cum[-1] + (0 if self._off(d) else 1))
            d += timedelta(days=1)
        self._cum = cum

    def __repr__(self) -> str:
        return (f"Calendar(version={self.version!r}, years={sorted(self.years)}, source={self.source!r}, "
                f"weekdays={sorted(self.weekdays)})")

    def _off(self, d: date) -> bool:
        return d.weekday() not in self.weekdays or d in self.holidays or d in self.company_off

    def _check_years(self, y0: int, y1: int) -> None:
        miss = [y for y in range(y0, y1 + 1) if y not in self.years]
        if miss:
            raise UnknownYearError(miss)

    def missing_years(self, d0: date | str, d1: date | str) -> list[int]:
        """[d0, d1] 이 걸친 해 중 달력에 없는 해(분석 시작 전 점검용)."""
        a, b = _as_date(d0, "d0"), _as_date(d1, "d1")
        if b < a:
            a, b = b, a
        return [y for y in range(a.year, b.year + 1) if y not in self.years]

    def is_holiday(self, d: date | str) -> bool:
        """주말(달력 weekdays 밖)·공휴일·회사 휴무. 달력에 없는 해 → UnknownYearError."""
        d = _as_date(d)
        self._check_years(d.year, d.year)
        return self._off(d)

    def wd_between(self, d1: date | str, d2: date | str) -> int:
        """(d1, d2] 안의 근무일 수(누적합 O(1)). d2 ≤ d1 이면 0."""
        a, b = _as_date(d1, "d1"), _as_date(d2, "d2")
        if b <= a:
            return 0
        self._check_years((a + timedelta(days=1)).year, b.year)
        return self._cum[(b - self._lo).days + 1] - self._cum[(a - self._lo).days + 1]

    def month_workdays(self, y: int, m: int) -> int:
        """그 달 근무일 = 평일 − 공휴일 − 회사 휴무(W §6.1 `W(m)`)."""
        first, last = _month_bounds(y, m)
        return self.wd_between(first - timedelta(days=1), last)

    def month_weekdays(self, y: int, m: int) -> int:
        """그 달 달력 평일 수(공휴일을 빼지 않음 — `mm.denominator='weekdays'` 개인 표시 전용, X-209)."""
        first, last = _month_bounds(y, m)
        self._check_years(y, y)
        w0 = first.weekday()
        return sum(1 for i in range(last.day) if (w0 + i) % 7 in self.weekdays)


def load_calendar(paths, registry=None, *, company_off: Iterable[date | str] = (),
                  weekdays: Iterable[int] | None = None) -> Calendar:
    """달력 원천 우선순위(계약 §3.21 · CR-15): 팀 레지스트리 `calendar` > `config\\calendar.json`.

    `registry` 는 팀 레지스트리 객체(dict) 또는 `.calendar` 속성을 가진 객체, 없으면 None.
    이 함수는 레지스트리 파일을 읽지 않는다(L-22 — 읽은 객체를 받는다).
    레지스트리 달력이 형식 검증에 실패하면 내장 달력으로 계산하고 `warnings` 에 남긴다
    (내장 달력도 확인된 값이므로 안전하다. 달력 판이 달라져 팀 화면에 `calendar_mismatch` 로 드러난다).
    """
    obj = _registry_calendar(registry)
    if obj is not None:
        try:
            return Calendar.from_obj(obj, company_off, weekdays, source="registry")
        except ValueError as e:
            cal = Calendar(paths.calendar_json(), company_off, weekdays)
            cal.warnings.append(f"팀 레지스트리 달력 형식 오류 — 내장 달력 {cal.version} 사용: {e}")
            return cal
    return Calendar(paths.calendar_json(), company_off, weekdays)


def _registry_calendar(registry):
    if registry is None:
        return None
    obj = registry.get("calendar") if isinstance(registry, Mapping) else getattr(registry, "calendar", None)
    return obj if obj else None


# ───────────────────────────── 날짜 정보 · 꼬리표 ─────────────────────────────
def build_days(ev, cfg, cal: Calendar) -> dict[date, DayInfo]:
    """날짜 d ∈ [d0 − 1, d1 + 1] 마다 `DayInfo`(W §2.5). `ev` 는 W 부록 A `Evidence` 를 덕 타이핑으로 읽는다:
    `d0` `d1`(date) · `leaves`({date: full|am|pm}) · `manual`(`kind`·`d` — kind 'absence' = 확인된 부재).

    분석 기간 안에 달력에 없는 해가 있으면 UnknownYearError. 앞뒤 하루(자정 넘김용 여유)가
    달력에 없는 해이면 그 날은 넣지 않는다(`slot_tag` 는 정보 없는 날을 휴일로 본다).
    """
    d0, d1 = _as_date(ev.d0, "ev.d0"), _as_date(ev.d1, "ev.d1")
    if d1 < d0:
        raise ValueError(f"분석 기간 거꾸로: {d0} > {d1}")
    miss = cal.missing_years(d0, d1)
    if miss:
        raise UnknownYearError(miss)
    std = _win(cfg["time.window.std"])
    lunch = _win(cfg["time.window.lunch"])
    dinner = _win(cfg["time.window.dinner"])
    half_am = _win(cfg["time.window.halfAmOff"])
    half_pm = _win(cfg["time.window.halfPmOff"])
    leaves: dict[date, str] = {}
    for k, v in (getattr(ev, "leaves", None) or {}).items():
        if v not in LEAVE_CODES:
            raise ValueError(f"근태 코드 오류 {v!r}(full·am·pm)")
        leaves[_as_date(k, "leaves")] = v
    absent = set()
    for m in getattr(ev, "manual", None) or ():
        if _field(m, "kind") == "absence" and _field(m, "d") is not None:
            absent.add(_as_date(_field(m, "d"), "manual.d"))
    days: dict[date, DayInfo] = {}
    d = d0 - timedelta(days=1)
    end = d1 + timedelta(days=1)
    while d <= end:
        in_range = d0 <= d <= d1
        if not in_range and d.year not in cal.years:
            d += timedelta(days=1)
            continue
        hol = cal.is_holiday(d)
        z = day0(d)
        s_eff = [] if hol else _day_iv(z, std)
        lv = leaves.get(d)
        frac = 0.0
        if not hol and lv == "full":
            s_eff, frac = [], 1.0
        elif not hol and lv == "am":
            s_eff, frac = _sub(s_eff, _day_iv(z, half_am)), 0.5
        elif not hol and lv == "pm":
            s_eff, frac = _sub(s_eff, _day_iv(z, half_pm)), 0.5
        days[d] = DayInfo(hol=hol, S=s_eff, lunch=[] if hol else _day_iv(z, lunch),
                          dinner=[] if hol else _day_iv(z, dinner), leave=frac, lv=lv,
                          confirmed_absence=d in absent, in_range=in_range)
        d += timedelta(days=1)
    return days


def slot_tag(slot: int, days: Mapping[date, DayInfo], cfg) -> str:
    """슬롯(로컬 초 // 300) 꼬리표 — 배타: holiday > night > extended > regular(W §3.13).

    holiday = 슬롯 시작 날짜가 휴일(정보 없는 날 포함) · night = 슬롯 시작 시각 ∈ `time.window.night`
    · regular = 슬롯 ⊆ S_eff − 점심(그 날 또는 자정을 넘긴 전날 창) · 그 밖 extended.
    """
    t = int(slot) * SLOT
    d = d_of(t)
    info = days.get(d)
    if info is None or info["hol"]:
        return "holiday"
    if _in_daily(t - day0(d), _win(cfg["time.window.night"])):
        return "night"
    spans: list[tuple[int, int]] = []
    meals: list[tuple[int, int]] = []
    for dd in (d, d - timedelta(days=1)):          # 전날 창이 자정을 넘겨 이 날로 이어질 수 있다
        di = days.get(dd)
        if di is not None:
            spans += di["S"]
            meals += di["lunch"]
    e = t + SLOT
    for a, b in _sub(_merge(spans), meals):
        if a <= t and e <= b:
            return "regular"
    return "extended"


# ───────────────────────────── 내부 ─────────────────────────────
def _as_date(x, where: str = "날짜") -> date:
    if isinstance(x, datetime):
        return x.date()
    if isinstance(x, date):
        return x
    if isinstance(x, str) and _ISO_DATE.match(x):
        try:
            return date.fromisoformat(x)
        except ValueError as e:
            raise ValueError(f"{where}: 없는 날짜 {x}") from e
    raise ValueError(f"{where}: 날짜는 date 또는 'YYYY-MM-DD' 여야 한다({type(x).__name__})")


def _month_bounds(y: int, m: int) -> tuple[date, date]:
    if isinstance(y, bool) or not isinstance(y, int) or isinstance(m, bool) or not isinstance(m, int) \
            or not 1 <= m <= 12:
        raise ValueError(f"연·월 오류 {y!r}-{m!r}")
    first = date(y, m, 1)
    nxt = date(y + 1, 1, 1) if m == 12 else date(y, m + 1, 1)
    return first, nxt - timedelta(days=1)


@functools.lru_cache(maxsize=64)
def _win(s: str) -> tuple[int, int]:
    """'HH:MM-HH:MM' → (시작 초, 끝 초). 끝 < 시작 = 자정을 넘김, 끝 = 시작 = 빈 창. 24:00 은 끝에만."""
    if not isinstance(s, str):
        raise TypeError(f"시각 구간은 문자열이어야 한다: {type(s).__name__}")
    m = _WIN_RE.match(s.strip())
    if not m:
        raise ValueError(f"시각 구간 형식 오류 {s!r} — 'HH:MM-HH:MM'")
    h0, m0, h1, m1 = (int(g) for g in m.groups())
    if h0 > 23 or m0 > 59 or m1 > 59 or h1 > 24 or (h1 == 24 and m1 != 0):
        raise ValueError(f"시각 구간 값 오류 {s!r}")
    return h0 * 3600 + m0 * 60, h1 * 3600 + m1 * 60


def _day_iv(z: int, w: tuple[int, int]) -> list[tuple[int, int]]:
    a, b = w
    if a == b:
        return []
    return [(z + a, z + b)] if b > a else [(z + a, z + b + DAY)]


def _in_daily(m: int, w: tuple[int, int]) -> bool:
    a, b = w
    if a == b:
        return False
    return a <= m < b if a < b else (m >= a or m < b)


def _merge(A):
    """겹치거나 맞닿은 구간 합치기(작은 목록 전용)."""
    out: list[tuple[int, int]] = []
    for a, b in sorted(A):
        if out and a <= out[-1][1]:
            if b > out[-1][1]:
                out[-1] = (out[-1][0], b)
        else:
            out.append((a, b))
    return out


def _sub(A, B):
    """구간 목록 차집합 A − B(작은 목록 전용)."""
    out = []
    for a, b in A:
        segs = [(a, b)]
        for c, e in B:
            nxt = []
            for x, y in segs:
                if e <= x or c >= y:
                    nxt.append((x, y))
                    continue
                if x < c:
                    nxt.append((x, c))
                if e < y:
                    nxt.append((e, y))
            segs = nxt
        out.extend(segs)
    return out


def _field(obj, name: str):
    return obj.get(name) if isinstance(obj, Mapping) else getattr(obj, name, None)


def _strict_json(raw: bytes):
    """UTF-8(BOM 허용) · 중복 키 거부 · NaN/Infinity 거부."""
    def pairs(items):
        out = {}
        for k, v in items:
            if k in out:
                raise ValueError(f"달력 JSON 중복 키 {k!r}")
            out[k] = v
        return out

    def bad_const(c):
        raise ValueError(f"달력 JSON 에 {c} 금지")

    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        raise ValueError("달력 파일이 UTF-8 이 아니다") from e
    try:
        return json.loads(text, object_pairs_hook=pairs, parse_constant=bad_const)
    except json.JSONDecodeError as e:
        raise ValueError(f"달력 JSON 형식 오류: {e.msg}(줄 {e.lineno})") from e
    except RecursionError:
        raise ValueError("달력 JSON 중첩이 너무 깊다") from None


def _int(v, where: str, lo: int, hi: int) -> int:
    if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
        raise ValueError(f"{where}: {lo}~{hi} 정수여야 한다({v!r})")
    return v


def _text(v, where: str) -> str:
    if not isinstance(v, str) or not v.strip():
        raise ValueError(f"{where}: 빈 문자열 불가")
    return v


def _weekdays(v, where: str) -> frozenset[int]:
    if not isinstance(v, list | tuple) or not v:
        raise ValueError(f"{where}: 0~6 요일 목록이어야 한다")
    out = [_int(x, where, 0, 6) for x in v]
    if len(set(out)) != len(out):
        raise ValueError(f"{where}: 요일 중복")
    return frozenset(out)


def _validate(obj) -> dict:
    """계약 §3.21 모양 검증(fail-closed). 모르는 키는 무시한다(앞으로의 판 호환)."""
    if not isinstance(obj, Mapping):
        raise ValueError("달력은 JSON 객체여야 한다")
    version = _text(obj.get("version"), "version")
    std = _int(obj.get("std_day_min"), "std_day_min", 1, 1440)
    wds = _weekdays(obj.get("weekdays"), "weekdays")
    note = obj.get("note", "")
    if not isinstance(note, str):
        raise ValueError("note: 문자열이어야 한다")
    years_raw = obj.get("years")
    if not isinstance(years_raw, list) or not years_raw:
        raise ValueError("years: 비지 않은 목록이어야 한다")
    years: set[int] = set()
    hols: dict[date, str] = {}
    for yi, y in enumerate(years_raw):
        if not isinstance(y, Mapping):
            raise ValueError(f"years[{yi}]: 객체여야 한다")
        yr = _int(y.get("year"), f"years[{yi}].year", 1970, 2199)
        if yr in years:
            raise ValueError(f"years: {yr} 중복")
        years.add(yr)
        hl = y.get("holidays")
        if not isinstance(hl, list):
            raise ValueError(f"{yr}.holidays: 목록이어야 한다")
        for hi, h in enumerate(hl):
            w = f"{yr}.holidays[{hi}]"
            if not isinstance(h, Mapping):
                raise ValueError(f"{w}: 객체여야 한다")
            d = _as_date(h.get("date"), f"{w}.date")
            if d.year != yr:
                raise ValueError(f"{w}.date {d} 가 {yr} 년이 아니다")
            if d in hols:
                raise ValueError(f"{w}.date {d} 중복")
            name = _text(h.get("name"), f"{w}.name")
            _text(h.get("kind"), f"{w}.kind")
            url = _text(h.get("source_url"), f"{w}.source_url")
            if not url.startswith(("https://", "http://")):
                raise ValueError(f"{w}.source_url: http(s) 주소여야 한다")
            _as_date(h.get("confirmed"), f"{w}.confirmed")
            hols[d] = name
    co = obj.get("company_off", [])
    if not isinstance(co, list):
        raise ValueError("company_off: 날짜 목록이어야 한다")
    company = {_as_date(x, "company_off") for x in co}
    return {"version": version, "std_day_min": std, "weekdays": wds, "note": note,
            "years": years, "holidays": hols, "company_off": company}
