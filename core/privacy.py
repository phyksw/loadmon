# -*- coding: utf-8 -*-
r"""
privacy.py — LM28 개인정보 정제 단일원. 네 관문이 같은 규칙을 쓴다:
  G1 수집 직후(run.py → scrub_csv) · G2 적재(extract.load_signals 의 add → sanitize·ad_score·private_score) ·
  G3 Copilot 직전(gate_items + gate_prompt) · G4 팀 반출(team_export_rows — export.py·teamup.py 공용).

LM27 lm27\privacy 에서 옮긴 것: rules.py 의 정규식 표(RX·CTX·ENG_CTX·HONORIFIC·PERSONAL_MAIL_DOMAINS·
ENG_UNIT_AFTER·COUNT_AFTER·DIM_NEAR·ID_BEFORE·credential_hit·체크섬), detect.py:193 정제 단계 순서,
classify.py 의 ad_score(헤더 항목 제외 — 수집 경로가 헤더를 주지 않는다: AD_PARTIAL)·private_score·window_class,
gate.py:165 의 G3 필터 순서. 가져오지 않은 것: HMAC 키링(사람은 [사람] 하나로)·소급 가림·해시 관문·감사 스키마.
LM28 에서 바꾼 점:
  · 사전 가명화는 ID 없이 [고객사]·[협력사]·[과제]·[나] — 설정 privacy.customers·partners(이름 또는
    {"names":[…],"domains":[…]}), maskCodenames(기본 false)면 level1Codenames 를 [과제] 로.
  · 'pin' 자격증명은 숫자 4~8자리 값만(회로의 'pin: GPIO12' 같은 공학 표기를 행 폐기하지 않게).
  · NAME_STOP 을 업무어로 넓혔다(호칭형 오탐 '안전성 수석' 류 방지).

불변식:
  · 멱등 — sanitize(sanitize(x)) == sanitize(x). 기존 토큰은 보호 구간이라 토큰 안 숫자를 다시 잡지 않는다.
  · 결정적 — 난수·시각 없음. 정제 함수는 원문을 출력·기록하지 않는다(감사 파일에는 범주별 건수·RULES_VER 만).
  · 수집기가 소유한 CSV 에 열을 더하지 않는다(scrub_csv) — 파일별 RULES_VER 는 data\privacy_audit.json 에.
  · 표준 라이브러리만.
"""
from __future__ import annotations

import calendar
import csv
import functools
import io
import ipaddress
import json
import os
import re
import time
import unicodedata

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RULES_VER = "lm28.1"          # 규칙(정규식·어휘·순서)을 바꾸면 올린다 — privacy_audit.json 에 파일별로 남는다
MAX_SCAN = 4000               # 한 필드에서 보는 최대 글자 수(병적 입력 방어)
EXTRA_PC_DIR = "추가PC"        # core\extract.EXTRA_PC_DIR 과 같은 값(data\추가PC\<PC>\)

# 내장 개인 폴더·파일 제외어 — mine.py 의 EXCLUDE 를 옮겨 온 단일원. excluded_keywords(cfg) 가 설정 목록과 합친다
EXCLUDE = ["개인", "사생활", "가족", "취미", "이력서", "면접", "취준", "자소서", "이직",
           "downloads", "다운로드", "temp", "임시", "공부", "인강"]

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
    r"|사람(?:#[0-9a-f]{6})?|(?:고객사|협력사|과제)(?::[A-Za-z0-9_\-]{1,16})?"
    r"|이메일@[A-Za-z0-9.\-:가-힣]{1,64})]")
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
                     r"|과제\s?번호|eco|ecn|품목|코드|code|모델|model|rev|ver)")
ID_BEFORE = re.compile(r"(?i)(?:(?<![A-Za-z])(?:po|pr|so|no|order)|오더|번호|코드|#)\s*[:.#]?\s*$")
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


