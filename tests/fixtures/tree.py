# -*- coding: utf-8 -*-
r"""%TEMP% 복제 트리 하네스(WP-05) — 시험은 실제 트리가 아니라 여기서 만든 복제본에서만 돈다(계약 §11.3).

    from tests.fixtures.tree import make_clone
    with make_clone() as c:                       # %TEMP%\lm27t_<rand>\ 에 lm27·collect·web·config·tools·tests·docs·진입 스크립트
        cp = c.run_cli("--help")                  # 동봉 파이썬(원본 경로) -X utf8 -B, 작업 폴더 = 복제 안 %TEMP%(bat 의 pushd 와 같게)
    # with 블록을 나가면(예외여도) 복제를 지운다

    class T(CloneTestCase): ...                   # 클래스마다 복제 1개(setUpClass 생성 · 정리 시 삭제), self.clone

- 복제하지 않는 것: __pycache__ · .ruff_cache · config\config.json(개인 덮어쓰기) · data\ · out\ · python\(동봉 파이썬은 원본 경로를 쓴다).
- 저장소 설정 파일(ruff.toml · .gitattributes · .gitignore · .claude\settings.json)은 복제한다 — 관문 시험이 그것을 본다.
- 복제 안의 %LOCALAPPDATA% 는 <clone>\_sandbox\LocalAppData 로 돌린다(c.env() / c.patched_environ()) — 실제 에이전트 폴더를 건드리지 않는다.
  로컬 금지어 목록(CR-06)은 복사하지 않고 위치만 LM27T_FORBIDDEN_WORDS 로 넘긴다(hook_check 가 복제 안에서만 읽음).
- assert_test_root(root): 실제 트리·설치 경로면 AssertionError(계약 §11.3 'assert ROOT != 실제 설치 경로').
- 정리(잔여물 0 — W1 통합 창 · W2 수정 E): 지우기는 긴 경로('\\?\' 접두)·읽기 전용 속성(파일·폴더)·잠긴 파일(물러섰다가
  다시 — 복제 지우기는 최대 약 20초)을 처리하고, 복제 표지는 **마지막에** 지운다(남은 조각도 표지가 있어 청소 대상으로
  알아본다). 못 지우면 stderr 에 알린다. make 때마다(프로세스당 한 번) %TEMP% 의 lm27t_* 를 청소한다(sweep_stale) —
  이름 바꾸기가 되는(= 그 안에 작업 폴더·열린 파일을 가진 프로세스가 없는) 것 중 ① 1시간 넘게 손대지 않았고 주인 프로세스가
  끝난(또는 PID 가 재사용된) 것 ② 6시간 넘게 손대지 않은 표지 있는 고아 복제(주인이 오래 사는 프로세스 — 워크플로 실행기
  등 — 라 살아 있어도). '손댄 시각' = 표지·폴더(2단까지)의 수정 시각 중 가장 늦은 것(run_py 가 표지를 갱신한다).
- 실행(run_py · run_cli · run_unittest)은 자식을 Job Object(KILL_ON_JOB_CLOSE)에 넣는다 — 시간 초과면 트리째(taskkill /T +
  Job 종료) 끊고, 정상 종료여도 남은 자손(고아 손주)을 끝낸다. 손주가 출력 파이프를 쥐어도 시간 제한이 듣는다(C19·C23).

명령줄(관문 실행기 tools\lint.ps1 이 그대로 쓴다 — 표준 라이브러리만 import):
    "<PY>" -X utf8 -B tests\fixtures\tree.py unit [영역 ...]      복제 → 영역별 unittest discover → 삭제. rc 0 = 전부 통과
    "<PY>" -X utf8 -B tests\fixtures\tree.py make [--extra docs]   복제만 하고 경로를 출력(지우지 않음)
    "<PY>" -X utf8 -B tests\fixtures\tree.py discover <경로> <영역> [--pattern test*.py]
                                                                  make 로 만든 복제에서 영역 하나를 discover(rc = unittest rc)
    "<PY>" -X utf8 -B tests\fixtures\tree.py remove <경로>         make 로 만든 복제를 지움(복제 표지가 있을 때만)
"""
from __future__ import annotations

import argparse
import contextlib
import os
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path

TREE_ROOT = Path(__file__).resolve().parents[2]          # 이 파일이 든 트리(원본 또는 복제)
CLONE_PREFIX = "lm27t_"
CLONE_MARK = ".lm27t_clone"                              # 복제 표지 — 이것이 있는 폴더만 지운다
CLONE_PARTS = ("lm27", "collect", "web", "config", "tools", "tests", "docs")   # docs — 관문 시험이 계약 표를 실행 때 읽는다
ENTRY_FILES = ("lm27_cli.py", "lm27_pipe.py", "ruff.toml")
ENTRY_GLOBS = ("*.bat",)
REPO_FILES = (".gitattributes", ".gitignore", ".claude/settings.json")   # 저장소 설정(WP-04) — 관문 시험 대상
FORBIDDEN_REL = Path("LoadMonitor27", "dev", "forbidden_words.txt")     # CR-06 로컬 금지어 목록(저장소 밖)
SKIP_NAMES = frozenset({"__pycache__", ".ruff_cache", ".pytest_cache", ".git", CLONE_MARK})
SKIP_REL = frozenset({"config/config.json", "config/settings.local.json"})
INJECT_VARS = ("LM_OUTLOOK_SELFTEST", "LM_PROBE_FAKE", "LM_INDEX_FAKE", "LM_OWA_FAKE", "LM_TEAMSWEB_FAKE",
               "LM_COPILOT_STUB", "LM_NO_BROWSER")       # 계약 §11.3(+ v1.2 C3 LM_PROBE_FAKE) 환경 변수 주입점 — 시험이 명시할 때만 넘긴다
