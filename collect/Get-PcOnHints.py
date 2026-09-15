# -*- coding: utf-8 -*-
r"""
Get-PcOnHints.py — 브라우저 사용기록의 '방문 시각'만으로 과거 PC 가동을 보강한다.

왜: 회사 PC는 System 이벤트 로그가 빨리 롤오버돼 3개월 기간에 며칠만 남는다(실측 2건).
    Edge/Chrome 사용기록은 기본 90일 보존이라 기간 전체를 덮는 유일한 상시 소스다.

프라이버시: visits.visit_time 컬럼(시각)만 SELECT 한다 — URL·제목·검색어는 조회 자체를
    하지 않는다. 산출물은 날짜별 가동시간 숫자뿐이다. 방문은 LM20 과 같이 전부 센다 — '동기화 방문'
    표식(visit_source·originator_cache_guid)은 이 PC 에서 본 방문에도 붙어 제외 근거가 못 된다(실측, visit_times 주석).

동작: 방문 시각을 30분 갭으로 세션화(+마지막 방문 5분 여유) → 힌트 구간.
    data\pc\pc_spans.csv(이벤트 구간, Get-PcOnHistory.ps1) 가 있으면 **이벤트 구간 ∪ 힌트 구간** 을
    합친 뒤 날짜별 on/night/first/last 를 한 구간 집합에서 다시 계산해 pc_on.csv 를 쓴다(예전의
    'on 은 힌트, night 는 이벤트' 따로 max 병합이 night≈on 모순 행을 만들던 결함 수정). 힌트 구간은
    pc_spans.csv 에 src=hint 로 보태 extract 가 같은 구간을 본다. pc_spans.csv 가 없으면(옛 수집분)
    날짜별 병합으로 폴백한다 — 주간(on−night)·야간을 **열별 최댓값**으로 합치고 first 는 이른 쪽·last 는 늦은 쪽.

  python collect\Get-PcOnHints.py --from 2026-05-19 --to 2026-08-17
"""
import csv
import glob
import io
import os
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta

if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, errors="replace", encoding=(
        (sys.stdout.encoding or "utf-8") if sys.stdout.isatty() else "utf-8"))  # 콘솔(bat)=콘솔 코드페이지 · 파이프(UI)=utf-8
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# v3: 원장(ledger) — 병합·래칫 없이 추가만 한다. core 가 없으면(수집기 단독 사본 트리) 보강을 보류한다.
sys.path.insert(0, os.path.join(ROOT, "core"))
try:
    import pc_ledger as _ledger
except ImportError:
    _ledger = None

GAP_MIN = 30          # 방문 간격이 이보다 벌어지면 다른 세션
TAIL_MIN = 5          # 마지막 방문 뒤 여유
CHROME_EPOCH_OFFSET = 11644473600   # 1601-01-01 → 1970-01-01 (초)
HINT_SRC = "hint"     # pc_spans.csv 의 src 값 (이벤트 구간은 event|event-cap|live|boot)
SPAN_FMT = "%Y-%m-%d %H:%M:%S"


def arg(flag, d=""):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else d


def history_files():
    """Edge/Chrome 전 프로필의 History 경로 (LM 전용 copilot_profile 은 여기 없음)"""
    la = os.environ.get("LOCALAPPDATA", "")
    outs = []
    for base in (os.path.join(la, "Microsoft", "Edge", "User Data"),
                 os.path.join(la, "Google", "Chrome", "User Data")):
        if not os.path.isdir(base):
            continue
        for prof in ["Default"] + [os.path.basename(p) for p in glob.glob(os.path.join(base, "Profile *"))]:
            h = os.path.join(base, prof, "History")
            if os.path.isfile(h):
                outs.append(h)
    return outs


def _chrome_us(t):
    """로컬 naive datetime → Chromium visit_time(1601 기준 µs)"""
    return int((t.timestamp() + CHROME_EPOCH_OFFSET) * 1e6)


