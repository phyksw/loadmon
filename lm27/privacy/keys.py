# -*- coding: utf-8 -*-
r"""가명 키(HMAC)·키링·에이전트 하위 키·문서군 정규화(P §9 · 계약 §4.2 · §4.3 · C16).

키 2층(P §9.1 · 계약 §4.2 · D-18):
  · L1 주 키 — ``data\keys\privacy_keyring.json``(``lm27-keyring/1``). 폴더와 함께 PC 사이를 따라가지만 manifest·세그먼트·
    팀 묶음·코파일럿·zip 에는 넣지 않는다. ``kid = "k" + sha256(secret)[:8]``.
  · L1′ 에이전트 하위 키 — ``%LOCALAPPDATA%\LoadMonitor27\agent\keys\subkeys.json``(``lm27-subkeys/1``), ``AGENT_PURPOSES``
    만. 주 키는 에이전트에 두지 않는다.
  · L2 팀 pepper — ``peer_key`` 만(행·세그먼트에 쓰지 않는다).

하위 키 ``subkey(master, purpose) = HMAC-SHA256(master, b"lm27:" + purpose)``, ``keyed(kr, purpose, value, n)`` =
``hex(HMAC-SHA256(subkey, value))[:n]`` — 키링(``Keyring``)과 에이전트 하위 키(``AgentKeys``)가 같은 값을 낸다(P-T28).
HMAC 재료는 **정제 전 원문**(메모리)이다. 이 모듈의 함수는 원문을 돌려주지 않고, 예외 메시지·감사에 원문을 싣지 않는다.

문서군 정규화 ``doc_fam(name)`` 은 한 함수다(계약 §4.3, P 의 ``doc_norm`` 은 폐지 — R0-7). 계약 v1.2 결정 C16 대로
P §18.2 D01~D08 기대값을 그대로 만족한다: 기본 이름만(경로면) → NFKC·소문자 → 확장자(복합 ``.gz·.zip·.7z``·Creo 판번호
``.prt.12`` 포함 — W §4.1) → 꼬리 반복 제거(최대 5회: 낱말 꼬리 ``복사본·사본·수정본·copy·최종·final`` 과 판 꼬리
``v3·rev2·r1`` 은 **앞에 구분자가 있을 때만**, ``(1)``) → 결과가 비면 원래 이름 → 구분자(공백·_·-·.)를 ``_`` 로 통일.
날짜 꼬리(``주간보고_20261005``)는 남긴다 — 서로 다른 주의 보고서를 한 문서로 묶지 않는다(P §9.3, D05).

키 계산 규칙(``DOC_*``·``PURPOSES``)은 규칙 해시(``RULES_HASH``)에 넣지 않는다 — 바꾸면 ``KEYS_VERSION`` 을 올린다(P §16.2).
이 모듈은 에이전트 bin 사본(계약 §1.3)에도 들어가므로 표준 라이브러리와 사본 안 모듈만 쓴다.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import os
import re
import secrets
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote, urlsplit

from lm27.paths import Paths
from lm27.util import fsx

from .detect import norm_person, subkey

__all__ = [
    "AGENT_PURPOSES", "KEYRING_FORMAT", "KEYS_VERSION", "NO_KID", "PURPOSES", "SUBKEYS_FORMAT",
    "AgentKeys", "Keyring", "KeyringError", "NoKeyError", "NoKeyringError", "NoKeys",
    "base_name", "cal_key", "chat_key", "commit_key", "dir_key", "dir_keys_of", "dir_segments", "doc_fam", "doc_key", "keyed",
    "kid_of", "load_agent_keys", "load_keyring", "msg_key", "path_key", "path_norm", "peer_key", "person_ident",
    "repo_key", "seg_norm", "thread_key", "who_key", "write_agent_subkeys",
]

KEYS_VERSION = "lm27-keys/1"
KEYRING_FORMAT = "lm27-keyring/1"
SUBKEYS_FORMAT = "lm27-subkeys/1"
PURPOSES = ("person", "msg", "thread", "chat", "cal", "doc", "path", "dir", "repo", "commit", "unit", "host", "peer")
AGENT_PURPOSES = ("person", "msg", "thread", "chat", "doc", "path", "dir")
NO_KID = "k00000000"                    # 키 없음 모드의 kid 자리값(형식은 지키되 어떤 실제 키와도 겹치지 않는 값)
KID_RX = re.compile(r"^k[0-9a-f]{8}$")
SECRET_BYTES = 32
_PC_RX = re.compile(r"^pcx?_[0-9a-f]{16}$")
_UTC_RX = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_EMAIL_RX = re.compile(r"^[A-Za-z0-9._%+\-]{1,64}@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,24}$")


class NoKeyError(KeyError):
    """에이전트가 받지 못한 용도의 키를 요구함(또는 키 없음 모드) → 그 행은 no_key 규칙으로 처리(P §9.4)."""


class KeyringError(Exception):
    """키링 파일 문제(메시지에는 파일 이름·유형만 — 비밀값·원문 없음)."""


class NoKeyringError(KeyringError):
    """키링이 없다(``create=False``). [수집] 진입점은 이 예외를 받으면 ``create=True`` 로 다시 부른다(P §9.5)."""


# ───────────────────────────── 키 객체 ─────────────────────────────
@dataclass(frozen=True)
class Keyring:
    """프로그램 폴더 실행(주 키 보유). ``all`` = kid → 비밀값(retired 포함 — 옛 행의 별칭 재계산용).
    repr 에 비밀값을 싣지 않는다(예외·로그로 새지 않게)."""
    primary_kid: str
    primary_secret: bytes = field(repr=False)
    all: dict = field(default_factory=dict, repr=False)

    @property
    def kid(self) -> str:
        return self.primary_kid

    def sub(self, purpose: str) -> bytes:
        return subkey(self.primary_secret, purpose)


@dataclass(frozen=True)
class AgentKeys:
    """PC 상주 에이전트(주 키 없음) — 용도별 하위 키만(``AGENT_PURPOSES``). 없는 용도는 ``NoKeyError``."""
    kid: str
    subkeys: dict = field(repr=False)

    def sub(self, purpose: str) -> bytes:
        try:
            return self.subkeys[purpose]
        except KeyError:
            raise NoKeyError(purpose) from None


@dataclass(frozen=True)
class NoKeys:
    """키 없음 모드(P §9.4 — 에이전트 ``subkeys.json`` 없음·손상). 모든 용도가 ``NoKeyError``, kid 는 ``NO_KID``."""
    kid: str = NO_KID

    def sub(self, purpose: str) -> bytes:
        raise NoKeyError(purpose)


def kid_of(secret: bytes) -> str:
    """``"k" + sha256(secret)[:8]``(계약 §4.2)."""
    return "k" + hashlib.sha256(secret).hexdigest()[:8]


# ───────────────────────────── HMAC ─────────────────────────────
def keyed(kr, purpose: str, value: str, n: int = 16) -> str:
    """``HMAC-SHA256(용도 하위 키, value)`` 16진 앞 n자. purpose 는 ``PURPOSES`` 중 하나(아니면 ValueError).
    에이전트에 없는 용도면 ``NoKeyError``."""
    if purpose not in PURPOSES:
        raise ValueError("keyed: 알 수 없는 용도")
    if not isinstance(value, str):
        raise TypeError("keyed: value 는 str")
    return hmac.new(kr.sub(purpose), value.encode("utf-8"), hashlib.sha256).hexdigest()[:n]


def person_ident(addr=None, name=None) -> str | None:
    """사람 키 재료(계약 §4.2): 주소가 이메일 형식이면 ``smtp:<소문자>``, 아니면 표시명 ``name:<norm_person>``,
    둘 다 없으면 None."""
    a = str(addr or "").strip()
    if a and _EMAIL_RX.match(a):
        return "smtp:" + a.lower()
    n = norm_person(str(name or "")) if name else ""
    return ("name:" + n) if n else None


def who_key(kr, ident: str) -> str:
    """ident(``smtp:…`` 또는 ``name:…``) → ``"w" + 16hex``(purpose person)."""
    return "w" + keyed(kr, "person", ident, 16)


def msg_key(kr, material: str) -> str:
    """메일·팀즈 메시지 키 ``"m" + 24hex``(purpose msg)."""
    return "m" + keyed(kr, "msg", material, 24)


def cal_key(kr, material: str) -> str:
    """일정 키 ``"e" + 24hex``(purpose cal — 에이전트에는 없는 용도)."""
    return "e" + keyed(kr, "cal", material, 24)


def thread_key(kr, material: str) -> str:
    return "t" + keyed(kr, "thread", material, 16)


def chat_key(kr, material: str) -> str:
    return "h" + keyed(kr, "chat", material, 16)


def commit_key(kr, sha: str) -> str:
    return "g" + keyed(kr, "commit", str(sha or "").strip().lower(), 16)


# ───────────────────────────── 문서군·폴더·경로 정규화 ─────────────────────────────
DOC_COMPOUND_EXT = re.compile(r"\.(?:gz|zip|7z)$")                  # 압축 꼬리(앞의 확장자를 한 번 더 뗀다 — W §4.1)
DOC_CREO_EXT = re.compile(r"\.(?:prt|asm|drw)\.\d{1,4}$")           # Creo 판번호(하우징.prt.12)
DOC_EXT = re.compile(r"\.[0-9a-z]{1,5}$")                          # 일반 확장자 1개
DOC_TAIL = re.compile(
    r"(?:[\s_\-]+(?:복사본|사본|수정본?|copy|최종|final|v\d{1,3}(?:\.\d{1,3}){0,2}|rev\.?\s?\d{1,3}|r\d{1,3})"
    r"|\s?\(\d{1,3}\))$")                                           # 꼬리 하나(구분자 필수 — '(1)' 만 예외)
DOC_SEP = re.compile(r"[\s_\-.]+")
DOC_TAIL_MAX = 5
NAME_MAX = 255                                                       # 한 이름에서 보는 최대 글자(병적 입력 방어)
_SPLIT_PATH = re.compile(r"[\\/]")
_URL_RX = re.compile(r"(?i)^[a-z][a-z0-9+.\-]{1,15}://")
_DRIVE_RX = re.compile(r"^[A-Za-z]:$")
_USERS_RX = re.compile(r"^[a-z]:\\users\\[^\\]+(?=\\|$)")


def doc_fam(name) -> str:
    """문서군 정규화 이름(해시 전 — 계약 §4.3 · C16 · P §18.2 D01~D08). 빈 값이면 ""."""
    if not name:
        return ""
    s = unicodedata.normalize("NFKC", str(name))
    s = _SPLIT_PATH.split(s)[-1].lower().strip()[:NAME_MAX]
    if not s:
        return ""
    s = DOC_COMPOUND_EXT.sub("", s)
    t = DOC_CREO_EXT.sub("", s)
    s = (t if t != s else DOC_EXT.sub("", s)).strip()
    base = s
    for _ in range(DOC_TAIL_MAX):
        t = DOC_TAIL.sub("", s)
        if t == s:
            break
        s = t
    if not DOC_SEP.sub("", s):
        s = base                                                   # 꼬리를 다 지우면 빈 값 → 원래 이름(D06)
    return DOC_SEP.sub("_", s).strip("_")


def doc_key(kr, name) -> str:
    """``"d" + keyed(kr, "doc", "n:" + doc_fam(name), 16)`` — 창 제목 문서명·파일 이름·메일 첨부·팀즈 파일 모두 이
    함수 하나(문서 연결, P-T27)."""
    return "d" + keyed(kr, "doc", "n:" + doc_fam(name), 16)


def seg_norm(seg) -> str:
    """폴더 한 단계 이름 정규화(H §4.2 — ``lm27.hier.registry.seg_norm`` 과 같은 규칙): NFKC → casefold →
    공백·_·-·. 묶음을 ``_`` 로 → 앞뒤 ``_`` 제거."""
    t = unicodedata.normalize("NFKC", str(seg or "")).casefold()
    return DOC_SEP.sub("_", t).strip("_")


def dir_key(kr, seg) -> str:
    """폴더 한 단계 키 ``"s" + keyed(kr, "dir", "seg:" + seg_norm(seg), 16)``(계약 §4.2 dir_keys · H X3).
    수집기의 ``dir_keys`` 와 레지스트리 폴더 규칙(``folder_ix``)이 같은 함수를 쓴다(WP-21 요청)."""
    return "s" + keyed(kr, "dir", "seg:" + seg_norm(seg), 16)


def dir_segments(path, n: int = 3) -> list:
    """경로(또는 URL)의 상위 폴더 이름들 — 가까운 것부터 최대 n 개(기본 이름·드라이브 문자 제외). 메모리 전용."""
    p = unicodedata.normalize("NFKC", str(path or "")).strip()
    if not p:
        return []
    if _URL_RX.match(p):
        p = unquote(urlsplit(p).path or "")
    parts = [x for x in re.split(r"[\\/]+", p[:4096]) if x]
    parts = [x for x in parts[:-1] if not _DRIVE_RX.match(x)]
    return list(reversed(parts))[:n]


def dir_keys_of(kr, path, n: int = 3) -> list:
    """상위 폴더 1~n 단의 폴더 키(가까운 것부터). 정규화해 빈 이름은 건너뛴다."""
    return [dir_key(kr, s) for s in dir_segments(path, n) if seg_norm(s)]


def path_norm(path) -> str:
    """전체 경로 정규화(P §9.3 path_key 재료): NFKC·소문자·``/``→``\\``·사용자 폴더 → ``%userprofile%``.
    URL 이면 질의·조각을 떼고 소문자."""
    p = unicodedata.normalize("NFKC", str(path or "")).strip()[:4096]
    if _URL_RX.match(p):
        return p.split("#", 1)[0].split("?", 1)[0].lower()
    p = p.replace("/", "\\").lower()
    return _USERS_RX.sub("%userprofile%", p)


def path_key(kr, path) -> str:
    """``"f" + keyed(kr, "path", path_norm(path), 16)`` — 같은 이름 다른 폴더를 가른다(pc_file 전용)."""
    return "f" + keyed(kr, "path", path_norm(path), 16)


def base_name(path) -> str:
    """경로(또는 URL)의 기본 이름(마지막 조각, URL 은 퍼센트 해독). 메모리 전용."""
    p = unicodedata.normalize("NFKC", str(path or "")).strip()[:4096]
    if _URL_RX.match(p):
        p = unquote(urlsplit(p).path or "")
    parts = [x for x in re.split(r"[\\/]+", p) if x]
    return parts[-1] if parts else ""


def repo_key(kr, repo_root) -> str:
    """git 저장소 키 ``"r" + keyed(kr, "repo", "repo:" + 정규화 이름, 16)``(계약 §4.2 — 저장소 정규화 이름. 같은
    저장소를 다른 PC·다른 위치에 받아도 한 문서군 — X-216)."""
    return "r" + keyed(kr, "repo", "repo:" + seg_norm(base_name(repo_root)), 16)


# ───────────────────────────── 팀 pepper(P §9.7) ─────────────────────────────
_PEPPER_RX = re.compile(r"^[0-9a-f]{64}$")


def peer_key(pepper_hex, smtp, internal_domains, kr):
    """팀 묶음 빌더 전용(행·세그먼트에 저장하지 않는다). 사내 도메인 주소만 키를 만들고 외부 주소는 ``(None, "")``.
    pepper 가 있으면 ``("c_" + HMAC(pepper, 주소)[:12], "team")``, 없으면 주 키 ``("c_" + keyed(peer)[:12], "personal")``."""
    a = (smtp or "").strip().lower()
    dom = a.rsplit("@", 1)[-1] if "@" in a else ""
    doms = [str(d).strip().lower() for d in (internal_domains or ()) if str(d).strip()]
    if not dom or not any(dom == d or dom.endswith("." + d) for d in doms):
        return None, ""
    if pepper_hex and _PEPPER_RX.match(str(pepper_hex)):
        return "c_" + hmac.new(bytes.fromhex(pepper_hex), a.encode("utf-8"), hashlib.sha256).hexdigest()[:12], "team"
    return "c_" + keyed(kr, "peer", a, 12), "personal"


# ───────────────────────────── 키링 파일(P §9.2·§9.5) ─────────────────────────────
def _utcnow(now=None) -> str:
    if isinstance(now, str) and _UTC_RX.match(now):
        return now
    if isinstance(now, datetime):
        return (now if now.tzinfo else now.replace(tzinfo=UTC)).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _audit(audit, key: str) -> None:
    if audit is not None:
        audit.add("key", key)


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def _unb64(s) -> bytes | None:
    if not isinstance(s, str):
        return None
    try:
        b = base64.b64decode(s.encode("ascii"), validate=True)
    except (binascii.Error, ValueError, UnicodeEncodeError):
        return None
    return b if len(b) == SECRET_BYTES else None


def _parse_keyring(obj) -> dict | None:
    """키링 객체 → {kid: 항목}(형식이 틀리면 None — 내용·비밀값은 오류 문구에 싣지 않는다)."""
    if not isinstance(obj, dict) or obj.get("format") != KEYRING_FORMAT or not isinstance(obj.get("keys"), list):
        return None
    out = {}
    for it in obj["keys"]:
        if not isinstance(it, dict):
            return None
        sec = _unb64(it.get("secret_b64"))
        if sec is None or it.get("kid") != kid_of(sec):
            return None
        cu = it.get("created_utc")
        out[it["kid"]] = {"kid": it["kid"], "secret": sec, "created_utc": cu if isinstance(cu, str) else "",
                          "origin": it.get("origin") if isinstance(it.get("origin"), str) else "",
                          "state": "retired" if it.get("state") == "retired" else "active"}
    return out or None


def _read_keyring_file(path) -> tuple[str, dict | None]:
    """('missing'|'corrupt'|'ok', 항목들)."""
    try:
        raw = fsx.read_bytes(path)
    except FileNotFoundError:
        return "missing", None
    except OSError:
        return "corrupt", None
    try:
        obj = fsx.loads_strict(raw)
    except ValueError:
        return "corrupt", None
    entries = _parse_keyring(obj)
    return ("ok", entries) if entries else ("corrupt", None)


def _keyring_obj(entries: dict, primary: str) -> dict:
    keys = []
    for kid in sorted(entries, key=lambda k: (entries[k]["created_utc"], k)):
        e = entries[kid]
        it = {"kid": kid, "created_utc": e["created_utc"], "secret_b64": _b64(e["secret"]), "state": e["state"]}
        if e.get("origin"):
            it["origin"] = e["origin"]
        keys.append(it)
    return {"format": KEYRING_FORMAT, "keys": keys, "primary": primary}


def _choose_primary(entries: dict) -> tuple[str, bool]:
    """주 키 = created_utc 가 가장 이른 active 키(동률이면 kid 사전순). 나머지 active 는 retired 로. (kid, 바뀜)."""
    active = [k for k, e in entries.items() if e["state"] == "active"] or list(entries)
    prim = min(active, key=lambda k: (entries[k]["created_utc"] or "9999", k))
    changed = False
    for k, e in entries.items():
        want = "active" if k == prim else "retired"
        if e["state"] != want:
            e["state"] = want
            changed = True
    return prim, changed


def load_keyring(data_dir, audit=None, *, create: bool = False, merge_from=(), now=None, origin=None) -> Keyring:
    r"""``<ROOT>\data\keys\privacy_keyring.json`` 을 읽는다(P §9.5).

    1. 형식이 깨졌으면 그 파일을 ``<이름>.corrupt-<UTC>`` 로 옆에 옮기고(자기 파일만) 없는 것으로 본다 — ``key.corrupt``.
    2. 없으면 ``create=True`` 일 때 새 키를 만들어 원자 기록(``key.created``), 아니면 ``NoKeyringError``.
    3. ``merge_from`` = 다른 번들의 키링 파일 경로들 — kid 로 합집합. 합집합으로 키가 2개 이상이 되면 ``key.conflict``.
    4. 주 키 = 가장 이른 active 키(동률 kid 순), 나머지 active 는 retired 로 바꿔 다시 쓴다.
    5. 폴더가 읽기 전용이면 메모리 키링으로 진행하고 쓰기는 다음 기회로 — ``key.bundle_readonly``.
    ``data_dir`` = ``<ROOT>\data``(경로는 ``Paths(<ROOT>).keyring()`` 으로 만든다)."""
    paths = Paths(Path(os.fspath(data_dir)).parent)
    kp = paths.keyring()
    state, entries = _read_keyring_file(kp)
    dirty = False
    if state == "corrupt":
        _audit(audit, "corrupt")
        try:
            os.replace(fsx.longp(kp), fsx.longp(kp.with_name(kp.name + ".corrupt-" + _utcnow(now).replace(":", ""))))
        except OSError:
            _audit(audit, "bundle_readonly")
        entries = None
    entries = dict(entries or {})
    before = set(entries)
    added = False
    for other in merge_from or ():
        st, more = _read_keyring_file(other)
        if st != "ok":
            continue
        for kid, e in more.items():
            if kid not in entries:
                entries[kid] = e
                added = True
            elif e["created_utc"] and (not entries[kid]["created_utc"] or e["created_utc"] < entries[kid]["created_utc"]):
                entries[kid]["created_utc"] = e["created_utc"]
    if added:
        dirty = True
        if len(entries) >= 2 and before:
            _audit(audit, "conflict")
    if not entries:
        if not create:
            raise NoKeyringError("키링 없음")
        sec = secrets.token_bytes(SECRET_BYTES)
        kid = kid_of(sec)
        org = origin if isinstance(origin, str) and _PC_RX.match(origin) else ""
        entries[kid] = {"kid": kid, "secret": sec, "created_utc": _utcnow(now), "origin": org, "state": "active"}
        _audit(audit, "created")
        dirty = True
    prim, changed = _choose_primary(entries)
    if dirty or changed:
        try:
            fsx.atomic_write(kp, fsx.canon_bytes(_keyring_obj(entries, prim)) + b"\n")
        except OSError:
            _audit(audit, "bundle_readonly")
    return Keyring(primary_kid=prim, primary_secret=entries[prim]["secret"],
                   all={k: e["secret"] for k, e in sorted(entries.items())})


# ───────────────────────────── 에이전트 하위 키(P §9.4) ─────────────────────────────
def _agent_paths(agent_dir) -> Paths:
    r"""``agent_dir`` = ``%LOCALAPPDATA%\LoadMonitor27\agent`` → 그 부모를 LAD 로 쓰는 Paths."""
    return Paths(lad=Path(os.fspath(agent_dir)).parent)


def write_agent_subkeys(kr: Keyring, agent_dir, audit=None, *, now=None) -> str:
    """키링 주 키에서 ``AGENT_PURPOSES`` 하위 키만 파생해 ``agent\\keys\\subkeys.json`` 에 원자 기록한다. 반환 kid.
    기존 파일의 kid 가 다르면 교체하고 ``key.agent_rotated``. 같은 kid·같은 키면 다시 쓰지 않는다."""
    if not isinstance(kr, Keyring):
        raise TypeError("write_agent_subkeys: 주 키(Keyring)가 필요합니다")
    p = _agent_paths(agent_dir).agent_subkeys()
    want = {pp: _b64(kr.sub(pp)) for pp in AGENT_PURPOSES}
    old = fsx.read_json(p, default=None)
    if isinstance(old, dict) and old.get("format") == SUBKEYS_FORMAT and old.get("kid") == kr.kid \
            and old.get("purposes") == want:
        return kr.kid
    if isinstance(old, dict) and old.get("kid") not in (None, kr.kid):
        _audit(audit, "agent_rotated")
    obj = {"format": SUBKEYS_FORMAT, "kid": kr.kid, "purposes": want, "written_utc": _utcnow(now)}
    fsx.atomic_write(p, fsx.canon_bytes(obj) + b"\n")
    return kr.kid


def load_agent_keys(agent_dir, audit=None) -> AgentKeys | None:
    """``subkeys.json`` → ``AgentKeys``. 없거나 손상이면 None(키 없음 모드 — 파이프 종료 6, ``R-NOKEY``).
    손상이면 ``key.corrupt``. 알려진 용도 중 있는 것만 싣는다(없는 용도는 쓸 때 ``NoKeyError``)."""
    p = _agent_paths(agent_dir).agent_subkeys()
    try:
        raw = fsx.read_bytes(p)
    except FileNotFoundError:
        return None
    except OSError:
        _audit(audit, "corrupt")
        return None
    try:
        obj = fsx.loads_strict(raw)
    except ValueError:
        obj = None
    if not isinstance(obj, dict) or obj.get("format") != SUBKEYS_FORMAT or not isinstance(obj.get("purposes"), dict) \
            or not isinstance(obj.get("kid"), str) or not KID_RX.match(obj["kid"]):
        _audit(audit, "corrupt")
        return None
    subs = {}
    for pp, v in obj["purposes"].items():
        b = _unb64(v)
        if pp in AGENT_PURPOSES and b is not None:
            subs[pp] = b
    if not subs:
        _audit(audit, "corrupt")
        return None
    return AgentKeys(kid=obj["kid"], subkeys=subs)
