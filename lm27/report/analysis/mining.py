# -*- coding: utf-8 -*-
r"""과정 마이닝 — 역할·단위업무·과제·업무 영역 수준 워크플로우(R §4.2 · §4.3 · §6.3.3 · 부록 A, 계약 §3.16 워크플로우 절).

결정적 산식만 쓴다(같은 입력이면 같은 결과 — G-R1). 단계 순서·소요·대기·병목은 프로그램이 계산하고, 코파일럿은 단계 이름·설명만
붙인다(RP3 — `apply_labels`). 시각은 로컬 분, 대기는 영업 분(R §3.2 `fmt.BizCal`).

- `collapse(items, keep=None, min_sec=600)`: 흔적 정리 — 짧은 구간 단계(minStepSec 미만) 버림, keep 밖 단계 버림, 바로 앞과
  같은 단계는 하나로(R §4.2.1 ①).
- `mine_role(units, log, cfg, *, bc, as_of_min, registry=None) -> dict | None`: 역할 업무 하나의 RoleWorkflow(R §4.2 —
  지지도·단계 상한·순서(위치 중앙값)·단계 통계·전이·대기·작업 비중·병목·역할 요약).
- `unit_workflow(unit, log, cal, *, as_of_min, min_sec=600)`: 단위업무 타임라인 재료(R §4.3.1).
- `project_workflow(project_key, units_by_role, log, cfg, *, bc, roles_wf)`: 역할 레인·역할 간 인계(R §4.3.2).
- `domain_workflow(code, units, log, roles)`: 영역(또는 사람 전체 'ALL') 묶음 구성·상위 병목(R §4.3.3).
- `handoffs(units, bc, handoff_wd, same_role=False)`: 인계 조건(선행자 하나 — 끝이 가장 늦은 것). 온톨로지 '선행함'도 같은 함수.
- `workflows(ctx) -> (wf, traces)`: 위를 모두 만든다(`wf` = 모델 `workflows` 절, traces = 서브에이전트·agentic 재료).
- `apply_labels(roles, answers, registry=None)`: workflow_label 답 반영(R §4.10.2 — 번호가 바뀐 옛 답은 같은 단계 **코드**의
  라벨을 `rule_pending` 으로).
- `role_sentences(rw, std_day_min=480)`: 역할 워크플로우 규칙 문장(R §6.3.3 — 코파일럿 없이도 항상, 최대 4문장).

설정(R §10.2): `report.mining.minStepSec` · `maxSteps` · `minSupportRatio` · `maxEdges` · `waitBottleneckMin` ·
`workBottleneckShare` · `minUnitsForBottleneck` · `handoffWd`(+ `extClassExtra` 는 확장자군 판정 — activity).

표준 라이브러리만 쓴다. 나눗셈·반올림은 `lm27.report.fmt` 로만(G-R11). 파일을 쓰지 않는다.
"""
from __future__ import annotations

import bisect
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import timedelta

from lm27.report import fmt as F
from lm27.report import vocab as V
from lm27.report.analysis.activity import EST_END, EST_START, Unit, lmin_date, lmin_iso
from lm27.vocab import steps as S

__all__ = [
    "FORCED",
    "Tr",
    "apply_labels",
    "collapse",
    "doc_sets",
    "domain_workflow",
    "handoffs",
    "mine_role",
    "project_workflow",
    "role_sentences",
    "unit_workflow",
    "workflows",
]

FORCED = ("REQ_IN", "REQ_OUT", "REPORT_OUT", "REPORT_IN")   # 시작·끝 점은 항상 남긴다(R §4.2.1 ②)
LABEL_MAX = 20                                               # 코파일럿 단계 라벨 상한(B §8.4 hard 60 · 화면 20)


def _order(code: str) -> int:
    st = S.STEP_TYPES.get(code)
    return st.order if st else 99


def _kind(code: str) -> str:
    st = S.STEP_TYPES.get(code)
    return st.kind if st else "A"


def _cls(code: str) -> str:
    st = S.STEP_TYPES.get(code)
    return st.cls if st else ""


def mining_cfg(cfg) -> dict:
    """마이닝 설정(R §10.2 report.mining.*) — 읽힘 기록은 lm27.config 가 한다(G-R9)."""
    return {"min_sec": int(cfg["report.mining.minStepSec"]), "max_steps": int(cfg["report.mining.maxSteps"]),
            "support": cfg["report.mining.minSupportRatio"], "max_edges": int(cfg["report.mining.maxEdges"]),
            "wait_min": int(cfg["report.mining.waitBottleneckMin"]),
            "work_share": cfg["report.mining.workBottleneckShare"],
            "min_units": int(cfg["report.mining.minUnitsForBottleneck"]),
            "handoff_wd": int(cfg["report.mining.handoffWd"])}


