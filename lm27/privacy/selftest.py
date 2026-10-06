# -*- coding: utf-8 -*-
r"""회귀 말뭉치 관문(P §18 · 계약 T-08) — ``run_selftest()`` 가 0 이면 통과, 1 이면 실패.

실행: ``python\python.exe -B tools\lm27_selftest.py privacy [--update-lock]`` = ``lm27 selftest privacy``.
lint 관문(``tools\lint.ps1 -Stage selftest``)·에이전트 설치·패키징 직전에 돈다(P §18.3).

절(section) — 실패 조건은 P §18.3:
  lock      규칙 고정: ``rules_hash()`` == ``rules.lock.json`` 의 rules_hash 이고 ``RULES_VERSION`` == rules_ver
  corpus    말뭉치 형식(id 중복·모르는 type 0)·최소 규모(양성 ≥30, 미끼 ≥20 — 말뭉치를 줄이는 변경 차단)
  pos·idem  양성: 출력 == 기대(사람 태그 ``#*`` 정규화)·건수 == 기대·drop 아님 / 멱등: 다시 정제해도 같고 건수 0
  drop·neg  자격증명 행 폐기 / 미끼: 출력 == 입력(공백 정규화)·건수 0
  ad·priv   광고 band · 공사 class
  win       창 분류(O-4 검증의 9건 — LM27 추가)
  gate      게이트 8 + 팀 라벨 6 — ``lm27.privacy.gate``(WP-11)
  ext       LM27 추가 22건 — scan·tokens_of(이 모듈 묶음) · doc_fam·키 동치(``lm27.privacy.keys`` — WP-11)
  template  코파일럿 프롬프트 템플릿 상수 전부 ``scan()`` 빈 목록 — ``lm27.bridge.stages.*``(WP-25)의 최상위
            대문자 상수 중 이름에 ``TEMPLATE``·``PROMPT`` 가 든 것(str, 또는 str 을 담은 tuple·list·dict)
  schema    ``lm27.privacy.records.SCHEMAS`` = ``schemas_v1.json`` 스냅숏(``schema_snapshot`` 형), 텍스트 열 ⊂ 열
  audit     감사 이벤트 형식 검사기 ``audit_violations`` 자기 점검(P §15.2 · T20 — 저장 지점 시험이 같은 함수를 쓴다)
  perf      20,000행 ≤ 5초 · 병적 입력 12종 각 ≤ 50ms — 넘으면 '경고'(계약 §11 '성능 경고 제외'), rc 에 영향 없음

'보류'(pending): 그 절이 쓰는 다른 작업 묶음의 모듈이 트리에 아직 없을 때. 조용히 넘기지 않고 절마다 '보류 — 모듈
없음' 으로 보고하며, 모듈 파일이 생기는 순간부터 그 절은 돌고 실패로 셀 수 있다(lint 관문의 '대상이 생기면 실패' 원칙).
``--update-lock`` 은 모든 절이 돌고 실패 0 일 때만 잠금을 쓴다(보류가 있으면 거부 — '말뭉치 전부 통과', P §16.4).

출력(I8): 말뭉치 id·건수·범주 코드·해시·판만. 원문·정제문·예시 문자열은 어디에도 내지 않는다. 사람용 줄은
``lm27.util.events`` 의 ``check`` 이벤트(텍스트 모드 = stderr, ``--events jsonl`` = stdout 한 줄 JSON)로 낸다.
"""
from __future__ import annotations

import importlib
import importlib.util
import pkgutil
import re
import sys
import time
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path

from lm27.paths import Paths
from lm27.util import events, fsx

from .classify import WindowContext, ad_score, private_score, window_class
from .detect import SanitizeContext, sanitize, subkey
from .rules import RULES_VERSION, rules_hash
from .scan import Hit, scan, tokens_of

__all__ = ["run_selftest", "rules_hash", "read_lock", "lock_matches", "load_corpus", "schema_snapshot",
           "audit_violations", "pathological_inputs", "PERF_ROWS", "PERF_ROW_SEC", "PERF_PATHO_MS"]

