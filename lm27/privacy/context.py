# -*- coding: utf-8 -*-
r"""정제·레코드·게이트 문맥(P §3.2 · §8 · §9.6 · §13.1 · §17.3 · 계약 §2.2 · §3.9 · X-247 · X-303 · X-304 · X-306).

  · ``build_context(cfg, registry, local, kr)`` → ``SanitizeContext``: 사전 가명화 출처 = 유효 레지스트리(내장 ⊕ 팀 ⊕ 개인
    로컬)의 ``codenames``·``aliases``(mask_name)·``customers``·``partners`` + ``privacy.customers``·``privacy.partners``
    (X-247) · 사람 사전 = ``data\local_only\person_dir.json`` · 본인 = ``self_name_set`` · 설정 검증(P §8.3 · §17.3 — 실패
    항목은 건너뛰고 감사 ``cfg.<코드>`` 만, 값은 남기지 않는다).
  · ``self_name_set(local, cfg, os_names)`` — 본인 표시명 집합 단일원(CT §4.4 · X-306): person_dir 의 ``self:true`` 이름 + OS
    표시명(``%USERNAME%``·LogonUI 표시명, 둘 다 없을 때만 디렉터리 표시명) + ``collect.ownerAddress`` 로컬부 + 고정어
    ``나``·``본인``·``you``·``me``, 변형 = 소문자·공백 제거·``님``/``씨`` 접미 제거. 수집기 ``_in.self_names``·
    ``context_cache.self_names`` 는 이 결과 전체를 쓴다. 정제문 치환(``SanitizeContext.self_names`` → ``[나]``)에는 고정어와
    1자 이름을 뺀 부분집합을 쓴다(``나중에``·``me`` 같은 일반 낱말이 깨지지 않게 — P §9.6 '1~2자 오탐' 원칙).
  · ``make_record_context(root, src, pc_id, *, agent_dir=None, stage="collect", my_addrs=())``:
      - 프로그램 폴더 모드(root 있음): 설정(``lm27.config``)·유효 레지스트리(``lm27.hier.registry.load_effective`` —
        **함수 안 지연 import**, ``persist=False``, 네트워크 없음 — X-304)·로컬 사전·키링(``create=True``)으로 만든다.
      - 에이전트 모드(root=None): ``agent\context_cache.json`` 과 하위 키(``subkeys.json``)만 쓴다(설정·레지스트리 import 0 —
        bin 사본에는 ``lm27.config``·``lm27.hier`` 가 없다, 계약 §1.3). 하위 키가 없거나 손상이면 키 없음 모드.
    두 모드가 같은 함수(``contexts_from_cache``)로 문맥을 만든다 — 같은 설정이면 에이전트와 프로그램 폴더의 정제가 같다.
  · ``write_context_cache(agent_dir, sctx_cfg)`` — 정제 문맥 직렬화(``lm27.ctxcache/1``, 계약 §3.9: 사전 이름 목록·허용 패턴·
    문맥어·``self_names``·창 분류 문맥·사적 폴더 낱말·근무창·``episode.finalWords``, 키·주소 없음) 원자 기록, 해시 반환
    (= 에이전트 config_hash). ``sctx_cfg`` = ``context_cache_obj(paths, cfg, kr=…)`` 의 결과.
  · ``make_gate_context(sctx, cfg, kr, *, stage, audit, web_grounding=False)`` — 카나리아(PC 이름·계정명·도메인·프로필 폴더·
    본인 주소와 로컬부·MachineGuid 두 형태·키 base64 앞 16자)는 메모리에서만 만든다(P §13.1). 서버 모드(WP-27 요청):
    ``make_gate_context(None, cfg, None, stage="team_server", audit=None)`` — 정제 사전 없음, 카나리아 = 서버 PC 환경.

이 패키지 최상위는 ``lm27.hier``·``lm27.team``·``lm27.config`` 를 import 하지 않는다(X-304 · 에이전트 사본).
"""
from __future__ import annotations

import base64
import hashlib
import os
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from lm27.paths import Paths
from lm27.util import fsx

from . import keys as K
from .audit import AuditSink
from .classify import PRIVATE_EXES, W_WORK, WindowContext
from .detect import SanitizeContext, sanitize
from .gate import GateContext
from .records import SRCS_BY_KIND, RecordContext, WorkWindow, dict_name
from .rules import NAME_STOP, PERSONAL_MAIL_DOMAINS

__all__ = [
    "CTXCACHE_SCHEMA", "PERSONDIR_FORMAT", "SELF_FIXED", "LocalOnly", "build_context", "context_cache_obj",
    "contexts_from_cache", "make_gate_context", "make_record_context", "merge_person_dir", "os_display_names",
    "read_context_cache", "refresh_context_cache", "self_name_set", "text_self_names", "validate_allow_patterns",
    "write_context_cache",
]

