# -*- coding: utf-8 -*-
r"""
extract.py — 정제된 메일·일정(data\outlook\mail.csv · calendar.csv)에서 업무 신호를 뽑아 업무 분류 행으로 만든다.
AgentFinder32 의 분석 첫 단계(mine.py)가 쓴다. 목적은 Agentic AI 로 바꿀 만한 업무를 찾는 것 하나다.

읽는 것(§5.1 · §5.2 — 수집 직후 G1 을 거친 파일만)
  mail.csv      box,time,sender,subject,conversation,rcv,time_precision,src,notice
  calendar.csv  start,end,all_day,busy_status,subject,categories,location,response,meeting_status,src[,body]
  이 밖의 파일(파일·폴더 흔적·Teams·작업창·PC 기록 등)은 읽지 않는다. _data_roots 는 늘 [data_dir] 하나다.

신호 = (날짜, 출처 라벨, 정제한 글, 가중치, who)
  · 날짜만 남긴다(그날 00:00 — 시각은 이 모듈 안의 중복 판정에만 쓰고 밖으로 내보내지 않는다).
  · who = 받은 메일의 보낸이 가명 'p:<12hex>' · 내가 보낸 메일 '나' · 회의는 "".
  · 가중치 = 관여의 세기(시간이 아니다) — signalWeights {메일, 메일발신, 메일CC, 회의}. 회의는 길이와 상관없이 회의 상수.
    5통 넘게 받기만 하고 한 번도 회신하지 않은 보낸이의 메일은 알림성이라 약하게(×0.2 · 참조 ×0.4) 센다.
  · 공지·광고 발신(notice=1)·단체발송(rcv=bulk)·행정 공지 제목은 업무 근거로 쓰지 않는다(bulk 로 센다).

분석 때 다시 거르는 것(G2 — 수집 때 거른 것과 같은 규칙을 한 번 더, 건수만 남긴다)
  restricted 제한 고객 · private 개인 주제어 · admin 근태·행방(종일·취소·거절 일정 포함) · nonwork 비업무 일정·자동 회신 ·
  sensitive 민감 주제 · credential 자격증명 · identifier 식별번호 · private_text 사적 대화 · duplicate 같은 항목의 사본 ·
  bulk 공지·단체발송.

공개 함수(다른 모듈이 쓴다 — spec §6.0)
  load_cfg · norm_cfg · cfg_list · load_signals · build_items2 · to_rows · _one_line · _read · _tokens · content_words ·
  talk_name · _meeting_skip · rule_name_ok
"""
import csv
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
import afcfg  # noqa: E402
import privacy  # noqa: E402

ROOT = os.path.dirname(_HERE)

# ── 신호 출처 라벨 · 가중치 ────────────────────────────────────────────────────────────────────
MAIL_SENT = "메일(발신)"
MAIL_IN = "메일(수신)"
MAIL_CC = "메일(CC)"
MAIL_ONEWAY = "메일(수신전용)"          # 받기만 하고 회신한 적 없는 보낸이(알림성) — 약하게
MEETING = "회의"
SIGNAL_WEIGHT_KEYS = ("메일", "메일발신", "메일CC", "회의")
DEFAULT_WEIGHTS = {k: float(afcfg.DEFAULTS["signalWeights"][k]) for k in SIGNAL_WEIGHT_KEYS}
ONEWAY_MIN = 5                         # 이만큼 받았는데 회신한 대화가 없으면 알림성
ONEWAY_IN, ONEWAY_CC = 0.2, 0.4
TENTATIVE_CHOICES = ("count", "skip", "response")

# 제외 건수의 칸(run_meta.excluded) — 수집(collect_summary §5.3)과 같은 칸 + 분석 때만 생기는 칸
COLLECT_EXCLUDED_KEYS = tuple(privacy.EXCLUDE_KEYS)
ANALYSIS_EXCLUDED_KEYS = ("nonwork", "bulk", "private_text", "credential", "duplicate")
EXCLUDED_KEYS = COLLECT_EXCLUDED_KEYS + ANALYSIS_EXCLUDED_KEYS


def signal_class(label):
    """출처 라벨 → run_meta.counted 칸(mail_out · mail_in · meetings)."""
    s = str(label or "")
    if s.startswith("메일(발신"):
        return "mail_out"
    if s.startswith("메일"):
        return "mail_in"
    return "meetings"


def _level1_of(text, l2=""):
    """규칙 상위 분류(core/details.level1_of) — 임포트 실패해도 추출은 계속(빈칸)."""
    try:
        from details import level1_of
        return level1_of(text, l2, ROOT)
    except Exception:  # noqa: BLE001
        return ""


def _level1_fill(l2, l3="", l1_map=None, pin=None):
    """상위 채움(core/details.level1_fill — 지정 상위 > taxonomy l1 > 규칙 > 과제명이 곧 범주('공통')).
    임포트 실패하면 규칙 상위(_level1_of)로 계속."""
    try:
        from details import level1_fill
    except ImportError:
        return _level1_of(f"{l2} {l3}", l2)
    try:
        return level1_fill(l2, l3, l1_map, pin, ROOT)
    except Exception:  # noqa: BLE001
        return ""


def _is_notice_subject(text):
    """강한 행정 공지 제목인가(core/details.is_notice_subject — 인사발령·부고·뉴스레터 …). 임포트 실패면 거르지 않는다."""
    try:
        from details import is_notice_subject
    except ImportError:
        return False
    return is_notice_subject(text)


