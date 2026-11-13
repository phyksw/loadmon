# -*- coding: utf-8 -*-
r"""
install.py — 설치 식별(D17)·설치 위치 검사(D21)·옛 LoadMonitor 프로그램 파일 검사(D20)·설치 폴더 권한(C3). spec §6.2.

data\install.json = {"install_id": 32 hex, "salt": 64 hex, "user": sha256(salt + 사용자 SID)}
  · install_id — 개인 리포트 공유 때만 owner_id 로 보낸다.
  · salt — 이 PC 밖으로 나가지 않는다(가명 p:… · 이름 해시의 HMAC 키). 화면·로그·공유 묶음에 싣지 않는다.
  · user — 이 프로세스 토큰의 사용자 SID(GetTokenInformation(TokenUser)). 환경 변수(USERDOMAIN·USERNAME)는 보지 않는다 —
    그 값을 바꿔도 다른 사람의 자료가 열리지 않는다. 지금 계정과 다르면 이 자료는 다른 사람의 것이다: 화면·run.py·teamup 은
    그 자료를 열지 않고 retention.purge_all 을 권한다("다른 사용자의 자료입니다 — 열지 않고 지웁니다"). 덮어쓰지 않는다.
  · 옛 판의 user(sha256(salt + 'domain\name' 소문자))는 한 번만 SID 꼴로 바꿔 적는다.
    그 이름도 토큰의 계정(LookupAccountSidW)에서 읽는다 — 환경 변수로는 옛 판 자료를 넘겨받지 못한다.
  · install.json 이 없거나 깨졌는데 이 설치의 자료(owned_data — 수집 자료·캐시·전용 Edge 프로필·분석 기록·서버에 살아 있는
    공유의 영수증)가 남아 있으면 새로 만들지 않는다: 주인을 모르는 자료(reason "unknown_owner")로 보고 다른 사용자의
    자료처럼 다룬다. install.json 은 data·report 가 빈 설치에서만 새로 만든다 — [모두 지우기]를 마친 설치도 빈 설치다:
    지우기 기록(data\withdrawal.json)과 서버 사본을 지울 영수증(표시 "withdraw")만 남고, 다음 시작은 새 설치로 바로 쓸 수 있다.

설치 폴더 권한(protect_root — C3): %USERPROFILE%·%LOCALAPPDATA% 밖의 폴더(예 C:\AgentFinder32)는 C:\ 의 Users·Authenticated
  Users 권한을 물려받아 이 PC 의 다른 계정이 자료를 읽고 프로그램 파일을 바꿀 수 있다. 그런 폴더면 상속을 끊고 이 사용자 SID·
  SYSTEM·Administrators 만 모든 권한으로 남긴다(icacls — 관리자 권한 없이 내가 만든 폴더의 권한은 바꿀 수 있다). 다시 읽어 다른
  계정의 권한이 남았으면 시작하지 않는다(%LOCALAPPDATA%\AgentFinder32 를 권한다). AF32_NO_ACL=1 이면 건너뛴다(시험).

API
  load(root) -> {"install_id", "salt", "user_ok": bool, "reason": ""|"other_user"|"unknown_owner"}
      없으면 만든다(빈 설치에서만). 주인을 모르면 install_id·salt 는 None.
  install_id(root) · salt(root)                            load 의 값(주인을 모르면 OwnerUnknown)
  current_sid() · identity() · user_hash(salt, user=None)   토큰 SID · 해시 입력 · sha256(salt + 입력)
  owned_data(root) -> list[str]                            install.json 없이 남은 이 설치의 자료(상대 경로 몇 개)
  is_mine(root) -> True|False|None                         load 와 같은 판정을 읽기만 해서(만들지도 고쳐 쓰지도 않는다): 내 설치 ·
                                                           다른 사용자의 설치나 주인을 모르는 자료 · 빈 설치(아직 주인 없음)
  location_problem(root) -> str|None                       UNC·네트워크 드라이브·OneDrive·Teams·SharePoint 동기화 폴더 아래면
                                                           한국어 문장(D21) — 연결(정션)을 따라간 실제 경로도 본다
  legacy_program_files(root) -> list[str]                  설치 폴더에 남은 LoadMonitor 프로그램 파일(상대 경로, 정렬)
  protect_root(root) -> (ok, msg)                          설치 폴더 권한을 내 계정 전용으로(위) — 못 하면 (False, 까닭)
  startup_check(root) -> str|None                          위치 → 옛 파일 → 권한 순으로 보고 막을 까닭(한국어) 또는 None
  acl_note() -> str                                        방금 권한을 내 계정 전용으로 바꿨으면 그 안내(아니면 '')
  OTHER_USER_MSG · UNKNOWN_OWNER_MSG                        다른 사용자의 자료 · 주인을 모르는 자료를 만났을 때 보일 한 줄
UI·run.py·teamserver.py·AgentFinder32.bat 은 시작할 때 startup_check → retention.purge_legacy → retention.purge 순으로 부른다.
CLI  python core\install.py --check [--root R]   (막을 까닭이 있으면 그 문장을 찍고 종료 코드 4, 없으면 0)
"""
import glob
import hashlib
import json
import os
import re
import secrets
import stat
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INSTALL_FILE = "install.json"
DRIVE_REMOTE = 4                 # GetDriveTypeW
NO_WIN = 0x08000000
NO_ACL_ENV = "AF32_NO_ACL"       # "1" 이면 protect_root 가 권한을 읽지도 바꾸지도 않는다(시험 — tests\_boot.py)
RECOMMENDED = "%LOCALAPPDATA%\\AgentFinder32"
LOCATION_MSG = ("이 폴더({root})는 클라우드·네트워크와 동기화됩니다(OneDrive·Teams·SharePoint 동기화 폴더·네트워크 드라이브·"
                "공유 폴더) — 개인 자료가 PC 밖으로 복사되지 않도록 " + RECOMMENDED + "(이 PC 의 내 사용자 폴더)에 압축을 푸세요")
