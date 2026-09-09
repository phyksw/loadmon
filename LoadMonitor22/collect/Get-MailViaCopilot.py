# -*- coding: utf-8 -*-
"""
Get-MailViaCopilot.py — Outlook 메일·일정을 M365 Copilot 무개입 왕복으로 추출한다 (폴백).

클래식 Outlook COM 이 없는 PC(새 Outlook 전용·COM 미등록·마법사에 막힘)와 Windows Search
색인 폴백마저 비는 PC 를 위한 마지막 경로. Copilot 은 내 사서함 데이터에 접근하므로
Outlook 버전·설치 형태와 무관하게 동작한다(최초 1회 로그인만 필요).

  python collect\\Get-MailViaCopilot.py --from 2026-05-19 --to 2026-08-17 [--force]

출력: data\\outlook\\mail.csv      (box,time,sender,subject,conversation,rcv,time_precision)   ← COM 스키마 + 정밀도 열
                                  time_precision: minute(시각 있음) | date(날짜만 답해 12:00 으로 둔 행 — 시간 근거로 쓰지 말 것)
                                  Copilot 에는 앞 6열(MAIL_HDR_ASK)만 묻는다 — 정밀도는 시각 해석 결과로 우리가 정한다. 7열로
                                  답해 와도 파서가 그 열을 떼어 낸다(예전엔 7열 헤더를 묻고 6열로 읽어 subject·rcv 가 밀렸다, C1).
      data\\outlook\\calendar.csv  (start,end,all_day,busy_status,subject,categories,location,response,meeting_status)
                                  ※ response/meeting_status 는 COM 수집기(Get-OutlookData.ps1)만 채운다 — 여기선 빈값
기존 파일에 자료가 있으면 덮어쓰지 않는다(--force 로 강제) — COM·색인이 이미 모은 것을 지키기 위해.
시각 표기는 ISO 'T'/'Z'·슬래시·점·한국어 연월일·오전/오후 를 모두 받는다(예전엔 행째 버렸다). 한 조각의 회수가
140행 이상이면(요청 상한 150 에 근접 = 잘림) 5일 조각으로 다시 묻는다.
"""
import csv
import hashlib
import io
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta

if __name__ == "__main__":      # import 시(파서 재사용·테스트) stdout을 건드리지 않는다
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, errors="replace", encoding=(
        (sys.stdout.encoding or "utf-8") if sys.stdout.isatty() else "utf-8"))  # 콘솔(bat)=콘솔 코드페이지 · 파이프(UI)=utf-8
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NO_WIN = 0x08000000
OUT_DIR = os.path.join(ROOT, "data", "outlook")
MAIL_HDR = "box,time,sender,subject,conversation,rcv,time_precision"
MAIL_HDR_ASK = "box,time,sender,subject,conversation,rcv"      # Copilot 에 묻는 열 — time_precision 은 묻지 않는다(C1)
CAL_HDR = "start,end,all_day,busy_status,subject,categories,location,response,meeting_status"
CAL_HDR_ASK = "start,end,all_day,busy_status,subject,categories,location"   # Copilot 에 묻는 열 — 응답 상태는 물을 수 없다
UNAVAILABLE_FLAG = os.path.join(OUT_DIR, "mail_copilot_unavailable.json")
FULL_N = 140                    # 한 조각 회수가 이 이상이면 150행 상한에 잘린 것으로 보고 5일 조각으로 재질의


def arg(flag, d=""):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else d


