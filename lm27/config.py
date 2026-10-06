# -*- coding: utf-8 -*-
r"""설정 레지스트리 단일원(계약 §5) — ``config\settings_registry.json`` 선언 + ``config\config.json`` 덮어쓰기.

규칙(계약 §5.1):
- 코드가 미등록 키를 읽으면 오류(``UnknownKeyError``). 읽힌 키는 기록되어 ``Cfg.used()`` 로 나온다(cfg_used).
- ``config.json`` 의 값이 형·범위·선택지에 맞지 않으면 기본값을 쓰고 경고를 남긴다(``Cfg.config_warnings``).
- ``config.json`` 의 미등록 키는 무시하고 경고를 남긴다. ``_`` 로 시작하는 키와 ``schema`` 는 설명용으로 조용히 무시한다.
- ``list(+-)`` 형: 값이 그냥 목록이면 내장(선언 기본값)을 대체, ``{"add": [...], "disable": [...]}`` 이면
  (내장 ∪ add) − disable.
- ``obj`` 형: 선언에 고정 키(``keys``)가 있으면 얕은 병합, 없으면 통째 대체.
- 경고 문구에는 값(원문일 수 있음)을 넣지 않는다 — 키와 사유만.

이 모듈은 표준 라이브러리만 쓰고 디스크에 쓰지 않는다(쓰기는 화면 설정 API 가 ``lm27.util.fsx`` 로).
"""
from __future__ import annotations

import copy
import hashlib
import ipaddress
import json
import math
import os
import re
import threading
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

SCHEMA = "lm27.settings_registry/1"

TYPES = frozenset({"int", "float", "bool", "str", "enum", "path", "timerange", "regex", "list", "list(+-)", "obj"})
ITEM_TYPES = frozenset({"str", "path", "regex", "w16", "hostport", "party", "int", "port_range", "cidr", "obj",
                        "float", "bool", "str_list"})
SCOPES = ("personal", "agent", "team_server")
RESTARTS = ("none", "ui", "agent", "team_server")
REQUIRED_FIELDS = ("default", "type", "owner", "readers", "spec", "uncalibrated", "secret", "scope", "restart",
                   "label_ko", "help_ko")
OPTIONAL_FIELDS = ("range", "choices", "item", "keys", "nullable", "pattern")
KEY_RX = re.compile(r"^[a-z][A-Za-z0-9]*(?:\.[a-z][A-Za-z0-9]*)+$")
OWNER_RX = re.compile(r"^(?:lm27(?:\.[a-z][a-z0-9_]*)+|collect/(?:agent/)?[A-Za-z][A-Za-z0-9_-]*\.(?:py|ps1))$")

# 계약 §5.1-8 — 에이전트로 내려가는 키(agent_config.json)
AGENT_SUBSET_PREFIXES = ("agent.", "pc.", "teams.uia.")
AGENT_SUBSET_KEYS = ("teams.timeRegex", "time.tzOffsetMin", "collect.lookbackDays", "collect.sinceYearStart",
                     "privacy.pipe.waitSec", "privacy.audit.retentionMonths")   # sinceYearStart = 수확 창(V6 — 통합)

_TIMERANGE_RX = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d-(?:[01]\d|2[0-3]):[0-5]\d$")
_W16_RX = re.compile(r"^w[0-9a-f]{16}$")
_HOSTPORT_RX = re.compile(r"^(?:[A-Za-z0-9](?:[A-Za-z0-9.\-]{0,251}[A-Za-z0-9])?|\[[0-9A-Fa-f:.]+\]):(\d{1,5})$")
_REGEX_MAX = 200


class ConfigError(Exception):
    """설정 레지스트리 오류의 기반."""


class RegistryError(ConfigError):
    """settings_registry.json 이 없거나 깨졌거나 선언 규칙을 어김(fail-closed)."""


class UnknownKeyError(ConfigError, KeyError):
    """미등록 설정 키를 읽음(계약 §5.1-5)."""

    def __init__(self, key: str):
        super().__init__(key)
        self.key = key

    def __str__(self) -> str:
        return f"미등록 설정 키: {self.key}"


