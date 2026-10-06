# -*- coding: utf-8 -*-
r"""``task_label`` — 단위업무 이름·과제/역할 고르기(**H §6 ``task_label/1.1`` 이 내용 정본** · B §8.3 골격 · X-250~X-252).

ai_in(H §6.2 — ``lm27.hier.copilot_io.build_task_label_items``): 키 ``grp:…``(명명 군집), ``group`` = 후보 1위 과제 ID,
보낼 필드 ``kinds · subjects · files · apps · domains · cands · hint · regv``, 규칙 재료 ``rule{project, score, source,
field, func, wtype, title, title_src, reg_set}``. 내용 키 = ``kinds·subjects·files·apps·domains·regv``(후보·규칙안은 빼서
규칙만 바뀌면 다시 묻지 않는다 — ``regv`` 가 레지스트리 변경 재질의를 맡는다, H §6.6).

프롬프트(H §6.3 글자 그대로): 머리말 13줄 + ``[업무영역]``·``[과제 목록]``(코드 · 영역 · ``copilot_desc`` + 예약 5줄)·
``[분야]``·``[기능]``·``[업무유형]`` — 목록 줄은 ``lm27.hier.copilot_io.prompt_context`` 한 벌(G-H9 · HG29 와 같은 바이트,
과제 이름·별칭·코드네임은 싣지 않는다 — B14). 축약(``compact``)이면 ``[과제 목록]`` 을 이 묶음 후보 코드 + 예약 5줄 + 안내
한 줄로 줄인다. 묶음 후보는 ``COMPACT_CODES_MAX`` 개까지(자주 나온 순) — 패킹 예산 계산(빈 묶음)은 가장 긴 설명의 과제
그만큼을 자리로 잡아 실제 묶음이 예산을 넘지 않는다. 웹 노출이면 ``domains`` 는 보내지 않는다(``web_drop_fields`` — 열은
두고 값만 ``-``, X-254 · T-H17).

답(H §6.5): ``{project, field, func, wtype, title, new, dom, conf}`` — 과제 코드는 active ∪ 예약 5개 ∪ ``NONE``·``NEW``.
NEW 는 ``new``(2자 이상)·``dom``(영역 5종)이 있어야 하고, 제목·새 이름에 금액 표현이 있으면 무효. 정규화: 따옴표·꺾쇠 기호
정리, 제목 앞뒤 공백·마침표 제거, 제목의 ``[과제:…]`` 토큰 제거. NEW 의 이름은 로컬 제안 큐(``proposals.on_new_name``)로만
간다 — ``ai_out.proposals`` 는 두지 않는다(X-252). 폴백(H §6.5): 규칙 과제(확정·유력·영역)·규칙 분야/기능/유형·규칙 이름·
``conf=l``.

형식 줄의 ``새 과제 이름 또는 ""`` 는 정제기가 '이름 또는' 을 사람 이름으로 잡아 프롬프트 게이트가 단계를 멈추므로
``새 과제명 또는 ""`` 로 바꿨다(완료 보고 CR — WP-10 이름 문맥 규칙). 그 밖은 H 실물과 같다.
"""
from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping
from types import SimpleNamespace

from lm27.bridge.stages import (as_text, current_batch, cut, fields_of, has_effective, registry_of, remember_batch,
                                rule_of, str_list, vocab_line)
from lm27.bridge.stages.base import TITLE_TEMPLATE, F, StageSpec, registry_codes

__all__ = ["COMPACT_CODES_MAX", "TaskLabel"]

COMPACT_CODES_MAX = 20            # 축약 머리말의 묶음 후보 과제 줄 상한
TITLE_MAX = 30
NEW_MAX = 20
CONFS = ("h", "m", "l")
DOMAINS = ("DEV", "MP", "EXT", "COM", "AX")
NO_DESC = "(설명 없음)"
FALLBACK_TITLE = "미분류 업무"
_MONEY_RX = re.compile(r"\d[\d,]*\s?(?:원|만원|억|달러|USD|KRW)")
_TOKEN_RX = re.compile(r"\[과제:[^\]]{1,24}\]")
_QUOTE_RX = re.compile("[\"'`“”‘’「」『』<>《》〈〉]")
_HINT_RX = re.compile(r"^([A-Z][A-Z0-9_]{1,15})/([A-Z][A-Z0-9_]{1,15})/([A-Z][A-Z0-9_]{1,15})$")
_SOURCES_NONE = ("none", "")

