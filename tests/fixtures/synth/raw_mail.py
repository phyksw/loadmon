# -*- coding: utf-8 -*-
"""kind=mail 원시 레코드(P §10.2 mail 원시 이름 · 계약 §3.5) — 정제 전 메모리 모양. 시험 입력용이며 디스크에 쓰지 않는다.

src 별 차이(수집 경로 모양): mail.com·mail.import = 헤더·본문 포함(분 단위) · mail.index = 본문·헤더 없음 ·
mail.owa = 이름만(주소 없음), 분석 시각 전전날 이전은 날짜만(date) · mail.copilot = 근무일별 요약 증인(copilot_text, date).
"""
from __future__ import annotations

import hashlib
from collections.abc import Iterable
from datetime import timedelta

from .month import (MailEv, Plan, at_local, daily_witness, fmt_offset, local_midnight, plant_text, plantable, to_local,
                    utc_iso)

SRCS = ("mail.com", "mail.index", "mail.owa", "mail.import", "mail.copilot")
FIELDS = frozenset({
    "internet_message_id", "conversation_id", "conversation_topic", "box", "folder_role", "sender_addr",
    "sender_name", "to", "cc", "subject", "attach_names", "sensitivity", "categories", "importance", "has_attach",
    "in_reply_to", "headers_text", "body_text", "focused_other", "copilot_text",
    "ts_utc", "ts_local_offset", "ts_precision", "observed_at", "confidence", "flags",
})


def message_id(ev: MailEv, plan: Plan) -> str:
    """합성 Message-ID(example 도메인)."""
    return f"<{ev.eid}.s{plan.seed}@{plan.persona.internal_domains[0]}>"


def conversation_id(thread: str) -> str:
    """합성 대화 ID(16진 대문자 — Outlook ConversationID 모양)."""
    return hashlib.sha1(thread.encode("utf-8")).hexdigest().upper()


def _one(ev: MailEv, plan: Plan, src: str) -> dict:
    P = plan.persona
    sender = P.person(ev.sender)
    to = [P.person(x) for x in ev.to]
    cc = [P.person(x) for x in ev.cc]
    subj = P.render(ev.subject)[0]
    body = P.render(ev.body)[0]
    rec = {
        "internet_message_id": message_id(ev, plan),
        "conversation_id": conversation_id(ev.thread),
        "conversation_topic": subj[4:] if subj.startswith("RE: ") else subj,
        "box": ev.box,
        "folder_role": ev.folder_role,
        "sender_addr": sender.addr,
        "sender_name": sender.name,
        "to": [{"addr": p.addr, "name": p.name} for p in to],
        "cc": [{"addr": p.addr, "name": p.name} for p in cc],
        "subject": subj,
        "attach_names": list(ev.attach),
        "sensitivity": 0,
        "categories": [],
        "importance": ev.importance,
        "has_attach": bool(ev.attach),
        "in_reply_to": f"<{conversation_id(ev.thread)[:12].lower()}.s{plan.seed}@{P.internal_domains[0]}>"
        if ev.reply else None,
        "headers_text": "",
        "body_text": body,
        "focused_other": False,
        "ts_utc": utc_iso(ev.utc),
        "ts_local_offset": fmt_offset(ev.off),
        "ts_precision": "minute",
        "observed_at": utc_iso(ev.utc + timedelta(minutes=15)),
        "confidence": 1.0,
    }
    if src in ("mail.index", "mail.owa"):
        for k in ("body_text", "headers_text", "in_reply_to", "focused_other"):
            rec.pop(k)
    if src == "mail.owa":
        rec["sender_addr"] = None
        rec["to"] = [{"addr": None, "name": p.name} for p in to]
        rec["cc"] = [{"addr": None, "name": p.name} for p in cc]
        rec["observed_at"] = utc_iso(plan.as_of)
        asof_day = to_local(plan.as_of, P.offset_min).date()
        if to_local(ev.utc, ev.off).date() < asof_day - timedelta(days=1):
            rec.update(ts_utc=utc_iso(local_midnight(ev.utc, ev.off)), ts_precision="date", confidence=0.4)
        else:
            rec["confidence"] = 0.8
    if src == "mail.import":
        rec["observed_at"] = utc_iso(plan.as_of)
    return rec


def _witness(plan: Plan) -> list[dict]:
    P = plan.persona
    out = []
    for d, parts in daily_witness(plan, "mail"):
        t0 = at_local(d, 0, P.offset_min)
        out.append({"copilot_text": P.render(parts)[0], "ts_utc": utc_iso(t0), "ts_local_offset": fmt_offset(P.offset_min),
                    "ts_precision": "date", "observed_at": utc_iso(plan.as_of), "confidence": 0.3})
    return out


def records(plan: Plan, *, src: str = "mail.com", canaries: Iterable | None = None) -> list[dict]:
    """계획의 메일 사건 → 원시 레코드 목록(계획 순서). canaries 를 주면 원문 필드에 심는다."""
    if src not in SRCS:
        raise ValueError(f"mail 경로 아님: {src}")
    if src == "mail.copilot":
        out = _witness(plan)
        plant_text(out, canaries, "copilot_text")
        return out
    out = [_one(ev, plan, src) for ev in plan.mails]
    if canaries and out:
        plant_text(out, canaries, "body_text" if src in ("mail.com", "mail.import") else "subject",
                   sep="\n" if src in ("mail.com", "mail.import") else " / ")
        n = len(out)
        for i, c in enumerate(plantable(canaries, "file")):
            rec = out[(3 + i * 5) % n]
            rec["attach_names"] = [*rec["attach_names"], c.sentence]
            rec["has_attach"] = True
        inbound = [r for r in out if r["box"] == "inbox"] or out
        for i, c in enumerate(plantable(canaries, "name")):
            inbound[(1 + i * 5) % len(inbound)]["sender_name"] = c.value
        for i, c in enumerate(plantable(canaries, "addr")):
            rec = out[(2 + i * 5) % n]
            rec["cc"] = [*rec["cc"], {"addr": c.value, "name": "외부 담당"}]
    return out
