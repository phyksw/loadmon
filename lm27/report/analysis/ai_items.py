# -*- coding: utf-8 -*-
r"""코파일럿 단계 입력 `ai_in` 만들기 · `ai_out` 반영 · 폴백 한 벌(R §4.10 · §2.4.1, 계약 §2.14 · §3.17 · §7.1 · B §2.5 · §8.4~§8.7).

- 단계 4종: `workflow_label`(역할 업무 1개 — 키 `ws:<role_id>`) · `agentic_match`(단계 유형 1개 — `ag:<type>`) ·
  `subagent_review`(역할 업무 1개 — `sa:<role_id>`) · `review_text`(주·달 1개 — `review:week:YYYY-Www` · `review:month:YYYY-MM`).
  키는 실행이 바뀌어도 같은 대상이면 같다. `fields` 는 정제된 필드만(B §2.5 — 단계 `send_fields` 밖 키는 브리지가 버림),
  `rule` 은 폴백 재료(보내지 않음), `meta` 는 항목 게이트용(보내지 않음).
- **시간·MM 은 보내지 않는다**(B1 · G-B8 · L-18): steps 의 세 번째 값은 지지도(건수), freq 는 등급 문구. 단위업무 제목 안의
  시간 숫자 표현은 지운다(`review.scrub_time`).
- `answers(ctx, stage, items)`: `ai_out` 의 항목 답(`items[key].ans`·`by`)이 있으면 그것, 없으면 **브리지 단계 정의의
  `fallback()` 한 벌**(`lm27.bridge.stages.REGISTRY[stage].fallback(item, ctx, why="no_ai_out")` — 결과 by = rule).
  같은 규칙을 보고서 쪽에 다시 쓰지 않는다(RP3 · G-R12). 브리지 단계 모듈이 아직 없으면 답 없음(단계 한글명 라벨 + 경고).
- `write_ai_items(run_id, stage=None) -> {stage: 건수}`(계약 §7.1 cli 어댑터 — 합 0 이면 rc 4): 입력을 단일 로더
  (`lm27.report.inputs.load_inputs` — WP-31)로 읽어 분석 문맥을 만들고 `data\derived\ai_in\<stage>.jsonl` 을 원자 쓰기.

표준 라이브러리만 쓴다. 쓰기는 `lm27.util.fsx.atomic_write`, 경로는 `lm27.paths` 로만(L-07 · L-08).
"""
from __future__ import annotations

import importlib
import importlib.util
from collections.abc import Iterable, Mapping
from types import SimpleNamespace

from lm27.report import vocab as V
from lm27.report.analysis.review import scrub_time
from lm27.report.analysis.subagent import flags_text

__all__ = ["STAGES", "agentic_items", "answers", "bridge_fallback", "build_items", "context_from_inputs",
           "review_items", "subagent_items", "workflow_items", "write_ai_items"]

STAGES = ("workflow_label", "agentic_match", "subagent_review", "review_text")
SRC_VER = "report/1"
STEPS_MAX = 8
TRANS_MAX = 6
TASKS_MAX = 5
PEERS_MAX = 8
TITLE_MAX = 40


def _get(o, k, d=None):
    if o is None:
        return d
    v = o.get(k, d) if isinstance(o, Mapping) else getattr(o, k, d)
    return d if v is None else v


def _meta() -> dict:
    from lm27.privacy import RULES_VERSION        # 정제 규칙 판(항목 게이트 meta — 보내지 않음)
    return {"priv_class": "work", "ad_band": "keep", "rules_ver": str(RULES_VERSION)}


def _proj(u) -> str:
    if u.project_id:
        return u.project_id
    return "NEW" if u.project_key and u.project_key != "UNC" else "NONE"


def _role_unit(ctx, rw):
    return next((ctx.units[u] for u in rw["units"] if u in ctx.units), None)


