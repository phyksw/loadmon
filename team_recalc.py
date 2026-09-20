# -*- coding: utf-8 -*-
r"""팀취합본만으로 개인별 로드율 재계산 — 판(LM20 · LM24 v3 계열) 무관.

왜 이 도구가 있나
  개인 PC 의 원자료(PC 가동·샘플러·달력)는 팀에 올라오지 않는다. 팀에 남은 것은 인별 폴더의
  signals_<tag>.csv(신호 원문: 시각·출처·가중치)와 mm_meta_<tag>.json(그 판이 계산한 일별 투입시간·월별 부재)뿐이다.
  두 파일은 LM20 과 LM24 계열이 **글자까지 같은 헤더·키**로 올리므로(teamup FILE_NAMES 동일 — 실측), 이 둘만으로
  모든 인원을 **하나의 산식·하나의 달력**으로 다시 재면 판 차이가 섞인 팀 취합을 같은 자리에서 비교할 수 있다.
  기존 team_report.html 등은 건드리지 않고 새 파일(팀로드율_재계산_<시각>.html/.csv)만 옆에 만든다.

산식(열 이름 그대로) — 표준일 std=8h, 표준 창 09~18시
  D  원값     : mm_meta.day_hours 그대로(그 판의 알고리즘 결과 — 판마다 다르다. 비교 기준선) · mm_meta 가 없으면 빈칸.
  B  근거 구간 : 신호 세션 합집합(v3 core.extract._signal_spans 를 그대로 옮김 — 능동끼리만 45분 다리 · 수동 하루 60분 상한 ·
               야간 수동 제외) ∪ 회의 구간(길이 = weight ÷ weights['회의'], 자정 넘김은 익일로 이월).
               샘플러 활동분(작업창 weight ÷ 분당 가중치)·수동기록 시간(weight ÷ 시간당 가중치)은 구간 위치를 몰라 **하한(max)** 으로.
               주말·공휴일은 능동 흔적이 있는 날만(두 판 공통 규칙).
  A  활동일   : 능동 흔적(산출물·발신·회의·샘플러·수동기록)이 있는 평일 = 8h , 주말·공휴일 활동일 = B , 그 외 0.
  C3 권장     : 능동 평일 = max(B, 8h + 표준 창(09~18) 밖의 **능동 세션** 초과분) , 능동 없는 평일 = B(수동 세션 ≤60분) , 주말·공휴일 = A 규칙.
               (다중 에이전트 실측: 합성 3유형에서 공휴일 보정 참값 대비 −7/−3/−16p 로 세 유형 모두 아래·방향 일정 ·
                신호 30% 유실에도 밀집 유형 −2~−7%. LM20 규칙의 '수동 다리' 과대(회의형 +14p)와 v3 의 PC 없는 날 과소를 둘 다 피한다.
                단 C3 는 PC 가동·샘플러 구간을 보지 못하는 **하한 성격**이라 원 판(D)이 그것을 실측했다면 D 가 더 클 수 있다.)
  가용(분모)   : 통일 달력(주말 + 양력 고정 공휴일 + 내장 연도표 + --holidays) 의 기간 내 평일수 − mm_meta.mm_months[월].absent(부재 일수).
               분석 시점 이후의 평일은 가용이 아니다(v3 A34 규칙을 두 판에 같이 적용 — 기간 종료 전에 올린 자료는 '기간 미완' 표시).
               LM20 의 부재는 기간 전체(미래 연차 포함) 값이라 기간 미완이면 절단 비율로 배분한다. v3 의 부재 '추정'(A31,
               mm_basis.inferred_absence_dates)은 판 의존 재료라 기본 분모에 넣지 않고 표시만 한다(--inferred 로 넣을 수 있다).
  로드율(%)    = 월 투입시간 ÷ (8h × 가용일수) × 100 — workdays·capacity_h 는 약분되므로 이 형태가 판 무관 항등식이다.
               가용이 0 인 달(전월 부재·기간 꼬리)은 비율이 없고 팀 합계에도 넣지 않는다.

한계(팀취합본에 없는 재료 — 어느 산식도 복원하지 못한다)
  PC 가동 구간 · 샘플러 구간(총 분만) · 연차 '일자'(월 합계만) · 회의 수락 여부(수락분만 올라옴) · 표본화 전 파일 시각.
  능동 흔적이 없는 평일은 8h 가 붙지 않아 C3 = 근거 구간뿐이다 — '무흔적 평일(−부재)' 열을 같이 보라.

사용
  python team_recalc.py [팀 폴더] [--out 폴더] [--now "YYYY-MM-DD HH:MM"] [--holidays 2026-11-02,...] [--std 8] [--inferred]
  팀 폴더를 지정하면 그 폴더만 본다(없거나 인별 폴더가 없으면 실패 — 다른 곳으로 조용히 바꾸지 않는다).
  생략하면 이 파일 폴더·상위 폴더의 teamdata\ → config\config.json 의 teamShareDir → 이 파일의 폴더 → 현재 폴더 순서로
  인별 폴더(member.json 또는 mm_meta_*.json·signals_*.csv 가 있는 하위 폴더)가 있는 곳을 찾는다('자동 탐색' 으로 표시).
  어떤 저장소 파일도 임포트하지 않는다(팀 폴더에 이 파일과 bat 만 붙여 넣어도 돈다).
"""
import argparse
import calendar
import csv
import glob
import html
import io
import json
import os
import re
import sys
import tempfile
import time
from datetime import date, datetime, timedelta

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, errors="replace", encoding=(
    (sys.stdout.encoding or "utf-8") if sys.stdout.isatty() else "utf-8"))
csv.field_size_limit(min(sys.maxsize, 2 ** 31 - 1))

VERSION = "team_recalc 1.1"
STD_DAY_H = 8.0
WORK_WIN = (9 * 60, 18 * 60)        # 표준 창 — 8h 바닥이 덮는 시간대(점심 포함). 이 밖의 능동 세션만 초과로 더한다
DAY_WIN = (8 * 60, 19 * 60)         # 야간 판정 경계(v3 DAY_WIN 과 동일 — 야간 수동 신호는 세션을 만들지 않는다)
SESSION_GAP_MIN = 45.0
PASSIVE_DAY_MAX_MIN = 60.0
FUTURE_SLACK_MIN = 5
# ── v3 core/extract.py 와 같은 값(이 파일은 저장소를 임포트하지 않으므로 사본을 둔다 — 바뀌면 여기도 맞춘다) ──
FIXED_HOLIDAYS = {(1, 1), (3, 1), (5, 1), (5, 5), (6, 6), (8, 15), (10, 3), (10, 9), (12, 25)}
KR_HOLIDAYS = {
    2025: {(1, 27), (1, 28), (1, 29), (1, 30), (3, 3), (5, 6), (6, 3), (10, 6), (10, 7), (10, 8)},
    2026: {(2, 16), (2, 17), (2, 18), (3, 2), (5, 25), (6, 3), (8, 17), (9, 24), (9, 25), (9, 28), (10, 5)},
    2027: {(2, 8), (2, 9), (2, 10), (5, 13), (8, 16), (9, 14), (9, 15), (9, 16), (10, 4), (10, 11), (12, 27)},
}
NIGHT_PRODUCTIVE = {"파일", "파일(코드)", "커밋", "메일(발신)", "팀즈(발신)", "수동기록", "메일(발신·일자)"}
LONE_SIGNAL_MIN = {"파일": 60, "파일(코드)": 90, "커밋": 90, "회의": 0,
                   "메일(발신)": 20, "팀즈(발신)": 10, "팀즈(오더)": 15,
                   "메일(수신)": 5, "메일(CC)": 5, "메일(수신전용)": 5, "팀즈(수신)": 5, "팀즈(단체)": 3,
                   "파일(열람)": 5, "파일(타인)": 0, "파일(일괄)": 0, "수동기록": 0, "메일(발신·일자)": 0,
                   "파일(해석출력)": 30, "작업창": 0, "작업창(IDE)": 0}
