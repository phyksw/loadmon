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
    분 단위 시각은 날짜만으로 낮추지 않는다(정밀도 래칫 — LM28 E).
  · iso_local(s) — <time datetime> ISO(Z·오프셋) → 이 PC 로컬 (date, (시, 분))(C-35).
  · apply_ranges(day_st, rngs, cap) · ranges_of(day_st, axis) — {날짜: st} 에 판정 반영(나은 상태만 · 오늘은 partial) →
    LMSTATUS ranges 조각(이어진 같은 상태끼리).
  · pick_list(cands) · mail_list_ok(lst, parsed, total) — 화면의 목록 칸 후보(JS 가 센 구조 사실) 중 메일 목록 칸 고르기·확인
    (LM28 현장 2026-10-08: 화면의 첫 listbox 가 메일 목록이 아니었다).
  · weekday_date(text, d0, d1) — 날짜 없이 요일만 있는 일정 글 → 그 주 안의 그 요일.
  · mask_shape(s) · skeleton(node) · fmt_flags(text) — 화면 구조 진단용(글자 → x · 태그·role·aria-label 길이 · 날짜 표기 꼴만).
  · 일정 위치 해석(LM28 현장 2026-10-11 — 라벨에 날짜·시각이 없는 막대): header_date · day_columns · col_date · col_span(요일 열)
    · hour_label · time_scale · y_to_min(시간 눈금) · cal_nonevent(칩·머리 칸) · picker_date(작은 달력 칸) · mask_cal(못 읽은
    막대 꼴 — 글자 x, 숫자·구두점·오전/오후·요일·종일만).
  · 다른 메일 폴더(LM28-OWA-5 — 받은·보낸 편지함 밖으로 옮긴·이름을 바꾼·보관한 메일): folder_name · folder_kind(시스템 폴더
    여러 언어·data-folder-name) · tree_nodes(폴더 창 treeitem → 부모·하위) · pick_mailbox(즐겨찾기·그룹·공유·온라인 보관을 빼고
    기본 사서함) · plan_folders(읽을 폴더·box·펼칠 폴더·제외 수) · node_key·find_node(화면이 다시 그려져도 같은 폴더) ·
    cap_extra(다른 폴더 판정은 그날 상태를 **낮추기만**) · url_kind(주소의 잘 알려진 폴더 마디) · same_folder.
  · body_key(시작, 끝, 제목) — 일정 본문 발췌 캐시 열쇠(제목은 해시만).
