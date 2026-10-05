# -*- coding: utf-8 -*-
"""합성 활동 계획(WP-05) — 한 사람의 기간 활동을 사건 목록(Plan)으로 만든다. raw_* 와 stored 가 같은 계획에서
원시 모양·저장 모양을 낸다(같은 계획 → 같은 사건 → 원시·저장이 서로 맞는다).

    plan = plan_period(date(2026, 9, 1), date(2026, 9, 30))     # 기본 밀도 light(근무일당 약 120 신호)
    plan = plan_month(2026, 10, seed=3, multi_pc=True)           # 금요일은 PC2(노트북)에서
    rows = signals_3m()                                          # 1명 × 3개월 ≈ 4.3만 저장 행(T-19 · W-G9), 60초 안

밀도 perf 는 design\\judge\\perf.py 의 분포를 따른다: 근무일당 메시지 250(메일 125 · 팀즈 125) + 의뢰 메일 6 + 회의 4 +
샘플러 300 + 문서 저장 150 + 커밋 6. 시각은 로컬(페르소나 오프셋) 기준으로 정하고 UTC 로 저장한다.
"""
from __future__ import annotations

import json
import random
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from .persona import Persona, default_persona

TREE_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_D0 = date(2026, 9, 1)
DEFAULT_D1 = date(2026, 9, 30)


# ── 시간 도우미 ─────────────────────────────────────────────────────────────
def utc_iso(dt: datetime) -> str:
    """계약 §9.4 저장 시각 YYYY-MM-DDTHH:MM:SSZ."""
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def fmt_offset(minutes: int) -> str:
    """분 오프셋 → '+09:00'."""
    sign = "+" if minutes >= 0 else "-"
    m = abs(minutes)
    return f"{sign}{m // 60:02d}:{m % 60:02d}"


def at_local(d: date, minute: int, off: int, second: int = 0) -> datetime:
    """로컬 날짜 d 의 '하루 중 분' → UTC 시각(aware)."""
    return datetime(d.year, d.month, d.day, tzinfo=UTC) + timedelta(minutes=minute - off, seconds=second)


def to_local(dt: datetime, off: int) -> datetime:
    """UTC 시각 → 로컬 벽시계(naive)."""
    return (dt.astimezone(UTC) + timedelta(minutes=off)).replace(tzinfo=None)


def local_midnight(dt: datetime, off: int) -> datetime:
    """dt 가 속한 로컬 날짜의 00:00 을 UTC 로."""
    loc = to_local(dt, off)
    return at_local(loc.date(), 0, off)


# ── 사건 ────────────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class MailEv:
    eid: str
    pc: str
    utc: datetime
    off: int
    box: str                      # inbox · sent
    folder_role: str              # inbox · sent · subfolder
    sender: str                   # 사람 pid
    to: tuple[str, ...]
    cc: tuple[str, ...]
    subject: tuple                # 텍스트 조각(persona.render)
    body: tuple
    thread: str                   # 대화 ID 원시 재료
    reply: bool
    attach: tuple[str, ...]       # 첨부 파일 이름(원문)
    act: str                      # request · info · ask · sched · report · ack
    importance: int = 1


@dataclass(frozen=True, slots=True)
class MeetEv:
    eid: str
    pc: str
    start: datetime
    end: datetime
    off: int
    subject: tuple
    organizer: str
    attendees: tuple[str, ...]
    location: str                 # online · room · external (location_class)
    place: tuple                  # 장소 원문 조각(저장 안 함)
    series: str | None            # 반복 시리즈 원시 재료
    response: int                 # 0 없음(내가 주최) · 3 수락
    body: tuple
    busy: str = "busy"


@dataclass(frozen=True, slots=True)
class Room:
    raw_id: str                   # 웹 대화 ID(19:…@thread.example — 실제 모양을 example 도메인으로)
    uia_id: str                   # UIA 합성 ID
    chat_type: str                # 1:1 · group · channel
    members: tuple[str, ...]
    title: tuple | None           # group·channel 제목 조각(1:1 은 None)


