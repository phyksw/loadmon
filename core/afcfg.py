# -*- coding: utf-8 -*-
r"""
afcfg.py — AgentFinder32 설정 기본값·하한 단일원(spec §6.4 · D22).

계약
  · DEFAULTS — config\config.default.json(= 배포하는 config\config.json)의 모든 설정 키와 기본값('_설명' 류 설명 키는 뺀다).
    두 파일은 DEFAULTS 에 블록마다 한국어 '_설명' 을 붙인 것이다. 키를 더하거나 바꾸면 여기와 두 파일을 함께 바꾼다.
  · get(cfg, "a.b", default=…) → 설정값. 없거나 None 이면 DEFAULTS 의 값(복사본), 그것도 없으면 default.
    D22 하한이 걸린 키(CLAMPED_KEYS)는 하한을 적용한 값을 돌려준다 — 설정 파일로 규칙을 약하게 만들 수 없다.
  · effective(cfg) → (cfg2, warnings). cfg2 = DEFAULTS 위에 cfg 를 깊게 겹친 새 dict(원본은 바꾸지 않는다) +
    D22 하한 적용 + 없어진 '규칙을 약하게 하는' 토글 제거. warnings = 한국어 문장 목록(run_meta.config_warnings·화면에 그대로).
  · load(root) → config\config.json(utf-8-sig) dict — 없으면 config\config.default.json, 그것도 없거나 깨졌으면 {}.
  · load_effective(root) → effective(load(root)).

D22 하한(설정은 더 엄격하게만 바꿀 수 있다)
  period.maxDays ≤ 92 · retention.rawDays ≤ 30 · intermediateDays ≤ 30 · resultDays ≤ 90 · htmlDays ≤ 90 · shareDays ≤ 30 ·
  serverPersonalDays ≤ 90 · serverTeamDays ≤ 180 (모든 일수 ≥ 1) · team.minGroupSize ≥ 5 · team.minCellSize ≥ 3 ·
  copilotAuto.requireWorkAccount 는 늘 true(회사 테넌트 밖 Copilot 금지 — R11).
  privacy.excludeCategories·excludeMailFolders·excludeKeywords 는 더하기만 한다(D3 — 기본 목록 ∪ 설정 목록. 개인·Personal·
  Private·사적 범주·폴더는 설정으로 뺄 수 없다). privacy.allowPatterns 는 정규식이고, 빈 글이나 개인 식별번호·연락처 형태의
  합성 견본(ALLOW_PROBES — 주민·외국인등록·카드·전화·메일 주소·계좌)·이름 견본(ALLOW_NAME_PROBES)에 맞는 넓은 식은 받지 않는다
  (allow_pattern_problem). privacy.sensitiveFilter.allowWords 는 공학·업무 문맥 낱말이 든 표현만 받는다(allow_word_problem).
  privacy.internalDomains 에서 공용 개인 메일 도메인(PERSONAL_MAIL_DOMAINS)은 뺀다. share.allowedNetworks 에서 너무 넓은
  대역(IPv4 /8 · IPv6 /32 미만)·멀티캐스트·링크 로컬·예약·지정되지 않은 대역은 빼고, 공인 대역은 알린다.
  privacy.contact {name, channel} 는 운영 담당이 채우는 문의·이의 창구(글자만 · 길이 상한).
  범위를 벗어난 값·형식 오류는 잘라 쓰고 warnings 에 적는다.

표준 라이브러리만. 이 모듈은 다른 core 모듈을 읽지 않는다(누구나 먼저 import 할 수 있다).
"""
import copy
import ipaddress
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PERIOD_MAX_DAYS = 92               # 분석 기간 상한(일) — 코드 하한. 설정은 이보다 짧게만
RETENTION_MAX = {                  # 보관 일수 상한(D13) — 설정은 이보다 짧게만
    "rawDays": 30, "intermediateDays": 30, "resultDays": 90, "htmlDays": 90, "shareDays": 30,
    "serverPersonalDays": 90, "serverTeamDays": 180,
}
TEAM_MIN = {"minGroupSize": 5, "minCellSize": 3}   # 익명 팀 집계 최소 인원(D16) — 설정은 이보다 크게만
CHANNELS = ("com", "owa", "copilot")               # 수집 경로(D1) — 이 안에서만 고른다
# 공용 개인 메일 도메인 — 사내 도메인이 될 수 없다(D7 · core\privacy 가 같은 목록을 쓴다)
PERSONAL_MAIL_DOMAINS = ("gmail.com", "naver.com", "daum.net", "hanmail.net", "kakao.com", "nate.com", "outlook.com",
                         "hotmail.com", "live.com", "yahoo.com", "icloud.com", "me.com", "proton.me")