# ───────────────────────────── 흔적 정리(R §4.2.1 ①) ─────────────────────────────
@dataclass
class Tr:
    """정리된 흔적 항목 하나(같은 단계가 이어진 Run·점을 합친 것). n = 합친 항목 수."""
    code: str
    kind: str
    a: int
    b: int
    sec: int
    obs_sec: int
    n: int = 1
    items: list = field(default_factory=list)


def _item_key(it) -> tuple:
    return (it.a, it.b, _order(it.type), it.type)


def collapse(items: Iterable, keep: Iterable[str] | None = None, min_sec: int = 600) -> list[Tr]:
    """구간 단계 중 sec < min_sec 인 Run 은 버리고(점 단계는 버리지 않음), keep 밖 단계를 버리고, 바로 앞 항목과 단계 코드가
    같으면 하나로 합친다(a = min, b = max, sec·obs_sec 합, n += 1)."""
    ks = None if keep is None else frozenset(keep)
    out: list[Tr] = []
    for it in sorted(items or (), key=_item_key):
        code = it.type
        if ks is not None and code not in ks:
            continue
        if it.kind != "M" and it.sec < min_sec:
            continue
        if out and out[-1].code == code:
            o = out[-1]
            o.a, o.b = min(o.a, it.a), max(o.b, it.b)
            o.sec += it.sec
            o.obs_sec += it.obs_sec
            o.n += 1
            o.items.append(it)
        else:
            out.append(Tr(code, it.kind, it.a, it.b, it.sec, it.obs_sec, 1, [it]))
    return out


# ───────────────────────────── 역할 업무 수준(R §4.2) ─────────────────────────────
def _role_units(units: Iterable[Unit]) -> list[Unit]:
    """마이닝 대상: 미착수(Z)가 아니고 투입 > 0 — 시작 시각순(동률 unit_id)."""
    us = [u for u in units if u.status != "not_started" and u.effort_min > 0]
    return sorted(us, key=lambda u: (u.start if u.start is not None else -1, u.unit_id))


def _bounds(u: Unit, trace: list[Tr], as_of_min: int) -> tuple[int, int]:
    """위치 계산 구간: 첫 차수 시작(추정 경계 포함) ~ 마지막 차수 끝(진행 중이면 분석 시각)."""
    st = u.start if u.start is not None else (trace[0].a if trace else 0)
    en = u.end if u.end is not None else max(as_of_min, st)
    return st, max(en, st)


def _step_name(code: str, registry) -> str:
    return V.step_name(code, registry)


