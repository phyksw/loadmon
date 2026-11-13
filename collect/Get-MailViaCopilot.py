# -*- coding: utf-8 -*-
"""
Get-MailViaCopilot.py — AgentFinder32 M365 Copilot 수집기: 회사 테넌트의 내 Copilot 에게 내 사서함의 메일·일정 목록(날짜·받은/보낸·
제목·참여자 메일 도메인)만 묻는다. 다른 경로(Outlook 앱·Outlook 웹)가 확인하지 못한 날만 묻는 확인용(증인)이다.

  python collect\\Get-MailViaCopilot.py --from 2026-08-01 --to 2026-10-31 [--ranges A:B,C:D] [--ranges-cal A:B] [--only mail|cal]
         [--out-dir data\\outlook\\src --tag copilot] [--retry-copilot]

AgentFinder32 규칙(spec D1·D2·D7·D8·D11·D19·§5.0~§5.2):
  · 내 자료가 아니거나 지우는 중이면(core\\consent.require) 묻지 않고 종료 코드 3(R-CONSENT). 제한 고객 목록이 없거나 사내 메일 도메인을 알 수 없으면
    종료 코드 4(R-NORESTRICTED·R-NODOMAIN) — G1 문맥(privacy.G1Context)을 먼저 세운 뒤에만 Copilot 을 연다.
  · 기간은 period.clamp(끝은 어제까지 · period.maxDays 일 이하) 안의 날만 묻는다(--ranges 도 그 안으로 자른다).
  · 프롬프트는 D1 문장(COLLECT_RULE)으로 시작한다 — 내 사서함·내 일정만, Teams 채팅·모임 채팅·녹취록·공유/그룹 사서함·파일·웹 금지,
    비공개·사외·휴가·건강·근태 항목 제외, 날짜·받은/보낸·제목·참여자 메일 도메인만(이름·주소 금지). 제목의 사람 이름은 [사람]으로
    바꿔 쓰게 한다(NAME_RULE 한 줄). 제한 고객 이름은 넣지 않는다.
    모든 프롬프트는 copilot_auto 의 G3 관문(gate_prompt)과 보내기 전 계정 확인(account_check)을 지난 뒤에만 나간다.
  · 답은 메모리에서만 읽는다 — 원문 답을 파일에 남기지 않는다. 행마다 privacy.g1_row 를 거친 정제 행만 privacy.G1Writer 로
    <out-dir>\\mail_<tag>.csv(§5.1)·cal_<tag>.csv(§5.2)에 쓴다(표를 받은 조각의 옛 행만 바꾼다 — owa_parse.merge_slices).
  · 참여자(D7): 도메인 칸을 사내/사외 판정 재료로 쓴다 — 받은 메일은 첫 도메인을 보낸 사람, 나머지를 참조로, 보낸 메일은 받는 사람으로.
    도메인이 비면 증명할 수 없어 G1 이 뺀다(external_unknown). 일정의 '없음'(나 혼자인 일정)은 참여자 없음으로 본다.
    따옴표 없이 쉼표로 이어 쓴 도메인 목록은 뒤쪽 도메인 칸을 모두 읽고(_tail_domains), 제목 칸에 남은 도메인 꼴 낱말(파일 이름
    제외)도 참여자로 더한다(subject_domains) — 회사 밖 도메인이 제목으로 밀려 사내 행으로 남지 않게.
  · 시각은 묻지 않는다 — 메일은 그날 12:00(time_precision=date), 일정은 날짜만(start=end=YYYY-MM-DD)으로 둔다.
  · 끝나면 전용 Edge 의 Outlook·M365 사이트 자료(캐시·저장소 — 쿠키는 남김)를 지운다(copilot_auto.clear_site_data — D13).
  · AF32STATUS counts.g1 = {kept, excluded}(숫자만) · 정제 건수는 <out-dir>\\g1_<tag>.json 에도(core\\mailmerge.save_g1_counts).
왕복(LM28~LM30 규칙 유지):
  · --ranges 'A:B,C~D,E'(또는 '@파일') — run.py 가 다른 경로가 확인하지 못한 날만 준다. 없으면 --from~--to. 7일 조각으로 묻는다.
    --ranges-cal 은 일정 조각의 구간(없으면 --ranges) — 메일·일정이 한 채팅을 이어 쓴다.
  · 왕복은 copilot_auto.send_inproc(같은 프로세스). G3 관문에 막힌 조각(blocked)은 보내지 않은 것으로 둔다.
  · 조각마다 새 채팅을 열지 않는다 — copilot_auto.ChatKeep 이 정한다(첫 조각·나쁜 조각 뒤·chatTurns 마다만 새 채팅). 프롬프트 끝 줄(★)의
    기간이 조각마다 달라 앞 조각의 답을 이번 답으로 집지 않는다.
  · 'empty'(없음)·'other'(표 아닌 답)는 실패로 세지 않는다. 드라이버가 답을 못 받은 조각만 연속 ERR_MAX 번이면 멈춘다.
    한 조각 회수가 FULL_N 이상(150행 상한에 잘림)이면 2일(그래도 많으면 1일) 조각으로 다시 묻는다.
  · '조회 불가(unable)'는 서로 다른 날 2회일 때만 14일 동안 생략한다(<out-dir>\\mail_copilot_unavailable.json — 날짜만).
  · 마지막 줄: AF32STATUS {v,src,rc,reason,counts,ranges} — rc 0 표를 받음(또는 '없음' 답) · 2 로그인 · 3 불가(R-UNABLE·R-NOREPLY·
    R-GATE·R-CONSENT·Edge 사유) · 4 설정 거부. ranges 의 st 는 표를 받은 조각 partial(증인 — '읽음'이 아니다) · 그 밖 unverified.
"""
import csv
import io
import json
import os
import re
import sys
import time
from datetime import date, datetime, timedelta

if __name__ == "__main__":      # import 시(파서 재사용·테스트) stdout을 건드리지 않는다
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, errors="replace", encoding=(
        (sys.stdout.encoding or "utf-8") if sys.stdout.isatty() else "utf-8"))  # 콘솔(bat)=콘솔 코드페이지 · 파이프(UI)=utf-8
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_HERE = os.path.dirname(os.path.abspath(__file__))
_CORE = os.path.join(ROOT, "core")
for _p in (_HERE, _CORE):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import owa_parse  # noqa: E402  — 병합(merge_slices)