# ───────────────────────────── 항목 만들기(R §4.10.1) ─────────────────────────────
def workflow_items(ctx, wf: Mapping) -> list[dict]:
    """workflow_label — 역할 업무마다: project·field·func · steps[[S, 단계 코드, 지지도]] ≤ 8 · trans 상위 6 · tasks(투입 상위
    5 단위업무 제목)."""
    out = []
    meta = _meta()
    for rid, rw in sorted(wf.get("roles", {}).items()):
        u0 = _role_unit(ctx, rw)
        if u0 is None or not rw["steps"]:
            continue
        us = sorted((ctx.units[u] for u in rw["units"] if u in ctx.units), key=lambda u: (-u.effort_min, u.unit_id))
        edges = list(rw.get("edges", ())) + list(rw.get("edges_rest", ()))
        fields = {"project": _proj(u0), "field": u0.field, "func": u0.func,
                  "steps": [[f"S{s['no']}", s["code"], int(s["n"])] for s in rw["steps"][:STEPS_MAX]],
                  "trans": [[f"S{i}", f"S{j}", int(n)] for i, j, n in edges[:TRANS_MAX]],
                  "tasks": [scrub_time(u.title)[:TITLE_MAX] for u in us[:TASKS_MAX] if scrub_time(u.title)]}
        rule = {"func_name": V.func_name(u0.func, ctx.registry),
                "step_names": {f"S{s['no']}": V.step_name(s["code"], ctx.registry) for s in rw["steps"]}}
        out.append({"key": "ws:" + rid, "group": u0.project_key, "fields": fields, "rule": rule, "src_ver": SRC_VER,
                    "meta": meta})
    return out


def agentic_items(ctx, items: Iterable[Mapping]) -> list[dict]:
    """agentic_match — 단계 유형마다: type · label(≤ 20) · freq · io(≤ 30) · apps(≤ 30) · ws(≤ 4)."""
    meta = _meta()
    out = []
    for it in sorted(items, key=lambda x: x["type"]):
        fields = {"type": it["type"], "label": scrub_time(it["label"])[:20], "freq": it["freq"], "io": it["io"][:30],
                  "apps": it["apps"][:30], "ws": list(it["ws"])[:4]}
        out.append({"key": "ag:" + it["type"], "group": "", "fields": fields,
                    "rule": {"catalog": [a["id"] for a in ctx.catalog]}, "src_ver": SRC_VER, "meta": meta})
    return out


def subagent_items(ctx, wf: Mapping, sub: Mapping) -> list[dict]:
    """subagent_review — 역할 업무마다: project · role(코파일럿 역할 한 줄, 없으면 '분야·기능') ·
    steps[[S, 단계 라벨, 단계 코드, 'D1 R1 B0 L1 S1 T1']](B-1 → subagent_review/1.1)."""
    meta = _meta()
    rows = {r["role_id"]: r for r in sub.get("roles", ())}
    out = []
    for rid, rw in sorted(wf.get("roles", {}).items()):
        u0 = _role_unit(ctx, rw)
        sr = rows.get(rid)
        if u0 is None or sr is None or not rw["steps"]:
            continue
        # 코파일럿이 답한 역할 한 줄만 쓴다. 규칙 답(브리지 폴백 — role '판단 유보' 자리표)은 역할 이름이 아니다(W2 통합)
        ai_role = rw.get("ai_role") if rw.get("ai_by") in ("ai", "manual", "rule_pending") else ""
        role = ai_role or f"{V.field_name(u0.field, ctx.registry)}·{V.func_name(u0.func, ctx.registry)}"
        fl = {r["no"]: r["flags"] for r in sr["steps"]}
        steps = [[f"S{s['no']}", scrub_time(s["label"])[:20], s["code"], flags_text(fl.get(s["no"], {}))]
                 for s in rw["steps"]]
        out.append({"key": "sa:" + rid, "group": u0.project_key,
                    "fields": {"project": _proj(u0), "role": scrub_time(role)[:40], "steps": steps},
                    "rule": {"verdict": sr["rule"], "fit_share": sr["fit_share"]}, "src_ver": SRC_VER, "meta": meta})
    return out


