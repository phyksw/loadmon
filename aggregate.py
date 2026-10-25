# -*- coding: utf-8 -*-
r"""
aggregate.py — 팀 공유폴더의 인별 결과를 모아 팀 총괄 리포트를 만든다 (팀장용).

  python aggregate.py \\서버\팀공유\LoadMonitor          # 또는 config.teamShareDir 사용
  python aggregate.py                                     # config 값 사용
  python aggregate.py [share] [--open] [--snapshot]       # --snapshot: 통합 보고서 타임스탬프 사본도

출력: <공유폴더>\team_report.html  (인별 MM · 과제×인원 매트릭스 · 유형 분포 ·
      공통업무(표준화·자동화 후보) · 팀 Agentic AI 니즈 후보 · raw 단서 링크)  +  team_mm.csv
      + team_full_report.html / team_full_report_v3.html (team_report.build — 통합 보고서 한 장)
마지막 줄 JSON: {"ok","members","agentic","needs","report","full_report","full_v3","snapshots"}
  agentic = 니즈 후보 파일(agentic_<기간>.json)이 있는 인원 수 · needs = 합친 팀 니즈 후보 수

팀 Agentic AI 니즈 후보(LM29부터): 인원별 agentic_<기간>.json 의 후보(new)만 읽어 이름(needs_key — core/details.fold 와 같은 축)으로
합친다(merge_needs). LM28 이 올린 파일의 과제 매칭(match)·오할당(misassigned)은 읽지 않는다.
"""
import ast
import csv
import glob
import html
import io
import json
import math
import os
import re
import sys
import time
import unicodedata
from collections import defaultdict

ROOT = os.path.dirname(os.path.abspath(__file__))

# 동봉한 파이썬(python\python311._pth)은 **스크립트가 있는 폴더를 sys.path 에 넣지 않는다** —
# python311.zip 과 python\ 만 들어간다. 그래서 뿌리 모듈(teamup·team_report…)을 실행 중에
# import 하려면 여기서 직접 넣어야 한다. 없으면 ModuleNotFoundError 가 나는데, 부르는 쪽이
# try/except 로 감싸고 있어 오류 없이 기능만 조용히 빠진다(실측: 공유폴더 member.json 에
# measure/coverage/cfg_used/tool_usage 가 통째로 없었고, 팀 통합보고서가 아예 안 만들어졌다).
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def esc(s):
    return html.escape(str(s or ""))


def fnum(v, default=None):
    """숫자 강제 변환 — 업로드로 들어온 남의 값이라 'abc'·dict·None·'<b>x</b>' 이 올 수 있다.
    실패하면 default. (한 인원의 값 하나가 팀 전체 취합을 rc=1 로 죽이던 결함 — 검증 확정)"""
    if v is None or isinstance(v, bool) or isinstance(v, (list, tuple, set, dict)):
        return default
    try:
        f = float(str(v).strip()) if not isinstance(v, (int, float)) else float(v)
    except (TypeError, ValueError):
        return default
    return f if math.isfinite(f) else default


def fint(v, default=None):
    """정수(개수) 강제 변환 — 목록이 오면 그 길이(long_days 가 [[날짜,h],…] 로 올 수도 있다), 객체는 default"""
    if isinstance(v, (list, tuple, set)):
        return len(v)
    f = fnum(v)
    return default if f is None else int(round(f))


def pct_text(v):
    """로드율 표시 — 숫자면 '30%'/'13.3%', 아니면 '–'. 문자열이 그대로 HTML 에 박히지 않게 한다."""
    f = fnum(v)
    if f is None:
        return "–"
    return f"{f:.1f}".rstrip("0").rstrip(".") + "%"


def mm_scale(total_mm, rows_sum):
    """행 MM 합 → 공식 투입(member.total_mm) 재스케일 배율 — **규칙은 여기 한 곳뿐**.

    §1(투입)·§2(과제×인원·트리맵)·§3(업무유형) 이 한 문서 안에서 같은 수치가 되게 한다.
    정제본이 옛것이거나 다른 기간 파일을 가져오면 행 합이 공식값과 달라지는데, 그때 §2 만
    행 합 그대로 두면 한 사람의 과제 열 합이 §1 투입의 몇 배로 보였다(검증 확정).
    공식값이 없거나 행 합이 0 이면 1.0(행 그대로)."""
    t, s = fnum(total_mm), fnum(rows_sum)
    if not t or t <= 0 or not s or s <= 0:
        return 1.0
    return t / s


# LM30(2026-10-21) leave_days — 가용에서 뺀 유급휴가 일수(반차 0.5 — 개수가 아니라 소수 그대로 · teamup.leave_days_of)
_NUM_KEYS = ("total_mm", "avail_mm", "load_pct", "worked_h", "overtime_h", "dropped_h", "leave_days")
_CNT_KEYS = ("signals", "no_evidence_days", "absence_days", "gap_days", "anomaly_days", "long_days")
_STR_KEYS = ("function", "tag", "host", "analyzed_at", "uploaded_at", "uploaded_from", "via")

# ── D5: 측정 방식·신뢰도·산식 설정 (teamup.build 가 mm_meta 의 measure/coverage/cfg_used 를 올린다) ──
# 수집 환경 차이(샘플러 유무·PC 기록 결측·설정)가 -9~-80pt 를 만드는데 표에서는 사람 차이로 읽혔다.
MEASURE_KEYS = ("sampler_days", "pc_floor_days", "trace_window_days", "offsite_days", "manual_days",
                "pc_record_days", "floor_blocked_passive_days", "pc_record_missing_days")
CFG_KEYS = ("standardDayHours", "usePcFloor", "pcFloorNeeds", "dayWindow", "lunch", "dinner",
            "tentativeMeetings", "holidays_n", "offsiteAsWork", "samplerGapBridgeMin")
GRADES = ("reliable", "caution", "unreliable")
GRADE_LABEL = {"reliable": "신뢰", "caution": "주의", "unreliable": "측정 불충분"}
GRADE_COLOR = {"reliable": "#0f7a3d", "caution": "#c98a00", "unreliable": "#c0122f"}


def norm_measure(v):
    """member.measure → {method:str, <MEASURE_KEYS>:int} / 객체가 아니면 None(구판 자료 — 배지 없음)"""
    if not isinstance(v, dict):
        return None
    out = {"method": str(v.get("method") or "")[:20]}
    for k in MEASURE_KEYS:
        if k in v:
            out[k] = fint(v.get(k), 0) or 0
    return out


def norm_coverage(v):
    """member.coverage → {grade, reasons[…]} / 등급이 셋 중 하나가 아니면 grade "" (unreliable 로 오인 금지)"""
    if not isinstance(v, dict):
        return None
    g = str(v.get("grade") or "").strip().lower()
    reasons = v.get("reasons")
    if not isinstance(reasons, list) or not reasons:
        reasons = v.get("missing") if isinstance(v.get("missing"), list) else []
    out = {"grade": g if g in GRADES else "",
           "reasons": [str(x)[:60] for x in reasons if str(x).strip()][:6]}
    r = fnum(v.get("pc_weekday_ratio"))
    if r is not None:
        out["pc_weekday_ratio"] = round(r, 2)
    return out