CREATE_NO_WINDOW = 0x08000000
# 시스템 %TEMP% — 가져올 때 한 번 고정. 복제 안 자식 프로세스는 TEMP 가 복제 안으로 바뀌므로 원래 값을 LM27T_TMP_BASE 로 받는다.
_TMP_BASE = Path(os.environ.get("LM27T_TMP_BASE") or tempfile.gettempdir()).resolve()


def _is_clone_dir(p: Path) -> bool:
    return (p / CLONE_MARK).is_file()


def _source_root() -> Path:
    """실제 원본 트리. 복제 안에서 불렸으면 복제가 남긴 환경 변수(LM27T_SRC_ROOT)를 따른다."""
    env = os.environ.get("LM27T_SRC_ROOT")
    if _is_clone_dir(TREE_ROOT) and env:
        return Path(env).resolve()
    return TREE_ROOT


SOURCE_ROOT = _source_root()


def python_home() -> Path:
    """동봉 파이썬 폴더 — 복제하지 않고 원본 경로를 돌려준다(복제 안에서는 LM27T_PY_HOME 으로 원본을 찾는다)."""
    env = os.environ.get("LM27T_PY_HOME")
    for cand in (SOURCE_ROOT / "python", Path(env) if env else None, TREE_ROOT / "python"):
        if cand is not None and (cand / "python.exe").is_file():
            return cand
    return Path(sys.executable).resolve().parent


def _forbidden_list() -> str:
    """CR-06 금지어 목록 위치(복제 env 로 넘김). 지금 %LOCALAPPDATA% 에 있으면 그것, 없으면 바깥 복제가 넘긴 값."""
    lad = os.environ.get("LOCALAPPDATA")
    if lad and (Path(lad) / FORBIDDEN_REL).is_file():
        return str(Path(lad) / FORBIDDEN_REL)
    return os.environ.get("LM27T_FORBIDDEN_WORDS", "")


FORBIDDEN_LIST = _forbidden_list()


def _is_under(p: Path, base: Path) -> bool:
    return p == base or base in p.parents


def _real_roots() -> list[Path]:
    """시험이 절대 돌면 안 되는 실제 경로: 원본 트리 · 배포 에이전트 폴더(%LOCALAPPDATA%\\LoadMonitor27)."""
    out = [SOURCE_ROOT.resolve()]
    if not _is_clone_dir(TREE_ROOT):
        out.append(TREE_ROOT.resolve())
    lad = os.environ.get("LOCALAPPDATA")
    if lad and not os.environ.get("LM27T_CLONE"):
        out.append((Path(lad) / "LoadMonitor27").resolve())
    return out


def assert_test_root(root: str | os.PathLike) -> Path:
    """root 가 %TEMP% 아래의 시험용 복제 트리(lm27t_*)인지 확인한다. 실제 트리·설치 경로면 AssertionError."""
    p = Path(root).resolve()
    for real in _real_roots():
        if _is_under(p, real) or _is_under(real, p):
            raise AssertionError(f"시험 루트가 실제 트리·설치 경로와 겹칩니다: {p}")
    if not _is_under(p, _TMP_BASE) or p == _TMP_BASE:
        raise AssertionError(f"시험 루트는 %TEMP% 아래여야 합니다: {p}")
    if not p.name.startswith(CLONE_PREFIX):
        raise AssertionError(f"시험 루트 이름은 {CLONE_PREFIX}* 여야 합니다: {p}")
    return p


def guard_write(path: str | os.PathLike) -> Path:
    """합성 자료를 쓸 경로 확인 — %TEMP% 아래이고 실제 트리·설치 경로 밖이어야 한다(아니면 AssertionError)."""
    p = Path(path).resolve()
    if not _is_under(p, _TMP_BASE) or p == _TMP_BASE:
        raise AssertionError(f"합성 자료는 %TEMP% 아래에만 씁니다: {p}")
    for real in _real_roots():
        if _is_under(p, real):
            raise AssertionError(f"실제 트리·설치 경로에는 쓰지 않습니다: {p}")
    return p


STALE_AGE_S = 3600                                       # 이보다 오래 손대지 않은 lm27t_* 만 청소 대상(주인·사용 확인 뒤)
ORPHAN_AGE_S = 6 * 3600                                  # 이보다 오래 손대지 않은 표지 있는 복제는 주인이 살아 있어도 고아로 본다
REMOVE_TRIES = 12                                        # 복제 지우기 재시도(물러서기 합계 약 20초 — 잠긴 파일·백신 검사 대기)
_SWEPT = False                                           # 프로세스당 한 번만 청소


