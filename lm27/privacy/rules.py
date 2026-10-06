# -*- coding: utf-8 -*-
r"""LM27 정제 규칙 — 버전 고정(P §5). 조직별 보정은 설정의 허용 패턴·문맥어로만(P §17) — 이 파일은 설정으로 못 바꾼다.

정규식·어휘·체크섬은 PRIVACY.md §5 코드 블록을 **바이트 그대로** 옮겼다(초판 검증 시제품과 같은 정규식). 한 글자라도
바꾸면 ``RULES_HASH`` 가 바뀌어 회귀 말뭉치 관문(``lm27.privacy.selftest`` · ``tools\lm27_selftest.py privacy``)의
'규칙 고정'이 실패한다 — 의도된 변경이면 P §16.4 절차(말뭉치 먼저 → ``RULES_VERSION`` 올림 → ``--update-lock``).

반복 상한 주의(P §6 구현 주의): 숫자·구분자 묶음에 무한 반복 ``*``/``+`` 를 쓰지 않는다(``\d[\d,]{0,24}`` 처럼 상한) —
병적 입력(``"1,"×8000``)에서 이차 시간 역추적이 난다(상한 없을 때 2.1초 실측).

이 모듈은 에이전트 bin 사본(계약 §1.3)에도 들어가므로 표준 라이브러리만 쓴다.
"""
from __future__ import annotations

import calendar
import hashlib
import json
import re


RULES_VERSION = "2026.10.1"
# 2026.10.0 → 2026.10.1(W1 통합 창 — P §16.4): ① 단계 0 정규화(detect) — 서식 문자(Cf: 소프트 하이픈·폭 0·단어 결합자 등)
# 삭제, 대시류(U+2010~2015·U+2212·U+FE58·U+FE63·U+FF0D) → '-' ② 띄운 구분자(' - '·' – ') 전화·카드 ③ 경로는 디렉터리
# 부분만 가리는 2단계(줄바꿈·뒤따르는 ':'·한 줄 두 경로·'/' 경로·file:/// · JSON 이스케이프 '\\' 경로) — 말뭉치 P61~ 참조.

# ── 5.0 단계 0 정규화(P §4 단계 0 — detect.sanitize 가 NFKC 직후에 쓴다. 규칙 해시에 든다) ─────────────────
#   · 제어 문자(C0·DEL·C1)·줄/문단 구분자·사설 영역(자리표시자 주입 방어) → 공백
#   · 서식 문자(유니코드 범주 Cf: 소프트 하이픈·폭 0 공백·결합자·방향 표지·단어 결합자·BOM 등) → 삭제(2026.10.1 —
#     공백으로 바꾸면 값 한가운데 끼운 서식 문자가 전화·이메일 탐지를 끊어 원문이 남았다)
#   · 대시류(U+2010~U+2015 · 빼기 U+2212 · 작은 em U+FE58 · 작은/전각 하이픈) → '-'(2026.10.1 — 자동 서식 ' – ' ·
#     비분리 하이픈으로 쓴 전화·주민·카드·사업자 번호 탐지. NFKC 처럼 정제문에도 반영된다)
CTRL_RX = re.compile("[\x00-\x08\x0b-\x1f\x7f-\x9f\u2028\u2029\ue000-\uf8ff]")
FORMAT_RX = re.compile("[\u00ad\u0600-\u0605\u061c\u06dd\u070f\u0890\u0891\u08e2\u180e\u200b-\u200f\u202a-\u202e"
                       "\u2060-\u2064\u2066-\u206f\ufeff\ufff9-\ufffb\U000110bd\U000110cd\U00013430-\U0001343f"
                       "\U0001bca0-\U0001bca3\U0001d173-\U0001d17a\U000e0001\U000e0020-\U000e007f]")
DASH_RX = re.compile("[\u2010-\u2015\u2212\ufe58\ufe63\uff0d]")

