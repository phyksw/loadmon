# -*- coding: utf-8 -*-
"""PII 카나리아(WP-05) — TAB §9.2 U03 · P §19 T19(말뭉치 양성 P01~P60 형식) 전부를 **런타임에 조립**한다.

저장소 텍스트에는 카나리아 원값·사설 IP·비예시 도메인 리터럴을 두지 않는다. 값은 시드로 조립한다(같은 시드 → 같은 값).
이름 카나리아는 자리표시자(홍길동·김철수)와 다른 합성 이름을 음절로 조립한다(문서 예시와 구분되게 — 계획 §5 WP-05 주의).

    from tests.fixtures.canary import canaries, find_canaries
    cs = canaries()                                    # 기본 시드 0 — 매번 같은 값
    raw = synth.raw_records("mail", canaries=cs)       # 원시 텍스트 필드에 c.sentence(문맥 포함 문장)를 심는다
    self.assertEqual(find_canaries(segment_bytes), []) # 찾은 카나리아 id 목록(값은 돌려주지 않는다)

묶음(group)
    pii  형식만으로 정제기가 잡아야 하는 원값(전화·주민·카드·계좌·이메일·IP·URL·경로·금액·이름 …) — 저장·전송 어디에도 0
    ctx  정제 사전이 있어야 잡히는 원값(고객사·과제 코드네임·사전 인물·본인 이름) — canary_ctx() 를 문맥에 넣고 시험
    env  게이트 카나리아(PC 이름·Windows 계정명·MachineGuid, P §13.1) — 프롬프트·팀 페이로드에 0
    key  가명 키 모양 값(who_key·로컬 키·pc_id·kid, P §14.3) — 팀 페이로드·프롬프트에 0(세그먼트에는 정상적으로 있을 수 있다)
weak = 짧거나 흔한 모양이라 바이트 검색이 우연히 맞을 수 있는 것 — find_canaries 기본에서 뺀다(weak=True 로 포함).
"""
from __future__ import annotations

import gzip
import html
import io
import json
import random
import re
import zipfile
import zlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

GROUPS = ("pii", "ctx", "env", "key")
SLOTS = ("text", "file", "title", "addr", "name", "path", "id")
CTX_CUSTOMER_ID = "C97"          # 카나리아 고객사 ID(정제 사전용, 자리표시자 C01 과 구분)
CTX_PROJECT_ID = "P0097"         # 카나리아 과제 ID(말뭉치 문맥 A 의 시험값 형식 P0001 과 같은 모양)

_SUR2 = ("남궁", "황보", "선우", "제갈", "독고")
_SUR1 = ("탁", "편", "봉", "옥", "빈")
_GIVEN = ("하", "윤", "서", "도", "린", "온", "결", "솔", "율", "채", "담", "슬")
_CORP = ("가", "온", "누", "리", "마", "루", "다", "솜", "새", "빛")
_UP = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_LO = "abcdefghijkmnopqrstuvwxyz"
_HEX = "0123456789abcdef"


@dataclass(frozen=True)
class Canary:
    cid: str            # 안정 ID(예: "c07.rrn") — 시험 실패 문구에는 값 대신 이것만 쓴다
    cat: str            # 범주(P §15.3 코드 계열 + U03 항목)
    group: str          # pii · ctx · env · key
    ref: str            # 근거 행(P01~P60 · U03)
    value: str          # 원값 — 정제·전송 뒤 어디에도 남으면 안 된다
    sentence: str       # 정제기가 그 형식을 잡는 문맥 문장(원시 텍스트 필드에 심는다)
    slot: str = "text"  # 심을 수 있는 원시 필드 종류(SLOTS)
    token: str = ""     # 기대 정제 토큰(참고용)
    weak: bool = False


class _Gen:
    def __init__(self, seed: int):
        self.r = random.Random(f"lm27-canary/{seed}")

    def d(self, n: int, nz: bool = False) -> str:
        s = "".join(self.r.choice("0123456789") for _ in range(n))
        if nz and s[0] == "0":
            s = self.r.choice("123456789") + s[1:]
        return s

    def hx(self, n: int) -> str:
        return "".join(self.r.choice(_HEX) for _ in range(n))

    def up(self, n: int) -> str:
        return "".join(self.r.choice(_UP) for _ in range(n))

    def lo(self, n: int) -> str:
        return "".join(self.r.choice(_LO) for _ in range(n))

    def pick(self, seq: Sequence[str]) -> str:
        return self.r.choice(seq)

    def given(self) -> str:
        a = self.pick(_GIVEN)
        b = self.pick([g for g in _GIVEN if g != a])
        return a + b


