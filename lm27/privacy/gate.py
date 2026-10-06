# -*- coding: utf-8 -*-
r"""코파일럿 전송 직전 게이트 G3(P §13)와 팀 업로드 검사 G4(P §14) — 판정은 정제기와 같은 규칙(``sanitize``·``scan``).

G3 ``gate_copilot(items, stage, gctx)``: 허용 밖 필드 → ``GateSpecError``(단계 중단, 아무것도 보내지 않음) · 사적·사내 친목
행 → 제외(``class_private``) · 광고 의심 → 제외(``class_ad``) · 텍스트 필드 재정제 → 자격증명·고위험 잔여 PII(``rules.HIGH``)·
카나리아 → 제외(``pii:<범주>``) · 그 밖(금액·고객사·사람·IP·URL·경로 …)은 재가림 후 통과(``remask``). 사람 태그는 기본
``[사람]``(``privacy.copilot.personTokens = plain``), 외부 도메인 이메일 토큰은 ``[이메일@외부]``. 웹 근거가 켜진 계정
(``web_grounding`` — 브리지 탐침의 web_exposed, X-112)이면 사람 태그를 강제로 평문으로 줄이고 ``ip``·``url``·``path``
잔여도 제외한다. ``gate_prompt_text`` = 최종 프롬프트에 ``scan()`` 0건·카나리아 0건(L1 전송 직전 한 번 더).

G4 ``check_team_payload(payload, gctx, spec)``: ``spec`` 은 **필수**다(``lm27.team.schema.TEAM_SPEC_V1`` — 호출자가 늘 명시,
이 패키지는 ``lm27.team`` 을 import 하지 않는다 — X-304). 노드 형식은 ``lm27.team.schema`` docstring 이 정본:
값 클래스 문자열(끝 ``?`` = null 허용, ``|EMPTY`` = 빈 문자열 허용) · dict(키 고정) · ``[node]`` · ``{"$row": [...]}`` ·
``{"$map": node, "$key": CLASS}``. 모르는 키 → ``unknown_key``(그 값도 금지 값 검사), 클래스 불일치 → ``bad_<클래스>``,
라벨 → ``label:<코드>``, 모든 문자열 값·키 이름에 금지 값(P §14.3) → ``forbidden:<코드>``. 위반은 ``Violation(path, code)``
(경로·코드만 — 값 없음, 열린 사전의 키는 ``{n}`` 자리표로).

서버 모드(WP-27 요청): ``make_gate_context(None, cfg, None, stage="team_server", audit=None)`` — 정제 사전 없음, 카나리아 =
서버 PC 환경. 표준 라이브러리 + 이 패키지만 쓴다(에이전트 사본 포함).
"""
from __future__ import annotations

import hashlib
import ipaddress
import math
import re
from dataclasses import dataclass, field
from typing import NamedTuple

from .detect import SanitizeContext, safe_truncate, sanitize
from .rules import HIGH, RX
from .scan import scan

__all__ = [
    "FORBIDDEN_CODES", "LABEL_FORBID", "MEDIUM_WEB", "GateContext", "GateItem", "GateResult", "GateSpecError",
    "StageSpec", "Violation", "canary_hit", "check_team_label", "check_team_payload", "forbidden_codes",
    "gate_copilot", "gate_prompt_text", "gate_text",
]

MEDIUM_WEB = frozenset({"ip", "url", "path"})        # 웹 근거 켜짐: 이 범주가 남으면 제외(P §13.3 · X-112)
CANARY_MIN = 4                                       # 이보다 짧은 카나리아는 오탐 — 무시(P §13.2)
# 코파일럿에 보내지 않는 필드 이름(P §13.4 · B1 · L-18 과 같은 시간형 판정) — 단계 등록 때 GateSpecError
TIME_FIELD_RX = re.compile(
    r"(?i)^(?:ts|t0|t1|date|dates|day|days|month|months|week|weeks|time|times|hour|hours|minute|minutes|min|mins|"
    r"sec|secs|second|seconds|mm|duration|start|end|effort|lead|wd|when|at)(?:_|$)|"
    r"(?:^|_)(?:utc|ts|date|day|days|time|hours?|h|min|mins|minutes|sec|secs|seconds|mm|wd|at|start|end|"
    r"duration|effort)$")