TASK_LABEL_HEAD_PROMPT = (
    "당신은 한 엔지니어의 업무 흔적 묶음(단위업무)을 팀 과제 목록과 어휘에 맞춰 분류합니다.",
    "항목마다 다음을 고르세요.",
    "- project : [과제 목록]의 코드 하나. P-99 로 시작하는 코드는 과제는 모르지만 업무 영역은 알 때 씁니다. "
    "업무가 아니거나 판단할 수 없으면 NONE, 목록에 없는 새 과제가 분명하면 NEW.",
    "- field : [분야] 코드 하나 / func : [기능] 코드 하나 / wtype : [업무유형] 코드 하나",
    "- title : 이 단위업무를 부르는 짧은 이름(명사구, 25자 이내). 과제 코드·사람 이름·금액·날짜는 넣지 않습니다.",
    '- new : project 가 NEW 일 때만 새 과제의 짧은 이름(20자 이내), 아니면 "".',
    '- dom : project 가 NEW 일 때만 새 과제의 업무영역 코드, 아니면 "".',
    "- conf : 확신 h(높음)·m(보통)·l(낮음)",
    "규칙:",
    "- [과제:P-0012] 처럼 꺾쇠 안의 코드는 그 과제를 가리킵니다. 후보·규칙안은 프로그램이 계산한 참고값이며 틀릴 수 있습니다.",
    "- 목록에 있는 코드만 씁니다. 코드를 바꾸거나 지어내지 않습니다.",
    "- 'OO 설계'·'OO 보고서 작성' 같은 활동 이름은 새 과제가 아닙니다. 여러 업무를 묶는 제품·프로젝트·과제일 때만 NEW 입니다.",
    "- [앞서 쓴 이름]에 같은 일이 있으면 그 이름을 그대로 다시 씁니다(같은 일은 같은 이름).",
)
TASK_LABEL_COLUMNS_PROMPT = "[항목] 번호 | 흔적 | 제목 요지 | 파일 | 앱 | 상대 | 후보 | 규칙안"
TASK_LABEL_FORMAT_PROMPT = ('{"rid": <요청번호>, "n": <항목 수>, "items": [ {"id": <번호>, "project": <코드|NONE|NEW>, '
                            '"field": <분야 코드>, "func": <기능 코드>, "wtype": <업무유형 코드>, "title": <짧은 이름>, '
                            '"new": <새 과제명 또는 "">, "dom": <영역 코드 또는 "">, "conf": <h|m|l>} ]}')
TASK_LABEL_UNKNOWN_PROMPT = "project 는 NONE, conf 는 l 로 쓰고 title 은 흔적에서 보이는 그대로 짧게 씁니다"
TASK_LABEL_COMPACT_PROMPT = "(목록은 이번 항목의 후보만 보입니다. 맞는 것이 없으면 NONE 또는 P-99 코드)"


def _cands(v) -> list[tuple[str, object]]:
    out = []
    for c in v or ():
        if isinstance(c, (list, tuple)) and c and isinstance(c[0], str):
            out.append((c[0], c[1] if len(c) > 1 else None))
    return out


def _cands_text(v) -> str:
    parts = []
    for p, s in _cands(v):
        try:
            parts.append(f"{p} {float(s):.2f}")
        except (TypeError, ValueError):
            parts.append(p)
    return ", ".join(parts)


def _reserved() -> dict:
    from lm27.hier import vocab as V
    return dict(V.RESERVED)