# 활동(Level 3) 규칙 — 신호 글에서 '무슨 활동인가'를 뽑는다(메일 제목·회의 제목의 낱말)
ACT_RULES = [
    ("설계", ["설계", "도면", "회로", "구조", "레이아웃", "schematic", "layout", "cad",
             ".dwg", ".sldprt", ".catpart", "design"]),
    ("해석·시뮬레이션", ["해석", "시뮬", "simul", "ansys", "zemax", "codev", "matlab",
                    "fem", "cfd", ".aedt", ".zmx", ".slx"]),
    ("SW개발", ["코드", "커밋", "commit", "구현", "디버그", "debug", ".py", ".c", ".cpp",
              ".cs", ".ipynb", "algorithm", "펌웨어", "firmware", "리팩터", "빌드에러"]),
    ("검증·평가", ["검증", "평가", "측정", "시험", "test", "v&v", "dv", "pv", "신뢰성",
                "계측", "실험"]),
    ("입고검사·현장", ["입고", "검사", "조립", "현장", "설비", "장비", "빌드", "샘플"]),
    ("자재·발주", ["자재", "발주", "구매", "ers", "bom", "부품", "조달", "견적"]),
    ("불량·대응", ["불량", "고장", "이슈", "fa ", "faca", "8d", "대책", "클레임", "ncr"]),
    ("회의·협업", ["회의", "미팅", "meeting", "리뷰", "review", "협의", "보고회"]),
    ("문서·보고", ["보고", "자료", "발표", "ppt", ".pptx", ".docx", "문서", "정리", "요약"]),
]
# 활동 → 업무유형(개발·사무·현장·협업 — judge 의 유형 4종과 같다). 규칙 결과의 초안이고 AI 판정이 덮어쓴다.
WORKTYPE_OF_ACT = {"설계": "개발", "해석·시뮬레이션": "개발", "SW개발": "개발", "검증·평가": "개발",
                   "입고검사·현장": "현장", "불량·대응": "현장", "자재·발주": "사무", "문서·보고": "사무",
                   "회의·협업": "협업"}
STOP = {"검토", "요청", "회신", "공유", "확인", "전달", "관련", "안내", "파일", "문서", "최종",
        "수정", "신규", "완료", "송부", "부탁", "주간", "월간", "일정", "메일", "첨부", "내용",
        "re", "fw", "fwd", "pptx", "xlsx", "docx", "pdf", "hwp", "microsoft", "teams",
        "outlook", "excel", "word", "powerpoint", "chrome", "edge", "explorer", "claude"}


def _one_line(s, n=120):
    """개행·탭·연속 공백을 한 칸으로, 앞뒤 공백 제거. 제목에서 온 세부업무 이름에 개행이 남으면 프롬프트의 한 줄이
    갈라지고 CSV 셀이 쪼개진다 — 쓰는 쪽(원천)에서 한 번 정규화한다. n=None 이면 자르지 않는다."""
    return " ".join(str(s or "").split())[:n]


# ── 비업무 일정·자동 메일 ──────────────────────────────────────────────────────────────────────
# 비업무 기본 키워드 — 소문자로 비교한다. config.nonWorkKeywords 는 더하기만 한다(_nonwork_list).
NONWORK_DEFAULT = ["집중 시간", "focus time", "미리 알림", "reminder", "할 일",
                   "연차", "휴가", "반차", "반휴", "월차", "공가", "휴직", "병가", "경조", "건강검진", "휴무",
                   "취소됨", "취소된", "canceled", "cancelled", "취소:",
                   "자동 회신", "automatic reply", "auto-reply", "out of office",
                   "부재중", "발송 실패", "undeliverable", "delivery has failed",
                   "read receipt", "읽음 확인"]
# 판정 규칙 — '어디서든 부분일치'는 'Reminder: 제출 마감'·'취소된 발주 재검토' 같은 업무 제목을 지운다.
#   접두(콜론) : Outlook 이 붙이는 '취소됨: '·'Canceled: '·'자동 회신: ' 류 — 제목 시작에 '키워드:' 일 때만
#   정확 일치  : Viva·Outlook 자동 항목('집중 시간'·'미리 알림'·'reminder'·'할 일') — 제목 전체가 그것일 때만
#   근태어     : 토큰 접미 일치('연차'·'여름휴가' ○ / '연차 사용 현황'·'휴가철' ×)
#   시스템 문구 : 자동회신·발송실패·읽음확인 — 어디에 있어도
#   그 밖의 config 추가어는 부분일치(사용자가 넣은 말은 사용자의 뜻대로)
NONWORK_PREFIX = {"취소됨", "취소된", "취소", "canceled", "cancelled", "자동 회신", "automatic reply", "auto-reply",
                  "undeliverable", "발송 실패"}
NONWORK_EXACT = {"미리 알림", "reminder", "할 일", "집중 시간", "focus time"}
NONWORK_TOKEN = {"연차", "휴가", "반차", "반휴", "병가", "경조", "경조사", "건강검진", "휴무", "휴직", "월차", "공가"}
_RE_PREFIX = re.compile(r"^\s*((re|fw|fwd|답장|전달|회신)\s*[:：]\s*)+", re.I)
_TOK_SPLIT = re.compile(r"[\s_\-·/()\[\],:：]+")
_TOK_STRIP = re.compile(r"(입니다|사용|신청|중|임|함)$")


def _token_suffix_hit(s, kws, limit=8):
    """토큰이 키워드로 **끝나면** 인정 — '여름휴가'·'오후반차' ○, '휴무일'·'휴가철' ×. 숫자만 앞에 붙은 토큰('2연차')은 아니다."""
    for t in _TOK_SPLIT.split(str(s or "").strip().lower())[:limit]:
        t = _TOK_STRIP.sub("", t.strip())
        if not t:
            continue
        for k in kws:
            if t == k or (t.endswith(k) and not t[:-len(k)].isdigit()):
                return True
    return False


def _nonwork_list(cfg):
    """기본 목록 + config.nonWorkKeywords 의 합집합(소문자, 순서 유지)."""
    seen, out = set(), []
    for n in list(NONWORK_DEFAULT) + list(cfg_list(cfg, "nonWorkKeywords")):
        s = str(n).strip().lower()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _nonwork_hit(low, nonwork):
    """비업무 판정 — 걸린 키워드 또는 None(위 규칙)."""
    s = _RE_PREFIX.sub("", str(low or "").strip().lower())
    if not s:
        return None
    for k in nonwork:
        if k.rstrip(":") in NONWORK_PREFIX or k.endswith(":"):
            if re.match(re.escape(k.rstrip(":")) + r"\s*[:：]", s):
                return k
        elif k in NONWORK_EXACT:
            if s == k or (k in ("집중 시간", "focus time") and s.startswith(k)):
                return k
        elif k in NONWORK_TOKEN:
            if _token_suffix_hit(s, (k,)):
                return k
        elif k in s:
            return k
    return None


def _truthy(v):
    return str(v or "").strip().lower() in ("true", "-1", "1", "yes", "y")