@dataclass(frozen=True)
class KeyMeta:
    """레지스트리 키 하나의 선언(``registry_meta(key)``)."""

    key: str
    default: object
    type: str
    range: dict | None
    choices: tuple | None
    owner: str
    readers: tuple
    spec: str
    uncalibrated: bool
    secret: bool
    scope: str
    restart: str
    label_ko: str
    help_ko: str
    item: str | None = None
    keys: tuple | None = None
    nullable: bool = False
    pattern: str | None = None

    @property
    def is_list_merge(self) -> bool:
        return self.type == "list(+-)"

    @property
    def is_agent(self) -> bool:
        return is_agent_key(self.key)

    def owner_file(self) -> str:
        return owner_file(self.owner)


# ───────────────────────── JSON 읽기(엄격: 중복 키·NaN 거부, utf-8-sig 허용) ─────────────────────────
def _pairs_no_dup(pairs):
    out = {}
    for k, v in pairs:
        if k in out:
            raise ValueError(f"중복 키: {k}")
        out[k] = v
    return out


def _no_constant(name):
    raise ValueError(f"허용하지 않는 수: {name}")


def _loads_strict(raw: bytes):
    """깊은 중첩(RecursionError)도 형식 오류(ValueError)로 — 깨진 config.json 은 경고 + 기본값이어야 한다."""
    try:
        return json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_pairs_no_dup, parse_constant=_no_constant)
    except RecursionError:
        raise ValueError("JSON 중첩이 너무 깊습니다") from None


def _read_bytes(path: Path) -> bytes:
    with open(path, "rb") as f:
        return f.read()


def _canon(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _jsonable(v):
    if isinstance(v, tuple | list):
        return [_jsonable(x) for x in v]
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    return v


def _frozen(v):
    """Cfg 안 저장형: 목록 → 튜플(불변). 사전은 그대로 두고 읽을 때 깊은 사본을 준다."""
    if isinstance(v, list | tuple):
        return tuple(_frozen(x) for x in v)
    if isinstance(v, dict):
        return {k: _frozen(x) for k, x in v.items()}
    return v


# ───────────────────────── 값 검사·정규화 ─────────────────────────
class _Bad(Exception):
    def __init__(self, code: str, text_ko: str):
        super().__init__(code)
        self.code = code
        self.text_ko = text_ko


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v) -> bool:
    return (isinstance(v, int | float) and not isinstance(v, bool)) and math.isfinite(v)


def _check_regex(s: str) -> None:
    if len(s) > _REGEX_MAX:
        raise _Bad("bad_pattern", f"정규식이 {_REGEX_MAX}자를 넘습니다")
    try:
        rx = re.compile(s)
    except re.error:
        raise _Bad("bad_pattern", "정규식으로 읽을 수 없습니다") from None
    if s and rx.search(""):
        raise _Bad("bad_pattern", "빈 문자열에 맞는 정규식은 쓸 수 없습니다")


def _check_pattern(s: str, pattern: str | None) -> None:
    if pattern is not None and not re.search(pattern, s):
        raise _Bad("bad_pattern", "형식이 맞지 않습니다")


def _check_range_num(v, rng: dict | None) -> None:
    if not rng:
        return
    lo, hi, step = rng.get("min"), rng.get("max"), rng.get("step")
    if lo is not None and v < lo:
        raise _Bad("out_of_range", f"{lo} 보다 작습니다")
    if hi is not None and v > hi:
        raise _Bad("out_of_range", f"{hi} 보다 큽니다")
    if step is not None and (v - (lo or 0)) % step:
        raise _Bad("out_of_range", f"{step} 의 배수여야 합니다")


def _check_len(n: int, rng: dict | None) -> None:
    if not rng:
        return
    lo, hi = rng.get("min"), rng.get("max")
    if lo is not None and n < lo:
        raise _Bad("out_of_range", f"원소가 {lo}개보다 적습니다")
    if hi is not None and n > hi:
        raise _Bad("out_of_range", f"원소가 {hi}개보다 많습니다")


