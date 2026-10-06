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
    #           단 작업 보류(``edge_hold`` — 한 작업 수집→분석) 중이면 닫지 않고 다음 세션에 넘기고(kept_launch), 보류가 끝나면
    #           ``release_edge_hold`` 가 닫는다(H2 — 로그인 상태 유지가 없는 회사에서 '한 번 로그인'으로 한 작업을 마치게).

회사 PC 위험 대응(2026-10 공식 문서 대조): 로그인 호스트 접미사·회사 IdP 화면에서 떠나지 않음(H3) · 장치 기반 조건부 액세스
AADSTS 는 'Edge 프로필 로그인' 안내(H1) · SSO 로 한순간 지나가는 로그인 화면은 조용히(L1) · edge:// 화면은 죽은 세션이 아니라
브라우저 로그인(M6) · UserDataDir 정책이면 띄우지 않고 남의 Edge 는 죽이지 않음(H5) · 로그인 화면 종류(회사·개인)를 남겨 개인 계정
Copilot 에는 보내지 않게(H4 — ``env.derive_account``) · 입력창 없는 Copilot 화면 반복은 채팅 차단 의심(M5).

허용 동작(B §4.1): Edge 실행 파일 탐색, 정책 레지스트리 **읽기**, 전용 프로필로 기동, 127.0.0.1 디버그 포트 연결,
자기 탭 생성·이동·닫기, 앞으로 가져오기, 새로고침, 모델 메뉴·업무 모드 버튼 클릭(자기 탭 안).
사용자 대신 로그인하지 않는다 — 로그인 필요면 안내(BR-LOGIN) + ``bridge.loginWaitMin`` 폴링만(B4). 그 대기가 로그인 없이
끝나면 '로그인 보류'(health.login_pending)를 남기고, 다음 수집·분석은 ``LOGIN_PENDING_CHECK_S`` 만 확인한다(v1.3 §0.8 V18 —
회사 계정이 없는 PC). [분석용 Edge 창 앞으로](``front``)·로그인 확인이 보류를 지운다.
"""
from __future__ import annotations

import contextlib
import os
import re
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urlsplit

from lm27.bridge import cdp as C
from lm27.bridge import fsio, js
from lm27.bridge import messages as _messages
from lm27.bridge import settings as S
from lm27.bridge.clock import INF, Deadline, default_clock, iso_now, iso_to_epoch, stamp
from lm27.bridge.messages import Notices, default_notices

# ── 로그인 보류(v1.3 §0.8 V18 — 회사 계정이 없는 PC) ───────────────────────────────────────────────
# 로그인 대기(bridge.loginWaitMin)가 로그인 없이 끝나면 브리지 프로필 health.login_pending 에 남긴다. 다음 수집·분석은 그 대기를
# 다시 하지 않고 LOGIN_PENDING_CHECK_S 만 로그인 상태를 본 뒤 넘어간다(사람에게 설정 변경을 요구하지 않는다). 사람이
# [분석용 Edge 창 앞으로]를 누르거나(front) 로그인이 확인되면 지운다. 로그인 탭이 개인 계정 화면(login.live.com)이면 안내 한 번.
LOGIN_NOTICES = {c: _messages.BR[c] for c in ("BR-LOGIN-PENDING", "BR-LOGIN-PERSONAL")}   # 글자 정본 = 문구 표(B §13)
LOGIN_PERSONAL_TEXT = LOGIN_NOTICES["BR-LOGIN-PERSONAL"][1].rstrip(".")      # 수집 안내(lm27.collect.run)도 같은 글자
LOGIN_CHECKS = ("", "wait", "pending")     # 이 세션의 마지막 로그인 대기: 없음 · 다 기다림 · 보류 상태 짧은 확인

APP_PATHS_KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe"
POLICY_KEY = r"SOFTWARE\Policies\Microsoft\Edge"
EDGE_REL = ("Microsoft", "Edge", "Application", "msedge.exe")
EDGE_ROOT_VARS = ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA")
# 오류 화면만 '죽은 세션'이다. edge:// 내부 화면(강제 Edge 로그인 BrowserSignin=2 등)은 사람이 풀 수 있는 브라우저 로그인으로
# 따로 본다(M6 — 로그인하지 않은 프로필을 '손상'으로 보고 다시 만들지 않는다)
DEAD_SCHEMES = ("chrome-error://", "edge-error://")
EDGE_SCHEME = "edge://"
BLANK_URL = "about:blank"                 # 웹 수집 역할이 시작 주소 없이 열 때(그 뒤 goto(url))
STATES = ("ready", "login_required", "dead", "loading", "wrong_page", "no_input", "edge_page")
# 로그인 화면 AADSTS 오류 번호(숫자만 읽음 — 계정·글 없음) 분류(Microsoft Entra 오류 코드 문서). 장치 기반 조건부 액세스는
# '브라우저(Edge 프로필) 로그인'으로 사람이 풀 수 있다(H1 — 구조적 차단으로 확정하지 않는다). 웹 수집기도 같은 분류를 쓴다.
DEVICE_CA_CODES = frozenset({"50005", "50097", "53000", "53001"})
POLICY_CA_CODES = frozenset({"53002", "53003", "53004", "530032"})
INTERACTIVE_CODES = frozenset({"50158"})   # 외부 보안 과제(사용 약관·타사 MFA) — 사람이 그 화면에서 마친다
LOGIN_HINTS = ("", "edge_profile", "edge_signin", "ca_policy")
ACCOUNT_KINDS = ("work", "personal")       # health.account.kind — 계정 식별 정보 없이 종류만(H4)
OPEN_STAGES = ("probe", "calibrate")       # 계정과 무관하게 보낼 수 있는 글 — 연결 확인 시험 낱말·보정 합성 글(업무 자료 아님)


def aadsts_kind(code) -> str:
    """AADSTS 번호(문자열·정수) → ``device``(Edge 프로필 로그인으로 풀림) · ``policy``(조직 정책 차단) · ``interactive``
    (사람이 그 화면에서 마칠 과제) · ``other`` · ``''``(번호 아님)."""
    c = str(code or "").strip()
    if not re.fullmatch(r"\d{5,6}", c):
        return ""
    if c in DEVICE_CA_CODES:
        return "device"
    if c in POLICY_CA_CODES:
        return "policy"
    if c in INTERACTIVE_CODES:
        return "interactive"
    return "other"
_VER_RX = re.compile(r"^\d+\.\d+\.\d+\.\d+$")
# 전용 프로필 소유 표식(W1 통합 창 — U-4 '본인 전용 프로필'): LM27 이 만든(또는 기본 위치에서 입양한) Edge 프로필 폴더에만
# 있다. 손상 프로필 재생성(이름 바꾸기·옛 .bad-* 정리)은 이 표식이 있고 profile_id 가 맞는 폴더에만 한다.
PROFILE_MARK = "lm27_profile.json"
PROFILE_MARK_SCHEMA = "lm27.edge_profile/1"
# 브라우저 기본 사용자 데이터 루트(회사·개인 기본 프로필 — U-4 불허): 이 아래는 절대 프로필로 쓰지 않는다
_BROWSER_ROOT_RX = re.compile(r"(?i)(?:^|[\\/])(?:microsoft[\\/]edge(?: beta| dev| sxs)?|google[\\/]chrome(?: beta| dev| sxs)?"
                              r"|chromium|bravesoftware[\\/]brave-browser)[\\/]user data(?:[\\/]|$)")
_STILL_ACTIVE = 259


def profile_mark_id(prof) -> str | None:
    """프로필 폴더의 LM27 소유 표식 profile_id(없거나 형식이 다르면 None)."""
    d = fsio.read_json(Path(prof) / PROFILE_MARK, None)
    if not isinstance(d, dict) or d.get("schema") != PROFILE_MARK_SCHEMA or not isinstance(d.get("profile_id"), str):
        return None
    return d["profile_id"]


def foreign_profile(prof, default) -> str | None:
    """그 폴더를 LM27 전용 Edge 프로필로 쓰면 안 되는 이유(None = 써도 됨). ``default`` = ``Paths.edge_profile()``.
      · ``browser_default`` — 브라우저 기본 사용자 데이터 루트(…\\Microsoft\\Edge\\User Data 등) 또는 그 아래(U-4 불허)
      · ``not_lm27`` — 비어 있지 않은데 LM27 표식이 없는 폴더(사용자 문서 폴더·다른 브라우저 프로필 등). 기본 위치는
        LM27 전용 자리라 표식이 없어도 입양한다(이전 판이 만든 프로필)."""
    p = Path(os.path.abspath(os.fspath(prof)))
    if _BROWSER_ROOT_RX.search(str(p)):
        return "browser_default"
    if os.path.normcase(str(p)) == os.path.normcase(os.path.abspath(os.fspath(default))):
        return None
    if p.exists() and not p.is_dir():
        return "not_lm27"
    try:
        nonempty = p.is_dir() and any(p.iterdir())
    except OSError:
        nonempty = True
    if nonempty and profile_mark_id(p) is None:
        return "browser_default" if (p / "Local State").is_file() else "not_lm27"   # 다른 위치의 브라우저 프로필 루트
    return None


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
    # 읽기만 하는 Edge 정책(값의 종류만 — 경로·글 없음, H2·H5·M6)
    policy_user_data_dir: str = "unset"    # forced | unset — UserDataDir 이 있으면 --user-data-dir 가 무시된다
    policy_browser_signin: str = "unset"   # force | enable | disable | unset — BrowserSignin
    policy_inprivate: str = "unset"        # enable | disable | force | unset — InPrivateModeAvailability
    policy_clear_on_exit: str = "unset"    # on | off | unset — ClearBrowsingDataOnExit
    policy_save_cookies: str = "unset"     # set | unset — SaveCookiesOnExit

    @property
    def major(self) -> int:
        try:
            return int(self.version.split(".", 1)[0])
        except ValueError:
            return 0

    @property
    def policy_blocked(self) -> bool:
        return "blocked" in (self.policy_debug, self.policy_devtools)

    def policies(self) -> dict:
        """탐침·진단에 싣는 정책 값(열거값만)."""
        return {"remote_debugging": self.policy_debug, "devtools": self.policy_devtools,
                "user_data_dir": self.policy_user_data_dir, "browser_signin": self.policy_browser_signin,
                "inprivate": self.policy_inprivate, "clear_on_exit": self.policy_clear_on_exit,
                "save_cookies_on_exit": self.policy_save_cookies}


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


def read_edge_policies(reg=winreg_read) -> dict:
    """원격 디버깅 밖의 Edge 정책을 **읽기만** 한다(HKLM 이 HKCU 보다 먼저 — 값의 종류만, 경로 원문은 버린다).
    ``UserDataDir``(REG_SZ — 있으면 forced) · ``BrowserSignin``(0 disable·1 enable·2 force) · ``InPrivateModeAvailability``
    (0 enable·1 disable·2 force) · ``ClearBrowsingDataOnExit``(1 on) · ``SaveCookiesOnExit``(목록 키가 있으면 set)."""
    def first(name):
        for hive in ("HKLM", "HKCU"):
            v = reg(hive, POLICY_KEY, name)
            if v is not None:
                return v
        return None
    udd = first("UserDataDir")
    bs = first("BrowserSignin")
    ip = first("InPrivateModeAvailability")
    co = first("ClearBrowsingDataOnExit")
    sc = None
    for hive in ("HKLM", "HKCU"):
        sc = sc or reg(hive, POLICY_KEY + r"\SaveCookiesOnExit", "1")
    return {"user_data_dir": "forced" if isinstance(udd, str) and udd.strip() else "unset",
            "browser_signin": {0: "disable", 1: "enable", 2: "force"}.get(bs, "unset") if isinstance(bs, int) else "unset",
            "inprivate": {0: "enable", 1: "disable", 2: "force"}.get(ip, "unset") if isinstance(ip, int) else "unset",
            "clear_on_exit": ("on" if co else "off") if isinstance(co, int) else "unset",
            "save_cookies": "set" if sc else "unset"}


def edge_info(finder=None, policy_reader=None, environ=None, extra_reader=None) -> EdgeInfo:
    path = (finder or (lambda: find_edge(environ=environ)))() or ""
    dbg, dev = (policy_reader or read_policy)()
    try:
        ex = (extra_reader or read_edge_policies)() or {}
    except OSError:
        ex = {}
    return EdgeInfo(path=path, version=edge_version(path), policy_debug=dbg, policy_devtools=dev,
                    policy_user_data_dir=str(ex.get("user_data_dir") or "unset"),
                    policy_browser_signin=str(ex.get("browser_signin") or "unset"),
                    policy_inprivate=str(ex.get("inprivate") or "unset"),
                    policy_clear_on_exit=str(ex.get("clear_on_exit") or "unset"),
                    policy_save_cookies=str(ex.get("save_cookies") or "unset"))


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
    if S.host_in(host_of(url), cfg.login_hosts):
        return "login_required", ""
    if url.startswith(EDGE_SCHEME):
        return "edge_page", ""                       # Edge 내부 화면(강제 로그인 등) — 죽은 세션이 아니다(M6)
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
                 tracer=None, pid: int | None = None, pid_ctime: int | None = None, policy_extra_reader=None):
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
        self.policy_extra_reader = policy_extra_reader
        self.proc_probe = proc_probe or process_alive
        self.in_use = in_use or profile_in_use
        self.notices = notices if notices is not None else default_notices()
        self.environ = os.environ if environ is None else environ
        self.tracer = tracer
        if url is not None and not str(url).startswith("https://"):
            raise ValueError("EdgeSession: 시작 주소(url=)는 https:// 로 시작해야 합니다")
        self.url = url or (cfg.url if role == "bridge" else BLANK_URL)
        self.profile = BridgeProfile(paths)
        self.lock = SessionLock(paths, self.clock, role=role, run_id=self.run_id,
                                proc_probe=self.proc_probe, pid=pid, pid_ctime=pid_ctime)
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
        self._last_host = ""                 # 마지막으로 본 자기 탭 호스트(로그인 화면 종류 판정 — 기록하지 않음)
        self._pending_checked = False        # 이 세션에서 보류 상태 짧은 확인을 이미 했다(다음 확인은 한 번 보기만)
        self.login_check = ""                # LOGIN_CHECKS — 웹 수집기가 상태 줄에 싣는다(V18 skipped=login_pending)
        self.login_account = ""              # "personal" = 개인 계정 화면을 봄(회사 계정 아님)
        self.login_seen: set = set()         # 이 세션이 본 로그인 화면 종류 {"org", "personal"}(호스트 원문은 두지 않는다, H4)
        self.login_hint = ""                 # LOGIN_HINTS — 사람이 풀 길(Edge 프로필 로그인 등, H1·M6)
        self.aadsts = ""                     # 로그인 화면의 AADSTS 번호(숫자만 — 진단)
        self._held = False                   # 마지막 로그인 대기가 로그인 없이 끝나 보류가 남음(O-18 ⑤ — runner 가 본다)
        self._in_login_wait = False
        self._launched_fresh = False         # 이 세션이 Edge 를 새로 띄웠다(로그인 유지 진단 — H2)
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
        self.info.profile_dir = str(self._resolve_profile_dir())
        self._acquire_lock()
        self.edge = edge_info(self.edge_finder, self.policy_reader, self.environ, self.policy_extra_reader)
        self._recover_dead_profile()
        port, how = self.choose_port()
        self.info.port = port
        self.info.origin_mode = self.profile.load()["health"].get("origin_mode") or "none"
        if how == "launch":
            if not self.edge.path:
                raise PhaseError("edge_not_found")
            if self.edge.policy_user_data_dir == "forced":
                # UserDataDir 정책이면 --user-data-dir 가 무시되고 사용자 본 Edge(회사 기본 프로필)가 뜬다 — 띄우지 않는다(H5·U-4)
                self.events.append("udd_forced")
                raise PhaseError("policy_blocked", why="user_data_dir_forced")
            self._launch(port)
            self._launched_fresh = True
        self._attach(port)
        if how == "reuse":
            self._adopt_front_launch()
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
                if self.hold_active():
                    self._keep_open()                      # 한 작업(수집→분석) 동안은 로그인된 창을 이어 쓴다(H2)
                else:
                    self._browser_close()
                    self._forget_launch(("front_launch", "kept_launch"))
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
                h["login_ok_browser"] = self.info.browser_id   # 로그인 유지 진단(H2) — 브라우저 실행 표지(계정 아님)
                h.pop("login_pending", None)                   # 로그인 확인 = 보류 해제(V18)
            elif kind == "origin_explicit":
                h["origin_mode"] = "explicit"
        self.profile.update(put)

    # ── 로그인 보류(v1.3 §0.8 V18) ─────────────────────────────────────
    def login_pending(self) -> dict | None:
        """브리지 프로필 ``health.login_pending``(지난 로그인 대기가 로그인 없이 끝남) — 없으면 None."""
        v = self.profile.load()["health"].get("login_pending")
        return v if isinstance(v, dict) else None

    def login_wait_s(self, pending=None) -> float:
        """이번 로그인 대기 상한(초). 보류 중이면 ``LOGIN_PENDING_CHECK_S``(이 세션에서 이미 짧게 확인했으면 0 — 한 번 보기만),
        아니면 ``bridge.loginWaitMin``."""
        if pending is None:
            pending = self.login_pending()
        if pending:
            return 0.0 if self._pending_checked else S.LOGIN_PENDING_CHECK_S
        return float(self.cfg.login_wait_min) * 60.0

    def _mark_login_pending(self) -> None:
        account = self.login_account

        def put(d):
            h = d.setdefault("health", {})
            cur = h.get("login_pending") if isinstance(h.get("login_pending"), dict) else {}
            now = iso_now(self.clock)
            h["login_pending"] = {"since": str(cur.get("since") or now), "checked": now, "role": self.role,
                                  "account": account or str(cur.get("account") or ""),
                                  "hint": self.login_hint or str(cur.get("hint") or "")}
        try:
            self.profile.update(put)
        except OSError:
            pass

    def clear_login_pending(self, why: str = "login_ok") -> bool:
        """보류 해제(로그인 확인·[분석용 Edge 창 앞으로]). 보류가 없었으면 쓰지 않는다. 반환: 지웠는가."""
        if not self.login_pending():
            return False

        def put(d):
            d.setdefault("health", {}).pop("login_pending", None)
        try:
            self.profile.update(put)
        except OSError:
            return False
        self._pending_checked = False
        self.events.append("login_pending_cleared:" + why)
        return True

    def login_ok(self) -> None:
        """웹 수집 역할이 로그인 뒤 화면(사서함·팀즈)을 확인했을 때 — 보류 해제 + 로그인 확인 시각(브리지는 ``ensure_ready``)."""
        self.clear_login_pending("login_ok")
        self._held = False
        try:
            self.record_health("ready")
        except OSError:
            pass

    def login_held(self) -> bool:
        """이 세션의 마지막 로그인 대기가 로그인 없이 끝나 보류가 남았는가(다 기다렸거나 보류 중 짧은 확인). 바깥 마감에 잘린
        대기는 아니다. runner 는 이때 AI 단계를 2-strike 치명 대신 바로 skipped(login_pending)로 넘긴다(O-18 ⑤)."""
        return bool(self._held) and self.login_pending() is not None

    def mark_login_pending(self) -> None:
        """웹 수집 역할이 세션 대기 밖에서 로그인을 다 기다렸거나(회사 SSO 등 모르는 화면) 개인 계정 사서함에 닿았을 때 —
        보류를 남긴다(다음 수집·분석은 짧게 확인 — V18)."""
        was = self.login_pending()
        self._pending_checked = True
        self.login_check = "pending" if was else (self.login_check or "wait")
        self._mark_login_pending()

    def _see_host(self, host: str) -> None:
        self._last_host = host or ""
        if S.host_in(self._last_host, S.PERSONAL_LOGIN_HOSTS):
            self.login_seen.add("personal")
            self.note_login_account("personal")
        elif S.host_in(self._last_host, self.cfg.login_hosts):
            self.login_seen.add("org")

    # ── 계정 종류(H4 — 개인 Microsoft 계정 Copilot 에는 업무 자료를 보내지 않는다) ─────────────────────
    def saved_account(self) -> str:
        """브리지 프로필 ``health.account.kind``(work|personal|'') — 이 프로필에서 마지막으로 확인한 로그인 계정 종류."""
        a = self.profile.load()["health"].get("account")
        k = a.get("kind") if isinstance(a, dict) else ""
        return k if k in ACCOUNT_KINDS else ""

    def record_account(self, kind: str, by: str) -> None:
        """계정 종류를 남긴다(식별 정보 없이 종류·근거 코드·시각만). 같은 값이면 쓰지 않는다."""
        if kind not in ACCOUNT_KINDS:
            return
        cur = self.profile.load()["health"].get("account")
        if isinstance(cur, dict) and cur.get("kind") == kind and cur.get("by") == by:
            return

        def put(d):
            d.setdefault("health", {})["account"] = {"kind": kind, "by": by, "at": iso_now(self.clock)}
        try:
            self.profile.update(put)
        except OSError:
            pass

    def send_block(self, stage: str = "") -> str:
        """전송 직전 계정 관문(H4) — 회사(Entra) 계정으로 확인되지 않았으면 업무 자료를 넣지 않는다. 연결 확인(probe)의 시험
        낱말과 보정(calibrate)의 합성 글은 예외(화면 조작 확인). 세션이 열 때 준비되지 않아 판별이 아직이면 지금 한다.
        반환: '' = 보내도 됨, 아니면 ``personal_account``·``account_unknown``."""
        if self.role != "bridge" or stage in OPEN_STAGES:
            return ""
        if getattr(self.env, "account", None) is None:
            try:
                self.ensure_work_mode()
                from lm27.bridge.env import detect_env
                detect_env(self)
                self.info.env = self.env
            except (OSError, C.CdpError, PhaseError):
                return "account_unknown"
        acct = getattr(self.env, "account", "unknown")
        return "" if acct == "work" else ("personal_account" if acct == "personal" else "account_unknown")

    def _note_account_after_login(self) -> None:
        """로그인 흐름을 거쳐 Copilot 이 준비됐을 때 — 이 세션이 본 로그인 화면 종류를 남긴다(개인 계정 화면이 우선)."""
        if "personal" in self.login_seen:
            self.record_account("personal", "personal_login")
        elif "org" in self.login_seen:
            self.record_account("work", "org_login")

    def note_login_account(self, account: str) -> None:
        """로그인 화면·도착 화면이 회사(조직) 계정이 아님(``personal``) — 안내 한 번(BR-LOGIN-PERSONAL). 보류에 계정 종류를 남긴다."""
        if account != "personal" or self.login_account == "personal":
            return
        self.login_account = "personal"
        self.events.append("login_personal")
        self.notices.notify("BR-LOGIN-PERSONAL")
        self.record_account("personal", "personal_login")      # 같은 프로필의 Copilot 도 개인 계정일 수 있다(H4)

    def _login_wait(self, dl: Deadline, poll, ok=None) -> str:
        """로그인 대기 한 번(B §4.7 · V18). ``poll(상한 초, 간격 초)`` → 대기 뒤 상태, ``ok(상태)`` = 로그인을 넘어섰나(기본:
        로그인·로딩이 아님). 보류 중이면 짧게(창을 앞으로 띄우지 않음), 아니면 먼저 ``LOGIN_GRACE_S`` 동안 1초 간격으로 보고 —
        SSO 로 한순간 지나가는 로그인 화면이면 창을 앞으로 띄우지도 안내하지도 않는다(L1) — 그래도 로그인 화면이면 BR-LOGIN 안내
        + ``bridge.loginWaitMin``. 로그인 화면의 AADSTS 번호가 장치 기반 조건부 액세스면 'Edge 프로필 로그인' 안내(H1). 로그인
        화면에서 끝났고 다 기다렸으면(또는 보류 확인이면) 보류를 남긴다 — 바깥 마감에 잘린 대기는 남기지 않는다."""
        ok = ok or (lambda s: s not in ("login_required", "loading"))
        pending = self.login_pending()
        want = self.login_wait_s(pending)
        avail = dl.cap(want)
        t0 = self.clock.mono()
        self._in_login_wait = True
        try:
            if pending:
                if str(pending.get("hint") or "") in ("edge_profile", "edge_signin"):
                    self.notices.notify("BR-LOGIN-EDGE")      # 지난번에 본 원인(장치 확인·Edge 로그인)을 먼저 알린다
                self.notices.notify("BR-LOGIN-PENDING", sec=int(S.LOGIN_PENDING_CHECK_S))
                self.events.append("login_pending_check")
                st = poll(avail, S.LOGIN_POLL_S)
            else:
                st = poll(min(avail, S.LOGIN_GRACE_S), S.IDENTITY_POLL_S)
                if ok(st):
                    self.events.append("login_passed")      # SSO 통과 — 안내·창 앞으로 없음(L1)
                    self._held = False
                    return st
                self._check_nopersist()
                self.activate()
                self.notices.notify("BR-LOGIN", loginWaitMin=self.cfg.login_wait_min)
                self.events.append("login_wait")
                st = poll(max(0.0, avail - (self.clock.mono() - t0)), S.LOGIN_POLL_S)
        finally:
            self._in_login_wait = False
        if ok(st):
            self.notices.notify("BR-LOGIN-OK")
            self._held = False
            return st
        if st in ("login_required", "loading"):
            full = avail >= want
            self.login_check = "pending" if pending else ("wait" if full else self.login_check)
            if pending or full:
                self._pending_checked = True
                self._mark_login_pending()
                self._held = True
        return st

    def _check_aadsts(self) -> None:
        """로그인 화면의 AADSTS 번호(숫자만)를 읽어 사람이 풀 길을 정한다 — 장치 기반 조건부 액세스면 Edge 프로필 로그인 안내(H1).
        로그인 대기 중 로그인 호스트에서만 부른다(페이지 글은 돌려받지 않는다)."""
        try:
            v = self.eval(js.aadsts())
        except (OSError, C.CdpError, PhaseError):
            return
        kind = aadsts_kind(v)
        if not kind or str(v) == self.aadsts:
            return
        self.aadsts = str(v)
        self.events.append("aadsts:" + kind)
        if kind == "device" and self.login_hint != "edge_profile":
            self.login_hint = "edge_profile"
            self.notices.notify("BR-LOGIN-EDGE")
        elif kind == "policy" and not self.login_hint:
            self.login_hint = "ca_policy"

    def _check_nopersist(self) -> None:
        """새로 띄운 Edge 가 로그인 화면인데 직전 로그인 확인이 다른 Edge 실행에서 ``LOGIN_PERSIST_DAYS`` 안이었다 — 로그인이
        Edge 를 닫으며 풀렸다(KMSI 없음·종료 시 삭제 정책 등). 안내 한 번 + ``health.login_nopersist``(H2)."""
        if not self._launched_fresh:
            return
        h = self.profile.load()["health"]
        t = iso_to_epoch(str(h.get("login_ok_at") or ""))
        if t is None or self.clock.now() - t > S.LOGIN_PERSIST_DAYS * 86400.0:
            return
        if not h.get("login_ok_browser") or h.get("login_ok_browser") == self.info.browser_id:
            return
        prev = h.get("login_nopersist") if isinstance(h.get("login_nopersist"), dict) else {}

        def put(d):
            d.setdefault("health", {})["login_nopersist"] = {"at": iso_now(self.clock), "n": int(prev.get("n") or 0) + 1,
                                                            "clear_on_exit": self.edge.policy_clear_on_exit}
        try:
            self.profile.update(put)
        except OSError:
            pass
        self.events.append("login_nopersist")
        self.notices.notify("BR-LOGIN-NOPERSIST")

    def recover(self, phase: str) -> None:
        """치명 실패 1차 복구(B §7.7 — ``lm27.bridge.runner.recover`` 가 세션의 이 메서드를 쓴다). 로그인 보류 중이면 다시
        기다리지 않는다(V18 — 사람이 없는 PC 에서 단계마다 1분씩 늘지 않게). 그 밖은 runner 의 기본 복구와 같다."""
        try:
            if phase == "login_required":
                if self.login_pending():
                    self.events.append("recover_login_skipped")
                    return
                self.navigate()
                self.poll_identity(S.LOGIN_RECHECK_S, until=lambda st: st not in ("login_required", "loading"))
            elif phase in ("input_not_found", "dead_session"):
                self.reload()
                self.poll_identity(float(self.cfg.ready_wait_sec))
        except (OSError, C.CdpError, PhaseError):
            pass

    def _resolve_profile_dir(self) -> Path:
        """설정 프로필 폴더가 LM27 전용이 아니면(``foreign_profile``) 손대지 않고 기본 전용 프로필로 돌아간다 — U-4 '회사
        기본 Edge 프로필 불허'·남의 폴더 보호. 사람에게 설정 변경을 요구하지 않고 안내 한 번(BR-PROFILE-FOREIGN)."""
        prof = self.cfg.profile_dir(self.paths)
        default = Path(self.paths.edge_profile())
        why = foreign_profile(prof, default)
        if why:
            self.events.append("profile_foreign:" + why)
            self.notices.notify("BR-PROFILE-FOREIGN")
            prof = default
        return prof

    def _mark_profile(self, prof: Path) -> None:
        """LM27 소유 표식(profile_id)을 프로필 폴더에 쓴다 — 새로 만들 때·기본 위치 입양 때."""
        pid = self.profile.profile_id() or self.profile.new_profile_id()
        fsio.write_atomic(Path(prof) / PROFILE_MARK, {"schema": PROFILE_MARK_SCHEMA, "profile_id": pid})

    def _owned_profile(self, prof: Path) -> bool:
        """표식이 있고 그 profile_id 가 지금 상태 파일(bridge_profile·profile_id)의 값과 같은가."""
        mid = profile_mark_id(prof)
        return mid is not None and mid == self.profile.profile_id()

    def _recover_dead_profile(self) -> bool:
        """서로 다른 호출 2회의 dead_session → Edge 를 닫고 프로필을 ``<이름>.bad-<시각>`` 로 바꿔 새 프로필(B §4.7).
        사람에게 폴더 조작을 요구하지 않는다. LM27 소유 표식이 있고 profile_id 가 맞는 폴더만 이름을 바꾸고, 옛
        ``.bad-*`` 도 표식이 든 것만 지운다(W1 통합 창 — 설정이 가리킨 남의 폴더를 바꾸거나 지우던 결함). Edge 정책이
        브라우저 로그인을 강제하거나(BrowserSignin=2) InPrivate 만 허용하면(=2) 다시 만들어도 같으므로 하지 않는다(M6)."""
        runs = {x.get("run") for x in self.profile.load()["health"].get("dead_sessions") or [] if isinstance(x, dict)}
        if len(runs) < S.DEAD_SESSION_LIMIT:
            return False
        if self.edge.policy_browser_signin == "force" or self.edge.policy_inprivate == "force":
            self.events.append("recreate_skipped_policy")
            return False
        prof = Path(self.info.profile_dir)
        dap = C.read_devtools_active_port(prof)
        if dap and C.debugger_alive(self.http, dap[0]) and self._owns(dap[0], dap[1]):
            self._close_browser_on(dap[0])
        if prof.exists():
            if not self._owned_profile(prof):
                self.events.append("bad_rename_refused")       # 우리 것이 아니면 이름을 바꾸지도 지우지도 않는다
                return False
            bad = prof.with_name(f"{prof.name}.bad-{stamp(self.clock)}")
            try:
                fsio.rename_dir(prof, bad)
            except OSError:
                self.events.append("bad_rename_failed")
                return False
            olds = sorted((p for p in prof.parent.glob(prof.name + ".bad-*")
                           if p.is_dir() and profile_mark_id(p) is not None), key=lambda p: p.name)
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
        if profile_mark_id(prof) != self.profile.profile_id():
            self._mark_profile(prof)                    # 새 전용 프로필(또는 기본 위치 입양) — 소유 표식
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
        self.info.launched_by_us = False
        if alive and not self.in_use(prof):
            # 살아 있는데 우리 프로필 폴더를 쥐고 있지 않다 — 정책(UserDataDir 등)으로 다른 폴더(사용자 본 Edge)로 떴을 수 있다.
            # 남의 Edge 는 죽이지 않는다(H5·U-4). 포트도 열리지 않았으니 자동 연결은 못 한다.
            self.events.append("kill_refused_not_ours")
            if self.edge.policy_blocked:
                raise PhaseError("policy_blocked", alive=True)
            raise PhaseError("launch_failed", alive=True, why="not_our_profile")
        if alive:
            self._proc.kill_tree()                         # 우리 프로필로 뜬 응답 없는 Edge 는 정리한다
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
        url = str(r.get("url") or "") if isinstance(r, dict) else ""
        host = host_of(url)
        if isinstance(r, dict):
            self._see_host(host)
        st, strength = classify_identity(r, self.cfg)
        if st == "login_required":
            if self._in_login_wait:
                self._check_aadsts()
        elif st == "wrong_page" and url.startswith("https://") and host and not S.MS_APP_HOST_RX.search(host):
            # Copilot 도 Microsoft 앱도 아닌 호스트 = 회사 IdP(AD FS·PingFederate 등) 로그인 화면일 수 있다 — 사람이 입력 중일
            # 수 있으니 떠나지 않고 로그인 대기로 본다(H3). 우리 탭은 Copilot 으로만 이동하므로 다른 까닭은 드물다.
            if "idp_host" not in self.events:
                self.events.append("idp_host")
            st = "login_required"
        elif st == "edge_page" and self.login_hint == "edge_signin":
            st = "login_required"                      # Edge 로그인 화면에 머묾 — 사람이 Edge 에 로그인할 때까지(M6)
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

        def reopen(from_state):
            """Copilot 주소로 한 번 다시 연다(대기 중에는 하지 않는다 — 사람이 입력 중인 로그인 화면을 떠나지 않게, H3)."""
            self.navigate()
            return self.poll_identity(dl.cap(S.IDENTITY_SETTLE_S), until=lambda s: s not in ("loading", from_state))
        try:
            st = self.identity()
            if st == "wrong_page":
                st = reopen("wrong_page")
            if st == "edge_page":
                st = reopen("edge_page")
                if st == "edge_page":                      # Edge 로그인(강제)·내부 화면에 머묾 — 사람이 Edge 에 로그인(M6)
                    self.login_hint = "edge_signin"
                    self.events.append("edge_page")
                    self.notices.notify("BR-LOGIN-EDGE")
                    st = "login_required"
            if st == "loading":
                st = self.poll_identity(dl.cap(c.ready_wait_sec), until=lambda s: s != "loading")
            if st == "login_required":
                st = self._login_wait(dl, lambda up_to, every: self.poll_identity(
                    up_to, every=every, until=lambda s: s not in ("login_required", "loading")))
                if st in ("login_required", "loading"):
                    return "login_required"
                if st in ("wrong_page", "edge_page"):      # 로그인을 마치고 Copilot 이 아닌 Microsoft 화면에 닿음 — 한 번 다시 연다
                    st = reopen(st)
                if st == "loading":
                    st = self.poll_identity(dl.cap(c.ready_wait_sec), until=lambda s: s != "loading")
            if st == "no_input":
                st = self.poll_identity(dl.cap(c.ready_wait_sec), until=lambda s: s != "no_input")
                if st == "no_input":
                    self.reload()
                    st = self.poll_identity(dl.cap(c.ready_wait_sec), until=lambda s: s != "no_input")
                if st in ("no_input", "loading"):
                    if st == "no_input":
                        self._observe_chat(False)          # Copilot 주소·로드 끝·입력창 없음 — 조직 차단 안내 화면일 수 있다(M5)
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
            if st in ("login_required", "edge_page"):
                return "login_required"
            if st == "ready" and not self._ready_recorded:
                self._ready_recorded = True
                self._held = False
                self.record_health("ready")
                self._note_account_after_login()
                self._observe_chat(True)
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
            self._see_host(p["host"])
            if c.login_host(p["host"]):
                if self._in_login_wait:
                    self._check_aadsts()
                return "login_required"
            if p["url"].startswith(EDGE_SCHEME):
                if self.login_hint != "edge_signin":     # 이동했는데 Edge 내부 화면(강제 Edge 로그인 등) — 사람이 Edge 에 로그인(M6)
                    self.login_hint = "edge_signin"
                    self.events.append("edge_page")
                    self.notices.notify("BR-LOGIN-EDGE")
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
                st = self._login_wait(dl, lambda up_to, every: poll(up_to, every,
                                                                    lambda s: s not in ("login_required", "loading")),
                                      ok=lambda s: s == "ready")
                if st != "ready":
                    return "login_required"
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
        """업무/웹 전환 상태를 읽고, preferWorkMode 이고 웹이면 업무 쪽을 1회 누른 뒤 다시 확인. 판별 불가면 unknown.
        단일 토글 'Work IQ'(2026-08 개편 — 업무·웹 탭을 대체)는 누름 상태가 false 일 때만 한 번 누른다(H13 — 상태를 모르면
        누르지 않는다: 켜져 있는 토글을 끄지 않게)."""
        c = self.cfg.dom
        try:
            r = self.eval(js.work_mode(c.work_labels, c.web_labels, False, c.toggle_labels)) or {}
            mode = r.get("mode") if r.get("found") else "unknown"
            if self.cfg.prefer_work_mode and mode == "web":
                self.eval(js.work_mode(c.work_labels, c.web_labels, True, c.toggle_labels))
                self.clock.sleep(S.WORK_MODE_SETTLE_S)
                r = self.eval(js.work_mode(c.work_labels, c.web_labels, False, c.toggle_labels)) or {}
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
        names = S.model_names(model)                       # '|' 별칭 + 한국어 기본 이름의 영어 표기(L11)
        try:
            r1 = self.eval(js.pick_model(names, c.model_button_labels)) or {}
            if r1.get("already"):
                return ModelNote(model, str(r1.get("cur") or model)[:S.MODEL_NOTE_MAX], True, (), "already")
            if not r1.get("ok"):
                return ModelNote(model, "", False, (), "selector_not_found")
            self.clock.sleep(S.MENU_SETTLE_S)
            if not r1.get("alreadyOpen"):
                if not (self.eval(js.menu_open()) or {}).get("open"):
                    self.eval(js.pick_model(names, c.model_button_labels))
                    self.clock.sleep(S.MENU_REOPEN_S)
            seen: tuple = ()
            for _depth in range(S.MENU_DEPTH):
                r2 = self.eval(js.pick_model_item(names)) or {}
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
                + c.work_labels + c.web_labels + c.web_grounding_labels + c.toggle_labels + c.account_labels
                + c.shield_labels)
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

    # ── 창 앞으로(화면 [분석용 Edge 창 앞으로] — 사람이 한 번 로그인할 창을 찾게) ──────────────────
    def front(self) -> dict:
        """전용 프로필 Edge 창을 사람 앞으로. 이 프로필의 Edge 가 떠 있으면(소유 확인 — 남의 디버그 Edge 에는 붙지 않는다) 그
        창을 앞으로(최소화면 되살림), 없으면 브리지와 같은 방식(같은 프로필·포트·기동 인자)으로 띄워 ``bridge.url``(Microsoft 365
        — 로그인 전이면 로그인 화면)을 연다. 띄운 창은 닫지 않는다 — 사람이 로그인하도록 둔다(다음 세션이 이어받아 끝날 때
        ``closeOnExit`` 를 적용한다 — L09). 자격 증명은 입력하지 않는다(B4). 사람이 이 버튼을 눌렀으므로 로그인 보류(V18)를
        지운다 — 다음 수집·분석은 로그인을 다시 기다린다. 탭 내용은 읽지 않는다(탭 id 만).
        반환 ``{state: front|launched|<단계>, port, restored, foreground, notices, login_pending_cleared?}``."""
        out: dict = {"state": "", "port": 0, "restored": False, "foreground": False}
        try:
            if self.clear_login_pending("front"):          # 사람이 로그인하러 왔다 — 다음 수집·분석은 다시 기다린다(V18)
                out["login_pending_cleared"] = True
        except OSError:
            pass
        try:
            if str(self.environ.get("LM_NO_BROWSER", "")).strip() not in ("", "0"):
                raise PhaseError("edge_not_found", why="no_browser")
            self.info.profile_dir = str(self._resolve_profile_dir())
            self.info.origin_mode = self.profile.load()["health"].get("origin_mode") or "none"
            last = self.profile.load().get("last_session") or {}
            self._targets = {r: list(v) for r, v in (last.get("targets") or {}).items() if isinstance(v, list)}
            port, how = self.choose_port()
            if how == "reuse":
                self._touch_launch(port)                # 사람이 쓰는 중 — 유휴 정리(L12) 시계를 다시 맞춘다
            if how == "launch":
                self.lock.acquire(self._targets)        # 기동 순간만 잡는다(재시도 대기 없음 — 화면 요청 안)
                try:
                    self.edge = edge_info(self.edge_finder, self.policy_reader, self.environ, self.policy_extra_reader)
                    if not self.edge.path:
                        raise PhaseError("edge_not_found")
                    if self.edge.policy_user_data_dir == "forced":     # 사용자 본 Edge 가 뜬다 — 띄우지 않는다(H5)
                        raise PhaseError("policy_blocked", why="user_data_dir_forced")
                    self.info.port = port
                    self._launch(port)
                    v = C.version(self.http, port)
                    self.info.browser_id = C.browser_id(str((v or {}).get("webSocketDebuggerUrl") or ""))
                    pages = self._pages()
                    if len(pages) == 1 and pages[0].get("id"):
                        self._targets[self.role] = [str(pages[0]["id"])]     # 다음 브리지 실행이 이 탭을 제 탭으로 쓴다
                    self._save_last_session()
                    self._note_front_launch(port)       # 다음 세션이 이 Edge 를 '우리가 띄운 것'으로 이어받는다(L09)
                finally:
                    self.lock.release()
                if self._proc is not None and hasattr(self._proc, "close"):
                    self._proc.close()                  # 창은 그대로 — 표준 입출력 손잡이만 놓는다
            out["state"], out["port"] = ("launched" if how == "launch" else "front"), port
            out["restored"], out["foreground"] = self._bring_to_front(port)
        except PhaseError as e:
            out["state"] = e.phase
            out["why"] = str(e.info.get("why") or e.info.get("owner_role") or "")
        except (OSError, C.CdpError, ValueError) as e:
            out["state"] = "launch_failed"
            out["why"] = type(e).__name__
        out["notices"] = list(getattr(self.notices, "shown", ()))
        self.events.append("front:" + out["state"])
        return out

    def _note_front_launch(self, port: int) -> None:
        """[분석용 Edge 창 앞으로]가 띄운 Edge(브라우저 ID·포트)를 브리지 프로필 ``front_launch`` 에 적는다. 그 창은 사람이
        로그인하도록 닫지 않지만, 다음 세션이 '재사용'으로 붙으면 그 세션이 띄운 것처럼 ``closeOnExit`` 를 적용한다(L09 —
        디버그 포트가 열린 Edge 가 끝없이 남지 않게)."""
        bid = self.info.browser_id
        if not bid:
            return

        def put(d):
            d["front_launch"] = {"browser_id": bid, "port": int(port), "at": iso_now(self.clock)}
        try:
            self.profile.update(put)
        except OSError:
            pass

    def _adopt_front_launch(self) -> bool:
        """재사용으로 붙은 Edge 가 [분석용 Edge 창 앞으로]가 띄운 그것(``front_launch``)이거나 작업 보류 동안 앞 세션이 닫지 않고
        남긴 그것(``kept_launch`` — H2)이면(브라우저 ID·포트 일치) 이 세션이 띄운 것으로 이어받는다 — 끝날 때 ``closeOnExit`` 가
        적용된다(L09). 이어받은 기록은 지운다(한 번만 — 이 세션이 닫거나 보류 중이면 다시 남긴다)."""
        d0 = self.profile.load()
        found = {k: d0.get(k) for k in ("front_launch", "kept_launch")
                 if isinstance(d0.get(k), dict) and d0[k].get("browser_id")}
        if not found:
            return False
        same = [k for k, fl in found.items()
                if fl.get("browser_id") == self.info.browser_id and fl.get("port") == self.info.port]

        def put(d):
            for k in found:
                d.pop(k, None)
        try:
            self.profile.update(put)
        except OSError:
            pass
        if not same:
            return False                                    # 그 Edge 는 이미 닫혔다(다른 브라우저) — 기록만 정리
        self.info.launched_by_us = True
        self.events.extend("adopt_front" if k == "front_launch" else "adopt_kept" for k in same)
        self.lock.update(launched_by_us=True)
        return True

    # ── 한 작업(수집→분석) 동안 로그인된 창 이어 쓰기(H2) · 남은 디버그 포트 Edge 정리(L12) ─────────────────
    def hold_active(self) -> bool:
        """작업 보류 표지(``edge_hold``)가 살아 있는가 — 주인 프로세스가 살아 있고 최대 수명(``EDGE_HOLD_MAX_S``) 안."""
        h = self.profile.load().get("edge_hold")
        if not isinstance(h, dict):
            return False
        try:
            until = float(h.get("until_s") or 0)
        except (TypeError, ValueError):
            return False
        pid = h.get("pid")
        if self.clock.now() >= until or not isinstance(pid, int) or isinstance(pid, bool):
            return False
        return bool(self.proc_probe(pid, h.get("pid_ctime") or None))

    def begin_hold(self, max_s: float | None = None) -> str:
        """작업 보류 시작 — 이 프로세스(주인)가 살아 있는 동안(최대 ``max_s``) 브리지·웹 수집 세션은 우리가 띄운 Edge 를 닫지 않고
        다음 세션에 넘긴다(로그인 쿠키가 브라우저를 닫을 때 사라지는 회사에서 '한 번 로그인'으로 한 작업을 마치게). 반환: 표지."""
        tok = uuid.uuid4().hex[:12]
        span = float(max_s if max_s is not None else S.EDGE_HOLD_MAX_S)
        rec = {"token": tok, "pid": self.lock.pid, "pid_ctime": self.lock.pid_ctime or 0, "since": iso_now(self.clock),
               "until_s": round(self.clock.now() + span, 1)}

        def put(d):
            d["edge_hold"] = rec
        self.profile.update(put)
        self.events.append("hold_begin")
        return tok

    def end_hold(self, token: str | None = None) -> dict:
        """작업 보류 끝 — 표지를 지우고(같은 표지일 때만, None 이면 무조건), 보류 동안 남겨 둔 우리 Edge 를 닫는다(잠금이 바쁘면
        그 세션이 끝날 때 닫는다). 반환 ``{released, closed[], busy}``."""
        released = False

        def put(d):
            nonlocal released
            h = d.get("edge_hold")
            if isinstance(h, dict) and (token is None or h.get("token") == token):
                d.pop("edge_hold", None)
                released = True
        try:
            self.profile.update(put)
        except OSError:
            pass
        out = self.sweep(("kept_launch",))
        out["released"] = released
        self.events.append("hold_end")
        return out

    def sweep(self, kinds=("front_launch", "kept_launch")) -> dict:
        """남은 디버그 포트 Edge 정리(L12·H2) — ``kept_launch`` 는 작업 보류가 끝났으면, ``front_launch`` 는 ``FRONT_TTL_S``
        넘게 손대지 않았으면, 그 포트의 브라우저 ID 가 기록과 같고 우리 프로필의 것일 때만 ``Browser.close``. 다른 세션이 잠금을
        쥐고 있으면 건드리지 않는다(그 세션이 이어받아 끝날 때 닫는다). 반환 ``{closed[], kept[], busy}``."""
        out: dict = {"closed": [], "kept": [], "busy": False}
        d = self.profile.load()
        recs = {k: d.get(k) for k in kinds if isinstance(d.get(k), dict) and d[k].get("browser_id")}
        if not recs:
            return out
        hold = self.hold_active()
        due = []
        for k, rec in recs.items():
            t = iso_to_epoch(str(rec.get("at") or ""))
            if (k == "kept_launch" and hold) or (k == "front_launch" and t is not None
                                                 and self.clock.now() - t < S.FRONT_TTL_S):
                out["kept"].append(k)
            else:
                due.append(k)
        if not due:
            return out
        try:
            self.lock.acquire({})
        except PhaseError:
            out["busy"] = True
            return out
        try:
            if not self.info.profile_dir:
                self.info.profile_dir = str(self._resolve_profile_dir())
            self.info.origin_mode = d["health"].get("origin_mode") or "none"
            dap = C.read_devtools_active_port(self.info.profile_dir)
            for k in due:
                rec = recs[k]
                port = rec.get("port")
                if isinstance(port, int):
                    self.info.port = port
                v = C.version(self.http, port) if isinstance(port, int) else None
                bid = C.browser_id(str((v or {}).get("webSocketDebuggerUrl") or ""))
                if v and bid == rec.get("browser_id") and dap and dap[0] == port and self._owns(port, dap[1]):
                    self._close_browser_on(port)
                    out["closed"].append(k)
            self._forget_launch(tuple(due), any_browser=True)
        finally:
            self.lock.release()
        if out["closed"]:
            self.events.append("sweep_closed")
        return out

    def _keep_open(self) -> None:
        """작업 보류 중 세션 끝 — 우리가 띄운 Edge 를 닫지 않고 다음 세션에 넘긴다. 웹 수집 탭은 빈 화면으로 돌려 사서함·팀즈
        화면을 남기지 않는다(Copilot 탭은 다음 단계가 이어 쓴다). 기록 ``kept_launch``."""
        if self.role != "bridge" and self.cdp is not None:
            try:
                self.call("Page.navigate", {"url": BLANK_URL})
            except (OSError, C.CdpError, PhaseError):
                pass
        bid, port = self.info.browser_id, self.info.port

        def put(d):
            d["kept_launch"] = {"browser_id": bid, "port": int(port), "at": iso_now(self.clock)}
        try:
            self.profile.update(put)
        except OSError:
            pass
        self.events.append("kept_open")

    def _touch_launch(self, port: int) -> None:
        """사람이 [분석용 Edge 창 앞으로]로 다시 찾은 Edge — 기록의 시각을 지금으로(유휴 정리 기준, L12)."""
        v = C.version(self.http, port)
        bid = C.browser_id(str((v or {}).get("webSocketDebuggerUrl") or ""))

        def put(d):
            for k in ("front_launch", "kept_launch"):
                r = d.get(k)
                if isinstance(r, dict) and r.get("browser_id") == bid and r.get("port") == port:
                    r["at"] = iso_now(self.clock)
        if bid:
            try:
                self.profile.update(put)
            except OSError:
                pass

    def _forget_launch(self, keys, *, any_browser: bool = False) -> None:
        """기록을 지운다 — 기본은 이 세션의 브라우저를 가리키는 것만(``any_browser`` 면 무조건)."""
        bid = self.info.browser_id

        def put(d):
            for k in keys:
                r = d.get(k)
                if isinstance(r, dict) and (any_browser or r.get("browser_id") == bid):
                    d.pop(k, None)
        try:
            self.profile.update(put)
        except OSError:
            pass

    def _observe_chat(self, ok: bool) -> None:
        """Copilot 채팅 입력창 관찰(브리지만, M5) — 조직 정책 차단 안내 화면을 서로 다른 날 반복해 보면 한동안 열지 않는다."""
        if self.role != "bridge":
            return
        from lm27.bridge.capability import ChatAccess
        try:
            ca = ChatAccess(self.profile, self.cfg, self.clock)
            if ok:
                ca.observe_ok()
            elif ca.observe_blocked():
                self.events.append("chat_unavailable")
        except OSError:
            pass

    def _front_connect(self, ws_url: str, port: int):
        """창 앞으로 전용 연결 — Origin 없이, 403 이면 127.0.0.1:<port> Origin 으로 한 번 더(B §4.4 와 같은 규칙)."""
        try:
            return self.connector.connect(ws_url, origin=self._origin())
        except C.HandshakeRejected as e:
            if e.status != 403 or self._origin():
                raise
            return self.connector.connect(ws_url, origin=f"http://127.0.0.1:{port}")

    def _bring_to_front(self, port: int) -> tuple[bool, bool]:
        """그 포트 브라우저의 창을 앞으로 — 우리 탭(지난 세션 기록)이 있으면 그 탭, 없으면 첫 페이지 탭의 창:
        ① ``Browser.getWindowForTarget`` → 최소화면 ``setWindowBounds(normal)``, 아니면 내렸다 원래 상태로(다른 프로세스 창을
        Windows 가 앞으로 못 올리는 제약 우회) ② ``Page.bringToFront`` ③ ``/json/activate/<id>``. 실패해도 진행.
        반환 (최소화를 되살렸는가, 앞으로 올리기 호출이 하나라도 성공했는가)."""
        self.info.port = port
        pages = self._pages()
        if not pages:
            return False, False
        own = {str(i) for ids in self._targets.values() for i in ids}
        tab = next((t for t in pages if str(t.get("id")) in own), None) or pages[0]
        tid = str(tab.get("id") or "")
        restored = fg = False
        v = C.version(self.http, port)
        if v and tid:
            try:
                b = self._front_connect(str(v.get("webSocketDebuggerUrl") or ""), port)
                try:
                    w = b.call("Browser.getWindowForTarget", {"targetId": tid}, timeout=S.FRONT_CALL_TIMEOUT_S) or {}
                    wid = w.get("windowId")
                    state = str((w.get("bounds") or {}).get("windowState") or "normal")
                    if isinstance(wid, int) and not isinstance(wid, bool):
                        if state == "minimized":
                            b.call("Browser.setWindowBounds", {"windowId": wid, "bounds": {"windowState": "normal"}},
                                   timeout=S.FRONT_CALL_TIMEOUT_S)
                            restored = True
                        elif state in ("normal", "maximized"):
                            b.call("Browser.setWindowBounds", {"windowId": wid, "bounds": {"windowState": "minimized"}},
                                   timeout=S.FRONT_CALL_TIMEOUT_S)
                            self.clock.sleep(S.FRONT_NUDGE_S)
                            b.call("Browser.setWindowBounds", {"windowId": wid, "bounds": {"windowState": state}},
                                   timeout=S.FRONT_CALL_TIMEOUT_S)
                        fg = True
                finally:
                    b.close()
            except (OSError, C.CdpError, C.HandshakeRejected, ValueError):
                self.events.append("front_window_failed")
        ws = str(tab.get("webSocketDebuggerUrl") or "")
        if C.local_ws_url(ws):
            try:
                c = self._front_connect(ws, port)
                try:
                    c.call("Page.bringToFront", {}, timeout=S.FRONT_CALL_TIMEOUT_S)
                    fg = True
                finally:
                    c.close()
            except (OSError, C.CdpError, C.HandshakeRejected, ValueError):
                self.events.append("front_tab_failed")
        try:
            self.http.json(port, f"/json/activate/{tid}")
            fg = True
        except C.HTTP_ERRORS:
            pass
        return restored, fg