# ── 탐지기 표 ───────────────────────────────────────────────────────────────────
RX = {
    "birth": re.compile(
        r"(?i)(?:생년월일|출생일|출생|date\s?of\s?birth|birth\s?date|dob)\s*[:：]?\s*(?P<d>(?:19|20)?\d{2}\s?[-./년]\s?"
        r"(?:0?[1-9]|1[0-2])\s?[-./월]\s?(?:0?[1-9]|[12]\d|3[01])\s?일?|(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])"
        r"|\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01]))(?![0-9])"),
    "rrn_front": re.compile(r"(?:주민|주민등록|주민번호)[^\d\n]{0,8}(?P<d>\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01]))(?![0-9\-–—*])"),
    "rrn": re.compile(NB + r"\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])(?P<sep>\s?[-–—]\s?|\s?)[1-8]\d{6}" + NA),
    "rrn_masked": re.compile(NB + r"\d{6}\s?[-–—]\s?[1-8](?:[*xX●○■]{6}|\d[*xX●○■]{5})"),
    "card16": re.compile(NB + r"(?:\d{4}(?:\s?-\s?|\s)?){3}\d{4}" + NA),
    "card15": re.compile(NB + r"3[47]\d{2}(?:\s?-\s?|\s)?\d{6}(?:\s?-\s?|\s)?\d{5}" + NA),
    "card_masked": re.compile(NB + r"\d{4}(?:\s?-\s?|\s)?(?:[*xX●]{4}(?:\s?-\s?|\s)?){2}\d{4}" + NA),
    "mobile": re.compile(NBP + r"(?:(?:\+|00)82[-.\s]?(?:\(0\))?\s?1[016789]|01[016789])\s?[-.\s)]{0,2}\d{3,4}\s?[-.\s]{0,2}\d{4}"
                         + NAP),
    "landline": re.compile(NBP + r"\(?0(?:2|3[1-3]|4[1-4]|5[1-5]|6[1-4]|70|50[2-8])\)?\s?[-.\s)]{1,2}\d{3,4}\s?[-.\s]\s?\d{4}"
                           + NAP),
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
          r"|교수|님께)")
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


# 공용 개인 메일 도메인 · Copilot·팀 반출에서 '잔여 시 행 제외'인 고위험 범주
PERSONAL_MAIL_DOMAINS = ("gmail.com", "naver.com", "daum.net", "hanmail.net", "kakao.com", "nate.com", "outlook.com",
                         "hotmail.com", "live.com", "yahoo.com", "icloud.com", "me.com", "proton.me")
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
    out = []
    for p in _as_list(pats):
        if isinstance(p, re.Pattern):
            out.append(p)
            continue
        try:
            out.append(re.compile(str(p)))
        except re.error:
            continue                       # 틀린 허용 패턴은 무시(정제는 계속 — 가림이 줄지 않는 쪽)
    return out


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


def _data_roots(data_dir):
    """본 수집 폴더 + data\\추가PC\\* (core\\extract._data_roots 와 같은 목록)."""
    roots = [data_dir]
    base = os.path.join(data_dir, EXTRA_PC_DIR)
    if os.path.isdir(base):
        try:
            roots += sorted(os.path.join(base, n) for n in os.listdir(base) if os.path.isdir(os.path.join(base, n)))
        except OSError:
            pass
    return roots


def me_list(data_dir=None):
    """mail_source.json 의 me[](본인 표시 이름·주소) — 모든 루트 합집합. 없으면 []."""
    data_dir = data_dir or os.path.join(ROOT, "data")
    out = []
    for root in _data_roots(data_dir):
        try:
            with open(os.path.join(root, "outlook", "mail_source.json"), encoding="utf-8-sig") as f:
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


def _truthy(v):
    return v is True or str(v).strip().lower() in ("true", "1", "yes", "y", "on")


def make_ctx(cfg=None, data_dir=None):
    """설정(privacy.customers·partners·allowPatterns·maskCodenames · owner·teamsSelfNames)과 mail_source me[] 로
    정제 문맥을 만든다. 사내 도메인 = privacy.internalDomains(선택 키) ∪ me[] 주소의 도메인."""
    cfg = cfg if isinstance(cfg, dict) else {}
    pv = cfg.get("privacy") if isinstance(cfg.get("privacy"), dict) else {}
    me = me_list(data_dir)
    names = [cfg.get("owner")] + _as_list(cfg.get("teamsSelfNames")) + [x for x in me if "@" not in x]
    internal = _as_list(pv.get("internalDomains")) + [domain_of(x) for x in me if "@" in x]
    codenames = []
    if _truthy(pv.get("maskCodenames")):
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