def build_prompt(kind, d0, d1, alt=False):
    """kind: mail | cal.  alt=검색형 화법(일괄 내보내기를 '조회 불가'로 거절하는 Copilot 대응)"""
    if kind == "mail":
        head = (f"내 Outlook 메일(받은 편지함과 보낸 편지함)에서 {d0}~{d1} 기간의 메일을 검색해줘. "
                "찾은 메일을 아래 CSV 형식 표로만 정리해줘(찾은 만큼만). 헤더 포함, 다른 설명 없이, "
                "코드 블록(```)으로:\n") if alt else (
                f"{d0}부터 {d1}까지 내 Outlook 받은 편지함과 보낸 편지함의 메일을 조회해서 아래 CSV "
                "형식으로만 출력해줘. 헤더 포함, 다른 설명 없이, 코드 블록(```)으로:\n")
        return (head + MAIL_HDR_ASK + "\n"
                "- box : 받은 메일이면 inbox, 내가 보낸 메일이면 sent\n"
                "- time : YYYY-MM-DD HH:MM (받은 시각 또는 보낸 시각)\n"
                "- sender : 보낸 사람 이름\n"
                "- subject : 제목\n"
                "- conversation : 스레드 제목 (RE:/FW: 를 뗀 원래 제목)\n"
                "- rcv : 받은 메일에서 내가 받는 사람(To)이면 to, 참조(CC)면 cc, 단체 배포·공지면 bulk. "
                "보낸 메일은 빈칸\n"
                '- 칸 안에 쉼표가 들어가면 그 칸을 따옴표("...")로 감싸\n'
                "- 자동 알림·광고·시스템 메일은 제외\n"
                "- 기간 안의 메일을 빠짐없이 뒤져서 최대 150행까지 출력\n"
                "- 조회 결과가 정말 없으면 '없음' 한 단어만 출력\n"
                "★ 실제로 검색된 메일만 출력하라 — 예시·가상·추정으로 행을 만들지 마라. "
                "검색이 안 되거나 확실하지 않은 행은 빼라. 행 수를 채우는 것보다 진짜만 적는 것이 중요하다.\n")
    head = (f"내 Outlook 일정(캘린더)에서 {d0}~{d1} 기간의 일정·회의를 검색해줘. "
            "찾은 일정을 아래 CSV 형식 표로만 정리해줘(찾은 만큼만). 헤더 포함, 다른 설명 없이, "
            "코드 블록(```)으로:\n") if alt else (
            f"{d0}부터 {d1}까지 내 Outlook 일정(캘린더)의 일정·회의를 조회해서 아래 CSV "
            "형식으로만 출력해줘. 헤더 포함, 다른 설명 없이, 코드 블록(```)으로:\n")
    return (head + CAL_HDR_ASK + "\n"
            "- start / end : YYYY-MM-DD HH:MM\n"
            "- all_day : 종일 일정이면 True, 아니면 False\n"
            "- busy_status : 바쁨 2, 미정 1, 한가함 0, 부재중 3 (숫자)\n"
            "- subject : 일정 제목\n"
            "- categories : 범주 (없으면 빈칸)\n"
            "- location : 장소 또는 Teams 회의 (없으면 빈칸)\n"
            '- 칸 안에 쉼표가 들어가면 그 칸을 따옴표("...")로 감싸\n'
            "- 반복 일정은 기간 안의 회차마다 한 행\n"
            "- 기간 안의 일정을 빠짐없이 뒤져서 최대 150행까지 출력\n"
            "- 조회 결과가 정말 없으면 '없음' 한 단어만 출력\n"
            "★ 실제로 검색된 일정만 출력하라 — 예시·가상·추정으로 행을 만들지 마라.\n")


UNABLE_MARKS = ("조회 불가", "조회가 불가", "조회할 수 없", "검색할 수 없", "검색이 불가",
                "액세스할 수 없", "접근할 수 없", "권한이 없", "지원되지 않", "지원하지 않",
                "제공되지 않", "cannot search", "can't search", "unable to", "no access",
                "don't have access", "조회 도구가 없", "데이터 조회 도구", "연결된 도구가 없",
                "도구가 없어", "no connected tool")
EMPTY_MARKS = ("없음", "찾을 수 없", "검색 결과가 없", "메일이 없", "일정이 없", "no emails",
               "no events", "couldn't find", "could not find")