@dataclass(frozen=True, slots=True)
class ChatEv:
    eid: str
    pc: str
    utc: datetime
    off: int
    room: Room
    author: str
    body: tuple
    files: tuple[str, ...]
    reply_to: str | None          # 채널 글타래 루트 메시지 ID
    mentions_me: bool
    act: str
    mid: str                      # 메시지 ID(웹 data-mid 모양)


@dataclass(frozen=True, slots=True)
class TickEv:
    eid: str
    pc: str
    utc: datetime
    off: int
    interval: int                 # 초
    exe: str
    app_id: str
    app_class: str
    title: tuple | None           # 창 제목 조각
    doc: str | None               # 창 제목 속 문서 이름(원문)
    idle: int
    state: str                    # active · locked
    layer: str                    # L2 · L3


@dataclass(frozen=True, slots=True)
class PowerEv:
    eid: str
    pc: str
    start: datetime
    end: datetime
    off: int
    event_class: str              # boot · logon …
    layer: str                    # L0 · L1
    end_uncertain: bool = False


@dataclass(frozen=True, slots=True)
class FileEv:
    eid: str
    pc: str
    utc: datetime
    off: int
    folder: tuple[str, ...]       # 사용자 프로필 아래 폴더(원문)
    name: str                     # 파일 이름(원문)
    op: str                       # create · save · modify
    size: int
    totaltime: int
    revision: int
    last_by: str                  # 마지막 저장자 pid
    pdf_sibling: bool


@dataclass(frozen=True, slots=True)
class CommitEv:
    eid: str
    pc: str
    utc: datetime
    off: int
    repo: str
    sha: str
    subject: tuple
    n_files: int
    exts: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ComputeEv:
    eid: str
    pc: str
    start: datetime
    end: datetime
    off: int
    exe: str
    app_id: str
    cpu_core: float


@dataclass(frozen=True, slots=True)
class ManualEv:
    eid: str
    pc: str
    day: date
    start_min: int | None
    end_min: int | None
    off: int
    category: str
    hours: float
    note: tuple
    entity: tuple | None
    project_id: str | None
    man_kind: str
    role_field: str
    role_func: str


@dataclass(frozen=True)
class Density:
    mail_in: int
    mail_out: int
    meets: int
    chats: int
    ticks: int
    saves: int
    commits: int
    commit_every: int
    compute_weekday: int | None
    manual_weekday: int | None


DENSITIES = {
    "light": Density(3, 2, 1, 6, 96, 4, 1, 2, 2, 4),
    "perf": Density(87, 44, 4, 125, 300, 150, 6, 1, 2, 4),
}


@dataclass
class Plan:
    persona: Persona
    d0: date
    d1: date
    seed: int
    density: str
    workdays: list[date]
    rooms: list[Room]
    mails: list[MailEv] = field(default_factory=list)
    meets: list[MeetEv] = field(default_factory=list)
    chats: list[ChatEv] = field(default_factory=list)
    ticks: list[TickEv] = field(default_factory=list)
    power: list[PowerEv] = field(default_factory=list)
    files: list[FileEv] = field(default_factory=list)
    commits: list[CommitEv] = field(default_factory=list)
    computes: list[ComputeEv] = field(default_factory=list)
    manuals: list[ManualEv] = field(default_factory=list)

    @property
    def as_of(self) -> datetime:
        """분석 시각 기본값 = 기간 다음 날 09:00 로컬."""
        return at_local(self.d1 + timedelta(days=1), 9 * 60, self.persona.offset_min)

    def counts(self) -> dict[str, int]:
        """kind 별 사건 수(pc_session = 샘플러 + 이벤트)."""
        return {"mail": len(self.mails), "cal": len(self.meets), "teams": len(self.chats),
                "pc_session": len(self.ticks) + len(self.power), "pc_file": len(self.files),
                "pc_git": len(self.commits), "pc_compute": len(self.computes), "manual": len(self.manuals)}

    def n_signals(self) -> int:
        return sum(self.counts().values())