CONTACT_MAX = {"name": 40, "channel": 120}         # privacy.contact 글자 수 상한(안내문에 그대로 싣는다)

DEFAULTS = {
    "owner": "",
    "function": "",
    "period": {"maxDays": PERIOD_MAX_DAYS},
    "collect": {"channels": list(CHANNELS), "cursorEpoch": 1, "mailAllPaths": False, "mailTimeOffsetH": 0},
    "outlook": {"subfolders": True, "attachWaitSec": 120, "ostStaleH": 72},
    "outlookBudgetSec": 0,
    "owaExtraFolders": True,
    "owaExtraFolderMax": 40,
    "owaExtraFolderSkip": [],
    "calendar": {"collectBody": False, "bodyToAI": False, "noteMaxChars": 160, "tentativeMeetings": "count"},
    "storeMailSubject": True,
    "privacy": {
        "internalDomains": [],
        "restrictedCustomersFile": "config\\restricted_customers.json",
        "excludeCategories": ["개인", "Personal", "Private", "사적"],
        "excludeMailFolders": ["개인", "Personal", "Private", "사적"],
        "excludeKeywords": ["개인", "가족", "사생활", "이력서", "자소서", "면접", "이직", "병원", "의료", "보험", "연말정산",
                            "자격증", "취미"],
        "sensitiveFilter": {"extraWords": [], "allowWords": []},
        "customers": [],
        "partners": [],
        "codenames": [],
        "allowPatterns": [],
        "maskCodenames": False,
        "contact": {"name": "", "channel": ""},
    },
    "nonWorkKeywords": ["연차", "휴가", "반차", "병가", "경조", "건강검진", "휴무", "취소됨", "취소된", "취소:", "canceled",
                        "cancelled", "자동 회신", "automatic reply", "auto-reply", "out of office", "부재중", "발송 실패",
                        "undeliverable", "delivery has failed", "read receipt", "읽음 확인"],
    "noticeSenders": ["no-reply", "noreply", "do-not-reply", "알림", "notification", "notice", "뉴스레터", "newsletter",
                      "웹진", "webzine", "공지", "설문", "survey", "시스템", "sharepoint", "yammer", "viva", "helpdesk",
                      "보안공지", "(광고)", "광고", "promotion", "프로모션", "마케팅", "수신거부", "unsubscribe"],
    "signalWeights": {"메일": 1.0, "메일발신": 1.5, "메일CC": 0.25, "회의": 2.0},
    "projects": [],
    "workflowUnit": "과제/담당업무",
    "level1Codenames": {"양산": [], "개발": [], "AX": []},
    "level1Set": [],
    "level1AxKeywords": [],
    "level1CommonKeywords": [],
    "flowBudgetMin": 120,
    "flowMaxChunks": 400,
    "flowUnitsPerChunk": 10,
    "flowFinishRounds": 12,
    "flowFinishMinGain": 2,
    "flowFinishMaxAsk": 3,
    "aiStageBudgetMin": 120,
    "aiTotalBudgetMin": 300,
    "aiStageStallMin": 15,
    "aiStageMaxMin": 0,
    "aiStageNoProgressMin": 45,
    "copilotAuto": {"url": "https://m365.cloud.microsoft/chat", "port": 9573, "stablePolls": 8, "pollSec": 3,
                    "replyTimeoutSec": 480, "roundtripMaxSec": 900, "model": "GPT-5.6", "judgeChunk": 40, "refineChunk": 20,
                    "agenticMaxWork": 60, "chatTurns": 12, "inProcess": True, "requireWorkAccount": True,
                    "keepEdgeOpen": False, "deleteChats": True, "throttleWaitSec": 120, "minGapSec": 15,
                    "runWaitMaxSec": 300},
    "agentic": {"domainHint": "", "ruleRowShare": 0.8},
    "retention": dict(RETENTION_MAX, scheduledPurge=True),
    "team": {"minGroupSize": TEAM_MIN["minGroupSize"], "minCellSize": TEAM_MIN["minCellSize"], "remoteView": False},
    "share": {"allowedNetworks": [], "pingTries": 2, "pingTimeoutSec": 3, "timeoutSec": 45},
    "uiAutoExit": True,
    "keepAwakeDuringRun": True,
}

