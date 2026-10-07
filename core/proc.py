# -*- coding: utf-8 -*-
r"""core\proc.py — 수집 단계 실행기(LM28 P6·F-23·W1-06·W1-07): 자식을 Job Object 로 감싸 트리째 정리한다.

  run_step(cmd, timeout, name, clock) → (rc, tail, status)
    · Popen 직후 Job(KILL_ON_JOB_CLOSE | BREAKAWAY_OK)에 넣는다. 시간 초과·중지면 Job 을 끝내고 핸들을 닫는다 —
      자식뿐 아니라 손자(copilot_auto·python 등)까지 함께 끝난다(LM24 는 직계 자식만 죽여 손자가 남았다 — W1-07).
      taskkill 은 띄우지 않는다(이 PC 는 끝난 프로세스가 커널에 남는다 — 프로세스 하나라도 아낀다).
    · BREAKAWAY_OK 라서 CREATE_BREAKAWAY_FROM_JOB 로 띄운 손자(전용 Edge — copilot_auto._popen_edge)는 Job 이 닫혀도 산다
      (1실행 1기동 — Edge 는 owner.json + close_own_edge 가 닫는다).
    · 정상 종료 뒤에도 Job 을 닫는다 — 끝난 자식이 남긴 고아 손자가 다음 단계와 충돌하지 않게.
    · 출력은 마지막 TAIL_MAX 줄만 모은다. 60초마다 '진행 중' 줄을 낸다 — 화면(UI)의 정체 감시(15분 무출력)가
      긴 수집(팀즈 웹·Copilot)을 죽음으로 오진하지 않게(W1-06).
    · status: ok(스스로 끝남) · timeout(시간 초과로 끝냄) · stopped(stop 이벤트로 끝냄) · error(띄우지 못함).
      rc: 자식 종료 코드 · 시간 초과/중지 -1 · 실행 실패 -2.
  attach(p) / release(job) / kill_tree(pid) — 감시기(core\watch.watch_child)가 쓰는 종료 수단을 Job 으로 바꿀 때 쓴다.
윈도가 아니거나 Job 을 만들지 못하면(정책) 직계 자식만 끝낸다(LM24 와 같다).
"""
import collections
import os
import queue
import subprocess
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NO_WIN = 0x08000000
CREATE_BREAKAWAY_FROM_JOB = 0x01000000
TAIL_MAX = 60                  # 모아 두는 출력 줄 수(LMSTATUS 줄 + 사람용 요약이 들어가고 남는다)
BEAT_SEC = 60                  # 진행 줄 간격(초)
_JOB_KILL_ON_CLOSE = 0x2000    # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
_JOB_BREAKAWAY_OK = 0x800      # JOB_OBJECT_LIMIT_BREAKAWAY_OK
_JOBS = {}                     # pid → Job 핸들(kill_tree 가 찾는다)
_K32 = {"k": None}


def _k32():
    """kernel32(전용 인스턴스 — argtypes 를 바꿔도 다른 모듈의 ctypes.windll 에 번지지 않는다). 윈도가 아니면 None."""
    if os.name != "nt":
        return None
    if _K32["k"] is not None:
        return _K32["k"]
    import ctypes
    from ctypes import wintypes
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
    k.CreateJobObjectW.restype = wintypes.HANDLE
    k.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    k.SetInformationJobObject.restype = wintypes.BOOL
    k.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    k.AssignProcessToJobObject.restype = wintypes.BOOL
    k.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    k.TerminateJobObject.restype = wintypes.BOOL
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    k.CloseHandle.restype = wintypes.BOOL
    k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k.OpenProcess.restype = wintypes.HANDLE
    k.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    k.TerminateProcess.restype = wintypes.BOOL
    _K32["k"] = k
    return k


def _limit_info():
    """JOBOBJECT_EXTENDED_LIMIT_INFORMATION — KILL_ON_JOB_CLOSE | BREAKAWAY_OK"""
    import ctypes
    from ctypes import wintypes

    class _Basic(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]

    class _Io(ctypes.Structure):
        _fields_ = [(n, ctypes.c_uint64) for n in ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                                                    "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class _Ext(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", _Basic), ("IoInfo", _Io), ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t)]

    info = _Ext()
    info.BasicLimitInformation.LimitFlags = _JOB_KILL_ON_CLOSE | _JOB_BREAKAWAY_OK
    return info


def attach(p):
    """방금 띄운 Popen 을 새 Job 에 넣는다 → Job 핸들(int) | None(윈도 아님·정책 거부 — 그때는 직계 자식만 다룬다)."""
    k = _k32()
    if k is None or p is None:
        return None
    import ctypes
    try:
        job = k.CreateJobObjectW(None, None)
        if not job:
            return None
        info = _limit_info()
        if not k.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)) \
                or not k.AssignProcessToJobObject(job, int(p._handle)):
            k.CloseHandle(job)
            return None
    except (OSError, AttributeError, ValueError, TypeError):
        return None
    _JOBS[p.pid] = job
    return job


