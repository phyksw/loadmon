# -*- coding: utf-8 -*-
r"""core\timeshare.py — 과제 몫의 시간화(옵션 mm.shareBasis="time") — LM28 WP8(REQ-26·A-24·W2-04).

LM24 의 과제 몫은 '가중치 비율'이다(share = w/Σw × 총 MM — 기본 'weight', 그대로 둔다). shareBasis="time" 이면 그날 투입
시간(day_work_hours 의 합집합 시간 — 총량은 바뀌지 않는다)을 분 단위로 과제에 **나누기만** 한다:
  ① 신호가 덮는 분 — 신호 시각 ± signalMinutes/2(회의·작업창·수동기록은 가중치에서 되짚은 길이). 그 분을 덮는 신호들의
     가중치 비율로 나눈다(같은 분을 두 과제가 덮으면 둘이 나눈다 — 병행 업무가 MM 을 부풀리지 않는다).
  ② 아무 신호도 덮지 않는 근무 분(PC 하한·샘플러 다리·저녁 크레딧 …) — 그날 과제별 직접 분에 비례해 나누되 과제마다
     직접 분 × cap(1.0) 을 넘지 않는다. 넘친 몫은 UNCLASSIFIED('근무 중 미분류')로 남긴다(숨기지 않는다 — A-24 L6·L7).
  · 정수 분 최대잉여법(LM27 time\intervals.split_int 이식) — 날마다 Σ = 그날 투입 분을 assert 한다(시간 보존).
  · 직접 분이 그날 투입보다 많으면(세션 꼬리가 하한 밖으로 나간 날) 투입 분을 직접 분 비율로 나눈다(미분류 0).
LM27 의 5분 슬롯 봉투·L1~L7 우선순위·레지스트리는 들이지 않는다. 표준 라이브러리만 쓰고 파일을 읽거나 쓰지 않는다.
"""
from collections import defaultdict

UNCLASSIFIED = "근무 중 미분류"
CAP_RATIO = 1.0             # 신호 없는 분을 과제에 줄 때 과제별 상한 = 직접 분 × 이 값(UD-10)
# signalMinutes 가 0 인 라벨의 덮는 길이 — 가중치에서 되짚는다(core\extract.load_signals 의 기본 가중치와 같은 단위)
MEET_W_PER_H = 2.0          # 회의: 시간당 2.0 → 길이 = w / 2.0 h (30분~5h)
WIN_MIN_PER_W = {"작업창": 20.0, "작업창(IDE)": 12.0}   # 작업창: 20분당 1.0 · IDE 12분당 1.0
MANUAL_W_PER_H = 2.0        # 수동기록: 시간당 2.0, 09:00 부터


def tie_key(k):
    """최대잉여 동률 정렬 키 — 미분류는 뒤, 나머지는 문자열 사전순(결정적)."""
    s = str(k)
    return (1 if k == UNCLASSIFIED else 0, s)


