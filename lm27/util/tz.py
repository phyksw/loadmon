# -*- coding: utf-8 -*-
r"""시간대 하위층 — 시간대 데이터베이스 모듈을 쓰지 않는다(동봉 파이썬에 tzdata 없음, L-04 · D-17).

계약 §2.1 · §9.1 · §9.4 · X-172 · CP §13.2:

- 저장은 UTC(`YYYY-MM-DDTHH:MM:SSZ`) + 관측 순간 오프셋 문자열(`+09:00`, 분 단위 정확). 적재기가 분으로 바꾼다.
- 수집 순간 오프셋 = Win32 ctypes 로 **그 UTC 순간의 규칙**(일광 절약 포함)대로 계산한다:
  `GetDynamicTimeZoneInformation` → `GetTimeZoneInformationForYear` → `SystemTimeToTzSpecificLocalTime`.
  사용자가 '일광 절약 시간 자동 조정'을 끈 PC(`DynamicDaylightTimeDisabled`)는 표준시만 쓴다.
  Win32 호출이 실패하면 C 런타임 `time.localtime` 의 `tm_gmtoff` 로 계산한다(같은 값의 다른 원천).
- 분석 근무 시간대는 설정 `time.tzOffsetMin` 하나다(이 모듈은 설정을 읽지 않는다).
- `run_id`·`job_id` 생성(CR-01): 로컬 시각 + 무작위 4hex(계약 §4.1, R §2.3.5).

이 파일은 에이전트 bin 사본(계약 §1.3)에 들어가므로 표준 라이브러리만 import 한다.
"""
from __future__ import annotations

import ctypes
import re
import secrets
import sys
import time
from datetime import UTC, datetime, timedelta, timezone

__all__ = [
    "OFFSET_LIMIT_MIN",
    "capture_offset_min",
    "fmt_offset",
    "new_job_id",
    "new_run_id",
    "parse_offset",
    "to_local",
]

OFFSET_LIMIT_MIN = 14 * 60          # 실재하는 오프셋 범위 UTC-12:00 ~ UTC+14:00 를 덮는 대칭 상한
_OFF_RE = re.compile(r"^([+-])(\d{2}):?(\d{2})$")
_TZ_ID_INVALID = 0xFFFFFFFF


# ───────────────────────────── Win32 구조체(ctypes 원시 형만 — wintypes 비의존) ─────────────────────────────
class _SYSTEMTIME(ctypes.Structure):
    _fields_ = [
        ("wYear", ctypes.c_ushort),
        ("wMonth", ctypes.c_ushort),
        ("wDayOfWeek", ctypes.c_ushort),
        ("wDay", ctypes.c_ushort),
        ("wHour", ctypes.c_ushort),
        ("wMinute", ctypes.c_ushort),
        ("wSecond", ctypes.c_ushort),
        ("wMilliseconds", ctypes.c_ushort),
    ]


_TZI_FIELDS = [
    ("Bias", ctypes.c_long),
    ("StandardName", ctypes.c_wchar * 32),
    ("StandardDate", _SYSTEMTIME),
    ("StandardBias", ctypes.c_long),
    ("DaylightName", ctypes.c_wchar * 32),
    ("DaylightDate", _SYSTEMTIME),
    ("DaylightBias", ctypes.c_long),
]


class _TZI(ctypes.Structure):          # TIME_ZONE_INFORMATION
    _fields_ = _TZI_FIELDS


class _DTZI(ctypes.Structure):         # DYNAMIC_TIME_ZONE_INFORMATION
    _fields_ = _TZI_FIELDS + [
        ("TimeZoneKeyName", ctypes.c_wchar * 128),
        ("DynamicDaylightTimeDisabled", ctypes.c_ubyte),
    ]


_K32 = None


def _k32():
    """kernel32 함수 원형을 한 번만 선언한다(이 모듈 전용 WinDLL 인스턴스)."""
    global _K32
    if _K32 is None:
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.GetDynamicTimeZoneInformation.argtypes = [ctypes.POINTER(_DTZI)]
        k.GetDynamicTimeZoneInformation.restype = ctypes.c_uint32
        k.GetTimeZoneInformationForYear.argtypes = [ctypes.c_ushort, ctypes.POINTER(_DTZI), ctypes.POINTER(_TZI)]
        k.GetTimeZoneInformationForYear.restype = ctypes.c_int
        k.SystemTimeToTzSpecificLocalTime.argtypes = [ctypes.POINTER(_TZI), ctypes.POINTER(_SYSTEMTIME),
                                                      ctypes.POINTER(_SYSTEMTIME)]
        k.SystemTimeToTzSpecificLocalTime.restype = ctypes.c_int
        _K32 = k
    return _K32


def _year_tzi(year: int) -> _TZI | None:
    """현재 PC 시간대의 그 해 규칙(TIME_ZONE_INFORMATION). 실패하면 None."""
    k = _k32()
    dtzi = _DTZI()
    if k.GetDynamicTimeZoneInformation(ctypes.byref(dtzi)) == _TZ_ID_INVALID:
        return None
    tzi = _TZI()
    if not k.GetTimeZoneInformationForYear(year, ctypes.byref(dtzi), ctypes.byref(tzi)):
        return None
    if dtzi.DynamicDaylightTimeDisabled:   # '일광 절약 시간 자동 조정' 꺼짐 → 시계는 표준시만 쓴다
        tzi.DaylightDate = _SYSTEMTIME()
        tzi.DaylightBias = 0
    return tzi


