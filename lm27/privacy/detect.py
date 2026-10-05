# -*- coding: utf-8 -*-
r"""``sanitize()`` 본체(P §4·§6) — 원문 한 필드 → 정제문 + 범주별 건수. 탐지 순서는 규칙의 일부다(P §4 표 0~11).

PRIVACY.md §6 코드 블록을 옮겼다. 바꾼 점(출력은 같다 — 회귀 말뭉치로 확인):
  · ``from .rules import *`` → 쓰는 이름만 명시 import(ruff F403/F405 없이).
  · 사전 정규식(고객사·협력사·과제·본인·사람)을 이름 목록별로 캐시(P §6 구현 주의)하고, 경계 단언을 이름마다가 아니라
    묶음 앞뒤에 한 번만 둔다(일치 결과는 같다 — 사람 사전 3천여 명에서 20,000행 21초 → 2초). 길이 같은 이름은 사전순.
  · 사전 가명화는 범주(고객사·협력사·과제) 안에서 **항목을 가로질러** 긴 이름 먼저(P §8.2 ②: '고객사A2' 가 다른 항목의
    '고객사A' 보다 우선 — 코드 블록은 항목마다 따로 돌아 이 규칙을 못 지켰다), 같은 이름은 먼저 정의된 항목(§8.3).
    항목이 하나뿐인 문맥(회귀 말뭉치 문맥 A)의 출력은 같다.
  · ``SanitizeContext.extra_stopwords``(설정 ``privacy.names.extraStopwords`` — 계약 §5.2·X-114): 호칭형 이름 후보에서
    ``NAME_STOP`` 과 합집합으로 뺀다. 비어 있으면(기본) 출력은 P §6 과 같다.
  · 토큰을 자르지 않는 절단은 공개 이름 ``safe_truncate``(게이트 ``max_item_chars`` 가 같은 함수를 쓴다 — P §13.2).

불변식(P §1.3): 멱등 ``sanitize(sanitize(x).text) == sanitize(x)``(기존 토큰은 보호 구간), 결정적(난수·시각 없음),
감사·예외·stderr 에 원문 금지 — 이 모듈은 아무것도 쓰거나 출력하지 않는다. 표준 라이브러리만(에이전트 bin 사본).

``re.sub`` 의 치환 함수 안에서 참조하는 ``t`` 는 **치환 전 문자열**이다(파이썬은 sub 가 끝난 뒤 대입) — 위치 계산이
이 성질에 기대므로 단계를 한 줄씩 유지한다.
"""
from __future__ import annotations

import functools
import hashlib
import hmac
import ipaddress
import re
import unicodedata
from dataclasses import dataclass, field

from .rules import (
    COUNT_AFTER,
    CTX,
    DIM_NEAR,
    ENG_CTX,
    ENG_UNIT_AFTER,
    HONORIFIC,
    ID_BEFORE,
    LABELED_NAME,
    MENTION,
    PERSONAL_MAIL_DOMAINS,
    PROTECT,
    RULES_VERSION,
    RX,
    TITLES,
    TOKEN_RX,
    brn_ok,
    credential_hit,
    luhn_ok,
    plausible_korean_name,
    rrn_checksum_ok,
    rrn_date_ok,
)

CTRL_RX = re.compile("[\x00-\x08\x0b-\x1f\x7f\u200b-\u200f\u2028-\u202e\ufeff\ue000-\uf8ff]")
MAX_SCAN = 4000            # 한 필드에서 검사하는 최대 글자 수(저장 상한보다 충분히 큼, 병적 입력 방어)