def long_path(p: str | os.PathLike) -> str:
    r"""Windows 긴 경로 접두('\\?\' · UNC 는 '\\?\UNC\') — 260자 넘는 경로도 지우고 열 수 있게. 다른 OS 는 그대로."""
    s = os.path.abspath(os.fspath(p))
    if os.name != "nt" or s.startswith("\\\\?\\"):
        return s
    if s.startswith("\\\\"):
        return "\\\\?\\UNC\\" + s[2:]
    return "\\\\?\\" + s


def _onerror_writable(func, path, _exc):
    """shutil.rmtree onerror — 읽기 전용 속성(파일·폴더)을 풀고 한 번 더."""
    with contextlib.suppress(OSError):
        os.chmod(path, stat.S_IWRITE)
        func(path)


def _rm_entry(p: str) -> None:
    """파일·링크·폴더 하나 지우기(긴 경로 문자열). 실패는 조용히 — 호출자가 남은 것을 보고 다시 시도한다."""
    try:
        st = os.lstat(p)
    except OSError:
        return
    if stat.S_ISDIR(st.st_mode) and not stat.S_ISLNK(st.st_mode) and not getattr(st, "st_reparse_tag", 0):
        with contextlib.suppress(OSError):
            os.chmod(p, stat.S_IWRITE)
        shutil.rmtree(p, onerror=_onerror_writable)
        return
    with contextlib.suppress(OSError):
        os.chmod(p, stat.S_IWRITE)
    with contextlib.suppress(OSError):
        if stat.S_ISDIR(st.st_mode):
            os.rmdir(p)                                  # 폴더 접합점·심볼릭 링크 — 대상은 따라가지 않는다
        else:
            os.remove(p)


def _rmtree(p: str | os.PathLike, tries: int = 6, *, last: str | None = None) -> bool:
    """복제·임시 폴더 지우기: 긴 경로 접두로, 읽기 전용 속성은 풀고(파일·폴더), 잠긴 파일(막 끝난 자식 프로세스의
    핸들·백신 검사)은 물러섰다가(0.25·0.5·…·최대 2초) 다시 시도한다. ``last`` = 맨 마지막에 지울 바로 아래 항목 이름
    (복제 표지 — 다 못 지우면 남겨 두어 남은 조각을 청소가 알아보게). 다 지웠으면 True."""
    lp = long_path(p)
    for i in range(max(1, int(tries))):
        if not os.path.lexists(lp):
            return True
        with contextlib.suppress(OSError):
            os.chmod(lp, stat.S_IWRITE)
        try:
            st = os.lstat(lp)
            linked = stat.S_ISLNK(st.st_mode) or bool(getattr(st, "st_reparse_tag", 0))
        except OSError:
            linked = False
        try:
            names = None if linked else os.listdir(lp)  # 링크·접합점이면 그 링크만 지운다(대상 내용은 따라가지 않는다)
        except NotADirectoryError:
            names = None
        except OSError:
            names = []
        if names is None:
            _rm_entry(lp)
        else:
            for n in names:
                if n != last:
                    _rm_entry(os.path.join(lp, n))
            try:
                rest = os.listdir(lp)
            except OSError:
                rest = None
            if rest is not None and all(n == last for n in rest):
                if last and rest:
                    _rm_entry(os.path.join(lp, last))
                with contextlib.suppress(OSError):
                    os.rmdir(lp)
        if not os.path.lexists(lp):
            return True
        if i + 1 < tries:
            time.sleep(min(2.0, 0.25 * (i + 1)))
    return not os.path.lexists(lp)


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


def _proc_info(pid: int) -> tuple[bool, float | None]:
    """(살아 있음, 시작 시각 epoch 초 또는 None). 열 수 없으면 권한 없음 = (True, None)(지우지 않는 쪽) · 그 밖 = 없음."""
    if pid <= 0:
        return False, None
    if os.name != "nt":
        return True, None
    k, ctypes, wintypes = _k32()
    h = k.OpenProcess(0x1000, False, int(pid))          # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return ctypes.get_last_error() == 5, None        # 권한 없음 = 있다 · 그 밖(87 등) = 없다
    try:
        code = wintypes.DWORD()
        if not k.GetExitCodeProcess(h, ctypes.byref(code)):
            return True, None
        if code.value != 259:                            # STILL_ACTIVE 가 아니면 끝남
            return False, None
        ft = [wintypes.FILETIME() for _ in range(4)]
        if not k.GetProcessTimes(h, *(ctypes.byref(x) for x in ft)):
            return True, None
        t100 = (ft[0].dwHighDateTime << 32) | ft[0].dwLowDateTime
        return True, t100 / 1e7 - 11644473600.0          # FILETIME(1601 기점 100ns) → epoch 초
    finally:
        k.CloseHandle(h)


def _pid_alive(pid: int) -> bool:
    """그 프로세스가 아직 살아 있는가(Windows: OpenProcess + GetExitCodeProcess). 판단할 수 없으면 True(지우지 않는 쪽)."""
    return _proc_info(pid)[0]


