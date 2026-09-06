# -*- coding: utf-8 -*-
"""
extract.py — 개인 PC 흔적에서 업무 로드를 추출해 [매핑데이터] 형식 행으로 만든다. (LoadMonitor22)

v3 변경 (사용자 피드백 반영):
  · CC 분리     — 메일 rcv 열(to/cc/bulk)로 참조·단체발송을 구분. CC는 약하게(0.25×),
                  단체발송(bulk)은 계상하지 않고 '제외 집계'로만 남긴다. 팀즈도 단체채팅·단순수신은 감쇠.
  · SW 개발 부스트 — 코드 파일 가중 ×2, 커밋 기본가중 상향+변경량 반영, IDE 작업창은 12분당 1.0
                  (문서 20분당 1.0보다 촘촘하게) — "개발 MM이 적게 잡힌다" 보정.
  · 출처 명시    — 모든 신호에 출처가 남고, 소스별 채택/제외 건수를 meta로 반환한다 (데이터 출처 확인용).

MM은 절대시간이 아니라 기간 대비 비율(share)이다. 합이 항상 100%.

LM22 (로드율 보완):
  · 상한 폐기    — 출력 worked 를 자르던 16h 상한·연차 4h 클램프 삭제. 입력의 물리 한계(PC on≤24·
                  night≤13·주간≤11h, 구간 [0,1440], 미래 시각·역행 회의 폐기)만 검증해 worked≤24 를
                  구성상 보장하고, 이상치는 info["anomalies"]·["long_days"] 로 표시한다(자르지 않는다).
  · 과대 보정    — PC 하한은 능동 흔적이 있는 날만 · 점심 1h 차감 · 반차 비례 · 수동 신호끼리 다리 금지 ·
                  회의 신호 패드 0 · 미정/거절/미응답 회의 설정 · 파일 일괄 버스트는 시간 근거 제외.
  · 과소 보정    — 샘플러 간격 실측·idle 300s·같은 제목 이어붙임·부분 가동 보정 · 저녁/새벽 크레딧 ·
                  주말 산출물 창 · 표본화 전 전체 파일 시각을 세션 재료로 · 부재 추정(가용 차감).

LM22 2차 (감사 A4~A38 의 신호·달력·부재 부분):
  · 근태        — 남의 초대(_absence_skip)·복합 근태어 접미 일치(_absence_hit)·시간제 OOF ≤5h 반차·반차 시각(spans)
  · 종일 행사    — offsite_days(출장·현장·교육 = 근무), 다일 회의 날짜별 8h, 약속(ms 0)은 blocks 로 분리(_meeting_spans)
  · 파일        — 버스트 분당 anchor 1건(뭉치 ≥N×5 는 0)·대표 1건 w=0·이력(files_history)·author(타인)·열람(Recent)·
                  중복 키 (분,이름,확장자,폴더명)·코드 30건 이상 그룹 ×2 미적용
                  S3: 확장자 179종(CODE_EXTS·EXT_ACT)·file_hint 크기/자리표시자 가드·해석 출력 뭉치(같은 폴더·연속 분,
                  SIM_OUT_EXTS)는 시작 분 anchor 1건 + 대표 '파일(해석출력)'(W 파일해석출력 1.5·30분·능동 흔적)
  · 메일·팀즈    — 공지 발신자 조각 일치·회신자 면제, 미응답 초대는 설정으로, 내 발신의 수신 사본 제외, 팀즈 시각 보정,
                  날짜만 아는 발신은 세션 없이 능동 흔적만, 수동 세션 일 상한(passiveDayMaxMin)
  · 달력        — KR_HOLIDAYS(2025~2027 설·추석·대체·선거) 내장 · 수동기록(worklog)·pc_spans 읽기

LM22 2차 (감사 A1·A3·A6·A9·A13·A24·A25·A30~A35·D3·D4·D5·D7 의 시간·집계 부분 — day_work_hours·mm_from_hours):
  · PC 하한(A3)   — 스칼라 max 가 아니라 구간: 주간 창을 [가동 창 밖 흔적 | 샘플러가 덮은 구간 | 덮지 않은 가동 구간] 로 나눠
                    마지막 조각에만 하한(pc_spans ∩ 창, 없으면 first_on~last_off − 설명되지 않는 절전 공백). 점심·저녁(A33)은
                    흔적 ±5분이 없는 부분만 · 창 양끝 trimIdleEdgesMin · 항상 켜진 PC 는 흔적 창 · 반차 시각 제외 · A35
  · 샘플러        — 고착일 폐기(A1)·같은 제목 이어붙임 실동작(A24)·미커버 구간만 하한(A25)·공백 다리(D3 samplerGapBridgeMin)
  · 폴백·하한     — PC 기록 없는 날 흔적 창(A9 pcFloorFallback)·종일 행사 표준일(A6)·수동 기록(A13)·시차 근무 창 밖(D4 flexEdgeH)·
                    주말 "pc"(D7)·두 PC 병합(A32)
  · 가용·부재     — 부재 추정 완화(A31)·추정일은 분모에서도 제외·미래 평일·오늘 비율(A34 mm_from_hours now)
  · 재산정(A30)   — rehours_after_judge: 판정에서 버린 신호를 뺀 시간·MM (judge·UI 가 호출)
  · 표기(D5)      — info.measure·coverage·cfg_used (mine.py 가 mm_meta 최상위에도 싣는다)
"""
import csv
import glob
import json
import os
import re
from collections import Counter, defaultdict
from datetime import datetime
from datetime import timedelta as _td

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 활동(Level 3) 규칙 — 신호 텍스트에서 '무슨 활동인가'를 뽑는다
ACT_RULES = [
    ("설계", ["설계", "도면", "회로", "구조", "레이아웃", "schematic", "layout", "cad",
             ".dwg", ".sldprt", ".catpart", "design"]),
    ("해석·시뮬레이션", ["해석", "시뮬", "simul", "ansys", "zemax", "codev", "matlab",
                    "fem", "cfd", ".aedt", ".zmx", ".slx"]),
    ("SW개발", ["코드", "커밋", "commit", "구현", "디버그", "debug", ".py", ".c", ".cpp",
              ".cs", ".ipynb", "algorithm", "펌웨어", "firmware", "리팩터", "빌드에러"]),
    ("검증·평가", ["검증", "평가", "측정", "시험", "test", "v&v", "dv", "pv", "신뢰성",
                "계측", "실험"]),
    ("입고검사·현장", ["입고", "검사", "조립", "출장", "현장", "설비", "장비", "빌드", "샘플"]),
    ("자재·발주", ["자재", "발주", "구매", "ers", "bom", "부품", "조달", "견적"]),
    ("불량·대응", ["불량", "고장", "이슈", "fa ", "faca", "8d", "대책", "클레임", "ncr"]),
    ("회의·협업", ["회의", "미팅", "meeting", "리뷰", "review", "협의", "보고회"]),
    ("문서·보고", ["보고", "자료", "발표", "ppt", ".pptx", ".docx", "문서", "정리", "요약"]),
]
CODE_EXTS = {".py", ".c", ".cpp", ".cc", ".cxx", ".h", ".hpp", ".hh", ".cs", ".java", ".js", ".ts", ".tsx",
             ".ipynb", ".m", ".mlx", ".jl", ".lua", ".v", ".sv", ".vhd", ".vhdl", ".xdc", ".tcl", ".ps1", ".sh", ".bat",
             ".sql", ".r", ".go", ".rs"}
# 확장자 → 업무유형(Level 3) 단서(S3-P2). ACT_RULES 는 텍스트 부분 문자열이라 '.len'⊂'.length'·'.dat'⊂'.data' 오탐이 있고
# '.asm'(어셈블리 소스)은 설계 규칙에 먼저 잡힌다 — 확장자는 이름 **끝**으로 따로 판정한다. 범용 확장자(.dat .db .txt .csv)는
# 넣지 않는다(폴더명·힌트로 판정). .zpl/.lsf(광학 스크립트)는 해석 쪽.
EXT_ACT = {}
for _n, _exts in (
    ("설계", ".dwg .dxf .sldprt .sldasm .slddrw .catpart .catproduct .catdrawing .prt .drw .frm .sec .ipt .iam .idw .step .stp "
            ".igs .iges .x_t .x_b .sat .jt .stl .pcbdoc .schdoc .prjpcb .schlib .pcblib .kicad_pcb .kicad_sch .kicad_pro "
            ".kicad_sym .kicad_mod .brd .dsn .opj .sch .gbr .gtl .gbl .drl"),
    ("해석·시뮬레이션", ".zmx .zar .zos .zpl .zsc .zdf .seq .len .lis .lts .frd .oml .inr .fsp .lms .ldev .ind .aedt .aedtz "
                   ".wbpj .wbpz .mechdb .cas .cas.gz .dat.gz .msh .rst .mph .inp .odb .cae .asc .s2p .slx .mdl"),
    ("SW개발", ".hex .elf .map .bin .ioc .uvprojx .ewp .eww .xpr .qpf .qsf .bit .sof .asm .sln .vcxproj .csproj .lvproj .lvlib .vi .ctl"),
    ("검증·평가", ".tdms .lvm .pcd .las .laz .ply .bag .mcap .db3 .pcap .pcapng .h5 .hdf5 .npy .npz .parquet .mat"),
):
    for _e in _exts.split():
        EXT_ACT[_e] = _n
_CREO_RE = re.compile(r"\.(prt|asm|drw|frm|sec)\.\d{1,4}$", re.I)       # Creo 판번호 파일 bracket.prt.3
_SIG_SUFFIX_RE = re.compile(r"( 외 \d+건| \((?:일괄|해석 출력) \d+건\))+$")   # load_signals 가 붙이는 규모 표기


def _sig_name(text):
    """파일 신호 텍스트('이름 § 힌트 | 폴더:… (일괄 N건)') 의 파일 이름 부분 — 소문자, 규모 표기 제거."""
    name = str(text or "").split(" § ")[0].split(" | 폴더:")[0].strip().lower()
    return _SIG_SUFFIX_RE.sub("", name).strip()


def _ext_of_signal_text(text):
    """파일 신호 텍스트에서 확장자 — 복합(.cas.gz)·Creo 판번호(.prt.3 → .prt) 인식."""
    name = _sig_name(text)
    m = _CREO_RE.search(name)
    if m:
        return "." + m.group(1)
    for ce in (".cas.gz", ".dat.gz"):
        if name.endswith(ce):
            return ce
    return os.path.splitext(name)[1]


IDE_HINTS = ["visual studio", "vscode", "vs code", "pycharm", "intellij", "matlab",
             "qt creator", "eclipse", "notepad++", "vim", "spyder", "jupyter",
             "code.exe", "devenv", "android studio"]
STOP = {"검토", "요청", "회신", "공유", "확인", "전달", "관련", "안내", "파일", "문서", "최종",
        "수정", "신규", "완료", "송부", "부탁", "주간", "월간", "일정", "메일", "첨부", "내용",
        "re", "fw", "fwd", "pptx", "xlsx", "docx", "pdf", "hwp", "microsoft", "teams",
        "outlook", "excel", "word", "powerpoint", "chrome", "edge", "explorer", "claude"}


def _one_line(s, n=120):
    """개행·탭·연속 공백을 한 칸으로, 앞뒤 공백 제거(S2). Outlook 제목·파일명에서 온 세부업무 이름에 개행이 남으면
    프롬프트의 '· 과제 / 세부업무' 한 줄이 갈라지고 CSV 셀이 쪼개진다 — 쓰는 쪽(원천)에서 한 번 정규화한다.
    n=None 이면 자르지 않는다."""
    return " ".join(str(s or "").split())[:n]


# 비업무 기본 키워드 — 전부 소문자로 비교한다(대소문자·철자 변형 방어)
# '집중 시간'·'미리 알림' 류 나혼자 일정은 회의가 아니다 (Viva Insights 도 회의 집계에서 제외)
# 경로에만 나타나는 제외 키워드 — 제목 대조에서는 뺀다.
# 'temp' 가 'temperature' 헤더를, '임시' 가 '임시 회의' 를 지우던 실측 경로 차단.
PATH_ONLY_KW = {"temp", "downloads", "다운로드", "임시"}

# 교육·세미나류 키워드 (소문자 비교) — 신호 필터와 시간 계상이 같은 판정을 공유한다
EDU_KW = ("교육", "세미나", "특강", "강의", "webinar", "워크샵", "워크숍", "workshop", "설명회")

NONWORK_DEFAULT = ["집중 시간", "focus time", "미리 알림", "reminder", "할 일",
                   "연차", "휴가", "반차", "병가", "경조", "건강검진", "휴무",
                   "취소됨", "취소된", "canceled", "cancelled", "취소:",
                   "자동 회신", "automatic reply", "auto-reply", "out of office",
                   "부재중", "발송 실패", "undeliverable", "delivery has failed",
                   "read receipt", "읽음 확인"]

# 'system' 은 뺐다 — 이 조직의 Function 명(System/OE/ME/EE)이 표시 이름('김철수/System')에 들어간다(A23).
NOTICE_DEFAULT = ["정부24", "인화원", "윤리사무국", "innohr", "no-reply", "noreply",
                  "do-not-reply", "알림", "notification", "notice", "뉴스레터", "newsletter",
                  "웹진", "webzine", "공지", "설문", "survey", "시스템",
                  "sharepoint", "yammer", "viva", "helpdesk", "보안", "인사팀 공지"]
# 일반 명사 키워드 — 표시 이름의 부서명·성씨('LiDAR시스템팀'·'공지영'·'Vivaldi')에 부분 일치하지 않도록
# 조각(이름/직급/부서 구분자로 나눈 단위) **전체 일치**만 인정한다. 나머지 키워드는 조각 시작 일치.
NOTICE_GENERIC = {"시스템", "system", "공지", "알림", "설문", "보안", "광고", "마케팅", "viva", "notice",
                  "survey", "promotion", "프로모션", "notification"}
_NOTICE_SEG = re.compile(r"[\s/|,;()\[\]<>\"'@._-]+")

# ── 종일 '회사 밖 근무'(출장·현장·교육) 제목 키워드 — config.mm.offsiteKeywords 가 우선(A6) ──
OFFSITE_KW = ("출장", "현장", "외근", "교육", "세미나", "전시", "박람회", "고객사", "방문", "시험",
              "workshop", "trip", "site", "training", "offsite", "field")
# 파일 흔적 원천 — 현재 스냅샷 + 수집기가 400일 누적하는 이력(A15). 같은 (분, 이름, 확장자, 폴더명)은 1건.
FILE_SOURCES = ("files.csv", "recent.csv", "files_history.csv", "recent_history.csv")
# Recent 의 '열람만' 경로 — Outlook 첨부 임시 폴더는 언제나 열람이다(D2b)
VIEW_PATH_KW = ("content.outlook", "inetcache", "olk\\attachments", "olk/attachments", "\\temp\\", "/temp/",
                "\\temporary internet files\\")
CODE_GROUP_MAX = 30        # 한 (폴더,날)에 코드 파일이 이 이상이면 설치·체크아웃으로 보고 코드 ×2 를 주지 않는다(A16 2차 방어)

# 비업무 키워드의 판정 규칙(A36) — 예전 '어디서든 부분일치'는 'Reminder: 제출 마감'·'연차 사용 현황'·
# '취소된 발주 재검토'·'휴가철 캠페인' 같은 정상 업무 신호를 지우고 회의는 시간까지 없앴다.
#   접두(콜론)  : Outlook 이 자동으로 붙이는 '취소됨: '·'Canceled: '·'자동 회신: ' 류 — 제목 시작에 '키워드:' 일 때만
#   정확 일치   : Viva·Outlook 자동 항목('집중 시간'·'미리 알림'·'reminder'·'할 일') — 제목 전체가 그것일 때만
#   근태어      : _absence_hit 와 같은 토큰 접미 규칙('연차'·'여름휴가' ○ / '연차 사용 현황'·'휴가철' ×)
#   시스템 문구 : 자동회신·발송실패·읽음확인 — 어디에 있어도(실제 업무 제목에 나올 일이 없다)
#   그 밖의 config 추가어는 예전처럼 부분일치(사용자가 넣은 말은 사용자의 의도대로)
NONWORK_PREFIX = {"취소됨", "취소된", "취소", "canceled", "cancelled", "자동 회신", "automatic reply", "auto-reply",
                  "undeliverable", "발송 실패"}
NONWORK_EXACT = {"미리 알림", "reminder", "할 일", "집중 시간", "focus time"}
NONWORK_TOKEN = {"연차", "휴가", "반차", "반휴", "병가", "경조", "경조사", "건강검진", "휴무", "휴직", "월차", "공가"}
NONWORK_SUBSTR = {"자동 회신", "automatic reply", "auto-reply", "out of office", "부재중", "발송 실패", "undeliverable",
                  "delivery has failed", "read receipt", "읽음 확인"}


def _nonwork_list(cfg):
    """기본 목록 + config 추가분의 **합집합**. 예전엔 config 가 있으면 기본을 통째로
    대체해서, config 에 빠진 '집중 시간'·'미리 알림'(Viva Insights 자동 블록)이
    업무 회의로 계상됐다."""
    extra = cfg_list(cfg, "nonWorkKeywords")
    seen, out = set(), []
    for n in list(NONWORK_DEFAULT) + list(extra):
        s = str(n).strip().lower()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


_RE_PREFIX = re.compile(r"^\s*((re|fw|fwd|답장|전달|회신)\s*[:：]\s*)+", re.I)


def _nonwork_hit(low, nonwork):
    """비업무 판정 — 걸린 키워드 또는 None. load_signals.add(메일·회의·팀즈)·_meeting_spans·offsite_days 가 공유한다.
    파일명에는 적용하지 않는다(파일은 산출물이지 근태 이벤트가 아니다 — 호출측이 건너뛴다)."""
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
        elif k in s:                      # 시스템 문구(어디서든) · config 추가어(부분일치, 예전 동작)
            return k
    return None


def load_cfg():
    """config 를 읽는다. 메모장 등으로 저장하면 BOM이 붙는데 utf-8 로만 읽으면 파싱이
    깨져 설정 전체가 조용히 무시된다(실측) — utf-8-sig 로 읽고, 실패하면 경고를 남긴다."""
    p = os.path.join(ROOT, "config", "config.json")
    try:
        with open(p, encoding="utf-8-sig") as f:
            cfg = json.load(f)
    except FileNotFoundError:
        return {}
    except (ValueError, OSError) as e:
        print(f"[!] config\\config.json 을 읽지 못했습니다 ({type(e).__name__}: {e}) — "
              "기본값으로 진행합니다. JSON 문법(쉼표·따옴표)을 확인하세요.")
        return {}
    if not isinstance(cfg, dict):
        print(f"[!] config\\config.json 의 최상위가 객체({{…}})가 아닙니다({type(cfg).__name__}) — "
              "기본값으로 진행합니다.")
        return {}
    return cfg


# ── config 값 검증 — 잘못된 값은 traceback 으로 죽거나 조용히 무시되는 대신 기본값 + 경고 ──
# (경고는 load_signals meta["config_warnings"]·day_work_hours info["config_warnings"] 로 나가
#  mine.py 출력·mm_meta.json 에 남는다 — 오타를 사용자가 알 수 있게)
def _num(v, dflt, lo=None, hi=None, key="", warns=None):
    """config 숫자 키 → float. 없음·빈 값은 기본값(경고 없음). bool·문자열·NaN·범위 밖은 기본값 + 경고."""
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


def _bool(v, dflt, key="", warns=None):
    """config 참/거짓 키. 문자열 "false"/"0"/"no" 도 거짓으로 읽는다 — bool("false") 는 참이었다."""
    if v is None:
        return dflt
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)) and v == v:
        return bool(v)
    s = str(v).strip().lower()
    if s in ("true", "1", "yes", "y", "on"):
        return True
    if s in ("false", "0", "no", "n", "off", ""):
        return False
    if warns is not None:
        warns.append(f"{key}={v!r} 는 true/false 가 아님 — 기본값 {str(dflt).lower()} 적용")
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
    """config 의 목록 키 → list. 문자열 하나면 [그것], 그 밖의 형식은 [] + 경고.
    (문자열을 그대로 순회하면 글자 단위 키워드가 돼 신호 대부분을 지운다)"""
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


MM_CHOICES = {"method": ("activity", "workday"), "pcFloorNeeds": ("active", "any"),
              "tentativeMeetings": ("count", "skip", "response"), "pcFloorFallback": ("trace", "none"),
              # 야간 해석(솔버) 근무 인정(S4-N1): span(실행 구간) · anchor(뭉치당 30분) · off(게이트만, 시간 0)
              "simNight": ("span", "anchor", "off")}
MM_BOOLS = ("usePcFloor", "inferAbsence", "eveningCredit", "spanFromAllFiles", "offsiteAsWork",
            "simNightHumanUnlock")
MM_BOOLS_FALSE = ("viewCountsAsActive", "simNightNeedsPc")   # 기본 false 인 참/거짓 키


def norm_cfg(cfg):
    """config 전체를 한 번에 검증해 (정규화된 값 dict, 경고 list) 를 돌려준다.
    load_signals·day_work_hours·mm_from_hours 가 같은 값을 쓴다. mm·signalWeights 가 객체가 아니면 {}."""
    warns = []
    cfg = cfg if isinstance(cfg, dict) else {}
    mmc = cfg.get("mm")
    if mmc is None:
        mmc = {}
    elif not isinstance(mmc, dict):
        warns.append(f"mm 은 객체({{…}})여야 함({type(mmc).__name__}) — mm 설정 전부 기본값")
        mmc = {}
    n = {"standardDayHours": _num(mmc.get("standardDayHours"), STD_DAY_H, 0.5, 24,
                                  "mm.standardDayHours", warns),
         "sessionGapMin": _num(mmc.get("sessionGapMin"), float(SESSION_GAP_MIN), 0, 1440,
                               "mm.sessionGapMin", warns),
         "idleActiveSec": _num(mmc.get("idleActiveSec"), float(IDLE_ACTIVE_SEC), 0, 86400,
                               "mm.idleActiveSec", warns),
         "fileBurstN": int(_num(mmc.get("fileBurstN"), FILE_BURST_N, 2, 100000, "mm.fileBurstN", warns)),
         "mailTimeOffsetH": _num(mmc.get("mailTimeOffsetH"), 0.0, -24, 24, "mm.mailTimeOffsetH", warns),
         "samplerIntervalSec": _num(cfg.get("samplerIntervalSec"), 60.0, 1, 3600,
                                    "samplerIntervalSec", warns),
         "dayCapHours": _day_cap(mmc, warns),
         "dayWindow": _win_cfg(mmc.get("dayWindow"), DAY_WIN, "mm.dayWindow", warns),
         "lunch": _win_cfg(mmc.get("lunch"), LUNCH, "mm.lunch", warns),
         # ── LM22 2차 시간 보정 키(A18·A33·D3·D4·A9) — 이름은 공통 계약 그대로 ──
         "dinner": _win_cfg(mmc.get("dinner"), DINNER, "mm.dinner", warns),
         "passiveDayMaxMin": _num(mmc.get("passiveDayMaxMin"), PASSIVE_DAY_MAX_MIN, 0, 1440,
                                  "mm.passiveDayMaxMin", warns),
         "samplerGapBridgeMin": _num(mmc.get("samplerGapBridgeMin"), SAMPLER_GAP_BRIDGE_MIN, 0, 1440,
                                     "mm.samplerGapBridgeMin", warns),
         "flexEdgeH": _num(mmc.get("flexEdgeH"), FLEX_EDGE_H, 0, 12, "mm.flexEdgeH", warns),
         "trimIdleEdgesMin": _num(mmc.get("trimIdleEdgesMin"), TRIM_IDLE_EDGES_MIN, 0, 240,
                                  "mm.trimIdleEdgesMin", warns),
         # 야간 해석 인정 상한(밤당 h, 0 = 무제한) — 재실행 흔적이 있는 밤은 simNightHumanUnlock 이 이 상한을 푼다
         "simNightCapH": _num(mmc.get("simNightCapH"), SIM_NIGHT_CAP_H, 0, 24, "mm.simNightCapH", warns)}
    for k, allowed in MM_CHOICES.items():
        n[k] = _choice(mmc.get(k), allowed[0], allowed, "mm." + k, warns)
    for k in MM_BOOLS:
        n[k] = _bool(mmc.get(k), True, "mm." + k, warns)
    for k in MM_BOOLS_FALSE:
        n[k] = _bool(mmc.get(k), False, "mm." + k, warns)
    # weekendWindow: true(산출물 ±30분 창) · "pc"(능동 흔적이 있으면 PC 가동 구간 전체, D7c) · false
    wv = mmc.get("weekendWindow")
    n["weekendWindow"] = ("pc" if isinstance(wv, str) and wv.strip().lower() == "pc"
                          else _bool(wv, True, "mm.weekendWindow", warns))
    mins = dict(LONE_SIGNAL_MIN)
    sm = mmc.get("signalMinutes")
    if isinstance(sm, dict):
        for k, v in sm.items():
            x = _num(v, None, None, None, "", None)
            if x is None:
                warns.append(f"mm.signalMinutes[{k}]={v!r} 는 숫자가 아님 — 무시")
            else:
                mins[str(k)] = x
    elif sm is not None:
        warns.append(f"mm.signalMinutes 는 객체({{\"파일\":60,…}})여야 함({type(sm).__name__}) — 무시")
    n["signalMinutes"] = mins
    weights = {}
    sw = cfg.get("signalWeights")
    if isinstance(sw, dict):
        for k, v in sw.items():
            x = _num(v, None, 0, None, "", None)
            if x is None:
                warns.append(f"signalWeights[{k}]={v!r} 는 0 이상의 숫자가 아님 — 기본 가중치 유지")
            else:
                weights[str(k)] = x
    elif sw is not None:
        warns.append(f"signalWeights 는 객체({{…}})여야 함({type(sw).__name__}) — 기본 가중치")
    n["signalWeights"] = weights
    bad = [x for x in cfg_list(cfg, "holidays", warns) if not _dt(str(x))]
    if bad:
        warns.append(f"holidays 의 {bad!r} 는 날짜(YYYY-MM-DD)가 아님 — 무시")
    for k in ("nonWorkKeywords", "noticeSenders", "excludePathKeywords", "projects"):
        cfg_list(cfg, k, warns)
    return n, warns