@functools.lru_cache(maxsize=256)
def _dict_rx(names):
    """사전 매칭(긴 이름 먼저, 대소문자 무시). ASCII 이름은 양쪽 영숫자 경계, 한글 든 이름은 앞 경계만(뒤에 조사)."""
    uniq = sorted({n for n in names if n}, key=lambda n: (-len(n), n))
    mixed = [re.escape(n) for n in uniq if not _ASCII_NAME.fullmatch(n)]
    ascii_ = [re.escape(n) for n in uniq if _ASCII_NAME.fullmatch(n)]
    parts = []
    if mixed:
        parts.append(r"(?<![가-힣A-Za-z0-9])(?:" + "|".join(mixed) + ")")
    if ascii_:
        parts.append(r"(?<![A-Za-z0-9])(?:" + "|".join(ascii_) + r")(?![A-Za-z0-9])")
    return re.compile("|".join(parts), re.I) if parts else None


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

    # ③ 기존 토큰 보호(멱등) · 조직 허용 패턴
    t = TOKEN_RX.sub(lambda m: ph.put(m.group(0)), t)
    for p in ctx.allow_patterns:
        t = p.sub(lambda m: ph.put(m.group(0)), t)
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

    # ⑧ 이름 문맥: 멘션 → 라벨형 → 호칭형(호칭형은 흔한 성씨 검사 + NAME_STOP)
    def name_sub(require_plausible):
        def rep(m):
            n = m.group("name")
            if require_plausible and re.fullmatch(r"[가-힣]+", n) and (not plausible_korean_name(n)
                                                                     or n in ctx.extra_stop):
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
AD_PARTIAL = True             # LM28 수집 경로(COM·색인·OWA·Copilot)는 메일 헤더를 주지 않는다 — 헤더 가점 없이 같은 임계
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


def private_score(text, is_1to1=None, offhours=False, partner_personal=False, *, sensitivity=0,
                  private_category=False):
    """정제문 하나의 공사 판정(LM27 classify.private_score, 방 성향 생략) → "work" | "private" | "social".
    점수 = 2×강한 사적어 + 약한 사적어 + 친목어 − 2×min(업무어,4) − 업무 응답어, 업무 토큰([과제]·[고객사]·[협력사]) −3,
    1:1 +1 / 단체(is_1to1=False) −1, 표준창 밖(평일 19~07시·주말) +1, 상대가 개인 메일 도메인 +3.
    2 이상이면 private(친목어만 있고 강한 사적어가 없으면 social), 아니면 work. 민감도 1·2·개인 범주는 즉시 private."""
    if sensitivity in (1, 2) or private_category:
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
    if offhours:
        s += 1
    if partner_personal:
        s += 3
    if s >= PRIV_THRESHOLD:
        return "social" if so and not ps else "private"
    return "work"


def is_personal_addr(addr, ctx=None):
    """상대 주소가 공용 개인 메일 도메인인가(gmail·naver …)."""
    dom = domain_of(addr)
    return bool(dom) and dom in _as_ctx(ctx).personal_domains


# ── 창 샘플 — 비업무 앱·사이트 ─────────────────────────────────────────────────────────
BROWSER_EXES = frozenset({"msedge.exe", "chrome.exe", "firefox.exe", "whale.exe", "opera.exe", "brave.exe", "iexplore.exe"})
PRIVATE_EXES = frozenset({"kakaotalk.exe", "telegram.exe", "discord.exe", "whatsapp.exe", "line.exe", "steam.exe",
                          "steamwebhelper.exe", "epicgameslauncher.exe", "battle.net.exe", "leagueclient.exe",
                          "riotclientservices.exe"})