CTXCACHE_SCHEMA = "lm27.ctxcache/1"
PERSONDIR_FORMAT = "lm27-persondir/1"
SELF_FIXED = ("나", "본인", "you", "me")
CORRESP_DAYS = 365
REGEX_MAX = 200
EXTRA_CTX_KEYS = (("account_strong", "privacy.extraCtx.account"), ("passport", "privacy.extraCtx.passport"),
                  ("license", "privacy.extraCtx.license"), ("money", "privacy.extraCtx.money"),
                  ("ip", "privacy.extraCtx.ip"), ("card", "privacy.extraCtx.card"))
TOKEN_ID_RX = re.compile(r"^[A-Za-z][A-Za-z0-9_\-]{0,15}$")          # 정제 토큰 안 ID(계약 §4.5 · X-050)
_WKEY_RX = re.compile(r"^w[0-9a-f]{16}$")
_HKEY_RX = re.compile(r"^h[0-9a-f]{16}$")
_DOMAIN_RX = re.compile(r"^[a-z0-9](?:[a-z0-9\-]{0,62}\.)+[a-z]{2,24}$")
_HANGUL = re.compile(r"[가-힣]")
_DAY_RX = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIMERANGE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)-([01]\d|2[0-3]):([0-5]\d)$")
ALL_SRCS = frozenset(s for v in SRCS_BY_KIND.values() for s in v)


def _cfgv(cfg, key: str, default=None):
    """설정 값 — ``Cfg``(미등록 키는 UnknownKeyError) 또는 dict(시험·서버)·None(기본값)."""
    if cfg is None:
        return default
    if isinstance(cfg, dict):
        return cfg.get(key, default)
    return cfg[key]


def _audit(audit, code: str, n: int = 1) -> None:
    if audit is not None and n:
        audit.add("cfg", code, n)


def _nfkc(s) -> str:
    return unicodedata.normalize("NFKC", str(s or "")).strip()


# ───────────────────────────── 로컬 전용 사전 ─────────────────────────────
@dataclass
class LocalOnly:
    r"""``data\local_only\`` 의 정제 관련 파일(P §3.1 표) — 폴더와 동행하지만 반출 금지."""
    person_dir: dict = field(default_factory=dict)
    corresp_domains: dict = field(default_factory=dict)
    ad_lists: dict = field(default_factory=dict)
    private_chats: tuple = ()

    @classmethod
    def load(cls, paths: Paths) -> LocalOnly:
        pd = fsx.read_json(paths.local_only_file("person_dir.json"), default={}) or {}
        cd = fsx.read_json(paths.local_only_file("corresp_domains.json"), default={}) or {}
        al = fsx.read_json(paths.local_only_file("ad_lists.json"), default={}) or {}
        pc = fsx.read_json(paths.local_only_file("private_chats.json"), default=None, want=None)
        if isinstance(pc, dict):
            pc = pc.get("chats") or pc.get("chat_keys") or []
        chats = tuple(sorted({c for c in (pc or []) if isinstance(c, str) and _HKEY_RX.match(c)}))
        return cls(person_dir=pd if isinstance(pd, dict) else {}, corresp_domains=cd if isinstance(cd, dict) else {},
                   ad_lists=al if isinstance(al, dict) else {}, private_chats=chats)


def _people(local) -> dict:
    if local is None:
        return {}
    pd = local.person_dir if isinstance(local, LocalOnly) else (local.get("person_dir") if isinstance(local, dict)
                                                               else None)
    ppl = (pd or {}).get("people") if isinstance(pd, dict) else None
    return ppl if isinstance(ppl, dict) else {}


# ───────────────────────────── 본인 이름(CT §4.4 · X-306) ─────────────────────────────
def _logonui_display_name() -> str:
    if os.name != "nt":
        return ""
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Authentication\LogonUI") as k:
            v, _t = winreg.QueryValueEx(k, "LastLoggedOnDisplayName")
    except OSError:
        return ""
    return str(v or "").strip()


def _directory_display_name() -> str:
    if os.name != "nt":
        return ""
    import ctypes
    from ctypes import wintypes
    try:
        fn = ctypes.windll.secur32.GetUserNameExW
    except (AttributeError, OSError):
        return ""
    size = wintypes.ULONG(256)
    buf = ctypes.create_unicode_buffer(256)
    if not fn(3, buf, ctypes.byref(size)):           # NameDisplay
        return ""
    return buf.value.strip()


def os_display_names(*, have_settings: bool = False) -> list:
    """OS 표시명(CT §4.4): ``%USERNAME%`` · LogonUI 표시명(레지스트리 읽기 — 오프라인 즉시). 디렉터리(AD) 표시명은
    설정 이름(``have_settings``)과 LogonUI 표시명이 **모두 없을 때만**(마지막 수단 — 도메인 조회가 걸릴 수 있다)."""
    out = []
    u = (os.environ.get("USERNAME") or "").strip()
    if u:
        out.append(u)
    d = _logonui_display_name()
    if d:
        out.append(d)
    if not have_settings and not d:
        d2 = _directory_display_name()
        if d2:
            out.append(d2)
    return out


