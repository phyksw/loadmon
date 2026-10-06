# -*- coding: utf-8 -*-
r"""확인 큐 Q01~Q18 — 시간 코어 B(W §7.3 · 부록 A `queue.py`, 계약 §2.9 · §3.14 confirm_queue.json · §4.1 qid · §6.3).

- `QueueItem` = 질문 하나. 파일 행(`to_row()`)은 계약 §3.14 열 그대로 `{qid, code, target, impact_min, evidence_keys,
  proposal, status}` 이다. 시간량은 정수 분(`impact_min`)이고 원문은 없다 — `target` 은 unit_id·로컬 날짜·회의 키·
  문서군 키뿐, `evidence_keys` 는 증거 키(msg_key·문서군 키·회의 키)뿐, `proposal` 은 고정 한국어 문구와 선택지·
  응답 종류(`Man.kind`)·날짜다.
- `qid = sha1("코드|대상|핵심 근거")[:12]`(계약 §4.1) — 같은 입력이면 같은 질문은 같은 ID(두 번 묻지 않는다, W-G12).
- `prioritize(items, cfg)`: 우선순위 = (영향 h + 0.01) × 유형 가중(W §7.3), ISO 주마다 상위 `time.queue.maxPerWeek`
  건만 `status = "open"`, 나머지는 `"deferred"`(T-23 주당 노출 ≤ 상한). 결정적(동률 = qid 순).
- `make_queue(...)`: 봉투·업무·귀속에서 질문을 만든다(Q01·Q03·Q04·Q05·Q06·Q08·Q09·Q10·Q11·Q12·Q13·Q14·Q15·Q16·Q17).
  Q02·Q03(커버리지 보류)·Q07·Q12(거대 성분)·Q18 은 단위업무 형성(`episodes.build_tasks`)이 만든다.

표준 라이브러리만 쓴다. 파일을 쓰지 않는다.
"""
from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date

from lm27.time.calendar import DAY, SLOT, d_of, day0
from lm27.time.intervals import I, L, SUB, U

__all__ = [
    "CODES",
    "QW",
    "QueueItem",
    "make_item",
    "make_queue",
    "prioritize",
    "qid_of",
]

MIN, HOUR = 60, 3600
CODES = tuple(f"Q{i:02d}" for i in range(1, 19))
# 유형 가중(W §7.3 — 낮은 신뢰일수록 큼)
QW = {"Q01": 1.0, "Q02": 0.3, "Q03": 0.8, "Q04": 0.6, "Q05": 0.9, "Q06": 0.9, "Q07": 0.2, "Q08": 0.7, "Q09": 1.0,
      "Q10": 0.5, "Q11": 0.1, "Q12": 0.4, "Q13": 1.0, "Q14": 0.6, "Q15": 0.4, "Q16": 0.5, "Q17": 0.6, "Q18": 0.5}
# 묻는 것·선택지·응답 → 저장(Man.kind) — W §7.3 표(고정 문구, 원문 없음)
ASK = {
    "Q01": ("업무 경계 확인", ("언제 지시받았나", "언제 보고했나", "같은 업무 합치기"), ("instr", "report", "must_link")),
    "Q02": ("미착수 의뢰", ("착수 안 함", "다른 업무에 포함", "오프라인 처리(시각·h)"), ("must_link", "work")),
    "Q03": ("오래 열림·보류", ("끝났나(시각)", "진행 중"), ("report",)),
    "Q04": ("원격 발신", ("업무로 보냈나", "사적"), ("exclude",)),
    "Q05": ("흔적 창·미등록 외근", ("외근·출장·현장이었나(시각)", "정정"), ("offsite", "work", "exclude")),
    "Q06": ("date-only 게이트", ("근무했나·몇 h",), ("work", "exclude")),
    "Q07": ("요약 근거", ("가리키는 의뢰·보고 시각",), ("instr", "report")),
    "Q08": ("근무창 공백", ("오프라인 업무였나(시각·업무)",), ("work",)),
    "Q09": ("추정 부재", ("부재였나", "근무(수동 입력)"), ("absence", "work")),
    "Q10": ("장시간일", ("맞나",), ("exclude",)),
    "Q11": ("솔버 대량", ("결과 확인 시간 기록(선택)",), ("work",)),
    "Q12": ("분할 제안·분할 과다", ("나눌까요", "합칠까요"), ("cannot_link", "must_link")),
    "Q13": ("UTC 저장 의심", ("그 경로가 UTC 저장인가",), ()),
    "Q14": ("회의 불참 의심", ("참석했나",), ("attended",)),
    "Q15": ("미정 회의", ("참석했나",), ("attended",)),
    "Q16": ("휴가 중 근무", ("근무 맞나",), ("exclude",)),
    "Q17": ("미귀속 블록", ("어느 업무(후보 3개)", "개인 시간"), ("work", "exclude")),
    "Q18": ("공용 문서 의심", ("공용 문서로 등록", "특정 업무 것"), ("must_link",)),
}
STATUS_OPEN, STATUS_DEFERRED = "open", "deferred"