def norm_tool_usage(v):
    """member.tool_usage → 프로그램 사용 이력(참고 지표) 정규화.

    ★ 로드율·MM 과 무관하다. 팀 화면에서 이 값이 '일한 양' 으로 읽히지 않게 별도 절에만 쓴다.
    수치는 전부 숫자로 강제하고, 이름·분류는 길이를 자른다(팀 서버로 올라온 남의 자료다).
    LM28 새 칸(core/extract.tool_usage — 실행 기록·파일 흔적): 프로그램마다 src(출처)·runs·runs_cum·focus_h·focus_h_cum·
    taskbar·last_run·file_days·files, 최상위 by_kind_n·by_cat_n(프로그램 수)·inhouse(자체·프로토타입(추정) — 이름은 core 가
    G3 관문을 거친 것)·inhouse_n·inhouse_hidden·sources(원천 요약 — 스칼라만)·note. 증가분을 모르는 칸(None)은 None 그대로 —
    0 으로 바꾸면 '안 썼다' 로 읽힌다. 옛 꼴(창기록만)은 예전 그대로 나온다."""
    if not isinstance(v, dict):
        return None

    def oint(x):
        n = fnum(x)
        return None if n is None else int(round(n))

    def oflt(x):
        n = fnum(x)
        return None if n is None else round(n, 2)
    out = {}
    for k in ("samples", "days"):
        n = fnum(v.get(k))
        if n is not None:
            out[k] = int(n)
    for k in ("total_h", "known_h", "unknown_h", "sim_h", "cad_h", "solver_bg_h"):
        n = fnum(v.get(k))
        if n is not None:
            out[k] = round(n, 2)
    progs = []
    for pr in (v.get("programs") if isinstance(v.get("programs"), list) else [])[:12]:
        if not isinstance(pr, dict):
            continue
        nm = str(pr.get("name") or "").strip()[:40]
        if not nm:
            continue
        row = {"name": nm, "kind": str(pr.get("kind") or "")[:6], "cat": str(pr.get("cat") or "")[:10]}
        for k in ("hours", "bg_hours"):
            row[k] = round(fnum(pr.get(k)) or 0.0, 2)
        row["days"] = int(fnum(pr.get("days")) or 0)
        if isinstance(pr.get("src"), list):             # 새 꼴만 — 옛 꼴 행은 예전 칸 그대로
            row["src"] = [str(s)[:6] for s in pr["src"] if str(s).strip()][:3]
            for k in ("runs", "runs_cum", "taskbar"):
                row[k] = oint(pr.get(k))
            for k in ("focus_h", "focus_h_cum"):
                row[k] = oflt(pr.get(k))
            row["last_run"] = str(pr.get("last_run") or "")[:16]
            row["file_days"] = int(fnum(pr.get("file_days")) or 0)
            row["files"] = int(fnum(pr.get("files")) or 0)
        progs.append(row)
    out["programs"] = progs
    for k in ("by_cat", "by_kind"):
        v2 = v.get(k)
        if not isinstance(v2, list):
            continue
        out[k] = [[str(x[0])[:12], round(fnum(x[1]) or 0.0, 2)] for x in v2
                  if isinstance(x, (list, tuple)) and len(x) >= 2][:8]
    for k in ("by_kind_n", "by_cat_n"):                 # 프로그램 수 — '자체·프로토타입(추정)' 이 잘리지 않게 14자
        v2 = v.get(k)
        if isinstance(v2, list):
            out[k] = [[str(x[0])[:14], int(fnum(x[1]) or 0)] for x in v2
                      if isinstance(x, (list, tuple)) and len(x) >= 2][:8]
    inh = []
    for x in (v.get("inhouse") if isinstance(v.get("inhouse"), list) else [])[:12]:
        if not isinstance(x, dict) or not str(x.get("name") or "").strip():
            continue
        inh.append({"name": str(x.get("name")).strip()[:40], "cls": str(x.get("cls") or "")[:12],
                    "runs": oint(x.get("runs")), "runs_cum": oint(x.get("runs_cum")),
                    "focus_h": oflt(x.get("focus_h")), "last_run": str(x.get("last_run") or "")[:16]})
    if inh or "inhouse" in v:
        out["inhouse"] = inh
    for k in ("inhouse_n", "inhouse_hidden"):
        n = fnum(v.get(k))
        if n is not None:
            out[k] = int(n)
    srcs = v.get("sources")
    if isinstance(srcs, dict):
        so = {}
        for sk, sv in list(srcs.items())[:4]:
            if not isinstance(sv, dict):
                continue
            d = {}
            for kk, vv in list(sv.items())[:16]:
                if isinstance(vv, bool) or vv is None:
                    d[str(kk)[:16]] = vv
                elif isinstance(vv, (int, float)):
                    if fnum(vv) is not None:
                        d[str(kk)[:16]] = vv
                elif isinstance(vv, str):
                    d[str(kk)[:16]] = vv[:200]
                elif isinstance(vv, list) and len(vv) == 2 and all(isinstance(y, str) for y in vv):
                    d[str(kk)[:16]] = [y[:10] for y in vv]       # window [시작, 끝]
            so[str(sk)[:8]] = d
        out["sources"] = so
    if isinstance(v.get("note"), str):
        out["note"] = v["note"][:200]
    return out if (out.get("programs") or out.get("total_h") or out.get("inhouse") or out.get("inhouse_n")) else None


ATT_KEYS = ("work_h", "ext_h", "night_h", "holiday_h", "offpc_h", "over52_weeks", "leave_work_days")
ATT_COUNTS = ("over52_weeks", "leave_work_days")


def norm_attendance(v):
    """member.attendance(LM30 출퇴근 추정 — teamup.attendance_of 의 달·전체 합계, 시각 없음) → {used_for_mm, months{YYYY-MM:
    {ATT_KEYS}}, total{ATT_KEYS}} / 객체가 아니거나 비었으면 None(LM29 이전 판 — 칸 없음). 숫자는 숫자로 강제하고 달은 36개까지
    (업로드로 들어온 남의 값이다)."""
    if not isinstance(v, dict):
        return None

    def row(x):
        if not isinstance(x, dict):
            return None
        out = {}
        for k in ATT_KEYS:
            n = fnum(x.get(k))
            if n is not None:
                out[k] = int(round(n)) if k in ATT_COUNTS else round(n, 2)
        return out
    months = {}
    src = v.get("months") if isinstance(v.get("months"), dict) else {}
    for mk in sorted(src)[:36]:
        r = row(src.get(mk))
        if r is not None and re.match(r"^\d{4}-\d{2}$", str(mk)):
            months[str(mk)] = r
    total = row(v.get("total")) or {}
    if not months and not total:
        return None
    return {"used_for_mm": bool(v.get("used_for_mm")), "months": months, "total": total}


def norm_cfg_used(v):
    """member.cfg_used → 알려진 키만, 값은 스칼라 또는 문자열 목록(비교·표시용)"""
    if not isinstance(v, dict):
        return None
    out = {}
    for k in CFG_KEYS:
        if k not in v:
            continue
        x = v.get(k)
        if isinstance(x, (list, tuple)):
            out[k] = [str(y) for y in x][:4]
        elif isinstance(x, (bool, int, float, str)) or x is None:
            out[k] = x
    return out


def is_unreliable(m):
    return bool(((m or {}).get("coverage") or {}).get("grade") == "unreliable")


def measure_text(m):
    """'샘플러 N일 / PC 하한 N일 / 흔적폭 N일 / 출장 N일 / 수동 N일' — measure 가 없으면 빈 문자열(구판)"""
    ms = (m or {}).get("measure")
    if not isinstance(ms, dict):
        return ""
    return (f"샘플러 {ms.get('sampler_days', 0)}일 / PC 하한 {ms.get('pc_floor_days', 0)}일 / "
            f"흔적폭 {ms.get('trace_window_days', 0)}일 / 출장 {ms.get('offsite_days', 0)}일 / "
            f"수동 {ms.get('manual_days', 0)}일")