# ── 체크섬(정제기 탐지기가 쓰는 공개 알고리즘 — 시험 값이 '형식이 맞는 가짜'가 되게) ─────────────
def rrn_check(d12: str) -> int:
    w = (2, 3, 4, 5, 6, 7, 8, 9, 2, 3, 4, 5)
    return (11 - sum(int(c) * k for c, k in zip(d12, w, strict=True)) % 11) % 10


def rrn_ok(v: str) -> bool:
    d = re.sub(r"\D", "", v)
    return len(d) == 13 and rrn_check(d[:12]) == int(d[12])


def luhn_check(payload: str) -> int:
    s = 0
    for i, c in enumerate(reversed(payload)):
        n = int(c)
        if i % 2 == 0:
            n *= 2
            if n > 9:
                n -= 9
        s += n
    return (10 - s % 10) % 10


def luhn_ok(v: str) -> bool:
    d = re.sub(r"\D", "", v)
    return len(d) >= 12 and luhn_check(d[:-1]) == int(d[-1])


def brn_check(d9: str) -> int:
    w = (1, 3, 7, 1, 3, 7, 1, 3, 5)
    s = sum(int(c) * k for c, k in zip(d9, w, strict=True)) + (int(d9[8]) * 5) // 10
    return (10 - s % 10) % 10


def brn_ok(v: str) -> bool:
    d = re.sub(r"\D", "", v)
    return len(d) == 10 and brn_check(d[:9]) == int(d[9])


def _rrn(g: _Gen, sexes: str) -> str:
    body = f"{g.r.randint(62, 99):02d}{g.r.randint(1, 12):02d}{g.r.randint(1, 28):02d}{g.pick(sexes)}{g.d(5)}"
    return body + str(rrn_check(body))


def _card(g: _Gen, prefix: str, length: int) -> str:
    payload = prefix + g.d(length - 1 - len(prefix))
    return payload + str(luhn_check(payload))


def _ip(*parts: int) -> str:
    return ".".join(str(p) for p in parts)