OUT_DIR = os.path.join(ROOT, "data", "outlook", "src")
CHUNK_DAYS = 7                 # 조각 길이(일)
REFINE_DAYS = 2                 # 조각 회수가 FULL_N 이상(잘림)이면 이 길이로 다시 묻는다
ERR_MAX = 4                     # 드라이버가 답을 못 받은(무응답·오류) 조각이 연속 이만큼이면 멈춘다(판정용 세션 보호)
UNABLE_TTL_DAYS = 14            # '조회 불가' 확정(서로 다른 날 2회) 뒤 생략하는 날 수
FATAL_PHASES = ("login_required", "edge_not_found", "launch_failed", "input_not_found")
LAST_FATAL = {}                 # 마지막 '사람이 풀 실패'의 phase·reason(AF32STATUS 사유)
MAIL_HDR_ASK = "box,date,subject,domains"       # Copilot 에 묻는 열(D1 — 날짜·받은/보낸·제목·참여자 도메인만)
CAL_HDR_ASK = "date,subject,domains"
FULL_N = 140                    # 한 조각 회수가 이 이상이면 150행 상한에 잘린 것으로 보고 REFINE_DAYS 조각으로 재질의
# D1 — 수집 프롬프트의 첫 문장(바꾸면 안내문·spec 과 함께 바꾼다). 제한 고객 이름은 어느 프롬프트에도 넣지 않는다.
COLLECT_RULE = ("내 사서함의 메일과 내 일정만 사용하세요. Teams 채팅·모임 채팅·녹취록·공유/그룹 사서함·파일·웹은 사용하지 마세요. "
                "비공개·개인·기밀 항목, 사외 참여자가 있는 항목, 휴가·건강·근태 항목은 빼세요. 날짜, 받은/보낸, 제목, 참여자 메일 "
                "도메인만 답하세요(이름·주소는 쓰지 마세요).")
# 제목에 든 사람 이름 — Copilot 이 답할 때 [사람]으로 바꿔 쓰게 한다(메일·일정 프롬프트에 한 줄씩). 이 수집기의 행에는 참여자 이름이 없어
# 참여자 이름 가림(G1)이 닿지 않는 이름을 줄인다 — 가리는 것은 G1·G2·G3 의 이름 규칙이고, 이 줄은 덜 들어오게 하는 부탁이다.
NAME_RULE = "제목에 사람 이름이 있으면 [사람]으로 바꿔 쓰세요"
# 내 사서함의 메일 폴더(사람이 만든·이름을 바꾼·보관 폴더 포함 — 지운 편지함·정크·임시 보관함 제외). box 는 받은/보낸으로만 묻는다.
MAIL_SCOPE = ("내 사서함의 메일 폴더(받은 편지함·보낸 편지함과 그 하위 폴더, 내가 만들거나 이름을 바꾼 폴더, 보관 폴더 포함 — "
              "지운 편지함·정크 메일·임시 보관함은 제외)")


def arg(flag, d=""):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else d


def build_prompt(kind, d0, d1, alt=False):
    """kind: mail | cal.  alt = 검색형 화법(일괄 내보내기를 '조회 불가'로 거절하는 Copilot 대응). 첫 문장은 늘 COLLECT_RULE.
    끝 줄(★)의 '이번 질문의 기간'은 지우지 말 것 — 조각을 한 채팅에 이어 보내므로 그 줄이 조각마다 달라야 앞 조각의 답을 집지 않는다."""
    if kind == "mail":
        head = (f"{MAIL_SCOPE}에서 {d0}~{d1} 기간의 메일을 검색해 아래 CSV 형식 표로만 정리해 주세요(찾은 만큼만). "
                "헤더 포함, 다른 설명 없이, 코드 블록(```)으로:\n") if alt else (
                f"{d0}부터 {d1}까지 {MAIL_SCOPE}의 메일을 아래 CSV 형식으로만 출력해 주세요. "
                "헤더 포함, 다른 설명 없이, 코드 블록(```)으로:\n")
        return (COLLECT_RULE + "\n" + head + MAIL_HDR_ASK + "\n"
                "- box : 받은 메일이면 inbox, 내가 보낸 메일이면 sent (폴더 이름은 쓰지 마세요)\n"
                "- date : YYYY-MM-DD (받은 날 또는 보낸 날)\n"
                "- subject : 제목\n"
                f"- {NAME_RULE}\n"
                "- domains : 보낸 사람·받는 사람·참조의 메일 주소에서 @ 뒤 도메인만, 세미콜론(;)으로 이어서 — 이름·주소는 쓰지 마세요\n"
                '- 칸 안에 쉼표가 들어가면 그 칸을 따옴표("...")로 감싸세요\n'
                "- 자동 알림·광고·시스템 메일은 빼세요\n"
                "- 같은 메일이 여러 폴더에 보이면 한 번만\n"
                "- 기간 안의 메일을 빠짐없이 찾아 최대 150행까지\n"
                "- 결과가 정말 없으면 '없음' 한 단어만 출력하세요\n"
                "★ 실제로 검색된 메일만 출력하세요 — 예시·가상·추정으로 행을 만들지 마세요. 확실하지 않은 행은 빼세요. "
                f"(이번 질문의 기간: {d0}~{d1})\n")
    head = (f"내 Outlook 일정(캘린더)에서 {d0}~{d1} 기간의 일정·회의를 검색해 아래 CSV 형식 표로만 정리해 주세요(찾은 만큼만). "
            "헤더 포함, 다른 설명 없이, 코드 블록(```)으로:\n") if alt else (
            f"{d0}부터 {d1}까지 내 Outlook 일정(캘린더)의 일정·회의를 아래 CSV 형식으로만 출력해 주세요. "
            "헤더 포함, 다른 설명 없이, 코드 블록(```)으로:\n")
    return (COLLECT_RULE + "\n" + head + CAL_HDR_ASK + "\n"
            "- date : YYYY-MM-DD (일정 날짜)\n"
            "- subject : 일정 제목\n"
            f"- {NAME_RULE}\n"
            "- domains : 주최자·참석자의 메일 주소에서 @ 뒤 도메인만, 세미콜론(;)으로 이어서 — 나 혼자인 일정이면 없음\n"
            '- 칸 안에 쉼표가 들어가면 그 칸을 따옴표("...")로 감싸세요\n'
            "- 종일 일정·취소된 회의·거절한 회의는 빼세요\n"
            "- 반복 일정은 기간 안의 회차마다 한 행\n"
            "- 기간 안의 일정을 빠짐없이 찾아 최대 150행까지\n"
            "- 결과가 정말 없으면 '없음' 한 단어만 출력하세요\n"
            f"★ 실제로 검색된 일정만 출력하세요 — 예시·가상·추정으로 행을 만들지 마세요. (이번 질문의 기간: {d0}~{d1})\n")


