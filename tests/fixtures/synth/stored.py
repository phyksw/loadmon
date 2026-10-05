# -*- coding: utf-8 -*-
"""정제 후 저장 행 모양(WP-05) — P §10.1·§10.2 + 계약 §3.1~§3.4 열. 봉인(SanitizedRow) 없는 dict 라서 하류 WP 의
가짜 입력이다(iter_records·load_evidence·시간 코어·번들·분류 시험). 정제기를 흉내 내지 않는다 — 같은 계획의 사건을
'정제가 끝난 모양'으로 바로 그린다(텍스트는 자리표시자 토큰, 키는 SynthKeys HMAC).

    rows = stored_rows()                                         # 2026-09 한 달 · kind 8종 · 기본 경로
    rows = stored_rows(kinds=("mail",), srcs={"mail": ("mail.com", "mail.index")})   # 병합 시험용 이중 경로
    rows = stored_rows(plan_month(2026, 10, multi_pc=True))
행 순서는 (ts_utc, id). 같은 인자 → 같은 행(바이트).
"""
from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Mapping
from datetime import date, timedelta

from .month import (Plan, at_local, daily_witness, fmt_offset, local_midnight, plan_period, to_local, utc_iso)
from .persona import RULES_VER, Persona, SynthKeys, norm_person, synth_keys
from .raw_cal import appointment_id
from .raw_mail import conversation_id, message_id
from .raw_pc import OFFICE_EXTS, full_path

KINDS = ("mail", "cal", "teams", "pc_session", "pc_file", "pc_git", "pc_compute", "manual")
SRCS_BY_KIND: dict[str, tuple[str, ...]] = {   # 계약 §6.5 경로 ID 21종
    "mail": ("mail.com", "mail.index", "mail.owa", "mail.import", "mail.copilot"),
    "cal": ("cal.com", "cal.index", "cal.owa", "cal.import", "cal.copilot"),
    "teams": ("teams.uia", "teams.web", "teams.copilot"),
    "pc_session": ("pc.sampler", "pc.events"),
    "pc_file": ("pc.files", "pc.mru", "pc.recent"),
    "pc_git": ("pc.git",),
    "pc_compute": ("pc.compute",),
    "manual": ("manual",),
}
DEFAULT_SRCS: dict[str, tuple[str, ...]] = {
    "mail": ("mail.com",), "cal": ("cal.com",), "teams": ("teams.uia",), "pc_session": ("pc.sampler", "pc.events"),
    "pc_file": ("pc.files",), "pc_git": ("pc.git",), "pc_compute": ("pc.compute",), "manual": ("manual",),
}
COMMON_COLUMNS = frozenset({
    "id", "kind", "src", "pc_id", "ts_utc", "ts_local_offset", "ts_precision", "ts_end", "direction", "act",
    "act_cues", "thread_key", "chat_key", "counterpart_keys", "n_participants", "doc_key", "app_id", "attach_keys",
    "flags", "confidence", "observed_at", "rules_ver", "kid", "san", "priv_score", "priv_class", "priv_why",
})
KIND_COLUMNS: dict[str, frozenset[str]] = {
    "mail": frozenset({"msg_key", "box", "folder_role", "sender_key", "sender_label", "n_to", "n_cc", "rcv",
                       "subject_masked", "attach_names_masked", "attach_exts", "categories_masked", "importance",
                       "is_reply", "refw_depth", "focused_other", "ad_score", "ad_band", "ad_why", "ad_partial",
                       "abs_hint", "replied", "i_sent_in_conv", "text_masked"}),
    "cal": frozenset({"msg_key", "subject_masked", "busy", "location_class", "categories_masked", "abs_hint",
                      "text_masked"}),
    "teams": frozenset({"msg_key", "chat_type", "author_key", "file_names_masked", "file_keys", "body_masked",
                        "chat_title_masked", "priv_score_base", "text_masked"}),
    "pc_session": frozenset({"fg_exe", "app_class", "title_masked", "site_class", "session_state", "idle_sec",
                             "layer", "event_class"}),
    "pc_file": frozenset({"path_key", "name_masked", "ext", "folder_role", "root_id", "op", "size_bucket",
                          "ooxml_totaltime", "ooxml_revision", "dir_keys"}),
    "pc_git": frozenset({"commit_key", "msg_masked", "n_commits", "n_files", "exts"}),
    "pc_compute": frozenset({"cpu_core"}),
    "manual": frozenset({"work_category", "hours", "text_masked", "project_id", "role_field", "role_func",
                         "man_kind", "ref_keys", "retract_of"}),
}
STORED_COLUMNS: dict[str, frozenset[str]] = {k: COMMON_COLUMNS | v for k, v in KIND_COLUMNS.items()}
FLAG_KEYS: dict[str, frozenset[str]] = {   # 계약 §3.3
    "mail": frozenset({"has_file", "list_unsub", "precedence", "esp", "body_unsub", "bulk", "cc", "sensitivity",
                       "cat_private", "ad", "private", "meeting_response", "cap_hit", "utc_suspect", "deferred",
                       "teams_notice"}),
    "cal": frozenset({"sensitivity", "cat_private", "private", "recurring", "all_day", "online_meeting",
                      "organizer_me", "recurrence_incomplete", "response", "meeting_status", "cap_hit",
                      "utc_suspect"}),
    "teams": frozenset({"mentions_me", "has_file", "private", "cap_hit", "utc_suspect", "n_part_est",
                        "author_inherited"}),
    "pc_session": frozenset({"end_uncertain", "stuck", "always_on", "remote", "utc_suspect", "no_key", "inprivate"}),
    "pc_file": frozenset({"view_only", "edit", "author_other", "pdf_export", "final_name", "has_file", "no_key",
                          "autosave"}),
    "pc_git": frozenset({"cap_hit"}),
    "pc_compute": frozenset({"solver", "license", "end_uncertain"}),
    "manual": frozenset(),
}
TEXT_COLUMNS: dict[str, tuple[str, ...]] = {   # id 의 '정제문 연결' 재료(이 생성기 기준)
    "mail": ("subject_masked", "attach_names_masked", "categories_masked", "text_masked"),
    "cal": ("subject_masked", "categories_masked", "text_masked"),
    "teams": ("body_masked", "file_names_masked", "chat_title_masked", "text_masked"),
    "pc_session": ("title_masked",),
    "pc_file": ("name_masked",),
    "pc_git": ("msg_masked",),
    "pc_compute": (),
    "manual": ("text_masked",),
}
CUES = {"request": ("req",), "report": ("rep",), "ask": ("ask",), "ack": ("ack",), "sched": ("sched",),
        "info": ("fyi",)}
