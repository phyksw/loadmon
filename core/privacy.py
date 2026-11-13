# -*- coding: utf-8 -*-
r"""
privacy.py — AF32(AgentFinder32) 개인정보 규칙 단일원. 메일·일정만 다룬다. 같은 규칙을 네 곳에 건다:
  G1 수집 직후(g1_row·G1Writer·g1_file — §5.0 원자료 → §5.1/5.2 정제 파일) · G2 적재(extract.load_signals → sanitize·
  keyword/admin/sensitive/identifier 재확인·private_score) · G3 Copilot 직전(gate_items + gate_prompt — 실패하면 보내지 않는다) ·
  공유(ShareScrubber·scrub_shared — 공유 탭의 미리보기·보내는 내용).

G1 이 빼는 것(drop_reason — 이 순서로 첫 사유 하나만 센다):
  restricted        제한 고객(config\restricted_customers.json 의 이름·약칭·도메인 — 제목·장소·본문·범주·참여자 표시 이름과
                    주소 앞부분·참여자 도메인. 회사 형태·띄어쓰기·하이픈 변형과 글 속 맨 도메인도 맞춘다)
  private           Outlook 민감도 1·2·3(개인·비공개·기밀) · privacy.excludeCategories 범주 · privacy.excludeMailFolders 폴더 ·
                    개인 키워드(EXCLUDE ∪ privacy.excludeKeywords — 상(喪) 낱말 포함)
  admin             근태·행방(admin_hit: 근태·연차·반차·휴가·병가·조퇴·지각·외출·외근·재택·출장·건강검진·부재·OOF·휴직·특근·
                    야근·당직·결근·월차·예비군·vacation·sick leave·WFH … — 제목·장소·범주·일정 본문) ·
                    종일·한가함(0)·부재중(3)·다른 곳에서 작업(4)·취소·거절 일정
  external          사외 주소가 하나라도 보인 메일·회의(보낸이·받는이·참조·주최자·참석자)
  external_unknown  모든 주소가 사내임을 확인하지 못한 메일·회의(주소를 읽지 못함 · 사내 도메인 목록 밖은 아니지만 증명 불가)
  sensitive         건강·노조·정치·종교·성생활·범죄 경력(sensitive_hit — 공학 오탐 허용 목록은 SENSITIVE_ALLOW)
  identifier        가린 뒤에도 남은 주민·외국인등록·여권·운전면허·카드·계좌 번호(has_identifier) · 자격증명(비밀번호·인증번호 …)
G1 이 남기는 것: 날짜·시각(data\outlook 안에서만)·받은/보낸·제목·대화 제목(사람 이름은 [사람], 번호·주소는 토큰)·보낸이 가명
(p:<12hex> = HMAC-SHA256(설치 소금, 주소 또는 이름)[:12] — 소금은 PC 밖으로 나가지 않는다)·notice(공지·광고 발신 0/1).
이름·주소는 사내/사외 판별과 이름 가리기에만 메모리에서 쓰고 저장하지 않는다. 기간 안 행에서 본 이름 조각의 HMAC 해시만
'마지막으로 본 날'과 함께 data\cache\name_hashes.json 에 남겨 다음 실행·공유에서 다시 가린다(이름 자체는 없다 · 본 날 +
retention.intermediateDays 가 되면 빠진다 — prune_name_hashes). 분석마다 그 해시를 report\name_hashes_<tag>.json 에도 남겨
(snapshot_name_hashes) 결과가 남아 있는 동안(resultDays) 공유 가림과 G3 가 쓴다.
사람 이름: G1 은 본 참여자 이름을, G1·G2·G3·공유는 '이름 + 호칭'(mask_titled_names)과 남은 모든 분석의 이름 해시에 든 이름을
[사람] 으로 가린다. G3 는 그런 이름이 남은 프롬프트를 보내지 않는다. 제목 속 메일 주소는 G1·G2 에서 통째로 [이메일]
(사내·개인메일·고객사·협력사 관계 표시는 [이메일@사내] 꼴로 남긴다 — 바깥 조직의 도메인은 남기지 않는다 · fold_mail_domains).
G2(신호 글·회의 안건)는 하루 중 시각도 [시각] 으로 가린다(D10 · minimize_text).
설정 privacy.allowPatterns 는 공학 코드 표기를 가리지 않게 할 뿐, 주민·외국인등록·카드·전화·메일 주소·계좌 판정과 고객사·과제·
사람 이름 가림을 약하게 만들지 못한다(그런 번호·사전 낱말이 든 부분은 보호하지 않는다 · afcfg.allow_pattern_problem 이 넓은
식을 거른다). privacy.sensitiveFilter.allowWords 는 공학 문맥 낱말이 든 표현만 받는다(afcfg.allow_word_problem).

불변식
  · 멱등 — sanitize(sanitize(x)) == sanitize(x). 기존 토큰은 보호 구간이라 토큰 안 숫자를 다시 잡지 않는다.
  · 결정적 — 난수·시각 없음(가명은 소금으로만 정해진다). 정제 함수는 원문을 출력·기록하지 않는다(건수만).
  · 실패하면 닫는다 — gate_items·gate_prompt 는 판단할 수 없으면(제한 고객 목록 없음 등) 보내지 않는다.
  · 표준 라이브러리만.
"""
from __future__ import annotations

import calendar
import csv
import functools
import hashlib
import hmac
import io
import ipaddress
import json
import os
import re
import sys
import time
import unicodedata

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
import afcfg  # noqa: E402

RULES_VER = "af32.3"          # 규칙(정규식·어휘·순서)을 바꾸면 올린다 — privacy_audit.json·collect_summary 에 남는다
#                               af32.2: 제목 속 바깥 도메인 메일 토큰 → [이메일] · 개인 주제어 내장 목록 = 배포 기본 목록
#                               af32.3: 호칭 이름 규칙(2자 이름·이사·상무·전무·사장·대표) · 표시 이름의 모든 조각 · 주민 꼴 13자리(체크섬
#                                       없이 — 바로 앞 공학 문맥만 뺀다) · +82 유선 · '.'·'/' 로 끊은 카드 · 근태·행방·건강 낱말 ·
#                                       상(喪) 낱말 · 제한 고객의 회사 형태·띄어쓰기·맨 도메인·참여자 표시 이름·주소 앞부분 · 이름 해시 기한
MAX_SCAN = 4000               # 한 필드에서 보는 최대 글자 수(병적 입력 방어)

# 내장 개인 주제어 — mail·일정 제목·장소·본문에 쓰인다. excluded_keywords(cfg) 가 privacy.excludeKeywords 와 합친다.
# 배포 기본 목록(afcfg.DEFAULTS privacy.excludeKeywords)을 모두 담는다 — 설정은 더하기만 한다(D3 · D22).
# 상(喪) 낱말(부친상·모친상 …)은 가족의 일이라 사적이다(경조 일정 — 업무가 아니다).
# (LM30 의 경로 전용 토큰 downloads·temp·임시·공부·인강은 파일 수집이 없어져 뺐다)
EXCLUDE = ["개인", "사생활", "가족", "취미", "이력서", "면접", "취준", "자소서", "이직", "병원", "의료", "보험", "연말정산",
           "자격증", "부친상", "모친상", "빙부상", "빙모상", "조부상", "조모상", "시부상", "시모상", "장모상"]

# ── 단계 0 정규화 ─────────────────────────────────────────────────────────────────
#   제어 문자·줄/문단 구분자·사설 영역(자리표시자 주입 방어) → 공백, 서식 문자(폭 0·소프트 하이픈 등) → 삭제,
#   대시류 → '-'(자동 서식 ' – '·비분리 하이픈으로 쓴 전화·주민·카드 번호 탐지)
CTRL_RX = re.compile("[\x00-\x08\x0b-\x1f\x7f-\x9f  -]")
FORMAT_RX = re.compile("[­؀-؅؜۝܏࢐࢑࣢᠎​-‏‪-‮"
                       "⁠-⁤⁦-⁯﻿￹-￻\U000110bd\U000110cd\U00013430-\U0001343f"
                       "\U0001bca0-\U0001bca3\U0001d173-\U0001d17a\U000e0001\U000e0020-\U000e007f]")
DASH_RX = re.compile("[‐-―−﹘﹣－]")

# ── 공통 경계 ─────────────────────────────────────────────────────────────────────
NB = r"(?<![0-9A-Za-z])"                    # 앞에 영숫자 없음
NA = r"(?![0-9A-Za-z])"                     # 뒤에 영숫자 없음
NBX = r"(?<![0-9A-Za-z\-./\\])"             # 코드 일부가 아님(DWG-2026-… 차단). '_' 는 파일명 구분자로 허용
NAX = r"(?![0-9A-Za-z]|[-/][0-9A-Za-z]|\.(?![A-Za-z]{2,5}(?![0-9A-Za-z]))[0-9A-Za-z])"  # .pdf 같은 확장자는 허용
NBP = r"(?<![0-9A-Za-z+/\\\-])"             # 전화용 앞 경계('.'·':'·'('·'_' 허용 → Tel.010…, 견적_010…)
NAP = r"(?![0-9A-Za-z]|-\d)"                # 전화용 뒤 경계

# ── 토큰 문법 — 이 정규식에 맞는 문자열만 '기존 토큰'으로 보호한다(멱등) ─────────────────
TOKEN_RX = re.compile(
    r"\[(?:주민번호|외국인등록번호|생년월일|카드|전화|사업자번호|법인번호|여권|운전면허|계좌|IP|URL|경로|금액|비율|회사|나"
    r"|사람(?:#[0-9a-f]{6})?|(?:고객사|협력사|과제)(?::[A-Za-z0-9_\-]{1,16})?|시각"
    r"|이메일(?:@[A-Za-z0-9.\-:가-힣]{1,64})?)]")
PERSON_TAG_RX = re.compile(r"\[사람#[0-9a-f]{6}\]")      # LM27 식 사람 태그 — G3 에서 [사람] 으로 통일

# ── 보호 구간(탐지 전에 자리표시자로 가림) — 날짜·시각·버전·규격 ─────────────────────
PROTECT = [
    ("date", re.compile(NB + r"(?:19|20)\d{2}([-./])(?:0?[1-9]|1[0-2])\1(?:0?[1-9]|[12]\d|3[01])" + NA)),
    ("date8", re.compile(NB + r"(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])" + NA)),
    ("time", re.compile(NB + r"(?:[01]?\d|2[0-3]):[0-5]\d(?::[0-5]\d)?" + NA)),
    ("version", re.compile(r"(?i)(?:(?<![A-Za-z])(?:rev|ver|version|v|build|fw|sw|release)[._\s-]?"
                           r"|(?:버전|빌드|펌웨어|릴리스|개정)[_\s]?)\d+(?:\.\d+){1,3}")),
    ("std", re.compile(r"(?<![A-Za-z])(?:IEC|ISO|IEEE|KS\s?[A-Z]?|JIS|ASTM|MIL-STD|UL|EN|CISPR|SAE|JEDEC|IPC)"
                       r"[\s-]?\d{2,6}(?:[-.:]\d{1,4})*")),
]

# ── 자격증명(하나라도 걸리면 행 폐기) ───────────────────────────────────────────────
CRED_KV = re.compile(
    r"(?i)(?:비밀번호|비번|패스워드|암호|password|passwd|pwd|pw|passcode)\s*(?:[:=：]|은|는|is)\s*(?P<v>[^\s,;]{4,64})")
CRED_PIN = re.compile(r"(?i)(?<![A-Za-z])pin\s*(?:[:=：]|은|는|is)\s*\d{4,8}(?![0-9A-Za-z])")   # PIN 은 숫자 값만
CRED_OTP = re.compile(r"(?i)(?:인증\s?번호|인증\s?코드|보안\s?코드|otp|verification\s?code)\s*(?:[:=：]|은|는|is)?\s*\[?\d{4,8}\]?")
CRED_TOKEN = re.compile(
    r"(?:eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}"
    r"|-----BEGIN (?:RSA |EC |OPENSSH |DSA |ENCRYPTED )?PRIVATE KEY-----"
    r"|(?<![A-Za-z0-9])AKIA[0-9A-Z]{16}(?![A-Za-z0-9])"
    r"|(?<![A-Za-z0-9])gh[pousr]_[A-Za-z0-9]{36}(?![A-Za-z0-9])"
    r"|(?<![A-Za-z0-9])xox[abprs]-[A-Za-z0-9\-]{10,}"
    r"|(?i:bearer)\s+[A-Za-z0-9_\-.=]{20,})")
CRED_APIKEY = re.compile(
    r"(?i)(?:api[_\-]?key|secret|access[_\-]?key|client[_\-]?secret|token|private[_\-]?key|connection\s?string)"
    r"\s*[:=：]\s*['\"]?(?P<v>[A-Za-z0-9_\-+/=.]{12,})")
CRED_STOP = re.compile(
    r"^(?:[가-힣]+|reset|change|changed|expired|expire|policy|required|update|updated|변경|재설정|초기화|만료|정책)$", re.I)


def _cred_value_ok(v):
    """값처럼 보이면 True: 한글뿐·불용어가 아니고 (숫자 or 기호 or 대소문자 혼합) — '비밀번호 변경 안내' 통과."""
    if CRED_STOP.match(v):
        return False
    has_digit = any(c.isdigit() for c in v)
    has_sym = any(not c.isalnum() for c in v)
    mixed = any(c.isupper() for c in v) and any(c.islower() for c in v)
    return has_digit or has_sym or mixed


def credential_hit(text):
    for m in CRED_KV.finditer(text):
        if _cred_value_ok(m.group("v")):
            return True
    return bool(CRED_PIN.search(text) or CRED_OTP.search(text) or CRED_TOKEN.search(text)
                or CRED_APIKEY.search(text))


# ── 문맥 사전 · 억제 문맥 ──────────────────────────────────────────────────────────
CTX = {
    "rrn": r"(?:주민|생년월일|외국인\s?등록|등록번호|resident)",
    "card": r"(?:카드|card|결제|신용|체크|visa|master|amex)",
    "brn": r"(?:사업자|등록번호|거래처|법인|business\s?(?:no|number|registration))",
    "corp": r"(?:법인\s?등록|법인번호)",
    "passport": r"(?:여권|passport|비자|visa|출입국|출국|입국|항공권|발권|e-?ticket|탑승)",
    "license": r"(?:면허|운전|license|licence|driver)",
    "account_strong": r"(?:계좌|입금|송금|이체|예금주|account\s?(?:no|number|#)|acct)",
    "account_weak": r"(?:은행|뱅크|bank|농협|수협|신협|새마을금고|우체국|증권|국민은행|우리은행|하나은행|신한은행|기업은행|SC제일|씨티)",
    "ip": r"(?:ip|서버|server|host|호스트|접속|주소|address|vpn|ssh|rdp|ping|gateway|게이트웨이|dns|http|ftp|방화벽|firewall)",
    "phone_rep": r"(?:대표|고객센터|콜센터|상담|문의|전화|tel|☎|call)",
    "money": r"(?:수주|계약|견적|단가|매출|매입|발주|입찰|투찰|낙찰|네고|금액|가격|비용|예산|대금|원가|판가|공급가|부가세|vat|price"
             r"|cost|quote|quotation|amount|revenue|budget|invoice|인보이스|(?<![A-Za-z])PO(?![A-Za-z]))",
}
# 공학·식별 억제 문맥: 후보 바로 앞 10자 안에 있으면 문맥 게이트형 탐지(유선·대표·카드·계좌·여권·면허 …)를 하지 않는다
ENG_CTX = re.compile(r"(?i)(?:문서\s?번호|도면|도번|dwg|부품|품번|p/?n|s/?n|시리얼|serial|lot|로트|관리\s?번호|접수\s?번호"
                     r"|과제\s?번호|eco|ecn|품목|코드|code|모델|model|rev|ver|(?<![a-z])(?:ean|gtin|upc|isbn)(?![a-z]))")
ID_BEFORE = re.compile(r"(?i)(?:(?<![A-Za-z])(?:po|pr|so|no|order)|오더|번호|코드|#)\s*[:.#]?\s*$")
# 주민 꼴 13자리를 주문·발주 번호로 보는 바로 앞 표기(PO·SO·Order·오더·#) — '번호'·'No.' 는 넣지 않는다(주민번호 칸에도 쓴다)
ORDER_BEFORE = re.compile(r"(?i)(?:(?<![A-Za-z])(?:po|pr|so|order)|오더|#)\s*[:.#]?\s*$")
ENG_UNIT_AFTER = re.compile(
    r"(?i)^\s?(?:mm|cm|um|μm|µm|nm|km|m|mil|inch|in|kg|mg|g|ton|t|kn|n|mpa|kpa|gpa|pa|bar|psi|kv|mv|v|ma|ua|a|mw|kw|w|kwh|wh|mah|ah|"
    r"ghz|mhz|khz|hz|rpm|°c|°f|℃|k|%|ppm|ppb|dbm|db|lux|lx|lm|cd|ea|pcs|set|lot|px|dpi|fps|ms|us|μs|ns|sec|s|min|hrs|hr|h|"
    r"tb|gb|mb|kb|gbps|mbps|bps|bit|cells|cell|nodes|elements|cycles|times|"
    r"개|대|매|장|셀|노드|요소|회|번|건|명|시간|분|초|일|주|개월|년|층|차|호|점|줄|행|열|쪽|페이지|화소|세트)(?![A-Za-z가-힣])")
COUNT_AFTER = re.compile(r"^\s?(?:회|개|셀|화소|명|건|대|장|매|시간|번|세트|ea|pcs|km|rpm|cycles|대수|가지|종|개소|라인)", re.I)
DIM_NEAR = re.compile(r"^\s?[xX×*]\s?\d|(?:[xX×*])\s?$")      # 1,200 x 800 같은 치수


# ── 체크섬 ──────────────────────────────────────────────────────────────────────
def luhn_ok(d):
    total, alt = 0, False
    for ch in reversed(d):
        n = int(ch)
        if alt:
            n *= 2
            if n > 9:
                n -= 9
        total += n
        alt = not alt
    return total % 10 == 0


def rrn_checksum_ok(d13):
    """주민번호 체크섬 — 2020-10 이후 발급분은 안 맞을 수 있어 '가점'으로만 쓴다."""
    w = [2, 3, 4, 5, 6, 7, 8, 9, 2, 3, 4, 5]
    s = sum(int(a) * b for a, b in zip(d13[:12], w, strict=False))
    return (11 - s % 11) % 10 == int(d13[12])


def brn_ok(d10):
    """사업자등록번호 체크섬."""
    w = [1, 3, 7, 1, 3, 7, 1, 3, 5]
    s = sum(int(a) * b for a, b in zip(d10[:9], w, strict=False)) + (int(d10[8]) * 5) // 10
    return (10 - s % 10) % 10 == int(d10[9])


def rrn_date_ok(d):
    """앞 6자리 생년월일 + 7번째 성별자리(1~8) 유효성 — 13월·성별 9 는 주민번호가 아니다."""
    yy, mm, dd, g = int(d[0:2]), int(d[2:4]), int(d[4:6]), int(d[6])
    if not 1 <= g <= 8:
        return False
    year = (1900 if g in (1, 2, 5, 6) else 2000) + yy
    if not 1 <= mm <= 12:
        return False
    return 1 <= dd <= calendar.monthrange(year, mm)[1]


def _order_before(t, s):
    """t 의 s 바로 앞(8자)이 주문·발주 번호 표기(PO·SO·Order·오더·#)인가."""
    return ORDER_BEFORE.search(t[max(0, s - 8):s]) is not None


def _eng_before(t, s):
    """t 의 s 바로 앞(10자)에 공학·식별 문맥(도번·P/N·LOT·코드 …)이 있는가."""
    return ENG_CTX.search(t[max(0, s - 10):s]) is not None


# ── 탐지기 표 ───────────────────────────────────────────────────────────────────
RX = {
    "birth": re.compile(
        r"(?i)(?:생년월일|출생일|출생|date\s?of\s?birth|birth\s?date|dob)\s*[:：]?\s*(?P<d>(?:19|20)?\d{2}\s?[-./년]\s?"
        r"(?:0?[1-9]|1[0-2])\s?[-./월]\s?(?:0?[1-9]|[12]\d|3[01])\s?일?|(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])"
        r"|\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01]))(?![0-9])"),
    "rrn_front": re.compile(r"(?:주민|주민등록|주민번호)[^\d\n]{0,8}(?P<d>\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01]))(?![0-9\-–—*])"),
    "rrn": re.compile(NB + r"\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])(?P<sep>\s?[-–—]\s?|\s?)[1-8]\d{6}" + NA),
    "rrn_masked": re.compile(NB + r"\d{6}\s?[-–—]\s?[1-8](?:[*xX●○■]{6}|\d[*xX●○■]{5})"),
    "card16": re.compile(NB + r"(?:\d{4}(?:\s?[-./]\s?|\s)?){3}\d{4}" + NA),
    "card15": re.compile(NB + r"3[47]\d{2}(?:\s?[-./]\s?|\s)?\d{6}(?:\s?[-./]\s?|\s)?\d{5}" + NA),
    "card_masked": re.compile(NB + r"\d{4}(?:\s?-\s?|\s)?(?:[*xX●]{4}(?:\s?-\s?|\s)?){2}\d{4}" + NA),
    "mobile": re.compile(NBP + r"(?:(?:\+|00)82[-.\s]?(?:\(0\))?\s?1[016789]|01[016789])\s?[-.\s)]{0,2}\d{3,4}\s?[-.\s]{0,2}\d{4}"
                         + NAP),
    "landline": re.compile(NBP + r"\(?0(?:2|3[1-3]|4[1-4]|5[1-5]|6[1-4]|70|50[2-8])\)?\s?[-.\s)]{1,2}\d{3,4}\s?[-.\s]\s?\d{4}"
                           + NAP),
    # +82 유선(국가 번호를 붙인 지역 번호 — 앞 0 은 빼거나 (0) 으로 쓴다). 국가 번호가 있으면 공학 문맥과 헷갈리지 않는다
    "landline82": re.compile(r"(?<![0-9A-Za-z+])(?:\+|00)82[-.\s]?(?:\(0\)\s?|0)?\(?(?:2|3[1-3]|4[1-4]|5[1-5]|6[1-4]|70"
                             r"|50[2-8])\)?\s?[-.\s)]{1,2}\d{3,4}\s?[-.\s]\s?\d{4}" + NAP),
    "rep": re.compile(NBP + r"1(?:5[4-9]\d|6[0-9]\d|8[0-9]\d)-\d{4}" + NAP),
    "intl": re.compile(r"(?<![0-9A-Za-z])\+(?!82)\d{1,3}[-.\s]?\(?\d{1,4}\)?(?:[-.\s]?\d{2,4}){2,3}" + NA),
    "brn": re.compile(NBX + r"\d{3}-\d{2}-\d{5}" + NAX),
    "brn_bare": re.compile(NBX + r"\d{10}" + NAX),
    "corp": re.compile(NBX + r"\d{6}-\d{7}" + NAX),
    "passport": re.compile(NBX + r"[MSRODG]\d{3}[A-Z0-9]\d{4}" + NAX),
    "license": re.compile(NBX + r"(?:1[1-9]|2[0-8])-?\d{2}-?\d{6}-?\d{2}" + NAX),
    "license_region": re.compile(r"(?:서울|부산|경기|강원|충북|충남|전북|전남|경북|경남|제주|대구|인천|광주|대전|울산)\s?\d{2}-\d{6}-\d{2}" + NAX),
    "account_hy": re.compile(NBX + r"\d{2,6}(?:-\d{2,7}){1,4}" + NAX),
    "account_bare": re.compile(NBX + r"\d{10,16}" + NAX),
    "ipv4": re.compile(r"(?<![0-9A-Za-z.])(?:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)"
                       r"(?P<port>:\d{2,5})?(?![0-9A-Za-z]|\.\d)"),
    "ipv6": re.compile(r"(?<![0-9A-Za-z:])(?:[0-9A-Fa-f]{0,4}:){2,7}[0-9A-Fa-f]{0,4}(?![0-9A-Za-z:])"),
    "url": re.compile(r"(?i)\b(?:https?|ftp)://[^\s<>\"'\]\)]+|\bwww\.[A-Za-z0-9\-]+\.[^\s<>\"'\]\)]+"),
    "email": re.compile(r"(?<![A-Za-z0-9._%+\-])[A-Za-z0-9._%+\-]{1,64}@(?P<dom>[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,24})"
                        r"(?![A-Za-z0-9\-])"),
    # 경로: 드라이브·UNC 머리 + 디렉터리 부분(마지막 구분자까지)만 맞춘다 — 기본 이름은 글에 남고 '[경로]\' 뒤에 붙는다
    "path": re.compile(
        r"\\\\\\\\[A-Za-z0-9._\-$]+\\\\(?:[^\\/:*?\"<>|\r\n]+\\\\)*"
        r"|\\\\[A-Za-z0-9._\-$]+\\(?:[^\\/:*?\"<>|\r\n]+[\\/](?![\\/]))*"
        r"|(?<![A-Za-z0-9])[A-Za-z]:\\\\(?:[^\\/:*?\"<>|\r\n]+\\\\)*"
        r"|(?<![A-Za-z0-9])[A-Za-z]:\\(?![\\/])(?:[^\\/:*?\"<>|\r\n]+[\\/](?![\\/]))*"
        r"|(?:file:/{2,3})?(?<![A-Za-z0-9])[A-Za-z]:/(?![\\/])(?:[^\\/:*?\"<>|\r\n]+/(?![\\/]))+"),
    # 금액(M1~M6)
    "money_cur": re.compile(
        r"(?:₩|\$|€|¥|£|(?<![A-Za-z])(?:KRW|USD|US\$|EUR|JPY|CNY|RMB|GBP)(?![A-Za-z]))\s?\d[\d,]{0,24}(?:\.\d+)?"
        r"(?:\s?(?:[KMB](?![A-Za-z])|천만|백만|십만|천|만|억|조|million|billion|mil|bn)(?![A-Za-z]))?"
        r"|\\\d{1,3}(?:,\d{3})+"),
    "money_kor": re.compile(
        NB + r"\d[\d,]{0,24}(?:\.\d+)?\s?(?:조|억|천만|백만|십만|만|천)(?:\s?\d[\d,]{0,24}(?:\.\d+)?\s?(?:억|천만|백만|십만|만|천))*"
        r"(?P<cur>\s?(?:원|달러|유로|엔|위안))?"),
    "money_suffix": re.compile(
        NB + r"(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s?(?:원|달러|유로|엔|위안|파운드|USD|KRW|EUR|JPY|CNY)"
        r"(?=$|[^가-힣A-Za-z0-9]|(?:이|은|을|의|에|으로|과|와|도|씩|대|선|짜리|정도|가량|까지|부터|이며|이고|입니다|이다|임)(?![가-힣]))"),
    "money_kw_adj": re.compile(
        r"(?i)(?P<kw>단가|금액|가격|견적가|공급가|판가|원가|계약금|대금|매출|수주액|수주\s?금액|price|amount|cost)\s*"
        r"(?:[:：=]|은|는|이|가|도)?\s*(?P<num>\d[\d,]{0,24}(?:\.\d+)?)" + NA),
    "money_bare": re.compile(NBX + r"(?:\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d{4,}(?:\.\d+)?)" + NAX),
    "rate": re.compile(r"(?i)(?P<kw>할인율|할인|인하율|인하|네고율|마진율|마진|이익률|dc|discount|margin)\s*(?:[:：=]|은|는|을|를)?\s*"
                       r"(?P<num>\d+(?:\.\d+)?\s?%)"),
    "company": re.compile(
        r"(?:\(주\)|\(유\)|\(재\)|\(사\)|주식회사|유한회사)\s?[가-힣A-Za-z0-9&]{2,20}|[가-힣A-Za-z0-9&]{2,20}\s?(?:\(주\)|주식회사)"
        r"|[A-Z][A-Za-z0-9&]{1,20}(?:\s[A-Z][A-Za-z0-9&]{1,20}){0,2},?\s(?:Co\.,?\s?Ltd\.?|Inc\.|Corp\.|GmbH|LLC|Ltd\.)"),
}

