# -*- coding: utf-8 -*-
r"""mail.import · cal.import — 반입 폴더의 EML·ICS·CSV 를 읽어 정제 관문으로 넘기는 PY 수집기(CM §11.5, 계약 §2.17·§7.3).

    "<PY>" -X utf8 -I -B collect\Import-MailCal.py --kind mail|cal --pc <pc_id> [--in-dir P] [--from D --to D]
                                                  [--events jsonl|text|off]

원칙(CM §0·§11.5·§12, 계약 §1.5·§3.5):
  · 원문(제목·주소·본문·헤더)은 메모리에만 둔다. 디스크에는 ``lm27.privacy.sanitize.sanitize_record`` 를 통과한 봉인 행만
    ``lm27.store.SegmentWriter`` 로 쓴다(in-process — 파이프 없음). 원본 파일은 읽기만 하고 옮기거나 고치지 않는다(무부작용).
  · 처리 표식 = 수집 커서(``raw_cursor.json`` 의 그 src 값) ``{"done": {<파일 내용 sha256 앞 16자>: [크기, mtime_ns]}}``.
    파일 이름·경로는 커서에 넣지 않는다. 커서 저장은 ``SegmentWriter.flush()`` 성공 뒤에만(계약 §7.3 · X-300).
  · ``.msg`` 는 지원하지 않는다(바이너리 직접 파싱 = 금지 경계, CM §0). 건수만 ``skipped_msg`` 로 남긴다(X-314) — 메일 반입에서만 센다.
  · 원시 필드 이름은 P §10.2 원시 이름(계약 §3.5). CSV 헤더도 같은 영문 이름이고 시각 열은 ``ts_local``(오프셋 포함 ISO),
    일정 끝은 ``ts_end_local``. 남는 열은 버리고 모자란 열은 빈칸으로 본다.
  · ICS 반복(RRULE)은 단순 주기(DAILY · WEEKLY(BYDAY) · MONTHLY(BYMONTHDAY 하나 또는 n번째 요일 하나) · YEARLY)만
    펼친다. 그 밖의 규칙은 마스터 1건 + ``recurrence_incomplete`` 로 남긴다(CM §11.5).
  · 시간대: ``zoneinfo`` 를 쓰지 않는다(L-04). ICS 는 파일 안 VTIMEZONE 규칙으로, 없으면 고정 오프셋 표 → 이 PC 시간대
    (+ ``flags.utc_suspect``). ``ts_local_offset`` 은 ``lm27.util.tz.capture_offset_min``.

rc(계약 §8.1): 0 새 레코드를 읽어 넘김(정제기가 버린 것도 '관측'이다) · 1 대상 없음(반입 폴더·파일 없음) ·
4 읽었지만 새것 0(이미 반입한 파일뿐) · 3 정제·저장 실패(R-TRANSPORT — 커서 그대로). 2 는 쓰지 않는다(로그인 없음).
결과: stderr 마지막 줄 ``{"_status": {…}}``(계약 v1.2 §0.7 C1 한 모양 — 숫자·열거·사유 코드만) + ``--events jsonl``(기본)
이면 stdout 에 ``result`` 이벤트.
"""
import argparse
import base64
import csv
import email
import email.policy
import hashlib
import html
import io
import json
import os
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from email.header import decode_header, make_header
from email.utils import getaddresses, parsedate_to_datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from lm27.config import load_config  # noqa: E402
from lm27.paths import Paths  # noqa: E402
from lm27.util import events, fsx, tz  # noqa: E402

KINDS_HERE = ("mail", "cal")
SRC_OF = {"mail": "mail.import", "cal": "cal.import"}
RC_SAVED, RC_NONE, RC_DRIVER, RC_NONEW = 0, 1, 3, 4
PC_ID_RX = re.compile(r"^pcx?_[0-9a-f]{16}$")
DATE_RX = re.compile(r"^\d{4}-\d{2}-\d{2}$")

MAX_FILE_BYTES = 64 * 1024 * 1024
HEADERS_MAX = 16000
BODY_HEAD, BODY_TAIL = 1000, 4000
CAL_BODY_MAX = 1000
ATTACH_MAX = 10
CATEGORY_MAX = 10
ADDR_MAX = 100
RRULE_MAX = 1000
CAL_AHEAD_DAYS = 31
CSV_FIELD_MAX = 4 * 1024 * 1024
EXT_MAIL = (".eml",)
EXT_CAL = (".ics",)
EXT_CSV = (".csv",)
EXT_MSG = (".msg",)

# 원시 필드 상한(P §10.2 원시 이름 + 공통 봉투 — 계약 §3.5). 이 밖의 키는 내지 않는다.
MAIL_FIELDS = frozenset({
    "internet_message_id", "conversation_id", "conversation_topic", "box", "folder_role", "sender_addr",
    "sender_name", "to", "cc", "subject", "attach_names", "sensitivity", "categories", "importance", "has_attach",
    "in_reply_to", "headers_text", "body_text", "focused_other",
    "ts_utc", "ts_local_offset", "ts_precision", "observed_at", "confidence", "flags",
})
CAL_FIELDS = frozenset({
    "global_appointment_id", "start_utc", "end_utc", "subject", "organizer", "attendees", "busy_status",
    "response_status", "meeting_status", "location", "is_recurring", "all_day", "online", "recurrence_incomplete",
    "sensitivity", "categories", "body_text", "ts_local_offset", "ts_precision", "observed_at", "confidence", "flags",
})
MAIL_FLAGS = frozenset({"meeting_response", "utc_suspect", "deferred"})
CAL_FLAGS = frozenset({"utc_suspect"})

_PREFIX_RX = re.compile(r"^\s*(?:(?:RE|FW|FWD|답장|전달|회신)\s*[:：]\s*)+", re.I)
_WS_RX = re.compile(r"\s+")
_ONLINE_RX = re.compile(r"(?i)teams\.microsoft\.com/l/meetup-join|zoom\.us/j/|\.webex\.com/")
_TAG_RX = re.compile(r"(?is)<(script|style)\b.*?</\1\s*>|<[^>]+>")
_SENSITIVITY = {"personal": 1, "private": 2, "company-confidential": 3, "confidential": 3}
_BUSY_WORDS = {"free": "free", "tentative": "tentative", "busy": "busy", "oof": "oof", "elsewhere": "elsewhere",
               "workingelsewhere": "elsewhere", "0": "free", "1": "tentative", "2": "busy", "3": "oof", "4": "elsewhere"}
_RESPONSE_WORDS = {"none": 0, "organizer": 1, "organized": 1, "tentative": 2, "accepted": 3, "declined": 4,
                   "notresponded": 5, "needs-action": 5}
_PARTSTAT = {"ACCEPTED": 3, "TENTATIVE": 2, "DECLINED": 4, "NEEDS-ACTION": 5}
_TRUE = frozenset({"1", "true", "t", "yes", "y", "예", "참"})
_FALSE = frozenset({"0", "false", "f", "no", "n", "아니오", "거짓"})
# VTIMEZONE 이 없을 때 쓰는 고정 오프셋(서머타임 없는 지역만 — 서머타임 지역은 규칙 없이 추정하지 않는다)
_FIXED_TZ = {
    "korea standard time": 540, "asia/seoul": 540, "tokyo standard time": 540, "asia/tokyo": 540,
    "china standard time": 480, "asia/shanghai": 480, "singapore standard time": 480, "asia/singapore": 480,
    "taipei standard time": 480, "asia/taipei": 480, "india standard time": 330, "asia/kolkata": 330,
    "utc": 0, "etc/utc": 0, "coordinated universal time": 0, "z": 0,
}
_WD = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}
_RRULE_KEYS = frozenset({"FREQ", "INTERVAL", "COUNT", "UNTIL", "BYDAY", "BYMONTHDAY", "BYMONTH", "WKST"})

