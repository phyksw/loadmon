# -*- coding: utf-8 -*-
r"""슬롯 귀속 L1~L7 — 시간 코어 B(W §5 · 부록 A `attribute.py`, 계약 §2.9 · §3.14 attrib.jsonl · §5.3 · §6.4 · C21).

`attribute(ev, env, tasks, days, cfg) -> (assign, level)` · `attribute_full(...) -> Attribution` · `resolve(fam_key, t, ctx)`

- 보존 법칙(W §5.1 · T-01): 봉투 슬롯 하나 = 정수 300초. 슬롯마다 `split_int(300, 가중)` 으로 단위업무·버킷에
  정수 초로 나누고, **날마다 Σ귀속 초 = 300 × 봉투 슬롯 수**를 확인한다. 어기면 `ConservationError`(분석 중단 —
  결과·팀 묶음을 만들지 않는다, fail-closed).
- 우선순위 사슬(W §5.3): L1 수동 > L2 회의(대형 분할·불참 의심) > L3 PC 맥락(다중 PC 최소 유휴·원격 데스크톱 양보·
  동률 균등, 점 사건 가중) > L4 앵커 직전 창 > L5 흡수·솔버 흡수·공백·하한 근접 > L6 직접 증거 비례(그날 상한) >
  L7 버킷 5종. 단계 값은 계약 §6.4 의 13종 문자열 그대로다.
- 정수 동률은 계약 §5.3 · X-208 규칙(`intervals.split_int` — 단위업무 `u_` 먼저, 키 사전순).
- `attrib.jsonl` 행(계약 §3.14 + C21): `{slot, target, sec, level, obs, app, fam}`. `obs` 는 **단계 코드 문자열**
  (`lm27.vocab.steps.obs_of` — '' = 단계 아님, R §3.3), `app` = 그 슬롯·그 대상의 최다 app_id, `fam` = 최다 문서군 키.
  대형 분할 회의 슬롯에서 다른 업무가 받은 몫은 그 업무의 PC 조각(L3) 근거로 단계를 정한다.

참조 `worktime_sim.py` Attributor 를 옮겨 계약 이름·정수 단위로 바꿨다. 표준 라이브러리 + `lm27.vocab.steps`.
파일을 쓰지 않는다.
"""
from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field

from lm27.time.calendar import SLOT, d_of, day0
from lm27.time.episodes import APP_TASK_CLS, Cycle, TaskCtx, UnitTask
from lm27.time.intervals import IvIx, split_int
from lm27.time.tokens import tok_sim
from lm27.vocab.steps import ext_class, obs_of

__all__ = [
    "BUCKET",
    "BUCKETS",
    "LEVELS",
    "Attribution",
    "ConservationError",
    "attribute",
    "attribute_full",
    "grade_of_level",
    "level_code",
    "resolve",
]

MIN = 60
BUCKETS = ("B_GENERIC", "B_COMM", "B_MEET", "B_OFFPC", "B_UNKNOWN")
BUCKET = {"generic": "B_GENERIC", "comm": "B_COMM", "offpc": "B_OFFPC", "unknown": "B_UNKNOWN", "meet": "B_MEET"}
LV_L1, LV_L2, LV_L2_BIG, LV_L2_ABS = "L1", "L2회의", "L2회의(대형분할)", "L2회의(불참의심)"
LV_L3, LV_L4, LV_L4_CAP = "L3PC", "L4앵커", "L4솔버cap"
LV_L5_ABS, LV_L5_SOLVER, LV_L5_GAP, LV_L5_NEAR = "L5흡수", "L5솔버흡수", "L5공백", "L5하한근접"
LV_L6, LV_L7 = "L6비례", "L7버킷"
LEVELS = (LV_L1, LV_L2, LV_L2_BIG, LV_L2_ABS, LV_L3, LV_L4, LV_L4_CAP, LV_L5_ABS, LV_L5_SOLVER, LV_L5_GAP,
          LV_L5_NEAR, LV_L6, LV_L7)                                       # 계약 §6.4 귀속 단계 13종
OBSERVED = frozenset({LV_L1, LV_L2, LV_L3})                                # 분 등급 O(W §7.1)
COMM_CLS = frozenset({"mail", "chat", "meet"})
END_PAD = frozenset({"E1", "E1d", "E1i", "E2h", "E2l", "E3c"})            # 끝 뒤 마무리 창(postPadMin)
_ANCHOR_OBS = {"sent": "send", "commit": "commit", "submit": "submit"}