def release(job, pid=None, kill=False):
    """Job 을 닫는다 — KILL_ON_JOB_CLOSE 라 안에 남은 프로세스(고아 손자 포함)가 끝난다. Job 에서 이탈한 Edge 는 산다.
    kill=True 면 닫기 전에 TerminateJobObject 로 먼저 끝낸다(시간 초과·중지)."""
    k = _k32()
    if not job:
        return
    # 한 번만 닫는다 — 감시기가 kill_tree 로 이미 닫은 Job 을 호출측이 다시 닫으면 남의 핸들을 닫을 수 있다
    keys = [q for q, j in _JOBS.items() if j == job and (pid is None or q == pid)]
    if not keys:
        return
    for q in keys:
        _JOBS.pop(q, None)
    if k is None:
        return
    try:
        if kill:
            k.TerminateJobObject(job, 1)
        k.CloseHandle(job)
    except OSError:
        pass


def kill_tree(pid):
    """감시기용 종료 — 그 pid 의 Job 이 있으면 트리째(Job), 없으면 그 프로세스만(TerminateProcess). taskkill 은 쓰지 않는다."""
    job = _JOBS.get(pid)
    if job:
        release(job, pid, kill=True)
        return
    k = _k32()
    if k is None:
        try:
            os.kill(pid, 9)
        except OSError:
            pass
        return
    try:
        h = k.OpenProcess(0x0001, False, int(pid))          # PROCESS_TERMINATE
        if h:
            k.TerminateProcess(h, 1)
            k.CloseHandle(h)
    except (OSError, ValueError):
        pass


def _beat_line(name, sec):
    return f"   … {name or '단계'} 진행 중 (경과 {int(sec // 60)}분 {int(sec % 60)}초)"


def run_step(cmd, timeout, name="", clock=None, *, beat=BEAT_SEC, on_line=None, cwd=None, env=None,
             stop=None, poll=1.0):
    """수집기 한 단계 → (rc, tail, status). 위 머리말 참고.
    clock: 시계 주입(시험 — 기본 time.monotonic). 시간 초과와 진행 줄 모두 이 시계로 잰다.
    on_line: 진행 줄을 받을 함수(기본 print). stop: threading.Event — 서면 Job 째 끝낸다."""
    clock = clock or time.monotonic
    say = on_line or (lambda s: print(s, flush=True))
    env = env if env is not None else dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
    tail = collections.deque(maxlen=TAIL_MAX)
    try:
        p = subprocess.Popen(cmd, cwd=cwd or ROOT, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, creationflags=NO_WIN if os.name == "nt" else 0)
    except OSError as e:
        return -2, [f"실행 실패: {e}"[:200]], "error"
    job = attach(p)
    q = queue.Queue()

    def _rd():
        try:
            for raw in p.stdout:
                q.put(raw.decode("utf-8", "replace").rstrip("\r\n"))
        except (OSError, ValueError):
            pass
        finally:
            q.put(None)

    th = threading.Thread(target=_rd, daemon=True)
    th.start()
    t0 = last_beat = clock()
    status, eof = "ok", False
    while True:
        try:
            ln = q.get(timeout=poll)
        except queue.Empty:
            ln = ""
        if ln is None:
            eof = True
            break
        if ln.strip():
            tail.append(ln.strip())
        now = clock()                # 줄이 쉬지 않고 나와도 시간 초과·진행 줄을 본다
        if p.poll() is not None:
            break
        if stop is not None and stop.is_set():
            status = "stopped"
            break
        if timeout and now - t0 > timeout:
            status = "timeout"
            break
        if beat and now - last_beat >= beat:
            last_beat = now
            say(_beat_line(name, now - t0))
    if status != "ok":
        if job:
            release(job, p.pid, kill=True)
            job = None
        else:
            try:
                p.kill()
            except OSError:
                pass
    try:
        rc = p.wait(timeout=30)
    except subprocess.TimeoutExpired:
        rc = None
    if job:
        release(job, p.pid)          # 정상 종료여도 닫는다 — 남은 고아 손자 정리(이탈한 Edge 는 산다)
    # 남은 출력 — 자식이 끝났으면 파이프는 곧 닫힌다(누가 핸들을 쥐고 있으면 3초만 기다린다)
    deadline = time.monotonic() + 3.0
    while not eof and time.monotonic() < deadline:
        try:
            ln = q.get(timeout=0.2)
        except queue.Empty:
            continue
        if ln is None:
            break
        if ln.strip():
            tail.append(ln.strip())
    try:
        p.stdout.close()
    except OSError:
        pass
    if status == "timeout":
        tail.append(f"시간 초과({timeout}s) — 트리째 정리하고 건너뜀")
        return -1, list(tail), status
    if status == "stopped":
        tail.append("중지 — 트리째 정리")
        return -1, list(tail), status
    return (rc if rc is not None else -1), list(tail), status