ACL_MSG = ("이 폴더({root})는 이 PC 의 다른 사용자도 열거나 바꿀 수 있는데, 권한을 내 계정 전용으로 바꾸지 못해 시작하지 "
           "않습니다 — " + RECOMMENDED + "(이 PC 의 내 사용자 폴더)에 새로 압축을 푸세요")
ACL_DONE_MSG = "이 폴더({root})의 권한을 이 PC 의 내 계정 전용으로 바꿨습니다 — 다른 사용자는 열 수 없습니다"
LEGACY_MSG = "LoadMonitor 폴더 위에 덮어쓰지 마세요. 새 폴더에 압축을 푸세요 (남은 옛 파일: {files})"
OTHER_USER_MSG = "다른 사용자의 자료입니다 — 열지 않고 지웁니다"
UNKNOWN_OWNER_MSG = "설치 정보가 없어 누구의 자료인지 확인할 수 없습니다 — 열지 않고 지웁니다"
STATUS_FILE = os.path.join("cache", "purge_status.json")   # data\ 아래 — 정리 기록의 예전 자리(자료로 세지 않는다 · 지금은
#                                                            data\purge_status.json — retention.PURGE_STATUS)

# D20 — 이 이름이 설치 폴더에 있으면 LoadMonitor 위에 덮어쓴 것이다(glob, 설치 폴더 기준)
LEGACY_PATTERNS = (
    "LoadMonitor*.bat", "team_recalc.py", "export.py", "aggregate.py", "team_report.py", "team_refine.py", "freeze.py",
    "collect\\Get-Teams*", "collect\\Get-PcOn*", "collect\\Get-ProgramUsage.py", "collect\\Get-GerpWork.py",
    "collect\\Get-FileActivity.ps1", "collect\\Get-RecentFiles.ps1", "collect\\Get-GitActivity.py",
    "collect\\Get-OutlookIndex.ps1", "collect\\Import-MailCal.py",
)

# 설치 폴더 권한 — 늘 남기는 주체(나 · SYSTEM · Administrators · 만든 사람 자리표시)와 지우는 넓은 그룹
SID_SYSTEM = "S-1-5-18"
SID_ADMINS = "S-1-5-32-544"
SELF_SIDS = (SID_SYSTEM, SID_ADMINS, "S-1-3-0", "S-1-3-4")       # + 이 사용자 SID(CREATOR OWNER · OWNER RIGHTS 는 자리표시)
BROAD_SIDS = ("S-1-1-0", "S-1-5-11", "S-1-5-32-545", "S-1-5-4", "S-1-5-32-546", "S-1-5-7")
#              Everyone · Authenticated Users · Users · INTERACTIVE · Guests · ANONYMOUS LOGON
_ACE_ALLOW = (0, 9)              # ACCESS_ALLOWED_ACE_TYPE · ACCESS_ALLOWED_CALLBACK_ACE_TYPE
_REPARSE_POINT = 0x400
_NOTE = {"msg": ""}              # 마지막 protect_root 가 권한을 바꿨으면 그 안내(CLI 가 찍는다)
_TOKEN = {}                      # 이 프로세스 토큰의 사용자(바뀌지 않는다 — 한 번만 읽는다)