def _mark_fields(d: Path) -> dict:
    """복제 표지 내용(키=값 줄). 읽을 수 없으면 빈 dict."""
    try:
        txt = (d / CLONE_MARK).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {}
    out = {}
    for line in txt.splitlines():
        k, _, v = line.partition("=")
        if k.strip():
            out[k.strip()] = v.strip()
    return out


def _mark_owner(d: Path) -> int:
    """복제 표지의 주인 PID(owner=, 옛 표지는 0)."""
    v = _mark_fields(d).get("owner", "")
    return int(v) if v.isdigit() else 0


def _owner_gone(d: Path) -> bool:
    """표지의 주인 프로세스가 끝났는가 — 같은 PID 가 복제를 만든 뒤에 시작한 다른 프로세스면(PID 재사용) 끝난 것으로 본다."""
    f = _mark_fields(d)
    owner = int(f["owner"]) if f.get("owner", "").isdigit() else 0
    if not owner:
        return True
    alive, started = _proc_info(owner)
    if not alive:
        return True
    try:
        made = float(f.get("made", ""))
    except ValueError:
        return False
    return started is not None and started > made + 2.0


def _last_touch(d: Path) -> float:
    """복제를 마지막으로 손댄 시각 — 폴더·표지와 2단까지의 폴더 수정 시각 중 가장 늦은 것(파일을 만들거나 바꾸면 그 폴더의
    수정 시각이 바뀐다 · run_py 는 표지를 갱신한다). 깊은 곳만 바뀐 복제는 이름 바꾸기 검사(열린 파일·작업 폴더)가 지킨다."""
    best = 0.0
    with contextlib.suppress(OSError):
        best = os.stat(long_path(d)).st_mtime
    with contextlib.suppress(OSError):
        best = max(best, os.stat(long_path(d / CLONE_MARK)).st_mtime)
    frontier = [long_path(d)]
    for _depth in range(2):
        nxt = []
        for top in frontier:
            try:
                it = os.scandir(top)
            except OSError:
                continue
            with it:
                for e in it:
                    try:
                        if e.is_dir(follow_symlinks=False):
                            best = max(best, e.stat(follow_symlinks=False).st_mtime)
                            nxt.append(e.path)
                    except OSError:
                        continue
        frontier = nxt
    return best


def sweep_stale(base: str | os.PathLike | None = None, *, age_s: float = STALE_AGE_S, orphan_s: float = ORPHAN_AGE_S,
                now: float | None = None, keep: Sequence[os.PathLike] = ()) -> list[Path]:
    r"""%TEMP%(또는 그 아래 base)의 오래된 lm27t_* 폴더를 지운다 — 지운 목록. 지우는 것은:
    ① ``age_s`` 넘게 손대지 않았고 복제 표지의 주인 프로세스(owner=)가 끝난(PID 재사용 포함 · 표지 없으면 통과) 것
    ② ``orphan_s`` 넘게 손대지 않은 표지 있는 복제(주인이 오래 사는 프로세스라 살아 있어도 — 남은 고아 복제)
    둘 다 이름 바꾸기가 되어야 한다(= 그 안에 작업 폴더·열린 파일을 가진 프로세스가 없다 — 쓰는 중인 복제는 건드리지 않는다).
    지우다 남은 것(``.sweep``)은 다음 청소가 이어서 지운다."""
    b = Path(base).resolve() if base is not None else _TMP_BASE
    if not (_is_under(b, _TMP_BASE)):
        raise AssertionError(f"청소 위치는 %TEMP% 아래여야 합니다: {b}")
    t = time.time() if now is None else now
    keep_n = {os.path.normcase(str(Path(k).resolve())) for k in keep}
    out = []
    try:
        names = sorted(os.listdir(b))
    except OSError:
        return out
    for n in names:
        if not n.startswith(CLONE_PREFIX):
            continue
        d = b / n
        if os.path.normcase(str(d)) in keep_n:
            continue
        try:
            if not stat.S_ISDIR(os.lstat(d).st_mode):
                continue
        except OSError:
            continue
        idle = t - _last_touch(d)
        if idle < age_s:
            continue
        marked = (d / CLONE_MARK).is_file()
        if not _owner_gone(d) and not (marked and idle >= orphan_s):
            continue
        trash = d if n.endswith(".sweep") else b / (n + ".sweep")
        if trash != d:
            try:
                os.rename(long_path(d), long_path(trash))
            except OSError:
                continue                                 # 누군가 그 안을 쓰고 있다(작업 폴더·열린 파일)
        if _rmtree(trash, tries=2, last=CLONE_MARK):
            out.append(d)
    return out


def _sweep_once() -> None:
    global _SWEPT
    if _SWEPT:
        return
    _SWEPT = True
    with contextlib.suppress(OSError, AssertionError):
        gone = sweep_stale()
        if gone:
            sys.stderr.write(f"[tree] 오래된 시험 폴더 {len(gone)}개를 청소했습니다\n")