# ── 이름(멘션·라벨·호칭) ─────────────────────────────────────────────────────────────
SURNAMES = ("김이박최정강조윤장임한오서신권황안송류유전홍고문양손배백허남심노하곽성차주우구민진나지엄채원천방공현함변염여추도소석선설마"
            "길연위표명기반라왕금옥육인맹제모탁국어은편용예경봉사부가복태목형피두감음빈동온호범좌팽승간상시갈단견당화창")
COMPOUND_SURNAMES = ("남궁", "황보", "제갈", "선우", "독고", "사공", "서문", "동방")
TITLES = (r"(?:님|씨|책임|선임|수석|매니저|프로|팀장|파트장|그룹장|실장|센터장|본부장|부장|차장|과장|대리|사원|주임|연구원|위원|박사"
          r"|교수|이사|상무|전무|사장|대표|님께)")
TITLE_WORDS = frozenset(TITLES[3:-1].split("|"))
NAME_STOP = {"이번주", "지난주", "다음주", "이번달", "지난달", "다음달", "이번에", "우리측", "고객사", "협력사", "공급사", "제조사", "주관사",
             "발주처", "수요처", "담당자", "책임자", "관계자", "작성자", "검토자", "승인자", "요청자", "참석자", "사용자", "관리자", "운영자",
             "여러분", "선생님", "전체팀", "각부서",
             # LM28: 성씨 글자로 시작하는 3자 업무어(호칭형 오탐 방지)
             "안전성", "신뢰성", "정확성", "생산성", "효율성", "가능성", "필요성", "중요성", "안정성", "유효성", "적합성", "기술팀",
             "대상자", "수신자", "발신자", "참조자", "상대방", "연구소", "본사측", "고객님", "구매팀", "품질팀", "개발팀", "설계팀",
             "전원이", "모두가", "각자가", "한국측", "주관부", "시험소", "인증원", "평가원", "공사측"}
NAME_SUFFIX_STOP = ("팀", "측", "처", "실")
HONORIFIC = re.compile(r"(?<![가-힣])(?P<name>[가-힣]{2,4})\s?(?=" + TITLES
                       + r"(?:[^가-힣]|$|께|이|은|는|과|와|의|도|한테|에게|님))")
MENTION = re.compile(r"@(?P<name>[가-힣]{2,4}|[A-Za-z][A-Za-z.\-]{1,30})(?=[\s,.:)!?]|$)")
LABELED_NAME = re.compile(r"(?:예금주|성명|이름|수신인|받는\s?분|보내는\s?분|작성자|담당자)\s*[:：]?\s*(?P<name>[가-힣]{2,4})(?![가-힣])")


def plausible_korean_name(n):
    """호칭형 후보가 사람 이름으로 그럴듯한가: 3자 + 흔한 성, 또는 4자 + 복성. 일반어·조직 접미 제외."""
    if n in NAME_STOP or n.endswith(NAME_SUFFIX_STOP):
        return False
    if len(n) == 3 and n[0] in SURNAMES:
        return True
    return len(n) == 4 and n[:2] in COMPOUND_SURNAMES


# 호칭 바로 앞에 오지만 사람 이름이 아닌 낱말 — 성씨 글자로 시작하는 업무어·부서·장소·나라·공학 낱말·가족 호칭('공장 이사'·
# '양산 책임'·'하중 대표'·'선생님'·'시스템 책임' …). NAME_PART_STOP(이름 조각과 겹치는 업무어)·NAME_STOP·_NAME_ORG_STOP·직함·
# GENERIC_WORK(흔한 업무어)와 함께 본다(_titled_stop). 여기 없는 낱말은 호칭 앞에서 [사람] 이 될 수 있다(가리는 쪽이 안전하다).
TITLED_STOP = frozenset("""
공장 공동 공급 공사 공무 공업 공학 공용 공식 공정 부서 부문 부품 부사 사업 사옥 사무 사내 사외 사장 사모 창고 현업 현장 기획 기업 기존 기사 기간 기관 전임 전산 전체 전사 전담 전문 전장
명예 심사 감사 선행 선생 선박 노조 노무 장기 장모 조달 조립 조직 조카 조정 홍보 경영 경리 제조 제작 구조 구역 인증 인프라 양산 양측 신규 신임 신사 고문 고모 이모 어머 차량 주관 주요 주무
주간 민원 진단 지사 지점 지역 지부 채용 원청 원장 추진 도장 소방 소장 라인 금형 모듈 모델 국내 국외 용접 예산 가공 음향 동력 동기 온도 상품 상생 상담 시설 시공 시험 단말 당사 화학 하청
우수 우리 정부 정비 장비 설비 성과 손익 배송 백업 허가 남부 북부 서부 동부 중부 표준 위원 대외 대내 대리 반장 반도체 연구 연구소 오늘 차기 차장 임시 임원 마감 마케팅 문의 한국 유럽 인도
서울 인천 천안 창원 구미 이천 용인 여수 전주 원주 제주 경기 강원 경북 경남 전북 전남 부산 지방 지구 권역 국가 국제 국산 국책 국방 국장 단장 조장 조원 여사 선배 동료 지인 주주 양사 고객
전원 전부 전국 인원 인력 인턴 신입 경력 정규 정식 정책 정밀 정전 정격 정지 정확 정품 하자 배상 연대 설명 사후 사전 사회 사고 사건 사례 사실 사유 사진 사번 사규 도의 도급 도입 도출 도달
도착 도로 도금 도료 도전 도움 도시 도서 감독 감리 감소 감량 감면 감시 감지 감도 감속 감압 감안 위임 위탁 위반 위험 위기 위치 위상 위성 위생 형사 형상 형번 형태 형성 민사 민간 민감 최초
최고 최대 최소 최근 최적 최저 이번 이전 이후 이상 이하 이동 이관 이송 이용 이행 이중 이름 이익 이월 이론 이외 이내 오전 오후 오차 오더 오픈 오일 오염 금주 금월 금년 금일 금액 금속 금융
금지 차주 차월 차년 차체 차종 차수 차이 차단 전월 전년 전면 전후 전용 전시 전개 전제 전망 전표 전화 전환 전압 전류 전력 전선 전극 전지 전파 당월 당초 당장 당해 당기 당직 연말 연초 연동
연결 연계 연락 연장 연기 연봉 연습 연료 연소 연비 연산 연속 연식 연합 연휴 연도 연마 주말 주초 주차 주소 주제 주의 주행 주변 주식 주력 주도 주최 주조 주입 하중 하부 하단 하위 하루 하계
진동 진공 진척 진도 진입 진출 진급 진로 소음 소형 소모 소비 소요 소개 소속 소집 소송 소급 소결 소성 소진 유량 유속 유압 유체 유통 유무 유의 유입 유출 유연 유닛 유저 유효 유관 유사 강도
강성 강판 강재 강화 강제 강의 강사 강당 경도 경로 경계 경과 경비 경상 경량 경사 경유 경향 경보 경위 경험 경쟁 경제 인장 인쇄 인식 인가 인근 인구 인재 인지 인용 인입 인출 인계 인하 인상
변형 변위 변속 변압 변동 변화 신호 신뢰 신고 신속 신차 신형 신설 신용 신분 신체 신년 용량 용도 용어 용역 용기 용해 용융 용지 용품 가격 가능 가동 가정 가입 가설 가속 가열 가압 가스 가상
가중 가점 가족 가구 가전 배선 배관 배치 배열 배기 배출 배경 배분 배정 배수 구동 구분 구축 구현 구입 구두 구체 구형 제동 제공 제한 제외 제거 제도 제정 제재 제시 제원 제반 제휴 제약 제철
제강 제습 조향 조명 조작 조합 조기 조별 조성 조업 조선 방열 방수 방진 방음 방전 방산 방송 방어 방화 방식 방향 방침 방문 방지 기구 기어 기판 기기 기능 기본 기초 기반 기여 기대 기회 기후
기온 기압 기체 기포 기종 기성 기밀 기재 기입 기동 기둥 기념 기부 모터 모드 모형 모집 모음 모양 모재 모의 사출 성형 성분 성적 성공 성격 성립 마모 마찰 마진 마을 마력 피로 피치 피해 피크
피복 피막 피팅 표면 표기 표현 표본 표지 표적 표제 표결 단면 단자 단품 단열 단위 단종 단독 단순 단기 단선 단락 단조 단체 단지 단속 단축 단차 단일 단점 단어 단서 부하 부식 부착 부가 부담
부당 부결 부록 부속 부여 부대 부스 부팅 부피 부호 부분 부족 부재 원료 원단 원격 원칙 원래 원활 원점 원형 원소 원리 원안 원문 화면 화질 화소 화상 화재 화물 화력 화공 화합 화해 음성 음량
음식 음료 음원 음영 시료 시편 시방 시간 시기 시한 시행 시도 시세 시황 시청 시각 시야 시선 시급 시내 시외 시중 시효 시정 시사 시상 시범 시가 시차 고장 고압 고온 고속 고정 고급 고가 고려
고지 고시 고용 고유 고도 고충 고민 장치 장착 장력 장애 장소 장점 장부 장면 장래 안건 안정 안쪽 안팎 송신 송풍 송전 송금 송장 임무 임대 임차 임금 임의 임계 임상 한글 한계 한도 한정 한편
한번 한쪽 한전 서류 서명 서면 서술 서브 권한 권장 권고 권리 권선 황색 황동 윤활 윤리 박스 박막 박판 문자 문항 문구 문안 문화 양쪽 양면 양호 양품 양도 양수 손상 손실 손해 백색 백서 허용
허브 남은 남미 심의 심화 심층 노동 노력 노출 노후 노드 노트 우선 우편 우회 우려 나사 나중 지시 지침 지출 지속 지정 지식 지금 지도 지름 지면 지주 채널 채택 채권 채무 채움 천장 함수 함량
염색 염분 염수 여부 여유 여건 여름 여신 여비 여행 여성 여분 여기 추적 추세 추천 추후 추석 추론 석유 석탄 석사 석식 선택 선별 선발 선적 선급 선수 선로 선반 선형 선도 선물 선언 선거 선결
선착 설문 설립 설득 설날 길이 명단 명세 명칭 명령 명확 명시 명의 명절 명판 명함 명암 반복 반품 반출 반입 반송 반납 반대 반응 반기 반환 반경 반사 라벨 왕복 옥외 옥내 옥상 육안 육성 육상
탁상 탁월 어제 어느 은행 은퇴 편의 편차 편성 편람 편입 편도 예정 예약 예비 예상 예외 예방 예시 예제 예고 예열 봉인 봉사 봉급 복구 복사 복합 복수 복지 복귀 복원 복제 복잡 복도 복리 태도
태양 태그 태풍 목적 목차 목업 목재 두께 두뇌 빈칸 동작 동향 동시 동일 동의 동반 동참 동결 동선 동봉 동급 동계 동종 동판 동축 동조 동적 온수 온실 호환 호출 호기 호스 호선 호칭 호텔 호황
호실 호소 범용 범례 범주 범퍼 범죄 좌표 좌석 좌측 좌우 팽창 승급 승진 승격 승차 승강 승용 승계 승부 간섭 간격 간접 간이 간략 간단 간부 간사 간행 간판 간호 상세 상위 상부 상단 상향 상황
상시 상용 상장 상사 상관 상대 상이 상승 상온 상한 상하 상차 상주 상속 상표 상가 상권 상임 상징 갈등 견본 견해 견인 견학 견고 창구 창업 창립 창의 창작 창출 시스템 서비스 모바일 배터리 원자재
부자재 기자재 기숙사 사무소 사업장 작업장 신사옥 신공장 제조물 도의적 사회적 신제품 신기술 신사업 차세대 반제품 소모품 예비품 시제품 양산품 주무관 변호사 노무사 감리사 기술사 설계사 정비사 임직원
한국어 이사회 위원회 조합원 노조원 연구회 간담회 설명회 공청회 전시회 박람회 동호회 송년회 신년회 하반기 상반기 성수기 주파수
모니터 노트북 마우스 이어폰 서피스 라우터 어댑터 공유기 모뎀 소나타
""".split())
# 호칭 낱말이 보통 낱말로 쓰인 자리 — '대표 모델·대표 조건'(으뜸·본보기), '책임 소재·책임 범위'. 그 앞 낱말은 사람 이름이 아니다
_TITLE_COMMON_RX = re.compile(
    r"대표\s?(?:조건|모델|사양|지표|특성|시료|샘플|도면|번호|사례|이미지|과제|제품|부품|품목|곡선|파형|단면|형상|치수|규격|항목|유형"
    r"|기종|차종|공정|라인|설비|모드|주파수|데이터|결과|증상|불량|원인|기능|성능|구조|물성|재질|색상|기술|전화|메일|주소|계정)"
    r"|책임\s?(?:소재|범위|한계|구역|분담|회피|전가|추궁|보험|부서|기간|조항|제한|면제|여부|이행|감리|기술사)")


def _titled_stop(n):
    """호칭 앞 낱말 n 이 사람 이름이 아닌 보통 낱말인가 — 업무어·부서·장소·조직·직함 목록과 조직 접미(팀·측·처·실)."""
    return (n in TITLED_STOP or n in NAME_PART_STOP or n in NAME_STOP or n in TITLE_WORDS or n in _NAME_ORG_STOP
            or n in GENERIC_WORK or n.endswith(NAME_SUFFIX_STOP))


def plausible_titled_name(n):
    """호칭(책임·님·이사 …) 바로 앞 한글 2~4자가 사람 이름으로 그럴듯한가 — 3자(흔한 성)·4자(복성)·2자(성 + 외자 · 성씨 글자로
    시작하는 이름)이고 업무어·직함·부서·장소 낱말(_titled_stop)이 아닐 때만."""
    if _titled_stop(n):
        return False
    if len(n) == 2:
        return n[0] in SURNAMES
    return plausible_korean_name(n)


def _titled_name_ok(m):
    """HONORIFIC 에 맞은 자리 m 이 '사람 이름 + 호칭' 인가 — 이름이 그럴듯하고(plausible_titled_name) 호칭 낱말이 보통 낱말로 쓰인
    자리('대표 모델'·'책임 소재' — _TITLE_COMMON_RX)가 아니다."""
    return plausible_titled_name(m.group("name")) and _TITLE_COMMON_RX.match(m.string, m.end()) is None


def titled_names(text):
    """글 속 '이름 + 호칭' 꼴의 이름(그럴듯한 것만 — _titled_name_ok) 목록. 가린 토큰 안은 보지 않는다."""
    return [m.group("name") for m in HONORIFIC.finditer(str(text or "")) if _titled_name_ok(m)]


def mask_titled_names(text):
    """'이름 + 호칭' 꼴의 이름 → [사람](호칭은 남긴다) — G1·G2·G3·공유가 같은 규칙(_titled_name_ok)을 쓴다."""
    s = str(text or "")
    if not s:
        return s

    def rep(m):
        if not _titled_name_ok(m):
            return m.group(0)
        s0, e0 = m.span("name")
        return m.group(0)[:s0 - m.start()] + "[사람]" + m.group(0)[e0 - m.start():]
    return HONORIFIC.sub(rep, s)


# 공용 개인 메일 도메인(단일원 afcfg — 사내 도메인이 될 수 없다) · Copilot 관문(G3)에서 '잔여 시 행 제외'인 고위험 범주
PERSONAL_MAIL_DOMAINS = afcfg.PERSONAL_MAIL_DOMAINS
HIGH = frozenset({"rrn", "frn", "birth", "card", "passport", "license", "account", "phone", "email", "cred", "brn", "corp"})
_DOMAIN_RX = re.compile(r"@([A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,24})(?![A-Za-z0-9\-])")
_LOCAL_RX = re.compile(r"(?<![A-Za-z0-9._%+\-])([A-Za-z0-9._%+\-]{1,64})@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,24}")
_GENERIC_SELF = {"나", "본인", "me", "you", "user", "admin", "owner"}


# ── 정제 문맥 ─────────────────────────────────────────────────────────────────────
def _as_list(v):
    """설정 값 → 목록. 문자열 하나면 [그것](글자 단위로 돌지 않게), 그 밖의 형식은 []."""
    if v is None:
        return []
    if isinstance(v, str):
        return [v] if v.strip() else []
    if isinstance(v, (list, tuple, set, frozenset)):
        return list(v)
    return []


def _dom_norm(d):
    s = str(d or "").strip().lower().lstrip("@").rstrip(".")
    return s if re.fullmatch(r"[a-z0-9\-]+(?:\.[a-z0-9\-]+)+", s) else ""


def _entries(v):
    """사전 항목 → [(이름 튜플, 도메인 튜플)]. 항목은 이름 문자열 또는 {"name"|"names": …, "domains": […]}."""
    out = []
    for e in _as_list(v):
        if isinstance(e, dict):
            names = _as_list(e.get("names")) + _as_list(e.get("name"))
            doms = _as_list(e.get("domains")) + _as_list(e.get("domain"))
        else:
            names, doms = [e], []
        names = tuple(n for n in (str(x).strip() for x in names) if len(n) >= 2)
        doms = tuple(d for d in (_dom_norm(x) for x in doms) if d)
        if names or doms:
            out.append((names, doms))
    return out


def _compile_allow(pats):
    """privacy.allowPatterns → 쓸 수 있는 정규식 목록. 틀린 식·빈 글에 맞는 식·개인 식별번호·연락처·이름 견본에 맞는 넓은 식은
    버린다(afcfg.allow_pattern_problem — 가림이 줄지 않는 쪽 · D22: 설정은 규칙을 약하게 만들지 못한다)."""
    out = []
    for p in _as_list(pats):
        if afcfg.allow_pattern_problem(p):
            continue
        out.append(p if isinstance(p, re.Pattern) else re.compile(str(p)))
    return out


_CODE_LIKE_RX = re.compile(r"\d|[A-Z]{2,}")


def _code_span_ok(s):
    """허용 패턴이 지킬 수 있는 꼴인가 — 공학 코드 표기만(숫자나 영문 대문자 2자 이상이 들고 한글이 없다). 고객사·과제·사람
    이름처럼 한글이나 보통 낱말인 부분은 허용 패턴에 맞아도 지키지 않는다(D22)."""
    s = str(s or "")
    return bool(s.strip()) and not re.search(r"[가-힣]", s) and _CODE_LIKE_RX.search(s) is not None


class Ctx:
    """정제 문맥 — make_ctx(cfg, data_dir) 가 설정·mail_source me[] 에서 만든다. 수집·분석 1회 동안 바꾸지 않는다.
    기본(빈 사전)은 규칙 말뭉치 시험용이다."""

    def __init__(self, customers=(), partners=(), codenames=(), self_names=(), allow_patterns=(),
                 internal_domains=(), personal_domains=PERSONAL_MAIL_DOMAINS, mask_company=True, mask_rates=True,
                 extra_stop=()):
        self.customers = _entries(customers)
        self.partners = _entries(partners)
        self.codenames = tuple(n for n in (str(x).strip() for x in _as_list(codenames)) if len(n) >= 2)
        self.self_names = tuple(n for n in (str(x).strip() for x in _as_list(self_names) if x)
                                if len(n) >= 2 and n.lower() not in _GENERIC_SELF)
        self.allow_patterns = tuple(_compile_allow(allow_patterns))
        self.internal_domains = tuple(sorted({d for d in (_dom_norm(x) for x in _as_list(internal_domains)) if d}))
        self.personal_domains = frozenset(d for d in (_dom_norm(x) for x in _as_list(personal_domains)) if d)
        self.mask_company = bool(mask_company)
        self.mask_rates = bool(mask_rates)
        self.extra_stop = frozenset(str(x) for x in _as_list(extra_stop))

    def is_internal(self, dom):
        dom = _dom_norm(dom)
        return bool(dom) and any(dom == d or dom.endswith("." + d) for d in self.internal_domains)

    def _in(self, entries, dom):
        return any(dom == d or dom.endswith("." + d) for _n, ds in entries for d in ds)

    def mail_label(self, dom):
        """이메일 토큰 라벨 — 사내 / 개인메일 / 고객사 / 협력사 / 도메인(소문자)."""
        dom = _dom_norm(dom)
        if self.is_internal(dom):
            return "사내"
        if dom in self.personal_domains:
            return "개인메일"
        if self._in(self.customers, dom):
            return "고객사"
        if self._in(self.partners, dom):
            return "협력사"
        return dom if 0 < len(dom) <= 60 else "외부"


_DEFAULT_CTX = Ctx()


def _as_ctx(ctx):
    if ctx is None:
        return _DEFAULT_CTX
    if isinstance(ctx, dict):
        return Ctx(**ctx)
    return ctx


def me_list(data_dir=None):
    r"""본인 표시 이름·주소 — data\outlook\mail_source.json(병합본)과 data\outlook\src\mail_source_*.json 의 me[] 합집합.
    없으면 []. (LM30 의 data\추가PC\* 는 읽지 않는다)"""
    import glob
    data_dir = data_dir or os.path.join(ROOT, "data")
    paths = [os.path.join(data_dir, "outlook", "mail_source.json")]
    paths += sorted(glob.glob(os.path.join(data_dir, "outlook", "src", "mail_source_*.json")))
    out = []
    for p in paths:
        try:
            with open(p, encoding="utf-8-sig") as f:
                me = (json.load(f) or {}).get("me") or []
        except (OSError, ValueError, AttributeError):
            continue
        out += [str(x).strip() for x in me if isinstance(x, str) and str(x).strip()]
    return list(dict.fromkeys(out))


def domain_of(s):
    """주소 문자열에서 도메인(소문자) — 없으면 ""."""
    m = _DOMAIN_RX.search(str(s or ""))
    return m.group(1).lower() if m else ""


def domains_in(s):
    """문자열 안의 모든 메일 도메인(소문자) 집합 — 'a@x.com; b@y.com' 같은 수신자 목록용."""
    return {m.group(1).lower() for m in _DOMAIN_RX.finditer(str(s or ""))}


def local_part(s):
    """주소 문자열의 로컬파트(소문자) — 'Hong <gd.hong@corp.com>' → 'gd.hong'. 없으면 ""."""
    m = _LOCAL_RX.search(str(s or ""))
    return m.group(1).lower() if m else ""


def make_ctx(cfg=None, data_dir=None):
    """설정(privacy.customers·partners·allowPatterns·maskCodenames·codenames · owner)과 mail_source me[] 로
    정제 문맥을 만든다. 사내 도메인 = privacy.internalDomains ∪ me[] 주소의 도메인."""
    cfg = cfg if isinstance(cfg, dict) else {}
    pv = cfg.get("privacy") if isinstance(cfg.get("privacy"), dict) else {}
    me = me_list(data_dir)
    names = [cfg.get("owner")] + [x for x in me if "@" not in x]
    internal = [d for d in (_dom_norm(x) for x in _as_list(pv.get("internalDomains"))) if d not in PERSONAL_MAIL_DOMAINS]
    internal += [d for d in (domain_of(x) for x in me if "@" in x) if d and d not in PERSONAL_MAIL_DOMAINS]
    codenames = []
    if pv.get("maskCodenames") is True or str(pv.get("maskCodenames")).strip().lower() in ("true", "1", "yes", "on"):
        l1 = cfg.get("level1Codenames")
        if isinstance(l1, dict):
            for v in l1.values():
                codenames += [str(x) for x in _as_list(v)]
        codenames += [str(x) for x in _as_list(pv.get("codenames"))]
    return Ctx(customers=pv.get("customers"), partners=pv.get("partners"), codenames=codenames,
               self_names=[x for x in names if isinstance(x, str)], allow_patterns=pv.get("allowPatterns"),
               internal_domains=internal)


# ── 정제 본체 ─────────────────────────────────────────────────────────────────────
class _Ph:
    """보호 구간·토큰을 사설 영역 자리표시자(\\uE000 + 번호 문자 + \\uE001)로 바꿔 두고 마지막에 복원."""

    def __init__(self):
        self.items = []

    def put(self, s):
        self.items.append(s)
        return "" + chr(0xE100 + len(self.items) - 1) + ""

    def restore(self, t):
        for _ in range(4):                 # 자리표시자 안에 자리표시자가 든 경우(허용 패턴이 토큰을 감쌈)까지
            if "" not in t:
                break
            t = re.sub("(.)", lambda m: self.items[ord(m.group(1)) - 0xE100], t)
        return t


_ASCII_NAME = re.compile(r"[A-Za-z0-9 .&\-]+")
_FLEX_SEPS_RX = re.compile(r"[\s\-·_]+")
_FLEX_SEP = r"[\s\-·_]?"
# ASCII 이름 뒤: 숫자는 붙어도 된다('Hanbit2026'). 소문자로 끝나면 대문자가 이어져도 된다('HanbitPrecision' — 낱말 이음),
# 그 밖에는 글자가 이어지면 다른 낱말이다('Hanbitx'·'HANBITX')
_ASCII_TAIL = r"(?:(?-i:(?<=[a-z])(?![a-z]))|(?-i:(?<![a-z]))(?![A-Za-z]))"


def flex_key(s):
    """사전 낱말의 비교 열쇠 — 띄어쓰기·하이픈·가운뎃점·밑줄을 지운 소문자('스카이 라인' == '스카이라인')."""
    return _FLEX_SEPS_RX.sub("", str(s or "")).lower()


def _flex(n):
    """사전 낱말 → 정규식 조각. 구분자를 뺀 3자 이상(영문·숫자만인 이름은 4자 이상)이면 글자 사이에 띄어쓰기·하이픈·가운뎃점·
    밑줄이 있거나 없어도 맞는다('스카이 라인'·'Han-bit'·'LG 에너지솔루션'). 그보다 짧으면 그대로 — 영문 3자 약칭('SKL')을
    풀어 맞추면 다른 회사 표기('SK L…')까지 잡는다."""
    core = _FLEX_SEPS_RX.sub("", n)
    if len(core) < (4 if _ASCII_NAME.fullmatch(n) else 3):
        return re.escape(n)
    return _FLEX_SEP.join(re.escape(ch) for ch in core)