# 없어진 토글 — 규칙을 약하게 할 수 있던 키. 설정에 남아 있으면 effective 가 빼고 알린다(D22).
REMOVED_WEAKENING = (
    "privacy.externalMail", "privacy.excludeExternalMail", "externalMail", "excludeExternalMail",
    "privacy.dropAdminPlan", "dropAdminPlan", "privacy.excludeSensitivity", "excludeSensitivity",
    "privacy.sensitiveFilter.enabled", "privacy.sensitiveFilter.on", "privacy.sensitiveFilter.off",
    "copilotAuto.sendSenderAddress",   # refs-ok — 남아 있으면 빼고 알린다
)

_MISSING = object()


def _split(key):
    return [k for k in str(key or "").split(".") if k]


def _lookup(d, parts):
    cur = d
    for k in parts:
        if not isinstance(cur, dict) or k not in cur:
            return _MISSING
        cur = cur[k]
    return cur


def _as_int(v):
    """정수로 읽을 수 있으면 int, 아니면 None(bool 은 숫자로 보지 않는다)."""
    if isinstance(v, bool) or v is None:
        return None
    try:
        f = float(str(v).strip())
    except (TypeError, ValueError):
        return None
    if f != f or f in (float("inf"), float("-inf")):
        return None
    return int(f)


def _as_bool(v, dflt):
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    if s in ("true", "1", "yes", "y", "on"):
        return True
    if s in ("false", "0", "no", "n", "off", ""):
        return False
    return dflt


as_bool = _as_bool     # 공개 이름 — 설정의 참/거짓 글자('true'·'1'·'on' …)를 bool 로


def _clamp_max(key, lo, hi, label):
    """정수 lo..hi 로 자르는 함수 — (값, 경고|None)."""
    def f(v):
        n = _as_int(v)
        if n is None:
            return hi, f"{key} 값({v!r})을 숫자로 읽지 못해 {hi}{label}로 둡니다"
        if n > hi:
            return hi, f"{key} {n} → {hi}: {hi}{label}보다 길게 둘 수 없습니다"
        if n < lo:
            return lo, f"{key} {n} → {lo}: {lo}{label}보다 짧게 둘 수 없습니다"
        return n, None
    return f


def _clamp_min(key, lo, label):
    def f(v):
        n = _as_int(v)
        if n is None:
            return lo, f"{key} 값({v!r})을 숫자로 읽지 못해 {lo}{label}으로 둡니다"
        if n < lo:
            return lo, f"{key} {n} → {lo}: {lo}{label}보다 작게 둘 수 없습니다"
        return n, None
    return f


def _clamp_true(key):
    def f(v):
        if v is True:
            return True, None
        return True, f"{key} 는 늘 true 입니다 — 회사 계정이 아닌 Copilot 에는 보내지 않습니다"
    return f


def _str_list(v):
    """설정 목록 값 → 문자열 목록(앞뒤 공백 제거·빈 값 제외). 문자열 하나면 [그것], 목록이 아니면 None(형식 오류)."""
    if v is None:
        return []
    if isinstance(v, str):
        return [v.strip()] if v.strip() else []
    if not isinstance(v, (list, tuple)):
        return None
    return [str(x).strip() for x in v if x is not None and str(x).strip()]


# 기본 목록 위에 더하기만 하는 설정(D3 · D22) — 설정이 기본 항목을 빼도 기본 항목은 늘 함께 쓴다
ADD_ONLY_LISTS = ("privacy.excludeCategories", "privacy.excludeMailFolders", "privacy.excludeKeywords")


def _clamp_add_only(key):
    def f(v):
        base = _lookup(DEFAULTS, _split(key))
        base = list(base) if isinstance(base, list) else []
        got = _str_list(v)
        warn = None
        if got is None:
            got = []
            warn = f"{key} 는 목록이어야 합니다 — 기본 목록만 씁니다"
        out, seen = [], set()
        for x in base + got:
            k = x.lower()
            if k not in seen:
                seen.add(k)
                out.append(x)
        have = {x.lower() for x in got}
        missing = [x for x in base if x.lower() not in have]
        if warn is None and v is not None and missing:
            warn = (f"{key} 에서 기본 항목({'·'.join(missing)})은 뺄 수 없습니다 — 설정에 없어도 늘 함께 뺍니다"
                    "(설정은 더하기만 합니다)")
        return out, warn
    return f


