# -*- coding: utf-8 -*-
"""kind=cal 원시 레코드(P §10.2 cal 원시 이름 · 계약 §3.5 start_utc·end_utc·busy_status·response_status·location·online·
is_recurring) — 정제 전 메모리 모양. 시험 입력용이며 디스크에 쓰지 않는다.

src 별 차이: cal.com·cal.import = 참석자 주소·본문 포함 · cal.index = 본문 없음 · cal.owa = 이름만 ·
cal.copilot = 근무일별 요약 증인(copilot_text, date).
"""
from __future__ import annotations

import hashlib
from collections.abc import Iterable
from datetime import timedelta

from .month import MeetEv, Plan, at_local, daily_witness, fmt_offset, plant_text, plantable, utc_iso

SRCS = ("cal.com", "cal.index", "cal.owa", "cal.import", "cal.copilot")
FIELDS = frozenset({
    "global_appointment_id", "start_utc", "end_utc", "subject", "organizer", "attendees", "busy_status",
    "response_status", "meeting_status", "location", "is_recurring", "all_day", "online", "recurrence_incomplete",
    "sensitivity", "categories", "body_text", "copilot_text",
    "ts_local_offset", "ts_precision", "observed_at", "confidence", "flags",
})


def appointment_id(ev: MeetEv, plan: Plan) -> str:
    """합성 GlobalAppointmentID(반복 시리즈는 회차가 같은 ID — 키 재료는 'ID|시작 UTC')."""
    return hashlib.sha1(f"{plan.seed}/{ev.series or ev.eid}".encode()).hexdigest().upper()


def _one(ev: MeetEv, plan: Plan, src: str) -> dict:
    P = plan.persona
    org = P.person(ev.organizer)
    atts = [P.person(x) for x in ev.attendees]
    names_only = src == "cal.owa"
    rec = {
        "global_appointment_id": appointment_id(ev, plan),
        "start_utc": utc_iso(ev.start),
        "end_utc": utc_iso(ev.end),
        "subject": P.render(ev.subject)[0],
        "organizer": {"addr": None if names_only else org.addr, "name": org.name},
        "attendees": [{"addr": None if names_only else p.addr, "name": p.name} for p in atts],
        "busy_status": ev.busy,
        "response_status": ev.response,
        "meeting_status": 1,
        "location": P.render(ev.place)[0],
        "is_recurring": ev.series is not None,
        "all_day": False,
        "online": ev.location == "online",
        "recurrence_incomplete": False,
        "sensitivity": 0,
        "categories": [],
        "body_text": P.render(ev.body)[0],
        "ts_local_offset": fmt_offset(ev.off),
        "ts_precision": "minute",
        "observed_at": utc_iso(ev.start - timedelta(days=1)),
        "confidence": 1.0,
    }
    if src in ("cal.index", "cal.owa"):
        rec.pop("body_text")
    if src in ("cal.owa", "cal.import"):
        rec["observed_at"] = utc_iso(plan.as_of)
        rec["confidence"] = 0.8 if src == "cal.owa" else 1.0
    return rec


def _witness(plan: Plan) -> list[dict]:
    P = plan.persona
    out = []
    for d, parts in daily_witness(plan, "cal"):
        t0 = at_local(d, 0, P.offset_min)
        out.append({"copilot_text": P.render(parts)[0], "start_utc": utc_iso(t0),
                    "end_utc": utc_iso(t0 + timedelta(days=1)), "ts_local_offset": fmt_offset(P.offset_min),
                    "ts_precision": "date", "observed_at": utc_iso(plan.as_of), "confidence": 0.3})
    return out


def records(plan: Plan, *, src: str = "cal.com", canaries: Iterable | None = None) -> list[dict]:
    """계획의 회의 사건 → 원시 레코드 목록(계획 순서). canaries 를 주면 원문 필드에 심는다."""
    if src not in SRCS:
        raise ValueError(f"cal 경로 아님: {src}")
    if src == "cal.copilot":
        out = _witness(plan)
        plant_text(out, canaries, "copilot_text")
        return out
    out = [_one(ev, plan, src) for ev in plan.meets]
    if canaries and out:
        plant_text(out, canaries, "body_text" if src in ("cal.com", "cal.import") else "subject",
                   sep="\n" if src in ("cal.com", "cal.import") else " / ")
        n = len(out)
        for i, c in enumerate(plantable(canaries, "name")):
            out[(1 + i * 3) % n]["organizer"] = {**out[(1 + i * 3) % n]["organizer"], "name": c.value}
        for i, c in enumerate(plantable(canaries, "addr")):
            rec = out[(2 + i * 3) % n]
            rec["attendees"] = [*rec["attendees"], {"addr": c.value, "name": "외부 참석자"}]
    return out