class OwnerUnknown(RuntimeError):
    """install.json 이 없거나 깨졌는데 이 설치의 자료가 남아 있다 — 새 설치 정보를 만들지 않는다(주인을 모른다)."""


def _data(root):
    return os.path.join(str(root or ROOT), "data")


# ── 사용자 식별(D17) ──────────────────────────────────────────────────────────────────────
def current_user():
    r"""환경 변수의 'USERDOMAIN\USERNAME'(소문자) — SID 를 읽지 못하는 곳(윈도가 아님)에서만 쓴다."""
    return (os.environ.get("USERDOMAIN", "") + "\\" + os.environ.get("USERNAME", "")).lower()


def _query_token_user():
    """(SID 'S-1-5-…', 계정 'domain\\name' 소문자 | None) — OpenProcessToken · GetTokenInformation(TokenUser) ·
    ConvertSidToStringSidW · LookupAccountSidW(ctypes, 이 모듈 전용 DLL 인스턴스)."""
    import ctypes
    from ctypes import wintypes as W
    adv = ctypes.WinDLL("advapi32", use_last_error=True)
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.GetCurrentProcess.restype = W.HANDLE
    k32.CloseHandle.argtypes = [W.HANDLE]
    k32.LocalFree.argtypes = [ctypes.c_void_p]
    k32.LocalFree.restype = ctypes.c_void_p
    adv.OpenProcessToken.argtypes = [W.HANDLE, W.DWORD, ctypes.POINTER(W.HANDLE)]
    adv.OpenProcessToken.restype = W.BOOL
    adv.GetTokenInformation.argtypes = [W.HANDLE, ctypes.c_int, ctypes.c_void_p, W.DWORD, ctypes.POINTER(W.DWORD)]
    adv.GetTokenInformation.restype = W.BOOL
    adv.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(W.LPWSTR)]
    adv.ConvertSidToStringSidW.restype = W.BOOL
    adv.LookupAccountSidW.argtypes = [W.LPCWSTR, ctypes.c_void_p, W.LPWSTR, ctypes.POINTER(W.DWORD), W.LPWSTR,
                                      ctypes.POINTER(W.DWORD), ctypes.POINTER(ctypes.c_int)]
    adv.LookupAccountSidW.restype = W.BOOL
    h = W.HANDLE()
    if not adv.OpenProcessToken(k32.GetCurrentProcess(), 0x0008, ctypes.byref(h)):      # TOKEN_QUERY
        return None, None
    try:
        need = W.DWORD(0)
        adv.GetTokenInformation(h, 1, None, 0, ctypes.byref(need))                       # TokenUser
        if not need.value:
            return None, None
        buf = ctypes.create_string_buffer(need.value)
        if not adv.GetTokenInformation(h, 1, buf, need, ctypes.byref(need)):
            return None, None
        psid = ctypes.c_void_p.from_buffer(buf).value                                   # TOKEN_USER.User.Sid
        s = W.LPWSTR()
        if not adv.ConvertSidToStringSidW(psid, ctypes.byref(s)):
            return None, None
        try:
            sid = str(s.value or "").upper()
        finally:
            k32.LocalFree(s)
        name, dom = ctypes.create_unicode_buffer(512), ctypes.create_unicode_buffer(512)
        nn, dn, use = W.DWORD(512), W.DWORD(512), ctypes.c_int(0)
        acct = None
        if adv.LookupAccountSidW(None, psid, name, ctypes.byref(nn), dom, ctypes.byref(dn), ctypes.byref(use)):
            acct = (dom.value + "\\" + name.value).lower()
        return (sid if sid.startswith("S-1-") else None), acct
    finally:
        k32.CloseHandle(h)


def _token_user():
    """(SID, 'domain\\name') — 이 프로세스 토큰의 사용자. 윈도가 아니거나 읽지 못하면 (None, None)."""
    if "sid" not in _TOKEN:
        sid = name = None
        if os.name == "nt":
            try:
                sid, name = _query_token_user()
            except (OSError, AttributeError, ValueError, TypeError):
                sid = name = None
        _TOKEN.update(sid=sid, name=name)
    return _TOKEN["sid"], _TOKEN["name"]


def current_sid():
    """이 프로세스 토큰의 사용자 SID('S-1-5-21-…') — 윈도가 아니거나 읽지 못하면 None."""
    return _token_user()[0]


def identity():
    """user 해시의 입력 — 토큰의 사용자 SID. SID 를 읽지 못하는 곳(윈도가 아님)에서만 환경 변수의 'domain\\name'."""
    return current_sid() or current_user()


