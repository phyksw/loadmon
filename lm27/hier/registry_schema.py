# -*- coding: utf-8 -*-
"""레지스트리 검증기(H §2.4 · §3.3, 계약 §3.19 · §3.20 · §4.5 · X-050 · X-232 · X-234 · X-241).

표준 라이브러리에는 JSON Schema 검증기가 없으므로 H §2.4 스키마와 **같은 검사**를 손으로 한다.
팀 서버 `PUT /api/registry` 검증은 `validate_registry(obj, side="server")` 를 import 해 부른다(단일원 — X-234).

- `validate_registry(obj, side)` → `list[Err]`. side = 'server'(PUT — 거부 항목은 모두 `reject`) |
  'client'(로드 — 파일 단위 위반만 `reject`, 항목 단위는 `drop`(그 항목·값 무시), 경고는 `warn`).
- `validate_local(obj)` → 개인 로컬 레지스트리(`lm27.registry_local/1`, H §3.3) 검사(항상 client 의미).
- `clean_registry(obj)` · `clean_local(obj)` → (client 의미로 걸러 낸 사본 | None, 오류). None = 파일 거부.
- `blocking(errs)` → 파일을 쓸 수 없는 오류(`reject`)가 있는가.

오류 코드(H §2.4 · X-244 `bad_domain` 하나): 스키마 — `missing` `bad_type` `bad_value` `bad_pattern` `bad_id`
`too_short` `too_long` `too_many` `out_of_range` `unknown_field` `bad_shape` `bad_domain` `bad_domains`
`too_large` `too_deep` `bad_calendar` / 의미 — `dup_id` `reserved_id` `alias_collision` `desc_has_codename`
`merge_cycle` `merge_target_missing` `retired_merge_target` `bad_ref` `generic_keyword` `short_alias`
`never_has_codename` `vocab_legacy_string`.
"""
import copy
import re
import unicodedata
from dataclasses import dataclass

from lm27.hier import match as _match
from lm27.hier import vocab as _vocab
from lm27.hier.names import ukey
from lm27.util.fsx import canon_bytes
from lm27.vocab import steps as _steps

SCHEMA = "lm27.registry/1"
LOCAL_SCHEMA = "lm27.registry_local/1"
SIDES = ("server", "client")
MAX_BYTES = 2 * 1024 * 1024          # 계약 §5.3 레지스트리 크기
MAX_DEPTH = 32                       # 계약 §5.3 JSON 깊이
REJECT, DROP, WARN = "reject", "drop", "warn"

PID_RX = re.compile(r"^P-\d{4}$")
LID_RX = re.compile(r"^L-\d{4}$")
PL_RX = re.compile(r"^[PL]-\d{4}$")
REG_ID_RX = re.compile(r"^[A-Za-z][A-Za-z0-9_\-]{0,23}$")
TOKEN_ID_RX = re.compile(r"^[A-Za-z][A-Za-z0-9_\-]{0,15}$")     # 정제 토큰에 들어가는 ID(고객사·협력사) ≤16자(X-050)
CODE_RX = re.compile(r"^[A-Z][A-Z0-9_]{1,15}$")
LOCAL_CODE_RX = re.compile(r"^L_[A-Z0-9_]{1,14}$")
APP_ID_RX = re.compile(r"^[a-z0-9_.\-]{1,24}$")
MAIL_DOMAIN_RX = re.compile(r"^[a-z0-9.\-]{3,80}$")
EXT_RX = re.compile(r"^\.[0-9a-z_]{1,10}$")    # H §2.4 는 {1,8} 이나 §1.4 내장 표의 .x_t·.kicad_pcb 를 받도록 넓힘
FOLDER_RX = re.compile(r'^[^\\/:*?"<>|]+$')
PERSON_KEY_RX = re.compile(r"^p_[0-9a-f]{12}$")
PROPOSAL_RX = re.compile(r"^pr_\d{1,4}$")
YM_RX = re.compile(r"^\d{4}-\d{2}$")
YM_OPT_RX = re.compile(r"^(\d{4}-\d{2})?$")
CATVER_RX = re.compile(r"^[A-Za-z0-9._\-]{1,24}$")
AGENT_ID_RX = re.compile(r"^AG[A-Za-z0-9_\-]{0,22}$")
PEPPER_RX = re.compile(r"^[0-9a-f]{64}$")
HEX8_RX = re.compile(r"^[0-9a-f]{8}$")
PUBSUF_RX = re.compile(r"^\.[a-z0-9.\-]{2,40}$")

PROJECT_STATUS = ("active", "proposed", "retired")
VOCAB_STATUS = ("active", "retired")
RULE_STATUS = ("active", "off")
AGENT_STATUS = ("running", "planned", "retired")
PUBLIC_CLASSES = ("기관", "학교", "공공", "협회")
RULE_IF = ("token", "sender_label", "domain", "app", "ext", "folder")
RULE_THEN = ("project", "domain", "field", "func", "wtype")
THEN_VOCAB = {"field": "fields", "func": "functions", "wtype": "activity_types"}
LOCAL_FROM = ("user", "bootstrap", "task_label", "codename_review")
CALENDAR_FORBIDDEN = ("std_window", "lunch", "night")         # 근무창은 개인 설정 time.window.*(계약 §3.19)
LOCAL_VOCAB_KINDS = ("fields", "functions", "activity_types")