def _mine(units: Iterable[Unit], log: Mapping, cfg, *, bc: F.BizCal, as_of_min: int,
          registry=None) -> tuple[dict | None, dict[str, list[Tr]]]:
    c = mining_cfg(cfg)
    U = _role_units(units)
    N = len(U)
    if N == 0:
        return None, {}
    t0 = {u.unit_id: collapse(log.get(u.unit_id, ()), None, c["min_sec"]) for u in U}
    sup: Counter = Counter()
    tot: Counter = Counter()
    for tr in t0.values():
        for code in {x.code for x in tr}:
            sup[code] += 1
        for x in tr:
            tot[x.code] += x.sec
    thr = max(1, F.ceil_mul(c["support"], N))
    cand = sorted((k for k in sup if sup[k] >= thr), key=lambda k: (-sup[k], -tot[k], _order(k)))
    forced = [k for k in cand if k in FORCED]
    rest = [k for k in cand if k not in FORCED]
    keep = forced + rest[: max(0, c["max_steps"] - len(forced))]
    keep_set = set(keep)
    dropped = sorted({k for k in sup if k not in keep_set}, key=lambda k: (_order(k), k))
    tr = {u.unit_id: collapse(log.get(u.unit_id, ()), keep_set, c["min_sec"]) for u in U}
    # ③ 순서 — 단위업무 구간 안 첫 출현 상대 위치의 중앙값
    pos: dict[str, list] = defaultdict(list)
    for u in U:
        t = tr[u.unit_id]
        st, en = _bounds(u, t, as_of_min)
        span = en - st
        seen: set[str] = set()
        for i, x in enumerate(t):
            if x.code in seen:
                continue
            seen.add(x.code)
            if span > 0:
                p = F.per(x.a - st, span)
            else:
                p = F.per(i, len(t) - 1) if len(t) > 1 else F.dec(0)
            pos[x.code].append(min(F.dec(1), max(F.dec(0), p)))
    order = sorted(keep, key=lambda k: (F.median(pos[k]) if pos[k] else F.dec(1), _order(k)))
    no = {k: i + 1 for i, k in enumerate(order)}
    # ④ 단계 통계(그 단계가 나온 단위업무만)
    months = Counter()
    for u in U:
        for m, v in u.by_month.items():
            if v > 0:
                months[m] += v
    n_months = max(1, len(months))
    steps = []
    for k in order:
        per_u = [sum(x.sec for x in tr[u.unit_id] if x.code == k) for u in U
                 if any(x.code == k for x in tr[u.unit_id])]
        occ = sum(1 for u in U for x in tr[u.unit_id] if x.code == k)
        kind = _kind(k)
        ssec = sum(x.sec for u in U for x in tr[u.unit_id] if x.code == k)
        sobs = sum(x.obs_sec for u in U for x in tr[u.unit_id] if x.code == k)
        mins = [F.frac(s, 60) for s in per_u]
        steps.append({
            "no": no[k], "code": k, "name": _step_name(k, registry), "kind": kind, "n": int(sup[k]),
            "freq_month": F.ratio(occ, n_months, 2),
            "median_min": 0 if kind == "M" else (F.median_int(mins) or 0),
            "p75_min": 0 if kind == "M" else (F.p75_int(mins) or 0),
            "obs_share": None if kind == "M" else F.ratio(sobs, ssec, 3),
            "wait_in_median_min": None, "work_share": None,
            "label": _step_name(k, registry), "desc": "", "label_by": "rule",
            "agent_grade": "", "subagent": "", "why": [],
        })
    # ⑤ 전이·대기
    edges: Counter = Counter()
    waits_in: dict[int, list] = defaultdict(list)
    edge_w: dict[tuple[int, int], list] = defaultdict(list)
    rework_units: Counter = Counter()
    for u in U:
        t = tr[u.unit_id]
        back: set[tuple[int, int]] = set()
        for x, y in zip(t, t[1:], strict=False):
            e = (no[x.code], no[y.code])
            edges[e] += 1
            w = bc.biz_min(x.b, y.a)
            waits_in[e[1]].append(w)
            edge_w[e].append(w)
            if e[0] > e[1]:
                back.add(e)
        for e in back:
            rework_units[e] += 1
    all_edges = sorted(([i, j, n] for (i, j), n in edges.items()), key=lambda e: (-e[2], e[0], e[1]))
    for s in steps:
        s["wait_in_median_min"] = F.median_int(waits_in.get(s["no"], ()))
    # ⑥ 작업 비중
    act = [s for s in steps if s["kind"] == "A"]
    tot_med = sum(s["median_min"] for s in act)
    for s in act:
        s["work_share"] = F.ratio(s["median_min"], tot_med, 3) if tot_med else 0.0
    # ⑦ 병목
    bott = []
    sample = "ok" if N >= c["min_units"] else "thin"
    if sample == "ok":
        ws = [s for s in steps if s["wait_in_median_min"] is not None]
        if ws:
            m = max(ws, key=lambda s: (s["wait_in_median_min"], -s["no"]))
            if m["wait_in_median_min"] >= c["wait_min"]:
                bott.append({"no": m["no"], "kind": "wait", "value_min": m["wait_in_median_min"]})
        if act:
            m = max(act, key=lambda s: (s["work_share"], -s["no"]))
            if F.dec(m["work_share"]) >= F.dec(c["work_share"]):
                bott.append({"no": m["no"], "kind": "work", "share": m["work_share"]})
    # ⑧ 역할 요약
    done = [u for u in U if u.closed]
    leads = [u.biz_lead_min for u in done if u.biz_lead_min is not None]
    par = F.median(F.dec(u.parallel) for u in U)
    rw = {
        "role_id": U[0].role_id, "units": [u.unit_id for u in U], "units_n": N, "support_threshold": thr,
        "steps": steps,
        "edges": all_edges[: c["max_edges"]], "edges_rest": all_edges[c["max_edges"]:],
        "edge_waits": [[i, j, F.median_int(edge_w[(i, j)])] for i, j, _n in all_edges],
        "rework": [e for e in all_edges if e[0] > e[1]],
        "rework_units": [[i, j, int(rework_units[(i, j)])] for i, j, _n in all_edges if i > j],
        "bottlenecks": bott,
        "dropped": [{"code": k, "name": _step_name(k, registry), "n": int(sup[k])} for k in dropped],
        "sample": sample,
        "short_runs_n": sum(1 for u in U for x in log.get(u.unit_id, ()) if x.kind != "M" and x.sec < c["min_sec"]),
        "traces": {u.unit_id: [x.code for x in tr[u.unit_id]] for u in U},
        "lead_biz_median_min": F.median_int(leads), "lead_biz_p75_min": F.p75_int(leads),
        "effort_median_min": F.median_int(u.effort_min for u in U) or 0,
        "effort_min": sum(u.effort_min for u in U),
        "parallel_median": None if par is None else F.half_up(par, 2),
        "done_ratio": F.ratio(len(done), N, 3),
        "months_active": len(months),
        "ai_role": "", "ai_summary": "", "ai_by": "rule", "sentences": [],
    }
    return rw, tr


