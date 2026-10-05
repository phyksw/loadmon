# -*- coding: utf-8 -*-
"""합성 자료 생성기(WP-05) — '모양'만 책임진다. 기대값은 각 WP 시험이 정한다.
출력 형을 바꾸면 SYNTH_VERSION 을 올리고 CR 로 알린다(IMPLEMENTATION_PLAN §3.3).

    from tests.fixtures import synth
    plan = synth.plan_month(2026, 9)                         # 활동 계획(같은 시드 → 같은 계획)
    raw = synth.raw_records("mail", plan)                    # kind 8종 원시 레코드(P §10.2 원시 이름 — 정제 전 모양)
    rows = synth.stored_rows()                               # 정제 후 저장 행 모양 dict(봉인 없음 — 하류 WP 가짜 입력)
    big = synth.signals_3m()                                 # 1명 × 3개월 ≈ 4.3만 행(T-19 · W-G9)
    synth.inject.write_all(tmpdir, plan)                     # 계약 §11.3 주입점 자료

모듈: persona(자리표시자 페르소나·시험 키) · month(활동 계획·시간 도우미) · raw_mail · raw_cal · raw_teams · raw_pc ·
raw_manual · stored · inject. 실명·실도메인 0 — 이메일은 example 도메인만, 이름은 홍길동·김철수와 '동료B' 같은 표지.
"""
from __future__ import annotations

from collections.abc import Iterable

from . import inject, month, persona, raw_cal, raw_mail, raw_manual, raw_pc, raw_teams, stored
from .month import Plan, load_holidays, plan_3m, plan_month, plan_period, signals_3m
from .persona import Persona, SynthKeys, default_persona, doc_fam, synth_keys
from .stored import FLAG_KEYS, KINDS, SRCS_BY_KIND, STORED_COLUMNS, stored_rows

SYNTH_VERSION = "1"

RAW_SRC = {   # kind 별 기본 원시 경로
    "mail": "mail.com", "cal": "cal.com", "teams": "teams.uia", "pc_session": "pc.sampler", "pc_file": "pc.files",
    "pc_git": "pc.git", "pc_compute": "pc.compute", "manual": "manual",
}
RAW_FIELDS = {   # kind 별 원시 필드 이름(P §10.2 원시 이름 + 공통 봉투) — 이 생성기가 내는 것의 상한
    "mail": raw_mail.FIELDS, "cal": raw_cal.FIELDS, "teams": raw_teams.FIELDS, "pc_session": raw_pc.SESSION_FIELDS,
    "pc_file": raw_pc.FILE_FIELDS, "pc_git": raw_pc.GIT_FIELDS, "pc_compute": raw_pc.COMPUTE_FIELDS,
    "manual": raw_manual.FIELDS,
}
_RAW = {
    "mail": raw_mail.records, "cal": raw_cal.records, "teams": raw_teams.records,
    "pc_session": raw_pc.session_records, "pc_file": raw_pc.file_records, "pc_git": raw_pc.git_records,
    "pc_compute": raw_pc.compute_records, "manual": raw_manual.records,
}


def raw_records(kind: str, plan: Plan | None = None, *, src: str | None = None, canaries: Iterable | None = None,
                seed: int = 0) -> list[dict]:
    """kind 원시 레코드(정제 전 메모리 모양). plan 이 없으면 2026-09 한 달(seed). canaries 를 주면 원문 필드에 심는다."""
    if kind not in _RAW:
        raise ValueError(f"알 수 없는 kind: {kind}")
    if plan is None:
        plan = plan_month(2026, 9, seed=seed)
    return _RAW[kind](plan, src=src or RAW_SRC[kind], canaries=canaries)


def raw_all(plan: Plan | None = None, *, canaries: Iterable | None = None, seed: int = 0) -> dict[str, list[dict]]:
    """kind 8종 원시 레코드(기본 경로) — {kind: [레코드…]}."""
    plan = plan or plan_month(2026, 9, seed=seed)
    return {k: raw_records(k, plan, canaries=canaries) for k in KINDS}


__all__ = [
    "FLAG_KEYS", "KINDS", "RAW_FIELDS", "RAW_SRC", "SRCS_BY_KIND", "STORED_COLUMNS", "SYNTH_VERSION",
    "Persona", "Plan", "SynthKeys", "default_persona", "doc_fam", "inject", "load_holidays", "month", "persona",
    "plan_3m", "plan_month", "plan_period", "raw_all", "raw_cal", "raw_mail", "raw_manual", "raw_pc", "raw_records",
    "raw_teams", "signals_3m", "stored", "stored_rows", "synth_keys",
]
