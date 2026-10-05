# -*- coding: utf-8 -*-
r"""브리지 시계(B §11.1, 관문 G-B1) — **브리지에서 ``time`` 모듈을 부르는 유일한 파일.**

브리지의 모든 모듈은 ``Clock`` 을 생성자 인자로 받는다. 그래서 480초 답 대기·900초 질의 예산·10분 로그인 대기도
시험에서는 ``VirtualClock`` 으로 밀리초 안에 돈다(잠들지 않고 시간만 민다).

    clk = VirtualClock()                 # mono()=0.0 에서 시작, now() = start_epoch + mono()
    dl = Deadline.after(clk, 900)        # 지금부터 900초 뒤 마감
    clk.sleep(30); dl.left()             # 870.0

기록용 시각(ISO + 오프셋)은 ``iso_now(clock)`` 으로 만든다 — 실제 시계는 그 순간의 PC 시간대
(``lm27.util.tz.capture_offset_min``), 가상 시계는 생성 때 준 고정 오프셋(기본 +09:00)을 쓴다(결정성).
"""
from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from typing import Protocol

INF = math.inf
VIRTUAL_START_EPOCH = 1_790_000_000.0      # 2026-09 무렵 — 가상 시계 벽시계의 시작값(B §11.1)
VIRTUAL_OFFSET_MIN = 9 * 60                # 가상 시계 기록용 시간대(+09:00 고정 — 시험 결정성)


class Clock(Protocol):
    """시계 프로토콜. ``mono`` = 단조 초, ``now`` = 벽시계 epoch 초(기록용), ``sleep`` = 기다리기."""

    def mono(self) -> float: ...

    def now(self) -> float: ...

    def sleep(self, s: float) -> None: ...


class RealClock:
    """실제 시계. ``time.monotonic``·``time.time``·``time.sleep`` 을 감싼다."""

    virtual = False

    def mono(self) -> float:
        return time.monotonic()

    def now(self) -> float:
        return time.time()

    def sleep(self, s: float) -> None:
        if s and s > 0:
            time.sleep(s)

    def offset_min(self) -> int:
        """지금 이 PC 의 UTC 오프셋(분) — 기록 시각 표기용."""
        from lm27.util.tz import capture_offset_min
        return capture_offset_min(datetime.now(UTC))

    def __repr__(self) -> str:
        return "RealClock()"


class VirtualClock:
    """가상 시계 — 잠들지 않고 시간만 민다. ``on_sleep`` 콜백은 시간이 민 뒤 불린다(가짜 페이지 동기화용)."""

    virtual = True

    def __init__(self, start_epoch: float = VIRTUAL_START_EPOCH, *, offset_min: int = VIRTUAL_OFFSET_MIN):
        self.t = 0.0
        self.base = float(start_epoch)
        self._off = int(offset_min)
        self.slept = 0.0                   # 누계 sleep 초(시험 단언용)
        self.sleeps = 0                    # sleep 호출 수
        self.on_sleep = None
        self._lk = threading.Lock()

    def mono(self) -> float:
        return self.t

    def now(self) -> float:
        return self.base + self.t

    def sleep(self, s: float) -> None:
        s = max(0.0, float(s or 0.0))
        with self._lk:
            self.t += s
            self.slept += s
            self.sleeps += 1
        cb = self.on_sleep
        if cb is not None:
            cb(self.t)

    def advance(self, s: float) -> None:
        """sleep 과 같되 호출 수를 세지 않는다(시험이 시간을 직접 밀 때)."""
        with self._lk:
            self.t += max(0.0, float(s or 0.0))

    def offset_min(self) -> int:
        return self._off

    def __repr__(self) -> str:
        return f"VirtualClock(t={self.t:.1f})"


@dataclass
class Deadline:
    """``clock.mono()`` 기준 절대 마감. ``at`` 이 무한이면 마감 없음."""

    clock: Clock
    at: float

    @classmethod
    def after(cls, clock: Clock, sec: float | None) -> Deadline:
        """지금부터 sec 초 뒤. sec 가 None·무한이면 마감 없음, 0 이하면 지금(곧바로 만료)."""
        if sec is None or sec == INF:
            return cls(clock, INF)
        return cls(clock, clock.mono() + max(0.0, float(sec)))

    def left(self) -> float:
        return max(0.0, self.at - self.clock.mono())

    def expired(self) -> bool:
        return self.left() <= 0.0

    def cap(self, sec: float) -> float:
        """sec 와 남은 시간 중 작은 값(대기 상한을 마감 안으로 자른다)."""
        return max(0.0, min(float(sec), self.left()))

    def earlier(self, other_at: float) -> Deadline:
        """두 마감 중 이른 쪽."""
        return Deadline(self.clock, min(self.at, other_at))

    def sub(self, sec: float) -> Deadline:
        """지금부터 sec 초 뒤와 이 마감 중 이른 쪽(하위 대기용)."""
        return Deadline(self.clock, min(self.at, self.clock.mono() + max(0.0, float(sec))))


_DEFAULT: list = []


def default_clock() -> RealClock:
    """프로세스 공용 실제 시계."""
    if not _DEFAULT:
        _DEFAULT.append(RealClock())
    return _DEFAULT[0]


def _offset(clock) -> int:
    fn = getattr(clock, "offset_min", None)
    if fn is None:
        return VIRTUAL_OFFSET_MIN
    try:
        return int(fn())
    except (OSError, ValueError):
        return 0


def iso_now(clock: Clock) -> str:
    """기록용 시각 ``YYYY-MM-DDTHH:MM:SS+09:00``(초 단위, 사람에게 보이는 시각 형식 — 계약 §9.4)."""
    off = _offset(clock)
    tzinfo = timezone(timedelta(minutes=off))
    return datetime.fromtimestamp(int(clock.now()), tz=tzinfo).isoformat()


def today(clock: Clock) -> str:
    """기록용 로컬 날짜 ``YYYY-MM-DD``(iso_now 와 같은 시간대)."""
    return iso_now(clock)[:10]


def stamp(clock: Clock) -> str:
    """파일 이름 스탬프 ``YYYYMMDDTHHMMZ``(계약 §9.4)."""
    return datetime.fromtimestamp(int(clock.now()), tz=UTC).strftime("%Y%m%dT%H%MZ")


def iso_to_epoch(s: str) -> float | None:
    """ISO 시각(오프셋 포함·'Z' 허용) → epoch 초. 형식이 아니면 None."""
    if not isinstance(s, str) or not s:
        return None
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        d = datetime.fromisoformat(t)
    except ValueError:
        return None
    if d.tzinfo is None:
        return None
    return d.timestamp()
