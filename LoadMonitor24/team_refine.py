# -*- coding: utf-8 -*-
"""
team_refine.py — 팀 취합의 유사 항목을 Copilot 으로 정리한다 (팀장용, UI [유사 항목 정리] 의 실체).

인별 분석은 각자 PC에서 따로 돌기 때문에 같은 일이 다른 표기로 갈라진다
(예: '광학 설계' / '광학계 설계' / 'Optical 설계' → 취합 표에 세 줄).
이 도구는 team_report.refine_once 로 ① 규칙(확실한 표기 변형) ② Copilot 반복(≤3회) 정리를 하여
매핑을 <공유폴더>\\team_aliases.json 에 저장하고, 이어서 team_report.build(sender) 로
계열·세부업무·후보·과제분류 캐시를 Copilot 으로 채운 뒤 aggregate.py 를 돌려 정적 리포트
(team_report.html·team_agentic.html·팀 통합 보고서)까지 새 매핑으로 맞춘다.
원본(인별 파일)은 수정하지 않는다 — 매핑만 얹으므로 언제든 삭제해 되돌릴 수 있다.

  python team_refine.py [공유폴더]        # 생략 시 config.teamShareDir → 이 PC 의 teamdata
출력 마지막 줄 JSON: {"ok","groups","aliases","members","rounds","detail":[...],"dropped",
                      "share","used","hint"?,"full_report"}
"""
import io
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "core"))
sys.path.insert(0, ROOT)

from team_report import build_prompt  # noqa: E402,F401  (옛 호출자 호환 — 프롬프트는 team_report 가 소유)


def scan(share):
    r"""그 폴더가 '취합 폴더'로 보이는지 — 하위 폴더 수와 member.json 유무.
    '인원이 없다'만 말하면 사용자가 무엇을 고쳐야 할지 알 수 없다(실측 제보)."""
    try:
        subs = [n for n in sorted(os.listdir(share)) if os.path.isdir(os.path.join(share, n))]
    except OSError:
        return {"folders": 0, "with_member": 0, "missing": []}
    miss = [n for n in subs if not os.path.exists(os.path.join(share, n, "member.json"))]
    return {"folders": len(subs), "with_member": len(subs) - len(miss), "missing": miss[:5]}


def main():
    import judge
    import team_report
    from aggregate import load_members
    share = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else ""
    if not share:
        try:
            cfg = json.load(open(os.path.join(ROOT, "config", "config.json"),
                                 encoding="utf-8-sig"))
            share = (cfg.get("teamShareDir") or "").strip()
        except (OSError, ValueError):
            share = ""
    used = "설정"
    if (not share or not os.path.isdir(share)):
        # 이 PC 에서 팀 서버를 돌려 받았으면 결과는 teamdata\ 에 있다 — 그쪽을 자동으로 본다
        td = os.path.join(ROOT, "teamdata")
        if os.path.isdir(td) and scan(td)["with_member"]:
            share, used = td, "이 PC 의 teamdata"
            print(f"[정리] 공유폴더가 설정되지 않아 {td} 를 사용합니다")
    if not share or not os.path.isdir(share):
        print("[정리] 공유폴더 없음")
        print(json.dumps({"ok": False, "error": "no share",
                          "hint": "팀 공유폴더를 지정하세요 — 팀 취합 화면 위쪽 [팀 공유폴더] 칸에 "
                                  "취합 폴더 경로를 넣고 저장하면 됩니다. 이 PC 에서 팀 서버를 "
                                  "돌렸다면 LoadMonitor24" + os.sep + "teamdata 를 넣으세요."},
                         ensure_ascii=False))
        return 1
    members = load_members(share)
    if not members:
        sc = scan(share)
        hint = (f"{share} 에서 인원을 찾지 못했습니다 — 하위 폴더 {sc['folders']}개 중 "
                f"member.json 이 있는 폴더는 {sc['with_member']}개입니다. "
                "구조는 <취합폴더>" + os.sep + "<이름>" + os.sep + "member.json 이어야 합니다"
                + (f" (없는 폴더: {', '.join(sc['missing'])})" if sc["missing"] else "")
                + ". 파일만 복사하지 말고 각자 화면의 [공유폴더로 저장]을 쓰면 member.json 까지 만들어집니다.")
        print("[정리] 취합할 인원이 없습니다 — " + hint)
        print(json.dumps({"ok": False, "error": "no members", "share": share,
                          "hint": hint, **sc}, ensure_ascii=False))
        return 1

    # Copilot 은 UI 버튼 경로(여기)에서만 — 팀 서버 자동 취합은 캐시만 적용한다
    sender = None if os.environ.get("LM_NO_COPILOT") else judge.copilot_send
    print(f"[정리] 인원 {len(members)}명 — 규칙 정리 + Copilot 정리(최대 3회, 왕복당 수십 초)")
    r = team_report.refine_once(share, sender)
    if not r.get("ok"):
        print(json.dumps({**r, "used": used}, ensure_ascii=False))
        return 1
    print(f"[정리] {r.get('groups', 0)}개 그룹 통합 → {os.path.join(share, team_report.ALIAS_FILE)}")
    for g in (r.get("detail") or [])[:8]:
        print("   " + g)

    # 계열·세부업무·후보·과제분류 캐시를 Copilot 으로 채우며 통합 보고서를 만든다(부분 실패 허용)
    full = {}
    try:
        print("[정리] 팀 통합 보고서 — 계열·세부·후보 통합(Copilot) 후 생성")
        full = team_report.build(share, sender=sender) or {}
    except Exception as e:  # noqa: BLE001 - 보고서 실패가 정리 결과를 잃게 하지 않는다
        print(f"[정리] 통합 보고서 생성 실패({type(e).__name__}: {e}) — 정리 결과는 저장됐습니다")
    # 정적 리포트(team_report.html·team_agentic.html)도 새 매핑으로 — 서버 자동 취합과 같은 경로
    try:
        subprocess.run([sys.executable, os.path.join(ROOT, "aggregate.py"), share],
                       capture_output=True, timeout=180, cwd=ROOT,
                       env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    except (subprocess.SubprocessError, OSError) as e:
        print(f"[정리] 정적 리포트 동기화 실패({type(e).__name__}) — 팀 화면에는 이미 반영됐습니다")
    print(json.dumps({**r, "used": used, "full_report": full.get("full", ""),
                      "full_v3": full.get("v3", "")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, errors="replace", encoding=(
        (sys.stdout.encoding or "utf-8") if sys.stdout.isatty() else "utf-8"))  # 콘솔(bat)=콘솔 코드페이지 · 파이프(UI)=utf-8
    sys.exit(main())