@dataclass(frozen=True, order=True)
class Err:
    """검증 오류 하나. level = reject(파일·PUT 거부) | drop(그 항목·값 무시) | warn(경고만)."""
    path: str
    code: str
    level: str = REJECT
    detail: str = ""

    def __str__(self) -> str:
        return f"{self.code}:{self.path}"


def blocking(errs) -> bool:
    """reject 수준 오류가 하나라도 있으면 True — 그 레지스트리(사본·캐시·PUT 본문)는 쓰지 않는다."""
    return any(e.level == REJECT for e in errs)


# ───────────────────────── 검사 문맥 ─────────────────────────
class _Ctx:
    """sev: 'F' 파일 단위(양쪽 reject) · 'R' 거부(server reject / client drop) · 'W' 경고."""

    def __init__(self, side: str):
        if side not in SIDES:
            raise ValueError(f"registry_schema: side 는 {SIDES} 중 하나")
        self.side = side
        self.errs: list[Err] = []

    def add(self, path: str, code: str, sev: str = "R", detail: str = "") -> None:
        if sev == "F":
            level = REJECT
        elif sev == "W":
            level = WARN
        else:
            level = REJECT if self.side == "server" else DROP
        self.errs.append(Err(path, code, level, detail))

    def result(self) -> list[Err]:
        return sorted(set(self.errs))


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v) -> bool:
    return (isinstance(v, int | float)) and not isinstance(v, bool) and v == v and v not in (float("inf"),
                                                                                              float("-inf"))


# 검사기: chk(ctx, v, path) -> (ok, 걸러 낸 값)
def _s(minl=0, maxl=None, rx=None, code="bad_pattern", enum=None, enum_code="bad_value"):
    def chk(ctx, v, path):
        if not isinstance(v, str):
            ctx.add(path, "bad_type")
            return False, None
        if minl and len(v) < minl:
            ctx.add(path, "too_short")
            return False, None
        if maxl is not None and len(v) > maxl:
            ctx.add(path, "too_long")
            return False, None
        if enum is not None and v not in enum:
            ctx.add(path, enum_code)
            return False, None
        if rx is not None and not rx.match(v):
            ctx.add(path, code)
            return False, None
        return True, v
    return chk


def _bool(ctx, v, path):
    if not isinstance(v, bool):
        ctx.add(path, "bad_type")
        return False, None
    return True, v


def _int(lo=None, hi=None):
    def chk(ctx, v, path):
        if not _is_int(v):
            ctx.add(path, "bad_type")
            return False, None
        if (lo is not None and v < lo) or (hi is not None and v > hi):
            ctx.add(path, "out_of_range")
            return False, None
        return True, v
    return chk


def _num(lo=None, hi=None):
    def chk(ctx, v, path):
        if not _is_num(v):
            ctx.add(path, "bad_type")
            return False, None
        if (lo is not None and v < lo) or (hi is not None and v > hi):
            ctx.add(path, "out_of_range")
            return False, None
        return True, v
    return chk


def _nullable(inner):
    def chk(ctx, v, path):
        if v is None:
            return True, None
        return inner(ctx, v, path)
    return chk


def _code_or_empty(ctx, v, path):
    if v == "":
        return True, ""
    return _s(rx=CODE_RX)(ctx, v, path)


def _list(max_items=None, item=None, min_items=0):
    """목록 — 틀린 원소는 하나씩 버리고(오류 기록), 상한을 넘으면 too_many 후 앞에서부터 상한까지만 남긴다."""
    def chk(ctx, v, path):
        if not isinstance(v, list):
            ctx.add(path, "bad_type")
            return False, None
        if len(v) < min_items:
            ctx.add(path, "bad_shape")
            return False, None
        vals = v
        if max_items is not None and len(v) > max_items:
            ctx.add(path, "too_many")
            vals = v[:max_items]
        out = []
        for j, x in enumerate(vals):
            if item is None:
                out.append(x)
                continue
            ok, val = item(ctx, x, f"{path}[{j}]")
            if ok:
                out.append(val)
        return True, out
    return chk


def _obj(fields, required=(), closed=False):
    """객체 — 필수 필드가 틀리면 항목 전체가 무효(False). 선택 필드가 틀리면 그 필드만 뺀다."""
    def chk(ctx, v, path):
        if not isinstance(v, dict):
            ctx.add(path, "bad_type")
            return False, None
        ok_all = True
        out = {}
        for name in required:
            if name not in v:
                ctx.add(f"{path}.{name}", "missing")
                ok_all = False
        for name, val in v.items():
            sub = f"{path}.{name}"
            if name in fields:
                ok, cv = fields[name](ctx, val, sub)
                if ok:
                    out[name] = cv
                elif name in required:
                    ok_all = False
            elif closed:
                ctx.add(sub, "unknown_field")
            else:
                out[name] = copy.deepcopy(val)
        return ok_all, out
    return chk


