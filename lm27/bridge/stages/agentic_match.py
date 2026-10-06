# -*- coding: utf-8 -*-
r"""``agentic_match`` — Agentic AI 매칭과 새 니즈(B §8.6 · R §4.7 · §4.10 · X-255).

ai_in(R §4.10.1 — ``lm27.report.analysis.ai_items.agentic_items``): 단계 유형 1개 = 항목 1개, 키 ``ag:<유형>``, 필드
``type · label(≤20) · freq(등급 문구) · io(≤30) · apps(≤30) · ws(≤4)``. ``freq`` 는 빈도 **등급**이지 시간이 아니다(B1).

머리말의 ``[에이전트 목록]`` = 팀 레지스트리 ``agents[]`` 중 running·planned — **코드 · ``copilot_desc`` · 입력 → 출력 ·
적용 단계 유형만** 싣는다(X-255: 이름·``desc`` 는 보내지 않는다 — 사내 과제 이름이 들어가기 쉽다, H §2.3.6). 목록이 커서
축약(``compact``)이면 이 묶음 단계 유형에 맞는 에이전트만(상한 ``COMPACT_AGENTS_MAX`` — 빈 묶음 예산 계산은 가장 긴 줄 그만큼).

답 ``{m[{a, fit, why}] ≤3, need{name, logic, in, out}|null}`` — ``a`` 는 카탈로그 코드만(running·planned). 정규화: ``m`` 의 같은
``a`` 는 첫 것만(셈), ``need.name`` 이 카탈로그 이름과 ukey 로 같으면 ``need`` 를 버린다(``need_dup_catalog`` 셈). 폴백
(B §8.6): 적용 단계 유형에 ``type`` 이 든 에이전트를 ``fit="중"``·``why=RULE_WHY`` 로 최대 3개, ``need=null``.
절감 시간·MM 은 묻지도 받지도 않는다.
"""
from __future__ import annotations

from types import SimpleNamespace

from lm27.bridge.stages import agents_of, as_text, current_batch, cut, fields_of, remember_batch, str_list
from lm27.bridge.stages.base import TITLE_TEMPLATE, F, StageSpec, registry_codes

__all__ = ["AgenticMatch", "RULE_WHY"]

FITS = ("상", "중", "하")
RULE_FIT = "중"
RULE_WHY = "단계 유형 일치(규칙)"
M_MAX = 3
COMPACT_AGENTS_MAX = 20
NO_DESC = "(설명 없음)"

AGENTIC_HEAD_PROMPT = (
    "당신은 업무 자동화(Agentic AI) 기획 분석가입니다. [에이전트 목록]은 팀이 운영하거나 계획한 에이전트이고, [항목]은 "
    "한 사람의 업무 단계(단계 유형별)입니다.",
    "항목마다 다음을 씁니다.",
    "- m : 이 단계를 대신하거나 도울 수 있는 에이전트 최대 3개. 각각 a(에이전트 코드), fit(상: 지금 바로 대부분 대신 / "
    "중: 사람 확인을 곁들여 보조 / 하: 일부만 보조), why(근거 40자 이내). 맞는 것이 없으면 빈 목록.",
    "- need : 목록에 없지만 이 단계에 필요한 새 에이전트가 분명하면 name(20자 이내)·logic(무엇을 입력받아 무엇을 자동으로 "
    "하는지 80자 이내)·in(입력 40자 이내)·out(출력 40자 이내). 없으면 null.",
    "규칙: 절감 시간이나 MM 같은 수치는 쓰지 않습니다. 억지로 맞추지 않습니다.",
)
AGENTIC_LIST_PROMPT = "[에이전트 목록] 코드 · 설명 · 입력 → 출력 · 적용 단계 유형"
AGENTIC_EMPTY_PROMPT = "(없음)"
AGENTIC_COMPACT_PROMPT = "(목록은 이번 항목의 단계 유형에 맞는 에이전트만 보입니다)"
AGENTIC_COLUMNS_PROMPT = "[항목] 번호 | 단계 유형 | 대표 라벨 | 빈도 | 입출력 | 앱 | 쓰이는 역할 업무"
AGENTIC_FORMAT_PROMPT = ('{"rid": <요청번호>, "n": <항목 수>, "items": [ {"id": <번호>, "m": [ {"a": <에이전트 코드>, '
                         '"fit": <상|중|하>, "why": <근거>} ], "need": <null 또는 {"name": <이름>, "logic": <로직>, '
                         '"in": <입력>, "out": <출력>}>} ]}')
AGENTIC_UNKNOWN_PROMPT = "m 은 빈 목록, need 는 null 로 씁니다"


def agent_line(a: dict) -> str:
    """에이전트 한 줄 — 코드 · copilot_desc · 입력 → 출력 · 적용 단계 유형(X-255)."""
    ins = "·".join(a.get("inputs") or ()) or "-"
    outs = "·".join(a.get("outputs") or ()) or "-"
    types = ", ".join(a.get("step_types") or ()) or "-"
    return f"{a['id']} · {a.get('copilot_desc') or NO_DESC} · {ins} → {outs} · {types}"