def coverage_badge(m):
    """측정 신뢰도 배지(HTML) — reliable/caution/unreliable. 등급이 없으면 빈 문자열."""
    cv = (m or {}).get("coverage") or {}
    g = cv.get("grade")
    if g not in GRADE_LABEL:
        return ""
    tip = " · ".join(cv.get("reasons") or []) or "측정 신뢰도 등급(PC 기록 40%·샘플러·달력 결측 수)"
    return (f'<span title="{esc(tip)}" style="font-size:10px;color:{GRADE_COLOR[g]};border:1px solid '
            f'{GRADE_COLOR[g]};border-radius:3px;padding:0 4px;margin-left:6px;white-space:nowrap">'
            f'{esc(GRADE_LABEL[g])}</span>')


def cfg_mismatch(members):
    """산식 설정(cfg_used)이 팀 '과반' 과 다른 인원 집합 — 분모(표준시간·공휴일·창)가 다르면 비교가 무의미.
    cfg_used 가 있는 인원이 2명 미만이거나 과반이 없으면(동수) 아무도 표시하지 않는다."""
    have = [m for m in members if isinstance(m.get("cfg_used"), dict) and m.get("cfg_used")]
    if len(have) < 2:
        return set()
    keys = sorted({k for m in have for k in m["cfg_used"]})
    sig = {}
    for m in have:
        sig[m["owner"]] = json.dumps({k: m["cfg_used"].get(k) for k in keys}, sort_keys=True,
                                     ensure_ascii=False)
    votes = defaultdict(int)
    for s in sig.values():
        votes[s] += 1
    top, n_top = max(votes.items(), key=lambda kv: kv[1])
    if n_top * 2 <= len(have):
        return set()
    return {o for o, s in sig.items() if s != top}


def cfg_badge(m):
    """'산식 설정 상이' 배지 — load_members 가 표시한 m["cfg_diff"] 기준"""
    if not (m or {}).get("cfg_diff"):
        return ""
    cu = m.get("cfg_used") or {}
    tip = ("산식 설정이 팀 다수와 다릅니다 — " + " · ".join(
        f"{k}={cu.get(k)}" for k in CFG_KEYS if k in cu)[:200])
    return (f'<span title="{esc(tip)}" style="font-size:10px;color:#6c4fb8;border:1px solid #b06ef7;'
            f'border-radius:3px;padding:0 4px;margin-left:6px;white-space:nowrap">산식 설정 상이</span>')


def mark_members(members):
    """load_members 끝에서 — measure/coverage/cfg_used 정규화 결과로 unreliable·cfg_diff 표식을 붙인다"""
    diff = cfg_mismatch(members)
    for m in members:
        m["unreliable"] = is_unreliable(m)
        m["cfg_diff"] = m.get("owner") in diff
        m["measure_text"] = measure_text(m)
    return members


def norm_member(m, name=""):
    """member.json 값을 쓰는 쪽이 믿을 수 있는 형태로 강제한다 — 숫자는 숫자로(아니면 None),
    기간은 [시작, 끝] 문자열 목록으로, 표시 문자열은 str 로. 형식이 이상한 칸은 경고만 남긴다."""
    bad = []
    for k in _NUM_KEYS:
        if k in m:
            v = fnum(m.get(k))
            if v is None and m.get(k) not in (None, ""):
                bad.append(f"{k}={str(m.get(k))[:20]!r}")
            m[k] = v
    for k in _CNT_KEYS:
        if k in m:
            v = fint(m.get(k))
            if v is None and m.get(k) not in (None, ""):
                bad.append(f"{k}={str(m.get(k))[:20]!r}")
            m[k] = v
    for k in _STR_KEYS:
        if k in m and m.get(k) is not None and not isinstance(m.get(k), str):
            m[k] = str(m.get(k))
    per = m.get("period")
    if isinstance(per, str):
        per = [x.strip() for x in per.split("~")] if "~" in per else [per.strip()]
    if not isinstance(per, list):
        per = []
    m["period"] = [str(x or "") for x in per][:2]
    # D5 — 측정 방식·신뢰도·산식 설정: 객체가 아니면 None(구판 클라이언트 — 배지 없음, unreliable 아님)
    m["measure"] = norm_measure(m.get("measure"))
    m["coverage"] = norm_coverage(m.get("coverage"))
    m["cfg_used"] = norm_cfg_used(m.get("cfg_used"))
    m["tool_usage"] = norm_tool_usage(m.get("tool_usage"))   # 프로그램 사용 이력(참고 지표 — 로드율과 무관)
    m["attendance"] = norm_attendance(m.get("attendance"))   # LM30 출퇴근 추정 달·전체 합계(없으면 None)
    if bad:
        print(f"[aggregate] {name or m.get('owner')}: member.json 값 형식 이상 — "
              f"{', '.join(bad[:4])} (그 칸만 무시)")
    return m


def norm_common(pivots):
    """pivots.common 항목을 dict·숫자 mm 으로 거른다 — 한 항목의 'abc' 가 합산 전체를 죽이지 않게"""
    out = []
    for c in (pivots.get("common") or []) if isinstance(pivots, dict) else []:
        if not isinstance(c, dict):
            continue
        det = str(c.get("detail") or "").strip()
        if not det:
            continue
        models = c.get("models")
        models = [str(x) for x in models if x] if isinstance(models, list) else []
        out.append({"detail": det, "mm": fnum(c.get("mm"), 0.0), "models": models})
    return out


def load_members(share):
    """인별 폴더 스캔 — 파일은 전부 BOM 허용(utf-8-sig)으로 읽고, 한 명 파일이 깨져도
    팀 전체 취합이 죽지 않게 그 사람만 건너뛴다(경고 출력).
    실측: PowerShell·메모장이 만든 member.json 의 BOM 하나로 취합 전체가 죽었다.
    값(숫자·기간)은 norm_member 로 강제 변환해 두므로 쓰는 쪽은 형식을 다시 검사하지 않아도 된다."""
    out = []
    for name in sorted(os.listdir(share)):
        d = os.path.join(share, name)
        mp = os.path.join(d, "member.json")
        if not os.path.isdir(d) or not os.path.exists(mp):
            continue
        try:
            m = json.load(open(mp, encoding="utf-8-sig"))
            # 손으로 만든/편집한 member.json 이 형식을 벗어나면 그 사람만 건너뛴다
            # (owner 없는 한 명 때문에 팀 전체 취합이 죽던 것 — 검증 확정)
            if not isinstance(m, dict):
                raise ValueError("member.json 이 객체가 아닙니다")
            if not str(m.get("owner") or "").strip():
                m["owner"] = name          # 폴더 이름을 이름으로 (그 자체가 인원 키다)
                print(f"[aggregate] {name}: member.json 에 owner 가 없어 폴더명을 씁니다")
            m["owner"] = str(m["owner"]).strip()
            norm_member(m, name)
            tag = str(m.get("tag") or "")
            # 개인 대시보드와 같은 우선순위: refined(정제본)가 있으면 그것을
            rows_p = os.path.join(d, f"mm_rows_{tag}.csv")
            ref_p = os.path.join(d, f"mm_rows_{tag}_refined.csv")
            # 단, 정제본이 원본보다 오래됐으면 쓰지 않는다 — 정제 없이 다시 올린 결과가
            # 옛 정제본에 덮여 MM 이 몇 배로 부풀던 실측 결함(같은 기간, 파일명만 다름).
            if os.path.exists(ref_p):
                try:
                    if (not os.path.exists(rows_p)
                            or os.path.getmtime(ref_p) >= os.path.getmtime(rows_p)):
                        rows_p = ref_p
                    else:
                        print(f"[aggregate] {name}: 정제본이 원본보다 오래되어 원본을 씁니다")
                except OSError:
                    rows_p = ref_p
            m["rows"] = (list(csv.DictReader(open(rows_p, encoding="utf-8-sig", errors="replace")))
                         if os.path.exists(rows_p) else [])
            m["rows"] = [r for r in m["rows"] if isinstance(r, dict)]
            pv_p = os.path.join(d, f"pivots_{tag}.json")
            pv = (json.load(open(pv_p, encoding="utf-8-sig")) if os.path.exists(pv_p) else {})
            if not isinstance(pv, dict):
                print(f"[aggregate] {name}: pivots 파일이 객체가 아니라 무시합니다")
                pv = {}
            pv["common"] = norm_common(pv)
            m["pivots"] = pv
        except (OSError, ValueError) as e:
            print(f"[aggregate] {name} 폴더 파일이 깨져 건너뜀 ({type(e).__name__}: {e})")
            continue
        m["dir"] = d
        try:                    # 파일이 놓인 시각 — 흔적이 없는 옛 자료의 최소 단서
            m["file_at"] = time.strftime("%Y-%m-%d %H:%M",
                                         time.localtime(os.path.getmtime(mp)))
        except OSError:
            m["file_at"] = ""
        out.append(m)
    return mark_members(out)       # unreliable · cfg_diff · measure_text — 모든 소비자가 같은 표식을 본다


