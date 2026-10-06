# -*- coding: utf-8 -*-
r"""업무 계층·분류(H §4.0 · §12, 계약 §2.10 · §3.15) — `classify_all(run_ctx) -> HierResult`.

흐름(H §4.0 — 시간 코어와 맞물리는 순서):

1. `prepare(...)` — 유효 레지스트리 → 분류 특징 → **증거 꼬리표 `HierTags`**(시간 코어 `normalize(…, tags)` 입력, 시간 코어가
   단위업무를 만들기 전에 부른다). 키는 시간 코어 `msg_key`·`fam_key` 와 같다(W1a CR).
2. 시간 코어가 단위업무·귀속·정수 분 표를 만든다(이 패키지 밖).
3. `classify_all(run_ctx)` — 단위업무별 증거 모음 → 규칙 라벨(과제·영역·분야·기능·유형) → 명명 군집·규칙 이름 → (코파일럿
   ai_in 쓰기) → 라벨 적용(규칙 + AI 답 + 사용자 수정 + 제목 캐시) → 이름 병합(S1) → 학습 규칙·정밀도 → 제안 큐 → 확인 질문
   H01~H06 → 불변식(H-I1·H-I2·H-I4·H-I5) → 결과 `hier/1`(`write_result`).

분류는 **시간 값을 바꾸지 않는다**(H-I5 · T-06): 단위업무·귀속·정수 분 표를 읽기만 하고, 분류 전후 다이제스트가 다르면
`HierInvariantError`(분석 중단). 코파일럿 답은 이름·분류만 바꾸고 증거 꼬리표·학습 규칙·레지스트리로 되먹이지 않는다(H-I6).
매 실행 전체를 다시 계산한다(증분 상태는 제목 캐시·제안 큐·학습 규칙·병합 기록 — `data\local_only\hier\` 만).

나눠 가진 패키지 규칙(계획 §3.1 · CR-09): 이 `__init__` 은 하위 모듈을 최상위에서 import 하지 않는다 — 공개 함수 안에서
지연 import 하고, `HierTags` 같은 이름은 모듈 `__getattr__` 로 늦게 꺼낸다. 표준 라이브러리만 쓴다.
"""
import hashlib
import os
from collections import Counter, defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field

__all__ = ["HIER_VERSION", "HierInvariantError", "HierResult", "HierTags", "check_invariants", "classify_all",
           "prepare", "write_result"]

HIER_VERSION = "hier/1"
RESULT_FILES = ("labels.json", "groups.json", "evidence_tags.jsonl", "queue.json", "proposals_snapshot.json",
                "hier_meta.json")
_OTHER_KEYS = ("episode.docs.genericStems", "episode.tokens.boilerplate", "time.tzOffsetMin", "team.unitTitleMode")


def __getattr__(name):
    if name == "HierTags":
        from lm27.hier.rules import HierTags
        return HierTags
    raise AttributeError(f"module 'lm27.hier' has no attribute {name!r}")


class HierInvariantError(RuntimeError):
    """계층 불변식 위반(H-I1·H-I4·H-I5 — 코드 결함, 분석 중단)."""


@dataclass
class HierResult:
    labels: dict = field(default_factory=dict)            # unit_id → UnitLabel
    groups: list = field(default_factory=list)            # Group
    tags: object = None                                   # HierTags
    tag_rows: list = field(default_factory=list)          # evidence_tags.jsonl 행
    queue: list = field(default_factory=list)             # H01~H06
    proposals: dict = field(default_factory=dict)         # proposals_snapshot.json
    meta: dict = field(default_factory=dict)              # hier_meta.json
    ai_items: list = field(default_factory=list)          # 이번에 만든 task_label ai_in 항목
    conflicts: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    unapplied: list = field(default_factory=list)         # 미적용 수정 기록 id
    rule_labels: dict = field(default_factory=dict)       # unit_id → RuleLabel(규칙만)
    copilot: dict = field(default_factory=dict)           # {allowed, notice, used}
    titles: dict = field(default_factory=dict)            # 군집 키 → (규칙 이름, 출처)
    units: dict = field(default_factory=dict)             # unit_id → UnitIn(증거 모음 — 부트스트랩 표본·화면 재료, 저장 안 함)

    def rollup_labels(self) -> dict:
        """시간 코어 `rollup(month, labels)` 입력(H §12.3): {unit_id: {domain, project, role, wtype, ax_link}}.
        과제 자리는 팀 묶음과 같은 값(P-… 또는 제안 ID, 개인 과제는 그 제안 ID)."""
        out = {}
        for uid in sorted(self.labels):
            lb = self.labels[uid]
            p = lb.project
            slot = p if p and str(p).startswith("P-") else (lb.proposal_id or None)
            out[uid] = {"domain": lb.domain, "project": slot, "role": lb.role_id, "wtype": lb.wtype,
                        "ax_link": bool(lb.ax_link)}
        return out

    def groups_obj(self) -> dict:
        """groups.json — {군집 키: {anchor, members, title, title_src, project, effort_min}}."""
        out = {}
        for g in self.groups:
            rep = self.labels.get(g.rep)
            out[g.key] = {"anchor": g.anchor, "members": list(g.members),
                          "title": rep.title if rep is not None else "",
                          "title_src": rep.title_src if rep is not None else "",
                          "project": (rep.project or rep.proposal_id) if rep is not None else None,
                          "effort_min": int(g.effort_min)}
        return dict(sorted(out.items()))


