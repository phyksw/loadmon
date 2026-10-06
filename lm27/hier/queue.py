# -*- coding: utf-8 -*-
r"""분류 확인 질문 H01~H06(H §11.2, 계약 §6.3 · §3.15 queue.json).

- 시간 확인 큐(Q01~Q18)와 **같은 화면**에 '분류' 꼬리표로 띄우되 코드를 `H` 로 구분하고 주간 상한을 따로 센다
  (`hier.queue.maxPerWeek` — 시간 질문은 `time.queue.maxPerWeek`). 질문은 선택 사항이다 — 답이 없어도 라벨·보고서·팀 묶음은
  그대로 만든다. 다른 사용자에게 묻지 않는다(본인 화면에서만).
- H01 과제미정(미분류 또는 예약 과제 + low, 군집 투입 ≥ `hier.queue.minEffortH`) · H02 규칙·AI 충돌 · H03 새과제확인(pending 이고
  n_units ≥ 2 또는 투입 ≥ `proposalMinEffortH`) · H04 이름병합애매(질문 구간 쌍) · H05 유형애매(유형 확신 l 이고 투입 ≥
  `wtypeMinEffortH`) · H06 퇴역과제(병합 없이 퇴역한 과제 라벨, 투입 ≥ `minEffortH`).
- `qid = sha1(코드 | 군집 키(쌍은 ukey 정렬) | 핵심 근거)[:12]` — 다시 분석해도 같은 질문은 같은 ID(두 번 묻지 않는다, T-23).
- 우선순위 = (영향 투입 h + 0.01) × 가중(`hier.queue.weights`), ISO 주마다 상위 `maxPerWeek` 건.
- 행 모양은 시간 큐(`confirm_queue.json`)와 같다: `{qid, code, target, impact_min, evidence_keys, proposal, status}`.

표준 라이브러리만 쓴다. 파일을 쓰지 않는다.
"""
import hashlib
from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import date

from lm27.hier.features import default_cfg, get
from lm27.hier.names import ukey
from lm27.time.calendar import d_of

__all__ = ["CODES", "QUESTIONS", "hier_queue", "make_q", "qid_of"]

CODES = ("H01", "H02", "H03", "H04", "H05", "H06")
QUESTIONS = {   # 코드 → (이름, 묻는 것, 선택지, 응답 저장)
    "H01": ("과제미정", "어느 과제인가요?", ["후보", "영역 일반", "새 과제", "업무 아님"], "set.project"),
    "H02": ("규칙·AI충돌", "둘 중 무엇인가요?", ["규칙 과제", "AI 과제", "그 밖"], "set.project"),
    "H03": ("새과제확인", "새 과제 제안을 어떻게 할까요?", ["내 과제로 받기", "기존 과제와 같음", "거절"], "proposal"),
    "H04": ("이름병합애매", "같은 것인가요?", ["같다", "다르다"], "merge|never_pairs"),
    "H05": ("유형애매", "이 업무의 유형은?", ["DEV", "OFFICE", "FIELD", "PM", "PL", "SUPPORT", "EDU"], "set.wtype"),
    "H06": ("퇴역과제", "어느 과제로 옮길까요?", ["후보", "영역 일반", "새 과제"], "set.project"),
}
STATUS_OPEN = "open"


def qid_of(code: str, target: str, core: str = "") -> str:
    """qid = sha1(코드|대상|핵심 근거)[:12](계약 §4.1 — 분류 큐)."""
    return hashlib.sha1(f"{code}|{target}|{core}".encode()).hexdigest()[:12]


def make_q(code: str, target: str, core: str, impact_min: int, *, evidence_keys: Iterable[str] = (),
           day: date | None = None, extra: Mapping | None = None) -> dict:
    """질문 행 하나(시간 큐와 같은 모양 + proposal 에 질문 표기·선택지·날짜·후보)."""
    if code not in QUESTIONS:
        raise ValueError(f"분류 확인 질문 코드 오류 {code!r}")
    name, ask, options, answer = QUESTIONS[code]
    prop = {"title": name, "ask": ask, "options": list(options), "answer": answer, "area": "분류"}
    if day is not None:
        prop["date"] = day.isoformat()
    if extra:
        prop.update(dict(extra))
    return {"qid": qid_of(code, target, core), "code": code, "target": target, "impact_min": int(impact_min),
            "evidence_keys": sorted({str(k) for k in evidence_keys if k}), "proposal": prop, "status": STATUS_OPEN}


def _gday(g) -> date | None:
    t = int(get(g, "last_t", 0) or 0) or int(get(g, "first_t", 0) or 0)
    return d_of(t) if t else None