def leave_days_text(m):
    r"""LM30(2026-10-21) 팀 표 가용 칸 옆 '유급휴가 N일' — 가용에서 실제로 뺀 일수(leave_days — 반차 0.5 · 오늘까지 · teamup.leave_days_of).
    예전 판 member(leave_days 없음)는 absence_days(기간 전체 달력 휴가). 0 이거나 없으면 ''(core\attendance 머리말 22 — 일수만)."""
    v = fnum(m.get("leave_days")) if isinstance(m, dict) else None
    if v is None:
        v = fnum(m.get("absence_days")) if isinstance(m, dict) else None
    return f"유급휴가 {round(v, 1):g}일" if v and v > 0 else ""


def anomaly_badge(m):
    """'PC 기록 이상 N일 · 16h 초과 N일' 배지 — 개인 분석의 입력 이상치 장부를 팀장도 보게(둘 다 0 이면 빈 문자열).
    aggregate 표와 팀 통합 보고서 §1 근거 칸이 같은 함수를 쓴다."""
    an, ld = fint(m.get("anomaly_days"), 0), fint(m.get("long_days"), 0)
    parts = ([f"PC 기록 이상 {an}일"] if an > 0 else []) + ([f"16h 초과 {ld}일"] if ld > 0 else [])
    if not parts:
        return ""
    return ('<span title="그 PC 의 mm_basis 이상치 장부(자르지 않고 표시만) — PC 가동 기록 오류, '
            '하루 16h 를 넘긴 날(휴가일 근무는 세지 않습니다)" style="font-size:10px;color:#b3541e;border:1px solid #e0b394;'
            'border-radius:3px;padding:0 4px;margin-left:6px;white-space:nowrap">'
            + esc(" · ".join(parts)) + "</span>")


def bar(v, vmax, color="#4f8ef7"):
    w = 0 if vmax <= 0 else max(2, round(v / vmax * 220))
    return (f'<svg width="230" height="14"><rect width="{w}" height="14" rx="3" fill="{color}"/>'
            f'<text x="{w+4}" y="11" font-size="10" fill="#666">{v:.2f}</text></svg>')


def norm_name(s):
    """이름 비교 축 — 연속 공백을 하나로, 앞뒤를 떼고, 대소문자를 무시한다.

    '차량  CM' 과 '차량 CM' 과 '차량 cm' 은 사람 눈에 같은 과제다. 예전에는
    글자 그대로 비교해서, 이 한 칸 차이로 정리가 조용히 실패했다."""
    return " ".join(str(s or "").split()).casefold()


class _AliasMap(dict):
    r"""정확히 같은 이름이 없으면 정규화한 이름으로 한 번 더 찾아 주는 매핑.

    이미 팀 공유폴더에 저장돼 있는 옛 team_aliases.json 도 이 덕에 살아난다
    (다시 [유사 항목 정리]를 돌리지 않아도 된다)."""

    def __init__(self, src):
        super().__init__(src or {})
        n = {}
        for _k, v in (src or {}).items():
            n[norm_name(v)] = v          # 대표 이름의 표기 변형도 대표로 접는다
        for k, v in (src or {}).items():
            n[norm_name(k)] = v
        self._n = n

    def get(self, key, default=None):
        if key in self:
            return self[key]
        return self._n.get(norm_name(key), default)


def resolve_chain(mp):
    r"""A→B, B→C 를 A→C 로 끝까지 따라간다(순환은 한 이름으로 모은다).

    사슬을 안 따라가면 같은 과제가 화면에 두 줄로 남는다 — 사용자가 본 그 증상.
    손편집으로 형식이 깨진 매핑(객체가 아니거나 값이 문자열이 아닌 줄)은 그 줄만 버린다."""
    mp = {str(k): v for k, v in mp.items()
          if isinstance(v, str) and str(k).strip() and v.strip()} if isinstance(mp, dict) else {}
    same = {norm_name(k): v for k, v in mp.items() if norm_name(v) == norm_name(k)}
    move = {norm_name(k): v for k, v in mp.items() if norm_name(v) != norm_name(k)}
    votes = {}
    for v in mp.values():
        votes[norm_name(v)] = votes.get(norm_name(v), 0) + 1
    out = {}
    for k, v in mp.items():
        seen, order, cur = {norm_name(k)}, [k], v
        while norm_name(cur) in move and norm_name(cur) not in seen:
            seen.add(norm_name(cur))
            order.append(cur)
            cur = move[norm_name(cur)]
        if norm_name(cur) in seen:                   # 순환 — 한 이름으로 모은다
            i = next(j for j, x in enumerate(order) if norm_name(x) == norm_name(cur))
            cur = sorted(order[i:], key=lambda x: (-votes.get(norm_name(x), 0), x))[0]
        cur = same.get(norm_name(cur), cur)
        if cur != k:
            out[k] = cur
    return out


def load_aliases(share):
    """Copilot 정리 결과(유사 항목 통합 매핑) — team_aliases.json.
    {"projects": {"변형 표기": "대표 표기"}, "details": {...}} 형태.

    읽을 때 사슬을 풀고 정규화 색인을 붙인다 — 저장본이 완벽하지 않아도 합쳐진다."""
    p = os.path.join(share, "team_aliases.json")
    try:
        o = json.load(open(p, encoding="utf-8-sig"))
        if not isinstance(o, dict):          # 손편집 '[]' 한 줄로 취합 전체가 죽지 않게
            print("[aggregate] team_aliases.json 이 객체가 아니라 무시합니다")
            o = {}
        return {"projects": _AliasMap(resolve_chain(o.get("projects") or {})),
                "details": _AliasMap(resolve_chain(o.get("details") or {}))}
    except (OSError, ValueError):
        return {"projects": _AliasMap({}), "details": _AliasMap({})}


# ── 팀 Agentic AI 니즈 후보(LM29부터 — 팀 과제 매칭 없이 인원별 니즈 후보만 모은다) ─────────────────────
def needs_key(name):
    """니즈 후보 이름 비교 축 — core/details.fold 와 같은 규칙(구분자·괄호를 공백으로 · 공백 접기 · 대소문자 무시)."""
    t = unicodedata.normalize("NFKC", str(name or ""))
    t = re.sub(r"[·・ㆍ‧/_\-()\[\]（）]", " ", t)
    return " ".join(t.split()).casefold()