class ConservationError(AssertionError):
    """보존 법칙 위반(Σ귀속 초 ≠ 300 × 봉투 슬롯) — 코드 결함, 분석 중단(T-01)."""


def level_code(level: str) -> str:
    """'L2회의(대형분할)' → 'L2'. tasks.json levels_s 의 키."""
    return str(level)[:2]


def grade_of_level(level: str, target: str) -> str:
    """분 등급(W §7.1): 버킷 X, 관측 귀속(L1·L2 전체·L3) O, 그 밖 I."""
    if str(target).startswith("B_"):
        return "X"
    return "O" if level in OBSERVED else "I"


@dataclass
class Attribution:
    """귀속 결과. assign = {슬롯: {대상: 초}}, level = {슬롯: 단계}, stype = {슬롯: 관측 유형},
    obs = {슬롯: {대상: (단계 코드, app_id, 문서군 키)}}, win = {unit_id: 업무 창 색인}."""
    assign: dict[int, dict[str, int]]
    level: dict[int, str]
    stype: dict[int, str]
    obs: dict[int, dict[str, tuple[str, str, str]]]
    win: dict[str, IvIx]
    start: dict[str, int]
    absent: list = field(default_factory=list)          # 불참 의심 회의(Q14)
    meet_slot: dict[int, tuple] = field(default_factory=dict)   # 슬롯 → (회의, 회의 대상)

    def effort(self) -> Counter:
        """대상(unit_id·버킷)별 귀속 초."""
        out: Counter = Counter()
        for dist in self.assign.values():
            for k, v in dist.items():
                out[k] += v
        return out

    def effort_levels(self) -> dict[str, Counter]:
        """대상별 단계(L1~L7) 초."""
        out: dict[str, Counter] = defaultdict(Counter)
        for s, dist in self.assign.items():
            lv = level_code(self.level[s])
            for k, v in dist.items():
                out[k][lv] += v
        return out

    def rows(self) -> list[dict]:
        """attrib.jsonl 행(슬롯 · 대상 순)."""
        out = []
        for s in sorted(self.assign):
            info = self.obs.get(s, {})
            for k in sorted(self.assign[s]):
                ob, app, fam = info.get(k, ("", "", ""))
                out.append({"slot": s, "target": k, "sec": int(self.assign[s][k]), "level": self.level[s],
                            "obs": ob, "app": app, "fam": fam})
        return out


def task_windows(tasks, as_of: int, post_pad: int) -> dict[str, IvIx]:
    """업무 창(W §5.2): 차수 [시작, 끝 + pad] — pad 는 끝이 E1·E1d·E1i·E2·E3c 일 때만, 진행 중은 분석 시각까지."""
    win = {}
    for t in tasks:
        out = []
        for c in t.cycles:
            if c.unstarted or c.s is None:
                continue
            e = c.e if c.e is not None else as_of
            p = post_pad if c.eb in END_PAD else 0
            out.append((c.s, e + p))
        win[t.id] = IvIx(out)
    return win


def resolve(fam_key: str, t: int, ctx) -> dict[str, int] | str | None:
    """문서군 f 의 시각 t 사건 → {unit_id: 가중} · 'B_GENERIC'(공용 문서) · None(미연결)(W §5.2).

    ctx = `TaskCtx`(attribution 이 있어야 업무 창을 안다) 또는 `_Attributor`.
    창 안 업무가 여럿이면 연결 강도 최대인 업무들에 균등(최근 시작 쏠림 없음), 창 밖이면 그 전에 시작한 업무 중
    가장 늦게 시작한 것, 그것도 없으면 가장 일찍 시작한 것.
    """
    if isinstance(ctx, TaskCtx):
        att = ctx.attribution
        if att is None:
            raise ValueError("resolve: 귀속 문맥이 없다 — attribute() 뒤에 부른다")
        return _resolve(ctx, att.win, att.start, fam_key, t)
    return ctx.resolve(fam_key, t)