def hier_queue(labels: Mapping, groups: Iterable, proposals: Iterable[Mapping], conflicts: Iterable[Mapping],
               merge_asks: Iterable[Mapping], cfg=None, *, as_of: date | None = None) -> list[dict]:
    """확인 질문 목록(H §11.2). labels = {unit_id: UnitLabel}, groups = 군집, proposals = 제안 항목(사전),
    conflicts = apply 의 H02 목록, merge_asks = 질문 구간 쌍(제안·이름). 주마다 상위 maxPerWeek 건, 우선순위 순."""
    cfg = default_cfg(cfg)
    min_h = float(cfg["hier.queue.minEffortH"]) * 60
    wt_h = float(cfg["hier.queue.wtypeMinEffortH"]) * 60
    pr_h = float(cfg["hier.queue.proposalMinEffortH"]) * 60
    per_week = int(cfg["hier.queue.maxPerWeek"])
    weights = {str(k): float(v) for k, v in dict(cfg["hier.queue.weights"]).items()}
    gl = sorted(groups, key=lambda x: x.key)
    gmap = {g.key: g for g in gl}
    items: list[dict] = []
    for g in gl:
        lab = labels.get(g.rep)
        if lab is None:
            continue
        lv = get(lab, "level", "")
        proj = get(lab, "project", None)
        reserved = bool(proj) and str(proj).startswith("P-99")
        day = _gday(g)
        cands = [p for p, _s in (get(lab, "cands", ()) or ())][:3]
        if (lv == "unclassified" or (reserved and lv == "low")) and g.effort_min >= min_h:
            items.append(make_q("H01", g.key, "", g.effort_min, evidence_keys=[g.anchor], day=day,
                                extra={"cands": cands}))
        flags = set(get(lab, "flags", ()) or ())
        if "retired_project" in flags and g.effort_min >= min_h:
            items.append(make_q("H06", g.key, str(proj or ""), g.effort_min, evidence_keys=[g.anchor], day=day,
                                extra={"cands": cands, "retired": proj}))
        wconf = (get(lab, "conf", {}) or {}).get("wtype")
        if wconf == "l" and (get(lab, "src", {}) or {}).get("wtype") != "user" and g.effort_min >= wt_h:
            items.append(make_q("H05", g.key, "", g.effort_min, evidence_keys=[g.anchor], day=day,
                                extra={"current": get(lab, "wtype", "")}))
    seen_h02 = set()
    for c in sorted(conflicts, key=lambda x: (str(x.get("group")), str(x.get("unit_id")))):
        gk = str(c.get("group") or "")
        if gk in seen_h02:
            continue
        seen_h02.add(gk)
        g = gmap.get(gk)
        eff = g.effort_min if g is not None else int(c.get("effort_min") or 0)
        items.append(make_q("H02", gk, f"{c.get('rule')}|{c.get('ai')}", eff,
                            evidence_keys=[g.anchor] if g is not None else (), day=_gday(g) if g is not None else None,
                            extra={"rule": c.get("rule"), "ai": c.get("ai")}))
    for p in sorted(proposals, key=lambda x: str(x.get("proposal_id"))):
        if p.get("status") != "pending":
            continue
        n, eff = int(p.get("n_units") or 0), int(p.get("effort_min") or 0)
        if n >= 2 or eff >= pr_h:
            items.append(make_q("H03", str(p["proposal_id"]), str(p.get("ukey") or ""), eff,
                                evidence_keys=p.get("groups") or (), day=_pday(p),
                                extra={"label": p.get("label"), "domain_guess": p.get("domain_guess")}))
    for a in sorted(merge_asks, key=lambda x: (str(x.get("a")), str(x.get("b")))):
        names = a.get("names") or [a.get("a"), a.get("b")]
        pair = "|".join(sorted(ukey(str(x)) for x in names))
        eff = int(a.get("effort_min") or 0)
        if not eff:
            for gk in a.get("groups") or ():
                g = gmap.get(gk)
                eff += g.effort_min if g is not None else 0
        items.append(make_q("H04", pair, f"{a.get('a')}|{a.get('b')}", eff, evidence_keys=a.get("groups") or (),
                            extra={"a": a.get("a"), "b": a.get("b"), "names": names, "score": a.get("score")}))
    by_q: dict[str, dict] = {}
    for it in items:
        by_q.setdefault(it["qid"], it)
    week: dict[str, list[dict]] = defaultdict(list)
    for it in by_q.values():
        d = it["proposal"].get("date")
        if d:
            y, w, _ = date.fromisoformat(d).isocalendar()
        elif as_of is not None:
            y, w, _ = as_of.isocalendar()
        else:
            y, w = 0, 0
        it["proposal"]["week"] = f"{y:04d}-W{w:02d}"
        week[it["proposal"]["week"]].append(it)
    out: list[dict] = []
    for wk in sorted(week):
        lst = sorted(week[wk], key=lambda it: (-_prio(it, weights), it["qid"]))
        out.extend(lst[:per_week])
    return sorted(out, key=lambda it: (-_prio(it, weights), it["qid"]))


def _prio(it: Mapping, weights: Mapping[str, float]) -> float:
    return (it["impact_min"] / 60.0 + 0.01) * weights.get(it["code"], 0.5)


def _pday(p: Mapping) -> date | None:
    for k in ("last_at", "first_at"):
        v = p.get(k)
        if isinstance(v, str) and len(v) >= 10:
            try:
                return date.fromisoformat(v[:10])
            except ValueError:
                continue
    return None
