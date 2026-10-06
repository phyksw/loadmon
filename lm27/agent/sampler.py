# -*- coding: utf-8 -*-
r"""py 구현 샘플러(계약 §2.4 · CP §3 · §8 · TAB §1.6.1) — ctypes(user32·wtsapi32·kernel32)로 매 틱 **원시 틱**을 메모리에만
만든다. 디스크에 아무것도 쓰지 않는다(저장은 감독 루프가 ``sanitize_record`` → ``SegmentWriter`` 로 — P I1·I2).

원시 틱(``RawTick``, 메모리 전용):
  · 전경 창: ``GetForegroundWindow`` → ``GetWindowThreadProcessId`` → ``QueryFullProcessImageNameW``(실행 파일 이름만 쓰고 경로는
    미지 프로그램 메타 조회에만) · ``GetWindowTextW``(제목 원문 — 플러시 때 정제기가 ``title_masked``·``doc_key`` 로 바꾸고 버린다).
  · 유휴: ``GetLastInputInfo`` 와 ``GetTickCount64`` 의 **2^32 모듈로 차이**(CP §3.3 — ``dwTime`` 은 32비트, 가동 49.7일 넘어도 정확).
  · 세션: ``WTSQuerySessionInformationW(WTSSessionInfoEx)`` 의 연결 상태·잠금 플래그 + ``WTSClientProtocolType``(2 = RDP) →
    ``active``·``locked``·``disconnected``·``remote``(CP §3.2). 사용자 이름 칸은 읽지 않는다.
  · 솔버 CPU: 솔버 이름(``pc.solverProcesses`` − ``pc.solverProcessesExclude``)인 프로세스만 ``GetProcessTimes`` 누계(CP §8).

레코드 모양(P §10.2 pc_session 원시 이름 — ps 구현 ``agent.ps1`` 과 같은 필드·같은 값, TAB-B22):
  ``tick_record(tick, interval_sec)`` = ts_utc · ts_local_offset · ts_precision(exact) · observed_at · confidence ·
  fg_exe(``catalog.exe_name``) · app_id · app_class(카탈로그 — 잡음 프로세스는 fg_exe·app_id 없이 ``system``, 전경 없음 ``idle``) ·
  fg_title · [fg_doc_name · fg_doc_path](C15 — 아는 경우만) · session_state · idle_sec · layer(``idle``·``system`` 이면 L2,
  아니면 L3 — X-079) · interval_sec(실제 틱 간격 — X-080·CP §3.7) · flags(remote · utc_suspect).
  고착(stuck)은 판정하지 않는다(정규화 몫 — CP §3.7). 수집은 pc_id·interval·idle 원값을 모든 행에 남긴다.

연산 구간(``ComputeTracker``, CP §8): 솔버 프로세스의 CPU 시간 차분 ÷ 벽시계 = 코어 수. ``pc.compute.cpuCoreThreshold``(0.5)
이상이 ``pc.compute.consecutiveTicks``(3) 틱 이어지면 구간. 같은 app_id 의 프로세스는 합친다. 끝나지 않은 구간은 플러시 때
``flags.end_uncertain`` 판으로(같은 id — 로더가 observed_at 최대를 쓴다, X-032), 끝나면 확정 판으로 낸다.

문서 경로(``DocIndex``, C15 — ``dir_keys``): 창 제목의 절대 경로, 없으면 Recent 바로가기(.lnk) 대상 경로에서 문서 이름으로
찾는다(메모리 색인, 10분마다 다시 읽음 — D-3 '최근 문서' 경로). 못 찾으면 비운다.

이 모듈은 에이전트 bin 사본에 들어간다(계약 §1.3) — 표준 라이브러리와 사본 안 모듈(``lm27.catalog``·``lm27.util``·
``lm27.privacy``)만 쓴다. 실기계 조회는 ``WinApi`` 한 곳에 모았고 시험은 같은 메서드를 가진 가짜를 넣는다.
"""
from __future__ import annotations

import os
import re
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime

from lm27 import catalog
from lm27.privacy.classify import TITLE_KEEP_CLASSES
from lm27.util import fsx, tz