def _map(key_rx, key_code, value, max_props=None, key_check=None):
    """{키: 값} 사전 — 키 형식·값 검사, 틀린 쌍은 버린다."""
    def chk(ctx, v, path):
        if not isinstance(v, dict):
            ctx.add(path, "bad_type")
            return False, None
        items = list(v.items())
        if max_props is not None and len(items) > max_props:
            ctx.add(path, "too_many")
            items = items[:max_props]
        out = {}
        for k, x in items:
            sub = f"{path}.{k}"
            if key_check is not None:
                if not key_check(ctx, k, sub):
                    continue
            elif not isinstance(k, str) or (key_rx is not None and not key_rx.match(k)):
                ctx.add(sub, key_code)
                continue
            ok, cv = value(ctx, x, sub)
            if ok:
                out[k] = cv
        return True, out
    return chk


# ───────────────────────── 필드 정의(H §2.4 스키마) ─────────────────────────
_KW = _s(2, 40)
_MAIL_DOMAIN = _s(rx=MAIL_DOMAIN_RX)
_APP_ID = _s(rx=APP_ID_RX)
_EXT = _s(rx=EXT_RX)
_DOMAIN_CODE = _s(enum=_vocab.DOMAINS, enum_code="bad_domain")


def _alias_item(ctx, v, path):
    """별칭·코드네임: 형식(문자열 ≤40) + 짧은 이름(한글 포함 < 2자, ASCII < 3자 — P §8.3 과 같은 문턱)."""
    if not isinstance(v, str):
        ctx.add(path, "bad_type")
        return False, None
    if len(v) > 40:
        ctx.add(path, "too_long")
        return False, None
    t = unicodedata.normalize("NFKC", v).strip()
    need = 3 if t.isascii() else 2
    if len(t) < need:
        ctx.add(path, "short_alias")
        return False, None
    return True, v


_DOMAIN_OVERRIDE = _obj({"desc": _s(maxl=60), "keywords_add": _list(50, _KW), "keywords_remove": _list(50, _KW)},
                        closed=True)
_DOMAIN_META = _map(None, "bad_domain", _DOMAIN_OVERRIDE,
                    key_check=lambda ctx, k, p: k in _vocab.DOMAINS or (ctx.add(p, "bad_domain") or False))
_PARTY = _obj({"id": _s(rx=TOKEN_ID_RX, code="bad_id"), "names": _list(None, _s(maxl=40)),
               "domains": _list(None, _MAIL_DOMAIN)}, required=("id",))
_PERIOD = _obj({"from": _s(rx=YM_RX), "to": _s(rx=YM_OPT_RX)})
_ADOPTED = _obj({"person_key": _s(rx=PERSON_KEY_RX), "proposal_id": _s(rx=PROPOSAL_RX)},
                required=("person_key", "proposal_id"))


def _pid_chk(reserved_ok=False, rx=PID_RX):
    def chk(ctx, v, path):
        if not isinstance(v, str):
            ctx.add(path, "bad_type")
            return False, None
        if not reserved_ok and _vocab.is_reserved_id(v):
            ctx.add(path, "reserved_id")             # 팀·개인 파일 어디에도 P-99xx 는 둘 수 없다(G-H6)
            return False, None
        if not rx.match(v):
            ctx.add(path, "bad_id")
            return False, None
        return True, v
    return chk


_PROJECT_FIELDS = {
    "id": _pid_chk(),
    "name": _s(1, 40),
    "domain": _DOMAIN_CODE,
    "status": _s(enum=PROJECT_STATUS),
    "merged_into": _nullable(_s(rx=PID_RX, code="bad_id")),
    "aliases": _list(20, _alias_item),
    "codenames": _list(20, _alias_item),
    "mask_name": _bool,
    "keywords": _list(30, _KW),
    "never": _list(20, _KW),
    "mail_domains": _list(20, _MAIL_DOMAIN),
    "customers": _list(10, _s(rx=TOKEN_ID_RX, code="bad_id")),
    "partners": _list(10, _s(rx=TOKEN_ID_RX, code="bad_id")),
    "folders": _list(20, _s(2, 60, FOLDER_RX)),
    "apps": _list(10, _APP_ID),
    "default_field": _code_or_empty,
    "default_func": _code_or_empty,
    "ax_link": _bool,
    "shared_docs": _list(20, _s(2, 80)),
    "copilot_desc": _s(maxl=40),
    "period": _PERIOD,
    "adopted": _list(100, _ADOPTED),
    "created_at": _s(),
    "note": _s(maxl=200),
}
_PROJECT = _obj(_PROJECT_FIELDS, required=("id", "name", "domain"))

_VOCAB_ITEM_FIELDS = {
    "code": _s(rx=CODE_RX),
    "name": _s(1, 20),
    "keywords": _list(30, _KW),
    "apps": _list(30, _APP_ID),
    "exts": _list(30, _EXT),
    "status": _s(enum=VOCAB_STATUS),
    "replaced_by": _code_or_empty,
}
_STEP_EXTRA = {
    "tool_access": _int(0, 2),
    "verifiable": _int(0, 2),
    "kind": _s(enum=("M", "A")),
    "cls": _s(enum=_steps.CLASSES),
}


