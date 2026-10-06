# -*- coding: utf-8 -*-
r"""``taxonomy_consolidate`` — 과제 체계 2회차 통합 확인(**H §8.3 ``taxonomy_consolidate/1.0``**). 결과는 병합이 아니라
병합 근거 하나(H §9.3 'AI 통합 제안 +1.0')로만 쓴다 — ``conf ∈ {h, m}`` 인 쌍만(``lm27.hier.bootstrap.consolidate_pairs``).

ai_in(``lm27.hier.copilot_io.build_consolidate_items``): 1회차 ``code=""``·``kind ∈ {project, common}`` 행(≤ 15) + 이미 있는
``pending`` 제안(≤ 15) — 항목 ``{key: cs:…, fields{name, dom, match(≤3)}}``. 항목 줄 ``{n} | {이름} | {영역} | {알아볼 낱말}``.

답 ``{same_as, conf}`` — ``same_as`` = 같은 대상인 **이 질의 안의** 다른 항목 번호(0 = 없음, 자기 자신·범위 밖은 무효).
번호는 질의마다 다시 매겨지므로(반분·재질의) 정규화가 번호를 그 항목의 키로 옮겨 ``same_as_key`` 를 붙인다 — 하류는 키로
짝을 맞춘다(번호는 이 질의를 알 때만 뜻이 있다). 폴백 ``{same_as: 0, conf: l}``(묶지 않음 — H §8.3 '확실하지 않으면 묶지 않는다').

머리말 첫 줄의 '다른 이름으로 갈린 것' 은 정제기가 '이름으로' 뒤 낱말을 사람 이름으로 잡아 프롬프트 게이트가 단계를 멈추므로
'서로 다른 표기로 갈린 것' 으로 바꿨다(완료 보고 CR — WP-10 이름 문맥 규칙).
"""
from __future__ import annotations

from types import SimpleNamespace

from lm27.bridge.stages import as_text, current_batch, fields_of, key_of, remember_batch, str_list
from lm27.bridge.stages.base import TITLE_TEMPLATE, F, StageSpec

__all__ = ["TaxonomyConsolidate"]

CONFS = ("h", "m", "l")
MATCH_SHOWN = 3

CONSOLIDATE_HEAD_PROMPT = (
    "아래는 한 엔지니어의 업무를 분류하려고 초안으로 뽑은 '상위 과제' 목록입니다. 같은 대상이 서로 다른 표기로 갈린 것을 찾아 "
    "주세요.",
    "규칙:",
    "- 같은 제품·프로젝트의 축약·확장·한영 표기, 상위·하위로 겹치는 것만 같은 대상으로 봅니다.",
    "- 괄호 꼬리((양산)·(선행))나 차수·버전 숫자가 다르면 같은 대상이 아닙니다.",
    "- 확실하지 않으면 묶지 않습니다(same_as 를 0 으로).",
)
CONSOLIDATE_COLUMNS_PROMPT = "[항목] 번호 | 이름 | 영역 | 알아볼 낱말"
CONSOLIDATE_FORMAT_PROMPT = ('{"rid": <요청번호>, "n": <항목 수>, "items": [ {"id": <번호>, '
                             '"same_as": <같은 대상인 다른 항목 번호 또는 0>, "conf": <h|m|l>} ]}')
CONSOLIDATE_UNKNOWN_PROMPT = "same_as 는 0, conf 는 l 로 씁니다"


class TaxonomyConsolidate(StageSpec):
    id = "taxonomy_consolidate"
    title_ko = "과제 체계 통합 확인"
    prompt_ver = "taxonomy_consolidate/1.0"
    schema_major = 1
    kind = "items"
    model_class = "deep"
    chat_policy = "continue"
    max_items = 30
    min_split = 0
    est_out_per_item = 40
    group_strict = False
    send_fields = ("name", "dom", "match")
    text_fields = ("name", "match")
    content_key_fields = ("name", "dom", "match")
    item_schema = (F("same_as", "int"), F("conf", "enum", enum=CONFS))
    stub = {"same_as": 0, "conf": "l"}

    def title_line(self, rid, n, batch, ctx) -> str:
        remember_batch(self, ctx, batch)
        return TITLE_TEMPLATE.format(rid=rid, title=self.title_ko, n=n)

    def header(self, ctx, compact: bool = False) -> str:
        return "\n".join(CONSOLIDATE_HEAD_PROMPT)

    def columns(self) -> str:
        return CONSOLIDATE_COLUMNS_PROMPT

    def item_line(self, it, n) -> str:
        f = fields_of(it)
        return " | ".join([str(n), as_text(f.get("name")) or "-", as_text(f.get("dom")) or "-",
                           ", ".join(str_list(f.get("match"))[:MATCH_SHOWN]) or "-"])

    def format_line(self) -> str:
        return CONSOLIDATE_FORMAT_PROMPT

    def unknown_rule(self) -> str:
        return CONSOLIDATE_UNKNOWN_PROMPT

    def shrink(self, it, max_chars: int):
        nf = fields_of(it)
        nf["match"] = str_list(nf.get("match"))[:1]
        return nf if len(self.item_line(SimpleNamespace(fields=nf), 99)) <= max_chars else None

    def _batch_keys(self, ctx) -> list[str]:
        return [key_of(x) for x in current_batch(self, ctx)]

    def validate(self, ans: dict, it, ctx) -> str:
        """``same_as`` 는 0 또는 이 질의의 다른 항목 번호(자기 자신·범위 밖 무효)."""
        v = ans.get("same_as")
        if not isinstance(v, int) or v < 0:
            return "bad_pattern:same_as"
        keys = self._batch_keys(ctx)
        if v and keys:
            if v > len(keys) or keys[v - 1] == key_of(it):
                return "bad_pattern:same_as"
        return ""

    def normalize(self, ans: dict, it, ctx) -> dict:
        out = dict(ans)
        keys = self._batch_keys(ctx)
        v = out.get("same_as")
        if isinstance(v, int) and v > 0 and keys and v <= len(keys) and keys[v - 1] != key_of(it):
            out["same_as_key"] = keys[v - 1]
        return out

    def fallback(self, it, ctx, why: str = "") -> dict:
        return {"same_as": 0, "conf": "l"}