def front_window(paths=None, *, cfg=None, **kw) -> dict:
    """화면 [분석용 Edge 창 앞으로](R §5.3 · B §10.5) — ``EdgeSession.front()`` 한 번(역할 bridge 의 전용 프로필).
    ``cfg`` = ``lm27.config`` Cfg 또는 ``BridgeSettings``. 알림은 표준 출력으로 내지 않고 결과의 ``notices`` 코드로만 돌려준다
    (화면 서버 안에서 부른다). 나머지 키워드는 ``EdgeSession`` 주입점(시험)."""
    bs = cfg if isinstance(cfg, S.BridgeSettings) else S.load_settings(paths, cfg=cfg)
    kw.setdefault("notices", Notices())
    return EdgeSession("bridge", None, paths=paths, cfg=bs, **kw).front()


def _bare(paths, cfg, kw) -> EdgeSession:
    bs = cfg if isinstance(cfg, S.BridgeSettings) else S.load_settings(paths, cfg=cfg)
    kw.setdefault("notices", Notices())
    return EdgeSession("bridge", None, paths=paths, cfg=bs, **kw)


def hold_edge(paths=None, *, cfg=None, max_s: float | None = None, **kw) -> str:
    r"""작업 보류 시작(H2) — 한 작업(수집 → 분석)을 묶는 쪽(화면 작업 관리자·수집 연결자 등)이 부른다. 이 프로세스가 살아 있는
    동안(최대 ``EDGE_HOLD_MAX_S``) 우리가 띄운 분석용 Edge 를 세션마다 닫지 않고 다음 세션이 이어 쓴다 — 로그인 상태 유지(KMSI)가
    없는 회사에서도 사람이 한 번 로그인한 창으로 그 작업을 마친다. 디버그 포트는 그대로 127.0.0.1 뿐이고, 작업이 끝나면
    ``release_edge_hold`` 가 닫는다(주인이 죽거나 최대 수명이 지나면 다음 세션·정리가 닫는다). 반환: 표지."""
    return _bare(paths, cfg, kw).begin_hold(max_s)


def release_edge_hold(paths=None, *, cfg=None, token: str | None = None, **kw) -> dict:
    """작업 보류 끝(H2) — 표지를 지우고 보류 동안 남은 우리 Edge 를 ``Browser.close`` 로 닫는다. 반환 ``{released, closed, busy}``."""
    return _bare(paths, cfg, kw).end_hold(token)


@contextlib.contextmanager
def edge_hold(paths=None, *, cfg=None, **kw):
    """``with edge_hold(paths):`` — 블록 동안 작업 보류, 나갈 때(예외여도) 풀고 남은 Edge 를 닫는다."""
    tok = hold_edge(paths, cfg=cfg, **dict(kw))
    try:
        yield tok
    finally:
        release_edge_hold(paths, cfg=cfg, token=tok, **dict(kw))


def sweep_edge(paths=None, *, cfg=None, **kw) -> dict:
    """남은 디버그 포트 Edge 정리(L12) — 화면 요청·에이전트 틱이 부른다(빠름: 기록이 없으면 파일 하나만 읽는다)."""
    return _bare(paths, cfg, kw).sweep()