def _get(ctx, name, default=None):
    if ctx is None:
        return default
    if isinstance(ctx, Mapping):
        return ctx.get(name, default)
    return getattr(ctx, name, default)


def prepare(records, reg, cfg=None, *, person_dir=None, catalog=None, kr=None, folder_key=None):
    """1단계(시간 코어 전): (특징 목록, HierTags, 꼬리표 행). 결정적 규칙에서만 나온다(H-I6)."""
    from lm27.hier.features import default_cfg, features_of
    from lm27.hier.rules import RuleCtx, tag_rows, tags_from_rows
    cfg = default_cfg(cfg)
    fk = folder_key if folder_key is not None else _folder_keyer(kr)
    feats = features_of(records or (), reg, person_dir, catalog, cfg)
    c = RuleCtx(reg, cfg, folder_key=fk)
    rows = tag_rows(feats, reg, cfg, ctx=c)
    return feats, tags_from_rows(rows, feats, reg), rows


def _folder_keyer(kr):
    if kr is None:
        return None
    from lm27.hier.registry import keyers_from
    return keyers_from(kr)[0]


def _digest(tasks, team_tables, attrib) -> str:
    """H-I5 다이제스트 — 단위업무 수·unit_id·경계·문서군·투입 재료·정수 분 표·귀속 행."""
    from lm27.hier.features import get
    from lm27.hier.unitlabel import attrib_rows, tables_json, task_id
    from lm27.util import fsx
    rows = []
    for t in sorted(tasks or (), key=task_id):
        cyc = []
        for c in get(t, "cycles", None) or ():
            cyc.append([get(c, "s", None), get(c, "sb", None), get(c, "e", None), get(c, "eb", None)])
        docs = get(t, "docs", None) or {}
        es = get(t, "effort_s", None)
        rows.append([task_id(t), str(get(t, "kind", "")), cyc, sorted(str(k) for k in docs),
                     es if isinstance(es, int) else None, str(get(t, "first_key", "") or "")])
    body = {"tasks": rows, "tables": _plain(tables_json(team_tables)), "attrib": _plain(attrib_rows(attrib))}
    return hashlib.sha256(fsx.canon_bytes(body)).hexdigest()


def _plain(x):
    if isinstance(x, Mapping):
        return {str(k): _plain(v) for k, v in x.items()}
    if isinstance(x, list | tuple):
        return [_plain(v) for v in x]
    if isinstance(x, set | frozenset):
        return sorted(_plain(v) for v in x)
    if isinstance(x, float) and x != x:
        return None
    return x


