# -*- coding: utf-8 -*-
"""이름 비교 축 단일원(H §9.2 · §2.3.3, 계약 §2.10 · §3.19 · X-233).

과제 이름·별칭·코드네임·키워드·제안 이름·단위업무 이름의 비교는 모두 이 모듈 하나로 한다.
LM24 의 `ukey2`·`ukey3`·`team_report.ukey` 세 벌을 한 벌로 통일했다. 팀 서버의 별칭 중복 검사도
이 모듈의 `ukey` 를 import 한다(사본 금지 — X-233).

- `fold(s, drop_note=True)`: 구분자(`·・ㆍ‧_-/–—－／`)를 공백으로 → NFKC → 다시 구분자 치환 →
  (drop_note 면 끝 괄호 제거) → 공백 접기 → casefold.
- `ukey(s)`: `fold(s, drop_note=False)` 에서 공백 제거 — 괄호 꼬리 `(양산)`·`(선행)` 은 실제 구분이라 남긴다.
- `note(s)`: 끝 괄호 안 표기(casefold). `num_tokens(s)`: 숫자 덩어리 집합(차수·버전).
- `name_toks(s)`: `fold(s, False).split()` 집합. `bigram_dice(a, b)`: `fold(·)` 공백 제거 2-gram Dice.

표준 라이브러리만 쓴다(팀 서버·개인 PC·클라우드PC 공용).
"""
import re
import unicodedata

# 구분자 → 공백(전각 괄호는 반각으로). NFKC 앞뒤 두 번 적용한다(전각 구분자가 NFKC 뒤에 반각 '-' 로 바뀌는 경우).
_SEP = {"·": " ", "・": " ", "ㆍ": " ", "‧": " ", "（": "(", "）": ")", "－": " ", "–": " ", "—": " ",
        "／": " ", "_": " ", "-": " ", "/": " "}
_NOTE_TAIL = re.compile(r"\s*\([^)]*\)\s*$")
_NOTE_RX = re.compile(r"\(([^)]*)\)\s*$")
_DIGITS = re.compile(r"\d+")


def _sep(t: str) -> str:
    return "".join(_SEP.get(ch, ch) for ch in t)


def fold(s, drop_note: bool = True) -> str:
    """비교용 접기. None·숫자도 문자열로 받아 접는다."""
    t = _sep(str(s if s is not None else ""))
    t = unicodedata.normalize("NFKC", t)
    t = _sep(t)
    if drop_note:
        t = _NOTE_TAIL.sub("", t)
    return " ".join(t.split()).casefold()


def ukey(s) -> str:
    """정규화 키 — 이름·별칭 동일성의 유일한 기준(괄호 꼬리 보존, 공백 제거)."""
    return fold(s, drop_note=False).replace(" ", "")


def note(s) -> str:
    """끝 괄호 안 표기(예 '열해석(양산)' → '양산'). 없으면 ''."""
    m = _NOTE_RX.search(unicodedata.normalize("NFKC", str(s if s is not None else "")))
    return m.group(1).strip().casefold() if m else ""


def num_tokens(s) -> set[str]:
    """숫자 덩어리 집합(차수·버전 — '2세대'·'v3' 의 숫자)."""
    return set(_DIGITS.findall(fold(s, drop_note=False)))


def name_toks(s) -> set[str]:
    """이름 낱말 집합(괄호 꼬리 포함)."""
    return set(fold(s, drop_note=False).split())


def bigram_dice(a, b) -> float:
    """두 이름의 2-gram Dice 계수(0~1). 괄호 꼬리는 떼고, 공백은 지우고 비교한다."""
    def bg(t):
        t = fold(t).replace(" ", "")
        return {t[i:i + 2] for i in range(len(t) - 1)} or {t}
    x, y = bg(a), bg(b)
    return 2 * len(x & y) / (len(x) + len(y) or 1)
