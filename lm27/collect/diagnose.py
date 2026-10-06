# -*- coding: utf-8 -*-
r"""진단 리포트 모델(계약 §2.5 · C §9) — PC 카드 · 출처 매트릭스 · 사유 분포. 그 PC 화면에서 끝난다(반출 없음).

  · 입력: pc.json(능력 기록·verdict — ``lm27.bundle.pcreg``), 커버리지 원장(``lm27.collect.ledger``), 빈칸 계획
    (``lm27.collect.todo``), 마지막 수집 실행의 단계 결과(``lm27.collect.stage_result``). 모두 숫자·열거·사유 코드뿐이다.
  · PC 카드: 탐침 숫자(지평선·색인 건수·UIA 줄 수 등 — 탐침이 이미 형식 검사한 값)와 사유, 그 PC 에서 할 수 있는 조치 문장
    ('이 날은 R-HORIZON → 백필 PC 의 OWA 가 채울 예정' 같은). 원문·창 제목·호스트 이름(``host_display``)은 싣지 않는다.
  · 출처 매트릭스: (날짜 × 축) 합성 상태 + 출처별 상태(C §5.1 열거). 미관측은 0h 가 아니다(T-09) — 화면이 색·배지로 가른다.
  · 사유 분포: 사유 코드별 건수·분류·'확정 가능' 여부 — '되는 사람/안 되는 사람'을 숫자로 설명한다(이름 없이).
    구조적 결손(어떤 축이 창 전체에서 한 번도 관측되지 않음)은 경고로 올린다.
  · 문구 규칙(C §9): '개발자에게 보내라'·재설치 권유 문구를 쓰지 않는다. 사람이 할 일은 로그인 1회·대화상자 닫기 정도다.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, datetime

from lm27.collect import ledger, rcmap, todo
from lm27.collect import stage_result as sr

__all__ = ["REASON_ACTIONS", "SCHEMA", "diagnose_model", "pc_card", "reason_distribution", "source_matrix"]

SCHEMA = "lm27.diagnose/1"
CAPS_ORDER = ("env", "mail.com", "cal.com", "mail.index", "cal.index", "edge_cdp_policy", "teams.uia", "pc.sampler",
              "pc.events", "pc.files", "pc.mru", "pc.recent", "pc.git", "mail.owa", "cal.owa", "teams.web",
              "mail.copilot", "teams.copilot", "cal.copilot", "bundle_location", "team_server_reach")
# 사유 → 그 PC 에서 할 수 있는 조치(사람 조작은 로그인·대화상자 정도 — 다른 경로가 빈칸을 채운다)
REASON_ACTIONS = {
    "R-NEWOL": "클래식 Outlook 이 없는 새 Outlook 전용 PC 입니다 — 메일·일정은 Outlook 웹 경로가 채웁니다(분석용 Edge 창에서 회사 계정 1회 로그인)",
    "R-NOPROF": "Outlook 에 메일 계정이 설정돼 있지 않습니다 — 메일·일정은 Outlook 웹 경로가 채웁니다(분석용 Edge 창에서 회사 계정 1회 로그인)",
    "R-WIZARD": "Outlook 시작 마법사 위험으로 COM 을 건너뜁니다 — 색인·Outlook 웹 경로가 채웁니다",
    "R-DIALOG": "Outlook 에 대화상자가 열려 있습니다 — 닫으면 다음 수집에서 다시 읽습니다",
    "R-CLM": "실행 정책이 막고 있습니다 — 되는 경로만 씁니다",
    "R-APPLOCKER": "실행 차단 정책이 있습니다 — 되는 경로만 씁니다",
    "R-OMG": "보호 열(주소·수신자)은 읽지 않습니다 — 나머지 열은 그대로 저장합니다",
    "R-ELEV": "관리자 권한 창과 권한이 달라 COM 을 쓸 수 없습니다 — 일반 권한으로 실행하면 됩니다",
    "R-ONLINE": "Outlook 온라인 모드라 로컬 색인이 비었습니다 — 백필 PC 의 OWA 가 채울 예정입니다",
    "R-HORIZON": "동기화 기간 밖의 날입니다 — 백필 PC 의 OWA 가 채울 예정입니다",
    "R-SUBFOLDER": "기본 폴더 밖 메일이 많습니다 — 색인으로 교차검증합니다",
    "R-STALE": "Outlook 캐시가 오래됐습니다 — Outlook 을 열어 동기화하면 다음 수집이 읽습니다",
    "R-NOIDX": "Windows 색인이 꺼져 있습니다 — COM·OWA 가 채웁니다",
    "R-IDXPOLICY": "색인 정책이 Outlook 을 막습니다 — COM·OWA 가 채웁니다",
    "R-IDXPAUSED": "색인이 일시정지·재구축 중입니다 — 다음 수집에서 다시 읽습니다",
    "R-EDGEPOL": "Edge 원격 디버깅 정책이 막고 있습니다 — 반입 폴더·수동 붙여넣기 경로를 씁니다",
    "R-LOGIN": "웹 로그인이 필요합니다 — 전용 창에서 한 번 로그인하면 이어서 읽습니다",
    "R-CA": "조건부 액세스가 막고 있습니다 — 다른 경로가 채웁니다",
    "R-NOLIC": "코파일럿 업무 데이터 라이선스가 없습니다 — 증인 조회를 건너뜁니다",
    "R-NOCONN": "코파일럿 조회 커넥터가 없습니다 — 증인 조회를 건너뜁니다",
    "R-UIAEMPTY": "팀즈 창이 숨겨져 있었습니다 — 백필 PC 의 팀즈 웹이 채울 예정입니다",
    "R-UIAELEV": "관리자 권한 팀즈 창은 읽을 수 없습니다 — 팀즈 웹이 채웁니다",
    "R-NOADDR": "내 주소·표시명을 확정하지 못했습니다 — 수신 구분은 미상으로 둡니다",
    "R-NOEVT": "이벤트 로그를 읽을 권한이 없습니다 — 샘플러 기록으로만 판단합니다",
    "R-RECURINC": "반복 일정을 일부만 펼쳤습니다 — 백필 PC 의 OWA 주 보기가 보완합니다",
    "R-NOAPP": "대상 프로그램이 설치되어 있지 않습니다",
    "R-CAP": "상한에 닿아 일부만 읽었습니다 — 다른 경로가 나머지를 채웁니다",
    "R-BUDGET": "시간 예산에 닿았습니다 — 다음 수집이 이어서 읽습니다",
    "R-TRANSPORT": "일시적인 실행·연결 문제입니다 — 다음 수집에서 다시 시도합니다('불가' 아님)",
    "R-COM-BUSY": "Outlook 이 바빴습니다 — 다음 수집에서 다시 시도합니다",
    "R-COMGAP": "색인 건수가 COM 보다 많습니다 — COM 누락 의심(하위 폴더·프로필)",
    "R-WEBSEL": "웹 화면 구조가 바뀌어 읽지 못했습니다 — 다른 경로가 채웁니다",
    "R-LISTVIRT": "대화 목록을 끝까지 내리지 못했습니다 — 다음 수집이 이어서 읽습니다",
    "R-ROOMGONE": "일부 대화방을 다시 찾지 못했습니다 — 다음 수집이 이어서 읽습니다",
    "R-NOGIT": "git 을 찾지 못했습니다",
    "R-MRUEMPTY": "최근 문서 기록이 비어 있습니다",
    "R-RECENTPOLICY": "최근 문서 기록 정책이 막고 있습니다 — 파일 스캔으로 보완합니다",
    "R-STUCK": "입력 유휴가 고착된 것으로 보입니다 — 품질 표시만 합니다",
    "R-SAMPLER-ZOMBIE": "기록 에이전트가 살아 있지만 쓰지 않습니다 — 다음 수집이 자동 복구합니다",
    "R-RULESMISMATCH": "정제기 판이 달라 에이전트를 자동으로 판 올림합니다",
    "R-NOKEY": "에이전트 키가 없어 자동 복구합니다",
    "R-BUNDLE-READONLY": "번들 폴더에 쓸 수 없습니다 — 쓸 수 있는 위치로 옮기면 이어서 기록합니다",
    "R-BUNDLE-ONEDRIVE": "번들이 동기화 폴더 안에 있습니다 — 동기화 충돌에 주의하세요",
    "R-BUNDLE-NETWORK": "번들이 네트워크 드라이브에 있습니다 — 잠금이 불안정할 수 있습니다",
    "R-BUNDLE-LOWSPACE": "디스크 여유 공간이 적습니다",
    "R-BUNDLE-LONGPATH": "번들 경로가 깁니다 — 짧은 위치를 권합니다",
    "R-TEAM-TIMEOUT": "팀 서버가 응답하지 않습니다 — 묶음은 대기열에 남아 다음에 보냅니다",
    "R-TEAM-REFUSED": "팀 서버가 꺼져 있거나 포트가 다릅니다 — 묶음은 대기열에 남습니다",
    "R-TEAM-LM24": "그 주소에는 이전 판 팀 서버가 응답합니다 — 보내지 않습니다",
    "R-TEAM-OTHERAPP": "그 주소에는 다른 프로그램이 응답합니다 — 보내지 않습니다",
    "R-TEAM-VERSION": "팀 서버 판이 맞지 않습니다 — 보내지 않습니다",
}
_NUM_TYPES = (int, float, bool)


def _numbers(value, depth=0) -> dict:
    """탐침 값에서 숫자·불리언·짧은 열거만(화면 카드용)."""
    out = {}
    if not isinstance(value, dict) or depth > 2:
        return out
    for k, v in sorted(value.items()):
        if isinstance(v, _NUM_TYPES) or v is None or (isinstance(v, str) and len(v) <= 40):
            out[k] = v
        elif isinstance(v, dict):
            sub = _numbers(v, depth + 1)
            if sub:
                out[k] = sub
    return out


def _actions(codes) -> list:
    return [{"reason": c, "text_ko": REASON_ACTIONS[c]} for c in sorted(set(codes)) if c in REASON_ACTIONS]


def pc_card(pc: dict, cells=(), todos=()) -> dict:
    """PC 카드 하나 — 식별·kind·역할·방문, 능력별 상태·verdict·숫자, 조치 문장, 이 PC 의 빈칸 작업 수."""
    caps = pc.get("capabilities") if isinstance(pc.get("capabilities"), dict) else {}
    rows, codes = [], set()
    for key in sorted(caps, key=lambda k: (CAPS_ORDER.index(k) if k in CAPS_ORDER else len(CAPS_ORDER), k)):
        ent = caps[key] if isinstance(caps[key], dict) else {}
        hist = ent.get("history") if isinstance(ent.get("history"), list) else []
        last = hist[-1] if hist and isinstance(hist[-1], dict) else {}
        rs = [r for r in ent.get("reasons") or () if rcmap.is_reason(r)]
        codes.update(rs)
        rows.append({"key": key, "ok": ent.get("ok"), "status": last.get("status"), "verdict": ent.get("verdict"),
                     "reasons": sorted(rs), "date": last.get("date"), "numbers": _numbers(ent.get("value"))})
    pid = pc.get("pc_id")
    mine = [c for c in cells or () if c.get("pc_id") == pid and c.get("status") in rcmap.UNOBSERVED]
    for c in mine:
        codes.update(r for r in c.get("reasons") or () if rcmap.is_reason(r))
    installs = [i for i in pc.get("installs") or () if isinstance(i, dict)]
    st = Counter(str(_d(t).get("state")) for t in todos or () if _d(t).get("want_pc") == pid)
    return {"pc_id": pid, "label_auto": pc.get("label_auto") or "", "label_user": pc.get("label_user") or "",
            "kind": pc.get("kind"), "roles": sorted(r for r in pc.get("roles") or () if isinstance(r, str)),
            "first_seen": pc.get("first_seen"), "last_seen": pc.get("last_seen"),
            "agent": {"installs": len(installs), "impl": installs[-1].get("impl") if installs else None},
            "flags": sorted(f for f in pc.get("flags") or () if isinstance(f, str)), "caps": rows,
            "unobserved_cells": len(mine), "todos": dict(sorted(st.items())), "actions": _actions(codes)}


def _d(t) -> dict:
    return t.to_dict() if hasattr(t, "to_dict") else (t if isinstance(t, dict) else {})


def source_matrix(cells) -> dict:
    """(날짜 × 축) 합성 상태 + 출처별 상태(코파일럿 zero_ok 예외 포함 — ``ledger.composite``)."""
    comp = ledger.composite(cells)
    dates = sorted({d for d, _a in comp})
    rows = [{"date": d, "axis": a, "status": v["status"], "srcs": v["srcs"], "reasons": v["reasons"]}
            for (d, a), v in sorted(comp.items())]
    per_axis = defaultdict(Counter)
    for (_d0, a), v in comp.items():
        per_axis[a][v["status"]] += 1
    return {"axes": list(ledger.AXES), "statuses": list(ledger.STATUS_ORDER), "dates": dates, "rows": rows,
            "summary": {a: dict(sorted(per_axis[a].items())) for a in ledger.AXES if a in per_axis}}


def reason_distribution(cells, pcs) -> dict:
    """사유 코드별 건수(미관측 셀 + 능력 기록) · 분류 · 확정 가능 · 걸린 PC 수."""
    by = Counter()
    pcs_of = defaultdict(set)
    for c in cells or ():
        if c.get("status") in rcmap.UNOBSERVED or c.get("status") == "partial":
            for r in c.get("reasons") or ():
                if rcmap.is_reason(r):
                    by[r] += 1
                    pcs_of[r].add(c.get("pc_id"))
    for pc in pcs or ():
        for ent in (pc.get("capabilities") or {}).values():
            for r in (ent.get("reasons") or ()) if isinstance(ent, dict) else ():
                if rcmap.is_reason(r):
                    by[r] += 1
                    pcs_of[r].add(pc.get("pc_id"))
    codes = {r: {"count": n, "class": rcmap.reason_class(r), "confirmable": rcmap.confirmable(r),
                 "pcs": len(pcs_of[r])} for r, n in sorted(by.items())}
    classes = Counter()
    for r, n in by.items():
        classes[rcmap.reason_class(r)] += n
    return {"by_code": codes, "by_class": dict(sorted(classes.items()))}


def _last_run(paths) -> dict | None:
    runs = ledger.list_runs(paths)
    if not runs:
        return None
    rid = runs[-1]
    res = sr.read_stage_results(paths, rid)
    stages = [{"stage": k, "state": v.get("state"), "rc": v.get("rc"), "reason": v.get("reason"),
               "items_ok": v.get("items_ok"), "hint": v.get("hint")} for k, v in res.items()]
    return {"run_id": rid, "stages": stages, "rc": rcmap.collect_rc(list(res.values())) if res else None}


def diagnose_model(paths, *, cells=None, pcs=None, todos=None, now=None) -> dict:
    """계약 함수: 진단 리포트 모델(dict — 화면이 그린다). 원문 0, 숫자·열거·사유 코드·고정 문구만."""
    from lm27.bundle import pcreg
    pcs = pcreg.load_all_pcs(paths) if pcs is None else list(pcs)
    cells = ledger.load_cells(paths) if cells is None else list(cells)
    todos = todo.load_todo(paths) if todos is None else list(todos)
    u = now if isinstance(now, datetime) else datetime.now(UTC)
    matrix = source_matrix(cells)
    warnings = []
    for a in ledger.AXES:
        s = matrix["summary"].get(a) or {}
        if s and not (s.get("ok") or s.get("zero_ok")):
            warnings.append({"code": "axis_unobserved", "axis": a})
    tstate = Counter(str(_d(t).get("state")) for t in todos)
    return {"schema": SCHEMA, "generated_at": u.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "pcs": [pc_card(p, cells, todos) for p in sorted(pcs, key=lambda p: str(p.get("first_seen") or ""))],
            "matrix": matrix, "reasons": reason_distribution(cells, pcs), "todo": dict(sorted(tstate.items())),
            "last_run": _last_run(paths), "warnings": warnings}
