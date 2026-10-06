# -*- coding: utf-8 -*-
r"""MM·초과·가용·정수 분 표 — 시간 코어 B(W §5.6 · §6 · 부록 A `mm.py`, 계약 §3.14 · §5.3 · X-208~X-211 · TAB §2.3.2).

- `team_tables(slots, assign, days, cfg)`: 개인 = 팀 공용 **정수 분 표**(W §5.6 · TAB R-3). (날짜, 꼬리표) 칸마다
  봉투 분 = 5 × 슬롯 수, 칸 안 대상별 초를 최대잉여법(`intervals.lr_minutes`, 동률 = 단위업무 먼저 — 계약 §5.3)으로
  정수 분으로 나눠 Σ = 봉투 분을 정확히 맞춘다. `alloc_daily` 에는 단위업무만 싣고 버킷은 미귀속으로 남긴다.
  개인 보고서·팀 묶음의 모든 분은 이 표에서 나온다(관문 G5 · T-05: Σalloc ≤ env, effort = Σalloc).
- `month_mm(env, assign, days, cfg, cal, as_of)`: 월 MM(W §6.1) = 봉투 분 ÷ (달력 `std_day_min` × 분모 근무일).
  1.0 초과를 자르지 않는다(상한 없음). 분모는 `mm.denominator`(workdays 기본 — weekdays 는 **개인 표시 전용**,
  팀 묶음은 늘 workdays, X-209). 가용·로드는 TAB 식 하나(X-210): `avail_days = covered_workdays − absence_days`
  (오늘은 as_of 가 그날 표준창 끝을 지났을 때만 covered), `load_pct = env_min ÷ (std × avail) × 100`(가용 0 이면 null).
  추정 부재는 `mm.inferredAbsence='exclude'` 일 때만 뺀다. 초과는 두 기준을 모두 싣고(`overtime_window_min` ·
  `overtime_daily8h_min`), `mm.overtimeBasis` 로 고른 쪽을 `overtime_min` 에 둔다(화면 표시). 계약 §3.14 열 밖의
  보조 열: `denominator` · `denom_days` · `std_day_min` · `overtime_basis` · `overtime_min`.
- `rollup(month, labels)`: 단위업무 MM 을 영역·과제·역할·업무 유형으로 굴려 올린다(라벨 없음 = 'UNC', 숨기지 않음).
  버킷(B_MEET 포함)은 과제로 옮기지 않는다(X-211 — 미귀속은 'unattributed').

모든 시간량은 정수 분, MM·로드는 float(표시는 `lm27.report.fmt`). 표준 라이브러리만 쓴다. 파일을 쓰지 않는다.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, timedelta

from lm27.time.calendar import SLOT, TAGS, d_of, day0, slot_tag
from lm27.time.intervals import lr_minutes

__all__ = [
    "BUCKETS",
    "TeamTables",
    "month_key",
    "month_mm",
    "rollup",
    "team_tables",
]

MIN = 60
SLOT_MIN = SLOT // MIN
BUCKETS = ("B_GENERIC", "B_COMM", "B_MEET", "B_OFFPC", "B_UNKNOWN")
UNC = "UNC"


def month_key(y: int, m: int) -> str:
    return f"{y:04d}-{m:02d}"


def _hm(s: str) -> tuple[int, int]:
    a, b = str(s).strip().split("-")
    h0, m0 = a.split(":")
    h1, m1 = b.split(":")
    return int(h0) * 3600 + int(m0) * MIN, int(h1) * 3600 + int(m1) * MIN


def _in_daily(m: int, w: tuple[int, int]) -> bool:
    a, b = w
    if a == b:
        return False
    return a <= m < b if a < b else (m >= a or m < b)


@dataclass
class TeamTables:
    """정수 분 표. env = {(날짜, 꼬리표): 분}, alloc = {(날짜, unit_id, 꼬리표): 분}, bucket = {(날짜, 버킷, 꼬리표): 분}."""
    env: dict[tuple[date, str], int]
    alloc: dict[tuple[date, str, str], int]
    bucket: dict[tuple[date, str, str], int] = field(default_factory=dict)

    def as_json(self) -> dict:
        """team_tables.json(계약 §3.14): envelope_daily · alloc_daily — 정수 분, 날짜 오름차순."""
        by_d: dict[date, dict[str, int]] = defaultdict(lambda: dict.fromkeys(TAGS, 0))
        for (d, tag), v in self.env.items():
            by_d[d][tag] += v
        env_rows = [[d.isoformat()] + [by_d[d][t] for t in TAGS] for d in sorted(by_d)]
        order = {t: i for i, t in enumerate(TAGS)}
        alloc_rows = [[d.isoformat(), u, tag, v] for (d, u, tag), v in
                      sorted(self.alloc.items(), key=lambda x: (x[0][0], x[0][1], order[x[0][2]])) if v > 0]
        return {"envelope_daily": {"cols": ["date", *TAGS], "rows": env_rows},
                "alloc_daily": {"cols": ["date", "unit_id", "tag", "min"], "rows": alloc_rows}}

    def effort_min(self) -> Counter:
        """unit_id → 기간 정수 분(= Σ alloc — I6)."""
        out: Counter = Counter()
        for (_d, u, _t), v in self.alloc.items():
            out[u] += v
        return out


def team_tables(slots, assign: Mapping, days: Mapping, cfg, *, tags: Mapping | None = None) -> TeamTables:
    """W §5.6 정수 분 표. tags = {슬롯: 꼬리표}(봉투가 이미 계산한 것 — 없으면 `slot_tag`)."""
    env_min: dict[tuple[date, str], int] = defaultdict(int)
    sec: dict[tuple[date, str], dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for s in sorted(slots):
        tag = tags[s] if tags is not None and s in tags else slot_tag(s, days, cfg)
        key = (d_of(s * SLOT), tag)
        env_min[key] += SLOT_MIN
        for tid, v in assign[s].items():
            sec[key][tid] += v
    alloc: dict[tuple[date, str, str], int] = {}
    bucket: dict[tuple[date, str, str], int] = {}
    for key, em in sorted(env_min.items()):
        mins = lr_minutes(dict(sec[key]), em)
        for tid, v in mins.items():
            if v <= 0:
                continue
            if tid.startswith("B_"):
                bucket[(key[0], tid, key[1])] = v
            else:
                alloc[(key[0], tid, key[1])] = v
    for key, em in env_min.items():
        got = sum(v for (d, _u, g), v in alloc.items() if (d, g) == key)
        if got > em:
            raise AssertionError(f"정수 분 표 위반: Σalloc {got} > envelope {em} ({key})")
    return TeamTables(dict(env_min), alloc, bucket)


def _covered(d: date, as_of: int, std_end: int) -> bool:
    """오늘은 분석 시각이 그날 표준창 끝을 지났을 때만 덮은 날(X-210)."""
    a = d_of(as_of)
    if d < a:
        return True
    if d > a:
        return False
    return as_of >= day0(d) + std_end


def month_mm(env, assign: Mapping, days: Mapping, cfg, cal, as_of: int, *, tables: TeamTables | None = None,
             tasks=None, ev=None) -> dict[tuple[int, int], dict]:
    """월별 결과(mm_month.json 행 — 계약 §3.14). 키 = (연, 월). tables 를 주지 않으면 여기서 만든다."""
    tb = tables or team_tables(env.slots, assign, days, cfg, tags=getattr(env, "tags", None))
    denom_kind = cfg["mm.denominator"]
    absence_mode = cfg["mm.inferredAbsence"]
    basis = cfg["mm.overtimeBasis"]                   # 화면이 쓰는 초과 기준(두 기준을 모두 싣고 고른 쪽을 따로)
    std_end = _hm(cfg["time.window.std"])[1]
    night = _hm(cfg["time.window.night"])
    std = int(cal.std_day_min)
    d0, d1 = _bounds(days)
    months: set[tuple[int, int]] = set()
    for (d, _t) in tb.env:
        months.add((d.year, d.month))
    d = d0
    while d <= d1:
        months.add((d.year, d.month))
        d += timedelta(days=1)
    env_min: dict = defaultdict(Counter)
    for (dd, tag), v in tb.env.items():
        env_min[(dd.year, dd.month)][tag] += v
    alloc_m: dict = defaultdict(Counter)
    for (dd, u, _t), v in tb.alloc.items():
        alloc_m[(dd.year, dd.month)][u] += v
    bucket_m: dict = defaultdict(Counter)
    for (dd, bk, _t), v in tb.bucket.items():
        bucket_m[(dd.year, dd.month)][bk] += v
    day_min: Counter = Counter()
    for (dd, _t), v in tb.env.items():
        day_min[dd] += v
    hol_night: Counter = Counter()
    on_leave: Counter = Counter()
    leave_slots = getattr(env, "on_leave", set()) or set()
    for s in env.slots:
        t = s * SLOT
        dd = d_of(t)
        info = days.get(dd)
        if (info is None or info["hol"]) and _in_daily(t - day0(dd), night):
            hol_night[(dd.year, dd.month)] += SLOT_MIN
        if s in leave_slots:
            on_leave[(dd.year, dd.month)] += SLOT_MIN
    machine_s: Counter = Counter()
    for tk in tasks or ():
        for a, b in getattr(tk, "machine_iv", ()) or ():
            _split_month(a, b, machine_s)
    msg_days = {d_of(m.t) for m in (ev.msgs if ev is not None else ())}
    env_days = set(day_min)
    out: dict[tuple[int, int], dict] = {}
    for (y, m) in sorted(months):
        wd = int(cal.month_workdays(y, m))
        wkd = int(cal.month_weekdays(y, m))
        denom = wd if denom_kind == "workdays" else wkd
        covered, absence = 0, 0.0
        d = date(y, m, 1)
        while d.month == m:
            if d0 <= d <= d1 and not _is_off(cal, days, d) and _covered(d, as_of, std_end):
                covered += 1
                info = days.get(d, {})
                lv = float(info.get("leave", 0.0) or 0.0) + (1.0 if info.get("confirmed_absence") else 0.0)
                if absence_mode == "exclude" and d not in env_days and d not in msg_days and not info.get("leave"):
                    lv = 1.0                          # 추정 부재(근거 0 평일)를 가용에서 뺀다 — 기본은 확인 전 표시만
                absence += min(1.0, lv)
            d += timedelta(days=1)
        em = sum(env_min[(y, m)].values())
        by_tag = {t: int(env_min[(y, m)].get(t, 0)) for t in TAGS}
        attributed = sum(alloc_m[(y, m)].values())
        buckets = {b: int(bucket_m[(y, m)].get(b, 0)) for b in BUCKETS}
        ot_window = em - by_tag["regular"]
        ot_daily = 0
        for dd, v in day_min.items():
            if (dd.year, dd.month) != (y, m):
                continue
            ot_daily += v if _is_off(cal, days, dd) else max(0, v - std)
        avail = covered - absence
        denom_min = std * denom
        out[(y, m)] = {
            "month": month_key(y, m), "workdays": wd, "covered_workdays": covered,
            "absence_days": round(absence, 4), "avail_days": round(avail, 4), "env_min": int(em),
            "by_tag_min": by_tag, "attributed_min": int(attributed), "unattributed_min": int(em - attributed),
            "buckets_min": buckets, "overtime_window_min": int(ot_window), "overtime_daily8h_min": int(ot_daily),
            "holiday_night_min": int(hol_night[(y, m)]), "on_leave_min": int(on_leave[(y, m)]),
            "machine_min": int(machine_s[(y, m)] // MIN),
            "mm": (em / denom_min) if denom_min else None,
            "load_pct": (em / (std * avail) * 100.0) if avail > 0 else None,
            "units_mm": {u: v / denom_min for u, v in sorted(alloc_m[(y, m)].items())} if denom_min else {},
            "rollup": {},
            "denominator": denom_kind, "denom_days": denom, "std_day_min": std,
            "overtime_basis": basis, "overtime_min": int(ot_window if basis == "window" else ot_daily),
        }
    return out


def _bounds(days: Mapping) -> tuple[date, date]:
    rng = [d for d, i in days.items() if i.get("in_range")]
    if not rng:
        ks = sorted(days)
        return (ks[0], ks[-1]) if ks else (date.max, date.min)
    return min(rng), max(rng)


def _is_off(cal, days: Mapping, d: date) -> bool:
    info = days.get(d)
    if info is not None:
        return bool(info["hol"])
    try:
        return bool(cal.is_holiday(d))
    except ValueError:
        return d.weekday() not in getattr(cal, "weekdays", frozenset({0, 1, 2, 3, 4}))


def _split_month(a: int, b: int, acc: Counter) -> None:
    """[a, b) 를 로컬 달 경계로 나눠 (연, 월) 별 초를 더한다."""
    t = a
    while t < b:
        d = d_of(t)
        nxt = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
        e = min(b, day0(nxt))
        acc[(d.year, d.month)] += e - t
        t = e


def rollup(month: Mapping, labels: Mapping | None) -> dict[str, dict]:
    """단위업무 MM(`month['units_mm']`)을 계층으로 굴려 올린다(W §6.1 · H §… `labels[unit_id] = {domain, project,
    role, wtype, ax_link}`). 라벨 없음 = 'UNC'. 미귀속(버킷)은 'unattributed' 한 값으로 — 과제로 옮기지 않는다(X-211).

    반환 {"domain": {코드: mm}, "project": {...}, "role": {...}, "wtype": {...}, "ax_link": {"true"|"false": mm},
    "unattributed": mm}. Σ domain + unattributed = month['mm'](I3 — 부동소수 합 오차만).
    """
    units = month.get("units_mm") or {}
    labels = labels or {}
    out: dict[str, dict] = {"domain": defaultdict(float), "project": defaultdict(float), "role": defaultdict(float),
                            "wtype": defaultdict(float), "ax_link": defaultdict(float)}

    def g(lab, *names):
        for n in names:
            v = lab.get(n) if isinstance(lab, Mapping) else getattr(lab, n, None)
            if v:
                return v
        return None
    for u in sorted(units):
        v = units[u]
        lab = labels.get(u) or {}                     # 사전 또는 UnitLabel 같은 속성 객체
        out["domain"][str(g(lab, "domain") or UNC)] += v
        out["project"][str(g(lab, "project", "proposal_id") or UNC)] += v
        out["role"][str(g(lab, "role", "role_id") or UNC)] += v
        out["wtype"][str(g(lab, "wtype") or UNC)] += v
        out["ax_link"]["true" if g(lab, "ax_link") else "false"] += v
    res: dict[str, dict] = {k: dict(sorted(v.items())) for k, v in out.items()}
    mm = month.get("mm") or 0.0
    res["unattributed"] = mm - sum(units.values())
    return res
