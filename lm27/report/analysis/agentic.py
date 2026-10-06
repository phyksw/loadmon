# -*- coding: utf-8 -*-
r"""Agentic 매칭과 새 니즈(R §4.7 · §6.7 · 부록 A, 결정 §10.5 · 계약 §3.16 agentic 절 · §3.18 agentic · D-19).

- 카탈로그 = 팀 레지스트리 `agents[]`(유효 레지스트리 — 저장소 기본은 중립 예시뿐). 비면 매칭 없이 니즈 후보만.
- 항목(R §4.7.2) = 사람의 모든 RoleWorkflow 에서 단계 유형 c 마다 하나: type · label(코파일럿 단계 라벨 중 가장 많이 쓰인 것,
  동률은 역할 투입 큰 쪽, 없으면 한글명) · occ_week(c 의 정리된 흔적 항목 수 / 투입한 ISO 주 수) · freq(주 3회 이상 ·
  주 1~2회 · 월 몇 회 · 드묾) · io('{디지털|대면} 입력·{정형|비정형} 출력' — §4.8 D·S) · apps(앱 범주 한글명 상위 2) ·
  ws(역할 업무 최대 4개 '과제 ID 기능명') · units · related_min(c 의 Run 분 — 실측, 점 단계는 0).
- 규칙 사전 점수(R §4.7.3) = 0.5·[유형 일치] + 0.2·[입력 토큰] + 0.2·[출력 토큰] + 0.1·[핵심어 ↔ 단위업무 제목] —
  토큰은 W §4.1 `raw_tokens`, 부분 문자열 일치 `tok_sim > 0`. 등급 상(≥ gradeHigh) · 중(≥ gradeMid) · 하(> 0) · 없음.
- 매칭 확정(R §4.7.4): 코파일럿 답(`m[{a, fit, why}]`)이 있으면 그 등급, 규칙 등급과 2단계 이상 다르면 `disagree`. 답이 없으면
  규칙 등급(출처 `rule`). 관련 투입은 실측 Run 분뿐 — '대신할 수 있는 양' 같은 추정 수치를 만들지 않는다(RP4).
- 새 니즈(R §4.7.5): 코파일럿 `need` 그대로(AI) + 규칙 니즈(빈도 주 1회 이상 ∧ D = 1 ∧ 서브에이전트 단계 판정 ≥ 조건부 ∧ 등급
  ≥ 중 인 에이전트 없음). need_id = 'n_' + sha1(type + '|' + ukey(이름))[:6], 카탈로그 이름과 ukey 가 같으면 버림.

설정(R §10.2): `report.agentic.gradeHigh` · `gradeMid`. 표준 라이브러리만 쓴다. 나눗셈은 `fmt` 로만. 파일을 쓰지 않는다.
"""
from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping

from lm27.report import fmt as F
from lm27.report import vocab as V
from lm27.vocab import steps as S

__all__ = ["LVL", "agentic_layer", "freq_of", "items_of", "need_id", "rule_grade", "rule_score", "team_matches"]

LVL = {"상": 3, "중": 2, "하": 1, "": 0}
WEEKS_PER_MONTH = "4.345"
APPS_MAX = 30
LABEL_MAX = 20
IO_MAX = 30
WS_MAX = 4
NEED_NAME_MAX = 40
_SPLIT = re.compile(r"[·→,;/|]+")


def agentic_cfg(cfg) -> dict:
    return {"high": F.dec(cfg["report.agentic.gradeHigh"]), "mid": F.dec(cfg["report.agentic.gradeMid"])}


def _toks(parts: Iterable[str]) -> set[str]:
    from lm27.time.tokens import raw_tokens     # W §4.1 토큰 단일원
    return raw_tokens([_SPLIT.sub(" ", str(p or "")) for p in parts])


def _hit(a: set[str], b: set[str]) -> bool:
    from lm27.time.tokens import tok_sim
    return bool(a) and bool(b) and tok_sim(a, b) > 0


def rule_score(agent: Mapping, item: Mapping) -> float:
    """R §4.7.3 규칙 사전 점수(0~1, 소수 2자리). item = {type, inputs[낱말], outputs[낱말], titles[제목]}."""
    s = F.dec(0)
    if item.get("type") in set(agent.get("step_types") or ()):
        s += F.dec("0.5")
    if _hit(_toks(agent.get("inputs") or ()), _toks(item.get("inputs") or ())):
        s += F.dec("0.2")
    if _hit(_toks(agent.get("outputs") or ()), _toks(item.get("outputs") or ())):
        s += F.dec("0.2")
    if _hit(_toks(agent.get("keywords") or ()), _toks(item.get("titles") or ())):
        s += F.dec("0.1")
    return F.half_up(s, 2)


