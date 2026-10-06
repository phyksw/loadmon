# -*- coding: utf-8 -*-
r"""수집 증분 커서 ``raw_cursor.json``(계약 §2.3 · §3.10 · X-300 · X-301) — ``agent\store\<pc_id>\raw_cursor.json``.

``{"<경로 ID>": <그 수집기의 커서 값>}``. 원문·원 ID 를 키로 쓰지 않는다(커서 값의 모양은 수집기 소유 — 계약 §3.10 표).

  · 읽기: ``load_raw_cursor(paths, pc_id)`` — 연결자가 수집기에 ``_in.cursor`` 로 넘기고, PY 수집기는 직접 읽는다.
  · 쓰기: ``save_raw_cursor(paths, pc_id, src, value)`` — **그 src 키만** 바꾼다. 잠금 ``raw_cursor.json.lock``
    (msvcrt.locking, 기본 10초) 안에서 읽기 → 교체 → ``atomic_write``. 에이전트 수확(pc.*)과 전경 수집(mail.* 등)이
    동시에 써도 다른 src 커서를 잃지 않는다(X-301). 출력 기록 성공 뒤에만 부른다(성공 전 진전 금지 — 정제 파이프는
    종료 0·2 일 때만).

잠금 ``file_lock(path, timeout_s)``: 잠금 파일의 0번 바이트를 읽기 전용 핸들로 ``msvcrt.locking`` 한다(LockFile 은 읽기
권한 핸들도 받는다 — 이 모듈은 쓰기 모드로 파일을 열지 않는다, L-07). 잡은 프로세스가 죽으면 OS 가 푼다. 같은 프로세스의
다른 스레드는 경로별 스레드 잠금으로 줄을 세운다. 시간 안에 못 잡으면 ``LockTimeout``.
"""
from __future__ import annotations

import contextlib
import os
import re
import threading
import time

from lm27.util import fsx

__all__ = ["CURSOR_LOCK_TIMEOUT_S", "LockTimeout", "file_lock", "load_raw_cursor", "save_raw_cursor"]

CURSOR_LOCK_TIMEOUT_S = 10.0
POLL_S = 0.05
_SRC_RX = re.compile(r"^(?:(?:mail|cal|teams|pc)\.[a-z]{2,10}|manual)$")
_MAX_CURSOR_BYTES = 4 * 1024 * 1024

_guard = threading.Lock()
_thread_locks: dict = {}


class LockTimeout(TimeoutError):
    """잠금을 시간 안에 얻지 못함(메시지에는 파일 이름만)."""


def _tlock(key: str) -> threading.Lock:
    with _guard:
        lk = _thread_locks.get(key)
        if lk is None:
            lk = _thread_locks[key] = threading.Lock()
        return lk


@contextlib.contextmanager
def file_lock(path, timeout_s: float = CURSOR_LOCK_TIMEOUT_S):
    """잠금 파일(없으면 1바이트로 만든다)의 0번 바이트를 잡는다. with 블록이 끝나면 푼다."""
    import msvcrt
    a = os.path.abspath(os.fspath(path))
    lp = fsx.longp(a)
    key = os.path.normcase(a)
    deadline = time.monotonic() + max(0.0, float(timeout_s))
    tl = _tlock(key)
    if not tl.acquire(timeout=max(0.0, float(timeout_s))):
        raise LockTimeout(f"잠금 대기 시간 초과: {os.path.basename(a)}")
    fh = None
    try:
        while True:
            if not os.path.isfile(lp):
                try:
                    fsx.atomic_write(a, b"\x00", fsync=False)
                except PermissionError:
                    if not os.path.isfile(lp):
                        raise
            try:
                fh = open(lp, "rb")
            except FileNotFoundError:
                fh = None
            if fh is not None:
                try:
                    msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    fh.close()
                    fh = None
            if time.monotonic() >= deadline:
                raise LockTimeout(f"잠금 대기 시간 초과: {os.path.basename(a)}")
            time.sleep(POLL_S)
        yield
    finally:
        if fh is not None:
            try:
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass                                   # 핸들을 닫으면 OS 가 어차피 푼다
            finally:
                fh.close()
        tl.release()


def load_raw_cursor(paths, pc_id: str) -> dict:
    """``raw_cursor.json`` 전체(없거나 형식이 깨졌으면 빈 사전 — 깨짐은 fsx 가 stderr 경고 1줄)."""
    obj = fsx.read_json(paths.raw_cursor(pc_id), default={})
    return obj if isinstance(obj, dict) else {}


def save_raw_cursor(paths, pc_id: str, src: str, value, *, timeout_s: float = CURSOR_LOCK_TIMEOUT_S) -> None:
    """그 ``src`` 키만 ``value`` 로 바꾼다(잠금 안에서 읽기 → 교체 → 원자 쓰기 — X-301). value 는 JSON 값(정규 바이트로
    직렬화할 수 있어야 한다 — NaN 금지). 너무 크면(4MiB 초과) ValueError."""
    if not isinstance(src, str) or not _SRC_RX.match(src):
        raise ValueError("save_raw_cursor: 경로 ID 형식이 아닙니다")
    blob = fsx.canon_bytes(value)
    if len(blob) > _MAX_CURSOR_BYTES:
        raise ValueError("save_raw_cursor: 커서가 너무 큽니다")
    p = paths.raw_cursor(pc_id)
    with file_lock(paths.raw_cursor_lock(pc_id), timeout_s):
        cur = fsx.read_json(p, default={})
        if not isinstance(cur, dict):
            cur = {}
        cur[src] = fsx.loads_strict(blob)
        fsx.atomic_write(p, fsx.canon_bytes(cur) + b"\n")