# privacy.allowPatterns 를 시험하는 합성 견본 — 개인 식별번호·연락처 형태(실제 사람의 값이 아니다). 여기에 맞는 넓은 식은
# 받지 않는다: 허용 패턴이 주민·외국인등록·카드·전화·메일 주소·계좌 판정을 약하게 만들 수 없다(D22 · D6 — 늘 켜진 규칙).
ALLOW_PROBES = (
    "900101-1234568", "9001011234568", "900101-5234567", "850615-2345678",
    "4111-1111-1111-1111", "4111111111111111", "4111 1111 1111 1111", "3782-822463-10005", "378282246310005",
    "4111.1111.1111.1111", "4111/1111/1111/1111",
    "010-2345-6789", "01023456789", "010 2345 6789", "02-123-4567", "031-987-6543", "+82-10-2345-6789",
    "+82-2-1234-5678",
    "kim.ext@partner.example", "a@b.co",
    "110-123-456789", "1002-345-678901", "123-456789-01-234", "12345678901234",
)
# 이름·보통 낱말 견본(합성) — 여기에 맞는 식은 고객사·과제·사람 이름까지 지키게 되므로 받지 않는다(허용 패턴은 공학 코드 표기만)
ALLOW_NAME_PROBES = ("홍길동", "한빛정밀", "스카이라인", "김철수 책임", "Smith", "Kevin", "Hanbit")
ALLOW_MAX_LEN = 200

# privacy.sensitiveFilter.allowWords(민감 낱말 규칙의 예외)가 받는 표현 — 이 공학·업무 문맥 낱말이 하나는 들어 있어야 한다
# (core\privacy.SENSITIVE_ALLOW 의 '안전보건·수술용 로봇·장애인 고용' 처럼). '입원으로'·'노조 회의'·'징역형' 처럼 문맥 없는 표현은
# 받지 않는다(D5 · D22 — 설정은 늘 켜진 규칙을 끄지 못한다).
ALLOW_WORD_CONTEXT = re.compile(
    r"(?i)(?:시스템|설계|개발|시험|장비|장치|기기|로봇|소프트웨어|프로그램|모듈|회로|센서|부품|제품|공정|검사|측정|계측|교육|예방"
    r"|안전|품질|인증|규격|표준|데이터|모델|해석|시뮬레이션|알고리즘|신호|배터리|전지|모터|펌웨어|코드|플랫폼|서버|기능|사양|소재"
    r"|재료|용품|용도|설비|라인|도면|특허|(?<![a-z])(?:system|design|device|robot|software|module|sensor|test|equipment|product"
    r"|process|training|safety|quality|data|model|simulation|algorithm|battery|motor|firmware|platform|server|feature|spec)"
    r"(?![a-z]))")


def allow_word_problem(w):
    """privacy.sensitiveFilter.allowWords 의 표현 하나 → 받지 않는 까닭(한국어) 또는 None(써도 된다)."""
    s = "" if w is None else str(w).strip()
    if len(s) < 2:
        return "2자보다 짧아"
    if not ALLOW_WORD_CONTEXT.search(s):
        return "공학·업무 문맥 낱말(시스템·설계·장비·교육 …)이 없는 표현이라"
    return None


def allow_pattern_problem(p):
    """privacy.allowPatterns 의 식 하나 → 받지 않는 까닭(한국어) 또는 None(써도 된다).
    정규식이 아니거나 · 빈 글에도 맞거나 · 개인 식별번호·연락처 견본(ALLOW_PROBES)의 어느 부분에라도 맞으면 받지 않는다."""
    if isinstance(p, re.Pattern):
        rx = p
    else:
        s = "" if p is None else str(p)
        if not s.strip():
            return "빈 식이라"
        if len(s) > ALLOW_MAX_LEN:
            return f"{ALLOW_MAX_LEN}자보다 긴 식이라"
        try:
            rx = re.compile(s)
        except (re.error, OverflowError, RecursionError):
            return "정규식 형식이 틀려"
    try:
        if rx.match("") is not None:
            return "빈 글에도 맞는 식이라"
        for sample in ALLOW_PROBES:
            m = rx.search(sample)
            if m is not None and m.group(0):
                return "주민·카드·전화·메일 주소·계좌 같은 개인 번호 형태에도 맞는 넓은 식이라"
        for sample in ALLOW_NAME_PROBES:
            m = rx.search(sample)
            if m is not None and m.group(0):
                return "고객사·과제·사람 이름 같은 보통 낱말에도 맞는 넓은 식이라"
    except (re.error, TypeError, ValueError, RecursionError):
        return "정규식을 시험하지 못해"
    return None