# ── 생성 ────────────────────────────────────────────────────────────────────
APPS = (  # exe · app_id(카탈로그 slug 모양) · app_class · 문서 확장자 · 제목 꼬리
    ("excel.exe", "excel", "office", "xlsx", " - Excel"),
    ("winword.exe", "word", "office", "docx", " - Word"),
    ("powerpnt.exe", "powerpoint", "office", "pptx", " - PowerPoint"),
    ("cadtool.exe", "unknown:cadtool.exe", "cad", "dwg", " - CAD"),
    ("msedge.exe", "edge", "browser", None, " - Microsoft Edge"),
    ("outlook.exe", "outlook", "mail_work", None, " - Outlook"),
    ("ms-teams.exe", "teams", "chat_work", None, " | Microsoft Teams"),
    ("explorer.exe", "explorer", "system", None, ""),
)
APP_W = (4, 2, 2, 2, 2, 2, 2, 1)
ACT_WORD = {"request": "검토 요청", "info": "자료 공유", "ask": "문의드립니다", "sched": "일정 협의",
            "report": "결과 보고", "ack": "확인 회신"}
ACT_BODY = {"request": "검토 부탁드립니다. 금요일까지 회신 바랍니다.", "info": "참고 자료 공유드립니다.",
            "ask": "확인 가능하실까요?", "sched": "회의 일정 조율 부탁드립니다.",
            "report": "결과 보고드립니다. 첨부 확인 부탁드립니다.", "ack": "확인했습니다. 감사합니다."}
CHAT_LINE = {"request": "검토 부탁드립니다", "ack": "넵 확인했습니다", "report": "결과 공유드립니다",
             "ask": "이거 확인 가능하실까요?", "info": "참고 자료 올립니다", "sched": "내일 10시 회의 가능하세요?"}
TAILS = ("", "", "_v2", "_v3", "_최종")


def _rooms(seed: int) -> list[Room]:
    r = random.Random(f"lm27-plan/{seed}/rooms")

    def rid() -> str:          # 웹 대화 ID 모양(19:…@thread…) — 도메인 자리는 example 계열로 둔다(L-26)
        return f"19:{r.getrandbits(128):032x}@thread.example"

    return [
        Room(rid(), "uia:chat:01", "1:1", ("self", "p01"), None),
        Room(rid(), "uia:chat:02", "group", ("self", "p01", "p02", "p03"), (("proj", 0), " 설계 협의")),
        Room(rid(), "uia:chat:03", "channel", ("self", "p01", "p02", "p03", "p04", "p05"), (("proj", 2), " 양산 채널")),
        Room(rid(), "uia:chat:04", "1:1", ("self", "p02"), None),
    ]


