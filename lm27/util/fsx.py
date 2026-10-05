# -*- coding: utf-8 -*-
r"""쓰기 하위층 유일원 — 원자 쓰기·결정적 gzip·정규 JSON 바이트·긴 경로·엄격한 JSON 읽기(계약 §2.1·§9.3, TAB §0.3).

규칙(계약 §9.3):
  · 최종 파일 쓰기는 ``atomic_write`` 하나(임시 ``.part`` → flush+fsync → ``os.replace``).
    ``os.replace`` 가 PermissionError 면 0.1·0.2·0.4·0.8·1.6초 간격으로 재시도(누계 3.1초 — 다른 프로세스가
    대상 파일을 열어 둔 동안 교체가 WinError 5 로 실패한 실측, TAB §0.2). 끝내 실패하면 ``.part`` 를 지우고 예외를 올린다.
  · 덧붙이기는 증거면 ``lm27.store.SegmentWriter``, 로그·jsonl 이면 ``append_line``. 그 밖의 ``open(…, "w"|"a")`` 는
    이 파일(과 store\writer.py · bridge\fsio.py)에만 있다(L-07).
  · 파일은 열고·다 읽고·즉시 닫는다(핸들을 쥔 채 기다리면 상대의 원자 교체를 막는다).
  · 240자 이상 경로는 ``longp()`` 로 ``\\?\`` 접두. 확장 경로에서 ``os.makedirs`` 가 깨지므로 ``ensure_dir`` 이 한 단계씩 만든다.
  · JSON 은 ``canon_bytes``(ensure_ascii=False · sort_keys · 구분자 ``,`` ``:`` · NaN 금지)로 쓰고,
    ``read_json``(utf-8-sig 허용 · 중복 키 · NaN/Infinity/범위 밖 수 거부)으로 읽는다.

이 모듈은 에이전트 bin 사본(계약 §1.3)에도 들어가므로 표준 라이브러리만 쓴다.
"""
import gzip
import hashlib
import io
import json
import math
import os
import sys
import threading
import time
from datetime import UTC, datetime

MAXP = 240                                   # 이 길이 이상이면 확장 경로(\\?\) — LM24 teamup.longp 계승
RETRY_WAITS = (0.1, 0.2, 0.4, 0.8, 1.6)      # os.replace PermissionError 재시도 간격(초)
READ_RETRY = (0.1, 0.1, 0.1, 0.1, 0.1)       # 읽기 PermissionError 재시도(원자 교체 순간, TAB §1.9)
_EXT = "\\\\?\\"
_EXT_UNC = "\\\\?\\UNC\\"

_sleep = time.sleep                          # 시험 주입점: 재시도 간격 기록용으로 바꿔 끼운다


# ── 정규 JSON ──────────────────────────────────────────────────────────────
def canon_bytes(obj) -> bytes:
    """정규 JSON 바이트 — 같은 값이면 언제나 같은 바이트(미리보기 = 실전송 · sha 멱등의 기초).
    NaN·Infinity 는 ValueError(allow_nan=False)."""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def reject_dup_keys(pairs):
    """json object_pairs_hook — 같은 객체 안 중복 키는 ValueError("dup key")."""
    out = {}
    for k, v in pairs:
        if k in out:
            raise ValueError("dup key")
        out[k] = v
    return out


def reject_nan(token):
    """json parse_constant — ``NaN`` · ``Infinity`` · ``-Infinity`` 는 ValueError."""
    raise ValueError(f"non-finite constant {token}")


def _strict_float(s):
    v = float(s)
    if math.isinf(v) or math.isnan(v):
        raise ValueError("non-finite number")
    return v