MEDIA_EXES = frozenset({"spotify.exe"})
SYSTEM_EXES = frozenset({"lockapp.exe", "logonui.exe", "screensaver.exe", "scrnsave.scr", "idle"})
INPRIVATE_RX = re.compile(r"(?i)InPrivate|Incognito|시크릿|비공개\s?창|Private\s?Browsing")
BROWSER_SUFFIX_RX = re.compile(r"\s[-–—]\s(?:(?P<profile>[^-–—]{1,40}?)\s[-–—]\s)?"
                               r"(?:Microsoft\s*Edge|Google\s*Chrome|Mozilla\s*Firefox|Whale|Opera|Brave)\s*$", re.I)
PRIVATE_PROFILES = frozenset({"개인", "Personal"})
PRIVATE_SITE_RX = re.compile(
    r"(?i)(쿠팡|11번가|G마켓|옥션|SSG\.COM|무신사|오늘의집|배달의민족|요기요|당근|번개장터|중고나라|넷플릭스|Netflix|티빙|TVING|웨이브|wavve"
    r"|왓챠|디즈니\+|Disney\+|쿠팡플레이|인터넷뱅킹|스마트뱅킹|증권|주식|코인|업비트|빗썸|웹툰|나무위키|디시인사이드|DC인사이드|인스타그램"
    r"|Instagram|Facebook|페이스북|트위터|Twitch|치지직|아프리카TV|SOOP|네이버\s?카페|다음\s?카페|부동산)")
MEDIA_SITE_RX = re.compile(r"(?i)(YouTube|유튜브|멜론|Melon|Spotify|SoundCloud)")
WORK_SITE_RX = re.compile(
    r"(?i)(SharePoint|OneDrive|Outlook|Teams|Microsoft 365|Office 365|Copilot|Power BI|Confluence|Jira|GitHub|GitLab|Bitbucket"
    r"|Jenkins|Redmine|Azure DevOps|Stack Overflow|Microsoft Learn|Datasheet|데이터시트|IEEE Xplore|ScienceDirect"
    r"|Google Scholar|DBpia|RISS|KIPRIS|Espacenet|Digi-?Key|Mouser|Octopart|PLM|ERP|MES|SAP|Windchill|Teamcenter|Polarion|DOORS)")
ZERO_WIDTH_RX = re.compile("[​-‏⁠﻿]")      # Edge 창 제목의 'Microsoft​ Edge' 등 — 판정 전 제거


def window_class(exe, title):
    """창 샘플 한 건의 공사 판정(LM27 classify.window_class 축약) → "work" | "private" | "media" | "unknown".
    제목은 판정에만 쓰고 돌려주지 않는다. 비업무 앱·InPrivate·개인 프로필·사적 사이트 → private, 미디어 → media,
    브라우저의 업무 사이트 → work, 그 밖의 웹 → unknown, 잠금·유휴 → unknown, 모르는 프로그램 → work(업무 신호)."""
    e = os.path.basename(str(exe or "").strip().strip('"')).lower()
    if e and not e.endswith((".exe", ".scr")) and e not in SYSTEM_EXES:
        e += ".exe"
    t = ZERO_WIDTH_RX.sub("", unicodedata.normalize("NFKC", str(title or "")))
    if e in PRIVATE_EXES:
        return "private"
    if e in MEDIA_EXES:
        return "media"
    if e in BROWSER_EXES:
        if INPRIVATE_RX.search(t):
            return "private"
        m = BROWSER_SUFFIX_RX.search(t)
        profile = (m.group("profile") or "").strip() if m else ""
        if profile and profile in PRIVATE_PROFILES:
            return "private"
        # 가운데 조각은 프로필이 아니라 사이트 이름일 수도 있다('PRJ-1 - Jira - Microsoft Edge') — 사이트 판정에는 넣는다
        page = (t[:m.start()] + (" " + profile if profile else "")) if m else t
        if PRIVATE_SITE_RX.search(page):
            return "private"
        if MEDIA_SITE_RX.search(page):
            return "media"
        if WORK_SITE_RX.search(page):
            return "work"
        return "unknown"
    if not e or e in SYSTEM_EXES:
        return "unknown"
    return "work"


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