CORPUS_REL = ("corpus", "regress_v1.jsonl")
LOCK_REL = ("rules.lock.json",)
SCHEMAS_REL = ("schemas_v1.json",)
MIN_POS, MIN_NEG = 30, 20
PERF_ROWS, PERF_ROW_SEC, PERF_PATHO_MS = 20_000, 5.0, 50.0
TYPES = ("pos", "drop", "neg", "ad", "priv", "gate", "label", "win", "ext")
EXT_KEYS = frozenset({"doc_fam", "who_key_equiv", "doc_key_equiv", "agent_key_missing"})   # lm27.privacy.keys 필요
SCHEMAS_FORMAT = "lm27-schemas/1"
VER_RX = re.compile(r"^\d{4}\.\d{1,2}\.\d{1,3}$")
HASH16_RX = re.compile(r"^[0-9a-f]{16}$")
PERSON_TAG = re.compile(r"\[사람#[0-9a-f]{6}\]")
WS2 = re.compile(r"\s{2,}")
TEMPLATE_NAME = re.compile(r"(?:^|_)(?:TEMPLATE|PROMPT)S?(?:_|$)")
DEP_KEYS, DEP_GATE, DEP_RECORDS = "lm27.privacy.keys", "lm27.privacy.gate", "lm27.privacy.records"
DEP_STAGES = "lm27.bridge.stages"


# ── 자원·의존 ───────────────────────────────────────────────────────────────────────
def _resource(*rel: str) -> Path:
    """이 패키지(``lm27\\privacy\\``)에 함께 배포되는 파일 — 말뭉치·잠금·스키마 스냅숏(시험은 이 함수를 바꿔 끼운다)."""
    return Paths().package_dir().joinpath("privacy", *rel)


def _dep(name: str):
    """다른 작업 묶음 소유 모듈. 모듈 파일(또는 패키지 폴더)이 트리에 아직 없으면 None — 그 절은 '보류'로 보고된다.
    없을 때는 부모 패키지도 import 하지 않는다(다른 묶음의 작업 중 파일을 건드리지 않게). ``sys.modules`` 에 이미 있으면
    그것을 쓴다(값이 None 이면 '없음' — 시험이 부재를 흉내 낼 때)."""
    if name in sys.modules:
        return sys.modules[name]
    base = Paths().root.joinpath(*name.split("."))
    if not (base.is_dir() or base.with_name(base.name + ".py").is_file()):
        return None
    if importlib.util.find_spec(name) is None:
        return None
    return importlib.import_module(name)


def _ver(v: str) -> tuple:
    return tuple(int(x) for x in v.split("."))


# ── 잠금(P §16.2·§16.4) ────────────────────────────────────────────────────────────
def read_lock(path=None) -> dict | None:
    """``rules.lock.json`` → ``{"rules_ver", "rules_hash"}``. 없거나 형식이 다르면 None(형식 오류는 fsx 가 stderr 경고)."""
    obj = fsx.read_json(path or _resource(*LOCK_REL), default=None)
    if not isinstance(obj, dict):
        return None
    ver, h = obj.get("rules_ver"), obj.get("rules_hash")
    if not (isinstance(ver, str) and VER_RX.match(ver) and isinstance(h, str) and HASH16_RX.match(h)):
        return None
    return {"rules_ver": ver, "rules_hash": h}


def lock_matches(path=None) -> bool:
    """지금 규칙이 잠금과 같은가(판·해시 모두). 배포본이 다르면 '검증 안 된 규칙'(P §20 ``selftest.lock_mismatch``)."""
    lk = read_lock(path)
    return bool(lk) and lk["rules_ver"] == RULES_VERSION and lk["rules_hash"] == rules_hash()


def _write_lock(path, h: str) -> None:
    fsx.atomic_write(path, fsx.canon_bytes({"rules_hash": h, "rules_ver": RULES_VERSION}) + b"\n")


# ── 말뭉치 ─────────────────────────────────────────────────────────────────────────
class CorpusError(ValueError):
    """말뭉치 파일 형식 오류(메시지는 줄 번호뿐 — 내용 없음)."""


def load_corpus(path=None) -> list:
    """말뭉치 JSONL(UTF-8 LF, 한 줄 1건) → dict 목록. 빈 줄은 건너뛴다. 깨진 줄은 CorpusError(줄 번호만)."""
    raw = fsx.read_bytes(path or _resource(*CORPUS_REL)).decode("utf-8")
    out = []
    for i, line in enumerate(raw.split("\n"), 1):
        if not line.strip():
            continue
        try:
            obj = fsx.loads_strict(line)
        except ValueError:
            raise CorpusError(f"말뭉치 {i}번째 줄 JSON 형식 오류") from None
        if not isinstance(obj, dict) or not isinstance(obj.get("id"), str) or obj.get("type") not in TYPES:
            raise CorpusError(f"말뭉치 {i}번째 줄 형식 오류(id·type)")
        out.append(obj)
    return out


