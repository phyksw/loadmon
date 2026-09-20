# -*- coding: utf-8 -*-
r"""lint 관문 10 — 팀취합본 로드율 재계산기(team_recalc.py)의 계약.

계약(어느 하나가 깨지면 패키징 전에 실패한다) — 3렌즈 반증 검증(2026-09-20)에서 재현된 결함 경로를 전부 합성 자료로 덮는다:
  ① 판 무관: 같은 signals 를 LM20 형식 mm_meta / v3 형식 mm_meta 와 짝지어도 A·B·C3 가 자리수까지 같다 · 판 배지 lm20/v3/불명.
  ② 산식: 능동 평일 8h 바닥 + 표준 창(09~18) 밖 **능동** 세션 초과(창 밖 수동 조각은 가산 안 함) · 수동만인 평일은 8h 없음·수동 세션 하루
     60분 상한 · 야간 수동 제외 · 주말은 능동 있는 날만(수동만인 토요일 0) · 수동기록 시간(weight ÷ 시간당) 하한 · 자정 넘는 회의 익일 이월
     — 손으로 계산한 값(189.0h / A 181.0h)과 일치.
  ③ 가용: 통일 달력 평일수 − mm_months.absent · 분석 시점 절단(v3 A34)이 두 판에 같이 적용(7/16 09:00 → 11.09일) · D 원값도 절단(90.0h)
     · 가용 0 인 달(전월 부재)은 비율 없음·팀 합계 제외.
  ④ 결손 입력을 0 으로 섞지 않음: signals 없음/0바이트/열 이름 다름 → A·B·C3 빈칸 · mm_meta 없음 → D 빈칸 · cp949 로 재저장된 CSV 도 같은 값.
  ⑤ 겹치는 기간 파일: 과제 CSV 의 인별 MM_C3 합 == 월별 CSV 의 팀합계_사용 행 C3_MM 합(이중 계산 없음).
  ⑥ 무해: 기존 team_report.html 은 바이트 하나 바뀌지 않고 새 파일 3개(html + csv 2)만 · 같은 초 재실행은 _2 로 비켜 감 · HTML 에 원문 <script 없음.
  ⑦ 팀 폴더 해석: 명시 인자가 없는 폴더면 실패(폴백 없음·파일 0개) · 자동 탐색은 설치 폴더(report\ 있음)에서 teamdata\ 를 고른다.
사용: python tools/check_recalc.py   (exit 0/1 · 저장소 무변경 — 임시 폴더에서 돈다)
"""
import contextlib
import csv
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
from datetime import date, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
fail = 0


def _say(msg):
    os.write(1, (msg + chr(10)).encode("utf-8", "replace"))


def bad(msg):
    global fail
    fail = 1
    _say("[recalc] " + msg)


D0, D1 = date(2026, 7, 1), date(2026, 7, 31)          # 2026-07: 공휴일 없음 → 평일 23
TAG = "20260701-20260731"
WD = [D0 + timedelta(days=i) for i in range((D1 - D0).days + 1) if (D0 + timedelta(days=i)).isoweekday() <= 5]
OVERTIME = {WD[1], WD[5], WD[9]}          # 20:00 파일 → 창 밖 1h ×3
PASSIVE_ONLY = WD[3]                      # 수신 메일만 10:00~15:00 매 20분(16통) → 수동 상한 60분 → C3 1.0h
SAT_FILE, SAT_PASSIVE, SUN_MANUAL = date(2026, 7, 4), date(2026, 7, 11), date(2026, 7, 12)
MANUAL_WD, MIDNIGHT_WD = WD[6], WD[8]     # 수동기록 10h 평일 · 23:00 회의 2h(익일 00~01 이월, 익일 = WD[9] 야근일)
OUT_PASSIVE_WD, NIGHT_PASSIVE_WD = WD[2], WD[4]   # 18:30 수신(창 밖 수동 — C3 불변) · 22:30 팀즈(수신)(야간 수동 — 제외)
# 기대값: 능동 평일 22×8 + 야근 3 + 토 파일 1 + 수동상한일 1 + 일 수동기록 4 + 수동기록 평일 +2(10h) + 자정 회의 +1 +1
EXP_C3 = 22 * 8.0 + 3 + 1 + 1 + 4 + 2 + 2
EXP_A = 22 * 8.0 + 1 + 4