def mine_role(units: Iterable[Unit], log: Mapping, cfg, *, bc: F.BizCal, as_of_min: int, registry=None) -> dict | None:
    """역할 업무 하나의 RoleWorkflow(R §4.2.2 · 계약 §3.16). 대상 단위업무가 없으면 None."""
    return _mine(units, log, cfg, bc=bc, as_of_min=as_of_min, registry=registry)[0]


# ───────────────────────────── 단위업무 수준(R §4.3.1) ─────────────────────────────
def unit_workflow(unit: Unit, log: Mapping, cal: F.BizCal, *, as_of_min: int, min_sec: int = 600) -> dict:
    """단위업무 타임라인 재료: 묶음 줄 · 원 Run(10분 미만 포함 — 근거 보존) · 점 · 경계 · 대기 · 설명된 투입 비율 · 차수."""
    items = list(log.get(unit.unit_id, ()))
    runs = [x for x in items if x.kind == "A"]
    lanes = [c for c in S.CLASSES if any(_cls(r.type) == c for r in runs)]
    out_runs = [{"type": r.type, "class": _cls(r.type), "a": lmin_iso(r.a), "b": lmin_iso(r.b), "min": r.minutes,
                 "obs_min": F.sec_min(r.obs_sec), "apps": [[k, F.sec_min(v)] for k, v in r.apps],
                 "fams": [[k, F.sec_min(v)] for k, v in r.fams]} for r in runs]
    ms = [{"type": x.type, "t": lmin_iso(x.t), "cycle": x.cycle, "flags": sorted(x.flags)}
          for x in items if x.kind == "M"]
    bnd = []
    from lm27.time.episodes import EG, SG          # 경계 근거 → 등급 조각(W §4.10.1 단일원)
    for i, cy in enumerate(unit.cycles):
        bnd.append({"cycle": i, "side": "start", "code": cy.sb, "t": lmin_iso(cy.s), "grade_part": SG.get(cy.sb, ""),
                    "estimated": cy.sb in EST_START})
        code = cy.eb if cy.e is not None else "OPEN"
        bnd.append({"cycle": i, "side": "end", "code": code, "t": lmin_iso(cy.e), "grade_part": EG.get(code, ""),
                    "estimated": code in EST_END})
    tr = collapse(items, None, min_sec)
    waits = [{"after": x.code, "before": y.code, "a": lmin_iso(x.b), "b": lmin_iso(y.a), "biz_min": cal.biz_min(x.b, y.a)}
             for x, y in zip(tr, tr[1:], strict=False)]
    longest = None
    for w in waits:
        if longest is None or w["biz_min"] > longest["biz_min"]:
            longest = w
    run_sec = sum(r.sec for r in runs)
    expl = F.ratio(run_sec, unit.effort_min * 60, 3) if unit.effort_min > 0 else None
    if expl is not None and expl > 1.0:
        expl = 1.0
    cycles = []
    for i, cy in enumerate(unit.cycles):
        mark = ""
        if i > 0:
            mark = "quiet_add" if unit.cycles[i - 1].eb == "NEXT_REQ" else "re_request"
        cycles.append({"no": i, "s": lmin_iso(cy.s), "sb": cy.sb, "e": lmin_iso(cy.e), "eb": cy.eb or "OPEN",
                       "interim": [[lmin_iso(t), code] for t, code in cy.interim], "unstarted": cy.unstarted,
                       "mark": mark})
    step_sec: Counter = Counter()
    for r in runs:
        step_sec[r.type] += r.sec
    return {"unit_id": unit.unit_id, "lanes": lanes, "runs": out_runs, "milestones": ms, "boundaries": bnd,
            "waits": waits, "longest_wait": longest, "explained_ratio": expl, "cycles": cycles,
            "steps": [x.code for x in tr],
            "step_min": {k: F.sec_min(v) for k, v in sorted(step_sec.items(), key=lambda kv: (_order(kv[0]), kv[0]))}}