"""
import hashlib
import re
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlparse

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
# 온전한 요일 낱말만(한 글자 '월'·'화'는 '9월' 같은 날짜 조각과 섞여 쓰지 않는다) — 날짜 없는 일정 막대의 요일
RE_WEEKDAY_FULL = re.compile(r"(?i)\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b|([월화수목금토일])요일")


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
        항목 0 + '비어 있음' 표식 → empty_verified · 날짜 순서가 아니면 unverified · 목록 끝 확인(reached_end)이면 ok ·
        그 밖은 list_verified(맨 아래 날짜 D — 기간 시작 앞에 닿았으면 D < s 라 기간 전체가 ok)
    reached_end 는 부르는 쪽이 '끝 근거'가 있을 때만 준다(LM28 현장 2026-10-08 이후): 바닥에서 새 행 0 이 여러 번(사이에 휠·
    '더 보기'·긴 대기, 불러오는 중 표시 없음) + 그 칸이 메일 목록(mail_list_ok). 'fits'(칸이 화면에 다 들어감)는 근거가 아니다.
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


def _exact_key(r):
    """정밀도 래칫(LM28 E)의 같은 메일 열쇠 — (상자·날·보낸이·제목·대화). 제목을 남기지 않는 설정(storeMailSubject=false)은
    제목이 비고 대화가 해시라 대화로 가른다."""
    return (str(r[0]), str(r[1])[:10], str(r[2]), str(r[3]), str(r[4]) if len(r) > 4 else "")


def merge_slices(old, new, verified, kind="mail"):
    """옛 행(old)과 이번 행(new) 합치기 → 새 목록(시각순). 통째로 덮어쓰지 않는다.
    verified: {축: [(from, to), …]} — 이번 실행이 끝까지 읽은 날(date 또는 'YYYY-MM-DD'). 메일 축 mail_in·mail_out, 일정 cal.
    · 검증된 날의 옛 행은 버리고 이번 행으로 바꾼다(그 날 0건이면 0건이 된다).
    · 검증 밖 날의 옛 행은 그대로 둔다(미검증 달의 지난 자료 보존). 검증 밖 이번 행은 같은 행(키)이 이미 있으면 넣지 않고,
      메일은 같은 (상자·날·보낸이·제목)의 날짜만 행(time_precision=date)을 분 단위 행으로 바꾼다.
    · 정밀도 래칫(LM28 E): 검증된 날의 옛 분 단위 행(지난 실행이 열어서 복원한 시각)은 이번 실행이 같은 메일(상자·날·보낸이·
      제목·대화)을 날짜만으로 읽었으면 그 시각을 물려준다 — 분 단위를 날짜만으로 낮추지 않는다(실행마다 복원 예산 150건이
      누적된다). 같은 열쇠가 여럿이면 늦은 시각부터(목록은 최신부터 읽는다)."""
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
    loose, exact, kept_min = {}, {}, set()
    if kind == "mail":
        for i, r in enumerate(out):
            if len(r) > 6 and str(r[6]).strip().lower() == "date":
                loose.setdefault((str(r[0]), day_of(r), str(r[2]), str(r[3])), []).append(i)
            elif len(r) > 6 and str(r[6]).strip().lower() == "minute":
                kept_min.add(_exact_key(r))          # 검증 밖 날의 옛 분 단위 행 — 같은 메일의 날짜만 사본은 더하지 않는다
        for r in old or []:
            if r and covered(r) and len(r) > 6 and str(r[6]).strip().lower() == "minute":
                exact.setdefault(_exact_key(r), []).append(str(r[1])[11:16])
        for v in exact.values():
            v.sort()
    drop = set()
    for r in new or []:
        r = list(r)
        is_date = mail and len(r) > 6 and str(r[6]).strip().lower() == "date"
        if covered(r):
            if is_date:
                hm = exact.get(_exact_key(r))
                if hm and re.fullmatch(r"\d{2}:\d{2}", hm[-1] or ""):
                    r[1] = f"{str(r[1])[:10]} {hm.pop()}"
                    r[6] = "minute"
            out.append(r)
            continue
        if key(r) in keys or (is_date and _exact_key(r) in kept_min):
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


# ── 목록 칸 고르기(LM28 현장 2026-10-08) ─────────────────────────────────────────
def _int(v, d=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return d


def pick_list(cands):
    """화면의 목록 칸 후보(JS 가 센 구조 사실 {i, opts, mailish, conv, main, vis, …}) → 메일 목록 칸 번호 | None.
    메일 행처럼 보이는 행(data-convid 또는 시각·날짜 조각)이 가장 많은 칸 — data-convid 가 있는 칸·본문(main·data-app-section)
    안쪽·보이는 칸을 앞세운다. 메일 행이 하나도 없는 칸은 고르지 않는다(현장: 첫 listbox 는 짧은 다른 칸이었다)."""
    best, top = None, 0
    for c in cands or ():
        if not isinstance(c, dict):
            continue
        m = _int(c.get("mailish"))
        if m <= 0:
            continue
        sc = m * 10 + (40 if _int(c.get("conv")) else 0) + (20 if _int(c.get("main")) else 0) + (5 if _int(c.get("vis")) else 0)
        if sc > top:
            best, top = _int(c.get("i"), None), sc
    return best


def mail_list_ok(lst, parsed=0, total=0):
    """고른 칸이 메일 목록으로 확인되는가 — 칸의 행 대부분(60%)이 메일 행(또는 data-convid 가 있음)이고, 읽은 항목 대부분(60%)의
    날짜를 풀었을 때. 목록 '끝'을 근거로 쓰려면(owa_parse.slice_verdict reached_end) 이것이 참이어야 한다."""
    if not isinstance(lst, dict):
        return False
    opts, m, cv = _int(lst.get("opts")), _int(lst.get("mailish")), _int(lst.get("conv"))
    if opts <= 0 or not (cv > 0 or m * 10 >= opts * 6):
        return False
    return total > 0 and parsed * 10 >= total * 6


def weekday_date(text, d0, d1):
    """날짜 없이 요일만 있는 일정 글('주간 회의, 화요일 오후 2:00 ~ 오후 3:00') → 그 주(d0~d1, 7일 이내) 안의 그 요일 | None.
    서로 다른 요일 낱말이 둘 이상이면(반복 설명·제목 속 요일) 고르지 않는다."""
    if not (d0 and d1) or not (0 <= (d1 - d0).days <= 6):
        return None
    wds = set()
    for m in RE_WEEKDAY_FULL.finditer(str(text or "")):
        w = (m.group(1) or "").lower() or (m.group(2) + "요일")
        if w in WDAY:
            wds.add(WDAY[w])
    if len(wds) != 1:
        return None
    wd, d = wds.pop(), d0
    while d <= d1:
        if d.weekday() == wd:
            return d
        d += DAY
    return None


# ── 화면 구조 진단(구조만 — 회사 PC 화면을 볼 수 없어 사진 한 장·진단 묶음으로 원인을 확정하려는 것) ─────────────────
RE_LETTER = re.compile(r"[^\W\d_]")                  # 모든 문자 체계의 글자(한글·한자·가나·라틴·키릴)
RE_KEEP_WORD = re.compile(r"오전|오후|어제|Yesterday|yesterday|AM|PM|am|pm")


def mask_shape(s, n=24):
    """글자 → x(숫자·구두점·공백과 오전/오후·AM/PM·어제 표기는 그대로) — Diagnose-Collectors.ps1 Mask 와 같은 규칙. n 자에서 자른다."""
    t, out, i = str(s or ""), [], 0
    for m in RE_KEEP_WORD.finditer(t):
        out.append(RE_LETTER.sub("x", t[i:m.start()]))
        out.append(m.group(0))
        i = m.end()
    out.append(RE_LETTER.sub("x", t[i:]))
    t = re.sub(r"\s+", " ", "".join(out)).strip()
    return t[:n] + ("…" if len(t) > n else "")


def skeleton(node, n=320):
    """JS 가 낸 행 골격({t 태그, r role, al aria-label 길이, cv data-convid, x 잎 글, c 자식[], k 자식 수}) → 한 줄
    'div[option,al87,cv]{div{span'xxx'|span'2026-09-02'}}' — 태그·role·길이·표식만 남기고 잎 글은 mask_shape 로 가린다."""
    def one(o, d):
        if not isinstance(o, dict) or d > 6:
            return ""
        s = re.sub(r"[^a-z0-9-]", "", str(o.get("t") or "?").lower())[:12] or "?"
        at = []
        if o.get("r"):
            at.append(re.sub(r"[^A-Za-z-]", "", str(o["r"]))[:16])
        if o.get("al"):
            at.append(f"al{_int(o['al'])}")
        if o.get("cv"):
            at.append("cv")
        if o.get("k"):
            at.append(f"k{_int(o['k'])}")
        if at:
            s += "[" + ",".join(a for a in at if a) + "]"
        if o.get("x"):
            s += "'" + mask_shape(o["x"], 16) + "'"
        kids = [k for k in (one(c, d + 1) for c in (o.get("c") or [])[:6]) if k]
        if kids:
            s += "{" + "|".join(kids) + "}"
        return s
    out = one(node, 0)
    return out[:n] + ("…" if len(out) > n else "")


def fmt_flags(text):
    """글의 날짜·시각 표기 꼴(내용 없이) → 'ymd+t2+wd' 꼴 — ymd·mdy·mon(영문 월)·kmd('n월 n일')·md(M/D) · tN(시각 수) ·
    wd(요일 낱말) · rel(오늘·어제) · ad(종일). 진단용으로 어떤 표기가 화면에 있는지만 남긴다."""
    t = hm_words(str(text or ""))
    f = []
    if RE_YMD.search(t):
        f.append("ymd")
    elif RE_MDY.search(t):
        f.append("mdy")
    elif RE_MONEN.search(t) or RE_DMONEN.search(t):
        f.append("mon")
    elif RE_MD_KO.search(t):
        f.append("kmd")
    elif RE_MD.search(RE_TIME.sub(" ", t)):
        f.append("md")
    n = len(find_times(t))
    if n:
        f.append(f"t{min(n, 9)}")
    if RE_WEEKDAY_FULL.search(t):
        f.append("wd")
    if re.search(r"(?i)어제|오늘|yesterday|today", t):
        f.append("rel")
    if re.search(r"(?i)종일|all[- ]day|終日|全天", t):
        f.append("ad")
    return "+".join(f) or "-"


# ── 일정 위치 해석(LM28 현장 2026-10-11 — 회사 PC: 막대 108 · 날짜·시각을 못 읽음 16 · 9주 중 1주만 확인) ─────────────────
# 라벨 꼴(반복 회의·종일 줄·자식 요소에만 있는 시각 …)은 화면마다 달라 고를 수 없다. 화면 구조와 무관한 신호로 푼다 — 막대 가로
# 가운데가 든 요일 열(열 머리 칸의 날짜·가로 위치)이 날짜, 세로 위치가 시간 눈금(시각 글의 세로 위치)으로 시각. 열·눈금을 못
# 찾으면 풀지 않는다(정직하게 일부). JS 가 내는 재료: 짧은 숫자 글 [{s, x, y, w, h}](가운데 좌표 px) · 막대 {x, l, r, t, b, ad, in}.
def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None             # NaN 제외


def _median(xs):
    s = sorted(xs)
    n = len(s)
    if not n:
        return None
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def header_date(text, d0, d1):
    """주 보기 열 머리 글 → 그 주(d0~d1) 안의 날짜 | None. 온전한 날짜('2026년 10월 5일 월요일'·'Mon 10/5') → 날 번호('5 월'·'5'
    — 그 주에 그 날이 하나뿐일 때) → 요일('월요일') 순. 시각·'시'·오전/오후가 든 글(시간 눈금)은 머리가 아니다."""
    t = hm_words(str(text or "")).strip()
    if not t or len(t) > 48 or not (d0 and d1) or find_times(t) or RE_DESIG.search(t) or re.search(r"\d\s*[시時]", t):
        return None
    d = _abs_date(t, d1, d0, d1)
    if d is None and is_datetime_text(t):
        d = _abs_date(t, d1, d0, d1, weak=True)
    if d is not None:
        return d if d0 <= d <= d1 else None
    nums = {int(x) for x in re.findall(r"(?<!\d)(\d{1,2})(?!\d)", t)}
    if nums:
        hits, d = [], d0
        while d <= d1:
            if d.day in nums:
                hits.append(d)
            d += DAY
        return hits[0] if len(hits) == 1 else None
    return weekday_date(t, d0, d1)


def day_columns(pts, d0, d1, xs=()):
    """열 머리 후보(짧은 숫자 글 [{s, x, y}]) → 요일 열 {x: 기준 열 가운데, d: 그 날짜, s: 하루 간격 px(오른쪽이 앞날이면 −),
    n: 읽힌 머리 수, lo·hi: 그 주} | None.
    같은 가로줄(y ±8px)에서 그 주의 날짜로 읽히는 칸 2개 이상 · 날짜가 x 순으로 한쪽으로만 늘고 · 하루 간격이 고르고(±35%) ·
    36px 이상인 줄. 여럿이면 막대 가운데 x(xs)를 가장 많이 품는 줄 — 왼쪽 작은 달력의 한 주 줄(칸 28px 안팎)은 간격에서 빠지고
    막대도 품지 않는다. 머리가 빠진 날은 간격으로 잇는다(col_date)."""
    if not (d0 and d1):
        return None
    cands = []
    for p in pts or ():
        if not isinstance(p, dict):
            continue
        x, y = _num(p.get("x")), _num(p.get("y"))
        d = header_date(p.get("s"), d0, d1) if x is not None and y is not None else None
        if d:
            cands.append((y, x, d))
    cands.sort(key=lambda c: (c[0], c[1]))
    rows, cur = [], []
    for c in cands:
        if cur and c[0] - cur[-1][0] > 8:
            rows.append(cur)
            cur = []
        cur.append(c)
    if cur:
        rows.append(cur)
    xs = [v for v in (_num(x) for x in xs or ()) if v is not None]
    best, key = None, None
    for row in rows:
        byd = {}
        for _y, x, d in row:
            byd.setdefault(d, []).append(x)                # 한 칸의 숫자 글과 이름(aria-label)이 같은 날로 둘 다 잡힐 수 있다
        if len(byd) < 2:
            continue
        pairs = sorted((_median(v), d) for d, v in byd.items())
        steps = [(xb - xa) / (db - da).days for (xa, da), (xb, db) in zip(pairs, pairs[1:], strict=False) if db != da]
        if len(steps) != len(pairs) - 1:
            continue
        s = _median(steps)
        if abs(s) < 36 or any(st * s <= 0 or abs(st - s) > 0.35 * abs(s) for st in steps):
            continue
        if any(max(v) - min(v) > 0.5 * abs(s) for v in byd.values()):
            continue                                       # 같은 날이 서로 다른 열에 — 머리 줄이 아니다
        dref = pairs[0][1]
        cols = {"x": _median([x - (d - dref).days * s for x, d in pairs]), "d": dref, "s": s, "n": len(pairs),
                "lo": d0, "hi": d1}
        k = (sum(1 for x in xs if col_date(cols, x) is not None), len(pairs), abs(s))
        if key is None or k > key:
            best, key = cols, k
    return best


def col_date(cols, x):
    """요일 열(day_columns)에서 가로 위치 x 가 든 열의 날짜 | None(그 주 밖 — 시간 눈금 칸·옆 창)."""
    v = _num(x)
    if not cols or v is None:
        return None
    k = round((v - cols["x"]) / cols["s"])
    d = cols["d"] + timedelta(days=k)
    return d if cols["lo"] <= d <= cols["hi"] else None


def col_span(cols, left, right):
    """종일 줄 막대의 왼쪽·오른쪽 끝 → 걸친 첫날·마지막 날 (a, b) | None(가장자리 몇 px 안쪽으로 잰다)."""
    lv, rv = _num(left), _num(right)
    if not cols or lv is None or rv is None or rv <= lv:
        return None
    pad = min(8.0, (rv - lv) / 4)
    a, b = col_date(cols, lv + pad), col_date(cols, rv - pad)
    if a is None or b is None:
        return None
    return min(a, b), max(a, b)


def _line(pts):
    """[(y, 분)] → (k, a) — y = a + k·분. 기울기는 모든 쌍 기울기의 가운데값(Theil–Sen), a 는 가운데값."""
    sl = [(y2 - y1) / (m2 - m1) for i, (y1, m1) in enumerate(pts) for y2, m2 in pts[i + 1:] if m2 != m1]
    k = _median(sl) or 0.0
    return k, _median([y - k * m for y, m in pts])


RE_HOUR_LABEL = re.compile(r"^(?:(오전|오후|AM|PM|A\.M\.|P\.M\.)\s*)?(\d{1,2})(?::([0-5]\d))?\s*(?:시|(AM|PM|A\.M\.|P\.M\.))?$",
                           re.I)


def hour_label(s):
    """시간 눈금 글('오전 9시'·'9 AM'·'09:00'·'21:00'·'9'·'정오') → 자정부터 분 | None."""
    t = str(s or "").strip()
    if t.lower() in ("정오", "noon"):
        return 720
    m = RE_HOUR_LABEL.match(t)
    if not m:
        return None
    ap = (m.group(1) or m.group(4) or "").upper()
    h, mm = int(m.group(2)), int(m.group(3) or 0)
    if ap and not 1 <= h <= 12:
        return None
    if ap in PM_WORDS and h < 12:
        h += 12
    elif ap in AM_WORDS and h == 12:
        h = 0
    if h > 24 or (h == 24 and mm):
        return None
    return h * 60 + mm


def time_scale(pts, calib=()):
    """시간 눈금 → {a, k, ot, ob, n, c}(막대 위 y = a + k·분 + ot · 아래 y = a + k·분 + ob) | None.
    pts: 짧은 숫자 글 [{s, x, y}] — 같은 세로줄(x ±24px)의 시각 글('오전 9시'·'9 AM'·'09:00' — 15분 단위만) 중 한 직선(모든 쌍
    기울기의 가운데값 · 벗어난 글은 버림)에 3개 이상(60% 이상) 놓이고, 위에서 아래로 분이 늘고, 가장 흔한 간격이 15·30·60분이며,
    시간당 12~600px 인 무리 중 가장 긴 것. 작은 달력의 세로줄(5·12·19 — 7시간 간격)은 기울기·간격에서 빠지고, 눈금 칸의 '현재 시각'
    같은 글 하나는 직선에서 벗어나 빠진다. calib: 라벨로 시각을 안 막대 [(위 y, 시작 분, 아래 y, 끝 분)] — 눈금 글이 선 위·아래·가운데
    어디에 붙는지 몰라 막대로 맞춘다(ot·ob). 눈금 글이 없으면 그런 막대 2개 이상(시작 60분 이상 차이)으로 직선을 맞춘다.
    보정이 서로 15분 넘게 어긋나거나 45분 넘게 벗어나면(막대와 눈금이 다른 스크롤 칸) None — 위치로 시각을 풀지 않는다."""
    hp = []
    for p in pts or ():
        if not isinstance(p, dict):
            continue
        x, y, m = _num(p.get("x")), _num(p.get("y")), hour_label(p.get("s"))
        if x is not None and y is not None and m is not None:
            hp.append((x, y, m))
    hp.sort()
    groups, cur = [], []
    for q in hp:
        if cur and q[0] - cur[0][0] > 24:
            groups.append(cur)
            cur = []
        cur.append(q)
    if cur:
        groups.append(cur)
    best = None
    for g in groups:
        bym = {}
        for _x, y, m in g:
            if m % 15 == 0:                               # 눈금은 정시·15분 단위 — '현재 시각 오후 10:50' 같은 글은 뺀다
                bym.setdefault(m, []).append(y)
        pts_ = sorted((_median(v), m) for m, v in bym.items())
        if len(pts_) < 3:
            continue
        k, a = _line(pts_)                                # 모든 쌍 기울기의 가운데값 — 벗어난 글 하나에 흔들리지 않는다
        if not 0.2 <= k <= 10:
            continue
        inl = [(y, m) for y, m in pts_ if abs(y - (a + k * m)) <= max(3.0, 9 * k)]
        ms = [m for _y, m in inl]
        if len(inl) < 3 or len(inl) * 10 < len(pts_) * 6 or any(b <= a2 for a2, b in zip(ms, ms[1:], strict=False)):
            continue
        dms = [b - a2 for a2, b in zip(ms, ms[1:], strict=False)]
        step = max(set(dms), key=dms.count)
        if step not in (15, 30, 60) or dms.count(step) * 10 < len(dms) * 6:
            continue
        k, a = _line(inl)
        if best is None or len(inl) > best[2]:
            best = (k, a, len(inl))
    cal = []
    for c in calib or ():
        v = [_num(x) for x in (tuple(c) + (None,) * 4)[:4]]
        if None not in v and v[3] > v[1] and v[2] > v[0]:
            cal.append(tuple(v))
    if best is None:
        tops = [(m, t) for t, m, _b, _e in cal]
        if len({m for m, _t in tops}) < 2 or max(m for m, _t in tops) - min(m for m, _t in tops) < 60:
            return None
        n = len(tops)
        mx, my = sum(m for m, _t in tops) / n, sum(t for _m, t in tops) / n
        sxx = sum((m - mx) ** 2 for m, _t in tops)
        k = sum((m - mx) * (t - my) for m, t in tops) / sxx
        a = my - k * mx
        if not 0.2 <= k <= 10 or any(abs(t - (a + k * m)) > max(4.0, 6 * k) for m, t in tops):
            return None
        best = (k, a, 0)
    k, a, n = best
    ot = ob = 0.0
    if cal:
        offt = [t - (a + k * m) for t, m, _b, _e in cal]
        offb = [b - (a + k * e) for _t, _m, b, e in cal]
        if max(offt) - min(offt) > 15 * k or max(offb) - min(offb) > 15 * k or abs(_median(offt)) > 45 * k:
            return None
        ot, ob = _median(offt), _median(offb)
    return {"a": a, "k": k, "ot": ot, "ob": ob, "n": n, "c": len(cal)}


def y_to_min(sc, y, edge="t", step=5):
    """시간 눈금(time_scale)으로 세로 위치 → 자정부터 분(step 분 단위로 반올림) | None(하루 밖). edge: 't' 막대 위 · 'b' 아래."""
    v = _num(y)
    if not sc or v is None:
        return None
    m = (v - sc["a"] - (sc["ot"] if edge == "t" else sc["ob"])) / sc["k"]
    m = int(round(m / step)) * step
    return m if 0 <= m <= 1440 else None


RE_MORE_N = re.compile(r"(?i)^.{0,8}?(?:\+\s*\d+|(?<!\d)\d+\s*개\s*더|(?<![\w:])\d+\s*more\b)|^\s*더\s*보기\s*[(\[]?\s*\+?\d+")
RE_BTN_W = re.compile(r"(?i)^\s*(?:더\s*보기|more|see more|show more|view more|모두\s*보기|자세히|옵션|options?)\s*$")
RE_HEAD_W = re.compile(r"(?i)하루\s*종일|종일|all[- ]day|오늘|today|이벤트|일정|약속|항목|events?|items?|appointments?|선택됨|"
                       r"selected|week|[개건주]")


def cal_nonevent(label, texts=()):
    """일정이 아닌 칸 → 'more'(숨은 일정 칩 — '+2'·'+2 더 보기'·'2개 더'·'2 more' — 주 보기에 다 안 그려진 일정이 있다는 뜻) ·
    'btn'(수 없는 '더 보기'·'옵션' 단추뿐) · 'head'(날짜·요일·종일·개수 낱말뿐 — 주 머리 칸) · ''(일정 막대).
    머리 글은 라벨(없으면 첫 글) 하나만, 칩 낱말은 짧은 글(40자 이하)의 앞머리에서만 본다 — 막대 안의 '+3'(참석자 수)·
    'and 3 more'(참석자) 같은 글을 칩으로 읽지 않게."""
    lab = str(label or "").strip()
    tx = [str(x).strip() for x in texts or () if str(x or "").strip()]
    head = lab or (tx[0] if tx else "")
    if not head:
        return ""
    if len(head) <= 40 and RE_MORE_N.search(head):
        return "more"
    if find_times(" ".join([lab] + tx)):
        return ""
    if all(RE_BTN_W.match(x) for x in [head] + tx):
        return "btn"
    if re.search(r"\d", head):
        r = RE_MD.sub(" ", _strip_dates(hm_words(head)))
        r = re.sub(r"\d+", " ", RE_HEAD_W.sub(" ", RE_WEEKDAY_ANY.sub(" ", r)))
        if _PUNCT_RX.sub("", r) == "":
            return "head"
    return ""


def picker_date(text, near=None):
    """작은 달력(날짜 고르기) 칸 이름 → date | None — '2026년 10월 5일 월요일'·'October 5, 2026'·'5, October, 2026'·'5, 10월, 2026'
    (Fluent Calendar 기본 꼴: 날, 달 이름, 해)·'10/5/2026'. 해가 없으면 near(목표 날짜)에 가장 가까운 해. 날 번호만('5')이면 None."""
    t = hm_words(str(text or "")).strip()
    if not t or find_times(t):
        return None
    ref = near or date.today()
    ym = re.search(r"(?<!\d)(\d{4})(?!\d)", t)
    if ym:
        d = _abs_date(t, ref)
        if d:
            return d
    rest = t
    m = re.search(r"(?i)\b" + _MON, rest)
    if m:
        mo = MON_EN[m.group(1)[:3].lower()]
    else:
        m = re.search(r"(?<!\d)(\d{1,2})\s*[월月]", rest)
        mo = int(m.group(1)) if m else None
    if mo is None:
        return None
    rest = rest[:m.start()] + " " + rest[m.end():]
    if ym:
        rest = rest.replace(ym.group(1), " ", 1)
    ds = re.findall(r"(?<!\d)(\d{1,2})(?!\d)", rest)
    if len(ds) != 1:
        return None
    if ym:
        return _safe(ym.group(1), mo, ds[0])
    cands = [x for x in (_safe(ref.year + k, mo, ds[0]) for k in (-1, 0, 1)) if x]
    return min(cands, key=lambda x: abs((x - ref).days)) if cands else None


_MONTHS_EN = ("January|February|March|April|May|June|July|August|September|October|November|December|"
              "Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec")
RE_KEEP_CAL = re.compile(
    r"오전|오후|(?<![A-Za-z])(?:AM|PM|am|pm|A\.M\.|P\.M\.)(?![A-Za-z])|하루\s?종일|종일|(?i:all[- ]day)|"
    r"[월화수목금토일]요일|\([월화수목금토일]\)|(?i:monday|tuesday|wednesday|thursday|friday|saturday|sunday)|"
    r"(?<=\d)\s?[년월일시분]|"
    r"(?i:(?<![A-Za-z])(?:" + _MONTHS_EN + r")\.?(?=,?\s*\d))|(?i:(?<=\d\s)(?:" + _MONTHS_EN + r")(?![A-Za-z]))|"
    r"(?i:(?<=\d,\s)(?:" + _MONTHS_EN + r")(?![A-Za-z]))")


def mask_cal(s, n=60):
    """못 읽은 일정 막대 꼴(구조 진단 — 회사 PC 화면을 볼 수 없어 사진 한 장으로 라벨 꼴을 확정하려는 것): 글자 → x, 숫자·구두점·
    공백과 오전/오후·AM/PM·요일·종일·날짜 단위(숫자 뒤 년·월·일·시·분)·숫자 곁의 영문 달 이름만 그대로. 4자리 넘는 숫자 무리와
    해(19xx·20xx)가 아닌 4자리 숫자는 #(회의실·전화·회의 번호). n 자에서 자른다."""
    t, out, i = str(s or ""), [], 0
    for m in RE_KEEP_CAL.finditer(t):
        out.append(RE_LETTER.sub("x", t[i:m.start()]))
        out.append(m.group(0))
        i = m.end()
    out.append(RE_LETTER.sub("x", t[i:]))
    t = re.sub(r"\s+", " ", "".join(out)).strip()
    t = re.sub(r"\d{4,}", lambda m: m.group(0) if (len(m.group(0)) == 4 and m.group(0)[:2] in ("19", "20"))
               else "#" * len(m.group(0)), t)
    return t[:n] + ("…" if len(t) > n else "")