def check_invariants(labels: Mapping, unit_ids, reg, proposals=None) -> list[tuple[str, str, str]]:
    """계층 불변식 H-I1(라벨 정확히 하나 · 빈 값 없음) · H-I2(영역 = 과제에서 유도) · H-I4(role_id 재계산 일치).
    반환 [(불변식, unit_id, 사유)]."""
    from lm27.hier.apply import role_slot
    from lm27.hier.unitlabel import role_id
    from lm27.hier.vocab import ALL_DOMAINS
    errs = []
    ids = set(unit_ids)
    for uid in sorted(ids - set(labels)):
        errs.append(("H-I1", uid, "라벨 없음"))
    for uid in sorted(set(labels) - ids):
        errs.append(("H-I1", uid, "단위업무 없는 라벨"))
    fields = set(reg.vocab.get("fields", {}))
    funcs = set(reg.vocab.get("functions", {}))
    wtypes = set(reg.vocab.get("activity_types", {}))
    for uid in sorted(labels):
        lb = labels[uid]
        if not lb.field or lb.field not in fields or not lb.func or lb.func not in funcs or not lb.wtype \
                or lb.wtype not in wtypes:
            errs.append(("H-I1", uid, "분야·기능·유형 코드"))
        if lb.domain not in ALL_DOMAINS:
            errs.append(("H-I1", uid, "영역 코드"))
        if lb.project and lb.proposal_id and str(lb.project).startswith("P-"):
            errs.append(("H-I1", uid, "과제 자리 둘"))
        if lb.proposal_id and not lb.project:
            want = proposals.dom_of(lb.proposal_id) if proposals is not None else lb.domain
        elif lb.project:
            want = reg.domain_of(lb.project)
        else:
            want = "UNC"
        if lb.domain != want:
            errs.append(("H-I2", uid, f"영역 {lb.domain} ≠ 유도 {want}"))
        slot = role_slot(lb.project, lb.proposal_id if not lb.project or not str(lb.project).startswith("P-")
                         else None, reg)
        if lb.role_id != role_id(slot, lb.field, lb.func):
            errs.append(("H-I4", uid, "role_id 재계산 불일치"))
    return errs


