# -*- coding: utf-8 -*-
"""kind=teams 원시 레코드(P §10.2 teams 원시 이름 · 계약 §3.5: chat_id·reply_to_id·author_addr·is_me·chat_title) —
정제 전 메모리 모양. 시험 입력용이며 디스크에 쓰지 않는다.

src 별 차이: teams.uia = 메시지 ID·주소 없음, UIA 합성 방 ID, 분 단위 · teams.web = data-mid·<time datetime>(exact)·
작성자 주소·참여자 · teams.copilot = 근무일별 요약 증인(copilot_text, date).
"""
from __future__ import annotations

from collections.abc import Iterable
from datetime import timedelta

from .month import ChatEv, Plan, Room, at_local, daily_witness, fmt_offset, plant_text, plantable, utc_iso

SRCS = ("teams.uia", "teams.web", "teams.copilot")
FIELDS = frozenset({
    "message_id", "chat_id", "chat_type", "n_participants", "reply_to_id", "author_addr", "author_name", "is_me",
    "participants", "mentions_me", "file_names", "body_text", "chat_title", "copilot_text",
    "ts_utc", "ts_local_offset", "ts_precision", "observed_at", "confidence", "flags",
})


def room_title(room: Room, plan: Plan) -> str:
    """방 이름 원문 — 1:1 은 상대 이름(그래서 저장하지 않는다, P §10.2)."""
    P = plan.persona
    if room.title:
        return P.render(room.title)[0]
    other = [m for m in room.members if m != "self"]
    return P.person(other[0]).name if other else P.me.name


def _one(ev: ChatEv, plan: Plan, src: str) -> dict:
    P = plan.persona
    room = ev.room
    author = P.person(ev.author)
    web = src == "teams.web"
    return {
        "message_id": ev.mid if web else None,
        "chat_id": room.raw_id if web else room.uia_id,
        "chat_type": room.chat_type,
        "n_participants": len(room.members),
        "reply_to_id": ev.reply_to if web else None,
        "author_addr": author.addr if web else None,
        "author_name": author.name,
        "is_me": author.is_self,
        "participants": [{"name": P.person(m).name, "smtp": P.person(m).addr} for m in room.members] if web else [],
        "mentions_me": ev.mentions_me,
        "file_names": list(ev.files),
        "body_text": P.render(ev.body)[0],
        "chat_title": room_title(room, plan),
        "ts_utc": utc_iso(ev.utc if web else ev.utc.replace(second=0)),
        "ts_local_offset": fmt_offset(ev.off),
        "ts_precision": "exact" if web else "minute",
        "observed_at": utc_iso(plan.as_of if web else ev.utc + timedelta(minutes=5)),
        "confidence": 1.0 if web else 0.8,
    }


def _witness(plan: Plan) -> list[dict]:
    P = plan.persona
    return [{"copilot_text": P.render(parts)[0], "ts_utc": utc_iso(at_local(d, 0, P.offset_min)),
             "ts_local_offset": fmt_offset(P.offset_min), "ts_precision": "date", "observed_at": utc_iso(plan.as_of),
             "confidence": 0.3} for d, parts in daily_witness(plan, "teams")]


def records(plan: Plan, *, src: str = "teams.uia", canaries: Iterable | None = None) -> list[dict]:
    """계획의 팀즈 메시지 → 원시 레코드 목록(계획 순서). canaries 를 주면 원문 필드에 심는다."""
    if src not in SRCS:
        raise ValueError(f"teams 경로 아님: {src}")
    if src == "teams.copilot":
        out = _witness(plan)
        plant_text(out, canaries, "copilot_text")
        return out
    out = [_one(ev, plan, src) for ev in plan.chats]
    if canaries and out:
        plant_text(out, canaries, "body_text", sep="\n")
        n = len(out)
        for i, c in enumerate(plantable(canaries, "file")):
            rec = out[(3 + i * 5) % n]
            rec["file_names"] = [*rec["file_names"], c.sentence]
        others = [r for r in out if not r["is_me"]] or out
        for i, c in enumerate(plantable(canaries, "name")):
            others[(1 + i * 5) % len(others)]["author_name"] = c.value
        if src == "teams.web":
            for i, c in enumerate(plantable(canaries, "addr")):
                others[(2 + i * 5) % len(others)]["author_addr"] = c.value
    return out