UNABLE_MARKS = ("조회 불가", "조회가 불가", "조회할 수 없", "검색할 수 없", "검색이 불가",
                "액세스할 수 없", "접근할 수 없", "권한이 없", "지원되지 않", "지원하지 않",
                "제공되지 않", "cannot search", "can't search", "unable to", "no access",
                "don't have access", "조회 도구가 없", "데이터 조회 도구", "연결된 도구가 없",
                "도구가 없어", "no connected tool")
EMPTY_MARKS = ("없음", "찾을 수 없", "검색 결과가 없", "메일이 없", "일정이 없", "no emails",
               "no events", "couldn't find", "could not find")
# box 칸 어휘(소문자) — '받은 메일'·'received'·'보낸 항목'처럼 답하는 꼴도 받는다
BOX_IN = ("inbox", "받은", "받은 편지함", "받은 메일", "받은메일", "수신", "received", "incoming")
BOX_OUT = ("sent", "보낸", "보낸 편지함", "보낸 메일", "보낸메일", "보낸 항목", "발신", "sent items", "outgoing")
NONE_WORDS = ("없음", "none", "-", "n/a", "na", "없다", "본인", "나")
_DOM_RX = re.compile(r"@?([A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,24})")
_DOM_SPLIT = re.compile(r"[;,/\s]+")


def _reply_status(reply):
    low = (reply or "").strip().lower()
    if any(m in low for m in UNABLE_MARKS):
        return "unable"
    if any(m in low for m in EMPTY_MARKS):
        return "empty"
    return "other"


RE_T = re.compile(
    r"^(\d{4})\s*[-/.]\s*(\d{1,2})\s*[-/.]\s*(\d{1,2})\.?"                      # 2026-06-03 · 2026/6/3 · 2026. 6. 3.
    r"(?:(?:[ T]+|(?<=\.))\s*(?:(오전|오후|AM|PM)\s*)?(\d{1,2}):(\d{2})(?::\d{2}(?:\.\d+)?)?\s*(AM|PM|오전|오후)?)?"
    r"\s*(Z|UTC|\(UTC\)|GMT|KST|\(KST\)|[+-]\d{2}:?\d{2})?\s*$", re.I)


def _parse_time(s):
    """시각 문자열 → (norm 'YYYY-MM-DD HH:MM', precision 'minute'|'date', utc_marked).
    '2026-06-03' 처럼 날짜만이면 12:00·date. 시각이 이상하면 ('', '', False)."""
    t = (s or "").strip().strip("'\"")
    t = re.sub(r"(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일?", r"\1-\2-\3", t)
    m = RE_T.match(t)
    if not m:
        return "", "", False
    y, mo, dd, k1, hh, mm, k2, tz = m.groups()
    try:
        d = datetime(int(y), int(mo), int(dd)).strftime("%Y-%m-%d")
    except ValueError:
        return "", "", False
    utc = bool(tz) and tz.upper().strip("()") in ("Z", "UTC", "GMT")
    if hh is None:
        return d + " 12:00", "date", utc
    h = int(hh)
    ap = (k1 or k2 or "").upper()
    if ap in ("PM", "오후") and h < 12:
        h += 12
    if ap in ("AM", "오전") and h == 12:
        h = 0
    if h > 23 or int(mm) > 59:
        return "", "", False
    return f"{d} {h:02d}:{mm}", "minute", utc


def _split(raw):
    if raw.startswith("|"):
        return [c.strip() for c in raw.strip("|").split("|")]
    try:
        return [c.strip() for c in next(csv.reader([raw]))]
    except (csv.Error, StopIteration):
        return [c.strip() for c in raw.split(",")]


def parse_domains(s):
    """도메인 칸 → (도메인 목록(소문자·중복 없음) | None(모름), 없음 답인가). '없음'·'-' 은 ([], True). 도메인 꼴이 아닌 글이 섞이면
    None(그 칸을 믿지 않는다 — G1 이 증명할 수 없는 행으로 뺀다)."""
    v = str(s or "").strip().strip("'\"")
    if not v:
        return None, False
    if v.lower() in NONE_WORDS:
        return [], True
    out = []
    for p in _DOM_SPLIT.split(v):
        p = p.strip().strip("()[]<>")
        if not p:
            continue
        if "@" in p and not p.startswith("@"):
            p = p.split("@", 1)[1]                      # 주소를 답했다 — 도메인만 쓴다(이름·주소는 남기지 않는다)
        m = _DOM_RX.fullmatch(p)
        if not m:
            return None, False
        d = m.group(1).lower().rstrip(".")
        if d not in out:
            out.append(d)
    return (out, False) if out else (None, False)


# 제목 글 안의 도메인 꼴 낱말(예: 'partner.example 견적', 'kim@partner.example') — 파일 이름(확장자)은 도메인으로 보지 않는다
_SUBJ_DOM_RX = re.compile(r"(?<![A-Za-z0-9.\-_])((?:[A-Za-z0-9\-]+\.)+([A-Za-z]{2,24}))(?![A-Za-z0-9_\-])")
FILE_EXTS = frozenset((
    "pdf", "doc", "docx", "dot", "xls", "xlsx", "xlsm", "xlsb", "csv", "ppt", "pptx", "pps", "ppsx", "txt", "rtf", "hwp",
    "hwpx", "odt", "ods", "odp", "zip", "7z", "rar", "tar", "gz", "tgz", "jpg", "jpeg", "png", "gif", "bmp", "tif", "tiff",
    "svg", "heic", "msg", "eml", "mp4", "mov", "avi", "wmv", "wav", "mp3", "py", "js", "ts", "md", "json", "xml", "html",
    "htm", "log", "ini", "cfg", "conf", "bat", "cmd", "ps1", "sh", "exe", "msi", "dll", "dwg", "dxf", "stp", "step", "igs",
    "iges", "stl", "sldprt", "sldasm", "slddrw", "prt", "asm", "drw", "catpart", "catproduct", "vsd", "vsdx", "one", "bin",
    "hex", "yml", "yaml", "sql", "db", "bak", "tmp", "dat", "lic", "cs", "cpp", "hpp", "java", "kt", "go", "rs", "rb",
    "php", "css", "scss", "ipynb", "mat", "fig", "slx", "mdl"))


def subject_domains(subj):
    """제목 글 안의 도메인 꼴 낱말 → 도메인 목록(소문자·중복 없음). 파일 이름(마지막 마디가 FILE_EXTS)은 빼고, '@' 뒤 도메인도 센다.
    Copilot 이 참여자 도메인 목록을 따옴표 없이 쉼표로 이어 써 도메인이 제목 칸으로 밀린 행을 G1 이 사내 행으로 보지 않게 한다."""
    out = []
    for m in _SUBJ_DOM_RX.finditer(str(subj or "")):
        if m.group(2).lower() in FILE_EXTS:
            continue
        d = m.group(1).lower().rstrip(".")
        if d not in out:
            out.append(d)
    return out


