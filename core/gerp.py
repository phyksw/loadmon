# -*- coding: utf-8 -*-
r"""
gerp.py — GERP 근무 기록 읽기(LM30 시험 기능 · 기본 꺼짐)의 판정·해석·저장·문구 (LoadMonitor30 · LM30(2026-10-19)).

사람이 전용 Edge(data\lm30_edge)에서 직접 로그인해 둔 회사 인사 시스템(GERP)의 근무시간 현황 화면을 collect\Get-GerpWork.py 가
우리 탭 하나로 열어 읽는다. 이 모듈은 브라우저 밖의 일만 한다 — 로그인 판정(순수 함수)·표 칸 해석·태깅(입실·퇴실) 요약·저장
(data\근태\gerp.csv · gerp_status.json)·화면 문구. 네트워크를 쓰지 않는다(시험이 그대로 부른다). 설정 검증은 core\attendance.norm_gerp.

규칙
 1. 로그인하지 않는다 — 아이디·비밀번호를 넣거나 저장하지 않고 로그인 단추도 누르지 않는다. 쿠키도 읽거나 저장하지 않는다.
    로그아웃 화면이면(login_state) 아무것도 읽지 않는다.
 2. GERP 기록은 '확실히 일한 부분'(참고)이다. 분석이 이 파일을 근태 기록 칸(core\attendance.load_records — 입실·퇴실 포함)으로 읽어
    +@(그 밖에서 LM 이 찾은 근무 — core\attendance 머리말 14)를 센다. GERP 를 읽지 못해도 +@ 는 연장 + 휴일로 추정해 보인다.
    GERP 에서 나온 값(+@ 중 근태와 견준 것·근태 시간 중 PC 흔적 없는 시간·입실·퇴실)은 이 PC 에만 둔다(팀·공유폴더·Copilot 으로 가지 않는다).
 3. gerp.csv 는 날짜마다 한 행 — 날짜로 덮어쓰고 다른 날은 그대로 둔다(화면은 지금 급여 기간만 보이므로 실행마다 쌓아 간다). 지난 날만
    적는다 — 오늘·앞날은 아직 끝나지 않았다(신청만 해 둔 계획 시각일 수 있다). 열 = COLS(load_records 가 읽는 6열 뒤에 GERP 칸).
    출근·퇴근은 GERP 에 적힌(신청한) 시각 · 입실·퇴실은 태깅(출입 기록)의 첫 입실·마지막 퇴실 — 다음 날 새벽이면 24 를 더한다('25:30').
 4. 태깅은 아직 적지 않은 날과 최근 GATE_RECENT 일만 다시 읽는다(gate_dates). 태깅수 '' = 아직 안 읽음 · '0' = 읽었는데 없음.
 5. 상태 파일·로그·LMSTATUS 에는 주소(질의 문자열)·사번·회사 코드를 싣지 않는다 — 태깅 조회 주소는 읽는 동안 메모리에만 있다.
    make_status 가 한 번 더 거른다(주소·긴 숫자 지움 · 진단은 숫자와 짧은 글만 · 기간 통계는 STAT_MAP 의 값만).
"""
import csv
import io
import json
import math
import os
import re
from datetime import date, datetime
from urllib.parse import urlparse

import attendance as _att   # core\ — 근태 기록 칸 폴더 이름(RECORDS_DIR)을 한 곳에서

CSV_NAME = "gerp.csv"
STATUS_NAME = "gerp_status.json"
COLS = ("날짜", "출근", "퇴근", "휴게(분)", "인정연장", "휴가", "근무구분", "근무유형", "총근무", "비근무(분)", "최종", "입실", "퇴실",
        "태깅수", "읽은때")
