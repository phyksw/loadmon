# -*- coding: utf-8 -*-
r"""collect\owa_parse.py — Outlook 웹(OWA) 화면 판정용 순수 함수(LM28 WP2). 브라우저·파일·시계를 모른다(오늘 날짜는 인자).

  · parse_list_date(text, today) — 목록 칸의 날짜·시각 글('오후 3:12'·'화 10:05'·'어제'·'2026-03-05'·'Mar 5') →
    (date, (시, 분) | None). 글 전체가 날짜·시각뿐일 때만 읽는다 — 제목 속 '월요일 회의'·'3/5 보고'를 날짜로 읽지 않게(F-04).
    list_when(조각들, today) 는 한 머리 글의 날짜 조각과 '시각만' 조각을 합친다('Thu 3/5/2026, 3:12 PM').
  · slice_verdict(item_dates, s, e, empty_marker, scrolled_contiguous, reached_end) → (판정, D) — 조각을 '읽음'으로 적어도
    되는지(F-03). 판정: ok · list_verified(D) · filter_ineffective · empty_verified · unverified.
  · verdict_ranges(판정, D, s, e) → [(from, to, st)] — 원장 상태어(ok · zero_ok · partial · unverified).
  · week_header_range(text) — 주 보기 머리('2026년 9월 14일–20일'·'Sep 28 – Oct 4, 2026') → (시작, 끝) | None(F-05).
  · merge_slices(old, new, verified, kind) — 이번에 검증한 날의 옛 행만 새 행으로 바꾸고 나머지 옛 행은 그대로(W1-04).
  · iso_local(s) — <time datetime> ISO(Z·오프셋) → 이 PC 로컬 (date, (시, 분))(C-35).
  · apply_ranges(day_st, rngs, cap) · ranges_of(day_st, axis) — {날짜: st} 에 판정 반영(나은 상태만 · 오늘은 partial) →
    LMSTATUS ranges 조각(이어진 같은 상태끼리).
"""
import re
from datetime import date, datetime, timedelta, timezone

DAY = timedelta(days=1)

# ── 낱말·정규식 ───────────────────────────────────────────────────────────────
DESIG = r"(?:오전|오후|AM|PM|am|pm|a\.m\.|p\.m\.|A\.M\.|P\.M\.|午前|午後|上午|下午)"
AM_WORDS = ("오전", "AM", "A.M.", "午前", "上午")
PM_WORDS = ("오후", "PM", "P.M.", "午後", "下午")
RE_TIME = re.compile(r"(?:(" + DESIG + r")\s*)?(?<!\d)(\d{1,2})[:.](\d{2})(?!\d)(?:\s*(" + DESIG + r"))?")
RE_DESIG = re.compile(DESIG)
RE_HM_WORD = re.compile(r"(?<!\d)(\d{1,2})\s*[시時时]\s*(\d{1,2})\s*[분分]")
MON_EN = {m: i + 1 for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov",
                                          "dec"))}
_MON = r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?"
RE_YMD = re.compile(r"(\d{4})\s*([년.\-/])\s*(\d{1,2})\s*([월.\-/])\s*(\d{1,2})\s*일?\.?")
RE_MDY = re.compile(r"(?<!\d)(\d{1,2})\s*[/.\-]\s*(\d{1,2})\s*[/.\-]\s*(\d{4})(?!\d)")
RE_MONEN = re.compile(r"\b" + _MON + r"\s+(\d{1,2})(?:st|nd|rd|th)?,?\s*(\d{4})?", re.I)
RE_DMONEN = re.compile(r"(?<!\d)(\d{1,2})\s+" + _MON + r",?\s*(\d{4})?", re.I)
RE_MD_KO = re.compile(r"(\d{1,2})\s*[월月]\s*(\d{1,2})\s*[일日]")
RE_MD = re.compile(r"(?<![\d/.\-])(\d{1,2})\s*[/.\-]\s*(\d{1,2})\.?(?![\d/.\-])")      # 약한 표기 — 날짜·시각뿐인 글에서만
TODAY_W = ("오늘", "today", "今日", "今天")
YDAY_W = ("어제", "yesterday", "昨日", "昨天")
# 요일 → 월=0. 한 글자('화')는 '나머지가 이 낱말뿐'일 때만 쓴다(LM27 Get-OutlookWeb.py:234-240 이식 — '8월'과 섞이지 않는다)
WEEKDAY_W = (("월요일", "monday", "mon", "월"), ("화요일", "tuesday", "tue", "화"), ("수요일", "wednesday", "wed", "수"),
             ("목요일", "thursday", "thu", "목"), ("금요일", "friday", "fri", "금"), ("토요일", "saturday", "sat", "토"),
             ("일요일", "sunday", "sun", "일"))