def _tail_domains(parts, first):
    """오른쪽 끝에서부터 도메인 칸(parse_domains 가 읽는 칸)을 모은다 — 제목 첫 칸(first) 뒤까지만 → (제목 끝 번호, 도메인 목록, '없음'
    칸이 있었나). 따옴표 없는 쉼표로 이어 쓴 참여자 도메인('partner.example, corp.example')을 모두 도메인으로 읽는다(마지막 칸만 읽던
    예전 규칙은 앞 도메인을 제목에 붙였다). 도메인 칸이 아닌 칸을 만나면 멈춘다."""
    k, doms, none_seen = len(parts), [], False
    while k - 1 > first:
        d, none = parse_domains(parts[k - 1])
        if d:
            doms = [x for x in d if x not in doms] + doms
        elif none:
            none_seen = True
        else:
            break
        k -= 1
    return k, doms, none_seen


def _row_domains(subj, doms, none_seen):
    """도메인 칸 + 제목 안의 도메인 → (도메인 목록 | None(모름), '없음' 답인가). 도메인 칸이 없으면 모름(None — G1 이 증명할 수 없는
    행으로 뺀다). 제목에 도메인이 보이면 참여자로 더한다 — 회사 밖 도메인이면 G1 이 사외로 뺀다."""
    extra = [d for d in subject_domains(subj) if d not in doms]
    if doms:
        return doms + extra, False
    if none_seen:
        return (extra, False) if extra else ([], True)
    return None, False


def parse_mail_rows(reply, diag=None):
    """CSV/마크다운 표 관용 파싱 → [box, time, subject, 도메인 목록|None, time_precision] 목록(메모리에서만).
    열: box,date,subject,domains. 제목의 따옴표 없는 쉼표로 열이 밀리면 box·date 는 앞, domains 는 뒤쪽의 도메인 칸 전부(_tail_domains)
    로 고정한다. 제목 칸에 남은 도메인 꼴 낱말도 참여자 도메인으로 더한다(subject_domains — 파일 이름 제외).
    diag(dict) 에 date_only·utc_marked·bad_time 건수를 더한다."""
    rows = []
    diag = diag if diag is not None else {}
    for ln in (reply or "").splitlines():
        raw = ln.strip().strip("`").strip()
        if not raw or re.match(r"^box\s*[,|]", raw, re.I) or re.match(r"^\|?[-\s|]+$", raw):
            continue
        parts = _split(raw)
        if len(parts) < 3:
            continue
        k, dl, none_seen = _tail_domains(parts, 2)
        box, when, subj = parts[0], parts[1], ",".join(parts[2:k])
        d, _none = _row_domains(subj, dl, none_seen)
        box = re.sub(r"\s+", " ", box).strip().lower()
        if box in BOX_IN:
            box = "inbox"
        elif box in BOX_OUT:
            box = "sent"
        if box not in ("inbox", "sent"):
            continue                    # 폴더 이름 등 받은/보낸을 알 수 없는 값 — 지어 정하지 않는다
        t, prec, utc = _parse_time(when)
        if not t:
            diag["bad_time"] = diag.get("bad_time", 0) + 1
            continue
        if prec == "date":
            diag["date_only"] = diag.get("date_only", 0) + 1
        if utc:
            diag["utc_marked"] = diag.get("utc_marked", 0) + 1
        rows.append([box, t, subj.strip(), d if d else None, prec])
    return rows


def parse_cal_rows(reply, diag=None):
    """일정 표 → [날짜 'YYYY-MM-DD', subject, 도메인 목록|None, 없음 답인가] 목록(메모리에서만). 열: date,subject,domains.
    도메인 칸은 뒤쪽의 도메인 칸 전부(_tail_domains), 제목 칸에 남은 도메인 꼴 낱말도 참여자로 더한다(메일과 같다)."""
    rows = []
    diag = diag if diag is not None else {}
    for ln in (reply or "").splitlines():
        raw = ln.strip().strip("`").strip()
        if not raw or re.match(r"^(date|start)\s*[,|]", raw, re.I) or re.match(r"^\|?[-\s|]+$", raw):
            continue
        parts = _split(raw)
        if len(parts) < 2:
            continue
        k, dl, none_seen = _tail_domains(parts, 1)
        when, subj = parts[0], ",".join(parts[1:k])
        t, _p, _u = _parse_time(when)
        if not t:
            diag["bad_time"] = diag.get("bad_time", 0) + 1
            continue
        d, none = _row_domains(subj, dl, none_seen)
        rows.append([t[:10], subj.strip(), d, none])
    return rows


def _timeout():
    try:
        with open(os.path.join(ROOT, "config", "config.json"), encoding="utf-8-sig") as f:
            sec = float(((json.load(f).get("copilotAuto") or {}).get("replyTimeoutSec")) or 240)
    except (OSError, ValueError, TypeError):
        sec = 240.0
    return max(900.0, sec * 3 + 180)


_CA = {}
_KEEP = {}                      # 조각 사이 채팅 이어 쓰기(copilot_auto.ChatKeep · 진짜 _send 가 처음 보낼 때 만든다)


def _ca():
    """copilot_auto 모듈(같은 프로세스) — 처음 쓸 때 한 번 불러온다(시험이 one_slice 를 주입하면 불리지 않는다)."""
    if "m" not in _CA:
        tools = os.path.join(ROOT, "tools")
        if tools not in sys.path:
            sys.path.insert(0, tools)
        import copilot_auto
        _CA["m"] = copilot_auto
    return _CA["m"]


def _keep():
    """조각 사이 채팅 이어 쓰기 결정(copilot_auto.ChatKeep — 프로세스에 하나)."""
    if "k" not in _KEEP:
        _KEEP["k"] = _ca().ChatKeep()
    return _KEEP["k"]


def _keep_done(good, res=None, mark=None):
    """조각 결과를 ChatKeep 에 알린다(good = 다음 조각을 같은 채팅에 이어도 되나) — mark(없으면 not good)면 그 채팅을 다음 단계도 이어 쓰지
    않게 표시한다(chat_mark_bad). 진짜 _send 를 쓴 적이 없으면(시험이 _send 를 바꿈) 아무것도 하지 않는다."""
    k = _KEEP.get("k")
    if k is None:
        return
    try:
        k.done(good, res)
        if (not good) if mark is None else mark:
            _ca().chat_mark_bad()
    except Exception:  # noqa: BLE001 — 셈 오류가 수집을 막지 않는다
        pass