def _resolve(ctx: TaskCtx, win, start, f: str, t: int):
    sg = ctx.seg_at(f, t) if f else None
    if not sg or not sg.links:
        return None
    if sg.shared:
        return "B_GENERIC"
    links = sg.links
    inwin = [k for k in links if win[k].has(t)]
    if inwin:
        top = max(links[k] for k in inwin)
        return dict.fromkeys(sorted(k for k in inwin if links[k] == top), 1)
    before = [k for k in links if start[k] <= t]
    if before:
        return {max(before, key=lambda k: (start[k], k)): 1}
    return {min(links, key=lambda k: (start[k], k)): 1}


def attribute(ev, env, tasks, days: Mapping, cfg) -> tuple[dict[int, dict[str, int]], dict[int, str]]:
    """W 부록 A 형: (슬롯 → {업무|버킷: 초}, 슬롯 → 단계). 전체 결과는 `tasks.ctx.attribution`."""
    a = attribute_full(ev, env, tasks, days, cfg)
    return a.assign, a.level


def attribute_full(ev, env, tasks, days: Mapping, cfg) -> Attribution:
    """귀속 전체 결과(`Attribution`). tasks = `episodes.build_tasks` 결과(`.ctx` 필요). 수동 기록이 어떤 업무와도
    맞지 않으면 MANUAL 업무를 tasks 에 덧붙인다."""
    ctx = getattr(tasks, "ctx", None)
    if not isinstance(ctx, TaskCtx):
        raise TypeError("attribute: tasks 는 episodes.build_tasks 결과(TaskList)여야 한다")
    att = _Attributor(ev, env, tasks, days, cfg, ctx).run()
    ctx.attribution = att
    return att


