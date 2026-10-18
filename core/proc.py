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
  kill_all() / run_within(fn, sec) / on_console_close(fn) — 콘솔 창(bat)을 닫을 때의 빠른 정리(ui\app.py·run.py main 이 건다):
    Job 을 모두 끝내고, 남는 전용 Edge 를 몇 초 안에 닫는다(윈도가 처리기에 주는 시간이 짧다).
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
RESUME_GAP = 30.0              # 수집기 감시 루프가 이만큼(초) 넘게 늦게 돌면 PC 가 잠들었다 깬 것으로 본다(core\watch 와 같다)
_ES_CONTINUOUS, _ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
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


def kill_all():
    """추적 중인 Job 을 모두 끝낸다 → 끝낸 Job 수. 콘솔 창 닫기 처리기가 쓴다(윈도가 몇 초만 준다 — Job 끝내기는 즉시다).
    Job 에 넣지 않은 자식(팀 서버 teamserver.py — 팀 전체가 쓴다)은 여기 없으므로 건드리지 않는다."""
    jobs = list(dict.fromkeys(list(_JOBS.values())))
    for job in jobs:
        release(job, None, kill=True)
    return len(jobs)


def run_within(fn, sec):
    """fn 을 데몬 스레드로 돌리고 sec 초까지만 기다린다 → True(그 안에 끝남)|False. 예외는 삼킨다.
    창 닫기 처리기는 몇 초 안에 돌아가야 한다 — 늦은 정리(CDP 응답 대기 등)가 그 시간을 넘겨 처리기째 잘리지 않게."""
    done = threading.Event()

    def _go():
        try:
            fn()
        except Exception:  # noqa: BLE001 - 정리 실패가 처리기를 막지 않는다
            pass
        finally:
            done.set()

    threading.Thread(target=_go, daemon=True, name="lm-fast-cleanup").start()
    return done.wait(sec)


# 콘솔 창 닫기(LM28) — bat 창을 X 로 닫으면 윈도가 CTRL_CLOSE_EVENT 를 보내고 처리기가 돌아온 뒤(최대 약 5초) 프로세스를 끝낸다.
# Job 안의 자식은 함께 끝나지만 Job 에서 이탈한 전용 Edge 는 남는다 — 그 몇 초 안에 Edge 를 닫을 기회다.
# Ctrl+C·Ctrl+Break 는 다음 처리기(파이썬의 KeyboardInterrupt)로 넘긴다. ctypes 콜백은 모듈에 붙잡아 둔다(GC 되면 처리기가 죽는다).
CTRL_CLOSE_EVENTS = (2, 5, 6)      # CTRL_CLOSE_EVENT · CTRL_LOGOFF_EVENT · CTRL_SHUTDOWN_EVENT
_CTRL = {"fn": None, "cb": None}


def console_event(ev):
    """처리기 본문(시험이 직접 부른다) → 1(처리함 — 곧 끝난다) | 0(다음 처리기로). 정리 함수의 예외는 삼킨다."""
    if ev not in CTRL_CLOSE_EVENTS:
        return 0
    fn = _CTRL["fn"]
    try:
        if fn is not None:
            fn(ev)
    except BaseException:  # noqa: BLE001 - 처리기는 절대 예외를 내지 않는다(윈도 스레드 위에서 돈다)
        pass
    return 1


def on_console_close(fn):
    """콘솔 창 닫기·로그오프·윈도 종료 때 fn(event) 를 부르게 건다 → True(걸었다)|False(윈도 아님·콘솔 없음·실패).
    두 번 불러도 처리기는 하나다(fn 만 바뀐다). 예외를 내지 않는다."""
    if os.name != "nt":
        return False
    if _CTRL["cb"] is not None:
        _CTRL["fn"] = fn
        return True
    try:
        import ctypes
        from ctypes import wintypes
        k = _k32()
        k.GetConsoleWindow.argtypes = []
        k.GetConsoleWindow.restype = wintypes.HWND
        if not k.GetConsoleWindow():
            return False                 # 창 없는 자식(화면이 NO_WIN 으로 띄운 run.py 등) — 닫힐 창이 없다
        proto = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)
        cb = proto(console_event)
        k.SetConsoleCtrlHandler.argtypes = [proto, wintypes.BOOL]
        k.SetConsoleCtrlHandler.restype = wintypes.BOOL
        if not k.SetConsoleCtrlHandler(cb, True):
            return False
    except Exception:  # noqa: BLE001 - 처리기를 못 걸어도 실행은 계속한다(예전 동작)
        return False
    _CTRL.update(fn=fn, cb=cb)
    return True


def _beat_line(name, sec):
    return f"   … {name or '단계'} 진행 중 (경과 {int(sec // 60)}분 {int(sec % 60)}초)"


# 프로그램(PowerShell 등)이 켜지는 순간 Windows 가 초기화에 실패한 종료 코드(STATUS_DLL_INIT_FAILED) — 부호 있는/없는 꼴.
# 현장(2026-10-14 개발 PC): 수집기 PowerShell 이 0xc0000142 로 못 켜지며 '응용 프로그램을 제대로 시작하지 못했습니다' 창을
# 띄우고 [확인]을 누를 때까지 멈춰, 단계마다 시간 초과(300·240초)까지 기다렸다. quiet_errors() 로 그 창을 막으면(자식이
# 오류 모드를 물려받는다) 자식은 곧바로 이 코드로 끝나고, run_step 이 잠깐 쉬었다 START_RETRY 번 다시 띄운다.
START_FAIL_RC = (0xC0000142, 0xC0000142 - (1 << 32))
START_FAIL_SEC = 30            # 이 안에 이 코드로 끝났을 때만 '켜지다 실패' 로 본다(일하다 끝난 것과 가른다)
START_RETRY = 2                # 다시 띄우는 횟수
START_WAIT = (3.0, 8.0)        # 다시 띄우기 전 쉬는 초(차례대로)
_sleep = time.sleep            # 시험이 대기를 0 으로 바꿀 수 있게
_ERRMODE = {"set": False}
_SEM = 0x0001 | 0x0002 | 0x8000   # SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX | SEM_NOOPENFILEERRORBOX


