# -*- coding: utf-8 -*-
r"""
Make-MovePack.py — 다른 PC 로 옮길 **최소 이동본**을 zip 한 개로 만든다(보조 수단).

※ 실사용 동선에서는 이 파일을 쓰지 않는다. 사용자는 [PC 이동 준비] 를 누르고 폴더를 탐색기로
  드래그한다(제보: "zip 을 따로 옮기거나 푸는 것은 못 한다"). 그래서 폴더를 실제로 줄이는 일은
  tools\Prepare-Move.ps1 의 Trim-Profile 이 [PC 이동 준비] 안에서 **자동으로** 한다.
  이 파일은 그 규칙의 사본(trim_profile)과, 원하는 사람을 위한 zip 묶기를 갖고 있다.

폴더가 큰 원인은 '데이터가 많아서' 가 아니라 폴더 하나다: data\copilot_profile(Copilot 로그인용
Edge 프로필)이 **파일 수의 94%·용량의 96%** 를 차지한다(실측 8개 설치본 100~529MB).
정작 옮겨야 할 수집 CSV·보고서는 0.06~0.27MB 다. 그리고 로그인 세션은 Windows DPAPI 로
'이 PC·이 계정' 에 묶여 있어 **가져가도 살아나지 않는다** — 받는 PC 에서 [AI 연결 진단] 으로
한 번 로그인하면 끝이다(30초 미만).

  python tools\Make-MovePack.py [--out D:\어디] [--full] [--no-report]
  python tools\Make-MovePack.py --trim      # zip 없이 **프로필만 줄인다**

--trim 은 [PC 이동 준비] 와 같은 규칙으로 프로필을 줄인다: 루트에서 Default 와 Local State 등
몇 개만 남기고, Default 안에서는 캐시류와 저장된 비밀번호·방문 이력을 지운다.
**로그인은 그대로 남는다**(Default 의 쿠키·MSAL 토큰, 루트 Local State 를 남긴다).
실측: 529.2MB/2,507개 → 11.7MB/418개(98% 회수, 0.8초). 비우고 나면 폴더째 복사해도 빠르다
(같은 폴더 robocopy 실측 0.68초 → 0.09초).
Edge 기동 인자의 캐시 상한(config.copilotAuto.diskCacheMB)은 Default\Cache 31MB 만 제어한다 —
ProvenanceData 168MB·component_crx_cache 168MB 는 그 상한과 무관해서 이 정리가 필요하다.

담는 것 : data\ (copilot_profile 제외) · report\ · config\*.json (병합 맵 포함)
안 담는 것: data\copilot_profile · python\ · .git\ · __pycache__ · *.zip · 얼린보고서 과거본(--full 이면 전부)
  · python\ 은 배포본(풀패키지)에 들어 있어 다시 받으면 된다
  · config 의 detail_aliases.json·project_aliases.json 은 **반드시** 담는다 — 저장소에 없고
    사람마다 달라서, 빠지면 같은 데이터에서 다른 병합 결과가 나온다(정확성 회귀)
  · data\pc_name.txt 는 한 줄짜리지만 빠지면 지난 PC 데이터가 새 수집에 덮인다

받는 PC 에서: 같은 판본 폴더에 이 zip 을 풀고 → [AI 연결 진단] 으로 Edge 로그인 1회 → [분석 실행].
"""
import io
import os
import shutil
import sys
import time
import zipfile

if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, errors="replace", encoding=(
        (sys.stdout.encoding or "utf-8") if sys.stdout.isatty() else "utf-8"))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP_DIRS = {"copilot_profile", "__pycache__", ".ruff_cache", ".git", "python"}
SKIP_EXT = {".zip", ".pyc", ".partial", ".tmp"}
KEEP_FROZEN = 2                 # report\얼린보고서\ 는 최근 몇 개만(한 장 0.5MB 씩 쌓인다)


def arg(flag, d=""):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv and sys.argv.index(flag) + 1 < len(sys.argv) else d


def log(m):
    print(f"[movepack] {m}")
    sys.stdout.flush()


def _walk(base, rel):
    """담을 파일 목록 — (전체경로, zip 안 경로). 건너뛴 폴더는 통째로 안 들어간다."""
    out = []
    top = os.path.join(base, rel)
    if not os.path.isdir(top):
        return out
    for cur, dirs, files in os.walk(top):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fn in files:
            if os.path.splitext(fn)[1].lower() in SKIP_EXT:
                continue
            p = os.path.join(cur, fn)
            out.append((p, os.path.relpath(p, base)))
    return out