def _vocab_list(kind):
    fields = dict(_VOCAB_ITEM_FIELDS)
    if kind == "step_types":
        fields.update(_STEP_EXTRA)
    item_obj = _obj(fields, required=("code", "name"))

    def item(ctx, v, path):
        if isinstance(v, str):
            if len(v) > 20 or not v.strip():
                ctx.add(path, "too_long" if v.strip() else "too_short")
                return False, None
            ctx.add(path, "vocab_legacy_string", "W")
            return True, {"code": _vocab.legacy_code(v, kind), "name": v.strip(), "status": "active", "legacy": True}
        return item_obj(ctx, v, path)
    return _list(100, item)


_VOCAB = _obj({k: _vocab_list(k) for k in _vocab.VOCAB_KINDS})


def _one_key(allowed, checks):
    """규칙 if·then: 아래 키 중 정확히 하나."""
    def chk(ctx, v, path):
        if not isinstance(v, dict):
            ctx.add(path, "bad_type")
            return False, None
        extra = [k for k in v if k not in allowed]
        for k in extra:
            ctx.add(f"{path}.{k}", "unknown_field")
        if extra:
            return False, None
        if len(v) != 1:
            ctx.add(path, "bad_shape")
            return False, None
        (k, x), = v.items()
        ok, cv = checks[k](ctx, x, f"{path}.{k}")
        return (True, {k: cv}) if ok else (False, None)
    return chk


_RULE = _obj({
    "id": _s(rx=re.compile(r"^TR[A-Za-z0-9_\-]{0,22}$"), code="bad_id"),
    "if": _one_key(RULE_IF, {"token": _KW, "sender_label": _s(1, 80), "domain": _MAIL_DOMAIN, "app": _APP_ID,
                             "ext": _EXT, "folder": _s(2, 60, FOLDER_RX)}),
    "then": _one_key(RULE_THEN, {"project": _s(rx=PID_RX, code="bad_id"), "domain": _DOMAIN_CODE,
                                 "field": _s(rx=CODE_RX), "func": _s(rx=CODE_RX), "wtype": _s(rx=CODE_RX)}),
    "w": _num(0.5, 6.0),
    "status": _s(enum=RULE_STATUS),
    "note": _s(maxl=60),
}, required=("id", "if", "then"))

_AGENT = _obj({
    "id": _s(rx=AGENT_ID_RX, code="bad_id"),
    "name": _s(2, 30),
    "axis": _s(maxl=24),
    "status": _s(enum=AGENT_STATUS),
    "desc": _s(maxl=200),
    "copilot_desc": _s(maxl=80),
    "step_types": _list(10, _s(rx=CODE_RX)),
    "inputs": _list(5, _s(maxl=20)),
    "outputs": _list(5, _s(maxl=20)),
    "keywords": _list(20, _KW),
    "owner_label": _s(maxl=20),
}, required=("id", "name"))

_PAIR = _list(2, _s(1, 40), min_items=2)


def _pair(ctx, v, path):
    if isinstance(v, list) and len(v) != 2:
        ctx.add(path, "bad_shape")
        return False, None
    ok, cv = _PAIR(ctx, v, path)
    if ok and len(cv) != 2:
        return False, None
    return ok, cv


_AGENTS_META = _obj({"catalog_version": _s(rx=CATVER_RX), "axes": _map(None, "bad_type", _s(maxl=60))})
_PUBLIC_CLASSES = _map(PUBSUF_RX, "bad_pattern", _s(enum=PUBLIC_CLASSES), max_props=50)

# 최상위 선택 필드(형식 위반은 그 필드만 무시 — client)
_TOP_OPTIONAL = {
    "updated_at": _s(),
    "updated_label": _s(maxl=20),
    "team": _obj({"label": _s(maxl=20)}),
    "pepper": _s(rx=PEPPER_RX),
    "pepper_id": _s(rx=HEX8_RX),
    "domain_meta": _DOMAIN_META,
    "members": _list(),
    "vocab": _VOCAB,
    "never_pairs": _list(500, _pair),
    "agents_meta": _AGENTS_META,
    "internal_domains": _list(None, _MAIL_DOMAIN),
    "customers": _list(None, _PARTY),
    "partners": _list(None, _PARTY),
    "public_domain_classes": _PUBLIC_CLASSES,
}
# 최상위 목록(형이 틀리면 파일 단위 위반 — 구조가 깨진 레지스트리는 쓰지 않는다)
_TOP_LISTS = {"projects": (500, _PROJECT), "rules": (500, _RULE), "agents": (200, _AGENT)}


# ───────────────────────── 크기·깊이 ─────────────────────────
def _depth(o, d=1) -> int:
    if isinstance(o, dict):
        return max([d] + [_depth(v, d + 1) for v in o.values()])
    if isinstance(o, list):
        return max([d] + [_depth(v, d + 1) for v in o])
    return d