def _ctx(d) -> SanitizeContext:
    return SanitizeContext(**d) if d else SanitizeContext()


# ── 스키마 스냅숏(P §18.3 '스키마') ──────────────────────────────────────────────────
def _field(spec, name):
    return spec.get(name) if isinstance(spec, dict) else getattr(spec, name)


def schema_snapshot(schemas: dict) -> dict:
    """``SCHEMAS``(kind → 열 허용 목록 spec) → ``schemas_v1.json`` 형 ``{"format": "lm27-schemas/1",
    "kinds": {kind: {"columns": [...], "text_fields": [...]}}}``(이름순). spec 은 ``columns``·``text_fields``
    속성(또는 dict 키)을 가진다 — text_fields 가 dict 이면 그 키. 저장 지점(WP-11)이 이 함수로 스냅숏 파일을 만든다."""
    kinds = {}
    for kind in sorted(schemas):
        spec = schemas[kind]
        kinds[kind] = {"columns": sorted(_field(spec, "columns")), "text_fields": sorted(_field(spec, "text_fields"))}
    return {"format": SCHEMAS_FORMAT, "kinds": kinds}


# ── 감사 이벤트 형식(P §15.2·§15.3 · T20) ─────────────────────────────────────────────
AUDIT_EVS = frozenset({"collect_batch", "load_resanitize", "gate_copilot", "gate_prompt", "gate_team", "rewrite_redact",
                       "key", "config", "selftest", "merge"})
# 이벤트 본문 키는 P §15.2 의 18개만(계약 §3.13). 본문의 경로 ID 키는 path_id(계약 v1.2 C10 — 봉투 src = 단계 이름과
# 겹치지 않게). 세그먼트 봉투 필드(id·kind·src)는 envelope=True 일 때만 허용.
AUDIT_NUM_KEYS = frozenset({"rows_in", "rows_out", "dur_ms"})
AUDIT_DICT_KEYS = frozenset({"dropped", "masked", "priv", "ad", "err"})
AUDIT_STR_RX = {
    "ev": re.compile(r"^[a-z_]{2,24}$"), "ts_utc": re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"),
    "pc_id": re.compile(r"^pcx?_[0-9a-f]{16}$"), "stage": re.compile(r"^[a-z][a-z0-9_:\-]{0,47}$"),
    "path_id": re.compile(r"^(?:(?:mail|cal|teams|pc)\.[a-z]{2,10}|[a-z][a-z0-9_]{1,15})$"), "rules_ver": VER_RX,
    "rules_hash": HASH16_RX, "config_hash": HASH16_RX, "kid": re.compile(r"^k[0-9a-f]{8}$"),
    "out_sha256": re.compile(r"^[0-9a-f]{16}(?:[0-9a-f]{48})?$")}
AUDIT_ENVELOPE_RX = {"id": HASH16_RX, "kind": re.compile(r"^privacy_audit$"),
                     "src": re.compile(r"^[a-z][a-z0-9_:\-]{0,47}$")}      # 봉투 src = 단계 이름(C10)
AUDIT_SUBKEY_RX = re.compile(r"^(?:[a-z][a-z0-9_.:\-]{0,47}|[A-Z][A-Za-z0-9_]{0,47})$")   # 범주·사유 코드 또는 예외 타입명
# 16진 해시·ID — 숫자열 검사 면제(pc_id 도 해시 앞 16hex 라 숫자 9자 이상이 정상으로 나온다: pc_0123456789abcdef)
_HASH_KEYS = frozenset({"rules_hash", "config_hash", "out_sha256", "id", "pc_id"})
_DIGITS9 = re.compile(r"\d{9,}")
_HANGUL_SENTENCE = re.compile(r"[가-힣]{2,}\s+[가-힣]{2,}")