class _Attributor:
    def __init__(self, ev, env, tasks, days, cfg, ctx: TaskCtx):
        self.ev, self.env, self.tasks, self.days, self.cfg, self.ctx = ev, env, tasks, days, cfg, ctx
        self.as_of = ev.as_of
        g = cfg.__getitem__
        self.post_pad = int(g("time.attrib.postPadMin")) * MIN
        self.pw = int(g("time.attrib.pointWeightSec"))
        self.split_min_att = int(g("time.attrib.meetSplitMinAtt"))
        self.split_share = float(g("time.attrib.meetSplitShare"))
        self.absent_cover = float(g("time.attrib.meetAbsentCover"))
        self.gap_max = int(g("time.attrib.gapSplitMaxMin")) // 5
        self.gmax = int(g("time.attrib.absorbGenericMaxMin")) // 5
        self.fnear = int(g("time.attrib.floorNearMin")) // 5
        self.solver_absorb = bool(g("time.attrib.solverAbsorbGeneric"))
        r = g("time.attrib.l6MaxRatio")
        self.l6_ratio = None if r is None else float(r)
        self.cover_sec = int(g("time.slotCoverSec"))
        self.win = task_windows(tasks, self.as_of, self.post_pad)
        self.start = {t.id: t.cycles[0].s for t in tasks}
        self.fam_ext = self._fam_ext()

    def resolve(self, f: str, t: int):
        return _resolve(self.ctx, self.win, self.start, f, t)

    def _fam_ext(self) -> dict[str, str]:
        """문서군 → 확장자군(파일 사건의 정제된 이름 확장자 최빈값 — 단계 코드 재료, 로컬 전용)."""
        cnt: dict[str, Counter] = defaultdict(Counter)
        for e in self.ev.docs:
            if e.fam and "." in e.raw:
                cnt[e.fam][e.raw.rsplit(".", 1)[-1].lower()] += 1
        out = {}
        for f, c in cnt.items():
            ext = sorted(c.items(), key=lambda x: (-x[1], x[0]))[0][0]
            out[f] = ext_class(ext)
        return out

    def _new_manual(self, m, key: str, label: str) -> UnitTask:
        uid = self.ctx.uid(key, "MANUAL")
        s = m.a if m.a is not None else day0(m.d)
        e = m.b if m.b is not None else day0(m.d) + 86400
        tk = UnitTask(id=uid, label=label, kind="MANUAL", first_key=key, tokens=set(m.tokens),
                      docs=({m.ref: 3} if m.ref else {}))
        c = Cycle(s, "S2M", s_ref="수동")
        c.e, c.eb, c.e_ref = e, "E3M", "수동"
        tk.cycles.append(c)
        tk.grade, tk.status = "M", "closed"
        if any(t.id == uid for t in self.tasks):
            raise ValueError("unit_id 충돌 — MANUAL 업무 키가 다른 업무와 같은 unit_id 가 됐다")
        self.tasks.append(tk)
        self.ctx.by_id[uid] = tk
        self.win[uid] = IvIx([(s, e)])
        self.start[uid] = s
        return tk

    def run(self) -> Attribution:
        cfg, env, ctx = self.cfg, self.env, self.ctx
        slots = sorted(env.slots)
        sset = set(slots)
        level: dict[int, str] = {}
        assign: dict[int, dict[str, int]] = {}
        stype: dict[int, str] = {}
        # ── L3 재료: 슬롯별 PC 조각(분 단위 맥락 — 다중 PC 최소 유휴·RDP 양보·동률 균등) ──
        pieces: dict[int, list] = defaultdict(list)
        for s in self.ev.samples:
            if s.state != "active" or s.priv in ("private", "social"):
                continue
            k = s.a // SLOT
            while k * SLOT < s.b:
                if k in sset:
                    x, y = max(s.a, k * SLOT), min(s.b, (k + 1) * SLOT)
                    if s.fam:
                        tgt = ("doc", s.fam)
                    elif s.cls in APP_TASK_CLS:
                        tgt = ("app", s.app)
                    elif s.cls == "remote":
                        tgt = ("remote", "")
                    elif s.cls in COMM_CLS:
                        tgt = ("comm", "")
                    else:
                        tgt = ("generic", "")
                    pieces[k].append((s.pc, x, y, tgt, s.idle or 0, s.cls, s.app, s.fam))
                k += 1
        L3: dict[int, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        OBS: dict[int, Counter] = defaultdict(Counter)
        inf3: dict[int, dict[str, dict[str, Counter]]] = defaultdict(lambda: defaultdict(
            lambda: {"cls": Counter(), "app": Counter(), "fam": Counter()}))
        slot_seen: dict[int, dict[str, Counter]] = defaultdict(lambda: {"app": Counter(), "fam": Counter()})
        for k in sorted(pieces):
            lst = pieces[k]
            cuts = sorted({p[1] for p in lst} | {p[2] for p in lst})
            for u, v in zip(cuts, cuts[1:], strict=False):
                cur = [p for p in lst if p[1] <= u and p[2] >= v]
                if not cur:
                    continue
                non_rdp_pcs = {p[0] for p in cur if p[3][0] != "remote"}
                cur = [p for p in cur if p[3][0] != "remote" or not (non_rdp_pcs - {p[0]})]
                mi = min(p[4] for p in cur)
                cur = [p for p in cur if p[4] == mi]
                by_pc: dict[str, list] = defaultdict(list)
                for p in cur:
                    by_pc[p[0]].append(p)
                share = (v - u) / len(by_pc)
                for pc in sorted(by_pc):
                    ps = by_pc[pc]
                    for p in ps:
                        w_ = share / len(ps)
                        typ, key = p[3]
                        _cls, app, fam = p[5], p[6], p[7]
                        if app:
                            slot_seen[k]["app"][app] += w_
                        if fam:
                            slot_seen[k]["fam"][fam] += w_
                        if typ == "doc":
                            r = self.resolve(key, u)
                            if r == "B_GENERIC":
                                OBS[k]["shared"] += w_
                            elif r is None:
                                OBS[k]["generic"] += w_
                            else:
                                for tid in r:
                                    L3[k][tid] += w_ / len(r)
                                    self._note3(inf3, k, tid, p, w_ / len(r))
                        elif typ == "app":
                            tid = None
                            for a, b, t in ctx.app_task.get(key, []):
                                if a <= u < b + 1:
                                    tid = t
                            if tid:
                                L3[k][tid] += w_
                                self._note3(inf3, k, tid, p, w_)
                            else:
                                OBS[k]["generic"] += w_
                        elif typ == "remote":
                            OBS[k]["generic"] += w_
                        else:
                            OBS[k][typ] += w_
        for e in self.ev.docs:                        # 점 사건(저장·내보내기) 가중
            if e.autosave or e.kind in ("open", "result") or e.other:
                continue
            k = e.t // SLOT
            if k in sset:
                r = self.resolve(e.fam, e.t)
                if isinstance(r, dict):
                    for tid in r:
                        L3[k][tid] += self.pw / len(r)
                        self._note_point(inf3, k, tid, e.fam, self.pw / len(r), "")
        for c in self.ev.commits:
            k = c.t // SLOT
            if k in sset:
                r = self.resolve(c.fam, c.t)
                if isinstance(r, dict):
                    for tid in r:
                        L3[k][tid] += self.pw / len(r)
                        self._note_point(inf3, k, tid, c.fam, self.pw / len(r), "ide")
        # ── L4: 앵커 직전 창 ──
        L4: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        L4obs: dict[int, Counter] = defaultdict(Counter)
        inf4: dict[int, dict[str, Counter]] = defaultdict(lambda: defaultdict(Counter))
        for a, b, kind, ref, t in env.anchor_sessions:
            tgt = None
            akind, afam, aapp = _ANCHOR_OBS.get(kind, kind), "", ""
            if kind == "sent":
                tid = ctx.msg_task.get(ref.id)
                if tid:
                    tgt = {tid: 1}
                else:
                    for f in ref.atts:
                        r = self.resolve(f, t)
                        if isinstance(r, dict):
                            tgt = r
                            break
                afam = ref.atts[0] if ref.atts else ""
            elif kind == "save":
                r = self.resolve(ref.fam, t)
                tgt = r if isinstance(r, dict) else None
                akind = "export" if ref.kind == "export" else "save"
                afam = ref.fam
            elif kind == "submit":
                if ref.fam:
                    r = self.resolve(ref.fam, t)
                    tgt = r if isinstance(r, dict) else None
                afam, aapp = ref.fam, ref.app
            elif kind == "commit":
                r = self.resolve(ref.fam, t)
                tgt = r if isinstance(r, dict) else None
                afam = ref.fam
            k = a // SLOT
            while k * SLOT < b:
                if k in sset:
                    sec = min(b, (k + 1) * SLOT) - max(a, k * SLOT)
                    if tgt:
                        for tid in tgt:
                            L4[k][tid] += sec // len(tgt)
                            inf4[k][tid][(akind, afam, aapp)] += sec // len(tgt)
                    else:
                        L4obs[k]["comm" if kind == "sent" else "generic"] += sec
                k += 1
        # ── L1: 수동 기록(업무 지정) ──
        L1: dict[int, str] = {}
        common = frozenset(self.ev.common_tokens)
        ml = int(cfg["episode.tokens.minSubLen"])
        for m in self.ev.manual:
            if m.kind != "work":
                continue
            f = m.ref or ""
            mt = set(m.tokens) - common
            tk = None
            for t in self.tasks:
                if (f and f in t.docs) or (mt and tok_sim(mt, set(t.tokens) - common, ml) >= 0.5):
                    tk = t
                    break
            if tk is None:
                key = f"manual:{f}" if f else "manual:t:" + _tok_digest(mt)
                tk = next((t for t in self.tasks if t.first_key == key), None)
                if tk is None:
                    tk = self._new_manual(m, key, "MANUAL:" + (f or key[len("manual:"):]))
            if m.a is not None and m.b is not None:
                for k in range(m.a // SLOT, (m.b - 1) // SLOT + 1):
                    if k in sset:
                        L1[k] = tk.id
            elif m.a is None:
                for k in env.manual_slots.get(m.id or m.key, ()):
                    if k in sset:
                        L1[k] = tk.id
        # ── L2: 회의(연결 업무 또는 B_MEET) — 대형 회의 분할·불참 의심 ──
        L2: dict[int, tuple[dict[str, int], str]] = {}
        attended = {m.ref for m in self.ev.manual if m.kind == "attended" and m.ref}
        absent = []
        meet_slot: dict[int, tuple] = {}
        for mt in env.counted_meetings:
            tgt = ctx.meet_task.get(mt.id, "B_MEET")
            ks = [k for k in range(mt.a // SLOT, (mt.b - 1) // SLOT + 1) if k in sset and
                  min(mt.b, (k + 1) * SLOT) - max(mt.a, k * SLOT) >= self.cover_sec]
            if not ks:
                continue
            other_total = sum(sum(v for tid, v in L3[k].items() if tid != tgt) for k in ks)
            is_absent = (mt.key not in attended and mt.id not in attended) and \
                other_total >= self.absent_cover * len(ks) * SLOT
            if is_absent:
                absent.append(mt)
            for k in ks:
                o = {tid: v for tid, v in L3[k].items() if tid != tgt and v > 0}
                os_ = min(SLOT, sum(o.values()))
                if is_absent and o:
                    w = dict(o)
                    w[tgt] = max(0.0, SLOT - os_)
                    L2[k] = (split_int(SLOT, w), LV_L2_ABS)
                elif o and mt.n_att >= self.split_min_att:
                    w = {tid: v * self.split_share for tid, v in o.items()}
                    w[tgt] = SLOT - os_ * self.split_share
                    L2[k] = (split_int(SLOT, w), LV_L2_BIG)
                else:
                    L2[k] = ({tgt: SLOT}, LV_L2)
                meet_slot[k] = (mt, tgt)
        # ── 슬롯 유형(버킷 분류용) ──
        basis = env.basis
        for k in slots:
            b = basis[k]
            obs = OBS.get(k)
            if b == "C2":
                stype[k] = "meet"
            elif obs and obs.get("shared", 0) >= max(obs.get("comm", 0), obs.get("generic", 0)) and \
                    obs.get("shared", 0) > 0:
                stype[k] = "shared"
            elif obs and sum(obs.values()) > 0:
                stype[k] = "comm" if obs.get("comm", 0) > obs.get("generic", 0) else "generic"
            elif b in ("C3", "C4"):
                o = L4obs.get(k)
                stype[k] = "comm" if (o and o.get("comm", 0) >= o.get("generic", 0)) else "generic"
            elif b == "C5":
                stype[k] = "comm"
            elif b in ("C1b", "C4L", "C6", "C7", "C10", "C10r"):
                stype[k] = "offpc"
            elif b in ("C8", "C8d", "C9", "C12"):
                stype[k] = "unknown"
            else:
                stype[k] = "generic"
        # ── 직접(L1~L4) ──
        for k in slots:
            if k in L1:
                assign[k], level[k] = {L1[k]: SLOT}, LV_L1
            elif k in L2:
                assign[k], level[k] = L2[k]
            elif k in L3 and sum(L3[k].values()) > 0:
                assign[k], level[k] = split_int(SLOT, dict(L3[k])), LV_L3
            elif k in L4 and sum(L4[k].values()) > 0:
                assign[k], level[k] = split_int(SLOT, dict(L4[k])), LV_L4
        direct = {k: v for k, v in assign.items() if not all(x.startswith("B_") for x in v)}

        def single(k):
            v = direct.get(k)
            if v and len(v) == 1:
                return next(iter(v))
            return None
        runs, cur = [], []
        for k in slots:
            if cur and k != cur[-1] + 1:
                runs.append(cur)
                cur = []
            cur.append(k)
        if cur:
            runs.append(cur)
        comp_all: dict[str, list] = defaultdict(list)
        for c in self.ev.comps:
            r = self.resolve(c.fam, c.a) if c.fam else None
            if isinstance(r, dict) and len(r) == 1:
                comp_all[next(iter(r))].append((c.a, c.b))
        comp_iv = comp_all if self.solver_absorb else {}
        cap_comp: dict[int, object] = {}
        # 솔버 cap 슬롯(옵션 C12)은 그 연산의 업무로
        for k in slots:
            if k not in assign and basis[k] == "C12":
                for tid in sorted(comp_all):
                    if any(a <= k * SLOT < b for a, b in comp_all[tid]):
                        assign[k], level[k] = {tid: SLOT}, LV_L4_CAP
                        cap_comp[k] = tid
                        break
        for run in runs:
            i = 0
            while i < len(run):
                if run[i] in assign:
                    i += 1
                    continue
                j = i
                while j < len(run) and run[j] not in assign:
                    j += 1
                block = run[i:j]
                left = run[i - 1] if i > 0 else None
                right = run[j] if j < len(run) else None
                ls, rs = (single(left) if left is not None else None), (single(right) if right is not None else None)
                ld = direct.get(left) if left is not None else None
                rd = direct.get(right) if right is not None else None
                types = {stype[k] for k in block}
                n = len(block)
                # L5a 흡수: 짧은 일반 앱·소통 블록이 같은 단일 업무 사이 / 솔버 대기 중 일반 앱은 솔버 업무
                if types <= {"generic", "comm"}:
                    if n <= self.gmax and ls and ls == rs:
                        for k in block:
                            assign[k], level[k] = {ls: SLOT}, LV_L5_ABS
                        i = j
                        continue
                    done = False
                    for tid in sorted(comp_iv):
                        ivs = comp_iv[tid]
                        if all(any(a <= k * SLOT < b for a, b in ivs) for k in block):
                            for k in block:
                                assign[k], level[k] = {tid: SLOT}, LV_L5_SOLVER
                            done = True
                            break
                    if done:
                        i = j
                        continue
                # L5b 공백: PC 밖(다리·흔적) — 짧으면 중점 분할, 길면 양쪽 같은 단일 업무만, 아니면 B_OFFPC
                if types <= {"offpc"}:
                    if ld or rd:
                        if n <= self.gap_max:
                            half = (n + 1) // 2 if (ld and rd) else (n if ld else 0)
                            for idx, k in enumerate(block):
                                src = ld if (idx < half and ld) else (rd if rd else ld)
                                assign[k], level[k] = dict(src), LV_L5_GAP
                        elif ls and ls == rs:
                            for k in block:
                                assign[k], level[k] = {ls: SLOT}, LV_L5_GAP
                        else:
                            for k in block:
                                assign[k], level[k] = {"B_OFFPC": SLOT}, LV_L7
                    else:
                        for k in block:
                            assign[k], level[k] = {"B_OFFPC": SLOT}, LV_L7
                    i = j
                    continue
                # L5c 하한 근접: PC 하한 슬롯은 floorNearMin 안의 가장 가까운 단일 업무
                for idx, k in enumerate(block):
                    if stype[k] != "unknown":
                        continue
                    dl = idx + 1 if ls else 10 ** 6
                    dr = n - idx if rs else 10 ** 6
                    if min(dl, dr) <= self.fnear:
                        assign[k], level[k] = {ls if dl <= dr else rs: SLOT}, LV_L5_NEAR
                i = j
        # ── L6 비례(직접 증거 초 비례, 창 열린 업무, 그날 상한 = 직접 × l6MaxRatio) → L7 버킷 ──
        day_direct: dict = defaultdict(lambda: defaultdict(int))
        for k, dist in direct.items():
            for tid, v in dist.items():
                if not tid.startswith("B_"):
                    day_direct[d_of(k * SLOT)][tid] += v
        used: dict = defaultdict(lambda: defaultdict(int))
        r = self.l6_ratio
        for k in slots:
            if k in assign:
                continue
            t = k * SLOT
            dd = d_of(t)

            def room(tid, dd=dd):
                return None if r is None else int(r * day_direct[dd][tid]) - used[dd][tid]
            wts = {tid: v for tid, v in day_direct[dd].items() if self.win[tid].has(t) and
                   (room(tid) is None or room(tid) > 0)}
            bucket = BUCKET.get(stype[k], "B_GENERIC")
            if stype[k] == "shared":                       # 공용 문서: 비례 배분하지 않고 근무 중 미분류
                assign[k], level[k] = {"B_GENERIC": SLOT}, LV_L7
                continue
            if wts:
                dist, out = split_int(SLOT, wts), {}
                for tid, v in dist.items():
                    rm = room(tid)
                    gv = v if rm is None else min(v, rm)
                    if gv > 0:
                        out[tid] = gv
                        used[dd][tid] += gv
                    if v - gv > 0:
                        out[bucket] = out.get(bucket, 0) + v - gv
                assign[k], level[k] = out, LV_L6
            else:
                assign[k], level[k] = {bucket: SLOT}, LV_L7
        # ── 보존 법칙(날마다 정수 초 — T-01, 실분석에서도 상시) ──
        env_day, att_day = Counter(), Counter()
        for k in slots:
            env_day[d_of(k * SLOT)] += SLOT
            v = assign.get(k)
            if not v or any((not isinstance(x, int)) or x < 0 for x in v.values()):
                raise ConservationError(f"보존 위반: 슬롯 {k} 귀속 형 오류")
            att_day[d_of(k * SLOT)] += sum(v.values())
        bad = sorted((d, env_day[d], att_day[d]) for d in env_day if env_day[d] != att_day[d])
        if bad or set(assign) != sset:
            raise ConservationError(f"보존 위반(Σ귀속 초 ≠ 300 × 슬롯): {bad[:3]}")
        obs = self._obs_rows(slots, assign, level, inf3, inf4, slot_seen, meet_slot, cap_comp)
        return Attribution(assign, level, stype, obs, self.win, self.start, absent, meet_slot)

    # --- 단계 코드·앱·문서군(attrib.jsonl obs·app·fam — C21) ---
    @staticmethod
    def _note3(inf3, k, tid, p, w):
        d = inf3[k][tid]
        d["cls"][p[5] or ""] += w
        if p[6]:
            d["app"][p[6]] += w
        if p[7]:
            d["fam"][p[7]] += w

    @staticmethod
    def _note_point(inf3, k, tid, fam, w, cls):
        """점 사건(저장·커밋) 가중 — 저장은 문서군 확장자로(cls ''), 커밋은 코드 작업(cls 'ide')으로 단계를 정한다."""
        d = inf3[k][tid]
        d["cls"][cls] += w
        if fam:
            d["fam"][fam] += w

    def _l3_obs(self, d) -> tuple[str, str, str]:
        cls = _top(Counter({k: v for k, v in d["cls"].items() if k})) or ""
        fam = _top(d["fam"]) or ""
        app = _top(d["app"]) or ""
        return obs_of("L3", cls, self.fam_ext.get(fam, ""), None, None), app, fam

    def _review(self, mt, tid: str) -> bool:
        tk = self.ctx.by_id.get(tid)
        if tk is None:
            return False
        for m2, rv in tk.meet_refs:
            if m2.id == mt.id and rv:
                return True
        return any(c.s_ref == mt.id or c.e_ref == mt.id for c in tk.cycles)

    def _obs_rows(self, slots, assign, level, inf3, inf4, slot_seen, meet_slot, cap_comp):
        out: dict[int, dict[str, tuple[str, str, str]]] = {}
        comp_app = {}
        for c in self.ev.comps:
            if c.fam:
                comp_app.setdefault(c.fam, c.app)
        for k in slots:
            lv = level[k]
            lc = level_code(lv)
            seen = slot_seen.get(k)
            seen_app = (_top(seen["app"]) or "") if seen else ""
            seen_fam = (_top(seen["fam"]) or "") if seen else ""
            row = {}
            for tid in assign[k]:
                if tid.startswith("B_"):
                    row[tid] = ("", seen_app, seen_fam)
                    continue
                if lc == "L1":
                    row[tid] = (obs_of("L1", None, "", None, None), "", "")
                elif lc == "L2":
                    mt, mtgt = meet_slot.get(k, (None, None))
                    if tid == mtgt and mt is not None:
                        role = "review" if self._review(mt, tid) else None
                        row[tid] = (obs_of("L2", "meet", "", None, role), "", "")
                    elif tid in inf3.get(k, {}):
                        row[tid] = self._l3_obs(inf3[k][tid])
                    else:
                        row[tid] = ("", "", "")
                elif lc == "L3":
                    d = inf3.get(k, {}).get(tid)
                    row[tid] = self._l3_obs(d) if d else ("", "", "")
                elif lv == LV_L4_CAP:
                    fam = ""
                    for c in self.ev.comps:
                        if c.fam and cap_comp.get(k) == tid and c.a <= k * SLOT < c.b:
                            fam = c.fam
                            break
                    row[tid] = (obs_of("L4", None, "", "solver", None), comp_app.get(fam, ""), fam)
                elif lc == "L4":
                    cnt = inf4.get(k, {}).get(tid)
                    if cnt:
                        (akind, afam, aapp), _sec = sorted(cnt.items(), key=lambda x: (-x[1], x[0]))[0]
                        row[tid] = (obs_of("L4", None, self.fam_ext.get(afam, ""), akind, None), aapp, afam)
                    else:
                        row[tid] = ("", "", "")
                else:                                   # L5·L6 — 관측 단계 없음(R §4.1.3)
                    row[tid] = ("", seen_app, seen_fam)
            out[k] = row
        return out


def _top(c: Counter) -> str | None:
    if not c:
        return None
    return sorted(c.items(), key=lambda x: (-x[1], x[0]))[0][0]


def _tok_digest(toks: set) -> str:
    """토큰만 있는 수동 기록의 MANUAL 업무 키 재료(원문 대신 해시 — 결과 파일에 낱말을 남기지 않는다)."""
    return hashlib.sha256("\x1f".join(sorted(toks)).encode("utf-8")).hexdigest()[:16]