def quiet_errors():
    """이 프로세스(와 앞으로 띄울 자식 — 오류 모드는 물려받는다)에서 Windows 의 '응용 프로그램 오류' 창을 띄우지 않는다.
    창이 뜨면 숨은 수집기가 사람이 [확인]을 누를 때까지 멈추고 화면에 오류 창이 쌓인다. 한 번만 걸고, 실패는 삼킨다
    → 걸었나(윈도가 아니면 False)."""
    if _ERRMODE["set"]:
        return True
    if os.name != "nt":
        return False
    try:
        import ctypes
        k = ctypes.WinDLL("kernel32")
        prev = k.SetErrorMode(_SEM)
        k.SetErrorMode(prev | _SEM)        # 이미 걸려 있던 다른 깃발은 지킨다
        _ERRMODE["set"] = True
    except Exception:  # noqa: BLE001 - 오류 창 막기는 덤이다 — 실패해도 실행은 계속
        return False
    return True


def keep_awake(on=True):
    """LM28(2026-10-18) — 분석이 도는 동안 PC 가 절전(잠자기)에 들어가지 않게 한다(on) · 놓는다(on=False). 화면 꺼짐·화면 보호기·잠금은
    그대로 된다(ES_DISPLAY_REQUIRED 는 쓰지 않는다). 부른 스레드 기준이고, 프로세스가 끝나면 윈도가 저절로 놓는다. 관리자 권한 없음 ·
    프로세스를 띄우지 않는다(ctypes). 제보: "화면보호기로 꺼지는 경우가 있다" — 화면 보호기 뒤 PC 가 절전에 들어가면 깨는 순간 감시가
    분석을 끊었다. → 걸었나(윈도가 아니거나 실패면 False)."""
    if os.name != "nt":
        return False
    try:
        import ctypes
        k = ctypes.WinDLL("kernel32")
        k.SetThreadExecutionState.restype = ctypes.c_uint32
        k.SetThreadExecutionState.argtypes = (ctypes.c_uint32,)
        flags = _ES_CONTINUOUS | (_ES_SYSTEM_REQUIRED if on else 0)
        return bool(k.SetThreadExecutionState(flags))
    except Exception:  # noqa: BLE001 - 절전 막기는 덤이다 — 실패해도 실행은 계속
        return False


def run_step(cmd, timeout, name="", clock=None, *, beat=BEAT_SEC, on_line=None, cwd=None, env=None,
             stop=None, poll=1.0):
    """수집기 한 단계 → (rc, tail, status). 위 머리말 참고.
    clock: 시계 주입(시험 — 기본 time.monotonic). 시간 초과와 진행 줄 모두 이 시계로 잰다.
    on_line: 진행 줄을 받을 함수(기본 print). stop: threading.Event — 서면 Job 째 끝낸다.
    자식이 켜지는 순간 실패하면(START_FAIL_RC · START_FAIL_SEC 안) 오류 창 없이 START_RETRY 번 다시 띄운다. 그래도 같으면 그
    종료 코드와 사람용 한 줄을 돌려준다(collect_status 가 R-STARTFAIL 로 적는다)."""
    quiet_errors()
    clock = clock or time.monotonic
    say = on_line or (lambda s: print(s, flush=True))
    tries = 0
    while True:
        t0 = clock()
        rc, tail, status = _run_step_once(cmd, timeout, name, clock, beat=beat, on_line=on_line, cwd=cwd, env=env,
                                          stop=stop, poll=poll)
        if not (status == "ok" and rc in START_FAIL_RC and clock() - t0 < START_FAIL_SEC):
            return rc, tail, status
        if tries >= START_RETRY or (stop is not None and stop.is_set()):
            tail.append("Windows 가 이 단계의 프로그램(PowerShell 등)을 시작하지 못했습니다(0xc0000142) — "
                        f"{tries + 1}번 모두 실패. 보안 프로그램·Windows 자원 문제가 의심됩니다 — PC 를 다시 시작한 뒤 실행하세요")
            return rc, tail, status
        wait = START_WAIT[min(tries, len(START_WAIT) - 1)]
        tries += 1
        say(f"   [!] {name or '단계'}: Windows 가 프로그램을 시작하지 못했습니다(0xc0000142) — "
            f"{wait:.0f}초 뒤 다시 띄웁니다({tries}/{START_RETRY})")
        _sleep(wait)


def _run_step_once(cmd, timeout, name="", clock=None, *, beat=BEAT_SEC, on_line=None, cwd=None, env=None,
                   stop=None, poll=1.0):
    """run_step 의 한 번 실행(다시 띄우기 없음) → (rc, tail, status)."""
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
    t0 = last_beat = tick = clock()
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
        # LM28(2026-10-18): PC 가 잠들었다 깼다(루프가 RESUME_GAP 넘게 늦게 돎) — 그 시간은 이 수집기의 시간 초과로 세지 않는다
        # (화면 보호기 뒤 절전에서 깨는 순간 돌던 수집기가 '시간 초과'로 끊기던 것). 시계는 절전 중에도 흐른다(GetTickCount64).
        if now - tick > poll + RESUME_GAP:
            t0 += now - tick - poll
            last_beat += now - tick - poll
        tick = now
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
