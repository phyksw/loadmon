# -*- coding: utf-8 -*-
r"""``speech_act`` — 화행 분류 보조(B §8.2). 정규화 단계의 규칙 화행 분류기가 회색 지대라고 표시한 메시지만 온다.

ai_in ``{key: "msg:…", fields: {ch, dir, chat, prev, text}, rule: {act, score}}`` — ``text`` 는 정제본 요지 ≤ 120자.
답 ``{act, conf}``. 하류(에피소드 페어링)는 ``by=ai`` 이고 ``conf ∈ {h, m}`` 일 때만 규칙 판정을 덮는다(``l`` 은 참고만).
폴백 = ``{act: 규칙 화행(없으면 info), conf: l}``. 문구는 B §8.2 글자 그대로.
"""
from __future__ import annotations

from types import SimpleNamespace

from lm27.bridge.stages import as_text, fields_of, rule_of
from lm27.bridge.stages.base import F, StageSpec

__all__ = ["ACTS", "SpeechAct"]

ACTS = ("request", "ack", "question", "report", "info", "social", "notice")
CONFS = ("h", "m", "l")
SHRINK_TEXT = 60

SPEECH_ACT_HEAD_PROMPT = (
    "당신은 업무 메시지의 말하기 의도(화행)를 분류합니다. 각 메시지를 읽고 아래 7가지 중 하나를 고르세요.",
    "- request : 나에게 일을 맡기거나 요청·지시·검토를 부탁함 (예: ~해 주세요, ~까지 부탁드립니다)",
    "- ack : 요청을 받아들이거나 확인함 (예: 네 알겠습니다, 확인했습니다)",
    "- question : 정보를 묻지만 일을 맡기지는 않음",
    "- report : 결과·완료·송부·공유를 알림 (예: 송부드립니다, 완료했습니다, 결과 공유드립니다)",
    "- info : 그 밖의 업무 대화·정보 전달",
    "- social : 인사·감사·잡담 등 업무 내용이 없는 말",
    "- notice : 여러 사람에게 보내는 공지·안내·자동 알림",
    "규칙: 메시지에 쓰인 것만 보고 판단합니다. 방향이 out 이면 내가 보낸 말입니다. 확신이 낮으면 conf 를 l 로 씁니다.",
)
SPEECH_ACT_COLUMNS_PROMPT = "[항목] 번호 | 채널 | 방향 | 대화 | 앞 화행 | 내용"
SPEECH_ACT_FORMAT_PROMPT = ('{"rid": <요청번호>, "n": <항목 수>, "items": [ {"id": <번호>, '
                            '"act": <request|ack|question|report|info|social|notice>, "conf": <h|m|l>} ]}')
SPEECH_ACT_UNKNOWN_PROMPT = "act 는 info, conf 는 l 로 씁니다"


class SpeechAct(StageSpec):
    id = "speech_act"
    title_ko = "화행 분류"
    prompt_ver = "speech_act/1.0"
    schema_major = 1
    kind = "items"
    model_class = "fast"
    chat_policy = "continue"
    max_items = 40
    min_split = 5
    est_out_per_item = 45
    send_fields = ("ch", "dir", "chat", "prev", "text")
    text_fields = ("text",)
    content_key_fields = ("ch", "dir", "chat", "text")
    item_schema = (F("act", "enum", enum=ACTS), F("conf", "enum", enum=CONFS))
    stub = {"act": "info", "conf": "m"}

    def header(self, ctx, compact: bool = False) -> str:
        return "\n".join(SPEECH_ACT_HEAD_PROMPT)

    def columns(self) -> str:
        return SPEECH_ACT_COLUMNS_PROMPT

    def item_line(self, it, n) -> str:
        f = fields_of(it)
        return " | ".join([str(n), as_text(f.get("ch")), as_text(f.get("dir")), as_text(f.get("chat")),
                           as_text(f.get("prev")) or "-", as_text(f.get("text"))])

    def format_line(self) -> str:
        return SPEECH_ACT_FORMAT_PROMPT

    def unknown_rule(self) -> str:
        return SPEECH_ACT_UNKNOWN_PROMPT

    def shrink(self, it, max_chars: int):
        """``text`` 를 60자로 → 그래도 크면 None(oversize)(B §8.2)."""
        nf = fields_of(it)
        nf["text"] = as_text(nf.get("text"))[:SHRINK_TEXT]
        return nf if len(self.item_line(SimpleNamespace(fields=nf), 99)) <= max_chars else None

    def fallback(self, it, ctx, why: str = "") -> dict:
        a = rule_of(it).get("act")
        return {"act": a if a in ACTS else "info", "conf": "l"}