def self_name_set(local, cfg, os_names=None, *, replay: bool = False) -> list:
    """본인 표시명 집합(정렬 목록 — X-306 단일원, CT §4.4). 원천: 설정(person_dir 의 ``self:true`` 이름 ·
    ``collect.ownerAddress`` 로컬파트) + OS 표시명(``os_names`` 주입, 없으면 ``os_display_names()``) + 고정값
    나·본인·you·me. 변형: NFKC · 소문자 · 공백 제거 · 님/씨 접미 제거를 모두 넣는다. ``replay=True``(원문이 타 PC)는
    설정값만. 원문 이름이므로 메모리·로컬 전용 파일(``context_cache.json``)·수집기 stdin(``_in.self_names``)에만 둔다."""
    settings = []
    for _wk, p in sorted(_people(local).items()):
        if isinstance(p, dict) and p.get("self"):
            settings += [n for n in (p.get("names") or []) if isinstance(n, str)]
    owner = str(_cfgv(cfg, "collect.ownerAddress", "") or "").strip()
    if "@" in owner:
        settings.append(owner.split("@", 1)[0])
    raw = list(settings)
    if not replay:
        raw += list(os_names) if os_names is not None else os_display_names(have_settings=bool(settings))
    raw += SELF_FIXED
    out = set()
    for n in raw:
        n = _nfkc(n)
        if not n or len(n) > 60:
            continue
        nospace = re.sub(r"\s+", "", n)
        forms = {n, n.lower(), nospace, nospace.lower()}
        forms |= {re.sub(r"(?:님|씨)$", "", f).strip() for f in list(forms)}
        out |= {f for f in forms if f}
    return sorted(out)


def text_self_names(names) -> list:
    """정제문 ``[나]`` 치환용 부분집합: 고정어(나·본인·you·me)와 1자 이름은 뺀다."""
    fixed = {x.lower() for x in SELF_FIXED}
    return sorted({n for n in (names or ()) if isinstance(n, str) and len(n) >= 2 and n.lower() not in fixed})


# ───────────────────────────── 설정 검증(P §8.3 · §17.3) ─────────────────────────────
def _compile_ok(p):
    if not isinstance(p, str) or not p or len(p) > REGEX_MAX:
        return None
    try:
        rx = re.compile(p)
    except re.error:
        return None
    if rx.fullmatch("") is not None:
        return None
    return rx


_CORPUS_POS: list = []


def _corpus_pos() -> list:
    """회귀 말뭉치 양성 입력(P §18.2) — (문맥 dict, 문장, 기준 정제 결과). 허용 패턴이 너무 넓은지 재는 데 쓴다."""
    if not _CORPUS_POS:
        from .selftest import load_corpus                # 지연 import(selftest → events 적재 비용)
        for r in load_corpus():
            if r.get("type") == "pos" and isinstance(r.get("text"), str):
                d = dict(r.get("ctx") or {})
                base = sanitize(r["text"], ctx=SanitizeContext(**d))
                _CORPUS_POS.append((d, r["text"], base))
    return _CORPUS_POS


def _too_broad(p: str) -> bool:
    """허용 패턴이 말뭉치 양성 PII 의 가림을 하나라도 막으면 너무 넓다(P §17.3 ``cfg.allow_too_broad``, P-T3)."""
    for d, text, base in _corpus_pos():
        ctx = SanitizeContext(**{**d, "allow_patterns": [*(d.get("allow_patterns") or []), p]})
        r = sanitize(text, ctx=ctx)
        if r.text != base.text or r.hits != base.hits:
            return True
    return False


def validate_allow_patterns(pats, audit=None) -> list:
    """``privacy.allowPatterns`` 검증 — 컴파일·길이 ≤200·빈 문자열 불일치(``cfg.bad_regex``), 말뭉치 PII 를 풀어 주면
    거부(``cfg.allow_too_broad``). 통과한 패턴 문자열 목록(순서 유지)."""
    out = []
    for p in pats or ():
        if _compile_ok(p) is None:
            _audit(audit, "bad_regex")
            continue
        if _too_broad(p):
            _audit(audit, "allow_too_broad")
            continue
        out.append(p)
    return out


def _regexes(pats, audit=None) -> list:
    out = []
    for p in pats or ():
        if _compile_ok(p) is None:
            _audit(audit, "bad_regex")
            continue
        out.append(p)
    return out


def _domains(items) -> list:
    out = []
    for d in items or ():
        x = _nfkc(d).lower().lstrip("@").strip(".")
        if x and _DOMAIN_RX.match(x) and x not in out:
            out.append(x)
    return out


def _alias_ok(n, audit):
    n = _nfkc(n)
    if not n:
        return None
    if len(n) < (2 if _HANGUL.search(n) else 3):
        _audit(audit, "short_alias")
        return None
    if n in NAME_STOP or W_WORK.fullmatch(n):
        _audit(audit, "generic_alias")
        return None
    return n