def split_int(total, weights):
    """정수 최대잉여 배분 — Σ = total 이 정확히 성립한다. 가중 0 이하 키는 빠진다(LM27 intervals.split_int).
    실수 가중은 1/1000 단위 정수로 바꿔 계산한다(결정적). 잉여 동률은 tie_key 순."""
    if isinstance(total, bool) or not isinstance(total, int) or total < 0:
        raise ValueError(f"split_int: total 은 0 이상 정수여야 한다({total!r})")
    w = {k: v for k, v in weights.items() if v > 0}
    if not w or total == 0:
        return {}
    if any(isinstance(v, float) for v in w.values()):
        w = {k: int(round(v * 1000)) for k, v in w.items()}
        w = {k: v for k, v in w.items() if v > 0}
        if not w:
            return {}
    s = sum(w.values())
    base = {k: (total * v) // s for k, v in w.items()}
    rem = total - sum(base.values())
    order = sorted(w, key=lambda k: (-((total * w[k]) % s), tie_key(k)))
    for k in order[:rem]:
        base[k] += 1
    return {k: v for k, v in base.items() if v > 0}


def cover_of(src, minute, weight, minutes_map=None):
    """신호 하나가 덮는 그날 구간(분) (a, b) — 없으면 None. minutes_map = config.mm.signalMinutes(정규화된 값)."""
    m = float(minute)
    try:
        w = float(weight or 0)
    except (TypeError, ValueError):
        w = 0.0
    if w <= 0:
        return None
    if src == "회의":
        dur = min(300.0, max(30.0, w / MEET_W_PER_H * 60.0))
        return (m, min(1440.0, m + dur))
    if src in WIN_MIN_PER_W:
        return (m, min(1440.0, m + max(1.0, w * WIN_MIN_PER_W[src])))
    if src == "수동기록":
        return (m, min(1440.0, m + max(30.0, w / MANUAL_W_PER_H * 60.0)))
    lone = float((minutes_map or {}).get(src, 0) or 0)
    if lone <= 0:
        return None
    half = max(2.5, lone / 2.0)
    a, b = max(0.0, m - half), min(1440.0, m + half)
    return (a, b) if b > a else None


def allocate_day(total_min, covers, cap=CAP_RATIO):
    """하루 분배. total_min = 그날 투입 분(정수), covers = [(a, b, 키, 가중치)] → {키: 분}(Σ = total_min).
    덮는 분은 구간 경계 사이 조각마다 가중치 비율로 실수 누적한 뒤 정수로 나눈다(분 단위 최대잉여)."""
    total_min = int(total_min)
    if total_min <= 0:
        return {}
    pts = sorted({float(x) for a, b, _k, _w in covers for x in (a, b)})
    acc, covered = defaultdict(float), 0.0
    for i in range(len(pts) - 1):
        lo, hi = pts[i], pts[i + 1]
        if hi - lo <= 1e-9:
            continue
        on = [(k, float(w)) for a, b, k, w in covers if a <= lo and b >= hi and w > 0]
        sw = sum(w for _k, w in on)
        if sw <= 0:
            continue
        covered += hi - lo
        for k, w in on:
            acc[k] += (hi - lo) * w / sw
    if not acc:
        out = {UNCLASSIFIED: total_min}
    elif covered >= total_min - 1e-9:
        out = split_int(total_min, dict(acc))
    else:
        direct = split_int(min(total_min, int(round(covered))), dict(acc))
        rest = total_min - sum(direct.values())
        room = min(rest, int(cap * sum(direct.values())))
        extra = split_int(room, {k: float(v) for k, v in direct.items()}) if room > 0 else {}
        out = dict(direct)
        for k, v in extra.items():
            out[k] = out.get(k, 0) + v
        if rest - room > 0:
            out[UNCLASSIFIED] = out.get(UNCLASSIFIED, 0) + rest - room
    assert sum(out.values()) == total_min, f"timeshare: 하루 배분 합 {sum(out.values())} ≠ 투입 {total_min}"
    return out


def allocate(day_minutes, rows, minutes_map=None, cap=CAP_RATIO):
    """기간 분배. day_minutes = {date: 그날 투입 분(int)}, rows = [(datetime, 출처 라벨, 가중치, 키)] →
    ({키: 분}, 통계 {"days", "total_min", "unclassified_min"}). 날마다 Σ = 그날 투입 분."""
    by_day = defaultdict(list)
    for t, src, w, key in rows or []:
        if t is None:
            continue
        cv = cover_of(src, t.hour * 60 + t.minute + t.second / 60.0, w, minutes_map)
        if cv:
            by_day[t.date()].append((cv[0], cv[1], key, float(w)))
    out = defaultdict(int)
    st = {"days": 0, "total_min": 0, "unclassified_min": 0}
    for d, tm in sorted(day_minutes.items()):
        tm = int(tm)
        if tm <= 0:
            continue
        res = allocate_day(tm, by_day.get(d, []), cap)
        st["days"] += 1
        st["total_min"] += tm
        st["unclassified_min"] += res.get(UNCLASSIFIED, 0)
        for k, v in res.items():
            out[k] += v
    assert sum(out.values()) == st["total_min"], "timeshare: 기간 배분 합이 투입과 다르다"
    return dict(out), st


def shares(alloc):
    """{키: 분} → {키: 몫}(합 1.0) — 비면 {}."""
    tot = sum(alloc.values())
    return {k: v / tot for k, v in alloc.items()} if tot else {}