IDENT_FIELDS = frozenset({"pc_id", "who_key", "kid", "sender_key", "author_key", "counterpart_keys", "path_key",
                          "install_id", "person_key", "peer_key"})


class GateSpecError(Exception):
    """단계 명세 위반(허용 밖 필드·금지 필드) — 프로그래밍 오류. 그 단계는 아무것도 보내지 않는다(fail-closed)."""


@dataclass
class GateItem:
    item_id: str                                     # msg_key·unit_id 등(HMAC 값 — 감사에 기록 가능)
    fields: dict
    meta: dict = field(default_factory=dict)         # {"priv_class": …, "ad_band": …, "rules_ver": …}


@dataclass(frozen=True)
class StageSpec:
    """코파일럿 브리지 단계마다 1개. ``name`` = 단계 id(X-113). 시간·MM·pc_id·who_key·kid 같은 필드가 허용 목록에
    있으면 등록 때 GateSpecError(P §13.4)."""
    name: str
    allowed_fields: frozenset
    text_fields: frozenset
    max_item_chars: int = 400

    def __post_init__(self):
        af = frozenset(self.allowed_fields)
        object.__setattr__(self, "allowed_fields", af)
        object.__setattr__(self, "text_fields", frozenset(self.text_fields))
        bad = sorted(f for f in af if f in IDENT_FIELDS or TIME_FIELD_RX.search(f))
        if bad:
            raise GateSpecError(f"{self.name}: 보내면 안 되는 필드 {bad}")
        if not self.text_fields <= af:
            raise GateSpecError(f"{self.name}: 텍스트 필드가 허용 필드 밖")
        if not isinstance(self.max_item_chars, int) or self.max_item_chars < 20:
            raise GateSpecError(f"{self.name}: max_item_chars")


@dataclass
class GateContext:
    """게이트 문맥(P §13.1). 카나리아는 메모리에서만(파일에 쓰지 않음). ``person_tokens`` = plain(기본)·keyed.
    ``web_grounding`` = 웹 근거 켜짐(브리지 탐침 web_exposed — X-112)."""
    sctx: SanitizeContext | None
    canaries: tuple = ()
    person_tokens: str = "plain"
    audit: object = None
    web_grounding: bool = False
    stage: str = ""

    def __post_init__(self):
        if self.sctx is None:
            self.sctx = SanitizeContext()
        self.canaries = tuple(c for c in (self.canaries or ()) if isinstance(c, str) and len(c.strip()) >= CANARY_MIN)
        self._can_low = tuple(dict.fromkeys(c.strip().lower() for c in self.canaries))


@dataclass
class GateResult:
    kept: list
    dropped: list                                    # [(item_id, 사유 코드)]
    counts: dict


# ───────────────────────────── 카나리아 ─────────────────────────────
_ASCII_CANARY = re.compile(r"^[a-z0-9._\-]+$")


def canary_hit(text: str, gctx: GateContext) -> bool:
    """카나리아 원값이 들어 있는가(대소문자 무시). ASCII 카나리아는 영숫자 경계로, 그 밖은 부분 문자열로."""
    low = (text or "").lower()
    if not low:
        return False
    for c in gctx._can_low:
        if _ASCII_CANARY.match(c):
            if re.search(r"(?<![a-z0-9])" + re.escape(c) + r"(?![a-z0-9])", low):
                return True
        elif c in low:
            return True
    return False


# ───────────────────────────── G3 코파일럿 ─────────────────────────────
_PERSON_TAG = re.compile(r"\[사람#[0-9a-f]{6}\]")
_EMAIL_TOKEN = re.compile(r"\[이메일@([^\]]+)\]")


def _email_label(m) -> str:
    lab = m.group(1)
    if lab in ("사내", "개인메일") or lab.startswith(("고객사:", "협력사:")):
        return m.group(0)
    return "[이메일@외부]"