EXTRA_PC_DIR = "추가PC"      # data\추가PC\<PC이름>\ — 다른 PC 에서 수집해 온 데이터


def _data_roots(data_dir):
    """본 수집 폴더 + 추가 PC 보관 폴더들. 여러 PC 를 쓰는 사람의 흔적을 한 번에 합친다."""
    roots = [data_dir]
    base = os.path.join(data_dir, EXTRA_PC_DIR)
    if os.path.isdir(base):
        roots += sorted(p for p in glob.glob(os.path.join(base, "*")) if os.path.isdir(p))
    return roots


def _read_multi(data_dir, *rel):
    """모든 루트에서 같은 상대경로의 CSV 를 읽어 이어붙인다."""
    rows = []
    for root in _data_roots(data_dir):
        rows += _read(os.path.join(root, *rel))
    return rows


def _glob_multi(data_dir, *rel_pattern):
    """모든 루트에 패턴을 적용한 파일 목록."""
    outs = []
    for root in _data_roots(data_dir):
        outs += glob.glob(os.path.join(root, *rel_pattern))
    return sorted(outs)


def _read(path):
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8-sig", errors="replace") as f:
            rows = list(csv.DictReader(f))
            # 수집기가 강제 종료되면 마지막 행이 열 수 부족(None 채움)으로 남는다.
            # 그 행 하나가 이후 모든 분석을 죽였다(실측 재현) — 여기서 걸러낸다.
            return [r for r in rows if None not in r.values()]
    except OSError:
        return []


def _dt(s, fmts=("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d")):
    """시각 문자열 → datetime. 시간부가 있는데 앞 형식이 모두 실패하면('2026-07-28 26:00:00')
    None — 예전의 날짜 폴백(s[:10])은 그 행을 '그날 00:00 신호'로 만들어 야간 0.5h·야근일 +1 을
    조용히 보탰다(실측). 호출측은 None 을 '시각 형식 오류'로 집계한다."""
    s = (s or "").strip()
    for f in fmts:
        if f == "%Y-%m-%d" and len(s) > 10:
            return None
        try:
            return datetime.strptime(s[:len(f) + 2], f)
        except ValueError:
            continue
    return None


# 폴더 근거 — 프로젝트가 아니라 그 안의 구획인 폴더명은 건너뛰고 위로 올라간다
GENERIC_DIR = {"documents", "문서", "desktop", "바탕 화면", "바탕화면", "downloads",
               "다운로드", "onedrive", "work", "작업", "업무", "temp", "임시", "new folder",
               "새 폴더", "자료", "data", "docs", "doc", "share", "공유", "backup", "백업",
               "users", "user", "내 pc", "pc", "폴더", "project", "projects", "프로젝트",
               "src", "source", "소스", "bin", "lib", "libs", "include", "inc", "obj",
               "build", "builds", "out", "output", "dist", "release", "debug", "target",
               "test", "tests", "테스트", "script", "scripts", "tool", "tools", "util",
               "utils", "config", "설정", "log", "logs", "로그", "result", "results",
               "결과", "report", "reports", "리포트", "보고", "img", "image", "images",
               "그림", "asset", "assets", "정리", "old", "archive", "보관", "이전",
               "final", "최종", "draft", "초안", "v1", "v2", "v3"}


def folder_label(folder):
    """파일이 속한 '프로젝트 폴더' 이름. 일반·구획 폴더면 한 단계 위로.
    사람이 프로젝트를 폴더로 나눠 쓰기 때문에 파일명 조각보다 훨씬 안정적인 근거다."""
    parts = [x for x in re.split(r"[\\/]+", str(folder or "")) if x.strip()]
    for x in reversed(parts):
        c = re.sub(r"\s+", " ", x).strip(" -_·|[](){}")[:40]
        if not c or c.lower() in GENERIC_DIR or re.fullmatch(r"[a-zA-Z]:", c):
            continue
        if re.fullmatch(r"\d{4}([-_.]?\d{2})*", c):      # 날짜 폴더
            continue
        return c
    return ""


def _is_ide(proc, title):
    t = f"{proc} {title}".lower()
    return any(h in t for h in IDE_HINTS) or any(e + " " in t or t.endswith(e) for e in CODE_EXTS)


_HINT_CACHE = None
_HINT_DIRTY = 0
_HINT_FLUSH_EVERY = 200     # 새 항목 N건마다 + 종료 때 저장 — 항목마다 전체 JSON 을 다시 쓰면 결과 폴더 5,000건에 O(n²) I/O
# 첫 줄 단서를 읽을 텍스트 확장자(S3-P3) — Abaqus *Heading·CODE V 렌즈 제목·Zemax 매크로 주석·MATLAB % 주석
HINT_TEXT_EXTS = {".txt", ".md", ".csv", ".tsv", ".py", ".m", ".c", ".cpp", ".cc", ".h", ".hpp", ".cs", ".js", ".ts", ".jl",
                  ".r", ".sh", ".bat", ".ps1", ".sql", ".tcl", ".lis", ".len", ".seq", ".inp", ".zpl", ".lsf", ".asc", ".lvm",
                  ".ioc", ".yaml", ".yml", ".toml", ".v", ".sv", ".vhd", ".vhdl", ".xdc", ".s2p"}
HINT_OOXML = (".docx", ".pptx", ".xlsx")
HINT_MAX_KB = 50_000        # 이보다 큰 파일은 열지 않는다 — 공유 폴더의 AV 온액세스 스캔·수 GB 측정 파일(줄바꿈 없는 .txt/.csv)
_PLACEHOLDER = 0x400000 | 0x40000 | 0x1000   # OneDrive 자리표시자(RECALL_ON_DATA_ACCESS·RECALL_ON_OPEN)·오프라인 — 열면 내려받기 시작
# 이진 해석 결과(.cas .rst .h5 .mat .odb .mph .db .dat …)는 위 두 목록에 없으므로 stat 도 open 도 하지 않는다


def _hint_cache_path():
    return os.path.join(ROOT, "data", "files", "file_hints.json")


def _hint_cache_flush():
    global _HINT_DIRTY
    if not _HINT_DIRTY or _HINT_CACHE is None:
        return
    cache_p = _hint_cache_path()
    try:
        os.makedirs(os.path.dirname(cache_p), exist_ok=True)
        with open(cache_p, "w", encoding="utf-8") as f:
            json.dump(_HINT_CACHE, f, ensure_ascii=False)
        _HINT_DIRTY = 0
    except OSError:
        pass


def _cache_put(key, hint):
    """빈 힌트도 캐시한다 — 큰 파일·자리표시자를 매번 stat/open 하지 않게. 저장은 N건마다·종료 때(atexit)."""
    global _HINT_DIRTY
    if _HINT_CACHE is not None:
        _HINT_CACHE[key] = hint
        _HINT_DIRTY += 1
        if _HINT_DIRTY >= _HINT_FLUSH_EVERY:
            _hint_cache_flush()
    return hint


def file_hint(path, size_kb=None):
    """파일 내용의 가벼운 단서 — 텍스트 파일 첫 의미 줄(4KB 안에서), office 문서는 내장 제목/첫 슬라이드 제목.
    무거운 요약 대신 '무슨 자료인지' 알 수 있는 최소 단서만. 결과는 캐시.
    열지 않는 것(S3-P3): 단서를 낼 수 없는 확장자(이진 해석 결과 등 — stat 도 하지 않는다) · HINT_MAX_KB 보다 큰 파일
    (수집기의 size_kb 또는 st_size) · OneDrive 자리표시자(st_file_attributes). 텍스트는 4KB 만 읽는다 —
    줄바꿈 없는 2GB 측정 .txt 를 `for ln in f` 로 읽으면 한 줄이 통째로 메모리에 올라왔다."""
    global _HINT_CACHE
    ext = _ext_of_signal_text(os.path.basename(str(path or "")))   # .cas.gz 는 여기서 걸러진다
    if ext not in HINT_TEXT_EXTS and ext not in HINT_OOXML:
        return ""
    if _HINT_CACHE is None:
        try:
            with open(_hint_cache_path(), encoding="utf-8") as f:
                _HINT_CACHE = json.load(f)
            if not isinstance(_HINT_CACHE, dict):
                _HINT_CACHE = {}
        except Exception:
            _HINT_CACHE = {}
        import atexit
        atexit.register(_hint_cache_flush)
    try:
        skb = float(size_kb) if size_kb not in (None, "") else None
    except (TypeError, ValueError):
        skb = None
    try:
        st = os.stat(path)
        key = f"{path}|{st.st_mtime:.0f}"
    except OSError:
        return ""
    if key in _HINT_CACHE:
        return _HINT_CACHE[key]
    if ((skb is not None and skb > HINT_MAX_KB) or st.st_size > HINT_MAX_KB * 1024
            or (getattr(st, "st_file_attributes", 0) & _PLACEHOLDER)):
        return _cache_put(key, "")
    hint = ""
    try:
        if ext in HINT_TEXT_EXTS:
            with open(path, encoding="utf-8", errors="replace") as f:
                head = f.read(4096)                              # 한 줄이 2GB 여도 4KB 만
            for ln in head.splitlines():
                ln = ln.strip()
                if re.match(r"\*[A-Za-z]", ln):                  # Abaqus 키워드 줄(*Heading·*Node …) — 제목은 그 다음 줄
                    continue
                ln = ln.lstrip("#/*-%!; ")                       # MATLAB %·Zemax !·Abaqus ** 주석 접두
                if len(ln) >= 6:
                    hint = ln[:70]
                    break
        elif ext in HINT_OOXML:
            import re as _re
            import zipfile
            with zipfile.ZipFile(path) as z:
                try:
                    core = z.read("docProps/core.xml").decode("utf-8", "replace")
                    m = _re.search(r"<dc:title>([^<]{3,80})</dc:title>", core)
                    if m:
                        hint = m.group(1)
                except KeyError:
                    pass
                if not hint and ext == ".pptx":
                    try:
                        s1 = z.read("ppt/slides/slide1.xml").decode("utf-8", "replace")
                        texts = _re.findall(r"<a:t>([^<]+)</a:t>", s1)
                        hint = " ".join(texts)[:70]
                    except KeyError:
                        pass
                if not hint and ext == ".docx":
                    try:
                        d1 = z.read("word/document.xml").decode("utf-8", "replace")
                        texts = _re.findall(r"<w:t[^>]*>([^<]+)</w:t>", d1)
                        hint = " ".join(texts)[:70]
                    except KeyError:
                        pass
    except Exception:
        hint = ""
    return _cache_put(key, hint)


def _text_filter(exclude):
    """개인정보 제외어 판정기 — text.lower() → 걸린 키워드 또는 None.
    load_signals(신호) 와 _file_times(시간 근거) 가 같은 규칙을 공유한다.
     · 경로 전용 토큰은 제외한다 — 경로는 수집기가 이미 거른다.
     · ASCII 는 단어 경계를 요구한다('temp'⊄'template'). 한글은 부분일치 유지
       ('개인'⊂'개인자료' 를 잡아야 하는 마지막 방어선)."""
    ex_all = [str(e).lower() for e in exclude if e]
    ex_kr = [e for e in ex_all if not e.isascii() and e not in PATH_ONLY_KW]
    ex_ascii = [e for e in ex_all if e.isascii() and e not in PATH_ONLY_KW]
    ex_pat = (re.compile("|".join(f"(?<![a-z0-9]){re.escape(e)}(?![a-z0-9])"
                                  for e in ex_ascii)) if ex_ascii else None)

    def hit(low):
        h = next((e for e in ex_kr if e in low), None)
        if not h and ex_pat:
            m = ex_pat.search(low)
            h = m.group(0) if m else None
        return h
    return hit


def _norm_person(s):
    """사람 표기 정규화 — 'CORP\\cs.kim'·'cs.kim@corp.com'·'Kim Chulsoo'·'김철수 (광학팀)' 을 비교 가능한 조각으로.
    도메인 접두·메일 도메인·괄호 뒤·공백·점·하이픈을 걷어낸 소문자."""
    s = str(s or "").strip().lower()
    s = s.split("\\")[-1].split("@")[0]
    s = re.sub(r"[\(\[/|].*$", "", s)              # '김철수 (광학팀)'·'홍길동/책임/…' → 이름만
    return re.sub(r"[\s._\-]+", "", s)


def _self_names(data_dir, cfg=None, file_rows=None, warns=None):
    """'나' 로 볼 이름 집합(정규화) — config.owner · Windows 계정 · teamsSelfNames · mail_source.json 의 me[].
    owner·teamsSelfNames·me 가 **전부 비어** '나' 후보가 Windows 계정뿐일 때만 파일 author 의 최빈값을 보탠다(owner
    미설정 PC 에서 내 문서 전부가 '타인' 으로 빠지는 것 방지). 세는 단위는 행이 아니라 (폴더, 날) 그룹 — 공유 결과 폴더에
    동료가 쓴 해석 뭉치 5,000행이 표를 지배해 동료가 '나' 가 되던 것 차단(VF-H2). 그룹 ≥3 이고 절반 이상일 때 적용하고,
    warns(list) 를 주면 한 줄 남긴다(이름은 가려서 — mm_meta 는 팀 서버로 올라간다).
    이름은 밖으로 나가지 않는다(Copilot 프롬프트·팀 묶음에 싣지 않음)."""
    cfg = cfg if isinstance(cfg, dict) else {}
    configured = {cfg.get("owner")}
    configured.update(cfg_list(cfg, "teamsSelfNames"))
    for root in _data_roots(data_dir):
        try:
            with open(os.path.join(root, "outlook", "mail_source.json"), encoding="utf-8-sig") as f:
                me = (json.load(f) or {}).get("me") or []
            configured.update(x for x in me if isinstance(x, str))
        except (OSError, ValueError, AttributeError):
            pass
    configured = {_norm_person(n) for n in configured if n}
    configured = {n for n in configured if len(n) >= 2}
    out = set(configured)
    acct = _norm_person(os.environ.get("USERNAME", ""))
    if len(acct) >= 2:
        out.add(acct)
    if configured:
        return out                     # 사용자가 '나' 를 알려줬다 — 파일 author 다수결은 쓰지 않는다
    if file_rows is None:
        file_rows = [r for p in FILE_SOURCES for r in _read_multi(data_dir, "files", p)]
    groups = set()
    for r in file_rows:
        a = _norm_person(r.get("author"))
        if not a:
            continue
        t = _dt(r.get("mtime"))
        groups.add((a, _burst_folder(r.get("folder")), t.date() if t else None))
    cnt = Counter(a for a, _f, _d in groups)
    if cnt:
        top, n = cnt.most_common(1)[0]
        tot = sum(cnt.values())
        if n >= 3 and n * 2 >= tot and len(top) >= 2 and top not in out:
            out.add(top)
            if warns is not None:
                warns.append(f"config.owner·teamsSelfNames 미설정 — 파일 author 최빈값 '{top[0]}{'*' * (len(top) - 1)}'"
                             f"((폴더,날) 그룹 {n}/{tot})을 나로 간주합니다. 다른 사람이면 config.owner 를 설정하세요")
    return out


def _is_me(author, self_names):
    """author 가 '나' 인가 — 비어 있으면 나(검사 불가). 정규화 후 완전 일치 또는 author 가 내 이름을 포함."""
    a = _norm_person(author)
    if not a:
        return True
    return a in self_names or any(len(s) >= 3 and s in a for s in self_names)


def _view_only(r, view_active=False):
    """recent.csv 행이 '열람만' 인가(D2b) — Outlook 첨부·임시 경로는 언제나 열람. 그 밖에는 target_mtime(원본의
    수정 시각)이 열람 시각(mtime)보다 2분 넘게 오래됐을 때(열어서 편집하지 않았다). 열이 없는 옛 recent.csv 는
    열람으로 보지 않는다. viewCountsAsActive=true 면 첨부 경로만 열람."""
    fol = (r.get("folder") or "").lower().replace("/", "\\")
    if any(k.replace("/", "\\") in fol for k in VIEW_PATH_KW):
        return True
    if view_active:
        return False
    tm, t = _dt(r.get("target_mtime")), _dt(r.get("mtime"))
    return bool(tm and t and tm < t - _td(minutes=2))


def _file_rows(data_dir):
    """모든 루트의 FILE_SOURCES 행 — 행마다 _root(루트 경로)·_recent(Recent 계열)·_hist(이력 파일) 표식을 남긴다."""
    out = []
    for rt in _data_roots(data_dir):
        for p in FILE_SOURCES:
            for r in _read(os.path.join(rt, "files", p)):
                r["_root"] = rt
                r["_recent"] = p.startswith("recent")
                r["_hist"] = p.endswith("_history.csv")
                out.append(r)
    return out


# 해석·시뮬레이션·기록 장비의 출력 확장자(S3-P4). 같은 폴더의 연속 분에 이런 파일이 수천 건 몰린 뭉치는 기계가 썼지만
# '내 일'(해석을 돌린 날)이다 — 뭉치 파일의 확장자 종류가 2개 이하이고 90% 이상이 여기 속하면 해석 출력형.
SIM_OUT_EXTS = {".dat", ".csv", ".tsv", ".txt", ".lis", ".out", ".h5", ".hdf5", ".npy", ".npz", ".mat", ".parquet", ".pkl",
                ".pcd", ".las", ".laz", ".ply", ".bag", ".mcap", ".db3", ".pcap", ".pcapng", ".tdms", ".lvm", ".rst", ".odb",
                ".cas", ".cas.gz", ".dat.gz", ".msh", ".bin"}


def _burst_folder(folder):
    """버스트 키의 폴더 조각 — 원 경로 소문자. folder_label 이 아니다: 라벨은 'results' 같은 일반명을 위 폴더로 올려
    서로 다른 결과 폴더를 합쳐 버린다."""
    return str(folder or "").lower().replace("/", "\\").rstrip("\\")


def _clusters(minutes, gap=2):
    """분 목록 → 연속(간격 ≤gap) 뭉치 [[m…], …] (정렬)"""
    out, cur = [], []
    for m in sorted(minutes):
        if cur and m - cur[-1] > gap:
            out.append(cur)
            cur = []
        cur.append(m)
    if cur:
        out.append(cur)
    return out


def _is_sim_output(exts):
    """뭉치의 확장자 분포(Counter) 가 해석 출력형인가 — 종류 ≤2 · 90% 이상 SIM_OUT_EXTS"""
    tot = sum(exts.values())
    return bool(tot and len(exts) <= 2
                and sum(n for e, n in exts.items() if e in SIM_OUT_EXTS) >= 0.9 * tot)


def _sim_end(code):
    """file_times 의 code 가 해석 출력 뭉치 anchor 면 그 뭉치의 끝 분, 아니면 None.
    code 는 False(일반 파일) · True(코드 파일) · ("sim", 끝 분). 옛 판이 남긴 문자열 "sim" 은 −1(끝 모름)로 —
    호출측이 max(시작, 끝) 으로 쓰면 폭 0 이 되어 야간 해석 인정이 조용히 늘지 않는다."""
    if isinstance(code, tuple) and code and code[0] == "sim":
        return float(code[1])
    return -1.0 if code == "sim" else None


def _file_times(data_dir, d0, d1, exclude=(), cfg=None, burst_n=None, self_names=None, sim_drop=None):
    """파일 흔적(FILE_SOURCES: 스냅샷 + 이력)의 **표본화 전 전체** 시각
    → ({date: [(분, code)]}, burst, n_burst, sim_bulk)   burst·sim_bulk 의 키는 (date, 분, 폴더 소문자)
      code 는 False(일반) · True(코드 파일) · ("sim", 끝 분)(해석 출력 뭉치의 시작 분 anchor — 기계가 쓴 시각, VF-H1.
      뭉치의 **시작·끝 분을 함께** 돌려준다: 야간 해석 인정(S4-N1, mm.simNight)이 실행 구간의 끝을 알아야 한다)
    · 시간 근거 전용이다 — 판정용 신호는 load_signals 의 표본(폴더·일 8건)을 그대로 쓴다.
      표본화가 긴 하루의 세션을 조각내 야간분을 잃던 과소(실측 07-08: 20.75h→16.5h)를 막는다.
    · 버스트 키는 (date, 분, 폴더) (S3-P4) — 폴더가 다르면 서로 버스트를 만들지 않는다. 해석이 두 시간 동안 결과 폴더에
      1초당 1파일을 쓰는 사이 다른 폴더에 손으로 저장한 pptx 가 '같은 분' 이라는 이유로 일괄로 접히지 않게.
    · 해석 출력 뭉치 = 같은 (date, 폴더)의 연속 버스트 분 합계 ≥ burst_n×5 이고 확장자가 해석 출력형(SIM_OUT_EXTS,
      종류 ≤2·90%) — 0 이 아니라 **뭉치 시작 분 anchor 1건**(해석만 돌린 날도 능동 흔적이 남아 하한이 열린다).
      load_signals 는 그 뭉치의 대표 1건을 '파일(해석출력)' 으로 남긴다(sim_bulk). anchor 는 code "sim" 으로 표시해
      day_work_hours·_signal_spans 가 하한 게이트에만 쓰고 야간 세션·저녁/새벽 크레딧 재료로는 쓰지 않는다(밤새 돌린
      솔버의 03:00 출력 3,000건이 새벽 크레딧 4.5h 가 되던 과대, VF-H1).
    · sim_drop = [(date, 폴더 라벨(소문자), 분, exact)] — 판정에서 대표를 버린 해석 뭉치(rehours_after_judge, VF-H3). 그 (날, 폴더)
      의 뭉치는 anchor 를 남기지 않는다. 라벨은 exact 면 완전 일치, 아니면 접두 일치(signals CSV 의 100자 절단으로 잘린 라벨),
      라벨이 없으면 대표 시각(분)으로 찾는다.
    · 그 밖의 파일은 예전 규칙 그대로(A7): 해석 뭉치를 뺀 **폴더 무관** (date, 분) 합계로 burst_n 건 이상이면 버스트 →
      분당 anchor 1건, 연속 뭉치 합계 ≥ burst_n×5 면 기계 생성(재동기화·복사·체크아웃)으로 0건. 재동기화가 여러 하위 폴더에
      흩어져 폴더마다 문턱 아래로 떨어지는 것을 폴더별 키만으로는 막지 못한다(F11: 5폴더×20건). 추가PC 루트별로 따로 세어
      max 를 쓴다 — 같은 동기화 폴더가 두 PC 에서 들어와 문턱이 절반이 되지 않게(A29).
    · 중복 키는 (분, 이름, 확장자, 프로젝트 폴더명) — 원경로·힌트와 무관(A29·A15).
    · 타인 저장 파일(author ≠ 나, A14)·열람만 한 Recent(D2b)·개인정보 제외어는 시간 근거가 아니다.
      비업무 키워드는 파일명에 적용하지 않는다(A36)."""
    cfg = cfg if isinstance(cfg, dict) else {}
    mc = norm_cfg(cfg)[0]
    burst_n = int(burst_n) if burst_n else mc["fileBurstN"]
    mmc = cfg.get("mm") if isinstance(cfg.get("mm"), dict) else {}
    view_active = _bool(mmc.get("viewCountsAsActive"), False)
    hit = _text_filter(exclude)
    all_rows = _file_rows(data_dir)
    if self_names is None:
        self_names = _self_names(data_dir, cfg, all_rows)
    rows, seen = [], set()
    pm_by_root = defaultdict(Counter)
    ext_by_key = defaultdict(Counter)           # (date, 분, 폴더) → 확장자 분포(해석 출력형 판정)
    for r in all_rows:
        t = _dt(r.get("mtime"))
        if not t or not (d0 <= t.date() <= d1):
            continue
        name = r.get("name") or ""
        ext = (r.get("ext") or "").lower()
        fol = folder_label(r.get("folder"))
        dk = (t.replace(second=0, microsecond=0), name.lower(), ext, fol.lower())
        if dk in seen:                          # 스냅샷·이력·추가PC 에 같은 파일이 겹친다
            continue
        seen.add(dk)
        key = (t.date(), t.hour * 60 + t.minute, _burst_folder(r.get("folder")))
        pm_by_root[r.get("_root")][key] += 1    # 버스트 판정은 필터 전 전체 건수로(루트별)
        ext_by_key[key][ext] += 1
        if not _is_me(r.get("author"), self_names):
            continue                            # 동료가 저장한 파일 — 내 시간 근거가 아니다
        if r.get("_recent") and _view_only(r, view_active):
            continue                            # 열람만 — 수동 흔적(D2b)
        low = (name + (" | 폴더:" + fol if fol else "")).lower()
        if hit(low):
            continue
        rows.append((key, ext in CODE_EXTS))
    per_min = Counter()
    for pm in pm_by_root.values():
        for k, n in pm.items():
            per_min[k] = max(per_min[k], n)
    big = burst_n * 5
    # ① 폴더별 버스트 → 연속 뭉치 ≥ big 이고 해석 출력형이면 해석 출력 뭉치(키 → 뭉치 id = (date, 시작 분, 폴더))
    burst_f = {k for k, n in per_min.items()
               if n + per_min.get((k[0], k[1] - 1, k[2]), 0) + per_min.get((k[0], k[1] + 1, k[2]), 0) >= burst_n}
    by_df = defaultdict(list)
    for k in burst_f:
        by_df[(k[0], k[2])].append(k[1])
    sim_cluster = {}
    for (day, folk), mins in by_df.items():
        for cl in _clusters(mins):
            span = [(day, x, folk) for x in range(cl[0], cl[-1] + 1)]
            if sum(per_min.get(k, 0) for k in span) < big:
                continue
            exts = Counter()
            for k in span:
                exts.update(ext_by_key.get(k, {}))
            if _is_sim_output(exts):
                for x in cl:
                    sim_cluster[(day, x, folk)] = (day, cl[0], folk)
    # ② 해석 뭉치를 뺀 나머지는 폴더 무관 (date, 분) 으로 예전 규칙(A7) — 분당 anchor 1건, 뭉치 ≥ big 은 0건
    glob = Counter()
    for k, n in per_min.items():
        if k not in sim_cluster:
            glob[(k[0], k[1])] += n
    burst_g = {g for g, n in glob.items()
               if n + glob.get((g[0], g[1] - 1), 0) + glob.get((g[0], g[1] + 1), 0) >= burst_n}
    by_day = defaultdict(list)
    for g in burst_g:
        by_day[g[0]].append(g[1])
    huge_g = set()
    for day, mins in by_day.items():
        for cl in _clusters(mins):
            if sum(glob.get((day, x), 0) for x in range(cl[0], cl[-1] + 1)) >= big:
                huge_g.update((day, x) for x in cl)
    burst = set(sim_cluster) | {k for k in per_min if k not in sim_cluster and (k[0], k[1]) in burst_g}
    out, nb, anchored, sim_first = {}, 0, set(), {}
    for key, code in rows:
        cid = sim_cluster.get(key)
        if cid is not None:                      # 해석 출력 뭉치 — 시작·끝 분(rows 는 시간순이 아니다)
            nb += 1
            m0, m1 = sim_first.get(cid, (key[1], key[1]))
            sim_first[cid] = (min(m0, key[1]), max(m1, key[1]))
            continue
        g = (key[0], key[1])
        if g in burst_g:
            nb += 1
            if g in huge_g or g in anchored:
                continue
            anchored.add(g)                      # 분당 anchor 1건 — ±half 만 남고 prod 게이트 재료는 유지
        out.setdefault(key[0], []).append((key[1], code))
    # 해석 출력 뭉치의 시작 분 anchor — 판정에서 대표를 버린 (날, 폴더) 는 남기지 않는다(VF-H3). 대표는 (폴더 라벨, 날)당 1건이라
    # 라벨이 온전하면(exact) 그 라벨의 폴더(하위 폴더 여럿이 한 라벨로 접힌 경우 전부)·그날 다른 뭉치도 함께 뺀다. 잘린 라벨(접두)·
    # 라벨 없음은 후보가 여럿이면 대표 시각(분)이 anchor 와 맞는 폴더로 좁힌다.
    by_folk = {}
    for (day, _m0, folk), (m, _mend) in sim_first.items():
        by_folk.setdefault((day, folk), set()).add(m)
    drop_folk = set()
    for dd, pre, mm, exact in (sim_drop or ()):
        if not pre and mm is None:
            continue
        cands = [k for k in by_folk if k[0] == dd
                 and (not pre or (folder_label(k[1]).lower() == pre if exact else folder_label(k[1]).lower().startswith(pre)))]
        if not exact and len(cands) > 1 and mm is not None:
            cands = [k for k in cands if int(mm) in by_folk[k]] or cands
        drop_folk.update(cands)
    for (day, _m0, folk), (m, mend) in sim_first.items():
        if (day, folk) not in drop_folk:
            out.setdefault(day, []).append((m, ("sim", mend)))
    return out, burst, nb, set(sim_cluster)


