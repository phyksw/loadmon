# -*- coding: utf-8 -*-
r"""논리 PC 별칭 ``data\pc_aliases.json`` ``lm27.pcalias/1``(계약 §3.23, TAB §1.8) — 추가 전용 결정 기록.

``{"schema": "lm27.pcalias/1", "decisions": [{at, pc_id, logical, rule(auto_vdi|user_undo|manual), why?}]}``

  · 풀링 VDI·재이미징으로 MachineGuid 가 바뀌면 세션마다 새 pc_id 폴더가 생긴다. 폴더는 그대로 두고(불변) 여기에
    "같은 논리 PC" 결정만 더한다. 같은 pc_id 는 마지막 결정(at 순)이 이긴다. ``user_undo`` 는 logical = 자기 pc_id.
  · 논리 PC 는 표시·PC 단위 품질 집계에만 쓴다(시간 봉투는 원래 모든 PC 합집합이라 별칭과 무관 — 오판이 MM 을 바꾸지 않음).
  · ``auto_alias``: kind ∈ vdi·cloud 인 새 PC 를, 먼저 나타난(first_seen 이 이른) 같은 kind·host_class·시간대이고
    pc_session 구간이 ``bundle.overlapToleranceMin`` 넘게 겹치지 않는 PC 들의 논리 PC 가 **정확히 하나**일 때만 묶는다.
    결정이 이미 있는 pc_id(사람이 되돌린 것 포함)는 다시 판단하지 않는다.
  · 이 모듈은 ``data\pcs`` 를 직접 읽지 않는다 — PC 목록은 ``pcreg``, 세그먼트 구간은 ``loader`` 로 얻는다(L-08).
  · 쓰기는 번들 잠금을 쥔 채로(호출자 책임).
"""
import re
from datetime import UTC, datetime, timedelta

from lm27.util import fsx

SCHEMA = "lm27.pcalias/1"
RULES = ("auto_vdi", "user_undo", "manual")
_PC_RX = re.compile(r"^pcx?_[0-9a-f]{16}$")
_LOGICAL_RX = re.compile(r"^[^\\/:*?\"<>|\x00-\x1f\x7f]{1,40}$")
_UTC_RX = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def load_aliases(paths) -> dict:
    obj = fsx.read_json(paths.pc_aliases(), None, want=dict)
    if not obj or not isinstance(obj.get("decisions"), list):
        return {"schema": SCHEMA, "decisions": []}
    decs = [d for d in obj["decisions"] if isinstance(d, dict) and isinstance(d.get("pc_id"), str)
            and isinstance(d.get("logical"), str) and d.get("rule") in RULES]
    return {"schema": SCHEMA, "decisions": decs}


def save_aliases(paths, obj: dict) -> bool:
    """정렬(at·pc_id) 후 원자 쓰기. 같은 바이트면 쓰지 않는다."""
    decs = sorted(obj.get("decisions") or [], key=lambda d: (str(d.get("at") or ""), d.get("pc_id", "")))
    data = fsx.canon_bytes({"schema": SCHEMA, "decisions": decs})
    p = paths.pc_aliases()
    try:
        if fsx.read_bytes(p) == data:
            return False
    except FileNotFoundError:
        pass
    fsx.atomic_write(p, data)
    return True


def _last_decisions(decisions) -> dict:
    """pc_id → 마지막 결정(at 순, 같은 at 이면 기록 순)."""
    out = {}
    for _i, d in sorted(enumerate(decisions), key=lambda x: (str(x[1].get("at") or ""), x[0])):
        out[d["pc_id"]] = d
    return out


def logical_map(paths) -> dict:
    """pc_id → 논리 PC(사슬 a→b→c 는 c 로, 순환은 끊는다). 결정이 없는 pc_id 는 들어 있지 않다."""
    last = _last_decisions(load_aliases(paths)["decisions"])
    direct = {pid: d["logical"] for pid, d in last.items()}
    out = {}
    for pid in direct:
        cur, seen = pid, {pid}
        while cur in direct and direct[cur] != cur:
            nxt = direct[cur]
            if nxt in seen:
                break
            seen.add(nxt)
            cur = nxt
        out[pid] = cur
    return out


def logical_of(pc_id: str, amap: dict) -> str:
    return amap.get(pc_id, pc_id)


def _check_pc(pc_id):
    if not isinstance(pc_id, str) or not _PC_RX.match(pc_id):
        raise ValueError("pc_id 형식이 아닙니다")


