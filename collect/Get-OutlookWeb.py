# -*- coding: utf-8 -*-
r"""mail.owa · cal.owa — Outlook 웹 백필 수집기(CM §11.3 · §14 · §15, 계약 §2.17 · §3.10 · §6.5 · §7.3 · D-14 · X-132 ·
X-184 · X-315). 모든 PC 에서 돈다(계약 v1.3 §0.8 V5 — 버전 무관 경로). 본인 전용 Edge 프로필은 ``lm27.bridge.session.EdgeSession.open(
role="owa")`` 하나로만 연다 — Edge 인자·프로필·포트 설정을 두지 않는다(G-B12 · L-16). 사용자 대신 로그인하지 않는다.

    "<PY>" -X utf8 -I -B collect\Get-OutlookWeb.py --kind mail|cal --pc <pc_id> [--from D --to D]
           [--blanks-file F] [--budget-sec N] [--force] [--run-id <run_id>] [--events jsonl|text|off]

무엇을 읽나(D-14 · X-132 — 원장의 빈칸만 비싼 경로로):
  · mail.owa — **빈칸만**: ``--blanks-file F`` = ``lm27.collect.todo`` 가 그 실행 폴더에 쓰는
    ``data\derived\collect\<run_id>\blanks_<src>.json`` = ``[{todo_id, date_range:[from, to], kind_axis}]``(X-315)의 날짜
    구간만 읽는다. 달 조각마다 받은 편지함 → 보낸 편지함 순서로 검색(``received>=… received<=…``)해 목록을 끝까지 내린다.
    같은 항목은 먼저 읽은 받은 편지함 쪽에 남는다(수신이 발신 = 능동 신호로 둔갑하지 않게 — 이전 판 감사).
    **보낸 편지함은 항목을 열어** 읽기 창 머리의 시각으로 분 단위(minute), **받은 메일은 열지 않는다**(읽음 표시를 바꾸지
    않는다) — 목록이 보여 주는 날짜만(date: 로컬 12:00 자리값, 시간 근거 아님 — CM-11). 오늘·어제·요일처럼 목록이 시각을
    보여 주는 항목은 minute. kind_axis(mail_in·mail_out)는 기록만 하고 두 폴더를 함께 읽는다 — 날짜 단위 커서가 폴더별로
    갈라지지 않게. ``--blanks-file`` 이 없으면 ``--from``·``--to`` 를 둘 다 준 경우만 그 구간(수동 진단), 아니면 대상 없음
    (rc 1 — 전체 재수집은 폐기).
  · cal.owa — **기간 전체**(색인이 펼치지 못한 반복 회의 보완): 주 보기(월요일 시작)를 주마다 열어 일정 요소의
    aria-label·글자를 해석한다. 여러 날 일정은 한 행(첫날~마지막날), 종일 일정은 date. ``--blanks-file`` 을 주면 그 구간만.
    기간 기본값 = 오늘 − ``collect.lookbackDays`` ~ 오늘(로컬).

원문(제목·이름·미리보기·장소)은 메모리에만 둔다. 디스크에는 ``lm27.privacy.sanitize.sanitize_record`` 를 통과한 봉인 행만
``lm27.store.SegmentWriter`` 로 쓴다(in-process — 계약 §1.5). 날짜는 화면이 '이 항목의 시각'이라 말하는 머리 조각
(title·aria-label 의 날짜·시각 조각)에서만 찾고, 미리보기·본문 인용문의 날짜는 쓰지 않는다(이전 판 결함).
시각 해석의 시간대는 이 PC 의 수집 순간 오프셋(``lm27.util.tz.capture_offset_min``)이며, 근무 시간대(``time.tzOffsetMin``)
와 다르면(UTC 클라우드PC) 분 단위 행에 ``flags.utc_suspect`` 를 달고 사유 R-TZ(경고)를 남긴다(CM-16).

커서(계약 §3.10 · X-300): ``raw_cursor.json`` 의 그 src 값 = ``{"assigned_todo_ids": [...], "done_ranges": [[from, to], ...]}``.
  · done_ranges = 끝까지 읽은(화면을 알아본) 날짜 구간(로컬, 양끝 포함). 메일은 오늘 이전 날만, 일정은 오늘이 들지 않은 주
    조각만 넣는다(이번 주는 다음 실행이 통째로 다시 읽는다 — 회의 변경 반영). 다음 실행은 이 구간을 건너뛴다(``--force`` =
    무시). 원장(``lm27.collect.ledger``)은 이 구간을 '읽었음'으로 볼 수 있다 — 읽었고 0건인 날(zero_ok)을 세그먼트만으로는
    알 수 없기 때문이다. 화면을 못 알아본 조각(선택자 실패)·예산에 끊긴 조각은 넣지 않는다.
  · assigned_todo_ids = 빈칸 파일의 todo 중 그 구간을 끝까지 읽은 것(최근 500개).
  · 커서는 그 조각의 ``SegmentWriter.flush()`` 성공 뒤에만 ``save_raw_cursor(paths, pc_id, src, value)`` 로 저장한다.
    원문·원 ID 를 키로 쓰지 않는다.

rc(계약 §8.1): 0 새 레코드(정제기가 버린 행도 관측) · 1 대상 없음·0건 · 2 로그인 필요(R-LOGIN, 조건부 액세스 R-CA —
로그인 전 '불가' 확정 0) · 3 드라이버 불가·불완전(R-EDGEPOL · R-NOAPP · R-WEBSEL · R-TRANSPORT — 사유 필수) · 4 읽을 구간이
모두 이미 읽음. 예산(``--budget-sec``, 0 = 없음) 소진은 rc 0/1 + partial + budget_hit + R-BUDGET(조각 단위로 저장하고 다음
실행이 커서로 이어 읽는다). ``exit 0`` 고정 금지.
상태(계약 v1.2 C1): stderr 마지막 줄 ``{"_status": {schema:"lm27.collector_status/1", src, rc, reasons[], partial, cap_hit,
budget_hit, n, counts{}}}``(숫자·열거·사유 코드만). ``--events jsonl``(기본)이면 stdout 에 30초마다 ``progress``(계약 §8.6).

시험 주입(계약 §11.3 — 형식은 ``tests\fixtures\synth\inject.py`` 머리 표): ``LM_OWA_FAKE=<json>`` 이면 브라우저 없이 그
파일의 화면 응답을 쓴다 ``{"login": bool|"ca", "mail": {"YYYY-MM": [항목…] | {"inbox": [항목…], "sent": [항목…]}},
"cal": {"YYYY-MM-DD": [일정…]}}`` — 항목 = ``{key, label, titles[], texts[]}``, 일정 = ``{label, texts[]}``. 이 수집기가
더 받는 선택 키(없어도 된다): 항목 ``open: {"head": [...]}``(보낸 편지함 항목을 열었을 때의 읽기 창 머리) · 폴더 값
``{"pages": [[항목…], …]}``(스크롤 회차) 또는 ``{"how": "", "items": []}``(선택자 실패) · ``"cal_grid": false``(주 보기를
못 찾음) · ``"login": "ca"``(조건부 액세스 차단). ``LM_NO_BROWSER=1`` 이면 Edge 를 띄우지 않는다(rc 3 + R-TRANSPORT).

이 파일은 같은 폴더의 ``Get-TeamsWeb.py``·``probe_owa.py``·``probe_teamsweb.py`` 가 함께 쓰는 웹 수집 도구(날짜·시각
해석, 상태 줄, 세션 상태 → rc 번역, 정제·저장·커서 묶음)를 담는다 — 그 파일들은 이 파일을 경로로 불러 쓴다.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)   # L-05 · 계약 §9.1 — collect\*.py 는 첫 실행문에서 자기 루트를 넣는다

import argparse
import hashlib
import json
import re
import unicodedata
from datetime import UTC, date, datetime, timedelta

from lm27.bridge.clock import INF, Deadline, default_clock
from lm27.util import events, fsx, tz

# ───────────────────────────── 상수 ─────────────────────────────
STATUS_SCHEMA = "lm27.collector_status/1"
KINDS_HERE = ("mail", "cal")
SRC_OF = {"mail": "mail.owa", "cal": "cal.owa"}
STAGE = "backfill_owa"
ROLE = "owa"
FAKE_ENV = "LM_OWA_FAKE"
NO_BROWSER_ENV = "LM_NO_BROWSER"
RC_SAVED, RC_NONE, RC_LOGIN, RC_DRIVER, RC_NONEW = 0, 1, 2, 3, 4
PC_ID_RX = re.compile(r"^pcx?_[0-9a-f]{16}$")
RUN_ID_RX = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{4}$")
DATE_RX = re.compile(r"^\d{4}-\d{2}-\d{2}$")
KIND_AXES = {"mail": ("mail_in", "mail_out"), "cal": ("cal",)}

# Outlook 웹 — 이동 주소(로그인 뒤 같은 사서함의 정식 호스트로 넘어갈 수 있다). 호스트는 파싱 뒤 **완전 일치**로만 본다
# (G-B9: 부분 문자열로 호스트를 고르지 않는다 — 다른 탭을 내 탭으로 오인한 이전 판 결함).
OWA_BASE = "https://outlook.office365.com"
MAIL_FOLDERS = (("inbox", "/mail/inbox"), ("sent", "/mail/sentitems"))
CAL_WEEK = "/calendar/view/week/{y}/{m}/{d}"
OWA_HOST_RX = re.compile(r"^outlook\.(?:office|office365)\.com$|^outlook\.cloud\.microsoft$")
# 개인(Microsoft) 계정의 사서함·팀즈(Outlook.com·Teams 개인) — 회사(조직) 계정이 아니다. 업무 자료로 읽지 않고 '로그인 필요 ·
# 개인 계정'으로 끝낸다(v1.3 §0.8 V18 '회사(조직) 계정이 아니면 메일·팀즈 웹 수집은 건너뛰고 PC 자료로'). Teams 웹도 이것을 쓴다.
PERSONAL_HOST_RX = re.compile(r"^outlook\.live\.com$|^teams\.live\.com$")

LIST_ROUNDS_MAX = 400        # 목록 한 폴더 조각에서 스크롤 회차 상한(이전 판 400 — 정지 판정이 먼저 끊는다)
LIST_STALL = 3               # 새 항목 없는 화면이 연속 3번 = 끝
LIST_SETTLE_S = 1.0          # 스크롤 뒤 그리기 대기
READY_WAIT_S = 20.0          # 목록·주 보기가 그려지기를 기다리는 상한
READY_POLL_S = 1.0
GOTO_QUICK_S = 30.0          # 이동 직후 로드·로그인 판정(짧게) — 로그인이면 조건부 액세스부터 본다
SEARCH_SETTLE_S = 4.0        # 검색 뒤 결과 그리기 대기(이전 판 5초)
OPEN_WAIT_S = 3.0            # 항목 열기 뒤 읽기 창 머리 바뀜 대기
OPEN_POLL_S = 0.5
LOGIN_POLL_S = 5.0           # 알려지지 않은 로그인 화면(회사 SSO 등) 대기 폴링
RESERVE_S = 5.0              # 예산 끝 여유 — 저장·커서·상태 줄까지 끝내도록
DONE_IDS_MAX = 500
DONE_RANGES_MAX = 400
MAX_EVENT_DAYS = 120         # 여러 날 일정으로 인정하는 최대 길이(넘으면 날짜 오독으로 보고 첫날만)
CONF_MINUTE, CONF_DATE = 0.8, 0.4     # 계약 §3.4: OWA minute 0.8 · date-only 0.4
CA_CODES = frozenset({"50005", "50097", "50158", "53000", "53001", "53002", "53003", "53004", "530032"})
AADSTS_RX = re.compile(r"^\d{5,6}$")

# 세션 상태(B §5.8 단계 문자열) → (rc, 사유). 그 밖은 모두 rc 3 + R-TRANSPORT(수송 — '불가' 확정 근거 아님).
SESSION_FAIL = {
    "login_required": (RC_LOGIN, "R-LOGIN"),
    "ca": (RC_LOGIN, "R-CA"),
    "policy_blocked": (RC_DRIVER, "R-EDGEPOL"),
    "edge_not_found": (RC_DRIVER, "R-NOAPP"),
}


class ArgError(Exception):
    pass


class FakeError(Exception):
    """주입 파일을 읽지 못함(형식·위치)."""


class BlanksError(Exception):
    """빈칸 파일을 읽지 못함(없음·형식)."""


class ScreenStop(Exception):
    """화면 쪽에서 더 갈 수 없음 — ``state`` 는 세션 단계 문자열(login_required·ca·tab_lost …)."""

    def __init__(self, state: str, info=None):
        super().__init__(state)
        self.state = state
        self.info = dict(info or {})


class StoreError(Exception):
    """정제·저장·커서 실패 — 원인 예외 유형 이름만 싣는다."""

    def __init__(self, what: str, etype: str):
        super().__init__(what)
        self.what = what
        self.etype = etype


# ───────────────────────────── 시각 도우미 ─────────────────────────────
def utc_iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def default_off(dt_utc: datetime) -> int:
    """이 PC 의 그 순간 UTC 오프셋(분) — 계약 §3.1 ``ts_local_offset``."""
    return tz.capture_offset_min(dt_utc)


def local_to_utc(naive: datetime, off_fn) -> datetime:
    """이 PC 시간대의 벽시계 시각(naive) → aware UTC(zoneinfo 없이 오프셋 두 번 맞춤)."""
    guess = naive.replace(tzinfo=UTC)
    first = guess - timedelta(minutes=off_fn(guess))
    return guess - timedelta(minutes=off_fn(first))


def local_date_of(dt_utc: datetime, off_fn) -> date:
    return (dt_utc + timedelta(minutes=off_fn(dt_utc))).date()


def off_text(dt_utc: datetime, off_fn) -> str:
    return tz.fmt_offset(off_fn(dt_utc))


def parse_day(s: str):
    if not s:
        return None
    if not DATE_RX.match(s):
        raise ArgError("날짜는 YYYY-MM-DD")
    try:
        return date.fromisoformat(s)
    except ValueError:
        raise ArgError("없는 날짜") from None


# ───────────────────────────── 날짜·시각 해석(표기 형식 무관 — 이전 판 이식) ─────────────────────────────
AM_WORDS = ("오전", "AM", "A.M.", "午前", "上午", "VORM.")
PM_WORDS = ("오후", "PM", "P.M.", "午後", "下午", "NACHM.")
DESIG = r"(?:오전|오후|AM|PM|am|pm|a\.m\.|p\.m\.|A\.M\.|P\.M\.|午前|午後|上午|下午|vorm\.|nachm\.)"
RE_TIME = re.compile(r"(?:(" + DESIG + r")\s*)?(?<!\d)(\d{1,2})[:.](\d{2})(?!\d)(?:\s*(" + DESIG + r"))?")
RE_DESIG = re.compile(DESIG)
MON_EN = {m: i + 1 for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov",
                                          "dec"))}
# 구분자는 짝이 맞아야 한다('2026년 6월 1일' · '2026. 6. 1.' · '2026-06-01') — '10.06.2026 - 12.06.2026' 의 '2026 - 12.06' 이
# 연월일로 읽히지 않게(_ymd 가 검사)
RE_YMD = re.compile(r"(\d{4})\s*([년.\-/])\s*(\d{1,2})\s*([월.\-/])\s*(\d{1,2})\s*일?")
RE_MDY = re.compile(r"(?<!\d)(\d{1,2})\s*[/.\-]\s*(\d{1,2})\s*[/.\-]\s*(\d{4})(?!\d)")
RE_MONEN = re.compile(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s*"
                      r"(\d{4})?", re.I)
RE_DMONEN = re.compile(r"(?<!\d)(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?,?\s*(\d{4})?",
                       re.I)
RE_MD = re.compile(r"(?<![\d/.])(\d{1,2})\s*[/.]\s*(\d{1,2})(?![\d/])")
RE_MD_KO = re.compile(r"(\d{1,2})\s*[월月]\s*(\d{1,2})\s*[일日]")
RE_DDMM = re.compile(r"(?<!\d)\d{1,2}\.\d{1,2}\.(?!\d)")
RE_HM_WORD = re.compile(r"(?<!\d)(\d{1,2})\s*[시時时]\s*(\d{1,2})\s*[분分]")
RE_H_WORD = re.compile(r"(?<!\d)(\d{1,2})\s*[시時时](?!\s*\d|간)")
TODAY_W = ("오늘", "today", "今日", "今天")
YDAY_W = ("어제", "yesterday", "昨日", "昨天")
# 요일 이름 → 월=0. 상대 날짜 '나머지가 이 낱말뿐'일 때만 쓰므로 한 글자('월')도 받는다('8월'과 섞이지 않는다).
WEEKDAY_W = (("월요일", "monday", "mon", "월"), ("화요일", "tuesday", "tue", "화"), ("수요일", "wednesday", "wed", "수"),
             ("목요일", "thursday", "thu", "목"), ("금요일", "friday", "fri", "금"), ("토요일", "saturday", "sat", "토"),
             ("일요일", "sunday", "sun", "일"))
WDAY = {w: i for i, ws in enumerate(WEEKDAY_W) for w in ws}
RE_WEEKDAY_ANY = re.compile(r"(?i)\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|mon|tue|wed|thu|fri|sat|"
                            r"sun)\b\.?|[월화수목금토일]요일")
_PUNCT_RX = re.compile(r"[\s,，.·|:：()\[\]~\-–—/]+")


def hm_words(s: str) -> str:
    """'오전 9시 12분' 처럼 콜론 없는 표기 → '오전 9:12'(제목 속성이 자주 이렇게 온다)."""
    s = RE_HM_WORD.sub(lambda m: f"{m.group(1)}:{int(m.group(2)):02d}", str(s or ""))
    return RE_H_WORD.sub(lambda m: m.group(1) + ":00", s)


def _hhmm(m):
    h, mm = int(m.group(2)), int(m.group(3))
    ap = (m.group(1) or m.group(4) or "").upper()
    if ap in PM_WORDS and h < 12:
        h += 12
    if ap in AM_WORDS and h == 12:
        h = 0
    if h > 23 or mm > 59:
        return None
    return h, mm


def find_times(text) -> list:
    """문자열의 모든 시각 → [(시, 분)]. 날짜 조각(10.06.2026 · 2026. 6. 10.)을 먼저 지운다 — '10.06' 이 10시 6분이 되지 않게."""
    t = RE_MDY.sub(" ", hm_words(text))
    t = RE_YMD.sub(" ", t)
    t = RE_DDMM.sub(" ", t)
    return [hm for hm in (_hhmm(m) for m in RE_TIME.finditer(t)) if hm]


def _ymd(m):
    y, s1, mo, s2, dd = m.groups()
    if not ((s1 == "년" and s2 == "월") or (s1 == s2 and s1 != "년")):
        return None
    return _safe_date(int(y), int(mo), int(dd))


def _safe_date(y, mo, dd):
    try:
        return date(y, mo, dd)
    except ValueError:
        return None


def _with_year(mo, dd, y, d0, d1, today):
    """연도 없는 표기 → 힌트 기간(d0~d1)·오늘의 해·작년 중 기간 안에 드는 쪽."""
    if y:
        return _safe_date(y, mo, dd)
    years = sorted({d0.year, d1.year}) if (d0 and d1) else []
    if today:
        years += [today.year, today.year - 1]
    for yy in years:
        d = _safe_date(yy, mo, dd)
        if d and (not d0 or not d1 or d0 <= d <= d1):
            return d
    return _safe_date(years[0], mo, dd) if years else None


def _mdy(a, b, y, d0, d1):
    """월/일/연(미국) 또는 일/월/연(유럽) — 힌트 기간 안에 드는 쪽, 없으면 유효한 첫 해석."""
    for mo, dd in ((a, b), (b, a)):
        d = _safe_date(y, mo, dd)
        if d and (not d0 or not d1 or d0 <= d <= d1):
            return d
    for mo, dd in ((a, b), (b, a)):
        d = _safe_date(y, mo, dd)
        if d:
            return d
    return None


def _md(a, b, d0, d1, today):
    for mo, dd in ((a, b), (b, a)):
        d = _with_year(mo, dd, None, d0, d1, today)
        if d and (not d0 or not d1 or d0 <= d <= d1):
            return d
    return _with_year(a, b, None, d0, d1, today) or _with_year(b, a, None, d0, d1, today)


def strip_datetime(text) -> str:
    """날짜·시각·요일·지정어·상대 날짜 낱말을 지운 나머지(구두점·공백 제외) — '날짜·시각만인 조각' 판정용."""
    t = hm_words(text)
    for rx in (RE_YMD, RE_MDY, RE_MONEN, RE_DMONEN, RE_MD_KO, RE_TIME, RE_DDMM, RE_WEEKDAY_ANY):
        t = rx.sub(" ", t)
    t = RE_MD.sub(" ", t)
    t = RE_DESIG.sub(" ", t)
    low = t.lower()
    for w in TODAY_W + YDAY_W:
        low = low.replace(w, " ")
    low = re.sub(r"(?<![가-힣])[월화수목금토일](?![가-힣])", " ", low)
    return _PUNCT_RX.sub("", low)


def is_datetime_text(text) -> bool:
    s = str(text or "").strip()
    return bool(s) and strip_datetime(s) == ""


def date_in(text, d0=None, d1=None, today=None, *, weak=False):
    """문자열의 날짜 → date 또는 None. 강한 표기(연월일·월/일/연·영문 월·'n월 n일')만. ``weak`` 면 'M/D'·'M.D' 도
    (날짜·시각만 든 조각에서만 — 제목의 'v1.2' 가 1월 2일이 되지 않게)."""
    t = str(text or "")
    for m in RE_YMD.finditer(t):
        d = _ymd(m)
        if d:
            return d
    m = RE_MDY.search(t)
    if m:
        d = _mdy(int(m.group(1)), int(m.group(2)), int(m.group(3)), d0, d1)
        if d:
            return d
    m = RE_MONEN.search(t)
    if m:
        d = _with_year(MON_EN[m.group(1)[:3].lower()], int(m.group(2)), int(m.group(3)) if m.group(3) else None,
                       d0, d1, today)
        if d:
            return d
    m = RE_DMONEN.search(t)
    if m:
        d = _with_year(MON_EN[m.group(2)[:3].lower()], int(m.group(1)), int(m.group(3)) if m.group(3) else None,
                       d0, d1, today)
        if d:
            return d
    m = RE_MD_KO.search(t)
    if m:
        d = _with_year(int(m.group(1)), int(m.group(2)), None, d0, d1, today)
        if d:
            return d
    if weak:
        m = RE_MD.search(RE_TIME.sub(" ", hm_words(t)))
        if m:
            return _md(int(m.group(1)), int(m.group(2)), d0, d1, today)
    return None


def find_dates(text, d0=None, d1=None, today=None) -> list:
    """문자열 안의 강한 날짜 전부(등장 순) — 여러 날 일정('6월 1일 ~ 6월 5일')을 첫날 하루로 접지 않게.
    잡은 조각은 같은 길이 공백으로 지워 '2026년 6월 1일' 의 '6월 1일' 이 다시 잡히지 않는다."""
    t = str(text or "")
    found = []

    def take(rx, fn):
        nonlocal t

        def sub(m):
            d = fn(m)
            if d:
                found.append((m.start(), d))
                return " " * len(m.group(0))
            return m.group(0)
        t = rx.sub(sub, t)

    take(RE_YMD, _ymd)
    take(RE_MDY, lambda m: _mdy(int(m.group(1)), int(m.group(2)), int(m.group(3)), d0, d1))
    take(RE_MONEN, lambda m: _with_year(MON_EN[m.group(1)[:3].lower()], int(m.group(2)),
                                        int(m.group(3)) if m.group(3) else None, d0, d1, today))
    take(RE_DMONEN, lambda m: _with_year(MON_EN[m.group(2)[:3].lower()], int(m.group(1)),
                                         int(m.group(3)) if m.group(3) else None, d0, d1, today))
    take(RE_MD_KO, lambda m: _with_year(int(m.group(1)), int(m.group(2)), None, d0, d1, today))
    found.sort(key=lambda x: x[0])
    return [d for _, d in found]


def first_date_pos(text):
    """문자열에서 강한 날짜 조각이 처음 나오는 위치(없으면 None) — 라벨의 '제목 | 날짜·시각' 경계."""
    pos = [m.start() for rx in (RE_YMD, RE_MDY, RE_MONEN, RE_DMONEN, RE_MD_KO) for m in [rx.search(text or "")] if m]
    return min(pos) if pos else None


def rel_only(text, today, *, bare_today: bool = True):
    """시각·지정어·구두점을 지운 나머지가 상대 날짜 낱말 **뿐**일 때만 그 날짜(오늘·어제·요일). 시각만 있으면 오늘
    (``bare_today`` — 메일 목록은 오늘 항목에 시각만 보인다. 팀즈 대화는 날짜 구분선이 날짜를 준다). 제목 속
    '월요일 회의' 같은 낱말을 날짜로 읽지 않게 엄격히 본다."""
    if today is None:
        return None
    t = hm_words(text)
    had_time = bool(RE_TIME.search(t))
    rest = _PUNCT_RX.sub(" ", RE_DESIG.sub(" ", RE_TIME.sub(" ", t))).strip().lower()
    if not rest:
        return today if (had_time and bare_today) else None
    if rest in TODAY_W:
        return today
    if rest in YDAY_W:
        return today - timedelta(days=1)
    wd = WDAY.get(rest)
    if wd is not None:
        back = (today.weekday() - wd) % 7
        return today - timedelta(days=back or 7)
    return None


def rel_date(text, today):
    """날짜 구분선 글('오늘'·'어제'·'월요일')의 상대 날짜(구분선은 날짜만 든 짧은 글이라 느슨하게 본다)."""
    if today is None:
        return None
    t = str(text or "").lower()
    if any(w in t for w in TODAY_W):
        return today
    if any(w in t for w in YDAY_W):
        return today - timedelta(days=1)
    for w, wd in WDAY.items():
        if len(w) >= 3 and w in t:
            back = (today.weekday() - wd) % 7
            return today - timedelta(days=back or 7)
    return rel_only(text, today)


def frags_of(text) -> list:
    """aria-label 같은 긴 머리 글 → 쉼표·세로줄·가운뎃점 조각."""
    return [x.strip() for x in re.split(r"[,，|·]\s*", str(text or "")) if x.strip()]


def parse_when(frags, d0=None, d1=None, today=None, *, bare_today: bool = True):
    """머리 조각들 → (날짜, (시, 분) | None) 또는 None.
    ① 같은 조각에 날짜·시각이 함께 든 것 — 날짜·시각만인 조각을 먼저, 그다음 다른 글이 섞인 조각('보낸 날짜: … 오후 3:24').
    ② 날짜만 — **날짜·시각만인 조각에서만**(제목·본문 조각 속 '9월 3일까지'를 그 항목의 날짜로 읽지 않는다).
    상대 날짜(오늘·어제·요일)는 그 조각이 시각·상대 날짜 낱말뿐일 때만(rel_only)."""
    frags = [str(f) for f in frags if f]
    pure = [f for f in frags if is_datetime_text(f)]
    mixed = [f for f in frags if f not in pure]
    for f in pure + mixed:
        ts = find_times(f)
        if not ts:
            continue
        is_pure = f in pure
        d = date_in(f, d0, d1, today, weak=is_pure) or (rel_only(f, today, bare_today=bare_today) if is_pure else None)
        if d:
            return d, ts[0]
    for f in pure:
        d = date_in(f, d0, d1, today, weak=True)
        if d:
            return d, None
        if not RE_TIME.search(hm_words(f)):
            d = rel_only(f, today)
            if d:
                return d, None
    return None


# ───────────────────────────── 범위(로컬 날짜, 양끝 포함) ─────────────────────────────
def merge_ranges(ranges) -> list:
    out = []
    for a, b in sorted((a, b) for a, b in ranges if a and b and a <= b):
        if out and a <= out[-1][1] + timedelta(days=1):
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def subtract_ranges(ranges, minus) -> list:
    out = []
    minus = merge_ranges(minus)
    for a, b in merge_ranges(ranges):
        cur = a
        for x, y in minus:
            if y < cur or x > b:
                continue
            if x > cur:
                out.append((cur, x - timedelta(days=1)))
            cur = max(cur, y + timedelta(days=1))
            if cur > b:
                break
        if cur <= b:
            out.append((cur, b))
    return out


def intersect_ranges(ranges, lo, hi) -> list:
    return [(max(a, lo), min(b, hi)) for a, b in merge_ranges(ranges) if a <= hi and b >= lo]


def covered(ranges, a, b) -> bool:
    return not subtract_ranges([(a, b)], ranges)


def ranges_json(ranges) -> list:
    return [[a.isoformat(), b.isoformat()] for a, b in merge_ranges(ranges)]


def ranges_from_json(v) -> list:
    out = []
    for x in v if isinstance(v, list) else []:
        if isinstance(x, list) and len(x) == 2 and all(isinstance(s, str) and DATE_RX.match(s) for s in x):
            try:
                a, b = date.fromisoformat(x[0]), date.fromisoformat(x[1])
            except ValueError:
                continue
            if a <= b:
                out.append((a, b))
    return merge_ranges(out)


def month_slices(ranges) -> list:
    """구간들 → 달 경계로 자른 조각(이전 판 '달 × 폴더' 검색 단위)."""
    out = []
    for a, b in merge_ranges(ranges):
        cur = a
        while cur <= b:
            nxt = (cur.replace(day=28) + timedelta(days=4)).replace(day=1)
            out.append((cur, min(b, nxt - timedelta(days=1))))
            cur = nxt
    return out


def weeks_of(ranges) -> list:
    """구간들을 덮는 주(월요일 시작) 목록."""
    out = []
    for a, b in merge_ranges(ranges):
        w = a - timedelta(days=a.weekday())
        while w <= b:
            if w not in out:
                out.append(w)
            w += timedelta(days=7)
    return sorted(out)


# ───────────────────────────── 상태 줄·사람용 한 줄 ─────────────────────────────
def new_status(src: str) -> dict:
    return {"schema": STATUS_SCHEMA, "src": src, "rc": RC_DRIVER, "reasons": [], "partial": False, "cap_hit": False,
            "budget_hit": False, "n": 0, "counts": {}}


def add_reason(st: dict, code: str) -> None:
    if code not in st["reasons"]:
        st["reasons"].append(code)


def status_line(st: dict, err=None) -> None:
    """stderr 마지막 줄(계약 v1.2 C1) — 숫자·열거·사유 코드만."""
    st["reasons"] = sorted(set(st.get("reasons") or []))
    human(json.dumps({"_status": st}, ensure_ascii=False, sort_keys=True, separators=(",", ":")), err)


def human(msg: str, err=None) -> None:
    stream = err if err is not None else sys.stderr
    try:
        stream.write(msg + "\n")
        stream.flush()
    except (OSError, ValueError):
        pass


def session_failure(state: str, info=None) -> tuple:
    """세션·화면 상태 → (rc, 사유). ``LM_NO_BROWSER``(시험 주입)로 Edge 를 띄우지 않은 것은 '미설치'가 아니다."""
    if state == "edge_not_found" and (info or {}).get("why") == "no_browser":
        return RC_DRIVER, "R-TRANSPORT"
    return SESSION_FAIL.get(state, (RC_DRIVER, "R-TRANSPORT"))


def add_login_facts(st: dict, screen) -> None:
    """로그인 필요(rc 2 · R-LOGIN)로 끝난 상태 줄에 로그인 사실을 싣는다(v1.3 §0.8 V18 — 열거·불리언만):
    ``login_pending`` = 지난 대기가 로그인 없이 끝나 이번에는 짧게 확인만 함(연결자가 ``skipped=login_pending``),
    ``login_account`` = ``personal``(로그인·도착 화면이 개인 계정 — 회사 계정 아님)."""
    if "R-LOGIN" not in st.get("reasons", ()):
        return
    fn = getattr(screen, "login_facts", None)
    f = fn() if callable(fn) else {}
    if f.get("login_pending"):
        st["login_pending"] = True
    if f.get("login_account") == "personal":
        st["login_account"] = "personal"


def is_ca_code(code) -> bool:
    c = str(code or "")
    return bool(AADSTS_RX.match(c)) and (c in CA_CODES or c.startswith("53"))


def load_fake(environ, name: str):
    """주입 파일(JSON) → dict. 변수가 없으면 None, 읽지 못하면 FakeError."""
    p = str((environ or {}).get(name) or "").strip()
    if not p:
        return None
    if not os.path.isfile(p):
        raise FakeError("missing")
    obj = fsx.read_json(p, None, want=dict)
    if obj is None:
        raise FakeError("unreadable")
    return obj


def stub_env(environ) -> list:
    """설정된 시험 주입 변수 이름(계약 §11.3 — 탐침이 경고)."""
    names = ("LM_OUTLOOK_SELFTEST", "LM_INDEX_FAKE", "LM_OWA_FAKE", "LM_TEAMSWEB_FAKE", "LM_COPILOT_STUB",
             "LM_NO_BROWSER", "LM_PROBE_FAKE")
    return [n for n in names if str((environ or {}).get(n) or "").strip()]


def nfkc(s) -> str:
    return unicodedata.normalize("NFKC", str(s or "")).strip()


def sha16(obj) -> str:
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]


# ───────────────────────────── 정제·저장·커서(계약 §2.2 · §2.3 — 지연 import) ─────────────────────────────
def store_api() -> dict:
    """정제·저장 함수 묶음. 수집기 파이썬은 lm27.privacy 에서 sanitize 모듈만 import 한다(L-10)."""
    from lm27.privacy.sanitize import make_record_context, sanitize_record
    from lm27.store import SegmentWriter
    from lm27.store.cursor import load_raw_cursor, save_raw_cursor
    return {"make_record_context": make_record_context, "sanitize_record": sanitize_record,
            "SegmentWriter": SegmentWriter, "load_raw_cursor": load_raw_cursor, "save_raw_cursor": save_raw_cursor}


class WebRun:
    """경로 하나(한 src)의 실행 묶음: 예산 · 정제 → SegmentWriter → flush · 커서 · 상태. Teams 웹 수집기도 쓴다."""

    def __init__(self, *, kind: str, src: str, pc_id: str, paths, cfg, api: dict, clock, now: datetime, off_fn,
                 budget_sec: float = 0.0, my_addrs=(), err=None):
        self.kind, self.src, self.pc_id = kind, src, pc_id
        self.paths, self.cfg, self.api = paths, cfg, api
        self.clock = clock
        self.now = now
        self.now_iso = utc_iso(now)
        self.off_fn = off_fn
        self.today = local_date_of(now, off_fn)
        self.t0 = clock.mono()
        self.dl = Deadline.after(clock, budget_sec) if budget_sec and budget_sec > 0 else Deadline(clock, INF)
        self.my_addrs = tuple(a for a in my_addrs if a)
        self.err = err
        self.st = new_status(src)
        self.c = self.st["counts"]
        self.rctx = None
        self.stored = 0
        self.dropped: dict = {}
        self.errors: dict = {}
        self.batch_errors = 0                    # 마지막 commit 묶음의 정제 error 행 수(그 날·방은 커서·체크포인트 제외)
        self.rows_in = 0
        work_off = self.cfg_get("time.tzOffsetMin", None)
        self.tz_mismatch = isinstance(work_off, int) and not isinstance(work_off, bool) and off_fn(now) != work_off
        if self.tz_mismatch:
            add_reason(self.st, "R-TZ")

    def cfg_get(self, key: str, default):
        try:
            v = self.cfg[key]
        except KeyError:
            return default
        return default if v is None else v

    # ── 예산 ──
    def out_of_time(self) -> bool:
        return self.dl.at != INF and self.dl.left() <= RESERVE_S

    def budget_cut(self) -> None:
        self.st["partial"] = True
        self.st["budget_hit"] = True
        add_reason(self.st, "R-BUDGET")

    def bump(self, key: str, n: int = 1) -> None:
        self.c[key] = self.c.get(key, 0) + n

    # ── 정제·저장 ──
    def context(self):
        """레코드 문맥(프로그램 폴더 모드 — 키링·사전·본인 이름). 처음 쓸 때 한 번 만든다."""
        if self.rctx is None:
            try:
                self.rctx = self.api["make_record_context"](self.paths.root, self.src, self.pc_id,
                                                            my_addrs=self.my_addrs, paths=self.paths, cfg=self.cfg)
            except Exception as e:                           # noqa: BLE001 — 문맥 실패는 저장 실패로(유형만)
                raise StoreError("context", type(e).__name__) from None
        return self.rctx

    def commit(self, raws) -> list:
        """원시(메모리) → 정제 관문 → 봉인 행만 SegmentWriter(flush 1회 = gzip 멤버 1개). 저장한 행 목록을 돌려준다."""
        return [r for r in self.commit_aligned(raws) if r is not None]

    def commit_aligned(self, raws) -> list:
        """``commit`` 과 같되 원시 목록과 같은 순서의 [봉인 행 | None](버림·오류는 None) — 새 메시지·표지 판정용.
        저장이 실패하면 StoreError(그 묶음은 쓰지 않는다 — with 블록이 반쪽 묶음을 버린다)."""
        self.batch_errors = 0
        if not raws:
            return []
        rctx = self.context()
        out = []
        try:
            with self.api["SegmentWriter"](self.paths, self.pc_id, self.kind, self.src) as w:
                for raw in raws:
                    o = self.api["sanitize_record"](self.kind, raw, rctx)
                    self.rows_in += 1
                    if o.status == "stored":
                        w.append(o.row)
                        out.append(o.row)
                        continue
                    why = str(o.reason or ("other" if o.status == "dropped" else "error"))
                    bucket = self.dropped if o.status == "dropped" else self.errors
                    bucket[why] = bucket.get(why, 0) + 1
                    if o.status != "dropped":
                        self.batch_errors += 1
                    out.append(None)
                w.flush()
        except StoreError:
            raise
        except Exception as e:                               # noqa: BLE001 — 저장 실패는 rc 3 + 수송 사유(유형만)
            raise StoreError("store", type(e).__name__) from None
        self.stored += sum(1 for r in out if r is not None)
        self.bump("flushes")
        return out

    def flag_row_errors(self) -> bool:
        """정제 error 행이 있었으면 상태 줄에 partial + R-TRANSPORT(정제 실패 — 계약 §6.1 수송)를 단다. 그 행이 든 날·방은
        커서(done 구간)·체크포인트에 넣지 않았으므로 다음 실행이 다시 읽는다(조용한 영구 누락 금지). 있었는가."""
        if not self.errors:
            return False
        self.st["partial"] = True
        add_reason(self.st, "R-TRANSPORT")
        return True

    def save_cursor(self, value) -> None:
        try:
            self.api["save_raw_cursor"](self.paths, self.pc_id, self.src, value)
        except Exception as e:                               # noqa: BLE001 — 커서 저장 실패: 다음 실행이 다시 읽고 id 로 흡수
            raise StoreError("cursor", type(e).__name__) from None
        self.st["cursor_saved"] = True

    def load_cursor(self) -> dict:
        try:
            cur = self.api["load_raw_cursor"](self.paths, self.pc_id) or {}
        except Exception as e:                               # noqa: BLE001
            raise StoreError("cursor_read", type(e).__name__) from None
        v = cur.get(self.src) if isinstance(cur, dict) else None
        return v if isinstance(v, dict) else {}

    def finish_audit(self) -> None:
        audit = getattr(self.rctx, "audit", None) if self.rctx is not None else None
        if audit is None or not self.rows_in:
            return
        ok = audit.flush(dur_ms=int((self.clock.mono() - self.t0) * 1000))
        if ok is False:
            self.bump("audit_fail")

    def fill_counts(self) -> None:
        self.c.update(rows_in=self.rows_in, stored=self.stored, dropped=dict(sorted(self.dropped.items())),
                      errors=dict(sorted(self.errors.items())))

    def flag_set(self, precision: str) -> dict:
        """원시 flags — 근무 시간대와 PC 시간대가 다르면 분 단위 해석 행에 utc_suspect(CM-16)."""
        return {"utc_suspect": True} if (self.tz_mismatch and precision in ("minute", "exact")) else {}


def heartbeat(stage: str, total=None):
    """--events jsonl 일 때만 30초 progress(계약 §8.6). 그 밖은 None."""
    if events.mode() != "jsonl":
        return None
    return events.Heartbeat(events.HEARTBEAT_SEC, stage=stage, total=total).start()


def stop_heartbeat(hb, done=None) -> None:
    if hb is None:
        return
    if done is not None:
        hb.update(done=done)
    hb.beat()
    hb.stop()


# ───────────────────────────── 화면 읽기 JS(값만 돌려준다 — 페이지에서 평가) ─────────────────────────────
def _js(name: str, body: str) -> str:
    return f"/*LM27:{name}*/(function(){{{body}}})()"


_CUT = ("var cut=function(s,n){s=String(s||'');if(s.length<=n)return s;var c=s.charCodeAt(n-1);"
        "return s.slice(0,(c>=0xD800&&c<=0xDBFF)?n-1:n);};")
# ↑ UTF-16 코드 단위로 자르되 앞 서로게이트에서 끊지 않는다(이모지를 반으로 잘라 외톨이 서로게이트를 넘기지 않게)
_LEAF = (_CUT + "var leafs=function(e,n){return Array.prototype.slice.call(e.querySelectorAll('span,div,a,p'))"
         ".filter(function(x){return x.childElementCount===0;}).map(function(x){return (x.textContent||'').trim();})"
         ".filter(function(x){return x;}).slice(0,n);};"
         "var titles=function(e,n){return Array.prototype.slice.call(e.querySelectorAll('[title]'))"
         ".map(function(x){return (x.getAttribute('title')||'').trim();}).filter(function(x){return x;}).slice(0,n);};")


def js_owa_list() -> str:
    """메일 목록 화면 한 장: 항목 aria-label · title · 잎 글자(메모리로만). ``window.__lm_mail`` 에 요소를 둔다(열기용)."""
    return _js("owa_list", _LEAF + """