__all__ = [
    "ComputeTracker", "DocIndex", "RawTick", "WinApi", "app_of", "compute_record", "default_api", "fmt_utc", "idle_sec",
    "lnk_target", "map_session", "session_state", "take_sample", "tick_record",
]

TICK_MOD = 1 << 32                       # GetLastInputInfo.dwTime 은 32비트(GetTickCount 하위)
IDLE_MAX = 4294968                       # P §10.2 idle_sec 상한(2^32 ms 를 초로)
TITLE_MAX = 1024                         # 제목 원문은 앞 1024자만 메모리에(병적 입력 방어)
PROTO_RDP = 2                            # WTSClientProtocolType: 0 콘솔 · 1 ICA · 2 RDP
WTS_DISCONNECTED = 4                     # WTS_CONNECTSTATE_CLASS.WTSDisconnected
WTS_LOCKED = 0                           # WTSINFOEX_LEVEL1.SessionFlags: 0 잠김 · 1 잠금 해제 · -1 모름
DOC_REFRESH_S = 600
DOC_MAX_LINKS = 200
_ZERO_WIDTH = re.compile("[​-‏⁠﻿]")
_ABS_RX = re.compile(r"^(?:[A-Za-z]:\\|\\\\[^\\]+\\)")
_EXT_RX = re.compile(r"\.[0-9A-Za-z]{1,8}$")
_TITLE_MARKS = re.compile(r"^[*\s]+|[*\s]+$|\s*\[(?:읽기 전용|Read-Only|호환 모드|Compatibility Mode)\]\s*$", re.I)


def fmt_utc(dt: datetime) -> str:
    """aware datetime → ``YYYY-MM-DDTHH:MM:SSZ``."""
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# ───────────────────────────── 순수 판정 ─────────────────────────────
def idle_sec(tick64: int, last_input: int) -> int:
    """유휴 초 = ((GetTickCount64 − dwTime) mod 2^32) / 1000 반올림, 상한 ``IDLE_MAX``(CP §3.3 — 이전 판 32비트 음수 결함 수정).
    파이썬 ``%`` 는 언제나 0 이상이라 dwTime 이 앞서 보이는 경우(랩어라운드)도 맞다."""
    diff = (int(tick64) - int(last_input)) % TICK_MOD
    return min(IDLE_MAX, int(round(diff / 1000.0)))


def map_session(connect_state, session_flags, protocol) -> tuple[str, bool]:
    """WTS 값 → (session_state, remote). 끊김 > 잠김 > 원격 > 활성(CP §3.2). 조회 실패(None)는 활성으로 본다."""
    remote = protocol == PROTO_RDP
    if connect_state == WTS_DISCONNECTED:
        return "disconnected", remote
    if session_flags == WTS_LOCKED:
        return "locked", remote
    if remote:
        return "remote", True
    return "active", False


def _layer(app_class: str) -> str:
    return "L2" if app_class in ("idle", "system") else "L3"


