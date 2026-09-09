# -*- coding: utf-8 -*-
"""
Get-GitActivity.py — 로컬 git 저장소의 내 커밋 이력을 수집 (SW 개발 시간 회수용).

설계·SW 개발은 파일 mtime 한 점만 남아 로드율에 거의 안 잡힌다.
커밋은 '무엇을 얼마나 바꿨는지'가 남는 유일한 소급 가능 개발 신호다.

사용:
  python collect\\Get-GitActivity.py --from 2026-05-19 --to 2026-08-17
  python collect\\Get-GitActivity.py --scan D:\\src        # 저장소 자동 탐색 후 config에 기록

출력: data\\files\\git_commits.csv
      time,repo,subject,files,insertions,deletions,branch
      data\\git_source.json   {status: ok|no_git|all_failed|no_repos, git_exe, tried, repos, failed, commits,
                              missing[] (config.gitRepos 중 없는 경로 — 오타·이동·자리표시자), identities, others_excluded}
      data\\files_excluded.json 의 "git" 절 (개인정보 키워드로 뺀 저장소 집계)

git 실행 파일: config.gitExe → PATH → Git for Windows·GitHub Desktop·SourceTree·Visual Studio 내장 git 순.
  하나도 없으면 '커밋 0건' 으로 조용히 성공하지 않고 rc 1 + 메시지 (예전엔 rc 0 이라 GUI git 사용자의
  개발 신호가 통째로 빠져도 알 수 없었다).
브랜치: HEAD 만이 아니라 모든 로컬·원격 추적 브랜치(--branches --remotes)를 훑고 같은 해시는 1건.
시각: 작성일(%ad)을 이 PC 로컬 시각으로(format-local) — UTC 환경(WSL·CI)의 커밋이 9시간 어긋나지 않는다.
      git 에는 --since=(from−60일) 만 주고 기간 필터는 파이썬이 작성일로 다시 건다(rebase·amend 로
      커밋일이 창 밖으로 밀린 커밋 회수).
작성자: git config user.name / user.email(저장소별·전역)과 정확히 일치하는 커밋만 — --author 는 앵커링한 정규식
      ('^이름 <' · '<메일>$', 대소문자 무시)으로 미리 거르고 파이썬이 %an/%ae 로 다시 확인한다. 예전엔 Windows
      계정명(USERNAME)까지 --author 부분일치로 넣어 'User'→'Userman', 'kim'→'kimchulsoo@…' 처럼 동료 커밋이
      내 것으로 집계됐다(C2). 계정명은 git 신원이 하나도 없을 때만 보조로 쓴다.
"""
import argparse
import glob
import io
import json
import os
import re
import shutil
import subprocess
import sys
from collections import Counter
from datetime import date, datetime, timedelta

if __name__ == "__main__":      # import 시엔 건드리지 않는다 — 임포트한 쪽의 stdout 이
    # 교체·GC 되면서 버퍼가 닫혀 이후 출력이 전부 죽는다(run.py 와 같은 관례)
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, errors="replace", encoding=(
        (sys.stdout.encoding or "utf-8") if sys.stdout.isatty() else "utf-8"))  # 콘솔(bat)=콘솔 코드페이지 · 파이프(UI)=utf-8
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFG = os.path.join(ROOT, "config", "config.json")
DATA = os.path.join(ROOT, "data")
OUT = os.path.join(DATA, "files")
NO_WIN = 0x08000000
RC_NOT_FOUND = 127      # git 실행 파일 없음 (셸 관례)
RC_TIMEOUT = 124        # 시간 초과 (coreutils timeout 관례)

# 경로에만 나타나는 제외 키워드 — 폴더명 완전 일치로만 건다(core/extract.PATH_ONLY_KW 와 같은 목록).
# 'temp' 부분일치가 Temperature_Test·template·temp_sensor 저장소를 조용히 지우던 실측 경로 차단.
PATH_ONLY_KW = {"temp", "downloads", "다운로드", "임시"}
# 패키지·빌드 폴더 — 세 수집기(파일·Recent·git)가 같은 목록을 쓴다. config.excludePackageDirs=false 로 끈다
PKG_DIRS = {".venv", "venv", "env", ".env", "node_modules", "site-packages", "__pycache__", ".git",
            ".tox", ".nox", ".mypy_cache", ".pytest_cache", "build", "dist", "target", ".idea", ".vs",
            ".vscode", "packages", ".conda", "conda-meta", "x64", "debug", "release"}