def audit_violations(ev: dict, *, envelope: bool = False) -> list:
    """감사 이벤트 1건의 형식 위반 코드 목록(빈 목록 = 통과). 본문 키는 P §15.2 의 18개만(계약 §3.13 — 경로 ID 키는
    ``path_id``(C10), ``envelope=True`` 이면 세그먼트 봉투 필드 ``id``·``kind``·``src`` 도 허용), 값은 숫자·판·16진
    해시·범주 코드·경로 ID·단계 이름 뿐, 문자열에 ``@``·9자리 이상 숫자열·한글 문장 금지(T20 — 16진 해시·ID 키는 숫자열
    검사 면제). 위반 코드에는 키 이름만 넣는다(값 없음)."""
    v = []
    if not isinstance(ev, dict):
        return ["type"]
    if ev.get("ev") not in AUDIT_EVS:
        v.append("ev")
    str_rx = dict(AUDIT_STR_RX, **AUDIT_ENVELOPE_RX) if envelope else AUDIT_STR_RX
    for k, val in ev.items():
        if k in str_rx:
            if not isinstance(val, str) or not str_rx[k].match(val):
                v.append("value:" + k)
        elif k in AUDIT_NUM_KEYS:
            if isinstance(val, bool) or not isinstance(val, (int, float)) or val < 0:
                v.append("value:" + k)
        elif k in AUDIT_DICT_KEYS:
            if not isinstance(val, dict):
                v.append("value:" + k)
                continue
            for sk, sv in val.items():
                if not isinstance(sk, str) or not AUDIT_SUBKEY_RX.match(sk) or _DIGITS9.search(sk):
                    v.append("subkey:" + k)
                elif isinstance(sv, bool) or not isinstance(sv, (int, float)) or sv < 0:
                    v.append("value:" + k)
        else:
            v.append("key:" + (k if isinstance(k, str) and AUDIT_SUBKEY_RX.match(k) else "?"))
        if isinstance(val, str) and k not in _HASH_KEYS:
            if "@" in val or _DIGITS9.search(val) or _HANGUL_SENTENCE.search(val):
                v.append("forbidden:" + k)
    return sorted(set(v))


_AUDIT_REF = {"ev": "collect_batch", "ts_utc": "2026-10-05T01:02:03Z", "pc_id": "pc_9a1b2c3d4e5f6a7b", "stage": "collect",
              "path_id": "mail.com", "rules_ver": "2026.10.0", "rules_hash": "4a684ebdcf99f956",
              "config_hash": "9c1e0b7a22d4f3e1", "kid": "k3f9a1c2e", "rows_in": 812, "rows_out": 640,
              "dropped": {"ad": 160, "cred": 2, "bad_raw": 10},
              "masked": {"phone": 14, "email": 230, "money": 9, "person": 412, "customer": 21},
              "priv": {"work": 598, "private": 37, "social": 5}, "ad": {"keep": 621, "suspect": 19, "drop": 160, "partial": 0},
              "err": {"KeyError": 0}, "out_sha256": "0" * 64, "dur_ms": 4210}       # P §15.2 예(해시 값은 형식 예)


def _audit_probes():
    """검사기가 잡아야 하는 위반(시험용 합성)."""
    yield dict(_AUDIT_REF, stage="collect" + chr(64) + "x")
    yield dict(_AUDIT_REF, extra_text="x")
    yield dict(_AUDIT_REF, masked={"phone": "열네 건"})
    yield dict(_AUDIT_REF, path_id="정제 시험 문장")
    yield dict(_AUDIT_REF, err={"1" * 10: 1})


# ── 성능(P §18.3·§19 T18 · 계약 T-19) ───────────────────────────────────────────────
def pathological_inputs() -> list:
    """병적 입력 12종(P §19 T18) — (이름, 문자열). 런타임에 조립한다(제어문자·전각·이모지를 소스에 두지 않음)."""
    return [
        ("comma_digits", "1," * 8000),
        ("at_signs", "@" * 10000),
        ("dashes", "-" * 10000),
        ("hangul", "가" * 10000),
        ("brackets", "[" * 5000),
        ("long_url", "https://www.example.com/" + "seg/" * 1000 + "?q=" + "1" * 200),
        ("long_path", "C:\\" + "폴더\\" * 1400 + "파일.xlsx"),
        ("zeros", "0" * 4000),
        ("fullwidth_digits", "".join(chr(0xFF10 + i % 10) for i in range(4000))),
        ("emoji", chr(0x1F600) * 4000),
        ("control_chars", "".join(chr(1 + i % 8) for i in range(4000))),
        ("tokens", "[전화]" * 2000),
    ]


