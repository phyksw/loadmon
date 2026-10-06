# -*- coding: utf-8 -*-
r"""``workflow_label`` — 워크플로우 단계 라벨(B §8.4 · R §4.10). 결정적 과정 마이닝이 역할 업무마다 만든 단계 순서에
Copilot 이 이름과 설명만 붙인다 — 단계를 만들거나 합치지 않는다.

ai_in(R §4.10.1 — ``lm27.report.analysis.ai_items.workflow_items``): 키 ``ws:<role_id>``, ``group`` = 과제 키(같은 과제의 역할
업무를 한 질의에 — ``group_strict``), 필드 ``project``(레지스트리 ID · 제안 ``NEW`` · 미분류 ``NONE``) · ``field``·``func``(어휘
코드) · ``steps[[S, 단계 유형, 지지도]] ≤ 8`` · ``trans[[S, S, 횟수]] ≤ 6`` · ``tasks ≤ 5``(단위업무 제목). 규칙 재료
``rule{func_name, step_names{S: 한글명}}``. **시간·MM 은 보내지 않는다** — 지지도·횟수는 건수다(B1 · G-B8).

내용 키 = ``project·field·func·steps_types·tasks`` — ``steps_types`` 는 ``steps`` 에서 횟수를 뺀 ``[S, 유형]``(변하는 값은
키에서 뺀다, B §8.4). 답 ``{role, summary, steps[{s, label, desc}]}`` → 정규화가 입력 순서로 맞추고 유형을 붙인다
``{role, summary, steps[{s, type, label, desc}]}``: 답의 S 는 입력 S 의 부분열이어야 하고(낯선 S → 무효), 빠진 S 는 폴백
라벨로 채운다(셈). 요약·설명에서 시간·공수 숫자 표현이 든 문장은 지운다(B1). 폴백(B §8.4): ``role="판단 유보"`` · 단계 라벨
= 단계 유형 한글명 · ``desc=""`` · 요약 = ``FALLBACK_SUMMARY_TEMPLATE``(보고서는 이 문장을 다시 쓰지 않는다 — RPT-29 · G-R12).

첫 줄의 B 원문 '워크플로우 단계 이름 붙이기' 는 정제기가 '이름 붙이기' 를 사람 이름으로 잡아 프롬프트 게이트가 단계를
멈추므로 '워크플로우 단계 라벨 붙이기' 로 바꿨다(완료 보고 CR — WP-10 이름 문맥 규칙).
"""
from __future__ import annotations

import re
from types import SimpleNamespace

from lm27.bridge.stages import (as_text, cut, fields_of, registry_of, rule_of, scrub_time, str_list, vocab_line,
                                vocab_name)
from lm27.bridge.stages.base import F, StageSpec

__all__ = ["FALLBACK_SUMMARY_TEMPLATE", "UNDECIDED_ROLE", "WorkflowLabel"]

UNDECIDED_ROLE = "판단 유보"
S_RX = re.compile(r"^S\d{1,2}$")
STEPS_MAX = 8
TRANS_MAX = 6
TASKS_MAX = 5
EST_BASE = 200
EST_PER_STEP = 110

WORKFLOW_HEAD_PROMPT = (
    "당신은 업무 프로세스 분석가입니다. 각 항목은 한 사람의 역할 업무 하나에서 프로그램이 기록으로부터 뽑아낸 단계 "
    "순서입니다(단계 코드·단계 유형·관측 횟수, 자주 이어진 전이, 단위업무 예).",
    "항목마다 다음을 씁니다.",
    '- role : 이 역할 업무에서 이 사람의 역할 한 줄(40자 이내). 근거가 약하면 "판단 유보".',
    "- steps : 주어진 단계 코드마다 label(단계 이름 15자 이내)과 desc(무슨 일을 하는지 한 문장, 60자 이내). "
    "주어진 코드만, 주어진 순서대로 씁니다. 단계를 새로 만들거나 합치지 않습니다.",
    "- summary : 이 역할 업무의 흐름 요약 2문장(120자 이내).",
    "규칙: 관측 횟수와 전이는 참고용입니다. 시간·공수·인원수는 쓰지 않습니다. 사람 이름은 쓰지 않습니다.",
)
WORKFLOW_COLUMNS_PROMPT = "[항목] 번호 | 과제·분야·기능 | 단계 | 전이 | 단위업무 예"
WORKFLOW_FORMAT_PROMPT = ('{"rid": <요청번호>, "n": <항목 수>, "items": [ {"id": <번호>, "role": <한 줄>, '
                          '"summary": <2문장>, "steps": [ {"s": <단계 코드>, "label": <단계 이름>, "desc": <한 문장>} ]} ]}')
