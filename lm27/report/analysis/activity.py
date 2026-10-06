# -*- coding: utf-8 -*-
r"""단위업무 활동 로그 · 분석 문맥(R §4.1 · §3.4 · §2.5 · 부록 A `build_activity`, 계약 §3.14 `timecore/1.1` · C21).

분석층의 바탕 모듈이다. 시간 코어 결과 파일(`tasks.json`·`attrib.jsonl`·`team_tables.json`·`env_slots.jsonl`·
`day_ledger.jsonl`·`run_meta.json`)과 분류 라벨(`hier\labels.json`)을 **읽기만** 해서(새 시간을 만들지 않는다 — 귀속된 분을
다시 나눌 뿐) 다른 분석 모듈이 쓰는 형으로 바꾼다.

- `Run`·`Milestone`·`ActivityLog`·`build_activity(tasks, attrib, days=None, cfg=None)`(R §4.1): 단위업무마다 시각순
  흔적. 구간 단계 = `attrib.obs`(C21 — 단계 코드 문자열, '' = 단계 아님)가 같은 연속 슬롯, 점 단계 = 차수 근거 코드.
  `obs` 열이 아예 없으면(시간 코어 구판) 거친 단계(L1 → OFFLINE · L2 → MEET · L4 → COMM)와 `coarse=True`(§4.1.4).
- `grade_of(level, target)`: 귀속 분 등급 O(관측 L1·L2회의·L3PC)·I(추정)·X(버킷)(W §7.1 · R §3.4).
- `obs_split(alloc, attrib, slot_tags)`: 정수 분 표의 (날짜, 업무, 꼬리표) 칸을 같은 최대잉여로 O/I 로 나눈다(동률 O 먼저 —
  R §3.4). obs_min + est_min = alloc 분이 칸마다 정확하다(모델 등식 G-R2).
- `Unit`·`make_units(...)`: 단위업무 한 개의 분석용 보기(경계·투입·라벨·동료·문서 — 시각은 **로컬 분**).
- `AnalysisCtx`·`make_context(...)`: 분석층 함수들이 함께 쓰는 문맥. 보고서 모델(WP-31 `model.build_model`)은
  `make_context` 로 문맥을 만들고 `lm27.report.analysis.analyze(ctx)` 를 부른다.

시각: 로컬 분 = 로컬 초 // 60, 원점 2020-01-01 00:00 로컬(계약 §3.14 · `lm27.time.calendar.EPOCH`). 모델의 시각 문자열은
근무 시간대 로컬 `YYYY-MM-DDTHH:MM`(R §9.2.2). 결정성(G-R1): 모든 목록은 명시 정렬 키로 만든다.

표준 라이브러리만 쓴다(+ `lm27.time.calendar`·`lm27.vocab.steps`·`lm27.report.fmt`·`lm27.report.vocab`). 파일을 쓰지 않는다.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from lm27.report import fmt as F
from lm27.report import vocab as V
from lm27.time.calendar import EPOCH, SLOT, TAGS, d_of, day0
from lm27.vocab import steps as S

__all__ = [
    "ActivityLog",
    "AnalysisCtx",
    "Cyc",
    "Milestone",
    "Run",
    "Unit",
    "build_activity",
    "grade_of",
    "lmin_date",
    "lmin_iso",
    "make_context",
    "make_units",
    "obs_split",
    "parse_local",
]

SLOT_MIN = SLOT // 60                          # 5분 슬롯 = 로컬 분 5
OBSERVED = frozenset({"L1", "L2회의", "L3PC"})  # O 등급 귀속 단계(W §7.1)
COARSE_OBS = {"L1": "OFFLINE", "L2": "MEET", "L4": "COMM"}   # obs 열 없는 구판(R §4.1.4)
SAMPLER_BASIS = frozenset({"C1", "C1b"})       # 샘플러 근거 슬롯(R §4.9 sampler_ratio)
PC_BASIS = frozenset({"C1", "C1b", "C7", "C8"})  # PC 가동 관측 근거(커버리지 원장에 pc 축이 없을 때의 대체 판정)
LEVEL_KEYS = ("L1", "L2", "L3", "L4", "L5", "L6", "L7")
CLOSED = frozenset({"closed", "estimated"})
EST_START = frozenset({"S2p", "S2m"})           # 추정 시작(R §4.4.2 '추정 시작')
EST_END = frozenset({"E2l", "E3c", "E3i", "NEXT_REQ"})   # 추정 종료(R §4.3.1)
_TYPE_EXT = {"DOC_DOC": "doc", "DOC_PPT": "ppt", "DOC_XLS": "xls", "DOC_PDF": "pdf", "DOC_ETC": "txt", "APP_CAD": "cad",
             "APP_IDE": "code", "COMMIT": "code"}           # Run 단계 유형 → 다룬 문서의 확장자군(이름을 모를 때)
_ACCEPT_RE = re.compile(r"^수락 (\d{2})-(\d{2}) (\d{2}):(\d{2})$")
_MEET_LINK_RE = re.compile(r"^회의연결 (\S+)$")
_EPOCH_DT = datetime(EPOCH.year, EPOCH.month, EPOCH.day)
_LOCAL_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}))?")


# ───────────────────────────── 시각 도우미 ─────────────────────────────
def lmin_iso(m: int | None) -> str | None:
    """로컬 분 → `YYYY-MM-DDTHH:MM`(근무 시간대 벽시계 — R §9.2.2)."""
    if m is None:
        return None
    return (_EPOCH_DT + timedelta(minutes=int(m))).strftime("%Y-%m-%dT%H:%M")


def lmin_date(m: int) -> date:
    """로컬 분 → 그 시각의 달력 날짜(`lm27.time.calendar.d_of` 단일원 — X-323)."""
    return d_of(int(m) * 60)


def date_lmin(d) -> int:
    """그 날 00:00 의 로컬 분(`lm27.time.calendar.day0` 단일원)."""
    dd = d if isinstance(d, date) else date.fromisoformat(str(d)[:10])
    return day0(dd) // 60


def parse_local(x) -> int | None:
    """기준 시각(as_of) → 로컬 분. int = 로컬 초(시간 코어 값), str = 근무 시간대 벽시계 ISO(`run_meta.as_of` 는
    `YYYY-MM-DDTHH:MM:SS+09:00` — 앞 16자가 근무 시간대 벽시계다), date = 그날 끝, datetime = 벽시계 그대로."""
    if x is None:
        return None
    if isinstance(x, bool):
        raise TypeError("as_of 에 bool 은 쓸 수 없다")
    if isinstance(x, int):
        return x // 60
    if isinstance(x, datetime):
        return int((x.replace(tzinfo=None) - _EPOCH_DT).total_seconds()) // 60
    if isinstance(x, date):
        return date_lmin(x) + F.DAY_MIN - 1
    m = _LOCAL_RE.match(str(x).strip())
    if not m:
        raise ValueError(f"기준 시각 형식 오류 {x!r}")
    y, mo, d, hh, mm = m.groups()
    base = date_lmin(date(int(y), int(mo), int(d)))
    if hh is None:
        return base + F.DAY_MIN - 1
    return base + int(hh) * 60 + int(mm)


def _lmin(t) -> int | None:
    return None if t is None else int(t) // 60


def _get(obj, name: str, default=None):
    """사전·속성 객체 겸용 읽기(UnitLabel·EffectiveRegistry·dict)."""
    if obj is None:
        return default
    if isinstance(obj, Mapping):
        v = obj.get(name, default)
    else:
        v = getattr(obj, name, default)
    return default if v is None else v


def grade_of(level, target) -> str:
    """귀속 분 등급(W §7.1 · R §3.4): 버킷 → X, L1·L2회의(전체)·L3PC → O, 그 밖(L2 분할·L4·L5·L6) → I."""
    if str(target).startswith("B_"):
        return "X"
    return "O" if str(level) in OBSERVED else "I"


def _level_key(level) -> str:
    s = str(level or "")
    return s[:2] if s[:1] == "L" and s[1:2].isdigit() else ""


# ───────────────────────────── 흔적 형(R §4.1.1) ─────────────────────────────
@dataclass(frozen=True)
class Run:
    """한 단위업무 안에서 같은 단계 유형(obs)이 이어진 슬롯 구간. a·b = 로컬 분 [a, b)."""
    unit_id: str
    type: str
    a: int
    b: int
    sec: int                                   # 그 업무에 귀속된 초 합(분할 슬롯은 그 업무 몫만)
    obs_sec: int                               # 그중 O 등급 초
    levels: frozenset[str]                     # 포함된 귀속 단계(L1~L6 표기)
    apps: tuple[tuple[str, int], ...]          # (app_id, 초) — 초 내림차순, 같으면 app_id 순
    fams: tuple[tuple[str, int], ...]          # (fam_key, 초)
    level_sec: tuple[tuple[str, int], ...] = ()   # (귀속 단계, 초) — 디지털 비중(R §4.8.1)
    kind = "A"

    @property
    def t(self) -> int:
        return self.a

    @property
    def minutes(self) -> int:
        return F.sec_min(self.sec)


@dataclass(frozen=True)
class Milestone:
    """점 단계(시각만, 소요 0). key = 근거 키(msg id·회의 id·'수동:<key>') — 로컬 드릴다운 전용."""
    unit_id: str
    type: str
    t: int
    cycle: int
    key: str
    flags: frozenset[str]                      # offline · interim · date_only
    kind = "M"

    @property
    def a(self) -> int:
        return self.t

    @property
    def b(self) -> int:
        return self.t

    @property
    def sec(self) -> int:
        return 0

    @property
    def obs_sec(self) -> int:
        return 0


class ActivityLog(dict):
    """unit_id → 시각순 [Run | Milestone]. `coarse` = obs 열 없는 구판 입력(R §4.1.4)."""
    coarse: bool = False


def _sort_key(it) -> tuple:
    st = S.STEP_TYPES.get(it.type)
    return (it.t, 0 if it.kind == "M" else 1, st.order if st else 99, it.type)


@dataclass(frozen=True)
class Cyc:
    """차수(로컬 분). interim = ((시각, 코드), …)."""
    s: int | None
    sb: str
    e: int | None
    eb: str | None
    s_ref: str | None
    e_ref: str | None
    interim: tuple[tuple[int, str], ...]
    unstarted: bool


def cycles_of(row) -> tuple[Cyc, ...]:
    """tasks.json 행의 cycles(로컬 초) → Cyc(로컬 분)."""
    out = []
    for c in _get(row, "cycles", ()) or ():
        it = tuple((_lmin(t), str(code)) for t, code in (_get(c, "interim", ()) or ()) if t is not None)
        out.append(Cyc(_lmin(_get(c, "s")), str(_get(c, "sb", "") or ""), _lmin(_get(c, "e")),
                       (str(_get(c, "eb")) if _get(c, "eb") else None), _get(c, "s_ref"), _get(c, "e_ref"), it,
                       bool(_get(c, "unstarted", False))))
    return tuple(out)


def _accept_time(flags: Iterable[str], cycles: tuple[Cyc, ...]) -> int | None:
    """표식 '수락 MM-DD HH:MM' → 로컬 분(연도는 첫 차수 시작에서 — 해를 넘기면 다음 해)."""
    s0 = next((c.s for c in cycles if c.s is not None), None)
    for f in flags:
        m = _ACCEPT_RE.match(str(f))
        if not m or s0 is None:
            continue
        mo, d, hh, mm = (int(x) for x in m.groups())
        d0 = lmin_date(s0)
        try:
            cand = date(d0.year, mo, d)
        except ValueError:
            continue
        if cand < d0 - timedelta(days=1):
            try:
                cand = date(d0.year + 1, mo, d)
            except ValueError:
                continue
        return date_lmin(cand) + hh * 60 + mm
    return None


def _milestones(unit_id: str, kind: str, cycles: tuple[Cyc, ...], flags: Iterable[str]) -> list[Milestone]:
    """차수 근거 코드 → 점 단계(R §4.1.2 ②). 추정 경계(S2p·S2m·E2h·E2l·E3c·E3i·NEXT_REQ·OPEN)는 점이 아니다."""
    out: list[Milestone] = []

    def add(code, t, ci, key, *fl):
        if t is not None:
            out.append(Milestone(unit_id, code, int(t), ci, str(key or ""), frozenset(fl)))
    for ci, c in enumerate(cycles):
        if c.sb in ("S1", "S1d"):
            add("REQ_IN", c.s, ci, c.s_ref, *(("date_only",) if c.sb == "S1d" else ()))
        elif c.sb == "S1o":
            add("REQ_OUT", c.s, ci, c.s_ref)
        elif c.sb == "S2M":
            add("REQ_IN", c.s, ci, c.s_ref, "offline")
        elif c.sb == "S2a":
            add("ACK_OUT", c.s, ci, c.s_ref)
        for t, code in c.interim:
            if code in ("E1p", "E1", "E1d"):
                add("REPORT_OUT", t, ci, "", "interim", *(("date_only",) if code == "E1d" else ()))
            elif code == "E1i":
                add("REPORT_IN", t, ci, "", "interim")
        if c.e is not None:
            if c.eb in ("E1", "E1d"):
                add("REPORT_OUT", c.e, ci, c.e_ref, *(("date_only",) if c.eb == "E1d" else ()))
            elif c.eb == "E1i":
                add("REPORT_IN", c.e, ci, c.e_ref)
            elif c.eb == "E3M":
                add("REPORT_OUT", c.e, ci, c.e_ref, "offline")
    if kind == "S1":
        ta = _accept_time(flags, cycles)
        if ta is not None:
            ci = max([i for i, c in enumerate(cycles) if c.s is not None and c.s <= ta] or [0])
            add("ACK_OUT", ta, ci, "")
    return out


def _top_pairs(cnt: Mapping[str, int]) -> tuple[tuple[str, int], ...]:
    return tuple(sorted(((k, int(v)) for k, v in cnt.items() if k and v > 0), key=lambda x: (-x[1], x[0])))


def build_activity(tasks, attrib, days=None, cfg=None) -> ActivityLog:
    """R §4.1.2 — 단위업무 활동 로그. tasks = tasks.json 행 또는 `Unit`, attrib = attrib.jsonl 행.

    ① 구간: target 이 단위업무(`u_…`)이고 obs ≠ '' 인 행을 (업무, obs) 별 슬롯 오름차순으로 훑어, 연속 슬롯(이전 + 1)이고
    같은 obs 면 한 Run 으로 잇는다. ② 점: 차수 근거 코드. ③ 정렬: (시각, 점 먼저, 단계 표 순번).
    `days`·`cfg` 는 부록 A 시그니처 호환(쓰지 않음)."""
    rows = list(attrib or ())
    coarse = bool(rows) and not any(isinstance(r, Mapping) and "obs" in r for r in rows)
    acc: dict[tuple[str, str], dict[int, dict]] = defaultdict(dict)
    for r in rows:
        tgt = str(_get(r, "target", ""))
        if not tgt.startswith("u_"):
            continue
        lv = str(_get(r, "level", ""))
        ob = COARSE_OBS.get(_level_key(lv), "") if coarse else str(_get(r, "obs", "") or "")
        if not ob or ob not in S.STEP_TYPES:
            continue
        slot = int(_get(r, "slot"))
        sec = int(_get(r, "sec", 0) or 0)
        if sec <= 0:
            continue
        d = acc[(tgt, ob)].setdefault(slot, {"sec": 0, "obs": 0, "lv": defaultdict(int), "app": defaultdict(int),
                                               "fam": defaultdict(int)})
        d["sec"] += sec
        if grade_of(lv, tgt) == "O":
            d["obs"] += sec
        d["lv"][lv] += sec
        app = str(_get(r, "app", "") or "")
        fam = str(_get(r, "fam", "") or "")
        if app:
            d["app"][app] += sec
        if fam:
            d["fam"][fam] += sec
    log = ActivityLog()
    log.coarse = coarse
    items: dict[str, list] = defaultdict(list)
    for (uid, ob), by_slot in sorted(acc.items()):
        cur = None
        for slot in sorted(by_slot):
            d = by_slot[slot]
            if cur is not None and slot == cur["last"] + 1:
                cur["last"] = slot
            else:
                if cur is not None:
                    items[uid].append(_mk_run(uid, ob, cur))
                cur = {"first": slot, "last": slot, "sec": 0, "obs": 0, "lv": defaultdict(int),
                       "app": defaultdict(int), "fam": defaultdict(int)}
            cur["sec"] += d["sec"]
            cur["obs"] += d["obs"]
            for k in ("lv", "app", "fam"):
                for x, v in d[k].items():
                    cur[k][x] += v
        if cur is not None:
            items[uid].append(_mk_run(uid, ob, cur))
    for t in tasks or ():
        uid = str(_get(t, "unit_id", "") or "")
        if not uid:
            continue
        cyc = t.cycles if isinstance(t, Unit) else cycles_of(t)
        ms = _milestones(uid, str(_get(t, "kind", "") or ""), cyc, _get(t, "flags", ()) or ())
        if ms:
            items[uid] += ms
    for uid in sorted(items):
        log[uid] = sorted(items[uid], key=_sort_key)
    return log


def _mk_run(uid: str, ob: str, cur: dict) -> Run:
    return Run(uid, ob, cur["first"] * SLOT_MIN, (cur["last"] + 1) * SLOT_MIN, int(cur["sec"]), int(cur["obs"]),
               frozenset(cur["lv"]), _top_pairs(cur["app"]), _top_pairs(cur["fam"]),
               tuple(sorted((k, int(v)) for k, v in cur["lv"].items())))


# ───────────────────────────── 정수 분 표 · O/I 나누기(R §3.4) ─────────────────────────────
def read_tables(tables) -> tuple[dict[str, dict[str, int]], dict[tuple[str, str, str], int]]:
    """team_tables.json → (envelope {날짜: {꼬리표: 분}}, alloc {(날짜, unit_id, 꼬리표): 분})."""
    env: dict[str, dict[str, int]] = {}
    alloc: dict[tuple[str, str, str], int] = {}
    if not isinstance(tables, Mapping):
        return env, alloc
    ed = tables.get("envelope_daily") or {}
    cols = list(ed.get("cols") or ["date", *TAGS])
    for row in ed.get("rows") or ():
        rec = dict(zip(cols, row, strict=False))
        d = str(rec.get("date"))
        env[d] = {t: int(rec.get(t, 0) or 0) for t in TAGS}
    ad = tables.get("alloc_daily") or {}
    cols = list(ad.get("cols") or ["date", "unit_id", "tag", "min"])
    for row in ad.get("rows") or ():
        rec = dict(zip(cols, row, strict=False))
        k = (str(rec.get("date")), str(rec.get("unit_id")), str(rec.get("tag")))
        alloc[k] = alloc.get(k, 0) + int(rec.get("min", 0) or 0)
    return env, alloc


def obs_split(alloc: Mapping, attrib, slot_tags: Mapping[int, str] | None = None) -> dict[tuple, tuple[int, int]]:
    """(날짜, unit_id, 꼬리표) 칸의 alloc 분 → (obs_min, est_min). 칸 안 O·I 초를 가중으로 최대잉여(동률 O 먼저).

    slot_tags = {슬롯: 꼬리표}(env_slots.jsonl). 슬롯 꼬리표를 모르면 같은 (날짜, 업무)의 O·I 초 전체를 가중으로 쓴다.
    귀속 행이 전혀 없는 칸은 추정(I)으로 둔다(관측으로 부풀리지 않는다)."""
    tags = slot_tags or {}
    w: dict[tuple, dict[str, int]] = defaultdict(lambda: {"O": 0, "I": 0})
    wd: dict[tuple, dict[str, int]] = defaultdict(lambda: {"O": 0, "I": 0})
    for r in attrib or ():
        tgt = str(_get(r, "target", ""))
        if not tgt.startswith("u_"):
            continue
        slot = int(_get(r, "slot"))
        d = d_of(slot * SLOT).isoformat()
        g = grade_of(_get(r, "level", ""), tgt)
        sec = int(_get(r, "sec", 0) or 0)
        tag = tags.get(slot)
        if tag is not None:
            w[(d, tgt, tag)][g] += sec
        wd[(d, tgt)][g] += sec
    out = {}
    for (d, u, tag), m in alloc.items():
        wt = w.get((d, u, tag)) or wd.get((d, u)) or {"O": 0, "I": 0}
        if wt["O"] <= 0 and wt["I"] <= 0:
            out[(d, u, tag)] = (0, int(m))
            continue
        sp = F.split_largest(int(m), wt, ("O", "I"))
        out[(d, u, tag)] = (int(sp.get("O", 0)), int(sp.get("I", 0)))
    return out


# ───────────────────────────── 단위업무 보기 ─────────────────────────────
@dataclass
class Unit:
    """단위업무 한 개의 분석용 보기. 시각은 로컬 분, 투입은 정수 분 표(alloc) 합(RP1)."""
    unit_id: str
    kind: str
    title: str
    title_by: str
    project_key: str                    # P-… · 제안 ID · 'UNC'(H rollup_labels 와 같은 자리)
    project_id: str | None              # 레지스트리 과제(P-… — 예약 P-99xx 포함)
    proposal_id: str | None
    domain: str
    field: str
    func: str
    wtype: str
    stance: str
    ax_link: bool
    role_id: str
    label_level: str
    grade: str
    status: str
    cycles: tuple[Cyc, ...]
    start: int | None
    end: int | None
    lead_min: int | None
    biz_lead_min: int | None
    effort_min: int
    obs_min: int
    est_min: int
    by_date: dict[str, int]
    by_month: dict[str, int]
    by_tag: dict[str, int]
    parallel: float
    machine_min: int
    pre_request_min: int
    levels_min: dict[str, int]
    flags: tuple[str, ...]
    docs: dict[str, dict]
    peers: tuple[tuple[str, str], ...]
    conv: str
    first_key: str
    meetings: tuple[str, ...]
    label: str = ""                     # 시간 코어 표지(키 기반 — 제목이 없을 때만 씀)

    @property
    def start_date(self) -> date | None:
        return None if self.start is None else lmin_date(self.start)

    @property
    def end_date(self) -> date | None:
        return None if self.end is None else lmin_date(self.end)

    @property
    def closed(self) -> bool:
        return self.status in CLOSED

    @property
    def n_cycles(self) -> int:
        return len([c for c in self.cycles if not c.unstarted])

    def span(self, as_of_min: int) -> tuple[int, int] | None:
        """리드 구간 [첫 차수 시작(추정 경계 포함), 마지막 차수 끝(진행 중이면 분석 시각)]."""
        if self.start is None:
            return None
        e = self.end if self.end is not None else max(as_of_min, self.start)
        return self.start, max(e, self.start)


GENERIC_UNIT_TITLE = "미분류 단위업무"     # 제목 재료가 시간 코어 표지·로컬 키뿐일 때(W2 C08 — 통합)


def _unit_title_or(fallback: str) -> str:
    """시간 코어 업무 표지(``SELF:…@MM-DD``·``MANUAL:t:…`` 등)·로컬 키 모양은 제목으로 내지 않는다(``lm27.hier.groups.is_marker``)."""
    from lm27.hier.groups import is_marker
    s = str(fallback or "")
    return GENERIC_UNIT_TITLE if not s.strip() or is_marker(s) else s


def _label_fields(lab, unit_id: str, fallback_title: str) -> dict:
    """UnitLabel(또는 labels.json 값) → 분석 필드. 라벨 없음 = UNC·ETC·ETC·OFFICE·DO(R §2.5 '없을 때')."""
    fallback_title = _unit_title_or(fallback_title)
    if lab is None:
        from lm27.hier.unitlabel import role_id as _role_id     # R-8 식(계약 §4.4) 단일원
        return {"project_key": "UNC", "project_id": None, "proposal_id": None, "domain": "UNC", "field": "ETC",
                "func": "ETC", "wtype": "OFFICE", "stance": "DO", "ax_link": False,
                "role_id": _role_id(None, "ETC", "ETC"), "level": "unclassified", "title": fallback_title,
                "title_by": "rule_generic"}
    p = _get(lab, "project")
    pid = _get(lab, "proposal_id")
    p_s = str(p) if p else ""
    key = p_s if p_s.startswith("P-") else (str(pid) if pid else "UNC")
    title = str(_get(lab, "title", "") or "")
    if not title or title != _unit_title_or(title):              # 예전 분류 결과의 표지 제목도 걸러 낸다
        title = fallback_title
    rid = str(_get(lab, "role_id", "") or "")
    if not rid:
        from lm27.hier.unitlabel import role_id as _role_id
        rid = _role_id(key if key != "UNC" else None, str(_get(lab, "field", "ETC")), str(_get(lab, "func", "ETC")))
    return {"project_key": key, "project_id": p_s if p_s.startswith("P-") else None,
            "proposal_id": str(pid) if pid else None, "domain": str(_get(lab, "domain", "UNC") or "UNC"),
            "field": str(_get(lab, "field", "ETC") or "ETC"), "func": str(_get(lab, "func", "ETC") or "ETC"),
            "wtype": str(_get(lab, "wtype", "OFFICE") or "OFFICE"), "stance": str(_get(lab, "stance", "DO") or "DO"),
            "ax_link": bool(_get(lab, "ax_link", False)), "role_id": rid,
            "level": str(_get(lab, "level", "unclassified") or "unclassified"), "title": title,
            "title_by": str(_get(lab, "title_src", "rule_generic") or "rule_generic")}


def _meetings(flags: Iterable[str], cycles: tuple[Cyc, ...]) -> tuple[str, ...]:
    out = set()
    for f in flags:
        m = _MEET_LINK_RE.match(str(f))
        if m:
            out.add(m.group(1))
    for c in cycles:
        if c.sb == "S2m" and c.s_ref:
            out.add(str(c.s_ref))
        if c.eb == "E3c" and c.e_ref:
            out.add(str(c.e_ref))
    return tuple(sorted(out))


def make_units(tasks, labels, alloc: Mapping, cells: Mapping, bc: F.BizCal) -> dict[str, Unit]:
    """tasks.json 행 + 라벨 + 정수 분 표 → {unit_id: Unit}. 리드는 차수 합(W §5.5), 영업 리드는 R §3.2 의 영업 분
    (반차·연차를 빼지 않는 달력 기준 경과 — 시간 코어 `biz_lead_s` 와 다를 수 있다)."""
    labels = labels or {}
    eff: dict[str, dict] = defaultdict(lambda: {"date": defaultdict(int), "month": defaultdict(int),
                                                "tag": defaultdict(int), "obs": 0, "est": 0})
    for (d, u, tag), m in alloc.items():
        e = eff[u]
        e["date"][d] += m
        e["month"][d[:7]] += m
        e["tag"][tag] += m
        o, s = cells.get((d, u, tag), (0, m))
        e["obs"] += o
        e["est"] += s
    out: dict[str, Unit] = {}
    for t in sorted(tasks or (), key=lambda r: str(_get(r, "unit_id", ""))):
        uid = str(_get(t, "unit_id", "") or "")
        if not uid:
            continue
        cyc = cycles_of(t)
        flags = tuple(str(f) for f in (_get(t, "flags", ()) or ()))
        lf = _label_fields(labels.get(uid), uid, str(_get(t, "label", "") or uid))
        starts = [c.s for c in cyc if c.s is not None]
        status = str(_get(t, "status", "") or "")
        ends = [c.e for c in cyc if c.e is not None]
        last_closed = bool(cyc) and cyc[-1].e is not None and not cyc[0].unstarted
        end = max(ends) if (ends and status in CLOSED) else None
        lead = biz = None
        if last_closed and status in CLOSED:
            lead = sum(c.e - c.s for c in cyc if c.e is not None and c.s is not None)
            biz = sum(bc.biz_min(c.s, c.e) for c in cyc if c.e is not None and c.s is not None)
        e = eff.get(uid)
        effort = sum(e["date"].values()) if e else 0
        lv_s = _get(t, "levels_s", {}) or {}
        lw = {k: int(lv_s.get(k, 0) or 0) for k in LEVEL_KEYS}
        # 귀속 단계별 분 — 시간 코어 초를 투입 분(정수 분 표)에 최대잉여로 맞춘다(Σ = effort_min). 초가 없으면 비운다.
        levels = F.split_largest(effort, lw, LEVEL_KEYS) if effort > 0 and sum(lw.values()) > 0 else {}
        docs = {}
        for f, v in sorted((_get(t, "docs", {}) or {}).items()):
            ops = _get(v, "ops", {}) or {}
            docs[str(f)] = {"n": int(_get(v, "n", 0) or 0),
                            "ops": {k: int(ops.get(k, 0) or 0) for k in ("save", "export", "attach")}}
        peers = sorted({(str(_get(p, "who_key")), str(_get(p, "rel"))) for p in (_get(t, "peers", ()) or ())
                        if _get(p, "who_key")})
        par = _get(t, "parallel", 0.0)
        out[uid] = Unit(
            unit_id=uid, kind=str(_get(t, "kind", "") or ""), title=lf["title"], title_by=lf["title_by"],
            project_key=lf["project_key"], project_id=lf["project_id"], proposal_id=lf["proposal_id"],
            domain=lf["domain"], field=lf["field"], func=lf["func"], wtype=lf["wtype"], stance=lf["stance"],
            ax_link=lf["ax_link"], role_id=lf["role_id"], label_level=lf["level"], grade=str(_get(t, "grade", "")),
            status=status, cycles=cyc, start=min(starts) if starts else None, end=end, lead_min=lead,
            biz_lead_min=biz, effort_min=int(effort), obs_min=int(e["obs"]) if e else 0,
            est_min=int(e["est"]) if e else 0, by_date=dict(sorted(e["date"].items())) if e else {},
            by_month=dict(sorted(e["month"].items())) if e else {},
            by_tag={tg: int(e["tag"].get(tg, 0)) for tg in TAGS} if e else dict.fromkeys(TAGS, 0),
            parallel=float(par) if isinstance(par, (int, float)) and not isinstance(par, bool) else 0.0,
            machine_min=F.sec_min(int(_get(t, "machine_s", 0) or 0)),
            pre_request_min=F.sec_min(int(_get(t, "pre_request_s", 0) or 0)),
            levels_min={k: int(levels.get(k, 0)) for k in LEVEL_KEYS}, flags=flags, docs=docs, peers=tuple(peers),
            conv=str(_get(t, "conv", "") or ""), first_key=str(_get(t, "first_key", "") or ""),
            meetings=_meetings(flags, cyc), label=str(_get(t, "label", "") or ""))
    return out


# ───────────────────────────── 날짜 사실(측정 품질·리뷰 재료) ─────────────────────────────
@dataclass
class DayFacts:
    env_min: int = 0
    by_tag: dict = field(default_factory=dict)
    conf_min: dict = field(default_factory=lambda: {"high": 0, "mid": 0, "low": 0})
    sampler: bool = False
    pc_basis: bool = False
    coverage: dict = field(default_factory=dict)        # 축 → 상태(C §5.3 일자 합성)
    leave: float = 0.0
    absence: bool = False


# ───────────────────────────── 분석 문맥 ─────────────────────────────
@dataclass
class AnalysisCtx:
    """분석층 함수가 함께 쓰는 문맥(make_context 가 만든다)."""
    cfg: object
    bc: F.BizCal
    units: dict[str, Unit]
    log: ActivityLog
    env: dict[str, dict[str, int]]
    alloc: dict[tuple[str, str, str], int]
    cells: dict[tuple[str, str, str], tuple[int, int]]
    days: dict[str, DayFacts]
    as_of_min: int
    d0: date
    d1: date
    registry: object = None
    person_dir: Mapping | None = None
    evidence: object = None
    ai: dict = field(default_factory=dict)              # 단계 → {key: {ans, by, …}}
    fam_ext: dict = field(default_factory=dict)         # 문서군 키 → 확장자군(정제 이름이 있을 때)
    catalog: list = field(default_factory=list)         # 레지스트리 agents[](dict 형)
    fallback: object = None                             # (stage, item, ns) → 답 | None
    warnings: list = field(default_factory=list)
    run_id: str = ""
    _by_date: dict | None = field(default=None, repr=False, compare=False)
    _doc_cls: dict | None = field(default=None, repr=False, compare=False)
    _units_sorted: list | None = field(default=None, repr=False, compare=False)
    _unit_cells: dict | None = field(default=None, repr=False, compare=False)

    # ── 파생 색인 ──
    def months(self) -> list[str]:
        out, d = [], date(self.d0.year, self.d0.month, 1)
        while d <= self.d1:
            out.append(f"{d.year:04d}-{d.month:02d}")
            d = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
        return out

    def dates(self) -> list[date]:
        out, d = [], self.d0
        while d <= self.d1:
            out.append(d)
            d += timedelta(days=1)
        return out

    def as_of_date(self) -> date:
        return lmin_date(self.as_of_min)

    def unit_list(self) -> list[Unit]:
        """단위업무(첫 차수 시작 → unit_id 순 — R §9.2.2 units 정렬). 한 번 정렬해 둔다(문맥은 만든 뒤 바뀌지 않는다)."""
        if self._units_sorted is None or len(self._units_sorted) != len(self.units):
            self._units_sorted = sorted(self.units.values(),
                                        key=lambda u: (u.start if u.start is not None else -1, u.unit_id))
        return list(self._units_sorted)

    def by_role(self) -> dict[str, list[Unit]]:
        out: dict[str, list[Unit]] = defaultdict(list)
        for u in self.unit_list():
            out[u.role_id].append(u)
        return dict(sorted(out.items()))

    def doc_class(self, fam: str) -> str:
        """문서군 → 확장자군: 정제 이름이 있으면 그 확장자(`fam_ext`), 없으면 그 문서를 다룬 Run 의 단계 유형으로
        (DOC_XLS → xls …). 모르면 ''."""
        if self._doc_cls is None:
            cnt: dict[str, Counter] = defaultdict(Counter)
            for items in self.log.values():
                for x in items:
                    g = _TYPE_EXT.get(x.type) if x.kind == "A" else None
                    if g:
                        for f, sec in x.fams:
                            cnt[f][g] += sec
            self._doc_cls = {f: sorted(c, key=lambda k: (-c[k], k))[0] for f, c in cnt.items() if c}
        return self.fam_ext.get(fam) or self._doc_cls.get(fam, "")

    def density(self, unit_id: str) -> dict[str, dict[str, int]]:
        """단위업무의 ISO 주별 관측·추정 분 {YYYY-Www: {obs, est}}(간트 밀도 칸 — R §9.2.1 units[].density)."""
        if self._unit_cells is None:
            ix: dict[str, list] = defaultdict(list)
            for (d, u, tag), (o, e) in sorted(self.cells.items()):
                ix[u].append((d, tag, o, e))
            self._unit_cells = dict(ix)
        out: dict[str, dict[str, int]] = {}
        for d, _tag, o, e in self._unit_cells.get(unit_id, ()):
            w = out.setdefault(F.iso_week(d), {"obs": 0, "est": 0})
            w["obs"] += o
            w["est"] += e
        return dict(sorted(out.items()))

    def day_split(self, d: str) -> dict[str, int]:
        """그 날짜의 봉투 = 관측 + 추정 + 미귀속(정수 분 — R §9.2.1 days[] · 모델 등식)."""
        env = sum((self.env.get(d) or {}).values())
        o = e = 0
        for k, m in self.alloc_on(d):
            co, ce = self.cells.get(k, (0, m))
            o += co
            e += ce
        return {"env_min": env, "obs_min": o, "est_min": e, "unattr_min": env - o - e}

    def alloc_on(self, d: str) -> list[tuple[tuple[str, str, str], int]]:
        """그 날짜의 정수 분 표 칸 [((날짜, unit_id, 꼬리표), 분)](unit_id·꼬리표 순)."""
        if self._by_date is None:
            ix: dict[str, list] = defaultdict(list)
            for k, m in sorted(self.alloc.items()):
                ix[k[0]].append((k, m))
            self._by_date = dict(ix)
        return self._by_date.get(d, [])


def _slot_rows(env_slots) -> tuple[dict[int, str], dict[str, DayFacts]]:
    tags: dict[int, str] = {}
    days: dict[str, DayFacts] = {}
    for r in env_slots or ():
        try:
            slot = int(_get(r, "slot"))
        except (TypeError, ValueError):
            continue
        d = str(_get(r, "date", "") or d_of(slot * SLOT).isoformat())
        tag = str(_get(r, "tag", "") or "")
        tags[slot] = tag
        df = days.setdefault(d, DayFacts())
        df.env_min += SLOT_MIN
        if tag:
            df.by_tag[tag] = df.by_tag.get(tag, 0) + SLOT_MIN
        conf = str(_get(r, "conf", "low") or "low")
        df.conf_min[conf] = df.conf_min.get(conf, 0) + SLOT_MIN
        basis = str(_get(r, "basis", "") or "")
        if basis in SAMPLER_BASIS:
            df.sampler = True
        if basis in PC_BASIS:
            df.pc_basis = True
    return tags, days


def _period(period, env: Mapping, as_of_min: int) -> tuple[date, date]:
    if period:
        a, b = period
        da = a if isinstance(a, date) else date.fromisoformat(str(a)[:10])
        db = b if isinstance(b, date) else date.fromisoformat(str(b)[:10])
        return da, db
    ds = sorted(env)
    if ds:
        return date.fromisoformat(ds[0]), date.fromisoformat(ds[-1])
    d = lmin_date(as_of_min)
    return d, d


def _ai_items(ai) -> dict[str, dict]:
    """ai_out 파일 객체(또는 이미 펼친 items) → {단계: {key: 항목}}."""
    out: dict[str, dict] = {}
    for stage, obj in (ai or {}).items():
        if not isinstance(obj, Mapping):
            continue
        items = obj.get("items") if isinstance(obj.get("items"), Mapping) else obj
        out[str(stage)] = {str(k): v for k, v in items.items() if isinstance(v, Mapping)}
    return out


def _catalog(registry) -> list[dict]:
    """레지스트리 agents[](EffectiveRegistry.agents 의 Agent 또는 원본 dict) → dict 목록(id 순)."""
    raw = _get(registry, "agents", ()) or ()
    out = []
    for a in raw:
        aid = str(_get(a, "id", "") or "")
        if not aid:
            continue
        if str(_get(a, "status", "running") or "running") in ("retired", "removed"):
            continue
        out.append({"id": aid, "name": str(_get(a, "name", "") or aid),
                    "step_types": [str(x) for x in (_get(a, "step_types", ()) or ())],
                    "inputs": [str(x) for x in (_get(a, "inputs", ()) or ())],
                    "outputs": [str(x) for x in (_get(a, "outputs", ()) or ())],
                    "keywords": [str(x) for x in (_get(a, "keywords", ()) or ())],
                    "axis": str(_get(a, "axis", "") or "")})
    return sorted(out, key=lambda a: a["id"])


def _fam_ext(fam_names: Mapping | None, cfg) -> dict[str, str]:
    """문서군 키 → 확장자군(정제 이름의 확장자 + `report.mining.extClassExtra`). 이름을 모르면 비운다."""
    extra = cfg["report.mining.extClassExtra"] if cfg is not None else None
    out = {}
    for f, nm in sorted((fam_names or {}).items()):
        s = str(nm or "")
        ext = s.rsplit(".", 1)[-1] if "." in s else ""
        g = S.ext_class(ext, extra) if ext else ""
        if g:
            out[str(f)] = g
    return out


def make_context(*, tasks, attrib, tables, cal, cfg, labels=None, registry=None, env_slots=None, day_ledger=None,
                 run_meta=None, as_of=None, period=None, person_dir=None, evidence=None, coverage=None,
                 leaves=None, absences=None, ai=None, fam_names=None, fallback=None, run_id="") -> AnalysisCtx:
    """분석 문맥 만들기 — 인자는 이미 읽은 파일 내용(계약 §3.14 · §3.15 형).

    tasks·attrib = 행 목록, tables = team_tables.json 객체, cal = `Calendar`(달력 판은 시간 결과와 같아야 한다 — 다르면
    호출자가 경고), cfg = `Cfg`. labels = {unit_id: UnitLabel|dict}(labels.json), registry = 유효 레지스트리 또는 원본 dict,
    env_slots·day_ledger = 행 목록, run_meta = run_meta.json(`as_of` 를 주지 않으면 여기서), period = (d0, d1)(주지 않으면
    봉투 날짜 범위), person_dir = person_dir.json, evidence = 정규화 증거(시간 코어 `Evidence` 또는 {msgs, meets} 모양 —
    동료 관계 확인용, 없어도 됨), coverage = {날짜: {축: 상태}}(없으면 day_ledger 의 coverage), leaves = {날짜: 0.5·1.0 또는
    am·pm·full}, absences = 확인된 부재 날짜들, ai = {단계: ai_out 객체}, fam_names = {문서군 키: 정제 이름}(확장자군 판정),
    fallback = (stage, item, ns) → 답(브리지 단계 `fallback()` 한 벌 — 없으면 `lm27.bridge.stages` 를 찾아 쓴다)."""
    bc = cal if isinstance(cal, F.BizCal) else F.BizCal.from_cfg(cal, cfg)
    if as_of is None:
        as_of = _get(run_meta, "as_of")
    as_of_min = parse_local(as_of)
    env, alloc = read_tables(tables)
    slot_tags, days = _slot_rows(env_slots)
    rows = list(attrib or ())
    cells = obs_split(alloc, rows, slot_tags)
    units = make_units(tasks, labels, alloc, cells, bc)
    if as_of_min is None:
        last = [u.end for u in units.values() if u.end is not None] + [date_lmin(d) + F.DAY_MIN - 1 for d in env]
        as_of_min = max(last) if last else 0
    log = build_activity(list(units.values()), rows)
    for r in day_ledger or ():
        d = str(_get(r, "date", "") or "")
        if not d:
            continue
        df = days.setdefault(d, DayFacts())
        cov = _get(r, "coverage", {}) or {}
        df.coverage = {str(k): str(v) for k, v in cov.items()}
        if not df.env_min:
            df.env_min = int(_get(r, "total_min", 0) or 0)
            df.by_tag = dict(_get(r, "by_tag_min", {}) or {})
            cm = _get(r, "conf_min", {}) or {}
            df.conf_min = {k: int(cm.get(k, 0) or 0) for k in ("high", "mid", "low")}
    for d, e in env.items():
        df = days.setdefault(d, DayFacts())
        tot = sum(e.values())
        if tot != df.env_min:
            df.env_min = tot
            df.by_tag = dict(e)
    for d, cov in (coverage or {}).items():
        days.setdefault(str(d), DayFacts()).coverage = {str(k): str(v) for k, v in cov.items()}
    for d, v in (leaves or {}).items():
        lv = {"full": 1.0, "am": 0.5, "pm": 0.5}.get(v, v) if isinstance(v, str) else v
        days.setdefault(str(d)[:10], DayFacts()).leave = float(lv or 0.0)
    for d in absences or ():
        days.setdefault(str(d)[:10], DayFacts()).absence = True
    d0, d1 = _period(period, env, as_of_min)
    warnings = []
    if log.coarse:
        warnings.append(V.warn("mining_coarse"))
    if not labels and tasks:                       # 단위업무 0개면 분류 결과가 빈 것이 정상(units_empty 가 알린다 — L03)
        warnings.append(V.warn("labels_missing"))
    if registry is None:
        warnings.append(V.warn("registry_missing"))
    cv_run, cv_now = str(_get(run_meta, "calendar_version", "") or ""), str(getattr(cal, "version", "") or "")
    if isinstance(cal, F.BizCal):
        cv_now = str(getattr(cal.cal, "version", "") or "")
    if cv_run and cv_now and cv_run != cv_now:            # R §11 — 숫자는 시간 결과 그대로, 경고만
        warnings.append(V.warn("calendar_mismatch", analysis=cv_run, current=cv_now))
    ctx = AnalysisCtx(cfg=cfg, bc=bc, units=units, log=log, env=env, alloc=alloc, cells=cells, days=days,
                      as_of_min=int(as_of_min), d0=d0, d1=d1, registry=registry, person_dir=person_dir,
                      evidence=evidence, ai=_ai_items(ai), fam_ext=_fam_ext(fam_names, cfg),
                      catalog=_catalog(registry), fallback=fallback, warnings=warnings, run_id=str(run_id or ""))
    return ctx