# 이름이 업무 폴더와 겹치는 여덟 이름(S3-P5) — .git 탐색에서 이름만으로 건너뛰지 않고 빌드 표식이 있을 때만
# (파일 수집기 Test-BuildDir 와 같은 규칙). Release\ 아래에 둔 저장소(예: D:\src\proj\Release\fw)를 --scan 이 찾지 못하던 것 방지.
# 깊이 제한(max_depth)이 있어 비용은 작다. gitRepos 를 손으로 적은 사용자에겐 영향 없음.
PKG_MAYBE = {"release", "target", "debug", "x64", "build", "dist", "env", "packages"}
MARK_IN = {"cmakecache.txt", "cachedir.tag", "pyvenv.cfg", "build.ninja", ".ninja_log", "compile_commands.json",
           "objects.list", "repositories.config", "makefile", "cmakefiles", "maven-status", "conda-meta",
           "site-packages", "node_modules"}
MARK_IN_SFX = (".pdb", ".obj", ".ilk", ".idb", ".o", ".d", ".su", ".pch", ".whl", ".nupkg", ".jar", ".class", ".tlog",
               ".recipe", ".pyc", ".exp")
MARK_UP = {"cmakelists.txt", "package.json", "setup.py", "pyproject.toml", "setup.cfg", "cargo.toml", "pom.xml",
           "build.gradle", "build.gradle.kts", "tsconfig.json", ".cproject", ".git", "meson.build", "sconstruct"}
MARK_UP_SFX = (".sln", ".vcxproj", ".csproj", ".vbproj", ".fsproj", ".uvprojx", ".uvproj", ".ewp", ".ioc", ".pro", ".cbp")
_MARK_CACHE = {}

GIT_EXE = None          # main() 또는 첫 git() 호출 때 _find_git 으로 채운다
_GIT_TRIED = None


def load_cfg():
    # 다른 모듈과 같은 utf-8-sig — 메모장이 남긴 BOM 하나로 이 수집기만 죽던 것(검증 확정)
    with open(CFG, encoding="utf-8-sig") as f:
        return json.load(f)


def _find_git(cfg=None):
    """git 실행 파일 → (경로 또는 None, 찾아본 곳 목록).
    config.gitExe 가 최우선(파일 또는 설치 폴더), 다음 PATH, 다음 GUI 클라이언트가 내장한 git."""
    tried = []
    exe = str((cfg or {}).get("gitExe") or "").strip().strip('"')
    if exe:
        cands = [exe, os.path.join(exe, "cmd", "git.exe"), os.path.join(exe, "bin", "git.exe"),
                 os.path.join(exe, "git.exe")]
        for c in cands:
            tried.append(c)
            if os.path.isfile(c):
                return c, tried
        print(f"[git] config.gitExe 경로에 git.exe 가 없습니다: {exe} — PATH·기본 설치 위치를 찾아봅니다")
    p = shutil.which("git")
    tried.append("PATH")
    if p:
        return p, tried
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    lad = os.environ.get("LOCALAPPDATA", "")
    vs_tail = ("Common7", "IDE", "CommonExtensions", "Microsoft", "TeamFoundation", "Team Explorer",
               "Git", "cmd", "git.exe")
    pats = [os.path.join(pf, "Git", "cmd", "git.exe"),
            os.path.join(pf86, "Git", "cmd", "git.exe"),
            os.path.join(pf, "Microsoft Visual Studio", "*", "*", *vs_tail),
            os.path.join(pf86, "Microsoft Visual Studio", "*", "*", *vs_tail)]
    if lad:                                 # 사용자 설치·GUI 클라이언트 내장 git
        pats += [os.path.join(lad, "Programs", "Git", "cmd", "git.exe"),
                 os.path.join(lad, "GitHubDesktop", "app-*", "resources", "app", "git", "cmd", "git.exe"),
                 os.path.join(lad, "Atlassian", "SourceTree", "git_local", "cmd", "git.exe")]
    for pat in pats:
        tried.append(pat)
        for c in sorted(glob.glob(pat), reverse=True):     # app-3.4.x 처럼 여러 판이면 최신 우선
            if os.path.isfile(c):
                return c, tried
    return None, tried