def _norm_item(item: str | None, v, pattern: str | None, choices):
    """목록 원소·객체 값 하나를 검사하고 정규화한 값을 돌려준다."""
    bad = _Bad("bad_item", "목록 원소의 형이 맞지 않습니다")
    if item in (None, "str", "path"):
        if not isinstance(v, str):
            raise bad
        _check_pattern(v, pattern)
    elif item == "regex":
        if not isinstance(v, str):
            raise bad
        _check_regex(v)
    elif item == "w16":
        if not isinstance(v, str) or not _W16_RX.match(v):
            raise _Bad("bad_item", "가명 키 형식(w + 16자리 16진)이 아닙니다")
    elif item == "hostport":
        m = _HOSTPORT_RX.match(v) if isinstance(v, str) else None
        if not m or not 1 <= int(m.group(1)) <= 65535:
            raise _Bad("bad_item", "host:port 형식이 아닙니다")
    elif item == "party":
        if not isinstance(v, dict) or not isinstance(v.get("id"), str) or not v["id"]:
            raise _Bad("bad_item", "{id, names, domains} 형식이 아닙니다")
        for f in ("names", "domains"):
            x = v.get(f, [])
            if not isinstance(x, list) or not all(isinstance(s, str) for s in x):
                raise _Bad("bad_item", "{id, names, domains} 형식이 아닙니다")
        if set(v) - {"id", "names", "domains"}:
            raise _Bad("bad_item", "{id, names, domains} 밖의 필드가 있습니다")
    elif item == "int":
        if not _is_int(v) or v < 0:
            raise bad
    elif item == "float":
        if not _is_num(v):
            raise bad
        v = float(v)
    elif item == "bool":
        if not isinstance(v, bool):
            raise bad
    elif item == "port_range":
        if (not isinstance(v, list) or len(v) != 2 or not all(_is_int(x) for x in v)
                or not 1 <= v[0] <= v[1] <= 65535):
            raise _Bad("bad_item", "[시작, 끝] 포트 구간이 아닙니다")
    elif item == "cidr":
        if not isinstance(v, str):
            raise bad
        try:
            ipaddress.ip_network(v, strict=False)
        except ValueError:
            raise _Bad("bad_item", "주소 대역(CIDR) 형식이 아닙니다") from None
    elif item == "obj":
        if not isinstance(v, dict):
            raise bad
    elif item == "str_list":
        if not isinstance(v, list) or not all(isinstance(s, str) for s in v):
            raise bad
    else:  # 선언 검사에서 걸러진다
        raise bad
    if choices is not None and v not in choices:
        raise _Bad("bad_choice", "허용된 값이 아닙니다")
    return v


def _norm_list(meta: KeyMeta, v) -> list:
    if not isinstance(v, list | tuple):
        raise _Bad("bad_type", "목록이어야 합니다")
    out = [_norm_item(meta.item, x, meta.pattern, meta.choices) for x in v]
    _check_len(len(out), meta.range)
    return out


def _normalize(meta: KeyMeta, v):
    """선언(meta)에 맞는 실효 값을 돌려준다. 맞지 않으면 _Bad."""
    t = meta.type
    if v is None:
        if meta.nullable:
            return None
        raise _Bad("bad_type", "빈 값(null)은 허용되지 않습니다")
    if t == "int":
        if not _is_int(v):
            raise _Bad("bad_type", "정수여야 합니다")
        _check_range_num(v, meta.range)
        return v
    if t == "float":
        if not _is_num(v):
            raise _Bad("bad_type", "수여야 합니다")
        _check_range_num(v, meta.range)
        return float(v)
    if t == "bool":
        if not isinstance(v, bool):
            raise _Bad("bad_type", "true 또는 false 여야 합니다")
        return v
    if t in ("str", "path", "enum", "timerange", "regex"):
        if not isinstance(v, str):
            raise _Bad("bad_type", "문자열이어야 합니다")
        if t == "enum" and v not in (meta.choices or ()):
            raise _Bad("bad_choice", "허용된 값이 아닙니다: " + "·".join(str(c) for c in meta.choices or ()))
        if t == "timerange" and not _TIMERANGE_RX.match(v):
            raise _Bad("bad_pattern", "HH:MM-HH:MM 형식이 아닙니다")
        if t == "regex" and v:
            _check_regex(v)
        _check_pattern(v, meta.pattern)
        return v
    if t == "list":
        return _norm_list(meta, v)
    if t == "list(+-)":
        if isinstance(v, dict):
            if not v or set(v) - {"add", "disable"}:
                raise _Bad("bad_list_op", "{add, disable} 만 쓸 수 있습니다")
            add = _norm_list(_replace(meta, range=None), v.get("add", []))
            dis = _norm_list(_replace(meta, range=None), v.get("disable", []))
            out = []
            for x in [*meta.default, *add]:
                if x not in out and x not in dis:
                    out.append(x)
            _check_len(len(out), meta.range)
            return out
        return _norm_list(meta, v)
    if t == "obj":
        if not isinstance(v, dict):
            raise _Bad("bad_type", "객체여야 합니다")
        if meta.keys is not None:
            extra = set(v) - set(meta.keys)
            if extra:
                raise _Bad("bad_item", "선언에 없는 하위 키가 있습니다")
            merged = copy.deepcopy(meta.default)
            for k, x in v.items():
                merged[k] = _norm_item(meta.item, x, None, None)
            return merged
        return {k: _norm_item(meta.item, x, meta.pattern, None) for k, x in v.items()}
    raise _Bad("bad_type", "알 수 없는 형")