class _KillJob:
    """자식을 Job Object 에 넣는다(KILL_ON_JOB_CLOSE) — 닫으면 남은 자손이 모두 끝난다(lm27.util.proc._Job 과 같은 ctypes,
    tree.py 는 표준 라이브러리만 import 하므로 복사). 못 만들면(권한·중첩 제한·다른 OS) 없는 것으로 동작한다."""

    _LIMIT_KILL_ON_JOB_CLOSE = 0x2000
    _EXTENDED_LIMIT_INFORMATION = 9

    def __init__(self, pid: int):
        self.h = None
        if os.name != "nt":
            return
        try:
            import ctypes
            from ctypes import wintypes

            class _Basic(ctypes.Structure):
                _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                            ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                            ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                            ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                            ("SchedulingClass", wintypes.DWORD)]

            class _Io(ctypes.Structure):
                _fields_ = [(n, ctypes.c_uint64) for n in ("ReadOperationCount", "WriteOperationCount",
                                                           "OtherOperationCount", "ReadTransferCount",
                                                           "WriteTransferCount", "OtherTransferCount")]

            class _Ext(ctypes.Structure):
                _fields_ = [("BasicLimitInformation", _Basic), ("IoInfo", _Io), ("ProcessMemoryLimit", ctypes.c_size_t),
                            ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                            ("PeakJobMemoryUsed", ctypes.c_size_t)]

            k = ctypes.WinDLL("kernel32", use_last_error=True)
            k.CreateJobObjectW.restype = wintypes.HANDLE
            k.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
            k.SetInformationJobObject.restype = wintypes.BOOL
            k.SetInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD)
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
            info = _Ext()
            info.BasicLimitInformation.LimitFlags = self._LIMIT_KILL_ON_JOB_CLOSE
            ok = bool(k.SetInformationJobObject(job, self._EXTENDED_LIMIT_INFORMATION, ctypes.byref(info),
                                                ctypes.sizeof(info)))
            ph = k.OpenProcess(0x0100 | 0x0001, False, int(pid)) if ok else None   # SET_QUOTA | TERMINATE
            ok = ok and bool(ph) and bool(k.AssignProcessToJobObject(job, ph))
            if ph:
                k.CloseHandle(ph)
            if ok:
                self.h = job
            else:
                k.CloseHandle(job)
        except (OSError, AttributeError, ValueError):
            self.h = None

    def terminate(self) -> None:
        if self.h:
            self.k.TerminateJobObject(self.h, 1)

    def close(self) -> None:
        """핸들을 닫는다 — KILL_ON_JOB_CLOSE 라 아직 남은 자손(고아 손주)은 여기서 끝난다."""
        if self.h:
            self.k.CloseHandle(self.h)
            self.h = None


def _kill_tree(pid: int) -> None:
    """``taskkill /T /F /PID`` — 자식과 그 아래 트리(부모가 살아 있는 동안 닿는 것). Windows 전용(다른 OS 는 호출자가 p.kill)."""
    if os.name != "nt":
        return
    sysroot = os.environ.get("SystemRoot") or os.environ.get("windir") or "C:\\Windows"
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        subprocess.run([os.path.join(sysroot, "System32", "taskkill.exe"), "/T", "/F", "/PID", str(int(pid))],
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30,
                       creationflags=CREATE_NO_WINDOW, check=False)


def _pipe_reader(stream, sink: list) -> threading.Thread:
    """파이프를 끝까지 읽는 데몬 스레드(끝나면 그 파이프를 닫는다). 손주가 쥔 파이프는 손주가 끝날 때 끝난다."""
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
            with contextlib.suppress(OSError):
                stream.close()
    t = threading.Thread(target=run, name="lm27t-pipe", daemon=True)
    t.start()
    return t


def _pipe_writer(stream, data: bytes) -> threading.Thread:
    def run():
        try:
            stream.write(data)
        except (OSError, ValueError):
            pass
        finally:
            with contextlib.suppress(OSError):
                stream.close()
    t = threading.Thread(target=run, name="lm27t-stdin", daemon=True)
    t.start()
    return t


DRAIN_S = 2.0                                            # 자식이 끝난 뒤 파이프 꼬리를 더 읽는 최대 시간
KILL_WAIT_S = 10.0                                       # 시간 초과로 끊은 뒤 자식이 사라지기를 기다리는 최대 시간


