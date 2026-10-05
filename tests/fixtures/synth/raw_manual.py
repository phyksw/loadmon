# -*- coding: utf-8 -*-
"""kind=manual 원시 레코드(P §10.2 manual 원시 이름 + 계약 §3.2 man_kind·ref_keys·retract_of) — 수동 기록 입력 모양.
시각이 없으면 date 만(정제기가 그날 00:00+오프셋 · ts_precision=date 로 만든다). 시험 입력용이며 디스크에 쓰지 않는다."""
from __future__ import annotations

from collections.abc import Iterable

from .month import ManualEv, Plan, at_local, fmt_offset, plant_text, plantable, utc_iso

SRCS = ("manual",)
FIELDS = frozenset({
    "category", "hours", "date", "start", "end", "note", "entity", "project_id", "role_field", "role_func",
    "man_kind", "ref_keys", "retract_of", "ts_local_offset", "observed_at", "confidence",
})


def _hhmm(minute: int | None) -> str | None:
    return None if minute is None else f"{minute // 60:02d}:{minute % 60:02d}"


def _one(ev: ManualEv, plan: Plan) -> dict:
    P = plan.persona
    return {
        "category": ev.category,
        "hours": ev.hours,
        "date": ev.day.isoformat(),
        "start": _hhmm(ev.start_min),
        "end": _hhmm(ev.end_min),
        "note": P.render(ev.note)[0],
        "entity": P.render(ev.entity)[0] if ev.entity else "",
        "project_id": ev.project_id,
        "role_field": ev.role_field,
        "role_func": ev.role_func,
        "man_kind": ev.man_kind,
        "ref_keys": [],
        "retract_of": None,
        "ts_local_offset": fmt_offset(ev.off),
        "observed_at": utc_iso(at_local(ev.day, 18 * 60, ev.off)),
        "confidence": 1.0,
    }


def records(plan: Plan, *, src: str = "manual", canaries: Iterable | None = None) -> list[dict]:
    """계획의 수동 기록 → 원시 레코드 목록. canaries 는 note(문장)·entity(이름)에 심는다."""
    if src != "manual":
        raise ValueError(f"manual 경로 아님: {src}")
    out = [_one(ev, plan) for ev in plan.manuals]
    if canaries and out:
        plant_text(out, canaries, "note", sep=" / ")
        for i, c in enumerate(plantable(canaries, "name")):
            out[(1 + i) % len(out)]["entity"] = c.value
    return out
