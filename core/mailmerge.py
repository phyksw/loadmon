# -*- coding: utf-8 -*-
r"""core\mailmerge.py — 수집 경로(collect.channels)의 정제 파일 → 분석이 읽는 공용 파일·수집 요약 (AgentFinder32 §5.1–§5.3).

각 수집기는 자기 정제 파일만 쓴다(G1 을 거친 행만 — privacy.g1_row·G1Writer·g1_file):
  data\outlook\src\mail_<ch>.csv  box,time,sender,subject,conversation,rcv,time_precision,src,notice          (§5.1)
  data\outlook\src\cal_<ch>.csv   start,end,all_day,busy_status,subject,categories,location,response,meeting_status,src[,body]  (§5.2)
  (ch ∈ com·owa·copilot — config collect.channels 에 든 것만 읽는다. 옛 판의 출처·반입 파일은 읽지도 옮기지도 않는다)
이 모듈만 data\outlook\mail.csv·calendar.csv·mail_source.json·collect_summary.json 을 쓴다.

병합(merge)
  메일 키: (편지함, 분, 정제 제목 40자) — 높은 출처가 받은 메일과 ±2분 안의 같은 제목이면 낮은 출처의 행은 버린다.
    · 같은 출처 안의 행은 서로 지우지 않는다(같은 분에 같은 제목으로 두 번 온 알림은 실제 2통).
    · 높은 출처의 '날짜만' 행(time_precision=date)은 낮은 출처의 분 단위 같은 메일로 시각을 채운다.
    · 우선순위: com > owa. 제목이 비면(storeMailSubject=false) 대화 해시, 그것도 없으면 보낸이(가명).
  일정 키: (시작 분 — 날짜만이면 날, 정제 제목 40자) — 우선순위 com > owa. 본문(body)은 calendar.collectBody 일 때만 열을 둔다.
  Copilot 행(증인)은 그날 그 축에 다른 출처 행이 0이고, 원장이 그날을 ok·zero_ok 로 확인하지 않았을 때만 넣는다.
  기간 창(period) 밖의 행은 공용 파일에 넣지 않고, 출처 정제 파일에서도 지운다(D13 — 매 실행). 그때 COM 완료 표
  (src\coverage_com.json)의 달 범위를 창 시작으로 줄이고, 원장(ledger — coverage.Ledger)의 창 밖 날도 지운다 — 지운 날을 나중에
  더 긴 기간으로 부르면 다시 읽는다. 수집하지 않는 실행(run.py --skip-collect)은 prune_window 가 같은 일을 한다(공용 파일 포함).

COM 원자료 G1(g1_com) — run.py 가 Get-OutlookData.ps1 이 끝나자마자(그리고 실행 시작에 남은 원자료가 있으면) 부른다:
  data\outlook\raw\mail_com.csv·cal_com.csv(§5.0) + com_manifest.json(이번에 읽은 달 구간 replace·append · 새 완료 표 · 내 주소)
  → 일정 본문 정리(meetnote.prep_raw_body) → 두 원자료의 참여자 이름을 먼저 모두 본다(G1Context.prepare — 메일·일정 어느 쪽에서
  처음 본 이름이든 둘 다 가린다) → privacy.g1_file(구간 병합) → src\mail_com.csv·cal_com.csv → 둘 다 되면 완료 표 확정.
  원자료·구간 표는 결과와 상관없이 지운다(실패하면 그 달들은 다음 실행이 다시 읽는다).
수집 요약(write_summary) — data\outlook\collect_summary.json(§5.3 · 이 PC 안에서만 — 공유하지 않는다).
G1 건수(save_g1_counts·load_g1_counts) — src\g1_<ch>.json(경로별 마지막 G1 의 kept·excluded — 글 없음).
G1 규칙 판(check_rules) — 정제 규칙(privacy 설정·제한 고객 목록·제목 저장·일정 본문)이 바뀌면 지난 정제 파일·완료 표·원장을
  지운다(새 규칙으로 다시 모은다). run.py 가 원장을 열기 전에 부른다.
"""
import csv
import glob
import hashlib
import io
import json
import os
import re
import sys
import time
from datetime import date, datetime, timedelta

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
import afcfg  # noqa: E402

CHANNELS = afcfg.CHANNELS                       # ("com", "owa", "copilot")
MAIL_COLS = ["box", "time", "sender", "subject", "conversation", "rcv", "time_precision", "src", "notice"]
CAL_COLS = ["start", "end", "all_day", "busy_status", "subject", "categories", "location", "response", "meeting_status",
            "src"]
CAL_BODY = "body"
SRC_COL = "src"
MAIL_PRI = ("com", "owa")
CAL_PRI = ("com", "owa")
WITNESS = ("copilot",)
WIN_MIN = 2                      # 같은 메일로 보는 시각 차(분)
MERGE_VER = "AF32-MERGE-1"
EXCLUDE_KEYS = ("private", "admin", "sensitive", "identifier", "external", "external_unknown", "restricted")
KEPT_KEYS = ("mail_in", "mail_out", "meetings")
RULES_FILE = "g1_rules.json"
SUMMARY_FILE = "collect_summary.json"
_WS = re.compile(r"\s+")
_TAG_RX = re.compile(r"^(mail|cal)_([A-Za-z0-9_-]{1,24})\.csv$")
_EPOCH = datetime(2000, 1, 1)