def gate_text(text: str, gctx: GateContext):
    """텍스트 1개 → (재정제·축약 텍스트, 재가림 건수) 또는 (None, {사유: 건수})(항목 제외)."""
    r = sanitize(text, "copilot", gctx.sctx)
    if r.drop:
        return None, {"cred": 1}
    high = {k: v for k, v in r.hits.items() if k in HIGH}
    if high:
        return None, dict(sorted(high.items()))      # 고위험 잔여 PII → 제외(가려 보내지 않음 — 정제 실패 신호)
    if gctx.web_grounding:
        web = {k: v for k, v in r.hits.items() if k in MEDIUM_WEB}
        if web:
            return None, dict(sorted(web.items()))
    if canary_hit(r.text, gctx):
        return None, {"canary": 1}
    t = r.text
    if gctx.person_tokens != "keyed" or gctx.web_grounding:
        t = _PERSON_TAG.sub("[사람]", t)
    t = _EMAIL_TOKEN.sub(_email_label, t)
    return t, dict(r.hits)


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def gate_copilot(items, stage: StageSpec, gctx: GateContext) -> GateResult:
    """G3(P §13.2). 허용 밖 필드가 하나라도 있으면 GateSpecError(아무것도 보내지 않는다).
    ``counts`` 는 ``drop:<사유>``·``remask:<범주>``(결과 봉투는 접두를 뗀 이름으로 옮긴다 — X-113)."""
    items = list(items)
    for it in items:
        if set(it.fields) - stage.allowed_fields:
            raise GateSpecError(f"{stage.name}: 허용 밖 필드")
    kept, dropped, counts = [], [], {}
    remask: dict = {}
    for it in items:
        meta = it.meta or {}
        if meta.get("priv_class") in ("private", "social"):
            dropped.append((it.item_id, "class_private"))
            continue
        if meta.get("ad_band") == "suspect":
            dropped.append((it.item_id, "class_ad"))
            continue
        new_fields, bad = dict(it.fields), None
        for f in sorted(stage.text_fields & set(it.fields)):
            out, info = gate_text(str(it.fields[f]), gctx)
            if out is None:
                bad = next(iter(info))
                break
            for k, v in info.items():
                remask[k] = remask.get(k, 0) + v
            new_fields[f] = safe_truncate(out, stage.max_item_chars)
        if bad:
            dropped.append((it.item_id, "pii:" + bad))
            continue
        kept.append(GateItem(it.item_id, new_fields, it.meta))
    for k, v in sorted(remask.items()):
        counts["remask:" + k] = v
    for _iid, why in dropped:
        counts["drop:" + why] = counts.get("drop:" + why, 0) + 1
    au = gctx.audit
    if au is not None:
        for _iid, why in dropped:
            au.add("dropped", why)
        for k, v in remask.items():
            au.add("remask", k, v)
        au.flush("gate_copilot", rows_in=len(items), rows_out=len(kept))
    return GateResult(kept, dropped, counts)


def gate_prompt_text(prompt: str, gctx: GateContext):
    """최종 프롬프트 검사(P §13.3): ``scan(prompt)`` 이 빈 목록이고 카나리아 0건이어야 통과. → (통과, {범주: 건수}).
    실패면 그 배치는 보내지 않는다(``gate_blocked``)."""
    hits = {h.cat: h.n for h in scan(prompt or "", gctx.sctx)}
    if canary_hit(prompt or "", gctx):
        hits["canary"] = hits.get("canary", 0) + 1
    ok = not hits
    au = gctx.audit
    if au is not None:
        for k, v in hits.items():
            au.add("masked", k, v)
        if not ok:
            au.add("dropped", "gate_blocked")
        au.flush("gate_prompt", rows_in=1, rows_out=1 if ok else 0, out_sha256=_sha(prompt or ""))
    return ok, dict(sorted(hits.items()))


# ───────────────────────────── G4 팀 라벨·금지 값 ─────────────────────────────
LABEL_FORBID = re.compile(r"@|\\|\d{5,}|\[사람#|\[이메일@|\[URL\]|\[경로\]")


def check_team_label(s, gctx: GateContext, max_len: int = 40) -> list:
    """팀 라벨 검사(P §14.4) — 위반 코드 목록(빈 목록 = 통과): type · too_long · forbidden_pattern · not_clean · canary.
    이미 정제된 라벨만 허용(정제기가 바꿀 것이 남아 있으면 불합격)."""
    if not isinstance(s, str):
        return ["type"]
    v = []
    if len(s) > max_len:
        v.append("too_long")
    if LABEL_FORBID.search(s):
        v.append("forbidden_pattern")
    r = sanitize(s, "label", gctx.sctx)
    if r.drop or r.text != s or r.hits:
        v.append("not_clean")
    low = s.lower()
    if any(c in low for c in gctx._can_low):
        v.append("canary")
    return v