def _frozen_trim(items, keep):
    """얼린보고서 과거본은 최근 몇 개만 — 한 장 0.5MB 라 오래 쓰면 이것만 수십 MB 가 된다."""
    fz = [(p, r) for p, r in items if os.sep + "얼린보고서" + os.sep in os.sep + r]
    if len(fz) <= keep:
        return items, 0
    fz.sort(key=lambda x: os.path.getmtime(x[0]), reverse=True)
    drop = {r for _p, r in fz[keep:]}
    return [(p, r) for p, r in items if r not in drop], len(drop)


# 프로필에서 '옮길 필요가 없는 것' 을 지운다. 지울 이름을 나열하지 않고 **남길 것만 남긴다** —
# Edge 는 버전이 오를 때마다 새 컴포넌트 폴더를 만들어서(ProvenanceData·Edge Entity Extraction·
# Edge Wallet·Subresource Filter…) 이름 목록 방식은 반드시 낡는다. 실측: 옛 목록의 DawnCache·
# optimization_guide_model_store 는 지금 프로필에 없는 이름이고, 그 목록으로는 529MB 중 244MB 밖에
# 못 걷어냈다. 반전 규칙은 같은 프로필에서 517.5MB(98%)를 회수한다(529.2MB/2,507개 → 11.7MB/418개).
# 이름 비교는 반드시 완전 일치 — '*Wallet*' 은 루트 'Edge Wallet'(지워도 됨)과 Default\EdgeWallet(보존)을,
# '*crx_cache*' 는 component_crx_cache(지움)와 extensions_crx_cache(보존)를 뒤섞는다.
# ※ 정본은 tools\Prepare-Move.ps1 의 Trim-Profile 이다(실사용 동선 [PC 이동 준비] 가 그쪽을 탄다).
#    여기는 같은 규칙의 사본이므로 한쪽을 고치면 다른 쪽도 같이 고칠 것.
KEEP_ROOT = {"Default", "Local State", "Last Browser", "Last Version",
             "first_party_sets.db", "Variations"}
DEL_IN_DEFAULT = ("Cache", "Code Cache", "GPUCache", "ShaderCache", "DawnCache",
                  "DawnGraphiteCache", "DawnWebGPUCache", "GrShaderCache",
                  "component_crx_cache", "optimization_guide_hint_cache_store",
                  "optimization_guide_model_store", "EdgeCoupons")
# 저장된 비밀번호·자동완성·방문 이력은 옮길 폴더에 있을 이유가 없다 — 실측해 보니 전용 프로필에도
# 동기화로 개인 비밀번호와 방문 이력이 들어와 있었다(공개 저장소라 건수는 적지 않는다).
# 로그인 세션은 Cookies·Local State 로 유지되므로 이 PC 에서 계속 써도 다시 로그인하지 않는다.
DEL_FILES_IN_DEFAULT = ("Login Data", "Login Data For Account", "Web Data", "History")


def _long(p):
    r"""260자(MAX_PATH)를 넘는 경로는 \\?\ 접두사가 있어야 지워진다 — Service Worker\CacheStorage 의
    GUID 경로가 쉽게 넘는다(실측: 267자에서 삭제가 통째로 실패해 21.4MB 가 그대로 남았다)."""
    p = os.path.abspath(p)
    if p.startswith("\\\\?\\"):
        return p
    return "\\\\?\\UNC" + p[1:] if p.startswith("\\\\") else "\\\\?\\" + p


def _rm(path):
    if not os.path.exists(path):
        return
    if os.path.isdir(path):
        shutil.rmtree(path, ignore_errors=True)
        if os.path.isdir(path):
            shutil.rmtree(_long(path), ignore_errors=True)
        return
    for p in (path, _long(path)):
        try:
            os.remove(p)
            return
        except OSError:
            pass


def _size(path):
    n = b = 0
    for r, _d, fs in os.walk(path):
        for f in fs:
            try:
                b += os.path.getsize(os.path.join(r, f))
                n += 1
            except OSError:
                pass
    return n, b