def classify_all(run_ctx) -> "HierResult":
    """분류 한 번(H §4.0). run_ctx(사전 또는 속성 객체) 키 — 모두 선택:

    paths · cfg · reg(EffectiveRegistry — 없으면 `load_effective(paths, cfg, now, kr=kr, persist=persist)`) · reg_status ·
    kr(키링 — 폴더 규칙) · records(load_evidence 행) · feats(prepare 결과 — 있으면 records 대신) · tasks(tasks.json 행 또는
    UnitTask) · attrib(attrib.jsonl 행) · team_tables · slot_basis({슬롯: 봉투 근거}) · person_dir · catalog ·
    ai_out({군집 키: 답} — 없으면 paths 의 ai_out\\task_label.json) · ai_pairs(부트스트랩 2회차 AI 통합 쌍 —
    `bootstrap.consolidate_pairs` 결과, 라벨 적용 전에 제안 큐 S2 점수로) · read_ai(기본 True) · write_ai_in(기본 False) ·
    copilot_enabled(기본 True) · persist(로컬 상태 파일 저장, 기본 False) · now(시각대 있는 datetime) · as_of(date) ·
    person_key · label_check(s → bool, 팀 라벨 검사) · rules_ver · out_dir(있으면 결과 파일을 쓴다).
    """
    from datetime import UTC, datetime

    from lm27.hier import apply as A
    from lm27.hier import copilot_io as CI
    from lm27.hier import groups as G
    from lm27.hier import learn as LR
    from lm27.hier import merge as MG
    from lm27.hier import queue as Q
    from lm27.hier.bootstrap import copilot_allowed
    from lm27.hier.features import default_cfg, features_of
    from lm27.hier.proposals import ProposalQueue
    from lm27.hier.rules import RuleCtx, tag_rows, tags_from_rows
    from lm27.hier.unitlabel import decide_wtype, field_func, unit_inputs, unit_rule_label
    from lm27.util import fsx

    cfg = default_cfg(_get(run_ctx, "cfg"))
    paths = _get(run_ctx, "paths")
    persist = bool(_get(run_ctx, "persist", False))
    now = _get(run_ctx, "now") or datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    at = now.isoformat(timespec="seconds")
    today = now.date()
    as_of = _get(run_ctx, "as_of") or today
    warnings: list[str] = []
    kr = _get(run_ctx, "kr")
    reg = _get(run_ctx, "reg")
    status = _get(run_ctx, "reg_status")
    if reg is None:
        from lm27.hier.registry import builtin_registry, load_effective
        if paths is not None:
            reg, status = load_effective(paths, cfg, now, kr=kr, persist=persist)
        else:
            reg = builtin_registry(cfg)
    if status is not None:
        warnings.extend(str(w) for w in getattr(status, "warnings", ()) or ())
    person_dir = _get(run_ctx, "person_dir")
    if person_dir is None and paths is not None:
        person_dir = fsx.read_json(paths.local_only_file("person_dir.json"), default=None)
    fk = _folder_keyer(kr)
    ctx = RuleCtx(reg, cfg, folder_key=fk)
    feats = _get(run_ctx, "feats")
    if feats is None:
        feats = features_of(_get(run_ctx, "records") or (), reg, person_dir, _get(run_ctx, "catalog"), cfg)
    feats = list(feats)
    rows = tag_rows(feats, reg, cfg, ctx=ctx)
    tags = tags_from_rows(rows, feats, reg)
    tasks = list(_get(run_ctx, "tasks") or ())
    attrib = _get(run_ctx, "attrib")
    tables = _get(run_ctx, "team_tables")
    dig0 = _digest(tasks, tables, attrib)
    units = unit_inputs(tasks, feats, attrib, _get(run_ctx, "catalog"), cfg=cfg, team_tables=tables,
                        slot_basis=_get(run_ctx, "slot_basis"))
    rule_l = {uid: unit_rule_label(u, reg, cfg, ctx=ctx) for uid, u in units.items()}
    ffs = {uid: field_func(u, reg, rule_l[uid], cfg, ctx=ctx) for uid, u in units.items()}
    wts = {uid: decide_wtype(u, ffs[uid], rule_l[uid], reg, cfg, ctx=ctx) for uid, u in units.items()}
    groups = G.name_groups(units.values(), rule_l, cfg)
    gctx = {"reg": reg, "cfg": cfg}
    titles = {g.key: G.rule_title(G.title_material(g, units, ffs.get(g.rep)), gctx) for g in groups}
    cache = G.TitleCache.for_paths(paths) if paths is not None else G.TitleCache()
    keep_days = int(cfg["hier.name.cacheKeepDays"])          # 저장 여부와 무관하게 읽는다(cfg_used 가 플래그로 바뀌지 않게)
    for g in groups:
        cache.touch(g.key, today.isoformat(), g.anchor)
    corrections = LR.load_corrections(paths) if paths is not None else list(_get(run_ctx, "corrections") or ())
    group_of = {m: g.key for g in groups for m in g.members}
    user_set, unapplied = LR.apply_corrections(units, corrections, group_of=group_of)
    pk = _get(run_ctx, "person_key")
    if pk is None and paths is not None:
        b = fsx.read_json(paths.bundle_json(), default=None)
        pk = b.get("person_key") if isinstance(b, Mapping) else None
    props = ProposalQueue.for_paths(paths) if paths is not None else ProposalQueue()
    warnings.extend(props.warnings)
    synced = props.sync_registry(reg, pk, at=at)
    cons_merged, _cons_asks = props.consolidate(_get(run_ctx, "ai_pairs") or (), reg, cfg, at=at)
    allowed, notice = copilot_allowed(reg, cfg)
    enabled = bool(_get(run_ctx, "copilot_enabled", True))
    ai = _get(run_ctx, "ai_out")
    if ai is None and paths is not None and bool(_get(run_ctx, "read_ai", True)):
        ai = CI.read_ai_out(paths.ai_out(CI.STAGE))
    ai = ai or {}
    pub = sorted({str(v) for v in (reg.public_suffix or {}).values()})
    items: list = []
    item_stats: dict = {}
    if _get(run_ctx, "write_ai_in", False) or _get(run_ctx, "build_ai_in", False):
        if allowed and enabled:
            items, item_stats = CI.build_task_label_items(
                groups, rule_l, ffs, wts, ai, reg, cfg, units=units, titles=titles, cache=cache,
                user_units=user_set.keys(), rules_ver=str(_get(run_ctx, "rules_ver") or ""), pub_classes=pub)
        if _get(run_ctx, "write_ai_in", False) and paths is not None:
            CI.write_ai_in(paths, CI.STAGE, items)
    if not (allowed and enabled):
        ai = {}
    labels, conflicts, astats = A.apply_labels(
        rule_l, ffs, wts, ai, user_set, cache, props, reg, cfg, groups=groups, units=units, titles=titles, at=at,
        label_check=_get(run_ctx, "label_check"), pub_classes=pub)
    # AI 답이 없는 미분류 군집 — 자주 나온 이름으로 규칙 제안 과제(계약 v1.3 §0.8 V15, LM24 규칙 대체)
    from lm27.hier.bootstrap import rule_auto_projects
    auto = rule_auto_projects(labels, groups, units, feats, reg, cfg, props, ai=ai, at=at,
                              label_check=_get(run_ctx, "label_check"))
    if auto.get("todo"):
        warnings.append(f"rule_auto_projects:{auto.get('assigned', 0)}/{auto['todo']}")
    # 이름 병합 S1(같은 역할 업무 안 — 자동 구간은 투입 큰 쪽 이름으로, 질문 구간은 H04)
    mctx = MG.merge_ctx_for(reg, cfg)
    mitems = []
    for g in groups:
        rep = labels.get(g.rep)
        if rep is not None and rep.title:
            mitems.append({"group": g.key, "role": rep.role_id, "title": rep.title, "effort_min": g.effort_min,
                           "locked": rep.title_src == "user"})
    renames, title_asks = MG.merge_titles(mitems, mctx, cfg)
    for g in groups:
        if g.key in renames:
            for m in g.members:
                lb = labels.get(m)
                if lb is not None and lb.title_src != "user":
                    lb.title = renames[g.key]
    # 학습 규칙(다음 실행부터 — 사람 수정에서만) · 정밀도 추적
    feats_by_unit = {uid: [f for f, _w, _r in u.ev] for uid, u in units.items()}
    gtoks = {g.key: set().union(*(f.toks for m in g.members for f in feats_by_unit.get(m, ()))) for g in groups}
    df, ng = LR.token_df(gtoks)
    learned_obj = LR.load_learned(paths) if paths is not None else {"rules": [], "learned_from": []}
    lrules, lfrom = LR.learn_rules(corrections, feats_by_unit, df, ng, learned_obj, units=units, group_of=group_of,
                                   cfg=cfg, reg=reg, today=today.isoformat())
    hits = _learned_hits(units, ctx)
    lrules = LR.track_precision(lrules, labels, hits, cfg=cfg, today=today.isoformat())
    # 제안 큐 근거 재계산 · 확인 질문
    efforts = {uid: int(u.effort_min) for uid, u in units.items()}
    days = _unit_days(units)
    props.refresh(labels, groups, efforts=efforts, days=days)
    queue = Q.hier_queue(labels, groups, props.items, conflicts, title_asks + list(props.asks), cfg, as_of=as_of)
    # 불변식
    errs = check_invariants(labels, units.keys(), reg, props)
    fatal = [e for e in errs if e[0] in ("H-I1", "H-I4")]
    if fatal:
        raise HierInvariantError("계층 불변식 위반: " + "; ".join(f"{a} {b} {c}" for a, b, c in fatal[:10]))
    warnings.extend(f"{a}:{b}" for a, b, _c in errs if a == "H-I2")
    if _digest(tasks, tables, attrib) != dig0:
        raise HierInvariantError("H-I5: 분류 전후 단위업무·귀속·정수 분 표가 달라졌습니다")
    if not allowed and notice:
        warnings.append("copilot_blocked:codename_review")
    if unapplied:
        warnings.append(f"unapplied_corrections:{len(unapplied)}")
    if ctx.unknown_token_feats:
        warnings.append(f"hier.unknown_token_id:{len(ctx.unknown_token_feats)}")
    meta = _meta(reg, status, labels, units, groups, items, astats, ai, warnings, cfg, item_stats)
    res = HierResult(labels=labels, groups=groups, tags=tags, tag_rows=rows, queue=queue, proposals=props.snapshot(),
                     meta=meta, ai_items=items, conflicts=conflicts, warnings=list(dict.fromkeys(warnings)),
                     unapplied=unapplied, rule_labels=rule_l,
                     copilot={"allowed": allowed, "notice": notice, "used": bool(ai), "synced": synced},
                     titles=titles, units=units)
    if persist and paths is not None:
        cache.prune(today, keep_days)
        cache.save()
        props.save()
        LR.save_learned(paths, lrules, lfrom)
        for gk, title in sorted(renames.items()):
            MG.append_merge_log(paths, {"at": at, "scope": "S1", "a": gk, "b": title, "score": None, "zone": "auto",
                                        "why": "same_role_title", "applied": True, "by": "auto"})
        for a, b in cons_merged:
            MG.append_merge_log(paths, {"at": at, "scope": "S2", "a": a, "b": b, "score": None, "zone": "auto",
                                        "why": "consolidate", "applied": True, "by": "auto"})
    out_dir = _get(run_ctx, "out_dir")
    if out_dir:
        write_result(res, out_dir)
    return res