ACTIVE_SRC = set(NIGHT_PRODUCTIVE) | {"회의", "팀즈(오더)", "작업창", "작업창(IDE)", "파일(해석출력)"}
# 활동일 게이트를 여는 능동 흔적 — '메일(발신·일자)' 는 날짜만 아는 발신(시각 00:00)이라 게이트만 연다(세션 0)
GATE_SRC = set(ACTIVE_SRC)
KNOWN_SRC = set(LONE_SIGNAL_MIN)
TAG_RE = re.compile(r"^(\d{8})-(\d{8})$")
FILE_RE = re.compile(r"^(mm_rows_(\d{8}-\d{8})(_refined)?\.csv|signals_(\d{8}-\d{8})\.csv|mm_meta_(\d{8}-\d{8})\.json)$")
# 인원이 아닌 폴더 — 팀 취합 산출물·예약어·잔재, 그리고 LoadMonitor 설치 폴더의 하위 이름(자동 탐색이 설치 폴더를 팀 폴더로 오인하지 않게)
SKIP_DIR_PREFIX = ("team_", "_staging", "개인리포트", "팀통합보고서", "팀로드율_재계산", ".")
SKIP_DIR_NAMES = {"report", "data", "teamdata", "samples", "config", "python", "docs", "core", "collect", "ui", "tools",
                  "analyze", "__pycache__", "node_modules"}
OUT_PREFIX = "팀로드율_재계산"
FORMULAS = ("C3", "A", "B", "D")


# ───────────────────────── 구간 산술 ─────────────────────────
def _clip(spans, lo, hi):
    return [(max(a, lo), min(b, hi)) for a, b in spans if min(b, hi) > max(a, lo)]


def _union_min(spans):
    total, cur_s, cur_e = 0.0, None, None
    for a, b in sorted((a, b) for a, b in spans if b > a):
        if cur_e is not None and a <= cur_e:
            cur_e = max(cur_e, b)
        else:
            if cur_e is not None:
                total += cur_e - cur_s
            cur_s, cur_e = a, b
    if cur_e is not None:
        total += cur_e - cur_s
    return total


def _is_night(t):
    m = t.hour * 60 + t.minute
    return m >= DAY_WIN[1] or m < DAY_WIN[0]


def signal_spans(signals, d0, d1, now, mins=None, gap=SESSION_GAP_MIN, passive_max=PASSIVE_DAY_MAX_MIN):
    """v3 core.extract._signal_spans 의 사본(extra·stats 제외) — signals = [(datetime, source)].
    · 목록(mins)에 없는/0 인 라벨은 세션을 만들지 않는다 · 야간 수동 신호 제외 · 수동은 다리를 놓지 않고(능동끼리만 gap)
      능동 세션을 닫지도 않는다(pend 보류) · 수동만으로 만든 세션은 하루 passive_max 분까지.
    (검증: 무작위 9,000 케이스에서 v3 원본과 0 불일치)"""
    now = now + timedelta(minutes=FUTURE_SLACK_MIN)
    mins = mins or LONE_SIGNAL_MIN
    by_day = {}
    for t, src in signals:
        if not (d0 <= t.date() <= d1) or t > now:
            continue
        if src == "파일(일괄)" or mins.get(src, 0) <= 0:
            continue
        if _is_night(t) and src not in NIGHT_PRODUCTIVE and src != "회의":
            continue
        by_day.setdefault(t.date(), []).append((t.hour * 60 + t.minute, src))
    out = {}
    for d, items in by_day.items():
        items.sort()
        spans, cur, pend = [], None, []
        for m, src in items:
            lone = mins.get(src, 0)
            half = max(2.5, lone / 2)
            a, b = m - half, m + half
            active = src in ACTIVE_SRC
            if cur:
                g = gap if (active and cur[2]) else 0.0
                if a - cur[1] <= g:
                    cur = (min(cur[0], a), max(cur[1], b), cur[2] or active)
                    if pend:
                        pend = [(max(p0, cur[1]), p1, False) for p0, p1, _ in pend if p1 > cur[1]]
                    continue
                if cur[2] and not active:
                    if pend and a <= pend[-1][1]:
                        pend[-1] = (min(pend[-1][0], a), max(pend[-1][1], b), False)
                        while len(pend) > 1 and pend[-2][1] >= pend[-1][0]:
                            q = pend.pop()
                            pend[-1] = (min(pend[-1][0], q[0]), max(pend[-1][1], q[1]), False)
                    else:
                        pend.append((a, b, False))
                    continue
                spans.append(cur)
                if active:
                    while pend and a <= pend[-1][1]:
                        p0, p1, _ = pend.pop()
                        a, b = min(a, p0), max(b, p1)
                spans.extend(pend)
                pend = []
            cur = (a, b, active)
        if cur:
            spans.append(cur)
            spans.extend(pend)
        res, pas = [], 0.0
        for a, b, ac in spans:
            a, b = max(0.0, a), min(1440.0, b)
            if b <= a:
                continue
            if not ac and passive_max >= 0:
                room = passive_max - pas
                if room <= 1e-9:
                    continue
                if b - a > room:
                    b = a + room
                pas += b - a
            res.append((a, b))
        out[d] = res
    return out


# ───────────────────────── 달력 ─────────────────────────
class Calendar:
    def __init__(self, extra_holidays=()):
        self.extra = set(extra_holidays)

    def off(self, d):
        md = (d.month, d.day)
        return d.isoweekday() >= 6 or d in self.extra or md in FIXED_HOLIDAYS or md in KR_HOLIDAYS.get(d.year, ())

    def full_workdays(self, y, mo):
        return sum(1 for i in range(calendar.monthrange(y, mo)[1]) if not self.off(date(y, mo, i + 1)))


def _parse_dt(s):
    s = str(s or "").strip().replace("T", " ")
    for fmt, n in (("%Y-%m-%d %H:%M:%S", 19), ("%Y-%m-%d %H:%M", 16), ("%Y-%m-%d", 10)):
        try:
            return datetime.strptime(s[:n], fmt)
        except ValueError:
            continue
    return None


def _parse_date(s):
    try:
        return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _tag_dates(tag):
    m = TAG_RE.match(tag or "")
    if not m:
        return None, None
    try:
        return (datetime.strptime(m.group(1), "%Y%m%d").date(), datetime.strptime(m.group(2), "%Y%m%d").date())
    except ValueError:
        return None, None


# ───────────────────────── 읽기 ─────────────────────────
def _jload(p):
    try:
        with open(p, encoding="utf-8-sig", errors="replace") as f:
            v = json.load(f)
        return v if isinstance(v, dict) else None
    except (OSError, ValueError):
        return None


def _read_text(p):
    """CSV 원문 — utf-8-sig 가 기본, Excel 이 ANSI 로 재저장한 파일(cp949)도 읽는다. 빈 파일은 None."""
    with open(p, "rb") as f:
        raw = f.read()
    if not raw.strip():
        return None
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp949", errors="replace")


def read_signals(p):
    """signals_<tag>.csv → {"rows": [(datetime, source, weight)], "bad": 시각 불량 행 수, "err": 읽기 실패 사유 또는 "",
    "lost": 파싱이 삼킨 줄 비율 의심(bool), "unknown_src": 출처 라벨 전부 미인식(bool)}.
    열 7/11 두 형태(앞 7열 고정) · BOM·cp949·LF/CRLF 무관 · 한 파일이 깨져도 예외를 밖으로 내지 않는다(그 사람만 빈칸)."""
    out = {"rows": [], "bad": 0, "err": "", "lost": False, "unknown_src": False}
    try:
        text = _read_text(p)
        if text is None:
            out["err"] = "빈 파일"
            return out
        rd = csv.DictReader(io.StringIO(text, newline=""))
        if not rd.fieldnames or "time" not in rd.fieldnames or "source" not in rd.fieldnames:
            out["err"] = "열 이름이 다름(time·source 없음)"
            return out
        n_rows, known = 0, 0
        for r in rd:
            n_rows += 1
            t = _parse_dt(r.get("time"))
            src = (r.get("source") or "").strip()
            if t is None or not src:
                out["bad"] += 1
                continue
            if src in KNOWN_SRC:
                known += 1
            try:
                wt = float(r.get("weight") or 0)
            except ValueError:
                wt = 0.0
            out["rows"].append((t, src, wt))
        lines = sum(1 for ln in text.splitlines() if ln.strip()) - 1
        if lines > 20 and n_rows < lines * 0.9:
            out["lost"] = True                 # 따옴표 불균형 등으로 파서가 여러 줄을 한 필드로 삼킨 흔적
        if len(out["rows"]) >= 50 and known == 0:
            out["unknown_src"] = True          # 라벨이 하나도 안 맞으면 인코딩·형식이 다른 파일 — 0% 로 섞지 않는다
    except (OSError, csv.Error, UnicodeDecodeError) as e:
        out["err"] = f"읽기 실패({type(e).__name__})"
    return out