TITLE_KEEP = frozenset({"office", "cad", "pdf", "viewer", "ide", "sim", "eda"})
FOLDER_ROLE = {"Documents": "documents", "Desktop": "desktop", "Downloads": "downloads"}
_SIZE = ((100_000, "<100KB"), (1_000_000, "100KB-1MB"), (4_000_000, "1-4MB"), (16_000_000, "4-16MB"),
         (64_000_000, "16-64MB"))


def size_bucket(n: int) -> str:
    for lim, name in _SIZE:
        if n < lim:
            return name
    return ">64MB"


def _merge(*sans: Mapping[str, int]) -> dict[str, int]:
    out: dict[str, int] = {}
    for s in sans:
        for k, v in s.items():
            out[k] = out.get(k, 0) + v
    return out


def _base(kind: str, src: str, pc_id: str, ts, off: int, prec: str, observed, conf: float, keys: SynthKeys,
          priv_score: int | None) -> dict:
    return {"kind": kind, "src": src, "pc_id": pc_id, "ts_utc": utc_iso(ts), "ts_local_offset": fmt_offset(off),
            "ts_precision": prec, "act": "", "confidence": conf, "observed_at": utc_iso(observed),
            "rules_ver": RULES_VER, "kid": keys.kid, "san": {}, "priv_score": priv_score, "priv_class": "work",
            "priv_why": []}