# ───────────────────────────── 인계(R §4.3.2 · §4.6.1 선행함) ─────────────────────────────
def _who(u: Unit) -> set[str]:
    return {w for w, _r in u.peers}


def doc_sets(units: Iterable[Unit], log: Mapping) -> dict[str, set[str]]:
    """단위업무가 다룬 문서군: 시간 코어 문서 연결(tasks.json docs) ∪ 귀속 Run 의 문서군."""
    out = {}
    for u in units:
        fs = set(u.docs)
        for x in log.get(u.unit_id, ()):
            if x.kind == "A":
                fs |= {f for f, _s in x.fams}
        out[u.unit_id] = fs
    return out


def handoffs(units: Iterable[Unit], bc: F.BizCal, handoff_wd: int, same_role: bool = False,
             peer_sets: Mapping[str, set] | None = None,
             doc_sets_: Mapping[str, set] | None = None) -> dict[str, tuple[str, int, list[str]]]:
    """단위업무 b 마다 선행자 a 하나: a.마지막 끝 날짜 ≤ b.시작 날짜 · wd_between(a.끝, b.시작) ≤ handoffWd ·
    (문서군 공유 또는 동료 공유) · (same_role=False 면 역할이 다름). 조건을 만족하는 a 중 끝이 가장 늦은 것(동률 unit_id).
    반환 {b: (a, 영업 분 간격, via[doc|peer])}. 문서군 집합을 주지 않으면 시간 코어 문서 연결만 본다."""
    us = [u for u in units if u.start is not None]
    ends = sorted((u for u in us if u.end is not None), key=lambda u: (lmin_date(u.end), u.unit_id))
    end_d = [lmin_date(u.end) for u in ends]
    ps = peer_sets or {}
    ds = doc_sets_ or {}
    docs = {u.unit_id: set(ds.get(u.unit_id, u.docs)) for u in us}
    who = {u.unit_id: (ps.get(u.unit_id) if u.unit_id in ps else _who(u)) for u in us}
    lows: dict = {}
    out: dict[str, tuple[str, int, list[str]]] = {}
    for b in sorted(us, key=lambda u: u.unit_id):
        bd = lmin_date(b.start)
        lo = lows.get(bd)
        if lo is None:                               # wd_between(lo, bd) ≤ handoffWd 인 가장 이른 날짜(창)
            lo, n = bd, 0
            while n < 400:
                prev = lo - timedelta(days=1)
                if bc.wd_between(prev, bd) > handoff_wd:
                    break
                lo, n = prev, n + 1
            lows[bd] = lo
        cands = []
        for a in ends[bisect.bisect_left(end_d, lo):bisect.bisect_right(end_d, bd)]:
            if a.unit_id == b.unit_id or (not same_role and a.role_id == b.role_id):
                continue
            via = [v for v, ok in (("doc", docs[a.unit_id] & docs[b.unit_id]),
                                   ("peer", who[a.unit_id] & who[b.unit_id])) if ok]
            if via:
                cands.append((a, via))
        if cands:
            a, via = min(cands, key=lambda c: (-c[0].end, c[0].unit_id))   # 끝이 가장 늦은 것, 동률 unit_id 순
            out[b.unit_id] = (a.unit_id, bc.biz_min(a.end, b.start), via)
    return out