def _size_checks(ctx, obj) -> bool:
    try:
        n = len(canon_bytes(obj))
    except (TypeError, ValueError):
        ctx.add("", "bad_type", "F")
        return False
    if n > MAX_BYTES:
        ctx.add("", "too_large", "F", str(n))
        return False
    if _depth(obj) > MAX_DEPTH:
        ctx.add("", "too_deep", "F")
        return False
    return True


# ───────────────────────── 의미 검사(H §2.4 '스키마 밖') ─────────────────────────
def _generic_words() -> frozenset[str]:
    """범용어(ukey): 상용구 · 범용 파일 이름 · 기능·업무 유형 어휘 키워드 · 영역 키워드 — 선언 기본값 기준.
    분야 어휘 키워드(브라켓·렌즈 같은 부품·기술 명사)는 과제 키워드로 쓰일 수 있어 넣지 않는다."""
    from lm27.config import registry_meta          # 지연 import — 설정 레지스트리 선언 기본값만 읽는다
    words = set(_match.boilerplate())
    words.update(str(w) for w in registry_meta("episode.docs.genericStems").default)
    for kind in ("functions", "activity_types"):
        for it in _vocab.BUILTIN_VOCAB[kind]:
            words.update(it.keywords)
    for c in _vocab.DOMAINS:
        words.update(_vocab.DOMAIN_META[c]["keywords"])
    return frozenset(k for k in (ukey(w) for w in words) if k)


def _code_keys(p: dict, aliases: bool) -> set[str]:
    """과제 하나의 '가려야 할 이름' ukey: 코드네임(+ mask_name 이면 이름) (+ aliases=True 면 별칭)."""
    names = list(p.get("codenames", []))
    if aliases:
        names += list(p.get("aliases", []))
    if p.get("mask_name"):
        names.append(p.get("name", ""))
    return {k for k in (ukey(x) for x in names) if len(k) >= 2}


def _semantic_projects(ctx, projects: list[tuple[int, dict, bool]], customers: set, partners: set,
                       fields: set, funcs: set) -> list[tuple[int, dict, bool]]:
    """dup_id · alias_collision · desc_has_codename · never_has_codename · generic_keyword · bad_ref · merge 사슬.
    입력·출력 = (원래 위치, 과제, 유효 여부). 무효 과제(ID 는 맞음)도 충돌·사슬 검사에는 넣는다(서버가 모든 사유를 보이게)."""
    out, seen = [], set()
    for i, p, ok in projects:
        if p["id"] in seen:
            ctx.add(f"projects[{i}].id", "dup_id")
            continue
        seen.add(p["id"])
        out.append((i, p, ok))
    generic = _generic_words()
    names: dict[str, str] = {}
    all_desc_keys = set()
    for _i, p, _ok in out:
        all_desc_keys |= _code_keys(p, aliases=True)
    code_only = set()
    for _i, p, _ok in out:
        code_only |= _code_keys(p, aliases=False)
    for i, p, _ok in out:
        pid = p["id"]
        # 별칭 충돌(이름·별칭·코드네임 ukey 가 서로 다른 과제끼리) — 먼저 정의된 쪽 유지
        k0 = ukey(p.get("name", ""))
        if k0 and k0 in names and names[k0] != pid:
            ctx.add(f"projects[{i}]", "alias_collision")
        elif k0:
            names.setdefault(k0, pid)
        for fld in ("aliases", "codenames"):
            keep = []
            for a in p.get(fld, []):
                k = ukey(a)
                if k and k in names and names[k] != pid:
                    ctx.add(f"projects[{i}]", "alias_collision")
                    continue
                if k:
                    names.setdefault(k, pid)
                keep.append(a)
            if fld in p:
                p[fld] = keep
        # 범용어 키워드·별칭 — 경고, 분류에서 그 낱말 무시
        for fld in ("keywords", "aliases"):
            if fld in p:
                keep = []
                for j, w in enumerate(p[fld]):
                    if ukey(w) in generic:
                        ctx.add(f"projects[{i}].{fld}[{j}]", "generic_keyword", "W")
                        continue
                    keep.append(w)
                p[fld] = keep
        # 코파일럿 설명에 코드네임·별칭·(mask_name) 이름
        desc = ukey(p.get("copilot_desc", ""))
        if desc and any(k in desc for k in all_desc_keys):
            ctx.add(f"projects[{i}].copilot_desc", "desc_has_codename")
            p["copilot_desc"] = ""
        for j, w in enumerate(p.get("never", [])):
            kw = ukey(w)
            if any(k in kw for k in code_only):
                ctx.add(f"projects[{i}].never[{j}]", "never_has_codename", "W")
        # 참조
        for fld, known in (("customers", customers), ("partners", partners)):
            if fld in p:
                keep = []
                for j, c in enumerate(p[fld]):
                    if c not in known:
                        ctx.add(f"projects[{i}].{fld}[{j}]", "bad_ref")
                        continue
                    keep.append(c)
                p[fld] = keep
        for fld, known in (("default_field", fields), ("default_func", funcs)):
            v = p.get(fld, "")
            if v and v not in known:
                ctx.add(f"projects[{i}].{fld}", "bad_ref")
                p[fld] = ""
    # merged_into 사슬 — 순환·없는 대상·퇴역 대상
    nxt = {p["id"]: p.get("merged_into") for _i, p, _ok in out}
    stat = {p["id"]: p.get("status", "active") for _i, p, _ok in out}
    broken = set()
    for s in nxt:
        t = nxt.get(s)
        if t and t not in nxt:
            ctx.add(f"projects[{s}].merged_into", "merge_target_missing")
            broken.add(s)
            continue
        seen_c, cur = set(), s
        while cur and nxt.get(cur):
            if cur in seen_c:
                ctx.add(f"projects[{s}]", "merge_cycle")
                broken.add(s)
                break
            seen_c.add(cur)
            cur = nxt.get(cur)
        if t and s not in broken and stat.get(t) == "retired" and not nxt.get(t):
            ctx.add(f"projects[{s}].merged_into", "retired_merge_target", "W")
    for _i, p, _ok in out:
        if p["id"] in broken:
            p["merged_into"] = None
    return out


