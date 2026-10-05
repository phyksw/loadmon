# -*- coding: utf-8 -*-
r"""번들 쓰기 잠금(계약 §2.6, TAB §1.9) — ``BundleLock(paths, purpose, timeout_s)`` · ``BundleBusy``.

번들(``data\``)에 쓰는 주체는 전경 프로세스(화면 서버·bat·CLI)뿐이며, 쓸 때마다 이 잠금을 쥔다. 읽기(분석·화면)는
잠금 없이 한다(세그먼트는 불변, manifest 는 원자 교체).

  · 잠금 = ``data\.bundle.lock`` 의 **0번 바이트**를 ``msvcrt.locking(LK_NBLCK, 1)`` 로 잠근다. OS 잠금이라 잡은
    프로세스가 죽으면 자동으로 풀린다(실측 — 낡은 잠금 파일 문제 없음). 잠금에는 읽기 전용 핸들로 충분하다(LockFile 은
    읽기 권한 핸들도 받는다) — 그래서 이 모듈은 쓰기 모드로 파일을 열지 않는다(L-07).
  · 표시용 내용: 잠금을 얻을 때마다 ``{"pid", "purpose", "at"}`` 한 줄을 ``fsx.append_line`` 으로 **파일 끝에** 덧붙인다
    (0번 바이트는 잠금 전용 — 잠근 바이트를 건드리면 다른 프로세스의 읽기가 막힌다). 기다리다 시간이 다 되면
    ``BundleBusy`` 가 1번 바이트 이후의 마지막 줄(누가·무엇 때문에·언제)을 담는다. 파일이 ``COMPACT_BYTES`` 를 넘으면
    아무도 쥐지 않은 순간에 한 줄짜리로 다시 만든다.
  · 대기: ``POLL_S``(0.25초) 간격으로 ``timeout_s``(기본 ``bundle.lockTimeoutSec`` = 30초)까지.
  · 같은 프로세스·같은 스레드 안에서 다시 잡으면(중첩 ``with``) 횟수만 늘린다 — 같은 프로세스의 두 번째 핸들은
    자기 잠금에 막히므로 그대로 두면 스스로 교착한다. 다른 스레드는 일반 대기와 같이 기다린다.

purpose 어휘: ``collect-init`` ``export`` ``fg-write`` ``collect-finish`` ``team_build`` ``move`` ``merge`` ``redact``.
"""
import json
import os
import re
import threading
import time

from lm27.util import fsx

PURPOSES = ("collect-init", "export", "fg-write", "collect-finish", "team_build", "move", "merge", "redact")
DEFAULT_TIMEOUT_S = 30           # bundle.lockTimeoutSec 의 선언 기본값(설정을 못 읽을 때만)
POLL_S = 0.25
COMPACT_BYTES = 1 << 20          # 표시용 줄이 쌓여 1MiB 를 넘으면 다시 만든다
_TAIL_BYTES = 4096
_PURPOSE_RX = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")

_sleep = time.sleep              # 시험 주입점
_monotonic = time.monotonic

_held_guard = threading.Lock()
_held = {}                       # 정규화 경로 → [소유 스레드 id, 횟수, 파일 객체]


class BundleBusy(Exception):
    """잠금을 ``timeout_s`` 안에 얻지 못함. ``holder`` = 잠금 파일에 남은 마지막 표시 줄(dict 또는 None)."""

    def __init__(self, purpose, timeout_s, holder=None):
        self.purpose = purpose
        self.timeout_s = timeout_s
        self.holder = holder if isinstance(holder, dict) else None
        who = ""
        if self.holder:
            who = f" — 사용 중: pid {self.holder.get('pid')} · {self.holder.get('purpose')} · {self.holder.get('at')}"
        super().__init__(f"번들이 다른 작업에 잠겨 있습니다({timeout_s}초 대기){who}")


def lock_timeout(cfg=None) -> int:
    """설정 ``bundle.lockTimeoutSec``(cfg 가 없으면 선언 기본값 30)."""
    if cfg is None:
        return DEFAULT_TIMEOUT_S
    return int(cfg["bundle.lockTimeoutSec"])


def read_holder(lock_path):
    """잠금 파일 1번 바이트 이후의 마지막 표시 줄 → dict(없거나 깨졌으면 None). 잠긴 0번 바이트는 읽지 않는다."""
    lp = fsx.longp(lock_path)
    try:
        size = os.path.getsize(lp)
        if size <= 1:
            return None
        with open(lp, "rb") as fh:
            fh.seek(max(1, size - _TAIL_BYTES))
            tail = fh.read()
    except OSError:
        return None
    for line in reversed(tail.split(b"\n")):
        line = line.strip(b"\x00 \r")
        if not line:
            continue
        try:
            obj = fsx.loads_strict(line)
        except ValueError:
            return None
        return obj if isinstance(obj, dict) else None
    return None