def trim_profile():
    """전용 Edge 프로필에서 옮길 필요가 없는 것을 지운다 → (지운 파일 수, 바이트).
    로그인(Default 안의 쿠키·MSAL 토큰, 루트 Local State)은 남는다.
    회수량은 **삭제 후 재측정**으로 낸다 — 삭제 전에 세면 잠겨서 못 지운 것까지 '지웠다' 로 집계돼
    '정리했다는데 폴더는 그대로' 가 된다(옛 구현의 결함)."""
    prof = os.path.join(ROOT, "data", "copilot_profile")
    if not os.path.isdir(prof):
        log("전용 Edge 프로필이 없습니다 — 비울 것이 없습니다.")
        return 0, 0
    n0, b0 = _size(prof)
    for name in os.listdir(prof):
        if name not in KEEP_ROOT:
            _rm(os.path.join(prof, name))
    dflt = os.path.join(prof, "Default")
    if os.path.isdir(dflt):
        for d in DEL_IN_DEFAULT:
            _rm(os.path.join(dflt, d))
        _rm(os.path.join(dflt, "Service Worker", "CacheStorage"))   # 등록부는 남긴다
        for f in DEL_FILES_IN_DEFAULT:
            _rm(os.path.join(dflt, f))
    n1, b1 = _size(prof)
    return n0 - n1, b0 - b1


def main():
    if "--trim" in sys.argv:
        log("전용 Edge 프로필의 캐시만 비웁니다 — 로그인은 그대로 남습니다.")
        log("(Edge 가 열려 있으면 일부는 잠겨 있어 다음에 지워집니다)")
        n, b = trim_profile()
        log(f"지운 캐시 {n:,}개 · {b / 1048576:.1f} MB")
        log("이제 폴더째 옮겨도 빠릅니다 — [PC 이동 준비]가 알려 주는 robocopy 한 줄을 쓰세요.")
        return 0
    full = "--full" in sys.argv
    out_dir = arg("--out") or os.path.dirname(ROOT)
    items = []
    for rel in ("data", "config"):
        items += _walk(ROOT, rel)
    if "--no-report" not in sys.argv:
        items += _walk(ROOT, "report")
    if not items:
        log("담을 것이 없습니다 — data\\ report\\ config\\ 가 모두 비어 있습니다.")
        return 1
    n_trim = 0
    if not full:
        items, n_trim = _frozen_trim(items, KEEP_FROZEN)
    total = sum(os.path.getsize(p) for p, _r in items if os.path.exists(p))

    host = (os.environ.get("COMPUTERNAME") or "PC").strip()[:20]
    name = f"{os.path.basename(ROOT)}_이동묶음_{host}_{time.strftime('%Y%m%d_%H%M%S')}.zip"
    dst = os.path.join(out_dir, name)
    os.makedirs(out_dir, exist_ok=True)

    log(f"담을 파일 {len(items):,}개 · {total / 1048576:.1f} MB"
        + (f" (얼린보고서 과거본 {n_trim}개 제외 — 전부 담으려면 --full)" if n_trim else ""))
    log("data\\copilot_profile 은 담지 않습니다 — Edge 캐시이고 로그인은 이 PC 에 묶여 있어 "
        "가져가도 살아나지 않습니다(받는 PC 에서 [AI 연결 진단] 1회).")
    t0 = time.monotonic()
    tmp = dst + ".partial"
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            for i, (p, rel) in enumerate(items, 1):
                try:
                    z.write(p, rel)
                except OSError as e:      # 열려 있는 파일 하나가 묶음 전체를 막지 않게
                    log(f"  건너뜀: {rel} ({type(e).__name__})")
                if i % 500 == 0:
                    log(f"  {i:,}/{len(items):,}")
        os.replace(tmp, dst)
    except OSError as e:
        try:
            os.remove(tmp)
        except OSError:
            pass
        log(f"묶음을 만들지 못했습니다({type(e).__name__}: {str(e)[:80]})")
        return 1
    sec = time.monotonic() - t0
    zmb = os.path.getsize(dst) / 1048576
    log(f"만들었습니다 — {dst}")
    log(f"  {len(items):,}개 → 파일 1개 · {total / 1048576:.1f} MB → {zmb:.1f} MB · {sec:.1f}초")
    log("  이 zip 하나만 옮기면 됩니다. 받는 PC 의 같은 판본 폴더에 풀고 바로 쓰세요.")
    log("  · [추가 PC 수집]·[팀 취합]·[재분석만] 은 로그인 없이 그대로 됩니다.")
    log("  · [분석 실행] 도 됩니다 — Copilot 로그인이 없으면 AI 판정만 건너뛰고 규칙 판정으로")
    log("    신호·MM·보고서를 만듭니다(약 35초 안에 알려 줍니다). 뒤에 [AI 연결 진단] 으로")
    log("    한 번 로그인하고 [재분석만] 을 누르면 AI 판정만 이어서 합니다.")
    log("  원본 폴더는 지우지 마세요 — 새 PC 가 잘 도는 것을 확인한 뒤에 정리하시면 됩니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