@lru_cache(maxsize=8)
def _build(seed: int) -> tuple[Canary, ...]:
    g = _Gen(seed)
    out: list[Canary] = []

    def add(cat: str, group: str, ref: str, value: str, sentence: str, slot: str = "text", token: str = "",
            weak: bool = False) -> None:
        out.append(Canary(f"c{len(out) + 1:02d}.{cat}", cat, group, ref, value, sentence, slot, token, weak))

    # 전화(P10~P16 · P54)
    v = f"010-{g.d(4, True)}-{g.d(4)}"
    add("phone", "pii", "P10", v, f"제 번호 {v} 로 연락주세요", token="[전화]")
    v = f"010{g.d(8, True)}"
    add("phone_digits", "pii", "P11", v, f"연락처 {v}", token="[전화]")
    v = f"+82 10 {g.d(4, True)} {g.d(4)}"
    add("phone_intl", "pii", "P12", v, f"{v} 로 회신 바랍니다", token="[전화]")
    v = f"02-{g.d(3, True)}-{g.d(4)}"
    add("phone_seoul", "pii", "P12", v, f"대표 {v}", token="[전화]")
    v = f"(031) {g.d(3, True)}-{g.d(4)}"
    add("phone_area", "pii", "P13", v, f"{v} 로 회신", token="[전화]")
    v = f"070-{g.d(4, True)}-{g.d(4)}"
    add("phone_voip", "pii", "P14", v, f"인터넷전화 {v}", token="[전화]")
    v = f"1{g.pick(('588', '577', '544', '566', '644', '661'))}-{g.d(4, True)}"
    add("phone_rep", "pii", "P15", v, f"고객센터 {v} 문의", token="[전화]")
    v = f"0505-{g.d(3, True)}-{g.d(4)}"
    add("phone_safe", "pii", "P16", v, f"안심번호 {v}", token="[전화]")
    v = f"02-{g.d(3, True)}-{g.d(4)}"
    add("phone_fax", "pii", "P54", v, f"Fax.{v} / 내선 안내", token="[전화]")
    # 주민·외국인등록번호(P01~P05 · P51) — 체크섬이 맞는 가짜
    v = _rrn(g, "12")
    v = f"{v[:6]}-{v[6:]}"
    add("rrn", "pii", "P01", v, f"RE: 주민번호 {v} 확인 요청", token="[주민번호]")
    v = _rrn(g, "12")
    add("rrn_digits", "pii", "P02", v, f"생년 및 주민 {v} 기재", token="[주민번호]")
    v = _rrn(g, "12")
    v = f"{v[:6]}-{v[6]}******"
    add("rrn_masked", "pii", "P03", v, f"등본상 {v} 로 표기", token="[주민번호]")
    v = _rrn(g, "5678")
    v = f"{v[:6]}-{v[6:]}"
    add("frn", "pii", "P04", v, f"외국인등록번호 {v} 사본", token="[외국인등록번호]")
    v = _rrn(g, "12")
    add("rrn_plain", "pii", "P05", v, f"신청서 {v} 첨부", token="[주민번호]")
    v = _rrn(g, "12")[:6]
    add("rrn_front", "pii", "P51", v, f"주민번호 앞자리 {v} 만 기재", token="[주민번호]", weak=True)
    # 카드(P06~P09) — Luhn
    v = _card(g, "4", 16)
    v = "-".join((v[0:4], v[4:8], v[8:12], v[12:16]))
    add("card", "pii", "P06", v, f"카드번호 {v} 결제 확인", token="[카드]")
    v = _card(g, "5" + g.pick("12345"), 16)
    v = " ".join((v[0:4], v[4:8], v[8:12], v[12:16]))
    add("card_space", "pii", "P07", v, f"법인카드 {v} 사용 내역", token="[카드]")
    v = _card(g, "37", 15)
    v = "-".join((v[0:4], v[4:10], v[10:15]))
    add("card_amex", "pii", "P08", v, f"{v} 승인", token="[카드]")
    v = f"{g.d(4, True)}-****-****-{g.d(4)}"
    add("card_masked", "pii", "P09", v, f"카드 {v} 결제 완료", token="[카드]")
    # 사업자번호(P17·P18) — 체크섬
    for ref, tpl in (("P17", "사업자등록번호 {} 거래처 등록"), ("P18", "번호 {} 확인")):
        d9 = g.d(3, True) + g.d(6)
        d = d9 + str(brn_check(d9))
        v = f"{d[:3]}-{d[3:5]}-{d[5:]}"
        add("brn", "pii", ref, v, tpl.format(v), token="[사업자번호]")
    # 여권·운전면허(P19~P22)
    v = "M" + g.d(8, True)
    add("passport", "pii", "P19", v, f"여권번호 {v} 로 출장 항공권 예약", token="[여권]")
    v = "M" + g.d(3, True) + g.pick("ABCDEFGHJKLMNPRSTUVWXYZ") + g.d(4)
    add("passport_new", "pii", "P20", v, f"passport {v} 사본 송부", token="[여권]")
    v = f"{g.r.randint(11, 28)}-{g.d(2)}-{g.d(6)}-{g.d(2)}"
    add("license", "pii", "P21", v, f"운전면허 {v} 사본", token="[운전면허]")
    v = f"{g.d(2, True)}-{g.d(6)}-{g.d(2)}"
    add("license_region", "pii", "P22", v, f"운전면허증 서울 {v} 갱신", token="[운전면허]")
    # 계좌(P23~P25)
    v = f"{g.d(3, True)}-{g.d(3)}-{g.d(6)}"
    add("account", "pii", "P23", v, f"계좌 {v} 로 송금 부탁드립니다", token="[계좌]")
    v = g.d(13, True)
    add("account_digits", "pii", "P24", v, f"입금 계좌 {v} 확인", token="[계좌]")
    v = f"{g.d(6, True)}-{g.d(2)}-{g.d(6)}"
    add("account_bank", "pii", "P25", v, f"급여 은행 계좌 {v} 이체 완료", token="[계좌]")
    # 이메일(P26 · P27 · P40) — 비예시 도메인은 조각을 이어 런타임에만 만든다
    ext_dom = ".".join(("example", "co", "kr"))
    v = f"{g.lo(5)}.{g.lo(3)}@{ext_dom}"
    add("email_ext", "pii", "P26", v, f"보고서 송부 {v}", slot="addr", token=f"[이메일@{ext_dom}]")
    v = f"qa{g.d(3, True)}.{g.lo(4)}@corp.example"
    add("email_int", "pii", "P27", v, f"회신: {v}", slot="addr", token="[이메일@사내]")
    v = f"{g.lo(4)}{g.d(2)}@custa.example"
    add("email_cust", "pii", "P40", v, f"{v} 회신", slot="addr", token="[이메일@고객사:C01]")
    # IP(P28 · P29 · P52 · U03 사설 IP) — 숫자를 이어 런타임에만 만든다
    v = _ip(10, g.r.randint(1, 254), g.r.randint(1, 254), g.r.randint(1, 254))
    add("ip_private", "pii", "P28", v, f"서버 {v}:8080 재기동", token="[IP]")
    v = _ip(203, 0, 113, g.r.randint(1, 254))
    add("ip_public", "pii", "P29", v, f"접속 IP {v} 차단", token="[IP]")
    v = _ip(192, 168, g.r.randint(0, 254), g.r.randint(2, 254))
    add("ip_private_c", "pii", "U03", v, f"게이트웨이 {v} 점검", token="[IP]")
    v = _ip(172, g.r.randint(16, 31), g.r.randint(0, 254), g.r.randint(2, 254))
    add("ip_private_b", "pii", "U03", v, f"공유 서버 {v} 접속", token="[IP]")
    v = "fe80::" + ":".join(g.hx(4) for _ in range(4))
    add("ipv6", "pii", "P52", v, f"장애 서버 {v}", token="[IP]")
    # URL(P30)
    v = f"https://portal{g.d(2)}.example.com/view?id={g.d(5, True)}&user={g.lo(4)}"
    add("url", "pii", "P30", v, f"링크 {v} 참고", token="[URL]")
    # 경로(P31 · P53 · U03 'C:\\'·UNC) — 사용자 폴더명·서버 이름이 든 앞부분이 원값
    winuser = f"{g.lo(4)}.{g.lo(5)}"
    v = "\\".join(("C:", "Users", winuser, "Documents"))
    add("path_win", "pii", "P31", v, v + "\\견적.xlsx", slot="path", token="[경로]")
    v = "\\\\" + "fs" + g.d(2, True) + g.lo(2) + "\\share"
    add("path_unc", "pii", "P53", v, v + "\\팀\\보고서.pptx", slot="path", token="[경로]")
    # 금액(P32~P38 · P48 · P49 · P55)
    v = f"{g.r.randint(11, 98)}억 {g.r.randint(1, 9)}{g.r.randint(1, 9)}00만원"
    add("money_eok", "pii", "P32", v, f"수주 금액 {v} 확정 건", token="[금액]")
    v = "USD " + g.d(7, True)
    add("money_usd", "pii", "P33", v, f"고객사 견적 단가 {v} 으로 회신", token="[금액]")
    v = f"{g.r.randint(2, 9)},{g.d(3)},{g.d(3)}"
    add("money_comma", "pii", "P34", v, f"견적 단가 {v} / 수량 300 ea", token="[금액]")
    v = f"{g.r.randint(2, 9)},{g.d(3)},000원"
    add("money_won", "pii", "P35", v, f"계약금 {v} 입금", token="[금액]")
    v = f"${g.r.randint(2, 9)}.{g.r.randint(1, 9)}M"
    add("money_quote", "pii", "P37", v, f"Quote {v} for next lot", token="[금액]", weak=True)
    v = f"{g.r.randint(11, 99)},{g.d(3)},{g.d(3)}"
    add("money_po", "pii", "P38", v, f"PO 금액 {v} 확정", token="[금액]")
    v = f"{g.r.randint(2, 9)}{g.d(2)},{g.d(3)}원"
    add("money_trip", "pii", "P48", v, f"출장비 {v} 정산", token="[금액]")
    v = f"{g.r.randint(2, 9)}억"
    add("money_scale", "pii", "P49", v, f"{v} 규모 사업 검토", token="[금액]", weak=True)
    v = f"{g.r.randint(2, 9)}억 {g.r.randint(1, 9)}천만 원"
    add("money_mixed", "pii", "P55", v, f"견적 {v} / 납기 2026-11-30", token="[금액]")
    # 비율·회사·생년월일(P46 · P47 · P50)
    v = f"{g.r.randint(2, 19)}.{g.d(3)}%"
    add("rate", "pii", "P46", v, f"네고율 {v} 인하 합의", token="[비율]")
    v = "㈜" + "".join(g.pick(_CORP) for _ in range(3))
    add("company", "pii", "P47", v, f"{v} 견적 회신", token="[회사]")
    v = f"19{g.r.randint(62, 99)}.{g.r.randint(1, 12):02d}.{g.r.randint(1, 28):02d}"
    add("birth", "pii", "P50", v, f"생년월일: {v}", token="[생년월일]")
    # 사람(P42 호칭형 · P43 멘션 · U03 동료 표시명) — 자리표시자와 다른 합성 이름
    v = g.pick(_SUR2) + g.given()
    add("person", "pii", "P42", v, f"{v} 책임님께 보고드립니다", slot="name", token="[사람#]")
    v = g.pick(_SUR2) + g.given()
    add("person_mention", "pii", "P43", v, f"@{v} 확인 부탁드립니다", slot="name", token="[사람#]")
    v = g.pick(_SUR1) + g.given()
    add("peer_name", "pii", "U03", v, f"{v} 선임님 자료 공유드립니다", slot="name", token="[사람#]")
    # 파일 이름 속 PII(P56~P60) — 밑줄·확장자 붙음 누출 회귀
    v = f"010-{g.d(4, True)}-{g.d(4)}"
    add("file_phone", "pii", "P56", v, f"견적_고객사A_{v}.xlsx", slot="file", token="[전화]")
    v = "M" + g.d(8, True)
    add("file_passport", "pii", "P57", v, f"여권사본_{v}.jpg", slot="file", token="[여권]")
    d9 = g.d(3, True) + g.d(6)
    d = d9 + str(brn_check(d9))
    v = f"{d[:3]}-{d[3:5]}-{d[5:]}"
    add("file_brn", "pii", "P58", v, f"사업자등록증_{v}.pdf", slot="file", token="[사업자번호]")
    v = f"{g.d(3, True)}-{g.d(3)}-{g.d(6)}"
    add("file_account", "pii", "P59", v, f"급여계좌_{v}.pdf", slot="file", token="[계좌]")
    v = _rrn(g, "12")
    v = f"{v[:6]}-{v[6:]}"
    add("file_rrn", "pii", "P60", v, f"등본_{v}.pdf", slot="file", token="[주민번호]")
    # 사전 문맥이 있어야 잡히는 것(P39 · P41 · P44 · P45)
    v = "고객사" + g.up(2)
    add("customer", "ctx", "P39", v, f"{v} 2차 미팅 준비", token=f"[고객사:{CTX_CUSTOMER_ID}]")
    v = "PROJ-" + g.up(3)
    add("project", "ctx", "P41", v, f"{v} 샘플 시험 결과", token=f"[과제:{CTX_PROJECT_ID}]")
    v = g.pick(_SUR1) + g.given()
    add("person_dict", "ctx", "P44", v, f"{v} 회신 대기", slot="name", token="[사람#]")
    v = g.pick(_SUR2) + g.given()
    add("self_name", "ctx", "P45", v, f"{v} 작성 보고서", slot="name", token="[나]")
    # 게이트 카나리아(U03 호스트명·Windows 사용자명·MachineGuid, P §13.1)
    v = "DESKTOP-" + g.up(7)
    add("hostname", "env", "U03", v, f"{v} 에서 저장", slot="title", token="(canary)")
    add("winuser", "env", "U03", winuser, f"{winuser} 폴더 정리", token="(canary)")
    v = f"{g.hx(8)}-{g.hx(4)}-4{g.hx(3)}-{g.pick('89ab')}{g.hx(3)}-{g.hx(12)}"
    add("machine_guid", "env", "U03", v, f"장비 {v} 등록", token="(canary)")
    # 가명 키 모양(U03 who_key·로컬 키·pc_id·kid) — 팀 페이로드·프롬프트 금지 값
    add("who_key", "key", "U03", "w" + g.hx(16), "", slot="id")
    for pre, n in (("m", 24), ("e", 24), ("t", 16), ("h", 16), ("d", 16), ("r", 16), ("f", 16), ("s", 16), ("g", 16)):
        add(f"key_{pre}", "key", "U03", pre + g.hx(n), "", slot="id")
    add("pc_id", "key", "U03", "pc_" + g.hx(16), "", slot="id")
    add("kid", "key", "U03", "k" + g.hx(8), "", slot="id")
    return tuple(out)


