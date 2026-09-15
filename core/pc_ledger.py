# -*- coding: utf-8 -*-
"""PC 가동 기록의 원장(ledger) — v3 구조 계약의 핵심.

왜 이 파일이 생겼나 (v3 구조 감사 실측):
  v2 까지는 같은 사실이 세 벌(pc_spans 구간 · pc_on 일별 파생 · 수집기별 병합 규칙)로 저장되고,
  쓰기 4곳(이벤트 수집기·힌트 병합·샘플러 보강·12h 자동 보강)이 '저장된 파생값'을 읽어 각자
  규칙으로 다시 병합했다. 규칙끼리 정면 모순이라(힌트의 no-shrink 래칫 vs 이벤트 수집기의 도달 창
  전면 재작성) **실행 한 번이 저장된 704.6h 중 593.5h 를 지울 수 있었고**(합성 실측), 읽기 규칙도
  4벌이라 같은 폴더가 추이 8h·진단 줄 618h 로 갈렸다. '8h만 찍힘'·'이동 후 수백 시간'·'0h'·
  '합산 안 됨' 네 증상은 전부 이 한 구조의 표면이었다.

v3 계약 — 네 문장:
  ① pc_spans.csv 가 **유일한 저장 원천(원장)** 이다. 추가 전용이며 지우지 않는다.
     (롤오버 내구성은 '저장값 보존 특례'가 아니라 '원장은 안 지운다'에서 나온다.)
  ② pc_on.csv 는 **캐시**다. 항상 원장에서 통째로 재생성하고, 절대 병합하지 않는다.
     (원장이 안 줄면 파생도 안 준다 — no-shrink 래칫·도달 창 보존·행 교체 특례 전부 불필요.)
  ③ 일별 파생(on/night/first/last)은 이 파일의 derive_daily **한 벌**만 쓴다.
     (수집기 PS·힌트 PY 에 있던 중복 구현을 이 파일로 통합 — 화면·하한·진단이 같은 숫자를 본다.)
  ④ 이동 PC 방어는 읽기 필터가 아니라 pc_anchor.json(이 PC 첫 사용 시각, 1회 기록·불변)으로
     **쓰기 시점**에 한다. 앵커 이전의 브라우저 방문(동기화로 넘어온 것)은 원장에 들어오지 못한다.

파일 형식:
  pc_spans.csv  start,end,src[,seen]   — seen(수집 시각)은 v3 에서 추가. 구판 3열 행도 그대로 읽힌다.
  pc_on.csv     date,on_hours,first_on,last_off,night_hours,weekend  — 구판과 동일(소비자 무수정).
  pc_anchor.json {"since": "YYYY-MM-DD HH:MM:SS", "made": "...", "how": "..."}

구판 폴더(추가PC 보관본 등, 앵커 없음)는 읽기 쪽(extract)이 기존 규칙으로 계속 읽는다 —
'그 폴더에 pc_anchor.json 이 있는가' 하나가 신·구 판단의 전부다.
"""
import csv
import io
import json
import os
import sys
import time
from datetime import datetime, timedelta

SPAN_FMT = "%Y-%m-%d %H:%M:%S"


class _dir_lock:
    r"""폴더 잠금 — 동시 실행(UI + bat)의 read-modify-write 유실을 막는다(최종 검증 실측: 잠금
    없이는 2프로세스 동시 append 에서 43% 유실 + os.replace PermissionError 크래시).
    윈도 msvcrt 바이트 잠금 · 못 얻으면 최대 10초 재시도 후 그냥 진행(잠그다 굶기지 않는다 —
    최악이 v2 의 평소 상태다)."""

    def __init__(self, pcdir):
        self.path = os.path.join(pcdir, ".ledger.lock")
        self.f = None

    def __enter__(self):
        try:
            import msvcrt
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            self.f = open(self.path, "a+")
            for _ in range(100):
                try:
                    msvcrt.locking(self.f.fileno(), msvcrt.LK_NBLCK, 1)
                    return self
                except OSError:
                    time.sleep(0.1)
            self.f.close()
            self.f = None
        except (ImportError, OSError):
            self.f = None
        return self

    def __exit__(self, *a):
        if self.f is not None:
            try:
                import msvcrt
                self.f.seek(0)
                msvcrt.locking(self.f.fileno(), msvcrt.LK_UNLCK, 1)
            except (ImportError, OSError):
                pass
            try:
                self.f.close()
            except OSError:
                pass
        return False