def version_of(meta):
    """판별 — 명시 버전 필드가 두 판 어디에도 없어 키 유무로 본다(기간 tag 파일 단위)."""
    if not meta:
        return "unknown"
    if any(k in meta for k in ("measure", "coverage", "cfg_used")):
        return "v3"
    mb = meta.get("mm_basis") or {}
    if isinstance(mb, dict) and any(k in mb for k in ("floor_blocked_passive_days", "lunch_deducted_h", "pc_record_days")):
        return "v3"
    w = meta.get("weights") or {}
    if isinstance(w, dict) and any(k in w for k in ("파일열람", "수동기록_시간당", "파일해석출력")):
        return "v3"
    return "lm20"


def pick_rows_file(mdir, tag):
    """aggregate.load_members 와 같은 규칙 — 정제본이 원본보다 새로우면 정제본."""
    rows_p = os.path.join(mdir, f"mm_rows_{tag}.csv")
    ref_p = os.path.join(mdir, f"mm_rows_{tag}_refined.csv")
    if os.path.exists(ref_p):
        try:
            if not os.path.exists(rows_p) or os.path.getmtime(ref_p) >= os.path.getmtime(rows_p):
                return ref_p
        except OSError:
            return ref_p
    return rows_p if os.path.exists(rows_p) else None


def read_rows(p):
    if not p:
        return []
    try:
        text = _read_text(p)
        if text is None:
            return []
        return [r for r in csv.DictReader(io.StringIO(text, newline="")) if isinstance(r, dict)]
    except (OSError, csv.Error, UnicodeDecodeError):
        return []


def member_dirs(root):
    out = []
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return out
    for n in names:
        d = os.path.join(root, n)
        if not os.path.isdir(d) or n.lower().startswith(SKIP_DIR_PREFIX) or n.lower() in SKIP_DIR_NAMES:
            continue
        if (os.path.exists(os.path.join(d, "member.json")) or glob.glob(os.path.join(d, "mm_meta_*.json"))
                or glob.glob(os.path.join(d, "signals_*.csv"))):
            out.append(d)
    return out


def find_root(arg):
    """팀 폴더 — 인자가 있으면 그 폴더만(없으면 실패 · 폴백 없음). 없으면 teamdata → config.teamShareDir → 이 파일 폴더 → 현재 폴더.
    returns (경로 또는 None, 설명)"""
    here = os.path.dirname(os.path.abspath(__file__))
    if arg:
        # cmd 는 "D:\team\" 처럼 끝 백슬래시가 따옴표를 이스케이프해 'D:\team"' 로 넘긴다 — 꼬리 따옴표만 정리
        a = os.path.abspath(str(arg).strip().rstrip('"').strip())
        if not os.path.isdir(a):
            return None, f"지정한 팀 폴더가 없습니다: {arg}"
        if not member_dirs(a):
            return None, f"지정한 폴더에 인별 폴더(member.json / mm_meta_*.json)가 없습니다: {a}"
        return a, "지정"
    cands = [os.path.join(here, "teamdata"), os.path.join(os.path.dirname(here), "teamdata")]
    for cfg_dir in (here, os.path.dirname(here)):
        c = _jload(os.path.join(cfg_dir, "config", "config.json"))
        if c and str(c.get("teamShareDir") or "").strip():
            cands.append(str(c["teamShareDir"]).strip())
    cands += [here, os.getcwd()]
    seen = set()
    for c in cands:
        c = os.path.abspath(c)
        if c in seen or not os.path.isdir(c):
            continue
        seen.add(c)
        if member_dirs(c):
            return c, "자동 탐색"
    return None, "인별 폴더(member.json 또는 mm_meta_*.json 이 있는 하위 폴더)를 찾지 못했습니다"


# ───────────────────────── 계산 ─────────────────────────
def analysis_time(meta, member, tag, meta_path, d0, d1, cal):
    """분석 시점(가용 절단용) — v3 mm_basis.future_days/today_fraction(정확값) → rehours_at → member.analyzed_at(같은 tag)
    → 파일 mtime(서버 저장 시각 ≥ 분석 시각). returns (datetime 또는 None, 출처)"""
    mb = meta.get("mm_basis") if isinstance(meta.get("mm_basis"), dict) else {}
    fd, tf = mb.get("future_days"), mb.get("today_fraction")
    if isinstance(fd, (int, float)) or isinstance(tf, (int, float)):
        # v3 는 기간이 분석 시각을 넘을 때만 future_days(미래 평일 수)·today_fraction(오늘 주간 창 경과 비율)을 남긴다.
        wds = [d0 + timedelta(days=i) for i in range((d1 - d0).days + 1) if not cal.off(d0 + timedelta(days=i))]
        n_f = int(fd or 0)
        if isinstance(tf, (int, float)):
            today = wds[-n_f - 1] if 0 <= n_f < len(wds) else None
            if today is not None:
                mins = DAY_WIN[0] + max(0.0, min(1.0, float(tf))) * (DAY_WIN[1] - DAY_WIN[0])
                return datetime(today.year, today.month, today.day) + timedelta(minutes=mins), "mm_basis"
        elif 0 < n_f <= len(wds):
            last = wds[-n_f - 1] if n_f < len(wds) else d0 - timedelta(days=1)
            return datetime(last.year, last.month, last.day, 23, 59), "mm_basis"
    t = _parse_dt(meta.get("rehours_at")) if meta else None
    if t:
        return t, "rehours_at"
    if member and str(member.get("tag") or "") == tag:
        t = _parse_dt(member.get("analyzed_at"))
        if t:
            return t, "analyzed_at"
    try:
        return datetime.fromtimestamp(os.path.getmtime(meta_path)), "파일 시각"
    except (OSError, TypeError):
        return None, ""