@functools.lru_cache(maxsize=256)
def _dict_rx(names):
    """사전 매칭(긴 이름 먼저, 대소문자 무시 · 3자 이상은 띄어쓰기·하이픈 변형도). ASCII 이름은 앞 영숫자 경계 + 뒤 _ASCII_TAIL,
    한글 든 이름은 앞 경계만(뒤에 조사)."""
    uniq = sorted({n for n in names if n}, key=lambda n: (-len(_FLEX_SEPS_RX.sub("", n)), n))
    mixed = [_flex(n) for n in uniq if not _ASCII_NAME.fullmatch(n)]
    ascii_ = [_flex(n) for n in uniq if _ASCII_NAME.fullmatch(n)]
    parts = []
    if mixed:
        parts.append(r"(?<![가-힣A-Za-z0-9])(?:" + "|".join(mixed) + ")")
    if ascii_:
        parts.append(r"(?<![A-Za-z0-9])(?:" + "|".join(ascii_) + r")" + _ASCII_TAIL)
    return re.compile("|".join(parts), re.I) if parts else None


@functools.lru_cache(maxsize=64)
def _domain_rx(domains):
    """맨 도메인(과 그 하위 도메인) 찾기 — 'portal.gaon.example'. 다른 도메인의 일부('notgaon.example'·
    'gaon.example.other.example')는 아니다."""
    ds = sorted({d for d in domains if d}, key=len, reverse=True)
    if not ds:
        return None
    return re.compile(r"(?<![A-Za-z0-9\-.])(?:[A-Za-z0-9\-]+\.)*(?:" + "|".join(re.escape(d) for d in ds)
                      + r")(?![A-Za-z0-9\-]|\.[A-Za-z0-9])", re.I)


def _names_of(entries):
    return tuple(n for names, _d in entries for n in names)


def safe_truncate(s, n):
    """토큰 중간을 자르지 않는다: 잘린 꼬리에 닫히지 않은 '['(24자 이내)가 있으면 그 앞에서 자른다."""
    if n is None or len(s) <= n:
        return s
    cut = s[: max(1, n - 1)]
    m = re.search(r"\[[^\[\]]{0,24}$", cut)
    if m:
        cut = cut[: m.start()]
    return cut.rstrip() + "…"


def _digits(s):
    return re.sub(r"\D", "", s)


# D10 — 하루 중 시각(14:30 · 9:05 · 14:30:15 · 14시 30분 · 14시 · 오후 2시 · 2시 반)은 data\outlook\** 밖으로 나가지 않는다.
# 제목·안건에 든 시각을 G2(신호 글 · 회의 안건)와 G3(Copilot 에 보내는 행·프롬프트)에서 [시각] 으로 가린다. 날짜(YYYY-MM-DD·
# MM-DD)·'24시간'·'3시간' 같은 길이, '3시 방향·12시 위치' 같은 자리 표시는 그대로 둔다.
_CLOCK_AFTER = r"(?=$|[^가-힣\d]|에|까지|부터|경|쯤|께|정각|전|후|이후|이전|부|의|로|으로|에서|이나|나|와|과|도|만|은|는)"
CLOCK_RX = re.compile(
    r"(?:오전|오후|새벽|아침|저녁|밤|낮)\s?(?:[01]?\d|2[0-4])(?:\s?:\s?[0-5]\d|\s?시(?:\s?[0-5]?\d\s?분|\s?반)?)" + _CLOCK_AFTER
    + r"|(?<![\d:])(?:[01]?\d|2[0-3])(?:\s?:\s?|\s?시\s?)[0-5]\d(?::[0-5]\d)?(?:\s?분)?(?![\d:])"
    r"|(?<![\d:.])(?:[01]?\d|2[0-4])\s?시(?!\s?(?:방향|위치|지점|부근))(?:\s?반)?" + _CLOCK_AFTER)
CLOCK_TOKEN = "[시각]"


def mask_clock(text):
    """글 안의 하루 중 시각 → [시각](D10). 빈 값은 그대로."""
    s = "" if text is None else str(text)
    return CLOCK_RX.sub(CLOCK_TOKEN, s) if s else s


# R5 — 제목 속 메일 주소는 sanitize 가 [이메일@<관계 또는 도메인>] 으로 가린다. G1·G2 는 바깥 조직의 도메인을 남기지 않고 통째로
# [이메일] 로 접는다(관계 표시 사내·개인메일·고객사·협력사는 사람·조직을 가리키지 않으므로 둔다). 사내/사외 판별(D7)은 제목이
# 아니라 참여자 주소로 하므로 이 도메인이 필요 없다.
MAIL_TOKEN = "[이메일]"
_MAIL_DOMAIN_TOKEN_RX = re.compile(r"\[이메일@(?!(?:사내|개인메일|고객사|협력사)\])[^\[\]]{1,64}\]")


def fold_mail_domains(text):
    """글 안의 '[이메일@바깥 도메인]'(·'[이메일@외부]') → [이메일]. 빈 값은 그대로."""
    s = "" if text is None else str(text)
    return _MAIL_DOMAIN_TOKEN_RX.sub(MAIL_TOKEN, s) if "[이메일@" in s else s


def minimize_text(text):
    """G2 마무리(신호 글 · 회의 제목·안건) — 하루 중 시각 → [시각](D10) · 바깥 도메인 메일 토큰 → [이메일](R5)."""
    return fold_mail_domains(mask_clock(text))


def sanitize(text, field="text", ctx=None, max_len=None):
    """원문 한 필드 → (정제문, 범주별 건수 dict, drop). drop=True(자격증명)면 정제문은 "" — 그 행은 저장하지 않는다.
    단계 순서(A-02): ① NFKC·앞 4,000자 ② 자격증명 → drop ③ 기존 토큰·허용 패턴 보호 ④ 생년월일 라벨
    ⑤ 날짜·시각·버전·규격 보호 ⑥ URL·이메일·경로 ⑦ 사전(고객사·협력사·과제·본인) ⑧ 이름 문맥(멘션·라벨·호칭)
    ⑨ 숫자형(주민 → 카드 → 전화 → 사업자·법인 → 여권 → 면허 → 계좌 → IP) ⑩ 금액 M1~M6 ⑪ 회사 접미형 ⑫ 복원·절단.
    field 는 이름표일 뿐 규칙 분기에 쓰지 않는다."""
    if text is None:
        return "", {}, False
    text = str(text)
    if not text:
        return "", {}, False
    ctx = _as_ctx(ctx)
    hits = {}

    def bump(k):
        hits[k] = hits.get(k, 0) + 1

    t = unicodedata.normalize("NFKC", text[:MAX_SCAN])
    t = CTRL_RX.sub(" ", FORMAT_RX.sub("", t))
    t = DASH_RX.sub("-", t)

    # ② 자격증명 → 행 폐기
    if credential_hit(t):
        return "", {"cred": 1}, True

    ph = _Ph()

    def tok(token, cat):
        bump(cat)
        return ph.put(token)

    def near(s, e, key, before=20, after=20):
        return re.search(CTX[key], t[max(0, s - before):e + after], re.I) is not None

    def eng_suppressed(s):
        return ENG_CTX.search(t[max(0, s - 10):s]) is not None

    # ③ 기존 토큰 보호(멱등) · 조직 허용 패턴 — 공학 코드 꼴(_code_span_ok)만 지킨다. 주민·카드·전화·메일 주소·계좌가 들었거나
    #    사전 낱말(고객사·협력사·과제 코드네임·본인)이 든 부분은 보호하지 않는다(D22 — 설정은 가림을 줄이지 못한다)
    t = TOKEN_RX.sub(lambda m: ph.put(m.group(0)), t)
    if ctx.allow_patterns:
        drx = _dict_rx(tuple(_names_of(ctx.customers) + _names_of(ctx.partners) + tuple(ctx.codenames)
                             + tuple(ctx.self_names)))
        for p in ctx.allow_patterns:
            t = p.sub(lambda m, drx=drx: ph.put(m.group(0))
                      if (_code_span_ok(m.group(0)) and not _shields_identifier(m.group(0))
                          and not (drx is not None and drx.search(m.group(0)))) else m.group(0), t)
    # ④ 라벨형 생년월일·주민 앞자리(날짜 보호보다 먼저)
    t = RX["birth"].sub(lambda m: m.group(0)[:m.start("d") - m.start()] + tok("[생년월일]", "birth"), t)
    t = RX["rrn_front"].sub(lambda m: m.group(0)[:m.start("d") - m.start()] + tok("[주민번호]", "rrn"), t)
    # ⑤ 날짜·시각·버전·규격 보호
    for _n, rx in PROTECT:
        t = rx.sub(lambda m: ph.put(m.group(0)), t)

    # ⑥ URL → 이메일(로컬파트는 버리고 관계 라벨만) → 경로(폴더는 지우고 기본 이름만)
    t = RX["url"].sub(lambda m: tok("[URL]", "url"), t)
    t = RX["email"].sub(lambda m: tok("[이메일@" + ctx.mail_label(m.group("dom")) + "]", "email"), t)

    def path_rep(m):
        bump("path")
        return ph.put("[경로]") + "\\"
    t = RX["path"].sub(path_rep, t)

    # ⑦ 사전 가명화: 고객사 → 협력사 → 과제 코드네임 → 본인
    for names, token, cat in ((_names_of(ctx.customers), "[고객사]", "customer"),
                              (_names_of(ctx.partners), "[협력사]", "partner"),
                              (ctx.codenames, "[과제]", "project"),
                              (ctx.self_names, "[나]", "self")):
        rx = _dict_rx(tuple(names))
        if rx:
            t = rx.sub(lambda m, token=token, cat=cat: tok(token, cat), t)

    # ⑧ 이름 문맥: 멘션 → 라벨형 → 호칭형(호칭형은 흔한 성씨 검사 + 업무어·부서·장소 낱말 제외 · '대표 모델' 같은 자리 제외)
    def name_sub(require_plausible):
        def rep(m):
            n = m.group("name")
            if require_plausible and re.fullmatch(r"[가-힣]+", n) and (not _titled_name_ok(m) or n in ctx.extra_stop):
                return m.group(0)
            s, e = m.span("name")
            return m.group(0)[:s - m.start()] + tok("[사람]", "person") + m.group(0)[e - m.start():]
        return rep
    t = MENTION.sub(name_sub(False), t)
    t = LABELED_NAME.sub(name_sub(False), t)
    t = HONORIFIC.sub(name_sub(True), t)

    # ⑨ 숫자형 PII — 순서 고정
    def v_rrn(m):
        d = _digits(m.group(0))
        if not rrn_date_ok(d):
            return m.group(0)
        hy = any(ch in m.group(0) for ch in "-–—")
        eng = eng_suppressed(m.start())
        ok = (hy and not eng) or (rrn_checksum_ok(d) and not eng) or near(m.start(), m.end(), "rrn")
        # 2020-10 이후 번호는 체크섬이 없다 — 생년월일·성별 자리가 맞는 13자리는 바로 앞이 공학·주문 번호 문맥이 아니면 가린다
        ok = ok or not (eng or _order_before(t, m.start()))
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
    t = RX["landline82"].sub(lambda m: tok("[전화]", "phone"), t)
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
        strong = re.search(CTX["account_strong"], t[max(0, m.start() - 12):m.start()], re.I) is not None
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

    # ⑩ 금액·비율(M1 비율 → M2 통화기호 → M3 한국어 단위 → M4 통화 접미 → M5 금액어 인접 → M6 문맥 맨숫자).
    #    수량·납기는 분류 단서라 남긴다 — 공학 단위·개수·치수·식별자 앞뒤는 억제
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
        if not re.search(CTX["money"], t[max(0, s - 20):e + 10], re.I):
            return m.group(0)
        after, before = t[e:e + 6], t[max(0, s - 4):s]
        if ENG_UNIT_AFTER.match(after) or COUNT_AFTER.match(after) or DIM_NEAR.match(after) or DIM_NEAR.search(before):
            return m.group(0)
        if ID_BEFORE.search(t[max(0, s - 8):s]) or eng_suppressed(s):
            return m.group(0)
        return tok("[금액]", "money")
    t = RX["money_bare"].sub(v_bare, t)

    # ⑪ 회사 접미형 — (주)XXX · XXX 주식회사 · Xxx Co., Ltd.
    if ctx.mask_company:
        t = RX["company"].sub(lambda m: tok("[회사]", "company"), t)

    # ⑫ 복원·공백 축약·토큰을 자르지 않는 절단
    out = re.sub(r"[ \t]{2,}", " ", ph.restore(t)).strip()
    if max_len:
        out = safe_truncate(out, max_len)
    return out, hits, False


# ── 광고성 메일(헤더 없음 — AD_PARTIAL) ──────────────────────────────────────────────
AD_PARTIAL = True             # 수집 경로(COM·OWA·Copilot)는 메일 헤더를 주지 않는다 — 헤더 가점 없이 같은 임계
AD_PREFIX = re.compile(r"^\s*(?:(?:re|fw|fwd|회신|전달|답장)\s*[:：]\s*)*[\(\[<【〈{]\s*(?:광고|ad|광고성\s?정보|홍보|advertisement)"
                       r"\s*[\)\]>】〉}]", re.I)
AD_WORDS = re.compile(
    r"(?i)(수신\s?거부|구독\s?(?:취소|해지)|unsubscribe|opt[- ]?out|뉴스레터|newsletter|웨비나|webinar|프로모션|promotion|"
    r"할인|특가|쿠폰|coupon|이벤트|event|무료\s?체험|free\s?trial|신제품\s?출시|런칭|초대합니다|세미나\s?안내|전시회\s?초대|"
    r"limited\s?offer|sale|경품|사은품|당첨|혜택|얼리버드|early\s?bird)")
AD_LOCALPART = re.compile(r"(?i)^(?:newsletter|news|marketing|promo|promotion|event|events|webinar|campaign|mailer|edm|ad|ads"
                          r"|offers?)[._\-]?|(?:^|[._\-])(?:newsletter|marketing|promo|campaign|edm)(?:$|[._\-])")
AD_DROP, AD_SUSPECT = 5, 3
JUNK_FOLDERS = {"junk", "spam", "정크", "정크 메일", "스팸", "junk email", "junk e-mail"}


def ad_score(subject, sender_addr="", box="", folder="", exchanged_domains=(), *, internal_domains=(),
             i_sent_in_conv=False, blocked=False, allowed=False):
    """광고 점수(LM27 classify.ad_score, 헤더 항목 제외) → (점수, "drop"|"suspect"|"keep").
    즉시 9(drop): 사용자 차단·정크 폴더·제목 첫머리 광고 표기 '(광고)'. 가점: 외부 도메인 +1, 외부이면서 왕래 없음 +2,
    제목 광고어 1종 +2 / 2종 이상 +3, 광고형 로컬파트 +1. 감점: 사내·왕래 −3(면제가 아니라 감점), 같은 대화에 내 발신 −4.
    허용 목록이면 상한 0. 5 이상 drop(저장하지 않고 건수만) · 3~4 suspect(신호에 flag 'ad' — Copilot 제외) · 이하 keep.
    LM28(헤더·수신자 목록 없음 — AD_PARTIAL): 도메인 가점은 광고 단서(광고어·광고형 로컬파트)가 있을 때만 준다 —
    처음 연락 온 외부 업무 메일('견적 요청')이 단서 없이 suspect 가 되지 않게. 주소 없는 표시 이름뿐이면 도메인 가점 없음."""
    if str(box or "").strip().lower() == "sent":
        return 0, "keep"
    subj = str(subject or "")
    if blocked:
        return 9, "drop"
    if str(folder or "").strip().lower() in JUNK_FOLDERS:
        return 9, "drop"
    if AD_PREFIX.search(subj):
        return 9, "drop"                   # 정보통신망법 제50조 광고 표기 — 단독 확정(회신·허용 면제 무효)
    s = 0
    dom = domain_of(sender_addr)
    internal = bool(dom) and any(dom == d or dom.endswith("." + d) for d in (_dom_norm(x) for x in internal_domains) if d)
    exch = {_dom_norm(x) for x in exchanged_domains or ()}
    corresp = bool(dom) and (dom in exch or any(dom.endswith("." + d) for d in exch if d))
    words = {w.lower() for w in AD_WORDS.findall(subj)}
    local = local_part(sender_addr)
    adlike = bool(local) and bool(AD_LOCALPART.search(local))
    if dom and not internal and (words or adlike):
        s += 1
        if not corresp:
            s += 2
    if words:
        s += 2 + (1 if len(words) >= 2 else 0)
    if adlike:
        s += 1
    if internal or corresp:
        s -= 3                             # 사내·왕래: 감점만(LM24 의 영구 면제 결함 수정)
    if i_sent_in_conv:
        s -= 4
    if allowed:
        s = min(s, 0)
    return s, ("drop" if s >= AD_DROP else ("suspect" if s >= AD_SUSPECT else "keep"))


# ── 공사(公私) 구분 ────────────────────────────────────────────────────────────────
#   NFKC 는 한글 호환 자모(ㅋ·ㅎ·ㅠ·ㅜ)를 첫가끝 자모(ᄏ·ᄒ·ᅲ·ᅮ)로 바꾼다 — 정제문에서도 잡히게 두 꼴을 다 받는다
P_STRONG = re.compile(
    r"(가족|와이프|아내|남편|신랑|애기|아기|아이들|딸아이|아들|부모님|엄마|아빠|장모|시댁|처가|병원|치과|한의원|약국|진료|택배|배송|쇼핑|주문했|직구|"
    r"여행|휴가\s?계획|비행기\s?표|숙소|캠핑|게임|축구|야구|농구|영화|드라마|넷플|유튜브|주식(?!회사)|코인(?!\s?(?:셀|전지|배터리|cell))|대출"
    r"|이사\s?(?:가|날|준비)|집들이|부동산|청약|전세|월세|결혼식|소개팅|데이트|생일\s?선물|헬스장|골프)")
# LM28: '술'·'헐' 은 앞뒤가 한글이 아닐 때만(기술·학술·헐거움 같은 업무어 오탐 방지)
P_WEAK = re.compile(r"(점심|저녁|야식|커피|한잔|(?<![가-힣])술|맥주|치킨|맛집|퇴근하고|퇴근\s?후에|주말에|휴일에|날씨|[ㅋᄏ]{2,}"
                    r"|[ㅎᄒ]{2,}|[ㅠᅲ]{2,}|[ㅜᅮ]{2,}|[ㄱᄀ]{2}|(?<![가-힣])헐(?![가-힣])|대박|😂|🤣|😆|🍺|🍻)")
P_SOCIAL = re.compile(r"(회식|경조사|축의|부의|조의|조문|돌잔치|동호회|송년회|신년회|뒤풀이|생일\s?축하|체육대회)")
W_WORK = re.compile(
    r"(?i)(검토|회신|보고|자료|첨부|일정|회의|미팅|도면|설계|시험|평가|해석|시뮬|샘플|발주|구매|견적|고객|과제|프로젝트|양산|개발|이슈|불량|대책|품질|"
    r"(?<![A-Za-z])(?:BOM|ECO|DR|PR|PO|spec)(?![A-Za-z])|사양|요청|부탁드립니다|공유드립니다|확인\s?부탁|승인|결재|기안|출장|교육|특허|예산|정산)")
W_ACK = re.compile(r"(넵|네\s?알겠습니다|알겠습니다|확인했습니다|감사합니다|수고하셨습니다)")
REG_TOKEN = re.compile(r"\[(?:과제|고객사|협력사)(?::[^\]]+)?\]")
PRIV_THRESHOLD = 2


def private_score(text, is_1to1=None, *, partner_personal=False, sensitivity=0, private_category=False):
    """정제문 하나의 공사 판정(LM27 classify.private_score, 방 성향 생략) → "work" | "private" | "social".
    점수 = 2×강한 사적어 + 약한 사적어 + 친목어 − 2×min(업무어,4) − 업무 응답어, 업무 토큰([과제]·[고객사]·[협력사]) −3,
    1:1 +1 / 단체(is_1to1=False) −1, 상대가 개인 메일 도메인 +3. 시각(퇴근 후·주말)은 보지 않는다(D10).
    2 이상이면 private(친목어만 있고 강한 사적어가 없으면 social), 아니면 work. Outlook 민감도 1·2·3·개인 범주는 즉시 private."""
    if sensitivity in (1, 2, 3) or private_category:
        return "private"
    t = str(text or "")
    ps, pw, so = P_STRONG.findall(t), P_WEAK.findall(t), P_SOCIAL.findall(t)
    ww, ack = W_WORK.findall(t), W_ACK.findall(t)
    s = 2 * len(ps) + len(pw) + len(so) - 2 * min(len(ww), 4) - len(ack)
    if REG_TOKEN.search(t):
        s -= 3
    if is_1to1 is True:
        s += 1
    elif is_1to1 is False:
        s -= 1
    if partner_personal:
        s += 3
    if s >= PRIV_THRESHOLD:
        return "social" if so and not ps else "private"
    return "work"


def is_personal_addr(addr, ctx=None):
    """상대 주소가 공용 개인 메일 도메인인가(gmail·naver …)."""
    dom = domain_of(addr)
    return bool(dom) and dom in _as_ctx(ctx).personal_domains


# ── 카나리아(이 PC·본인 식별자) ─────────────────────────────────────────────────────────
CANARY_MIN = 4                        # 이보다 짧은 값은 오탐 — 무시
_GENERIC_CANARY = {"user", "users", "admin", "administrator", "owner", "guest", "workgroup", "default", "public",
                   "corp", "home", "local", "desktop", "laptop", "domain", "windows", "pc"}
_ASCII_CANARY = re.compile(r"^[a-z0-9._\-]+$")


def canaries(cfg=None, data_dir=None, env=None):
    """카나리아 값(소문자) — COMPUTERNAME·USERNAME·USERDOMAIN·본인 SMTP 주소·로컬파트·mail_source me[].
    4자 미만·일반 계정명(user·admin …)은 무시한다. 메모리에서만 쓰고 파일에 남기지 않는다."""
    env = os.environ if env is None else env
    vals = [env.get(k) for k in ("COMPUTERNAME", "USERNAME", "USERDOMAIN")]
    for x in me_list(data_dir):
        vals.append(x)
        if "@" in x:
            vals.append(local_part(x))
    return _norm_canaries(vals)


canaries_fn = canaries                 # 아래 함수들의 키워드 인자 이름(canaries)이 이 함수를 가리므로 별칭


def _norm_canaries(cans):
    return tuple(dict.fromkeys(s for s in (str(c or "").strip().lower() for c in cans or ())
                               if len(s) >= CANARY_MIN and s not in _GENERIC_CANARY))


def canary_in(text, cans):
    """카나리아 원값이 들어 있는가(대소문자 무시). ASCII 값은 영숫자 경계로, 그 밖은 부분 문자열로."""
    low = str(text or "").lower()
    if not low:
        return False
    for c in cans or ():
        if _ASCII_CANARY.match(c):
            if re.search(r"(?<![a-z0-9])" + re.escape(c) + r"(?![a-z0-9])", low):
                return True
        elif c in low:
            return True
    return False


# ── G3 Copilot 직전 ───────────────────────────────────────────────────────────────
_AD_FLAG = re.compile(r"(?<![a-z])ad(?![a-z])", re.I)


def _gate_restricted(cfg, data_dir, restricted):
    """G3 의 제한 고객 목록 — 주면 그것, 아니면 설치 폴더(data_dir 의 위 폴더, 없으면 ROOT)의 목록. 못 읽으면 None(닫는다)."""
    if restricted is not None:
        return restricted
    root = os.path.dirname(os.path.abspath(data_dir)) if data_dir else ROOT
    try:
        return load_restricted(cfg, root)
    except RestrictedListError:
        return None


def gate_items(items, fields, cfg=None, *, canaries=None, ctx=None, max_chars=400, data_dir=None, restricted=None):
    """G3 — Copilot 에 보내기 직전의 행 관문. items = dict 목록(원본은 바꾸지 않는다) → (보낼 행 목록, 제외 건수 {사유: n}).
    사유: 제한고객목록없음 · 사적 · 광고의심 · 제한고객 · 민감정보:<범주> · 자격증명 · 개인정보:<범주> · 식별번호 · 카나리아.
    ⓪ 제한 고객 목록(restricted — 없으면 data_dir 위 설치 폴더의 config 에서 읽는다)을 못 읽으면 모두 제외(실패하면 닫는다)
    ① 사적/친목(priv·priv_class)·광고 의심(flag 'ad') 행 제외 ② fields 원문에 제한 고객 이름·도메인 → 제외 ③ 민감정보 → 제외
    ④ fields 재정제(호칭 이름 → [사람]) ⑤ 자격증명 → 제외 ⑥ 고위험(HIGH) 잔여 → 제외 ⑦ 가린 뒤에도 남은 맨 식별번호 → 제외
    ⑧ 카나리아 → 제외 ⑨ 이름 해시(남은 모든 분석의 것 — name_gate)에 든 이름 → [사람] · [사람#…] → [사람] 통일 · 하루 중
    시각 → [시각](D10) ⑩ 필드마다 max_chars(400)자 — 토큰을 자르지 않는다."""
    flds = [fields] if isinstance(fields, str) else list(fields or ())
    if ctx is None:
        ctx = make_ctx(cfg, data_dir)
    cans = (_norm_canaries(canaries) if canaries is not None
            else canaries_fn(cfg, data_dir))
    rs = _gate_restricted(cfg, data_dir, restricted)
    hashes, salt = name_gate(os.path.dirname(os.path.abspath(data_dir)) if data_dir else ROOT)
    kept, dropped = [], {}

    def drop(why):
        dropped[why] = dropped.get(why, 0) + 1

    for it in items or ():
        if not isinstance(it, dict):
            continue
        if rs is None:
            drop("제한고객목록없음")
            continue
        if str(it.get("priv") or it.get("priv_class") or "").strip().lower() in ("private", "social"):
            drop("사적")
            continue
        if _AD_FLAG.search(str(it.get("flag") or "")):
            drop("광고의심")
            continue
        raw = "\n".join(str(it.get(f)) for f in flds if it.get(f) not in (None, ""))
        if rs.hit(raw):
            drop("제한고객")
            continue
        sh = sensitive_hit(raw, cfg)
        if sh:
            drop("민감정보:" + sh)
            continue
        new, bad = dict(it), None
        for f in flds:
            v = it.get(f)
            if v is None or v == "":
                continue
            clean, cats, dr = sanitize(str(v), f, ctx)
            if dr:
                bad = "자격증명"
                break
            hi = sorted(k for k in cats if k in HIGH)
            if hi:
                bad = "개인정보:" + hi[0]
                break
            if has_identifier(clean, allow_patterns=ctx.allow_patterns):
                bad = "식별번호"
                break
            if canary_in(clean, cans):
                bad = "카나리아"
                break
            if hashes:
                clean = _hash_mask(clean, hashes, salt)
            new[f] = safe_truncate(PERSON_TAG_RX.sub("[사람]", mask_clock(clean)), max_chars)
        if bad:
            drop(bad)
            continue
        kept.append(new)
    return kept, dropped