def _send(prompt):
    """한 조각 왕복 — copilot_auto.send_inproc(같은 프로세스). 결과 dict 는 --send 의 JSON 과 같다. 마감은 조각마다 _timeout() 초.
    fresh 는 ChatKeep 이 정한다(첫 조각·나쁜 조각 뒤·chatTurns 마다만 새 채팅). 결정을 못 하면 새 채팅."""
    try:
        fr = _keep().next()
    except Exception:  # noqa: BLE001
        fr = True
    return _ca().send_inproc(prompt, fresh=fr, deadline=time.time() + _timeout(), stage="mail_copilot")


def _one_slice(kind, s0, s1, alt=False):
    """한 조각(<=7일) 왕복 → (행 목록, 상태) — 상태: table|unable|empty|other|blocked(G3 — 보내지 않음)|
    error(드라이버가 답을 못 받음)|fatal(로그인 등 사람이 풀 실패 — LAST_FATAL 에 phase·reason).
    표·'없음'·표 아닌 답이면 다음 조각은 같은 채팅, 오류·'조회 불가'면 새 채팅(_keep_done). blocked 는 보내지 않았으니 알리지 않는다."""
    rows, st, res = _ask(kind, s0, s1, alt)
    if st != "blocked":
        r = res if isinstance(res, dict) else {}
        clean = st in ("table", "empty") and not r.get("cut") and not r.get("slow")
        _keep_done(st in ("table", "empty", "other"), r, mark=not clean)
    return rows, st


def _ask(kind, s0, s1, alt=False):
    """_one_slice 의 왕복·해석 → (행 목록, 상태, 드라이버 결과 dict — 예외·해석 실패면 None). 답 원문은 메모리에서만 읽는다."""
    prompt = build_prompt(kind, s0, s1, alt)
    try:
        res = _send(prompt)
    except Exception as e:  # noqa: BLE001 — 드라이버 예외는 이 조각만 건너뛴다
        print(f"[mail-copilot]   {kind} {s0}~{s1}: 드라이버 오류({type(e).__name__})")
        return [], "error", None
    if not isinstance(res, dict):
        print(f"[mail-copilot]   {kind} {s0}~{s1}: 드라이버 응답 해석 실패")
        return [], "error", None
    if res.get("status") == "blocked" or res.get("phase") == "blocked":
        print(f"[mail-copilot]   {kind} {s0}~{s1}: 개인정보 관문(G3) — 보내지 않음")
        return [], "blocked", res
    if not res.get("ok"):
        print(f"[mail-copilot]   {kind} {s0}~{s1}: 실패 — {res.get('error', '')}")
        # 로그인 필요·Edge 없음 같은 '사람이 손대야 풀리는' 실패는 조각을 나눠 다시 물어도 똑같다 — 한 번에 접는다.
        if str(res.get("phase") or "") in FATAL_PHASES:
            print(f"[mail-copilot]   {res.get('hint', '')}")
            LAST_FATAL.update(phase=str(res.get("phase") or ""), reason=str(res.get("reason") or ""))
            return [], "fatal", res
        return [], "error", res
    reply = str(res.get("reply") or "")
    res["reply"] = ""                       # 답 원문은 더 들고 있지 않는다
    diag = {}
    rows = parse_mail_rows(reply, diag) if kind == "mail" else parse_cal_rows(reply, diag)
    st = "table" if rows else _reply_status(reply)
    reply = ""
    # 환각 방어: 요청 구간 밖 날짜의 행은 버린다
    good = [r for r in rows if s0 <= r[1 if kind == "mail" else 0][:10] <= s1]
    if len(good) < len(rows):
        print(f"[mail-copilot]   {kind} {s0}~{s1}: 기간 밖 날짜 {len(rows) - len(good)}행 제외 (환각/오검색 의심)")
    notes = []
    if diag.get("utc_marked"):
        notes.append(f"UTC 표기 행 {diag['utc_marked']} — config collect.mailTimeOffsetH 확인")
    if diag.get("bad_time"):
        notes.append(f"날짜 해석 불가 행 {diag['bad_time']} 제외")
    if notes:
        print(f"[mail-copilot]   {kind} {s0}~{s1}: " + " · ".join(notes))
    return good, ("table" if good else ("empty" if st == "table" else st)), res


# ── G1 — 답 행 → 원자료 dict(메모리) → privacy.g1_row → 정제 파일 ───────────────────────────
def raw_mail(r):
    """메일 행 [box, time, subject, 도메인|None, precision] → G1 원자료 dict(§5.0 열). 받은 메일은 첫 도메인이 보낸 사람(@도메인),
    나머지는 참조 · 보낸 메일은 모두 받는 사람. 도메인이 없으면 빈칸(G1 이 증명할 수 없는 행으로 뺀다)."""
    box, t, subj, doms, prec = r[0], r[1], r[2], (r[3] or []), r[4]
    conv = re.sub(r"^((RE|FW|FWD|답장|전달|회신)\s*:\s*)+", "", subj, flags=re.I)
    d = {"box": box, "time": t, "sender_name": "", "sender_addr": "", "to": "", "cc": "", "rcv": "",
         "time_precision": prec, "subject": subj, "conversation": conv, "sensitivity": "0", "categories": "", "folder": ""}
    if box == "sent":
        d["to"] = "; ".join(doms)
    elif doms:
        d["sender_addr"] = "@" + doms[0]
        d["cc"] = "; ".join(doms[1:])
    return d


def raw_cal(r):
    """일정 행 [날짜, subject, 도메인|None, 없음 답] → G1 원자료 dict. '없음'(나 혼자인 일정)은 참여자 빈칸(G1 이 사내로 본다),
    도메인이 없거나 믿을 수 없으면 '? <>'(증명할 수 없음 — G1 이 뺀다). 시각은 묻지 않았다 — start=end=날짜."""
    day, subj, doms, none = r[0], r[1], r[2], r[3]
    att = "; ".join(doms) if doms else ("" if none else "? <>")
    return {"start": day, "end": day, "all_day": "0", "busy_status": "2", "subject": subj, "categories": "",
            "location": "", "response": "", "meeting_status": "", "sensitivity": "0", "organizer": "", "attendees": att}