# ───────────────────────────── 실기계 조회(ctypes) ─────────────────────────────
class WinApi:
    """user32·kernel32·wtsapi32 호출 묶음. 각 메서드는 실패하면 빈 값(0·""·None)을 돌려준다(예외를 감독 루프로 올리지 않는다).
    사용자 이름·도메인 칸이 든 구조체는 필요한 정수 칸만 꺼내고 바로 해제한다."""

    def __init__(self):
        import ctypes
        from ctypes import wintypes
        self.ct, self.wt = ctypes, wintypes
        u = ctypes.WinDLL("user32", use_last_error=True)
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        w = ctypes.WinDLL("wtsapi32", use_last_error=True)
        u.GetForegroundWindow.restype = wintypes.HWND
        u.GetForegroundWindow.argtypes = ()
        u.GetWindowThreadProcessId.restype = wintypes.DWORD
        u.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
        u.GetWindowTextLengthW.restype = ctypes.c_int
        u.GetWindowTextLengthW.argtypes = (wintypes.HWND,)
        u.GetWindowTextW.restype = ctypes.c_int
        u.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)

        class _LII(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

        self._LII = _LII
        u.GetLastInputInfo.restype = wintypes.BOOL
        u.GetLastInputInfo.argtypes = (ctypes.POINTER(_LII),)
        k.GetTickCount64.restype = ctypes.c_ulonglong
        k.GetTickCount64.argtypes = ()
        k.OpenProcess.restype = wintypes.HANDLE
        k.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        k.CloseHandle.restype = wintypes.BOOL
        k.CloseHandle.argtypes = (wintypes.HANDLE,)
        k.QueryFullProcessImageNameW.restype = wintypes.BOOL
        k.QueryFullProcessImageNameW.argtypes = (wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                 ctypes.POINTER(wintypes.DWORD))
        k.GetProcessTimes.restype = wintypes.BOOL
        k.GetProcessTimes.argtypes = (wintypes.HANDLE,) + (ctypes.POINTER(wintypes.FILETIME),) * 4

        class _PE(ctypes.Structure):
            _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                        ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD),
                        ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
                        ("pcPriClassBase", wintypes.LONG), ("dwFlags", wintypes.DWORD),
                        ("szExeFile", wintypes.WCHAR * 260)]

        self._PE = _PE
        k.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        k.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
        k.Process32FirstW.restype = wintypes.BOOL
        k.Process32FirstW.argtypes = (wintypes.HANDLE, ctypes.POINTER(_PE))
        k.Process32NextW.restype = wintypes.BOOL
        k.Process32NextW.argtypes = (wintypes.HANDLE, ctypes.POINTER(_PE))

        class _L1(ctypes.Structure):
            _fields_ = [("SessionId", wintypes.ULONG), ("SessionState", ctypes.c_int), ("SessionFlags", wintypes.LONG),
                        ("WinStationName", wintypes.WCHAR * 33), ("UserName", wintypes.WCHAR * 21),
                        ("DomainName", wintypes.WCHAR * 18), ("LogonTime", wintypes.LARGE_INTEGER),
                        ("ConnectTime", wintypes.LARGE_INTEGER), ("DisconnectTime", wintypes.LARGE_INTEGER),
                        ("LastInputTime", wintypes.LARGE_INTEGER), ("CurrentTime", wintypes.LARGE_INTEGER),
                        ("IncomingBytes", wintypes.DWORD), ("OutgoingBytes", wintypes.DWORD),
                        ("IncomingFrames", wintypes.DWORD), ("OutgoingFrames", wintypes.DWORD),
                        ("IncomingCompressedBytes", wintypes.DWORD), ("OutgoingCompressedBytes", wintypes.DWORD)]

        class _U(ctypes.Union):
            _fields_ = [("Level1", _L1)]

        class _EX(ctypes.Structure):
            _fields_ = [("Level", wintypes.DWORD), ("Data", _U)]

        self._EX = _EX
        w.WTSQuerySessionInformationW.restype = wintypes.BOOL
        w.WTSQuerySessionInformationW.argtypes = (wintypes.HANDLE, wintypes.DWORD, ctypes.c_int,
                                                  ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.DWORD))
        w.WTSFreeMemory.restype = None
        w.WTSFreeMemory.argtypes = (ctypes.c_void_p,)
        self.u, self.k, self.w = u, k, w

    # 전경 창
    def foreground(self) -> tuple[int, int]:
        h = self.u.GetForegroundWindow()
        if not h:
            return 0, 0
        pid = self.wt.DWORD(0)
        self.u.GetWindowThreadProcessId(h, self.ct.byref(pid))
        return int(h), int(pid.value)

    def window_text(self, hwnd: int) -> str:
        if not hwnd:
            return ""
        n = self.u.GetWindowTextLengthW(hwnd)
        if n <= 0:
            return ""
        n = min(n, TITLE_MAX)
        buf = self.ct.create_unicode_buffer(n + 1)
        self.u.GetWindowTextW(hwnd, buf, n + 1)
        return buf.value

    def image_path(self, pid: int) -> str:
        if not pid:
            return ""
        h = self.k.OpenProcess(0x1000, False, pid)          # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return ""
        try:
            size = self.wt.DWORD(1024)
            buf = self.ct.create_unicode_buffer(1024)
            if not self.k.QueryFullProcessImageNameW(h, 0, buf, self.ct.byref(size)):
                return ""
            return buf.value
        finally:
            self.k.CloseHandle(h)

    # 유휴
    def tick64(self) -> int:
        return int(self.k.GetTickCount64())

    def last_input(self):
        lii = self._LII()
        lii.cbSize = self.ct.sizeof(self._LII)
        if not self.u.GetLastInputInfo(self.ct.byref(lii)):
            return None
        return int(lii.dwTime)

    # 세션
    def _wts_query(self, cls: int):
        p = self.ct.c_void_p()
        n = self.wt.DWORD(0)
        if not self.w.WTSQuerySessionInformationW(None, 0xFFFFFFFF, cls, self.ct.byref(p), self.ct.byref(n)) \
                or not p.value:
            return None, 0
        return p, n.value

    def wts(self) -> tuple:
        """(연결 상태, 잠금 플래그, 프로토콜) — 실패한 칸은 None."""
        state = flags = proto = None
        p, n = self._wts_query(25)                           # WTSSessionInfoEx
        if p is not None:
            try:
                if n >= self.ct.sizeof(self._EX):
                    ex = self.ct.cast(p, self.ct.POINTER(self._EX)).contents
                    if ex.Level == 1:
                        state, flags = int(ex.Data.Level1.SessionState), int(ex.Data.Level1.SessionFlags)
            finally:
                self.w.WTSFreeMemory(p)
        p, n = self._wts_query(16)                           # WTSClientProtocolType
        if p is not None:
            try:
                if n >= 2:
                    proto = int(self.ct.cast(p, self.ct.POINTER(self.ct.c_ushort)).contents.value)
            finally:
                self.w.WTSFreeMemory(p)
        return state, flags, proto

    # 프로세스
    def processes(self) -> list:
        """[(pid, 실행 파일 이름)] — 스냅숏 한 번."""
        h = self.k.CreateToolhelp32Snapshot(2, 0)            # TH32CS_SNAPPROCESS
        if not h or h == self.ct.c_void_p(-1).value:
            return []
        out = []
        try:
            e = self._PE()
            e.dwSize = self.ct.sizeof(self._PE)
            ok = self.k.Process32FirstW(h, self.ct.byref(e))
            while ok:
                out.append((int(e.th32ProcessID), str(e.szExeFile)))
                ok = self.k.Process32NextW(h, self.ct.byref(e))
        finally:
            self.k.CloseHandle(h)
        return out

    def cpu_seconds(self, pid: int):
        h = self.k.OpenProcess(0x1000, False, pid)
        if not h:
            return None
        try:
            ft = [self.wt.FILETIME() for _ in range(4)]
            if not self.k.GetProcessTimes(h, *(self.ct.byref(f) for f in ft)):
                return None
            ker = (ft[2].dwHighDateTime << 32) | ft[2].dwLowDateTime
            usr = (ft[3].dwHighDateTime << 32) | ft[3].dwLowDateTime
            return (ker + usr) / 1e7
        finally:
            self.k.CloseHandle(h)