CSV_CAL_ONLY = frozenset({"global_appointment_id", "start_utc", "end_utc", "ts_end_local", "busy_status",
                          "response_status", "meeting_status", "location", "is_recurring", "all_day", "online",
                          "attendees", "organizer", "recurrence_incomplete"})
CSV_MAIL_ONLY = frozenset({"internet_message_id", "box", "folder_role", "sender_addr", "sender_name", "to", "cc",
                           "attach_names", "has_attach", "in_reply_to", "headers_text", "conversation_id",
                           "focused_other"})


# ───────────────────────────── 공용 도구 ─────────────────────────────
def utc_iso(dt: datetime) -> str:
    """aware datetime → ``YYYY-MM-DDTHH:MM:SSZ``."""
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def offset_str(dt_utc: datetime) -> str:
    """그 순간 이 PC 시간대 오프셋(``+09:00``) — 계약 §3.1 ``ts_local_offset``."""
    return tz.fmt_offset(tz.capture_offset_min(dt_utc))


def local_to_utc(naive: datetime) -> datetime:
    """이 PC 시간대의 벽시계 시각(naive) → aware UTC. zoneinfo 없이 오프셋 두 번 맞춤."""
    guess = naive.replace(tzinfo=UTC)
    off = tz.capture_offset_min(guess)
    first = guess - timedelta(minutes=off)
    off2 = tz.capture_offset_min(first)
    return guess - timedelta(minutes=off2)


def _clean(rec: dict, allowed: frozenset) -> dict:
    """None 값·빈 flags 를 빼고 허용 필드만 남긴다(금지 원시 필드 P-T31 이 섞일 틈을 없앤다)."""
    out = {}
    for k, v in rec.items():
        if k not in allowed or v is None:
            continue
        if k == "flags" and not v:
            continue
        out[k] = v
    return out