def _chunks(text, n=3500):
    """긴 프롬프트를 줄 경계로 n 자 안팎씩 — sanitize 는 앞 MAX_SCAN 자만 보므로 나눠 검사한다."""
    buf, size = [], 0
    for ln in str(text or "").splitlines(True):
        while len(ln) > n:
            if buf:
                yield "".join(buf)
                buf, size = [], 0
            yield ln[:n]
            ln = ln[n - 100:]               # 경계에 걸친 값을 놓치지 않게 100자 겹침
        if size + len(ln) > n and buf:
            yield "".join(buf)
            buf, size = [], 0
        buf.append(ln)
        size += len(ln)
    if buf:
        yield "".join(buf)


def gate_prompt(text, cfg=None, *, canaries=None, ctx=None, data_dir=None, restricted=None):
    """G3 최종 프롬프트 검사 → True(보내도 됨). 실패하면 닫는다 — 제한 고객 목록을 못 읽음 · 제한 고객 이름·도메인 · 민감정보 ·
    자격증명 · 고위험 잔여 · 가린 뒤에도 남은 맨 식별번호 · 카나리아 · '이름 + 호칭'(titled_names) · 이름 해시(남은 모든 분석의
    것)에 든 사람 이름(known_name_in) 중 하나라도 있으면 False(그 배치는 보내지 않는다).
    이미 정제된 토큰은 보호 구간이라 다시 걸리지 않는다."""
    if ctx is None:
        ctx = make_ctx(cfg, data_dir)
    rs = _gate_restricted(cfg, data_dir, restricted)
    if rs is None or rs.hit(str(text or "")):
        return False
    if sensitive_hit(text, cfg):
        return False
    if titled_names(_nfkc(text)):
        return False
    hashes, salt = name_gate(os.path.dirname(os.path.abspath(data_dir)) if data_dir else ROOT)
    if hashes and known_name_in(_nfkc(text), hashes, salt):
        return False
    cans = _norm_canaries(canaries) if canaries is not None else canaries_fn(cfg, data_dir)
    for part in _chunks(text):
        clean, cats, dr = sanitize(part, "prompt", ctx)
        if dr or any(k in HIGH for k in cats):
            return False
        if has_identifier(clean, allow_patterns=ctx.allow_patterns):
            return False
    return not canary_in(text, cans)


# ── 수집 CSV 제자리 정제(옛 G1 — 열을 바꾸지 않는 정제가 필요한 곳용) ─────────────────────────────────────────────────────
def _audit_path_for(path):
    """CSV 경로의 위쪽 'data' 폴더의 privacy_audit.json — 없으면 CSV 와 같은 폴더."""
    d = os.path.dirname(os.path.abspath(path))
    cur = d
    for _ in range(6):
        if os.path.basename(cur).lower() == "data":
            return os.path.join(cur, "privacy_audit.json"), cur
        nxt = os.path.dirname(cur)
        if nxt == cur:
            break
        cur = nxt
    return os.path.join(d, "privacy_audit.json"), d


def _audit_write(audit_path, base, path, entry):
    """감사 기록 — 파일별 RULES_VER·건수만(원문·예시 없음). 실패해도 정제는 유효하다."""
    rel = os.path.relpath(os.path.abspath(path), base).replace("\\", "/") if base else os.path.basename(path)
    try:
        with open(audit_path, encoding="utf-8") as f:
            cur = json.load(f)
        if not isinstance(cur, dict):
            cur = {}
    except (OSError, ValueError):
        cur = {}
    files = cur.get("files") if isinstance(cur.get("files"), dict) else {}
    files[rel] = entry
    cur = {"rules_ver": RULES_VER, "files": files}
    tmp = f"{audit_path}.{os.getpid()}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cur, f, ensure_ascii=False, indent=1)
        os.replace(tmp, audit_path)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass


def scrub_csv(path, cols, key_cols=None, *, ctx=None, cfg=None, audit_path=None, data_dir=None):
    """G1 — 수집기 CSV 한 개를 제자리에서 정제한다(머리글·열 수·열 순서 불변 — 열을 더하지 않는다).
      · cols 의 값을 sanitize — 자격증명(drop)이 하나라도 있으면 그 행을 뺀다.
      · key_cols 를 주면 정제 **후** 값으로 키를 만들어 같은 키의 행은 처음 것 하나만 남긴다(멱등 — 다시 돌려도 같다).
      · 파일별 RULES_VER·범주 건수만 data\\privacy_audit.json 에 남긴다.
    → {"ok", "rows_in", "rows_out", "dropped", "folded", "cats", "changed"} / 실패 {"ok": False, "error"}."""
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError as e:
        return {"ok": False, "error": f"{type(e).__name__}"}
    bom = raw.startswith(b"\xef\xbb\xbf")
    try:
        text = raw.decode("utf-8-sig")
        enc = "utf-8-sig" if bom else "utf-8"
    except UnicodeDecodeError:
        text = raw.decode("cp949", "replace")      # Excel 이 다시 저장한 파일 — 다시 쓸 때는 UTF-8(BOM)
        enc = "utf-8-sig"
    nl = "\r\n" if "\r\n" in text[:4096] or not text else "\n"
    try:
        rows = list(csv.reader(io.StringIO(text, newline="")))
    except csv.Error as e:
        return {"ok": False, "error": f"csv: {e}"}
    if not rows:
        return {"ok": True, "rows_in": 0, "rows_out": 0, "dropped": 0, "folded": 0, "cats": {}, "changed": False}
    if ctx is None:
        ctx = make_ctx(cfg, data_dir)
    head = rows[0]
    want, kwant = set(cols or ()), set(key_cols or ())
    idx = [i for i, h in enumerate(head) if h in want]
    kidx = [i for i, h in enumerate(head) if h in kwant] if key_cols else []
    cats, out, seen = {}, [head], set()
    dropped = folded = 0
    changed = False
    for r in rows[1:]:
        if not r:
            continue
        nr, bad = list(r), False
        for i in idx:
            if i >= len(nr) or not nr[i]:
                continue
            clean, c, dr = sanitize(nr[i], head[i], ctx)
            if dr:
                bad = True
                break
            for k, v in c.items():
                cats[k] = cats.get(k, 0) + v
            if clean != nr[i]:
                nr[i] = clean
                changed = True
        if bad:
            dropped += 1
            changed = True
            cats["cred"] = cats.get("cred", 0) + 1
            continue
        if kidx:
            k = tuple(nr[i] if i < len(nr) else "" for i in kidx)
            if k in seen:
                folded += 1
                changed = True
                continue
            seen.add(k)
        out.append(nr)
    info = {"ok": True, "rows_in": len(rows) - 1, "rows_out": len(out) - 1, "dropped": dropped, "folded": folded,
            "cats": dict(sorted(cats.items())), "changed": changed}
    if changed:
        buf = io.StringIO()
        csv.writer(buf, lineterminator=nl).writerows(out)
        tmp = f"{path}.{os.getpid()}.g1tmp"
        try:
            with open(tmp, "w", encoding=enc, newline="") as f:
                f.write(buf.getvalue())
            os.replace(tmp, path)
        except OSError as e:
            try:
                os.remove(tmp)
            except OSError:
                pass
            return {"ok": False, "error": f"쓰기 실패({type(e).__name__}) — 다른 프로그램이 열고 있을 수 있습니다"}
    ap, base = (audit_path, os.path.dirname(os.path.abspath(audit_path))) if audit_path else _audit_path_for(path)
    _audit_write(ap, base, path, {"rules_ver": RULES_VER, "at": time.strftime("%Y-%m-%d"),
                                  "rows_in": info["rows_in"], "rows_out": info["rows_out"],
                                  "dropped": dropped, "folded": folded, "cats": info["cats"]})
    return info


# ── 공유용 도메인 계급(리포트의 외부 계급 표시) ─────────────────────────────────────────────
WHO_CLASSES = ("사내", "고객사", "협력사", "외부")
_EXTERNAL_MARK = re.compile(r"\((?:외부|external|guest|게스트)\)", re.I)


def who_class(who, ctx=None):
    """신호의 who(표시 이름·주소) → 도메인 계급 사내 | 고객사 | 협력사 | 외부(빈 값은 빈 값). 가명(p:…)·'나' 는 사내.
    사전(고객사·협력사 이름) → 주소 도메인(사내·고객사·협력사 도메인, 그 밖 외부) → '(외부)' 표기 → 사내."""
    w = str(who or "").strip()
    if not w:
        return ""
    if w in WHO_CLASSES:
        return w
    if w in ("나", "[나]") or PSEUDO_RX.fullmatch(w):
        return "사내"
    ctx = _as_ctx(ctx)
    rx = _dict_rx(_names_of(ctx.customers))
    if rx and rx.search(w):
        return "고객사"
    rx = _dict_rx(_names_of(ctx.partners))
    if rx and rx.search(w):
        return "협력사"
    dom = domain_of(w)
    if dom:
        lab = ctx.mail_label(dom)
        return lab if lab in ("사내", "고객사", "협력사") else "외부"
    if _EXTERNAL_MARK.search(w):
        return "외부"
    return "사내"


def canary_hit(rows, canaries=None, *, cfg=None, data_dir=None):
    """행(들)의 키·값 어디에든 카나리아(이 PC·본인 식별자)가 있는가."""
    cans = _norm_canaries(canaries) if canaries is not None else canaries_fn(cfg, data_dir)
    if not cans:
        return False
    for r in rows or ():
        vals = list(r.items()) if isinstance(r, dict) else [(None, r)]
        for k, v in vals:
            if (k and canary_in(k, cans)) or canary_in(v, cans):
                return True
    return False


# ═════════════════════════════════════════════════════════════════════════════════════════
# AF32 규칙 — 민감정보(D5) · 식별번호(D6) · 근태·행방(D4) · 제한 고객(D9) · 사내/사외(D7) · 이름·가명(D8)
# ═════════════════════════════════════════════════════════════════════════════════════════
class SetupRefused(Exception):
    """분석·공유를 시작하지 않는 설정 문제(종료 코드 4). str(e) = 사람에게 보일 한국어 문장."""

    code = 4

    def __init__(self, message, detail="", where=""):
        super().__init__(message)
        self.message = message
        self.detail = detail
        self.where = where              # 형식 오류의 자리(예 'customers[2].domains') — 운영 담당이 고칠 곳


class RestrictedListError(SetupRefused):
    """제한 고객 목록 파일이 없거나 형식이 틀렸다(D9) — 분석·공유를 하지 않는다."""


class InternalDomainsError(SetupRefused):
    """사내 메일 도메인을 하나도 알 수 없다(D7) — 수집·분석을 하지 않는다."""


RESTRICTED_MSG = ("제한 고객 목록 파일이 없습니다 — 운영 담당이 배포한 config\\restricted_customers.json 을 넣으세요. "
                  "제한 고객이 없으면 빈 목록 파일을 받습니다")
# 파일은 있지만 목록으로 쓸 수 없을 때(detail 'invalid') — 틀린 곳(.where)을 함께 알린다. 고칠 때까지 분석·공유를 하지 않는다
RESTRICTED_BAD_MSG = ("제한 고객 목록 파일의 형식이 틀렸습니다 — 운영 담당이 배포한 config\\restricted_customers.json 을 그대로 "
                      "넣으세요. 고칠 때까지 분석과 공유를 하지 않습니다")
RESTRICTED_TEMPLATE_MSG = ("제한 고객 목록 파일이 견본 그대로입니다 — 견본은 목록이 아닙니다. 운영 담당이 배포한 "
                           "config\\restricted_customers.json 을 넣으세요")
INTERNAL_MSG ="사내 메일 도메인을 알 수 없어 분석하지 않았습니다 — 설정의 privacy.internalDomains 를 채우세요"
EXCLUDE_KEYS = ("private", "admin", "sensitive", "identifier", "external", "external_unknown", "restricted")
DROP_ORDER = ("restricted", "private", "admin", "external", "external_unknown", "sensitive", "identifier")

KB = r"(?<![가-힣])"            # 앞이 한글이 아님(낱말 첫머리)


def _nfkc(s):
    return DASH_RX.sub("-", CTRL_RX.sub(" ", FORMAT_RX.sub("", unicodedata.normalize("NFKC", str(s or "")))))


# ── 민감정보(D5) — 낱말 목록은 사람의 상태·신념을 가리키는 표현만(공학 낱말과 겹치는 '장애'·'진단'·'구속'·'코로나 방전'·
#    '전도율'·'미사용'·'재활용' 같은 것은 일부러 넣지 않았다). SENSITIVE_ALLOW 는 공학·법정 교육 표현의 예외(명시 목록 — 시험이 본다).
SENSITIVE_WORDS = {
    "health": [
        r"진단서", r"소견서", r"입원", r"퇴원", r"수술", r"투병", r"질병", r"질환", r"병명", r"항암",
        # 암 — 위암·간암·유방암·갑상선암 같은 붙은 이름(낱말 첫머리 — 뒤 낱말이 없어도) · 홀로 쓴 '암 진단·암 판정·암 수술' ·
        # 그 밖의 '…암' 은 치료·투병·환자·확진·말기가 붙을 때만. 암호·암기·암석, 로봇암(arm)·명암·화강암 + 진단·판정은 아니다
        KB + r"(?:위|간|폐|유방|대장|직장|갑상선|췌장|자궁(?:경부|내막)?|난소|전립선|방광|신장|식도|후두|구강|피부|혈액|담도|담낭"
             r"|두경부|소아|말기)암",
        KB + r"암\s?(?:진단|판정|수술|치료|투병|환자|확진|말기)",
        KB + r"[가-힣]{1,4}암\s?(?:치료|투병|환자|확진|말기)",
        r"종양", r"백혈병",
        r"몸살", r"아파서", r"병문안", r"희귀병|난치병", KB + r"산재\s?(?:신청|처리|승인)", KB + r"(?:약|진통제)\s?복용",
        # 감기 — '감기로 불참·감기 기운·감기에 걸려·감기약'. 감는 일(코일 감기·감기 로봇·되감기)은 아니다
        KB + r"감기(?:\s?(?:기운|몸살|때문)|(?:에)?\s?걸[려렸리린]|로(?![가-힣])|\s?약(?![가-힣]))",
        r"임신", r"출산", r"난임", r"정신과", r"정신\s?건강", r"우울증",
        r"공황\s?장애", r"불안\s?장애", r"심리\s?상담", r"상담\s?치료", r"처방전", r"응급실", r"장애인",
        r"장애\s?(?:등급|판정|진단|수당)", r"코로나(?:19)?\s?(?:확진|양성|감염)", r"확진\s?(?:판정|자)", r"독감", r"통원\s?치료",
        r"재활\s?치료", r"투약", r"복용\s?중", r"건강\s?(?:문제|악화|이상)", r"건강상(?:의)?\s?이유",
        r"병원\s?(?:진료|예약|검진|치료|입원|방문)", r"진료\s?(?:예약|확인서)", r"치료\s?(?:중|받)",
        r"(?:정형외과|산부인과|소아과|피부과|이비인후과|신경과|정신건강의학과|비뇨기과|한의원|치과)",
        KB + r"(?:내과|외과|안과)\s?(?:진료|예약|검진|방문|치료)",
        r"(?i:medical\s+certificate|sick\s+note|doctor'?s\s+note|hospitali[sz](?:ed|ation)|\bsurgery\b|pregnan(?:t|cy)"
        r"|chemotherapy|cancer\s+(?:treatment|diagnosis)|mental\s+health|psychiatri(?:st|c)|therapy\s+session"
        r"|\bdisability\b|tested\s+positive|\bprescription\b|diagnosed\s+with)",
    ],
    "union": [
        r"노조", r"노동\s?조합", r"단체\s?교섭", r"임단협", KB + r"단협", r"파업", r"쟁의", r"조합원", r"노사\s?협의",
        r"(?i:labou?r\s+union|trade\s+union|union\s+(?:member|meeting|dues|rep)|collective\s+bargaining|on\s+strike"
        r"|general\s+strike|\bwalkout\b)",
    ],
    "politics": [
        r"정당\s?(?:가입|활동|후원|지지|원)", KB + r"당원(?![가-힣])", r"당원\s?(?:가입|명부|모집|활동)", KB + r"입당",
        KB + r"탈당", r"선거\s?운동", r"지지\s?후보", r"후보\s?지지", r"정치\s?(?:후원|성향|활동|자금)",
        r"(?:대선|총선|지방선거)\s?(?:후보|캠프|투표|유세)", r"투표\s?인증", r"탄핵", r"촛불\s?집회", r"집회\s?(?:참가|참석|참여)",
        r"시위\s?(?:참가|참석|참여)", r"(?:더불어민주당|국민의힘|정의당|진보당|개혁신당|조국혁신당|기본소득당|녹색당)",
        r"(?i:political\s+(?:party|donation|campaign)|party\s+membership|election\s+campaign"
        r"|voted?\s+for\s+(?:the\s+)?(?:candidate|party))",
    ],
    "religion": [
        r"교회", r"성당", r"사찰", r"예배", r"주일\s?미사", KB + r"미사\s?(?:참석|드리)", r"기도회", r"법회",
        r"성경\s?공부", KB + r"큐티(?![가-힣])", KB + r"목사", r"신부님", r"스님", r"수녀", r"선교", r"세례", r"신앙", r"종교",
        r"불교", r"기독교", r"천주교", r"개신교", r"원불교", r"이슬람",
        r"(?i:\bchurch\b|\bprayers?\b|\bworship\b|bible\s+study|\bmosque\b|\bsynagogue\b|\breligio(?:n|us)\b"
        r"|\bbaptism\b|\bsermon\b)",
    ],
    "sex_life": [
        KB + r"성\s?생활", r"성적\s?지향", KB + r"성\s?소수자", r"동성애", KB + r"성\s?정체성", r"트랜스젠더", r"성관계",
        KB + r"성병", r"피임", r"성희롱", r"성추행", r"성폭력", r"성폭행", r"성매매",
        r"(?i:sexual\s+(?:orientation|harassment|assault)|sex\s+life|\blgbt\w*|\bgay\b|\blesbian\b|transgender"
        r"|contracepti(?:on|ve))",
    ],
    "criminal": [
        r"전과\s?(?:기록|자|조회|사실)", r"범죄\s?(?:경력|기록)", r"기소", r"형사\s?(?:처벌|고소|사건|재판)", r"벌금형", r"징역",
        r"집행\s?유예", r"구속\s?(?:영장|기소|수감)", r"체포", r"피의자", r"피고인", r"고소장",
        r"(?:경찰|검찰)\s?(?:조사|출석|소환)", r"음주\s?운전", r"성범죄", r"수사\s?(?:의뢰|기관|대상)", r"신원\s?조회",
        r"(?i:criminal\s+record|\bconvicted\b|\bconviction\b|\barrested\b|\bindicted\b|\bfelony\b|\bDUI\b"
        r"|police\s+investigation)",
    ],
}
# 예외 — 이 표현 안의 낱말은 민감정보로 보지 않는다(공학·안전·법정 의무 교육·조직 공지)
SENSITIVE_ALLOW = [
    r"안전\s?보건", r"산업\s?안전\s?보건", r"보건\s?관리자", r"보건\s?교육", r"건강성", r"신뢰성",
    r"성희롱\s?예방(?:\s?교육)?", r"성폭력\s?예방(?:\s?교육)?", r"성매매\s?예방(?:\s?교육)?", r"(?:4|사)\s?대\s?폭력\s?예방(?:\s?교육)?",
    r"폭력\s?예방\s?교육", r"직장\s?내\s?(?:성희롱|괴롭힘)(?:\s?예방)?(?:\s?교육)?",
    r"장애인\s?(?:인식\s?개선|고용)", r"장애인식\s?개선", r"수술용", r"수술\s?로봇", r"치과용", r"저출산", r"출산율", r"질병관리청",
    # 감기 = 감는 일(코일·권선·와이어 감기) — 공학 표현
    r"(?:코일|권선|와이어|케이블|테이프|필름|보빈|코어|전선|선재|스풀|모터|자석|" + KB + r"(?:실|롤))\s?감기",
    # 암 = arm(로봇 암·로어 암·컨트롤 암) — 기계 부품
    r"(?:로봇|로어|어퍼|컨트롤|로커|와이퍼|스윙|픽업|매니퓰레이터|크레인|붐|토션|텐션|리프트|서스펜션|트레일링)\s?암",
]
SENSITIVE_RX = {k: re.compile("|".join("(?:" + p + ")" for p in v)) for k, v in SENSITIVE_WORDS.items()}
_ALLOW_RX = re.compile("|".join("(?:" + p + ")" for p in SENSITIVE_ALLOW))


def _sens_cfg(cfg):
    sf = afcfg.get(cfg, "privacy.sensitiveFilter") or {}
    if not isinstance(sf, dict):
        sf = {}
    extra = tuple(sorted({str(x).strip() for x in _as_list(sf.get("extraWords")) if len(str(x).strip()) >= 2}))
    allow = tuple(sorted({str(x).strip() for x in _as_list(sf.get("allowWords")) if len(str(x).strip()) >= 2}))
    return extra, allow


@functools.lru_cache(maxsize=32)
def _sens_extra(extra, allow):
    """설정 추가어·예외어 → (추가어 정규식|None, 예외어 정규식|None). 예외어는 공학 문맥 낱말(시스템·설계·장비 …
    afcfg.allow_word_problem)이 든 표현만 받는다(SENSITIVE_ALLOW 처럼). 민감 낱말 그 자체도 받지 않는다 — '입원'·'입원으로'·
    '노조 회의' 를 예외로 적어 늘 켜진 규칙을 끌 수 없다(D5 · D22)."""
    ex = re.compile("|".join(re.escape(w) for w in sorted(extra, key=len, reverse=True)), re.I) if extra else None
    ok = []
    for w in allow:
        n = _nfkc(w)
        if afcfg.allow_word_problem(n) or any(rx.fullmatch(n) for rx in SENSITIVE_RX.values()):
            continue
        ok.append(re.escape(n))
    al = re.compile("|".join(sorted(ok, key=len, reverse=True)), re.I) if ok else None
    return ex, al


def sensitive_hit(text, cfg=None):
    """민감정보(D5) 범주 → "health"|"union"|"politics"|"religion"|"sex_life"|"criminal"|"custom"(설정 추가어) | None.
    예외 표현(SENSITIVE_ALLOW ∪ privacy.sensitiveFilter.allowWords)을 먼저 지우고 본다. 설정은 낱말을 더하기만 한다."""
    if not text:
        return None
    t = _nfkc(text)
    extra, allow = _sens_cfg(cfg)
    ex, al = _sens_extra(extra, allow)
    t = _ALLOW_RX.sub(" ", t)
    if al is not None:
        t = al.sub(" ", t)
    for cat, rx in SENSITIVE_RX.items():
        if rx.search(t):
            return cat
    if ex is not None and ex.search(t):
        return "custom"
    return None


# ── 식별번호(D6) — 문맥 낱말 없이 맨 형태로. 가린 뒤 글에 남아 있으면 그 행은 버린다(G1)·보내지 않는다(G3).
#    체크섬이 있는 것(주민·카드)은 체크섬으로, 공학 코드와 겹치는 형태(여권·면허·계좌)는 바로 앞 공학 문맥(도번·LOT·P/N …)만 뺀다.
_ID_RRN = re.compile(NB + r"\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\s?(?P<hy>-)?\s?[1-8]\d{6}" + NA)
_ID_PASSPORT = re.compile(NBX + r"[MSRODG]\d{3}[A-Z0-9]\d{4}" + NAX)
_ID_LICENSE = re.compile(NBX + r"(?:1[1-9]|2[0-8])-\d{2}-\d{6}-\d{2}" + NAX)
_ID_ACCOUNT = re.compile(NBX + r"\d{2,6}(?:-\d{2,7}){2,4}" + NAX)


def _strong_identifier(t):
    """체크섬·구조로 정해지는 식별번호 — 주민·외국인등록(생년월일·성별 자리 유효 + 하이픈 또는 체크섬 · 2020-10 이후 번호는
    체크섬이 없으므로 맨 13자리도 바로 앞이 공학·주문 번호 문맥(도번·P/N·LOT·코드·PO·#)이 아니면) · 카드(16·15자리, Luhn —
    띄어쓰기·하이픈·'.'·'/' 로 끊어도) · 계좌(하이픈 3묶음 이상, 숫자 10~14 · 연도로 시작하거나 전화 형식이면 아님 · 바로 앞 공학
    문맥이면 아님). t 는 NFKC 한 글."""
    def eng(s):
        return _eng_before(t, s)

    for m in _ID_RRN.finditer(t):
        d = _digits(m.group(0))
        if rrn_date_ok(d) and (m.group("hy") or rrn_checksum_ok(d) or not (eng(m.start()) or _order_before(t, m.start()))):
            return True
    for rx in (RX["card16"], RX["card15"]):
        for m in rx.finditer(t):
            if luhn_ok(_digits(m.group(0))):
                return True
    for m in _ID_ACCOUNT.finditer(t):
        g = m.group(0)
        n = len(_digits(g))
        if not 10 <= n <= 14 or eng(m.start()):
            continue
        if (re.match(r"(?:19|20)\d{2}-", g) or RX["mobile"].fullmatch(g) or RX["landline"].fullmatch(g)
                or RX["landline82"].fullmatch(g)):
            continue
        return True
    return False


def _shields_identifier(s):
    """허용 패턴에 맞은 부분 s 에 주민·외국인등록·카드·전화·메일 주소·계좌 꼴이 들었나 — 들었으면 그 부분은 보호하지 않는다
    (privacy.allowPatterns 가 늘 켜진 판정을 약하게 만들지 못하게 · D22). 판정은 넉넉하게(보호하지 않는 쪽으로) 한다."""
    t = _nfkc(s)
    if not re.search(r"\d|@", t):
        return False
    if (RX["email"].search(t) or RX["mobile"].search(t) or RX["landline"].search(t) or RX["landline82"].search(t)
            or RX["intl"].search(t)):
        return True
    for m in _ID_RRN.finditer(t):
        if rrn_date_ok(_digits(m.group(0))):
            return True
    if re.search(r"\d{10,16}", t):
        return True                                   # 맨 숫자 10~16자리(계좌·카드·주민 꼴)
    return _strong_identifier(t)


