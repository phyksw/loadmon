# -*- coding: utf-8 -*-
r"""같이 일한 동료(R §4.5 · §6.5 · 부록 A `peers_layer`, 계약 §3.16 동료 절 · §3.18 peers).

`peers_of(u)` = 단위업무 u 의 who_key 집합과 관계 꼬리표:

- requester(시작 근거 메시지의 상대) · reporter(종료 근거 보고의 상대): 시간 코어 `tasks.json peers` 그대로(W-4 반영분).
- thread: u 에 연결된 대화(`conv`)에서 그 사람과 주고받은 메시지가 `report.peers.minMsgs`(2)건 이상 — 참조(cc)·단체(bulk)
  수신만 있는 메시지는 세지 않는다.
- meeting: u 에 연결된 회의(시간 코어 표식 '회의연결 …'·S2m·E3c 회의)의 참석자, 참석 인원 ≤ `report.peers.maxMeetingSize`(10).
- 제외: 본인(사람 사전 `self`), 큰 회의만으로 엮인 사람, cc·bulk 수신만 있는 사람(사적·광고 메시지는 정규화에서 이미 빠짐).

thread·meeting 을 확인하려면 정규화 증거(`evidence` — 시간 코어 `Evidence` 의 `msgs`·`meets`, 또는 같은 필드의 dict 행
{"msgs": [...], "meets": [...]})가 필요하다. 증거가 없으면 시간 코어 관계를 그대로 쓰고 경고 `peers_unverified` 를 남긴다.

지표: units(공동 단위업무 수) · shared_effort_min(그 단위업무들의 투입 합 — 정수 분 표) · roles(관계별 단위업무 수) ·
projects(분 내림차순 상위 3) · first·last(함께한 단위업무 경계 날짜). 정렬 = shared_effort_min ↓ → units ↓ → who_key.
사내(사람 사전 internal)와 미확인은 개인 목록(`internal`), 외부는 도메인 계급(고객사·협력사·그 밖) **사람 수**로만 모은다.

`key`(who_key)는 로컬 해석용이다 — 보고서 모델은 `refs.people` 정수 참조로 바꿔 싣는다(R §9.2.2, WP-31 model).

설정(R §10.2): `report.peers.minMsgs` · `maxMeetingSize` · `topN`. 표준 라이브러리만 쓴다. 파일을 쓰지 않는다.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from lm27.report import vocab as V
from lm27.report.analysis.activity import Unit, lmin_date

__all__ = ["RELS", "PeerIndex", "external_class", "peer_index", "peers_layer", "peers_section"]

RELS = ("requester", "reporter", "thread", "meeting")
EXT_CLASSES = ("customer", "partner", "other")


def _get(o, k, d=None):
    if o is None:
        return d
    v = o.get(k, d) if isinstance(o, Mapping) else getattr(o, k, d)
    return d if v is None else v


@dataclass
class PeerIndex:
    """동료 계산 결과(분석 내부 — 온톨로지·서브에이전트·리뷰가 함께 쓴다)."""
    by_unit: dict[str, dict[str, frozenset]] = field(default_factory=dict)    # unit_id → who → 관계
    weight: dict[tuple[str, str, str], int] = field(default_factory=dict)     # (unit, who, 관계) → 근거 수
    cls: dict[str, str] = field(default_factory=dict)                         # who → internal|unknown|customer|…
    verified: bool = False
    self_keys: frozenset = frozenset()


class _Ev:
    """정규화 증거 보기(시간 코어 Evidence 또는 dict 행)."""

    def __init__(self, evidence):
        self.thread: Counter = Counter()      # (conv, who) → 메시지 수(cc·bulk 제외)
        self.meet: dict[str, tuple[frozenset, int]] = {}
        for m in _get(evidence, "msgs", ()) or ():
            fl = {str(x) for x in (_get(m, "flags", ()) or ())}
            if "cc" in fl or "bulk" in fl:
                continue
            conv, who = str(_get(m, "conv", "") or ""), str(_get(m, "peer", "") or "")
            if conv and who:
                self.thread[(conv, who)] += 1
        for mt in _get(evidence, "meets", ()) or ():
            att = frozenset(str(x) for x in (_get(mt, "attendees", ()) or ()))
            n = int(_get(mt, "n_att", len(att)) or len(att))
            for k in (_get(mt, "id", ""), _get(mt, "key", "")):
                if k:
                    self.meet[str(k)] = (att, n)


def _people(person_dir) -> Mapping:
    p = _get(person_dir, "people", None)
    return p if isinstance(p, Mapping) else {}


def _domains(items) -> list[tuple[str, str]]:
    out = []
    for it in items or ():
        for d in _get(it, "domains", ()) or ():
            if isinstance(d, str) and d.strip():
                out.append((d.strip().lower().lstrip("@").lstrip("."), str(_get(it, "id", ""))))
    return out


def external_class(who: str, person_dir, registry) -> str:
    """외부 상대의 도메인 계급(customer·partner·other) — 사람 사전 smtp 도메인 ↔ 레지스트리 customers·partners 도메인."""
    rec = _people(person_dir).get(who) or {}
    doms = {str(a).rsplit("@", 1)[-1].lower() for a in (_get(rec, "smtp", ()) or ()) if "@" in str(a)}
    for kind, items in (("customer", _get(registry, "customers", ())), ("partner", _get(registry, "partners", ()))):
        for d, _id in _domains(items):
            if any(x == d or x.endswith("." + d) for x in doms):
                return kind
    return "other"


def _class_of(who: str, person_dir, registry) -> str:
    rec = _people(person_dir).get(who)
    if rec is None:
        return "unknown"
    if bool(_get(rec, "internal", False)):
        return "internal"
    return external_class(who, person_dir, registry)


def peer_index(units: Iterable[Unit], evidence, person_dir, cfg, *, registry=None) -> PeerIndex:
    """단위업무별 동료와 관계(R §4.5 peers_of). evidence 가 없으면 시간 코어 관계를 그대로(미확인)."""
    min_msgs = int(cfg["report.peers.minMsgs"])
    max_meet = int(cfg["report.peers.maxMeetingSize"])
    people = _people(person_dir)
    self_keys = frozenset(k for k, v in people.items() if bool(_get(v, "self", False)))
    ev = _Ev(evidence) if evidence is not None else None
    idx = PeerIndex(verified=ev is not None, self_keys=self_keys)
    for u in sorted(units, key=lambda x: x.unit_id):
        base: dict[str, set] = defaultdict(set)
        for who, rel in u.peers:
            if who and who not in self_keys and rel in RELS:
                base[who].add(rel)
        out: dict[str, frozenset] = {}
        for who in sorted(base):
            rels = base[who]
            keep = set()
            for r in ("requester", "reporter"):
                if r in rels:
                    keep.add(r)
                    idx.weight[(u.unit_id, who, r)] = 1
            if "thread" in rels:
                if ev is None or not u.conv:              # 대화 키가 없으면 확인할 수 없다 — 시간 코어 관계 그대로
                    keep.add("thread")
                    idx.weight[(u.unit_id, who, "thread")] = 1
                else:
                    n = ev.thread.get((u.conv, who), 0)
                    if n >= min_msgs:
                        keep.add("thread")
                        idx.weight[(u.unit_id, who, "thread")] = n
            if "meeting" in rels:
                if ev is None:
                    keep.add("meeting")
                    idx.weight[(u.unit_id, who, "meeting")] = 1
                else:
                    ok = [m for m in u.meetings if m in ev.meet and who in ev.meet[m][0] and ev.meet[m][1] <= max_meet]
                    if ok:
                        keep.add("meeting")
                        idx.weight[(u.unit_id, who, "meeting")] = len(ok)
            if keep:
                out[who] = frozenset(keep)
                if who not in idx.cls:
                    idx.cls[who] = _class_of(who, person_dir, registry)
        idx.by_unit[u.unit_id] = out
    return idx


def peers_section(idx: PeerIndex, units: Mapping[str, Unit], cfg, *, as_of_min: int, unit_ids=None) -> dict:
    """모델 `peers` 절(R §9.2.1): internal(사내·미확인 개인, 상위 topN) · others(나머지 요약) · external(계급별 사람 수) ·
    unresolved(사람 사전에 없는 사람 수 — 팀 묶음 `peer_unresolved:<수>`). unit_ids 를 주면 그 단위업무만으로 계산."""
    top_n = int(cfg["report.peers.topN"])
    sel = set(units) if unit_ids is None else set(unit_ids)
    agg: dict[str, dict] = {}
    for uid in sorted(sel):
        u = units.get(uid)
        if u is None:
            continue
        for who, rels in sorted(idx.by_unit.get(uid, {}).items()):
            a = agg.setdefault(who, {"units": set(), "effort": 0, "roles": Counter(), "proj": Counter(),
                                     "first": None, "last": None})
            a["units"].add(uid)
            a["effort"] += u.effort_min
            for r in rels:
                a["roles"][r] += 1
            a["proj"][u.project_key] += u.effort_min
            d0 = u.start_date
            d1 = u.end_date or lmin_date(max(as_of_min, u.start or 0))
            if d0 is not None:
                a["first"] = d0 if a["first"] is None else min(a["first"], d0)
                a["last"] = d1 if a["last"] is None else max(a["last"], d1)
    rows, ext = [], Counter()
    for who, a in agg.items():
        cls = idx.cls.get(who, "unknown")
        if cls in EXT_CLASSES:
            ext[cls] += 1
            continue
        rows.append({"key": who, "internal": True if cls == "internal" else None, "units": len(a["units"]),
                     "unit_ids": sorted(a["units"]), "shared_effort_min": int(a["effort"]),
                     "roles": {r: int(a["roles"].get(r, 0)) for r in RELS},
                     "projects": [k for k, _v in sorted(a["proj"].items(), key=lambda kv: (-kv[1], kv[0]))][:3],
                     "first": a["first"].isoformat() if a["first"] else None,
                     "last": a["last"].isoformat() if a["last"] else None})
    rows.sort(key=lambda r: (-r["shared_effort_min"], -r["units"], r["key"]))
    for i, r in enumerate(rows):
        r["k"] = i + 1
    shown, rest = rows[:top_n], rows[top_n:]
    out = {"internal": shown,
           "others": {"n": len(rest), "units": len({x for r in rest for x in r["unit_ids"]}),
                      "shared_effort_min": sum(r["shared_effort_min"] for r in rest)},
           "external": {c: int(ext.get(c, 0)) for c in EXT_CLASSES},
           "unresolved": sum(1 for r in rows if r["internal"] is None),
           "verified": idx.verified}
    if not idx.verified and agg:
        out["warnings"] = [V.warn("peers_unverified")]
    return out


def peers_layer(units, evidence, person_dir, cfg, *, registry=None, as_of_min: int = 0) -> dict:
    """R 부록 A `peers_layer(tasks, evidence, person_dir, cfg)` — units = {unit_id: Unit} 또는 Unit 목록."""
    um = units if isinstance(units, Mapping) else {u.unit_id: u for u in units}
    idx = peer_index(um.values(), evidence, person_dir, cfg, registry=registry)
    return peers_section(idx, um, cfg, as_of_min=as_of_min)
