# -*- coding: utf-8 -*-
r"""Import-MailCal.py — 자동 경로가 모두 막힌 사람용 반입 파일 읽기(LM28 C-17 간소판). 원본은 읽기만 한다.
  python collect\Import-MailCal.py [--in data\import] [--out-dir data\outlook\src] [--from D] [--to D] [--me a@b.com,...]
· *.eml 머리(Date·From·To·Cc·Subject)만 — 보낸 메일 = 경로에 sent·보낸 폴더 또는 From 이 내 주소(--me·mail_source*.json me[])
· *.ics VEVENT + 단순 RRULE(DAILY·WEEKLY(BYDAY)·MONTHLY · INTERVAL·COUNT·UNTIL · EXDATE · 바뀐 회차 RECURRENCE-ID).
  Z 시각은 로컬로, TZID 시각은 그대로(로컬로 본다), 날짜만은 종일 · *.csv 우리 열(box,time,… / start,end,…)만
· *.msg 는 읽지 않는다(건수만). 출력 <out-dir>\mail_import.csv·cal_import.csv(입력 폴더 전체로 매번 다시) +
  마지막 줄 LMSTATUS(src import · rc 0 · 1 입력 없음 · 3 쓰기 실패)."""
import csv
import email.parser
import email.policy
import email.utils
import hashlib
import io
import json
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone

if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, errors="replace", encoding=sys.stdout.encoding or "utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAIL_HDR = "box,time,sender,subject,conversation,rcv,time_precision"
CAL_HDR = "start,end,all_day,busy_status,subject,categories,location,response,meeting_status"
SENT_DIR = re.compile(r"(?i)(^|[\\/])(sent[^\\/]*|보낸[^\\/]*)[\\/]")
WD = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}
F = "%Y-%m-%d %H:%M"
CAP = 500                        # 반복 일정 하나를 펼치는 회차 상한


def arg(flag, d=""):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv and sys.argv.index(flag) + 1 < len(sys.argv) else d


def read_eml(path, me, sent_hint=False):
    """.eml 머리 → 메일 행(7열) 또는 None(날짜 없음)."""
    with open(path, "rb") as f:
        msg = email.parser.BytesHeaderParser(policy=email.policy.default).parse(f)
    try:
        dt = email.utils.parsedate_to_datetime(str(msg.get("Date") or ""))
    except (TypeError, ValueError, IndexError):
        return None
    dt = dt.astimezone().replace(tzinfo=None) if dt.tzinfo else dt
    frm, to, cc = ([a.lower() for _, a in email.utils.getaddresses([str(msg.get(h) or "")]) if a]
                   for h in ("From", "To", "Cc"))
    sent = sent_hint or bool(me and frm and frm[0] in me)
    subj = re.sub(r"\s+", " ", str(msg.get("Subject") or "")).strip()
    name = email.utils.parseaddr(str(msg.get("From") or ""))[0] or (frm[0] if frm else "")
    rcv = "" if sent else ("cc" if me and any(a in me for a in cc) and not any(a in me for a in to) else "to")
    conv = re.sub(r"^((RE|FW|FWD|답장|전달|회신)\s*:\s*)+", "", subj, flags=re.I)
    return ["sent" if sent else "inbox", dt.strftime(F), name, subj, conv, rcv, "minute"]


def ics_dt(val, params=None):
    """DTSTART 값 → (로컬 datetime, 날짜만인가). Z 는 로컬로, TZID·떠 있는 시각은 그대로."""
    v = str(val or "").strip()
    if (params or {}).get("VALUE", "").upper() == "DATE" or re.fullmatch(r"\d{8}", v):
        return datetime.strptime(v[:8], "%Y%m%d"), True
    m = re.fullmatch(r"(\d{8})T(\d{4})(\d{2})?(Z)?", v)
    if not m:
        raise ValueError(v)
    dt = datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M")
    return (dt.replace(tzinfo=timezone(timedelta(0))).astimezone().replace(tzinfo=None) if m.group(4) else dt), False


