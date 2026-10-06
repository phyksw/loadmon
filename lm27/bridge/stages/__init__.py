# -*- coding: utf-8 -*-
r"""L4 단계 등록부(B §8 · 계약 §2.12 · X-253) — 단계 11종 ``REGISTRY`` 와 단계 모듈이 함께 쓰는 작은 도구.

    from lm27.bridge.stages import REGISTRY                  # 처음 읽을 때 단계 모듈을 지연 import 해 만든다(PEP 562)
    spec = REGISTRY["task_label"]                             # dict: 단계 id → StageSpec 인스턴스(삽입 순서 = 호출 순서)
    ans = REGISTRY["workflow_label"].fallback(item, ctx, why="no_ai_out")    # 세션 없이(R §4.10.3 · L-30)

호출 순서: 조회 3종(수집 마무리) → speech_act(정규화 보조) → taxonomy_bootstrap → taxonomy_consolidate → task_label(분류)
→ workflow_label → agentic_match → subagent_review(워크플로우) → review_text(리뷰). ``lm27.bridge.runner.resolve_specs`` 가
이 순서대로 고른다.

**import 무부작용**(L-30 · R B-2): 이 패키지와 단계 모듈은 최상위에서 파일·네트워크·세션·하위 프로세스를 건드리지 않는다.
여러 작업 패키지가 나눠 가진 패키지라(``base.py`` 는 WP-24) 이 ``__init__`` 은 하위 모듈을 최상위에서 import 하지 않는다 —
``REGISTRY`` 는 처음 읽힐 때 만든다(계약 §2 머리 · CR-09). 단계 모듈의 프롬프트 상수는 이름에 ``PROMPT``·``TEMPLATE`` 를
넣는다 — 정제 selftest 의 '템플릿' 절이 ``scan()`` 0건을 본다(WP-10 요청).

폴백·접기는 ``item``·``ctx`` 를 두 모양으로 받는다: 브리지 실행기(``runner.WorkItem`` · ``base.StageCtx``)와 보고서 분석층
(ai_in 행 dict · ``SimpleNamespace(registry, catalog, cfg, …)`` — R §4.10.3). 아래 도구(``fields_of``·``rule_of``·
``registry_of``·``catalog_of``)가 그 차이를 흡수한다.
"""
from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping

__all__ = [
    "STAGE_IDS", "STAGE_TABLE", "agents_of", "as_text", "build_registry", "current_batch", "cut", "fields_of", "get",
    "has_effective", "key_of", "remember_batch", "registry_of", "rule_of", "scrub_time", "str_list", "vocab_line",
    "vocab_name", "vocab_pairs", "web_combo", "web_exposed", "web_plain",
]

# (단계 id, 모듈, 클래스) — 삽입 순서 = 호출 순서
STAGE_TABLE = (
    ("lookup_mail", "lookup", "LookupMail"),
    ("lookup_teams", "lookup", "LookupTeams"),
    ("lookup_calendar", "lookup", "LookupCalendar"),
    ("speech_act", "speech_act", "SpeechAct"),
    ("taxonomy_bootstrap", "taxonomy_bootstrap", "TaxonomyBootstrap"),
    ("taxonomy_consolidate", "taxonomy_consolidate", "TaxonomyConsolidate"),
    ("task_label", "task_label", "TaskLabel"),
    ("workflow_label", "workflow_label", "WorkflowLabel"),
    ("agentic_match", "agentic_match", "AgenticMatch"),
    ("subagent_review", "subagent_review", "SubagentReview"),
    ("review_text", "review_text", "ReviewText"),
)
STAGE_IDS = tuple(s for s, _m, _c in STAGE_TABLE)


def build_registry() -> dict:
    """단계 모듈을 import 해 ``{단계 id: StageSpec 인스턴스}`` 를 만든다(새 dict — 부를 때마다 새 인스턴스)."""
    import importlib
    out: dict = {}
    for sid, mod, cls in STAGE_TABLE:
        m = importlib.import_module(f"{__name__}.{mod}")
        spec = getattr(m, cls)()
        if spec.id != sid:
            raise ValueError(f"단계 등록부: {cls}.id 가 {sid} 가 아닙니다")
        out[sid] = spec
    return out


def __getattr__(name: str):
    """``REGISTRY`` 는 처음 읽힐 때 만든다(PEP 562 — 패키지 import 만으로는 단계 모듈을 부르지 않는다)."""
    if name == "REGISTRY":
        reg = build_registry()
        globals()["REGISTRY"] = reg
        return reg
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def get(stage_id: str):
    """등록부의 단계 하나(없으면 KeyError)."""
    reg = globals().get("REGISTRY")
    if reg is None:
        reg = __getattr__("REGISTRY")
    return reg[stage_id]


