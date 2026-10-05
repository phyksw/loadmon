# -*- coding: utf-8 -*-
r"""합성 git 저장소(시험 전용, WP-14) — %TEMP% 아래에 작성자·시각을 고정한 커밋을 만든다(실제 사용자 설정과 격리).

    env = isolated_env(tmp)                      # 전역·시스템 git 설정을 읽지 않는 환경(GIT_CONFIG_GLOBAL=빈 파일, NOSYSTEM)
    repo = make_repo(path, self_name, self_email, env=env)
    commit(repo, "홍길동", "hong.gd@example.com", when, "제목", {"a.py": "x"}, env=env)
    branch(repo, "feature", env=env) · checkout(repo, "main", env=env) · merge(repo, "feature", env=env)

이름·주소는 자리표시자(홍길동·김철수 · example.com)만 쓴다.
"""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
from datetime import datetime
from pathlib import Path

from tests.fixtures.tree import guard_write

CREATE_NO_WINDOW = 0x08000000


def git_exe() -> str | None:
    return shutil.which("git")


def remove_tree(path) -> bool:
    """합성 저장소 폴더 지우기 — git 객체 파일은 읽기 전용이라 속성을 풀고 지운다(남기지 않는다)."""
    p = guard_write(path)

    def _onerror(func, target, _exc):
        try:
            os.chmod(target, stat.S_IWRITE)
            func(target)
        except OSError:
            pass

    if p.exists():
        shutil.rmtree(p, onerror=_onerror)
    return not p.exists()


def isolated_env(tmp: str | os.PathLike) -> dict:
    t = guard_write(tmp)
    t.mkdir(parents=True, exist_ok=True)
    g = t / "gitconfig_empty"
    if not g.exists():
        g.write_bytes(b"")
    return {"GIT_CONFIG_GLOBAL": str(g), "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"}


def _git(repo, args, env, extra=None):
    e = dict(os.environ)
    e.update(env or {})
    e.update(extra or {})
    cp = subprocess.run([git_exe(), "-C", str(repo), *args], capture_output=True, env=e, check=False,
                        creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0, timeout=60)
    if cp.returncode != 0:
        raise RuntimeError(f"git {args[0]} 실패 rc={cp.returncode}: {cp.stderr.decode('utf-8', 'replace')[:200]}")
    return cp.stdout.decode("utf-8", "replace")


def make_repo(path, self_name: str | None, self_email: str | None, *, env) -> Path:
    p = guard_write(path)
    p.mkdir(parents=True, exist_ok=True)
    _git(p, ["-c", "init.defaultBranch=main", "init", "-q"], env)
    if self_name:
        _git(p, ["config", "user.name", self_name], env)
    if self_email:
        _git(p, ["config", "user.email", self_email], env)
    _git(p, ["config", "commit.gpgsign", "false"], env)
    return p


def _git_date(when: datetime) -> str:
    return when.strftime("%Y-%m-%dT%H:%M:%S%z")


def commit(repo, name: str, email: str, when: datetime, subject: str, files: dict, *, env,
           committer_when: datetime | None = None) -> str:
    for rel, content in files.items():
        f = Path(repo) / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(content, encoding="utf-8")
        _git(repo, ["add", "--", rel], env)
    cw = committer_when or when
    extra = {"GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": email, "GIT_AUTHOR_DATE": _git_date(when),
             "GIT_COMMITTER_NAME": name, "GIT_COMMITTER_EMAIL": email, "GIT_COMMITTER_DATE": _git_date(cw)}
    _git(repo, ["commit", "-q", "--allow-empty", "-m", subject], env, extra)
    return _git(repo, ["rev-parse", "HEAD"], env).strip()


def branch(repo, name: str, *, env) -> None:
    _git(repo, ["checkout", "-q", "-b", name], env)


def checkout(repo, name: str, *, env) -> None:
    _git(repo, ["checkout", "-q", name], env)


def merge(repo, name: str, when: datetime, *, env, who=("홍길동", "hong.gd@example.com")) -> str:
    extra = {"GIT_AUTHOR_NAME": who[0], "GIT_AUTHOR_EMAIL": who[1], "GIT_AUTHOR_DATE": _git_date(when),
             "GIT_COMMITTER_NAME": who[0], "GIT_COMMITTER_EMAIL": who[1], "GIT_COMMITTER_DATE": _git_date(when)}
    _git(repo, ["merge", "-q", "--no-ff", "-m", "merge " + name, name], env, extra)
    return _git(repo, ["rev-parse", "HEAD"], env).strip()