def qid_of(code: str, target: str, core: str = "") -> str:
    """질문 ID(계약 §4.1): sha1('코드|대상|핵심 근거')[:12]."""
    return hashlib.sha1(f"{code}|{target}|{core}".encode()).hexdigest()[:12]


@dataclass
class QueueItem:
    """확인 질문 하나(W 부록 A `QueueItem` — 시간량은 정수 분 `impact_min`, 계약 §3.14)."""
    qid: str
    code: str
    target: str
    impact_min: int
    evidence_keys: list[str] = field(default_factory=list)
    proposal: dict = field(default_factory=dict)
    status: str = STATUS_OPEN
    day: str | None = None             # 주(ISO) 계산용 로컬 날짜 — 파일에는 proposal.date 로 실린다

    def to_row(self) -> dict:
        return {"qid": self.qid, "code": self.code, "target": self.target, "impact_min": int(self.impact_min),
                "evidence_keys": list(self.evidence_keys), "proposal": dict(self.proposal), "status": self.status}


def make_item(code: str, target: str, core: str = "", *, impact_min: int | None = None,
              evidence_keys: Iterable[str] = (), day: date | str | None = None, note: str = "") -> QueueItem:
    """질문 하나를 만든다. `core` = 핵심 근거(키·시각 등 — qid 재료), `note` = 숫자·코드만 담은 한 줄 설명."""
    if code not in ASK:
        raise ValueError(f"확인 큐 코드 오류 {code!r}")
    title, options, answers = ASK[code]
    d = day.isoformat() if isinstance(day, date) else (str(day) if day else None)
    prop = {"title": title, "options": list(options), "answer_kinds": list(answers)}
    if d:
        prop["date"] = d
    if note:
        prop["note"] = note
    keys = sorted({str(k) for k in evidence_keys if k})
    return QueueItem(qid_of(code, str(target), str(core)), code, str(target),
                     60 if impact_min is None else max(0, int(impact_min)), keys, prop, STATUS_OPEN, d)


def _week(item: QueueItem) -> str:
    if item.day:
        try:
            y, w, _ = date.fromisoformat(item.day).isocalendar()
            return f"{y}-W{w:02d}"
        except ValueError:
            return "-"
    return "-"


def prioritize(items: Iterable[QueueItem], cfg) -> list[QueueItem]:
    """노출 선택(W §7.3): 같은 qid 는 하나만, 우선순위 순으로 ISO 주마다 `time.queue.maxPerWeek` 건까지 open.

    반환 = 중복을 뺀 전체 목록(우선순위 순). 각 항목의 `status` 를 open·deferred 로 정한다.
    """
    cap = int(cfg["time.queue.maxPerWeek"])
    seen: dict[str, QueueItem] = {}
    for it in items:
        if it.qid not in seen:
            seen[it.qid] = it
    rows = sorted(seen.values(), key=lambda x: (-(x.impact_min / 60 + 0.01) * QW.get(x.code, 0.5), x.qid))
    per: Counter = Counter()
    for it in rows:
        wk = _week(it)
        if per[wk] >= cap:
            it.status = STATUS_DEFERRED
            continue
        per[wk] += 1
        it.status = STATUS_OPEN
    return rows


