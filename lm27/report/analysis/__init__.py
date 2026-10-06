# -*- coding: utf-8 -*-
r"""보고서 분석층(R §4 · §2.1 · §9.2.3 · 부록 A, 계약 §2.14 · §3.16) — 결정적 산식만.

시간 코어 결과(`time\*` — `timecore/1.1`)와 분류 라벨(`hier\*` — `hier/1`), 코파일럿 답(`ai_out`), 레지스트리·사람 사전을 읽어
보고서 모델의 분석 절(워크플로우 · 리뷰 · 동료 · 온톨로지 · agentic · 서브에이전트 · 측정 품질)을 만든다. **새 시간을 만들지
않는다**(귀속된 분을 다시 나눌 뿐 — RP1). 코파일럿은 이름·설명·문장만, 판정 수치는 규칙이 계산한다(RP3 · D-19).

    from lm27.report.analysis import analyze, make_context
    ctx = make_context(tasks=…, attrib=…, tables=…, cal=…, cfg=…, labels=…, registry=…, env_slots=…, day_ledger=…,
                       run_meta=…, person_dir=…, evidence=…, ai={stage: ai_out}, period=(d0, d1))
    sec = analyze(ctx)      # {"workflows", "reviews", "peers", "ontology", "agentic", "subagent", "quality", "flags", "team"}

만드는 순서(R §9.2.3): 활동 로그(activity) → 역할 워크플로우(mining) → workflow_label 답 반영 → 동료(peers) → 서브에이전트
(subagent — 규칙 → subagent_review 답) → agentic(단계 유형 항목 → agentic_match 답 → 매칭·니즈) → 온톨로지(ontology) →
리뷰(review → review_text 답) → 측정 품질(quality). 답이 없으면 브리지 단계 `fallback()` 한 벌(R §4.10.3).

모듈: `activity`(로그·문맥) · `mining` · `review` · `peers` · `ontology` · `agentic` · `subagent` · `quality` · `ai_items`
(ai_in 쓰기 — cli `report ai-items`). 이 `__init__` 은 하위 모듈을 최상위에서 import 하지 않는다(가벼운 import — CR-09 규칙과
같은 방식). 표준 라이브러리만 쓴다. 파일을 쓰지 않는다(쓰기는 `ai_items.write_ai_items` 하나).
"""
from __future__ import annotations

__all__ = ["ANALYSIS_VERSION", "AnalysisCtx", "analyze", "make_context", "write_ai_items"]

ANALYSIS_VERSION = "report/1"


def __getattr__(name: str):
    if name in ("AnalysisCtx", "make_context"):
        from lm27.report.analysis import activity
        return getattr(activity, name)
    if name == "write_ai_items":
        from lm27.report.analysis.ai_items import write_ai_items
        return write_ai_items
    raise AttributeError(f"module 'lm27.report.analysis' has no attribute {name!r}")


def _sources(counts: dict) -> dict:
    """라벨 출처 집계 {ai, manual, rule}(rule_pending 은 rule 로 센다 — R §3.5 머리 띠)."""
    out = {"ai": 0, "manual": 0, "rule": 0}
    for k, v in counts.items():
        out["manual" if k == "manual" else ("ai" if k == "ai" else "rule")] += int(v)
    return out


def analyze(ctx) -> dict:
    """분석 문맥 → 모델 분석 절들. 같은 문맥이면 같은 결과(G-R1)."""
    from lm27.report import vocab as V
    from lm27.report.analysis import agentic, ai_items, mining, ontology, peers, quality, review, subagent
    from collections import Counter

    wf, traces = mining.workflows(ctx)
    wl_ans = ai_items.answers(ctx, "workflow_label", ai_items.workflow_items(ctx, wf))
    label_counts = mining.apply_labels(wf["roles"], wl_ans, ctx.registry)
    for rw in wf["roles"].values():
        rw["sentences"] = mining.role_sentences(rw, ctx.bc.std_day_min)
    pidx = peers.peer_index(ctx.units.values(), ctx.evidence, ctx.person_dir, ctx.cfg, registry=ctx.registry)
    pe = peers.peers_section(pidx, ctx.units, ctx.cfg, as_of_min=ctx.as_of_min)
    sub0 = subagent.subagent_layer(ctx, wf["roles"], traces, pidx, answers=None)
    sa_ans = ai_items.answers(ctx, "subagent_review", ai_items.subagent_items(ctx, wf, sub0))
    sub = subagent.subagent_layer(ctx, wf["roles"], traces, pidx, answers=sa_ans)
    rows = subagent.person_step_rows(ctx, wf["roles"], traces, pidx)
    its = agentic.items_of(ctx, wf["roles"], traces, rows)
    ag_ans = ai_items.answers(ctx, "agentic_match", ai_items.agentic_items(ctx, its))
    ag = agentic.agentic_layer(ctx, wf["roles"], traces, rows, ag_ans)
    sets = ontology.unit_set_map(ctx, pidx)
    rels = ontology.relations(ctx, pidx, sets)
    onto = ontology.ontology_layer(ctx, pidx, roles_wf=wf["roles"], sets=sets, rels=rels)
    rv = review.review_periods(ctx, wf=wf, pidx=pidx, rels=rels)
    rv_counts = review.attach_ai(rv, ai_items.answers(ctx, "review_text", ai_items.review_items(ctx, rv, pidx)))
    q = quality.quality_layer(ctx)
    sa_counts = Counter(str((r.get("ai") or {}).get("by") or "rule") for r in sub["roles"])
    ag_counts = Counter(m["by"] for m in ag["matches"])
    sources = {"workflow_label": _sources(label_counts), "subagent_review": _sources(sa_counts),
               "agentic_match": _sources(ag_counts), "review_text": _sources(rv_counts)}
    tot_ai = sum(v["ai"] + v["manual"] for v in sources.values())
    tot = sum(sum(v.values()) for v in sources.values())
    copilot = "rule_only" if tot_ai == 0 else ("ai" if tot_ai == tot else "partial")
    warnings = list(ctx.warnings) + list(pe.pop("warnings", [])) + list(ag.pop("warnings", []))
    if not ctx.units:
        warnings.append(V.warn("units_empty"))
    seen, uniq = set(), []
    for w in warnings:
        if w["code"] not in seen:
            seen.add(w["code"])
            uniq.append(w)
    return {"workflows": wf, "reviews": rv, "peers": pe, "ontology": onto, "agentic": ag, "subagent": sub,
            "quality": q,
            "flags": {"copilot": copilot, "label_sources": sources, "warnings": uniq, "mining_coarse": ctx.log.coarse},
            "team": {"agentic_matches": agentic.team_matches(ag, wf["roles"]),
                     "subagents": [{"role_id": r["role_id"], "fit": r["final"], "chain": r["chain"]}
                                   for r in sub["roles"]]}}
