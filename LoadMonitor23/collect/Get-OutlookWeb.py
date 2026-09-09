# -*- coding: utf-8 -*-
"""
Get-OutlookWeb.py — Outlook 웹(outlook.office.com)을 전용 Edge 프로필로 열어 메일·일정을 읽는다 (폴백).

Outlook 의 '버전'과 무관한 경로다: 클래식/새 Outlook/2016 마법사/COM 미등록 어느 PC 든, Copilot 에
쓰는 전용 Edge 프로필(data\\copilot_profile)에 회사 계정으로 한 번 로그인해 두면 동작한다. Copilot 처럼
LLM 을 거치지 않으므로 지어낸 행이 없고, 데이터는 PC 밖으로 나가지 않는다(브라우저가 내 사서함을 보여주는
것을 읽을 뿐).

  python collect\\Get-OutlookWeb.py --from 2026-06-01 --to 2026-06-30 [--only mail|cal] [--force]

출력: data\\outlook\\mail.csv      (box,time,sender,subject,conversation,rcv,time_precision)   ← COM 스키마 + 정밀도 열
                                  time_precision: minute(시각 해석) | date(날짜만 보여 12:00 으로 둔 행 — 시간 근거로 쓰지 말 것)
      data\\outlook\\calendar.csv  (start,end,all_day,busy_status,subject,categories,location,response,meeting_status)
                                  ※ response/meeting_status 는 COM 수집기(Get-OutlookData.ps1)만 채운다 — 여기선 빈값
                                  ※ 여러 날에 걸친 일정(휴가·출장·워크숍)은 start~end 한 행(첫날~마지막날) — extract 가 일자로 전개한다
종료 코드: 0 저장(또는 이미 자료 있어 생략) / 1 아무것도 못 읽음 / 2 로그인 필요(전용 Edge 창에서 1회) / 3 드라이버 불가

화면 구조는 Microsoft 가 바꿀 수 있어 '역할(role)·aria-label·title' 같은 접근성 속성만 의지하고, 무엇을 몇 개
인식했는지 로그에 남긴다(회사 PC 의 원문을 밖으로 보낼 수 없으므로 진단은 로그 숫자로 한다).
발신/수신 구분: 받은 편지함·보낸 편지함 폴더 URL 을 따로 열어 슬라이스마다 검색하고(폴더가 곧 box), 화면에
폴더명 조각('보낸 편지함')이 있으면 그것을 우선한다 — 제목·미리보기의 영어 단어(presentation·consent·
'Sent from my iPhone')로 발신을 판정하던 부분 문자열 규칙은 폐기(감사 outlook-5).
시험용: LM_OWA_FAKE=<json> 이면 브라우저 없이 그 파일의 항목을 화면 대신 쓴다.
        mail: {"YYYY-MM": [item…]} (받은 편지함 슬라이스) 또는 {"YYYY-MM": {"inbox": [...], "sent": [...]}}
"""
import hashlib
import importlib.util
import io
import json
import os
import re
import sys
import time
from datetime import date, datetime, timedelta
from urllib.parse import quote

if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, errors="replace", encoding=(
        (sys.stdout.encoding or "utf-8") if sys.stdout.isatty() else "utf-8"))  # 콘솔(bat)=콘솔 코드페이지 · 파이프(UI)=utf-8
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "data", "outlook")
MAIL_HDR = "box,time,sender,subject,conversation,rcv,time_precision"
CAL_HDR = "start,end,all_day,busy_status,subject,categories,location,response,meeting_status"
MAIL_URL = "https://outlook.office.com/mail/"
# 폴더별 슬라이스 — 폴더 URL 이 곧 box 다(검색 범위가 '현재 폴더'인 OWA). 화면에 폴더명 조각이 있으면 그쪽이 우선.
MAIL_FOLDERS = (("inbox", MAIL_URL + "inbox"), ("sent", MAIL_URL + "sentitems"))
CAL_URL = "https://outlook.office.com/calendar/view/week"
HOSTS = ("outlook.office.com", "outlook.cloud.microsoft", "outlook.office365.com", "outlook.live.com")
MAX_EVENT_DAYS = 120            # 다일 일정으로 인정하는 최대 길이 — 그 이상은 날짜 오독으로 보고 첫 날짜만 쓴다


def arg(flag, d=""):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else d


def log(msg):
    print("[outlook-web] " + msg)


# ── 날짜·시각 해석 (표기 형식 무관) ─────────────────────────────────────────────
AM_WORDS = ("오전", "AM", "A.M.", "午前", "上午", "VORM.")
PM_WORDS = ("오후", "PM", "P.M.", "午後", "下午", "NACHM.")
DESIG = r"(?:오전|오후|AM|PM|am|pm|a\.m\.|p\.m\.|A\.M\.|P\.M\.|午前|午後|上午|下午|vorm\.|nachm\.)"
RE_TIME = re.compile(r"(?:(" + DESIG + r")\s*)?(?<!\d)(\d{1,2})[:.](\d{2})(?!\d)(?:\s*(" + DESIG + r"))?")
MON_EN = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
# 구분자는 짝이 맞아야 한다('2026년 6월 1일' · '2026. 6. 1.' · '2026-06-01') — '10.06.2026 - 12.06.2026' 의
# '2026 - 12.06' 이 연월일로 읽혀 다일 일정이 반년짜리가 되지 않게(_ymd 가 검사)
RE_YMD = re.compile(r"(\d{4})\s*([년.\-/])\s*(\d{1,2})\s*([월.\-/])\s*(\d{1,2})\s*일?")


