# -*- coding: utf-8 -*-
r"""홈 화면 API(R §5.1 · §5.7 · §5.8 · CH-H01·CH-H02) — ``GET /api/home`` · ``GET /api/next-actions``.

    GET /api/home          → HomeModel(R §5.1.5): pc · collect · coverage · reason_text · matrix · next_actions · analysis · team
    GET /api/next-actions  → [NextAction](R §5.7 — lm27.ui.nextactions)

이 모듈은 수집·분석 화면이 함께 쓰는 읽기 도우미(PC × 출처 능력 표·커버리지 합성·사유 문구)도 둔다.
  · 능력 표(RPT-42): 칸 값 = pc.json ``capabilities.<키>.verdict``(판정은 ``lm27.bundle.pcreg.verdict`` 하나 — 여기서 다시 계산하지
    않는다). PC 역할에 해당하지 않으면 ``해당 없음``(측정하지 않은 칸을 '불가'로 그리지 않는다), pc.json 에 키가 없으면 ``미확인``.
  · 커버리지: ``lm27.collect.ledger.composite``(출처 중 최선 값 — Copilot zero_ok 예외 포함, C §5.3).
  · 사유 문구: ``lm27.report.vocab.REASON_UI``(R §5.8 단일원 — 화면은 표를 복제하지 않는다).
모든 읽기는 ``lm27.paths`` 와 각 명세의 로더로만 한다(G-R10). 응답에 원문·경로·주소 0.
"""
from __future__ import annotations

from datetime import date, timedelta

__all__ = ["AXES", "MATRIX_COLS", "ROUTES", "applies", "coverage_days", "matrix", "reason_texts", "this_pc"]

AXES = ("mail_in", "mail_out", "cal", "teams", "pc")
AXIS_KO = {"mail_in": "메일 받음", "mail_out": "메일 보냄", "cal": "일정", "teams": "팀즈", "pc": "PC"}
_ALL = None
_BACKFILL = ("account_backfill", "copilot")
# (키, 열 묶음, 열 이름, 해당 역할 — None = 모든 PC) — R §5.1.3
MATRIX_COLS = (
    ("mail.com", "메일", "Outlook 앱", ("mail_local",)), ("mail.index", "메일", "검색 색인", ("mail_local",)),
    ("mail.owa", "메일", "Outlook 웹", ("account_backfill",)), ("mail.copilot", "메일", "Copilot 조회", ("copilot",)),
    ("mail.import", "메일", "반입 파일", _ALL),
    ("cal.com", "일정", "Outlook 앱", ("mail_local",)), ("cal.index", "일정", "검색 색인", ("mail_local",)),
    ("cal.owa", "일정", "Outlook 웹", ("account_backfill",)), ("cal.import", "일정", "반입 파일", _ALL),
    ("teams.uia", "팀즈", "팀즈 창 읽기", ("teams_window",)), ("teams.web", "팀즈", "팀즈 웹", ("account_backfill",)),
    ("teams.copilot", "팀즈", "Copilot 조회", ("copilot",)),
    ("pc.sampler", "PC", "사용 기록기", ("pc_usage",)), ("pc.events", "PC", "이벤트 로그", ("pc_usage",)),
    ("pc.files", "PC", "폴더 파일", ("pc_usage",)), ("pc.mru", "PC", "Office 최근 문서", ("pc_usage",)),
    ("pc.recent", "PC", "최근 항목", ("pc_usage",)), ("pc.git", "PC", "git", ("pc_usage",)),
    ("pc.compute", "PC", "연산 감지", ("pc_usage",)),
    ("env", "환경", "실행 환경", _ALL), ("edge_cdp_policy", "환경", "Edge 자동화 정책", _BACKFILL),
    ("web_login", "환경", "웹 로그인", _BACKFILL), ("copilot_connector", "환경", "Copilot 커넥터", _BACKFILL),
    ("copilot_env", "환경", "Copilot 등급·모드", _BACKFILL), ("bundle_location", "환경", "번들 위치", _ALL),
    ("team_server_reach", "환경", "팀 서버 도달", _ALL),
)
SRC_NAMES = {"mail.com": "Outlook 앱(메일)", "mail.index": "검색 색인(메일)", "mail.owa": "Outlook 웹(메일)",
             "mail.copilot": "Copilot 조회(메일)", "mail.import": "반입 파일(메일)", "cal.com": "Outlook 앱(일정)",
             "cal.index": "검색 색인(일정)", "cal.owa": "Outlook 웹(일정)", "cal.copilot": "Copilot 조회(일정)",
             "cal.import": "반입 파일(일정)", "teams.uia": "팀즈 창 읽기", "teams.web": "팀즈 웹",
             "teams.copilot": "Copilot 조회(팀즈)", "pc.sampler": "사용 기록기", "pc.events": "이벤트 로그",
             "pc.files": "폴더 파일", "pc.mru": "Office 최근 문서", "pc.recent": "최근 항목", "pc.git": "git",
             "pc.compute": "연산 감지", "manual": "수동 기록"}