def _learned_hits(units, ctx) -> dict[str, set[str]]:
    """활성 학습 규칙(과제 결과)이 맞은 단위업무 — 정밀도 추적 재료."""
    out: dict[str, set[str]] = defaultdict(set)
    for uid in sorted(units):
        for f, _w, _r in units[uid].ev:
            for r, _wt in ctx.rule_hits(f, "project"):
                if r.origin == "learned":
                    out[r.id].add(uid)
    return dict(out)


def _unit_days(units) -> dict[str, tuple[str, str]]:
    from lm27.time.calendar import d_of
    out = {}
    for uid, u in units.items():
        a = u.start or 0
        b = u.end or a
        if a:
            out[uid] = (d_of(a).isoformat(), d_of(b).isoformat())
    return out


def _meta(reg, status, labels, units, groups, items, astats, ai, warnings, cfg, item_stats) -> dict:
    by_level = Counter(lb.level for lb in labels.values())
    tot = sum(int(u.effort_min) for u in units.values()) or 0
    unc = sum(int(units[uid].effort_min) for uid, lb in labels.items() if lb.level == "unclassified" and uid in units)
    conf_hi = sum(int(units[uid].effort_min) for uid, lb in labels.items()
                  if lb.level in ("confirmed", "high") and uid in units)
    ng = len(groups)
    asked = len(items) if items else len(ai)
    used = {k: v for k, v in cfg.used().items()
            if k.split(".", 1)[0] == "hier" or k in _OTHER_KEYS}   # 접두 비교는 L-12 죽은 키 검사를 가리므로 이름공간 비교
    return {"hier_version": HIER_VERSION, "registry_version": int(getattr(reg, "version", 0) or 0),
            "registry_source": str(getattr(status, "source", None) or getattr(reg, "source", "builtin")),
            "hier_hash": str(getattr(reg, "hier_hash", "") or ""),
            "counts": {"units": len(labels), "groups": ng, "ai_items": int(astats.get("ai_items", 0)),
                       "ai_invalid": int(astats.get("ai_invalid", 0)), "ai_in": len(items),
                       "by_level": {k: by_level.get(k, 0) for k in ("confirmed", "high", "medium", "low",
                                                                     "unclassified")},
                       "ask_reasons": dict(item_stats or {})},
            "ai_share": (asked / ng) if ng else 0.0,
            "unclassified_share": (unc / tot) if tot else 0.0,
            "confident_share": (conf_hi / tot) if tot else 0.0,
            "warnings": list(dict.fromkeys(warnings)), "cfg_used": used}