var out={how:'',n:0,items:[],listboxes:0,search:false};
var sb=document.querySelector('#topSearchInput, input[role="searchbox"], [role="search"] input, input[aria-label*="검색"], input[aria-label*="Search"]');
out.search=!!sb;
out.listboxes=document.querySelectorAll('[role="listbox"]').length;
var SELS=['[role="listbox"] [role="option"]','[role="option"]','[role="row"][aria-label]','[data-convid]'];
var opts=[];
for(var i=0;i<SELS.length;i++){opts=Array.prototype.slice.call(document.querySelectorAll(SELS[i]));if(opts.length){out.how=SELS[i];break;}}
window.__lm_mail=opts;
out.n=opts.length;
out.items=opts.slice(0,600).map(function(o,i){return {idx:i,
 key:(o.getAttribute('data-convid')||o.getAttribute('data-item-id')||o.id||'')+'|'+cut(o.getAttribute('aria-label'),80),
 ck:o.getAttribute('data-convid')?'c':(o.getAttribute('data-item-id')?'i':''),
 label:cut(o.getAttribute('aria-label'),400),titles:titles(o,12),texts:leafs(o,24)};});
return out;""")


def js_owa_scroll() -> str:
    return _js("owa_scroll", """
var lb=document.querySelector('[role="listbox"]')||document.querySelector('[role="option"]');
if(!lb)return 'no-list';
var el=lb;
for(var i=0;i<12&&el;i++){if(el.scrollHeight>el.clientHeight+20&&getComputedStyle(el).overflowY!=='visible')break;el=el.parentElement;}
if(!el)return 'no-scroller';
var before=el.scrollTop;
el.scrollTop=el.scrollTop+Math.max(200,el.clientHeight-40);
el.dispatchEvent(new Event('scroll',{bubbles:true}));
return (el.scrollTop>before)?'scrolled':'end';""")


def js_owa_focus_search() -> str:
    return _js("owa_focus_search", """
