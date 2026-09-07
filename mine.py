# -*- coding: utf-8 -*-
"""
mine.py — 개인 PC 수집 데이터에서 업무 로드를 추출한다.

  python mine.py <수집데이터폴더> --from 2026-05-19 --to 2026-08-17 [--name 홍길동] [--func System]

출력: 화면 표 + report\\mm_rows_<기간>.csv ([매핑데이터] 형식)
"""
import csv
import json
import io
import os
import sys
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "core"))
from progress import progress  # noqa: E402
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, errors="replace", encoding=(
        (sys.stdout.encoding or "utf-8") if sys.stdout.isatty() else "utf-8"))  # 콘솔(bat)=콘솔 코드페이지 · 파이프(UI)=utf-8
import extract  # noqa: E402

ROOT = os.path.dirname(os.path.abspath(__file__))
# 개인 파일 제외 — 리포트·AI 프롬프트에 실리면 안 되는 경로 키워드
EXCLUDE = ["개인", "사생활", "가족", "취미", "이력서", "면접", "취준", "자소서", "이직",
           "downloads", "다운로드", "temp", "임시", "공부", "인강"]


def arg(flag, dflt=""):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else dflt


def known_projects(cfg):
    """규칙 기준선이 쓸 과제 이름 — config 힌트 + UI 지정 + **이전 판정에서 발견된 과제**.
    한 번이라도 판정에 성공했다면 그 이름이 재사용되므로, 이후 판정이 실패해도 화면이
    파일명 조각이 아니라 과제명으로 묶인다(실측 대응)."""
    import glob as _glob
    out, idx = [], {}

    def add(name, match=()):
        name = str(name or "").strip()
        if not name or name == "공통":
            return
        alts = [str(k).strip() for k in (match or []) if str(k).strip()]
        key = name.lower()
        if key in idx:                    # 같은 과제가 여러 출처면 별칭을 합친다
            cur = out[idx[key]][1]
            for a in alts:
                if a.lower() not in {x.lower() for x in cur}:
                    cur.append(a)
            return
        idx[key] = len(out)
        out.append((name, alts))          # 별칭은 이름이 아니라 '매칭어'로

    for p in extract.cfg_list(cfg, "projects"):
        add(p)
    try:
        sys.path.insert(0, os.path.join(ROOT, "core"))
        import projmap
        for p in projmap.load_user_projects(ROOT):
            add(p.get("name"), p.get("match") or [])
    except Exception as e:
        print(f"[mine] 지정 과제 로드 건너뜀({type(e).__name__})")
    try:
        fs = sorted(_glob.glob(os.path.join(ROOT, "report", "entities_*.json")),
                    key=os.path.getmtime, reverse=True)
        # 최신순으로 훑되, 판정이 실제로 성공한 체계를 만나면 그것을 쓴다.
        # (직전 실행이 실패해 규칙 토큰만 남겼어도, 그 이전의 성공 체계를 재사용한다)
        for fp in fs:
            try:
                ent = json.load(open(fp, encoding="utf-8-sig"))
            except (OSError, ValueError):
                continue
            models = ent.get("models") or []
            if not any(isinstance(m, dict) and (m.get("match") or m.get("obs"))
                       for m in models):
                continue                      # 규칙 폴백 산출물 — 건너뛴다
            for m in models:
                if isinstance(m, dict):
                    add(m.get("name"), m.get("match") or [])
            break
    except (OSError, ValueError, AttributeError):
        pass
    return out


