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

    say("")
    say("■ 읽는 법")
    say("  · 'LM20 +보강' 이 '현재 +보강' 보다 크면 → 수집기 차이(이 표를 그대로 보내 주세요)")
    say("  · 두 수집기는 비슷한데 '저장된 data' 가 작으면 → 저장된 기록이 옛 수집 결과(분석 실행을 다시 돌리면 채워짐)")
    say("  · '저장된 data' 는 큰데 '화면 선' 이 작으면 → 화면 계산 문제")
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