def loads_strict(data):
    """bytes(utf-8, BOM 허용) 또는 str 을 엄격하게 파싱한다 — 중복 키·NaN·Infinity·범위 밖 수(1e999)·너무 깊은
    중첩(RecursionError)은 ValueError. UnicodeDecodeError 도 ValueError 의 하위형이다."""
    if isinstance(data, (bytes, bytearray, memoryview)):
        text = bytes(data).decode("utf-8-sig")
    elif isinstance(data, str):
        text = data[1:] if data.startswith("﻿") else data
    else:
        raise TypeError("loads_strict: bytes 또는 str 이 필요합니다")
    try:
        return json.loads(text, object_pairs_hook=reject_dup_keys, parse_constant=reject_nan,
                          parse_float=_strict_float)
    except RecursionError:
        # '[' 10만 개 같은 깊은 중첩 — 형식 깨짐과 같게(기본값 + 경고 1줄). 팀 레지스트리 캐시·다른 PC 파일처럼
        # 밖에서 온 JSON 하나가 호출자를 통째로 죽이지 않게 한다.
        raise ValueError("JSON 중첩이 너무 깊습니다") from None


# ── 경로 ───────────────────────────────────────────────────────────────────
def longp(p) -> str:
    r"""절대 경로 문자열. 240자 이상이면 확장 경로(``\\?\`` · UNC 는 ``\\?\UNC\``)로 — 짧으면 그대로."""
    s = os.fspath(p)
    if os.name != "nt":
        return os.path.abspath(s)
    if s.startswith(_EXT):
        return s
    a = os.path.abspath(s)
    if len(a) < MAXP:
        return a
    if a.startswith("\\\\"):
        return _EXT_UNC + a[2:]
    return _EXT + a


def ensure_dir(path) -> str:
    """폴더가 없으면 한 단계씩 만든다(확장 경로에서 os.makedirs 가 부모를 거슬러 오르다 깨지는 문제 회피).
    반환: 정규화된 절대 경로(확장 접두 없음)."""
    a = os.path.abspath(os.fspath(path))
    todo = []
    cur = a
    while not os.path.isdir(longp(cur)):
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        todo.append(cur)
        cur = parent
    for d in reversed(todo):
        try:
            os.mkdir(longp(d))
        except FileExistsError:
            if not os.path.isdir(longp(d)):
                raise
    return a


# ── 쓰기 ───────────────────────────────────────────────────────────────────
def _as_bytes(data) -> bytes:
    if isinstance(data, str):
        return data.encode("utf-8")
    if isinstance(data, (bytes, bytearray, memoryview)):
        return bytes(data)
    raise TypeError("atomic_write: bytes 또는 str 이 필요합니다")


def _remove_quiet(p):
    try:
        os.remove(p)
    except FileNotFoundError:
        pass
    except PermissionError:
        _sleep(0.1)
        try:
            os.remove(p)
        except OSError:
            _warn(f"임시 조각을 지우지 못했습니다: {os.path.basename(p)}")


def _replace_retry(src, dst):
    for wait in RETRY_WAITS + (None,):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if wait is None:
                raise
            _sleep(wait)


def part_name(path) -> str:
    """원자 쓰기 조각 이름 ``<path>.<pid>.<thread>.<rand4>.part``(계약 §1.5)."""
    a = os.path.abspath(os.fspath(path))
    return f"{a}.{os.getpid()}.{threading.get_ident()}.{os.urandom(2).hex()}.part"


def atomic_write(path, data, *, fsync=True) -> None:
    """같은 폴더에 ``<path>.<pid>.<thread>.<rand4>.part`` 로 쓰고 flush(+fsync) → ``os.replace``.
    부모 폴더가 없으면 만든다. 실패하면 조각을 지우고 예외를 올린다(반쪽 파일을 남기지 않는다).
    ``data`` 는 bytes(str 이면 UTF-8 로 인코딩)."""
    raw = _as_bytes(data)
    a = os.path.abspath(os.fspath(path))
    ensure_dir(os.path.dirname(a))
    part = longp(part_name(a))
    try:
        with open(part, "wb") as fh:
            fh.write(raw)
            fh.flush()
            if fsync:
                os.fsync(fh.fileno())
        _replace_retry(part, longp(a))
    except BaseException:
        _remove_quiet(part)
        raise