# ── 설정 ──────────────────────────────────────────────────────────────────────────────────
def load_cfg():
    r"""config\config.json 을 읽는다(없으면 config\config.default.json). 메모장 저장은 BOM 이 붙으므로 utf-8-sig.
    깨졌으면 경고 한 줄을 찍고 {} — 기본값(core\afcfg.DEFAULTS)으로 진행한다."""
    for name in ("config.json", "config.default.json"):
        p = os.path.join(ROOT, "config", name)
        if not os.path.exists(p):
            continue
        try:
            with open(p, encoding="utf-8-sig") as f:
                cfg = json.load(f)
        except (ValueError, OSError) as e:
            print(f"[!] config\\{name} 을 읽지 못했습니다 ({type(e).__name__}) — 기본값으로 진행합니다. "
                  "JSON 문법(쉼표·따옴표)을 확인하세요.")
            return {}
        if not isinstance(cfg, dict):
            print(f"[!] config\\{name} 의 최상위가 객체({{…}})가 아닙니다 — 기본값으로 진행합니다.")
            return {}
        return cfg
    return {}


def _num(v, dflt, lo=None, hi=None, key="", warns=None):
    """config 숫자 값 → float. 없음·빈 값은 기본값(경고 없음). bool·글자·NaN·범위 밖은 기본값 + 경고."""
    if v is None or (isinstance(v, str) and not v.strip()):
        return dflt
    x = None
    if not isinstance(v, bool):
        try:
            x = float(v)
        except (TypeError, ValueError):
            x = None
        if x is not None and (x != x or x in (float("inf"), float("-inf"))):
            x = None
    if x is not None and (lo is None or x >= lo) and (hi is None or x <= hi):
        return x
    if warns is not None:
        rng = "" if lo is None and hi is None else (
            f"(허용 {'' if lo is None else format(lo, 'g')}~{'' if hi is None else format(hi, 'g')})")
        warns.append(f"{key}={v!r} 는 쓸 수 없는 값{rng} — 기본값 {dflt} 적용")
    return dflt


def _choice(v, dflt, allowed, key="", warns=None):
    if v is None or (isinstance(v, str) and not v.strip()):
        return dflt
    s = str(v).strip().lower()
    if s in allowed:
        return s
    if warns is not None:
        warns.append(f"{key}={v!r} 는 {'/'.join(allowed)} 중 하나가 아님 — 기본값 '{dflt}' 적용")
    return dflt


def cfg_list(cfg, key, warns=None):
    """config 의 목록 키 → list. 글자 하나면 [그것], 그 밖의 형식은 [] + 경고
    (글자를 그대로 순회하면 한 글자 키워드가 돼 신호 대부분을 지운다)."""
    v = (cfg or {}).get(key) if isinstance(cfg, dict) else None
    if v is None:
        return []
    if isinstance(v, str):
        return [v] if v.strip() else []
    if isinstance(v, (list, tuple)):
        return list(v)
    if warns is not None:
        warns.append(f"{key} 는 목록([…])이어야 함({type(v).__name__}) — 무시")
    return []


def norm_cfg(cfg):
    """분석에 쓰는 설정을 검증해 (값 dict, 경고 list) — 잘못된 값은 죽지 않고 기본값 + 경고(run_meta.config_warnings).
    값: tentativeMeetings(calendar.tentativeMeetings — count·skip·response) · mailTimeOffsetH(collect.mailTimeOffsetH,
    −24~24 — 웹 경로가 UTC 로 남긴 시각 보정) · signalWeights({메일, 메일발신, 메일CC, 회의} — 0 이상, 다른 키는 무시)."""
    warns = []
    cfg = cfg if isinstance(cfg, dict) else {}
    cal = cfg.get("calendar") if isinstance(cfg.get("calendar"), dict) else {}
    col = cfg.get("collect") if isinstance(cfg.get("collect"), dict) else {}
    n = {"tentativeMeetings": _choice(cal.get("tentativeMeetings"), "count", TENTATIVE_CHOICES,
                                      "calendar.tentativeMeetings", warns),
         "mailTimeOffsetH": _num(col.get("mailTimeOffsetH"), 0.0, -24, 24, "collect.mailTimeOffsetH", warns)}
    weights = dict(DEFAULT_WEIGHTS)
    sw = cfg.get("signalWeights")
    if isinstance(sw, dict):
        for k, v in sw.items():
            k = str(k)
            if k.startswith("_"):
                continue                               # '_설명' 류
            if k not in SIGNAL_WEIGHT_KEYS:
                warns.append(f"signalWeights[{k}] 는 쓰지 않는 가중치라 무시합니다(메일·메일발신·메일CC·회의만)")
                continue
            x = _num(v, None, 0, None)
            if x is None:
                warns.append(f"signalWeights[{k}]={v!r} 는 0 이상의 숫자가 아님 — 기본 가중치 {DEFAULT_WEIGHTS[k]:g}")
            else:
                weights[k] = x
    elif sw is not None:
        warns.append(f"signalWeights 는 객체({{…}})여야 함({type(sw).__name__}) — 기본 가중치")
    n["signalWeights"] = weights
    for k in ("nonWorkKeywords", "noticeSenders", "projects"):
        cfg_list(cfg, k, warns)
    return n, warns


# ── CSV 읽기 ──────────────────────────────────────────────────────────────────────────────
def _data_roots(data_dir):
    r"""읽을 수집 폴더 — 늘 [data_dir] 하나(다른 PC 의 자료를 합치지 않는다)."""
    return [data_dir]


def _read_multi(data_dir, *rel):
    """_data_roots 의 같은 상대경로 CSV 를 읽는다."""
    rows = []
    for root in _data_roots(data_dir):
        rows += _read(os.path.join(root, *rel))
    return rows


READ_DROPPED = {}          # {경로: 버린 행 수} — 화면이 "읽지 못한 행 N개" 를 말할 수 있게


def _read(path):
    """CSV → [dict]. 없거나 못 읽으면 []. 열이 남는 행은 버리고(READ_DROPPED 에 센다), 열이 모자란 행은 빈칸으로 채운다."""
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8-sig", errors="replace") as f:
            rows = list(csv.DictReader(f))
    except OSError:
        return []
    except csv.Error:
        READ_DROPPED[path] = READ_DROPPED.get(path, 0) + 1
        return []
    out, dropped = [], 0
    for r in rows:
        if None in r:
            dropped += 1
            continue
        if None in r.values():
            r = {k: ("" if v is None else v) for k, v in r.items()}
        out.append(r)
    if dropped:
        READ_DROPPED[path] = dropped
    return out


