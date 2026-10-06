# -*- coding: utf-8 -*-
r"""자식 프로세스 실행·감시·트리 종료(계약 §2.1·§8.7·§9.1, C §8.4).

규칙:
  · 자식은 창 없이(``CREATE_NO_WINDOW``) 띄운다. 보이는 콘솔이 필요한 도우미만 ``new_console=True``.
  · 종료는 ``kill_tree(pid)`` = ``taskkill /T /F /PID`` 하나. ``os.kill`` 은 쓰지 않는다(L-16) —
    자식만 죽이면 그 아래 드라이버·PowerShell·Edge 가 남아 다음 실행을 막는다(LM24 core/watch.py 실측).
  · 시간 초과는 ``run_child(…, timeout_s=)`` 가 kill_tree 로 끝내고 ``timed_out=True`` 를 돌려준다
    (수집 단계는 이를 ``transport_fail`` + R-TRANSPORT 로 번역한다 — 계약 §8.1).
  · stdin 을 주지 않으면 ``DEVNULL`` — 자식이 콘솔 입력을 기다리며 멈추지 않는다(수집기는 stdin 이 없으면 기본값으로 돈다, §7.3).
  · 생존 확인 ``pid_alive`` 는 ctypes ``OpenProcess`` + ``WaitForSingleObject`` 로 한다(신호를 보내 살아 있는지 떠보는 방식은 쓰지 않는다).

이 모듈은 에이전트 bin 사본(계약 §1.3)에도 들어가므로 표준 라이브러리만 쓴다.
"""
import collections
import os
import subprocess
import threading
import time
from dataclasses import dataclass

CREATE_NO_WINDOW = 0x08000000
CREATE_NEW_CONSOLE = 0x00000010
PIPE = subprocess.PIPE
DEVNULL = subprocess.DEVNULL
STDOUT = subprocess.STDOUT
STDERR_TAIL = "tail"            # spawn(stderr=STDERR_TAIL): 파이프 + 배수 스레드가 마지막 줄만 보관(교착 방지)
TAIL_LINES = 200
KILL_TIMEOUT_S = 30             # taskkill 자체의 시간 제한
GONE_WAIT_S = 5.0               # kill_tree 뒤 대상 pid 가 사라지기를 기다리는 최대 시간

_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_SYNCHRONIZE = 0x00100000
_WAIT_TIMEOUT = 0x102
_ERROR_ACCESS_DENIED = 5


@dataclass
class ChildResult:
    """``run_child`` 결과. ``rc`` 는 시간 초과로 끊었으면 None."""
    rc: int | None
    stdout: bytes
    stderr: bytes
    timed_out: bool
    elapsed_s: float
    pid: int

    def out_text(self) -> str:
        return self.stdout.decode("utf-8", errors="replace")

    def err_text(self) -> str:
        return self.stderr.decode("utf-8", errors="replace")


def _flags(new_console=False) -> int:
    if os.name != "nt":
        return 0
    return CREATE_NEW_CONSOLE if new_console else CREATE_NO_WINDOW


def _merge_env(env):
    """``env`` 를 현재 환경 위에 덮는다. 값이 None 인 키는 지운다(대소문자 무시 — Windows 환경 변수 규칙)."""
    if env is None:
        return None
    out = dict(os.environ)
    for k, v in env.items():
        if v is None:
            for key in [x for x in out if x.upper() == str(k).upper()]:
                del out[key]
        else:
            out[str(k)] = str(v)
    return out


def _system_exe(name: str) -> str:
    """System32 의 실행 파일 절대 경로(PATH 조작에 흔들리지 않게). 시스템 경로이지 데이터 경로가 아니다."""
    sysroot = os.environ.get("SystemRoot") or os.environ.get("windir") or "C:\\Windows"
    return os.path.join(sysroot, "System32", name)


def _k32():
    import ctypes
    from ctypes import wintypes
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.OpenProcess.restype = wintypes.HANDLE
    k.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    k.WaitForSingleObject.restype = wintypes.DWORD
    k.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    k.CloseHandle.restype = wintypes.BOOL
    k.CloseHandle.argtypes = (wintypes.HANDLE,)
    return k, ctypes