WDAY = {w: i for i, ws in enumerate(WEEKDAY_W) for w in ws}
RE_WEEKDAY_ANY = re.compile(r"(?i)\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|mon|tue|tues|wed|thu|"
                            r"thur|thurs|fri|sat|sun)\b\.?|[월화수목금토일]요일|(?<![가-힣])[월화수목금토일](?![가-힣])")
_PUNCT_RX = re.compile(r"[\s,，.·|:：()\[\]~\-–—/]+")
RE_ISO = re.compile(r"(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?\s*(Z|[+-]\d{2}:?\d{2})?")


def _safe(y, mo, dd):
    try:
        return date(int(y), int(mo), int(dd))
    except (TypeError, ValueError):
        return None


def hm_words(s):
    """'오후 3시 12분' 처럼 콜론 없는 표기 → '오후 3:12'."""
    return RE_HM_WORD.sub(lambda m: f"{m.group(1)}:{int(m.group(2)):02d}", str(s or ""))


def _strip_dates(t):
    for rx in (RE_YMD, RE_MDY, RE_MONEN, RE_DMONEN, RE_MD_KO):
        t = rx.sub(" ", t)
    return t


def find_times(text):
    """글 속 시각 전부 → [(시, 분)]. 날짜 조각을 먼저 지운다('2026.03.05' 의 '03.05' 가 3시 5분이 되지 않게)."""
    out = []
    for m in RE_TIME.finditer(_strip_dates(hm_words(text))):
        h, mm = int(m.group(2)), int(m.group(3))
        ap = (m.group(1) or m.group(4) or "").upper()
        if ap in PM_WORDS and h < 12:
            h += 12
        if ap in AM_WORDS and h == 12:
            h = 0
        if h <= 23 and mm <= 59:
            out.append((h, mm))
    return out


def is_datetime_text(text):
    """글 전체가 날짜·시각·요일·상대 날짜 낱말뿐인가(구두점·공백 제외)."""
    t = str(text or "").strip()
    if not t:
        return False
    t = _strip_dates(hm_words(t))
    t = RE_TIME.sub(" ", t)
    t = RE_MD.sub(" ", t)
    t = RE_DESIG.sub(" ", t)
    t = RE_WEEKDAY_ANY.sub(" ", t).lower()
    for w in TODAY_W + YDAY_W:
        t = t.replace(w, " ")
    return _PUNCT_RX.sub("", t) == ""


def _no_year(mo, dd, today, d0=None, d1=None):
    """연도 없는 월·일 — 힌트 기간(d0~d1)에 드는 해, 없으면 오늘 이전이 되는 가장 가까운 해(목록은 미래 날짜가 없다)."""
    if d0 and d1:
        for y in sorted({d0.year, d1.year}):
            d = _safe(y, mo, dd)
            if d and d0 <= d <= d1:
                return d
    d = _safe(today.year, mo, dd)
    if d and d > today:
        d = _safe(today.year - 1, mo, dd)
    return d


