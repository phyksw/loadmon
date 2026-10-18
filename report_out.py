# -*- coding: utf-8 -*-
"""
report_out.py — 현재 분석 결과를 하나의 리포트 파일로 출력한다 (8b).

  python report_out.py                       # 최신 결과
  python report_out.py --from ... --to ...

출력: report\\리포트_<기간>.html   (브라우저에서 열람, Word에서 [파일 > 열기]로 편집 가능)
      report\\리포트_<기간>.doc    (더블클릭하면 Word로 열림 — 같은 내용)

담기는 것: 투입/가용 MM·로드율(LM30v1 — 법정 채움이면 1절이 달마다 1MM 기준·법정 채움·근무·LM30 방식 MM · legal_section)
          · 과제별 로드 · 업무분류 배분 · 공통업무(표준화·자동화 후보)
          · 월별 리뷰 코멘트(빠진 달은 다른 기간 파일에서 이월 — core/narratives) · Agentic AI 니즈 후보(LM29부터 — 발굴만)
          · 산정 근거와 신뢰도(초과근무 세분·미관측 일수)
          · 출퇴근·시간외 근무(LM30 — 결론 한 줄·재는 법·달·주 합계·최근 31일 날짜별 출근·퇴근·근태 기록 비교 · attendance_section)
          · 산출 방식(PC 가동 하한의 근거·날짜별 방식 최신순·퇴근 후·시각 · 시간 근거 합계 — LM30부터는 'LM29 방식(비교용) 근거')
          · raw 단서 요약 · 같이 일한 동료 · 연관 업무 · 업무 영역·과제 워크플로 요약(단위업무 등급)
표기(LM28): 업무 영역(Level 1) / 과제(Level 2) / 세부업무(Level 3) / 업무분류(개발·사무·현장·협업).
'대체 가능 MM' 은 계산하지도 보이지도 않는다(A-33 RP4 — 실측 투입·빈도만).
"""
import csv
import glob
import html
import io
import json
import os
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.abspath(__file__))
REP = os.path.join(ROOT, "report")
if os.path.join(ROOT, "core") not in sys.path:         # privacy(동료 절의 외부 계급)·details — LM28
    sys.path.insert(0, os.path.join(ROOT, "core"))


def _fresh_refined(plain, refined):
    """정제본을 써도 되는가 — 원본보다 오래된 정제본은 쓰지 않는다.

    정제 없이 다시 분석해 원본만 새로 쓰인 경우, 옛 정제본을 그대로 쓰면 화면·리포트·
    워크플로우가 옛 숫자를 말한다(실측 확인된 결함)."""
    if not os.path.exists(refined):
        return False
    try:
        return (not os.path.exists(plain)
                or os.path.getmtime(refined) >= os.path.getmtime(plain))
    except OSError:
        return True


def arg(flag, d=""):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else d


def esc(x):
    return html.escape(str(x if x is not None else ""))


def _json(p):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _rows(p):
    # 다른 도구가 CP949 로 저장한 CSV 도 견딘다 — UnicodeDecodeError 로 리포트 생성이
    # 통째로 죽던 결함(검증 확정). utf-8 실패 시 cp949 재시도로 내용까지 살린다.
    for enc in ("utf-8-sig", "cp949"):
        try:
            with open(p, encoding=enc) as f:
                return list(csv.DictReader(f))
        except UnicodeDecodeError:
            continue
        except (OSError, csv.Error):
            return []
    try:
        with open(p, encoding="utf-8-sig", errors="replace") as f:
            return list(csv.DictReader(f))
    except (OSError, csv.Error):
        return []


def latest_tag():
    fs = sorted(glob.glob(os.path.join(REP, "mm_meta_*.json")), key=os.path.getmtime)
    return os.path.basename(fs[-1])[len("mm_meta_"):-len(".json")] if fs else ""


# ── LM22 2차: 측정 방식·신뢰도·추가 보정 키 (mm_basis → meta 최상위 → meta.mm_info 순으로 찾는다) ──
GRADE_LABEL = {"reliable": "신뢰", "caution": "주의", "unreliable": "측정 불충분"}
GRADE_COLOR = {"reliable": "#0f7a3d", "caution": "#c98a00", "unreliable": "#c0122f"}


def _pick(meta, b, key):
    for src in (b, meta, meta.get("mm_info") if isinstance(meta.get("mm_info"), dict) else {}):
        if isinstance(src, dict) and src.get(key) is not None:
            return src.get(key)
    return None


def _obj(v):
    return v if isinstance(v, dict) else None


def _n(v):
    """일수·건수 — 목록/객체면 길이, 숫자면 정수, 아니면 0"""
    if isinstance(v, bool):
        return 0
    if isinstance(v, (list, tuple, dict)):
        return len(v)
    try:
        return int(round(float(v)))
    except (TypeError, ValueError):
        return 0


