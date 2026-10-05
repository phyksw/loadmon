# -*- coding: utf-8 -*-
r"""pc.git 수집기(CP §9, 계약 §2.17 · §7.3) — 본인 git 커밋을 정제해 로컬 원장(pc_git)에 쓴다. 파이썬 수집기(in-process 정제).

    "<PY>" -X utf8 -I -B collect\Get-GitActivity.py --pc <pc_id> [--from YYYY-MM-DD] [--to YYYY-MM-DD] [--scan <폴더>]

이전 판 ``Get-GitActivity.py`` 이식 + 다시 설계:
  · **본인 신원 정확 일치만**: 저장소별(+전역) ``git config user.name``·``user.email`` 과 ``%an``·``%ae`` 가 정규화(공백·대소문자)
    정확 일치하는 커밋만. ``--author`` 는 앵커 정규식(``^이름 <``·``<메일>$``)으로 1차만 거른다. 계정명(USERNAME)은 git 신원이
    하나도 없을 때만 보조(동료 커밋 혼입 결함 수정).
  · 전 브랜치(``--branches --remotes --source --no-merges``), 해시 중복 제거, ``LC_ALL=C``, 작성 시각은 ``%at``(유닉스 초)
    → UTC + 그 순간의 이 PC 오프셋(UTC 로 설정된 WSL·CI 의 9시간 어긋남 없음). ``--since=(from − 60일)`` 로 넉넉히 받고
    기간은 작성 시각으로 다시 건다(rebase·amend 회수).
  · git 실행 파일: ``pc.git.exe`` → PATH → Git for Windows·GitHub Desktop·SourceTree·Visual Studio 내장 순. 없으면 '0건 성공'이
    아니라 **rc 3 + R-NOGIT**. 모든 저장소가 실패해도 rc 3 + R-NOGIT.
  · 원시 레코드(저장소 경로·커밋 sha·커밋 제목 원문)는 메모리에서 ``lm27.privacy.sanitize.sanitize_record("pc_git", …)`` 로만
    정제하고, 통과 행만 ``lm27.store.SegmentWriter`` 로 쓴다(원문·전체 경로 디스크 0 — 계약 §1.5). 사적 폴더 저장소는 정제기가
    행 폐기(건수만). 이전 판의 커밋 CSV·상태 JSON 파일은 쓰지 않는다 — 상태는 stderr 마지막 줄 ``{"_status": …}``.
  · 커서(계약 §3.10): ``{last_ts_utc, repos{<doc_key>: <commit_key>}}`` — ``SegmentWriter.flush()`` 성공 뒤에만
    ``save_raw_cursor(paths, pc_id, "pc.git", value)``. 커서 − 14일 이후 커밋만 다시 쓴다(늦게 받은 커밋 회수, 중복은 id 로 흡수).
  · 시간 상수(계약 §5.3): 저장소당 60초, 단계 240초 — 넘으면 남은 저장소를 건너뛰고 partial + R-BUDGET.

rc(계약 §8.1): 0 새 커밋 저장 · 1 저장소·본인 커밋 없음 · 3 git 없음·전 저장소 실패(R-NOGIT)·정제·저장 실패(R-TRANSPORT)
· 4 읽었지만 커서 뒤 새 커밋 0.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)   # L-05 · 계약 §9.1 — collect\*.py 는 첫 실행문에서 자기 루트를 넣는다

import argparse
import glob
import json
import re
import shutil
import time
from datetime import UTC, date, datetime, timedelta

from lm27.util import proc as _proc
from lm27.util import tz as _tz

SRC = "pc.git"
KIND = "pc_git"
REPO_TIMEOUT_S = 60          # git 저장소당(계약 §5.3)
STAGE_BUDGET_S = 240         # 단계 전체(계약 §5.3)
SINCE_PAD_DAYS = 60          # --since 여유(rebase·amend 회수)
REVISIT_DAYS = 14            # 커서 − 이 일수 이후 커밋을 다시 쓴다(늦게 받은 커밋 회수 — 중복은 레코드 id 로 흡수)
FIND_DEPTH = 4
FIND_LIMIT = 40
FALLBACK_DEPTH = 3
EXT_RX = re.compile(r"^\.[0-9a-z]{1,5}$")
PC_ID_RX = re.compile(r"^pcx?_[0-9a-f]{16}$")
DATE_RX = re.compile(r"^\d{4}-\d{2}-\d{2}$")
NO_WIN = 0x08000000 if os.name == "nt" else 0

# 패키지·빌드 폴더(파일 수집기와 같은 목록) — 저장소 탐색이 내려가지 않는다. 업무 폴더와 이름이 겹치는 여덟 이름은 빌드 표식이 있을 때만.
PKG_DIRS = {".venv", "venv", "env", ".env", "node_modules", "site-packages", "__pycache__", ".git", ".tox", ".nox",
            ".mypy_cache", ".pytest_cache", "build", "dist", "target", ".idea", ".vs", ".vscode", "packages", ".conda",
            "conda-meta", "x64", "debug", "release"}
PKG_MAYBE = {"release", "target", "debug", "x64", "build", "dist", "env", "packages"}
MARK_IN = {"cmakecache.txt", "cachedir.tag", "pyvenv.cfg", "build.ninja", ".ninja_log", "compile_commands.json",
           "objects.list", "repositories.config", "makefile", "cmakefiles", "maven-status", "conda-meta",
           "site-packages", "node_modules"}
MARK_IN_SFX = (".pdb", ".obj", ".ilk", ".idb", ".o", ".d", ".su", ".pch", ".whl", ".nupkg", ".jar", ".class", ".tlog",
               ".recipe", ".pyc", ".exp")
MARK_UP = {"cmakelists.txt", "package.json", "setup.py", "pyproject.toml", "setup.cfg", "cargo.toml", "pom.xml",
           "build.gradle", "build.gradle.kts", "tsconfig.json", ".cproject", ".git", "meson.build", "sconstruct"}
MARK_UP_SFX = (".sln", ".vcxproj", ".csproj", ".vbproj", ".fsproj", ".uvprojx", ".uvproj", ".ewp", ".ioc", ".pro", ".cbp")

RS, US = "\x1e", "\x1f"
LOG_FORMAT = "--format=%x1e%H%x1f%at%x1f%an%x1f%ae%x1f%S%x1f%s"


# ───────────────────────────── 시각 ─────────────────────────────
def _utc_iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_utc(s):
    if not isinstance(s, str) or not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)


def _local_date(dt_utc: datetime):
    return (dt_utc + timedelta(minutes=_tz.capture_offset_min(dt_utc))).date()


# ───────────────────────────── git 실행 파일 ─────────────────────────────
def find_git(cfg_exe: str = ""):
    """git 실행 파일 → (경로 또는 None, 찾아본 곳 수). pc.git.exe(파일 또는 설치 폴더) → PATH → GUI 클라이언트 내장 git."""
    tried = 0
    exe = str(cfg_exe or "").strip().strip('"')
    if exe:
        for c in (exe, os.path.join(exe, "cmd", "git.exe"), os.path.join(exe, "bin", "git.exe"), os.path.join(exe, "git.exe")):
            tried += 1
            if os.path.isfile(c):
                return c, tried
    p = shutil.which("git")
    tried += 1
    if p:
        return p, tried
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    lad = os.environ.get("LOCALAPPDATA", "")
    vs_tail = ("Common7", "IDE", "CommonExtensions", "Microsoft", "TeamFoundation", "Team Explorer", "Git", "cmd",
               "git.exe")
    pats = [os.path.join(pf, "Git", "cmd", "git.exe"), os.path.join(pf86, "Git", "cmd", "git.exe"),
            os.path.join(pf, "Microsoft Visual Studio", "*", "*", *vs_tail),
            os.path.join(pf86, "Microsoft Visual Studio", "*", "*", *vs_tail)]
    if lad:
        pats += [os.path.join(lad, "Programs", "Git", "cmd", "git.exe"),
                 os.path.join(lad, "GitHubDesktop", "app-*", "resources", "app", "git", "cmd", "git.exe"),
                 os.path.join(lad, "Atlassian", "SourceTree", "git_local", "cmd", "git.exe")]
    for pat in pats:
        tried += 1
        for c in sorted(glob.glob(pat), reverse=True):
            if os.path.isfile(c):
                return c, tried
    return None, tried


def git_env() -> dict:
    """git 자식 환경 — 메시지 언어 C(한국어 shortstat 대비), 대화형 프롬프트·선택 잠금 끔."""
    return {"LC_ALL": "C", "LANG": "C", "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0"}


def run_git(exe, repo, args, timeout_s=REPO_TIMEOUT_S):
    """→ (stdout 문자열, rc). 시간 초과는 rc 124, 실행 불가는 127(원인 구분 집계용)."""
    try:
        r = _proc.run_child([exe, "-C", repo, "-c", "core.quotepath=off", *args], timeout_s=timeout_s, env=git_env())
    except OSError:
        return "", 127
    if r.timed_out:
        return "", 124
    return r.stdout.decode("utf-8", "replace"), int(r.rc if r.rc is not None else 124)


# ───────────────────────────── 저장소 탐색 ─────────────────────────────
_MARK_CACHE: dict = {}


def _has_marks(d, exact, sfx):
    k = (d.lower(), exact is MARK_IN)
    if k in _MARK_CACHE:
        return _MARK_CACHE[k]
    r = False
    try:
        with os.scandir(d) as it:
            for n, e in enumerate(it):
                if n >= 5000:
                    break
                b = e.name.lower()
                if b in exact or b.endswith(sfx):
                    r = True
                    break
    except OSError:
        r = False
    _MARK_CACHE[k] = r
    return r


def _skip_dir(dirpath, name):
    n = name.lower()
    if (n in PKG_DIRS and n not in PKG_MAYBE) or n.startswith("cmake-build-"):
        return True
    if n in PKG_MAYBE:
        p = os.path.join(dirpath, name)
        return _has_marks(p, MARK_IN, MARK_IN_SFX) or _has_marks(dirpath, MARK_UP, MARK_UP_SFX)
    return False


def find_repos(roots, *, max_depth=FIND_DEPTH, limit=FIND_LIMIT, pkg_on=True, deadline=None):
    """``.git`` 을 가진 폴더 탐색(깊이 제한·개수 제한·시간 제한). 패키지·빌드 폴더는 내려가지 않는다. 중첩 저장소는 건너뛴다."""
    found = []
    for root in roots:
        if not root or not os.path.isdir(root):
            continue
        base = os.path.abspath(root).rstrip("\\/").count(os.sep)
        for dirpath, dirnames, _files in os.walk(root):
            if deadline is not None and time.monotonic() > deadline:
                return found
            if dirpath.rstrip("\\/").count(os.sep) - base >= max_depth:
                dirnames[:] = []
            if pkg_on:
                dirnames[:] = [d for d in dirnames if not _skip_dir(dirpath, d)]
            else:
                dirnames[:] = [d for d in dirnames if d.lower() not in (".git", "node_modules", "__pycache__")]
            if os.path.exists(os.path.join(dirpath, ".git")):
                found.append(dirpath)
                dirnames[:] = []
                if len(found) >= limit:
                    return found
    return found


def _dedupe(paths):
    out, seen = [], set()
    for p in paths:
        k = os.path.normcase(os.path.abspath(p))
        if k not in seen:
            seen.add(k)
            out.append(p)
    return out


# ───────────────────────────── 신원·커밋 ─────────────────────────────
def norm_id(s) -> str:
    """작성자 이름·메일 정규화 — 공백 정리·소문자(정확 일치 대조용)."""
    return re.sub(r"\s+", " ", str(s or "").strip()).lower()


def identities(exe, repo) -> set:
    """그 저장소에서 '나'의 git 신원(정규화) — 저장소 설정(없으면 전역) user.name·user.email + 전역 값."""
    ids = set()
    for args in (["config", "--get", "user.name"], ["config", "--get", "user.email"],
                 ["config", "--global", "--get", "user.name"], ["config", "--global", "--get", "user.email"]):
        out, rc = run_git(exe, repo, args, timeout_s=15)
        if rc == 0 and out.strip():
            ids.add(out.strip())
    return ids


_BRE_SPECIAL = set(".[]*^$\\")


def _bre_escape(s):
    return "".join(("\\" + c) if c in _BRE_SPECIAL else c for c in s)


def author_patterns(authors):
    """--author 앵커 정규식(1차 관문 — 최종 판정은 정규화 정확 일치). git 은 'Name <email>' 에 대조한다."""
    pats = []
    for a in sorted(str(x or "").strip() for x in authors):
        if not a:
            continue
        pats.append("^" + _bre_escape(a) + " <")
        if "@" in a:
            pats.append("<" + _bre_escape(a) + ">$")
    return list(dict.fromkeys(pats))[:12]


def log_commits(exe, repo, since_day: date, authors, *, timeout_s=REPO_TIMEOUT_S):
    """저장소 하나의 내 커밋 → (커밋 목록, 다른 작성자 수, rc). 커밋 = {sha, at(UTC datetime), subject, files[]}."""
    ids = {norm_id(a) for a in authors if str(a or "").strip()}
    if not ids:
        return [], 0, 0
    args = ["log", "--branches", "--remotes", "--source", "--no-merges", f"--since={since_day.isoformat()}", LOG_FORMAT,
            "--name-only", "--basic-regexp", "--regexp-ignore-case"]
    args += [f"--author={p}" for p in author_patterns(authors)]
    out, rc = run_git(exe, repo, args, timeout_s=timeout_s)
    if rc != 0:
        return [], 0, rc
    commits, others = [], 0
    for block in out.split(RS):
        if not block.strip():
            continue
        head, _, rest = block.partition("\n")
        p = head.split(US)
        if len(p) < 6:
            continue
        sha, at, an, ae, _ref, subj = p[0], p[1], p[2], p[3], p[4], US.join(p[5:])
        if norm_id(an) not in ids and norm_id(ae) not in ids:
            others += 1
            continue
        try:
            when = datetime.fromtimestamp(int(at), UTC)
        except (ValueError, OverflowError, OSError):
            continue
        files = [ln.strip() for ln in rest.splitlines() if ln.strip()]
        commits.append({"sha": sha.strip(), "at": when, "subject": subj.strip(), "files": files})
    return commits, others, 0


def _exts(files) -> list:
    out = set()
    for f in files:
        base = re.split(r"[\\/]", f)[-1].lower()
        i = base.rfind(".")
        if i > 0 and EXT_RX.match(base[i:]):
            out.add(base[i:])
    return sorted(out)[:10]


def raw_record(repo, c, observed_at: str) -> dict:
    """정제 전 원시 레코드(P §10.2 pc_git 원시 이름). 작성자 신원은 넘기지 않는다."""
    return {"repo_root": repo, "commit_sha": c["sha"], "subject": c["subject"][:300], "n_commits": 1,
            "n_files": min(len(c["files"]), 100000), "exts": _exts(c["files"]), "ts_utc": _utc_iso(c["at"]),
            "ts_local_offset": _tz.fmt_offset(_tz.capture_offset_min(c["at"])), "ts_precision": "minute",
            "observed_at": observed_at, "confidence": 1.0, "flags": {}}


# ───────────────────────────── 정제·저장(계약 §2.2·§2.3 — 지연 import) ─────────────────────────────
def store_api():
    """정제·저장 함수 묶음. 수집기 파이썬은 lm27.privacy 에서 sanitize 모듈만 import 한다(L-10)."""
    from lm27.privacy.sanitize import make_record_context, sanitize_record
    from lm27.store import SegmentWriter
    from lm27.store.cursor import load_raw_cursor, save_raw_cursor
    return {"make_record_context": make_record_context, "sanitize_record": sanitize_record,
            "SegmentWriter": SegmentWriter, "load_raw_cursor": load_raw_cursor, "save_raw_cursor": save_raw_cursor}


def _cfg(cfg, key, default):
    try:
        v = cfg[key]
    except KeyError:
        return default
    return default if v is None else v


def collect(paths, cfg, pc_id, *, d0=None, d1=None, scan=(), now=None, api=None) -> dict:
    """한 번의 수집 → 상태 dict(``rc``·``reasons``·건수). 정제·저장은 ``api``(기본 store_api())."""
    t0 = time.monotonic()
    deadline = t0 + STAGE_BUDGET_S
    now_utc = now or datetime.now(UTC)
    st = {"schema": "lm27.collector_status/1", "src": SRC, "rc": 3, "reasons": [], "partial": False, "cap_hit": False,
          "budget_hit": False, "n": 0}
    lookback = int(_cfg(cfg, "collect.lookbackDays", 120) or 120)
    today = _local_date(now_utc)
    day1 = d1 or today
    day0 = d0 or (today - timedelta(days=lookback))
    st["range"] = [day0.isoformat(), day1.isoformat()]
    exe, tried = find_git(_cfg(cfg, "pc.git.exe", ""))
    st["git"] = "found" if exe else "missing"
    st["git_tried"] = tried
    conf = [str(x) for x in (_cfg(cfg, "pc.git.repos", []) or []) if str(x or "").strip()]
    repos = [r for r in conf if os.path.isdir(r)]
    st["repos_missing"] = len(conf) - len(repos)
    pkg_on = bool(_cfg(cfg, "pc.excludePackageDirs", True))
    scan_roots = [str(x) for x in (_cfg(cfg, "pc.git.scanRoots", []) or []) if str(x or "").strip()] + list(scan)
    if scan_roots:
        repos += find_repos(scan_roots, pkg_on=pkg_on, deadline=deadline)
    if not repos and not conf and not scan_roots:
        roots = [str(x) for x in (_cfg(cfg, "pc.watchFolders", []) or []) if str(x or "").strip()]
        if bool(_cfg(cfg, "pc.autoDiscoverFolders", True)):
            roots.append(os.path.expanduser("~"))
        repos += find_repos(roots, max_depth=FALLBACK_DEPTH, pkg_on=pkg_on, deadline=deadline)
    repos = _dedupe(repos)
    st["repos"] = len(repos)
    if not repos:                                          # 저장소가 없으면 대상 없음(git 유무와 무관 — 이전 판 순서)
        st["rc"] = 1
        return st
    if not exe:                                            # 저장소는 있는데 git 이 없다 → 0건 성공이 아니라 불완전
        st["rc"], st["reasons"] = 3, ["R-NOGIT"]
        return st
    api = api or store_api()
    cur = (api["load_raw_cursor"](paths, pc_id) or {}).get(SRC) or {}
    cur_utc = _parse_utc(cur.get("last_ts_utc")) if isinstance(cur, dict) else None
    since_day = day0 - timedelta(days=SINCE_PAD_DAYS)
    revisit = (cur_utc - timedelta(days=REVISIT_DAYS)) if cur_utc else None
    observed = _utc_iso(now_utc)
    raws, failed, others, id_fallback, seen = [], 0, 0, 0, set()
    n_new = n_range = 0
    budget = False
    for repo in repos:
        if time.monotonic() > deadline:
            budget = True
            break
        ids = identities(exe, repo)
        if not ids:
            u = (os.environ.get("USERNAME") or "").strip()
            if u:
                ids, id_fallback = {u}, id_fallback + 1
        commits, n_other, rc = log_commits(exe, repo, since_day, ids,
                                           timeout_s=max(1, min(REPO_TIMEOUT_S, int(deadline - time.monotonic()) or 1)))
        if rc != 0:
            failed += 1
            continue
        others += n_other
        for c in commits:
            if c["sha"] in seen:
                continue
            ld = _local_date(c["at"])
            if not (day0 <= ld <= day1):
                continue
            seen.add(c["sha"])
            n_range += 1
            if cur_utc is not None and c["at"] <= cur_utc:
                if revisit is None or c["at"] <= revisit:
                    continue
            else:
                n_new += 1
            raws.append(raw_record(repo, c, observed))
    st.update(repos_failed=failed, others_excluded=others, identity_fallback=id_fallback, in_range=n_range)
    if failed and failed == len(repos):
        st["rc"], st["reasons"] = 3, ["R-NOGIT"]
        return st
    raws.sort(key=lambda r: (r["ts_utc"], r["commit_sha"]))
    rc_ctx = api["make_record_context"](paths.root, SRC, pc_id)
    stored, dropped, errors = [], {}, {}
    for raw in raws:
        out = api["sanitize_record"](KIND, raw, rc_ctx)
        if out.status == "stored":
            stored.append(out.row)
        elif out.status == "dropped":
            dropped[out.reason or "other"] = dropped.get(out.reason or "other", 0) + 1
        else:
            errors[out.reason or "error"] = errors.get(out.reason or "error", 0) + 1
    raws = None                                            # 원문 참조 해제(메모리에서만)
    st.update(rows_in=len(stored) + sum(dropped.values()) + sum(errors.values()), stored=len(stored),
              dropped=dropped, errors=errors)
    try:
        w = api["SegmentWriter"](paths, pc_id, KIND, SRC)
        try:
            for row in stored:
                w.append(row)
            w.flush()
        finally:
            w.close()
    except Exception as e:  # noqa: BLE001 — 저장 실패는 rc 3 + 수송 사유로 알리고 커서를 진전하지 않는다
        st["rc"], st["reasons"] = 3, ["R-TRANSPORT"]
        st["error"] = type(e).__name__
        return st
    audit = getattr(rc_ctx, "audit", None)
    if audit is not None:
        audit.flush(rows_in=st["rows_in"], rows_out=len(stored), dur_ms=int((time.monotonic() - t0) * 1000))
    new_cur = dict(cur) if isinstance(cur, dict) else {}
    repos_cur = dict(new_cur.get("repos") or {}) if isinstance(new_cur.get("repos"), dict) else {}
    last = cur_utc
    for row in stored:
        data = row.data
        ts = _parse_utc(data.get("ts_utc"))
        if ts is not None and (last is None or ts > last):
            last = ts
        dk, ck = data.get("doc_key"), data.get("commit_key")
        if dk and ck:
            repos_cur[dk] = ck
    new_cur = {"last_ts_utc": _utc_iso(last) if last else None, "repos": dict(sorted(repos_cur.items()))}
    api["save_raw_cursor"](paths, pc_id, SRC, new_cur)
    st["cursor_saved"] = True
    if budget:
        st["partial"], st["budget_hit"] = True, True
        st["reasons"] = ["R-BUDGET"]
    st["n"] = n_new
    st["rc"] = 0 if n_new > 0 else (4 if n_range > 0 else 1)
    return st


# ───────────────────────────── 진입점 ─────────────────────────────
def _status_line(st) -> None:
    sys.stderr.write(json.dumps({"_status": st}, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
    sys.stderr.flush()


def _parse_day(s):
    if s is None or s == "":
        return None
    if not DATE_RX.match(s):
        raise ValueError("날짜 형식")
    return date.fromisoformat(s)


def main(argv=None, *, paths=None, cfg=None, now=None, api=None) -> int:
    ap = argparse.ArgumentParser(prog="Get-GitActivity.py", add_help=True)
    ap.add_argument("--pc", default="")
    ap.add_argument("--from", dest="d0", default="")
    ap.add_argument("--to", dest="d1", default="")
    ap.add_argument("--scan", action="append", default=[])
    try:
        a = ap.parse_args(argv)
        d0, d1 = _parse_day(a.d0), _parse_day(a.d1)
    except (SystemExit, ValueError) as e:
        if isinstance(e, SystemExit) and e.code in (0, None):
            return 0          # --help: 사용법만 내고 끝(수집이 아니므로 상태 줄 없음 — Import-MailCal.py 와 같게, W1a 통합)
        _status_line({"schema": "lm27.collector_status/1", "src": SRC, "rc": 3, "reasons": ["R-TRANSPORT"],
                      "error": "BadArguments"})
        return 3
    t0 = time.monotonic()
    if not PC_ID_RX.match(a.pc or ""):
        _status_line({"schema": "lm27.collector_status/1", "src": SRC, "rc": 3, "reasons": ["R-TRANSPORT"],
                      "error": "BadPcId"})
        return 3
    try:
        if paths is None:
            from lm27.paths import Paths
            paths = Paths(ROOT)
        if cfg is None:
            from lm27.config import load_config
            cfg = load_config(paths)
        st = collect(paths, cfg, a.pc, d0=d0, d1=d1, scan=tuple(a.scan), now=now, api=api)
    except Exception as e:  # noqa: BLE001 — 수집기 내부 오류는 rc 3 + 수송 사유(예외 유형만, 원문·메시지 없음)
        st = {"schema": "lm27.collector_status/1", "src": SRC, "rc": 3, "reasons": ["R-TRANSPORT"],
              "error": type(e).__name__}
    st["elapsed_ms"] = int((time.monotonic() - t0) * 1000)
    _status_line(st)
    return int(st.get("rc", 3))


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        _r = getattr(_s, "reconfigure", None)
        if _r is not None:
            _r(encoding="utf-8", errors="replace")
    sys.exit(main())
