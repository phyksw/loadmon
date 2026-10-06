# -*- coding: utf-8 -*-
r"""``review_text`` — 주간·월간 리뷰 문장(B §8.5 · R §4.4 · §4.10). 기간 1개 = 항목 1개 = 질의 1건(새 채팅, 단건형).

ai_in(R §4.10.1 — ``lm27.report.analysis.ai_items.review_items``): 키 ``review:week:YYYY-Www`` · ``review:month:YYYY-MM``,
필드 ``kind(week|month) · period · facts[[F번호, 상태, 단위업무 이름, 과제 ID, 기능 한글명]] ≤25 · peers[[동료k, 함께 한
단위업무 수]] ≤8 · edges[[E번호, 출발, 관계, 도착]] ≤12(달만)``, 규칙 재료 ``rule{peers_map{동료k: who_key}, fact_units}``.
번호표 ``동료1``… 은 이 질의에서만 쓰는 이름이고 who_key 대응은 보내지 않는다(B §9.3) — 정규화·폴백이 답에 ``peers_map`` 을
붙여 둔다(개인 보고서 렌더러가 로컬 사람 사전으로 푼다, 팀 묶음에는 리뷰 문장을 싣지 않는다).

프롬프트(B §8.5 글자 그대로): 머리말에 ``[사실 목록]``·``[함께 한 동료]``·``[관계](월간만)`` 가 들어가므로 ``title_line`` 이
묶음(항목 1개)을 기억해 둔다. ``[항목]`` 줄은 ``1 | {period}`` 한 줄. 사실·관계 글은 정제 게이트의 텍스트 필드로 넘길 수 없는
중첩 목록이라 웹 노출이면 이 단계가 엄격 규칙 S1·S2 를 직접 적용하고(번호 토큰 → 종류 토큰), S3(금액 + 고객사) 사실·관계는
글을 ``-`` 로 비운다(완료 보고 CR — 게이트가 중첩 목록 글을 다루게).

답 ``{summary, highlights[{text, refs[F…]}] ≤5, relations[{text, refs[E…]}] ≤3, next[] ≤3}``. 정규화: ``refs`` 가 입력 번호가
아니면 그 하이라이트·관계를 버리고(셈), 하이라이트가 모두 버려지고 요약도 비면 무효. 문장 안의 번호표(``동료`` + 숫자)는
``peers`` 에 있는 것만(아니면 ``동료``). 시간·공수·MM·퍼센트 숫자 표현이 든 문장은 지운다(B1). 폴백 = 결정적 템플릿
(``FALLBACK_SUMMARY_TEMPLATE`` — 보고서는 이 문장을 다시 쓰지 않는다, RPT-29 · G-R12).
"""
from __future__ import annotations

import re
from collections import Counter

from lm27.bridge.stages import (as_text, current_batch, cut, fields_of, remember_batch, rule_of, scrub_time,
                                web_combo, web_exposed, web_plain)
from lm27.bridge.stages.base import F, StageSpec

__all__ = ["FALLBACK_SUMMARY_TEMPLATE", "ReviewText"]

KIND_KO = {"week": "주간", "month": "월간"}
PERIOD_KO = {"week": "주", "month": "달"}
FACTS_MAX = 25
PEERS_MAX = 8
EDGES_MAX = 12
EST_WEEK = 1200
EST_MONTH = 1800
DONE, DOING = "완료", "진행"
PEER_TAG_RX = re.compile(r"동료(\d+)")
_F_RX = re.compile(r"^F\d{1,3}$")
_E_RX = re.compile(r"^E\d{1,3}$")