# ───────────────────────────── 과제 수준(R §4.3.2) ─────────────────────────────
def project_workflow(project_key: str, units_by_role: Mapping[str, list[Unit]], log: Mapping, cfg, *,
                     bc: F.BizCal, roles_wf: Mapping | None = None) -> dict:
    """과제 하나: 역할 레인(첫 단위업무 시작 → role_id 순) · 역할 간 인계 집계 · 역할 구성(투입 분·비중·병목 한 줄)."""
    c = mining_cfg(cfg)
    rows = []
    for rid, us in units_by_role.items():
        starts = [u.start for u in us if u.start is not None]
        rows.append((min(starts) if starts else 1 << 62, rid, us))
    rows.sort(key=lambda r: (r[0], r[1]))
    tot = sum(u.effort_min for _s, _r, us in rows for u in us)
    roles = []
    for st, rid, us in rows:
        m = sum(u.effort_min for u in us)
        rw = (roles_wf or {}).get(rid)
        roles.append({"role_id": rid, "units": [u.unit_id for u in sorted(us, key=lambda u: (u.start or 0, u.unit_id))],
                      "first_start": lmin_iso(st) if st < (1 << 62) else None, "effort_min": m,
                      "share": F.ratio(m, tot, 3) if tot else 0.0, "bottleneck": _bn_text(rw)})
    allu = [u for _s, _r, us in rows for u in us]
    ho = handoffs(allu, bc, c["handoff_wd"], same_role=False, doc_sets_=doc_sets(allu, log))
    by_id = {u.unit_id: u for u in allu}
    agg: dict[tuple[str, str], dict] = {}
    for b_id, (a_id, gap, via) in sorted(ho.items()):
        x, y = by_id[a_id].role_id, by_id[b_id].role_id
        g = agg.setdefault((x, y), {"from": x, "to": y, "n": 0, "gaps": [], "via": {"doc": 0, "peer": 0}, "pairs": []})
        g["n"] += 1
        g["gaps"].append(gap)
        for v in via:
            g["via"][v] += 1
        g["pairs"].append([a_id, b_id, gap, via])
    hand = []
    for (x, y), g in sorted(agg.items(), key=lambda kv: (-kv[1]["n"], kv[0])):
        hand.append({"from_role": x, "to_role": y, "n": g["n"], "gap_biz_median_min": F.median_int(g["gaps"]),
                     "via": g["via"], "pairs": g["pairs"]})
    return {"key": project_key, "roles": roles, "handoffs": hand, "effort_min": tot,
            "units_n": len(allu), "done_n": sum(1 for u in allu if u.closed)}


def _bn_text(rw) -> str:
    """역할 병목 한 줄 코드 'wait:3|work:2'(R §9.2.1 tree 의 bottleneck) — 표본 부족이면 'thin'."""
    if not rw:
        return ""
    if rw.get("sample") == "thin":
        return "thin"
    return "|".join(f"{b['kind']}:{b['no']}" for b in rw.get("bottlenecks", ()))


# ───────────────────────────── 업무 영역 · 사람 전체(R §4.3.3) ─────────────────────────────
def _class_mix(units: Iterable[Unit], log: Mapping) -> tuple[dict[str, int], int]:
    """묶음별 Run 분(구간 단계만, 묶음 고정 순서) + 단계로 설명되지 않은 투입(L5·L6 등 — '단계 없음')."""
    mix: Counter = Counter()
    run_sec = 0
    eff = 0
    for u in units:
        eff += u.effort_min
        for x in log.get(u.unit_id, ()):
            if x.kind == "A":
                mix[_cls(x.type)] += x.sec
                run_sec += x.sec
    class_min = {c: F.sec_min(mix[c]) for c in S.CLASSES if mix.get(c)}
    return class_min, max(0, eff - F.sec_min(run_sec))