# ── 다른 메일 폴더(LM28-OWA-5) ─────────────────────────────────────────────────────────────────
# 사용자 제보: '메일함 보낸/받은만 보는데 메일 폴더를 바꿀 수 있음(이름 등) — 제외되는 게 있을 수 있다'. 규칙·사람이 옮긴 메일,
# 보관한 메일, 이름을 바꾼 폴더의 메일은 받은·보낸 편지함 주소(/mail/inbox·/mail/sentitems)로는 보이지 않는다. 왼쪽 폴더 창
# (role=tree·treeitem — 접근성 속성만)에서 기본 사서함의 폴더를 가린다. 시스템 폴더는 data-folder-name(잘 알려진 폴더 이름 —
# 언어 무관)을 먼저, 없으면 화면 이름(여러 언어)을 **사서함 맨 위 칸에서만** 본다 — 시스템 폴더는 늘 맨 위에 있고 같은 이름의
# 형제 폴더는 만들 수 없으니, 그 아래의 '메모'·'보관' 같은 이름은 사람이 만든 폴더다. 제외 폴더(지운 편지함 등)의 하위는 함께 뺀다.
# 보관(Archive)은 받은 메일로 읽는다(COM 수집기와 같다 — 보낸 편지함 아래만 보낸 메일).
WK_KIND = {"inbox": "inbox", "sentitems": "sent", "deleteditems": "deleted", "junkemail": "junk", "drafts": "drafts",
           "outbox": "outbox", "archive": "archive", "notes": "notes", "conversationhistory": "conv", "rssfeeds": "rss",
           "rsssubscriptions": "rss", "syncissues": "sync", "conflicts": "sync", "localfailures": "sync",
           "serverfailures": "sync", "searchfolders": "search", "finder": "search", "scheduled": "scheduled",
           "clutter": ""}                       # 낮은 우선 순위 메일(Clutter)은 받은 메일 — 사람이 만든 폴더처럼 읽는다