def _offset_with_tzi(utc: datetime, tzi: _TZI) -> int | None:
    """주어진 시간대 규칙으로 UTC 순간의 오프셋(분). Win32 변환이 실패하면 None."""
    u = _as_utc(utc)
    if not 1601 <= u.year <= 30827:
        return None
    st = _SYSTEMTIME(u.year, u.month, 0, u.day, u.hour, u.minute, u.second, u.microsecond // 1000)
    loc = _SYSTEMTIME()
    if not _k32().SystemTimeToTzSpecificLocalTime(ctypes.byref(tzi), ctypes.byref(st), ctypes.byref(loc)):
        return None
    local = datetime(loc.wYear, loc.wMonth, loc.wDay, loc.wHour, loc.wMinute, loc.wSecond,
                     loc.wMilliseconds * 1000)
    base = u.replace(tzinfo=None, microsecond=(u.microsecond // 1000) * 1000)
    return round((local - base).total_seconds() / 60)


def _offset_win(utc: datetime) -> int | None:
    """현재 PC 시간대(동적 규칙)로 그 UTC 순간의 오프셋(분). Win32 가 아니거나 실패하면 None."""
    if sys.platform != "win32":
        return None
    u = _as_utc(utc)
    tzi = _year_tzi(u.year)
    if tzi is None:
        return None
    return _offset_with_tzi(u, tzi)


def _offset_crt(utc: datetime) -> int:
    """C 런타임 기준 오프셋(분) — Win32 경로가 없을 때의 대체 원천."""
    lt = time.localtime(_as_utc(utc).timestamp())
    return int(lt.tm_gmtoff) // 60


# ───────────────────────────── 공개 함수 ─────────────────────────────
def capture_offset_min(utc_dt: datetime | str | None = None) -> int:
    """수집 순간(UTC)의 이 PC 시간대 오프셋(분). 예 KST → 540.

    `utc_dt` 는 aware datetime(어느 시간대든 UTC 로 바꿔 쓴다)·naive datetime(UTC 로 본다)·ISO 문자열.
    None 이면 지금(`datetime.now(UTC)`).
    """
    u = datetime.now(UTC) if utc_dt is None else _as_utc(utc_dt)
    off = _offset_win(u)
    if off is None:
        off = _offset_crt(u)
    return off


def fmt_offset(off_min: int) -> str:
    """분 → `+09:00` · `-05:30` · `+00:00`(계약 §9.4 `ts_local_offset`)."""
    m = _check_off(off_min)
    sign = "-" if m < 0 else "+"
    h, mm = divmod(abs(m), 60)
    return f"{sign}{h:02d}:{mm:02d}"


def parse_offset(s: str) -> int:
    """`+09:00` · `-05:30` · `+0900` · `Z` → 분. 그 밖 형식·범위 밖은 ValueError."""
    if not isinstance(s, str):
        raise TypeError(f"오프셋은 문자열이어야 한다: {type(s).__name__}")
    t = s.strip()
    if t == "Z":
        return 0
    m = _OFF_RE.match(t)
    if not m:
        raise ValueError(f"오프셋 형식 오류 {s!r} — '+HH:MM' 이어야 한다")
    hh, mi = int(m.group(2)), int(m.group(3))
    if mi >= 60:
        raise ValueError(f"오프셋 분이 60 이상 {s!r}")
    v = hh * 60 + mi
    v = -v if m.group(1) == "-" else v
    if abs(v) > OFFSET_LIMIT_MIN:
        raise ValueError(f"오프셋 범위 밖 {s!r}(±14:00 까지)")
    return v


def to_local(ts_utc: datetime | str, off_min: int | str) -> datetime:
    """UTC 시각 + 오프셋(분 또는 `+09:00`) → 그 오프셋의 aware datetime(벽시계 = 로컬 시각).

    `ts_utc` 는 저장 형식 `YYYY-MM-DDTHH:MM:SSZ`·ISO 문자열·datetime(naive 는 UTC 로 본다).
    """
    off = parse_offset(off_min) if isinstance(off_min, str) else _check_off(off_min)
    return _as_utc(ts_utc).astimezone(timezone(timedelta(minutes=off)))


def new_run_id(now_utc: datetime | str | None = None) -> str:
    """`YYYYMMDD-HHMMSS-xxxx`(로컬 시각 + 무작위 4hex, 계약 §4.1). collect·analyze·bridge 공통."""
    return _local_naive(now_utc).strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(2)


def new_job_id(now_utc: datetime | str | None = None) -> str:
    """`j` + `YYYYMMDDHHMMSS`(로컬 시각) + 무작위 4hex(계약 §4.1, R §2.3.5)."""
    return "j" + _local_naive(now_utc).strftime("%Y%m%d%H%M%S") + secrets.token_hex(2)


# ───────────────────────────── 내부 ─────────────────────────────
def _as_utc(x: datetime | str) -> datetime:
    if isinstance(x, datetime):
        dt = x
    elif isinstance(x, str):
        try:
            dt = datetime.fromisoformat(x.strip())
        except ValueError as e:
            raise ValueError(f"UTC 시각 형식 오류 {x[:40]!r}") from e
    else:
        raise TypeError(f"시각은 datetime 또는 ISO 문자열이어야 한다: {type(x).__name__}")
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _check_off(off_min: int) -> int:
    if isinstance(off_min, bool) or not isinstance(off_min, int):
        raise TypeError(f"오프셋(분)은 정수여야 한다: {type(off_min).__name__}")
    if abs(off_min) > OFFSET_LIMIT_MIN:
        raise ValueError(f"오프셋 범위 밖 {off_min}분(±{OFFSET_LIMIT_MIN}분 까지)")
    return off_min


def _local_naive(now_utc: datetime | str | None) -> datetime:
    u = datetime.now(UTC) if now_utc is None else _as_utc(now_utc)
    return (u + timedelta(minutes=capture_offset_min(u))).replace(tzinfo=None)