def canaries(seed: int = 0, groups: Iterable[str] | None = None, *, weak: bool = True) -> tuple[Canary, ...]:
    """카나리아 목록(같은 시드 → 같은 값·같은 cid). groups 로 묶음을 고르고, weak=False 면 약한 것을 뺀다."""
    gs = set(groups) if groups is not None else set(GROUPS)
    bad = gs - set(GROUPS)
    if bad:
        raise ValueError(f"알 수 없는 묶음: {sorted(bad)}")
    return tuple(c for c in _build(seed) if c.group in gs and (weak or not c.weak))


def text_canaries(cs: Iterable[Canary] | None = None) -> tuple[Canary, ...]:
    """원시 텍스트 필드에 심을 것(문장이 있는 pii·ctx·env)."""
    cs = canaries() if cs is None else cs
    return tuple(c for c in cs if c.sentence and c.group != "key")


def canary_ctx(cs: Iterable[Canary] | None = None) -> dict:
    """ctx·env 카나리아를 정제·게이트 문맥에 넣기 위한 사전(P §18.1 문맥 A 모양 + canaries 목록)."""
    by = {c.cat: c for c in (canaries() if cs is None else cs)}
    ctx: dict = {"internal_domains": ["corp.example"], "customers": [], "projects": [], "persons": {},
                 "self_names": [], "canaries": []}
    if "customer" in by:
        ctx["customers"].append({"id": CTX_CUSTOMER_ID, "names": [by["customer"].value], "domains": []})
    if "project" in by:
        ctx["projects"].append({"id": CTX_PROJECT_ID, "codenames": [by["project"].value]})
    if "person_dict" in by:
        ctx["persons"][by["person_dict"].value] = "c0ffee" + "0" * 10
    if "self_name" in by:
        ctx["self_names"].append(by["self_name"].value)
    for c in by.values():
        if c.group == "env":
            ctx["canaries"].append(c.value)
            if c.cat == "machine_guid":
                ctx["canaries"].append(c.value.replace("-", ""))
    return ctx