def load_signals(data_dir, d0, d1, exclude=(), cfg=None):
    """수집 폴더 → (signals, meta)
    signals: [(dt, source_label, text, weight)] — weight는 시간이 아니라 '관여 강도'
    meta: {"counted": {출처: 건수}, "excluded": {사유: 건수}, "weights": {...},
           "file_times": {date: [(분, code)]} — 표본화 전 전체 파일 시각(시간 근거용, JSON 아님)}"""
    cfg = cfg if (isinstance(cfg, dict) and cfg) else load_cfg()
    mc, cfg_warns = norm_cfg(cfg)          # mm·signalWeights 가 객체가 아니어도 죽지 않는다(기본값 + 경고)
    tentative = mc["tentativeMeetings"]
    mail_off = mc["mailTimeOffsetH"]       # 웹·Copilot 경로의 UTC 기록 보정
    W = {"파일": 3.0, "커밋": 4.0, "회의": 2.0, "메일": 1.0, "메일발신": 1.5, "메일CC": 0.25,
         "팀즈오더": 1.2, "팀즈": 0.4, "작업창_분당": 1 / 20, "IDE_분당": 1 / 12,
         "코드파일배수": 2.0,
         # LM22 2차: 열람만 한 Recent(D2b) · 동료 저장 파일(A14, 과제 맥락용) · 수동 기록(A13, 시간당)
         "파일열람": 1.0, "파일타인": 0.3, "수동기록_시간당": 2.0,
         # S3-P4: 해석 출력 뭉치(같은 폴더·연속 분에 데이터 파일 수천 건) 의 대표 1건 — 해석을 돌린 날의 산출
         "파일해석출력": 1.5}
    W.update(mc["signalWeights"])
    # 비업무 키워드는 대소문자 무시로 비교한다 — "Canceled:"(영문 Outlook)·"Cancelled:"(영국식)이
    # 소문자 'canceled' 목록을 통과해 취소 회의가 회의 가중치로 계상되던 결함이 실측됐다.
    nonwork = _nonwork_list(cfg)
    # 개인정보 필터를 '제목'에 걸 때의 오탐 방지:
    #  · 경로 전용 토큰은 제외한다 — 경로는 수집기가 이미 거른다.
    #  · ASCII 는 단어 경계를 요구한다('temp'⊄'template'). 한글은 부분일치 유지
    #    ('개인'⊂'개인자료' 를 잡아야 하는 마지막 방어선).
    _hit = _text_filter(exclude)
    mmc = cfg.get("mm") if isinstance(cfg.get("mm"), dict) else {}
    view_active = _bool(mmc.get("viewCountsAsActive"), False)
    all_frows = _file_rows(data_dir)
    # '나' 의 이름 집합(owner·계정·teamsSelfNames·mail_source me — 전부 비면 author 최빈값, VF-H2) — 파일 author(A14)·
    # 내가 보낸 메일의 수신 사본(A29) 판정에 쓴다. 이름은 meta 에도 싣지 않는다(다수결 적용은 config_warnings 한 줄, 이름 가림).
    self_names = _self_names(data_dir, cfg, all_frows, warns=cfg_warns)
    sig = []
    meta = {"counted": Counter(), "excluded": Counter(), "weights": {}, "config_warnings": cfg_warns,
            "view_only": 0, "author_excluded": 0}
    _dedup = {}                            # 중복 키 → sig 색인(None = 걸러진 신호)

    def _pt(s):
        """시각 파싱 + 형식 오류 집계 — 값이 있는데 못 읽으면 그 행은 조용히 사라지지 않고 센다"""
        t = _dt(s)
        if t is None and str(s or "").strip():
            meta["excluded"]["시각 형식 오류"] += 1
        return t

    def add(t, src, text, w, label=None, who="", dkey=None):
        if not (t and text):
            return
        text = _one_line(text, None)       # 개행·탭·연속 공백 → 한 칸(S2) — 프롬프트 한 줄·CSV 셀이 갈라지지 않게
        if not text:
            return
        lbl = label or src
        # 추가 PC 취합·파일 이력에서 같은 신호가 두 번 온다. 호출측이 준 키(파일: 분·이름·확장자·폴더명 —
        # 힌트·원경로와 무관, 메일: 분·편지함·대화 — 라벨·발신자 표기와 무관) 또는 (시각, 출처, 원문, 발신자)가
        # 같으면 한 번만 계상하고, 나중 것의 가중치가 높으면 그쪽(라벨 포함)을 남긴다(A29).
        key = dkey or (t, lbl, text[:120], who)
        if key in _dedup:
            meta["excluded"]["중복(추가 PC 취합·이력)"] += 1
            i = _dedup[key]
            if i is not None and w > sig[i][3]:
                meta["counted"][sig[i][1]] -= 1
                sig[i] = (sig[i][0], lbl, sig[i][2], w, sig[i][4])
                meta["counted"][lbl] += 1
            return
        _dedup[key] = None
        if not (d0 <= t.date() <= d1):
            return
        low = text.lower()
        hit = _hit(low)
        if hit:
            # 어떤 키워드가 무엇을 지웠는지 남긴다 — 조용한 삭제는 추적이 불가능하다
            meta["excluded"]["개인정보필터"] += 1
            meta["excluded"][f"개인정보필터({hit})"] += 1
            return
        if src != "파일":                    # 파일명에는 비업무 목록을 적용하지 않는다(A36) — 산출물이지 근태가 아니다
            nw = _nonwork_hit(low, nonwork)
            if nw:
                meta["excluded"]["비업무(연차·취소 등)"] += 1
                meta["excluded"][f"비업무({nw})"] += 1
                return
        _dedup[key] = len(sig)
        sig.append((t, lbl, text, w, (who or "").strip()[:20]))
        meta["counted"][lbl] += 1

    # ── 메일: 발신 > 직접수신 > CC. 단체발송·공지·수신전용 발신자는 업무 증거로 쓰지 않는다 ──
    notice = [str(x).strip().lower() for x in (cfg_list(cfg, "noticeSenders") or NOTICE_DEFAULT)
              if str(x).strip()]
    mail_rows = _read_multi(data_dir, "outlook", "mail.csv")
    # 행동 기반 판별의 재료: 내가 발신한 대화(conversation) 집합 + 발신자별 수신 횟수
    sent_conv = {(r.get("conversation") or "").strip().lower()
                 for r in mail_rows if r.get("box") == "sent"} - {""}
    recv_cnt = Counter()
    replied = set()
    for r in mail_rows:
        if r.get("box") != "sent":
            snd = (r.get("sender") or "").strip().lower()
            recv_cnt[snd] += 1
            if (r.get("conversation") or "").strip().lower() in sent_conv:
                replied.add(snd)      # 이 발신자와는 실제로 주고받은 이력이 있다

    def is_notice(snd, exempt=True):
        """공지·시스템 발신자 판정(A23) — 표시 이름을 조각(이름/직급/부서 구분자)으로 나눠 본다.
        일반 명사(시스템·공지·알림·viva…)는 조각 **전체 일치**만('LiDAR시스템팀'·'공지영'·'Vivaldi' 는 아님),
        구분자가 든 키워드('no-reply'·'인사팀 공지')는 부분 문자열, 나머지는 조각 시작 일치.
        회신 이력이 있는 발신자(replied)는 무조건 공지가 아니다."""
        s = (snd or "").strip().lower()
        if not s:
            return False
        if exempt and s in replied:
            return False
        segs = [x for x in _NOTICE_SEG.split(s) if x]
        for k in notice:
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

    def _mail_key(t, box, conv, subj, snd):
        """추가PC 취합용 중복 키(A29) — (분, 편지함, 대화 정규화 또는 제목 앞 40자). 둘 다 비면 발신자로 구분."""
        c = _RE_PREFIX.sub("", (conv or subj or "").strip().lower())[:40]
        return (t.replace(second=0, microsecond=0), "메일", "sent" if box == "sent" else "inbox",
                c or ("@" + _norm_person(snd)))

    for r in mail_rows:
        t = _pt(r.get("time"))
        if not t:
            continue
        if mail_off:
            t = t + _td(hours=mail_off)
        # 웹·Copilot 경로가 날짜만 알아낸 행(time_precision=date) — 시각은 정오로 두고 시간 근거에서 뺀다(A38):
        # 발신은 전용 라벨(세션 없음·능동 흔적 유지), 수신은 수동 신호라 정오 5분이 상한 안에서 묻힌다
        date_only = (r.get("time_precision") or "").strip().lower() == "date"
        if date_only:
            t = t.replace(hour=12, minute=0, second=0, microsecond=0)
        subj = r.get("subject")
        snd = (r.get("sender") or "").strip()
        key = _mail_key(t, r.get("box"), r.get("conversation"), subj, snd)
        if r.get("box") == "sent":
            add(t, "메일", subj, W["메일발신"], "메일(발신·일자)" if date_only else "메일(발신)", "나", dkey=key)
            continue
        sl = snd.lower()
        if _norm_person(sl) in self_names:        # 나에게 보낸 메모·다른 경로의 발신 사본 — 수신이 아니다(A29)
            if d0 <= t.date() <= d1:
                meta["excluded"]["내가 보낸 메일의 수신 사본"] += 1
            continue
        if is_notice(sl):             # ① 공지·시스템 발신자 — 업무 아님, 연결성에도 미포함
            if d0 <= t.date() <= d1:
                meta["excluded"]["공지·시스템 발신(정부24·HR 등)"] += 1
            continue
        rcv = (r.get("rcv") or "to").lower()     # 구버전 데이터(rcv 없음)는 직접 수신 취급
        if rcv == "bulk":
            if d0 <= t.date() <= d1:
                meta["excluded"]["메일 단체발송(To/CC 아님)"] += 1
            continue
        # ② 행동 기반: 5통 이상 받았는데 회신 대화가 한 번도 없는 발신자 = 알림성 → 강한 감쇠
        oneway = recv_cnt[sl] >= 5 and sl not in replied
        if rcv == "cc":
            add(t, "메일", subj, W["메일CC"] * (0.4 if oneway else 1.0),
                "메일(수신전용)" if oneway else "메일(CC)", snd, dkey=key)
        else:
            add(t, "메일", subj, (W["메일"] * 0.2) if oneway else W["메일"],
                "메일(수신전용)" if oneway else "메일(수신)", snd, dkey=key)

    off_kws = _offsite_kws(cfg)
    for r in _read_multi(data_dir, "outlook", "calendar.csv"):
        t, en = _pt(r.get("start")), _dt(r.get("end"))
        h = max(0.5, min(5.0, (en - t).total_seconds() / 3600)) if (t and en and en > t) else 1.0
        subj = r.get("subject") or ""
        busy = str(r.get("busy_status") or "2")
        # 종일 일정은 회의가 아니다 — 근태·행사·기간 블록이 5시간짜리 회의로 계상되던 것을 차단.
        # 단 종일 '회사 밖 근무'(출장·현장·교육 — offsite_days 와 같은 판정, A6)는 표준일 8h 만큼의 회의 가중치로
        # 날마다 남겨 과제 배분 근거가 되게 한다(시간은 day_work_hours 가 offsite_days 로 인정).
        if _truthy(r.get("all_day")):
            if t and _offsite_row(r, off_kws, nonwork, tentative, _hit):
                for dd in _allday_dates(t, en):
                    if d0 <= dd <= d1:
                        add(datetime(dd.year, dd.month, dd.day, 9, 0), "회의", subj, STD_DAY_H * W["회의"])
                continue
            if t and d0 <= t.date() <= d1:
                meta["excluded"]["종일 일정(회의 아님)"] += 1
            continue
        # 한가함(Free)·거절·미응답·취소·(설정 시)미정 = 참석 근거 없음 — 시간 계상(_meeting_spans)과 같은 판정
        skip = _meeting_skip(r, tentative)
        if skip:
            if t and d0 <= t.date() <= d1:
                meta["excluded"][skip] += 1
            continue
        if _edu_unaccepted(r, subj, busy):
            if t and d0 <= t.date() <= d1:      # 수락(busy/OOF·응답 1/3) 아닌 교육 = 미참여 추정
                meta["excluded"]["교육(미참여 추정 — 일정 미수락)"] += 1
            continue
        add(t, "회의", subj, h * W["회의"])

    # ── 파일: 산출물 = 최강 신호. 코드 파일은 추가 배수 (SW 개발 과소계상 보정) ──
    # 파일 신호는 먼저 모아서 축약한다. 시뮬레이션 배치·압축 해제 같은 기계 생성
    # 파일은 한 폴더·한 날에 수천 건이 몰리는데(실측: 한 주 3,058건), 그대로 신호가 되면
    # ① AI 판정 왕복이 수십 배로 늘고 ② 과제가 파일명 토큰 수프로 흩어지고 ③ 투입 MM 이
    # 실제 일한 양과 무관하게 부푼다. 사람 손이 만든 파일은 하루 한 폴더 8건을 넘기 어렵다.
    # 표본화 전 전체 시각(시간 근거)과 일괄 버스트 분(分)을 먼저 뽑는다 — day_work_hours 가
    # meta["file_times"] 를 세션 재료로 쓴다. 버스트(같은 분 ±1 에 N건)는 시간 근거에서 분당 anchor 1건만
    # 남기고(A7), 판정 신호로는 (폴더,날)당 대표 1건 '파일(일괄)' 을 가중치 0 으로 둔다(AI 표식용 —
    # 시간 0 인 일괄 파일이 월 MM 의 43% 를 가져가던 부작용 차단). 해석 출력 뭉치(S3-P4: 같은 폴더·연속 분에
    # 데이터 파일 수천 건)는 시작 분 anchor 1건 + 대표 1건 '파일(해석출력)'(W["파일해석출력"], 30분 세션, 능동 흔적).
    # 원천은 스냅샷 + 수집기가 누적한 이력(A15) — 같은 (분, 이름, 확장자, 폴더명)은 1건(A29).
    # author 가 나와 다른 파일(공유·동기화 폴더의 동료 저장, A14)은 '파일(타인)' 로만, Recent 의 열람만 한 행
    # (D2b: 첨부 임시 경로·열람 시각이 원본 수정보다 늦음)은 '파일(열람)' 로 남긴다 — 둘 다 시간 근거·능동 흔적이 아니다.
    meta["file_times"], burst, _nb, sim_bulk = _file_times(data_dir, d0, d1, exclude, cfg, self_names=self_names)
    file_groups = {}
    seen_f = set()
    for r in all_frows:
        t = _pt(r.get("mtime"))
        if not t:
            continue
        ext = (r.get("ext") or "").lower()
        code = ext in CODE_EXTS
        name = r.get("name") or ""
        fol = folder_label(r.get("folder"))
        dkey = (t.replace(second=0, microsecond=0), "파일", name.lower(), ext, fol.lower())
        if dkey in seen_f:
            if not r.get("_hist"):
                meta["excluded"]["중복(추가 PC 취합·이력)"] += 1
            continue
        seen_f.add(dkey)
        if not (d0 <= t.date() <= d1):
            continue
        other = not _is_me(r.get("author"), self_names)
        view = (not other) and bool(r.get("_recent")) and _view_only(r, view_active)
        if other:
            meta["author_excluded"] += 1
        if view:
            meta["view_only"] += 1
        # 잘린 행은 folder 가 None(restval)이다 — .get(k, "") 는 '키는 있고 값이 None'을
        # 못 거른다. os.path.join(None,…) 으로 죽던 실측 재현 지점. 타인 파일은 내용 단서를 열지 않는다.
        hint = "" if other else file_hint(os.path.join(r.get("folder") or "", name), r.get("size_kb"))
        text = (name + (" § " + hint if hint else "") + (" | 폴더:" + fol if fol else ""))
        bkey = (t.date(), t.hour * 60 + t.minute, _burst_folder(r.get("folder")))
        bulk = (not other) and (not view) and bkey in burst
        sim = bulk and bkey in sim_bulk
        file_groups.setdefault((fol or (r.get("folder") or ""), t.date()), []).append(
            (t, text, code, bulk, dkey, other, view, sim))

    PER_GROUP, PER_DAY = 8, 40

    def _spread(lst, n):
        """시간순으로 고르게 n 건 표본 — 하루의 앞·중간·끝이 남아 세션 폭이 보존된다."""
        lst = sorted(lst, key=lambda x: x[0])
        if len(lst) <= n:
            return lst
        if n <= 1:                       # 예산이 1칸 남은 날 — (n-1) 나눗셈 즉사 방지(재현 확정)
            return lst[:1]
        step = (len(lst) - 1) / (n - 1)
        return [lst[round(i * step)] for i in range(n)]

    day_load = Counter()
    dropped_files = n_bulk = n_sim = 0
    # 작은 그룹부터 — 예산(PER_DAY)이 차도 사람 손 파일(소규모 폴더)이 통째로 밀리지 않게(A7).
    for (_fol, day), grp in sorted(file_groups.items(), key=lambda kv: (kv[0][1], len(kv[1]))):
        hand = [x for x in grp if not x[3]]
        sim_grp = [x for x in grp if x[3] and x[7]]
        bulk_grp = [x for x in grp if x[3] and not x[7]]
        if sim_grp:                      # 해석 출력 뭉치(S3-P4) — 예산에 세지 않고 대표 1건, 가중치 W["파일해석출력"]
            t, text, code, _b, dkey, _o, _v, _s = sorted(sim_grp, key=lambda x: x[0])[0]
            add(t, "파일", text + f" (해석 출력 {len(sim_grp)}건)", W["파일해석출력"], "파일(해석출력)", dkey=dkey)
            n_sim += len(sim_grp)
            dropped_files += len(sim_grp) - 1
        if bulk_grp:                     # 일괄(버스트) 파일 — 예산에 세지 않고 대표 1건만 w=0
            t, text, code, _b, dkey, _o, _v, _s = sorted(bulk_grp, key=lambda x: x[0])[0]
            add(t, "파일", text + f" (일괄 {len(bulk_grp)}건)", 0.0, "파일(일괄)", dkey=dkey)
            n_bulk += len(bulk_grp)
            dropped_files += len(bulk_grp) - 1
        if not hand:
            continue
        keep = _spread(hand, PER_GROUP)
        room = PER_DAY - day_load[day]
        if room <= 0:
            dropped_files += len(hand)
            continue
        if len(keep) > room:
            keep = _spread(keep, room)
        day_load[day] += len(keep)
        dropped_files += len(hand) - len(keep)
        # 한 (폴더,날)에 코드 파일이 CODE_GROUP_MAX 이상이면 pip/npm 설치·체크아웃 — 코드 ×2 를 주지 않는다(A16)
        code_x2 = sum(1 for x in hand if x[2]) < CODE_GROUP_MAX
        for i, (t, text, code, _b, dkey, other, view, _s) in enumerate(keep):
            if len(hand) > len(keep) and i == len(keep) - 1:
                text += f" 외 {len(hand) - len(keep)}건"     # AI 가 규모를 알게 한다
            if other:
                add(t, "파일", text, W["파일타인"], "파일(타인)", dkey=dkey)
            elif view:
                add(t, "파일", text, W["파일열람"], "파일(열람)", dkey=dkey)
            else:
                add(t, "파일", text,
                    W["파일"] * (W["코드파일배수"] if (code and code_x2) else 1.0),
                    "파일(코드)" if code else "파일", dkey=dkey)
    if dropped_files:
        meta["excluded"]["파일 축약(같은 폴더·같은 날 표본화)"] += dropped_files
    if n_bulk:
        meta["excluded"]["파일 일괄생성(시간 근거 anchor 1건·(폴더,날)당 대표 1건 w=0)"] += n_bulk
    if n_sim:
        meta["excluded"]["파일 해석출력 뭉치(시작 분 anchor 1건·(폴더,날)당 대표 1건)"] += n_sim
    if meta["view_only"]:
        meta["excluded"]["파일 열람만(수동 흔적 — 하한 미개방)"] += meta["view_only"]
    if meta["author_excluded"]:
        meta["excluded"]["타인 저장 파일(author ≠ 나 — 시간 근거 제외)"] += meta["author_excluded"]
    for _lbl in ("파일(일괄)", "파일(해석출력)"):
        if not meta["counted"][_lbl]:
            del meta["counted"][_lbl]

    # ── 수동 기록(A13): collect/Add-WorkLog.ps1 의 worklog.csv — PC 밖 업무(출장·조립·현장) ──
    # 시간은 day_work_hours 가 manual_hours 로 하한 인정한다. 여기서는 과제 배분 근거(시간당 2.0)와
    # 능동 흔적(NIGHT_PRODUCTIVE)만 — 세션은 만들지 않는다(signalMinutes 0).
    for dd, (mh, texts) in sorted(manual_hours(data_dir, d0, d1).items()):
        add(datetime(dd.year, dd.month, dd.day, 9, 0), "수동기록",
            (" · ".join(texts) or "수동 기록")[:120], mh * W["수동기록_시간당"], "수동기록", "나")

    for r in _read_multi(data_dir, "files", "git_commits.csv"):
        try:
            churn = float(r.get("insertions") or 0) + float(r.get("deletions") or 0)
        except ValueError:               # Excel 재저장 등으로 오염된 수치 — 가중치만 포기
            churn = 0.0
        add(_pt(r.get("time")), "커밋",
            f"{r.get('repo','')} {r.get('subject','')}", W["커밋"] + min(4.0, churn / 150))

    # ── 팀즈: 오더(요청류) > 발신 > 단순 수신. 단체채팅 수신은 감쇠 (CC성 분리) ──
    # mailTimeOffsetH 는 팀즈 행에도 적용한다(A27 — Graph 경로가 UTC 로 남긴 시각 보정, 창 읽기는 보통 0)
    for p in _glob_multi(data_dir, "m365", "teams_*.csv"):
        for r in _read(p):
            t = _pt(r.get("time"))
            if t and mail_off:
                t = t + _td(hours=mail_off)
            kind = (r.get("kind") or "").lower()
            frm0 = (r.get("from") or "").strip()
            # A8: 창 읽기 경로(구판 수집분)는 본인 메시지도 kind=msg 로 남겼다 — 발신자가 '나' 면 발신으로 본다
            # (팀즈로 일한 날이 수동 흔적만 남아 PC 하한이 막히던 원인). self_names 는 owner·계정·teamsSelfNames.
            if kind not in ("sent", "order") and frm0 and _norm_person(frm0) in self_names:
                kind = "sent"
            group = (r.get("chat") or "").count(",") >= 2   # 참여자 3명 이상 = 단체채팅
            if kind == "order":
                w, lbl = W["팀즈오더"], "팀즈(오더)"
            elif kind == "sent":
                w, lbl = W["메일발신"] * 0.6, "팀즈(발신)"
            else:
                w, lbl = W["팀즈"], "팀즈(수신)"
            if group and kind not in ("order", "sent"):   # 내가 보낸 단체방 메시지는 발신(능동)으로 남긴다
                w *= 0.5
                lbl = "팀즈(단체)"
            frm = (r.get("from") or "").strip()
            if is_notice(frm, exempt=False):
                if t and d0 <= t.date() <= d1:
                    meta["excluded"]["공지·시스템 발신(정부24·HR 등)"] += 1
                continue
            add(t, "팀즈", r.get("summary"), w, lbl, frm)

    # ── 작업창: 순활동 '분' 단위 — 샘플 수가 아니라 실측 간격 × 샘플(A28). idle 임계는 시간 계산(_activity_spans)과
    # 같은 mm.idleActiveSec 을 쓴다(예전 180 고정은 읽기 구간을 시간엔 넣고 가중치엔 빼는 불일치). IDE·코드 창은 촘촘히 ──
    import statistics
    idle_act = mc["idleActiveSec"]
    day_len_min = float(mc["dayWindow"][1] - mc["dayWindow"][0])
    for p in _glob_multi(data_dir, "activity", "activity_*.csv"):
        rows = []
        for r in _read(p):
            t = _pt(r.get("time"))
            try:
                idle = float(r.get("idle_sec") or 0)
            except ValueError:           # 샘플러 강제종료로 열이 밀린 행 — 폐기(하단 스팬 계산과 동일 패턴)
                continue
            if t:
                rows.append((t, idle, r.get("process") or "", (r.get("title") or "")[:70]))
        rows.sort(key=lambda x: x[0])
        deltas = [(rows[i + 1][0] - rows[i][0]).total_seconds() for i in range(len(rows) - 1)
                  if 0 < (rows[i + 1][0] - rows[i][0]).total_seconds() <= 600]
        step = statistics.median(deltas) if deltas else float(mc["samplerIntervalSec"])
        step = min(300.0, max(float(mc["samplerIntervalSec"]), step))
        per = defaultdict(lambda: {"n": 0, "min": 0.0, "t0": None, "ide": False})
        for t, idle, proc, title in rows:
            if not title or idle > idle_act:
                continue
            s = per[(t.date(), title)]
            s["n"] += 1
            s["min"] += step / 60.0
            s["t0"] = min(s["t0"] or t, t)
            s["ide"] = s["ide"] or _is_ide(proc, title)
        for (_d, title), s in per.items():
            if s["n"] < 5:
                continue
            rate = W["IDE_분당"] if s["ide"] else W["작업창_분당"]
            add(s["t0"], "작업창", title, min(s["min"], day_len_min) * rate,
                "작업창(IDE)" if s["ide"] else "작업창")

    sig.sort(key=lambda x: x[0])
    meta["counted"] = dict(meta["counted"])
    meta["excluded"] = dict(meta["excluded"])
    meta["weights"] = {k: round(v, 4) if isinstance(v, float) else v for k, v in W.items()}
    return sig, meta