def has_identifier(text, *, allow_patterns=()):
    """맨 식별번호가 있는가(D6): 주민·외국인등록번호(생년월일·성별 자리 유효 + 하이픈 또는 체크섬) · 여권(M·S·R·O·D·G + 8자) ·
    운전면허(하이픈 형식·지역명 형식) · 카드(16·15자리, Luhn) · 계좌(하이픈 3묶음 이상, 숫자 10~14 · 연도로 시작하거나 전화 형식이면
    아님). 이미 가린 토큰([주민번호] 등)은 숫자가 없다.
    allow_patterns(정규식 — privacy.allowPatterns)에 맞는 부분은 공학 코드와 겹치는 여권·운전면허 꼴만 보지 않는다 — 주민·외국인등록·
    카드·계좌는 허용 패턴과 상관없이 본다(D22 — 설정은 늘 켜진 규칙을 약하게 만들지 못한다)."""
    if not text:
        return False
    t = _nfkc(text)
    if _strong_identifier(t):
        return True
    for p in _compile_allow(allow_patterns):
        t = p.sub(lambda m: " " if _code_span_ok(m.group(0)) else m.group(0), t)

    def eng(s):
        return ENG_CTX.search(t[max(0, s - 10):s]) is not None

    for m in _ID_PASSPORT.finditer(t):
        if not eng(m.start()):
            return True
    for m in _ID_LICENSE.finditer(t):
        if not eng(m.start()):
            return True
    if RX["license_region"].search(t):
        return True
    return False


# ── 근태·행방(D4) ──────────────────────────────────────────────────────────────────────────
# 낱말 뒤에 올 수 있는 것(근태어가 다른 낱말의 첫머리가 아닐 때) — 끝·한글 아님·조사·신청류
_ADMIN_END = (r"(?=$|[^가-힣]|신청|사용|처리|승인|결재|계획|일정|중|로|를|는|은|이|가|도|자|표|일|근무|예정|기간|수당|식대|비|교대"
              r"|명령|대체|확인|현황|내역|기록)")
# 근태가 아닌 같은 글자 — 공가(共架: 전주·통신 설비를 함께 쓰는 일) · 월차(달마다 하는 결산·보고·회의)
_GONGGA = r"공가(?!\s?(?:설비|전주|케이블|선로|통신|구간|시설|공사|점용))"
_WOLCHA = r"(?<![가-힣\d])월차(?!\s?(?:결산|보고|손익|회의|마감|실적|점검))"
ADMIN_RX = re.compile(
    r"(?i)(근태|반반차|반차|연차(?!\s?보고서|별|\s?평가)|휴가|병가|조퇴|지각|외출|외근|재택|출장|건강\s?검진"
    r"|부재(?![료력재])|(?<![a-z])oof(?![a-z])|out\s+of\s+(?:the\s+)?office|working\s+elsewhere"
    # 휴직·복직·특근·야근·당직·휴일 근무·결근·월차·반휴·공가·예비군·민방위 · 자동 회신(Outlook 부재 회신 머리)
    r"|휴직|무단\s?결근|(?:(?<![가-힣])(?:복직|특근|야근|당직|결근|반휴|" + _GONGGA + r")|" + _WOLCHA + r")" + _ADMIN_END
    + r"|휴일\s?근무|주말\s?근무"
    r"|예비군(?!수)|민방위|자동\s?회신\s?[:：]|automatic\s+reply\s*[:：]"
    r"|(?<![a-z])vacations?(?![a-z])|(?:annual|sick|parental|maternity|paternity)\s+leave|(?<![a-z])pto(?![a-z])"
    r"|(?<![a-z])wfh(?![a-z])|work(?:ing)?\s+from\s+home|(?<![a-z])(?:day|days|time)\s+off(?![a-z]))")
_STRUCT_RX = re.compile(r"(?:구조|철골|강재|기둥|트러스|프레임|용접|접합|응력|좌굴|단면|하중|설계|해석|보\s|부재력)")
# 기계의 PTO(동력 인출 장치 — 트랙터·변속기) 문맥 — 근태의 PTO(유급 휴가)가 아니다
_PTO_ENG_RX = re.compile(r"(?i)(?:shaft|축|기어|gear|클러치|clutch|구동|drive|rpm|동력|트랙터|tractor|변속|감속|출력)")


def admin_hit(text):
    """근태·행방 항목인가(D4) — 근태·연차·반차·반반차·휴가·병가·조퇴·지각·외출·외근·재택·출장·건강검진·부재·OOF·out of office·
    working elsewhere · 휴직(육아휴직·무급휴직)·복직·특근·야근·당직·휴일/주말 근무·결근·월차·반휴·공가·예비군·민방위·
    '자동 회신:' · vacation·annual/sick/parental leave·PTO·WFH·work from home·day off·time off(신청·계획·승인·결재가 붙어도 같다).
    구조 공학의 '부재'(구조 부재·부재력), 기계의 PTO(동력 인출 축·기어), 공가(共架) 설비·전주, 월차 결산·보고는 아니다."""
    if not text:
        return False
    t = _nfkc(text)
    for m in ADMIN_RX.finditer(t):
        near = t[max(0, m.start() - 6):m.end() + 6]
        if m.group(0).startswith("부재") and _STRUCT_RX.search(near):
            continue
        if m.group(0).lower() == "pto" and _PTO_ENG_RX.search(t[max(0, m.start() - 12):m.end() + 12]):
            continue
        return True
    return False


# ── 개인 키워드 ────────────────────────────────────────────────────────────────────────────
def excluded_keywords(cfg=None):
    """개인 주제어 = 내장 EXCLUDE ∪ privacy.excludeKeywords (정렬 목록). G1·mine·judge·refine 이 같이 쓴다."""
    vals = afcfg.get(cfg if isinstance(cfg, dict) else {}, "privacy.excludeKeywords") or []
    return sorted(set(EXCLUDE) | {str(k).strip() for k in _as_list(vals) if str(k).strip()})


@functools.lru_cache(maxsize=32)
def _kw_matcher(words):
    kr = [w for w in words if not w.isascii()]
    asc = [w for w in words if w.isascii()]
    pat = re.compile("|".join(f"(?<![a-z0-9]){re.escape(w)}(?![a-z0-9])" for w in asc)) if asc else None
    return tuple(kr), pat


def keyword_hit(text, cfg=None, words=None):
    """개인 주제어에 걸리면 그 낱말, 아니면 None. 한글은 부분 일치('개인'⊂'개인자료'), 영문은 단어 경계('temp'⊄'template')."""
    low = _nfkc(text).lower()
    if not low:
        return None
    ws = tuple(sorted({str(w).lower() for w in (words if words is not None else excluded_keywords(cfg)) if str(w).strip()}))
    kr, pat = _kw_matcher(ws)
    h = next((w for w in kr if w in low), None)
    if not h and pat is not None:
        m = pat.search(low)
        h = m.group(0) if m else None
    return h


# ── 제한 고객(D9) ──────────────────────────────────────────────────────────────────────────
_CO_HEAD_RX = re.compile(r"^\s*(?:\(\s*(?:주|유|사|재|합|株)\s*\)|주식\s?회사|유한\s?회사|합자\s?회사|株式会社)\s*")
_CO_TAIL_RX = re.compile(r"(?:\s*(?:\(\s*(?:주|유|株)\s*\)|주식\s?회사|유한\s?회사|社)"
                         r"|(?:\s*,\s*|\s+)(?:co\.?\s*,?\s*ltd\.?|co\.?|inc\.?|corp\.?|corporation|llc|gmbh|ltd\.?|limited|plc))"
                         r"\s*$", re.I)


def company_core(name):
    """회사 형태((주)·㈜·주식회사·유한회사·社·Inc.·Co., Ltd.·Corp.·LLC·GmbH …)를 앞뒤에서 뗀 이름 — 뗀 것이 없거나 2자 미만이면 ""."""
    s0 = _nfkc(name).strip()
    s = s0
    for _ in range(3):
        s2 = _CO_TAIL_RX.sub("", _CO_HEAD_RX.sub("", s)).strip(" ,.")
        if s2 == s:
            break
        s = s2
    return s if s != s0 and len(_FLEX_SEPS_RX.sub("", s)) >= 2 else ""


def domain_norm(v):
    """도메인 표기 → 소문자 도메인. 'sales@hanbit.example'·'https://도메인/…'·'@Hanbit.example'·'www.hanbit.example.' 모두
    'hanbit.example'(주소의 앞부분·경로·www. 는 뗀다). 도메인 꼴이 아니면 ""."""
    s = _nfkc(v).strip()
    if "@" in s:
        s = s.rsplit("@", 1)[1]
    s = re.sub(r"^[A-Za-z][A-Za-z0-9+.\-]*://", "", s)
    s = re.split(r"[/?#:\s]", s, maxsplit=1)[0].lower().rstrip(".")
    if s.startswith("www."):
        s = s[4:]
    return _dom_norm(s)


class Restricted:
    """제한 고객 목록(config\\restricted_customers.json) — 이름·약칭·도메인. load_restricted 가 만든다.
    path·sha256(파일 바이트의 sha256 — run_meta.restricted_sha256)·confirmed('YYYY-MM-DD')·customers[{name,aliases,domains}].
    이름·약칭은 NFKC 로 맞추고, 회사 형태를 뗀 이름((주)한빛정밀 → 한빛정밀)도 약칭으로 더한다. 3자 이상 이름은 띄어쓰기·
    하이픈 변형('LG 에너지솔루션'·'Han-bit')에도 맞고, 영문 이름 뒤에는 숫자가 붙어도 맞는다('Hanbit2026')."""

    def __init__(self, customers=(), *, path="", sha256="", confirmed=""):
        self.path, self.sha256, self.confirmed = path, sha256, confirmed
        self.customers = []
        names, doms = [], []
        for c in customers or ():
            if not isinstance(c, dict):
                continue
            nm = c.get("name")
            nm = _nfkc(nm).strip() if isinstance(nm, str) else ""
            al = [_nfkc(x).strip() for x in _as_list(c.get("aliases")) if isinstance(x, str) and x.strip()]
            ds = [d for d in (domain_norm(x) for x in _as_list(c.get("domains")) if isinstance(x, str)) if d]
            if not (nm or al or ds):
                continue
            self.customers.append({"name": nm, "aliases": al, "domains": ds})
            for x in [nm] + al:
                if len(x) >= 2:
                    names.append(x)
                core = company_core(x)
                if core:
                    names.append(core)
            doms += ds
        self.names = tuple(dict.fromkeys(names))
        self.domains = tuple(dict.fromkeys(doms))
        self._rx = _dict_rx(self.names) if self.names else None
        self._drx = _domain_rx(self.domains) if self.domains else None
        # 주소 앞부분용 — 영문 4자 이상 이름만('hanbit-tf@…'). 2~3자 약칭('HB')은 사람의 머리글자 주소('hb.kim@…')와 겹친다
        local = tuple(n for n in self.names if n.isascii() and len(flex_key(n)) >= 4)
        self._lrx = _dict_rx(local) if local else None

    @classmethod
    def empty(cls):
        """빈 목록(제한 고객 없음) — 시험·명시적 호출용."""
        return cls((), confirmed="")

    def terms(self):
        """가릴 이름·약칭 목록(긴 것부터)."""
        return sorted(self.names, key=len, reverse=True)

    def info(self):
        """화면·리포트용 요약 — {"confirmed": 'YYYY-MM-DD', "sha8": 파일 sha256 앞 8자, "customers": 고객 수}(이름은 없다)."""
        return {"confirmed": self.confirmed, "sha8": str(self.sha256 or "")[:8], "customers": len(self.customers)}

    def hit(self, text="", domains=()):
        """글(제목·장소·본문·참여자 표시 이름)에 이름·약칭·도메인(맨 도메인·하위 도메인 포함)이 있거나, 참여자 도메인(domains)
        중 하나가 제한 고객 도메인(또는 그 하위)인가. 글은 NFKC·폭 0 문자 제거(_nfkc) 뒤에 본다."""
        t = _nfkc(text) if text else ""
        if self._rx is not None and t and self._rx.search(t):
            return True
        if self.domains:
            got = {d for d in (_dom_norm(x) for x in domains or ()) if d} | domains_in(t)
            for d in got:
                if any(d == x or d.endswith("." + x) for x in self.domains):
                    return True
            if t and self._drx is not None and self._drx.search(t):
                return True
        return False

    def hit_local(self, local_parts):
        """참여자 주소의 앞부분(@ 앞) 가운데 제한 고객의 영문 이름·약칭(4자 이상)이 든 것이 있는가 — 'hanbit-tf'·'hanbit.sales'."""
        if self._lrx is None:
            return False
        return any(self._lrx.search(_nfkc(x)) for x in local_parts or () if x)


_RESTRICTED_CACHE = {}
_RESTRICTED_TOP = ("confirmed", "customers")
_RESTRICTED_KEYS = ("name", "aliases", "domains")


class _DupKey(ValueError):
    """JSON 객체에 같은 키가 두 번 — 마지막 값만 남는 조용한 덮어쓰기를 막는다."""


def _pairs_no_dup(pairs):
    d = {}
    for k, v in pairs:
        if k in d:
            raise _DupKey(k)
        d[k] = v
    return d


def _no_json_const(c):
    raise ValueError(f"JSON 상수 {c} 는 받지 않습니다")


def _restricted_invalid(where):
    """형식이 틀린 목록 파일의 오류 — detail 'invalid', .where = 틀린 곳(문장 끝에도 붙인다 — 운영 담당이 고칠 곳)."""
    msg = RESTRICTED_TEMPLATE_MSG if where == "_template" else f"{RESTRICTED_BAD_MSG}(틀린 곳: {where})"
    return RestrictedListError(msg, "invalid", where)


def _check_restricted_doc(d, today=None):
    """제한 고객 목록 문서 검사 — 틀린 곳이 있으면 RestrictedListError('invalid', .where = 'customers[2].domains' 꼴)."""
    from datetime import date as _date
    if not isinstance(d, dict):
        raise _restricted_invalid("(최상위)")
    for k in d:
        if str(k).startswith("_"):
            if k == "_template":
                raise _restricted_invalid("_template")        # 배포 견본을 그대로 복사한 파일 — 목록이 아니다
            continue
        if k not in _RESTRICTED_TOP:
            raise _restricted_invalid(str(k))
    if not isinstance(d.get("customers"), list):
        raise _restricted_invalid("customers")
    conf = d.get("confirmed")
    if not isinstance(conf, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", conf.strip()):
        raise _restricted_invalid("confirmed")
    try:
        cd = _date.fromisoformat(conf.strip())
    except ValueError:
        raise _restricted_invalid("confirmed") from None
    if cd > (today or _date.today()):
        raise _restricted_invalid("confirmed")               # 앞날 — 확인한 날이 아니다
    for i, c in enumerate(d["customers"]):
        w = f"customers[{i}]"
        if not isinstance(c, dict):
            raise _restricted_invalid(w)
        for k in c:
            if not (k in _RESTRICTED_KEYS or str(k).startswith("_")):
                raise _restricted_invalid(f"{w}.{k}")
        nm = c.get("name")
        if nm is not None and not isinstance(nm, str):
            raise _restricted_invalid(w + ".name")
        nm = _nfkc(nm or "").strip()
        if nm and len(nm) < 2:
            raise _restricted_invalid(w + ".name")
        al = c.get("aliases")
        al = [] if al is None else al
        if not isinstance(al, list) or any(not isinstance(x, str) or len(_nfkc(x).strip()) < 2 for x in al):
            raise _restricted_invalid(w + ".aliases")
        ds = c.get("domains")
        ds = [] if ds is None else ds
        if not isinstance(ds, list) or any(not isinstance(x, str) or not domain_norm(x) for x in ds):
            raise _restricted_invalid(w + ".domains")
        if not nm and not ds:
            raise _restricted_invalid(w + ".name")               # 이름이나 도메인 하나는 있어야 한다(약칭만으로는 안 된다)


def restricted_path(cfg, root=None):
    r"""제한 고객 목록 파일 경로 — privacy.restrictedCustomersFile(설치 폴더 기준 상대 또는 절대)."""
    p = str(afcfg.get(cfg, "privacy.restrictedCustomersFile") or "config\\restricted_customers.json")
    p = p.replace("/", os.sep).replace("\\", os.sep)
    return p if os.path.isabs(p) else os.path.join(str(root or ROOT), p)


def load_restricted(cfg, root=None):
    """제한 고객 목록 → Restricted. 파일이 없거나 형식이 틀리면 RestrictedListError(분석·공유 거부, 종료 코드 4 ·
    형식 오류는 detail 'invalid' 와 틀린 곳 .where).
    형식: {"confirmed": "YYYY-MM-DD"(확인한 날 — 앞날은 안 된다), "customers": [{"name": 2자 이상(도메인이 있으면 비워도 된다),
    "aliases": [2자 이상 글], "domains": [도메인('x@도메인'·'https://도메인/…' 도 받는다)]}]} — '_' 로 시작하는 키는 설명.
    같은 키를 두 번 쓰거나 NaN·Infinity·모르는 키·'_template'(배포 견본 그대로)가 있으면 받지 않는다."""
    p = restricted_path(cfg, root)
    try:
        st = os.stat(p)
        key = (os.path.normcase(os.path.abspath(p)), st.st_mtime_ns, st.st_size)
    except OSError:
        raise RestrictedListError(RESTRICTED_MSG, "missing") from None
    if key in _RESTRICTED_CACHE:
        return _RESTRICTED_CACHE[key]
    try:
        with open(p, "rb") as f:
            raw = f.read()
        d = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_pairs_no_dup, parse_constant=_no_json_const)
    except (OSError, ValueError, UnicodeDecodeError, RecursionError):
        raise _restricted_invalid("json") from None
    _check_restricted_doc(d)
    r = Restricted(d["customers"], path=p, sha256=hashlib.sha256(raw).hexdigest(), confirmed=d["confirmed"].strip())
    if len(_RESTRICTED_CACHE) > 16:
        _RESTRICTED_CACHE.clear()
    _RESTRICTED_CACHE[key] = r
    return r


def restricted_hit(text, restricted, domains=()):
    """제한 고객 이름·약칭·도메인이 글에 있거나 참여자 도메인이 제한 고객의 것인가. restricted 가 None 이면 True(닫는다)."""
    if restricted is None:
        return True
    return restricted.hit(text, domains)


# ── 사내/사외(D7) ──────────────────────────────────────────────────────────────────────────
_ADDR_RX = re.compile(r"[A-Za-z0-9._%+'\-]{1,64}@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,24}")
_BARE_DOM_RX = re.compile(r"@?([A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,24})")


def parse_people(s):
    """';' 로 이은 'Name <addr>' 목록(또는 주소·도메인만) → [(이름, 주소(소문자)|"", 도메인|"")]. 주소를 못 읽으면 ("이름", "", "")."""
    out = []
    for part in re.split(r"[;\r\n]+", str(s or "")):
        part = part.strip().strip(",").strip()
        if not part:
            continue
        name, addr = part, ""
        m = re.match(r"^(.*?)\s*<([^<>]*)>\s*$", part)
        if m:
            name, inner = m.group(1).strip().strip("\"'").strip(), m.group(2).strip()
            a = _ADDR_RX.search(inner)
            addr = a.group(0).lower() if a else ""
            if not addr and (dm := _BARE_DOM_RX.fullmatch(inner)):
                out.append((name, "", dm.group(1).lower()))
                continue
        else:
            a = _ADDR_RX.search(part)
            if a:
                addr = a.group(0).lower()
                name = (part[:a.start()] + part[a.end():]).strip(" \"'()<>")
            elif (dm := _BARE_DOM_RX.fullmatch(part)) and "." in part and " " not in part:
                out.append(("", "", dm.group(1).lower()))
                continue
        out.append((name, addr, addr.split("@", 1)[1] if addr else ""))
    return out


def internal_domains(cfg=None, my_addresses=()):
    """사내 도메인 집합 = privacy.internalDomains ∪ 내 주소들의 도메인(채널이 본 것). 공용 개인 메일 도메인(gmail·naver …)은
    사내가 아니다 — 프로필의 개인 계정 주소가 그 도메인 사람 모두를 사내로 만들지 못한다(D7)."""
    out = {d for d in (_dom_norm(x) for x in _as_list(afcfg.get(cfg, "privacy.internalDomains"))) if d}
    for a in my_addresses or ():
        d = domain_of(a) or _dom_norm(a)
        if d:
            out.add(d)
    return {d for d in out if d not in PERSONAL_MAIL_DOMAINS}


def _is_internal_dom(dom, internal):
    d = _dom_norm(dom)
    return bool(d) and any(d == x or d.endswith("." + x) for x in internal)


def external_status(addrs, internal):
    """참여자 주소들 → "internal" | "external" | "unknown".
    사외 도메인이 하나라도 보이면 external, 주소를 읽지 못한 사람이 있거나 아무도 없거나 사내 목록이 비면 unknown,
    모두 사내 도메인(또는 그 하위)이면 internal. addrs = 주소 문자열·'Name <addr>'·도메인·(이름, 주소, 도메인) 튜플."""
    internal = {d for d in (_dom_norm(x) for x in internal or ()) if d}
    people = []
    for a in addrs or ():
        if isinstance(a, tuple):
            people.append(a)
        else:
            people += parse_people(a)
    if not people or not internal:
        return "unknown"
    unknown = False
    for _n, _a, dom in people:
        if not dom:
            unknown = True
        elif not _is_internal_dom(dom, internal):
            return "external"
    return "unknown" if unknown else "internal"


# ── 공지·시스템 발신자(extract.is_notice 에서 옮김 — G1 이 notice 0/1 로 정한다) ─────────────────────────
NOTICE_DEFAULT = ["no-reply", "noreply", "do-not-reply", "알림", "notification", "notice", "뉴스레터", "newsletter",
                  "웹진", "webzine", "공지", "설문", "survey", "시스템", "sharepoint", "yammer", "viva", "helpdesk",
                  "보안", "보안공지", "(광고)", "광고", "promotion", "프로모션", "마케팅", "수신거부", "unsubscribe"]
NOTICE_GENERIC = {"시스템", "system", "공지", "알림", "설문", "보안", "광고", "마케팅", "viva", "notice",
                  "survey", "promotion", "프로모션", "notification"}
_NOTICE_SEG = re.compile(r"[\s/|,;()\[\]<>\"'@._-]+")


def notice_words(cfg=None):
    """공지 발신자 낱말 — config.noticeSenders(없으면 NOTICE_DEFAULT), 소문자."""
    vals = cfg.get("noticeSenders") if isinstance(cfg, dict) else None
    vals = vals if isinstance(vals, list) and vals else NOTICE_DEFAULT
    return [str(x).strip().lower() for x in vals if str(x).strip()]


def is_notice_sender(sender, cfg=None, *, replied=(), words=None):
    """공지·시스템 발신자 판정 — 표시 이름·주소를 조각으로 나눠 본다. 일반 명사(시스템·공지·알림…)는 조각 전체 일치만,
    구분자가 든 낱말('no-reply')은 부분 문자열, 나머지는 조각 시작 일치. 회신 이력이 있는 발신자(replied)는 공지가 아니다."""
    s = str(sender or "").strip().lower()
    if not s or s in replied:
        return False
    segs = [x for x in _NOTICE_SEG.split(s) if x]
    for k in (words if words is not None else notice_words(cfg)):
        kk = k.strip("()[] ")
        if not kk:
            continue
        if _NOTICE_SEG.search(kk):
            if kk in s:
                return True
        elif kk in NOTICE_GENERIC:
            if kk in segs:
                return True
        elif any(seg == kk or seg.startswith(kk) for seg in segs):
            return True
    return False


# ── 이름·가명(D8) ──────────────────────────────────────────────────────────────────────────
PSEUDO_RX = re.compile(r"p:[0-9a-f]{12}")
# 이름 조각(성을 뺀 이름)이 흔한 업무어·낱말과 같으면 호칭·멘션이 붙었을 때만 가린다(그 밖에는 업무어로 둔다) — 해시에도 넣지 않는다
NAME_PART_STOP = frozenset({
    "지원", "수정", "진행", "정보", "보안", "현장", "시험", "설계", "개발", "기술", "전략", "관리", "운영", "영업", "품질", "생산",
    "구매", "재무", "인사", "총무", "연구", "분석", "검토", "보고", "확인", "요청", "공유", "회의", "자료", "일정", "검증", "평가",
    "안전", "환경", "표준", "혁신", "미래", "성장", "가치", "나라", "하나", "한결", "다운", "보람", "은혜", "사랑", "소망", "기쁨",
    "슬기", "나래", "믿음", "새롬", "초롱", "한별", "지혜", "진실", "성실", "용기", "희망", "행복", "다솜", "한솔", "가람", "누리",
    "온유", "주연", "정상", "상수", "변수", "현재", "대상", "정도", "상태", "영상", "전기", "전자", "통신", "제어", "기계", "소재",
    "부품", "공정", "장비", "설비", "원가", "단가", "견적", "계약", "발주", "납기", "출하", "입고", "재고", "도면", "사양", "규격",
    "문서", "양식", "결재", "승인", "협의", "조율", "준비", "정리", "완료", "시작", "종료", "재원", "주원", "지수", "수지", "정수",
    "상현", "현상", "성능", "기준", "시장", "고객", "제품", "과제", "업무", "담당", "총괄", "대표", "부장", "차장", "과장", "대리",
    "young", "park", "song", "sun", "min", "may", "june", "will", "mark", "grace", "joy", "hope", "rose", "ray", "bill",
    "art", "jack", "frank", "max", "lane", "dean", "gun", "jung", "han", "kang", "moon", "bae", "ha", "an", "no", "do", "ma",
})
_NAME_ORG_STOP = frozenset({
    "team", "group", "dept", "department", "it", "hr", "qa", "qc", "admin", "service", "services", "system", "support",
    "help", "desk", "helpdesk", "no", "reply", "noreply", "info", "notice", "news", "the", "of", "and", "corp", "inc", "ltd",
    "co", "center", "centre", "office", "lab", "project", "bot", "alert", "alerts", "notification", "mailer", "daemon",
    "postmaster", "microsoft", "outlook", "teams", "calendar", "room", "meeting", "회의실", "공용", "팀", "실", "센터", "본부",
    # 성씨 글자로 시작하는 시스템·조직 낱말(표시 이름 '시스템 알림'·'보안 담당' 이 사람 이름으로 잡히지 않게)
    "시스템", "알림", "공지", "관리자", "담당자", "운영자", "헬프데스크", "고객센터", "전산", "보안", "설문", "교육", "인사", "총무",
    "구매", "품질", "생산", "기술", "연구", "개발", "자동", "회신", "안내", "발신", "수신", "전용", "공유", "일정", "예약",
    # 표시 이름의 부서 조각('김민수/마케팅'·'이서연 (서비스)')
    "마케팅", "서비스", "모바일", "반도체", "배터리", "홍보", "경영", "기획", "영업", "재무", "회계", "전략", "물류", "법무",
    "감사", "비서", "사무", "행정", "시설", "안전", "고객지원", "경영지원", "사업부", "연구소", "디자인", "솔루션", "플랫폼",
})
_TITLE_WORDS = re.compile(r"\s*(?:" + TITLES[3:-1] + r"|님|씨|님께)\s*$")
_EN_TITLE = re.compile(r"(?i)^(?:mr|mrs|ms|miss|dr|prof)\.?\s+")
_NAME_SEG_RX = re.compile(r"[()\[\]/|;（）【】{}]+")          # 표시 이름의 조각 구분(괄호·'/'·'|'·';')
_LAST_FIRST_RX = re.compile(r"[A-Za-z][A-Za-z'\-]*(?:\s+[A-Za-z][A-Za-z'\-]*)?\s*,\s*[A-Za-z][A-Za-z'\-]*"
                            r"(?:\s+[A-Za-z][A-Za-z'\-]*)?")