@dataclass
class SanitizeContext:
    """정제 문맥(P §3.2) — ``lm27.privacy.context.build_context()`` 가 설정·레지스트리·로컬 전용 사전에서 만든다.
    수집 실행 1회 동안 바꾸지 않는다. 기본값(빈 사전, 0 바이트 키)은 회귀 말뭉치 시험용이다 — 실제 저장 경로는
    키 없음 모드(P §9.4)로 ``[사람#…]`` 를 ``[사람]`` 으로 강등한다(레코드 정제기 몫)."""
    internal_domains: list = field(default_factory=list)
    personal_mail_domains: list = field(default_factory=lambda: list(PERSONAL_MAIL_DOMAINS))
    customers: list = field(default_factory=list)
    partners: list = field(default_factory=list)
    projects: list = field(default_factory=list)
    persons: dict = field(default_factory=dict)
    self_names: list = field(default_factory=list)
    allow_patterns: list = field(default_factory=list)
    extra_ctx: dict = field(default_factory=dict)
    mask_company_suffix: bool = True
    mask_rates: bool = True
    key: bytes = b"\x00" * 32
    person_subkey: bytes | None = None
    extra_stopwords: list = field(default_factory=list)   # 호칭형 NAME_STOP 합집합(계약 §5.2·X-114)


@dataclass(frozen=True)
class SanitizeResult:
    """정제 결과 — ``text`` 정제문(drop 이면 ""), ``hits`` 범주 코드(P §15.3) → 건수, ``drop`` 자격증명이면 행 폐기."""
    text: str
    hits: dict
    drop: bool = False
    drop_reason: str | None = None
    rules_ver: str = RULES_VERSION


def subkey(master: bytes, purpose: str) -> bytes:
    """용도별 하위 키 ``HMAC-SHA256(master, b"lm27:" + purpose)``(계약 §4.2) — 키링·에이전트 하위 키가 같은 값을 낸다."""
    return hmac.new(master, b"lm27:" + purpose.encode("ascii"), hashlib.sha256).digest()


def keyed_hex(master: bytes, purpose: str, value: str) -> str:
    """``HMAC-SHA256(subkey(master, purpose), value)`` 16진 64자(자르지 않음 — 호출자가 앞부분을 쓴다)."""
    return hmac.new(subkey(master, purpose), value.encode("utf-8"), hashlib.sha256).hexdigest()


def norm_person(name: str) -> str:
    """사람 이름 정규화(who_key 재료 ``name:<norm_person>`` — 계약 §4.2): NFKC·소문자, 괄호 안·호칭 꼬리·구분자 제거."""
    n = unicodedata.normalize("NFKC", name).lower()
    n = re.sub(r"\(.*?\)|\[.*?\]", "", n)
    n = re.sub(TITLES + r"$", "", n.strip())
    return re.sub(r"[\s.\-_·]", "", n)


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def _ctx_rx(ctx: SanitizeContext, key: str) -> str:
    base = CTX[key]
    extra = ctx.extra_ctx.get(key) or []
    return base if not extra else "(?:" + base + "|" + "|".join(re.escape(x) for x in extra) + ")"


def safe_truncate(s: str, n: int) -> str:
    """토큰 중간을 자르지 않는다: 잘린 꼬리에 닫히지 않은 '[' (24자 이내)가 있으면 그 앞에서 자른다."""
    if len(s) <= n:
        return s
    cut = s[: n - 1]
    m = re.search(r"\[[^\[\]]{0,24}$", cut)
    if m:
        cut = cut[: m.start()]
    return cut.rstrip() + "…"


class _Ph:
    """보호 구간·토큰을 사설 영역 문자 자리표시자(\uE000 + 번호문자 + \uE001)로 바꿔 두고 마지막에 복원."""

    def __init__(self):
        self.items: list[str] = []

    def put(self, s: str) -> str:
        self.items.append(s)
        return "\ue000" + chr(0xE100 + len(self.items) - 1) + "\ue001"

    def restore(self, t: str) -> str:
        return re.sub("\ue000(.)\ue001", lambda m: self.items[ord(m.group(1)) - 0xE100], t)