def _check_registry(obj, side: str):
    """(걸러 낸 사본 | None, 오류 목록). None = 파일 단위 거부."""
    ctx = _Ctx(side)
    if not isinstance(obj, dict):
        ctx.add("", "bad_type", "F")
        return None, ctx.result()
    if not _size_checks(ctx, obj):
        return None, ctx.result()
    clean: dict = {}
    fatal = False
    if "schema" not in obj:
        ctx.add("schema", "missing", "F")
        fatal = True
    elif obj["schema"] != SCHEMA:
        ctx.add("schema", "bad_value", "F")
        fatal = True
    if "version" not in obj:
        ctx.add("version", "missing", "F")
        fatal = True
    elif not _is_int(obj["version"]):
        ctx.add("version", "bad_type", "F")
        fatal = True
    elif obj["version"] < 0:
        ctx.add("version", "out_of_range", "F")
        fatal = True
    if "domains" in obj and obj["domains"] != list(_vocab.ALL_DOMAINS):
        ctx.add("domains", "bad_domains", "F")
        fatal = True
    if not fatal:
        clean["schema"] = SCHEMA
        clean["version"] = obj["version"]
        if "domains" in obj:
            clean["domains"] = list(_vocab.ALL_DOMAINS)
    for name, chk in _TOP_OPTIONAL.items():
        if name in obj:
            ok, cv = chk(ctx, obj[name], name)
            if ok:
                clean[name] = cv
    for name, (mx, item) in _TOP_LISTS.items():
        if name not in obj:
            continue
        v = obj[name]
        if not isinstance(v, list):
            ctx.add(name, "bad_type", "F")
            fatal = True
            continue
        vals = v
        if len(v) > mx:
            ctx.add(name, "too_many")
            vals = v[:mx]
        items = []
        for i, x in enumerate(vals):
            ok, cv = item(ctx, x, f"{name}[{i}]")
            if ok:
                items.append((i, cv, True))
            elif name == "projects" and isinstance(cv, dict) and "id" in cv:
                items.append((i, cv, False))         # ID 는 맞는 무효 과제 — 의미 검사(충돌·사슬)에는 넣고 결과에서는 뺀다
        clean[name] = items
    if "calendar" in obj:
        cal = _check_calendar(ctx, obj["calendar"])
        if cal is not None:
            clean["calendar"] = cal
    # 의미 검사
    customers = _party_ids(ctx, clean, "customers")
    partners = _party_ids(ctx, clean, "partners")
    vocab_codes = _vocab_semantic(ctx, clean)
    projects = _semantic_projects(ctx, clean.get("projects", []), customers, partners,
                                  vocab_codes["fields"], vocab_codes["functions"])
    clean["projects"] = [p for _i, p, ok in projects if ok]
    pids = {p["id"] for p in clean["projects"]}
    clean["rules"] = _semantic_rules(ctx, [(i, r) for i, r, _ok in clean.get("rules", [])], pids, vocab_codes)
    clean["agents"] = _semantic_agents(ctx, clean, vocab_codes)
    _semantic_domain_meta(ctx, clean, projects)
    if fatal:
        return None, ctx.result()
    return clean, ctx.result()


def _check_calendar(ctx, cal):
    """레지스트리 calendar(계약 §3.21 모양). 형식은 lm27.time.calendar 의 검증기 하나로 본다."""
    if not isinstance(cal, dict):
        ctx.add("calendar", "bad_type")
        return None
    bad = [k for k in CALENDAR_FORBIDDEN if k in cal]
    for k in bad:
        ctx.add(f"calendar.{k}", "unknown_field")
    if bad:
        return None
    from lm27.time.calendar import Calendar         # 지연 import — lm27.time 은 다른 작업 패키지와 나눠 쓰는 패키지
    try:
        Calendar.from_obj(cal)
    except (ValueError, TypeError, KeyError) as e:
        ctx.add("calendar", "bad_calendar", detail=type(e).__name__)
        return None
    return copy.deepcopy(cal)


