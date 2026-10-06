# -*- coding: utf-8 -*-
r"""근태 대응 — 일정의 부재 힌트·플래그 → 회의 범주·부재일(계약 §2.7 · X-204 · X-218 · P §12.7 R-P8 · W §2.2).

    meet_category(row) -> str                     "offsite" · "edu" · "trip" · "leave" · ""(W §2.2 Meet.category)
    leaves(rows, cal, *, off_min=None) -> {date: "full" | "am" | "pm"}     W §2.5 build_days 의 leaves 입력

근거 열은 정제기가 비우기 **전에** 메모리에서 뽑은 ``abs_hint``(P §12.7 — 사적 일정도 남는다, R-P8)가 1순위이고, 정제된
제목(``subject_masked``)·``busy``·``location_class``·``flags`` 가 2순위다. 원문은 없다.

``meet_category`` 규칙(우선순위 순):

1. ``abs_hint`` ∈ {leave, sick, half, half_am, half_pm, early, out}(연차·병가·반차·조퇴·외출) → ``leave``. 단 제목이 공지·안내형
   (안내·공지·현황·집계·캠페인·권장·촉진·신청 방법·사용 계획)이면 근태가 아니다 — '연차 사용 촉진 안내' 가 하루를 지우지
   않게(놓치면 정상 근무로 남으므로 놓치는 쪽이 안전하다 — LM24 A5).
2. ``abs_hint = trip`` 또는 제목 '출장' → ``trip``.
3. 제목 교육·세미나·특강·강의·워크숍·설명회·연수·학회·컨퍼런스 → ``edu``.
4. 제목 외근·현장·방문·파견·전시회·박람회, ``busy = elsewhere``(근무지 외), ``location_class = external`` → ``offsite``.
5. 그 밖 ``""``.

``leaves`` 규칙(LM24 ``absence_days`` 이식 — 내 근태만):

- cal 행 중 ``meet_category = leave`` 만. ``*.copilot`` 증인(요약)은 쓰지 않는다.
- 내 근태가 아닌 것: 취소(``meeting_status`` 5·7) · 거절·미응답(``response`` 4·5) · 받은 초대(``meeting_status`` 3)인데 내가
  부재중(``busy=oof``)으로 두지 않은 것(동료가 팀에 공유한 '[연차] 김철수') · 한가함(``busy=free``)으로 둔 초대.
- 종일(``flags.all_day`` 또는 로컬 00:00 시작·23시간 이상): ``half_am`` → am, ``half_pm`` → pm, ``half`` → 제목의 오전/AM 이면
  am, 아니면 pm, 그 밖 full. 첫날 = 시작이 자정이 되는 오프셋(``off_min`` → 그 행의 수집 오프셋 순 — UTC 클라우드PC 가 본
  종일 일정도 하루로)의 날짜, 날 수 = 길이 ÷ 24시간(반올림, 최소 1, 62일 상한).
- 시간제: 부재중(oof)이면 반차 힌트이거나 5시간 이하 → 반차(am·pm), 그 밖 full. 그 밖 상태는 6시간 이상 full, 3시간 이상
  반차, 더 짧으면 근태로 보지 않는다. 반차의 오전/오후 = 힌트, 없으면 구간 가운데 시각이 12:30 이전이면 am.
- 날짜·시각 = ``off_min``(사람 근무 시간대 분, 없으면 그 행의 수집 오프셋). ``cal``(``lm27.time.calendar.Calendar``)을 주면
  휴일(주말·공휴일·회사 휴무)은 뺀다(달력에 없는 해의 날짜는 그대로 둔다). 같은 날 am + pm = full, full 이 이긴다.

수동 '부재' 응답(``manual`` · ``man_kind = absence``)은 여기서 다루지 않는다 — 시간 코어 ``build_days`` 가 확인된 부재로
따로 읽는다(이중 계상 방지). 표준 라이브러리만 쓴다. 파일을 읽거나 쓰지 않는다.
"""
from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping
from datetime import UTC, date, datetime, timedelta