def _parties(items, seen: dict, audit, field_: str = "names") -> list:
    """사전 항목(P §8.3) — id 형식·별칭 길이·일반어·중복(먼저 정의된 쪽) 검증. id 별로 합친다."""
    out, by_id = [], {}
    for it in items or ():
        if not isinstance(it, dict):
            continue
        pid = it.get("id")
        if not isinstance(pid, str) or not TOKEN_ID_RX.match(pid):
            _audit(audit, "bad_id")
            continue
        e = by_id.get(pid)
        if e is None:
            e = {"id": pid, field_: []}
            if field_ == "names":
                e["domains"] = []
            by_id[pid] = e
            out.append(e)
        for n in it.get(field_) or ():
            n2 = _alias_ok(n, audit)
            if not n2:
                continue
            low = n2.lower()
            if low in seen:
                if seen[low] != pid:
                    _audit(audit, "dup_alias")
                continue
            seen[low] = pid
            e[field_].append(n2)
        if field_ == "names":
            for d in _domains(it.get("domains")):
                if d not in e["domains"]:
                    e["domains"].append(d)
    return out


def _persons(local, selfs) -> dict:
    """사람 사전 → 표시명 → who_key 16hex(P §9.6). 본인·성만 있는 이름(김·이 책임·남궁)·일반어는 넣지 않는다."""
    self_low = {s.lower() for s in selfs}
    pairs = []
    for wk, p in sorted(_people(local).items()):
        if not isinstance(wk, str) or not _WKEY_RX.match(wk) or not isinstance(p, dict) or p.get("self"):
            continue
        for n in p.get("names") or ():
            n2 = dict_name(n, self_low)                  # 규칙 단일원(records.dict_name — 레코드 당사자 가림과 같음)
            if n2 is None:
                continue
            pairs.append((n2, wk[1:]))
    out: dict = {}
    for n, k in sorted(pairs):
        out.setdefault(n, k)
    return out


def _reg_dict(registry) -> dict:
    if registry is None:
        return {}
    if hasattr(registry, "privacy_dict"):
        return registry.privacy_dict()
    return registry if isinstance(registry, dict) else {}


def _key_material(kr) -> tuple[bytes, bytes | None]:
    if isinstance(kr, K.Keyring):
        return kr.primary_secret, None
    if isinstance(kr, K.AgentKeys):
        return b"\x00" * 32, kr.subkeys.get("person")
    return b"\x00" * 32, None


def build_context(cfg, registry, local, kr, *, os_names=None, audit=None) -> SanitizeContext:
    """설정·유효 레지스트리(``privacy_dict()`` 형 또는 EffectiveRegistry)·로컬 사전·키 → ``SanitizeContext``(P §3.2)."""
    reg = _reg_dict(registry)
    seen: dict = {}
    customers = _parties([*(reg.get("customers") or ()), *(_cfgv(cfg, "privacy.customers", ()) or ())], seen, audit)
    partners = _parties([*(reg.get("partners") or ()), *(_cfgv(cfg, "privacy.partners", ()) or ())], seen, audit)
    projects = [p for p in _parties(reg.get("projects") or (), seen, audit, "codenames") if p["codenames"]]
    selfs = self_name_set(local, cfg, os_names)
    extra = {}
    for ck, key in EXTRA_CTX_KEYS:
        vals = [_nfkc(x) for x in (_cfgv(cfg, key, ()) or ()) if _nfkc(x)]
        if vals:
            extra[ck] = vals
    key, psk = _key_material(kr)
    return SanitizeContext(
        internal_domains=_domains([*(reg.get("internal_domains") or ()), *(_cfgv(cfg, "privacy.internalDomains", ()) or ())]),
        personal_mail_domains=_domains(_cfgv(cfg, "privacy.personalMailDomains", PERSONAL_MAIL_DOMAINS)),
        customers=[c for c in customers if c["names"] or c["domains"]],
        partners=[p for p in partners if p["names"] or p["domains"]],
        projects=projects, persons=_persons(local, selfs), self_names=text_self_names(selfs),
        allow_patterns=validate_allow_patterns(_cfgv(cfg, "privacy.allowPatterns", ()), audit), extra_ctx=extra,
        mask_company_suffix=bool(_cfgv(cfg, "privacy.maskCompanySuffix", True)),
        mask_rates=bool(_cfgv(cfg, "privacy.money.maskRates", True)), key=key, person_subkey=psk,
        extra_stopwords=[_nfkc(x) for x in (_cfgv(cfg, "privacy.names.extraStopwords", ()) or ()) if _nfkc(x)])


# ───────────────────────────── 정제 문맥 사본(계약 §3.9) ─────────────────────────────
def _calendar_dates(cal) -> tuple[list, list]:
    """달력 객체(W §2.5 형) → (휴일 날짜, 평일 번호). 형식이 틀리면 빈 휴일·월~금."""
    days, wk = set(), [0, 1, 2, 3, 4]
    if isinstance(cal, dict):
        for y in cal.get("years") or ():
            for h in (y.get("holidays") or ()) if isinstance(y, dict) else ():
                d = h.get("date") if isinstance(h, dict) else None
                if isinstance(d, str) and _DAY_RX.match(d):
                    days.add(d)
        for d in cal.get("company_off") or ():
            if isinstance(d, str) and _DAY_RX.match(d):
                days.add(d)
        w = cal.get("weekdays")
        if isinstance(w, list) and w and all(isinstance(x, int) and 0 <= x <= 6 for x in w):
            wk = sorted(set(w))
    return sorted(days), wk