def _finish(row: dict) -> dict:
    """id = sha1(src|pc_id|ts_utc|주 키|sha1(텍스트 열을 \\x1f 로 이은 것))[:16] (P §10.1 · 계약 §3.1)."""
    texts: list[str] = []
    for col in TEXT_COLUMNS[row["kind"]]:
        v = row.get(col)
        if isinstance(v, list):
            texts.extend(v)
        elif v:
            texts.append(v)
    th = hashlib.sha1("\x1f".join(texts).encode("utf-8")).hexdigest()
    primary = row.get("msg_key") or row.get("commit_key") or row.get("path_key") or row.get("doc_key") or ""
    row["id"] = hashlib.sha1("|".join((row["src"], row["pc_id"], row["ts_utc"], primary, th)).encode("utf-8")
                             ).hexdigest()[:16]
    return row


def _witness(plan: Plan, kind: str, src: str, keys: SynthKeys) -> list[dict]:
    """*.copilot 증인 행(계약 §3.2): date 정밀도, confidence 0.3, text_masked ≤200, 형식 준수 HMAC msg_key."""
    P = plan.persona
    pc = P.pc("CLOUD")
    out = []
    for d, parts in daily_witness(plan, kind):
        _raw, text, san = P.render(parts, keys)
        ts = at_local(d, 0, P.offset_min)
        row = _base(kind, src, pc.pc_id, ts, P.offset_min, "date", plan.as_of, 0.3, keys, None)
        material = f"cp:{src}|{d.isoformat()}|{hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]}"
        row.update(text_masked=text[:200], san=san)
        if kind == "mail":
            row.update(msg_key=keys.msg(material), box="other", folder_role="other", direction="unknown")
        elif kind == "cal":
            row.update(msg_key=keys.cal(material), ts_end=utc_iso(ts + timedelta(days=1)))
        else:
            row.update(msg_key=keys.msg(material), chat_key=keys.chat("cp:" + d.isoformat()), chat_type="group",
                       direction="unknown", author_key=None)
        out.append(_finish(row))
    return out


def _mail(plan: Plan, src: str, keys: SynthKeys) -> list[dict]:
    if src == "mail.copilot":
        return _witness(plan, "mail", src, keys)
    P = plan.persona
    sent_threads = {ev.thread for ev in plan.mails if ev.box == "sent"}
    asof_day = to_local(plan.as_of, P.offset_min).date()
    out = []
    for ev in plan.mails:
        pc = P.pc("CLOUD" if src == "mail.owa" else ev.pc)
        sender = P.person(ev.sender)
        to = [P.person(x) for x in ev.to]
        cc = [P.person(x) for x in ev.cc]
        _raw, subj, san = P.render(ev.subject, keys)
        names = [P.mask(n, keys) for n in ev.attach]
        ts, prec, conf, observed = ev.utc, "minute", 1.0, ev.utc + timedelta(minutes=15)
        if src == "mail.owa":
            observed = plan.as_of
            if to_local(ev.utc, ev.off).date() < asof_day - timedelta(days=1):
                ts, prec, conf = local_midnight(ev.utc, ev.off), "date", 0.4
            else:
                conf = 0.8
        elif src == "mail.import":
            observed = plan.as_of
        row = _base("mail", src, pc.pc_id, ts, ev.off, prec, observed, conf, keys, -3)
        others = [p for p in (sender, *to, *cc) if not p.is_self]
        row.update({
            "direction": "out" if ev.box == "sent" else "in",
            "act_cues": list(CUES.get(ev.act, ())),
            "msg_key": keys.msg("mid:" + message_id(ev, plan)),
            "thread_key": keys.thread(conversation_id(ev.thread)),
            "box": ev.box,
            "folder_role": ev.folder_role,
            "sender_key": "self" if sender.is_self else keys.who(sender),
            "sender_label": P.label_of(sender),
            "counterpart_keys": sorted({keys.who(p) for p in others})[:20],
            "n_participants": len({p.pid for p in (sender, *to, *cc)}),
            "n_to": len(to),
            "n_cc": len(cc),
            "rcv": "na" if ev.box == "sent" else ("to" if "self" in ev.to else "cc" if "self" in ev.cc else "bulk"),
            "subject_masked": subj[:120],
            "attach_names_masked": [m[:80] for m, _s in names][:5],
            "attach_keys": [keys.doc(n) for n in ev.attach][:10],
            "attach_exts": sorted({"." + n.rsplit(".", 1)[-1].lower() for n in ev.attach})[:10],
            "categories_masked": [],
            "importance": ev.importance,
            "is_reply": ev.reply,
            "refw_depth": 1 if ev.reply else 0,
            "focused_other": None,
            "ad_score": -3 if sender.org in ("self", "internal") else -1,
            "ad_band": "keep",
            "ad_why": [],
            "ad_partial": src in ("mail.index", "mail.owa"),
            "abs_hint": "none",
            "replied": ev.box == "inbox" and ev.thread in sent_threads,
            "i_sent_in_conv": ev.thread in sent_threads,
            "san": _merge(san, *(s for _m, s in names)),
        })
        if ev.attach:
            row["flags"] = {"has_file": True}
        out.append(_finish(row))
    return out