def record_alias(paths, pc_id, logical, rule="manual", *, why=None, at=None) -> dict:
    """결정 한 줄을 더한다. logical = 다른 pc_id 또는 사람이 붙인 이름(≤40자, 경로 문자·제어문자 없음).
    반환 ``{rc, decision}`` — 이미 같은 논리 PC 면 rc 4(쓰지 않음)."""
    _check_pc(pc_id)
    if rule not in RULES:
        raise ValueError("rule 은 auto_vdi·user_undo·manual")
    if not isinstance(logical, str) or not _LOGICAL_RX.match(logical) or logical != logical.strip():
        raise ValueError("논리 PC 이름 형식이 아닙니다")
    obj = load_aliases(paths)
    amap = logical_map(paths)
    target = amap.get(logical, logical) if _PC_RX.match(logical) and logical != pc_id else logical
    if target == pc_id and rule != "user_undo":
        raise ValueError("자기 자신을 가리키는 별칭은 되돌리기(undo_alias)로 하세요")
    if amap.get(pc_id, pc_id) == target and (pc_id in amap or target == pc_id):
        return {"rc": 4, "decision": None}
    dec = {"at": at or fsx.utcnow_iso(), "pc_id": pc_id, "logical": logical, "rule": rule}
    if why:
        dec["why"] = why
    obj["decisions"].append(dec)
    save_aliases(paths, obj)
    return {"rc": 0, "decision": dec}


def undo_alias(paths, pc_id, *, at=None) -> dict:
    """별칭을 되돌린다(logical = 자기 pc_id, rule=user_undo). 별칭이 없으면 rc 4."""
    _check_pc(pc_id)
    amap = logical_map(paths)
    if amap.get(pc_id, pc_id) == pc_id:
        return {"rc": 4, "decision": None}
    return record_alias(paths, pc_id, pc_id, rule="user_undo", at=at)


def _utc(ts):
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def samples_overlap(spans_a, spans_b, tol_min: int) -> bool:
    """두 PC 의 pc_session 구간 목록이 tol_min 분 넘게 겹치면 True(동시에 쓰인 서로 다른 기계)."""
    tol = timedelta(minutes=tol_min)
    for a0, a1 in spans_a:
        for b0, b1 in spans_b:
            if min(_utc(a1), _utc(b1)) - max(_utc(a0), _utc(b0)) > tol:
                return True
    return False


def auto_alias(paths, cfg, *, now=None, spans=None) -> list:
    """VDI·클라우드 자동 별칭(TAB §1.8). 반환: 새로 더한 결정 목록. ``spans`` = {pc_id: [(t0, t1)]} 주입(시험)."""
    if not cfg["bundle.autoAliasVdi"]:
        return []
    tol = int(cfg["bundle.overlapToleranceMin"])
    from lm27.bundle import loader, pcreg
    pcs = [p for p in pcreg.load_all_pcs(paths) if isinstance(p.get("first_seen"), str)]
    sp = spans if spans is not None else {p["pc_id"]: loader.session_spans(paths, p["pc_id"]) for p in pcs}
    decided = set(_last_decisions(load_aliases(paths)["decisions"]))
    amap = logical_map(paths)
    made = []
    order = sorted(pcs, key=lambda p: (p["first_seen"], p["pc_id"]))
    for idx, new in enumerate(order):
        if new["pc_id"] in decided or new.get("kind") not in ("vdi", "cloud"):
            continue
        hc = new.get("host_class") or ""
        if not hc:
            continue                                # host_class 를 모르면 판단하지 않는다
        off = (new.get("tz") or {}).get("utc_offset_min")
        cands = [old for old in order[:idx]
                 if old.get("kind") == new.get("kind") and (old.get("host_class") or "") == hc
                 and (old.get("tz") or {}).get("utc_offset_min") == off
                 and not samples_overlap(sp.get(old["pc_id"], ()), sp.get(new["pc_id"], ()), tol)]
        logicals = {logical_of(c["pc_id"], amap) for c in cands}
        if len(logicals) != 1:
            continue
        target = next(iter(logicals))
        res = record_alias(paths, new["pc_id"], target, rule="auto_vdi", at=now,
                           why={"kind": new.get("kind"), "host_class": hc, "tz": off})
        if res.get("decision"):
            made.append(res["decision"])
            decided.add(new["pc_id"])
            amap = logical_map(paths)
    return made