OK_STATES = frozenset({"ok", "zero_ok", "partial"})
_HIST_OF = {"ok": "ok", "fail": "fail", "transport_fail": "transport_fail", "unknown": "unknown"}
HIST_N = 10


# ───────────────────────────── 공용 도우미 ─────────────────────────────
def reason_texts(codes) -> dict:
    """사유 코드 → 화면 문장(R §5.8 ``REASON_UI`` — 모르는 코드는 '<코드> · 다음 수집에서 다시 확인합니다')."""
    from lm27.report.vocab import reason_text
    return {c: reason_text(c)[1] for c in sorted({str(x) for x in codes if isinstance(x, str) and x})}


def reason_shorts(codes) -> dict:
    from lm27.report.vocab import reason_short
    return {c: reason_short(c) for c in sorted({str(x) for x in codes if isinstance(x, str) and x})}


def this_pc(app) -> tuple[str | None, dict]:
    """(이 PC 의 pc_id, pc.json) — 번들이 아직 없으면 (pc_id 또는 None, {})."""
    from lm27.bundle import loader, pcreg
    try:
        ident = app.deps.identify()
    except Exception:                                    # 식별 실패(드문 경우) — 화면은 '이 PC 정보 없음'
        return None, {}
    try:
        pc = pcreg.load_pc(loader.pc_dir_of(app.paths, ident.pc_id)) or {}
    except (OSError, ValueError):
        pc = {}
    return ident.pc_id, pc


def all_pcs(app) -> list:
    from lm27.bundle import pcreg
    try:
        return pcreg.load_all_pcs(app.paths)
    except (OSError, ValueError):
        return []


def pc_label(pc: dict) -> str:
    return str(pc.get("label_user") or pc.get("label_auto") or "PC")


def applies(key: str, roles) -> bool:
    """그 능력 칸이 이 PC 역할에 해당하는가(R §5.1.3 표)."""
    want = next((c[3] for c in MATRIX_COLS if c[0] == key), _ALL)
    if want is None:
        return True
    rs = set(roles or ())
    return any(r in rs for r in want)


def _summary(value) -> str:
    """측정값 요약(숫자만 — 예 'n 812 · days 30'). 글자 값(원문 가능)은 싣지 않는다."""
    if not isinstance(value, dict):
        return ""
    parts = []
    for k in sorted(value):
        v = value[k]
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            continue
        parts.append(f"{k} {v}")
        if len(parts) >= 3:
            break
    return " · ".join(parts)


def matrix_cell(pc: dict, key: str) -> dict:
    roles = pc.get("roles") or ()
    if not applies(key, roles):
        return {"verdict": "해당 없음", "applies": False}
    ent = (pc.get("capabilities") or {}).get(key)
    if not isinstance(ent, dict):
        return {"verdict": "미확인", "applies": True, "reasons": [], "hist": []}
    hist = [h for h in ent.get("history") or () if isinstance(h, dict)]
    v = ent.get("verdict")
    out = {"verdict": v if v in ("가능", "불가(잠정)", "불가(확정)", "미확인") else "미확인", "applies": True,
           "reasons": sorted({str(r) for r in ent.get("reasons") or () if isinstance(r, str)}),
           "hist": [_HIST_OF.get(h.get("status"), "unknown") for h in hist[-HIST_N:]],
           "last": str(hist[-1].get("date")) if hist else None}
    s = _summary(ent.get("value"))
    if s:
        out["summary"] = s
    return out