FORBIDDEN_CODES = ("forbidden:who_key", "forbidden:local_key", "forbidden:kid", "forbidden:pc_id", "forbidden:guid",
                   "forbidden:email", "forbidden:path", "forbidden:url", "forbidden:ip", "forbidden:digits",
                   "forbidden:canary")
_F_WHO = re.compile(r"(?<![0-9a-z_])w[0-9a-f]{16}(?![0-9a-f])")
_F_LOCAL = re.compile(r"(?<![0-9a-z_])[mehtdfrgs][0-9a-f]{16,24}(?![0-9a-f])")
_F_KID = re.compile(r"(?<![0-9a-z_])k[0-9a-f]{8}(?![0-9a-f])")
_F_PC = re.compile(r"pcx?_[0-9a-f]{16}")
_F_GUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_F_DIGITS = re.compile(r"\d{9,}")
_KEYISH = frozenset({"PERSON_KEY", "PEER_KEY", "UNIT_ID", "ROLE_ID", "VER"})      # local_key·digits 면제(P §14.3)
_NO_DIGITS = frozenset({"NUM", "SNUM", "DATE", "MONTH", "DATETIME_OFFSET", "UTC", "VER"})


def _ip_hit(s: str) -> bool:
    for m in RX["ipv4"].finditer(s):
        try:
            ipaddress.ip_address(m.group(0).split(":")[0])
            return True
        except ValueError:
            continue
    return False


def forbidden_codes(s, gctx: GateContext | None = None, *, cls: str = "") -> list:
    """문자열 하나의 금지 값 코드(P §14.3) — 정렬 목록(빈 목록 = 통과). 값은 돌려주지 않는다.
    ``cls`` = 값 클래스(PERSON_KEY·PEER_KEY·UNIT_ID·ROLE_ID·VER 면 local_key·digits 면제, NUM·DATE·UTC·VER 면 digits 면제)."""
    if not isinstance(s, str) or not s:
        return []
    base = cls.rstrip("?").split("|", 1)[0]
    out = set()
    if _F_WHO.search(s):
        out.add("forbidden:who_key")
    if base not in _KEYISH and _F_LOCAL.search(s):
        out.add("forbidden:local_key")
    if _F_KID.search(s):
        out.add("forbidden:kid")
    if _F_PC.search(s):
        out.add("forbidden:pc_id")
    if _F_GUID.search(s):
        out.add("forbidden:guid")
    if "@" in s or RX["email"].search(s):
        out.add("forbidden:email")
    if "\\" in s or RX["path"].search(s):
        out.add("forbidden:path")
    if RX["url"].search(s):
        out.add("forbidden:url")
    if _ip_hit(s):
        out.add("forbidden:ip")
    if base not in _KEYISH and base not in _NO_DIGITS and _F_DIGITS.search(s):
        out.add("forbidden:digits")
    if gctx is not None and canary_hit(s, gctx):
        out.add("forbidden:canary")
    return sorted(out)


class Violation(NamedTuple):
    """팀 페이로드 위반 하나 — 경로·코드만(값 없음). 튜플로도 풀린다(``path, code = v``)."""
    path: str
    code: str


_RX_CLASS = {
    "VER": re.compile(r"\d{4}\.\d{1,2}\.\d{1,3}|\d+\.\d+(?:\.\d+)?|[0-9a-f]{16}"),
    "DATETIME_OFFSET": re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:[+-]\d{2}:\d{2}|Z)"),
    "UTC": re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:[+-]\d{2}:\d{2}|Z)"),
    "DATE": re.compile(r"\d{4}-\d{2}-\d{2}"),
    "MONTH": re.compile(r"\d{4}-\d{2}"),
    "PERSON_KEY": re.compile(r"p_[0-9a-f]{12}"),
    "PEER_KEY": re.compile(r"c_[0-9a-f]{12}"),
    "UNIT_ID": re.compile(r"u_[0-9a-f]{10}"),
    "ROLE_ID": re.compile(r"r_[0-9a-f]{6}"),
    "PROJECT_ID": re.compile(r"P-\d{4}"),
    "PROPOSAL_ID": re.compile(r"pr_\d{1,4}"),
    "NEED_ID": re.compile(r"n_[0-9a-f]{6}"),
    "REG_ID": re.compile(r"[A-Za-z][A-Za-z0-9_\-]{0,23}"),
    "APP_ID": re.compile(r"[a-z0-9_.\-]{1,24}"),
    "HEX8": re.compile(r"[0-9a-f]{8}"),
}
_VOCAB_CODE = re.compile(r"[A-Z][A-Z0-9_]{1,15}")
_COUNT_CODE = re.compile(r"[a-z][a-z0-9_.:\-]{0,47}")
_LABEL_MAX = {"LABEL20": 20, "LABEL30": 30, "LABEL40": 40, "LABEL60": 60}
_SAFE_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,40}")
_RE_CACHE: dict = {}


