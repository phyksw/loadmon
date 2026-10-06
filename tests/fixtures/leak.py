# -*- coding: utf-8 -*-
r"""누수 관문 도우미(WP-05 하네스 — W1 통합 창): 장기 실행 부품을 합성 입력으로 반복 구동하면서 자원이 반복 횟수에 비례해
늘지 않는지 본다. 표준 라이브러리만(ctypes·tracemalloc).

    from tests.fixtures.leak import assert_bounded
    assert_bounded(self, step, warm=20, n=200)       # step(i) 를 warm 번 → 측정 → n 번 → 측정 → n 번 → 측정

재는 것: 파이썬 할당(tracemalloc 현재 크기) · 살아 있는 스레드 수 · 프로세스 핸들 수(Windows: 열린 파일·소켓·이벤트 등 —
GetProcessHandleCount) · 자식 프로세스 수(이 프로세스를 부모로 둔 살아 있는 프로세스) · 임시 폴더 항목 수(%TEMP% 바로 아래).
판정: 두 번째 n 번 동안 늘어난 양이 한도 안(스레드·임시 = 0, 핸들 = 작은 여유, 메모리 = 반복당 바이트 한도) —
첫 n 번에서 캐시가 차는 것은 허용하고, 그다음에도 계속 늘면 누수다. 자식 프로세스는 처음보다 늘면 안 된다.
임시 항목은 측정 동안 이 프로세스의 tempfile 기준을 전용 폴더로 돌려 센다(다른 시험 프로세스와 섞이지 않게).
"""
from __future__ import annotations

import gc
import os
import tempfile
import threading
import tracemalloc
from dataclasses import dataclass

__all__ = ["Snap", "assert_bounded", "child_pids", "handle_count", "snap", "temp_entries"]


def handle_count() -> int:
    """이 프로세스의 열린 핸들 수(Windows). 다른 OS 는 열린 fd 수(/proc/self/fd), 모르면 0."""
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        k32.GetProcessHandleCount.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        n = wintypes.DWORD()
        if k32.GetProcessHandleCount(k32.GetCurrentProcess(), ctypes.byref(n)):
            return int(n.value)
        return 0
    try:
        return len(os.listdir("/proc/self/fd"))
    except OSError:
        return 0


CONSOLE_HOSTS = frozenset({"conhost.exe", "openconsole.exe"})   # 창 없는 콘솔 프로세스에 OS 가 붙이는 콘솔 호스트(우리 자식 아님)


def child_pids() -> set[int]:
    """이 프로세스를 부모로 둔 살아 있는 프로세스 PID(Windows Toolhelp32 — 콘솔 호스트 conhost 제외). 다른 OS 는 빈 집합."""
    if os.name != "nt":
        return set()
    import ctypes
    from ctypes import wintypes

    class PE(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD),
                    ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
                    ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_wchar * 260)]

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k32.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
    k32.Process32FirstW.argtypes = (wintypes.HANDLE, ctypes.POINTER(PE))
    k32.Process32NextW.argtypes = (wintypes.HANDLE, ctypes.POINTER(PE))
    k32.CloseHandle.argtypes = (wintypes.HANDLE,)
    h = k32.CreateToolhelp32Snapshot(0x00000002, 0)          # TH32CS_SNAPPROCESS
    if not h or h == wintypes.HANDLE(-1).value:
        return set()
    me, out = os.getpid(), set()
    try:
        e = PE()
        e.dwSize = ctypes.sizeof(PE)
        ok = k32.Process32FirstW(h, ctypes.byref(e))
        while ok:
            if e.th32ParentProcessID == me and e.th32ProcessID != me and e.szExeFile.lower() not in CONSOLE_HOSTS:
                out.add(int(e.th32ProcessID))
            ok = k32.Process32NextW(h, ctypes.byref(e))
    finally:
        k32.CloseHandle(h)
    return out


def temp_entries(base: str | None = None) -> int:
    """%TEMP%(또는 base) 바로 아래 항목 수 — 반복마다 남는 임시 파일·폴더를 센다."""
    try:
        return len(os.listdir(base or tempfile.gettempdir()))
    except OSError:
        return 0


@dataclass(frozen=True)
class Snap:
    mem: int
    threads: int
    handles: int
    children: int
    temp: int


def snap(temp_base: str | None = None) -> Snap:
    gc.collect()
    mem = tracemalloc.get_traced_memory()[0] if tracemalloc.is_tracing() else 0
    return Snap(mem, threading.active_count(), handle_count(), len(child_pids()), temp_entries(temp_base))


def assert_bounded(tc, step, *, warm: int = 20, n: int = 200, mem_per_iter: int = 2048, handle_slack: int = 16,
                   thread_slack: int = 0, child_slack: int = 0, temp_slack: int = 0, temp_base: str | None = None,
                   frames: int = 1) -> tuple[Snap, Snap, Snap]:
    """step(i) 반복 구동 누수 판정(위 머리말). 실패하면 tc.fail 로 무엇이 얼마나 늘었는지 적는다. (s1, s2, s3) 를 돌려준다."""
    started = not tracemalloc.is_tracing()
    # 임시 항목은 이 측정 전용 폴더에서 센다 — 이 프로세스의 tempfile.* 을 그 폴더로 돌린다(같은 %TEMP% 를 쓰는 다른 시험
    # 프로세스가 만든 항목에 흔들리지 않게). temp_base 를 주면 그 폴더를 센다. 끝나면 되돌리고 지운다.
    import shutil
    private = None
    saved_tempdir = tempfile.tempdir
    if temp_base is None:
        private = tempfile.mkdtemp(prefix="lm27t_leak_")
        tempfile.tempdir = private
        temp_base = private
    if started:
        tracemalloc.start(frames)
    try:
        i = 0
        for _ in range(warm):
            step(i)
            i += 1
        s1 = snap(temp_base)
        for _ in range(n):
            step(i)
            i += 1
        s2 = snap(temp_base)
        for _ in range(n):
            step(i)
            i += 1
        s3 = snap(temp_base)
    finally:
        if started:
            tracemalloc.stop()
        if private is not None:
            tempfile.tempdir = saved_tempdir
            shutil.rmtree(private, ignore_errors=True)
    probs = []
    # 두 번째 n 번 동안의 증가로 판정한다 — 첫 n 번에 한 번 생기는 것(캐시·풀·지연 생성)은 누수가 아니다.
    # 스레드·자식은 처음보다도 늘면 안 된다(남아 있으면 정리 실패).
    if s3.threads - s2.threads > thread_slack or s3.threads - s1.threads > thread_slack + 1:
        probs.append(f"스레드 {s1.threads}→{s2.threads}→{s3.threads}")
    if s3.children - s1.children > child_slack:
        probs.append(f"자식 프로세스 {s1.children}→{s2.children}→{s3.children}")
    if s3.temp - s2.temp > temp_slack:
        probs.append(f"임시 항목 {s1.temp}→{s2.temp}→{s3.temp}")
    if s3.handles - s2.handles > handle_slack:
        probs.append(f"핸들 {s1.handles}→{s2.handles}→{s3.handles}")
    grow = (s3.mem - s2.mem) / max(1, n)
    if grow > mem_per_iter:
        probs.append(f"메모리 반복당 +{grow:.0f}B(한도 {mem_per_iter}B: {s1.mem}→{s2.mem}→{s3.mem})")
    if probs:
        tc.fail("반복 구동 누수: " + " · ".join(probs))
    return s1, s2, s3
