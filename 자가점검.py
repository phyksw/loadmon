# -*- coding: utf-8 -*-
"""자가점검 — 이 폴더에 필수 파일이 다 있는지 확인. python 자가점검.py"""
import io
import json
import os
import sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, errors="replace", encoding=(
        (sys.stdout.encoding or "utf-8") if sys.stdout.isatty() else "utf-8"))  # 콘솔(bat)=콘솔 코드페이지 · 파이프(UI)=utf-8
ROOT = os.path.dirname(os.path.abspath(__file__))
# 개발 전용 파일(시험 tests\·lint 관문·FILES.txt 생성·인코딩 정리 도구·현장점검 문서)은 배포(GitHub 내려받기)에 넣지 않으므로
# 여기에도 적지 않는다 — 적으면 받은 PC 의 자가점검이 '누락'으로 멈춘다(.gitignore 의 '개발 전용' 묶음 · 2026-10-17).
NEED = [
    "AgentFinder32-UI.bat",
    "AgentFinder32.bat",
    "AgentFinder32-팀서버.bat",
    "AgentFinder32-팀서버주소.bat",
    "AgentFinder32-수집진단.bat",
    "AgentFinder32-강제종료.bat",
    "agentic.py",
    "flow.py",
    "teamserver.py",
    "teamup.py",
    "team_summary.py",
    "retag.py",
    "report_out.py",
    "README.md",
    "judge.py",
    "mine.py",
    "refine.py",
    "FILES.txt",
    "run.py",
    "자가점검.py",
    "collect/Get-OutlookData.ps1",
    "collect/Get-MailViaCopilot.py",
    "collect/Get-OutlookWeb.py",
    "collect/Diagnose-Collectors.ps1",
    "collect/LmName.ps1",
    # 빠지면 배포본이 시작부터 죽는다(run.py·수집기·app.py 가 모듈 머리에서 임포트·dot-source)
    "collect/OutlookCommon.ps1",
    "collect/owa_parse.py",
    # 빠지면 회의 안건 없이 판정한다
    "core/meetnote.py",
    "config/config.json",
    "config/config.default.json",
    "config/restricted_customers.example.json",
    "core/extract.py",
    "core/budget.py",
    "core/stage_state.py",
    "core/watch.py",
    "core/teamaddr.py",
    "core/lmname.py",
    "core/privacy.py",
    "core/coverage.py",
    "core/proc.py",
    "core/collect_status.py",
    "core/mailmerge.py",
    "core/details.py",
    "core/owner.py",
    "core/progress.py",
    "core/projmap.py",
    # AF32 규칙 단일원 — 설정 하한·기간·설치 검사·시작 확인·보관기한(빠지면 모든 시작점이 멈춘다)
    "core/afcfg.py",
    "core/period.py",
    "core/install.py",
    "core/consent.py",
    "core/retention.py",
    "docs/설정가이드.md",
    "docs/사용안내.html",
    "docs/운영기준.md",
    "tools/copilot_auto.py",
    "tools/trace_summary.py",
    "tools/Get-EmbeddedPython.ps1",
    "tools/Make-Package.ps1",
    "tools/Stop-AF32.ps1",
    "tools/stop_af32.py",
    "tools/ps_launch.py",
    "ui/app.py",
]
miss = [p for p in NEED if not os.path.exists(os.path.join(ROOT, p.replace("/", os.sep)))]
print(f"[점검] 필수 {len(NEED)}개 중 {len(NEED)-len(miss)}개 존재")
if miss:
    print(f"[!] 누락 {len(miss)}개 — 원본 PC에서 아래 파일을 복사하세요:")
    for m in miss:
        print("    " + m)
    sys.exit(1)
print("[OK] 전부 있습니다. AgentFinder32-UI.bat 을 실행하세요.")
print("     이 도구는 Agentic AI 로 바꿀 만한 업무를 찾는 데만 씁니다. 결과는 이 PC 에 남고, 공유는 [공유] 탭에서 고를 때만 보냅니다.")

try:
    _cfg = json.load(open(os.path.join(ROOT, "config", "config.json"), encoding="utf-8-sig"))
except (OSError, ValueError):
    _cfg = {}
if not isinstance(_cfg, dict):
    _cfg = {}

# ── 배포 위생 ────────────────────────────────────────────────────────────
# 남이 만든 설정(owner)이 그대로 남은 배포본은 받은 사람의 화면·리포트에 남의 이름을 보인다.
# data\ report\ 가 비어 있어도 owner 는 남는다 — 폴더째 복사한 뒤 data\ report\ 만 지운 배포본이
# 그 경우라, 잔존 파일 유무와 무관하게 항상 본다.
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
    print("    남이 만든 배포본이면 그대로 두지 마세요. config\\config.json 의 owner 를 비우거나 고치세요.")


def _edge_profile_names():
    """전용 Edge 프로필 폴더 이름 — 이 판(af32_edge)과, 옛 판 폴더를 옮겨 오며 딸려 온 옛 판 프로필.
    이름은 core\\lmname.py 단일원에서 읽는다(위 NEED 점검을 지났으니 파일은 있다). 못 읽으면 이 판 이름만 본다."""
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("lm_lmname", os.path.join(ROOT, "core", "lmname.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return (mod.EDGE_PROFILE_NAME,) + tuple(mod.OLD_PROFILES)
    except Exception:          # 이름 모듈이 깨져도 자가점검은 죽지 않는다
        return ("af32_edge",)


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
            extra = "  <- 조직장 서버가 받은 공유 자료 포함, 이 PC 밖으로 옮기지 마세요"
        if d == "data" and any(os.path.isdir(os.path.join(ROOT, d, x)) for x in _edge_profile_names()):   # 이 판·옛 판 전용 Edge 프로필
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


# ── 조직장 서버 주소 ────────────────────────────────────────────────────────
# 공유는 화면의 [공유] 탭에서 본인이 고를 때만 이 주소로 보낸다(자동으로 보내지 않는다). 주소·참여 코드는
# AgentFinder32-팀서버주소.bat 으로 넣는다. 주소를 넣지 않았으면 아무 데도 보내지 않는다.
try:
    import importlib.util
    _spec = importlib.util.spec_from_file_location("lm_teamaddr", os.path.join(ROOT, "core", "teamaddr.py"))
    _ta = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_ta)
    print()
    print(f"[조직장 서버] 공유할 때만 쓰는 주소 — 바꾸려면 {getattr(_ta, 'EDIT_BAT', 'AgentFinder32-팀서버주소.bat')}")
    _desc = getattr(_ta, "describe", None)
    _load = getattr(_ta, "load", None)
    if callable(_desc) and callable(_load):
        print(_desc(_load(ROOT)))
except Exception as _e:            # 주소 확인이 실패해도 파일 점검 결과는 그대로 둔다
    print(f"[!] 조직장 서버 주소를 읽지 못했습니다({type(_e).__name__}) — core\\teamaddr.py 를 확인하세요")
