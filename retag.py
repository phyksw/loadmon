# -*- coding: utf-8 -*-
"""
retag.py — 지정 반영 재분류 (AgentFinder32)

사용자가 UI에서 과제를 **추후** 지정·수정했을 때, 이미 분류된 신호 중
'공통'이나 자동발견 과제로 귀속된 것을 지정 과제와의 유사성으로 재귀속한다.
Copilot 왕복 없이 결정적 규칙(core\\projmap.py)으로 몇 초에 끝난다:
  · 이름·식별 키워드가 신호 원문에 직접 등장 → 재귀속
  · 관련 내용(설명) 토큰 2개 이상 등장 → 재귀속
  · 사용자가 지정한 다른 과제로 이미 판정된 신호는 존중(변경 없음)

  python retag.py                          # 최신 signals_* 대상(AgentFinder32 표식이 있는 기간만)
  python retag.py --from 2026-08-01 --to 2026-10-31

재분류 후 work_rows·pivots·evidence 를 다시 쓴다(judge.write_outputs 공용 — 근거건수만, 시간·MM 없음).
시작할 때 내 자료인지(consent.require — 다른 사용자의 자료면 종료 코드 4 · 지우는 중이면 3)와 제한 고객 목록(privacy.load_restricted — 없으면 종료 코드 4)을 확인한다.
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
    import details
    import projmap
    rc = details.consent_gate("retag", ROOT) or details.restricted_gate("retag", ROOT)   # 다른 사용자의 자료 4 · 지우는 중 3 · 제한 고객 목록 없음 4
    if rc:
        return rc
    import extract
    from judge import PRODUCT, SIGNAL_COLS, _write_csv_atomic, _write_json_atomic, merge_details, sanitize_models
    from judge import write_outputs
    rep = os.path.join(ROOT, "report")
    d0, d1 = arg("--from"), arg("--to")
    if d0 and d1:
        sp = os.path.join(rep, f"signals_{d0.replace('-','')}-{d1.replace('-','')}.csv")
    else:
        cands = sorted(glob.glob(os.path.join(rep, "signals_*.csv")), key=os.path.getmtime)
        cands = [c for c in cands if details.af32_tag_ok(os.path.basename(c)[len("signals_"):-len(".csv")], rep)]
        sp = cands[-1] if cands else ""
    if not sp or not os.path.exists(sp):
        print("[retag] 대상 signals_*.csv 없음 — 먼저 분석을 실행하세요")
        print(json.dumps({"ok": False, "error": "no signals"}))
        return 1
    tag = os.path.basename(sp)[len("signals_"):-len(".csv")]
    if not details.af32_tag_ok(tag, rep):
        print(f"[retag] report\\run_meta_{tag}.json 에 {PRODUCT} 표식이 없어 이 기간 자료를 쓰지 않습니다")
        print(json.dumps({"ok": False, "error": "not af32"}))
        return 1

    projects = projmap.load_user_projects(ROOT)
    if not projects:
        print("[retag] 지정된 과제가 없습니다 — UI '과제 지정' 카드에서 먼저 추가하세요")
        print(json.dumps({"ok": False, "error": "no projects"}))
        return 1

    with open(sp, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        print(json.dumps({"ok": False, "error": "empty signals"}))
        return 1
    # AI 판정 전(mine 전용) CSV에는 비업무·미지정 행이 남아 있어 재분류하면 오귀속된다
    if not any((r.get("judge") or "").strip() for r in rows):
        print("[retag] 이 결과는 아직 AI 판정 전입니다 — [분석 실행]에 'AI 판정' 체크 후 다시 실행하세요")
        print(json.dumps({"ok": False, "error": "not judged"}))
        return 1
    for r in rows:                              # 날짜만(D10)
        r["time"] = str(r.get("time") or "")[:10]
    n, by, ev = projmap.retag_rows(rows, projects)

    n_out = None
    if n:
        for r in rows:  # judge 미실행 상태(과제 열 없음)여도 일관 컬럼으로 저장
            r.setdefault("model", r.get("project") or "공통")
            r.setdefault("worktype", "")
            r.setdefault("detail", r.get("activity") or "")
            r.setdefault("judge", "")
        merge_details(rows)      # signals 와 work_rows 의 세부업무 이름을 일치시킨다
        for r in rows:
            r["project"] = r.get("model", r.get("project", ""))
            r["activity"] = r.get("detail", r.get("activity", ""))
        _write_csv_atomic(sp, SIGNAL_COLS, rows)
        n_out, _pv = write_outputs(rows, tag, extract.load_cfg(), rep)

        # 화면은 정제본(_refined)을 우선 보이므로, 재분류로 낡아진 정제본과 그 매핑은 무효화한다
        # (다음 AI 실행의 refine 단계에서 재분류 반영본으로 다시 생성됨)
        for nm in (f"work_rows_{tag}_refined.csv", f"refine_map_{tag}.json"):
            fp = os.path.join(rep, nm)
            if os.path.exists(fp):
                os.remove(fp)
                print(f"[retag] {nm} 은 재분류로 낡아져 무효화 — 다음 AI 실행 때 다시 만듭니다")
    # 재분류 0건이면 signals·work_rows·pivots 를 다시 쓰지 않는다 — 내용이 같아도 원본 work_rows 의 mtime 이 정제본보다
    # 새로워져 core/details.rows_path 가 원본을 고르게 된다.

    # entities 에 지정 과제 반영 (UI 엔티티 카드·다음 체계 수립 일관성) — 표식 product
    ep = os.path.join(rep, f"entities_{tag}.json")
    try:
        eo = {"models": [], "worktypes": []}
        if os.path.exists(ep):
            with open(ep, encoding="utf-8-sig") as f:
                eo = json.load(f)
        if isinstance(eo, dict):
            eo["product"] = PRODUCT
            eo["models"] = sanitize_models(
                [{"name": p["name"], "match": p.get("match") or [], "obs": "사용자 지정", "pinned": True}
                 for p in projects] + list(eo.get("models") or []))
            _write_json_atomic(ep, eo)
    except (OSError, ValueError):
        pass

    detail = " · ".join(f"{k} {v}건" for k, v in sorted(by.items(), key=lambda x: -x[1]))
    print(f"[retag] 재분류 {n}건" + (f" → {detail}" if detail else " (유사 신호 없음)")
          + (f" · 업무 분류 {n_out}줄 다시 씀" if n_out is not None else " · 다시 쓰지 않음(결과 파일 변경 없음)"))
    for k, samples in ev.items():
        for s in samples[:3]:
            print(f"        {k} ← {s}")
    print(json.dumps({"ok": True, "retagged": n, "by": by, "tag": tag}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, errors="replace", encoding=(
        (sys.stdout.encoding or "utf-8") if sys.stdout.isatty() else "utf-8"))  # 콘솔(bat)=콘솔 코드페이지 · 파이프(UI)=utf-8
    sys.exit(main())
