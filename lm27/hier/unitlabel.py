# -*- coding: utf-8 -*-
r"""단위업무 라벨의 규칙 판정 — 증거 모음 · 과제/영역 · 분야/기능 · 업무 유형 · 참여 방식 · AX 연계 · role_id
(H §4.6~§4.8 · §10 · §1.4, 계약 §2.10 · §4.4 · §6.6).

- `unit_inputs(tasks, feats, attrib, catalog)` → `{unit_id: UnitIn}`. 시간 코어의 단위업무(`tasks.json` 행 또는 `UnitTask`)와
  슬롯 귀속(`attrib.jsonl` 행)에서 역할별 증거(boundary 2.0 · msg 1.0 · doc 1.5×강도/3 · meet 1.0 · app 1.0 — `hier.unit.w`)와
  귀속 분(앱 범주별 L3 분·회의 L2 분·PC 밖 분·총 투입)을 모은다. 분은 분류 단서이며 코파일럿에 보내지 않는다(B1).
  단위업무를 만들거나 바꾸지 않는다(H-I5) — 입력을 읽기만 한다.
- `unit_rule_label(u, reg, cfg)` → `RuleLabel`(과제·영역, 출처 user·token·rule·rule_probable·domain_rule·none).
- `field_func(u, reg, rl, cfg)` → `FieldFunc`(분야·기능 + 확신 h·m·l). `decide_wtype` → (유형, 확신, 근거).
- `decide_stance(u)` → DO·COORD·REVIEW·LEAD(개인 보고서 전용). `ax_link(u, domain, reg, project)` → bool.
- `role_id(과제 자리, 분야 코드, 기능 코드)` = `"r_" + sha256("LM27.role|" + 자리 + "|" + 분야 + "|" + 기능)[:6]`(계약 §4.4).

앱 범주(카탈로그 한글 9종 — X-245) → 분야·기능 표(`CAT_FIELD`·`CAT_FUNC`·`TECH_CATS`)는 H §4.8·§16 X10 그대로다.
어휘 키워드·업무 유형 판정 낱말은 유효 레지스트리 어휘(`lm27.hier.vocab` 내장 ⊕ 팀 ⊕ 개인)에서 읽는다.
표준 라이브러리만 쓴다. 파일을 쓰지 않는다.
"""
import hashlib
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from dataclasses import field as _dc_field

from lm27.hier import match as _match
from lm27.hier import vocab as _vocab
from lm27.hier.features import Feat, default_cfg, feat, get, union_feat
from lm27.hier.names import ukey
from lm27.hier.rules import NEG, KwIndex, RuleCtx, rule_ctx, score_domains, score_projects

__all__ = [
    "CAT_FIELD", "CAT_FUNC", "KIND_LABELS", "OFFICE_CAT", "OFFPC_BASIS", "TECH_CATS", "FieldFunc", "RuleLabel", "UnitIn",
    "ax_link", "decide_stance", "decide_wtype", "field_func", "make_unit", "role_id", "task_id", "unit_inputs",
    "unit_rule_label", "vocab_hits",
]

CAT_FIELD = {"CAD": "MECH", "EDA": "ELEC", "FPGA": "ELEC", "SW": "SW", "광학": "OPT"}
CAT_FUNC = {"CAD": "DESIGN", "EDA": "DESIGN", "FPGA": "DESIGN", "광학": "DESIGN", "해석": "ANALYSIS", "SW": "IMPL",
            "계측": "TEST"}
TECH_CATS = frozenset({"CAD", "해석", "광학", "EDA", "FPGA", "SW", "계측"})
OFFICE_CAT = "사무"
OFFPC_BASIS = frozenset({"C1b", "C4", "C4L", "C6", "C7", "C10", "C10r"})      # PC 밖 슬롯 근거(다리·흔적 창·원격 발신)
ROLES = ("boundary", "msg", "doc", "meet", "app", "manual")
REVIEW_RX = re.compile(r"검토|리뷰|확인|승인")
MSG_KIND_SET = frozenset({"mail", "teams", "summary"})
_DEF_UNIT_W = {"boundary": 2.0, "msg": 1.0, "doc": 1.5, "meet": 1.0, "app": 1.0}


def _r2(x: float) -> float:
    return round(x, 2)