_API: list = []


def default_api() -> WinApi:
    if not _API:
        _API.append(WinApi())
    return _API[0]


def session_state(api=None) -> str:
    """지금 세션 상태(``active``·``locked``·``disconnected``·``remote``)."""
    a = api or default_api()
    st, fl, pr = a.wts()
    return map_session(st, fl, pr)[0]


# ───────────────────────────── 원시 틱 ─────────────────────────────
@dataclass
class RawTick:
    """한 틱의 관측(메모리 전용). ``fg_title``·``fg_path`` 는 원문이라 저장하지 않는다(정제기만 본다)."""
    ts: datetime
    off_min: int
    fg_exe: str = ""
    fg_title: str = ""
    fg_path: str = ""
    session_state: str = "active"
    remote: bool = False
    idle_sec: int | None = None
    cpu: dict = field(default_factory=dict)      # pid → (exe, CPU 누계 초) — 솔버 이름인 프로세스만
    errors: tuple = ()                           # 실패한 조회의 예외 유형 이름(원문 없음)
    ok: dict = field(default_factory=dict)       # 조회별 성공 여부(자기 시험용)


def _call(fn, errs, ok, name, default):
    try:
        v = fn()
        ok[name] = True
        return v
    except (OSError, ValueError, AttributeError, TypeError) as e:
        errs.append(type(e).__name__)
        ok[name] = False
        return default