def run_tree(argv: Sequence[str], *, cwd: str, env: Mapping[str, str] | None, data: bytes | None,
             timeout: float) -> subprocess.CompletedProcess:
    """자식을 Job Object 에 넣어 실행 — subprocess.run(capture_output, timeout) 과 같은 결과·예외. 다른 점(C19·C23):
    시간 초과면 ``taskkill /T`` + Job 종료로 **트리째** 끊고(자식만 죽여 손주가 고아로 남던 것), 손주가 파이프를 쥐어도
    읽기는 유한 시간만 기다린 뒤 ``TimeoutExpired``(지금까지 모은 출력 포함)를 올린다. 정상 종료여도 Job 을 닫아 남은 자손을
    끝낸다(시험 하네스는 아무것도 남기지 않는다). 다 읽은 파이프만 닫는다(proc.run_child 와 같은 규칙)."""
    p = subprocess.Popen(list(argv), cwd=cwd, env=dict(env) if env is not None else None,
                         stdin=subprocess.PIPE if data is not None else subprocess.DEVNULL,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0)
    job = _KillJob(p.pid)
    out: list = []
    err: list = []
    readers = [_pipe_reader(p.stdout, out), _pipe_reader(p.stderr, err)]
    if data is not None:
        _pipe_writer(p.stdin, data)
    timed_out = False
    try:
        try:
            p.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill_tree(p.pid)
            job.terminate()                              # 부모가 먼저 끝나 /T 가 닿지 않는 고아 손주까지
            try:
                p.wait(timeout=KILL_WAIT_S)
            except subprocess.TimeoutExpired:
                p.kill()
                with contextlib.suppress(subprocess.TimeoutExpired):
                    p.wait(timeout=KILL_WAIT_S)
        job.close()                                      # 남은 자손 끝내기 — 그래야 손주가 쥔 파이프도 EOF 가 된다
        deadline = time.monotonic() + DRAIN_S
        for t in readers:
            t.join(max(0.0, deadline - time.monotonic()))
    finally:
        job.close()
    so, se = b"".join(list(out)), b"".join(list(err))
    if timed_out:
        raise subprocess.TimeoutExpired(list(argv), timeout, output=so, stderr=se)
    return subprocess.CompletedProcess(list(argv), p.returncode, so, se)


def _ignore_for(src: Path):
    def _ignore(d: str, names: list[str]) -> set[str]:
        rel = Path(os.path.relpath(d, src))
        out = set()
        for n in names:
            if n in SKIP_NAMES or n.endswith((".pyc", ".pyo", ".part")):
                out.add(n)
            elif (rel / n).as_posix() in SKIP_REL:
                out.add(n)
        return out
    return _ignore


def _copy_quiet(s: str, d: str) -> str:
    """복제 중 원본 파일이 사라지면(다른 작업이 막 지운 임시 파일 등) 그 파일만 건너뛴다."""
    try:
        return shutil.copy2(s, d)
    except FileNotFoundError:
        return d