def review_items(ctx, reviews: Mapping, pidx=None) -> list[dict]:
    """review_text — 주·달마다: kind · period · facts ≤ 25 · peers ≤ 8 · edges ≤ 12(달만). 번호표 → who_key 는 rule.peers_map.
    월 edges 의 동료 번호표는 그 질의 안 번호(R §3.6 — 화면에 낼 때 peers_map → who_key → 로컬 이름)."""
    from lm27.report.analysis.review import period_peers
    meta = _meta()
    out = []
    for kind, rows in (("week", reviews.get("weeks", ())), ("month", reviews.get("months", ()))):
        for r in rows:
            if not r.get("facts"):
                continue
            a = (r.get("partial") or {}).get("from", r["from"])
            b = (r.get("partial") or {}).get("to", r["to"])
            umin = {x["unit_id"]: int(x["min"]) for x in r.get("active", ())}
            pp = period_peers(pidx, umin, PEERS_MAX) if pidx is not None else list(r.get("peers_top", ()))
            peers, pmap = [], {}
            for i, p in enumerate(pp[:PEERS_MAX]):
                tag = f"동료{i + 1}"
                peers.append([tag, int(p["units"])])
                pmap[tag] = p["key"]
            fields = {"kind": kind, "period": f"{a}~{b}", "facts": [list(f) for f in r["facts"]], "peers": peers}
            if kind == "month":
                fields["edges"] = [list(e) for e in r.get("edges", ())]
            out.append({"key": f"review:{kind}:{r['key']}", "group": "", "fields": fields,
                        "rule": {"peers_map": pmap, "fact_units": dict(r.get("fact_units", {}))}, "src_ver": SRC_VER,
                        "meta": meta})
    return out


# ───────────────────────────── 답 반영·폴백(R §4.10.2·§4.10.3) ─────────────────────────────
def bridge_fallback(stage: str, item: Mapping, ns) -> Mapping | None:
    """브리지 단계 정의의 폴백 한 벌(`lm27.bridge.stages.REGISTRY[stage].fallback(item, ctx, why)`). 단계 모듈은 임포트만으로
    세션·전송·쓰기를 하지 않는다(B-2 · L-30). 모듈·단계가 아직 없으면 None(답 없음)."""
    if importlib.util.find_spec("lm27.bridge.stages") is None:
        return None
    reg = getattr(importlib.import_module("lm27.bridge.stages"), "REGISTRY", None)
    spec = reg.get(stage) if isinstance(reg, Mapping) else None
    fb = getattr(spec, "fallback", None)
    if fb is None:
        return None
    ans = fb(dict(item), ns, why="no_ai_out")
    return ans if isinstance(ans, Mapping) else None


def answers(ctx, stage: str, items: Iterable[Mapping]) -> dict[str, tuple]:
    """항목 키 → (ans, by). ai_out 의 항목 답 → 없으면 폴백(by = rule) → 없으면 빠짐."""
    got = ctx.ai.get(stage, {}) or {}
    fb = ctx.fallback if ctx.fallback is not None else bridge_fallback
    ns = SimpleNamespace(registry=ctx.registry, agents=ctx.catalog, catalog=ctx.catalog, cfg=ctx.cfg, stage=stage)
    out: dict[str, tuple] = {}
    missing = False
    for it in items:
        k = it["key"]
        a = got.get(k)
        if isinstance(a, Mapping) and isinstance(a.get("ans"), Mapping):
            ans = dict(a["ans"])
            if stage == "review_text" and isinstance(a.get("peers_map"), Mapping):
                ans.setdefault("peers_map", dict(a["peers_map"]))
            out[k] = (ans, str(a.get("by") or "ai"))
            continue
        ans = fb(stage, it, ns)
        if isinstance(ans, Mapping):
            ans = dict(ans)
            if stage == "review_text":
                ans.setdefault("peers_map", dict((it.get("rule") or {}).get("peers_map", {})))
            out[k] = (ans, "rule")
        else:
            missing = True
    if missing and not any(w.get("code") == "fallback_unavailable" for w in ctx.warnings):
        ctx.warnings.append(V.warn("fallback_unavailable"))
    return out


