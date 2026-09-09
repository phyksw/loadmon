# -*- coding: utf-8 -*-
"""자가점검 — 이 폴더에 필수 파일이 다 있는지 확인. python 자가점검.py"""
import io
import json
import os
import sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, errors="replace", encoding=(
        (sys.stdout.encoding or "utf-8") if sys.stdout.isatty() else "utf-8"))  # 콘솔(bat)=콘솔 코드페이지 · 파이프(UI)=utf-8
ROOT = os.path.dirname(os.path.abspath(__file__))
NEED = [
    "LoadMonitor23-UI.bat",
    "LoadMonitor23.bat",
    "LoadMonitor23-팀취합.bat",
    "LoadMonitor23-팀서버.bat",
    "LoadMonitor23-팀업로드.bat",
    "LoadMonitor23-수집진단.bat",
    "LoadMonitor23-샘플러등록.bat",
    "LoadMonitor23-이동준비.bat",
    "agentic.py",
    "freeze.py",
    "team_report.py",
    "flow.py",
    "teamserver.py",
    "teamup.py",
    "aggregate.py",
    "export.py",
    "retag.py",
    "team_refine.py",
    "report_out.py",
    "README.md",
    "check.py",
    "judge.py",
    "mine.py",
    "refine.py",
    "ruff.toml",
    "FILES.txt",
    "run.py",
    "자가점검.py",
    "collect/Add-WorkLog.ps1",
    "collect/Get-FileActivity.ps1",
    "collect/Get-GitActivity.py",
    "collect/Get-LicenseUsage.ps1",
    "collect/Get-OutlookData.ps1",
    "collect/Get-OutlookIndex.ps1",
    "collect/Get-MailViaCopilot.py",
    "collect/Get-OutlookWeb.py",
    "collect/Get-PcOnHistory.ps1",
    "collect/Get-PcOnHints.py",
    "collect/Start-TeamsSampler.ps1",
    "collect/Get-RecentFiles.ps1",
    "collect/Get-TeamsChats.py",
    "collect/Get-TeamsViaCopilot.py",
    "collect/Get-TeamsWeb.py",
    "collect/Get-TeamsWindow.ps1",
    "collect/Diagnose-Collectors.ps1",
    "collect/Register-Samplers.ps1",
    "collect/Start-ActivitySampler.ps1",
    "config/config.json",
    "config/config.default.json",
    "config/agentic_tasks.json",
    "core/board.py",
    "core/extract.py",
    "core/programs.py",
    "core/details.py",
    "core/owner.py",
    "core/progress.py",
    "core/projmap.py",
    "docs/설정가이드.md",
    "docs/사용안내.html",
    "tools/copilot_auto.py",
    "tools/Get-EmbeddedPython.ps1",
    "tools/check_page_js.py",
    "tools/lint.ps1",
    "tools/Make-Package.ps1",
    "tools/Prepare-Move.ps1",
    "tools/update_files.py",
    "ui/app.py",
]
miss = [p for p in NEED if not os.path.exists(os.path.join(ROOT, p.replace("/", os.sep)))]
print(f"[점검] 필수 {len(NEED)}개 중 {len(NEED)-len(miss)}개 존재")
if miss:
    print(f"[!] 누락 {len(miss)}개 — 원본 PC에서 아래 파일을 복사하세요:")
    for m in miss:
        print("    " + m)
    sys.exit(1)
print("[OK] 전부 있습니다. LoadMonitor23-UI.bat 을 실행하세요.")


