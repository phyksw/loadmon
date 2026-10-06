# -*- coding: utf-8 -*-
r"""보고서 표시 함수 · 나눗셈 단일원(R §3.1 · §3.2 · 부록 A, 계약 §2.14 · L-19 · G-R11 · X-281).

화면(JS)과 CSV·해석 문장(파이썬)이 같은 숫자를 다르게 반올림하지 않도록, 표시는 **정수 연산만** 쓰는 함수 한 벌로 한다.
`web\common\lm27ui.js` 의 같은 이름 함수(fmtH1·fmtRatio·fmtMM·fmtPct·fmtDays·fmtSigned·fmtNum·fmtX·hText·mmText·pctText·
daysText·shareText)와 **글자 단위로 같은 결과**를 낸다(RPT-11 — 교차 사례 `tests\fixtures\wp28\fmt_js.json`).
파이썬 `round()`(은행가 반올림)·`format(x, '.2f')`·JS `toFixed` 는 표시에 쓰지 않는다.

이 모듈은 보고서 층(`lm27\report\**` — 분석층·모델·내보내기·CSV)의 **유일한 나눗셈·반올림 자리**다(RP1 · G-R11 · L-19).
분석층은 비율·중앙값·자카드·최대잉여 배분·영업 분을 모두 여기 함수로 계산한다. 비율은 정확한 유리수(`Fraction`)로
계산한 뒤 정수 half-up 으로 자리를 맞춘다(부동소수 순서·해시 시드와 무관 — 결정성 G-R1).

- 표시: `fmt_h1` `fmt_ratio` `fmt_mm` `fmt_pct` `fmt_days` `fmt_signed` `fmt_num` `fmt_x` `h_text` `mm_text` `pct_text`
  `days_text` `share_text`(W1a CR — WP-28 `fmtNum`·`fmtX`·`pctText`·`shareText` 의 파이썬 짝).
- 산식 도우미: `frac` `dec` `half_up` `ratio` `median` `median_int` `p75_int` `jaccard` `split_largest` `sec_min`
  `ge` `lt` `ceil_mul` `per` · 많은 쌍의 정확한 가중합 `wsum`·`nd_ge`·`nd_half_up`(연관도).
- 영업 시간(R §3.2): `Window` · `window_from_cfg` · `BizCal`(`biz_min`·`wd_between`·`is_workday`) · `biz_min(a, b, cal,
  window)`. 시각은 **로컬 분**(로컬 초 // 60 — 원점 2020-01-01 00:00 로컬, 계약 §3.14 · `lm27.time.calendar.EPOCH`).
  반차·연차는 빼지 않는다(리드타임은 달력 기준 경과 — R §3.2).
- ISO 주(R §4.4.1): `iso_week(d)` → `'YYYY-Www'` · `week_bounds(key)`.

표준 라이브러리만 쓴다(+ 달력 원점·날짜 변환 `lm27.time.calendar` 의 `DAY`·`day0`·`d_of` — X-323). 파일을 쓰지 않는다.
"""
from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from fractions import Fraction

from lm27.time.calendar import DAY, d_of, day0

__all__ = [
    "DASH",
    "DAY_MIN",
    "MINUS",
    "BizCal",
    "Window",
    "biz_min",
    "ceil_mul",
    "days_text",
    "dec",
    "fmt_days",
    "fmt_h1",
    "fmt_mm",
    "fmt_num",
    "fmt_pct",
    "fmt_ratio",
    "fmt_signed",
    "fmt_x",
    "frac",
    "ge",
    "h_text",
    "half_up",
    "iso_week",
    "jaccard",
    "lt",
    "median",
    "median_int",
    "mm_text",
    "nd_ge",
    "nd_half_up",
    "p75_int",
    "pct_text",
    "per",
    "ratio",
    "sec_min",
    "share_text",
    "split_largest",
    "week_bounds",
    "window_from_cfg",
    "wsum",
]

DASH = "—"                 # '자료 없음'(긴 줄표 U+2014) — 0 과 구분한다(R §3.1)
MINUS = "−"           # 음수 표시 '−'(U+2212)
DAY_MIN = 1440
DEFAULT_STD_DAY_MIN = 480
_WIN_RE = re.compile(r"^\s*(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\s*$")
_WEEK_RE = re.compile(r"^(\d{4})-W(\d{2})$")


# ───────────────────────────── 1. 표시 함수(정수 half-up — 파이썬 = JS) ─────────────────────────────
def fmt_h1(minutes: int) -> str:
    """분 → 시간 소수 1자리(half-up, 정수 연산). minutes ≥ 0(JS `fmtH1` 과 같은 글자)."""
    q = (int(minutes) * 10 * 2 + 60) // 120
    return f"{q // 10}.{q % 10}"