def effective_roles(pc: dict, pcs: list, cfg) -> list:
    """그 PC 에서 실제로 도는 역할(수집 계획과 같은 계산 — ``lm27.collect.plan.pc_roles``). pc.json ``roles`` 는 바탕일 뿐이라
    설정(``collect.webEverywhere``·``collect.backfillPc``)으로 더하고 빼는 역할(웹 경로 등)이 빠진다. 설정이 없으면 바탕 그대로."""
    base = [str(r) for r in pc.get("roles") or () if isinstance(r, str)]
    if cfg is None:
        return sorted(base)
    try:
        from lm27.collect import plan
        return list(plan.pc_roles(pc, pcs=[p for p in pcs if isinstance(p, dict)], cfg=cfg))
    except Exception:                                    # 계산 실패(설정 깨짐 등) — 바탕 역할로
        return sorted(base)


def matrix(pcs: list, this_id: str | None, comp: dict | None = None, today: date | None = None, cfg=None) -> dict:
    """CH-H02 PC × 출처 능력 표 + 계정 합성 행 + 설명 문장(R §5.1.3). ``cfg`` 가 있으면 역할은 실제로 도는 역할."""
    cols = [{"key": k, "group": g, "label": lb} for k, g, lb, _r in MATRIX_COLS]
    rows, codes = [], set()
    by_id = {p.get("pc_id"): dict(p, roles=effective_roles(p, pcs, cfg)) for p in pcs if isinstance(p, dict)}
    order = sorted(by_id.values(), key=lambda p: (p.get("pc_id") != this_id, pc_label(p), str(p.get("pc_id"))))
    explain = []
    for pc in order:
        cells = {k: matrix_cell(pc, k) for k, _g, _l, _r in MATRIX_COLS}
        for k, c in cells.items():
            codes.update(c.get("reasons") or ())
            if c.get("verdict") in ("불가(잠정)", "불가(확정)") and c.get("reasons"):
                from lm27.report.vocab import reason_text
                col = next(x for x in MATRIX_COLS if x[0] == k)
                explain.append(f"{pc_label(pc)} 의 {col[2]}({col[1]}): {reason_text(c['reasons'][0])[1]}")
        rows.append({"pc": pc_label(pc), "pc_id_tail": str(pc.get("pc_id") or "")[-4:], "kind": pc.get("kind"),
                     "this": pc.get("pc_id") == this_id, "roles": sorted(str(r) for r in pc.get("roles") or ()),
                     "cells": cells})
    account = []
    if comp:
        labels = {p.get("pc_id"): pc_label(p) for p in pcs if isinstance(p, dict)}
        for ax in ("mail_in", "mail_out", "cal", "teams"):
            r, best = axis_ratio(comp, ax, today)
            account.append({"axis": ax, "axis_ko": AXIS_KO[ax], "ratio30": r,
                            "best": [f"{s}@{labels.get(pc, '다른 PC')}" for s, pc in best]})
    return {"cols": cols, "rows": rows, "account": account, "explain": explain[:20], "reasons": sorted(codes)}


# ───────────────────────────── 커버리지 ─────────────────────────────
def _calendar(app):
    try:
        from lm27.time.calendar import load_calendar
        return load_calendar(app.paths)
    except Exception:                                    # 달력 파일이 없거나 깨짐 — 평일 규칙만으로(공휴일 표시 없음)
        return None


def _hol(cal, d: date) -> bool:
    if cal is None:
        return False
    try:
        return bool(cal.is_holiday(d))
    except Exception:                                    # 달력에 없는 해 — 공휴일 표시 없음
        return False