def user_hash(salt_hex, user=None):
    """sha256(salt + 사용자) 16진 — user=None 이면 이 프로세스의 사용자(identity()), 주면 그 문자열(시험·옛 판 꼴)."""
    return hashlib.sha256((str(salt_hex) + (identity() if user is None else user)).encode("utf-8")).hexdigest()


def legacy_user_hash(salt_hex):
    """옛 판 user — sha256(salt + 'domain\\name' 소문자). 이름은 토큰의 계정에서 읽는다(환경 변수가 아니다). 못 읽으면 None."""
    name = _token_user()[1]
    return hashlib.sha256((str(salt_hex) + name).encode("utf-8")).hexdigest() if name else None


def _valid(d):
    return (isinstance(d, dict) and re.fullmatch(r"[0-9a-f]{32}", str(d.get("install_id") or ""))
            and re.fullmatch(r"[0-9a-f]{64}", str(d.get("salt") or ""))
            and re.fullmatch(r"[0-9a-f]{64}", str(d.get("user") or "")))


def _write(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def _read_json(path):
    try:
        with open(path, encoding="utf-8-sig") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _is_link(path):
    """정션·심볼릭 링크인가(lstat 을 못 하면 참 — 모르는 곳으로 들어가지 않는다)."""
    try:
        st = os.lstat(path)
    except OSError:
        return True
    return stat.S_ISLNK(st.st_mode) or bool((getattr(st, "st_file_attributes", 0) or 0) & _REPARSE_POINT)


def _has_file(top, skip=()):
    """top 아래(연결 폴더에는 들어가지 않는다)에 파일이 하나라도 있나. skip = 세지 않을 파일(절대 경로)."""
    if not os.path.isdir(top) or _is_link(top):
        return False
    skip_n = {os.path.normcase(os.path.abspath(s)) for s in skip}
    for cur, dirs, files in os.walk(top, onerror=lambda e: None):
        if any(os.path.normcase(os.path.abspath(os.path.join(cur, f))) not in skip_n for f in files):
            return True
        dirs[:] = [d for d in dirs if not _is_link(os.path.join(cur, d))]
    return False


def owned_data(root=None):
    r"""install.json 없이 남은 이 설치의 자료 → 상대 경로 몇 개(없으면 []). 자료로 보는 것:
    data\outlook\ · data\cache\ · data\af32_edge\(전용 Edge 로그인 프로필)와 그 옛 사본 af32_edge.bad-* ·
    report\run_meta_*.json(AgentFinder32 표식) · data\share_receipts.json 의 표시("withdraw") 없는 영수증(서버에 살아 있는 공유).
    자료로 보지 않는 것 — [모두 지우기]를 마친 설치에 남는 것과 기록뿐인 파일: 지우기 기록(data\withdrawal.json) · 그때 남긴
    영수증("withdraw": true — 서버 사본을 지우는 일감) · 정리 기록(data\purge_status.json · 예전 자리 data\cache\purge_status.json —
    날짜와 건수만) · 분석 잠금·예약 작업 확인 기록 · 예전 판이 남기던 기록 파일(정리가 지운다 — 읽지 않는다)."""
    r = str(root or ROOT)
    data = _data(r)
    found = []
    for name in ("outlook", "cache", "af32_edge"):
        if _has_file(os.path.join(data, name), skip=(os.path.join(data, STATUS_FILE),)):
            found.append("data\\" + name)
    for p in sorted(glob.glob(os.path.join(data, "af32_edge.bad-*"))):
        if _has_file(p):
            found.append("data\\" + os.path.basename(p))
    rec = _read_json(os.path.join(data, "share_receipts.json"))
    lst = rec.get("receipts") if isinstance(rec, dict) else rec
    if isinstance(lst, list) and any(isinstance(x, dict) and not x.get("withdraw") for x in lst):
        found.append("data\\share_receipts.json")
    for p in sorted(glob.glob(os.path.join(r, "report", "run_meta_*.json"))):
        m = _read_json(p)
        if isinstance(m, dict) and m.get("product") == "AgentFinder32":
            found.append("report\\" + os.path.basename(p))
            break
    return found


def _migrate(root, d, old, new):
    r"""옛 판 user(이름 해시 old) → SID 해시(new). 소금·설치 ID 는 그대로(가명이 이어진다)."""
    d = dict(d, user=new)
    _write(os.path.join(_data(root), INSTALL_FILE), d)
    return d


def load(root=None):
    r"""data\install.json → {"install_id", "salt", "user_ok", "reason"}.
    · 있고 user 가 지금 사용자(SID)면 user_ok=True. 옛 판 user 면 한 번 SID 꼴로 바꿔 적고 user_ok=True.
    · 있고 다른 사용자면 덮어쓰지 않고 user_ok=False, reason "other_user" — 부르는 쪽이 그 자료를 열지 않고 지우기를 권한다.
    · 없거나 깨졌는데 이 설치의 자료(owned_data)가 남아 있으면 만들지 않고 user_ok=False, reason "unknown_owner"
      (install_id·salt 는 None).
    · 없거나 깨졌고 자료도 없으면(빈 설치 · purge_all·[모두 지우기] 뒤) 새로 만든다(user_ok=True)."""
    p = os.path.join(_data(root), INSTALL_FILE)
    d = _read_json(p)
    if _valid(d):
        cur = user_hash(d["salt"])
        if d["user"] == cur:
            return {"install_id": d["install_id"], "salt": d["salt"], "user_ok": True, "reason": ""}
        old = legacy_user_hash(d["salt"])
        if old and old != cur and d["user"] == old:
            try:
                d = _migrate(root, d, old, cur)
            except OSError:
                pass
            return {"install_id": d["install_id"], "salt": d["salt"], "user_ok": True, "reason": ""}
        return {"install_id": d["install_id"], "salt": d["salt"], "user_ok": False, "reason": "other_user"}
    if owned_data(root):
        return {"install_id": None, "salt": None, "user_ok": False, "reason": "unknown_owner"}
    s = secrets.token_hex(32)
    d = {"install_id": secrets.token_hex(16), "salt": s, "user": user_hash(s)}
    _write(p, d)
    return {"install_id": d["install_id"], "salt": d["salt"], "user_ok": True, "reason": ""}


def is_mine(root=None):
    r"""이 설치의 자료가 지금 Windows 사용자의 것인가 — 읽기만 한다(load 와 같은 판정이지만 설치 정보를 만들지도, 옛 판의 이름
    해시를 고쳐 쓰지도 않는다). → True(내 설치 — 옛 판의 이름 해시로 적힌 것 포함) · False(다른 사용자의 설치 · 설치 정보 없이 남은
    자료) · None(설치 정보도 자료도 없는 빈 설치 — 아직 주인이 없다).
    보관기한 정리처럼 시작 확인보다 먼저 도는 코드가 묻는다 — 내 자료가 아닌 폴더에는 지우기만 하고 쓰지 않으려고."""
    d = _read_json(os.path.join(_data(root), INSTALL_FILE))
    if _valid(d):
        cur = user_hash(d["salt"])
        if d["user"] == cur:
            return True
        old = legacy_user_hash(d["salt"])
        return bool(old and old != cur and d["user"] == old)
    return False if owned_data(root) else None


def _known(root):
    ins = load(root)
    if not ins.get("install_id"):
        raise OwnerUnknown(OTHER_USER_MSG)
    return ins


def install_id(root=None):
    """설치 ID(32 hex) — 개인 리포트 공유의 owner_id 로만 쓴다. 주인을 모르는 자료면 OwnerUnknown."""
    return _known(root)["install_id"]


def salt(root=None):
    """설치 소금(64 hex) — 이 PC 밖으로 내보내지 않는다. 주인을 모르는 자료면 OwnerUnknown."""
    return _known(root)["salt"]


# ── 설치 위치(D21) ───────────────────────────────────────────────────────────────────────
def _drive_type(path):
    """GetDriveTypeW(드라이브 뿌리) — 윈도가 아니거나 실패하면 0."""
    if os.name != "nt":
        return 0
    try:
        import ctypes
        drv = os.path.splitdrive(os.path.abspath(path))[0]
        if not drv:
            return 0
        return int(ctypes.windll.kernel32.GetDriveTypeW(drv + "\\"))
    except (AttributeError, OSError, ValueError):
        return 0


def _under(path, base):
    try:
        a = os.path.normcase(os.path.abspath(path)).rstrip("\\/")
        b = os.path.normcase(os.path.abspath(base)).rstrip("\\/")
    except (TypeError, ValueError):
        return False
    return bool(b) and (a == b or a.startswith(b + os.sep))


def _is_unc(path):
    low = str(path).replace("/", "\\")
    return low.startswith("\\\\?\\UNC\\") or (low.startswith("\\\\") and not low.startswith(("\\\\?\\", "\\\\.\\")))


def _real(path):
    """연결(정션·심볼릭 링크)을 따라간 실제 경로 — 못 따라가면 절대 경로."""
    try:
        return os.path.realpath(path)
    except (OSError, ValueError):
        return os.path.abspath(path)


def _reg_sync_roots():
    r"""레지스트리의 동기화 폴더(읽기만) — HKCU\Software\Microsoft\OneDrive\Accounts\*\UserFolder · …\Tenants\*\<값 이름> ·
    HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\SyncRootManager\*\UserSyncRoots\<이 사용자 SID>."""
    out = []
    try:
        import winreg
    except ImportError:
        return out

    def keys(h):
        i = 0
        while True:
            try:
                yield winreg.EnumKey(h, i)
            except OSError:
                return
            i += 1

    def values(h):
        i = 0
        while True:
            try:
                yield winreg.EnumValue(h, i)
            except OSError:
                return
            i += 1
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\OneDrive\Accounts") as acc:
            for name in list(keys(acc)):
                try:
                    with winreg.OpenKey(acc, name) as a:
                        try:
                            out.append(str(winreg.QueryValueEx(a, "UserFolder")[0]))
                        except OSError:
                            pass
                        try:
                            with winreg.OpenKey(a, "Tenants") as t:
                                for tn in list(keys(t)):
                                    with winreg.OpenKey(t, tn) as tk:
                                        out.extend(str(v[0]) for v in values(tk) if ":\\" in str(v[0]))
                        except OSError:
                            pass
                except OSError:
                    continue
    except OSError:
        pass
    sid = current_sid()
    try:
        base = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\SyncRootManager"
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base) as m:
            for name in list(keys(m)):
                try:
                    with winreg.OpenKey(m, name + r"\UserSyncRoots") as u:
                        for v in values(u):
                            if (sid is None or str(v[0]).upper() == sid) and isinstance(v[1], str):
                                out.append(v[1])
                except OSError:
                    continue
    except OSError:
        pass
    return out


