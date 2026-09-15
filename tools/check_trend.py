# -*- coding: utf-8 -*-
r"""lint 관문 9 — 월간 활동 추이의 계약(수번째 반복 제보를 기계로 봉인).

반복 제보의 실체: ① "수십 시간인데 8h" — 선이 PC 이벤트 로그에 묶여, 롤오버로 파괴된 달은 영영
한 자릿수였다 ② "왜 집계기간 전체가 아니라 6월부터" — 분석 창이 화면 기간을 잘랐다 ③ 판정 밖
달의 막대가 통째로 비었다(all-or-nothing raw 폴백).

이 관문은 그 시나리오를 그대로 합성해(3~9월 산출물·회의 흔적 풍부 + PC 기록은 8월 이후만 +
분석은 6~9월만) ui.trend 를 실제로 돌려 검증한다:
  ① 추이 기간이 자료 시작(3월)까지 확장되는가
  ② 판정 기간 밖(3~5월) 막대가 수집 흔적으로 채워지는가
  ③ 주선(wk_h·근무 실측)이 PC 기록이 파괴된 달에도 수십 시간대인가 — MM 과 같은 산식
  ④ PC 가동(pc_h)은 그 달에 실제로 빈약한가(③이 pc 에 기대지 않았음의 교차 증명)
어느 하나가 깨지면 패키징 전에 실패한다 — 같은 제보가 조용히 재발할 수 없다.
사용: python tools/check_trend.py   (exit 0/1 · 저장소 무변경 — 임시 트리에서 돈다)
"""
import csv
import importlib.util
import json
import os
import shutil
import sys
import tempfile
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
fail = 0


def _say(msg):
    # ui/app.py 임포트가 sys.stdout 을 재래핑해 기존 핸들이 닫힌다(알려진 함정) — fd 1 에 직접 쓴다
    os.write(1, (msg + chr(10)).encode("utf-8", "replace"))


def bad(msg):
    global fail
    fail = 1
    _say("[trend] " + msg)


T = tempfile.mkdtemp(prefix="lm_trendgate_")
try:
    for d in ("core", "ui", "report", "config", "data/pc", "data/files", "data/outlook"):
        os.makedirs(os.path.join(T, *d.split("/")), exist_ok=True)
    shutil.copy2(os.path.join(ROOT, "ui", "app.py"), os.path.join(T, "ui", "app.py"))
    shutil.copy2(os.path.join(ROOT, "mine.py"), os.path.join(T, "mine.py"))
    for f in os.listdir(os.path.join(ROOT, "core")):
        if f.endswith(".py"):
            shutil.copy2(os.path.join(ROOT, "core", f), os.path.join(T, "core", f))
    shutil.copy2(os.path.join(ROOT, "config", "config.default.json"),
                 os.path.join(T, "config", "config.json"))

    TAG = "20260601-20260915"
    rep = os.path.join(T, "report")
    # 분석(판정 신호)은 6~9월만
    with open(os.path.join(rep, f"signals_{TAG}.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["time", "source", "who", "project", "activity", "weight", "text",
                    "model", "worktype", "detail", "judge"])
        for m in range(6, 10):
            for d in range(2, 26, 3):
                w.writerow([f"2026-{m:02d}-{d:02d}T10:00", "파일", "", "과제가", "설계", "1.0",
                            f"산출물{m}-{d}", "과제가", "개발", "설계", "AI"])
    with open(os.path.join(rep, f"mm_meta_{TAG}.json"), "w", encoding="utf-8") as f:
        json.dump({"period": ["2026-06-01", "2026-09-15"], "months": 3.5, "total_mm": 2.0}, f)
    # 근무 흔적(산출물 세션 + 회의)은 3월부터 풍부 — '수십 시간' 의 재료(파일·메일은 롤오버가 없다)
    with open(os.path.join(T, "data", "files", "files.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["mtime", "path", "author"])
        for m in range(3, 10):
            for d in range(2, 27):
                if date(2026, m, min(d, 28)).weekday() >= 5:
                    continue
                for hh in (9, 11, 14, 17):
                    w.writerow([f"2026-{m:02d}-{d:02d} {hh:02d}:10:00",
                                rf"D:\작업\문서_{m}_{d}_{hh}.docx", ""])
    with open(os.path.join(T, "data", "outlook", "calendar.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["start", "end", "subject", "accepted", "organizer"])
        for m in range(3, 10):
            for d in range(3, 27, 4):
                w.writerow([f"2026-{m:02d}-{d:02d} 10:00", f"2026-{m:02d}-{d:02d} 11:00",
                            "정례", "1", ""])
    # PC 기록은 8월 이후만(롤오버로 3~7월 파괴 — 제보 상황)
    with open(os.path.join(T, "data", "pc", "pc_on.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "on_hours", "first_on", "last_off", "night_hours", "weekend"])
        for m in (8, 9):
            for d in range(3, 26, 2):
                w.writerow([f"2026-{m:02d}-{d:02d}", "9.0", "08:30", "17:30", "0", "0"])

    core = os.path.join(T, "core")
    sys.path[:] = [core, T] + [p for p in sys.path if p not in (core, T)]
    spec = importlib.util.spec_from_file_location("app", os.path.join(T, "ui", "app.py"))
    A = importlib.util.module_from_spec(spec)
    sys.modules["app"] = A
    spec.loader.exec_module(A)

    per = A.dash_period({"period": ["2026-06-01", "2026-09-15"]}, None)
    ext = A.data_extent()
    lo = min(x for x in (per[0], ext[0]) if x)
    hi = max(x for x in (per[1], ext[1]) if x)
    if not (lo <= "2026-03-05"):
        bad(f"① 집계기간 확장 실패 — 분석 창({per})이 화면 기간을 자릅니다(전체 시작 {lo})")
    info = {}
    tr = A.trend(lo, hi, TAG, info=info)
    by = {w["label"]: w for w in tr}
    if "3월" not in by:
        bad(f"① 추이에 3월 버킷이 없습니다 — 기간 {info.get('period')}")
    else:
        bars_out = sum(by[m]["파일"] + by[m]["메일"] + by[m]["회의"] for m in ("3월", "4월", "5월") if m in by)
        if bars_out <= 0:
            bad("② 판정 기간 밖(3~5월) 막대가 비었습니다 — 수집 흔적 보완이 죽었습니다")
        wk4 = float(by.get("4월", {}).get("wk_h") or 0)
        pc4 = float(by.get("4월", {}).get("pc_h") or 0)
        if wk4 < 50.0:
            bad(f"③ 근무 실측 선이 무너졌습니다 — 4월 근무 {wk4:.1f}h(<50h). "
                "선이 다시 PC 로그에 묶였는지 확인하세요(수번째 제보 '수십 시간인데 8h' 재발)")
        if pc4 > 5.0:
            bad(f"④ 교차 증명 실패 — 파괴 시나리오인데 4월 pc_h={pc4:.1f}h(픽스처 오류?)")
        if fail == 0:
            _say(f"[trend] 계약 OK — 기간 {lo}~{hi[:10]} · 3~5월 막대 {bars_out}건(수집 흔적) · "
                 f"4월 근무 {wk4:.1f}h(PC {pc4:.1f}h — 파괴돼도 선은 실측)")
finally:
    shutil.rmtree(T, ignore_errors=True)
sys.exit(fail)