def _replace(meta: KeyMeta, **kw) -> KeyMeta:
    d = {f: getattr(meta, f) for f in meta.__dataclass_fields__}
    d.update(kw)
    return KeyMeta(**d)


# ───────────────────────── 레지스트리 적재·선언 검사 ─────────────────────────
_REG_CACHE: dict = {}
_REG_LOCK = threading.Lock()


def _as_paths(paths):
    """경로는 lm27.paths 로만 만든다(L-08). None = 이 트리, 문자열·PathLike = 그 루트,
    ``settings_registry()``·``config_json()`` 이 있는 객체는 그대로, ``root`` 만 있는 객체는 그 루트로."""
    from lm27.paths import Paths
    if paths is None:
        return Paths()
    if isinstance(paths, str | os.PathLike):
        return Paths(paths)
    if callable(getattr(paths, "settings_registry", None)) and callable(getattr(paths, "config_json", None)):
        return paths
    r = getattr(paths, "root", None)
    if callable(r):
        r = r()
    if r is None:
        raise TypeError("load_config: Paths 가 아니고 root 도 없습니다")
    return Paths(r)


def _registry_path(path=None) -> Path:
    return Path(path) if path is not None else Path(_as_paths(None).settings_registry())


def _meta_from(key: str, d: dict, problems: list) -> KeyMeta | None:
    if not KEY_RX.match(key):
        problems.append(f"{key}: 키 표기 위반(네임스페이스.낱말 camelCase, snake_case 금지)")
        return None
    if not isinstance(d, dict):
        problems.append(f"{key}: 선언이 객체가 아닙니다")
        return None
    miss = [f for f in REQUIRED_FIELDS if f not in d]
    if "range" not in d and "choices" not in d:
        miss.append("range|choices")
    unknown = set(d) - set(REQUIRED_FIELDS) - set(OPTIONAL_FIELDS)
    if miss or unknown:
        problems.append(f"{key}: 필드 누락 {miss} · 미지 필드 {sorted(unknown)}")
        return None
    t = d["type"]
    if t not in TYPES:
        problems.append(f"{key}: 알 수 없는 형 {t}")
        return None
    item = d.get("item")
    if item is not None and item not in ITEM_TYPES:
        problems.append(f"{key}: 알 수 없는 원소 형 {item}")
        return None
    if t in ("list", "list(+-)") and item is None:
        problems.append(f"{key}: 목록 형에 item 이 없습니다")
        return None
    rng = d.get("range")
    if rng is not None and (not isinstance(rng, dict) or set(rng) - {"min", "max", "step"}
                            or not all(_is_num(x) for x in rng.values())):
        problems.append(f"{key}: range 형식 위반")
        return None
    ch = d.get("choices")
    if ch is not None and not isinstance(ch, list):
        problems.append(f"{key}: choices 는 목록이어야 합니다")
        return None
    if t == "enum" and not ch:
        problems.append(f"{key}: enum 에 choices 가 없습니다")
        return None
    keys = d.get("keys")
    if keys is not None and (t != "obj" or not isinstance(keys, list)
                             or not all(isinstance(x, str) for x in keys)):
        problems.append(f"{key}: keys 는 obj 의 문자열 목록이어야 합니다")
        return None
    pat = d.get("pattern")
    if pat is not None:
        try:
            re.compile(pat)
        except (re.error, TypeError):
            problems.append(f"{key}: pattern 을 읽을 수 없습니다")
            return None
    for f, typ in (("owner", str), ("spec", str), ("label_ko", str), ("help_ko", str)):
        if not isinstance(d[f], typ) or not d[f].strip():
            problems.append(f"{key}: {f} 가 비었거나 형이 틀립니다")
            return None
    if not OWNER_RX.match(d["owner"]):
        problems.append(f"{key}: owner 형식 위반({d['owner']})")
        return None
    if not isinstance(d["readers"], list) or not all(isinstance(x, str) and OWNER_RX.match(x) for x in d["readers"]):
        problems.append(f"{key}: readers 형식 위반")
        return None
    for f in ("uncalibrated", "secret"):
        if not isinstance(d[f], bool):
            problems.append(f"{key}: {f} 는 bool 이어야 합니다")
            return None
    if d.get("nullable") is not None and not isinstance(d["nullable"], bool):
        problems.append(f"{key}: nullable 은 bool 이어야 합니다")
        return None
    if d["scope"] not in SCOPES or d["restart"] not in RESTARTS:
        problems.append(f"{key}: scope·restart 값 위반")
        return None
    if (d["scope"] == "agent") != is_agent_key(key):
        problems.append(f"{key}: scope=agent 는 계약 §5.1-8 에이전트 부분집합과 같아야 합니다")
        return None
    if d["secret"] and (not key.endswith("Sha256") or d["default"] != ""):
        problems.append(f"{key}: secret 키는 sha256 만 담고 기본값이 비어야 합니다")
        return None
    meta = KeyMeta(key=key, default=d["default"], type=t, range=rng, choices=tuple(ch) if ch is not None else None,
                   owner=d["owner"], readers=tuple(d["readers"]), spec=d["spec"], uncalibrated=d["uncalibrated"],
                   secret=d["secret"], scope=d["scope"], restart=d["restart"], label_ko=d["label_ko"],
                   help_ko=d["help_ko"], item=item, keys=tuple(keys) if keys is not None else None,
                   nullable=bool(d.get("nullable", False)), pattern=pat)
    if t == "bool" and meta.choices not in (None, (False, True)):
        problems.append(f"{key}: bool 의 choices 는 [false, true] 여야 합니다")
        return None
    if t == "list(+-)" and not isinstance(meta.default, list):
        problems.append(f"{key}: list(+-) 기본값은 목록이어야 합니다")
        return None
    if t == "obj" and keys is not None and (not isinstance(meta.default, dict) or sorted(meta.default) != sorted(keys)):
        problems.append(f"{key}: obj 기본값의 키가 keys 와 다릅니다")
        return None
    try:
        nv = _normalize(meta, meta.default)
    except _Bad as e:
        problems.append(f"{key}: 기본값이 자기 선언을 어깁니다({e.text_ko})")
        return None
    if _canon(_jsonable(nv)) != _canon(meta.default):
        problems.append(f"{key}: 기본값이 정규형이 아닙니다(float 키의 정수 기본값 등)")
        return None
    return meta