def fmt_ratio(num: int, den: int, digits: int) -> str | None:
    """num/den 을 digits 자리로 half-up. den ≤ 0 이면 None(JS `fmtRatio` — X-281 `ratio()`)."""
    if den <= 0:
        return None
    s = 10 ** digits
    q = (num * s * 2 + den) // (2 * den)
    return f"{q // s}.{q % s:0{digits}d}" if digits else str(q)


def fmt_mm(env_min: int, denom_min: int) -> str | None:
    """MM 2자리(`0.99`). 분모 0 이면 None."""
    return fmt_ratio(env_min, denom_min, 2)


def fmt_pct(num: int, den: int, digits: int = 0) -> str | None:
    """백분율 숫자(기호 없음). JS 는 `digits || 0`."""
    return fmt_ratio(num * 100, den, digits or 0)


def fmt_days(biz_min_: int, std_day_min: int = DEFAULT_STD_DAY_MIN) -> str | None:
    """영업 분 → 영업일 1자리(JS `fmtDays` — std 가 0·None 이면 480)."""
    return fmt_ratio(biz_min_, std_day_min or DEFAULT_STD_DAY_MIN, 1)


def fmt_signed(fn, num, *a) -> str:
    """부호 있는 값(증감): 절댓값을 같은 함수로 → '+'·'−'(U+2212), 0 은 '±0'(JS `fmtSigned`)."""
    if num == 0:
        return "±0"
    body = fn(abs(num), *a)
    return ("+" if num > 0 else MINUS) + str(body)


def _js_round(x: float) -> int:
    """JS `Math.round` — 가장 가까운 정수, 동률은 +∞ 쪽(x − floor(x) 는 부동소수에서 정확하다)."""
    f = math.floor(x)
    return f + 1 if (x - f) >= 0.5 else f


def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def fmt_num(v, digits: int) -> str | None:
    """JSON 소수 값(팀 MM·병행도 등)의 표시 — JS `fmtNum`: 1e-6 단위 정수(Math.round)로 바꾼 뒤 정수 half-up.
    0 으로 반올림되면 부호를 붙이지 않는다. 숫자가 아니거나 유한하지 않으면 None."""
    if not _is_num(v):
        return None
    n = _js_round(abs(float(v)) * 1000000.0)
    s = fmt_ratio(n, 1000000, digits)
    return (MINUS + s) if (v < 0 and re.search(r"[1-9]", s)) else s


def fmt_x(parallel) -> str:
    """병행도 `×1.8`(JS `fmtX`). 값 없음 = '—'."""
    s = fmt_num(parallel, 1)
    return DASH if s is None else "×" + s


def h_text(minutes) -> str:
    """분 → `158.0h`(JS `hText`). None = '—'."""
    return DASH if minutes is None else fmt_h1(minutes) + "h"


def mm_text(env_min: int, denom_min: int) -> str:
    """`0.99 MM`(JS `mmText`). 분모 0 이면 '—'."""
    s = fmt_mm(env_min, denom_min)
    return DASH if s is None else s + " MM"


def pct_text(num, den) -> str:
    """비율·로드율 글자(JS `pctText`): 0 → '0%', 1% 미만 → 1자리, 그 밖 정수 % · 분모 없음 → '—'."""
    if den is None or num is None or den <= 0:
        return DASH
    if num == 0:
        return "0%"
    return (fmt_pct(num, den, 1) if num * 100 < den else fmt_pct(num, den, 0)) + "%"


def days_text(biz_min_, std_day_min: int = DEFAULT_STD_DAY_MIN) -> str:
    """`3.2영업일`(JS `daysText`). None = '—'."""
    return DASH if biz_min_ is None else str(fmt_days(biz_min_, std_day_min)) + "영업일"


def share_text(share) -> str:
    """0~1 소수 비중 → 정수 % 글자(JS `shareText` — Math.round(share × 1000) 을 10 으로 half-up)."""
    if not _is_num(share):
        return DASH
    return str(fmt_ratio(_js_round(float(share) * 1000.0), 10, 0)) + "%"


