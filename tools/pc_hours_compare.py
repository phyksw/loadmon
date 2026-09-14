# -*- coding: utf-8 -*-
r"""PC 가동시간 비교 — 이 PC 에서 **LM20 수집기**와 **현재 수집기**를 같은 기간으로 나란히 돌려 달별 시간을 비교한다.

왜: "같은 PC 에서 LM20 이 더 많은 시간을 낸다" 는 제보는 그 PC 의 이벤트 로그·브라우저 기록·창 샘플러에 달려 있어
    다른 PC 에서는 재현할 수 없다. 이 도구는 그 PC 에서 두 판본을 **실제로** 돌려 어느 단계(이벤트 로그 / 보강 /
    저장된 data / 화면 선)에서 시간이 갈라지는지 숫자로 보여 준다.

안전: 실제 data\ 는 읽기만 한다. 두 수집기는 %TEMP%\lm_pc_compare\ 의 임시 폴더에서 돌고 끝나면 지운다.
      결과(report\pc_hours_compare.txt)에는 **날짜별·달별 시간과 건수만** 있다 — URL·창 제목·메일 내용·사람 이름 없음.
      LM20 수집기 원본은 tools\lm20_ref\*.txt (LoadMonitor20 0551 풀패키지의 collect\ 그대로, 확장자만 .txt).

  python tools\pc_hours_compare.py                         (올해 1월 1일 ~ 오늘)
  python tools\pc_hours_compare.py --from 2026-06-01 --to 2026-09-14
"""
import csv
import glob
import io
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import date, datetime, timedelta

if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, errors="replace", encoding=(
        (sys.stdout.encoding or "utf-8") if sys.stdout.isatty() else "utf-8"))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
REF = os.path.join(ROOT, "tools", "lm20_ref")
WORK = os.path.join(tempfile.gettempdir(), "lm_pc_compare")
NO_WIN = 0x08000000
EPOCH = 11644473600
LINES = []


def say(s=""):
    print(s, flush=True)
    LINES.append(s)


def arg(flag, d=""):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else d


def month_sum(pc_on_path, d0, d1):
    """pc_on.csv → ({'2026-06': h}, 기록 있는 날 수)"""
    out, days = {}, 0
    try:
        with open(pc_on_path, encoding="utf-8-sig", errors="replace") as f:
            for r in csv.DictReader(f):
                k = str(r.get("date") or "")[:10]
                if not (d0 <= k <= d1):
                    continue
                try:
                    h = float(r.get("on_hours") or 0)
                except ValueError:
                    continue
                out[k[:7]] = out.get(k[:7], 0.0) + h
                days += 1
    except OSError:
        pass
    return out, days


def run_tree(name, hist_src, hints_src, d0, d1):
    """임시 트리에 수집기 두 개를 두고 이벤트 → (스냅샷) → 보강 순서로 돌린다(run.py 와 같은 순서)."""
    t = os.path.join(WORK, name)
    os.makedirs(os.path.join(t, "collect"), exist_ok=True)
    os.makedirs(os.path.join(t, "data", "pc"), exist_ok=True)
    shutil.copyfile(hist_src, os.path.join(t, "collect", "Get-PcOnHistory.ps1"))
    shutil.copyfile(hints_src, os.path.join(t, "collect", "Get-PcOnHints.py"))
    act = os.path.join(DATA, "activity")
    if os.path.isdir(act):                       # 창 샘플러 시각은 보강 재료 — 두 판본에 같은 사본을 준다
        shutil.copytree(act, os.path.join(t, "data", "activity"), dirs_exist_ok=True)
    env = dict(os.environ, PYTHONIOENCODING="utf-8", LM_NO_BROWSER="1")
    t0 = time.time()
    p1 = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                         os.path.join(t, "collect", "Get-PcOnHistory.ps1"), "-From", d0, "-To", d1],
                        capture_output=True, cwd=t, env=env, creationflags=NO_WIN, timeout=600)
    ev_log = (p1.stdout or b"").decode("utf-8", "replace").strip().splitlines()
    pc_on = os.path.join(t, "data", "pc", "pc_on.csv")
    ev_only = os.path.join(t, "data", "pc", "pc_on_events_only.csv")
    if os.path.exists(pc_on):
        shutil.copyfile(pc_on, ev_only)
    p2 = subprocess.run([sys.executable, os.path.join(t, "collect", "Get-PcOnHints.py"), "--from", d0, "--to", d1],
                        capture_output=True, cwd=t, env=env, creationflags=NO_WIN, timeout=600)
    hint_log = (p2.stdout or b"").decode("utf-8", "replace").strip().splitlines()
    return {"events": month_sum(ev_only, d0, d1), "all": month_sum(pc_on, d0, d1),
            "rc": (p1.returncode, p2.returncode), "sec": round(time.time() - t0, 1),
            "ev_log": [x for x in ev_log if x.startswith("[pc-on]")][-4:],
            "hint_log": [x for x in hint_log if x.startswith("[pc-hint]")][-4:]}


