# -*- coding: utf-8 -*-
r"""
Get-PcOnHints.py — 브라우저 사용기록의 '방문 시각'만으로 과거 PC 가동을 보강한다.

왜: 회사 PC는 System 이벤트 로그가 빨리 롤오버돼 3개월 기간에 며칠만 남는다(실측 2건).
    Edge/Chrome 사용기록은 기본 90일 보존이라 기간 전체를 덮는 유일한 상시 소스다.

프라이버시: visits.visit_time 컬럼(시각)만 SELECT 한다 — URL·제목·검색어는 조회 자체를
    하지 않는다. 산출물은 날짜별 가동시간 숫자뿐이다. 다른 기기(휴대폰)에서 동기화된 방문
    (visit_source.source=0, originator_cache_guid 있음)은 이 PC 의 가동 근거가 아니므로 제외한다.

동작: 방문 시각을 30분 갭으로 세션화(+마지막 방문 5분 여유) → 힌트 구간.
    data\pc\pc_spans.csv(이벤트 구간, Get-PcOnHistory.ps1) 가 있으면 **이벤트 구간 ∪ 힌트 구간** 을
    합친 뒤 날짜별 on/night/first/last 를 한 구간 집합에서 다시 계산해 pc_on.csv 를 쓴다(예전의
    'on 은 힌트, night 는 이벤트' 따로 max 병합이 night≈on 모순 행을 만들던 결함 수정). 힌트 구간은
    pc_spans.csv 에 src=hint 로 보태 extract 가 같은 구간을 본다. pc_spans.csv 가 없으면(옛 수집분)
    날짜별 병합으로 폴백하되 on 을 힌트로 바꿀 때 night/first/last 도 힌트 값으로 함께 바꾼다.

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
    반환 (times, excluded): excluded = 다른 기기 동기화 방문 수(제외됨)."""
    tmp = os.path.join(tempfile.gettempdir(), "lm_hist_copy")
    times = []
    excluded = 0
    try:
        shutil.copy2(hist_path, tmp)
        for ext in ("-wal", "-shm"):        # WAL 에만 있는 최근 방문 포함
            if os.path.isfile(hist_path + ext):
                shutil.copy2(hist_path + ext, tmp + ext)
        con = sqlite3.connect(tmp)
        try:
            cols = {r[1] for r in con.execute("PRAGMA table_info(visits)")}
            has_src = bool(con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='visit_source'").fetchone())
            lo, hi = _chrome_us(t0), _chrome_us(t1)
            where = ["v.visit_time >= ? AND v.visit_time < ?"]
            q = "SELECT v.visit_time FROM visits v"
            if has_src:
                # visit_source 는 '이 PC 에서 직접 본 방문(SOURCE_BROWSED=1)' 에는 행이 없고, 동기화(0)·
                # 확장·가져오기(2~5) 방문에만 남는다 → 행이 없거나 1 인 것만 이 PC 의 가동 근거
                q += " LEFT JOIN visit_source s ON s.id = v.id"
                where.append("(s.source IS NULL OR s.source = 1)")
            if "originator_cache_guid" in cols:   # 최근 Chromium: 다른 기기에서 온 방문은 원 기기 GUID 가 채워진다
                where.append("(v.originator_cache_guid IS NULL OR v.originator_cache_guid = '')")
            n_all = con.execute("SELECT COUNT(*) FROM visits v WHERE " + where[0], (lo, hi)).fetchone()[0]
            n_keep = 0
            for (v,) in con.execute(q + " WHERE " + " AND ".join(where), (lo, hi)):
                try:
                    t = datetime.fromtimestamp(v / 1e6 - CHROME_EPOCH_OFFSET)
                except (OSError, OverflowError, ValueError):
                    continue
                n_keep += 1
                if t0 <= t < t1:
                    times.append(t)
            excluded = max(0, n_all - n_keep)
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
    return times, excluded


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


def _hhmm(dt, day_key):
    """자정으로 끝난 구간은 '00:00'이 아니라 '24:00' — 문자열 비교(max)에서 가장 이른
    시각으로 취급돼 마지막 사용 시각이 영원히 반영되지 않던 문제를 막는다."""
    if dt.strftime("%H:%M") == "00:00" and dt.date().isoformat() != day_key:
        return "24:00"
    return dt.strftime("%H:%M")


def _row(k, d):
    return {"date": k, "on_hours": str(round(d["on"], 2)), "first_on": d["first"].strftime("%H:%M"),
            "last_off": _hhmm(d["last"], k), "night_hours": str(round(d["night"], 2)),
            "weekend": str(1 if datetime.strptime(k, "%Y-%m-%d").weekday() >= 5 else 0)}


def _write_pc_on(csv_path, rows):
    os.makedirs(os.path.dirname(csv_path), exist_ok=True)
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "on_hours", "first_on", "last_off", "night_hours", "weekend"])
        for k in sorted(rows):
            r = rows[k]
            w.writerow([r.get("date"), r.get("on_hours"), r.get("first_on"),
                        r.get("last_off"), r.get("night_hours"), r.get("weekend")])