def _load_registry(paths: Paths, cfg, kr):
    """유효 레지스트리(X-247) — 프로그램 폴더 모드에서만, 함수 안 지연 import(X-304). 네트워크 없음·자동 대응 기록 없음."""
    from lm27.hier.registry import load_effective
    reg, _st = load_effective(paths, cfg, kr=kr, persist=False)
    cal = getattr(reg, "calendar", None)
    return reg.privacy_dict(), (cal if isinstance(cal, dict) and cal.get("years") else None)


def context_cache_obj(paths: Paths, cfg, *, kr=None, registry=None, calendar=None, local=None, os_names=None,
                      audit=None) -> dict:
    """정제 문맥 직렬화 객체(``lm27.ctxcache/1`` — 계약 §3.9). 키·주소 없음(사전 이름·도메인·패턴·문맥어·본인 이름·창 분류
    문맥·사적 폴더 낱말·근무창·최종 이름 낱말). 에이전트 ``context_cache.json`` 과 프로그램 폴더 정제가 같은 객체를 쓴다."""
    cal_reg = None
    if registry is None:
        registry, cal_reg = _load_registry(paths, cfg, kr)
    local = local if local is not None else LocalOnly.load(paths)
    sctx = build_context(cfg, registry, local, kr, os_names=os_names, audit=audit)
    cal = calendar if calendar is not None else (cal_reg or fsx.read_json(paths.calendar_json(), default={}))
    holidays, weekdays = _calendar_dates(cal)
    std = str(_cfgv(cfg, "time.window.std", "09:00-18:00") or "09:00-18:00")
    return {
        "schema": CTXCACHE_SCHEMA,
        "sanitize": {
            "internal_domains": list(sctx.internal_domains), "personal_mail_domains": list(sctx.personal_mail_domains),
            "customers": sorted(sctx.customers, key=lambda c: c["id"]),
            "partners": sorted(sctx.partners, key=lambda c: c["id"]),
            "projects": sorted(sctx.projects, key=lambda c: c["id"]), "persons": dict(sorted(sctx.persons.items())),
            "self_names": list(sctx.self_names), "allow_patterns": list(sctx.allow_patterns),
            "extra_ctx": dict(sorted(sctx.extra_ctx.items())), "mask_company_suffix": sctx.mask_company_suffix,
            "mask_rates": sctx.mask_rates, "extra_stopwords": list(sctx.extra_stopwords)},
        "self_names": self_name_set(local, cfg, os_names),
        "window": {
            "private_exes": sorted({str(x).lower() for x in (_cfgv(cfg, "privacy.window.privateExes", PRIVATE_EXES)
                                                             or ())}),
            "private_profiles": [_nfkc(x) for x in (_cfgv(cfg, "privacy.window.privateProfiles", ("개인", "Personal"))
                                                    or ()) if _nfkc(x)],
            "work_title_patterns": _regexes(_cfgv(cfg, "privacy.window.workTitlePatterns", ()), audit)},
        "path_exclude": [_nfkc(x) for x in (_cfgv(cfg, "privacy.path.excludeKeywords", ()) or ()) if _nfkc(x)],
        "private_categories": [_nfkc(x) for x in (_cfgv(cfg, "privacy.private.categories", ()) or ()) if _nfkc(x)],
        "private_extra_words": [_nfkc(x) for x in (_cfgv(cfg, "privacy.private.extraWords", ()) or ()) if _nfkc(x)],
        "private_extra_work_words": [_nfkc(x) for x in (_cfgv(cfg, "privacy.private.extraWorkWords", ()) or ())
                                     if _nfkc(x)],
        "ad_extra_words": [_nfkc(x) for x in (_cfgv(cfg, "privacy.ad.extraWords", ()) or ()) if _nfkc(x)],
        "final_words": [_nfkc(x) for x in (_cfgv(cfg, "episode.finalWords", ()) or ()) if _nfkc(x)],
        "private_chats": list(local.private_chats),
        "work_window": {"std": std if _TIMERANGE.match(std) else "09:00-18:00", "weekdays": weekdays,
                        "holidays": holidays, "tz_offset_min": int(_cfgv(cfg, "time.tzOffsetMin", 540))},
    }


def cache_hash(obj: dict) -> str:
    """정제 설정 해시(P §16.3 ``config_hash``) — 직렬화 객체(``hash`` 빼고)의 정규 바이트 sha256 앞 16자."""
    body = {k: v for k, v in obj.items() if k != "hash"}
    return hashlib.sha256(fsx.canon_bytes(body)).hexdigest()[:16]


def _agent_paths(agent_dir) -> Paths:
    return Paths(lad=Path(os.fspath(agent_dir)).parent)