def _clamp_allow(key):
    def f(v):
        got = v if isinstance(v, (list, tuple)) else ([v] if isinstance(v, str) and v.strip() else [])
        if v is not None and not isinstance(v, (list, tuple, str)):
            return [], f"{key} 는 정규식 목록이어야 합니다 — 비워 둡니다"
        out, bad = [], []
        for x in got:
            why = allow_pattern_problem(x)
            if why:
                bad.append(f"'{str(x)[:60]}'({why})")
            elif str(x) not in out:
                out.append(str(x))
        warn = (f"{key} 의 {', '.join(bad)} 받지 않습니다 — 허용 패턴은 공학 코드 표기에만 씁니다. 주민·카드·전화·메일 주소·"
                "계좌 형태와 고객사·과제·사람 이름은 설정과 상관없이 늘 가립니다" if bad else None)
        return out, warn
    return f


CLAMPS = {"period.maxDays": _clamp_max("period.maxDays", 1, PERIOD_MAX_DAYS, "일")}
for _k, _v in RETENTION_MAX.items():
    CLAMPS["retention." + _k] = _clamp_max("retention." + _k, 1, _v, "일")
for _k, _v in TEAM_MIN.items():
    CLAMPS["team." + _k] = _clamp_min("team." + _k, _v, "명")
CLAMPS["copilotAuto.requireWorkAccount"] = _clamp_true("copilotAuto.requireWorkAccount")
for _k in ADD_ONLY_LISTS:
    CLAMPS[_k] = _clamp_add_only(_k)
CLAMPS["privacy.allowPatterns"] = _clamp_allow("privacy.allowPatterns")
CLAMPED_KEYS = tuple(CLAMPS)


def get(cfg, key, default=None):
    """설정값 하나 — cfg 의 'a.b.c' 경로 값(None 이 아니면), 없으면 DEFAULTS 의 값(복사본), 그것도 없으면 default.
    CLAMPED_KEYS 는 D22 하한을 적용한 값이다(경고는 effective 가 모은다)."""
    parts = _split(key)
    v = _lookup(cfg if isinstance(cfg, dict) else {}, parts)
    if v is _MISSING or v is None:
        v = _lookup(DEFAULTS, parts)
        if v is _MISSING:
            return default
        v = copy.deepcopy(v)
    fn = CLAMPS.get(".".join(parts))
    if fn is not None:
        v, _w = fn(v)
    return v


def _merge(base, over):
    """DEFAULTS(base) 위에 설정(over)을 깊게 겹친다 — dict 는 키별로, 그 밖(목록·값)은 설정이 이긴다. 새 객체."""
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _pop(d, parts):
    cur = d
    for k in parts[:-1]:
        if not isinstance(cur, dict) or k not in cur:
            return _MISSING
        cur = cur[k]
    if isinstance(cur, dict) and parts[-1] in cur:
        return cur.pop(parts[-1])
    return _MISSING


def _set(d, parts, v):
    cur = d
    for k in parts[:-1]:
        if not isinstance(cur.get(k), dict):
            cur[k] = {}
        cur = cur[k]
    cur[parts[-1]] = v


_DOM_RX = re.compile(r"[a-z0-9\-]+(?:\.[a-z0-9\-]+)+")


def _norm_domains(vals, warns, key):
    out = []
    lst = vals if isinstance(vals, list) else ([vals] if isinstance(vals, str) and vals.strip() else [])
    if not isinstance(vals, (list, str)) and vals is not None:
        warns.append(f"{key} 는 목록이어야 합니다 — 비워 둡니다")
    for x in lst:
        s = str(x or "").strip().lower().lstrip("@").rstrip(".")
        if not s:
            continue
        if _DOM_RX.fullmatch(s):
            if s not in out:
                out.append(s)
        else:
            warns.append(f"{key} 의 '{x}' 는 메일 도메인 형식이 아니라 뺍니다")
    return out