# ── git 실행 파일 ────────────────────────────────────────────────────────
# git 이 PATH 에 없으면 예전 수집기는 조용히 '커밋 0건'(rc 0) 을 냈다(2차 감사 실측 — GitHub Desktop·
# SourceTree 내장 git 사용자는 커밋 신호 전량 소실). 수집기의 탐색 규칙(_find_git)을 그대로 빌려 미리 말한다.
def _git_exe(cfg):
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "lm_git_collector", os.path.join(ROOT, "collect", "Get-GitActivity.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        fn = getattr(mod, "_find_git", None) or getattr(mod, "find_git", None)
        if fn:
            r = fn(cfg)                        # (경로 또는 None, 찾아본 곳 목록) — config.gitExe 최우선
            if isinstance(r, (tuple, list)):
                r = r[0] if r else ""
            return str(r or "")
    except Exception:          # 수집기가 바뀌어도 자가점검은 죽지 않는다 — PATH 만 본다
        pass
    import shutil
    return shutil.which("git") or ""


try:
    _cfg = json.load(open(os.path.join(ROOT, "config", "config.json"), encoding="utf-8-sig"))
except (OSError, ValueError):
    _cfg = {}
_gexe = str(_cfg.get("gitExe") or "").strip()
if _gexe and not os.path.exists(_gexe):
    print(f"[!] config.gitExe='{_gexe}' 경로가 없습니다 — 확인하세요")
_gfound = _git_exe(_cfg)
if _gfound:
    print(f"[git] 실행 파일: {_gfound}")
else:
    print("[!] git 실행 파일을 찾지 못했습니다 — PATH·Git for Windows·GitHub Desktop·SourceTree·VS 내장 git 어디에도 없음.")
    print("    gitRepos 를 쓰면 커밋 신호가 수집되지 않습니다(수집 단계가 실패로 기록되고 data\\git_source.json 에 사유가 남습니다).")
    print("    config\\config.json 의 gitExe 에 git.exe 전체 경로를 적으세요. (git 을 쓰지 않으면 무시해도 됩니다)")

# ── 배포 위생 ────────────────────────────────────────────────────────────
# 남의 설정(owner)을 그대로 쓰면 팀 서버의 그 사람 기록을 내 결과로 덮어쓴다(검증 지적).
# data\ report\ 가 비어 있어도 owner 는 남는다 — 폴더째 복사한 뒤 data\ report\ 만 지운 배포본이
# 그 경우라, 잔존 파일 유무와 무관하게 항상 본다(예전엔 잔존 파일이 있을 때만 검사해 조용히 지나갔다).
def _my_names():
    """이 PC 의 계정명과 표시 이름(AD 의 '홍길동' 같은 이름) — owner 는 대개 표시 이름으로 적는다."""
    names = {os.environ.get("USERNAME", "")}
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(256)
        n = ctypes.c_ulong(256)
        if ctypes.windll.secur32.GetUserNameExW(3, buf, ctypes.byref(n)):   # 3 = NameDisplay
            names.add(buf.value)
    except (AttributeError, OSError):
        pass
    return {x.replace(" ", "").lower() for x in names if x and x.strip()}


_own = str(_cfg.get("owner") or "").strip()
_mine = _my_names()
if _own and _mine and _own.replace(" ", "").lower() not in _mine:
    print()
    print(f"[!] config.owner 가 '{_own}' 입니다 — 본인 이름이 맞습니까? (이 PC 계정: {os.environ.get('USERNAME', '')})")
    print("    남이 만든 배포본이면 그대로 두지 마세요. 팀 서버에서 그 사람 기록을 덮어씁니다.")
    print("    (대시보드 [팀 취합 업로드] 카드나 config\\config.json 의 owner 를 고치세요)")

# 배포본에 남의 data\ report\ 가 딸려 오면, 받은 사람 화면에 **남의 분석 결과**가
# 자기 결과처럼 뜬다(실측: 배포 zip 에 report 17개 + Edge 자격증명 30개가 들어갔고
# 대시보드에 시험용 과제명 'coding'/'모듈 개발' 이 표시됐다).
leak = []
for d in ("report", "data", "teamdata"):
    p = os.path.join(ROOT, d)
    if os.path.isdir(p):
        n = sum(len(fs) for _r, _ds, fs in os.walk(p))
        if n:
            leak.append((d, n))
if leak:
    print()
    print("[!] 배포 위생 경고 — 남에게 줄 때는 이 폴더를 빼세요 (FILES.txt 참고):")
    for d, n in leak:
        extra = ""
        if d == "teamdata":
            extra = "  <- 팀원들의 분석 결과 포함, 팀 밖 공유 금지"
        if d == "data" and os.path.isdir(os.path.join(ROOT, d, "copilot_profile")):
            extra = "  <- Edge 로그인 정보 포함, 절대 공유 금지"
        print(f"    {d}\\  파일 {n:,}개{extra}")
    print("    (본인 PC 에서 쓰는 건 정상입니다. 배포본에만 없으면 됩니다.)")

# 개발 캐시(.ruff_cache\ __pycache__\)는 FILES.txt 에 없어 Make-Package zip 에는 안 들어가지만,
# 폴더를 통째로 복사·압축하는 경로(사용안내 §2 Ctrl+C/V)에는 그대로 따라간다(실측: .ruff_cache 6개).
caches = []
for r, ds, _fs in os.walk(ROOT):
    ds[:] = [d for d in ds if d not in ("python", "data", "report", "teamdata")]
    for d in list(ds):
        if d in (".ruff_cache", "__pycache__"):
            n = sum(len(f) for _r, _d, f in os.walk(os.path.join(r, d)))
            caches.append((os.path.relpath(os.path.join(r, d), ROOT), n))
            ds.remove(d)
if caches:
    print()
    print("[!] 캐시 폴더가 있습니다 — 남에게 주거나 폴더째 복사하기 전에 지우세요 (동작에는 영향 없음):")
    for d, n in caches:
        print(f"    {d}\\  파일 {n:,}개")
    print("    (__pycache__ 는 파이썬이 실행 때 만드는 것이라 지워도 다시 생깁니다 — 본인 PC 에서는 그대로 둬도 됩니다.")
    print(r"     .ruff_cache 는 옛 lint 실행의 잔재 — 지금은 tools\lint.ps1 --no-cache, ruff.toml cache-dir=%TEMP% 라 다시 생기지 않습니다.)")