def _git_exe():
    """지연 초기화 — 다른 스크립트가 import 해서 collect()/my_identities() 만 불러도 동작한다."""
    global GIT_EXE, _GIT_TRIED
    if _GIT_TRIED is None:
        cfg = {}
        try:
            cfg = load_cfg()
        except (OSError, ValueError):
            pass
        GIT_EXE, _GIT_TRIED = _find_git(cfg)
    return GIT_EXE


def excl_keywords(cfg):
    return [str(k).strip().lower() for k in (cfg.get("excludePathKeywords") or [])
            if str(k).strip()]


def make_excl(excl):
    """excludePathKeywords 판정기 path → 걸린 키워드 또는 ''. 세 수집기·core/extract._text_filter 와 같은 규칙:
     · 경로 전용 토큰(temp·downloads·임시·다운로드)은 폴더명 완전 일치
     · ASCII 키워드는 단어 경계 ('temp'⊄'template'·'temperature', 'resume'⊄'presume')
     · 한글은 부분일치 유지('개인'⊂'개인자료' — 마지막 방어선)"""
    kws = [str(k).strip().lower() for k in (excl or []) if str(k).strip()]
    seg = {k for k in kws if k in PATH_ONLY_KW}
    kr = [k for k in kws if not k.isascii() and k not in PATH_ONLY_KW]
    asc = [k for k in kws if k.isascii() and k not in PATH_ONLY_KW]
    pat = re.compile("|".join(f"(?<![a-z0-9]){re.escape(k)}(?![a-z0-9])" for k in asc)) if asc else None

    def hit(path):
        low = str(path or "").lower()
        parts = [x for x in re.split(r"[\\/]+", low) if x]
        h = next((k for k in seg if k in parts), "")
        if not h:
            h = next((k for k in kr if k in low), "")
        if not h and pat:
            m = pat.search(low)
            h = m.group(0) if m else ""
        return h
    return hit


def filter_repos(repos, excl):
    r"""개인 폴더 저장소를 걸러 낸다 — 커밋 메시지는 팀 서버·Copilot 프롬프트로 나가므로
    파일·Recent 수집기(Get-FileActivity.ps1 / Get-RecentFiles.ps1)와 같은 기준을 여기서도 건다.
    무엇이 어떤 키워드로 빠졌는지 반드시 말한다(조용한 삭제 금지). → (keep, dropped[(repo, kw)])
    excl: 키워드 목록 또는 make_excl() 판정기."""
    hit = excl if callable(excl) else make_excl(excl)
    keep, dropped = [], []
    seen = set()
    for r in repos:
        key = os.path.normcase(os.path.abspath(r))
        if key in seen:
            continue
        seen.add(key)
        k = hit(r)
        if k:
            dropped.append((r, k))
        else:
            keep.append(r)
    for r, k in dropped[:5]:
        print(f"[git] 제외: {os.path.basename(r.rstrip(chr(92) + '/'))} (개인정보 키워드 '{k}')")
    if dropped:
        print(f"[git] 개인 폴더 저장소 {len(dropped)}개를 수집에서 제외했습니다")
    return keep, dropped


def git(repo, args, timeout=60):
    """→ (stdout, rc, stderr). 실행 파일 없음은 rc 127, 시간 초과는 rc 124 — 다른 실패(128 등)와 구분해 집계한다.
    메시지 언어를 C 로 고정한다: 한국어 git 은 --shortstat 을 'N개 파일 변경' 으로 찍어 정규식이 0 을 읽는다."""
    exe = _git_exe()
    if not exe:
        return "", RC_NOT_FOUND, "git 실행 파일 없음"
    env = dict(os.environ, LC_ALL="C", LANG="C", GIT_TERMINAL_PROMPT="0", GIT_OPTIONAL_LOCKS="0")
    try:
        r = subprocess.run([exe, "-C", repo] + args, capture_output=True,
                           timeout=timeout, creationflags=NO_WIN, env=env)
        return (r.stdout.decode("utf-8", "replace"), r.returncode,
                r.stderr.decode("utf-8", "replace"))
    except OSError as ex:
        return "", RC_NOT_FOUND, str(ex)
    except subprocess.TimeoutExpired:
        return "", RC_TIMEOUT, f"시간 초과 {timeout}s"


def _has_marks(d, exact, sfx):
    """폴더 안(최대 5,000 항목)에 표식 이름·접미가 있는가 — 폴더당 1회만 본다(캐시)"""
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
        pass
    _MARK_CACHE[k] = r
    return r