GATE_COLS = ("입실", "퇴실", "태깅수")
KINDS = ("ok", "logged_out", "no_table", "disabled", "no_url", "error")
GATE_RECENT = 2                 # 오늘 전 이 날 수 안의 태깅은 늘 다시 읽는다(자정 넘은 퇴실·늦게 고친 기록)
GATE_KEY = "retrievegateinouthist"     # 화면이 보내는 태깅 조회 요청 주소에 든 이름(소문자로 견준다)
LEAVE_HALF = ("반차", "반휴")
LEAVE_FULL = ("연차", "휴가")
STAT_MAP = {"TNA_YM": "ym", "WORK_DAYS": "work_days", "FIXED_WORK_DAYS": "fixed_work_days",
            "MON_BASE_WRK_HOURS": "base_hours", "MON_MAX_WRK_HOURS": "max_hours", "MON_MAX_OT_HOUR": "max_ot_hours"}
OFF_TEXT = "GERP 근무 기록 읽기는 시험용 선택 기능이라 꺼져 있습니다(config\\config.json 의 attendance.gerp.enabled)."
_KIND_KO = {"logged_out": "로그인 안 되어 있어 건너뜀", "no_table": "근무 현황 표를 찾지 못함", "disabled": "꺼져 있어 건너뜀",
            "no_url": "주소가 없어 건너뜀", "error": "읽지 못함"}