def _sync_roots():
    """이 사용자의 클라우드 동기화 폴더 — %OneDrive%·%OneDriveCommercial%·%OneDriveConsumer% + 레지스트리(Teams·SharePoint
    동기화 라이브러리 · 다른 OneDrive 계정 · 그 밖의 동기화 앱)."""
    out = []
    for k in ("OneDrive", "OneDriveCommercial", "OneDriveConsumer"):
        v = os.environ.get(k, "").strip()
        if v:
            out.append(v)
    if os.name == "nt":
        out += _reg_sync_roots()
    seen, res = set(), []
    for p in out:
        p = str(p or "").strip().strip('"')
        if p and os.path.normcase(p) not in seen:
            seen.add(os.path.normcase(p))
            res.append(p)
    return res


def location_problem(root=None):
    r"""설치 위치가 PC 밖과 동기화되면 한국어 문장, 아니면 None(D21).
    UNC(\\서버\공유) · 네트워크 드라이브(GetDriveTypeW = DRIVE_REMOTE) · OneDrive·Teams·SharePoint 동기화 폴더 아래.
    설치 폴더와 data\·report\·config\·teamdata\ 는 연결(정션)을 따라간 실제 경로까지 본다."""
    r = os.path.abspath(str(root or ROOT))
    msg = LOCATION_MSG.format(root=r)
    if _is_unc(r):
        return msg                       # 네트워크 경로 — 실제 경로를 묻지 않는다(망에 닿지 않게)
    paths = [r, _real(r)]
    for sub in ("data", "report", "config", "teamdata"):
        p = os.path.join(r, sub)
        if os.path.lexists(p):
            paths.append(_real(p))
    roots = _sync_roots()
    roots += [_real(s) for s in roots if not _is_unc(s)]
    for p in paths:
        if _is_unc(p) or _drive_type(p) == DRIVE_REMOTE:
            return msg
        if any(_under(p, s) for s in roots):
            return msg
    return None