def _is_build_dir(path, parent):
    """build·release 류 폴더가 진짜 빌드 폴더인가 — 그 폴더의 표식(CMakeCache.txt·pyvenv.cfg·*.obj/*.pdb/*.o …) 또는
    바로 위 폴더의 프로젝트 표식(CMakeLists.txt·package.json·*.sln·*.vcxproj …). 파일 수집기 Test-BuildDir 와 같은 규칙."""
    return _has_marks(path, MARK_IN, MARK_IN_SFX) or _has_marks(parent, MARK_UP, MARK_UP_SFX)


def _is_pkg_dir(name):
    """이름만으로 확정되는 패키지 폴더 — 여덟 이름(PKG_MAYBE)은 여기서 확정하지 않는다"""
    n = name.lower()
    return (n in PKG_DIRS and n not in PKG_MAYBE) or n.startswith("cmake-build-")


def _skip_dir(dirpath, name):
    """find_repos 가 내려가지 않을 폴더 — 이름만으로 확정되는 패키지 폴더, 또는 여덟 이름 중 빌드 표식이 있는 것(S3-P5)"""
    if _is_pkg_dir(name):
        return True
    return name.lower() in PKG_MAYBE and _is_build_dir(os.path.join(dirpath, name), dirpath)


def find_repos(roots, max_depth=4, limit=40, pkg_on=True):
    """.git 폴더를 가진 디렉터리 탐색 (깊이 제한 — 회사 PC의 큰 드라이브 대비).
    패키지·빌드 폴더(PKG_DIRS)는 내려가지 않는다 — 파일 수집기와 같은 목록. 단 release·target·debug·x64·build·dist·
    env·packages 는 그 폴더(또는 바로 위)에 빌드 표식이 있을 때만 건너뛴다(S3-P5 — 업무 폴더 이름과 겹친다)."""
    found = []
    for root in roots:
        if not os.path.isdir(root):
            continue
        base_depth = root.rstrip("\\/").count(os.sep)
        for dirpath, dirnames, _ in os.walk(root):
            if dirpath.count(os.sep) - base_depth > max_depth:
                dirnames[:] = []
                continue
            if pkg_on:
                dirnames[:] = [d for d in dirnames if not _skip_dir(dirpath, d)]
            else:
                dirnames[:] = [d for d in dirnames
                               if d not in ("node_modules", "venv", ".venv", "__pycache__", "build")]
            if os.path.isdir(os.path.join(dirpath, ".git")):
                found.append(dirpath)
                dirnames[:] = []            # 중첩 저장소는 건너뜀
                if len(found) >= limit:
                    return found
    return found


def my_identities(repos):
    """'나' 의 git 신원 집합 — 저장소별(·전역) git config user.name / user.email.
    Windows 계정명(USERNAME)은 git 신원이 하나도 없을 때만 보조로 쓴다 — 'User'·'kim' 같은 짧은 계정명이
    --author 부분일치로 동료('Userman'·'kimchulsoo@…')의 커밋을 내 것으로 세던 결함(C2).
    대조는 collect() 가 정규화(공백 정리·소문자) 정확 일치로 한다."""
    ids = set()
    for r in repos[:20]:
        for key in ("user.name", "user.email"):
            out, rc, _ = git(r, ["config", "--get", key])
            if rc == 0 and out.strip():
                ids.add(out.strip())
    if not ids:
        u = (os.environ.get("USERNAME") or "").strip()
        if u:
            ids.add(u)
            print(f"[git] git config user.name/email 이 없어 Windows 계정명 '{u}' 과 정확히 일치하는 작성자만 셉니다")
    return ids


def _norm_id(s):
    """작성자 이름·메일 정규화 — 공백 정리·소문자 (정확 일치 대조용)"""
    return re.sub(r"\s+", " ", str(s or "").strip()).lower()


_BRE_SPECIAL = set(".[]*^$\\")


def _bre_escape(s):
    """git --author 의 기본 정규식(BRE)용 이스케이프 — --basic-regexp 를 같이 주므로 ( ) + ? | { 는 글자다"""
    return "".join(("\\" + c) if c in _BRE_SPECIAL else c for c in s)