def _ymd(m):
    """RE_YMD 매치 → date 또는 None (구분자 불일치·무효 날짜)"""
    y, s1, mo, s2, dd = m.groups()
    if not ((s1 == "년" and s2 == "월") or (s1 == s2 and s1 != "년")):
        return None
    try:
        return date(int(y), int(mo), int(dd))
    except ValueError:
        return None
RE_MDY = re.compile(r"(?<!\d)(\d{1,2})\s*[/.\-]\s*(\d{1,2})\s*[/.\-]\s*(\d{4})(?!\d)")
RE_MONEN = re.compile(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s*(\d{4})?", re.I)
RE_DMONEN = re.compile(r"(?<!\d)(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?,?\s*(\d{4})?", re.I)
RE_MD = re.compile(r"(?<![\d/])(\d{1,2})\s*[/.]\s*(\d{1,2})(?![\d/])")
RE_MD_KO = re.compile(r"(\d{1,2})\s*[월月]\s*(\d{1,2})\s*[일日]")


def _hhmm(m):
    h = int(m.group(2))
    mm = int(m.group(3))
    ap = (m.group(1) or m.group(4) or "").upper()
    if ap in PM_WORDS and h < 12:
        h += 12
    if ap in AM_WORDS and h == 12:
        h = 0
    if h > 23 or mm > 59:
        return None
    return h, mm


def find_times(text):
    """문자열의 모든 시각 → [(h, m)] (표기 무관). 날짜 조각(10.06.2026 / 2026. 6. 10.)은 먼저 지운다 —
    '10.06' 이 10시 06분으로 읽히지 않게."""
    t = RE_MDY.sub(" ", text or "")
    t = RE_YMD.sub(" ", t)
    t = re.sub(r"(?<!\d)\d{1,2}\.\d{1,2}\.(?!\d)", " ", t)     # 독일식 '10.06.' (일.월.) 도 시각이 아니다
    out = []
    for m in RE_TIME.finditer(t):
        hm = _hhmm(m)
        if hm:
            out.append(hm)
    return out


def find_date(text, hint_d0=None, hint_d1=None):
    """문자열의 날짜 → date 또는 None. 연도 없는 표기는 힌트 기간(검색한 달)으로 연도·순서를 정한다."""
    t = text or ""
    for m in RE_YMD.finditer(t):
        d = _ymd(m)
        if d:
            return d
    m = RE_MDY.search(t)
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        for mo, dd in ((a, b), (b, a)):          # 월/일/연 (미국) 또는 일/월/연 (유럽) — 기간 안에 드는 쪽
            try:
                d = date(y, mo, dd)
            except ValueError:
                continue
            if not hint_d0 or hint_d0 <= d <= hint_d1:
                return d
        for mo, dd in ((a, b), (b, a)):
            try:
                return date(y, mo, dd)
            except ValueError:
                continue
    m = RE_MONEN.search(t) or None
    if m:
        mo = MON_EN[m.group(1)[:3].lower()]
        dd = int(m.group(2))
        y = int(m.group(3)) if m.group(3) else None
        return _with_year(mo, dd, y, hint_d0, hint_d1)
    m = RE_DMONEN.search(t)
    if m:
        mo = MON_EN[m.group(2)[:3].lower()]
        dd = int(m.group(1))
        y = int(m.group(3)) if m.group(3) else None
        return _with_year(mo, dd, y, hint_d0, hint_d1)
    m = RE_MD_KO.search(t)
    if m:
        return _with_year(int(m.group(1)), int(m.group(2)), None, hint_d0, hint_d1)
    m = RE_MD.search(t)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        for mo, dd in ((a, b), (b, a)):
            d = _with_year(mo, dd, None, hint_d0, hint_d1)
            if d and (not hint_d0 or hint_d0 <= d <= hint_d1):
                return d
        return _with_year(a, b, None, hint_d0, hint_d1) or _with_year(b, a, None, hint_d0, hint_d1)
    return None


def _with_year(mo, dd, y, d0, d1):
    if y:
        try:
            return date(y, mo, dd)
        except ValueError:
            return None
    years = []
    if d0:
        years = sorted({d0.year, d1.year})
    years += [date.today().year, date.today().year - 1]
    for yy in years:
        try:
            d = date(yy, mo, dd)
        except ValueError:
            continue
        if not d0 or d0 <= d <= d1:
            return d
    try:
        return date(years[0], mo, dd)
    except (ValueError, IndexError):
        return None


def _safe_date(y, mo, dd):
    try:
        return date(y, mo, dd)
    except ValueError:
        return None


def _mdy_date(a, b, y, d0, d1):
    """월/일/연(미국) 또는 일/월/연(유럽) — 힌트 기간 안에 드는 쪽, 없으면 유효한 첫 해석"""
    for mo, dd in ((a, b), (b, a)):
        d = _safe_date(y, mo, dd)
        if d and (not d0 or d0 <= d <= d1):
            return d
    for mo, dd in ((a, b), (b, a)):
        d = _safe_date(y, mo, dd)
        if d:
            return d
    return None


def _md_date(a, b, d0, d1):
    for mo, dd in ((a, b), (b, a)):
        d = _with_year(mo, dd, None, d0, d1)
        if d and (not d0 or d0 <= d <= d1):
            return d
    return _with_year(a, b, None, d0, d1) or _with_year(b, a, None, d0, d1)


def _first_date_pos(text):
    """문자열에서 날짜 조각이 처음 나오는 위치(없으면 None) — 라벨의 '제목 | 날짜·시각' 경계를 찾는 데 쓴다"""
    pos = [m.start() for rx in (RE_YMD, RE_MDY, RE_MONEN, RE_DMONEN, RE_MD_KO) for m in [rx.search(text or "")] if m]
    return min(pos) if pos else None


def find_dates(text, hint_d0=None, hint_d1=None):
    """문자열 안의 **모든** 날짜를 등장 순서대로 → [date]. 우선순위는 find_date 와 같다(YMD → MDY → 영문 월 →
    한국어 월일 → M/D). 잡은 조각은 같은 길이의 공백으로 지워 '2026년 6월 1일' 의 '6월 1일' 이 다시 잡히지 않는다.
    다일 일정('6월 1일 ~ 6월 5일')을 첫날 하루로 접던 결함(감사 outlook-6)의 재료."""
    t = text or ""
    found = []

    def _take(rx, fn):
        nonlocal t

        def _sub(m):
            d = fn(m)
            if d:
                found.append((m.start(), d))
                return " " * len(m.group(0))
            return m.group(0)
        t = rx.sub(_sub, t)

    _take(RE_YMD, _ymd)
    _take(RE_MDY, lambda m: _mdy_date(int(m.group(1)), int(m.group(2)), int(m.group(3)), hint_d0, hint_d1))
    _take(RE_MONEN, lambda m: _with_year(MON_EN[m.group(1)[:3].lower()], int(m.group(2)),
                                         int(m.group(3)) if m.group(3) else None, hint_d0, hint_d1))
    _take(RE_DMONEN, lambda m: _with_year(MON_EN[m.group(2)[:3].lower()], int(m.group(1)),
                                          int(m.group(3)) if m.group(3) else None, hint_d0, hint_d1))
    _take(RE_MD_KO, lambda m: _with_year(int(m.group(1)), int(m.group(2)), None, hint_d0, hint_d1))
    _take(RE_MD, lambda m: _md_date(int(m.group(1)), int(m.group(2)), hint_d0, hint_d1))
    found.sort(key=lambda x: x[0])
    return [d for _, d in found]


STATUS_WORDS = ("읽지 않음", "읽음", "unread", "read", "첨부 파일", "첨부", "attachment", "attachments",
                "플래그", "flagged", "flag", "중요", "important", "선택됨", "selected", "대화", "conversation",
                "답장함", "replied", "전달함", "forwarded", "초안", "draft", "상세 정보", "details")
# 폴더명은 화면의 '독립 조각'(쉼표·구분점으로 나뉜 leaf) 과 **완전 일치**로만 본다 — 단독 'sent' 는 제목·미리보기의
# presentation/consent/'Sent from my iPhone' 에 걸려 수신을 발신(능동 신호)으로 둔갑시켰다(감사 outlook-5).
SENT_WORDS = ("보낸 편지함", "보낸 항목", "보낸 메일함", "sent items", "sent mail", "sent messages")
INBOX_WORDS = ("받은 편지함", "받은 메일함", "inbox")
CC_WORDS = ("참조", "cc")                      # 수신 슬라이스에서 '참조' 헤더 조각이 보이면 rcv=cc
SKIP_FOLDER = ("지운 편지함", "삭제된 항목", "삭제된 편지함", "deleted items", "trash", "정크", "정크 메일", "junk",
               "junk email", "junk e-mail", "spam", "스팸", "임시 보관함", "drafts", "보낼 편지함", "outbox")


def _folder_tokens(pool):
    """화면 문자열들을 쉼표·세로줄·가운뎃점 단위의 독립 조각으로 → 소문자 토큰 목록(폴더명·상태어 판정용)"""
    toks = []
    for p in pool:
        for x in re.split(r"[,，|·\n]\s*", p or ""):
            x = x.strip().lower().rstrip(":：").strip()
            if x:
                toks.append(x)
    return toks


def _conv_token(conv):
    """storeMailSubject=false 일 때 conversation 열에 남기는 대체값 — 원문 대신 짧은 해시.
    extract 의 '회신 이력'(발신 conversation ∩ 수신 conversation) 판정은 문자열 동일성만 보므로 그대로 동작한다."""
    s = re.sub(r"\s+", " ", str(conv or "")).strip().lower()
    return "#" + hashlib.sha1(s.encode("utf-8")).hexdigest()[:10] if s else ""


def parse_mail_item(item, d0, d1, folder=""):
    """화면 항목(aria-label·title·leaf texts) → [box,time,sender,subject,conversation,rcv,time_precision] 또는 None
    folder: 이 항목을 읽은 폴더 슬라이스('inbox'|'sent'|'') — 화면에 폴더명 조각이 없을 때의 box."""
    label = item.get("label") or ""
    titles = [t for t in (item.get("titles") or []) if t]
    texts = [t for t in (item.get("texts") or []) if t]
    pool = titles + [label] + texts
    # 시각·날짜: 전체 날짜가 든 title 을 우선(OWA 는 시각 요소의 title 에 전체 날짜를 둔다)
    when = None
    precision = "minute"
    for cand in pool:
        d = find_date(cand, d0, d1)
        ts = find_times(cand)
        if d and ts:
            when = (d, ts[0])
            break
    if not when:
        d = None
        ts = None
        for cand in pool:
            d = d or find_date(cand, d0, d1)
            ts = ts or (find_times(cand) or None)
        if d and ts:
            when = (d, ts[0])
        elif d:
            when = (d, (12, 0))             # 날짜만 보이는 항목 — 00:00 은 '새벽 산출물' 이 된다. 주간 중앙 + 정밀도 표시
            precision = "date"
    if not when:
        return None
    t = f"{when[0].isoformat()} {when[1][0]:02d}:{when[1][1]:02d}"
    toks = _folder_tokens(pool)
    if any(x in SKIP_FOLDER for x in toks):
        return None
    if any(x in SENT_WORDS for x in toks):
        box = "sent"
    elif any(x in INBOX_WORDS for x in toks):
        box = "inbox"
    else:
        box = "sent" if folder == "sent" else "inbox"    # 폴더 조각이 없으면 읽은 폴더가 곧 box(없으면 보수적으로 수신)
    # 발신자·제목: 시각/날짜/상태어/폴더명이 아닌 짧은 leaf 텍스트의 첫째·둘째
    cands = []
    for x in texts:
        xl = x.lower().strip()
        if not xl or len(x) > 120:
            continue
        if find_times(x) or find_date(x, d0, d1):
            continue
        if xl in STATUS_WORDS or xl in SENT_WORDS or xl in INBOX_WORDS or xl in CC_WORDS or xl.rstrip(":：").strip() in CC_WORDS:
            continue
        if re.fullmatch(r"[\d\s.,:/\-]+", x):
            continue
        cands.append(x.strip())
    sender = cands[0] if cands else ""
    subject = cands[1] if len(cands) > 1 else ""
    if not subject and label:
        # aria-label 에서 상태어 제거 후 "보낸이, 제목, ..." 형태로 보완
        parts = [p.strip() for p in re.split(r"[,，]\s*", label) if p.strip()]
        parts = [p for p in parts if p.lower() not in STATUS_WORDS and p.lower() not in SENT_WORDS
                 and p.lower() not in INBOX_WORDS and not find_times(p) and not find_date(p, d0, d1)]
        if len(parts) >= 2:
            sender = sender or parts[0]
            subject = parts[1]
    conv = re.sub(r"^((RE|FW|FWD|답장|전달|회신)\s*:\s*)+", "", subject, flags=re.I)
    if box == "sent":
        rcv = ""
    else:
        # 수신 구분은 화면에 거의 없다 — '참조' 조각이 보일 때만 cc, 아니면 보수적으로 직접 수신
        rcv = "cc" if any(x in CC_WORDS for x in toks) else "to"
    return [box, t, sender, subject, conv, rcv, precision]


def parse_event(ev, d0, d1):
    """일정 요소(aria-label·texts) → [start,end,all_day,busy,subject,categories,location] 또는 None
    날짜가 2개 이상이면(다일 일정) start=첫 날짜(+첫 시각), end=마지막 날짜(+둘째 시각 또는 23:59) 한 행."""
    label = ev.get("label") or ""
    texts = [t for t in (ev.get("texts") or []) if t]
    pool = [label] + texts
    joined = " | ".join(pool)
    dates = []
    for cand in pool:
        dates = find_dates(cand, d0, d1)
        if dates:
            break
    if not dates:
        return None
    d_st, d_en = min(dates), max(dates)
    if (d_en - d_st).days > MAX_EVENT_DAYS:     # 주 보기 라벨에 넉 달짜리 일정은 없다 — 날짜 오독이면 첫 날짜만
        d_en = d_st
    multi = d_en > d_st
    # 시각은 날짜 뒤의 것을 우선한다 — OWA 라벨은 "이벤트: <제목>, <날짜> <시작> ~ <끝>" 꼴이라 제목 속의
    # '10:30 데일리 브리핑' 같은 숫자가 시작 시각으로 읽히지 않게. 날짜 뒤에 시각이 없으면 전체에서 찾는다.
    pos = _first_date_pos(label)
    ts = (find_times(label[pos:]) if pos is not None else []) or find_times(label) or find_times(joined)
    all_day = bool(re.search(r"종일|all[- ]day|終日|全天", joined, re.I))
    if len(ts) >= 2:
        st = datetime(d_st.year, d_st.month, d_st.day, ts[0][0], ts[0][1])
        en = datetime(d_en.year, d_en.month, d_en.day, ts[1][0], ts[1][1])
        if en <= st:
            en = en + timedelta(days=1) if en < st else st + timedelta(minutes=30)
        ad = "False"
    elif all_day or not ts:
        st = datetime(d_st.year, d_st.month, d_st.day, 0, 0)
        en = datetime(d_en.year, d_en.month, d_en.day, 23, 59)
        ad = "True"
        if not all_day and not ts:
            return None
    else:
        st = datetime(d_st.year, d_st.month, d_st.day, ts[0][0], ts[0][1])
        en = datetime(d_en.year, d_en.month, d_en.day, 23, 59) if multi else st + timedelta(minutes=30)
        ad = "False"
    # 제목: 날짜·시각·'이벤트:' 같은 접두를 뗀 첫 조각
    subj = ""
    for cand in ([label] + texts):
        c = RE_TIME.sub(" ", cand)
        c = RE_YMD.sub(" ", c)
        c = RE_MDY.sub(" ", c)
        c = RE_MONEN.sub(" ", c)
        c = RE_DMONEN.sub(" ", c)
        c = RE_MD_KO.sub(" ", c)
        c = re.sub(r"(?i)^\s*(이벤트|event|약속|appointment|회의|meeting)\s*[:：]\s*", "", c)
        c = re.sub(r"(?i)\b(월요일|화요일|수요일|목요일|금요일|토요일|일요일|monday|tuesday|wednesday|thursday|friday|saturday|sunday|mon|tue|wed|thu|fri|sat|sun)\b\.?,?", " ", c)
        c = re.sub(r"[~\-–—]\s*", " ", c)
        c = re.sub(r"\s{2,}", " ", c).strip(" ,.|")
        if len(c) >= 2:
            subj = c.split(",")[0].strip()[:120]
            break
    busy = "0" if re.search(r"한가함|free|available", joined, re.I) else ("1" if re.search(r"미정|tentative", joined, re.I) else "2")
    loc = ""
    m = re.search(r"(?:장소|location|위치)\s*[:：]\s*([^,|]+)", joined, re.I)
    if m:
        loc = m.group(1).strip()[:80]
    elif re.search(r"teams 모임|teams 회의|microsoft teams", joined, re.I):
        loc = "Teams 회의"
    return [st.strftime("%Y-%m-%d %H:%M"), en.strftime("%Y-%m-%d %H:%M"), ad, busy, subj, "", loc]


# ── 브라우저(CDP) ─────────────────────────────────────────────────────────────
JS_MAIL = r"""
(() => {
  const out = {href: location.href, n: 0, items: [], listboxes: 0, search: false};
  const sb = document.querySelector('#topSearchInput, input[role="searchbox"], [role="search"] input, input[aria-label*="검색"], input[aria-label*="Search"], input[placeholder*="검색"], input[placeholder*="Search"]');
  out.search = !!sb;
  let opts = [...document.querySelectorAll('[role="listbox"] [role="option"]')];
  out.listboxes = document.querySelectorAll('[role="listbox"]').length;
  if (!opts.length) opts = [...document.querySelectorAll('[role="option"]')];
  if (!opts.length) opts = [...document.querySelectorAll('[role="row"][aria-label], [data-convid], [data-item-id]')];
  out.n = opts.length;
  out.items = opts.slice(0, 600).map(o => ({
    key: (o.getAttribute("data-convid") || o.getAttribute("data-item-id") || o.id || "") + "|" + (o.getAttribute("aria-label") || "").slice(0, 80),
    label: o.getAttribute("aria-label") || "",
    titles: [...o.querySelectorAll("[title]")].map(x => x.getAttribute("title") || "").filter(Boolean).slice(0, 12),
    texts: [...o.querySelectorAll("span,div,a")].filter(x => x.childElementCount === 0).map(x => (x.textContent || "").trim()).filter(Boolean).slice(0, 24)
  }));
  return JSON.stringify(out);
})()
"""
JS_SCROLL = r"""
(() => {
  const lb = document.querySelector('[role="listbox"]') || document.querySelector('[role="option"]');
  if (!lb) return "no-list";
  let el = lb;
  for (let i = 0; i < 12 && el; i++) {
    if (el.scrollHeight > el.clientHeight + 20 && getComputedStyle(el).overflowY !== "visible") break;
    el = el.parentElement;
  }
  if (!el) return "no-scroller";
  const before = el.scrollTop;
  el.scrollTop = el.scrollTop + Math.max(200, el.clientHeight - 40);
  el.dispatchEvent(new Event("scroll", {bubbles: true}));
  return (el.scrollTop > before) ? "scrolled" : "end";
})()
"""
JS_CAL = r"""
(() => {
  const out = {href: location.href, n: 0, events: []};
  const cands = [...document.querySelectorAll('[role="main"] [aria-label], [role="grid"] [aria-label], [role="button"][aria-label], [role="listitem"][aria-label]')];
  const seen = new Set();
  for (const e of cands) {
    const l = e.getAttribute("aria-label") || "";
    if (!/\d{1,2}[:.]\d{2}|종일|all[- ]day|終日/i.test(l)) continue;
    if (!/\d/.test(l)) continue;
    const k = l.slice(0, 160);
    if (seen.has(k)) continue;
    seen.add(k);
    out.events.push({label: l, texts: [...e.querySelectorAll("span,div")].filter(x => x.childElementCount === 0).map(x => (x.textContent || "").trim()).filter(Boolean).slice(0, 10)});
    if (out.events.length >= 400) break;
  }
  out.n = out.events.length;
  return JSON.stringify(out);
})()
"""
JS_FOCUS_SEARCH = r"""
(() => {
  const sels = ['#topSearchInput', 'input[role="searchbox"]', '[role="search"] input', 'input[aria-label*="검색"]', 'input[aria-label*="Search"]', 'input[placeholder*="검색"]', 'input[placeholder*="Search"]', '[role="combobox"][aria-label*="검색"]', '[role="combobox"][aria-label*="Search"]'];
  const vis = el => { const r = el.getBoundingClientRect(); return r.width > 40 && r.height > 8; };
  for (const s of sels) { for (const c of document.querySelectorAll(s)) { if (vis(c)) { c.focus(); c.click(); window.__lm_sb = c; return "ok:" + s; } } }
  const btn = document.querySelector('button[aria-label*="검색"], button[aria-label*="Search"]');
  if (btn) { btn.click(); return "button"; }
  return "none";
})()
"""
JS_CLEAR_SEARCH = r"""
(() => { const el = window.__lm_sb; if (!el) return "none";
  el.focus(); try { el.select && el.select(); } catch (e) {}
  const d = Object.getOwnPropertyDescriptor(el.__proto__, 'value'); if (d && d.set) { d.set.call(el, ''); } else { el.value = ''; }
  el.dispatchEvent(new Event('input', {bubbles: true})); return "cleared"; })()
"""


class Browser:
    def __init__(self):
        spec = importlib.util.spec_from_file_location("_ca", os.path.join(ROOT, "tools", "copilot_auto.py"))
        self.ca = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.ca)
        self.cfg = self.ca.load_cfg()
        self.port = self.cfg["port"]
        self.cdp = None

    def start(self):
        if not self.ca.ensure_edge(self.cfg):
            return False
        tabs = [t for t in self.ca.http_json(self.port, "/json") if t.get("type") == "page"]
        ws = None
        for t in tabs:
            if any(h in (t.get("url") or "") for h in HOSTS):
                ws = t["webSocketDebuggerUrl"]
                break
        if not ws:
            for method in ("PUT", "GET"):
                try:
                    t = self.ca.http_json(self.port, "/json/new?" + quote(MAIL_URL, safe=""), method=method)
                    ws = t["webSocketDebuggerUrl"]
                    break
                except Exception:
                    continue
        if not ws:
            return False
        self.cdp = self.ca.CDP(ws)
        try:
            self.cdp.call("Page.enable")
        except Exception:
            pass
        return True

    def goto(self, url, wait=6.0):
        try:
            self.cdp.call("Page.navigate", {"url": url})
        except Exception:
            self.cdp.reconnect()
            self.cdp.call("Page.navigate", {"url": url})
        return self.wait_ready(wait)

    def href(self):
        try:
            return str(self.cdp.eval("location.href"))
        except Exception:
            return ""

    def wait_ready(self, settle=6.0, limit=75):
        """로드 완료 + 목록/로그인 판별 → 'login' | 'ok' | 'timeout'"""
        t0 = time.time()
        while time.time() - t0 < limit:
            time.sleep(1.0)
            h = self.href()
            if "login.microsoftonline" in h or "login.live.com" in h or "login.microsoft" in h:
                return "login"
            try:
                rs = self.cdp.eval("document.readyState")
                n = int(self.cdp.eval('document.querySelectorAll(\'[role="listbox"],[role="grid"],[role="main"]\').length') or 0)
            except Exception:
                rs, n = "", 0
            if rs == "complete" and n > 0:
                time.sleep(settle)
                h = self.href()
                if "login.microsoftonline" in h or "login.live.com" in h:
                    return "login"
                return "ok"
        return "timeout"

    def eval_json(self, js, timeout=40):
        r = self.cdp.eval(js, timeout=timeout)
        if isinstance(r, str):
            try:
                return json.loads(r)
            except ValueError:
                return {}
        return r or {}

    def search(self, query):
        how = str(self.cdp.eval(JS_FOCUS_SEARCH))
        if how == "none":
            return False
        time.sleep(0.8)
        if how == "button":
            str(self.cdp.eval(JS_FOCUS_SEARCH))
            time.sleep(0.6)
        self.cdp.eval(JS_CLEAR_SEARCH)
        try:
            self.cdp.call("Input.insertText", {"text": query})
        except Exception:
            return False
        time.sleep(0.4)
        self.ca.press_enter(self.cdp)
        time.sleep(5.0)
        return True

    def close(self):
        try:
            if self.cdp:
                self.cdp.close()
        except Exception:
            pass


