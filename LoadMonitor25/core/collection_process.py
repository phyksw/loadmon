"""Stream an owned collector's output with a bounded deadline and diagnostics.

No process discovery or application termination: only the Popen child is killed.
The pipe reader polls before reading so an inherited pipe held by another process
cannot keep a reader thread alive after this collector exits.
"""
from __future__ import annotations

import codecs
from collections import deque
import math
import os
import queue
import subprocess
import threading
import time


HEARTBEAT_SECONDS = 15.0
MAX_LINE_CHARS = 4096
TAIL_LINES = 12
POLL_SECONDS = 0.03
DRAIN_SECONDS = 0.3


def _pipe_probe(stream):
    fd = stream.fileno()
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        import msvcrt

        handle = msvcrt.get_osfhandle(fd)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        peek = kernel.PeekNamedPipe
        peek.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
                         ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD),
                         ctypes.POINTER(wintypes.DWORD)]
        peek.restype = wintypes.BOOL

        def probe():
            available = wintypes.DWORD()
            if not peek(handle, None, 0, None, ctypes.byref(available), None):
                code = ctypes.get_last_error()
                if code in {109, 232, 233}:  # broken/closing/disconnected pipe
                    return -1
                raise ctypes.WinError(code)
            return available.value
        return fd, probe

    import select
    return fd, lambda: 4096 if select.select([fd], [], [], 0)[0] else 0


def _read_lines(stream, messages, stop, done):
    pending, discarding = "", False
    decoder = codecs.getincrementaldecoder("utf-8")("replace")

    def put(line):
        if not line:
            return
        while True:
            try:
                messages.put(line, timeout=POLL_SECONDS)
                return
            except queue.Full:
                if stop.is_set():
                    return

    def consume(text):
        nonlocal pending, discarding
        pending += text
        while "\n" in pending:
            line, pending = pending.split("\n", 1)
            if not discarding:
                put(_bounded_line(line.rstrip("\r")))
            discarding = False
        if discarding:
            pending = ""
        elif len(pending) > MAX_LINE_CHARS:
            put(_bounded_line(pending))
            pending, discarding = "", True

    try:
        fd, probe = _pipe_probe(stream)
        while not stop.is_set():
            available = probe()
            if available < 0:
                break
            if not available:
                stop.wait(POLL_SECONDS)
                continue
            data = os.read(fd, min(4096, available))
            if not data:
                break
            consume(decoder.decode(data))
        consume(decoder.decode(b"", final=True))
        if pending and not discarding:
            put(_bounded_line(pending.rstrip("\r")))
    except (OSError, ValueError) as error:
        put(f"[수집] 출력 읽기 실패 ({type(error).__name__})")
    finally:
        done.set()


def _bounded_line(line):
    suffix = " … [긴 로그 줄 일부 생략]"
    return line if len(line) <= MAX_LINE_CHARS else line[:MAX_LINE_CHARS - len(suffix)] + suffix


def run_stream(command, timeout, cwd=None, env=None, creationflags=0, on_line=None):
    """Return {returncode, tail, timed_out}; forward lines while the child runs.

    Heartbeats go to on_line but do not replace useful collector lines in tail.
    OSError from launch and exceptions raised by the callback propagate after
    cleanup. No shell is used. A timeout terminates only the process we started.
    """
    seconds = float(timeout)
    if not math.isfinite(seconds) or seconds < 0:
        raise ValueError("collector timeout must be finite and nonnegative")
    started = time.monotonic()
    process = subprocess.Popen(command, cwd=cwd, env=env, creationflags=creationflags,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=0)
    messages = queue.Queue(maxsize=128)
    stop, done = threading.Event(), threading.Event()
    reader = threading.Thread(target=_read_lines, args=(process.stdout, messages, stop, done),
                              name="lm25-collector-output", daemon=True)
    tail = deque(maxlen=TAIL_LINES)
    timed_out, exit_seen, killed_at = False, None, None
    heartbeat_at = started + HEARTBEAT_SECONDS

    def emit(line):
        tail.append(line)
        if on_line:
            on_line(line)

    try:
        reader.start()
        while True:
            now = time.monotonic()
            running = process.poll() is None
            if running and not timed_out and now >= started + seconds:
                timed_out = True
                killed_at = now
                process.kill()
            if killed_at is not None and now - killed_at >= 1.0:
                break  # A termination that cannot be confirmed must not wait forever.
            if not running:
                exit_seen = exit_seen if exit_seen is not None else now
                if (done.is_set() and messages.empty()) or now - exit_seen >= DRAIN_SECONDS:
                    break
            if running and now >= heartbeat_at:
                if on_line:
                    on_line(f"[수집 진행] 경과 {int(now - started)}초 · 제한 {int(seconds)}초 · 작업 응답 대기")
                heartbeat_at = now + HEARTBEAT_SECONDS
            try:
                emit(messages.get(timeout=POLL_SECONDS))
            except queue.Empty:
                pass
        stop.set()
        reader.join(timeout=1.0)
        while not messages.empty():
            emit(messages.get_nowait())
        return {"returncode": process.returncode if process.returncode is not None else -1,
                "tail": list(tail), "timed_out": timed_out}
    finally:
        stop.set()
        if process.poll() is None:
            process.kill()
            try:
                process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                pass
        if reader.ident is not None:
            reader.join(timeout=1.0)
        process.stdout.close()