def take_sample(prev=None, *, api=None, now=None, solvers=None, cfg=None) -> RawTick:
    """원시 틱 하나(메모리). ``prev`` 는 직전 틱(쓰지 않아도 된다 — 시그니처 계약). ``solvers`` = 솔버 이름 집합
    (``catalog.solver_set(cfg)``) — 주면 그 이름의 프로세스 CPU 누계를 읽는다. ``now``·``api`` 는 시험 주입."""
    a = api or default_api()
    ts = (now or datetime.now(UTC)).astimezone(UTC).replace(microsecond=0)
    errs, ok = [], {}
    off = _call(lambda: tz.capture_offset_min(ts), errs, ok, "tz", 0)
    hwnd, pid = _call(a.foreground, errs, ok, "fg", (0, 0))
    title = _call(lambda: a.window_text(hwnd), errs, ok, "title", "") if hwnd else ""
    path = _call(lambda: a.image_path(pid), errs, ok, "image", "") if pid else ""
    exe = catalog.exe_name(os.path.basename(path)) if path else ""
    tick = _call(a.tick64, errs, ok, "tick", None)
    last = _call(a.last_input, errs, ok, "idle", None)
    idle = idle_sec(tick, last) if tick is not None and last is not None else None
    ok["idle"] = idle is not None
    st, fl, pr = _call(a.wts, errs, ok, "session", (None, None, None))
    state, remote = map_session(st, fl, pr)
    ok["session"] = st is not None
    cpu = {}
    if solvers:
        for p_id, name in _call(a.processes, errs, ok, "procs", []):
            if p_id and catalog.is_solver(name, cfg, solvers=solvers):
                secs = _call(lambda p_id=p_id: a.cpu_seconds(p_id), errs, ok, "cpu", None)
                if secs is not None:
                    cpu[p_id] = (catalog.exe_norm(name), float(secs))
    return RawTick(ts=ts, off_min=int(off or 0), fg_exe=exe, fg_title=(title or "")[:TITLE_MAX], fg_path=path or "",
                   session_state=state, remote=remote, idle_sec=idle, cpu=cpu, errors=tuple(errs), ok=ok)


def app_of(exe: str, extra=()) -> tuple:
    """실행 파일 이름 → (fg_exe, app_id, app_class). 전경 없음 = (None, None, idle) · 잡음(OS 서비스·라이선스 대리자)
    = (None, None, system) · 카탈로그 밖 = (exe, unknown:<exe>, other)."""
    if not exe:
        return None, None, "idle"
    if catalog.is_noise(exe):
        return None, None, "system"
    aid = catalog.app_id_for(exe, extra)
    if not aid:
        return None, None, "system"
    return catalog.exe_name(exe), aid, catalog.app_class_of(aid, extra)


def tick_record(tick: RawTick, interval_sec: int, *, extra=(), doc_path: str | None = None) -> dict:
    """원시 틱 → pc_session(pc.sampler) 원시 레코드(P §10.2 원시 이름, 메모리). 제목 원문을 담으므로 정제기에만 넘긴다."""
    fg, aid, ac = app_of(tick.fg_exe, extra)
    ts = fmt_utc(tick.ts)
    rec = {"ts_utc": ts, "ts_local_offset": tz.fmt_offset(tick.off_min), "ts_precision": "exact", "observed_at": ts,
           "confidence": 1.0, "fg_exe": fg, "app_id": aid, "app_class": ac, "fg_title": tick.fg_title or "",
           "session_state": tick.session_state, "layer": _layer(ac), "interval_sec": max(1, int(interval_sec))}
    if tick.idle_sec is not None:
        rec["idle_sec"] = int(tick.idle_sec)
    if doc_path:
        rec["fg_doc_path"] = doc_path
        rec["fg_doc_name"] = re.split(r"[\\/]", doc_path)[-1]
    flags = {}
    if tick.remote:
        flags["remote"] = True
    if tick.off_min == 0:
        flags["utc_suspect"] = True                      # UTC 로 설정된 PC(클라우드PC 등 — CP §13.2)
    if flags:
        rec["flags"] = flags
    return rec


# ───────────────────────────── 연산 구간(CP §8) ─────────────────────────────
@dataclass
class _Run:
    app_id: str
    exe: str
    start: datetime
    last: datetime
    ticks: int = 0
    core_s: float = 0.0
    wall_s: float = 0.0