def _dt(s, fmts=("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d")):
    """시각 글자 → datetime. 시각부가 있는데 앞 형식이 모두 실패하면 None(날짜만으로 살리지 않는다)."""
    s = (s or "").strip()
    for f in fmts:
        if f == "%Y-%m-%d" and len(s) > 10:
            return None
        try:
            return datetime.strptime(s[:len(f) + 2], f)
        except ValueError:
            continue
    return None


def _as_day(v):
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v)[:10])


def _self_pseudonyms(data_dir, cfg):
    r"""내 주소·이름의 가명 집합 — 내가 나에게 보낸 메일(받은편지함의 사본)을 받은 메일로 두 번 세지 않게.
    소금은 <data_dir>\install.json 이 이미 있을 때만 읽는다(여기서 만들거나 고치지 않는다). 없거나 깨졌으면 빈 집합."""
    try:
        with open(os.path.join(data_dir, "install.json"), encoding="utf-8-sig") as f:
            salt = str((json.load(f) or {}).get("salt") or "")
    except (OSError, ValueError, AttributeError):
        return set()
    if not re.fullmatch(r"[0-9a-f]{64}", salt):
        return set()
    vals = list(privacy.me_list(data_dir)) + [str((cfg or {}).get("owner") or "")]
    return {p for p in (privacy.pseudonym(v, salt) for v in vals if str(v or "").strip()) if p}


