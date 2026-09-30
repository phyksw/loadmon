# -*- coding: utf-8 -*-
"""
Get-OutlookWeb.py — Outlook 웹(outlook.office.com)을 전용 Edge 프로필로 열어 메일·일정을 읽는다 (폴백).

클래식 Outlook COM과 별도로 전용 Edge 프로필의 로그인된 웹 화면을 읽는다.
OWA 화면 구조·회사 정책에 따라 지원 여부와 관측 범위가 달라지며 전체 사서함 완료를 보장하지 않는다.
LLM이나 비공개 메일 API를 사용하지 않는다.

  python collect\\Get-OutlookWeb.py --from 2026-06-01 --to 2026-06-30 [--only mail|cal] [--force]

출력: data\\outlook\\mail.csv      (box,time,sender,subject,conversation,rcv,time_precision)   ← COM 스키마 + 정밀도 열
                                  time_precision: minute(시각 해석) | date(날짜만 보여 12:00 으로 둔 행 — 시간 근거로 쓰지 말 것)
      data\\outlook\\calendar.csv  (start,end,all_day,busy_status,subject,categories,location,response,meeting_status)
                                  ※ response/meeting_status 는 COM 수집기(Get-OutlookData.ps1)만 채운다 — 여기선 빈값
                                  ※ 여러 날에 걸친 일정(휴가·출장·워크숍)은 start~end 한 행(첫날~마지막날) — extract 가 일자로 전개한다
종료 코드: 0 관측 저장 / 1 아무것도 못 읽음 / 2 로그인 필요(전용 Edge 창에서 1회) / 3 브라우저 시작 불가

화면 구조는 Microsoft 가 바꿀 수 있어 '역할(role)·aria-label·title' 같은 접근성 속성만 의지하고, 무엇을 몇 개
인식했는지 로그에 남긴다(회사 PC 의 원문을 밖으로 보낼 수 없으므로 진단은 로그 숫자로 한다).
발신/수신 구분: 받은/보낸 폴더에서 날짜 검색하되 검색 범위가 그대로인지 확인할 수 없으므로,
항목의 독립 폴더명 조각으로 증명되지 않은 방향은 unknown이다. 제목·미리보기의 부분 단어로 판정하지 않는다.
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
from urllib.parse import quote, urlsplit

if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, errors="replace", encoding=(
        (sys.stdout.encoding or "utf-8") if sys.stdout.isatty() else "utf-8"))  # 콘솔(bat)=콘솔 코드페이지 · 파이프(UI)=utf-8
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "data", "outlook")
sys.path.insert(0, os.path.join(ROOT, "core"))
from collection_state import _atomic_text, merge_csv, read_csv, record_key, write_csv, write_status  # noqa: E402

MAIL_HDR = "box,time,sender,subject,conversation,rcv,time_precision"
CAL_HDR = "start,end,all_day,busy_status,subject,categories,location,response,meeting_status"
MAIL_URL = "https://outlook.office.com/mail/"
# Folder navigation requests a scope; it cannot certify the server's search scope.
MAIL_FOLDERS = (("inbox", MAIL_URL + "inbox"), ("sent", MAIL_URL + "sentitems"))
CAL_URL = "https://outlook.office.com/calendar/view/week"
HOSTS = ("outlook.office.com", "outlook.cloud.microsoft", "outlook.office365.com", "outlook.live.com")
MAX_EVENT_DAYS = 120            # 다일 일정으로 인정하는 최대 길이 — 그 이상은 날짜 오독으로 보고 첫 날짜만 쓴다


def arg(flag, d=""):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else d


def log(msg):
    print("[outlook-web] " + msg, flush=True)


def is_login_url(url):
    host = (urlsplit(str(url or "")).hostname or "").lower()
    return host in {"login.microsoftonline.com", "login.live.com", "login.microsoft.com"}


def structured_stamp(text):
    """Only an explicit HTML time value can carry an ISO timezone."""
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})?", str(text or "")):
        return None
    try:
        value = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return value.astimezone().replace(tzinfo=None) if value.tzinfo else value
    except ValueError:
        return None


def explicit_date_header(text):
    """Unverified search cannot supply a missing year or ambiguous month/day order."""
    for match in RE_MDY.finditer(text or ""):
        a, b = int(match.group(1)), int(match.group(2))
        if 1 <= a <= 12 and 1 <= b <= 12 and a != b:
            return False
    if RE_YMD.search(text or "") or RE_MDY.search(text or ""):
        return True
    return any(match and match.group(3) for match in (RE_MONEN.search(text or ""), RE_DMONEN.search(text or "")))


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


def parse_mail_item(item, d0, d1, folder="", *, explicit_dates=False):
    """화면 항목(aria-label·title·leaf texts) → [box,time,sender,subject,conversation,rcv,time_precision] 또는 None
    folder: 이 항목을 읽은 폴더 슬라이스('inbox'|'sent'|'') — 화면에 폴더명 조각이 없을 때의 box."""
    label = item.get("label") or ""
    titles = [t for t in (item.get("titles") or []) if t]
    texts = [t for t in (item.get("texts") or []) if t]
    pool = titles + [label] + texts
    # ★ 날짜는 **머리 조각(title·aria-label)에서만** 찾는다. texts 는 발신자·제목·미리보기(본문 앞머리)라
    #   회신 메일이면 인용문 머리글('2026년 6월 12일 (금) 오전 10:00, 홍길동 님이 작성:')이 그대로 들어 있다.
    #   그것을 시각으로 쓰면 9월 회신이 6월 메일이 되고, 6월 리뷰에 하지도 않은 최근 일이 등장한다(제보).
    #   미리보기에 인용문이 있는 것은 한국어 Outlook 에서 흔해 발생 빈도가 높다.
    # Explicit time/column metadata may be a visible leaf in modern OWA. Never
    # treat arbitrary preview text as a message date or exact timestamp.
    head = list(item.get("date_texts") or []) + titles + [label]
    if explicit_dates:
        head = [text for text in head if explicit_date_header(text)]
    when = None
    precision = "minute"
    for value in item.get("date_texts") or []:
        stamp = structured_stamp(value)
        if stamp:
            when = (stamp.date(), (stamp.hour, stamp.minute))
            break
    for cand in head:
        if when:
            break
        d = find_date(cand, d0, d1)
        ts = find_times(cand)
        if d and ts:
            when = (d, ts[0])
            break
    if not when:
        d = None
        ts = None
        for cand in head:
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
        box = "unknown" if folder == "unknown" else "sent" if folder == "sent" else "inbox"
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
    sender = str(item.get("sender") or (cands[0] if cands else ""))
    subject = str(item.get("subject") or (cands[1] if len(cands) > 1 else ""))
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
JS_DOM = r"""(() => {
  const visible = e => { if (!e || e.closest('[aria-hidden="true"]')) return false;
    const r=e.getBoundingClientRect(), s=getComputedStyle(e);
    return r.width>0 && r.height>0 && s.visibility!=="hidden" && s.display!=="none"; };
  const normal = s => (s || "").replace(/\s+/g," ").trim().toLowerCase();
  const searchSelectors = '#topSearchInput,input[role="searchbox"],[role="search"] input,'+
    'input[aria-label*="검색"],input[aria-label*="Search" i],input[placeholder*="검색"],'+
    'input[placeholder*="Search" i],[role="combobox"][aria-label*="검색"],[role="combobox"][aria-label*="Search" i]';
  const searchBox = () => [...document.querySelectorAll(searchSelectors)].find(visible);
  const idSelector = '[data-item-id],[data-itemid],[data-message-id]';
  const itemId = e => e && (e.getAttribute('data-item-id') || e.getAttribute('data-itemid') || e.getAttribute('data-message-id')) || '';
  const dateHint = new RegExp(__LM_DATE_HINT__, 'i');
  const rows = () => {
    let found=[...document.querySelectorAll('[role="listbox"] [role="option"],[role="grid"] [role="row"],'+
      '[role="listitem"][data-item-id],[role="listitem"][data-itemid],[role="listitem"][data-message-id]')];
    if(!found.length) found=[...document.querySelectorAll('[role="option"],[role="row"][aria-label]')];
    const eligible=e=>visible(e) && !e.closest('[role="search"],[role="combobox"],[role="menu"],[role="document"]') &&
      !e.querySelector('[role="columnheader"],[role="document"],[data-testid="message-body"],[data-tid="message-body"]');
    const message=e=>itemId(e) || e.getAttribute('data-convid') || e.querySelector('time,[data-testid="sender"],[data-tid="sender"]') ||
      dateHint.test((e.getAttribute('aria-label')||'')+' '+[...e.querySelectorAll('[title]')].map(x=>x.getAttribute('title')||'').join(' '));
    found=found.filter(e=>eligible(e)&&message(e));
    // Preserve the attribute-only OWA layout supported before v25.9. The
    // fallback applies after unrelated options (e.g. folders) are removed.
    if(!found.length) found=[...document.querySelectorAll('[data-convid],'+idSelector)].filter(eligible);
    // Nested wrappers do not represent additional messages.
    return found.filter(e=>!found.some(other=>other!==e && e.contains(other)));
  };
  const firstText = (e,selector) => {const child=[...e.querySelectorAll(selector)].find(visible);return child ? (child.textContent||'').trim() : '';};
  const info = e => {
    const identity=itemId(e), label=e.getAttribute('aria-label')||'';
    const texts=[...e.querySelectorAll('span,div,a,time')].filter(x=>x.childElementCount===0 && visible(x))
      .map(x=>(x.textContent||'').trim()).filter(Boolean).slice(0,32);
    const dates=[...e.querySelectorAll('time,[data-testid*="date" i],[data-testid*="time" i],[data-tid*="date" i],'+
      '[data-tid*="time" i],[data-automationid*="date" i]')].filter(visible)
      .map(x=>x.getAttribute('datetime')||x.getAttribute('title')||x.getAttribute('aria-label')||x.textContent||'').filter(Boolean);
    const subject=firstText(e,'[data-testid="message-subject"],[data-tid="message-subject"],[data-testid="subject"],[data-tid="subject"]');
    const sender=firstText(e,'[data-testid="sender"],[data-tid="sender"],[data-testid="message-sender"],[data-tid="message-sender"]');
    // An ID is stable when read/unread labels change. Without it, retain all
    // visible header evidence, not a truncated preview or recycled DOM index.
    const key=identity ? 'item:'+identity : 'visible:'+JSON.stringify([e.getAttribute('data-convid')||'',label,texts,dates]);
    return {key,item_id:identity,conversation_id:e.getAttribute('data-convid')||'',label,texts,date_texts:dates,subject,sender,
      titles:[...e.querySelectorAll('[title]')].filter(visible).map(x=>x.getAttribute('title')).filter(Boolean).slice(0,16)};
  };
  const listScroller = list => {
    const candidates=new Map();
    for(const row of list){let e=row.parentElement;for(let i=0;e && i<12;i++,e=e.parentElement){
      if(e.scrollHeight>e.clientHeight+20 && /auto|scroll/.test(getComputedStyle(e).overflowY))
        candidates.set(e,(candidates.get(e)||0)+1);
    }}
    return [...candidates].sort((a,b)=>b[1]-a[1])[0]?.[0] || null;
  };
""".replace("__LM_DATE_HINT__", json.dumps("|".join(rx.pattern for rx in (RE_YMD, RE_MDY, RE_MONEN, RE_DMONEN, RE_MD_KO, RE_MD, RE_TIME))))
JS_MAIL = JS_DOM + r"""
  const list=rows(), sb=searchBox();
  const signals=[...document.querySelectorAll('[role="status"],[role="heading"],[data-testid*="empty" i]')].filter(visible)
    .map(e=>normal(e.textContent));
  const empty=signals.some(s=>/^(no (results|messages|items)( found)?[.!]?|we didn't find anything[.!]?|검색 결과가 없습니다[.!]?|결과 없음|항목이 없습니다[.!]?)$/.test(s));
  const loading=[...document.querySelectorAll('[role="progressbar"],[aria-busy="true"]')].some(visible);
  const searching=/\/search(?:\/|\?|$)/i.test(location.href) || signals.some(s=>/^(search results|검색 결과)(\s|$)/.test(s));
  return JSON.stringify({href:location.href,n:list.length,items:list.slice(0,600).map(info),search:!!sb,
    query:sb ? (sb.value||sb.textContent||'') : '',empty,loading,searching,
    listboxes:document.querySelectorAll('[role="listbox"],[role="grid"]').length,
    state:loading ? 'loading' : list.length ? 'results' : empty ? 'empty' : 'unsupported'});
})()"""
JS_OPEN_MAIL = JS_DOM + r"""
  const key=%s, matches=rows().filter(e=>info(e).key===key);
  if(matches.length!==1) return 'unverified-item';
  window.__lm_mail_selected=matches[0];window.__lm_mail_key=key;
  matches[0].click();return 'opened';
})()"""
JS_MAIL_DETAIL = JS_DOM + r"""
  const expected=%s;
  const selected=rows().filter(e=>info(e).key===expected.key && (e.getAttribute('aria-selected')==='true' || e.getAttribute('data-is-selected')==='true'));
  if(selected.length!==1) return JSON.stringify({reason:'selected_message_not_verified'});
  const bodySelector='[data-testid="message-body"],[data-testid="message-body-content"],[data-tid="message-body"],'+
    '[role="document"][aria-label*="Message body" i],[role="document"][aria-label*="메일 본문"],'+
    '[role="document"][aria-label*="메시지 본문"],div[aria-label="Message body" i],div[aria-label="메시지 본문"]';
  let bodies=[...document.querySelectorAll(bodySelector)].filter(visible);
  bodies=bodies.filter(e=>!bodies.some(other=>other!==e && e.contains(other)));
  const candidates=[];
  for(const body of bodies){
    const identityContainer=body.closest(idSelector);
    const message=identityContainer;
    if(!message || message.contains(selected[0])) continue;
    const subject=firstText(message,'[data-testid="message-subject"],[data-tid="message-subject"],[role="heading"]');
    if(!expected.subject || normal(subject)!==normal(expected.subject)) continue;
    const identity=itemId(identityContainer);
    if(!identity || !expected.item_id || identity!==expected.item_id) continue;
    const text=body.innerText || body.textContent || '';
    candidates.push({container:'message-body',item_id:identity,selected_key:expected.key,subject,proof:'message-id',
      body:text.slice(0,expected.limit+1),truncated:text.length>expected.limit,url:location.href});
  }
  return JSON.stringify(candidates.length===1 ? candidates[0] : {reason:'unique_message_body_not_verified'});
})()"""
JS_SCROLL = JS_DOM + r"""
  const list=rows(); if(!list.length) return 'no-list';
  const el=listScroller(list); if(!el) return 'end';
  const before=el.scrollTop; el.scrollTop+=Math.max(100,el.clientHeight-40);
  el.dispatchEvent(new Event('scroll',{bubbles:true}));
  return el.scrollTop>before ? 'scrolled' : 'end';
})()"""
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
JS_FOCUS_SEARCH = JS_DOM + r"""
  const c=searchBox();if(c){c.focus();c.click();window.__lm_sb=c;return 'ok';}
  const btn=[...document.querySelectorAll('button[aria-label*="검색"],button[aria-label*="Search" i]')].find(visible);
  if(btn){btn.click();return 'button';}return 'none';
})()"""
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
        self.cfg = dict(self.ca.load_cfg())
        self.cfg["url"] = MAIL_URL
        self.port = self.cfg["port"]
        self.cdp = None
        self.deadline = None
        self.last_diagnostic = ""
        self._ready_once = False

    def remaining(self, limit=12):
        remaining = limit if self.deadline is None else min(limit, self.deadline - time.monotonic())
        if remaining <= 0:
            raise TimeoutError("outlook_web_time_budget")
        return remaining

    def pause(self, seconds):
        time.sleep(min(seconds, self.remaining(seconds)))

    def start(self):
        if self.deadline is not None:
            self.cfg["_collection_deadline"] = self.deadline
        if not self.ca.ensure_edge(self.cfg):
            self.last_diagnostic = self.cfg.get('_edge_reason', 'driver_unavailable')
            return False
        self.port = self.cfg["port"]
        tabs = [t for t in self.ca.http_json(self.port, "/json", timeout=self.remaining(3)) if t.get("type") == "page"]
        ws = None
        for t in tabs:
            if urlsplit(t.get("url") or "").hostname in HOSTS:
                ws = t["webSocketDebuggerUrl"]
                break
        if not ws:
            for method in ("PUT", "GET"):
                try:
                    t = self.ca.http_json(self.port, "/json/new?" + quote(MAIL_URL, safe=""), method=method, timeout=self.remaining(3))
                    ws = t["webSocketDebuggerUrl"]
                    break
                except Exception:
                    continue
        if not ws:
            return False
        self.cdp = self.ca.CDP(ws, timeout=self.remaining(5))
        try:
            self.cdp.call("Page.enable", timeout=self.remaining(3))
        except Exception:
            pass
        return True

    def goto(self, url, wait=0.0):
        try:
            self.cdp.call("Page.navigate", {"url": url}, timeout=self.remaining())
        except Exception:
            self.remaining()
            self.cdp.reconnect(timeout=self.remaining(3))
            self.cdp.call("Page.navigate", {"url": url}, timeout=self.remaining())
        return self.wait_ready(wait)

    def href(self):
        try:
            return str(self.cdp.eval("location.href", timeout=self.remaining(3)))
        except Exception:
            return ""

    def wait_ready(self, settle=0.0, limit=18):
        """Wait for observable mail/calendar UI, not an empty generic main shell."""
        until = time.monotonic() + self.remaining(limit)
        login_since = None
        login_grace = 2 if getattr(self, "_ready_once", False) else 8
        while time.monotonic() < until:
            h = self.href()
            if is_login_url(h):
                if login_since is None:
                    login_since = time.monotonic()
                    log("회사 로그인 리다이렉트를 확인하고 있습니다.")
                if time.monotonic()-login_since >= login_grace:
                    self.last_diagnostic = "login_required"
                    return "login"
                if time.monotonic() >= until:
                    break
                self.pause(min(0.2, max(0, until-time.monotonic())))
                continue
            login_since = None
            try:
                page = self.eval_json(JS_MAIL, timeout=3)
                calendar = "/calendar" in h and int(self.cdp.eval('document.querySelectorAll(\'[role="grid"]\').length', timeout=self.remaining(3)) or 0)
            except Exception:
                page, calendar = {}, False
            if urlsplit(h).hostname in HOSTS and not page.get("loading") and (calendar or page.get("items") or page.get("empty") or (page.get("search") and page.get("listboxes"))):
                self.last_diagnostic = "ready"
                self._ready_once = True
                return "ok"
            self.pause(0.2)
        self.last_diagnostic = "login_required" if login_since is not None else "mail_surface_not_ready"
        return "login" if login_since is not None else "timeout"

    def eval_json(self, js, timeout=8):
        r = self.cdp.eval(js, timeout=self.remaining(timeout))
        if isinstance(r, str):
            try:
                return json.loads(r)
            except ValueError:
                return {}
        return r or {}

    def search(self, query):
        self.last_diagnostic = "search_input_missing"
        before = self.eval_json(JS_MAIL)
        signature = tuple(item.get("key") for item in before.get("items", []))
        how = str(self.cdp.eval(JS_FOCUS_SEARCH, timeout=self.remaining(3)))
        if how == "none":
            return False
        if how == "button":
            self.pause(0.15)
            if str(self.cdp.eval(JS_FOCUS_SEARCH, timeout=self.remaining(3))) != "ok":
                return False
        self.cdp.eval(JS_CLEAR_SEARCH, timeout=self.remaining(3))
        try:
            self.cdp.call("Input.insertText", {"text": query}, timeout=self.remaining(3))
            self.cdp.call("Input.dispatchKeyEvent", {"type": "keyDown", "key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13}, timeout=self.remaining(3))
            self.cdp.call("Input.dispatchKeyEvent", {"type": "keyUp", "key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13}, timeout=self.remaining(3))
        except Exception:
            return False
        until, stable, saw_loading = time.monotonic() + self.remaining(12), 0, False
        visible_stable, visible_keys = 0, None
        login_since = None
        while time.monotonic() < until:
            # The poll window decides whether to start another observation;
            # its last few milliseconds are not a safe CDP response timeout.
            # Every call still has the hard route deadline through remaining().
            page = self.eval_json(JS_MAIL, timeout=3)
            if is_login_url(page.get("href", "")):
                visible_stable = 0
                login_since = time.monotonic() if login_since is None else login_since
                if time.monotonic()-login_since >= 2:
                    self.last_diagnostic = "login_required"
                    return False
                if time.monotonic() >= until:
                    break
                self.pause(min(0.2, max(0, until-time.monotonic())))
                continue
            login_since = None
            entered = str(page.get("query") or "").strip() == query
            changed = tuple(item.get("key") for item in page.get("items", [])) != signature
            saw_loading = saw_loading or bool(page.get("loading"))
            transitioned = changed or saw_loading or (page.get("searching") and not before.get("searching")) or (page.get("href") and page.get("href") != before.get("href"))
            result = page.get("state") in {"results", "empty"}
            keys = tuple(item.get("key") for item in page.get("items", []))
            if entered and keys and result and not page.get("loading"):
                visible_stable = visible_stable+1 if keys == visible_keys else 1
                visible_keys = keys
            else:
                visible_stable = 0
            if entered and result and not page.get("loading") and transitioned:
                stable += 1
                if stable >= 2:
                    self.last_diagnostic = "visible_search_results; folder_scope_unverified"
                    return "query_entered_unverified"
            else:
                stable = 0
            left = until-time.monotonic()
            if left > 0:
                self.pause(min(0.2, left))
        if visible_stable >= 2 and login_since is None:
            self.last_diagnostic = "query_entered; visible_results_unverified"
            return "visible_unverified"
        self.last_diagnostic = "login_required" if login_since is not None else "search_result_not_ready_or_stale"
        return False

    def close(self):
        try:
            if self.cdp:
                self.cdp.close()
        except Exception:
            pass

    def wait_list_change(self, keys, limit=2):
        until = time.monotonic() + self.remaining(limit)
        while time.monotonic() < until:
            self.pause(0.2)
            if time.monotonic() >= until:
                break
            page = self.eval_json(JS_MAIL, timeout=2)
            if not page.get("loading") and tuple(item.get("key") for item in page.get("items", [])) != keys:
                return


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


def mail_search_query(start, end, folder):
    """Documented Outlook AQS date range; sent folders use the sent date."""
    property_name = "sent" if folder == "sent" else "received"
    return f"{property_name}:{start:%m/%d/%Y}..{end:%m/%d/%Y}"


def mail_search_windows(d0, d1, days=7):
    current = d0
    while current <= d1:
        end = min(d1, current + timedelta(days=max(1, days) - 1))
        yield current, end
        current = end + timedelta(days=1)


def _fake_mail_batch(fake, month_key, folder):
    """시험용 화면: 달별 항목이 목록이면 받은 편지함 슬라이스로, {"inbox":[…],"sent":[…]} 면 폴더별로 쓴다"""
    fm = (fake.get("mail") or {}).get(month_key, [])
    if isinstance(fm, dict):
        return list(fm.get(folder) or [])
    return list(fm) if folder == "inbox" else []


def detail_context(item, row, detail, limit):
    """Accept only an identified, selected message body; never a list preview/page dump."""
    def norm(value):
        return re.sub(r"\s+", " ", str(value or "")).strip().casefold()
    if not item.get("item_id") or detail.get("item_id") != item["item_id"]:
        return "", "", "detail_message_identity_missing_or_mismatch", ""
    if detail.get("selected_key") != item.get("key") or detail.get("container") != "message-body":
        return "", "", "detail_container_or_selection_not_verified", ""
    if not row[3] or norm(detail.get("subject")) != norm(row[3]):
        return "", "", "detail_subject_mismatch", ""
    body = re.sub(r"\s+", " ", str(detail.get("body") or "")).strip()
    if not body:
        return "", "", "detail_body_empty", ""
    truncated = bool(detail.get("truncated")) or len(body) > limit
    url = str(detail.get("url") or "")
    if not any(url.startswith("https://" + host + "/") for host in HOSTS):
        url = ""
    return body[:limit], str(truncated).lower(), "", url


def read_mail_detail(br, item, row, limit):
    if not item.get("item_id"):
        return {}, "message_identity_missing"
    try:
        timeout = br.remaining(3) if hasattr(br, "remaining") else 3
        if str(br.cdp.eval(JS_OPEN_MAIL % json.dumps(item.get("key", "")), timeout=timeout)) != "opened":
            return {}, "message_could_not_be_selected"
        expected = {"item_id": item.get("item_id", ""), "key": item.get("key", ""),
                    "subject": row[3], "limit": limit}
        until = time.monotonic() + (br.remaining(3) if hasattr(br, "remaining") else 3)
        detail = {}
        while time.monotonic() < until:
            detail = br.eval_json(JS_MAIL_DETAIL % json.dumps(expected, ensure_ascii=False), timeout=2)
            if detail.get("body"):
                return detail, ""
            time.sleep(min(0.15, max(0, until-time.monotonic())))
        return {}, detail.get("reason", "message_detail_not_verified")
    except Exception as error:
        return {}, "detail_read_failed:" + type(error).__name__


def collect_mail(br, d0, d1, fake=None, *, body=False, context_chars=4000,
                 checkpoint=None, deadline=None, state_path=None, store_subject=True):
    """Read visible search results; checkpoint each page and retain metadata on detail failure."""
    rows, seen, observed, undated_seen = [], set(), set(), set()
    diag = {"search": 0, "items": 0, "parsed": 0, "sent": 0, "cc": 0,
            "date_only": 0, "pages": 0, "sent_pass_new": 0, "body_rows": 0,
            "detail_failed": 0, "completed_units": 0, "search_failed": 0,
            "search_unverified": 0, "search_attempts": 0, "undated": 0, "period_filtered": 0,
            "empty_results": 0, "unsupported_pages": 0, "navigation_failed": 0, "visible_unverified": 0, "reasons": []}
    state = {"schema": 2, "requested_from": str(d0), "requested_to": str(d1),
             "body": body, "context_chars": context_chars, "units": {}}
    if state_path and fake is None:
        try:
            with open(state_path, encoding="utf-8") as stream:
                previous = json.load(stream)
            if all(previous.get(key) == state[key] for key in state if key != "units") and isinstance(previous.get("units"), dict):
                state = previous
        except (OSError, ValueError, TypeError):
            pass
    active_seen, active_unit = set(), None

    def save_progress():
        if state_path and fake is None and active_unit is not None:
            active_unit["seen_hashes"] = sorted(active_seen)
            _atomic_text(state_path, json.dumps(state, ensure_ascii=True))

    def job_key(start, end, folder):
        return f"{folder}:{start}:{end}"

    def consume(page, folder, start, end, *, visible_only=False):
        diag["pages"] += 1
        pending = []
        if page.get("n", 0) > 600:
            diag["reasons"].append("visible_page_item_limit_reached")
        for item in page.get("items", []):
            if deadline and time.monotonic() >= deadline:
                diag["reasons"].append("time_budget_reached")
                raise TimeoutError("collection budget")
            key = item.get("key") or json.dumps(item, ensure_ascii=False)[:200]
            key_hash = hashlib.sha256(key.encode("utf-8")).hexdigest()
            if key in seen or (not visible_only and key_hash in active_seen):
                continue
            if key not in observed:
                observed.add(key)
                diag["items"] += 1
                if folder == "sent":
                    diag["sent_pass_new"] += 1
            # A folder URL alone does not prove OWA search remained in that folder.
            row = parse_mail_item(item, start, end, folder if fake is not None else "unknown",
                                  explicit_dates=(fake is None or visible_only))
            if not row:
                if key not in undated_seen:
                    undated_seen.add(key)
                    diag["undated"] += 1
                    diag["reasons"].append("mail_date_unconfirmed")
                    pending.append(_undated_mail(item, key_hash, folder, d0, d1, store_subject))
                continue
            if not (d0.isoformat() <= row[1][:10] <= d1.isoformat()):
                diag["period_filtered"] += 1
                continue
            if visible_only:
                row[0], row[5] = "unknown", ""
            excerpt = truncated = source_url = ""
            reason = ""
            if body:
                if fake is not None:
                    detail, reason = item.get("detail") or {}, ""
                else:
                    detail, reason = read_mail_detail(br, item, row, context_chars)
                if not reason:
                    excerpt, truncated, reason, source_url = detail_context(item, row, detail, context_chars)
                if reason:
                    diag["detail_failed"] += 1
                    if reason not in diag["reasons"]:
                        diag["reasons"].append(reason)
                elif excerpt:
                    diag["body_rows"] += 1
            # A conversation identifier is not a message identifier.
            source_id = item.get("item_id") or "derived:outlook-visible:" + key_hash
            row += [excerpt, truncated, source_id, "outlook_web", source_url,
                    item.get("conversation_id", ""), folder if fake is not None else "requested:" + folder, ""]
            rows.append(row)
            seen.add(key)
            if not reason and not visible_only:
                active_seen.add(key_hash)
            diag["parsed"] += 1
            if row[0] == "sent":
                diag["sent"] += 1
            elif row[5] == "cc":
                diag["cc"] += 1
            if row[6] == "date":
                diag["date_only"] += 1
        if pending:
            _save_undated_mail(pending)
        if checkpoint and rows:
            checkpoint(rows)
        save_progress()

    try:
        windows = months_of(d0, d1) if fake is not None else mail_search_windows(d0, d1)
        jobs = [(start, end, folder, url) for start, end in windows for folder, url in MAIL_FOLDERS]
        expanded = []
        for start, end, folder, url in jobs:
            if state["units"].get(job_key(start, end, folder), {}).get("split"):
                expanded.extend((day, day, folder, url) for day, _ in mail_search_windows(start, end, 1))
            else:
                expanded.append((start, end, folder, url))
        jobs = expanded
        pending = [job for job in jobs if not state["units"].get(job_key(*job[:3]), {}).get("traversed")]
        # Resume untouched/interrupted ranges first; once explored, refresh newest ranges.
        jobs = sorted(pending, key=lambda job: state["units"].get(job_key(*job[:3]), {}).get("last_attempt", 0)) or list(reversed(jobs))
        diag["total_units"] = len(jobs)
        failures = 0
        for start, end, folder, url in jobs:
                active_unit = state["units"].setdefault(job_key(start, end, folder), {})
                active_seen = set(active_unit.get("seen_hashes") or []) if not active_unit.get("traversed") else set()
                if deadline and time.monotonic() >= deadline:
                    diag["reasons"].append("time_budget_reached")
                    return rows, "partial", diag
                if fake is not None:
                    batch = _fake_mail_batch(fake, start.strftime("%Y-%m"), folder)
                    consume({"items": batch}, folder, start, end)
                    diag["completed_units"] += 1
                    continue
                active_unit["attempted_at"] = time.time()
                active_unit["traversed"] = False
                save_progress()
                log(f"메일 검색 {start}~{end} ({folder}); 저장 {len(rows)}건")
                navigation = br.goto(url)
                if navigation == "login":
                    return rows, "login", diag
                if navigation != "ok":
                    active_unit["last_attempt"] = time.time()
                    save_progress()
                    diag["navigation_failed"] += 1
                    diag["reasons"].append("folder_navigation_not_verified")
                    failures += 1
                    if failures >= 2:
                        diag["reasons"].append("mail_surface_unavailable; remaining_ranges_pending")
                        break
                    continue
                diag["search_attempts"] += 1
                searched = br.search(mail_search_query(start, end, folder))
                if searched == "visible_unverified":
                    diag["visible_unverified"] += 1
                    diag["reasons"].append("visible_observations_only; search_not_verified; range_pending")
                    active_unit["last_attempt"] = time.time()
                    page = br.eval_json(JS_MAIL)
                    if is_login_url(page.get("href", "")):
                        return rows, "login", diag
                    if str(page.get("query") or "").strip() == mail_search_query(start, end, folder):
                        consume(page, folder, start, end, visible_only=True)
                    else:
                        diag["reasons"].append("search_query_changed; visible_observations_skipped")
                    save_progress()
                    # This neither certifies a search nor advances its cursor.
                    # Repeated UI uncertainty should not use the entire run budget.
                    failures += 1
                    if failures >= 3:
                        break
                    continue
                if searched:
                    diag["search"] += 1
                    diag["search_unverified"] += 1
                    diag["reasons"].append("query_entered; server_search_and_folder_scope_not_verified")
                else:
                    active_unit["last_attempt"] = time.time()
                    save_progress()
                    diag["search_failed"] += 1
                    diag["reasons"].append("search_input_failed; stale_visible_list_skipped")
                    detail = getattr(br, "last_diagnostic", "")
                    if detail == "login_required":
                        return rows, "login", diag
                    if detail:
                        diag["reasons"].append(detail)
                    failures += 1
                    if failures >= 3:
                        diag["reasons"].append("search_unavailable; remaining_ranges_pending")
                        break
                    continue
                stall, seen_scroll = 0, set()
                saturated, unsupported = False, False
                for _ in range(400):
                    if deadline and time.monotonic() >= deadline:
                        diag["reasons"].append("time_budget_reached")
                        return rows, "partial", diag
                    page = br.eval_json(JS_MAIL)
                    if page.get("state") == "unsupported":
                        diag["unsupported_pages"] += 1
                        diag["reasons"].append("mail_list_selector_unsupported; range_pending")
                        unsupported = True
                        break
                    if page.get("empty"):
                        diag["empty_results"] += 1
                        break
                    consume(page, folder, start, end)
                    new = {item.get("key") for item in page.get("items", [])} - seen_scroll
                    seen_scroll |= new
                    if len(seen_scroll) >= 1000:
                        saturated = True
                        diag["reasons"].append("search_result_limit_possible")
                        break
                    stall = 0 if new else stall + 1
                    if stall >= 3:
                        break
                    if hasattr(br, "remaining"):
                        scrolled = str(br.cdp.eval(JS_SCROLL, timeout=br.remaining(3)))
                    else:
                        scrolled = str(br.cdp.eval(JS_SCROLL))
                    if scrolled in ("no-list", "end") and stall >= 1:
                        break
                    if hasattr(br, "wait_list_change"):
                        br.wait_list_change(tuple(item.get("key") for item in page.get("items", [])), limit=1.5 if scrolled == "scrolled" else 0.3)
                    else:
                        time.sleep(1.0)
                else:
                    saturated = True
                    diag["reasons"].append("mail_scroll_limit_reached")
                if unsupported:
                    active_unit["last_attempt"] = time.time()
                    failures += 1
                    save_progress()
                    if failures >= 3:
                        break
                    continue
                failures = 0
                if saturated and start < end:
                    active_unit["split"] = True
                    jobs.extend((day, day, folder, url) for day, _ in mail_search_windows(start, end, 1))
                    diag["reasons"].append("saturated_range_retried_by_day")
                # Traversed means the available UI list stopped, never complete mailbox coverage.
                active_unit.update(traversed=True, saturated=saturated, finished_at=time.time(),
                                   scope="visible inbox/sent search; server and folder scope unverified")
                save_progress()
                diag["completed_units"] += 1
    except Exception as error:
        if checkpoint and rows:
            checkpoint(rows)
        save_progress()
        diag["reasons"].append("time_budget_reached" if isinstance(error, TimeoutError) else "mail_page_failed:" + type(error).__name__)
        return rows, "partial" if rows else "failed", diag
    rows.sort(key=lambda row: row[1])
    return rows, ("ok" if rows else "empty"), diag


def collect_cal(br, d0, d1, fake=None, *, checkpoint=None, deadline=None):
    rows, seen = [], set()
    diag = {"weeks": 0, "events": 0, "parsed": 0}
    cur = d0 - timedelta(days=d0.weekday())
    while cur <= d1:
        if deadline and time.monotonic() >= deadline:
            diag["reasons"] = ["calendar_time_budget_reached"]
            return rows, "partial", diag
        diag["weeks"] += 1
        if fake is not None:
            pg = {"events": fake.get("cal", {}).get(cur.isoformat(), [])}
        else:
            url = f"{CAL_URL}/{cur.year}/{cur.month}/{cur.day}"
            try:
                st = br.goto(url, wait=5.0)
                if st == "login":
                    return rows, "login", diag
                if st != "ok":
                    diag["reasons"] = ["calendar_page_not_ready"]
                    return rows, "partial" if rows else "failed", diag
                pg = br.eval_json(JS_CAL)
            except Exception as error:
                diag["reasons"] = ["calendar_page_failed:" + type(error).__name__]
                return rows, "partial" if rows else "failed", diag
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
        if checkpoint and rows:
            checkpoint(rows)
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


def _undated_mail(item, key_hash, folder, d0, d1, store_subject):
    # Parsing may help identify metadata, but its inferred date is NEVER stored.
    candidate = parse_mail_item(item, d0, d1, "unknown")
    sender = candidate[2] if candidate else str(item.get("sender") or "")
    subject = candidate[3] if candidate else str(item.get("subject") or "")
    return {"box": "unknown", "time": "", "time_precision": "unknown", "sender": sender,
            "subject": subject if store_subject else "", "conversation": "", "rcv": "",
            "context_excerpt": "", "source_id": item.get("item_id") or "derived:outlook-visible:" + key_hash,
            "source_kind": "outlook_web", "conversation_id": item.get("conversation_id") or "",
            "account": "", "folder": "requested:" + folder,
            "timestamp_text": " | ".join(str(x) for x in [*(item.get("date_texts") or []),
                                *(item.get("titles") or []), item.get("label") or ""])[:1000] if store_subject else "",
            "requested_from": str(d0), "requested_to": str(d1)}


def _save_undated_mail(rows):
    path = os.path.join(ROOT, 'data', 'collection_pending', 'outlook_web_undated.csv')
    known = {record_key(row, 'mail') for row in read_csv(os.path.join(OUT_DIR, 'mail.csv')) if row.get('source_id')}
    pending = [row for row in rows if record_key(row, 'mail') not in known]
    if pending:
        merge_csv(path, pending, list(pending[0]), kind='mail')


def _save(kind, rows, store_subject):
    """Atomic union: partial or narrower fallback never replaces earlier history."""
    dst = os.path.join(OUT_DIR, "mail.csv" if kind == "mail" else "calendar.csv")
    base = (MAIL_HDR if kind == "mail" else CAL_HDR).split(",")
    extra = ["context_excerpt", "context_truncated", "source_id", "source_kind",
             "source_url", "conversation_id", "folder", "account"]
    fields = base + [key for key in extra if key not in base]
    records = []
    for raw in rows:
        values = list(raw) + [""] * max(0, len(fields) - len(raw))
        row = dict(zip(fields, values, strict=False))
        row["source_kind"] = row.get("source_kind") or "outlook_web"
        if not store_subject:
            row["subject"] = ""
            row["context_excerpt"] = ""
            row["context_truncated"] = ""
            if kind == "mail":
                row["conversation"] = _conv_token(row.get("conversation", ""))
        records.append(row)
    merge_csv(dst, records, fields, kind="mail" if kind == "mail" else "calendar")
    if kind == 'mail':
        pending_path = os.path.join(ROOT, 'data', 'collection_pending', 'outlook_web_undated.csv')
        if os.path.exists(pending_path):
            resolved = {record_key(row, 'mail') for row in records if row.get('source_id')}
            pending = read_csv(pending_path)
            remaining = [row for row in pending if record_key(row, 'mail') not in resolved]
            if len(remaining) != len(pending):
                write_csv(pending_path, remaining, list(pending[0]))
    return dst


def main():
    started = time.monotonic()
    d0s = arg("--from") or (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
    d1s = arg("--to") or datetime.now().strftime("%Y-%m-%d")
    d0, d1 = date.fromisoformat(d0s), date.fromisoformat(d1s)
    only = arg("--only")
    try:
        with open(os.path.join(ROOT, "config", "config.json"), encoding="utf-8-sig") as stream:
            cfg = json.load(stream)
    except (OSError, ValueError):
        cfg = {}
    store_subject = bool(cfg.get("storeMailSubject", True))
    collection = cfg.get("collection") or {}
    try:
        budget = max(1, min(1800, float(arg("--time-budget") or arg("--budget") or collection.get("mailWebBudgetSec", 180))))
    except (TypeError, ValueError):
        budget = 180
    deadline = started + budget
    body = (bool(collection.get("mailWebBody", False)) or "--include-body" in sys.argv) and store_subject
    body = body and "--exclude-body" not in sys.argv
    try:
        context_chars = min(20000, max(0, int(collection.get("contextChars", 4000))))
    except (TypeError, ValueError):
        context_chars = 4000
    body = body and context_chars > 0
    counts, diagnostics = {}, {}
    reasons = ["visible_search_results_only; mailbox-wide coverage is not verified"]
    if not body:
        reasons.append("metadata_only: mailWebBody is disabled; no message body collected")
    else:
        reasons.append("message detail opening can mark mail read; tenant selectors require real-environment verification")
    todo = [kind for kind in ("mail", "cal") if not only or only == kind]
    attempted = set()
    def finish(code, reason="", blocked=False, in_progress=False):
        kinds = {kind: ("partial" if counts.get(kind) or in_progress else "failed") if kind in attempted or kind in todo else "skipped"
                 for kind in ("mail", "cal")}
        write_status(ROOT, "outlook_web", d0s, d1s,
                     status="partial" if sum(counts.values()) or in_progress or code == 0 else ("blocked" if blocked else "failed"),
                     rows=sum(counts.values()), scope="OWA visible inbox/sent search pages and calendar week views",
                     reasons=reasons + ([reason] if reason else []),
                     mail_status=kinds["mail"], calendar_status=kinds["cal"],
                     mail_rows=counts.get("mail", 0), calendar_rows=counts.get("cal", 0),
                     body_requested=body, body_rows=diagnostics.get("mail", {}).get("body_rows", 0),
                     completed_units=sum(x.get("completed_units", x.get("weeks", 0)) for x in diagnostics.values()),
                     total_units=sum(x.get("total_units", x.get("weeks", 0)) for x in diagnostics.values()),
                     diagnostics={kind: {key: value for key, value in diag.items() if isinstance(value, (int, float))}
                                  for kind, diag in diagnostics.items()},
                     elapsed_sec=round(time.monotonic()-started, 2), time_budget_sec=budget,
                     context_chars=context_chars)
        return code
    finish(1, "collection started; completion not verified", in_progress=True)
    # A nonempty local CSV says nothing about the selected range or earlier
    # partial collection. Existing rows are retained by atomic union.
    fake = None
    fake_path = os.environ.get("LM_OWA_FAKE", "")
    if fake_path:
        try:
            with open(fake_path, encoding="utf-8-sig") as stream:
                fake = json.load(stream)
        except (OSError, ValueError):
            return finish(1, "invalid synthetic fixture")
        if fake.get("login"):
            return finish(2, "login_required", blocked=True)
    br = None
    log(f"웹 화면 수집 시작: {d0s}~{d1s}, 최대 {budget:g}초; 전체 사서함 완료는 확인하지 않습니다")
    if fake is None:
        if os.environ.get("LM_NO_BROWSER"):
            return finish(3, "browser_disabled", blocked=True)
        try:
            br = Browser()
            br.deadline = deadline
            if not br.start():
                br.close()
                return finish(3, "time_budget_reached" if time.monotonic() >= deadline else
                              (getattr(br, 'last_diagnostic', '') or "Edge startup failed"), blocked=True)
            initial = br.goto(MAIL_URL)
            if initial == "login":
                log("전용 Edge 창에서 회사 계정 로그인이 필요합니다. 로그인 후 수집을 다시 실행하세요.")
                br.close()
                return finish(2, "login_required", blocked=True)
            if initial == "timeout":
                br.close()
                return finish(1, "mail page timeout")
        except Exception as error:
            if br:
                br.close()
            return finish(3, "time_budget_reached" if isinstance(error, TimeoutError) else "browser_failed:" + type(error).__name__, blocked=True)
    try:
        for kind in todo:
            attempted.add(kind)
            saved_count = 0
            def checkpoint(current):
                nonlocal saved_count
                if len(current) > saved_count:
                    _save(kind, current[saved_count:], store_subject)
                    saved_count = len(current)
                counts[kind] = len(current)
                finish(0, "partial observations checkpointed")
            if kind == "mail":
                rows, state, diag = collect_mail(br, d0, d1, fake, body=body,
                                                context_chars=context_chars, checkpoint=checkpoint, deadline=deadline,
                                                state_path=os.path.join(OUT_DIR, "web_mail_jobs.json"), store_subject=store_subject)
            else:
                rows, state, diag = collect_cal(br, d0, d1, fake, checkpoint=checkpoint, deadline=deadline)
            diagnostics[kind] = diag
            reasons.extend(diag.get("reasons", []))
            if rows:
                checkpoint(rows)
            if state == "login":
                log("로그인이 필요해 수집을 중단했습니다. 이미 저장한 관측은 유지합니다.")
                return finish(2, "login_required_after_partial_collection", blocked=True)
            log(f"{kind}: {len(rows)} observations retained; declared scope remains partial")
        if sum(counts.values()):
            source = {"source": "owa", "when": datetime.now().strftime("%Y-%m-%d %H:%M"),
                      "kinds": list(counts), "rows": sum(counts.values()), "mail": counts.get("mail", 0),
                      "calendar": counts.get("cal", 0), "calendar_complete": False, "me": [],
                      "warnings": list(dict.fromkeys(reasons))}
            with open(os.path.join(OUT_DIR, "mail_source.json"), "w", encoding="utf-8") as stream:
                json.dump(source, stream, ensure_ascii=False)
        return finish(0 if sum(counts.values()) else 1)
    except Exception as error:
        return finish(1, "time_budget_reached" if isinstance(error, TimeoutError) else "collection_or_save_failed:" + type(error).__name__)
    finally:
        if br:
            br.close()


if __name__ == "__main__":
    sys.exit(main())