def _dict_rx(names):
    """사전 매칭: 긴 이름 우선. ASCII 이름은 양쪽 영숫자 경계, 한글 포함 이름은 앞 경계만(뒤에는 조사가 붙음).
    같은 이름 목록이면 컴파일한 정규식을 다시 쓴다(P §6 구현 주의 — 사전 정규식 캐시). 캐시 키는 이름 튜플(문자열 해시는
    파이썬이 기억하므로 이름 3천 개도 호출당 십여 µs)."""
    return _dict_rx_cached(tuple(names))


def _dict_ids(entries, field_: str) -> dict:
    """사전 항목 목록 ``[{"id", names|codenames}]`` → ``{소문자 이름: id}``. 같은 이름(대소문자 무시)이 둘 이상의 id 에
    있으면 먼저 정의된 쪽(P §8.3 ``cfg.dup_alias`` 와 같은 규칙)."""
    out = {}
    for e in entries or ():
        for n in e.get(field_, None) or ():
            if n and n.lower() not in out:
                out[n.lower()] = e["id"]
    return out


def _dict_id(ids: dict, matched: str) -> str:
    """일치한 글자(대소문자 무시 일치)의 id. 소문자 사전에 없으면 casefold 로 다시 찾고, 그래도 없으면 첫 항목 id —
    사전에 걸린 이름은 어느 경우에도 토큰으로 가린다(원문 누출 금지)."""
    hit = ids.get(matched.lower())
    if hit is None:
        cf = matched.casefold()
        hit = next((v for k, v in ids.items() if k.casefold() == cf), None)
    return hit if hit is not None else next(iter(ids.values()))


_ASCII_NAME = re.compile(r"[A-Za-z0-9 .&\-]+")


@functools.lru_cache(maxsize=256)
def _dict_rx_cached(names: tuple):
    """경계 단언을 이름마다 붙이지 않고 묶음 앞뒤로 한 번만 둔다 — 이름이 수천 개인 사람 사전에서 30배 빠르다(이름마다
    lookbehind 를 붙이면 정규식 엔진이 첫 글자 표로 위치를 건너뛰지 못한다). 한글 등이 든 이름 묶음을 먼저, ASCII 이름
    묶음을 뒤에 둔다: 한 위치에서 둘 다 맞으려면 한글 든 이름의 비ASCII 글자가 ASCII 구간과 맞아야 하므로 불가능 —
    그래서 '긴 이름 먼저'(P §8.2 ②)는 묶음 안의 길이순 정렬만으로 지켜진다. 길이 같은 이름은 사전순(결정적)."""
    uniq = sorted({n for n in names if n}, key=lambda n: (-len(n), n))
    mixed = [re.escape(n) for n in uniq if not _ASCII_NAME.fullmatch(n)]
    ascii_ = [re.escape(n) for n in uniq if _ASCII_NAME.fullmatch(n)]
    parts = []
    if mixed:
        parts.append(r"(?<![가-힣A-Za-z0-9])(?:" + "|".join(mixed) + ")")
    if ascii_:
        parts.append(r"(?<![A-Za-z0-9])(?:" + "|".join(ascii_) + r")(?![A-Za-z0-9])")
    return re.compile("|".join(parts), re.I) if parts else None