def _replace_retry(src, dst, tries=25):
    """os.replace 를 짧게 재시도 — 화면·백신이 읽는 순간의 WinError 5 로 수집이 죽지 않게."""
    for _ in range(tries):
        try:
            os.replace(src, dst)
            return True
        except PermissionError:
            time.sleep(0.2)
    try:
        os.replace(src, dst)
        return True
    except OSError:
        return False
EVENT_SRC = ("event", "event-gap", "event-cap", "boot")   # 물리 이벤트 계열(전원·부팅·세션)
LIVE_SRC = "live"                                         # 현재 부팅 세션 — 부팅당 1행 upsert
HINT_SRC = "hint"                                         # 브라우저 방문 파생
SAMPLER_SRC = "sampler"                                   # 창 샘플러
MIGR_SRC = "migr"                                         # 1회 이행으로 살린 구판 행
DAY_WIN = (8 * 60, 19 * 60)                               # 주간 경계(분) — extract.DAY_WIN 과 같은 값


def _dt(s):
    s = (str(s or ""))[:19]
    for fmt in (SPAN_FMT, "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def spans_path(pcdir):
    return os.path.join(pcdir, "pc_spans.csv")


def on_path(pcdir):
    return os.path.join(pcdir, "pc_on.csv")


def anchor_path(pcdir):
    return os.path.join(pcdir, "pc_anchor.json")


def read_spans(pcdir):
    """원장 읽기 → [(a, b, src, seen), …] (형식 오류·역전 행은 버리되 개수를 센다)."""
    p = spans_path(pcdir)
    out, bad = [], 0
    if not os.path.exists(p):
        return out, bad
    try:
        with open(p, encoding="utf-8-sig", errors="replace", newline="") as f:
            for r in csv.DictReader(f):
                a, b = _dt(r.get("start")), _dt(r.get("end"))
                if not (a and b and b > a):
                    bad += 1
                    continue
                out.append((a, b, (r.get("src") or "event").strip() or "event",
                            (r.get("seen") or "").strip()))
    except (OSError, csv.Error):
        return out, bad + 1
    return out, bad


def _write_spans(pcdir, rows):
    """원장 전체 쓰기(추가·upsert 결과) — 4열 헤더, BOM 없는 UTF-8, 시작 시각 정렬."""
    p = spans_path(pcdir)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["start", "end", "src", "seen"])
        for a, b, src, seen in sorted(rows, key=lambda r: (r[0], r[1], r[2])):
            w.writerow([a.strftime(SPAN_FMT), b.strftime(SPAN_FMT), src, seen])
    _replace_retry(tmp, p)


def append_spans(pcdir, new_spans, src=None, seen=None, anchor=None):
    """원장에 관측 구간을 **추가**한다 — 지우지 않는다.
    · (start,end,src) 완전 일치는 중복이라 건너뛴다(재실행 멱등 — 겹치는 구간은 그대로 두고
      읽기 합집합이 해소한다. 실데이터의 겹침 65쌍이 이미 이 방식으로 무해함을 실측).
    · src=live 만 예외: '현재 부팅 세션'은 관측마다 끝이 자라는 같은 사실이므로 (start,src) 로
      upsert — 부팅당 1행. 로그가 롤오버돼도 원장에 남아 '도달 창' 개념 자체가 사라진다.
    · anchor(datetime)를 주면 그보다 앞선 구간은 앵커로 자르고, 통째로 앞이면 버린다
      (이동 PC 의 동기화 방문이 저장소에 들어오지 못하게 — 쓰기 시점 방어).
    반환 (추가된 수, live 갱신 수, 앵커로 거른 수)."""
    os.makedirs(pcdir, exist_ok=True)
    with _dir_lock(pcdir):
        return _append_locked(pcdir, new_spans, src, seen, anchor)