__all__ = ["LEAVE_CODES", "LEAVE_HINTS", "MEET_CATEGORIES", "leaves", "meet_category"]

MEET_CATEGORIES = ("offsite", "edu", "trip", "leave", "")
LEAVE_CODES = ("full", "am", "pm")
LEAVE_HINTS = frozenset({"leave", "sick", "half", "half_am", "half_pm", "early", "out"})
HALF_HINTS = frozenset({"half", "half_am", "half_pm"})
MAX_DAYS = 62
_COPILOT = frozenset({"mail.copilot", "cal.copilot", "teams.copilot"})
_GUARD_RX = re.compile(r"안내|공지|현황|집계|캠페인|권장|촉진|신청\s*방법|사용\s*계획|설명회|교육")
_TRIP_RX = re.compile(r"출장|business\s*trip", re.I)
_EDU_RX = re.compile(r"교육|세미나|특강|강의|워크숍|워크샵|설명회|연수|학회|컨퍼런스|webinar|workshop|training|seminar|"
                     r"conference", re.I)
_OFFSITE_RX = re.compile(r"외근|현장|방문|파견|전시회|박람회|offsite|off-site|on-site|onsite|site\s*visit", re.I)
_AM_RX = re.compile(r"오전|(?<![a-z])am(?![a-z])", re.I)
_PM_RX = re.compile(r"오후|(?<![a-z])pm(?![a-z])", re.I)
_TOKEN_RX = re.compile(r"\[[^\[\]]{1,60}\]")


def _flags(row: Mapping) -> Mapping:
    f = row.get("flags")
    return f if isinstance(f, Mapping) else {}


def _subject(row: Mapping) -> str:
    s = row.get("subject_masked")
    if not isinstance(s, str) or not s:
        return ""
    return unicodedata.normalize("NFKC", _TOKEN_RX.sub(" ", s))


def _int(v) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def meet_category(row: Mapping) -> str:
    """일정 행 하나 → 근태 범주(W §2.2 · X-204). 일정이 아니거나 근거가 없으면 ""."""
    if not isinstance(row, Mapping) or row.get("kind") != "cal":
        return ""
    hint = row.get("abs_hint")
    subj = _subject(row)
    if hint in LEAVE_HINTS and not _GUARD_RX.search(subj):
        return "leave"
    if hint == "trip" or _TRIP_RX.search(subj):
        return "trip"
    if _EDU_RX.search(subj):
        return "edu"
    if _OFFSITE_RX.search(subj) or row.get("busy") == "elsewhere" or row.get("location_class") == "external":
        return "offsite"
    return ""


# ───────────────────────────── 부재일 ─────────────────────────────
def _utc(ts) -> datetime | None:
    if not isinstance(ts, str) or len(ts) < 16:
        return None
    try:
        return datetime.strptime(ts[:19] if len(ts) >= 19 else ts[:16],
                                 "%Y-%m-%dT%H:%M:%S" if len(ts) >= 19 else "%Y-%m-%dT%H:%M").replace(tzinfo=UTC)
    except ValueError:
        return None


def _row_off(row: Mapping) -> int:
    s = row.get("ts_local_offset")
    if isinstance(s, str) and len(s) == 6 and s[0] in "+-" and s[3] == ":":
        try:
            v = int(s[1:3]) * 60 + int(s[4:6])
            return -v if s[0] == "-" else v
        except ValueError:
            return 0
    return 0


def _mine(row: Mapping) -> bool:
    """내 근태 일정인가(LM24 `_absence_skip` 의 반대 — 취소·거절·미응답·남이 보낸 공유 초대·한가함 초대는 아니다)."""
    fl = _flags(row)
    ms, resp = _int(fl.get("meeting_status")), _int(fl.get("response"))
    busy = row.get("busy")
    if ms in (5, 7) or resp in (4, 5):
        return False
    if ms == 3 and busy != "oof":
        return False
    return not (busy == "free" and ms not in (None, 0))


