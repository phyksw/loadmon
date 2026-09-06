# -*- coding: utf-8 -*-
"""
retag.py — 지정 반영 재분류 (LoadMonitor8)

사용자가 UI에서 과제를 **추후** 지정·수정했을 때, 이미 분류된 신호 중
'공통'이나 자동발견 과제로 귀속된 것을 지정 프로젝트와의 유사성으로 재귀속한다.
Copilot 왕복 없이 결정적 규칙(core\\projmap.py)으로 몇 초에 끝난다:
  · 이름·식별 키워드가 신호 원문에 직접 등장 → 재귀속
  · 관련 내용(설명) 토큰 2개 이상 등장 → 재귀속
  · 사용자가 지정한 다른 프로젝트로 이미 판정된 신호는 존중(변경 없음)

  python retag.py                          # 최신 signals_* 대상
  python retag.py --from 2026-05-19 --to 2026-08-17

재분류 후 mm_rows·pivots 를 재집계한다(judge.write_outputs 공용).
마지막 줄에 JSON 결과를 출력한다 — UI [지정 반영 재분류] 버튼이 이를 읽는다.
"""
import csv
import glob
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "core"))
sys.path.insert(0, ROOT)


def arg(flag, d=""):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else d


def main():
    import projmap
    from judge import merge_details, write_outputs
    import extract
    rep = os.path.join(ROOT, "report")
    d0, d1 = arg("--from"), arg("--to")
    if d0 and d1:
        sp = os.path.join(rep, f"signals_{d0.replace('-','')}-{d1.replace('-','')}.csv")
    else:
        cands = sorted(glob.glob(os.path.join(rep, "signals_*.csv")), key=os.path.getmtime)
        cands = [c for c in cands if not c.endswith("_rules.csv")]
        sp = cands[-1] if cands else ""
    if not sp or not os.path.exists(sp):
        print("[retag] 대상 signals_*.csv 없음 — 먼저 분석을 실행하세요")
        print(json.dumps({"ok": False, "error": "no signals"}))
        return 1
    tag = os.path.basename(sp)[len("signals_"):-len(".csv")]

    projects = projmap.load_user_projects(ROOT)
    if not projects:
        print("[retag] 지정된 프로젝트가 없습니다 — UI '과제 지정' 카드에서 먼저 추가하세요")
        print(json.dumps({"ok": False, "error": "no projects"}))
        return 1

    rows = list(csv.DictReader(open(sp, encoding="utf-8-sig")))
    if not rows:
        print(json.dumps({"ok": False, "error": "empty signals"}))
        return 1
    # AI 판정 전(mine 전용) CSV에는 비업무·미지정 행이 남아 있어 재분류하면 오귀속된다
    if not any((r.get("judge") or "").strip() for r in rows):
        print("[retag] 이 결과는 아직 AI 판정 전입니다 — [분석 실행]에 'AI 판정' 체크 후 다시 실행하세요")
        print(json.dumps({"ok": False, "error": "not judged"}))
        return 1
    n, by, ev = projmap.retag_rows(rows, projects)

    total_mm = None
    if n:
        cols = ["time", "source", "who", "project", "activity", "weight", "text",
                "model", "worktype", "detail", "judge"]
        for r in rows:  # judge 미실행 상태(과제 열 없음)여도 일관 컬럼으로 저장
            r.setdefault("model", r.get("project") or "공통")
            r.setdefault("worktype", "")
            r.setdefault("detail", r.get("activity") or "")
            r.setdefault("judge", "")
        merge_details(rows)      # 리뷰(signals)와 대시보드(mm_rows)의 세부업무 이름을 일치시킨다
        with open(sp, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            for r in rows:
                w.writerow({c: r.get(c, "") for c in cols})

        cfg = extract.load_cfg()
        total_mm, pv = write_outputs(rows, tag, cfg, rep)

        # 대시보드는 정제본(_refined)을 우선 표시하므로, 재분류로 낡아진 정제본은 무효화한다
        # (다음 --ai 실행의 refine 단계에서 재분류 반영본으로 다시 생성됨)
        refined_p = os.path.join(rep, f"mm_rows_{tag}_refined.csv")
        if os.path.exists(refined_p):
            os.remove(refined_p)
            print("[retag] 정제본(mm_rows_*_refined)은 재분류로 낡아져 무효화 — 다음 AI 실행 때 재생성됩니다")
    # 재분류 0건이면 signals·mm_rows·pivots 를 다시 쓰지 않는다 — 내용이 같아도 원본 mm_rows 의
    # mtime 이 정제본보다 새로워져 core/details.rows_path 가 원본을 고르고, 그 뒤의 Agentic 실측
    # 재계산이 대시보드(정제본)와 다른 행으로 load_mm 을 붕괴시켰다(UI-1).

    # entities에 지정 프로젝트 반영 (UI 엔티티 카드·다음 taxonomy 일관성)
    ep = os.path.join(rep, f"entities_{tag}.json")
    try:
        eo = json.load(open(ep, encoding="utf-8")) if os.path.exists(ep) else {"models": [], "worktypes": []}
        from judge import sanitize_models
        eo["models"] = sanitize_models(
            [{"name": p["name"], "match": p.get("match") or [], "obs": "사용자 지정", "pinned": True}
             for p in projects] + eo.get("models", []))
        with open(ep, "w", encoding="utf-8") as f:
            json.dump(eo, f, ensure_ascii=False, indent=1)
    except (OSError, ValueError):
        pass

    detail = " · ".join(f"{k} {v}건" for k, v in sorted(by.items(), key=lambda x: -x[1]))
    print(f"[retag] 재분류 {n}건" + (f" → {detail}" if detail else " (유사 신호 없음)")
          + (f" · 총 {total_mm:.2f} MM 재집계" if total_mm is not None
             else " · 재집계 생략(결과 파일 변경 없음)"))
    for k, samples in ev.items():
        for s in samples[:3]:
            print(f"        {k} ← {s}")
    print(json.dumps({"ok": True, "retagged": n, "by": by, "tag": tag}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, errors="replace", encoding=(
        (sys.stdout.encoding or "utf-8") if sys.stdout.isatty() else "utf-8"))  # 콘솔(bat)=콘솔 코드페이지 · 파이프(UI)=utf-8
    sys.exit(main())