# ── 찾기 ─────────────────────────────────────────────────────────────────────
def _ascii_alnum(ch: str) -> bool:
    return ch.isascii() and ch.isalnum()


@lru_cache(maxsize=4096)
def _needles(c: Canary) -> tuple[tuple[bytes, bool, bool], ...]:
    """(바이트 패턴, 왼쪽 경계, 오른쪽 경계). 원값 + JSON 이스케이프·\\u 이스케이프·HTML 이스케이프·숫자만·UTF-16LE/BE·
    CP949 형태. 대소문자는 ASCII 만 무시한다(데이터와 패턴 모두 bytes.lower).
    CP949 = 한국어 Windows 의 기본 인코딩(PowerShell 5.1 Set-Content·cmd '>' 리디렉션·-X utf8 없는 open()) — T-07 이
    잡으려는 누출 경로라서 한글 값은 이 바이트로도 찾는다. ASCII 부분은 UTF-8 과 같은 바이트라 경계 규칙도 같다."""
    vals = {c.value}
    if c.cat == "machine_guid":
        vals.add(c.value.replace("-", ""))
    digits = re.sub(r"\D", "", c.value)
    if c.group == "pii" and len(digits) >= 9 and digits != c.value:
        vals.add(digits)
    out: set[tuple[bytes, bool, bool]] = set()
    for v in vals:
        lb, rb = _ascii_alnum(v[0]), _ascii_alnum(v[-1])
        for form in {v, json.dumps(v, ensure_ascii=False)[1:-1], json.dumps(v)[1:-1], html.escape(v, quote=False)}:
            out.add((form.encode("utf-8").lower(), lb, rb))
        out.add((v.encode("utf-16-le").lower(), False, False))
        out.add((v.encode("utf-16-be").lower(), False, False))
        try:
            cp = v.encode("cp949")
        except UnicodeEncodeError:
            cp = None
        if cp is not None and cp != v.encode("utf-8"):
            out.add((cp.lower(), lb, rb))
    return tuple(sorted(out))


