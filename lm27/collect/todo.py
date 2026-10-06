# -*- coding: utf-8 -*-
r"""빈칸 계획기(파생) — ``data\derived\todo.json`` · 백필 빈칸 파일 ``blanks_<src>.json``(계약 §3.12 · §6.4 · §7.3 ·
X-014 · X-126 · X-315, C §6 · CM §2 · CT §11 · B §8.1 · D-6 · D-7).

원장의 일자 합성(``lm27.collect.ledger.composite``)이 미관측(not_attempted·blocked·transport_fail·out_of_horizon)인 날을
'다음에 가능한 출처·PC' 작업으로 묶는다. 사람에게 조작을 요구하지 않는다 — 다음 [수집]·다음 PC 가 자동으로 집어 간다.

  · 축 → 출처 사슬(싼 것 먼저, 빈칸만 비싼 것으로 — D-6 · D-14): 메일 = ``mail.owa``(백필 PC) → ``mail.copilot``(클라우드PC
    증인), 일정 = ``cal.owa`` → ``cal.copilot``(``bridge.stages.lookup_calendar`` 가 켜졌을 때만), 팀즈 = ``teams.web`` →
    ``teams.copilot``. PC 축은 그 PC 에서만 읽을 수 있어 배정할 곳이 없다(작업 없음).
  · 배정 PC: 백필 출처는 ``collect.backfillPc``(기본 클라우드PC), 코파일럿은 클라우드PC. 그 PC 가 번들에 아직 없으면
    ``want_pc = "cloud"`` + ``open``(배정 대기).
  · '그래도 비면 다음'(C §6.1): 그 날을 사슬의 앞 출처가 이미 시도했는데도(원장에 그 출처 셀이 있음) 비었으면 다음 출처로
    — OWA 가 읽었는데도 빈 날만 코파일럿 증인으로 간다. 쓸 수 있는 출처가 모두 시도했으면 첫 출처로 다시(일시 실패 재시도).
  · '불가' 반영(계약 §6.4 — 판정은 ``lm27.bundle.pcreg.verdict`` 하나): 배정 PC 에서 그 출처(또는 OWA·팀즈 웹이면 Edge
    원격 디버깅 정책 ``edge_cdp_policy``)가 ``불가(확정)`` 이면 사슬의 다음 출처로 넘어간다. 사슬이 모두 막혔으면
    ``blocked_confirmed``. 지난 todo 에서 ``blocked_confirmed`` 였던 작업이 다시 시도 대상이 되면(탐침 값 변화·TTL 만료·
    ok 관측) 한 번 ``released`` 로 알린다. 영속 이력은 pc.json 에 있으므로 todo 는 매번 다시 만든다(X-014).
  · 메일 수신·발신 축은 같은 OWA 실행이 두 폴더를 함께 읽으므로 날짜마다 한 작업으로 묶는다(``kind_axis`` = 그 날 빈 축이
    발신뿐이면 ``mail_out``, 아니면 ``mail_in``). ``todo_id`` = ``<want_src>:<from>:<to>``(결정적), 구간은 로컬 달 안에서 잇는다.
  · 빈칸 파일(X-315): ``write_blanks`` 가 그 실행 폴더에 ``[{todo_id, date_range:[from, to], kind_axis}]`` 를 쓴다 —
    ``Get-OutlookWeb.py --blanks-file`` · 코파일럿 조회 어댑터의 입력. 원문 0.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta

from lm27.collect import ledger, plan, rcmap
from lm27.util import fsx

__all__ = ["CHAIN", "SCHEMA", "STATES", "WANT_CLOUD", "Todo", "blanks_for", "load_todo", "plan_todo", "write_blanks"]

SCHEMA = "lm27.todo/1"
STATES = ("open", "assigned", "blocked_confirmed", "released")
LIVE_STATES = ("open", "assigned", "released")
CHAIN = {"mail": ("mail.owa", "mail.copilot"), "cal": ("cal.owa", "cal.copilot"), "teams": ("teams.web", "teams.copilot")}
AXIS_GROUP = {"mail_in": "mail", "mail_out": "mail", "cal": "cal", "teams": "teams"}
EDGE_SRCS = frozenset({"mail.owa", "cal.owa", "teams.web"})
WANT_CLOUD = "cloud"
ATTEMPTS_MAX = 10
CONFIRMED = "불가(확정)"


@dataclass
class Todo:
    """작업 하나(계약 §3.12)."""
    todo_id: str
    account: str
    date_range: list
    kind_axis: str
    want_src: str
    want_pc: str
    reasons: list = field(default_factory=list)
    attempts: list = field(default_factory=list)
    state: str = "open"
    updated: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _utc_iso(now=None) -> str:
    u = now if isinstance(now, datetime) else datetime.now(UTC)
    if u.tzinfo is None:
        u = u.replace(tzinfo=UTC)
    return u.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_todo(paths) -> list:
    """지난 todo.json 의 작업 목록(없거나 깨졌으면 빈 목록)."""
    obj = fsx.read_json(paths.todo(), None, want=dict)
    if not obj or obj.get("schema") != SCHEMA or not isinstance(obj.get("todos"), list):
        return []
    return [t for t in obj["todos"] if isinstance(t, dict) and isinstance(t.get("todo_id"), str)]


def _copilot_pc(pcs) -> str | None:
    rows = sorted((p for p in pcs or () if isinstance(p, dict) and p.get("kind") == "cloud" and p.get("pc_id")),
                  key=lambda p: (str(p.get("first_seen") or ""), p["pc_id"]))
    return rows[0]["pc_id"] if rows else None


def _cap(pcs_by_id, pc_id, key) -> dict:
    pc = pcs_by_id.get(pc_id) or {}
    caps = pc.get("capabilities") if isinstance(pc.get("capabilities"), dict) else {}
    ent = caps.get(key)
    return ent if isinstance(ent, dict) else {}


def _verdict(pcs_by_id, pc_id, key, cfg, today) -> tuple:
    """(verdict, 사유) — pc.json 이력을 오늘 기준으로 다시 판정(TTL 경과 반영 — 계약 §6.4 유일 구현)."""
    from lm27.bundle import pcreg
    ent = _cap(pcs_by_id, pc_id, key)
    hist = ent.get("history") if isinstance(ent.get("history"), list) else []
    if not hist:
        return "미확인", []
    v = pcreg.verdict(hist, cfg, today=today)
    rs = sorted({r for h in hist[-3:] if isinstance(h, dict) for r in h.get("reasons") or () if rcmap.is_reason(r)})
    return v, rs


def _attempts(pcs_by_id, pc_id, key) -> list:
    ent = _cap(pcs_by_id, pc_id, key)
    out = []
    for h in (ent.get("history") or [])[-ATTEMPTS_MAX:]:
        if not isinstance(h, dict) or not isinstance(h.get("date"), str):
            continue
        rs = [r for r in h.get("reasons") or () if rcmap.is_reason(r)]
        out.append({"pc_id": pc_id, "date": h["date"], "result": rs[0] if rs else str(h.get("status") or "unknown")})
    return out


def _options(group, pcs_by_id, cfg, today, backfill, copilot_pc) -> tuple:
    """사슬의 쓸 수 있는 출처 ``[(src, pc, state)]``('불가(확정)' 아닌 것 — 배정 PC 가 없으면 ``open``)와 막힘 사유."""
    out, blocked_rs = [], []
    chain = [s for s in CHAIN[group] if s not in plan.COPILOT_STAGE_OF or plan.copilot_enabled(cfg, s)]
    for src in chain:
        pc = copilot_pc if src in ledger.COPILOT_SRCS else backfill
        if pc is None:
            out.append((src, WANT_CLOUD, "open"))
            continue
        v, rs = _verdict(pcs_by_id, pc, src, cfg, today)
        if v != CONFIRMED and src in EDGE_SRCS:
            ve, rse = _verdict(pcs_by_id, pc, "edge_cdp_policy", cfg, today)
            if ve == CONFIRMED:
                v, rs = ve, rse
        if v == CONFIRMED:
            blocked_rs += rs
            continue
        out.append((src, pc, "assigned"))
    first = chain[0]
    fallback = (first, (copilot_pc if first in ledger.COPILOT_SRCS else backfill) or WANT_CLOUD, "blocked_confirmed")
    return out, fallback, sorted(set(blocked_rs))


def _choose(opts, fallback, blocked_rs, tried) -> tuple:
    """(want_src, want_pc, state, 막힘 사유) — 그 날을 아직 시도하지 않은 첫 출처('그래도 비면 다음' — C §6.1). 쓸 수 있는
    출처가 모두 시도했는데도 비었으면 사슬 첫 출처로 다시(일시 실패 재시도). 모두 '불가(확정)' 이면 blocked_confirmed."""
    if not opts:
        return (*fallback, blocked_rs)
    fresh = [o for o in opts if o[0] not in tried]
    return (*(fresh or opts)[0], ())


def _blank_days(comp: dict, d0: date, d1: date) -> dict:
    """그룹(mail·cal·teams) → {날짜: (빈 축 집합, 사유 집합)} — 합성이 미관측인 날."""
    out = {g: {} for g in CHAIN}
    d = d0
    while d <= d1:
        day = d.isoformat()
        for axis, grp in AXIS_GROUP.items():
            c = comp.get((day, axis)) or {"status": "not_attempted", "reasons": []}
            if c["status"] in rcmap.UNOBSERVED:
                axes, rs = out[grp].setdefault(day, (set(), set()))
                axes.add(axis)
                rs.update(r for r in c.get("reasons") or () if rcmap.is_reason(r))
        d += timedelta(days=1)
    return out


def _runs(days: dict):
    """연속 날짜(같은 달·같은 축 집합·같은 배정)를 구간으로 → [(from, to, 축 집합, 사유 집합, 배정)]."""
    out = []
    for day in sorted(days):
        axes, rs, pick = days[day]
        if out:
            a, b, ax, r, pk = out[-1]
            nxt = (date.fromisoformat(b) + timedelta(days=1)).isoformat()
            if nxt == day and day[:7] == a[:7] and ax == axes and pk == pick:
                out[-1] = (a, day, ax, r | rs, pk)
                continue
        out.append((day, day, set(axes), set(rs), pick))
    return out


def _tried(cells) -> dict:
    """(그룹, 날짜) → 그 날을 이미 시도한 출처(셀이 not_attempted 가 아님 — 코파일럿 zero_ok 도 시도한 것)."""
    out = {}
    for c in cells:
        grp = AXIS_GROUP.get(c.get("kind_axis"))
        if grp and c.get("status") != "not_attempted":
            out.setdefault((grp, c["date"]), set()).add(c.get("src"))
    return out


def plan_todo(paths, cfg, *, now=None, cells=None, pcs=None, prev=None, write=True) -> list:
    """계약 함수: 원장 → 빈칸 작업 목록(``Todo``)을 다시 만들고(``write`` 면) ``todo.json`` 을 원자 교체한다.
    ``cells``·``pcs``·``prev``(지난 작업 목록) = 시험 주입, ``now`` = 지금(UTC aware — 창·TTL 기준)."""
    from lm27.bundle import pcreg
    cells = ledger.load_cells(paths) if cells is None else list(cells)
    pcs = pcreg.load_all_pcs(paths) if pcs is None else list(pcs)
    prev = load_todo(paths) if prev is None else list(prev)
    pcs_by_id = {p["pc_id"]: p for p in pcs if isinstance(p, dict) and isinstance(p.get("pc_id"), str)}
    d0, d1 = ledger.ledger_window(cfg, now)
    for c in cells:
        dc = date.fromisoformat(c["date"])
        d0 = min(d0, dc)
    today = d1
    backfill = plan.backfill_pc_id(pcs, cfg)
    copilot_pc = _copilot_pc(pcs)
    was_blocked = {t["todo_id"] for t in prev if t.get("state") == "blocked_confirmed"}
    stamp = _utc_iso(now)
    comp = ledger.composite(cells)
    tried = _tried(cells)
    todos = []
    for grp, days in _blank_days(comp, d0, d1).items():
        if not days:
            continue
        opts, fallback, brs = _options(grp, pcs_by_id, cfg, today, backfill, copilot_pc)
        picked = {day: (axes, rs, _choose(opts, fallback, tuple(brs), tried.get((grp, day), set())))
                  for day, (axes, rs) in days.items()}
        for a, b, axes, rs, (want_src, want_pc, state, brs2) in _runs(picked):
            tid = f"{want_src}:{a}:{b}"
            st = state
            if st != "blocked_confirmed" and tid in was_blocked:
                st = "released"
            axis = "mail_out" if axes == {"mail_out"} else ("mail_in" if grp == "mail" else grp)
            todos.append(Todo(todo_id=tid, account=ledger.ACCOUNT, date_range=[a, b], kind_axis=axis,
                              want_src=want_src, want_pc=want_pc, reasons=sorted(set(rs) | set(brs2)),
                              attempts=_attempts(pcs_by_id, want_pc, want_src) if want_pc != WANT_CLOUD else [],
                              state=st, updated=stamp))
    todos.sort(key=lambda t: (t.date_range[0], t.want_src, t.todo_id))
    if write:
        fsx.atomic_write(paths.todo(), fsx.canon_bytes({"schema": SCHEMA, "updated": stamp,
                                                         "todos": [t.to_dict() for t in todos]}) + b"\n")
    return todos


# ── 빈칸 파일(X-315) ────────────────────────────────────────────────────────
def _as_dict(t) -> dict:
    return t.to_dict() if isinstance(t, Todo) else dict(t)


def blanks_for(todos, src: str, pc_id: str | None) -> list:
    """이 PC 가 맡은 그 출처의 살아 있는 작업 → ``[{todo_id, date_range, kind_axis}]``(날짜 순)."""
    out = []
    for t in todos or ():
        d = _as_dict(t)
        if d.get("want_src") != src or d.get("state") not in LIVE_STATES:
            continue
        if pc_id is not None and d.get("want_pc") != pc_id:
            continue
        out.append({"todo_id": d["todo_id"], "date_range": list(d["date_range"]), "kind_axis": d["kind_axis"]})
    return sorted(out, key=lambda x: (x["date_range"][0], x["todo_id"]))


def write_blanks(paths, run_id: str, src: str, todos, *, pc_id: str | None = None):
    """그 실행 폴더에 ``blanks_<src>.json`` 을 쓰고 경로를 돌려준다(작업이 없으면 쓰지 않고 None)."""
    rows = blanks_for(todos, src, pc_id)
    if not rows:
        return None
    p = paths.blanks_file(run_id, src)
    fsx.atomic_write(p, fsx.canon_bytes(rows) + b"\n")
    return p