def visit_times(hist_path, t0, t1):
    """방문 시각 목록 — 브라우저가 잠그고 있어도 사본으로 읽는다 (URL 은 조회하지 않음).
    반환 방문 시각 목록."""
    tmp = os.path.join(tempfile.gettempdir(), "lm_hist_copy")
    times = []
    try:
        shutil.copy2(hist_path, tmp)
        for ext in ("-wal", "-shm"):        # WAL 에만 있는 최근 방문 포함
            if os.path.isfile(hist_path + ext):
                shutil.copy2(hist_path + ext, tmp + ext)
        con = sqlite3.connect(tmp)
        try:
            lo, hi = _chrome_us(t0), _chrome_us(t1)
            # 방문은 **전부** 이 PC 의 가동 근거로 센다 — LM20 과 같다. LM22~LM24 는 visit_source(source≠1)·
            # originator_cache_guid 로 '다른 기기 동기화' 를 걸렀는데, 이 PC 이벤트 로그 가동 구간과 로컬 시각으로 대조하니
            # 거른 방문도 이 PC 가 켜진 시간의 것이었다(남긴 방문 89% · source=8 1,946건 95% · guid 532건 70% — guid 의 나머지는
            # 전부 종료 이벤트가 빠진 하루(이벤트 구간이 20h 에서 잘린 날)에 몰려 있고 그날도 일반 방문이 PC 가 켜져 있었음을
            # 보인다). 그 필터가 보강 시간을 LM20 보다 줄였다(보강만 8월 60.1h → 38.0h).
            for (v,) in con.execute("SELECT visit_time FROM visits WHERE visit_time >= ? AND visit_time < ?", (lo, hi)):
                try:
                    t = datetime.fromtimestamp(v / 1e6 - CHROME_EPOCH_OFFSET)
                except (OSError, OverflowError, ValueError):
                    continue
                if t0 <= t < t1:
                    times.append(t)
        finally:
            con.close()
    except Exception as e:
        print(f"[pc-hint] {os.path.basename(os.path.dirname(hist_path))}: 읽기 실패 ({e.__class__.__name__})")
    finally:
        for p in (tmp, tmp + "-wal", tmp + "-shm"):
            try:
                os.remove(p)
            except OSError:
                pass
    return times


def to_spans(times):
    """시각 목록 → (시작, 끝) 세션 구간 (30분 갭 분리, 끝 +5분)"""
    spans = []
    for t in sorted(times):
        if spans and (t - spans[-1][1]).total_seconds() <= GAP_MIN * 60:
            spans[-1][1] = t
        else:
            spans.append([t, t])
    return [(a, b + timedelta(minutes=TAIL_MIN)) for a, b in spans]


def merge_spans(spans):
    """겹치거나 맞닿은 구간 병합 → 정렬된 [(a, b)] (합집합)"""
    out = []
    for a, b in sorted((a, b) for a, b in spans if b > a):
        if out and a <= out[-1][1]:
            if b > out[-1][1]:
                out[-1] = (out[-1][0], b)
        else:
            out.append((a, b))
    return out


def daily_from_spans(spans):
    """자정 분할 → {date: {on, night, first, last}} — PS 수집기와 같은 정의(야간 = 08시 이전·19시 이후)"""
    daily = {}
    for a, b in spans:
        cur = a
        while cur.date() <= b.date():
            day_end = datetime.combine(cur.date(), datetime.min.time()) + timedelta(days=1)
            seg_end = min(b, day_end)
            if seg_end <= cur:
                break
            k = cur.date().isoformat()
            d = daily.setdefault(k, {"on": 0.0, "night": 0.0, "first": cur, "last": seg_end})
            d["on"] += (seg_end - cur).total_seconds() / 3600
            d["first"] = min(d["first"], cur)
            d["last"] = max(d["last"], seg_end)
            m8 = datetime.combine(cur.date(), datetime.min.time()) + timedelta(hours=8)
            m19 = datetime.combine(cur.date(), datetime.min.time()) + timedelta(hours=19)
            if cur < m8:
                d["night"] += (min(seg_end, m8) - cur).total_seconds() / 3600
            if seg_end > m19:
                d["night"] += (seg_end - max(cur, m19)).total_seconds() / 3600
            cur = day_end
    return daily


def read_spans_csv(path):
    """pc_spans.csv → [(start, end, src)] (없으면 [])"""
    out = []
    if not os.path.isfile(path):
        return out
    with open(path, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            try:
                a = datetime.strptime((r.get("start") or "")[:19], SPAN_FMT)
                b = datetime.strptime((r.get("end") or "")[:19], SPAN_FMT)
            except ValueError:
                continue
            if b > a:
                out.append((a, b, (r.get("src") or "event").strip() or "event"))
    return out


def write_spans_csv(path, spans):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["start", "end", "src"])
        for a, b, s in sorted(spans):
            w.writerow([a.strftime(SPAN_FMT), b.strftime(SPAN_FMT), s])


def sampler_times(t0, t1, data_root=None):
    r"""창 샘플러(activity_*.csv)의 샘플 시각 — 1분 간격으로 찍히는 가장 확실한 가동 증거.
    제목·프로세스는 읽지 않고 time 열만 쓴다. 브라우저 기록이 정책으로 막힌 PC 의 대비책.
    data_root 를 주면 그 뿌리(data\추가PC\<PC>)의 샘플을 읽는다."""
    times = []
    for p in glob.glob(os.path.join(data_root or os.path.join(ROOT, "data"), "activity", "activity_*.csv")):
        try:
            with open(p, encoding="utf-8-sig", errors="replace") as f:
                for r in csv.DictReader(f):
                    try:
                        t = datetime.strptime((r.get("time") or "")[:19], "%Y-%m-%d %H:%M:%S")
                    except ValueError:
                        try:
                            t = datetime.strptime((r.get("time") or "")[:16], "%Y-%m-%d %H:%M")
                        except ValueError:
                            continue
                    if t0 <= t < t1:
                        times.append(t)
        except OSError:
            continue
    return times


