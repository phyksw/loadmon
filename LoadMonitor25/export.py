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
    from datetime import date
    import teamup
    from core.bundles import write_bundle
    try:
        if date.fromisoformat(d0) > date.fromisoformat(d1):
            raise ValueError("시작일이 종료일보다 늦습니다")
        if not os.path.isabs(share) or not os.path.isdir(share):
            raise ValueError("teamShareDir는 접근 가능한 절대경로여야 합니다")
        payload = teamup.make_payload(cfg, d0, d1)
        if not payload:
            raise ValueError("해당 기간 산출물이 없습니다")
        member, files = payload["member"], payload["files"]
        member.update(via="공유폴더", uploaded_at=time.strftime("%Y-%m-%d %H:%M"),
                      uploaded_from=os.environ.get("COMPUTERNAME", ""))
        dst = os.path.join(share, member["owner"])
        write_bundle(dst, member, files)
    except (OSError, ValueError, TypeError) as error:
        print(f"[export] 내보내기 실패 — 이전 결과 유지: {error}")
        return 1
    print(f"[export] {member['owner']} → {dst} ({len(files)}개 파일, 완성 묶음 게시)")
    return 0


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, errors="replace", encoding=(
        (sys.stdout.encoding or "utf-8") if sys.stdout.isatty() else "utf-8"))  # 콘솔(bat)=콘솔 코드페이지 · 파이프(UI)=utf-8
    sys.exit(main())