def recalc_period(sig, meta, d0, d1, cal, now, t_an, std=STD_DAY_H, has_sig=True, has_meta=True, version="unknown",
                  use_inferred=False):
    """(owner, tag) 하나의 일별·월별 재계산. returns dict(months={...}, days={...}, flags={...}).
    has_sig=False(signals 없음·못 읽음)면 A·B·C3 는 None, has_meta=False 면 D 는 None — 팀 합계에서 그 산식만 빠진다(0 으로 섞지 않는다)."""
    w = meta.get("weights") if isinstance(meta.get("weights"), dict) else {}

    def _w(k, dflt):
        try:
            v = float(w.get(k, dflt))
            return v if v > 0 else dflt
        except (TypeError, ValueError):
            return dflt
    w_meet = _w("회의", 2.0)
    rate_win = _w("작업창_분당", 0.05)
    rate_ide = _w("IDE_분당", 1.0 / 12)          # 두 판 기본 W['IDE_분당'] = 1/12
    w_manual = _w("수동기록_시간당", 2.0)
    cut = min(now, t_an) if t_an else now
    plain = [(t, s) for t, s, _wt in sig if s != "회의"]
    s_all = signal_spans(plain, d0, d1, cut)
    s_act = signal_spans([(t, s) for t, s in plain if s in ACTIVE_SRC], d0, d1, cut)
    meets, sampler_min, manual_min, gate_days, offsite_days = {}, {}, {}, set(), set()
    for t, s, wt in sig:
        if not (d0 <= t.date() <= d1) or t > cut + timedelta(minutes=FUTURE_SLACK_MIN):
            continue
        d = t.date()
        if s in GATE_SRC:
            gate_days.add(d)
        if s == "회의":
            dur_h = (wt / w_meet) if w_meet else 1.0
            m = t.hour * 60 + t.minute
            if dur_h >= std - 1e-9 and m <= 9 * 60:
                offsite_days.add(d)          # v3 종일 행사(회사 밖 근무)를 09:00 회의 8h×W 로 싣는다 — 판 차이 표식
            end = m + max(0.0, dur_h) * 60.0
            meets.setdefault(d, []).append((float(m), min(1440.0, end)))
            if end > 1440.0:                 # 자정을 넘는 회의 — 익일 조각(두 판 _meeting_spans 와 같은 이월) · 익일 게이트도 연다
                nd = d + timedelta(days=1)
                if d0 <= nd <= d1 and nd <= cut.date():
                    meets.setdefault(nd, []).append((0.0, min(1440.0, end - 1440.0)))
                    gate_days.add(nd)
        elif s in ("작업창", "작업창(IDE)"):
            rate = rate_ide if s.endswith("(IDE)") else rate_win
            sampler_min[d] = sampler_min.get(d, 0.0) + (wt / rate if rate else 0.0)
        elif s == "수동기록":
            manual_min[d] = manual_min.get(d, 0.0) + (wt / w_manual) * 60.0 if w_manual else 0.0
    dh_meta = {}
    for k, v in (meta.get("day_hours") or {}).items() if isinstance(meta.get("day_hours"), dict) else ():
        dd = _parse_date(k)
        if dd:
            try:
                dh_meta[dd] = float(v)
            except (TypeError, ValueError):
                pass
    mb = meta.get("mm_basis") if isinstance(meta.get("mm_basis"), dict) else {}
    inferred = {x for x in (_parse_date(v) for v in (mb.get("inferred_absence_dates") or []) if v) if x}
    days = {}
    d = d0
    while d <= d1:
        off = cal.off(d)
        active = d in gate_days
        sp = list(s_all.get(d, [])) + list(meets.get(d, []))
        spa = list(s_act.get(d, [])) + list(meets.get(d, []))
        b = max(_union_min(sp), sampler_min.get(d, 0.0), manual_min.get(d, 0.0)) / 60.0
        if off and not active:
            b = 0.0
        if not off:
            if active:
                outside = (_union_min(_clip(spa, 0, WORK_WIN[0])) + _union_min(_clip(spa, WORK_WIN[1], 1440))) / 60.0
                a_h, c_h = std, max(b, std + outside)
            else:
                a_h, c_h = 0.0, b
        else:
            a_h, c_h = b, b
        d_h = dh_meta.get(d, 0.0) if d <= cut.date() else 0.0     # 원값도 분석 시점까지만(재계산 분모와 같은 창)
        days[d] = {"A": a_h, "B": b, "C3": c_h, "D": d_h, "off": off, "active": active}
        d += timedelta(days=1)
    # 월별 — 가용은 통일 달력 × 분석 시점 절단, 부재는 mm_months[월].absent
    mmm = meta.get("mm_months") if isinstance(meta.get("mm_months"), dict) else {}
    today = cut.date()
    now_m = cut.hour * 60 + cut.minute + cut.second / 60.0
    today_frac = min(1.0, max(0.0, (now_m - DAY_WIN[0]) / float(DAY_WIN[1] - DAY_WIN[0])))
    months, future_wd = {}, 0
    for d, r in days.items():
        mk = d.strftime("%Y-%m")
        m = months.setdefault(mk, {"covered": 0.0, "workdays": cal.full_workdays(d.year, d.month), "absent": 0.0,
                                   "absent_raw": 0.0, "inferred": 0, "A": 0.0, "B": 0.0, "C3": 0.0, "D": 0.0,
                                   "noact_wd": 0, "noact_zero": 0, "offsite": 0, "days": 0, "wd_in_period": 0})
        m["days"] += 1
        if not r["off"]:
            m["wd_in_period"] += 1
            if d > today:
                future_wd += 1
            else:
                m["covered"] += today_frac if d == today else 1.0
                if d in inferred:
                    m["inferred"] += 1
            if not r["active"] and d <= today:
                m["noact_wd"] += 1
                if r["B"] <= 1e-9:
                    m["noact_zero"] += 1
        if d in offsite_days:
            m["offsite"] += 1
        for k in FORMULAS:
            m[k] += r[k]
    for mk, m in months.items():
        mi = mmm.get(mk) if isinstance(mmm.get(mk), dict) else {}
        try:
            absent = float(mi.get("absent") or 0.0)
        except (TypeError, ValueError):
            absent = 0.0
        m["absent_raw"] = absent
        m["absent_scaled"] = False
        if version == "lm20" and future_wd > 0 and m["wd_in_period"] > 0 and m["covered"] < m["wd_in_period"] - 1e-9:
            # LM20 의 부재는 기간 전체(분석 이후 연차 포함) 값 — 절단된 가용에서 통째로 빼면 과대. 절단 비율로 배분한다.
            absent = absent * m["covered"] / m["wd_in_period"]
            m["absent_scaled"] = True
        if use_inferred:
            absent += m["inferred"]
        m["absent"] = min(absent, m["covered"])
        m["avail_days"] = max(0.0, m["covered"] - m["absent"])
        m["avail_h"] = std * m["avail_days"]
        m["capacity_h"] = std * max(1, m["workdays"])
        for k in FORMULAS:
            if (k != "D" and not has_sig) or (k == "D" and not has_meta):
                m[k], m[k + "_pct"], m[k + "_mm"] = None, None, None
                continue
            m[k + "_pct"] = round(m[k] / m["avail_h"] * 100.0, 1) if m["avail_h"] > 0 else None
            m[k + "_mm"] = round(m[k] / m["capacity_h"], 3)
        if not has_sig:
            m["noact_wd"], m["noact_zero"] = None, None
        m["meta_load_pct"] = mi.get("load_pct") if mi else None
        m["meta_workdays"] = mi.get("workdays") if mi else None
    flags = {"future_wd": future_wd, "truncated": future_wd > 0, "offsite_days": len(offsite_days),
             "signals": len(sig), "active_days": len(gate_days) if has_sig else None,
             "inferred_days": sum(m["inferred"] for m in months.values()),
             "absent_scaled": any(m["absent_scaled"] for m in months.values()),
             "zero_avail_h": round(sum((m["C3"] or 0.0) for m in months.values() if m["avail_h"] <= 0), 1)}
    return {"months": months, "days": days, "flags": flags}