def make_signals(path, d0=D0, d1=D1, rich=True, encoding="utf-8-sig", header=None):
    rows = [header or ["time", "source", "who", "project", "activity", "weight", "text"]]
    d = d0
    while d <= d1:
        iso = d.isoformat()
        if d.isoweekday() <= 5:
            if d == PASSIVE_ONLY:
                for i in range(16):
                    hh, mm = divmod(10 * 60 + 20 * i, 60)
                    rows.append([f"{iso} {hh:02d}:{mm:02d}", "메일(수신)", "", "과제가", "", "0.5", "수신"])
            else:
                rows.append([f"{iso} 09:30", "파일", "", "과제가", "설계", "3.0", "문서"])
                rows.append([f"{iso} 10:00", "회의", "", "과제가", "회의", "2.0", "정례"])
                rows.append([f"{iso} 11:00", "메일(수신)", "", "과제가", "", "0.5", "수신"])
                rows.append([f"{iso} 14:00", "파일(코드)", "", "과제가", "코딩", "6.0", "코드"])
                if d in OVERTIME:
                    rows.append([f"{iso} 20:00", "파일", "", "과제가", "설계", "3.0", "야근"])
                if rich and d == OUT_PASSIVE_WD:
                    rows.append([f"{iso} 18:30", "메일(수신)", "", "과제가", "", "0.5", "창 밖 수동"])
                if rich and d == NIGHT_PASSIVE_WD:
                    rows.append([f"{iso} 22:30", "팀즈(수신)", "", "과제가", "", "0.3", "야간 수동"])
                if rich and d == MANUAL_WD:
                    rows.append([f"{iso} 09:00", "수동기록", "", "과제가", "현장", "20.0", "현장 10h"])
                if rich and d == MIDNIGHT_WD:
                    rows.append([f"{iso} 23:00", "회의", "", "과제가", "회의", "4.0", "해외 콜"])
        elif d == SAT_FILE:
            rows.append([f"{iso} 10:00", "파일", "", "과제가", "설계", "3.0", "주말"])
        elif rich and d == SAT_PASSIVE:
            rows.append([f"{iso} 11:00", "메일(수신)", "", "과제가", "", "0.5", "주말 수신"])
        elif rich and d == SUN_MANUAL:
            rows.append([f"{iso} 09:00", "수동기록", "", "과제가", "출장", "8.0", "출장 4h"])
        d += timedelta(days=1)
    with open(path, "w", encoding=encoding, newline="") as f:
        csv.writer(f).writerows(rows)


def make_meta(path, d0, d1, v3, absent, day_h, rehours_at=None, bom=False, extra=None):
    mk = d0.strftime("%Y-%m")
    m = {"period": [d0.isoformat(), d1.isoformat()], "months": 1.0, "signals": 90,
         "counted": {"파일": 46}, "excluded": {}, "weights": {"파일": 3.0, "회의": 2.0, "작업창_분당": 0.05, "IDE_분당": 0.0833},
         "total_mm": 1.0, "avail_mm": 0.9, "load_pct": 100.0,
         "mm_months": {mk: {"worked": sum(day_h.values()), "workdays": 23, "covered": 23, "absent": absent,
                            "capacity_h": 184, "avail_mm": 0.913, "mm": 1.0, "load_pct": 100.0}},
         "worked_h": round(sum(day_h.values()), 1), "mm_basis": {"absence_days": absent, "method": "activity"},
         "day_hours": {k.isoformat(): v for k, v in day_h.items()}}
    if v3:
        m["measure"] = {"method": "PC 하한"}
        m["cfg_used"] = {"standardDayHours": 8}
        m["mm_basis"]["lunch_deducted_h"] = 3.0
        m["weights"]["파일열람"] = 0.3
        m["weights"]["수동기록_시간당"] = 2.0       # v3 전용 라벨 — LM20 묶음에는 없다(판별 표식이기도 하다)
    if rehours_at:
        m["rehours_at"] = rehours_at
    if extra:
        m.update(extra)
    with open(path, "w", encoding=("utf-8-sig" if bom else "utf-8")) as f:
        json.dump(m, f, ensure_ascii=False, indent=1)