# ── 수집 ─────────────────────────────────────────────────────────────────────
def months_of(d0, d1):
    outs = []
    cur = d0.replace(day=1)
    while cur <= d1:
        nxt = (cur.replace(day=28) + timedelta(days=4)).replace(day=1)
        s = max(cur, d0)
        e = min(nxt - timedelta(days=1), d1)
        outs.append((s, e))
        cur = nxt
    return outs


def _fake_mail_batch(fake, month_key, folder):
    """시험용 화면: 달별 항목이 목록이면 받은 편지함 슬라이스로, {"inbox":[…],"sent":[…]} 면 폴더별로 쓴다"""
    fm = (fake.get("mail") or {}).get(month_key, [])
    if isinstance(fm, dict):
        return list(fm.get(folder) or [])
    return list(fm) if folder == "inbox" else []


def collect_mail(br, d0, d1, fake=None):
    """달 × 폴더(받은 편지함 → 보낸 편지함) 슬라이스로 읽는다. box 는 (화면의 폴더명 조각) > (읽은 폴더) 순.
    검색 범위가 '모든 폴더'로 잡힌 OWA 라도 같은 항목(key)은 먼저 읽은 받은 편지함 슬라이스에 남으므로
    발신이 수신으로 격하될 뿐, 수신이 발신(능동 신호)이 되는 방향의 오류는 생기지 않는다."""
    rows, seen = [], set()
    diag = {"search": 0, "items": 0, "parsed": 0, "sent": 0, "cc": 0, "date_only": 0, "pages": 0, "sent_pass_new": 0}
    for s, e in months_of(d0, d1):
        mon_n = 0
        for folder, url in MAIL_FOLDERS:
            if fake is not None:
                batch = _fake_mail_batch(fake, s.strftime("%Y-%m"), folder)
                pages = [{"items": batch, "n": len(batch), "search": True}]
            else:
                st = br.goto(url)
                if st == "login":
                    return rows, "login", diag
                q = f"received>={s.isoformat()} received<={e.isoformat()}"
                ok = br.search(q)
                if ok:
                    diag["search"] += 1
                pages = []
                stall = 0
                # 화면에 새로 나온 것이 있는지는 이 슬라이스 전용 집합으로 본다 —
                # 행 중복 제거용 seen 과 같이 쓰면 두 번째 화면부터 newk 가 늘 비어
                # stall 이 오르지 않고 400회를 다 돌아 폴백 전체가 시간 초과된다(검증 확정).
                seen_scroll = set()
                for _ in range(400):
                    pg = br.eval_json(JS_MAIL)
                    pages.append(pg)
                    newk = {it.get("key") for it in pg.get("items", [])} - seen_scroll
                    seen_scroll |= newk
                    if not newk:
                        stall += 1
                    else:
                        stall = 0
                    if stall >= 3:
                        break
                    r = str(br.cdp.eval(JS_SCROLL))
                    if r in ("no-list", "end") and stall >= 1:
                        break
                    time.sleep(1.0)
                    if not ok:                  # 검색창을 못 찾았으면 폴더를 그냥 훑는다 — 기간 아래로 내려가면 멈춘다
                        olds = [parse_mail_item(it, s, e, folder) for it in pg.get("items", [])]
                        olds = [o for o in olds if o]
                        if olds and min(o[1][:10] for o in olds) < d0.isoformat():
                            break
            for pg in pages:
                diag["pages"] += 1
                for it in pg.get("items", []):
                    k = it.get("key") or json.dumps(it, ensure_ascii=False)[:200]
                    if k in seen:
                        continue
                    seen.add(k)
                    diag["items"] += 1
                    if folder == "sent":
                        diag["sent_pass_new"] += 1
                    r = parse_mail_item(it, s, e, folder)
                    if not r:
                        continue
                    if not (d0.isoformat() <= r[1][:10] <= d1.isoformat()):
                        continue
                    diag["parsed"] += 1
                    if r[0] == "sent":
                        diag["sent"] += 1
                    elif r[5] == "cc":
                        diag["cc"] += 1
                    if r[6] == "date":
                        diag["date_only"] += 1
                    rows.append(r)
                    mon_n += 1
        log(f"메일 {s.strftime('%Y-%m')}: 항목 {diag['items']}개 중 해석 {mon_n}건 누적 {len(rows)}건"
            f" (보낸 편지함 슬라이스 신규 {diag['sent_pass_new']}개)")
    rows.sort(key=lambda r: r[1])
    return rows, ("ok" if rows else "empty"), diag