_NAME_ORG_SUFFIX = ("팀", "측", "처", "실", "부", "과", "단", "소", "국", "청", "사", "회")


def _hangul_name_ok(n):
    """표시 이름의 한글 덩어리가 사람 이름 같은가 — 3자(흔한 성)·4자(복성)·2자(성+외자, 흔한 낱말 아님). 조직 접미(팀·실·부…)는 아니다."""
    if n in NAME_STOP or n.endswith(_NAME_ORG_SUFFIX):
        return False
    if len(n) == 3:
        return n[0] in SURNAMES
    if len(n) == 4:
        return n[:2] in COMPOUND_SURNAMES
    return len(n) == 2 and n[0] in SURNAMES and n not in NAME_PART_STOP


def _seg_name_tokens(seg, first):
    """표시 이름의 한 조각 → ([전체 이름], [조각]). 숫자가 든 낱말(설계1팀·Team2)·직함·조직 낱말만 빼고 나머지 낱말을 본다.
    첫 조각이 아니면(괄호·'/' 뒤 — 부서·직급이 흔하다) 2자 한글과 한 낱말 영문은 이름으로 보지 않는다."""
    full, parts = [], []
    seg = _TITLE_WORDS.sub("", seg.strip().strip("\"'")).strip()
    words = [w for w in seg.split() if not any(ch.isdigit() for ch in w)]
    han = [h for w in words for h in re.findall(r"[가-힣]+", w)]
    if han:
        for h in han:
            if h.lower() in _NAME_ORG_STOP or h in NAME_STOP or h in TITLE_WORDS or (not first and len(h) == 2):
                continue
            if _hangul_name_ok(h):
                full.append(h)
                given = h[2:] if len(h) == 4 else (h[1:] if len(h) == 3 else "")
                if len(given) >= 2:
                    parts.append(given)
        return full, parts
    s2 = _EN_TITLE.sub("", " ".join(words))
    if "," in s2:
        a, b = (x.strip() for x in s2.split(",", 1))
        lw = re.findall(r"[A-Za-z][A-Za-z'\-]+", b + " " + a)
    else:
        lw = re.findall(r"[A-Za-z][A-Za-z'\-]+", s2)
    if lw and not any(w.lower() in _NAME_ORG_STOP for w in lw) and 1 <= len(lw) <= 4 and (first or len(lw) >= 2):
        if len(lw) >= 2:
            head, last = " ".join(lw[:-1]), lw[-1]
            full += [" ".join(lw), " ".join(lw[::-1]), f"{last}, {head}", f"{head}, {last}"]
        parts += [w for w in lw if len(w) >= 2]
    return full, parts


@functools.lru_cache(maxsize=4096)
def name_tokens(display):
    """표시 이름 하나 → (전체 이름들, 조각들). 사람 이름 같지 않은 것(부서·시스템·주소만)은 빈 튜플.
    괄호·'/'·'|'·';'·쉼표로 나눈 모든 조각을 본다('Gildong Choi (최길순)'·'김철수 설계1팀'·'[외부] 이영희') — 숫자가 든 낱말·
    직함·조직 낱말만 빼고 이름 전체를 버리지 않는다. 한글: 3자(흔한 성)·4자(복성)·2자(성+외자 — 첫 조각에서만) 이름, 조각은
    성을 뺀 이름(2자 이상). 영문: 'First Last'·'Last First'·'Last, First' 와 2자 이상 낱말(첫 조각이 아니면 두 낱말 이상만)."""
    s = unicodedata.normalize("NFKC", str(display or "")).strip()
    s = _ADDR_RX.sub(" ", re.sub(r"<[^<>]*>", " ", s))
    full, parts = [], []
    first = True
    for seg in _NAME_SEG_RX.split(s):
        seg = seg.strip().strip("\"'").strip()
        if not seg:
            continue
        for sub in ([seg] if _LAST_FIRST_RX.fullmatch(seg) else seg.split(",")):
            sub = sub.strip()
            if not sub:
                continue
            f, p = _seg_name_tokens(sub, first)
            first = False
            full += f
            parts += p
    return tuple(dict.fromkeys(full)), tuple(dict.fromkeys(p for p in parts if p not in full))


def _name_key(tok):
    return unicodedata.normalize("NFKC", str(tok or "")).strip().lower()


def _hmac_hex(salt, value):
    key = str(salt or "").encode("utf-8")
    return hmac.new(key, str(value).encode("utf-8"), hashlib.sha256).hexdigest()


def pseudonym(value, salt):
    """가명 'p:' + HMAC-SHA256(설치 소금, 정규화한 주소 또는 이름)[:12]. 값이 비면 "". 소금은 install.salt(root)."""
    v = str(value or "").strip()
    if not v:
        return ""
    a = _ADDR_RX.search(v)
    norm = a.group(0).lower() if a else re.sub(r"\s+", " ", unicodedata.normalize("NFKC", v)).strip().lower()
    return "p:" + _hmac_hex(salt, norm)[:12]


def name_hash(token, salt):
    """이름 조각의 해시(16 hex) — data\\cache\\name_hashes.json 에 이것만 남는다."""
    return _hmac_hex(salt, "n:" + _name_key(token))[:16]


@functools.lru_cache(maxsize=256)
def _name_rx(full, parts):
    """(전체 이름, 조각) → 정규식 두 개(늘 가림 · 호칭/멘션이 붙을 때만 가림)."""
    def alt(names):
        uniq = sorted({n for n in names if n}, key=lambda n: (-len(n), n))
        kr = [re.escape(n) for n in uniq if re.search(r"[가-힣]", n)]
        en = [re.escape(n).replace(r"\ ", r"\s+") for n in uniq if not re.search(r"[가-힣]", n)]
        ps = []
        if kr:
            ps.append(r"(?<![가-힣A-Za-z0-9])(?:" + "|".join(kr) + ")")
        if en:
            ps.append(r"(?<![A-Za-z0-9])(?:" + "|".join(en) + r")(?![A-Za-z0-9])")
        return "|".join(ps)
    always = list(full) + [p for p in parts if p.lower() not in NAME_PART_STOP]
    titled = [p for p in parts if p.lower() in NAME_PART_STOP]
    a = alt(always)
    t = alt(titled)
    rx_a = re.compile(a, re.I) if a else None
    rx_t = re.compile(r"(?:@(?:" + t + r"))|(?:" + t + r")(?=\s?" + TITLES + r")", re.I) if t else None
    return rx_a, rx_t


def mask_names(text, names):
    """글 안의 사람 이름 → [사람]. names = 표시 이름들('홍길동 책임/개발팀'·'Kim, Gildong <g@x>') 또는 이름 조각.
    전체 이름과 2자 이상 조각을 호칭이 있든 없든 가린다 — 단 흔한 업무어와 같은 조각(NAME_PART_STOP)은 호칭·@ 가 붙을 때만."""
    if not text or not names:
        return str(text or "")
    full, parts = set(), set()
    for n in names:
        f, p = name_tokens(n)
        if not f and not p:
            s = unicodedata.normalize("NFKC", str(n or "")).strip()
            if len(s) >= 2 and not _ADDR_RX.search(s) and not any(ch.isdigit() for ch in s) \
                    and s.lower() not in _NAME_ORG_STOP and s not in NAME_STOP:
                (parts if s.lower() in NAME_PART_STOP else full).add(s)
            continue
        full.update(f)
        parts.update(p)
    rx_a, rx_t = _name_rx(tuple(sorted(full)), tuple(sorted(parts)))
    t = str(text)
    if rx_a is not None:
        t = rx_a.sub("[사람]", t)
    if rx_t is not None:
        t = rx_t.sub(lambda m: "[사람]" if not m.group(0).startswith("@") else "@[사람]", t)
    return t


NAME_HASHES_REL = os.path.join("data", "cache", "name_hashes.json")
NAME_HASHES_TAG = "name_hashes_{tag}.json"      # report\ — 그 tag 의 분석 결과와 함께 산다(retention 의 result 분류)
_HASH16_RX = re.compile(r"[0-9a-f]{16}")
_DAY_RX = re.compile(r"\d{4}-\d{2}-\d{2}")
_TAG_RX = re.compile(r"\d{8}-\d{8}")
_TAG_FILES = ("run_meta_{t}.json", "signals_{t}.csv", "work_rows_{t}.csv", "work_rows_{t}_refined.csv", "agentic_{t}.json",
              "workflow_{t}.json")


def _today(today=None):
    from datetime import date as _date
    from datetime import datetime as _dt
    if today is None:
        return _date.today()
    if isinstance(today, _dt):
        return today.date()
    if isinstance(today, _date):
        return today
    return _date.fromisoformat(str(today)[:10])


def _hash_cfg(cfg, root):
    """이름 해시 기한에 쓸 설정 — 주면 그것, 없으면 root 의 config\\config.json(실효 설정)."""
    if isinstance(cfg, dict):
        return cfg
    try:
        return afcfg.load_effective(root)[0]
    except (OSError, ValueError, TypeError):
        return {}


def _hash_days(cfg, root, key):
    """이름 해시를 쓰는 일수 — retention.<key>(intermediateDays·resultDays — D13 상한 적용)."""
    try:
        return max(1, int(afcfg.get(_hash_cfg(cfg, root), "retention." + key)))
    except (TypeError, ValueError):
        return afcfg.RETENTION_MAX[key]


def _read_hash_file(p):
    """이름 해시 파일 → ({해시: 'YYYY-MM-DD' 마지막으로 본 날}, 판 2|1|None). v2 = {"v": 2, "hashes": {해시: 날}} ·
    v1(옛 판) = {"hashes": [해시…]} 은 파일 수정 날에 본 것으로 읽는다. 없거나 깨졌으면 ({}, None)."""
    try:
        with open(p, encoding="utf-8-sig") as f:
            d = json.load(f)
        mt = os.path.getmtime(p)
    except (OSError, ValueError):
        return {}, None
    h = d.get("hashes") if isinstance(d, dict) else None
    out = {}
    if isinstance(h, dict):
        for k, v in h.items():
            k, v = str(k), str(v or "")[:10]
            if _HASH16_RX.fullmatch(k) and _DAY_RX.fullmatch(v):
                out[k] = v
        return out, 2
    if isinstance(h, list):
        from datetime import date as _date
        day = _date.fromtimestamp(mt).isoformat()
        for k in h:
            if _HASH16_RX.fullmatch(str(k)):
                out[str(k)] = day
        return out, 1
    return {}, None


def _fresh_hashes(entries, today, days):
    """마지막으로 본 날 + days 가 오늘보다 뒤인 것만(본 날 + 기한이 되는 날 빠진다 — retention 의 파일 기한과 같은 셈법 ·
    앞날은 오늘로) — {해시: 날}."""
    from datetime import timedelta as _td
    cut, top = (today - _td(days=days)).isoformat(), today.isoformat()
    return {h: min(d, top) for h, d in entries.items() if d > cut}


def _write_hash_file(p, entries):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = f"{p}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"product": "AgentFinder32", "v": 2, "hashes": dict(sorted(entries.items()))}, f, ensure_ascii=False)
    os.replace(tmp, p)


def _tag_hash_path(root, tag):
    return os.path.join(str(root or ROOT), "report", NAME_HASHES_TAG.format(tag=tag))


def _tag_hash_files(root):
    import glob
    out = []
    for p in sorted(glob.glob(os.path.join(str(root or ROOT), "report", "name_hashes_*.json"))):
        m = re.fullmatch(r"name_hashes_(\d{8}-\d{8})\.json", os.path.basename(p))
        if m:
            out.append((m.group(1), p))
    return out


def load_name_hashes(root=None, tag=None, *, cfg=None, today=None):
    r"""이름 해시 집합(이름 원문 없음) — data\cache\name_hashes.json 중 retention.intermediateDays 안에 본 것 ∪
    report\name_hashes_<tag>.json 중 retention.resultDays 안에 본 것(tag 를 주면 그 tag 것, 주지 않으면 남아 있는 모든 tag 것 —
    남은 분석 결과의 이름을 G1·G2·G3·공유·사람 이름 관문이 계속 가린다). 기한이 지난 해시는 쓰지 않는다. 없으면 빈 집합."""
    root = str(root or ROOT)
    td = _today(today)
    cfg = _hash_cfg(cfg, root)
    cur, _v = _read_hash_file(os.path.join(root, NAME_HASHES_REL))
    out = set(_fresh_hashes(cur, td, _hash_days(cfg, root, "intermediateDays")))
    tags = ([(tag, _tag_hash_path(root, tag))] if tag and _TAG_RX.fullmatch(str(tag))
            else ([] if tag else _tag_hash_files(root)))
    if tags:
        rdays = _hash_days(cfg, root, "resultDays")
        for _t, p in tags:
            out |= set(_fresh_hashes(_read_hash_file(p)[0], td, rdays))
    return out


def save_name_hashes(root, tokens, salt, *, cfg=None, today=None):
    r"""이름 조각들의 해시를 data\cache\name_hashes.json(v2 — {해시: 마지막으로 본 날 'YYYY-MM-DD'})에 합쳐 쓴다(이름은 쓰지
    않는다). 이번에 본 해시는 오늘로 새로 하고, retention.intermediateDays 보다 오래 보지 못한 해시는 뺀다 → 저장된 해시 수."""
    root = str(root or ROOT)
    td = _today(today)
    p = os.path.join(root, NAME_HASHES_REL)
    cur, ver = _read_hash_file(p)
    keep = _fresh_hashes(cur, td, _hash_days(cfg, root, "intermediateDays"))
    for t in tokens or ():
        if t and _name_key(t) not in NAME_PART_STOP:
            keep[name_hash(t, salt)] = td.isoformat()
    if keep == cur and ver == 2:
        return len(keep)
    _write_hash_file(p, keep)
    return len(keep)


def snapshot_name_hashes(root, tag, *, cfg=None, today=None):
    r"""report\name_hashes_<tag>.json = 지금 쓰는 이름 해시(data\cache — intermediateDays 안) ∪ 그 파일에 있던 것(resultDays 안).
    분석(extract.load_signals)이 tag 마다 부른다 — 결과(agentic_·workflow_<tag>)는 resultDays 까지 남으므로 공유 가림·사람 이름
    관문이 그동안 이 해시를 쓴다. 그 tag 의 결과와 함께 지워진다(prune_name_hashes·retention). → 저장한 해시 수."""
    root = str(root or ROOT)
    if not tag or not _TAG_RX.fullmatch(str(tag)):
        return 0
    td = _today(today)
    cfg = _hash_cfg(cfg, root)
    g, _v = _read_hash_file(os.path.join(root, NAME_HASHES_REL))
    g = _fresh_hashes(g, td, _hash_days(cfg, root, "intermediateDays"))
    p = _tag_hash_path(root, tag)
    old, ver = _read_hash_file(p)
    keep = _fresh_hashes(old, td, _hash_days(cfg, root, "resultDays"))
    for h, d in g.items():
        keep[h] = max(d, keep.get(h, ""))
    if keep == old and ver == 2:
        return len(keep)
    if not keep:
        if os.path.exists(p):
            os.remove(p)
        return 0
    _write_hash_file(p, keep)
    return len(keep)


def prune_name_hashes(root=None, cfg=None, *, today=None):
    r"""보관기한 정리(retention.purge 가 부른다 — 파일 수정 시각이 아니라 해시마다 본 날로 나이를 잰다):
    data\cache\name_hashes.json 에서 retention.intermediateDays 보다 오래 보지 못한 해시를 빼고(옛 판 목록은 v2 로 바꿔 쓴다 ·
    다 빠지면 파일을 지운다), report\name_hashes_<tag>.json 에서 resultDays 보다 오래된 해시를 뺀다. 그 tag 의 분석 자료
    (run_meta·signals·work_rows·agentic·workflow)가 하나도 남지 않았거나 해시가 비면 그 파일을 지운다.
    → {"removed": 뺀 해시 수, "kept": 남은 해시 수(전체 파일 합), "deleted": [지운 파일의 설치 폴더 기준 상대 경로],
       "errors": [상대 경로]}. 예외를 던지지 않는다."""
    root = os.path.abspath(str(root or ROOT))
    out = {"removed": 0, "kept": 0, "deleted": [], "errors": []}
    try:
        td = _today(today)
    except ValueError:
        td = _today()
    cfg = _hash_cfg(cfg, root)
    jobs = [(os.path.join(root, NAME_HASHES_REL), _hash_days(cfg, root, "intermediateDays"), None)]
    rdays = _hash_days(cfg, root, "resultDays")
    jobs += [(p, rdays, t) for t, p in _tag_hash_files(root)]
    for p, days, tag in jobs:
        rel = os.path.relpath(p, root)
        try:
            cur, ver = _read_hash_file(p)
            if ver is None:
                continue
            keep = _fresh_hashes(cur, td, days)
            orphan = tag is not None and not any(
                os.path.exists(os.path.join(root, "report", f.format(t=tag))) for f in _TAG_FILES)
            out["removed"] += len(cur) - (0 if orphan else len(keep))
            if orphan or not keep:
                os.remove(p)
                out["deleted"].append(rel)
                continue
            out["kept"] += len(keep)
            if keep != cur or ver != 2:
                _write_hash_file(p, keep)
        except OSError:
            out["errors"].append(rel)
    return out


def _hash_mask(text, hashes, salt):
    """해시 집합에 든 이름 조각 → [사람]. 한글 덩어리는 첫머리 2~4자와 덩어리 전체, 영문은 낱말 하나씩 본다."""
    if not text or not hashes:
        return text

    def han(m):
        run = m.group(0)
        for n in (len(run), 4, 3, 2):
            if 2 <= n <= len(run) and name_hash(run[:n], salt) in hashes:
                return "[사람]" + run[n:]
        return run

    def eng(m):
        w = m.group(0)
        return "[사람]" if name_hash(w, salt) in hashes else w
    t = re.sub(r"(?<![가-힣\[])[가-힣]{2,}", han, str(text))
    return re.sub(r"(?<![A-Za-z\[])[A-Za-z][A-Za-z'\-]+(?![A-Za-z])", eng, t)


def mask_known_names(text, hashes, salt):
    """이름 해시(name_gate·load_name_hashes)에 든 이름 조각 → [사람] — G2(신호 글·회의 안건)·G3(Copilot 행)가 쓴다."""
    s = "" if text is None else str(text)
    return _hash_mask(s, hashes, salt) if (s and hashes and salt) else s


# 이름 바로 뒤에 붙는 것 — 조사·호칭(2자 이름 조각이 '현수막'·'민수용' 같은 낱말의 첫머리가 아니라 이름일 때)
_NAME_TAIL_RX = re.compile(r"(?:" + TITLES[3:-1] + r"|님|씨|께|에게|한테|이랑|랑|하고|이|가|은|는|을|를|의|와|과|도|만|에|로|으로)")


def known_name_in(text, hashes, salt):
    """이름 해시에 든 사람 이름이 글에 남아 있는가(G3 최종 프롬프트 검사용 — 엄격하게): 한글 덩어리 전체·첫머리 3~4자(성 + 이름),
    2자 첫머리는 바로 뒤가 조사·호칭이거나 덩어리가 그 2자일 때만('현수막'·'민수용' 은 아니다) · 영문 낱말 하나씩."""
    if not text or not hashes or not salt:
        return False
    for m in re.finditer(r"(?<![가-힣\[])[가-힣]{2,}", str(text)):
        run = m.group(0)
        for n in (len(run), 4, 3, 2):
            if not 2 <= n <= len(run) or name_hash(run[:n], salt) not in hashes:
                continue
            if n == 2 and len(run) > 2 and not _NAME_TAIL_RX.fullmatch(run[2:]):
                continue
            return True
    for m in re.finditer(r"(?<![A-Za-z\[])[A-Za-z][A-Za-z'\-]+(?![A-Za-z])", str(text)):
        if name_hash(m.group(0), salt) in hashes:
            return True
    return False


_GATE_CACHE = {}


def name_gate(root=None, *, cfg=None):
    r"""(이름 해시 집합, 설치 소금) — load_name_hashes(root)(남은 모든 tag 포함)와 data\install.json 의 소금을 읽기만 한다(만들지
    않는다). 둘 중 하나라도 없거나 깨졌으면 (빈 집합, ""). 파일이 바뀌지 않으면 다시 읽지 않는다(G2·G3 가 묶음마다 부른다)."""
    root = os.path.abspath(str(root or ROOT))
    paths = [os.path.join(root, NAME_HASHES_REL), os.path.join(root, "data", "install.json"),
             os.path.join(root, "config", "config.json")]
    paths += [p for _t, p in _tag_hash_files(root)]
    key = [root, str(_today()),
           json.dumps(afcfg.get(cfg, "retention"), sort_keys=True, default=str) if isinstance(cfg, dict) else ""]
    for p in paths:
        try:
            st = os.stat(p)
            key.append((p, st.st_mtime_ns, st.st_size))
        except OSError:
            key.append((p, None))
    key = tuple(key)
    hit = _GATE_CACHE.get(root)
    if hit and hit[0] == key:
        return hit[1]
    try:
        with open(paths[1], encoding="utf-8-sig") as f:
            salt = str((json.load(f) or {}).get("salt") or "")
    except (OSError, ValueError, AttributeError):
        salt = ""
    res = (frozenset(), "")
    if re.fullmatch(r"[0-9a-f]{64}", salt):
        hs = load_name_hashes(root, cfg=cfg)
        res = (frozenset(hs), salt) if hs else (frozenset(), "")
    if len(_GATE_CACHE) > 16:
        _GATE_CACHE.clear()
    _GATE_CACHE[root] = (key, res)
    return res


# ── 원자료 값 읽기 ─────────────────────────────────────────────────────────────────────────
_SENS_WORDS = {"personal": 1, "개인": 1, "private": 2, "비공개": 2, "confidential": 3, "기밀": 3, "normal": 0, "보통": 0}
_BUSY_WORDS = {"free": 0, "한가함": 0, "tentative": 1, "미정": 1, "busy": 2, "바쁨": 2, "oof": 3, "outofoffice": 3,
               "부재중": 3, "workingelsewhere": 4, "다른곳에서작업": 4}


def _int_or(v, words, dflt=None):
    s = str(v if v is not None else "").strip()
    if not s:
        return dflt
    try:
        return int(float(s))
    except ValueError:
        return words.get(re.sub(r"[\s_\-]+", "", s.lower()), dflt)


def _truthy(v):
    return v is True or str(v).strip().lower() in ("true", "1", "-1", "yes", "y", "on", "예")


def _cats(v):
    return [c.strip() for c in re.split(r"[;,]", str(v or "")) if c.strip()]


def _row_people(row, kind):
    """원자료 행 → [(이름, 주소, 도메인)] (보낸이·받는이·참조 또는 주최자·참석자)."""
    if kind == "mail":
        ppl = []
        sn, sa = str(row.get("sender_name") or "").strip(), str(row.get("sender_addr") or "").strip()
        if sn or sa:
            p = parse_people(f"{sn.replace(';', ' ')} <{sa}>" if sa else sn.replace(";", " "))
            ppl.append(p[0] if p else (sn, "", ""))   # 보낸이는 늘 한 사람(첫 칸)
        for col in ("to", "cc"):
            ppl += parse_people(row.get(col))
        return ppl
    return parse_people(row.get("organizer")) + parse_people(row.get("attendees"))


def _row_text(row, kind, *, body=True):
    keys = ("subject", "conversation") if kind == "mail" else ("subject", "location")
    vals = [str(row.get(k) or "") for k in keys]
    if body and kind != "mail":
        vals.append(str(row.get("body") or ""))
    return "\n".join(v for v in vals if v)


def _external_for(row, kind, people, internal):
    """메일·회의의 사내/사외. 받은 메일은 보낸이가 있어야, 보낸 메일은 받는이·참조가 있어야 증명할 수 있다.
    참여자가 없는 일정(내 일정 — 주최자·참석자 모두 비어 있음)은 사외 사람이 없으므로 internal."""
    if kind == "mail":
        has_sender = bool(str(row.get("sender_addr") or "").strip() or str(row.get("sender_name") or "").strip())
        others = people[1:] if has_sender else people
        if str(row.get("box") or "").strip().lower() == "sent":
            check = others                    # 보낸 메일의 보낸이는 나 — 받는이·참조만 본다
        else:
            if not has_sender:
                return "unknown"
            check = people
        return external_status(check, internal) if check else "unknown"
    if not people:
        return "internal" if internal else "unknown"
    return external_status(people, internal)


def drop_reason(row, kind, *, cfg=None, restricted=None, internal=(), masked=None, allow_patterns=None):
    """원자료 행(§5.0 열 이름의 dict) 하나 → 빼는 사유(DROP_ORDER 의 첫 것) 또는 None.
    restricted 가 None 이면 'restricted'(제한 고객 목록 없이 판정하지 않는다 — 닫는다). internal = 사내 도메인 집합.
    masked = 이미 가린 글(없으면 여기서 sanitize 로 가려 식별번호를 본다). kind = "mail" | "cal"."""
    kind = "mail" if kind == "mail" else "cal"
    text = _row_text(row, kind)
    people = _row_people(row, kind)
    # ① 제한 고객 — 글·범주·참여자 표시 이름('Hanbit 대응TF <…>')·참여자 도메인, 그리고 주소 앞부분('<hanbit-tf@corp…>' — 영문
    #    4자 이상 이름만: hit_local). 이름·주소는 메모리에서만 본다
    who = "\n".join(p[0] for p in people if p[0])
    if restricted is None or restricted.hit(text + "\n" + str(row.get("categories") or "") + "\n" + who,
                                            [p[2] for p in people if p[2]]):
        return "restricted"
    if restricted.hit_local(p[1].split("@", 1)[0] for p in people if p[1]):
        return "restricted"
    # ② 사적 — 민감도·범주·폴더·개인 키워드
    if _int_or(row.get("sensitivity"), _SENS_WORDS, 0) in (1, 2, 3):
        return "private"
    ex_cats = {c.lower() for c in _as_list(afcfg.get(cfg, "privacy.excludeCategories"))}
    if any(c.lower() in ex_cats for c in _cats(row.get("categories"))):
        return "private"
    folder = str(row.get("folder") or "").strip().lower()
    if folder:
        segs = [s for s in re.split(r"[\\/]+", folder) if s]
        for f in (str(x).strip().lower() for x in _as_list(afcfg.get(cfg, "privacy.excludeMailFolders"))):
            if f and any(f in s for s in segs):
                return "private"
    if keyword_hit(text + "\n" + str(row.get("categories") or ""), cfg):
        return "private"
    # ③ 근태·행방 — 낱말(제목·장소·범주 · 일정 본문이 있으면 본문도) · 일정 구조(종일·한가함·부재중·다른 곳·취소·거절)
    if admin_hit("\n".join(str(row.get(k) or "") for k in ("subject", "location", "categories")
                           + (("body",) if kind == "cal" else ()))):
        return "admin"
    if kind == "cal":
        if _truthy(row.get("all_day")):
            return "admin"
        if _int_or(row.get("busy_status"), _BUSY_WORDS, 2) in (0, 3, 4):
            return "admin"
        ms = str(row.get("meeting_status") or "").strip().lower()
        if ms in ("5", "7") or "cancel" in ms or "취소" in ms:
            return "admin"
        rs = str(row.get("response") or "").strip().lower()
        if rs == "4" or "declin" in rs or "거절" in rs:
            return "admin"
        if re.match(r"^\s*(?:취소됨|취소|canceled|cancelled)\s*[:：]", str(row.get("subject") or ""), re.I):
            return "admin"
    # ④ 사외 · 증명 불가
    st = _external_for(row, kind, people, internal)
    if st == "external":
        return "external"
    if st != "internal":
        return "external_unknown"
    # ⑤ 민감정보
    if sensitive_hit(text, cfg):
        return "sensitive"
    # ⑥ 식별번호(가린 뒤에도 남은 것)·자격증명
    if masked is None:
        ctx = Ctx(allow_patterns=afcfg.get(cfg, "privacy.allowPatterns"))
        parts = []
        for v in text.split("\n"):
            c, _h, dr = sanitize(v, "g1", ctx)
            if dr:
                return "identifier"
            parts.append(c)
        masked = "\n".join(parts)
    if has_identifier(masked, allow_patterns=allow_patterns if allow_patterns is not None
                      else afcfg.get(cfg, "privacy.allowPatterns")):
        return "identifier"
    return None