def author_patterns(authors):
    """--author 용 앵커링 정규식 — git 은 'Name <email>' 에 대조하므로 이름은 '^이름 <', 메일은 '<메일>$'.
    부분일치를 막는 1차 관문(성능용)이고 최종 판정은 collect() 의 정확 일치. 여러 --author 는 OR."""
    pats = []
    for a in sorted(str(x or "").strip() for x in authors):
        if not a:
            continue
        pats.append("^" + _bre_escape(a) + " <")
        if "@" in a:
            pats.append("<" + _bre_escape(a) + ">$")
    return list(dict.fromkeys(pats))[:12]


def split_missing(paths):
    """config.gitRepos → (있는 폴더, 없는 경로). 없는 경로(오타·이동·삭제·자리표시자)는 main 이 알리고
    git_source.json 의 missing[] 에 남긴다 — 예전엔 아무 말 없이 버려 사용자가 알 길이 없었다(C6)."""
    ok, missing = [], []
    for r in paths or []:
        s = str(r or "").strip()
        if s:
            (ok if os.path.isdir(s) else missing).append(s)
    return ok, missing


def _branch(ref):
    """%S(--source) 값 → 브랜치 이름. git 판에 따라 'feature' · 'refs/heads/feature' · 'origin/main' ·
    'refs/remotes/origin/main' 으로 온다. 원격 추적 브랜치는 'origin/main' 처럼 남긴다(다른 PC 에서 푸시한
    커밋이라는 표시). %S 미지원 옛 git 은 '%S' 를 그대로 찍으므로 빈 값으로."""
    ref = (ref or "").strip()
    if not ref or ref.startswith("%"):
        return ""
    if ref.startswith("refs/heads/"):
        ref = ref[len("refs/heads/"):]
    elif ref.startswith("refs/remotes/"):
        ref = ref[len("refs/remotes/"):]
    elif ref.startswith("refs/"):
        ref = ref.split("/", 2)[-1]
    return ref[:24]


def _parse_time(s):
    try:
        return datetime.strptime((s or "").strip()[:16], "%Y-%m-%d %H:%M")
    except ValueError:
        return None


def collect(repos, d0, d1, authors, stats=None):
    """저장소별 git log → (rows, failed[(repo, rc, 메시지)]). 실패 저장소는 조용히 건너뛰지 않고 집계한다.
    authors: my_identities() — git 에는 앵커링 정규식으로 미리 거르고, 여기서 %an/%ae 정규화 정확 일치로 다시 확인한다.
    stats(dict) 에 others_excluded(1차 관문은 지났지만 정확 일치가 아닌 커밋 수)를 더한다."""
    lo, hi = date.fromisoformat(d0), date.fromisoformat(d1)
    since = (lo - timedelta(days=60)).isoformat()      # 기간 필터는 아래서 작성일로 다시 건다
    rows, failed, seen = [], [], set()
    stats = stats if stats is not None else {}
    ids = {_norm_id(a) for a in authors if str(a or "").strip()}
    if not ids:                             # 신원을 모르면 남의 커밋과 구분할 수 없다 — 전부 넣지 않고 세지 않는다
        print("[git] 작성자 신원 없음(git config user.name/email · USERNAME) — 커밋을 세지 않습니다")
        return rows, failed
    pats = author_patterns(authors)
    for repo in repos:
        name = os.path.basename(repo.rstrip("\\/"))
        # --branches --remotes: HEAD 조상만 훑던 결함(피처 브랜치 커밋 누락) 수정. --all 은 refs/stash 잡음.
        # %S(브랜치)를 %s(제목) 앞에 둔다 — 제목에 '|' 가 있어도 split(…, 5) 의 마지막 조각이 제목 전체.
        # --basic-regexp: 사용자의 grep.patternType(extended·perl) 설정과 무관하게 앵커링 패턴이 그대로 통한다.
        args = ["log", "--branches", "--remotes", "--source", "--no-merges", f"--since={since}",
                "--date=format-local:%Y-%m-%d %H:%M", "--pretty=format:@@%H|%ad|%an|%ae|%S|%s", "--shortstat",
                "--basic-regexp", "--regexp-ignore-case"]
        for pat in pats:
            args += [f"--author={pat}"]
        out, rc, err = git(repo, args, timeout=90)
        if rc != 0:
            msg = " ".join(err.strip().split())[:120] or f"rc {rc}"
            failed.append((repo, rc, msg))
            print(f"[git] {name} 실패(rc {rc}): {msg}")
            continue
        cur = None
        n_other = 0
        for ln in out.splitlines():
            if ln.startswith("@@"):
                if cur:
                    rows.append(cur)
                cur = None
                p = ln[2:].split("|", 5)
                if len(p) < 6:
                    continue
                h, ad, an, ae, ref, subj = p
                if _norm_id(an) not in ids and _norm_id(ae) not in ids:
                    n_other += 1            # 1차 관문(정규식)은 지났지만 내 신원과 정확히 일치하지 않는 작성자
                    continue
                t = _parse_time(ad)
                if t is None or not (lo <= t.date() <= hi):
                    continue                # 창 밖(--since 여유분) — 작성일 기준
                if h in seen:               # 같은 커밋이 여러 브랜치에서 도달됨 — 1건
                    continue
                seen.add(h)
                cur = {"time": t.strftime("%Y-%m-%d %H:%M"), "repo": name, "subject": subj[:150],
                       "files": 0, "ins": 0, "dele": 0, "branch": _branch(ref)}
            elif cur and ("changed" in ln or "insertion" in ln or "deletion" in ln):
                m = re.search(r"(\d+) files? changed", ln)
                cur["files"] = int(m.group(1)) if m else 0
                m = re.search(r"(\d+) insertion", ln)
                cur["ins"] = int(m.group(1)) if m else 0
                m = re.search(r"(\d+) deletion", ln)
                cur["dele"] = int(m.group(1)) if m else 0
        if cur:
            rows.append(cur)
        if n_other:
            stats["others_excluded"] = stats.get("others_excluded", 0) + n_other
            print(f"[git] {name}: 작성자가 내 신원과 정확히 일치하지 않는 커밋 {n_other}건 제외")
    rows.sort(key=lambda r: r["time"])
    return rows, failed