# ───────────────────────── 자료구조 ─────────────────────────
@dataclass(frozen=True)
class UnitIn:
    """단위업무 하나의 분류 입력(H §4.6). 앞 10 필드가 명세 형, 그 뒤는 군집·이름·질문용 확장."""
    unit_id: str
    kind: str                                            # S1 | ACK | COORD | SELF | APP | REPORT_ONLY | MANUAL
    ev: tuple[tuple[Feat, float, str], ...] = ()         # (특징, 가중, 역할)
    app_min: Mapping[str, int] = field(default_factory=dict)       # 카탈로그 범주 → L3 귀속 분
    meet_min: int = 0
    offpc_min: int = 0
    effort_min: int = 0
    peers_ext: bool = False
    organizer_meetings: int = 0
    sent_requests: int = 0
    # ── 확장 ──
    first_key: str = ""
    start: int = 0                                       # 첫 차수 시작(로컬 초, 없으면 0)
    end: int = 0                                         # 마지막 차수 끝(없으면 0)
    convs: frozenset[str] = frozenset()
    peer: str = ""
    follow_of: str | None = None
    fams: Mapping[str, int] = field(default_factory=dict)          # 문서군 키 → 연결 강도
    fam_min: Mapping[str, int] = field(default_factory=dict)       # 문서군 키 → 귀속 분
    bkeys: frozenset[str] = frozenset()                  # 경계 메시지 키(msg_key·id)
    app_ids: Mapping[str, int] = field(default_factory=dict)       # app_id → L3 귀속 분
    proj: str | None = None                              # 시간 코어가 쓴 증거 꼬리표 과제(참고)
    label: str = ""                                      # 시간 코어 label(정제본)
    fam_names: Mapping[str, str] = field(default_factory=dict)     # 문서군 키 → 가장 최근 문서 이름(정제본)
    subjects: tuple[str, ...] = ()                       # 제목 요지 재료: 시작 근거 · 마지막 종료 근거 · 그 밖 잦은 제목
    kinds: Mapping[str, int] = field(default_factory=dict)         # 흔적 종류별 건수(ai_in kinds — 시간 아님)


@dataclass(frozen=True)
class RuleLabel:
    project: str | None
    score: float
    source: str                                          # user | token | rule | rule_probable | domain_rule | none
    conf: str                                            # h | m | l
    cands: tuple[tuple[str, float], ...]
    domain: str
    why: tuple[str, ...] = ()


@dataclass(frozen=True)
class FieldFunc:
    field: str
    field_conf: str
    func: str
    func_conf: str
    field_src: str = "rule"                              # rule | fallback
    func_src: str = "rule"
    scores: Mapping = _dc_field(default_factory=dict)    # {'field': {...}, 'func': {...}} — 설명(로컬)


def task_id(t) -> str:
    """tasks.json 행(`unit_id`) · UnitTask(`id`) 공용 ID."""
    return str(get(t, "unit_id", None) or get(t, "id", "") or "")


def _feat_peers_ext(f: Feat) -> bool:
    return bool(f.ent.get("고객사")) or bool(f.ent.get("협력사")) or \
        any(lb.startswith(("고객사:", "협력사:")) for lb in f.dom_labels)


def make_unit(unit_id: str, kind: str, ev: Iterable[tuple[Feat, float, str]] = (), **kw) -> UnitIn:
    """골든·도구용 생성기 — peers_ext·organizer_meetings·sent_requests 를 주지 않으면 ev 에서 센다."""
    evs = tuple(ev)
    kw.setdefault("peers_ext", any(_feat_peers_ext(f) for f, _w, _r in evs))
    kw.setdefault("organizer_meetings", sum(1 for f, _w, r in evs if f.kind == "cal" and "organizer_me" in f.flags))
    kw.setdefault("sent_requests", sum(1 for f, _w, r in evs
                                        if f.kind in MSG_KIND_SET and f.direction == "out" and f.act == "request"))
    return UnitIn(unit_id=unit_id, kind=kind, ev=evs, **kw)


# ───────────────────────── 증거 모음(H §4.6) ─────────────────────────
def _cycles(t) -> list:
    cs = get(t, "cycles", None) or []
    return list(cs) if isinstance(cs, list | tuple) else []


def _doc_strength(v) -> int:
    if isinstance(v, bool):
        return 2
    if isinstance(v, int):
        return max(1, min(int(v), 3))
    if isinstance(v, Mapping):
        for k in ("strength", "s", "w"):
            x = v.get(k)
            if isinstance(x, int) and not isinstance(x, bool):
                return max(1, min(x, 3))
        ops = v.get("ops")
        if isinstance(ops, list | tuple) and any(o in ("attach", "must_link") for o in ops):
            return 3
        if isinstance(ops, Mapping) and any(isinstance(ops.get(k), int) and ops.get(k) > 0
                                            for k in ("attach", "must_link")):
            return 3
    return 2


def attrib_rows(attrib) -> list[Mapping]:
    if attrib is None:
        return []
    rows_fn = getattr(attrib, "rows", None)
    if callable(rows_fn):                                   # 시간 코어 Attribution 객체(rows() = attrib.jsonl 행)
        return [r for r in rows_fn() if isinstance(r, Mapping)]
    if isinstance(attrib, Mapping):
        rows = attrib.get("rows") or attrib.get("attrib") or []
    else:
        rows = attrib
    return [r for r in rows if isinstance(r, Mapping)]


def tables_json(team_tables):
    """정수 분 표 → team_tables.json 모양(사전이면 그대로, 시간 코어 TeamTables 면 as_json())."""
    fn = getattr(team_tables, "as_json", None)
    return fn() if callable(fn) else team_tables


def _alloc_min(team_tables) -> dict[str, int]:
    out: dict[str, int] = defaultdict(int)
    team_tables = tables_json(team_tables)
    ad = get(team_tables, "alloc_daily", None) if team_tables is not None else None
    rows = get(ad, "rows", None) or []
    for r in rows:
        if isinstance(r, list | tuple) and len(r) >= 4 and isinstance(r[3], int):
            out[str(r[1])] += int(r[3])
    return dict(out)