def _append_locked(pcdir, new_spans, src, seen, anchor):
    rows, _bad = read_spans(pcdir)
    seen = seen or datetime.now().strftime("%Y-%m-%d %H:%M")
    have = {(a.strftime(SPAN_FMT), b.strftime(SPAN_FMT), s) for a, b, s, _ in rows}
    live_by_start = {a.strftime(SPAN_FMT): i for i, (a, b, s, _) in enumerate(rows) if s == LIVE_SRC}
    added = live_up = clipped = 0
    for item in new_spans:
        a, b = item[0], item[1]
        s = (item[2] if len(item) > 2 and item[2] else src) or "event"
        if not (isinstance(a, datetime) and isinstance(b, datetime) and b > a):
            continue
        if anchor is not None:
            if b <= anchor:
                clipped += 1
                continue
            if a < anchor:
                a = anchor
                clipped += 1
        key = (a.strftime(SPAN_FMT), b.strftime(SPAN_FMT), s)
        if s == LIVE_SRC and key[0] in live_by_start:
            i = live_by_start[key[0]]
            if rows[i][1] != b:
                rows[i] = (a, b, s, seen)
                live_up += 1
            continue
        if key in have:
            continue
        have.add(key)
        rows.append((a, b, s, seen))
        if s == LIVE_SRC:
            live_by_start[key[0]] = len(rows) - 1
        added += 1
    if added or live_up:
        _write_spans(pcdir, rows)
    return added, live_up, clipped


def _union(spans):
    """[(a, b), …] → 겹침 병합 정렬 목록."""
    out = []
    for a, b in sorted((a, b) for a, b in spans if b > a):
        if out and a <= out[-1][1]:
            if b > out[-1][1]:
                out[-1] = (out[-1][0], b)
        else:
            out.append((a, b))
    return out


def derive_daily(spans):
    """구간 목록 → {'YYYY-MM-DD': {'on','night','first','last','cross'}} — **유일한** 일별 파생.
    합집합 먼저(겹침 이중 계상 방지) → 자정 분할 → 주간 경계(08/19)로 야간 분해.
    cross=True 면 그 날이 자정 넘겨 끝났다(pc_on 의 last_off 를 '24:00' 으로 쓰는 규칙)."""
    daily = {}
    for a, b in _union([(a, b) for a, b, *_ in spans]):
        cur = a
        while cur < b:
            day_end = datetime(cur.year, cur.month, cur.day) + timedelta(days=1)
            seg = min(b, day_end)
            k = cur.strftime("%Y-%m-%d")
            d = daily.setdefault(k, {"on": 0.0, "night": 0.0, "first": cur, "last": seg, "cross": False})
            d["on"] += (seg - cur).total_seconds() / 3600.0
            d["first"] = min(d["first"], cur)
            d["last"] = max(d["last"], seg)
            if seg >= day_end:
                d["cross"] = True
            m8 = datetime(cur.year, cur.month, cur.day) + timedelta(minutes=DAY_WIN[0])
            m19 = datetime(cur.year, cur.month, cur.day) + timedelta(minutes=DAY_WIN[1])
            if cur < m8:
                d["night"] += (min(seg, m8) - cur).total_seconds() / 3600.0
            if seg > m19:
                d["night"] += (seg - max(cur, m19)).total_seconds() / 3600.0
            cur = day_end
    return daily


def _read_on_rows(pcdir):
    p = on_path(pcdir)
    out = []
    if not os.path.exists(p):
        return out
    try:
        with open(p, encoding="utf-8-sig", errors="replace", newline="") as f:
            for r in csv.DictReader(f):
                if _dt((r.get("date") or "")[:10]):
                    out.append(r)
    except (OSError, csv.Error):
        pass
    return out


def regen_pc_on(pcdir, anchor=None):
    """pc_on.csv 를 원장에서 **통째로 재생성**한다 — 병합 없음.
    원장에 없는 날의 구판 행(과거 재작성으로 구간 근거가 지워진 날)은 그대로 옮겨 적는다(carry).
    원장에 있는 날은 언제나 파생값이다 — 같은 날에 두 규칙이 경합하지 않는다.
    anchor: 이 폴더의 첫 사용 시각 — carry(원장 밖 구판 행)는 앵커 이전 날짜를 거른다
    (이동 PC 의 v2 오염 행이 캐시에 영속하지 않게 — 최종 검증 MAJOR).
    반환 (원장 파생 일수, carry 일수)."""
    with _dir_lock(pcdir):
        return _regen_locked(pcdir, anchor)


