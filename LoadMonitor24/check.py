# -*- coding: utf-8 -*-
"""
check.py — 배분표 진단 CLI (읽기 전용).

  python check.py "D:\\자료작성\\데이터.xlsx"
  python check.py <파일> --write out.xlsx     # 파생열 재계산본을 '사본'으로 저장
"""
import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "core"))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, errors="replace", encoding=(
        (sys.stdout.encoding or "utf-8") if sys.stdout.isatty() else "utf-8"))  # 콘솔(bat)=콘솔 코드페이지 · 파이프(UI)=utf-8
import board  # noqa: E402

HEADCOUNT = {"System": 10, "OE": 10, "ME": 9, "EE": 6}      # 파트 정원 (조직 입력)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__)
        return 2
    path = args[0]
    rows = board.load_board(path)
    rec = board.recompute(rows)
    issues, ag = board.validate(rec, HEADCOUNT)
    print(f"[배분표] {os.path.basename(path)} — {len(rows)}행 · "
          f"인원 {len({board._s(r['이름']) for r in rows})}명 · 총 {ag['total_mm']:.2f} MM\n")

    d = board.diff_vs_file(rows, rec)
    if d:
        print("■ 파일의 파생값 ↔ 규칙 재계산 불일치")
        for c, lst in d.items():
            print(f"   {c}: {len(lst)}건  예) {lst[0]}")
    else:
        print("■ 파생 15열: 파일 값과 규칙 재계산이 전부 일치 (표가 최신 상태)")

    print(f"\n■ 정합성 검증 — {len(issues)}건")
    for it in sorted(issues, key=lambda x: {"high": 0, "medium": 1, "low": 2}[x["severity"]]):
        print(f"   [{it['severity']:6s}] {it['kind']:12s} {it['msg']}")

    print("\n■ AX 과제별 로드 (상위 8)")
    for c, v in sorted(ag["by_code"].items(), key=lambda kv: -kv[1]["mm"])[:8]:
        fn = " ".join(f"{k} {x:.2f}" for k, x in v["by_func"].items() if x)
        print(f"   {c:12s} {v['mm']:6.2f} MM · 인원 {v['people']:4.1f}명"
              f"(실질 {v['people_01']:4.1f}) · 최근3M {v['run3']:5.2f} · {fn}")

    print("\n■ 파트별 로드율")
    for f, v in ag["by_part"].items():
        r = v["배분율_재직"]
        print(f"   {f:8s} 정원 {v['정원']:.0f} · 실명 {v['실명인원']:.1f} · "
              f"월평균 {v['월평균mm_재직']:.2f} MM · 배분율 {r if r is None else f'{r:.2f}'}")

    if "--write" in sys.argv:
        out = sys.argv[sys.argv.index("--write") + 1]
        board.write_board(path, out, rec)
        print(f"\n[저장] 재계산본 → {out} (원본 무변경)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