# ───────────────────────────── 만들기·쓰기 ─────────────────────────────
def build_items(ctx, stage: str | None = None) -> dict[str, list[dict]]:
    """분석 문맥 → 단계별 ai_in 항목(stage None = 4단계 모두). 앞 단계 답(ai_out)이 있으면 라벨에 반영한 뒤 만든다."""
    from lm27.report.analysis import agentic, mining, peers, subagent
    from lm27.report.analysis import review as R
    want = STAGES if stage is None else (stage,)
    unknown = [s for s in want if s not in STAGES]
    if unknown:
        raise ValueError(f"ai-items 단계 이름 오류 {unknown} — {', '.join(STAGES)} 중 하나")
    wf, traces = mining.workflows(ctx)
    out: dict[str, list[dict]] = {}
    wl = workflow_items(ctx, wf)
    if "workflow_label" in want:
        out["workflow_label"] = wl
    mining.apply_labels(wf["roles"], answers(ctx, "workflow_label", wl), ctx.registry)
    pidx = peers.peer_index(ctx.units.values(), ctx.evidence, ctx.person_dir, ctx.cfg, registry=ctx.registry)
    if "subagent_review" in want:
        sub0 = subagent.subagent_layer(ctx, wf["roles"], traces, pidx, answers=None)
        out["subagent_review"] = subagent_items(ctx, wf, sub0)
    if "agentic_match" in want:
        rows = subagent.person_step_rows(ctx, wf["roles"], traces, pidx)
        out["agentic_match"] = agentic_items(ctx, agentic.items_of(ctx, wf["roles"], traces, rows))
    if "review_text" in want:
        from lm27.report.analysis import ontology
        sets = ontology.unit_set_map(ctx, pidx)
        rv = R.review_periods(ctx, wf=wf, pidx=pidx, rels=ontology.relations(ctx, pidx, sets))
        out["review_text"] = review_items(ctx, rv, pidx)
    return {s: out[s] for s in want if s in out}


def context_from_inputs(inp, cfg, cal, *, fallback=None):
    """`lm27.report.inputs.ReportInputs`(R 부록 A — WP-31) → 분석 문맥. 시간 결과는 `inp.time` 의 논리 이름(R §2.5:
    env_slots · day_ledger · interval_ledger · tasks · attrib · team_tables · mm_month · queue · run_meta)으로 찾는다."""
    from lm27.report.analysis.activity import make_context
    t = _get(inp, "time")

    def tf(*names):
        for n in names:
            v = _get(t, n)
            if v is not None:
                return v
        return None
    labels = _get(inp, "labels")
    if isinstance(labels, Mapping) and isinstance(labels.get("labels"), Mapping):
        labels = labels["labels"]
    ev = _get(inp, "evidence")
    period = _get(inp, "period")
    if period is None and _get(inp, "from_") and _get(inp, "to"):
        period = (_get(inp, "from_"), _get(inp, "to"))
    return make_context(tasks=tf("tasks") or [], attrib=tf("attrib") or [], tables=tf("team_tables", "tables") or {},
                        cal=cal, cfg=cfg, labels=labels, registry=_get(inp, "registry"), env_slots=tf("env_slots"),
                        day_ledger=tf("day_ledger"), run_meta=tf("run_meta"), period=period,
                        person_dir=_get(inp, "person_dir"), evidence=ev, leaves=_get(inp, "leaves"),
                        absences=_get(inp, "absences"), ai=_get(inp, "ai"), fam_names=_get(ev, "fam_names"),
                        fallback=fallback, run_id=str(_get(inp, "run_id", "") or ""))


def write_ai_items(run_id: str, stage: str | None = None, *, paths=None, cfg=None, inputs=None, cal=None,
                   fallback=None) -> dict[str, int]:
    """`lm27 report ai-items --run <run_id> [--stage <stage>]`(계약 §7.1). 반환 {stage: 건수}(합 0 이면 cli rc 4).

    paths·cfg·inputs·cal·fallback 은 시험·파이프라인 주입점(없으면 `Paths()` · `load_config` · `load_inputs(run_id)` ·
    `load_calendar(paths, 레지스트리)`)."""
    from lm27.util.fsx import atomic_write, canon_bytes
    if paths is None:
        from lm27.paths import Paths
        paths = Paths()
    if cfg is None:
        from lm27.config import load_config
        cfg = load_config(paths)
    if inputs is None:
        from lm27.report.inputs import load_inputs        # 보고서 입력 단일 로더(R §2.5 · WP-31)
        inputs = load_inputs(run_id, paths=paths, cfg=cfg)   # 받은 paths·cfg 로(W2 통합 WP-32 CR — 기본 Paths() 아님)
    if cal is None:
        from lm27.time.calendar import load_calendar
        cal = load_calendar(paths, _get(inputs, "registry"))
    ctx = context_from_inputs(inputs, cfg, cal, fallback=fallback)
    items = build_items(ctx, stage)
    counts = {}
    for st, its in items.items():
        lines = [canon_bytes(dict(it)).decode("utf-8") for it in its]
        atomic_write(paths.ai_in(st), ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8"))
        counts[st] = len(lines)
    return counts
