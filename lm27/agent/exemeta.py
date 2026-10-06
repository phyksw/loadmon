# -*- coding: utf-8 -*-
r"""미지 프로그램 메타(계약 §2.4 · §3.9 · CP §6.3 · X-024 · REQ-05) — ``store\<pc_id>\exe_meta.json``(``lm27.exemeta/1``).

카탈로그(``lm27.catalog``)에 없는 실행 파일을 처음 볼 때 한 번, 공개 메타데이터를 읽어 둔다:
  · 판 정보(``GetFileVersionInfoW``·``VerQueryValueW``): CompanyName · ProductName · FileDescription · ProductVersion
  · Authenticode 서명자(``CryptQueryObject`` → 서명자 인증서의 단순 표시 이름). 카탈로그 서명 파일 등은 빈 값.
추정(``catalog.guess_meta`` — 서명자 → 회사 → 제품·설명 순, 원문을 쓰는 판정은 메모리에서만)으로 ``guess_cat``(범주 9종)·
``guess_kind``(상용·비상용)·``source``(signer·company·product·desc·none)를 채운다. 저장하는 문자열(company·product·desc·signer)은
모두 **정제 통과값**(``lm27.privacy.sanitize`` — 사내 도구 이름·코드네임 가명화, CP §6.3)이고 판(ver)은 숫자·점만 둔다.
실행 파일 경로 원문은 저장하지 않는다(키 = 실행 파일 이름 ``catalog.exe_name`` 표기). 쓰기는 ``fsx.atomic_write`` 하나.

이 모듈은 에이전트 bin 사본에 들어간다(표준 라이브러리 + 사본 안 ``lm27.catalog``·``lm27.privacy``·``lm27.util``).
실기계 조회는 ``WinVersion`` 에 모았고 시험은 같은 메서드(``version_info``·``signer``)를 가진 가짜를 넣는다.
"""
from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from lm27 import catalog
from lm27.privacy.detect import SanitizeContext, sanitize
from lm27.util import fsx

__all__ = ["EXEMETA_SCHEMA", "ExeMeta", "WinVersion", "load_exe_meta", "observe_exe", "save_exe_meta"]

EXEMETA_SCHEMA = "lm27.exemeta/1"
TEXT_MAX = {"company": 80, "product": 80, "desc": 120, "signer": 80}
MAX_ENTRIES = 2000                       # 파일이 무한히 커지지 않게(가장 오래된 first_seen 부터 버림)
_VER_RX = re.compile(r"^\d{1,6}(?:[.,]\d{1,6}){0,3}$")
_UTC_RX = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_CTRL = re.compile("[\x00-\x1f\x7f]")
_SOURCES = ("signer", "company", "product", "desc", "none")


@dataclass(frozen=True)
class ExeMeta:
    """실행 파일 하나의 메타(정제 통과값). ``as_entry()`` 가 exe_meta.json 의 값 모양."""
    exe: str
    company: str = ""
    product: str = ""
    desc: str = ""
    ver: str = ""
    signer: str = ""
    first_seen: str = ""
    guess_cat: str = ""
    guess_kind: str = ""
    source: str = "none"

    def as_entry(self) -> dict:
        d = asdict(self)
        d.pop("exe")
        return d