def domain_workflow(code: str, units: Iterable[Unit], log: Mapping, roles: Mapping) -> dict:
    """영역(또는 'ALL' = 사람 전체): 과제(투입 내림차순 — 과제별 묶음 구성 포함, CH-P10) · 묶음별 Run 분 · 단계 없음 분 ·
    상위 병목 3 · 단위업무 수·리드·투입."""
    us = sorted(units, key=lambda u: u.unit_id)
    by_p: dict[str, list[Unit]] = defaultdict(list)
    for u in us:
        by_p[u.project_key].append(u)
    projects = []
    for k, pu in sorted(by_p.items(), key=lambda kv: (-sum(u.effort_min for u in kv[1]), kv[0])):
        pm, pn = _class_mix(pu, log)
        projects.append({"key": k, "effort_min": sum(u.effort_min for u in pu), "class_mix": pm, "none_min": pn})
    class_min, none_min = _class_mix(us, log)
    eff = sum(u.effort_min for u in us)
    rids = sorted({u.role_id for u in us})
    bn = []
    for rid in rids:
        rw = roles.get(rid)
        if not rw:
            continue
        for b in rw.get("bottlenecks", ()):
            step = next((s for s in rw["steps"] if s["no"] == b["no"]), None)
            if b["kind"] == "wait":
                score = int(b["value_min"])
            else:
                score = F.half_up(F.dec(b["share"]) * int(rw.get("effort_min", 0)))
            bn.append({"role_id": rid, "no": b["no"], "code": step["code"] if step else "", "kind": b["kind"],
                       "value_min": b.get("value_min"), "share": b.get("share"), "score_min": score})
    bn.sort(key=lambda b: (-b["score_min"], b["role_id"], b["kind"], b["no"]))
    done = [u for u in us if u.closed]
    leads = [u.biz_lead_min for u in done if u.biz_lead_min is not None]
    active = [u for u in us if u.effort_min > 0]
    return {"code": code, "projects": projects, "class_mix": class_min, "none_min": none_min,
            "top_bottlenecks": bn[:3], "units_n": len(us), "done_n": len(done),
            "open_n": sum(1 for u in us if u.status == "open"),
            "unstarted_n": sum(1 for u in us if u.status == "not_started"),
            "lead_biz_median_min": F.median_int(leads),
            "effort_median_min": F.median_int(u.effort_min for u in active), "effort_min": eff}


# ───────────────────────────── 전체 ─────────────────────────────
def workflows(ctx) -> tuple[dict, dict]:
    """모델 `workflows{roles, units, projects, domains, person}` + 역할별 정리된 흔적(서브에이전트·agentic 재료)."""
    roles: dict[str, dict] = {}
    traces: dict[str, dict[str, list[Tr]]] = {}
    for rid, us in ctx.by_role().items():
        rw, tr = _mine(us, ctx.log, ctx.cfg, bc=ctx.bc, as_of_min=ctx.as_of_min, registry=ctx.registry)
        if rw is not None:
            roles[rid] = rw
            traces[rid] = tr
    min_sec = int(ctx.cfg["report.mining.minStepSec"])
    units = {u.unit_id: unit_workflow(u, ctx.log, ctx.bc, as_of_min=ctx.as_of_min, min_sec=min_sec)
             for u in ctx.unit_list()}
    by_proj: dict[str, dict[str, list[Unit]]] = defaultdict(lambda: defaultdict(list))
    by_dom: dict[str, list[Unit]] = defaultdict(list)
    for u in ctx.unit_list():
        by_proj[u.project_key][u.role_id].append(u)
        by_dom[u.domain].append(u)
    projects = {k: project_workflow(k, dict(sorted(v.items())), ctx.log, ctx.cfg, bc=ctx.bc, roles_wf=roles)
                for k, v in sorted(by_proj.items())}
    domains = {c: domain_workflow(c, by_dom[c], ctx.log, roles)
               for c in sorted(by_dom, key=lambda c: (V.domain_order(c), c))}
    person = domain_workflow("ALL", ctx.unit_list(), ctx.log, roles)
    return {"roles": roles, "units": units, "projects": projects, "domains": domains, "person": person}, traces


# ───────────────────────────── 코파일럿 라벨 반영(R §4.10.2) ─────────────────────────────
def _clip(s, n: int) -> str:
    t = " ".join(str(s or "").split())
    return t[:n]