FOLDER_WORDS = (                               # 소문자 · 이름 전체가 같을 때만(맨 위 칸)
    ("inbox", ("받은 편지함", "받은편지함", "받은 메일함", "inbox", "posteingang", "boîte de réception", "bandeja de entrada",
               "posta in arrivo", "caixa de entrada", "受信トレイ", "收件箱", "收件匣")),
    ("sent", ("보낸 편지함", "보낸편지함", "보낸 항목", "보낸 메일함", "sent items", "sent mail", "sent messages",
              "gesendete elemente", "éléments envoyés", "elementos enviados", "posta inviata", "itens enviados", "送信済みアイテム",
              "已发送邮件", "寄件備份")),
    ("deleted", ("지운 편지함", "지운편지함", "삭제된 항목", "삭제된 편지함", "deleted items", "trash", "gelöschte elemente",
                 "éléments supprimés", "elementos eliminados", "posta eliminata", "itens excluídos", "削除済みアイテム", "已删除邮件",
                 "刪除的郵件")),
    ("junk", ("정크 메일", "정크", "정크 메일함", "스팸", "스팸 메일", "junk email", "junk e-mail", "junk", "spam", "junk-e-mail",
              "courrier indésirable", "correo no deseado", "posta indesiderata", "lixo eletrônico", "迷惑メール", "垃圾邮件",
              "垃圾郵件")),
    ("drafts", ("임시 보관함", "임시보관함", "drafts", "entwürfe", "brouillons", "borradores", "bozze", "rascunhos", "下書き",
                "草稿")),
    ("outbox", ("보낼 편지함", "보낼편지함", "outbox", "postausgang", "boîte d'envoi", "bandeja de salida", "posta in uscita",
                "caixa de saída", "送信トレイ", "发件箱", "寄件匣")),
    ("conv", ("대화 기록", "conversation history", "unterhaltungsverlauf", "historique des conversations",
              "historial de conversaciones", "会話の履歴", "对话历史记录", "交談記錄")),
    ("rss", ("rss 구독", "rss 피드", "rss feeds", "rss subscriptions", "rss-feeds", "rss-abonnements", "flux rss", "fuentes rss",
             "rss フィード", "rss 源", "rss 订阅")),
    ("sync", ("동기화 문제", "충돌", "로컬 오류", "서버 오류", "sync issues", "conflicts", "local failures", "server failures",
              "synchronisierungsprobleme", "konflikte", "lokale fehler", "serverfehler", "problèmes de synchronisation", "同期の失敗",
              "同步问题")),
    ("notes", ("메모", "notes", "notizen", "notas", "メモ", "便笺")),
    ("search", ("검색 폴더", "search folders", "suchordner", "dossiers de recherche", "carpetas de búsqueda", "検索フォルダー",
                "搜索文件夹")),
    ("scheduled", ("예약됨", "예약된 항목", "scheduled", "geplant", "planifié", "programado", "スケジュール済み", "已计划")),
    ("archive", ("보관", "보관함", "보관 편지함", "보관 처리", "archive", "archiv", "archives", "archivo", "archivio", "arquivo",
                 "アーカイブ", "存档", "封存")),
)
SKIP_KINDS = frozenset({"deleted", "junk", "drafts", "outbox", "conv", "rss", "sync", "notes", "search", "scheduled"})
SYS_KINDS = SKIP_KINDS | {"inbox", "sent", "archive"}
# 사서함이 아닌 머리 — 즐겨찾기(기본 사서함 폴더의 사본)·그룹·나와 공유·온라인 보관 사서함(머리 이름 또는 나무 aria-label)
FAV_RX = re.compile(r"(?i)^(?:즐겨찾기|즐겨\s*찾는\s*폴더|favorites?|favourites?|favoriten|favoris|favoritos|preferiti|お気に入り|"
                    r"收藏夹|我的最愛)$")