RCV_OK = ("to", "cc", "bulk", "")
BUSY_WORDS = {"바쁨": "2", "busy": "2", "미정": "1", "tentative": "1", "한가함": "0", "free": "0",
              "부재중": "3", "부재": "3", "oof": "3", "out of office": "3"}


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
    """시각 문자열 → (norm 'YYYY-MM-DD HH:MM', precision 'minute'|'date', utc_marked)
    받는 표기: '2026-06-03 9:05' · '2026-06-03T14:00:00Z' · '2026/06/03 14:00' · '2026.06.03 14:00' · '2026년 6월 3일 오후 2:10'
    · '2026-06-03'(날짜만 → 12:00, precision=date). 시각이 이상하면 ('', '', False) — 날짜만 맞다고 잘린 값을 저장하면
    분석기가 조용히 버린다. 날짜만 있는 행을 00:00 으로 두면 발신 메일이 '새벽 산출물'(야근일)이 된다(감사 outlook-12)."""
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


def _norm_time(s):
    """호환용: _parse_time 의 정규화 문자열만"""
    return _parse_time(s)[0]


def _conv_token(conv):
    """storeMailSubject=false 일 때 conversation 열의 대체값 — 원문 대신 짧은 해시(회신 이력 판정만 유지)"""
    s = re.sub(r"\s+", " ", str(conv or "")).strip().lower()
    return "#" + hashlib.sha1(s.encode("utf-8")).hexdigest()[:10] if s else ""


def _split(raw):
    if raw.startswith("|"):
        return [c.strip() for c in raw.strip("|").split("|")]
    try:
        return [c.strip() for c in next(csv.reader([raw]))]
    except (csv.Error, StopIteration):
        return [c.strip() for c in raw.split(",")]


def parse_mail_rows(reply, diag=None):
    """CSV/마크다운 표 관용 파싱 → [box,time,sender,subject,conversation,rcv,time_precision] 목록
    diag(dict) 에 date_only·utc_marked·bad_time 건수를 더한다.
    7열(time_precision 까지) 답은 그 열을 떼고 6열 로직으로 — 정밀도는 _parse_time 결과로만 정한다(C1)."""
    rows = []
    diag = diag if diag is not None else {}
    for ln in (reply or "").splitlines():
        raw = ln.strip().strip("`").strip()
        if not raw or re.match(r"^box\s*[,|]", raw, re.I) or re.match(r"^\|?[-\s|]+$", raw):
            continue
        parts = _split(raw)
        # 마지막 칸이 정밀도 어휘(minute/date)면 뗀다. 빈 칸이면 그 앞 칸이 rcv 어휘일 때만 —
        # '제목의 따옴표 없는 쉼표 + 빈 rcv' 로 밀린 6열 행(아래 복구 로직 대상)과 구분한다.
        if len(parts) >= 7 and (parts[-1].lower() in ("minute", "date")
                                or (parts[-1] == "" and parts[-2].lower() in RCV_OK)):
            parts = parts[:-1]
        if len(parts) > 6:
            # 따옴표 없는 쉼표(제목)로 열이 밀리면 — box/time 은 앞, rcv 는 맨 뒤 어휘로 고정
            tail = parts[-1].lower() if parts[-1].lower() in RCV_OK else None
            if tail is not None:
                mid = parts[3:-2]
                parts = [parts[0], parts[1], parts[2], ",".join(mid), parts[-2], parts[-1]]
            else:
                parts = [parts[0], parts[1], parts[2], ",".join(parts[3:-1]), parts[-1], ""]
        if len(parts) < 6:
            parts = parts + [""] * (6 - len(parts))
        box = parts[0].lower()
        if box in ("받은", "받은 편지함", "inbox", "수신"):
            box = "inbox"
        elif box in ("보낸", "보낸 편지함", "sent", "발신"):
            box = "sent"
        if box not in ("inbox", "sent"):
            continue
        t, prec, utc = _parse_time(parts[1])
        if not t:
            diag["bad_time"] = diag.get("bad_time", 0) + 1
            continue
        if prec == "date":
            diag["date_only"] = diag.get("date_only", 0) + 1
        if utc:
            diag["utc_marked"] = diag.get("utc_marked", 0) + 1
        rcv = parts[5].lower()
        if rcv not in RCV_OK:
            rcv = "to" if box == "inbox" else ""
        if box == "sent":
            rcv = ""
        conv = parts[4] or re.sub(r"^((RE|FW|FWD|답장|전달|회신)\s*:\s*)+", "", parts[3], flags=re.I)
        rows.append([box, t, parts[2], parts[3], conv, rcv, prec])
    return rows


