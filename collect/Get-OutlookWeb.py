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

LM28 '읽음' 규칙(F-03·F-04·F-05 — 검증된 조각만 읽음으로 적는다 · P4):
  · 메일은 달 조각(최신 달부터) × 폴더마다 기간 검색 뒤 결과를 끝까지 내리며 owa_parse.slice_verdict 로 판정한다. 검색 표기는
    공개 도움말의 AQS(received:MM/DD/YYYY..MM/DD/YYYY) → KQL(received>=…) → ISO 범위 순으로 시도하고, 조각 안 결과를 한 번
    본 표기만 이 실행에서 계속 쓴다 — 그 표기에서만 '결과 없음'이 0건 확인(zero_ok)이다(모르는 표기는 낱말 검색이 되어 결과
    없음이 나온다). 결과에 조각 밖 날짜가 보이면 검색이 화면에 안 걸린 것(폴더 목록 그대로)이라 이 실행의 검색을 접고, 폴더마다
    **1회** 목록을 최신부터 기간 시작 앞 날짜에 닿을 때까지 내린다(폴백 — LIST_SCREENS·시간 예산 안, 잘리면 partial).
    끊김 없이 D 까지 내려갔으면 [D+1, 끝] 은 ok, D 이하는 partial. 목록의 오늘(시각만)·이번 주(요일+시각)·어제 표기도 날짜로 읽는다(F-04).
  · 목록 칸(LM28 현장 2026-10-08): 화면의 '첫 listbox'가 아니라 메일 행(data-convid·날짜·시각 조각)이 가장 많은 칸(본문 안쪽
    우선 — owa_parse.pick_list)을 읽고, 스크롤은 그 행의 가장 가까운 '실제로 스크롤되는' 조상(overflow auto/scroll·
    data-is-scrollable)에 건다 — 새 Outlook 웹은 가상 목록의 스크롤 칸이 listbox **안쪽**에 있다. 가상 목록(창 밖 행은 DOM 에
    없음)이라 화면마다 새 행만 모으고(화면 위치순), scrollTop 대입이 안 먹으면 실제 휠 입력(CDP)을 쓴다.
  · 목록 '끝'의 근거는 둘뿐이다 — ① 기간 시작 앞 날짜에 닿음 ② 바닥에서 새 행 0 이 END_CONFIRM 번(사이에 결과 '더 보기'·휠·
    더 긴 대기, '불러오는 중' 표시 없음)이고 그 칸이 메일 목록으로 확인됨(owa_parse.mail_list_ok). 'fits'(칸이 화면에 다
    들어감)는 근거가 아니다 — 현장에서 첫 listbox 는 늘 '다 들어감'이라 받은·보낸 17건으로 281일을 읽음으로 적었다.
    근거가 없으면 partial(끊김 없이 읽은 최신 쪽만 ok)·unverified 로 남겨 다음 경로·다음 실행이 다시 읽는다.
  · 날짜만 보이는 줄은 항목의 다른 title·aria-label·<time datetime>(로컬로 바꿈)에서 시각을 찾고, 보낸 편지함은 그래도
    없으면 항목을 열어 읽기 창 머리에서 owaTimeRecoverMax(150)건까지 시각을 얻는다(받은 메일은 열지 않는다 — 읽음 표시).
  · 일정은 가장 최근 주만 URL 로 열고, 그다음은 '이전 주' 단추를 1회씩 눌러 순차로 읽는다. 단추가 없거나 끝내 안 먹으면(머리가
    그대로) 주소(/calendar/view/week/Y/M/D)로 그 주를 연다 — 주소도 무시되면 멈추고 남은 주는 미확인. 매번 화면 머리의 날짜
    범위가 기대한 주와 같을 때만 그 주를 읽음으로 하고(실제로 지나간 주만 weeks_ok), 다르면 그 주의 행을 버린다(클릭 수 ≤
    주 수 + 3). 일정 0개인 주는 이 실행에서 일정을 한 번이라도 읽었을 때만 ok(선택자가 빗나가면 모든 주가 0개로 보인다),
    못 읽은 일정 막대(data-calitemid)가 있는 주는 partial. calendar_complete 는 기간의 지난 날이 모두 확인됐을 때만 true.
  · 전용 Edge 는 copilot_auto.edge_lock 안에서만 쓰고(다른 작업과 직렬), 이 수집기가 연 탭만 닫는다(로그인 대기면 둔다).
    메일·일정을 함께 읽으면 메일은 시간 예산의 끝 일부(최대 300초)를 일정에 남기고 멈춘다.

화면 구조는 Microsoft 가 바꿀 수 있어 '역할(role)·aria-label·title' 같은 접근성 속성만 의지하고, 무엇을 몇 개
인식했는지 남긴다(회사 PC 의 원문을 밖으로 보낼 수 없으므로 진단은 구조로 한다): 마지막 요약 줄 앞에
'[outlook-web] 구조: …' 한 줄(사진 한 장으로 원인 확정용 — run.py 가 '구조:' 줄을 last_run.json 단계에 따로 싣는다)과
LMSTATUS counts.dom_census(같은 내용 + 행 골격 — 태그·role·aria-label 길이·data-convid 표식·data-app-section 값·개수·크기·
스크롤 상태만, 글자는 x · 4KB 이내)를 낸다.
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
from urllib.parse import quote, urlparse

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
# 판정 규칙의 판 — mail_source 에 '판|collect.cursorEpoch' 로, LMSTATUS counts.collector_ver 로 싣는다.
# 2: 'fits' 를 끝 근거에서 뺌 · 메일 목록 칸 고르기 · 검색 표기 확인(결과 없음은 걸린 표기에서만 0건) · 일정 주소 이동·0개 주 증명
COLLECTOR_VER = "LM28-OWA-2"
SEARCH_SCREENS = 150                       # 검색 결과 한 조각을 내리는 화면 수 상한(LM24 의 달마다 400회 대신)
LIST_SCREENS = 800                         # 폴백(검색 없이 최신부터) 한 폴더를 내리는 화면 수 상한
STALL_MAX = 3                              # 내렸는데 새 항목 없는 화면이 이만큼 이어지면 멈춘다(끝을 모른다)
END_CONFIRM = 3                            # 바닥에서 새 항목 0 이 이만큼 이어지면(사이에 '더 보기'·휠·더 긴 대기) 목록 끝 — 메일 목록일 때만
BUSY_MAX = 4                               # 바닥의 '불러오는 중' 표시를 기다리는 횟수 — 그래도 남으면 끝을 모른다(partial)
MORE_MAX = 40                              # 결과 '더 보기' 단추를 누르는 횟수 상한(한 번 읽기)
CAL_RETRY = 3                              # '이전 주' 단추가 안 먹었을 때(머리 그대로) 다시 누르는 횟수(전체) — 그 뒤는 주소로 주를 옮긴다
# 기간 검색 표기 — 공개 도움말(Outlook 웹 AQS: 'Received:01/01/2017', 날짜는 MM/DD/YYYY, 범위는 '..')을 먼저, LM28 처음 표기(KQL)·ISO 범위를
# 다음으로. 이 실행에서 조각 안 결과를 한 번 본 표기만 계속 쓴다(Run.srch.proven).
SEARCH_FORMS = (("aqs", lambda s, e: f"received:{s:%m/%d/%Y}..{e:%m/%d/%Y}"),
                ("kql", lambda s, e: f"received>={s.isoformat()} received<={e.isoformat()}"),
                ("iso", lambda s, e: f"received:{s.isoformat()}..{e.isoformat()}"))
END_KO = {"d0": "시작 앞 도달", "bottom": "목록 끝", "busy": "불러오는 중 계속", "stall": "새 항목 없음", "stuck": "스크롤 안 먹음",
          "noscroll": "스크롤칸 없음", "nolist": "목록 칸 없음", "cap": "화면 상한", "time": "시간 예산", "outside": "검색 안 걸림",
          "empty": "비어 있음", "js": "스크립트 오류", "": "없음"}