_CTRL_RX = re.compile(r"[\x00-\x1f\x7f-\x9f  ]")


def _norm_contact(v, warns):
    """privacy.contact → {"name", "channel"}(운영 담당이 채우는 문의·이의 창구 — 안내문의 권리 항목에 그대로 싣는다).
    글자만 받고(제어 문자 제거·앞뒤 공백 정리·길이 상한 CONTACT_MAX), 형식이 틀리면 빈 값과 경고."""
    out = {"name": "", "channel": ""}
    if v is None:
        return out
    if not isinstance(v, dict):
        warns.append("privacy.contact 는 {name, channel} 형식이어야 합니다 — 비워 둡니다")
        return out
    for k, n in CONTACT_MAX.items():
        x = v.get(k)
        if x is None:
            continue
        if not isinstance(x, str):
            warns.append(f"privacy.contact.{k} 는 글이어야 합니다 — 비워 둡니다")
            continue
        s = " ".join(_CTRL_RX.sub(" ", x).split())
        if len(s) > n:
            warns.append(f"privacy.contact.{k} 는 {n}자까지만 씁니다")
            s = s[:n].rstrip()
        out[k] = s
    return out


def _network_problem(net):
    """share.allowedNetworks 의 망 하나 → 받지 않는 까닭(한국어) 또는 None. 모든 주소를 여는 넓은 대역(IPv4 /8 미만 · IPv6 /32
    미만), 멀티캐스트·링크 로컬·예약·지정되지 않은 대역은 회사 망으로 볼 수 없다."""
    if net.prefixlen < (8 if net.version == 4 else 32):
        return f"너무 넓은 대역(/{net.prefixlen})이라"
    if net.network_address.is_unspecified:
        return "지정되지 않은 대역이라"
    if net.is_multicast:
        return "멀티캐스트 대역이라"
    if net.is_link_local:
        return "링크 로컬 대역이라"
    if net.is_reserved:
        return "예약 대역이라"
    return None