# ───────────────────────── 항목·문맥 두 모양 흡수 ─────────────────────────
def _field(obj, name: str):
    if isinstance(obj, Mapping):
        return obj.get(name)
    return getattr(obj, name, None)


def fields_of(it) -> dict:
    """항목의 보낼 필드(``WorkItem.fields`` 또는 ai_in 행의 ``fields``)."""
    v = _field(it, "fields")
    return dict(v) if isinstance(v, Mapping) else {}


def rule_of(it) -> dict:
    """항목의 규칙 재료(보내지 않음)."""
    v = _field(it, "rule")
    return dict(v) if isinstance(v, Mapping) else {}


def key_of(it) -> str:
    v = _field(it, "key")
    return v if isinstance(v, str) else ""


def registry_of(ctx):
    """문맥의 유효 레지스트리(``EffectiveRegistry`` · 시험용 dict · None)."""
    return _field(ctx, "registry") if ctx is not None else None


def has_effective(reg) -> bool:
    """``lm27.hier.registry.EffectiveRegistry`` 꼴인가(과제·어휘 표를 가진 객체)."""
    return reg is not None and not isinstance(reg, Mapping) and callable(getattr(reg, "active_ids", None)) \
        and isinstance(getattr(reg, "projects", None), Mapping) and isinstance(getattr(reg, "vocab", None), Mapping)


def agents_of(ctx) -> list[dict]:
    """agentic 카탈로그(running·planned 만, id 순) → ``[{id, name, copilot_desc, step_types, inputs, outputs}]``.
    원천: 보고서 문맥의 ``catalog``(dict 목록) → 레지스트리 ``agents``(``Agent`` 또는 dict) → 시험용 dict 의 ``agents``."""
    raw = _field(ctx, "catalog") if ctx is not None else None
    if not raw:
        reg = registry_of(ctx)
        raw = _field(reg, "agents") if reg is not None else None
    out = []
    for a in raw or ():
        aid = as_text(_field(a, "id"))
        if not aid or as_text(_field(a, "status") or "running") in ("retired", "removed"):
            continue
        out.append({"id": aid, "name": as_text(_field(a, "name")), "copilot_desc": as_text(_field(a, "copilot_desc")),
                    "step_types": str_list(_field(a, "step_types")), "inputs": str_list(_field(a, "inputs")),
                    "outputs": str_list(_field(a, "outputs"))})
    return sorted(out, key=lambda x: x["id"])


def web_exposed(ctx) -> bool:
    """문맥의 웹 노출 여부 — 모르면 노출로 본다(B15 안전 쪽)."""
    v = getattr(ctx, "web_exposed", None) if ctx is not None else None
    return True if v is None else bool(v)


# ───────────────────────── 묶음 기억(머리말이 묶음을 알아야 하는 단계) ─────────────────────────
def remember_batch(spec, ctx, batch) -> None:
    """``title_line`` 이 부르는 자리 — 조립 중인 묶음을 단계 인스턴스에 잠시 둔다(머리말·``rephrase`` 가 쓴다).
    ``exchange.assemble`` 은 질의마다 ``title_line`` → ``rephrase``/``header`` 순으로 부르므로 같은 질의 안에서만 쓰인다.
    패킹 예산 계산(``runner._fixed_len``)은 빈 묶음으로 부르므로 머리말은 '가장 긴 모양'을 낸다."""
    spec._lm27_scratch = (ctx, list(batch or ()))


def current_batch(spec, ctx=None, *, any_ctx: bool = False) -> list:
    """기억한 묶음(같은 문맥에서만 — ``any_ctx`` 면 문맥을 따지지 않는다). 없으면 []."""
    s = getattr(spec, "_lm27_scratch", None)
    if not s:
        return []
    if not any_ctx and s[0] is not ctx:
        return []
    return list(s[1])


def remembered_ctx(spec):
    s = getattr(spec, "_lm27_scratch", None)
    return s[0] if s else None


# ───────────────────────── 글 ─────────────────────────
def as_text(v) -> str:
    """값 → 한 줄 문자열(None → '', 줄바꿈 → 공백)."""
    if v is None:
        return ""
    s = v if isinstance(v, str) else str(v)
    return re.sub(r"[\r\n\t]+", " ", s).strip()


def str_list(v, n: int | None = None) -> list[str]:
    """문자열 목록(문자열 하나면 [그것], 빈 값은 뺀다)."""
    if v is None:
        return []
    if isinstance(v, str):
        v = [v]
    if not isinstance(v, (list, tuple)):
        return []
    out = [as_text(x) for x in v if not isinstance(x, (dict, list, tuple)) and as_text(x)]
    return out[:n] if n is not None else out