def _party_ids(ctx, clean, name) -> set[str]:
    out, seen = [], set()
    for j, p in enumerate(clean.get(name, [])):
        if p["id"] in seen:
            ctx.add(f"{name}[{j}].id", "dup_id")
            continue
        seen.add(p["id"])
        out.append(p)
    if name in clean:
        clean[name] = out
    return seen


def _vocab_semantic(ctx, clean) -> dict[str, set[str]]:
    """어휘 코드 중복·replaced_by 참조. 반환 = 종류별 유효 코드(내장 ∪ 팀)."""
    codes = {k: set(_vocab.builtin_codes(k)) for k in _vocab.VOCAB_KINDS}
    voc = clean.get("vocab")
    if not isinstance(voc, dict):
        return codes
    for kind in _vocab.VOCAB_KINDS:
        if kind not in voc:
            continue
        seen, keep = set(), []
        for j, it in enumerate(voc[kind]):
            if it["code"] in seen:
                ctx.add(f"vocab.{kind}[{j}].code", "dup_id")
                continue
            seen.add(it["code"])
            keep.append((j, it))
        team_codes = seen
        known = codes[kind] | team_codes
        for j, it in keep:
            rb = it.get("replaced_by", "")
            if rb and rb not in known:
                ctx.add(f"vocab.{kind}[{j}].replaced_by", "bad_ref")
                it["replaced_by"] = ""
        voc[kind] = [it for _j, it in keep]
        codes[kind] = known
    return codes


def _semantic_rules(ctx, rules, pids, vocab_codes) -> list[dict]:
    out, seen = [], set()
    for i, r in rules:
        if r["id"] in seen:
            ctx.add(f"rules[{i}].id", "dup_id")
            continue
        seen.add(r["id"])
        (k, v), = r["then"].items()
        if k == "project" and v not in pids and v not in _vocab.RESERVED:
            ctx.add(f"rules[{i}].then.project", "bad_ref")
            continue
        if k in THEN_VOCAB and v not in vocab_codes[THEN_VOCAB[k]]:
            ctx.add(f"rules[{i}].then.{k}", "bad_ref")
            continue
        out.append(r)
    return out


def _semantic_agents(ctx, clean, vocab_codes) -> list[dict]:
    axes = set()
    meta = clean.get("agents_meta")
    if isinstance(meta, dict) and isinstance(meta.get("axes"), dict):
        axes = set(meta["axes"])
    keys = set()
    for p in clean.get("projects", []):
        keys |= _code_keys(p, aliases=True)
    out, seen = [], set()
    for i, a, _ok in clean.get("agents", []):
        if a["id"] in seen:
            ctx.add(f"agents[{i}].id", "dup_id")
            continue
        seen.add(a["id"])
        if a.get("axis") and a["axis"] not in axes:
            ctx.add(f"agents[{i}].axis", "bad_ref")
            a.pop("axis")
        if "step_types" in a:
            keep = []
            for j, c in enumerate(a["step_types"]):
                if c not in vocab_codes["step_types"]:
                    ctx.add(f"agents[{i}].step_types[{j}]", "bad_ref")
                    continue
                keep.append(c)
            a["step_types"] = keep
        d = ukey(a.get("copilot_desc", ""))
        if d and any(k in d for k in keys):
            ctx.add(f"agents[{i}].copilot_desc", "desc_has_codename")
            a["copilot_desc"] = ""
        out.append(a)
    return out


def _semantic_domain_meta(ctx, clean, projects) -> None:
    dm = clean.get("domain_meta")
    if not isinstance(dm, dict):
        return
    keys = set()
    for _i, p, _ok in projects:
        keys |= _code_keys(p, aliases=True)
    for c, ov in dm.items():
        d = ukey(ov.get("desc", ""))
        if d and any(k in d for k in keys):
            ctx.add(f"domain_meta.{c}.desc", "desc_has_codename")
            ov["desc"] = ""


# ───────────────────────── 공개 함수(팀 레지스트리) ─────────────────────────
def validate_registry(obj, side: str = "client") -> list[Err]:
    """팀 레지스트리 검증(H §2.4). side='server' 는 팀 서버 PUT(거부 = reject), 'client' 는 로드(항목 무시 = drop)."""
    if side not in SIDES:
        raise ValueError(f"registry_schema: side 는 {SIDES} 중 하나")
    return _check_registry(obj, side)[1]


def clean_registry(obj) -> tuple[dict | None, list[Err]]:
    """client 의미로 걸러 낸 사본과 오류. 파일 단위 거부면 (None, 오류). 입력은 바꾸지 않는다."""
    return _check_registry(obj, "client")