def _num(v, signed: bool) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and (signed or v >= 0)


def _check_class(v, cls: str, path: str, gctx, out: list) -> None:
    """값 하나를 클래스로 검사해 위반을 out 에 더한다(금지 값 검사 포함)."""
    nullable = cls.endswith("?")
    c = cls[:-1] if nullable else cls
    empty_ok = c.endswith("|EMPTY")
    if empty_ok:
        c = c[: -len("|EMPTY")]
    if v is None:
        if not nullable:
            out.append(Violation(path, "bad_" + _cls_name(c)))
        return
    if empty_ok and v == "":
        return
    if c.startswith("CONST:"):
        if v != c[len("CONST:"):]:
            out.append(Violation(path, "bad_const"))
    elif c in ("NUM", "SNUM"):
        if not _num(v, c == "SNUM"):
            out.append(Violation(path, "bad_" + c.lower()))
        return
    elif c == "BOOL":
        if not isinstance(v, bool):
            out.append(Violation(path, "bad_bool"))
        return
    elif c == "COUNTS":
        if not isinstance(v, dict):
            out.append(Violation(path, "bad_counts"))
            return
        for i, (k, n) in enumerate(sorted(v.items(), key=lambda kv: str(kv[0]))):
            if not isinstance(k, str) or not _COUNT_CODE.fullmatch(k) or not _num(n, False):
                out.append(Violation(f"{path}{{{i}}}", "bad_counts"))
            _forbid(k, path + "{" + str(i) + "}", gctx, out, "")
        return
    elif c in _LABEL_MAX:
        if not isinstance(v, str):
            out.append(Violation(path, "bad_" + c.lower()))
            return
        for code in check_team_label(v, gctx, _LABEL_MAX[c]):
            out.append(Violation(path, "label:" + code))
    elif c.startswith("ENUM{") and c.endswith("}"):
        if not isinstance(v, str) or v not in c[5:-1].split(","):
            out.append(Violation(path, "bad_enum"))
    elif c.startswith("ENUM:"):
        if not isinstance(v, str) or not _VOCAB_CODE.fullmatch(v):
            out.append(Violation(path, "bad_enum"))
    elif c.startswith("RE:"):
        rx = _RE_CACHE.get(c)
        if rx is None:
            rx = _RE_CACHE[c] = re.compile(c[3:])
        if not isinstance(v, str) or not rx.fullmatch(v):
            out.append(Violation(path, "bad_re"))
    elif c in _RX_CLASS:
        if not isinstance(v, str) or not _RX_CLASS[c].fullmatch(v):
            out.append(Violation(path, "bad_" + c.lower()))
    else:
        out.append(Violation(path, "bad_spec"))
        return
    if isinstance(v, str):
        _forbid(v, path, gctx, out, c)


def _cls_name(c: str) -> str:
    if c.startswith(("ENUM", "CONST", "RE:")):
        return c.split("{", 1)[0].split(":", 1)[0].lower()
    return c.lower()


def _forbid(s: str, path: str, gctx, out: list, cls: str) -> None:
    for code in forbidden_codes(s, gctx, cls=cls):
        out.append(Violation(path, code))