def _locked_writes(jobs):
    """결과 파일 4종을 임시파일에 쓴 뒤 교체한다. Excel 등이 파일을 열어두면(Windows 잠금)
    교체가 PermissionError 로 실패하는데, 예전엔 거기서 통째로 죽어 mm_rows 만 새것이고
    meta 는 낡은 반쪽 상태가 됐다(실측: 로드율 '—' + '종료' 배너). 잠긴 파일은 건너뛰고
    나머지는 마저 쓴 뒤, 무엇이 잠겼는지 돌려준다.
    임시파일 이름에는 pid 를 붙인다 — 같은 사본에서 분석이 동시에 돌면(UI 재실행·팀 일괄) 같은
    .tmp 를 서로 지우고 덮어써 한쪽이 '열려 있음' 으로 실패했다(실측 exit 4)."""
    import glob as _glob
    import time as _time
    locked = []
    for path, writer in jobs:
        # 죽은 실행이 남긴 임시파일만 정리(10분 이상) — 지금 동시에 도는 다른 분석의 것은 건드리지 않는다
        for old in _glob.glob(_glob.escape(path) + ".*.tmp"):
            try:
                if _time.time() - os.path.getmtime(old) > 600:
                    os.remove(old)
            except OSError:
                pass
        tmp = f"{path}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding=("utf-8-sig" if path.endswith(".csv") else "utf-8"),
                  newline=("" if path.endswith(".csv") else None)) as f:
            writer(f)
        try:
            os.replace(tmp, path)
        except OSError:
            locked.append(os.path.basename(path))
            try:
                os.remove(tmp)
            except OSError:
                pass
    return locked


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__)
        return 2
    data_dir = args[0]
    d0 = date.fromisoformat(arg("--from", "2026-01-01"))
    d1 = date.fromisoformat(arg("--to", date.today().isoformat()))
    owner = arg("--name", os.environ.get("USERNAME", ""))
    func = arg("--func", "")
    months = max(0.5, (d1 - d0).days / 30.44)

    cfg = extract.load_cfg()
    exclude = sorted(set(EXCLUDE) | {str(k) for k in extract.cfg_list(cfg, "excludePathKeywords")
                                     if str(k).strip()})
    progress("신호 수집", 0, 3)
    sig, meta = extract.load_signals(data_dir, d0, d1, exclude, cfg)
    if not sig:
        print(f"[mine] 신호 0건 — 수집 폴더 확인: {data_dir}")
        return 2                     # 2 = 신호 없음 (예외 사망(3)과 구분 — run.py 가 다르게 안내)
    print(f"[mine] {d0}~{d1} ({months:.1f}개월) · 신호 {len(sig)}건")
    print("[출처] 채택: " + ", ".join(f"{k} {v}" for k, v in
                                    sorted(meta["counted"].items(), key=lambda x: -x[1])))
    if meta["excluded"]:
        print("[출처] 제외: " + ", ".join(f"{k} {v}" for k, v in meta["excluded"].items())
              + "   ← CC·단체발송·비업무는 본인 업무로 계상하지 않음")

    # MM v4: 투입 MM(실제 투입시간, 상한 없음) 과 가용 MM(연차를 일자에서 뺀 값)을 나란히 낸다.
    # 로드율 = 투입 ÷ 가용. PC 가동시간은 시간의 근거가 아니라 그날 일했는지 교차확인과
    # 초과근무 산정에만 쓴다 (PC 시간만으로 재면 MM이 실제의 1/5로 붕괴).
    progress("신호 수집", 1, 3)
    absence = dict(extract.absence_days(data_dir, d0, d1))
    day_hours, hinfo = extract.day_work_hours(data_dir, sig, d0, d1, cfg,
                                              file_times=meta.get("file_times"))
    # 부재 추정(PC 도 흔적도 없는 평일)은 달력 근태와 합쳐 가용에서 차감한다 (LM22). 추정일은 미등록 공휴일처럼
    # 그 달 평일수(투입 MM 분모)에서도 뺀다(A31) — inferred 로 따로 넘긴다.
    inferred = hinfo.pop("inferred_absence", {}) or {}
    absence.update(inferred)
    # 잘못된 설정값은 죽지 않고 기본값으로 대체됐다 — 무엇이 무시됐는지 사용자에게 보인다
    cfg_warns = list(dict.fromkeys(list(meta.get("config_warnings") or [])
                                   + list(hinfo.get("config_warnings") or [])))
    for w in cfg_warns:
        print(f"[설정] {w}")
    # 미래 평일·오늘 잔여는 가용이 아니다(A34) — future_days·today_fraction 이 hinfo 에 남는다
    mm_months, total_mm, avail_mm = extract.mm_from_hours(
        day_hours, d0, d1, cfg=cfg, absence=absence, inferred=inferred, info=hinfo)
    load_pct = (total_mm / avail_mm * 100) if avail_mm else 0.0
    print(f"[MM] 투입 {total_mm:.2f} MM ({sum(day_hours.values()):.0f}h) / "
          f"가용 {avail_mm:.2f} MM  →  로드율 {load_pct:.0f}%")
    print(f"     부재 {hinfo['absence_days']}일 차감 · 초과근무 {hinfo['overtime_h']:.0f}h · "
          f"주말근무 {hinfo['weekend_days']}일 · 야근일 {hinfo['night_days']}일 · "
          f"PC가동 하한 보정 {hinfo.get('pc_floor_h', 0):.0f}h/{hinfo.get('pc_floor_days', 0)}일")
    print(f"     점심 차감 {hinfo.get('lunch_deducted_h', 0):.0f}h · "
          f"저녁 식사 차감 {hinfo.get('dinner_deducted_h', 0):.1f}h · "
          f"저녁·새벽 인정 {hinfo.get('evening_credit_h', 0):.0f}h · "
          f"주말 산출물 창 {hinfo.get('weekend_window_h', 0):.0f}h · "
          f"수동흔적만 {hinfo.get('floor_blocked_passive_days', 0)}일(하한 미적용) · "
          f"부재 추정 {hinfo.get('inferred_absence_days', 0)}일(가용 차감) · "
          f"미래시각 폐기 {hinfo.get('future_signals_dropped', 0)}건")
    print(f"     상한 없음(하루 24h 물리 한계만) · 이상치 {len(hinfo.get('anomalies') or [])}일 · "
          f"16h 초과 {len(hinfo.get('long_days') or [])}일 · "
          f"부재일 흔적 {hinfo.get('absent_worked_h', 0):.1f}h"
          + ("   ★ 발신 메일의 60% 이상이 00~08시 — 시각이 UTC 로 기록된 듯합니다. "
             "config.mm.mailTimeOffsetH(예: 9) 로 보정하세요" if hinfo.get("utc_suspect") else ""))
    # LM22 2차 — 측정 방식·신뢰도(D5)와 새 보정(A6·A9·A13·A33·D3·D4·D7·A34) 한 줄씩
    ms = hinfo.get("measure") or {}
    cv = hinfo.get("coverage") or {}
    grade = {"reliable": "신뢰", "caution": "주의", "unreliable": "측정 불충분"}.get(cv.get("grade"), "–")
    print(f"     측정 {ms.get('method', '–')} · 샘플러 {ms.get('sampler_days', 0)}일 / PC 하한 {ms.get('pc_floor_days', 0)}일 / "
          f"흔적 창 {ms.get('trace_window_days', 0)}일 / 종일 행사 {ms.get('offsite_days', 0)}일 / "
          f"수동 기록 {ms.get('manual_days', 0)}일 · PC 기록 평일 {round((cv.get('pc_weekday_ratio') or 0) * 100)}% · "
          f"신뢰도 {grade}" + (" — " + " · ".join(cv.get("reasons") or []) if cv.get("reasons") else ""))
    extra_bits = []
    if hinfo.get("offsite_days"):
        extra_bits.append(f"종일 행사(출장·현장·교육) {hinfo['offsite_days']}일 {hinfo.get('offsite_h', 0):.1f}h 인정")
    if hinfo.get("manual_days"):
        extra_bits.append(f"수동 기록 {hinfo['manual_days']}일 {hinfo.get('manual_h', 0):.1f}h 인정")
    if hinfo.get("sampler_stuck_days"):
        extra_bits.append(f"샘플러 idle 고착 {hinfo['sampler_stuck_days']}일(폐기 → PC 하한)")
    if hinfo.get("sampler_bridge_h"):
        extra_bits.append(f"샘플러 공백 다리 {hinfo['sampler_bridge_h']:.1f}h")
    if hinfo.get("flex_edge_h"):
        extra_bits.append(f"시차 근무 창 밖 인정 {hinfo['flex_edge_h']:.1f}h")
    if hinfo.get("weekend_pc_days"):
        extra_bits.append(f"주말 PC 창 인정 {hinfo['weekend_pc_days']}일")
    if hinfo.get("pc_record_missing_days"):
        extra_bits.append(f"PC 기록 결측 평일 {hinfo['pc_record_missing_days']}일"
                          f"(흔적 창 폴백 {hinfo.get('trace_window_h', 0):.1f}h/{hinfo.get('trace_window_days', 0)}일)")
    pcc = hinfo.get("pc_coverage_by_month") or {}
    low = [k for k, v in sorted(pcc.items()) if v < 0.4]
    if low:
        extra_bits.append("PC 기록 40% 미만(하한 미적용) " + ", ".join(f"{k} {round(pcc[k] * 100)}%" for k in low))
    if hinfo.get("future_days"):
        extra_bits.append(f"미래 평일 {hinfo['future_days']}일 가용 제외")
    if hinfo.get("today_fraction") is not None:
        extra_bits.append(f"오늘 {round(hinfo['today_fraction'] * 100)}% 가용")
    if extra_bits:
        print("     " + " · ".join(extra_bits))
    # 야간 해석(솔버) 인정(S4-N1) — 밤 단위. 값이 0 이면 줄 자체를 내지 않는다
    if hinfo.get("sim_night_h") or hinfo.get("sim_night_days"):
        print(f"     야간 해석 인정 {hinfo.get('sim_night_h', 0):.1f}h · {hinfo.get('sim_night_days', 0)}일"
              f"(상한 {hinfo.get('sim_night_capped_days', 0)}일 · "
              f"재실행으로 상한 해제 {hinfo.get('sim_night_unlocked_days', 0)}일 · "
              f"PC 밖 {hinfo.get('sim_night_remote_h', 0):.1f}h)")
    progress("신호 수집", 2, 3)
    items, assigns = extract.build_items2(sig, known_projects(cfg))
    rows = extract.to_rows(items, total_mm, owner, func)
    progress("신호 수집", 3, 3)
    # 총계는 [MM] 줄과 같은 total_mm 으로 — 행별 반올림 합(7.585→'7.58')과 총계('7.59')가 어긋나던 표시 결함
    print(f"[mine] 업무 항목 {len(rows)}개 · 총 {total_mm:.2f} MM (주40h 근무일 기준)\n")

    print(f"{'Level 2 (프로젝트)':26s} {'Level 3 (활동)':16s} {'비중':>6s} {'MM':>6s} {'일수':>4s} 확신 근거")
    print("-" * 108)
    for r in rows[:20]:
        print(f"{r['Level 2'][:25]:26s} {r['Level 3'][:15]:16s} "
              f"{r['share']*100:5.1f}% {r['mm']:6.2f} {r['활동일수']:4d}  {r['확신도']}  {r['근거'][:34]}")

    out_dir = os.path.join(ROOT, "report")
    os.makedirs(out_dir, exist_ok=True)
    tag2 = f"{d0:%Y%m%d}-{d1:%Y%m%d}"
    out = os.path.join(out_dir, f"mm_rows_{tag2}.csv")
    ev = os.path.join(out_dir, f"evidence_{tag2}.md")
    sp = os.path.join(out_dir, f"signals_{tag2}.csv")
    meta_path = os.path.join(out_dir, f"mm_meta_{tag2}.json")
    cols = ["Function", "Level 1", "제품", "Level 2", "Level 3", "이름", "상세설명",
            "share", "mm", "근거", "확신도", "활동일수"]

    def _w_rows(f):
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            row = {c: r.get(c, "") for c in cols}
            row["Level 3"] = extract._one_line(row.get("Level 3"))   # S2: 세부업무 이름의 개행·탭은 셀·프롬프트를 가른다
            w.writerow(row)

    def _w_ev(f):
        for r in rows:
            f.write(f"## {r['Level 2']} / {r['Level 3']} — {r['mm']:.2f} MM ({r['share']*100:.1f}%)\n")
            for x in r["evidence"]:
                f.write(f"- {x}\n")
            f.write("\n")

    def _sig_text(src, text):
        """text 열은 100자 계약. 해석 출력 대표('이름 | 폴더:라벨 (해석 출력 N건)')는 폴더 라벨이 곧 신호라 꼬리(폴더·규모)를
        남기고 이름 쪽을 줄인다(VF-H3 — 긴 결과 파일명이 라벨을 잘라내면 판정 뒤 재산정이 그 뭉치를 찾지 못했다)."""
        s = extract._one_line(text, None)
        if len(s) <= 100:
            return s
        if src == "파일(해석출력)":
            i = s.rfind(" | 폴더:")
            if i > 0 and len(s) - i < 100:
                tail = s[i:]
                return s[:100 - len(tail)].rstrip() + tail
        return s[:100]

    def _w_sig(f):
        w = csv.writer(f)
        w.writerow(["time", "source", "who", "project", "activity", "weight", "text"])
        for t, src, text, wt, who, proj, act in assigns:
            # S2: activity·text 는 한 줄로(개행·탭·앞뒤 공백 정규화) — 열 이름·text ≤100자 계약은 그대로
            w.writerow([t.strftime("%Y-%m-%d %H:%M"), src, who, proj, extract._one_line(act), round(wt, 3),
                        _sig_text(src, text)])

    import json

    def _w_meta(f):
        # measure·coverage·cfg_used(D5)는 mm_basis 에도 남고 최상위에도 싣는다 — 팀 취합(teamup)·리포트·UI 가 읽는다
        json.dump({"period": [d0.isoformat(), d1.isoformat()], "months": round(months, 2),
                   "signals": len(sig), "counted": meta["counted"],
                   "excluded": meta["excluded"], "weights": meta["weights"],
                   "total_mm": total_mm, "avail_mm": avail_mm,
                   "load_pct": round(load_pct, 1), "mm_months": mm_months,
                   "config_warnings": cfg_warns,
                   "worked_h": round(sum(day_hours.values()), 1),
                   "measure": hinfo.get("measure"), "coverage": hinfo.get("coverage"),
                   "cfg_used": hinfo.get("cfg_used"), "tool_usage": hinfo.get("tool_usage"),
                   "mm_basis": hinfo,
                   "day_hours": {k.isoformat(): round(v, 2) for k, v in day_hours.items()}},
                  f, ensure_ascii=False, indent=1)

    locked = _locked_writes([(out, _w_rows), (ev, _w_ev), (sp, _w_sig), (meta_path, _w_meta)])
    if locked:
        print(f"[mine] 저장 실패(다른 프로그램에서 열려 있음 — Excel 등, 또는 같은 폴더에서 다른 분석이 "
              f"동시에 실행 중): {', '.join(locked)}")
        print("       그 파일을 닫거나 다른 분석이 끝난 뒤 다시 실행하세요 — 닫지 않으면 화면이 낡은 값을 보여줍니다.")
        return 4                          # 4 = 결과 파일 잠김 (원인 구분용)
    print(f"\n[mine] 행 → {out}\n[mine] 근거 → {ev}\n[mine] 출처 메타 → {meta_path}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:                # 어떤 예외든 '신호 0건'으로 오진되지 않게 코드를 구분한다
        import traceback
        traceback.print_exc()        # 전문은 UI 로그로
        print(f"[mine] 오류로 중단: {sys.exc_info()[0].__name__}: {sys.exc_info()[1]}")
        sys.exit(3)                  # 3 = 예외 사망