GROUP_RX = re.compile(r"(?i)^(?:그룹|groups?|gruppen|groupes|grupos|gruppi|グループ|组|群組)$")
SHARED_RX = re.compile(r"(?i)^(?:나와\s*공유(?:됨|된\s*(?:항목|폴더))?|공유\s*(?:폴더|사서함|항목)|shared(?:\s+(?:with\s+me|folders?|"
                       r"mailboxes?))?|für\s+mich\s+freigegeben|partagés?\s+avec\s+moi|compartidos?\s+conmigo|自分と共有|与我共享)$")
ARCH_MB_RX = re.compile(r"(?i)온라인\s*보관|online\s*archive|in-place\s*archive|보관\s*사서함|archive\s*mailbox|onlinearchiv|"
                        r"archive\s+en\s+ligne|archivo\s+en\s+línea|オンライン\s*アーカイブ|在线存档")
_UNREAD_W = r"(?:읽지\s*않(?:음|은(?:\s*(?:항목|메시지|메일))?)|unread(?:\s+(?:items?|messages?))?)"
_FOLDER_TAIL = re.compile(                     # '…, 3 unread' · '…, 읽지 않음 3' · '… 읽지 않은 항목 3개' · '…, 선택됨'
    r"(?i)\s*[,，]?\s*(?:\(?\d+\)?\s*(?:개|건)?\s*" + _UNREAD_W + r"|" + _UNREAD_W + r"\s*\(?\d+\)?\s*(?:개|건)?"
    r"|선택됨|selected|펼쳐짐|확장됨|축소됨|접힘|expanded|collapsed)\s*$")