def _tokens(text):
    t = re.sub(r"^\s*((re|fw|fwd|답장|전달|회신)\s*[:：]\s*)+", "", text or "", flags=re.I)
    t = re.sub(r"\.(pptx|xlsx|docx|pdf|hwp|png|jpg|zip|csv|py|c|cpp|m)\b", " ", t, flags=re.I)
    t = re.sub(r"\d{4}[-_.]?\d{2}[-_.]?\d{2}|\bv?\d+(?:[._]\d+)+\b", " ", t)
    out = set()
    for m in re.findall(r"\[([^\]]{2,20})\]", t):
        s = m.strip().lower()
        if s and s not in STOP:
            out.add(s)
    for tok in re.split(r"[\s_\-\.\\/\[\]()<>:,·|~!?\"'+]+", t.lower()):
        tok = tok.strip()
        # 조사 어미 제거 — '보고의'·'문의의'·'과제명와' 같은 조각이 프로젝트명으로 새는 것 방지
        if len(tok) >= 3:
            tok = re.sub(r"(의|를|을|은|는|이|가|에|로|와|과|도|께)$", "", tok)
        if 2 <= len(tok) <= 24 and tok not in STOP and not tok.isdigit():
            out.add(tok)
    return out


def activity_of(text, source=""):
    """신호 → 활동(Level 3). 커밋·IDE·코드 파일은 SW개발, 파일 신호는 먼저 확장자(이름 끝, EXT_ACT — S3-P2)로,
    그 다음 텍스트 규칙(ACT_RULES)으로 본다."""
    if source.startswith("커밋") or "IDE" in source or source == "파일(코드)":
        return "SW개발"
    if source.startswith("파일"):
        if _CREO_RE.search(_sig_name(text)):
            return "설계"      # Creo 판번호(housing.asm.12·a.frm.1)는 CAD 가 확정 — '.asm'(어셈블리 소스) 규칙보다 먼저(VF-H4)
        a = EXT_ACT.get(_ext_of_signal_text(text))
        if a:
            return a
    low = (text or "").lower()
    for name, kws in ACT_RULES:
        if any(k in low for k in kws):
            return name
    return "회의·협업" if source == "회의" else "기타"


def _norm_projects(projects):
    """지정을 (표시이름, [매칭어…]) 로 정규화. 문자열이면 이름 자신이 매칭어(기존 동작).
    (이름, [별칭]) 이면 **별칭에 걸려도 상위 과제명으로 귀속**된다 —
    별칭이 그대로 과제명처럼 표시되던 문제 방지."""
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


def _needle_hit(needle, low, toks):
    """시드 매칭어 ↔ 신호. 토큰 경계로 판정한다 — raw 부분문자열은 오탐이 실측됐다
    ('ai'⊂'email', 'cad'⊂'cascade'). projmap 의 판정기를 그대로 재사용."""
    try:
        import projmap
        return projmap._kw_hit(needle, toks)
    except Exception:
        return len(needle) >= 4 and needle in low