def gate_items(items, fields, cfg=None, *, canaries=None, ctx=None, max_chars=400, data_dir=None):
    """G3 — Copilot 에 보내기 직전의 행 관문(LM27 gate.py:165 순서). items = dict 목록(원본은 바꾸지 않는다).
    → (보낼 행 목록, 제외 건수 {사유: n}). 사유: 사적 · 광고의심 · 자격증명 · 개인정보:<범주> · 카나리아.
    ① 사적/친목(priv·priv_class)·광고 의심(flag 'ad') 행 제외 ② fields 재정제 ③ 자격증명 → 제외
    ④ 고위험(HIGH) 잔여 → 제외(가려 보내지 않는다 — 앞 관문이 놓친 신호) ⑤ 카나리아 → 제외
    ⑥ [사람#…] → [사람] 통일 ⑦ 필드마다 max_chars(400)자 — 토큰을 자르지 않는다."""
    flds = [fields] if isinstance(fields, str) else list(fields or ())
    if ctx is None:
        ctx = make_ctx(cfg, data_dir)
    cans = (_norm_canaries(canaries) if canaries is not None
            else canaries_fn(cfg, data_dir))
    kept, dropped = [], {}

    def drop(why):
        dropped[why] = dropped.get(why, 0) + 1

    for it in items or ():
        if not isinstance(it, dict):
            continue
        if str(it.get("priv") or it.get("priv_class") or "").strip().lower() in ("private", "social"):
            drop("사적")
            continue
        if _AD_FLAG.search(str(it.get("flag") or "")):
            drop("광고의심")
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
            if canary_in(clean, cans):
                bad = "카나리아"
                break
            new[f] = safe_truncate(PERSON_TAG_RX.sub("[사람]", clean), max_chars)
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


def gate_prompt(text, cfg=None, *, canaries=None, ctx=None, data_dir=None):
    """G3 최종 프롬프트 검사 → True(보내도 됨). 자격증명·고위험 잔여·카나리아가 하나라도 있으면 False(그 배치는 보내지
    않는다). 이미 정제된 토큰은 보호 구간이라 다시 걸리지 않는다."""
    if ctx is None:
        ctx = make_ctx(cfg, data_dir)
    cans = _norm_canaries(canaries) if canaries is not None else canaries_fn(cfg, data_dir)
    for part in _chunks(text):
        _c, cats, dr = sanitize(part, "prompt", ctx)
        if dr or any(k in HIGH for k in cats):
            return False
    return not canary_in(text, cans)


# ── 제외어 단일원 ─────────────────────────────────────────────────────────────────
def excluded_keywords(cfg=None):
    """개인 폴더·파일 제외어 = 내장 EXCLUDE ∪ config.excludePathKeywords (정렬 목록). mine·judge·refine·run 이 같이 쓴다."""
    cfg = cfg if isinstance(cfg, dict) else {}
    return sorted(set(EXCLUDE) | {str(k) for k in _as_list(cfg.get("excludePathKeywords")) if str(k).strip()})


# ── G1 수집 직후 — CSV 제자리 정제 ─────────────────────────────────────────────────────
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
        tmp = f"{path}.{os.getpid()}.lm28tmp"
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
    _audit_write(ap, base, path, {"rules_ver": RULES_VER, "at": time.strftime("%Y-%m-%d %H:%M"),
                                  "rows_in": info["rows_in"], "rows_out": info["rows_out"],
                                  "dropped": dropped, "folded": folded, "cats": info["cats"]})
    return info


# ── G4 팀 반출 ─────────────────────────────────────────────────────────────────────
WHO_CLASSES = ("사내", "고객사", "협력사", "외부")
TEAM_DROP_COLS = ("flag",)            # 팀으로 내보내지 않는 열(광고 의심 표식 등 로컬 판정용)
_EXTERNAL_MARK = re.compile(r"\((?:외부|external|guest|게스트)\)", re.I)


def who_class(who, ctx=None):
    """신호의 who(발신자 표시 이름·주소) → 도메인 계급 사내 | 고객사 | 협력사 | 외부(빈 값은 빈 값).
    사전(고객사·협력사 이름) → 주소 도메인(사내·고객사·협력사 도메인, 그 밖 외부) → '(외부)' 표기 → 사내.
    주소 없는 표시 이름은 Exchange 사내 사용자인 경우가 대부분이라 사내로 둔다."""
    w = str(who or "").strip()
    if not w:
        return ""
    if w in WHO_CLASSES:
        return w
    if w in ("나", "[나]"):
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