# ───────────────────────────── 2. 산식 도우미(분석층의 유일한 나눗셈 자리) ─────────────────────────────
def dec(x) -> Fraction:
    """설정 숫자(0.3·1.5·480) → 정확한 유리수. float 는 10진 표기 그대로(0.3 → 3/10)."""
    if isinstance(x, bool):
        raise TypeError("dec: bool 은 숫자로 쓰지 않는다")
    if isinstance(x, Fraction):
        return x
    if isinstance(x, int):
        return Fraction(x)
    if isinstance(x, float):
        if not math.isfinite(x):
            raise ValueError("dec: 유한하지 않은 값")
        return Fraction(repr(x))
    return Fraction(str(x))


def frac(num, den) -> Fraction | None:
    """num/den 정확한 유리수. den 0 이면 None."""
    if den == 0:
        return None
    return dec(num) / dec(den)


def per(num, den) -> Fraction:
    """num/den — den 0 이면 0(빈 표본의 비율)."""
    f = frac(num, den)
    return Fraction(0) if f is None else f


def half_up(x, digits: int = 0):
    """정확한 half-up(동률은 +∞ 쪽). digits 0 → int, 그 밖 → float(가장 가까운 2진 표현)."""
    q = dec(x)
    s = 10 ** digits
    n = math.floor(q * s + Fraction(1, 2))
    return int(n) if digits == 0 else float(Fraction(n, s))


def ratio(num, den, digits: int = 3) -> float | None:
    """num/den 을 digits 자리 half-up float. den ≤ 0 이면 None(R §4.2 work_share 등 '소수 3자리')."""
    if den is None or den <= 0:
        return None
    return half_up(frac(num, den), digits)


def ge(num, den, thr) -> bool:
    """num/den ≥ thr(정확한 비교). den 0 이면 False."""
    f = frac(num, den)
    return f is not None and f >= dec(thr)


def lt(num, den, thr) -> bool:
    """num/den < thr(정확한 비교). den 0 이면 False."""
    f = frac(num, den)
    return f is not None and f < dec(thr)


def ceil_mul(x, n: int) -> int:
    """ceil(x × n) — 정확한 유리수(R §4.2 지지도 문턱 ceil(0.3 × N))."""
    return math.ceil(dec(x) * n)


def sec_min(sec: int) -> int:
    """초 → 분 정수 half-up(표시·통계용. 정수 분 표의 분은 시간 코어 최대잉여 값을 그대로 쓴다)."""
    return half_up(Fraction(int(sec), 60))


def _sorted_exact(xs: Iterable) -> list:
    """정렬된 표본 — 모두 정수면 정수 그대로(빠른 길), 아니면 정확한 유리수."""
    v = list(xs)
    if all(type(x) is int for x in v):
        v.sort()
        return v
    return sorted(dec(x) for x in v)