def _cal(plan: Plan, src: str, keys: SynthKeys) -> list[dict]:
    if src == "cal.copilot":
        return _witness(plan, "cal", src, keys)
    P = plan.persona
    out = []
    for ev in plan.meets:
        pc = P.pc("CLOUD" if src == "cal.owa" else ev.pc)
        org = P.person(ev.organizer)
        atts = [P.person(x) for x in ev.attendees]
        _raw, subj, san = P.render(ev.subject, keys)
        observed = plan.as_of if src in ("cal.owa", "cal.import") else ev.start - timedelta(days=1)
        row = _base("cal", src, pc.pc_id, ev.start, ev.off, "minute", observed, 0.8 if src == "cal.owa" else 1.0,
                    keys, -2)
        flags: dict = {"response": ev.response, "meeting_status": 1}
        if ev.series:
            flags["recurring"] = True
        if ev.location == "online":
            flags["online_meeting"] = True
        if org.is_self:
            flags["organizer_me"] = True
        row.update({
            "ts_end": utc_iso(ev.end),
            "act_cues": [],
            "msg_key": keys.cal(f"{appointment_id(ev, plan)}|{utc_iso(ev.start)}"),
            "thread_key": keys.thread("series:" + ev.series) if ev.series else None,
            "subject_masked": subj[:120],
            "counterpart_keys": sorted({keys.who(p) for p in (org, *atts) if not p.is_self})[:20],
            "n_participants": len({p.pid for p in (org, *atts)}),
            "busy": ev.busy,
            "location_class": ev.location,
            "categories_masked": [],
            "abs_hint": "none",
            "flags": flags,
            "san": san,
        })
        out.append(_finish(row))
    return out


def _teams(plan: Plan, src: str, keys: SynthKeys) -> list[dict]:
    if src == "teams.copilot":
        return _witness(plan, "teams", src, keys)
    P = plan.persona
    web = src == "teams.web"
    out = []
    for ev in plan.chats:
        room = ev.room
        pc = P.pc("CLOUD" if web else ev.pc)
        author = P.person(ev.author)
        raw_body, body, san = P.render(ev.body, keys)
        title = None
        if room.title and room.chat_type in ("group", "channel", "meeting"):
            _r, title, s2 = P.render(room.title, keys)
            san = _merge(san, s2)
        files = [P.mask(n, keys) for n in ev.files]
        if web:
            ts, prec, conf, observed = ev.utc, "exact", 1.0, plan.as_of
            mk = keys.msg("tid:" + ev.mid)
        else:
            ts, prec, conf, observed = ev.utc.replace(second=0), "minute", 0.8, ev.utc + timedelta(minutes=5)
            loc = to_local(ts, ev.off)
            norm_body = re.sub(r"\s+", " ", raw_body).strip()
            mk = keys.msg(f"teams:{loc.date().isoformat()}|{room.uia_id}|{norm_person(author.name)}|"
                          f"{loc.strftime('%H:%M')}|{hashlib.sha256(norm_body.encode('utf-8')).hexdigest()[:16]}")
        row = _base("teams", src, pc.pc_id, ts, ev.off, prec, observed, conf, keys, -2)
        row.update({
            "direction": "sent" if author.is_self else "received",
            "act_cues": list(CUES.get(ev.act, ())),
            "msg_key": mk,
            "chat_key": keys.chat(room.raw_id if web else room.uia_id),
            "chat_type": room.chat_type,
            "thread_key": keys.thread(ev.reply_to) if (web and ev.reply_to) else None,
            "author_key": "self" if author.is_self else keys.who(author),
            "counterpart_keys": sorted({keys.who(P.person(m)) for m in room.members if m != "self"})[:20],
            "n_participants": len(room.members),
            "file_names_masked": [m[:80] for m, _s in files][:5],
            "file_keys": [keys.doc(n) for n in ev.files][:10],
            "body_masked": body[:300],
            "chat_title_masked": title[:60] if title else None,
            "priv_score_base": -2,
            "san": _merge(san, *(s for _m, s in files)),
        })
        flags = {}
        if ev.mentions_me:
            flags["mentions_me"] = True
        if ev.files:
            flags["has_file"] = True
        if flags:
            row["flags"] = flags
        out.append(_finish(row))
    return out