def apply_labels(roles: Mapping[str, dict], answers: Mapping[str, tuple], registry=None) -> dict[str, int]:
    """workflow_label 답(키 `ws:<role_id>` → (ans, by)) → Step.label/desc/label_by · ai_role/ai_summary/ai_by.

    답의 `s` 코드로 단계를 찾는다. 번호가 바뀐(재분석으로 단계 구성이 달라진) 옛 답은 같은 단계 **코드**의 라벨을 쓰고
    `label_by = rule_pending`(브리지가 다시 묻는다). 답이 없으면 단계 유형 한글명 + `rule`. 반환 = 출처별 단계 수."""
    cnt: Counter = Counter()
    for rid, rw in roles.items():
        got = answers.get("ws:" + rid)
        ans, by = (got if got else (None, "rule"))
        steps_ans = []
        if isinstance(ans, Mapping):
            for st in ans.get("steps") or ():
                if isinstance(st, Mapping):
                    steps_ans.append(st)
        cur = [(f"S{s['no']}", s["code"]) for s in rw["steps"]]
        by_s = {str(st.get("s")): st for st in steps_ans}
        by_type: dict[str, Mapping] = {}
        for st in steps_ans:
            ty = st.get("type")
            if isinstance(ty, str) and ty not in by_type:
                by_type[ty] = st
        fresh = bool(steps_ans) and all(
            (str(st.get("s")), st.get("type", dict(cur).get(str(st.get("s"))))) in set(cur) for st in steps_ans)
        for s in rw["steps"]:
            hit = by_s.get(f"S{s['no']}")
            if hit is not None and hit.get("type", s["code"]) == s["code"] and fresh:
                lab, lby = hit, str(by or "ai")
            elif s["code"] in by_type:
                lab, lby = by_type[s["code"]], "rule_pending"
            else:
                lab, lby = None, "rule"
            if lab is not None and _clip(lab.get("label"), LABEL_MAX):
                s["label"] = _clip(lab.get("label"), LABEL_MAX)
                s["desc"] = _clip(lab.get("desc"), 80)
                s["label_by"] = lby
            else:
                s["label"] = V.step_name(s["code"], registry)
                s["desc"] = ""
                s["label_by"] = "rule"
            cnt[s["label_by"]] += 1
        if isinstance(ans, Mapping):
            rw["ai_role"] = _clip(ans.get("role"), 40)
            rw["ai_summary"] = _clip(ans.get("summary"), 160)
            rw["ai_by"] = str(by or "ai") if fresh else ("rule_pending" if steps_ans else str(by or "rule"))
        else:
            rw["ai_role"], rw["ai_summary"], rw["ai_by"] = "", "", "rule"
    return dict(sorted(cnt.items()))


# ───────────────────────────── 규칙 문장(R §6.3.3) ─────────────────────────────
def _batchim(word: str) -> int | None:
    """마지막 글자의 받침 번호(0 = 없음). 한글이 아니면 None."""
    w = str(word or "").rstrip()
    if not w:
        return None
    code = ord(w[-1]) - 0xAC00
    if 0 <= code < 11172:
        return code % 28
    return None


def josa(word: str, with_b: str, without_b: str) -> str:
    """받침에 맞는 조사(을/를 · 이/가 · 은/는). 한글이 아니면 '을(를)' 꼴."""
    b = _batchim(word)
    if b is None:
        return f"{with_b}({without_b})"
    return with_b if b else without_b


def josa_ro(word: str) -> str:
    """(으)로 — 받침이 없거나 ㄹ 받침이면 '로'."""
    b = _batchim(word)
    if b is None:
        return "(으)로"
    return "로" if b in (0, 8) else "으로"


def role_sentences(rw: Mapping, std_day_min: int = 480) -> list[str]:
    """역할 워크플로우 규칙 문장(코파일럿 없이도 항상, 최대 4문장 — R §6.3.3). 숫자는 `fmt` 표시 함수."""
    out: list[str] = []
    steps = {s["no"]: s for s in rw.get("steps", ())}
    bns = {b["kind"]: b for b in rw.get("bottlenecks", ())}
    w = bns.get("work")
    if w and w["no"] in steps:
        lab = steps[w["no"]]["label"]
        out.append(f"{lab} 작업이 이 역할 투입의 {F.share_text(w['share'])}로 가장 큽니다.")
    wt = bns.get("wait")
    if wt and wt["no"] in steps:
        j = wt["no"]
        inc = [e for e in list(rw.get("edges", ())) + list(rw.get("edges_rest", ())) if e[1] == j]
        if inc:
            i = sorted(inc, key=lambda e: (-e[2], e[0]))[0][0]
            prev, lab = steps[i]["label"], steps[j]["label"]
            out.append(f"{prev}{josa(prev, '을', '를')} 마치고 {lab}{josa(lab, '을', '를')} 시작하기까지 보통 "
                       f"{F.fmt_days(wt['value_min'], std_day_min)}영업일을 기다립니다.")
    rus = [r for r in rw.get("rework_units", ()) if r[2] > 0]
    if rus:
        i, j, n = sorted(rus, key=lambda r: (-r[2], r[0], r[1]))[0]
        if i in steps and j in steps:
            back, front = steps[i]["label"], steps[j]["label"]
            out.append(f"{n}건의 단위업무에서 {back}{josa(back, '을', '를')} 하다가 {front}{josa_ro(front)} "
                       "되돌아갔습니다.")
    if rw.get("sample") == "thin":
        out.append(f"단위업무가 {rw.get('units_n', 0)}건뿐이라 병목은 판단하지 않았습니다.")
    return out[:4]
