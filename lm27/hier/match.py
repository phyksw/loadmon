# -*- coding: utf-8 -*-
"""분류 토큰화·키워드 매칭 단일원(H §4.3, 계약 §2.10 · X-050 · X-051).

- `match_tokens(text)`: 정제문 → 분류 토큰 집합(H 의 `tokens_of` — 정제기 `scan.tokens_of` 와 이름이 겹쳐
  `match_tokens` 로 바꿨다, X-051). NFKC → 회신·전달 머리 제거 → 꺾쇠 토큰 제거 → 구분자로 나눔 → 소문자,
  2자 이상·숫자만 아님·상용구 아님·판 표기(v3·rev2·r1·날짜 6~8자리) 아님.
- `ent_tokens(text)`: 정제 토큰 `[과제:ID]`·`[고객사:ID]`·`[협력사:ID]` → {'과제': {...}, ...}. 토큰 안 ID 는
  16자 이하(X-050 — P 토큰 문법과 같게).
- `kw_hit(k, toks, mode)`: 부분 문자열 전면 허용 금지('정렬' ⊂ '재정렬', 'ai' ⊂ 'email' 오탐 — LM24 `_kw_hit`).
  `name` 모드(과제 키워드·별칭)는 한글 앞 경계만, `head` 모드(어휘·영역 키워드)는 앞 경계 또는 짧은 접두(≤3자)
  뒤 꼬리(열해석 ⊃ 해석)를 허용한다. 키워드가 여러 조각이면(lidar-x) 모든 조각이 맞아야 한다.
- `ai_hit(text)`: 키워드 'ai' 는 토큰이 아니라 원문(소문자)에 `(?<![a-z])ai(?![a-z])` 로 본다.
- `boilerplate(cfg)`: 분류 상용구 = 시간 상용구(`episode.tokens.boilerplate`) ∪ H 추가 ∪ `hier.tokens.boilerplateAdd`.
- `common_words()`: 업무 일반어(`lm27\\hier\\data\\common_words.txt`, 사내 어휘 없음) — 코드네임 후보 제외용(H §8.1).
"""
import re
import unicodedata
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path

from lm27.util import fsx

TOKEN_RX = re.compile(r"\[(과제|고객사|협력사):([A-Za-z][A-Za-z0-9_\-]{0,15})\]")      # P §5.2 토큰 문법(X-050)
SPECIAL_RX = re.compile(r"\[[^\[\]]{1,40}\]")                                          # 그 밖의 꺾쇠 토큰
SPLIT_RX = re.compile(r"[\s_\-.,/()\[\]+&~:;!?'\"…·「」<>{}|=*#]+")
RE_PREFIX = re.compile(r"^\s*((re|fw|fwd|회신|전달|답장)\s*[:：]\s*)+", re.I)
VER_RX = re.compile(r"v\d+|rev\d+|r\d+|\d{6,8}")
HANGUL_RX = re.compile(r"[가-힣]")
AI_RX = re.compile(r"(?<![a-z])ai(?![a-z])")
ENT_KINDS = ("과제", "고객사", "협력사")
# H §4.3 의 분류 전용 상용구 추가분(시간 상용구 episode.tokens.boilerplate 에 더한다)
H_BOILERPLATE = ("안녕하세요", "감사합니다", "드림", "올립니다", "입니다", "했습니다", "해주세요", "주세요", "바랍니다",
                 "진행", "내용", "건으로")
_FUZZY_MIN = 0.9
_COMMON_WORDS_FILE = Path(__file__).with_name("data") / "common_words.txt"     # 패키지 동봉 자료(데이터 폴더 아님)


@lru_cache(maxsize=1)
def _default_boilerplate() -> frozenset[str]:
    """설정 없이 쓸 때의 상용구 = 설정 레지스트리 선언 기본값 + H 추가(값의 원천은 한 곳 — 레지스트리)."""
    from lm27.config import registry_meta          # 지연 import — 설정 레지스트리 파일을 실제로 쓸 때만 읽는다
    base = registry_meta("episode.tokens.boilerplate").default
    return frozenset(str(w).lower() for w in (*base, *H_BOILERPLATE))


def boilerplate(cfg=None) -> frozenset[str]:
    """분류 상용구 집합(소문자). cfg 가 있으면 실효 설정값, 없으면 선언 기본값."""
    if cfg is None:
        return _default_boilerplate()
    words = list(cfg["episode.tokens.boilerplate"]) + list(H_BOILERPLATE) + list(cfg["hier.tokens.boilerplateAdd"])
    return frozenset(str(w).lower() for w in words)


def _nfkc(text) -> str:
    return unicodedata.normalize("NFKC", str(text or ""))


def match_tokens(text, boiler=None) -> set[str]:
    """정제문 → 분류 토큰 집합(H §4.3 `tokens_of`). boiler 를 주지 않으면 선언 기본 상용구."""
    bp = _default_boilerplate() if boiler is None else boiler
    t = RE_PREFIX.sub("", _nfkc(text))
    t = SPECIAL_RX.sub(" ", t)                     # 꺾쇠 토큰은 ent_tokens 로 따로 뽑는다
    out = set()
    for w in SPLIT_RX.split(t.lower()):
        w = w.strip()
        if len(w) < 2 or w.isdigit() or w in bp or VER_RX.fullmatch(w):
            continue
        out.add(w)
    return out


def ent_tokens(text) -> dict[str, set[str]]:
    """정제 토큰 → {'과제': {ID…}, '고객사': {…}, '협력사': {…}}."""
    out: dict[str, set[str]] = {k: set() for k in ENT_KINDS}
    for k, v in TOKEN_RX.findall(str(text or "")):
        out[k].add(v)
    return out


def ai_hit(text) -> bool:
    """키워드 'ai' 의 예외 판정 — 원문(소문자)에 단어 경계로('email'·'detail' 은 아님)."""
    return AI_RX.search(_nfkc(text).lower()) is not None


def kw_parts(k) -> list[str]:
    """키워드 조각(2자 이상) — kw_hit 와 같은 분해."""
    return [p for p in SPLIT_RX.split(_nfkc(k).lower()) if len(p) >= 2]


def kw_hit(k, toks, mode: str = "name") -> bool:
    """키워드 k 가 토큰 집합 toks 에 맞는가. mode = 'name'(과제 키워드·별칭) | 'head'(어휘·영역 키워드)."""
    if mode not in ("name", "head"):
        raise ValueError("kw_hit: mode 는 'name' 또는 'head'")
    parts = kw_parts(k)
    if not parts:
        return False

    def one(p: str) -> bool:
        if p in toks:
            return True
        if HANGUL_RX.search(p):
            if any(t.startswith(p) for t in toks):                       # 조사 붙은 꼴(과제a의) — 앞 경계
                return True
            return mode == "head" and any(t.endswith(p) and len(t) - len(p) <= 3 for t in toks)   # 열해석 ⊃ 해석
        if len(p) >= 4 and any(t.startswith(p) or t.endswith(p) for t in toks):
            return True
        return len(p) >= 5 and any(len(t) >= 4 and SequenceMatcher(None, p, t).ratio() >= _FUZZY_MIN for t in toks)
    return all(one(p) for p in parts)


@lru_cache(maxsize=1)
def common_words() -> frozenset[str]:
    """업무 일반어(소문자·NFKC). 한 줄 한 낱말, '#' 뒤는 주석."""
    raw = fsx.read_bytes(_COMMON_WORDS_FILE).decode("utf-8")
    out = set()
    for line in raw.splitlines():
        w = line.split("#", 1)[0].strip()
        if w:
            out.add(_nfkc(w).lower())
    return frozenset(out)