def norm_needs(a2):
    """agentic 결과(dict) → {"tag", "kind": "needs", "new": [정리한 후보]}. 후보는 이름 있는 dict 만, 글자는 길이를 자르고
    근거 업무 행 수(evidence_rows)는 정수로 강제한다 — 업로드된 남의 값('abc'·목록) 한 칸이 취합을 죽이지 않게.
    LM28 파일의 match·misassigned 는 버린다(MM·적합률을 팀 화면에 싣지 않는다)."""
    new = []
    for x in (a2.get("new") if isinstance(a2.get("new"), list) else []):
        if not isinstance(x, dict):
            continue
        nm = " ".join(str(x.get("name") or "").split())[:80]
        if not nm:
            continue
        ev = x.get("evidence_rows")
        new.append({"name": nm, "logic": str(x.get("logic") or "")[:300], "reason": str(x.get("reason") or "")[:300],
                    "evidence_rows": max(0, fint(ev, 0) or 0) if not isinstance(ev, (list, tuple, set)) else 0})
    return {"tag": str(a2.get("tag") or ""), "kind": "needs", "new": new}


def load_agentic(m):
    r"""인원 폴더의 agentic_<기간>.json → norm_needs 사본(없거나 깨졌으면 None). 그 기간 파일이 없으면 같은 폴더의 가장 최근
    agentic_*.json 을 쓰고 other_period=True 를 단다(예전 판으로 올린 사람의 후보가 빠지지 않게 — LM28 팀 보고서와 같은 규칙)."""
    d, tag = m.get("dir") or "", str(m.get("tag") or "")
    ap = os.path.join(d, f"agentic_{tag}.json")
    other = False
    if not (tag and os.path.exists(ap)):
        fs = glob.glob(os.path.join(d, "agentic_*.json")) if d else []
        if not fs:
            return None
        try:
            ap = max(fs, key=os.path.getmtime)
        except OSError:
            ap = sorted(fs)[-1]
        other = True
    try:
        with open(ap, encoding="utf-8-sig") as f:
            a2 = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(a2, dict):
        print(f"[aggregate] {m.get('owner')}: agentic 파일이 객체가 아니라 무시합니다")
        return None
    out = norm_needs(a2)
    out["other_period"] = bool(other and out["tag"] != tag)
    return out


def merge_needs(entries):
    """인원별 니즈 후보 → 팀 Agentic AI 니즈 후보 목록. 이름을 needs_key 로 같게 보고 합친다:
    who(제안 인원 — 이름순) · n(제안 인원 수) · ev(근거 업무 행 합) · names(표기 변형) · logic·reason(더 긴 것).
    대표 이름은 처음 나온 표기. 정렬 = 제안 인원 많은 순 → 근거 행 많은 순 → 이름.
    entries: [{"owner": 이름, "new": [{name, logic, reason, evidence_rows}]}] (load_agentic 이 정리한 꼴)."""
    groups = {}
    for e in entries or []:
        if not isinstance(e, dict):
            continue
        who = str(e.get("owner") or "").strip()
        for n in (e.get("new") if isinstance(e.get("new"), list) else []):
            if not isinstance(n, dict):
                continue
            nm = " ".join(str(n.get("name") or "").split())
            k = needs_key(nm)
            if not k:
                continue
            g = groups.get(k)
            if g is None:
                g = groups[k] = {"name": nm, "names": set(), "who": set(), "logic": "", "reason": "", "ev": 0}
            g["names"].add(nm)
            if who:
                g["who"].add(who)
            g["ev"] += max(0, fint(n.get("evidence_rows"), 0) or 0)
            for fld in ("logic", "reason"):
                v = str(n.get(fld) or "")
                if len(v) > len(g[fld]):
                    g[fld] = v
    out = [{"name": g["name"], "names": sorted(g["names"]), "who": sorted(g["who"]), "n": len(g["who"]),
            "logic": g["logic"], "reason": g["reason"], "ev": g["ev"]} for g in groups.values()]
    out.sort(key=lambda g: (-g["n"], -g["ev"], g["name"]))
    return out


def collect_needs(members):
    """인원 목록 → (팀 니즈 후보 merge_needs, 후보 파일이 있는 인원 수, 다른 기간 결과를 쓴 인원). 측정 불충분 인원도
    넣는다 — 니즈 후보는 그 사람의 업무 내용이지 투입 시간 비교가 아니다."""
    entries, other = [], []
    for m in members:
        try:
            a2 = load_agentic(m)
        except Exception as e:  # noqa: BLE001 - 인원 하나 때문에 팀 화면을 잃지 않는다
            print(f"[aggregate] {m.get('owner')}: 니즈 후보 읽기 실패({type(e).__name__}) — 이 인원은 건너뜀")
            a2 = None
        if a2 is None:
            continue
        entries.append({"owner": m["owner"], "new": a2["new"]})
        if a2.get("other_period"):
            other.append(m["owner"])
    return merge_needs(entries), len(entries), other