def sanitize(text: str, field_name: str = "text", ctx: SanitizeContext | None = None,
             max_len: int | None = None) -> SanitizeResult:
    """원문 한 필드를 정제한다(P §4 순서). 앞 ``MAX_SCAN``(4,000)자만 본다. 자격증명이면 ``drop=True``.
    ``field_name`` 은 이름표일 뿐 규칙 분기에 쓰지 않는다(P §13.4 ①). ``max_len`` 이 있으면 토큰을 자르지 않고 절단."""
    ctx = ctx or SanitizeContext()
    hits: dict = {}

    def bump(k):
        hits[k] = hits.get(k, 0) + 1

    if not text:
        return SanitizeResult("", {})
    t = unicodedata.normalize("NFKC", text[:MAX_SCAN])
    t = CTRL_RX.sub(" ", t)

    # (1) 자격증명 → 행 폐기
    if credential_hit(t):
        return SanitizeResult("", {"cred": 1}, True, "cred")

    ph = _Ph()

    def tok(token: str, cat: str):
        bump(cat)
        return ph.put(token)

    def near(s, e, key, before=20, after=20):
        return re.search(_ctx_rx(ctx, key), t[max(0, s - before):e + after], re.I) is not None

    def eng_suppressed(s):
        return ENG_CTX.search(t[max(0, s - 10):s]) is not None

    # (2) 기존 토큰 보호(멱등) · 조직 허용 패턴
    t = TOKEN_RX.sub(lambda m: ph.put(m.group(0)), t)
    for p in ctx.allow_patterns:
        t = re.sub(p, lambda m: ph.put(m.group(0)), t)
    # (3) 라벨형 생년월일·주민 앞자리 (날짜 보호보다 먼저)
    t = RX["birth"].sub(lambda m: m.group(0)[:m.start("d") - m.start()] + tok("[생년월일]", "birth"), t)
    t = RX["rrn_front"].sub(lambda m: m.group(0)[:m.start("d") - m.start()] + tok("[주민번호]", "rrn"), t)
    # (4) 날짜·시각·버전·규격 보호
    for _, rx in PROTECT:
        t = rx.sub(lambda m: ph.put(m.group(0)), t)

    # (5) URL · 이메일 · 경로
    t = RX["url"].sub(lambda m: tok("[URL]", "url"), t)

    def email_rep(m):
        dom = m.group("dom").lower()
        label = dom
        if any(dom == d or dom.endswith("." + d) for d in ctx.internal_domains):
            label = "사내"
        elif dom in ctx.personal_mail_domains:
            label = "개인메일"
        else:
            for c in ctx.customers:
                if any(dom == d or dom.endswith("." + d) for d in c.get("domains", [])):
                    label = "고객사:" + c["id"]
            for v in ctx.partners:
                if any(dom == d or dom.endswith("." + d) for d in v.get("domains", [])):
                    label = "협력사:" + v["id"]
        return tok("[이메일@" + label + "]", "email")
    t = RX["email"].sub(email_rep, t)

    def path_rep(m):
        bump("path")
        base = m.group("base") or ""
        return ph.put("[경로]") + ("\\" + base if base else "")
    t = RX["path"].sub(path_rep, t)

    # (6) 사전 가명화: 고객사 → 협력사 → 과제 코드네임 → 본인 → 사람 사전. 한 범주 안에서는 항목을 가로질러
    #     긴 이름 먼저(P §8.2 ② — '고객사A2' 가 다른 항목의 '고객사A' 보다 우선), 같은 이름은 먼저 정의된 항목(§8.3)
    for entries, field_, label, cat in ((ctx.customers, "names", "고객사", "customer"),
                                        (ctx.partners, "names", "협력사", "partner"),
                                        (ctx.projects, "codenames", "과제", "project")):
        ids = _dict_ids(entries, field_)
        rx = _dict_rx(ids)
        if rx:
            t = rx.sub(lambda m, ids=ids, label=label, cat=cat: tok("[" + label + ":" + _dict_id(ids, m.group(0)) + "]",
                                                                    cat), t)
    rx = _dict_rx(ctx.self_names)
    if rx:
        t = rx.sub(lambda m: tok("[나]", "self"), t)

    def person_token(name: str) -> str:
        v = "name:" + norm_person(name)
        pk = ctx.persons.get(name) or (hmac.new(ctx.person_subkey, v.encode("utf-8"), hashlib.sha256).hexdigest()
                                       if ctx.person_subkey else keyed_hex(ctx.key, "person", v))
        return "[사람#" + pk[:6] + "]"
    rx = _dict_rx(ctx.persons)
    if rx:
        t = rx.sub(lambda m: tok(person_token(m.group(0)), "person"), t)

    # (7) 이름 문맥 규칙: 멘션 → 라벨형 → 호칭형(호칭형은 NAME_STOP ∪ ctx.extra_stopwords 제외)
    extra_stop = frozenset(ctx.extra_stopwords or ())

    def name_sub(require_plausible: bool):
        def rep(m):
            n = m.group("name")
            if require_plausible and re.fullmatch(r"[가-힣]+", n) and (not plausible_korean_name(n)
                                                                     or n in extra_stop):
                return m.group(0)
            s, e = m.span("name")
            return m.group(0)[:s - m.start()] + tok(person_token(n), "person") + m.group(0)[e - m.start():]
        return rep
    t = MENTION.sub(name_sub(False), t)
    t = LABELED_NAME.sub(name_sub(False), t)
    t = HONORIFIC.sub(name_sub(True), t)

    # (8) 숫자형 PII — 순서 고정
    def v_rrn(m):
        d = _digits(m.group(0))
        if not rrn_date_ok(d):
            return m.group(0)
        hy = any(ch in m.group(0) for ch in "-–—")
        ok = (hy and not eng_suppressed(m.start())) or (rrn_checksum_ok(d) and not eng_suppressed(m.start()))
        ok = ok or near(m.start(), m.end(), "rrn")
        if not ok:
            return m.group(0)
        return tok("[외국인등록번호]", "frn") if d[6] in "5678" else tok("[주민번호]", "rrn")
    t = RX["rrn"].sub(v_rrn, t)
    t = RX["rrn_masked"].sub(
        lambda m: tok("[외국인등록번호]" if _digits(m.group(0))[6:7] in ("5", "6", "7", "8") else "[주민번호]", "rrn"), t)

    def v_card(m):
        d = _digits(m.group(0))
        if eng_suppressed(m.start()):
            return m.group(0)
        if luhn_ok(d) or near(m.start(), m.end(), "card"):
            return tok("[카드]", "card")
        return m.group(0)
    t = RX["card16"].sub(v_card, t)
    t = RX["card15"].sub(v_card, t)
    t = RX["card_masked"].sub(lambda m: tok("[카드]", "card"), t)

    t = RX["mobile"].sub(lambda m: tok("[전화]", "phone"), t)
    t = RX["landline"].sub(lambda m: m.group(0) if eng_suppressed(m.start()) else tok("[전화]", "phone"), t)
    t = RX["rep"].sub(lambda m: tok("[전화]", "phone")
                      if near(m.start(), m.end(), "phone_rep", 15, 5) and not eng_suppressed(m.start()) else m.group(0), t)
    t = RX["intl"].sub(lambda m: tok("[전화]", "phone"), t)

    def v_brn(m):
        if eng_suppressed(m.start()):
            return m.group(0)
        if brn_ok(_digits(m.group(0))) or near(m.start(), m.end(), "brn"):
            return tok("[사업자번호]", "brn")
        return m.group(0)
    t = RX["brn"].sub(v_brn, t)
    t = RX["brn_bare"].sub(lambda m: tok("[사업자번호]", "brn")
                           if near(m.start(), m.end(), "brn") and brn_ok(m.group(0)) and not eng_suppressed(m.start())
                           else m.group(0), t)
    t = RX["corp"].sub(lambda m: tok("[법인번호]", "corp") if near(m.start(), m.end(), "corp", 15, 5) else m.group(0), t)

    t = RX["passport"].sub(lambda m: tok("[여권]", "passport")
                           if near(m.start(), m.end(), "passport", 25, 25) and not eng_suppressed(m.start()) else m.group(0), t)
    t = RX["license"].sub(lambda m: tok("[운전면허]", "license")
                          if near(m.start(), m.end(), "license", 25, 25) and not eng_suppressed(m.start()) else m.group(0), t)
    t = RX["license_region"].sub(lambda m: tok("[운전면허]", "license"), t)

    def v_acct(m):
        g = m.group(0)
        if not 10 <= len(_digits(g)) <= 16 or eng_suppressed(m.start()):
            return g
        strong = re.search(_ctx_rx(ctx, "account_strong"), t[max(0, m.start() - 12):m.start()], re.I) is not None
        weak = near(m.start(), m.end(), "account_strong") or near(m.start(), m.end(), "account_weak")
        year_led = re.match(r"(?:19|20)\d{2}(?:-|$)", g) is not None or re.match(r"(?:19|20)\d{6}", g) is not None
        if year_led and not strong:
            return g
        return tok("[계좌]", "account") if (strong or weak) else g
    t = RX["account_hy"].sub(v_acct, t)
    t = RX["account_bare"].sub(v_acct, t)

    def v_ip(m):
        g = m.group(0)
        try:
            ip = ipaddress.ip_address(g.split(":")[0])
        except ValueError:
            return g
        if ip.is_private or ip.is_loopback or ip.is_link_local or m.group("port") or near(m.start(), m.end(), "ip"):
            return tok("[IP]", "ip")
        return g
    t = RX["ipv4"].sub(v_ip, t)

    def v_ip6(m):
        g = m.group(0)
        if g.count(":") < 2 or not re.search(r"[0-9A-Fa-f]", g):
            return g
        try:
            ipaddress.IPv6Address(g)
        except ValueError:
            return g
        return tok("[IP]", "ip")
    t = RX["ipv6"].sub(v_ip6, t)

    # (9) 금액·비율 (§7)
    if ctx.mask_rates:
        t = RX["rate"].sub(lambda m: m.group(0)[:m.start("num") - m.start()] + tok("[비율]", "rate"), t)
    t = RX["money_cur"].sub(lambda m: tok("[금액]", "money"), t)

    def v_kor(m):
        after = t[m.end():m.end() + 6]
        if m.group("cur"):
            return tok("[금액]", "money")
        if COUNT_AFTER.match(after) or ENG_UNIT_AFTER.match(after):
            return m.group(0)
        if "억" in m.group(0) or near(m.start(), m.end(), "money", 20, 10):
            return tok("[금액]", "money")
        return m.group(0)
    t = RX["money_kor"].sub(v_kor, t)

    def v_suffix(m):
        num = m.group("num")
        if "," in num or len(_digits(num)) >= 3 or near(m.start(), m.end(), "money", 20, 10):
            return tok("[금액]", "money")
        return m.group(0)
    t = RX["money_suffix"].sub(v_suffix, t)

    def v_kw_adj(m):
        after = t[m.end():m.end() + 6]
        if ENG_UNIT_AFTER.match(after) or COUNT_AFTER.match(after) or DIM_NEAR.match(after):
            return m.group(0)
        return m.group(0)[:m.start("num") - m.start()] + tok("[금액]", "money")
    t = RX["money_kw_adj"].sub(v_kw_adj, t)

    def v_bare(m):
        s, e = m.start(), m.end()
        if not re.search(_ctx_rx(ctx, "money"), t[max(0, s - 20):e + 10], re.I):
            return m.group(0)
        after, before = t[e:e + 6], t[max(0, s - 4):s]
        if ENG_UNIT_AFTER.match(after) or COUNT_AFTER.match(after) or DIM_NEAR.match(after) or DIM_NEAR.search(before):
            return m.group(0)
        if ID_BEFORE.search(t[max(0, s - 8):s]) or eng_suppressed(s):
            return m.group(0)
        return tok("[금액]", "money")
    t = RX["money_bare"].sub(v_bare, t)

    # (10) 회사 접미형
    if ctx.mask_company_suffix:
        t = RX["company"].sub(lambda m: tok("[회사]", "company"), t)

    # (11) 복원·정리·절단
    out = re.sub(r"[ \t]{2,}", " ", ph.restore(t)).strip()
    if max_len:
        out = safe_truncate(out, max_len)
    return SanitizeResult(out, hits)