# ── 5.1 공통 경계 ─────────────────────────────────────────────────────────────
NB = r"(?<![0-9A-Za-z])"                    # 앞에 영숫자 없음
NA = r"(?![0-9A-Za-z])"                     # 뒤에 영숫자 없음
NBX = r"(?<![0-9A-Za-z\-./\\])"             # 코드 일부가 아님(앞에 영숫자·-·.·/·\ 없음) — DWG-2026-… 차단. '_' 는 파일명 구분자로 허용
NAX = r"(?![0-9A-Za-z]|[-/][0-9A-Za-z]|\.(?![A-Za-z]{2,5}(?![0-9A-Za-z]))[0-9A-Za-z])"  # 뒤에 영숫자·'구분자+영숫자' 없음(.pdf 같은 확장자는 허용)
NBP = r"(?<![0-9A-Za-z+/\\\-])"             # 전화용 앞 경계('.'·':'·'('·'_' 허용 → Tel.010…, 견적_010…)
NAP = r"(?![0-9A-Za-z]|-\d)"                # 전화용 뒤 경계

# ── 5.2 토큰 문법 (이 정규식에 맞는 문자열만 '기존 토큰'으로 보호 → 멱등) ────────────
TOKEN_RX = re.compile(
    r"\[(?:주민번호|외국인등록번호|생년월일|카드|전화|사업자번호|법인번호|여권|운전면허|계좌|IP|URL|경로|금액|비율|회사|나"
    r"|사람(?:#[0-9a-f]{6})?|고객사:[A-Za-z0-9_\-]{1,16}|과제:[A-Za-z0-9_\-]{1,16}|협력사:[A-Za-z0-9_\-]{1,16}"
    r"|이메일@[A-Za-z0-9.\-:가-힣]{1,64})]")

# ── 5.3 보호 구간 (탐지 전에 자리표시자로 가림) ─────────────────────────────────
PROTECT = [
    ("date", re.compile(NB + r"(?:19|20)\d{2}([-./])(?:0?[1-9]|1[0-2])\1(?:0?[1-9]|[12]\d|3[01])" + NA)),
    ("date8", re.compile(NB + r"(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])" + NA)),
    ("time", re.compile(NB + r"(?:[01]?\d|2[0-3]):[0-5]\d(?::[0-5]\d)?" + NA)),
    ("version", re.compile(r"(?i)(?:(?<![A-Za-z])(?:rev|ver|version|v|build|fw|sw|release)[._\s-]?"
                           r"|(?:버전|빌드|펌웨어|릴리스|개정)[_\s]?)\d+(?:\.\d+){1,3}")),
    ("std", re.compile(r"(?<![A-Za-z])(?:IEC|ISO|IEEE|KS\s?[A-Z]?|JIS|ASTM|MIL-STD|UL|EN|CISPR|SAE|JEDEC|IPC)"
                       r"[\s-]?\d{2,6}(?:[-.:]\d{1,4})*")),
]

# ── 5.4 자격증명 (하나라도 걸리면 행 폐기) ──────────────────────────────────────
CRED_KV = re.compile(
    r"(?i)(?:비밀번호|비번|패스워드|암호|password|passwd|pwd|pw|passcode|pin)\s*(?:[:=：]|은|는|is)\s*(?P<v>[^\s,;]{4,64})")
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


def _cred_value_ok(v: str) -> bool:
    """값처럼 보이면 True: 한글뿐·불용어가 아니고 (숫자 or 기호 or 대소문자 혼합)."""
    if CRED_STOP.match(v):
        return False
    has_digit = any(c.isdigit() for c in v)
    has_sym = any(not c.isalnum() for c in v)
    mixed = any(c.isupper() for c in v) and any(c.islower() for c in v)
    return has_digit or has_sym or mixed


def credential_hit(text: str) -> bool:
    for m in CRED_KV.finditer(text):
        if _cred_value_ok(m.group("v")):
            return True
    return bool(CRED_OTP.search(text) or CRED_TOKEN.search(text) or CRED_APIKEY.search(text))


# ── 5.5 문맥 사전 · 억제 문맥 ──────────────────────────────────────────────────
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
# 공학·식별 억제 문맥: 후보 바로 앞 10자 안에 있으면 문맥 게이트형 탐지(여권·면허·계좌·체크섬 실패 카드 등)를 하지 않는다
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


# ── 5.6 체크섬 ──────────────────────────────────────────────────────────────────
def luhn_ok(d: str) -> bool:
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


def rrn_checksum_ok(d13: str) -> bool:          # 2020-10 이후 발급분은 안 맞을 수 있음 → '가점'으로만 사용
    w = [2, 3, 4, 5, 6, 7, 8, 9, 2, 3, 4, 5]
    s = sum(int(a) * b for a, b in zip(d13[:12], w, strict=False))
    return (11 - s % 11) % 10 == int(d13[12])