class AgenticMatch(StageSpec):
    id = "agentic_match"
    title_ko = "Agentic AI 매칭·새 니즈"
    prompt_ver = "agentic_match/1.0"
    schema_major = 1
    kind = "items"
    model_class = "deep"
    chat_policy = "continue"
    max_items = 15
    min_split = 5
    est_out_per_item = 260
    group_strict = False
    send_fields = ("type", "label", "freq", "io", "apps", "ws")
    text_fields = ("label", "apps", "ws")
    content_key_fields = ("type", "label", "freq", "io", "apps", "ws")
    uses_registry = True
    item_schema = (F("m", "list", max_items=M_MAX,
                     item=(F("a", "code", codes="catalog"), F("fit", "enum", enum=FITS),
                           F("why", "str", required=False, max_len=40, hard_max=120))),
                   F("need", "nullable_obj", required=False,
                     item=(F("name", "str", min_len=2, max_len=20, hard_max=60),
                           F("logic", "str", required=False, max_len=80, hard_max=200),
                           F("in", "str", required=False, max_len=40, hard_max=120),
                           F("out", "str", required=False, max_len=40, hard_max=120))))
    stub = {"m": [], "need": None}

    # ── 프롬프트 ──
    def title_line(self, rid, n, batch, ctx) -> str:
        remember_batch(self, ctx, batch)
        return TITLE_TEMPLATE.format(rid=rid, title=self.title_ko, n=n)

    def header(self, ctx, compact: bool = False) -> str:
        agents = agents_of(ctx)
        lines = list(AGENTIC_HEAD_PROMPT) + [AGENTIC_LIST_PROMPT]
        if compact:
            agents = self._compact(agents, current_batch(self, ctx))
        lines += [agent_line(a) for a in agents] or [AGENTIC_EMPTY_PROMPT]
        if compact:
            lines.append(AGENTIC_COMPACT_PROMPT)
        return "\n".join(lines)

    @staticmethod
    def _compact(agents: list, batch) -> list:
        """이 묶음 단계 유형에 맞는 에이전트(상한) — 빈 묶음(예산 계산)이면 줄이 가장 긴 상한 개(어떤 묶음보다 길거나 같다)."""
        if batch:
            types = {as_text(fields_of(it).get("type")) for it in batch}
            return [a for a in agents if types & set(a.get("step_types") or ())][:COMPACT_AGENTS_MAX]
        longest = sorted(agents, key=lambda a: (-len(agent_line(a)), a["id"]))[:COMPACT_AGENTS_MAX]
        return sorted(longest, key=lambda a: a["id"])

    def columns(self) -> str:
        return AGENTIC_COLUMNS_PROMPT

    def item_line(self, it, n) -> str:
        f = fields_of(it)
        return " | ".join([str(n), as_text(f.get("type")), as_text(f.get("label")) or "-", as_text(f.get("freq")) or "-",
                           as_text(f.get("io")) or "-", as_text(f.get("apps")) or "-",
                           ", ".join(str_list(f.get("ws"))) or "-"])

    def format_line(self) -> str:
        return AGENTIC_FORMAT_PROMPT

    def unknown_rule(self) -> str:
        return AGENTIC_UNKNOWN_PROMPT

    def shrink(self, it, max_chars: int):
        nf = fields_of(it)
        nf["ws"] = str_list(nf.get("ws"))[:2]
        if len(self.item_line(SimpleNamespace(fields=nf), 99)) <= max_chars:
            return nf
        nf["ws"] = []
        return nf if len(self.item_line(SimpleNamespace(fields=nf), 99)) <= max_chars else None

    # ── 검증·정규화 ──
    def code_sets(self, ctx) -> dict:
        """카탈로그 코드 = running·planned 에이전트만(퇴역 코드는 답에서 무효)."""
        out = dict(registry_codes(getattr(ctx, "registry", None)))
        out["catalog"] = frozenset(a["id"] for a in agents_of(ctx))
        return out

    def normalize(self, ans: dict, it, ctx) -> dict:
        seen, m, dup = set(), [], 0
        for x in ans.get("m") or ():
            a = x.get("a")
            if a in seen:
                dup += 1
                continue
            seen.add(a)
            m.append({"a": a, "fit": x.get("fit"), "why": as_text(x.get("why"))})
        need = ans.get("need")
        dropped_need = False
        if isinstance(need, dict):
            from lm27.hier.names import ukey
            names = {ukey(a.get("name")) for a in agents_of(ctx) if a.get("name")}
            if ukey(as_text(need.get("name"))) in names:
                need, dropped_need = None, True
            else:
                need = {"name": as_text(need.get("name")), "logic": as_text(need.get("logic")),
                        "in": as_text(need.get("in")), "out": as_text(need.get("out"))}
        out = {"m": m, "need": need if isinstance(need, dict) else None}
        if dup:
            out["dup_agents"] = dup
        if dropped_need:
            out["need_dup_catalog"] = 1
        return out

    # ── 폴백(B §8.6) ──
    def fallback(self, it, ctx, why: str = "") -> dict:
        t = as_text(fields_of(it).get("type"))
        m = [{"a": a["id"], "fit": RULE_FIT, "why": cut(RULE_WHY, 40)} for a in agents_of(ctx)
             if t and t in (a.get("step_types") or ())][:M_MAX]
        return {"m": m, "need": None}