def _alnum_byte(b: int) -> bool:
    return 48 <= b <= 57 or 65 <= b <= 90 or 97 <= b <= 122


_HEXB = frozenset(b"0123456789abcdef")


def _left_ok(low: bytes, i: int) -> bool:
    """i 앞이 경계인가. JSON 이스케이프(\\n \\t \\r \\b \\f · \\uXXXX) 바로 뒤도 경계로 본다(직렬화된 본문 속 누출을 놓치지 않게)."""
    if i == 0 or not _alnum_byte(low[i - 1]):
        return True
    if i >= 2 and low[i - 2] == 0x5C and low[i - 1] in b"ntrbf":
        return True
    return i >= 6 and low[i - 6] == 0x5C and low[i - 5] == 0x75 and all(b in _HEXB for b in low[i - 4:i])


def _hit(low: bytes, pat: bytes, lb: bool, rb: bool) -> bool:
    if not (lb or rb):
        return pat in low
    start = 0
    while True:
        i = low.find(pat, start)
        if i < 0:
            return False
        j = i + len(pat)
        if (not lb or _left_ok(low, i)) and (not rb or j >= len(low) or not _alnum_byte(low[j])):
            return True
        start = i + 1


_GZ_MAGIC = b"\x1f\x8b\x08"
_GZ_SCAN_MAX = 8                       # 한 데이터 안에서 풀어 볼 gzip 시작점 수(머리말 뒤에 붙은 gzip 등)