def rule_why(agent: Mapping, item: Mapping) -> list[str]:
    """규칙 이유 칩 코드(type·input·output·keyword — vocab.RULE_WHY)."""
    out = []
    if item.get("type") in set(agent.get("step_types") or ()):
        out.append("type")
    if _hit(_toks(agent.get("inputs") or ()), _toks(item.get("inputs") or ())):
        out.append("input")
    if _hit(_toks(agent.get("outputs") or ()), _toks(item.get("outputs") or ())):
        out.append("output")
    if _hit(_toks(agent.get("keywords") or ()), _toks(item.get("titles") or ())):
        out.append("keyword")
    return out


def rule_grade(score, cfg) -> str:
    c = agentic_cfg(cfg)
    s = F.dec(score)
    if s >= c["high"]:
        return "상"
    if s >= c["mid"]:
        return "중"
    if s > 0:
        return "하"
    return ""


def freq_of(occ: int, weeks: int) -> tuple[str, object]:
    """(빈도 등급, occ_week 유리수) — R §4.7.2."""
    ow = F.per(occ, max(1, weeks))
    if ow >= 3:
        f = V.FREQ[0]
    elif ow >= 1:
        f = V.FREQ[1]
    elif ow * F.dec(WEEKS_PER_MONTH) >= 1:
        f = V.FREQ[2]
    else:
        f = V.FREQ[3]
    return f, ow


def need_id(step_type: str, name: str) -> str:
    """'n_' + sha1(type + '|' + ukey(이름))[:6](같은 니즈는 재분석해도 같은 ID — 계약 §3.18)."""
    from lm27.hier.names import ukey
    return "n_" + hashlib.sha1(f"{step_type}|{ukey(name)}".encode()).hexdigest()[:6]


def _proj_field(u) -> str:
    if u.project_id:
        return u.project_id
    return "NEW" if u.project_key and u.project_key != "UNC" else "NONE"


def _cat(app: str) -> str:
    from lm27.catalog import cat_of
    return cat_of(app) or ""


