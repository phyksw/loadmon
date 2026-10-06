# -*- coding: utf-8 -*-
r"""분석 파이프라인 단계 표(계약 §2.13 · §8.5 · R §5.3.2 · R §13 A-1 · B §2.3) — 단계 id · 이름 · 의존 · 선택 계획.

    STAGES: list[StageDef]            단계 10종(이 순서로 돈다 — 계약 §8.5 분석 단계 id)
    plan_run(selected, *, ai, rerun)  -> dict[단계 id, 행동]   --rerun/--stages 선택을 단계별 행동으로 펼친다

| id | 이름(R §5.3.2) | 하는 일 | 의존 |
|---|---|---|---|
| ``load`` | 기록 읽기 | 번들 단일 로더 → 재정제(G2) → 병합 → 파생 열(``lm27.normalize.load.load_evidence``) | — |
| ``normalize`` | 정리·병합 | 근태(``absence.leaves``)·커버리지 원장 → 시간 코어 프로필, 화행 회색 지대(B §2.3 호출 지점 2 —
  ``speech_act`` 는 이 단계 안의 AI 보조 단계) → 화행 다시 붙이기 | load |
| ``classify`` | 분류(규칙) | 증거 꼬리표(HierTags) → 시간 코어 계산(단위업무·귀속 — 메모리) → 단위업무 규칙 라벨 → task_label ai_in | normalize |
| ``ai:task_label`` | AI 업무 이름·분류 | 브리지 ``task_label``(호출 지점 3) | classify |
| ``time`` | 근무시간·단위업무 | 최종 라벨(AI 답 반영) → 롤업 → 보존 검사(T-01) · 분류 불변(T-06) → ``time\``·``hier\`` 결과 파일 | classify |
| ``mining`` | 워크플로우 계산 | 과정 마이닝 → ai_in(workflow_label·agentic_match·subagent_review) | time |
| ``ai:workflow`` | AI 단계 이름·매칭·검토 | 브리지 3단계(호출 지점 4) | mining |
| ``review`` | 리뷰 사실 | 주간·월간 리뷰 사실 → ai_in(review_text) | time |
| ``ai:review_text`` | AI 리뷰 문장 | 브리지 ``review_text``(호출 지점 5) | review |
| ``report`` | 보고서 만들기 | ``lm27.report.build_report`` → ``report_model.json`` | time |

``classify`` 가 시간 코어를 먼저 계산하는 까닭: 단위업무 규칙 라벨(H §4.0)과 코파일럿 업무 이름(``ai:task_label``)은 시간
코어가 만든 단위업무 위에서만 정해지는데 계약 순서는 classify → ai:task_label → time 이다. 시간 코어 결과는 분류 꼬리표
(HierTags — 규칙만)에만 기대고 AI 라벨은 시간 값으로 되먹지 않으므로(H-I6) 한 번 계산한 결과를 ``time`` 단계가 그대로
라벨·롤업·파일로 마무리한다(두 번 계산하지 않는다).

선택 계획(``plan_run``) — 행동 값:
``run``(고른 단계) · ``auto``(고른 단계에 필요해 함께 도는 단계 — 메모리 사슬·AI 단계의 입력 단계) ·
``reuse``(재분석 원본 실행의 ``time``·``hier`` 결과 파일을 새 실행으로 옮겨 쓴다) · ``skip:<사유>``(``ai_off``·
``not_selected``·``reused``). 메모리 사슬(load → normalize → classify → time)은 결과가 메모리에만 있으므로 그중 하나라도
고르면 넷 다 돈다(빠른 재분석 ``classify,time,mining,report`` 의 load·normalize 는 ``auto`` — 확인 질문 응답(수동 행)을 다시
읽어야 하므로). 사슬을 고르지 않은 재분석은 원본 실행의 시간·분류 결과를 다시 쓴다(``reuse``).

이 모듈은 표준 라이브러리만 쓰고 파일을 읽거나 쓰지 않는다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = ["AI_STAGES", "BY_ID", "CHAIN", "QUICK_RERUN", "STAGES", "STAGE_IDS", "StageDef", "check_ids", "get",
           "name_ko", "plan_run"]

STAGE_RX = re.compile(r"^[a-z][a-z_]*(?::[a-z][a-z_]*)?$")      # 계약 §8.5 단계 id 모양(cli _STAGE_ID_RX 와 같다)


@dataclass(frozen=True)
class StageDef:
    """분석 단계 하나. ``bridge`` = 이 단계가 부르는 브리지 단계(B §8 단계 id, 호출 순서대로). ``ai`` 단계는 단계 전체가
    브리지 호출이고(``--no-ai`` 면 건너뜀), ``ai=False`` 인데 ``bridge`` 가 있으면 단계 안의 선택적 AI 보조 단계다
    (``normalize`` 의 ``speech_act``). ``chain`` = 결과가 메모리에만 있는 사슬 단계. ``outputs`` = 실행 폴더·파생 폴더에
    남기는 산출 묶음 이름."""
    id: str
    name_ko: str
    needs: tuple[str, ...] = ()
    ai: bool = False
    bridge: tuple[str, ...] = ()
    chain: bool = False
    outputs: tuple[str, ...] = ()
    desc_ko: str = ""


STAGES: list[StageDef] = [
    StageDef("load", "기록 읽기", (), chain=True,
             desc_ko="번들 단일 로더로 증거를 읽고 지금 규칙으로 다시 가린 뒤 병합합니다"),
    StageDef("normalize", "정리·병합", ("load",), bridge=("speech_act",), chain=True,
             desc_ko="근태·커버리지를 시간 코어 프로필로 모으고 화행을 정리합니다"),
    StageDef("classify", "분류(규칙)", ("normalize",), chain=True,
             desc_ko="규칙으로 증거·단위업무를 분류합니다(단위업무는 시간 코어가 만듭니다)"),
    StageDef("ai:task_label", "AI 업무 이름·분류", ("classify",), ai=True, bridge=("task_label",),
             desc_ko="코파일럿이 단위업무 이름과 분류를 붙입니다"),
    StageDef("time", "근무시간·단위업무", ("classify",), chain=True, outputs=("time", "hier"),
             desc_ko="최종 라벨로 롤업하고 시간·분류 결과 파일을 씁니다"),
    StageDef("mining", "워크플로우 계산", ("time",), outputs=("ai_in",),
             desc_ko="역할 업무별 워크플로우를 계산합니다"),
    StageDef("ai:workflow", "AI 단계 이름·매칭·검토", ("mining",), ai=True,
             bridge=("workflow_label", "agentic_match", "subagent_review"),
             desc_ko="코파일럿이 워크플로우 단계 이름·에이전트 매칭·서브에이전트 검토를 붙입니다"),
    StageDef("review", "리뷰 사실", ("time",), outputs=("ai_in",),
             desc_ko="주간·월간 리뷰 사실을 모읍니다"),
    StageDef("ai:review_text", "AI 리뷰 문장", ("review",), ai=True, bridge=("review_text",),
             desc_ko="코파일럿이 리뷰 문장을 씁니다"),
    StageDef("report", "보고서 만들기", ("time",), outputs=("report",),
             desc_ko="보고서 모델을 만듭니다"),
]
STAGE_IDS: tuple[str, ...] = tuple(s.id for s in STAGES)
BY_ID: dict[str, StageDef] = {s.id: s for s in STAGES}
AI_STAGES: tuple[str, ...] = tuple(s.id for s in STAGES if s.ai)
CHAIN: tuple[str, ...] = tuple(s.id for s in STAGES if s.chain)              # load · normalize · classify · time
QUICK_RERUN: tuple[str, ...] = ("classify", "time", "mining", "report")      # 빠른 재분석(계약 §7.1 · X-281)
_MEMORY = frozenset(CHAIN) | {"ai:task_label"}                               # 메모리 사슬 결과가 필요한 단계
_PRODUCER = {"ai:task_label": "classify", "ai:workflow": "mining", "ai:review_text": "review"}
_NEEDS_TIME = ("mining", "review", "report")


def get(stage_id: str) -> StageDef:
    """단계 정의(없는 id 면 ValueError — 한국어)."""
    s = BY_ID.get(stage_id)
    if s is None:
        raise ValueError(f"분석 단계 id 가 아닙니다: {str(stage_id)[:40]} — {', '.join(STAGE_IDS)} 중 하나")
    return s


def name_ko(stage_id: str) -> str:
    return get(stage_id).name_ko


def check_ids(ids) -> list[str]:
    """단계 id 목록 검사 — 모양·이름이 틀리면 ValueError. 중복을 빼고 표 순서로 돌려준다."""
    if isinstance(ids, str):
        ids = [x.strip() for x in ids.split(",") if x.strip()]
    want = set()
    for x in ids or ():
        if not isinstance(x, str) or not STAGE_RX.match(x):
            raise ValueError(f"단계 id 모양이 아닙니다(예 {','.join(QUICK_RERUN)}): {str(x)[:40]}")
        get(x)
        want.add(x)
    if not want:
        raise ValueError("고른 단계가 없습니다")
    return [s for s in STAGE_IDS if s in want]


def plan_run(selected=None, *, ai: bool = True, rerun: bool = False) -> dict[str, str]:
    """단계별 행동 ``{id: run|auto|reuse|skip:<사유>}`` (표 순서). ``selected`` None = 전체 분석.

    재분석이 아닌데 메모리 사슬 단계를 하나도 고르지 않으면(다시 쓸 이전 결과가 없음) ValueError."""
    if selected is None:
        return {s.id: ("skip:ai_off" if s.ai and not ai else "run") for s in STAGES}
    sel = set(check_ids(selected))
    want = set(sel)
    for st, producer in _PRODUCER.items():                 # AI 단계의 입력(ai_in·메모리 라벨)을 만드는 단계
        if st in want and ai:
            want.add(producer)
    chain = bool(want & _MEMORY)
    if chain:
        want |= set(CHAIN)
    elif not rerun:
        raise ValueError("다시 쓸 이전 분석이 없어 고른 단계만 돌 수 없습니다 — --rerun <run_id> 와 함께 쓰세요")
    out: dict[str, str] = {}
    for s in STAGES:
        if s.ai:
            if s.id not in sel:
                out[s.id] = "skip:not_selected"
            else:
                out[s.id] = "run" if ai else "skip:ai_off"
        elif s.id == "time" and not chain:
            out[s.id] = "reuse" if want & set(_NEEDS_TIME) else "skip:not_selected"
        elif s.chain and not chain:
            out[s.id] = "skip:reused" if want & set(_NEEDS_TIME) else "skip:not_selected"
        elif s.id in sel:
            out[s.id] = "run"
        elif s.id in want:
            out[s.id] = "auto"
        else:
            out[s.id] = "skip:not_selected"
    if not any(v in ("run", "auto") for v in out.values()):
        raise ValueError("돌릴 단계가 없습니다(AI 단계만 골랐는데 --no-ai 입니다)")
    return out