def load_team(root, cal, now, std, log, use_inferred=False):
    people = []
    for mdir in member_dirs(root):
        name = os.path.basename(mdir)
        member = _jload(os.path.join(mdir, "member.json")) or {}
        member_broken = os.path.exists(os.path.join(mdir, "member.json")) and not member
        # 인원 키는 폴더명 — 팀 서버가 <저장루트>\<owner>\ 로 저장하므로 폴더명이 인원이다(aggregate 와 같은 규칙).
        # member.json 의 owner 가 다르면(복사·개명) 비고에만 적는다 — 같은 owner 두 폴더가 한 사람으로 합쳐지지 않게.
        owner = name
        m_owner = str(member.get("owner") or "").strip()
        function = str(member.get("function") or "").strip()
        metas, sigs = {}, {}
        for p in sorted(glob.glob(os.path.join(mdir, "mm_meta_*.json"))):
            fm = FILE_RE.match(os.path.basename(p))
            if fm and fm.group(5):
                metas[fm.group(5)] = p
        for p in sorted(glob.glob(os.path.join(mdir, "signals_*.csv"))):
            fm = FILE_RE.match(os.path.basename(p))
            if fm and fm.group(4):
                sigs[fm.group(4)] = p
        tags = sorted(set(metas) | set(sigs))
        if not tags:
            log(f"  - {owner}: 기간 파일(mm_meta_/signals_)이 없어 건너뜀")
            continue
        for tag in tags:
            d0, d1 = _tag_dates(tag)
            meta = _jload(metas[tag]) if tag in metas else None
            ver = version_of(meta)
            if meta and isinstance(meta.get("period"), list) and len(meta["period"]) == 2:
                p0, p1 = _parse_date(meta["period"][0]), _parse_date(meta["period"][1])
                d0, d1 = p0 or d0, p1 or d1
            if not d0 or not d1 or d1 < d0:
                log(f"  - {owner}/{tag}: 기간을 읽을 수 없어 건너뜀")
                continue
            sr = read_signals(sigs[tag]) if tag in sigs else {"rows": [], "bad": 0, "err": "signals 파일 없음", "lost": False,
                                                              "unknown_src": False}
            has_sig = not sr["err"] and not sr["unknown_src"]
            if not has_sig and not meta:
                log(f"  - {owner}/{tag}: signals·mm_meta 둘 다 쓸 수 없어 건너뜀({sr['err'] or '출처 라벨 미인식'})")
                continue
            t_an, t_src = analysis_time(meta or {}, member, tag, metas.get(tag) or sigs.get(tag), d0, d1, cal)
            res = recalc_period(sr["rows"] if has_sig else [], meta or {}, d0, d1, cal, now, t_an, std,
                                has_sig=has_sig, has_meta=bool(meta), version=ver, use_inferred=use_inferred)
            res["flags"].update({"version": ver, "sig_bad": sr["bad"], "sig_err": sr["err"], "sig_lost": sr["lost"],
                                 "unknown_src": sr["unknown_src"], "has_sig": has_sig, "has_meta": bool(meta),
                                 "member_broken": member_broken, "m_owner": m_owner if m_owner and m_owner != name else "",
                                 "t_an": t_an.strftime("%Y-%m-%d %H:%M") if t_an else "", "t_src": t_src,
                                 "meta_load_pct": (meta or {}).get("load_pct")})
            rows = read_rows(pick_rows_file(mdir, tag))
            people.append({"owner": owner, "dir": name, "function": function, "tag": tag, "d0": d0, "d1": d1,
                           "res": res, "rows": rows, "idx": len(people)})
            fl = res["flags"]
            why = []
            if not has_sig:
                why.append(f"signals 못 씀({sr['err'] or '출처 라벨 미인식'}) → A·B·C3 빈칸")
            if not meta:
                why.append("mm_meta 없음 → D 빈칸")
            if fl["truncated"]:
                why.append(f"기간 미완(분석 {fl['t_an']}, 미래 평일 {fl['future_wd']})")
            log(f"  - {owner} [{tag}] 판={ver} 신호 {fl['signals']}건"
                + (f" 능동일 {fl['active_days']}" if fl["active_days"] is not None else "")
                + (" · " + " · ".join(why) if why else ""))
    return people


def choose_month_sources(people):
    """같은 사람의 여러 기간(tag)이 한 달을 겹쳐 덮으면 팀 합계·인별 월표·과제 배분은 가용일이 큰(같으면 늦게 분석한) 기간 하나만 쓴다."""
    best = {}
    for i, p in enumerate(people):
        for mk, m in p["res"]["months"].items():
            key = (p["owner"], mk)
            cand = (m["covered"], p["res"]["flags"].get("t_an") or "", i)
            if key not in best or cand > best[key][0]:
                best[key] = (cand, i)
    return {k: v[1] for k, v in best.items()}


def picked_months(p, pick):
    """이 기간 파일이 팀 합계를 대표하는 달만 — 과제 배분·CSV 가 겹친 달을 이중 계산하지 않게."""
    return {mk: m for mk, m in p["res"]["months"].items() if pick.get((p["owner"], mk)) == p["idx"]}


def person_notes(p):
    fl = p["res"]["flags"]
    notes = []
    if fl.get("m_owner"):
        notes.append(f"member.json owner '{fl['m_owner']}' (폴더명과 다름 — 폴더명으로 집계)")
    if fl.get("member_broken"):
        notes.append("member.json 손상(폴더명으로 집계 · 팀 통합보고서에는 빠질 수 있음)")
    if fl["truncated"]:
        notes.append(f"기간 미완 — 분석 {fl['t_an']}({fl['t_src']}) 이후 평일 {fl['future_wd']}일 제외")
    if fl.get("absent_scaled"):
        notes.append("LM20 부재는 기간 전체 값 — 절단 비율로 배분")
    if not fl["has_meta"]:
        notes.append("mm_meta 없음 — 부재 0 가정 · D 없음(신뢰도 낮음)")
    if not fl["has_sig"]:
        notes.append(f"signals 못 씀({fl.get('sig_err') or '출처 라벨 미인식 — 인코딩·형식 의심'}) — A·B·C3 계산 불가(D 만)")
    if fl.get("sig_lost"):
        notes.append("signals 행 유실 의심(따옴표 불균형 등 — 파일을 다시 올리세요)")
    if fl.get("sig_bad"):
        notes.append(f"신호 {fl['sig_bad']}행 시각 불량 제외")
    if fl.get("inferred_days"):
        notes.append(f"LM24 부재 추정 {fl['inferred_days']}일(원 판은 평일수에서 뺌 — 재계산 가용에는 남김)")
    if fl["offsite_days"]:
        notes.append(f"종일 행사(회사 밖 근무) {fl['offsite_days']}일 — LM24 만 8h 회의로 싣는 항목")
    if fl.get("zero_avail_h"):
        notes.append(f"가용 0 인 달의 투입 {fl['zero_avail_h']}h 는 비율·팀 합계에서 제외")
    return notes


# ───────────────────────── 출력 ─────────────────────────
def esc(s):
    return html.escape("" if s is None else str(s), quote=True)


def fmt(v, nd=1, suffix=""):
    if v is None:
        return "—"
    try:
        return f"{float(v):,.{nd}f}{suffix}"
    except (TypeError, ValueError):
        return esc(v)


def pct_cls(v):
    if v is None:
        return ""
    return "hi" if v >= 120 else ("ok" if v >= 70 else "lo")


VER_LABEL = {"v3": "LM24(v3)", "lm20": "LM20(추정)", "unknown": "판 불명"}


def person_sums(p, std):
    """기간 파일 하나의 합계 — 가용 0 인 달은 비율에서 제외(그 달의 투입은 zero_avail_h 로 비고에)."""
    ms = [m for m in p["res"]["months"].values() if m["avail_h"] > 0]
    avail_h = sum(m["avail_h"] for m in ms)
    sums = {k: (sum(m[k] for m in ms) if all(m[k] is not None for m in ms) and ms else None) for k in FORMULAS}
    pcts = {k: (sums[k] / avail_h * 100 if (avail_h > 0 and sums[k] is not None) else None) for k in FORMULAS}
    return avail_h, sums, pcts