def items_of(ctx, roles_wf: Mapping[str, dict], traces: Mapping[str, Mapping[str, list]], person_rows: Mapping) -> list[dict]:
    """단계 유형별 항목(R §4.7.2). 반환 항목에는 규칙 점수 재료(inputs·outputs·titles — 모델에 싣지 않음)도 있다."""
    weeks = len({F.iso_week(d) for u in ctx.units.values() for d, m in u.by_date.items() if m > 0})
    by_code: dict[str, list[str]] = defaultdict(list)
    for rid, rw in roles_wf.items():
        for s in rw["steps"]:
            by_code[s["code"]].append(rid)
    out = []
    for code in sorted(by_code, key=lambda k: (S.STEP_TYPES[k].order if k in S.STEP_TYPES else 99, k)):
        rids = sorted(by_code[code], key=lambda r: (-int(roles_wf[r].get("effort_min", 0)), r))
        labels: Counter = Counter()
        lab_eff: dict[str, int] = {}
        occ = 0
        run_sec = 0
        cat_sec: Counter = Counter()
        ext: Counter = Counter()
        prev: set[str] = set()
        units: set[str] = set()
        for rid in rids:
            rw = roles_wf[rid]
            st = next(s for s in rw["steps"] if s["code"] == code)
            if st.get("label_by") in ("ai", "manual") and st.get("label"):
                labels[st["label"]] += 1
                lab_eff[st["label"]] = max(lab_eff.get(st["label"], 0), int(rw.get("effort_min", 0)))
            no = st["no"]
            for e in list(rw.get("edges", ())) + list(rw.get("edges_rest", ())):
                if e[1] == no:
                    p = next((s for s in rw["steps"] if s["no"] == e[0]), None)
                    if p is not None:
                        prev.add(V.step_name(p["code"], ctx.registry))
            for uid, tr in traces.get(rid, {}).items():
                for x in tr:
                    if x.code != code:
                        continue
                    occ += 1
                    units.add(uid)
                    for it in x.items:
                        if it.kind != "A":
                            continue
                        run_sec += it.sec
                        for a, sv in it.apps:
                            cat = _cat(a)
                            if cat:
                                cat_sec[cat] += sv
                        for f, sv in it.fams:
                            g = ctx.doc_class(f)
                            if g:
                                ext[g] += sv
        freq, ow = freq_of(occ, weeks)
        prow = person_rows.get(code, {})
        flags = (prow.get("score") or {}).get("flags", {})
        io = f"{'디지털' if flags.get('D') else '대면'} 입력·{'정형' if flags.get('S') else '비정형'} 출력"
        label = sorted(labels, key=lambda k: (-labels[k], -lab_eff.get(k, 0), k))[0] if labels else \
            V.step_name(code, ctx.registry)
        cats = [k for k, _v in sorted(cat_sec.items(), key=lambda kv: (-kv[1], kv[0]))][:2]
        apps = "·".join(cats)[:APPS_MAX] if cats else V.step_name(code, ctx.registry)[:APPS_MAX]
        ws = []
        for rid in rids[:WS_MAX]:
            u0 = next((ctx.units[u] for u in roles_wf[rid]["units"] if u in ctx.units), None)
            if u0 is not None:
                ws.append(f"{_proj_field(u0)} {V.func_name(u0.func, ctx.registry)}")
        exts = [V.EXT_CLASS_NAMES[g] for g, _v in sorted(ext.items(), key=lambda kv: (-kv[1], kv[0]))
                if g in V.EXT_CLASS_NAMES]
        titles = [ctx.units[u].title for u in sorted(units) if u in ctx.units]
        out.append({"type": code, "label": label[:LABEL_MAX], "occ": occ, "occ_week": F.half_up(ow, 2), "freq": freq,
                    "io": io[:IO_MAX], "apps": apps, "ws": ws, "units": sorted(units),
                    "related_min": F.sec_min(run_sec), "roles": rids,
                    "inputs": ["디지털" if flags.get("D") else "대면", *cats, *sorted(prev)],
                    "outputs": [V.step_name(code, ctx.registry), *exts], "titles": titles,
                    "D": int(flags.get("D", 0)), "verdict": (prow.get("score") or {}).get("verdict", ""),
                    "per_month": F.half_up(ow * F.dec(WEEKS_PER_MONTH), 1)})
    out.sort(key=lambda it: (-it["occ_week"], S.STEP_TYPES[it["type"]].order if it["type"] in S.STEP_TYPES else 99))
    return out


PUBLIC_ITEM = ("type", "label", "occ_week", "freq", "io", "apps", "ws", "units", "related_min")