def median(xs: Iterable) -> Fraction | None:
    """정확한 중앙값(짝수 개는 가운데 둘의 평균). 빈 표본 None."""
    v = _sorted_exact(xs)
    if not v:
        return None
    k = len(v)
    if k % 2:
        return Fraction(v[k // 2])
    return Fraction(v[k // 2 - 1] + v[k // 2]) / 2


def median_int(xs: Iterable) -> int | None:
    """중앙값 → 정수 half-up(R §4.2 median_min). 빈 표본 None."""
    m = median(xs)
    return None if m is None else half_up(m)


def p75_int(xs: Iterable) -> int | None:
    """75 백분위(최근순위 방식: 정렬 후 ceil(0.75 × n) 번째) → 정수 half-up. 빈 표본 None."""
    v = _sorted_exact(xs)
    if not v:
        return None
    k = math.ceil(Fraction(3, 4) * len(v))
    return half_up(v[max(1, k) - 1])


def wsum(terms: Iterable[tuple]) -> tuple[int, int]:
    """Σ wᵢ·(nᵢ/dᵢ) 를 정확한 정수 분수 (N, D) 로(가중 = `dec` 값, dᵢ = 0 인 항은 0). 큰 표본의 연관도처럼 같은 계산을
    많이 할 때 Fraction 정규화 비용 없이 정확하게 — 비교·반올림은 `nd_ge`·`nd_half_up`."""
    n, d = 0, 1
    for w, num, den in terms:
        if not den or not num:
            continue
        wf = dec(w)
        if wf == 0:
            continue
        tn, td = wf.numerator * int(num), wf.denominator * int(den)
        n, d = n * td + tn * d, d * td
    return n, d


def nd_ge(n: int, d: int, thr) -> bool:
    """n/d ≥ thr(정확)."""
    t = dec(thr)
    return n * t.denominator >= t.numerator * d


def nd_half_up(n: int, d: int, digits: int) -> float:
    """n/d 를 digits 자리 half-up float(정확한 정수 연산). q/s 는 정수 나눗셈의 올바른 반올림 — `float(Fraction(q, s))` 와
    같은 값이다(분수 객체를 만들지 않아 큰 표본의 연관도 계산이 빠르다 — W2 검토 C07)."""
    s = 10 ** digits
    q = (2 * n * s + d) // (2 * d)
    return q / s


def jaccard(a, b) -> Fraction:
    """자카드 |A∩B| / |A∪B|(둘 다 비면 0)."""
    A, B = set(a), set(b)
    u = len(A | B)
    return Fraction(len(A & B), u) if u else Fraction(0)


def split_largest(total: int, weights: Mapping, order: Iterable | None = None) -> dict:
    """정수 최대잉여 배분 — Σ = total 이 정확히 성립(가중 ≤ 0 키는 빠짐). 잉여 동률은 `order` 순(없으면 키 순).

    R §3.4: 관측/추정(O·I) 분을 (날짜, 꼬리표, 업무) 칸 안에서 다시 나눌 때 동률은 'O' 가 먼저다.
    가중이 모두 0 이면 첫 키(order 순)에 total 을 준다(빈 칸 없이 Σ 를 지킨다)."""
    if isinstance(total, bool) or not isinstance(total, int) or total < 0:
        raise ValueError(f"split_largest: total 은 0 이상 정수({total!r})")
    rank = {k: i for i, k in enumerate(order or ())}
    keys = sorted(weights, key=lambda k: (rank.get(k, len(rank)), str(k)))
    w = {k: dec(weights[k]) for k in keys if dec(weights[k]) > 0}
    if total == 0:
        return {}
    if not w:
        return {keys[0]: total} if keys else {}
    s = sum(w.values())
    base = {k: math.floor(total * v / s) for k, v in w.items()}
    rem = total - sum(base.values())
    by_rem = sorted(w, key=lambda k: (-(total * w[k] / s - base[k]), rank.get(k, len(rank)), str(k)))
    for k in by_rem[:rem]:
        base[k] += 1
    return {k: int(v) for k, v in base.items() if v > 0}


# ───────────────────────────── 3. 영업 시간(R §3.2) ─────────────────────────────
@dataclass(frozen=True)
class Window:
    """하루 정규 구역(로컬 분, [a, b) 목록 — 개인 표준창 − 점심). 기본 09:00~12:00 · 13:00~18:00."""
    zones: tuple[tuple[int, int], ...] = ((540, 720), (780, 1080))

    @property
    def day_min(self) -> int:
        return sum(b - a for a, b in self.zones)


def _hm(s) -> tuple[int, int]:
    m = _WIN_RE.match(str(s or ""))
    if not m:
        raise ValueError(f"시간 창 형식 오류 {s!r}(HH:MM-HH:MM)")
    h0, m0, h1, m1 = (int(x) for x in m.groups())
    return h0 * 60 + m0, h1 * 60 + m1


def _day_parts(a: int, b: int) -> list[tuple[int, int]]:
    if a == b:
        return []
    if a < b:
        return [(a, b)]
    return [(a, DAY_MIN), (0, b)]                   # 자정을 넘기는 창 — 같은 달력 날짜의 두 조각


def _sub(zs: list[tuple[int, int]], cuts: list[tuple[int, int]]) -> list[tuple[int, int]]:
    out = []
    for a, b in zs:
        cur = [(a, b)]
        for c0, c1 in cuts:
            nxt = []
            for x, y in cur:
                if c1 <= x or c0 >= y:
                    nxt.append((x, y))
                    continue
                if x < c0:
                    nxt.append((x, c0))
                if c1 < y:
                    nxt.append((c1, y))
            cur = nxt
        out += cur
    return sorted(z for z in out if z[1] > z[0])


def window_from_cfg(cfg) -> Window:
    """개인 근무창 설정(`time.window.std` − `time.window.lunch`) → 정규 구역(R §3.2)."""
    std = _day_parts(*_hm(cfg["time.window.std"]))
    lunch = _day_parts(*_hm(cfg["time.window.lunch"]))
    return Window(tuple(_sub(std, lunch)))


class BizCal:
    """달력 + 정규 구역 — 영업 분·근무일 계산(R §3.2). `cal` = `lm27.time.calendar.Calendar`(또는 같은 모양).

    달력 `years` 밖 날짜(분석 기간 밖 근거 — 드묾)는 달력 `weekdays` 만으로 근무일을 정한다(공휴일 정보 없음)."""

    def __init__(self, cal, window: Window | None = None):
        self.cal = cal
        self.window = window or Window()
        self._wd: dict[int, bool] = {}
        self._pre_lo: int | None = None
        self._pre: list[int] = []

    @classmethod
    def from_cfg(cls, cal, cfg) -> BizCal:
        return cls(cal, window_from_cfg(cfg))

    @property
    def zone_min(self) -> int:
        return self.window.day_min

    @property
    def std_day_min(self) -> int:
        return int(getattr(self.cal, "std_day_min", 0) or DEFAULT_STD_DAY_MIN)

    # ── 근무일 ──
    def _is_wd_ix(self, ix: int) -> bool:
        v = self._wd.get(ix)
        if v is None:
            d = d_of(ix * DAY)
            years = getattr(self.cal, "years", None)
            if years is not None and d.year not in years:
                wk = getattr(self.cal, "weekdays", None) or frozenset({0, 1, 2, 3, 4})
                v = d.weekday() in wk
            else:
                v = not bool(self.cal.is_holiday(d))
            self._wd[ix] = v
        return v

    def is_workday(self, d) -> bool:
        return self._is_wd_ix(day0(_as_date(d)) // DAY)

    def _count(self, lo: int, hi: int) -> int:
        """[lo, hi] 날짜 색인 안 근무일 수(누적합 — 필요한 범위만 늘린다)."""
        if hi < lo:
            return 0
        if self._pre_lo is None or lo < self._pre_lo or hi >= self._pre_lo + len(self._pre) - 1:
            a = lo if self._pre_lo is None else min(lo, self._pre_lo)
            b = hi if self._pre_lo is None else max(hi, self._pre_lo + len(self._pre) - 2)
            pre = [0]
            for ix in range(a, b + 1):
                pre.append(pre[-1] + (1 if self._is_wd_ix(ix) else 0))
            self._pre_lo, self._pre = a, pre
        o = self._pre_lo
        return self._pre[hi - o + 1] - self._pre[lo - o]

    def wd_between(self, d1, d2) -> int:
        """(d1, d2] 안 근무일 수. d2 ≤ d1 이면 0(W 부록 A `Calendar.wd_between` 과 같은 뜻)."""
        a, b = _as_date(d1), _as_date(d2)
        if b <= a:
            return 0
        return self._count(day0(a) // DAY + 1, day0(b) // DAY)

    # ── 영업 분 ──
    def _part(self, ix: int, a: int, b: int) -> int:
        """날짜 색인 ix 안의 [a, b)(로컬 분) 중 정규 구역 분."""
        if b <= a or not self._is_wd_ix(ix):
            return 0
        base = ix * DAY_MIN
        tot = 0
        for z0, z1 in self.window.zones:
            lo, hi = max(a, base + z0), min(b, base + z1)
            if hi > lo:
                tot += hi - lo
        return tot

    def biz_min(self, a: int | None, b: int | None) -> int:
        """[a, b) 로컬 분 안 근무일 정규 구역 분(R §3.2). b ≤ a·None 이면 0."""
        if a is None or b is None or b <= a:
            return 0
        da, db = a // DAY_MIN, (b - 1) // DAY_MIN
        if da == db:
            return self._part(da, a, b)
        tot = self._part(da, a, (da + 1) * DAY_MIN) + self._part(db, db * DAY_MIN, b)
        if db - da > 1:
            tot += self._count(da + 1, db - 1) * self.zone_min
        return tot


def biz_min(a: int, b: int, cal, window: Window | None = None) -> int:
    """영업 분(R §3.2 · 부록 A) — cal 이 `BizCal` 이면 그대로, 아니면 `BizCal(cal, window)` 한 번."""
    bc = cal if isinstance(cal, BizCal) else BizCal(cal, window)
    return bc.biz_min(a, b)


def _as_date(d) -> date:
    if isinstance(d, date):
        return d
    return date.fromisoformat(str(d)[:10])


# ───────────────────────────── 4. ISO 주 ─────────────────────────────
def iso_week(d) -> str:
    """날짜 → ISO 주 키 `YYYY-Www`(월요일 시작)."""
    y, w, _ = _as_date(d).isocalendar()
    return f"{y:04d}-W{w:02d}"


def week_bounds(key: str) -> tuple[date, date]:
    """ISO 주 키 → (월요일, 일요일)."""
    m = _WEEK_RE.match(str(key))
    if not m:
        raise ValueError(f"ISO 주 키 형식 오류 {key!r}")
    mon = date.fromisocalendar(int(m.group(1)), int(m.group(2)), 1)
    return mon, mon + timedelta(days=6)