def parse_registry(raw: bytes) -> dict[str, KeyMeta]:
    """레지스트리 바이트 → {키: KeyMeta}. 규칙 위반이면 RegistryError(위반 목록)."""
    try:
        doc = _loads_strict(raw)
    except (UnicodeDecodeError, ValueError) as e:
        raise RegistryError(f"settings_registry.json 을 읽을 수 없습니다: {type(e).__name__}") from None
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA or not isinstance(doc.get("keys"), dict):
        raise RegistryError(f"settings_registry.json 의 schema 가 {SCHEMA} 가 아니거나 keys 가 없습니다")
    problems: list[str] = []
    out: dict[str, KeyMeta] = {}
    for key, d in doc["keys"].items():
        m = _meta_from(key, d, problems)
        if m is not None:
            out[key] = m
    if problems:
        raise RegistryError("설정 레지스트리 선언 위반 " + str(len(problems)) + "건: " + " | ".join(problems[:20]))
    return out


def load_registry(path=None) -> dict[str, KeyMeta]:
    """레지스트리 적재(경로·mtime·크기로 캐시). 없거나 깨지면 RegistryError — 기본값으로 돌지 않는다."""
    p = _registry_path(path)
    try:
        st = os.stat(p)
    except OSError:
        raise RegistryError(f"설정 레지스트리가 없습니다: {p.name}") from None
    ck = (str(p), st.st_mtime_ns, st.st_size)
    with _REG_LOCK:
        hit = _REG_CACHE.get(str(p))
        if hit is not None and hit[0] == ck:
            return hit[1]
    reg = parse_registry(_read_bytes(p))
    with _REG_LOCK:
        _REG_CACHE[str(p)] = (ck, reg)
    return reg


