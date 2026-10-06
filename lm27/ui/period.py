# -*- coding: utf-8 -*-
r"""분석 기간 기본값과 빠른 선택(올해·1~4분기·상반기·하반기) — 화면 API·CLI 가 함께 쓰는 단일원.

사용자 결정(2026-10-06 — LM24 와 같은 기본): "기간 설정은 할 수 있되, 2026-01-01 ~ 오늘 날짜로 일단 디폴트로 설정하고,
필요시 1분기, 2분기, 3분기, 4분기, 상반기, 하반기로 설정할 수 있게".

    presets(today)            → 빠른 선택 7개 [{key, label, from, to, disabled, partial, tip}] (PRESETS 순서)
    default_range(today)      → 기본 기간 (from, to) = 올해 1월 1일 ~ 오늘
    preset_range(key, today)  → 그 빠른 선택의 (from, to) — 모르는 키·아직 오지 않은 기간이면 None
    key_of(from_, to, today)  → (from, to) 와 같은 빠른 선택 키(없으면 None = 직접 지정)
    period_source(key)        → analyze --period-source 값('ytd' → 'default', 분기·반기 → 그 키, 없음 → 'user')
    range_for_source(src, today) → 날짜 없이 기간 출처만 받았을 때의 (from, to)(API·CLI) — 쓸 수 없으면 None
    today_local(off_min, now) → 근무 시간대(설정 time.tzOffsetMin) 벽시계의 오늘

규칙
  · 기본(``ytd``, 올해) = 오늘이 속한 해의 1월 1일 ~ 오늘.
  · 1분기 01-01~03-31 · 2분기 04-01~06-30 · 3분기 07-01~09-30 · 4분기 10-01~12-31 · 상반기 01-01~06-30 · 하반기 07-01~12-31
    (모두 오늘이 속한 해). 오늘이 들어 있는(진행 중인) 기간은 끝을 오늘로 줄인다(``partial``). 아직 시작하지 않은 기간은
    고를 수 없다(``disabled`` + 이유 ``tip``). 분기 끝 날짜는 윤년과 무관하다(2월 29일은 1분기 안의 하루일 뿐).
  · 같은 규칙의 JS 판 = ``web\common\lm27ui.js`` 의 ``periodPresets``·``defaultPeriod``·``periodKeyOf``·``periodSource``.
    교차 시험(tests\web\common_test.js — 동봉 파이썬과 날짜 수백 개 대조 · 골든 tests\fixtures\wp35\period_cases.json)이
    두 판의 결과가 글자 단위로 같은지 본다. 문구(tip)를 바꾸면 두 판을 함께 바꾼다.
날짜는 'YYYY-MM-DD' 글자로 다룬다(ISO 날짜는 글자 비교 = 날짜 비교). 표준 라이브러리만 쓰고 디스크·설정을 읽지 않는다.
"""
from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta, timezone

__all__ = ["DEFAULT_KEY", "PERIOD_SOURCES", "PRESETS", "default_range", "key_of", "period_source", "preset_range",
           "presets", "range_for_source", "today_local"]

PRESETS = (("ytd", "올해"), ("q1", "1분기"), ("q2", "2분기"), ("q3", "3분기"), ("q4", "4분기"), ("h1", "상반기"),
           ("h2", "하반기"))
_SPAN = {"ytd": ("01-01", "12-31"), "q1": ("01-01", "03-31"), "q2": ("04-01", "06-30"), "q3": ("07-01", "09-30"),
         "q4": ("10-01", "12-31"), "h1": ("01-01", "06-30"), "h2": ("07-01", "12-31")}
DEFAULT_KEY = "ytd"
# analyze --period-source 값(R RP8 기간 출처 — 머리 띠 표시 근거). 'default' = 기본 기간(올해 1월 1일 ~ 오늘), 분기·반기 = 그 키,
# 손으로 고친 날짜 = 'user'. this_month·last_month·this_year 는 이전 화면이 보내던 값(명령줄 호환·옛 실행 표시로 받기만 한다).
# 'rerun' 은 파이프라인이 스스로 붙이므로 받지 않는다. lm27\cli.py 의 PERIOD_SOURCES 는 이 튜플의 사본이다(--help 가 이 모듈을
# import 하지 않게) — tests\ui\test_period.py 가 둘이 같은지 본다.
PERIOD_SOURCES = ("default", "this_month", "last_month", "this_year", "q1", "q2", "q3", "q4", "h1", "h2", "user")
_DATE_RX = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")       # fullmatch — JS 판 /^\d{4}-\d{2}-\d{2}$/ 와 같은 글자 집합