def build_html(root, people, pick, now, std, extra_hol, out_csv_names, root_how):
    months_all = sorted({mk for p in people for mk in p["res"]["months"]})
    team = {mk: dict.fromkeys(FORMULAS, 0.0) | {k + "_av": 0.0 for k in FORMULAS} | {k + "_n": 0 for k in FORMULAS}
            | {"avail_h": 0.0, "n": 0} for mk in months_all}
    for (_owner, mk), idx in pick.items():
        m = people[idx]["res"]["months"][mk]
        if m["avail_h"] <= 0:
            continue                          # 가용 0 인 달 — 분모가 없으니 분자도 팀 합계에 넣지 않는다
        t = team[mk]
        for k in FORMULAS:
            if m[k] is not None:          # signals 없는 기간은 A·B·C3, mm_meta 없는 기간은 D 에서 빠진다(0 으로 섞지 않는다)
                t[k] += m[k]
                t[k + "_av"] += m["avail_h"]
                t[k + "_n"] += 1
        t["avail_h"] += m["avail_h"]
        t["n"] += 1

    def _tp(t, k):
        return t[k] / t[k + "_av"] * 100 if t[k + "_av"] else None

    h = []
    h.append("<!doctype html><html lang='ko'><head><meta charset='utf-8'><title>팀 로드율 재계산</title><style>"
             "body{font-family:'Malgun Gothic',Segoe UI,sans-serif;font-size:13px;color:#222;margin:18px;background:#fafafa}"
             "h1{font-size:20px;margin:0 0 6px}h2{font-size:15px;margin:22px 0 6px;border-left:4px solid #3a4a5c;padding-left:8px}"
             "table{border-collapse:collapse;background:#fff;margin:6px 0}th,td{border:1px solid #d8d8d8;padding:3px 7px;text-align:right;white-space:nowrap}"
             "th{background:#eef1f5;font-weight:600}td.l,th.l{text-align:left}td.hi{color:#a50034;font-weight:600}td.lo{color:#777}"
             ".dim{color:#666}.badge{display:inline-block;padding:0 6px;border-radius:9px;font-size:11px;background:#e8eef7;color:#2b4c7e;margin-left:4px}"
             ".badge.lm20{background:#f4ecd8;color:#7a5a12}.badge.unknown{background:#eee;color:#666}.warn{color:#a50034}"
             ".box{background:#fff;border:1px solid #ddd;padding:8px 12px;margin:6px 0}.mono{font-family:Consolas,monospace}"
             "details{margin:4px 0}summary{cursor:pointer;color:#2b4c7e}</style></head><body>")
    h.append(f"<h1>팀 로드율 재계산 <span class='dim' style='font-size:12px'>{esc(VERSION)} · {esc(now.strftime('%Y-%m-%d %H:%M'))}</span></h1>")
    h.append(f"<div class='dim'>팀 폴더({esc(root_how)}): <span class='mono'>{esc(root)}</span> · 인원 {len({p['owner'] for p in people})}명 · "
             f"기간 파일 {len(people)}개 · 표준일 {std:g}h · 표준 창 09~18 · 추가 공휴일 {esc(', '.join(x.isoformat() for x in sorted(extra_hol)) or '없음')}</div>")
    h.append("<div class='box'><b>이 보고서는 무엇인가</b> — 팀에 올라온 두 파일(signals_&lt;기간&gt;.csv · mm_meta_&lt;기간&gt;.json)만으로 "
             "모든 인원을 <b>하나의 산식·하나의 달력</b>으로 다시 잰 값입니다. 판(LM20 / LM24)마다 다르게 계산된 원값(D)을 그대로 비교하면 "
             "같은 사람이 판에 따라 수십 p 갈립니다(실측). 기존 team_report.html 등은 건드리지 않았습니다.<br>"
             f"<b>C3(권장)</b> = 능동 흔적이 있는 평일은 {std:g}h 를 바닥으로, 09~18시 밖의 능동 세션만 초과로 더함 · 능동 없는 평일은 근거 구간(B, 수동 세션은 하루 60분까지) 그대로 · 주말·공휴일은 능동 있는 날만. "
             f"<b>A</b> = 능동 평일 {std:g}h(출근일 하한) + 주말·공휴일 활동일은 B. <b>B</b> = max(신호 세션 ∪ 회의 구간, 샘플러 활동분, 수동기록 시간). <b>D</b> = 그 판이 계산한 원값(비교 기준선).<br>"
             f"<b>가용</b> = 통일 달력 평일수(분석 시점 이후 제외) − mm_meta 의 월별 부재 일수 · <b>로드율</b> = 투입시간 ÷ ({std:g}h × 가용일). 가용 0 인 달은 비율·팀 합계에서 제외.<br>"
             "<span class='warn'>한계</span>: PC 가동·샘플러 구간·연차 일자·회의 수락 여부·표본화 전 파일 시각은 팀에 올라오지 않아 어느 산식도 복원하지 못합니다. "
             "능동 흔적이 없는 평일은 8h 가 붙지 않아 C3 = 근거 구간뿐입니다 — '무흔적 평일(−부재)' 열을 함께 보세요.</div>")
    # 1. 팀 월별 합계
    h.append("<h2>1. 팀 합계 (월별) — 인원별로 그 달을 덮는 기간 파일 하나씩</h2><table><tr><th class='l'>월</th><th>인원<br><span class='dim'>(C3/D)</span></th><th>가용(h)<br><span class='dim'>전원</span></th>"
             "<th>C3(h)</th><th>C3 로드율</th><th>A(h)</th><th>A 로드율</th><th>B(h)</th><th>B 로드율</th><th>D 원값(h)</th><th>D 로드율</th></tr>")
    tot = dict.fromkeys(FORMULAS, 0.0) | {k + "_av": 0.0 for k in FORMULAS} | {"avail_h": 0.0}

    def _cells(t):
        return "".join(f"<td>{fmt(t[k])}</td><td class='{pct_cls(_tp(t, k))}' title='{k} {fmt(t[k])}h ÷ 가용 {fmt(t[k + '_av'])}h ({k} 값이 있는 인원만)'>"
                       f"{fmt(_tp(t, k), 1, '%')}</td>" for k in FORMULAS)
    for mk in months_all:
        t = team[mk]
        for k in tot:
            tot[k] += t[k]
        h.append(f"<tr><td class='l'>{esc(mk)}</td><td>{t['C3_n']}/{t['D_n']}</td><td>{fmt(t['avail_h'])}</td>{_cells(t)}</tr>")
    h.append(f"<tr><th class='l'>합계</th><th></th><th>{fmt(tot['avail_h'])}</th>{_cells(tot)}</tr></table>"
             "<div class='dim'>각 로드율의 분모는 그 산식 값이 있는 인원의 가용만 더한 것입니다(셀에 마우스를 올리면 분자·분모) — signals 를 못 쓴 기간은 C3·A·B 에서, "
             "mm_meta 가 없는 기간은 D 에서 빠지므로 산식마다 분모 인원이 다를 수 있습니다. '가용(h) 전원' 은 전원 합계라 C3 로드율 검산에는 쓰지 마세요.</div>")
    # 2. 인별 요약(기간 파일 단위)
    h.append("<h2>2. 인별 요약 (기간 파일 단위)</h2><table><tr><th class='l'>이름</th><th class='l'>기능</th><th class='l'>기간</th><th class='l'>판</th>"
             "<th>신호</th><th>능동일</th><th>무흔적 평일<br><span class='dim'>(−부재)</span></th><th>부재(일)</th><th>가용(일)</th>"
             "<th>C3(h)</th><th>C3 로드율</th><th>A 로드율</th><th>B 로드율</th><th>D 로드율<br><span class='dim'>(재계산 분모)</span></th>"
             "<th>원 판 로드율<br><span class='dim'>(mm_meta)</span></th><th>C3−D(p)</th><th class='l'>비고</th></tr>")
    for p in sorted(people, key=lambda x: (x["owner"], x["tag"])):
        ms = p["res"]["months"]
        fl = p["res"]["flags"]
        avail_h, sums, pcts = person_sums(p, std)
        noact = sum(m["noact_wd"] or 0 for m in ms.values()) if fl["has_sig"] else None
        absent = sum(m["absent"] for m in ms.values())
        inferred = fl.get("inferred_days") or 0
        ver = fl["version"]
        diff = (pcts["C3"] - pcts["D"]) if (pcts["C3"] is not None and pcts["D"] is not None) else None
        noact_cell = (f"{noact} <span class='dim'>({max(0, noact - absent - inferred):.0f})</span>" if noact is not None else "—")
        h.append(f"<tr><td class='l'><b>{esc(p['owner'])}</b></td><td class='l'>{esc(p['function'])}</td>"
                 f"<td class='l'>{esc(p['d0'].isoformat())} ~ {esc(p['d1'].isoformat())}</td>"
                 f"<td class='l'><span class='badge {esc(ver)}'>{esc(VER_LABEL.get(ver, ver))}</span></td>"
                 f"<td>{fl['signals'] if fl['has_sig'] else '—'}</td><td>{fmt(fl['active_days'], 0)}</td><td>{noact_cell}</td>"
                 f"<td>{fmt(absent)}</td><td>{fmt(avail_h / std if std else 0)}</td>"
                 f"<td>{fmt(sums['C3'])}</td><td class='{pct_cls(pcts['C3'])}'><b>{fmt(pcts['C3'], 1, '%')}</b></td>"
                 f"<td>{fmt(pcts['A'], 1, '%')}</td><td>{fmt(pcts['B'], 1, '%')}</td><td>{fmt(pcts['D'], 1, '%')}</td>"
                 f"<td>{fmt(fl.get('meta_load_pct'), 1, '%')}</td><td>{fmt(diff, 1)}</td><td class='l dim'>{esc(' · '.join(person_notes(p)))}</td></tr>")
    h.append("</table><div class='dim'>"
             "<b>C3−D</b> 가 크게 양수면 원 판이 PC 없이 세션만 재었을 가능성(흔적이 적은 근무 유형)입니다. 음수면 (a) 원 판이 수동 신호 다리(LM20)·PC 가장자리로 더 잡았거나 "
             "(b) C3 가 보지 못하는 PC 가동·샘플러 구간을 원 판이 실측한 경우입니다 — C3 는 합성 참값 대비 −3~−16p 아래로 재는 하한 성격이므로 −15p 안의 음수는 판 차이로 단정하지 마세요.<br>"
             "<b>'D 로드율(재계산 분모)' 과 '원 판 로드율'</b> 의 차이는 달력(공휴일표)·분석 시점 절단·LM24 부재 추정(A31 — 원 판은 그 날을 평일수에서 빼지만 재계산은 가용에 남김, 비고에 일수)·원 판의 반올림(MM·가용 MM 소수 3자리) 때문입니다.</div>")
    # 3. 인별 월별
    h.append("<h2>3. 인별 월별 (C3 기본 · 괄호 안 A / D)</h2><table><tr><th class='l'>이름</th>"
             + "".join(f"<th>{esc(mk)}</th>" for mk in months_all) + "<th>합계</th></tr>")
    for o in sorted({p["owner"] for p in people}):
        cells, s_c3, s_av = [], 0.0, 0.0
        for mk in months_all:
            idx = pick.get((o, mk))
            if idx is None:
                cells.append("<td class='dim'>—</td>")
                continue
            m = people[idx]["res"]["months"][mk]
            if m["avail_h"] <= 0:
                cells.append(f"<td class='dim' title='가용 0일 — 비율 없음 (C3 {fmt(m['C3'])}h)'>—</td>")
                continue
            if m["C3"] is None:
                cells.append(f"<td class='dim' title='signals 없음 — D 만'>D {fmt(m['D_pct'], 0, '%')}</td>")
                continue
            s_c3 += m["C3"]
            s_av += m["avail_h"]
            cells.append(f"<td class='{pct_cls(m['C3_pct'])}' title='C3 {fmt(m['C3'])}h / 가용 {fmt(m['avail_days'])}일 · 부재 {fmt(m['absent'])} · 무흔적 평일 {m['noact_wd']} · 기간 {esc(people[idx]['tag'])}'>"
                         f"<b>{fmt(m['C3_pct'], 0, '%')}</b><br><span class='dim'>({fmt(m['A_pct'], 0)} / {fmt(m['D_pct'], 0)})</span></td>")
        tp = s_c3 / s_av * 100 if s_av > 0 else None
        h.append(f"<tr><td class='l'><b>{esc(o)}</b></td>{''.join(cells)}<td class='{pct_cls(tp)}'><b>{fmt(tp, 1, '%')}</b></td></tr>")
    h.append("</table>")
    # 4. 과제 배분(share × 재계산 MM) — pick 된 달만
    h.append("<h2>4. 과제 배분 — mm_rows 의 비율(share)에 재계산 투입 MM(C3)을 다시 곱한 값</h2>"
             "<div class='dim'>원 판의 mm 절대값은 판마다 다른 총 MM 을 배분한 값이라 쓰지 않고, 비율만 가져와 재정규화해 C3 총 MM 에 곱합니다. "
             "정제본(_refined)이 원본보다 새로우면 정제본. 같은 사람의 기간 파일이 겹치면 팀 합계를 대표하는 달만 넣습니다.</div>")
    for p in sorted(people, key=lambda x: (x["owner"], x["tag"])):
        rows = p["rows"]
        ms = picked_months(p, pick)
        if not rows or not ms:
            continue
        tot_mm_c3 = sum(m["C3_mm"] or 0.0 for m in ms.values()) if p["res"]["flags"]["has_sig"] else None
        tot_mm_d = sum(m["D_mm"] or 0.0 for m in ms.values()) if p["res"]["flags"]["has_meta"] else None
        shares = []
        for r in rows:
            try:
                sh = float(r.get("share") or 0)
            except ValueError:
                sh = 0.0
            if sh > 0:
                shares.append((sh, r))
        ssum = sum(s for s, _ in shares) or 1.0
        skipped = len(p["res"]["months"]) - len(ms)
        h.append(f"<details><summary><b>{esc(p['owner'])}</b> [{esc(p['tag'])}] — 총 MM C3 {fmt(tot_mm_c3, 2)} (원값 {fmt(tot_mm_d, 2)}) · 행 {len(shares)}"
                 + (f" · 다른 기간 파일이 대표하는 달 {skipped}개 제외" if skipped else "") + "</summary>"
                 "<table><tr><th class='l'>Level 1</th><th class='l'>Level 2</th><th class='l'>Level 3</th><th class='l'>이름</th><th>비율</th><th>MM(C3)</th><th>MM(원값)</th><th>활동일수</th></tr>")
        for sh, r in sorted(shares, key=lambda x: -x[0]):
            h.append(f"<tr><td class='l'>{esc(r.get('Level 1'))}</td><td class='l'>{esc(r.get('Level 2'))}</td><td class='l'>{esc(r.get('Level 3'))}</td>"
                     f"<td class='l'>{esc(r.get('이름'))}</td><td>{fmt(sh / ssum * 100, 1, '%')}</td>"
                     f"<td>{fmt(sh / ssum * tot_mm_c3 if tot_mm_c3 is not None else None, 3)}</td>"
                     f"<td>{fmt(sh / ssum * tot_mm_d if tot_mm_d is not None else None, 3)}</td><td>{esc(r.get('활동일수'))}</td></tr>")
        h.append("</table></details>")
    h.append("<h2>5. 산식·재료 메모</h2><div class='box dim'>"
             "· 세션 규칙은 LM24 v3 core.extract._signal_spans 와 같다(능동끼리만 45분 다리 · 수동은 다리 없음·하루 60분 상한 · 야간 수동 제외 · 회의 신호는 세션 0, 회의 길이는 weight ÷ weights['회의']로 복원, 자정 넘김은 익일로 이월).<br>"
             "· 샘플러(작업창) 활동분 = weight ÷ 분당 가중치, 수동기록 시간 = weight ÷ 시간당 가중치 — 구간 위치를 몰라 B 의 하한으로만 쓴다(LM20 파일은 샘플 간격 60초 가정).<br>"
             "· 달력: 주말 + 양력 고정 공휴일 + 내장 연도표(2025~2027 설·추석·대체공휴일·선거일) + --holidays. 두 판의 원 분모(workdays)는 쓰지 않는다(LM20 은 내장 연도표가 없어 같은 달을 하루 더 센다).<br>"
             "· 분석 시점 절단: 기간 종료 전에 올린 자료는 분석 시점 이후 평일을 가용에서 뺀다(LM24 A34 규칙을 두 판에 같이 적용 — LM20 원값은 미래 평일을 가용에 넣어 같은 자료를 훨씬 낮게 낸다). "
             "LM20 의 부재는 기간 전체 값이라 절단 비율로 배분한다(비고).<br>"
             "· 부재는 월 합계만 있어 일자별로 차감하지 못한다 — 연차일에 능동 신호(외부 발신 등)가 있으면 그날 8h 가 붙는다(최대 그 달 부재 일수만큼, 대개 ≤1일의 위쪽 오차).<br>"
             f"· 같은 데이터는 CSV 로도 저장했다: {esc(' · '.join(out_csv_names))}</div></body></html>")
    return "".join(h)