SC_KO = {"anc": "스크롤칸 찾음", "dis": "스크롤칸 찾음(속성)", "doc": "문서 스크롤", "anc0": "스크롤칸 넘침 없음", "": "스크롤칸 없음"}
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
        # LM28: 날짜 없이 요일만 있는 막대('주간 회의, 화요일 오후 2:00 ~ 오후 3:00') — 그 주(d0~d1) 안의 그 요일(요일이 하나일 때만)
        wd = owa_parse.weekday_date(label, d0, d1)
        dates = [wd] if wd else []
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
# 자리표 __LIB__(아래 공용 조각)·__PICK__(고른 칸 순번, -1 = 후보 칸 사실만)·__SKEL__·__MODE__ 는 _js() 가 채운다.
#
# LM28(현장 2026-10-08 — 메일 17건으로 281일 '읽음'): 예전엔 document.querySelector('[role="listbox"]')(화면의 **첫** listbox)
#   에서 위로만 스크롤 칸을 찾고, 못 찾으면 'fits'(다 보임)로 끝을 확인했다. 새 Outlook 웹은 메일 목록이 가상 목록이고 그 스크롤
#   칸(.customScrollBar[data-is-scrollable] — 공개 스크립트들이 쓰는 표지)이 listbox **안쪽**에 있어, listbox 자체는 늘 '다 들어감'
#   이었다. 이제 후보 칸(listbox·grid·data-convid 무리)마다 행 수·메일 행 수(data-convid 또는 날짜·시각 조각)·본문 안쪽 여부를
#   세어 내고(파이썬 owa_parse.pick_list 가 고른다), 고른 칸의 **행에서** 위로 가장 가까운 '실제로 넘치는' 스크롤 조상을 찾는다.
_JS_LIB = r"""
  const RX_DT = /\d{1,2}[:.]\d{2}|\d{4}\s*[-.\/년]\s*\d{1,2}|\d{1,2}\s*\/\s*\d{1,2}|\d{1,2}\s*월\s*\d{1,2}\s*일|어제|오늘|yesterday|today|\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{1,2}\b|\b\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b/i;
  const vis = e => { const r = e.getBoundingClientRect(); return r.width > 2 && r.height > 2; };
  const topOnly = rs => rs.length > 300 ? rs : rs.filter(r => !rs.some(o => o !== r && o.contains(r)));
  const rowsIn = c => {
    let rs = [...c.querySelectorAll('[role="option"]')];
    if (!rs.length) rs = [...c.querySelectorAll('[role="row"]')].filter(r => !r.querySelector('[role="columnheader"]'));
    if (!rs.length) rs = [...c.querySelectorAll('[data-convid], [data-item-id]')];
    return topOnly(rs);
  };
  const cid = r => { const x = r.matches('[data-convid], [data-item-id]') ? r : r.querySelector('[data-convid], [data-item-id]');
    return x ? (x.getAttribute("data-convid") || x.getAttribute("data-item-id") || "") : ""; };
  const isMail = r => !!cid(r) || RX_DT.test((r.getAttribute("aria-label") || "") + " " + (r.textContent || "").slice(0, 300));
  const conts = () => {
    const cs = [...document.querySelectorAll('[role="listbox"], [role="grid"]')];
    const loose = topOnly([...document.querySelectorAll("[data-convid]")].filter(r => !r.closest('[role="listbox"], [role="grid"]')));
    if (loose.length) { let p = loose[0].parentElement; while (p && !loose.every(x => p.contains(x))) p = p.parentElement;
      if (p && !p.querySelector('[role="listbox"], [role="grid"]')) cs.push(p); }   // 다른 칸을 품은 큰 조상은 후보가 아니다(행이 섞인다)
    return cs.slice(0, 12);
  };
  const pickC = () => {
    const w = window.__lm_c;
    if (w && w.isConnected && w.__lm_i === PICK) return w;
    const c = conts()[PICK] || null;
    if (c) { c.__lm_i = PICK; window.__lm_c = c; }
    return c;
  };
  const OVF = /(auto|scroll|overlay)/;
  const scOf = (c, rows) => {
    let el = rows[0] || c, d = 0, first = null;
    while (el && el !== document.body && el !== document.documentElement && d < 30) {
      if (OVF.test(getComputedStyle(el).overflowY) || el.getAttribute("data-is-scrollable") === "true") {
        if (el.scrollHeight > el.clientHeight + 8) return {el, how: "anc", d};
        if (!first) first = {el, how: "anc0", d};
      }
      el = el.parentElement; d++;
    }
    const near = [...c.querySelectorAll('[data-is-scrollable="true"]'), ...(c.parentElement ? c.parentElement.querySelectorAll('[data-is-scrollable="true"]') : [])];
    for (const x of near) { if (x.scrollHeight > x.clientHeight + 8 && (!rows[0] || x.contains(rows[0]))) return {el: x, how: "dis", d: -1}; }
    if (first) return first;
    const se = document.scrollingElement;
    if (se && se.scrollHeight > se.clientHeight + 8) return {el: se, how: "doc", d: -1};
    return null;
  };
  const where = (c, el) => el === c ? "self" : (c.contains(el) ? "in" : (el.contains(c) ? "out" : "apart"));
  const busyIn = e => { if (!e) return false; if (e.getAttribute("aria-busy") === "true") return true;
    return [...e.querySelectorAll('[role="progressbar"], [aria-busy="true"], .ms-Spinner, [class*="pinner"], [class*="himmer"]')].some(vis); };
  const fact = (c, i) => { const rs = rowsIn(c);
    return {i, role: (c.getAttribute("role") || c.tagName.toLowerCase()).slice(0, 12), opts: rs.length, mailish: rs.filter(isMail).length,
            conv: rs.filter(r => !!cid(r)).length, main: c.closest('[role="main"], main, [data-app-section]') ? 1 : 0, vis: vis(c) ? 1 : 0,
            al: (c.getAttribute("aria-label") || "").length}; };
"""
# LM28: PICK<0 이면 후보 칸 사실(cands — 구조만)·data-app-section 값(sec)만, PICK>=0 이면 그 칸의 행(화면 위치순)과 칸 사실(lst —
#       스크롤 칸 찾은 방법·위치·크기·'불러오는 중')을 낸다. 항목마다 idx(열기용)·cv(data-convid)·dts(시각이 든 다른 title·aria-label·
#       datetime 속성 — 시각 복원용), 화면마다 empty('결과 없음/비어 있음' 표식)·sel(선택된 폴더 이름)·pivots(선택된 탭 글 — 중요/기타).
#       SKEL 이면 첫 행의 골격(태그·role·aria-label 길이·잎 글 — 파이썬이 owa_parse.skeleton 으로 가린 뒤에만 남긴다).
JS_MAIL = r"""/*LM28:owa_list*/
(() => {
  const PICK = __PICK__, SKEL = __SKEL__;
__LIB__
  const out = {href: location.href, n: 0, items: [], cands: [], lst: null, lb: 0, search: false, empty: false, sel: "", pivots: [], sec: []};
  out.search = !!document.querySelector('#topSearchInput, input[role="searchbox"], [role="search"] input, input[aria-label*="검색"], input[aria-label*="Search"], input[placeholder*="검색"], input[placeholder*="Search"], [role="combobox"][aria-label*="검색"], [role="combobox"][aria-label*="Search"]');
  out.lb = document.querySelectorAll('[role="listbox"]').length;
  const ts = document.querySelector('[role="treeitem"][aria-selected="true"]');
  out.sel = ts ? ((ts.getAttribute("title") || ts.textContent || "").trim().slice(0, 40)) : "";
  out.pivots = [...document.querySelectorAll('[role="tab"][aria-selected="true"]')].map(x => (x.textContent || "").trim().slice(0, 20)).filter(Boolean).slice(0, 6);
  const isEmpty = () => { const m = document.querySelector('[role="main"]') || document.body; const t = ((m && m.innerText) || "").slice(0, 3000);
    return /결과가 없|결과를 찾을 수 없|찾지 못했|항목이 없|비어 있|didn.t find|did not find|no results|no items|nothing in (this )?folder|folder is empty/i.test(t); };
  if (PICK < 0) {
    window.__lm_c = null;
    out.cands = conts().map(fact);
    out.sec = [...new Set([...document.querySelectorAll("[data-app-section]")].map(e => e.getAttribute("data-app-section") || ""))].filter(v => /^[A-Za-z][\w-]{0,39}$/.test(v)).slice(0, 10);
    if (!out.cands.some(c => c.mailish > 0)) out.empty = isEmpty();
    return JSON.stringify(out);
  }
  const c = pickC();
  if (!c) return JSON.stringify(out);
  const rows = rowsIn(c).sort((a, b) => a.getBoundingClientRect().top - b.getBoundingClientRect().top);
  window.__lm_mail = rows;
  const sc = scOf(c, rows);
  out.lst = Object.assign(fact(c, PICK), sc ? {how: sc.how, d: sc.d, where: where(c, sc.el), sh: sc.el.scrollHeight, ch: sc.el.clientHeight,
    st: Math.round(sc.el.scrollTop)} : {how: "", d: -1, where: "", sh: 0, ch: 0, st: 0}, {busy: ((sc && busyIn(sc.el)) || busyIn(c)) ? 1 : 0});
  out.n = rows.length;
  if (!rows.length) out.empty = isEmpty();
  out.items = rows.slice(0, 600).map((o, i) => { const l = o.getAttribute("aria-label") || "", k = cid(o); return {
    idx: i, cv: k ? 1 : 0,
    key: (k || o.id || "") + "|" + l.slice(0, 80),
    label: l,
    titles: [...o.querySelectorAll("[title]")].map(x => x.getAttribute("title") || "").filter(Boolean).slice(0, 12),
    texts: [...o.querySelectorAll("span,div,a")].filter(x => x.childElementCount === 0).map(x => (x.textContent || "").trim()).filter(Boolean).slice(0, 24),
    dts: [...o.querySelectorAll("[datetime],[title],[aria-label]")].map(x => x.getAttribute("datetime") || x.getAttribute("title") || x.getAttribute("aria-label") || "").filter(v => v && v.length <= 80 && /\d{1,2}[:.]\d{2}/.test(v)).slice(0, 6)
  }; });
  if (SKEL && rows[0]) {
    const node = (e, d) => { const o = {t: e.tagName.toLowerCase()}; const r = e.getAttribute("role"); if (r) o.r = r;
      const al = e.getAttribute("aria-label"); if (al) o.al = al.length; if (e.hasAttribute("data-convid")) o.cv = 1;
      const ks = [...e.children]; if (!ks.length) { const x = (e.textContent || "").trim(); if (x) o.x = x.slice(0, 40); return o; }
      if (d >= 4) { o.k = ks.length; return o; } o.c = ks.slice(0, 6).map(k => node(k, d + 1)); return o; };
    out.skel = node(rows[0], 0);
  }
  return JSON.stringify(out);
})()
"""
# LM28: 고른 칸(PICK)의 스크롤 칸을 한 화면 내린다 → {r, how, d, sh, ch, st, busy, x, y}
#   r: scrolled(내려감) · bottom(이미 바닥 — 넘치지 않는 칸 포함, 끝인지는 파이썬이 여러 번 확인) · no-move(대입이 안 먹음 — 휠로)
#      · no-scroller(스크롤 칸 못 찾음 — 끝을 모른다) · no-list(칸 없음) · top(MODE=top — 맨 위로). x·y = 휠 입력 자리(칸 가운데)
JS_SCROLL = r"""/*LM28:owa_scroll*/
(() => {
  const PICK = __PICK__, MODE = "__MODE__";
__LIB__
  const c = pickC();
  if (!c) return JSON.stringify({r: "no-list"});
  const rows = rowsIn(c), s = scOf(c, rows);
  if (!s) return JSON.stringify({r: "no-scroller", n: rows.length});
  const el = s.el, rc = el.getBoundingClientRect();
  const o = {r: "", how: s.how, d: s.d, sh: el.scrollHeight, ch: el.clientHeight, st: Math.round(el.scrollTop),
             busy: (busyIn(el) || busyIn(c)) ? 1 : 0, x: Math.round(rc.left + rc.width / 2), y: Math.round(rc.top + Math.min(rc.height / 2, 300))};
  if (MODE === "top") { el.scrollTop = 0; el.dispatchEvent(new Event("scroll", {bubbles: true})); o.r = "top"; return JSON.stringify(o); }
  if (el.scrollTop + el.clientHeight >= el.scrollHeight - 4) { o.r = "bottom"; return JSON.stringify(o); }
  const before = el.scrollTop;
  el.scrollTop = before + Math.max(120, el.clientHeight - 60);
  el.dispatchEvent(new Event("scroll", {bubbles: true}));
  o.r = el.scrollTop > before + 1 ? "scrolled" : "no-move";
  o.st = Math.round(el.scrollTop);
  return JSON.stringify(o);
})()
"""
# LM28: 목록 바닥의 결과 '더 보기'류 단추(마지막 행 **아래**에 있는 것만 — 대화 펼치기·옵션·필터·폴더 범위 단추는 누르지 않는다)
JS_MORE = r"""/*LM28:owa_more*/
(() => {
  const PICK = __PICK__;
__LIB__
  const c = pickC();
  if (!c) return "none";
  const rows = rowsIn(c);
  if (!rows.length) return "none";
  const s = scOf(c, rows);
  const last = Math.max(...rows.map(r => r.getBoundingClientRect().bottom));
  const RX = /더\s?보기|결과\s?더|더 많은 결과|load more|show more|see more|view more|more results/i;
  const NO = /옵션|option|작업|action|메뉴|menu|필터|filter|정렬|sort|폴더|folder|보관|archive|설정|setting/i;
  for (const z of [s && s.el, c, c.parentElement].filter(Boolean)) {
    for (const b of z.querySelectorAll('button, [role="button"], a[href], [role="link"]')) {
      if (b.disabled || b.getAttribute("aria-disabled") === "true" || !vis(b)) continue;
      if (b.getBoundingClientRect().top < last - 4) continue;
      const t = ((b.getAttribute("aria-label") || "") + " " + (b.textContent || "")).trim().slice(0, 80);
      if (RX.test(t) && !NO.test(t)) { b.click(); return "clicked"; }
    }
  }
  return "none";
})()
"""
# LM28: 일정 화면 머리(heads — 날짜 범위가 든 짧은 글)·열 머리(cols)·바탕(grid) 도 낸다(F-05 — 그 주가 맞는지 확인).
#   일정 막대는 data-calitemid(공개 스크립트들이 쓰는 표지 — cal:1, 이름은 aria-label·title·글자 순)를 먼저, 그다음 시각·종일이 든
#   aria-label 요소. 구조 진단용 수: nc(data-calitemid 수)·nb(aria-label 후보 수)·nt(그중 시각·종일이 든 수).
JS_CAL = r"""/*LM28:owa_cal*/
(() => {
  const out = {href: location.href, n: 0, events: [], heads: [], cols: [], grid: false, nc: 0, nb: 0, nt: 0};
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
  const seen = new Set();
  const push = (e, l, cal) => {
    const k = l.slice(0, 160);
    if (!k || seen.has(k)) return;
    seen.add(k);
    out.events.push({label: l, cal, texts: [...e.querySelectorAll("span,div")].filter(x => x.childElementCount === 0).map(x => (x.textContent || "").trim()).filter(Boolean).slice(0, 10)});
  };
  const items = [...document.querySelectorAll("[data-calitemid]")];
  out.nc = items.length;
  for (const e of items) {
    if (out.events.length >= 400) break;
    const inner = e.querySelector("[aria-label]");
    const l = (e.getAttribute("aria-label") || (inner && inner.getAttribute("aria-label")) || e.getAttribute("title") || (e.textContent || "").trim()).slice(0, 300);
    if (l) push(e, l, 1);
  }
  const cands = [...document.querySelectorAll('[role="main"] [aria-label], [role="grid"] [aria-label], [role="button"][aria-label], [role="listitem"][aria-label]')];
  out.nb = cands.length;
  for (const e of cands) {
    if (out.events.length >= 400) break;
    if (e.closest("[data-calitemid]")) continue;
    const l = e.getAttribute("aria-label") || "";
    if (!/\d{1,2}[:.]\d{2}|종일|all[- ]day|終日/i.test(l)) continue;
    if (!/\d/.test(l)) continue;
    out.nt++;
    push(e, l, 0);
  }
  out.n = out.events.length;
  return JSON.stringify(out);
})()
"""
# LM28(F-05): 주 보기의 '이전 주' 단추 — 주/week 가 든 이름(aria-label·title)을 먼저, 없으면 '이전'·'Previous' 로 시작하는 이름
JS_CAL_PREV = r"""/*LM28:owa_cal_prev*/
(() => {
  const bs = [...document.querySelectorAll('button, [role="button"]')].filter(b => !b.disabled && b.offsetParent !== null);
  const name = b => ((b.getAttribute("aria-label") || "") + " " + (b.getAttribute("title") || "")).trim();
  const pick = rx => bs.find(b => rx.test(name(b)));
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
    """한 번의 수집(LM28) — 기간·오늘·시간 예산·계수(LMSTATUS counts)·화면 진단(selector_diag·cen)·시각 복원 예산·검색 표기 상태.
    시험은 today·deadline 을 넘긴다(deadline=None 이면 예산 없음). reserve = 메일 단계가 일정에 남기는 예산 끝(초)."""

    def __init__(self, d0, d1, today=None, deadline=None, recover_max=150, reserve=0.0):
        self.d0, self.d1 = d0, d1
        self.today = today or date.today()
        self.deadline = deadline
        try:
            self.recover_left = max(0, int(recover_max))
        except (TypeError, ValueError):
            self.recover_left = 150
        try:
            self.reserve = max(0.0, float(reserve or 0))
        except (TypeError, ValueError):
            self.reserve = 0.0
        self.phase = ""
        self.timed_out = False
        self.hit_time = False                  # 앞 단계(메일)가 제 몫의 예산에 닿았다 — 사유 R-TIMEOUT 은 남긴다
        self.last_head = None
        self.c = {"slices_ok": 0, "list_verified": 0, "filter_ineffective": 0, "slices_unverified": 0,
                  "fallback_scroll": 0, "weeks_ok": 0, "weeks_unverified": 0, "weeks_partial": 0, "weeks_total": 0,
                  "cal_clicks": 0, "cal_complete": False, "date_only": 0, "recovered": 0, "opened": 0, "rows": 0}
        self.sd = {}
        self.cen = {"mail": {}, "cal": {}}     # 화면 구조 진단(dom_census) — 구조만(글자는 owa_parse.mask_shape, aria-label 은 길이)
        # 기간 검색 표기 — proven: 이 실행에서 조각 안 결과를 본 표기 · broken: 결과가 폴더 목록 그대로(검색이 화면에 안 걸림) ·
        #   dead: 날짜를 다르게 읽은 표기 · nobox: 검색창 없음 · slices/hit: 검색한 조각 수 / 검색이 걸린(확인·일부 확인) 조각 수 ·
        #   tries: 검색 입력 횟수
        self.srch = {"proven": "", "broken": False, "nobox": False, "dead": [], "slices": 0, "hit": 0, "tries": 0}

    def bump(self, k, n=1):
        self.sd[k] = self.sd.get(k, 0) + n

    def start_phase(self, name):
        """메일 → 일정 차례 — 메일 단계는 예산 끝의 reserve 초를 일정에 남긴다. 앞 단계의 시간 초과는 사유로만 남긴다."""
        self.hit_time = self.hit_time or self.timed_out
        self.timed_out = False
        self.phase = name

    def out_of_time(self):
        if self.deadline is not None:
            dl = self.deadline - (self.reserve if self.phase == "mail" else 0.0)
            if time.time() >= dl:
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


def _int(v, d=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return d


def _js(js, pick=-1, skel=False, mode="down"):
    """JS 상수의 자리표 채우기(__LIB__ 공용 조각·__PICK__ 고른 칸 순번·__SKEL__·__MODE__) — 머리 표식(/*LM28:…*/)은 맨 앞 그대로."""
    return (js.replace("__LIB__", _JS_LIB).replace("__PICK__", str(int(pick)))
            .replace("__SKEL__", "1" if skel else "0").replace("__MODE__", mode))


def _scroll(br, pick, mode="down"):
    """고른 칸을 한 화면 내린다(JS_SCROLL) → 응답 dict(실패면 {})."""
    try:
        r = br.eval_json(_js(JS_SCROLL, pick, mode=mode))
    except Exception:
        return {}
    return r if isinstance(r, dict) else {}


def _wheel(br, sr, dy=900):
    """스크롤 칸 가운데에 실제 휠 입력(CDP Input.dispatchMouseEvent) — scrollTop 대입이 안 먹는 가상 목록·'더 불러오기'를 깨운다."""
    x, y = _int(sr.get("x")), _int(sr.get("y"))
    if x <= 0 or y <= 0:
        return False
    try:
        br.cdp.call("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})
        br.cdp.call("Input.dispatchMouseEvent", {"type": "mouseWheel", "x": x, "y": y, "deltaX": 0, "deltaY": dy})
        return True
    except Exception:
        return False


def _more(br, pick):
    """목록 바닥의 결과 '더 보기' 단추를 누른다(JS_MORE — 마지막 행 아래 것만) → 눌렀으면 True."""
    try:
        return str(br.cdp.eval(_js(JS_MORE, pick)) or "") == "clicked"
    except Exception:
        return False


def _read_screens(br, run, folder, s, e, list_mode):
    """지금 화면(검색 결과 또는 폴더 목록)을 위에서부터 내린다 → (got, meta).
    got = [(항목, 날짜|None, 행|None)] 화면 순서 · meta = {reached, empty, sel, pivots, screens, end, mail_ok, pick, lst, …}.
    · 칸: 첫 화면에서 후보 칸의 사실(JS_MAIL PICK=-1 — 칸마다 행 수·메일 행 수·data-convid·본문 안쪽)을 받아
      owa_parse.pick_list 로 메일 목록 칸을 고르고, 그 칸만 읽고 내린다(가상 목록 — 화면마다 새 행만 모은다).
    · 멈춤: 검색 화면은 조각 밖(앞뒤 1일 여유 밖) 날짜가 보이면(검색이 안 걸림 — end 'outside'), 목록 화면(폴백)은 가장 깊은
      날짜가 기간 시작(run.d0)보다 앞서면(end 'd0').
    · 끝(reached): 바닥에서 새 행 0 이 END_CONFIRM 번(그 사이 '더 보기'·실제 휠·더 긴 대기) + '불러오는 중' 없음 + 메일 목록
      확인(owa_parse.mail_list_ok)일 때만. 'fits'(칸이 다 들어감)는 근거가 아니다. 그 밖(스크롤 칸 없음·안 움직임·새 행 없음·
      불러오는 중이 계속·화면 수 상한·예산)은 끝을 모른 채 멈춘다(그 아래 날은 partial)."""
    got, seen_k = [], set()
    meta = {"reached": False, "empty": False, "sel": "", "pivots": [], "screens": 0, "end": "", "mail_ok": False,
            "pick": None, "lst": {}, "cands": [], "lb": 0, "search": False, "sec": [], "skel": None,
            "wheel": 0, "more": 0, "busy": 0}
    h0, h1 = (run.d0, run.d1) if list_mode else (s, e)
    lo, hi = s - timedelta(days=1), e + timedelta(days=1)
    # 시각 복원은 받을 행만 — 검색 화면은 그 조각 안 날짜만(검색이 안 걸린 화면의 행은 버려지고 폴백이 다시 읽는다)
    d0s, d1s = (run.d0.isoformat(), run.d1.isoformat()) if list_mode else (max(s, run.d0).isoformat(),
                                                                           min(e, run.d1).isoformat())
    cap = LIST_SCREENS if list_mode else SEARCH_SCREENS
    pick = None
    stall = quiet = busy = nomove = empty_n = repick = 0
    topped = False
    while meta["screens"] < cap:
        if run.out_of_time():
            meta["end"] = "time"
            break
        skel = pick is not None and meta["skel"] is None and not run.cen["mail"].get("skel")
        try:
            pg = br.eval_json(_js(JS_MAIL, -1 if pick is None else pick, skel)) or {}
        except Exception:
            run.bump("js_error")
            meta["end"] = "js"
            break
        meta["screens"] += 1
        if meta["screens"] == 1:
            meta["sel"] = str(pg.get("sel") or "")
            meta["pivots"] = [str(x) for x in pg.get("pivots") or []]
            meta["lb"], meta["search"] = _int(pg.get("lb")), bool(pg.get("search"))
        if pick is None:                     # 후보 칸의 사실만 받고 파이썬이 고른다(첫 listbox 가 아니다)
            cands = [c for c in pg.get("cands") or [] if isinstance(c, dict)]
            if cands or not meta["cands"]:
                meta["cands"] = cands
            if pg.get("sec") and not meta["sec"]:
                meta["sec"] = [str(x)[:40] for x in pg.get("sec") or []][:8]
            i = owa_parse.pick_list(cands)
            if i is None:
                if pg.get("empty"):
                    empty_n += 1
                    if empty_n >= 2:          # '결과 없음/비어 있음' 이 두 화면 이어짐(그려지는 중이 아니다)
                        meta["empty"], meta["end"] = True, "empty"
                        break
                elif meta["screens"] >= 4:
                    run.bump("list_none")
                    meta["end"] = "nolist"
                    break
                _sleep(1.5)                   # 목록이 아직 안 그려졌을 수 있다 — 잠깐 더
                continue
            pick = meta["pick"] = i
            run.bump("list_pick")
            continue
        lst = pg.get("lst") if isinstance(pg.get("lst"), dict) else None
        if lst is None:                      # 고른 칸이 사라졌다(다시 그려짐) — 다시 고른다(2번까지)
            repick += 1
            if repick > 2:
                meta["end"] = "nolist"
                break
            pick = None
            _sleep(1.0)
            continue
        if _int(lst.get("mailish")) >= _int(meta["lst"].get("mailish"), -1):
            meta["lst"] = lst
        if skel and isinstance(pg.get("skel"), dict):
            meta["skel"] = pg["skel"]
        items = [it for it in pg.get("items") or [] if isinstance(it, dict)]
        if not got and not items:
            if pg.get("empty"):
                empty_n += 1
                if empty_n >= 2:
                    meta["empty"], meta["end"] = True, "empty"
                    break
            elif meta["screens"] >= 6:
                meta["end"] = "nolist"
                break
            _sleep(1.5)
            continue
        if not got and _int(lst.get("st")) > 4 and not topped:
            topped = True                    # 목록이 맨 위가 아닌 데서 열렸다 — 올리고 다시 읽는다(끊김 없이 최신부터)
            _scroll(br, pick, "top")
            _sleep(1.0)
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
            if r and not (r[2] or r[3]) and not it.get("cv"):
                r, d = None, None            # 무리 머리('어제'·'지난 주' — 날짜뿐인 줄)는 메일 행이 아니다
            got.append((it, d, r))
            if d is not None and not list_mode and (d < lo or d > hi):
                stop = True                  # 검색이 안 걸린 화면 — 더 내리지 않는다
            if r and r[6] == "date" and d0s <= r[1][:10] <= d1s:
                _recover(br, run, it, r, folder)
        if stop:
            meta["end"] = "outside"
            break
        if list_mode:
            ds = [g[1] for g in got if g[1]]
            if ds and ds[-1] < run.d0:
                meta["end"] = "d0"           # 기간 시작 앞 날짜에 닿았다 — 끝 근거 ①
                break
        if new:
            busy = 0
        sr = _scroll(br, pick)
        how = str(sr.get("r") or "")
        if how == "scrolled":
            quiet = nomove = 0
            stall = 0 if new else stall + 1
            if stall >= STALL_MAX:
                meta["end"] = "stall"
                break
            _sleep(1.0)
            continue
        if how == "no-move":                 # scrollTop 대입이 안 먹는다 — 실제 휠 입력으로
            nomove = 0 if new else nomove + 1
            if nomove > 2:
                meta["end"] = "stuck"
                break
            if _wheel(br, sr):
                meta["wheel"] += 1
            _sleep(1.0)
            continue
        if how == "bottom":
            stall = nomove = 0
            if sr.get("busy"):               # '불러오는 중' — 끝이 아니다. 더 기다린다
                busy += 1
                meta["busy"] += 1
                if busy > BUSY_MAX:
                    meta["end"] = "busy"
                    break
                _sleep(2.0)
                continue
            quiet = 0 if new else quiet + 1
            if quiet >= END_CONFIRM:
                meta["end"] = "bottom"       # 끝 근거 ② — 메일 목록 확인은 아래에서
                break
            if quiet == 1 and meta["more"] < MORE_MAX and _more(br, pick):
                meta["more"] += 1            # 결과 '더 보기' — 눌렀으면 다시 센다
                quiet = 0
                _sleep(2.0)
                continue
            if quiet == 2 and _wheel(br, sr):
                meta["wheel"] += 1           # 실제 휠 — 다음 묶음 불러오기를 깨운다
            _sleep(1.5 + quiet)              # 1.5·2.5·3.5초 — 다음 묶음이 늦게 붙는 사서함(지연 로드)을 끝으로 오인하지 않게
            continue
        if how == "no-list":
            repick += 1
            if repick <= 2:
                pick = None
                continue
            meta["end"] = "nolist"
            break
        run.bump(how or "scroll_none")       # no-scroller · 응답 없음 — 끝을 모른다
        meta["end"] = "noscroll"
        break
    else:
        run.bump("screen_cap")
        meta["end"] = "cap"
    parsed = sum(1 for g in got if g[1] is not None)
    meta["mail_ok"] = owa_parse.mail_list_ok(meta["lst"], parsed, len(got))
    meta["reached"] = meta["end"] == "bottom" and meta["mail_ok"]
    if meta["end"] == "bottom" and not meta["mail_ok"]:
        run.bump("end_not_mail")
    return got, meta


def _cen_box(run, folder):
    """폴더별 읽기 진단 칸 — reads(화면 읽기 수 · 표기 바꿔 다시 읽기 포함)·screens·ends(끝 사유별 수)·fb(목록 폴백의 끝 사유)·
    v(읽기별 판정 수)·fin(조각별 마지막 판정 수 — 검색 조각만)·wheel·more·busy."""
    return run.cen["mail"].setdefault("box", {}).setdefault(folder, {"reads": 0, "screens": 0, "ends": {}, "fb": "", "ok": 0,
                                                                     "wheel": 0, "more": 0, "busy": 0, "v": {}, "fin": {}})


def _cen_read(run, folder, meta, list_mode, v, got):
    """한 번 읽기의 구조 진단을 run.cen['mail'] 에 — 구조만(칸 수·고른 칸 사실·스크롤 칸·끝 사유·날짜 표기 꼴). 글자는 남기지 않는다
    (행 골격은 owa_parse.skeleton 이 글자를 x 로 바꾼 뒤에만)."""
    cm = run.cen["mail"]
    key = "l" if list_mode else "s"
    lst = meta.get("lst") or {}
    # 화면 모양은 그 방식(검색 s·목록 l)의 첫 읽기 — 다만 칸을 못 고른 읽기(결과 없음 등) 뒤에 고른 읽기가 오면 그것으로 바꾼다
    if (key not in cm or (cm[key].get("pick") is None and meta.get("pick") is not None)) and (meta.get("cands") or lst):
        cm[key] = {"lb": meta.get("lb", 0), "sb": 1 if meta.get("search") else 0, "sec": list(meta.get("sec") or [])[:8],
                   "cands": [[_int(c.get("i")), str(c.get("role") or "")[:12], _int(c.get("opts")), _int(c.get("mailish")),
                              _int(c.get("conv")), _int(c.get("main")), _int(c.get("vis")), _int(c.get("al"))]
                             for c in (meta.get("cands") or [])[:6]],
                   "pick": meta.get("pick"),
                   "lst": {k: lst.get(k) for k in ("opts", "mailish", "conv", "how", "d", "where", "sh", "ch", "busy") if k in lst}}
    if meta.get("skel") and not cm.get("skel"):
        cm["skel"] = owa_parse.skeleton(meta["skel"])
    if "fmt" not in cm:
        for it, _d, _r in got:
            if it.get("label") or it.get("texts"):
                cm["fmt"] = owa_parse.fmt_flags(" , ".join([str(it.get("label") or "")] + [str(x) for x in it.get("texts") or []]))
                break
    bx = _cen_box(run, folder)
    bx["reads"] += 1
    bx["screens"] += meta.get("screens", 0)
    end = meta.get("end") or "?"
    bx["ends"][end] = bx["ends"].get(end, 0) + 1
    if list_mode:
        bx["fb"] = end
    bx["ok"] += 1 if meta.get("mail_ok") else 0
    for k in ("wheel", "more", "busy"):
        bx[k] += _int(meta.get(k))
    bx["v"][v] = bx["v"].get(v, 0) + 1
    ds = [g[1] for g in got if g[1]]
    if ds:
        e0 = min(ds).isoformat()
        cm["earliest"] = min(cm.get("earliest") or e0, e0)


def _rebase(br, url):
    """주소의 호스트를 지금 탭의 Outlook 호스트로(새 도메인 outlook.cloud.microsoft 등) — 모르면 그대로."""
    try:
        h = (urlparse(br.href() or "").hostname or "").lower()
    except Exception:
        h = ""
    if h and h in HOSTS and h != "outlook.live.com":
        u = urlparse(url)
        return u._replace(netloc=h).geturl()
    return url


def _search_slice(br, run, folder, url, s, e, diag):
    """한 폴더·한 달 조각을 기간 검색으로 읽는다 → (got, 판정, D, 상태 ok|skip|timeout|login|personal).
    · 이 실행에서 걸린 표기(Run.srch.proven)가 있으면 그것만, 없으면 SEARCH_FORMS 를 차례로 — '결과 없음'·날짜 없음은 표기가
      안 걸린 것일 수 있어(모르는 표기는 낱말 검색이 된다) 다음 표기로 넘어가고, 그 조각을 0건 확인으로 치지 않는다.
    · 결과에 조각 밖 날짜(filter_ineffective): 화면 맨 위가 폴더의 최신 메일(오늘 근처)이면 검색이 화면에 안 걸린 것(폴더 목록
      그대로) — 표기를 바꿔도 같으므로 이 실행의 검색을 접는다(broken · 남은 폴더는 바로 목록 폴백). 그 밖(표기를 다른 날짜로
      읽음)은 그 표기만 버리고(dead) 다음 표기로. 걸린 표기에서만 '결과 없음'이 empty_verified(zero_ok)다."""
    sr = run.srch
    if sr["broken"] or sr["nobox"]:
        return [], "unverified", None, "skip"
    forms = ([f for f in SEARCH_FORMS if f[0] == sr["proven"]] if sr["proven"]
             else [f for f in SEARCH_FORMS if f[0] not in sr["dead"]])
    if not forms:
        sr["broken"] = True
        return [], "unverified", None, "skip"
    got, v, D, searched = [], "unverified", None, False
    for k, fmt in forms:
        if run.out_of_time():
            break
        st = br.goto(url)
        if st in ("login", "personal"):
            return [], v, D, st
        if st != "ok":
            run.bump("goto_timeout")
            return [], v, D, "timeout"
        if not br.search(fmt(s, e)):
            run.bump("search_none")
            sr["nobox"] = True
            break
        searched = True
        diag["search"] += 1
        sr["tries"] += 1
        got, meta = _read_screens(br, run, folder, s, e, False)
        diag["pages"] += meta["screens"]
        proven = sr["proven"] == k
        v, D = owa_parse.slice_verdict([g[1] for g in got], s, e, meta["empty"] and proven, False, meta["reached"])
        if v in ("ok", "list_verified") and not meta["mail_ok"]:
            run.bump("not_mail_list")
            v, D = "unverified", None
        if _folder_mismatch(folder, meta["sel"]):
            run.bump("folder_mismatch")
            got, v, D = [], "unverified", None
        _cen_read(run, folder, meta, False, v, got)
        if v == "filter_ineffective":
            if proven:
                break                        # 걸리던 표기가 이 조각에서만 안 걸림 — 이 폴더만 목록 폴백
            sr["dead"].append(k)
            newest = max((g[1] for g in got if g[1]), default=None)
            if (newest and newest >= run.today - timedelta(days=3)) or len(sr["dead"]) >= len(SEARCH_FORMS):
                sr["broken"] = True
                log("메일 검색: 결과에 조각 밖 날짜(폴더 목록 그대로) — 기간 검색이 화면에 걸리지 않습니다. "
                    "이번 실행은 목록을 최신부터 내려 읽습니다")
                break
            got = []                         # 이 표기는 날짜를 다르게 읽는다 — 다음 표기로
            continue
        if v in ("ok", "list_verified", "empty_verified"):
            if v != "empty_verified" and not proven:
                sr["proven"] = k
                log(f"메일 검색: 기간 표기 '{k}' 가 걸림(결과가 조각 안) — 이번 실행은 이 표기로 읽습니다")
            break
        got = []                             # 결과 없음(표기 미확인)·날짜 없음 — 다음 표기로(이 화면의 행은 받지 않는다)
    if searched:
        sr["slices"] += 1
        if v in ("ok", "list_verified", "empty_verified"):
            sr["hit"] += 1
        fin = _cen_box(run, folder)["fin"]
        fin[v] = fin.get(v, 0) + 1
    return got, v, D, ("ok" if searched else "skip")


def collect_mail(br, d0, d1, fake=None, today=None, run=None):
    """달(최신 달부터) × 폴더(받은 편지함 → 보낸 편지함) 슬라이스로 읽는다. box 는 (화면의 폴더명 조각) > (읽은 폴더) 순.
    검색 범위가 '모든 폴더'로 잡힌 OWA 라도 같은 항목(key)은 먼저 읽은 받은 편지함 슬라이스에 남으므로
    발신이 수신으로 격하될 뿐, 수신이 발신(능동 신호)이 되는 방향의 오류는 생기지 않는다.
    LM28(F-03): 조각마다 owa_parse.slice_verdict 로 '읽음'을 판정한다(_search_slice — 표기 확인). 검색이 안 걸린 폴더
    (filter_ineffective·unverified·검색 접음)는 폴더당 1회 폴백 — 폴더 주소로 다시 열어 최신부터 기간 시작 앞까지 내려 기간 전체를
    판정하고(끝 근거가 없으면 끊김 없이 읽은 최신 쪽만 ok), 그 폴더의 남은 조각은 건너뛴다. 검색이 안 걸린 화면의 행은 버린다
    (폴백이 다시 읽는다). 최신 달부터 읽는 것은 검색 표기를 메일이 있을 법한 달에서 먼저 확인하고(그 표기에서만 '결과 없음'이
    0건 확인), 예산에 닿으면 오래된 달이 남게(다음 실행이 잇는다) 하려는 것이다.
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

    months = list(reversed(months_of(d0, d1)))
    if fake is None and len(months) > 1 and months[0][1] >= run.today - timedelta(days=1):
        # 검색 표기는 다 지난 달에서 먼저 확인한다 — 무시된 검색(폴더 목록 그대로)이 첫 화면의 오늘 날짜 메일로 바로 드러난다
        #   (이번 달을 먼저 하면 폴더 목록도 조각 안 날짜라 한 달을 다 내려야 안다)
        months[0], months[1] = months[1], months[0]
    for s, e in months:
        mon_n, tried = 0, False
        for folder, url0 in MAIL_FOLDERS:
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
                url = _rebase(br, url0)
                got, v, D, how = _search_slice(br, run, folder, url, s, e, diag)
                if how in ("login", "personal"):
                    return rows, how, diag, day_st
                if how == "timeout":
                    continue
                if v in ("filter_ineffective", "unverified"):
                    if how == "ok":
                        run.c["filter_ineffective" if v == "filter_ineffective" else "slices_unverified"] += 1
                    else:
                        run.bump("search_skip")          # 이 실행의 검색을 접었다(조각 밖 날짜·검색창 없음) — 바로 목록으로
                    if run.out_of_time():
                        continue
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
                    # 끝 근거는 '기간 시작 앞 도달'(list_verified D<d0) 또는 '바닥 확인 + 메일 목록'(reached)뿐 — 'fits' 는 없다
                    v, D = owa_parse.slice_verdict([g[1] for g in got], d0, d1, meta["empty"], True, meta["reached"])
                    if v != "empty_verified" and not meta["mail_ok"]:
                        run.bump("not_mail_list")       # 메일 목록으로 확인 못 한 칸 — 행은 받되 '읽음'은 없다
                        v, D = "unverified", None
                    if _folder_mismatch(folder, meta["sel"]):
                        run.bump("folder_mismatch")
                        got, v, D = [], "unverified", None
                    _cen_read(run, folder, meta, True, v, got)
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
                    log(f"메일 {folder}: 기간 검색 대신 목록을 최신부터 {meta['screens']}화면 내려 읽음 — 끝 근거 "
                        f"{END_KO.get(meta['end'], meta['end'])} · {'D=' + D.isoformat() if D else v}")
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