def load_signals(data_dir, d0, d1, exclude=(), cfg=None, *, restricted=None):
    r"""수집 폴더(data\) → (signals, meta).
    signals: [(datetime 그날 00:00, 출처 라벨, 정제한 글, 가중치, who)] — 날짜순.
    meta: {"counted": {mail_in, mail_out, meetings}, "excluded": {EXCLUDED_KEYS: 건수}, "weights": {메일·메일발신·메일CC·회의},
           "config_warnings": [...], "unreadable": 시각을 읽지 못한 행 수}
    exclude = 개인 주제어(없으면 privacy.excluded_keywords(cfg)). restricted = privacy.Restricted(없으면 설정의 목록을 읽는다 —
    목록이 없거나 깨졌으면 privacy.RestrictedListError, 분석하지 않는다). 기간 [d0, d1] 밖의 행은 세지도 않는다.
    이름: 신호 글의 '이름 + 호칭'(sanitize)과 이름 해시(남은 모든 분석의 것 — privacy.name_gate)에 든 이름은 [사람] 이다(D8 · G2).
    이 분석(tag = d0~d1)의 이름 해시를 report\name_hashes_<tag>.json 에 남긴다(privacy.snapshot_name_hashes — 결과와 함께 산다)."""
    cfg = cfg if (isinstance(cfg, dict) and cfg) else load_cfg()
    d0, d1 = _as_day(d0), _as_day(d1)
    mc, cfg_warns = norm_cfg(cfg)
    tentative = mc["tentativeMeetings"]
    mail_off = mc["mailTimeOffsetH"]
    W = dict(mc["signalWeights"])
    nonwork = _nonwork_list(cfg)
    words = [str(x) for x in (exclude or privacy.excluded_keywords(cfg)) if str(x).strip()]
    if restricted is None:
        restricted = privacy.load_restricted(cfg, ROOT)
    allow = afcfg.get(cfg, "privacy.allowPatterns") or []
    pctx = privacy.make_ctx(cfg, data_dir)
    root_dir = os.path.dirname(os.path.abspath(data_dir))
    try:
        import period
        privacy.snapshot_name_hashes(root_dir, period.tag_of(d0, d1), cfg=cfg)
    except OSError:
        pass                                # 남기지 못해도 분석은 한다(공유 가림은 data\cache 의 해시로)
    hashes, salt = privacy.name_gate(root_dir, cfg=cfg)
    sig = []
    counted = Counter()
    excl = Counter()
    unreadable = [0]
    dedup = {}                              # 중복 키 → sig 색인(None = 걸러진 항목)
    verdicts = {}                           # 글 → (정제문, 자격증명인가, 뺄 칸|None) — 같은 제목이 수백 번 온다

    def verdict(text):
        """G2 — 원문으로 제한 고객 → 개인 주제어 → 근태·행방 → 비업무 → 민감 주제를 보고, 정제(sanitize) 뒤 자격증명 →
        남은 식별번호 → 사적 대화를 본다. 처음 걸린 칸 하나만 센다(수집 때 G1 의 순서와 같은 앞부분)."""
        v = verdicts.get(text)
        if v is None:
            c, _hits, drop = privacy.sanitize(text, "signal", pctx)
            # D10 — 제목의 시각은 [시각] · R5 — 메일 주소 토큰에 바깥 도메인을 남기지 않는다([이메일]) · D8 — 이름 해시에 든 이름은 [사람]
            clean = privacy.mask_known_names(privacy.minimize_text(_one_line(c, None)), hashes, salt)
            cred = bool(drop)
            if restricted.hit(text):
                why = "restricted"
            elif privacy.keyword_hit(text, words=words):
                why = "private"
            elif privacy.admin_hit(text):
                why = "admin"
            elif _nonwork_hit(text.lower(), nonwork):
                why = "nonwork"
            elif privacy.sensitive_hit(text, cfg):
                why = "sensitive"
            elif cred:
                why = "credential"
            elif privacy.has_identifier(clean, allow_patterns=allow):
                why = "identifier"
            elif privacy.private_score(clean) != "work":
                why = "private_text"
            else:
                why = None
            v = verdicts[text] = (clean, cred, why)
        return v

    def in_period(t):
        return t is not None and d0 <= t.date() <= d1

    def skip(key, t):
        if in_period(t):
            excl[key] += 1

    def pt(s):
        t = _dt(s)
        if t is None and str(s or "").strip():
            unreadable[0] += 1
        return t

    def add(t, lbl, text, w, who="", dkey=None):
        if not in_period(t):
            return
        text = _one_line(text, None)
        if not text:
            return
        clean, cred, why = verdict(text)
        key = dkey or (t, lbl, (text if cred else clean)[:120], who)
        if key in dedup:
            excl["duplicate"] += 1
            i = dedup[key]
            if i is not None and w > sig[i][3]:          # 같은 항목이면 더 센 쪽(라벨 포함)을 남긴다
                sig[i] = (sig[i][0], lbl, sig[i][2], w, sig[i][4])
            return
        dedup[key] = None
        if why:
            excl[why] += 1
        else:
            dedup[key] = len(sig)
            sig.append((datetime(t.year, t.month, t.day), lbl, clean, w, who))
            counted[signal_class(lbl)] += 1

    # ── 메일: 발신 > 직접 수신 > 참조. 공지·광고·단체발송은 업무 근거가 아니다 ───────────────────────────
    def conv_norm(conv, subj=""):
        return _RE_PREFIX.sub("", " ".join(str(conv or subj or "").split()).lower())[:40]

    def sender_of(r):
        s = str(r.get("sender") or "").strip().lower()
        return s if privacy.PSEUDO_RX.fullmatch(s) else ""

    mail_rows = _read_multi(data_dir, "outlook", "mail.csv")
    my_ids = _self_pseudonyms(data_dir, cfg)
    sent_conv = {conv_norm(r.get("conversation")) for r in mail_rows
                 if str(r.get("box") or "").strip().lower() == "sent"} - {""}
    recv_cnt, replied = Counter(), set()
    for r in mail_rows:
        if str(r.get("box") or "").strip().lower() != "sent":
            snd = sender_of(r)
            recv_cnt[snd] += 1
            if snd and conv_norm(r.get("conversation")) in sent_conv:
                replied.add(snd)                       # 이 보낸이와는 주고받은 적이 있다
    # 같은 메일을 정확한 시각과 '날짜만'(웹 경로)으로 두 번 받았으면 날짜만 행은 사본이다
    exact = set()
    for r in mail_rows:
        if str(r.get("time_precision") or "").strip().lower() != "date":
            t0 = _dt(r.get("time"))
            if t0:
                exact.add((t0.date(), str(r.get("box") or "").strip().lower(),
                           conv_norm(r.get("conversation"), r.get("subject"))))
    for r in mail_rows:
        t = pt(r.get("time"))
        if t is None:
            continue
        box = str(r.get("box") or "").strip().lower()
        sent = box == "sent"
        date_only = str(r.get("time_precision") or "").strip().lower() == "date"
        conv = conv_norm(r.get("conversation"), r.get("subject"))
        if date_only and (t.date(), box, conv) in exact:
            skip("duplicate", t)
            continue
        if mail_off:
            t = t + timedelta(hours=mail_off)
        if date_only:
            t = t.replace(hour=12, minute=0, second=0, microsecond=0)
        subj = r.get("subject")
        snd = sender_of(r)
        key = (t.replace(second=0, microsecond=0), "메일", "sent" if sent else "inbox", conv or ("@" + snd))
        if sent:
            add(t, MAIL_SENT, subj, W["메일발신"], "나", dkey=key)
            continue
        if snd and snd in my_ids:                     # 내가 나에게 보낸 메일 — 보낸 메일로 이미 셌다
            skip("duplicate", t)
            continue
        if str(r.get("notice") or "").strip() == "1":   # 공지·시스템·광고 발신(G1 이 정함)
            skip("bulk", t)
            continue
        rcv = str(r.get("rcv") or "to").strip().lower()
        # 웹 경로·받는 사람을 못 읽은 행은 내가 받는 사람·참조에 있었는지 모른다 — 강한 행정 공지 제목은 단체발송으로 본다
        # (내가 회신한 대화는 남긴다)
        if ((str(r.get("src") or "").strip().lower() != "com" or rcv == "unknown")
                and _is_notice_subject(subj) and conv_norm(r.get("conversation")) not in sent_conv):
            skip("bulk", t)
            continue
        if rcv == "bulk":
            skip("bulk", t)
            continue
        oneway = bool(snd) and recv_cnt[snd] >= ONEWAY_MIN and snd not in replied
        if rcv == "cc":
            add(t, MAIL_ONEWAY if oneway else MAIL_CC, subj, W["메일CC"] * (ONEWAY_CC if oneway else 1.0), snd, dkey=key)
        else:
            add(t, MAIL_ONEWAY if oneway else MAIL_IN, subj, W["메일"] * (ONEWAY_IN if oneway else 1.0), snd, dkey=key)

    # ── 회의: 참석한 회의만, 가중치는 회의 상수(길이를 쓰지 않는다) ───────────────────────────────────
    for r in _read_multi(data_dir, "outlook", "calendar.csv"):
        t = pt(r.get("start"))
        if t is None:
            continue
        busy = str(r.get("busy_status") or "").strip()
        if _truthy(r.get("all_day")) or busy in ("3", "4"):
            skip("admin", t)                           # 종일·부재중·다른 곳에서 작업 — 행방이지 회의가 아니다
            continue
        why = _meeting_skip(r, tentative)
        if why:
            skip("nonwork" if "tentativeMeetings" in why else "admin", t)
            continue
        add(t, MEETING, r.get("subject"), W["회의"], "")

    sig.sort(key=lambda x: x[0])
    meta = {"counted": {k: counted.get(k, 0) for k in ("mail_in", "mail_out", "meetings")},
            "excluded": {k: excl.get(k, 0) for k in EXCLUDED_KEYS},
            "weights": {k: round(float(W[k]), 4) for k in SIGNAL_WEIGHT_KEYS},
            "config_warnings": cfg_warns,
            "unreadable": unreadable[0]}
    return sig, meta


def _meeting_skip(r, tentative="count"):
    """일정 행을 '참석'으로 볼 수 없는 사유(글자) 또는 None.
      busy_status   : 0 한가함(미수락·정보성) — 주최(1)·수락(3)했으면 참석
      response      : 0 없음/1 주최/2 미정/3 수락/4 거절/5 미응답 — 열이 있을 때만
      meeting_status: 5·7 취소된 회의 — 열이 있을 때만
      tentative     : "count"(기본) 미정도 셈 · "skip" 미정 제외 · "response" 응답 기준(미정·미응답 제외)
    수집 파일(§5.2)은 이 열들을 비워 쓴다 — 그때는 늘 None(수집 때 이미 거른 것)."""
    busy = str(r.get("busy_status") or "2").strip()
    resp = str(r.get("response") or "").strip()
    ms = str(r.get("meeting_status") or "").strip()
    if ms in ("5", "7"):
        return "취소된 회의(meeting_status)"
    if resp == "4":
        return "거절한 회의(response)"
    if busy == "0" and resp not in ("1", "3"):
        return "미수락 일정(한가함 상태)"
    pending = resp in ("2", "5") or (not resp and busy == "1")
    if tentative == "skip" and (pending or busy == "1"):
        return "미정 회의(tentativeMeetings=skip)"
    if tentative == "response" and pending:
        return "미정 회의(tentativeMeetings=response)"
    return None


