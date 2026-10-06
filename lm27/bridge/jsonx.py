# -*- coding: utf-8 -*-
r"""L2 답 해석(B §6.4) — 답 정규화 · rid 봉투 후보 추출 · 잘린 JSON 복구.

    x = extract(reply, rid)        # Extracted(kind=env|echo|stale|none, obj, how=strict|salvaged|"", cut, pledge)
    found = all_envelopes(text)    # 수동 반입(B §10.4): 붙여넣은 글 안의 봉투 전부(완전·잘린 것), 뒤에서부터

정규화(``normalize``, LM24 ``core/details._normalize_reply`` 일반화): ① 꼬리 400자 안의 '생성 중단' 문구(``STOP_MARKS``)
위치에서 자르고 cut=True ② 코드펜스 제거 ③ 굽은 따옴표 → ``"`` ④ 모든 서약 ``[[END R…]]``·``<<END R…>>`` → 줄바꿈.

잘린 봉투 복구(``close_truncated``, LM24 ``judge._close_truncated`` 일반화): 문자열·이스케이프 상태를 추적하며 최상위
객체를 훑고 ``items`` 목록(깊이 2)의 **마지막 완전한 원소** 뒤에서 ``]}`` 로 닫는다. 원소가 하나도 완전하지 않으면
``"items": [`` 직후에서 닫아 rid·n 만이라도 얻는다. 괄호 개수 근사(LM24 ``_looks_closed``)는 쓰지 않는다 — 문자열 안의
``}`` 에 속는다(조사 probe2).

원문은 메모리에서만 다룬다(디스크에 쓰지 않는다 — B9).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

RID_PAT = r"R[2-9A-HJ-NP-TV-Z]{5}"
RID_RX = re.compile(r"^" + RID_PAT + r"$")
ANY_PLEDGE_RX = re.compile(r"(?:\[\[|<<)\s*END\s+" + RID_PAT + r"\s*(?:\]\]|>>)")
ENV_START_RX = re.compile(r'\{\s*"rid"\s*:')
# '생성 중단' 문구(LM24 core/details.STOP_MARKS + tools/copilot_auto.CUT_REPLY_MARKS 한 벌, 비교는 소문자)
STOP_MARKS = ("i've stopped generating", "stopped generating the response", "stopped generating",
              "stopped the response", "응답 생성을 중지", "응답 생성을 중단", "생성을 중지했", "생성이 중지되",
              "생성을 중단했", "생성을 멈췄", "응답을 중단했")
STOP_TAIL = 400                  # 중단 문구는 꼬리 400자 안에서만 본다(B §6.4 ①)
MAX_TRIES = 600                  # 뒤에서 '{' 를 거슬러 raw_decode 하는 최대 시도(LM24 rfind_json)
EXAMPLE_MARKS = ("<요청번호>", "<번호>", "<항목 수>")
_FENCE_RX = re.compile(r"```[A-Za-z0-9_-]*[ \t]*\r?\n?")
_SMART = {"“": '"', "”": '"', "„": '"', "‟": '"', "＂": '"'}
_DEC = json.JSONDecoder()


def pledge_rx(rid: str) -> re.Pattern:
    """이번 rid 의 서약(``[[END rid]]`` · ``<<END rid>>``)."""
    return re.compile(r"(?:\[\[|<<)\s*END\s+" + re.escape(rid) + r"\s*(?:\]\]|>>)")


def normalize(reply) -> tuple[str, bool]:
    """(정규화한 글, 생성 중단 문구로 잘렸는가)."""
    t = str(reply or "")
    low = t.lower()
    pos = max((low.rfind(m) for m in STOP_MARKS), default=-1)
    cut = pos >= 0 and pos >= len(t) - STOP_TAIL
    if cut:
        t = t[:pos]
    t = _FENCE_RX.sub("\n", t)
    t = "".join(_SMART.get(c, c) for c in t)
    t = ANY_PLEDGE_RX.sub("\n", t)
    return t, cut


@dataclass
class Found:
    """봉투 후보 하나. ``start``·``end`` 는 정규화한 글 안 위치."""
    obj: dict
    how: str                     # strict | salvaged
    start: int
    end: int

    @property
    def rid(self) -> str:
        return str(self.obj.get("rid", "")).strip().upper()


def find_envelopes(text: str, max_tries: int = MAX_TRIES) -> list[Found]:
    """뒤에서부터 '{' 를 거슬러 raw_decode — ``rid`` 키를 가진 완전한 객체만(가장 뒤의 것이 먼저)."""
    out: list[Found] = []
    i = text.rfind("{")
    tries = 0
    while i != -1 and tries < max_tries:
        try:
            o, end = _DEC.raw_decode(text, i)
            if isinstance(o, dict) and "rid" in o:
                out.append(Found(o, "strict", i, end))
        except ValueError:
            pass
        tries += 1
        i = text.rfind("{", 0, i)
    return out


def close_truncated(text: str, i: int, list_key: str = "items"):
    """``text[i:]`` 의 최상위 객체를 닫아 해석 → (dict 또는 None, how, 끝 위치). 객체가 온전히 닫히면 how=strict."""
    stack: list[str] = []
    in_str = esc = False
    last_good = -1
    j, n = i, len(text)
    while j < n:
        c = text[j]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c in "{[":
            stack.append(c)
        elif c in "}]":
            if not stack:
                break
            stack.pop()
            if not stack:
                try:
                    o = json.loads(text[i:j + 1])
                except ValueError:
                    return None, "", j + 1
                return (o, "strict", j + 1) if isinstance(o, dict) else (None, "", j + 1)
            if len(stack) == 2 and stack[0] == "{" and stack[1] == "[":
                last_good = j + 1
        j += 1
    if last_good > 0:
        raw = text[i:last_good] + "]}"
        end = last_good
    else:
        k = text.find('"' + list_key + '"', i)
        if k < 0:
            return None, "", n
        b = text.find("[", k)
        if b < 0:
            return None, "", n
        raw = text[i:b + 1] + "]}"
        end = b + 1
    try:
        o = json.loads(raw)
    except ValueError:
        return None, "", end
    return (o, "salvaged", end) if isinstance(o, dict) else (None, "", end)


@dataclass
class Extracted:
    kind: str                    # env | echo | stale | none
    obj: dict | None
    how: str                     # strict | salvaged | ""
    cut: bool
    pledge: bool


def extract(reply, rid: str) -> Extracted:
    """답에서 이번 rid 의 봉투를 꺼낸다(B §6.4). 다른 rid 의 완전한 봉투만 있으면 stale, 예시 골격이면 echo."""
    raw = str(reply or "")
    pledge = bool(pledge_rx(rid).search(raw))
    t, cut = normalize(raw)
    cands = find_envelopes(t)
    mine = [c for c in cands if c.rid == rid]
    if mine:
        return Extracted("env", mine[0].obj, "strict", cut, pledge)
    for m in reversed(list(ENV_START_RX.finditer(t))):
        o, how, _end = close_truncated(t, m.start())
        if o is not None and str(o.get("rid", "")).strip().upper() == rid:
            return Extracted("env", o, how, cut, pledge)
    if cands:
        r0 = cands[0].rid
        return Extracted("stale" if RID_RX.match(r0) else "echo", cands[0].obj, "strict", cut, pledge)
    if any(m in t for m in EXAMPLE_MARKS):
        return Extracted("echo", None, "", cut, pledge)
    return Extracted("none", None, "", cut, pledge)


@dataclass
class Envelope:
    """수동 반입 봉투 하나 — ``segment`` = 그 봉투만 담은 글(분류 함수에 그대로 넘긴다)."""
    rid: str
    obj: dict
    how: str
    segment: str


def all_envelopes(text) -> list[Envelope]:
    """붙여넣은 글 안의 rid 봉투 전부(완전·잘린 것), 뒤에서부터. 같은 rid 가 여럿이면 가장 뒤의 것 하나."""
    t, _cut = normalize(text)
    found: list[Found] = []
    taken: list[tuple[int, int]] = []
    for f in find_envelopes(t):
        if RID_RX.match(f.rid):
            found.append(f)
            taken.append((f.start, f.end))
    for m in ENV_START_RX.finditer(t):
        s = m.start()
        if any(a <= s < b for a, b in taken):
            continue
        o, how, end = close_truncated(t, s)
        if o is None:
            continue
        f = Found(o, how, s, end)
        if RID_RX.match(f.rid):
            found.append(f)
            taken.append((s, end))
    found.sort(key=lambda f: f.start, reverse=True)
    out: list[Envelope] = []
    seen: set[str] = set()
    for f in found:
        if f.rid in seen:
            continue
        seen.add(f.rid)
        out.append(Envelope(f.rid, f.obj, f.how, t[f.start:f.end]))     # 잘린 봉투는 잘린 그대로(분류가 truncated 로 본다)
    return out