var sels=['#topSearchInput','input[role="searchbox"]','[role="search"] input','input[aria-label*="검색"]','input[aria-label*="Search"]','input[placeholder*="검색"]','input[placeholder*="Search"]','[role="combobox"][aria-label*="검색"]','[role="combobox"][aria-label*="Search"]'];
var vis=function(el){var r=el.getBoundingClientRect();return r.width>40&&r.height>8;};
for(var i=0;i<sels.length;i++){var cs=document.querySelectorAll(sels[i]);for(var j=0;j<cs.length;j++){if(vis(cs[j])){cs[j].focus();cs[j].click();window.__lm_sb=cs[j];return 'ok';}}}
var btn=document.querySelector('button[aria-label*="검색"], button[aria-label*="Search"]');
if(btn){btn.click();return 'button';}
return 'none';""")


def js_owa_clear_search() -> str:
    return _js("owa_clear_search", """
var el=window.__lm_sb;if(!el)return 'none';
el.focus();try{if(el.select)el.select();}catch(e){}
var d=Object.getOwnPropertyDescriptor(Object.getPrototypeOf(el),'value');
if(d&&d.set){d.set.call(el,'');}else{el.value='';}
el.dispatchEvent(new Event('input',{bubbles:true}));return 'cleared';""")


def js_owa_open(idx: int) -> str:
    """목록 항목 하나를 연다(보낸 편지함만 — 받은 메일은 열지 않는다). 포인터 순서 전체를 보낸다."""
    return _js("owa_open", f"""