def _read_pc_on(csv_path):
    rows = {}
    if os.path.isfile(csv_path):
        with open(csv_path, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                if r.get("date"):
                    rows[r["date"]] = r
    return rows


def merge_pc_on(csv_path, hints, hint_spans=None, spans_path=None):
    """힌트를 pc_on.csv 에 병합. 반환 (합계 일수, 신규 일수, 보강 일수).

    spans_path(pc_spans.csv) 가 있으면 구간 단위 병합: 이벤트 구간 ∪ 힌트 구간을 합친 한 집합에서
    날짜별 on/night/first/last 를 다시 계산한다(night 만 이벤트 값이 남는 모순 없음). 그 날짜들의
    행은 재계산값으로 바뀌고, 다른 날짜 행은 그대로 둔다. 힌트 구간은 pc_spans.csv 에 src=hint 로
    저장(재실행 시 예전 hint 행은 교체).
    없으면 날짜별 폴백: 힌트 on 이 더 크면 on·night·first·last 를 **힌트 값으로 함께** 바꾼다."""
    rows = _read_pc_on(csv_path)
    added = improved = 0
    if spans_path and hint_spans is not None and os.path.isfile(spans_path):
        ev = [(a, b, s) for a, b, s in read_spans_csv(spans_path) if s != HINT_SRC]
        union = merge_spans([(a, b) for a, b, _ in ev] + list(hint_spans))
        daily = daily_from_spans(union)
        for k, d in sorted(daily.items()):
            new = _row(k, d)
            old = rows.get(k)
            if not old:
                added += 1
            else:
                try:
                    if float(old.get("on_hours") or 0) + 0.005 < float(new["on_hours"]):
                        improved += 1
                except (ValueError, TypeError):
                    pass
            rows[k] = new
        _write_pc_on(csv_path, rows)
        write_spans_csv(spans_path, ev + [(a, b, HINT_SRC) for a, b in hint_spans])
        return len(rows), added, improved

    for k, d in sorted(hints.items()):
        h = _row(k, d)
        old = rows.get(k)
        if not old:
            rows[k] = h
            added += 1
            continue
        try:
            if float(old.get("on_hours") or 0) < float(h["on_hours"]):
                # 힌트가 더 넓으면 행 전체를 힌트 값으로 — on 만 바꾸고 night 는 이벤트 max 로 두면
                # night≈on 인 모순 행(주간 0h)이 생긴다(감사 teams-pc-sampler-8)
                old.update(h)
                improved += 1
        except (ValueError, TypeError):
            continue
    _write_pc_on(csv_path, rows)
    return len(rows), added, improved


def sampler_times(t0, t1):
    """창 샘플러(activity_*.csv)의 샘플 시각 — 1분 간격으로 찍히는 가장 확실한 가동 증거.
    제목·프로세스는 읽지 않고 time 열만 쓴다. 브라우저 기록이 정책으로 막힌 PC 의 대비책."""
    times = []
    for p in glob.glob(os.path.join(ROOT, "data", "activity", "activity_*.csv")):
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
    files = history_files()
    if not files:
        print("[pc-hint] Edge/Chrome 사용기록 없음(정책 차단 가능) — 샘플러 시각으로만 보강 시도")
    times = []
    for h in files:
        vt, excl = visit_times(h, t0, t1)
        times += vt
        prof = os.path.basename(os.path.dirname(h))
        brand = "Edge" if "\\Edge\\" in h else "Chrome"
        note = f" · 다른 기기 동기화 {excl}건 제외" if excl else ""
        print(f"[pc-hint] {brand}\\{prof}: 방문 시각 {len(vt)}건{note} (URL 미조회)")
    st = sampler_times(t0, t1)
    if st:
        print(f"[pc-hint] 창 샘플러: 샘플 시각 {len(st)}건 합류")
    times += st
    pc_dir = os.path.join(ROOT, "data", "pc")
    csv_path = os.path.join(pc_dir, "pc_on.csv")
    spans_path = os.path.join(pc_dir, "pc_spans.csv")
    if not times:
        print("[pc-hint] 보강 근거 없음(방문 기록·샘플러 모두 0건) — 이벤트 로그 결과 유지")
        return 0
    # TAIL_MIN 여유가 --to 자정을 넘겨 기간 밖 날짜 행을 만들지 않게 t1 로 자른다
    hint_spans = [(a, min(b, t1)) for a, b in to_spans(times) if a < t1]
    daily = daily_from_spans(hint_spans)
    total, added, improved = merge_pc_on(csv_path, daily, hint_spans, spans_path)
    mode = "구간 합집합" if os.path.isfile(spans_path) else "날짜별(pc_spans.csv 없음)"
    print(f"[pc-hint] 힌트 {len(daily)}일 → pc_on.csv 병합({mode}): 신규 {added}일 · 보강 {improved}일 · 합계 {total}일")
    return 0


if __name__ == "__main__":
    sys.exit(main())