def team_export_rows(rows, ctx=None, *, info=None):
    """G4 팀 반출 행 변환 → 새 행 목록(dict — 원본은 바꾸지 않는다). export.py(공유폴더)·teamup.py(서버 묶음·
    --to-folder)가 같이 쓴다. who → 계급(사내|고객사|협력사|외부), text 재정제, 자격증명·HIGH 잔여 행은 그 행만 빼고,
    flag 열은 뺀다. info(dict)를 주면 rows_in·rows_out·high_dropped 를 채운다."""
    ctx = _as_ctx(ctx)
    out, n_in, n_high = [], 0, 0
    for r in rows or ():
        if not isinstance(r, dict):
            continue
        n_in += 1
        nr = {k: v for k, v in r.items() if k is not None and k not in TEAM_DROP_COLS}
        if "who" in nr:
            nr["who"] = who_class(nr.get("who"), ctx)
        if "text" in nr:
            clean, cats, dr = sanitize(nr.get("text") or "", "text", ctx)
            if dr or any(k in HIGH for k in cats):
                n_high += 1
                continue
            nr["text"] = clean
        out.append(nr)
    if isinstance(info, dict):
        info.update(rows_in=n_in, rows_out=len(out), high_dropped=n_high)
    return out


def canary_hit(rows, canaries=None, *, cfg=None, data_dir=None):
    """반출할 행(들)의 키·값 어디에든 카나리아(이 PC·본인 식별자)가 있는가 — 있으면 그 파일은 통째로 내보내지 않는다."""
    cans = _norm_canaries(canaries) if canaries is not None else canaries_fn(cfg, data_dir)
    if not cans:
        return False
    for r in rows or ():
        vals = list(r.items()) if isinstance(r, dict) else [(None, r)]
        for k, v in vals:
            if (k and canary_in(k, cans)) or canary_in(v, cans):
                return True
    return False


def team_export_csv(text, ctx=None, canaries=None, *, cfg=None, data_dir=None):
    """signals CSV 본문(문자열) → (반출 본문 또는 None, info). None 이면 그 파일을 내보내지 않는다(카나리아·형식 오류).
    info: rows_in·rows_out·high_dropped·canary·why."""
    info = {"rows_in": 0, "rows_out": 0, "high_dropped": 0, "canary": False, "why": ""}
    if ctx is None:
        ctx = make_ctx(cfg, data_dir)
    try:
        rd = csv.DictReader(io.StringIO(str(text or ""), newline=""))
        fields = [f for f in (rd.fieldnames or []) if f not in TEAM_DROP_COLS]
        rows = list(rd)
    except csv.Error as e:
        info["why"] = f"형식 오류({e})"
        return None, info
    out = team_export_rows(rows, ctx, info=info)
    cans = _norm_canaries(canaries) if canaries is not None else canaries_fn(cfg, data_dir)
    if canary_hit(out, cans):
        info["canary"] = True
        info["why"] = "이 PC·본인 식별자(카나리아)가 남아 있어 신호 파일을 통째로 빼고 보냅니다"
        return None, info
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore", lineterminator="\r\n")
    w.writeheader()
    for r in out:
        w.writerow({f: r.get(f, "") for f in fields})
    return buf.getvalue(), info


def team_export_file(src, dst, ctx=None, canaries=None, *, cfg=None, data_dir=None):
    """signals CSV 파일 → 반출 사본(dst, UTF-8 BOM). → info(+ written). 카나리아·읽기 실패면 쓰지 않는다."""
    try:
        with open(src, encoding="utf-8-sig", errors="replace", newline="") as f:
            text = f.read()
    except OSError as e:
        return {"written": False, "why": f"읽기 실패({type(e).__name__})"}
    out, info = team_export_csv(text, ctx, canaries, cfg=cfg, data_dir=data_dir)
    if out is None:
        info["written"] = False
        return info
    with open(dst, "w", encoding="utf-8-sig", newline="") as f:
        f.write(out)
    info["written"] = True
    return info
