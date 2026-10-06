# -*- coding: utf-8 -*-
r"""단위업무 형성 — 시간 코어 B(W §4 · 부록 A `episodes.py`, 계약 §2.9 · §3.14 tasks.json · §4.2 unit_id · §6.4).

`build_tasks(ev, env, days, cfg, cal, *, unit_key) -> (TaskList[UnitTask], list[QueueItem])`

흐름(W §4.0): (a) 대화 상태기계 → (b) 문서군 구간화(반복 문서 ISO 주·휴면 분리) → (c) 키 사슬 연결(강한 키 단독·
약한 키 합산·과제 충돌 = 연결 금지) → (d) 자체 업무(SELF)·앱 업무(APP)·고아 보고·무연결 발신 → (e) 진행 시각 →
(f) 회의 연결(S2m·E3c·L2 대상) → (g) 확인 응답(증거 키) → (h) 경계·등급·상태 → (i) 기계 시간 → (j) 거대 성분 가드.
코파일럿은 개입하지 않는다(시간·경계·등급을 덮어쓰지 못한다).

제품 입력 대응(참조 `worktime_sim.py` TaskBuilder 이식 — 이름·형은 계약대로):
- 문서군은 `Evidence` 의 문서군 키(`lm27.time.tokens.fam_key` — d16 · d16@폴더 · `B_GENERIC` · 저장소 r16)다. 다시
  정규화하지 않는다(확인 응답 `Man.ref` 도 이미 문서군 키). 문서군 토큰은 `ev.fam_tokens[f]`(로컬 전용), 범용 판정은
  `tokens.is_generic_key(f)`. 폴더를 모르는 범용 이름(`B_GENERIC`)은 서로 다른 문서의 묶음이므로 자체 업무를 만들지
  않는다(첨부로 이어진 경우만 업무 창으로 나뉜다 — 계약 §4.3 'B_GENERIC 처리').
- 회의 주최자 키는 저장하지 않는다(X-204 — `Meet.organizer` 는 'self' 또는 ''). 그래서 '의뢰자 주최·동석'
  (회의 연결 점수·S2m·E3c)은 `Meet.attendees`(counterpart_keys) 와 업무 상대들의 교집합으로 판정한다.
- unit_id(W §4.11 · 계약 §4.2) = "u_" + hex(HMAC-SHA256(k_unit, 시작 근거 키))[:10]. 시작 근거 키: S1·S1d·S1o·ACK =
  그 메시지 msg_key, SELF = '문서군 키|날짜', APP = 'app:<app_id>|날짜', REPORT_ONLY = 보고 msg_key, MANUAL =
  'manual:<문서군 키>'. `unit_key` = 목적 'unit' 하위 키(bytes — `subkey(주 키, "unit")`) · 키링 객체(지연 import
  `lm27.privacy.keys.keyed`) · 호출 가능(`fn(시작 근거 키, 종류) -> unit_id`, 시험·호환 주입).
- 업무 표지 `label` 은 키로만 만든다(`S1:<대화 키>#n` · `SELF:<문서군 키>@MM-DD` · `APP:<app_id>@MM-DD` ·
  `REPORT:<대화 키>` · `MANUAL:<참조>`) — 문서 이름·제목 원문 없음(W-G8).
- 결정성(G2): 입력은 `normalize` 가 정준 정렬했고, 모든 동률은 (점수, 시각, unit_id) 로 깬다.

표준 라이브러리만 쓴다(+ 지연 import `lm27.privacy.keys` — 키링 객체를 받았을 때만). 파일을 쓰지 않는다.
"""
from __future__ import annotations

import bisect
import hashlib
import hmac
import re
from collections import defaultdict
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date, timedelta

from lm27.time.calendar import DAY, d_of, day0
from lm27.time.intervals import U
from lm27.time.queue import QueueItem, make_item
from lm27.time.tokens import B_GENERIC, boilerplate, is_generic_key, raw_tokens, tok_sim

__all__ = [
    "APP_TASK_CLS",
    "EG",
    "KINDS",
    "SG",
    "TEAM_END",
    "TEAM_START",
    "Cycle",
    "TaskCtx",
    "TaskList",
    "UnitTask",
    "build_tasks",
    "completion",
    "grade_of",
    "make_unit_key",
    "team_bounds",
]

MIN, HOUR = 60, 3600
SG = {"S1": "A", "S1o": "A", "S1d": "B", "S2a": "B", "S2M": "B", "S2m": "C", "S2p": "C"}
EG = {"E1": "A", "E1i": "A", "E1d": "B", "E2h": "B", "E3M": "B", "E2l": "C", "E3c": "C", "NEXT_REQ": "D", "E3i": "D"}
GORD = "ABCDE"
KINDS = ("S1", "ACK", "COORD", "SELF", "APP", "REPORT_ONLY", "MANUAL")
APP_TASK_CLS = frozenset({"cad", "cae", "sim", "eda", "ide", "eng"})
EXACT = ("exact", "minute")
UNIT_RX = re.compile(r"^u_[0-9a-f]{10}$")
RELS = ("requester", "reporter", "thread", "meeting")
_BAD_COV = frozenset({"blocked", "out_of_horizon", "transport_fail", "not_attempted"})


# W §4.11 시간 코어 경계 근거 → 팀 묶음 units[].start/end(kind, precision) — X-207: grade M · end.kind E3i 포함
TEAM_START = {"S1": ("S1i", "minute"), "S1d": ("S1i", "date"), "S1o": ("S1o", "minute"), "S2a": ("S2", "exact"),
              "S2m": ("S2", "exact"), "S2p": ("S2", "none"), "S2M": ("M", "exact")}
TEAM_END = {"E1": ("E1o", "minute"), "E1d": ("E1o", "date"), "E1i": ("E1i", "minute"), "E2h": ("E2", "exact"),
            "E2l": ("E2", "exact"), "E3c": ("E3c", "exact"), "E3M": ("M", "exact"), "E3i": ("E3i", "none"),
            "NEXT_REQ": ("E3i", "none")}


def team_bounds(sb: str, eb: str | None, grade: str) -> dict | None:
    """팀 묶음 단위업무 경계(W §4.11 표 — 단일원). 미착수(Z)는 올리지 않으므로 None.

    반환 {start_kind, start_precision, end_kind(None = 진행 중), end_precision, grade, status}. 진행 중(O)의 grade 는
    시작 근거 등급(잠정), status 는 closed·estimated·open. S1·S1o·E1·E1i 의 정밀도는 'minute'(분 단위 이상 — 차수에는
    exact·minute 구분을 남기지 않는다).
    """
    if grade == "Z":
        return None
    sk, sp = TEAM_START[sb]
    if eb in (None, "OPEN"):
        return {"start_kind": sk, "start_precision": sp, "end_kind": None, "end_precision": "none",
                "grade": "M" if grade == "M" else SG[sb], "status": "open"}
    ek, ep = TEAM_END[eb]
    status = "estimated" if eb in ("E2l", "E3i", "NEXT_REQ") else "closed"
    return {"start_kind": sk, "start_precision": sp, "end_kind": ek, "end_precision": ep, "grade": grade,
            "status": status}