def _cal_url(br, d):
    """그 날이 든 주 보기 주소 — 지금 탭의 Outlook 호스트 그대로(/calendar/view/week/Y/M/D)."""
    return _rebase(br, f"{CAL_URL}/{d.year}/{d.month}/{d.day}")


def _head_of(pg, today=None):
    """주 보기 화면에서 주 범위로 읽힌 머리 글(구조 진단용 — 가린 뒤에만 남긴다) | ''."""
    for h in pg.get("heads") or []:
        if owa_parse.week_header_range(h, today):
            return str(h)
    return ""


def _cen_cal_page(run, pg):
    """주 보기 한 장의 구조 수(최댓값) — data-calitemid 수·aria-label 후보 수·그중 시각/종일이 든 수·머리 글 수·열 머리 수."""
    cc = run.cen["cal"]
    for k in ("nc", "nb", "nt"):
        cc[k] = max(_int(cc.get(k)), _int(pg.get(k)))
    cc["heads"] = max(_int(cc.get("heads")), len(pg.get("heads") or []))
    cc["cols"] = max(_int(cc.get("cols")), len(pg.get("cols") or []))
    cc["grid"] = 1 if (cc.get("grid") or pg.get("grid")) else 0


def collect_cal(br, d0, d1, fake=None, today=None, run=None):
    """주 보기로 일정을 읽는다. LM28(F-05): 가장 최근 주(d1 이 든 주)만 URL 로 열고, 그다음은 '이전 주' 단추를 1회씩 눌러
    순차로 읽는다. 매번 화면 머리의 날짜 범위(cal_screen_range)가 기대한 주와 같을 때만 그 주를 읽음(ok)으로 하고 행을 받는다 —
    다르면(머리 못 읽음·다른 주) 그 주는 unverified, 행은 버린다. 단추가 안 먹어 머리가 그대로면 CAL_RETRY 번까지 다시 누르고,
    그래도 그대로거나 단추가 없으면 주소(/calendar/view/week/Y/M/D)로 그 주를 연다 — 주소가 먹으면 남은 주도 주소로, 주소도
    무시되면(머리 그대로) 멈춘다(남은 주는 미확인 — 지나가지 않은 주를 '확인'으로 세지 않는다).
    클릭 수 ≤ 주 수 + CAL_RETRY(URL 이 무시돼 더 뒤 주가 보이면 거슬러 가는 만큼 더한다). 예전에는 주마다 URL 로 이동하고
    그리드만 보이면 그 주를 읽음으로 쳤다 — URL 이 무시되면 매주 이번 주만 보고 완료로 적었다.
    P4: 일정 0개인 주는 이 실행에서 일정을 한 번이라도 읽었을 때만 ok(일정 칸 선택자가 빗나가면 모든 주가 0개다 — 그때는
    partial), 못 읽은 일정 막대(data-calitemid 인데 날짜·시각을 못 읽음)가 있는 주는 partial. run.c.cal_complete = 기간의 지난
    날이 모두 확인됨.
    → (행, 상태 ok|empty|login|personal|timeout|unverified, diag, {날짜: st})"""
    run = run or Run(d0, d1, today)
    rows, seen = [], set()
    diag = {"weeks": 0, "events": 0, "parsed": 0}
    day_st = dict.fromkeys(_days(d0, d1), "unverified")
    one = timedelta(days=1)
    cc = run.cen["cal"]
    ev_n = cc.setdefault("ev", {"seen": 0, "cal": 0, "parsed": 0, "unparsed": 0})
    wk = {"ok": 0, "zero": 0, "part": 0, "unv": 0}
    zero_weeks = []                         # 일정 0개로 확인한 주 — 끝에 '이 실행에서 일정을 읽었나'로 ok·partial 을 정한다
    n_weeks = ((d1 - timedelta(days=d1.weekday())) - (d0 - timedelta(days=d0.weekday()))).days // 7 + 1
    run.c["weeks_total"] = n_weeks

    def keep(evs, hs, he, check):
        """그 주 화면의 일정 → (그 주의 행 | None, 못 읽은 일정 막대 수). 기간과 겹치는 것만·중복 한 번 rows 에 더한다.
        check 면 일정이 그 주 밖일 때(바탕이 아직 앞 주) (None, 0)."""
        got, bad = [], 0
        for ev in evs:
            r = parse_event(ev, hs, he)
            if not r:
                if ev.get("cal"):
                    bad += 1                 # data-calitemid 막대인데 날짜·시각을 못 읽었다 — 그 주는 '읽음'이 아니다
                continue
            if check and (r[1][:10] < (hs - one).isoformat() or r[0][:10] > (he + one).isoformat()):
                return None, 0
            got.append(r)
        diag["events"] += len(evs)
        ev_n["seen"] += len(evs)
        ev_n["cal"] += sum(1 for ev in evs if ev.get("cal"))
        ev_n["parsed"] += len(got)
        ev_n["unparsed"] += bad
        if "fmt" not in cc and evs:
            cc["fmt"] = owa_parse.fmt_flags(str(evs[0].get("label") or ""))
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
        return got, bad

    def done(st):
        proven = ev_n["parsed"] > 0
        for a, b in zero_weeks:
            owa_parse.apply_ranges(day_st, [(a, b, "ok" if proven else "partial")], run.today)
        if zero_weeks and not proven:
            run.bump("cal_zero_unproven")    # 일정을 한 번도 못 읽은 실행 — 0개 주를 '확인'으로 치지 않는다
        run.c["weeks_ok"] = wk["ok"] + (wk["zero"] if proven else 0)
        run.c["weeks_partial"] = wk["part"] + (0 if proven else wk["zero"])
        run.c["weeks_unverified"] = wk["unv"] + max(0, n_weeks - diag["weeks"])
        past = [x for d, x in day_st.items() if d < run.today]
        run.c["cal_complete"] = bool(run.c["weeks_ok"]) and all(x in ("ok", "zero_ok") for x in past) and not run.timed_out
        cc["weeks"] = {"ok": run.c["weeks_ok"], "zero": wk["zero"], "part": run.c["weeks_partial"],
                       "unv": run.c["weeks_unverified"], "total": n_weeks}
        rows.sort(key=lambda r: r[0])
        log(f"일정: {diag['weeks']}주(확인 {run.c['weeks_ok']} · 일부 {run.c['weeks_partial']} · 미확인 "
            f"{run.c['weeks_unverified']} · 클릭 {run.c['cal_clicks']}) · 요소 {diag['events']}개 중 해석 {len(rows)}건 "
            f"(다일 {diag.get('multi_day', 0)}건)")
        return rows, st, diag, day_st

    if fake is not None:                    # 회귀용(LM_OWA_FAKE) — LM24 처럼 월요일 주마다, 각본에 있는 주는 읽음
        cur = d0 - timedelta(days=d0.weekday())
        while cur <= d1:
            diag["weeks"] += 1
            evs = (fake.get("cal") or {}).get(cur.isoformat())
            keep([ev for ev in evs or [] if isinstance(ev, dict)], cur, cur + timedelta(days=6), False)
            if evs is not None:
                wk["ok"] += 1
                owa_parse.apply_ranges(day_st, [(max(cur, d0), min(cur + timedelta(days=6), d1), "ok")], run.today)
            else:
                wk["unv"] += 1
            cur += timedelta(days=7)
        return done("ok" if rows else "empty")

    w7 = timedelta(days=7)
    st = br.goto(_cal_url(br, d1), wait=5.0)
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
    _cen_cal_page(run, pg)
    head = _head_of(pg, run.today)               # 주 범위로 읽힌 머리 글(가려서만 남긴다) — 없으면 열 머리 날짜로 읽었다
    cc["hdr"] = owa_parse.mask_shape(head, 40) if head else ("cols" if ref else "")
    cc.setdefault("prev", {"ok": 0, "stuck": 0, "none": 0})
    if ref is None:
        run.bump("cal_header_none")
        cc["url"] = {"start": "unknown", "tries": 0, "ok": 0}
        log("일정: 주 보기 머리(날짜 범위)를 읽지 못해 어느 주인지 확인할 수 없습니다 — 일정은 읽음으로 적지 않습니다")
        return done("unverified")
    # 주소 이동이 먹는가 — 연 주가 d1 의 주면 먹었다(단 이번 주면 무시돼도 같은 화면이라 모른다), 다른 주면 무시됐다
    nav = {"mode": "click", "url": None}
    if ref[0] <= d1 <= ref[1]:
        nav["url"] = None if ref[0] <= run.today <= ref[1] else True
    else:
        nav["url"] = False
        run.bump("cal_url_ignored" if ref[0] > d1 else "cal_url_other")
    cc["url"] = {"start": {True: "ok", False: "ignored", None: "unknown"}[nav["url"]], "tries": 0, "ok": 0}
    st_ = {"clicks": 0, "retries": 0, "cap": n_weeks + CAL_RETRY}
    if ref[0] > d1:                         # URL 이 무시돼 더 뒤 주(이번 주 등)가 보인다 — 거슬러 가는 만큼 상한에 더한다
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
        """한 주 과거로 → (새 기준, 대안, 화면, 확인됨, 사유). 머리가 기준-7일(또는 대안-7일)이면 확인됨.
        ① '이전 주' 단추 — 머리가 그대로면 CAL_RETRY(전체) 번까지 다시 누른다. 그 밖(머리 못 읽음·다른 주)은 미확인: 기준은
           기대한 주로 두고, 읽은 머리는 대안으로 남긴다(다음 화면에서 어느 쪽이 맞았는지 가린다).
        ② 단추가 없거나 끝내 안 먹으면 주소로 기대한 주를 연다 — 먹으면 이후도 주소로. 주소도 무시되면(머리 그대로) 멈춘다."""
        exps = [(ref[0] - w7, ref[1] - w7)] + ([(alt[0] - w7, alt[1] - w7)] if alt else [])
        if nav["mode"] == "click":
            while True:
                p = press()
                if p == "cap":
                    return None, None, None, False, "cap"
                if p != "ok":
                    cc["prev"]["none"] += 1
                    run.bump("cal_prev_none")
                    break
                pg2 = _cal_page(br)
                rng = cal_screen_range(pg2, run.today)
                if rng is not None and rng in (ref, alt):
                    cc["prev"]["stuck"] += 1
                    run.bump("cal_stuck")
                    if st_["retries"] < CAL_RETRY:
                        st_["retries"] += 1
                        continue
                    break                        # 단추가 안 먹는다 — 주소로
                cc["prev"]["ok"] += 1
                if rng in exps:
                    return rng, None, pg2, True, "ok"
                run.bump("cal_header_none" if rng is None else "cal_header_mismatch")
                return exps[0], rng, pg2, False, "ok"
        if nav["url"] is False:
            return None, None, None, False, "stuck"
        g = br.goto(_cal_url(br, exps[0][0]), wait=5.0)
        cc["url"]["tries"] += 1
        if g in ("login", "personal"):
            return None, None, None, False, g
        pg2 = _cal_page(br) if g == "ok" else {}
        rng = cal_screen_range(pg2, run.today) if pg2 else None
        if rng is not None and rng in exps:
            nav["mode"], nav["url"] = "url", True
            cc["url"]["ok"] += 1
            return rng, None, pg2, True, "ok"
        same = rng is not None and rng in (ref, alt)
        if nav["url"] is True and not same:  # 주소 이동은 이 실행에서 먹었다 — 이 주 머리만 다르다(그 주만 미확인)
            run.bump("cal_header_none" if rng is None else "cal_header_mismatch")
            return exps[0], rng, pg2, False, "ok"
        nav["url"] = False
        run.bump("cal_url_fail")
        return None, None, None, False, "stuck"

    alt, ok_week = None, True
    while ref[0] > d1:                      # 시작 주까지 — 이동만(읽지 않는다)
        nref, nalt, npg, okw, p = advance(ref, alt)
        if nref is None:
            if p in ("login", "personal"):
                return rows, p, diag, day_st
            run.bump("cal_click_cap" if p == "cap" else "cal_nav_stuck")
            return done("unverified")
        ref, alt, pg, ok_week = nref, nalt, npg, okw
    while True:
        if ref[1] >= d0 and ref[0] <= d1:
            diag["weeks"] += 1
            _cen_cal_page(run, pg)
            evs = [ev for ev in pg.get("events") or [] if isinstance(ev, dict)]
            got, bad = keep(evs, ref[0], ref[1], True) if ok_week else (None, 0)
            if ok_week and got is None:     # 일정이 그 주 밖 — 바탕이 아직 앞 주다. 한 번 더 읽는다
                _sleep(1.5)
                pg = _cal_page(br)
                if cal_screen_range(pg, run.today) == ref:
                    got, bad = keep([ev for ev in pg.get("events") or [] if isinstance(ev, dict)], ref[0], ref[1], True)
                if got is None:
                    run.bump("cal_stale")
            a, b = max(ref[0], d0), min(ref[1], d1)
            if ok_week and got is not None:
                if bad:                      # 못 읽은 일정 막대가 있다 — 행은 받되 그 주는 일부만
                    wk["part"] += 1
                    run.bump("cal_unparsed", bad)
                    owa_parse.apply_ranges(day_st, [(a, b, "partial")], run.today)
                elif got:
                    wk["ok"] += 1
                    owa_parse.apply_ranges(day_st, [(a, b, "ok")], run.today)
                else:
                    wk["zero"] += 1
                    zero_weeks.append((a, b))
            else:
                wk["unv"] += 1
        if ref[0] <= d0 or run.out_of_time():
            break
        nref, nalt, npg, okw, p = advance(ref, alt)
        if nref is None:
            if p in ("login", "personal"):
                return rows, p, diag, day_st
            run.bump("cal_click_cap" if p == "cap" else "cal_nav_stuck")
            log("일정: '이전 주' 단추도 주소 이동도 먹지 않아 더 거슬러 가지 못했습니다 — 남은 주는 미확인(다음 실행이 다시 읽음)")
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
            run.start_phase(kind)           # 메일은 예산 끝 일부(reserve)를 일정에 남기고 멈춘다
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
    # 메일·일정을 함께 읽으면 메일은 예산 끝의 일부를 일정에 남긴다 — 큰 사서함의 목록 폴백이 일정을 통째로 굶기지 않게
    reserve = min(300.0, 0.25 * budget) if len(todo) > 1 else 0.0
    run = Run(d0, d1, deadline=t0 + budget, recover_max=cfg.get("owaTimeRecoverMax", 150), reserve=reserve)
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
            run.start_phase(kind)
            results[kind] = (collect_mail(None, d0, d1, fake, run=run) if kind == "mail"
                             else collect_cal(None, d0, d1, fake, run=run))
    return finish(results, fail, run, todo, paths, src_p, out_dir, tag, src_name, store_subject, cfg)