def _fix_surrogates(s: str) -> str:
    """compat32 가 8비트 헤더 바이트를 surrogateescape 로 담은 경우 UTF-8 → CP949 → latin-1 순으로 되살린다."""
    if not any("\udc80" <= c <= "\udcff" for c in s):
        return s
    raw = s.encode("utf-8", "surrogateescape")
    for enc in ("utf-8", "cp949"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def hdecode(v) -> str:
    """RFC 2047 인코딩 낱말을 푼 헤더 문자열(접힌 공백은 하나로)."""
    if v is None:
        return ""
    s = _fix_surrogates(str(v))
    try:
        s = str(make_header(decode_header(s)))
    except (LookupError, ValueError, UnicodeError, TypeError):
        pass
    return _WS_RX.sub(" ", s).strip()


def addr_list(values, cap: int = ADDR_MAX) -> list:
    """주소 헤더 값들 → ``[{addr, name}]``(주소는 소문자, 이름은 RFC 2047 해독). 빈 항목은 뺀다."""
    raw = [_fix_surrogates(str(v)) for v in (values or []) if v is not None]
    out = []
    for name, addr in getaddresses(raw):
        a = (addr or "").strip().strip("<>").lower()
        n = hdecode(name) if name else ""
        if not a and not n:
            continue
        out.append({"addr": a or None, "name": n or None})
        if len(out) >= cap:
            break
    return out


def strip_prefix(subject: str) -> str:
    return _PREFIX_RX.sub("", subject or "").strip()


def body_window(text: str) -> str:
    """본문은 앞 1,000자 + 끝 4,000자만 메모리로(CM §3.1 · P §10.2)."""
    t = (text or "").strip()
    if len(t) <= BODY_HEAD + BODY_TAIL:
        return t
    return t[:BODY_HEAD] + "\n" + t[-BODY_TAIL:]


def html_text(s: str) -> str:
    return _WS_RX.sub(" ", html.unescape(_TAG_RX.sub(" ", s or ""))).strip()


def as_bool(v):
    if isinstance(v, bool):
        return v
    t = str(v or "").strip().lower()
    if t in _TRUE:
        return True
    if t in _FALSE:
        return False
    return None


def as_int(v, lo: int, hi: int):
    try:
        n = int(str(v).strip())
    except (TypeError, ValueError):
        return None
    return n if lo <= n <= hi else None


def _payload_text(part) -> str:
    data = part.get_payload(decode=True)
    if not isinstance(data, bytes | bytearray):
        return ""
    cs = part.get_content_charset() or "utf-8"
    try:
        return bytes(data).decode(cs, errors="replace")
    except LookupError:
        return bytes(data).decode("utf-8", errors="replace")


def _header_block(data: bytes) -> str:
    m = re.search(rb"\r?\n\r?\n", data)
    head = data[:m.start()] if m else data
    return head[: HEADERS_MAX * 2].decode("utf-8", errors="replace")[:HEADERS_MAX]


def _box_for(sender_addr, my_addrs) -> tuple[str, str]:
    """(box, folder_role) — 반입 파일에는 폴더가 없으므로 발신자 = 나 로만 판정. 내 주소를 모르면 other."""
    if not my_addrs:
        return "other", "other"
    if sender_addr and sender_addr.lower() in my_addrs:
        return "sent", "sent"
    return "inbox", "inbox"


def _thread_index_id(v: str):
    """Outlook Thread-Index → ConversationID 모양(색인 바이트 6..21 의 16진 대문자) — COM 경로와 같은 대화 재료."""
    try:
        raw = base64.b64decode(re.sub(r"\s+", "", v), validate=False)
    except (ValueError, TypeError):
        return None
    return raw[6:22].hex().upper() if len(raw) >= 22 else None


def _raw(msg, name: str):
    """헤더 원래 값(compat32 의 Header 감싸기 없이 — 8비트 원문 헤더를 _fix_surrogates 로 되살리려고)."""
    n = name.lower()
    for k, v in msg.raw_items():
        if k.lower() == n:
            return v
    return None


def _raw_all(msg, name: str) -> list:
    n = name.lower()
    return [v for k, v in msg.raw_items() if k.lower() == n]


# ───────────────────────────── EML ─────────────────────────────
def parse_eml(data: bytes, my_addrs=(), *, now: datetime | None = None):
    """EML 바이트 → mail 원시 레코드(dict) 또는 None(시각을 알 수 없음)."""
    now = now or datetime.now(UTC)
    mine = {a.lower() for a in my_addrs if a}
    msg = email.message_from_bytes(data, policy=email.policy.compat32)
    flags = {}
    dt = None
    for raw_date in [_raw(msg, "Date")] + [str(r).rsplit(";", 1)[-1] for r in reversed(_raw_all(msg, "Received") or [])
                                         if ";" in str(r)]:
        if not raw_date:
            continue
        try:
            dt = parsedate_to_datetime(str(raw_date).strip())
        except (TypeError, ValueError, IndexError):
            dt = None
        if dt is not None:
            break
    if dt is None:
        return None
    if dt.tzinfo is None:                       # '-0000'(시간대 모름) — UTC 로 두고 의심 표시
        dt = dt.replace(tzinfo=UTC)
        flags["utc_suspect"] = True
    dt = dt.astimezone(UTC)

    frm = addr_list(_raw_all(msg, "From"), cap=1)
    sender = frm[0] if frm else {"addr": None, "name": None}
    box, role = _box_for(sender["addr"], mine)
    subject = hdecode(_raw(msg, "Subject"))
    topic = hdecode(_raw(msg, "Thread-Topic")) or strip_prefix(subject)
    conv = None
    if _raw(msg, "Thread-Index"):
        conv = _thread_index_id(str(_raw(msg, "Thread-Index")))
    if not conv:
        refs = re.findall(r"<[^<>\s]+>", " ".join(str(x) for x in (_raw_all(msg, "References") or [])))
        irt = re.findall(r"<[^<>\s]+>", str(_raw(msg, "In-Reply-To") or ""))
        root = (refs or irt or [str(_raw(msg, "Message-ID") or "").strip()])[0]
        conv = ("ref:" + root) if root else None

    text, html_body, names, attach = None, None, [], False
    for part in msg.walk():
        if part.is_multipart():
            continue
        ctype = part.get_content_type()
        fn = part.get_filename()
        disp = str(part.get("Content-Disposition") or "").lower()
        if fn or disp.startswith("attachment"):
            attach = True
            if fn and len(names) < ATTACH_MAX:
                names.append(hdecode(fn))
            continue
        if ctype == "text/calendar":
            method = str(part.get_param("method") or "").upper()
            if method == "REPLY" or "METHOD:REPLY" in _payload_text(part).upper():
                flags["meeting_response"] = True
            continue
        if ctype == "text/plain" and text is None:
            text = _payload_text(part)
        elif ctype == "text/html" and html_body is None:
            html_body = _payload_text(part)
    body = text if text is not None else html_text(html_body or "")

    sens = 0
    s_raw = str(_raw(msg, "Sensitivity") or "").strip().lower()
    if s_raw in _SENSITIVITY:
        sens = _SENSITIVITY[s_raw]
    imp = 1
    i_raw = str(_raw(msg, "Importance") or "").strip().lower()
    p_raw = str(_raw(msg, "X-Priority") or "").strip()[:1]
    if i_raw in ("high", "urgent"):
        imp = 2
    elif i_raw in ("low", "non-urgent"):
        imp = 0
    elif p_raw in ("1", "2"):
        imp = 2
    elif p_raw in ("4", "5"):
        imp = 0
    cats = [c.strip() for c in hdecode(_raw(msg, "Keywords")).split(",") if c.strip()][:CATEGORY_MAX]
    if _raw(msg, "Deferred-Delivery"):
        flags["deferred"] = True
    mid = str(_raw(msg, "Message-ID") or "").strip()
    rec = {
        "internet_message_id": mid or None,
        "conversation_id": conv,
        "conversation_topic": topic,
        "box": box,
        "folder_role": role,
        "sender_addr": sender["addr"],
        "sender_name": sender["name"],
        "to": addr_list(_raw_all(msg, "To")),
        "cc": addr_list(_raw_all(msg, "Cc")),
        "subject": subject,
        "attach_names": names,
        "has_attach": attach,
        "sensitivity": sens,
        "categories": cats,
        "importance": imp,
        "in_reply_to": bool(_raw(msg, "In-Reply-To") or _raw(msg, "References")),
        "headers_text": _header_block(data),
        "body_text": body_window(body),
        "ts_utc": utc_iso(dt),
        "ts_local_offset": offset_str(dt),
        "ts_precision": "minute",
        "observed_at": utc_iso(now),
        "confidence": 1.0,
        "flags": {k: v for k, v in flags.items() if k in MAIL_FLAGS},
    }
    return _clean(rec, MAIL_FIELDS)


# ───────────────────────────── ICS ─────────────────────────────
def ics_unescape(v: str) -> str:
    out, i = [], 0
    while i < len(v):
        c = v[i]
        if c == "\\" and i + 1 < len(v):
            n = v[i + 1]
            out.append("\n" if n in "nN" else n)
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _split_outside_quotes(s: str, sep: str) -> list:
    parts, cur, q = [], [], False
    for ch in s:
        if ch == '"':
            q = not q
        if ch == sep and not q:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    parts.append("".join(cur))
    return parts


def ics_lines(text: str) -> list:
    """접힌 줄을 펴고 (이름, 매개변수 dict, 값) 목록으로."""
    out = []
    for ln in re.split(r"\r\n|\n|\r", text):
        if ln[:1] in (" ", "\t") and out:
            out[-1] += ln[1:]
        elif ln.strip():
            out.append(ln)
    parsed = []
    for ln in out:
        q, cut = False, -1
        for i, ch in enumerate(ln):
            if ch == '"':
                q = not q
            elif ch == ":" and not q:
                cut = i
                break
        if cut < 0:
            continue
        head, value = ln[:cut], ln[cut + 1:]
        parts = _split_outside_quotes(head, ";")
        params = {}
        for p in parts[1:]:
            k, _, v = p.partition("=")
            params[k.strip().upper()] = v.strip().strip('"')
        parsed.append((parts[0].strip().upper(), params, value))
    return parsed


def ics_tree(lines) -> list:
    """BEGIN/END 를 따라 구성요소 트리 ``[{name, props: [(n, p, v)], children}]``(최상위 목록)."""
    root = {"name": "", "props": [], "children": []}
    stack = [root]
    for name, params, value in lines:
        if name == "BEGIN":
            node = {"name": value.strip().upper(), "props": [], "children": []}
            stack[-1]["children"].append(node)
            stack.append(node)
        elif name == "END":
            if len(stack) > 1:
                stack.pop()
        else:
            stack[-1]["props"].append((name, params, value))
    return root["children"]


def _prop(node, name):
    for n, p, v in node["props"]:
        if n == name:
            return p, v
    return None, None


def _props(node, name):
    return [(p, v) for n, p, v in node["props"] if n == name]


def parse_offset_hhmm(s: str):
    m = re.fullmatch(r"([+-])(\d{2})(\d{2})(\d{2})?", (s or "").strip())
    if not m:
        return None
    v = int(m.group(2)) * 60 + int(m.group(3))
    return -v if m.group(1) == "-" else v


def parse_ics_dt(value: str):
    """``YYYYMMDD`` · ``YYYYMMDDTHHMMSS`` · ``…Z`` → (naive datetime, is_date, is_utc). 형식이 아니면 None."""
    v = (value or "").strip()
    m = re.fullmatch(r"(\d{4})(\d{2})(\d{2})(?:T(\d{2})(\d{2})(\d{2})?(Z)?)?", v)
    if not m:
        return None
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        if m.group(4) is None:
            return datetime(y, mo, d), True, False
        return datetime(y, mo, d, int(m.group(4)), int(m.group(5)), int(m.group(6) or 0)), False, bool(m.group(7))
    except ValueError:
        return None


def parse_duration(v: str):
    m = re.fullmatch(r"([+-])?P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", (v or "").strip())
    if not m or not any(m.group(i) for i in range(2, 7)):
        return None
    td = timedelta(weeks=int(m.group(2) or 0), days=int(m.group(3) or 0), hours=int(m.group(4) or 0),
                   minutes=int(m.group(5) or 0), seconds=int(m.group(6) or 0))
    return -td if m.group(1) == "-" else td


def nth_weekday(year: int, month: int, n: int, wd: int):
    """그 달의 n번째(음수면 끝에서) 요일 wd 날짜. 없으면 None."""
    if not 1 <= month <= 12 or n == 0:
        return None
    if n > 0:
        first = date(year, month, 1)
        d = first + timedelta(days=(wd - first.weekday()) % 7 + 7 * (n - 1))
    else:
        nxt = date(year + (month == 12), month % 12 + 1, 1)
        last = nxt - timedelta(days=1)
        d = last - timedelta(days=(last.weekday() - wd) % 7 + 7 * (-n - 1))
    return d if d.month == month else None


def parse_rrule(v: str) -> dict:
    out = {}
    for part in (v or "").split(";"):
        k, _, val = part.partition("=")
        if k.strip():
            out[k.strip().upper()] = val.strip().upper()
    return out


class VTimezone:
    """VTIMEZONE 하나 — STANDARD/DAYLIGHT 구성요소의 시작·규칙으로 벽시계 시각의 오프셋(분)을 낸다(zoneinfo 없이)."""

    def __init__(self, node):
        self.comps = []
        for ch in node["children"]:
            if ch["name"] not in ("STANDARD", "DAYLIGHT"):
                continue
            _p, st = _prop(ch, "DTSTART")
            _p, to = _prop(ch, "TZOFFSETTO")
            _p, fr = _prop(ch, "TZOFFSETFROM")
            _p, rr = _prop(ch, "RRULE")
            ps = parse_ics_dt(st or "")
            off_to = parse_offset_hhmm(to or "")
            if ps is None or off_to is None:
                continue
            rdates = []
            for _p2, rv in _props(ch, "RDATE"):
                for one in rv.split(","):
                    r = parse_ics_dt(one)
                    if r:
                        rdates.append(r[0])
            self.comps.append({"start": ps[0], "to": off_to, "from": parse_offset_hhmm(fr or ""),
                               "rule": parse_rrule(rr) if rr else None, "rdates": rdates})

    def _onsets(self, c, year):
        if not c["rule"]:
            return [c["start"], *c["rdates"]]
        r = c["rule"]
        if r.get("FREQ") != "YEARLY":
            return [c["start"]]
        mo = as_int(r.get("BYMONTH", c["start"].month), 1, 12)
        m = re.fullmatch(r"([+-]?\d)?(MO|TU|WE|TH|FR|SA|SU)", r.get("BYDAY", ""))
        out = []
        for y in (year - 1, year):
            if m and mo:
                d = nth_weekday(y, mo, int(m.group(1) or 1), _WD[m.group(2)])
            else:
                try:
                    d = date(y, c["start"].month, c["start"].day)
                except ValueError:
                    d = None
            if d is None:
                continue
            on = datetime.combine(d, c["start"].time())
            if on >= c["start"]:
                out.append(on)
        return out

    def offset(self, local: datetime):
        best = None
        for c in self.comps:
            for on in self._onsets(c, local.year):
                if on <= local and (best is None or on > best[0]):
                    best = (on, c["to"])
        if best is not None:
            return best[1]
        if self.comps:
            first = min(self.comps, key=lambda c: c["start"])
            return first["from"] if first["from"] is not None else first["to"]
        return None


class _TzResolver:
    def __init__(self, tree):
        self.vtz = {}
        for cal in tree:
            for ch in cal["children"]:
                if ch["name"] == "VTIMEZONE":
                    _p, tzid = _prop(ch, "TZID")
                    if tzid:
                        self.vtz[tzid.strip()] = VTimezone(ch)

    def to_utc(self, naive: datetime, tzid, is_utc: bool):
        """(aware UTC, 의심 여부). TZID 규칙 → 고정 표 → 이 PC 시간대(의심)."""
        if is_utc:
            return naive.replace(tzinfo=UTC), False
        if tzid:
            vt = self.vtz.get(tzid.strip())
            off = vt.offset(naive) if vt else None
            if off is None:
                off = _FIXED_TZ.get(tzid.strip().strip("/").lower())
            if off is not None:
                return (naive - timedelta(minutes=off)).replace(tzinfo=UTC), False
            return local_to_utc(naive), True
        return local_to_utc(naive), False          # 부유 시각(시간대 없음) = 보는 사람의 시간대

    def _offset_at_utc(self, u: datetime, tzid) -> int:
        """UTC 순간의 그 시간대 오프셋(분) — 규칙(벽시계 기준)은 한 번 맞춰 본다. 모르면 이 PC 시간대."""
        key = (tzid or "").strip()
        vt = self.vtz.get(key) if key else None
        naive = u.astimezone(UTC).replace(tzinfo=None)
        if vt is not None:
            off = vt.offset(naive)
            if off is not None:
                off2 = vt.offset(naive + timedelta(minutes=off))
                return off2 if off2 is not None else off
        if key and key.strip("/").lower() in _FIXED_TZ:
            return _FIXED_TZ[key.strip("/").lower()]
        return tz.capture_offset_min(u)

    def utc_to_local(self, u: datetime, tzid) -> datetime:
        """aware UTC → 그 시간대 벽시계(naive)."""
        return (u.astimezone(UTC) + timedelta(minutes=self._offset_at_utc(u, tzid))).replace(tzinfo=None)


def expand_rrule(start: datetime, rule: dict, *, until_local, lo: datetime, hi: datetime, all_day: bool):
    """단순 주기 RRULE 을 벽시계 시각 목록으로 펼친다(start 포함, [lo, hi] 안만). 지원하지 않는 규칙이면 None."""
    if set(rule) - _RRULE_KEYS:
        return None
    freq = rule.get("FREQ")
    interval = as_int(rule.get("INTERVAL", "1"), 1, 1000)
    count = as_int(rule["COUNT"], 1, 100000) if "COUNT" in rule else None
    if freq not in ("DAILY", "WEEKLY", "MONTHLY", "YEARLY") or interval is None or ("COUNT" in rule and count is None):
        return None
    byday = [x for x in rule.get("BYDAY", "").split(",") if x]
    bymd = rule.get("BYMONTHDAY", "")
    bymonth = rule.get("BYMONTH", "")
    nth = None
    if byday:
        if freq == "WEEKLY":
            if any(x not in _WD for x in byday):
                return None
        elif freq == "MONTHLY" and len(byday) == 1:
            m = re.fullmatch(r"([+-]?[1-5])(MO|TU|WE|TH|FR|SA|SU)", byday[0])
            if not m:
                return None
            nth = (int(m.group(1)), _WD[m.group(2)])
        else:
            return None
    if bymd and (freq != "MONTHLY" or "," in bymd or as_int(bymd, 1, 31) is None or nth):
        return None
    if bymonth and (freq != "YEARLY" or as_int(bymonth, 1, 12) != start.month):
        return None
    t = start.time()
    wk0 = start.date() - timedelta(days=start.weekday())
    days = sorted({_WD[x] for x in byday} or {start.weekday()}) if freq == "WEEKLY" else []

    def period(k):
        """주기 k(0 = 시작 주기)의 회차들(벽시계, 오름차순)."""
        if freq == "DAILY":
            return [start + timedelta(days=k * interval)]
        if freq == "WEEKLY":
            week = wk0 + timedelta(weeks=k * interval)
            return [datetime.combine(week + timedelta(days=wd), t) for wd in days
                    if week + timedelta(days=wd) >= start.date()]
        if freq == "MONTHLY":
            mi = start.month - 1 + k * interval
            y, m = start.year + mi // 12, mi % 12 + 1
            if nth:
                d = nth_weekday(y, m, nth[0], nth[1])
            else:
                try:
                    d = date(y, m, as_int(bymd, 1, 31) if bymd else start.day)
                except ValueError:
                    d = None
            return [datetime.combine(d, t)] if d is not None and d >= start.date() else []
        try:
            return [datetime.combine(date(start.year + k * interval, start.month, start.day), t)]
        except ValueError:
            return []

    # 상한(RRULE_MAX)은 '분석 창 안에 낸 회차' 수에 건다(W1 통합 창 결함 수정 — 전에는 시작부터 센 회차 1,000번째에서 끊겨
    # 오래된 반복 회의의 최근 회차가 조용히 사라졌다: 2022년 시작 '매 평일'이 창 안 310건 대신 45건, 매일은 0건).
    # COUNT 가 없으면 창 바로 앞 주기로 건너뛴다. COUNT 가 있으면 회차 번호를 시작부터 세야 하므로 처음부터 센다(COUNT ≤ 100000).
    k0 = 0
    if count is None and lo.date() > start.date():
        if freq == "DAILY":
            k0 = (lo.date() - start.date()).days // interval - 1
        elif freq == "WEEKLY":
            k0 = ((lo.date() - wk0).days // 7) // interval - 1
        elif freq == "MONTHLY":
            k0 = ((lo.year - start.year) * 12 + lo.month - start.month) // interval - 1
        else:
            k0 = (lo.year - start.year) // interval - 1
        k0 = max(0, k0)
    max_periods = (count or 0) + RRULE_MAX * 10            # 안전 상한(주기 수) — 걸리면 불완전(None)
    out, n, k = [], 0, k0
    while True:
        if k - k0 > max_periods:
            return None                                     # hi 에 못 닿았다 — 마스터 1건 + recurrence_incomplete
        for occ in period(k):
            if until_local is not None and (occ.date() > until_local.date() if all_day else occ > until_local):
                return out
            n += 1
            if (count is not None and n > count) or occ > hi:
                return out
            if occ >= lo:
                out.append(occ)
                if len(out) > RRULE_MAX:
                    return None                             # 창 안 회차가 상한을 넘음 — 불완전 표시(조용히 자르지 않는다)
        k += 1


def _cal_addr(params, value):
    v = (value or "").strip()
    if v.lower().startswith("mailto:"):
        v = v[7:]
    addr = v.strip().lower() if "@" in v else None
    name = hdecode(params.get("CN", "")) if params.get("CN") else None
    if not addr and not name:
        return None
    return {"addr": addr, "name": name}


def parse_ics(data: bytes, my_addrs=(), *, now: datetime | None = None, window=None):
    """ICS 바이트 → (cal 원시 레코드 목록, 통계 dict). window = (lo_utc, hi_utc) — 반복 전개 범위."""
    now = now or datetime.now(UTC)
    mine = {a.lower() for a in my_addrs if a}
    text = None
    for enc in ("utf-8-sig", "cp949"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        text = data.decode("latin-1")
    tree = ics_tree(ics_lines(text))
    res = _TzResolver(tree)
    stats = {"events": 0, "occurrences": 0, "recurrence_incomplete": 0, "replies_skipped": 0, "bad_events": 0}
    lo_utc, hi_utc = window or (now - timedelta(days=400), now + timedelta(days=CAL_AHEAD_DAYS))
    out = []
    for cal in tree:
        if cal["name"] != "VCALENDAR":
            continue
        _p, method = _prop(cal, "METHOD")
        events_ = [ch for ch in cal["children"] if ch["name"] == "VEVENT"]
        if (method or "").strip().upper() == "REPLY":
            stats["replies_skipped"] += len(events_)
            continue
        overrides = {}
        for ev in events_:
            p, rid = _prop(ev, "RECURRENCE-ID")
            _p2, uid = _prop(ev, "UID")
            if rid and uid:
                pr = parse_ics_dt(rid)
                if pr:
                    u, _s = res.to_utc(pr[0], p.get("TZID"), pr[2])
                    overrides.setdefault(uid.strip(), set()).add(pr[0].date() if pr[1] else u)
        for ev in events_:
            try:
                recs = _event_records(ev, res, mine, now, lo_utc, hi_utc, overrides, stats)
            except (ValueError, KeyError, TypeError, OverflowError):
                stats["bad_events"] += 1
                continue
            out.extend(recs)
    return out, stats


def _event_records(ev, res, mine, now, lo_utc, hi_utc, overrides, stats):
    p_st, v_st = _prop(ev, "DTSTART")
    st = parse_ics_dt(v_st or "")
    if st is None:
        stats["bad_events"] += 1
        return []
    stats["events"] += 1
    tzid = (p_st or {}).get("TZID")
    start_l, is_date, st_utc_flag = st
    p_en, v_en = _prop(ev, "DTEND")
    en = parse_ics_dt(v_en or "") if v_en else None
    _p, v_du = _prop(ev, "DURATION")
    if en is not None and is_date:
        dur = timedelta(days=(en[0].date() - start_l.date()).days)
    elif en is not None:                           # 시작·끝의 시간대가 달라도 되게 절대 시각 차로 잰다
        su0, _s = res.to_utc(start_l, tzid, st_utc_flag)
        eu0, _s = res.to_utc(en[0], (p_en or {}).get("TZID") or (None if en[2] else tzid), en[2])
        dur = eu0 - su0
    else:
        dur = parse_duration(v_du or "") or (timedelta(days=1) if is_date else timedelta(0))
    if dur < timedelta(0):
        dur = timedelta(0)
    _p, uid = _prop(ev, "UID")
    uid = (uid or "").strip() or None
    _p, summary = _prop(ev, "SUMMARY")
    _p, loc = _prop(ev, "LOCATION")
    _p, desc = _prop(ev, "DESCRIPTION")
    _p, status = _prop(ev, "STATUS")
    _p, transp = _prop(ev, "TRANSP")
    _p, cls = _prop(ev, "CLASS")
    _p, cdo_busy = _prop(ev, "X-MICROSOFT-CDO-BUSYSTATUS")
    _p, cdo_allday = _prop(ev, "X-MICROSOFT-CDO-ALLDAYEVENT")
    _p, rrule = _prop(ev, "RRULE")
    p_rid, rid = _prop(ev, "RECURRENCE-ID")
    org_p, org_v = _prop(ev, "ORGANIZER")
    organizer = _cal_addr(org_p or {}, org_v) if org_v else None
    attendees, my_partstat = [], None
    for ap, av in _props(ev, "ATTENDEE"):
        a = _cal_addr(ap, av)
        if a is None:
            continue
        if a["addr"] and a["addr"] in mine:
            my_partstat = (ap.get("PARTSTAT") or "").upper()
        if len(attendees) < ADDR_MAX:
            attendees.append(a)
    cats = []
    for _cp, cv in _props(ev, "CATEGORIES"):
        cats += [ics_unescape(x).strip() for x in _split_outside_quotes(cv, ",") if x.strip()]
    status_u = (status or "").strip().upper()
    if cdo_busy and cdo_busy.strip().lower() in _BUSY_WORDS:
        busy = _BUSY_WORDS[cdo_busy.strip().lower()]
    elif (transp or "").strip().upper() == "TRANSPARENT":
        busy = "free"
    elif status_u == "TENTATIVE":
        busy = "tentative"
    else:
        busy = "busy"
    if organizer and organizer["addr"] and organizer["addr"] in mine:
        response = 1
    else:
        response = _PARTSTAT.get(my_partstat or "", 0)
    meeting_status = 5 if status_u == "CANCELLED" else (1 if attendees else 0)
    all_day = is_date or (cdo_allday or "").strip().upper() == "TRUE"
    online = bool(_prop(ev, "X-MICROSOFT-SKYPETEAMSMEETINGURL")[1] or _prop(ev, "X-MICROSOFT-ONLINEMEETINGCONFLINK")[1]
                  or _ONLINE_RX.search((loc or "") + " " + (desc or "")))
    sens = {"PRIVATE": 2, "CONFIDENTIAL": 3}.get((cls or "").strip().upper(), 0)
    base = {
        "global_appointment_id": uid,
        "subject": ics_unescape(summary or "").strip(),
        "organizer": organizer,
        "attendees": attendees,
        "busy_status": busy,
        "response_status": response,
        "meeting_status": meeting_status,
        "location": ics_unescape(loc or "").strip() or None,
        "is_recurring": bool(rrule or rid),
        "all_day": all_day,
        "online": online,
        "recurrence_incomplete": False,
        "sensitivity": sens,
        "categories": cats[:CATEGORY_MAX],
        "body_text": ics_unescape(desc or "").strip()[:CAL_BODY_MAX] or None,
        "ts_precision": "date" if all_day else "minute",
        "observed_at": utc_iso(now),
        "confidence": 1.0,
    }

    def one(local_start):
        su, sus = res.to_utc(local_start, tzid, st_utc_flag)
        if is_date:                                # 종일 — 끝은 그 날짜들의 자정(벽시계)으로
            eu, _x = res.to_utc(local_start + dur, tzid, st_utc_flag)
        else:
            eu = su + dur
        r = dict(base, start_utc=utc_iso(su), end_utc=utc_iso(max(eu, su)), ts_local_offset=offset_str(su))
        if sus:
            r["flags"] = {"utc_suspect": True}
        return _clean(r, CAL_FIELDS)

    if not rrule or rid:
        return [one(start_l)]
    rule = parse_rrule(rrule)
    until_local, bad = None, False
    if "UNTIL" in rule:
        pu = parse_ics_dt(rule["UNTIL"])
        if pu is None:
            bad = True
        elif pu[2] and not is_date and not st_utc_flag:     # UTC UNTIL → 이벤트 시간대 벽시계로
            until_local = res.utc_to_local(pu[0].replace(tzinfo=UTC), tzid)
        else:
            until_local = pu[0]
    lo_l = res.utc_to_local(lo_utc, tzid) - timedelta(days=1)
    hi_l = res.utc_to_local(hi_utc, tzid) + timedelta(days=1)
    occs = None if bad else expand_rrule(start_l, rule, until_local=until_local, lo=lo_l, hi=hi_l, all_day=is_date)
    if occs is None:                                # 복잡 반복 — 마스터 1건 + 불완전 표시(CM §11.5)
        stats["recurrence_incomplete"] += 1
        r = one(start_l)
        r["recurrence_incomplete"] = True
        return [r]
    ex = set()
    for xp, xv in _props(ev, "EXDATE"):
        for one_v in xv.split(","):
            px = parse_ics_dt(one_v)
            if px is None:
                continue
            if px[1]:
                ex.add(px[0].date())
            else:
                u, _s = res.to_utc(px[0], xp.get("TZID") or tzid, px[2])
                ex.add(u)
    ov = overrides.get(uid or "", set())
    out = []
    for occ in occs:
        su, _s = res.to_utc(occ, tzid, st_utc_flag)
        key = occ.date() if is_date else su
        if key in ex or key in ov:
            continue
        out.append(one(occ))
    stats["occurrences"] += len(out)
    return out


# ───────────────────────────── CSV ─────────────────────────────
def _decode_text(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp949"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def csv_kind(header) -> str | None:
    h = set(header)
    if h & CSV_CAL_ONLY:
        return "cal"
    if h & CSV_MAIL_ONLY:
        return "mail"
    return None


def _csv_time(v: str):
    """오프셋 포함 ISO(``2026-09-01T09:00:00+09:00``·``…Z``) → (aware UTC, 의심). naive 는 이 PC 시간대 + 의심."""
    t = (v or "").strip()
    if not t:
        return None, False
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t.replace(" ", "T", 1) if "T" not in t else t)
    except ValueError:
        return None, False
    if dt.tzinfo is None:
        return local_to_utc(dt), True
    return dt.astimezone(UTC), False


def _list_cell(v: str) -> list:
    return [x.strip() for x in re.split(r"[;,]", v or "") if x.strip()]


def _addr_cell(v: str) -> list:
    return addr_list([(v or "").replace(";", ",")]) if (v or "").strip() else []


def parse_csv(data: bytes, my_addrs=(), *, now: datetime | None = None):
    """CSV 바이트 → (kind | None, 원시 레코드 목록, 통계). 헤더(P §10.2 원시 이름)로 메일·일정을 가른다."""
    now = now or datetime.now(UTC)
    mine = {a.lower() for a in my_addrs if a}
    csv.field_size_limit(max(csv.field_size_limit(), CSV_FIELD_MAX))      # 헤더·본문 열이 긴 반입 CSV
    rows = list(csv.reader(io.StringIO(_decode_text(data))))
    stats = {"rows": 0, "bad_rows": 0}
    if not rows:
        return None, [], stats
    header = [h.strip().lower() for h in rows[0]]
    kind = csv_kind(header)
    if kind is None:
        return None, [], stats
    out = []
    for raw_row in rows[1:]:
        if not any(c.strip() for c in raw_row):
            continue
        stats["rows"] += 1
        cells = (raw_row + [""] * len(header))[:len(header)]     # 남는 열 버림 · 모자란 열 빈칸
        d = dict(zip(header, cells, strict=True))
        rec = _csv_mail(d, mine, now) if kind == "mail" else _csv_cal(d, mine, now)
        if rec is None:
            stats["bad_rows"] += 1
            continue
        out.append(rec)
    return kind, out, stats


def _csv_mail(d, mine, now):
    t, sus = _csv_time(d.get("ts_local") or "")
    if t is None:
        t, sus = _csv_time(d.get("ts_utc") or "")
    if t is None:
        return None
    flags = {}
    if sus:
        flags["utc_suspect"] = True
    if as_bool(d.get("meeting_response")):
        flags["meeting_response"] = True
    sender = (d.get("sender_addr") or "").strip().lower() or None
    box = (d.get("box") or "").strip().lower()
    if box not in ("inbox", "sent", "other"):
        box, role = _box_for(sender, mine)
    else:
        role = box if box != "other" else "other"
    fr = (d.get("folder_role") or "").strip().lower()
    if fr in ("inbox", "sent", "archive", "subfolder", "other", "junk", "deleted"):
        role = fr
    subject = (d.get("subject") or "").strip()
    names = _list_cell(d.get("attach_names"))[:ATTACH_MAX]
    rec = {
        "internet_message_id": (d.get("internet_message_id") or "").strip() or None,
        "conversation_id": (d.get("conversation_id") or "").strip() or None,
        "conversation_topic": (d.get("conversation_topic") or "").strip() or strip_prefix(subject),
        "box": box,
        "folder_role": role,
        "sender_addr": sender,
        "sender_name": (d.get("sender_name") or "").strip() or None,
        "to": _addr_cell(d.get("to")),
        "cc": _addr_cell(d.get("cc")),
        "subject": subject,
        "attach_names": names,
        "has_attach": as_bool(d.get("has_attach")) if (d.get("has_attach") or "").strip() else bool(names),
        "sensitivity": as_int(d.get("sensitivity"), 0, 3) or 0,
        "categories": _list_cell(d.get("categories"))[:CATEGORY_MAX],
        "importance": as_int(d.get("importance"), 0, 2) if (d.get("importance") or "").strip() else 1,
        "in_reply_to": bool(as_bool(d.get("in_reply_to"))),
        "headers_text": (d.get("headers_text") or "")[:HEADERS_MAX] or None,
        "body_text": body_window(d.get("body_text") or "") or None,
        "focused_other": as_bool(d.get("focused_other")) if (d.get("focused_other") or "").strip() else None,
        "ts_utc": utc_iso(t),
        "ts_local_offset": offset_str(t),
        "ts_precision": "minute",
        "observed_at": utc_iso(now),
        "confidence": 1.0,
        "flags": flags,
    }
    return _clean(rec, MAIL_FIELDS)


def _csv_cal(d, mine, now):
    s, sus = _csv_time(d.get("ts_local") or "")
    if s is None:
        s, sus = _csv_time(d.get("start_utc") or "")
    if s is None:
        return None
    e, sus2 = _csv_time(d.get("ts_end_local") or "")
    if e is None:
        e, sus2 = _csv_time(d.get("ts_end") or d.get("end_utc") or "")
    if e is None or e < s:
        e, sus2 = s, False
    orgs = _addr_cell(d.get("organizer"))
    organizer = orgs[0] if orgs else None
    attendees = _addr_cell(d.get("attendees"))
    busy = _BUSY_WORDS.get((d.get("busy_status") or "").strip().lower(), "busy")
    resp_raw = (d.get("response_status") or "").strip().lower()
    response = as_int(resp_raw, 0, 5)
    if response is None:
        response = _RESPONSE_WORDS.get(resp_raw.replace(" ", ""), 0)
    if organizer and organizer["addr"] and organizer["addr"] in mine:
        response = 1
    ms = as_int(d.get("meeting_status"), 0, 7)
    all_day = bool(as_bool(d.get("all_day")))
    rec = {
        "global_appointment_id": (d.get("global_appointment_id") or "").strip() or None,
        "start_utc": utc_iso(s),
        "end_utc": utc_iso(e),
        "subject": (d.get("subject") or "").strip(),
        "organizer": organizer,
        "attendees": attendees,
        "busy_status": busy,
        "response_status": response,
        "meeting_status": ms if ms is not None else (1 if attendees else 0),
        "location": (d.get("location") or "").strip() or None,
        "is_recurring": bool(as_bool(d.get("is_recurring"))),
        "all_day": all_day,
        "online": bool(as_bool(d.get("online"))),
        "recurrence_incomplete": bool(as_bool(d.get("recurrence_incomplete"))),
        "sensitivity": as_int(d.get("sensitivity"), 0, 3) or 0,
        "categories": _list_cell(d.get("categories"))[:CATEGORY_MAX],
        "body_text": (d.get("body_text") or "").strip()[:CAL_BODY_MAX] or None,
        "ts_local_offset": offset_str(s),
        "ts_precision": "date" if all_day else "minute",
        "observed_at": utc_iso(now),
        "confidence": 1.0,
        "flags": {"utc_suspect": True} if (sus or sus2) else {},
    }
    return _clean(rec, CAL_FIELDS)


# ───────────────────────────── 파일 훑기 ─────────────────────────────
def scan_files(in_dir: str) -> list:
    """반입 폴더(하위 포함)의 (상대 경로, 절대 경로, 소문자 확장자) — 상대 경로 순(결정적). 심볼릭 링크는 따라가지 않는다."""
    out = []
    for dp, dns, fns in os.walk(in_dir, followlinks=False):
        dns.sort()
        for fn in sorted(fns):
            p = os.path.join(dp, fn)
            if os.path.islink(p):
                continue
            ext = os.path.splitext(fn)[1].lower()
            if ext in EXT_MAIL + EXT_CAL + EXT_CSV + EXT_MSG:
                out.append((os.path.relpath(p, in_dir), p, ext))
    out.sort(key=lambda x: x[0].lower())
    return out


def in_range(rec: dict, kind: str, lo, hi) -> bool:
    """--from/--to(로컬 날짜) 창 안인가 — 메일은 ts_utc, 일정은 [start, end) 가 창과 겹치면."""
    if lo is None and hi is None:
        return True
    if kind == "mail":
        s = e = datetime.fromisoformat(rec["ts_utc"].replace("Z", "+00:00"))
    else:
        s = datetime.fromisoformat(rec["start_utc"].replace("Z", "+00:00"))
        e = datetime.fromisoformat(rec["end_utc"].replace("Z", "+00:00"))
    if lo is not None and max(s, e) < lo:
        return False
    return not (hi is not None and s >= hi)


# ───────────────────────────── 정제 관문·저장(계약 시그니처) ─────────────────────────────
@dataclass
class Backend:
    """정제·저장 지점(WP-11). 시험은 같은 모양의 가짜를 넣는다."""
    make_record_context: Callable
    sanitize_record: Callable
    SegmentWriter: Callable
    load_raw_cursor: Callable
    save_raw_cursor: Callable


def real_backend() -> Backend:
    """계약 §2.2·§2.3 의 실물 — 수집기 파이썬은 lm27.privacy.sanitize · lm27.store 만 쓴다(L-10)."""
    from lm27.privacy.sanitize import make_record_context, sanitize_record
    from lm27.store import SegmentWriter
    from lm27.store.cursor import load_raw_cursor, save_raw_cursor
    return Backend(make_record_context, sanitize_record, SegmentWriter, load_raw_cursor, save_raw_cursor)


class _ArgError(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise _ArgError(message)


def build_parser() -> argparse.ArgumentParser:
    ap = _Parser(prog="Import-MailCal.py", description="반입 폴더의 EML·ICS·CSV → 정제 → 로컬 원장(mail.import·cal.import)")
    ap.add_argument("--kind", required=True, choices=KINDS_HERE)
    ap.add_argument("--pc", required=True, help="pc_id")
    ap.add_argument("--in-dir", default="", help="반입 폴더(빈 값 = collect.importDir 또는 data\\import)")
    ap.add_argument("--from", dest="from_", default="", help="YYYY-MM-DD(로컬)")
    ap.add_argument("--to", default="", help="YYYY-MM-DD(로컬, 포함)")
    ap.add_argument("--events", default="jsonl", choices=("jsonl", "text", "off"))
    return ap


def _local_day_utc(s: str, end: bool):
    if not s:
        return None
    if not DATE_RX.match(s):
        raise _ArgError("날짜는 YYYY-MM-DD")
    d = date.fromisoformat(s)
    return local_to_utc(datetime.combine(d + timedelta(days=1 if end else 0), datetime.min.time()))


def _human(msg: str, err) -> None:
    try:
        err.write(msg + "\n")
        err.flush()
    except (OSError, ValueError):
        pass


def _finish(res: dict, err, rc: int) -> int:
    """상태 줄(계약 v1.2 §0.7 C1 한 모양 — ``_status``, 필수 schema·src·rc·reasons·partial·cap_hit·budget_hit·n·counts).
    반복 일정을 일부만 펼쳤으면 R-RECURINC + partial(C4 — 부분 결과, rc 는 그대로)."""
    res["rc"] = rc
    reasons = set(res.get("reasons") or [])
    if res.get("recurrence_incomplete"):
        reasons.add("R-RECURINC")
    res["reasons"] = sorted(reasons)
    res["schema"] = "lm27.collector_status/1"
    res.setdefault("cap_hit", False)
    res.setdefault("budget_hit", False)
    res["partial"] = bool(res["cap_hit"] or res["budget_hit"] or res.get("recurrence_incomplete"))
    res["n"] = int(res.get("items_ok") or 0)
    res.setdefault("counts", {})
    _human(json.dumps({"_status": res}, ensure_ascii=False, separators=(",", ":"), sort_keys=True), err)
    if events.mode() == "jsonl":
        events.emit("result", stage="import", **{k: v for k, v in res.items() if k != "stage"})
    return rc


def collect(kind: str, pc_id: str, *, paths: Paths, cfg, backend: Backend, in_dir: str = "", lo=None, hi=None,
            now: datetime | None = None, err=None) -> int:
    """반입 1회. 반환 = 수집기 rc. 결과 줄은 err(stderr)로."""
    err = err if err is not None else sys.stderr
    now = now or datetime.now(UTC)
    src = SRC_OF[kind]
    owner = str(cfg["collect.ownerAddress"] or "").strip().lower()
    my_addrs = (owner,) if owner else ()
    folder = in_dir or str(cfg["collect.importDir"] or "") or str(paths.import_dir())
    counts = {"files": 0, "new_files": 0, "done_files": 0, "bad_files": 0, "too_large": 0, "bad_rows": 0,
              "out_of_range": 0, "other_kind_csv": 0, "replies_skipped": 0, "stored": 0, "dropped": {},
              "errors": 0, "rows_in": 0}
    res = {"src": src, "stage": "import", "items_total": 0, "items_ok": 0, "items_failed": 0, "skipped_msg": 0,
           "recurrence_incomplete": 0, "reasons": [], "counts": counts}
    if kind == "mail" and not my_addrs:
        res["reasons"].append("R-NOADDR")
    if not os.path.isdir(folder):
        _human(f"[반입] {src}: 반입 폴더가 없습니다 — 대상 없음", err)
        return _finish(res, err, RC_NONE)
    files = scan_files(folder)
    cur = backend.load_raw_cursor(paths, pc_id) or {}
    prev = cur.get(src) if isinstance(cur, dict) else None
    done = dict(prev.get("done") or {}) if isinstance(prev, dict) and isinstance(prev.get("done"), dict) else {}
    seen_pairs = {tuple(v) for v in done.values() if isinstance(v, list) and len(v) == 2}
    window = (lo or now - timedelta(days=int(cfg["collect.lookbackDays"])), hi or now + timedelta(days=CAL_AHEAD_DAYS))
    raws, new_done = [], {}
    hb = events.Heartbeat(events.HEARTBEAT_SEC, stage="import", total=len(files)) if events.mode() == "jsonl" else None
    try:
        if hb is not None:
            hb.__enter__()
        for i, (_rel, path, ext) in enumerate(files):
            if hb is not None:
                hb.update(done=i)
            if ext in EXT_MSG:
                if kind == "mail":
                    res["skipped_msg"] += 1
                continue
            if (kind == "mail" and ext in EXT_CAL) or (kind == "cal" and ext in EXT_MAIL):
                continue
            try:
                st = os.stat(path)
            except OSError:
                counts["bad_files"] += 1
                continue
            if st.st_size > MAX_FILE_BYTES:
                counts["too_large"] += 1
                continue
            pair = (int(st.st_size), int(st.st_mtime_ns))
            counts["files"] += 1
            if pair in seen_pairs:
                counts["done_files"] += 1
                continue
            try:
                data = fsx.read_bytes(path)
            except OSError:
                counts["bad_files"] += 1
                continue
            sha16 = hashlib.sha256(data).hexdigest()[:16]
            if sha16 in done:
                counts["done_files"] += 1
                new_done[sha16] = list(pair)              # 내용이 같으면 크기·시각만 새로
                continue
            try:
                recs = _parse_file(kind, ext, data, my_addrs, now, window, counts, res)
            except Exception as e:                      # noqa: BLE001 — 한 파일 오류로 반입 전체를 멈추지 않는다(유형만 센다)
                counts["bad_files"] += 1
                by = counts.setdefault("bad_file_errors", {})
                by[type(e).__name__] = by.get(type(e).__name__, 0) + 1
                continue
            if recs is None:                              # 다른 kind 의 CSV — 그 kind 반입이 처리한다(표식 없음)
                continue
            counts["new_files"] += 1
            for r in recs:
                if in_range(r, kind, lo, hi):
                    raws.append(r)
                else:
                    counts["out_of_range"] += 1
            new_done[sha16] = list(pair)
    finally:
        if hb is not None:
            hb.__exit__(None, None, None)

    if counts["files"] == 0:
        _human(f"[반입] {src}: 반입할 파일이 없습니다 — 대상 없음"
               + (f"(.msg {res['skipped_msg']}개는 지원하지 않아 건너뜀 — EML 로 저장해 넣으세요)" if res["skipped_msg"] else ""),
               err)
        return _finish(res, err, RC_NONE)
    counts["rows_in"] = res["items_total"] = len(raws)
    if raws:
        try:
            stored, dropped, errors = _sanitize_and_store(kind, src, pc_id, paths, backend, my_addrs, raws)
        except Exception as e:                          # noqa: BLE001 — 저장 실패는 rc 3, 원문·메시지 없이 유형만
            counts["store_error"] = type(e).__name__
            res["reasons"].append("R-TRANSPORT")
            _human(f"[반입] {src}: 정제·저장 실패({type(e).__name__}) — 커서를 그대로 두고 다음 실행에서 다시 읽습니다", err)
            return _finish(res, err, RC_DRIVER)
        counts["stored"], counts["dropped"], counts["errors"] = stored, dropped, errors
        res["items_ok"], res["items_failed"] = stored, errors
    if new_done:
        merged = dict(done)
        merged.update(new_done)
        try:
            backend.save_raw_cursor(paths, pc_id, src, {"done": dict(sorted(merged.items()))})
        except Exception as e:                          # noqa: BLE001 — 커서 저장 실패: 다음 실행이 다시 읽고 id 로 흡수
            counts["cursor_error"] = type(e).__name__
            res["reasons"].append("R-TRANSPORT")
            _human(f"[반입] {src}: 커서 저장 실패({type(e).__name__}) — 다음 실행에서 다시 읽습니다", err)
            return _finish(res, err, RC_DRIVER)
    rc = RC_SAVED if raws else RC_NONEW
    nd = sum(counts["dropped"].values()) if isinstance(counts["dropped"], dict) else 0
    _human(f"[반입] {src}: 파일 {counts['files']}개(새 {counts['new_files']}) · 레코드 {len(raws)} · 저장 "
           f"{counts['stored']} · 버림 {nd} · 오류 {counts['errors']}"
           + (f" · .msg {res['skipped_msg']}개 건너뜀(지원 안 함 — EML 로 저장해 넣으세요)" if res["skipped_msg"] else ""),
           err)
    return _finish(res, err, rc)


def _parse_file(kind, ext, data, my_addrs, now, window, counts, res):
    if ext in EXT_MAIL:
        rec = parse_eml(data, my_addrs, now=now)
        if rec is None:
            counts["bad_rows"] += 1
            return []
        return [rec]
    if ext in EXT_CAL:
        recs, st = parse_ics(data, my_addrs, now=now, window=window)
        res["recurrence_incomplete"] += st["recurrence_incomplete"]
        counts["replies_skipped"] += st["replies_skipped"]
        counts["bad_rows"] += st["bad_events"]
        return recs
    got, recs, st = parse_csv(data, my_addrs, now=now)
    if got != kind:
        counts["other_kind_csv"] += 1
        counts["files"] -= 1
        return None
    counts["bad_rows"] += st["bad_rows"]
    if kind == "cal":
        res["recurrence_incomplete"] += sum(1 for r in recs if r.get("recurrence_incomplete"))
    return recs


def _sanitize_and_store(kind, src, pc_id, paths, backend, my_addrs, raws):
    """정제 관문 통과 행만 SegmentWriter 로(flush 1회 = gzip 멤버 1개). (저장, {버림 사유: 건수}, 오류) 를 돌려준다."""
    rctx = backend.make_record_context(paths.root, src, pc_id, my_addrs=tuple(my_addrs))
    writer = backend.SegmentWriter(paths, pc_id, kind, src)
    stored, errors, dropped = 0, 0, {}
    try:
        for raw in raws:
            out = backend.sanitize_record(kind, raw, rctx)
            status = getattr(out, "status", None)
            if status == "stored":
                writer.append(out.row)
                stored += 1
            elif status == "dropped":
                why = str(getattr(out, "reason", None) or "unknown")
                dropped[why] = dropped.get(why, 0) + 1
            else:
                errors += 1
        writer.flush()
    finally:
        writer.close()
    audit = getattr(rctx, "audit", None)
    if audit is not None:
        for why, n in sorted(dropped.items()):
            audit.add("dropped", why, n)
        audit.flush(rows_in=len(raws), rows_out=stored)
    return stored, dropped, errors


def run(argv=None, *, backend: Backend | None = None, paths: Paths | None = None, cfg=None,
        now: datetime | None = None, err=None) -> int:
    err = err if err is not None else sys.stderr
    res = {"src": None, "stage": "import", "items_total": 0, "items_ok": 0, "items_failed": 0, "skipped_msg": 0,
           "recurrence_incomplete": 0, "reasons": ["R-TRANSPORT"], "counts": {}}
    try:
        a = build_parser().parse_args(argv)
        if not PC_ID_RX.match(a.pc or ""):
            raise _ArgError("pc_id 형식이 아닙니다")
        lo = _local_day_utc(a.from_, end=False)
        hi = _local_day_utc(a.to, end=True)
        if lo is not None and hi is not None and hi <= lo:
            raise _ArgError("--to 가 --from 보다 앞섭니다")
    except _ArgError as e:
        _human(f"[반입] 인자 오류: {e}", err)
        return _finish(res, err, RC_DRIVER)
    events.configure(a.events)
    res["src"] = SRC_OF[a.kind]
    paths = paths or Paths(ROOT)
    cfg = cfg if cfg is not None else load_config(paths)
    if backend is None:
        try:
            backend = real_backend()
        except ImportError as e:
            res["counts"] = {"import_error": type(e).__name__}
            _human(f"[반입] {res['src']}: 정제기 모듈을 불러오지 못했습니다({type(e).__name__}) — 수집하지 않습니다", err)
            _finish(res, err, RC_DRIVER)
            return RC_DRIVER
    try:
        return collect(a.kind, a.pc, paths=paths, cfg=cfg, backend=backend, in_dir=a.in_dir, lo=lo, hi=hi, now=now,
                       err=err)
    except Exception as e:                              # noqa: BLE001 — 예상 밖 오류도 rc 3 + 사유(트레이스백 rc 1 = '대상 없음' 오독 방지)
        res["counts"] = {"error": type(e).__name__}
        _human(f"[반입] {res['src']}: 내부 오류({type(e).__name__}) — 다음 실행에서 다시 시도합니다", err)
        return _finish(res, err, RC_DRIVER)


def main() -> int:
    for st in (sys.stdout, sys.stderr):
        rc_ = getattr(st, "reconfigure", None)
        if rc_ is not None:
            rc_(encoding="utf-8", errors="replace")
    return run()


if __name__ == "__main__":
    sys.exit(main())