def _gunzip_from(data: bytes, at: int) -> bytes:
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=io.BytesIO(data[at:])) as gz:
        while True:
            try:
                chunk = gz.read(1 << 16)
            except (OSError, EOFError, zlib.error):
                break
            if not chunk:
                break
            buf.write(chunk)
    return buf.getvalue()


def _unpack(data: bytes) -> bytes:
    """검사할 바이트 = 원 바이트 + 그 안의 gzip(여러 멤버 포함)을 풀 수 있는 데까지 푼 것.
    원 바이트도 함께 보므로 gzip 멤버 뒤에 붙은 평문 꼬리·gzip 앞의 머리말도 검사한다. 잘린 꼬리가 있어도 앞 멤버는 푼다."""
    parts = [data]
    at, n = data.find(_GZ_MAGIC), 0
    while at >= 0 and n < _GZ_SCAN_MAX:
        un = _gunzip_from(data, at)
        if un:
            parts.append(un)
        n += 1
        at = data.find(_GZ_MAGIC, at + 1)
    return b"\n".join(parts)


def find_canaries(data: bytes, canaries_: Iterable[Canary] | None = None, *, groups: Iterable[str] | None = None,
                  weak: bool = False) -> list[str]:
    """data(bytes — gzip 이면 풀어서) 안에서 발견한 카나리아 cid 목록(정렬). 값은 돌려주지 않는다.
    canaries_ 를 주면 그 목록 전부를, 안 주면 기본 시드 목록에서 groups·weak 조건에 맞는 것을 찾는다."""
    if canaries_ is None:
        cs = canaries(0, groups, weak=weak)
    else:
        cs = tuple(canaries_)
        if groups is not None:
            gs = set(groups)
            cs = tuple(c for c in cs if c.group in gs)
    low = _unpack(bytes(data)).lower()
    return sorted(c.cid for c in cs if any(_hit(low, p, lb, rb) for p, lb, rb in _needles(c)))


def find_canaries_in_tree(root: str | Path, canaries_: Iterable[Canary] | None = None, *,
                          groups: Iterable[str] | None = None, weak: bool = False,
                          skip_dirs: Sequence[str] = ("__pycache__",)) -> dict[str, list[str]]:
    """root 아래 모든 파일(.gz 는 풀고 .zip 은 멤버별)을 검사해 {상대 경로: [cid…]} (발견한 파일만)."""
    base = Path(root)
    cs = tuple(canaries_) if canaries_ is not None else None
    hits: dict[str, list[str]] = {}
    for p in sorted(base.rglob("*")):
        if not p.is_file() or any(part in skip_dirs for part in p.relative_to(base).parts):
            continue
        found: set[str] = set()
        if p.suffix.lower() == ".zip" and zipfile.is_zipfile(p):
            with zipfile.ZipFile(p) as z:
                for n in z.namelist():
                    found.update(find_canaries(z.read(n), cs, groups=groups, weak=weak))
        else:
            found.update(find_canaries(p.read_bytes(), cs, groups=groups, weak=weak))
        if found:
            hits[p.relative_to(base).as_posix()] = sorted(found)
    return hits