REVIEW_TITLE_TEMPLATE = "[LM27 요청 {rid} · {kind_ko} 리뷰 문장 · {period}]"
REVIEW_HEAD_TEMPLATE = (
    "당신은 한 엔지니어의 {kind_ko} 업무 리뷰를 씁니다. 아래 [사실 목록]은 프로그램이 기록에서 확정한 것입니다. 이 목록에 있는 "
    "사실만 씁니다.",
    "쓸 것:",
    "- summary : 이 기간의 업무를 3~4문장으로 요약(300자 이내)",
    '- highlights : 중요한 일 최대 5개. 각각 text(80자 이내)와 근거 refs(사실 번호 목록, 예 ["F1","F3"])',
    '- relations : (월간만) 과제·업무·산출물·동료 사이의 연관 최대 3개. 각각 text(80자 이내)와 refs(관계 번호 목록, 예 ["E2"])',
    "- next : 다음 기간에 이어질 일 최대 3개(각 60자 이내). '진행'·'시작' 상태 사실에서만 고릅니다",
    "규칙: 시간·공수·MM·퍼센트 같은 숫자는 쓰지 않습니다(프로그램이 따로 붙입니다). 사람은 동료1·동료2 같은 번호표만 씁니다. "
    "목록에 없는 일을 지어내지 않습니다.",
)
REVIEW_FACTS_PROMPT = "[사실 목록] 번호 | 상태 | 단위업무 | 과제 | 기능"
REVIEW_PEERS_TEMPLATE = "{tag} — 함께 한 단위업무 {n}건"
REVIEW_PEERS_HEAD_PROMPT = "[함께 한 동료]"
REVIEW_EDGES_HEAD_PROMPT = "[관계]"
REVIEW_NONE_PROMPT = "없음"
REVIEW_COLUMNS_PROMPT = "[항목] 번호 | 기간"
REVIEW_FORMAT_PROMPT = ('{"rid": <요청번호>, "n": 1, "items": [ {"id": 1, "summary": <요약>, "highlights": [ {"text": <문장>, '
                        '"refs": [<F번호>]} ], "relations": [ {"text": <문장>, "refs": [<E번호>]} ], "next": [<문장>]} ]}')
REVIEW_UNKNOWN_PROMPT = "사실이 적으면 summary 를 짧게 쓰고 highlights 를 빈 목록으로 둡니다"
FALLBACK_SUMMARY_TEMPLATE = "이번 {period}에는 {done}건을 마쳤고 {doing}건을 진행했습니다."
FALLBACK_PROJECTS_TEMPLATE = " 주요 과제는 {projects}입니다."


def _rows(v, n: int, width: int) -> list[list[str]]:
    out = []
    for x in v or ():
        if isinstance(x, (list, tuple)) and x:
            r = [as_text(y) for y in x][:width]
            out.append(r + [""] * (width - len(r)))
    return out[:n]


def _kind(f: dict) -> str:
    k = as_text(f.get("kind"))
    return k if k in KIND_KO else "week"