_APPEND_LOCK = threading.Lock()              # 같은 프로세스 안 스레드 사이 직렬화
_FILE_APPEND_DATA = 0x0004
_SYNCHRONIZE = 0x00100000
_SHARE_ALL = 0x1 | 0x2 | 0x4                 # FILE_SHARE_READ | WRITE | DELETE — 읽는 쪽·원자 교체를 막지 않는다
_OPEN_ALWAYS = 4
_FILE_ATTRIBUTE_NORMAL = 0x80
_APPEND_RETRY_ERRS = (32, 33)                # ERROR_SHARING_VIOLATION · ERROR_LOCK_VIOLATION — 잠깐 뒤 다시
_k32_cache = []


def _k32_append():
    if not _k32_cache:
        import ctypes
        from ctypes import wintypes
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.CreateFileW.restype = wintypes.HANDLE
        k.CreateFileW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                                  wintypes.DWORD, wintypes.HANDLE)
        k.WriteFile.restype = wintypes.BOOL
        k.WriteFile.argtypes = (wintypes.HANDLE, ctypes.c_char_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
                                ctypes.c_void_p)
        k.FlushFileBuffers.restype = wintypes.BOOL
        k.FlushFileBuffers.argtypes = (wintypes.HANDLE,)
        k.CloseHandle.restype = wintypes.BOOL
        k.CloseHandle.argtypes = (wintypes.HANDLE,)
        _k32_cache.append((k, ctypes, wintypes))
    return _k32_cache[0]


def _append_bytes_nt(lp: str, data: bytes, fsync: bool) -> None:
    """``FILE_APPEND_DATA`` 만으로 열어(``FILE_WRITE_DATA`` 없음) ``WriteFile`` 한 번 — 커널이 그 쓰기를 파일 끝에
    통째로 붙인다. 여러 프로세스가 동시에 덧붙여도 줄이 섞이거나 덮이지 않는다(CRT 의 'a' 모드는 '끝으로 이동 후 쓰기'를
    흉내 내므로 원자적이지 않다 — 4프로세스 8,000줄 중 1,600여 줄 유실·깨짐 실측)."""
    k, ctypes, wintypes = _k32_append()
    invalid = ctypes.c_void_p(-1).value
    for wait in READ_RETRY + (None,):
        h = k.CreateFileW(lp, _FILE_APPEND_DATA | _SYNCHRONIZE, _SHARE_ALL, None, _OPEN_ALWAYS,
                          _FILE_ATTRIBUTE_NORMAL, None)
        if h is not None and h != invalid:
            break
        err = ctypes.get_last_error()
        if wait is None or err not in _APPEND_RETRY_ERRS:
            raise ctypes.WinError(err)
        _sleep(wait)
    try:
        done = wintypes.DWORD(0)
        if not k.WriteFile(h, data, len(data), ctypes.byref(done), None):
            raise ctypes.WinError(ctypes.get_last_error())
        if done.value != len(data):
            raise OSError(f"append_line: 덧붙이기가 짧게 끝났습니다({done.value}/{len(data)}바이트)")
        if fsync and not k.FlushFileBuffers(h):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        k.CloseHandle(h)