def grade_of(sb: str, eb: str | None) -> str:
    """경계 등급(W §4.10.1): O(진행 중) 또는 A~E. 양 끝 모두 추정이면 한 단계 강등, 양 끝 날짜만이면 C."""
    if eb in (None, "OPEN"):
        return "O"
    g = max(SG[sb], EG[eb], key=GORD.index)
    if sb in ("S2p", "S2m") and eb in ("E2l", "E3i", "NEXT_REQ"):
        g = GORD[min(4, GORD.index(g) + 1)]
    if sb == "S1d" and eb == "E1d":
        g = "C"
    return g


# ───────────────────────────── 형(W 부록 A) ─────────────────────────────
@dataclass
class Cycle:
    """차수 — 시작·종료 시각(로컬 초)과 근거 코드. interim = [(시각, 'E1p'|앞 종료 코드)]."""
    s: int | None
    sb: str
    e: int | None = None
    eb: str | None = None
    s_ref: str | None = None
    e_ref: str | None = None
    interim: list = field(default_factory=list)
    unstarted: bool = False


@dataclass
class UnitTask:
    """단위업무 인스턴스(W 부록 A `UnitTask` + 구현 확장 — X-217)."""
    id: str
    label: str
    kind: str                                   # S1 | ACK | COORD | SELF | APP | REPORT_ONLY | MANUAL
    conv: str = ""
    peer: str = ""
    peers: set = field(default_factory=set)
    tokens: set = field(default_factory=set)
    docs: dict = field(default_factory=dict)    # 문서군 키 → 연결 강도(3 첨부·확인, 2 토큰)
    convs: set = field(default_factory=set)
    cycles: list = field(default_factory=list)
    p_times: list = field(default_factory=list)
    adds: list = field(default_factory=list)    # 추가 지시 [(시각, 메시지 id, msg_key)]
    flags: list = field(default_factory=list)
    grade: str = ""
    status: str = ""
    machine_s: int = 0
    app: str = ""
    proj: str | None = None
    first_key: str = ""
    pre_from: int | None = None
    follow_of: str | None = None
    segs: list = field(default_factory=list)
    labels: dict = field(default_factory=dict)
    meet_refs: list = field(default_factory=list)   # [(Meet, 검토 회의 여부)]
    rels: dict = field(default_factory=dict)        # who_key → {requester·reporter·thread·meeting}
    machine_iv: list = field(default_factory=list)  # 연산 구간 [(a, b)] — 월별 기계 시간
    pre_request_s: int = 0

    def is_open(self) -> bool:
        return bool(self.cycles) and self.cycles[-1].e is None

    def last_end(self) -> int | None:
        es = [c.e for c in self.cycles if c.e is not None]
        return max(es) if es else None

    def rel(self, who: str, kind: str) -> None:
        if who and isinstance(who, str):
            self.rels.setdefault(who, set()).add(kind)


@dataclass
class _Seg:
    """문서군 구간(반복 문서는 ISO 주마다, 아니면 휴면 분리)."""
    fam: str
    i: int
    t0: int
    t1: int
    times: list
    links: dict = field(default_factory=dict)   # unit_id → 연결 강도
    recurring: bool = False
    shared: bool = False


@dataclass
class TaskCtx:
    """귀속(attribute)·확인 큐가 이어 쓰는 형성 문맥."""
    segs: dict
    seg_starts: dict
    finfo: dict
    msg_task: dict
    meet_task: dict
    app_task: dict
    by_id: dict
    as_of: int
    uid: Callable[[str, str], str]
    attribution: object | None = None
    builder: object | None = None                # 형성기(E2 점수 `completion` 의 문맥)

    def seg_at(self, f: str, t: int) -> _Seg | None:
        """문서군 f 에서 시각 t 를 담은(없으면 가장 가까운) 구간."""
        lst = self.segs.get(f)
        if not lst:
            return None
        i = bisect.bisect_right(self.seg_starts[f], t) - 1
        if i < 0:
            return lst[0]
        if i + 1 < len(lst) and t > lst[i].t1 and (lst[i + 1].t0 - t) < (t - lst[i].t1):
            return lst[i + 1]
        return lst[i]


class TaskList(list):
    """`build_tasks` 결과 — 업무 목록 + 형성 문맥(`.ctx`). 귀속은 이 문맥이 있어야 한다."""
    ctx: TaskCtx


# ───────────────────────────── unit_id ─────────────────────────────
def make_unit_key(key) -> Callable[[str, str], str]:
    """unit_id 생성기(W §4.11 · 계약 §4.2). key = 목적 'unit' 하위 키 bytes · 키링 객체 · 호출 가능."""
    if key is None:
        raise ValueError("unit_id 키가 없다 — 목적 'unit' 하위 키(bytes)나 키링을 넘겨야 한다(W §4.11)")
    if isinstance(key, (bytes, bytearray)):
        if len(key) < 16:
            raise ValueError("unit_id 키가 너무 짧다(16바이트 이상)")
        k = bytes(key)

        def by_bytes(start: str, kind: str) -> str:
            return "u_" + hmac.new(k, str(start).encode("utf-8"), hashlib.sha256).hexdigest()[:10]
        return by_bytes
    if callable(key):
        def by_fn(start: str, kind: str) -> str:
            v = str(key(start, kind))
            return v if v.startswith("u_") else "u_" + v
        return by_fn
    if isinstance(key, str):
        raise TypeError("unit_id 키에 문자열은 쓰지 않는다(person_key 같은 공개 ID 는 비밀 키가 아니다)")

    def by_keyring(start: str, kind: str) -> str:
        from lm27.privacy.keys import keyed           # 지연 import — 키링 객체를 받았을 때만(계약 §4.2)
        return "u_" + keyed(key, "unit", str(start), 10)
    return by_keyring


# ───────────────────────────── 공용 ─────────────────────────────
def _fmt(t: int) -> str:
    d = d_of(t)
    m = (t - day0(d)) // MIN
    return f"{d.month:02d}-{d.day:02d} {m // 60:02d}:{m % 60:02d}"


def _mmdd(t: int) -> str:
    d = d_of(t)
    return f"{d.month:02d}-{d.day:02d}"


def _hm(s: str) -> tuple[int, int]:
    a, b = str(s).strip().split("-")
    h0, m0 = a.split(":")
    h1, m1 = b.split(":")
    return int(h0) * HOUR + int(m0) * MIN, int(h1) * HOUR + int(m1) * MIN


def _lower_set(xs) -> frozenset[str]:
    return frozenset(str(x).lower() for x in xs if str(x).strip())


def build_tasks(ev, env, days: Mapping, cfg, cal, *, unit_key=None) -> tuple[TaskList, list[QueueItem]]:
    """W §4 단위업무 형성. 반환 = (업무 목록 — `.ctx` 형성 문맥 포함, 형성 중 생긴 확인 질문)."""
    b = _Builder(ev, env, days, cfg, cal, make_unit_key(unit_key))
    tasks = b.build()
    out = TaskList(tasks)
    out.ctx = b.ctx
    return out, b.queue


def completion(task: UnitTask, cycle: Cycle, nxt: int, ctx) -> tuple[int, str, float] | None:
    """E2 작성·산출 완료 후보(W §4.9.2 — E2 점수 유일원). ctx = 형성기(`_Builder`).

    점수 = 조용함 + 내보내기 + 최종 이름 + 해석 결과 + 발신 첨부(`episode.e2Weights`). 조용함 = 마지막 편집 →
    min(다음 차수 시작, 분석 시각) 근무일 ≥ quietWd(자동 저장 문서는 autosaveQuietWd). 후보 뒤에도 그 업무 작업이
    `e2TailMin` 넘게 이어지면 종료가 아니다. 반환 (마지막 시각, E2h|E2l, 점수) 또는 None.
    ctx = `TaskCtx`(`build_tasks` 결과의 `.ctx`) 또는 형성기.
    """
    b = getattr(ctx, "builder", None) or ctx
    return b.completion(task, cycle, nxt)