class ComputeTracker:
    """솔버 CPU 누계(틱마다) → 연산 구간. ``observe`` 가 닫힌 구간을, ``open_intervals`` 가 진행 중 구간을 돌려준다."""

    def __init__(self, threshold: float = 0.5, ticks: int = 3, extra=()):
        self.threshold = float(threshold)
        self.need = max(1, int(ticks))
        self.extra = extra
        self.prev: dict = {}                       # pid → (exe, 누계 초, 시각)
        self.runs: dict = {}                       # app_id → _Run

    def observe(self, ts: datetime, cpu: dict) -> list:
        per_app: dict = {}
        for pid, (exe, secs) in (cpu or {}).items():
            p = self.prev.get(pid)
            if p and p[0] == exe and secs >= p[1]:
                dt = (ts - p[2]).total_seconds()
                if dt > 0:
                    aid = catalog.app_id_for(exe, self.extra) or catalog.unknown_app_id(exe)
                    if aid:
                        a = per_app.setdefault(aid, [0.0, exe, p[2], dt])
                        a[0] += secs - p[1]
                        a[2] = min(a[2], p[2])
                        a[3] = max(a[3], dt)
        self.prev = {pid: (exe, secs, ts) for pid, (exe, secs) in (cpu or {}).items()}
        closed = []
        for aid in list(self.runs):
            v = per_app.get(aid)
            if v is None or v[0] / v[3] < self.threshold:
                run = self.runs.pop(aid)
                if run.ticks >= self.need:
                    closed.append(run)
        for aid, (core, exe, t0, dt) in per_app.items():
            if core / dt < self.threshold:
                continue
            run = self.runs.get(aid)
            if run is None:
                run = self.runs[aid] = _Run(app_id=aid, exe=exe, start=t0, last=ts)
            run.last = ts
            run.ticks += 1
            run.core_s += core
            run.wall_s += dt
        return closed

    def open_intervals(self) -> list:
        """구간으로 인정된(연속 틱 수를 채운) 진행 중 구간."""
        return [r for r in self.runs.values() if r.ticks >= self.need]

    def close_all(self) -> list:
        out = self.open_intervals()
        self.runs = {}
        return out


def compute_record(run: _Run, off_min: int, observed_at: datetime, *, final: bool) -> dict:
    """연산 구간 → pc_compute(pc.compute) 원시 레코드. 진행 중이면 ``flags.end_uncertain``."""
    flags = {"solver": True}
    if not final:
        flags["end_uncertain"] = True
    cores = run.core_s / run.wall_s if run.wall_s > 0 else 0.0
    return {"ts_utc": fmt_utc(run.start), "ts_end": fmt_utc(max(run.last, run.start)),
            "ts_local_offset": tz.fmt_offset(off_min), "ts_precision": "exact", "observed_at": fmt_utc(observed_at),
            "confidence": 1.0, "fg_exe": catalog.exe_name(run.exe), "app_id": run.app_id,
            "cpu_core": round(min(256.0, max(0.0, cores)), 3), "flags": flags}


# ───────────────────────────── 문서 경로 색인(C15) ─────────────────────────────
def _u16(b: bytes, o: int) -> int:
    return int.from_bytes(b[o:o + 2], "little")


def _u32(b: bytes, o: int) -> int:
    return int.from_bytes(b[o:o + 4], "little")


def _utf16z(b: bytes, o: int) -> str:
    if o <= 0 or o >= len(b):
        return ""
    end = o
    while end + 1 < len(b) and b[end:end + 2] != b"\x00\x00":
        end += 2
    return b[o:end].decode("utf-16-le", errors="replace")


def _ansiz(b: bytes, o: int) -> str:
    if o <= 0 or o >= len(b):
        return ""
    end = b.find(b"\x00", o)
    raw = b[o:end if end >= 0 else len(b)]
    try:
        return raw.decode("mbcs")
    except (LookupError, UnicodeDecodeError):
        return raw.decode("latin-1")