# ── G1 ────────────────────────────────────────────────────────────────────────────────────
MAIL_RAW_COLS = ["box", "time", "sender_name", "sender_addr", "to", "cc", "rcv", "time_precision", "subject",
                 "conversation", "sensitivity", "categories", "folder"]
CAL_RAW_COLS = ["start", "end", "all_day", "busy_status", "subject", "categories", "location", "response",
                "meeting_status", "sensitivity", "organizer", "attendees"]
MAIL_COLS = ["box", "time", "sender", "subject", "conversation", "rcv", "time_precision", "src", "notice"]
CAL_COLS = ["start", "end", "all_day", "busy_status", "subject", "categories", "location", "response", "meeting_status",
            "src"]
BODY_MAX = 600


class G1Context:
    """G1 한 번(한 채널·한 실행)의 문맥 — 설정·제한 고객·사내 도메인·소금·기간·이름 집합·건수.
    만들 때 제한 고객 목록이 없으면 RestrictedListError, 사내 도메인이 비면 InternalDomainsError(둘 다 종료 코드 4).
      src            출처 표식(com·owa·copilot) — 정제 행의 src 열
      my_addresses   이 채널이 본 내 주소(사내 도메인의 근거) — data\\outlook\\mail_source*.json 의 me[] 도 더한다
      period         (d0, d1) date — 주면 그 밖의 행은 버리고 out_of_period 로만 센다
    건수: kept {"mail_in","mail_out","meetings"} · excluded {EXCLUDE_KEYS} · out_of_period.
    이름: 본 모든 참여자 이름(기간 밖·버릴 행 포함)은 메모리에서 가리기에 쓰고, finish() 는 기간 안 행의 이름 조각 해시만
    data\\cache\\name_hashes.json 에 본 날과 함께 합쳐 쓴다(save_name_hashes — intermediateDays 가 지나면 빠진다)."""

    def __init__(self, cfg, root=None, *, src="", my_addresses=(), period=None, restricted=None, internal=None,
                 salt=None):
        self.root = os.path.abspath(str(root or ROOT))
        self.cfg, _w = afcfg.effective(cfg if isinstance(cfg, dict) else {})
        self.src = str(src or "")
        self.restricted = restricted if restricted is not None else load_restricted(self.cfg, self.root)
        data_dir = os.path.join(self.root, "data")
        me = [str(x) for x in my_addresses or () if str(x).strip()] + me_list(data_dir)
        self.my_addresses = [x for x in me if "@" in x]
        self.internal = ({d for d in (_dom_norm(x) for x in internal) if d} if internal is not None
                         else internal_domains(self.cfg, self.my_addresses))
        if not self.internal:
            raise InternalDomainsError(INTERNAL_MSG)
        if salt is None:
            import install
            salt = install.salt(self.root)
        self.salt = salt
        self.period = period
        self.pctx = make_ctx(self.cfg, data_dir)
        self.pctx.internal_domains = tuple(sorted(set(self.pctx.internal_domains) | self.internal))
        self.allow = afcfg.get(self.cfg, "privacy.allowPatterns")
        self.notice = notice_words(self.cfg)
        self.store_subject = bool(afcfg.get(self.cfg, "storeMailSubject"))
        self.collect_body = bool(afcfg.get(self.cfg, "calendar.collectBody"))
        self.hashes = load_name_hashes(self.root, cfg=self.cfg)      # 남은 모든 분석(tag)의 이름 해시 포함
        self.names = set()          # 본 표시 이름(메모리에서만 — 가리기용)
        self.tokens = set()         # 본 이름 조각(메모리에서만)
        self.keep_tokens = set()    # 기간 안 행의 이름 조각(해시로만 저장 — finish)
        self.sent_conv, self.replied = set(), set()
        self.kept = {"mail_in": 0, "mail_out": 0, "meetings": 0}
        self.excluded = dict.fromkeys(EXCLUDE_KEYS, 0)
        self.out_of_period = 0

    def _person_display(self, n):
        """표시 이름에서 공지·시스템 조각('마케팅'·'시스템'·'no-reply')을 뺀 나머지 — '김민수/마케팅' → '김민수'.
        조각 하나가 공지 낱말이라고 이름 전체를 버리지 않는다(L3-05)."""
        segs = [x.strip() for x in _NAME_SEG_RX.split(str(n or "")) if x.strip()]
        return " / ".join(x for x in segs if not is_notice_sender(x, words=self.notice))

    def _people_tokens(self, row, kind):
        out = []
        for n, _a, _d in _row_people(row, kind):
            disp = self._person_display(n) if n else ""
            if disp:
                f, p = name_tokens(disp)
                if f or p:
                    out.append((disp, f, p))
        return out

    def see(self, row, kind):
        """행의 참여자 이름을 메모리의 이름 집합에 더한다(가리기용) — 버릴 행·기간 밖 행의 사람(사외 포함)도 더한다.
        시스템·공지 표시 이름은 사람 이름 조각이 하나도 없을 때만 뺀다."""
        for disp, f, p in self._people_tokens(row, kind):
            self.names.add(disp)
            self.tokens.update(f)
            self.tokens.update(p)

    def keep(self, row, kind):
        """기간 안 행의 참여자 이름 조각 → 해시로 남길 집합(finish 가 쓴다). 기간 밖 행의 사람은 남기지 않는다(L1-08)."""
        for _disp, f, p in self._people_tokens(row, kind):
            self.keep_tokens.update(f)
            self.keep_tokens.update(p)

    def prepare(self, rows, kind):
        """행 목록을 먼저 훑는다 — 이름 집합 · 내가 보낸 대화 · 회신한 상대(공지 판정의 예외)."""
        for r in rows:
            self.see(r, kind)
            if kind == "mail" and str(r.get("box") or "").strip().lower() == "sent":
                c = _conv_key(r.get("conversation") or r.get("subject"))
                if c:
                    self.sent_conv.add(c)
        if kind == "mail":
            for r in rows:
                if str(r.get("box") or "").strip().lower() != "sent":
                    c = _conv_key(r.get("conversation"))
                    if c and c in self.sent_conv:
                        for v in (r.get("sender_addr"), r.get("sender_name")):
                            if str(v or "").strip():
                                self.replied.add(str(v).strip().lower())

    def mask(self, text, max_len=None):
        """제목·장소·본문 한 칸 → (가린 글, 자격증명인가). 이름(본 것 + 해시) → [사람], 그 밖은 sanitize.
        메일 주소는 바깥 조직의 도메인 없이 [이메일](관계 표시만 [이메일@사내] 꼴)로 남는다(fold_mail_domains · R5)."""
        t = mask_names(text, self.names) if self.names else str(text or "")
        t = _hash_mask(t, self.hashes, self.salt)
        clean, _hits, drop = sanitize(t, "g1", self.pctx, max_len=max_len)
        return fold_mail_domains(clean), drop

    def counts(self):
        return {"kept": dict(self.kept), "excluded": dict(self.excluded), "out_of_period": self.out_of_period}

    def finish(self):
        """기간 안 행의 이름 조각 해시를 본 날과 함께 저장하고(기한이 지난 해시는 뺀다) 건수를 돌려준다."""
        try:
            save_name_hashes(self.root, self.keep_tokens, self.salt, cfg=self.cfg)
        except OSError:
            pass
        return self.counts()


g1_context = G1Context


def _conv_key(s):
    return re.sub(r"^\s*(?:(?:re|fw|fwd|회신|전달|답장)\s*[:：]\s*)+", "", str(s or "").strip().lower())[:60]


def _in_period(row, kind, period):
    if not period:
        return True
    from datetime import date as _date
    s = str(row.get("time" if kind == "mail" else "start") or "").strip()[:10]
    try:
        d = _date.fromisoformat(s)
    except ValueError:
        return False
    d0, d1 = period
    d0 = _date.fromisoformat(str(d0)[:10]) if not isinstance(d0, _date) else d0
    d1 = _date.fromisoformat(str(d1)[:10]) if not isinstance(d1, _date) else d1
    return d0 <= d <= d1


def g1_row(row, kind, ctx):
    """원자료 행 하나(§5.0 열 이름의 dict) → (정제 행 dict | None, 사유). 사유: None(남김) · EXCLUDE_KEYS 하나 · 'out_of_period'.
    정제 행은 §5.1(메일 MAIL_COLS) 또는 §5.2(일정 CAL_COLS [+ body]) 열만 가진다 — 이름·주소·범주·민감도·폴더는 없다.
    ctx = G1Context. OWA·Copilot 수집기는 항목마다 이것을 부르고 G1Writer 로 쓴다(원자료 파일을 쓰지 않는다)."""
    kind = "mail" if kind == "mail" else "cal"
    if not isinstance(row, dict):
        return None, "identifier"
    ctx.see(row, kind)
    if not _in_period(row, kind, ctx.period):
        ctx.out_of_period += 1
        return None, "out_of_period"
    ctx.keep(row, kind)
    # 가린 글(식별번호 판정용 — 자격증명이면 그대로 identifier)
    fields = ("subject", "conversation") if kind == "mail" else ("subject", "location")
    masked, cred = {}, False
    for f in fields:
        masked[f], d = ctx.mask(row.get(f))
        cred = cred or d
    body_on = kind == "cal" and ctx.collect_body
    if body_on and row.get("body"):
        one = re.sub(r"\s+", " ", str(row.get("body") or "")).strip()
        masked["body"], d = ctx.mask(one, max_len=BODY_MAX)
        cred = cred or d
    why = drop_reason(row, kind, cfg=ctx.cfg, restricted=ctx.restricted, internal=ctx.internal,
                      masked="\n".join(masked.values()), allow_patterns=ctx.allow)
    if why is None and cred:
        why = "identifier"
    if why:
        ctx.excluded[why] = ctx.excluded.get(why, 0) + 1
        return None, why
    if kind == "mail":
        sent = str(row.get("box") or "").strip().lower() == "sent"
        sender = ""
        if not sent:
            sa = str(row.get("sender_addr") or "").strip()
            sender = pseudonym(sa if _ADDR_RX.search(sa) else str(row.get("sender_name") or ""), ctx.salt)
        notice = 0
        if not sent:
            snd = " ".join(str(row.get(k) or "") for k in ("sender_name", "sender_addr")).strip()
            rep = ctx.replied
            if is_notice_sender(snd, words=ctx.notice) and not ({str(row.get("sender_addr") or "").strip().lower(),
                                                                    str(row.get("sender_name") or "").strip().lower()}
                                                                   & rep):
                notice = 1
            else:
                _s, band = ad_score(row.get("subject"), row.get("sender_addr"), "inbox", row.get("folder"),
                                    internal_domains=tuple(ctx.internal),
                                    i_sent_in_conv=_conv_key(row.get("conversation")) in ctx.sent_conv)
                notice = 1 if band in ("drop", "suspect") else 0
        subj, conv = masked["subject"], masked["conversation"]
        if not ctx.store_subject:
            subj = ""
            conv = ("c:" + _hmac_hex(ctx.salt, "c:" + _conv_key(row.get("conversation")))[:12]
                    if str(row.get("conversation") or "").strip() else "")
        out = {"box": "sent" if sent else (str(row.get("box") or "inbox").strip() or "inbox"),
               "time": str(row.get("time") or "").strip(), "sender": sender, "subject": subj, "conversation": conv,
               "rcv": str(row.get("rcv") or "").strip(), "time_precision": str(row.get("time_precision") or "").strip(),
               "src": ctx.src, "notice": str(notice)}
        ctx.kept["mail_out" if sent else "mail_in"] += 1
        return out, None
    out = {"start": str(row.get("start") or "").strip(), "end": str(row.get("end") or "").strip(), "all_day": "0",
           "busy_status": "", "subject": masked["subject"] if ctx.store_subject else "", "categories": "",
           "location": masked["location"], "response": "", "meeting_status": "", "src": ctx.src}
    if body_on:
        out["body"] = masked.get("body", "") if ctx.store_subject else ""
    ctx.kept["meetings"] += 1
    return out, None


class G1Writer:
    """정제 행 쓰기 — data\\outlook\\src\\mail_<ch>.csv(MAIL_COLS) · cal_<ch>.csv(CAL_COLS [+ body]).
    UTF-8(BOM)·CRLF. close() 때 임시 파일에 쓴 뒤 바꿔 넣는다(중간에 멈추면 옛 파일이 그대로). with 문 안에서 예외가 나면 쓰지 않는다.
      body=True        일정에 body 열을 둔다(calendar.collectBody 가 켜졌을 때)
      merge=callable   merge(옛 행 목록, 새 행 목록) → 쓸 행 목록 — 옛 파일과 합칠 때(없으면 새 행으로 덮어쓴다)
    write(정제 행) · add(원자료 행, ctx) → 사유|None (g1_row 후 남는 행만 쓴다) · close() → {"path", "rows"} · discard()."""

    def __init__(self, path, kind, *, body=False, merge=None):
        self.path = path
        self.kind = "mail" if kind == "mail" else "cal"
        self.cols = list(MAIL_COLS) if self.kind == "mail" else list(CAL_COLS) + (["body"] if body else [])
        self.merge = merge
        self.rows = []
        self.closed = False
        self.written = 0             # close() 가 파일에 쓴 행 수(병합 뒤) — 다시 불러도 같은 값을 돌려준다

    def write(self, clean_row):
        if clean_row:
            self.rows.append({c: str(clean_row.get(c, "") if clean_row.get(c) is not None else "") for c in self.cols})

    def add(self, row, ctx):
        clean, why = g1_row(row, self.kind, ctx)
        if clean is not None:
            self.write(clean)
        return why

    def _old(self):
        try:
            with open(self.path, encoding="utf-8-sig", errors="replace", newline="") as f:
                return [{c: (r.get(c) or "") for c in self.cols} for r in csv.DictReader(f)]
        except (OSError, csv.Error):
            return []

    def close(self):
        if self.closed:
            return {"path": self.path, "rows": self.written}
        rows = self.rows
        if callable(self.merge):
            rows = [{c: str(r.get(c, "") or "") for c in self.cols} for r in self.merge(self._old(), list(self.rows))]
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        tmp = f"{self.path}.{os.getpid()}.g1tmp"
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=self.cols, extrasaction="ignore", lineterminator="\r\n")
        w.writeheader()
        w.writerows(rows)
        try:
            with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
                f.write(buf.getvalue())
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
        self.closed = True
        self.written = len(rows)
        return {"path": self.path, "rows": self.written}

    def discard(self):
        self.rows = []
        self.closed = True
        self.written = 0

    def __enter__(self):
        return self

    def __exit__(self, et, ev, tb):
        if et is None:
            self.close()
        else:
            self.discard()
        return False


def _read_raw(path):
    with open(path, "rb") as f:
        raw = f.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp949", "replace")
    return [r for r in csv.DictReader(io.StringIO(text, newline="")) if isinstance(r, dict)]


def g1_file(raw_path, out_path, kind, *, cfg, root=None, period=None, src=None, my_addresses=(), merge=None, ctx=None):
    r"""COM 수집기의 원자료(§5.0 data\outlook\raw\mail_com.csv·cal_com.csv) → 정제 파일(§5.1/5.2). 원자료 파일은
    결과와 상관없이(오류·설정 거부여도) 지운다 — 원자료는 남기지 않는다.
    → {"kept": {"mail_in","mail_out","meetings"}, "excluded": {EXCLUDE_KEYS: n}, "out_of_period": n, "rows_in": n,
       "path": out_path}. 제한 고객 목록 없음·사내 도메인 없음은 SetupRefused(원자료는 지운 뒤 다시 던진다).
    src 를 주지 않으면 파일 이름 mail_<ch>.csv·cal_<ch>.csv 의 <ch>. merge 는 G1Writer 와 같다."""
    kind = "mail" if kind == "mail" else "cal"
    if src is None:
        m = re.match(r"^(?:mail|cal)_([A-Za-z0-9_-]{1,24})\.csv$", os.path.basename(str(out_path or raw_path)))
        src = m.group(1) if m else ""
    try:
        try:
            rows = _read_raw(raw_path)
        except (OSError, csv.Error):
            rows = []
        ctx = ctx or G1Context(cfg, root, src=src, my_addresses=my_addresses, period=period)
        ctx.prepare(rows, kind)
        cal_body = kind == "cal" and ctx.collect_body
        with G1Writer(out_path, kind, body=cal_body, merge=merge) as w:
            for r in rows:
                w.add(r, ctx)
        res = ctx.finish()
        res.update(rows_in=len(rows), path=out_path)
        return res
    finally:
        for _ in range(3):
            try:
                os.remove(raw_path)
                break
            except FileNotFoundError:
                break
            except OSError:
                time.sleep(0.3)


# ── 공유 가림(ShareScrubber) ─────────────────────────────────────────────────────────────────
# 흔한 업무어 두 겹:
#   GENERIC_BASE  업무 행위를 말하는 흔한 낱말 — 내 업무 분류(work_rows 의 Level 1/2/3·활동·상세설명)에 나와도 가리지 않는다(가리면
#                 공유 리포트가 '[과제] [과제]' 만 남는다). 이 목록 밖의 업무 분류 낱말은 모두 [과제] 로 가린다(§6.1 — 줄이지 않는다).
#   GENERIC_WORK  GENERIC_BASE + 더 넓은 일반 업무어·공학 일반어·자주 쓰는 동사 꼴 — 이름이 아닌 낱말. 내 신호 글·근거에서 낱말
#                 사전에 넣지 않을 낱말과, ShareScrubber.leftover 가 '남은 이름일 수 있는 낱말'로 보지 않을 낱말을 정한다.
GENERIC_BASE = frozenset("""
개발 양산 공통 AX 설계 검토 시험 해석 분석 평가 검증 회의 보고 보고서 자료 작성 정리 관리 운영 지원 요청 대응 협의 조율 준비
일정 계획 수립 결과 회신 공유 확인 승인 결재 기안 발주 구매 견적 계약 납품 출하 입고 재고 품질 불량 대책 개선 이슈 문제 원인
교육 세미나 출장 문서 양식 표준 규격 사양 도면 모델 모델링 시뮬레이션 데이터 수집 처리 집계 통계 리포트 대시보드 메일 일정 주간
월간 정기 업무 과제 프로젝트 담당 세부 업무유형 유형 기술 연구 실험 측정 테스트 샘플 시제품 부품 조립 생산 공정 장비 설비 유지
보수 점검 진단 모니터링 자동화 프로그램 코드 소프트웨어 하드웨어 시스템 도구 툴 템플릿 체크리스트 매뉴얼 가이드 절차 프로세스
워크플로우 단계 입력 출력 결과물 산출물 요약 정의 분류 선정 비교 조사 기획 제안 발표 협업 소통 커뮤니케이션 고객 대응 요구사항
변경 이력 버전 릴리스 배포 설치 구성 설정 통합 연동 인터페이스 테스트케이스 결함 수정 리뷰 피드백 문의 답변 안내 공지 신청 등록
작업 실행 검사 판정 기준 목표 지표 예산 비용 정산 인보이스 회계 재무 인사 총무 특허 인증 규제 안전 환경 보안 위험 리스크
일반 기타 전반 신규 기존 내부 외부 사내 주요 핵심 반복 수동 정형 비정형 대량 소량 일일 매일 매주 매월 분기 연간 후보 Agentic AI 에이전트
의견 항목 취합 자동 현황 초안 사항 지적 조치 내용 목록 정보 상태 진행 완료 대상 방법 방안 결정 기록 서식
design review test analysis report meeting data model simulation document plan schedule quality issue support
""".split())
GENERIC_WORK = GENERIC_BASE | frozenset("""
메일함 수신 발신 발송 전달 첨부 첨부파일 파일 폴더 게시판 공지사항 알림 안내문 요청서 신청서 견적서 회의록 일정표 계획서
결과서 성적서 시험성적서 사양서 명세서 설계서 점검표 대장 리스트 엑셀 시트 그래프 차트 엑셀표 보고 자료 회의자료 발표자료
제출 접수 갱신 업데이트 반영 전송 회람 보관 저장 백업 정정 보완 추출 대조 매칭 검색 조회 변환 생성 편집 병합 정렬 필터 표시
통보 응답 합의 판단 예측 추정 산출 계산 산정 주문 출고 납기 배송 청구 지급 기한 마감 주기 빈도 증상 발생 발생일 오류 에러
경고 알람 회로 보드 커넥터 케이블 센서 모듈 펌웨어 설계안 시험항목 계측 신뢰성 내구성 안정성 성능 스크립트 데이터베이스 서버
네트워크 로그 변경점 변경사항 파라미터 조건 팀원 팀장 담당자 관계자 요청자 작성자 검토자 승인자 협력사 공급사 부서 파트 수시
당일 전일 익일 주기적 정기적 챗봇 흐름 업무흐름 표 양식화 문서화 표준화 일원화 체계 체계화 구조 구조화 사람 담당별 항목별
날짜별 주차별 월별 시간순 순서 우선순위 누락 중복 확인용 참고 참조 근거 출처 원본 사본 최신 최종 이전 다음 기존안 수정안 변경안
요청 메일 회신 메일 보고 메일 메일로 받은 보낸 모아 모은 모아서 받아 보내 읽어 읽고 뽑아 뽑는 넣어 넣는 만들어 만든 합쳐 합친
맞춰 맞춘 찾아 찾는 묶어 묶는 나눠 나눈 바꿔 바꾼 채워 채운 옮겨 옮긴 붙여 붙인 골라 고른 걸러 거른 따라 따른 통해 대해
위해 위한 관련 관한 같은 여러 모든 매번 반복적 반복되는 자동으로 수작업 손으로 직접 한꺼번에 일괄 미리 먼저 다시 함께 각각
표로 표를 표에 표의 표가 형식 오가며 차례 시점 기간 구간 범위 요일 정해진 지난 하나 둘 넘게 남짓 이상 이하 정도 가량
송부 추가 취합본 라인 회신본 보고본 완료본 수정본 최종본 초안본 사본 파일명 제목 본문 첨부물 요청건 회의건
가지 연락 방문 통화 사례 경우 때마다 번에
re fw fwd
design review test analysis report meeting data model simulation document plan schedule quality issue support
weekly monthly daily summary list mail email draft template sheet table chart dashboard check status update request reply
the this that these those for from with without and or not all each every any when then after before into per via
to of in on at by as is are be it its a an send read write create make collect gather summarize compile prepare
organize sort filter merge extract convert generate use using based new same other next last first auto automatic
manual file files folder form format item items step steps task tasks work team member members user users week month
day year time date name title subject body text note notes result results input output process flow tool tools rule
rules type part parts count number total visit prep
""".split())
# 공학 일반 명사 — 이름이 아니므로 leftover 는 표시하지 않는다(GENERIC_WORK 에도 있다). 다만 내 업무 분류·메일 낱말에 있으면
# 다른 업무 분류 낱말처럼 [과제] 로 가린다(무슨 일을 하는지 드러내는 낱말 — §6.1 의 'Level 낱말').
DOMAIN_WORDS = frozenset("회로 보드 커넥터 케이블 센서 모듈 펌웨어 설계안 시험항목 계측 신뢰성 내구성 안정성 성능 스크립트 "
                         "데이터베이스 서버 네트워크 로그 파라미터 라인 구조".split())
# 호칭 앞 낱말 목록(TITLED_STOP)의 보통 명사(두께·전압·공장 …)도 같다 — 표시하지 않고, 내 낱말이면 가린다. 나라·도시·회사·제품
# 이름은 뺀다(공유본에 남으면 표시한다 — 일한 곳·상대를 드러낼 수 있다)
_NOT_COMMON = frozenset("한국 유럽 인도 서울 인천 천안 창원 구미 이천 용인 여수 전주 원주 제주 경기 강원 경북 경남 전북 전남 부산 "
                        "한전 소나타 서피스".split())
COMMON_NOUNS = DOMAIN_WORDS | (TITLED_STOP - _NOT_COMMON - GENERIC_WORK)      # 흔한 업무어(GENERIC_WORK)는 가리지도 않는다
COMMON_CODES = frozenset({
    "AI", "AX", "IT", "PC", "PDF", "API", "ERP", "MES", "PLM", "CAD", "CAE", "CAM", "BOM", "ECO", "ECN", "KPI", "RPA",
    "LLM", "GPT", "HTML", "CSV", "JSON", "XML", "OCR", "QA", "QC", "HR", "SW", "HW", "UI", "UX", "DB", "SQL", "VBA",
    "FAQ", "PPT", "SOP", "VOC", "RFQ", "RFP", "PO", "PR", "OK", "NG", "TBD", "ETC", "R&D", "M365", "AF32", "2D", "3D",
    "MS", "OS", "IoT", "SAP", "CRM", "SCM", "DR", "PM", "PL", "EE", "ME", "SE", "ECU", "PCB", "FMEA", "DOE", "SPC",
    "AgentFinder32", "Copilot", "Excel", "Word", "PowerPoint", "Outlook", "Teams", "SharePoint", "Python",
    "Agentic", "Agent", "Power", "Automate", "Forms", "Planner", "Loop", "OneNote", "OneDrive", "Windows", "Office",
    "Microsoft", "Edge", "Chat",
})
_SHARE_TOKEN_RX = re.compile(r"\[(?:과제|고객사|사람|코드|나|협력사|회사|전화|주민번호|외국인등록번호|생년월일|카드"
                             r"|사업자번호|법인번호|여권|운전면허|계좌|IP|URL|경로|금액|비율|시각)\]")
