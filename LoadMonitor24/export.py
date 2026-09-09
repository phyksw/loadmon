# -*- coding: utf-8 -*-
"""
export.py -- 본인 분석 결과를 팀 공유폴더로 내보낸다 (config.teamShareDir).

  python export.py --from 2026-05-19 --to 2026-08-17

공유폴더의 <이름> 하위에 복사되는 것: mm_rows / signals(판정 반영) / mm_meta / pivots /
ai_narratives / entities + member.json(요약). raw 단서(신호 원문)가 포함되므로
팀 취합 시 오해석을 줄일 수 있다. 개인 폴더 신호는 이미 excludePathKeywords 로 걸러진 상태.
"""
import io
import json
import os
import re
import shutil
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))

# 동봉한 파이썬(python\python311._pth)은 **스크립트가 있는 폴더를 sys.path 에 넣지 않는다** —
# python311.zip 과 python\ 만 들어간다. 그래서 뿌리 모듈(teamup·team_report…)을 실행 중에
# import 하려면 여기서 직접 넣어야 한다. 없으면 ModuleNotFoundError 가 나는데, 부르는 쪽이
# try/except 로 감싸고 있어 오류 없이 기능만 조용히 빠진다(실측: 공유폴더 member.json 에
# measure/coverage/cfg_used/tool_usage 가 통째로 없었고, 팀 통합보고서가 아예 안 만들어졌다).
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def arg(flag, d=""):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else d