class Clone:
    """%TEMP% 복제 트리 하나. with 문 또는 remove() 로 지운다."""

    def __init__(self, root: str | os.PathLike, src: str | os.PathLike | None = None):
        self.root = assert_test_root(root)
        self.src = Path(src).resolve() if src else SOURCE_ROOT
        self.py_home = python_home()

    # ── 경로 ───────────────────────────────────────────────────────────────
    @property
    def python(self) -> Path:
        return self.py_home / "python.exe"

    @property
    def pythonw(self) -> Path:
        return self.py_home / "pythonw.exe"

    @property
    def sandbox(self) -> Path:
        return self.root / "_sandbox"

    @property
    def lad(self) -> Path:
        """복제 전용 %LOCALAPPDATA%."""
        return self.sandbox / "LocalAppData"

    @property
    def temp(self) -> Path:
        """복제 전용 %TEMP%(자식 프로세스의 작업 폴더)."""
        return self.sandbox / "Temp"

    def path(self, *parts: str) -> Path:
        return self.root.joinpath(*parts)

    # ── 환경 ───────────────────────────────────────────────────────────────
    def env(self, extra: Mapping[str, object] | None = None, **kw: object) -> dict[str, str]:
        """자식 프로세스 환경: 주입 변수는 비우고(명시한 것만), LOCALAPPDATA·TEMP 는 복제 안으로.
        값이 None 이면 그 변수를 지운다."""
        e = dict(os.environ)
        for k in INJECT_VARS:
            e.pop(k, None)
        e.update({
            "LOCALAPPDATA": str(self.lad), "TEMP": str(self.temp), "TMP": str(self.temp),
            "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8",
            "LM27T_CLONE": str(self.root), "LM27T_SRC_ROOT": str(self.src), "LM27T_PY_HOME": str(self.py_home),
            "LM27T_TMP_BASE": str(_TMP_BASE),
        })
        if FORBIDDEN_LIST:
            e["LM27T_FORBIDDEN_WORDS"] = FORBIDDEN_LIST
        else:
            e.pop("LM27T_FORBIDDEN_WORDS", None)
        for k, v in {**(extra or {}), **kw}.items():
            if v is None:
                e.pop(k, None)
            else:
                e[k] = str(v)
        return e

    @contextlib.contextmanager
    def patched_environ(self, extra: Mapping[str, object] | None = None, **kw: object) -> Iterator[dict[str, str]]:
        """같은 프로세스 안 시험용: os.environ 을 env() 로 잠시 바꾼다(TEMP·TMP 는 그대로 — tempfile 기준이 흔들리지 않게)."""
        saved = dict(os.environ)
        new = self.env(extra, **kw)
        new["TEMP"], new["TMP"] = saved.get("TEMP", ""), saved.get("TMP", "")
        self.lad.mkdir(parents=True, exist_ok=True)
        try:
            os.environ.clear()
            os.environ.update({k: v for k, v in new.items() if v != ""})
            yield new
        finally:
            os.environ.clear()
            os.environ.update(saved)

    # ── 실행 ───────────────────────────────────────────────────────────────
    def run_py(self, args: Sequence[object], *, env: Mapping[str, str] | None = None, input: bytes | str | None = None,
               timeout: float = 300, cwd: str | os.PathLike | None = None,
               flags: Sequence[str] = ("-X", "utf8", "-B"), gui: bool = False) -> subprocess.CompletedProcess:
        """동봉 파이썬으로 실행(창 없음). 스크립트는 c.path("lm27_cli.py") 처럼 절대 경로로 준다. stdout/stderr 는 bytes.
        자식은 Job Object 안에서 돈다(``run_tree`` — 시간 초과면 트리째 끊고 ``TimeoutExpired``, 끝나면 남은 자손도 끝낸다)."""
        self.temp.mkdir(parents=True, exist_ok=True)
        self.lad.mkdir(parents=True, exist_ok=True)
        self.touch()
        exe = self.pythonw if gui else self.python
        argv = [str(exe), *flags, *(str(a) for a in args)]
        data = input.encode("utf-8") if isinstance(input, str) else input
        try:
            return run_tree(argv, cwd=str(cwd or self.temp), env=dict(env) if env is not None else self.env(),
                            data=data, timeout=timeout)
        finally:
            self.touch()

    def touch(self) -> None:
        """복제를 쓰고 있다는 표시(표지 수정 시각 갱신) — 오래 쓰는 복제를 청소가 고아로 보지 않게."""
        with contextlib.suppress(OSError):
            os.utime(long_path(self.root / CLONE_MARK), None)

    def run_cli(self, *args: object, **kw) -> subprocess.CompletedProcess:
        """lm27 <명령> = 동봉 파이썬 + 복제의 lm27_cli.py(계약 §7.1)."""
        return self.run_py([self.path("lm27_cli.py"), *args], **kw)

    def run_unittest(self, area: str, *, pattern: str = "test*.py", timeout: float = 1800,
                     env: Mapping[str, str] | None = None) -> subprocess.CompletedProcess:
        """복제 안에서 "<PY>" -X utf8 -B -m unittest discover -s <clone>\\tests\\<영역> -t <clone>(CR-08)."""
        return self.run_py(["-m", "unittest", "discover", "-s", self.path("tests", area), "-t", self.root,
                            "-p", pattern], timeout=timeout, env=env)

    # ── 정리 ───────────────────────────────────────────────────────────────
    def remove(self, *, tries: int = REMOVE_TRIES) -> bool:
        """복제를 지운다(긴 경로·읽기 전용 속성·잠긴 파일은 물러섰다가 다시 — 최대 약 20초). 복제 표지는 맨 마지막에 지워,
        못 지운 조각에도 표지가 남는다. 못 지우면 stderr 에 남기고 False — 다음 make 의 청소가 쓰는 프로세스가 없어진 뒤
        이어서 지운다(sweep_stale)."""
        root = assert_test_root(self.root)
        if not os.path.lexists(long_path(root)):
            return True
        if not _is_clone_dir(root) and not os.path.lexists(long_path(root / "_sandbox")):
            raise AssertionError(f"복제 표지가 없어 지우지 않습니다: {root}")
        ok = _rmtree(root, tries=tries, last=CLONE_MARK)
        if not ok:
            sys.stderr.write(f"[tree] 복제를 지우지 못했습니다(잠긴 파일): {root}\n")
        return ok

    def __enter__(self) -> Clone:
        return self

    def __exit__(self, *_exc) -> None:
        self.remove()

    def __repr__(self) -> str:
        return f"Clone({str(self.root)!r})"


def make_clone(*, parts: Sequence[str] = CLONE_PARTS, extra: Sequence[str] = (), entry: bool = True,
               owner_pid: int | None = None) -> Clone:
    """%TEMP%\\lm27t_<rand>\\ 에 트리를 복제해 Clone 을 돌려준다. with 문으로 쓰면 끝에 지운다.
    parts = 복제할 최상위 폴더(없는 것은 건너뜀), extra = 더 넣을 폴더·파일(예: "docs"), entry = 진입 스크립트·bat·ruff.toml.
    owner_pid = 복제를 쓰는 프로세스(표지 owner= — 기본 자기 자신, CLI make 는 부른 쪽). 그 프로세스가 끝난 뒤 1시간이
    지나도 남아 있으면 다음 make 가 청소한다."""
    _sweep_once()
    owner = int(owner_pid) if owner_pid else os.getpid()
    root = None
    for _ in range(20):
        cand = _TMP_BASE / (CLONE_PREFIX + secrets.token_hex(4))
        try:
            cand.mkdir()
        except FileExistsError:
            continue
        root = cand
        break
    if root is None:
        raise RuntimeError("복제 폴더 이름을 정하지 못했습니다")
    try:
        (root / CLONE_MARK).write_text(f"src={SOURCE_ROOT}\ntree={TREE_ROOT}\nowner={owner}\nmade={time.time():.0f}\n",
                                       encoding="utf-8")
        src = TREE_ROOT
        ignore = _ignore_for(src)
        for part in dict.fromkeys((*parts, *extra)):    # 같은 부분을 두 번 주면(예: extra=docs) 한 번만 복제
            s = src / part
            if s.is_dir():
                shutil.copytree(s, root / part, ignore=ignore, copy_function=_copy_quiet)
            elif s.is_file():
                shutil.copy2(s, root / part)
        if entry:
            names = [n for n in ENTRY_FILES if (src / n).is_file()]
            for pat in ENTRY_GLOBS:
                names += sorted(p.name for p in src.glob(pat) if p.is_file())
            for n in names:
                shutil.copy2(src / n, root / n)
            for rel in REPO_FILES:
                s = src.joinpath(*rel.split("/"))
                if s.is_file():
                    d = root.joinpath(*rel.split("/"))
                    d.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(s, d)
        clone = Clone(root, SOURCE_ROOT)
        clone.lad.mkdir(parents=True, exist_ok=True)
        clone.temp.mkdir(parents=True, exist_ok=True)
        return clone
    except BaseException:
        _rmtree(root)
        raise


