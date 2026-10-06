# -*- coding: utf-8 -*-
r"""이름 병합 거버넌스 — 점수 · 세 구간 · 제약 클러스터링 · 병합 기록(H §9, 계약 §2.10).

- `pair_score(a, b, ctx)` → (점수, 근거). −∞ 규칙(never 쌍·괄호 꼬리 상이·숫자 토큰 상이·둘 다 다른 등록 과제·확정 영역 상이)이
  먼저, 그다음 표기 동일 10.0, 그 밖 가감(이름 2-gram Dice · 공유 근거 Jaccard · 고객사 토큰 · 영역 추정 상이 · 진부분집합 ·
  시기 비겹침 · AI 통합 제안). **AI 근거만으로는 자동 구간을 넘지 못한다**(점수를 `auto` 바로 아래로 — H §9.3 13).
- `zone(점수)` → auto(≥ `hier.merge.auto`) · ask(≥ `hier.merge.ask`) · reject.
- `cluster(names, W, order, cap)` → Pivot(KwikCluster) + 국소 탐색. 무리 안에 −∞ 쌍 0, 크기 ≤ `hier.merge.cap`(G-H10) —
  쌍 단위 판정만 하면 never 로 갈라 둔 두 이름이 제3의 이름을 거쳐 합쳐지는 것을 막는다(LM24 실측).
- `merge_titles` — 범위 S1(같은 역할 업무 안의 명명 군집 이름): 자동 구간 무리는 투입 큰 쪽 이름으로 맞추고, 질문 구간 쌍은
  확인 질문 H04 재료로 돌려준다. 사용자 이름은 바꾸지 않는다. 등록 과제끼리(S4)·팀원 사이(S5)는 클라이언트가 합치지 않는다.
- `append_merge_log` — `data\local_only\hier\merge_log.jsonl`(추가 전용 — 되돌리기는 반대 결정(never_pairs)을 남긴다).
- `team_proposal_candidates(entries)` — 범위 S5(팀 서버 `/admin` '제안 묶음 후보', H §9.6 · T-H21): 모든 팀원 묶음의
  `proposals[]` 를 모아 이름·`domain_guess` 만으로(서버에는 근거 키가 없다) 자동·질문 구간 쌍과 묶음 후보를 돌려준다.
  **아무것도 합치지 않는다**(입력도 바꾸지 않는다) — 팀장이 [새 과제로 등록]·[기존 과제의 별칭으로]·[무시]를 고른다.

표준 라이브러리만 쓴다.
"""
import math
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date

from lm27.hier.features import default_cfg
from lm27.hier.names import bigram_dice, fold, name_toks, note, num_tokens, ukey
from lm27.util import fsx

__all__ = [
    "NEG", "MergeCtx", "append_merge_log", "cluster", "merge_ctx_for", "merge_titles", "name_bigrams", "pair_score",
    "pair_weights", "team_proposal_candidates", "zone",
]

NEG = float("-inf")
MERGE_LOG = "merge_log.jsonl"


@dataclass(frozen=True)
class MergeCtx:
    """`pair_score` 문맥. 이름 → 값 사전은 원래 이름(표기 그대로)을 키로 쓴다."""
    never: frozenset = frozenset()                         # ukey 쌍(frozenset) — 팀·개인 never_pairs
    never_words: Mapping[str, tuple[str, ...]] = field(default_factory=dict)   # ukey(등록 과제 이름) → never 낱말
    registry_ids: Mapping[str, str] = field(default_factory=dict)              # ukey(등록 과제 이름·별칭) → ID
    dom: Mapping[str, str] = field(default_factory=dict)                       # 이름 → 영역(추정 또는 확정)
    dom_confirmed: frozenset = frozenset()                 # 영역이 확정인 이름(등록 과제·받아들인 개인 과제)
    shared: Mapping[str, frozenset] = field(default_factory=dict)             # 이름 → 공유 근거 키(문서군·대화·상대)
    cust: Mapping[str, frozenset] = field(default_factory=dict)               # 이름 → 고객사 토큰
    span: Mapping[str, tuple[str, str]] = field(default_factory=dict)         # 이름 → (첫, 마지막 근거 날짜)
    ai_pairs: frozenset = frozenset()                      # AI 통합 제안 ukey 쌍(§8.3)
    auto: float = 1.0
    ask: float = 0.35
    span_gap_days: int = 120