def make_rows(path, name, lv2="과제가"):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Function", "Level 1", "제품", "Level 2", "Level 3", "이름", "상세설명", "share", "mm", "근거", "확신도", "활동일수"])
        w.writerow(["System", "", "", lv2, "설계", name, "", "0.7", "0.7", "", "상", "20"])
        w.writerow(["System", "", "", "<script>x</script>", "회의·협업", name, "", "0.3", "0.3", "", "중", "20"])


def load_module(path):
    spec = importlib.util.spec_from_file_location("team_recalc_gate", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def read_csv(p):
    with open(p, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


T = tempfile.mkdtemp(prefix="lm_recalcgate_")
try:
    day_h = dict.fromkeys(WD, 7.5)
    for name, v3, bom, rehours in (("가_LM20", False, False, None), ("나_V3", True, True, None),
                                   ("다_V3미완", True, False, "2026-07-16 09:00")):
        md = os.path.join(T, name)
        os.makedirs(md)
        make_signals(os.path.join(md, f"signals_{TAG}.csv"))
        make_meta(os.path.join(md, f"mm_meta_{TAG}.json"), D0, D1, v3, 2.0, day_h, rehours, bom)
        with open(os.path.join(md, "member.json"), "w", encoding="utf-8") as f:
            json.dump({"owner": name, "function": "System <script>", "tag": TAG, "analyzed_at": "2026-08-03 09:00"}, f, ensure_ascii=False)
        make_rows(os.path.join(md, f"mm_rows_{TAG}.csv"), name)
    # 결손 입력 4종: mm_meta 만 · signals 만(판 불명) · 0바이트 signals · 열 이름 다른 signals
    os.makedirs(os.path.join(T, "라_메타만"))
    make_meta(os.path.join(T, "라_메타만", f"mm_meta_{TAG}.json"), D0, D1, False, 0.0, day_h)
    os.makedirs(os.path.join(T, "마_신호만"))
    make_signals(os.path.join(T, "마_신호만", f"signals_{TAG}.csv"))
    os.makedirs(os.path.join(T, "자_빈신호"))
    make_meta(os.path.join(T, "자_빈신호", f"mm_meta_{TAG}.json"), D0, D1, True, 0.0, day_h)
    open(os.path.join(T, "자_빈신호", f"signals_{TAG}.csv"), "wb").close()
    os.makedirs(os.path.join(T, "차_열이름"))
    make_meta(os.path.join(T, "차_열이름", f"mm_meta_{TAG}.json"), D0, D1, True, 0.0, day_h)
    make_signals(os.path.join(T, "차_열이름", f"signals_{TAG}.csv"), header=["시각", "출처", "who", "project", "activity", "weight", "text"])
    # 가용 0 인 달(전월 부재) · cp949 재저장 · 겹치는 두 기간
    os.makedirs(os.path.join(T, "바_부재월"))
    make_signals(os.path.join(T, "바_부재월", f"signals_{TAG}.csv"))
    make_meta(os.path.join(T, "바_부재월", f"mm_meta_{TAG}.json"), D0, D1, True, 23.0, day_h)
    os.makedirs(os.path.join(T, "아_엑셀"))
    make_signals(os.path.join(T, "아_엑셀", f"signals_{TAG}.csv"), encoding="cp949")
    make_meta(os.path.join(T, "아_엑셀", f"mm_meta_{TAG}.json"), D0, D1, False, 2.0, day_h)
    os.makedirs(os.path.join(T, "사_겹침"))
    for t0, t1 in ((date(2026, 6, 1), date(2026, 7, 31)), (date(2026, 7, 1), date(2026, 8, 31))):
        tg = f"{t0:%Y%m%d}-{t1:%Y%m%d}"
        make_signals(os.path.join(T, "사_겹침", f"signals_{tg}.csv"), t0, t1, rich=False)
        dh = {t0 + timedelta(days=i): 7.5 for i in range((t1 - t0).days + 1) if (t0 + timedelta(days=i)).isoweekday() <= 5}
        make_meta(os.path.join(T, "사_겹침", f"mm_meta_{tg}.json"), t0, t1, True, 0.0, dh)
        make_rows(os.path.join(T, "사_겹침", f"mm_rows_{tg}.csv"), "사_겹침")
    # 예약 폴더·기존 보고서
    os.makedirs(os.path.join(T, "team_cache"))
    with open(os.path.join(T, "team_cache", "member.json"), "w") as f:
        f.write("{}")
    old_html = "<html>기존 팀 보고서</html>"
    with open(os.path.join(T, "team_report.html"), "w", encoding="utf-8") as f:
        f.write(old_html)
    before = sorted(os.listdir(T))

    R = load_module(os.path.join(ROOT, "team_recalc.py"))
    rc = R.main([T, "--now", "2026-09-20 12:00", "--quiet"])
    if rc != 0:
        bad(f"main() rc={rc}")
    new = [x for x in sorted(os.listdir(T)) if x not in before]
    if len(new) != 3 or not any(x.endswith(".html") for x in new) or sum(x.endswith(".csv") for x in new) != 2:
        bad(f"⑥ 새 파일이 html 1 + csv 2 가 아닙니다: {new}")
    if open(os.path.join(T, "team_report.html"), encoding="utf-8").read() != old_html:
        bad("⑥ 기존 team_report.html 이 바뀌었습니다")
    html_p = [os.path.join(T, x) for x in new if x.endswith(".html")]
    page = open(html_p[0], encoding="utf-8").read() if html_p else ""
    if "<script" in page:
        bad("⑥ HTML 에 이스케이프 안 된 <script 가 있습니다(인젝션)")
    mon_p = [os.path.join(T, x) for x in new if x.endswith("_월별.csv")]
    task_p = [os.path.join(T, x) for x in new if x.endswith("_과제.csv")]
    rows = read_csv(mon_p[0]) if mon_p else []
    by = {(r["이름"], r["기간"], r["월"]): r for r in rows}
    who = {r["이름"] for r in rows}
    exp_who = {"가_LM20", "나_V3", "다_V3미완", "라_메타만", "마_신호만", "자_빈신호", "차_열이름", "바_부재월", "아_엑셀", "사_겹침"}
    if who != exp_who:
        bad(f"인원 집합이 다릅니다(team_cache 는 제외돼야 함): {sorted(who)}")
    else:
        P = f"{D0}~{D1}"
        a, b, c = by[("가_LM20", P, "2026-07")], by[("나_V3", P, "2026-07")], by[("다_V3미완", P, "2026-07")]
        # ① 판 무관 · 판별
        for k in ("A_h", "B_h", "C3_h", "A_pct", "B_pct", "C3_pct"):
            if a[k] != b[k]:
                bad(f"① 판 무관 실패 — {k}: LM20 {a[k]} vs v3 {b[k]}")
        if not (a["판"].startswith("LM20") and b["판"].startswith("LM24") and by[("마_신호만", P, "2026-07")]["판"] == "판 불명"):
            bad(f"① 판별 실패: {a['판']} / {b['판']} / {by[('마_신호만', P, '2026-07')]['판']}")
        # ② 산식
        if abs(float(a["C3_h"]) - EXP_C3) > 0.05:
            bad(f"② C3 산식 불일치 — {a['C3_h']}h (기대 {EXP_C3:.1f}: 능동 평일 22×8 + 창 밖 3 + 토 1 + 수동상한 1 + 수동기록 4+2 + 자정 회의 2)")
        if abs(float(a["A_h"]) - EXP_A) > 0.05:
            bad(f"② A 산식 불일치 — {a['A_h']}h (기대 {EXP_A:.1f})")
        if float(a["D_h"]) != round(23 * 7.5, 1):
            bad(f"② D 원값 불일치 — {a['D_h']} (기대 172.5)")
        # ③ 가용 · 절단 · 가용 0
        if float(a["가용일"]) != 21.0 or float(a["달력평일"]) != 23:
            bad(f"③ 가용 불일치 — 평일 {a['달력평일']} 가용 {a['가용일']} (기대 23 / 21)")
        if abs(float(c["가용일(절단·부재 전)"]) - 11.09) > 0.01 or abs(float(c["가용일"]) - 9.09) > 0.01:
            bad(f"③ 분석 시점 절단 실패 — 절단 전 {c['가용일(절단·부재 전)']} 가용 {c['가용일']} (기대 11.09 / 9.09)")
        if abs(float(c["D_h"]) - 12 * 7.5) > 0.05:
            bad(f"③ D 원값이 분석 시점까지 잘리지 않음 — {c['D_h']} (기대 90.0)")
        exp_pct = round(EXP_C3 / (8 * 21) * 100, 1)
        if abs(float(a["C3_pct"]) - exp_pct) > 0.15:
            bad(f"③ 로드율 항등식 불일치 — {a['C3_pct']} (기대 {exp_pct})")
        z = by[("바_부재월", P, "2026-07")]
        if float(z["가용일"]) != 0.0 or z["C3_pct"] != "" or z["팀합계_사용"] != "":
            bad(f"③ 가용 0 인 달 처리 — 가용 {z['가용일']} pct '{z['C3_pct']}' 사용 '{z['팀합계_사용']}' (기대 0 / 빈칸 / 빈칸)")
        # C3 인원 = 가·나·다·마·아·사(6) · D 인원 = 가·나·다·라·자·차·아·사(8) — 바_부재월(가용 0)은 양쪽 모두 제외
        if "<td>6/8</td>" not in page:
            bad("③ 팀 합계 표의 2026-07 인원(C3/D) 이 '6/8' 이 아닙니다 — 가용 0·결손 인원이 분모에 섞였습니다")
        # ④ 결손 입력
        r = by[("라_메타만", P, "2026-07")]
        if r["C3_h"] != "" or r["A_h"] != "" or r["D_h"] == "":
            bad(f"④ signals 없는 기간 — C3 '{r['C3_h']}' A '{r['A_h']}' D '{r['D_h']}' (기대: C3·A 빈칸, D 있음)")
        r = by[("마_신호만", P, "2026-07")]
        if r["D_h"] != "" or r["C3_h"] == "":
            bad(f"④ mm_meta 없는 기간 — D '{r['D_h']}' C3 '{r['C3_h']}' (기대: D 빈칸, C3 있음)")
        for nm in ("자_빈신호", "차_열이름"):
            r = by[(nm, P, "2026-07")]
            if r["C3_h"] != "" or "signals 못 씀" not in r["비고"]:
                bad(f"④ {nm}: 읽을 수 없는 signals 가 0% 로 섞였습니다 — C3 '{r['C3_h']}' 비고 '{r['비고'][:60]}'")
        r = by[("아_엑셀", P, "2026-07")]
        if r["C3_h"] != a["C3_h"]:
            bad(f"④ cp949 signals 가 utf-8 과 다른 값 — {r['C3_h']} vs {a['C3_h']}")
        # ⑤ 겹치는 기간 — 과제 CSV 인별 MM_C3 합 == 월별 Y 행 C3_MM 합
        trs = read_csv(task_p[0]) if task_p else []
        mm_task = sum(float(x["MM_C3"] or 0) for x in trs if x["이름"] == "사_겹침")
        mm_used = sum(float(x["C3_MM"] or 0) for x in rows if x["이름"] == "사_겹침" and x["팀합계_사용"] == "Y")
        if abs(mm_task - mm_used) > 0.002 or mm_used <= 0:
            bad(f"⑤ 겹치는 기간 파일의 과제 MM 이중 계산 — 과제 {mm_task:.3f} vs 월별 사용 {mm_used:.3f}")
        used_months = sorted(x["월"] for x in rows if x["이름"] == "사_겹침" and x["팀합계_사용"] == "Y")
        if used_months != ["2026-06", "2026-07", "2026-08"]:
            bad(f"⑤ 겹친 달이 한 번씩만 대표되지 않음: {used_months}")
    # ⑥ 같은 초 재실행 → _2 로 비켜 감(총 6개)
    rc2 = R.main([T, "--now", "2026-09-20 12:00", "--quiet"])
    new2 = [x for x in sorted(os.listdir(T)) if x not in before]
    if rc2 != 0 or len(new2) != 6:
        bad(f"⑥ 같은 초 재실행 — rc {rc2}, 새 파일 {len(new2)}개(기대 6)")
    # ⑦ 팀 폴더 해석 — 없는 인자는 실패(폴백 없음) · 설치 폴더 자동 탐색은 teamdata 를 고른다
    before7 = sorted(os.listdir(T))
    with contextlib.redirect_stdout(io.StringIO()):          # 실패 안내문은 관문 출력에 섞지 않는다
        rc7 = R.main([os.path.join(T, "없는폴더"), "--now", "2026-09-20 12:00", "--quiet"])
    if rc7 == 0 or sorted(os.listdir(T)) != before7:
        bad(f"⑦ 없는 팀 폴더 인자가 실패하지 않았습니다(rc {rc7}) — 조용한 폴백 재발")
    inst = os.path.join(T, "install")
    os.makedirs(os.path.join(inst, "report"))
    os.makedirs(os.path.join(inst, "config"))
    shutil.copy2(os.path.join(ROOT, "team_recalc.py"), os.path.join(inst, "team_recalc.py"))
    make_signals(os.path.join(inst, "report", f"signals_{TAG}.csv"))
    make_meta(os.path.join(inst, "report", f"mm_meta_{TAG}.json"), D0, D1, True, 0.0, day_h)
    shutil.copytree(os.path.join(T, "가_LM20"), os.path.join(inst, "teamdata", "가_LM20"))
    R2 = load_module(os.path.join(inst, "team_recalc.py"))
    cwd0 = os.getcwd()
    os.chdir(inst)
    try:
        root7, how7 = R2.find_root(None)
    finally:
        os.chdir(cwd0)
    if os.path.normcase(root7 or "") != os.path.normcase(os.path.join(inst, "teamdata")):
        bad(f"⑦ 설치 폴더 자동 탐색이 teamdata 를 고르지 않음: {root7} ({how7})")
    if fail == 0:
        _say(f"[recalc] 계약 OK — 판 무관(A·B·C3 동일) · C3 {a['C3_h']}h={a['C3_pct']}% · 절단 가용 {c['가용일']}일·D {c['D_h']}h · "
             f"가용 0·결손 4종 분리 · 겹침 MM {mm_used:.3f} · 기존 보고서 무변경 · 재실행 6개 · 폴백 없음")
finally:
    shutil.rmtree(T, ignore_errors=True)
sys.exit(fail)