def _verdict_ko(day_st_by_axis, today, axes=("mail_in", "mail_out")):
    """축들의 지난 날 상태 → '확인'(모두 ok·zero_ok) · '일부'(일부만) · '미확인'(하나도 없음) · '오늘만'."""
    sts = [x for ax in axes for d, x in (day_st_by_axis.get(ax) or {}).items() if d < today]
    if not sts:
        return "오늘만"
    if all(x in ("ok", "zero_ok") for x in sts):
        return "확인"
    return "일부" if any(x in ("ok", "zero_ok") for x in sts) else "미확인"


def _fit(cen, cap=4000):
    """dom_census 를 직렬화 cap 자 안으로(collect_status.KEEP_NESTED 4096 — 넘치면 last_run.json 에서 빠진다).
    넘치면 행 골격 → 후보 칸 표 → data-app-section 값 → 폴더별 세부 순으로 덜어 낸다."""
    def size(o):
        return len(json.dumps(o, ensure_ascii=False, default=str))
    if size(cen) <= cap:
        return cen
    m = cen.get("mail") if isinstance(cen.get("mail"), dict) else {}
    for drop in (("skel",), ("l", "cands"), ("s", "cands"), ("l", "sec"), ("s", "sec"), ("box",)):
        tgt = m
        for k in drop[:-1]:
            tgt = tgt.get(k) if isinstance(tgt.get(k), dict) else {}
        tgt.pop(drop[-1], None)
        if size(cen) <= cap:
            return cen
    return {"v": cen.get("v"), "ver": cen.get("ver"), "cut": 1}