def _regen_locked(pcdir, anchor):
    rows, _bad = read_spans(pcdir)
    daily = derive_daily(rows)
    _amin = anchor.strftime("%Y-%m-%d") if anchor else ""
    carry = [r for r in _read_on_rows(pcdir)
             if (r.get("date") or "")[:10] not in daily
             and (not _amin or (r.get("date") or "")[:10] >= _amin)]
    lines = []
    for k in daily:
        d = daily[k]
        dt0 = datetime.strptime(k, "%Y-%m-%d")
        we = 1 if dt0.weekday() >= 5 else 0
        last = "24:00" if d["cross"] and d["last"].strftime("%H:%M") == "00:00" else d["last"].strftime("%H:%M")
        lines.append({"date": k, "on_hours": str(round(d["on"], 2)),
                      "first_on": d["first"].strftime("%H:%M"), "last_off": last,
                      "night_hours": str(round(d["night"], 2)), "weekend": str(we)})
    for r in carry:
        lines.append({k: (r.get(k) or "") for k in
                      ("date", "on_hours", "first_on", "last_off", "night_hours", "weekend")})
    lines.sort(key=lambda r: r["date"])
    tmp = on_path(pcdir) + ".tmp"
    with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["date", "on_hours", "first_on", "last_off",
                                          "night_hours", "weekend"])
        w.writeheader()
        w.writerows(lines)
    _replace_retry(tmp, on_path(pcdir))
    return len(daily), len(carry)


def read_anchor(pcdir):
    try:
        with open(anchor_path(pcdir), encoding="utf-8-sig") as f:
            return _dt(json.load(f).get("since"))
    except (OSError, ValueError, TypeError, AttributeError):
        return None


def ensure_anchor(pcdir, own_pc=True):
    """이 폴더의 '첫 사용 시각' 앵커 — 없으면 1회 기록, 있으면 그대로(불변).
    본 PC: min(USERPROFILE 생성, 원장 첫 물리 이벤트). 남의 폴더(추가PC 보관본): 첫 물리 이벤트만
    (남의 프로필 생성 시각은 이 기계 것이라 무의미). 근거가 하나도 없으면 만들지 않는다 → 그 폴더는
    구판 규칙(extract 의 안전망 필터)으로 읽힌다."""
    try:
        os.makedirs(pcdir, exist_ok=True)      # 폴더가 없으면 기록이 조용히 실패했다(최종 검증 MINOR)
    except OSError:
        pass
    old = read_anchor(pcdir)
    if old is not None:
        return min(old, datetime.now())        # 미래로 굳은 앵커(시계 이상)도 지금 이후로는 안 막게
    cands, how = [], []
    if own_pc:
        prof = os.environ.get("USERPROFILE", "")
        try:
            if prof and os.path.isdir(prof):
                cands.append(datetime.fromtimestamp(os.path.getctime(prof)))
                how.append("profile")
        except OSError:
            pass
    rows, _bad = read_spans(pcdir)
    evt = [a for a, b, s, _ in rows if s in EVENT_SRC or s == LIVE_SRC]
    if evt:
        cands.append(min(evt))
        how.append("first-event")
    if not cands:
        return None
    since = min(min(cands), datetime.now())    # 미래 ctime(시계 이상)이 앵커가 되면 힌트 보강이 전멸한다
    try:
        with open(anchor_path(pcdir), "w", encoding="utf-8") as f:
            json.dump({"since": since.strftime(SPAN_FMT),
                       "made": datetime.now().strftime(SPAN_FMT), "how": "+".join(how)}, f)
    except OSError:
        return None
    return since


