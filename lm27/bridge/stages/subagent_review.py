# -*- coding: utf-8 -*-
r"""``subagent_review`` — 서브에이전트 도입 검토(B §8.7 · R §4.8 · R §13 B-1 → ``subagent_review/1.1`` · X-256).

ai_in(R §4.10.1 — ``lm27.report.analysis.ai_items.subagent_items``): 역할 업무 1개 = 항목 1개, 키 ``sa:<role_id>``, ``group``
= 과제 키, 필드 ``project`` · ``role``(코파일럿 역할 한 줄, 없으면 '분야·기능') · ``steps[[S, 단계 라벨, 단계 유형, 플래그]]``.
플래그 글자 ``"D1 R1 B0 L1 S1 T1"`` 은 프로그램이 계산한다(R §4.8.2 — D 디지털 입출력 · R 주 1회 이상 반복 · B 규칙 판단 가능 ·
L 책임 낮고 되돌리기 쉬움 · S 다음 단계 입력 정형 · **T 도구 접근** — B-1 로 추가, 머리말 설명 줄 1줄, 내용 키 주판 그대로).

답 ``{verdict(적합|부분|부적합), orch, subs[{steps[S…], role, io, check}] ≤4, risk}``. 정규화: ``subs[].steps`` 가 입력 S 밖이면
그 sub 를 버리고(셈), ``verdict == 부적합`` 이면 ``subs`` 를 비운다(셈). 최종 판정은 보고서 분석층이 규칙 판정과 더 보수적인
쪽으로 정한다(R §4.8.3 — 코파일럿이 규칙의 하드 조건을 넘지 못한다).

폴백(B §8.7 규칙): 단계마다 플래그 합 ≥ ``CAND_FLAGS`` → '서브에이전트 후보'. 후보 단계 비율 ≥ 0.5 → 적합, > 0 → 부분,
0 → 부적합. ``subs`` = 이어진 후보 단계 묶음마다 1개(``role`` = 단계 라벨을 이은 것, ``io`` = '첫 유형 → 끝 유형',
``check`` = '결과 검토'), ``orch`` = '{역할} 흐름 조율', ``risk`` = ``RULE_RISK``.

나눠 가진 목록 글(단계 라벨)은 정제 게이트의 텍스트 필드로 넘길 수 없는 중첩 목록이라, 웹 노출이면 이 단계가 줄을 만들 때
엄격 규칙 S1·S2 를 직접 적용한다(``lm27.bridge.stages.web_plain`` — 번호 토큰이 프롬프트에 남아 S5 로 단계가 멈추지 않게).
"""
from __future__ import annotations

import re
from types import SimpleNamespace

from lm27.bridge.stages import as_text, cut, fields_of, remember_batch, remembered_ctx, web_exposed, web_plain
from lm27.bridge.stages.base import F, StageSpec

__all__ = ["CAND_FLAGS", "RULE_RISK", "SubagentReview"]

VERDICTS = ("적합", "부분", "부적합")
CAND_FLAGS = 4
FIT_SHARE = 0.5
SUBS_MAX = 4
RULE_CHECK = "결과 검토"
RULE_RISK = "규칙 판정 — 사람 검토 필요"
RULE_ORCH_TEMPLATE = "{role} 흐름 조율"
S_RX = re.compile(r"^S\d{1,2}$")
FLAG_RX = re.compile(r"\b([DRBLST])([01])\b")

SUBAGENT_HEAD_PROMPT = (
    "당신은 업무 흐름에 AI 서브에이전트를 넣을 수 있는지 검토합니다. 각 항목은 한 역할 업무의 단계 흐름과, 단계마다 프로그램이 "
    "확인한 조건 플래그입니다.",
    "플래그: D=입출력이 디지털, R=주 1회 이상 반복, B=규칙으로 판단 가능, L=책임이 낮고 되돌리기 쉬움, S=다음 단계 입력이 정형 "
    "(1=해당, 0=아님)",
    "T=그 단계에서 쓰는 도구를 프로그램이 다룰 수 있음 (1=해당, 0=아님)",
    "항목마다 다음을 씁니다.",
    "- verdict : 적합 / 부분 / 부적합",
    '- orch : 전체를 조율하는 오케스트레이터가 맡을 일(60자 이내). 부적합이면 "".',
    "- subs : 서브에이전트 구성 최대 4개. 각각 steps(맡을 단계 코드 목록), role(40자 이내), io(입력→출력 60자 이내), "
    "check(사람이 확인할 지점 40자 이내). 부적합이면 빈 목록.",
    "- risk : 도입 시 주의점(80자 이내)",
    "규칙: 주어진 단계 코드만 씁니다. 플래그가 대부분 0 인 단계는 사람 몫으로 둡니다. 절감 시간이나 MM 은 쓰지 않습니다.",
)
SUBAGENT_COLUMNS_PROMPT = "[항목] 번호 | 과제 · 역할 | 단계(코드 라벨 유형 플래그)"
SUBAGENT_FORMAT_PROMPT = ('{"rid": <요청번호>, "n": <항목 수>, "items": [ {"id": <번호>, "verdict": <적합|부분|부적합>, '
                          '"orch": <한 줄>, "subs": [ {"steps": [<단계 코드>], "role": <역할>, "io": <입력→출력>, '
                          '"check": <확인 지점>} ], "risk": <주의점>} ]}')
SUBAGENT_UNKNOWN_PROMPT = "verdict 는 부분, subs 는 빈 목록으로 씁니다"