def _r1(v):
    return round(v, 1) if v is not None else ""


def write_csvs(base, people, pick):
    months_csv = base + "_월별.csv"
    with open(months_csv, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["이름", "기능", "기간", "판", "월", "달력평일", "가용일(절단·부재 전)", "부재일", "부재일(원값)", "추정부재일(LM24)", "가용일",
                    "무흔적평일", "무흔적(B=0)", "종일행사일", "C3_h", "A_h", "B_h", "D_h", "C3_pct", "A_pct", "B_pct", "D_pct",
                    "원판_load_pct", "원판_workdays", "C3_MM", "D_MM", "팀합계_사용", "비고"])
        for p in sorted(people, key=lambda x: (x["owner"], x["tag"])):
            notes = " · ".join(person_notes(p))
            for mk, m in sorted(p["res"]["months"].items()):
                used = "Y" if (pick.get((p["owner"], mk)) == p["idx"] and m["avail_h"] > 0) else ""
                w.writerow([p["owner"], p["function"], f"{p['d0']}~{p['d1']}", VER_LABEL.get(p["res"]["flags"]["version"], ""), mk,
                            m["workdays"], round(m["covered"], 2), round(m["absent"], 2), round(m["absent_raw"], 2), m["inferred"],
                            round(m["avail_days"], 2), "" if m["noact_wd"] is None else m["noact_wd"],
                            "" if m["noact_zero"] is None else m["noact_zero"], m["offsite"],
                            _r1(m["C3"]), _r1(m["A"]), _r1(m["B"]), _r1(m["D"]),
                            "" if m["C3_pct"] is None else m["C3_pct"], "" if m["A_pct"] is None else m["A_pct"],
                            "" if m["B_pct"] is None else m["B_pct"], "" if m["D_pct"] is None else m["D_pct"],
                            m["meta_load_pct"], m["meta_workdays"], "" if m["C3_mm"] is None else m["C3_mm"],
                            "" if m["D_mm"] is None else m["D_mm"], used, notes])
    tasks_csv = base + "_과제.csv"
    with open(tasks_csv, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["이름", "기간", "판", "Level 1", "Level 2", "Level 3", "과제/업무", "비율", "MM_C3", "MM_원값", "활동일수", "대표하는 달"])
        for p in sorted(people, key=lambda x: (x["owner"], x["tag"])):
            ms = picked_months(p, pick)
            if not ms:
                continue
            tot_c3 = sum(m["C3_mm"] or 0.0 for m in ms.values()) if p["res"]["flags"]["has_sig"] else None
            tot_d = sum(m["D_mm"] or 0.0 for m in ms.values()) if p["res"]["flags"]["has_meta"] else None
            shares = []
            for r in p["rows"]:
                try:
                    sh = float(r.get("share") or 0)
                except ValueError:
                    sh = 0.0
                if sh > 0:
                    shares.append((sh, r))
            ssum = sum(s for s, _ in shares) or 1.0
            for sh, r in sorted(shares, key=lambda x: -x[0]):
                w.writerow([p["owner"], p["tag"], VER_LABEL.get(p["res"]["flags"]["version"], ""), r.get("Level 1", ""), r.get("Level 2", ""),
                            r.get("Level 3", ""), r.get("이름", ""), round(sh / ssum, 4),
                            round(sh / ssum * tot_c3, 3) if tot_c3 is not None else "",
                            round(sh / ssum * tot_d, 3) if tot_d is not None else "", r.get("활동일수", ""), " ".join(sorted(ms))])
    return [os.path.basename(months_csv), os.path.basename(tasks_csv)]


