# -*- coding: utf-8 -*-
r"""시험 주입점 자료(WP-05) — 계약 §11.3 단일 목록의 파일·환경 변수를 합성 계획에서 만든다. 수집기·브리지 시험이 실데이터
없이 돌게 한다. 파일은 %TEMP% 아래(복제 트리·임시 폴더)에만 쓴다(tree.guard_write).

    env = env_for(index_fake=write_index_fake(d, plan), owa_fake=write_owa_fake(d, plan), no_browser=True)
    clone.run_py([...], env=clone.env(env))

| 주입점                         | 만드는 것                                           | 읽는 쪽 인코딩(PS 5.1 고려)          |
|--------------------------------|-----------------------------------------------------|--------------------------------------|
| LM_OUTLOOK_SELFTEST=N[,선택…]  | outlook_selftest_env(n, *opts) — COM 수집기·탐침이 가짜 N건(선택 newol·noprof·wizard·dialog·elev·busyall·notrunning·noaddr·omg·slowb·archive·jetfail·horizon=YYYY-MM·hang=attach\|read·delay=<ms>) | — |
| LM_PROBE_FAKE=<json>           | 탐침(Invoke-CapabilityProbe.ps1) 사실 표 — 실기계 조회 대신 이 사실로 판정(WP-17) | UTF-8(BOM 없음, JSON)  |
| LM_INDEX_FAKE=<json>           | write_index_fake — {"mail":[System.* 행], "calendar":[…]}. 선택 키 _error·_total_outlook_items·_policy·_newol·_ext_rejected·_my_addrs | UTF-8(BOM 없음, JSON) |
| LM_OWA_FAKE=<json>             | write_owa_fake — {"login", "mail":{YYYY-MM:{inbox,sent}}, "cal":{날짜:[…]}}. 선택: 항목 open:{head:[…]}(보낸 항목 읽기 창 머리 — 분 단위), 폴더 값 {"pages":[[…]]}·{"how":"","items":[]}, "cal_grid": false, "login": "ca"(WP-26) | UTF-8 |
| LM_TEAMSWEB_FAKE=<json>        | write_teamsweb_fake — {"login", "chats":{…}, "msgs":{idx:[화면 응답…]}}. 선택: chats 를 회차 목록으로 + "chats_end": false, channels · activity(tid·mid·mention), 방 gone:true, 메시지 me·files·mentions·reply_to, 회차 ctype·n_part(WP-26) | UTF-8 |
| LM_COPILOT_STUB=<폴더>         | write_copilot_stub — <stage>.json(B §11.4)          | UTF-8                                |
| Get-TeamsWindow.ps1 -RawFile   | write_teams_rawfile — UIA 원문 줄(작성자, 날짜 시각, 본문) 또는 JSON 스냅숏 | UTF-8 BOM + CRLF  |
| Get-EventActivity.ps1 -EventsCsv -Now -BootTime | write_events_csv + events_args — t,kind,src(kind=channel 줄 = 채널 상태) | ASCII + CRLF |
| Get-OfficeMru.ps1 -MruRegFile  | write_mru_reg — reg 내보내기 텍스트(User MRU)        | UTF-16 LE BOM + CRLF(reg.exe 기본)   |
| Get-RecentFiles.ps1 -RecentDir -MruRegFile | Recent 바로가기 폴더·reg 내보내기(위와 같은 형)  | —                                    |
| 모든 PS 수집기 -TestNow        | 'YYYY-MM-DD HH:MM' 로컬 시각(가상 현재)              | —                                    |

(계약 v1.2 §0.7 C3 등재 — SYNTH_VERSION 2. 환경 변수 주입점 이름은 INJECT_ENV 에서만 꺼내 쓴다.)

수집기 stdout·stdin 제어 줄(계약 §7.3): ndjson(records, meta=…, cursor=…) · in_line(cursor=…, cfg=…, self_names=…).
"""
from __future__ import annotations

import json
import os
from collections.abc import Iterable, Mapping
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from ..tree import guard_write
from .month import ChatEv, MailEv, Plan, at_local, to_local, utc_iso
from .raw_cal import appointment_id
from .raw_mail import conversation_id
from .raw_pc import full_path
from .raw_teams import room_title