def _iso(today) -> str:
    """오늘(date · datetime · 'YYYY-MM-DD') → 'YYYY-MM-DD'. 없는 날짜(2026-02-30)·다른 형이면 ValueError."""
    if isinstance(today, datetime):
        return today.date().isoformat()
    if isinstance(today, date):
        return today.isoformat()
    if isinstance(today, str) and _DATE_RX.fullmatch(today):
        return date.fromisoformat(today).isoformat()
    raise ValueError("오늘 날짜는 YYYY-MM-DD 입니다")


def presets(today) -> list[dict]:
    """빠른 선택 7개(PRESETS 순서). 고를 수 없는(아직 오지 않은) 기간은 from·to 에 그 기간 전체를 둔다(표시용)."""
    t = _iso(today)
    y = t[:4]
    out = []
    for key, label in PRESETS:
        a = y + "-" + _SPAN[key][0]
        b = y + "-" + _SPAN[key][1]
        if a > t:
            out.append({"key": key, "label": label, "from": a, "to": b, "disabled": True, "partial": False,
                        "tip": a + " ~ " + b + " — 아직 오지 않은 기간이라 고를 수 없습니다"})
        elif b >= t:
            out.append({"key": key, "label": label, "from": a, "to": t, "disabled": False, "partial": True,
                        "tip": a + " ~ " + t + "(진행 중 — 끝은 오늘)"})
        else:
            out.append({"key": key, "label": label, "from": a, "to": b, "disabled": False, "partial": False,
                        "tip": a + " ~ " + b})
    return out


def preset_range(key, today) -> tuple[str, str] | None:
    """그 빠른 선택의 (from, to). 모르는 키이거나 아직 오지 않은 기간이면 None."""
    for p in presets(today):
        if p["key"] == key:
            return None if p["disabled"] else (p["from"], p["to"])
    return None


def default_range(today) -> tuple[str, str]:
    """기본 기간 = 올해 1월 1일 ~ 오늘(늘 고를 수 있다)."""
    return preset_range(DEFAULT_KEY, today)


def key_of(from_, to, today) -> str | None:
    """(from, to) 가 고를 수 있는 빠른 선택과 같으면 그 키. 여럿이 같으면 PRESETS 순서로 첫 번째
    (1분기 안에서는 올해·1분기·상반기가 같은 기간이라 '올해'). 아니면 None(직접 지정)."""
    for p in presets(today):
        if not p["disabled"] and p["from"] == from_ and p["to"] == to:
            return p["key"]
    return None


def range_for_source(source, today) -> tuple[str, str] | None:
    """날짜 없이 기간 출처만 받았을 때의 기간(API·CLI): 없음·'default' → 기본(올해 1월 1일 ~ 오늘), 'q1'~'q4'·'h1'·'h2' → 그 빠른
    선택(아직 오지 않은 기간이면 None). 그 밖(this_month·last_month·this_year·user — 날짜와 함께만 쓰는 값)과 문자열이 아닌
    값(목록·객체 — API 본문)은 None."""
    if source is not None and not isinstance(source, str):
        return None
    if source in (None, "", "default"):
        return default_range(today)
    if source in _SPAN and source != DEFAULT_KEY:
        return preset_range(source, today)
    return None


def period_source(key) -> str:
    """빠른 선택 키 → analyze --period-source 값: 'ytd' → 'default', 분기·반기 → 그 키, 그 밖(직접 지정) → 'user'."""
    if key == DEFAULT_KEY:
        return "default"
    return key if key in _SPAN else "user"


def today_local(off_min, now: datetime | None = None) -> date:
    """근무 시간대(분 — 설정 ``time.tzOffsetMin``) 벽시계의 오늘. ``now`` 는 aware datetime(naive 는 UTC 로 본다, 없으면 지금)."""
    t = now if now is not None else datetime.now(UTC)
    if t.tzinfo is None:
        t = t.replace(tzinfo=UTC)
    return t.astimezone(timezone(timedelta(minutes=int(off_min)))).date()