# ───────────────────────────── 질문 만들기 ─────────────────────────────
def _hm(s: str) -> tuple[int, int]:
    a, b = str(s).strip().split("-")
    h0, m0 = a.split(":")
    h1, m1 = b.split(":")
    return int(h0) * HOUR + int(m0) * MIN, int(h1) * HOUR + int(m1) * MIN


def _fmt(t: int) -> str:
    d = d_of(t)
    m = (t - day0(d)) // MIN
    return f"{d.month:02d}-{d.day:02d} {m // 60:02d}:{m % 60:02d}"


def _wd(cal, d1: date, d2: date) -> int:
    """(d1, d2] 근무일 수 — 달력에 없는 해는 요일 규칙으로(분석 거부는 build_days 몫)."""
    try:
        return int(cal.wd_between(d1, d2))
    except ValueError:
        n, d = 0, d1
        wds = getattr(cal, "weekdays", frozenset({0, 1, 2, 3, 4}))
        while d < d2:
            d = date.fromordinal(d.toordinal() + 1)
            n += 1 if d.weekday() in wds else 0
        return n


def make_queue(ev, cfg, env, tasks, days: Mapping, effort: Mapping, assign: Mapping, attrib_ctx=None, *,
               cal=None, parallel: Mapping | None = None) -> list[QueueItem]:
    """W §7.3 발생 조건으로 질문을 만든다(정렬·노출은 `prioritize`). 원문 없음 — 키·날짜·정수 분만.

    effort = {unit_id|버킷: 귀속 초}, assign = {슬롯: {대상: 초}}, attrib_ctx = `attribute.Attribution`(불참 의심 회의),
    cal = 달력(Q03 근무일 계산), parallel = {unit_id: 병행도}(Q12 분할 과다).
    """
    q: list[QueueItem] = []
    min_eff = float(cfg["time.queue.minEffortH"]) * HOUR
    open_long = int(cfg["time.queue.openLongWd"])
    solver_day = float(cfg["time.queue.solverDayH"]) * HOUR
    gap_min = int(cfg["time.queue.gapMin"]) * MIN
    run_min = int(cfg["time.queue.bucketRunMin"])
    par_max = float(cfg["time.queue.parallelSuspect"])
    long_day = float(cfg["time.envelope.longDayH"]) * 60
    half_am = _hm(cfg["time.window.halfAmOff"])
    half_pm = _hm(cfg["time.window.halfPmOff"])
    as_of_d = d_of(ev.as_of)
    for tk in tasks:
        eff = int(effort.get(tk.id, 0))
        c0, cl = tk.cycles[0], tk.cycles[-1]
        start_d = d_of(c0.s) if c0.s is not None else as_of_d
        if tk.grade in ("C", "D", "E") and eff >= min_eff:
            q.append(make_item("Q01", tk.id, f"{c0.sb}>{cl.eb}", impact_min=eff // MIN,
                               evidence_keys=(tk.first_key,), day=start_d, note=f"등급 {tk.grade} · {c0.sb}→{cl.eb}"))
        if tk.status == "open" and tk.kind != "MANUAL" and cal is not None and \
                _wd(cal, start_d, as_of_d) >= open_long:
            q.append(make_item("Q03", tk.id, "open_long", impact_min=eff // MIN, evidence_keys=(tk.first_key,),
                               day=start_d, note=f"진행 중 {open_long}근무일 이상"))
        if tk.machine_s > solver_day:
            q.append(make_item("Q11", tk.id, "solver", impact_min=eff // MIN, evidence_keys=(tk.first_key,),
                               day=start_d, note=f"기계 {tk.machine_s // MIN}분(MM 미포함)"))
        pv = (parallel or {}).get(tk.id)
        if pv is not None and pv > par_max:
            q.append(make_item("Q12", tk.id, "parallel", impact_min=eff // MIN, evidence_keys=(tk.first_key,),
                               day=start_d, note=f"병행도 {pv:.1f}"))
    for d, fl in sorted(env.flags.items()):
        for f in fl:
            if "원격발신 " in f and "흔적" not in f:
                q.append(make_item("Q04", d.isoformat(), f, day=d, note=f))
            elif "흔적창" in f:
                q.append(make_item("Q05", d.isoformat(), f, day=d, note=f))
            elif "date-only 게이트" in f:
                q.append(make_item("Q06", d.isoformat(), f, day=d, note=f))
    if ev.utc_suspect:
        q.append(make_item("Q13", "-", "utc", note="정밀 발신의 00~08시 비율이 문턱 이상 — time.envelope.mailTimeOffsetH 확인"))
    for mt in getattr(attrib_ctx, "absent", ()) or ():
        q.append(make_item("Q14", mt.key or mt.id, "absent", evidence_keys=(mt.key,), day=d_of(mt.a),
                           impact_min=(mt.b - mt.a) // MIN, note="회의 중 다른 업무 PC 능동 입력"))
    for mt in env.tentative_unconfirmed:
        q.append(make_item("Q15", mt.key or mt.id, "tentative", evidence_keys=(mt.key,), day=d_of(mt.a),
                           impact_min=(mt.b - mt.a) // MIN, note="참석 근거 부족 — 미산입"))
    slots = env.slots
    env_iv = U([(s * SLOT, (s + 1) * SLOT) for s in slots])
    msg_days = Counter(d_of(m.t) for m in ev.msgs)
    for d, info in sorted(days.items()):
        if not info["in_range"]:
            continue
        z = day0(d)
        D_ = [(z, z + DAY)]
        if info["lv"] in ("full", "am", "pm") and not info["hol"]:
            if info["lv"] == "full":
                lw = D_
            else:
                a, b = half_am if info["lv"] == "am" else half_pm
                lw = [(z + a, z + b)]
            on_leave = L(I(env_iv, lw))
            if on_leave:
                q.append(make_item("Q16", d.isoformat(), info["lv"], impact_min=on_leave // MIN, day=d,
                                   note=f"휴가 중 근무 {on_leave // MIN}분"))
        if not info["S"]:
            continue
        if not I(env_iv, D_):
            if not env.flags.get(d) and not info["confirmed_absence"]:
                n = msg_days.get(d, 0)
                q.append(make_item("Q09", d.isoformat(), "absence", day=d, impact_min=sum(b - a for a, b in info["S"])
                                   // MIN, note=(f"존재 증거만 {n}건" if n else "근거 0") + " — 확인 전 가용에서 빼지 않음"))
            continue
        for a, b in SUB(SUB(info["S"], info["lunch"]), env_iv):
            if b - a >= gap_min:
                q.append(make_item("Q08", d.isoformat(), f"{a}-{b}", impact_min=(b - a) // MIN, day=d,
                                   note=f"{_fmt(a)}~{_fmt(b)[6:]}"))
    by_day: Counter = Counter()
    for s in slots:
        by_day[d_of(s * SLOT)] += SLOT // MIN
    for d, mins in sorted(by_day.items()):
        if mins > long_day:
            q.append(make_item("Q10", d.isoformat(), "long", impact_min=mins, day=d, note=f"하루 봉투 {mins}분"))
    run, cur = [], []
    for s in sorted(slots):
        dist = assign.get(s, {})
        b = [k for k in dist if str(k).startswith("B_")]
        if b and sum(dist[k] for k in b) == SLOT:
            if cur and s != cur[-1] + 1:
                run.append(cur)
                cur = []
            cur.append(s)
        else:
            if cur:
                run.append(cur)
            cur = []
    if cur:
        run.append(cur)
    for r in run:
        mins = len(r) * (SLOT // MIN)
        if mins >= run_min:
            d = d_of(r[0] * SLOT)
            q.append(make_item("Q17", d.isoformat(), str(r[0]), impact_min=mins, day=d,
                               note=f"{_fmt(r[0] * SLOT)} {mins}분"))
    return q