var e=(window.__lm_mail||[])[{int(idx)}];
if(!e||!e.isConnected)return 'gone';
try{{e.scrollIntoView({{block:'center'}});}}catch(x){{}}
var evs=['pointerdown','mousedown','pointerup','mouseup','click'];
for(var i=0;i<evs.length;i++){{e.dispatchEvent(new MouseEvent(evs[i],{{bubbles:true,cancelable:true,view:window}}));}}
return 'ok';""")


def js_owa_head() -> str:
    """읽기 창 머리의 보낸 시각 조각만(title·datetime·글자 120자) — 본문은 읽지 않는다."""
    return _js("owa_head", _CUT + """
var SELS=['[data-testid="SentReceivedSavedTime"]','[role="main"] [data-testid*="Time"]','[role="main"] time'];
var out={found:false,head:[]};
for(var i=0;i<SELS.length;i++){var els=document.querySelectorAll(SELS[i]);
 for(var j=0;j<els.length&&out.head.length<4;j++){var e=els[j];
  var t=cut(((e.getAttribute('title')||'')+' '+(e.getAttribute('datetime')||'')+' '+(e.textContent||'')).trim(),120);
  if(t)out.head.push(t);}
 if(out.head.length){out.found=true;break;}}
return out;""")


def js_owa_cal() -> str:
    """주 보기의 일정 요소: aria-label(시각·날짜가 든 것) + 잎 글자 10개. 주 보기 바탕(grid·main)이 있는가."""
    return _js("owa_cal", _LEAF + """