def _merger(kind, spans):
    """G1Writer 의 merge — 표를 받은 조각(spans)의 옛 정제 행만 이번 정제 행으로 바꾼다(owa_parse.merge_slices)."""
    import privacy
    cols = privacy.MAIL_COLS if kind == "mail" else privacy.CAL_COLS + ["body"]
    axes = ("mail_in", "mail_out") if kind == "mail" else ("cal",)
    ver = {ax: list(spans or []) for ax in axes}

    def merge(old, new):
        lo = [[str(r.get(c, "") or "") for c in cols] for r in old or ()]
        ln = [[str(r.get(c, "") or "") for c in cols] for r in new or ()]
        out = owa_parse.merge_slices(lo, ln, ver, "mail" if kind == "mail" else "cal")
        return [dict(zip(cols, (r + [""] * len(cols))[:len(cols)], strict=True)) for r in out]
    return merge


def save_g1(kind, rows, path, ctx, spans):
    """이번 조각의 행 → 항목마다 privacy.g1_row → G1Writer(표를 받은 조각의 옛 행만 교체) → 이번에 남긴 행 수."""
    import privacy
    kept = 0
    with privacy.G1Writer(path, kind, merge=_merger(kind, spans)) as w:
        for r in rows:
            kept += w.add(raw_mail(r) if kind == "mail" else raw_cal(r), ctx) is None
    return kept


# ── '조회 불가' 기억 — 서로 다른 날 2회일 때만 14일 생략 ─────────────────────────
def unable_load(path):
    """기억 파일 → {"hits": ['YYYY-MM-DD'…], "until": 'YYYY-MM-DD'|''}."""
    try:
        with open(path, encoding="utf-8-sig") as f:
            o = json.load(f)
    except (OSError, ValueError):
        return {"hits": [], "until": ""}
    if not isinstance(o, dict):
        return {"hits": [], "until": ""}
    hits = [str(h)[:10] for h in (o.get("hits") or []) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(h)[:10])]
    return {"hits": sorted(set(hits)), "until": str(o.get("until") or "")[:10]}


def unable_active(st, today):
    """지금 생략할 때인가 — 확정(until)이 있고 오늘이 그날 이하."""
    u = str((st or {}).get("until") or "")
    return bool(u) and today.isoformat() <= u


def unable_note(st, today):
    """오늘 '조회 불가'를 받았다 → (새 기억, 이번에 확정됐나). TTL 밖 관측은 버리고, 서로 다른 날 2회면 오늘+14일까지 생략."""
    lo = (today - timedelta(days=UNABLE_TTL_DAYS)).isoformat()
    hits = sorted({h for h in (st or {}).get("hits") or [] if h >= lo} | {today.isoformat()})
    until = str((st or {}).get("until") or "")
    confirmed = False
    if len(hits) >= 2:
        until = (today + timedelta(days=UNABLE_TTL_DAYS)).isoformat()
        confirmed = True
    return {"hits": hits, "until": until}, confirmed


def unable_save(path, st):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"hits": st.get("hits") or [], "until": st.get("until") or "",
                       "note": "Copilot 이 메일 조회 불가로 답한 날들 — 서로 다른 날 2회면 until 까지 생략(재시도: --retry-copilot "
                               "또는 이 파일 삭제)"}, f, ensure_ascii=False, indent=1)
    except OSError:
        pass


def unable_clear(path):
    try:
        os.remove(path)
    except OSError:
        pass


def parse_ranges(text):
    """--ranges 'A:B,C~D,E' 또는 '@파일'(같은 글 또는 JSON [[A,B],…]) → [('YYYY-MM-DD','YYYY-MM-DD')] 날짜순·겹침 합침.
    잘못된 조각은 버린다."""
    t = str(text or "").strip()
    if t.startswith("@"):
        try:
            with open(t[1:], encoding="utf-8-sig") as f:
                raw = f.read()
        except OSError:
            return []
        try:
            o = json.loads(raw)
            t = ",".join(f"{x[0]}:{x[-1]}" if isinstance(x, (list, tuple)) else str(x) for x in o)
        except (ValueError, TypeError, IndexError):
            t = raw
    out = []
    for part in re.split(r"[,;\s]+", t):
        ds = re.findall(r"\d{4}-\d{2}-\d{2}", part)
        if not ds:
            continue
        try:
            a, b = date.fromisoformat(ds[0]), date.fromisoformat(ds[-1])
        except ValueError:
            continue
        out.append((min(a, b), max(a, b)))
    out.sort()
    merged = []
    for a, b in out:
        if merged and a <= merged[-1][1] + timedelta(days=1):
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    return [(a.isoformat(), b.isoformat()) for a, b in merged]


def clip_ranges(ranges, d0, d1):
    """구간 목록을 [d0, d1] 안으로 자른다(기간 밖은 묻지 않는다) — 'YYYY-MM-DD' 문자열."""
    out = []
    for a, b in ranges or ():
        a, b = max(a, d0), min(b, d1)
        if a <= b:
            out.append((a, b))
    return out


def emit_status(rc, reasons=(), counts=None, ranges=None, src="copilot"):
    """수집기 마지막 줄 — 'AF32STATUS ' + JSON 한 줄(숫자·짧은 사유만)."""
    rs = ",".join(dict.fromkeys(r for r in reasons if r))
    print("AF32STATUS " + json.dumps({"v": 1, "src": src, "rc": int(rc), "reason": rs, "counts": counts or {},
                                    "ranges": ranges or []}, ensure_ascii=False))
    sys.stdout.flush()