def effective(cfg):
    """설정 → (실효 설정, 경고 목록). 실효 설정 = DEFAULTS ⊕ cfg(깊은 겹침) + D22 하한 + 없어진 약화 토글 제거 +
    형식 정리(collect.channels ⊂ com·owa·copilot, privacy.internalDomains 소문자 도메인, share.allowedNetworks CIDR,
    calendar.collectBody·bodyToAI·retention.scheduledPurge·team.remoteView 는 bool). 원본 cfg 는 바꾸지 않는다."""
    src = cfg if isinstance(cfg, dict) else {}
    warns = []
    out = _merge(DEFAULTS, src)
    for key in REMOVED_WEAKENING:
        if _pop(out, _split(key)) is not _MISSING:
            warns.append(f"{key} 설정은 없어졌습니다 — 무시합니다(이 규칙은 늘 켜져 있습니다)")
    for key, fn in CLAMPS.items():
        parts = _split(key)
        v = _lookup(out, parts)
        if v is _MISSING or v is None:
            v = _lookup(DEFAULTS, parts)
        v2, w = fn(v)
        _set(out, parts, v2)
        if w:
            warns.append(w)
    # 수집 경로 — 허용 목록 안에서만
    ch = _lookup(out, ["collect", "channels"])
    if not isinstance(ch, list):
        warns.append("collect.channels 는 목록이어야 합니다 — 기본값(com·owa·copilot)을 씁니다")
        ch = list(CHANNELS)
    good = []
    for c in ch:
        s = str(c or "").strip().lower()
        if s in CHANNELS:
            if s not in good:
                good.append(s)
        else:
            warns.append(f"collect.channels 의 '{c}' 는 쓸 수 없는 수집 경로라 뺍니다(com·owa·copilot 만)")
    if not good:
        warns.append("collect.channels 가 비어 있어 아무것도 모으지 않습니다")
    out["collect"]["channels"] = good
    # 사내 도메인 — 공용 개인 메일 도메인(gmail·naver …)은 사내가 될 수 없다(D7)
    pv = out.get("privacy") if isinstance(out.get("privacy"), dict) else {}
    doms = _norm_domains(pv.get("internalDomains"), warns, "privacy.internalDomains")
    personal = [d for d in doms if d in PERSONAL_MAIL_DOMAINS]
    if personal:
        warns.append(f"privacy.internalDomains 의 {'·'.join(personal)} 는 공용 개인 메일 도메인이라 사내 도메인으로 쓰지 않습니다")
    pv["internalDomains"] = [d for d in doms if d not in PERSONAL_MAIL_DOMAINS]
    sf = pv.get("sensitiveFilter")
    if not isinstance(sf, dict):
        warns.append("privacy.sensitiveFilter 는 {extraWords, allowWords} 형식이어야 합니다 — 기본값을 씁니다")
        sf = copy.deepcopy(DEFAULTS["privacy"]["sensitiveFilter"])
    for k in ("extraWords", "allowWords"):
        v = sf.get(k)
        if v is None:
            sf[k] = []
        elif isinstance(v, str):
            sf[k] = [v] if v.strip() else []
        elif not isinstance(v, list):
            warns.append(f"privacy.sensitiveFilter.{k} 는 목록이어야 합니다 — 비워 둡니다")
            sf[k] = []
    bad = [f"'{str(w)[:40]}'" for w in sf["allowWords"] if allow_word_problem(w)]
    if bad:
        warns.append(f"privacy.sensitiveFilter.allowWords 의 {', '.join(bad)} 는 받지 않습니다 — 공학·업무 문맥 낱말(시스템·설계·"
                     "장비·교육 …)이 든 표현만 예외로 적을 수 있습니다(건강·노조·정치·종교·성생활·범죄 경력 규칙은 늘 켜져 있습니다)")
    sf["allowWords"] = [w for w in sf["allowWords"] if not allow_word_problem(w)]
    pv["sensitiveFilter"] = sf
    pv["contact"] = _norm_contact(pv.get("contact"), warns)
    out["privacy"] = pv
    # 공유 허용 망 — 모든 주소를 여는 넓은 대역·멀티캐스트·링크 로컬·지정되지 않은 대역은 뺀다(L5-04). 사설망 밖의 대역은 받되 알린다:
    # 공인 대역은 '공인 IP 대역', 100.64.0.0/10(통신사·사내망이 함께 쓰는 공유 주소 대역 — 사설망도 공인 대역도 아니다)은 그 이름으로
    sh = out.get("share") if isinstance(out.get("share"), dict) else {}
    nets = sh.get("allowedNetworks")
    nets = nets if isinstance(nets, list) else ([] if nets in (None, "") else [nets])
    ok_nets = []
    for n in nets:
        try:
            net = ipaddress.ip_network(str(n).strip(), strict=False)
        except ValueError:
            warns.append(f"share.allowedNetworks 의 '{n}' 는 망 주소(예 10.20.0.0/16) 형식이 아니라 뺍니다")
            continue
        why = _network_problem(net)
        if why:
            warns.append(f"share.allowedNetworks 의 '{net}' 는 {why} 뺍니다")
            continue
        if not net.is_private:
            kind = "공인 IP 대역" if net.is_global else "사설망(10.x · 172.16~31.x · 192.168.x) 밖의 공유 주소 대역"
            warns.append(f"share.allowedNetworks 의 '{net}' 는 {kind}입니다 — 회사 안 망인지 운영 담당이 확인하세요")
        if str(net) not in ok_nets:
            ok_nets.append(str(net))
    sh["allowedNetworks"] = ok_nets
    out["share"] = sh
    # bool 정리
    for key in ("calendar.collectBody", "calendar.bodyToAI", "retention.scheduledPurge", "team.remoteView"):
        parts = _split(key)
        v = _lookup(out, parts)
        dv = _lookup(DEFAULTS, parts)
        b = _as_bool(v, dv)
        if not isinstance(v, bool):
            warns.append(f"{key} 값({v!r})을 {str(b).lower()} 로 읽습니다")
        _set(out, parts, b)
    return out, warns


def load(root=None):
    r"""<root>\config\config.json(utf-8-sig) → dict. 없으면 config.default.json, 둘 다 없거나 깨졌으면 {}."""
    base = os.path.join(str(root or ROOT), "config")
    for name in ("config.json", "config.default.json"):
        p = os.path.join(base, name)
        if not os.path.exists(p):
            continue
        try:
            with open(p, encoding="utf-8-sig") as f:
                d = json.load(f)
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}
    return {}


def load_effective(root=None):
    """effective(load(root)) → (실효 설정, 경고 목록)."""
    return effective(load(root))