var out={grid:false,n:0,events:[]};
out.grid=!!document.querySelector('[role="grid"], [role="main"] [role="row"], [data-app-section="calendar-view"]');
var cands=Array.prototype.slice.call(document.querySelectorAll('[role="main"] [aria-label], [role="grid"] [aria-label], [role="button"][aria-label], [role="listitem"][aria-label]'));
var seen={};
for(var i=0;i<cands.length;i++){var l=cands[i].getAttribute('aria-label')||'';
 if(!/\\d{1,2}[:.]\\d{2}|종일|all[- ]day|終日/i.test(l))continue;
 if(!/\\d/.test(l))continue;
 var k=cut(l,160);if(seen[k])continue;seen[k]=1;
 out.events.push({label:cut(l,400),texts:leafs(cands[i],10)});
 if(out.events.length>=400)break;}
out.n=out.events.length;
return out;""")


def js_aadsts() -> str:
    """로그인 화면의 AADSTS 오류 번호만(숫자 — 조건부 액세스 판별). 페이지 글은 돌려주지 않는다."""
    return _js("web_aadsts", """
var t=(document.body&&document.body.innerText)||'';var m=t.match(/AADSTS(\\d{5,6})/);return m?m[1]:'';""")


# ───────────────────────────── 화면(가짜 · 실제 CDP) ─────────────────────────────
class FakeOwaScreen:
    """``LM_OWA_FAKE`` 화면 — 브라우저 없이 주입 파일의 항목·일정을 화면 응답처럼 낸다. ``cost_s`` = 화면 한 장마다
    시계를 미는 초(시험의 가상 시계 예산)."""

    synthetic = True
    can_open = True

    def __init__(self, fake: dict, clock, *, cost_s: float = 0.0):
        self.fake = fake if isinstance(fake, dict) else {}
        self.clock = clock
        self.cost_s = float(cost_s)

    def _cost(self) -> None:
        if self.cost_s > 0:
            self.clock.sleep(self.cost_s)

    def open(self, dl) -> str:
        lg = self.fake.get("login")
        if lg == "ca":
            return "ca"
        return "login_required" if lg else "ready"

    def login_facts(self) -> dict:
        """주입 키 ``login_pending``(bool) · ``login_account``("personal") — 세션의 로그인 보류·계정 종류 흉내(V18)."""
        return {"login_pending": self.fake.get("login_pending") is True,
                "login_account": "personal" if self.fake.get("login_account") == "personal" else ""}

    def mail_pages(self, folder: str, s: date, e: date, dl):
        v = (self.fake.get("mail") or {}).get(s.strftime("%Y-%m"))
        if isinstance(v, list):
            pages = [{"items": v}] if folder == "inbox" else []
        elif isinstance(v, dict):
            f = v.get(folder)
            if isinstance(f, list):
                pages = [{"items": f}]
            elif isinstance(f, dict) and isinstance(f.get("pages"), list):
                pages = [{"items": p if isinstance(p, list) else []} for p in f["pages"]]
            elif isinstance(f, dict):
                pages = [f]
            else:
                pages = []
        else:
            pages = []
        if not pages:                                      # 그 달·폴더에 항목이 없다 = 알아본 빈 목록(실제 화면과 같게 한 장)
            pages = [{"items": []}]
        for p in pages:
            self._cost()
            items = [it for it in p.get("items") or [] if isinstance(it, dict)]
            how = p.get("how", "fake")
            yield {"how": how, "search": bool(how), "listboxes": 1 if how else 0, "n": len(items),
                   "items": [dict(it, idx=i) for i, it in enumerate(items)]}

    def open_item(self, idx: int, item: dict, dl):
        self._cost()
        op = item.get("open") if isinstance(item, dict) else None
        head = op.get("head") if isinstance(op, dict) else None
        return [str(x) for x in head if x] if isinstance(head, list) else None

    def week(self, wk: date, dl) -> dict:
        self._cost()
        cal = self.fake.get("cal") or {}
        evs = []
        for i in range(7):
            v = cal.get((wk + timedelta(days=i)).isoformat()) if isinstance(cal, dict) else None
            evs += [x for x in v if isinstance(x, dict)] if isinstance(v, list) else []
        return {"grid": bool(self.fake.get("cal_grid", True)), "n": len(evs), "events": evs}

    def close(self) -> None:
        return None


class CdpBase:
    """실제 화면 공통 — ``EdgeSession.open(role=…)`` 의 자기 탭에서 JS 로 읽는다(남의 탭은 닫지도 읽지도 않는다).
    JS 예외는 건수만(그 화면은 빈 응답), 연결·탭 실패는 ``ScreenStop``. Teams 웹 화면도 이것을 이어 쓴다."""

    synthetic = False

    def __init__(self, session, clock, counts: dict):
        self.s = session
        self.clock = clock
        self.c = counts
        self._errs = self._error_types()

    @staticmethod
    def _error_types() -> tuple:
        from lm27.bridge.cdp import CdpError
        from lm27.bridge.session import PhaseError
        return CdpError, PhaseError

    def _bump(self, k: str) -> None:
        self.c[k] = self.c.get(k, 0) + 1

    def eval(self, expr: str, dl=None):
        """JS 평가. JS 예외는 None(건수만), 연결·탭 실패는 ScreenStop."""
        cdp_error, phase_error = self._errs
        to = 25.0 if dl is None else max(1.0, min(25.0, dl.left() if dl.at != INF else 25.0))
        try:
            return self.s.eval(expr, timeout=to)
        except phase_error as e:
            raise ScreenStop(getattr(e, "phase", "tab_lost")) from None
        except cdp_error:
            self._bump("js_errors")
            return None
        except OSError:
            raise ScreenStop("cdp_error") from None

    def call(self, method: str, params: dict) -> None:
        cdp_error, phase_error = self._errs
        try:
            self.s.call(method, params)
        except phase_error as e:
            raise ScreenStop(getattr(e, "phase", "tab_lost")) from None
        except (cdp_error, OSError):
            raise ScreenStop("cdp_error") from None

    def _sleep(self, s: float) -> None:
        self.clock.sleep(s)
        tick = getattr(self.s, "tick", None)
        if tick is not None:
            tick()

    def open(self, dl) -> str:
        st = self.s.start()
        return "ready" if st == "ready" else st

    def host(self) -> str:
        try:
            return str(self.s.page_state().get("host") or "")
        except Exception:                                    # noqa: BLE001 — 진단용(호스트를 모르면 빈 값)
            return ""

    def aadsts(self) -> str:
        v = self.eval(js_aadsts())
        return str(v) if isinstance(v, str) and AADSTS_RX.match(v) else ""

    def login_facts(self) -> dict:
        """세션의 로그인 사실(V18): 마지막 대기가 보류 상태 짧은 확인이었나 · 개인 계정 화면을 봤나."""
        return {"login_pending": getattr(self.s, "login_check", "") == "pending",
                "login_account": "personal" if getattr(self.s, "login_account", "") == "personal" else ""}

    def _session_call(self, name: str, *args) -> None:
        fn = getattr(self.s, name, None)
        if callable(fn):
            try:
                fn(*args)
            except OSError:
                pass

    def _login_wait_s(self) -> float:
        """이번 로그인 대기 상한 — 세션이 정한다(보류 중이면 짧게 — V18). 세션이 모르면 ``bridge.loginWaitMin``."""
        fn = getattr(self.s, "login_wait_s", None)
        if callable(fn):
            return float(fn())
        return float(getattr(getattr(self.s, "cfg", None), "login_wait_min", 10)) * 60.0

    def goto(self, url: str, dl, host_rx, *, wait_login: bool = True) -> str:
        """이동 + 로드·로그인 판정. 로그인 화면이면 조건부 액세스(AADSTS)부터 보고, 아니면 사람이 로그인할 때까지
        세션의 로그인 대기(``bridge.loginWaitMin`` — 로그인 보류 중이면 짧게, V18)를 예산 안에서 기다린다. ``wait_login=False``
        (탐침) 면 첫 판정(``GOTO_QUICK_S``)만 하고 더 기다리지 않는다. 알려지지 않은 호스트(회사 SSO 등)도 로그인 대기로 본다.
        개인 계정의 사서함·팀즈(``PERSONAL_HOST_RX``)에 닿으면 읽지 않고 로그인 필요(개인 계정)로 끝낸다."""
        st = self.s.goto(url, dl.sub(GOTO_QUICK_S))
        if st == "login_required":
            code = self.aadsts()
            if is_ca_code(code):
                self.c["aadsts"] = int(code)
                return "ca"
            if not wait_login:
                return "login_required"
            st = self.s.wait_page(dl)
            if st == "login_required":
                code = self.aadsts()
                if is_ca_code(code):
                    self.c["aadsts"] = int(code)
                    return "ca"
                return "login_required"
        if st != "ready":
            return st
        host = self.host()
        if host_rx.match(host):
            self._session_call("login_ok")                  # 회사 사서함·팀즈에 닿음 = 로그인 확인(보류 해제)
            return "ready"
        if PERSONAL_HOST_RX.match(host):
            return self._personal()
        self._bump("host_unexpected")
        if not wait_login:
            return "login_required"
        want = self._login_wait_s()
        wait = min(want, dl.left() if dl.at != INF else INF)
        end = Deadline.after(self.clock, wait)
        while not end.expired():
            self._sleep(LOGIN_POLL_S)
            host = self.host()
            if host_rx.match(host):
                self._session_call("login_ok")
                return "ready"
            if PERSONAL_HOST_RX.match(host):
                return self._personal()
        if wait >= want:
            self._session_call("mark_login_pending")       # 다 기다렸다 — 다음 수집은 짧게(V18)
        return "login_required"

    def _personal(self) -> str:
        """개인 계정 사서함·팀즈에 닿음 — 읽지 않는다. 세션에 계정 종류를 남기고(안내 한 번) 보류로 둔다(V18)."""
        self._bump("personal_account")
        self._session_call("note_login_account", "personal")
        self._session_call("mark_login_pending")
        return "login_required"

    def close(self) -> None:
        try:
            self.s.close()
        except Exception:                                    # noqa: BLE001 — 정리 실패는 수집 결과를 바꾸지 않는다
            self._bump("close_errors")


class CdpOwaScreen(CdpBase):
    """Outlook 웹 실제 화면: 폴더 이동 → 검색 → 목록 끝까지 내리기 · 보낸 항목 열기 · 주 보기."""

    can_open = True

    def __init__(self, session, clock, counts: dict):
        super().__init__(session, clock, counts)
        self._head = None

    def _wait_list(self, dl) -> dict:
        end = dl.sub(READY_WAIT_S)
        pg = {}
        while True:
            pg = self.eval(js_owa_list(), dl) or {}
            if pg.get("n") or pg.get("listboxes"):
                return pg
            if end.expired():
                return pg
            self._sleep(READY_POLL_S)

    def _search(self, q: str) -> bool:
        how = str(self.eval(js_owa_focus_search()) or "none")
        if how == "none":
            return False
        self._sleep(0.8)
        if how == "button":
            self.eval(js_owa_focus_search())
            self._sleep(0.6)
        self.eval(js_owa_clear_search())
        self.call("Input.insertText", {"text": q})
        self._sleep(0.4)
        for t, key in (("rawKeyDown", None), ("char", "\r"), ("keyUp", None)):
            params = {"type": t, "key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13, "nativeVirtualKeyCode": 13}
            if key:
                params["text"] = key
            self.call("Input.dispatchKeyEvent", params)
        self._sleep(SEARCH_SETTLE_S)
        return True

    def mail_pages(self, folder: str, s: date, e: date, dl):
        path = dict(MAIL_FOLDERS)[folder]
        st = self.goto(OWA_BASE + path, dl, OWA_HOST_RX)
        if st != "ready":
            raise ScreenStop(st)
        self._wait_list(dl)
        ok = self._search(f"received>={s.isoformat()} received<={e.isoformat()}")
        if ok:
            self._bump("search")
        seen_scroll: set = set()
        stall = 0
        for _rnd in range(LIST_ROUNDS_MAX):
            if dl.at != INF and dl.left() <= RESERVE_S:
                return
            pg = self.eval(js_owa_list(), dl) or {}
            pg["search"] = bool(pg.get("search")) or ok
            yield pg
            keys = {str(it.get("key") or "") for it in pg.get("items") or [] if isinstance(it, dict)}
            newk = keys - seen_scroll
            seen_scroll |= newk
            stall = 0 if newk else stall + 1
            if stall >= LIST_STALL:
                return
            r = str(self.eval(js_owa_scroll(), dl) or "")
            if r in ("no-list", "end", "no-scroller") and stall >= 1:
                return
            self._sleep(LIST_SETTLE_S)
        self._bump("list_rounds_cap")

    def open_item(self, idx: int, item: dict, dl):
        if str(self.eval(js_owa_open(idx), dl) or "") != "ok":
            return None
        end = dl.sub(OPEN_WAIT_S)
        while True:
            h = self.eval(js_owa_head(), dl) or {}
            head = [str(x) for x in h.get("head") or [] if x]
            sig = tuple(head)
            if h.get("found") and head and sig != self._head:
                self._head = sig
                return head
            if end.expired():
                return None
            self._sleep(OPEN_POLL_S)

    def week(self, wk: date, dl) -> dict:
        st = self.goto(OWA_BASE + CAL_WEEK.format(y=wk.year, m=wk.month, d=wk.day), dl, OWA_HOST_RX)
        if st != "ready":
            raise ScreenStop(st)
        end = dl.sub(READY_WAIT_S)
        while True:
            pg = self.eval(js_owa_cal(), dl) or {}
            if pg.get("grid") or pg.get("n"):
                self._sleep(1.0)
                return self.eval(js_owa_cal(), dl) or pg
            if end.expired():
                return pg
            self._sleep(READY_POLL_S)


def edge_session(role: str, run_id: str, *, paths, clock, environ=None):
    """기본 세션 공장 — ``lm27.bridge.session.EdgeSession.open(role, run_id)``(역할 공용 프로필·포트·잠금, B §4.5)."""
    from lm27.bridge.session import EdgeSession
    return EdgeSession.open(role, run_id, paths=paths, clock=clock, environ=environ)


def make_owa_screen(environ, *, paths, clock, run_id, counts, session_factory=None, fake_cost_s: float = 0.0):
    """주입 파일이 있으면 가짜 화면, 아니면 실제 세션 화면(``LM_NO_BROWSER`` 는 세션이 'edge_not_found' 로 막는다)."""
    fake = load_fake(environ, FAKE_ENV)
    if fake is not None:
        return FakeOwaScreen(fake, clock, cost_s=fake_cost_s)
    factory = session_factory or edge_session
    return CdpOwaScreen(factory(ROLE, run_id, paths=paths, clock=clock, environ=environ), clock, counts)


# ───────────────────────────── 메일 항목 해석 ─────────────────────────────
STATUS_WORDS = frozenset({"읽지 않음", "읽음", "unread", "read", "첨부 파일", "첨부", "attachment", "attachments", "플래그",
                          "flagged", "flag", "중요", "important", "high importance", "선택됨", "selected", "대화",
                          "conversation", "답장함", "replied", "전달함", "forwarded", "초안", "draft", "상세 정보", "details",
                          "고정됨", "pinned", "외부", "external"})
ATTACH_WORDS = frozenset({"첨부 파일", "첨부", "attachment", "attachments", "has attachments"})
IMPORTANT_WORDS = frozenset({"중요", "important", "high importance", "중요도 높음"})
# 폴더명은 화면의 '독립 조각'과 **완전 일치**로만 본다 — 단독 'sent' 는 제목·미리보기에 걸려 수신을 발신으로 둔갑시켰다.
SENT_WORDS = frozenset({"보낸 편지함", "보낸 항목", "보낸 메일함", "sent items", "sent mail", "sent messages"})
INBOX_WORDS = frozenset({"받은 편지함", "받은 메일함", "inbox"})
CC_WORDS = frozenset({"참조", "cc"})
# 읽지 않는 폴더(X-067 1차 — 지운 편지함·정크·임시 보관함·보낼 편지함)
SKIP_FOLDER = frozenset({"지운 편지함", "삭제된 항목", "삭제된 편지함", "deleted items", "trash", "정크", "정크 메일", "junk",
                         "junk email", "junk e-mail", "spam", "스팸", "임시 보관함", "drafts", "보낼 편지함", "outbox"})
TO_PREFIX_RX = re.compile(r"^\s*(?:받는\s*사람|받는사람|to)\s*[:：]?\s*", re.I)
RE_REFW = re.compile(r"^((RE|FW|FWD|답장|전달|회신)\s*[:：]\s*)+", re.I)


def folder_tokens(pool) -> list:
    toks = []
    for p in pool:
        for x in re.split(r"[,，|·\n]\s*", str(p or "")):
            x = x.strip().lower().rstrip(":：").strip()
            if x:
                toks.append(x)
    return toks


def _cand_text(x: str) -> bool:
    xl = x.lower().strip()
    if not xl or len(x) > 160:
        return False
    if is_datetime_text(x):
        return False
    if xl in STATUS_WORDS or xl in SENT_WORDS or xl in INBOX_WORDS or xl.rstrip(":：").strip() in CC_WORDS:
        return False
    return not re.fullmatch(r"[\d\s.,:/\-]+", x)


def recipients_of(who: str) -> list:
    """보낸 편지함 목록의 받는 사람 칸('받는 사람 김철수, 동료B') → 이름 목록(메모리)."""
    t = TO_PREFIX_RX.sub("", str(who or ""))
    names = [n.strip() for n in re.split(r"[;,，]", t) if n.strip()]
    return names[:20]


def parse_mail_item(item: dict, d0: date, d1: date, folder: str, today: date):
    """화면 항목(aria-label · title · 잎 글자) → 해석 dict 또는 None(시각을 못 짚음). 건너뛸 폴더면 ``{"skip": True}``.
    날짜는 **머리 조각(title · aria-label 의 날짜·시각 조각)에서만** — 미리보기의 인용 머리글 날짜를 쓰지 않는다."""
    label = str(item.get("label") or "")
    titles = [str(t) for t in item.get("titles") or [] if t]
    texts = [str(t) for t in item.get("texts") or [] if t]
    w = parse_when(titles + frags_of(label), d0, d1, today)
    if not w:
        return None
    toks = folder_tokens(titles + [label] + texts)
    if any(x in SKIP_FOLDER for x in toks):
        return {"skip": True}
    if any(x in SENT_WORDS for x in toks):
        box = "sent"
    elif any(x in INBOX_WORDS for x in toks):
        box = "inbox"
    else:
        box = "sent" if folder == "sent" else "inbox"     # 폴더 조각이 없으면 읽은 폴더(모르면 보수적으로 수신)
    cands = [x.strip() for x in texts if _cand_text(x)]
    who = cands[0] if cands else ""
    subject = cands[1] if len(cands) > 1 else ""
    preview = cands[2] if len(cands) > 2 else ""
    if not subject and label:
        parts = [p for p in frags_of(label) if _cand_text(p)]
        if len(parts) >= 2:
            who = who or parts[0]
            subject = parts[1]
    return {"date": w[0], "hm": w[1], "box": box, "who": who, "subject": subject, "preview": preview,
            "has_attach": any(x in ATTACH_WORDS for x in toks), "important": any(x in IMPORTANT_WORDS for x in toks)}


def mail_raw(r: dict, run: WebRun) -> dict:
    """해석 dict → 원시 레코드(P §10.2 mail 원시 이름 — 계약 §3.5). 원문은 메모리에만."""
    d = r["date"]
    hm = r["hm"] if r.get("hm") else (12, 0)              # 날짜만 보이는 항목 — 00:00 은 '새벽 산출물'이 된다
    precision = "minute" if r.get("hm") else "date"
    ts = local_to_utc(datetime(d.year, d.month, d.day, hm[0], hm[1]), run.off_fn)
    raw = {"box": r["box"], "folder_role": r["box"], "ts_utc": utc_iso(ts), "ts_local_offset": off_text(ts, run.off_fn),
           "ts_precision": precision, "observed_at": run.now_iso,
           "confidence": CONF_MINUTE if precision == "minute" else CONF_DATE,
           "flags": run.flag_set(precision)}
    subj = r.get("subject") or ""
    if subj:
        raw["subject"] = subj
        raw["conversation_topic"] = RE_REFW.sub("", subj).strip()
    if r.get("preview"):
        raw["body_text"] = r["preview"]
    if r["box"] == "sent":
        names = recipients_of(r.get("who") or "")
        if names:
            raw["to"] = [{"name": n} for n in names]
    elif r.get("who"):
        raw["sender_name"] = r["who"]
    if r.get("has_attach"):
        raw["has_attach"] = True
    if r.get("important"):
        raw["importance"] = 2
    return raw


# ───────────────────────────── 일정 해석 ─────────────────────────────
ALLDAY_RX = re.compile(r"종일|all[- ]day|終日|全天", re.I)
CANCEL_RX = re.compile(r"^\s*(?:취소됨|취소|canceled|cancelled)\s*[:：]\s*", re.I)
EVENT_PREFIX_RX = re.compile(r"(?i)^\s*(이벤트|event|약속|appointment|회의|meeting)\s*[:：]\s*")
LOCATION_RX = re.compile(r"(?:장소|location|위치)\s*[:：]\s*([^,|]+)", re.I)
TEAMS_LOC_RX = re.compile(r"teams\s*(?:모임|회의)|microsoft teams|teams meeting", re.I)
RECUR_RX = re.compile(r"되풀이|반복|recurring|series|occurrence", re.I)
PRIVATE_RX = re.compile(r"(?:^|[\s,])(?:비공개|private)(?:$|[\s,])", re.I)
EVENT_NOISE = frozenset({"되풀이", "반복", "recurring", "series", "비공개", "private", "바쁨", "busy", "한가함", "free",
                         "미정", "tentative", "부재 중", "out of office", "다른 곳에서 작업 중", "working elsewhere"})


def _busy_of(joined: str) -> str:
    if re.search(r"부재\s*중|out of office|\boof\b", joined, re.I):
        return "oof"
    if re.search(r"다른 곳에서 작업|working elsewhere", joined, re.I):
        return "elsewhere"
    if re.search(r"한가함|\bfree\b|available", joined, re.I):
        return "free"
    if re.search(r"미정|tentative", joined, re.I):
        return "tentative"
    return "busy"


def _event_subject(label: str, texts: list) -> tuple:
    """제목: 날짜·시각만인 조각·상태 낱말·장소 표기가 아닌 첫 조각(aria-label 조각 → 잎 글자). '이벤트:'·취소 접두는
    뗀다(제목 속 날짜 글자는 제목의 일부로 둔다). 취소 접두가 있었으면 (제목, True)."""
    canceled = False
    for cand in frags_of(label) + [str(x) for x in texts]:
        c = cand.strip()
        if CANCEL_RX.match(c):
            canceled = True
            c = CANCEL_RX.sub("", c)
        c = EVENT_PREFIX_RX.sub("", c).strip(" ,.|")
        if len(c) < 2 or is_datetime_text(c) or c.lower() in EVENT_NOISE or ALLDAY_RX.fullmatch(c) or LOCATION_RX.match(c):
            continue
        return c[:120], canceled
    return "", canceled


def _event_when(label: str, texts: list, d0: date, d1: date, today: date) -> tuple:
    """(날짜들, 시각들) — **날짜·시각만인 조각**(aria-label 조각·잎 글자)에서만. 제목 조각 속 날짜('9월 3일 회고')가 일정을
    여러 날로 늘리지 않게. 조각으로 나뉘지 않은 라벨이면 첫 강한 날짜 위치부터의 꼬리만 본다(제목은 보통 앞에 온다)."""
    pure = [f for f in frags_of(label) + [str(x) for x in texts] if is_datetime_text(f)]
    dates, times = [], []
    for f in pure:
        for d in find_dates(f, d0, d1, today):
            if d not in dates:
                dates.append(d)
        times += find_times(f)
    if not dates:
        pos = first_date_pos(label)
        if pos is not None:
            dates = find_dates(label[pos:], d0, d1, today)
            times = find_times(label[pos:])
    return dates, times


def parse_event(ev: dict, d0: date, d1: date, today: date):
    """일정 요소(aria-label · 잎 글자) → dict 또는 None. 날짜가 2개 이상이면 여러 날 일정 한 행
    (start = 첫 날짜 + 첫 시각, end = 마지막 날짜 + 둘째 시각 또는 23:59)."""
    label = str(ev.get("label") or "")
    texts = [str(t) for t in ev.get("texts") or [] if t]
    joined = " | ".join([label] + texts)
    dates, ts = _event_when(label, texts, d0, d1, today)
    if not dates:
        return None
    d_st, d_en = min(dates), max(dates)
    if (d_en - d_st).days > MAX_EVENT_DAYS:               # 주 보기에 넉 달짜리 일정은 없다 — 날짜 오독이면 첫날만
        d_en = d_st
    multi = d_en > d_st
    all_day = bool(ALLDAY_RX.search(joined))
    if len(ts) >= 2 and not all_day:
        st = datetime(d_st.year, d_st.month, d_st.day, ts[0][0], ts[0][1])
        en = datetime(d_en.year, d_en.month, d_en.day, ts[1][0], ts[1][1])
        if en <= st:
            en = en + timedelta(days=1) if en < st else st + timedelta(minutes=30)
    elif all_day or not ts:
        if not all_day:
            return None
        st = datetime(d_st.year, d_st.month, d_st.day, 0, 0)
        en = datetime(d_en.year, d_en.month, d_en.day, 23, 59)
    else:
        st = datetime(d_st.year, d_st.month, d_st.day, ts[0][0], ts[0][1])
        en = datetime(d_en.year, d_en.month, d_en.day, 23, 59) if multi else st + timedelta(minutes=30)
    subj, canceled = _event_subject(label, texts)
    loc = ""
    m = LOCATION_RX.search(joined)
    if m:
        loc = m.group(1).strip()[:80]
    else:
        for t in texts:
            tt = t.strip()
            if tt and tt != subj and not is_datetime_text(tt) and tt.lower() not in EVENT_NOISE                     and not CANCEL_RX.match(tt) and not ALLDAY_RX.search(tt):
                loc = tt[:80]
                break
    online = bool(TEAMS_LOC_RX.search(joined))
    return {"start": st, "end": en, "all_day": all_day, "subject": subj, "location": loc, "online": online,
            "busy": _busy_of(joined), "recurring": bool(RECUR_RX.search(joined)), "canceled": canceled,
            "private": bool(PRIVATE_RX.search(joined))}


def cal_raw(r: dict, run: WebRun) -> dict:
    s_utc = local_to_utc(r["start"], run.off_fn)
    e_utc = local_to_utc(r["end"], run.off_fn)
    precision = "date" if r["all_day"] else "minute"
    raw = {"start_utc": utc_iso(s_utc), "end_utc": utc_iso(e_utc), "ts_local_offset": off_text(s_utc, run.off_fn),
           "ts_precision": precision, "observed_at": run.now_iso,
           "confidence": CONF_DATE if r["all_day"] else CONF_MINUTE, "busy_status": r["busy"],
           "all_day": bool(r["all_day"]), "online": bool(r["online"]), "is_recurring": bool(r["recurring"]),
           "flags": run.flag_set(precision)}
    if r.get("subject"):
        raw["subject"] = r["subject"]
    if r.get("location"):
        raw["location"] = r["location"]
    if r.get("canceled"):
        raw["meeting_status"] = 5
    if r.get("private"):
        raw["sensitivity"] = 2
    return raw


# ───────────────────────────── 빈칸 파일(X-315) ─────────────────────────────
TODO_ID_RX = re.compile(r"^[A-Za-z0-9_.:\-]{1,120}$")


def load_blanks(path: str, kind: str) -> list:
    """``[{todo_id, date_range:[from, to], kind_axis}]`` → [(todo_id, from, to, kind_axis)]. 다른 축의 항목은 뺀다."""
    if not os.path.isfile(path):
        raise BlanksError("missing")
    obj = fsx.read_json(path, None, want=None)
    if isinstance(obj, dict) and isinstance(obj.get("blanks"), list):
        obj = obj["blanks"]
    if not isinstance(obj, list):
        raise BlanksError("format")
    out = []
    for x in obj:
        if not isinstance(x, dict):
            continue
        axis = str(x.get("kind_axis") or "")
        if axis and axis not in KIND_AXES[kind]:
            continue
        dr = x.get("date_range")
        if not (isinstance(dr, list) and len(dr) == 2 and all(isinstance(s, str) and DATE_RX.match(s) for s in dr)):
            continue
        try:
            a, b = date.fromisoformat(dr[0]), date.fromisoformat(dr[1])
        except ValueError:
            continue
        if a > b:
            continue
        tid = str(x.get("todo_id") or "")
        out.append((tid if TODO_ID_RX.match(tid) else "", a, b, axis))
    return out


# ───────────────────────────── 수집 ─────────────────────────────
class Opts:
    def __init__(self, *, kind: str, pc: str, d0=None, d1=None, blanks_file: str = "", budget_sec: int = 0,
                 force: bool = False, run_id: str = ""):
        self.kind, self.pc = kind, pc
        self.d0, self.d1 = d0, d1
        self.blanks_file = blanks_file
        self.budget_sec = budget_sec
        self.force = force
        self.run_id = run_id


def _requested(run: WebRun, opts: Opts) -> tuple:
    """(요청 구간들, 빈칸 [(todo_id, from, to)]) — 빈칸 파일 · --from/--to · 기본 기간."""
    today = run.today
    lookback = int(run.cfg_get("collect.lookbackDays", 120) or 120)
    d0 = opts.d0 or (today - timedelta(days=lookback))
    d1 = opts.d1 or today
    blanks = []
    if opts.blanks_file:
        blanks = load_blanks(opts.blanks_file, opts.kind)
        run.c["blanks"] = len(blanks)
        req = [(a, b) for _t, a, b, _x in blanks]
        if opts.d0 or opts.d1:
            req = intersect_ranges(req, d0, d1)
    elif opts.kind == "mail":
        req = [(d0, d1)] if (opts.d0 and opts.d1) else []
    else:
        req = [(d0, d1)]
    if opts.kind == "mail":
        req = intersect_ranges(req, date(2000, 1, 1), today)     # 메일은 오늘까지만
    return merge_ranges(req), [(t, a, b) for t, a, b, _x in blanks]


def _done_past(done, today, kind) -> list:
    """다음 실행이 건너뛸 수 있는 읽은 구간 — 메일은 오늘 이전 날, 일정은 끝난 주(오늘 이전)만."""
    return intersect_ranges(done, date(2000, 1, 1), today - timedelta(days=1))


def collect(opts: Opts, *, paths, cfg, api, clock, now, off_fn, environ, session_factory=None, err=None,
            fake_cost_s: float = 0.0) -> dict:
    """경로 하나(mail.owa 또는 cal.owa) 수집 → 상태 dict(rc · reasons · counts)."""
    src = SRC_OF[opts.kind]
    owner = str(cfg_get(cfg, "collect.ownerAddress", "") or "").strip().lower()
    run = WebRun(kind=opts.kind, src=src, pc_id=opts.pc, paths=paths, cfg=cfg, api=api, clock=clock, now=now,
                 off_fn=off_fn, budget_sec=opts.budget_sec, my_addrs=(owner,) if "@" in owner else (), err=err)
    st, c = run.st, run.c
    try:
        req, blanks = _requested(run, opts)
    except BlanksError as e:
        c["blanks_error"] = str(e)
        add_reason(st, "R-TRANSPORT")
        st["rc"] = RC_DRIVER
        human(f"[OWA] {src}: 빈칸 파일을 읽지 못했습니다({e}) — 수집하지 않습니다", err)
        return st
    cur = run.load_cursor()
    done = ranges_from_json(cur.get("done_ranges"))
    todos_done = {str(x) for x in cur.get("assigned_todo_ids") or [] if isinstance(x, str) and TODO_ID_RX.match(x)}
    todo = req if opts.force else subtract_ranges(req, _done_past(done, run.today, opts.kind))
    c["ranges"] = len(req)
    c["days_requested"] = sum((b - a).days + 1 for a, b in req)
    c["days_todo"] = sum((b - a).days + 1 for a, b in todo)
    if not req:
        st["rc"] = RC_NONE
        human(f"[OWA] {src}: 읽을 빈칸 구간이 없습니다 — 대상 없음", err)
        return st
    if not todo:
        st["rc"] = RC_NONEW
        human(f"[OWA] {src}: 요청 구간을 이미 모두 읽었습니다 — 새로 읽을 것 없음", err)
        return st
    try:
        screen = make_owa_screen(environ, paths=paths, clock=clock, run_id=opts.run_id, counts=c,
                                 session_factory=session_factory, fake_cost_s=fake_cost_s)
    except FakeError as e:
        c["fake_error"] = str(e)
        add_reason(st, "R-TRANSPORT")
        st["rc"] = RC_DRIVER
        return st
    c["synthetic"] = bool(screen.synthetic)
    hb = None
    try:
        state = screen.open(run.dl)
        if state != "ready":
            rc, why = session_failure(state, getattr(getattr(screen, "s", None), "error", None))
            c["session"] = state
            add_reason(st, why)
            add_login_facts(st, screen)
            st["rc"] = rc
            human(f"[OWA] {src}: {'로그인이 필요합니다(전용 Edge 창에서 1회)' if rc == RC_LOGIN else 'Edge 세션을 쓸 수 없습니다'}"
                  f" — {state}", err)
            return st
        state_box = {"done": done, "todos": todos_done}
        if opts.kind == "mail":
            slices = month_slices(todo)
            hb = heartbeat(STAGE, total=len(slices))
            stop = _collect_mail(run, screen, slices, blanks, state_box, opts, hb)
        else:
            weeks = weeks_of(todo)
            hb = heartbeat(STAGE, total=len(weeks))
            stop = _collect_cal(run, screen, weeks, todo, blanks, state_box, opts, hb)
    except StoreError as e:
        c["store_error"] = f"{e.what}:{e.etype}"
        add_reason(st, "R-TRANSPORT")
        st["rc"] = RC_DRIVER
        run.finish_audit()                                 # 앞 조각에서 이미 저장한 행의 감사는 남긴다
        run.fill_counts()
        st["n"] = run.stored + sum(run.dropped.values())
        human(f"[OWA] {src}: 정제·저장 실패({e.etype}) — 커서를 그대로 두고 다음 실행에서 다시 읽습니다", err)
        return st
    finally:
        stop_heartbeat(hb)
        screen.close()
    run.finish_audit()
    run.fill_counts()
    n = run.stored + sum(run.dropped.values())
    st["n"] = n
    row_err = run.flag_row_errors()
    if stop is not None:                                   # 중간에 로그인 만료·탭 잃음
        rc, why = session_failure(stop.state, stop.info)
        c["session"] = stop.state
        add_reason(st, why)
        add_login_facts(st, screen)
        st["rc"] = rc
        st["partial"] = True
    elif c.get("sel_fail") and not c.get("sel_ok") and not c.get("items") and not c.get("events"):
        add_reason(st, "R-WEBSEL")                         # 화면 구조를 하나도 못 알아봄(선택자 전부 실패)
        st["rc"] = RC_DRIVER
    elif n > 0:
        st["rc"] = RC_SAVED
    elif row_err:                                          # 읽은 행이 전부 정제 오류 — 0건(rc 1 · zero_ok)으로 적지 않는다
        st["rc"] = RC_DRIVER
    else:
        st["rc"] = RC_NONE
    nd = sum(run.dropped.values())
    human(f"[OWA] {src}: 조각 {c.get('slices_done', 0)}/{c.get('slices', 0)} · 화면 항목 {c.get('items', c.get('events', 0))} · "
          f"저장 {run.stored} · 버림 {nd} · 날짜만 {c.get('date_only', 0)} · 열어 분 단위 {c.get('sent_opened', 0)}"
          + (" · 예산 소진(다음 실행이 이어 읽음)" if st["budget_hit"] else ""), err)
    return st


def cfg_get(cfg, key: str, default):
    try:
        v = cfg[key]
    except KeyError:
        return default
    return default if v is None else v


def _mark_done(run: WebRun, box: dict, a: date, b: date, blanks) -> None:
    """읽은 구간 반영 → 끝까지 읽은 todo → 커서 저장(그 조각 flush 성공 뒤)."""
    box["done"] = merge_ranges(box["done"] + [(a, b)])
    keep = _done_past(box["done"], run.today, run.kind)
    for tid, x, y in blanks:
        if tid and covered(keep, x, y):                    # 오늘·앞날이 든 todo 는 끝나지 않는다(다음 실행이 남은 날만)
            box["todos"].add(tid)
    run.save_cursor({"assigned_todo_ids": sorted(box["todos"])[-DONE_IDS_MAX:],
                     "done_ranges": ranges_json(keep)[-DONE_RANGES_MAX:]})


def _collect_mail(run: WebRun, screen, slices, blanks, box: dict, opts: Opts, hb):
    """달 조각 × (받은 편지함 → 보낸 편지함). 조각마다 정제·저장·커서. 중간에 화면이 끊기면 ScreenStop 을 돌려준다."""
    c = run.c
    c["slices"] = len(slices)
    today = run.today
    for i, (s, e) in enumerate(slices):
        if run.out_of_time():
            run.budget_cut()
            break
        rows, seen, complete, stop = [], set(), True, None
        known = dict.fromkeys(dict(MAIL_FOLDERS), False)   # 폴더마다 화면을 알아봤나 — 못 알아본 조각은 '읽음'이 아니다
        try:
            for folder, _path in MAIL_FOLDERS:
                for page in screen.mail_pages(folder, s, e, run.dl):
                    run.bump("pages")
                    if page.get("how") or page.get("listboxes") or page.get("search"):
                        run.bump("sel_ok")
                        known[folder] = True
                    else:
                        run.bump("sel_fail")
                    for it in page.get("items") or []:
                        if not isinstance(it, dict):
                            continue
                        key = str(it.get("key") or "") or sha16(it)
                        if key in seen:
                            run.bump("dup")
                            continue
                        seen.add(key)
                        run.bump("items")
                        r = parse_mail_item(it, s, e, folder, today)
                        if r is None:
                            run.bump("unparsed")
                            continue
                        if r.get("skip"):
                            run.bump("skipped_folder")
                            continue
                        if not s <= r["date"] <= e:
                            run.bump("out_of_range")
                            continue
                        if r["box"] == "sent" and r["hm"] is None and screen.can_open:
                            if run.out_of_time():
                                complete = False
                            else:
                                _open_sent(run, screen, it, r, s, e)
                        rows.append(r)
                if run.out_of_time():
                    complete = False
                    break
        except ScreenStop as x:
            stop, complete = x, False
        rows.sort(key=lambda r: (r["box"] != "sent", r["date"], r["hm"] or (12, 0)))   # 보낸 편지함 먼저(P §11.3)
        for r in rows:
            run.bump("minute" if r["hm"] else "date_only")
        run.commit([mail_raw(r, run) for r in rows])
        rows = None
        if stop is not None:
            return stop
        if complete and all(known.values()) and run.batch_errors:
            run.bump("slices_row_errors")                  # 정제 오류 행이 든 조각은 '읽음'으로 두지 않는다(다음 실행이 다시)
        elif complete and all(known.values()):
            _mark_done(run, box, s, e, blanks)
            run.bump("slices_done")
        if hb is not None:
            hb.update(done=i + 1)
        if not complete:
            run.budget_cut()
            break
    return None


def _open_sent(run: WebRun, screen, it: dict, r: dict, s: date, e: date) -> None:
    """보낸 편지함 항목을 열어 읽기 창 머리의 시각으로 분 단위를 채운다(D-14 · X-132). 같은 날짜일 때만 받는다."""
    head = screen.open_item(int(it.get("idx", 0) or 0), it, run.dl)
    w = parse_when(head or [], s, e, run.today) if head else None
    if w and w[1] and w[0] == r["date"]:
        r["hm"] = w[1]
        run.bump("sent_opened")
    else:
        run.bump("sent_open_fail")


def _collect_cal(run: WebRun, screen, weeks, todo, blanks, box: dict, opts: Opts, hb):
    """주 보기 × 주. 주마다 정제·저장·커서(끝난 주만 done)."""
    c = run.c
    c["slices"] = len(weeks)
    seen = set()
    for i, wk in enumerate(weeks):
        if run.out_of_time():
            run.budget_cut()
            break
        wk_end = wk + timedelta(days=6)
        try:
            pg = screen.week(wk, run.dl)
        except ScreenStop as x:
            return x
        run.bump("weeks")
        known = bool(pg.get("grid") or pg.get("n"))
        run.bump("sel_ok" if known else "sel_fail")
        rows = []
        part = intersect_ranges(todo, wk, wk_end)
        for ev in pg.get("events") or []:
            if not isinstance(ev, dict):
                continue
            run.bump("events")
            r = parse_event(ev, wk, wk_end, run.today)
            if r is None:
                run.bump("unparsed")
                continue
            sd, ed = r["start"].date(), r["end"].date()
            if not any(sd <= b and ed >= a for a, b in part):
                run.bump("out_of_range")
                continue
            k = (r["start"], r["end"], r["subject"])
            if k in seen:                                  # 여러 주에 걸친 막대는 주마다 같은 행으로 읽힌다 — 한 번만
                run.bump("dup")
                continue
            seen.add(k)
            if sd != ed:
                run.bump("multi_day")
            run.bump("date_only" if r["all_day"] else "minute")
            rows.append(r)
        run.commit([cal_raw(r, run) for r in rows])
        rows = None
        if hb is not None:
            hb.update(done=i + 1)
        if not known:                                      # 주 보기를 못 알아봤다 — 0건으로 '읽음' 처리하지 않는다
            continue
        if run.batch_errors:                               # 정제 오류 행이 든 주도 '읽음'으로 두지 않는다(다음 실행이 다시)
            run.bump("slices_row_errors")
            continue
        for a, b in part:
            if b < run.today:
                _mark_done(run, box, a, b, blanks)
        run.bump("slices_done")
    return None


# ───────────────────────────── 진입점 ─────────────────────────────
class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ArgError(message)


def build_parser() -> argparse.ArgumentParser:
    ap = _Parser(prog="Get-OutlookWeb.py", description="Outlook 웹 백필(mail.owa · cal.owa) → 정제 → 로컬 원장")
    ap.add_argument("--kind", required=True, choices=KINDS_HERE)
    ap.add_argument("--pc", required=True, help="pc_id")
    ap.add_argument("--from", dest="from_", default="", help="YYYY-MM-DD(로컬)")
    ap.add_argument("--to", default="", help="YYYY-MM-DD(로컬, 포함)")
    ap.add_argument("--blanks-file", default="", help="빈칸 파일(lm27.collect.todo 가 쓴 blanks_<src>.json)")
    ap.add_argument("--budget-sec", type=int, default=0, help="시간 예산(초, 0 = 없음)")
    ap.add_argument("--force", action="store_true", help="커서의 읽은 구간을 무시하고 다시 읽기")
    ap.add_argument("--run-id", default="", help="수집 실행 run_id(세션 잠금·건강 기록용, 없으면 새로)")
    ap.add_argument("--events", default="jsonl", choices=("jsonl", "text", "off"))
    return ap


def parse_opts(argv) -> tuple:
    """(Opts, events 모드). 인자 오류는 ArgError. --help 는 SystemExit(0)."""
    a = build_parser().parse_args(argv)
    if not PC_ID_RX.match(a.pc or ""):
        raise ArgError("pc_id 형식이 아닙니다")
    d0, d1 = parse_day(a.from_), parse_day(a.to)
    if d0 and d1 and d1 < d0:
        raise ArgError("--to 가 --from 보다 앞섭니다")
    if a.budget_sec < 0:
        raise ArgError("--budget-sec 는 0 이상")
    if a.run_id and not RUN_ID_RX.match(a.run_id):
        raise ArgError("run_id 형식이 아닙니다")
    return Opts(kind=a.kind, pc=a.pc, d0=d0, d1=d1, blanks_file=a.blanks_file, budget_sec=a.budget_sec,
                force=a.force, run_id=a.run_id or tz.new_run_id()), a.events


def run(argv=None, *, paths=None, cfg=None, api=None, now=None, clock=None, off_fn=None, session_factory=None,
        environ=None, err=None, fake_cost_s: float = 0.0) -> int:
    """한 번 실행 → 수집기 rc. 상태 줄은 err(stderr) 마지막 줄."""
    err = err if err is not None else sys.stderr
    environ = os.environ if environ is None else environ
    try:
        opts, ev_mode = parse_opts(argv)
    except SystemExit as e:
        if e.code in (0, None):
            return 0                                     # --help: 사용법만(수집이 아니므로 상태 줄 없음)
        raise
    except ArgError as e:
        st = new_status("mail.owa")
        st["counts"]["error"] = "BadArguments"
        add_reason(st, "R-TRANSPORT")
        human(f"[OWA] 인자 오류: {e}", err)
        status_line(st, err)
        return RC_DRIVER
    events.configure(ev_mode)
    t0 = (clock or default_clock()).mono()
    try:
        if paths is None:
            from lm27.paths import Paths
            paths = Paths(ROOT)
        if cfg is None:
            from lm27.config import load_config
            cfg = load_config(paths)
        st = collect(opts, paths=paths, cfg=cfg, api=api or store_api(), clock=clock or default_clock(),
                     now=now or datetime.now(UTC), off_fn=off_fn or default_off, environ=environ,
                     session_factory=session_factory, err=err, fake_cost_s=fake_cost_s)
    except Exception as e:                               # noqa: BLE001 — 내부 오류는 rc 3 + 수송 사유(유형만, 원문 없음)
        st = new_status(SRC_OF[opts.kind])
        st["counts"]["error"] = type(e).__name__
        add_reason(st, "R-TRANSPORT")
        human(f"[OWA] {SRC_OF[opts.kind]}: 내부 오류({type(e).__name__}) — 다음 실행에서 다시 시도합니다", err)
    st["elapsed_ms"] = int(((clock or default_clock()).mono() - t0) * 1000)
    status_line(st, err)
    return int(st.get("rc", RC_DRIVER))


def main() -> int:
    for s in (sys.stdout, sys.stderr):
        r = getattr(s, "reconfigure", None)
        if r is not None:
            r(encoding="utf-8", errors="replace")
    return run()


if __name__ == "__main__":
    sys.exit(main())
