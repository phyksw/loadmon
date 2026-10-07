# -*- coding: utf-8 -*-
r"""core\mailmerge.py — 출처별 메일·일정 파일 → data\outlook\mail.csv·calendar.csv·mail_source.json (LM28 P5·REQ-18).

각 수집기는 자기 파일만 쓴다: data\outlook\src\mail_<tag>.csv·cal_<tag>.csv·mail_source_<tag>.json
(tag: com·index·owa·copilot·import·legacy). 이 모듈만 분석이 읽는 공용 파일을 쓴다 — 통째 덮어쓰기로 한 출처가 다른 출처의
자료를 지우는 일이 없다(LM24 는 대체 경로가 mail.csv 를 다시 쓰며 COM 자료·완료 표를 버렸다).
  메일 키: (편지함, 분, 정제 제목 40자) — 높은 출처가 받은 메일과 ±2분 안의 같은 제목이면 낮은 출처의 행은 버린다.
    · 같은 출처 안의 행은 서로 지우지 않는다(같은 분에 같은 제목으로 두 번 온 알림은 실제 2통 — COM 규칙).
    · 높은 출처의 '날짜만' 행(time_precision=date)은 낮은 출처의 분 단위 같은 메일로 시각을 채운다.
    · 우선순위: com > owa > index > import > legacy. 제목이 비면(storeMailSubject=false) 대화 해시, 그것도 없으면 보낸이.
  일정 키: (시작 분, 정제 제목 40자) — 우선순위 com > owa > import > index > legacy.
  Copilot 행(증인)은 그날 그 축에 다른 출처 행이 0이고, 원장이 그날을 ok·zero_ok 로 확인하지 않았을 때만 넣는다.
  출력 끝 열 'src' = 그 행을 준 출처(분석은 열 이름으로 읽는다 — 끝 열 추가는 extract._read 와 맞다).
  mail_source.json 은 LM24 키를 유지한다: source(주 출처)·mail_rows·date_only·selftest·uncovered_months·me[](합집합)
  + LM28 키 sources{출처: 행 수}·calendar_complete·coverage_complete·period·ver.
"""
import csv
import json
import os
import re
import time
from datetime import date, datetime, timedelta

MAIL_COLS = ["box", "time", "sender", "subject", "conversation", "rcv", "time_precision"]
CAL_COLS = ["start", "end", "all_day", "busy_status", "subject", "categories", "location", "response", "meeting_status"]
SRC_COL = "src"
MAIL_PRI = ("com", "owa", "index", "import", "legacy")
CAL_PRI = ("com", "owa", "import", "index", "legacy")
WITNESS = ("copilot",)
WIN_MIN = 2                      # 같은 메일로 보는 시각 차(분)
MERGE_VER = "LM28-MERGE-1"
_WS = re.compile(r"\s+")
_TAG_RX = re.compile(r"^(mail|cal)_([A-Za-z0-9_-]{1,24})\.csv$")
_EPOCH = datetime(2000, 1, 1)


def _tags(src_dir, kind, pri):
    """src 폴더의 <kind>_<tag>.csv → tag 목록(우선순위 순, 모르는 tag 는 뒤 — 증인은 빼고)"""
    try:
        names = os.listdir(src_dir)
    except OSError:
        return []
    found = []
    for n in names:
        m = _TAG_RX.match(n)
        if m and m.group(1) == kind:
            found.append(m.group(2))
    order = {t: i for i, t in enumerate(pri)}
    return sorted((t for t in found if t not in WITNESS), key=lambda t: (order.get(t, len(pri)), t))


def _read(path, cols):
    """CSV → dict 목록(빠진 열은 빈 값). 머리말 이름으로 읽는다 — 옛 6열 파일도 받는다."""
    try:
        with open(path, encoding="utf-8-sig", errors="replace", newline="") as f:
            rows = list(csv.DictReader(f))
    except (OSError, csv.Error):
        return []
    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        out.append({c: ("" if r.get(c) is None else str(r.get(c))) for c in cols})
    return out