def load_composite(app, cells=None) -> tuple[dict, list]:
    """(합성 {(date, axis): {status, reasons, srcs}}, 원 셀 목록)."""
    from lm27.collect import ledger
    cells = ledger.load_cells(app.paths) if cells is None else cells
    return ledger.composite(cells), cells


def coverage_days(app, d0: date, d1: date, comp=None, cells=None) -> dict:
    """CH-H01 입력(R §5.1.4) — 일자 × 축 합성 상태 + 출처별 셀 + 사유 이름. 기록 0 인 축은 not_attempted."""
    if comp is None:
        comp, cells = load_composite(app, cells)
    cal = _calendar(app)
    days, codes, srcs_seen = [], set(), set()
    d = d0
    while d <= d1:
        ds = d.isoformat()
        hol = _hol(cal, d)
        row = {"d": ds, "wd": d.weekday() < 5 and not hol, "hol": hol, "s": {}}
        why, src = {}, {}
        for ax in AXES:
            c = comp.get((ds, ax))
            st = c["status"] if c else "not_attempted"
            row["s"][ax] = st
            if c and st not in OK_STATES and c.get("reasons"):
                why[ax] = list(c["reasons"])
                codes.update(c["reasons"])
            if c and c.get("srcs"):
                src[ax] = [[s, v] for s, v in sorted(c["srcs"].items())]
                srcs_seen.update(c["srcs"])
        if why:
            row["why"] = why
        if src:
            row["src"] = src
        days.append(row)
        d += timedelta(days=1)
    return {"axes": list(AXES), "days": days, "reasonText": reason_shorts(codes),
            "srcNames": {s: SRC_NAMES.get(s, s) for s in sorted(srcs_seen)}}


def axis_ratio(comp: dict, axis: str, today: date | None = None, n: int = 30) -> tuple:
    """최근 n 근무일(평일) 중 합성 ok·zero_ok·partial 비율과 그 축의 최선 출처들([(src, pc_id)])."""
    today = today or date.today()
    days, d = [], today
    while len(days) < n and (today - d).days < 120:
        if d.weekday() < 5:
            days.append(d.isoformat())
        d -= timedelta(days=1)
    if not days:
        return None, []
    ok = sum(1 for ds in days if (comp.get((ds, axis)) or {}).get("status") in OK_STATES)
    from lm27.report.fmt import ratio
    srcs: dict = {}
    for ds in days:
        for s, st in ((comp.get((ds, axis)) or {}).get("srcs") or {}).items():
            if st in OK_STATES:
                srcs[s] = srcs.get(s, 0) + 1
    best = [(s, None) for s, _n in sorted(srcs.items(), key=lambda kv: (-kv[1], kv[0]))[:2]]
    return ratio(ok, len(days), 2), best


def _last_gap(comp: dict, today: date) -> dict | None:
    for k in range(0, 60):
        d = (today - timedelta(days=k))
        if d.weekday() >= 5:
            continue
        ds = d.isoformat()
        for ax in AXES:
            c = comp.get((ds, ax))
            if c and c["status"] not in OK_STATES and c["status"] != "not_attempted":
                return {"d": ds, "axis": ax, "reasons": list(c.get("reasons") or ())}
    return None


# ───────────────────────────── 처리기 ─────────────────────────────
def _team_brief(app) -> dict:
    from lm27.ui.api_team import registry_view
    out = {"registry": None, "outbox": {"pending": 0, "approved": 0, "failed": 0, "sent": 0}, "reach": None}
    _reg, st = registry_view(app)                        # 팀 레지스트리는 분류 명세 적재기로만 읽는다(L-22)
    if st is not None and getattr(st, "source", "builtin") != "builtin":
        out["registry"] = {"version": getattr(st, "version", None), "fetched_at": getattr(st, "fetched_at", None)}
    try:
        from lm27.team import queue
        for it in queue.list_items(paths=app.paths):
            st = getattr(it, "state", None) or (it.meta or {}).get("state")
            meta = getattr(it, "meta", {}) or {}
            if st in ("sent", "delivered"):
                out["outbox"]["sent"] += 1
            elif st == "failed":
                out["outbox"]["failed"] += 1
            elif st in ("pending", "retry_wait", "auth_needed", "wrong_server", "sending", "exported"):
                out["outbox"]["approved" if meta.get("approved") else "pending"] += 1
    except Exception:                                    # 대기열 모듈·폴더가 없음 — 0건
        pass
    return out