# ════════════════════════════════ 작은 도구 ════════════════════════════════
def _int(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return 0
    return int(x) if math.isfinite(x) else 0


def _hm(m):
    m = int(round(m))
    return f"{m // 60:02d}:{m % 60:02d}"


def _short(s, n=30):
    return re.sub(r"\s+", " ", str(s or "")).strip()[:n]


def _fmt(v):
    """숫자 → 짧은 글('8.5'·'60'·'0') · None → ''"""
    if v is None:
        return ""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return ""
    if not math.isfinite(x):
        return ""
    s = f"{x:.2f}".rstrip("0").rstrip(".")
    return "0" if s in ("", "-0") else s


_YMD = re.compile(r"(\d{4})\s*[-./]\s*(\d{1,2})\s*[-./]\s*(\d{1,2})")


def _ymd(s):
    m = _YMD.search(str(s or ""))
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def host_of(url):
    """주소의 호스트(소문자) · 못 읽으면 ''"""
    try:
        return (urlparse(str(url or "")).hostname or "").lower()
    except ValueError:
        return ""


# ════════════════════════════════ 로그인 판정(순수) ════════════════════════════════
_SSO_PREFIX = ("sso", "login", "logon", "signin", "auth", "idp", "adfs", "saml", "oauth")
_SSO_LABELS = ("cas", "sts", "account", "accounts", "iam")


def looks_sso(url):
    """주소가 SSO·로그인 화면처럼 보이나 — 호스트의 마디(끝 마디 빼고)가 sso·login·signin·auth·idp·adfs… 로 시작하거나 cas·sts·account
    마디이거나, 경로의 마디가 그렇게 시작한다. 부분 문자열이 아니라 마디로만 본다."""
    try:
        u = urlparse(str(url or ""))
        host = (u.hostname or "").lower()
    except ValueError:
        return False
    if not host:
        return False
    labels = host.split(".")
    for lab in (labels[:-1] if len(labels) > 1 else labels):
        if lab.startswith(_SSO_PREFIX) or lab in _SSO_LABELS:
            return True
    return any(seg.startswith(_SSO_PREFIX) for seg in (u.path or "").lower().split("/") if seg)


def login_state(snap, cfg_url):
    """화면 스냅숏 → (상태, 까닭) — 상태 logged_out | logged_in | error.
    snap = {"top": 맨 위 문서 주소, "docs": [{"uid": input#userid 가 있나, "pw": 보이는 비밀번호 칸 수} … (모든 프레임)]}.
      · logged_out — 어느 프레임이든 input#userid 가 있거나 보이는 비밀번호 칸이 있다(까닭 'form') · 맨 위 주소의 호스트가 설정 주소의
        호스트와 다르고 SSO·로그인 화면처럼 보인다(looks_sso — 까닭 'sso'. 로그인된 세션도 SSO 를 잠깐 거치므로 호출측이 두 번 이어
        볼 때만 믿는다)
      · error — 맨 위가 브라우저 오류 화면(chrome-error·edge-error — 네트워크 · 까닭 'net')
      · 그 밖은 logged_in(표가 끝내 없으면 호출측이 no_table)."""
    s = snap if isinstance(snap, dict) else {}
    top = str(s.get("top") or "")
    if top.lower().startswith(("chrome-error://", "edge-error://")):
        return "error", "net"
    for d in s.get("docs") or ():
        if isinstance(d, dict) and (_int(d.get("uid")) > 0 or _int(d.get("pw")) > 0):
            return "logged_out", "form"
    th, ch = host_of(top), host_of(cfg_url)
    if th and ch and th != ch and looks_sso(top):
        return "logged_out", "sso"
    return "logged_in", ""


# ════════════════════════════════ 표 칸 해석 ════════════════════════════════
_HM = re.compile(r"(\d{1,2})\s*:\s*(\d{2})")
_NEXT = ("익일", "다음날", "다음 날", "(+1)")
_DUR_H = re.compile(r"(\d+(?:\.\d+)?)\s*시간")
_DUR_M = re.compile(r"(\d+(?:\.\d+)?)\s*분")
_DUR_HM = re.compile(r"^(\d{1,3})\s*:\s*(\d{2})$")
_NUM = re.compile(r"^\d+(?:\.\d+)?$")


def norm_hm(s):
    """시각 칸 → 'HH:MM' — '09:00'·'9:00'·'09:00:00'·'익일 01:30'(다음 날 표시면 24 를 더한다 — '25:30'). 못 읽으면 ''."""
    t = re.sub(r"\s+", " ", str(s or "")).strip()
    m = _HM.search(t)
    if not m:
        return ""
    h, mi = int(m.group(1)), int(m.group(2))
    if mi >= 60 or h > 47:
        return ""
    if h < 24 and any(k in t for k in _NEXT):
        h += 24
    return f"{h:02d}:{mi:02d}"


def dur_min(s, plain="min"):
    """시간 칸 → 분(float) · 못 읽으면 None. '8시간 30분'·'1시간'·'60분'·'8:30'(시:분)·숫자만(plain 'min' 이면 분, 'h' 면 시간).
    말뿐인 칸('-'·'없음')·음수는 None."""
    t = str(s or "").replace(",", "").strip()
    if not t:
        return None
    h, m = _DUR_H.search(t), _DUR_M.search(t)
    if h or m:
        return round((float(h.group(1)) if h else 0.0) * 60.0 + (float(m.group(1)) if m else 0.0), 2)
    hm = _DUR_HM.match(t)
    if hm:
        return float(int(hm.group(1)) * 60 + int(hm.group(2)))
    if _NUM.match(t):
        v = float(t)
        return round(v * 60.0, 2) if plain == "h" else v
    return None


def leave_of(t1, t2):
    """근무구분·근무유형 글 → 휴가 비율 — 반차·반휴 0.5 · 연차·휴가 1 · 그 밖 0(반이 먼저 — '연차(반차)' 는 0.5)."""
    s = f"{t1 or ''} {t2 or ''}"
    if any(k in s for k in LEAVE_HALF):
        return 0.5
    if any(k in s for k in LEAVE_FULL):
        return 1.0
    return 0.0


def hr_row(cells):
    """근무시간 현황 표 한 행의 칸 글(4~13번째 칸 — 날짜·근무구분·근무유형·총근무·출근·퇴근·최종·휴게·비근무·연장. 칸 글이 비면 화면이
    그 칸의 입력 상자 값을 준다) → 행 dict | None(날짜를 못 읽음).
    {date, type1, type2, total_h, in, out, final, break_min, nonwork_min, ot_h, leave} — 시각 'HH:MM'(못 읽으면 ''), 시간은 float | None."""
    c = [str(x) if x is not None else "" for x in list(cells or [])[:10]]
    c += [""] * (10 - len(c))
    d = _ymd(c[0])
    if d is None:
        return None
    t1, t2 = _short(c[1]), _short(c[2])
    tot, ot = dur_min(c[3], "h"), dur_min(c[9], "h")
    return {"date": d, "type1": t1, "type2": t2, "total_h": round(tot / 60.0, 2) if tot is not None else None,
            "in": norm_hm(c[4]), "out": norm_hm(c[5]), "final": norm_hm(c[6]) or _short(c[6], 20),
            "break_min": dur_min(c[7], "min"), "nonwork_min": dur_min(c[8], "min"),
            "ot_h": round(ot / 60.0, 2) if ot is not None else None, "leave": leave_of(t1, t2)}


def hr_cols(r, read_at):
    """행 dict(hr_row) → gerp.csv 의 근무 기록 칸. 휴게가 0~600분 밖이면 비운다(load_records 가 그 행을 버리지 않게)."""
    brk = r.get("break_min")
    if brk is not None and not (0 <= brk <= 600):
        brk = None
    lv = float(r.get("leave") or 0)
    return {"날짜": r["date"].isoformat(), "출근": r.get("in") or "", "퇴근": r.get("out") or "", "휴게(분)": _fmt(brk),
            "인정연장": _fmt(r.get("ot_h")), "휴가": _fmt(lv) if lv > 0 else "", "근무구분": r.get("type1") or "",
            "근무유형": r.get("type2") or "", "총근무": _fmt(r.get("total_h")), "비근무(분)": _fmt(r.get("nonwork_min")),
            "최종": r.get("final") or "", "읽은때": str(read_at or "")}


def period_stats(raw):
    """기간 통계(화면의 ds_summary 에서 STAT_MAP 의 6개만) → {ym: 'YYYYMM', work_days·fixed_work_days·base_hours·max_hours·
    max_ot_hours: 숫자}. 다른 칸(사번 등)은 받아도 버린다."""
    out = {}
    if not isinstance(raw, dict):
        return out
    for k, name in STAT_MAP.items():
        v = raw.get(k)
        if name == "ym":
            s = re.sub(r"\D", "", str(v or ""))
            if len(s) == 6:
                out["ym"] = s
            continue
        try:
            x = float(str(v).replace(",", ""))
        except (TypeError, ValueError):
            continue
        if math.isfinite(x) and 0 <= x <= 10000:
            out[name] = round(x, 2)
    return out


# ════════════════════════════════ 태깅(입실·퇴실) ════════════════════════════════
def gate_summary(day, hist):
    """태깅 이력(화면이 OUT_INOUT_HIST 를 [시각 'yyyymmddHHMMSS', IN|OUT, 입실|퇴실] 셋으로 줄인 것) → {"in": 첫 입실, "out": 마지막
    퇴실, "n": 받은 건수}. 시각은 그 근무일 00:00 부터 — 다음 날 새벽 퇴실은 24 를 더한다('25:30'). 시각을 못 읽거나 이틀 밖이면 건너뛴다.
    구분은 IN·OUT 이 먼저, 없으면 이름(입·퇴)으로."""
    ins, outs, n = [], [], 0
    for x in hist or ():
        if not isinstance(x, (list, tuple)) or not x:
            continue
        n += 1
        dt = re.sub(r"\D", "", str(x[0] or ""))
        if len(dt) < 12:
            continue
        try:
            t = datetime(int(dt[0:4]), int(dt[4:6]), int(dt[6:8]), int(dt[8:10]), int(dt[10:12]))
        except ValueError:
            continue
        m = (t.date() - day).days * 1440 + t.hour * 60 + t.minute
        if not (0 <= m < 2880):
            continue
        fl = str(x[1] if len(x) > 1 else "").strip().upper()
        nm = str(x[2] if len(x) > 2 else "")
        if fl == "IN" or (fl not in ("IN", "OUT") and "입" in nm):
            ins.append(m)
        elif fl == "OUT" or "퇴" in nm:
            outs.append(m)
    return {"in": _hm(min(ins)) if ins else "", "out": _hm(max(outs)) if outs else "", "n": n}


def gate_dates(days, tagged, today, cap, recent=GATE_RECENT):
    """태깅을 읽을 날 — 표에 보인 지난 날(오늘 전) 중 아직 태깅을 적지 않은 날 + 최근 recent 일(늦은 퇴실·고친 기록), 최신부터 cap 일."""
    tg = set(tagged or ())
    want = {d for d in days or () if isinstance(d, date) and d < today and (d not in tg or (today - d).days <= recent)}
    return sorted(want, reverse=True)[:max(0, int(cap or 0))]


_TNA = re.compile(r"([?&]IN_SEARCH(?:\.|%2[Ee])TNA_DATE=)(\d{8})(?=&|#|$)")


def with_tna_date(url, day):
    """화면이 보낸 태깅 조회 주소에서 IN_SEARCH.TNA_DATE 값(yyyymmdd)만 바꾼다(다른 값은 글자 그대로) → 주소 | ''(그 값이 없다)."""
    s = str(url or "")
    if not _TNA.search(s):
        return ""
    ymd = day.strftime("%Y%m%d")
    return _TNA.sub(lambda m: m.group(1) + ymd, s, count=1)


# ════════════════════════════════ gerp.csv ════════════════════════════════
def csv_path(data_dir):
    return os.path.join(str(data_dir or ""), _att.RECORDS_DIR, CSV_NAME)


def _decode(b):
    if b[:3] == b"\xef\xbb\xbf":
        return b[3:].decode("utf-8", "replace")
    try:
        return b.decode("utf-8")
    except UnicodeDecodeError:
        return b.decode("cp949", "replace")


def read_rows(path):
    """gerp.csv → {날짜 iso: {열: 글}}(날짜를 못 읽는 행은 버린다). 파일이 없거나 못 읽으면 {}. 엑셀이 CP949 로 다시 저장해도 읽는다."""
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError:
        return {}
    try:
        rows = list(csv.reader(io.StringIO(_decode(raw))))
    except csv.Error:
        return {}
    if not rows:
        return {}
    hdr = [re.sub(r"\s+", "", str(h or "").replace("﻿", "")) for h in rows[0]]
    idx = {k: hdr.index(k) for k in COLS if k in hdr}
    if "날짜" not in idx:
        return {}
    out = {}
    for r in rows[1:]:
        d = _ymd(r[idx["날짜"]] if idx["날짜"] < len(r) else "")
        if d is None:
            continue
        row = dict.fromkeys(COLS, "")
        for k, i in idx.items():
            row[k] = str(r[i]).strip() if i < len(r) else ""
        row["날짜"] = d.isoformat()
        out[row["날짜"]] = row
    return out


def tagged_dates(rows):
    """read_rows 결과 → 태깅을 이미 적은 날(태깅수 칸이 빈 글이 아닌 날)의 date 집합"""
    out = set()
    for iso, r in (rows or {}).items():
        if str((r or {}).get("태깅수") or "").strip():
            d = _ymd(iso)
            if d is not None:
                out.add(d)
    return out


def _write_csv(path, rows):
    """UTF-8 BOM · CRLF · 날짜 순 — 임시 파일에 쓴 뒤 바꿔 끼운다(쓰다 끊겨도 앞 파일이 남는다). 엑셀에 열려 있으면 OSError."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f, lineterminator="\r\n")
            w.writerow(COLS)
            for iso in sorted(rows):
                w.writerow([rows[iso].get(k, "") for k in COLS])
        os.replace(tmp, path)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def upsert(path, hr_rows, gates, read_at, today):
    """gerp.csv 에 날짜 단위로 덮어쓴다 → (근무 기록을 적은 날 수, 태깅을 적은 날 수, 파일의 날 수). 지난 날(today 전)만 적는다.
    hr_rows = [hr_row 행] · gates = {date: gate_summary}. 이번에 읽지 않은 날과 칸(태깅을 다시 읽지 않은 날의 입실·퇴실)은 그대로 둔다.
    적을 것이 없으면 파일을 건드리지 않는다. 열린 파일(엑셀)이면 OSError — 호출측이 알린다."""
    cur = read_rows(path)
    n_hr = n_gate = 0
    for r in hr_rows or ():
        d = r.get("date") if isinstance(r, dict) else None
        if not isinstance(d, date) or d >= today:
            continue
        iso = d.isoformat()
        old = cur.get(iso) or {}
        row = dict.fromkeys(COLS, "")
        for k in GATE_COLS:
            row[k] = old.get(k, "")
        row.update(hr_cols(r, read_at))
        cur[iso] = row
        n_hr += 1
    for d, gt in (gates or {}).items():
        if not isinstance(d, date) or d >= today or not isinstance(gt, dict):
            continue
        iso = d.isoformat()
        row = cur.get(iso)
        if row is None:
            row = dict.fromkeys(COLS, "")
            row["날짜"] = iso
        row.update({"입실": str(gt.get("in") or ""), "퇴실": str(gt.get("out") or ""), "태깅수": str(_int(gt.get("n")))})
        cur[iso] = row
        n_gate += 1
    if n_hr or n_gate:
        _write_csv(path, cur)
    return n_hr, n_gate, len(cur)


def csv_info(data_dir):
    """모아 둔 기록 — {"days": 날 수, "from": 첫 날, "to": 끝 날, "tagged": 태깅을 적은 날 수}(파일이 없으면 0·'')"""
    rows = read_rows(csv_path(data_dir))
    ds = sorted(rows)
    return {"days": len(ds), "from": ds[0] if ds else "", "to": ds[-1] if ds else "", "tagged": len(tagged_dates(rows))}


# ════════════════════════════════ 상태 파일 ════════════════════════════════
def status_path(data_dir):
    return os.path.join(str(data_dir or ""), _att.RECORDS_DIR, STATUS_NAME)


def read_status(data_dir):
    try:
        with open(status_path(data_dir), encoding="utf-8-sig") as f:
            o = json.load(f)
        return o if isinstance(o, dict) else {}
    except (OSError, ValueError):
        return {}


_SCRUB = (re.compile(r"[a-z][a-z0-9+.-]*://\S+", re.I), re.compile(r"[?&][\w.%-]+=\S*"), re.compile(r"\d{6,}"))
_AT_RX = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")


def clean_text(s, n=200):
    """사람이 읽을 글에서 주소·질의 조각·긴 숫자(사번 같은 것)를 지운다 — 상태 파일·화면 문구 관문"""
    t = re.sub(r"\s+", " ", str(s or "")).strip()
    for rx in _SCRUB:
        t = rx.sub("…", t)
    return t[:n]


def make_status(kind, now, rows=0, gate_days=0, period=None, why="", stats=None, diag=None, prev=None):
    r"""상태 파일 내용(data\근태\gerp_status.json) — {at, ok, kind, rows(이번에 적은 지난 날 수), gate_days(태깅을 적은 날 수),
    period([첫 날, 끝 날] — 화면에 보인 기간), why(쉬운 말)[, last_ok_at(마지막으로 읽힌 때 — 앞 상태에서 이어 받음), stats, diag]}.
    주소·사번·회사 코드는 싣지 않는다 — why 는 clean_text, diag 는 숫자·짧은 글(주소 꼴 아님)만, stats 는 STAT_MAP 의 값만."""
    k = kind if kind in KINDS else "error"
    at = now.strftime("%Y-%m-%d %H:%M")
    per = [str(x)[:10] for x in (period or [])][:2]
    if len(per) != 2 or not all(re.match(r"^\d{4}-\d{2}-\d{2}$", x) for x in per):
        per = []
    st = {"at": at, "ok": k == "ok", "kind": k, "rows": _int(rows), "gate_days": _int(gate_days), "period": per,
          "why": clean_text(why)}
    last = at if k == "ok" else str((prev if isinstance(prev, dict) else {}).get("last_ok_at") or "")[:16]
    if _AT_RX.match(last):
        st["last_ok_at"] = last
    ps = {}
    names = set(STAT_MAP.values())
    for name, v in (stats or {}).items():
        if name not in names:
            continue
        if name == "ym":
            if re.fullmatch(r"\d{6}", str(v)):
                ps[name] = str(v)
        elif isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(float(v)):
            ps[name] = v
    if ps:
        st["stats"] = ps
    dg = {}
    for key, v in (diag or {}).items():
        if len(dg) >= 24:
            break
        if isinstance(v, bool) or (isinstance(v, (int, float)) and math.isfinite(float(v))):
            dg[str(key)[:24]] = v
        elif isinstance(v, str) and len(v) <= 24 and not re.search(r"[:/?&=@%]|\d{6,}", v):
            dg[str(key)[:24]] = v
    if dg:
        st["diag"] = dg
    return st


def write_status(data_dir, st):
    """상태 파일 쓰기(UTF-8 · 임시 파일 뒤 바꿔 끼우기) → 썼나"""
    p = status_path(data_dir)
    tmp = f"{p}.{os.getpid()}.tmp"
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False, indent=1)
        os.replace(tmp, p)
        return True
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False


def timeout_sec(g):
    """한 번 읽기의 바깥 상한(초) — 화면 기다림(timeoutSec) 두 배 + 태깅 날마다 3초 + 여유 90초(최소 120). run.py·화면이 쓴다."""
    g = g if isinstance(g, dict) else {}
    return int(max(120, _int(g.get("timeoutSec") or 60) * 2 + _int(g.get("maxGateDays")) * 3 + 90))


# ════════════════════════════════ 화면 문구 ════════════════════════════════
def status_text(st, g=None, info=None):
    """대시보드 카드의 GERP 한 줄 — '마지막으로 읽은 때 2026-10-19 09:12 · 근무 기록 21일(태깅 5일) · 모아 둔 기록 45일(…~…)'.
    로그아웃이면 '2026-10-19 09:12 · 로그인 안 되어 있어 건너뜀 · 마지막으로 읽은 때 …'. 주소가 없으면 넣는 곳을 말한다."""
    g = g if isinstance(g, dict) else {}
    st = st if isinstance(st, dict) else {}
    info = info if isinstance(info, dict) else {}
    if not g.get("url"):
        return ("GERP 근무 현황 화면 주소가 비어 있습니다 — config\\config.json 의 attendance.gerp.url 에 넣으세요"
                "(주소는 이 PC 에만 둡니다).")
    kind, at = str(st.get("kind") or ""), str(st.get("at") or "")
    bits = []
    if not kind or not at:
        bits.append("아직 읽지 않았습니다 — [GERP 열기(직접 로그인)]로 로그인해 둔 뒤 [GERP 근무 기록 읽기]를 누르세요")
    elif kind == "ok":
        s = f"마지막으로 읽은 때 {at} · 근무 기록 {_int(st.get('rows'))}일"
        if _int(st.get("gate_days")):
            s += f"(태깅 {_int(st.get('gate_days'))}일)"
        bits.append(s)
    else:
        s = f"{at} · {_KIND_KO.get(kind, '읽지 못함')}"
        why = clean_text(st.get("why"), 80)
        if kind == "error" and why:
            s += f"({why})"
        if st.get("last_ok_at"):
            s += f" · 마지막으로 읽은 때 {clean_text(st.get('last_ok_at'), 16)}"
        bits.append(s)
    if _int(info.get("days")):
        bits.append(f"모아 둔 기록 {_int(info.get('days'))}일({info.get('from')}~{info.get('to')})")
    return " · ".join(bits)