WORKFLOW_UNKNOWN_PROMPT = 'role 은 "판단 유보", label 은 단계 유형의 한글명을 그대로 씁니다'
FALLBACK_SUMMARY_TEMPLATE = "{func} 업무가 {first}에서 시작해 {last}로 이어집니다."


def _steps(v) -> list[tuple[str, str, object]]:
    """입력 ``steps`` → [(S, 유형, 지지도)](모양이 어긋난 원소는 뺀다)."""
    out = []
    for x in v or ():
        if isinstance(x, (list, tuple)) and len(x) >= 2 and S_RX.match(as_text(x[0])):
            out.append((as_text(x[0]), as_text(x[1]), x[2] if len(x) > 2 else ""))
    return out[:STEPS_MAX]


def _trans(v) -> list[tuple[str, str, object]]:
    out = []
    for x in v or ():
        if isinstance(x, (list, tuple)) and len(x) >= 2:
            out.append((as_text(x[0]), as_text(x[1]), x[2] if len(x) > 2 else ""))
    return out[:TRANS_MAX]


class WorkflowLabel(StageSpec):
    id = "workflow_label"
    title_ko = "워크플로우 단계 라벨 붙이기"
    prompt_ver = "workflow_label/1.0"
    schema_major = 1
    kind = "items"
    model_class = "deep"
    chat_policy = "continue"
    max_items = 6
    min_split = 1
    est_out_per_item = EST_BASE
    group_strict = True
    send_fields = ("project", "field", "func", "steps", "trans", "tasks")
    text_fields = ("tasks",)
    content_key_fields = ("project", "field", "func", "steps_types", "tasks")
    names_field = ""
    item_schema = (F("role", "str", max_len=40, hard_max=120),
                   F("summary", "str", max_len=160, hard_max=400),
                   F("steps", "list", max_items=STEPS_MAX,
                     item=(F("s", "str", pattern=r"S\d{1,2}"), F("label", "str", max_len=20, hard_max=60),
                           F("desc", "str", required=False, max_len=80, hard_max=200))))
    stub = {"role": UNDECIDED_ROLE, "summary": "흐름 요약", "steps": [{"s": "S1", "label": "의뢰 수신", "desc": ""}]}

    # ── 프롬프트 ──
    def header(self, ctx, compact: bool = False) -> str:
        reg = registry_of(ctx)
        return "\n".join(list(WORKFLOW_HEAD_PROMPT) + [vocab_line(reg, "step_types", "단계 유형"),
                                                       vocab_line(reg, "fields", "분야"),
                                                       vocab_line(reg, "functions", "기능")])

    def columns(self) -> str:
        return WORKFLOW_COLUMNS_PROMPT

    def item_line(self, it, n) -> str:
        f = fields_of(it)
        head = f"과제 {as_text(f.get('project')) or '-'} · 분야 {as_text(f.get('field')) or '-'} · 기능 " \
               f"{as_text(f.get('func')) or '-'}"
        steps = " → ".join(f"{s} {t} {c}회" for s, t, c in _steps(f.get("steps")))
        trans = ", ".join(f"{a}→{b} {c}" for a, b, c in _trans(f.get("trans")))
        tasks = " / ".join(str_list(f.get("tasks"))[:TASKS_MAX])
        return f"{n} | {head} | {steps or '-'} | {trans or '-'} | {tasks or '-'}"

    def format_line(self) -> str:
        return WORKFLOW_FORMAT_PROMPT

    def unknown_rule(self) -> str:
        return WORKFLOW_UNKNOWN_PROMPT

    def est_out(self, it) -> int:
        """B §8.4: 200 + 110 × 단계 수."""
        return EST_BASE + EST_PER_STEP * len(_steps(fields_of(it).get("steps")))

    def key_material(self, fields: dict) -> dict:
        return {"project": fields.get("project"), "field": fields.get("field"), "func": fields.get("func"),
                "steps_types": [[s, t] for s, t, _c in _steps(fields.get("steps"))], "tasks": fields.get("tasks")}

    def shrink(self, it, max_chars: int):
        """``tasks`` 2개로 → ``trans`` 3개로 → None(B §8.4)."""
        nf = fields_of(it)
        nf["tasks"] = str_list(nf.get("tasks"))[:2]
        if len(self.item_line(SimpleNamespace(fields=nf), 99)) <= max_chars:
            return nf
        nf["trans"] = list(nf.get("trans") or [])[:3]
        return nf if len(self.item_line(SimpleNamespace(fields=nf), 99)) <= max_chars else None

    # ── 검증·정규화 ──
    def validate(self, ans: dict, it, ctx) -> str:
        """답의 S 집합 ⊆ 입력 S 이고 입력 순서의 부분열(낯선 S·순서 뒤바뀜 → 무효)."""
        order = [s for s, _t, _c in _steps(fields_of(it).get("steps"))]
        pos = {s: i for i, s in enumerate(order)}
        last = -1
        for st in ans.get("steps") or ():
            s = st.get("s")
            if s not in pos or pos[s] <= last:
                return "bad_pattern:steps"
            last = pos[s]
        return ""

    def normalize(self, ans: dict, it, ctx) -> dict:
        """입력 순서로 맞추고 유형을 붙이며, 빠진 단계는 폴백 라벨로 채운다. 요약·설명의 시간 수치 문장은 지운다(B1)."""
        f = fields_of(it)
        names = self._step_names(it, ctx)
        got = {st.get("s"): st for st in ans.get("steps") or ()}
        steps, filled, scrubbed = [], 0, 0
        for s, t, _c in _steps(f.get("steps")):
            st = got.get(s)
            if st is None:
                filled += 1
                steps.append({"s": s, "type": t, "label": names.get(s) or t, "desc": ""})
                continue
            desc, n = scrub_time(st.get("desc"))
            scrubbed += n
            steps.append({"s": s, "type": t, "label": cut(st.get("label"), 20) or names.get(s) or t, "desc": desc})
        summary, n = scrub_time(ans.get("summary"))
        scrubbed += n
        out = {"role": as_text(ans.get("role")) or UNDECIDED_ROLE, "summary": summary, "steps": steps}
        if filled:
            out["filled_steps"] = filled
        if scrubbed:
            out["time_scrubbed"] = scrubbed
        return out

    def _step_names(self, it, ctx) -> dict:
        """S → 한글명(규칙 재료 ``step_names`` → 레지스트리 단계 유형 어휘 → 내장 표)."""
        given = rule_of(it).get("step_names")
        given = given if isinstance(given, dict) else {}
        reg = registry_of(ctx)
        out = {}
        for s, t, _c in _steps(fields_of(it).get("steps")):
            out[s] = as_text(given.get(s)) or vocab_name(reg, "step_types", t)
        return out

    # ── 폴백(B §8.4) ──
    def fallback(self, it, ctx, why: str = "") -> dict:
        f = fields_of(it)
        names = self._step_names(it, ctx)
        steps = [{"s": s, "type": t, "label": names.get(s) or t, "desc": ""} for s, t, _c in _steps(f.get("steps"))]
        func = as_text(rule_of(it).get("func_name")) or vocab_name(registry_of(ctx), "functions", f.get("func"))
        summary = ""
        if steps:
            summary = FALLBACK_SUMMARY_TEMPLATE.format(func=func or "-", first=steps[0]["label"],
                                                       last=steps[-1]["label"])
        return {"role": UNDECIDED_ROLE, "summary": summary, "steps": steps}