def merge_ctx_for(reg=None, cfg=None, **kw) -> MergeCtx:
    """유효 레지스트리·설정에서 기본 문맥: never_pairs·등록 과제 이름 색인·never 낱말·구간 문턱(`hier.merge.*`)."""
    cfg = default_cfg(cfg)
    base: dict = {"auto": float(cfg["hier.merge.auto"]), "ask": float(cfg["hier.merge.ask"]),
                  "span_gap_days": int(cfg["hier.merge.spanGapDays"])}
    if reg is not None:
        ids: dict[str, str] = {}
        words: dict[str, tuple[str, ...]] = {}
        for pid in sorted(reg.projects):
            p = reg.projects[pid]
            if p.origin == "reserved":
                continue
            rep = reg.resolve(pid)
            for a in (p.name, *p.aliases, *p.codenames):
                k = ukey(a)
                if k:
                    ids.setdefault(k, rep)
            if p.never:
                for a in (p.name, *p.aliases):
                    words[ukey(a)] = tuple(p.never)
        base.update({"never": frozenset(reg.never_pairs), "registry_ids": ids, "never_words": words})
    base.update(kw)
    return MergeCtx(**base)


def _days_between(a: str, b: str) -> int | None:
    try:
        return abs((date.fromisoformat(b) - date.fromisoformat(a)).days)
    except (TypeError, ValueError):
        return None


def pair_score(a: str, b: str, ctx: MergeCtx | None = None) -> tuple[float, str]:
    """두 이름의 병합 점수(H §9.3). 반환 (점수(소수 3자리) 또는 −∞, 근거 한 줄)."""
    c = ctx if ctx is not None else MergeCtx()
    ka, kb = ukey(a), ukey(b)
    if frozenset((ka, kb)) in c.never:
        return NEG, "never"
    for x, y in ((ka, kb), (kb, ka)):
        if any(ukey(w) and ukey(w) in y for w in c.never_words.get(x, ())):
            return NEG, "never"
    if note(a) != note(b):
        return NEG, f"괄호 꼬리 상이({note(a)!r}/{note(b)!r})"
    if num_tokens(a) != num_tokens(b):
        return NEG, "숫자 토큰 상이"
    if ka in c.registry_ids and kb in c.registry_ids and c.registry_ids[ka] != c.registry_ids[kb]:
        return NEG, "둘 다 레지스트리 과제(다른 ID)"
    da, db = c.dom.get(a), c.dom.get(b)
    if da and db and da != db and a in c.dom_confirmed and b in c.dom_confirmed:
        return NEG, "영역 상이(확정)"
    if ka == kb:
        return 10.0, "표기 동일"
    sc, non_ai, why = 0.0, 0.0, []
    d = bigram_dice(a, b)
    if d > 0.45:
        v = 2.4 * (d - 0.45)
        sc += v
        non_ai += v
        why.append(f"이름 {d:.2f}")
    sa, sb = c.shared.get(a, frozenset()), c.shared.get(b, frozenset())
    if sa and sb:
        j = len(sa & sb) / len(sa | sb)
        if j > 0:
            sc += 2.0 * j
            non_ai += 2.0 * j
            why.append(f"공유근거 {j:.2f}")
        elif len(sa) >= 2 and len(sb) >= 2:
            sc -= 0.8
            why.append("근거 배타 -0.8")
    ca, cb = c.cust.get(a, frozenset()), c.cust.get(b, frozenset())
    if ca and ca & cb:
        sc += 1.2
        non_ai += 1.2
        why.append("고객 일치")
    if da and db and da != db:
        sc -= 0.8
        why.append("영역 추정 상이 -0.8")
    ta, tb = name_toks(a), name_toks(b)
    if (ta < tb or tb < ta) and len(ta ^ tb) >= 2:
        sc -= 0.5
        why.append("진부분집합 -0.5")
    spa, spb = c.span.get(a), c.span.get(b)
    if spa and spb:
        gap = max(_days_between(spa[1], spb[0]) or 0, _days_between(spb[1], spa[0]) or 0) \
            if (spa[1] < spb[0] or spb[1] < spa[0]) else 0
        if gap >= c.span_gap_days:
            sc -= 0.6
            why.append("시기 비겹침 -0.6")
    if frozenset((ka, kb)) in c.ai_pairs:
        sc += 1.0
        why.append("AI 통합 제안 +1.0")
        if non_ai <= 0 and sc >= c.auto:
            sc = c.auto - 0.01
            why.append("AI 단독 근거 → 질문 구간으로 제한")
    return round(sc, 3), " · ".join(why) or "근거 없음"