def browser_counts(d0, d1):
    """브라우저 방문 시각 달별 건수 — 전체 / '동기화 표식'(visit_source≠1 또는 기기 GUID) 붙은 것. URL 은 읽지 않는다."""
    la = os.environ.get("LOCALAPPDATA", "")
    t0 = datetime.strptime(d0, "%Y-%m-%d")
    t1 = datetime.strptime(d1, "%Y-%m-%d") + timedelta(days=1)
    res = []
    for base, brand in ((os.path.join(la, "Microsoft", "Edge", "User Data"), "Edge"),
                        (os.path.join(la, "Google", "Chrome", "User Data"), "Chrome")):
        for h in glob.glob(os.path.join(base, "*", "History")):
            tmp = os.path.join(tempfile.gettempdir(), "lm_pccmp_hist")
            by, oldest = {}, None
            try:
                shutil.copy2(h, tmp)
                con = sqlite3.connect(tmp)
                try:
                    cols = {r[1] for r in con.execute("PRAGMA table_info(visits)")}
                    has_vs = bool(con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='visit_source'").fetchone())
                    q = ("SELECT v.visit_time, " + ("s.source" if has_vs else "NULL") + ", "
                         + ("COALESCE(v.originator_cache_guid,'')" if "originator_cache_guid" in cols else "''")
                         + " FROM visits v" + (" LEFT JOIN visit_source s ON s.id=v.id" if has_vs else ""))
                    for vt, src, guid in con.execute(q):
                        try:
                            t = datetime.fromtimestamp(vt / 1e6 - EPOCH)        # 로컬 시각
                        except (OSError, OverflowError, ValueError):
                            continue
                        oldest = t if oldest is None or t < oldest else oldest
                        if not (t0 <= t < t1):
                            continue
                        m = t.strftime("%Y-%m")
                        a = by.setdefault(m, [0, 0])
                        a[0] += 1
                        if (src is not None and src != 1) or guid:
                            a[1] += 1
                finally:
                    con.close()
            except Exception as e:  # noqa: BLE001 - 잠김·정책 차단이면 그 사실만 적는다
                res.append((f"{brand}\\{os.path.basename(os.path.dirname(h))}", None, f"읽기 실패({type(e).__name__})"))
                continue
            finally:
                try:
                    os.remove(tmp)
                except OSError:
                    pass
            res.append((f"{brand}\\{os.path.basename(os.path.dirname(h))}", by,
                        oldest.strftime("%Y-%m-%d") if oldest else "-"))
    return res


def sampler_counts(root, d0, d1):
    by = {}
    for p in glob.glob(os.path.join(root, "activity", "activity_*.csv")):
        try:
            with open(p, encoding="utf-8-sig", errors="replace") as f:
                for r in csv.DictReader(f):
                    k = str(r.get("time") or "")[:10]
                    if d0 <= k <= d1:
                        by[k[:7]] = by.get(k[:7], 0) + 1
        except OSError:
            continue
    return by


def oldest_event():
    try:
        p = subprocess.run(["powershell", "-NoProfile", "-Command",
                            "(Get-WinEvent -LogName System -MaxEvents 1 -Oldest).TimeCreated.ToString('yyyy-MM-dd HH:mm')"],
                           capture_output=True, creationflags=NO_WIN, timeout=60)
        return (p.stdout or b"").decode("utf-8", "replace").strip() or "읽기 실패"
    except (OSError, subprocess.SubprocessError):
        return "읽기 실패"


def screen_line(d0, d1):
    """화면 월간 추이의 PC 선이 쓰는 값 — core/extract.pc_daily(본 PC + 추가PC) 를 달별로 더한다."""
    try:
        sys.path.insert(0, os.path.join(ROOT, "core"))
        import extract
        pc = extract.pc_daily(DATA, date.fromisoformat(d0), date.fromisoformat(d1))[0]
        out = {}
        for dd, v in pc.items():
            k = dd.isoformat()
            if d0 <= k <= d1:
                out[k[:7]] = out.get(k[:7], 0.0) + float(v[0] or 0)
        return out, len([1 for dd in pc if d0 <= dd.isoformat() <= d1])
    except Exception as e:  # noqa: BLE001
        return {"오류": f"{type(e).__name__}: {str(e)[:80]}"}, 0


def months(d0, d1):
    y, m = int(d0[:4]), int(d0[5:7])
    out = []
    while (y, m) <= (int(d1[:4]), int(d1[5:7])):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


MAIL_MIN = {"메일(발신)": 20, "메일(수신)": 5, "메일(CC)": 3, "메일(수신전용)": 2, "메일(발신·일자)": 0}
PASSIVE_MAX_MIN = 60.0        # core/extract.PASSIVE_DAY_MAX_MIN — 수동 신호(수신·CC)만으로 만든 시간의 하루 상한


def mail_rows(d0, d1):
    r"""본 PC + 추가PC 의 mail.csv 를 읽어 (달, 구분, 시각 정밀도) 별 통수. 제목·주소·사람 이름은 읽지 않는다."""
    roots = [DATA] + sorted(p for p in glob.glob(os.path.join(DATA, "추가PC", "*")) if os.path.isdir(p))
    per_month, per_day, n_all = {}, {}, 0
    for rt in roots:
        p = os.path.join(rt, "outlook", "mail.csv")
        if not os.path.isfile(p):
            continue
        try:
            with open(p, encoding="utf-8-sig", errors="replace") as f:
                for r in csv.DictReader(f):
                    t = str(r.get("time") or "")
                    k = t[:10]
                    if not (d0 <= k <= d1):
                        continue
                    n_all += 1
                    box = "발신" if (r.get("box") or "").strip() == "sent" else "수신"
                    prec = (r.get("time_precision") or "").strip().lower()
                    prec = "날짜만" if prec == "date" else ("시각" if len(t) >= 16 else "시각(열 없음)")
                    a = per_month.setdefault(k[:7], {})
                    a[(box, prec)] = a.get((box, prec), 0) + 1
                    per_day.setdefault(k, [0, 0])[0 if box == "발신" else 1] += 1
        except OSError:
            continue
    return per_month, per_day, n_all


def mail_source():
    out = []
    for rt in [DATA] + sorted(p for p in glob.glob(os.path.join(DATA, "추가PC", "*")) if os.path.isdir(p)):
        p = os.path.join(rt, "outlook", "mail_source.json")
        if not os.path.isfile(p):
            continue
        try:
            with open(p, encoding="utf-8-sig") as f:
                j = json.load(f)
        except (OSError, ValueError):
            continue
        name = "본 PC" if rt == DATA else "추가PC:" + os.path.basename(rt)
        out.append((name, str(j.get("source") or "?"), bool(j.get("coverage_complete", True)),
                    list(j.get("uncovered_months") or [])))
    return out


def latest_meta(d0, d1):
    """가장 최근 분석 결과(mm_meta_*.json) — 메일 관련 제외 건수와 근무시간 산정 근거."""
    best, best_mt = None, -1.0
    for p in glob.glob(os.path.join(ROOT, "report", "mm_meta_*.json")):
        try:
            mt = os.path.getmtime(p)
        except OSError:
            continue
        if mt > best_mt:
            best, best_mt = p, mt
    if not best:
        return None, None
    try:
        with open(best, encoding="utf-8-sig") as f:
            return os.path.basename(best), json.load(f)
    except (OSError, ValueError):
        return os.path.basename(best), None


def mail_section(d0, d1):
    say("")
    say("■ 메일 — 수집 경로 · 시각 · 시간 계상")
    src = mail_source()
    if not src:
        say("  mail_source.json 이 없습니다 — 아직 메일 수집을 돌리지 않았습니다.")
    for name, s, complete, unc in src:
        label = {"com": "Outlook 앱(COM) — 시각 정확", "index": "Windows 검색 색인(앱 없이) — 시각 정확",
                 "owa": "Outlook 웹(전용 Edge) — 어제 이전은 시각이 날짜만일 수 있음",
                 "web": "Outlook 웹(전용 Edge) — 어제 이전은 시각이 날짜만일 수 있음",
                 "copilot": "Copilot 왕복 — 시각이 날짜만일 수 있음"}.get(s, s)
        say(f"  [{name}] 수집 경로: {label}" + ("" if complete else f" · 미수집 달 {len(unc)}개: {', '.join(unc[:8])}"))
    per_month, per_day, n_all = mail_rows(d0, d1)
    if not n_all:
        say("  기간 안 메일 0통 — 수집이 안 됐거나 기간이 어긋났습니다.")
        return
    say(f"  기간 안 메일 {n_all:,}통 · 달별(발신/수신, 시각 있음 → 날짜만):")
    for m in sorted(per_month):
        a = per_month[m]
        snd_t = a.get(("발신", "시각"), 0) + a.get(("발신", "시각(열 없음)"), 0)
        snd_d = a.get(("발신", "날짜만"), 0)
        rcv_t = a.get(("수신", "시각"), 0) + a.get(("수신", "시각(열 없음)"), 0)
        rcv_d = a.get(("수신", "날짜만"), 0)
        say(f"    {m}  발신 {snd_t:>5,} / 날짜만 {snd_d:>5,}   수신 {rcv_t:>6,} / 날짜만 {rcv_d:>6,}")
    d_only = sum(v for a in per_month.values() for (b, p), v in a.items() if p == "날짜만")
    if d_only:
        say(f"  ※ 시각이 '날짜만' 인 메일 {d_only:,}통은 **시간 계상에서 빠집니다**(정오로 두고 근거에서 제외 — A38).")
        say("     Outlook 앱(클래식)을 켠 상태로 [분석 실행]을 하면 앱 경로(COM)가 정확한 시각으로 다시 씁니다.")
    # 수동 상한이 하루에 얼마나 잘라내는지 — 규칙 상수로 계산(수신·CC 를 수신 5분으로 본 근사)
    cut_days, cut_min = 0, 0.0
    for _d, (_n_snd, n_rcv) in sorted(per_day.items()):
        passive = n_rcv * MAIL_MIN["메일(수신)"]
        if passive > PASSIVE_MAX_MIN:
            cut_days += 1
            cut_min += passive - PASSIVE_MAX_MIN
    say(f"  수신 메일만으로 만든 시간의 하루 상한({PASSIVE_MAX_MIN:.0f}분)에 걸리는 날: {cut_days}일"
        + (f" · 잘리는 양 합계 약 {cut_min / 60:.1f}h (수신 1통 {MAIL_MIN['메일(수신)']}분 기준 근사)" if cut_days else ""))
    say("  (발신 메일은 능동 흔적이라 상한이 없고, 앞뒤 작업과 45분 안이면 한 세션으로 이어집니다.)")
    name, meta = latest_meta(d0, d1)
    if not meta:
        say("  분석 결과(mm_meta)가 없어 실제 계상 시간은 못 보여 줍니다 — [분석 실행] 뒤 다시 돌려 주세요.")
        return
    basis = meta.get("mm_basis") or {}
    say(f"  최근 분석({name}) 기준: 근무시간 합 {meta.get('worked_h', '?')}h · 투입 {meta.get('total_mm', '?')} MM"
        f" · 로드율 {meta.get('load_pct', '?')}%")
    for k, lbl in (("passive_capped_days", "수신 메일 상한에 걸린 날"), ("pc_floor_days", "PC 가동 하한이 적용된 날"),
                   ("lunch_deducted_h", "점심 차감(h)"), ("dinner_deducted_h", "저녁 차감(h)"),
                   ("pc_record_missing_days", "PC 기록이 없던 날")):
        if k in basis:
            say(f"    · {lbl}: {basis[k]}")
    exc = meta.get("excluded") or {}
    mail_exc = {k: v for k, v in exc.items() if any(x in k for x in ("메일", "공지", "단체", "시각 형식"))}
    if mail_exc:
        say("    · 메일에서 제외된 건수: " + " · ".join(f"{k} {v:,}" for k, v in sorted(mail_exc.items(), key=lambda x: -x[1])))


def main():
    today = date.today()
    d0 = arg("--from") or today.replace(month=1, day=1).isoformat()
    d1 = arg("--to") or today.isoformat()
    if not (os.path.isfile(os.path.join(REF, "Get-PcOnHistory.ps1.txt")) and os.path.isfile(os.path.join(REF, "Get-PcOnHints.py.txt"))):
        say("[!] tools\\lm20_ref\\ 의 LM20 수집기 원본이 없습니다 — 배포 폴더를 다시 받으세요.")
        return 1
    shutil.rmtree(WORK, ignore_errors=True)
    say(f"[PC 가동시간 비교] 기간 {d0} ~ {d1} · PC {os.environ.get('COMPUTERNAME', '')} · {time.strftime('%Y-%m-%d %H:%M')}")
    say("  실제 data 폴더는 읽기만 합니다. 두 수집기는 임시 폴더에서 돌고 끝나면 지웁니다.")
    say("")
    miss = [p for p in (os.path.join(ROOT, "collect", "Get-PcOnHistory.ps1"),
                        os.path.join(ROOT, "collect", "Get-PcOnHints.py")) if not os.path.isfile(p)]
    if miss:
        say("[!] 이 폴더에 수집기가 없습니다 — 비교를 건너뛰고 메일 항목만 보여 줍니다: "
            + ", ".join(os.path.basename(p) for p in miss))
        mail_section(d0, d1)
        return 1
    say("① LM20 수집기(0551) 실행 중…")
    lm20 = run_tree("LM20", os.path.join(REF, "Get-PcOnHistory.ps1.txt"), os.path.join(REF, "Get-PcOnHints.py.txt"), d0, d1)
    say(f"   끝 ({lm20['sec']}초, rc={lm20['rc']})")
    say("② 현재 수집기 실행 중…")
    cur = run_tree("CUR", os.path.join(ROOT, "collect", "Get-PcOnHistory.ps1"), os.path.join(ROOT, "collect", "Get-PcOnHints.py"), d0, d1)
    say(f"   끝 ({cur['sec']}초, rc={cur['rc']})")
    real_main = month_sum(os.path.join(DATA, "pc", "pc_on.csv"), d0, d1)
    extra = {}
    for r in sorted(glob.glob(os.path.join(DATA, "추가PC", "*"))):
        if os.path.isdir(r):
            extra[os.path.basename(r)] = month_sum(os.path.join(r, "pc", "pc_on.csv"), d0, d1)
    screen, screen_days = screen_line(d0, d1)

    say("")
    say("■ 달별 PC 가동시간(h) — 같은 PC · 같은 기간")
    hdr = ["달", "LM20 이벤트", "LM20 +보강", "현재 이벤트", "현재 +보강", "저장된 data(본 PC)"] + \
          [f"추가PC:{k}"[:14] for k in extra] + ["화면 선"]
    say("  " + " | ".join(f"{h:>12}" for h in hdr))
    tot = [0.0] * (len(hdr) - 1)
    for m in months(d0, d1):
        vals = [lm20["events"][0].get(m, 0.0), lm20["all"][0].get(m, 0.0), cur["events"][0].get(m, 0.0),
                cur["all"][0].get(m, 0.0), real_main[0].get(m, 0.0)] + [v[0].get(m, 0.0) for v in extra.values()] + \
               [screen.get(m, 0.0) if isinstance(screen.get(m, 0.0), float) else 0.0]
        tot = [a + b for a, b in zip(tot, vals, strict=True)]
        say("  " + " | ".join([f"{m:>12}"] + [f"{v:12.1f}" for v in vals]))
    say("  " + " | ".join([f"{'합계':>12}"] + [f"{v:12.1f}" for v in tot]))
    days = [lm20["events"][1], lm20["all"][1], cur["events"][1], cur["all"][1], real_main[1]] + \
           [v[1] for v in extra.values()] + [screen_days]
    say("  " + " | ".join([f"{'기록 날 수':>12}"] + [f"{v:12d}" for v in days]))
    if "오류" in screen:
        say(f"  (화면 선 계산 실패: {screen['오류']})")

    say("")
    say("■ 원천 자료")
    say(f"  System 이벤트 로그의 가장 오래된 이벤트: {oldest_event()}")
    for lbl, info in (("LM20", lm20), ("현재", cur)):
        for x in info["ev_log"] + info["hint_log"]:
            say(f"  [{lbl}] {x}")
    for prof, by, note in browser_counts(d0, d1):
        if by is None:
            say(f"  브라우저 {prof}: {note}")
            continue
        say(f"  브라우저 {prof}: 가장 오래된 방문 {note} · 달별 방문(전체/동기화 표식) "
            + "  ".join(f"{m[5:]}월 {a[0]}/{a[1]}" for m, a in sorted(by.items())))
    sm = sampler_counts(DATA, d0, d1)
    say("  창 샘플러(본 PC) 달별 샘플: " + ("  ".join(f"{m[5:]}월 {n}" for m, n in sorted(sm.items())) or "없음"))
    for r in sorted(glob.glob(os.path.join(DATA, "추가PC", "*"))):
        if os.path.isdir(r):
            s2 = sampler_counts(r, d0, d1)
            say(f"  창 샘플러(추가PC:{os.path.basename(r)}) 달별 샘플: " + ("  ".join(f"{m[5:]}월 {n}" for m, n in sorted(s2.items())) or "없음"))

    mail_section(d0, d1)
    say("")
    say("■ 읽는 법")
    say("  · 'LM20 +보강' 이 '현재 +보강' 보다 크면 → 수집기 차이(이 표를 그대로 보내 주세요)")
    say("  · 두 수집기는 비슷한데 '저장된 data' 가 작으면 → 저장된 기록이 옛 수집 결과(분석 실행을 다시 돌리면 채워짐)")
    say("  · '저장된 data' 는 큰데 '화면 선' 이 작으면 → 화면 계산 문제")
    say("  · 메일 항목의 '날짜만' 이 많으면 → Outlook 앱(COM) 경로로 다시 수집해야 시간이 잡힙니다")
    shutil.rmtree(WORK, ignore_errors=True)
    out = os.path.join(ROOT, "report", "pc_hours_compare.txt")
    try:
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", encoding="utf-8-sig") as f:
            f.write("\n".join(LINES) + "\n")
        say("")
        say(f"결과 저장: {out}")
    except OSError as e:
        say(f"[!] 결과 저장 실패({type(e).__name__})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