def _abs_date(t, today, d0=None, d1=None, weak=False):
    """강한 표기(연월일·월/일/연·영문 월·'n월 n일') → date. weak 면 'M/D'·'M-D' 도(날짜·시각뿐인 글에서만)."""
    for m in RE_YMD.finditer(t):
        y, s1, mo, s2, dd = m.groups()
        if (s1 == "년" and s2 == "월") or (s1 == s2 and s1 != "년"):
            d = _safe(y, mo, dd)
            if d:
                return d
    m = RE_MDY.search(t)
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        cands = [d for d in (_safe(y, a, b), _safe(y, b, a)) if d]
        inr = [d for d in cands if d0 and d1 and d0 <= d <= d1]
        if inr or cands:
            return (inr or cands)[0]
    m = RE_MONEN.search(t)
    if m:
        mo, dd = MON_EN[m.group(1)[:3].lower()], int(m.group(2))
        return _safe(m.group(3), mo, dd) if m.group(3) else _no_year(mo, dd, today, d0, d1)
    m = RE_DMONEN.search(t)
    if m:
        mo, dd = MON_EN[m.group(2)[:3].lower()], int(m.group(1))
        return _safe(m.group(3), mo, dd) if m.group(3) else _no_year(mo, dd, today, d0, d1)
    m = RE_MD_KO.search(t)
    if m:
        return _no_year(int(m.group(1)), int(m.group(2)), today, d0, d1)
    if weak:
        m = RE_MD.search(RE_TIME.sub(" ", t))
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            cands = [d for d in (_no_year(a, b, today, d0, d1), _no_year(b, a, today, d0, d1)) if d]
            inr = [d for d in cands if d0 and d1 and d0 <= d <= d1]
            if inr or cands:
                return (inr or cands)[0]
    return None


def _parse(text, today, d0=None, d1=None):
    """parse_list_date 본체 → (date, hm, 시각만인가) | None."""
    t = hm_words(str(text or "")).strip()
    if not t or today is None or not is_datetime_text(t):
        return None
    ts = find_times(t)
    hm = ts[0] if ts else None
    d = _abs_date(t, today, d0, d1, weak=True)
    if d:
        return d, hm, False
    rest = _PUNCT_RX.sub(" ", RE_DESIG.sub(" ", RE_TIME.sub(" ", t))).strip().lower()
    if not rest:
        return (today, hm, True) if hm else None
    if rest in TODAY_W:
        return today, hm, False
    if rest in YDAY_W:
        return today - DAY, hm, False
    wd = WDAY.get(rest.rstrip("."))
    if wd is not None:
        back = (today.weekday() - wd) % 7
        return today - timedelta(days=back or 7), hm, False
    return None


def parse_list_date(text, today, d0=None, d1=None):
    """목록 칸 글 → (date, (시, 분) | None) | None. 글 전체가 날짜·시각뿐일 때만(그 밖은 None).
    '오후 3:12'(시각만 = 오늘) · '화 10:05'·'Tue 3:12 PM'(요일 = 지난 그 요일, 오늘과 같은 요일이면 7일 전) · '어제' ·
    '2026-03-05'·'2026년 3월 5일 (목) 오후 3:12' · 'Mar 5'·'5 Mar 2026' · '3/5'(연도는 오늘 이전이 되게)."""
    r = _parse(text, today, d0, d1)
    return (r[0], r[1]) if r else None


def list_when(frags, today, d0=None, d1=None):
    """한 머리 글의 조각들(frags_of) → (date, hm | None) | None. 날짜·시각뿐인 조각만 본다.
    날짜 조각에 시각이 있으면 그것, 날짜 조각과 '시각만' 조각이 따로 있으면('Thu 3/5/2026, 3:12 PM') 합치고,
    시각만 있으면 오늘(목록은 오늘 메일에 시각만 보인다)."""
    dated, tonly = [], []
    for f in frags or ():
        r = _parse(f, today, d0, d1)
        if not r:
            continue
        if r[2]:
            tonly.append(r[1])
        else:
            dated.append(r)
    for d, hm, _ in dated:
        if hm:
            return d, hm
    if dated:
        return dated[0][0], (tonly[0] if tonly else None)
    if tonly:
        return today, tonly[0]
    return None


def frags_of(text):
    """aria-label 같은 긴 머리 글 → 쉼표·세로줄·가운뎃점 조각."""
    return [x.strip() for x in re.split(r"[,，|·\n]\s*", str(text or "")) if x.strip()]