class CloneTestCase(unittest.TestCase):
    """클래스마다 복제 1개: setUpClass 에서 만들고 클래스 정리 때 지운다. cls.clone_extra 로 docs 등을 더한다."""

    clone: Clone
    clone_extra: tuple[str, ...] = ()

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.clone = make_clone(extra=cls.clone_extra)
        cls.addClassCleanup(cls.clone.remove)


def best_of(fn, *, n: int = 3, under: float | None = None) -> float:
    """부하에 민감한 시간 시험용(W1 통합 창 R8): ``fn()`` 을 최대 n 번 재서 가장 짧은 경과(초). ``under`` 보다 짧으면
    바로 멈춘다 — 다른 무거운 작업이 함께 도는 PC 에서 한 번 느린 측정으로 실패하지 않게(최솟값이 실제 비용에 가장 가깝다)."""
    best = float("inf")
    for _ in range(max(1, int(n))):
        t0 = time.perf_counter()
        fn()
        best = min(best, time.perf_counter() - t0)
        if under is not None and best < under:
            break
    return best


def area_dirs(root: str | os.PathLike) -> list[str]:
    """시험 파일이 있는 tests\\<영역> 이름 목록(fixtures·밑줄 시작 폴더 제외)."""
    t = Path(root) / "tests"
    if not t.is_dir():
        return []
    return sorted(p.name for p in t.iterdir()
                  if p.is_dir() and p.name != "fixtures" and not p.name.startswith(("_", "."))
                  and any(p.glob("test*.py")))


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="tree.py", description="LM27 시험 복제 트리(%TEMP%)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    mk = sub.add_parser("make", help="복제만 만들고 경로 출력")
    mk.add_argument("--extra", action="append", default=[])
    rm = sub.add_parser("remove", help="make 로 만든 복제 삭제")
    rm.add_argument("path")
    un = sub.add_parser("unit", help="복제에서 영역별 unittest 실행 후 삭제")
    un.add_argument("areas", nargs="*")
    un.add_argument("--extra", action="append", default=[])
    dc = sub.add_parser("discover", help="make 로 만든 복제에서 영역 하나의 unittest discover")
    dc.add_argument("path")
    dc.add_argument("area")
    dc.add_argument("--pattern", default="test*.py")
    a = ap.parse_args(argv)
    if a.cmd == "make":
        # 복제를 쓰는 쪽은 이 프로세스가 아니라 부른 쪽(lint.ps1 등) — 그 PID 를 주인으로 적는다(청소 판단)
        print(make_clone(extra=tuple(a.extra), owner_pid=os.getppid() or None).root)
        return 0
    if a.cmd == "remove":
        return 0 if Clone(a.path).remove() else 1
    if a.cmd == "discover":
        c = Clone(a.path)
        if not _is_clone_dir(c.root):
            raise AssertionError(f"복제 표지가 없어 실행하지 않습니다: {c.root}")
        cp = c.run_unittest(a.area, pattern=a.pattern)
        sys.stdout.write(cp.stderr.decode("utf-8", "replace"))
        sys.stdout.write(cp.stdout.decode("utf-8", "replace"))
        sys.stdout.flush()
        return cp.returncode
    rc = 0
    with make_clone(extra=tuple(a.extra)) as c:
        for area in (a.areas or area_dirs(c.root)):
            if not c.path("tests", area).is_dir():
                print(f"[unit] {area}: 영역 폴더 없음 — 건너뜀")
                continue
            cp = c.run_unittest(area)
            sys.stdout.write(cp.stderr.decode("utf-8", "replace"))
            sys.stdout.write(cp.stdout.decode("utf-8", "replace"))
            print(f"[unit] {area}: {'통과' if cp.returncode == 0 else '실패'} (rc {cp.returncode})")
            if cp.returncode != 0:
                rc = 1
    return rc


if __name__ == "__main__":
    for _st in (sys.stdout, sys.stderr):
        _rc = getattr(_st, "reconfigure", None)
        if _rc is not None:
            _rc(encoding="utf-8", errors="replace")
    sys.exit(main())