# ── 작은 도우미 ─────────────────────────────────────────────────────────────────
def channels_of(cfg=None, channels=None):
    """쓸 수집 경로 — channels(주면 그대로, CHANNELS 안의 것만) 또는 config collect.channels."""
    src = channels if channels is not None else afcfg.get(cfg, "collect.channels")
    if isinstance(src, str):
        src = [src]
    out = []
    for c in src or ():
        s = str(c or "").strip().lower()
        if s in CHANNELS and s not in out:
            out.append(s)
    return out


def _today():
    r"""기록에 남기는 날짜('YYYY-MM-DD') — 병합·정제·규칙 확인을 한 날. 하루 중 시각은 남기지 않는다(쓰이지 않는다 —
    새로 썼는지는 파일 수정 시각으로 본다)."""
    return time.strftime("%Y-%m-%d")


def _period(period):
    """(d0, d1) | {"from","to"} | ['d0','d1'] → ('YYYY-MM-DD', 'YYYY-MM-DD') | (None, None)."""
    if not period:
        return None, None
    try:
        if isinstance(period, dict):
            a, b = period.get("from"), period.get("to")
        else:
            a, b = period[0], period[-1]
        a = date.fromisoformat(str(a)[:10]).isoformat()
        b = date.fromisoformat(str(b)[:10]).isoformat()
        return (a, b) if a <= b else (b, a)
    except (TypeError, ValueError, IndexError, KeyError):
        return None, None


def _day(t):
    s = str(t or "").strip()[:10]
    try:
        date.fromisoformat(s)
        return s
    except ValueError:
        return ""