URL_KIND = {"inbox": "inbox", "sentitems": "sent", "deleteditems": "deleted", "junkemail": "junk", "drafts": "drafts",
            "outbox": "outbox", "archive": "archive", "notes": "notes", "conversationhistory": "conv", "rssfeeds": "rss",
            "syncissues": "sync", "searchfolders": "search", "scheduled": "scheduled"}


def folder_name(s):
    """폴더 창 항목 이름(title·잎 글·aria-label) → 비교용 이름 — 공백 접기, 끝의 '읽지 않음 3'·'3 unread'·'선택됨' 같은 상태 꼬리를
    뗀다. 끝 숫자만은 떼지 않는다('2025'·'과제 3' 은 폴더 이름이다 — 읽지 않은 수는 JS 가 따로 뺀다)."""
    t = re.sub(r"\s+", " ", str(s or "")).strip()
    for _ in range(3):
        u = _FOLDER_TAIL.sub("", t).strip(" ,，")
        if not u or u == t:
            break
        t = u
    return t[:120]


def folder_kind(name, wk="", top=True):
    """폴더 → 종류: inbox · sent · archive · 제외(SKIP_KINDS — deleted·junk·drafts·outbox·conv·rss·sync·notes·search·scheduled)
    · ''(사람이 만든 폴더). wk(data-folder-name — 잘 알려진 폴더 이름)가 있으면 그것, 없으면 이름(여러 언어 — top 일 때만)."""
    w = re.sub(r"[^a-z]", "", str(wk or "").lower())
    if w in WK_KIND:
        return WK_KIND[w]
    if not top:
        return ""
    n = folder_name(name).lower()
    for kind, words in FOLDER_WORDS:
        if n in words:
            return kind
    return ""