def write_context_cache(agent_dir, sctx_cfg: dict) -> str:
    r"""``agent\context_cache.json``(``lm27.ctxcache/1``) 원자 기록 → 해시(= 에이전트 config_hash). 키·주소를 싣지 않는다
    — ``sanitize.key``·``person_subkey`` 같은 키 필드가 있으면 ValueError."""
    if not isinstance(sctx_cfg, dict):
        raise TypeError("write_context_cache: context_cache_obj() 결과(dict)가 필요합니다")
    s = sctx_cfg.get("sanitize") or {}
    if "key" in s or "person_subkey" in s:
        raise ValueError("write_context_cache: 키는 문맥 사본에 싣지 않는다")
    obj = dict(sctx_cfg)
    obj["schema"] = CTXCACHE_SCHEMA
    obj.pop("hash", None)
    h = cache_hash(obj)
    obj["hash"] = h
    fsx.atomic_write(_agent_paths(agent_dir).context_cache(), fsx.canon_bytes(obj) + b"\n")
    return h


def read_context_cache(agent_dir) -> dict | None:
    """``context_cache.json`` → dict(형식이 다르거나 해시가 맞지 않으면 None)."""
    obj = fsx.read_json(_agent_paths(agent_dir).context_cache(), default=None)
    if not isinstance(obj, dict) or obj.get("schema") != CTXCACHE_SCHEMA or obj.get("hash") != cache_hash(obj):
        return None
    return obj


def refresh_context_cache(paths: Paths, cfg, *, kr=None, audit=None, os_names=None) -> str:
    """프로그램 폴더 [수집]·설치가 에이전트 문맥 사본을 새로 쓴다(유효 레지스트리·로컬 사전·설정) → 해시."""
    return write_context_cache(paths.agent_dir(), context_cache_obj(paths, cfg, kr=kr, audit=audit, os_names=os_names))


def _work_window(w: dict) -> tuple[WorkWindow, int]:
    m = _TIMERANGE.match(str(w.get("std") or ""))
    s, e = (int(m.group(1)) * 60 + int(m.group(2)), int(m.group(3)) * 60 + int(m.group(4))) if m else (540, 1080)
    wk = w.get("weekdays")
    wk = frozenset(x for x in wk if isinstance(x, int) and 0 <= x <= 6) if isinstance(wk, list) and wk else None
    hol = frozenset(d for d in (w.get("holidays") or ()) if isinstance(d, str) and _DAY_RX.match(d))
    off = w.get("tz_offset_min", 540)
    off = off if isinstance(off, int) and not isinstance(off, bool) and abs(off) <= 840 else 540
    return WorkWindow(start_min=s, end_min=e, weekdays=wk or frozenset({0, 1, 2, 3, 4}), holidays=hol), off


def contexts_from_cache(obj: dict, kr):
    """직렬화 객체 + 키 → (SanitizeContext, WindowContext, WorkWindow, 근무 시간대 오프셋(분))."""
    s = obj.get("sanitize") if isinstance(obj.get("sanitize"), dict) else {}
    key, psk = _key_material(kr)
    sctx = SanitizeContext(
        internal_domains=list(s.get("internal_domains") or []),
        personal_mail_domains=list(s.get("personal_mail_domains") or PERSONAL_MAIL_DOMAINS),
        customers=[dict(c) for c in s.get("customers") or [] if isinstance(c, dict)],
        partners=[dict(c) for c in s.get("partners") or [] if isinstance(c, dict)],
        projects=[dict(c) for c in s.get("projects") or [] if isinstance(c, dict)],
        persons={k: v for k, v in (s.get("persons") or {}).items() if isinstance(k, str) and isinstance(v, str)},
        self_names=[n for n in s.get("self_names") or [] if isinstance(n, str)],
        allow_patterns=[p for p in s.get("allow_patterns") or [] if _compile_ok(p) is not None],
        extra_ctx={k: list(v) for k, v in (s.get("extra_ctx") or {}).items() if isinstance(v, list)},
        mask_company_suffix=bool(s.get("mask_company_suffix", True)), mask_rates=bool(s.get("mask_rates", True)),
        key=key, person_subkey=psk, extra_stopwords=[x for x in s.get("extra_stopwords") or [] if isinstance(x, str)])
    w = obj.get("window") if isinstance(obj.get("window"), dict) else {}
    wctx = WindowContext(private_exes=tuple(w.get("private_exes") or PRIVATE_EXES),
                         private_profiles=tuple(w.get("private_profiles") or ("개인", "Personal")),
                         work_title_patterns=tuple(p for p in w.get("work_title_patterns") or ()
                                                   if _compile_ok(p) is not None), sctx=sctx)
    ww, off = _work_window(obj.get("work_window") if isinstance(obj.get("work_window"), dict) else {})
    return sctx, wctx, ww, off


# ───────────────────────────── 로컬 사전 갱신(P §9.6 · §11.3) ─────────────────────────────
def merge_person_dir(cur: dict, people: dict) -> dict:
    """사람 사전 병합(P §9.6): people 키 합집합, names·smtp 합집합, first 최소·last 최대, self·internal 은 OR."""
    out = {"format": PERSONDIR_FORMAT, "people": {}}
    base = cur.get("people") if isinstance(cur, dict) and isinstance(cur.get("people"), dict) else {}
    for wk, p in base.items():
        if isinstance(wk, str) and _WKEY_RX.match(wk) and isinstance(p, dict):
            out["people"][wk] = p
    for wk, p in (people or {}).items():
        old = out["people"].get(wk) or {}
        names = sorted({*(old.get("names") or []), *(p.get("names") or [])})
        smtp = sorted({*(old.get("smtp") or []), *(p.get("smtp") or [])})
        firsts = [x for x in (old.get("first"), p.get("first")) if isinstance(x, str) and x]
        lasts = [x for x in (old.get("last"), p.get("last")) if isinstance(x, str) and x]
        out["people"][wk] = {"names": names, "smtp": smtp, "self": bool(old.get("self") or p.get("self")),
                             "internal": bool(old.get("internal") or p.get("internal")),
                             "first": min(firsts) if firsts else "", "last": max(lasts) if lasts else ""}
    out["people"] = dict(sorted(out["people"].items()))
    return out