def _ensure_lock_file(lp: str) -> None:
    """잠금 파일이 없으면 0번 바이트 하나로 만든다. 다른 프로세스가 동시에 만들었으면 그것을 쓴다."""
    if os.path.isfile(lp):
        return
    try:
        fsx.atomic_write(lp, b"\x00", fsync=False)
    except PermissionError:
        if not os.path.isfile(lp):
            raise


def _maybe_compact(lp: str) -> None:
    """표시 줄이 너무 쌓였으면 아무도 쥐지 않은 지금 한 바이트짜리로 다시 만든다(실패하면 다음 기회에)."""
    try:
        if os.path.getsize(lp) <= COMPACT_BYTES:
            return
        fsx.atomic_write(lp, b"\x00", fsync=False)
    except OSError:
        pass


class BundleLock:
    r"""``with BundleLock(paths, "export", 30): …`` — ``data\.bundle.lock`` 0번 바이트 잠금.

    ``timeout_s`` 가 None 이면 ``cfg`` 의 ``bundle.lockTimeoutSec``(cfg 도 없으면 30초).
    ``acquire()``/``release()`` 로 직접 써도 된다. 얻지 못하면 ``BundleBusy``."""

    def __init__(self, paths, purpose, timeout_s=None, *, cfg=None):
        if not isinstance(purpose, str) or not _PURPOSE_RX.match(purpose):
            raise ValueError("BundleLock: purpose 형식이 아닙니다")
        self.paths = paths
        self.purpose = purpose
        self.timeout_s = float(lock_timeout(cfg) if timeout_s is None else timeout_s)
        if self.timeout_s < 0:
            raise ValueError("BundleLock: timeout_s 는 0 이상")
        self.path = os.path.abspath(os.fspath(paths.bundle_lock()))
        self._key = os.path.normcase(self.path)
        self._mine = False

    # ── 잠금 ────────────────────────────────────────────────────────────
    def _try_once(self):
        """잠금 시도 1회 → 파일 객체(성공) 또는 None(다른 프로세스가 쥠)."""
        import msvcrt
        lp = fsx.longp(self.path)
        _ensure_lock_file(lp)
        fh = open(lp, "rb")
        try:
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            fh.close()
            return None
        return fh

    def _note(self) -> None:
        line = json.dumps({"pid": os.getpid(), "purpose": self.purpose, "at": fsx.utcnow_iso()},
                          ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        try:
            fsx.append_line(self.path, line)
        except OSError:
            pass                                    # 표시 줄은 진단용 — 못 써도 잠금은 유효하다

    def acquire(self):
        me = threading.get_ident()
        deadline = _monotonic() + self.timeout_s
        compacted = False
        while True:
            with _held_guard:
                ent = _held.get(self._key)
                if ent is not None and ent[0] == me:
                    ent[1] += 1
                    self._mine = True
                    return self
                if ent is None:
                    if not compacted:
                        compacted = True
                        _maybe_compact(fsx.longp(self.path))
                    fh = self._try_once()
                    if fh is not None:
                        _held[self._key] = [me, 1, fh]
                        self._mine = True
                        break
            if _monotonic() >= deadline:
                raise BundleBusy(self.purpose, self.timeout_s, read_holder(self.path))
            _sleep(POLL_S)
        self._note()
        return self

    def release(self) -> None:
        if not self._mine:
            return
        import msvcrt
        self._mine = False
        with _held_guard:
            ent = _held.get(self._key)
            if ent is None:
                return
            ent[1] -= 1
            if ent[1] > 0:
                return
            del _held[self._key]
            fh = ent[2]
        try:
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass                                    # 핸들을 닫으면 OS 가 어차피 푼다
        finally:
            fh.close()

    @property
    def held(self) -> bool:
        return self._mine

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *_exc):
        self.release()
        return False

    def __repr__(self):
        return f"BundleLock(purpose={self.purpose!r}, timeout_s={self.timeout_s}, held={self._mine})"


def is_held_here(paths) -> bool:
    """이 프로세스가 지금 번들 잠금을 쥐고 있는가(하위 함수가 '잠금 안에서만' 을 확인할 때)."""
    key = os.path.normcase(os.path.abspath(os.fspath(paths.bundle_lock())))
    with _held_guard:
        return key in _held