def _mins(sec: Mapping[str, int]) -> dict[str, int]:
    return {k: (int(v) + 30) // 60 for k, v in sorted(sec.items()) if v > 0}


class _FeatIndex:
    def __init__(self, feats: Iterable[Feat]):
        self.by_id: dict[str, Feat] = {}
        self.by_key: dict[str, Feat] = {}
        self.by_conv: dict[str, list[Feat]] = defaultdict(list)
        self.by_fam: dict[str, list[Feat]] = defaultdict(list)
        self.att_fam: dict[str, list[tuple[Feat, str]]] = defaultdict(list)
        self.cals: list[Feat] = []
        self.wins: dict[str, list[Feat]] = defaultdict(list)
        self.manuals: list[Feat] = []
        for f in sorted(feats, key=lambda x: (x.t, x.id)):
            self.by_id.setdefault(f.id, f)
            if f.key:
                self.by_key.setdefault(f.key, f)
            if f.kind in MSG_KIND_SET and f.conv:
                self.by_conv[f.conv].append(f)
            if f.kind in ("file", "win", "git", "compute"):
                for fk in f.fams:
                    self.by_fam[fk].append(f)
            if f.kind in ("mail", "teams"):
                for fk, nm in f.names:
                    self.att_fam[fk].append((f, nm))
            if f.kind == "cal":
                self.cals.append(f)
            if f.kind == "win" and f.app:
                self.wins[f.app].append(f)
            if f.kind == "manual":
                self.manuals.append(f)

    def ref(self, r) -> Feat | None:
        if not isinstance(r, str) or not r:
            return None
        return self.by_id.get(r) or self.by_key.get(r)

    def fam_feat(self, fk: str) -> Feat | None:
        parts = list(self.by_fam.get(fk, ()))
        for f, nm in self.att_fam.get(fk, ()):
            parts.append(feat(f.id + "#" + fk, "file", nm, t=f.t, fams=(fk,), names=((fk, nm),)))
        if not parts:
            return None
        return union_feat(parts, "fam:" + fk)

    def latest_name(self, fk: str) -> str:
        """문서군의 가장 최근 이름(파일·창·첨부 — 시각 최대, 동률은 이름순)."""
        best = None
        for f in self.by_fam.get(fk, ()):
            for k, nm in f.names:
                if k == fk and nm and (best is None or (f.t, nm) > best):
                    best = (f.t, nm)
        for f, nm in self.att_fam.get(fk, ()):
            if nm and (best is None or (f.t, nm) > best):
                best = (f.t, nm)
        return best[1] if best else ""

    def cal_at(self, slots: Iterable[int]) -> list[Feat]:
        ss = sorted(set(slots))
        if not ss or not self.cals:
            return []
        out = []
        for c in self.cals:
            b = c.t_end or c.t
            if any(c.t <= s < b for s in ss):
                out.append(c)
        return out

    def wins_at(self, app: str, slots: Iterable[int], slot_len: int = 300) -> list[Feat]:
        ss = sorted(set(slots))
        out = []
        for w in self.wins.get(app, ()):
            b = w.t_end or (w.t + 60)
            if any(w.t < s + slot_len and s < b for s in ss):
                out.append(w)
        return out


def unit_inputs(tasks: Iterable, feats: Iterable[Feat], attrib=None, catalog=None, *, cfg=None, team_tables=None,
                slot_basis: Mapping[int, str] | None = None) -> dict[str, UnitIn]:
    """단위업무별 증거 모음(H §4.6). tasks = tasks.json 행 또는 UnitTask, attrib = attrib.jsonl 행 목록,
    team_tables = 정수 분 표(있으면 투입은 alloc 합 — 개인 = 팀), slot_basis = 슬롯 → 봉투 근거(env_slots — PC 밖 분)."""
    cfg = default_cfg(cfg)
    uw = dict(_DEF_UNIT_W)
    uw.update({str(k): float(v) for k, v in dict(cfg["hier.unit.w"]).items()})
    ix = _FeatIndex(feats)
    cat_of = _cat_fn(catalog, cfg)
    rows_by: dict[str, list[Mapping]] = defaultdict(list)
    for r in attrib_rows(attrib):
        tgt = r.get("target")
        if isinstance(tgt, str) and tgt:
            rows_by[tgt].append(r)
    alloc = _alloc_min(team_tables)
    out: dict[str, UnitIn] = {}
    for t in sorted(tasks, key=task_id):
        uid = task_id(t)
        if not uid:
            continue
        out[uid] = _one(t, uid, ix, rows_by.get(uid, []), alloc, uw, cat_of, slot_basis)
    return out


def _cat_fn(catalog, cfg):
    cat = catalog
    if cat is None:
        from lm27 import catalog as cat                       # 지연 import — 카탈로그 단일원(X-245)
    pe = getattr(cat, "programs_extra", None)
    extra = tuple(pe(cfg)) if callable(pe) else ()
    memo: dict[str, str] = {}

    def f(app: str) -> str:
        if not app:
            return ""
        if app not in memo:
            memo[app] = (cat.cat_of(app, extra) if extra else cat.cat_of(app)) or ""
        return memo[app]
    return f


def _one(t, uid: str, ix: _FeatIndex, rows: list[Mapping], alloc: Mapping[str, int], uw: Mapping[str, float],
         cat_of, slot_basis) -> UnitIn:
    kind = str(get(t, "kind", "") or "")
    convs = {str(get(t, "conv", "") or "")} | {str(x) for x in (get(t, "convs", None) or ()) if x}
    convs.discard("")
    docs_raw = get(t, "docs", None) or {}
    docs = {str(k): _doc_strength(v) for k, v in sorted(docs_raw.items())} if isinstance(docs_raw, Mapping) else {}
    cycles = _cycles(t)
    ev: list[tuple[Feat, float, str]] = []
    used: set[str] = set()
    bkeys: set[str] = set()

    def push(f: Feat | None, role: str, w: float | None = None) -> None:
        if f is None or f.id in used:
            return
        used.add(f.id)
        ev.append((f, uw.get(role, 1.0) if w is None else w, role))
    # boundary — 시작·종료 근거 메시지(id 또는 msg_key), 중간 보고(E1p)
    starts, ends = [], []
    for c in cycles:
        for k in ("s_ref", "e_ref"):
            f = ix.ref(get(c, k, None))
            if f is not None and f.kind in MSG_KIND_SET:
                push(f, "boundary")
                bkeys.update(x for x in (f.key, f.id) if x)
            elif f is not None and f.kind == "cal":
                push(f, "meet")
        s, e = get(c, "s", None), get(c, "e", None)
        if isinstance(s, int):
            starts.append(s)
        if isinstance(e, int):
            ends.append(e)
        for it in get(c, "interim", None) or ():
            ti = it[0] if isinstance(it, list | tuple) and it else None
            code = it[1] if isinstance(it, list | tuple) and len(it) > 1 else ""
            if isinstance(ti, int) and code == "E1p":
                for cv in sorted(convs):
                    for m in ix.by_conv.get(cv, ()):
                        if m.t == ti and m.direction == "out":
                            push(m, "boundary")
                            bkeys.update(x for x in (m.key, m.id) if x)
    # msg — 같은 대화의 다른 메시지 + 추가 지시
    for a in get(t, "adds", None) or ():
        if isinstance(a, list | tuple) and len(a) >= 2:
            push(ix.ref(a[1]) or (ix.ref(a[2]) if len(a) > 2 else None), "msg")
    for cv in sorted(convs):
        for m in ix.by_conv.get(cv, ()):
            push(m, "msg")
    # doc — 연결 문서군(강도 3 → 1.5, 2 → 1.0, 자체 업무의 자기 문서군 1.5)
    for fk, st in docs.items():
        uf = ix.fam_feat(fk)
        if uf is not None:
            w = uw.get("doc", 1.5) if kind == "SELF" else uw.get("doc", 1.5) * st / 3.0
            push(uf, "doc", w)
    # 귀속 행 → 분
    cat_sec: dict[str, int] = defaultdict(int)
    app_sec: dict[str, int] = defaultdict(int)
    fam_sec: dict[str, int] = defaultdict(int)
    meet_sec = offpc_sec = tot_sec = 0
    l2_slots: list[int] = []
    l3_slots: dict[str, list[int]] = defaultdict(list)
    for r in rows:
        sec = r.get("sec")
        if not isinstance(sec, int) or isinstance(sec, bool) or sec <= 0:
            continue
        tot_sec += sec
        lv = str(r.get("level") or "")
        slot = r.get("slot") if isinstance(r.get("slot"), int) else None
        app = str(r.get("app") or "")
        fk = str(r.get("fam") or "")
        if fk:
            fam_sec[fk] += sec
        if lv.startswith("L3"):
            if app:
                app_sec[app] += sec
                cat_sec[cat_of(app) or ""] += sec
                if slot is not None:
                    l3_slots[app].append(slot)
        elif lv.startswith("L2"):
            meet_sec += sec
            if slot is not None:
                l2_slots.append(slot)
        if slot_basis is not None and slot is not None:
            if slot_basis.get(slot) in OFFPC_BASIS:
                offpc_sec += sec
        elif lv.startswith("L5공백"):
            offpc_sec += sec
    # meet — 회의 L2 슬롯과 겹치는 일정 + 시간 코어가 연결한 회의
    for mref in get(t, "meet_refs", None) or ():
        mid = get(mref[0], "id", None) if isinstance(mref, list | tuple) and mref else get(mref, "id", None)
        f = ix.ref(mid)
        if f is not None and f.kind == "cal":
            push(f, "meet")
    for f in ix.cal_at(l2_slots):
        push(f, "meet")
    # app — 앱마다 1건(그 앱 L3 슬롯과 겹치는 창 특징의 합집합)
    app_ids = sorted(set(app_sec) | ({str(get(t, "app", ""))} - {""}))
    for app in app_ids:
        ws = ix.wins_at(app, l3_slots.get(app, ())) if app in l3_slots else []
        if ws:
            uf = union_feat(ws, f"app:{uid}:{app}", "win")
            uf = _with_app(uf, app, cat_of(app))
        else:
            uf = Feat(id=f"app:{uid}:{app}", kind="win", app=app, app_cat=cat_of(app))
        push(uf, "app")
    # manual — 수동 기록·확인 응답의 ref, MANUAL 업무의 그 기록
    keys = bkeys | set(convs) | set(docs) | {str(get(t, "first_key", "") or "")}
    fk0 = str(get(t, "first_key", "") or "")
    man_ref = fk0[len("manual:"):] if fk0.startswith("manual:") else ""
    for m in ix.manuals:
        if (man_ref and (m.id == man_ref or m.key == man_ref)) or (m.refs & keys):
            push(m, "manual", 1.0)
    # 투입 = 정수 분 표(alloc 합)가 있으면 그것, 없으면 귀속 초, 없으면 시간 코어 effort_s
    if uid in alloc:
        effort = alloc[uid]
    elif tot_sec:
        effort = (tot_sec + 30) // 60
    else:
        es = get(t, "effort_s", None)
        effort = (int(es) + 30) // 60 if isinstance(es, int) and not isinstance(es, bool) else 0
    feats = [f for f, _w, _r in ev]
    cat_min = _mins(cat_sec)
    cat_min.pop("", None)
    s_first = ix.ref(get(cycles[0], "s_ref", None)) if cycles else None
    e_last = ix.ref(get(cycles[-1], "e_ref", None)) if cycles else None
    return UnitIn(
        unit_id=uid, kind=kind, ev=tuple(ev), app_min=cat_min, meet_min=(meet_sec + 30) // 60,
        offpc_min=(offpc_sec + 30) // 60, effort_min=int(effort),
        peers_ext=any(_feat_peers_ext(f) for f in feats),
        organizer_meetings=sum(1 for f in feats if f.kind == "cal" and "organizer_me" in f.flags),
        sent_requests=sum(1 for f in feats if f.kind in MSG_KIND_SET and f.direction == "out" and f.act == "request"),
        first_key=fk0, start=min(starts) if starts else 0, end=max(ends) if ends else 0, convs=frozenset(convs),
        peer=str(get(t, "peer", "") or ""), follow_of=get(t, "follow_of", None) or None, fams=docs,
        fam_min=_mins(fam_sec), bkeys=frozenset(bkeys), app_ids=_mins(app_sec),
        proj=get(t, "proj", None) or None, label=str(get(t, "label", "") or ""),
        fam_names={fk: ix.latest_name(fk) for fk in docs if ix.latest_name(fk)},
        subjects=_subjects(s_first, e_last, ev), kinds=_kinds(ev))


def _subjects(s_first: Feat | None, e_last: Feat | None, ev) -> tuple[str, ...]:
    """제목 요지(H §6.2 subjects): 시작 근거 제목 · 마지막 종료 근거 제목 · 그 밖 가장 잦은 대화 제목(ukey 가 다른 것만).
    메시지가 없으면 회의 제목."""
    out: list[str] = []
    seen: set[str] = set()

    def add(x: str) -> None:
        k = ukey(x)
        if x and k and k not in seen:
            seen.add(k)
            out.append(x)
    for f in (s_first, e_last):
        if f is not None and f.kind in MSG_KIND_SET:
            add(f.subject)
    cnt: dict[str, list] = {}
    for f, _w, r in ev:
        if r in ("boundary", "msg") and f.kind in MSG_KIND_SET and f.subject:
            k = ukey(f.subject)
            if k and k not in seen:
                e = cnt.setdefault(k, [0, f.subject])
                e[0] += 1
    if not cnt:
        for f, _w, r in ev:
            if r == "meet" and f.subject:
                k = ukey(f.subject)
                if k and k not in seen:
                    e = cnt.setdefault(k, [0, f.subject])
                    e[0] += 1
    if cnt:
        k, (_n, subj) = min(cnt.items(), key=lambda kv: (-kv[1][0], kv[0]))
        add(subj)
    return tuple(out[:3])


KIND_LABELS = ("메일수신", "메일발신", "팀즈수신", "팀즈발신", "회의", "문서", "앱", "수동")


def _kinds(ev) -> dict[str, int]:
    """흔적 종류별 건수(H §6.2 kinds) — 분류 단서이며 시간이 아니다."""
    c: dict[str, int] = defaultdict(int)
    for f, _w, r in ev:
        if f.kind == "mail":
            c["메일발신" if f.direction == "out" else "메일수신"] += 1
        elif f.kind == "teams":
            c["팀즈발신" if f.direction == "out" else "팀즈수신"] += 1
        elif f.kind == "cal":
            c["회의"] += 1
        elif r == "doc":
            c["문서"] += 1
        elif r == "app":
            c["앱"] += 1
        elif f.kind == "manual":
            c["수동"] += 1
    return {k: c[k] for k in KIND_LABELS if c.get(k)}


def _with_app(f: Feat, app: str, cat: str) -> Feat:
    return replace(f, app=app, app_cat=cat)


# ───────────────────────── 과제·영역(H §4.7) ─────────────────────────
class _UnitCfg:
    def __init__(self, cfg):
        cfg = default_cfg(cfg)
        self.min_mass = float(cfg["hier.unit.minMass"])
        self.confirm = float(cfg["hier.unit.confirm"])
        self.margin = float(cfg["hier.unit.margin"])
        self.high = float(cfg["hier.unit.high"])
        self.fallback = float(cfg["hier.unit.fallback"])
        self.p_margin = float(cfg["hier.unit.probableMargin"])
        self.v_top = float(cfg["hier.vocab.top"])
        self.v_margin = float(cfg["hier.vocab.margin"])
        self.v_high = float(cfg["hier.vocab.high"])
        self.v_low = float(cfg["hier.vocab.low"])
        self.office_share = float(cfg["hier.vocab.officeDocShare"])
        self.meet_share = float(cfg["hier.vocab.meetShare"])
        self.tech_dev = float(cfg["hier.wtype.techShareDev"])
        self.tech_high = float(cfg["hier.wtype.techShareHigh"])
        self.offpc_field = float(cfg["hier.wtype.offpcFieldShare"])
        self.offpc_both = float(cfg["hier.wtype.offpcFieldBoth"])
        self.ax_min = int(cfg["hier.ax.minHits"])


_UCFG: list = []


def _ucfg(cfg) -> _UnitCfg:
    for c, u in _UCFG:
        if c is cfg:
            return u
    u = _UnitCfg(cfg)
    _UCFG[:] = [(cfg, u)]
    return u


def unit_rule_label(u: UnitIn, reg, cfg=None, *, ctx: RuleCtx | None = None) -> RuleLabel:
    """단위업무 과제·영역 판정(H §4.7). 사람이 적은 수동 라벨 > 경계 메시지의 단일 과제 토큰 > 증거 점수 > 영역 키워드."""
    c = ctx if ctx is not None and ctx.reg is reg else rule_ctx(reg, cfg)
    uc = _ucfg(cfg if cfg is not None else c.cfg)
    S: dict[str, float] = {}
    D: dict[str, float] = {}
    W = 0.0
    decisive: set[str] = set()
    why: list[str] = []
    for f, w, role in u.ev:
        if f.manual and f.manual.get("project_id"):
            p = reg.resolve(f.manual["project_id"])
            return RuleLabel(p, 1.0, "user", "h", (), reg.domain_of(p), ("manual " + str(f.id),))
        W += w
        wy: dict[str, list[str]] = {}
        sc = score_projects(f, reg, ctx=c, why=wy)
        for pid, v in sc.items():
            s = -1.0 if v == NEG else min(v, c.ev_min) / c.ev_min
            S[pid] = S.get(pid, 0.0) + w * s
            for frag in wy.get(pid, ()):
                why.append(f"{pid} ← {frag} ({role} {f.id})")
        if role == "boundary" and len(f.ent.get("과제", ())) == 1:
            tid = next(iter(f.ent["과제"]))
            p = reg.resolve(tid)
            if p in c.cand and sc.get(p) != NEG:
                decisive.add(p)
        for dom, v in score_domains(f, reg, ctx=c).items():
            D[dom] = D.get(dom, 0.0) + w * min(v, c.ev_min) / c.ev_min
    mass = max(W, uc.min_mass)
    cands = tuple(sorted(((p, _r2(v / mass)) for p, v in S.items() if v > 0), key=lambda x: (-x[1], x[0]))[:3])
    why_t = tuple(why)
    if len(decisive) == 1:                                              # 경계 토큰이 서로 다르면 결정 토큰으로 쓰지 않는다
        p = next(iter(decisive))
        return RuleLabel(p, 1.0, "token", "h", cands, reg.domain_of(p), why_t)
    if cands:
        top = cands[0][1]
        sec = cands[1][1] if len(cands) > 1 else 0.0
        if top >= uc.confirm and top - sec >= uc.margin:
            return RuleLabel(cands[0][0], top, "rule", "h" if top >= uc.high else "m", cands,
                             reg.domain_of(cands[0][0]), why_t)
        if top >= uc.fallback and top - sec >= uc.p_margin:
            return RuleLabel(cands[0][0], top, "rule_probable", "l", cands, reg.domain_of(cands[0][0]), why_t)
    order = {d: i for i, d in enumerate(c.dom_order)}
    dl = sorted(((v / mass, d) for d, v in D.items()), key=lambda x: (-x[0], order.get(x[1], 99)))
    if dl:
        top, dom = dl[0]
        sec = dl[1][0] if len(dl) > 1 else 0.0
        rid = _vocab.RESERVED_BY_DOMAIN[dom]
        if top >= c.d_confirm and top - sec >= c.d_margin:
            return RuleLabel(rid, _r2(top), "domain_rule", "m", cands, dom, why_t + (f"{dom} 영역 키워드 {_r2(top)}",))
        cands = cands + ((rid, _r2(top)),)
    return RuleLabel(None, cands[0][1] if cands else 0.0, "none", "l", cands[:3], "UNC", why_t)


# ───────────────────────── 분야·기능(H §4.8) ─────────────────────────
class _VocabIx:
    def __init__(self, reg):
        self.items: dict[str, list] = {}
        self.ix: dict[str, KwIndex] = {}
        for kind in ("fields", "functions", "activity_types"):
            table = reg.vocab.get(kind, {})
            act = [it for it in table.values() if it.status == "active"]
            self.items[kind] = act
            kws = []
            for ci, it in enumerate(act):
                for ki, k in enumerate(it.keywords):
                    kws.append((k, (it.code, ci, ki)))
            self.ix[kind] = KwIndex(kws, "head")


_VIX: list = []


def _vix(reg) -> _VocabIx:
    for r, v in _VIX:
        if r is reg:
            return v
    v = _VocabIx(reg)
    _VIX[:] = [(reg, v)]
    return v


def vocab_hits(toks: Iterable[str], index: KwIndex) -> dict[str, int]:
    """토큰마다 가장 긴 어휘 키워드 하나만 센다(입고검사 ⊃ 입고 — H §4.8). 동률은 표 순서 앞."""
    cnt: dict[str, int] = defaultdict(int)
    for t in sorted(set(toks)):
        best = None
        for k, (code, ci, ki) in index.hits({t}):
            key = (-len(k), ci, ki)
            if best is None or key < best[0]:
                best = (key, code)
        if best is not None:
            cnt[best[1]] += 1
    return dict(cnt)


def _app_match(app: str, hint: str) -> bool:
    a, h = str(app).lower(), str(hint).lower()
    if not a or not h:
        return False
    return a == h or a.startswith(h + "_") or h in a.replace("-", "_").split("_") or \
        a.replace("_", "") == h.replace("_", "")


def _pick(d: Mapping[str, float], fallback: str, uc: _UnitCfg) -> tuple[str, str, str]:
    lst = sorted(((k, v) for k, v in d.items() if v > 0), key=lambda x: (-x[1], x[0]))
    if not lst:
        return fallback, "l", "fallback"
    top = lst[0][1]
    sec = lst[1][1] if len(lst) > 1 else 0.0
    if top >= uc.v_top and top - sec >= uc.v_margin:
        return lst[0][0], ("h" if top >= uc.v_high else "m"), "rule"
    if top >= uc.v_low:
        return lst[0][0], "l", "rule"
    return fallback, "l", "fallback"


def field_func(u: UnitIn, reg, rl: RuleLabel, cfg=None, *, ctx: RuleCtx | None = None) -> FieldFunc:
    """분야·기능 판정(H §4.8). 어휘 키워드(긴 것 하나만) · 확장자 · 앱 힌트 · 앱 범주 · 과제·본인 기본값 · 구조 신호 · 규칙."""
    c = ctx if ctx is not None and ctx.reg is reg else rule_ctx(reg, cfg)
    uc = _ucfg(cfg if cfg is not None else c.cfg)
    vx = _vix(reg)
    feats = [f for f, _w, _r in u.ev]
    toks = frozenset().union(*(f.toks for f in feats)) if feats else frozenset()
    exts = frozenset().union(*(f.exts for f in feats)) if feats else frozenset()
    apps = {f.app for f in feats if f.app} | set(u.app_ids)
    cats = {f.app_cat for f in feats if f.app_cat}
    fs: dict[str, float] = defaultdict(float)
    for code, n in vocab_hits(toks, vx.ix["fields"]).items():
        fs[code] += min(1.0 * n, 3.0)
    for it in vx.items["fields"]:
        ne = len(exts & {e.lower() for e in it.exts})
        if ne:
            fs[it.code] += 1.5 * ne
        if it.apps and any(_app_match(a, h) for a in apps for h in it.apps):
            fs[it.code] += 2.0
    for cat in sorted(cats):
        if CAT_FIELD.get(cat):
            fs[CAT_FIELD[cat]] += 2.0
    pv = reg.projects.get(reg.resolve(rl.project)) if rl.project else None
    pdf = getattr(pv, "default_field", "") if pv is not None else ""
    if pdf:
        fs[pdf] += 1.5
    person = reg.person or {}
    my_field = str(person.get("default_field") or "")
    if my_field:
        fs[my_field] += 1.0
    cs: dict[str, float] = defaultdict(float)
    if u.kind == "COORD":
        cs["MEET"] += 1.5
        cs["PM"] += 1.0
    if u.kind == "REPORT_ONLY":
        cs["DOC"] += 2.0
    tot = sum(u.app_min.values()) or 1
    for cat, m in sorted(u.app_min.items()):
        if CAT_FUNC.get(cat):
            cs[CAT_FUNC[cat]] += 3.0 * m / tot
    office = u.app_min.get(OFFICE_CAT, 0)
    tech = sum(m for cat, m in u.app_min.items() if cat in TECH_CATS)
    if u.effort_min and office / u.effort_min >= uc.office_share and tech == 0:
        cs["DOC"] += 1.5
    if u.effort_min and u.meet_min / u.effort_min >= uc.meet_share:
        cs["MEET"] += 2.0
    for code, n in vocab_hits(toks, vx.ix["functions"]).items():
        cs[code] += min(1.0 * n, 3.0)
    if any(f.ent.get("협력사") for f in feats):
        cs["OUTSRC"] += 1.0
    pdc = getattr(pv, "default_func", "") if pv is not None else ""
    if pdc:
        cs[pdc] += 1.0
    for f in feats:
        for r, w in c.rule_hits(f, "field"):
            fs[r.then[1]] += w
        for r, w in c.rule_hits(f, "func"):
            cs[r.then[1]] += w
    fcodes = set(reg.vocab.get("fields", {}))
    ccodes = set(reg.vocab.get("functions", {}))
    fs = {k: v for k, v in fs.items() if k in fcodes}
    cs = {k: v for k, v in cs.items() if k in ccodes}
    fb = my_field if my_field in fcodes else "ETC"
    fcode, fconf, fsrc = _pick(fs, fb, uc)
    ccode, cconf, csrc = _pick(cs, "ETC", uc)
    return FieldFunc(fcode, fconf, ccode, cconf, fsrc, csrc,
                     {"field": dict(sorted(fs.items())), "func": dict(sorted(cs.items()))})


# ───────────────────────── 업무 유형·참여 방식·AX 연계(H §10) ─────────────────────────
def _words_hit(vx: _VocabIx, code: str, toks: frozenset[str]) -> bool:
    it = next((x for x in vx.items["activity_types"] if x.code == code), None)
    if it is None or not it.keywords:
        return False
    return any(_match.kw_hit(k, toks, "head") for k in it.keywords)


def decide_wtype(u: UnitIn, ff: FieldFunc, rl: RuleLabel, reg=None, cfg=None, *,
                 ctx: RuleCtx | None = None) -> tuple[str, str, str]:
    """업무 유형(H §10.1) — 결정 목록을 위에서부터 보고 처음 맞는 줄. 반환 (코드, 확신, 근거)."""
    if reg is None:
        raise ValueError("decide_wtype: 유효 레지스트리가 필요합니다(유형 판정 낱말·규칙)")
    c = ctx if ctx is not None and ctx.reg is reg else rule_ctx(reg, cfg)
    uc = _ucfg(cfg if cfg is not None else c.cfg)
    vx = _vix(reg)
    codes = set(reg.vocab.get("activity_types", {}))
    feats = [f for f, _w, _r in u.ev]
    toks = frozenset().union(*(f.toks for f in feats)) if feats else frozenset()
    best = None
    for f in feats:
        for r, w in c.rule_hits(f, "wtype"):
            if r.then[1] in codes and (best is None or (-w, r.id) < (-best[1], best[0].id)):
                best = (r, w)
    if best is not None:
        return best[0].then[1], "m", "rule:" + best[0].id
    eff = max(u.effort_min, 1)
    off = u.offpc_min / eff
    tech = sum(m for cat, m in u.app_min.items() if cat in TECH_CATS)
    share = tech / eff
    field_hit = _words_hit(vx, "FIELD", toks)
    if field_hit or off >= uc.offpc_field:
        conf = "m" if (field_hit and off >= uc.offpc_both) else "l"
        return "FIELD", conf, "현장 낱말·PC 밖"
    if _words_hit(vx, "EDU", toks) and (rl.domain in ("EXT", "COM") or ff.func == "STUDY"):
        return "EDU", "m", "교육 낱말"
    if u.kind == "COORD":
        if _words_hit(vx, "PM", toks) or u.peers_ext:
            return "PM", "m", "조율형+일정·외부"
        return "PL", "m", "조율형+사내"
    if ff.func == "PM":
        return "PM", "l", "기능 PM"
    if share >= uc.tech_dev or (ff.func in ("DESIGN", "ANALYSIS", "TEST", "IMPL") and tech > 0):
        conf = "h" if share >= uc.tech_high else ("m" if share >= uc.tech_dev else "l")
        return "DEV", conf, f"공학 앱 {share:.2f}"
    if rl.domain == "EXT" or ff.func == "SUPPORT":
        return "SUPPORT", "l", "외부지원·대응"
    return "OFFICE", ("m" if share < 0.1 else "l"), f"공학 앱 {share:.2f}"


def decide_stance(u: UnitIn) -> str:
    """참여 방식(H §10.2): COORD · LEAD · REVIEW · DO. '검토' 는 상용구라 토큰이 아니라 정제문 정규식으로 본다."""
    if u.kind == "COORD":
        return "COORD"
    if u.organizer_meetings >= 1 and u.sent_requests >= 1:
        return "LEAD"
    if u.kind == "S1" and u.effort_min < 30 and any(REVIEW_RX.search(f.text or "") for f, _w, r in u.ev
                                                    if r in ("boundary", "msg")):
        return "REVIEW"
    return "DO"


def ax_link(u: UnitIn, domain: str, reg, project, cfg=None) -> bool:
    """AX 연계(H §10.3): AX 영역 자체는 False, 과제 지정 → True, 강한 낱말 1개 또는 AX 낱말 `hier.ax.minHits` 개."""
    if domain == "AX":
        return False
    pv = reg.projects.get(reg.resolve(project)) if project else None
    if pv is not None and pv.ax_link:
        return True
    uc = _ucfg(default_cfg(cfg))
    feats = [f for f, _w, _r in u.ev]
    toks = frozenset().union(*(f.toks for f in feats)) if feats else frozenset()
    text = " ".join(f.text for f in feats if f.text)
    hits = set()
    for k in reg.domain_kw.get("AX", ()):
        kl = str(k).strip().lower()
        if kl == "ai":
            if _match.ai_hit(text):
                hits.add(kl)
        elif _match.kw_hit(k, toks, "head"):
            hits.add(kl)
    return bool(hits & _vocab.AX_STRONG) or len(hits) >= uc.ax_min


def role_id(project_or_proposal: str | None, field: str, func: str) -> str:
    """R-8 식(계약 §4.4) — 자리 = 과제 ID · 제안 ID · 'UNC', 분야·기능 = 어휘 코드."""
    slot = project_or_proposal or "UNC"
    return "r_" + hashlib.sha256(f"LM27.role|{slot}|{field}|{func}".encode()).hexdigest()[:6]