def agentic_layer(ctx, roles_wf: Mapping[str, dict], traces: Mapping[str, Mapping[str, list]], person_rows: Mapping,
                  answers: Mapping[str, tuple] | None = None) -> dict:
    """모델 `agentic` 절 + RoleWorkflow Step.agent_grade(그 단계 유형의 최고 등급)."""
    from lm27.hier.names import ukey
    cat = ctx.catalog
    its = items_of(ctx, roles_wf, traces, person_rows)
    matches = []
    best: dict[str, str] = {}
    ai_needs = []
    for it in its:
        got = (answers or {}).get("ag:" + it["type"])
        ans, by = (got if got else (None, "rule"))
        if str(by) not in ("ai", "manual"):
            ans = None              # 규칙 답(브리지 폴백·rule_pending)은 코파일럿 의견이 아니다 — 등급은 R §4.7.3 규칙 사전 점수
        ai_m: dict[str, Mapping] = {}
        if isinstance(ans, Mapping):
            for m in ans.get("m") or ():
                if isinstance(m, Mapping) and str(m.get("a") or "") and str(m.get("a")) not in ai_m:
                    ai_m[str(m.get("a"))] = m
            nd = ans.get("need")
            if isinstance(nd, Mapping) and str(nd.get("name") or "").strip():
                ai_needs.append((it, nd, str(by or "ai")))
        for a in cat:
            sc = rule_score(a, it)
            rg = rule_grade(sc, ctx.cfg)
            if isinstance(ans, Mapping):
                m = ai_m.get(a["id"])
                g = str(m.get("fit") or "") if m is not None else ""
                g = g if g in LVL else ""
                mby = str(by or "ai")
                why_ai = str(m.get("why") or "")[:40] if m is not None else ""
            else:
                g, mby, why_ai = rg, "rule", ""
            dis = isinstance(ans, Mapping) and abs(LVL[g] - LVL[rg]) >= 2
            if not g and not dis:
                continue
            matches.append({"agent_id": a["id"], "step_type": it["type"], "grade": g, "by": mby, "why_ai": why_ai,
                            "why_rule": rule_why(a, it), "rule_grade": rg, "rule_score": sc, "roles": list(it["roles"]),
                            "units": list(it["units"]), "related_min": it["related_min"], "disagree": bool(dis)})
            if g and LVL[g] > LVL.get(best.get(it["type"], ""), 0):
                best[it["type"]] = g
    matches.sort(key=lambda m: (m["agent_id"], S.STEP_TYPES[m["step_type"]].order if m["step_type"] in S.STEP_TYPES
                                else 99))
    for rw in roles_wf.values():
        for s in rw["steps"]:
            s["agent_grade"] = best.get(s["code"], "")
    agents = []
    for a in cat:
        ms = [m for m in matches if m["agent_id"] == a["id"] and m["grade"]]
        if not ms:
            continue
        g = max((m["grade"] for m in ms), key=lambda x: LVL[x])
        agents.append({"agent_id": a["id"], "grade": g, "step_types": [m["step_type"] for m in ms],
                       "related_min": sum(m["related_min"] for m in ms),
                       "units": sorted({u for m in ms for u in m["units"]})})
    related_total = sum(it["related_min"] for it in its if best.get(it["type"]))
    cat_names = {ukey(a["name"]) for a in cat}
    needs: dict[str, dict] = {}
    for it, nd, by in ai_needs:
        name = str(nd.get("name") or "").strip()[:NEED_NAME_MAX]
        if ukey(name) in cat_names:
            continue
        nid = need_id(it["type"], name)
        needs.setdefault(nid, _need_row(nid, it, name, str(nd.get("logic") or "")[:80], str(nd.get("in") or "")[:40],
                                        str(nd.get("out") or "")[:40], by))
    for it in its:
        if it["freq"] not in V.FREQ[:2] or not it["D"] or it["verdict"] not in ("적합", "조건부"):
            continue
        if LVL.get(best.get(it["type"], ""), 0) >= LVL["중"]:
            continue
        nm = V.step_name(it["type"], ctx.registry)
        name = f"{nm} 자동화"[:NEED_NAME_MAX]
        if ukey(name) in cat_names:
            continue
        nid = need_id(it["type"], name)
        logic = f"{it['apps']} 로 하는 {nm} 단계를 입력 → 출력으로 자동화"
        needs.setdefault(nid, _need_row(nid, it, name, logic[:80], it["io"].split("·")[0],
                                        it["io"].split("·")[-1], "rule"))
    return {"catalog_version": str(_reg_get(ctx.registry, "catalog_version", "") or ""), "catalog_n": len(cat),
            "items": [{k: it[k] for k in PUBLIC_ITEM} for it in its], "matches": matches, "agents": agents,
            "needs": sorted(needs.values(), key=lambda n: (-LVL.get(n["grade"], 0), n["step_type"], n["need_id"])),
            "related_min_total": related_total,
            "warnings": [] if cat else [V.warn("catalog_empty")]}


def _need_row(nid: str, it: Mapping, name: str, logic: str, i: str, o: str, by: str) -> dict:
    if it["freq"] == V.FREQ[0] and it["verdict"] == "적합":
        grade = "상"
    elif it["freq"] in V.FREQ[2:]:
        grade = "하"
    else:
        grade = "중"
    return {"need_id": nid, "step_type": it["type"], "name": name, "label": name, "logic": logic, "in": i, "out": o,
            "by": by, "grade": grade, "freq_per_month": it["per_month"], "units": list(it["units"])}


def _reg_get(reg, k, d=None):
    if reg is None:
        return d
    return reg.get(k, d) if isinstance(reg, Mapping) else getattr(reg, k, d)


def team_matches(agentic: Mapping, roles_wf: Mapping[str, dict]) -> list[dict]:
    """팀 묶음 `agentic.matches[]` = (agent_id, role_id, step_type, grade, units)로 펼친 것(R §4.7.4 — 개인 = 팀)."""
    out = []
    for m in agentic.get("matches", ()):
        if not m.get("grade"):
            continue
        for rid in m.get("roles", ()):
            rw = roles_wf.get(rid)
            if rw is None:
                continue
            us = sorted(set(m.get("units", ())) & set(rw.get("units", ())))
            out.append({"agent_id": m["agent_id"], "role_id": rid, "step_type": m["step_type"], "grade": m["grade"],
                        "units": us})
    return sorted(out, key=lambda x: (x["agent_id"], x["role_id"], x["step_type"]))