def label_kind(s):
    """사서함 머리·나무 이름 → 'fav' · 'group' · 'shared' · 'arch'(온라인 보관 사서함) · ''(사서함일 수 있음)."""
    t = folder_name(s)
    if FAV_RX.match(t):
        return "fav"
    if GROUP_RX.match(t):
        return "group"
    if SHARED_RX.match(t):
        return "shared"
    if ARCH_MB_RX.search(t):
        return "arch"
    return ""


def tree_nodes(items):
    """JS owa_tree(read) 의 항목 사실 [{i, t 나무 순번, lvl aria-level, par DOM 조상 항목 순번, n 이름, al aria-label, wk
    data-folder-name, ex 펼침 1·0·-1(속성 없음), sel, v}] → 노드 [{i, t, lvl, name, raw, wk, ex, sel, v, par, kids}](화면 순서).
    부모는 DOM 조상 항목(par) → 없으면 같은 나무의 앞선 항목 중 aria-level 이 작은 가장 가까운 것(OWA 폴더 창은 하위 묶음이
    머리 항목의 형제로 그려져 DOM 만으로는 부모를 모를 수 있다). raw = JS 가 낸 이름 그대로(누르기 직전 같은 항목인지 맞춘다)."""
    nodes, src = [], {}
    for it in items or ():
        if not isinstance(it, dict):
            continue
        k = len(nodes)
        src[_int(it.get("i"), k)] = k
        raw = str(it.get("n") or "")[:120]
        nodes.append({"i": k, "t": _int(it.get("t"), -1), "lvl": max(0, _int(it.get("lvl"))), "dp": _int(it.get("par"), -1),
                      "raw": raw, "name": folder_name(raw or it.get("al")), "wk": str(it.get("wk") or "")[:40].lower(),
                      "ex": _int(it.get("ex"), -1), "sel": 1 if _int(it.get("sel")) else 0, "v": 1 if _int(it.get("v"), 1) else 0,
                      "par": -1, "kids": []})
    for n in nodes:
        p = src.get(n["dp"], -1) if n["dp"] >= 0 else -1
        if p < 0 and n["lvl"] > 1:
            for m in reversed(nodes[:n["i"]]):
                if m["t"] == n["t"] and 0 < m["lvl"] < n["lvl"]:
                    p = m["i"]
                    break
        n["par"] = p if 0 <= p < n["i"] else -1        # 앞선 항목만 — 고리가 생기지 않게
    for n in nodes:
        if n["par"] >= 0:
            nodes[n["par"]]["kids"].append(n["i"])
    return nodes


def _tree_labels(trees):
    return {k: label_kind(t.get("al")) for k, t in enumerate(trees or ()) if isinstance(t, dict)}


def pick_mailbox(nodes, trees=()):
    """폴더 창 노드 → (기본 사서함 범위 {kind 'root'|'tree', root, tree, top[맨 위 폴더 순번], score} | None, 사유 ''·'none'·'nomb').
    후보는 즐겨찾기·그룹·나와 공유·온라인 보관(머리 이름·나무 aria-label)이 아닌 ① 머리 항목 — 하위에 받은 편지함이 있음 ② 나무 —
    머리 없이 맨 위 폴더에 받은 편지함이 있음. 고르기: 맨 위 시스템 폴더 종류 수(사서함은 받은·보낸·지운·정크·임시… — 이름 표시가
    없는 즐겨찾기는 두세 개) → 받은 편지함이 선택된 쪽 → 화면 순서(기본 사서함이 공유·보관 사서함보다 위에 그려진다)."""
    if not nodes:
        return None, "none"
    tlab = _tree_labels(trees)
    roots = [n for n in nodes if n["par"] < 0]
    cands = []

    def add(kind, root, tree, top):
        kinds = [folder_kind(nodes[k]["name"], nodes[k]["wk"]) for k in top]
        if "inbox" not in kinds:
            return
        sel = any(nodes[k]["sel"] and kd == "inbox" for k, kd in zip(top, kinds, strict=True))
        score = len(set(kinds) & SYS_KINDS)
        cands.append(((score, 1 if sel else 0, -min(top)),
                      {"kind": kind, "root": root, "tree": tree, "top": list(top), "score": score}))
    for r in roots:
        if tlab.get(r["t"]) or label_kind(r["name"]) or not r["kids"]:
            continue
        add("root", r["i"], r["t"], r["kids"])
    by_t = {}
    for r in roots:
        by_t.setdefault(r["t"], []).append(r["i"])
    for t, top in by_t.items():
        if tlab.get(t):
            continue
        top = [i for i in top if not label_kind(nodes[i]["name"])]
        if top:
            add("tree", -1, t, top)
    if not cands:
        return None, "nomb"
    return max(cands, key=lambda c: c[0])[1], ""


def open_roots(nodes, trees=()):
    """접힌 머리 항목(즐겨찾기·그룹·나와 공유·온라인 보관이 아닌 것)의 순번 — 펼쳐야 기본 사서함의 폴더가 그려진다(화면 순서)."""
    tlab = _tree_labels(trees)
    return [n["i"] for n in nodes if n["par"] < 0 and n["ex"] == 0 and not tlab.get(n["t"]) and not label_kind(n["name"])]