def _steps(v) -> list[tuple[str, str, str, str]]:
    """입력 ``steps`` → [(S, 라벨, 유형, 플래그 글자)]."""
    out = []
    for x in v or ():
        if isinstance(x, (list, tuple)) and len(x) >= 3 and S_RX.match(as_text(x[0])):
            out.append((as_text(x[0]), as_text(x[1]), as_text(x[2]), as_text(x[3]) if len(x) > 3 else ""))
    return out


def flag_sum(flags: str) -> int:
    """플래그 글자 ``"D1 R1 B0 L1 S1 T1"`` 의 1 개수."""
    return sum(int(v) for _k, v in FLAG_RX.findall(flags or ""))


class SubagentReview(StageSpec):
    id = "subagent_review"
    title_ko = "서브에이전트 도입 검토"
    prompt_ver = "subagent_review/1.1"
    schema_major = 1
    kind = "items"
    model_class = "deep"
    chat_policy = "continue"
    max_items = 5
    min_split = 1
    est_out_per_item = 600
    group_strict = False
    send_fields = ("project", "role", "steps")
    text_fields = ("role",)
    content_key_fields = ("project", "role", "steps")
    item_schema = (F("verdict", "enum", enum=VERDICTS),
                   F("orch", "str", required=False, max_len=60, hard_max=160),
                   F("subs", "list", required=False, max_items=SUBS_MAX,
                     item=(F("steps", "list", max_items=8), F("role", "str", required=False, max_len=40, hard_max=120),
                           F("io", "str", required=False, max_len=60, hard_max=160),
                           F("check", "str", required=False, max_len=40, hard_max=120))),
                   F("risk", "str", required=False, max_len=80, hard_max=200))
    stub = {"verdict": "부분", "orch": "", "subs": [], "risk": "사람 검토 필요"}

    # ── 프롬프트 ──
    def header(self, ctx, compact: bool = False) -> str:
        return "\n".join(SUBAGENT_HEAD_PROMPT)

    def columns(self) -> str:
        return SUBAGENT_COLUMNS_PROMPT

    def item_line(self, it, n) -> str:
        f = fields_of(it)
        plain = web_exposed(remembered_ctx(self))
        steps = []
        for s, label, t, flags in _steps(f.get("steps")):
            lab = web_plain(label) if plain else label
            steps.append(f"{s} {lab}({t}) [{flags}]")
        role = as_text(f.get("role"))
        return f"{n} | {as_text(f.get('project')) or '-'} · {role or '-'} | " + (" → ".join(steps) or "-")

    def title_line(self, rid, n, batch, ctx) -> str:
        remember_batch(self, ctx, batch)        # 항목 줄의 웹 노출 판단(그 질의의 문맥)
        return super().title_line(rid, n, batch, ctx)

    def format_line(self) -> str:
        return SUBAGENT_FORMAT_PROMPT

    def unknown_rule(self) -> str:
        return SUBAGENT_UNKNOWN_PROMPT

    def shrink(self, it, max_chars: int):
        """단계 라벨을 8자로 → 그래도 크면 None."""
        nf = fields_of(it)
        nf["steps"] = [[s, cut(label, 8), t, flags] for s, label, t, flags in _steps(nf.get("steps"))]
        return nf if len(self.item_line(SimpleNamespace(fields=nf), 99)) <= max_chars else None

    # ── 정규화(B §8.7 validate) ──
    def normalize(self, ans: dict, it, ctx) -> dict:
        codes = {s for s, _l, _t, _f in _steps(fields_of(it).get("steps"))}
        verdict = ans.get("verdict")
        subs, bad = [], 0
        for sub in ans.get("subs") or ():
            st = [as_text(x) for x in sub.get("steps") or ()]
            if not st or any(x not in codes for x in st):
                bad += 1
                continue
            subs.append({"steps": st, "role": as_text(sub.get("role")), "io": as_text(sub.get("io")),
                         "check": as_text(sub.get("check"))})
        cleared = 0
        if verdict == "부적합" and subs:
            cleared = len(subs)
            subs = []
        out = {"verdict": verdict, "orch": "" if verdict == "부적합" else as_text(ans.get("orch")), "subs": subs,
               "risk": as_text(ans.get("risk"))}
        if bad:
            out["bad_subs"] = bad
        if cleared:
            out["cleared_subs"] = cleared
        return out

    # ── 폴백(B §8.7 규칙) ──
    def fallback(self, it, ctx, why: str = "") -> dict:
        f = fields_of(it)
        steps = _steps(f.get("steps"))
        cand = [flag_sum(flags) >= CAND_FLAGS for _s, _l, _t, flags in steps]
        share = (sum(cand) / len(cand)) if cand else 0.0
        verdict = "적합" if share >= FIT_SHARE else ("부분" if share > 0 else "부적합")
        subs, run = [], []
        for (s, label, t, _flags), c in zip(steps, cand, strict=True):
            if c:
                run.append((s, label, t))
                continue
            if run:
                subs.append(run)
                run = []
        if run:
            subs.append(run)
        role = as_text(f.get("role")) or "-"
        out_subs = [{"steps": [s for s, _l, _t in r], "role": cut(" · ".join(lb for _s, lb, _t in r if lb), 40),
                     "io": f"{r[0][2]} → {r[-1][2]}", "check": RULE_CHECK} for r in subs][:SUBS_MAX]
        if verdict == "부적합":
            out_subs = []
        return {"verdict": verdict, "orch": "" if verdict == "부적합" else cut(RULE_ORCH_TEMPLATE.format(role=role), 60),
                "subs": out_subs, "risk": RULE_RISK}