def collect_team_data(share):
    """팀 뷰어 UI 용 실시간 취합 — 공유폴더를 읽어 시각화 가능한 JSON 을 만든다.
    team_aliases.json(Copilot 정리 결과)이 있으면 과제·세부업무 표기를 대표 이름으로 통합."""
    members = load_members(share)
    al = load_aliases(share)
    pj_map, dt_map = al["projects"], al["details"]
    out = {"share": share, "aliases": bool(pj_map or dt_map),
           "alias_n": len(pj_map) + len(dt_map), "members": [],
           "matrix": {}, "details": {}, "wt": {}, "common": [],
           # D5(b) — 측정 불충분(unreliable) 인원: 표에는 남되 팀 평균·순위·과제 매트릭스·유형 분포에서 뺀다
           "excluded": [m["owner"] for m in members if m.get("unreliable")]}
    matrix = defaultdict(lambda: defaultdict(float))
    details = defaultdict(lambda: defaultdict(float))
    wt_dist = defaultdict(lambda: defaultdict(float))
    common_all = defaultdict(lambda: {"mm": 0.0, "models": set(), "who": set()})
    for m in members:
        who = m["owner"]
        out["members"].append({
            "owner": who, "function": m.get("function", ""),
            "period": m.get("period") or [], "tag": m.get("tag", ""),
            "total_mm": m.get("total_mm") or 0.0,
            "avail_mm": m.get("avail_mm") or 0.0,
            "load_pct": m.get("load_pct"),
            "signals": m.get("signals"), "worked_h": m.get("worked_h"),
            "no_evidence_days": m.get("no_evidence_days"),
            "absence_days": m.get("absence_days"),
            # LM30(2026-10-21) 가용에서 뺀 유급휴가 일수(leave_days_text) · 휴가로 본 평일 수 — 화면이 '무흔적 평일'에서 뺀다(휴가를 일하지
            # 않은 날처럼 보이지 않게)
            "leave_days": m.get("leave_days"),
            "inferred_absence_days": m.get("inferred_absence_days") or 0,
            # PC 기록 이상·16h 초과 일수 — 개인 mm_basis 의 anomalies/long_days 를 teamup 이 개수로 올린다
            "anomaly_days": m.get("anomaly_days") or 0,
            "long_days": m.get("long_days") or 0,
            # D5 — 측정 방식·신뢰도·산식 설정(구판 자료는 None/False — 화면이 배지를 생략한다)
            "measure": m.get("measure"), "coverage": m.get("coverage"), "cfg_used": m.get("cfg_used"),
            # 프로그램 사용 이력 — 여기 빠지면 팀 화면에서 오류 없이 통째로 사라진다(조용한 화이트리스트)
            "tool_usage": m.get("tool_usage"),
            # LM30 출퇴근 추정의 달·전체 합계(근무·연장·야간·휴일·PC 밖·52시간 넘은 주·휴가일 근무 — 시각 없음).
            # 팀 통합 보고서 v3(로드율 제외본)에서는 개인 근무 시간이라 뺀다(team_report)
            "attendance": m.get("attendance"),
            "measure_text": m.get("measure_text", ""),
            "unreliable": bool(m.get("unreliable")), "cfg_diff": bool(m.get("cfg_diff")),
            # 누가·언제·어디서 (없으면 빈 값 — 옛 클라이언트가 올린 자료도 그대로 표시된다)
            "host": m.get("host", ""), "analyzed_at": m.get("analyzed_at", ""),
            "uploaded_at": m.get("uploaded_at", ""),
            "uploaded_from": m.get("uploaded_from", ""),
            "via": m.get("via", ""),
            "file_at": m.get("file_at", "")})
        if m.get("unreliable"):
            continue        # 비교 집계(매트릭스·세부·유형·공통업무)에서 제외 — 인별 표에는 위에서 남겼다
        try:                # 한 인원의 행·피벗이 이상해도 나머지 인원은 그대로 취합한다
            rows = [(r, fnum(r.get("mm"))) for r in m["rows"]]
            rows = [(r, mm) for r, mm in rows if mm is not None]
            # 행 MM 은 공식 투입(member.total_mm)에 맞춘다 — 규칙은 mm_scale 한 곳
            k9 = mm_scale(m.get("total_mm"), sum(mm for _r, mm in rows))
            for r, mm in rows:
                mm *= k9
                pj = pj_map.get(r.get("Level 2") or "공통", r.get("Level 2") or "공통")
                dt = dt_map.get(r.get("Level 3") or "기타", r.get("Level 3") or "기타")
                matrix[pj][who] += mm
                details[f"{pj} / {dt}"][who] += mm
                wt_dist[who][r.get("유형") or "사무"] += mm
            for c in (m["pivots"].get("common") or []):
                k = dt_map.get(c.get("detail"), c.get("detail"))
                common_all[k]["mm"] += fnum(c.get("mm"), 0.0) * k9
                common_all[k]["models"].update(pj_map.get(x, x) for x in (c.get("models") or []))
                common_all[k]["who"].add(who)
        except Exception as e:  # noqa: BLE001 - 인원 하나 때문에 팀 화면을 잃지 않는다
            print(f"[aggregate] {who}: 행 집계 실패({type(e).__name__}: {e}) — 이 인원의 행은 건너뜀")
    out["matrix"] = {k: dict(v) for k, v in
                     sorted(matrix.items(), key=lambda kv: -sum(kv[1].values()))}
    out["details"] = {k: dict(v) for k, v in
                      sorted(details.items(), key=lambda kv: -sum(kv[1].values()))[:40]}
    out["wt"] = {k: dict(v) for k, v in wt_dist.items()}
    out["common"] = sorted(
        [{"detail": k, "models": sorted(v["models"]), "who": sorted(v["who"]),
          "mm": round(v["mm"], 3)} for k, v in common_all.items()],
        key=lambda x: -(len(x["who"]) * 10 + x["mm"]))[:15]
    # 팀 Agentic AI 니즈 후보 — 인원별 후보를 이름으로 합친 것(LM29부터 · 팀 과제 매칭 없음)
    out["needs"], out["agentic_n"], out["needs_other"] = collect_needs(members)
    return out


def visual_report(share, data):
    r"""팀 화면(TEAM_PAGE)을 그대로 담은 정적 리포트 — 서버 없이 열리는 한 파일.

    ui/app.py 를 '텍스트로' 읽어 TEAM_PAGE 문자열만 꺼낸다(임포트하면 서버 모듈이 실행된다).
    데이터는 window.__TEAM_DATA__ 로 박아 넣고, 조작 카드는 스냅샷 모드에서 숨겨진다."""
    up = os.path.join(ROOT, "ui", "app.py")
    try:
        tree = ast.parse(open(up, encoding="utf-8").read())
    except (OSError, SyntaxError) as e:
        print(f"[aggregate] 화면 템플릿을 읽지 못했습니다({type(e).__name__}) — 표 형식 리포트로 대체")
        return ""
    page = ""
    for node in tree.body:
        if (isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "TEAM_PAGE"
                and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)):
            page = node.value.value
            break
    if not page or "</body>" not in page:
        print("[aggregate] 화면 템플릿(TEAM_PAGE)을 찾지 못했습니다 — 표 형식 리포트로 대체")
        return ""
    # '<' 를 통째로 < 로 — 팀원 이름·과제명은 업로드로 들어온 남의 값이라 '</script>' 나
    # '<!--<script' 를 넣으면 이 파일을 여는 팀 전체 브라우저에서 코드가 실행된다(저장형 XSS,
    # 검증 확정). JSON 문자열 안에서는 < 가 '<' 로 정상 복원된다.
    payload = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")
    stamp = time.strftime("%Y-%m-%d %H:%M")
    inject = ("<script>window.__TEAM_DATA__=" + payload + ";"
              + "window.__SNAP_AT__=" + json.dumps(stamp) + ";</script>\n")
    # 본문 스크립트보다 먼저 실행돼야 한다 — 마지막 <script> 앞에 넣는다
    cut = page.rindex("<script>")
    outp = os.path.join(share, "team_report.html")
    body = page[:cut] + inject + page[cut:]
    # 팀 서버는 업로드마다 취합을 돌린다 — 동시에 두 번 돌면 같은 이름의 임시 파일을 서로 밟는다.
    # pid 를 붙여 각자 자기 파일만 쓰게 한다.
    tmp = f"{outp}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(body)
    try:
        os.replace(tmp, outp)
    except OSError:
        # 윈도우에서는 대상 파일을 누가 '열어 두기만' 해도 replace 가 실패한다
        # (브라우저 탭·워드·백신). 그때는 그냥 덮어쓴다 — open(...,"w") 는 대개 성공한다.
        try:
            with open(outp, "w", encoding="utf-8") as f:
                f.write(body)
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass
    return outp