def lnk_target(data: bytes) -> str:
    """셸 바로가기(.lnk) 바이트 → 대상 경로(LinkInfo 의 LocalBasePath + CommonPathSuffix, 또는 네트워크 이름). 모르면 ""."""
    try:
        if len(data) < 0x4C or _u32(data, 0) != 0x4C:
            return ""
        flags = _u32(data, 0x14)
        off = 0x4C
        if flags & 0x1:                                   # HasLinkTargetIDList
            off += 2 + _u16(data, off)
        if not flags & 0x2 or off + 0x1C > len(data):     # HasLinkInfo
            return ""
        li = off
        hdr, lif = _u32(data, li + 4), _u32(data, li + 8)
        uni = hdr >= 0x24
        suffix = _utf16z(data, li + _u32(data, li + 0x20)) if uni else _ansiz(data, li + _u32(data, li + 0x18))
        if lif & 0x1:
            base = _utf16z(data, li + _u32(data, li + 0x1C)) if uni else _ansiz(data, li + _u32(data, li + 0x10))
            if base:
                return base.rstrip("\\") + "\\" + suffix if suffix else base
        if lif & 0x2:
            cn = li + _u32(data, li + 0x14)
            nn = _u32(data, cn + 8)
            net = _utf16z(data, cn + _u32(data, cn + 0x14)) if nn > 0x14 else ""
            net = net or _ansiz(data, cn + nn)
            if net:
                return net.rstrip("\\") + "\\" + suffix if suffix else net
    except (IndexError, ValueError):
        return ""
    return ""


def _recent_dir() -> str:
    base = os.environ.get("APPDATA") or ""
    return os.path.join(base, "Microsoft", "Windows", "Recent") if base else ""


def _clean_title(title: str) -> str:
    t = _ZERO_WIDTH.sub("", unicodedata.normalize("NFKC", title or ""))
    return t.strip()


class DocIndex:
    """문서 이름 → 전체 경로(메모리). 원천: 창 제목 안의 절대 경로 > Recent 바로가기 대상(가장 최근 것이 이긴다).
    ``recent_dir`` = 시험 주입(없으면 ``%APPDATA%\\Microsoft\\Windows\\Recent``)."""

    def __init__(self, recent_dir: str | None = None, *, max_links: int = DOC_MAX_LINKS, refresh_s: float = DOC_REFRESH_S,
                 clock=time.monotonic):
        self.recent_dir = recent_dir
        self.max_links = max_links
        self.refresh_s = refresh_s
        self.clock = clock
        self._at = None
        self._by_name: dict = {}
        self._by_stem: dict = {}

    def refresh(self) -> int:
        d = self.recent_dir if self.recent_dir is not None else _recent_dir()
        by_name, stems = {}, {}
        try:
            ents = [e for e in os.scandir(d) if e.is_file() and e.name.lower().endswith(".lnk")] if d else []
        except OSError:
            ents = []
        ents.sort(key=lambda e: (-_mtime(e), e.name))
        for e in ents[:self.max_links]:
            try:
                tgt = lnk_target(fsx.read_bytes(e.path)[:65536])    # 읽기만 — 대상 경로는 메모리에만
            except OSError:
                continue
            if not tgt or "://" in tgt:
                continue
            name = re.split(r"[\\/]", tgt)[-1]
            key = name.lower()
            if not key or key in by_name:
                continue
            by_name[key] = tgt
            stem = os.path.splitext(key)[0]
            stems.setdefault(stem, set()).add(tgt)
        self._by_name = by_name
        self._by_stem = {s: next(iter(v)) for s, v in stems.items() if len(v) == 1}
        self._at = self.clock()
        return len(by_name)

    def path_for(self, title: str, app_class: str) -> str | None:
        """문서 창(``TITLE_KEEP_CLASSES``)의 제목 → 문서 전체 경로(메모리). 모르면 None."""
        if app_class not in TITLE_KEEP_CLASSES or not title:
            return None
        t = _clean_title(title)
        pieces = [_TITLE_MARKS.sub("", p).strip() for p in t.split(" - ")]
        for p in pieces:
            if _ABS_RX.match(p) and _EXT_RX.search(p):
                return p
        name = pieces[0] if pieces else ""
        if not name:
            return None
        if self._at is None or self.clock() - self._at >= self.refresh_s:
            self.refresh()
        key = name.lower()
        return self._by_name.get(key) or (self._by_stem.get(key) if not _EXT_RX.search(key) else None)


def _mtime(e) -> float:
    try:
        return e.stat().st_mtime
    except OSError:
        return 0.0