_MAIL_TOKEN_RX = re.compile(r"\[이메일(?:@[^\]]{0,64})?\]|\[사람#[0-9a-f]{6}\]")   # 메일 주소 토큰(도메인이 든 옛 토큰 포함)은 [사람] 으로
_YM_RX = re.compile(r"(?<!\d)(?:19|20)\d{2}-(?:0[1-9]|1[0-2])(?:\s?~\s?(?:19|20)\d{2}-(?:0[1-9]|1[0-2]))?(?!\d|-\d)")
_FULL_DATE_RX = re.compile(r"(?<!\d)((?:19|20)\d{2})\s?[-./년]\s?(0?[1-9]|1[0-2])\s?[-./월]\s?(?:0?[1-9]|[12]\d|3[01])(?:\s?일)?(?!\d)")
_DATE8_RX = re.compile(r"(?<!\d)((?:19|20)\d{2})(0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])(?!\d)")
_ORDINAL_RX = re.compile(r"(?<![\w])\d{1,2}(?:차|단계|번째|회차)(?![\w])")
_CODE_UP_RX = re.compile(r"(?<![A-Za-z0-9_\[])[A-Z]{2,}[-\d]*(?![A-Za-z0-9_\]])")   # 뒤에 한글 조사가 붙어도 코드
_CODE_DIGIT_RX = re.compile(r"(?<![\w\[])\w*\d\w*(?![\w\]])")
# 영문 고유 이름 꼴 — 대문자로 시작하고 소문자가 이어지는 3자 이상 낱말('Samsung'·'Hyundai'·'Younghee'·'Alpha')
_CAP_WORD_RX = re.compile(r"(?<![A-Za-z0-9_\[])[A-Z][a-z][A-Za-z'\-]+(?![A-Za-z0-9])")
_SPLIT_RX = re.compile(r"[\s,·/|()\[\]{}<>:;\"'~+&→\-]+")
_PARTICLE_RX = re.compile(r"(?:으로|에서|에게|까지|부터|보다|처럼|이며|이고|와|과|의|을|를|은|는|이|가|에|로|도|만)$")
_PARTICLE_WORDS = frozenset("으로 에서 에게 까지 부터 보다 처럼 이며 이고 와 과 의 을 를 은 는 이 가 에 로 도 만 씩 및 또는 등".split())
# 업무 행위 낱말의 끝(동사·명사형 어미) — 상세설명의 '정리한다·검토하고' 가 낱말 그대로 [과제] 로 가려지지 않게 줄기만 본다
_VERB_END_RX = re.compile(r"(?:합니다|한다|하고|하여|해서|하며|하는|하기|했다|된다|되는|되고|되어|됨|함|해|한|할|된|될|돼"
                          r"|적인|적으로|적)$")
# 횟수·수량 낱말(메일·일정에서 나온 빈도 — §5.11 공유본에는 숫자를 싣지 않는다). '매주·매월' 같은 주기는 남긴다.
_NUM_NATIVE = (r"(?:(?:열|스물|스무|서른|마흔|쉰|예순|일흔|여든|아흔)(?:한|두|세|네|다섯|여섯|일곱|여덟|아홉)?"
               r"|한두|두세|서너|너덧|대여섯|예닐곱|한|두|세|네|다섯|여섯|일곱|여덟|아홉)")
_NUM_SINO = (r"(?:수십|수백|수천|수만|[일이삼사오육칠팔구]?십[일이삼사오육칠팔구]?|[일이삼사오육칠팔구]?백"
             r"|[일이삼사오육칠팔구]?천)여?")
_NUM_AFTER = (r"(?=$|[^가-힣]|씩|에|이|가|은|는|을|를|도|만|의|으로|로|정도|가량|쯤|남짓|안팎|넘게|이상|이하|마다|까지|부터"
              r"|동안|간)")
# '한 번에'(한꺼번에)·'이 건'(이 일)·'일 건' 은 횟수가 아니다 — 한 자리 한자어 수는 삼~구만 본다
_NUM_WORD_RX = re.compile(
    r"(?<![가-힣A-Za-z0-9])(?!한\s?번에)(?:" + _NUM_NATIVE + r"\s?(?:번|건|회|차례|명|개|시간|주|달|개월|통|배)"
    + r"|" + _NUM_SINO + r"\s?(?:번|건|회|차례|명|개|시간|주|일|개월|통|배)"
    + r"|[삼사오육칠팔구]\s(?:번|건|회|차례|명|개월)"
    + r"|이틀|사흘|나흘|닷새|엿새|이레|여드레|아흐레|열흘|보름)" + _NUM_AFTER
    + r"|(?<![A-Za-z])(?:once|twice|thrice|(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|twenty"
    r"|thirty|dozen)\s+times)(?![A-Za-z])", re.I)
_WORD_RUN_RX = re.compile(r"[가-힣]+|[A-Za-z][A-Za-z'\-]*[A-Za-z]")


def _tokens_of(s, keep=None):
    """글 → 낱말 목록 — 3자 이상 한글 낱말은 서술 어미(…한다·…되는·…적)를 먼저, 그다음 조사를 뗀 줄기. 흔한 업무어 목록(keep —
    기본 GENERIC_WORK)에 그대로 있는 낱말('한꺼번에'·'메일로')은 줄기로 바꾸지 않는다."""
    keep = GENERIC_WORK if keep is None else keep
    out = []
    for w in _SPLIT_RX.split(unicodedata.normalize("NFKC", str(s or ""))):
        w = w.strip(".?!")
        if not w:
            continue
        if re.search(r"[가-힣]", w) and len(w) > 2 and w not in keep:
            w3 = _VERB_END_RX.sub("", w)
            w = w3 if len(w3) >= 2 else w
            w2 = _PARTICLE_RX.sub("", w) if len(w) > 2 else w
            w = w2 if len(w2) >= 2 else w
        out.append(w)
    return out


def _generic(tok):
    t = tok.strip()
    low = t.lower()
    return (t in GENERIC_WORK or low in GENERIC_WORK or t in COMMON_NOUNS or t.upper() in COMMON_CODES or t in COMMON_CODES
            or len(t) < 2 or _PREDICATE_RX.fullmatch(t) is not None or t in _PARTICLE_WORDS or t in TITLE_WORDS
            or (t.endswith("님") and t[:-1] in TITLE_WORDS))


# '쓴다·만든다·합친다·정리했다·같다' 같은 서술어(한글 + '다'·'요' 로 끝남)는 이름이 아니다 — 상세설명 문장에서 나와도 가리지 않는다
_PREDICATE_RX = re.compile(r"[가-힣]+(?:다|요)")


def _generic_base(tok):
    """업무 분류(work_rows) 낱말의 예외 판정 — 좁은 목록(GENERIC_BASE)·COMMON_CODES·1자·서술어·조사만 흔한 낱말이다. 그 밖의
    업무 분류 낱말은 넓은 목록(GENERIC_WORK)에 있어도 가린다(내 업무 분류에 적힌 낱말은 예전처럼 공유본에 싣지 않는다)."""
    t = tok.strip()
    return (t in GENERIC_BASE or t.lower() in GENERIC_BASE or t.upper() in COMMON_CODES or t in COMMON_CODES
            or len(t) < 2 or _PREDICATE_RX.fullmatch(t) is not None or t in _PARTICLE_WORDS)


def _own_word(tok):
    """내 신호 글·근거에서 낱말 사전(→ [과제])에 넣을 낱말인가 — 흔한 업무어가 아니거나, 보통 명사(COMMON_NOUNS)다."""
    return tok in COMMON_NOUNS or not _generic(tok)


def _vocab_tokens(text, own=False):
    """글 → 이름일 수 있는 낱말(가림 토큰·날짜·숫자만인 것·흔한 업무어·보통 명사를 뺀 2자 이상). own=True 면 내 낱말 사전에
    넣을 낱말(_own_word — 보통 명사도 넣는다)."""
    t = _MAIL_TOKEN_RX.sub(" ", TOKEN_RX.sub(" ", _nfkc(text)))
    out = []
    for w in _tokens_of(t):
        if not re.search(r"[가-힣A-Za-z]", w) or re.search(r"\d", w) or not (_own_word(w) if own else not _generic(w)):
            continue
        out.append(w)
    return out


class ShareScrubber:
    """공유(개인 리포트·익명 팀 집계)로 나가는 글을 가린다(§6.1). 만들 때 제한 고객 목록이 없으면 RestrictedListError.
    가리는 것 → 바꾸는 토큰:
      [고객사]  제한 고객 이름·약칭·회사 형태를 뗀 이름·도메인(하위 도메인 포함) · privacy.customers · privacy.partners
      [과제]    privacy.codenames·level1Codenames · config\\projects.json 이름·키워드 · report\\entities_*.json 의 과제 이름·키워드·
                제품 · 내 work_rows(일반본과 정제본 둘 다)의 Level 1/2/3·활동·상세설명 낱말(좁은 목록 GENERIC_BASE 밖의
                것 모두 — '회로 설계 검토' 의 '회로')과 Level 2 이름 · 내 신호 글(signals_<tag>.csv 의 text)·근거
                (evidence_<tag>.md)의 낱말(넓은 목록 GENERIC_WORK 밖의 것과 보통 명사 COMMON_NOUNS) · terms(문자열)
      [사람]    이름 + 호칭(mask_titled_names) · 이름 해시(data\\cache 와 report\\name_hashes_<tag>.json)에 든 이름 · 메일 주소 ·
                전화번호
      [코드]    식별번호 · URL · 영문 대문자 코드([A-Z]{2,}[-\\d]*)·숫자가 든 낱말(\\w*\\d\\w*) · 대문자로 시작하는 영문 고유 이름 ·
                횟수 낱말('세 번'·'스무 건'·'once') — COMMON_CODES·흔한 업무 영어·'YYYY-MM' 날짜·'1차/2단계' 서수는 뺀다.
                privacy.allowPatterns 는 이름·연락처·식별자를 다 가린 뒤에 남은 공학 코드 표기에만 쓴다(가린 부분·사전 낱말·
                식별번호 꼴이 든 곳은 지키지 않는다 — _allow_ok).
      날짜는 'YYYY-MM' 로 줄인다(YYYY-MM-DD·YYYY.MM.DD·YYYYMMDD·YYYY년 M월 D일).
    사전 낱말은 3자 이상이면 띄어쓰기·하이픈 변형('스카이 라인')에도 맞는다. 글은 NFKC·폭 0 문자 제거(_nfkc) 뒤에 본다.
    tag 를 주면 그 tag 의 자료만, 없으면 report\\ 의 모든 tag. terms = 더 가릴 낱말(문자열 → [과제], (낱말, 토큰) 쌍).
    .text(s) → 가린 글 · .leftover(가린 글) → 남은 '이름일 수 있는 낱말' 목록(C4 — 미리보기가 그 항목을 표시한다) ·
    .table() → 지금까지 바꾼 낱말 [{"term","token","kind","hits"}] (미리보기 화면용 — PC 안에서만) ·
    .warnings → 쓰지 않은 설정(사전 낱말에 맞는 privacy.allowPatterns) 한국어 문장 목록."""

    def __init__(self, cfg, *, root=None, terms=(), tag=None):
        self.root = os.path.abspath(str(root or ROOT))
        self.cfg, _w = afcfg.effective(cfg if isinstance(cfg, dict) else {})
        self.tag = str(tag) if tag and _TAG_RX.fullmatch(str(tag)) else None
        self.restricted = load_restricted(self.cfg, self.root)
        self.warnings = []
        dic, keys = {}, {}

        def add(term, token, kind):
            t = _nfkc(term).strip()
            k = flex_key(t)
            if len(k) < 2 or k in keys:
                return
            dic[t] = (token, kind)
            keys[k] = t
        for n in self.restricted.terms():
            add(n, "[고객사]", "제한 고객")
        cust = _entries(afcfg.get(self.cfg, "privacy.customers")) + _entries(afcfg.get(self.cfg, "privacy.partners"))
        for n in _names_of(cust):
            add(n, "[고객사]", "고객사·협력사")
            core = company_core(n)
            if core:
                add(core, "[고객사]", "고객사·협력사")
        l1 = afcfg.get(self.cfg, "level1Codenames")
        cods = list(_as_list(afcfg.get(self.cfg, "privacy.codenames")))
        if isinstance(l1, dict):
            for v in l1.values():
                cods += _as_list(v)
        for n in cods:
            add(n, "[과제]", "과제 코드네임")
        for n in self._projects():
            add(n, "[과제]", "지정 과제")
        for n in self._entities(self.tag):
            add(n, "[과제]", "과제 체계")
        vocab = {}

        def voc(w, kind):
            k = _nfkc(w).strip().lower()
            if len(k) < 2:
                return
            if re.search(r"[가-힣]", k) and re.search(r"[a-z]", k) and not re.search(r"\d", k):
                add(w, "[과제]", kind)      # 한글·영문이 섞인 이름('LG화학')은 낱말 덩어리로 나뉜다 — 사전에 넣어 통째로 맞춘다
            elif k not in vocab:
                vocab[k] = ("[과제]", kind)
        for full, toks in self._work_items(self.tag):
            if full:
                add(full, "[과제]", "업무 분류")
            for w in toks:
                voc(w, "업무 분류")
        for text in self._own_texts(self.tag):
            for w in _vocab_tokens(text, own=True):
                voc(w, "내 메일·일정 낱말")
        for t in terms or ():
            if isinstance(t, (tuple, list)) and len(t) == 2:
                add(t[0], str(t[1]), "추가")
            else:
                add(t, "[과제]", "추가")
        self.dic = dic
        self._keys = keys
        self._rx = _dict_rx(tuple(sorted(dic))) if dic else None
        self.vocab = vocab
        doms = list(self.restricted.domains) + [d for _n, ds in cust for d in ds]
        self._drx = _domain_rx(tuple(dict.fromkeys(doms))) if doms else None
        # 허용 패턴 — 사전 낱말·내 낱말에 맞는 식은 공유 가림에 쓰지 않는다(그 이름을 지키게 되므로 · D22)
        self.allow = []
        probes = list(dic) + [w for w in vocab if _CODE_LIKE_RX.search(w.upper())]
        for p in _compile_allow(afcfg.get(self.cfg, "privacy.allowPatterns")):
            bad = next((w for w in probes if p.search(w) or p.search(w.upper())), None)
            if bad is not None:
                self.warnings.append(f"privacy.allowPatterns 의 '{p.pattern[:60]}' 는 고객사·과제 이름에도 맞아 공유할 때 쓰지 "
                                     "않습니다(공유본에서는 늘 가립니다)")
                continue
            self.allow.append(p)
        try:
            import install
            self.salt = install.salt(self.root)
        except (OSError, ValueError):
            self.salt = ""
        self.hashes = load_name_hashes(self.root, tag=self.tag, cfg=self.cfg) if self.salt else set()
        self.hits = {}

    # 재료 ─────────────────────────────────────────────────────────────────
    def _projects(self):
        try:
            with open(os.path.join(self.root, "config", "projects.json"), encoding="utf-8-sig") as f:
                d = json.load(f)
        except (OSError, ValueError):
            return []
        out = []
        for it in d if isinstance(d, list) else []:
            if isinstance(it, dict):
                out.append(str(it.get("name") or ""))
                out += [str(x) for x in _as_list(it.get("match"))]
            elif isinstance(it, str):
                out.append(it)
        return out

    def _report_files(self, pattern, tag):
        import glob
        rep = os.path.join(self.root, "report")
        return sorted(glob.glob(os.path.join(rep, pattern.format(tag=tag if tag else "*"))))

    def _entities(self, tag):
        out = []
        for p in self._report_files("entities_{tag}.json", tag):
            try:
                with open(p, encoding="utf-8-sig") as f:
                    d = json.load(f)
            except (OSError, ValueError):
                continue
            for m in (d.get("models") or []) if isinstance(d, dict) else []:
                if not isinstance(m, dict):
                    continue
                for k in ("name", "product"):
                    if str(m.get(k) or "").strip() and str(m.get(k)).strip() != "공통":
                        out.append(str(m[k]))
                for k in ("match", "merged"):
                    out += [str(x) for x in _as_list(m.get(k))]
        return out

    def _work_items(self, tag):
        """work_rows 일반본과 정제본(_refined) 둘 다 — [(흔한 업무어만이 아닌 Level 2 이름 | "", [Level 1/2/3·활동·상세설명의
        낱말 중 좁은 목록(GENERIC_BASE) 밖의 것 — _generic_base])]. 정제본이 이름을 바꿔도 일반본의 옛 이름이 사전에 남는다.
        업무 분류 낱말은 넓은 목록(GENERIC_WORK)에 든 낱말이어도 가린다('회로 설계 검토' 의 '회로')."""
        files = sorted(set(self._report_files("work_rows_{tag}.csv", tag)
                           + self._report_files("work_rows_{tag}_refined.csv", tag)))
        out = []
        for p in files:
            try:
                with open(p, encoding="utf-8-sig", errors="replace", newline="") as f:
                    for r in csv.DictReader(f):
                        full, toks = "", []
                        for col in ("Level 1", "Level 2", "Level 3", "활동", "상세설명"):
                            v = str(r.get(col) or "").strip()
                            if not v:
                                continue
                            ts = [w for w in _tokens_of(v, GENERIC_BASE) if not _generic_base(w)]
                            toks += ts
                            if col == "Level 2" and len(v) >= 2 and ts:
                                full = v
                        out.append((full, toks))
            except (OSError, csv.Error):
                continue
        return out

    def _own_texts(self, tag):
        """내 신호 글(signals_<tag>.csv 의 text)과 근거(evidence_<tag>.md 의 '## L2 / L3' 머리와 '- MM-DD 글' 줄) — 이 낱말이
        Copilot 이 쓴 후보·단계 글에 다시 나오면 가린다(메일 제목에만 있던 고객사·제품·사람 이름)."""
        out = []
        for p in self._report_files("signals_{tag}.csv", tag):
            try:
                with open(p, encoding="utf-8-sig", errors="replace", newline="") as f:
                    out += [str(r.get("text") or "") for r in csv.DictReader(f)]
            except (OSError, csv.Error):
                continue
        for p in self._report_files("evidence_{tag}.md", tag):
            try:
                with open(p, encoding="utf-8-sig", errors="replace") as f:
                    for ln in f:
                        ln = ln.strip()
                        if ln.startswith("## "):
                            out.append(re.sub(r"\s—\s근거\s*\d+\s*건\s*$", "", ln[3:]))
                        elif ln.startswith("- "):
                            out.append(re.sub(r"^\d{2}-\d{2}\s", "", ln[2:]))
            except OSError:
                continue
        return out

    # 가리기 ───────────────────────────────────────────────────────────────
    def _hit(self, term, token, kind):
        k = (term, token)
        if k in self.hits:
            self.hits[k][1] += 1
        else:
            self.hits[k] = [kind, 1]
        return token

    def _vocab_sub(self, t, ph):
        """내 업무 낱말(work_rows·신호·근거) → [과제]. 낱말(조사·서술 어미를 뗀 줄기) 그대로이거나, 그 낱말(2자 이상)로 시작하는
        한글 덩어리('스카이라인팀'·'미르테크')면 그 앞부분을 가린다 — 붙은 조사·뒷말은 남긴다. 흔한 업무어(GENERIC_WORK)
        그 자체인 낱말('회의록')은 앞부분이 맞아도 가리지 않는다."""
        if not self.vocab:
            return t

        def rep(m):
            w = m.group(0)
            lw = w.lower()
            n, hitw = 0, None
            if lw in self.vocab:
                n, hitw = len(w), lw
            elif re.match(r"[가-힣]", w):
                st = _tokens_of(w)
                stem = st[0] if st else w
                if stem != w and w.startswith(stem) and stem.lower() in self.vocab:
                    n, hitw = len(stem), stem.lower()
                elif w not in GENERIC_WORK and stem not in GENERIC_WORK:
                    for k in range(len(w) - 1, 1, -1):
                        if w[:k] in self.vocab:
                            n, hitw = k, w[:k]
                            break
            if not n:
                return w
            tok, kind = self.vocab[hitw]
            return ph.put(self._hit(w[:n], tok, kind)) + w[n:]
        return _WORD_RUN_RX.sub(rep, t)

    def text(self, s):
        """글 하나를 가린다 → 가린 글(공유 미리보기·보내는 내용 모두 이것을 거친다)."""
        if s is None:
            return ""
        t = _nfkc(s)
        t = _FULL_DATE_RX.sub(lambda m: f"{m.group(1)}-{int(m.group(2)):02d}", t)
        t = _DATE8_RX.sub(lambda m: f"{m.group(1)}-{m.group(2)}", t)
        t = _MAIL_TOKEN_RX.sub("[사람]", t)
        ph = _Ph()
        t = _SHARE_TOKEN_RX.sub(lambda m: ph.put(m.group(0)), t)
        t = _YM_RX.sub(lambda m: ph.put(m.group(0)), t)
        t = _ORDINAL_RX.sub(lambda m: ph.put(m.group(0)), t)
        # 연락처·식별자(허용 패턴과 상관없이 늘 가린다)
        t = RX["url"].sub(lambda m: ph.put(self._hit(m.group(0), "[코드]", "주소(URL)")), t)
        t = RX["email"].sub(lambda m: ph.put(self._hit(m.group(0), "[사람]", "메일 주소")), t)
        for k in ("mobile", "landline82", "landline", "intl"):
            t = RX[k].sub(lambda m: ph.put(self._hit(m.group(0), "[사람]", "전화번호")), t)
        for rx in (_ID_RRN, RX["card16"], RX["card15"], _ID_PASSPORT, _ID_LICENSE, RX["license_region"], _ID_ACCOUNT):
            t = rx.sub(lambda m: ph.put(self._hit(m.group(0), "[코드]", "식별번호")), t)
        # 맨 도메인(제한 고객·고객사·협력사 — 하위 도메인 포함)
        if self._drx is not None:
            t = self._drx.sub(lambda m: ph.put(self._hit(m.group(0), "[고객사]", "고객사 도메인")), t)
        # 사전(제한 고객 → 고객사·협력사 → 과제 이름·업무 분류 이름) — 띄어쓰기·하이픈 변형 포함
        if self._rx is not None:
            def rep(m):
                key = self._keys.get(flex_key(m.group(0))) or m.group(0)
                tok, kind = self.dic.get(key, ("[과제]", "업무 분류"))
                return ph.put(self._hit(m.group(0), tok, kind))
            t = self._rx.sub(rep, t)
        # 사람 — 이름 + 호칭 · 이름 해시
        before = t
        t = mask_titled_names(t)
        if t != before:
            self.hits.setdefault(("(호칭 이름)", "[사람]"), ["사람 이름", 0])[1] += t.count("[사람]") - before.count("[사람]")
        if self.hashes:
            before = t
            t = _hash_mask(t, self.hashes, self.salt)
            if t != before:
                self.hits.setdefault(("(이름)", "[사람]"), ["사람 이름", 0])[1] += t.count("[사람]") - before.count("[사람]")
        t = re.sub(r"\[사람\]", lambda m: ph.put(m.group(0)), t)
        # 내 업무·메일 낱말
        t = self._vocab_sub(t, ph)
        # 대문자로 시작하는 영문 고유 이름(회사·제품·사람 — 흔한 업무 영어·COMMON_CODES 는 뺀다)
        t = _CAP_WORD_RX.sub(lambda m: m.group(0) if (m.group(0) in COMMON_CODES or m.group(0).lower() in GENERIC_WORK)
                             else ph.put(self._hit(m.group(0), "[코드]", "영문 이름")), t)
        # 횟수·수량 낱말
        t = _NUM_WORD_RX.sub(lambda m: ph.put(self._hit(m.group(0), "[코드]", "횟수")), t)

        # 허용 패턴 — 이름·연락처·식별자를 다 가린 뒤에, 남은 공학 코드 표기만 지킨다(가린 부분·사전 낱말이 든 곳은 지키지 않는다)
        for p in self.allow:
            t = p.sub(lambda m: ph.put(m.group(0)) if self._allow_ok(m.group(0)) else m.group(0), t)

        # 코드 낱말
        def code(m):
            w = m.group(0)
            if w in COMMON_CODES or w.upper() in COMMON_CODES:
                return w
            return ph.put(self._hit(w, "[코드]", "코드·숫자"))
        t = _CODE_UP_RX.sub(code, t)
        t = _CODE_DIGIT_RX.sub(code, t)
        return re.sub(r"[ \t]{2,}", " ", ph.restore(t))

    def _allow_ok(self, s):
        """허용 패턴에 맞은 부분 s 를 지켜도 되는가 — 공학 코드 꼴(_code_span_ok: 숫자나 영문 대문자 2자 이상 · 한글 없음)이고, 이미
        가린 부분(자리표시자)·사전 낱말·식별번호 꼴이 들어 있지 않다(D22 — 허용 패턴은 이름을 지키지 못한다)."""
        if not _code_span_ok(s) or any(0xE000 <= ord(ch) <= 0xF8FF for ch in s):
            return False
        return not (self._rx is not None and self._rx.search(s)) and not _shields_identifier(s)

    def leftover(self, text):
        """가린 글(text() 의 결과)에 남은 '이름일 수 있는 낱말' → 목록(나온 순서 · 중복 없음). 가림 토큰·날짜·서수·숫자가 든 낱말·
        2자 미만·흔한 업무어(GENERIC_WORK)·보통 명사(COMMON_NOUNS)·COMMON_CODES·서술어는 뺀다. 공유 미리보기가 이 낱말이 남은
        항목을 표시하고 익명 팀 집계에는 넣지 않는다 — 보내기 전에 팀원이 확인한다(C4). 글을 바꾸지 않고 가린 건수(table)도
        세지 않는다."""
        t = _SHARE_TOKEN_RX.sub(" ", _MAIL_TOKEN_RX.sub(" ", _nfkc(text)))
        t = _ORDINAL_RX.sub(" ", _YM_RX.sub(" ", t))
        return list(dict.fromkeys(_vocab_tokens(t)))

    def table(self):
        """지금까지 바꾼 낱말 → [{"term","token","kind","hits"}] (많이 바꾼 것부터)."""
        rows = [{"term": term, "token": tok, "kind": kind, "hits": n} for (term, tok), (kind, n) in self.hits.items()]
        return sorted(rows, key=lambda r: (-r["hits"], r["term"]))


def scrub_shared(text, *, cfg, root=None, terms=()):
    """글 하나를 공유용으로 가린다 — ShareScrubber(cfg, root=root, terms=terms).text(text)."""
    return ShareScrubber(cfg, root=root, terms=terms).text(text)