class _Builder:
    def __init__(self, plan: Plan, dens: Density, multi_pc: bool):
        self.p = plan
        self.P = plan.persona
        self.k = dens
        self.multi_pc = multi_pc
        s = plan.seed
        self.r = {name: random.Random(f"lm27-plan/{s}/{name}")
                  for name in ("mail", "meet", "chat", "tick", "file", "git", "misc")}
        self.n: dict[str, int] = {}
        self.rev: dict[str, int] = {}
        self.open: list[tuple[str, int, str, str]] = []      # (대화, 과제, 주제, 의뢰자) — 답신 재료
        self.roots: dict[str, str] = {}                       # 채널 방 → 글타래 루트 메시지 ID

    def eid(self, pre: str) -> str:
        self.n[pre] = self.n.get(pre, 0) + 1
        return f"{pre}{self.n[pre]:06d}"

    def pc_for(self, d: date) -> str:
        return "PC2" if self.multi_pc and d.weekday() == 4 else "PC1"

    def day(self, i: int, d: date) -> None:
        off = self.P.offset_min
        pc = self.pc_for(d)
        npj = len(self.P.projects)
        active = [(i + j) % npj for j in range(3)]
        self._power(d, pc, off)
        self._ticks(d, pc, off, active)
        self._mails(d, pc, off, active)
        self._meets(d, pc, off, active)
        self._chats(d, pc, off, active)
        self._files(d, pc, off, active)
        if i % self.k.commit_every == 0:
            self._commits(d, pc, off)
        if self.k.compute_weekday is not None and d.weekday() == self.k.compute_weekday:
            self._compute(d, pc, off)
        if self.k.manual_weekday is not None and d.weekday() == self.k.manual_weekday:
            self._manual(d, pc, off, i)

    def _doc(self, r: random.Random, pi: int, ext: str, tail: str = "") -> tuple[str, tuple]:
        pj = self.P.projects[pi]
        topic = r.choice(pj.topics)
        return f"{topic}_{pj.codename}{tail}.{ext}", (f"{topic}_", ("proj", pi), f"{tail}.{ext}")

    def _power(self, d: date, pc: str, off: int) -> None:
        self.p.power.append(PowerEv(self.eid("e"), pc, at_local(d, 8 * 60 + 50, off), at_local(d, 18 * 60 + 10, off),
                                    off, "boot", "L0"))
        self.p.power.append(PowerEv(self.eid("e"), pc, at_local(d, 8 * 60 + 52, off), at_local(d, 18 * 60 + 8, off),
                                    off, "logon", "L1"))

    def _ticks(self, d: date, pc: str, off: int, active: list[int]) -> None:
        r = self.r["tick"]
        step = (8 * 3600) // self.k.ticks                    # 09~12 · 13~18 = 8시간
        for j in range(self.k.ticks):
            sec = j * step
            sec += 9 * 3600 if sec < 3 * 3600 else 10 * 3600     # 12:00 이후는 13:00 부터
            exe, app_id, cls, ext, suffix = r.choices(APPS, APP_W)[0]
            title: tuple | None
            doc = None
            if ext:
                doc, parts = self._doc(r, r.choice(active), ext)
                title = (*parts, suffix)
            elif cls == "browser":
                title = ("사내 포털 - 업무 공지", suffix)
            elif cls == "mail_work":
                title = ("받은 편지함", suffix)
            elif cls == "chat_work":
                title = ("채팅", suffix)
            else:
                title = None
            self.p.ticks.append(TickEv(self.eid("s"), pc, at_local(d, 0, off, sec), off, step, exe, app_id, cls, title,
                                       doc, r.randint(0, 90), "active", "L2" if cls in ("system", "idle") else "L3"))
        self.p.ticks.append(TickEv(self.eid("s"), pc, at_local(d, 12 * 60, off), off, 3600, "lockapp.exe", "lockapp",
                                   "idle", None, None, 3600, "locked", "L2"))

    def _mails(self, d: date, pc: str, off: int, active: list[int]) -> None:
        r = self.r["mail"]
        P = self.P
        for j in range(self.k.mail_in):
            pi = r.choice(active)
            topic = r.choice(P.projects[pi].topics)
            sender = r.choice(P.peers)
            act = "request" if j == 0 or r.random() < 0.3 else r.choice(("info", "ask", "sched"))
            thread = "conv-" + self.eid("t")
            cc = tuple(x.pid for x in r.sample(P.internal_peers, r.randint(0, 2)) if x.pid != sender.pid)
            subj = (("proj", pi), f" {topic} {ACT_WORD[act]}")
            body = (("person", "self"), f" {P.me.title}님, ", ("proj", pi), f" {topic} {ACT_BODY[act]}")
            if sender.org == "customer":
                body = (*body, " ", ("org", "C01"), " 드림")
            self.p.mails.append(MailEv(self.eid("m"), pc, at_local(d, r.randrange(8 * 60 + 30, 18 * 60), off,
                                                                    r.randrange(60)), off, "inbox",
                                       "subfolder" if r.random() < 0.1 else "inbox", sender.pid, ("self",), cc,
                                       subj, body, thread, False, (), act, 2 if act == "request" else 1))
            if act in ("request", "ask"):
                self.open.append((thread, pi, topic, sender.pid))
        for _ in range(self.k.mail_out):
            if self.open and r.random() < 0.8:
                thread, pi, topic, to = self.open.pop(0)
                reply = True
            else:
                pi = r.choice(active)
                topic = r.choice(P.projects[pi].topics)
                to = r.choice(P.internal_peers).pid
                thread = "conv-" + self.eid("t")
                reply = False
            attach: tuple[str, ...] = ()
            if r.random() < 0.6:
                name, _parts = self._doc(r, pi, r.choice(("xlsx", "docx", "pptx")), r.choice(TAILS))
                attach = (name,)
            act = "report" if attach else r.choice(("info", "ack"))
            subj = ("RE: " if reply else "", ("proj", pi), f" {topic} {ACT_WORD[act]}")
            body = (("person", to), f" {P.person(to).title}님, ", ("proj", pi), f" {topic} {ACT_BODY[act]}")
            cc = tuple(x.pid for x in r.sample(P.internal_peers, r.randint(0, 1)) if x.pid != to)
            self.p.mails.append(MailEv(self.eid("m"), pc, at_local(d, r.randrange(9 * 60, 18 * 60 + 30), off,
                                                                    r.randrange(60)), off, "sent", "sent", "self",
                                       (to,), cc, subj, body, thread, reply, attach, act))

    def _meets(self, d: date, pc: str, off: int, active: list[int]) -> None:
        r = self.r["meet"]
        P = self.P
        slots = (10 * 60, 14 * 60, 15 * 60 + 30, 16 * 60 + 30, 9 * 60 + 30)
        for j in range(self.k.meets):
            weekly = d.weekday() == 0 and j == 0
            pi = 4 if weekly else active[j % len(active)]
            start = slots[j % len(slots)]
            org = "self" if r.random() < 0.3 else r.choice(P.internal_peers).pid
            att = tuple(sorted({org, "self", *(x.pid for x in r.sample(P.internal_peers, r.randint(1, 3)))}))
            loc = r.choice(("online", "online", "room", "external"))
            if loc == "external":
                att = tuple(sorted({*att, "c01"}))
                place: tuple = (("org", "C01"), " 본사 회의실")
            else:
                place = ("온라인 회의",) if loc == "online" else ("3층 302호",)
            subj = (("proj", pi), " 주간 회의" if weekly else " 진행 점검 회의")
            self.p.meets.append(MeetEv(self.eid("c"), pc, at_local(d, start, off), at_local(d, start + 60, off), off,
                                       subj, org, att, loc, place, f"series-{P.projects[pi].pid}" if weekly else None,
                                       0 if org == "self" else 3, (("proj", pi), " 진행 현황 공유 및 이슈 논의")))

    def _chats(self, d: date, pc: str, off: int, active: list[int]) -> None:
        r = self.r["chat"]
        rooms = self.p.rooms
        used: set[tuple[str, str, int]] = set()                 # (방, 작성자, 분) — UIA 대체 키가 겹치지 않게
        for j in range(self.k.chats):
            room = r.choice(rooms)
            author = r.choice(room.members)
            minute = r.randrange(9 * 60, 18 * 60)
            while (room.raw_id, author, minute) in used:
                minute = 9 * 60 + (minute - 9 * 60 + 1) % (9 * 60)
            used.add((room.raw_id, author, minute))
            act = r.choice(tuple(CHAT_LINE))
            pi = r.choice(active)
            topic = r.choice(self.P.projects[pi].topics)
            mention = room.chat_type != "1:1" and author != "self" and r.random() < 0.15
            body: tuple = (("proj", pi), f" {topic} {CHAT_LINE[act]}")
            if mention:
                body = ("@", ("person", "self"), " ", *body)
            files: tuple[str, ...] = ()
            if act == "report" and r.random() < 0.5:
                files = (self._doc(r, pi, "xlsx", "_v2")[0],)
            utc = at_local(d, minute, off, r.randrange(60))
            mid = str(int(utc.timestamp()) * 1000 + j % 1000)
            reply_to = None
            if room.chat_type == "channel":
                root = self.roots.get(room.raw_id)
                if root is not None and r.random() < 0.6:
                    reply_to = root
                else:
                    self.roots[room.raw_id] = mid
            self.p.chats.append(ChatEv(self.eid("h"), pc, utc, off, room, author, body, files, reply_to, mention, act,
                                       mid))

    def _files(self, d: date, pc: str, off: int, active: list[int]) -> None:
        r = self.r["file"]
        P = self.P
        for _ in range(self.k.saves):
            pi = r.choice(active)
            ext = r.choice(("xlsx", "docx", "pptx", "dwg"))
            name, _parts = self._doc(r, pi, ext, r.choice(TAILS))
            base = name.rsplit(".", 1)[0]
            rev = self.rev.get(base, 0) + 1
            self.rev[base] = rev
            last_by = "self" if r.random() < 0.9 else r.choice(P.internal_peers).pid
            folder = ("Documents", P.projects[pi].codename) if r.random() < 0.85 else ("Desktop",)
            self.p.files.append(FileEv(self.eid("f"), pc, at_local(d, r.randrange(9 * 60, 18 * 60), off,
                                                                    r.randrange(60)), off, folder, name,
                                       "create" if rev == 1 else "save", r.randrange(20_000, 9_000_000),
                                       rev * r.randint(5, 40), rev, last_by, r.random() < 0.05))

    def _commits(self, d: date, pc: str, off: int) -> None:
        r = self.r["git"]
        for _ in range(self.k.commits):
            subj = (("proj", 5), " " + r.choice(("변환 스크립트 수정", "시험 추가", "로그 정리", "설정 분리")))
            self.p.commits.append(CommitEv(self.eid("g"), pc, at_local(d, r.randrange(9 * 60, 18 * 60), off,
                                                                        r.randrange(60)), off,
                                           r.choice(("자동화도구", "데이터변환")), f"{r.getrandbits(160):040x}", subj,
                                           r.randint(1, 5), (".py",)))

    def _compute(self, d: date, pc: str, off: int) -> None:
        self.p.computes.append(ComputeEv(self.eid("u"), pc, at_local(d, 14 * 60, off), at_local(d, 16 * 60, off), off,
                                         "simsolve.exe", "unknown:simsolve.exe", 3.5))

    def _manual(self, d: date, pc: str, off: int, i: int) -> None:
        if (i // 5) % 2 == 0:
            ev = ManualEv(self.eid("w"), pc, d, 13 * 60, 15 * 60, off, "현장 지원", 2.0,
                          (("org", "C01"), " 현장 방문 시험 지원"), (("proj", 3),), self.P.projects[3].pid, "offsite",
                          "ELEC", "TEST")
        else:
            ev = ManualEv(self.eid("w"), pc, d, None, None, off, "교육", 1.5, ("사내 안전 교육 이수",), None, None,
                          "work", "ELEC", "DESIGN")
        self.p.manuals.append(ev)


def plan_period(d0: date | None = None, d1: date | None = None, *, persona: Persona | None = None, seed: int = 0,
                density: str = "light", holidays: Iterable[date] = (), multi_pc: bool = False) -> Plan:
    """기간 [d0, d1] 의 활동 계획(같은 인자 → 같은 계획). 주말·holidays 는 근무일에서 뺀다."""
    d0 = d0 or DEFAULT_D0
    d1 = d1 or DEFAULT_D1
    if d1 < d0:
        raise ValueError("d1 < d0")
    if density not in DENSITIES:
        raise ValueError(f"알 수 없는 밀도: {density}")
    P = persona or default_persona(seed)
    hol = frozenset(holidays)
    days = [d0 + timedelta(days=i) for i in range((d1 - d0).days + 1)]
    work = [d for d in days if d.weekday() < 5 and d not in hol]
    plan = Plan(P, d0, d1, seed, density, work, _rooms(seed))
    b = _Builder(plan, DENSITIES[density], multi_pc)
    for i, d in enumerate(work):
        b.day(i, d)
    return plan


def plan_month(year: int = 2026, month: int = 9, **kw) -> Plan:
    """한 달치 계획(P §19 T19 '합성 페르소나 한 달치')."""
    d0 = date(year, month, 1)
    d1 = date(year + month // 12, month % 12 + 1, 1) - timedelta(days=1)
    return plan_period(d0, d1, **kw)


def load_holidays(path: str | Path | None = None) -> frozenset[date]:
    """config\\calendar.json 의 공휴일·company_off 날짜(파일이 없으면 빈 집합). 읽기만 한다."""
    p = Path(path) if path else TREE_ROOT / "config" / "calendar.json"
    if not p.is_file():
        return frozenset()
    obj = json.loads(p.read_text(encoding="utf-8-sig"))
    out = {date.fromisoformat(h["date"]) for y in obj.get("years") or [] for h in y.get("holidays") or []}
    out.update(date.fromisoformat(s) for s in obj.get("company_off") or [])
    return frozenset(out)


def plan_3m(seed: int = 26, start: date | None = None, *, months: int = 3,
            holidays: Iterable[date] | None = None) -> Plan:
    """성능용 계획: 1명 × months 개월(30일 단위), 밀도 perf. holidays 를 안 주면 달력 파일의 공휴일을 뺀다."""
    d0 = start or DEFAULT_D0
    d1 = d0 + timedelta(days=30 * months - 1)
    return plan_period(d0, d1, seed=seed, density="perf", holidays=load_holidays() if holidays is None else holidays)


def signals_3m(seed: int = 26, start: date | None = None, *, months: int = 3,
               holidays: Iterable[date] | None = None) -> list[dict]:
    """1명 × 3개월 저장 행(약 4.3만, T-19 · W-G9 입력). 생성은 60초 안(test_fixtures 가 잰다)."""
    from .stored import stored_rows  # 순환 import 회피(stored 가 이 모듈을 쓴다)
    return stored_rows(plan_3m(seed, start, months=months, holidays=holidays))


# ── *.copilot 증인 재료(raw_* · stored 공용) ───────────────────────────────────
_WITNESS_LABEL = {"mail": "메일", "cal": "일정", "teams": "팀즈 메시지"}


def daily_witness(plan: Plan, kind: str) -> list[tuple[date, tuple]]:
    """근무일마다 (로컬 날짜, 요약 텍스트 조각) — 코파일럿 존재 증인 행(계약 §3.2 '*.copilot')의 재료."""
    if kind not in _WITNESS_LABEL:
        raise ValueError(f"증인 kind 아님: {kind}")
    evs: list = {"mail": plan.mails, "cal": plan.meets, "teams": plan.chats}[kind]
    by: dict[date, list] = {}
    for ev in evs:
        t = ev.start if kind == "cal" else ev.utc
        by.setdefault(to_local(t, ev.off).date(), []).append(ev)
    out: list[tuple[date, tuple]] = []
    for d in sorted(by):
        day = by[d]
        pis = sorted({part[1] for ev in day for part in (ev.body if kind == "teams" else ev.subject)
                      if isinstance(part, tuple) and part[0] == "proj"})
        parts: list = [f"{d.isoformat()} {_WITNESS_LABEL[kind]} {len(day)}건, 주요 과제 "]
        for i, pi in enumerate(pis[:3]):
            if i:
                parts.append("·")
            parts.append(("proj", pi))
        out.append((d, tuple(parts)))
    return out


# ── 원시 레코드에 카나리아 심기(raw_* 공용) ─────────────────────────────────────
def plantable(canaries: Iterable | None, slot: str | None = None) -> list:
    """심을 카나리아: 문장이 있고 key 묶음이 아닌 것. slot 을 주면 그 슬롯만."""
    out = [c for c in (canaries or ()) if getattr(c, "sentence", "") and getattr(c, "group", "") != "key"]
    if slot is not None:
        out = [c for c in out if c.slot == slot]
    return out


def plant_text(records: Sequence[dict], canaries: Iterable | None, field_name: str, *, sep: str = " ",
               start: int = 0) -> list[str]:
    """records 의 텍스트 필드에 카나리아 문장을 덧붙인다(제자리, 결정적 위치). 심은 cid 목록을 돌려준다."""
    cs = plantable(canaries)
    if not records or not cs:
        return []
    n = len(records)
    for i, c in enumerate(cs):
        rec = records[(start + i * 7) % n]
        cur = rec.get(field_name) or ""
        rec[field_name] = f"{cur}{sep}{c.sentence}" if cur else c.sentence
    return [c.cid for c in cs]