def pid_alive(pid: int) -> bool:
    """그 pid 의 프로세스가 아직 살아 있는가(ctypes). 권한이 없어 열지 못하면 '있음'으로 본다."""
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
    if os.name != "nt":
        raise NotImplementedError("pid_alive: Windows 전용")
    k, ctypes = _k32()
    h = k.OpenProcess(_SYNCHRONIZE | _PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return ctypes.get_last_error() == _ERROR_ACCESS_DENIED
    try:
        return k.WaitForSingleObject(h, 0) == _WAIT_TIMEOUT
    finally:
        k.CloseHandle(h)


def kill_tree(pid: int) -> bool:
    """프로세스와 자손 전부를 ``taskkill /T /F /PID`` 로 끝낸다(계약 §8.7). 반환: 대상 pid 가 사라졌으면 True.
    자기 자신의 pid 는 거부한다(ValueError)."""
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        raise ValueError("kill_tree: 양의 정수 pid 가 필요합니다")
    if pid == os.getpid():
        raise ValueError("kill_tree: 자기 자신은 대상이 아닙니다")
    try:
        subprocess.run([_system_exe("taskkill.exe"), "/T", "/F", "/PID", str(pid)],
                       stdin=DEVNULL, stdout=DEVNULL, stderr=DEVNULL,
                       timeout=KILL_TIMEOUT_S, creationflags=_flags(False), check=False)
    except (OSError, subprocess.SubprocessError):
        pass                    # 아래 생존 확인이 결과를 정한다(taskkill 실패를 성공으로 보고하지 않는다)
    deadline = time.monotonic() + GONE_WAIT_S
    while pid_alive(pid):
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.05)
    return True


CLOSE_WAIT_S = 2.0              # Child.close 가 읽기 스트림 하나를 닫으며 기다리는 최대 시간(막히면 데몬 스레드에 맡긴다)


def _close_quiet(st) -> None:
    if st is None:
        return
    try:
        st.close()
    except (OSError, ValueError):
        pass


def _close_bounded(st, wait_s: float) -> None:
    """다른 스레드가 읽는 중일 수 있는 스트림을 데몬 스레드에서 닫고 ``wait_s`` 까지만 기다린다(그 뒤는 그 스레드가 마저 닫는다)."""
    t = threading.Thread(target=_close_quiet, args=(st,), name="lm27-close", daemon=True)
    t.start()
    t.join(wait_s)


class Child:
    """``spawn`` 결과 — ``subprocess.Popen`` 의 얇은 껍데기. 감시기(lm27.collect.watch)가 stdout 줄을 읽는다."""

    def __init__(self, popen, argv):
        self.popen = popen
        self.argv = list(argv)
        self.started = time.monotonic()
        self.stderr_tail = collections.deque(maxlen=TAIL_LINES)
        self._drain = None

    @property
    def pid(self) -> int:
        return self.popen.pid

    @property
    def stdin(self):
        return self.popen.stdin

    @property
    def stdout(self):
        return self.popen.stdout

    @property
    def stderr(self):
        return self.popen.stderr

    @property
    def returncode(self):
        return self.popen.returncode

    def poll(self):
        return self.popen.poll()

    def wait(self, timeout=None):
        return self.popen.wait(timeout=timeout)

    def alive(self) -> bool:
        return self.popen.poll() is None

    def iter_lines(self):
        """stdout 을 줄 단위(UTF-8, 깨진 바이트는 대체 문자)로 읽는다. 끝나면 멈춘다."""
        out = self.popen.stdout
        if out is None:
            return
        for raw in iter(out.readline, b""):
            yield raw.decode("utf-8", errors="replace").rstrip("\r\n")

    def kill_tree(self) -> bool:
        if not self.alive():
            return True
        gone = kill_tree(self.pid)
        try:
            self.popen.wait(timeout=10)
        except subprocess.TimeoutExpired:
            return False
        return gone

    def _start_drain(self):
        err = self.popen.stderr

        def _rd():
            try:
                for raw in iter(err.readline, b""):
                    self.stderr_tail.append(raw.decode("utf-8", errors="replace").rstrip("\r\n"))
            except (OSError, ValueError):
                pass
            finally:
                _close_quiet(err)                   # EOF(손주까지 핸들을 놓음)에서 배수 스레드가 스스로 닫는다

        self._drain = threading.Thread(target=_rd, name="lm27-stderr-drain", daemon=True)
        self._drain.start()

    def close(self):
        """표준 스트림을 닫는다 — 막히지 않는다. 다른 스레드가 ``readline`` 에서 막힌 읽기 파이프(손주가 핸들을 쥐고 있음)를 닫으면
        BufferedReader 잠금에 걸려 호출자가 손주 수명만큼 멈춘다(W2 C21·L13 과 같은 모양 — 통합). 그래서 ① 살아 있는 배수 스레드의
        stderr 는 그 스레드가 EOF 에서 닫게 두고 ② 읽기 스트림 닫기는 데몬 스레드에서 ``CLOSE_WAIT_S`` 까지만 기다린다."""
        _close_quiet(self.popen.stdin)
        for st in (self.popen.stdout, self.popen.stderr):
            if st is None:
                continue
            if st is self.popen.stderr and self._drain is not None and self._drain.is_alive():
                continue
            _close_bounded(st, CLOSE_WAIT_S)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        if self.alive():
            self.kill_tree()
        self.close()
        return False