def expand(st, en, rrule, skip, d1=None):
    """단순 RRULE 전개 → [(시작, 끝)]. skip = 빼는 회차('YYYYMMDD' — EXDATE·바뀐 회차, COUNT 에는 센다)."""
    r = {k.upper(): v for p in str(rrule or "").split(";") for k, _, v in [p.partition("=")] if v}
    freq, n = r.get("FREQ", "").upper(), max(1, int(r.get("INTERVAL") or 1))
    if freq not in ("DAILY", "WEEKLY", "MONTHLY") or (freq == "MONTHLY" and st.day > 28):
        return [(st, en)]                # 그 밖·29~31일 매월은 간소판 밖 — 첫 회차만
    count = int(r["COUNT"]) if r.get("COUNT", "").isdigit() else None
    until = ics_dt(r["UNTIL"])[0] if r.get("UNTIL") else None
    byday = sorted({WD[x[-2:].upper()] for x in r.get("BYDAY", "").split(",") if x[-2:].upper() in WD}
                   if freq == "WEEKLY" else ())
    out, k = [], 0
    for i in range(5000):
        b = st + timedelta(days=i * n) if freq == "DAILY" else st + timedelta(weeks=i * n)
        cands = [c for c in (b - timedelta(days=b.weekday() - w) for w in byday) if c >= st] if byday else [b]
        if freq == "MONTHLY":
            y, m = divmod(st.month - 1 + i * n, 12)
            cands = [st.replace(year=st.year + y, month=m + 1)]
        for c in cands:
            if (until and c > until) or (count is not None and k >= count) or len(out) >= CAP:
                return out
            k += 1
            if c.strftime("%Y%m%d") not in skip:
                out.append((c, c + (en - st)))
        if d1 and cands and min(cands).date() > d1:
            break
    return out


def read_ics(path, d0=None, d1=None):
    """.ics → 일정 행(7열). 바뀐 회차(RECURRENCE-ID)는 따로 한 행, 원 반복에서는 그 회차를 뺀다."""
    with open(path, encoding="utf-8-sig", errors="replace") as f:
        text = re.sub(r"\r?\n[ \t]", "", f.read())          # 접힌 줄(공백·탭으로 시작)을 앞 줄에 붙인다
    evs, ev = [], None
    for u in (x.strip() for x in text.splitlines()):
        head, _, val = u.partition(":")
        parts = head.split(";")
        name, params = parts[0].upper(), {k.upper(): v for p in parts[1:] for k, _, v in [p.partition("=")]}
        if u.upper() in ("BEGIN:VEVENT", "END:VEVENT"):
            evs += [ev] if (ev and "st" in ev and u.upper()[0] == "E") else []
            ev = {"ex": set()} if u.upper()[0] == "B" else None
        elif ev is None or not val:
            continue
        elif name in ("DTSTART", "DTEND", "RECURRENCE-ID"):
            try:
                dt, ad = ics_dt(val, params)
            except ValueError:
                continue
            ev.update({"DTSTART": {"st": dt, "ad": ad}, "DTEND": {"en": dt},
                       "RECURRENCE-ID": {"rid": dt.strftime("%Y%m%d")}}[name])
        elif name == "EXDATE":
            ev["ex"].update(x.strip()[:8] for x in val.split(","))
        elif name in ("SUMMARY", "LOCATION", "CATEGORIES", "UID", "RRULE", "TRANSP", "STATUS"):
            ev[name.lower()] = re.sub(r"\\([,;\\nN])", lambda m: " " if m.group(1) in "nN" else m.group(1), val).strip()
    moved = {}
    for e in evs:
        if e.get("rid"):
            moved.setdefault(e.get("uid", ""), set()).add(e["rid"])
    rows = []
    for e in evs:
        st, ad = e["st"], e.get("ad", False)
        en = e.get("en") or (st + timedelta(days=1) if ad else st + timedelta(minutes=30))
        skip = e["ex"] | (set() if e.get("rid") else moved.get(e.get("uid", ""), set()))
        busy = "0" if e.get("transp", "").upper() == "TRANSPARENT" else ("1" if e.get("status", "").upper() == "TENTATIVE" else "2")
        for a, b in expand(st, en, None if e.get("rid") else e.get("rrule"), skip, d1):
            b = b - timedelta(minutes=1) if ad else b          # 종일: 마지막 날 23:59
            if not ((d0 and b.date() < d0) or (d1 and a.date() > d1)):
                rows.append([a.strftime(F), b.strftime(F), str(bool(ad)), busy, e.get("summary", ""),
                             e.get("categories", ""), e.get("location", "")])
    return rows


def read_csv(path):
    """우리 열의 CSV → (메일 행, 일정 행). 머리가 다르면 ([], [])."""
    with open(path, encoding="utf-8-sig", errors="replace", newline="") as f:
        rd = list(csv.reader(f))
    hdr = [h.strip().lower() for h in (rd[0] if rd else [])][:2]
    if hdr == ["box", "time"]:
        return [(r + [""])[:6] + [(r[6] if len(r) > 6 and r[6] else "minute")] for r in rd[1:] if len(r) >= 6], []
    return [], ([r[:7] for r in rd[1:] if len(r) >= 7] if hdr == ["start", "end"] else [])