class TaskLabel(StageSpec):
    id = "task_label"
    title_ko = "단위업무 이름·과제/역할 고르기"
    prompt_ver = "task_label/1.1"
    schema_major = 1
    kind = "items"
    model_class = "fast"
    chat_policy = "continue"
    max_items = 30
    min_split = 5
    est_out_per_item = 120
    est_out_fixed = 80
    group_strict = False
    send_fields = ("kinds", "subjects", "files", "apps", "domains", "cands", "hint", "regv")
    text_fields = ("subjects", "files", "apps", "domains")
    web_drop_fields = ("domains",)
    content_key_fields = ("kinds", "subjects", "files", "apps", "domains", "regv")
    uses_registry = True
    names_field = "title"
    item_schema = (F("project", "code", codes="projects", extra_codes=("NONE", "NEW")),
                   F("field", "code", codes="vocab.field"), F("func", "code", codes="vocab.func"),
                   F("wtype", "code", codes="vocab.wtype"),
                   F("title", "str", min_len=2, max_len=TITLE_MAX, hard_max=80),
                   F("new", "str", required=False, max_len=NEW_MAX),
                   F("dom", "enum", required=False, enum=DOMAINS + ("",)),
                   F("conf", "enum", enum=CONFS))
    stub = {"project": "NONE", "field": "ETC", "func": "ETC", "wtype": "OFFICE", "title": "업무 흔적 정리", "new": "",
            "dom": "", "conf": "m"}

    # ── 프롬프트 ──
    def title_line(self, rid, n, batch, ctx) -> str:
        remember_batch(self, ctx, batch)
        return TITLE_TEMPLATE.format(rid=rid, title=self.title_ko, n=n)

    def header(self, ctx, compact: bool = False) -> str:
        reg = registry_of(ctx)
        cand = self._compact_codes(reg, current_batch(self, ctx)) if compact else ()
        return "\n".join(list(TASK_LABEL_HEAD_PROMPT) + self.context_lines(reg, compact=compact, cand_codes=cand))

    def context_lines(self, reg, *, compact: bool = False, cand_codes=()) -> list[str]:
        """[업무영역]·[과제 목록]·예약 5줄·[분야]·[기능]·[업무유형](H §6.3) — 유효 레지스트리는
        ``copilot_io.prompt_context`` 한 벌, 시험용 dict·없음은 같은 모양으로 코드만."""
        if has_effective(reg):
            from lm27.hier.copilot_io import prompt_context
            return list(prompt_context(reg, "task_label", compact=compact, cand_codes=tuple(cand_codes)))
        from lm27.hier import vocab as V
        lines = [V.domain_prompt_line(), "[과제 목록] 코드 · 업무영역 · 설명"]
        codes = registry_codes(reg).get("projects", frozenset())
        desc = reg.get("desc") if isinstance(reg, Mapping) and isinstance(reg.get("desc"), Mapping) else {}
        doms = reg.get("domains") if isinstance(reg, Mapping) and isinstance(reg.get("domains"), Mapping) else {}
        res = _reserved()
        ids = sorted(c for c in codes if c not in res)
        if compact:
            ids = [i for i in ids if i in set(cand_codes)]
        for pid in ids:
            lines.append(f"{pid} · {doms.get(pid, '-')} · {desc.get(pid) or NO_DESC}")
        for rid, dom in res.items():
            lines.append(f"{rid} · {dom} · {V.reserved_desc(rid)}")
        if compact:
            lines.append(TASK_LABEL_COMPACT_PROMPT)
        lines += [vocab_line(reg, "fields", "분야"), vocab_line(reg, "functions", "기능"),
                  vocab_line(reg, "activity_types", "업무유형")]
        return lines

    def _compact_codes(self, reg, batch) -> tuple:
        """축약 머리말의 과제 코드 — 묶음이 있으면 그 후보 코드(자주 나온 순, 상한), 빈 묶음(예산 계산)이면 설명이 긴
        과제 상한 개(어떤 묶음의 목록보다도 길거나 같다)."""
        active = self._active(reg)
        if batch:
            cnt = Counter(p for it in batch for p, _s in _cands(fields_of(it).get("cands")) if p in active)
            return tuple(c for c, _n in sorted(cnt.items(), key=lambda kv: (-kv[1], kv[0]))[:COMPACT_CODES_MAX])
        return tuple(sorted(active, key=lambda p: (-len(active[p]), p))[:COMPACT_CODES_MAX])

    @staticmethod
    def _active(reg) -> dict:
        """active 과제 → 프롬프트 설명(길이 비교용)."""
        if has_effective(reg):
            out = {}
            for pid in reg.active_ids():
                p = reg.projects.get(pid)
                out[pid] = as_text(getattr(p, "copilot_desc", "")) or NO_DESC
            return out
        codes = registry_codes(reg).get("projects", frozenset())
        desc = reg.get("desc") if isinstance(reg, Mapping) and isinstance(reg.get("desc"), Mapping) else {}
        res = _reserved()
        return {c: as_text(desc.get(c)) or NO_DESC for c in codes if c not in res}

    def columns(self) -> str:
        return TASK_LABEL_COLUMNS_PROMPT

    def item_line(self, it, n) -> str:
        """H §6.3 항목 줄 — 빈 칸은 ``-``(웹 노출로 ``domains`` 를 비운 경우도 열은 남고 값만 ``-``)."""
        f = fields_of(it)
        return " | ".join([str(n), as_text(f.get("kinds")), " / ".join(str_list(f.get("subjects"))) or "-",
                           ", ".join(str_list(f.get("files"))) or "-", ", ".join(str_list(f.get("apps"))) or "-",
                           ", ".join(str_list(f.get("domains"))) or "-", _cands_text(f.get("cands")) or "-",
                           as_text(f.get("hint"))])

    def format_line(self) -> str:
        return TASK_LABEL_FORMAT_PROMPT

    def unknown_rule(self) -> str:
        return TASK_LABEL_UNKNOWN_PROMPT

    def shrink(self, it, max_chars: int):
        """``subjects`` 1개로 → ``files`` 2개로 → ``domains`` 제거 → 그래도 크면 None(B §8.3)."""
        nf = fields_of(it)
        steps = (("subjects", 1), ("files", 2), ("domains", 0))
        for name, keep in steps:
            nf[name] = str_list(nf.get(name))[:keep]
            if len(self.item_line(SimpleNamespace(fields=nf), 99)) <= max_chars:
                return nf
        return None

    # ── 검증·정규화(H §6.5) ──
    def code_sets(self, ctx) -> dict:
        """과제 코드 = active ∪ 예약 5개(H §6.5), 어휘 = active 코드(``copilot_io.codes_for`` 한 벌)."""
        reg = registry_of(ctx)
        if has_effective(reg):
            from lm27.hier.copilot_io import codes_for
            return {k: frozenset(v) for k, v in codes_for(reg).items()}
        out = dict(registry_codes(reg))
        out["projects"] = frozenset(out.get("projects", frozenset())) | frozenset(_reserved())
        return out

    def validate(self, ans: dict, it, ctx) -> str:
        if ans.get("project") == "NEW":
            if len(as_text(ans.get("new"))) < 2:
                return "missing:new"
            if ans.get("dom") not in DOMAINS:
                return "missing:dom"
        if _MONEY_RX.search(as_text(ans.get("title"))) or _MONEY_RX.search(as_text(ans.get("new"))):
            return "bad_pattern:title"
        return ""

    def normalize(self, ans: dict, it, ctx) -> dict:
        out = dict(ans)
        title = _TOKEN_RX.sub("", as_text(out.get("title")))
        title = _QUOTE_RX.sub("", title)
        out["title"] = cut(re.sub(r"\s+", " ", title).strip(" .。"), TITLE_MAX) or as_text(ans.get("title"))
        new = _QUOTE_RX.sub("", _TOKEN_RX.sub("", as_text(out.get("new")))).strip(" .。")
        out["new"] = cut(new, NEW_MAX) if out.get("project") == "NEW" else ""
        out["dom"] = out.get("dom") if out.get("project") == "NEW" and out.get("dom") in DOMAINS else ""
        return out

    # ── 폴백(H §6.5) ──
    def fallback(self, it, ctx, why: str = "") -> dict:
        r = rule_of(it)
        f = fields_of(it)
        proj = r.get("project")
        src = as_text(r.get("source") or "rule")
        project = proj if isinstance(proj, str) and proj and src not in _SOURCES_NONE else "NONE"
        m = _HINT_RX.match(as_text(f.get("hint")))
        hint = m.groups() if m else ("", "", "")
        field = as_text(r.get("field")) or hint[0] or "ETC"
        func = as_text(r.get("func")) or hint[1] or "ETC"
        wtype = as_text(r.get("wtype")) or hint[2] or "OFFICE"
        title = cut(as_text(r.get("title")), TITLE_MAX) or FALLBACK_TITLE
        return {"project": project, "field": field, "func": func, "wtype": wtype, "title": title, "new": "", "dom": "",
                "conf": "l"}