def write_csv(rows):
    """git_commits.csv — .tmp 에 쓰고 성공 시 교체(수집기가 중간에 죽어도 지난 파일이 반쪽으로 남지 않는다)."""
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, "git_commits.csv")

    def esc(s):
        s = re.sub(r"[\r\n]+", " ", str(s))
        return '"' + s.replace('"', '""') + '"' if ("," in s or '"' in s) else s

    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
        f.write("time,repo,subject,files,insertions,deletions,branch\n")
        for r in rows:
            f.write(",".join(esc(r[k]) for k in
                             ("time", "repo", "subject", "files", "ins", "dele", "branch")) + "\n")
    os.replace(tmp, path)
    return path


def _write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def write_source(status, **kw):
    """data\\git_source.json — Diagnose-Collectors·자가점검이 'git 을 찾았는지' 를 이 파일로 안다."""
    doc = {"status": status, "git_exe": GIT_EXE or "", "tried": list(_GIT_TRIED or []),
           "updated": datetime.now().strftime("%Y-%m-%d %H:%M")}
    doc.update(kw)
    try:
        _write_json(os.path.join(DATA, "git_source.json"), doc)
    except OSError as ex:
        print(f"[git] git_source.json 기록 실패: {ex}")


def update_excluded_json(section, payload):
    """data\\files_excluded.json — 파일·Recent·git 수집기가 각자 절(section)만 바꿔 쓴다."""
    p = os.path.join(DATA, "files_excluded.json")
    doc = {}
    try:
        with open(p, encoding="utf-8-sig") as f:
            doc = json.load(f)
        if not isinstance(doc, dict):
            doc = {}
    except (OSError, ValueError):
        doc = {}
    doc[section] = payload
    try:
        _write_json(p, doc)
    except OSError as ex:
        print(f"[git] files_excluded.json 기록 실패: {ex}")