def plan_folders(nodes, scope, skip=()):
    """기본 사서함 범위 → {"extra": [{i, box, kind, depth}](화면 순서 — 읽을 폴더), "expand": [i …](접힌 폴더 — 제외 폴더는 빼고
    받은·보낸 편지함은 넣는다), "sys": 제외한 시스템 폴더 수(그 하위 포함), "user": 설정(owaExtraFolderSkip — 이름 일부, 대소문자
    무시)으로 뺀 수(그 하위 포함)}. 받은·보낸 편지함 자신은 주소로 이미 읽으므로 넣지 않는다.
    box: 보낸 편지함의 하위는 sent, 그 밖(받은 편지함 하위·보관·사람이 만든 폴더)은 inbox — COM 수집기(OutlookCommon
    Get-MailFolderList)와 같다."""
    us = [str(x).strip().lower() for x in skip or () if str(x or "").strip()]
    out = {"extra": [], "expand": [], "sys": 0, "user": 0}

    def size(i, d=0):
        return 1 + (sum(size(k, d + 1) for k in nodes[i]["kids"]) if d < 40 else 0)

    def walk(i, box, top, depth):
        n = nodes[i]
        kind = folder_kind(n["name"], n["wk"], top)
        if kind in SKIP_KINDS:
            out["sys"] += size(i)
            return
        if us and any(u in n["name"].lower() for u in us):
            out["user"] += size(i)
            return
        if kind == "sent":
            box = "sent"
        if kind not in ("inbox", "sent"):
            out["extra"].append({"i": i, "box": box, "kind": kind or "user", "depth": depth})
        if n["ex"] == 0:
            out["expand"].append(i)
        if depth < 40:
            for k in n["kids"]:
                walk(k, box, False, depth + 1)
    for i in (scope or {}).get("top") or ():
        walk(i, "inbox", True, 0)
    return out


def node_key(nodes, i, trees=()):
    """화면이 다시 그려져도 같은 폴더를 찾는 열쇠 — (나무 aria-label, 머리부터 그 폴더까지의 이름…). 같은 부모 아래 같은 이름의
    폴더는 Outlook 이 만들지 않는다. 나무 이름은 머리 없는 나무 둘(즐겨찾기 나무·사서함 나무)의 같은 폴더 이름을 가른다."""
    names, k, guard = [], i, 0
    while 0 <= k < len(nodes) and guard < 64:
        names.append(nodes[k]["name"])
        k = nodes[k]["par"]
        guard += 1
    t = nodes[i]["t"]
    tl = str(trees[t].get("al") or "") if 0 <= t < len(trees or ()) and isinstance(trees[t], dict) else ""
    return (tl,) + tuple(reversed(names))


def find_node(nodes, key, trees=()):
    """node_key 로 노드 순번 | None."""
    for n in nodes:
        if n["name"] == key[-1] and node_key(nodes, n["i"], trees) == key:
            return n["i"]
    return None


def tree_shape(nodes, trees=(), scope=None):
    """폴더 창 구조 진단(글자 없음 — 수와 종류 기호만): 나무 수·항목 수·aria-level 있는 수·DOM 부모 있는 수·data-folder-name 있는
    수·선택 수·머리 종류(f 즐겨찾기 · g 그룹 · s 공유 · a 온라인 보관 · m 고른 사서함 · o 그 밖, 8개까지)·고른 범위 꼴(r·t)."""
    tlab = _tree_labels(trees)
    roots = [n for n in nodes if n["par"] < 0]
    code = {"fav": "f", "group": "g", "shared": "s", "arch": "a"}
    rk = ""
    for r in roots[:8]:
        lk = tlab.get(r["t"]) or label_kind(r["name"])
        if scope and ((scope["kind"] == "root" and scope["root"] == r["i"]) or (scope["kind"] == "tree" and scope["tree"] == r["t"])):
            rk += "m"
        else:
            rk += code.get(lk, "o")
    return {"trees": len(trees or ()), "items": len(nodes), "lvl": sum(1 for n in nodes if n["lvl"]),
            "dom": sum(1 for n in nodes if n["dp"] >= 0), "wk": sum(1 for n in nodes if n["wk"]),
            "sel": sum(1 for n in nodes if n["sel"]), "roots": len(roots), "rk": rk,
            "pick": (scope or {}).get("kind", "")[:1], "score": int((scope or {}).get("score") or 0)}


def cap_extra(day_st, rngs):
    """다른 폴더 하나의 판정 범위 [(from, to, st)] → 그 축의 {날짜: st} 를 **낮추기만** 한다. 그 폴더를 끝까지 읽지 못한 날
    (ok·zero_ok 가 아닌 날)의 ok·zero_ok 는 partial — 받은·보낸 편지함이 확인했어도 그 폴더의 메일이 빠졌을 수 있다(P4).
    올리지는 않는다(폴더 하나를 끝까지 읽었다고 받은 편지함이 못 읽은 날이 '읽음'이 되지 않는다). → 낮춘 날 수"""
    n = 0
    for a, b, st in rngs or ():
        if st in ("ok", "zero_ok"):
            continue
        d = a
        while d <= b:
            if day_st.get(d) in ("ok", "zero_ok"):
                day_st[d] = "partial"
                n += 1
            d += DAY
    return n


def url_kind(href):
    """폴더를 연 주소 → 잘 알려진 폴더 종류(/mail/deleteditems → 'deleted' · /mail/junkemail → 'junk' …) | ''. 받은·보낸 편지함은
    주소가 그 폴더 자신일 때만(/mail/inbox) — 하위 폴더는 폴더 ID 주소다. 계정 번호 마디(/mail/0/…)는 건너뛴다."""
    try:
        segs = [s.lower() for s in urlparse(str(href or "")).path.split("/") if s]
    except ValueError:
        return ""
    for k, s in enumerate(segs):
        if s == "mail":
            rest = [x for x in segs[k + 1:] if not x.isdigit()]
            kind = URL_KIND.get(rest[0], "") if rest else ""
            return "" if (kind in ("inbox", "sent") and len(rest) != 1) else kind
    return ""


def same_folder(sel, name):
    """목록 화면이 짚은 선택 폴더 이름(JS owa_list 의 sel — title 또는 글 40자)이 이 폴더인가 → True · False · None(모름).
    끝의 숫자·공백(읽지 않은 수가 이름 글에 붙어 온다)은 떼고 앞부분으로 맞춘다."""
    def norm(s):
        return re.sub(r"[\s\d,()]+$", "", re.sub(r"\s+", " ", str(s or "")).strip()).lower()[:40]
    a, b = norm(sel), norm(folder_name(name))
    if not a or not b:
        return None
    return a.startswith(b) or b.startswith(a)


def body_key(start, end, subject):
    """일정 본문 발췌 캐시 열쇠 'start|end|sha1(제목)[:12]' — 캐시 파일에 제목 원문을 남기지 않는다(LM28-OWA-5)."""
    s = re.sub(r"\s+", " ", str(subject or "")).strip()
    return f"{str(start or '')[:16]}|{str(end or '')[:16]}|{hashlib.sha1(s.encode('utf-8')).hexdigest()[:12]}"