# ── 낱말 ─────────────────────────────────────────────────────────────────────────────────
def _tokens(text):
    """과제 후보 낱말 집합 — 가림 토큰([사람]·[전화] …)·RE/FW·확장자·날짜·버전·상투어(STOP)·숫자는 뺀다."""
    t = privacy.TOKEN_RX.sub(" ", text or "")
    t = re.sub(r"^\s*((re|fw|fwd|답장|전달|회신)\s*[:：]\s*)+", "", t, flags=re.I)
    t = re.sub(r"\.(pptx|xlsx|docx|pdf|hwp|png|jpg|zip|csv|py|c|cpp|m)\b", " ", t, flags=re.I)
    t = re.sub(r"\d{4}[-_.]?\d{2}[-_.]?\d{2}|\bv?\d+(?:[._]\d+)+\b", " ", t)
    out = set()
    for m in re.findall(r"\[([^\]]{2,20})\]", t):
        s = m.strip().lower()
        if s and s not in STOP:
            out.add(s)
    for tok in re.split(r"[\s_\-\.\\/\[\]()<>:,·|~!?\"'+]+", t.lower()):
        tok = tok.strip()
        if len(tok) >= 3:                       # 조사 꼬리 — '보고의'·'과제명와' 가 과제명으로 새지 않게
            tok = re.sub(r"(의|를|을|은|는|이|가|에|로|와|과|도|께)$", "", tok)
        if 2 <= len(tok) <= 24 and tok not in STOP and not tok.isdigit():
            out.add(tok)
    return out


def activity_of(text, source=""):
    """신호 → 활동(Level 3) — 글의 낱말 규칙(ACT_RULES). 걸리는 것이 없으면 회의는 '회의·협업', 그 밖은 '기타'."""
    low = (text or "").lower()
    for name, kws in ACT_RULES:
        if any(k in low for k in kws):
            return name
    return "회의·협업" if source == MEETING else "기타"


def worktype_of(activity, kinds=()):
    """활동(Level 3) → 업무유형(개발·사무·현장·협업). 규칙에 없는 활동은 근거가 회의뿐이면 협업, 아니면 사무."""
    wt = WORKTYPE_OF_ACT.get(str(activity or ""))
    if wt:
        return wt
    ks = set(kinds or ())
    return "협업" if ks and ks <= {MEETING} else "사무"


def _norm_projects(projects):
    """지정을 (표시이름, [매칭어…]) 로. 글자면 이름 자신이 매칭어, (이름, [별칭]) 이면 별칭에 걸려도 이름으로 귀속."""
    out = []
    for p in projects or []:
        if isinstance(p, dict):
            name, alts = p.get("name"), list(p.get("match") or [])
        elif isinstance(p, (tuple, list)) and len(p) == 2:
            name, alts = p[0], list(p[1] or [])
        else:
            name, alts = p, []
        name = str(name or "").strip()
        if not name:
            continue
        needles = [name.lower()] + [str(a).strip().lower() for a in alts if str(a).strip()]
        out.append((name, [n for n in dict.fromkeys(needles) if n]))
    return out


# ── 규칙 과제명 잡음 — 상투어·버전 표기·6~8자리 날짜·편집기 기본 이름·사본 표기는 과제 후보가 아니다 ──────────────────
RULE_NAME_NOISE = {
    "untitled", "copy", "사본", "복사본", "복사", "수정본", "최종본", "final", "draft", "초안", "new", "old", "temp", "tmp",
    "backup", "백업", "test", "sample", "document", "book", "image", "presentation", "제목", "제목없음", "통합", "새",
    "워크시트", "프레젠테이션", "보고서", "자료", "회의", "미팅", "결과", "보고", "업무", "작업", "정리", "현황", "계획",
    "참고", "회람", "문의", "제출", "승인", "요약", "발표", "발표자료", "회의록", "초안본", "수정", "답변", "부탁드립니다",
    "드립니다", "감사합니다", "안녕하세요", "건", "관련하여", "진행", "확인요청", "검토요청", "요청드립니다", "공유드립니다"}
_RULE_NAME_RX = re.compile(r"^(v|ver|rev|r|버전)\.?\d+[a-z]?$|^\d{6,8}$|^(untitled|copy|사본|제목\s*없음)[\-_ ]?\d*$"
                           r"|^\(\d+\)$|^\d+(차|판|본)$", re.I)


def rule_name_ok(tok):
    """규칙 과제명 후보로 쓸 수 있는 낱말인가 — 상투어·버전·날짜·Untitled·copy 를 거른다."""
    t = str(tok or "").strip().lower()
    return bool(t) and t not in RULE_NAME_NOISE and not _RULE_NAME_RX.match(t)