def collect_cal(br, d0, d1, fake=None):
    rows, seen = [], set()
    diag = {"weeks": 0, "events": 0, "parsed": 0}
    cur = d0 - timedelta(days=d0.weekday())
    while cur <= d1:
        diag["weeks"] += 1
        if fake is not None:
            pg = {"events": fake.get("cal", {}).get(cur.isoformat(), [])}
        else:
            url = f"{CAL_URL}/{cur.year}/{cur.month}/{cur.day}"
            st = br.goto(url, wait=5.0)
            if st == "login":
                return rows, "login", diag
            pg = br.eval_json(JS_CAL)
        wk_end = cur + timedelta(days=6)
        for ev in pg.get("events", []):
            diag["events"] += 1
            r = parse_event(ev, cur, wk_end)
            if not r:
                continue
            # 기간과 겹치는 일정만 — 다일 일정은 기간 전에 시작해 기간 안에서 끝나도 남긴다(extract 가 일자로 전개)
            if r[1][:10] < d0.isoformat() or r[0][:10] > d1.isoformat():
                continue
            k = (r[0], r[1], r[4])
            if k in seen:                    # 여러 주에 걸친 막대는 주마다 같은 행으로 읽힌다 — 한 번만
                continue
            seen.add(k)
            diag["parsed"] += 1
            if r[0][:10] != r[1][:10]:
                diag["multi_day"] = diag.get("multi_day", 0) + 1
            rows.append(r)
        cur += timedelta(days=7)
    rows.sort(key=lambda r: r[0])
    log(f"일정: {diag['weeks']}주 · 요소 {diag['events']}개 중 해석 {len(rows)}건 (다일 {diag.get('multi_day', 0)}건)")
    return rows, ("ok" if rows else "empty"), diag