def _minute(t):
    """'YYYY-MM-DD HH:MM[:SS]' → 2000-01-01 부터의 분(날짜만이면 None)"""
    s = str(t or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return int((datetime.strptime(s, fmt) - _EPOCH).total_seconds() // 60)
        except ValueError:
            continue
    return None


def _in_window(day, d0, d1):
    return bool(day) and (d0 is None or d0 <= day) and (d1 is None or day <= d1)


def _read_rows(path):
    """CSV → (머리 열 목록, dict 행 목록). 없거나 못 읽으면 ([], [])."""
    try:
        with open(path, encoding="utf-8-sig", errors="replace", newline="") as f:
            rd = csv.DictReader(f)
            rows = [r for r in rd if isinstance(r, dict)]
            return list(rd.fieldnames or []), rows
    except (OSError, csv.Error):
        return [], []


def _read(path, cols):
    """CSV → dict 목록(빠진 열은 빈 값). 머리말 이름으로 읽는다."""
    _h, rows = _read_rows(path)
    return [{c: ("" if r.get(c) is None else str(r.get(c))) for c in cols} for r in rows]


def _write_csv(path, cols, rows):
    """cols 순서로 쓴다(UTF-8 BOM · CRLF) — 임시 파일 뒤 바꿔 넣기."""
    tmp = f"{path}.{os.getpid()}.tmp"
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(cols)
    for r in rows:
        w.writerow([r.get(c, "") if r.get(c) is not None else "" for c in cols])
    try:
        with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
            f.write(buf.getvalue())
        os.replace(tmp, path)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def _read_json(path):
    try:
        with open(path, encoding="utf-8-sig") as f:
            o = json.load(f)
        return o if isinstance(o, dict) else None
    except (OSError, ValueError):
        return None


def _write_json(path, obj):
    tmp = f"{path}.{os.getpid()}.tmp"
    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
        return True
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False


def _remove(path):
    for _ in range(3):
        try:
            os.remove(path)
            return True
        except FileNotFoundError:
            return False
        except OSError:
            time.sleep(0.3)
    return False


def _tags(src_dir, kind, pri, allowed):
    """src 폴더의 <kind>_<tag>.csv → tag 목록(우선순위 순) — allowed(쓸 수집 경로) 밖·증인은 뺀다."""
    try:
        names = os.listdir(src_dir)
    except OSError:
        return []
    found = []
    for n in names:
        m = _TAG_RX.match(n)
        if m and m.group(1) == kind and m.group(2) in allowed and m.group(2) not in WITNESS:
            found.append(m.group(2))
    order = {t: i for i, t in enumerate(pri)}
    return sorted(found, key=lambda t: (order.get(t, len(pri)), t))


def _default_norm():
    """키 정규화 — 정제된 제목을 privacy.sanitize 로 한 번 더(이미 정제된 토큰은 그대로). 못 쓰면 원문."""
    try:
        import privacy
    except ImportError:
        return lambda s: s
    return lambda s: privacy.sanitize(s, "subject")[0]


def _keytext(norm, cache, subject, conversation="", sender=""):
    s = str(subject or "").strip()
    if s:
        if s not in cache:
            cache[s] = _WS.sub(" ", str(norm(s) or "")).strip().lower()[:40]
        return cache[s]
    c = str(conversation or "").strip()
    if c:
        return "#conv " + c.lower()[:40]
    return "#from " + _WS.sub(" ", str(sender or "")).strip().lower()[:40]


def _box(b):
    return "sent" if str(b or "").strip().lower() == "sent" else "in"


def _axis(b):
    return "mail_out" if _box(b) == "sent" else "mail_in"


# ── 기간 창 밖 지우기(D13) ──────────────────────────────────────────────────────
def trim_coverage(cov, d0):
    """COM 완료 표(dict — coverage_com.json 꼴)의 달 범위를 창 시작 d0 로 줄인다: 끝이 d0 이전인 달은 지우고, 시작이 d0 앞이면 시작을
    d0 로(그 달을 나중에 더 이른 기간으로 부르면 다시 읽는다). 이어 읽던 표식(partial)이 d0 앞에서 시작하면 지운다. → 바꾼 수."""
    if not isinstance(cov, dict) or not d0:
        return 0
    lo = f"{d0} 00:00:00"
    n = 0
    for kind in ("mail", "calendar"):
        sec = cov.get(kind) if isinstance(cov.get(kind), dict) else {}
        for k in list(sec):
            e = sec[k] if isinstance(sec[k], dict) else {}
            if str(e.get("end") or "") <= lo:
                del sec[k]
                n += 1
            elif str(e.get("start") or "") < lo:
                e["start"] = lo
                n += 1
        part = (cov.get("partial") or {}).get(kind) if isinstance(cov.get("partial"), dict) else None
        if isinstance(part, dict):
            for k in list(part):
                e = part[k] if isinstance(part[k], dict) else {}
                if str(e.get("start") or "") < lo:
                    del part[k]
                    n += 1
    return n


def prune_src(src_dir, period, *, channels=None):
    r"""출처 정제 파일(mail_<ch>.csv·cal_<ch>.csv)에서 기간 창 밖 행을 지우고(바뀐 파일만 다시 쓴다) COM 완료 표를 창 시작으로 줄인다.
    collect.channels 밖의 출처 파일은 통째로 지운다(쓰지 않는 경로의 자료를 남기지 않는다). → {"rows": 지운 행 수, "files": [...]}"""
    d0, d1 = _period(period)
    out = {"rows": 0, "files": []}
    allowed = set(channels if channels is not None else CHANNELS)
    for p in sorted(glob.glob(os.path.join(src_dir, "*.csv"))):
        m = _TAG_RX.match(os.path.basename(p))
        if not m:
            continue
        if m.group(2) not in allowed:
            if _remove(p):
                out["files"].append(os.path.basename(p))
            continue
        if d0 is None:
            continue
        head, rows = _read_rows(p)
        if not head:
            continue
        tcol = "time" if m.group(1) == "mail" else "start"
        keep = [r for r in rows if _in_window(_day(r.get(tcol)), d0, d1)]
        if len(keep) != len(rows):
            try:
                _write_csv(p, head, keep)
                out["rows"] += len(rows) - len(keep)
                out["files"].append(os.path.basename(p))
            except OSError:
                pass
    if d0 is not None:
        for cp in glob.glob(os.path.join(src_dir, "coverage_*.json")):
            cov = _read_json(cp)
            if cov is not None and trim_coverage(cov, d0):
                _write_json(cp, cov)
    return out


def prune_window(data_dir, period, cfg=None, ledger=None):
    r"""수집하지 않는 실행(run.py --skip-collect)의 기간 창 정리(D13 — 기간 밖 행은 실행마다 지운다): 출처 정제 파일
    (data\outlook\src — prune_src · collect.channels 밖의 출처 파일은 통째로) · 공용 파일 data\outlook\mail.csv·calendar.csv 의
    창 밖 행 · 원장(ledger)의 창 밖 날. → {"rows": 지운 행 수, "files": [바뀐 파일 이름], "ledger_days": 원장에서 지운 날 수}
    (원장은 고치기만 한다 — 저장은 부르는 쪽이 ledger_days 가 있을 때 한다). 수집 요약·출처 표(건수만)는 다음 수집이 새로 쓴다."""
    d0, d1 = _period(period)
    out = {"rows": 0, "files": [], "ledger_days": 0}
    if d0 is None:
        return out
    out_dir = os.path.join(str(data_dir), "outlook")
    res = prune_src(os.path.join(out_dir, "src"), (d0, d1), channels=channels_of(cfg))
    out["rows"] += int(res.get("rows") or 0)
    out["files"] += list(res.get("files") or [])
    if ledger is not None and hasattr(ledger, "prune"):
        try:
            out["ledger_days"] = int(ledger.prune(d0, d1) or 0)
        except Exception:  # noqa: BLE001 — 원장 정리 실패가 정리를 막지 않는다(다음 실행이 다시)
            pass
    for name, tcol in (("mail.csv", "time"), ("calendar.csv", "start")):
        p = os.path.join(out_dir, name)
        head, rows = _read_rows(p)
        if not head:
            continue
        keep = [r for r in rows if _in_window(_day(r.get(tcol)), d0, d1)]
        if len(keep) != len(rows):
            try:
                _write_csv(p, head, keep)
                out["rows"] += len(rows) - len(keep)
                out["files"].append(name)
            except OSError:
                pass
    return out


# ── 병합 ───────────────────────────────────────────────────────────────────────
def _merge_mail(src_dir, norm, cache, verified, allowed, d0, d1):
    acc, idx, per_day, by_src, dup = [], {}, {}, {}, 0
    for tag in _tags(src_dir, "mail", MAIL_PRI, allowed):
        new_idx = []
        for r in _read(os.path.join(src_dir, f"mail_{tag}.csv"), MAIL_COLS):
            day = _day(r["time"])
            if not _in_window(day, d0, d1):
                continue
            m = None if r["time_precision"].strip().lower() == "date" else _minute(r["time"])
            k = (_box(r["box"]), _keytext(norm, cache, r["subject"], r["conversation"], r["sender"]))
            hit = False
            for e in idx.get(k, ()):
                if m is not None and e["m"] is not None:
                    hit = abs(m - e["m"]) <= WIN_MIN
                elif e["day"] == day:
                    hit = True
                    if m is not None and e["m"] is None:      # 높은 출처의 '날짜만' 행 → 이 행의 시각으로 채운다
                        e["m"] = m
                        acc[e["i"]]["time"] = r["time"]
                        acc[e["i"]]["time_precision"] = "minute"
                if hit:
                    break
            if hit:
                dup += 1
                continue
            row = dict(r, **{SRC_COL: tag})
            if m is not None and not row["time_precision"]:
                row["time_precision"] = "minute"
            row["notice"] = "1" if str(row.get("notice") or "").strip() == "1" else "0"
            acc.append(row)
            new_idx.append((k, {"m": m, "day": day, "i": len(acc) - 1}))
            per_day[(day, _axis(r["box"]))] = per_day.get((day, _axis(r["box"])), 0) + 1
            by_src[tag] = by_src.get(tag, 0) + 1
        for k, e in new_idx:                  # 같은 출처 안의 행끼리는 지우지 않는다(이 출처를 다 본 뒤에 색인에 넣는다)
            idx.setdefault(k, []).append(e)
    n_cp = 0
    for tag in WITNESS:
        if tag not in allowed:
            continue
        for r in _read(os.path.join(src_dir, f"mail_{tag}.csv"), MAIL_COLS):
            day = _day(r["time"])
            ax = _axis(r["box"])
            if not _in_window(day, d0, d1) or per_day.get((day, ax)) or (verified and verified(day, ax)):
                continue
            row = dict(r, **{SRC_COL: tag})
            row["notice"] = "1" if str(row.get("notice") or "").strip() == "1" else "0"
            acc.append(row)
            by_src[tag] = by_src.get(tag, 0) + 1
            n_cp += 1
    acc.sort(key=lambda r: r["time"])
    return acc, by_src, dup, n_cp


def _merge_cal(src_dir, norm, cache, verified, allowed, d0, d1):
    acc, seen, per_day, by_src, dup = [], {}, {}, {}, 0
    cols = CAL_COLS + [CAL_BODY]
    for tag in _tags(src_dir, "cal", CAL_PRI, allowed):
        new_keys = []
        for r in _read(os.path.join(src_dir, f"cal_{tag}.csv"), cols):
            day = _day(r["start"])
            if not _in_window(day, d0, d1):
                continue
            m = _minute(r["start"])
            k = (m if m is not None else day, _keytext(norm, cache, r["subject"]))
            if k in seen:
                dup += 1
                body = r[CAL_BODY].strip()
                if body:                          # 접히는 행의 본문 — 남는 행의 본문이 비었으면 받는다
                    for i in seen[k]:
                        if not acc[i][CAL_BODY].strip():
                            acc[i][CAL_BODY] = body
                continue
            acc.append(dict(r, **{SRC_COL: tag}))
            new_keys.append((k, len(acc) - 1))
            per_day[day] = per_day.get(day, 0) + 1
            by_src[tag] = by_src.get(tag, 0) + 1
        for k, i in new_keys:
            seen.setdefault(k, []).append(i)
    n_cp = 0
    for tag in WITNESS:
        if tag not in allowed:
            continue
        for r in _read(os.path.join(src_dir, f"cal_{tag}.csv"), cols):
            day = _day(r["start"])
            if not _in_window(day, d0, d1) or per_day.get(day) or (verified and verified(day, "cal")):
                continue
            acc.append(dict(r, **{SRC_COL: tag}))
            by_src[tag] = by_src.get(tag, 0) + 1
            n_cp += 1
    acc.sort(key=lambda r: r["start"])
    return acc, by_src, dup, n_cp


def _sources_meta(src_dir, allowed):
    """mail_source_<ch>.json 들 → (me 합집합, selftest, warnings) — 쓸 수집 경로의 것만."""
    me, selftest, warns = [], False, []
    for ch in sorted(allowed):
        o = _read_json(os.path.join(src_dir, f"mail_source_{ch}.json"))
        if not o:
            continue
        for x in o.get("me") or []:
            if isinstance(x, str) and x.strip() and x.strip() not in me:
                me.append(x.strip())
        selftest = selftest or bool(o.get("selftest"))
        for w in o.get("warnings") or []:
            if isinstance(w, str) and w not in warns and len(warns) < 6:
                warns.append(w)
    return me, selftest, warns


def _src_rows(src_dir, allowed):
    """경로별 정제 파일 행 수(메일 + 일정) — 요약의 channels.rows."""
    out = {}
    for ch in allowed:
        n = 0
        for kind in ("mail", "cal"):
            _h, rows = _read_rows(os.path.join(src_dir, f"{kind}_{ch}.csv"))
            n += len(rows)
        out[ch] = n
    return out


def merge(src_dir, out_dir, *, verified=None, period=None, norm=None, today=None, cfg=None, channels=None, ledger=None):
    """경로별 정제 파일 → out_dir\\mail.csv(§5.1)·calendar.csv(§5.2)·mail_source.json.
    verified(날, 축)→bool 은 원장(coverage.Ledger.is_verified). period(d0, d1)가 있으면 창 밖 행을 공용 파일에 넣지 않고 출처 파일·
    COM 완료 표·원장(ledger — 없으면 verified 의 주인이 Ledger 면 그것)에서도 지운다. channels(없으면 config collect.channels) 밖의
    출처 파일은 읽지 않고 지운다. 출처 파일이 하나도 없으면 공용 파일을 건드리지 않는다.
    → 정보 dict {ok, mail, calendar, sources, cal_sources, dup, copilot, kept{mail_in,mail_out,meetings}, src_rows{ch: n},
       pruned, internal_domains, error, …}"""
    norm = norm or _default_norm()
    cache = {}
    allowed = channels_of(cfg, channels)
    d0, d1 = _period(period)
    pruned = prune_src(src_dir, (d0, d1) if d0 else None, channels=allowed)
    led = ledger if ledger is not None else getattr(verified, "__self__", None)
    if d0 and led is not None and hasattr(led, "prune"):
        try:
            led.prune(d0, d1)
        except Exception:  # noqa: BLE001 — 원장 정리 실패가 병합을 막지 않는다(다음 실행이 다시)
            pass
    mtags = _tags(src_dir, "mail", MAIL_PRI, allowed)
    ctags = _tags(src_dir, "cal", CAL_PRI, allowed)
    has_cp = any(os.path.exists(os.path.join(src_dir, f"{k}_{t}.csv")) for k in ("mail", "cal") for t in WITNESS
                 if t in allowed)
    if not mtags and not ctags and not has_cp:
        return {"ok": False, "error": "no_sources", "mail": 0, "calendar": 0, "sources": {}, "cal_sources": {},
                "kept": dict.fromkeys(KEPT_KEYS, 0), "src_rows": dict.fromkeys(allowed, 0), "pruned": pruned}
    mail, msrc, mdup, mcp = _merge_mail(src_dir, norm, cache, verified, allowed, d0, d1)
    cal, csrc, cdup, ccp = _merge_cal(src_dir, norm, cache, verified, allowed, d0, d1)
    body_on = bool(afcfg.get(cfg, "calendar.collectBody"))
    if not body_on:
        for r in cal:
            r[CAL_BODY] = ""
    kept = {"mail_in": sum(1 for r in mail if _box(r["box"]) != "sent"),
            "mail_out": sum(1 for r in mail if _box(r["box"]) == "sent"), "meetings": len(cal)}
    info = {"ok": True, "mail": len(mail), "calendar": len(cal), "sources": msrc, "cal_sources": csrc,
            "dup": mdup + cdup, "copilot": mcp + ccp, "error": "", "kept": kept, "pruned": pruned,
            "src_rows": _src_rows(src_dir, allowed), "channels": list(allowed),
            "cal_body": sum(1 for r in cal if str(r.get(CAL_BODY) or "").strip())}
    try:
        os.makedirs(out_dir, exist_ok=True)
        _write_csv(os.path.join(out_dir, "mail.csv"), MAIL_COLS, mail)
        _write_csv(os.path.join(out_dir, "calendar.csv"), CAL_COLS + ([CAL_BODY] if body_on else []), cal)
    except OSError as e:
        info.update(ok=False, error=f"쓰기 실패({type(e).__name__}) — Excel 등에서 연 파일을 닫으세요")
        return info
    me, selftest, warns = _sources_meta(src_dir, allowed)
    try:
        import privacy
        info["internal_domains"] = sorted(privacy.internal_domains(cfg, [x for x in me if "@" in x]))
    except Exception:  # noqa: BLE001 — 요약용(실패하면 빈 목록)
        info["internal_domains"] = []
    order = {t: i for i, t in enumerate(MAIL_PRI + WITNESS)}
    primary = (sorted(msrc.items(), key=lambda kv: (-kv[1], order.get(kv[0], 99)))[0][0] if msrc
               else (mtags[0] if mtags else ""))
    n_date = sum(1 for r in mail if (r.get("time_precision") or "").strip().lower() == "date")
    unc, cal_ok = [], bool(csrc.get("com"))
    if verified and d0:
        today = today or date.today()
        a, b = date.fromisoformat(d0), date.fromisoformat(d1)
        hi = min(b, today - timedelta(days=1))
        months, cal_ok, d = set(), True, a
        while d <= hi:
            s = d.isoformat()
            if not all(verified(s, ax) for ax in ("mail_in", "mail_out", "cal")):
                months.add(s[:7])
            if not verified(s, "cal"):
                cal_ok = False
            d += timedelta(days=1)
        unc = sorted(months)
    src = {"product": "AgentFinder32", "source": primary, "sources": msrc, "cal_sources": csrc,
           "when": _today(), "mail": len(mail), "calendar": len(cal), "mail_rows": len(mail),
           "date_only": n_date, "selftest": selftest, "uncovered_months": unc, "coverage_complete": not unc,
           "calendar_complete": cal_ok, "me": me, "warnings": warns, "period": [d0, d1] if d0 else [],
           "channels": list(allowed), "merged": True, "ver": MERGE_VER}
    _write_json(os.path.join(out_dir, "mail_source.json"), src)
    info.update(primary=primary, date_only=n_date, uncovered_months=unc)
    return info


# ── 수집 요약(§5.3) ────────────────────────────────────────────────────────────
def _add_counts(acc, c):
    """G1 건수 하나(dict — {"kept","excluded"} 또는 excluded 키를 바로 가진 dict)를 acc 에 더한다."""
    if not isinstance(c, dict):
        return
    ex = c.get("excluded") if isinstance(c.get("excluded"), dict) else c
    for k in EXCLUDE_KEYS:
        try:
            acc[k] += int(ex.get(k) or 0)
        except (TypeError, ValueError):
            pass


def save_g1_counts(src_dir, ch, counts, *, pre=None):
    r"""경로 ch 의 마지막 G1 건수 → src_dir\g1_<ch>.json {"product","src","when","kept","excluded","out_of_period"}.
    pre = 수집기가 구조 규칙으로 미리 뺀 건수(COM AF32STATUS counts.excluded — private·admin)를 excluded 에 더한다."""
    ex = dict.fromkeys(EXCLUDE_KEYS, 0)
    _add_counts(ex, counts)
    _add_counts(ex, pre)
    kept = dict.fromkeys(KEPT_KEYS, 0)
    for k in KEPT_KEYS:
        try:
            kept[k] = int(((counts or {}).get("kept") or {}).get(k) or 0)
        except (TypeError, ValueError, AttributeError):
            pass
    o = {"product": "AgentFinder32", "src": ch, "when": _today(), "kept": kept, "excluded": ex,
         "out_of_period": int((counts or {}).get("out_of_period") or 0) if isinstance(counts, dict) else 0}
    _write_json(os.path.join(src_dir, f"g1_{ch}.json"), o)
    return o


def load_g1_counts(src_dir, channels=None):
    """src_dir\\g1_<ch>.json 들 → {ch: {"kept","excluded",…}} (쓸 수집 경로의 것만)."""
    out = {}
    for ch in channels if channels is not None else CHANNELS:
        o = _read_json(os.path.join(src_dir, f"g1_{ch}.json"))
        if o:
            out[ch] = o
    return out


def write_summary(out_dir, *, period, clamp, channels, g1_counts, merge_info, internal_domains=None):
    r"""data\outlook\collect_summary.json(§5.3) 을 쓰고 그 dict 를 돌려준다(이 PC 안에서만 — 공유하지 않는다).
      period        (d0, d1) | {"from","to"}
      clamp         period.clamp 의 info({"clamped": bool, "requested": …}) — 잘리지 않았으면 null 로 적는다
      channels      {ch: rc | {"rc": rc}} 또는 경로 이름 목록 — 이번에 돈 경로의 rc(돌지 않았으면 null)
      g1_counts     None 이면 out_dir\src\g1_<ch>.json 을 모아 쓴다 · {ch: counts} · counts 하나 · counts 목록
      merge_info    merge() 의 결과 — kept·src_rows·internal_domains
    excluded 는 경로별 G1 건수(수집기가 미리 뺀 구조 규칙 건수 포함)의 합이다."""
    d0, d1 = _period(period)
    mi = merge_info if isinstance(merge_info, dict) else {}
    given_rows = {}
    if isinstance(channels, dict):
        names = channels_of(channels=list(channels))
        rcs = {}
        for ch in names:
            v = channels.get(ch)
            if isinstance(v, dict) and isinstance(v.get("rows"), int) and not isinstance(v.get("rows"), bool):
                given_rows[ch] = v["rows"]
            v = v.get("rc") if isinstance(v, dict) else v
            try:
                rcs[ch] = None if v is None else int(v)
            except (TypeError, ValueError):
                rcs[ch] = None
    else:
        names = channels_of(channels=channels) if channels else list(mi.get("channels") or CHANNELS)
        rcs = dict.fromkeys(names)
    for ch in mi.get("channels") or ():
        if ch not in names:
            names.append(ch)
            rcs.setdefault(ch, None)
    src_dir = os.path.join(out_dir, "src")
    if g1_counts is None:
        g1_counts = load_g1_counts(src_dir, names)
    ex = dict.fromkeys(EXCLUDE_KEYS, 0)
    if isinstance(g1_counts, dict) and any(k in g1_counts for k in ("excluded", "kept") + EXCLUDE_KEYS):
        _add_counts(ex, g1_counts)
    elif isinstance(g1_counts, dict):
        for c in g1_counts.values():
            _add_counts(ex, c)
    elif isinstance(g1_counts, (list, tuple)):
        for c in g1_counts:
            _add_counts(ex, c)
    rows = dict(mi.get("src_rows") if isinstance(mi.get("src_rows"), dict) else {}, **given_rows)
    src_k = mi.get("kept") if isinstance(mi.get("kept"), dict) else None
    if src_k is None and isinstance(g1_counts, dict) and isinstance(g1_counts.get("kept"), dict):
        src_k = g1_counts["kept"]
    kept = {k: int((src_k or {}).get(k) or 0) for k in KEPT_KEYS}
    dom = internal_domains
    if dom is None:
        dom = mi.get("internal_domains")
    if not dom and isinstance(g1_counts, dict) and isinstance(g1_counts.get("internal_domains"), (list, tuple)):
        dom = g1_counts["internal_domains"]
    cl = clamp if isinstance(clamp, dict) and clamp.get("clamped") else None
    o = {"product": "AgentFinder32",
         "period": {"from": d0, "to": d1},
         "clamped": cl,
         "channels": {ch: {"rc": rcs.get(ch), "rows": int(rows.get(ch) or 0)} for ch in names},
         "kept": kept,
         "excluded": ex,
         "internal_domains": sorted({str(x).strip().lower() for x in dom or () if str(x).strip()})}
    _write_json(os.path.join(out_dir, SUMMARY_FILE), o)
    return o


# ── COM 원자료 G1(§5.0) ─────────────────────────────────────────────────────────
def _spans(v):
    """구간 표 → [('YYYY-MM-DD', 'YYYY-MM-DD'(끝 제외))] — [[a,b],…] 와 PowerShell 이 펴 낸 [a,b,c,d] 꼴 모두 받는다."""
    out = []
    if not isinstance(v, (list, tuple)):
        return out
    flat = [x for x in v if isinstance(x, str)]
    if flat and len(flat) == len(v):
        v = [flat[i:i + 2] for i in range(0, len(flat) - 1, 2)]
    for x in v:
        if isinstance(x, (list, tuple)) and len(x) >= 2:
            a, b = _day(x[0]), _day(x[1])
            if a and b:
                out.append((a, b))
    return out


def range_merge(spans, kind, period=None):
    """g1_file 의 merge — 옛 정제 행(old)과 이번 정제 행(new) → 쓸 행. spans = {"replace": 구간, "append": 구간}(끝 제외).
    · replace 구간(이번에 그 달을 처음부터 다시 읽음)의 옛 행은 버리고 이번 행으로 바꾼다(0건이면 0건).
    · append 구간(예산에 닿아 멈춘 달을 이어 읽음)의 옛 행은 두고 이번 행을 더한다 — 일정은 같은 회의(시작·끝·제목·장소)를 한 번만.
    · 기간 창(period) 밖의 옛 행은 버린다(D13). 시각순."""
    sp = spans if isinstance(spans, dict) else {}
    rep, app = _spans(sp.get("replace")), _spans(sp.get("append"))
    d0, d1 = _period(period)
    tcol = "time" if kind == "mail" else "start"

    def inside(day, rs):
        return any(a <= day < b for a, b in rs)

    def key(r):
        return tuple(str(r.get(c) or "") for c in ("start", "end", "subject", "location"))

    def merge(old, new):
        keep = []
        for r in old or ():
            d = _day(r.get(tcol))
            if d and not inside(d, rep) and _in_window(d, d0, d1):
                keep.append(r)
        add = list(new or ())
        if kind != "mail" and app:
            seen = {key(r) for r in keep if inside(_day(r.get(tcol)), app)}
            add = [r for r in add if not (inside(_day(r.get(tcol)), app) and key(r) in seen)]
        out = keep + add
        out.sort(key=lambda r: str(r.get(tcol) or ""))
        return out
    return merge


def _read_raw_rows(path):
    r"""COM 원자료 CSV(§5.0) → dict 행 목록 — UTF-8(BOM 허용), 안 되면 CP949(privacy.g1_file 과 같은 읽기). 못 읽으면 []."""
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError:
        return []
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp949", "replace")
    try:
        return [r for r in csv.DictReader(io.StringIO(text, newline="")) if isinstance(r, dict)]
    except csv.Error:
        return []


def g1_com(root, cfg, *, period=None, tag="com"):
    r"""COM 원자료 → G1 → 정제 파일(§5.0 → §5.1/§5.2). 원자료(data\outlook\raw\mail_<tag>.csv·cal_<tag>.csv)와 구간 표
    (<tag>_manifest.json)는 결과와 상관없이 지운다. 구간 표가 없으면(쓰다 끊긴 원자료) 합치지 않고 지운다(그 달들은 다음 실행이
    다시 읽는다). 둘 다 정제되면 구간 표의 완료 표를 창 시작으로 줄여 src\coverage_<tag>.json 으로 확정하고 G1 건수를
    src\g1_<tag>.json 에 남긴다. 제한 고객 목록 없음·사내 도메인 없음은 privacy.SetupRefused 를 다시 던진다(원자료는 지운 뒤).
    → {"ran", "kept", "excluded", "out_of_period", "kinds": {"mail": {...}, "cal": {...}}, "committed", "error"}"""
    import meetnote
    import privacy
    root = os.path.abspath(str(root))
    raw_dir = os.path.join(root, "data", "outlook", "raw")
    src_dir = os.path.join(root, "data", "outlook", "src")
    raws = {"mail": os.path.join(raw_dir, f"mail_{tag}.csv"), "cal": os.path.join(raw_dir, f"cal_{tag}.csv")}
    man_p = os.path.join(raw_dir, f"{tag}_manifest.json")
    info = {"ran": False, "kept": dict.fromkeys(KEPT_KEYS, 0), "excluded": dict.fromkeys(EXCLUDE_KEYS, 0),
            "out_of_period": 0, "kinds": {}, "committed": False, "error": ""}
    have = [k for k, p in raws.items() if os.path.exists(p)]
    if not have and not os.path.exists(man_p):
        return info
    man = _read_json(man_p)
    try:
        if man is None:
            info["error"] = "manifest_missing"
            return info
        info["ran"] = True
        per = period or man.get("period")
        d0, d1 = _period(per)
        me = [str(x) for x in man.get("me") or [] if isinstance(x, str)]
        ctx = privacy.G1Context(cfg, root, src=tag, my_addresses=me, period=(d0, d1) if d0 else None)
        os.makedirs(src_dir, exist_ok=True)
        if os.path.exists(raws["cal"]):
            meetnote.prep_raw_body(raws["cal"])
        for kind in ("mail", "cal"):          # 두 원자료의 참여자를 먼저 모두 본다 — 일정에서만 본 이름도 메일 제목에서 가린다
            if os.path.exists(raws[kind]):
                ctx.prepare(_read_raw_rows(raws[kind]), kind)
        ok = True
        for kind in ("mail", "cal"):
            if not os.path.exists(raws[kind]):
                ok = False
                continue
            out_p = os.path.join(src_dir, f"{kind}_{tag}.csv")
            spans = man.get(kind) if isinstance(man.get(kind), dict) else {}
            res = privacy.g1_file(raws[kind], out_p, kind, cfg=cfg, root=root, period=(d0, d1) if d0 else None, src=tag,
                                  my_addresses=me, merge=range_merge(spans, kind, (d0, d1) if d0 else None), ctx=ctx)
            info["kinds"][kind] = {"rows_in": int(res.get("rows_in") or 0)}
        tot = ctx.counts()
        info["kept"] = dict(tot.get("kept") or {})
        _add_counts(info["excluded"], tot)
        _add_counts(info["excluded"], man.get("excluded"))
        info["out_of_period"] = int(tot.get("out_of_period") or 0)
        if ok:
            cov = man.get("coverage") if isinstance(man.get("coverage"), dict) else None
            if cov is not None:
                trim_coverage(cov, d0)
                info["committed"] = _write_json(os.path.join(src_dir, f"coverage_{tag}.json"), cov)
            save_g1_counts(src_dir, tag, tot, pre=man.get("excluded"))
        return info
    finally:
        for p in list(raws.values()) + [man_p]:
            if os.path.exists(p):
                _remove(p)


# ── G1 규칙 판 ─────────────────────────────────────────────────────────────────
RULES_SKIP = ("contact",)        # privacy 설정 중 G1 결과와 상관없는 키(문의처 — 안내문에만 나온다)


def rules_tag(cfg, root=None):
    """정제(G1) 결과를 바꾸는 규칙의 지문 — privacy 판(RULES_VER)·privacy 설정(문의처·설명 키는 빼고)·제목 저장·일정 본문·
    공지 발신자·제한 고객 목록(sha256)."""
    import privacy
    c, _w = afcfg.effective(cfg if isinstance(cfg, dict) else {})
    try:
        rs = privacy.load_restricted(c, root).sha256
    except Exception:  # noqa: BLE001 — 목록이 없으면 그 자체가 지문(분석은 다른 곳에서 거부된다)
        rs = "missing"
    pv = c.get("privacy")
    if isinstance(pv, dict):
        pv = {k: v for k, v in pv.items() if k not in RULES_SKIP and not str(k).startswith("_")}
    blob = json.dumps({"rules": getattr(privacy, "RULES_VER", ""), "merge": MERGE_VER, "privacy": pv,
                       "store": afcfg.get(c, "storeMailSubject"), "body": afcfg.get(c, "calendar.collectBody"),
                       "notice": c.get("noticeSenders"), "restricted": rs}, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def check_rules(root, cfg):
    r"""G1 규칙이 지난 정제 때와 다르면 지난 정제 파일(data\outlook\src\*.csv·coverage_*.json·g1_*.json)·공용 파일(mail.csv·
    calendar.csv)·원장(data\coverage_ledger.json)을 지워 새 규칙으로 다시 모으게 한다. 처음(지문 파일 없음)이면 지문만 적는다.
    run.py 는 원장을 열기 전에 부른다. → {"changed": bool, "deleted": [파일 이름]}"""
    root = os.path.abspath(str(root))
    src_dir = os.path.join(root, "data", "outlook", "src")
    p = os.path.join(src_dir, RULES_FILE)
    cur = rules_tag(cfg, root)
    old = (_read_json(p) or {}).get("tag")
    out = {"changed": False, "deleted": []}
    if old == cur:
        return out
    if old:
        out["changed"] = True
        pats = [os.path.join(src_dir, x) for x in ("mail_*.csv", "cal_*.csv", "coverage_*.json", "g1_*.json")]
        pats += [os.path.join(root, "data", "outlook", x) for x in ("mail.csv", "calendar.csv")]
        pats += [os.path.join(root, "data", "coverage_ledger.json")]
        for pat in pats:
            for f in glob.glob(pat):
                if os.path.basename(f) == RULES_FILE:
                    continue
                if _remove(f):
                    out["deleted"].append(os.path.basename(f))
    _write_json(p, {"product": "AgentFinder32", "tag": cur, "when": _today()})
    return out