# ── 절 ─────────────────────────────────────────────────────────────────────────────
@dataclass
class _Sec:
    key: str
    name_ko: str
    state: str = "pass"                 # pass · fail · pending · warn
    ok: int = 0
    total: int = 0
    failed: list = field(default_factory=list)
    note: str = ""

    def check(self, ident: str, good: bool, why: str = "") -> None:
        self.total += 1
        if good:
            self.ok += 1
        else:
            self.failed.append(ident + (f"({why})" if why else ""))
            self.state = "fail"

    def fail(self, note: str) -> None:
        self.state, self.note = "fail", note

    def pend(self, note: str) -> None:
        if self.state != "fail":
            self.state = "pending"
        self.note = note


def _err_note(e: BaseException) -> str:
    """절 안 예외의 보고 문구 — 코드 형태 오류(속성·인자·import)만 메시지를 싣고, 그 밖은 예외 유형만(I8)."""
    if isinstance(e, (AttributeError, TypeError, ImportError)):
        return f"{type(e).__name__}: {str(e)[:160]}"
    return type(e).__name__


def _sec_lock(update_lock: bool) -> _Sec:
    s = _Sec("lock", "규칙 고정")
    h = rules_hash()
    s.note = f"{RULES_VERSION} · {h}"
    if update_lock:
        s.state = "pending"
        s.note += " · 잠금 갱신 대기(모든 절 통과 시 기록)"
        return s
    lk = read_lock()
    if lk is None:
        s.check("lock", False, "잠금 파일 없음·형식 오류")
    elif lk["rules_ver"] == RULES_VERSION and lk["rules_hash"] != h:
        s.check("lock", False, "규칙이 바뀌었는데 판·말뭉치·잠금 갱신 안 됨(P §16.4)")
    elif lk["rules_ver"] != RULES_VERSION:
        s.check("lock", False, f"판 불일치(잠금 {lk['rules_ver']})")
    else:
        s.check("lock", True)
    return s


def _sec_corpus(rows: list) -> _Sec:
    s = _Sec("corpus", "말뭉치 형식·최소 규모")
    ids = [r["id"] for r in rows]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    s.check("ids", not dup, ("id 중복 " + ",".join(dup[:5])) if dup else "")
    n_pos = sum(r["type"] == "pos" for r in rows)
    n_neg = sum(r["type"] == "neg" for r in rows)
    s.check("min_pos", n_pos >= MIN_POS, f"양성 {n_pos} < {MIN_POS}")
    s.check("min_neg", n_neg >= MIN_NEG, f"미끼 {n_neg} < {MIN_NEG}")
    counts = {t: sum(r["type"] == t for r in rows) for t in TYPES}
    s.note = " ".join(f"{t}{n}" for t, n in counts.items() if n)
    return s


def _sec_pos(rows: list) -> tuple[_Sec, _Sec]:
    sp, si = _Sec("pos", "양성(가림)"), _Sec("idem", "멱등")
    for r in (x for x in rows if x["type"] == "pos"):
        try:
            ctx = _ctx(r.get("ctx"))
            res = sanitize(r["text"], ctx=ctx)
            exp = r["expect"]
            got = PERSON_TAG.sub("[사람#*]", res.text) if "#*" in exp else res.text
            why = ",".join(w for w, bad in (("text", got != exp), ("hits", res.hits != r.get("hits", {})),
                                            ("drop", res.drop)) if bad)
            sp.check(r["id"], not why, why)
            res2 = sanitize(res.text, ctx=ctx)
            si.check(r["id"], res2.text == res.text and not res2.hits)
        except Exception as e:                  # 한 건의 예외는 그 건의 실패(나머지는 계속)
            sp.check(r["id"], False, type(e).__name__)
    return sp, si


def _sec_simple(rows: list) -> list:
    sd, sn = _Sec("drop", "자격증명 폐기"), _Sec("neg", "오탐 미끼")
    sa, sq, sw = _Sec("ad", "광고 점수"), _Sec("priv", "공사 구분"), _Sec("win", "창 분류")
    by_type = {"drop": sd, "neg": sn, "ad": sa, "priv": sq, "win": sw}
    for r in rows:
        t = r["type"]
        if t not in by_type:
            continue
        try:
            if t == "drop":
                good = sanitize(r["text"], ctx=_ctx(r.get("ctx"))).drop
            elif t == "neg":
                res = sanitize(r["text"], ctx=_ctx(r.get("ctx")))
                good = res.text == WS2.sub(" ", r["text"]).strip() and not res.hits and not res.drop
            elif t == "ad":
                good = ad_score(r["meta"])[1] == r["band"]
            elif t == "priv":
                good = private_score(r["text"], **(r.get("kw") or {}))[1] == r["class"]
            else:
                good = window_class(r["exe"], r["title"], r.get("app_class", ""), WindowContext()).priv_class == r["class"]
            by_type[t].check(r["id"], good)
        except Exception as e:
            by_type[t].check(r["id"], False, type(e).__name__)
    return [sd, sn, sa, sq, sw]


