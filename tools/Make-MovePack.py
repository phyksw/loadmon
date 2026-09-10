# -*- coding: utf-8 -*-
r"""
Make-MovePack.py — 다른 PC 로 옮길 **최소 이동본**을 zip 한 개로 만든다.

폴더째 옮기면 10~30분이 걸린다는 제보의 원인은 '데이터가 많아서' 가 아니라 폴더 하나다:
data\copilot_profile(Copilot 로그인용 Edge 프로필)이 **파일 수의 94%·용량의 96%** 를 차지한다
(tools\Prepare-Move.ps1 의 실측 기록). 그 안은 Edge 가 새 PC 에서 알아서 다시 받는 캐시이고,
로그인 세션은 Windows DPAPI 로 '이 PC·이 계정' 에 묶여 있어 **가져가도 살아나지 않는다** —
받는 PC 에서 [AI 연결 진단] 으로 한 번 로그인하면 끝이다(30초 미만).

느린 이유는 바이트와 **파일 개수** 둘 다다(실측: 같은 58.6MB 를 3,000개로 쪼개면 17배 느리다).
그래서 zip **한 개**로 만든다 — 옮길 파일이 1개가 되면 두 원인이 함께 사라진다.

  python tools\Make-MovePack.py [--out D:\어디] [--full] [--no-report]

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


def main():
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
    log("  이 zip 하나만 옮기면 됩니다. 받는 PC 의 같은 판본 폴더에 풀고 →")
    log("  [AI 연결 진단] 으로 Edge 에 회사 계정 1회 로그인 → [분석 실행].")
    log("  원본 폴더는 지우지 마세요 — 새 PC 가 잘 도는 것을 확인한 뒤에 정리하시면 됩니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