def main():
    d0, d1 = arg("--from"), arg("--to")
    if not d0 or not d1:
        # 인자 없이 돌면 tag='-' 가 되어 공유폴더의 정상 member.json 을 빈 내용으로
        # 덮어쓴다(검증 확정) — 반드시 기간을 받아야 한다.
        print("[export] 사용법: python export.py --from YYYY-MM-DD --to YYYY-MM-DD")
        return 1
    cfg = json.load(open(os.path.join(ROOT, "config", "config.json"), encoding="utf-8-sig"))
    share = (cfg.get("teamShareDir") or "").strip()
    if not share:
        print("[export] config.teamShareDir 미설정 — 건너뜀")
        return 0
    tag = f"{d0.replace('-','')}-{d1.replace('-','')}"
    sys.path.insert(0, os.path.join(ROOT, "core"))
    try:                                   # teamup 과 같은 규칙 — 같은 사람이 두 폴더로 갈라지면 팀 MM 이 중복된다
        from owner import safe_owner
    except ImportError:
        def safe_owner(v):
            """core\\owner.py 와 같은 규칙(그 파일이 없을 때만 쓰인다 — 규칙이 갈리면 인원이 두 폴더로 나뉜다)"""
            s = re.sub(r'[\\/:*?"<>|.]', '_', str(v or '').strip())
            s = re.sub(r'\s+', ' ', s).strip()[:40].strip()
            return s or '이름미상'
    owner = safe_owner(cfg.get("owner") or os.environ.get("USERNAME", ""))
    rep = os.path.join(ROOT, "report")
    dst = os.path.join(share, owner)

    def longp(p):                          # 260자 초과 공유폴더 대응 (teamup.longp 와 같은 규칙)
        p = os.path.abspath(p)
        if os.name != "nt" or len(p) < 240 or p.startswith("\\\\?\\"):
            return p
        return ("\\\\?\\UNC" + p[1:]) if p.startswith("\\\\") else ("\\\\?\\" + p)

    try:
        os.makedirs(longp(dst), exist_ok=True)
    except OSError as e:
        print(f"[export] 공유폴더 접근 실패: {e}")
        return 1
    # teamup.FILE_NAMES(서버 업로드)와 같은 목록이어야 한다 — workflow 가 빠져 있어 공유폴더로 낸 사람만
    # 팀 통합 보고서의 워크플로우 절(§7~§10 · AX 가능 MM)에서 통째로 빠졌다(샘플 생성에서 실측).
    names = [f"mm_rows_{tag}.csv", f"mm_rows_{tag}_refined.csv", f"signals_{tag}.csv",
             f"mm_meta_{tag}.json", f"pivots_{tag}.json", f"ai_narratives_{tag}.json",
             f"entities_{tag}.json", f"agentic_{tag}.json", f"workflow_{tag}.json"]
    # 한 파일만 실패해도 member.json 을 새로 쓰면, 공유폴더가 '옛 행 + 새 요약'으로 섞여
    # 팀 리포트가 같은 사람의 MM 을 두 값으로 보여 준다(검증 확정: 0.10 vs 0.50).
    # 그래서 스테이징에 전부 복사하고, 전부 성공했을 때만 제자리로 옮긴다.
    want = [n for n in names if os.path.exists(os.path.join(rep, n))]
    stage = os.path.join(dst, f"_staging_{tag}")
    bad = []
    try:
        shutil.rmtree(longp(stage), ignore_errors=True)
        os.makedirs(longp(stage), exist_ok=True)
    except OSError as e:
        print(f"[export] 임시 폴더를 만들지 못했습니다: {e}")
        return 1
    for n in want:
        try:
            shutil.copy2(os.path.join(rep, n), longp(os.path.join(stage, n)))
        except OSError as e:
            bad.append(f"{n}({type(e).__name__})")
    copied = 0
    if not bad:
        for n in want:
            try:
                os.replace(longp(os.path.join(stage, n)), longp(os.path.join(dst, n)))
                copied += 1
            except OSError as e:          # 대상이 잠겨 있으면 여기서 걸린다
                bad.append(f"{n}({type(e).__name__})")
                break
    shutil.rmtree(longp(stage), ignore_errors=True)
    if bad:
        print(f"[export] 내보내기 취소 — 복사 실패: {', '.join(bad[:3])}")
        print("         공유폴더의 그 파일이 Excel 등에서 열려 있거나 읽기전용입니다.")
        print("         닫고 다시 실행하세요 (공유폴더는 이전 결과 그대로 유지).")
        return 1
    if copied == 0:
        # 해당 기간 산출물이 하나도 없으면(날짜 오타 등) member.json 을 덮어쓰지 않는다
        print(f"[export] {tag} 산출물이 없습니다 — 기간을 확인하세요 (member.json 미갱신)")
        return 1
    meta_p = os.path.join(rep, f"mm_meta_{tag}.json")
    try:
        mj = json.load(open(meta_p, encoding="utf-8-sig")) if os.path.exists(meta_p) else {}
    except (OSError, ValueError):
        mj = {}
    try:
        with open(longp(os.path.join(dst, "member.json")), "w", encoding="utf-8") as f:
            b = mj.get("mm_basis") or {}
            member = {"owner": owner, "function": cfg.get("function", ""),
                      "period": [d0, d1], "tag": tag,
                      "total_mm": mj.get("total_mm"), "avail_mm": mj.get("avail_mm"),
                      "load_pct": mj.get("load_pct"), "worked_h": mj.get("worked_h"),
                      "signals": mj.get("signals"),
                      "absence_days": b.get("absence_days"), "overtime_h": b.get("overtime_h"),
                      "no_evidence_days": b.get("no_evidence_days"), "gap_days": b.get("gap_days")}
            # 측정 품질·산식 스냅샷은 teamup(서버 업로드)과 **같은 헬퍼**로 만든다 — 여기서 빠뜨리면
            # 공유폴더로 낸 사람만 팀 리포트의 '측정 방식·신뢰도' 열이 비어 사람 차이로 읽힌다(샘플 생성에서 실측).
            try:
                import teamup
                member.update({"anomaly_days": teamup._count(b.get("anomalies")),
                               "long_days": teamup._count(b.get("long_days")),
                               "inferred_absence_days": teamup._count(b.get("inferred_absence_days")),
                               "lunch_deducted_h": teamup._hours(b.get("lunch_deducted_h")),
                               "measure": teamup.measure_of(mj, b), "coverage": teamup.coverage_of(mj, b),
                               "cfg_used": teamup.cfg_used_of(mj, b),
                               "tool_usage": teamup.tool_usage_of(mj, b),
                               "rehours": bool(mj.get("rehours")), "dropped_h": teamup._hours(mj.get("dropped_h"))})
            except Exception as e:  # noqa: BLE001 - 스냅샷이 없어도 내보내기는 끝나야 한다
                # 무엇이 없어서 빠졌는지 함께 적는다 — 이름만 찍으면 원인을 못 찾는다(실측: 동봉 파이썬이
                # 스크립트 폴더를 sys.path 에 넣지 않아 import teamup 이 죽고, measure/coverage/
                # cfg_used/tool_usage 가 통째로 빠진 member.json 이 공유폴더로 나갔다 — 위 sys.path 참고)
                print(f"[export] 측정 스냅샷 생략({type(e).__name__}: {e}) — 팀 리포트의 '측정 방식' 열이 빈다")
            member["host"] = os.environ.get("COMPUTERNAME", "")
            member["analyzed_at"] = time.strftime("%Y-%m-%d %H:%M")
            json.dump(member, f, ensure_ascii=False, indent=1)
    except OSError as e:
        print(f"[export] member.json 쓰기 실패(잠금/권한): {e}")
        return 1
    print(f"[export] {owner} → {dst} ({copied}개 파일)")
    return 0


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, errors="replace", encoding=(
        (sys.stdout.encoding or "utf-8") if sys.stdout.isatty() else "utf-8"))  # 콘솔(bat)=콘솔 코드페이지 · 파이프(UI)=utf-8
    sys.exit(main())