def _sec_gate(rows: list) -> _Sec:
    s = _Sec("gate", "게이트·팀 라벨")
    items = [r for r in rows if r["type"] in ("gate", "label")]
    if not items:
        return s
    try:
        g = _dep(DEP_GATE)
        if g is None:
            s.pend(f"{DEP_GATE} 없음 — {len(items)}건 보류(WP-11)")
            return s
        stage = g.StageSpec(name="classify", allowed_fields=frozenset({"id", "text"}), text_fields=frozenset({"text"}))
    except Exception as e:
        s.fail(_err_note(e))
        return s
    for r in items:
        try:
            gctx = g.GateContext(sctx=_ctx(r.get("ctx")), canaries=tuple(r.get("canaries") or ()))
            if r["type"] == "label":
                s.check(r["id"], list(g.check_team_label(r["text"], gctx)) == r["violations"])
                continue
            item = g.GateItem(item_id=r["id"], fields={"id": r["id"], "text": r["text"]}, meta={"priv_class": "work"})
            res = g.gate_copilot([item], stage, gctx)
            if r["expect"] == "keep":
                good = len(res.kept) == 1 and res.kept[0].fields.get("text") == r["out"] and not res.dropped
            else:
                good = not res.kept and len(res.dropped) == 1 and res.dropped[0][1] == r["why"]
            s.check(r["id"], good)
        except Exception as e:
            s.check(r["id"], False, type(e).__name__)
    return s


def _keyrings(keys, master_hex: str):
    k = bytes.fromhex(master_hex)
    kid = "k" + sha256(k).hexdigest()[:8]
    kr = keys.Keyring(primary_kid=kid, primary_secret=k, all={kid: k})
    ak = keys.AgentKeys(kid=kid, subkeys={p: subkey(k, p) for p in keys.AGENT_PURPOSES})
    return kr, ak


def _ext_one(r: dict, rows: list, keys) -> bool:
    fn = r["fn"]
    if fn == "scan":
        got = scan(r["arg"])
        return all(isinstance(h, Hit) for h in got) and [[h.cat, h.n] for h in got] == r["expect"]
    if fn == "scan_pos_idem":
        for p in (x for x in rows if x["type"] == "pos"):
            ctx = _ctx(p.get("ctx"))
            if scan(sanitize(p["text"], ctx=ctx).text, ctx) != []:
                return False
        return True
    if fn == "tokens_of":
        return tokens_of(r["arg"]) == r["expect"]
    if fn == "tokens_of_len":
        return len(tokens_of(r["arg"])) == r["expect"]
    if fn == "person_tag_equiv":
        k = bytes.fromhex(r["master_hex"])
        a = sanitize(r["arg"], ctx=SanitizeContext(key=k)).text
        b = sanitize(r["arg"], ctx=SanitizeContext(person_subkey=subkey(k, "person"))).text
        return a == b and "[사람#" in a
    if fn == "doc_fam":
        return keys.doc_fam(r["arg"]) == r["expect"]
    kr, ak = _keyrings(keys, r["master_hex"])
    if fn == "who_key_equiv":
        a, b = keys.who_key(kr, r["arg"]), keys.who_key(ak, r["arg"])
        return a == b and re.fullmatch(r"w[0-9a-f]{16}", a) is not None
    if fn == "doc_key_equiv":
        got = {keys.doc_key(x, name) for name in r["args"] for x in (kr, ak)}
        return len(got) == 1 and re.fullmatch(r"d[0-9a-f]{16}", next(iter(got))) is not None
    if fn == "agent_key_missing":
        try:
            keys.keyed(ak, *r["args"])
        except keys.NoKeyError:
            return True
        return False
    raise ValueError("모르는 ext 함수")


def _sec_ext(rows: list) -> _Sec:
    s = _Sec("ext", "LM27 추가(scan·tokens·doc_fam·키)")
    items = [r for r in rows if r["type"] == "ext"]
    keys, pending = None, 0
    if any(r.get("fn") in EXT_KEYS for r in items):
        try:
            keys = _dep(DEP_KEYS)
        except Exception as e:
            s.fail(_err_note(e))
            return s
    for r in items:
        if r.get("fn") in EXT_KEYS and keys is None:
            pending += 1
            continue
        try:
            s.check(r["id"], _ext_one(r, rows, keys))
        except Exception as e:
            s.check(r["id"], False, type(e).__name__)
    if pending:
        s.pend(f"{DEP_KEYS} 없음 — {pending}건 보류(WP-11)")
    return s


