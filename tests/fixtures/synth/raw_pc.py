# -*- coding: utf-8 -*-
"""kind=pc_session·pc_file·pc_git·pc_compute 원시 레코드(P §10.2 원시 이름) — 정제 전 메모리 모양. 시험 입력용이며 디스크에
쓰지 않는다. 사용자명·컴퓨터 이름·이벤트 메시지 원문 필드는 만들지 않는다(금지 원시 필드 — P §10.2 · T31).

    session_records(plan)                    # pc.sampler 창 샘플(전경 exe·창 제목 원문·idle·session_state·layer)
    session_records(plan, src="pc.events")   # pc.events 전원·세션 구간(무텍스트)
    file_records(plan, src="pc.files")       # pc.files · pc.mru · pc.recent (전체 경로 원문)
    git_records(plan) · compute_records(plan)
"""
from __future__ import annotations

from collections.abc import Iterable
from datetime import timedelta

from .month import CommitEv, FileEv, Plan, fmt_offset, plant_text, plantable, utc_iso
from .persona import Persona

SESSION_SRCS = ("pc.sampler", "pc.events")
FILE_SRCS = ("pc.files", "pc.mru", "pc.recent")
OFFICE_EXTS = frozenset({"xlsx", "docx", "pptx"})
SESSION_FIELDS = frozenset({
    "fg_exe", "app_id", "app_class", "fg_title", "fg_doc_name", "session_state", "idle_sec", "layer", "interval_sec",
    "event_class", "ts_utc", "ts_end", "ts_local_offset", "ts_precision", "observed_at", "confidence", "flags",
})
FILE_FIELDS = frozenset({
    "path", "op", "size", "ooxml_totaltime", "ooxml_revision", "ooxml_last_modified_by", "target_mtime", "pdf_sibling",
    "ts_utc", "ts_local_offset", "ts_precision", "observed_at", "confidence", "flags",
})
GIT_FIELDS = frozenset({
    "repo_root", "commit_sha", "subject", "n_commits", "n_files", "exts",
    "ts_utc", "ts_local_offset", "ts_precision", "observed_at", "confidence", "flags",
})
COMPUTE_FIELDS = frozenset({
    "fg_exe", "app_id", "cpu_core", "ts_utc", "ts_end", "ts_local_offset", "ts_precision", "observed_at", "confidence",
    "flags",
})


def full_path(P: Persona, ev: FileEv) -> str:
    """원시 전체 경로(사용자 폴더 아래, 자리표시자 사용자명)."""
    return "\\".join(("C:", "Users", P.winuser, *ev.folder, ev.name))


def repo_root(P: Persona, ev: CommitEv) -> str:
    return "\\".join(("C:", "Users", P.winuser, "src", ev.repo))


def session_records(plan: Plan, *, src: str = "pc.sampler", canaries: Iterable | None = None) -> list[dict]:
    """창 샘플(pc.sampler) 또는 전원·세션 이벤트(pc.events) 원시 레코드. 카나리아는 샘플의 창 제목 원문에 심는다."""
    if src not in SESSION_SRCS:
        raise ValueError(f"pc_session 경로 아님: {src}")
    if src == "pc.events":
        return [{"event_class": ev.event_class, "session_state": "active", "layer": ev.layer,
                 "ts_utc": utc_iso(ev.start), "ts_end": utc_iso(ev.end), "ts_local_offset": fmt_offset(ev.off),
                 "ts_precision": "minute", "observed_at": utc_iso(ev.end + timedelta(hours=6)), "confidence": 1.0,
                 "flags": {"end_uncertain": ev.end_uncertain}} for ev in plan.power]
    P = plan.persona
    out = [{"fg_exe": ev.exe, "app_id": ev.app_id, "app_class": ev.app_class,
            "fg_title": P.render(ev.title)[0] if ev.title else "", "fg_doc_name": ev.doc,
            "session_state": ev.state, "idle_sec": ev.idle, "layer": ev.layer, "interval_sec": ev.interval,
            "ts_utc": utc_iso(ev.utc), "ts_local_offset": fmt_offset(ev.off), "ts_precision": "exact",
            "observed_at": utc_iso(ev.utc + timedelta(seconds=ev.interval)), "confidence": 1.0, "flags": {}}
           for ev in plan.ticks]
    if canaries and out:
        office = [r for r in out if r["app_class"] == "office"] or out
        for i, c in enumerate(plantable(canaries, "file")):           # 먼저 문서 이름 바꾸기(뒤의 덧붙이기를 덮지 않게)
            rec = office[(4 + i * 5) % len(office)]
            rec["fg_title"] = f"{c.sentence} - Excel"
            rec["fg_doc_name"] = c.sentence
        plant_text(office, canaries, "fg_title", sep=" - ")
    return out


