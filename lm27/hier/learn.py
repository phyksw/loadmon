# -*- coding: utf-8 -*-
r"""사용자 수정과 규칙 학습 — `corrections.jsonl` → 라벨 덮기 · 학습 규칙 · 정밀도 추적(H §11.3~§11.5, 계약 §3.15).

- **입력은 사용자 수정 기록뿐이다**(H-I6 · G-H7 · L-25): 이 모듈은 코파일럿 답·제안 큐를 읽지 않는다. 학습 규칙은 사람의
  수정에서만 나온다.
- `apply_corrections(units, corrections)` → (unit_id → 사용자 지정 필드, 미적용 기록 id). 대상은 **증거 키**로 찾는다
  (① 시작 근거 키 == anchor ② 경계 메시지 키 ∩ unit_keys ③ 문서군 키 겹침 ≥ 0.5 이고 대화 키 공유, 또는 군집 키 일치) —
  자체 업무가 나중에 의뢰 메일을 얻어 unit_id 가 바뀌어도 수정이 따라간다. 같은 필드는 `at` 이 늦은 기록이 이긴다.
- `learn_rules(...)` — `scope=similar` 이고 과제를 고친 기록에서: 대화·문서군·폴더·저장소 **키 규칙**(`LK-…`, 가중
  `hier.rule.w.keyRule`, 바로 active) · 드문 **토큰 규칙**(`LT-<sha1(토큰)[:8]>`, 문서 빈도 ≤ `hier.learn.tokenDfMax`,
  한 수정당 `tokenMax` 개, 같은 과제로 `tokenSupport` 번 수정되면 active) · 분야·기능·유형을 고친 업무의 주 앱(L3 비중
  ≥ 0.5) **앱 규칙**(`LK-app-…`, `appSupport` 에서 active). 같은 조건 키가 다른 과제를 가리키면 늦은 것이 이기고 앞의 것은
  `superseded`. 이미 배운 기록은 `learned_from` 에 남겨 다시 배우지 않는다(분석 기간이 바뀌어도 규칙이 사라지지 않게).
- `track_precision(rules, labels, hits)` — 활성 학습 규칙마다 적중 군집 수와 사용자·토큰 라벨과의 일치/불일치를 센다.
  적중 ≥ `hier.learn.retireMinHits` 이고 정밀도 < `retireMinPrec` 이면 `retired`(사유·날짜). 사용자 [다시 켜기] 전에는 돌아오지 않는다.
- 토큰 후보 제외: 상용구 ∪ 기능·업무 유형 어휘 키워드 ∪ 영역 키워드 ∪ 범용 문서 줄기. 분야 어휘 키워드(브라켓·광정렬·공차…)는
  과제 구별력이 커서 제외하지 않는다(H §15 골든 HG36 과 같고, WP-21 `generic_keyword` 판정과 같은 해석 — CR).

표준 라이브러리만 쓴다. 쓰기는 `fsx.atomic_write`(직전 판 `.bak`).
"""
import hashlib
from collections import Counter
from collections.abc import Iterable, Mapping

from lm27.hier import match as _match
from lm27.hier import vocab as _vocab
from lm27.hier.features import default_cfg, get
from lm27.hier.names import ukey
from lm27.time.tokens import is_generic_key
from lm27.util import fsx

__all__ = [
    "LEARNED_SCHEMA", "SET_FIELDS", "apply_corrections", "excluded_tokens", "learn_from", "learn_rules",
    "load_corrections", "load_learned", "match_units", "retire_check", "save_learned", "track_precision",
]

LEARNED_SCHEMA = "lm27.rules_learned/1"
CORRECTIONS = "corrections.jsonl"
LEARNED = "rules_learned.json"
LEARNED_BAK = "rules_learned.json.bak"
SET_FIELDS = ("project", "field", "func", "wtype", "title")
NO_PROJECT = ("", "UNC", "NONE")
APP_RULE_W = 2.0                                # 앱 규칙 가중(H §11.4 표 — 설정 키 없음)
APP_SHARE = 0.5