def _strings(val):
    if isinstance(val, str):
        yield val
    elif isinstance(val, dict):
        for v in val.values():
            yield from _strings(v)
    elif isinstance(val, (list, tuple)):
        for v in val:
            yield from _strings(v)


def _sec_template() -> _Sec:
    s = _Sec("template", "프롬프트 템플릿 scan 0")
    try:
        pkg = _dep(DEP_STAGES)
        if pkg is None:
            s.pend(f"{DEP_STAGES} 없음 — 보류(WP-25)")
            return s
        names = sorted(m.name for m in pkgutil.iter_modules(getattr(pkg, "__path__", [])))
        for n in names:
            mod = importlib.import_module(f"{DEP_STAGES}.{n}")
            for attr in sorted(vars(mod)):
                if attr.isupper() and TEMPLATE_NAME.search(attr):
                    for i, txt in enumerate(_strings(getattr(mod, attr))):
                        s.check(f"{n}.{attr}[{i}]", scan(txt) == [])
    except Exception as e:
        s.fail(_err_note(e))
        return s
    if s.total == 0:
        s.pend("템플릿 상수 0개(이름에 TEMPLATE·PROMPT) — 보류")
    return s


def _sec_schema() -> _Sec:
    s = _Sec("schema", "열 허용 목록 스냅숏")
    try:
        rec = _dep(DEP_RECORDS)
        if rec is None:
            s.pend(f"{DEP_RECORDS} 없음 — 보류(WP-11)")
            return s
        snap = schema_snapshot(rec.SCHEMAS)
        want = fsx.read_json(_resource(*SCHEMAS_REL), default=None)
        if not isinstance(want, dict) or want.get("format") != SCHEMAS_FORMAT:
            s.check("schemas_v1.json", False, "파일 없음·형식 다름")
            return s
        wk, sk = want.get("kinds") or {}, snap["kinds"]
        for kind in sorted(set(wk) | set(sk)):
            s.check(kind, wk.get(kind) == sk.get(kind), "스냅숏과 다름")
            cols = set(sk.get(kind, {}).get("columns", []))
            s.check(kind + ":text", set(sk.get(kind, {}).get("text_fields", [])) <= cols, "텍스트 열이 열 목록 밖")
    except Exception as e:
        s.fail(_err_note(e))
    return s


def _sec_audit() -> _Sec:
    s = _Sec("audit", "감사 형식 검사기")
    s.check("ref", audit_violations(_AUDIT_REF) == [])
    for i, ev in enumerate(_audit_probes(), 1):
        s.check(f"probe{i}", audit_violations(ev) != [])
    return s


def _best_ms(fn, tries: int = 3) -> float:
    best = None
    for _ in range(tries):
        t0 = time.perf_counter()
        fn()
        dt = (time.perf_counter() - t0) * 1000.0
        best = dt if best is None or dt < best else best
    return best


def _sec_perf(rows: list) -> _Sec:
    s = _Sec("perf", "성능")
    pool = [(r["text"], _ctx(r.get("ctx"))) for r in rows if r["type"] in ("pos", "neg")]
    if not pool:
        s.pend("양성·미끼 없음")
        return s
    t0 = time.perf_counter()
    for i in range(PERF_ROWS):
        text, ctx = pool[i % len(pool)]
        sanitize(text, ctx=ctx)
    sec = time.perf_counter() - t0
    slow = [] if sec <= PERF_ROW_SEC else [f"rows {sec:.2f}s"]
    patho = pathological_inputs()
    worst = 0.0
    for name, text in patho:
        ms = _best_ms(lambda text=text: sanitize(text))
        worst = max(worst, ms)
        if ms > PERF_PATHO_MS:
            slow.append(f"{name} {ms:.0f}ms")
    s.total = 1 + len(patho)
    s.ok = s.total - len(slow)
    s.note = f"{PERF_ROWS}행 {sec:.2f}s · 병적 입력 최대 {worst:.1f}ms"
    if slow:
        s.state, s.failed = "warn", slow
    return s


