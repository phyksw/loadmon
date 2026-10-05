# -*- coding: utf-8 -*-
r"""L0 세션(B §4) — Edge 탐색·정책 확인·기동·포트·소유 확인·프로필 잠금·탭 소유·신원·로그인 대기·모델·업무 모드.

역할 ``bridge``(Copilot)·``owa``·``teams_web`` 은 **같은 프로필·같은 포트 범위·같은 잠금**을 쓴다(B §4.5 '역할 공용 한 벌',
관문 G-B12). 웹 수집기는 Edge 인자·프로필·포트를 따로 두지 않고 ``EdgeSession.open(role=…)`` 만 부른다.

    with EdgeSession.open("bridge", run_id) as sess:     # 잠금 → 포트 → 기동/재사용 → 자기 탭 → ensure_ready
        if sess.state != "ready": …                      # 실패는 예외가 아니라 단계 문자열(B §5.8)
    with EdgeSession.open("owa", run_id) as sess:        # 웹 수집 역할: 빈 탭으로 붙은 뒤
        st = sess.goto(owa_url)                          # 이동 + 로드·로그인 대기(BR-LOGIN 안내 + 5초 폴링)
    # __exit__: 우리가 띄운 Edge 이고 closeOnExit 면 Browser.close(5초 안에 안 닫혀도 강제 종료하지 않음),
    #           아니면 자기 탭만 닫는다. 잠금 해제. 남의 탭은 닫지도 읽지도 않는다(B13).

허용 동작(B §4.1): Edge 실행 파일 탐색, 정책 레지스트리 **읽기**, 전용 프로필로 기동, 127.0.0.1 디버그 포트 연결,
자기 탭 생성·이동·닫기, 앞으로 가져오기, 새로고침, 모델 메뉴·업무 모드 버튼 클릭(자기 탭 안).
사용자 대신 로그인하지 않는다 — 로그인 필요면 안내(BR-LOGIN) + ``bridge.loginWaitMin`` 폴링만(B4).
"""
from __future__ import annotations

import os
import re
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urlsplit

from lm27.bridge import cdp as C
from lm27.bridge import fsio, js
from lm27.bridge import settings as S
from lm27.bridge.clock import INF, Deadline, default_clock, iso_now, iso_to_epoch, stamp
from lm27.bridge.messages import Notices, default_notices

APP_PATHS_KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe"
POLICY_KEY = r"SOFTWARE\Policies\Microsoft\Edge"
EDGE_REL = ("Microsoft", "Edge", "Application", "msedge.exe")
EDGE_ROOT_VARS = ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA")
DEAD_SCHEMES = ("chrome-error://", "edge-error://", "edge://")
BLANK_URL = "about:blank"                 # 웹 수집 역할이 시작 주소 없이 열 때(그 뒤 goto(url))
STATES = ("ready", "login_required", "dead", "loading", "wrong_page", "no_input")
_VER_RX = re.compile(r"^\d+\.\d+\.\d+\.\d+$")
_STILL_ACTIVE = 259


class PhaseError(Exception):
    """L0 실패 — ``phase`` 는 B §5.8 의 단계 문자열."""

    def __init__(self, phase: str, **info):
        super().__init__(phase)
        self.phase = phase
        self.info = info


@dataclass
class EdgeInfo:
    path: str = ""
    version: str = ""
    policy_debug: str = "unset"       # allowed | blocked | unset
    policy_devtools: str = "unset"

    @property
    def major(self) -> int:
        try:
            return int(self.version.split(".", 1)[0])
        except ValueError:
            return 0

    @property
    def policy_blocked(self) -> bool:
        return "blocked" in (self.policy_debug, self.policy_devtools)


@dataclass
class ModelNote:
    wanted: str = ""
    picked: str = ""
    ok: bool = True
    menu_seen: tuple = ()
    note: str = ""


@dataclass
class SessionInfo:
    role: str = "bridge"
    profile_dir: str = ""
    profile_id: str = ""
    port: int = 0
    browser_id: str = ""
    launched_by_us: bool = False
    target_id: str = ""
    ws_url: str = ""
    state: str = ""
    identity: str = ""                # strong | weak | ""
    work_mode: str = "unknown"
    model_current: str = ""
    chat_seq: int = 0
    origin_mode: str = "none"         # none | explicit
    env: object = None


# ───────────────────────── Edge 탐색·정책(읽기만) ─────────────────────────
def winreg_read(hive: str, key: str, value: str):
    """레지스트리 값 읽기(쓰지 않는다). hive = 'HKLM'·'HKCU'. 없으면 None."""
    if os.name != "nt":
        return None
    import winreg
    root = {"HKLM": winreg.HKEY_LOCAL_MACHINE, "HKCU": winreg.HKEY_CURRENT_USER}[hive]
    try:
        with winreg.OpenKey(root, key, 0, winreg.KEY_READ) as k:
            v, _typ = winreg.QueryValueEx(k, value)
            return v
    except OSError:
        return None


def find_edge(reg=winreg_read, environ=None, isfile=os.path.isfile) -> str | None:
    """B §4.3 탐색 순서: App Paths(HKLM·HKCU) → %ProgramFiles(x86)% → %ProgramFiles% → %LOCALAPPDATA%."""
    environ = os.environ if environ is None else environ
    for hive in ("HKLM", "HKCU"):
        v = reg(hive, APP_PATHS_KEY, "")
        if isinstance(v, str) and v.strip():
            p = v.strip().strip('"')
            if isfile(p):
                return p
    for var in EDGE_ROOT_VARS:
        base = environ.get(var)
        if base:
            p = os.path.join(base, *EDGE_REL)
            if isfile(p):
                return p
    return None


def edge_version(path: str, listdir=os.listdir) -> str:
    """msedge.exe 옆 판 폴더(예 ``129.0.2792.65``) 중 가장 높은 것. 모르면 ''."""
    if not path:
        return ""
    try:
        names = [n for n in listdir(os.path.dirname(path)) if _VER_RX.match(n)]
    except OSError:
        return ""
    return max(names, key=lambda n: tuple(int(x) for x in n.split(".")), default="")