def _scan_any(v, path: str, gctx, out: list) -> None:
    """모르는 키 아래 값 — 모든 문자열 값·키 이름에 금지 값 검사만."""
    if isinstance(v, str):
        _forbid(v, path, gctx, out, "")
    elif isinstance(v, dict):
        for i, (k, x) in enumerate(sorted(v.items(), key=lambda kv: str(kv[0]))):
            kp = _key_path(path, k, i)
            _forbid(str(k), kp, gctx, out, "")
            _scan_any(x, kp, gctx, out)
    elif isinstance(v, (list, tuple)):
        for i, x in enumerate(v):
            _scan_any(x, f"{path}[{i}]", gctx, out)


def _key_path(path: str, k, i: int) -> str:
    """경로 조각 — 안전한 이름 모양의 키만 싣고, 그 밖은 자리표 ``{i}``(값을 경로로 흘리지 않는다)."""
    if isinstance(k, str) and _SAFE_KEY.fullmatch(k) and not forbidden_codes(k):
        return f"{path}.{k}" if path else k
    return f"{path}{{{i}}}"


def _walk(v, node, path: str, gctx, out: list, depth: int) -> None:
    if depth > 40:
        out.append(Violation(path, "too_deep"))
        return
    if isinstance(node, str):
        _check_class(v, node, path, gctx, out)
    elif isinstance(node, list):
        if not isinstance(v, list):
            out.append(Violation(path, "bad_list"))
            _scan_any(v, path, gctx, out)
            return
        for i, x in enumerate(v):
            _walk(x, node[0], f"{path}[{i}]", gctx, out, depth + 1)
    elif isinstance(node, dict) and "$row" in node:
        cols = node["$row"]
        if not isinstance(v, list) or len(v) != len(cols):
            out.append(Violation(path, "bad_row"))
            _scan_any(v, path, gctx, out)
            return
        for i, (x, n) in enumerate(zip(v, cols, strict=True)):
            _walk(x, n, f"{path}[{i}]", gctx, out, depth + 1)
    elif isinstance(node, dict) and "$map" in node:
        if not isinstance(v, dict):
            out.append(Violation(path, "bad_map"))
            _scan_any(v, path, gctx, out)
            return
        for i, (k, x) in enumerate(sorted(v.items(), key=lambda kv: str(kv[0]))):
            kp = f"{path}{{{i}}}"
            _check_class(k, node.get("$key", "LABEL20"), kp, gctx, out)
            _walk(x, node["$map"], kp, gctx, out, depth + 1)
    elif isinstance(node, dict):
        if not isinstance(v, dict):
            out.append(Violation(path, "bad_object"))
            _scan_any(v, path, gctx, out)
            return
        for i, (k, x) in enumerate(sorted(v.items(), key=lambda kv: str(kv[0]))):
            if k in node:
                _walk(x, node[k], f"{path}.{k}" if path else k, gctx, out, depth + 1)
            else:
                kp = _key_path(path, k, i)
                out.append(Violation(kp, "unknown_key"))
                _forbid(str(k), kp, gctx, out, "")
                _scan_any(x, kp, gctx, out)
    else:
        out.append(Violation(path, "bad_spec"))


def check_team_payload(payload, gctx: GateContext, spec) -> list:
    """팀 페이로드 검사(G4 · P §14.5) — ``spec`` 필수(``TEAM_SPEC_V1`` — 호출자가 명시, X-304). 위반 목록
    ``[Violation(path, code)]``(경로·코드만, 정렬·중복 제거). 하나라도 있으면 업로드하지 않는다(fail-closed)."""
    if not isinstance(spec, dict):
        raise TypeError("check_team_payload: spec(TEAM_SPEC_V1 — '최상위 필드명 → 규칙' 사전)이 필요합니다")
    if gctx is None:
        gctx = GateContext(sctx=None)
    out: list = []
    _walk(payload, spec, "", gctx, out, 0)
    res = sorted(set(out))
    au = gctx.audit
    if au is not None and res:
        # 위반이면 여기서 1줄(P §15.4 ``gate_team.violations`` + 코드별 건수 — 경로·값 없음). 통과면 기록하지 않는다 —
        # 호출자(팀 빌더 ``audit_gate_team``)가 전송 바이트 sha 와 함께 ``flush("gate_team", out_sha256=…)`` 한다(중복 방지).
        au.add("gate_team", "violations", len(res))
        for v in res:
            au.add("gate_team", v.code.replace(":", "_"))
        au.flush("gate_team", rows_in=1, rows_out=0)
    return res