INJECT_ENV = {   # 계약 §11.3 환경 변수 주입점(이름은 이 표에서만 꺼내 쓴다)
    "outlook_selftest": "LM_OUTLOOK_SELFTEST",
    "probe_fake": "LM_PROBE_FAKE",                 # 계약 v1.2 §0.7 C3(WP-17 탐침)
    "index_fake": "LM_INDEX_FAKE",
    "owa_fake": "LM_OWA_FAKE",
    "teamsweb_fake": "LM_TEAMSWEB_FAKE",
    "copilot_stub": "LM_COPILOT_STUB",
    "no_browser": "LM_NO_BROWSER",
}
STUB_STAGES = ("lookup_mail", "lookup_teams", "lookup_calendar", "speech_act", "task_label", "taxonomy_bootstrap",
               "taxonomy_consolidate", "workflow_label", "review_text", "agentic_match", "subagent_review")
STUB_DEFAULTS: dict[str, dict] = {"speech_act": {"act": "info", "conf": "m"}}
_FILETIME_EPOCH = datetime(1601, 1, 1, tzinfo=UTC)


# ── 공용 ────────────────────────────────────────────────────────────────────
def canon_bytes(obj) -> bytes:
    """계약 §9.3 정규 JSON 바이트(ensure_ascii=False · sort_keys · 구분자 , : · NaN 금지)."""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _line(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8") + b"\n"


def ndjson(records: Iterable[Mapping], *, meta: Mapping | None = None, cursor: Mapping | None = None,
           kind: str | None = None) -> bytes:
    """PS 수집기 stdout 모양(계약 §7.3): [첫 줄 {"_meta":…}] + 레코드 줄 + [끝 줄 {"_cursor":…}]. kind 를 주면 줄마다 _kind."""
    out = bytearray()
    if meta is not None:
        out += _line({"_meta": dict(meta)})
    for r in records:
        out += _line({**r, "_kind": kind} if kind else dict(r))
    if cursor is not None:
        out += _line({"_cursor": dict(cursor)})
    return bytes(out)


def in_line(*, cursor=None, cfg: Mapping | None = None, self_names: Iterable[str] | None = None) -> bytes:
    """연결자가 수집기 stdin 에 쓰는 한 줄 {"_in": {cursor, cfg, self_names?}}(계약 §7.3)."""
    body: dict = {"cursor": cursor, "cfg": dict(cfg or {})}
    if self_names is not None:
        body["self_names"] = list(self_names)
    return _line({"_in": body})


def env_for(**values) -> dict[str, str]:
    """INJECT_ENV 의 짧은 이름 → 환경 변수 dict. no_browser=True → "1", 경로는 문자열로. None 은 건너뜀."""
    out: dict[str, str] = {}
    for k, v in values.items():
        if k not in INJECT_ENV:
            raise KeyError(f"계약 §11.3 에 없는 주입점: {k}")
        if v is None or v is False:
            continue
        out[INJECT_ENV[k]] = "1" if v is True else str(v)
    return out


SELFTEST_OPTS = frozenset({"newol", "noprof", "wizard", "dialog", "elev", "busyall", "notrunning", "noaddr", "omg",
                           "slowb", "archive", "jetfail"})
SELFTEST_KV = {"horizon": r"\d{4}-\d{2}", "hang": r"attach|read", "delay": r"\d{1,6}"}


def outlook_selftest_env(n: int, *opts: str) -> dict[str, str]:
    """LM_OUTLOOK_SELFTEST=N[,선택…] — COM 수집기·탐침이 가짜 메일·일정 N건을 스스로 만든다(CM §5.1 · 계약 v1.2 C3 문법:
    선택 = SELFTEST_OPTS 낱말 또는 horizon=YYYY-MM · hang=attach|read · delay=<ms>). 모르는 선택은 ValueError."""
    import re
    for o in opts:
        k, eq, v = str(o).partition("=")
        if not ((not eq and k in SELFTEST_OPTS) or (eq and k in SELFTEST_KV and re.fullmatch(SELFTEST_KV[k], v))):
            raise ValueError(f"LM_OUTLOOK_SELFTEST 선택이 아닙니다: {o}")
    return {"LM_OUTLOOK_SELFTEST": ",".join([str(int(n)), *map(str, opts)])}


def _put(path: str | os.PathLike, data: bytes) -> Path:
    p = guard_write(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def _json_file(path: str | os.PathLike, obj) -> Path:
    return _put(path, json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True).encode("utf-8") + b"\n")


def _ampm(t: datetime) -> str:
    """로컬 시각 → '오전 9:05' / '오후 3:40'."""
    h = t.hour % 12 or 12
    return f"{'오전' if t.hour < 12 else '오후'} {h}:{t.minute:02d}"


def _kdate(d: date) -> str:
    return f"{d.year}년 {d.month}월 {d.day}일"


# ── LM_INDEX_FAKE ───────────────────────────────────────────────────────────
def index_fake(plan: Plan, *, pc: str = "PC1") -> dict:
    """Windows Search 색인 행 모양(System.* 속성, 시각은 로컬 'yyyy-MM-dd HH:mm' — 이전 판 시험 주입 형식)."""
    P = plan.persona
    mail = []
    for ev in plan.mails:
        if ev.pc != pc:
            continue
        loc = to_local(ev.utc, ev.off).strftime("%Y-%m-%d %H:%M")
        sender = P.person(ev.sender)
        to = [P.person(x) for x in ev.to]
        cc = [P.person(x) for x in ev.cc]
        folder = "보낸 편지함" if ev.box == "sent" else "받은 편지함"
        row = {
            "System.ItemUrl": f"mapi://lm27t/{folder}/{ev.eid}",
            "System.ItemFolderPathDisplay": "\\" + folder,
            "System.Subject": P.render(ev.subject)[0],
            "System.ItemDate": loc,
            "System.Message.FromName": [sender.name],
            "System.Message.FromAddress": [sender.addr],
            "System.Message.ToName": [p.name for p in to],
            "System.Message.ToAddress": [p.addr for p in to],
            "System.Message.CcName": [p.name for p in cc],
            "System.Message.CcAddress": [p.addr for p in cc],
            "System.Kind": ["email"],
        }
        row["System.Message.DateSent" if ev.box == "sent" else "System.Message.DateReceived"] = loc
        mail.append(row)
    cal = []
    for ev in plan.meets:
        if ev.pc != pc:
            continue
        cal.append({
            "System.ItemUrl": f"mapi://lm27t/일정/{ev.eid}",
            "System.Subject": P.render(ev.subject)[0],
            "System.StartDate": to_local(ev.start, ev.off).strftime("%Y-%m-%d %H:%M"),
            "System.EndDate": to_local(ev.end, ev.off).strftime("%Y-%m-%d %H:%M"),
            "System.Calendar.ShowTimeAs": 2,
            "System.Calendar.Location": P.render(ev.place)[0],
            "System.Calendar.IsRecurring": ev.series is not None,
            "System.Kind": ["calendar"],
        })
    return {"mail": mail, "calendar": cal}


def write_index_fake(dirpath: str | os.PathLike, plan: Plan, *, pc: str = "PC1", name: str = "index_fake.json") -> Path:
    return _json_file(Path(dirpath) / name, index_fake(plan, pc=pc))


# ── LM_OWA_FAKE ─────────────────────────────────────────────────────────────
def _owa_when(ev_utc: datetime, off: int, as_of_local: datetime) -> str:
    loc = to_local(ev_utc, off)
    if loc.date() == as_of_local.date():
        return _ampm(loc)
    if loc.date() == as_of_local.date() - timedelta(days=1):
        return "어제 " + _ampm(loc)
    return loc.date().isoformat()                       # 어제 이전은 날짜만(date-only — CM §15 #11)


def _owa_item(ev: MailEv, plan: Plan, as_of_local: datetime) -> dict:
    P = plan.persona
    subj = P.render(ev.subject)[0]
    when = _owa_when(ev.utc, ev.off, as_of_local)
    if ev.box == "sent":
        who = "받는 사람 " + ", ".join(P.person(x).name for x in ev.to)
    else:
        who = P.person(ev.sender).name
    label = f"{who}, {subj}, {when}"
    preview = P.render(ev.body)[0][:40]
    return {"key": f"{conversation_id(ev.thread)}|{label[:80]}", "label": label, "titles": [subj],
            "texts": [who, subj, preview, when]}


def owa_fake(plan: Plan, *, as_of: datetime | None = None, login: bool = False) -> dict:
    """OWA 화면 응답 모양: 달 × 폴더(받은·보낸) 항목(aria-label·title·leaf texts) + 날짜별 일정. login=True 면 로그인 필요."""
    P = plan.persona
    as_of_local = to_local(as_of or plan.as_of, P.offset_min)
    mail: dict[str, dict[str, list]] = {}
    for ev in plan.mails:
        month = to_local(ev.utc, ev.off).strftime("%Y-%m")
        box = mail.setdefault(month, {"inbox": [], "sent": []})
        box["sent" if ev.box == "sent" else "inbox"].append(_owa_item(ev, plan, as_of_local))
    cal: dict[str, list] = {}
    for ev in plan.meets:
        s, e = to_local(ev.start, ev.off), to_local(ev.end, ev.off)
        subj = P.render(ev.subject)[0]
        place = P.render(ev.place)[0]
        cal.setdefault(s.date().isoformat(), []).append({
            "label": f"{subj}, {_kdate(s.date())} {_ampm(s)} - {_ampm(e)}, {place}",
            "texts": [subj, f"{_ampm(s)} - {_ampm(e)}", place]})
    return {"login": login, "mail": mail, "cal": cal}


def write_owa_fake(dirpath: str | os.PathLike, plan: Plan, *, as_of: datetime | None = None, login: bool = False,
                   name: str = "owa_fake.json") -> Path:
    return _json_file(Path(dirpath) / name, owa_fake(plan, as_of=as_of, login=login))


# ── LM_TEAMSWEB_FAKE ────────────────────────────────────────────────────────
def _web_msg(ev: ChatEv, plan: Plan) -> dict:
    P = plan.persona
    author = P.person(ev.author).name
    body = P.render(ev.body)[0]
    loc = to_local(ev.utc, ev.off)
    return {"t": "msg", "label": f"{author} {_ampm(loc)} {body[:60]}", "author": author, "ts": _ampm(loc),
            "iso": [utc_iso(ev.utc)], "titles": list(ev.files), "body": body, "texts": [author, body, *ev.files],
            "mid": ev.mid}


def teamsweb_fake(plan: Plan, *, login: bool = False) -> dict:
    """Teams 웹 화면 응답 모양: 채팅 목록 + 방별 메시지 화면(날짜 구분선 · data-mid · <time datetime>)."""
    rooms = plan.rooms
    items = [{"idx": i, "label": room_title(r, plan), "texts": [room_title(r, plan)], "tid": r.raw_id}
             for i, r in enumerate(rooms)]
    msgs: dict[str, list] = {}
    for i, r in enumerate(rooms):
        evs = sorted((ev for ev in plan.chats if ev.room.raw_id == r.raw_id), key=lambda e: (e.utc, e.mid))
        page: list[dict] = []
        last_day = None
        for ev in evs:
            day = to_local(ev.utc, ev.off).date()
            if day != last_day:
                page.append({"t": "sep", "text": _kdate(day)})
                last_day = day
            page.append(_web_msg(ev, plan))
        msgs[str(i)] = [{"how": "[data-mid]", "chat": room_title(r, plan),
                         "n": sum(1 for x in page if x["t"] == "msg"), "items": page}]
    return {"login": login, "chats": {"how": "[role=treeitem]", "n": len(items), "items": items}, "msgs": msgs}


def write_teamsweb_fake(dirpath: str | os.PathLike, plan: Plan, *, login: bool = False,
                        name: str = "teamsweb_fake.json") -> Path:
    return _json_file(Path(dirpath) / name, teamsweb_fake(plan, login=login))


# ── LM_COPILOT_STUB ─────────────────────────────────────────────────────────
def copilot_stub(stages: Mapping[str, Mapping] | None = None) -> dict[str, dict]:
    """단계별 스텁 답(B §11.4): {"mode": [...], "default": {...}, "by_key": {...}}. stages 로 단계별 덮어쓰기."""
    out = {s: {"mode": ["ok"], "default": dict(STUB_DEFAULTS.get(s, {})), "by_key": {}} for s in STUB_STAGES}
    for s, spec in (stages or {}).items():
        out[s] = {**out.get(s, {"mode": ["ok"], "default": {}, "by_key": {}}), **dict(spec)}
    return out


def write_copilot_stub(dirpath: str | os.PathLike, stages: Mapping[str, Mapping] | None = None) -> Path:
    """폴더에 <stage>.json 을 쓰고 폴더 경로를 돌려준다(LM_COPILOT_STUB 값)."""
    d = Path(dirpath)
    for s, spec in copilot_stub(stages).items():
        _json_file(d / f"{s}.json", spec)
    return guard_write(d)


# ── Get-TeamsWindow.ps1 -RawFile ────────────────────────────────────────────
def teams_rawfile(plan: Plan, *, pc: str = "PC1", undated: int = 2) -> str:
    """UIA 원문 재생 줄: '작성자, 2026년 9월 1일 오전 10:05, 본문'. 끝의 undated 줄은 날짜 표기 없이(날짜 미상 격리 시험)."""
    P = plan.persona
    lines = []
    evs = sorted((ev for ev in plan.chats if ev.pc == pc), key=lambda e: (e.utc, e.mid))
    for ev in evs:
        loc = to_local(ev.utc, ev.off)
        lines.append(f"{P.person(ev.author).name}, {_kdate(loc.date())} {_ampm(loc)}, {P.render(ev.body)[0]}")
    for ev in evs[-undated:] if undated > 0 else []:
        loc = to_local(ev.utc, ev.off)
        lines.append(f"{P.person(ev.author).name}, {_ampm(loc)}, {P.render(ev.body)[0]}")
    return "\r\n".join(lines) + "\r\n"


def write_teams_rawfile(path: str | os.PathLike, plan: Plan, *, pc: str = "PC1", undated: int = 2) -> Path:
    return _put(path, b"\xef\xbb\xbf" + teams_rawfile(plan, pc=pc, undated=undated).encode("utf-8"))


# ── Get-EventActivity.ps1 -EventsCsv -Now -BootTime ─────────────────────────
_ON_SRC = {"boot": "6005", "logon": "7001", "wake": "1", "unlock": "4801", "rdp_connect": "25"}
_OFF_SRC = {"boot": "6006", "logon": "7002", "wake": "42", "unlock": "4800", "rdp_connect": "24"}


def events_csv(plan: Plan, *, pc: str = "PC1") -> str:
    """합성 이벤트 CSV(t,kind,src): 전원·세션 구간의 시작 on · 끝 off, t 는 로컬 'yyyy-MM-dd HH:mm'."""
    rows = ["t,kind,src"]
    evs = sorted((ev for ev in plan.power if ev.pc == pc), key=lambda e: (e.start, e.eid))
    for ev in evs:
        rows.append(f"{to_local(ev.start, ev.off):%Y-%m-%d %H:%M},on,{_ON_SRC.get(ev.event_class, '6005')}")
        rows.append(f"{to_local(ev.end, ev.off):%Y-%m-%d %H:%M},off,{_OFF_SRC.get(ev.event_class, '6006')}")
    return "\r\n".join(rows) + "\r\n"


def write_events_csv(path: str | os.PathLike, plan: Plan, *, pc: str = "PC1") -> Path:
    return _put(path, events_csv(plan, pc=pc).encode("ascii"))


def events_args(path: str | os.PathLike, plan: Plan, *, pc: str = "PC1") -> list[str]:
    """Get-EventActivity.ps1 시험 인자: -EventsCsv <path> -Now <마지막 근무일 끝 + 30분> -BootTime <마지막 부팅>."""
    boots = sorted((ev for ev in plan.power if ev.pc == pc and ev.layer == "L0"), key=lambda e: e.start)
    if not boots:
        raise ValueError(f"{pc} 의 전원 사건이 없습니다")
    last = boots[-1]
    now = to_local(last.end + timedelta(minutes=30), last.off)
    return ["-EventsCsv", str(path), "-Now", f"{now:%Y-%m-%d %H:%M}",
            "-BootTime", f"{to_local(last.start, last.off):%Y-%m-%d %H:%M}"]


# ── Get-OfficeMru.ps1 -MruRegFile ───────────────────────────────────────────
_MRU_APPS = {"docx": "Word", "xlsx": "Excel", "pptx": "PowerPoint"}


def _filetime_hex(t: datetime) -> str:
    """FILETIME(1601-01-01 UTC 부터 100ns 단위) 16진 16자리 — 정수 연산(부동소수 반올림 없음)."""
    dt = t - _FILETIME_EPOCH
    return f"{(dt.days * 86400 + dt.seconds) * 10_000_000 + dt.microseconds * 10:016X}"


def _reg_str(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def mru_reg(plan: Plan, *, versions: Iterable[str] = ("16.0",), limit: int = 20, pc: str = "PC1") -> str:
    """Office User MRU 레지스트리 내보내기 텍스트(reg.exe export 모양). 앱별 최근 문서 limit 개, Item 1 = 가장 최근."""
    P = plan.persona
    latest: dict[str, tuple[datetime, str]] = {}
    for ev in plan.files:
        ext = ev.name.rsplit(".", 1)[-1].lower()
        if ev.pc != pc or ext not in _MRU_APPS:
            continue
        path = full_path(P, ev)
        if path not in latest or latest[path][0] < ev.utc:
            latest[path] = (ev.utc, ext)
    lines = ["Windows Registry Editor Version 5.00", ""]
    for ver in versions:
        for ext, app in _MRU_APPS.items():
            items = sorted(((t, p) for p, (t, e) in latest.items() if e == ext), reverse=True)[:limit]
            if not items:
                continue
            key = f"HKEY_CURRENT_USER\\Software\\Microsoft\\Office\\{ver}\\{app}\\User MRU\\ADAL_LM27T0000\\File MRU"
            lines.append(f"[{key}]")
            lines.append('"Max Display"=dword:00000032')
            for i, (t, p) in enumerate(items, 1):
                lines.append(f'"Item {i}"="[F00000000][T{_filetime_hex(t)}][O00000000]*{_reg_str(p)}"')
            lines.append("")
    return "\r\n".join(lines) + "\r\n"


def write_mru_reg(path: str | os.PathLike, plan: Plan, *, versions: Iterable[str] = ("16.0",), limit: int = 20,
                  pc: str = "PC1") -> Path:
    return _put(path, b"\xff\xfe" + mru_reg(plan, versions=versions, limit=limit, pc=pc).encode("utf-16-le"))


# ── 묶음 ────────────────────────────────────────────────────────────────────
def write_all(dirpath: str | os.PathLike, plan: Plan, *, as_of: datetime | None = None) -> dict[str, Path]:
    """주입 자료 전부를 dirpath 아래에 쓴다 → {이름: 경로}. env_for(index_fake=…, owa_fake=…, …) 로 환경을 만든다."""
    d = Path(dirpath)
    return {
        "index_fake": write_index_fake(d, plan),
        "owa_fake": write_owa_fake(d, plan, as_of=as_of),
        "teamsweb_fake": write_teamsweb_fake(d, plan),
        "copilot_stub": write_copilot_stub(d / "copilot_stub"),
        "teams_rawfile": write_teams_rawfile(d / "teams_raw.txt", plan),
        "events_csv": write_events_csv(d / "events.csv", plan),
        "mru_reg": write_mru_reg(d / "office_mru.reg", plan),
    }


def appointment_ids(plan: Plan) -> list[str]:
    """시험 편의: 계획의 일정 GlobalAppointmentID 목록(색인·OWA 대조용)."""
    return [appointment_id(ev, plan) for ev in plan.meets]


def first_workday_utc(plan: Plan) -> str:
    """시험 편의: 첫 근무일 09:00 로컬의 UTC 문자열(가상 시계 시작점)."""
    return utc_iso(at_local(plan.workdays[0], 9 * 60, plan.persona.offset_min))