def brn_ok(d10: str) -> bool:                   # 사업자등록번호
    w = [1, 3, 7, 1, 3, 7, 1, 3, 5]
    s = sum(int(a) * b for a, b in zip(d10[:9], w, strict=False)) + (int(d10[8]) * 5) // 10
    return (10 - s % 10) % 10 == int(d10[9])


def rrn_date_ok(d: str) -> bool:                # 앞 6자리 생년월일 + 7번째 성별자리(1~8) 유효성
    yy, mm, dd, g = int(d[0:2]), int(d[2:4]), int(d[4:6]), int(d[6])
    if not 1 <= g <= 8:
        return False
    year = (1900 if g in (1, 2, 5, 6) else 2000) + yy
    if not 1 <= mm <= 12:
        return False
    return 1 <= dd <= calendar.monthrange(year, mm)[1]


# ── 5.7 탐지기 표 ───────────────────────────────────────────────────────────────
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
    # 경로(2026.10.1): 드라이브·UNC 머리 + 디렉터리 부분(마지막 구분자까지)만 맞춘다 — 기본 이름은 글에 그대로 남고
    # 정제기가 '[경로]\' 로 바꾼다. 종결 조건(뒤따르는 ' - '·공백 2개·끝)을 요구하던 옛 식은 줄바꿈·':'·한 줄 두 경로에서
    # 경로 전체를 남겼다. 구분자는 '\'·'/' 섞임 허용(바로 뒤 구분자가 또 오면 끊는다 — 문장 속 '\\서버' 를 삼키지 않게),
    # JSON 이스케이프 경로('C:\\Users\\…')·이스케이프 UNC 는 '\\' 를 한 구분자로, '/' 드라이브 경로·file:/// 는 폴더 1단 이상.
    "path": re.compile(
        r"\\\\\\\\[A-Za-z0-9._\-$]+\\\\(?:[^\\/:*?\"<>|\r\n]+\\\\)*"
        r"|\\\\[A-Za-z0-9._\-$]+\\(?:[^\\/:*?\"<>|\r\n]+[\\/](?![\\/]))*"
        r"|(?<![A-Za-z0-9])[A-Za-z]:\\\\(?:[^\\/:*?\"<>|\r\n]+\\\\)*"
        r"|(?<![A-Za-z0-9])[A-Za-z]:\\(?![\\/])(?:[^\\/:*?\"<>|\r\n]+[\\/](?![\\/]))*"
        r"|(?:file:/{2,3})?(?<![A-Za-z0-9])[A-Za-z]:/(?![\\/])(?:[^\\/:*?\"<>|\r\n]+/(?![\\/]))+"),
    # 금액 (§7)
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

# ── 5.8 이름(호칭·멘션·라벨) ─────────────────────────────────────────────────────
SURNAMES = ("김이박최정강조윤장임한오서신권황안송류유전홍고문양손배백허남심노하곽성차주우구민진나지엄채원천방공현함변염여추도소석선설마"
            "길연위표명기반라왕금옥육인맹제모탁국어은편용예경봉사부가복태목형피두감음빈동온호범좌팽승간상시갈단견당화창")
COMPOUND_SURNAMES = ("남궁", "황보", "제갈", "선우", "독고", "사공", "서문", "동방")
TITLES = (r"(?:님|씨|책임|선임|수석|매니저|프로|팀장|파트장|그룹장|실장|센터장|본부장|부장|차장|과장|대리|사원|주임|연구원|위원|박사"
          r"|교수|님께)")
NAME_STOP = {"이번주", "지난주", "다음주", "이번달", "지난달", "다음달", "이번에", "우리측", "고객사", "협력사", "공급사", "제조사", "주관사",
             "발주처", "수요처", "담당자", "책임자", "관계자", "작성자", "검토자", "승인자", "요청자", "참석자", "사용자", "관리자", "운영자",
             "여러분", "선생님", "전체팀", "각부서"}
NAME_SUFFIX_STOP = ("팀", "측", "처", "실")
HONORIFIC = re.compile(r"(?<![가-힣])(?P<name>[가-힣]{2,4})\s?(?=" + TITLES
                       + r"(?:[^가-힣]|$|께|이|은|는|과|와|의|도|한테|에게|님))")