def parse_cal_rows(reply, diag=None):
    rows = []
    diag = diag if diag is not None else {}
    for ln in (reply or "").splitlines():
        raw = ln.strip().strip("`").strip()
        if not raw or re.match(r"^start\s*[,|]", raw, re.I) or re.match(r"^\|?[-\s|]+$", raw):
            continue
        parts = _split(raw)
        if len(parts) > 7:
            # subject 의 쉼표로 밀림 — start/end/all_day/busy 는 앞 4칸, 뒤 2칸(categories,location) 고정
            parts = parts[:4] + [",".join(parts[4:-2]), parts[-2], parts[-1]]
        if len(parts) < 7:
            parts = parts + [""] * (7 - len(parts))
        (st, ps, _u1), (en, pe, _u2) = _parse_time(parts[0]), _parse_time(parts[1])
        if not (st and en):
            diag["bad_time"] = diag.get("bad_time", 0) + 1
            continue
        ad = "True" if parts[2].strip().lower() in ("true", "1", "yes", "y", "종일") else "False"
        # 날짜만 답한 일정은 종일 일정으로 본다 — 시작 00:00 · 끝 23:59 (12:00 짜리 회의로 두지 않는다)
        if ps == "date":
            st = st[:10] + " 00:00"
        if pe == "date":
            en = en[:10] + " 23:59"
        if ps == "date" and pe == "date":
            ad = "True"
        bs = parts[3].strip().lower()
        bs = bs if bs in ("0", "1", "2", "3") else BUSY_WORDS.get(bs, "2")
        rows.append([st, en, ad, bs, parts[4], parts[5], parts[6]])
    return rows


def _timeout():
    try:
        with open(os.path.join(ROOT, "config", "config.json"), encoding="utf-8-sig") as f:
            sec = float(((json.load(f).get("copilotAuto") or {}).get("replyTimeoutSec")) or 240)
    except (OSError, ValueError, TypeError):
        sec = 240.0
    return max(900.0, sec * 3 + 180)