def _reach(pc: dict) -> dict | None:
    ent = (pc.get("capabilities") or {}).get("team_server_reach")
    if not isinstance(ent, dict):
        return None
    v = ent.get("value") if isinstance(ent.get("value"), dict) else {}
    res = str(v.get("result") or "")
    from lm27.team.client import TEXT_KO
    return {"result": res, "target": str(v.get("target") or ""), "text_ko": TEXT_KO.get(res, "")}


def _analysis_brief(app) -> dict | None:
    from lm27.ui import api_report
    cur = api_report.current(app)
    if not cur:
        return None
    model = api_report.model_or_none(app, cur["run_id"], "full")
    if not model:
        return {"run_id": cur["run_id"], "month": None, "kpi": None}
    months = [m for m in model.get("months") or () if isinstance(m, dict) and m.get("env_min")]
    if not months:
        return {"run_id": cur["run_id"], "month": None, "kpi": None}
    m = months[-1]
    from lm27.report import fmt
    q = m.get("quality") if isinstance(m.get("quality"), dict) else {}
    kpi = {"mm": fmt.fmt_mm(int(m.get("env_min") or 0), int(m.get("denom_min") or 0)),
           "load_pct": fmt.fmt_pct(int(m.get("env_min") or 0), int(m.get("avail_min") or 0)),
           "ot_h": fmt.fmt_h1(int(m.get("overtime_window_min") or 0)),
           "unattr_pct": fmt.fmt_pct(int(m.get("unattr_min") or 0), int(m.get("env_min") or 0)),
           "quality": str(q.get("grade") or "")}
    return {"run_id": cur["run_id"], "month": m.get("m"), "kpi": kpi}


def _collect_brief(app, pcs: list) -> dict:
    from lm27.ui import api_collect
    last = api_collect.last_collect(app)
    stale = sum(1 for p in pcs if api_collect.pc_stale(app, p))
    return {"last": last, "pcs": {"total": len(pcs), "ok": len(pcs) - stale, "stale": stale}}


def get_home(app, req):
    from lm27.ui import nextactions
    cfg = app.cfg()
    pc_id, pc = this_pc(app)
    pcs = all_pcs(app)
    today = app.deps.now().date()
    try:
        comp = load_composite(app)[0]
    except Exception:                                    # 원장 없음·깨짐 — 그 카드만 빈 상태
        comp = {}
    ndays = int(cfg["ui.homeCoverageDays"])
    d0 = today - timedelta(days=max(1, ndays) - 1)
    cov = {"from": d0.isoformat(), "to": today.isoformat(),
           "ratio30": {ax: axis_ratio(comp, ax, today)[0] for ax in AXES}, "last_gap": _last_gap(comp, today)}
    mx = matrix(pcs, pc_id, comp, today, cfg=cfg)
    codes = set(mx.pop("reasons"))
    if cov["last_gap"]:
        codes.update(cov["last_gap"]["reasons"])
    team = _team_brief(app)
    team["reach"] = _reach(pc)
    out = {"pc": {"label": pc_label(pc) if pc else "", "kind": pc.get("kind") if pc else None,
                  "roles": effective_roles(pc, pcs, cfg) if pc else [], "is_this": True},
           "collect": _collect_brief(app, pcs), "coverage": cov, "matrix": mx,
           "next_actions": [a.as_dict() for a in nextactions.next_actions(nextactions.gather(app))][:8],
           "analysis": _analysis_brief(app), "team": team}
    out["reason_text"] = reason_texts(codes)
    return out


def get_next_actions(app, req):
    from lm27.ui import nextactions
    return [a.as_dict() for a in nextactions.next_actions(nextactions.gather(app))]


ROUTES = (("GET", r"/api/home", get_home),
          ("GET", r"/api/next-actions", get_next_actions))