# ── 실행 ───────────────────────────────────────────────────────────────────────────
_STATE_KO = {"pass": "통과", "fail": "실패", "pending": "보류", "warn": "경고"}


def _report(s: _Sec) -> None:
    head = f"  {s.name_ko} … {_STATE_KO[s.state]}"
    if s.total:
        head += f" {s.ok}/{s.total}"
    if s.note:
        head += f" — {s.note}"
    if s.failed:
        head += " · " + ", ".join(s.failed[:12]) + (" …" if len(s.failed) > 12 else "")
    events.emit("check", stage="selftest", name=s.key, state=s.state, ok=s.ok, total=s.total,
                failed=s.failed[:40] or None, text_ko=head)


def _finish_lock(secs: list) -> None:
    """``--update-lock``: 모든 절이 돌고 실패 0 일 때만 기록(P §16.4 ④). 판을 안 올리고 해시만 바뀌면 거부(③)."""
    lock_sec, others = secs[0], secs[1:]
    if any(x.state == "fail" for x in others):
        lock_sec.fail("실패 절이 있어 잠금을 쓰지 않음")
        return
    if any(x.state == "pending" for x in others):
        lock_sec.fail("보류 절이 있어 잠금을 쓰지 않음(말뭉치 전부 통과 필요)")
        return
    h = rules_hash()
    path = _resource(*LOCK_REL)
    lk = read_lock(path)
    if lk and lk["rules_ver"] == RULES_VERSION and lk["rules_hash"] != h:
        lock_sec.fail("규칙이 바뀌었는데 RULES_VERSION 을 올리지 않음(P §16.4 ③)")
    elif lk and _ver(RULES_VERSION) < _ver(lk["rules_ver"]):
        lock_sec.fail(f"판을 내릴 수 없음(잠금 {lk['rules_ver']})")
    else:
        _write_lock(path, h)
        lock_sec.state, lock_sec.ok, lock_sec.total = "pass", 1, 1
        lock_sec.note = f"{RULES_VERSION} · {h} · 잠금 기록"


def run_selftest(corpus_path=None, *, update_lock: bool = False, perf: bool = True) -> int:
    """회귀 말뭉치 관문 전부를 돌린다. 0 = 통과(실패 0 — 보류·성능 경고는 rc 에 영향 없음), 1 = 실패.
    ``update_lock=True`` 이면 모든 절이 돌고 실패 0 일 때만 ``rules.lock.json`` 을 지금 규칙의 ``{rules_ver, rules_hash}``
    로 쓴다 — 판(RULES_VERSION)을 올리지 않고 해시만 바뀌었으면 거부(P §16.4 ③). ``perf=False`` 는 성능 절(약 1초,
    경고 전용)을 건너뛴다 — 에이전트 설치 직전 검사처럼 시간이 빠듯한 호출용(계약 시그니처의 선택 인자 추가)."""
    events.emit("check", stage="selftest", name="start", state="run",
                text_ko=f"[selftest privacy] 규칙 {RULES_VERSION} · 해시 {rules_hash()}")
    secs: list[_Sec] = [_sec_lock(update_lock)]
    try:
        rows = load_corpus(corpus_path)
    except (OSError, CorpusError, UnicodeDecodeError) as e:
        c = _Sec("corpus", "말뭉치 형식·최소 규모")
        c.fail(str(e) if isinstance(e, CorpusError) else f"읽기 실패({type(e).__name__})")
        secs.append(c)
        rows = None
    if rows is not None:
        secs.append(_sec_corpus(rows))
        secs.extend(_sec_pos(rows))
        secs.extend(_sec_simple(rows))
        secs.append(_sec_gate(rows))
        secs.append(_sec_ext(rows))
    secs.extend((_sec_template(), _sec_schema(), _sec_audit()))
    if rows is not None and perf:
        secs.append(_sec_perf(rows))
    if update_lock:
        _finish_lock(secs)
    for s in secs:
        _report(s)
    n_fail = sum(s.state == "fail" for s in secs)
    n_pend = sum(s.state == "pending" for s in secs)
    n_warn = sum(s.state == "warn" for s in secs)
    rc = 1 if n_fail else 0
    events.emit("check", stage="selftest", name="summary", state="fail" if rc else "pass", fail=n_fail, pending=n_pend,
                warn=n_warn, rc=rc,
                text_ko=f"  결과: {'실패' if rc else '통과'} (실패 절 {n_fail} · 보류 {n_pend} · 경고 {n_warn})")
    return rc