def spawn(argv, *, stdin=DEVNULL, stdout=PIPE, stderr=STDERR_TAIL, env=None, cwd=None,
          new_console=False) -> Child:
    """자식을 띄우고 기다리지 않는다. 기본: stdin 없음 · stdout 파이프(바이트) · stderr 는 배수 스레드가 꼬리만 보관.
    ``env`` 는 현재 환경 위에 덮어쓴다(None 값 = 지움). ``new_console=True`` 면 보이는 콘솔 창(도우미 전용)."""
    tail = stderr == STDERR_TAIL
    p = subprocess.Popen(list(argv), stdin=stdin, stdout=stdout, stderr=PIPE if tail else stderr,
                         env=_merge_env(env), cwd=cwd, creationflags=_flags(new_console))
    ch = Child(p, argv)
    if tail:
        ch._start_drain()
    return ch


DRAIN_S = 2.0                   # 자식이 끝난 뒤 파이프 꼬리를 더 읽는 최대 시간(손주가 핸들을 쥐고 있어도 여기서 끝)
KILL_DRAIN_S = 5.0              # 시간 초과로 끊은 뒤 남은 출력을 읽는 최대 시간

_PROCESS_SET_QUOTA = 0x0100
_PROCESS_TERMINATE = 0x0001


class _Job:
    """자식을 Job Object 에 넣어 둔다 — 시간 초과 때 부모가 이미 끝나 ``taskkill /T`` 가 닿지 않는 고아 손주까지
    한 번에 끝낸다(``terminate``). 정상 종료 때는 그냥 닫는다(KILL_ON_JOB_CLOSE 를 켜지 않으므로 의도적으로 남긴
    자손 — 예: 수집기가 띄운 전용 Edge — 는 죽지 않는다). Job 을 못 만들면(권한·중첩 제한) 없는 것으로 동작한다."""

    def __init__(self, pid):
        self.h = None
        if os.name != "nt":
            return
        try:
            import ctypes
            from ctypes import wintypes
            k = ctypes.WinDLL("kernel32", use_last_error=True)
            k.CreateJobObjectW.restype = wintypes.HANDLE
            k.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
            k.AssignProcessToJobObject.restype = wintypes.BOOL
            k.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
            k.TerminateJobObject.restype = wintypes.BOOL
            k.TerminateJobObject.argtypes = (wintypes.HANDLE, wintypes.UINT)
            k.OpenProcess.restype = wintypes.HANDLE
            k.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
            k.CloseHandle.restype = wintypes.BOOL
            k.CloseHandle.argtypes = (wintypes.HANDLE,)
            self.k = k
            job = k.CreateJobObjectW(None, None)
            if not job:
                return
            ph = k.OpenProcess(_PROCESS_SET_QUOTA | _PROCESS_TERMINATE, False, pid)
            ok = bool(ph) and bool(k.AssignProcessToJobObject(job, ph))
            if ph:
                k.CloseHandle(ph)
            if ok:
                self.h = job
            else:
                k.CloseHandle(job)
        except (OSError, AttributeError):
            self.h = None

    def terminate(self):
        if self.h:
            self.k.TerminateJobObject(self.h, 1)

    def close(self):
        if self.h:
            self.k.CloseHandle(self.h)
            self.h = None