def legacy_program_files(root=None):
    r"""설치 폴더에 남은 LoadMonitor 프로그램 파일(설치 폴더 기준 상대 경로, 정렬) — 비어 있지 않으면 시작을 막는다(D20)."""
    r = str(root or ROOT)
    found = set()
    for pat in LEGACY_PATTERNS:
        for p in glob.glob(os.path.join(r, pat)):
            if os.path.isfile(p):
                found.add(os.path.relpath(p, r))
    return sorted(found)


# ── 설치 폴더 권한(C3) ────────────────────────────────────────────────────────────────────
def _dacl(path):
    """경로의 DACL → [(SID, 허용 ACE 인가, 권한 마스크)] · 읽지 못하면 None · NULL DACL(누구나 모든 권한)이면 Everyone 한 줄."""
    import ctypes
    from ctypes import wintypes as W
    adv = ctypes.WinDLL("advapi32", use_last_error=True)
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    adv.GetNamedSecurityInfoW.argtypes = [W.LPCWSTR, ctypes.c_int, W.DWORD] + [ctypes.POINTER(ctypes.c_void_p)] * 5
    adv.GetNamedSecurityInfoW.restype = W.DWORD
    adv.GetAce.argtypes = [ctypes.c_void_p, W.DWORD, ctypes.POINTER(ctypes.c_void_p)]
    adv.GetAce.restype = W.BOOL
    adv.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(W.LPWSTR)]
    adv.ConvertSidToStringSidW.restype = W.BOOL
    k32.LocalFree.argtypes = [ctypes.c_void_p]
    k32.LocalFree.restype = ctypes.c_void_p
    acl, sd = ctypes.c_void_p(), ctypes.c_void_p()
    # SE_FILE_OBJECT(1) · DACL_SECURITY_INFORMATION(4)
    if adv.GetNamedSecurityInfoW(str(path), 1, 4, None, None, ctypes.byref(acl), None, ctypes.byref(sd)) != 0:
        return None
    try:
        if not acl.value:
            return [("S-1-1-0", True, 0x1F01FF)]
        out = []
        for i in range(ctypes.c_ushort.from_address(acl.value + 4).value):        # ACL.AceCount
            ace = ctypes.c_void_p()
            if not adv.GetAce(acl, i, ctypes.byref(ace)) or not ace.value:
                continue
            typ = ctypes.c_ubyte.from_address(ace.value).value
            if typ not in (0, 1, 9, 10):                                            # 허용·거부(콜백 포함) — 개체 ACE 는 파일에 없다
                continue
            mask = ctypes.c_uint32.from_address(ace.value + 4).value
            s = W.LPWSTR()
            if not adv.ConvertSidToStringSidW(ctypes.c_void_p(ace.value + 8), ctypes.byref(s)):
                continue
            try:
                out.append((str(s.value or "").upper(), typ in _ACE_ALLOW, mask))
            finally:
                k32.LocalFree(s)
        return out
    finally:
        k32.LocalFree(sd)