def _one_slice(kind, s0, s1, alt=False):
    """한 조각(<=30일) 왕복 → (행 목록, 상태) — 상태: table|unable|empty|other"""
    prompt = build_prompt(kind, s0, s1, alt)
    tf = os.path.join(ROOT, "data", f"mail_prompt_{kind}.txt")
    os.makedirs(os.path.dirname(tf), exist_ok=True)
    with open(tf, "w", encoding="utf-8") as f:
        f.write(prompt)
    try:
        out = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "copilot_auto.py"),
                              "--send", tf], capture_output=True, timeout=_timeout(), cwd=ROOT,
                             env=dict(os.environ, PYTHONIOENCODING="utf-8"), creationflags=NO_WIN)
    except subprocess.TimeoutExpired:
        print(f"[mail-copilot]   {kind} {s0}~{s1}: 왕복 시간 초과 — 이 조각 건너뜀")
        return [], "other"
    except OSError as e:
        print(f"[mail-copilot]   {kind} {s0}~{s1}: 드라이버 실행 실패({type(e).__name__})")
        return [], "other"
    txt = (out.stdout or b"").decode("utf-8", "replace").strip()
    try:
        res = json.loads(txt.splitlines()[-1])
    except Exception:
        print(f"[mail-copilot]   {kind} {s0}~{s1}: 드라이버 응답 해석 실패")
        return [], "other"
    if not res.get("ok"):
        print(f"[mail-copilot]   {kind} {s0}~{s1}: 실패 — {res.get('error', '')}")
        return [], "other"
    reply = res.get("reply", "")
    try:                                    # 원문 응답 보존 — 진위·누락 진단용
        rd = os.path.join(OUT_DIR, "replies")
        os.makedirs(rd, exist_ok=True)
        with open(os.path.join(rd, f"{kind}_{s0}_{s1}.txt"), "w", encoding="utf-8") as f:
            f.write(reply)
    except OSError:
        pass
    diag = {}
    rows = parse_mail_rows(reply, diag) if kind == "mail" else parse_cal_rows(reply, diag)
    # 환각 방어: 요청 구간 밖 날짜의 행은 버린다 (팀즈 경로와 동일 규칙)
    good = [r for r in rows if s0 <= r[0 if kind == "cal" else 1][:10] <= s1]
    if len(good) < len(rows):
        print(f"[mail-copilot]   {kind} {s0}~{s1}: 기간 밖 날짜 {len(rows) - len(good)}행 제외 (환각/오검색 의심)")
    notes = []
    if diag.get("date_only"):
        notes.append(f"날짜만 답한 행 {diag['date_only']}(12:00·time_precision=date)")
    if diag.get("utc_marked"):
        notes.append(f"UTC 표기 행 {diag['utc_marked']} — config.mm.mailTimeOffsetH 확인")
    if diag.get("bad_time"):
        notes.append(f"시각 해석 불가 행 {diag['bad_time']} 제외")
    if notes:
        print(f"[mail-copilot]   {kind} {s0}~{s1}: " + " · ".join(notes))
    return good, ("table" if good else _reply_status(reply))


def _esc(s):
    s = re.sub(r"[\r\n]+", " ", str(s or ""))
    return '"' + s.replace('"', '""') + '"' if ("," in s or '"' in s) else s


def _has_data(path):
    try:
        with open(path, encoding="utf-8-sig") as f:
            return sum(1 for ln in f if ln.strip()) > 1
    except OSError:
        return False


def _save(kind, rows, store_subject):
    dst = os.path.join(OUT_DIR, "mail.csv" if kind == "mail" else "calendar.csv")
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(dst, "w", encoding="utf-8-sig", newline="") as f:
        f.write((MAIL_HDR if kind == "mail" else CAL_HDR) + "\n")
        hdr_n = (MAIL_HDR if kind == "mail" else CAL_HDR).count(",") + 1
        for r in rows:
            r = list(r)
            r += [""] * (hdr_n - len(r))     # 새 열(response,meeting_status)은 빈값 — 열 수가 모자라면 extract._read 가 행을 버린다
            if not store_subject:           # config.storeMailSubject=false 면 제목을 남기지 않는다(COM 경로와 동일) — conversation 은 해시
                if kind == "mail":
                    r[3] = ""
                    r[4] = _conv_token(r[4])
                else:
                    r[4] = ""
            f.write(",".join(_esc(c) for c in r) + "\n")
    return dst


