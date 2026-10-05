# -*- coding: utf-8 -*-
r"""치환 없는 탐지 ``scan()`` 과 토큰 파생 ``tokens_of()``(P §6.2 — H3·H9).

  · ``scan(text, ctx)`` — 남아 있는 PII·금액·이메일·경로 등을 범주별 건수(``Hit``)로만. 값·위치는 돌려주지 않는다(I8)
    → 결과를 로그·감사에 그대로 남겨도 된다. 이미 정제된 문자열이면(토큰은 보호 구간) 빈 목록. 업로드 전 검사·감사
    화면 '정제 시험대'·코파일럿 최종 프롬프트 검사(P §13.3)가 공용으로 쓴다.
  · ``tokens_of(masked)`` — 정제문 → 토큰 목록(``subject_tokens`` 의 정의, 계약 §3.1·X-060). 저장하지 않고 적재 때마다
    다시 만든다(결정적).

LM27 보강: ``sanitize()`` 는 한 필드의 앞 ``MAX_SCAN``(4,000)자만 본다(P §4 단계 0). 최종 프롬프트(입력 기본 8,000자 —
D-10)처럼 그보다 긴 글을 ``scan()`` 에 넘기면 뒤쪽이 검사되지 않으므로, 긴 글은 줄 경계에서 4,000자 이하 조각으로 나눠
조각마다 탐지하고 건수를 더한다. 한 줄이 4,000자를 넘으면 그 줄은 겹침(``SEAM``)을 두고 잘라 이어지는 값도 잡는다 —
겹친 구간의 값은 두 번 셀 수 있다(건수는 참고, 게이트 판정은 '빈 목록인가'). 4,000자 이하 입력의 결과는 P §6.2 와 같다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .detect import MAX_SCAN, SanitizeContext, sanitize

SEAM = 200                  # 4,000자를 넘는 한 줄을 자를 때 겹치는 글자 수(값 하나보다 충분히 김)


@dataclass(frozen=True)
class Hit:
    """탐지 범주 하나 — ``cat`` P §15.3 범주 코드, ``n`` 건수. 원문 조각은 없다."""
    cat: str
    n: int


def _chunks(text: str):
    """긴 글을 줄 경계에서 MAX_SCAN 이하 조각으로. 한 줄이 MAX_SCAN 을 넘으면 SEAM 만큼 겹쳐 자른다."""
    buf, size = [], 0
    for line in text.splitlines(keepends=True):
        if len(line) > MAX_SCAN:
            if buf:
                yield "".join(buf)
                buf, size = [], 0
            step = MAX_SCAN - SEAM
            for i in range(0, len(line), step):
                yield line[i:i + MAX_SCAN]
                if i + MAX_SCAN >= len(line):
                    break
            continue
        if size + len(line) > MAX_SCAN and buf:
            yield "".join(buf)
            buf, size = [], 0
        buf.append(line)
        size += len(line)
    if buf:
        yield "".join(buf)


def scan(text: str, ctx: SanitizeContext | None = None) -> list:
    """치환 없이 탐지만: 남아 있는 PII·금액·이메일·경로 등을 범주별 건수로(범주 이름순). 값·위치는 돌려주지 않는다(I8).
    이미 정제된 문자열이면(토큰은 보호 구간) 빈 목록. 자격증명이 있으면 ``[Hit("cred", 1)]`` 하나."""
    if not text:
        return []
    parts = [text] if len(text) <= MAX_SCAN else list(_chunks(text))
    hits: dict = {}
    for part in parts:
        r = sanitize(part, "scan", ctx)
        if r.drop:
            return [Hit("cred", 1)]
        for k, v in r.hits.items():
            hits[k] = hits.get(k, 0) + v
    return [Hit(k, v) for k, v in sorted(hits.items())]


TOKEN_SPLIT = re.compile(r"\[[^\[\]]{1,40}\]|[0-9A-Za-z가-힣][0-9A-Za-z가-힣._\-]*")


def tokens_of(masked: str, max_tokens: int = 30) -> list:
    """정제문 → 토큰 목록(수집 공통 명세 §3.1 subject_tokens 의 정의). [전화] 같은 토큰은 한 덩어리로 유지,
    일반 낱말은 24자에서 자른다. 저장하지 않고 적재 때마다 다시 만든다(결정적)."""
    out = []
    for m in TOKEN_SPLIT.finditer(masked or ""):
        w = m.group(0)
        if len(w) > 24 and not w.startswith("["):
            w = w[:24]
        out.append(w)
        if len(out) >= max_tokens:
            break
    return out