def main():
    share = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else ""
    if not share:
        cfg = json.load(open(os.path.join(ROOT, "config", "config.json"), encoding="utf-8-sig"))
        share = (cfg.get("teamShareDir") or "").strip()
    if not share or not os.path.isdir(share):
        print("[aggregate] 공유폴더 없음 — 인자로 경로를 주거나 config.teamShareDir 설정")
        print(json.dumps({"ok": False, "error": "no share"}))
        return 1
    members = load_members(share)
    if not members:
        print(f"[aggregate] 취합할 인원이 없습니다 ({share} 아래 <이름>\\member.json 필요)")
        print(json.dumps({"ok": False, "error": "no members", "share": share}, ensure_ascii=False))
        return 1

    # 과제×인원 MM 매트릭스 + 유형 분포 + 공통업무 합산
    # 유사 항목 정리 결과(team_aliases.json)를 정적 리포트에도 적용한다 — 팀 뷰어
    # (collect_team_data)에서만 통합되고 이 HTML 은 갈라져 있어 같은 과제가 따로 잡혔다.
    al = load_aliases(share)
    pj_map, dt_map = al["projects"], al["details"]
    matrix = defaultdict(lambda: defaultdict(float))
    wt_dist = defaultdict(lambda: defaultdict(float))
    common_all = defaultdict(lambda: {"mm": 0.0, "models": set(), "who": set()})
    rescaled = []                  # 행 합이 공식 투입과 달라 재스케일된 인원 — 표에 밝힌다
    # D5(b) — 측정 불충분(coverage.grade=unreliable: PC 기록·샘플러·달력이 모두 결측) 인원은 팀 평균·순위·
    # 재스케일(mm_scale)·과제 매트릭스에서 빼고 §1 에 별도 표로 둔다. 파일만 수집된 사람(36%)이 '정상
    # 결과' 로 표에 섞이던 것을 막는다. 구판 자료(coverage 없음)는 예전처럼 비교에 들어간다.
    members_cmp = [m for m in members if not m.get("unreliable")]
    members_x = [m for m in members if m.get("unreliable")]
    for m in members_cmp:
        who = m["owner"]
        try:                # 한 인원의 행·피벗이 이상해도 나머지 인원은 그대로 취합한다
            rows = [(r, fnum(r.get("mm"))) for r in m["rows"]]
            rows = [(r, mm) for r, mm in rows if mm is not None]
            raw_sum = sum(mm for _r, mm in rows)
            # 행 MM 을 공식 투입(member.total_mm)에 맞춘다 — §1·§2·§3 이 같은 수치가 되게(규칙: mm_scale)
            k9 = mm_scale(m.get("total_mm"), raw_sum)
            if abs(k9 - 1.0) > 0.05:
                rescaled.append(f"{who} {raw_sum:.2f}→{fnum(m.get('total_mm'), 0.0):.2f}")
            for r, mm in rows:
                mm *= k9
                lv2 = r.get("Level 2") or "공통"
                matrix[pj_map.get(lv2, lv2)][who] += mm
                wt_dist[who][r.get("유형") or "사무"] += mm
            for c in (m["pivots"].get("common") or []):
                k = dt_map.get(c.get("detail"), c.get("detail"))
                common_all[k]["mm"] += fnum(c.get("mm"), 0.0) * k9
                common_all[k]["models"].update(pj_map.get(x, x) for x in (c.get("models") or []))
                common_all[k]["who"].add(who)
        except Exception as e:  # noqa: BLE001 - 인원 하나 때문에 취합 전체를 rc=1 로 잃지 않는다
            print(f"[aggregate] {who}: 행 집계 실패({type(e).__name__}: {e}) — 이 인원의 행은 건너뜀")

    # 인별 투입 = 공식값(member.total_mm), 없으면 행 합 — §2 열 합과 같은 값이 되게 위에서 맞췄다
    tot_by_member = {m["owner"]: (m.get("total_mm") or sum(matrix[md][m["owner"]] for md in matrix))
                     for m in members}
    vmax = max([tot_by_member[m["owner"]] for m in members_cmp] or [1]) or 1   # 순위·막대는 비교 인원 기준
    models_sorted = sorted(matrix, key=lambda md: -sum(matrix[md].values()))
    WT = ["개발", "사무", "현장", "협업"]
    WTC = {"개발": "#4f8ef7", "사무": "#f7b94f", "현장": "#4fc47f", "협업": "#b06ef7"}

    h = ["<!doctype html><meta charset='utf-8'><title>팀 로드율 총괄</title>",
         "<style>body{font:14px 'Malgun Gothic',sans-serif;max-width:1100px;margin:24px auto;color:#222}",
         "table{border-collapse:collapse;width:100%;margin:8px 0 24px}th,td{border:1px solid #ddd;",
         "padding:5px 8px;text-align:left;font-size:13px}th{background:#f5f7fa}",
         "h2{margin:26px 0 4px;font-size:17px}.dim{color:#888;font-size:12px}</style>",
         f"<h1>팀 업무 로드율 총괄</h1><p class='dim'>공유폴더: {esc(share)} · 인원 {len(members)}명"
         + (f"(측정 불충분 {len(members_x)}명은 비교 제외)" if members_x else "")
         + " · MM = 주40시간(평일 8h) 가동시간 기준, 야간은 산출물 있는 날만 인정</p>"]

    def _row1(m, grey=False):
        t = tot_by_member[m["owner"]]
        av = m.get("avail_mm")
        pct = m.get("load_pct")
        if pct is None and av:
            pct = round(t / av * 100, 1)
        warn = []
        # LM30(2026-10-21) 무흔적 평일은 휴가로 본 평일을 뺀 수 · 유급휴가는 신뢰도 근거(경고)가 아니다 — 가용 칸에 일수만(일하지 않은 날로 세지 않는다)
        noev = max(0, fint(m.get("no_evidence_days"), 0) - fint(m.get("inferred_absence_days"), 0))
        if noev:
            warn.append(f"무흔적 평일 {noev}일")
        if m.get("gap_days"):
            warn.append(f"연속공백 {m['gap_days']}회 제외")
        if m.get("rehours") and fnum(m.get("dropped_h")):
            warn.append(f"비업무 제외 −{fnum(m.get('dropped_h'), 0.0):.1f}h")
        badge = anomaly_badge(m) + coverage_badge(m) + cfg_badge(m)
        return (f"<tr{' style=color:#8b929b' if grey else ''}><td>{esc(m['owner'])}</td><td>{esc(m.get('function'))}</td>"
                f"<td>{esc('~'.join(m.get('period') or []))}</td><td><b>{t:.2f}</b></td>"
                f"<td>{'–' if av is None else format(av, '.2f')}"
                + (f" <span class='dim'>{esc(leave_days_text(m))}</span>" if leave_days_text(m) else "")
                + "</td>"
                f"<td><b>{pct_text(pct)}</b></td>"
                f"<td>{'' if grey else bar(t, vmax)}</td>"
                f"<td class='dim'>{esc(measure_text(m)) or '-'}</td>"
                f"<td class='dim'>{esc(' · '.join(warn)) or '-'} · 신호 {esc(m.get('signals'))}건"
                f"{badge}</td></tr>")

    HEAD1 = ("<table><tr><th>이름</th><th>파트</th><th>기간</th><th>투입 MM</th><th>가용 MM</th>"
             "<th>로드율</th><th></th><th>측정 방식</th><th>신뢰도 근거</th></tr>")
    h.append("<h2>1. 인별 로드율 (투입 MM ÷ 가용 MM)</h2>"
             "<p class='dim'>가용 MM = 그 기간에 일할 수 있었던 양 — 유급휴가(연차·반차)는 법정 휴가라 일하지 않은 날로 세지 않고 가용에서 뺍니다 · "
             "투입 MM = 실제 투입 시간(야근은 상한 없이 반영(하루 24h 물리 한계만)) · 로드율 100% = 가용을 꽉 채워 일함 · "
             "'PC 기록 이상'·'16h 초과' 는 그 PC 의 입력 이상치 장부(자르지 않고 표시만)에서 온 일수 · "
             "측정 방식 = 투입 시간을 무엇으로 쟀는가(샘플러 실측 / PC 가동 하한 / 흔적 폭 / 종일 행사 / 수동 기록 일수) · "
             "신뢰(PC 기록≥40%·샘플러·달력 모두 있음) / 주의(일부 결측) / 측정 불충분(전부 결측 — 비교 제외) · "
             "'산식 설정 상이' = 표준시간·점심·주간 창·공휴일 수 등이 팀 다수와 달라 분모가 다른 사람</p>" + HEAD1)
    for m in members_cmp:
        h.append(_row1(m))
    h.append("</table>")
    if members_x:
        h.append("<h3 style='font-size:14px;margin:4px 0'>측정 불충분 — 팀 평균·순위·과제 매트릭스에서 제외</h3>"
                 "<p class='dim'>PC 가동 기록·창 샘플러·Outlook 일정이 모두 비어 투입 시간의 근거가 파일 흔적뿐인 인원 — "
                 "수집 실패이지 낮은 로드가 아닙니다. 그 PC 에서 수집을 살린 뒤 다시 올리면 비교에 들어갑니다.</p>" + HEAD1)
        for m in members_x:
            h.append(_row1(m, grey=True))
        h.append("</table>")

    h.append("<h2>2. 과제 × 인원 (MM)</h2>"
             + ("<p class='dim'>행 MM 합이 공식 투입(1절)과 달라 투입에 맞춰 재스케일한 인원: "
                + esc(", ".join(rescaled)) + "</p>" if rescaled else "")
             + ("<p class='dim'>측정 불충분으로 제외한 인원: "
                + esc(", ".join(m["owner"] for m in members_x))
                + " — 과제 배분은 그 사람의 개인 리포트를 보세요</p>" if members_x else "")
             + "<table><tr><th>과제</th>"
             + "".join(f"<th>{esc(m['owner'])}</th>" for m in members_cmp) + "<th>합계</th></tr>")
    for md in models_sorted:
        cells = "".join(f"<td>{matrix[md][m['owner']]:.2f}</td>" if matrix[md][m["owner"]] else "<td class='dim'>-</td>"
                        for m in members_cmp)
        h.append(f"<tr><td><b>{esc(md)}</b></td>{cells}<td><b>{sum(matrix[md].values()):.2f}</b></td></tr>")
    h.append("</table>")

    h.append("<h2>3. 업무유형 분포 (인별 MM)</h2><table><tr><th>이름</th>"
             + "".join(f"<th style='color:{WTC[w]}'>{w}</th>" for w in WT) + "</tr>")
    for m in members_cmp:
        h.append(f"<tr><td>{esc(m['owner'])}</td>"
                 + "".join(f"<td>{wt_dist[m['owner']].get(w, 0):.2f}</td>" for w in WT) + "</tr>")
    h.append("</table>")

    h.append("<h2>4. 공통업무 — 표준화·자동화 후보</h2>"
             "<p class='dim'>여러 과제·여러 사람에게 반복되는 세부업무일수록 표준화·AI 대체 우선순위가 높다</p>"
             "<table><tr><th>세부업무</th><th>관련 과제</th><th>수행 인원</th><th>합산 MM</th></tr>")
    for k, v in sorted(common_all.items(), key=lambda kv: -(len(kv[1]["who"]) * 10 + kv[1]["mm"]))[:15]:
        h.append(f"<tr><td><b>{esc(k)}</b></td><td>{esc(', '.join(sorted(v['models'])))}</td>"
                 f"<td>{esc(', '.join(sorted(v['who'])))}</td><td>{v['mm']:.2f}</td></tr>")
    h.append("</table>")

    # 팀 Agentic AI 니즈 후보 — 인원별 후보를 이름으로 합친 것(팀 과제 매칭 없음 · MM 없이 근거 업무 행 수만)
    needs, ag_n, needs_other = collect_needs(members)
    h.append("<h2>5. 팀 Agentic AI 니즈 후보</h2>"
             f"<p class='dim'>니즈 후보 결과가 있는 인원 {ag_n}명 · 같은 이름(띄어쓰기·구분자 무시)은 합쳤습니다 · "
             "근거 업무 = 제안한 사람들의 근거 업무 행 수 합(MM 아님)"
             + (f" · 다른 기간 결과를 쓴 인원: {esc(', '.join(needs_other))}" if needs_other else "") + "</p>"
             "<table><tr><th>후보</th><th>제안 인원</th><th>근거 업무(행)</th><th>동작 로직 · 발굴 사유</th></tr>")
    for g in needs[:30]:
        h.append(f"<tr><td><b>{esc(g['name'])}</b></td><td>{g['n']}명 — {esc(', '.join(g['who']))}</td>"
                 f"<td>{int(g['ev'])}</td><td>{esc(g['logic'])}<br><span class='dim'>{esc(g['reason'])}</span></td></tr>")
    if not needs:
        h.append("<tr><td colspan=4 class='dim'>발굴된 니즈 후보가 없습니다</td></tr>")
    h.append("</table>")

    h.append("<h2>6. raw 단서</h2><p class='dim'>수치가 이상하면 본인 폴더의 signals_*.csv(신호 원문·판정)로 확인 — "
             "각 행에 출처·원문·AI 판정이 남아 있어 오해석을 막는다</p><ul>")
    for m in members:
        h.append(f"<li>{esc(m['owner'])}: {esc(m['dir'])}\\signals_{esc(m.get('tag'))}.csv "
                 f"<span class='dim'>(신호 {esc(m.get('signals'))}건 · 인정 {esc(m.get('worked_h'))}h)</span></li>")
    h.append("</ul>")

    out_html = os.path.join(share, "team_report.html")
    # 화면 그대로의 리포트를 먼저 시도하고(사용자 요청), 실패하면 표 형식으로 대체한다
    vis = ""
    try:
        vis = visual_report(share, collect_team_data(share))
    except Exception as e:                      # 리포트 하나 때문에 취합 전체를 잃지 않는다
        print(f"[aggregate] 화면형 리포트 생성 실패({type(e).__name__}: {e}) — 표 형식으로 대체")
    if not vis:
        try:
            with open(out_html, "w", encoding="utf-8") as f:
                f.write("\n".join(h))
        except OSError as e:      # 리포트 하나 때문에 취합 전체를 rc=1 로 잃지 않는다
            print(f"[aggregate] 리포트 저장 실패({type(e).__name__}) — 취합 자료는 정상입니다")
    else:
        # 표 형식도 함께 남긴다 — 인쇄·발췌용
        with open(os.path.join(share, "team_report_표.html"), "w", encoding="utf-8") as f:
            f.write("\n".join(h))
    with open(os.path.join(share, "team_mm.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["과제"] + [m["owner"] for m in members_cmp] + ["합계"])   # 측정 불충분 인원은 열에서도 제외
        for md in models_sorted:
            w.writerow([md] + [round(matrix[md][m["owner"]], 3) for m in members_cmp]
                       + [round(sum(matrix[md].values()), 3)])
    # 팀 통합 보고서(team_full_report.html / _v3) — 캐시만 적용(Copilot 없음). 팀 서버가
    # 업로드마다 이 파일을 돌리므로 여기서 함께 갱신된다. 실패해도 취합 rc 는 잃지 않는다.
    full = {}
    try:
        import team_report
        full = team_report.build(share, snapshot=("--snapshot" in sys.argv)) or {}
        print(f"[aggregate] 팀 통합 보고서 → {full.get('full', '')} "
              f"(v3: {os.path.basename(full.get('v3', '') or '')})")
    except Exception as e:  # noqa: BLE001 - 통합보고서 하나 때문에 취합 rc 를 잃지 않는다
        print(f"[aggregate] 팀 통합 보고서 생성 실패({type(e).__name__}: {e}) — 취합 자료는 정상입니다")
    print(f"[aggregate] {len(members)}명 · 과제 {len(models_sorted)}개 → {out_html}")
    print(f"[aggregate] 팀 Agentic AI 니즈 후보 {len(needs)}건 (후보 결과 {ag_n}명)")
    print(json.dumps({"ok": True, "members": len(members), "agentic": ag_n, "needs": len(needs),
                      "report": out_html,
                      "full_report": full.get("full", ""), "full_v3": full.get("v3", ""),
                      "snapshots": full.get("snapshots") or []}, ensure_ascii=False))
    if "--open" in sys.argv:                     # 팀취합 bat 경로 — 결과를 바로 브라우저로
        import webbrowser
        webbrowser.open(out_html)
        if full.get("full"):
            webbrowser.open(full["full"])
    return 0


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, errors="replace", encoding=(
        (sys.stdout.encoding or "utf-8") if sys.stdout.isatty() else "utf-8"))  # 콘솔(bat)=콘솔 코드페이지 · 파이프(UI)=utf-8
    sys.exit(main())