# ───────────────────────────── 실기계 조회(ctypes) ─────────────────────────────
class WinVersion:
    """version.dll · crypt32.dll 조회. 실패하면 빈 값(예외를 올리지 않는다)."""

    _FIELDS = (("company", "CompanyName"), ("product", "ProductName"), ("desc", "FileDescription"),
               ("ver", "ProductVersion"))

    def __init__(self):
        import ctypes
        from ctypes import wintypes
        self.ct, self.wt = ctypes, wintypes
        v = ctypes.WinDLL("version", use_last_error=True)
        v.GetFileVersionInfoSizeW.restype = wintypes.DWORD
        v.GetFileVersionInfoSizeW.argtypes = (wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD))
        v.GetFileVersionInfoW.restype = wintypes.BOOL
        v.GetFileVersionInfoW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p)
        v.VerQueryValueW.restype = wintypes.BOOL
        v.VerQueryValueW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p),
                                     ctypes.POINTER(wintypes.UINT))
        self.v = v
        self.c = None

    def version_info(self, path: str) -> dict:
        ct, wt = self.ct, self.wt
        out = {}
        n = self.v.GetFileVersionInfoSizeW(path, None)
        if not n or n > 4 * 1024 * 1024:
            return out
        buf = ct.create_string_buffer(n)
        if not self.v.GetFileVersionInfoW(path, 0, n, buf):
            return out
        langs = []
        p, ln = ct.c_void_p(), wt.UINT(0)
        if self.v.VerQueryValueW(buf, "\\VarFileInfo\\Translation", ct.byref(p), ct.byref(ln)) and p.value and ln.value >= 4:
            arr = ct.cast(p, ct.POINTER(wt.WORD * (ln.value // 2))).contents
            langs = [f"{arr[i]:04x}{arr[i + 1]:04x}" for i in range(0, len(arr) - 1, 2)]
        for lang in langs + ["040904b0", "040904e4", "041204b0", "000004b0"]:
            for key, name in self._FIELDS:
                if key in out:
                    continue
                q, ql = ct.c_void_p(), wt.UINT(0)
                if self.v.VerQueryValueW(buf, f"\\StringFileInfo\\{lang}\\{name}", ct.byref(q), ct.byref(ql)) \
                        and q.value and ql.value:
                    s = ct.wstring_at(q.value, max(0, ql.value - 1)).strip("\x00 ")
                    if s:
                        out[key] = s
            if len(out) == len(self._FIELDS):
                break
        return out

    def _crypt(self):
        if self.c is None:
            ct, wt = self.ct, self.wt
            c = ct.WinDLL("crypt32", use_last_error=True)

            class _BLOB(ct.Structure):
                _fields_ = [("cbData", wt.DWORD), ("pbData", ct.c_void_p)]

            class _ALG(ct.Structure):
                _fields_ = [("pszObjId", ct.c_char_p), ("Parameters", _BLOB)]

            class _BIT(ct.Structure):
                _fields_ = [("cbData", wt.DWORD), ("pbData", ct.c_void_p), ("cUnusedBits", wt.DWORD)]

            class _PKI(ct.Structure):
                _fields_ = [("Algorithm", _ALG), ("PublicKey", _BIT)]

            class _SIGNER(ct.Structure):
                _fields_ = [("dwVersion", wt.DWORD), ("Issuer", _BLOB), ("SerialNumber", _BLOB),
                            ("HashAlgorithm", _ALG), ("HashEncryptionAlgorithm", _ALG), ("EncryptedHash", _BLOB),
                            ("AuthAttrs", _BLOB), ("UnauthAttrs", _BLOB)]

            class _CERTINFO(ct.Structure):
                _fields_ = [("dwVersion", wt.DWORD), ("SerialNumber", _BLOB), ("SignatureAlgorithm", _ALG),
                            ("Issuer", _BLOB), ("NotBefore", wt.FILETIME), ("NotAfter", wt.FILETIME),
                            ("Subject", _BLOB), ("SubjectPublicKeyInfo", _PKI), ("IssuerUniqueId", _BIT),
                            ("SubjectUniqueId", _BIT), ("cExtension", wt.DWORD), ("rgExtension", ct.c_void_p)]

            c.CryptQueryObject.restype = wt.BOOL
            c.CryptQueryObject.argtypes = (wt.DWORD, ct.c_void_p, wt.DWORD, wt.DWORD, wt.DWORD,
                                           ct.POINTER(wt.DWORD), ct.POINTER(wt.DWORD), ct.POINTER(wt.DWORD),
                                           ct.POINTER(ct.c_void_p), ct.POINTER(ct.c_void_p), ct.c_void_p)
            c.CryptMsgGetParam.restype = wt.BOOL
            c.CryptMsgGetParam.argtypes = (ct.c_void_p, wt.DWORD, wt.DWORD, ct.c_void_p, ct.POINTER(wt.DWORD))
            c.CertFindCertificateInStore.restype = ct.c_void_p
            c.CertFindCertificateInStore.argtypes = (ct.c_void_p, wt.DWORD, wt.DWORD, wt.DWORD, ct.c_void_p,
                                                     ct.c_void_p)
            c.CertGetNameStringW.restype = wt.DWORD
            c.CertGetNameStringW.argtypes = (ct.c_void_p, wt.DWORD, wt.DWORD, ct.c_void_p, wt.LPWSTR, wt.DWORD)
            c.CertFreeCertificateContext.restype = wt.BOOL
            c.CertFreeCertificateContext.argtypes = (ct.c_void_p,)
            c.CertCloseStore.restype = wt.BOOL
            c.CertCloseStore.argtypes = (ct.c_void_p, wt.DWORD)
            c.CryptMsgClose.restype = wt.BOOL
            c.CryptMsgClose.argtypes = (ct.c_void_p,)
            self.c = (c, _SIGNER, _CERTINFO)
        return self.c

    def signer(self, path: str) -> str:
        """내장 Authenticode 서명의 서명자 표시 이름(없으면 "")."""
        ct, wt = self.ct, self.wt
        c, _SIGNER, _CERTINFO = self._crypt()
        enc, ctype, fmt = wt.DWORD(), wt.DWORD(), wt.DWORD()
        store, msg = ct.c_void_p(), ct.c_void_p()
        wpath = ct.create_unicode_buffer(path)
        if not c.CryptQueryObject(1, ct.cast(wpath, ct.c_void_p), 0x400, 0x2, 0, ct.byref(enc), ct.byref(ctype),
                                  ct.byref(fmt), ct.byref(store), ct.byref(msg), None):
            return ""
        cert = None
        try:
            size = wt.DWORD(0)
            if not c.CryptMsgGetParam(msg, 6, 0, None, ct.byref(size)) or not size.value:   # CMSG_SIGNER_INFO_PARAM
                return ""
            sbuf = ct.create_string_buffer(size.value)
            if not c.CryptMsgGetParam(msg, 6, 0, sbuf, ct.byref(size)):
                return ""
            si = ct.cast(sbuf, ct.POINTER(_SIGNER)).contents
            info = _CERTINFO()
            info.Issuer = si.Issuer
            info.SerialNumber = si.SerialNumber
            cert = c.CertFindCertificateInStore(store, 0x00010001, 0, 0xB0000, ct.byref(info), None)
            if not cert:
                return ""
            name = ct.create_unicode_buffer(256)
            n = c.CertGetNameStringW(cert, 4, 0, None, name, 256)                         # SIMPLE_DISPLAY
            return name.value.strip() if n > 1 else ""
        finally:
            if cert:
                c.CertFreeCertificateContext(cert)
            if store.value:
                c.CertCloseStore(store, 0)
            if msg.value:
                c.CryptMsgClose(msg)


_READER: list = []


def _default_reader():
    if not _READER:
        _READER.append(WinVersion())
    return _READER[0]


# ───────────────────────────── 관찰·저장 ─────────────────────────────
def _clean(s, key: str, sctx) -> str:
    """정제 통과값(자격 증명이면 빈 값) — 제어문자 제거·길이 상한."""
    t = _CTRL.sub(" ", str(s or "")).strip()
    if not t:
        return ""
    r = sanitize(t, "text", sctx, TEXT_MAX[key])
    return "" if r.drop else r.text.strip()


def _ver(s) -> str:
    t = str(s or "").strip().replace(",", ".").replace(" ", "")
    return t if _VER_RX.match(t) else ""


def _utc(now=None) -> str:
    n = now or datetime.now(UTC)
    return n.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def observe_exe(exe_path, *, reader=None, sctx: SanitizeContext | None = None, now=None) -> ExeMeta:
    """실행 파일 경로(메모리) → ``ExeMeta``(정제 통과값). ``sctx`` = 에이전트 정제 문맥(사내 도구 이름 가명화 — 없으면 기본
    규칙만). ``reader`` = 시험 주입(``version_info(path) -> dict``·``signer(path) -> str``)."""
    path = os.fspath(exe_path)
    rd = reader or _default_reader()
    exe = catalog.exe_name(os.path.basename(path))
    try:
        vi = rd.version_info(path) or {}
    except (OSError, ValueError, AttributeError):
        vi = {}
    try:
        sg = rd.signer(path) or ""
    except (OSError, ValueError, AttributeError):
        sg = ""
    g = catalog.guess_meta(vi.get("company", ""), vi.get("product", ""), vi.get("desc", ""), sg)   # 원문 판정은 메모리에서만
    ctx = sctx if sctx is not None else SanitizeContext()
    src = g.get("source") if g.get("source") in _SOURCES else "none"
    return ExeMeta(exe=exe, company=_clean(vi.get("company"), "company", ctx), product=_clean(vi.get("product"), "product", ctx),
                   desc=_clean(vi.get("desc"), "desc", ctx), ver=_ver(vi.get("ver")), signer=_clean(sg, "signer", ctx),
                   first_seen=_utc(now), guess_cat=catalog.norm_cat(g.get("guess_cat")),
                   guess_kind=g.get("guess_kind") if g.get("guess_kind") in catalog.KINDS else "", source=src)


def load_exe_meta(paths, pc_id: str) -> dict:
    """``exe_meta.json`` 의 항목 사전 ``{<exe>: {...}}``(없거나 깨졌으면 빈 사전). 최상위 ``schema`` 칸은 뺀다."""
    obj = fsx.read_json(paths.exe_meta(pc_id), default={})
    if not isinstance(obj, dict):
        return {}
    return {k: v for k, v in obj.items() if isinstance(k, str) and k.endswith(".exe") and isinstance(v, dict)}


def _valid_entry(e) -> bool:
    if not isinstance(e, dict):
        return False
    for k in ("company", "product", "desc", "ver", "signer", "guess_cat", "guess_kind", "source", "first_seen"):
        if not isinstance(e.get(k, ""), str) or _CTRL.search(e.get(k, "")):
            return False
    return not e.get("first_seen") or bool(_UTC_RX.match(e["first_seen"]))


def save_exe_meta(paths, pc_id: str, meta: ExeMeta) -> bool:
    """항목 하나를 더하거나 고친다(first_seen 은 처음 값 유지). 정제 통과값만 원자 쓰기. 바뀌었으면 True."""
    if not isinstance(meta, ExeMeta) or not meta.exe:
        raise TypeError("save_exe_meta: ExeMeta 가 필요합니다")
    items = {k: v for k, v in load_exe_meta(paths, pc_id).items() if isinstance(k, str) and _valid_entry(v)}
    new = meta.as_entry()
    old = items.get(meta.exe)
    if isinstance(old, dict) and old.get("first_seen"):
        new["first_seen"] = old["first_seen"]
    if old == new:
        return False
    items[meta.exe] = new
    if len(items) > MAX_ENTRIES:
        keep = sorted(items, key=lambda k: (items[k].get("first_seen") or "", k))[-MAX_ENTRIES:]
        items = {k: items[k] for k in keep}
    obj = {"schema": EXEMETA_SCHEMA, **dict(sorted(items.items()))}       # 계약 §3.9 형 {<exe>: {...}} + 판 이름
    fsx.atomic_write(paths.exe_meta(pc_id), fsx.canon_bytes(obj) + b"\n")
    return True