def migrate(pcdir, anchor=None):
    """1회 이행 — 원장에 근거가 없는 구판 pc_on 행을 살린다.
    '끊김 없는 행'(first~last 창 길이 ≈ on ±15분)만 창 그대로 src=migr 구간으로 원장에 넣는다.
    끊김 있는 행은 어디가 비었는지 알 수 없어 구간을 지어내지 않는다 — regen 의 carry 로 산다.
    앵커 이전 행은 승격하지 않는다 — 이동 PC 의 v2 오염 행이 원장에 들어오면 추가 전용이라
    지울 정규 경로가 없다(최종 검증 MAJOR: 두 수정이 한 세트여야 CRITICAL 수정이 안전하다).
    멱등: migr 구간도 완전 일치 중복 제거를 거치므로 두 번 돌려도 한 번이다. 반환 이행 구간 수."""
    rows, _bad = read_spans(pcdir)
    covered = set(derive_daily(rows))
    add = []
    for r in _read_on_rows(pcdir):
        k = (r.get("date") or "")[:10]
        if k in covered:
            continue
        try:
            on = float(r.get("on_hours") or 0)
            fo = datetime.strptime(k + " " + (r.get("first_on") or ""), "%Y-%m-%d %H:%M")
            lo_s = (r.get("last_off") or "").strip()
            lo = (datetime.strptime(k, "%Y-%m-%d") + timedelta(days=1)) if lo_s == "24:00" \
                else datetime.strptime(k + " " + lo_s, "%Y-%m-%d %H:%M")
        except (ValueError, TypeError):
            continue
        if anchor is not None and lo <= anchor:
            continue                            # 앵커 이전 — 이동 전 기계·동기화 흔적일 수 있다
        if lo > fo and abs((lo - fo).total_seconds() / 3600.0 - on) <= 0.25:
            add.append((max(fo, anchor) if anchor else fo, lo, MIGR_SRC))
    if add:
        append_spans(pcdir, add, seen="migrated")
    return len(add)


def ingest(pcdir, own_pc=True, events_file=None):
    """수집 후 원장 반영의 표준 경로 — 수집기(PS)와 힌트(PY)와 run.py 가 전부 이것만 부른다.
    ① 관측 파일(pc_events_new.csv)이 있으면 원장에 append 하고 지운다
    ② 앵커 확보(첫 실행 1회) ③ 구판 행 이행(1회·멱등) ④ pc_on 캐시 재생성.
    반환 dict(사람용 요약은 호출자가 찍는다)."""
    ev = events_file or os.path.join(pcdir, "pc_events_new.csv")
    added = live_up = clipped = 0
    if os.path.exists(ev):
        new = []
        try:
            with open(ev, encoding="utf-8-sig", errors="replace", newline="") as f:
                for r in csv.DictReader(f):
                    a, b = _dt(r.get("start")), _dt(r.get("end"))
                    if a and b and b > a:
                        new.append((a, b, (r.get("src") or "event").strip() or "event"))
        except (OSError, csv.Error):
            new = []
        anchor = read_anchor(pcdir)          # 이벤트 계열은 이 기계의 물리 증거라 앵커로 거르지 않는다
        added, live_up, clipped = append_spans(pcdir, new, seen=None, anchor=None)
        try:
            os.remove(ev)
        except OSError:
            pass
        _ = anchor
    since = ensure_anchor(pcdir, own_pc=own_pc)
    migr = migrate(pcdir, anchor=since)
    days, carried = regen_pc_on(pcdir, anchor=since)
    return {"added": added, "live_up": live_up, "clipped": clipped, "migrated": migr,
            "days": days, "carried": carried,
            "anchor": since.strftime(SPAN_FMT) if since else ""}


def main(argv):
    io_out = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    if "--ingest" in argv:
        pcdir = argv[argv.index("--ingest") + 1]
        own = "--foreign" not in argv
        r = ingest(pcdir, own_pc=own)
        tail = (" · 앵커 " + r["anchor"][:10]) if r["anchor"] else ""
        io_out.write(f"[pc-ledger] 원장 반영: 추가 {r['added']} · live 갱신 {r['live_up']}"
                     f" · 이행 {r['migrated']} · 파생 {r['days']}일(+carry {r['carried']}){tail}" + chr(10))
        io_out.flush()
        return 0
    io_out.write("사용: python core\\pc_ledger.py --ingest <pc폴더> [--foreign]\n")
    io_out.flush()
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