def zone(score: float, cfg=None, *, auto: float | None = None, ask: float | None = None) -> str:
    """auto · ask · reject(H §9.4). cfg 를 주면 `hier.merge.auto`·`ask`, auto·ask 를 주면 그 값."""
    if auto is None or ask is None:
        c = default_cfg(cfg)
        auto = float(c["hier.merge.auto"]) if auto is None else auto
        ask = float(c["hier.merge.ask"]) if ask is None else ask
    if score == NEG or score != score:
        return "reject"
    return "auto" if score >= auto else ("ask" if score >= ask else "reject")


def _pk(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a <= b else (b, a)


def pair_weights(names: Iterable[str], ctx: MergeCtx | None = None) -> dict[tuple[str, str], float]:
    """이름 목록의 모든 쌍 점수 {(작은, 큰): 점수}."""
    ns = sorted(set(names))
    out = {}
    for i, a in enumerate(ns):
        for b in ns[i + 1:]:
            out[(a, b)] = pair_score(a, b, ctx)[0]
    return out


def _ok(grp: list[str], W: Mapping, cap: int) -> bool:
    if len(grp) > cap:
        return False
    g = sorted(grp)
    return all(W.get(_pk(g[i], g[j]), 0.0) != NEG for i in range(len(g)) for j in range(i + 1, len(g)))


def cluster(names: Iterable[str], W: Mapping, order: Iterable[str] | None = None, cap: int = 5, *,
            threshold: float = 1.0, rounds: int = 6) -> list[list[str]]:
    """제약 클러스터링(H §9.5): Pivot — 순서대로 축을 잡고 W ≥ threshold 이며 무리 안 −∞ 가 없고 크기 ≤ cap 인 이름을 붙인다.
    그 뒤 국소 탐색(최대 rounds 회): 한 이름을 다른 무리·단독으로 옮겨 목적함수(무리 안 음수 + 무리 밖 양수)가 줄면 옮긴다."""
    ns = list(dict.fromkeys(order if order is not None else sorted(set(names))))
    for n in sorted(set(names) - set(ns)):
        ns.append(n)
    part: list[list[str]] = []
    placed: set[str] = set()
    for p in ns:
        if p in placed:
            continue
        grp = [p]
        placed.add(p)
        for x in ns:
            if x in placed or W.get(_pk(p, x), 0.0) < threshold:
                continue
            if _ok(grp + [x], W, cap):
                grp.append(x)
                placed.add(x)
        part.append(grp)
    return _local_search(part, W, cap, threshold, rounds)


def _v(W: Mapping, a: str, b: str, threshold: float) -> float:
    w = W.get(_pk(a, b), 0.0)
    return NEG if w == NEG else w - threshold


def _cost_in(x: str, grp: list[str], W, threshold) -> float:
    """x 를 grp 에 둘 때 x 쪽 비용: 무리 안 음수 몫 − 무리 안 양수 몫(무리 밖 양수는 놓친 몫으로 상쇄)."""
    s = 0.0
    for y in grp:
        if y == x:
            continue
        v = _v(W, x, y, threshold)
        if v == NEG:
            return math.inf
        s += -v
    return s


def _local_search(part: list[list[str]], W: Mapping, cap: int, threshold: float, rounds: int) -> list[list[str]]:
    groups = [list(g) for g in part]
    for _ in range(max(0, rounds)):
        moved = False
        for gi in range(len(groups)):
            for x in list(groups[gi]):
                if len(groups[gi]) == 1:
                    cur = 0.0
                else:
                    cur = _cost_in(x, groups[gi], W, threshold)
                best = (cur, None)
                for gj, g in enumerate(groups):
                    if gj == gi or not g or len(g) + 1 > cap:
                        continue
                    c = _cost_in(x, g + [x], W, threshold)
                    if c < best[0] - 1e-12:
                        best = (c, gj)
                if len(groups[gi]) > 1 and 0.0 < best[0] - 1e-12:
                    best = (0.0, -1)
                if best[1] is None:
                    continue
                groups[gi].remove(x)
                if best[1] == -1:
                    groups.append([x])
                else:
                    groups[best[1]].append(x)
                moved = True
        groups = [g for g in groups if g]
        if not moved:
            break
    out = [sorted(g) for g in groups if g]
    return sorted(out, key=lambda g: g[0])


# ───────────────────────── S1 — 단위업무 이름 맞추기 ─────────────────────────
def merge_titles(items: Iterable[Mapping], ctx: MergeCtx | None = None, cfg=None) -> tuple[dict[str, str], list[dict]]:
    """같은 역할 업무 안의 군집 이름(S1). items = [{group, role, title, effort_min, locked}](locked = 사용자 이름).
    반환 (군집 키 → 바뀐 이름, 질문 구간 쌍 [{a, b, score, why, groups}]). 자동 무리는 투입 큰 쪽 이름(동률 ukey 순)."""
    cfg = default_cfg(cfg)
    c = ctx if ctx is not None else merge_ctx_for(None, cfg)
    cap = int(cfg["hier.merge.cap"])
    by_role: dict[str, list[Mapping]] = {}
    for it in items:
        if it.get("title"):
            by_role.setdefault(str(it.get("role") or ""), []).append(it)
    renames: dict[str, str] = {}
    asks: list[dict] = []
    for role in sorted(by_role):
        its = by_role[role]
        eff: dict[str, int] = {}
        groups_of: dict[str, list[str]] = {}
        locked: set[str] = set()
        for it in its:
            t = str(it["title"])
            eff[t] = eff.get(t, 0) + int(it.get("effort_min") or 0)
            groups_of.setdefault(t, []).append(str(it["group"]))
            if it.get("locked"):
                locked.add(t)
        names = sorted(eff)
        if len(names) < 2:
            continue
        W = pair_weights(names, c)
        order = sorted(names, key=lambda n: (n not in locked, -eff[n], ukey(n), n))
        for grp in cluster(names, W, order, cap, threshold=c.auto):
            if len(grp) < 2:
                continue
            keep = [n for n in grp if n in locked] or grp
            rep = min(keep, key=lambda n: (-eff[n], ukey(n), n))
            for n in grp:
                if n != rep and n not in locked:
                    for gk in groups_of[n]:
                        renames[gk] = rep
        for (a, b), s in sorted(W.items()):
            if zone(s, auto=c.auto, ask=c.ask) == "ask":
                asks.append({"a": a, "b": b, "score": s, "why": pair_score(a, b, c)[1], "role": role,
                             "groups": sorted(set(groups_of[a]) | set(groups_of[b])),
                             "effort_min": eff[a] + eff[b]})
    return renames, asks


# ───────────────────────── S5 — 팀 서버 '제안 묶음 후보'(H §9.6) ─────────────────────────
def name_bigrams(s) -> frozenset[str]:
    """`bigram_dice` 와 같은 2-gram 집합(괄호 꼬리 떼고 공백 지움) — 후보 쌍 색인용."""
    t = fold(s).replace(" ", "")
    return frozenset({t[i:i + 2] for i in range(len(t) - 1)} or {t})


def _top(c: Counter) -> str:
    return min(c.items(), key=lambda kv: (-kv[1], kv[0]))[0] if c else ""


def team_proposal_candidates(entries: Iterable[Mapping], cfg=None, *, ctx: MergeCtx | None = None) -> dict:
    """팀원 묶음 `proposals[]` 모음 → {pairs, bundles}(H §9.6 · S5). entries 항목 = {person_key, proposal_id, label,
    domain_guess, effort_min?}. 같은 ukey 는 한 이름으로 모으고(대표 표기 = 가장 많은 표기), 서로 다른 이름 쌍은 `pair_score`
    (근거 = 이름 2-gram·`domain_guess` 뿐, ctx 의 never·등록 과제 색인은 −∞ 규칙에 쓴다)로 자동·질문 구간만 남긴다. 한 사람
    안의 쌍은 그 사람의 S2 몫이라 뺀다. 묶음 후보 = 질문 구간 이상으로 이어진 이름들을 제약 클러스터링(무리 안 −∞ 0, 크기 ≤
    `hier.merge.cap`)한 무리 + 여러 사람이 같은 ukey 로 낸 이름. 반환 값만 만들고 **아무것도 합치지 않는다**."""
    cfg = default_cfg(cfg)
    c = ctx if ctx is not None else merge_ctx_for(None, cfg)
    cap = int(cfg["hier.merge.cap"])
    groups: dict[str, dict] = {}
    for e in entries:
        label = " ".join(str(e.get("label") or "").split())
        k = ukey(label)
        if len(k) < 2:
            continue
        g = groups.setdefault(k, {"labels": Counter(), "members": set(), "persons": set(), "doms": Counter(),
                                  "effort_min": 0})
        g["labels"][label] += 1
        pk = str(e.get("person_key") or "")
        g["members"].add((pk, str(e.get("proposal_id") or "")))
        g["persons"].add(pk)
        dg = str(e.get("domain_guess") or "")
        if dg:
            g["doms"][dg] += 1
        v = e.get("effort_min")
        g["effort_min"] += int(v) if isinstance(v, int | float) and not isinstance(v, bool) else 0
    keys = sorted(groups)
    rep = {k: _top(groups[k]["labels"]) for k in keys}
    dom = {rep[k]: _top(groups[k]["doms"]) for k in keys if groups[k]["doms"]}
    base = MergeCtx(never=c.never, never_words=c.never_words, registry_ids=c.registry_ids, dom=dom, auto=c.auto,
                    ask=c.ask, span_gap_days=c.span_gap_days)
    if c.ask > 0:                    # 양수 점수는 이름 Dice > 0.45 에서만 나온다 → 2-gram 색인으로 빠짐없이 후보를 고른다
        bg = {k: name_bigrams(rep[k]) for k in keys}
        index: dict[str, list[int]] = defaultdict(list)
        for i, k in enumerate(keys):
            for b in bg[k]:
                index[b].append(i)
        shared: Counter = Counter()
        for i, k in enumerate(keys):
            for b in bg[k]:
                for j in index[b]:
                    if j > i:
                        shared[(i, j)] += 1
        cand = sorted((i, j) for (i, j), n in shared.items()
                      if 2 * n / (len(bg[keys[i]]) + len(bg[keys[j]])) > 0.45)
    else:
        cand = [(i, j) for i in range(len(keys)) for j in range(i + 1, len(keys))]
    pairs: list[dict] = []
    parent = list(range(len(keys)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for i, j in cand:
        ga, gb = groups[keys[i]], groups[keys[j]]
        if len(ga["persons"] | gb["persons"]) < 2:
            continue
        s, why = pair_score(rep[keys[i]], rep[keys[j]], base)
        z = zone(s, auto=c.auto, ask=c.ask)
        if z == "reject":
            continue
        pairs.append({"a": rep[keys[i]], "b": rep[keys[j]], "score": s, "zone": z, "why": why,
                      "persons": len(ga["persons"] | gb["persons"]),
                      "effort_min": ga["effort_min"] + gb["effort_min"]})
        parent[find(i)] = find(j)
    comps: dict[int, list[str]] = defaultdict(list)
    for i, k in enumerate(keys):
        comps[find(i)].append(k)
    bundles: list[dict] = []
    for comp in comps.values():
        names = [rep[k] for k in comp]
        eff = {rep[k]: groups[k]["effort_min"] for k in comp}
        if len(comp) > 1:
            W = pair_weights(names, base)
            order = sorted(names, key=lambda n: (-eff[n], ukey(n), n))
            parts = cluster(names, W, order, cap, threshold=c.ask)
        else:
            W, parts = {}, [names]
        for grp in parts:
            ks = [ukey(n) for n in grp]
            persons = set().union(*(groups[k]["persons"] for k in ks))
            if len(persons) < 2:
                continue
            ws = [W[_pk(a, b)] for ai, a in enumerate(sorted(grp)) for b in sorted(grp)[ai + 1:]]
            bundles.append({"names": sorted(grp), "zone": "auto" if all(w >= c.auto for w in ws) else "ask",
                            "members": sorted([list(m) for k in ks for m in groups[k]["members"]]),
                            "persons": len(persons), "effort_min": sum(groups[k]["effort_min"] for k in ks)})
    pairs.sort(key=lambda x: (-x["score"], x["a"], x["b"]))
    bundles.sort(key=lambda x: (-x["persons"], -x["effort_min"], x["names"]))
    return {"pairs": pairs, "bundles": bundles}


def append_merge_log(paths, entry: Mapping) -> None:
    """병합 기록 한 줄 덧붙이기(`merge_log.jsonl` — 로컬 전용). −∞ 점수는 null 로."""
    e = dict(entry)
    s = e.get("score")
    if isinstance(s, float) and not math.isfinite(s):
        e["score"] = None
    fsx.append_line(paths.hier_local_file(MERGE_LOG), fsx.canon_bytes(e).decode("utf-8"))