def slices_of(d0, d1, days=30):
    a = datetime.strptime(d0, "%Y-%m-%d")
    b = datetime.strptime(d1, "%Y-%m-%d")
    outs, cur = [], a
    while cur <= b:
        end = min(cur + timedelta(days=days - 1), b)
        outs.append((cur.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")))
        cur = end + timedelta(days=1)
    return outs


def _span_days(s0, s1):
    return (datetime.strptime(s1, "%Y-%m-%d") - datetime.strptime(s0, "%Y-%m-%d")).days + 1


def _refine(kind, s0, s1, alt, days, take, one_slice=None):
    """s0~s1 을 days 일 조각으로 다시 물어 take 에 넣는다. 조각이 또 140행 이상이면 1일까지 쪼갠다(그 아래는 경고만).
    one_slice 는 시험용 주입점(기본 _one_slice)."""
    q = one_slice or _one_slice
    for t0s, t1s in slices_of(s0, s1, days):
        got = q(kind, t0s, t1s, alt)[0]
        add = take(got)
        full = len(got) >= FULL_N
        print(f"[mail-copilot]     {t0s}~{t1s}: +{add}건"
              + (" (140행 이상 — 1일 조각에서도 잘림 가능)" if full and days <= 1 else ""))
        if full and days > 1:
            print(f"[mail-copilot]     {t0s}~{t1s}: {len(got)}건(잘림 의심) → 1일 조각 재질의")
            _refine(kind, t0s, t1s, alt, 1, take, q)


def collect_kind(kind, d0, d1, ctx=None, one_slice=None, ranges=None, dst=None):
    """한 종류(mail|cal)를 7일 조각으로 왕복 → (받은 행 수, unable 여부, fatal 여부, 조각 결과 [(from, to, 상태)], 남긴 행 수).
    ranges(다른 경로가 확인하지 못한 날의 구간 목록)가 있으면 그 구간만, 없으면 d0~d1. 표를 받은 조각마다 그 조각의 행을 G1 으로
    정제해 병합 저장한다(ctx 가 없으면 저장하지 않는다 — 시험용). one_slice 는 시험용 주입점(기본 _one_slice)."""
    q = one_slice or _one_slice
    spans = list(ranges) if ranges else [(d0, d1)]
    sl = [c for a, b in spans for c in slices_of(a, b, CHUNK_DAYS)]
    print(f"[mail-copilot] {kind}: {len(spans)}구간 → {len(sl)}조각 왕복 ({CHUNK_DAYS}일 단위)")
    rows, seen, chunks = [], set(), []
    kept = 0

    def take(batch):
        n = 0
        for r in batch:
            k = (r[0], r[1], r[2]) if kind == "mail" else (r[0], r[1])
            if k not in seen:
                seen.add(k)
                rows.append(r)
                n += 1
        return n

    alt, errs, unable, fatal = False, 0, False, False
    for i, (s0, s1) in enumerate(sl):
        print(f"[mail-copilot] {kind} {i + 1}/{len(sl)} 조각 {s0}~{s1}")
        got, st = q(kind, s0, s1, alt)
        if st == "fatal":
            print(f"[mail-copilot] Copilot 을 쓸 수 없어 남은 {len(sl) - i}조각을 생략합니다 "
                  "(로그인 뒤 다시 실행하면 이어서 모읍니다)")
            fatal = True
            break
        if st == "unable" and not alt:
            print("[mail-copilot]   '조회 불가' 응답 — 검색형 화법으로 전환해 재시도")
            alt = True
            got, st = q(kind, s0, s1, alt)
        if st == "unable":
            print(f"[mail-copilot] Copilot 이 {kind} 조회를 지원하지 않는 응답 — 남은 조각 생략")
            unable = True
            break
        if st == "error":
            errs += 1
            chunks.append((s0, s1, st))
            if errs >= ERR_MAX:
                print(f"[mail-copilot] {ERR_MAX}조각 연속 답을 받지 못해 중단 (판정용 Copilot 세션 보호)")
                break
            continue
        errs = 0
        n0 = len(rows)
        take(got)
        if st == "table" and len(got) >= FULL_N and _span_days(s0, s1) > REFINE_DAYS:
            print(f"[mail-copilot]   {len(got)}건 (150행 상한에 잘림) → {REFINE_DAYS}일 조각 재질의")
            _refine(kind, s0, s1, alt, REFINE_DAYS, take, q)
        chunks.append((s0, s1, st))
        if st == "table" and ctx is not None and dst:
            kept += save_g1(kind, rows[n0:], dst, ctx, [(s0, s1)])    # 이 조각의 옛 행만 바뀐다(증분)
        print(f"[mail-copilot]   {'없음' if st == 'empty' else st} · 누적 {len(rows)}건")
    n = len(rows)
    rows.clear()                            # 답에서 읽은 행은 정제 파일에 쓴 뒤 더 들고 있지 않는다
    return n, unable, fatal, chunks, kept


def _precision_counts(out_dir, name):
    """방금 쓴 정제 메일 파일의 (전체, 날짜만) 통수 — 수만."""
    p = os.path.join(out_dir, name)
    n_all = n_date = 0
    try:
        with open(p, encoding="utf-8-sig", errors="replace") as f:
            for r in csv.DictReader(f):
                n_all += 1
                if (r.get("time_precision") or "").strip().lower() == "date":
                    n_date += 1
    except OSError:
        return 0, 0
    return n_all, n_date


def chunk_ranges(kind, chunks):
    """조각 결과 → AF32STATUS ranges — 표를 받은 조각은 partial(Copilot 은 증인이지 '읽음'이 아니다), 그 밖은 unverified."""
    axes = ("mail_in", "mail_out") if kind == "mail" else ("cal",)
    out = []
    for a, b, st in chunks:
        for ax in axes:
            out.append({"axis": ax, "from": a, "to": b, "st": "partial" if st == "table" else "unverified"})
    return out


def _setup(cfg, d0s, d1s):
    """시작 확인·기간·G1 문맥 → (cfg2, d0 'YYYY-MM-DD', d1, ctx) 또는 (rc, 사유). Copilot 을 열기 전에 확인한다."""
    import afcfg
    import consent
    import period
    import privacy
    try:
        consent.require(ROOT, cfg)
    except consent.ConsentRequired as e:
        print(f"[mail-copilot] {e.message} — Copilot 에 묻지 않았습니다")
        return 3, "R-CONSENT"
    cfg2, _w = afcfg.effective(cfg)
    try:
        d0, d1, info = period.clamp(d0s or None, d1s or None, cfg2)
    except ValueError as e:
        print(f"[mail-copilot] {e}")
        return 3, "R-ARGS"
    if info.get("clamped"):
        print("[mail-copilot] " + period.notice_text(info, d0, d1, cfg2))
    try:
        ctx = privacy.G1Context(cfg2, ROOT, src="copilot", period=(d0, d1))
    except privacy.RestrictedListError as e:
        print(f"[mail-copilot] {e.message}")
        return 4, "R-NORESTRICTED"
    except privacy.SetupRefused as e:
        print(f"[mail-copilot] {e.message}")
        return 4, "R-NODOMAIN"
    return cfg2, d0.isoformat(), d1.isoformat(), ctx


def _clear_site():
    """전용 Edge 의 Outlook·M365 사이트 자료(캐시·저장소 — 쿠키는 남김)를 지운다(D13). Copilot 을 쓴 실행에서만."""
    if "m" not in _CA:
        return
    try:
        ca = _ca()
        ca.clear_site_data(ca.load_cfg()["port"])
    except Exception as e:  # noqa: BLE001 — 지우기 실패는 run.py 수집 끝에서 다시 지운다
        print(f"[mail-copilot] 전용 Edge 의 사이트 자료를 지우지 못했습니다({type(e).__name__}) — 수집 끝에 다시 지웁니다")


def main():
    import mailmerge
    only = arg("--only")            # 'mail' | 'cal' — run.py 가 필요한 종류만 지정
    tag = arg("--tag") or "copilot"
    src_name = tag
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,24}", tag):
        print(f"[mail-copilot] --tag 값이 올바르지 않습니다: {tag}")
        emit_status(3, ["R-ARGS"])
        return 3
    out_arg = arg("--out-dir")
    out_dir = (out_arg if os.path.isabs(out_arg) else os.path.join(ROOT, out_arg)) if out_arg else OUT_DIR
    paths = {"mail": os.path.join(out_dir, f"mail_{tag}.csv"), "cal": os.path.join(out_dir, f"cal_{tag}.csv")}
    src_p = os.path.join(out_dir, f"mail_source_{tag}.json")
    flag_p = os.path.join(out_dir, "mail_copilot_unavailable.json")
    try:
        with open(os.path.join(ROOT, "config", "config.json"), encoding="utf-8-sig") as f:
            cfg = json.load(f)
        cfg = cfg if isinstance(cfg, dict) else {}
    except (OSError, ValueError):
        cfg = {}
    st = _setup(cfg, arg("--from"), arg("--to"))
    if isinstance(st[0], int):
        emit_status(st[0], [st[1]], src=src_name)
        return st[0]
    cfg, d0, d1, ctx = st
    ranges = clip_ranges(parse_ranges(arg("--ranges")), d0, d1) if "--ranges" in sys.argv else None
    # 일정 조각의 구간(없으면 --ranges). run.py 가 메일·일정의 미확인 구간이 달라도 한 프로세스로 부른다(채팅 하나)
    ranges_cal = clip_ranges(parse_ranges(arg("--ranges-cal")), d0, d1) if "--ranges-cal" in sys.argv else ranges
    rng_by = {"mail": ranges, "cal": ranges_cal}
    if all(r is not None and not r for r in rng_by.values()):
        print("[mail-copilot] --ranges 에 물을 날이 없습니다 — 왕복 생략")
        emit_status(0, [], {"chunks": 0}, src=src_name)
        return 0
    today = date.today()
    ust = unable_load(flag_p)
    if "--retry-copilot" in sys.argv:
        ust = {"hits": [], "until": ""}
        unable_clear(flag_p)
    if unable_active(ust, today):
        print(f"[mail-copilot] 이 계정의 Copilot 은 메일 조회 불가로 확인됨(서로 다른 날 2회 — {ust['until']} 까지 왕복 생략)")
        print(f"               (재시도: --retry-copilot 또는 {flag_p} 삭제)")
        emit_status(3, ["R-UNABLE"], {"unable_until": ust["until"]}, src=src_name)
        return 3
    todo = [k for k in ("mail", "cal") if (not only or k == only) and not (rng_by[k] is not None and not rng_by[k])]
    if not todo:
        emit_status(0, [], {"skipped": 1}, src=src_name)
        return 0
    total, unable_kinds, counts, out_ranges = 0, set(), {}, []
    tally = {"chunks": 0, "table": 0, "empty": 0, "other": 0, "error": 0, "blocked": 0}
    fatal = False
    LAST_FATAL.clear()
    try:
        for kind in todo:
            n, unable, fat, chunks, kept = collect_kind(kind, d0, d1, ctx, ranges=rng_by[kind], dst=paths[kind])
            total += n
            counts[kind] = n
            if unable:
                unable_kinds.add(kind)
            for _a, _b, cst in chunks:
                tally["chunks"] += 1
                tally[cst] = tally.get(cst, 0) + 1
            out_ranges += chunk_ranges(kind, chunks)
            print(f"[mail-copilot] {kind}: {n}건 받음 → 정제 뒤 {kept}건 남김(병합 저장)")
            if fat:
                fatal = True
                break                       # 로그인 등 사람이 풀 실패 — 다음 종류도 똑같다
    finally:
        _clear_site()
    g1 = ctx.finish()
    try:
        mailmerge.save_g1_counts(out_dir, tag, g1)
    except OSError:
        pass
    if total:
        try:
            os.makedirs(out_dir, exist_ok=True)
            _pa, _pd = _precision_counts(out_dir, os.path.basename(paths["mail"]))
            src = {"product": "AgentFinder32", "source": tag, "when": datetime.now().strftime("%Y-%m-%d"),
                   "kinds": todo, "rows": total, "mail": counts.get("mail", 0), "calendar": counts.get("cal", 0),
                   "me": [], "mail_rows": _pa, "date_only": _pd, "warnings": [],
                   "ranges": [list(x) for x in ranges] if ranges else [[d0, d1]], "counts": dict(tally)}
            if ranges_cal is not ranges:
                src["ranges_cal"] = [list(x) for x in ranges_cal] if ranges_cal else [[d0, d1]]
            with open(src_p, "w", encoding="utf-8") as f:
                json.dump(src, f, ensure_ascii=False)
        except OSError:
            pass
    counts_out = dict(tally, rows=total, mail=counts.get("mail", 0), cal=counts.get("cal", 0),
                      g1={"kept": dict(g1.get("kept") or {}), "excluded": dict(g1.get("excluded") or {})})
    if fatal:
        ph = LAST_FATAL.get("phase") or ""
        why = LAST_FATAL.get("reason") or ("R-LOGIN" if ph == "login_required" else "R-EDGELAUNCH")
        emit_status(2 if ph == "login_required" else 3, [why], counts_out, out_ranges, src=src_name)
        return 2 if ph == "login_required" else 3
    if total == 0:
        # '불가' 기억은 메일 조회가 막혔을 때만 — 서로 다른 날 2회여야 14일 생략
        if "mail" in unable_kinds:
            ust, confirmed = unable_note(ust, today)
            unable_save(flag_p, ust)
            print("               (" + (f"서로 다른 날 2회 확인 — {ust['until']} 까지 Copilot 메일 왕복을 생략합니다)"
                                       if confirmed else "1회 기록 — 다른 날 한 번 더 같은 답이면 14일 동안 생략합니다)"))
            emit_status(3, ["R-UNABLE"], counts_out, out_ranges, src=src_name)
            return 3
        answered = tally.get("empty", 0) + tally.get("other", 0)
        if not answered:
            why = "R-GATE" if tally.get("blocked") and not tally.get("error") else "R-NOREPLY"
            print("[mail-copilot] 표를 얻지 못했습니다(답 없음·관문에 막힘)")
            emit_status(3, [why], counts_out, out_ranges, src=src_name)
            return 3
        print("[mail-copilot] 표를 얻지 못했습니다('없음' 또는 표 아닌 답)")
        emit_status(0, [], counts_out, out_ranges, src=src_name)
        return 0
    if ust.get("hits") or ust.get("until"):
        unable_clear(flag_p)           # 표를 받았다 — 조건이 바뀌었다(기억 해제)
    emit_status(0, [], counts_out, out_ranges, src=src_name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