def main():
    d0 = arg("--from") or (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
    d1 = arg("--to") or datetime.now().strftime("%Y-%m-%d")
    t0 = datetime.strptime(d0, "%Y-%m-%d")
    t1 = datetime.strptime(d1, "%Y-%m-%d") + timedelta(days=1)
    if _ledger is None:
        print("[pc-hint] core\\pc_ledger 가 없어 보강을 보류합니다 — 기존 기록은 건드리지 않습니다")
        return 0
    pc_dir = os.path.join(ROOT, "data", "pc")
    anchor = _ledger.ensure_anchor(pc_dir, own_pc=True)
    if anchor is not None and anchor > t0:
        # 이 PC 첫 사용 이후 방문만 센다 — 이동해 온 PC 의 동기화 방문이 원장에 들어오지 못하게
        # **쓰기 시점**에 막는다(v2 의 읽기 필터는 구판 폴더용 안전망으로만 남는다).
        print(f"[pc-hint] 이 PC 첫 사용 {anchor:%Y-%m-%d} 이후 방문만 셉니다(이동 PC 동기화 방문 제외)")
        t0 = max(t0, anchor)
    files = history_files()
    if not files:
        print("[pc-hint] Edge/Chrome 사용기록 없음(정책 차단 가능) — 샘플러 시각으로만 보강 시도")
    times = []
    for h in files:
        vt = visit_times(h, t0, t1)
        times += vt
        prof = os.path.basename(os.path.dirname(h))
        brand = "Edge" if "\\Edge\\" in h else "Chrome"
        print(f"[pc-hint] {brand}\\{prof}: 방문 시각 {len(vt)}건 (URL 미조회)")
    st = sampler_times(t0, t1)
    if st:
        print(f"[pc-hint] 창 샘플러: 샘플 시각 {len(st)}건 합류")
    times += st
    if not times:
        print("[pc-hint] 보강 근거 없음(방문 기록·샘플러 모두 0건) — 원장 그대로")
        extra_sampler(t0, t1)          # 본 PC 근거가 없어도 옮겨 온 PC 의 샘플러는 보강한다
        return 0
    # TAIL_MIN 여유가 --to 자정을 넘겨 기간 밖 구간을 만들지 않게 t1 로 자른다
    hint_spans = [(a, min(b, t1), HINT_SRC) for a, b in to_spans(times) if a < t1]
    added, _lu, clipped = _ledger.append_spans(pc_dir, hint_spans, anchor=anchor)
    days, carried = _ledger.regen_pc_on(pc_dir)
    extra_sampler(t0, t1)            # 요약 줄보다 먼저 — run.py 가 마지막 줄을 수집 단계 요약으로 남긴다
    print(f"[pc-hint] 힌트 구간 {len(hint_spans)}개 → 원장 추가 {added}"
          + (f" · 앵커 이전 제외 {clipped}" if clipped else "")
          + f" · 캐시 재생성 {days}일(+이월 {carried})")
    return 0


def extra_sampler(t0, t1):
    r"""추가PC\<지난 PC>\ 로 보관된 창 샘플러 기록을 **그 PC 의** pc_on 에 보강한다.
    폴더째 옮기면 지난 PC 의 activity 가 보관 폴더로 옮겨지는데, 보강은 본 폴더의 activity 만 읽어 마지막 분석 뒤
    옮기기 전까지 쌓인 샘플이 가동 시간에 끝내 반영되지 않았다(감사 확인 — 이동을 반복할수록 빠진다).
    다른 PC 의 시간을 이 PC 기록에 섞지 않도록 그 뿌리의 pc_on·pc_spans 에만 쓰고(src=sampler), 행은 줄이지 않는다."""
    base = os.path.join(ROOT, "data", "추가PC")
    if not os.path.isdir(base):
        return
    for name in sorted(os.listdir(base)):
        root = os.path.join(base, name)
        if not os.path.isdir(os.path.join(root, "activity")):
            continue
        st = sampler_times(t0, t1, data_root=root)
        if not st:
            continue
        spans = [(a, min(b, t1), "sampler") for a, b in to_spans(st) if a < t1]
        pc_dir = os.path.join(root, "pc")
        os.makedirs(pc_dir, exist_ok=True)
        if _ledger is None:
            continue
        try:
            # 남의 폴더 — 앵커는 그 폴더 자신의 첫 물리 이벤트로만(own_pc=False), 샘플은 그 PC 실사용 증거라 앵커로 거르지 않는다
            add, _lu, _cl = _ledger.append_spans(pc_dir, [(a, b, "sampler") for a, b, *_ in spans])
            days, carried = _ledger.regen_pc_on(pc_dir)
        except OSError as e:
            print(f"[pc-hint] 추가PC\\{name}: 샘플러 보강 실패({e.__class__.__name__})")
            continue
        print(f"[pc-hint] 추가PC\\{name}: 창 샘플러 {len(st)}건 → 원장 추가 {add} · 캐시 {days}일(+이월 {carried})")


if __name__ == "__main__":
    sys.exit(main())