def _half_side(hint, subj: str, a: datetime, b: datetime) -> str:
    if hint == "half_am":
        return "am"
    if hint == "half_pm":
        return "pm"
    if _AM_RX.search(subj) and not _PM_RX.search(subj):
        return "am"
    if _PM_RX.search(subj) and not _AM_RX.search(subj):
        return "pm"
    mid = a + (b - a) / 2
    return "am" if (mid.hour * 60 + mid.minute) < 12 * 60 + 30 else "pm"


def _midnight_offset(a: datetime, offs: list[int]) -> int | None:
    for off in offs:
        la = a + timedelta(minutes=off)
        if (la.hour, la.minute) == (0, 0):
            return off
    return None


def _codes(row: Mapping, off_min: int | None) -> list[tuple[date, str]]:
    a, b = _utc(row.get("ts_utc")), _utc(row.get("ts_end"))
    if a is None:
        return []
    if b is None or b < a:
        b = a
    own = _row_off(row)
    offs = [off_min, own] if off_min is not None else [own]
    hint = row.get("abs_hint")
    subj = _subject(row)
    dur_h = (b - a).total_seconds() / 3600
    mid = _midnight_offset(a, offs)
    all_day = bool(_flags(row).get("all_day")) or (mid is not None and dur_h >= 23)
    if all_day:
        # 종일 일정의 날짜는 '자정에 시작하는' 오프셋으로 본다(사람 시간대 → 수집 PC 오프셋 순) — UTC 클라우드PC 가 본
        # 종일 일정이 이틀로 갈라지지 않게. 날 수 = 길이(24시간 단위, 최소 1).
        off = mid if mid is not None else offs[0]
        if hint in HALF_HINTS:
            code = "am" if hint == "half_am" else "pm" if hint == "half_pm" else (
                "am" if (_AM_RX.search(subj) and not _PM_RX.search(subj)) else "pm")
        else:
            code = "full"
        first = (a + timedelta(minutes=off)).date()
        n = max(1, min(MAX_DAYS, round(dur_h / 24)))
        return [(first + timedelta(days=i), code) for i in range(n)]
    off = offs[0]
    la, lb = a + timedelta(minutes=off), b + timedelta(minutes=off)
    if dur_h >= 20:                                   # 시간제로 올린 여러 날 휴가 — 걸친 날 모두 종일
        out, d = [], la.date()
        while d <= lb.date() and len(out) < MAX_DAYS:
            out.append((d, "full"))
            d += timedelta(days=1)
        return out
    half = hint in HALF_HINTS
    if row.get("busy") == "oof":
        code = _half_side(hint, subj, la, lb) if (half or dur_h <= 5) else "full"
    elif dur_h >= 6:
        code = _half_side(hint, subj, la, lb) if half else "full"
    elif dur_h >= 3:
        code = _half_side(hint, subj, la, lb)
    else:
        return []
    return [(la.date(), code)]


def _holiday(cal, d: date) -> bool:
    if cal is None:
        return False
    years = getattr(cal, "years", None)
    if years is not None and d.year not in years:
        return False
    return bool(cal.is_holiday(d))


def leaves(rows: Iterable[Mapping], cal=None, *, off_min: int | None = None) -> dict[date, str]:
    """일정 행들 → 근태 부재일 {날짜: full|am|pm}(날짜순). ``cal`` 이 있으면 휴일은 뺀다."""
    out: dict[date, str] = {}
    for r in rows:
        if not isinstance(r, Mapping) or r.get("kind") != "cal" or r.get("src") in _COPILOT:
            continue
        if r.get("ts_precision") not in ("exact", "minute", "date"):
            continue
        if meet_category(r) != "leave" or not _mine(r):
            continue
        for d, code in _codes(r, off_min):
            if _holiday(cal, d):
                continue
            cur = out.get(d)
            if cur is None:
                out[d] = code
            elif cur != code and "full" not in (cur, code):
                out[d] = "full"                       # 오전 반차 + 오후 반차 = 종일
            elif code == "full":
                out[d] = "full"
    return dict(sorted(out.items()))