def read_policy(reg=winreg_read) -> tuple[str, str]:
    """``RemoteDebuggingAllowed``(0 = 금지)·``DeveloperToolsAvailability``(2 = 금지) — 읽기만(B §4.3)."""
    def judge(name, blocked_val):
        seen = "unset"
        for hive in ("HKLM", "HKCU"):
            v = reg(hive, POLICY_KEY, name)
            if isinstance(v, int):
                if v == blocked_val:
                    return "blocked"
                seen = "allowed"
        return seen
    return judge("RemoteDebuggingAllowed", 0), judge("DeveloperToolsAvailability", 2)


def edge_info(finder=None, policy_reader=None, environ=None) -> EdgeInfo:
    path = (finder or (lambda: find_edge(environ=environ)))() or ""
    dbg, dev = (policy_reader or read_policy)()
    return EdgeInfo(path=path, version=edge_version(path), policy_debug=dbg, policy_devtools=dev)


# ───────────────────────── 프로세스 생존(ctypes — os.kill 금지) ─────────────────────────
def _k32():
    import ctypes
    from ctypes import wintypes
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.OpenProcess.restype = wintypes.HANDLE
    k.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    k.GetExitCodeProcess.restype = wintypes.BOOL
    k.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    k.GetProcessTimes.restype = wintypes.BOOL
    k.GetProcessTimes.argtypes = (wintypes.HANDLE,) + (ctypes.POINTER(wintypes.FILETIME),) * 4
    k.CloseHandle.restype = wintypes.BOOL
    k.CloseHandle.argtypes = (wintypes.HANDLE,)
    return k, ctypes, wintypes


def process_ctime(pid: int) -> int | None:
    """프로세스 생성 시각(FILETIME 정수) — PID 재사용을 가리는 표지. 못 읽으면 None."""
    if os.name != "nt" or not isinstance(pid, int) or pid <= 0:
        return None
    k, ctypes, wintypes = _k32()
    h = k.OpenProcess(0x1000, False, pid)                 # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return None
    try:
        ft = [wintypes.FILETIME() for _ in range(4)]
        if not k.GetProcessTimes(h, *[ctypes.byref(x) for x in ft]):
            return None
        return (ft[0].dwHighDateTime << 32) | ft[0].dwLowDateTime
    finally:
        k.CloseHandle(h)


def process_alive(pid, ctime=None) -> bool:
    """살아 있는가(OpenProcess + GetExitCodeProcess == STILL_ACTIVE, ctime 이 있으면 생성 시각까지 같아야)."""
    if os.name != "nt" or not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
    k, ctypes, wintypes = _k32()
    h = k.OpenProcess(0x1000, False, pid)
    if not h:
        return ctypes.get_last_error() == 5                # 접근 거부 = 있음
    try:
        code = wintypes.DWORD(0)
        if not k.GetExitCodeProcess(h, ctypes.byref(code)) or code.value != _STILL_ACTIVE:
            return False
        if ctime:
            ft = [wintypes.FILETIME() for _ in range(4)]
            if k.GetProcessTimes(h, *[ctypes.byref(x) for x in ft]):
                return ((ft[0].dwHighDateTime << 32) | ft[0].dwLowDateTime) == int(ctime)
        return True
    finally:
        k.CloseHandle(h)


def profile_in_use(profile_dir) -> bool:
    """크로미움 프로필의 ``lockfile`` 이 다른 프로세스에 잡혀 있는가(읽기 열기가 공유 위반이면 사용 중)."""
    p = os.path.join(os.fspath(profile_dir), "lockfile")
    if not os.path.isfile(p):
        return False
    try:
        fd = os.open(p, os.O_RDONLY)
    except PermissionError:
        return True
    except OSError:
        return False
    os.close(fd)
    return False


def spawn_launcher(args):
    """기본 기동기 — 창 없이(CREATE_NO_WINDOW) 띄우고 기다리지 않는다. 반환 핸들: ``pid``·``alive()``·``kill_tree()``."""
    from lm27.util import proc
    return proc.spawn(args, stdin=proc.DEVNULL, stdout=proc.DEVNULL, stderr=proc.DEVNULL)


# ───────────────────────── 신원 판정(순수) ─────────────────────────
def host_of(url: str) -> str:
    try:
        return (urlsplit(str(url or "")).hostname or "").lower()
    except ValueError:
        return ""


def url_matches(url: str, prefix: str) -> bool:
    """URL 이 접두로 시작하는가 — 호스트는 파싱 후 **완전 일치**, 경로는 접두(부분 문자열 비교 금지, B §4.6)."""
    try:
        u, p = urlsplit(str(url or "")), urlsplit(str(prefix or ""))
    except ValueError:
        return False
    if u.scheme != p.scheme or (u.hostname or "").lower() != (p.hostname or "").lower() or not p.hostname:
        return False
    if (u.port or None) != (p.port or None):
        return False
    return (u.path or "/").startswith(p.path or "/")


def classify_identity(r: dict, cfg) -> tuple[str, str]:
    """JS ``identity`` 반환 → (상태, 신원 강도). B §4.6 판정 표 순서 그대로."""
    r = r if isinstance(r, dict) else {}
    url, ready = str(r.get("url") or ""), str(r.get("ready") or "")
    inp = r.get("input") if isinstance(r.get("input"), dict) else {}
    if host_of(url) in cfg.login_hosts:
        return "login_required", ""
    if not url or url == "about:blank" or url.startswith(DEAD_SCHEMES):
        return ("loading" if ready not in ("complete", "") else "dead"), ""
    if not any(url_matches(url, p) for p in cfg.chat_url_prefixes):
        return "wrong_page", ""
    if ready != "complete" and not inp.get("found"):
        return "loading", ""
    if inp.get("found"):
        aria = str(inp.get("aria") or "").lower()
        strong = bool(aria) and any(lbl.lower() in aria for lbl in cfg.dom.input_aria_labels)
        return "ready", ("strong" if strong else "weak")
    return "no_input", ""


def mask_text(s: str, n: int = S.DIAG_MASK_CHARS) -> str:
    """형식 보존 마스킹(B §12.4): 한글 → 가, 영문 → x, 숫자 → 0, 앞 n자."""
    out = []
    for ch in str(s or "")[:n]:
        if "가" <= ch <= "힣":
            out.append("가")
        elif ch.isascii() and ch.isalpha():
            out.append("x")
        elif ch.isdigit():
            out.append("0")
        else:
            out.append(ch)
    return "".join(out)