def _session(plan: Plan, src: str, keys: SynthKeys) -> list[dict]:
    P = plan.persona
    out = []
    if src == "pc.events":
        for ev in plan.power:
            row = _base("pc_session", src, P.pc(ev.pc).pc_id, ev.start, ev.off, "minute", ev.end + timedelta(hours=6),
                        1.0, keys, None)
            row.update({"ts_end": utc_iso(ev.end), "app_id": None, "session_state": "active", "idle_sec": None,
                        "layer": ev.layer, "event_class": ev.event_class})
            if ev.end_uncertain:
                row["flags"] = {"end_uncertain": True}
            out.append(_finish(row))
        return out
    for ev in plan.ticks:
        row = _base("pc_session", src, P.pc(ev.pc).pc_id, ev.utc, ev.off, "exact",
                    ev.utc + timedelta(seconds=ev.interval), 1.0, keys, None)
        keep = ev.title is not None and ev.app_class in TITLE_KEEP
        _r, title, san = P.render(ev.title, keys) if keep else ("", None, {})
        row.update({
            "ts_end": utc_iso(ev.utc + timedelta(seconds=ev.interval)),
            "app_id": ev.app_id,
            "fg_exe": ev.exe,
            "app_class": ev.app_class,
            "title_masked": title[:120] if title else None,
            "doc_key": keys.doc(ev.doc) if ev.doc else None,
            "site_class": "work_site" if ev.app_class == "browser" else None,
            "session_state": ev.state,
            "idle_sec": ev.idle,
            "layer": ev.layer,
            "event_class": None,
            "san": san,
        })
        out.append(_finish(row))
    return out


def _file(plan: Plan, src: str, keys: SynthKeys) -> list[dict]:
    P = plan.persona
    files = src == "pc.files"
    out = []
    for ev in plan.files:
        ext = ev.name.rsplit(".", 1)[-1].lower()
        office = ext in OFFICE_EXTS
        name, san = P.mask(ev.name, keys)
        ts = ev.utc if files else ev.utc.replace(second=0)
        row = _base("pc_file", src, P.pc(ev.pc).pc_id, ts, ev.off, "exact" if files else "minute",
                    ev.utc + timedelta(minutes=5 if files else 360), 1.0 if files else 0.8, keys, None)
        parents = list(reversed(("Users", P.winuser, *ev.folder)))[:3]
        row.update({
            "doc_key": keys.doc(ev.name),
            "path_key": keys.path(full_path(P, ev)),
            "name_masked": name[:80],
            "ext": "." + ext,
            "folder_role": FOLDER_ROLE.get(ev.folder[0], "other"),
            "root_id": None,
            "op": ev.op if files else "open",
            "size_bucket": size_bucket(ev.size),
            "ooxml_totaltime": ev.totaltime if office else None,
            "ooxml_revision": ev.revision if office else None,
            "dir_keys": [keys.dir(n) for n in parents],
            "san": san,
        })
        flags = {}
        if files:
            flags["edit"] = True
        if ev.last_by != "self":
            flags["author_other"] = True
        if ev.pdf_sibling:
            flags["pdf_export"] = True
        if "_최종" in ev.name:
            flags["final_name"] = True
        if flags:
            row["flags"] = flags
        out.append(_finish(row))
    return out