def iso_local(s):
    """<time datetime> 값(ISO) → 이 PC 로컬 (date, (시, 분)). Z·오프셋이 있으면 로컬로 바꾸고, 없으면 그대로(로컬로 본다)."""
    m = RE_ISO.search(str(s or ""))
    if not m:
        return None
    try:
        dt = datetime(*(int(m.group(i)) for i in range(1, 6)), int(m.group(6) or 0))
    except ValueError:
        return None
    tz = m.group(7)
    if tz:
        if tz == "Z":
            off = timedelta(0)
        else:
            sg = -1 if tz[0] == "-" else 1
            hh, mm = int(tz[1:3]), int(tz[-2:])
            off = sg * timedelta(hours=hh, minutes=mm)
        dt = dt.replace(tzinfo=timezone(off)).astimezone().replace(tzinfo=None)
    return dt.date(), (dt.hour, dt.minute)


# ── 조각 판정(F-03) ─────────────────────────────────────────────────────────
INVERSION_HEAD = 5            # 목록 맨 위 몇 개(고정·중요 표시 항목)는 날짜 순서 검사에서 뺀다


def _monotone(ds):
    """목록이 최신부터 내려가는가 — 맨 위 고정 항목 몇 개를 빼고, 앞보다 새 날짜가 나오는 역전이 거의 없을 때."""
    body = ds[INVERSION_HEAD:] if len(ds) > INVERSION_HEAD + 1 else ds
    inv = sum(1 for a, b in zip(body, body[1:], strict=False) if b > a)   # 인접 쌍(길이 1 차이 — strict 아님)
    return inv <= max(2, len(body) // 100)


def slice_verdict(item_dates, s, e, empty_marker=False, scrolled_contiguous=False, reached_end=False):
    """한 폴더·한 조각 화면 → (판정, D).
    item_dates: 화면에 나온 순서(위 → 아래)의 항목 날짜(해석 못 한 항목은 None).
    · 검색 화면(scrolled_contiguous=False — 기간 검색 뒤 결과를 내린 것):
        항목 0 + '결과 없음' 표식 → empty_verified · 항목 0(표식 없음)·해석 0 → unverified
        조각 밖(앞뒤 1일 여유 밖) 날짜가 하나라도 → filter_ineffective(검색이 안 걸린 화면 — 받은 편지함 첫 화면 등)
        조각 날짜가 하나도 없음 → unverified · 끝까지 내림(reached_end) → ok · 못 내림 → list_verified(맨 아래 항목 날짜)
    · 목록 화면(scrolled_contiguous=True — 검색 없이 최신부터 끊김 없이 내린 것):
        항목 0 + '비어 있음' 표식 → empty_verified · 날짜 순서가 아니면 unverified · 목록 전체가 한 화면(reached_end — 부르는
        쪽이 'fits' 일 때만 준다)이면 ok · 그 밖은 list_verified(맨 아래 날짜 D — 'end' 는 지연 로드일 수 있어 믿지 않는다)
    list_verified(D) = [D+1, e] 는 끝까지 읽음, D 이하는 일부(그 날 항목이 더 아래 있을 수 있다)."""
    ds = [d for d in item_dates if d]
    if scrolled_contiguous:
        if not item_dates:
            return ("empty_verified", None) if empty_marker else ("unverified", None)
        if not ds or not _monotone(ds):
            return "unverified", None
        if reached_end:                     # 폴더 목록 전체가 한 화면에 보였다(fits) — 더 오래된 항목이 없다
            return "ok", None
        return "list_verified", ds[-1]
    if not item_dates:
        return ("empty_verified", None) if empty_marker else ("unverified", None)
    if not ds:
        return "unverified", None
    if any(d < s - DAY or d > e + DAY for d in ds):
        return "filter_ineffective", None
    if not any(s <= d <= e for d in ds):
        return "unverified", None
    if reached_end:
        return "ok", None
    if not _monotone(ds):                   # 끝까지 못 내린 결과가 날짜순이 아니면(관련도순 등) D 로 자를 수 없다
        return "unverified", None
    return "list_verified", ds[-1]


def verdict_ranges(verdict, D, s, e):
    """판정 → [(from, to, st)] — st: ok(끝까지 읽음 · 0건인 날 포함) · zero_ok(검색 결과 없음 확인) · partial · unverified."""
    if verdict == "ok":
        return [(s, e, "ok")]
    if verdict == "empty_verified":
        return [(s, e, "zero_ok")]
    if verdict == "list_verified" and D is not None:
        if D < s:
            return [(s, e, "ok")]
        if D >= e:
            return [(s, e, "partial")]
        return [(s, D, "partial"), (D + DAY, e, "ok")]
    return [(s, e, "unverified")]


ST_RANK = {"ok": 5, "zero_ok": 4, "partial": 3, "unverified": 1}


def apply_ranges(day_st, rngs, cap=None):
    """{날짜: st} 에 [(from, to, st)] 를 더 높은 상태만 남기며 반영(같은 날을 두 길로 읽었으면 나은 쪽).
    cap(date) 이후 날(오늘 포함)의 ok·zero_ok 는 partial 로 — 오늘은 아직 메일·일정이 더 온다(다음 실행이 다시 읽게)."""
    for a, b, st in rngs:
        d = a
        while d <= b:
            s2 = st
            if cap is not None and d >= cap and st in ("ok", "zero_ok"):
                s2 = "partial"
            if d in day_st and ST_RANK.get(s2, 0) > ST_RANK.get(day_st[d], 0):
                day_st[d] = s2
            d += DAY
    return day_st


def ranges_of(day_st, axis):
    """{날짜: st} → [{axis, from, to, st}] (이어진 같은 상태끼리)."""
    out = []
    for d in sorted(day_st):
        st = day_st[d]
        if out and out[-1]["st"] == st and out[-1]["_to"] + DAY == d:
            out[-1]["_to"] = d
            continue
        out.append({"axis": axis, "_from": d, "_to": d, "st": st})
    return [{"axis": x["axis"], "from": x["_from"].isoformat(), "to": x["_to"].isoformat(), "st": x["st"]} for x in out]


# ── 주 보기 머리(F-05) ──────────────────────────────────────────────────────
def _part_ymd(p):
    """범위 한쪽 글 → [연, 월, 일](없는 칸은 None)."""
    y = mo = dd = None
    m = re.search(r"(?<!\d)(\d{4})(?!\d)", p)
    if m:
        y = int(m.group(1))
        p = p[:m.start()] + " " + p[m.end():]
    m = re.search(r"(\d{1,2})\s*[월月]", p)
    if m:
        mo = int(m.group(1))
        p = p[:m.start()] + " " + p[m.end():]
    else:
        m = re.search(r"\b" + _MON, p, re.I)
        if m:
            mo = MON_EN[m.group(1)[:3].lower()]
            p = p[:m.start()] + " " + p[m.end():]
    m = re.search(r"(\d{1,2})\s*[일日]", p) or re.search(r"(?<!\d)(\d{1,2})(?!\d)", p)
    if m:
        dd = int(m.group(1))
    return [y, mo, dd]


def week_header_range(text, today=None):
    """주 보기 머리 글 → (시작, 끝) — 길이 0~6일 범위만(주·근무 주). 못 읽으면 None.
    '2026년 9월 14일–20일' · '2026년 9월 28일 – 10월 4일' · '2026년 12월 28일–2027년 1월 3일' · 'September 14–20, 2026' ·
    'Sep 28 – Oct 4, 2026' · 'Dec 28, 2026 – Jan 3, 2027' · '2026-09-14 ~ 2026-09-20'."""
    t = RE_TIME.sub(" ", hm_words(str(text or ""))).strip()      # 일정 시각('오후 2:00 – 오후 3:00')은 범위가 아니다
    if not t or not re.search(r"\d", t):
        return None
    rest = RE_WEEKDAY_ANY.sub(" ", re.sub(r"(?i)\b" + _MON, " ", t))
    if re.search(r"[A-Za-z가-힣]", re.sub(r"(?i)[년월일주]|\bweek\b|\bof\b", "", rest)):
        return None                                          # 날짜 아닌 낱말(일정 제목 등)이 든 글은 머리가 아니다
    full = []
    for m in RE_YMD.finditer(t):
        y, s1, mo, s2, dd = m.groups()
        if (s1 == "년" and s2 == "월") or (s1 == s2 and s1 != "년"):
            d = _safe(y, mo, dd)
            if d:
                full.append(d)
    if len(full) >= 2:
        a, b = full[0], full[-1]
    else:
        parts = re.split(r"\s*[–—~〜]\s*", t, maxsplit=1)
        if len(parts) < 2:
            parts = re.split(r"\s+-\s+|(?<=[\d일])-(?=\s*\d)", t, maxsplit=1)
        if len(parts) < 2:
            return None
        L, R = _part_ymd(parts[0]), _part_ymd(parts[1])
        if L[2] is None or R[2] is None:
            return None
        inh_y = L[0] is None
        L[0] = L[0] if L[0] is not None else R[0]
        R[0] = R[0] if R[0] is not None else L[0]
        L[1] = L[1] if L[1] is not None else R[1]
        R[1] = R[1] if R[1] is not None else L[1]
        guess = L[0] is None and R[0] is None and today is not None
        if guess:                                          # 연도 없는 머리('9월 14일–20일') — 오늘의 해
            L[0] = R[0] = today.year
        if None in L or None in R:
            return None
        a, b = _safe(*L), _safe(*R)
        if not (a and b):
            return None
        if guess and a > today + timedelta(days=7):        # 오늘보다 한참 뒤면 작년 머리
            a, b = _safe(a.year - 1, a.month, a.day), _safe(b.year - 1, b.month, b.day)
            if not (a and b):
                return None
        if b < a and inh_y:
            a = _safe(a.year - 1, a.month, a.day)          # 'Dec 28 – Jan 3, 2027' — 왼쪽 해는 오른쪽 해의 앞 해
        elif b < a:
            b = _safe(b.year + 1, b.month, b.day)
        if not (a and b):
            return None
    if not (0 <= (b - a).days <= 6):
        return None
    return a, b


# ── 병합(W1-04) ─────────────────────────────────────────────────────────────
def _mail_axis(r):
    return "mail_out" if str(r[0]).strip().lower() == "sent" else "mail_in"


def merge_slices(old, new, verified, kind="mail"):
    """옛 행(old)과 이번 행(new) 합치기 → 새 목록(시각순). 통째로 덮어쓰지 않는다.
    verified: {축: [(from, to), …]} — 이번 실행이 끝까지 읽은 날(date 또는 'YYYY-MM-DD'). 메일 축 mail_in·mail_out, 일정 cal.
    · 검증된 날의 옛 행은 버리고 이번 행으로 바꾼다(그 날 0건이면 0건이 된다).
    · 검증 밖 날의 옛 행은 그대로 둔다(미검증 달의 지난 자료 보존). 검증 밖 이번 행은 같은 행(키)이 이미 있으면 넣지 않고,
      메일은 같은 (상자·날·보낸이·제목)의 날짜만 행(time_precision=date)을 분 단위 행으로 바꾼다."""
    mail = kind == "mail"
    ver = {ax: [(str(a), str(b)) for a, b in (rs or [])] for ax, rs in (verified or {}).items()}

    def day_of(r):
        return str(r[1] if mail else r[0])[:10]

    def key(r):
        # 메일 (상자·시각·보낸이·제목) · 일정 (시작·끝·제목)
        return tuple(str(x) for x in r[:4]) if mail else (str(r[0]), str(r[1]), str(r[4]) if len(r) > 4 else "")

    def covered(r):
        d = day_of(r)
        return any(a <= d <= b for a, b in ver.get(_mail_axis(r) if mail else "cal", ()))

    out = [list(r) for r in (old or []) if r and not covered(r)]
    keys = {key(r) for r in out}
    loose = {}
    if kind == "mail":
        for i, r in enumerate(out):
            if len(r) > 6 and str(r[6]).strip().lower() == "date":
                loose.setdefault((str(r[0]), day_of(r), str(r[2]), str(r[3])), []).append(i)
    drop = set()
    for r in new or []:
        r = list(r)
        if covered(r):
            out.append(r)
            continue
        if key(r) in keys:
            continue
        if kind == "mail" and len(r) > 6 and str(r[6]).strip().lower() == "minute":
            idx = loose.get((str(r[0]), day_of(r), str(r[2]), str(r[3])))
            if idx:
                drop.add(idx.pop(0))
        keys.add(key(r))
        out.append(r)
    out = [r for i, r in enumerate(out) if i not in drop]
    out.sort(key=lambda r: str(r[1] if kind == "mail" else r[0]))
    return out