def my_addrs():
    out = {a.strip().lower() for a in arg("--me").split(",") if "@" in a}
    base = os.path.join(ROOT, "data", "outlook")
    for p in [os.path.join(d, n) for d in (base, os.path.join(base, "src")) if os.path.isdir(d)
              for n in os.listdir(d) if n.startswith("mail_source") and n.endswith(".json")]:
        try:
            with open(p, encoding="utf-8-sig") as f:
                out |= {str(a).lower() for a in (json.load(f).get("me") or []) if "@" in str(a)}
        except (OSError, ValueError, AttributeError):
            pass
    return out


def _esc(c):
    s = re.sub(r"[\r\n]+", " ", str(c or ""))
    return '"' + s.replace('"', '""') + '"' if ("," in s or '"' in s) else s


def write_csv(path, hdr, rows):
    n, tmp = hdr.count(",") + 1, path + ".tmp"
    with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
        f.write(hdr + "\n")
        for r in rows:
            f.write(",".join(_esc(c) for c in (list(r) + [""] * n)[:n]) + "\n")
    os.replace(tmp, path)


def main():
    in_dir = arg("--in") or os.path.join(ROOT, "data", "import")
    out_dir = arg("--out-dir") or os.path.join(ROOT, "data", "outlook", "src")
    d0 = date.fromisoformat(arg("--from")) if arg("--from") else date.today() - timedelta(days=400)
    d1 = date.fromisoformat(arg("--to")) if arg("--to") else date.today()
    try:
        with open(os.path.join(ROOT, "config", "config.json"), encoding="utf-8-sig") as f:
            store_subject = bool(json.load(f).get("storeMailSubject", True))
    except (OSError, ValueError, AttributeError):
        store_subject = True
    me, mail, cal, c = my_addrs(), [], [], {"eml": 0, "ics": 0, "csv": 0, "msg": 0, "bad": 0}
    for p in sorted(os.path.join(b, fn) for b, _d, fs in os.walk(in_dir) for fn in fs):
        ext = os.path.splitext(p)[1].lower()
        if ext not in (".eml", ".ics", ".csv", ".msg"):
            continue
        c[ext[1:]] += 1
        try:
            if ext == ".eml":
                r = read_eml(p, me, bool(SENT_DIR.search(os.path.relpath(p, in_dir))))
                mail, c["bad"] = (mail + [r], c["bad"]) if r else (mail, c["bad"] + 1)
            elif ext in (".ics", ".csv"):
                m2, c2 = ([], read_ics(p, d0, d1)) if ext == ".ics" else read_csv(p)
                mail, cal = mail + m2, cal + c2
        except (OSError, ValueError, TypeError) as e:
            c["bad"] += 1
            print(f"[import] 읽지 못함: {os.path.basename(p)} ({type(e).__name__})")
    if c["msg"]:
        print(f"[import] .msg {c['msg']}개는 읽지 않습니다 — Outlook 에서 .eml(메일)·.ics(일정)로 저장해 넣으세요")
    rc, why = (0, "") if (c["eml"] or c["ics"] or c["csv"]) else (1, "")
    if rc == 1:
        print(f"[import] 반입 파일이 없습니다({in_dir})")
    else:
        mail = [r for r in mail if d0.isoformat() <= str(r[1])[:10] <= d1.isoformat()]
        for r in ([] if store_subject else mail):     # 제목을 남기지 않는다 — conversation 은 짧은 해시(회신 이력 판정만)
            s = re.sub(r"\s+", " ", str(r[4] or "")).strip().lower()
            r[3], r[4] = "", ("#" + hashlib.sha1(s.encode("utf-8")).hexdigest()[:10] if s else "")
        for r in ([] if store_subject else cal):
            r[4] = ""
        mail = sorted({tuple(r[:4]): r for r in mail}.values(), key=lambda r: r[1])
        cal = sorted({(r[0], r[1], r[4]): r for r in cal}.values(), key=lambda r: r[0])
        try:
            os.makedirs(out_dir, exist_ok=True)
            write_csv(os.path.join(out_dir, "mail_import.csv"), MAIL_HDR, mail)
            write_csv(os.path.join(out_dir, "cal_import.csv"), CAL_HDR, cal)
        except OSError as e:
            rc, why = 3, "R-WRITE"
            print(f"[import] 쓰지 못함({type(e).__name__})")
        print(f"[import] 메일 {len(mail)}건 · 일정 {len(cal)}건 (eml {c['eml']} · ics {c['ics']} · csv {c['csv']} · 실패 {c['bad']})")
    c.update(mail_rows=len(mail), cal_rows=len(cal))
    print("LMSTATUS " + json.dumps({"v": 1, "src": "import", "rc": rc, "reason": why, "counts": c, "ranges": []}))
    return rc


if __name__ == "__main__":
    sys.exit(main())