def write_result(res: "HierResult", out_dir=None, *, paths=None, run_id: str | None = None) -> list[str]:
    """`hier/1` 결과 파일 6개를 원자 쓰기(계약 §3.15). 폴더 = out_dir(호출자가 `lm27.paths` 로 만든
    분석 폴더의 hier 하위 폴더), 없으면 `paths.analysis_hier(run_id)`(계약 §3.15 — W1 통합 창에서 lm27.paths 에 생김).
    반환: 쓴 파일 이름."""
    from lm27.util import fsx
    if out_dir is None:
        if paths is None or not run_id:
            raise ValueError("write_result: out_dir 또는 paths·run_id(Paths.analysis_hier)가 필요합니다")
        out_dir = paths.analysis_hier(run_id)
    d = os.fspath(out_dir)
    fsx.ensure_dir(d)
    labels = {uid: res.labels[uid].to_obj() for uid in sorted(res.labels)}
    tag_lines = "".join(fsx.canon_bytes(r).decode("utf-8") + "\n" for r in sorted(res.tag_rows, key=lambda x: x["id"]))
    files = {
        "labels.json": fsx.canon_bytes(labels),
        "groups.json": fsx.canon_bytes(res.groups_obj()),
        "evidence_tags.jsonl": tag_lines.encode("utf-8"),
        "queue.json": fsx.canon_bytes(list(res.queue)),
        "proposals_snapshot.json": fsx.canon_bytes(res.proposals),
        "hier_meta.json": fsx.canon_bytes(res.meta),
    }
    for name in RESULT_FILES:
        fsx.atomic_write(os.path.join(d, name), files[name])
    return list(RESULT_FILES)