def _h(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def measure_line(meta, b):
    """'샘플러 N일 / PC 하한 N일 / 흔적폭 N일 / 출장 N일 / 수동 N일' (+ 산정 방법) — measure 가 없으면 mm_basis 일수로"""
    ms = _obj(_pick(meta, b, "measure")) or {}
    src = ms if ms else b
    if not src:
        return ""
    parts = [f"샘플러 {_n(src.get('sampler_days'))}일", f"PC 하한 {_n(src.get('pc_floor_days'))}일",
             f"흔적폭 {_n(src.get('trace_window_days'))}일", f"출장 {_n(src.get('offsite_days'))}일",
             f"수동 {_n(src.get('manual_days'))}일"]
    # LM28(E) — PC 기록 없는 달의 표준일 추정·브라우저 기록만 있는 평일(값이 있을 때만)
    if _n(src.get("std_nopc_days")):
        parts.append(f"표준일 추정 {_n(src.get('std_nopc_days'))}일")
    if _n(src.get("hint_only_days")):
        parts.append(f"브라우저 기록만 {_n(src.get('hint_only_days'))}일")
    meth = str(ms.get("method") or b.get("method") or "")
    return " / ".join(parts) + (f" ({esc(meth)})" if meth else "")


def coverage_badge(meta, b):
    cv = _obj(_pick(meta, b, "coverage")) or {}
    g = str(cv.get("grade") or "").lower()
    if g not in GRADE_LABEL:
        return ""
    reasons = cv.get("reasons") if isinstance(cv.get("reasons"), list) else (
        cv.get("missing") if isinstance(cv.get("missing"), list) else [])
    tip = " · ".join(str(x) for x in reasons) or "측정 신뢰도 등급(PC 기록 40%·샘플러·달력 결측 수)"
    return (f"<span class='tag' title='{esc(tip)}' style='border:1px solid {GRADE_COLOR[g]};color:{GRADE_COLOR[g]};"
            f"background:#fff;vertical-align:middle'>{GRADE_LABEL[g]}</span>")


TOOL_NOTE = "참고 지표 — 투입 MM·로드율과 무관 · 실행 기록은 Windows 가 사용자 계정에 남긴 실행 흔적(관리자 권한 불필요)"


def _tool_ev(p):
    """프로그램 한 줄의 가장 센 근거 한 마디 — 창기록 시간 > 실행 증가분 > 누적 실행 > 파일 일수 > 배경 솔버."""
    if _h(p.get("hours")) >= 0.05:
        return f"{_h(p.get('hours')):.1f}h" + (f"(배경 {_h(p.get('bg_hours')):.0f}h)" if _h(p.get("bg_hours")) >= 1 else "")
    if p.get("runs") is not None and _n(p.get("runs")):
        return f"실행 {_n(p.get('runs'))}회"
    if p.get("focus_h") is not None and _h(p.get("focus_h")) >= 0.05:      # 띄워 둔 채 쓴 도구 — 새 실행 없이 포커스만
        return f"포커스 {_h(p.get('focus_h')):.1f}h"
    if p.get("runs_cum") is not None and _n(p.get("runs_cum")):
        return f"누적 실행 {_n(p.get('runs_cum'))}회"
    if _n(p.get("file_days")):
        return f"파일 {_n(p.get('file_days'))}일"
    if _h(p.get("bg_hours")) >= 1:
        return f"배경 {_h(p.get('bg_hours')):.0f}h"
    return str(p.get("last_run") or "")[:10]


def tool_usage_text(tu):
    """8절 '프로그램 사용(참고)' 칸의 글(태그 없이 — 셀은 부르는 쪽이 통째로 esc 한다). 옛 꼴(창기록만)·새 꼴 둘 다. 비면 ''."""
    tu = tu if isinstance(tu, dict) else {}
    progs = [p for p in (tu.get("programs") or []) if isinstance(p, dict) and p.get("name")]
    inh = [x for x in (tu.get("inhouse") or []) if isinstance(x, dict) and x.get("name")]
    if not progs and not inh and not _n(tu.get("inhouse_hidden")):
        return str(tu.get("why") or "").strip()
    v = " · ".join(f"{p.get('name')}({_tool_ev(p)})" if _tool_ev(p) else str(p.get("name")) for p in progs[:6])
    kinds = [x for x in (tu.get("by_kind_n") or []) if isinstance(x, (list, tuple)) and len(x) >= 2]
    if kinds:
        v += " / 구분: " + " · ".join(f"{x[0]} {_n(x[1])}개" for x in kinds)
    else:
        hk = [x for x in (tu.get("by_kind") or []) if isinstance(x, (list, tuple)) and len(x) >= 2 and _h(x[1]) > 0]
        if hk:
            v += " / 구분: " + " · ".join(f"{x[0]} {_h(x[1]):.1f}h" for x in hk)
    if inh or _n(tu.get("inhouse_hidden")):
        v += f" / 자체·프로토타입(추정) {len(inh) + _n(tu.get('inhouse_hidden'))}개"
    if _h(tu.get("solver_bg_h")) >= 1:
        v += f" / 배경 솔버 가동 {_h(tu.get('solver_bg_h')):.0f}h"
    if _h(tu.get("unknown_h")) >= 1:
        v += f" / 창기록 미상 {_h(tu.get('unknown_h')):.0f}h(카탈로그에 없는 실행 파일)"
    return v + " / ※ " + str(tu.get("note") or TOOL_NOTE) + (" — 상세는 아래 표" if tu.get("sources") else "")


def tool_usage_table(tu):
    """8절 뒤에 붙는 프로그램 사용 상세 표(HTML — 값은 전부 esc). 출처·실행 횟수·포커스 시간·마지막 실행·파일 일수와
    자체·프로토타입(추정) 목록. 새 꼴(sources 가 있는 것)만 — 옛 꼴은 8절 한 칸으로 충분하다. 비면 ''."""
    tu = tu if isinstance(tu, dict) else {}
    if not isinstance(tu.get("sources"), dict):
        return ""
    progs = [p for p in (tu.get("programs") or []) if isinstance(p, dict) and p.get("name")]
    inh = [x for x in (tu.get("inhouse") or []) if isinstance(x, dict) and x.get("name")]
    if not progs and not inh:
        return ""

    def cnt(v, c):
        if v is None:
            return "–" if c is None else f"누적 {_n(c):,}"
        return f"{_n(v):,}회"

    def hrs(v, c):
        if v is None:
            return f"누적 {_h(c):.1f}h" if _h(c) else "–"
        return f"{_h(v):.1f}h"
    reg = tu["sources"].get("실행기록") if isinstance(tu["sources"].get("실행기록"), dict) else {}
    win = reg.get("window") if isinstance(reg.get("window"), list) and len(reg.get("window")) == 2 else None
    basis = (f"실행 횟수·포커스 시간 = 실행 기록 스냅샷 {win[0]}~{win[1]} 사이 증가분" if reg.get("basis") == "delta" and win
             else ("실행 기록 스냅샷이 1장뿐이라 횟수·시간은 이 계정의 누적값" if reg.get("basis") == "cum" else ""))
    h = ["<h3 style='font-size:14px'>프로그램 사용(참고) — 상용·비상용·자체 도구</h3>",
         f"<div class='dim'>{esc(str(tu.get('note') or TOOL_NOTE))}" + (f" · {esc(basis)}" if basis else "") + "</div>"]
    if progs:
        h.append("<table><tr><th>프로그램</th><th>구분·분류</th><th>출처</th><th>실행 횟수</th><th>포커스 시간</th>"
                 "<th>마지막 실행</th><th>파일 일수</th><th>창기록</th></tr>")
        for p in progs[:25]:
            src = p.get("src") if isinstance(p.get("src"), list) else ["창기록"]
            side = (f"{_h(p.get('hours')):.1f}h" if _h(p.get("hours")) >= 0.05 else
                    (f"배경 {_h(p.get('bg_hours')):.0f}h" if _h(p.get("bg_hours")) >= 1 else "–"))
            h.append(f"<tr><td><b>{esc(p.get('name'))}</b></td>"
                     f"<td>{esc(p.get('kind'))}{(' · ' + esc(p.get('cat'))) if p.get('cat') else ''}</td>"
                     f"<td>{esc('·'.join(str(s) for s in src))}</td><td>{esc(cnt(p.get('runs'), p.get('runs_cum')))}</td>"
                     f"<td>{esc(hrs(p.get('focus_h'), p.get('focus_h_cum')))}</td>"
                     f"<td>{esc(str(p.get('last_run') or '')[:16]) or '–'}</td>"
                     f"<td>{(str(_n(p.get('file_days'))) + '일') if _n(p.get('file_days')) else '–'}</td>"
                     f"<td>{esc(side)}</td></tr>")
        h.append("</table>")
    if inh or _n(tu.get("inhouse_hidden")):
        h.append("<div style='margin:6px 0'><b>자체·프로토타입(추정)</b> " + " · ".join(
            f"{esc(x.get('name'))}(" + (f"실행 {_n(x.get('runs'))}회" if x.get("runs") is not None
                                       else f"누적 실행 {_n(x.get('runs_cum'))}회")
            + (f" · {esc(str(x.get('last_run'))[:10])}" if x.get("last_run") else "") + ")" for x in inh[:15])
            + (f" · 이름을 가린 도구 {_n(tu.get('inhouse_hidden'))}개" if _n(tu.get("inhouse_hidden")) else "")
            + "<div class='dim'>카탈로그에 없는 실행 파일이 사용자 폴더·다른 드라이브·네트워크에서 돈 것 — "
              "무료 휴대용 도구일 수도 있다(config.programsExtra 로 이름표를 붙인다)</div></div>")
    amb = [x for x in (tu.get("ambiguous_files") or []) if isinstance(x, (list, tuple)) and len(x) >= 2]
    more = ([f"카탈로그 밖 설치 프로그램 {_n(tu.get('unknown_n'))}개(이름은 싣지 않는다)"] if _n(tu.get("unknown_n")) else [])
    if amb:
        more.append("도구 불명 파일(확장자를 여러 도구가 쓴다): " + " · ".join(f"{esc(x[0])} {_n(x[1])}개" for x in amb[:8]))
    if reg.get("track_off"):
        more.append("앱 실행 추적이 꺼져 있다(설정 &gt; 개인 정보 &gt; 일반 또는 회사 정책) — 실행 횟수가 늘지 않아 안 쓴 것처럼 보일 수 있다")
    if more:
        h.append("<div class='dim'>" + " / ".join(more) + "</div>")
    return "".join(h)


def _fmt_days(v):
    """일수 값 — {date: subject}·[date…]·숫자 모두 표시(날짜 앞 12개)"""
    if isinstance(v, dict):
        items = sorted(v.items())
        return f"{len(items)}일" + (" — " + " · ".join(
            f"{str(k)[5:]} {str(x)[:24]}" if x not in (None, True, "") else str(k)[5:] for k, x in items[:12])
            + (" …" if len(items) > 12 else "") if items else "")
    if isinstance(v, (list, tuple)):
        return f"{len(v)}일" + (" — " + " · ".join(str(x)[5:] if len(str(x)) >= 10 else str(x) for x in v[:12])
                               + (" …" if len(v) > 12 else "") if v else "")
    return f"{_n(v)}일"


# ══ LM28(WP9) 새 절 — 순수 함수(파일을 읽지 않는다 · 분석리포트 freeze.py 도 같은 함수를 쓴다) ═══════════════════
# 표기(REQ-27·W2-18): 업무 영역(Level 1) / 과제(Level 2) / 세부업무(Level 3) / 업무분류(유형 — 개발·사무·현장·협업).
FLOOR_KIND_KO = {"spans": "PC 하한(가동 구간)", "window": "PC 하한(가동 창 − 절전 공백)", "nowin": "PC 하한(창 정보 없음)",
                 "always_on": "PC 하한(늘 켜 둔 PC — 흔적 ±30분)", "trace": "흔적 창(PC 기록 없음)",
                 # LM28(E) — 브라우저 기록만 있는 날의 흔적 창 · PC 기록 없는 달의 표준일 추정(어디서나 '표준일 추정') · 날짜만 아는 발신
                 "trace_hint": "흔적 창(브라우저 사용)", "std_nopc": "표준일 추정(PC 기록 없는 달)",
                 "untimed": "시각 미상 발신"}
CUT_KO = {"lunch_h": "점심", "dinner_h": "저녁 식사", "sleep_gap_h": "절전·꺼짐 공백", "half_day": "반차",
          "day_cap_11h": "하루 상한 11h"}
TAG_KO = (("regular_h", "정규"), ("extended_h", "연장"), ("night_h", "야간(22~06)"), ("holiday_h", "휴일"),
          ("holiday_night_h", "휴일 중 야간"))
# 직접 관계 — CC·단체·수신전용(bulk)은 빼고 센다. 팀즈 웹이 날짜만 짚은 남의 글('팀즈(수신·일자)' — LM28 E)은 단체·오더가
# 한 라벨로 섞여 직접 관계를 가를 수 없어 세지 않는다(단체 채팅 상대가 동료로 부풀지 않게).
PEER_DIRECT = ("메일(수신)", "팀즈(수신)", "팀즈(오더)", "회의")
PEER_REL = {"메일(수신)": "메일", "팀즈(수신)": "팀즈", "팀즈(오더)": "의뢰(팀즈)", "회의": "회의"}
MEETING_MAX = 10                                                  # 이보다 큰 회의로만 엮인 사람은 동료가 아니다(A-37)
FLOOR_WHY = [
    "디지털 신호는 시각의 '점'이라 신호만 이으면 '3시간 작업 후 저장 1번' 이 1시간 미만이 된다. 그날 일했다는 "
    "<b>능동 증거</b>가 있을 때만, PC 가 실제로 켜져 있던 주간 구간을 근무의 바닥값(하한)으로 쓴다.",
    "창 08:00~19:00 의 근거: ① 법정 1일 근로 8시간(근로기준법 제50조 제2항) + 8시간 근로 시 휴게 1시간 이상(제54조 제1항) "
    "→ 정규 09~18(체류 9h) ② 시차출퇴근(08~10시 출근) 여유 앞뒤 1h ③ PC 가동 수집기가 08시·19시 경계로 주간·야간을 나눠 "
    "적산하므로 같은 경계를 써야 주간·야간 숫자가 맞는다(LM20·LM24 와 같은 값 — 팀 비교 연속성).",
    "열리는 조건: 그날 능동 흔적(산출물 저장·발신·수락한 회의·창 샘플러·종일 행사·수동 기록)이 있어야 열린다. 수신·CC 만 "
    "있는 날은 닫힌다(단 수동 흔적 8통 이상이 3시간 이상에 걸치면 연다 — mm.passiveFloorMinN·passiveFloorMinH).",
    "깎는 것: PC 꺼짐·절전 공백, 흔적 없는 점심 12~13시, 야근일 흔적 없는 저녁 식사, 반차(표준일 × 0.5 상한), 하루 상한 11h. "
    "창 샘플러가 덮은 시간은 하한 대신 실측을 쓴다.",
    "퇴근 후: 퇴근 경계(PC 하한 창 끝, 기본 19:00 — 그 뒤 PC 를 켰으면 켠 시각)부터 마지막 저녁 산출물 시각까지 전체를 "
    "인정한다(+30분 꼬리 없음). PC 밖 발신은 발신 세션만 인정하고 따로 센다.",
    "한계와 선택: PC 를 08~19 켜 두고 흔적이 하나라도 있으면 최대 10h 가 잡힐 수 있다(정규 09~18 근무자의 08~09·18~19 포함). "
    "정규 시간만 바닥으로 쓰려면 mm.pcFloorWindow=[9,18](퇴근 경계도 18:00 이 됨). 이 보고서에 쓴 값은 아래 '산식 설정' 에 남는다.",
]
# ── LM30(2026-10-18) 출퇴근 추정 — 투입 MM 을 맡았으면 꼬리표·초과근무 줄은 그 값이고, LM29 의 PC 하한·저녁 인정 줄은 비교용 근거다 ──
LM29_TAG = "LM29 방식(비교용) 근거"
ATT_TAG_KO = {"night_h": "야간(22~06 — 위 시간과 겹쳐 셈)", "holiday_night_h": "휴일 중 야간(겹쳐 셈)"}
LM29_ONLY = ("pc_floor_h", "pc_floor_days", "lunch_deducted_h", "evening_credit_h", "weekend_window_h",
             "floor_blocked_passive_days", "dinner_deducted_h", "flex_edge_h", "sampler_bridge_h", "trace_window_days",
             "trace_window_h", "pc_record_missing_days", "passive_capped_days", "weekend_pc_days", "sim_night")
ATT_LABEL = {"overtime_h": "초과근무(h — 연장 + 휴일, 출퇴근 추정)", "night_days": "20시 넘어 퇴근한 날(일)",
             "weekend_days": "주말·휴일 근무(일)", "absent_worked_h": "휴가일 근무(h)"}
ATT_DOW = "월화수목금토일"
# LM30v1(2026-10-19) 법정 채움 MM 이면 휴가·부재 추정은 가용에서 빼지 않고 법정 시간으로 채운다 — 8절 줄 이름
LEGAL_LABEL = {"absence_days": "달력 휴가(일 — 가용에서 빼지 않고 법정 시간으로 채움)",
               "inferred_absence_days": "휴가 추정(일 — 근태 행이 없는 PC·흔적 없는 평일, mm.creditInferredLeave 면 채움)"}


def att_used(meta, b):
    """출퇴근 추정이 투입 MM 을 맡았나 — mm_basis.attendance.used_for_mm 또는 measure.method == '출퇴근 추정'."""
    a = _obj(_pick(meta, b, "attendance")) or {}
    if a.get("used_for_mm"):
        return True
    ms = _obj(_pick(meta, b, "measure")) or {}
    return ms.get("method") == "출퇴근 추정"


def legal_local(att):
    """attendance 파일(이 PC 전용)의 법정 채움 나눔(agg["legal"] — 달마다 근태 기록 시간·+@·표시 날짜) | None"""
    agg = att.get("agg") if isinstance(att, dict) and isinstance(att.get("agg"), dict) else {}
    lg = agg.get("legal")
    return lg if isinstance(lg, dict) else None


def legal_section(meta, b, local=None, head="<h2>1. 월별 로드</h2>"):
    r"""LM30v1(2026-10-19) 법정 채움 MM 표(순수 함수 — 리포트 1절·분석리포트 공용) → HTML 조각 목록(법정 채움 결과가 아니면 []).
      달마다 1MM 기준(평일 N일 × 8시간) · 법정 채움(공휴일·유급휴가·휴가 추정) · 근무(근태 기록 + 디지털 +@ · 기록 없는 날 측정) ·
      투입 MM · 가용 MM · 로드율 · LM30 방식 MM(비교) + 규칙 한 문장.
      local = attendance 파일의 agg["legal"](legal_local — 근태 기록 시간·+@ 나눔과 '휴가 추정'·'근태·흔적 모두 없음' 날짜). 이 PC 의
      리포트에서만 준다 — 공유폴더로 복사되는 분석리포트는 local=None 이라 달 합계만 담는다."""
    import attendance as _at
    if _at.mm_rule_of(meta) != "legal":
        return []
    mo = sorted((k, v) for k, v in (meta.get("mm_months") or {}).items() if isinstance(v, dict))
    if not mo:
        return []
    cu = _obj(_pick(meta, b, "cfg_used")) or {}
    std = _at._std(cu.get("standardDayHours"))
    lm = local.get("months") if isinstance(local, dict) and isinstance(local.get("months"), dict) else {}

    def h1(v):
        return f"{_h(v):.1f}h"

    def dd(v):
        return f"{round(_h(v), 2):g}일"
    h = [head, f"<div><b>{esc(_at.legal_rule_text(std))}</b></div>",
         "<table><tr><th>월</th><th>1MM 기준</th><th>법정 채움</th><th>근무</th><th>투입 MM</th><th>가용 MM</th><th>로드율</th>"
         "<th>LM30 방식 MM(비교)</th></tr>"]
    for k, v in mo:
        L = lm.get(k) if isinstance(lm.get(k), dict) else None
        work = f"기록 없는 날 측정 {h1(v.get('measured_h'))}"
        if L is not None:
            work = f"근태 기록 {h1(L.get('hr_h'))} + 디지털 +@ {h1(L.get('plus_h'))} · " + work
            if _h(L.get("credit_work_h")) >= 0.05:
                work += f" · 그중 공휴일·휴가인 날 근무 {h1(L.get('credit_work_h'))}"
        l30 = v.get("mm_lm30")
        h.append(f"<tr><td>{esc(k)}</td><td>평일 {_n(v.get('workdays'))}일 × {std:g}시간 = {h1(v.get('capacity_h'))}</td>"
                 f"<td><b>{h1(v.get('legal_h'))}</b> <span class='dim'>공휴일 {dd(v.get('holiday_days'))} · 유급휴가 "
                 f"{dd(v.get('leave_days'))} · 휴가 추정 {dd(v.get('inferred_leave_days'))}</span></td>"
                 f"<td><b>{h1(v.get('actual_h'))}</b> <span class='dim'>{esc(work)}</span></td>"
                 f"<td><b>{_h(v.get('mm')):.2f}</b></td><td>{_h(v.get('avail_mm')):.2f}</td>"
                 f"<td><b>{'–' if v.get('load_pct') is None else str(v['load_pct']) + '%'}</b></td>"
                 f"<td>{'–' if l30 is None else format(_h(l30), '.2f') + ' (' + format(_h(v.get('mm')) - _h(l30), '+.2f') + ')'}</td></tr>")
    h.append("</table>")
    t30 = meta.get("mm_lm30")
    h.append("<div class='dim'>투입 MM = (근무 + 법정 채움) ÷ 1MM · 가용 MM = 지난 평일의 비율 · 로드율 = 투입 ÷ 가용"
             + (f" — LM30 방식이었다면 {_h(t30):.2f} MM(차이 {_h(meta.get('total_mm')) - _h(t30):+.2f} MM)" if t30 is not None else "")
             + " · 평일이라는 이유만으로는 채우지 않습니다</div>")
    if cu.get("creditInferredLeave") is False:
        h.append("<div class='dim'>휴가 추정(기록 없음)은 채우지 않습니다(설정 mm.creditInferredLeave false).</div>")
    if local is not None:
        fl = local.get("flags") if isinstance(local.get("flags"), dict) else {}
        for key in ("inferred", "nohr"):
            t = _at.legal_flag_text(fl, key)
            if t:
                h.append(f"<div class='dim'><b>{esc(t)}</b></div>")
        h.append("<div class='dim'>투입 MM(달 합계)에는 근태 기록 시간이 들어가 팀 서버로 갑니다. 날짜별 근태 기록, "
                 "'근태 기록·디지털 +@' 나눔과 위 날짜 목록은 이 리포트와 대시보드에만 있습니다.</div>")
    else:
        h.append("<div class='dim'>근태 기록 시간과 디지털 +@의 나눔·날짜 목록은 본인 PC의 대시보드·리포트에서만 보입니다 — "
                 "여기에는 달 합계만 담았습니다.</div>")
    return h


def attendance_section(meta, b, att=None, per_day=True, max_days=31, max_weeks=26):
    r"""8절 '출퇴근·시간외 근무'(LM30 2026-10-18 — 순수 함수 · 분석리포트 freeze.py 도 같은 함수) → HTML 조각 목록(출퇴근 추정이 없으면 []).
      meta·b = mm_meta·mm_basis — 달·주·전체 합계·근태 기록 비교 합계(시각 없음) · att = report\attendance_<기간>.json(이 PC 전용 —
      날짜별 출근·퇴근·평소 시각). per_day=False(공유폴더로 복사되는 분석리포트)면 att 를 쓰지 않는다 — 날짜별 표·평소 시각이 없다.
    담는 것: 결론 한 줄(가장 최근 달) · 재는 법 · 달 합계 표 · 주 합계 표(최근 max_weeks 주) · 평소 출근·퇴근 · 날짜별 표(최근 max_days 일) ·
    근태 기록 비교 · 무엇이 이 PC 에만 있나. 문구는 core\attendance(화면 카드와 같은 함수).
    LM30(2026-10-19) +@ — 맨 위 +@ 줄 · 설명 줄 · 달·주 표의 +@ 칸 · 날짜별 표의 근태 출근·퇴근·입실·퇴실·+@·까닭. 근태 기록과 견준
    값(attendance 파일 agg 의 근태 칸 — attendance.hr_view)은 per_day 일 때만(이 PC 리포트). 합계는 늘 근태 칸을 뺀 사본(strip_hr)이고,
    per_day=False 면 +@ 는 근태 없이 추정한 값·근태 기록 비교 줄은 '본인 PC 에서만'(attendance.FROZEN_REC_TEXT)이다."""
    import copy

    import attendance as _at
    from datetime import date, timedelta
    att = att if (per_day and isinstance(att, dict)) else {}
    agg = copy.deepcopy(_obj(_pick(meta, b, "attendance")) or _obj(att.get("agg")) or {})
    _at.strip_hr(agg)                                   # 근태 칸은 hr 로만(옛 mm_meta 에 남은 것도 뺀다)
    hr = _at.hr_view(att.get("agg")) if per_day and att else None
    months = agg.get("months") if isinstance(agg.get("months"), dict) else {}
    weeks = agg.get("weeks") if isinstance(agg.get("weeks"), dict) else {}
    if not months:
        return []
    cu = _obj(_pick(meta, b, "cfg_used")) or {}
    p = cu.get("attendance") if isinstance(cu.get("attendance"), dict) else {}
    wk_h = _h(p.get("weekHours")) or float(_at.DEFAULTS["weekHours"])
    per = meta.get("period") if isinstance(meta.get("period"), list) else []
    d1 = str(per[-1])[:10] if per else ""
    std = cu.get("standardDayHours")
    h_mo = (hr or {}).get("months") or {}
    h_wk = (hr or {}).get("weeks") or {}

    def h1(v):
        return f"{_h(v):.1f}h"

    def plus_td(v, hv):
        """+@ 칸 — 근태와 견준 칸이 있으면 합(굵게), 없으면 추정"""
        if isinstance(hv, dict) and "plus_all_h" in hv:
            return f"<td><b>{h1(hv.get('plus_all_h'))}</b></td>"
        return f"<td>{h1(_at.est_of(v))}</td>"
    h = ["<h3 style='font-size:14px;margin:18px 0 4px'>출퇴근·시간외 근무</h3>",
         f"<div><b>{esc(_at.plus_line(agg, hr, d1, None, std))}</b></div>",
         f"<div><b>{esc(_at.headline(agg, d1))}</b> — "
         + ("이 근무시간으로 투입 MM을 쟀습니다." if agg.get("used_for_mm")
            else "투입 MM은 LM29 방식으로 쟀습니다(이 절은 참고 — 설정 attendance.useForMM).") + "</div>",
         f"<div class='dim'>{esc(_at.plus_note(std, _at.mm_rule_of(meta)))}</div>",
         f"<div class='dim'>{esc(_at.rule_text(p or None, cu.get('standardDayHours'), cu.get('nightWindow')))}</div>"]
    plus_th = "<th>+@</th>" if hr else "<th>+@(추정)</th>"
    h.append("<table><tr><th>월</th><th>근무</th><th>정규</th><th>연장</th><th>야간</th><th>휴일</th><th>PC 밖</th>"
             "<th>LM29 방식</th><th>근무일</th><th>20시 넘은 퇴근</th><th>휴가일 근무</th><th>52시간 넘은 주</th>"
             + plus_th + "</tr>")
    tot = agg.get("total") if isinstance(agg.get("total"), dict) else {}
    for lab, v in [(mk, months[mk]) for mk in sorted(months)] + ([("합계", tot)] if tot else []):
        v = v if isinstance(v, dict) else {}
        b0, b1 = ("<b>", "</b>") if lab == "합계" else ("", "")
        hv = (hr or {}).get("total") if lab == "합계" else h_mo.get(lab)
        h.append(f"<tr><td>{b0}{esc(lab)}{b1}</td><td><b>{h1(v.get('work_h'))}</b></td><td>{h1(v.get('regular_h'))}</td>"
                 f"<td>{h1(v.get('ext_h'))}</td><td>{h1(v.get('night_h'))}</td><td>{h1(v.get('holiday_h'))}</td>"
                 f"<td>{h1(v.get('offpc_h'))}</td><td>{h1(v.get('lm29_h'))}</td><td>{_n(v.get('days'))}일</td>"
                 f"<td>{_n(v.get('late_days'))}일</td><td>{_n(v.get('leave_work_days'))}일</td>"
                 f"<td>{_n(v.get('over52_weeks'))}주</td>" + plus_td(v, hv) + "</tr>")
    h.append("</table>")
    if hr:
        ht = hr.get("total") if isinstance(hr.get("total"), dict) else {}
        h.append(f"<div class='dim'>+@ 나눔(분석 기간 전체) — 근태 기록과 견준 것 {h1(ht.get('plus_h'))} · 기록 없이 추정한 것 "
                 f"{h1(ht.get('plus_est_h'))} · 그중 PC 밖 {h1(_h(ht.get('plus_offpc_h')) + _h(ht.get('plus_est_offpc_h')))} · "
                 f"근태 시간 중 PC 흔적 없는 시간 {h1(ht.get('missing_h'))}(참고) · 입실·퇴실로 본 근태 밖 체류 "
                 f"{h1(ht.get('gate_plus_h'))}(참고)</div>")
    wk = sorted(((k, v) for k, v in weeks.items() if isinstance(v, dict)), reverse=True)[:max_weeks]
    if wk:
        h.append(f"<div class='dim'>주 합계(월~일) — 최근 {len(wk)}주"
                 + (f"(전체 {len(weeks)}주 중)" if len(weeks) > len(wk) else "")
                 + f" · {wk_h:g}시간 초과 = 그 주 근무에서 {wk_h:g}시간을 넘은 시간 · '일부' = 분석 기간에 걸친 주</div>")
        h.append(f"<table><tr><th>주(월~일)</th><th>근무</th><th>연장</th><th>야간</th><th>휴일</th><th>PC 밖</th>"
                 f"<th>{wk_h:g}시간 초과</th><th>52시간</th>{plus_th}</tr>")
        for k, w in wk:
            o52 = "<b style='color:#c0122f'>넘음</b>" if w.get("over52") else "–"
            h.append(f"<tr><td>{esc(str(w.get('from'))[5:])}~{esc(str(w.get('to'))[5:])}"
                     + (" <span class='dim'>일부</span>" if w.get("partial") else "") + "</td>"
                     f"<td><b>{h1(w.get('work_h'))}</b></td><td>{h1(w.get('ext_h'))}</td><td>{h1(w.get('night_h'))}</td>"
                     f"<td>{h1(w.get('holiday_h'))}</td><td>{h1(w.get('offpc_h'))}</td>"
                     f"<td>{h1(w.get('over40_h')) if _h(w.get('over40_h')) > 0 else '–'}</td><td>{o52}</td>"
                     + plus_td(w, h_wk.get(k)) + "</tr>")
        h.append("</table>")
    days = att.get("days") if isinstance(att.get("days"), dict) else {}
    if per_day and att:
        h.append(f"<div class='dim'>{esc(_at.usual_text(att.get('usual')))}</div>")
    try:
        end = date.fromisoformat(d1 or str(max(days))[:10]) if days else None
    except ValueError:
        end = None
    if per_day and days and end is not None:
        lo = (end - timedelta(days=max_days - 1)).isoformat()
        rows = [(k, days[k]) for k in sorted(days, reverse=True)
                if isinstance(days[k], dict) and lo <= str(k)[:10] <= end.isoformat()]
        h.append(f"<div class='dim'>날짜별 출근·퇴근 — 최근 {max_days}일({len(rows)}일 · 최신순) · 근거 = 출근 쪽 → 퇴근 쪽 · "
                 "+@ = 근태 기록 밖 근무(근태 기록이 없는 날은 추정)</div>"
                 "<table><tr><th>날짜(요일)</th><th>출근</th><th>퇴근</th><th>근무</th><th>연장</th><th>야간</th><th>휴일</th>"
                 "<th>PC 밖</th><th>LM29 방식</th><th>근거</th><th>확실성</th>"
                 "<th>근태 출근·퇴근</th><th>입실·퇴실</th><th>+@</th><th>+@ 까닭</th></tr>")
        for k, r in rows:
            try:
                dow = ATT_DOW[date.fromisoformat(str(k)[:10]).weekday()]
            except ValueError:
                dow = ""
            lv = (("다음 날 " if _n(r.get("leave_day")) > 0 else "") + str(r.get("leave"))) if r.get("leave") else "–"
            rc = r.get("rec") if isinstance(r.get("rec"), dict) else None
            pl = _at.day_plus(r, std)
            pv = (f"<b>{h1(pl['h'])}</b>" + (" <span class='dim'>추정</span>" if pl["est"] else "")) if pl["h"] > 0 else "–"
            h.append(f"<tr><td>{esc(str(k)[5:10])}({dow})</td><td>{esc(r.get('arrive') or '–')}</td><td>{esc(lv)}</td>"
                     f"<td><b>{h1(r.get('work_h'))}</b></td><td>{h1(r.get('ext_h'))}</td><td>{h1(r.get('night_h'))}</td>"
                     f"<td>{h1(r.get('holiday_h'))}</td><td>{h1(r.get('offpc_h'))}</td><td>{h1(r.get('lm29_h'))}</td>"
                     f"<td class='dim'>{esc(_at.day_why(r, p or None))}</td>"
                     f"<td>{esc(_at.CONF_KO.get(r.get('conf'), '–'))}</td>"
                     f"<td>{esc(_rec_span(rc))}</td><td>{esc(_gate_span(rc))}</td><td>{pv}</td>"
                     f"<td class='dim'>{esc(pl['why'])}</td></tr>")
        h.append("</table>")
    h.append(f"<div class='dim'><b>근태 기록 비교</b> — "
             f"{esc(_at.records_text((hr or {}).get('records')) if per_day else _at.FROZEN_REC_TEXT)}</div>")
    h.append("<div class='dim'>" + ("날짜별 출근·퇴근 추정 시각과 근태 기록(GERP 포함)에서 나온 값은 이 PC의 이 리포트와 대시보드에만 "
                                    "있습니다 — 팀 서버와 공유폴더로 복사되는 보고서에는 근태 기록 없이 잰 주·달 합계 시간만 갑니다."
                                    if per_day else
                                    "날짜별 출근·퇴근 시각과 근태 기록은 본인 PC의 대시보드·리포트에서만 보입니다 — 이 분석리포트에는 "
                                    "주·달 합계만 담았습니다.") + "</div>")
    return h


def _rec_span(rc):
    """날짜별 행의 rec → '근태 출근·퇴근' 칸 글(LM30 2026-10-19 — 이 PC 리포트만)"""
    if not isinstance(rc, dict):
        return "–"
    if rc.get("in") and rc.get("out"):
        return f"{rc['in']}~" + ("다음 날 " if _n(rc.get("out_day")) > 0 else "") + str(rc["out"])
    if _h(rc.get("leave")) >= 1:
        return "휴가"
    return "기록 없음" if rc.get("missing") else "시각 없음"


def _gate_span(rc):
    """날짜별 행의 rec → '입실·퇴실' 칸 글(태깅 — 참고)"""
    if not isinstance(rc, dict) or not (rc.get("gate_in") or rc.get("gate_out")):
        return "–"
    return (f"{rc.get('gate_in') or '?'}~" + ("다음 날 " if _n(rc.get("gate_out_day")) > 0 else "")
            + str(rc.get("gate_out") or "?"))


def day_method(db):
    """day_basis[날짜] → 그날 어느 방식으로 셌나(종일 행사·수동 기록·흔적 창·PC 하한·표준일 추정·시각 미상 발신·
    샘플러/흔적 실측). 0h 날(LM28 E — 0h 평일도 day_basis 에 남는다)은 흔적 없음(PC 기록도 없으면 기록 없음)."""
    db = db if isinstance(db, dict) else {}
    if db.get("offsite"):
        return "종일 행사"
    if db.get("manual"):
        return "수동 기록"
    fl = db.get("floor") if isinstance(db.get("floor"), dict) else None
    if fl:
        m = FLOOR_KIND_KO.get(str(fl.get("kind") or ""), "PC 하한")
        return m + (" · 표준일 추정" if fl.get("est") and "표준일 추정" not in m else "")
    if _h(db.get("h")) <= 0:
        pc = db.get("pc") if isinstance(db.get("pc"), dict) else {}
        return "기록 없음" if str(pc.get("rec") or "") == "none" else "흔적 없음"
    return "샘플러·흔적 실측"


def after_text(db, edge="19:00"):
    """'퇴근 후·시각' 칸(LM28 E) — 퇴근 경계 뒤 PC 가동·내 흔적·받은 흔적·인정한 창·빠진 이유(ev) · 날짜만 아는 발신(untimed) ·
    AI 비업무 발신 시간 유지(ai_n_kept) · PC 기록 종류(브라우저 기록만·항상 켜짐) · 부재. edge = 퇴근 경계(하한 창 끝)."""
    db = db if isinstance(db, dict) else {}
    bits = []
    ev = db.get("ev") if isinstance(db.get("ev"), dict) else {}
    why = str(ev.get("why") or "")
    if why == "no_active_after":
        bits.append(f"PC {edge} 이후 {_h(ev.get('pc_after_h')):.1f}h · 내 흔적 0 · 받은 {_n(ev.get('pas_after'))} → 미인정")
    elif why == "credited":
        bits.append(f"퇴근 후 {_h(ev.get('credit_h')):.1f}h 인정")
    elif why == "capped":
        bits.append(f"PC 야간 가동 한도로 일부만 인정 {_h(ev.get('credit_h')):.1f}h")
    elif why == "no_pc_after":
        bits.append(f"내 흔적 {_n(ev.get('act_after'))}건 · 퇴근 후 PC 기록 없음(발신 세션만)")
    un = db.get("untimed") if isinstance(db.get("untimed"), dict) else {}
    if _n(un.get("n")):
        cm = _n(un.get("credit_min"))
        bits.append(f"날짜만 아는 발신 {_n(un.get('n'))}통" + (f"({cm}분 인정)" if cm else "(하한에 포함)"))
    if _n(db.get("ai_n_kept")):
        bits.append(f"AI 비업무 발신 {_n(db.get('ai_n_kept'))}건 시간 유지")
    pc = db.get("pc") if isinstance(db.get("pc"), dict) else {}
    if str(pc.get("rec") or "") == "hint":
        bits.append("브라우저 기록만")
    if pc.get("always_on"):
        bits.append("PC 항상 켜짐")
    ab = _h(db.get("absent"))
    if ab > 0:
        bits.append("부재 종일" if ab >= 1 else f"부재 {ab:g}일")
    return " · ".join(bits)


def time_basis_line(meta, b):
    """LM28(E) 시간 근거 합계 한 줄 — 퇴근 후 미인정·시각 미상 발신·표준일 추정(PC 기록 없는 달)·브라우저 기록만 있는 평일·
    AI 비업무 발신 시간 유지(값이 있는 것만, 없으면 ""). mine 요약 줄·대시보드 MM 카드와 같은 숫자(mm_basis 키 — 재산정 뒤에는
    judge 가 바꾼 mm_basis · ai_n_time_kept 는 mm_meta 최상위에도 있다)."""
    bits = []
    if _n(_pick(meta, b, "evening_missed_days")):
        bits.append(f"퇴근 후 미인정 {_n(_pick(meta, b, 'evening_missed_days'))}일·PC "
                    f"{_h(_pick(meta, b, 'evening_missed_pc_h')):.1f}h(퇴근 뒤 PC 는 켜져 있었는데 내 흔적 없음)")
    if _n(_pick(meta, b, "untimed_sends")):
        bits.append(f"시각 미상 발신 {_n(_pick(meta, b, 'untimed_sends'))}통"
                    f"({_h(_pick(meta, b, 'untimed_credit_h')):.1f}h 인정)")
    if _n(_pick(meta, b, "std_nopc_days")):
        bits.append(f"표준일 추정 {_n(_pick(meta, b, 'std_nopc_days'))}일"
                    f"(+{_h(_pick(meta, b, 'std_nopc_h')):.1f}h — PC 기록 없는 달)")
    if _n(_pick(meta, b, "hint_only_days")):
        bits.append(f"브라우저 기록만 있는 평일 {_n(_pick(meta, b, 'hint_only_days'))}일")
    if _n(_pick(meta, b, "ai_n_time_kept")):
        bits.append(f"AI 비업무 발신 시간 유지 {_n(_pick(meta, b, 'ai_n_time_kept'))}건")
    return " · ".join(bits)


def floor_day_rows(day_basis, limit=None, edge="19:00", lm29=False):
    """day_basis → [{date, h, method, open, add_h, cut, tags, extra, after}] **최신순**(LM28 E — 0h 평일·흔적 있는 휴일 포함 ·
    after = '퇴근 후·시각' 칸). limit 이면 최근 limit 일만.
    LM30(2026-10-18): lm29=True(출퇴근 추정이 투입을 맡은 결과)면 이 표는 'LM29 방식(비교용) 근거' 다 — h 는 LM29 방식 시간(lm29_h)이고
    꼬리표 칸은 비운다(날짜별 꼬리표가 출퇴근 추정 값으로 바뀌었다). 출퇴근 추정 시간은 그 밖 칸에 적는다."""
    out = []
    for d in sorted(((day_basis or {}) if isinstance(day_basis, dict) else {}), reverse=True):
        db = day_basis[d] if isinstance(day_basis[d], dict) else {}
        att = db.get("att") if isinstance(db.get("att"), dict) else {}
        l29v = bool(lm29 and att and db.get("lm29_h") is not None)
        if l29v:
            db = dict(db, h=db.get("lm29_h"))
        fl = db.get("floor") if isinstance(db.get("floor"), dict) else {}
        cut = fl.get("cut") if isinstance(fl.get("cut"), dict) else {}
        cut_s = " · ".join(f"{CUT_KO.get(k, k)} {_h(v):.2f}h" if k != "half_day" else f"반차 {_h(v):.1f}일"
                           for k, v in cut.items() if v)
        tags = db.get("tags") if isinstance(db.get("tags"), dict) and not l29v else {}
        tag_s = " · ".join(f"{lab} {_h(tags.get(k[:-2])):.1f}h" for k, lab in TAG_KO if _h(tags.get(k[:-2])) > 0)
        extra = []
        if db.get("evening"):
            extra.append("저녁 " + ", ".join("~".join(str(x) for x in w) for w in db["evening"] if isinstance(w, list)))
        elif _h(db.get("evening_h")) > 0:
            # LM30(2026-10-18) — mm_meta 에는 저녁 창의 시각 대신 길이만 남는다(날짜별 시각은 이 PC 의 attendance 파일에만)
            extra.append(f"저녁 {_h(db.get('evening_h')):.1f}h")
        conf_ko = ({'high': '높음', 'mid': '보통', 'low': '낮음'}).get(att.get('conf'), '–') if att else ""
        if l29v:
            extra.append(f"출퇴근 추정 {_h(att.get('work')):.2f}h(신뢰도 {conf_ko})")
        elif att:
            extra.append(f"출퇴근 추정 신뢰도 {conf_ko}"
                         + (f" · LM29 방식 {_h(db.get('lm29_h')):.2f}h" if db.get("lm29_h") is not None else ""))
        if db.get("remote_send"):
            extra.append(f"PC 밖 발신 {_n(db.get('remote_send'))}통")
        if db.get("private_min"):
            extra.append(f"사적 차감 {_n(db.get('private_min'))}분")
        out.append({"date": d, "h": _h(db.get("h")), "method": day_method(db),
                    "open": ", ".join(str(x) for x in (fl.get("open") or [])),
                    "add_h": _h(fl.get("add_h")), "cut": cut_s, "tags": tag_s, "extra": " · ".join(extra),
                    "after": after_text(db, edge)})
    return out[:limit] if limit else out


def floor_section(meta, b, max_rows=62):
    """'산출 방식 — PC 가동 하한의 근거' 절(★ 사용자 지시 2026-10-07 ②) → HTML 조각 목록.
    LM28(E): 날짜표는 최신순(최근 max_rows 일)이고 0h 평일도 들어간다 · '퇴근 후·시각' 열 · 표 위에 시간 근거 합계 한 줄.
    LM30(2026-10-18): 출퇴근 추정이 투입을 맡았으면(att_used) 이 절은 'LM29 방식(비교용) 근거' 다 — 제목·합계 줄·표 머리를 그렇게 적고
    날짜표의 시간은 LM29 방식 시간이다(floor_day_rows lm29=True)."""
    cu = b.get("cfg_used") if isinstance(b.get("cfg_used"), dict) else (meta.get("cfg_used") or {})
    cu = cu if isinstance(cu, dict) else {}
    a_on = att_used(meta, b)
    win = cu.get("pcFloorWindow")
    win_s = "~".join(str(x) for x in win) if isinstance(win, (list, tuple)) else "08:00~19:00"
    edge = str(win[1]) if isinstance(win, (list, tuple)) and len(win) == 2 and win[1] else "19:00"
    head = (f"<h2>{LM29_TAG} — PC 가동 하한</h2><div class='dim'>투입 MM은 출퇴근 추정으로 쟀습니다(위 '출퇴근·시간외 근무'). "
            "아래는 LM29 방식으로 쟀다면의 근거로, 비교용입니다. " if a_on else
            "<h2>산출 방식 — PC 가동 하한의 근거</h2><div class='dim'>")
    h = [head + f"이 보고서의 하한 창: <b>{esc(win_s)}</b>"
         + (f" · 근거 문구: {esc(cu.get('floorBasis'))}" if cu.get("floorBasis") else "") + "</div><ul>"]
    h += [f"<li style='margin:3px 0'>{t}</li>" for t in FLOOR_WHY]
    h.append("</ul>")
    tb = time_basis_line(meta, b)
    if tb:
        h.append(f"<div class='dim'><b>시간 근거 합계{'(LM29 방식)' if a_on else ''}</b> — {esc(tb)}</div>")
    rows = floor_day_rows(b.get("day_basis") or meta.get("day_basis"), edge=edge, lm29=a_on)
    if rows:
        cnt = {}
        for r in rows:
            cnt[r["method"]] = cnt.get(r["method"], 0) + 1
        h.append("<div class='dim'>날짜별로 어느 방식으로 셌는지 — " + esc(" · ".join(f"{k} {v}일" for k, v in
                                                                         sorted(cnt.items(), key=lambda x: -x[1])))
                 + (f" (최근 {max_rows}일만 표시 · 전체는 mm_meta 의 mm_basis.day_basis)" if len(rows) > max_rows else "")
                 + "</div>")
        h.append(f"<table><tr><th>날짜</th><th>{'LM29 방식' if a_on else '인정'}</th><th>방식</th><th>하한을 연 흔적</th>"
                 "<th>하한이 더한 시간</th><th>깎은 것</th><th>꼬리표</th><th>퇴근 후·시각</th><th>그 밖</th></tr>")
        for r in rows[:max_rows]:
            h.append(f"<tr><td>{esc(r['date'])}</td><td>{r['h']:.2f}h</td><td>{esc(r['method'])}</td>"
                     f"<td class='dim'>{esc(r['open']) or '–'}</td>"
                     f"<td>{(format(r['add_h'], '.2f') + 'h') if r['add_h'] else '–'}</td>"
                     f"<td class='dim'>{esc(r['cut']) or '–'}</td><td class='dim'>{esc(r['tags'])}</td>"
                     f"<td class='dim'>{esc(r['after']) or '–'}</td>"
                     f"<td class='dim'>{esc(r['extra'])}</td></tr>")
        h.append("</table>")
    return h


def overtime_rows(meta, b):
    """8절 초과근무 세분(A-22) — [(라벨, 값 문자열)]. 값이 없는 키는 뺀다.
    LM30(2026-10-18): 출퇴근 추정이 투입을 맡았으면(att_used) 꼬리표 줄은 출퇴근 추정 값(야간은 겹쳐 셈)이고, LM29 에만 있는 줄
    (퇴근 후 인정 창·사적 차감·PC 밖 발신 통수·야간 해석 CPU)은 'LM29 방식(비교용) 근거' 로 적는다."""
    a_on = att_used(meta, b)
    pre = f"{LM29_TAG} — " if a_on else ""
    out = []
    for k, lab in TAG_KO:
        v = _pick(meta, b, k)
        if v is not None:
            out.append((f"출퇴근 추정 — {ATT_TAG_KO.get(k, lab)}(h)" if a_on else f"근무 꼬리표 — {lab}(h)",
                        f"{_h(v):.1f}h"))
    for k, lab in (("evening_window_h", "퇴근 후 인정 창(h)"), ("private_deducted_h", "사적 차감(h — 샘플러 연속 실측만)")):
        v = _pick(meta, b, k)
        if v is not None:
            out.append((pre + lab, f"{_h(v):.1f}h"))
    rs = _pick(meta, b, "remote_send")
    if rs:
        out.append((pre + "PC 밖 발신(통)", f"{_n(rs)}통"))
    if _pick(meta, b, "sim_night_cpu_denied"):
        out.append((pre + "야간 해석 CPU 미확인(인정 안 함, 일)", f"{_n(_pick(meta, b, 'sim_night_cpu_denied'))}일"))
    un = _pick(meta, b, "unobserved_days")
    if un is not None:
        out.append(("미관측 평일(원장 — 근거 없음, 0h 로 세지 않음)", _fmt_days(un)))
    ev = _pick(meta, b, "evidence_none_observed")
    if ev is not None:
        out.append(("관측했는데 흔적 없는 평일", _fmt_days(ev)))
    bl = _pick(meta, b, "inferred_absence_blocked_unobserved")
    if bl is not None:
        out.append(("미관측이라 부재 추정 안 함(일)", _fmt_days(bl)))
    return out


def _flags(r):
    return {x.strip() for x in str(r.get("flag") or "").replace(";", ",").split(",") if x.strip()}


def _attendees(r):
    for k in ("attendees", "n_attendees", "rcpt_n", "recipients_n"):
        try:
            if str(r.get(k) or "").strip():
                return int(float(r.get(k)))
        except (TypeError, ValueError):
            continue
    return 0


def peers(sig_rows, summary=False, ctx=None, top=20):
    r"""같이 일한 동료(A-37·W2-10) — 판정 신호(signals) 행에서 직접 관계(메일 수신·팀즈·팀즈 오더·회의)만 센다.
    빼는 것: 본인·빈 이름, CC·단체 발송·수신전용(bulk)으로만 엮인 사람, 10명 넘는 회의로만 엮인 사람, 광고 의심(flag ad)·
    사적(flag priv) 행. 외부인은 사람이 아니라 도메인 계급(고객사·협력사·외부)으로 묶는다(core\privacy.who_class).
    summary=True(요약판)면 사내 사람 이름을 [사람] 으로 가린다. 정렬: 함께한 가중치 ↓ → 함께한 과제 수 ↓ → 키, 상위 top.
    → [{key, kind(사람|계급), rel{관계: 횟수}, n, w, projects[상위 3], first, last}]"""
    try:
        import privacy as _pv          # core\ — 실패해도 동료 절은 사내/외부를 '(외부)' 표기로만 가른다
    except Exception:  # noqa: BLE001
        _pv = None
    agg = {}
    for r in sig_rows or []:
        src = str(r.get("source") or "")
        who = str(r.get("who") or "").strip()
        if not who or who in ("나", "[나]") or src not in PEER_DIRECT:
            continue
        fl = _flags(r)
        if "ad" in fl or "priv" in fl or "private" in fl:
            continue
        if src == "회의" and _attendees(r) > MEETING_MAX:
            continue
        cls = ""
        try:
            cls = _pv.who_class(who, ctx) if _pv else ("외부" if "(외부)" in who else "사내")
        except Exception:  # noqa: BLE001
            cls = "사내"
        key, kind = (who, "사람") if cls in ("사내", "") else (cls, "계급")
        a = agg.setdefault(key, {"key": key, "kind": kind, "rel": {}, "n": 0, "w": 0.0, "pj": {}, "first": "",
                                 "last": ""})
        rel = PEER_REL.get(src, src)
        a["rel"][rel] = a["rel"].get(rel, 0) + 1
        a["n"] += 1
        a["w"] += _h(r.get("weight"))
        pj = str(r.get("model") or r.get("project") or "").strip()
        if pj:
            a["pj"][pj] = a["pj"].get(pj, 0) + 1
        t = str(r.get("time") or "")[:10]
        if t:
            a["first"] = min(a["first"] or t, t)
            a["last"] = max(a["last"], t)
    out = sorted(agg.values(), key=lambda a: (-a["w"], -len(a["pj"]), a["key"]))[:top]
    for a in out:
        a["projects"] = [k for k, _v in sorted(a.pop("pj").items(), key=lambda kv: -kv[1])[:3]]
        a["w"] = round(a["w"], 2)
        if summary and a["kind"] == "사람":
            a["key"] = "[사람]"
    return out


def task_edges(sig_rows):
    r"""과제 → {people: 동료 집합, files: 산출물 집합} — 대시보드 상세 리뷰의 '업무 연결성' 간선(ui\app.review)과 같은 규칙:
    who 가 있고 '나' 가 아니면 사람, source 가 파일·커밋이면 산출물(본문 앞 60자). 연관 업무 표의 재료."""
    out = {}
    for r in sig_rows or []:
        pj = str(r.get("model") or r.get("project") or "").strip() or "미지정"
        e = out.setdefault(pj, {"people": set(), "files": set()})
        who = str(r.get("who") or "").strip()
        src = str(r.get("source") or "")
        if "ad" in _flags(r):
            continue
        if who and who not in ("나", "[나]") and src in PEER_DIRECT:
            e["people"].add(who)
        if src.startswith(("파일", "커밋")):
            t = str(r.get("text") or "").strip()[:60]
            if t:
                e["files"].add(t)
    return out


def _jac(a, b):
    u = len(a | b)
    return (len(a & b) / u) if u else 0.0


def related_tasks(sig_rows, top=10):
    r"""연관 업무(REQ-38·A-38 최소판) — 과제 쌍마다 공유 산출물·공유 동료의 자카드. 연관도 = 0.4·J(산출물) + 0.3·J(동료)
    (A-38 식에서 앱·선행 항은 계산하지 않는다 — 그래프 엔진 없음). 공유가 하나도 없는 쌍은 뺀다. 연관도 ↓ 상위 top.
    → [{a, b, files, people, j_files, j_people, rel}] (자카드·연관도는 소수 4자리)"""
    e = task_edges(sig_rows)
    names = sorted(e)
    out = []
    for i, a in enumerate(names):
        for b2 in names[i + 1:]:
            fa, fb, pa, pb = e[a]["files"], e[b2]["files"], e[a]["people"], e[b2]["people"]
            sf, sp = len(fa & fb), len(pa & pb)
            if not (sf or sp):
                continue
            jf, jp = _jac(fa, fb), _jac(pa, pb)
            out.append({"a": a, "b": b2, "files": sf, "people": sp, "j_files": round(jf, 4),
                        "j_people": round(jp, 4), "rel": round(0.4 * jf + 0.3 * jp, 4)})
    out.sort(key=lambda x: (-x["rel"], x["a"], x["b"]))
    return out[:top]


def workflow_summary(wf, rows=None):
    r"""업무 영역·과제 워크플로 요약(REQ-37) — workflow_<tag>.json 의 흐름을 (업무 영역, 과제)로 묶어 단계 이름별 빈도
    (그 단계를 밟는 흐름 수). 업무 영역은 흐름의 level1 → 없으면 mm_rows 의 Level 1. Copilot 추가 호출 없음.
    → [{"area", "project", "flows", "steps": [(단계, 빈도)]}] — (업무 영역, 과제) 한 쌍이 한 행."""
    l1_of = {}
    for r in rows or []:
        if isinstance(r, dict) and r.get("Level 2") and r.get("Level 1"):
            l1_of.setdefault(str(r["Level 2"]), str(r["Level 1"]))
    grp = {}
    for fl in ((wf or {}).get("flows") or []) if isinstance(wf, dict) else []:
        if not isinstance(fl, dict):
            continue
        pj = str(fl.get("project") or "").strip() or str(fl.get("model") or "").split(" / ")[0].strip() or "과제 미상"
        area = str(fl.get("level1") or "").strip() or l1_of.get(pj, "") or "영역 미분류"
        g = grp.setdefault((area, pj), {"area": area, "project": pj, "flows": 0, "steps": {}})
        g["flows"] += 1
        seen = set()
        for s in fl.get("steps") or []:
            nm = str((s or {}).get("name") or "").strip() if isinstance(s, dict) else ""
            if nm and nm not in seen:
                seen.add(nm)
                g["steps"][nm] = g["steps"].get(nm, 0) + 1
    out = []
    for g in sorted(grp.values(), key=lambda g: (g["area"], -g["flows"], g["project"])):
        g["steps"] = sorted(g["steps"].items(), key=lambda kv: (-kv[1], kv[0]))
        out.append(g)
    return out


def new_sections(sig, wf, rows, pv, summary=False, ctx=None, n0=10):
    r"""리포트·분석리포트 공용 새 절(동료·연관 업무·영역/과제 워크플로·단위업무) → HTML 조각 목록. n0 = 첫 절 번호."""
    h = []
    pe = peers(sig, summary=summary, ctx=ctx)
    h.append(f"<h2 id='peers'>{n0}. 같이 일한 동료</h2><div class='dim'>직접 관계(받은 메일·팀즈·팀즈 오더·회의)만 셉니다 — "
             "CC·단체 발송으로만 엮인 사람, 10명 넘는 회의로만 엮인 사람, 광고·사적 상대는 뺐습니다. "
             "외부인은 사람 대신 도메인 계급(고객사·협력사·외부)으로 묶었습니다"
             + (" · 요약판이라 사내 이름은 [사람] 으로 가렸습니다" if summary else "") + ". 상위 20.</div>")
    if pe:
        h.append("<table class='peers'><tr><th>동료</th><th>관계(횟수)</th><th>신호</th><th>함께한 과제(상위 3)</th>"
                 "<th>처음~마지막</th></tr>")
        for a in pe:
            h.append(f"<tr><td><b>{esc(a['key'])}</b>{' <span class=dim>(계급)</span>' if a['kind'] == '계급' else ''}</td>"
                     f"<td>{esc(' · '.join(f'{k} {v}' for k, v in sorted(a['rel'].items(), key=lambda x: -x[1])))}</td>"
                     f"<td>{a['n']}</td><td>{esc(', '.join(a['projects']))}</td>"
                     f"<td class='dim'>{esc(a['first'])} ~ {esc(a['last'])}</td></tr>")
        h.append("</table>")
    else:
        h.append("<div class='dim'>직접 관계로 엮인 동료가 없습니다(판정 신호에 받은 메일·팀즈·회의 상대가 없음).</div>")
    rt = related_tasks(sig)
    h.append(f"<h2 id='related'>{n0 + 1}. 연관 업무</h2><div class='dim'>과제 쌍마다 공유 산출물·공유 동료의 자카드 — "
             "연관도 = 0.4 × J(산출물) + 0.3 × J(동료). 상위 10. 같은 문서·같은 사람이 겹치는 과제는 함께 보거나 합칠 후보입니다.</div>")
    if rt:
        h.append("<table class='related'><tr><th>과제 A</th><th>과제 B</th><th>공유 산출물</th><th>J(산출물)</th>"
                 "<th>공유 동료</th><th>J(동료)</th><th>연관도</th></tr>")
        for x in rt:
            h.append(f"<tr><td>{esc(x['a'])}</td><td>{esc(x['b'])}</td><td>{x['files']}</td><td>{x['j_files']:.4f}</td>"
                     f"<td>{x['people']}</td><td>{x['j_people']:.4f}</td><td><b>{x['rel']:.4f}</b></td></tr>")
        h.append("</table>")
    else:
        h.append("<div class='dim'>산출물이나 동료를 공유하는 과제 쌍이 없습니다.</div>")
    ws = workflow_summary(wf, rows)
    h.append(f"<h2 id='wfsum'>{n0 + 2}. 업무 영역·과제 워크플로 요약</h2><div class='dim'>담당자 워크플로우를 업무 영역·과제로 묶어 "
             "단계 이름과 빈도(그 단계를 밟는 흐름 수)를 셉니다 — Copilot 추가 호출 없음.</div>")
    if ws:
        h.append("<table class='wfsum'><tr><th>업무 영역</th><th>과제</th><th>흐름</th><th>단계(빈도)</th></tr>")
        for g in ws:
            h.append(f"<tr><td>{esc(g['area'])}</td><td><b>{esc(g['project'])}</b></td><td>{g['flows']}</td><td>"
                     + " · ".join(f"{esc(nm)}{(' ×' + str(c)) if c > 1 else ''}" for nm, c in g["steps"][:12])
                     + ("" if len(g["steps"]) <= 12 else f" <span class='dim'>… +{len(g['steps']) - 12}</span>")
                     + "</td></tr>")
        h.append("</table>")
    else:
        h.append("<div class='dim'>워크플로우 분석이 없습니다 — 대시보드 [담당자 워크플로우] 탭에서 만들 수 있습니다.</div>")
    ep = (pv or {}).get("episodes") if isinstance(pv, dict) else None
    units = [u for u in ((ep or {}).get("units") or []) if isinstance(u, dict)] if isinstance(ep, dict) else []
    if units:
        gr = (ep or {}).get("unit_grades") or {}
        h.append("<h3 style='font-size:14px;margin:14px 0 4px'>단위업무(시작 단서 → 종료 단서)</h3>"
                 "<div class='dim'>등급: 확정(요청·보고/최종본 단서) · 근거(한쪽 단서) · 추정(휴면·정체로 끝을 추정) — "
                 + esc(" · ".join(f"{k} {v}" for k, v in gr.items())) + "</div>"
                 "<table class='units'><tr><th>과제</th><th>세부업무</th><th>시작</th><th>끝</th><th>리드(h)</th>"
                 "<th>등급</th></tr>")
        for u in units[:30]:
            h.append(f"<tr><td>{esc(u.get('model'))}</td><td>{esc(u.get('detail'))}</td>"
                     f"<td class='dim'>{esc(str(u.get('start') or '')[:16])} {esc(u.get('start_cue'))}</td>"
                     f"<td class='dim'>{esc(str(u.get('end') or '진행 중')[:16])} {esc(u.get('end_cue') or '')}</td>"
                     f"<td>{'' if u.get('lead_h') is None else esc(u.get('lead_h'))}</td><td><b>{esc(u.get('grade'))}</b></td></tr>")
        h.append("</table>")
    return h


def _privacy_ctx():
    """동료 절의 외부 계급 판정 문맥(core\\privacy.make_ctx) — 실패하면 None(기본 규칙)"""
    try:
        if os.path.join(ROOT, "core") not in sys.path:
            sys.path.insert(0, os.path.join(ROOT, "core"))
        import privacy as _pv
        cfg = _json(os.path.join(ROOT, "config", "config.json"))
        return _pv.make_ctx(cfg if isinstance(cfg, dict) else {}, os.path.join(ROOT, "data"))
    except Exception:  # noqa: BLE001
        return None


def build(tag, summary=False):
    meta = _json(os.path.join(REP, f"mm_meta_{tag}.json"))
    if not meta:
        return None
    # 오래된 정제본은 쓰지 않는다 (aggregate·flow 와 같은 규칙)
    rows = ((_rows(os.path.join(REP, f"mm_rows_{tag}_refined.csv"))
             if _fresh_refined(os.path.join(REP, f"mm_rows_{tag}.csv"),
                               os.path.join(REP, f"mm_rows_{tag}_refined.csv")) else [])
            or _rows(os.path.join(REP, f"mm_rows_{tag}.csv")))
    pv = _json(os.path.join(REP, f"pivots_{tag}.json"))
    # 월별 코멘트 — 이 기간 파일의 달 + 빠진 달은 다른 기간 파일에서(core/narratives.load_merged — judge·화면과 같은 이월 규칙,
    # 기간 밖의 달은 섞지 않는다). 예전에는 정확한 tag 파일만 읽어, 기간이 날마다 바뀌면 5절이 통째로 빠졌다(진단 C).
    try:
        import narratives as _nv
        nar = _nv.load_merged(REP, tag, months=_nv.period_months(tag)) or {}
    except Exception:  # noqa: BLE001 - 코멘트 판독 실패가 리포트를 막지 않게(예전 방식으로)
        nar = _json(os.path.join(REP, f"ai_narratives_{tag}.json"))
    ent = _json(os.path.join(REP, f"entities_{tag}.json"))
    sig = _rows(os.path.join(REP, f"signals_{tag}.csv"))
    b = meta.get("mm_basis") or {}
    period = " ~ ".join(meta.get("period") or [tag])
    inmm = meta.get("total_mm") or 0
    # LM30v1(2026-10-19) 법정 채움 MM — 1절은 legal_section(이 PC 리포트라 attendance 파일의 근태 기록 시간·+@ 나눔·표시 날짜까지)
    import attendance as _at
    legal_on = _at.mm_rule_of(meta) == "legal"
    att_doc = _json(os.path.join(REP, f"attendance_{tag}.json"))
    avmm = meta.get("avail_mm") or 0
    pct = meta.get("load_pct")
    if pct is None and avmm:
        pct = round(inmm / avmm * 100, 1)

    WT = {"개발": "#2a78d6", "사무": "#e08a00", "현장": "#0e8c7a", "협업": "#6c4fb8"}
    h = ["<!doctype html><meta charset='utf-8'><title>업무 로드 리포트</title>",
         "<style>body{font-family:'Malgun Gothic',sans-serif;max-width:960px;margin:28px auto;",
         "color:#1b1f24;line-height:1.6;padding:0 16px}h1{font-size:22px;margin-bottom:2px}",
         "h2{font-size:16px;margin:26px 0 6px;padding-bottom:4px;border-bottom:2px solid #e4e7eb}",
         "table{border-collapse:collapse;width:100%;margin:8px 0 14px;font-size:13px}",
         "th,td{border:1px solid #dde1e6;padding:5px 8px;text-align:left}th{background:#f5f7fa}",
         ".dim{color:#6b7280;font-size:12px}.kpi{display:flex;gap:26px;margin:14px 0 6px}",
         ".kpi div b{display:block;font-size:26px;line-height:1.2}",
         ".tag{display:inline-block;background:#f0f3f7;border-radius:3px;padding:1px 7px;",
         "margin:1px 3px 1px 0;font-size:11.5px}</style>",
         f"<h1>업무 로드 리포트</h1><div class='dim'>{esc(meta.get('owner') or '')} · 기간 {esc(period)}"
         f" · 신호 {esc(meta.get('signals'))}건</div>",
         "<div class='kpi'>",
         f"<div><span class='dim'>로드율</span><b>{'–' if pct is None else str(pct)+'%'}</b>{coverage_badge(meta, b)}</div>",
         f"<div><span class='dim'>투입 MM</span><b>{inmm:.2f}</b></div>",
         f"<div><span class='dim'>가용 MM</span><b>{avmm:.2f}</b></div>",
         f"<div><span class='dim'>인정 시간</span><b>{esc(meta.get('worked_h'))}h</b></div></div>",
         ("<div class='dim'>로드율 = 투입 ÷ 가용 · 1 MM = 8h × 그 달 평일 전부(공휴일 포함) · 투입 = 실제 근무(근태 기록이 있으면 그 "
          "시간 + 디지털 +@) + 공휴일·유급휴가 법정 채움 · 가용 = 지난 평일의 비율 · 상한 없이 그대로(하루 24h 물리 한계만 · "
          "이상치는 8절 표에 표시) · 인정 시간은 LM이 잰 근무(법정 채움 없음)</div>"
          if legal_on else
          "<div class='dim'>로드율 = 투입 ÷ 가용 · 1 MM = 8h × 그 달 평일수 · "
          "가용은 연차·휴가(+부재 추정)를 일자에서 뺀 값 · 투입은 상한 없이 실측 그대로"
          "(하루 24h 물리 한계만 · 이상치는 8절 표에 표시)</div>")]
    ml = measure_line(meta, b)
    if ml:
        cv = _obj(_pick(meta, b, "coverage")) or {}
        reasons = cv.get("reasons") if isinstance(cv.get("reasons"), list) else []
        h.append(f"<div class='dim'>측정 방식: {ml}"
                 + (" — " + esc(" · ".join(str(x) for x in reasons[:4])) if reasons else "")
                 + (" · <b style='color:#c0122f'>측정 불충분 — 팀 비교에서 제외되는 결과</b>"
                    if str(cv.get("grade") or "") == "unreliable" else "") + "</div>")
    if meta.get("rehours"):
        bef = meta.get("total_mm_before_rehours")
        h.append(f"<div class='dim'>비업무 제외 {_n(meta.get('dropped_n'))}건 · −{_h(meta.get('dropped_h')):.1f}h — "
                 "판정 후 시간을 다시 재어 투입 "
                 + (f"{_h(bef):.2f} → " if bef is not None else "") + f"{inmm:.2f} MM 으로 갱신"
                 "(버린 신호의 시간이 남은 행에 옮겨 붙지 않음)</div>")
    fut, tf = _pick(meta, b, "future_days"), _pick(meta, b, "today_fraction")
    if fut is not None or tf is not None:
        h.append("<div class='dim'>가용 기준: "
                 + (f"미래 평일 {_n(fut)}일은 가용에서 제외" if fut is not None else "")
                 + (" · " if (fut is not None and tf is not None) else "")
                 + (f"오늘은 {round(_h(tf) * 100)}% 만 가용(분석 시각 기준)" if tf is not None else "") + "</div>")

    mo = sorted((meta.get("mm_months") or {}).items())
    pcc = _obj(_pick(meta, b, "pc_coverage_by_month")) or {}
    # LM30(2026-10-18) — 출퇴근 추정이 투입을 맡았으면 달마다 'LM29 방식이었다면' MM(같은 분모 — mm_months.mm_lm29)을 나란히
    l29_on = any(isinstance(v, dict) and v.get("mm_lm29") is not None for _k, v in mo)
    if mo and legal_on:
        h += legal_section(meta, b, legal_local(att_doc), head="<h2>1. 월별 로드</h2>")
        if pcc:
            h.append("<div class='dim'>월별 PC 기록 — " + " · ".join(
                f"{esc(k)} {round(_h(r) * 100)}%" + (" [하한 미적용]" if _h(r) < 0.4 else "") for k, r in sorted(pcc.items()))
                + " (40% 미만인 달은 PC 하한·부재 추정이 꺼져 그 달만 낮게 나올 수 있다)</div>")
    elif mo:
        h.append("<h2>1. 월별 로드</h2><table><tr><th>월</th><th>투입 MM</th>" + ("<th>LM29 방식 MM</th>" if l29_on else "")
                 + "<th>가용 MM</th><th>로드율</th><th>투입 시간</th><th>부재</th><th>그 달 평일</th>"
                 + ("<th>PC 기록</th>" if pcc else "") + "</tr>")
        for k, v in mo:
            v = v if isinstance(v, dict) else {}
            l29_td = ""
            if l29_on:
                l29_td = f"<td>{_h(v.get('mm_lm29')):.2f}</td>" if v.get("mm_lm29") is not None else "<td class='dim'>–</td>"
            pc_td = ""
            if pcc:
                r = pcc.get(k)
                if r is None:
                    pc_td = "<td class='dim'>–</td>"
                else:
                    pc_td = (f"<td>{round(_h(r) * 100)}%"
                             + (" <b style='color:#b54708'>하한 미적용(PC 기록 없음)</b>" if _h(r) < 0.4 else "")
                             + "</td>")
            h.append(f"<tr><td>{esc(k)}</td><td><b>{_h(v.get('mm')):.2f}</b></td>{l29_td}"
                     f"<td>{_h(v.get('avail_mm')):.2f}</td>"
                     f"<td><b>{'–' if v.get('load_pct') is None else str(v['load_pct'])+'%'}</b></td>"
                     f"<td>{esc(v.get('worked'))}h</td><td>{esc(v.get('absent'))}일</td>"
                     f"<td>{esc(v.get('workdays'))}일</td>{pc_td}</tr>")
        h.append("</table>")
        if l29_on:
            t29 = meta.get("mm_lm29")
            h.append("<div class='dim'>투입 MM은 출퇴근 추정(LM30 방식)으로 쟀습니다"
                     + (f" — LM29 방식이었다면 {_h(t29):.2f} MM(차이 {_h(inmm) - _h(t29):+.2f} MM)" if t29 is not None else "")
                     + " · 같은 분모(8h × 그 달 평일수) · 근거는 8절 '출퇴근·시간외 근무'</div>")
        if pcc:
            h.append("<div class='dim'>PC 기록 = 그 달 평일 중 PC 가동 기록이 있는 날의 비율 — 40% 미만이면 "
                     "PC 하한·부재 추정이 꺼져 그 달만 낮게 나올 수 있다(System 로그 롤오버·힌트 없음).</div>")

    if rows:
        h.append("<h2>2. 과제별 업무 로드</h2><table><tr><th>업무 영역</th><th>업무분류</th><th>과제</th><th>세부업무</th>"
                 "<th>상세설명</th><th>MM</th><th>비중</th><th>근거</th><th>확신</th></tr>")
        for r in sorted(rows, key=lambda x: -float(x.get("mm") or 0)):
            h.append(f"<tr><td>{esc(r.get('Level 1'))}</td><td>{esc(r.get('유형'))}</td><td><b>{esc(r.get('Level 2'))}</b></td>"
                     f"<td>{esc(r.get('Level 3'))}</td><td>{esc(r.get('상세설명'))}</td>"
                     f"<td>{esc(r.get('mm'))}</td>"
                     f"<td>{round(float(r.get('share') or 0)*100)}%</td>"
                     f"<td class='dim'>{esc(r.get('근거'))}</td><td>{esc(r.get('확신도'))}</td></tr>")
        h.append("</table>")

    bw = pv.get("by_worktype") or {}
    if bw:
        h.append("<h2>3. 업무분류 배분</h2><table><tr><th>업무분류</th><th>MM</th><th>과제 배분</th></tr>")
        for t, v in bw.items():
            chips = "".join(f"<span class='tag'>{esc(k)} {x:.2f}</span>"
                            for k, x in (v.get("models") or {}).items())
            h.append(f"<tr><td><b style='color:{WT.get(t,'#333')}'>{esc(t)}</b></td>"
                     f"<td>{v.get('mm',0):.2f}</td><td>{chips}</td></tr>")
        h.append("</table>")

    common = pv.get("common") or []
    if common:
        h.append("<h2>4. 공통업무 — 표준화·자동화 후보</h2>"
                 "<div class='dim'>여러 과제에 반복되는 업무일수록 표준화·AI 대체 우선순위가 높다</div>"
                 "<table><tr><th>세부업무</th><th>관련 과제</th><th>합산 MM</th></tr>")
        for c in common:
            h.append(f"<tr><td><b>{esc(c.get('detail'))}</b></td>"
                     f"<td>{esc(', '.join(c.get('models') or []))}</td>"
                     f"<td>{c.get('mm',0):.2f}</td></tr>")
        h.append("</table>")

    if nar:
        h.append("<h2>5. 월별 리뷰 코멘트</h2>")
        for mk in sorted(nar):
            v = nar[mk] or {}
            if not isinstance(v, dict):
                continue
            # 다른 기간에서 이월했거나(from_tag) 이번 실행에서 새로 만들지 못한(earlier) 달 — 이전 분석의 코멘트임을 적는다
            old = " <span class='dim'>(이전 분석 코멘트)</span>" if (v.get("from_tag") or v.get("earlier")) else ""
            h.append(f"<h3 style='font-size:14px;margin:14px 0 4px'>{esc(mk)}{old}</h3>"
                     f"<div>{esc(v.get('summary'))}</div>")
            for p in (v.get("projects") or []):
                if not isinstance(p, dict):          # AI가 문자열 배열로 줄 때도 리포트는 나와야 한다
                    h.append(f"<div style='margin-top:3px'>· {esc(p)}</div>")
                    continue
                h.append(f"<div style='margin-top:3px'>· <b>{esc(p.get('name'))}</b> "
                         f"{esc(p.get('story'))} <span class='dim'>{esc(p.get('worktypes'))}</span></div>")

    if ent.get("models"):
        models = [m for m in ent["models"] if isinstance(m, dict)]
        has_l1 = any(m.get("l1") for m in models)          # 체계가 과제마다 고른 업무 영역(l1) — 있는 체계만 열을 보인다
        h.append("<h2>6. 과제 체계</h2>"
                 + ("<div class='dim'><b>규칙 폴백 체계(임시)</b> — 체계 수립 왕복이 실패해 규칙으로 만든 임시 체계입니다. "
                    "다음 판정이 다시 세웁니다.</div>" if ent.get("fallback") else "")
                 + ("<div class='dim'><b>지난 체계 재사용</b> — 새로 물을 신호가 없어 지난 정상 체계를 그대로 썼습니다.</div>"
                    if ent.get("reused_from") else "")
                 + "<table><tr><th>과제</th>" + ("<th>업무 영역</th>" if has_l1 else "")
                 + "<th>식별 키워드</th><th>채택 근거</th></tr>")
        pin_badge = "<span class='tag'>지정</span>"
        for m in models:
            badge = pin_badge if m.get("pinned") else ""
            h.append(f"<tr><td><b>{esc(m.get('name'))}</b> {badge}</td>"
                     + (f"<td>{esc(m.get('l1') or '–')}</td>" if has_l1 else "")
                     + f"<td class='dim'>{esc(', '.join(m.get('match') or []))}</td>"
                     f"<td class='dim'>{esc(m.get('obs'))}</td></tr>")
        h.append("</table>")

    # LM29부터 — Agentic AI 니즈 후보만(팀 과제 매칭·오할당 검증 없음). LM28 이 남긴 파일이면 match·misassigned 는 읽지 않는다.
    ag = _json(os.path.join(REP, f"agentic_{tag}.json"))
    ag = ag if isinstance(ag, dict) else {}
    ag_new =[n for n in (ag.get("new") if isinstance(ag.get("new"), list) else []) if isinstance(n, dict)]
    if ag:
        h.append("<h2>7. Agentic AI 니즈 후보</h2>"
                 "<div class='dim'>팀 과제와 매칭하지 않고, 내 반복 업무에서 Agentic AI 로 자동화할 만한 니즈 후보만 찾았습니다"
                 "(Copilot 판정) · 근거 업무 N행 = 이 후보의 근거가 된 내 업무 행 수(MM 아님)</div>")
        for n2 in ag_new:
            # '대체 가능 MM' 은 보이지 않는다(A-33 RP4) — 근거 업무 행 수만
            h.append(f"<div style='margin:6px 0'>· <b>{esc(n2.get('name'))}</b>"
                     + (f" <span class='dim'>(근거 업무 {_n(n2.get('evidence_rows'))}행)</span>"
                        if n2.get("evidence_rows") is not None else "")
                     + (f"<br><span class='dim'>동작 로직: {esc(n2.get('logic'))}</span>" if n2.get("logic") else "")
                     + (f"<br><span class='dim'>발굴 사유: {esc(n2.get('reason'))}</span>" if n2.get("reason") else "")
                     + (f"<br><span class='dim'>근거 업무: {esc(', '.join(str(w) for w in (n2.get('work') or [])[:12]))}</span>"
                        if isinstance(n2.get("work"), list) and n2.get("work") else "")
                     + "</div>")
        if not ag_new:
            h.append("<div class='dim'>근거가 충분한 니즈 후보가 없습니다.</div>")
        if _n(ag.get("rule_rows")):
            # AI 판정 대기(신호 대부분이 규칙 판정이라 아직 묻지 않은 업무) — 후보가 적은 이유로 읽히게(진단 D)
            h.append(f"<div class='dim'>AI 판정 대기 {_n(ag.get('rule_rows'))}행 — 신호 대부분이 규칙 판정이라 아직 보내지 "
                     "않은 업무입니다(판정이 회복된 뒤 [니즈 후보 발굴 실행]).</div>")

    h.append("<h2>8. 산정 근거와 신뢰도</h2><table>")
    # LM22: 상한 없음 — 잘라낸 것이 아니라 '표시'한다(이상치·16h 초과·부재일 흔적). 값이 없는 키는 표에 없다.
    BASIS_ROWS = (("basis", "산정 방식"), ("method", "투입 산정"), ("absence_days", "부재(가용 차감)"),
                  ("inferred_absence_days", "부재 추정(가용 차감, 일)"),
                  ("overtime_h", "초과근무(h)"), ("weekend_days", "주말 근무(일)"),
                  ("night_days", "야근(일)"), ("no_evidence_days", "흔적 없는 평일"),
                  ("gap_days", "연속공백 제외(회)"), ("sampler_days", "창 샘플러 가동(일)"),
                  ("sampler_partial_days", "샘플러 부분 가동 보정(일)"),
                  ("holidays", "공휴일 제외(일)"),
                  ("pc_floor_h", "PC가동 하한 보정(h)"), ("pc_floor_days", "PC가동 하한 보정(일)"),
                  ("lunch_deducted_h", "점심 차감(h)"),
                  ("evening_credit_h", "퇴근 후·새벽 인정(h — 퇴근 경계~마지막 산출물 전체, +30분 꼬리 없음)"),
                  ("weekend_window_h", "주말 산출물 창(h)"),
                  ("floor_blocked_passive_days", "수동 흔적만(하한 미적용, 일)"),
                  ("absent_worked_h", "부재일 흔적(h)"),
                  ("future_signals_dropped", "미래 시각 폐기(건)"),
                  ("phys_cap_days", "24h 물리상한(일)"), ("day_cap_days", "설정 상한 적용(일)"),
                  ("sampler_stuck_days", "샘플러 고착 의심(일)"),
                  # ── LM22 2차(A6·A9·A13·A18·A33·A34·D3·D4·D5·D7) — 값이 있는 키만 표에 나온다 ──
                  ("measure", "측정 방식"), ("coverage", "측정 신뢰도"),
                  ("tool_usage", "프로그램 사용(참고)"),
                  ("offsite_days", "종일 행사 — 출장·현장·교육(표준 8h 인정, 일)"),
                  ("offsite_h", "종일 행사 인정(h)"),
                  ("manual_days", "수동 기록 Add-WorkLog(일)"), ("manual_h", "수동 기록 인정(h)"),
                  ("dinner_deducted_h", "저녁 식사 차감(h)"),
                  ("flex_edge_h", "시차 근무 창 밖 인정(h)"),
                  ("sampler_bridge_h", "샘플러 공백 다리(h)"),
                  ("pc_record_missing_days", "PC 기록 결측 평일(흔적 창 폴백, 일)"),
                  ("trace_window_days", "흔적 창 폴백(일)"), ("trace_window_h", "흔적 창 폴백(h)"),
                  ("pc_coverage_by_month", "월별 PC 기록 비율"),
                  ("passive_capped_days", "수동 세션 상한 적용(일)"),
                  ("weekend_pc_days", "주말 PC 창 인정(일)"),
                  ("sim_night", "야간 해석(솔버) 인정"),
                  ("future_days", "미래 평일(가용 제외, 일)"), ("today_fraction", "오늘 진행 비율(가용 반영)"),
                  ("cfg_used", "산식 설정"),
                  ("anomalies", "이상치(PC 기록 오류·부재일 흔적 등, 일)"),
                  ("long_days", "16h 초과(일)"), ("utc_suspect", "메일 시각 UTC 의심"),
                  ("config_warnings", "설정 경고(기본값으로 대체)"))
    NEW_KEYS = ("measure", "coverage", "cfg_used", "tool_usage", "offsite_days", "offsite_h", "manual_days", "manual_h",
                "dinner_deducted_h", "flex_edge_h", "sampler_bridge_h", "pc_record_missing_days",
                "trace_window_days", "trace_window_h", "pc_coverage_by_month", "passive_capped_days",
                "weekend_pc_days", "future_days", "today_fraction")
    bb = dict(b)
    for k in NEW_KEYS:                       # mine 이 최상위/mm_info 에 실었을 수도 있다
        if k not in bb and _pick(meta, b, k) is not None:
            bb[k] = _pick(meta, b, k)
    # 야간 해석(솔버) 인정(S4-N1) — 밤새 돌린 해석의 실행 구간. 값이 0 이면 줄을 만들지 않는다
    if _h(_pick(meta, b, "sim_night_h")) or _n(_pick(meta, b, "sim_night_days")):
        bb["sim_night"] = (f"{_h(_pick(meta, b, 'sim_night_h')):.1f}h · "
                           f"{_n(_pick(meta, b, 'sim_night_days'))}일"
                           f"(상한 {_n(_pick(meta, b, 'sim_night_capped_days'))}일 · "
                           f"재실행으로 상한 해제 {_n(_pick(meta, b, 'sim_night_unlocked_days'))}일 · "
                           f"PC 밖 {_h(_pick(meta, b, 'sim_night_remote_h')):.1f}h)")
    if meta.get("rehours"):
        bb["rehours"] = (f"비업무 제외 {_n(meta.get('dropped_n'))}건 · −{_h(meta.get('dropped_h')):.1f}h"
                         + (f" (투입 {_h(meta.get('total_mm_before_rehours')):.2f} → {inmm:.2f} MM)"
                            if meta.get("total_mm_before_rehours") is not None else ""))
    BASIS_ROWS = BASIS_ROWS + (("rehours", "비업무 제외 재산정"),)
    # LM30v1(2026-10-19) 법정 채움 MM — 맨 위에 규칙 한 문장, 끝에 표시 날짜('휴가 추정'·'근태·흔적 모두 없음' — 이 PC 리포트만).
    # 휴가·부재 추정 줄은 가용에서 빼지 않고 법정 시간으로 채우므로 이름을 바꾼다
    if legal_on:
        cu8 = _obj(_pick(meta, b, "cfg_used")) or {}
        bb["mm_rule"] = "법정 채움(mm.basis legal) — " + _at.legal_rule_text(cu8.get("standardDayHours"))
        lfl = (legal_local(att_doc) or {}).get("flags")
        ftxt = " / ".join(t for t in (_at.legal_flag_text(lfl, k) for k in ("inferred", "nohr")) if t)
        if ftxt:
            bb["legal_flags"] = ftxt
        BASIS_ROWS = (("mm_rule", "MM 기준"),) + BASIS_ROWS + (("legal_flags", "법정 채움 표시 날짜"),)
    tool_tbl = ""                       # 프로그램 사용(참고) 상세 표 — 이 표(셀이 통째로 esc 된다) 뒤에 따로 붙인다
    # LM30(2026-10-18) — 출퇴근 추정이 투입을 맡았으면 초과근무·야근일·주말 근무는 그 값(이름을 그렇게)이고, PC 하한·점심·저녁 인정
    # 같은 LM29 줄은 'LM29 방식(비교용) 근거' 로 적는다
    a_on = att_used(meta, b)
    for k, label in BASIS_ROWS:
        if a_on:
            label = ATT_LABEL.get(k, label)
            if k in LM29_ONLY:
                label = f"{LM29_TAG} — {label}"
        if legal_on:
            label = LEGAL_LABEL.get(k, label)
        if k not in bb:
            continue
        v = bb[k]
        if k in ("offsite_days", "manual_days", "pc_record_missing_days", "trace_window_days",
                 "passive_capped_days", "weekend_pc_days", "future_days"):
            v = _fmt_days(v)
        elif k in ("offsite_h", "manual_h", "dinner_deducted_h", "flex_edge_h", "sampler_bridge_h",
                   "trace_window_h"):
            v = f"{_h(v):.1f}h"
        elif k == "today_fraction":
            v = f"{round(_h(v) * 100)}% (분석 시각까지의 주간 창 비율 — 그만큼만 가용)"
        elif k == "pc_coverage_by_month":
            if not isinstance(v, dict) or not v:
                continue
            v = " · ".join(f"{esc(mk)} {round(_h(r) * 100)}%" + (" [하한 미적용]" if _h(r) < 0.4 else "")
                           for mk, r in sorted(v.items()))
        elif k == "measure":
            ms = v if isinstance(v, dict) else {}
            v = measure_line(meta, {**b, **ms}) or "–"
            if ms.get("floor_blocked_passive_days"):
                v += f" · 수동 흔적만 {_n(ms.get('floor_blocked_passive_days'))}일"
            if ms.get("pc_record_missing_days"):
                v += f" · PC 기록 결측 {_n(ms.get('pc_record_missing_days'))}일"
        elif k == "coverage":
            cv = v if isinstance(v, dict) else {}
            g = str(cv.get("grade") or "").lower()
            reasons = cv.get("reasons") if isinstance(cv.get("reasons"), list) else (
                cv.get("missing") if isinstance(cv.get("missing"), list) else [])
            if g not in GRADE_LABEL and not reasons:
                continue
            v = (GRADE_LABEL.get(g, g or "–")
                 + (" — " + " · ".join(str(x) for x in reasons[:6]) if reasons else "")
                 + (" · 팀 비교에서 제외" if g == "unreliable" else ""))
            r = cv.get("pc_weekday_ratio")
            if isinstance(r, (int, float)) and not isinstance(r, bool):
                v += f" · 평일 PC 기록 {round(float(r) * 100)}%"
        elif k == "tool_usage":
            # 참고 지표 — 투입 시간이 아니다(맨 앞 창을 띄우고 있던 시간). 로드율과 섞어 읽지 않도록 문구로 못 박는다.
            # 이 표의 셀은 마지막에 통째로 esc() 되므로 여기서는 태그도 esc 도 쓰지 않는다(쓰면 글자로 박힌다).
            # 새 꼴(출처·실행 횟수·포커스·마지막 실행·파일 일수 + 자체·프로토타입(추정))은 이 표 뒤의 상세 표(tool_tbl)로 —
            # 옛 꼴(창기록만)도 같은 함수가 그린다.
            tu = v if isinstance(v, dict) else {}
            v = tool_usage_text(tu)
            if not v:
                continue
            tool_tbl = tool_usage_table(tu)
        elif k == "cfg_used":
            cu = v if isinstance(v, dict) else {}
            if not cu:
                continue

            def _win(x):
                return "~".join(str(y) for y in x) if isinstance(x, (list, tuple)) else str(x or "")
            v = (f"표준 {cu.get('standardDayHours', '–')}h · PC 하한 {'끔' if cu.get('usePcFloor') is False else '켬'}"
                 + (f"({cu.get('pcFloorNeeds')})" if cu.get("pcFloorNeeds") else "")
                 + f" · 주간 창 {_win(cu.get('dayWindow'))} · 점심 {_win(cu.get('lunch'))}"
                 + (f" · 저녁 {_win(cu.get('dinner'))}" if cu.get("dinner") else "")
                 + f" · 미정 회의 {cu.get('tentativeMeetings', '–')} · 공휴일 {_n(cu.get('holidays_n'))}일"
                 + (" · 종일 행사 미인정" if cu.get("offsiteAsWork") is False else "")
                 + (f" · 샘플러 공백 다리 {_n(cu.get('samplerGapBridgeMin'))}분"
                    if cu.get("samplerGapBridgeMin") is not None else "")
                 # LM28 — 하한 창(퇴근 경계)·야간 창·사적 차감 문턱·과제 몫 기준
                 + (f" · PC 하한 창 {_win(cu.get('pcFloorWindow'))}" if cu.get("pcFloorWindow") else "")
                 + (f" · 야간 {_win(cu.get('nightWindow'))}" if cu.get("nightWindow") else "")
                 + (f" · 사적 차감 {cu.get('privateRunMin')}분 연속" if cu.get("privateRunMin") is not None else "")
                 + (f" · 과제 몫 {cu.get('shareBasis')}" if cu.get("shareBasis") else "")
                 # LM28(E) — PC 기록 없는 달의 평일: standard = 표준일 추정(기본) · trace = 흔적 창(예전)
                 + (f" · PC 기록 없는 달 {'흔적 창(예전)' if cu.get('noPcMonthDay') == 'trace' else '표준일 추정(기본)'}"
                    if cu.get("noPcMonthDay") else "")
                 + " — 팀과 다르면 팀 취합에 '산식 설정 상이' 배지")
        if k == "anomalies":
            items = [a for a in (v or []) if isinstance(a, dict)]
            v = f"{len(items)}일" + (" — " + " · ".join(
                f"{str(a.get('date', ''))[5:]} {a.get('kind', '')}"
                + (f" ({a.get('raw')} → {a.get('used')})" if a.get("raw") is not None else "")
                for a in items[:12]) if items else "")
        elif k == "long_days":
            items = [x for x in (v or []) if isinstance(x, (list, tuple)) and len(x) == 2]
            v = f"{len(items)}일" + (" — " + " · ".join(f"{str(x[0])[5:]} {x[1]}h" for x in items[:12])
                                    if items else "")
        elif k == "config_warnings":
            items = [str(x) for x in (v or []) if str(x).strip()]
            if not items:
                continue
            v = f"{len(items)}건 — " + " · ".join(items[:8]) + (" …" if len(items) > 8 else "")
        elif k == "utc_suspect":
            if not v:
                continue
            v = "예 — 발신 메일의 60% 이상이 00~08시. config.mm.mailTimeOffsetH(예: 9) 로 보정"
        h.append(f"<tr><th style='width:180px'>{label}</th><td>{esc(v)}</td></tr>")
    # LM28(A-22·C-31): 초과근무 세분(연장·야간·휴일)·사적 차감·미관측 일수 — WP8 mm_basis 새 키(값이 있는 것만)
    for label, v in overtime_rows(meta, b):
        h.append(f"<tr><th style='width:180px'>{esc(label)}</th><td>{esc(v)}</td></tr>")
    h.append("</table>")
    # LM30(2026-10-18) 출퇴근·시간외 근무 — 이 리포트는 이 PC 에만 있으므로(공유폴더로 복사되지 않는다) 날짜별 표까지 싣는다
    h += attendance_section(meta, b, _json(os.path.join(REP, f"attendance_{tag}.json")), per_day=True)
    if tool_tbl:
        h.append(tool_tbl)
    h.append("<div class='dim'>해석 참고: 애자일 관행(SAFe 등)은 명목 가용의 70~80%를 실질 "
             "capacity로 본다 — 회의·전환비용을 감안하면 로드율 75~85%가 '꽉 찬 상태'에 가깝고, "
             "지속적 100% 초과는 과부하 신호다.</div>")
    if not b.get("sampler_days"):
        h.append("<div class='dim'>※ 투입 시간은 PC 켜기·끄기 기록과 활동 흔적(회의·산출물·메일·커밋)으로 계산했습니다 "
                 "(LM30v1 에는 창 샘플러가 없습니다).</div>")
    # ★ 사용자 지시(2026-10-07 ②): 산출 방식 — PC 가동 하한의 근거 + 날짜별 방식·하한을 연 흔적·깎은 시간
    h += floor_section(meta, b)

    if sig:
        by = defaultdict(list)
        for r in sig:
            by[r.get("project") or r.get("model") or "공통"].append(r)
        h.append("<h2>9. raw 단서 (해석 검증용)</h2>"
                 "<div class='dim'>수치가 이상하면 아래 원문으로 확인하세요. 전체는 "
                 f"report\\signals_{esc(tag)}.csv 에 있습니다.</div>")
        for pj, rs in sorted(by.items(), key=lambda kv: -len(kv[1]))[:8]:
            h.append(f"<div style='margin-top:8px'><b>{esc(pj)}</b> "
                     f"<span class='dim'>{len(rs)}건</span></div><div class='dim'>")
            for r in rs[:6]:
                h.append(f"· {esc(r.get('time','')[:16])} [{esc(r.get('source'))}] "
                         f"{esc((r.get('text') or '')[:70])}<br>")
            h.append("</div>")
    # LM28(REQ-37·REQ-38·A-37·A-38·W2-10): 동료 · 연관 업무 · 업무 영역·과제 워크플로 요약(단위업무 등급)
    wf = _json(os.path.join(REP, f"workflow_{tag}.json"))
    h += new_sections(sig, wf, rows, pv, summary=summary, ctx=_privacy_ctx(), n0=10)     # 7절 = Agentic AI 니즈 후보
    return "\n".join(h)


def main():
    d0, d1 = arg("--from"), arg("--to")
    tag = f"{d0.replace('-','')}-{d1.replace('-','')}" if (d0 and d1) else latest_tag()
    if not tag:
        print("[report] 분석 결과가 없습니다 — 먼저 [분석 실행]")
        print(json.dumps({"ok": False, "error": "no result"}))
        return 1
    doc = build(tag)
    if not doc:
        print(f"[report] mm_meta_{tag}.json 이 없습니다")
        print(json.dumps({"ok": False, "error": "no meta"}))
        return 1
    out_html = os.path.join(REP, f"리포트_{tag}.html")
    with open(out_html, "w", encoding="utf-8") as f:
        f.write(doc)
    out_doc = os.path.join(REP, f"리포트_{tag}.doc")     # Word 가 HTML 을 그대로 연다
    with open(out_doc, "w", encoding="utf-8") as f:
        f.write(doc)
    print(f"[report] → {out_html}")
    print(f"[report] → {out_doc}  (더블클릭하면 Word로 열립니다)")
    print(json.dumps({"ok": True, "html": out_html, "doc": out_doc, "tag": tag},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, errors="replace", encoding=(
        (sys.stdout.encoding or "utf-8") if sys.stdout.isatty() else "utf-8"))  # 콘솔(bat)=콘솔 코드페이지 · 파이프(UI)=utf-8
    sys.exit(main())