class ReviewText(StageSpec):
    id = "review_text"
    title_ko = "리뷰 문장"
    prompt_ver = "review_text/1.0"
    schema_major = 1
    kind = "single"
    model_class = "deep"
    chat_policy = "fresh_each"
    max_items = 1
    est_out_per_item = EST_WEEK
    group_strict = False
    send_fields = ("kind", "period", "facts", "peers", "edges")
    text_fields = ("period",)
    content_key_fields = ("kind", "period", "facts", "peers", "edges")
    item_schema = (F("summary", "str", max_len=300, hard_max=800),
                   F("highlights", "list", max_items=5,
                     item=(F("text", "str", max_len=80, hard_max=200), F("refs", "list", max_items=6))),
                   F("relations", "list", required=False, max_items=3,
                     item=(F("text", "str", max_len=80, hard_max=200), F("refs", "list", max_items=6))),
                   F("next", "list", required=False, max_items=3))
    stub = {"summary": "이번 기간의 업무를 정리했습니다.", "highlights": [], "relations": [], "next": []}

    # ── 프롬프트 ──
    def title_line(self, rid, n, batch, ctx) -> str:
        remember_batch(self, ctx, batch)
        f = fields_of(batch[0]) if batch else {}
        return REVIEW_TITLE_TEMPLATE.format(rid=rid, kind_ko=KIND_KO[_kind(f)], period=as_text(f.get("period")) or "-")

    def header(self, ctx, compact: bool = False) -> str:
        batch = current_batch(self, ctx)
        f = fields_of(batch[0]) if batch else {}
        kind = _kind(f)
        plain = web_exposed(ctx)
        lines = [t.format(kind_ko=KIND_KO[kind]) for t in REVIEW_HEAD_TEMPLATE]
        lines.append(REVIEW_FACTS_PROMPT)
        for fid, state, title, proj, func in _rows(f.get("facts"), FACTS_MAX, 5):
            lines.append(" | ".join([fid, state, self._text(title, plain), proj or "-", func or "-"]))
        peers = [REVIEW_PEERS_TEMPLATE.format(tag=t, n=n or "0") for t, n in _rows(f.get("peers"), PEERS_MAX, 2)]
        lines.append(REVIEW_PEERS_HEAD_PROMPT + " " + (" · ".join(peers) or REVIEW_NONE_PROMPT))
        if kind == "month":
            lines.append(REVIEW_EDGES_HEAD_PROMPT)
            for eid, a, rel, b in _rows(f.get("edges"), EDGES_MAX, 4):
                lines.append(f"{eid} {self._text(a, plain)} —{rel}→ {self._text(b, plain)}")
        return "\n".join(lines)

    @staticmethod
    def _text(s: str, plain: bool) -> str:
        """중첩 목록 글의 웹 노출 엄격 규칙(B §9.7 S1·S2·S3) — 게이트의 텍스트 필드가 아니어서 여기서."""
        s = as_text(s)
        if not plain:
            return s or "-"
        if web_combo(s):
            return "-"
        return web_plain(s) or "-"

    def columns(self) -> str:
        return REVIEW_COLUMNS_PROMPT

    def item_line(self, it, n) -> str:
        return f"{n} | {as_text(fields_of(it).get('period')) or '-'}"

    def format_line(self) -> str:
        return REVIEW_FORMAT_PROMPT

    def unknown_rule(self) -> str:
        return REVIEW_UNKNOWN_PROMPT

    def est_out(self, it) -> int:
        return EST_MONTH if _kind(fields_of(it)) == "month" else EST_WEEK

    # ── 검증·정규화(B §8.5) ──
    def validate(self, ans: dict, it, ctx) -> str:
        cleaned = self._clean(ans, it)
        if not cleaned["highlights"] and not cleaned["summary"]:
            return "bad_pattern:highlights"
        return ""

    def normalize(self, ans: dict, it, ctx) -> dict:
        return self._clean(ans, it)

    def _clean(self, ans: dict, it) -> dict:
        f = fields_of(it)
        fids = {r[0] for r in _rows(f.get("facts"), FACTS_MAX, 5) if _F_RX.match(r[0])}
        eids = {r[0] for r in _rows(f.get("edges"), EDGES_MAX, 4) if _E_RX.match(r[0])}
        tags = {r[0] for r in _rows(f.get("peers"), PEERS_MAX, 2)}
        counts: Counter = Counter()

        def text(s, n):
            t, k = scrub_time(s)
            counts["time_scrubbed"] += k
            fixed = PEER_TAG_RX.sub(lambda m: m.group(0) if m.group(0) in tags else "동료", t)
            if fixed != t:
                counts["peer_tag_fixed"] += 1
            return cut(fixed, n)

        def refs_ok(refs, allowed):
            rs = [as_text(x) for x in refs or ()]
            return rs if rs and all(r in allowed for r in rs) else None

        hl = []
        for h in ans.get("highlights") or ():
            rs = refs_ok(h.get("refs"), fids)
            if rs is None:
                counts["bad_refs"] += 1
                continue
            t = text(h.get("text"), 80)
            if t:
                hl.append({"text": t, "refs": rs})
        rel = []
        for r in ans.get("relations") or ():
            rs = refs_ok(r.get("refs"), eids)
            if rs is None:
                counts["bad_refs"] += 1
                continue
            t = text(r.get("text"), 80)
            if t:
                rel.append({"text": t, "refs": rs})
        nxt = [t for t in (text(x, 60) for x in ans.get("next") or ()) if t][:3]
        out = {"summary": text(ans.get("summary"), 300), "highlights": hl, "relations": rel, "next": nxt,
               "peers_map": self._peers_map(it)}
        for k, v in sorted(counts.items()):
            if v:
                out[k] = int(v)
        return out

    @staticmethod
    def _peers_map(it) -> dict:
        pm = rule_of(it).get("peers_map")
        return {str(k): str(v) for k, v in sorted(pm.items())} if isinstance(pm, dict) else {}

    # ── 폴백(B §8.5 결정적 템플릿) ──
    def fallback(self, it, ctx, why: str = "") -> dict:
        f = fields_of(it)
        facts = _rows(f.get("facts"), FACTS_MAX, 5)
        done = [r for r in facts if r[1] == DONE]
        doing = [r for r in facts if r[1] == DOING]
        cnt = Counter(r[3] for r in facts if r[3] and r[3] not in ("-", "NONE", "NEW"))
        top = [p for p, _n in sorted(cnt.items(), key=lambda kv: (-kv[1], kv[0]))[:2]]
        summary = FALLBACK_SUMMARY_TEMPLATE.format(period=PERIOD_KO[_kind(f)], done=len(done), doing=len(doing))
        if top:
            summary += FALLBACK_PROJECTS_TEMPLATE.format(projects=", ".join(top))
        return {"summary": summary, "highlights": [{"text": cut(r[2], 80), "refs": [r[0]]} for r in done[:3] if r[2]],
                "relations": [], "next": [cut(r[2], 60) for r in doing[:2] if r[2]], "peers_map": self._peers_map(it)}