def _others(path, me):
    """그 폴더에 권한(허용 ACE)을 가진 다른 주체의 SID 집합 — 나·SYSTEM·Administrators 말고. 읽지 못하면 None."""
    entries = _dacl(path)
    if entries is None:
        return None
    keep = set(SELF_SIDS) | ({me} if me else set())
    return {sid for sid, allow, mask in entries if allow and mask and sid not in keep}


def _icacls(path, *args):
    """icacls <path> <args…> /Q (창 없이) → 종료 코드. protect_root 만 부른다(시험이 이 함수를 바꿔 끼워 대상 폴더를 확인한다)."""
    try:
        p = subprocess.run(["icacls", str(path)] + [str(a) for a in args] + ["/Q"], capture_output=True, timeout=120,
                           creationflags=NO_WIN if os.name == "nt" else 0)
        return p.returncode
    except (OSError, subprocess.SubprocessError, ValueError):
        return -1


def _in_profile(path):
    """%USERPROFILE%·%LOCALAPPDATA% 아래인가(그 폴더는 처음부터 이 사용자 전용이다)."""
    for k in ("USERPROFILE", "LOCALAPPDATA"):
        base = os.environ.get(k, "").strip()
        if base and (_under(path, base) or _under(path, _real(base))):
            return True
    return False


def _no_touch(path):
    r"""권한을 바꾸면 안 되는 곳 — 드라이브 뿌리 · Windows·Program Files 아래 · ProgramData·Users·Public 같은 공용 폴더 자신."""
    p = os.path.normcase(os.path.abspath(path)).rstrip("\\/")
    if os.path.dirname(p) == p or len(p) <= 3:
        return True
    env = os.environ
    under = [env.get(k, "") for k in ("SystemRoot", "windir", "ProgramFiles", "ProgramFiles(x86)", "ProgramW6432")]
    if any(b and _under(p, b) for b in under):
        return True
    same = [env.get(k, "") for k in ("ProgramData", "ALLUSERSPROFILE", "PUBLIC")]
    prof = env.get("USERPROFILE", "")
    if prof:
        same.append(os.path.dirname(os.path.abspath(prof)))
    return any(b and p == os.path.normcase(os.path.abspath(b)).rstrip("\\/") for b in same)


def _subdirs(path):
    """바로 아래 폴더들(설치 폴더 권한을 다시 확인할 곳)."""
    try:
        names = os.listdir(path)
    except OSError:
        return []
    return [os.path.join(path, n) for n in sorted(names) if os.path.isdir(os.path.join(path, n))]


def _exposed(paths, me):
    """[(경로, 다른 주체 SID 목록 | None(읽지 못함))] — 다른 주체가 없는 경로는 빼고. 네트워크 경로는 묻지 않고 읽지 못함으로 본다."""
    out = []
    for p in paths:
        s = None if _is_unc(p) else _others(p, me)
        if s is None or s:
            out.append((p, sorted(s) if s is not None else None))
    return out