# ── 대화 낱말 — 맞장구·인사·호칭·시각·흔한 소통 낱말과 '…습니다/…요/…까/…드린' 같은 문장 끝 꼴은 일을 가리키지 않는다.
#    규칙 과제 토큰(_cand_ok)·과제 이름(talk_name — details.task_name_ok·judge)이 되지 않는다. ──────────────────────────
TALK_WORDS = frozenset((
    # 맞장구·인사
    "네네", "넵넵", "예예", "응응", "오케이", "ok", "okay", "thanks", "thank", "thx", "noted", "sure", "yes", "please", "pls",
    "fyi", "asap", "수고", "안녕", "죄송", "실례", "괜찮", "그럼", "그래", "그래서", "그리고", "근데", "그런데", "그러면",
    # 부사·대명사
    "혹시", "혹시나", "아직", "이미", "벌써", "먼저", "바로", "일단", "우선", "다시", "계속", "같이", "함께", "모두", "다들", "조금",
    "많이", "너무", "정말", "진짜", "아마", "역시", "특히", "그냥", "어떻게", "언제", "언제쯤", "어디", "얼마나", "저희", "제가",
    "저는", "저도", "그쪽", "이쪽", "여기", "거기", "저기", "이거", "그거", "저거", "이건", "그건", "이것", "그것", "이번", "다음",
    "지난", "해당",
    # 시각·날
    "오늘", "내일", "어제", "모레", "그제", "금일", "명일", "익일", "오전", "오후", "아침", "점심", "저녁", "새벽", "지금", "방금",
    "이따", "이따가", "아까", "나중", "주말", "주중", "평일", "이번주", "다음주", "지난주", "금주", "차주", "내주", "이번달",
    "다음달", "지난달", "월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일", "시간", "잠깐", "잠시", "당일", "퇴근",
    "출근",
    # 흔한 소통 낱말 — 메일·회신·공유·확인 같은 것은 STOP·RULE_NAME_NOISE 에 이미 있다
    "통화", "전화", "연락", "말씀", "메시지", "문자", "채팅", "답장",
    # 호칭(낱말 하나 — '책임님' 처럼 '님' 이 붙은 꼴은 아래 규칙)
    "책임", "선임", "수석", "매니저", "프로", "팀장", "파트장", "그룹장", "실장", "센터장", "본부장", "부장", "차장", "과장", "대리",
    "사원", "주임", "연구원", "위원", "박사", "교수", "담당", "담당자", "팀원", "여러분",
    # 수
    "하나", "다섯", "여섯", "일곱", "여덟", "아홉", "한두", "두세", "서너"))
_TALK_END_RX = re.compile(r"(?:니다|요|까|죠|드림|드린|드릴|드려|드렸|드리고|드리면|드리며|드려서|드리는|드리기|주시면|주시고|주셔서"
                          r"|하시면|하시고|하셔서|했음|됐음|있음|없음|했어|됐어|했다|됐다|한다|된다)$")
_TALK_NUM_RX = re.compile(r"^\d+(?:시|분|일|월|주|년|개|건|번|명|부|장|회|초|시간|분기|주차|차)(?:쯤|경|에|까지|부터|간|째|씩|반)?$")
_TALK_JAMO_RX = re.compile(r"^[ㄱ-ㅎㅏ-ㅣ]+$")
_TALK_SPLIT_RX = re.compile(r"[\s_\-\.\\/\[\]()<>:,·|~!?\"'+…^*;=&#%@]+")
_TALK_PART2_RX = re.compile(r"(?:으로|에서|에게|까지|부터|처럼|한테|이랑|에는|에도|에선|께서)$")
_TALK_PART1_RX = re.compile(r"(?:의|를|을|은|는|이|가|에|로|와|과|도|께|만)$")


def talk_word(tok):
    """일을 가리키지 않는 대화 낱말인가 — TALK_WORDS · '…님'(호칭) · 문장 끝·높임 꼴 · '3시'·'2개' 같은 수 · 자모('ㅎㅎ')."""
    t = str(tok or "").strip().lower()
    if not t:
        return False
    return (t in TALK_WORDS or (len(t) >= 2 and t.endswith("님")) or bool(_TALK_END_RX.search(t))
            or bool(_TALK_NUM_RX.match(t)) or bool(_TALK_JAMO_RX.match(t)))


def _talk_tokens(text):
    """대화 낱말 판정용 낱말 목록 — _tokens 와 같은 앞손질 뒤 두 글자 조사('으로'·'에서'…)부터 뗀다. 두 글자 미만·숫자만은 뺀다."""
    t = privacy.TOKEN_RX.sub(" ", str(text or ""))
    t = re.sub(r"^\s*((re|fw|fwd|답장|전달|회신)\s*[:：]\s*)+", "", t, flags=re.I)
    t = re.sub(r"\.(pptx|xlsx|docx|pdf|hwp|png|jpg|zip|csv|py|c|cpp|m)\b", " ", t, flags=re.I)
    t = re.sub(r"\d{4}[-_.]?\d{2}[-_.]?\d{2}|\bv?\d+(?:[._]\d+)+\b", " ", t)
    out = []
    for tok in _TALK_SPLIT_RX.split(t.lower()):
        tok = tok.strip()
        if len(tok) >= 3:
            t2 = _TALK_PART2_RX.sub("", tok)
            tok = t2 if t2 != tok else _TALK_PART1_RX.sub("", tok)
        if len(tok) >= 2 and not tok.isdigit():
            out.append(tok)
    return out


def content_words(text):
    """글에서 일을 가리키는 낱말 — 상투어·버전·날짜·가림 토큰·대화 낱말을 뺀 나머지(순서 유지). 빈 목록이면 일을 가리키지 않는다."""
    return [x for x in _talk_tokens(text) if x not in STOP and rule_name_ok(x) and not talk_word(x)]


def talk_name(name):
    """이름이 대화 낱말(과 상투어)뿐인가 — '책임님'·'보내드렸습니다'·'네 확인했습니다' 는 True(과제 이름 금지).
    대화 낱말이 하나는 있어야 한다. 낱말이 하나도 없으면(빈 값·가림 토큰뿐) False — 그쪽은 사람 이름 관문이 본다."""
    toks = _talk_tokens(name)
    return (any(talk_word(x) for x in toks)
            and not any(x not in STOP and rule_name_ok(x) and not talk_word(x) for x in toks))


# ── 신호 → (과제 × 활동) 격자 ─────────────────────────────────────────────────────────────────
def _needle_hit(needle, low, toks):
    """지정 매칭어 ↔ 신호 — 낱말 경계로 본다('ai'⊂'email' 같은 부분 문자열 오탐 방지). projmap 의 판정기를 그대로 쓴다."""
    try:
        import projmap
        return projmap._kw_hit(needle, toks)
    except Exception:  # noqa: BLE001
        return len(needle) >= 4 and needle in low


def _name_guard(signals):
    """규칙 과제 후보 관문 — 사람 이름·공지류('근태공지' 등) 낱말은 과제가 아니다. 낱말별 판정을 기억하는 함수를 돌려준다
    (core/details 가 없으면 늘 통과)."""
    try:
        from details import is_notice_name, is_person_name, person_keys, ukey2
    except ImportError:
        return lambda _x: True
    people = person_keys({s[4] for s in signals if len(s) > 4}, ROOT)     # who 열 + G1 이름 해시(D8)
    memo = {}

    def ok(x):
        v = memo.get(x)
        if v is None:
            v = memo[x] = (ukey2(x) not in people and not is_person_name(x, people) and not is_notice_name(x))
        return v
    return ok