class _Builder:
    def __init__(self, ev, env, days: Mapping, cfg, cal, uid):
        self.ev, self.env, self.days, self.cfg, self.cal, self.uid = ev, env, days, cfg, cal, uid
        self.as_of = ev.as_of
        self.tasks: list[UnitTask] = []
        self.queue: list[QueueItem] = []
        self.by_conv: dict[str, list[UnitTask]] = defaultdict(list)
        self.msg_task: dict[str, str] = {}
        self.meet_task: dict[str, str] = {}
        self.app_task: dict[str, list] = {}
        self.orphan_reports = []
        self.unlinked_sends = []
        self.common = frozenset(ev.common_tokens)
        self.fam_tokens = ev.fam_tokens
        g = cfg.__getitem__
        self.ml = int(g("episode.tokens.minSubLen"))
        self.boiler = boilerplate(cfg)
        self.rmax = int(g("episode.requestMaxParticipants"))
        self.rework_wd = int(g("episode.reworkWindowWd"))
        self.reopen_wd = int(g("episode.reopenQuietWd"))
        self.supp_wd = int(g("episode.supplementWd"))
        self.pre_tol = int(g("episode.preStartTolMin")) * MIN
        self.pre_work = int(g("episode.preWorkH")) * HOUR
        self.link_wd = int(g("episode.linkWindowWd"))
        self.theta = float(g("episode.link.theta"))
        self.w_tok = float(g("episode.link.wToken"))
        self.w_time = float(g("episode.link.wTime"))
        self.w_proj = float(g("episode.link.wProject"))
        self.report_sim = float(g("episode.link.reportSim"))
        self.multi_sim = float(g("episode.link.multiCloseSim"))
        self.send_sim = float(g("episode.link.sendTokenSim"))
        self.final_words = _lower_set(g("episode.finalWords"))
        self.review_words = _lower_set(g("episode.reviewWords"))
        self.interim_words = _lower_set(g("episode.interimWords"))
        self.rec_weeks = int(g("episode.recurringMinWeeks"))
        self.rec_days = int(g("episode.recurringMaxDaysPerWeek"))
        self.merge_sim = float(g("episode.selfMergeSim"))
        self.merge_days = int(g("episode.selfMergeDays"))
        self.split_wd = int(g("episode.splitWd"))
        self.dormant_wd = int(g("episode.dormantWd"))
        self.quiet_wd = int(g("episode.quietWd"))
        self.as_quiet_wd = int(g("episode.autosaveQuietWd"))
        w = g("episode.e2Weights")
        self.e2w = {k: float(w.get(k, 0.0)) for k in ("quiet", "export", "final", "result", "attached")}
        self.e2_high = float(g("episode.e2High"))
        self.e2_low = float(g("episode.e2Low"))
        self.e2_tail = int(g("episode.e2TailMin")) * MIN
        self.s2_pad = int(g("episode.s2PrePadMin")) * MIN
        self.e3_pad = int(g("episode.e3PostPadMin")) * MIN
        self.meet_back = int(g("episode.s2MeetLookbackH")) * HOUR
        self.e3c_ahead = int(g("episode.e3cLookaheadH")) * HOUR
        self.meet_min = float(g("episode.meetLinkMin"))
        self.shared_min = int(g("episode.sharedDocMinTasks"))
        self.giant_n = int(g("episode.giantNodes"))
        self.giant_days = int(g("episode.giantDays"))
        self.need_cov = bool(g("episode.requireCommsCoverageForE3"))
        self.unstarted_wd = int(g("episode.unstartedWd"))
        self.post_pad = int(g("time.attrib.postPadMin")) * MIN
        self.pre_mail = int(g("time.envelope.preWindowMin.mail")) * MIN
        self.pre_teams = int(g("time.envelope.preWindowMin.teams")) * MIN
        self.std = _hm(g("time.window.std"))
        self._wd_cache: dict[tuple[date, date], int] = {}
        self._ft_cache: dict[str, frozenset[str]] = {}

    # --- 공용 ---
    def wd(self, t1: int, t2: int) -> int:
        """(d_of(t1), d_of(t2)] 근무일 수. 달력에 없는 해는 요일 규칙(분석 거부는 build_days 가 이미 했다)."""
        d1, d2 = d_of(t1), d_of(t2)
        k = (d1, d2)
        v = self._wd_cache.get(k)
        if v is None:
            try:
                v = int(self.cal.wd_between(d1, d2))
            except ValueError:
                v, d = 0, d1
                while d < d2:
                    d += timedelta(days=1)
                    v += 0 if self._off(d) else 1
            self._wd_cache[k] = v
        return v

    def _off(self, d: date) -> bool:
        try:
            return bool(self.cal.is_holiday(d))
        except ValueError:
            return d.weekday() not in getattr(self.cal, "weekdays", frozenset({0, 1, 2, 3, 4}))

    def toks(self, x) -> set[str]:
        return set(x) - self.common

    def ftoks(self, f: str) -> frozenset[str]:
        v = self._ft_cache.get(f)
        if v is None:
            v = frozenset(self.fam_tokens.get(f, ())) - self.common
            self._ft_cache[f] = v
        return v

    @staticmethod
    def is_generic(f: str) -> bool:
        return is_generic_key(f)

    def new(self, kind: str, label: str, key: str, **kw) -> UnitTask:
        t = UnitTask(id=self.uid(key, kind), label=label, kind=kind, first_key=key, **kw)
        if not UNIT_RX.match(t.id):
            raise ValueError(f"unit_id 형식 오류 {t.id!r}(^u_[0-9a-f]{{10}}$)")
        self.tasks.append(t)
        return t

    def doc_toks(self, tk: UnitTask) -> set[str]:
        out: set[str] = set()
        for f in tk.docs:
            out |= self.ftoks(f)
        return out

    def topic(self, mtok, mfam, tk: UnitTask) -> float:
        """메시지 ↔ 업무 화제 점수: 첨부 문서군 일치 3, 토큰(부분 문자열) 2.5 × 유사도(W §4.2)."""
        sc = 3.0 * len(set(mfam) & set(tk.docs))
        ft: set[str] = set()
        for f in mfam:
            ft |= self.ftoks(f)
        sc += 2.5 * tok_sim(self.toks(mtok) | ft, self.toks(tk.tokens) | self.doc_toks(tk), self.ml)
        return sc

    def day_start(self, t: int) -> int:
        return day0(d_of(t)) + self.std[0]

    def day_end(self, t: int) -> int:
        return day0(d_of(t)) + self.std[1]

    def _q(self, code: str, target: str, core: str, **kw) -> None:
        self.queue.append(make_item(code, target, core, **kw))

    # --- (a) 대화 상태기계 ---
    def conversations(self) -> None:
        for m in self.ev.msgs:
            if m.prec == "summary":
                self._q("Q07", d_of(m.t).isoformat(), m.key, evidence_keys=(m.key,), day=d_of(m.t),
                        note=f"{m.dir}/{m.act}: 시각·경계 근거 아님")
                continue
            mt, fa = set(m.tokens), set(m.atts)
            conv_tasks = self.by_conv[m.conv]
            open_ = [t for t in conv_tasks if t.is_open()]
            is_rep = m.act == "report" or (m.act == "info" and bool(m.atts))
            exact = m.prec in EXACT
            if m.dir == "in" and m.act == "request" and m.direct and m.n_part <= self.rmax:
                sb = "S1" if exact else "S1d"
                s = m.t if exact else self.day_start(m.t)
                if open_ and self._attach_additional(m, mt, fa, open_):
                    continue
                if self._rework(m, mt, fa, conv_tasks, s, sb):
                    continue
                tk = self.new("S1", f"S1:{m.conv}#{len(conv_tasks) + 1}", m.key, conv=m.conv, peer=m.peer,
                              peers={m.peer}, tokens=set(mt), convs={m.conv}, proj=m.proj)
                tk.rel(m.peer, "requester")
                for f in fa:
                    tk.docs[f] = 3
                tk.cycles.append(Cycle(s, sb, s_ref=m.id))
                self.by_conv[m.conv].append(tk)
                self.msg_task[m.id] = tk.id
                continue
            if m.dir == "out" and m.act == "request" and m.n_part <= self.rmax:          # S1o 조율형(PM/PL)
                if open_ and self._attach_additional(m, mt, fa, [t for t in open_ if t.kind == "COORD"]):
                    continue
                tk = self.new("COORD", f"COORD:{m.conv}#{len(conv_tasks) + 1}", m.key, conv=m.conv, peer=m.peer,
                              peers={m.peer}, tokens=set(mt), convs={m.conv}, proj=m.proj)
                tk.rel(m.peer, "thread")
                for f in fa:
                    tk.docs[f] = 3
                tk.cycles.append(Cycle(m.t if exact else self.day_start(m.t), "S1o" if exact else "S1d", s_ref=m.id))
                tk.p_times.append(m.t)
                self.by_conv[m.conv].append(tk)
                self.msg_task[m.id] = tk.id
                continue
            if m.dir == "out" and m.act == "ack":
                if open_:
                    tk = max(open_, key=lambda t: (self.topic(mt, fa, t), t.cycles[-1].s, t.id))
                    tk.flags.append(f"수락 {_fmt(m.t)}")
                    tk.p_times.append(m.t)
                    tk.rel(m.peer, "thread")
                    self.msg_task[m.id] = tk.id
                    continue
                if not exact:
                    continue
                tk = self.new("ACK", f"ACK:{m.conv}#{len(conv_tasks) + 1}", m.key, conv=m.conv, peer=m.peer,
                              peers={m.peer}, tokens=set(mt), convs={m.conv}, proj=m.proj)
                tk.rel(m.peer, "requester")
                tk.cycles.append(Cycle(m.t, "S2a", s_ref=m.id))
                tk.p_times.append(m.t)
                self.by_conv[m.conv].append(tk)
                self.msg_task[m.id] = tk.id
                continue
            if m.dir == "out" and is_rep:
                self._report_out(m, mt, fa, open_, conv_tasks)
                continue
            if m.dir == "in" and is_rep:
                coord = [t for t in open_ if t.kind == "COORD"]
                if coord:
                    tk = max(coord, key=lambda t: (self.topic(mt, fa, t), t.cycles[-1].s, t.id))
                    c = tk.cycles[-1]
                    c.e, c.eb, c.e_ref = (m.t if exact else self.day_end(m.t)), ("E1i" if exact else "E1d"), m.id
                    for f in fa:
                        tk.docs[f] = 3
                    tk.tokens |= mt
                    tk.rel(m.peer, "reporter")
                continue
            if m.dir == "out" and exact:                                              # 진행(P): 비보고 발신
                tk = None
                if open_:
                    tk = max(open_, key=lambda t: (self.topic(mt, fa, t), t.cycles[-1].s, t.id))
                elif conv_tasks:
                    tk = max(conv_tasks, key=lambda t: (t.cycles[-1].s, t.id))
                    if self.wd(tk.last_end() or tk.cycles[-1].s, m.t) > self.supp_wd:
                        tk = None
                if tk is not None:
                    tk.p_times.append(m.t)
                    tk.rel(m.peer, "thread")
                    self.msg_task[m.id] = tk.id
                else:
                    self.unlinked_sends.append(m)

    def _attach_additional(self, m, mt, fa, open_) -> bool:
        if not open_:
            return False
        best = max(open_, key=lambda t: (self.topic(mt, fa, t), t.cycles[-1].s, t.id))
        if self.topic(mt, fa, best) > 0 or not (self.toks(mt) or fa):
            best.adds.append((m.t, m.id, m.key))
            best.tokens |= mt
            for f in fa:
                best.docs[f] = 3
            best.rel(m.peer, "requester" if m.dir == "in" else "thread")
            self.msg_task[m.id] = best.id
            return True
        return False                       # 같은 대화방·다른 화제 → 새 업무(병행)

    def _rework(self, m, mt, fa, conv_tasks, s, sb) -> bool:
        closed = [t for t in conv_tasks if not t.is_open() and t.kind in ("S1", "ACK") and t.last_end() is not None
                  and self.wd(t.last_end(), s) <= self.rework_wd]
        if not closed:
            return False
        best = max(closed, key=lambda t: (self.topic(mt, fa, t), t.last_end(), t.id))
        if self.topic(mt, fa, best) > 0 or not (self.toks(mt) or fa):
            best.cycles.append(Cycle(s, sb, s_ref=m.id))
            best.tokens |= mt
            for f in fa:
                best.docs[f] = 3
            best.rel(m.peer, "requester")
            self.msg_task[m.id] = best.id
            return True
        return False

    def _close(self, tk: UnitTask, m, fa, mt, flag: str | None = None) -> None:
        exact = m.prec in EXACT
        c = tk.cycles[-1]
        c.e, c.eb, c.e_ref = (m.t if exact else self.day_end(m.t)), ("E1" if exact else "E1d"), m.id
        for f in fa:
            tk.docs[f] = 3
        tk.tokens |= mt
        tk.convs.add(m.conv)
        tk.rel(m.peer, "reporter")
        if flag:
            tk.flags.append(flag)
        self.msg_task.setdefault(m.id, tk.id)

    def _report_out(self, m, mt, fa, open_, conv_tasks) -> None:
        interim = bool(self.toks(mt) & self.interim_words)
        primary = None
        conv_ids = {t.id for t in conv_tasks}
        if open_:
            primary = max(open_, key=lambda t: (self.topic(mt, fa, t), t.cycles[-1].s, t.id))
        else:
            # 보완 보고: 같은 대화의 최근(≤1 근무일) 닫힌 업무, 또는 첨부 문서군이 같은 최근 업무 → 끝 연장(앞 끝은 중간 보고)
            rec = [t for t in self.tasks if t.kind in ("S1", "ACK", "COORD", "SELF") and not t.is_open()
                   and t.last_end() is not None and t.last_end() <= m.t and
                   ((t.id in conv_ids and self.wd(t.last_end(), m.t) <= 1) or
                    (fa & set(t.docs) and self.wd(t.last_end(), m.t) <= self.supp_wd))]
            if rec:
                tk = max(rec, key=lambda t: (self.topic(mt, fa, t), t.last_end(), t.id))
                c = tk.cycles[-1]
                c.interim.append((c.e, c.eb))
                exact = m.prec in EXACT
                c.e, c.eb, c.e_ref = (m.t if exact else self.day_end(m.t)), ("E1" if exact else "E1d"), m.id
                for f in fa:
                    tk.docs[f] = 3
                tk.flags.append("보완보고(끝 연장)")
                tk.rel(m.peer, "reporter")
                self.msg_task[m.id] = tk.id
                return
            cands = [t for t in self.tasks if t.kind in ("S1", "ACK") and t.is_open() and t.peer == m.peer and
                     (fa & set(t.docs) or self.topic(mt, fa, t) >= 2.5 * self.report_sim)]
            if cands:
                primary = max(cands, key=lambda t: (self.topic(mt, fa, t), t.cycles[-1].s, t.id))
        if primary is None:
            self.orphan_reports.append(m)
            return
        if interim:
            primary.cycles[-1].interim.append((m.t, "E1p"))
            for f in fa:
                primary.docs[f] = 3
            primary.p_times.append(m.t)
            primary.rel(m.peer, "reporter")
            self.msg_task[m.id] = primary.id
            return
        self._close(primary, m, fa, mt)
        self.msg_task[m.id] = primary.id
        # 다대다: 같은 의뢰자의 다른 열린 업무 중 첨부 문서군이 그 업무의 것(일치 또는 토큰 유사 ≥ multiCloseSim)이면 함께 닫는다
        for tk in list(self.tasks):
            if tk is primary or not tk.is_open() or tk.kind not in ("S1", "ACK") or tk.peer != m.peer:
                continue
            hit = [f for f in sorted(fa) if f in tk.docs or
                   tok_sim(self.ftoks(f), self.toks(tk.tokens), self.ml) >= self.multi_sim]
            if hit:
                self._close(tk, m, set(hit), set(), flag="다대다 종료")
                for f in hit:                   # 그 첨부는 이 업무의 산출 — 주 업무에서 빼서 공용 귀속을 피한다
                    if primary.docs.get(f) == 3 and \
                            tok_sim(self.ftoks(f), self.toks(primary.tokens), self.ml) < self.multi_sim:
                        del primary.docs[f]

    # --- (b) 문서군 구간화 ---
    def families(self) -> None:
        info: dict[str, dict] = defaultdict(lambda: {"times": [], "saves": [], "exports": [], "results": [], "fg": [],
                                                     "raw": set(), "proj": set(), "autosave": False,
                                                     "folders": set(), "finals": False, "recurring": False})
        for e in self.ev.docs:
            if e.other or not e.fam:
                continue
            x = info[e.fam]
            x["raw"].add(e.raw)
            x["folders"].add(e.folder)
            if e.proj:
                x["proj"].add(e.proj)
            if e.kind in ("save", "create") and not e.burst:
                if e.autosave:
                    x["autosave"] = True
                else:
                    x["saves"].append(e.t)
                x["times"].append(e.t)
            elif e.kind == "export":
                x["exports"].append(e.t)
                x["times"].append(e.t)
            elif e.kind == "result":
                x["results"].append(e.t)
        for s in self.ev.samples:
            if s.state == "active" and s.fam and s.priv not in ("private", "social"):
                x = info[s.fam]
                x["fg"].append((s.a, s.b))
                x["times"] += [s.a, s.b - 1]
        for c in self.ev.comps:
            if c.fam:
                x = info[c.fam]
                x["times"].append(c.a)
                if c.b <= self.as_of:
                    x["results"].append(c.b)
        for c in self.ev.commits:
            if c.fam:
                x = info[c.fam]
                x["times"].append(c.t)
                x["saves"].append(c.t)
        for x in info.values():
            x["times"] = sorted(set(x["times"]))
            x["finals"] = any(any(w in str(r).lower() for w in self.final_words) for r in x["raw"])
        segs: dict[str, list[_Seg]] = {}
        for f in sorted(info):
            x = info[f]
            ts = x["times"]
            if not ts:
                continue
            weeks: dict[tuple, set] = defaultdict(set)
            for t in ts:
                dd = d_of(t)
                weeks[dd.isocalendar()[:2]].add(dd)
            per_week = sorted(len(v) for v in weeks.values())
            med = per_week[len(per_week) // 2]
            # 반복 문서: ISO 주 ≥ recurringMinWeeks 이고 주당 활동일 중앙값 ≤ recurringMaxDaysPerWeek(드문드문 매주)
            recurring = len(weeks) >= self.rec_weeks and med <= self.rec_days
            out, cur = [], [ts[0]]
            for t in ts[1:]:
                brk = (d_of(t).isocalendar()[:2] != d_of(cur[-1]).isocalendar()[:2]) if recurring else \
                    (self.wd(cur[-1], t) > self.split_wd)
                if brk:
                    out.append(cur)
                    cur = []
                cur.append(t)
            out.append(cur)
            segs[f] = [_Seg(f, i, sg[0], sg[-1], sg, recurring=recurring) for i, sg in enumerate(out)]
            x["recurring"] = recurring
        self.finfo, self.segs = dict(info), segs
        self.seg_starts = {f: [s.t0 for s in v] for f, v in segs.items()}

    def seg_at(self, f: str, t: int) -> _Seg | None:
        lst = self.segs.get(f)
        if not lst:
            return None
        i = bisect.bisect_right(self.seg_starts[f], t) - 1
        if i < 0:
            return lst[0]
        if i + 1 < len(lst) and t > lst[i].t1 and (lst[i + 1].t0 - t) < (t - lst[i].t1):
            return lst[i + 1]
        return lst[i]

    # --- (c) 키 사슬 연결 ---
    def _rework_end(self, e_last: int) -> int:
        """마지막 끝 날짜 + reworkWindowWd 근무일 그날 끝(로컬 초)."""
        d = d_of(e_last)
        k = 0
        while k < self.rework_wd:
            d += timedelta(days=1)
            if not self._off(d):
                k += 1
        return day0(d) + DAY

    def link_docs(self) -> None:
        cannot = {(m.key, m.ref) for m in self.ev.manual if m.kind == "cannot_link" and m.ref}
        must: dict[str, set[str]] = defaultdict(set)
        for m in self.ev.manual:
            if m.kind == "must_link" and m.ref:
                must[m.key].add(m.ref)
        key_task = {tk.first_key: tk for tk in self.tasks}
        for k in sorted(must):
            tk = key_task.get(k)
            if tk:
                for f in sorted(must[k]):
                    tk.docs[f] = 3
        for tk in [t for t in self.tasks if t.kind in ("S1", "ACK", "COORD")]:
            s0 = tk.cycles[0].s
            e_last = tk.last_end() if not tk.is_open() else self.as_of
            lo = s0 - self.pre_work
            hi = max(e_last, s0)
            if not tk.is_open():
                hi = self._rework_end(e_last)
            ttoks = self.toks(tk.tokens)
            for f, lst in self.segs.items():
                if (tk.first_key, f) in cannot:
                    continue
                proj = self.finfo[f]["proj"]
                if tk.proj and proj and tk.proj not in proj:
                    continue                                   # 과제 레지스트리 충돌 = 연결 금지
                strength = 0
                if tk.docs.get(f) == 3:
                    strength = 3
                elif not self.is_generic(f) and ttoks:
                    sim = tok_sim(self.ftoks(f), ttoks, self.ml)
                    if sim > 0:
                        for sg in lst:
                            if sg.t1 < lo or sg.t0 > hi:
                                continue
                            in_time = (s0 - self.pre_work <= sg.t0 and self.wd(s0, sg.t0) <= self.link_wd)
                            score = self.w_tok * sim + self.w_time * in_time + \
                                self.w_proj * bool(tk.proj and tk.proj in proj)
                            if score >= self.theta:
                                strength = 2
                                break
                if not strength:
                    continue
                if strength == 2:
                    tk.docs.setdefault(f, 2)
                for sg in lst:
                    if sg.t1 < lo or sg.t0 > hi:
                        continue
                    if sg.recurring:
                        wk = {d_of(c.s).isocalendar()[:2] for c in tk.cycles} | \
                             {d_of(c.e).isocalendar()[:2] for c in tk.cycles if c.e is not None}
                        if d_of(sg.t0).isocalendar()[:2] not in wk:
                            continue
                    sg.links[tk.id] = max(sg.links.get(tk.id, 0), strength)
        # 공용 문서: 레지스트리 표식 또는 같은 구간에 ≥ sharedDocMinTasks 업무 → 귀속 시 B_GENERIC
        for f in sorted(self.segs):
            for sg in self.segs[f]:
                if f in self.ev.shared_docs or len(sg.links) >= self.shared_min:
                    sg.shared = True
                    self._q("Q18", f, str(sg.i), evidence_keys=(f,), day=d_of(sg.t0),
                            note=f"연결 업무 {len(sg.links)}개 — 귀속은 근무 중 미분류")

    # --- (d) 자체 업무·앱 업무·고아 보고·무연결 발신 ---
    def self_tasks(self) -> None:
        selfs: list[UnitTask] = []
        # 병합 후보 색인(결과는 예전 '모든 자체 업무 훑기'와 같다 — W2 검토 C07, 9개월에서 시간 코어의 절반):
        # 자체 업무의 가장 이른 진행 시각 = 만든 구간의 t0(구간 times 는 오름차순·t0 = 첫 값, 뒤에 붙는 구간은 시각순으로
        # 더 늦다)이라 만든 순서로 단조 증가 → |구간 t0 − 그 값| ≤ selfMergeDays 인 업무는 이분 탐색한 꼬리뿐이다.
        # 범용 문서군으로 만든 업무(docs 에 범용 키)는 병합 후보가 아니다(병합은 범용이 아닌 문서군만 붙인다). 토큰은 만든 뒤
        # 이 고리에서 바뀌지 않는다. 조건 순서만 바꿨다(시각 → 토큰 유사도 — 둘 다 부작용 없는 판정이라 첫 일치가 같다).
        s_min: list[int] = []
        s_gen: list[bool] = []
        s_tok: list[set[str]] = []
        win = self.merge_days * DAY
        last_of: dict[str, str] = {}
        order = sorted((sg.t0, f, sg.i) for f in self.segs for sg in self.segs[f])
        for _t0, f, i in order:                    # 시각순 — 자체 업무 ID 는 '가장 이른 문서군 구간'이 정한다
            sg = self.segs[f][i]
            if sg.links or f == B_GENERIC:
                continue
            merged = None
            if not self.is_generic(f):
                ft = self.ftoks(f)
                for j in range(bisect.bisect_left(s_min, sg.t0 - win), len(selfs)):
                    if s_gen[j]:
                        continue
                    if tok_sim(ft, s_tok[j], self.ml) >= self.merge_sim:
                        merged = selfs[j]
                        break
            if merged is None:
                key = f"{f}|{d_of(sg.t0).isoformat()}"
                merged = self.new("SELF", f"SELF:{f}@{_mmdd(sg.t0)}", key, tokens=set(self.ftoks(f)),
                                  follow_of=last_of.get(f))
                merged.cycles.append(Cycle(None, "S2p"))
                selfs.append(merged)
                s_min.append(min(sg.times))
                s_gen.append(self.is_generic(f))
                s_tok.append(self.toks(merged.tokens))
            merged.docs[f] = 3
            merged.p_times += sg.times
            sg.links[merged.id] = 3
            merged.segs.append((f, sg.i))
            last_of[f] = merged.id
        # 앱 단위 업무: 문서 키 없는 공학 앱 능동 사용
        app_ev: dict[str, list] = defaultdict(list)
        for s in self.ev.samples:
            if s.state == "active" and not s.fam and s.cls in APP_TASK_CLS and s.priv not in ("private", "social"):
                app_ev[s.app].append((s.a, s.b))
        for app, ivs in sorted(app_ev.items()):
            ivs = U(ivs)
            groups, cur = [], [ivs[0]]
            for iv in ivs[1:]:
                if self.wd(cur[-1][1], iv[0]) > self.split_wd:
                    groups.append(cur)
                    cur = []
                cur.append(iv)
            groups.append(cur)
            for g in groups:
                tk = self.new("APP", f"APP:{app}@{_mmdd(g[0][0])}", f"app:{app}|{d_of(g[0][0]).isoformat()}",
                              tokens=raw_tokens([app], self.boiler), app=app)
                tk.p_times = [a for a, _ in g] + [b - 1 for _, b in g]
                tk.cycles.append(Cycle(None, "S2p"))
                self.app_task.setdefault(app, []).append((g[0][0], g[-1][1], tk.id))
        # 고아 보고: 첨부 문서군이 자체 업무의 것이면 그 업무를 E1 로 닫고(S2p×E1), 아니면 단발 보고
        for m in self.orphan_reports:
            fa = set(m.atts)
            exact = m.prec in EXACT
            cands = [t for t in self.tasks if t.kind == "SELF" and fa & set(t.docs) and t.p_times and
                     min(t.p_times) <= m.t and t.cycles[-1].e is None]
            if cands:
                tk = max(cands, key=lambda t: (max(x for x in t.p_times if x <= m.t), t.id))
                c = tk.cycles[-1]
                c.e, c.eb, c.e_ref = (m.t if exact else self.day_end(m.t)), ("E1" if exact else "E1d"), m.id
                tk.peer = m.peer
                tk.peers.add(m.peer)
                tk.convs.add(m.conv)
                tk.tokens |= set(m.tokens)
                tk.rel(m.peer, "reporter")
                self.msg_task[m.id] = tk.id
            else:
                pre = self.pre_mail if m.ch == "mail" else self.pre_teams
                tk = self.new("REPORT_ONLY", f"REPORT:{m.conv}", m.key, conv=m.conv, peer=m.peer, peers={m.peer},
                              tokens=set(m.tokens), convs={m.conv})
                tk.rel(m.peer, "reporter")
                for f in fa:
                    tk.docs[f] = 3
                c = Cycle(m.t - pre, "S2p")
                c.e, c.eb, c.e_ref = (m.t if exact else self.day_end(m.t)), ("E1" if exact else "E1d"), m.id
                tk.cycles.append(c)
                tk.p_times = [m.t]
                tk.flags.append("단발보고(진행 증거 없음)")
                self.msg_task[m.id] = tk.id
                self.by_conv[m.conv].append(tk)
        # 업무 대화 밖 비보고 발신: 토큰이 어떤 업무(토큰 ∪ 문서군 토큰)와 유사도 ≥ sendTokenSim → 그 업무 진행·L4 귀속.
        # 업무 토큰 집합은 이 고리 안에서 바뀌지 않으므로 한 번만 만든다(빈 집합은 유사도 0 — 고를 수 없다). 고르는 규칙
        # (최댓값 · 동점은 작은 id)은 훑는 순서와 무관하다(W2 검토 C07).
        send_ts = [(tk, tt) for tk in self.tasks if tk.kind not in ("APP", "REPORT_ONLY")
                   for tt in (self.toks(tk.tokens) | self.doc_toks(tk),) if tt] if self.unlinked_sends else []
        for m in self.unlinked_sends:
            best, bs = None, 0.0
            mt = self.toks(m.tokens)
            for tk, tt in (send_ts if mt else ()):
                sc = tok_sim(mt, tt, self.ml)
                if sc > bs or (sc == bs and best is not None and tk.id < best.id):
                    best, bs = tk, sc
            if best is not None and bs >= self.send_sim:
                best.p_times.append(m.t)
                best.rel(m.peer, "thread")
                self.msg_task[m.id] = best.id

    # --- (e) 진행 시각 ---
    def collect_progress(self) -> None:
        """한 구간이 여러 업무에 이어지면(범용·공용 문서) 시각마다 예비 창 [시작 − 30분, (끝 또는 분석 시각) +
        postPad]이 열린 업무에만 준다(없으면 가장 가까운 앞 업무)."""
        byid = {t.id: t for t in self.tasks}
        prew = {}
        for t in self.tasks:
            if t.cycles and t.cycles[0].s is not None:
                e = t.last_end() if not t.is_open() else self.as_of
                prew[t.id] = (t.cycles[0].s - self.s2_pad, (e or self.as_of) + self.post_pad)
        for f in sorted(self.segs):
            for sg in self.segs[f]:
                ids = [k for k in sg.links if byid[k].kind in ("S1", "ACK", "COORD", "REPORT_ONLY")]
                if not ids:
                    continue
                if len(sg.links) == 1:
                    byid[ids[0]].p_times += sg.times
                    continue
                for t in sg.times:
                    inw = [k for k in ids if k in prew and prew[k][0] <= t <= prew[k][1]]
                    if not inw:
                        bef = [k for k in ids if k in prew and prew[k][0] <= t]
                        inw = [max(bef, key=lambda k: (prew[k][0], k))] if bef else []
                    for k in inw:
                        byid[k].p_times.append(t)
        for tk in self.tasks:
            tk.p_times = sorted(set(tk.p_times))

    # --- (f) 회의 연결 ---
    @staticmethod
    def requester_in(mt, tk: UnitTask) -> bool:
        """'의뢰자 주최·동석' — 주최자 키가 없으므로(X-204) 참석자(counterpart_keys) ∩ 업무 상대들로 판정한다."""
        return mt.organizer in tk.peers or any(a in tk.peers for a in mt.attendees)

    def meetings(self) -> None:
        # 회의마다 모든 업무를 훑던 것을(9개월 회의 1천 × 업무 8천) 업무별 창 [시작 − 회의 되돌아보기, 끝(열림이면 분석
        # 시각) + E3c 앞보기] 을 한 번만 계산해 시작순 이분 탐색으로 줄인다(W2 검토 C07). 이 고리는 업무의 차수·진행 시각·
        # 토큰·문서군·상대(peers)를 바꾸지 않으므로(flags·meet_refs·rels 만) 창·토큰 집합은 고리 동안 그대로다. 고르는
        # 규칙(최댓값 · 동점은 작은 id)은 훑는 순서와 무관하다.
        win = []
        for tk in self.tasks:
            if tk.kind not in ("S1", "ACK", "COORD", "SELF", "REPORT_ONLY"):
                continue
            s0 = tk.cycles[0].s if tk.cycles[0].s is not None else (tk.p_times[0] if tk.p_times else None)
            if s0 is None:
                continue
            e = tk.last_end() if not tk.is_open() else self.as_of
            win.append((s0 - self.meet_back, (e or self.as_of) + self.e3c_ahead, tk))
        win.sort(key=lambda x: x[0])
        los = [x[0] for x in win]
        tt_of: dict[str, set[str]] = {}
        for mt in self.env.counted_meetings:
            best, bs = None, 0.0
            mtoks = self.toks(mt.tokens)
            for k in range(bisect.bisect_right(los, mt.a)):
                _lo, hi, tk = win[k]
                if mt.a > hi:
                    continue
                tt = tt_of.get(tk.id)
                if tt is None:
                    tt = tt_of[tk.id] = self.toks(tk.tokens) | self.doc_toks(tk)
                sc = 2.0 * bool(self.requester_in(mt, tk)) + 2.5 * tok_sim(mtoks, tt, self.ml)
                if sc > bs or (sc == bs and best is not None and tk.id < best.id):
                    best, bs = tk, sc
            if best is not None and bs >= self.meet_min:
                self.meet_task[mt.id] = best.id
                best.flags.append(f"회의연결 {mt.id}")
                rv = bool(mtoks & self.review_words) or \
                    tok_sim(mtoks, self.toks(best.tokens) | self.doc_toks(best), self.ml) > 0
                best.meet_refs.append((mt, rv))
                for a in mt.attendees:
                    best.rel(a, "meeting")

    # --- (g) 확인 응답(증거 키로 저장된 제약) ---
    def manual_answers(self) -> None:
        for m in self.ev.manual:
            if m.kind not in ("instr", "report"):
                continue
            f = m.ref or ""
            mt = self.toks(m.tokens)
            cands = [t for t in self.tasks if t.kind != "APP" and
                     ((f and f in t.docs) or (m.key and m.key == t.first_key) or
                      (mt and tok_sim(mt, self.toks(t.tokens), self.ml) >= 0.5))]
            if not cands or m.a is None:
                continue
            tk = min(cands, key=lambda t: (abs((t.p_times[0] if t.p_times else self.as_of) - m.a), t.id))
            if m.kind == "instr":
                c = tk.cycles[0]
                if c.sb in ("S2p", "S2m"):
                    c.s, c.sb, c.s_ref = m.a, "S2M", f"수동:{m.key}"
                    tk.flags.append("확인응답 반영(시작)")
            else:
                c = tk.cycles[-1]
                if c.eb in (None, "OPEN", "E3i", "E2l", "NEXT_REQ", "E3c"):
                    c.e, c.eb, c.e_ref = m.a, "E3M", f"수동:{m.key}"
                    tk.flags.append("확인응답 반영(종료)")

    # --- (h) 경계 확정·등급 ---
    def completion(self, tk: UnitTask, c: Cycle, nxt: int):
        w = self.e2w
        best = None
        q_to = min(nxt, self.as_of)
        ps = [t for t in tk.p_times if c.s - self.s2_pad <= t < min(nxt, self.as_of + 1)]
        tail_lo = (ps[-1] - self.e2_tail) if ps else None
        for f in sorted(tk.docs):
            x = self.finfo.get(f)
            if not x:
                continue
            lo, hi = c.s, min(nxt, self.as_of + 1)
            saves = [t for t in x["saves"] if lo <= t < hi]
            exports = [t for t in x["exports"] if lo <= t < hi]
            results = [t for t in x["results"] if lo <= t < hi]
            fgs = [b for a, b in x["fg"] if lo <= a < hi]
            if not (saves or exports or results or (x["autosave"] and fgs)):
                continue
            last = max(saves + exports + results + ([max(fgs)] if (fgs and x["autosave"]) else []))
            sc = 0.0
            qwd = self.as_quiet_wd if x["autosave"] else self.quiet_wd
            if self.wd(last, q_to) >= qwd:
                sc += w["quiet"]
            if exports and (not saves or 0 <= max(exports) - max(saves) <= DAY):
                sc += w["export"]
            if x["finals"]:
                sc += w["final"]
            if results:
                sc += w["result"]
            if any(m.dir == "out" and f in m.atts and 0 <= m.t - last <= 7 * DAY for m in self.ev.msgs):
                sc += w["attached"]
            sc = round(sc, 4)
            if tail_lo is not None and last < tail_lo:      # 완료 후보 뒤에도 그 업무 작업이 이어지면 종료가 아니다
                continue
            if sc >= self.e2_low and (best is None or last > best[0]):
                best = (last, "E2h" if sc >= self.e2_high else "E2l", round(sc, 2))
        return best

    def coverage_ok(self, t1: int, t2: int) -> bool:
        """[t1, t2] 날짜에 mail_out·teams 커버리지 결손이 없는가(E3i 판정 보류 근거)."""
        d = d_of(t1)
        end = d_of(t2)
        while d <= end:
            for ax in ("mail_out", "teams"):
                if self.ev.coverage.get((d, ax)) in _BAD_COV:
                    return False
            d += timedelta(days=1)
        return True

    def boundaries(self) -> None:
        pre, post = self.s2_pad, self.e3_pad
        for tk in self.tasks:
            P = tk.p_times
            c0 = tk.cycles[0]
            if c0.s is None:
                first = P[0] if P else self.as_of
                c0.s = first - pre
                # S2m: 의뢰자 동석 회의가 첫 진행 전 s2MeetLookbackH 안에 끝났으면 그 회의 시작(가장 최근 회의)
                for mt, _rv in sorted(tk.meet_refs, key=lambda x: (-x[0].a, x[0].id)):
                    if mt.b <= first and first - mt.b <= self.meet_back:
                        c0.s, c0.sb, c0.s_ref = mt.a, "S2m", mt.id
                        break
            if tk.kind in ("S1", "ACK", "COORD") and P and P[0] < c0.s - self.pre_tol:
                tk.pre_from = P[0]
                tk.flags.append("선행착수(공식 의뢰 전 작업)")
            # NEXT_REQ: 열린 차수에 '조용한 기간(≥ reopenQuietWd 근무일)' 뒤 같은 화제 추가 지시 → 새 차수
            if tk.adds and tk.kind in ("S1", "ACK"):
                for ta, mid, _mk in sorted(tk.adds):
                    idx = None
                    for ii, c in enumerate(tk.cycles):
                        if c.s <= ta and (c.e is None or c.e > ta):
                            idx = ii
                    if idx is None:
                        continue
                    c = tk.cycles[idx]
                    before = [p for p in P if c.s - pre <= p < ta]
                    if before and self.wd(before[-1], ta) >= self.reopen_wd:
                        old = (c.e, c.eb, c.e_ref)
                        e2 = self.completion(tk, c, ta)
                        if e2:
                            c.e, c.eb, c.e_ref = e2[0], e2[1], "완료후보"
                        else:
                            c.e, c.eb, c.e_ref = before[-1] + post, "NEXT_REQ", mid
                        nc = Cycle(ta, "S1", s_ref=mid)
                        if old[0] is not None:
                            nc.e, nc.eb, nc.e_ref = old
                        tk.cycles.insert(idx + 1, nc)
            for i, c in enumerate(tk.cycles):
                if c.e is not None:
                    continue
                nxt = tk.cycles[i + 1].s if i + 1 < len(tk.cycles) else self.as_of + 1
                ps = [t for t in P if c.s - pre <= t < nxt]
                e2 = self.completion(tk, c, nxt)
                e3c = None
                if ps:
                    for mt, ok in sorted(tk.meet_refs, key=lambda x: (x[0].a, x[0].id)):
                        if ok and self.requester_in(mt, tk) and ps[-1] <= mt.a <= ps[-1] + self.e3c_ahead \
                                and mt.a < nxt:
                            e3c = mt
                            break
                if e2:
                    c.e, c.eb, c.e_ref = e2[0], e2[1], "완료후보"
                elif e3c is not None:
                    c.e, c.eb, c.e_ref = e3c.b, "E3c", e3c.id
                elif ps and self.wd(ps[-1], self.as_of) >= self.dormant_wd:
                    if not self.need_cov or self.coverage_ok(ps[-1], self.as_of):
                        c.e, c.eb, c.e_ref = ps[-1] + post, "E3i", "휴면추정"
                    else:
                        c.eb = "OPEN"
                        self._q("Q03", tk.id, "coverage", evidence_keys=(tk.first_key,), day=d_of(c.s),
                                note="메일·팀즈 수집 결손 기간 — 종료 판정 보류")
                elif not ps and tk.kind in ("S1", "ACK", "COORD") and i == 0:
                    c.unstarted = True
                    c.eb = "OPEN"
                else:
                    c.eb = "OPEN"
            for c in tk.cycles:
                if c.e is not None and c.e < c.s:
                    c.e = c.s
            sb, eb = tk.cycles[0].sb, tk.cycles[-1].eb
            if tk.kind == "REPORT_ONLY":
                tk.grade = "D"
            elif tk.cycles[0].unstarted and len(tk.cycles) == 1:
                tk.grade = "Z"
            else:
                tk.grade = grade_of(sb, eb)
            tk.status = "open" if eb in (None, "OPEN") else ("estimated" if eb in ("E2l", "E3i", "NEXT_REQ")
                                                               else "closed")
            if tk.grade == "Z":
                tk.status = "not_started"
                if self.wd(tk.cycles[0].s, self.as_of) >= self.unstarted_wd:
                    self._q("Q02", tk.id, tk.first_key, evidence_keys=(tk.first_key,), day=d_of(tk.cycles[0].s),
                            note="의뢰 후 진행 증거 없음")

    # --- (i) 기계 시간 ---
    def machine(self) -> None:
        byid = {t.id: t for t in self.tasks}
        for c in self.ev.comps:
            tid = None
            if c.fam and c.fam in self.segs:
                sg = self.seg_at(c.fam, c.a)
                if sg and sg.links:
                    tid = max(sg.links, key=lambda k: (sg.links[k], k))
            if tid is None:
                for a, b, t in self.app_task.get(c.app, []):
                    if a - DAY <= c.a <= b + DAY:
                        tid = t
            if tid and c.b > c.a:
                byid[tid].machine_s += c.b - c.a
                byid[tid].machine_iv.append((c.a, c.b))

    def build(self) -> list[UnitTask]:
        self.conversations()
        self.families()
        self.link_docs()
        self.self_tasks()
        self.collect_progress()
        self.meetings()
        self.manual_answers()
        self.boundaries()
        self.machine()
        for tk in self.tasks:                         # (j) 거대 성분 가드
            if len(tk.p_times) > self.giant_n or \
                    (tk.p_times and tk.p_times[-1] - tk.p_times[0] > self.giant_days * DAY):
                tk.flags.append("거대성분")
                self._q("Q12", tk.id, "giant", evidence_keys=(tk.first_key,),
                        day=d_of(tk.cycles[0].s) if tk.cycles and tk.cycles[0].s is not None else None,
                        note="증거가 너무 많거나 기간이 김 — 나눌까요?")
        ids = [t.id for t in self.tasks]
        if len(set(ids)) != len(ids):
            raise ValueError("unit_id 충돌 — 서로 다른 시작 근거 키가 같은 unit_id 가 됐다")
        self.ctx = TaskCtx(self.segs, self.seg_starts, self.finfo, self.msg_task, self.meet_task, self.app_task,
                           {t.id: t for t in self.tasks}, self.as_of, self.uid, builder=self)
        return self.tasks