def registry_meta(key: str, *, path=None) -> KeyMeta:
    """키 하나의 선언. 미등록 키면 UnknownKeyError."""
    reg = load_registry(path)
    try:
        return reg[key]
    except KeyError:
        raise UnknownKeyError(key) from None


def is_agent_key(key: str) -> bool:
    """계약 §5.1-8 의 에이전트 부분집합(agent_config.json)에 드는 키인가."""
    return key in AGENT_SUBSET_KEYS or key.startswith(AGENT_SUBSET_PREFIXES)


def owner_file(owner: str) -> str:
    """owner 표기 → 저장소 상대 경로(``/`` 구분). 점 경로는 ``lm27/a/b.py`` 로 읽는다(L-12 단계 적용 기준)."""
    if "/" in owner:
        return owner
    return owner.replace(".", "/") + ".py"


def check_value(key: str, value, *, path=None) -> str | None:
    """화면 저장 전 검사: 통과면 None, 아니면 한국어 사유(값은 넣지 않는다). 미등록 키면 UnknownKeyError."""
    meta = registry_meta(key, path=path)
    try:
        _normalize(meta, value)
    except _Bad as e:
        return e.text_ko
    return None


# ───────────────────────── Cfg ─────────────────────────
def _warn(code: str, key: str, text_ko: str) -> dict:
    return {"code": code, "key": key, "text_ko": text_ko}


class Cfg:
    """실효 설정. ``cfg[key]`` 로 읽고(읽힌 키 기록), 미등록 키는 UnknownKeyError."""

    def __init__(self, registry: Mapping[str, KeyMeta], raw: Mapping | None = None,
                 warnings: Iterable[dict] = (), source: str | None = None):
        self._registry = registry
        self._raw: dict = {}
        self._values: dict = {}
        self._warnings: list[dict] = list(warnings)
        self._read: set[str] = set()
        self.source = source
        raw = dict(raw or {})
        for key, meta in registry.items():
            if key in raw:
                try:
                    v = _normalize(meta, raw[key])
                    self._raw[key] = raw[key]
                except _Bad as e:
                    self._warnings.append(_warn(e.code, key, f"{meta.label_ko}: {e.text_ko} — 기본값을 씁니다"))
                    v = meta.default
            else:
                v = meta.default
            self._values[key] = _frozen(v)

    # 읽기 ---------------------------------------------------------------
    def __getitem__(self, key: str):
        try:
            v = self._values[key]
        except KeyError:
            raise UnknownKeyError(key) from None
        self._read.add(key)
        return copy.deepcopy(v) if isinstance(v, dict) else v

    def __contains__(self, key) -> bool:
        return key in self._values

    def keys(self) -> list[str]:
        return list(self._values)

    def meta(self, key: str) -> KeyMeta:
        try:
            return self._registry[key]
        except KeyError:
            raise UnknownKeyError(key) from None

    # 기록·요약 ----------------------------------------------------------
    def used(self) -> dict:
        """지금까지 읽힌 키와 값(정렬, JSON 형) — 실행 결과의 cfg_used."""
        return {k: _jsonable(self._values[k]) for k in sorted(self._read)}

    def snapshot(self) -> dict:
        """모든 키의 실효 값(정렬, JSON 형). 읽힘으로 세지 않는다(화면 설정 표시용)."""
        return {k: _jsonable(self._values[k]) for k in sorted(self._values)}

    def overridden(self) -> list[str]:
        """config.json·덮어쓰기로 유효하게 바뀐 키(정렬)."""
        return sorted(self._raw)

    def hash(self, keys: Iterable[str] | None = None) -> str:
        """실효 값의 정규 해시(sha256 앞 16자). keys 를 주면 그 키만(미등록이면 UnknownKeyError).
        읽힘으로 세지 않는다."""
        sel = sorted(self._values) if keys is None else sorted(set(keys))
        body = {}
        for k in sel:
            if k not in self._values:
                raise UnknownKeyError(k)
            body[k] = _jsonable(self._values[k])
        return hashlib.sha256(_canon(body)).hexdigest()[:16]

    def agent_subset(self) -> dict:
        """에이전트로 내려갈 키·값(계약 §5.1-8, 정렬). 정제 설정 해시는 호출자(agent.install)가 덧붙인다."""
        return {k: _jsonable(self._values[k]) for k in sorted(self._values) if is_agent_key(k)}

    @property
    def config_warnings(self) -> list[dict]:
        """config.json 경고 목록 [{code, key, text_ko}] — 화면 다음 할 일 N16. 값은 담지 않는다."""
        return [dict(w) for w in self._warnings]

    def derive(self, overrides: Mapping) -> Cfg:
        """덮어쓰기를 더한 새 Cfg(보정·섭동 시험용). 미등록 키는 UnknownKeyError, 틀린 값은 기본값 + 경고.
        원래 Cfg 는 바뀌지 않고, 새 Cfg 의 읽힘 기록은 비어 있다."""
        for k in overrides:
            if k not in self._registry:
                raise UnknownKeyError(k)
        raw = dict(self._raw)
        raw.update(overrides)
        base = [w for w in self._warnings if w["key"] not in overrides]
        return Cfg(self._registry, raw, base, self.source)


