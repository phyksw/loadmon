# -*- coding: utf-8 -*-
"""
Get-OutlookWeb.py — Outlook 웹(outlook.office.com)을 전용 Edge 프로필로 열어 메일·일정을 읽는다 (폴백).

Outlook 의 '버전'과 무관한 경로다: 클래식/새 Outlook/2016 마법사/COM 미등록 어느 PC 든, Copilot 에
쓰는 전용 Edge 프로필(data\\lm28_edge)에 회사 계정으로 한 번 로그인해 두면 동작한다. Copilot 처럼
LLM 을 거치지 않으므로 지어낸 행이 없고, 데이터는 PC 밖으로 나가지 않는다(브라우저가 내 사서함을 보여주는
것을 읽을 뿐).

  python collect\\Get-OutlookWeb.py --from 2026-06-01 --to 2026-06-30 [--only mail|cal] [--force]
         [--out-dir data\\outlook\\src --tag owa] [--budget-sec N]

출력: data\\outlook\\mail.csv      (box,time,sender,subject,conversation,rcv,time_precision)   ← COM 스키마 + 정밀도 열
                                  time_precision: minute(시각 해석) | date(날짜만 보여 12:00 으로 둔 행 — 시간 근거로 쓰지 말 것)
      data\\outlook\\calendar.csv  (start,end,all_day,busy_status,subject,categories,location,response,meeting_status)
                                  ※ response/meeting_status 는 COM 수집기(Get-OutlookData.ps1)만 채운다 — 여기선 빈값
                                  ※ 여러 날에 걸친 일정(휴가·출장·워크숍)은 start~end 한 행(첫날~마지막날) — extract 가 일자로 전개한다
      LM28: --out-dir·--tag 를 주면 <폴더>\\mail_<tag>.csv·cal_<tag>.csv·mail_source_<tag>.json(출처별 파일 — 병합은 mailmerge).
            없으면 LM24 처럼 data\\outlook\\mail.csv·calendar.csv·mail_source.json(자료가 있으면 --force 때만).
            어느 쪽이든 통째로 덮어쓰지 않는다 — 이번에 검증한 날의 옛 행만 새 행으로 바꾸고 나머지는 둔다(W1-04).
종료 코드(= LMSTATUS rc, LM28): 0 정상(덜 읽은 날은 ranges 가 말한다) / 2 로그인 필요(전용 Edge 창에서 1회 · R-LOGIN·R-PERSONAL 등)
          / 3 불가·불완전(R-WEBSEL 모든 조각 미검증 · R-TIMEOUT · R-EDGEBUSY · Edge 기동 사유). LM24 의 1(아무것도 못 읽음)은 없앴다.
마지막 줄: LMSTATUS {v,src,rc,reason,counts,ranges[{axis: mail_in|mail_out|cal, from, to, st}]}
          st: ok(그 날을 끝까지 읽음 — 0건인 날 포함) · zero_ok(검색 결과 없음 확인) · partial · unverified. 오늘은 ok 대신 partial.

LM28 '읽음' 규칙(F-03·F-04·F-05 — 검증된 조각만 읽음으로 적는다):
  · 메일은 달 조각 × 폴더마다 기간 검색 뒤 결과를 끝까지 내리며 owa_parse.slice_verdict 로 판정한다. 결과 항목이 조각 밖
    날짜면 검색이 안 걸린 화면(filter_ineffective)이라 그 폴더는 **1회만** 검색을 지우고 최신부터 내려 기간 시작 앞 날짜에
    닿을 때까지 읽는다(폴백 — 새 항목 없는 화면 3번이면 멈춤). 끊김 없이 D 까지 내려갔으면 [D+1, 끝] 은 ok, D 이하는 partial.
    LM24 의 '달마다 최대 400회 스크롤'은 없앴다. 목록의 오늘(시각만)·이번 주(요일+시각)·어제 표기도 날짜로 읽는다(F-04).
  · 날짜만 보이는 줄은 항목의 다른 title·aria-label·<time datetime>(로컬로 바꿈)에서 시각을 찾고, 보낸 편지함은 그래도
    없으면 항목을 열어 읽기 창 머리에서 owaTimeRecoverMax(150)건까지 시각을 얻는다(받은 메일은 열지 않는다 — 읽음 표시).
  · 일정은 가장 최근 주만 URL 로 열고, 그다음은 '이전 주' 단추를 1회씩 눌러 순차로 읽는다. 매번 화면 머리의 날짜 범위가
    기대한 주와 같을 때만 그 주를 읽음으로 하고, 다르면 그 주의 행을 버린다(클릭 수 ≤ 주 수 + 3).
  · 전용 Edge 는 copilot_auto.edge_lock 안에서만 쓰고(다른 작업과 직렬), 이 수집기가 연 탭만 닫는다(로그인 대기면 둔다).

화면 구조는 Microsoft 가 바꿀 수 있어 '역할(role)·aria-label·title' 같은 접근성 속성만 의지하고, 무엇을 몇 개
인식했는지 로그에 남긴다(회사 PC 의 원문을 밖으로 보낼 수 없으므로 진단은 로그 숫자로 한다).
발신/수신 구분: 받은 편지함·보낸 편지함 폴더 URL 을 따로 열어 슬라이스마다 검색하고(폴더가 곧 box), 화면에
폴더명 조각('보낸 편지함')이 있으면 그것을 우선한다 — 제목·미리보기의 영어 단어(presentation·consent·
'Sent from my iPhone')로 발신을 판정하던 부분 문자열 규칙은 폐기(감사 outlook-5).
시험용: LM_OWA_FAKE=<json> 이면 브라우저 없이 그 파일의 항목을 화면 대신 쓴다(회귀용 — 검색·스크롤·주 이동은 건너뛴다).
        mail: {"YYYY-MM": [item…]} (받은 편지함 슬라이스) 또는 {"YYYY-MM": {"inbox": [...], "sent": [...]}}
        검색 무시·URL 무시 같은 화면 결함 재현은 tests\\fakes\\fake_browser.py(FakeBrowser — 이 모듈의 JS 상수에 각본 응답)로 한다.
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
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:                  # Get-TeamsWeb 이 이 파일을 경로로 불러도 owa_parse 를 찾게
    sys.path.insert(0, _HERE)
import owa_parse  # noqa: E402  — LM28 순수 판정 함수(목록 날짜·조각 판정·주 머리·병합)

_sleep = time.sleep                        # 시험(FakeBrowser)이 대기를 0 으로 바꿀 수 있게 — 수집 루프의 대기만
OUT_DIR = os.path.join(ROOT, "data", "outlook")
COLLECTOR_VER = "LM28-OWA-1"               # 판정 규칙의 판 — mail_source 에 '판|collect.cursorEpoch' 로 싣는다
SEARCH_SCREENS = 150                       # 검색 결과 한 조각을 내리는 화면 수 상한(LM24 의 달마다 400회 대신)
LIST_SCREENS = 800                         # 폴백(검색 없이 최신부터) 한 폴더를 내리는 화면 수 상한
STALL_MAX = 3                              # 새 항목 없는 화면이 이만큼 이어지면 멈춘다
CAL_RETRY = 3                              # '이전 주' 단추가 안 먹었을 때(머리 그대로) 다시 누르는 횟수(전체)
AXIS_OF = {"inbox": "mail_in", "sent": "mail_out"}
FOCUSED_WORDS = ("중요", "기타", "focused", "other")   # 받은 편지함 '중요/기타' 탭 — 목록 폴백은 한쪽만 보여 준다
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


def parse_mail_item(item, d0, d1, folder="", today=None, info=None):
    """화면 항목(aria-label·title·leaf texts) → [box,time,sender,subject,conversation,rcv,time_precision] 또는 None
    folder: 이 항목을 읽은 폴더 슬라이스('inbox'|'sent'|'') — 화면에 폴더명 조각이 없을 때의 box.
    today: 목록의 상대 날짜(오늘=시각만·이번 주=요일+시각·어제)를 풀 기준 날(LM28 F-04 — 없으면 오늘).
    info(dict): 판정용 메모 — date(항목 날짜, 지운·정크 폴더 항목도), src(시각 출처 head·lm24·text, 날짜만이면 '')."""
    label = item.get("label") or ""
    titles = [t for t in (item.get("titles") or []) if t]
    texts = [t for t in (item.get("texts") or []) if t]
    pool = titles + [label] + texts
    info = info if info is not None else {}
    td = today or date.today()
    # ★ 날짜는 **머리 조각(title·aria-label)에서만** 찾는다. texts 는 발신자·제목·미리보기(본문 앞머리)라
    #   회신 메일이면 인용문 머리글('2026년 6월 12일 (금) 오전 10:00, 홍길동 님이 작성:')이 그대로 들어 있다.
    #   그것을 시각으로 쓰면 9월 회신이 6월 메일이 되고, 6월 리뷰에 하지도 않은 최근 일이 등장한다(제보).
    #   미리보기에 인용문이 있는 것은 한국어 Outlook 에서 흔해 발생 빈도가 높다.
    head = titles + [label]
    when = None
    precision = "minute"
    src = ""
    # LM28(F-04): 머리 글을 쉼표 조각으로 나눠 '날짜·시각뿐인 조각'을 먼저 본다 — 목록의 오늘(시각만)·이번 주(요일+시각)·
    #   어제 표기도 날짜로 읽고, 제목 속 '3/5 보고' 같은 글은 날짜로 읽지 않는다. 시각까지 있을 때만 여기서 확정한다.
    pure_d = None
    for cand in head:
        r = owa_parse.list_when(owa_parse.frags_of(cand), td, d0, d1)
        if r and r[1]:
            when, src = (r[0], r[1]), "head"
            break
        if r and pure_d is None:
            pure_d = r[0]
    if not when:
        for cand in head:
            d = find_date(cand, d0, d1)
            ts = find_times(cand)
            if d and ts:
                when, src = (d, ts[0]), "lm24"
                break
    if not when:
        d = pure_d
        ts = None
        for cand in head:
            d = d or find_date(cand, d0, d1)
            ts = ts or (find_times(cand) or None)
        src = "lm24"
        # 시각은 본문 조각에서 와도 된다(날짜를 머리에서 이미 짚었을 때만) — 날짜만 본문에서 오면 안 된다.
        if d and not ts:
            src = "text"
            for cand in texts:
                ts = ts or (find_times(cand) or None)
        if d and ts:
            when = (d, ts[0])
        elif d:
            when = (d, (12, 0))             # 날짜만 보이는 항목 — 00:00 은 '새벽 산출물' 이 된다. 주간 중앙 + 정밀도 표시
            precision, src = "date", ""
    if not when:
        # LM28(F-04): 머리에 날짜가 전혀 없으면 목록 칸 잎 글자 — 글 전체가 날짜·시각뿐인 잎만('화 오후 3:12'·'어제').
        #   미리보기 잎은 다른 글이 섞여 있어 여기에 걸리지 않는다(인용문 머리글 오독 방지는 그대로).
        r = owa_parse.list_when(texts, td, d0, d1)
        if r:
            when = (r[0], r[1] or (12, 0))
            precision, src = ("minute", "text") if r[1] else ("date", "")
    if not when:
        return None
    info["date"] = when[0]
    info["src"] = src
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
# JS 상수 머리의 /*LM28:이름*/ 은 시험의 FakeBrowser 가 어느 화면 읽기인지 알아보는 표식이다(페이지에서는 주석).
# LM28: 항목마다 idx(열기용)·dts(시각이 든 다른 title·aria-label·datetime 속성 — 시각 복원용, LM24 의 title 12개 상한 밖까지),
#       화면마다 empty('결과 없음/비어 있음' 표식 — 항목이 0일 때만)·sel(선택된 폴더 이름)·pivots(선택된 탭 글 — 중요/기타)를 낸다.
JS_MAIL = r"""/*LM28:owa_list*/
(() => {
  const out = {href: location.href, n: 0, items: [], listboxes: 0, search: false, empty: false, sel: "", pivots: []};
  const sb = document.querySelector('#topSearchInput, input[role="searchbox"], [role="search"] input, input[aria-label*="검색"], input[aria-label*="Search"], input[placeholder*="검색"], input[placeholder*="Search"]');
  out.search = !!sb;
  let opts = [...document.querySelectorAll('[role="listbox"] [role="option"]')];
  out.listboxes = document.querySelectorAll('[role="listbox"]').length;
  if (!opts.length) opts = [...document.querySelectorAll('[role="option"]')];
  if (!opts.length) opts = [...document.querySelectorAll('[role="row"][aria-label], [data-convid], [data-item-id]')];
  window.__lm_mail = opts;
  out.n = opts.length;
  if (!opts.length) {
    const m = document.querySelector('[role="main"]') || document.body;
    const t = ((m && m.innerText) || "").slice(0, 3000);
    out.empty = /결과가 없|결과를 찾을 수 없|찾지 못했|항목이 없|비어 있|didn.t find|did not find|no results|no items|nothing in (this )?folder|folder is empty/i.test(t);
  }
  const ts = document.querySelector('[role="treeitem"][aria-selected="true"]');
  out.sel = ts ? ((ts.getAttribute("title") || ts.textContent || "").trim().slice(0, 40)) : "";
  out.pivots = [...document.querySelectorAll('[role="tab"][aria-selected="true"]')].map(x => (x.textContent || "").trim().slice(0, 20)).filter(Boolean).slice(0, 6);
  out.items = opts.slice(0, 600).map((o, i) => ({
    idx: i,
    key: (o.getAttribute("data-convid") || o.getAttribute("data-item-id") || o.id || "") + "|" + (o.getAttribute("aria-label") || "").slice(0, 80),
    label: o.getAttribute("aria-label") || "",
    titles: [...o.querySelectorAll("[title]")].map(x => x.getAttribute("title") || "").filter(Boolean).slice(0, 12),
    texts: [...o.querySelectorAll("span,div,a")].filter(x => x.childElementCount === 0).map(x => (x.textContent || "").trim()).filter(Boolean).slice(0, 24),
    dts: [...o.querySelectorAll("[datetime],[title],[aria-label]")].map(x => x.getAttribute("datetime") || x.getAttribute("title") || x.getAttribute("aria-label") || "").filter(v => v && v.length <= 80 && /\d{1,2}[:.]\d{2}/.test(v)).slice(0, 6)
  }));
  return JSON.stringify(out);
})()
"""
# LM28: 'fits' = 스크롤 영역이 없고 목록 전체가 화면 안(끝까지 보임) · 'no-scroller' = 스크롤 영역을 못 찾음(끝을 모른다)
JS_SCROLL = r"""/*LM28:owa_scroll*/
(() => {
  const lb = document.querySelector('[role="listbox"]') || document.querySelector('[role="option"]');
  if (!lb) return "no-list";
  let el = lb, found = false;
  for (let i = 0; i < 12 && el; i++) {
    if (el.scrollHeight > el.clientHeight + 20 && getComputedStyle(el).overflowY !== "visible") { found = true; break; }
    el = el.parentElement;
  }
  if (!found) {
    const r = lb.getBoundingClientRect();
    return (r.bottom <= window.innerHeight + 2 && lb.scrollHeight <= lb.clientHeight + 4) ? "fits" : "no-scroller";
  }
  const before = el.scrollTop;
  el.scrollTop = el.scrollTop + Math.max(200, el.clientHeight - 40);
  el.dispatchEvent(new Event("scroll", {bubbles: true}));
  return (el.scrollTop > before) ? "scrolled" : "end";
})()
"""
# LM28: 일정 화면 머리(heads — 날짜 범위가 든 짧은 글)·열 머리(cols)·바탕(grid) 도 낸다(F-05 — 그 주가 맞는지 확인)
JS_CAL = r"""/*LM28:owa_cal*/
(() => {
  const out = {href: location.href, n: 0, events: [], heads: [], cols: [], grid: false};
  out.grid = !!document.querySelector('[role="grid"], [role="main"] [role="row"]');
  const hs = new Set();
  for (const e of document.querySelectorAll('[role="heading"], h1, h2, h3, button, [aria-live]')) {
    for (const v of [e.getAttribute("aria-label") || "", (e.textContent || "").trim()]) {
      if (v && v.length <= 80 && /\d/.test(v) && /[–—~〜-]/.test(v)) hs.add(v);
    }
    if (hs.size >= 40) break;
  }
  out.heads = [...hs];
  out.cols = [...document.querySelectorAll('[role="columnheader"]')].map(x => (x.getAttribute("aria-label") || x.textContent || "").trim()).filter(v => v && v.length <= 60).slice(0, 10);
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
# LM28(F-05): 주 보기의 '이전 주' 단추 — 주/week 가 든 이름을 먼저, 없으면 '이전'·'Previous' 로 시작하는 이름
JS_CAL_PREV = r"""/*LM28:owa_cal_prev*/
(() => {
  const bs = [...document.querySelectorAll('button[aria-label], [role="button"][aria-label]')].filter(b => !b.disabled && b.offsetParent !== null);
  const pick = rx => bs.find(b => rx.test((b.getAttribute("aria-label") || "").trim()));
  const b = pick(/이전 ?주|지난 ?주|previous week/i) || pick(/^(이전|previous|go to previous|go back)/i);
  if (!b) return "none";
  b.click();
  return "ok";
})()
"""
# LM28(UD-08 보완): 보낸 편지함 항목 하나를 연다(받은 메일은 열지 않는다 — 읽음 표시). __IDX__ = owa_list 의 idx
JS_OPEN = r"""/*LM28:owa_open*/
(() => {
  const e = (window.__lm_mail || [])[__IDX__];
  if (!e || !e.isConnected) return "gone";
  for (const t of ["pointerdown", "mousedown", "pointerup", "mouseup", "click"]) {
    e.dispatchEvent(new MouseEvent(t, {bubbles: true, cancelable: true, view: window}));
  }
  return "ok";
})()
"""
# 읽기 창 머리의 보낸 시각 조각만(title·datetime·글자 120자) — 본문은 읽지 않는다(LM27 선택자 이식)
JS_HEAD = r"""/*LM28:owa_head*/
(() => {
  const sels = ['[data-testid="SentReceivedSavedTime"]', '[role="main"] [data-testid*="Time"]', '[role="main"] time'];
  const out = {found: false, head: []};
  for (const s of sels) {
    for (const e of document.querySelectorAll(s)) {
      const t = ((e.getAttribute("title") || "") + " " + (e.getAttribute("datetime") || "") + " " + (e.textContent || "")).trim().slice(0, 120);
      if (t) out.head.push(t);
      if (out.head.length >= 4) break;
    }
    if (out.head.length) { out.found = true; break; }
  }
  return JSON.stringify(out);
})()
"""
JS_FOCUS_SEARCH = r"""/*LM28:owa_focus_search*/
(() => {
  const sels = ['#topSearchInput', 'input[role="searchbox"]', '[role="search"] input', 'input[aria-label*="검색"]', 'input[aria-label*="Search"]', 'input[placeholder*="검색"]', 'input[placeholder*="Search"]', '[role="combobox"][aria-label*="검색"]', '[role="combobox"][aria-label*="Search"]'];
  const vis = el => { const r = el.getBoundingClientRect(); return r.width > 40 && r.height > 8; };
  for (const s of sels) { for (const c of document.querySelectorAll(s)) { if (vis(c)) { c.focus(); c.click(); window.__lm_sb = c; return "ok:" + s; } } }
  const btn = document.querySelector('button[aria-label*="검색"], button[aria-label*="Search"]');
  if (btn) { btn.click(); return "button"; }
  return "none";
})()
"""
JS_CLEAR_SEARCH = r"""/*LM28:owa_clear_search*/
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
        self.own_tab = ""          # LM28: 이 수집기가 /json/new 로 연 탭 id — 끝에 이것만 닫는다(사람·다른 작업의 탭은 두기)
        self.reason = ""           # LM28: 로그인·기동 실패 사유 코드(LMSTATUS reason)

    def start(self):
        if not self.ca.ensure_edge(self.cfg):
            self.reason = self.ca.LAST.get("reason") or "R-EDGELAUNCH"     # R-EDGEPOL·R-EDGEFOREIGN·R-EDGELAUNCH(WP5)
            return False
        tabs = [t for t in self.ca.http_json(self.port, "/json") if t.get("type") == "page"]
        ws = None
        for t in tabs:
            # LM28: 호스트 정확 일치(부분 문자열 금지 — C-36)
            if self.ca.host_in(self.ca._host(t.get("url")), HOSTS):
                ws = t["webSocketDebuggerUrl"]
                break
        if not ws:
            for method in ("PUT", "GET"):
                try:
                    t = self.ca.http_json(self.port, "/json/new?" + quote(MAIL_URL, safe=""), method=method)
                    ws = t["webSocketDebuggerUrl"]
                    self.own_tab = str(t.get("id") or "")
                    break
                except Exception:
                    continue
        if not ws:
            self.reason = "R-EDGELAUNCH"
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

    def kind(self, url):
        """탭 주소 → copilot_auto.page_kind(호스트 정확·마디 일치 — WP5). 개인 Outlook(outlook.live.com)은 개인 계정 화면이다."""
        k = "personal" if self.ca._host(url) == "outlook.live.com" else self.ca.page_kind(url, self.cfg)
        if k == "personal" and not self.ca._truthy(self.cfg.get("requireWorkAccount"), True):
            return "work" if self.ca.host_in(self.ca._host(url), HOSTS) else "login"     # LM24 처럼(개인 계정 허용 설정)
        return k

    def _login(self, kind):
        """로그인 화면 → 'login' | 'personal'. 사유(AADSTS 번호로 나눔)를 남기고, 사람이 그 탭에서 로그인하는 중일 수 있으니
        owner.json 에 로그인 대기를 적는다(close_own_edge 가 창을 닫지 않게 — WP5)."""
        if kind == "personal":
            self.reason = "R-PERSONAL"
        else:
            code = ""
            if kind in ("login", "adfs"):
                try:
                    code = str(self.cdp.eval(self.ca.js_aadsts(), timeout=10) or "")
                except Exception:
                    code = ""
            self.reason = self.ca.aadsts_reason(code) if code else "R-LOGIN"
        try:
            self.ca._update_owner(self.cfg, login_pending=time.strftime("%Y-%m-%d %H:%M:%S"))
        except Exception:
            pass
        return "personal" if kind == "personal" else "login"

    def wait_ready(self, settle=6.0, limit=75):
        """로드 완료 + 목록/로그인 판별 → 'login' | 'personal' | 'ok' | 'timeout'
        LM28: 로그인 판정은 주소의 부분 문자열이 아니라 page_kind 로(WP5). Outlook 호스트가 아닌 곳(회사 IdP 등)에서 끝까지
        머물면 로그인 대기로 본다 — 회사 로그인 화면에도 role=main 이 있어 예전엔 그 화면을 '준비됨'으로 읽었다."""
        t0 = time.time()
        kind = ""
        while time.time() - t0 < limit:
            time.sleep(1.0)
            h = self.href()
            kind = self.kind(h)
            if kind in ("login", "adfs", "personal"):
                return self._login(kind)
            if not self.ca.host_in(self.ca._host(h), HOSTS):
                continue
            try:
                rs = self.cdp.eval("document.readyState")
                n = int(self.cdp.eval('document.querySelectorAll(\'[role="listbox"],[role="grid"],[role="main"]\').length') or 0)
            except Exception:
                rs, n = "", 0
            if rs == "complete" and n > 0:
                time.sleep(settle)
                h = self.href()
                kind = self.kind(h)
                if kind in ("login", "adfs", "personal"):
                    return self._login(kind)
                try:
                    self.ca._update_owner(self.cfg, login_pending="")
                except Exception:
                    pass
                return "ok"
        if kind in ("other", "mixed"):
            return self._login(kind)
        self.reason = "R-TIMEOUT"
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

    def close(self, keep_tab=False):
        """CDP 연결을 닫고, 이 수집기가 연 탭만 닫는다(keep_tab — 로그인 대기면 사람이 그 탭에서 로그인한다)."""
        try:
            if self.cdp:
                self.cdp.close()
        except Exception:
            pass
        if self.own_tab and not keep_tab:
            try:
                self.ca._close_tab(self.port, self.own_tab)
            except Exception:
                pass
            self.own_tab = ""


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


def _days(d0, d1):
    out, d = [], d0
    while d <= d1:
        out.append(d)
        d += timedelta(days=1)
    return out


class Run:
    """한 번의 수집(LM28) — 기간·오늘·시간 예산·계수(LMSTATUS counts)·화면 진단(selector_diag)·시각 복원 예산.
    시험은 today·deadline 을 넘긴다(deadline=None 이면 예산 없음)."""

    def __init__(self, d0, d1, today=None, deadline=None, recover_max=150):
        self.d0, self.d1 = d0, d1
        self.today = today or date.today()
        self.deadline = deadline
        try:
            self.recover_left = max(0, int(recover_max))
        except (TypeError, ValueError):
            self.recover_left = 150
        self.timed_out = False
        self.last_head = None
        self.c = {"slices_ok": 0, "list_verified": 0, "filter_ineffective": 0, "slices_unverified": 0,
                  "fallback_scroll": 0, "weeks_ok": 0, "weeks_unverified": 0, "cal_clicks": 0,
                  "date_only": 0, "recovered": 0, "opened": 0, "rows": 0}
        self.sd = {}

    def bump(self, k, n=1):
        self.sd[k] = self.sd.get(k, 0) + n

    def out_of_time(self):
        if self.deadline is not None and time.time() >= self.deadline:
            self.timed_out = True
        return self.timed_out


def _when_from(strings, day, today, d0=None, d1=None):
    """시각이 든 글들(title·aria-label·<time datetime>·읽기 창 머리) → 그 날짜(day)의 (시, 분) | None.
    ISO(Z·오프셋)는 로컬로 바꾼다(C-35). 날짜가 행의 날짜와 같을 때만 받는다 — 다른 날의 시각을 붙이지 않게."""
    for s in strings or ():
        s = str(s or "")
        r = owa_parse.iso_local(s)
        if r and r[0] == day:
            return r[1]
        r = owa_parse.list_when(owa_parse.frags_of(s), today, d0, d1)
        if r and r[1] and r[0] == day:
            return r[1]
        ts = find_times(s)
        if ts and find_date(s, d0, d1) == day:
            return ts[0]
    return None


def _open_head(br, run, it):
    """보낸 편지함 항목을 열어 읽기 창 머리의 시각 글 → [글] | None. 지금 화면에 있는 항목만(idx — owa_list 의 순번).
    머리가 앞 항목 것과 같으면(아직 안 바뀜) 잠깐 더 기다린다."""
    try:
        idx = int(it.get("idx"))
    except (TypeError, ValueError):
        return None
    try:
        r = str(br.cdp.eval(JS_OPEN.replace("__IDX__", str(idx))) or "")
    except Exception:
        r = ""
    if r != "ok":
        run.bump("open_fail")
        return None
    run.c["opened"] += 1
    for _ in range(4):
        _sleep(0.8)
        try:
            h = br.eval_json(JS_HEAD) or {}
        except Exception:
            h = {}
        head = [str(x) for x in h.get("head") or [] if x]
        if h.get("found") and head and tuple(head) != run.last_head:
            run.last_head = tuple(head)
            return head
    run.bump("head_none")
    return None


def _recover(br, run, it, r, folder):
    """날짜만 행(r)의 시각 복원(LM28 UD-08 보완) — ① 항목의 다른 title·aria-label·<time datetime>(목록 화면에 이미 있음)
    ② 보낸 편지함은 그래도 없으면 항목을 열어 읽기 창 머리(owaTimeRecoverMax 건까지·예산 안 — 받은 메일은 열지 않는다)."""
    day = date.fromisoformat(r[1][:10])
    hm = _when_from(it.get("dts") or [], day, run.today, run.d0, run.d1)
    if hm is None and folder == "sent" and br is not None and run.recover_left > 0 and not run.out_of_time():
        run.recover_left -= 1
        hm = _when_from(_open_head(br, run, it) or [], day, run.today, run.d0, run.d1)
    if not hm:
        return False
    r[1] = f"{r[1][:10]} {hm[0]:02d}:{hm[1]:02d}"
    r[6] = "minute"
    run.c["recovered"] += 1
    return True


def _folder_mismatch(folder, sel):
    """화면 왼쪽에 선택된 폴더 이름이 읽으려는 폴더의 반대면 True — 보낸 편지함 주소가 무시돼 받은 편지함이 보이는 화면을
    발신(능동 신호)으로 읽지 않게. 이름을 모르면 False(LM24 처럼 읽은 폴더를 믿는다)."""
    s = re.sub(r"[\d\s,()]+$", "", str(sel or "")).strip().lower()
    if not s:
        return False
    return s in (INBOX_WORDS if folder == "sent" else SENT_WORDS)


def _focused(pivots):
    return any(str(p or "").strip().lower() in FOCUSED_WORDS for p in pivots or ())


def _read_screens(br, run, folder, s, e, list_mode):
    """지금 화면(검색 결과 또는 폴더 목록)을 위에서부터 내린다 → (got, meta).
    got = [(항목, 날짜|None, 행|None)] 화면 순서 · meta = {reached, empty, sel, pivots, screens}.
    검색 화면은 조각 밖(앞뒤 1일 여유 밖) 날짜가 보이면 바로 멈추고(검색이 안 걸림 — 더 내려 봐야 폴더 목록이다),
    목록 화면(폴백)은 가장 깊은 날짜가 기간 시작(run.d0)보다 앞서면 멈춘다. 끝 판정은 'fits'(목록 전체가 보임) 또는
    'end' 뒤 새 항목 없는 화면 2번. 'no-scroller'·화면 수 상한·예산이면 끝을 모른 채 멈춘다(그 아래 날은 partial)."""
    got, seen_k = [], set()
    meta = {"reached": False, "fits": False, "empty": False, "sel": "", "pivots": [], "screens": 0}
    h0, h1 = (run.d0, run.d1) if list_mode else (s, e)
    lo, hi = s - timedelta(days=1), e + timedelta(days=1)
    # 시각 복원은 받을 행만 — 검색 화면은 그 조각 안 날짜만(검색이 안 걸린 화면의 행은 버려지고 폴백이 다시 읽는다)
    d0s, d1s = (run.d0.isoformat(), run.d1.isoformat()) if list_mode else (max(s, run.d0).isoformat(),
                                                                           min(e, run.d1).isoformat())
    cap = LIST_SCREENS if list_mode else SEARCH_SCREENS
    stall = 0
    while meta["screens"] < cap:
        if run.out_of_time():
            break
        try:
            pg = br.eval_json(JS_MAIL) or {}
        except Exception:
            run.bump("js_error")
            break
        meta["screens"] += 1
        if meta["screens"] == 1:
            meta["sel"] = str(pg.get("sel") or "")
            meta["pivots"] = [str(x) for x in pg.get("pivots") or []]
            run.bump("listbox" if pg.get("listboxes") else "listbox_none")
        items = [it for it in pg.get("items") or [] if isinstance(it, dict)]
        if not items and pg.get("empty"):
            meta["empty"] = True
        if not got and not items and not meta["empty"] and meta["screens"] < 3:
            _sleep(1.5)                     # 목록이 아직 안 그려졌을 수 있다 — 잠깐 더
            continue
        new = []
        for it in items:
            k = it.get("key") or json.dumps(it, ensure_ascii=False)[:200]
            if k not in seen_k:
                seen_k.add(k)
                new.append(it)
        stop = False
        for it in new:
            info = {}
            r = parse_mail_item(it, h0, h1, folder, run.today, info)
            d = info.get("date")
            got.append((it, d, r))
            if d is not None and not list_mode and (d < lo or d > hi):
                stop = True                 # 검색이 안 걸린 화면 — 더 내리지 않는다
            if r and r[6] == "date" and d0s <= r[1][:10] <= d1s:
                _recover(br, run, it, r, folder)
        if stop:
            break
        if list_mode:
            ds = [g[1] for g in got if g[1]]
            if ds and ds[-1] < run.d0:
                break                       # 기간 시작 앞 날짜에 닿았다
        stall = 0 if new else stall + 1
        if stall >= STALL_MAX:
            break
        try:
            sr = str(br.cdp.eval(JS_SCROLL) or "")
        except Exception:
            sr = ""
        if sr == "fits":
            meta["reached"] = meta["fits"] = True
            run.bump("fits")
            break
        if sr in ("no-list", "no-scroller"):
            run.bump(sr)
            break
        if sr == "end" and stall >= 2:
            meta["reached"] = True
            break
        _sleep(1.0)
    else:
        run.bump("screen_cap")
    return got, meta


def collect_mail(br, d0, d1, fake=None, today=None, run=None):
    """달 × 폴더(받은 편지함 → 보낸 편지함) 슬라이스로 읽는다. box 는 (화면의 폴더명 조각) > (읽은 폴더) 순.
    검색 범위가 '모든 폴더'로 잡힌 OWA 라도 같은 항목(key)은 먼저 읽은 받은 편지함 슬라이스에 남으므로
    발신이 수신으로 격하될 뿐, 수신이 발신(능동 신호)이 되는 방향의 오류는 생기지 않는다.
    LM28(F-03): 조각마다 owa_parse.slice_verdict 로 '읽음'을 판정한다. 검색이 안 걸린 폴더(filter_ineffective·unverified)는
    폴더당 1회 폴백 — 검색을 지우고(폴더 주소로 다시 열기) 최신부터 기간 시작 앞까지 내려 기간 전체를 list_verified 로 판정하고,
    그 폴더의 남은 조각은 건너뛴다. 검색이 안 걸린 화면의 행은 버린다(폴백이 다시 읽는다).
    → (행, 상태 ok|empty|login|personal, diag, {축 mail_in·mail_out: {날짜: st}})"""
    run = run or Run(d0, d1, today)
    rows, seen = [], set()
    diag = {"search": 0, "items": 0, "parsed": 0, "sent": 0, "cc": 0, "date_only": 0, "pages": 0, "sent_pass_new": 0}
    day_st = {ax: dict.fromkeys(_days(d0, d1), "unverified") for ax in ("mail_in", "mail_out")}
    fell = set()                            # 폴백을 마친 폴더 — 남은 조각은 그 폴백이 이미 덮었다
    d0s, d1s = d0.isoformat(), d1.isoformat()

    def take(got, folder, skip_days=()):
        n = 0
        for it, _d, r in got:
            k = it.get("key") or json.dumps(it, ensure_ascii=False)[:200]
            if k in seen:
                continue
            seen.add(k)
            diag["items"] += 1
            if folder == "sent":
                diag["sent_pass_new"] += 1
            if not r or not (d0s <= r[1][:10] <= d1s) or r[1][:10] in skip_days:
                continue
            diag["parsed"] += 1
            if r[0] == "sent":
                diag["sent"] += 1
            elif r[5] == "cc":
                diag["cc"] += 1
            rows.append(r)
            n += 1
        return n

    for s, e in months_of(d0, d1):
        mon_n, tried = 0, False
        for folder, url in MAIL_FOLDERS:
            if folder in fell or run.out_of_time():
                continue
            tried = True
            ax = AXIS_OF[folder]
            if fake is not None:            # 회귀용(LM_OWA_FAKE) — 검색·스크롤 없이 그 달 항목이 곧 검색 결과
                got = []
                for it in _fake_mail_batch(fake, s.strftime("%Y-%m"), folder):
                    info = {}
                    r = parse_mail_item(it, s, e, folder, run.today, info)
                    if r and r[6] == "date":
                        _recover(None, run, it, r, folder)
                    got.append((it, info.get("date"), r))
                diag["pages"] += 1
                v, D = owa_parse.slice_verdict([g[1] for g in got], s, e, bool(fake.get("empty_marker")), False, True)
            else:
                st = br.goto(url)
                if st in ("login", "personal"):
                    return rows, st, diag, day_st
                if st != "ok":
                    run.bump("goto_timeout")
                    continue
                ok = br.search(f"received>={s.isoformat()} received<={e.isoformat()}")
                got, v, D = [], "unverified", None
                if ok:
                    diag["search"] += 1
                    got, meta = _read_screens(br, run, folder, s, e, False)
                    diag["pages"] += meta["screens"]
                    v, D = owa_parse.slice_verdict([g[1] for g in got], s, e, meta["empty"], False, meta["reached"])
                    if _folder_mismatch(folder, meta["sel"]):
                        run.bump("folder_mismatch")
                        got, v, D = [], "unverified", None
                else:
                    run.bump("search_none")
                if v in ("filter_ineffective", "unverified"):
                    run.c["filter_ineffective" if v == "filter_ineffective" else "slices_unverified"] += 1
                    # 폴백 — 폴더당 1회. 이미 읽음(ok·zero_ok·partial)인 날의 행은 앞 검색에서 받았으므로 다시 받지 않는다.
                    fell.add(folder)
                    run.c["fallback_scroll"] += 1
                    st = br.goto(url)
                    if st in ("login", "personal"):
                        return rows, st, diag, day_st
                    if st != "ok":
                        run.bump("goto_timeout")
                        continue
                    got, meta = _read_screens(br, run, folder, d0, d1, True)
                    diag["pages"] += meta["screens"]
                    # 목록 끝은 'fits'(전부 보임)일 때만 믿는다 — 'end' 는 지연 로드가 늦었을 수 있다
                    v, D = owa_parse.slice_verdict([g[1] for g in got], d0, d1, meta["empty"], True, meta["fits"])
                    if _folder_mismatch(folder, meta["sel"]):
                        run.bump("folder_mismatch")
                        got, v, D = [], "unverified", None
                    rng = owa_parse.verdict_ranges(v, D, d0, d1)
                    if folder == "inbox" and _focused(meta["pivots"]):
                        # '중요/기타' 탭이 켜진 받은 편지함 — 목록은 한쪽만 보여 준다. 행은 받되 '읽음'으로 적지 않는다
                        run.bump("focused_pivot")
                        rng = [(a, b, "partial" if x == "ok" else x) for a, b, x in rng]
                    if v == "list_verified":
                        run.c["list_verified"] += 1
                    done = {dd.isoformat() for dd, x in day_st[ax].items() if x != "unverified"}
                    mon_n += take(got, folder, done)
                    owa_parse.apply_ranges(day_st[ax], rng, run.today)
                    log(f"메일 {folder}: 기간 검색이 걸리지 않아({v if v != 'list_verified' else '폴백'}) 목록을 최신부터 "
                        f"{meta['screens']}화면 내려 읽음 — {'D=' + D.isoformat() if D else '판정 불가'}")
                    continue
            if v in ("ok", "empty_verified"):
                run.c["slices_ok"] += 1
            elif v == "list_verified":
                run.c["list_verified"] += 1
            elif v == "filter_ineffective":
                run.c["filter_ineffective"] += 1
            else:
                run.c["slices_unverified"] += 1
            owa_parse.apply_ranges(day_st[ax], owa_parse.verdict_ranges(v, D, s, e), run.today)
            mon_n += take(got, folder)
        if tried:                           # 두 폴더 모두 폴백이 덮은 달은 읽지 않았다 — 줄을 남기지 않는다
            log(f"메일 {s.strftime('%Y-%m')}: 항목 {diag['items']}개 중 해석 {mon_n}건 누적 {len(rows)}건"
                f" (보낸 편지함 슬라이스 신규 {diag['sent_pass_new']}개)")
    rows.sort(key=lambda r: r[1])
    diag["date_only"] = sum(1 for r in rows if r[6] == "date")
    return rows, ("ok" if rows else "empty"), diag, day_st


def _cal_page(br, tries=3):
    """주 보기 한 장(일정·머리·열 머리) — 바탕이 뜰 때까지 짧게 기다린다."""
    pg = {}
    for _ in range(tries):
        try:
            pg = br.eval_json(JS_CAL) or {}
        except Exception:
            pg = {}
        if pg.get("grid") or pg.get("n") or pg.get("heads"):
            return pg
        _sleep(1.5)
    return pg


def cal_screen_range(pg, today=None):
    """주 보기 화면 → 보이는 날짜 범위 (시작, 끝) | None — 머리 글(owa_parse.week_header_range) 먼저, 없으면 열 머리의
    날짜(3개 이상 · 7일 안)."""
    for h in pg.get("heads") or []:
        r = owa_parse.week_header_range(h, today)
        if r:
            return r
    ds = sorted({d for c in pg.get("cols") or [] for d in [find_date(str(c))] if d})
    if len(ds) >= 3 and (ds[-1] - ds[0]).days <= 6:
        return ds[0], ds[-1]
    return None


def collect_cal(br, d0, d1, fake=None, today=None, run=None):
    """주 보기로 일정을 읽는다. LM28(F-05): 가장 최근 주(d1 이 든 주)만 URL 로 열고, 그다음은 '이전 주' 단추를 1회씩 눌러
    순차로 읽는다. 매번 화면 머리의 날짜 범위(cal_screen_range)가 기대한 주와 같을 때만 그 주를 읽음(ok)으로 하고 행을 받는다 —
    다르면(머리 못 읽음·다른 주) 그 주는 unverified, 행은 버린다. 단추가 안 먹어 머리가 그대로면 CAL_RETRY 번까지 다시 누른다.
    클릭 수 ≤ 주 수 + CAL_RETRY(URL 이 무시돼 더 뒤 주가 보이면 거슬러 가는 만큼 더한다). 예전에는 주마다 URL 로 이동하고
    그리드만 보이면 그 주를 읽음으로 쳤다 — URL 이 무시되면 매주 이번 주만 보고 완료로 적었다.
    → (행, 상태 ok|empty|login|personal|timeout|unverified, diag, {날짜: st})"""
    run = run or Run(d0, d1, today)
    rows, seen = [], set()
    diag = {"weeks": 0, "events": 0, "parsed": 0}
    day_st = dict.fromkeys(_days(d0, d1), "unverified")
    one = timedelta(days=1)

    def keep(evs, hs, he, check):
        """그 주 화면의 일정 → 행(기간과 겹치는 것만·중복 한 번). check 면 일정이 그 주 밖일 때(바탕이 아직 앞 주) None."""
        got = []
        for ev in evs:
            r = parse_event(ev, hs, he)
            if not r:
                continue
            if check and (r[1][:10] < (hs - one).isoformat() or r[0][:10] > (he + one).isoformat()):
                return None
            got.append(r)
        diag["events"] += len(evs)
        for r in got:
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
        return got

    def done(st):
        rows.sort(key=lambda r: r[0])
        log(f"일정: {diag['weeks']}주(확인 {run.c['weeks_ok']} · 미확인 {run.c['weeks_unverified']} · 클릭 "
            f"{run.c['cal_clicks']}) · 요소 {diag['events']}개 중 해석 {len(rows)}건 (다일 {diag.get('multi_day', 0)}건)")
        return rows, st, diag, day_st

    if fake is not None:                    # 회귀용(LM_OWA_FAKE) — LM24 처럼 월요일 주마다, 각본에 있는 주는 읽음
        cur = d0 - timedelta(days=d0.weekday())
        while cur <= d1:
            diag["weeks"] += 1
            evs = (fake.get("cal") or {}).get(cur.isoformat())
            keep([ev for ev in evs or [] if isinstance(ev, dict)], cur, cur + timedelta(days=6), False)
            if evs is not None:
                run.c["weeks_ok"] += 1
                owa_parse.apply_ranges(day_st, [(max(cur, d0), min(cur + timedelta(days=6), d1), "ok")], run.today)
            cur += timedelta(days=7)
        return done("ok" if rows else "empty")

    w7 = timedelta(days=7)
    n_weeks = ((d1 - timedelta(days=d1.weekday())) - (d0 - timedelta(days=d0.weekday()))).days // 7 + 1
    st = br.goto(f"{CAL_URL}/{d1.year}/{d1.month}/{d1.day}", wait=5.0)
    if st in ("login", "personal"):
        return rows, st, diag, day_st
    if st != "ok":
        run.bump("goto_timeout")
        return done("timeout")
    pg = _cal_page(br)
    ref = cal_screen_range(pg, run.today)
    if ref is None:
        _sleep(2.0)
        pg = _cal_page(br)
        ref = cal_screen_range(pg, run.today)
    if ref is None:
        run.bump("cal_header_none")
        log("일정: 주 보기 머리(날짜 범위)를 읽지 못해 어느 주인지 확인할 수 없습니다 — 일정은 읽음으로 적지 않습니다")
        return done("unverified")
    st_ = {"clicks": 0, "retries": 0, "cap": n_weeks + CAL_RETRY}
    if ref[0] > d1:                         # URL 이 무시돼 더 뒤 주(이번 주 등)가 보인다 — 거슬러 가는 만큼 상한에 더한다
        run.bump("cal_url_ignored")
        st_["cap"] += (ref[0] - d1).days // 7 + 1

    def press():
        if st_["clicks"] >= st_["cap"]:
            return "cap"
        try:
            r = str(br.cdp.eval(JS_CAL_PREV) or "")
        except Exception:
            r = ""
        st_["clicks"] += 1
        run.c["cal_clicks"] = st_["clicks"]
        if r != "ok":
            return "none"
        _sleep(2.0)
        return "ok"

    def advance(ref, alt):
        """한 주 과거로 → (새 기준, 대안, 화면, 확인됨, 사유). 머리가 기준-7일(또는 대안-7일)이면 확인됨. 머리가 그대로면
        단추가 안 먹은 것 — CAL_RETRY 번까지 다시 누른다. 그 밖(머리 못 읽음·다른 주)은 미확인: 기준은 기대한 주로 두고,
        읽은 머리는 대안으로 남긴다(다음 화면에서 어느 쪽이 맞았는지 가린다)."""
        exps = [(ref[0] - w7, ref[1] - w7)] + ([(alt[0] - w7, alt[1] - w7)] if alt else [])
        while True:
            p = press()
            if p != "ok":
                return None, None, None, False, p
            pg2 = _cal_page(br)
            rng = cal_screen_range(pg2, run.today)
            if rng is not None and rng in (ref, alt) and st_["retries"] < CAL_RETRY:
                st_["retries"] += 1
                run.bump("cal_stuck")
                continue
            if rng in exps:
                return rng, None, pg2, True, "ok"
            run.bump("cal_header_none" if rng is None else "cal_header_mismatch")
            return exps[0], rng, pg2, False, "ok"

    alt, ok_week = None, True
    while ref[0] > d1:                      # 시작 주까지 — 이동만(읽지 않는다)
        nref, nalt, npg, okw, p = advance(ref, alt)
        if nref is None:
            run.bump("cal_click_cap" if p == "cap" else "cal_prev_none")
            return done("unverified")
        ref, alt, pg, ok_week = nref, nalt, npg, okw
    while True:
        if ref[1] >= d0 and ref[0] <= d1:
            diag["weeks"] += 1
            evs = [ev for ev in pg.get("events") or [] if isinstance(ev, dict)]
            got = keep(evs, ref[0], ref[1], True) if ok_week else None
            if ok_week and got is None:     # 일정이 그 주 밖 — 바탕이 아직 앞 주다. 한 번 더 읽는다
                _sleep(1.5)
                pg = _cal_page(br)
                if cal_screen_range(pg, run.today) == ref:
                    got = keep([ev for ev in pg.get("events") or [] if isinstance(ev, dict)], ref[0], ref[1], True)
                if got is None:
                    run.bump("cal_stale")
            if ok_week and got is not None:
                run.c["weeks_ok"] += 1
                owa_parse.apply_ranges(day_st, [(max(ref[0], d0), min(ref[1], d1), "ok")], run.today)
            else:
                run.c["weeks_unverified"] += 1
        if ref[0] <= d0 or run.out_of_time():
            break
        nref, nalt, npg, okw, p = advance(ref, alt)
        if nref is None:
            run.bump("cal_click_cap" if p == "cap" else "cal_prev_none")
            break
        ref, alt, pg, ok_week = nref, nalt, npg, okw
    return done("ok" if rows else "empty")


def _esc(s):
    s = re.sub(r"[\r\n]+", " ", str(s or ""))
    return '"' + s.replace('"', '""') + '"' if ("," in s or '"' in s) else s


def _has_data(path):
    try:
        with open(path, encoding="utf-8-sig") as f:
            return sum(1 for ln in f if ln.strip()) > 1
    except OSError:
        return False


def _read_rows(path, min_cols):
    """기존 CSV 의 행(머리 제외) — 없거나 못 읽으면 []. 열이 모자란 행은 버린다(extract._read 와 같은 기준)."""
    import csv as _csv
    try:
        with open(path, encoding="utf-8-sig", errors="replace", newline="") as f:
            rd = _csv.reader(f)
            next(rd, None)
            return [list(r) for r in rd if r and len(r) >= min_cols]
    except OSError:
        return []


def _verified(day_st_by_axis):
    """{축: {날짜: st}} → {축: [(from, to)]} — 이번에 끝까지 읽은 날(ok·zero_ok)만. 병합이 이 날의 옛 행을 바꾼다."""
    out = {}
    for ax, ds in day_st_by_axis.items():
        out[ax] = [(x["from"], x["to"]) for x in owa_parse.ranges_of(ds, ax) if x["st"] in ("ok", "zero_ok")]
    return out


def _save(kind, rows, store_subject, dst=None, verified=None):
    """LM28: 통째로 덮어쓰지 않는다(W1-04) — 옛 행과 owa_parse.merge_slices 로 합친다: 이번에 검증한 날(verified)의 옛 행만
    새 행으로 바꾸고, 미검증 날의 옛 행은 그대로 둔다. 임시 파일에 쓴 뒤 바꿔 넣는다. → (경로, 쓴 행 수)"""
    dst = dst or os.path.join(OUT_DIR, "mail.csv" if kind == "mail" else "calendar.csv")
    hdr = MAIL_HDR if kind == "mail" else CAL_HDR
    hdr_n = hdr.count(",") + 1
    new = []
    for r in rows:
        r = list(r)
        r += [""] * (hdr_n - len(r))     # 새 열(response,meeting_status)은 빈값 — 열 수가 모자라면 extract._read 가 행을 버린다
        if not store_subject:            # 제목을 남기지 않는다 — conversation 도 원문 대신 해시(회신 이력 판정만 유지)
            if kind == "mail":
                r[3] = ""
                r[4] = _conv_token(r[4])
            else:
                r[4] = ""
        new.append(r)
    old = [r + [""] * (hdr_n - len(r)) for r in _read_rows(dst, 6 if kind == "mail" else 7)]
    merged = owa_parse.merge_slices(old, new, verified or {}, "mail" if kind == "mail" else "cal")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    tmp = dst + ".tmp"
    with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
        f.write(hdr + "\n")
        for r in merged:
            f.write(",".join(_esc(c) for c in r[:hdr_n]) + "\n")
    os.replace(tmp, dst)
    return dst, len(merged)


def _precision_counts(out_dir, name="mail.csv"):
    """방금 쓴 메일 파일의 (전체, 시각을 못 읽은) 통수 — mail_source.json 에 남겨 화면이 손실을 말할 수 있게 한다."""
    import csv as _csv
    p = os.path.join(out_dir, name)
    n_all = n_date = 0
    try:
        with open(p, encoding="utf-8-sig", errors="replace") as f:
            for r in _csv.DictReader(f):
                n_all += 1
                if (r.get("time_precision") or "").strip().lower() == "date":
                    n_date += 1
    except OSError:
        return 0, 0
    return n_all, n_date


def emit_status(rc, reasons=(), counts=None, ranges=None, src="owa"):
    """수집기 마지막 줄(LM28 P3) — 'LMSTATUS ' + JSON 한 줄. reason 은 사유 코드를 쉼표로(첫 코드가 주 사유)."""
    rs = ",".join(dict.fromkeys(r for r in reasons if r))
    print("LMSTATUS " + json.dumps({"v": 1, "src": src, "rc": int(rc), "reason": rs, "counts": counts or {},
                                    "ranges": ranges or []}, ensure_ascii=False))
    sys.stdout.flush()


def _web(br, run, d0, d1, todo, results):
    """전용 Edge(잠금 안)에서 읽기 → None(정상) | (rc, 사유). 결과는 results[kind] = (행, 상태, diag, day_st).
    이 수집기가 연 탭만 닫는다 — 로그인 대기면 사람이 그 탭에서 로그인하므로 둔다."""
    try:
        started = br.start()
    except Exception as e:                  # 드라이버 모듈 부재·포트 충돌 등 — 사슬의 다음 경로로 넘긴다
        log(f"드라이버를 쓸 수 없습니다({type(e).__name__}: {str(e)[:80]}) — 다음 대체 경로로")
        return 3, "R-DRIVER"
    if not started:
        log("전용 Edge(디버그 포트)를 띄우지 못했습니다 — Edge 설치·config.copilotAuto.port 확인"
            + (f" ({br.reason})" if br.reason else ""))
        return 3, br.reason or "R-EDGELAUNCH"
    keep = False
    try:
        st = br.goto(MAIL_URL)
        if st in ("login", "personal"):
            keep = True
            if st == "personal":
                log("전용 Edge 가 개인 Microsoft 계정 화면입니다 — 업무 메일이 아니므로 읽지 않습니다. 회사 계정으로 로그인하세요.")
            else:
                log("로그인 필요 — 지금 열린 전용 Edge 창의 Outlook 탭에서 회사 계정을 한 번 선택/로그인하세요 (Copilot 과 같은 창, 1회).")
            log("           로그인 뒤 [분석 실행] 또는 대시보드 [Outlook 웹 읽기]를 다시 누르면 이어서 읽습니다.")
            return 2, br.reason or "R-LOGIN"
        if st != "ok":
            log("Outlook 웹 화면이 뜨지 않았습니다(네트워크·차단?) — 전용 Edge 창에서 outlook.office.com 이 열리는지 확인하세요.")
            return 3, "R-TIMEOUT"
        for kind in todo:
            res = collect_mail(br, d0, d1, None, run=run) if kind == "mail" else collect_cal(br, d0, d1, None, run=run)
            results[kind] = res
            if res[1] in ("login", "personal"):
                keep = True
                log("로그인 필요 — 전용 Edge 창의 Outlook 탭에서 회사 계정을 한 번 선택하세요.")
                return 2, br.reason or "R-LOGIN"
        return None
    finally:
        br.close(keep_tab=keep)


def main():
    t0 = time.time()
    d0s = arg("--from") or (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
    d1s = arg("--to") or datetime.now().strftime("%Y-%m-%d")
    d0, d1 = date.fromisoformat(d0s), date.fromisoformat(d1s)
    only = arg("--only")
    force = "--force" in sys.argv
    tag = arg("--tag")
    src_name = tag or "owa"
    if tag and not re.fullmatch(r"[A-Za-z0-9_-]{1,24}", tag):
        log(f"--tag 값이 올바르지 않습니다: {tag}")
        emit_status(3, ["R-ARGS"], src="owa")
        return 3
    out_arg = arg("--out-dir")
    out_dir = (out_arg if os.path.isabs(out_arg) else os.path.join(ROOT, out_arg)) if out_arg else OUT_DIR
    paths = {"mail": os.path.join(out_dir, f"mail_{tag}.csv" if tag else "mail.csv"),
             "cal": os.path.join(out_dir, f"cal_{tag}.csv" if tag else "calendar.csv")}
    src_p = os.path.join(out_dir, f"mail_source_{tag}.json" if tag else "mail_source.json")
    try:
        cfg = json.load(open(os.path.join(ROOT, "config", "config.json"), encoding="utf-8-sig"))
    except (OSError, ValueError):
        cfg = {}
    store_subject = bool(cfg.get("storeMailSubject", True))
    todo = []
    for kind in ("mail", "cal"):
        if only and kind != only:
            continue
        # 출처별 파일(--tag)은 이 수집기 것이라 늘 읽는다. LM24 경로(공용 파일)는 COM·색인이 모은 것을 지키려 --force 때만.
        if not tag and _has_data(paths[kind]) and not force:
            log(f"{os.path.basename(paths[kind])} 에 이미 자료가 있어 건너뜀 (덮어쓰려면 --force)")
        else:
            todo.append(kind)
    if not todo:
        emit_status(0, [], {"skipped": 1}, src=src_name)
        return 0
    months = max(1, (d1 - d0).days // 30 + 1)
    try:
        budget = float(arg("--budget-sec") or 0)
    except ValueError:
        budget = 0.0
    if budget <= 0:                         # 부르는 쪽 상한(run.py 180+150×개월 · 화면 1500초)보다 짧게 — 저장할 시간을 남긴다
        budget = min(1380.0, 120.0 + 140.0 * months)
    run = Run(d0, d1, deadline=t0 + budget, recover_max=cfg.get("owaTimeRecoverMax", 150))
    fake = None
    fk = os.environ.get("LM_OWA_FAKE", "")
    if fk:
        try:
            fake = json.load(open(fk, encoding="utf-8-sig"))
        except (OSError, ValueError):
            fake = {}
        if fake.get("login"):
            log("로그인 필요(시험용 가짜)")
            emit_status(2, ["R-LOGIN"], src=src_name)
            return 2
    results = {}
    fail = None
    if fake is None:
        if os.environ.get("LM_NO_BROWSER"):
            log("LM_NO_BROWSER 설정 — 브라우저를 띄우지 않습니다(시험용)")
            emit_status(3, ["R-NOBROWSER"], src=src_name)
            return 3
        try:
            br = Browser()
        except Exception as e:              # 드라이버 모듈 부재 등 — 사슬의 다음 경로로 넘긴다
            log(f"드라이버를 쓸 수 없습니다({type(e).__name__}: {str(e)[:80]}) — 다음 대체 경로로")
            emit_status(3, ["R-DRIVER"], src=src_name)
            return 3
        try:
            with br.ca.edge_lock(br.cfg):   # 같은 전용 Edge 를 쓰는 작업(Copilot·팀즈 웹·진단)과 직렬(F-16)
                fail = _web(br, run, d0, d1, todo, results)
        except br.ca.EdgeBusy as e:
            log(f"{e} — 다른 작업이 끝난 뒤 다시 실행하세요")
            emit_status(3, ["R-EDGEBUSY"], src=src_name)
            return 3
    else:
        for kind in todo:
            results[kind] = (collect_mail(None, d0, d1, fake, run=run) if kind == "mail"
                             else collect_cal(None, d0, d1, fake, run=run))
    return finish(results, fail, run, todo, paths, src_p, out_dir, tag, src_name, store_subject, cfg)


def finish(results, fail, run, todo, paths, src_p, out_dir, tag, src_name, store_subject, cfg):
    """읽은 결과 저장(병합) → mail_source(_<tag>).json → LMSTATUS. 로그인으로 끊겨도 그 앞에서 읽은 것은 저장한다."""
    total, counts, ranges = 0, {}, []
    axes = {"mail": ("mail_in", "mail_out"), "cal": ("cal",)}
    any_read = False
    for kind in todo:
        if kind not in results:
            continue
        rows, _stt, diag, day_st = results[kind]
        by_axis = day_st if kind == "mail" else {"cal": day_st}
        for ax in axes[kind]:
            ranges += owa_parse.ranges_of(by_axis[ax], ax)
            any_read = any_read or any(x != "unverified" for x in by_axis[ax].values())
        if kind == "mail":
            log(f"메일 진단: 검색 {diag['search']}회 · 화면 항목 {diag['items']}개 · 해석 {diag['parsed']}건"
                f"(보낸 {diag['sent']} · 참조 {diag['cc']} · 날짜만 {diag['date_only']}) · 페이지 {diag['pages']}")
            run.c["date_only"] = diag["date_only"]
        ver = _verified(by_axis)
        if rows or any(ver.values()):
            try:
                _, n_file = _save(kind, rows, store_subject, paths[kind], ver)
                log(f"{kind}: 이번 {len(rows)}건 읽음 · 파일 {n_file}행(검증한 날만 교체)")
            except OSError as e:
                log(f"{kind}: 저장 실패({type(e).__name__})")
        else:
            log(f"{kind}: 읽은 것이 없음 — 화면 항목은 보이는데 해석이 0이면 표기 형식 문제(로그의 '항목/해석' 수 참고)")
        total += len(rows)
        counts[kind] = len(rows)
    run.c["rows"] = total
    run.c["mail"] = counts.get("mail", 0)
    run.c["cal"] = counts.get("cal", 0)
    run.c["selector_diag"] = dict(run.sd)
    reasons = []
    if fail:
        rc, why = fail
        reasons.append(why)
    elif not any_read:
        rc = 3
        reasons.append("R-WEBSEL")                      # 화면은 열렸는데 어느 조각도 '읽음'으로 확인하지 못함
    else:
        rc = 0
    if run.timed_out:
        reasons.append("R-TIMEOUT")
        log("시간 예산에 닿아 멈췄습니다 — 못 읽은 날은 다음 실행이 다시 읽습니다")
    # mail_source — LM24 경로(공용 파일)는 행을 읽었을 때만(LM24 와 같게), 출처별 파일은 정상 종료면 늘
    if (total and not tag) or (tag and rc == 0):
        try:
            mail_name = os.path.basename(paths["mail"])
            _pa, _pd = _precision_counts(out_dir, mail_name)
            src = {"source": "owa", "when": datetime.now().strftime("%Y-%m-%d %H:%M"),
                   "kinds": todo, "rows": total, "mail": counts.get("mail", 0), "calendar": counts.get("cal", 0),
                   "me": [],                           # 내 주소는 화면에 없다 — rcv 는 to/cc(참조 조각) 만
                   # 시각을 못 읽은 통수 — 목록 화면은 어제 이전 항목에 날짜만 보인다. 그 행은 시간 계상에서 빠지므로
                   # (core/extract A38) 화면이 '몇 통이 빠졌는지' 를 말할 수 있어야 한다(감사 지적: 콘솔에만 있었다).
                   "mail_rows": _pa, "date_only": _pd,
                   "warnings": ([f"시각을 못 읽은 메일 {_pd}/{_pa}통 — 시간 계상 제외(클래식 Outlook 을 켜고 재수집 권장)"]
                                if _pd else []),
                   "ver": f"{COLLECTOR_VER}|{int(((cfg.get('collect') or {}).get('cursorEpoch')) or 1)}",
                   "period": [run.d0.isoformat(), run.d1.isoformat()], "counts": dict(run.c)}
            if "cal" in todo:
                # 주 보기는 반복 회의를 회차마다 그린다 — 색인 폴백(마스터 1건)과 달리 일정이 완전하다(확인한 주가 있을 때)
                src["calendar_complete"] = bool(run.c.get("weeks_ok"))
                src["calendar_recurring_masters"] = 0
            os.makedirs(os.path.dirname(src_p), exist_ok=True)
            with open(src_p, "w", encoding="utf-8") as f:
                json.dump(src, f, ensure_ascii=False)
            if not tag and "mail" in todo and _has_data(paths["mail"]):
                try:
                    os.remove(os.path.join(OUT_DIR, "outlook_skip.json"))
                except OSError:
                    pass
        except (OSError, ValueError, TypeError):
            pass
    emit_status(rc, reasons, dict(run.c), ranges, src=src_name)
    return rc


if __name__ == "__main__":
    sys.exit(main())