def append_line(path, line: str, *, fsync=False) -> None:
    """로그·jsonl 한 줄 덧붙이기(UTF-8, LF). 줄 안에 줄바꿈이 있으면 ValueError(한 줄 = 한 기록).
    끝의 ``\n`` 하나는 허용하고 없으면 붙인다. 부모 폴더가 없으면 만든다.
    동시성: 한 줄 = 한 번의 커널 덧붙이기(Windows ``FILE_APPEND_DATA``) + 프로세스 안 잠금 — 에이전트·수확·화면 서버
    스레드·병렬 파이프가 같은 파일(export_log·감사·원장)에 동시에 써도 줄이 사라지거나 섞이지 않는다."""
    if not isinstance(line, str):
        raise TypeError("append_line: str 이 필요합니다")
    body = line[:-1] if line.endswith("\n") else line
    if "\n" in body or "\r" in body:
        raise ValueError("append_line: 한 줄 안에 줄바꿈이 있습니다")
    data = (body + "\n").encode("utf-8")
    a = os.path.abspath(os.fspath(path))
    ensure_dir(os.path.dirname(a))
    with _APPEND_LOCK:
        if os.name == "nt":
            _append_bytes_nt(longp(a), data, fsync)
            return
        with open(longp(a), "ab") as fh:     # POSIX O_APPEND 는 write 한 번이 원자적
            fh.write(data)
            fh.flush()
            if fsync:
                os.fsync(fh.fileno())


# ── 읽기 ───────────────────────────────────────────────────────────────────
def read_bytes(path) -> bytes:
    """파일 전체를 읽고 즉시 닫는다. 원자 교체 순간의 PermissionError 는 0.1초 × 5회 재시도."""
    lp = longp(path)
    for wait in READ_RETRY + (None,):
        try:
            with open(lp, "rb") as fh:
                return fh.read()
        except PermissionError:
            if wait is None or os.path.isdir(lp):
                raise
            _sleep(wait)
    raise AssertionError("unreachable")


def _want_name(want) -> str:
    if isinstance(want, tuple):
        return "|".join(getattr(w, "__name__", str(w)) for w in want)
    return getattr(want, "__name__", str(want))


def read_json(path, default=None, *, want=dict):
    """JSON 파일을 엄격하게 읽는다(utf-8-sig 허용, 중복 키·NaN·Infinity 거부).
    · 파일 없음 → ``default``(첫 실행의 정상 상태라 경고하지 않는다)
    · 읽기 실패·형식 깨짐·``want`` 형 아님 → ``default`` + stderr 경고 1줄(조용히 삼키지 않는다)
    ``want=None`` 이면 형을 따지지 않는다. 경고에는 파일 이름(basename)과 예외 유형만 쓴다."""
    name = os.path.basename(os.fspath(path))
    try:
        raw = read_bytes(path)
    except FileNotFoundError:
        return default
    except OSError as e:
        _warn(f"JSON 읽기 실패({type(e).__name__}): {name}")
        return default
    try:
        obj = loads_strict(raw)
    except ValueError as e:
        _warn(f"JSON 형식 오류({type(e).__name__}): {name}")
        return default
    if want is not None and not isinstance(obj, want):
        _warn(f"JSON 형이 다릅니다(기대 {_want_name(want)}, 실제 {type(obj).__name__}): {name}")
        return default
    return obj


# ── 바이트 도구 ─────────────────────────────────────────────────────────────
def gzip_bytes(raw) -> bytes:
    """결정적 gzip — ``GzipFile(filename="", mtime=0, compresslevel=6)``. 헤더에 시각·이름이 없어 같은 입력 = 같은 바이트."""
    bio = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=bio, mtime=0, compresslevel=6) as gz:
        gz.write(_as_bytes(raw))
    return bio.getvalue()


def sha256_hex(b) -> str:
    """바이트(str 이면 UTF-8)의 sha256 16진 문자열."""
    return hashlib.sha256(_as_bytes(b)).hexdigest()


def utcnow_iso() -> str:
    """지금 UTC 를 ``YYYY-MM-DDTHH:MM:SSZ``(초 단위)로."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── 경고 ───────────────────────────────────────────────────────────────────
def _warn(msg: str) -> None:
    """사람용 경고 1줄 → stderr(계약 §8.6 '사람용 요약은 stderr'). pythonw 처럼 stderr 가 없으면 생략."""
    st = sys.stderr
    if st is None:
        return
    try:
        st.write("[경고] " + msg + "\n")
        st.flush()
    except (OSError, ValueError):
        pass