def _census(run, todo, results):
    """화면 구조 진단 → (사람용 한 줄 '구조: …'(200자 안팎 — 사진 한 장으로 원인 확정용), dom_census dict ≤ 4KB).
    구조만 — 칸 수·고른 칸·스크롤 칸·검색 표기·끝 근거·주 이동. 글자는 mask_shape 로 가렸고 aria-label 은 길이만이다."""
    cen = {"v": 2, "ver": COLLECTOR_VER}
    parts = []
    if "mail" in todo and "mail" in results and run.cen["mail"]:
        cm = run.cen["mail"]
        st = cm.get("l") or cm.get("s") or {}
        lst = st.get("lst") or {}
        if st.get("pick") is None:
            a = f"listbox {st.get('lb', 0)}(메일 후보 없음)"
        else:
            a = (f"listbox {st.get('lb', 0)}(메일 후보 #{_int(st.get('pick')) + 1} option {lst.get('opts', 0)}·"
                 f"{SC_KO.get(str(lst.get('how') or ''), '스크롤칸 ?')})")
        sb = (cm.get("s") or st).get("sb")
        sr = run.srch
        if sr["slices"]:
            b = f"조각 검색 걸림 {sr['hit']}/{sr['slices']}" + (f"({sr['proven']})" if sr["proven"] else "")
        else:
            b = "조각 검색 못 함(검색창 없음)" if sr["nobox"] else "조각 검색 안 함"
        ends = []
        for f, ko in (("inbox", "받은"), ("sent", "보낸")):
            bx = (cm.get("box") or {}).get(f)
            if not bx:
                continue
            if bx.get("fb"):
                ends.append(f"{ko} {END_KO.get(bx['fb'], bx['fb'])}")
            else:                            # 검색 조각만 — 끝까지 확인한 조각(ok·결과 없음 확인) / 검색한 조각
                fin = bx.get("fin") or {}
                ends.append(f"{ko} 검색 끝 {fin.get('ok', 0) + fin.get('empty_verified', 0)}/{sum(fin.values())}")
        vd = _verdict_ko(results["mail"][3], run.today)
        parts.append(f"{a} · 검색창 {'예' if sb else '아니오'} · {b} · 가장 이른 날짜 {cm.get('earliest') or '없음'} · "
                     f"끝 근거 {'·'.join(ends) or '없음'} → {vd}")
        cen["mail"] = dict(cm, srch=dict(sr), verdict=vd)
    if "cal" in todo and "cal" in results and run.cen["cal"].get("url"):
        cc = run.cen["cal"]
        w = cc.get("weeks") or {}
        pv = cc.get("prev") or {}
        if pv.get("ok"):
            prev = f"먹힘 {pv['ok']}" + (f"·멈춤 {pv['stuck']}" if pv.get("stuck") else "")
        elif pv.get("stuck"):
            prev = f"안 먹힘 {pv['stuck']}"
        else:
            prev = "단추 없음" if pv.get("none") else "안 씀"
        ul = cc.get("url") or {}
        url = {"ok": "먹힘", "ignored": "무시", "unknown": "모름"}.get(str(ul.get("start")), "모름")
        if ul.get("tries"):
            url += f"·이동 {ul.get('ok', 0)}/{ul['tries']}"
        ev = cc.get("ev") or {}
        parts.append(f"일정 주 {w.get('ok', 0)}/{w.get('total', 0)}(머리 {'예' if cc.get('hdr') else '아니오'}·이전 주 {prev}·"
                     f"주소 {url}·막대 {ev.get('seen', 0)}·못 읽음 {ev.get('unparsed', 0)}) → "
                     f"{'완료' if run.c.get('cal_complete') else '미완'}")
        cen["cal"] = dict(cc, complete=bool(run.c.get("cal_complete")))
    return "구조: " + " | ".join(parts), _fit(cen)


