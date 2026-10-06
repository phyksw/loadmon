# -*- coding: utf-8 -*-
r"""L4 단계 기반(B §8.0) — ``StageSpec`` 기반 클래스 · 필드 명세 언어 ``F``(B §6.5) · 항목 검증 · 내용 키(B §7.9) ·
단계 문맥 ``StageCtx`` · 공통 프롬프트 문구(B §6.2 글자 그대로) · 단계 완결성 검사(G-B4·G-B8).

WP-25 의 단계 11종(``lm27.bridge.stages.*``)이 ``StageSpec`` 을 잇는다. 단계는 머리말·항목 줄·답 형식·추가 검사·정규화·
폴백·접기만 정하고, 패킹·사다리·게이트·커밋·재개는 L2·L3(``exchange``·``runner``) 한 벌이 맡는다.

**import 무부작용**(L-30 · R B-2): 이 모듈은 최상위에서 파일·네트워크·세션을 건드리지 않는다 — 세션 없이 ``fallback()`` 을
부를 수 있다. ``lm27.privacy`` 는 import 하지 않는다(브리지에서 정제 관문을 부르는 파일은 ``lm27.bridge.gate`` 하나).

프롬프트 공통 문구 상수는 이름에 ``PROMPT``·``TEMPLATE`` 를 넣는다 — 정제 selftest 의 '템플릿' 절이 ``scan()`` 0건을 본다.

내용 키(B §7.9): ``{"s": 스키마 주판, "r": "", "f": 내용 키 필드}`` 의 sha256 앞 24자. 레지스트리 판은 키에 넣지 않는다 —
레지스트리 변경은 커밋의 ``reg`` 와 재개 규칙 (c)(``runner.resume_filter``), 단계의 ``regv`` 필드(H §6.6)가 다룬다
(H42 '과제 목록 불변 → 재사용'). 판단 근거는 완료 보고의 CR.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field

__all__ = [
    "ANSWER_HEAD_PROMPT", "CHAT_POLICIES", "FIELD_KINDS", "FOOTER_TEMPLATE", "FORMAT_LINE_TEMPLATE", "F", "KINDS",
    "LOOKUP_COUNT_PROMPT", "MODEL_CLASSES", "NOTE_PROMPT", "NOTE_PROMPTS", "NO_WEB_PROMPT", "OVERLAP_PROMPT",
    "PLEDGE_TEMPLATE", "SEEN_NAMES_PROMPT", "STRICT_FORMAT_PROMPT", "StageCtx", "StageSpec", "TIME_KEY_RX",
    "TITLE_TEMPLATE", "canon", "check_item", "check_stage", "clean_str", "content_key", "note_for",
]

KINDS = ("items", "lookup", "single")
MODEL_CLASSES = ("fast", "deep")
CHAT_POLICIES = ("continue", "fresh_each")
FIELD_KINDS = ("str", "int", "bool", "enum", "code", "list", "obj", "nullable_obj")
STAGE_ID_RX = re.compile(r"^[a-z][a-z0-9_]{0,47}$")

# 답 항목의 시간형 키(B §6.5-2) — 이 이름의 키가 있으면 그 항목 무효(forbidden_field, B1). 조회 단계만 자기 스키마 예외.
TIME_KEY_RX = re.compile(r"(?i)^(start|end|begin|finish|time|date|datetime|hours?|minutes?|mins?|mm|man_?month"
                         r"|duration|effort|lead_?time)$")
# 보낼 필드 이름의 시간형 판정(L-18 · G-B8 · P §13.4 와 같은 규칙) — 단계 완결성 검사용
SEND_TIME_KEY_RX = re.compile(
    r"(?i)^(?:ts|t0|t1|date|dates|day|days|month|months|week|weeks|time|times|hour|hours|minute|minutes|min|mins|"
    r"sec|secs|second|seconds|mm|duration|start|end|effort|lead|wd|when|at)(?:_|$)|"
    r"(?:^|_)(?:utc|ts|date|day|days|time|hours?|h|min|mins|minutes|sec|secs|seconds|mm|wd|at|start|end|"
    r"duration|effort)$")
TIME_TEXT_RX = re.compile(r"\d+(\.\d+)?\s*(MM|M/M|시간|h)\b")          # G-B8 프롬프트 시간 수치
_MAIL_RX = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+\.[A-Za-z0-9.\-]+")
_IPV4_RX = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
_CODE_FREE_RX = re.compile(r"^[A-Za-z0-9_\-]{1,24}$")                  # 코드 집합을 모를 때의 최소 형식
_QUOTES = "\"'`“”‘’「」『』"
ELLIPSIS = "…"

# ───────────────────────── 공통 프롬프트 문구(B §6.2, 글자 그대로) ─────────────────────────
TITLE_TEMPLATE = "[LM27 요청 {rid} · {title} · 항목 {n}개]"
SEEN_NAMES_PROMPT = "[앞서 쓴 이름] {names}"
OVERLAP_PROMPT = "[참고 — 이미 처리한 항목, 답하지 마세요]"
ANSWER_HEAD_PROMPT = "[답 형식]"
FOOTER_TEMPLATE = (
    "- 아래 형식의 JSON 하나를 ```json 코드 블록 하나에 담아 답합니다. 코드 블록 밖에는 설명을 쓰지 않습니다.",
    '- rid 에는 "{rid}" 를, n 에는 items 의 개수를 씁니다. 항목 번호 1~{n} 을 빠짐없이 한 번씩, 번호 순서대로 씁니다.',
    "- 문자열 값은 큰따옴표로 감싸고 값 안에서 줄을 바꾸지 않습니다.",
    "- 근거가 부족하면 지어내지 말고 {unknown_rule}.",
    "- 사람 이름·전화번호·메일 주소·금액은 쓰지 않습니다. [전화]·[금액]·[사람] 같은 꺾쇠 표기는 가려진 값입니다.",
)
LOOKUP_COUNT_PROMPT = '- rid 에는 "{rid}" 를, n 에는 쓴 행 수를 씁니다. id 는 1부터 차례로 씁니다.'
NO_WEB_PROMPT = "- 웹 검색을 하지 말고 이 메시지에 적힌 내용만으로 답합니다."
FORMAT_LINE_TEMPLATE = "- 형식(<…> 자리에 실제 값): {format_line}"
STRICT_FORMAT_PROMPT = "- 반드시 JSON 코드 블록 하나로만 답합니다."
PLEDGE_TEMPLATE = "- 코드 블록이 끝나면 맨 마지막 줄에 [[END {rid}]] 만 씁니다."
NOTE_PROMPT = "- 주의: {notes}"
# 무효 사유 → 다음 질의 '주의' 줄 문구(B §6.7 partial)
NOTE_PROMPTS = {
    "missing": "{f} 를 빠뜨리지 않습니다",
    "bad_enum": "{f} 는 정해진 값 중 하나만 씁니다",
    "unknown_code": "{f} 는 목록에 있는 코드만 씁니다",
    "too_long": "{f} 는 정해진 길이 안으로 씁니다",
    "too_short": "{f} 는 너무 짧지 않게 씁니다",
    "bad_pattern": "{f} 는 정해진 형식대로 씁니다",
    "bad_type": "{f} 값의 형식을 지킵니다",
    "forbidden_field": "시각·날짜·공수 필드는 쓰지 않습니다",
}


def note_for(code: str) -> str:
    """무효 사유 코드(``unknown_code:project`` 꼴) → '주의' 문구 한 조각. 모르는 코드는 ''."""
    if not isinstance(code, str) or not code:
        return ""
    head, _, f = code.partition(":")
    tmpl = NOTE_PROMPTS.get(head)
    if tmpl is None:
        return ""
    return tmpl.format(f=f or "값")


# ───────────────────────── 필드 명세 언어(B §6.5) ─────────────────────────
@dataclass(frozen=True)
class F:
    name: str
    kind: str                     # "str" | "int" | "bool" | "enum" | "code" | "list" | "obj" | "nullable_obj"
    required: bool = True
    enum: tuple = ()              # kind == "enum"
    codes: str = ""               # kind == "code": 문맥의 허용 코드 집합 이름(예 "projects", "vocab.field", "catalog")
    extra_codes: tuple = ()       # code 에 더해 허용하는 값(예 ("NONE", "NEW"))
    max_len: int = 0              # str: 초과 시 잘라 쓰고 trunc 셈(거부 아님). 0 = 무제한
    hard_max: int = 0             # str: 이 길이를 넘으면 거부(too_long). 0 = 없음
    min_len: int = 0              # str: 미만이면 거부(too_short)
    max_items: int = 0            # list: 초과분은 버리고 caps_hit list_items 셈
    item: tuple = ()              # list/obj 의 하위 F 들
    pattern: str = ""             # str: fullmatch 정규식(불일치 → bad_pattern)

    def __post_init__(self):
        if self.kind not in FIELD_KINDS:
            raise ValueError(f"F({self.name}): kind 는 {FIELD_KINDS} 중 하나")


def clean_str(v) -> str:
    """NFKC · 앞뒤 공백 · 감싼 따옴표 제거(B §6.5-6 공통 정규화). 줄바꿈은 공백으로."""
    s = unicodedata.normalize("NFKC", str(v))
    s = re.sub(r"[\r\n\t]+", " ", s).strip()
    while len(s) >= 2 and s[0] in _QUOTES and s[-1] in _QUOTES:
        s = s[1:-1].strip()
    return s


def _cut(s: str, n: int) -> str:
    return s if len(s) <= n else s[:max(0, n - 1)].rstrip() + ELLIPSIS


def _check_value(f: F, v, ctx, path: str, counts: Counter):
    """값 하나 → (정규화한 값, 오류 코드 또는 '')."""
    k = f.kind
    if k == "str" or k == "enum" or k == "code":
        if isinstance(v, bool) or v is None or isinstance(v, (dict, list)):
            if k == "enum" and v in f.enum:
                return v, ""
            return None, f"bad_type:{path}"
        if k == "enum" and not isinstance(v, str):
            return (v, "") if v in f.enum else (None, f"bad_enum:{path}")
        s = clean_str(v)
        if k == "enum":
            return (s, "") if s in f.enum else (None, f"bad_enum:{path}")
        if k == "code":
            allowed = ctx.codes(f.codes) if ctx is not None and f.codes else None
            if s in f.extra_codes:
                return s, ""
            if allowed is None:
                return (s, "") if _CODE_FREE_RX.match(s) else (None, f"unknown_code:{path}")
            return (s, "") if s in allowed else (None, f"unknown_code:{path}")
        if f.pattern and not re.fullmatch(f.pattern, s):
            return None, f"bad_pattern:{path}"
        if f.min_len and len(s) < f.min_len:
            return None, f"too_short:{path}"
        if f.hard_max and len(s) > f.hard_max:
            return None, f"too_long:{path}"
        if f.max_len and len(s) > f.max_len:
            counts["trunc"] += 1
            s = _cut(s, f.max_len)
        return s, ""
    if k == "int":
        if isinstance(v, bool):
            return None, f"bad_type:{path}"
        if isinstance(v, int):
            return v, ""
        if isinstance(v, float) and v.is_integer():
            return int(v), ""
        if isinstance(v, str) and re.fullmatch(r"\s*-?\d{1,12}\s*", v):
            return int(v), ""
        return None, f"bad_type:{path}"
    if k == "bool":
        if isinstance(v, bool):
            return v, ""
        if isinstance(v, str) and v.strip().lower() in ("true", "false"):
            return v.strip().lower() == "true", ""
        return None, f"bad_type:{path}"
    if k == "list":
        if not isinstance(v, list):
            return None, f"bad_type:{path}"
        if f.max_items and len(v) > f.max_items:
            counts["list_items"] += len(v) - f.max_items
            v = v[:f.max_items]
        out = []
        for el in v:
            if f.item:
                if not isinstance(el, dict):
                    return None, f"bad_type:{path}"
                sub, err = _check_fields(f.item, el, ctx, path, counts)
                if err:
                    return None, err
                out.append(sub)
            else:
                if isinstance(el, (dict, list)) or el is None or isinstance(el, bool):
                    return None, f"bad_type:{path}"
                out.append(clean_str(el) if isinstance(el, str) else el)
        return out, ""
    if k == "obj" or k == "nullable_obj":
        if k == "nullable_obj" and (v is None or (isinstance(v, str) and v.strip().lower() in ("", "null", "none"))):
            return None, ""
        if not isinstance(v, dict):
            return None, f"bad_type:{path}"
        return _check_fields(f.item, v, ctx, path, counts)
    return None, f"bad_type:{path}"


def _check_fields(schema, raw: dict, ctx, prefix: str, counts: Counter):
    """dict 하나를 F 목록으로 검사 → (정규화 dict, 오류 코드). 명세에 없는 키는 버리고 extra_fields 를 센다."""
    names = {f.name for f in schema}
    for key in raw:
        if key not in names:
            counts["extra_fields"] += 1
    out = {}
    for f in schema:
        path = f"{prefix}.{f.name}" if prefix else f.name
        v = raw.get(f.name)
        if f.kind == "nullable_obj":
            if f.name not in raw:                      # 키 자체가 없으면 빠짐(null 은 정상 값)
                if f.required:
                    return None, f"missing:{path}"
                continue
        elif f.name not in raw or v is None or (isinstance(v, str) and not v.strip()):
            if f.required:
                return None, f"missing:{path}"
            continue
        val, err = _check_value(f, v, ctx, path, counts)
        if err:
            return None, err
        out[f.name] = val
    return out, ""


def check_item(spec, raw: dict, ctx=None, *, allow_time: bool | None = None):
    """답 항목 하나(B §6.5 순서 2~4) → (정규화 dict 또는 None, 오류 코드, Counter).

    ① ``id`` 는 호출자(L2)가 이미 읽었다 — 여기서는 뺀다. ② 시간형 키(``TIME_KEY_RX``)가 있으면 ``forbidden_field``
    (조회 단계 ``allow_time`` 이면 자기 스키마의 키만 예외). ③ 명세에 없는 키는 버리고 ``extra_fields`` 를 센다.
    ④ ``F`` 검사 실패 → ``missing:<f>``·``bad_enum:<f>``·``unknown_code:<f>``·``too_long:<f>``·``too_short:<f>``·
    ``bad_pattern:<f>``·``bad_type:<f>``."""
    counts: Counter = Counter()
    if not isinstance(raw, dict):
        return None, "bad_type:item", counts
    body = {k: v for k, v in raw.items() if k != "id"}
    schema = tuple(spec.item_schema)
    names = {f.name for f in schema}
    at = spec.allow_time if allow_time is None else allow_time
    for key in body:
        if isinstance(key, str) and TIME_KEY_RX.match(key) and not (at and key in names):
            counts["forbidden_field"] += 1
            return None, "forbidden_field", counts
    ans, err = _check_fields(schema, body, ctx, "", counts)
    return ans, err, counts


# ───────────────────────── 내용 키(B §7.9) ─────────────────────────
def canon(v):
    """문자열: NFKC + 공백 정리, 목록: 원소마다, 사전: 키 정렬, 수: 그대로."""
    if isinstance(v, str):
        return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", v)).strip()
    if isinstance(v, (list, tuple)):
        return [canon(x) for x in v]
    if isinstance(v, dict):
        return {str(k): canon(v[k]) for k in sorted(v, key=str)}
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v


def content_key(spec, fields: dict) -> str:
    """내용 키 ck(24hex, 계약 §4.4) — ``content_key_fields``(없으면 ``send_fields``)만, 변하는 값(MM·시간·건수)은 넣지 않는다."""
    mat = spec.key_material(dict(fields or {}))
    payload = {"s": int(spec.schema_major), "r": "", "f": {k: canon(mat.get(k)) for k in sorted(mat)}}
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


# ───────────────────────── 단계 문맥 ─────────────────────────
@dataclass
class StageCtx:
    """L4 단계가 받는 문맥(실행 1회·단계 1개). 레지스트리는 유효 레지스트리(``EffectiveRegistry``) 또는 시험용 dict.
    ``codes_map`` = 단계가 정한 허용 코드 집합(``StageSpec.code_sets``), ``pack_out`` = 지금 답 예산(조회 행 상한 계산)."""
    run_id: str = ""
    registry: object = None
    registry_version: str = ""
    codes_map: dict = field(default_factory=dict)
    env: object = None
    cfg: object = None
    clock: object = None
    pack_out: int = 0
    data: dict = field(default_factory=dict)

    def codes(self, name: str):
        """허용 코드 집합(frozenset) — 모르는 이름이면 None(형식 검사만)."""
        if name in self.codes_map:
            v = self.codes_map[name]
            return v if isinstance(v, frozenset) else frozenset(v or ())
        return None

    @property
    def web_exposed(self) -> bool:
        return bool(getattr(self.env, "web_exposed", True))


def registry_codes(reg) -> dict:
    """유효 레지스트리(또는 시험용 dict) → 기본 코드 집합 이름표. 단계가 ``code_sets`` 로 바꿀 수 있다."""
    out: dict = {}
    if reg is None:
        return out
    if isinstance(reg, dict):
        for k, v in reg.get("codes", {}).items() if isinstance(reg.get("codes"), dict) else ():
            out[str(k)] = frozenset(str(x) for x in v or ())
        return out
    if hasattr(reg, "active_ids"):
        out["projects"] = frozenset(reg.active_ids())
    vc = getattr(reg, "vocab_codes", None)
    if callable(vc):
        for name, kind in (("vocab.field", "fields"), ("vocab.func", "functions"), ("vocab.wtype", "activity_types"),
                           ("vocab.step", "step_types")):
            try:
                out[name] = frozenset(vc(kind))
            except KeyError:
                continue
    agents = getattr(reg, "agents", None)
    if agents is not None:
        out["catalog"] = frozenset(str(getattr(a, "id", "")) for a in agents if getattr(a, "id", ""))
    return out


def registry_version(reg) -> str:
    """레지스트리 판 표기(커밋 ``reg``·ai_out ``registry_version``) — ``r<판>``. 모르면 ''."""
    if reg is None:
        return ""
    if isinstance(reg, dict):
        v = reg.get("version")
    else:
        v = getattr(reg, "version", None)
    return f"r{v}" if v is not None and str(v) != "" else ""


# ───────────────────────── StageSpec 기반 클래스(B §8.0.1) ─────────────────────────
class StageSpec:
    """L4 단계 하나. 하위 클래스가 클래스 속성과 ``header``·``columns``·``item_line``·``format_line``·``unknown_rule``·
    ``fallback`` 을 정한다. 조회형(``kind="lookup"``)은 ``title_line``·``normalize_row``·``is_full``·``split`` 도 쓴다."""

    id: str = ""
    title_ko: str = ""
    prompt_ver: str = ""              # "task_label/1.1" — 문구만 바뀌면 부판(커밋 재사용)
    schema_major: int = 1             # 응답 스키마 주판 — 바뀌면 내용 키가 바뀌어 다시 묻는다
    kind: str = "items"               # "items" | "lookup" | "single"
    model_class: str = "fast"         # "fast" | "deep"
    chat_policy: str = "continue"     # "continue" | "fresh_each"
    want_work_mode: bool = False
    max_items: int = 1
    min_split: int = 0                # 0 = 설정 bridge.splitMinItems(분류형), 생성형 1, 단건형은 반분 없음
    est_out_per_item: int = 100
    est_out_fixed: int = 0
    group_strict: bool = False
    send_fields: tuple = ()
    text_fields: tuple | None = None  # None = 보낼 필드 중 문자열·문자열 목록 값(대기열에서 판정)
    web_drop_fields: tuple = ()
    gate_max_chars: int = 400
    content_key_fields: tuple = ()    # () = send_fields
    uses_registry: bool = False
    names_field: str = ""
    item_schema: tuple = ()
    allow_time: bool = False          # 조회 단계만(자기 스키마의 시각 필드)
    stub: dict | None = None          # 스텁 고정 답(G-B4 — 시험·LM_COPILOT_STUB 기본 답)

    # ── 프롬프트 ───────────────────────────────────────────────────────
    def title_line(self, rid: str, n: int, batch, ctx) -> str:
        return TITLE_TEMPLATE.format(rid=rid, title=self.title_ko, n=n)

    def header(self, ctx, compact: bool = False) -> str:
        """역할·규칙·참고 목록(여러 줄). ``compact`` = 축약 머리말(이 묶음 후보 + 상위 빈도)."""
        raise NotImplementedError(f"{self.id}: header() 가 없습니다")

    def columns(self) -> str:
        """``[항목] 번호 | …`` 줄(조회형은 '' — 항목 줄이 없다)."""
        cols = " | ".join(("번호",) + tuple(self.send_fields))
        return f"[항목] {cols}"

    def item_line(self, it, n) -> str:
        parts = [str(n)]
        for k in self.send_fields:
            v = it.fields.get(k, "")
            if isinstance(v, (list, tuple)):
                v = " / ".join(str(x) for x in v)
            parts.append(str(v if v is not None else ""))
        return " | ".join(parts)

    def overlap_line(self, it, ans) -> str:
        """겹침 줄(B §7.4) — 번호 없는 항목 줄 + ``→ 답한 이름``. 이름 필드가 없는 단계는 ''."""
        if not self.names_field or not isinstance(ans, dict) or not ans.get(self.names_field):
            return ""
        line = re.sub(r"^\s*0\s*\|\s*", "", self.item_line(it, 0))
        return f"- {line} → {ans.get(self.names_field)}"

    def shrink(self, it, max_chars: int):
        """항목 하나가 예산보다 클 때 필드 축약 사다리 — 줄여도 크면 None(oversize)."""
        return None

    def format_line(self) -> str:
        parts = [f'"{f.name}": <{f.name}>' for f in self.item_schema]
        body = ", ".join(['"id": <번호>'] + parts)
        return '{"rid": <요청번호>, "n": <항목 수>, "items": [ {' + body + '} ]}'

    def unknown_rule(self) -> str:
        return "모르는 값은 정해진 기본값으로 씁니다"

    def rephrase(self) -> str | None:
        """거절 시 바꿔 쓸 머리말(없으면 None)."""
        return None

    # ── 검증·정규화 ────────────────────────────────────────────────────
    def code_sets(self, ctx) -> dict:
        """답 검증 코드 집합 이름표(``F(codes=…)``) — 기본은 레지스트리에서(과제·어휘·카탈로그)."""
        return registry_codes(getattr(ctx, "registry", None))

    def validate(self, ans: dict, it, ctx) -> str:
        """단계 추가 검사 — '' 이면 통과, 아니면 무효 사유 코드."""
        return ""

    def normalize(self, ans: dict, it, ctx) -> dict:
        return ans

    def normalize_row(self, row: dict, it, ctx):
        """조회형 행 하나 → (행 또는 None, 셈 코드 튜플). 기본: 그대로."""
        return row, ()

    def is_full(self, ans: dict, status: str, ctx) -> bool:
        """조회형 '가득 참'(B §8.1) — 기본: 잘렸거나 more=true. 단계가 행 수 기준을 더한다."""
        return status == "truncated" or bool(isinstance(ans, dict) and ans.get("more") is True)

    def split(self, it, ctx):
        """조회형 구간 쪼개기 — 새 항목 [{key, fields, group?}, …] 또는 None(더 못 쪼갬)."""
        return None

    def est_out(self, it) -> int:
        return int(self.est_out_per_item)

    def key_material(self, fields: dict) -> dict:
        """내용 키 재료(``content_key_fields`` — 단계가 파생 필드를 만들 수 있다)."""
        keys = tuple(self.content_key_fields) or tuple(self.send_fields)
        return {k: fields.get(k) for k in keys}

    def fallback(self, it, ctx, why: str):
        """규칙 폴백 답(조회형은 None — 규칙으로 대신할 수 없다). 세션 없이 불릴 수 있어야 한다(L-30)."""
        return None

    def stub_answer(self, it=None) -> dict | None:
        """스텁 고정 답(G-B4) — 형식이 맞는 답 하나."""
        return dict(self.stub) if isinstance(self.stub, dict) else None

    # ── 산출 ───────────────────────────────────────────────────────────
    def fold(self, ctx, latest: dict) -> dict:
        """접기(B §7.10) — ``latest`` = key → ``{ans, by, rid, asks, at, …}``. 계약 §3.17 ai_out 형."""
        by = Counter(v.get("by") for v in latest.values())
        return {"schema": 1, "stage": self.id, "stage_ver": self.prompt_ver,
                "run_id": getattr(ctx, "run_id", ""), "registry_version": getattr(ctx, "registry_version", ""),
                "items": {k: latest[k] for k in sorted(latest)},
                "stats": {"total": len(latest), "ai": by["ai"], "manual": by["manual"], "rule": by["rule"],
                          "pending": by["rule_pending"]}}

    # ── 보조 ───────────────────────────────────────────────────────────
    @property
    def schema(self) -> str:
        return f"{self.id}/{int(self.schema_major)}"

    def split_floor(self, cfg) -> int:
        """반분 최소 크기(B §7.5) — 단건형은 반분 없음(큰 값)."""
        if self.kind == "single":
            return 1 << 30
        if self.min_split and self.min_split > 0:
            return int(self.min_split)
        return int(getattr(cfg, "split_min_items", 1) or 1)

    def privacy_spec(self, text_fields=None):
        """정제 관문의 ``StageSpec``(P §13.1) — 만들기는 ``lm27.bridge.gate`` 가 한다(정제 관문 import 는 그 파일 하나)."""
        from lm27.bridge import gate
        return gate.privacy_spec(self, text_fields)

    def __repr__(self) -> str:
        return f"<StageSpec {self.id}>"


# ───────────────────────── 단계 완결성(G-B4 · G-B8) ─────────────────────────
class _Probe:
    """완결성 검사용 빈 항목."""

    def __init__(self, fields=None, rule=None):
        self.key = "probe:0"
        self.group = ""
        self.fields = dict(fields or {})
        self.rule = dict(rule or {})
        self.meta = {}


def check_stage(spec, ctx=None, *, codename_words=(), sample_fields=None) -> list:
    """단계 하나의 완결성 문제 목록(빈 목록 = 통과) — G-B4(``prompt_ver``·``item_schema``·``format_line`` 의
    ``<요청번호>``·폴백(조회 제외)·스텁 고정 답·머리말에 메일 주소·IPv4·코드네임 사전 단어 0)·G-B8(보낼 필드에 시간형
    키 0, 머리말·형식 줄에 시간 수치 0)."""
    probs = []
    ctx = ctx if ctx is not None else StageCtx()
    sid = getattr(spec, "id", "")
    if not isinstance(sid, str) or not STAGE_ID_RX.match(sid):
        probs.append("id 형식")
    if not isinstance(spec.prompt_ver, str) or "/" not in spec.prompt_ver:
        probs.append("prompt_ver 없음")
    if spec.kind not in KINDS:
        probs.append("kind")
    if spec.model_class not in MODEL_CLASSES:
        probs.append("model_class")
    if spec.chat_policy not in CHAT_POLICIES:
        probs.append("chat_policy")
    if not spec.item_schema or not all(isinstance(f, F) for f in spec.item_schema):
        probs.append("item_schema 없음")
    if not spec.send_fields:
        probs.append("send_fields 없음")
    for f in spec.send_fields:
        if SEND_TIME_KEY_RX.search(str(f)):
            probs.append(f"send_fields 시간형 키 {f}")
    sf = set(spec.send_fields)
    for name, group in (("text_fields", spec.text_fields or ()), ("web_drop_fields", spec.web_drop_fields)):
        if not set(group) <= sf:
            probs.append(f"{name} 가 send_fields 밖")
    try:
        fl = spec.format_line()
    except Exception as e:  # noqa: BLE001 — 완결성 검사는 예외를 문제로 적는다
        fl = ""
        probs.append(f"format_line 오류 {type(e).__name__}")
    if "<요청번호>" not in fl:
        probs.append("format_line 에 <요청번호> 없음")
    texts = [fl]
    for compact in (False, True):
        try:
            texts.append(spec.header(ctx, compact))
        except Exception as e:  # noqa: BLE001
            probs.append(f"header 오류 {type(e).__name__}")
    try:
        texts.append(spec.unknown_rule())
        texts.append(spec.columns())
    except Exception as e:  # noqa: BLE001
        probs.append(f"문구 오류 {type(e).__name__}")
    blob = "\n".join(t for t in texts if isinstance(t, str))
    if _MAIL_RX.search(blob):
        probs.append("머리말에 메일 주소")
    if _IPV4_RX.search(blob):
        probs.append("머리말에 IPv4")
    if TIME_TEXT_RX.search(blob):
        probs.append("머리말에 시간 수치(G-B8)")
    low = blob.lower()
    for w in codename_words or ():
        if isinstance(w, str) and w.strip() and w.strip().lower() in low:
            probs.append("머리말에 코드네임 사전 단어")
            break
    probe = _Probe(sample_fields)
    if spec.kind != "lookup":
        try:
            fb = spec.fallback(probe, ctx, "ai_failed")
        except Exception as e:  # noqa: BLE001
            fb = None
            probs.append(f"fallback 오류 {type(e).__name__}")
        if not isinstance(fb, dict):
            probs.append("폴백 없음")
    stub = spec.stub_answer(probe)
    if not isinstance(stub, dict):
        probs.append("스텁 고정 답 없음")
    elif spec.kind != "lookup":
        ans, err, _c = check_item(spec, stub, ctx)
        if err:
            probs.append(f"스텁 답 형식 {err}")
    return probs