MENTION = re.compile(r"@(?P<name>[가-힣]{2,4}|[A-Za-z][A-Za-z.\-]{1,30})(?=[\s,.:)!?]|$)")
LABELED_NAME = re.compile(r"(?:예금주|성명|이름|수신인|받는\s?분|보내는\s?분|작성자|담당자)\s*[:：]?\s*(?P<name>[가-힣]{2,4})(?![가-힣])")


def plausible_korean_name(n: str) -> bool:
    """호칭형 후보가 사람 이름으로 그럴듯한가: 3자 + 흔한 성, 또는 4자 + 복성. 일반어·조직 접미 제외."""
    if n in NAME_STOP or n.endswith(NAME_SUFFIX_STOP):
        return False
    if len(n) == 3 and n[0] in SURNAMES:
        return True
    return len(n) == 4 and n[:2] in COMPOUND_SURNAMES


# 공용 개인 메일 도메인(내장 기본값 — 설정으로 추가·해제, §17)
PERSONAL_MAIL_DOMAINS = ("gmail.com", "naver.com", "daum.net", "hanmail.net", "kakao.com", "nate.com", "outlook.com",
                         "hotmail.com", "live.com", "yahoo.com", "icloud.com", "me.com", "proton.me")

# 코파일럿 게이트에서 '잔여 시 행 제외'인 고위험 범주 (§13)
HIGH = {"rrn", "frn", "birth", "card", "passport", "license", "account", "phone", "email", "cred", "brn", "corp"}


# ── 규칙 해시(P §16.2) ───────────────────────────────────────────────────────────
# rules·classify 모듈의 모든 re.Pattern(패턴 문자열 + 플래그), RX·PROTECT·CTX 표, 어휘·가중치 상수와 RULES_VERSION 을
# 키 이름순 JSON(ensure_ascii=False, sort_keys=True)으로 덤프한 sha256 앞 16자. 창 분류 목록(frozenset)과 ABS_HINT 도
# 넣는다(판정 결과를 바꾸는 고정 상수 — P §16.2 목록에 더함). keys.py 의 문서군·키 상수는 넣지 않는다(KEYS_VERSION 몫).
HASH_NAMES = frozenset({
    "CTX", "NAME_STOP", "NAME_SUFFIX_STOP", "SURNAMES", "COMPOUND_SURNAMES", "HIGH", "AD_DROP", "AD_SUSPECT",
    "PRIV_THRESHOLD", "RULES_VERSION", "PERSONAL_MAIL_DOMAINS", "BROWSER_EXES", "PRIVATE_EXES", "MEDIA_EXES",
    "TITLE_KEEP_CLASSES", "PRIVATE_APP_CLASSES", "MEDIA_APP_CLASSES"})
_PAIR_TABLES = ("PROTECT", "ABS_HINT")       # [(이름, 패턴), …]


def _rule_namespace() -> dict:
    """rules·classify 모듈의 전역. classify 는 detect → rules 를 import 하므로 함수 안에서 지연 import 한다."""
    from . import classify
    ns = dict(vars(classify))
    ns.update(globals())
    return ns


def rules_hash() -> str:
    """지금 메모리에 있는 규칙의 해시(16hex). 부를 때마다 다시 계산한다 — 시험이 규칙을 바꿔 끼우면 바로 드러난다."""
    parts = {}
    for name, val in sorted(_rule_namespace().items()):
        if isinstance(val, re.Pattern):
            parts[name] = [val.pattern, val.flags]
        elif name == "RX":
            parts[name] = {k: [x.pattern, x.flags] for k, x in val.items()}
        elif name in _PAIR_TABLES:
            parts[name] = [[k, x.pattern, x.flags] for k, x in val]
        elif name in HASH_NAMES:
            parts[name] = sorted(val) if isinstance(val, (set, frozenset)) else val
    blob = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=list).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


def __getattr__(name: str):
    """``RULES_HASH`` — 처음 읽을 때 한 번 계산해 고정한다(P §16.2 'import 시 계산'. classify 와의 순환 import 때문에
    모듈 최상위가 아니라 첫 접근 시점). ``lm27.privacy`` 재수출·lint L-24 대조·에이전트 사본 대조가 이 값을 쓴다."""
    if name == "RULES_HASH":
        h = rules_hash()
        globals()["RULES_HASH"] = h
        return h
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