def _git(plan: Plan, src: str, keys: SynthKeys) -> list[dict]:
    P = plan.persona
    out = []
    for ev in plan.commits:
        _r, msg, san = P.render(ev.subject, keys)
        row = _base("pc_git", src, P.pc(ev.pc).pc_id, ev.utc, ev.off, "exact", ev.utc + timedelta(hours=1), 1.0, keys,
                    None)
        row.update({"doc_key": keys.repo(ev.repo), "commit_key": keys.commit(ev.sha), "msg_masked": msg[:120],
                    "n_commits": 1, "n_files": ev.n_files, "exts": list(ev.exts), "san": san})
        out.append(_finish(row))
    return out


def _compute(plan: Plan, src: str, keys: SynthKeys) -> list[dict]:
    P = plan.persona
    out = []
    for ev in plan.computes:
        row = _base("pc_compute", src, P.pc(ev.pc).pc_id, ev.start, ev.off, "minute", ev.end + timedelta(minutes=5),
                    1.0, keys, None)
        row.update({"ts_end": utc_iso(ev.end), "app_id": ev.app_id, "cpu_core": ev.cpu_core, "flags": {"solver": True}})
        out.append(_finish(row))
    return out


def _manual(plan: Plan, src: str, keys: SynthKeys) -> list[dict]:
    P = plan.persona
    out = []
    for ev in plan.manuals:
        if ev.start_min is not None and ev.end_min is not None:
            ts, te, prec = at_local(ev.day, ev.start_min, ev.off), at_local(ev.day, ev.end_min, ev.off), "minute"
        else:
            ts, te, prec = at_local(ev.day, 0, ev.off), None, "date"
        _r, note, san = P.render(ev.note, keys)
        if ev.entity:
            _r2, ent, s2 = P.render(ev.entity, keys)
            note, san = f"{note} / {ent}", _merge(san, s2)
        row = _base("manual", src, P.pc(ev.pc).pc_id, ts, ev.off, prec, at_local(ev.day, 18 * 60, ev.off), 1.0, keys,
                    None)
        row.update({"ts_end": utc_iso(te) if te else None, "work_category": ev.category, "hours": ev.hours,
                    "text_masked": note[:200], "project_id": ev.project_id, "role_field": ev.role_field,
                    "role_func": ev.role_func, "man_kind": ev.man_kind, "ref_keys": [], "retract_of": None,
                    "san": san})
        out.append(_finish(row))
    return out


_BUILD = {"mail": _mail, "cal": _cal, "teams": _teams, "pc_session": _session, "pc_file": _file, "pc_git": _git,
          "pc_compute": _compute, "manual": _manual}


def stored_rows(plan: Plan | None = None, *, kinds: Iterable[str] | None = None,
                srcs: Mapping[str, Iterable[str]] | None = None, seed: int = 0, d0: date | None = None,
                d1: date | None = None, density: str = "light", persona: Persona | None = None,
                keys: SynthKeys | None = None, multi_pc: bool = False) -> list[dict]:
    """정제 후 저장 행 모양 dict 목록((ts_utc, id) 정렬). plan 을 안 주면 [d0, d1](기본 2026-09 한 달) 계획을 만든다.
    srcs = {kind: (경로 ID, …)} 로 kind 별 경로를 바꾼다(기본 DEFAULT_SRCS). 봉인 없음 — 가짜 입력 전용."""
    if plan is None:
        plan = plan_period(d0, d1, persona=persona, seed=seed, density=density, multi_pc=multi_pc)
    keys = keys or synth_keys(plan.seed)
    want = tuple(kinds) if kinds is not None else KINDS
    sel = dict(DEFAULT_SRCS)
    for k, v in (srcs or {}).items():
        sel[k] = tuple(v)
    rows: list[dict] = []
    for kind in want:
        if kind not in _BUILD:
            raise ValueError(f"알 수 없는 kind: {kind}")
        for src in sel[kind]:
            if src not in SRCS_BY_KIND[kind]:
                raise ValueError(f"{kind} 의 경로 아님: {src}")
            rows.extend(_BUILD[kind](plan, src, keys))
    rows.sort(key=lambda r: (r["ts_utc"], r["id"]))
    return rows