def file_records(plan: Plan, *, src: str = "pc.files", canaries: Iterable | None = None) -> list[dict]:
    """문서 증거 원시 레코드(전체 경로 원문 — 정제기가 path_key·doc_key·name_masked 로 바꾼다). 카나리아는 경로·파일 이름에."""
    if src not in FILE_SRCS:
        raise ValueError(f"pc_file 경로 아님: {src}")
    P = plan.persona
    files = src == "pc.files"
    out = []
    for ev in plan.files:
        office = ev.name.rsplit(".", 1)[-1].lower() in OFFICE_EXTS
        out.append({
            "path": full_path(P, ev),
            "op": ev.op if files else "open",
            "size": ev.size,
            "ooxml_totaltime": ev.totaltime if office else None,
            "ooxml_revision": ev.revision if office else None,
            "ooxml_last_modified_by": P.person(ev.last_by).name if office else None,
            "target_mtime": utc_iso(ev.utc),
            "pdf_sibling": ev.pdf_sibling,
            "ts_utc": utc_iso(ev.utc if files else ev.utc.replace(second=0)),
            "ts_local_offset": fmt_offset(ev.off),
            "ts_precision": "exact" if files else "minute",
            "observed_at": utc_iso(ev.utc + timedelta(minutes=5 if files else 360)),
            "confidence": 1.0 if files else 0.8,
            "flags": {},
        })
    if canaries and out:
        n = len(out)
        for i, c in enumerate(plantable(canaries, "path")):
            out[(1 + i * 5) % n]["path"] = c.sentence
        for i, c in enumerate(plantable(canaries, "file")):
            rec = out[(3 + i * 5) % n]
            rec["path"] = "\\".join((*rec["path"].split("\\")[:-1], c.sentence))
        for i, c in enumerate(plantable(canaries, "name")):
            rec = out[(2 + i * 5) % n]
            if rec["ooxml_last_modified_by"] is not None:
                rec["ooxml_last_modified_by"] = c.value
    return out


def git_records(plan: Plan, *, src: str = "pc.git", canaries: Iterable | None = None) -> list[dict]:
    """본인 커밋 원시 레코드(저장소 경로 원문·커밋 sha·제목). 작성자 신원은 넘기지 않는다(P §10.2)."""
    if src != "pc.git":
        raise ValueError(f"pc_git 경로 아님: {src}")
    P = plan.persona
    out = [{"repo_root": repo_root(P, ev), "commit_sha": ev.sha, "subject": P.render(ev.subject)[0], "n_commits": 1,
            "n_files": ev.n_files, "exts": list(ev.exts), "ts_utc": utc_iso(ev.utc),
            "ts_local_offset": fmt_offset(ev.off), "ts_precision": "exact",
            "observed_at": utc_iso(ev.utc + timedelta(hours=1)), "confidence": 1.0, "flags": {}}
           for ev in plan.commits]
    if canaries and out:
        plant_text(out, canaries, "subject", sep=" / ")
        for i, c in enumerate(plantable(canaries, "path")):
            out[(1 + i * 3) % len(out)]["repo_root"] = c.sentence
    return out


def compute_records(plan: Plan, *, src: str = "pc.compute", canaries: Iterable | None = None) -> list[dict]:
    """계산 구간 원시 레코드(무텍스트 — 카나리아를 심을 곳이 없다)."""
    if src != "pc.compute":
        raise ValueError(f"pc_compute 경로 아님: {src}")
    return [{"fg_exe": ev.exe, "app_id": ev.app_id, "cpu_core": ev.cpu_core, "ts_utc": utc_iso(ev.start),
             "ts_end": utc_iso(ev.end), "ts_local_offset": fmt_offset(ev.off), "ts_precision": "minute",
             "observed_at": utc_iso(ev.end + timedelta(minutes=5)), "confidence": 1.0, "flags": {"solver": True}}
            for ev in plan.computes]