def build_items2(signals, projects=None, min_w=1.0):
    """build_items + 신호별 귀속 내역 반환 — 주간/월별/분기 리뷰의 원천.
    returns (items, assigns)  assigns: [(dt, source, text, weight, project, activity)]"""
    items = build_items(signals, projects, min_w)
    # 같은 매칭 규칙으로 신호별 귀속 재현
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
        proj = next((name for name, nls in pl
                     if any(_needle_hit(n, low, tk) for n in nls)), None)
        if proj is None:
            cand = [x for x in tk if 3 <= len(x) <= 20 and 2 <= df[x] <= max(3, len(parsed) // 3)]
            proj = sorted(cand, key=lambda x: (-df[x], x))[0] if cand else "미지정"
        assigns.append((t, src, text, w, who, proj, activity_of(text, src)))
    return items, assigns


def build_items(signals, projects=None, min_w=1.0):
    """신호 → (프로젝트 × 활동) 격자. projects 지정 시 우선 매칭, 없으면 토큰 자동 발견."""
    pl = _norm_projects(projects)
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
        cand = [x for x in tk if 3 <= len(x) <= 20 and 2 <= df[x] <= max(3, len(parsed) // 3)]
        return sorted(cand, key=lambda x: (-df[x], x))[0] if cand else "미지정"

    items = defaultdict(lambda: {"w": 0.0, "ev": [], "src": Counter(), "days": set()})
    for t, src, text, w, tk in parsed:
        p = match_project(text, tk)
        a = activity_of(text, src)
        it = items[(p, a)]
        it["w"] += w
        it["src"][src] += 1
        it["days"].add(t.date())
        if len(it["ev"]) < 6:
            it["ev"].append(f"{t:%m-%d} [{src}] {text[:70]}")
    kept = {k: v for k, v in items.items() if v["w"] >= min_w}
    # 전부 걸러지면(약한 신호만 있는 기간) 문턱 없이 돌려준다 — rows 가 비어 총 MM 과 어긋나지 않게
    return kept if kept or not items else dict(items)


def to_rows(items, months, owner="", function=""):
    """가중치 → 비율(share) → 총 MM 배분. share 합이 항상 1.0 — 미분류 없음.
    총 MM이 0이면 0을 그대로 쓴다 — 예전 `months or 1` 폴백은 인정 근무 0h인 기간을
    화면에는 0, CSV에는 1.00 MM으로 내보내 두 산출물이 어긋나게 했다."""
    tot = sum(v["w"] for v in items.values()) or 1e-9
    months = float(months) if months is not None else 0.0
    rows = []
    for (proj, act), v in sorted(items.items(), key=lambda kv: -kv[1]["w"]):
        share = v["w"] / tot
        srcs = len({s.split("(")[0] for s in v["src"]})
        conf = "상" if (srcs >= 2 and len(v["days"]) >= 3) else ("중" if srcs >= 2 or len(v["days"]) >= 3 else "하")
        rows.append({
            "Function": function, "Level 1": "", "Level 2": proj, "Level 3": _one_line(act),
            "이름": owner, "상세설명": "",
            "share": round(share, 4), "mm": round(share * months, 3),
            "근거": " · ".join(f"{s}{n}" for s, n in v["src"].most_common()),
            "확신도": conf, "활동일수": len(v["days"]),
            "evidence": v["ev"],
        })
    if rows:
        # 행별 반올림(소수 3자리) 잔차를 가장 큰 행에 얹는다 — 행 합계와 총 MM 이 화면에서 어긋나지 않게
        # (실측: 행 합 7.585 → '7.58' vs 총 7.587 → '7.59')
        resid = round(months - sum(r["mm"] for r in rows), 3)
        if abs(resid) >= 0.0005:
            rows[0]["mm"] = max(0.0, round(rows[0]["mm"] + resid, 3))
    return rows


# ── MM v4: 투입 MM ↔ 가용 MM (로드율 비교용) ───────────────────────────────
# 사용자 확정 설계:
#   · 1 MM 의 정의 = 8h × 그 달 평일수 (주40시간 기준)
#   · 연차·휴가는 '일자에서 뺀다' → 가용 MM 의 분자에서 그 날짜가 빠진다
#   · 실제 업무시간이 주 52시간을 넘어도 자르지 않는다 — 상한 없이 실측 그대로
#   · 두 숫자를 나란히 낸다:  투입 MM(실제 일한 양)  /  가용 MM(일할 수 있었던 양)
#     로드율(%) = 투입 MM ÷ 가용 MM      100% = 가용 시간을 꽉 채워 일함
#
# 야간(19~08시)은 'PC가 켜져 있던 시간'이 아니라 **산출물 신호가 실제로 찍힌 시각의 폭**으로
# 잰다. 그래야 취침 중 켜둔 PC를 근무로 세지 않으면서도 진짜 야근은 상한 없이 정직하게 잡힌다.
# '수동기록'(Add-WorkLog)·날짜만 아는 발신(메일(발신·일자))도 그날의 능동 흔적이다 — 세션은 만들지 않는다(signalMinutes 0)
# '파일(해석출력)'(S3-P4) — 해석 출력 뭉치의 대표 1건: 해석을 돌린 날의 산출이라 능동 흔적(ACTIVE_SRC — PC 하한이 열린다)이지만
# 기계가 쓴 시각이라 야간 산출물(NIGHT_PRODUCTIVE)은 아니다 — 밤새 돌린 솔버의 03:00 출력이 새벽 크레딧·야간 세션이 되지
# 않는다(VF-H1). 주간 창 안의 시각은 day_work_hours 가 예전처럼 산출물·흔적으로 쓴다.
NIGHT_PRODUCTIVE = {"파일", "파일(코드)", "커밋", "메일(발신)", "팀즈(발신)", "수동기록", "메일(발신·일자)"}
STD_DAY_H = 8.0
# 근태어(A5) — 한글은 토큰 **접미 일치**(여름휴가·연차휴가·오후반차·육아휴직 ○ / 휴무일·휴가철·2연차 ×),
# 영문은 단어 경계 구문. 놓치면 정상 근무로 계산되므로 놓치는 쪽이 안전한 방향이다.
ABSENCE_KW_KR = ("연차", "휴가", "반차", "반휴", "병가", "경조", "경조사", "대체휴무", "휴무", "휴직", "월차", "공가")
ABSENCE_KW_EN = ("vacation", "pto", "annual leave", "out of office", "ooo")
ABSENCE_KW = ABSENCE_KW_KR + ABSENCE_KW_EN
HALF_KW = ("반차", "반휴", "오전", "오후", "half day", "half-day")
ABSENCE_GUARD = ("안내", "공지", "웹진", "캠페인", "신청 방법", "사용 촉진", "권장", "현황", "집계")
_ABS_SPLIT = re.compile(r"[\s_\-·/()\[\],:：]+")
_ABS_STRIP = re.compile(r"(입니다|사용|신청|중|임|함)$")
_ABS_EN = re.compile(r"(?<![a-z])(" + "|".join(re.escape(k) for k in ABSENCE_KW_EN) + r")(?![a-z])")
# 양력 고정 공휴일 + 근로자의날. 음력 명절·대체공휴일·선거일은 아래 KR_HOLIDAYS(연도별) 로 내장하고,
# 표에 없는 연도·임시 공휴일은 config.holidays 로 보충한다(A31). 그래도 없으면 '연휴 감지'가 과대계상을 막는다.
FIXED_HOLIDAYS = {(1, 1), (3, 1), (5, 1), (5, 5), (6, 6), (8, 15), (10, 3), (10, 9), (12, 25)}
# ★ 배포 전 정부 공고(인사혁신처·관보)로 재확인할 것 — 설·추석 연휴, 대체공휴일, 선거일, 임시공휴일.
#   2025: 설 1/28~30(+임시 1/27) · 삼일절 대체 3/3 · 어린이날/부처님오신날 대체 5/6 · 대선 6/3 · 추석 10/6~7 + 대체 10/8
#   2026: 설 2/16~18 · 삼일절 대체 3/2 · 부처님오신날 대체 5/25 · 지방선거 6/3 · 광복절 대체 8/17 ·
#         추석 9/24~25 + 대체 9/28 · 개천절 대체 10/5
#   2027: 설 2/8 + 대체 2/9~10 · 부처님오신날 5/13 · 광복절 대체 8/16 · 추석 9/14~16 · 개천절 대체 10/4 · 한글날 대체 10/11 ·
#         성탄절(토) 대체 12/27 (2023년부터 성탄·부처님오신날도 대체공휴일 적용)
KR_HOLIDAYS = {
    2025: {(1, 27), (1, 28), (1, 29), (1, 30), (3, 3), (5, 6), (6, 3), (10, 6), (10, 7), (10, 8)},
    2026: {(2, 16), (2, 17), (2, 18), (3, 2), (5, 25), (6, 3), (8, 17), (9, 24), (9, 25), (9, 28), (10, 5)},
    2027: {(2, 8), (2, 9), (2, 10), (5, 13), (8, 16), (9, 14), (9, 15), (9, 16), (10, 4), (10, 11), (12, 27)},
}
GAP_DAYS = 3
NIGHT_PAD_H = 0.5          # 야간 산출물 앞뒤로 인정하는 준비·마무리 시간


def _is_night(t, day_win=None):
    # 수집기(Get-PcOnHistory.ps1)가 night_hours 를 '08:00 이전 + 19:00 이후'로 적산하므로
    # 판정도 같은 경계(DAY_WIN)를 쓴다. 06시 기준이면 06~08시 근무가 인정시간에서 통째로 사라진다.
    # day_win 은 호출측(day_work_hours)의 지역 설정 — 모듈 전역을 덮어쓰지 않는다.
    a, b = day_win or DAY_WIN
    m = t.hour * 60 + t.minute
    return m >= b or m < a


def _truthy(v):
    return str(v or "").strip().lower() in ("true", "-1", "1", "yes", "y")


def _token_suffix_hit(s, kws, limit=8):
    """토큰이 키워드로 **끝나면** 인정(A5) — '여름휴가'·'연차휴가'·'오후반차'·'육아휴직' ○, '휴무일'·'휴가철' ×.
    숫자만 앞에 붙은 토큰('2연차' = 2년차)은 근태가 아니다. 어미(입니다·사용·신청·중…)는 떼고 본다."""
    for t in _ABS_SPLIT.split(str(s or "").strip().lower())[:limit]:
        t = _ABS_STRIP.sub("", t.strip())
        if not t:
            continue
        for k in kws:
            if t == k or (t.endswith(k) and not t[:-len(k)].isdigit()):
                return True
    return False


def _absence_hit(subj):
    """제목이 실제 근태인지 — '휴가철 안전 캠페인'·'휴무일 근무 협조'·'연차 사용 현황' 같은 공지가 하루를
    통째로 차감하지 않도록 오탐 가드어가 있으면 아니고, 한글은 토큰 접미 일치·영문은 단어 경계 구문만 인정한다.
    놓치면 정상 근무로 계산되므로 놓치는 쪽이 안전한 방향이다."""
    s = str(subj or "")
    if any(x in s for x in ABSENCE_GUARD):
        return False
    low = s.lower()
    if _ABS_EN.search(low):
        return True
    return _token_suffix_hit(low, ABSENCE_KW_KR)


def _half_hit(subj):
    """반차 표식 — 반차·반휴·오전·오후·half day, 또는 토큰 AM/PM(mm-formula-14)."""
    low = str(subj or "").lower()
    if any(k in low for k in HALF_KW):
        return True
    return any(t in ("am", "pm") for t in _ABS_SPLIT.split(low))


def _absence_skip(r):
    """남이 보낸·취소된·거절한·미응답 초대는 내 근태가 아니다(A4 — 동료 '[연차] 이름' 팀 공유 초대).
      meeting_status 3=받은 초대 / 5·7=취소 · response 4=거절 5=미응답 · busy 0=한가함
    열이 없는 경로(웹·색인·Copilot)는 busy 0 만 걸러 자기 근태(기본 '바쁨/부재중')를 남긴다."""
    ms = str(r.get("meeting_status") or "").strip()
    resp = str(r.get("response") or "").strip()
    busy = str(r.get("busy_status") or "").strip()
    if ms in ("5", "7") or resp in ("4", "5"):
        return True
    if ms == "3" and busy != "3":              # 받은 초대는 내가 OOF 로 표시한 것만 근태로 인정
        return True
    if busy == "0" and ms != "0":              # 한가함 초대(정보성)
        return True
    return False


def absence_days(data_dir, d0, d1, spans=None):
    """근태 부재일 — Outlook 종일 일정·부재중(OOF)·시간제 근태 일정에서 읽는다.
    returns {date: 0.5(반차) | 1.0(종일)}   ※ 출장·교육은 근무이므로 부재가 아니다(offsite_days 가 맡는다).
      · 종일: 제목에 반차 표식(오전/오후/반차/AM/PM)이면 0.5, 아니면 1.0
      · 시간제 OOF(busy 3): 길이 ≤5h 또는 반차 표식이면 0.5, 그 밖에 1.0 (A5 — 예전엔 무조건 1.0)
      · 시간제 바쁨: ≥6h → 1.0 · ≥3h → 0.5 · 그 미만 0 (예전과 같음)
      · 남이 보낸·취소·거절·미응답 초대(_absence_skip)는 아니다(A4)
    spans(dict 를 넘기면) 에 {date: [(m0, m1)]} 부재 구간(분)을 채운다 — 반차 시각. 종일 반차는 오전이면
    주간 창 시작~점심 끝, 오후면 점심 시작~주간 창 끝으로 둔다."""
    from datetime import timedelta
    out = {}
    for r in _read_multi(data_dir, "outlook", "calendar.csv"):
        if _absence_skip(r):
            continue
        t0, t1 = _dt(r.get("start")), _dt(r.get("end"))
        subj = r.get("subject") or ""
        if not t0 or not _absence_hit(subj):
            continue
        allday = _truthy(r.get("all_day"))
        oof = str(r.get("busy_status") or "").strip() == "3"
        half = _half_hit(subj)
        seg = None
        if allday:
            frac = 0.5 if half else 1.0
            if half:
                low = subj.lower()
                seg = ((DAY_WIN[0], LUNCH[1]) if ("오전" in low or "am" in _ABS_SPLIT.split(low))
                       else (LUNCH[0], DAY_WIN[1]))
        elif t1 and t1 > t0:
            dur = (t1 - t0).total_seconds() / 3600
            if oof:
                frac = 0.5 if (half or dur <= 5) else 1.0
            else:
                # 종일이 아닌 '바쁨' 상태로 올린 근태 — 길이로 판단한다. 이걸 놓치면
                # nonWorkKeywords 가 신호만 지우고 그날은 정상 8h 근무로 남는다.
                frac = 1.0 if dur >= 6 else (0.5 if dur >= 3 else 0.0)
                if frac == 1.0 and half:
                    frac = 0.5
            if frac == 0.0:
                continue
            if frac == 0.5 and t1.date() == t0.date():
                seg = (t0.hour * 60 + t0.minute, t1.hour * 60 + t1.minute)
        else:
            continue
        last = (t1 or t0).date()
        if t1 and t1.hour == 0 and t1.minute == 0 and last > t0.date():
            last -= timedelta(days=1)      # 종일/OOF 일정의 end 는 익일 00:00 (하루 더 차감 방지)
        d = t0.date()
        while d <= last:
            if d0 <= d <= d1:
                out[d] = max(out.get(d, 0.0), frac)
                if spans is not None and seg is not None:
                    spans.setdefault(d, []).append(seg)
            d += timedelta(days=1)
    return out


def _allday_dates(t0, t1):
    """종일 일정의 날짜 목록 — end 가 익일 00:00 이면 그 전날까지."""
    from datetime import timedelta
    if not t0:
        return []
    last = (t1 or t0).date()
    if t1 and t1.hour == 0 and t1.minute == 0 and last > t0.date():
        last -= timedelta(days=1)
    out, d = [], t0.date()
    while d <= last and len(out) < 62:      # 두 달 넘는 종일 블록은 행사가 아니다
        out.append(d)
        d += timedelta(days=1)
    return out


def _offsite_kws(cfg):
    """종일 '회사 밖 근무' 키워드 — config.mm.offsiteKeywords(기본 OFFSITE_KW) + 교육류(EDU_KW). 소문자."""
    cfg = cfg if isinstance(cfg, dict) else {}
    mmc = cfg.get("mm") if isinstance(cfg.get("mm"), dict) else {}
    kws = [str(k).strip().lower() for k in (cfg_list(mmc, "offsiteKeywords") or OFFSITE_KW) if str(k).strip()]
    return tuple(dict.fromkeys(kws + [k.lower() for k in EDU_KW]))


def _edu_unaccepted(r, subj, busy):
    """교육·세미나 일정인데 수락 근거가 없다(busy 2·3 도 아니고 응답 1·3 도 아님) = 미참여 추정."""
    resp = str(r.get("response") or "").strip()
    return (any(k in subj.lower() for k in EDU_KW) and str(busy).strip() not in ("2", "3")
            and resp not in ("1", "3"))


def _is_block_row(r, subj_low):
    """캘린더 행이 '회의가 아닌 블록' 인가(A19) — 약속(meeting_status 0)은 언제나 블록. 상태 열이 없는 폴백 경로에서는
    5h 를 넘고 출장·교육 키워드도 없는 시간제 일정('재택근무' 09~18)만 블록(자정을 넘는 4h 회의는 회의다).
    _meeting_spans(시간 근거 제외)와 offsite_days(종일 행사 폴백)가 같은 판정을 공유한다."""
    ms = str(r.get("meeting_status") or "").strip()
    if ms == "0":
        return True
    if ms:
        return False
    t0, t1 = _dt(r.get("start")), _dt(r.get("end"))
    if not (t0 and t1 and t1 > t0):
        return False
    off_kws = tuple(k.lower() for k in OFFSITE_KW) + tuple(k.lower() for k in EDU_KW)
    return (t1 - t0).total_seconds() / 60 > 300 and not any(k in subj_low for k in off_kws)


def _offsite_row(r, kws, nonwork, tentative="count", hit=None):
    """캘린더 행이 '회사 밖 근무'(출장·현장·교육) 하루인가(A6) — 종일 일정, 또는 회의가 아닌 하루짜리(≥6h) 시간제
    블록(A19 의 blocks: '협력사 현장 09~18' OOF 약속). busy 3(부재중)·4(근무지 외), 또는 busy 2 이고 제목에 키워드.
    근태(_absence_hit)·비업무·개인정보 제외어·취소/거절/한가함/설정상 미정(_meeting_skip)·남이 보낸 초대(ms 3 인데
    내가 부재중/근무지외로 표시하지 않음)는 아니다."""
    subj = r.get("subject") or ""
    low = subj.lower()
    if not _truthy(r.get("all_day")):
        t0, t1 = _dt(r.get("start")), _dt(r.get("end"))
        if not (t0 and t1 and (t1 - t0) >= _td(hours=6) and _is_block_row(r, low)):
            return False                        # 시간제 회의는 _meeting_spans 가 시간으로 센다(이중 계상 방지)
    if _absence_hit(subj) or _nonwork_hit(low, nonwork) or (hit is not None and hit(low)):
        return False
    if _meeting_skip(r, tentative):
        return False
    busy = str(r.get("busy_status") or "2").strip()
    ms = str(r.get("meeting_status") or "").strip()
    resp = str(r.get("response") or "").strip()
    if ms == "3" and busy not in ("3", "4") and resp not in ("1", "3"):
        return False                            # 남이 보낸 초대('[출장] 이름')는 내가 수락했거나 부재중/근무지외 표시일 때만
    return busy in ("3", "4") or (busy == "2" and any(k in low for k in kws))


def offsite_days(data_dir, d0, d1, cfg=None, exclude=None):
    """'회사 밖 근무' 일(A6) → {date: subject} — 종일 일정 + 하루짜리(≥6h) 시간제 블록(재택근무가 아닌 출장·현장·교육,
    A19 의 blocks 중 부재중/근무지외 또는 키워드). config.mm.offsiteAsWork=false 면 {}.
    day_work_hours 가 그날을 표준일 × (1−부재) 하한·능동 흔적으로 인정하고 부재 추정에서 뺀다.
    exclude(개인정보 제외어)를 주지 않으면 config.excludePathKeywords 를 쓴다."""
    cfg = cfg if isinstance(cfg, dict) else {}
    mmc = cfg.get("mm") if isinstance(cfg.get("mm"), dict) else {}
    if not _bool(mmc.get("offsiteAsWork"), True):
        return {}
    kws = _offsite_kws(cfg)
    nonwork = _nonwork_list(cfg)
    tentative = norm_cfg(cfg)[0]["tentativeMeetings"]
    hit = _text_filter(cfg_list(cfg, "excludePathKeywords") if exclude is None else exclude)
    out = {}
    for r in _read_multi(data_dir, "outlook", "calendar.csv"):
        if not _offsite_row(r, kws, nonwork, tentative, hit):
            continue
        t0, t1 = _dt(r.get("start")), _dt(r.get("end"))
        days = _allday_dates(t0, t1) if _truthy(r.get("all_day")) else [
            dd for dd in _allday_dates(t0, t1)
            if dd == t0.date() or dd < t1.date() or (t1.hour * 60 + t1.minute) >= 360]   # 마지막 날은 6h 이상일 때만
        for dd in days:
            if d0 <= dd <= d1 and dd not in out:
                out[dd] = (r.get("subject") or "").strip()
    return out


def manual_hours(data_dir, d0, d1):
    """collect/Add-WorkLog.ps1 의 data/manual/worklog.csv(date,category,hours,entity,note,user) → {date: (hours, [text…])}
    PC 밖 업무(출장·조립·장비 점검)의 유일한 원천(A13). 추가PC 포함(같은 행은 1건), 0 < h, 하루 합계 ≤ PHYS_CAP_H.
    day_work_hours 가 그날을 기록 시간 하한·능동 흔적으로 인정하고 부재 추정에서 뺀다."""
    out, seen = {}, set()
    for r in _read_multi(data_dir, "manual", "worklog.csv"):
        t = _dt((r.get("date") or "").strip()[:10])
        try:
            h = float(r.get("hours") or 0)
        except (TypeError, ValueError):
            continue
        if not t or not (0 < h <= PHYS_CAP_H) or not (d0 <= t.date() <= d1):
            continue
        key = (t.date(), (r.get("category") or "").strip(), h, (r.get("entity") or "").strip(),
               (r.get("note") or "").strip())
        if key in seen:
            continue
        seen.add(key)
        txt = " ".join(x for x in key[1:2] + key[3:5] if x)
        h0, lst = out.get(t.date(), (0.0, []))
        out[t.date()] = (min(PHYS_CAP_H, h0 + h), lst + ([txt] if txt else []))
    return out


def _pc_spans_rows(rows, d0, d1, anomalies=None):
    """pc_spans 행(start,end,src) → {date: [(m0, m1), …]} — read_pc_spans 의 본체. 루트별로 따로 부를 수 있게 뗐다(pc_daily 가
    구간이 어느 PC 것인지 알아야 한다)."""
    out = {}
    for r in rows:
        a, b = _dt(r.get("start")), _dt(r.get("end"))
        if not (a and b and b > a):
            continue
        note = ((f"pc_spans {(r.get('src') or '').strip() or 'event'} 구간 {round((b - a).total_seconds() / 3600, 1):g}h(>48h) — "
                 "자정 분할해 수용") if (b - a) > _td(hours=48) else None)
        cur = a
        while cur < b:
            dd = cur.date()
            nxt = datetime(dd.year, dd.month, dd.day) + _td(days=1)
            seg_end = min(b, nxt)
            if d0 <= dd <= d1:
                m0 = cur.hour * 60 + cur.minute + cur.second / 60.0
                m1 = 1440.0 if seg_end == nxt else seg_end.hour * 60 + seg_end.minute + seg_end.second / 60.0
                if m1 > m0:
                    out.setdefault(dd, []).append((m0, m1))
                    if note and anomalies is not None:
                        anomalies.append((dd, note))
                        note = None                    # 행마다 한 번(첫 해당 날짜)
            cur = seg_end
    return out


def read_pc_spans(data_dir, d0, d1, anomalies=None):
    """data/pc_spans.csv 또는 data/pc/pc_spans.csv(start,end,src — 로컬 시각, 자정 분할 없음) → {date: [(m0, m1), …]}
    없으면 {}. 자정을 넘는 구간은 날짜별로 자른다(끝이 자정이면 1440). 추가PC 의 구간도 그대로 모은다 —
    합집합·주간 창 교집합은 호출측(day_work_hours)이 한다.
    행 길이에 상한을 두지 않는다(VF-H8) — 수집기 계약이 'live = 현재 부팅 세션 → 지금까지 · 닫힌 구간 길이 무관' 이라 며칠
    켜 둔 PC 는 한 행(live·event-gap)이 된다. 예전 48h 상한은 그 행을 통째로 버려 pc_on 이 없으면 'PC 기록 결측' 으로 집계됐다.
    물리 한계는 자정 분할 조각(저마다 ≤24h)이 지킨다. 48h 를 넘는 행은 anomalies(list 를 주면) 에 (첫 해당 날짜, 설명) 으로
    남겨 결측과 구분한다. 시각 형식 오류·end ≤ start 행은 버린다."""
    rows = _read_multi(data_dir, "pc_spans.csv") + _read_multi(data_dir, "pc", "pc_spans.csv")
    return _pc_spans_rows(rows, d0, d1, anomalies)


def pc_daily(data_dir, d0, d1, day_win=None, anom=None, span_anoms=None):
    r"""PC 가동 기록을 날짜별로 합친다(본 PC + data\추가PC\*) → (pc, pc_wins, pc_spans, pc_win_all).
      pc         {date: (on_h, night_h, first_on_min|None, last_off_min|None)}
      pc_wins    {date: [(first_on, last_off), …]} — pc_on 행별 가동 창(두 PC 면 두 창, VF-H9)
      pc_spans   {date: [(m0, m1), …]} — pc_spans.csv **실제 구간**의 합집합(모든 루트)
      pc_win_all {date: [(m0, m1), …]} — 여러 PC 가 섞인 날에 한해, 실제 구간 ∪ 구간 없는 PC 의 창(하한 창의 재료)
    · PC 한 대(루트 하나)뿐인 날은 예전 규칙 그대로다 — pc_on 행이 있으면 그 행(on·night 는 수집기 값), 없으면
      _pc_row 가 구간에서 파생. 자기 구간과 자기 창을 섞지 않는다(잠금·절전 몇 분 공백·HH:mm 반올림으로 창이 구간보다
      조금 길어져 always_on·저녁 게이트가 뒤집히던 것 — 재검증 실측).
    · 여러 PC(루트 ≥2)가 기록을 남긴 날: 모든 PC 실제 구간의 합집합 + 구간 파일이 없는 PC(옛 수집분)의 '끊김 없는
      행(on ≈ 창 길이 ±15분)'의 창을 합쳐 그 길이를 가동 시간으로 쓴다 — 예전 (주간·야간) max 는 두 PC 를 다른 시간에
      쓴 날(데스크톱 08~12 + 노트북 13~18)을 5h 로 깎았다(제보). 스칼라 병합값과의 max 라 예전 값 밑으로는 안 간다.
      야간 조각은 수집기 경계(DAY_WIN 08/19시)로 잰다 — 행의 night 열과 같은 축이어야 max 가 이중 계상이 안 된다.
    · 화면의 주간 추이 PC 선도 이 함수(pc)를 쓴다.
    anom(d, kind, raw, used) 를 주면 기록 오류를 그리로 보고한다(기간 안 날짜만). span_anoms(list)는 구간 이상치."""
    day_win = day_win or DAY_WIN
    cw0, cw1 = float(DAY_WIN[0]), float(DAY_WIN[1])      # 야간 조각은 수집기 경계로(행의 night 열과 같은 축)
    pc, pc_wins, syn, roots_with, real_by_root = {}, {}, {}, {}, {}
    roots = _data_roots(data_dir)
    for ri, root in enumerate(roots):
        rows_sp = _read(os.path.join(root, "pc_spans.csv")) + _read(os.path.join(root, "pc", "pc_spans.csv"))
        real_by_root[ri] = _pc_spans_rows(rows_sp, d0, d1, anomalies=span_anoms)
        for dd in real_by_root[ri]:
            roots_with.setdefault(dd, set()).add(ri)
        for r in _read(os.path.join(root, "pc", "pc_on.csv")):
            try:
                d = datetime.strptime((r.get("date") or "")[:10], "%Y-%m-%d").date()
                on, ni = float(r.get("on_hours") or 0), float(r.get("night_hours") or 0)
            except (ValueError, TypeError):
                continue
            raw = (on, ni)
            roots_with.setdefault(d, set()).add(ri)
            if not (0.0 <= on <= PHYS_CAP_H and 0.0 <= ni <= min(on, PC_NIGHT_MAX_H)):
                on = min(max(on, 0.0), PHYS_CAP_H)
                ni = min(max(ni, 0.0), on, PC_NIGHT_MAX_H)
                if anom is not None and d0 <= d <= d1:
                    anom(d, f"pc_on 기록 오류(on {raw[0]:g}h·night {raw[1]:g}h)", [raw[0], raw[1]], [on, ni])
            fo, lo = _hhmm(r.get("first_on")), _hhmm(r.get("last_off"))
            if fo is not None and lo is not None and fo > lo:
                # 켠 시각이 끈 시각보다 늦다 — 가동 창을 알 수 없으니(옛 3열 형식처럼) 창 없이 계산하고 표시만
                if anom is not None and d0 <= d <= d1:
                    anom(d, f"pc_on first_on {_fmt_hm(fo)} > last_off {_fmt_hm(lo)}(가동 창 무시)", None, None)
                fo = lo = None
            if fo is not None and lo is not None and lo > fo:
                pc_wins.setdefault(d, []).append((fo, lo))
                if abs((lo - fo) / 60.0 - on) <= 0.25:           # 켠 뒤 끄기까지 끊김 없던 행 — 창이 곧 구간
                    syn.setdefault(d, []).append((fo, lo, ri))
            o_on, o_ni, o_fo, o_lo = pc.get(d, (0.0, 0.0, None, None))
            day_m, ni_m = max(o_on - o_ni, on - ni), max(o_ni, ni)
            pc[d] = (min(PHYS_CAP_H, day_m + ni_m), ni_m,
                     min((x for x in (o_fo, fo) if x is not None), default=None),
                     max((x for x in (o_lo, lo) if x is not None), default=None))
    pc_spans = {}
    for m in real_by_root.values():
        for dd, lst in m.items():
            pc_spans.setdefault(dd, []).extend(lst)
    pc_spans = {dd: _union_spans(lst) for dd, lst in pc_spans.items()}
    pc_win_all = {}
    for dd in set(pc_spans) | set(syn):
        if len(roots_with.get(dd, ())) < 2:
            continue                                   # PC 한 대뿐인 날 — 예전 규칙 그대로
        real = list(pc_spans.get(dd) or [])
        extra = [(a, b) for a, b, ri in syn.get(dd, []) if dd not in real_by_root.get(ri, {})]
        sp = _union_spans(real + extra)
        if not sp:
            continue
        pc_win_all[dd] = sp
        u_on = _union_min(sp) / 60.0
        u_ni = _union_min(_clip(sp, 0, cw0) + _clip(sp, cw1, 1440)) / 60.0
        o_on, o_ni, o_fo, o_lo = pc.get(dd, (0.0, 0.0, None, None))
        day_m, ni_m = max(o_on - o_ni, u_on - u_ni), max(o_ni, u_ni)
        pc[dd] = (min(PHYS_CAP_H, day_m + ni_m), ni_m,
                 min((x for x in (o_fo, sp[0][0]) if x is not None), default=None),
                 max((x for x in (o_lo, sp[-1][1]) if x is not None), default=None))
    return pc, pc_wins, pc_spans, pc_win_all


def _holiday_set(cfg):
    out = set()
    for x in cfg_list(cfg, "holidays"):
        dt = _dt(str(x))
        if dt:
            out.add(dt.date())
    return out


def _is_off_day(d, holidays, workdays=(1, 2, 3, 4, 5)):
    """주말 · config.holidays · 양력 고정 공휴일 · 내장 연도별 표(KR_HOLIDAYS: 설·추석·대체공휴일·선거일)"""
    md = (d.month, d.day)
    return (d.isoweekday() not in workdays or d in holidays
            or md in FIXED_HOLIDAYS or md in KR_HOLIDAYS.get(d.year, ()))


# ── 활동 구간(interval) 기반 투입시간 ──────────────────────────────────────
# '평일이면 8h'는 출근 여부일 뿐 업무 투입량이 아니다. 실제로 흔적이 남은 시간대만
# 합집합으로 더해 '근무 중 업무에 활용된 시간'을 잰다.
#   · 회의      : 캘린더 시작~종료 구간 그대로 (회의 '신호'는 세션을 만들지 않는다)
#   · 창 샘플러 : 무입력이 아닌 샘플 구간 (있으면 가장 정확)
#   · 신호 세션 : 파일·메일·커밋·팀즈 타임스탬프를 간격 SESSION_GAP_MIN 이내로 묶은 구간
# 구간이 겹치면 한 번만 센다(합집합). 근거가 없는 시간은 세지 않는다.
#
# LM22 — 출력 worked 를 자르는 상한(16h·연차 4h)은 없다. 대신 **입력의 물리 한계**만 검증해
# (PC on≤24·night≤13·주간≤11h, 모든 구간 [0,1440], 미래 시각·역행 회의 폐기) worked≤24 가
# 구성상 보장되고, 이상치는 잘라내는 대신 info["anomalies"]·["long_days"] 로 '표시'한다.
SESSION_GAP_MIN = 45       # 이 간격 안이면 같은 작업 세션 (config.mm.sessionGapMin 로 조정)
# ※ ActivityWatch 등은 수 분 단위 AFK 로 끊지만, 신호 밀도가 낮은 이 도구에서 너무 짧으면
#   실제 연속 작업이 조각난다 — 45분은 그 절충값이다. 수동 신호(수신·CC·단체)끼리는 다리를
#   놓지 않는다(40분 간격 수신 8통이 4.75h 로 부풀던 실측 E3).
# 흩어진 신호 하나가 함의하는 최소 작업시간(분). 설계 파일 한 번 저장은 30분이 아니라
# 한 시간 안팎의 작업을 뜻한다 — 산출물일수록 길게 잡는다. config.mm.signalMinutes 로 조정.
# 회의 0 = 회의 신호는 세션을 만들지 않는다. _meeting_spans 가 캘린더 구간을 정확히 재는데
# ±30분 패드가 겹쳐 회의마다 시작 전 30분이 얹혔다(실측 E17b: 1h 회의 4건 → 6h).
# 목록에 없는 라벨은 세션을 만들지 않는다(A18 — 예전 기본 10분은 가장 약한 '메일(수신전용)' 에 수신의 2배를 줬다).
LONE_SIGNAL_MIN = {"파일": 60, "파일(코드)": 90, "커밋": 90, "회의": 0,
                   "메일(발신)": 20, "팀즈(발신)": 10, "팀즈(오더)": 15,
                   "메일(수신)": 5, "메일(CC)": 3, "메일(수신전용)": 2, "팀즈(수신)": 5, "팀즈(단체)": 3,
                   # 열람만 한 Recent 는 수신 메일 수준의 수동 흔적(D2b) · 타인 파일·일괄 대표·수동기록·
                   # 날짜만 아는 발신은 시간 근거가 아니다(가중치·게이트만)
                   "파일(열람)": 5, "파일(타인)": 0, "파일(일괄)": 0, "수동기록": 0, "메일(발신·일자)": 0,
                   # 해석 출력 뭉치 대표(S3-P4) — 시작 분 anchor(file_times) 와 별도로 30분 세션(주간만 — 야간은 NIGHT_PRODUCTIVE
                   # 가 아니라 세션이 없다, VF-H1)
                   "파일(해석출력)": 30,
                   # 작업창 0 = 샘플러 신호는 세션을 만들지 않는다 — 샘플러 스팬(_activity_spans)이 이미
                   # 정확한데 lone 10분 기본값이 첫 샘플 앞 5분을 매일 덧붙였다(실측 9h → 9.08h)
                   "작업창": 0, "작업창(IDE)": 0}
ACTIVE_SRC = set(NIGHT_PRODUCTIVE) | {"회의", "팀즈(오더)", "작업창", "작업창(IDE)", "파일(해석출력)"}   # 능동 흔적
PASSIVE_DAY_MAX_MIN = 60.0  # 수동 신호만으로 만든 세션의 하루 합계 상한(분) — config.mm.passiveDayMaxMin(A18)
# ── 물리 한계·보정 파라미터 (config.mm 로 조정) ──
PHYS_CAP_H = 24.0          # 하루 24h — 유일한 출력 한계. 입력 검증이 정상이면 닿을 수 없다
PC_NIGHT_MAX_H = 13.0      # 야간창 19~24 + 00~08 = 13시간(입력 검증용 — 출력 상한이 아니다)
PC_DAY_MAX_H = 11.0        # 주간창 08~19 = 11h — on−night 가 이보다 크면 야간열 누락으로 본다
DAY_WIN = (8 * 60, 19 * 60)   # 주간 창(분). 수집기 night_hours 정의(08시 이전·19시 이후)와 같은 경계
LUNCH = (12 * 60, 13 * 60)    # PC 하한에서 차감하는 점심 — 그 시간에 흔적이 있으면 차감하지 않는다
DINNER = (18 * 60, 18 * 60 + 30)  # 야근일(PC 야간 가동 + 이 창 끝까지 켜짐)에 흔적이 없으면 차감하는 저녁 식사(A33)
TRACE_PAD_MIN = 5          # 점심·저녁·창 가장자리 판정에서 신호 1건이 뜻하는 '흔적 폭' ±분(A33 — 세션 꼬리 ±30분은 흔적이 아니다)
SAMPLER_GAP_BRIDGE_MIN = 60.0  # 샘플러 가동 창 안의 무입력 공백 중 이 분 이하는 근무로 잇는다(D3a, 점심·저녁 창 제외)
FLEX_EDGE_H = 1.0          # 시차 근무: 산출물 없이도 주간 창 밖 PC 가동을 앞뒤 각 이 시간까지 인정(D4a, 야간 합 ≤ PC night)
TRIM_IDLE_EDGES_MIN = 10.0  # PC 가동 창 양끝 이 분 안에 흔적이 없으면 창을 그만큼(첫/마지막 흔적까지) 다듬는다(A33)
SIM_NIGHT_CAP_H = 4.0      # 야간 해석(솔버) 인정 상한 — 밤(야간 창)당 h. config.mm.simNightCapH, 0 이면 무제한
SIM_NIGHT_ANCHOR_MIN = 30.0  # mm.simNight="anchor": 야간 해석 뭉치마다 인정하는 분(제출·확인 시간)
STUCK_COVER_H = 14.0       # 샘플러 고착(A1): 하루 샘플이 이 시간 이상을 덮는데 idle>0 비율이 STUCK_IDLE_RATIO 미만이면 폐기
STUCK_IDLE_RATIO = 0.02
IDLE_ACTIVE_SEC = 300      # 샘플러: 이 안이면 '읽는 중'도 활동 (기존 180s 는 읽기·생각 구간을 버렸다)
SAME_TITLE_BRIDGE_MIN = 10  # 같은 창 제목이 유지되면 이 간격까지 이어붙임
FILE_BURST_N = 8           # 같은 분(±1분)에 파일 N건 이상 = 일괄 동기화·복사 → 시간 근거 아님
FUTURE_SLACK_MIN = 5       # now+5분 이후 시각의 신호 = 시계 오류 → 시간 근거에서 폐기(집계)
LONG_DAY_H = 16.0          # 이보다 긴 날은 자르지 않고 long_days 에 표시만 한다


def _hhmm(s):
    """'HH:MM' → 분. '24:00' 은 1440. 못 읽으면 None."""
    s = str(s or "").strip()
    if not s:
        return None
    if s == "24:00":
        return 1440.0
    try:
        h, m = s.split(":")[:2]
        v = int(h) * 60 + int(m)
        return float(v) if 0 <= v <= 1440 else None
    except ValueError:
        return None


def _win_cfg(v, dflt, key="", warns=None):
    """config 의 ["HH:MM","HH:MM"] → (분,분). 형식이 이상하면 기본값(+경고)."""
    if v is None:
        return dflt
    try:
        a, b = _hhmm(v[0]), _hhmm(v[1])
        if a is not None and b is not None and 0 <= a < b <= 1440:
            return (a, b)
    except (TypeError, IndexError, KeyError):
        pass
    if warns is not None:
        warns.append(f"{key}={v!r} 는 [\"HH:MM\",\"HH:MM\"](시작<끝) 형식이 아님 — "
                     f"기본값 {_fmt_hm(dflt[0])}-{_fmt_hm(dflt[1])} 적용")
    return dflt


def _fmt_hm(m):
    return f"{int(m) // 60:02d}:{int(m) % 60:02d}"


def _day_cap(mmc, warns=None):
    """config.mm.dayCapHours — 원하면 설정으로만 거는 선택 상한(기본 없음).
    null·0·""·false = 없음. true 같은 bool·문자열·0.5~24 밖의 값은 상한 없음 + 경고."""
    cap = (mmc or {}).get("dayCapHours")
    if cap is None or cap is False or cap == 0 or (isinstance(cap, str) and cap.strip().lower()
                                                   in ("", "0", "null", "none", "false")):
        return None
    x = _num(cap, None, 0.5, 24, "mm.dayCapHours", None)
    if x is None and warns is not None:
        warns.append(f"mm.dayCapHours={cap!r} 는 쓸 수 없는 값(0.5~24 시간 또는 null) — 상한 없음")
    return x


def _clip(spans, lo, hi):
    return [(max(a, lo), min(b, hi)) for a, b in spans if min(b, hi) > max(a, lo)]


def _union_min(spans):
    """[(시작분, 끝분)] 합집합의 총 분 — 반올림 없음(크레딧 맞춤 계산용)"""
    total, cur_s, cur_e = 0.0, None, None
    for a, b in sorted((a, b) for a, b in spans if b > a):
        if cur_e is not None and a <= cur_e:
            cur_e = max(cur_e, b)
        else:
            if cur_e is not None:
                total += cur_e - cur_s
            cur_s, cur_e = a, b
    if cur_e is not None:
        total += cur_e - cur_s
    return total


def _union_hours(spans):
    """[(시작분, 끝분)] 합집합의 총 시간(h) — 겹치는 구간을 이중으로 세지 않는다"""
    return round(_union_min(spans) / 60.0, 2) if spans else 0.0


# ── 구간 산술(A3 — 하한을 스칼라 max 가 아니라 구간 단위로 합치기 위한 도구) ──
def _union_spans(spans):
    """[(a, b)] → 겹침을 합친 정렬 목록(빈 구간 제거)"""
    out = []
    for a, b in sorted((float(a), float(b)) for a, b in spans if b > a):
        if out and a <= out[-1][1]:
            if b > out[-1][1]:
                out[-1] = (out[-1][0], b)
        else:
            out.append((a, b))
    return out


def _subtract_spans(a, b):
    """a − b (구간 목록, 분)"""
    out = _union_spans(a)
    for ba, bb in _union_spans(b):
        nxt = []
        for x, y in out:
            if bb <= x or ba >= y:
                nxt.append((x, y))
                continue
            if x < ba:
                nxt.append((x, ba))
            if bb < y:
                nxt.append((bb, y))
        out = nxt
    return out


def _intersect_spans(a, b):
    """a ∩ b (구간 목록, 분)"""
    out = []
    ub = _union_spans(b)
    for x, y in _union_spans(a):
        for ba, bb in ub:
            lo, hi = max(x, ba), min(y, bb)
            if hi > lo:
                out.append((lo, hi))
    return _union_spans(out)


def _trace_window(pts, spans, pad_min=NIGHT_PAD_H * 60):
    """능동 흔적(시각 pts + 구간 spans)의 '첫 흔적 −pad ~ 마지막 흔적 +pad' 창 [(a, b)] — 없으면 [].
    항상 켜 두는 PC(A3f)·PC 기록이 없는 날(A9)의 하한 재료."""
    lo = list(pts) + [a for a, _b in spans]
    hi = list(pts) + [b for _a, b in spans]
    if not lo:
        return []
    a, b = max(0.0, min(lo) - pad_min), min(1440.0, max(hi) + pad_min)
    return [(a, b)] if b > a else []


def _trim_edges(window, trace_sp, trim_min):
    """PC 가동 창 양끝 trim_min 분 안에 흔적(trace_sp)이 없으면 그 끝을 안쪽으로 최대 trim_min 만큼(첫/마지막 흔적을
    넘지 않게) 다듬는다(A33 — 출퇴근 전후 켜 둔 시간). 창은 [(a, b)] 합집합, 흔적은 [(a, b)] 목록."""
    sp = _union_spans(window)
    if not sp or trim_min <= 0:
        return sp
    a0, b0 = sp[0][0], sp[-1][1]
    # 자정(00:00·24:00)에 닿은 끝은 수집기의 날짜 분할이지 켜고 끈 시각이 아니다 — 다듬지 않는다
    if a0 > 0 and not _intersect_spans([(a0, a0 + trim_min)], trace_sp):
        first_tr = min((x for x, y in trace_sp if y > a0), default=a0 + trim_min)
        sp = _clip(sp, min(a0 + trim_min, max(a0, first_tr)), 1440.0)
    if sp and b0 < 1440 and not _intersect_spans([(b0 - trim_min, b0)], trace_sp):
        last_tr = max((y for x, y in trace_sp if x < b0), default=b0 - trim_min)
        sp = _clip(sp, 0.0, max(b0 - trim_min, min(b0, last_tr)))
    return sp


def _fit_credit(credit, spans, allowed):
    """저녁·새벽 크레딧 [(a, b, anchor)] 을 '기존 구간에 더해지는 양 ≤ allowed(분)' 안에 맞춘다.
    줄일 때는 산출물 쪽 끝(anchor 'b' 저녁=끝, 'a' 새벽=시작)을 고정하고 창 가장자리 쪽을 깎는다 —
    가장자리 기준으로 줄이면 산출물 시각 자체가 크레딧 밖으로 밀려난다. 더해지는 양은 배율에 단조라
    이분 탐색으로 맞춘다. returns [(a, b)]"""
    def at(s):
        out = []
        for a, b, anchor in credit:
            ln = (b - a) * s
            out.append((b - ln, b) if anchor == "b" else (a, a + ln))
        return [(a, b) for a, b in out if b > a + 1e-9]

    base = _union_min(spans)

    def gain(s):
        return _union_min(spans + at(s)) - base

    if gain(1.0) <= allowed + 1e-9:
        return at(1.0)
    lo, hi = 0.0, 1.0
    for _ in range(40):
        mid = (lo + hi) / 2
        if gain(mid) <= allowed + 1e-9:
            lo = mid
        else:
            hi = mid
    return at(lo)


def _tail_clip(spans, limit):
    """구간 목록에서 **뒤쪽 limit 분**만 남긴다(앞을 깎는다). 야간 해석 인정의 상한 —
    해석 출력이 찍힌 끝쪽을 남겨야 인정 구간이 산출물 시각 밖으로 밀려나지 않는다(_fit_credit 과 같은 원칙)."""
    sp = _union_spans(spans)
    drop = _union_min(sp) - float(limit)
    if limit <= 0 or drop <= 1e-9:
        return sp
    out = []
    for a, b in sp:
        if drop <= 1e-9:
            out.append((a, b))
        elif b - a <= drop + 1e-9:
            drop -= b - a
        else:
            out.append((a + drop, b))
            drop = 0.0
    return out


def _sim_night_credit(sim_sp, hum_pt, hum_sp, view_pt, pc_night, d0, d1, day_win,
                      mode="span", cap_h=SIM_NIGHT_CAP_H, unlock=True, needs_pc=False):
    """야간 해석(솔버) 근무 인정(S4-N1) — 밤새 돌린 해석(ANSYS·Zemax·CFD…)의 실행 구간을 근무로 돌려준다.

    밤 = 주간 창 밖의 한 덩어리(기본 19:00~다음날 08:00) — 자정을 넘으므로 두 날짜에 걸친다.
      · end   = 그 밤 안 마지막 해석 출력 시각(뭉치의 끝 — _file_times 가 시작·끝을 함께 준다)
      · start = 그 밤 안에서 첫 해석 출력 **이전**의 마지막 사람 능동 흔적(= job 제출 시각). 없으면 첫 출력 시각
      · needs_pc 면 내 PC 야간 가동 구간과 겹치는 만큼만 — 기본 false(서버·클러스터에서 도는 해석이 대부분)
      · 상한 cap_h(밤당 h, 0=무제한)는 앞을 깎는다(출력 쪽 끝을 남긴다). 첫 출력 **뒤**에 사람 흔적(능동 신호·
        열람·샘플러·회의)이 있으면 = 새벽에 결과를 보고 다시 돌린 밤이라 상한을 풀고 구간 전체를 인정한다
        (unlock). 제출 시각(첫 출력 전)의 흔적은 해제 사유가 아니다.
      · mode="anchor" 는 뭉치마다 SIM_NIGHT_ANCHOR_MIN 분(제출·확인)만, "off" 는 아무것도 인정하지 않는다.
    입력은 모두 {date: …}(그날 0~1440분). sim_sp·hum_sp·pc_night 은 [(a, b)], hum_pt·view_pt 는 [분].
    returns ({date: [(a, b)]}, {"nights": 인정한 밤, "capped": 상한이 걸린 밤, "unlocked": 상한이 풀린 밤})
    구간은 날짜별로 잘라 돌려준다 — 호출측이 그날 흔적에 합집합으로 더한다(중복 계상 없음). 한 날짜가 두 밤
    (전날 밤의 새벽 + 그날 밤의 저녁)에 걸리면 날짜 합계에도 같은 상한을 건다."""
    out, free, st = {}, set(), {"nights": 0, "capped": 0, "unlocked": 0}
    dw0, dw1 = float(day_win[0]), float(day_win[1])
    if mode == "off" or not sim_sp or dw1 - dw0 >= 1440:
        return out, st
    base = d0.toordinal()

    def _am(dd, m):
        return (dd.toordinal() - base) * 1440.0 + float(m)

    def _pts(src):
        return sorted(_am(dd, m) for dd, lst in (src or {}).items() if d0 <= dd <= d1 for m in lst)

    def _sps(src):
        return _union_spans([(_am(dd, a), _am(dd, b)) for dd, lst in (src or {}).items()
                             if d0 <= dd <= d1 for a, b in lst])

    # 뭉치는 폭이 0 일 수 있다(한 분에 몰린 출력 수천 건·대표 신호 1건) — 합집합으로 접으면 사라지므로 그대로 둔다
    sim_a = sorted((_am(dd, a), _am(dd, max(a, b))) for dd, lst in (sim_sp or {}).items()
                   if d0 <= dd <= d1 for a, b in lst)
    hum_a, view_a = _pts(hum_pt), _pts(view_pt)
    hums_a, pc_a = _sps(hum_sp), _sps(pc_night)
    nd = d0 - _td(days=1)
    while nd <= d1:
        # 밤의 경계는 _is_night 과 같다 — 19:00 은 밤, 08:00 은 낮
        w0, w1 = _am(nd, dw1), _am(nd, 1440.0) + dw0
        nd += _td(days=1)
        cl = [(max(a, w0), min(b, w1)) for a, b in sim_a if b >= w0 and a < w1]
        if not cl:
            continue
        first, last = min(a for a, _b in cl), max(b for _a, b in cl)
        if mode == "anchor":
            seg = [(a, min(a + SIM_NIGHT_ANCHOR_MIN, w1)) for a, _b in cl]
        else:
            # job 제출 = 첫 출력 이전의 마지막 사람 흔적. 구간 흔적(회의·샘플러)은 그 끝을 흔적 시각으로 본다
            cand = [t for t in hum_a if w0 <= t <= first]
            cand += [min(b, first) for a, b in hums_a if b > w0 and a <= first]
            seg = [(max(cand) if cand else first, last)]
        if needs_pc:
            seg = _intersect_spans(seg, _clip(pc_a, w0, w1))
        seg = _union_spans(seg)
        if not seg:
            continue
        opened = bool(unlock and (any(first < t <= w1 for t in hum_a)
                                  or any(first < t <= w1 for t in view_a)
                                  or any(b > first and a < w1 for a, b in hums_a)))
        if opened:
            st["unlocked"] += 1
        elif cap_h > 0 and _union_min(seg) > cap_h * 60 + 1e-9:
            seg, st["capped"] = _tail_clip(seg, cap_h * 60), st["capped"] + 1
        st["nights"] += 1
        for a, b in seg:                       # 자정을 넘는 구간은 날짜별로 분할해 각 날에 배분
            while b > a + 1e-9:
                k = int(a // 1440)
                edge = min(b, (k + 1) * 1440.0)
                dd = datetime.fromordinal(base + k).date()
                if d0 <= dd <= d1:
                    out.setdefault(dd, []).append((a - k * 1440.0, edge - k * 1440.0))
                    if opened:
                        free.add(dd)
                a = edge
    res = {}
    for dd, sp in out.items():
        sp = _union_spans(sp)
        if cap_h > 0 and dd not in free and _union_min(sp) > cap_h * 60 + 1e-9:
            sp = _tail_clip(sp, cap_h * 60)    # 한 날짜가 두 밤에 걸린 경우 — 날짜 합계에도 같은 상한
        res[dd] = sp
    return res, st


def _activity_spans(data_dir, d0, d1, interval_sec=60, idle_active=IDLE_ACTIVE_SEC):
    """창 샘플러 → (spans, cov_spans, stuck_days)
      spans      {date: [(분,분)]} 활동 구간(idle ≤ idle_active 샘플, 같은 창 제목 10분 이어붙임)
      cov_spans  {date: [(분,분)]} 샘플이 실제로 덮은 구간의 합집합(idle 샘플 포함, 샘플마다 (m, m+3×step)) —
                 샘플러가 켜지기 전·죽은 뒤·중간 공백은 여기 없다(A25 — 미커버 구간에만 PC 하한)
      stuck_days {date} 고착 판정(A1): 그날 샘플이 STUCK_COVER_H(14h) 이상을 덮는데 idle>0 인 샘플 비율이
                 STUCK_IDLE_RATIO(2%) 미만 — TickCount 랩(가동 24.9~49.7일)·원격 세션의 idle 0 고착. 그날은
                 spans·cov 에서 빼서 PC 하한 모드로 폴백한다(예전엔 ≥20h 를 '표시'만 하고 24h 를 계상했다)
    · 샘플 간격은 config 가 아니라 파일에서 실측(인접 간격 중앙값, ≤300s)한다 — 120s 로 돌린
      샘플러를 60s 로 가정하면 절반이 사라졌다(실측 E5).
    · idle ≤ idle_active(300s) 는 '읽는 중'도 활동. 같은 창 제목이 10분 안에 이어지면 붙인다 — idle 샘플에서도
      prev 를 유지해야 다음 활동 샘플이 잇는다(A24: 예전엔 idle 샘플이 prev 를 지워 실제로 붙은 적이 없었다).
    · 같은 시각 중복 샘플은 한 번만."""
    import statistics
    out, cov, stat = {}, {}, {}
    for f in _glob_multi(data_dir, "activity", "activity_*.csv"):
        rows, seen = [], set()
        for r in _read(f):
            t = _dt(r.get("time") or r.get("ts"))
            if not t or not (d0 <= t.date() <= d1) or t in seen:
                continue
            try:
                idle = float(r.get("idle_sec") or r.get("idle") or 0)
            except ValueError:
                continue                     # 강제종료로 열이 밀린 행 — 활동으로 세지 않는다
            seen.add(t)
            rows.append((t, idle, (r.get("title") or "")[:70]))
        rows.sort(key=lambda x: x[0])
        deltas = [(rows[i + 1][0] - rows[i][0]).total_seconds() for i in range(len(rows) - 1)
                  if 0 < (rows[i + 1][0] - rows[i][0]).total_seconds() <= 600]
        step = statistics.median(deltas) if deltas else float(interval_sec)
        step = min(300.0, max(float(interval_sec), step))
        prev = None
        for t, idle, title in rows:
            dd = t.date()
            m = t.hour * 60 + t.minute + t.second / 60.0
            cov.setdefault(dd, []).append((m, min(1440.0, m + 3 * step / 60.0)))
            s = stat.setdefault(dd, [0, 0])
            s[0] += 1
            s[1] += 1 if idle > 0 else 0
            if idle > idle_active:
                # 같은 창을 계속 보고 있는 동안(≤10분)은 prev 를 지우지 않는다 — 다음 활동 샘플이 a=prev[1] 로 잇는다
                if not (prev and prev[2] == title and prev[3] == dd and 0 <= m - prev[1] <= SAME_TITLE_BRIDGE_MIN):
                    prev = None
                continue
            a, b = m, min(1440.0, m + step / 60.0)
            if (prev and prev[2] == title and prev[3] == dd
                    and 0 <= a - prev[1] <= SAME_TITLE_BRIDGE_MIN):
                a = prev[1]                  # 같은 창을 계속 보고 있었다 — 읽기 구간을 잇는다
            out.setdefault(dd, []).append((a, b))
            prev = (a, b, title, dd)
    stuck = set()
    for dd, (n, n_pos) in stat.items():
        if n and _union_min(cov[dd]) >= STUCK_COVER_H * 60 and n_pos / n < STUCK_IDLE_RATIO:
            stuck.add(dd)
            out.pop(dd, None)
            cov.pop(dd, None)
    for dd in list(cov):
        cov[dd] = _union_spans(cov[dd])
    return out, cov, stuck


def _meeting_skip(r, tentative="count"):
    """캘린더 행을 '참석'으로 볼 수 없는 사유(문자열) 또는 None. 신호 필터(load_signals)와
    시간 계상(_meeting_spans)이 같은 판정을 공유한다.
      busy_status  : 0 한가함(미수락·정보성) — 제외
      response     : Outlook ResponseStatus (0 없음/1 주최/2 미정/3 수락/4 거절/5 미응답) — 열이 있을 때만
      meeting_status: 5·7 = 취소된 회의 — 열이 있을 때만
      tentative    : "count"(기본) 미정(busy 1)도 계상 · "skip" 미정 제외 ·
                     "response" 응답 기준(미정·미응답·거절 제외, 열이 없으면 busy 1 제외)"""
    busy = str(r.get("busy_status") or "2").strip()
    resp = str(r.get("response") or "").strip()
    ms = str(r.get("meeting_status") or "").strip()
    if ms in ("5", "7"):
        return "취소된 회의(meeting_status)"
    if resp == "4":
        return "거절한 회의(response)"
    if busy == "0" and resp not in ("1", "3"):     # 주최(1)·수락(3)한 회의는 Free 표시라도 참석(A36)
        return "미수락 일정(한가함 상태)"
    # 미응답(5)·미정(2)·response 없는 busy 1 = '미정' 한 부류 — 설정(tentativeMeetings)이 판정한다(A17).
    # 수집 경로(COM 만 response 를 채움)에 따라 같은 캘린더가 달라지지 않도록 count 모드에서는 계상.
    pending = resp in ("2", "5") or (not resp and busy == "1")
    if tentative == "skip" and (pending or busy == "1"):
        return "미정 회의(tentativeMeetings=skip)"
    if tentative == "response" and pending:
        return "미정 회의(tentativeMeetings=response)"
    return None


def _meeting_spans(data_dir, d0, d1, nonwork, tentative="count", exclude=(), now=None, day_win=None):
    """returns (out, carried, accepted, blocks)
      out      {date: [(a,b)…]} 회의 구간(분). 다일·자정 넘김은 날짜별로 잘라 각 날 상한 = max(8h, 주간 창 길이)
               (A6 — 6/1 09:00→6/3 18:00 출장의 둘째 날이 사라지지 않는다; 12h 현장 08~20 은 창 길이까지)
      carried  자정(또는 기간 시작 전날)에서 넘어온 조각이 있는 날짜 — 익일이 주말이어도 수락 회의의 연속
      accepted 하한 게이트를 여는 '실제 회의' 가 있는 날짜(A19) — 열이 있으면 meeting_status 1·3 또는 response 1·3,
               열이 없으면 busy 2·3 폴백. '치과' 약속 1h 는 게이트를 열지 않는다
      blocks   {date: [(a, b, subject)]} 참석자 없는 약속(meeting_status 0 — 재택근무·출장·개인 OOF 블록)과 상태를
               알 수 없는 4h 이상 블록(폴백 경로, 출장·교육 키워드가 없을 때) — 회의 시간이 아니다. day_work_hours 가
               오프사이트 폴백 근거로만 쓴다(A19)
    개인정보 제외어(exclude, load_signals 와 같은 규칙)·비업무·취소/거절/한가함/설정상 미정은 시간이 아니다.
    end ≤ start(역행·시각 오류)·종일 일정은 버리고, now 이후(아직 열리지 않은 회의)는 잘라낸다."""
    out, carried, accepted, blocks = {}, set(), set(), {}
    hit = _text_filter(exclude)
    now = (now or datetime.now()) + _td(minutes=FUTURE_SLACK_MIN)
    dw = day_win or DAY_WIN
    cap_single = max(8 * 60.0, float(dw[1] - dw[0]))   # 하루짜리 긴 일정(12h 현장 08~20)은 주간 창 길이까지
    cap_multi = 8 * 60.0                                # 다일 일정(출장·교육 6/1 09:00→6/3 18:00)은 각 날 8h
    for r in _read_multi(data_dir, "outlook", "calendar.csv"):
        t0, t1 = _dt(r.get("start")), _dt(r.get("end"))
        subj_raw = (r.get("subject") or "").strip()
        subj = subj_raw.lower()
        if _nonwork_hit(subj, nonwork) or _meeting_skip(r, tentative) or hit(subj):
            continue                       # 취소·연차·미수락·거절·개인정보 일정은 업무 시간이 아니다
        if not (t0 and t1 and t1 > t0) or _truthy(r.get("all_day")):
            continue
        if not (d0 <= t1.date() and t0.date() <= d1):     # 기간 시작 전날 밤 회의의 당일 조각도 남긴다(A36)
            continue
        busy = str(r.get("busy_status") or "2").strip()
        resp = str(r.get("response") or "").strip()
        ms = str(r.get("meeting_status") or "").strip()
        # 미수락 교육은 시간 계상에서도 뺀다 — 신호 필터(load_signals)와 판정 일치
        if _edu_unaccepted(r, subj, busy):
            continue
        dur_min = (t1 - t0).total_seconds() / 60
        is_block = _is_block_row(r, subj)      # 약속(ms 0)·상태 없는 5h 초과 비키워드 블록 — 회의 시간이 아니다
        cap = cap_multi if dur_min > 1440 else cap_single
        if ms or resp:
            acc = ms in ("1", "3") or resp in ("1", "3")
        else:
            acc = busy in ("2", "3")
        cur, first = t0, True
        while cur < t1:
            dd = cur.date()
            nxt = datetime(dd.year, dd.month, dd.day) + _td(days=1)
            seg_end = min(t1, nxt)
            if cur > now:
                break
            if d0 <= dd <= d1:
                a = cur.hour * 60 + cur.minute + cur.second / 60.0
                b = 1440.0 if seg_end == nxt else seg_end.hour * 60 + seg_end.minute + seg_end.second / 60.0
                if seg_end > now:              # 진행 중인 회의는 지금까지만
                    b = min(b, now.hour * 60 + now.minute + now.second / 60.0)
                if b - a > cap:                # 긴 조각은 주간 창과 겹치는 부분(없으면 시작부터 상한)만
                    ca, cb = max(a, float(dw[0])), min(b, float(dw[1]))
                    a, b = (ca, cb) if cb > ca else (a, a + cap)
                    if b - a > cap:
                        b = a + cap
                if b > a:
                    if is_block:
                        blocks.setdefault(dd, []).append((a, b, subj_raw))
                    else:
                        out.setdefault(dd, []).append((a, b))
                        if acc:
                            accepted.add(dd)
                        if not first:
                            carried.add(dd)    # 익일이 주말이어도 이 조각은 수락 회의의 연속
            cur, first = seg_end, False
    return out, carried, accepted, blocks


def _signal_spans(signals, d0, d1, mins=None, now=None, extra=None, gap=None, day_win=None,
                  passive_max_min=None, stats=None):
    """신호 타임스탬프 → 세션 구간. returns ({date: [(a,b)]}, 미래 시각으로 폐기한 신호 수)
    · 흩어진 신호는 각자 최소 작업시간(LONE_SIGNAL_MIN)을 시각 앞뒤로 대칭 배치한다.
      목록(signalMinutes)에 없는 라벨은 세션을 만들지 않는다(A18 — 예전 기본 10분).
    · 야간(19~08시)의 수동 신호(수신 메일·CC·팀즈 수신)는 세션을 만들지 않는다 —
      '야간은 산출물이 있을 때만'이라는 원칙.
    · 수동 신호는 세션 간격(gap, 기본 SESSION_GAP_MIN)으로 서로 다리를 놓지 않는다 — 능동 흔적끼리만.
      수동 신호만으로 만든 세션은 하루 합계 passive_max_min(기본 PASSIVE_DAY_MAX_MIN=60, config.mm.passiveDayMaxMin)
      까지만 남긴다(A18 — 연차·PC 없는 날 수신 30통이 3h 가 되던 과대). stats(dict) 를 주면
      stats["passive_capped_days"] 에 상한이 걸린 날 수를 채운다.
    · now+5분 이후 시각(시계 오류·타임존) 은 폐기하고 센다. '파일(일괄)' 은 시간 근거가 아니다.
    · extra = {date: [(분, code)]} 표본화 전 전체 파일 시각(시간 재료로만 합친다) — 표본 신호와 같이
      signalMinutes 가 0 이하면 세션을 만들지 않는다(파일 세션을 설정으로 끌 수 있어야 한다).
      code "sim"(해석 출력 뭉치의 시작 분 anchor, VF-H1)은 기계가 쓴 시각이라 야간이면 건너뛴다(밤새 돌린 솔버 ≠ 야근) —
      주간이면 예전처럼 파일 1건의 세션(해석을 돌린 날의 흔적).
    · gap·day_win 은 인자로 받는다 — 모듈 전역을 고치지 않는다(재진입 안전)."""
    now = (now or datetime.now()) + _td(minutes=FUTURE_SLACK_MIN)
    mins = mins or LONE_SIGNAL_MIN
    gap = float(SESSION_GAP_MIN) if gap is None else float(gap)
    passive_max = PASSIVE_DAY_MAX_MIN if passive_max_min is None else float(passive_max_min)
    by_day, dropped = {}, 0
    for t, src, _x, _w, _who in signals:
        if not (d0 <= t.date() <= d1):
            continue
        if t > now:
            dropped += 1
            continue
        if src == "파일(일괄)" or mins.get(src, 0) <= 0:
            continue
        if _is_night(t, day_win) and src not in NIGHT_PRODUCTIVE and src != "회의":
            continue
        by_day.setdefault(t.date(), []).append((t.hour * 60 + t.minute, src))
    for d, lst in (extra or {}).items():
        if not (d0 <= d <= d1):
            continue
        day0 = datetime(d.year, d.month, d.day)
        for m, code in lst:
            if _sim_end(code) is not None:
                if _is_night(day0 + _td(minutes=m), day_win):
                    continue                     # 해석 출력 anchor 의 야간 시각 — 세션 재료가 아니다(VF-H1·S4-N1)
                label = "파일"
            else:
                label = "파일(코드)" if code else "파일"
            if mins.get(label, 0) <= 0 or day0 + _td(minutes=m) > now:
                continue
            by_day.setdefault(d, []).append((m, label))
    out, capped_days = {}, 0
    for d, items in by_day.items():
        items.sort()
        spans, cur = [], None
        for m, src in items:
            lone = mins.get(src, 0)
            half = max(2.5, lone / 2)
            a, b = m - half, m + half
            active = src in ACTIVE_SRC
            if cur:
                g = gap if (active and cur[2]) else 0.0
                if a - cur[1] <= g:
                    # 시작도 함께 확장한다 — 신호 종류마다 폭(half)이 2.5~45분으로 달라
                    # 뒤 신호의 a 가 cur[0] 보다 앞설 수 있다. 끝만 늘리면 그 앞부분이 잘려
                    # '신호를 더 넣을수록 시간이 줄어드는' 비단조 과소계상이 된다.
                    cur = (min(cur[0], a), max(cur[1], b), cur[2] or active)
                    continue
                spans.append(cur)
            cur = (a, b, active)
        if cur:
            spans.append(cur)
        # 자정 클램프 — 00시 직후 신호가 음수 분(전날)으로, 24시 직전이 1440분 초과로 새지 않게.
        # 수동만으로 만든 세션(ac=False)은 일 합계 passive_max 까지만(A18).
        res, pas, capped = [], 0.0, False
        for a, b, ac in spans:
            a, b = max(0.0, a), min(1440.0, b)
            if b <= a:
                continue
            if not ac and passive_max >= 0:
                room = passive_max - pas
                if room <= 1e-9:
                    capped = True
                    continue
                if b - a > room:
                    b, capped = a + room, True
                pas += b - a
            res.append((a, b))
        out[d] = res
        capped_days += 1 if capped else 0
    if stats is not None:
        stats["passive_capped_days"] = capped_days
    return out, dropped


def _utc_suspect(data_dir, d0, d1, offset_h=0.0):
    """발신(메일 sent + 팀즈 kind=sent, A27)의 60% 이상이 00~08시면 시각이 UTC 로 기록된 것으로 의심
    (웹·Copilot·Graph 수집 경로). 낮 발신이 새벽 '야근'으로 옮겨가는 구조적 오류 — 경고만 하고
    config.mm.mailTimeOffsetH 로 보정한다(보정값을 적용한 뒤의 시각으로 판정하므로 offset 을 맞추면 경고가 사라진다).
    날짜만 아는 행(time_precision=date)은 판정에서 뺀다."""
    n = k = 0
    rows = [r for r in _read_multi(data_dir, "outlook", "mail.csv") if r.get("box") == "sent"
            and (r.get("time_precision") or "").strip().lower() != "date"]
    for p in _glob_multi(data_dir, "m365", "teams_*.csv"):
        rows += [r for r in _read(p) if (r.get("kind") or "").strip().lower() == "sent"]
    for r in rows:
        t = _dt(r.get("time"))
        if not t:
            continue
        if offset_h:
            t = t + _td(hours=offset_h)
        if not (d0 <= t.date() <= d1):
            continue
        n += 1
        k += 1 if t.hour < 8 else 0
    return bool(n >= 5 and k / n >= 0.6)


def day_work_hours(data_dir, signals, d0, d1, cfg=None, now=None, file_times=None):
    """투입 시간 = 그날 활동 흔적(회의·창 샘플러·신호 세션) 구간의 합집합 + PC 가동 구간 하한(구간 단위, A3).
    method="workday" 로 두면 예전처럼 '평일이면 표준 8h'로 계산한다(비교용).
      now        : 미래 시각 판정 기준(테스트용, 기본 datetime.now())
      file_times : load_signals meta["file_times"] — 표본화 전 전체 파일 시각(없으면 직접 읽는다)
    returns ({date: 투입시간h}, info) — info 키는 기존 키를 유지하고 추가만 한다.

    LM22 2차(시간 쪽) 규칙 요약:
      · PC 하한(A3)   : 주간 창을 세 조각으로 나눈다 — PC 가동 창 밖 흔적(그대로 더함) · 샘플러가 덮은 구간(실측) ·
                       샘플러가 덮지 않은 PC 가동 구간(하한). 하한 = 가동 구간(pc_spans ∩ 주간 창, 없으면 first_on~last_off)
                       − 점심·저녁 공백(흔적 ±5분이 없을 때만) − 설명되지 않는 절전 공백(가동 창 − on 중 점심·회의로
                       설명되지 않는 만큼). PC 가 꺼진 시간의 수락 회의는 흡수되지 않고 더해진다.
      · 창 다듬기(A33): 가동 창 양끝 trimIdleEdgesMin 분 안에 흔적이 없으면 그만큼 안쪽으로(출퇴근 전후 켜 둔 PC).
      · 항상 켜진 PC  : first_on≤0·last_off≥24:00 또는 on≥20h — 가동 창 대신 '첫 능동 흔적 −30 ~ 마지막 +30'.
      · PC 기록 없음(A9): pcFloorFallback=trace 면 능동 흔적·회의의 첫 −30 ~ 마지막 +30 ∩ 주간 창(점심 차감, 표준일 상한).
      · 샘플러(A25·D3): 미커버 구간에만 하한(50% 문턱 절벽 없음) · 가동 창 안 ≤samplerGapBridgeMin 공백은 근무(점심 제외).
      · 종일 행사(A6)·수동 기록(A13): 표준일×(1−부재)·기록 시간을 하한으로, 능동 흔적, 부재 추정 제외.
      · 시차 근무(D4) : 산출물 없어도 주간 창 밖 PC 가동을 앞뒤 각 flexEdgeH 까지(야간 합 ≤ PC night).
      · 주말 "pc"(D7) : weekendWindow="pc" 면 능동 흔적이 있는 주말은 평일과 같은 PC 하한.
      · 부재 추정(A31): 투입 ≤15분·PC ≤30분·능동 흔적 없음(수신 1통·유지관리 깨움 허용).
      · 야간 해석(S4-N1): 밤새 돌린 솔버(ANSYS·Zemax·CFD…)의 출력 뭉치를 근무로 인정한다 — mm.simNight
                       span(제출~마지막 출력 구간, 기본) · anchor(뭉치당 30분) · off(게이트만, 시간 0).
                       상한 mm.simNightCapH(밤당 4h, 0=무제한) · 첫 출력 뒤 사람 흔적이 있으면 상한 해제
                       (simNightHumanUnlock) · mm.simNightNeedsPc=true 면 내 PC 야간 가동과 겹치는 만큼만.
                       PC 가 꺼져 있어도 인정하므로 저녁·새벽 크레딧의 '야간 합 ≤ PC night' 캡 계산에서는 제외한다.
    info 새 키: sampler_stuck_days(A1)·offsite_days·offsite_h·manual_days·manual_h·dinner_deducted_h·flex_edge_h·
      sampler_bridge_h·passive_capped_days·weekend_pc_days·pc_record_missing_days·pc_record_days·trace_window_h·
      trace_window_days·pc_coverage_by_month{YYYY-MM:비율}·always_on_days·measure·coverage·cfg_used(D5)·
      sim_night_h·sim_night_days·sim_night_capped_days·sim_night_unlocked_days·sim_night_remote_h(S4-N1)"""
    from datetime import timedelta
    cfg = cfg if isinstance(cfg, dict) else {}
    mc, cfg_warns = norm_cfg(cfg)            # 잘못된 설정값은 죽지 않고 기본값 + info["config_warnings"]
    std = mc["standardDayHours"]
    method = mc["method"]
    use_pc_floor = mc["usePcFloor"]
    floor_needs = mc["pcFloorNeeds"]                                    # active | any
    tentative = mc["tentativeMeetings"]                                 # count | skip | response
    infer_abs = mc["inferAbsence"]
    weekend_win = mc["weekendWindow"]                                   # True | "pc" | False (D7c)
    weekend_pc = weekend_win == "pc"
    evening_credit = mc["eveningCredit"]
    span_all_files = mc["spanFromAllFiles"]
    sim_mode = mc["simNight"]                                           # span | anchor | off (S4-N1)
    sim_cap_h = mc["simNightCapH"]
    sim_unlock = mc["simNightHumanUnlock"]
    sim_needs_pc = mc["simNightNeedsPc"]
    # 창·간격은 지역 변수다 — 예전엔 모듈 전역(DAY_WIN·LUNCH·SESSION_GAP_MIN)을 덮어써서 같은
    # 프로세스의 다음 호출(UI·테스트)에 설정이 새어 나갔다(재진입 안전).
    day_win, lunch, gap = mc["dayWindow"], mc["lunch"], mc["sessionGapMin"]
    dinner = mc["dinner"]
    day_cap = mc["dayCapHours"]
    mail_off = mc["mailTimeOffsetH"]
    bridge_min = mc["samplerGapBridgeMin"]
    flex_h = mc["flexEdgeH"]
    trim_min = mc["trimIdleEdgesMin"]
    fallback = mc["pcFloorFallback"]
    offsite_on = mc["offsiteAsWork"]
    dw0, dw1 = float(day_win[0]), float(day_win[1])
    # PC 주간 가동 하한의 상한 — 수집기 야간 경계(08/19시)의 11h 와 주간 창 길이 중 작은 쪽. 창을 줄이면
    # (09~18시) 창보다 긴 하한이 걸리던 결함 방지. 창이 수집기 경계와 다르면 한 줄 경고를 남긴다
    # (PC night 는 수집기 경계로 적산돼 있어 창 밖 시간의 크레딧·물리 한계가 정확하지 않다).
    day_max_h = min(PC_DAY_MAX_H, (dw1 - dw0) / 60.0)
    if tuple(day_win) != tuple(DAY_WIN):
        cfg_warns.append(f"mm.dayWindow {_fmt_hm(day_win[0])}-{_fmt_hm(day_win[1])} 는 수집기 야간 경계"
                         f"({_fmt_hm(DAY_WIN[0])}-{_fmt_hm(DAY_WIN[1])})와 다름 — PC 주간 가동 하한을 "
                         f"{day_max_h:g}h 로 제한하지만 24h 물리 한계 보장·저녁 크레딧 정확도는 떨어진다")
    nonwork = _nonwork_list(cfg)
    exclude = cfg_list(cfg, "excludePathKeywords")
    anomalies, _anom_idx = [], {}

    def _anom(d, kind, raw=None, used=None):
        k = d.isoformat()
        if k in _anom_idx:                     # 하루 한 줄 — 종류만 잇는다
            a = anomalies[_anom_idx[k]]
            a["kind"] += " · " + kind
            if used is not None:
                a["used"] = used
            return
        _anom_idx[k] = len(anomalies)
        anomalies.append({"date": k, "kind": kind, "raw": raw, "used": used})

    # ── PC 가동 기록(pc_on.csv + pc_spans.csv, 본 PC + 추가PC/*) — 날짜별 병합은 pc_daily 한 곳에서 한다(화면의 주간 추이
    #    PC 선도 같은 함수). 여러 PC 의 구간은 합집합, 구간 없는 행은 (주간·야간) max(A32) — 제보: 'PC 가동시간 합산 안 됨'. ──
    span_anoms = []
    pc, pc_wins, pc_spans, pc_win_all = pc_daily(data_dir, d0, d1, day_win=day_win, anom=_anom, span_anoms=span_anoms)
    for dd, kind in span_anoms:
        _anom(dd, kind, None, None)
    act, cov, stuck = _activity_spans(data_dir, d0, d1, interval_sec=mc["samplerIntervalSec"],
                                      idle_active=mc["idleActiveSec"])
    meets, meet_carry, accepted, blocks = _meeting_spans(
        data_dir, d0, d1, nonwork, tentative, exclude=exclude, now=now, day_win=day_win)
    # 약속(ms 0) 블록 중 출장·현장·교육 키워드가 든 것은 그 시간만큼 근무(A19 — 오프사이트 폴백 근거). '재택근무'·'치과' 는 아니다.
    off_kws = _offsite_kws(cfg)
    blk = {}
    for dd, lst in blocks.items():
        for a, b, subj in lst:
            if any(k in (subj or "").lower() for k in off_kws):
                blk.setdefault(dd, []).append((a, b))
    offsite = offsite_days(data_dir, d0, d1, cfg, exclude) if (offsite_on and method == "activity") else {}
    manual = manual_hours(data_dir, d0, d1)
    mins = mc["signalMinutes"]
    extra = None
    if span_all_files and method == "activity":
        extra = (file_times if file_times is not None
                 else _file_times(data_dir, d0, d1, exclude, cfg)[0])
    sstats = {}
    sess, future_dropped = _signal_spans(signals, d0, d1, mins, now=now, extra=extra, gap=gap, day_win=day_win,
                                         passive_max_min=mc["passiveDayMaxMin"], stats=sstats)
    abs_spans = {}
    absence = absence_days(data_dir, d0, d1, spans=abs_spans)
    holidays = _holiday_set(cfg)
    hours, inferred = {}, {}
    cal_n = 0
    for r in _read_multi(data_dir, "outlook", "calendar.csv"):
        t = _dt(r.get("start"))
        if t and d0 <= t.date() <= d1:
            cal_n += 1
    # 화면의 '부재 N일 차감'은 실제로 가용에서 빠지는 평일만 센다 — 연차 기간에 낀 주말은 차감 대상이 아니다
    info = {"absence_days": round(sum(v for dd, v in absence.items() if not _is_off_day(dd, holidays)), 1),
            "overtime_h": 0.0, "gap_days": 0,
            "weekend_days": 0, "night_days": 0, "no_evidence_days": 0, "holidays": 0,
            "sampler_days": len(act), "method": method,
            "pc_floor_h": 0.0, "pc_floor_days": 0,
            # ── LM22 추가(기존 키는 위에 그대로) ──
            "floor_blocked_passive_days": 0, "lunch_deducted_h": 0.0, "evening_credit_h": 0.0,
            "weekend_window_h": 0.0, "sampler_partial_days": 0, "sampler_stuck_days": len(stuck),
            "inferred_absence_days": 0, "future_signals_dropped": future_dropped,
            "phys_cap_days": 0, "day_cap_days": 0, "day_cap_hours": day_cap,
            "absent_worked_h": 0.0, "long_days": [], "anomalies": anomalies,
            "utc_suspect": _utc_suspect(data_dir, d0, d1, mail_off),
            "config_warnings": cfg_warns,
            # ── LM22 2차(A6·A9·A13·A18·A33·D3·D4·D7·D5) ──
            "offsite_days": 0, "offsite_h": 0.0, "manual_days": 0, "manual_h": 0.0,
            "dinner_deducted_h": 0.0, "flex_edge_h": 0.0, "sampler_bridge_h": 0.0,
            "passive_capped_days": int(sstats.get("passive_capped_days", 0)), "weekend_pc_days": 0,
            "pc_record_missing_days": 0, "pc_record_days": 0, "trace_window_h": 0.0, "trace_window_days": 0,
            "pc_coverage_by_month": {}, "always_on_days": 0,
            # ── S4-N1: 야간 해석(솔버) 근무 인정 — 밤(야간 창) 단위로 센다 ──
            "sim_night_h": 0.0, "sim_night_days": 0, "sim_night_capped_days": 0,
            "sim_night_unlocked_days": 0, "sim_night_remote_h": 0.0,
            "basis": ""}
    for dd in sorted(stuck):
        if d0 <= dd <= d1:
            _anom(dd, "샘플러 idle 0 고착(TickCount 랩·원격 세션) — 그날 샘플러 폐기, PC 하한 모드", None, None)
    # 능동 산출물(파일·코드·커밋·발신·수동기록) 시각 — 주말 근거·저녁 크레딧·PC 하한 게이트·흔적 창의 재료.
    # tp = 모든 신호 시각(수동 포함) — 점심·저녁·창 가장자리의 '흔적 ±5분' 판정(A33).
    # sim_days = 해석 출력 뭉치(대표 '파일(해석출력)'·anchor code "sim")가 있는 날 — 기계가 쓴 시각이라 하한 게이트(active_day)만
    # 열고, 주간 창 안의 시각만 산출물·흔적으로 쓴다(VF-H1: 밤새 돌린 솔버의 03:00 출력이 새벽 크레딧·흔적 창·자정 연속성의
    # 재료가 되던 과대 — '취침 중 켜둔 PC 를 근무로 세지 않는다').
    # sim_sp/hum_pt/view_pt = 야간 해석 인정(S4-N1)의 재료 — 해석 출력 뭉치의 (시작, 끝) · 사람 능동 흔적 시각 ·
    # 열람만 한 흔적(상한 해제 판정에만 쓴다). '파일(해석출력)' 자신은 사람 흔적이 아니다.
    prod, tp, sim_days = {}, {}, set()
    sim_sp, hum_pt, view_pt = {}, {}, {}
    now_lim = (now or datetime.now()) + timedelta(minutes=FUTURE_SLACK_MIN)   # 미래 시각(시계 오류)은 흔적이 아니다
    for t, src, _x, _w, _who in signals:
        if not (d0 <= t.date() <= d1) or t > now_lim:
            continue
        m = t.hour * 60 + t.minute
        if src == "파일(해석출력)":
            sim_days.add(t.date())
            sim_sp.setdefault(t.date(), []).append((float(m), float(m)))
            if dw0 <= m < dw1:
                prod.setdefault(t.date(), []).append(m)
                tp.setdefault(t.date(), []).append(m)
            continue
        if src != "회의":                       # 회의는 캘린더 구간(meets)이 정확한 흔적이다 — 시작 시각 ±5분을 덧붙이지 않는다
            tp.setdefault(t.date(), []).append(m)
        if src in NIGHT_PRODUCTIVE:
            prod.setdefault(t.date(), []).append(m)
        if src in ACTIVE_SRC:
            hum_pt.setdefault(t.date(), []).append(float(m))
        elif src == "파일(열람)":
            view_pt.setdefault(t.date(), []).append(float(m))
    for dd, lst in (extra or {}).items():
        if d0 <= dd <= d1 and lst:
            day0 = datetime(dd.year, dd.month, dd.day)
            ok = []
            for m, c in lst:
                if day0 + timedelta(minutes=m) > now_lim:
                    continue
                end = _sim_end(c)
                if end is not None:              # 해석 출력 anchor — 대표 신호와 같은 규칙(게이트만, 주간 창 안일 때만 산출물)
                    sim_days.add(dd)
                    sim_sp.setdefault(dd, []).append((float(m), min(1440.0, max(float(m), end))))
                    if not (dw0 <= m < dw1):
                        continue
                else:
                    hum_pt.setdefault(dd, []).append(float(m))   # 표본에서 빠진 사람 저장 파일도 제출 흔적이다
                ok.append(m)
            if ok:
                prod.setdefault(dd, []).extend(ok)
                tp.setdefault(dd, []).extend(ok)

    def _night_zone(sp):
        return _clip(sp, 0, dw0) + _clip(sp, dw1, 1440)

    # 자정 연속성 — 수집기는 자정에 하루를 끊는다(전날 last_off 24:00 · 당일 first_on 00:00). PC 가 자정을
    # 넘겨 켜져 있고 양쪽에 야간 산출물이 있으면 그 자정은 경계가 아니라 한 세션의 한가운데다
    # (야간 근무자 20~04시: 전날 저녁 크레딧은 24:00 까지, 당일 새벽 크레딧은 00:00 부터).
    def _night_prod(dd, evening):
        return any((m >= dw1) if evening else (m < dw0) for m in (prod.get(dd) or ()))

    def _pc_row(dd):
        """pc_on 행(없으면 pc_spans 에서 파생) → (on, night, first_on, last_off)"""
        row = pc.get(dd)
        sp = pc_spans.get(dd)
        if row is None and sp:
            return (_union_min(sp) / 60.0, _union_min(_night_zone(sp)) / 60.0, sp[0][0], sp[-1][1])
        return row or (0.0, 0.0, None, None)

    def cont_next(dd):
        nd = dd + timedelta(days=1)
        r0, r1 = _pc_row(dd), _pc_row(nd)
        return bool(r0[1] > 0 and r1[1] > 0
                    and r0[3] is not None and r0[3] >= 1440 and r1[2] is not None and r1[2] <= 0
                    and _night_prod(dd, True) and _night_prod(nd, False))

    def cont_prev(dd):
        return cont_next(dd - timedelta(days=1))
    # PC 로그 생존 여부(월별) — 롤오버로 통째로 빈 달에는 부재 추정을 하지 않고, 월별 비율은 리포트 배지(A9)로 나간다
    pc_alive = {}
    d = d0
    while d <= d1:
        if not _is_off_day(d, holidays):
            k = d.strftime("%Y-%m")
            n, m = pc_alive.get(k, (0, 0))
            # 종일 행사·수동 기록일은 PC 기록이 있는 날과 같이 센다 — 현장 근무자가 'PC 기록 40% 미만' 으로 오인되지 않게
            has_pc = (pc.get(d, (0.0,))[0] > 0 or bool(pc_spans.get(d)) or d in offsite or d in manual)
            pc_alive[k] = (n + 1, m + (1 if has_pc else 0))
        d += timedelta(days=1)
    info["pc_coverage_by_month"] = {k: round(m / n, 2) for k, (n, m) in sorted(pc_alive.items()) if n}
    info["pc_record_days"] = sum(m for _n, m in pc_alive.values())
    # ── 야간 해석(솔버) 인정(S4-N1) — 한 밤이 자정을 넘어 두 날짜에 걸치므로 하루씩 도는 아래 루프 안에서는
    #    만들 수 없다. 밤 단위로 미리 인정 구간을 계산해 두고 루프는 그날 몫만 합집합으로 더한다. ──
    sim_night, sim_stat = {}, {"nights": 0, "capped": 0, "unlocked": 0}
    if sim_mode != "off" and method == "activity" and sim_sp:
        pc_night = {}
        for dd in set(pc_spans) | set(pc_wins):
            nz = _night_zone(pc_spans.get(dd) or _union_spans(pc_wins.get(dd) or []))
            if nz:
                pc_night[dd] = nz
        hum_sp = {dd: _union_spans(list(meets.get(dd, [])) + list(act.get(dd, [])))
                  for dd in set(meets) | set(act)}
        sim_night, sim_stat = _sim_night_credit(sim_sp, hum_pt, hum_sp, view_pt, pc_night, d0, d1, day_win,
                                                mode=sim_mode, cap_h=sim_cap_h, unlock=sim_unlock,
                                                needs_pc=sim_needs_pc)
    info["sim_night_days"] = sim_stat["nights"]
    info["sim_night_capped_days"] = sim_stat["capped"]
    info["sim_night_unlocked_days"] = sim_stat["unlocked"]
    gap_run = []
    d = d0
    while d <= d1:
        off = _is_off_day(d, holidays)
        absent = absence.get(d, 0.0)
        has_pc_row = d in pc
        on, night, first_on, last_off = _pc_row(d)
        pcs = pc_spans.get(d) or []
        raw_day = max(0.0, on - night)
        day_on = min(day_max_h, raw_day)             # 주간창 ≤11h — worked ≤ 11 + 야간 13 = 24 보장
        if raw_day > PC_DAY_MAX_H + 1e-9:
            _anom(d, f"PC 주간 가동 {raw_day:g}h > {PC_DAY_MAX_H:g}h(야간열 누락 추정)",
                  [on, night], [day_on, night])
        off_blk = list(blk.get(d, []))
        if off_blk:
            # 하루짜리(≥6h) 행사 블록('협력사 현장 출장 09~18')은 점심을 덮는다 — 흔적이 없는 점심 부분은 뺀다(표준일 8h 와 일치)
            tr0 = ([(m - TRACE_PAD_MIN, m + TRACE_PAD_MIN) for m in tp.get(d, [])]
                   + list(meets.get(d, [])) + list(act.get(d, [])))
            lunch_gap0 = _subtract_spans([tuple(lunch)], tr0)
            off_blk = [s for a, b in off_blk
                       for s in (_subtract_spans([(a, b)], lunch_gap0)
                                 if (b - a >= 6 * 60 and a <= lunch[0] and b >= lunch[1]) else [(a, b)])]
        is_offsite = d in offsite and absent < 1.0
        is_manual = d in manual
        active_day = ((d in prod) or (d in sim_days) or (d in accepted) or bool(act.get(d)) or bool(off_blk)
                      or is_offsite or is_manual)
        spans = list(act.get(d, [])) + list(meets.get(d, [])) + list(sess.get(d, [])) + list(off_blk)
        if off and not active_day:
            # 주말·공휴일은 능동 흔적(산출물·수락 회의·샘플러)이 있는 날만 — 수신 메일 1통은 근무가 아니다.
            # 자정을 넘어 이어진 회의 조각(수락 회의의 연속)은 남긴다 — 버리면 금요일 심야→
            # 토요일 새벽 회의의 새벽분이 조용히 소실된다(검증 확정)
            spans = list(meets.get(d, [])) if d in meet_carry else []
        # 흔적 폭(A33): 신호 시각 ±5분 + 회의·샘플러·행사 블록 구간 — 점심·저녁·창 가장자리 판정에 쓴다(세션 꼬리 ±30분은 아니다)
        trace_sp = ([(m - TRACE_PAD_MIN, m + TRACE_PAD_MIN) for m in tp.get(d, [])]
                    + list(meets.get(d, [])) + list(act.get(d, [])) + list(off_blk))
        # PC 가동 창 — pc_spans 가 있으면 그 구간, 없으면 pc_on 행별 first_on~last_off 의 합집합(두 PC 면 두 구간, VF-H9).
        # 양끝 다듬기(A33 trimIdleEdgesMin).
        # 여러 PC 가 섞인 날은 실제 구간 ∪ 구간 없는 PC 의 창(pc_win_all)을 예전 창에 **더한다** — 가동 시간(pc_daily)과 같은
        # 재료로 하한 창을 만들되 예전 창보다 좁아지지는 않게(창 길이보다 on 이 큰 잘못된 행의 창도 예전엔 창에 들어갔다)
        pc_win = list(pcs) if pcs else _union_spans(pc_wins.get(d) or [])
        if pc_win_all.get(d):
            pc_win = _union_spans(list(pc_win) + list(pc_win_all[d]))
        always_on = (on >= 20.0 or (first_on is not None and last_off is not None
                                    and first_on <= 0 and last_off >= 1440))
        if pc_win and trim_min > 0 and not always_on:
            pc_win = _trim_edges(pc_win, trace_sp, trim_min)
        t_first = pc_win[0][0] if pc_win else first_on
        t_last = pc_win[-1][1] if pc_win else last_off
        # 주말 하한 모드(D7c): weekendWindow="pc" 이고 능동 흔적이 있으면 평일과 같은 규칙
        floor_day = (not off) or (weekend_pc and active_day and bool(pc_win))
        # ── 주말·공휴일 산출물 창: PC 가동을 '첫 산출물−30분 ~ 마지막 산출물+30분' 안에서만 인정 ──
        if (weekend_win and not floor_day and off and d in prod and on > 0 and t_first is not None
                and t_last is not None and not act.get(d)):
            win = (t_first if cont_prev(d) else max(t_first, min(prod[d]) - NIGHT_PAD_H * 60),
                   t_last if cont_next(d) else min(t_last, max(prod[d]) + NIGHT_PAD_H * 60))
            wins = [win] if win[1] > win[0] else []
            # 창 안의 점심(≥30분)에 흔적(신호 ±5분·회의·샘플러)이 없으면 그 부분은 뺀다(평일 하한과 같은 규칙, A35)
            if wins:
                lw = _intersect_spans(wins, [tuple(lunch)])
                if _union_min(lw) >= 30:
                    wins = _subtract_spans(wins, _subtract_spans(lw, trace_sp))
            if wins:
                before = _union_hours(spans)
                gain = min(on, _union_hours(spans + wins)) - before
                if gain > 0:
                    spans += wins
                    info["weekend_window_h"] += gain
        # ── 야간 해석(솔버) 인정(S4-N1): 그 밤의 실행 구간(제출 ~ 마지막 출력) 중 이 날짜 몫을 합집합으로 더한다.
        #    PC 가 꺼져 있어도 인정하므로(서버·클러스터) 아래 저녁·새벽 크레딧·시차 근무의 'PC 야간 가동' 여유에서는 뺀다.
        sim_add = []                           # 실제로 **더해진** 몫만 — 이미 다른 흔적이 덮은 시간은 야간 해석 인정분이 아니다
        if sim_night.get(d):
            gain_sp = _subtract_spans(sim_night[d], spans)
            gain = _union_min(gain_sp)
            if gain > 1e-9:
                spans += gain_sp
                sim_add = gain_sp
                info["sim_night_h"] += gain / 60.0
                pcn = _night_zone(pc_spans.get(d) or _union_spans(pc_wins.get(d) or []))
                info["sim_night_remote_h"] += _union_min(_subtract_spans(gain_sp, pcn)) / 60.0
        # ── 저녁·새벽 크레딧: 평일 야간 PC 가동을 '산출물 ±30분' 범위에서, **PC 가동 창(first_on~last_off)
        # 안에서만**, 야간 합계 ≤ PC 야간 가동으로 인정 (취침 중 켜둔 PC 는 마지막 산출물 뒤라 제외) ──
        #   · 저녁 = max(주간창 끝, first_on) ~ min(last_off, 마지막 야간 산출물+30) — 20시에 켰으면 20시부터
        #   · 새벽 = max(first_on, 첫 새벽 산출물−30) ~ min(주간창 시작, last_off) — 05시에 껐으면 05시까지
        #   · PC 가 자정을 넘겨 켜져 있고 양쪽에 야간 산출물이 있으면(야간 근무자) 자정은 경계가 아니다
        #   · 합계가 PC 야간 가동을 넘으면 산출물 쪽 끝은 두고 창 가장자리 쪽을 깎는다(_fit_credit)
        if evening_credit and not off and night > 0 and d in prod and t_last is not None:
            ev_last = max((m for m in prod[d] if m >= dw1), default=None)
            ev_first = min((m for m in prod[d] if m < dw0), default=None)
            credit = []                    # (a, b, 고정할 끝) — 'b' 저녁(끝 고정) · 'a' 새벽(시작 고정)
            if ev_last is not None:
                e_a = max(dw1, t_first if t_first is not None else dw1)
                e_b = min(t_last, 1440.0 if cont_next(d) else ev_last + NIGHT_PAD_H * 60)
                if e_b > e_a:
                    credit.append((e_a, e_b, "b"))
            if ev_first is not None and t_first is not None:
                m_a = max(t_first, 0.0 if cont_prev(d) else ev_first - NIGHT_PAD_H * 60)
                m_b = min(dw0, t_last)
                if m_b > m_a:
                    credit.append((m_a, m_b, "a"))
            if credit:
                # 야간 합계 ≤ PC 야간 가동 — 단 야간 해석 인정분(PC 밖에서도 인정)은 이 캡의 대상이 아니다
                allowed = night * 60 - _union_min(_subtract_spans(_night_zone(spans), sim_add))
                if allowed > 1e-9:
                    fitted = _fit_credit(credit, spans, allowed)
                    gain = _union_min(spans + fitted) - _union_min(spans)
                    if gain > 1e-9:
                        spans += fitted
                        info["evening_credit_h"] += gain / 60.0
        # ── 샘플러 공백 다리(D3a): 샘플러가 덮은 구간 안의 무입력 공백 중 ≤ bridge_min(점심·저녁 창 제외)은 근무 ──
        #   자리 토론·전화·즉석 회의(캘린더 없음)가 idle 로 버려지던 계통 과소. 장시간 이석·샘플러가 죽은 공백은 아니다.
        covered_all = cov.get(d) or []
        if act.get(d) and bridge_min > 0 and covered_all and (not off or floor_day):
            base_u = _union_spans(spans)
            skip_w = [tuple(lunch)]
            if night > 0 or (t_last is not None and t_last >= dinner[1]) or base_u[-1][1] >= dinner[1]:
                skip_w.append(tuple(dinner))
            bridged = []
            for i in range(1, len(base_u)):
                g = (base_u[i - 1][1], base_u[i][0])
                if g[1] - g[0] <= 1e-9:
                    continue
                if _union_min(_intersect_spans([g], covered_all)) < (g[1] - g[0]) - 1e-6:
                    continue                    # 샘플러가 없던 공백(죽음·절전) — 하한 블록이 맡는다
                eff = _subtract_spans([g], skip_w)
                if eff and _union_min(eff) <= bridge_min:
                    bridged += eff
            if bridged:
                gain = _union_min(spans + bridged) - _union_min(spans)
                if gain > 1e-9:
                    spans += bridged
                    info["sampler_bridge_h"] += gain / 60.0
        day_spans = _clip(spans, dw0, dw1)
        day_min = _union_min(day_spans)
        night_min = _union_min(_night_zone(spans))
        # 야간 해석 인정분을 뺀 야간 사용량 — 시차 근무(D4a)의 'PC 야간 가동' 여유를 잴 때만 쓴다(S4-N1)
        night_min_ex = _union_min(_subtract_spans(_night_zone(spans), sim_add)) if sim_add else night_min
        # ── PC 주간 가동 하한 (과소평가 보정) — 구간 단위(A3·A25·A9·A33·A35) ──────────
        # 신호 세션만으로는 '3시간 일하고 파일 1번 저장'이 1시간으로 계상된다. 그날 **능동** 흔적
        # (산출물·수락 회의·샘플러·행사·수동 기록)이 있으면 주간 투입을 PC 가동 구간으로 끌어올린다.
        #   · 흔적이 0인 날은 그대로 0 — 'PC 켜짐 = 근무'로 되돌아가지 않는다(v2 붕괴 원인)
        #   · 수동 신호(수신·CC)만 있는 날은 하한 미적용(pcFloorNeeds=active) — CC 1통이 10h 가 되던 과대
        #   · 점심·저녁 차감(그 시간에 흔적 ±5분이 있으면 그만큼 차감 안 함) · 반차는 표준일×(1−부재) 상한(흔적 초과분 인정)
        #   · 샘플러가 덮은 구간은 실측 우선, 덮지 않은 가동 구간만 하한 · 야간 PC 가동은 하한에 넣지 않는다
        #   · 야간 해석 인정분은 이 게이트를 열지 않는다(S4-N1) — 밤에 솔버가 돌았다는 것이 그날 **주간**에
        #     자리에 있었다는 근거는 아니다. 켜 둔 PC + 야간 해석만으로 주간 8h 가 붙던 것을 막는다.
        if (use_pc_floor and method == "activity" and floor_day and absent < 1.0
                and (day_min + night_min_ex) > 0):
            gate_ok = (floor_needs != "active") or active_day
            base, kind, gap_h, day_on_eff = [], None, 0.0, day_on
            if gate_ok:
                if pcs:
                    base = _clip(pc_win, dw0, dw1)
                    kind, day_on_eff = "spans", _union_min(base) / 60.0
                elif day_on > 0 and pc_win:
                    base = _clip(pc_win, dw0, dw1)
                    kind, gap_h = "window", max(0.0, _union_min(base) / 60.0 - day_on)
                elif day_on > 0:
                    base, kind, gap_h = [(dw0, dw1)], "nowin", max(0.0, (dw1 - dw0) / 60.0 - day_on)
                if base and always_on:
                    # 항상 켜 두는 PC(A3f): day_on 포화 대신 '첫 능동 흔적 −30 ~ 마지막 +30' 만
                    tw = _trace_window(prod.get(d, []), list(meets.get(d, [])) + list(act.get(d, [])) + list(off_blk))
                    base = _intersect_spans(base, _clip(tw, dw0, dw1))
                    kind, gap_h, day_on_eff = "always_on", 0.0, _union_min(base) / 60.0
                    info["always_on_days"] += 1
                if (not base and fallback == "trace" and not act.get(d) and not is_offsite and not is_manual
                        and ((d in prod) or (d in accepted) or off_blk)):
                    # PC 기록이 없는 날(A9): 흔적 창 [첫 능동 흔적 −30, 마지막 +30] ∩ 주간 창(표준일 상한).
                    # 종일 행사·수동 기록일은 PC 가 꺼진 게 당연하다 — 결측이 아니고 각자의 규칙(A6·A13)이 맡는다.
                    tw = _clip(_trace_window(prod.get(d, []), list(meets.get(d, [])) + list(off_blk)), dw0, dw1)
                    if tw:
                        base, kind, day_on_eff = tw, "trace", _union_min(tw) / 60.0
                        if not has_pc_row:
                            info["pc_record_missing_days"] += 1
            elif day_on > 0 or pcs:
                info["floor_blocked_passive_days"] += 1
            if base:
                if abs_spans.get(d):
                    # 반차 시각(A5) — 그 시간은 가동 창이 아니다. 절전 공백(gap)은 어디 있었는지 모르므로 남은 창 길이에 비례해 줄인다
                    len0 = _union_min(base)
                    base = _subtract_spans(base, abs_spans[d])
                    if len0 > 0 and kind == "window":
                        gap_h *= _union_min(base) / len0
                covered = _clip(covered_all, dw0, dw1) if act.get(d) else []
                unc = _subtract_spans(base, covered) if covered else list(base)
                # 점심(A35 — day_on 크기와 무관하게 창이 점심을 ≥30분 덮으면) · 저녁(A33 — 야근일만) 공백: 흔적 ±5분이 없는 부분
                lunch_gap, dinner_gap = [], []
                lw = _intersect_spans(base, [tuple(lunch)])
                if _union_min(lw) >= 30 and (kind != "window" or _union_min(lw) / 60.0 <= day_on_eff + 1e-9):
                    lunch_gap = _subtract_spans(lw, trace_sp)
                if night > 0 and day_on_eff >= 6 and last_off is not None and last_off >= dinner[1]:
                    dinner_gap = _subtract_spans(_intersect_spans(base, [tuple(dinner)]), trace_sp)
                floor_u_sp = _intersect_spans(_subtract_spans(base, lunch_gap + dinner_gap), unc)
                lunch_ded = _union_min(_intersect_spans(lunch_gap, unc)) / 60.0
                dinner_ded = _union_min(_intersect_spans(dinner_gap, unc)) / 60.0
                floor_u = _union_min(floor_u_sp) / 60.0
                meet_h = _union_min(_intersect_spans(list(meets.get(d, [])) + list(off_blk), unc)) / 60.0   # PC 밖 달력 회의
                if kind == "window":
                    # 절전·잠금 PC(A3e): 가동 창과 on 의 차이(gap) 중 점심·달력 회의로 설명되는 만큼은 근무 — 나머지는 뺀다
                    floor_u = max(0.0, floor_u - max(0.0, gap_h - lunch_ded - meet_h))
                elif kind == "nowin":
                    # 창을 모르면 on 이 상한 — 단 PC 절전 중의 달력 회의(unc 안)는 on 밖의 근무라 더한다(VF-H6: 옛 3열 pc_on 에서
                    # 회의 1h 가 상한에 흡수되던 과소)
                    floor_u = max(0.0, min(floor_u, day_on - lunch_ded - dinner_ded + meet_h))
                elif kind == "trace":
                    floor_u = min(floor_u, std)
                inside_u = _union_min(_intersect_spans(day_spans, unc))    # 미커버 가동 구간 안의 실측 흔적
                rest = day_min - inside_u                                   # 창 밖 흔적 + 샘플러 실측 — 그대로 더한다
                if 0 < absent < 1:
                    floor_u = min(floor_u, max(0.0, std * (1.0 - absent) - rest / 60.0))
                if floor_u * 60.0 > inside_u + 1e-9:
                    gain = (floor_u * 60.0 - inside_u) / 60.0
                    day_min = rest + floor_u * 60.0
                    info["lunch_deducted_h"] += lunch_ded
                    info["dinner_deducted_h"] += dinner_ded
                    if kind == "trace":
                        info["trace_window_days"] += 1
                        info["trace_window_h"] += gain
                    else:
                        info["pc_floor_h"] += gain
                        info["pc_floor_days"] += 1
                    if covered:
                        info["sampler_partial_days"] += 1
                    if off:
                        info["weekend_pc_days"] += 1
            # ── 시차 근무(D4a): 산출물 없어도 주간 창 밖 PC 가동을 앞뒤 각 flex_h 까지(야간 합 ≤ PC night) ──
            if flex_h > 0 and gate_ok and kind in ("window", "spans") and pc_win and not off:
                cand = (_clip(pc_win, max(0.0, dw0 - flex_h * 60), dw0) + _clip(pc_win, dw1, min(1440.0, dw1 + flex_h * 60)))
                allowed = night * 60 - night_min_ex
                if cand and allowed > 1e-9:
                    fitted = _fit_credit([(a, b, "b") if b <= dw0 else (a, b, "a") for a, b in cand], spans, allowed)
                    gain = _union_min(spans + fitted) - _union_min(spans)
                    if gain > 1e-9:
                        spans += fitted
                        night_min = _union_min(_night_zone(spans))
                        info["flex_edge_h"] += gain / 60.0
        worked = (day_min + night_min) / 60.0
        # 야간 시간은 경계에 걸친 구간도 겹치는 만큼만 정확히 잰다 (18~20시 연장근무 누락 방지)
        night_h = night_min / 60.0
        if act.get(d) and _union_hours(act[d]) >= 20:
            _anom(d, "샘플러 활동 ≥20h(원격세션 idle 고착 의심)", [round(_union_hours(act[d]), 2)], None)
        # ── 종일 행사(A6): 출장·현장·교육 — 표준일 × (1−부재) 를 하한으로(PC 없음·휴대폰 발신 2통이 0h 이던 날) ──
        if is_offsite and not off and method == "activity":
            base_off = std * (1.0 - absent)
            info["offsite_days"] += 1
            if worked < base_off:
                info["offsite_h"] += base_off - worked
                worked = base_off
        # ── 수동 기록(A13): collect/Add-WorkLog.ps1 — 기록 시간을 하한으로(대체가 아니라 하한) ──
        if is_manual and method == "activity":
            mh = float(manual[d][0])
            info["manual_days"] += 1
            if worked < mh:
                info["manual_h"] += mh - worked
                worked = mh
        if method != "activity":                 # 예전 방식(비교용)
            if not off and absent < 1.0:
                base = std * (1.0 - absent)
                evidence = worked > 0 or on > 0
                if not evidence:
                    gap_run.append(d)
                else:
                    gap_run = []
                if len(gap_run) >= GAP_DAYS:      # 연휴·장기부재 — 8h 채움 중단 (v5에서 소실 복원)
                    for gd in gap_run:
                        hours.pop(gd, None)
                    info["gap_days"] += 1
                    base = 0.0
                worked = max(worked, base)
        if absent >= 1.0 and worked > 0:
            # 연차인데 흔적이 있다 — 예전 4h 클램프 대신 장부에 남기고 흔적만큼 그대로 계상
            info["absent_worked_h"] += worked
            _anom(d, "부재일(연차·휴가) 흔적 — 자르지 않고 흔적만큼 계상", None, [round(worked, 2)])
        if worked > PHYS_CAP_H:                  # 입력 검증이 정상이면 닿지 않는 마지막 물리 한계
            info["phys_cap_days"] += 1
            _anom(d, "24h 물리 한계 초과", [round(worked, 2)], [PHYS_CAP_H])
            worked = PHYS_CAP_H
        if day_cap and worked > day_cap:         # 사용자가 설정으로만 거는 선택 상한
            info["day_cap_days"] += 1
            worked = day_cap
        if worked > LONG_DAY_H:
            info["long_days"].append([d.isoformat(), round(worked, 2)])
        if worked > 0:
            hours[d] = round(worked, 2)
            if off:
                info["weekend_days"] += 1
                info["overtime_h"] += worked
            else:
                info["overtime_h"] += max(0.0, worked - std)
            if night_h >= 0.5:
                info["night_days"] += 1
        elif not off and absent < 1.0:
            info["no_evidence_days"] += 1
        if not off and absent <= 0.0 and infer_abs and method == "activity":
            k = d.strftime("%Y-%m")
            n, m = pc_alive.get(k, (0, 0))
            # 부재 추정(A31 완화): 투입 ≤15분·PC 가동 ≤30분(유지관리 깨움)·능동 흔적 없음(수신 1통 허용)인 평일 —
            # 그 달 PC 기록이 평일의 40% 이상 살아 있을 때만(수집 실패를 부재로 오인하지 않게). 호출측이 가용에서 차감한다.
            # 달력 근태가 있는 날(반차 0.5 포함)은 추정하지 않는다(VF-H7 — 반차일이 추정 1.0 이 되어 분모에서 통째로 빠지던 것).
            if (worked <= 0.25 and on <= 0.5 and not active_day and not is_offsite and not is_manual
                    and n and m / n >= 0.4):
                inferred[d] = 1.0
                info["inferred_absence_days"] += 1
        if off and d.isoweekday() <= 5:
            info["holidays"] += 1
        d += timedelta(days=1)
    for k in ("overtime_h", "pc_floor_h", "lunch_deducted_h", "evening_credit_h",
              "weekend_window_h", "absent_worked_h", "offsite_h", "manual_h", "dinner_deducted_h",
              "flex_edge_h", "sampler_bridge_h", "trace_window_h", "sim_night_h", "sim_night_remote_h"):
        info[k] = round(info[k], 1)
    info["inferred_absence"] = inferred
    info["inferred_absence_dates"] = [x.isoformat() for x in sorted(inferred)]
    # ── D5: 측정 방식·신뢰도·산식 설정 — mine.py 가 mm_meta 최상위에 싣고 팀 취합·리포트가 배지로 보인다 ──
    wd_hours = sum(1 for dd in hours if not _is_off_day(dd, holidays))
    if method != "activity":
        meth = "표준일(workday)"
    elif info["sampler_days"] and info["sampler_days"] >= max(1, wd_hours) * 0.5:
        meth = "샘플러 실측"
    elif info["pc_floor_days"]:
        meth = "PC 하한"
    elif info["trace_window_days"]:
        meth = "흔적 창"
    else:
        meth = "신호 세션"
    info["measure"] = {"method": meth, "sampler_days": info["sampler_days"], "pc_floor_days": info["pc_floor_days"],
                       "floor_blocked_passive_days": info["floor_blocked_passive_days"],
                       "pc_record_days": info["pc_record_days"], "trace_window_days": info["trace_window_days"],
                       "offsite_days": info["offsite_days"], "manual_days": info["manual_days"]}
    wd_n = sum(n for n, _m in pc_alive.values())
    pc_ratio = (info["pc_record_days"] / wd_n) if wd_n else 0.0
    reasons = []
    if pc_ratio < 0.4:
        reasons.append(f"PC 기록 평일 {round(pc_ratio * 100)}%(<40%)")
    if not info["sampler_days"]:
        reasons.append("창 샘플러 0일")
    if not cal_n:
        reasons.append("달력 0행")
    info["coverage"] = {"grade": "reliable" if not reasons else ("caution" if len(reasons) == 1 else "unreliable"),
                        "reasons": reasons, "pc_weekday_ratio": round(pc_ratio, 2)}
    info["cfg_used"] = {"standardDayHours": std, "usePcFloor": use_pc_floor, "pcFloorNeeds": floor_needs,
                        "dayWindow": [_fmt_hm(dw0), _fmt_hm(dw1)], "lunch": [_fmt_hm(lunch[0]), _fmt_hm(lunch[1])],
                        "dinner": [_fmt_hm(dinner[0]), _fmt_hm(dinner[1])], "tentativeMeetings": tentative,
                        "holidays_n": len(holidays), "offsiteAsWork": offsite_on,
                        "samplerGapBridgeMin": bridge_min}
    info["basis"] = (("투입 = 활동 흔적(회의·창 샘플러·신호 세션) 구간의 합집합 · PC 가동 구간 하한(구간 단위) · 상한 없음"
                      f"(하루 24h 물리 한계만) · 이상치 {len(anomalies)}일 표시")
                     if method == "activity" else "투입 = 평일 표준 8h 기준(비교용)")
    return hours, info


def mm_from_hours(day_hours, d0, d1, workdays=(1, 2, 3, 4, 5), cfg=None, absence=None, now=None, inferred=None,
                  info=None):
    """월별 투입 MM · 가용 MM · 로드율.

      1 MM      = 8h × 그 달 '달력상 전체' 평일수  (부분월도 이 분모를 쓴다 — 기간 내 평일로
                  나누면 부분월이 각각 1.0을 채워 3개월 분석이 4.0 MM으로 부푼다)
      가용 MM   = (평일수 − 부재일수) ÷ 평일수      ← 연차는 '일자에서' 빠진다
      투입 MM   = 그 달 투입시간 ÷ (8h × 평일수)    ← 상한 없음. 야근하면 1.0을 넘는다
      로드율(%) = 투입 MM ÷ 가용 MM × 100

    LM22 2차:
      now      : 분석 시각(기본 datetime.now()). 오늘보다 뒤의 평일은 가용에서 뺀다(info["future_days"]),
                 오늘은 주간 창에서 지금까지 지난 비율만 가용(info["today_fraction"]) — 09시에 돌리면 오늘 잔여가
                 통째로 가용이던 −27pt 과소(A34).
      inferred : 부재 '추정' 일자(day_work_hours info["inferred_absence"] 의 키). 이 날은 미등록 공휴일처럼 그 달
                 평일수(1 MM 의 분모)에서도 뺀다 — 추정이 성공해도 투입 MM 분모가 20일 그대로이던 −15%(A31).
                 달력 근태(연차)는 예전처럼 가용에서만 빠진다. 로드율은 두 경우 모두 같다.
      info     : dict 를 주면 future_days·today_fraction 을 채운다(mine.py 가 day_work_hours info 를 넘긴다).

    returns ({'YYYY-MM': {...}}, 총 투입 MM, 총 가용 MM)"""
    import calendar as _cal
    from datetime import date as _date, timedelta
    cfg = cfg or {}
    mc = norm_cfg(cfg)[0]
    std = mc["standardDayHours"]                         # 0·문자열 등 잘못된 값은 기본 8h(경고)
    dw0, dw1 = mc["dayWindow"]
    holidays = _holiday_set(cfg)
    absence = absence or {}
    inf_days = set(inferred.keys() if isinstance(inferred, dict) else (inferred or ()))
    now = now or datetime.now()
    today = now.date()
    now_m = now.hour * 60 + now.minute + now.second / 60.0
    today_frac = min(1.0, max(0.0, (now_m - dw0) / max(1.0, float(dw1 - dw0))))
    future_days = 0
    months = {}
    d = d0
    while d <= d1:
        m = months.setdefault(d.strftime("%Y-%m"),
                              {"worked": 0.0, "workdays": 0, "covered": 0, "absent": 0.0, "_inf": 0})
        if not _is_off_day(d, holidays, workdays):
            if d > today:
                future_days += 1                          # 아직 오지 않은 평일 — 가용이 아니다(A34)
            else:
                frac = today_frac if d == today else 1.0
                if d in inf_days:
                    m["_inf"] += 1                        # 추정 부재 — 분모(그 달 평일수)에서도 뺀다(A31)
                else:
                    m["covered"] += frac
                    m["absent"] += min(frac, absence.get(d, 0.0))
        m["worked"] += day_hours.get(d, 0.0)
        d += timedelta(days=1)
    tot_mm = tot_cap = 0.0
    for mk, m in months.items():
        y, mo = int(mk[:4]), int(mk[5:7])
        full = sum(1 for dd in (_date(y, mo, i + 1) for i in range(_cal.monthrange(y, mo)[1]))
                   if not _is_off_day(dd, holidays, workdays))
        full = max(0, full - m.pop("_inf"))
        m["workdays"] = full                                   # 달 전체 평일수(추정 부재 제외)
        m["capacity_h"] = std * max(1, full)                   # 1 MM 에 해당하는 시간
        # 가용: 이 기간에 실제로 일할 수 있었던 날 (부재 차감). 기간 밖·미래 날짜는 가용이 아니다.
        avail_days = max(0.0, m["covered"] - m["absent"])
        m["covered"] = round(m["covered"], 3)
        m["avail_mm"] = round(avail_days / max(1, full), 3)
        m["mm"] = round(m["worked"] / m["capacity_h"], 3)       # 투입
        m["load_pct"] = round(m["mm"] / m["avail_mm"] * 100, 1) if m["avail_mm"] > 0 else None
        m["worked"] = round(m["worked"], 1)
        m["absent"] = round(m["absent"], 1)
        tot_mm += m["mm"]
        tot_cap += m["avail_mm"]
    if isinstance(info, dict):
        if future_days:
            info["future_days"] = future_days
        if d0 <= today <= d1:
            info["today_fraction"] = round(today_frac, 2)
    return months, round(tot_mm, 3), round(tot_cap, 3)


def rehours_after_judge(data_dir, kept_rows, dropped_rows, d0, d1, cfg, exclude=()):
    """A30 — 판정에서 버린(비업무 'n'·오할당 제외) 신호를 뺀 채 투입시간·MM 을 다시 잰다.
    kept_rows/dropped_rows: report\\signals_<tag>.csv 행(dict: time·source·who·text·weight…, judge/ui 가 넘긴다).
    버린 파일 신호의 폴더 라벨·파일명은 _file_times 의 제외어로도 넘겨, 표본화에서 빠졌던 같은 폴더의 파일 시각이
    시간 근거에 남지 않게 한다(판정 신호는 폴더·일 8건 표본이지만 시간 근거는 전체 파일 시각이다).
    returns {"day_hours": {iso: h}, "info", "total_mm", "avail_mm", "months", "dropped_h"} — dropped_h 는
    (kept+dropped 로 잰 시간) − (kept 만으로 잰 시간). 예전에는 mine 단계 total_mm 이 그대로 남아 버린 신호의
    시간이 남은 행에 옮겨 붙었다."""
    cfg = cfg if isinstance(cfg, dict) else {}

    def _sig(rows):
        out = []
        for r in rows or []:
            if not isinstance(r, dict):
                continue
            t = _dt(r.get("time"))
            if not t:
                continue
            try:
                w = float(r.get("weight") or 0)
            except (TypeError, ValueError):
                w = 0.0
            out.append((t, (r.get("source") or "").strip(), (r.get("text") or "").strip() or "-", w,
                        (r.get("who") or "").strip()[:20]))
        out.sort(key=lambda x: x[0])
        return out

    kept_sig = _sig(kept_rows)
    all_sig = _sig(list(kept_rows or []) + list(dropped_rows or []))
    ex = [str(e) for e in (exclude or ()) if str(e).strip()]

    def _fol(text, force=False):
        m = re.search(r"\| 폴더:(.+?)(?: 외 \d+건| \((?:일괄|해석 출력) \d+건\))?$", text)
        # 100자에서 잘린 원문의 폴더 라벨은 믿지 않는다(부분 일치 위험) — force 는 접두 일치로 쓸 때(해석 출력 대표, VF-H3)
        return m.group(1).strip().lower() if (m and (force or len(text) < 100)) else ""

    kept_fols = {_fol(str(r.get("text") or "")) for r in (kept_rows or []) if isinstance(r, dict)
                 and str(r.get("source") or "").startswith("파일")} - {""}
    ex_drop, sim_drop = set(), []
    for r in dropped_rows or []:
        src = str(r.get("source") or "").strip() if isinstance(r, dict) else ""
        if not src.startswith("파일"):
            continue
        text = str(r.get("text") or "")
        if src == "파일(해석출력)":
            # 해석 출력 뭉치의 대표(VF-H3) — 뭉치(날, 폴더) 단위가 곧 신호다. 텍스트 길이와 무관하게 (날짜, 폴더 라벨[잘렸으면
            # 접두], 대표 시각) 으로 _file_times 가 그 뭉치의 anchor 를 남기지 않게 한다. 예전엔 파일명 1건(run_00000.dat)만
            # 빠져 다음 파일이 anchor 가 되고 PC 하한이 그대로 남았다(dropped_h 0).
            t = _dt(r.get("time"))
            if t:
                # 라벨이 온전한가 — 100자 미만이거나 꼬리 '(해석 출력 N건)' 이 남아 있으면(mine.py 가 꼬리를 보존) 완전 일치, 아니면 접두
                exact = len(text) < 100 or bool(re.search(r" \(해석 출력 \d+건\)$", text))
                sim_drop.append((t.date(), _fol(text, force=True), t.hour * 60 + t.minute, exact))
        head = re.split(r" § | \| 폴더:| 외 \d+건| \((?:일괄|해석 출력) \d+건\)", text)[0].strip()
        if len(head) >= 3:
            ex_drop.add(head.lower())                      # 파일명 — 같은 파일의 다른 저장 시각도 시간 근거에서
        fol = _fol(text)
        # 폴더 라벨은 그 폴더의 표본이 **전부** 버려졌을 때만(개인 폴더) — 업무 폴더의 파일 1건을 버렸다고 폴더 전체의
        # 시간 근거가 사라지지 않게. kept 에 같은 폴더의 파일 신호가 남아 있으면 파일명으로만 뺀다.
        if len(fol) >= 2 and fol not in kept_fols:
            ex_drop.add(fol)
    ft_kept = _file_times(data_dir, d0, d1, ex + sorted(ex_drop), cfg, sim_drop=sim_drop)[0]
    ft_all = _file_times(data_dir, d0, d1, ex, cfg)[0] if (ex_drop or sim_drop) else ft_kept
    hours_k, info_k = day_work_hours(data_dir, kept_sig, d0, d1, cfg, file_times=ft_kept)
    hours_a, _info_a = day_work_hours(data_dir, all_sig, d0, d1, cfg, file_times=ft_all)
    absence = dict(absence_days(data_dir, d0, d1))
    inferred = info_k.get("inferred_absence") or {}
    absence.update(inferred)
    months, tmm, tcap = mm_from_hours(hours_k, d0, d1, cfg=cfg, absence=absence, inferred=inferred, info=info_k)
    dropped_h = max(0.0, sum(hours_a.values()) - sum(hours_k.values()))
    return {"day_hours": {k.isoformat(): round(v, 2) for k, v in hours_k.items()}, "info": info_k,
            "total_mm": tmm, "avail_mm": tcap, "months": months, "dropped_h": round(dropped_h, 2)}