def _writable(d):
    try:
        os.makedirs(d, exist_ok=True)
        probe = os.path.join(d, f".{OUT_PREFIX}_write_test_{os.getpid()}")
        with open(probe, "w") as f:
            f.write("x")
        os.remove(probe)
        return True
    except OSError:
        return False


def reserve_base(out_dir, stamp):
    """산출 파일 이름을 선점한다(같은 초에 두 번 실행돼도 서로 덮지 않게) — 빈 html 을 'x' 모드로 만든다."""
    base = os.path.join(out_dir, f"{OUT_PREFIX}_{stamp}")
    b, n = base, 1
    while True:
        try:
            with open(b + ".html", "x", encoding="utf-8") as f:
                f.write("")
            return b
        except FileExistsError:
            n += 1
            b = f"{base}_{n}"
            if n > 99:
                raise


def main(argv=None):
    ap = argparse.ArgumentParser(description="팀취합본만으로 로드율 재계산(판 무관) — 기존 보고서는 두고 새 파일만 만든다")
    ap.add_argument("root", nargs="?", help="팀 폴더(인별 폴더가 있는 곳). 생략 시 자동 탐색 · 지정하면 그 폴더만(폴백 없음)")
    ap.add_argument("--out", help="산출 폴더(기본: 팀 폴더 → 쓸 수 없으면 이 파일 폴더 → 임시 폴더)")
    ap.add_argument("--now", help="기준 시각 'YYYY-MM-DD HH:MM'(기본: 지금) — 미래 평일 절단·미래 신호 폐기 기준")
    ap.add_argument("--holidays", default="", help="추가 공휴일(쉼표 구분 YYYY-MM-DD) — 내장 연도표에 없는 임시 휴일")
    ap.add_argument("--std", type=float, default=STD_DAY_H, help="표준일 시간(기본 8)")
    ap.add_argument("--inferred", action="store_true", help="LM24 의 부재 '추정' 일자(A31)도 가용에서 뺀다(기본: 표시만)")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)

    def log(s):
        if not a.quiet:
            print(s)
    if not a.std or a.std <= 0:
        print("[!] --std 는 0 보다 커야 합니다")
        return 2
    now = _parse_dt(a.now) if a.now else None
    if a.now and not now:
        print(f"[!] --now 형식 오류: {a.now}")
        return 2
    now = now or datetime.now()
    extra_hol = set()
    for x in (a.holidays or "").split(","):
        dd = _parse_date(x.strip()) if x.strip() else None
        if dd:
            extra_hol.add(dd)
    cal = Calendar(extra_hol)
    root, how = find_root(a.root)
    if not root:
        print(f"[!] {how}")
        print("    팀 공유폴더(또는 teamdata) 경로를 인자로 주세요:  python team_recalc.py <팀 폴더>   (경로 끝의 \\ 는 빼세요)")
        return 1
    log(f"[재계산] 팀 폴더({how}): {root}")
    people = load_team(root, cal, now, a.std, log, use_inferred=a.inferred)
    if not people:
        print("[!] 재계산할 기간 파일이 없습니다.")
        return 1
    pick = choose_month_sources(people)
    out_dir = None
    for cand in ([os.path.abspath(a.out)] if a.out else []) + [root, os.path.dirname(os.path.abspath(__file__)), tempfile.gettempdir()]:
        if _writable(cand):
            out_dir = cand
            break
        log(f"[재계산] 산출 폴더에 쓸 수 없습니다(읽기 전용?): {cand}")
    if not out_dir:
        print("[!] 산출 폴더를 어디에도 만들 수 없습니다 — --out 으로 쓸 수 있는 폴더를 주세요")
        return 1
    stamp = now.strftime("%Y%m%d_%H%M%S") if not a.now else time.strftime("%Y%m%d_%H%M%S")
    try:
        base = reserve_base(out_dir, stamp)
        csv_names = write_csvs(base, people, pick)
        page = build_html(root, people, pick, now, a.std, extra_hol, csv_names, how)
        with open(base + ".html", "w", encoding="utf-8") as f:
            f.write(page)
    except OSError as e:
        print(f"[!] 산출 파일을 쓸 수 없습니다: {type(e).__name__}: {e} — --out 으로 다른 폴더를 주세요")
        return 1
    log(f"[재계산] 새 보고서 → {base}.html")
    for n in csv_names:
        log(f"[재계산] CSV → {os.path.join(out_dir, n)}")
    log("[재계산] 기존 team_report.html 등은 변경하지 않았습니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
