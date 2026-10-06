# -*- coding: utf-8 -*-
r"""온톨로지 그래프 · 연관도 · 연관 업무 추천(R §4.6 · §6.6 · 부록 A, 결정 §10.5 · 계약 §3.16 온톨로지 절 · §6.6).

**닫힌 관계 어휘**(D-19): 소속 · 의뢰함 · 보고함 · 산출함 · 사용함 · 함께함 · 선행함 · 같은문서 · 같은과제(`vocab.ONTO_RELS`).
노드는 P(과제) · R(역할 업무) · U(단위업무) · D(문서군) · A(앱) · C(동료 — 외부는 도메인 계급 노드 하나씩).

| 관계 | 방향 | 성립 | w(근거 수) · h(분) |
|---|---|---|---|
| 소속 | U→R→P | 분류 라벨(구조 간선) | — |
| 의뢰함 · 보고함 | C→U · U→C | requester · reporter | 메시지 수 · 그 단위업무 투입 |
| 산출함 | U→D | Run 의 그 문서군 초 ≥ 1분, 또는 저장·내보내기·첨부 | 저장·내보내기·첨부 수 · 그 문서 Run 분 |
| 사용함 | U→A | Run 의 그 앱 분 ≥ `report.ontology.appMinMin` | Run 수 · 분 |
| 함께함 | U–C | thread · meeting | 메시지·회의 수 · 그 단위업무 투입 |
| 선행함 | U→U | 인계 조건(R §4.3.2, 역할이 같아도 됨) — 추론 | 1 |
| 같은문서 | U–U | 두 단위업무가 같은 문서군을 산출함 — 추론 | 공유 문서 수 |
| 같은과제 | U–U | 같은 과제(구조로 이미 보이므로 그리지 않음) | — |

연관도(R §4.6.2) `rel(u, v) = w_doc·J(D) + w_peer·J(C) + w_app·J(A) + w_seq·seq` — 정확한 유리수로 계산해 소수 4자리
half-up(결정성). seq = 1(선행 조건 성립 — 한쪽 끝 날짜 ≤ 다른 쪽 시작 날짜, 그 사이 근무일 ≤ handoffWd, 문서·동료 공유) ·
0.5(같은 역할이고 리드 구간 날짜가 겹침) · 0. 추천(R §4.6.3) = rel ≥ minRel 인 다른 단위업무, rel ↓ → 시작 → unit_id 순 최대 5,
종류 same(같은 일 의심) · chain(이어진 일) · ref(참고할 일) · related(관련 일) — 첫 번째로 맞는 것.

그래프(R §4.6.4): 중심 과제 1개(기본 = 기준 시각 달의 투입 최대 과제)의 R·U 전부(U 가 maxUnits 를 넘으면 투입 상위 + '기타 n'),
바깥 D·A·C 는 연결 가중치(Σh, 같으면 Σw) 상위 topN + 무리별 '기타 n'. 다른 과제 그래프는 `graphs`, 과제 간 연관도는
`related_projects`(seq 없이 가중치 재정규화). 노드 `key` 는 로컬 해석용 원래 키(문서군·앱·who_key) — 보고서 모델이 변형별
이름·번호표로 바꾼다(R §3.6 · §9.2.4).

설정(R §10.2): `report.ontology.weights` · `minRel` · `sameWorkRel` · `appMinMin` · `topN` · `maxUnits`
(+ 선행 조건의 `report.mining.handoffWd`). 표준 라이브러리만 쓴다. 나눗셈은 `fmt` 로만. 파일을 쓰지 않는다.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Mapping
from datetime import date

from lm27.report import fmt as F
from lm27.report import vocab as V
from lm27.report.analysis.activity import Unit, lmin_date
from lm27.report.analysis.mining import handoffs

__all__ = ["UnitSets", "ontology_layer", "project_graph", "relations", "relatedness", "unit_sets"]

TYPE_ORDER = {"P": 0, "R": 1, "U": 2, "D": 3, "A": 4, "C": 5}
REC_MAX = 5


def onto_cfg(cfg) -> dict:
    w = cfg["report.ontology.weights"]
    return {"w": {k: F.dec(w.get(k, 0)) for k in ("doc", "peer", "app", "seq")},
            "min_rel": F.dec(cfg["report.ontology.minRel"]), "same": F.dec(cfg["report.ontology.sameWorkRel"]),
            "app_min": int(cfg["report.ontology.appMinMin"]), "top_n": int(cfg["report.ontology.topN"]),
            "max_units": int(cfg["report.ontology.maxUnits"]), "handoff_wd": int(cfg["report.mining.handoffWd"])}


class UnitSets(dict):
    """단위업무 하나의 관계 재료: docs·apps·peers 집합과 가중(산출·사용 분·횟수), 역할·과제·리드 날짜."""


def unit_sets(u: Unit, log: Mapping, peers: Mapping[str, frozenset], app_min: int, as_of_min: int) -> UnitSets:
    doc_sec: Counter = Counter()
    app_sec: Counter = Counter()
    app_runs: Counter = Counter()
    for x in log.get(u.unit_id, ()):
        if x.kind != "A":
            continue
        for f, s in x.fams:
            doc_sec[f] += s
        for a, s in x.apps:
            app_sec[a] += s
            app_runs[a] += 1
    ops = {f: sum(v["ops"].values()) for f, v in u.docs.items()}
    docs = {f for f, s in doc_sec.items() if s >= 60} | {f for f, n in ops.items() if n > 0}
    apps = {a for a, s in app_sec.items() if s >= app_min * 60}
    end = u.end_date
    lead_end = end or (lmin_date(max(as_of_min, u.start)) if u.start is not None else None)
    return UnitSets(unit_id=u.unit_id, role=u.role_id, project=u.project_key, docs=docs, apps=apps,
                    peers=set(peers), start_d=u.start_date, end_d=end, lead_end_d=lead_end,
                    doc_min={f: F.sec_min(doc_sec.get(f, 0)) for f in docs}, doc_w={f: ops.get(f, 0) for f in docs},
                    app_min={a: F.sec_min(app_sec[a]) for a in apps}, app_w={a: app_runs[a] for a in apps},
                    effort=u.effort_min, start=u.start)


def _wd(bc, a: date, b: date) -> int:
    if bc is not None:
        return bc.wd_between(a, b)
    n, d = 0, a
    while d < b:
        d = date.fromordinal(d.toordinal() + 1)
        n += d.weekday() < 5
    return n


def _seq(u: Mapping, v: Mapping, handoff_wd: int, bc=None):
    share = bool(set(u["docs"]) & set(v["docs"])) or bool(set(u["peers"]) & set(v["peers"]))
    for a, b in ((u, v), (v, u)):
        if share and a.get("end_d") is not None and b.get("start_d") is not None and a["end_d"] <= b["start_d"] \
                and _wd(bc, a["end_d"], b["start_d"]) <= handoff_wd:
            return F.dec(1)
    if u.get("role") == v.get("role") and _overlap(u, v):
        return F.dec("0.5")
    return F.dec(0)


def _overlap(u: Mapping, v: Mapping) -> bool:
    a0, a1 = u.get("start_d"), u.get("lead_end_d", u.get("end_d"))
    b0, b1 = v.get("start_d"), v.get("lead_end_d", v.get("end_d"))
    if None in (a0, a1, b0, b1):
        return False
    return not (a1 < b0 or b1 < a0)


def _jac_terms(u: Mapping, v: Mapping, w: Mapping) -> list[tuple]:
    out = []
    for k, key in (("doc", "docs"), ("peer", "peers"), ("app", "apps")):
        a, b = u[key], v[key]
        out.append((w[k], len(a & b), len(a | b)))
    return out


def relatedness(u: Mapping, v: Mapping, cfg, *, bc=None, oc: dict | None = None) -> tuple[float, float]:
    """R §4.6.2 연관도 (rel, seq). u·v = {docs, peers, apps, role, start_d, end_d[, lead_end_d]}(date).
    정확한 정수 분수로 더해 소수 4자리 half-up(부동소수 순서와 무관 — 결정성)."""
    c = oc or onto_cfg(cfg)
    w = c["w"]
    u = {**u, "docs": set(u["docs"]), "peers": set(u["peers"]), "apps": set(u["apps"])}
    v = {**v, "docs": set(v["docs"]), "peers": set(v["peers"]), "apps": set(v["apps"])}
    seq = _seq(u, v, c["handoff_wd"], bc)
    n, d = F.wsum(_jac_terms(u, v, w) + [(w["seq"], seq.numerator, seq.denominator)])
    return F.nd_half_up(n, d, 4), F.half_up(seq, 1)


def _rec_kind(u: Mapping, v: Mapping, rel: float, seq: float, c: dict) -> str:
    if u["role"] == v["role"] and F.dec(rel) >= c["same"] and (_overlap(u, v) or seq == 1.0):
        return "same"
    if seq == 1.0:
        return "chain"
    if u["project"] != v["project"] and set(u["docs"]) & set(v["docs"]):
        return "ref"
    return "related"


def _neighbors(sets: Mapping[str, UnitSets], ids: list[str], same_role: bool, apps: bool = True):
    """연관 추천 후보: (a, {b > a — ids 순}) — 문서·동료·앱 중 하나라도 같이 가진 단위업무, 그리고 ``same_role`` 이면 같은
    역할 단위업무. 공유가 하나도 없는 쌍은 자카드 항이 모두 0 이라 연관도 ≤ seq 가중 — seq 가중이 문턱보다 작으면 같은
    역할이어도 추천이 될 수 없다. 그래서 예전의 모든 쌍 훑기(n² — 9개월 단위업무 8천 개면 3천만 쌍, W2 검토 C07)와 **같은
    후보**를 역색인으로 바로 얻는다. 쌍마다 한 번만 낸다(같은 쌍이 여러 열쇠를 공유해도). ``apps`` 가 거짓이면 앱 열쇠를
    빼고 문서·동료(·역할)로만 후보를 낸다 — 앱만 같이 가진 쌍이 추천이 될 수 없을 때(`recommendations` 가 판정, O-18④)."""
    inv: dict[tuple, list[str]] = defaultdict(list)
    pos: dict[str, list[tuple[tuple, int]]] = {}
    for a in ids:
        s = sets[a]
        keys = [("d", f) for f in s["docs"]] + [("p", p) for p in s["peers"]]
        if apps:
            keys += [("a", x) for x in s["apps"]]
        if same_role:
            keys.append(("r", s["role"]))
        mine = []
        for k in keys:
            lst = inv[k]
            mine.append((k, len(lst)))
            lst.append(a)
        pos[a] = mine
    for a in ids:
        nb: set[str] = set()
        for k, j in pos[a]:
            lst = inv[k]
            if j + 1 < len(lst):
                nb.update(lst[j + 1:])
        if nb:
            yield a, nb


_TOP_SLACK = 32          # 단위업무별 후보 목록이 이만큼 쌓이면 상위 REC_MAX 만 남긴다(메모리 — 전체 연관 쌍을 들고 있지 않는다)


def recommendations(sets: Mapping[str, UnitSets], cfg, *, bc=None) -> dict[str, list[dict]]:
    """단위업무마다 연관 업무 추천 최대 5개(R §4.6.3). 연관도 = Σ 가중·자카드(문서·동료·앱) + 가중·seq — 정확한 정수
    분수로 계산해 소수 4자리 half-up(`relatedness` 와 같은 값 · 같은 문턱 비교). seq 를 1 로 둔 상한이 문턱에 못 미치는
    쌍은 seq(근무일 계산)를 건너뛴다.

    큰 표본 성능(W2 검토 C07 — 3개월 단위업무 2,736개에서 보고서 빌드의 80%): 후보 쌍은 역색인(`_neighbors` — 예전 모든
    쌍 훑기와 같은 후보)으로, 쌍 계산은 공통 분모 정수 연산(분수 객체 없이)과 근무일 수 메모로, 결과는 단위업무별 상위
    목록만 들고 간다(전체 연관 쌍 사전을 만들지 않는다). 결과는 예전 구현과 같다(시험이 예전 구현과 대조)."""
    c = onto_cfg(cfg)
    w = c["w"]
    ids = sorted(sets)
    t = c["min_rel"]
    den = math.lcm(*(x.denominator for x in (w["doc"], w["peer"], w["app"], w["seq"], t)))
    wd_, wp_, wa_ = (int(x * den) for x in (w["doc"], w["peer"], w["app"]))   # 가중 × 공통 분모(정수)
    ws_, tn = int(w["seq"] * den), int(t * den)
    seq_half = {k: F.half_up(v, 1) for k, v in ((2, F.dec(1)), (1, F.dec("0.5")), (0, F.dec(0)))}   # seq×2 → 표시값
    hwd = c["handoff_wd"]
    wd_memo: dict[tuple, int] = {}
    P = {}
    for a in ids:
        s = sets[a]
        P[a] = (s["docs"], s["peers"], s["apps"], len(s["docs"]), len(s["peers"]), len(s["apps"]), s.get("role"),
                s.get("start_d"), s.get("end_d"), s.get("lead_end_d", s.get("end_d")),
                s.get("start") if s.get("start") is not None else -1)
    top: dict[str, list] = defaultdict(list)
    thr: dict[str, int] = {}                          # 단위업무 → 상위 목록 5위의 연관도 × 10⁴ 하한(목록을 자른 뒤에만)
    # 문서·동료를 하나도 같이 갖지 않은 쌍은 seq 가 인계(1)일 수 없어(인계는 문서·동료 공유가 조건) 연관도 ≤ 앱 가중 + seq
    # 가중/2 — 그것이 문턱보다 작으면 앱만 같이 가진 쌍은 추천이 될 수 없다(같은 결과). 흔한 앱(메일·메신저)은 거의 모든
    # 단위업무가 가져 후보 쌍이 n² 에 가까웠다(3개월 성능 밀도 보고서 빌드의 큰 몫 — O-18④).
    apps_ok = w["app"] + w["seq"] / 2 >= t
    for a, nb in _neighbors(sets, ids, w["seq"] >= t, apps_ok):
        da, pa, aa, nda, npa, naa, ra, sa, ea, la, sta = P[a]
        for b in nb:
            db, pb, ab, ndb, npb, nab, rb, sb, eb, lb, stb = P[b]
            # Σ (가중×공통 분모)·|∩|/|∪| = n/d (`F.wsum` 과 같은 값 — 교집합 0·가중 0 인 항은 0)
            n, d = 0, 1
            idoc = len(da & db)
            ipeer = len(pa & pb)
            if idoc and wd_:
                n, d = wd_ * idoc, nda + ndb - idoc
            if ipeer and wp_:
                u_ = npa + npb - ipeer
                n, d = n * u_ + wp_ * ipeer * d, d * u_
            if wa_:
                iapp = len(aa & ab)
                if iapp:
                    u_ = naa + nab - iapp
                    n, d = n * u_ + wa_ * iapp * d, d * u_
            if n + ws_ * d < tn * d:
                continue                              # seq = 1 이어도 문턱 미만 — 추천이 될 수 없다
            # seq = 1 상한의 소수 4자리 정수(반올림은 단조) — 양쪽 다 지금 5위보다 작으면 어느 쪽 상위 목록에도 못 든다
            q_ub = (2 * (n + ws_ * d) * 10000 + d * den) // (2 * d * den)
            if q_ub < thr.get(a, -1) and q_ub < thr.get(b, -1):
                continue
            s2 = 0                                    # seq × 2 (`_seq` 와 같은 판정: 인계 1 · 같은 역할 겹침 0.5 · 0)
            if idoc or ipeer:
                for e_, s_ in ((ea, sb), (eb, sa)):
                    if e_ is not None and s_ is not None and e_ <= s_:
                        k = (e_, s_)
                        v = wd_memo.get(k)
                        if v is None:
                            v = wd_memo[k] = _wd(bc, e_, s_)
                        if v <= hwd:
                            s2 = 2
                            break
            if not s2 and ra == rb and None not in (sa, la, sb, lb) and not (la < sb or lb < sa):
                s2 = 1
            num, dd = 2 * n + ws_ * s2 * d, 2 * d * den   # 연관도 = num/dd (정확)
            if num > 0 and num * den >= tn * dd:
                r = F.nd_half_up(num, dd, 4)
                q = (2 * num * 10000 + dd) // (2 * dd)    # r 의 소수 4자리 정수(= r × 10⁴)
                sv = seq_half[s2]
                for x, item in ((a, ((-r, stb, b), r, b, sv, q)), (b, ((-r, sta, a), r, a, sv, q))):
                    lst = top[x]
                    lst.append(item)
                    if len(lst) > _TOP_SLACK:
                        lst.sort()
                        del lst[REC_MAX:]
                        thr[x] = lst[-1][4]           # 지금 5위의 정수 연관도(이 뒤로 5위는 같거나 커진다 — 안전한 하한)
    out: dict[str, list[dict]] = {}
    for a in ids:
        cand = sorted(top.get(a, ()))
        if cand:
            u = sets[a]
            out[a] = [{"unit_id": b, "rel": r, "seq": s, "kind": _rec_kind(u, sets[b], r, s, c),
                       "shared": {"docs": len(u["docs"] & sets[b]["docs"]), "peers": len(u["peers"] & sets[b]["peers"]),
                                  "apps": len(u["apps"] & sets[b]["apps"])}} for _k, r, b, s, _q in cand[:REC_MAX]]
    return out


def _peer_node(who: str, cls: Mapping[str, str]) -> tuple[str, str]:
    k = cls.get(who, "unknown")
    if k in ("customer", "partner", "other"):
        return "c:ext:" + k, "ext:" + k
    return "c:" + who, who


def relations(ctx, pidx, sets: Mapping[str, UnitSets]) -> list[dict]:
    """단위업무 수준 관계 간선 전부(그래프·리뷰 관계 재료). 소속(구조)은 그래프에서 따로 만든다."""
    c = onto_cfg(ctx.cfg)
    out: list[dict] = []
    for uid in sorted(sets):
        s = sets[uid]
        u = ctx.units[uid]
        for who, rels in sorted(pidx.by_unit.get(uid, {}).items()):
            nid, _key = _peer_node(who, pidx.cls)
            for r in sorted(rels):
                w = int(pidx.weight.get((uid, who, r), 1))
                if r == "requester":
                    out.append({"from": nid, "to": uid, "rel": "의뢰함", "w": w, "h": u.effort_min, "inferred": False})
                elif r == "reporter":
                    out.append({"from": uid, "to": nid, "rel": "보고함", "w": w, "h": u.effort_min, "inferred": False})
            mt = [r for r in rels if r in ("thread", "meeting")]
            if mt:
                w = sum(int(pidx.weight.get((uid, who, r), 1)) for r in mt)
                out.append({"from": uid, "to": nid, "rel": "함께함", "w": w, "h": u.effort_min, "inferred": False})
        for f in sorted(s["docs"]):
            out.append({"from": uid, "to": "d:" + f, "rel": "산출함", "w": int(s["doc_w"].get(f, 0)),
                        "h": int(s["doc_min"].get(f, 0)), "inferred": False})
        for a in sorted(s["apps"]):
            out.append({"from": uid, "to": "a:" + a, "rel": "사용함", "w": int(s["app_w"][a]), "h": int(s["app_min"][a]),
                        "inferred": False})
    ho = handoffs(list(ctx.units.values()), ctx.bc, c["handoff_wd"], same_role=True,
                  peer_sets={k: set(v) for k, v in pidx.by_unit.items()},
                  doc_sets_={k: set(v["docs"]) for k, v in sets.items()})
    for b, (a, _gap, _via) in sorted(ho.items()):
        out.append({"from": a, "to": b, "rel": "선행함", "w": 1, "h": 0, "inferred": True})
    by_doc: dict[str, list[str]] = defaultdict(list)
    for uid in sorted(sets):
        for f in sets[uid]["docs"]:
            by_doc[f].append(uid)
    pair: Counter = Counter()
    for us in by_doc.values():
        for i, a in enumerate(us):
            for b in us[i + 1:]:
                pair[(a, b)] += 1
    for (a, b), n in sorted(pair.items()):
        out.append({"from": a, "to": b, "rel": "같은문서", "w": int(n), "h": 0, "inferred": True})
    merged: dict[tuple[str, str, str], dict] = {}
    for e in out:                                    # 외부 상대는 계급 노드 하나로 모이므로 같은 간선을 합친다(w 합, h 최대)
        k = (e["from"], e["to"], e["rel"])
        if k in merged:
            merged[k]["w"] += e["w"]
            merged[k]["h"] = max(merged[k]["h"], e["h"])
        else:
            merged[k] = dict(e)
    return list(merged.values())


def _node_key(nid: str) -> str:
    for p in ("d:", "a:", "c:"):
        if nid.startswith(p):
            return nid[len(p):]
    return nid


def project_graph(ctx, center: str, sets: Mapping[str, UnitSets], rels: list[dict], *, roles_wf=None) -> dict:
    """중심 과제 하나의 방사형 그래프 노드·간선(R §4.6.4)."""
    c = onto_cfg(ctx.cfg)
    units = [ctx.units[k] for k in sorted(sets) if ctx.units[k].project_key == center]
    units.sort(key=lambda u: (-u.effort_min, u.unit_id))
    keep_u = units[: c["max_units"]]
    more_u = units[c["max_units"]:]
    kept = {u.unit_id for u in keep_u}
    nodes = [{"id": center, "type": "P", "group": "work", "label": center, "key": center,
              "weight_min": sum(u.effort_min for u in units)}]
    edges = []
    role_min: Counter = Counter()
    for u in units:
        role_min[u.role_id] += u.effort_min
    for rid in sorted(role_min, key=lambda r: (-role_min[r], r)):
        u0 = next(u for u in units if u.role_id == rid)
        nodes.append({"id": rid, "type": "R", "group": "work", "key": rid, "weight_min": int(role_min[rid]),
                      "label": f"{V.field_name(u0.field, ctx.registry)} · {V.func_name(u0.func, ctx.registry)}"})
        edges.append({"from": rid, "to": center, "rel": "소속", "w": 0, "h": 0, "inferred": False})
    for u in sorted(keep_u, key=lambda u: (u.role_id, u.start if u.start is not None else -1, u.unit_id)):
        nodes.append({"id": u.unit_id, "type": "U", "group": "work", "key": u.unit_id, "label": u.title,
                      "weight_min": u.effort_min, "start": u.start_date.isoformat() if u.start_date else None})
        edges.append({"from": u.unit_id, "to": u.role_id, "rel": "소속", "w": 0, "h": 0, "inferred": False})
    if more_u:
        nodes.append({"id": "etc:U", "type": "U", "group": "work", "key": "", "label": "", "etc": len(more_u),
                      "weight_min": sum(u.effort_min for u in more_u)})
    outer_h: Counter = Counter()
    outer_w: Counter = Counter()
    ue = []
    for e in rels:
        a, b = e["from"], e["to"]
        if e["rel"] in ("선행함", "같은문서"):
            if a in kept and b in kept:
                ue.append(e)
            continue
        unit_end, other = (a, b) if a in kept else ((b, a) if b in kept else (None, None))
        if unit_end is None:
            continue
        outer_h[other] += int(e.get("h", 0))
        outer_w[other] += int(e.get("w", 0))
        ue.append(e)
    ranked = sorted(outer_h, key=lambda k: (-outer_h[k], -outer_w[k], TYPE_ORDER.get(_type(k), 9), k))
    top = set(ranked[: c["top_n"]])
    etc: dict[str, list[str]] = defaultdict(list)
    for k in ranked[c["top_n"]:]:
        etc[_type(k)].append(k)
    for k in sorted(top, key=lambda k: (TYPE_ORDER.get(_type(k), 9), -outer_h[k], k)):
        t = _type(k)
        nodes.append({"id": k, "type": t, "group": V.ONTO_NODES[t][1], "key": _node_key(k), "label": "",
                      "weight_min": int(outer_h[k]), "w": int(outer_w[k])})
    for t in ("D", "A", "C"):
        if etc.get(t):
            nodes.append({"id": "etc:" + t, "type": t, "group": V.ONTO_NODES[t][1], "key": "", "label": "",
                          "etc": len(etc[t]), "weight_min": sum(int(outer_h[k]) for k in etc[t])})
    for e in ue:
        if e["rel"] in ("선행함", "같은문서") or e["from"] in top or e["to"] in top:
            edges.append(dict(e))
    return {"center": center, "nodes": nodes, "edges": edges}


def _type(nid: str) -> str:
    if nid.startswith("d:"):
        return "D"
    if nid.startswith("a:"):
        return "A"
    if nid.startswith("c:"):
        return "C"
    return "U"


def _project_sets(sets: Mapping[str, UnitSets]) -> dict[str, dict]:
    out: dict[str, dict] = defaultdict(lambda: {"docs": set(), "peers": set(), "apps": set()})
    for s in sets.values():
        p = out[s["project"]]
        p["docs"] |= s["docs"]
        p["peers"] |= s["peers"]
        p["apps"] |= s["apps"]
    return out


def related_projects(center: str, sets: Mapping[str, UnitSets], cfg) -> list[dict]:
    """과제 간 연관도(seq 제외, 가중치 doc·peer·app 을 합 1 로 재정규화) 상위 3(R §4.6.4)."""
    c = onto_cfg(cfg)
    w = c["w"]
    tot = w["doc"] + w["peer"] + w["app"]
    if tot <= 0:
        return []
    ps = _project_sets(sets)
    if center not in ps:
        return []
    a = ps[center]
    out = []
    for k in sorted(ps):
        if k == center:
            continue
        b = ps[k]
        r = (w["doc"] * F.jaccard(a["docs"], b["docs"]) + w["peer"] * F.jaccard(a["peers"], b["peers"])
             + w["app"] * F.jaccard(a["apps"], b["apps"])) * F.per(1, tot)
        if r > 0:
            out.append({"key": k, "rel": F.half_up(r, 4),
                        "shared": {"docs": len(a["docs"] & b["docs"]), "peers": len(a["peers"] & b["peers"]),
                                   "apps": len(a["apps"] & b["apps"])}})
    out.sort(key=lambda x: (-x["rel"], x["key"]))
    return out[:3]


def default_center(ctx) -> str | None:
    """기본 중심 과제 = 기준 시각 달(기간 밖이면 기간 마지막 달)의 투입 최대 과제(동률 과제 키), 없으면 기간 전체 최대."""
    months = ctx.months()
    am = ctx.as_of_date().isoformat()[:7]
    m = am if am in months else (months[-1] if months else am)
    per: Counter = Counter()
    tot: Counter = Counter()
    for u in ctx.units.values():
        per[u.project_key] += u.by_month.get(m, 0)
        tot[u.project_key] += u.effort_min
    for cnt in (per, tot):
        best = sorted((k for k in cnt if cnt[k] > 0), key=lambda k: (-cnt[k], k))
        if best:
            return best[0]
    return None


def ontology_layer(ctx, pidx, *, center: str | None = None, roles_wf=None, sets=None, rels=None) -> dict:
    """모델 `ontology` 절: center · nodes · edges(중심 과제) · recs · related_projects · centers(과제 투입 순) ·
    graphs(다른 과제 그래프). 단위업무 0 개면 빈 절. sets·rels 를 주면 다시 계산하지 않는다."""
    if sets is None:
        sets = unit_set_map(ctx, pidx)
    if rels is None:
        rels = relations(ctx, pidx, sets)
    recs = recommendations(sets, ctx.cfg, bc=ctx.bc)
    tot: Counter = Counter()
    for u in ctx.units.values():
        tot[u.project_key] += u.effort_min
    centers = [k for k in sorted(tot, key=lambda k: (-tot[k], k)) if tot[k] > 0]
    cen = center if center in tot else default_center(ctx)
    if cen is None:
        return {"center": None, "nodes": [], "edges": [], "recs": recs, "related_projects": [], "centers": [],
                "graphs": {}}
    g = project_graph(ctx, cen, sets, rels, roles_wf=roles_wf)
    graphs = {}
    for k in centers:
        if k != cen:
            gk = project_graph(ctx, k, sets, rels, roles_wf=roles_wf)
            graphs[k] = {"nodes": gk["nodes"], "edges": gk["edges"], "related_projects": related_projects(k, sets, ctx.cfg)}
    return {"center": cen, "nodes": g["nodes"], "edges": g["edges"], "recs": recs,
            "related_projects": related_projects(cen, sets, ctx.cfg), "centers": centers, "graphs": graphs}


def unit_set_map(ctx, pidx) -> dict[str, UnitSets]:
    """리뷰·서브에이전트가 쓰는 단위업무 관계 재료(ontology_layer 와 같은 계산)."""
    c = onto_cfg(ctx.cfg)
    return {uid: unit_sets(u, ctx.log, pidx.by_unit.get(uid, {}), c["app_min"], ctx.as_of_min)
            for uid, u in sorted(ctx.units.items())}