def slices_of(d0, d1, days=30):
    a = datetime.strptime(d0, "%Y-%m-%d")
    b = datetime.strptime(d1, "%Y-%m-%d")
    outs, cur = [], a
    while cur <= b:
        end = min(cur + timedelta(days=days - 1), b)
        outs.append((cur.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")))
        cur = end + timedelta(days=1)
    return outs


def need_subdivide(n_rows, span_days):
    return span_days > 12 and (n_rows < 5 or n_rows >= 35)


def _span_days(s0, s1):
    return (datetime.strptime(s1, "%Y-%m-%d") - datetime.strptime(s0, "%Y-%m-%d")).days + 1


def _refine(kind, s0, s1, alt, days, take, one_slice=None):
    """s0~s1 을 days 일 조각으로 다시 물어 take 에 넣는다. 조각이 또 140행 이상이면 5일까지 쪼갠다(그 아래는 경고만).
    one_slice 는 시험용 주입점(기본 _one_slice)."""
    q = one_slice or _one_slice
    for t0s, t1s in slices_of(s0, s1, days):
        got = q(kind, t0s, t1s, alt)[0]
        add = take(got)
        full = len(got) >= FULL_N
        print(f"[mail-copilot]     {t0s}~{t1s}: +{add}건"
              + (" (140행 이상 — 5일 조각에서도 잘림 가능)" if full and days <= 5 else ""))
        if full and days > 5:
            print(f"[mail-copilot]     {t0s}~{t1s}: {len(got)}건(잘림 의심) → 5일 조각 재질의")
            _refine(kind, t0s, t1s, alt, 5, take, q)


def collect_kind(kind, d0, d1, store_subject, one_slice=None):
    """한 종류(mail|cal)를 30일 조각으로 왕복 → (저장 행 수, 'unable' 여부).
    회수가 140행 이상(150행 상한에 잘림)이면 5일, 35~139행이면 10일 조각(그 안에서 140행이면 다시 5일)로 재질의.
    one_slice 는 시험용 주입점(기본 _one_slice)."""
    q = one_slice or _one_slice
    sl = slices_of(d0, d1)
    print(f"[mail-copilot] {kind}: {d0}~{d1} → {len(sl)}조각 왕복 (30일 단위)")
    rows, seen = [], set()
    kidx = 0 if kind == "cal" else 1

    def take(batch):
        n = 0
        for r in batch:
            # 메일은 제목까지 키에 넣는다 — 같은 분에 보낸 발신 메일은 전부 sender='나'라 (box,time,sender)만으로는 서로 지워진다
            k = (r[0], r[1], r[2], r[3]) if kind == "mail" else (r[0], r[1], r[4])
            if k not in seen:
                seen.add(k)
                rows.append(r)
                n += 1
        return n

    alt, fails, unable = False, 0, False
    for i, (s0, s1) in enumerate(sl):
        print(f"[mail-copilot] {kind} {i + 1}/{len(sl)} 조각 {s0}~{s1}")
        got, st = q(kind, s0, s1, alt)
        if st == "unable" and not alt:
            print("[mail-copilot]   '조회 불가' 응답 — 검색형 화법으로 전환해 재시도")
            alt = True
            got, st = q(kind, s0, s1, alt)
        if st == "unable":
            print(f"[mail-copilot] Copilot 이 {kind} 조회를 지원하지 않는 응답 — 남은 조각 생략")
            unable = True
            break
        if st in ("other", "empty") and not got:
            fails += 1
            if fails >= 3:
                print("[mail-copilot] 3조각에서 표를 얻지 못해 중단 (판정용 Copilot 세션 보호)")
                break
        take(got)
        if st == "empty":
            print(f"[mail-copilot]   이 조각은 {kind} 없음 · 누적 {len(rows)}건")
            continue
        span = _span_days(s0, s1)
        if len(got) >= FULL_N and span > 5:
            print(f"[mail-copilot]   {len(got)}건 (150행 상한에 잘림) → 5일 조각 재질의")
            _refine(kind, s0, s1, alt, 5, take, q)
        elif need_subdivide(len(got), span):
            print(f"[mail-copilot]   {len(got)}건 ({'회수 부족' if len(got) < 5 else '잘림 의심'}) → 10일 조각 재질의")
            _refine(kind, s0, s1, alt, 10, take, q)
        if rows:
            rows.sort(key=lambda r: r[kidx])
            _save(kind, rows, store_subject)          # 증분 저장
        print(f"[mail-copilot]   누적 {len(rows)}건" + (" (증분 저장됨)" if rows else ""))
    if rows:
        rows.sort(key=lambda r: r[kidx])
        _save(kind, rows, store_subject)
    return len(rows), unable


def main():
    d0 = arg("--from") or (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
    d1 = arg("--to") or datetime.now().strftime("%Y-%m-%d")
    force = "--force" in sys.argv
    only = arg("--only")            # 'mail' | 'cal' — run.py 가 필요한 종류만 지정
    try:
        cfg = json.load(open(os.path.join(ROOT, "config", "config.json"), encoding="utf-8-sig"))
    except (OSError, ValueError):
        cfg = {}
    store_subject = bool(cfg.get("storeMailSubject", True))
    if os.path.exists(UNAVAILABLE_FLAG) and "--retry-copilot" not in sys.argv:
        try:
            info = json.load(open(UNAVAILABLE_FLAG, encoding="utf-8-sig"))
        except (OSError, ValueError):
            info = {}
        print(f"[mail-copilot] 이 계정의 Copilot 은 메일 조회 불가로 확인됨({info.get('when', '?')}) — 왕복 생략")
        print("               (재시도: --retry-copilot 또는 data\\outlook\\mail_copilot_unavailable.json 삭제)")
        return 1
    todo = []
    for kind, fn in (("mail", "mail.csv"), ("cal", "calendar.csv")):
        if only and kind != only:
            continue
        p = os.path.join(OUT_DIR, fn)
        if _has_data(p) and not force:
            print(f"[mail-copilot] {fn} 에 이미 자료가 있어 건너뜀 (덮어쓰려면 --force)")
        else:
            todo.append(kind)
    if not todo:
        return 0
    total, unable_kinds, counts = 0, set(), {}
    for kind in todo:
        n, unable = collect_kind(kind, d0, d1, store_subject)
        total += n
        counts[kind] = n
        if unable:
            unable_kinds.add(kind)
        print(f"[mail-copilot] {kind}: {n}건 저장")
    try:
        os.makedirs(OUT_DIR, exist_ok=True)
        src = {"source": "copilot", "when": datetime.now().strftime("%Y-%m-%d %H:%M"),
               "kinds": todo, "rows": total, "mail": counts.get("mail", 0), "calendar": counts.get("cal", 0),
               "me": [], "warnings": []}
        if "cal" in todo:
            # 프롬프트가 회차마다 한 행을 요구한다 — 반복 마스터만 남는 색인 폴백과 달리 '완전' 로 표시(LLM 회수 한계는 별개)
            src["calendar_complete"] = bool(counts.get("cal"))
            src["calendar_recurring_masters"] = 0
        with open(os.path.join(OUT_DIR, "mail_source.json"), "w", encoding="utf-8") as f:
            json.dump(src, f, ensure_ascii=False)
    except OSError:
        pass
    if total == 0:
        # '불가' 기억은 메일 조회가 막혔을 때만 남긴다(메일이 핵심). 일정만 시도해 막힌 경우는 기록하지 않는다 —
        # 전역 플래그가 다음 실행의 메일 왕복까지 막아 버리기 때문.
        if "mail" in unable_kinds:
            try:
                os.makedirs(OUT_DIR, exist_ok=True)     # 아무것도 저장 못 한 경로라 폴더가 없을 수 있다
                with open(UNAVAILABLE_FLAG, "w", encoding="utf-8") as f:
                    json.dump({"when": datetime.now().strftime("%Y-%m-%d %H:%M"),
                               "note": "Copilot 응답이 메일/일정 조회 불가 유형 — 재시도는 --retry-copilot 또는 이 파일 삭제"},
                              f, ensure_ascii=False, indent=1)
                print("               (기록됨 — 다음 분석부터 Copilot 메일 왕복을 자동 생략합니다)")
            except OSError:
                pass
        print("[mail-copilot] 표를 얻지 못함 — 실제 응답 원문은 data\\outlook\\replies\\ 에서 확인")
        return 1
    if os.path.exists(UNAVAILABLE_FLAG):
        try:
            os.remove(UNAVAILABLE_FLAG)
        except OSError:
            pass
    # 메일이 채워졌으면 COM 단계가 남긴 '건너뜀 사유'는 더 이상 화면에 낼 이유가 없다
    try:
        if "mail" in todo and _has_data(os.path.join(OUT_DIR, "mail.csv")):
            os.remove(os.path.join(OUT_DIR, "outlook_skip.json"))
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