# ───────────────────────── bridge_profile.json ─────────────────────────
def _skeleton() -> dict:
    return {"schema": 1, "profile_id": "", "calibration": [], "runtime_adjust": {}, "dom": {}, "capabilities": {},
            "health": {"origin_mode": "none", "dead_sessions": []}, "env": {}, "last_session": {}}


class BridgeProfile:
    r"""``%LOCALAPPDATA%\LoadMonitor27\bridge\bridge_profile.json``(B §4.10 — 계정 정보 없음) 읽기·갱신.
    보정값·학습한 DOM 선택자·조회 능력·건강·env·지난 세션(포트·브라우저 ID·자기 탭). 쓰기는 ``fsio.write_atomic``."""

    def __init__(self, paths):
        self.paths = paths
        self.path = fsio.bridge_file(paths, "bridge_profile")
        self.id_path = fsio.bridge_file(paths, "profile_id")

    def load(self) -> dict:
        d = fsio.read_json(self.path, None)
        base = _skeleton()
        if isinstance(d, dict):
            for k, v in d.items():
                if k in base and isinstance(base[k], dict) and not isinstance(v, dict):
                    continue
                base[k] = v
            base["health"] = {**_skeleton()["health"], **(base.get("health") or {})}
        return base

    def save(self, d: dict) -> None:
        fsio.write_atomic(self.path, d)

    def update(self, fn) -> dict:
        d = self.load()
        fn(d)
        self.save(d)
        return d

    def profile_id(self) -> str:
        t = (fsio.read_text(self.id_path) or "").strip()
        try:
            return str(uuid.UUID(t))
        except ValueError:
            return ""

    def new_profile_id(self) -> str:
        """프로필 폴더를 새로 만들 때 UUID 를 만든다 — 보정값 키 ``(profile_id, model, edge_major)``(B §4.10)."""
        pid = str(uuid.uuid4())
        fsio.write_atomic(self.id_path, pid + "\n")

        def put(d):
            d["profile_id"] = pid
            d["calibration"] = [c for c in d.get("calibration") or [] if isinstance(c, dict)]
        self.update(put)
        return pid


# ───────────────────────── 프로필 잠금(B §4.5) ─────────────────────────
class SessionLock:
    """``session.lock.json`` — 원자적 생성(O_EXCL), 죽은 소유자(PID·생성 시각) 또는 30분 무응답이면 ``.stale`` 로 옮기고 인수."""

    def __init__(self, paths, clock, *, role: str, run_id: str, proc_probe=process_alive, pid: int | None = None,
                 pid_ctime: int | None = None):
        self.path = Path(paths.edge_lock())
        self.clock = clock
        self.role = role
        self.run_id = run_id
        self.probe = proc_probe
        self.pid = os.getpid() if pid is None else pid
        self.pid_ctime = process_ctime(self.pid) if pid_ctime is None and pid is None else pid_ctime
        self.held = False
        self.took_over = False
        self.doc: dict = {}
        self._last_beat = -INF
        self._mx = threading.Lock()                        # 배경 하트비트와 주 흐름의 갱신을 직렬화

    def _new_doc(self, targets=None) -> dict:
        now = iso_now(self.clock)
        return {"schema": 1, "pid": self.pid, "pid_ctime": self.pid_ctime or 0, "role": self.role,
                "run_id": self.run_id, "port": 0, "browser_id": "", "launched_by_us": False,
                "targets": {r: list((targets or {}).get(r, [])) for r in S.ROLES}, "acquired": now, "heartbeat": now}

    def is_stale(self, cur: dict) -> bool:
        pid = cur.get("pid")
        if not isinstance(pid, int) or not self.probe(pid, cur.get("pid_ctime") or None):
            return True
        t = iso_to_epoch(str(cur.get("heartbeat") or cur.get("acquired") or ""))
        return t is not None and self.clock.now() - t > S.LOCK_STALE_S

    def acquire(self, targets=None) -> None:
        """잡거나 ``PhaseError("lock_busy", owner_role, age_sec)``."""
        for _attempt in (1, 2):
            doc = self._new_doc(targets)
            if fsio.create_exclusive(self.path, doc):
                self.doc, self.held = doc, True
                self._last_beat = self.clock.mono()
                return
            cur = fsio.read_json(self.path, None)
            if cur is None:                                # 막 만들어지는 중일 수 있다 — 한 번 더 본다
                self.clock.sleep(S.LAUNCH_POLL_S)
                cur = fsio.read_json(self.path, None)
            if cur is None or self.is_stale(cur):
                if isinstance(cur, dict) and not targets:
                    targets = cur.get("targets") if isinstance(cur.get("targets"), dict) else None
                fsio.move_aside(self.path, str(self.path) + ".stale")
                self.took_over = True
                continue
            t = iso_to_epoch(str(cur.get("acquired") or ""))
            raise PhaseError("lock_busy", owner_role=str(cur.get("role") or ""),
                             age_sec=int(self.clock.now() - t) if t else -1)
        raise PhaseError("lock_busy", owner_role="", age_sec=-1)

    def update(self, **fields) -> None:
        with self._mx:
            if not self.held:
                return
            self.doc.update(fields)
            self.doc["heartbeat"] = iso_now(self.clock)
            fsio.write_atomic(self.path, self.doc)
            self._last_beat = self.clock.mono()

    def heartbeat(self) -> bool:
        """30초가 지났으면 heartbeat 갱신."""
        if self.held and self.clock.mono() - self._last_beat >= S.LOCK_HEARTBEAT_S:
            self.update()
            return True
        return False

    def release(self) -> None:
        with self._mx:
            if not self.held:
                return
            cur = fsio.read_json(self.path, None)
            if not isinstance(cur, dict) or cur.get("pid") == self.pid:
                fsio.remove(self.path)
            self.held = False