def _cand_ok(x, df, n, guard):
    """규칙 과제 후보 낱말 — 3~20자 · 2회 이상이되 너무 흔하지 않음(신호의 1/3, 최소 3) · 상투어·대화 낱말 아님 ·
    근태·행방 낱말 아님(privacy.admin_hit) · 사람·공지 아님."""
    return (3 <= len(x) <= 20 and 2 <= df[x] <= max(3, n // 3) and rule_name_ok(x) and not talk_word(x)
            and not privacy.admin_hit(x) and guard(x))


def build_items2(signals, projects=None, min_w=1.0):
    """build_items + 신호별 귀속 → (items, assigns). assigns: [(날짜, 출처, 글, 가중치, who, 과제, 활동)] — signals 파일의 행."""
    guard = _name_guard(signals)
    items = build_items(signals, projects, min_w, _guard=guard)
    pl = _norm_projects(projects)
    df = Counter()
    parsed = []
    for t, src, text, w, who in signals:
        tk = _tokens(text)
        parsed.append((t, src, text, w, who, tk))
        for x in tk:
            df[x] += 1
    assigns = []
    for t, src, text, w, who, tk in parsed:
        low = text.lower()
        proj = next((name for name, nls in pl if any(_needle_hit(n, low, tk) for n in nls)), None)
        if proj is None:
            cand = [x for x in tk if _cand_ok(x, df, len(parsed), guard)]
            proj = sorted(cand, key=lambda x: (-df[x], x))[0] if cand else "미지정"
        assigns.append((t, src, text, w, who, proj, activity_of(text, src)))
    return items, assigns


EVIDENCE_PER_ITEM = 6          # evidence_<tag>.md 의 항목당 근거 줄 수


def build_items(signals, projects=None, min_w=1.0, _guard=None):
    """신호 → {(과제, 활동): {"w", "ev", "src", "days"}}. 지정 과제가 먼저, 없으면 자주 나온 낱말(사람·공지 낱말 제외).
    ev = 'MM-DD 글' 근거 줄(최대 EVIDENCE_PER_ITEM). 가중치 합이 min_w 미만인 칸은 뺀다(전부 빠지면 그대로 둔다)."""
    pl = _norm_projects(projects)
    guard = _guard or _name_guard(signals)
    df = Counter()
    parsed = []
    for t, src, text, w, _who in signals:
        tk = _tokens(text)
        parsed.append((t, src, text, w, tk))
        for x in tk:
            df[x] += 1

    def match_project(text, tk):
        low = text.lower()
        for name, nls in pl:
            if any(_needle_hit(n, low, tk) for n in nls):
                return name
        cand = [x for x in tk if _cand_ok(x, df, len(parsed), guard)]
        return sorted(cand, key=lambda x: (-df[x], x))[0] if cand else "미지정"

    items = defaultdict(lambda: {"w": 0.0, "ev": [], "src": Counter(), "days": set()})
    for t, src, text, w, tk in parsed:
        it = items[(match_project(text, tk), activity_of(text, src))]
        it["w"] += w
        it["src"][src] += 1
        it["days"].add(t.date())
        if len(it["ev"]) < EVIDENCE_PER_ITEM:
            it["ev"].append(f"{t:%m-%d} {_one_line(text)[:70]}")
    kept = {k: v for k, v in items.items() if v["w"] >= min_w}
    return kept if kept or not items else dict(items)


def _ax_field(text):
    """work_rows 끝 열: ax(AX 연계 표식 1/0) · field(분야) — core/details 규칙. 임포트 실패해도 추출은 계속(0·빈칸)."""
    try:
        from details import ax_flag, field_of
        return ax_flag(text), field_of(text)
    except Exception:  # noqa: BLE001
        return 0, ""


def evidence_kind(label):
    """출처 라벨 → 근거 갈래('메일(수신)' → '메일' · '회의' → '회의')."""
    return str(label or "").split("(")[0] or "기타"


def to_rows(items, function="", l1_map=None, pin=None):
    """격자 → work_rows 행(spec §5.5). 행 = {Function, Level 1, 유형, Level 2, Level 3, 상세설명, 근거건수, 근거, 확신도, ax,
    field, share, evidence}. 근거건수 = 신호 수 · 근거 = '메일 12 · 회의 3' · share = 가중치 비율(순서용 — 시간이 아니다) ·
    evidence = 'MM-DD 글' 목록(evidence_<tag>.md 로만 — CSV 에는 쓰지 않는다).
    확신도: 근거 갈래 2개 이상 + 서로 다른 날 3일 이상이면 상, 둘 중 하나면 중, 아니면 하(날짜 수는 여기서만 쓰고 남기지 않는다).
    l1_map·pin(ukey2(과제) → 상위): 지난 체계의 l1·사람이 정한 상위 — details.level1_fill 로 상위를 채운다."""
    tot = sum(v["w"] for v in items.values()) or 1e-9
    order = sorted(items.items(), key=lambda kv: (-kv[1]["w"], kv[0]))
    rows = []
    for (proj, act), v in order:
        kinds = Counter()
        for s, c in v["src"].items():
            kinds[evidence_kind(s)] += c
        n_days = len(v["days"])
        conf = "상" if (len(kinds) >= 2 and n_days >= 3) else ("중" if len(kinds) >= 2 or n_days >= 3 else "하")
        l3 = _one_line(act)
        ax, fld = _ax_field(f"{proj} {l3}")
        rows.append({
            "Function": function, "Level 1": _level1_fill(proj, l3, l1_map, pin), "유형": worktype_of(l3, kinds),
            "Level 2": proj, "Level 3": l3, "상세설명": "",
            "근거건수": int(sum(kinds.values())),
            "근거": " · ".join(f"{k} {c}" for k, c in sorted(kinds.items(), key=lambda kv: (-kv[1], kv[0]))),
            "확신도": conf, "ax": ax, "field": fld, "share": round(v["w"] / tot, 4),
            "evidence": list(v["ev"]),
        })
    return rows