def protect_root(root=None):
    r"""설치 폴더를 이 PC 의 내 계정 전용으로(C3) → (ok, msg).
    · AF32_NO_ACL=1 · 윈도가 아님 · %USERPROFILE%·%LOCALAPPDATA% 아래 · 설치 폴더와 바로 아래 폴더에 다른 주체의 권한이 없음
      → (True, "") — 아무것도 바꾸지 않는다.
    · 다른 주체(Users·Authenticated Users·Everyone 같은 그룹이나 다른 계정)의 권한이 있으면 icacls 로 상속을 끊고
      (/inheritance:r) 이 사용자 SID·SYSTEM·Administrators 만 (OI)(CI)F 로 두고(/grant:r) 넓은 그룹의 명시 권한을 지운다
      (/remove:g). 바로 아래 폴더의 넓은 그룹 명시 권한도 지운다(상속의 전파는 연결 너머로 가지 않는다).
    · 바로 아래 폴더가 연결(정션)이면 그 너머(실제 경로 — 자료는 거기에 있다)의 권한을 본다. 보기만 하고 바꾸지 않는다 —
      그곳이 사용자 폴더 밖이고 다른 주체에게 열려 있으면 시작하지 않는다.
    · 다시 읽어 다른 주체가 남았거나(명시한 다른 계정 · 바꿀 권한 없음 · 열린 연결 너머) 권한을 읽지 못하면 (False, ACL_MSG) —
      시작하지 않는다. 드라이브 뿌리·Windows·Program Files·공용 폴더는 바꾸지 않고 거절한다."""
    r = os.path.abspath(str(root or ROOT))
    _NOTE["msg"] = ""
    if os.environ.get(NO_ACL_ENV, "").strip() == "1" or os.name != "nt":
        return True, ""
    real = _real(r)
    if _in_profile(real):
        return True, ""
    me = current_sid()
    subs = _subdirs(real)
    paths = [real] + [p for p in subs if not _is_link(p)]
    links = []                          # 연결 폴더의 실제 경로 — 권한을 보기만 한다(없는 곳·사용자 폴더 안은 뺀다)
    for p in subs:
        if _is_link(p):
            t = _real(p)
            if _is_unc(t) or (os.path.isdir(t) and not _in_profile(t)):
                links.append(t)
    bad = _exposed(paths + links, me)
    if not bad:
        return True, ""
    fail = (False, ACL_MSG.format(root=r))
    if not me or _no_touch(real) or _is_link(real):
        return fail                     # 바꾸면 안 되는 곳 · 연결을 따라가지 못한 경로 — 권한을 건드리지 않는다
    if any(p == real for p, _s in bad):
        _icacls(real, "/inheritance:r", "/grant:r", f"*{me}:(OI)(CI)F", f"*{SID_SYSTEM}:(OI)(CI)F",
                f"*{SID_ADMINS}:(OI)(CI)F")
    for p in paths:
        left = _others(p, me)
        broad = sorted(set(left or ()) & set(BROAD_SIDS))
        if broad:
            _icacls(p, "/remove:g", *[f"*{s}" for s in broad])
    if _exposed(paths + links, me):
        return fail
    _NOTE["msg"] = ACL_DONE_MSG.format(root=r)
    return True, _NOTE["msg"]


def startup_check(root=None):
    """시작 전 검사 — 설치 위치(D21) → 옛 LoadMonitor 프로그램 파일(D20) → 설치 폴더 권한(C3).
    막을 까닭(한국어 한 문장) 또는 None. 권한을 바꾼 안내는 _NOTE["msg"] 에 남는다(CLI 가 찍는다)."""
    msg = location_problem(root)
    if msg:
        return msg
    old = legacy_program_files(root)
    if old:
        shown = ", ".join(old[:6]) + (f" 외 {len(old) - 6}개" if len(old) > 6 else "")
        return LEGACY_MSG.format(files=shown)
    ok, msg = protect_root(root)
    return None if ok else msg


def acl_note():
    """마지막 startup_check(protect_root)가 설치 폴더 권한을 내 계정 전용으로 바꿨으면 그 안내(한국어 한 줄), 아니면 ''."""
    return _NOTE["msg"]


if __name__ == "__main__":
    if "--check" in sys.argv:
        m = startup_check(sys.argv[sys.argv.index("--root") + 1] if "--root" in sys.argv[:-1] else None)
        if m:
            print(m)
            sys.exit(4)
        if _NOTE["msg"]:
            print(_NOTE["msg"])
        sys.exit(0)
    print(__doc__)