# ───────────────────────── EdgeSession ─────────────────────────
class EdgeSession:
    """L0 세션 하나(역할 하나). 의존은 모두 주입 가능(시험: 가짜 HTTP·CDP·기동기·가상 시계)."""

    def __init__(self, role: str = "bridge", run_id: str | None = None, *, url: str | None = None, paths=None,
                 cfg=None, clock=None, http=None, connector=None, launcher=None, can_bind=None, edge_finder=None,
                 policy_reader=None, proc_probe=None, in_use=None, notices: Notices | None = None, environ=None,
                 tracer=None, pid: int | None = None, pid_ctime: int | None = None):
        if role not in S.ROLES:
            raise ValueError(f"EdgeSession: role 은 {S.ROLES} 중 하나")
        if paths is None:
            from lm27.paths import Paths
            paths = Paths()
        if cfg is None:
            cfg = S.load_settings(paths)
        self.role = role
        self.run_id = run_id or ""
        self.paths = paths
        self.cfg = cfg
        self.clock = clock or default_clock()
        self.http = http or C.UrllibHttp()
        self.connector = connector or C.WsConnector(self.clock)
        self.launcher = launcher or spawn_launcher
        self.can_bind = can_bind or C.can_bind
        self.edge_finder = edge_finder
        self.policy_reader = policy_reader
        self.in_use = in_use or profile_in_use
        self.notices = notices if notices is not None else default_notices()
        self.environ = os.environ if environ is None else environ
        self.tracer = tracer
        if url is not None and not str(url).startswith("https://"):
            raise ValueError("EdgeSession: 시작 주소(url=)는 https:// 로 시작해야 합니다")
        self.url = url or (cfg.url if role == "bridge" else BLANK_URL)
        self.profile = BridgeProfile(paths)
        self.lock = SessionLock(paths, self.clock, role=role, run_id=self.run_id,
                                proc_probe=proc_probe or process_alive, pid=pid, pid_ctime=pid_ctime)
        self.info = SessionInfo(role=role)
        self.edge = EdgeInfo()
        self.state = ""
        self.error: dict = {}
        self.cdp = None
        self.env = None
        self._proc = None
        self._targets: dict = {}
        self._started = False
        self._closed = False
        self._model_cache: dict = {}
        self._ready_recorded = False
        self._hb_stop = threading.Event()
        self._hb_thread = None
        self.events: list[str] = []          # 시험·진단용 진행 기록(코드만)

    # ── 수명 ───────────────────────────────────────────────────────────
    @classmethod
    def open(cls, role: str = "bridge", run_id: str | None = None, **kw) -> EdgeSession:
        """세션 객체를 만든다(아직 기동하지 않음). ``with`` 로 쓰면 들어갈 때 ``start()``, 나갈 때 ``close()``."""
        return cls(role, run_id, **kw)

    def __enter__(self) -> EdgeSession:
        self.start()
        return self

    def __exit__(self, *exc) -> bool:
        self.close()
        return False

    def start(self) -> str:
        """잠금 → 포트 → 기동/재사용 → 자기 탭 → 연결 → (bridge) ensure_ready·업무 모드·env 판별. 반환: 상태 문자열."""
        if self._started:
            return self.state
        self._started = True
        try:
            self.state = self._start()
        except PhaseError as e:
            self.state, self.error = e.phase, dict(e.info)
        except (OSError, C.CdpError, ValueError) as e:     # 예상 못 한 기동·연결 오류도 단계 문자열로(예외로 새지 않게)
            self.state = "launch_failed" if self.cdp is None else "cdp_error"
            self.error = {"why": type(e).__name__}
        if self.cdp is None and self.state != "ready":
            self.lock.release()                            # 붙지도 못했으면 잠금을 바로 놓는다(다른 역할을 막지 않게)
        elif not getattr(self.clock, "virtual", False):
            self._start_heartbeat()
        self.info.state = self.state
        if self.tracer is not None:
            self.tracer.write(kind="session", role=self.role, port=self.info.port, launched=self.info.launched_by_us,
                              origin_mode=self.info.origin_mode, identity=self.info.identity, phase=self.state)
        return self.state

    def _start(self) -> str:
        if str(self.environ.get("LM_NO_BROWSER", "")).strip() not in ("", "0"):
            raise PhaseError("edge_not_found", why="no_browser")       # 시험 주입점: Edge 를 띄우지도 붙지도 않는다
        self.info.profile_dir = str(self.cfg.profile_dir(self.paths))
        self._acquire_lock()
        self._recover_dead_profile()
        self.edge = edge_info(self.edge_finder, self.policy_reader, self.environ)
        port, how = self.choose_port()
        self.info.port = port
        self.info.origin_mode = self.profile.load()["health"].get("origin_mode") or "none"
        if how == "launch":
            if not self.edge.path:
                raise PhaseError("edge_not_found")
            self._launch(port)
        self._attach(port)
        if self.role == "bridge":
            st = self.ensure_ready()
            if st == "ready":
                self.ensure_work_mode()
                from lm27.bridge.env import detect_env
                detect_env(self)
                self.info.env = self.env
            return st
        return "ready" if self.url == BLANK_URL else self.wait_page()

    def close(self) -> None:
        """자기 탭 정리 → (우리가 띄웠고 closeOnExit) Browser.close → 잠금 해제. 여러 번 불러도 된다."""
        if self._closed:
            return
        self._closed = True
        try:
            if self.info.launched_by_us and self.cfg.edge.close_on_exit and self.info.port:
                self._browser_close()
            elif self.cdp is not None:
                self._close_own_tab()
        finally:
            self._hb_stop.set()
            if self.cdp is not None:
                self.cdp.close()
                self.cdp = None
            self._save_last_session()
            self.lock.release()

    def _start_heartbeat(self) -> None:
        """실제 시계일 때만: 30초마다 잠금 heartbeat 를 갱신하는 배경 스레드(B §2.3 — 가상 시계 시험에서는 끔)."""
        if self._hb_thread is not None:
            return

        def loop():
            while not self._hb_stop.wait(S.LOCK_HEARTBEAT_S):
                self.tick()
        self._hb_thread = threading.Thread(target=loop, name="lm27-bridge-lock-heartbeat", daemon=True)
        self._hb_thread.start()

    # ── 잠금·복구 ──────────────────────────────────────────────────────
    def _acquire_lock(self) -> None:
        last = self.profile.load().get("last_session") or {}
        targets = last.get("targets") if isinstance(last.get("targets"), dict) else {}
        for attempt in range(S.LOCK_BUSY_RETRIES + 1):
            try:
                self.lock.acquire(targets)
                self._targets = {r: list(v) for r, v in (self.lock.doc.get("targets") or {}).items()}
                return
            except PhaseError:
                if attempt >= S.LOCK_BUSY_RETRIES:
                    raise
                self.notices.notify("BR-LOCK-BUSY")
                self.events.append("lock_wait")
                self.clock.sleep(S.LOCK_BUSY_WAIT_S)

    def record_health(self, kind: str) -> None:
        """건강 기록 — ``dead_session`` 은 호출(run_id)마다 1회만 쌓는다."""
        def put(d):
            h = d.setdefault("health", {})
            if kind == "dead_session":
                lst = [x for x in h.get("dead_sessions") or [] if isinstance(x, dict)]
                if not any(x.get("run") == self.run_id for x in lst):
                    lst.append({"run": self.run_id, "at": iso_now(self.clock)})
                h["dead_sessions"] = lst[-5:]
            elif kind == "ready":
                h["dead_sessions"] = []
                h["login_ok_at"] = iso_now(self.clock)
            elif kind == "origin_explicit":
                h["origin_mode"] = "explicit"
        self.profile.update(put)

    def _recover_dead_profile(self) -> bool:
        """서로 다른 호출 2회의 dead_session → Edge 를 닫고 프로필을 ``<이름>.bad-<시각>`` 로 바꿔 새 프로필(B §4.7).
        사람에게 폴더 조작을 요구하지 않는다."""
        runs = {x.get("run") for x in self.profile.load()["health"].get("dead_sessions") or [] if isinstance(x, dict)}
        if len(runs) < S.DEAD_SESSION_LIMIT:
            return False
        prof = Path(self.info.profile_dir)
        dap = C.read_devtools_active_port(prof)
        if dap and C.debugger_alive(self.http, dap[0]) and self._owns(dap[0], dap[1]):
            self._close_browser_on(dap[0])
        if prof.exists():
            bad = prof.with_name(f"{prof.name}.bad-{stamp(self.clock)}")
            try:
                fsio.rename_dir(prof, bad)
            except OSError:
                self.events.append("bad_rename_failed")
                return False
            olds = sorted((p for p in prof.parent.glob(prof.name + ".bad-*") if p.is_dir()), key=lambda p: p.name)
            for p in olds[:-(S.BAD_PROFILE_KEEP + 1)]:
                fsio.remove_tree(p)
        self.profile.new_profile_id()

        def clear(d):
            d.setdefault("health", {})["dead_sessions"] = []
            d["last_session"] = {}
        self.profile.update(clear)
        self.notices.notify("BR-DEAD-PROFILE")
        self.events.append("profile_recreated")
        return True

    # ── 포트·기동 ──────────────────────────────────────────────────────
    def _owns(self, port: int, browser_path: str | None) -> bool:
        """그 포트의 브라우저가 우리 프로필의 것인가 — DevToolsActivePort 2째 줄, 없으면 지난 세션 기록 대조(B §4.3)."""
        v = C.version(self.http, port)
        if not v:
            return False
        ws = str(v.get("webSocketDebuggerUrl") or "")
        if browser_path:
            return ws.endswith(browser_path)
        last = self.profile.load().get("last_session") or {}
        return bool(last.get("browser_id")) and last.get("port") == port and C.browser_id(ws) == last.get("browser_id")

    def choose_port(self) -> tuple[int, str]:
        """(포트, reuse|launch). 남의 디버그 Edge 가 있는 포트에는 절대 붙지 않는다(B §4.3)."""
        dap = C.read_devtools_active_port(self.info.profile_dir)
        if dap and C.debugger_alive(self.http, dap[0]) and self._owns(dap[0], dap[1]):
            return dap[0], "reuse"
        for p in self.cfg.ports():
            if C.debugger_alive(self.http, p):
                if self._owns(p, dap[1] if dap else None):
                    return p, "reuse"
                self.events.append(f"skip_foreign:{p}")
                continue
            if not self.can_bind(p):
                self.events.append(f"skip_busy:{p}")
                continue
            return p, "launch"
        raise PhaseError("port_exhausted")

    def launch_args(self, port: int, origin_explicit: bool = False) -> list[str]:
        """기동 인자(B §4.3). 모든 Origin 허용은 쓰지 않는다 — explicit 이면 127.0.0.1:<port> 만."""
        c = self.cfg
        args = [self.edge.path,
                f"--user-data-dir={self.info.profile_dir}",
                f"--remote-debugging-port={port}",
                "--no-first-run", "--no-default-browser-check",
                "--disable-background-timer-throttling",
                "--disable-backgrounding-occluded-windows",
                "--disable-renderer-backgrounding",
                f"--window-size={c.edge.window_size}"]
        if c.edge.disk_cache_mb > 0:
            args.append(f"--disk-cache-size={c.edge.disk_cache_mb * 1048576}")
        if origin_explicit:
            args.append(f"--remote-allow-origins=http://127.0.0.1:{port}")
        args.append(self.url)
        return args

    def _launch(self, port: int, *, retried: bool = False) -> None:
        prof = Path(self.info.profile_dir)
        if not prof.exists() or not self.profile.profile_id():
            self.profile.new_profile_id()
        self._proc = self.launcher(self.launch_args(port, self.info.origin_mode == "explicit"))
        self.info.launched_by_us = True
        self.events.append(f"launch:{port}")
        dl = Deadline.after(self.clock, S.LAUNCH_WAIT_S)
        while not dl.expired():
            self.clock.sleep(S.LAUNCH_POLL_S)
            if C.debugger_alive(self.http, port):
                return
        alive = bool(self._proc is not None and self._proc.alive())
        if not alive and self.in_use(prof):
            # 사람이 같은 프로필을 일반 실행 중 — 새 기동이 그쪽으로 넘어가고 포트는 열리지 않는다(B §4.3·§4.5)
            self.info.launched_by_us = False
            if retried:
                raise PhaseError("profile_busy")
            self.notices.notify("BR-PROFILE-BUSY")
            self.clock.sleep(S.PROFILE_BUSY_RECHECK_S)
            if self.in_use(prof):
                raise PhaseError("profile_busy")
            self._launch(port, retried=True)
            return
        if alive:
            self._proc.kill_tree()                         # 우리가 띄운 응답 없는 Edge 는 정리한다
        self.info.launched_by_us = False
        if alive and self.edge.policy_blocked:
            raise PhaseError("policy_blocked")
        raise PhaseError("launch_failed", alive=alive)

    def _attach(self, port: int) -> None:
        v = C.version(self.http, port)
        if not v:
            raise PhaseError("launch_failed", why="no_version")
        self._browser_ws = str(v.get("webSocketDebuggerUrl") or "")
        self.info.browser_id = C.browser_id(self._browser_ws)
        self.own_tab()
        self._connect()
        self.lock.update(port=port, browser_id=self.info.browser_id, launched_by_us=self.info.launched_by_us,
                         targets=self._targets)
        self._save_last_session()

    def _origin(self) -> str | None:
        return f"http://127.0.0.1:{self.info.port}" if self.info.origin_mode == "explicit" else None

    def _connect(self) -> None:
        try:
            self.cdp = self.connector.connect(self.info.ws_url, origin=self._origin())
            return
        except C.HandshakeRejected as e:
            if e.status != 403 or self._origin():
                raise PhaseError("launch_failed", why=f"handshake_{e.status}") from None
        # 403 — Origin 이 필요하다. 다음부터 explicit 로 띄우고, 우리가 띄운 Edge 면 지금 다시 띄운다(B §4.4)
        self.record_health("origin_explicit")
        self.info.origin_mode = "explicit"
        if not self.info.launched_by_us or self._proc is None:
            raise PhaseError("launch_failed", why="origin_rejected")
        self._proc.kill_tree()
        self._wait_port_closed(self.info.port)
        self._launch(self.info.port)
        v = C.version(self.http, self.info.port)
        if not v:
            raise PhaseError("launch_failed", why="no_version")
        self._browser_ws = str(v.get("webSocketDebuggerUrl") or "")
        self.info.browser_id = C.browser_id(self._browser_ws)
        self._targets[self.role] = []
        self.own_tab()
        try:
            self.cdp = self.connector.connect(self.info.ws_url, origin=self._origin())
        except C.HandshakeRejected:
            raise PhaseError("launch_failed", why="origin_rejected") from None

    def _wait_port_closed(self, port: int) -> bool:
        dl = Deadline.after(self.clock, S.CLOSE_WAIT_S)
        while C.debugger_alive(self.http, port):
            if dl.expired():
                return False
            self.clock.sleep(S.LAUNCH_POLL_S)
        return True

    # ── 탭 소유(B §4.6) ────────────────────────────────────────────────
    def _pages(self) -> list[dict]:
        try:
            tabs = self.http.json(self.info.port, "/json")
        except C.HTTP_ERRORS:
            return []
        return [t for t in tabs or [] if isinstance(t, dict) and t.get("type") == "page"]

    def own_tab(self) -> dict:
        """지난번 우리 탭이 살아 있으면 재사용, 아니면 새 탭을 만든다. **남의 탭은 닫지도 옮기지도 않는다.**"""
        prev = self._targets.get(self.role) or []
        pages = self._pages()
        tab = next((t for t in pages if t.get("id") in prev), None)
        if tab is None and not prev and self.info.launched_by_us and len(pages) == 1:
            tab = pages[0]                                 # 우리가 방금 띄운 Edge 의 첫 탭(기동 인자의 주소) = 우리 탭
            self._targets[self.role] = [tab["id"]]
            self.events.append("tab_adopt")
        elif tab is None:
            path = "/json/new?" + quote(self.url, safe="")
            for method in ("PUT", "GET"):
                try:
                    tab = self.http.json(self.info.port, path, method=method)
                    break
                except C.HTTP_ERRORS:
                    continue
            if not isinstance(tab, dict) or not tab.get("id"):
                raise PhaseError("tab_lost", why="new_tab")
            self._targets[self.role] = [tab["id"]]
            self.events.append("tab_new")
        else:
            self.events.append("tab_reuse")
        ws = str(tab.get("webSocketDebuggerUrl") or "")
        if not C.local_ws_url(ws):
            raise PhaseError("tab_lost", why="ws_url")
        self.info.target_id, self.info.ws_url = str(tab["id"]), ws
        return tab

    def tab_alive(self) -> bool:
        return any(t.get("id") == self.info.target_id for t in self._pages())

    def reconnect(self) -> None:
        """시간 초과 뒤 다시 연결. 자기 탭이 사라졌으면 ``PhaseError("tab_lost")``."""
        if not self.tab_alive():
            raise PhaseError("tab_lost")
        if self.cdp is not None:
            try:
                self.cdp.reconnect()
                return
            except (OSError, C.HandshakeRejected):
                self.cdp.close()
        self.cdp = self.connector.connect(self.info.ws_url, origin=self._origin())

    def _close_own_tab(self) -> None:
        tid = self.info.target_id
        if not tid:
            return
        try:
            self.http.json(self.info.port, f"/json/close/{tid}")
        except C.HTTP_ERRORS:
            pass
        self._targets[self.role] = []

    def _close_browser_on(self, port: int) -> bool:
        v = C.version(self.http, port)
        if not v:
            return True
        try:
            b = self.connector.connect(str(v.get("webSocketDebuggerUrl") or ""), origin=self._origin())
            try:
                b.call("Browser.close", {}, timeout=S.CLOSE_WAIT_S)
            finally:
                b.close()
        except (OSError, C.CdpError, C.HandshakeRejected, ValueError):
            pass
        self.events.append("browser_close")
        return self._wait_port_closed(port)

    def _browser_close(self) -> None:
        """우리가 띄운 Edge 를 Browser.close — 5초 안에 포트가 닫히지 않으면 그대로 둔다(강제 종료하지 않는다)."""
        self._close_browser_on(self.info.port)
        self._targets = {r: [] for r in S.ROLES}

    def _save_last_session(self) -> None:
        if not self.info.port:
            return

        def put(d):
            d["last_session"] = {"port": self.info.port, "browser_id": self.info.browser_id,
                                 "targets": {r: list(v) for r, v in self._targets.items() if v}}
        try:
            self.profile.update(put)
        except OSError:
            pass

    # ── 페이지 조작 ─────────────────────────────────────────────────────
    def tick(self) -> None:
        """폴링 중 잠금 하트비트(30초)."""
        try:
            self.lock.heartbeat()
        except OSError:
            pass

    def eval(self, expr: str, timeout: float = S.CDP_CALL_TIMEOUT_S):
        """자기 탭에서 JS 평가. 시간 초과·연결 끊김이면 1회 다시 연결해 재시도(LM24 규약)."""
        if self.cdp is None:
            raise PhaseError(self.state or "tab_lost")
        try:
            return self.cdp.eval(expr, timeout=timeout)
        except (C.CdpTimeout, ConnectionError):
            self.reconnect()
            return self.cdp.eval(expr, timeout=timeout)

    def call(self, method: str, params: dict | None = None, timeout: float = S.CDP_CALL_TIMEOUT_S):
        if self.cdp is None:
            raise PhaseError(self.state or "tab_lost")
        try:
            return self.cdp.call(method, params or {}, timeout=timeout)
        except (C.CdpTimeout, ConnectionError):
            self.reconnect()
            return self.cdp.call(method, params or {}, timeout=timeout)

    def activate(self) -> None:
        """자기 탭을 앞으로(``Page.bringToFront`` + ``/json/activate/<id>``) — 실패해도 진행."""
        try:
            self.call("Page.bringToFront", {})
        except (OSError, C.CdpError, PhaseError):
            pass
        try:
            self.http.json(self.info.port, f"/json/activate/{self.info.target_id}")
        except C.HTTP_ERRORS:
            pass

    def navigate(self, url: str | None = None) -> None:
        self.call("Page.navigate", {"url": url or self.url})

    def reload(self) -> None:
        try:
            self.call("Page.reload", {})
        except (OSError, C.CdpError):
            pass

    # ── 신원·준비(B §4.6·§4.7) ─────────────────────────────────────────
    def identity(self) -> str:
        try:
            r = self.eval(js.identity(self.cfg.dom.input_selectors))
        except C.CdpError:
            r = {}
        st, strength = classify_identity(r, self.cfg)
        if st == "ready":
            self.info.identity = strength
        return st

    def poll_identity(self, up_to: float, *, every: float = S.IDENTITY_POLL_S, until=None) -> str:
        """``until(상태)`` 가 참이 될 때까지(기본: ready) every 초 간격, 최대 up_to 초."""
        until = until or (lambda s: s == "ready")
        dl = Deadline.after(self.clock, up_to)
        st = self.identity()
        while not until(st) and not dl.expired():
            self.clock.sleep(min(every, max(dl.left(), 0.0)) or every)
            self.tick()
            st = self.identity()
        return st

    def ensure_ready(self, dl: Deadline | None = None) -> str:
        """L1 에 넘길 '입력할 수 있는 Copilot 탭' 상태를 만든다(B §4.7). 반환: ready 또는 L1 단계 문자열."""
        if self.cdp is None:
            return self.state or "tab_lost"
        dl = dl or Deadline(self.clock, INF)
        c = self.cfg
        try:
            st = self.identity()
            if st == "wrong_page":
                self.navigate()
                st = self.poll_identity(dl.cap(S.IDENTITY_SETTLE_S), until=lambda s: s not in ("loading", "wrong_page"))
            if st == "loading":
                st = self.poll_identity(dl.cap(c.ready_wait_sec), until=lambda s: s != "loading")
            if st == "login_required":
                self.activate()
                self.notices.notify("BR-LOGIN", loginWaitMin=c.login_wait_min)
                self.events.append("login_wait")
                st = self.poll_identity(dl.cap(c.login_wait_min * 60), every=S.LOGIN_POLL_S,
                                        until=lambda s: s not in ("login_required", "loading"))
                if st in ("login_required", "loading"):
                    return "login_required"
                self.notices.notify("BR-LOGIN-OK")
            if st == "no_input":
                st = self.poll_identity(dl.cap(c.ready_wait_sec), until=lambda s: s != "no_input")
                if st == "no_input":
                    self.reload()
                    st = self.poll_identity(dl.cap(c.ready_wait_sec), until=lambda s: s != "no_input")
                if st in ("no_input", "loading"):
                    self.dump_diagnose()
                    self.notices.notify("BR-INPUT")
                    return "input_not_found"
            if st == "dead":
                self.reload()
                st = self.poll_identity(dl.cap(S.IDENTITY_SETTLE_S), until=lambda s: s not in ("dead", "loading"))
                if st in ("dead", "loading"):
                    self.record_health("dead_session")
                    return "dead_session"
            if st == "wrong_page":
                return "wrong_tab"
            if st == "login_required":
                return "login_required"
            if st == "ready" and not self._ready_recorded:
                self._ready_recorded = True
                self.record_health("ready")
            return st if st == "ready" else "input_not_found"
        except PhaseError as e:
            return e.phase
        except (OSError, C.CdpError):
            return "tab_lost" if not self.tab_alive() else "cdp_error"

    def page_state(self) -> dict:
        """웹 수집 역할용: ``{host, ready}``(페이지 글·제목 없음)."""
        try:
            r = self.eval(js.identity(()))
        except (C.CdpError, PhaseError):
            r = {}
        r = r if isinstance(r, dict) else {}
        return {"host": host_of(r.get("url") or ""), "ready": str(r.get("ready") or ""), "url": str(r.get("url") or "")}

    def goto(self, url: str, dl: Deadline | None = None) -> str:
        """웹 수집 역할: 자기 탭에서 https 주소로 이동하고 로드·로그인을 기다린다(``wait_page``). 반환: 상태 문자열."""
        if not str(url or "").startswith("https://"):
            raise ValueError("goto: https:// 주소만")
        if self.cdp is None:
            return self.state or "tab_lost"
        try:
            self.navigate(url)
        except (OSError, C.CdpError, PhaseError):
            return "tab_lost" if not self.tab_alive() else "cdp_error"
        self.state = self.info.state = self.wait_page(dl)
        return self.state

    def wait_page(self, dl: Deadline | None = None) -> str:
        """웹 수집 역할(owa·teams_web): 로그인 화면이면 BR-LOGIN 안내 + 5초 폴링, 로드 끝나면 ready(B §4.1)."""
        if self.cdp is None:
            return self.state or "tab_lost"
        dl = dl or Deadline(self.clock, INF)
        c = self.cfg

        def judge():
            p = self.page_state()
            if p["host"] in c.login_hosts:
                return "login_required"
            if not p["url"] or p["url"].startswith(DEAD_SCHEMES):
                return "dead" if p["ready"] == "complete" else "loading"
            return "ready" if p["ready"] == "complete" else "loading"

        def poll(up_to, every, until):
            d2 = Deadline.after(self.clock, up_to)
            st = judge()
            while not until(st) and not d2.expired():
                self.clock.sleep(every)
                self.tick()
                st = judge()
            return st
        try:
            st = poll(dl.cap(c.ready_wait_sec), S.IDENTITY_POLL_S, lambda s: s != "loading")
            if st == "login_required":
                self.activate()
                self.notices.notify("BR-LOGIN", loginWaitMin=c.login_wait_min)
                st = poll(dl.cap(c.login_wait_min * 60), S.LOGIN_POLL_S, lambda s: s not in ("login_required", "loading"))
                if st != "ready":
                    return "login_required"
                self.notices.notify("BR-LOGIN-OK")
            if st == "dead":
                self.reload()
                st = poll(dl.cap(S.IDENTITY_SETTLE_S), S.IDENTITY_POLL_S, lambda s: s not in ("dead", "loading"))
            return "ready" if st == "ready" else ("dead_session" if st == "dead" else "input_not_found")
        except PhaseError as e:
            return e.phase
        except (OSError, C.CdpError):
            return "tab_lost" if not self.tab_alive() else "cdp_error"

    # ── 업무 모드·모델(B §4.8) ─────────────────────────────────────────
    def ensure_work_mode(self) -> str:
        """업무/웹 전환 상태를 읽고, preferWorkMode 이고 웹이면 업무 쪽을 1회 누른 뒤 다시 확인. 판별 불가면 unknown."""
        c = self.cfg.dom
        try:
            r = self.eval(js.work_mode(c.work_labels, c.web_labels, False)) or {}
            mode = r.get("mode") if r.get("found") else "unknown"
            if self.cfg.prefer_work_mode and mode == "web":
                self.eval(js.work_mode(c.work_labels, c.web_labels, True))
                self.clock.sleep(S.WORK_MODE_SETTLE_S)
                r = self.eval(js.work_mode(c.work_labels, c.web_labels, False)) or {}
                mode = r.get("mode") if r.get("found") else "unknown"
        except (OSError, C.CdpError, PhaseError):
            mode = "unknown"
        self.info.work_mode = mode if mode in ("work", "web") else "unknown"
        return self.info.work_mode

    def select_model(self, model: str) -> ModelNote:
        """모델 메뉴에서 고르기 — **채팅마다 1회**(같은 chat_seq·같은 모델이면 생략), 실패해도 진행(경고)."""
        model = (model or "").strip()
        if not model:
            return ModelNote(wanted="", picked="", ok=True, note="untouched")
        key = (self.info.chat_seq, model)
        if key in self._model_cache:
            return self._model_cache[key]
        note = self._select_model(model)
        self._model_cache = {key: note}
        if note.picked:
            self.info.model_current = note.picked[:S.MODEL_NOTE_MAX]
        return note

    def _select_model(self, model: str) -> ModelNote:
        c = self.cfg.dom
        try:
            r1 = self.eval(js.pick_model(model, c.model_button_labels)) or {}
            if r1.get("already"):
                return ModelNote(model, str(r1.get("cur") or model)[:S.MODEL_NOTE_MAX], True, (), "already")
            if not r1.get("ok"):
                return ModelNote(model, "", False, (), "selector_not_found")
            self.clock.sleep(S.MENU_SETTLE_S)
            if not r1.get("alreadyOpen"):
                if not (self.eval(js.menu_open()) or {}).get("open"):
                    self.eval(js.pick_model(model, c.model_button_labels))
                    self.clock.sleep(S.MENU_REOPEN_S)
            seen: tuple = ()
            for _depth in range(S.MENU_DEPTH):
                r2 = self.eval(js.pick_model_item(model)) or {}
                if r2.get("ok"):
                    self.clock.sleep(S.MENU_PICK_S)
                    return ModelNote(model, str(r2.get("picked") or model)[:S.MODEL_NOTE_MAX], True, seen, "picked")
                if r2.get("submenu"):
                    self.clock.sleep(S.MENU_SETTLE_S)
                    continue
                seen = tuple(str(x)[:S.MODEL_NOTE_MAX] for x in (r2.get("seen") or [])[:S.MENU_SEEN_MAX])
                break
            self.eval(js.close_menu())
            return ModelNote(model, "", False, seen, "item_not_found")
        except (OSError, C.CdpError, PhaseError) as e:
            return ModelNote(model, "", False, (), type(e).__name__)

    # ── 진단(B §12.4) ──────────────────────────────────────────────────
    def dump_diagnose(self) -> str | None:
        """화면 구조 덤프(형식 보존 마스킹)를 ``bridge\\diagnose\\diagnose_<시각>.json`` 에. 원문 없음."""
        c = self.cfg.dom
        keep = (c.input_aria_labels + c.send_labels + c.stop_labels + c.new_chat_labels + c.model_button_labels
                + c.work_labels + c.web_labels + c.web_grounding_labels)
        try:
            d = self.eval(js.diagnose(c.input_selectors, keep)) or {}
        except (OSError, C.CdpError, PhaseError):
            return None
        if not isinstance(d, dict):
            return None
        d["url_path"] = re.sub(r"[0-9A-Fa-f-]{8,}", "x", str(d.get("url_path") or ""))[:80]
        for m in d.get("message_candidates") or []:
            if isinstance(m, dict):
                m["text_mask"] = mask_text(m.get("text_mask") or "")
        d["learned_assistant_sel"] = str((self.profile.load().get("dom") or {}).get("assistant_sel") or "")
        p = fsio.child(fsio.bridge_file(self.paths, "diagnose"), f"diagnose_{stamp(self.clock)}.json")
        try:
            fsio.write_atomic(p, d)
        except OSError:
            return None
        return str(p)