# ───────────────────────── load_config ─────────────────────────
def _read_config_json(path: Path, registry: Mapping[str, KeyMeta]) -> tuple[dict, list[dict]]:
    try:
        raw = _read_bytes(path)
    except FileNotFoundError:
        return {}, []
    except OSError as e:
        return {}, [_warn("bad_file", "", f"개인 설정 파일을 열 수 없습니다({type(e).__name__}) — 모두 기본값을 씁니다")]
    try:
        doc = _loads_strict(raw)
    except (UnicodeDecodeError, ValueError) as e:
        return {}, [_warn("bad_file", "", f"개인 설정 파일이 깨졌습니다({type(e).__name__}) — 모두 기본값을 씁니다")]
    if not isinstance(doc, dict):
        return {}, [_warn("bad_file", "", "개인 설정 파일은 객체여야 합니다 — 모두 기본값을 씁니다")]
    vals, warns = {}, []
    for k, v in doc.items():
        if k == "schema" or k.startswith("_"):
            continue
        if k not in registry:
            warns.append(_warn("unknown_key", k if KEY_RX.match(k) else "",
                               "등록되지 않은 설정 키는 무시합니다" + ("" if KEY_RX.match(k) else "(표기 위반)")))
            continue
        vals[k] = v
    return vals, warns


def load_config(paths=None, *, config_path=None, registry_path=None, overrides: Mapping | None = None) -> Cfg:
    """설정 적재: 선언 기본값 ← ``config\\config.json``(개인 덮어쓰기) ← overrides(코드·시험용, 엄격).

    paths: ``lm27.paths.Paths``(``settings_registry()``·``config_json()``) · 루트 경로 · ``root`` 를 가진 객체 · None(이 트리).
    registry_path·config_path 는 시험·도구용 명시 경로(주면 paths 보다 앞선다).
    """
    p = _as_paths(paths) if registry_path is None or config_path is None else None
    reg_p = Path(registry_path) if registry_path is not None else Path(p.settings_registry())
    cfg_p = Path(config_path) if config_path is not None else Path(p.config_json())
    registry = load_registry(reg_p)
    raw, warns = _read_config_json(cfg_p, registry)
    if overrides:
        for k in overrides:
            if k not in registry:
                raise UnknownKeyError(k)
        raw.update(overrides)
    return Cfg(registry, raw, warns, source=str(cfg_p))