def _commit_fn(paths: Paths, mode: str):
    def commit(rc: RecordContext) -> int:
        from lm27.store.cursor import file_lock      # 지연 import(store → privacy 방향 순환 회피)
        n = 0
        if rc.people:
            if mode == "program":
                pdp, lock = paths.local_only_file("person_dir.json"), paths.local_only_file("person_dir.json.lock")
            else:
                pdp, lock = paths.person_dir_delta(), None
            ctx = file_lock(lock) if lock is not None else _nullctx()
            with ctx:
                cur = fsx.read_json(pdp, default={}) or {}
                merged = merge_person_dir(cur, rc.people)
                if merged != cur:
                    fsx.atomic_write(pdp, fsx.canon_bytes(merged) + b"\n")
            n += len(rc.people)
            rc.people = {}
        if rc.corresp_new and mode == "program":
            cp = paths.local_only_file("corresp_domains.json")
            with file_lock(paths.local_only_file("corresp_domains.json.lock")):
                cur = fsx.read_json(cp, default={}) or {}
                new = dict(cur)
                for d, day in rc.corresp_new.items():
                    if isinstance(new.get(d), str) and new[d] >= day:
                        continue
                    new[d] = day
                if new != cur:
                    fsx.atomic_write(cp, fsx.canon_bytes(dict(sorted(new.items()))) + b"\n")
            n += len(rc.corresp_new)
            rc.corresp_new = {}
        return n
    return commit


class _nullctx:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


# ───────────────────────────── 레코드 문맥 ─────────────────────────────
def _today(now) -> date:
    if isinstance(now, datetime):
        return (now if now.tzinfo else now.replace(tzinfo=UTC)).astimezone(UTC).date()
    if isinstance(now, date):
        return now
    return datetime.now(UTC).date()


def make_record_context(root, src: str, pc_id: str, *, agent_dir=None, stage: str = "collect", my_addrs=(),
                        paths: Paths | None = None, cfg=None, keyring=None, registry=None, local=None, os_names=None,
                        now=None, clock=None) -> RecordContext:
    r"""수집 실행 1회의 레코드 문맥(P §3.3). ``root=None`` 이면 에이전트 모드(``agent_dir`` 기본 ``Paths().agent_dir()``).
    ``my_addrs`` = 본인 SMTP 주소(메모리 전용 — 파이프는 첫 줄 ``_meta``). 그 밖 키워드 인자는 시험·호출자 주입용
    (``cfg``·``keyring``·``registry``·``local``·``os_names``·``now``·``clock``)."""
    if src not in ALL_SRCS:
        raise ValueError("make_record_context: 경로 ID 형식이 아닙니다")
    if root is None:
        ad = Path(os.fspath(agent_dir)) if agent_dir is not None else Paths().agent_dir()
        p = paths or _agent_paths(ad)
        st = "agent" if stage == "collect" else stage
        audit = AuditSink.open(None, pc_id, st, src, agent_dir=ad, clock=clock)
        kr = keyring or K.load_agent_keys(ad, audit) or K.NoKeys()
        cache = read_context_cache(ad)
        if cache is None:
            audit.add("cfg", "ctxcache_missing")
            cache = {}
        mode, local_obj, stage = "agent", None, st
    else:
        p = paths or Paths(root)
        if cfg is None:
            from lm27.config import load_config          # 프로그램 폴더 모드에서만(에이전트 사본에는 없다)
            cfg = load_config(p)
        audit = AuditSink.open(p.data(), pc_id, stage, src, paths=p, clock=clock)
        kr = keyring or K.load_keyring(p.data(), audit, create=True, origin=pc_id)
        if isinstance(local, dict):                        # 시험·호출자 주입: LocalOnly 필드 이름의 dict 도 받는다
            local = LocalOnly(**{k: v for k, v in local.items() if k in LocalOnly.__dataclass_fields__})
        local_obj = local if local is not None else LocalOnly.load(p)
        cache = context_cache_obj(p, cfg, kr=kr, registry=registry, local=local_obj, os_names=os_names, audit=audit)
        mode = "program"
    sctx, wctx, ww, off = contexts_from_cache(cache, kr)
    no_key = isinstance(kr, K.NoKeys) or (not isinstance(kr, K.Keyring) and sctx.person_subkey is None)
    corresp, ad_lists = set(), {}
    if mode == "program":
        cut = (_today(now) - timedelta(days=CORRESP_DAYS)).isoformat()
        corresp = {d for d, day in (local_obj.corresp_domains or {}).items()
                   if isinstance(d, str) and isinstance(day, str) and day >= cut}
        al = local_obj.ad_lists or {}
        ad_lists = {
            "block_domains": tuple(_domains([*(al.get("block_domains") or ()),
                                             *(_cfgv(cfg, "privacy.ad.blockDomains", ()) or ())])),
            "allow_domains": tuple(_domains([*(al.get("allow_domains") or ()),
                                             *(_cfgv(cfg, "privacy.ad.allowDomains", ()) or ())])),
            "block_senders": frozenset(x for x in al.get("block_senders") or () if isinstance(x, str)
                                       and _WKEY_RX.match(x)),
            "allow_senders": frozenset(x for x in al.get("allow_senders") or () if isinstance(x, str)
                                       and _WKEY_RX.match(x)),
            "block_subject_rx": tuple(re.compile(x) for x in _regexes(_cfgv(cfg, "privacy.ad.blockSubjectRegex", ()),
                                                                      audit))}
    rc = RecordContext(
        pc_id=pc_id, src=src, sctx=sctx, keyring=kr, corresp_domains=corresp, ad_lists=ad_lists,
        private_chats=set(cache.get("private_chats") or ()), work_window=ww, off_min=off, audit=audit, no_key=no_key,
        wctx=wctx, path_exclude=tuple(cache.get("path_exclude") or ("개인", "가족", "사진", "private", "personal")),
        private_categories=tuple(cache.get("private_categories") or ("개인", "Personal", "Private", "가족")),
        ad_extra_words=tuple(cache.get("ad_extra_words") or ()),
        private_extra_words=tuple(cache.get("private_extra_words") or ()),
        private_extra_work_words=tuple(cache.get("private_extra_work_words") or ()),
        final_words=tuple(cache.get("final_words") or ()), stage=stage, mode=mode)
    rc.add_my_addrs(my_addrs)
    audit.kid = getattr(kr, "kid", K.NO_KID)
    audit.config_hash = cache_hash(cache) if cache else None
    rc.on_commit = _commit_fn(p, mode)
    audit.after_flush = rc.commit_local
    return rc