def cut(s: str, n: int) -> str:
    """앞 n 자(자르기만 — 말줄임 없음)."""
    s = as_text(s)
    return s if len(s) <= n else s[:n].rstrip()


# 시간·공수 숫자 표현(B §8.4 normalize · B1) — 이 표현이 든 문장은 지운다
TIME_QTY_RX = re.compile(r"\d+(?:[.,]\d+)?\s*(?:시간|h|MM|M/M|분|일|%)")
_SENT_RX = re.compile(r"(?<=[.!?。])\s+")


def scrub_time(text: str) -> tuple[str, int]:
    """문장 단위로 시간·공수 숫자 표현이 든 문장을 지운다 → (남은 글, 지운 문장 수)."""
    s = as_text(text)
    if not s or not TIME_QTY_RX.search(s):
        return s, 0
    keep, n = [], 0
    for sent in _SENT_RX.split(s):
        if TIME_QTY_RX.search(sent):
            n += 1
        elif sent.strip():
            keep.append(sent.strip())
    return " ".join(keep), n


def web_plain(text: str) -> str:
    """웹 노출 엄격 규칙 S1·S2(B §9.7)를 게이트가 다루지 못하는 중첩 목록의 글에 직접 적용 —
    ``[고객사:ID]``→``[고객사]`` · ``[이메일@협력사:ID]``→``[이메일@협력사]`` · ``[사람#6hex]``→``[사람]``.
    정규식은 ``lm27.bridge.gate`` 의 것 한 벌(ID 글자판 = P §5 보호 구간, G-B11)."""
    from lm27.bridge import gate as G
    t = as_text(text)
    t = G.RX_MAIL_ORG.sub(lambda m: "[이메일@" + m.group(1) + "]", t)
    t = G.RX_ORG_ID.sub(lambda m: "[" + m.group(1) + "]", t)
    return G.RX_PERSON_KEY.sub("[사람]", t)


def web_combo(text: str) -> bool:
    """S3(B §9.7) — 금액형 토큰과 고객사형 토큰이 함께 있는가."""
    from lm27.bridge import gate as G
    t = as_text(text)
    return bool(G.RX_AMOUNT.search(t) and G.RX_CUSTOMER.search(t))


# ───────────────────────── 어휘(코드 한글명) ─────────────────────────
_KIND_CODES = {"fields": "vocab.field", "functions": "vocab.func", "activity_types": "vocab.wtype",
               "step_types": "vocab.step"}


def _builtin_pairs(kind: str) -> list[tuple[str, str]]:
    if kind == "step_types":
        from lm27.vocab.steps import STEP_TYPES
        return [(c, s.name) for c, s in STEP_TYPES.items()]
    from lm27.hier.vocab import BUILTIN_VOCAB
    return [(it.code, it.name) for it in BUILTIN_VOCAB.get(kind, ())]


def vocab_pairs(reg, kind: str) -> list[tuple[str, str]]:
    """어휘 ``(코드, 한글명)`` 목록 — 유효 레지스트리의 active·팀 공유 코드(개인 ``L_`` 코드 제외, H §6.3),
    시험용 dict 는 그 코드 목록(이름은 내장 표), 없으면 내장 표."""
    voc = getattr(reg, "vocab", None) if reg is not None and not isinstance(reg, Mapping) else None
    if isinstance(voc, Mapping) and isinstance(voc.get(kind), Mapping):
        return [(it.code, it.name) for it in voc[kind].values()
                if getattr(it, "status", "active") == "active" and getattr(it, "origin", "") != "local"]
    base = _builtin_pairs(kind)
    if isinstance(reg, Mapping):
        codes = (reg.get("codes") or {}).get(_KIND_CODES.get(kind, "")) if isinstance(reg.get("codes"), Mapping) else None
        if codes:
            names = dict(base)
            return [(str(c), names.get(str(c), str(c))) for c in codes]
    return base


def vocab_line(reg, kind: str, head: str) -> str:
    """``[머리] 코드 이름 · 코드 이름 · …`` 한 줄(B §8.0.3 '코드 한글명 쌍')."""
    return f"[{head}] " + " · ".join(f"{c} {n}" for c, n in vocab_pairs(reg, kind))


def vocab_name(reg, kind: str, code) -> str:
    """코드 → 한글명(모르면 코드 그대로)."""
    c = as_text(code)
    for k, n in vocab_pairs(reg, kind):
        if k == c:
            return n
    for k, n in _builtin_pairs(kind):
        if k == c:
            return n
    return c


def nfkc(s) -> str:
    return unicodedata.normalize("NFKC", as_text(s))