def _minute(t):
    """'YYYY-MM-DD HH:MM[:SS]' → 2000-01-01 부터의 분(날짜만이면 None)"""
    s = str(t or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return int((datetime.strptime(s, fmt) - _EPOCH).total_seconds() // 60)
        except ValueError:
            continue
    return None


def _day(t):
    s = str(t or "").strip()[:10]
    try:
        date.fromisoformat(s)
        return s
    except ValueError:
        return ""


def _default_norm():
    """정제 함수 — core\\privacy.sanitize(기본 문맥). 못 쓰면 원문 그대로."""
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


def _merge_mail(src_dir, norm, cache, verified):
    acc, idx, per_day, by_src, dup = [], {}, {}, {}, 0
    for tag in _tags(src_dir, "mail", MAIL_PRI):
        new_idx = []
        for r in _read(os.path.join(src_dir, f"mail_{tag}.csv"), MAIL_COLS):
            day = _day(r["time"])
            if not day:
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
            acc.append(row)
            new_idx.append((k, {"m": m, "day": day, "i": len(acc) - 1}))
            per_day[(day, _axis(r["box"]))] = per_day.get((day, _axis(r["box"])), 0) + 1
            by_src[tag] = by_src.get(tag, 0) + 1
        for k, e in new_idx:                  # 같은 출처 안의 행끼리는 지우지 않는다(이 출처를 다 본 뒤에 색인에 넣는다)
            idx.setdefault(k, []).append(e)
    n_cp = 0
    for tag in WITNESS:
        for r in _read(os.path.join(src_dir, f"mail_{tag}.csv"), MAIL_COLS):
            day = _day(r["time"])
            ax = _axis(r["box"])
            if not day or per_day.get((day, ax)) or (verified and verified(day, ax)):
                continue
            acc.append(dict(r, **{SRC_COL: tag}))
            by_src[tag] = by_src.get(tag, 0) + 1
            n_cp += 1
    acc.sort(key=lambda r: r["time"])
    return acc, by_src, dup, n_cp


def _merge_cal(src_dir, norm, cache, verified):
    acc, seen, per_day, by_src, dup = [], set(), {}, {}, 0
    for tag in _tags(src_dir, "cal", CAL_PRI):
        new_keys = []
        for r in _read(os.path.join(src_dir, f"cal_{tag}.csv"), CAL_COLS):
            day = _day(r["start"])
            if not day:
                continue
            m = _minute(r["start"])
            k = (m if m is not None else day, _keytext(norm, cache, r["subject"]))
            if k in seen:
                dup += 1
                continue
            acc.append(dict(r, **{SRC_COL: tag}))
            new_keys.append(k)
            per_day[day] = per_day.get(day, 0) + 1
            by_src[tag] = by_src.get(tag, 0) + 1
        seen.update(new_keys)
    n_cp = 0
    for tag in WITNESS:
        for r in _read(os.path.join(src_dir, f"cal_{tag}.csv"), CAL_COLS):
            day = _day(r["start"])
            if not day or per_day.get(day) or (verified and verified(day, "cal")):
                continue
            acc.append(dict(r, **{SRC_COL: tag}))
            by_src[tag] = by_src.get(tag, 0) + 1
            n_cp += 1
    acc.sort(key=lambda r: r["start"])
    return acc, by_src, dup, n_cp


def _write_csv(path, cols, rows):
    tmp = f"{path}.{os.getpid()}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(cols + [SRC_COL])
            for r in rows:
                w.writerow([r.get(c, "") for c in cols] + [r.get(SRC_COL, "")])
        os.replace(tmp, path)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def _sources_meta(src_dir):
    """mail_source_<tag>.json 들 → (me 합집합, selftest, warnings)"""
    me, selftest, warns = [], False, []
    try:
        names = sorted(os.listdir(src_dir))
    except OSError:
        names = []
    for n in names:
        if not (n.startswith("mail_source") and n.endswith(".json")):
            continue
        try:
            with open(os.path.join(src_dir, n), encoding="utf-8-sig") as f:
                o = json.load(f)
        except (OSError, ValueError):
            continue
        if not isinstance(o, dict):
            continue
        for x in o.get("me") or []:
            if isinstance(x, str) and x.strip() and x.strip() not in me:
                me.append(x.strip())
        selftest = selftest or bool(o.get("selftest"))
        for w in o.get("warnings") or []:
            if isinstance(w, str) and w not in warns and len(warns) < 6:
                warns.append(w)
    return me, selftest, warns


def merge(src_dir, out_dir, *, verified=None, period=None, norm=None, today=None):
    """출처별 파일 → out_dir\\mail.csv·calendar.csv·mail_source.json. verified(날, 축)→bool 은 원장(coverage.Ledger.is_verified).
    출처 파일이 하나도 없으면 공용 파일을 건드리지 않는다. → 정보 dict {ok, mail, calendar, sources, cal_sources, dup, copilot, …}"""
    norm = norm or _default_norm()
    cache = {}
    mtags, ctags = _tags(src_dir, "mail", MAIL_PRI), _tags(src_dir, "cal", CAL_PRI)
    has_cp = any(os.path.exists(os.path.join(src_dir, f"{k}_{t}.csv")) for k in ("mail", "cal") for t in WITNESS)
    if not mtags and not ctags and not has_cp:
        return {"ok": False, "error": "no_sources", "mail": 0, "calendar": 0, "sources": {}, "cal_sources": {}}
    mail, msrc, mdup, mcp = _merge_mail(src_dir, norm, cache, verified)
    cal, csrc, cdup, ccp = _merge_cal(src_dir, norm, cache, verified)
    info = {"ok": True, "mail": len(mail), "calendar": len(cal), "sources": msrc, "cal_sources": csrc,
            "dup": mdup + cdup, "copilot": mcp + ccp, "error": ""}
    try:
        os.makedirs(out_dir, exist_ok=True)
        _write_csv(os.path.join(out_dir, "mail.csv"), MAIL_COLS, mail)
        _write_csv(os.path.join(out_dir, "calendar.csv"), CAL_COLS, cal)
    except OSError as e:
        info.update(ok=False, error=f"쓰기 실패({type(e).__name__}) — Excel 등에서 연 파일을 닫으세요")
        return info
    me, selftest, warns = _sources_meta(src_dir)
    order = {t: i for i, t in enumerate(MAIL_PRI + WITNESS)}
    primary = (sorted(msrc.items(), key=lambda kv: (-kv[1], order.get(kv[0], 99)))[0][0] if msrc
               else (mtags[0] if mtags else ""))
    n_date = sum(1 for r in mail if (r.get("time_precision") or "").strip().lower() == "date")
    unc, cal_ok = [], bool(csrc.get("com"))
    if verified and period:
        today = today or date.today()
        try:
            d0, d1 = date.fromisoformat(str(period[0])[:10]), date.fromisoformat(str(period[-1])[:10])
        except (TypeError, ValueError, IndexError):
            d0 = d1 = None
        if d0 and d1:
            hi = min(d1, today - timedelta(days=1))       # 오늘은 아직 메일이 온다 — 미확인으로 세지 않는다
            months, cal_ok, d = set(), True, d0
            while d <= hi:
                s = d.isoformat()
                if not all(verified(s, ax) for ax in ("mail_in", "mail_out", "cal")):
                    months.add(s[:7])
                if not verified(s, "cal"):
                    cal_ok = False
                d += timedelta(days=1)
            unc = sorted(months)
    src = {"source": primary, "sources": msrc, "cal_sources": csrc, "when": time.strftime("%Y-%m-%d %H:%M"),
           "mail": len(mail), "calendar": len(cal), "mail_rows": len(mail), "date_only": n_date,
           "selftest": selftest, "uncovered_months": unc, "coverage_complete": not unc,
           "calendar_complete": cal_ok, "calendar_recurring_masters": 0, "me": me, "warnings": warns,
           "period": list(period) if period else [], "merged": True, "ver": MERGE_VER}
    try:
        tmp = os.path.join(out_dir, f"mail_source.json.{os.getpid()}.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(src, f, ensure_ascii=False)
        os.replace(tmp, os.path.join(out_dir, "mail_source.json"))
    except OSError:
        pass
    info.update(primary=primary, date_only=n_date, uncovered_months=unc)
    return info