def main():
    global GIT_EXE, _GIT_TRIED
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="d0", default="")
    ap.add_argument("--to", dest="d1", default="")
    ap.add_argument("--scan", default="", help="이 경로 아래 git 저장소를 찾아 config에 기록")
    a = ap.parse_args()
    cfg = load_cfg()
    GIT_EXE, _GIT_TRIED = _find_git(cfg)
    pkg_on = cfg.get("excludePackageDirs", True) is not False
    d0 = a.d0 or (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
    d1 = a.d1 or datetime.now().strftime("%Y-%m-%d")
    repos, missing = split_missing(cfg.get("gitRepos") or [])
    if a.scan:
        found = find_repos([a.scan], pkg_on=pkg_on)
        merged = sorted(set(cfg.get("gitRepos", [])) | set(found))
        cfg["gitRepos"] = merged
        with open(CFG, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        print(f"[git] 저장소 {len(found)}개 발견 → config.gitRepos 에 기록")
        repos, missing = split_missing(merged)
    for r in missing:                       # 조용히 버리지 않는다(C6) — git_source.json 의 missing[] 에도 남긴다
        why = "자리표시자 — 실제 경로로 바꾸세요" if re.search(r"[<>]", r) else "config.gitRepos 경로 확인 (이동·삭제·오타)"
        print(f"[git] 설정 저장소 없음: {r}  ({why})")
    hit = make_excl(excl_keywords(cfg))
    repos, dropped = filter_repos(repos, hit)
    if not repos:                       # 설정이 없으면 작업 폴더에서 자동 탐색
        roots = list(cfg.get("watchFolders", []))
        if cfg.get("autoDiscoverFolders", True):
            roots.append(os.path.expanduser("~"))   # 설정으로 끌 수 있어야 한다(다른 수집기와 동일)
        repos, dropped2 = filter_repos(find_repos(roots, max_depth=3, pkg_on=pkg_on), hit)
        dropped += dropped2
        if repos:
            print(f"[git] 자동 탐색으로 {len(repos)}개 발견 (config.gitRepos 에 넣으면 고정됩니다)")
    by_kw = Counter(k for _, k in dropped)
    update_excluded_json("git", {
        "updated": datetime.now().strftime("%Y-%m-%d %H:%M"), "period": [d0, d1],
        "repos_excluded": len(dropped), "by_keyword": dict(by_kw),
        "note": "excludePathKeywords 로 뺀 저장소 수(키워드별). 경로는 남기지 않는다"})
    if not repos:
        print("[git] 저장소 없음 — --scan D:\\src 로 탐색하거나 config.gitRepos 설정")
        write_source("no_repos", repos=0, failed=0, commits=0, missing=missing)
        return 0
    if not GIT_EXE:
        # 예전엔 여기서 '커밋 0건' 으로 rc 0 — GitHub Desktop·SourceTree·VS 내장 git 만 쓰는 PC 의
        # 커밋 신호가 통째로 빠져도 '원래 없는 것' 과 구분할 수 없었다.
        print(f"[git] git 실행 파일 없음 — 커밋 신호 수집 불가 (저장소 {len(repos)}개는 있음)")
        print("      찾아본 곳: " + " · ".join(_GIT_TRIED))
        print('      Git for Windows 를 설치하거나 config.json 에 "gitExe": "C:\\\\...\\\\git.exe" 를 적으세요')
        print("      기존 git_commits.csv 는 덮어쓰지 않았습니다")
        write_source("no_git", repos=len(repos), failed=len(repos), commits=0, missing=missing)
        return 1
    print(f"[git] git: {GIT_EXE}")
    ids = my_identities(repos)
    stats = {}
    rows, failed = collect(repos, d0, d1, ids, stats)
    fails = [{"repo": os.path.basename(r.rstrip("\\/")), "rc": rc, "error": m} for r, rc, m in failed]
    if failed and len(failed) == len(repos):
        rcs = Counter(rc for _, rc, _ in failed)
        why = " · ".join(f"rc {rc}×{n}" for rc, n in sorted(rcs.items()))
        print(f"[git] 모든 저장소({len(repos)}개)에서 git 실행 실패 — 커밋 신호를 수집하지 못했습니다 ({why})")
        if rcs.get(RC_NOT_FOUND):
            print("      git 실행 파일을 열지 못했습니다 — config.gitExe 를 확인하세요")
        if rcs.get(128):
            print("      rc 128 = git 저장소가 아니거나 손상됨(config.gitRepos 경로 확인)")
        print("      기존 git_commits.csv 는 덮어쓰지 않았습니다")
        write_source("all_failed", repos=len(repos), failed=len(failed), commits=0, failures=fails,
                     missing=missing, identities=len(ids))
        return 1
    path = write_csv(rows)
    print(f"[git] 저장소 {len(repos)}개 · 커밋 {len(rows)}건 → {path}"
          + (f" · 실패 {len(failed)}개(위 메시지)" if failed else "")
          + (f" · 설정 저장소 없음 {len(missing)}개(위 메시지)" if missing else ""))
    write_source("ok", repos=len(repos), failed=len(failed), commits=len(rows), failures=fails,
                 missing=missing, identities=len(ids), others_excluded=stats.get("others_excluded", 0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