def _esc(s):
    s = re.sub(r"[\r\n]+", " ", str(s or ""))
    return '"' + s.replace('"', '""') + '"' if ("," in s or '"' in s) else s


def _has_data(path):
    try:
        with open(path, encoding="utf-8-sig") as f:
            return sum(1 for ln in f if ln.strip()) > 1
    except OSError:
        return False


def _save(kind, rows, store_subject):
    dst = os.path.join(OUT_DIR, "mail.csv" if kind == "mail" else "calendar.csv")
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(dst, "w", encoding="utf-8-sig", newline="") as f:
        f.write((MAIL_HDR if kind == "mail" else CAL_HDR) + "\n")
        hdr_n = (MAIL_HDR if kind == "mail" else CAL_HDR).count(",") + 1
        for r in rows:
            r = list(r)
            r += [""] * (hdr_n - len(r))     # 새 열(response,meeting_status)은 빈값 — 열 수가 모자라면 extract._read 가 행을 버린다
            if not store_subject:            # 제목을 남기지 않는다 — conversation 도 원문 대신 해시(회신 이력 판정만 유지)
                if kind == "mail":
                    r[3] = ""
                    r[4] = _conv_token(r[4])
                else:
                    r[4] = ""
            f.write(",".join(_esc(c) for c in r) + "\n")
    return dst