def finish(results, fail, run, todo, paths, src_p, out_dir, tag, src_name, store_subject, cfg):
    """읽은 결과 저장(병합) → mail_source(_<tag>).json → LMSTATUS. 로그인으로 끊겨도 그 앞에서 읽은 것은 저장한다."""
    total, counts, ranges = 0, {}, []
    axes = {"mail": ("mail_in", "mail_out"), "cal": ("cal",)}
    any_read = False
    vers = {}
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
        vers[kind] = _verified(by_axis)
    run.c["collector_ver"] = COLLECTOR_VER
    if run.cen["mail"].get("box") or run.cen["cal"].get("url"):
        # 화면 구조 한 줄 — 저장 요약 줄 바로 앞(run.py 는 마지막 12줄을 화면에, '구조:' 줄은 last_run.json 단계 census 로 따로
        # 싣는다 — 수집 진단 화면이 note 아래에 그대로 보여 준다). 같은 내용 + 행 골격은 counts.dom_census(4KB 이내).
        line, cen = _census(run, todo, results)
        run.c["dom_census"] = cen
        log(line)
    for kind in todo:
        if kind not in results:
            continue
        rows = results[kind][0]
        ver = vers[kind]
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
    if run.timed_out or run.hit_time:
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
                # 주 보기는 반복 회의를 회차마다 그린다 — 색인 폴백(마스터 1건)과 달리 회차가 다 보인다. LM28: '완전'은 기간의
                # 지난 날이 모두 확인됐을 때만(예전엔 확인한 주가 하나만 있어도 true — 현장: 일정 2건·cal_stale 1 인데 true)
                src["calendar_complete"] = bool(run.c.get("cal_complete"))
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