# ───────────────────────── 계약 §5.2 표 파서(생성 대조 — 시험·lint L-12 공용) ─────────────────────────
_TYPE_WORDS = frozenset({"int", "float", "bool", "str", "path", "list", "list(+-)", "obj"})
_STAR = "★"


def _split_outside(s: str, sep: str) -> list[str]:
    out, depth, cur, i = [], 0, [], 0
    while i < len(s):
        c = s[i]
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth = max(0, depth - 1)
        if depth == 0 and s.startswith(sep, i):
            out.append("".join(cur))
            cur = []
            i += len(sep)
            continue
        cur.append(c)
        i += 1
    out.append("".join(cur))
    return [x.strip() for x in out]


def _cells(line: str) -> list[str]:
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|"):
        body = body[:-1]
    # 칸 안의 \| 는 칸 구분이 아니다
    return [c.replace("\\|", "|").strip() for c in re.split(r"(?<!\\)\|", body)]


def parse_contract_default(piece: str):
    """§5.2 기본값 칸 조각 → (ok, 값). '내장'·'W 목록'·'H 값' 같은 서술은 (False, None)."""
    s = piece.replace(_STAR, "").strip()
    s = re.sub(r"\(.*\)$", "", s).strip()          # 0(끔) · ""(= data\import)
    if s.startswith("`") and s.count("`") >= 2:
        s = s[1:s.index("`", 1)]
    s = s.strip()
    if not s:
        return False, None
    try:
        return True, json.loads(s)
    except ValueError:
        pass
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", s) or _TIMERANGE_RX.match(s):
        return True, s
    return False, None


def contract_table_rows(md_text: str) -> list[dict]:
    """계약 §5.2 키 표 → 키별 행 [{key, star, default_text, default_ok, default, type_text, reader, spec}] (표 순서).

    키 칸의 ``.x`` 줄임은 앞의 온전한 키에서 마지막 마디를 바꾼 것으로 펼친다. ★ 는 키 칸(키 바로 뒤)이나
    그 키의 기본값 조각에 붙는다. 기본값·형 칸은 ' · ' 로 나눠 키와 맞추고, 조각이 하나면 모든 키에 쓴다."""
    s = md_text.index("### 5.2 ")
    e = md_text.index("### 5.3 ", s)
    out: list[dict] = []
    hdr = None
    for line in md_text[s:e].splitlines():
        if not line.lstrip().startswith("|"):
            hdr = None
            continue
        cells = _cells(line)
        if hdr is None:
            hdr = cells
            continue
        if all(set(c) <= set("-: ") for c in cells):
            continue
        row = dict(zip(hdr, cells, strict=False))
        keys, stars, prev = [], [], None
        for m in re.finditer(r"`([^`]+)`\s*(★)?", cells[0]):
            tok = m.group(1)
            if tok.startswith("."):
                if prev is None:
                    raise ValueError(f"§5.2 줄임 키 앞에 온전한 키가 없습니다: {tok}")
                k = prev.rsplit(".", 1)[0] + tok
            else:
                k = prev = tok
            keys.append(k)
            stars.append(bool(m.group(2)))
        if not keys:
            continue
        n = len(keys)
        dtext = row.get("기본값", "")
        dparts = _split_outside(dtext, " · ")
        if len(dparts) != n:
            dparts = dparts * n if len(dparts) == 1 else [None] * n
        ttext = row.get("형")
        tparts = [None] * n
        if ttext:
            tt = ttext.split(" — ")[0].strip()
            parts = _split_outside(tt, " · ")
            if len(parts) == n:
                tparts = parts
            elif len(parts) == 1:
                sub = _split_outside(tt, "·")
                if len(sub) == n and all(x in _TYPE_WORDS for x in sub):
                    tparts = sub
                else:
                    tparts = [tt] * n
        for i, k in enumerate(keys):
            dp = dparts[i]
            ok, val = parse_contract_default(dp) if dp is not None else (False, None)
            out.append({"key": k, "star": stars[i] or (dp is not None and _STAR in dp),
                        "default_text": dp, "default_ok": ok, "default": val, "type_text": tparts[i],
                        "reader": row.get("읽는 곳"), "spec": row.get("명세 §", "")})
    return out
