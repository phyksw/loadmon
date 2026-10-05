# -*- coding: utf-8 -*-
r"""토큰·문서군 키 — 시간 코어(W §4.1 · 부록 A `tokens.py`, 계약 §2.9 · §4.3).

- 문서군 정규화는 **한 함수**다: `fam = lm27.privacy.keys.doc_fam`(재수출, 계약 §4.3 · X-043). 정제기·수집기·
  메일 첨부·창 제목이 같은 함수를 쓰므로, 시간 코어는 그 결과를 해시(`doc_key = "d" + HMAC(...)`)로만 받는다.
  `fam()` 은 첫 호출 때 `lm27.privacy.keys` 를 지연 import 한다(privacy 패키지 적재 비용·순환 회피 — 계약 §3.1 CR-09).
- 범용 이름(보고서.pptx·새 Microsoft Excel 워크시트 …)은 시간 코어가 상위 폴더 키로 가른다:
  `fam_key(doc_key, name_masked, dir_keys, cfg)` = 범용이 아니면 `doc_key`, 범용이면 `doc_key@dir0+dir1`,
  범용인데 폴더 키가 없으면 `B_GENERIC`(계약 §4.3). git 저장소 키(`r…`)는 그대로 문서군 키다(X-216).
- 토큰은 정제문에서 파생된 `subject_tokens`(P §6.2 `tokens_of`)를 다시 다듬는다(`raw_tokens`): 소문자·NFKC,
  구분자 분리, 길이 ≥ 2, 상용구(`episode.tokens.boilerplate`)·버전·숫자 제거. 정제 토큰 중 개체 ID 를 가진 것
  (`[과제:P-0001]` `[고객사:C01]` `[사람#a1b2c3]`)은 한 덩어리로 남기고, 범주 자리표시(`[전화]` `[사람]` …)는 버린다.
- `tok_sim` 은 부분 문자열(길이 ≥ min_sub_len)을 일치로 보는 Dice 유사도(한국어 합성어 — W §4.1, must_fix).

표준 라이브러리만 쓴다(+ 지연 import 한 `lm27.privacy.keys`). 파일을 쓰지 않는다.
"""
from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

__all__ = [
    "B_GENERIC",
    "GENERIC_RE",
    "boilerplate",
    "fam",
    "fam_key",
    "generic_stems",
    "is_generic",
    "is_generic_key",
    "min_sub_len",
    "raw_tokens",
    "tok_sim",
]

B_GENERIC = "B_GENERIC"
SPLIT_RE = re.compile(r"[_\-\s\.,/()\[\]+&~]+")
VER_RE = re.compile(r"^(v\d+(\.\d+)?|rev\d+|r\d+|\d+)$")
GENERIC_RE = re.compile(r"^(book|문서|통합 문서|presentation|프레젠테이션|image|untitled|document|새 문서)\s*\d*$")
BRACKET_RE = re.compile(r"\[[^\[\]]{1,40}\]")
_ENTITY_MARKS = (":", "#")             # 개체 ID 를 가진 정제 토큰만 낱말로 남긴다

_DOC_FAM = None


def _doc_fam():
    global _DOC_FAM
    if _DOC_FAM is None:
        from lm27.privacy.keys import doc_fam    # 지연 import — 문서군 정규화 단일원(계약 §4.3)
        _DOC_FAM = doc_fam
    return _DOC_FAM


def fam(name: str) -> str:
    """문서군 정규화(해시 전 이름) — `lm27.privacy.keys.doc_fam` 재수출(계약 §2.9 · §4.3)."""
    if not name:
        return ""
    return _doc_fam()(name)


def _norm(s: str) -> str:
    return unicodedata.normalize("NFKC", str(s)).lower().strip()


def generic_stems(cfg) -> frozenset[str]:
    """범용 이름 줄기(`episode.docs.genericStems`, NFKC·소문자)."""
    return frozenset(_norm(x) for x in cfg["episode.docs.genericStems"] if str(x).strip())


def boilerplate(cfg) -> frozenset[str]:
    """연결 비교에서 뺄 상용구(`episode.tokens.boilerplate`, NFKC·소문자)."""
    return frozenset(_norm(x) for x in cfg["episode.tokens.boilerplate"] if str(x).strip())


def min_sub_len(cfg) -> int:
    """부분 문자열 일치 최소 길이(`episode.tokens.minSubLen`)."""
    return int(cfg["episode.tokens.minSubLen"])


def _is_generic_fam(f: str, stems: frozenset[str]) -> bool:
    return f in stems or bool(GENERIC_RE.match(f))


def is_generic(name_masked: str | None, cfg, *, stems: frozenset[str] | None = None) -> bool:
    """정제된 문서 이름이 범용 이름인가(W §4.1). 이름을 모르면(빈 값) 범용으로 보지 않는다 — 키만으로 가른다."""
    if not name_masked:
        return False
    f = fam(name_masked)
    if not f:
        return False
    return _is_generic_fam(f, generic_stems(cfg) if stems is None else stems)


def fam_key(doc_key: str | None, name_masked: str | None, dir_keys: Iterable[str] | None, cfg, *,
            stems: frozenset[str] | None = None) -> str:
    """시간 코어 문서군 키(계약 §4.3). doc_key 가 없으면 빈 문자열."""
    if not doc_key:
        return ""
    if doc_key.startswith("r"):          # git 저장소 키 r16 — 그대로(X-216)
        return doc_key
    if not is_generic(name_masked, cfg, stems=stems):
        return doc_key
    dk = [d for d in (dir_keys or ()) if d][:2]
    if not dk:
        return B_GENERIC
    return doc_key + "@" + "+".join(dk)


def is_generic_key(f: str | None) -> bool:
    """문서군 키가 범용 이름의 것인가(빈 키·`B_GENERIC`·폴더로 가른 키)."""
    return (not f) or f == B_GENERIC or "@" in f


def _keep_bracket(tok: str) -> bool:
    return any(m in tok for m in _ENTITY_MARKS)


def raw_tokens(parts: Iterable[str], boiler: Iterable[str] = ()) -> set[str]:
    """정제문 조각들 → 연결 비교용 토큰 집합(W §4.1 `raw_tokens`)."""
    bl = boiler if isinstance(boiler, (set, frozenset)) else frozenset(boiler)
    out: set[str] = set()
    for p in parts:
        if p is None:
            continue
        x = _norm(p)
        if "[" in x:
            for m in BRACKET_RE.finditer(x):
                tok = m.group(0)
                if _keep_bracket(tok):
                    out.add(tok)
            x = BRACKET_RE.sub(" ", x)
        for w in SPLIT_RE.split(x):
            if len(w) < 2 or w in bl or VER_RE.match(w):
                continue
            out.add(w)
    return out


def tok_sim(a: Iterable[str], b: Iterable[str], min_sub_len: int = 2) -> float:
    """부분 문자열 일치를 인정하는 Dice 유사도: (A 에서 맞은 수 + B 에서 맞은 수) / (|A| + |B|)."""
    A = a if isinstance(a, (set, frozenset)) else set(a)
    B = b if isinstance(b, (set, frozenset)) else set(b)
    if not A or not B:
        return 0.0
    ml = min_sub_len

    def hit(x: str, Y) -> bool:
        if x in Y:
            return True
        for y in Y:
            if (len(x) >= ml and x in y) or (len(y) >= ml and y in x):
                return True
        return False

    ma = sum(1 for x in A if hit(x, B))
    mb = sum(1 for y in B if hit(y, A))
    return (ma + mb) / (len(A) + len(B))
