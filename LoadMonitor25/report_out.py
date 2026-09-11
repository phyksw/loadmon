# -*- coding: utf-8 -*-
"""
report_out.py — 현재 분석 결과를 하나의 리포트 파일로 출력한다 (8b).

  python report_out.py                       # 최신 결과
  python report_out.py --from ... --to ...

출력: report\\리포트_<기간>.html   (브라우저에서 열람, Word에서 [파일 > 열기]로 편집 가능)
      report\\리포트_<기간>.doc    (더블클릭하면 Word로 열림 — 같은 내용)

담기는 것: 투입/가용 MM·로드율 · 과제별 로드 · 업무유형 배분 · 공통업무(Agentic AI 후보)
          · 월별 리뷰 코멘트 · 산정 근거와 신뢰도 · raw 단서 요약
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
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


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


def build(tag):
    meta = _json(os.path.join(REP, f"mm_meta_{tag}.json"))
    if not meta:
        return None
    # 오래된 정제본은 쓰지 않는다 (aggregate·flow·agentic 과 같은 규칙)
    rows = ((_rows(os.path.join(REP, f"mm_rows_{tag}_refined.csv"))
             if _fresh_refined(os.path.join(REP, f"mm_rows_{tag}.csv"),
                               os.path.join(REP, f"mm_rows_{tag}_refined.csv")) else [])
            or _rows(os.path.join(REP, f"mm_rows_{tag}.csv")))
    pv = _json(os.path.join(REP, f"pivots_{tag}.json"))
    nar = _json(os.path.join(REP, f"ai_narratives_{tag}.json"))
    ent = _json(os.path.join(REP, f"entities_{tag}.json"))
    sig = _rows(os.path.join(REP, f"signals_{tag}.csv"))
    b = meta.get("mm_basis") or {}
    period = " ~ ".join(meta.get("period") or [tag])
    inmm = meta.get("total_mm") or 0
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
         "<div class='dim'>로드율 = 투입 ÷ 가용 · 1 MM = 8h × 그 달 평일수 · "
         "가용은 연차·휴가(+부재 추정)를 일자에서 뺀 값 · 투입은 상한 없이 실측 그대로"
         "(하루 24h 물리 한계만 · 이상치는 8절 표에 표시)</div>"]
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
    if mo:
        h.append("<h2>1. 월별 로드</h2><table><tr><th>월</th><th>투입 MM</th><th>가용 MM</th>"
                 "<th>로드율</th><th>투입 시간</th><th>부재</th><th>그 달 평일</th>"
                 + ("<th>PC 기록</th>" if pcc else "") + "</tr>")
        for k, v in mo:
            v = v if isinstance(v, dict) else {}
            pc_td = ""
            if pcc:
                r = pcc.get(k)
                if r is None:
                    pc_td = "<td class='dim'>–</td>"
                else:
                    pc_td = (f"<td>{round(_h(r) * 100)}%"
                             + (" <b style='color:#b54708'>하한 미적용(PC 기록 없음)</b>" if _h(r) < 0.4 else "")
                             + "</td>")
            h.append(f"<tr><td>{esc(k)}</td><td><b>{_h(v.get('mm')):.2f}</b></td>"
                     f"<td>{_h(v.get('avail_mm')):.2f}</td>"
                     f"<td><b>{'–' if v.get('load_pct') is None else str(v['load_pct'])+'%'}</b></td>"
                     f"<td>{esc(v.get('worked'))}h</td><td>{esc(v.get('absent'))}일</td>"
                     f"<td>{esc(v.get('workdays'))}일</td>{pc_td}</tr>")
        h.append("</table>")
        if pcc:
            h.append("<div class='dim'>PC 기록 = 그 달 평일 중 PC 가동 기록이 있는 날의 비율 — 40% 미만이면 "
                     "PC 하한·부재 추정이 꺼져 그 달만 낮게 나올 수 있다(System 로그 롤오버·힌트 없음).</div>")

    if rows:
        h.append("<h2>2. 과제별 업무 로드</h2><table><tr><th>유형</th><th>과제</th><th>세부업무</th>"
                 "<th>상세설명</th><th>MM</th><th>비중</th><th>근거</th><th>확신</th></tr>")
        for r in sorted(rows, key=lambda x: -float(x.get("mm") or 0)):
            h.append(f"<tr><td>{esc(r.get('유형'))}</td><td><b>{esc(r.get('Level 2'))}</b></td>"
                     f"<td>{esc(r.get('Level 3'))}</td><td>{esc(r.get('상세설명'))}</td>"
                     f"<td>{esc(r.get('mm'))}</td>"
                     f"<td>{round(float(r.get('share') or 0)*100)}%</td>"
                     f"<td class='dim'>{esc(r.get('근거'))}</td><td>{esc(r.get('확신도'))}</td></tr>")
        h.append("</table>")

    bw = pv.get("by_worktype") or {}
    if bw:
        h.append("<h2>3. 업무유형 배분</h2><table><tr><th>유형</th><th>MM</th><th>과제 배분</th></tr>")
        for t, v in bw.items():
            chips = "".join(f"<span class='tag'>{esc(k)} {x:.2f}</span>"
                            for k, x in (v.get("models") or {}).items())
            h.append(f"<tr><td><b style='color:{WT.get(t,'#333')}'>{esc(t)}</b></td>"
                     f"<td>{v.get('mm',0):.2f}</td><td>{chips}</td></tr>")
        h.append("</table>")

    common = pv.get("common") or []
    if common:
        h.append("<h2>4. 공통업무 — Agentic AI 자동화 후보</h2>"
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
            h.append(f"<h3 style='font-size:14px;margin:14px 0 4px'>{esc(mk)}</h3>"
                     f"<div>{esc(v.get('summary'))}</div>")
            for p in (v.get("projects") or []):
                if not isinstance(p, dict):          # AI가 문자열 배열로 줄 때도 리포트는 나와야 한다
                    h.append(f"<div style='margin-top:3px'>· {esc(p)}</div>")
                    continue
                h.append(f"<div style='margin-top:3px'>· <b>{esc(p.get('name'))}</b> "
                         f"{esc(p.get('story'))} <span class='dim'>{esc(p.get('worktypes'))}</span></div>")

    if ent.get("models"):
        h.append("<h2>6. 과제 체계</h2><table><tr><th>과제</th><th>식별 키워드</th>"
                 "<th>채택 근거</th></tr>")
        pin_badge = "<span class='tag'>지정</span>"
        for m in ent["models"]:
            badge = pin_badge if m.get("pinned") else ""
            h.append(f"<tr><td><b>{esc(m.get('name'))}</b> {badge}</td>"
                     f"<td class='dim'>{esc(', '.join(m.get('match') or []))}</td>"
                     f"<td class='dim'>{esc(m.get('obs'))}</td></tr>")
        h.append("</table>")

    import aggregate
    ag = aggregate.norm_agentic(_json(os.path.join(REP, f"agentic_{tag}.json")))
    classified_mm = sum(aggregate.fnum(row.get("mm"), 0.0) for row in rows)
    h.append(f"<div class='dim'>투입 추정 {inmm:.2f} MM · 분류 업무 {classified_mm:.2f} MM · "
             f"미배분 {max(0.0, inmm-classified_mm):.2f} MM(제외·분류 미확정, 절감량 아님)</div>")
    if ag.get("match") is not None:
        h.append("<h2>7. Agentic AI 과제 매칭</h2>"
                 "<div class='dim'>계획된 Agentic AI 12과제와 현재 업무 로드의 매칭 — "
                 "적합률은 AI 적용 적합도이며, 예상 절감량은 미검증입니다.</div>"
                 "<table><tr><th>축</th><th>과제</th><th>적합률</th><th>후보별 안분 업무량(MM)</th>"
                 "<th>매칭 현업</th><th>사유</th></tr>")
        for m in ag.get("match") or []:
            if not m.get("fit"):
                continue
            h.append(f"<tr><td>{esc(m.get('axis'))}</td>"
                     f"<td><b>{esc(m.get('task'))}</b> {esc(m.get('name'))}</td>"
                     f"<td><b>{esc(m.get('fit'))}%</b></td><td>{'미확인' if m.get('allocated_candidate_mm') is None else format(m['allocated_candidate_mm'], '.2f')}</td>"
                     f"<td>{esc(', '.join(m.get('work') or []))}</td>"
                     f"<td class='dim'>{esc(m.get('reason'))}</td></tr>")
        h.append("</table>")
        if ag.get("new"):
            h.append("<h3 style='font-size:14px'>신규 Agentic AI 후보 발굴</h3>")
            for n2 in ag["new"]:
                h.append(f"<div style='margin:6px 0'>· <b>{esc(n2.get('name'))}</b> "
                         f"(후보별 안분 업무량 {'미확인' if n2.get('allocated_candidate_mm') is None else format(n2['allocated_candidate_mm'], '.2f')} MM)<br>"
                         f"<span class='dim'>로직: {esc(n2.get('logic'))}<br>"
                         f"사유: {esc(n2.get('reason'))}</span></div>")
        if ag.get("misassigned"):
            h.append("<h3 style='font-size:14px'>분류기 검증 — 오할당 의심</h3>"
                     "<div class='dim'>본인 업무가 아닌데 분류된 것으로 의심되는 항목 — "
                     "UI Agentic AI 탭에서 확정·제외 가능</div>")
            for m2 in ag["misassigned"]:
                h.append(f"<div class='dim'>· <b>{esc(m2.get('row'))}</b> — {esc(m2.get('reason'))}</div>")

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
                  ("lunch_deducted_h", "점심 차감(h)"), ("evening_credit_h", "저녁·새벽 인정(h)"),
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
    for k, label in BASIS_ROWS:
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
            tu = v if isinstance(v, dict) else {}
            progs = [p for p in (tu.get("programs") or []) if isinstance(p, dict)]
            if not progs:
                why = str(tu.get("why") or "").strip()
                if not why:
                    continue
                v = why
            else:
                v = " · ".join(
                    f"{p.get('name')} " + (f"배경 {_h(p.get('bg_hours')):.0f}h" if _h(p.get("hours")) < 0.05
                                           else f"{_h(p.get('hours')):.1f}h"
                                                + (f"(배경 {_h(p.get('bg_hours')):.0f}h)"
                                                   if _h(p.get("bg_hours")) >= 1 else ""))
                    for p in progs[:6])
                kinds = [x for x in (tu.get("by_kind") or []) if isinstance(x, (list, tuple)) and len(x) >= 2]
                if kinds:
                    v += " / 구분: " + " · ".join(f"{x[0]} {_h(x[1]):.1f}h" for x in kinds)
                if _h(tu.get("solver_bg_h")) >= 1:
                    v += f" / 배경 솔버 가동 {_h(tu.get('solver_bg_h')):.0f}h"
                if _h(tu.get("unknown_h")) >= 1:
                    v += f" / 미상 {_h(tu.get('unknown_h')):.0f}h(카탈로그에 없는 실행 파일)"
                v += " / ※ 참고 지표 — 창 샘플러가 본 '맨 앞 창' 시간이라 투입 MM·로드율에는 들어가지 않는다"
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
    h.append("</table>")
    h.append("<div class='dim'>해석 참고: 애자일 관행(SAFe 등)은 명목 가용의 70~80%를 실질 "
             "capacity로 본다 — 회의·전환비용을 감안하면 로드율 75~85%가 '꽉 찬 상태'에 가깝고, "
             "지속적 100% 초과는 과부하 신호다.</div>")
    if not b.get("sampler_days"):
        h.append("<div class='dim'>※ 창 샘플러가 꺼져 있어 투입 시간이 과소 집계됐을 수 있습니다 — "
                 "collect\\Start-ActivitySampler.ps1 을 켜면 정확도가 크게 올라갑니다.</div>")

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