# ───────────────────────── 수정 기록 ─────────────────────────
def load_corrections(paths=None, *, path=None) -> list[dict]:
    """`corrections.jsonl`(추가 전용)을 읽는다. 끊긴 줄·형식이 틀린 줄은 건너뛴다. (at, id) 순."""
    p = path if path is not None else paths.hier_local_file(CORRECTIONS)
    try:
        raw = fsx.read_bytes(p)
    except OSError:
        return []
    out = []
    for line in raw.decode("utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            c = fsx.loads_strict(line.encode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            continue
        if isinstance(c, Mapping) and isinstance(c.get("set"), Mapping) and isinstance(c.get("target"), Mapping):
            out.append(dict(c))
    return sorted(out, key=lambda c: (str(c.get("at") or ""), str(c.get("id") or "")))


def _keys(v) -> set[str]:
    return {str(x) for x in (v or ()) if x} if isinstance(v, list | tuple | set | frozenset) else set()


def match_units(c: Mapping, units: Mapping, group_of: Mapping[str, str] | None = None) -> list[str]:
    """수정 기록 하나의 대상 단위업무(H §11.3): 군집 키 · ① anchor · ② 경계 메시지 키 · ③ 문서군 겹침 ≥ 0.5 + 대화 공유."""
    tg = c.get("target") or {}
    grp = str(tg.get("group") or "")
    anchor = str(tg.get("anchor") or "")
    ukeys = _keys(tg.get("unit_keys"))
    fkeys = _keys(tg.get("fam_keys"))
    ckeys = _keys(tg.get("conv_keys"))
    out = []
    for uid in sorted(units):
        u = units[uid]
        if grp and group_of is not None and group_of.get(uid) == grp:
            out.append(uid)
            continue
        if anchor and str(get(u, "first_key", "") or "") == anchor:
            out.append(uid)
            continue
        bk = _keys(get(u, "bkeys", ()))
        if ukeys and (bk & ukeys or str(get(u, "first_key", "") or "") in ukeys):
            out.append(uid)
            continue
        fams = set((get(u, "fams", {}) or {}).keys())
        convs = _keys(get(u, "convs", ()))
        if fkeys and ckeys and len(fams & fkeys) / len(fkeys) >= 0.5 and convs & ckeys:
            out.append(uid)
    return out


def apply_corrections(units: Mapping, corrections: Iterable[Mapping], *,
                      group_of: Mapping[str, str] | None = None) -> tuple[dict[str, dict], list[str]]:
    """사용자 수정 → {unit_id: {필드: 값, '_ids': [기록 id]}}, 미적용 기록 id 목록. 같은 필드는 늦은 기록이 이긴다.
    project 값 ''·'UNC'·'NONE' 은 '과제 없음(사용자 확정)' — None 으로 싣는다."""
    out: dict[str, dict] = {}
    unapplied = []
    for c in sorted(corrections, key=lambda x: (str(x.get("at") or ""), str(x.get("id") or ""))):
        st = c.get("set") or {}
        targets = match_units(c, units, group_of)
        if not targets:
            unapplied.append(str(c.get("id") or ""))
            continue
        for uid in targets:
            d = out.setdefault(uid, {"_ids": []})
            for k in SET_FIELDS:
                if k in st:
                    v = st[k]
                    if k == "project" and (v is None or (isinstance(v, str) and v in NO_PROJECT)):
                        v = None
                    elif not isinstance(v, str):
                        continue                              # 형식이 틀린 값(손상된 줄) — 그 필드만 무시
                    d[k] = v
            d["_ids"].append(str(c.get("id") or ""))
    return out, unapplied


# ───────────────────────── 규칙 학습(H §11.4) ─────────────────────────
def excluded_tokens(reg=None, cfg=None) -> frozenset[str]:
    """토큰 규칙·코드네임 후보에서 뺄 낱말: 상용구 ∪ 기능·업무 유형 어휘 키워드 ∪ 영역 키워드 ∪ 범용 문서 줄기(소문자)."""
    cfg = default_cfg(cfg)
    out = set(_match.boilerplate(cfg))
    kinds = ("functions", "activity_types")
    if reg is not None:
        for k in kinds:
            for it in reg.vocab.get(k, {}).values():
                out.update(str(x).lower() for x in it.keywords)
        for d in _vocab.DOMAINS:
            out.update(str(x).lower() for x in reg.domain_kw.get(d, ()))
    else:
        for k in kinds:
            for it in _vocab.BUILTIN_VOCAB[k]:
                out.update(str(x).lower() for x in it.keywords)
        for d in _vocab.DOMAINS:
            out.update(str(x).lower() for x in _vocab.domain_keywords(d))
    out.update(str(x).lower() for x in cfg["episode.docs.genericStems"])
    return frozenset(out)


def _rule(rid: str, kind: str, cond: tuple[str, str], then: tuple[str, str], w: float, status: str, support: int,
          src: str, today: str) -> dict:
    return {"id": rid, "kind": kind, "if": {cond[0]: cond[1]}, "then": {then[0]: then[1]}, "w": w, "status": status,
            "support": support, "from": [src] if src else [], "hits": 0, "agree": 0, "disagree": 0,
            "created_at": today, "updated_at": today, "reason": ""}


def _rid(prefix: str, k: str, existing: Iterable[Mapping], cond_key: str) -> str:
    """규칙 ID = 접두 + 키 앞 8자. 같은 ID 가 다른 조건 키로 이미 쓰였으면 키 전체(충돌 방지)."""
    rid = prefix + k[:8]
    for r in existing:
        if r.get("id") == rid and (r.get("if") or {}).get(cond_key) != k:
            return prefix + k
    return rid


def _find(existing: Iterable[Mapping], cond: tuple[str, str], then_key: str) -> Mapping | None:
    for r in existing:
        c = r.get("if") or {}
        t = r.get("then") or {}
        if c.get(cond[0]) == cond[1] and then_key in t and r.get("status") in ("active", "candidate", "off"):
            return r
    return None


def learn_from(c: Mapping, feats_of_target: Iterable, df: Mapping[str, int], n_groups: int,
               existing: Iterable[Mapping] = (), *, cfg=None, reg=None, app_of_target: str = "",
               today: str = "", excluded: frozenset[str] | None = None) -> list[dict]:
    """수정 기록 하나 → 새·갱신 학습 규칙(H §11.4 `learn_from`). existing = 지금까지의 규칙(토큰 지지 수 계산용)."""
    cfg = default_cfg(cfg)
    df_max = float(cfg["hier.learn.tokenDfMax"])
    tok_max = int(cfg["hier.learn.tokenMax"])
    tok_sup = int(cfg["hier.learn.tokenSupport"])
    app_sup = int(cfg["hier.learn.appSupport"])
    w_key = float(cfg["hier.rule.w.keyRule"])
    w_tok = float(cfg["hier.rule.w.learnedToken"])
    st = c.get("set") or {}
    tg = c.get("target") or {}
    cid = str(c.get("id") or "")
    ex = list(existing)
    out: list[dict] = []
    P = st.get("project")
    if c.get("scope") == "similar" and P and str(P) not in NO_PROJECT:
        P = str(P)
        for k in sorted(_keys(tg.get("conv_keys"))):
            out.append(_rule(_rid("LK-conv-", k, ex + out, "conv"), "key", ("conv", k), ("project", P), w_key, "active",
                             1, cid, today))
        for k in sorted(_keys(tg.get("fam_keys"))):
            if is_generic_key(k):
                continue
            kind = "repo" if k.startswith("r") else "fam"
            out.append(_rule(_rid(f"LK-{kind}-", k, ex + out, kind), "key", (kind, k), ("project", P), w_key,
                             "active", 1, cid, today))
        dks = [str(x) for x in (tg.get("dir_keys") or ()) if x]
        if dks:
            out.append(_rule(_rid("LK-dir-", dks[0], ex + out, "dir"), "key", ("dir", dks[0]), ("project", P), w_key,
                             "active", 1, cid, today))
        exc = excluded if excluded is not None else excluded_tokens(reg, cfg)
        cnt: Counter = Counter()
        for f in feats_of_target:
            cnt.update(get(f, "toks", ()) or ())
        ng = max(int(n_groups), 1)
        cand = [t for t, n in cnt.items() if n >= 2 and len(t) >= 2 and df.get(t, 0) / ng <= df_max and t not in exc]
        for t in sorted(cand, key=lambda t: (df.get(t, 0), -cnt[t], t))[:tok_max]:
            prev = _find(ex + out, ("token", t), "project")
            same = prev is not None and (prev.get("then") or {}).get("project") == P
            sup = int(prev.get("support", 0)) + 1 if same else 1
            rid = "LT-" + hashlib.sha1(t.encode("utf-8")).hexdigest()[:8]
            out.append(_rule(rid, "token", ("token", t), ("project", P), w_tok, "active" if sup >= tok_sup else "candidate",
                             sup, cid, today))
    if app_of_target:
        for axis in ("field", "func", "wtype"):
            v = st.get(axis)
            if not v:
                continue
            prev = _find(ex + out, ("app", app_of_target), axis)
            same = prev is not None and (prev.get("then") or {}).get(axis) == v
            sup = int(prev.get("support", 0)) + 1 if same else 1
            rid = f"LK-app-{axis}-" + hashlib.sha1(app_of_target.encode("utf-8")).hexdigest()[:8]
            out.append(_rule(rid, "app", ("app", app_of_target), (axis, str(v)), APP_RULE_W,
                             "active" if sup >= app_sup else "candidate", sup, cid, today))
    return out


def _main_app(units: Mapping, uids: Iterable[str]) -> str:
    tot: Counter = Counter()
    for uid in uids:
        u = units.get(uid)
        for a, m in (get(u, "app_ids", {}) or {}).items():
            tot[a] += int(m)
    s = sum(tot.values())
    if not s:
        return ""
    a, m = min(tot.items(), key=lambda kv: (-kv[1], kv[0]))
    return a if m / s >= APP_SHARE else ""


def _merge_rule(rules: list[dict], new: Mapping, today: str) -> None:
    for i, r in enumerate(rules):
        if r["id"] != new["id"]:
            continue
        if r.get("then") != new.get("then"):                       # 같은 조건 키가 다른 결과 → 늦은 것이 이긴다
            old = dict(r)
            old["status"] = "superseded"
            old["reason"] = "superseded"
            old["updated_at"] = today
            n = sum(1 for x in rules if x["id"].startswith(r["id"] + "~"))
            old["id"] = f"{r['id']}~{n + 1}"
            rules.append(old)
            rules[i] = dict(new)
            return
        cur = dict(r)
        if cur.get("status") not in ("off", "retired"):
            cur["status"] = new["status"] if cur.get("status") != "active" else "active"
        cur["support"] = max(int(cur.get("support", 0)), int(new.get("support", 0)))
        cur["from"] = sorted(set(cur.get("from") or ()) | set(new.get("from") or ()))
        cur["updated_at"] = today
        rules[i] = cur
        return
    rules.append(dict(new))


def learn_rules(corrections: Iterable[Mapping], feats_by_unit: Mapping[str, Iterable], df: Mapping[str, int],
                n_groups: int, existing=(), *, units: Mapping | None = None,
                group_of: Mapping[str, str] | None = None, cfg=None, reg=None,
                today: str = "") -> tuple[list[dict], list[str]]:
    """아직 배우지 않은 수정 기록(대상이 이번 실행에 있는 것)에서 규칙을 배운다. 반환 (규칙 목록, learned_from).
    existing = 이전 `rules_learned.json` 객체 또는 규칙 목록. 대상이 없는 기록은 다음 실행으로 미룬다."""
    if isinstance(existing, Mapping):
        rules = [dict(r) for r in existing.get("rules") or () if isinstance(r, Mapping)]
        done = {str(x) for x in existing.get("learned_from") or ()}
    else:
        rules = [dict(r) for r in existing or () if isinstance(r, Mapping)]
        done = set()
    for r in rules:
        done.update(str(x) for x in r.get("from") or ())
    excl = excluded_tokens(reg, cfg)
    us = units or {}
    for c in sorted(corrections, key=lambda x: (str(x.get("at") or ""), str(x.get("id") or ""))):
        cid = str(c.get("id") or "")
        if not cid or cid in done:
            continue
        targets = match_units(c, us, group_of)
        if not targets:
            continue
        feats = [f for uid in targets for f in (feats_by_unit.get(uid) or ())]
        new = learn_from(c, feats, df, n_groups, rules, cfg=cfg, reg=reg, app_of_target=_main_app(us, targets),
                         today=today, excluded=excl)
        for nr in new:
            _merge_rule(rules, nr, today)
        done.add(cid)
    return sorted(rules, key=lambda r: r["id"]), sorted(done)


# ───────────────────────── 정밀도 추적 ─────────────────────────
def retire_check(agree: int, disagree: int, status: str = "active", cfg=None) -> tuple[str, float | None]:
    """적중 ≥ `hier.learn.retireMinHits` 이고 정밀도 < `retireMinPrec` 이면 ('retired', 정밀도)."""
    cfg = default_cfg(cfg)
    min_hits = int(cfg["hier.learn.retireMinHits"])            # 둘 다 먼저 읽는다(cfg_used 가 자료에 따라 바뀌지 않게)
    min_prec = float(cfg["hier.learn.retireMinPrec"])
    n = int(agree) + int(disagree)
    prec = agree / n if n else None
    if n >= min_hits and prec is not None and prec < min_prec:
        return "retired", prec
    return status, prec


def track_precision(rules: Iterable[Mapping], labels: Mapping, hits: Mapping[str, Iterable[str]], *, cfg=None,
                    today: str = "") -> list[dict]:
    """이번 실행의 적중 수·일치·불일치를 규칙에 적고, 문턱 아래면 retired. hits = {규칙 id: 적중 unit_id}.
    일치 판정은 과제 축이 사용자·토큰 출처인 라벨만(그 밖은 정답이 아니다)."""
    out = []
    for r in rules:
        d = dict(r)
        if d.get("status") != "active" or "project" not in (d.get("then") or {}):
            out.append(d)
            continue
        P = d["then"]["project"]
        groups, agree, dis = set(), 0, 0
        seen_g = set()
        for uid in sorted(set(hits.get(d["id"], ()))):
            lb = labels.get(uid)
            if lb is None:
                continue
            g = get(lb, "group", "") or uid
            groups.add(g)
            src = (get(lb, "src", {}) or {}).get("project")
            if src not in ("user", "token") or g in seen_g:
                continue
            seen_g.add(g)
            if get(lb, "project", None) == P:
                agree += 1
            else:
                dis += 1
        d["hits"], d["agree"], d["disagree"] = len(groups), agree, dis
        st, prec = retire_check(agree, dis, "active", cfg)
        if st == "retired":
            d["status"] = "retired"
            d["reason"] = f"정밀도 {agree}/{agree + dis}"
            d["updated_at"] = today
        out.append(d)
    return out


def load_learned(paths=None, *, path=None) -> dict:
    """`rules_learned.json` → {rules, learned_from}(없거나 깨지면 빈 것 — 깨지면 .bak)."""
    p = path if path is not None else paths.hier_local_file(LEARNED)
    obj = fsx.read_json(p, default=None)
    if not isinstance(obj, Mapping) and paths is not None:
        obj = fsx.read_json(paths.hier_local_file(LEARNED_BAK), default=None)
    if not isinstance(obj, Mapping):
        return {"schema": LEARNED_SCHEMA, "rules": [], "learned_from": []}
    return {"schema": LEARNED_SCHEMA, "rules": [dict(r) for r in obj.get("rules") or () if isinstance(r, Mapping)],
            "learned_from": [str(x) for x in obj.get("learned_from") or ()]}


def save_learned(paths, rules: Iterable[Mapping], learned_from: Iterable[str]) -> bool:
    """원자 쓰기(직전 판 .bak). 바뀐 것이 없으면 쓰지 않고 False."""
    p = paths.hier_local_file(LEARNED)
    data = fsx.canon_bytes({"schema": LEARNED_SCHEMA, "rules": sorted((dict(r) for r in rules), key=lambda r: r["id"]),
                            "learned_from": sorted(set(learned_from))})
    try:
        old = fsx.read_bytes(p)
    except OSError:
        old = None
    if old == data:
        return False
    if old is not None:
        fsx.atomic_write(paths.hier_local_file(LEARNED_BAK), old)
    fsx.atomic_write(p, data)
    return True


def token_df(groups_tokens: Mapping[str, Iterable[str]]) -> tuple[dict[str, int], int]:
    """군집 키 → 토큰 집합 → (토큰 문서 빈도, 군집 수)."""
    df: Counter = Counter()
    for toks in groups_tokens.values():
        df.update(set(toks))
    return dict(df), len(groups_tokens)


def ukeys_of(names: Iterable[str]) -> set[str]:
    return {ukey(n) for n in names if n}