def _reader(stream, sink):
    """파이프를 끝까지 읽어 sink(list)에 담는 데몬 스레드. 읽기 끝(EOF)이면 스레드가 끝나고 파이프를 닫는다
    (run_child 가 기다림을 끝낸 뒤에도 손자가 쥔 파이프는 손자가 끝날 때 여기서 닫힌다)."""
    def run():
        try:
            while True:
                b = stream.read1(65536) if hasattr(stream, "read1") else stream.read(65536)
                if not b:
                    break
                sink.append(b)
        except (OSError, ValueError):
            pass
        finally:
            try:
                stream.close()
            except OSError:
                pass
    t = threading.Thread(target=run, name="lm27-run-child-pipe", daemon=True)
    t.start()
    return t


def _writer(stream, data):
    def run():
        try:
            stream.write(data)
        except (OSError, ValueError):
            pass                # 자식이 stdin 을 다 읽지 않고 끝남 — 결과는 rc 로 판단
        finally:
            try:
                stream.close()
            except OSError:
                pass
    t = threading.Thread(target=run, name="lm27-run-child-stdin", daemon=True)
    t.start()
    return t


def run_child(argv, *, timeout_s, stdin=None, env=None, cwd=None) -> ChildResult:
    """자식을 실행하고 끝날 때까지(최대 ``timeout_s`` 초) 기다린다. stdout·stderr 는 바이트로 모은다.
    ``stdin`` = bytes·str(UTF-8)·None(DEVNULL). 시간 초과면 kill_tree(+ Job Object)로 트리 전체를 끝내고
    ``rc=None, timed_out=True``.

    대기 상한: ``timeout_s`` + ``KILL_DRAIN_S``(+ taskkill 시간) — 무한 대기 없음. 판정은 **자식 프로세스의 종료**로 한다
    (파이프 EOF 가 아니다): 자식이 띄운 손주가 상속받은 stdout 을 쥐고 오래 살아도, 자식이 제때 끝났으면 그 rc 를 그대로
    돌려주고(``timed_out=False``) 파이프 꼬리는 ``DRAIN_S`` 만 더 읽는다. 그런 손주는 끝내지 않는다(의도한 자손일 수 있다)."""
    if timeout_s is None or timeout_s <= 0:
        raise ValueError("run_child: timeout_s 는 양수여야 합니다(무한 대기 금지)")
    data = stdin.encode("utf-8") if isinstance(stdin, str) else stdin
    t0 = time.monotonic()
    p = subprocess.Popen(list(argv), stdin=PIPE if data is not None else DEVNULL, stdout=PIPE, stderr=PIPE,
                         env=_merge_env(env), cwd=cwd, creationflags=_flags(False))
    job = _Job(p.pid)
    out, err = [], []
    readers = [_reader(p.stdout, out), _reader(p.stderr, err)]
    if data is not None:
        _writer(p.stdin, data)
    timed_out = False
    try:
        try:
            p.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            timed_out = True
            kill_tree(p.pid)
            job.terminate()                  # 부모가 먼저 끝나 /T 가 닿지 않는 고아 손주까지
            try:
                p.wait(timeout=KILL_DRAIN_S)
            except subprocess.TimeoutExpired:
                p.kill()                     # TerminateProcess(자식만) — os.kill 아님
                try:
                    p.wait(timeout=KILL_DRAIN_S)
                except subprocess.TimeoutExpired:
                    pass
        deadline = time.monotonic() + (KILL_DRAIN_S if timed_out else DRAIN_S)
        for t in readers:
            t.join(max(0.0, deadline - time.monotonic()))
        for t, st in zip(readers, (p.stdout, p.stderr), strict=True):
            if not t.is_alive():             # 다 읽은 파이프만 닫는다(손자가 쥔 파이프는 읽기 스레드가 끝날 때 닫힌다)
                st.close()
    finally:
        job.close()
    rc = None if timed_out else p.returncode
    return ChildResult(rc, b"".join(list(out)), b"".join(list(err)), timed_out, time.monotonic() - t0, p.pid)
