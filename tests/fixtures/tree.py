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
INJECT_VARS = ("LM_OUTLOOK_SELFTEST", "LM_INDEX_FAKE", "LM_OWA_FAKE", "LM_TEAMSWEB_FAKE", "LM_COPILOT_STUB",
               "LM_NO_BROWSER")                          # 계약 §11.3 환경 변수 주입점 — 시험이 명시할 때만 넘긴다
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


def _rmtree(p: Path, tries: int = 5) -> bool:
    def _onerror(func, path, _exc):
        with contextlib.suppress(OSError):
            os.chmod(path, stat.S_IWRITE)
            func(path)

    for i in range(tries):
        if not p.exists():
            return True
        shutil.rmtree(p, onerror=_onerror)
        if not p.exists():
            return True
        time.sleep(0.2 * (i + 1))                        # 자식 프로세스가 막 끝나 핸들이 남은 경우
    return not p.exists()


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
        """동봉 파이썬으로 실행(창 없음). 스크립트는 c.path("lm27_cli.py") 처럼 절대 경로로 준다. stdout/stderr 는 bytes."""
        self.temp.mkdir(parents=True, exist_ok=True)
        self.lad.mkdir(parents=True, exist_ok=True)
        exe = self.pythonw if gui else self.python
        argv = [str(exe), *flags, *(str(a) for a in args)]
        data = input.encode("utf-8") if isinstance(input, str) else input
        return subprocess.run(argv, cwd=str(cwd or self.temp), env=dict(env) if env is not None else self.env(),
                              input=data, capture_output=True, timeout=timeout,
                              creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0, check=False)

    def run_cli(self, *args: object, **kw) -> subprocess.CompletedProcess:
        """lm27 <명령> = 동봉 파이썬 + 복제의 lm27_cli.py(계약 §7.1)."""
        return self.run_py([self.path("lm27_cli.py"), *args], **kw)

    def run_unittest(self, area: str, *, pattern: str = "test*.py", timeout: float = 1800,
                     env: Mapping[str, str] | None = None) -> subprocess.CompletedProcess:
        """복제 안에서 "<PY>" -X utf8 -B -m unittest discover -s <clone>\\tests\\<영역> -t <clone>(CR-08)."""
        return self.run_py(["-m", "unittest", "discover", "-s", self.path("tests", area), "-t", self.root,
                            "-p", pattern], timeout=timeout, env=env)

    # ── 정리 ───────────────────────────────────────────────────────────────
    def remove(self) -> bool:
        root = assert_test_root(self.root)
        if not root.exists():
            return True
        if not _is_clone_dir(root):
            raise AssertionError(f"복제 표지가 없어 지우지 않습니다: {root}")
        return _rmtree(root)

    def __enter__(self) -> Clone:
        return self

    def __exit__(self, *_exc) -> None:
        self.remove()

    def __repr__(self) -> str:
        return f"Clone({str(self.root)!r})"


def make_clone(*, parts: Sequence[str] = CLONE_PARTS, extra: Sequence[str] = (), entry: bool = True) -> Clone:
    """%TEMP%\\lm27t_<rand>\\ 에 트리를 복제해 Clone 을 돌려준다. with 문으로 쓰면 끝에 지운다.
    parts = 복제할 최상위 폴더(없는 것은 건너뜀), extra = 더 넣을 폴더·파일(예: "docs"), entry = 진입 스크립트·bat·ruff.toml."""
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
        (root / CLONE_MARK).write_text(f"src={SOURCE_ROOT}\ntree={TREE_ROOT}\n", encoding="utf-8")
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
        print(make_clone(extra=tuple(a.extra)).root)
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