# ───────────────────────── 개인 로컬 레지스트리(H §3.3) ─────────────────────────
_LOCAL_PROJECT_FIELDS = dict(_PROJECT_FIELDS)
_LOCAL_PROJECT_FIELDS.pop("adopted")
_LOCAL_PROJECT_FIELDS.update({
    "id": _pid_chk(rx=LID_RX),
    "proposal_id": _nullable(_s(rx=PROPOSAL_RX)),
    "maps_to": _nullable(_pid_chk()),
    "created_from": _s(enum=LOCAL_FROM),
})
_LOCAL_PROJECT = _obj(_LOCAL_PROJECT_FIELDS, required=("id", "name", "domain"))


def _overlay_key(ctx, k, path) -> bool:
    if not isinstance(k, str) or not PID_RX.match(k):
        ctx.add(path, "bad_id")
        return False
    if _vocab.is_reserved_id(k):
        ctx.add(path, "reserved_id")
        return False
    return True


_OVERLAY = _obj({"aliases": _list(20, _alias_item), "keywords": _list(30, _KW), "never": _list(20, _KW),
                 "folders": _list(20, _s(2, 60, FOLDER_RX)), "mail_domains": _list(20, _MAIL_DOMAIN),
                 "default_field": _code_or_empty}, closed=True)
_LOCAL_VOCAB_ITEM = _obj({"code": _s(rx=LOCAL_CODE_RX), "name": _s(1, 20), "keywords": _list(30, _KW),
                          "apps": _list(30, _APP_ID), "exts": _list(30, _EXT), "maps_to": _code_or_empty,
                          "status": _s(enum=VOCAB_STATUS)}, required=("code", "name"))
_LOCAL_TOP = {
    "updated_at": _s(),
    "overlays": _map(None, "bad_id", _OVERLAY, key_check=_overlay_key),
    "roots": _map(REG_ID_RX, "bad_id", _s(rx=PL_RX, code="bad_id")),
    "domain_meta": _DOMAIN_META,
    "vocab_add": _obj({k: _list(100, _LOCAL_VOCAB_ITEM) for k in LOCAL_VOCAB_KINDS}, closed=True),
    "never_pairs": _list(500, _pair),
    "person": _obj({"default_field": _code_or_empty, "default_func": _code_or_empty}),
    "codename_review": _obj({"done_at": _s(), "ignored": _list(None, _s(rx=HEX8_RX)), "skipped": _bool}),
}


def _check_local(obj):
    ctx = _Ctx("client")
    if not isinstance(obj, dict):
        ctx.add("", "bad_type", "F")
        return None, ctx.result()
    if not _size_checks(ctx, obj):
        return None, ctx.result()
    if "schema" not in obj:
        ctx.add("schema", "missing", "F")
        return None, ctx.result()
    if obj["schema"] != LOCAL_SCHEMA:
        ctx.add("schema", "bad_value", "F")
        return None, ctx.result()
    clean: dict = {"schema": LOCAL_SCHEMA}
    for name, chk in _LOCAL_TOP.items():
        if name in obj:
            ok, cv = chk(ctx, obj[name], name)
            if ok:
                clean[name] = cv
    projects = []
    if "projects" in obj:
        v = obj["projects"]
        if not isinstance(v, list):
            ctx.add("projects", "bad_type", "F")
            return None, ctx.result()
        if len(v) > 500:
            ctx.add("projects", "too_many")
            v = v[:500]
        seen_id, seen_pr = set(), set()
        for i, x in enumerate(v):
            ok, p = _LOCAL_PROJECT(ctx, x, f"projects[{i}]")
            if not ok:
                continue
            if p["id"] in seen_id:
                ctx.add(f"projects[{i}].id", "dup_id")
                continue
            seen_id.add(p["id"])
            pr = p.get("proposal_id")
            if pr:
                if pr in seen_pr:
                    ctx.add(f"projects[{i}].proposal_id", "dup_id")
                    p["proposal_id"] = None
                else:
                    seen_pr.add(pr)
            projects.append((i, p))
    keys = set()
    for _i, p in projects:
        keys |= _code_keys(p, aliases=True)
    for i, p in projects:                            # 개인 과제 설명도 코파일럿에 간다 — 코드네임·별칭이 들면 비운다
        d = ukey(p.get("copilot_desc", ""))
        if d and any(k in d for k in keys):
            ctx.add(f"projects[{i}].copilot_desc", "desc_has_codename")
            p["copilot_desc"] = ""
    clean["projects"] = [p for _i, p in projects]
    va = clean.get("vocab_add")
    if isinstance(va, dict):
        for kind, items in va.items():
            seen, keep = set(), []
            for j, it in enumerate(items):
                if it["code"] in seen:
                    ctx.add(f"vocab_add.{kind}[{j}].code", "dup_id")
                    continue
                seen.add(it["code"])
                keep.append(it)
            va[kind] = keep
    return clean, ctx.result()


def validate_local(obj) -> list[Err]:
    """개인 로컬 레지스트리 검사(H §3.3). 파일 단위 위반만 reject, 나머지는 drop·warn."""
    return _check_local(obj)[1]


def clean_local(obj) -> tuple[dict | None, list[Err]]:
    """걸러 낸 개인 로컬 레지스트리 사본과 오류. 파일 단위 거부면 (None, 오류)."""
    return _check_local(obj)