def main():
    d0s = arg("--from") or (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
    d1s = arg("--to") or datetime.now().strftime("%Y-%m-%d")
    d0, d1 = date.fromisoformat(d0s), date.fromisoformat(d1s)
    only = arg("--only")
    force = "--force" in sys.argv
    try:
        cfg = json.load(open(os.path.join(ROOT, "config", "config.json"), encoding="utf-8-sig"))
    except (OSError, ValueError):
        cfg = {}
    store_subject = bool(cfg.get("storeMailSubject", True))
    todo = []
    for kind, fn in (("mail", "mail.csv"), ("cal", "calendar.csv")):
        if only and kind != only:
            continue
        p = os.path.join(OUT_DIR, fn)
        if _has_data(p) and not force:
            log(f"{fn} 에 이미 자료가 있어 건너뜀 (덮어쓰려면 --force)")
        else:
            todo.append(kind)
    if not todo:
        return 0
    fake = None
    fk = os.environ.get("LM_OWA_FAKE", "")
    if fk:
        try:
            fake = json.load(open(fk, encoding="utf-8-sig"))
        except (OSError, ValueError):
            fake = {}
        if fake.get("login"):
            log("로그인 필요(시험용 가짜)")
            return 2
    br = None
    if fake is None:
        if os.environ.get("LM_NO_BROWSER"):
            log("LM_NO_BROWSER 설정 — 브라우저를 띄우지 않습니다(시험용)")
            return 3
        try:
            br = Browser()
            started = br.start()
        except Exception as e:              # 드라이버 모듈 부재·포트 충돌 등 — 사슬의 다음 경로로 넘긴다
            log(f"드라이버를 쓸 수 없습니다({type(e).__name__}: {str(e)[:80]}) — 다음 대체 경로로")
            return 3
        if not started:
            log("전용 Edge(디버그 포트)를 띄우지 못했습니다 — Edge 설치·config.copilotAuto.port 확인")
            return 3
        st = br.goto(MAIL_URL)
        if st == "login":
            log("로그인 필요 — 지금 열린 전용 Edge 창의 Outlook 탭에서 회사 계정을 한 번 선택/로그인하세요 (Copilot 과 같은 창, 1회).")
            log("           로그인 뒤 [분석 실행] 또는 대시보드 [Outlook 웹 읽기]를 다시 누르면 이어서 읽습니다.")
            return 2
        if st == "timeout":
            log("Outlook 웹 화면이 뜨지 않았습니다(네트워크·차단?) — 전용 Edge 창에서 outlook.office.com 이 열리는지 확인하세요.")
            return 1
    total = 0
    status = {}
    counts = {}
    for kind in todo:
        if kind == "mail":
            rows, stt, diag = collect_mail(br, d0, d1, fake)
            log(f"메일 진단: 검색 {diag['search']}회 · 화면 항목 {diag['items']}개 · 해석 {diag['parsed']}건"
                f"(보낸 {diag['sent']} · 참조 {diag['cc']} · 날짜만 {diag['date_only']}) · 페이지 {diag['pages']}")
        else:
            rows, stt, diag = collect_cal(br, d0, d1, fake)
        status[kind] = stt
        if stt == "login":
            log("로그인 필요 — 전용 Edge 창의 Outlook 탭에서 회사 계정을 한 번 선택하세요.")
            if br:
                br.close()
            return 2
        if rows:
            _save(kind, rows, store_subject)
            total += len(rows)
            counts[kind] = len(rows)
            log(f"{kind}: {len(rows)}건 저장")
        else:
            log(f"{kind}: 읽은 것이 없음 — 화면 항목은 보이는데 해석이 0이면 표기 형식 문제(로그의 '항목/해석' 수 참고)")
    if br:
        br.close()
    if total:
        try:
            src = {"source": "owa", "when": datetime.now().strftime("%Y-%m-%d %H:%M"),
                   "kinds": todo, "rows": total, "mail": counts.get("mail", 0), "calendar": counts.get("cal", 0),
                   "me": [],                           # 내 주소는 화면에 없다 — rcv 는 to/cc(참조 조각) 만
                   "warnings": []}
            if "cal" in todo:
                # 주 보기는 반복 회의를 회차마다 그린다 — 색인 폴백(마스터 1건)과 달리 일정이 완전하다
                src["calendar_complete"] = bool(counts.get("cal"))
                src["calendar_recurring_masters"] = 0
            with open(os.path.join(OUT_DIR, "mail_source.json"), "w", encoding="utf-8") as f:
                json.dump(src, f, ensure_ascii=False)
            if "mail" in todo and _has_data(os.path.join(OUT_DIR, "mail.csv")):
                try:
                    os.remove(os.path.join(OUT_DIR, "outlook_skip.json"))
                except OSError:
                    pass
        except OSError:
            pass
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