# ───────────────────────────── 게이트 문맥(P §13.1) ─────────────────────────────
def _machine_guid() -> str:
    if os.name != "nt":
        return ""
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography", 0,
                            winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0)) as k:
            v, _t = winreg.QueryValueEx(k, "MachineGuid")
    except OSError:
        return ""
    return str(v or "").strip()


def make_gate_context(sctx, cfg, kr, *, stage: str, audit, web_grounding: bool = False, environ=None,
                      machine_guid: str | None = None, local=None, paths: Paths | None = None,
                      extra_canaries=()) -> GateContext:
    """게이트 문맥(P §13.1). ``sctx``·``kr`` 가 None 이면 서버 모드(정제 사전 없음·키 카나리아 없음). ``environ`` 을 주면
    그 사전에서 PC 이름·계정을 읽고 MachineGuid 레지스트리는 읽지 않는다(시험). 본인 주소 카나리아는 ``local``(또는
    ``paths`` 의 로컬 사전) person_dir 의 self 주소 + ``collect.ownerAddress``."""
    env = os.environ if environ is None else environ
    can = []
    for k in ("COMPUTERNAME", "USERNAME", "USERDOMAIN"):
        v = str(env.get(k) or "").strip()
        if v:
            can.append(v)
    up = str(env.get("USERPROFILE") or "").strip()
    if up:
        can.append(K.base_name(up))
    mg = machine_guid if machine_guid is not None else (_machine_guid() if environ is None else "")
    if mg:
        can += [mg, mg.replace("-", "")]
    if local is None and paths is not None:
        local = LocalOnly.load(paths)
    owner = str(_cfgv(cfg, "collect.ownerAddress", "") or "").strip()
    addrs = [owner] if "@" in owner else []
    for p in _people(local).values():
        if isinstance(p, dict) and p.get("self"):
            addrs += [a for a in p.get("smtp") or () if isinstance(a, str) and "@" in a]
            can += [n for n in p.get("names") or () if isinstance(n, str)]
    for a in addrs:
        can += [a, a.split("@", 1)[0]]
    if sctx is not None:
        can += list(sctx.self_names or ())
    if isinstance(kr, K.Keyring):
        can += [base64.b64encode(s).decode("ascii")[:16] for s in kr.all.values()]
    elif isinstance(kr, K.AgentKeys):
        can += [base64.b64encode(s).decode("ascii")[:16] for s in kr.subkeys.values()]
    can += [c for c in extra_canaries or () if isinstance(c, str)]
    pt = str(_cfgv(cfg, "privacy.copilot.personTokens", "plain") or "plain")
    if pt not in ("plain", "keyed") or web_grounding:
        pt = "plain"
    return GateContext(sctx=sctx if sctx is not None else SanitizeContext(),
                       canaries=tuple(sorted({c.strip() for c in can if c and c.strip()})), person_tokens=pt,
                       audit=audit, web_grounding=bool(web_grounding), stage=stage)
