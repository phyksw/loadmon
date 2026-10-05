# -*- coding: utf-8 -*-
r"""근무 봉투 — 5분 슬롯 합집합(W §3 · 부록 A `envelope.py`, 계약 §2.9 · §3.14 env_slots·day_ledger · D-9 · D-16).

`build_envelope(ev, cfg, days) -> Envelope`

- 봉투 = 구성요소 C1~C12 의 **합집합**을 5분 슬롯으로 양자화(슬롯 안 ≥ `time.slotCoverSec`)한 것. 그 뒤 수신
  크레딧(C5)을 '아직 봉투가 아닌 슬롯'에만 후선택하고, **마지막 단계에서** 사적 사용(P R-P3·R-P4)·개인 일정(R-P5)·
  사용자 제외를 차감한다(R-P9 · D-16). 여러 PC·경로의 같은 슬롯은 한 번만 센다.
- 샘플러 권위는 부정 증거로만 행사한다(단조성 W §3.12): 양성 증거를 더하면 봉투가 줄지 않고, PC 가동(L0/L1)
  기록을 빼면 늘지 않는다(관문 G3).
- date·summary·unknown 정밀도는 시간 근거가 아니다(T-09). `time.envelope.dateOnlyGate` 를 켤 때만 date-only 발신이
  그날 PC 하한의 게이트가 된다(C8d, 낮은 신뢰).
- 설명 원장(`Envelope.ledger`)은 날짜 → 항목 → **정수 초**, `ledger_n` 은 같은 항목의 건수다. 항목 이름은 W §7.4 ·
  X-215 표기(`사적차감`·`개인일정차감`·`사용자제외`·`창밖_무자격_제외` …, 구성요소 기여는 `봉투_C1` …). 내용·앱 이름은
  담지 않는다(P R-P7).
- 꼬리표는 계약 코드 `regular` `extended` `night` `holiday`(배타 — `lm27.time.calendar.slot_tag`).

참조 구현 `worktime_sim.py` `envelope()` 를 옮겨 계약 설정 키·형·정수 단위로 바꿨다. 표준 라이브러리만 쓴다.
파일을 쓰지 않는다.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from typing import NamedTuple

from lm27.time.calendar import DAY, SLOT, day0, d_of, slot_tag
from lm27.time.evidence import CODE_EXT, Evidence, Meet
from lm27.time.intervals import I, L, SUB, U, IvIx, pre_iv, pts_in, slot_cover

__all__ = [
    "CONF",
    "DEDUCT_ITEMS",
    "EXCLUDE_ITEMS",
    "NAMES",
    "PRIO",
    "Anchor",
    "AnchorSession",
    "Envelope",
    "RemoteSend",
    "build_envelope",
]

MIN, HOUR = 60, 3600
PRIO = ("C11", "C11u", "C2", "C1", "C3", "C4", "C1b", "C4L", "C6", "C7", "C8", "C8d", "C9", "C10", "C10r", "C12",
        "C5")
CONF = {"C11": "high", "C11u": "high", "C2": "high", "C1": "high", "C3": "high", "C4": "mid", "C1b": "mid",
        "C4L": "mid", "C5": "mid", "C6": "mid", "C7": "mid", "C8": "low", "C8d": "low", "C9": "low", "C10": "low",
        "C10r": "low", "C12": "low"}
NAMES = {"C1": "샘플러", "C1b": "샘플러다리", "C2": "회의", "C3": "앵커세션", "C4": "원격발신", "C4L": "원격연결다리",
         "C5": "수신크레딧", "C6": "사슬다리", "C7": "PC다리", "C8": "PC하한", "C8d": "date-only하한",
         "C9": "수신사슬하한", "C10": "흔적창", "C10r": "원격흔적창", "C11": "수동·종일외근", "C11u": "수동(시각없음)",
         "C12": "솔버cap"}
DEDUCT_ITEMS = ("사적차감", "개인일정차감", "사용자제외")                       # 마지막 단계 차감(봉투가 줄어듦)
EXCLUDE_ITEMS = ("창밖_무자격_제외", "창밖_골격밖_제외", "잠금단절_다리없음", "사적단절_다리없음", "점심차감",
                 "수신상한_제외")                                                 # 넣지 않은 시간(버린 시간)
ENV_PREFIX = "봉투_"
WORK_CLS = frozenset({"office", "cad", "cae", "sim", "eda", "ide", "eng"})   # W §3.1 업무 앱
PRE_KEYS = {"mail": "time.envelope.preWindowMin.mail", "teams": "time.envelope.preWindowMin.teams",
            "file": "time.envelope.preWindowMin.file", "code": "time.envelope.preWindowMin.code",
            "commit": "time.envelope.preWindowMin.commit", "submit": "time.envelope.preWindowMin.submit"}


class Anchor(NamedTuple):
    """능동 앵커 — (t, kind sent|save|commit|submit, 직전 창 초, PC 또는 None, 근거 객체)."""
    t: int
    kind: str
    pre_s: int
    pc: str | None
    ref: object


class AnchorSession(NamedTuple):
    """앵커 세션 조각 — (a, b, kind, 근거 객체, 앵커 시각)."""
    a: int
    b: int
    kind: str
    ref: object
    t: int


class RemoteSend(NamedTuple):
    """원격(휴대폰·웹) 발신 후보 — (t, 메시지, 직전 창)."""
    t: int
    ref: object
    iv: tuple[int, int]


@dataclass
class Envelope:
    """근무 봉투(W 부록 A `Envelope` + 구현 확장 — X-217). 슬롯 = 로컬 초 // 300."""
    slots: set[int]
    basis: dict[int, str]
    comp_cov: dict[str, dict[int, int]]
    ledger: dict[date, Counter]
    flags: dict[date, list[str]]
    anchors: list[Anchor]
    anchor_sessions: list[AnchorSession]
    counted_meetings: list[Meet]
    tentative_unconfirmed: list[Meet]
    reg: list[tuple[int, int]]
    ledger_n: dict[date, Counter] = field(default_factory=dict)
    s_all: list[tuple[int, int]] = field(default_factory=list)
    pts: list[int] = field(default_factory=list)
    remote_sends: list[RemoteSend] = field(default_factory=list)
    meet_iv: list[tuple[int, int]] = field(default_factory=list)
    cov: dict[str, list[tuple[int, int]]] = field(default_factory=dict)
    act: dict[str, list[tuple[int, int]]] = field(default_factory=dict)
    all_cov: list[tuple[int, int]] = field(default_factory=list)
    all_act: list[tuple[int, int]] = field(default_factory=list)
    manual_slots: dict[str, list[int]] = field(default_factory=dict)
    tags: dict[int, str] = field(default_factory=dict)
    on_leave: set[int] = field(default_factory=set)
    pcs: dict[int, tuple[str, ...]] = field(default_factory=dict)

    # 참조 구현 이름(하류 이식 편의)
    @property
    def led(self) -> dict[date, Counter]:
        return self.ledger

    @property
    def anchor_sess(self) -> list[AnchorSession]:
        return self.anchor_sessions

    @property
    def counted_meets(self) -> list[Meet]:
        return self.counted_meetings

    @property
    def tentative_q(self) -> list[Meet]:
        return self.tentative_unconfirmed

    def conf(self, s: int) -> str:
        """슬롯 신뢰 high·mid·low(W §7.1)."""
        return CONF[self.basis[s]]

    def minutes(self) -> int:
        """봉투 총 분(정수)."""
        return len(self.slots) * (SLOT // MIN)

    def tag_minutes(self) -> dict[str, int]:
        """꼬리표별 분."""
        out: Counter = Counter()
        for s in self.slots:
            out[self.tags[s]] += SLOT // MIN
        return dict(sorted(out.items()))

    def day_minutes(self) -> dict[date, int]:
        out: Counter = Counter()
        for s in self.slots:
            out[d_of(s * SLOT)] += SLOT // MIN
        return dict(sorted(out.items()))

    def day_tag_minutes(self) -> dict[date, dict[str, int]]:
        out: dict[date, Counter] = defaultdict(Counter)
        for s in self.slots:
            out[d_of(s * SLOT)][self.tags[s]] += SLOT // MIN
        return {d: dict(sorted(c.items())) for d, c in sorted(out.items())}


def _hm(s: str) -> tuple[int, int]:
    a, b = str(s).strip().split("-")
    h0, m0 = a.split(":")
    h1, m1 = b.split(":")
    return int(h0) * HOUR + int(m0) * MIN, int(h1) * HOUR + int(m1) * MIN


def trim_edges(base, tr, trim: int):
    """하한 양끝 다듬기: 양끝 trim 초 안에 흔적이 없으면 가장 가까운 흔적까지(최대 trim) 깎는다."""
    sp = U(base)
    if not sp or trim <= 0:
        return sp
    a0, b0 = sp[0][0], sp[-1][1]
    if not I([(a0, a0 + trim)], tr):
        first = min((x for x, y in tr if y > a0), default=a0 + trim)
        sp = I(sp, [(min(a0 + trim, max(a0, first)), b0)])
    if sp and not I([(b0 - trim, b0)], tr):
        last = max((y for x, y in tr if x < b0), default=b0 - trim)
        sp = I(sp, [(a0, max(b0 - trim, min(b0, last)))])
    return sp


def build_envelope(ev: Evidence, cfg, days: Mapping) -> Envelope:
    """W §3 근무 봉투. `days` = `lm27.time.calendar.build_days(ev, cfg, cal)`."""
    return _Builder(ev, cfg, days).run()


class _Builder:
    def __init__(self, ev: Evidence, cfg, days: Mapping):
        self.ev, self.cfg, self.days = ev, cfg, days
        g = cfg.__getitem__
        self.cover_min = int(g("time.slotCoverSec"))
        self.std = _hm(g("time.window.std"))
        self.half_am = _hm(g("time.window.halfAmOff"))
        self.half_pm = _hm(g("time.window.halfPmOff"))
        self.sampler_bridge = int(g("time.envelope.samplerBridgeMin")) * MIN
        self.session_gap = int(g("time.envelope.sessionGapMin")) * MIN
        self.pc_bridge = int(g("time.envelope.pcBridgeMin")) * MIN
        self.lock_break = int(g("time.envelope.lockBreakMin")) * MIN
        self.pre = {k: int(g(v)) * MIN for k, v in PRE_KEYS.items()}
        self.pad = int(g("time.envelope.tracePadMin")) * MIN
        self.trim = int(g("time.envelope.trimEdgesMin")) * MIN
        self.always_on = float(g("time.envelope.alwaysOnH")) * HOUR
        self.tpad = int(g("time.envelope.traceWindowPadMin")) * MIN
        self.tw_min = int(g("time.envelope.traceWindowMinAnchors"))
        self.remote_min = int(g("time.envelope.remoteSpanMinSends"))
        self.link_gap = int(g("time.envelope.remoteLinkGapMin")) * MIN
        self.fg_min = int(g("time.envelope.afterHoursFgMin")) * MIN
        self.an_min = int(g("time.envelope.afterHoursAnchorMin")) * MIN
        self.sk_pad = int(g("time.envelope.skeletonPadMin")) * MIN
        self.sk_pre = int(g("time.envelope.skeletonAnchorPreMin")) * MIN
        self.credit = int(g("time.envelope.passiveCreditMin")) * MIN
        self.day_cap = int(g("time.envelope.passiveDayCapMin")) * MIN
        self.max_part = int(g("time.envelope.passiveMaxParticipants"))
        self.chain_gap = int(g("time.envelope.passiveChainGapMin")) * MIN
        self.chain_n = int(g("time.envelope.passiveChainMinN"))
        self.date_gate = bool(g("time.envelope.dateOnlyGate"))
        self.tentative = g("time.envelope.tentative")
        self.tent_ratio = float(g("time.envelope.tentativeEvidenceRatio"))
        self.solver_mode = g("time.envelope.solverMode")
        self.solver_cap = int(round(float(g("time.envelope.solverCapH")) * HOUR))
        self.priv_run = int(g("privacy.time.regularPrivateRunMin")) * MIN
        self.priv_break = int(g("privacy.time.offhoursPrivateBreakMin")) * MIN
        self.led: dict[date, Counter] = defaultdict(Counter)
        self.led_n: dict[date, Counter] = defaultdict(Counter)
        self.flags: dict[date, list[str]] = defaultdict(list)

    def note(self, d: date, item: str, sec: int, n: int = 1) -> None:
        if sec:
            self.led[d][item] += int(sec)
            self.led_n[d][item] += n

    def run(self) -> Envelope:
        """W §3 의 순서를 한 함수에 그대로 둔다(참조 구현 대조가 쉽도록)."""
        ev, days = self.ev, self.days
        S_all = U([iv for d in days.values() for iv in d["S"]])
        lunches = U([iv for d in days.values() for iv in d["lunch"]])
        meals = U(lunches + [iv for d in days.values() for iv in d["dinner"]])
        reg = SUB(S_all, lunches)
        S_ix = IvIx(S_all)

        # ── 샘플러: PC별 커버·활동·잠금·사적·업무 전경 ──
        cov, act, lock, priv, media, fgwork = (defaultdict(list) for _ in range(6))
        for s in ev.samples:
            cov[s.pc].append((s.a, s.b))
            if s.state == "active":
                if s.priv in ("private", "social"):
                    priv[s.pc].append((s.a, s.b))
                elif s.priv == "media":
                    media[s.pc].append((s.a, s.b))
                else:
                    act[s.pc].append((s.a, s.b))
                    if s.cls in WORK_CLS or s.fam:
                        fgwork[s.pc].append((s.a, s.b))
            elif s.state == "idle":
                pass                                      # 유휴 = 커버만(부정 증거)
            else:                                         # locked · disconnected · sleep
                lock[s.pc].append((s.a, s.b))
        for pc, iv in media.items():                      # R-P6: 정규 구역 media = 일반 활동, 밖 = 사적
            act[pc] += I(iv, reg)
            priv[pc] += SUB(iv, reg)
        pcs = sorted(set(cov) | {p.pc for p in ev.pcon})
        for pc in pcs:
            cov[pc], act[pc], lock[pc], priv[pc], fgwork[pc] = U(cov[pc]), U(act[pc]), U(lock[pc]), U(priv[pc]), \
                U(fgwork[pc])
        all_cov = U([iv for p in pcs for iv in cov[p]])
        all_act = U([iv for p in pcs for iv in act[p]])
        all_lock = U([iv for p in pcs for iv in lock[p]])
        all_priv = U([iv for p in pcs for iv in priv[p]])
        unlocked_cov = U([iv for p in pcs for iv in SUB(cov[p], lock[p])])
        act_ix = IvIx(all_act)
        pcon: dict[str, list[tuple[int, int]]] = defaultdict(list)
        for p in ev.pcon:
            pcon[p.pc].append((p.a, p.b))
        fallback_on = U([iv for pc in pcon for iv in SUB(pcon[pc], cov.get(pc, []))])
        fb_ix = IvIx(fallback_on)
        neg_all = SUB(all_cov, all_act)                   # 부정 증거(잠금·유휴·사적)
        lockall = SUB(SUB(all_lock, all_act), fallback_on)
        lock_any_ix = IvIx(all_lock)
        all_cov_ix, unl_ix = IvIx(all_cov), IvIx(unlocked_cov)
        lockall_ix, neg_all_ix = IvIx(lockall), IvIx(neg_all)
        privonly_ix = IvIx(SUB(all_priv, all_act))
        fbact_ix = IvIx(fallback_on + all_act)            # C7: 샘플러 없는 가동 또는 능동 관측이 공백을 다 덮어야
        cov_ix = {pc: IvIx(cov[pc]) for pc in pcs}
        neg_pc_ix = {pc: IvIx(SUB(cov[pc], act[pc])) for pc in pcs}
        fb_pc = {pc: SUB(pcon[pc], cov.get(pc, [])) for pc in pcon}
        pre = self.pre

        # ── 능동 앵커(정확 시각만) — 사적 메시지는 정규화에서 이미 빠짐(R-P1) ──
        anchors: list[Anchor] = []
        for m in ev.msgs:
            if m.dir == "out" and m.prec in ("exact", "minute") and "deferred" not in m.flags:
                anchors.append(Anchor(m.t, "sent", pre["mail" if m.ch == "mail" else "teams"], None, m))
        for e in ev.docs:
            if e.kind in ("save", "export", "create") and not e.autosave and not e.burst and not e.other:
                k = "code" if e.raw.lower().endswith(CODE_EXT) else "file"
                anchors.append(Anchor(e.t, "save", pre[k], e.pc, e))
        for c in ev.commits:
            anchors.append(Anchor(c.t, "commit", pre["commit"], c.pc, c))
        for c in ev.comps:
            anchors.append(Anchor(c.a, "submit", pre["submit"], c.pc, c))
        anchors.sort(key=lambda x: (x.t, x.kind, str(getattr(x.ref, "id", "")), x.pc or ""))
        pts = [a.t for a in anchors]

        # ── 회의(수락·주최), 미정은 회의 창 전경 근거가 있을 때만, 종일 외근은 C11 로 ──
        meet_iv, personal_iv, counted, tentative_q = [], [], [], []
        offsite_days: set[date] = set()
        meetwin = U([(s.a, s.b) for s in ev.samples if s.state == "active" and s.cls == "meet"])
        for mt in ev.meets:
            if mt.status in ("declined", "cancelled"):
                continue
            if mt.personal:
                personal_iv.append((mt.a, mt.b))
                continue
            if mt.all_day:
                if mt.category in ("offsite", "edu", "trip") and mt.status in ("accepted", "organizer"):
                    offsite_days.add(d_of(mt.a))
                continue
            ok = mt.status in ("accepted", "organizer")
            if mt.status == "tentative":
                ok = self.tentative == "count" or (
                    self.tentative == "evidence" and
                    L(I([(mt.a, mt.b)], meetwin)) >= self.tent_ratio * (mt.b - mt.a))
                if not ok:
                    tentative_q.append(mt)
            if ok:
                meet_iv.append((mt.a, mt.b))
                counted.append(mt)
        meet_iv = U(meet_iv)

        # ── 수동 기록 ──
        manual_iv, manual_untimed = [], []
        for m in ev.manual:
            if m.kind == "work" and m.a is not None and m.b is not None:
                manual_iv.append((m.a, m.b))
            elif m.kind == "work" and m.a is None and m.hours:
                manual_untimed.append(m)
            elif m.kind == "offsite" and m.d:
                offsite_days.add(m.d)
        manual_iv = U(manual_iv)
        offsite_iv = U([iv for d in offsite_days if d in days for iv in days[d]["S"]])
        pad = self.pad
        all_fg = U([iv for p in pcs for iv in fgwork[p]])
        # 식사 차감 판정용 흔적: 앵커 직전 5분 + 업무 앱 전경 + 정규 구역 활동 + 회의 + 수동
        trace_iv = U([(t - pad, t + MIN) for t in pts] + all_fg + I(all_act, reg) + meet_iv + manual_iv)
        trace_ix = IvIx(trace_iv)
        trim_ix = IvIx(trace_iv + [(t - pad, t + pad) for t in pts] + [(a - pad, b + pad) for a, b in all_act])
        meals_ix = IvIx(meals)
        lunch_ix = IvIx(lunches)

        def meal_cut(iv, which: IvIx | None = None):
            """흔적 없는 식사 시간을 뺀다(점심·저녁)."""
            iv = U(iv)
            if not iv:
                return []
            ix = meals_ix if which is None else which
            lo, hi = iv[0][0], iv[-1][1]
            return SUB(iv, SUB(I(iv, ix.clip(lo, hi)), trace_ix.clip(lo, hi)))

        # ── (C1·C1b) 샘플러 활동 + PC 내부 다리, 창 밖·점심은 자격 + 골격 ±30분 ──
        skel_ix = IvIx(meet_iv + manual_iv)
        sampler_iv, samp_bridge = [], []
        for pc in pcs:
            A_ = act[pc]
            if not A_:
                continue
            C_ix, Lk_ix, fg_ix = IvIx(cov[pc]), IvIx(lock[pc]), IvIx(fgwork[pc])
            br = []
            for (_a0, b0), (a1, _b1) in zip(A_, A_[1:], strict=False):
                g, gl = (b0, a1), a1 - b0
                if gl <= self.sampler_bridge and C_ix.length(*g) == gl and \
                        not any(Lk_ix.hit(x, y) for x, y in SUB([g], S_ix.clip(*g))):
                    br += meal_cut([g])
            run = U(A_ + br)
            for a, b in SUB(run, reg):
                fgw = fg_ix.length(a, b)
                near = bool(pts_in(pts, a - self.an_min, b + self.an_min)) or bool(skel_ix.clip(a, b))
                if not (fgw >= self.fg_min or near):
                    run = SUB(run, [(a, b)])
                    self.note(d_of(a), "창밖_무자격_제외", b - a)
                    continue
                near_pts = pts_in(pts, a - 5 * MIN, b + self.sk_pre)
                skel = U(fg_ix.clip(a, b) + I([(a, b)], [(t - self.sk_pre, t + 5 * MIN) for t in near_pts]) +
                         skel_ix.clip(a, b))
                keep = U(skel + I([(a, b)], [(x - self.sk_pad, y + self.sk_pad) for x, y in skel]))
                drop = SUB([(a, b)], keep)
                if drop:
                    run = SUB(run, drop)
                    self.note(d_of(a), "창밖_골격밖_제외", L(drop))
            sampler_iv += run
            samp_bridge += I(br, run)
        sampler_iv = U(sampler_iv)
        samp_bridge = U(samp_bridge)
        sampler_core = SUB(sampler_iv, samp_bridge)

        # ── (C3·C4) 앵커 세션: 직전 창 — 샘플러가 덮은 PC 앵커는 그 PC 의 부정 증거만 뺀다 ──
        sess_iv, remote_iv = [], []
        anchor_sess: list[AnchorSession] = []
        remote_sends: list[RemoteSend] = []
        for an in anchors:
            t, kind, pc, ref = an.t, an.kind, an.pc, an.ref
            iv = pre_iv(t, an.pre_s)
            tail = (t // SLOT * SLOT, t // SLOT * SLOT + SLOT)
            parts = U(meal_cut([iv]) + [tail])
            iv = next(p for p in parts if p[0] <= tail[0] < p[1])
            if pc is not None and pc in cov_ix and cov_ix[pc].has(t):
                keep = U(SUB([iv], neg_pc_ix[pc].clip(*iv)) + [tail])
                for x, y in keep:
                    sess_iv.append((x, y))
                    anchor_sess.append(AnchorSession(x, y, kind, ref, t))
                continue
            anchor_sess.append(AnchorSession(iv[0], iv[1], kind, ref, t))
            if kind == "sent" and not act_ix.hit(t - 5 * MIN, t + 5 * MIN):
                remote_sends.append(RemoteSend(t, ref, iv))
                if not fb_ix.has(t):
                    remote_iv.append(iv)
                    if not S_ix.has(t):
                        self.flags[d_of(t)].append(f"원격발신 {_fmt(t)}")
                    continue
            sess_iv.append(iv)

        # ── (C4L) 원격 연결 다리: 같은 연결 키(대화·첨부 문서군)의 앞 관측이 60분 안 ──
        link_iv = []
        fam_obs: dict[str, list[int]] = defaultdict(list)
        for s in ev.samples:
            if s.state == "active" and s.fam and s.priv not in ("private", "social"):
                fam_obs[s.fam].append(s.b)
        for e in ev.docs:
            if e.kind in ("save", "export", "create") and not e.other and e.fam:
                fam_obs[e.fam].append(e.t)
        conv_obs: dict[str, list[int]] = defaultdict(list)
        for an in anchors:
            if an.kind == "sent":
                conv_obs[an.ref.conv].append(an.t)
        for t, ref, iv in remote_sends:
            cands = []
            for f in ref.atts:
                cands += [x for x in fam_obs.get(f, ()) if iv[0] - self.link_gap <= x <= iv[0]]
            cands += [x for x in conv_obs.get(ref.conv, ()) if iv[0] - self.link_gap <= x < t - 5 * MIN]
            if cands:
                x = max(cands)
                if iv[0] > x:
                    link_iv += meal_cut([(x, iv[0])])

        # ── (C6·C7) 사슬 다리 ≤45분(창 밖 전 PC 잠금·사적 전용이 끊음), 45~120분 PC 다리 ──
        chain = U(sampler_iv + sess_iv + remote_iv + link_iv)
        bridge_iv, bridge_pc_iv = [], []
        for (_a0, b0), (a1, _b1) in zip(chain, chain[1:], strict=False):
            g, gl = (b0, a1), a1 - b0
            if gl <= self.session_gap:
                offg = SUB([g], S_ix.clip(*g))
                if any(y - x >= self.lock_break for p0, p1 in offg for x, y in lockall_ix.clip(p0, p1)):
                    self.note(d_of(b0), "잠금단절_다리없음", gl)
                    continue
                if any(y - x >= self.priv_break for p0, p1 in offg for x, y in privonly_ix.clip(p0, p1)):
                    self.note(d_of(b0), "사적단절_다리없음", gl)
                    continue
                bridge_iv += meal_cut([g])
            elif gl <= self.pc_bridge and not neg_all_ix.hit(*g) and fbact_ix.length(*g) == gl:
                bridge_pc_iv += meal_cut([g])

        # ── (C8·C8d·C9·C10·C10r) 평일 S_eff 안 하한·수신 사슬·흔적 창(합집합형) ──
        floor_iv, floor_do_iv, pchain_iv, tw_iv, twr_iv = [], [], [], [], []
        date_only_out, summary_days = Counter(), Counter()
        for m in ev.msgs:
            if m.prec == "date" and m.dir == "out":
                date_only_out[d_of(m.t)] += 1
            if m.prec == "summary":
                summary_days[d_of(m.t)] += 1
        manual_days = {m.d for m in ev.manual if m.kind in ("work", "offsite") and m.d}
        direct_in = sorted(m.t for m in ev.msgs if m.dir == "in" and m.direct and m.prec in ("exact", "minute")
                           and not m.flags & {"cc", "notice", "bulk"} and m.n_part <= self.max_part)
        sent_ex = sorted(a.t for a in anchors if a.kind == "sent")
        meet_ix, sampler_ix = IvIx(meet_iv), IvIx(sampler_iv)
        for d, info in sorted(days.items()):
            Sd = info["S"]
            if not Sd or not info["in_range"]:
                continue
            z = day0(d)
            D_ = [(z, z + DAY)]
            day_pts = pts_in(pts, z, z + DAY - 1)
            gate = bool(day_pts) or meet_ix.hit(z, z + DAY) or sampler_ix.hit(z, z + DAY) or d in manual_days
            gate_do = (not gate) and self.date_gate and date_only_out[d] > 0
            tr = trim_ix.clip(z, z + DAY)
            base = []
            for pc in pcon:
                b_pc = I(fb_pc[pc], Sd)
                if not b_pc:
                    continue
                if L(I(pcon[pc], D_)) >= self.always_on:
                    ext = self.tpad - pad
                    b_pc = I(b_pc, [(tr[0][0] - ext, tr[-1][1] + ext)]) if tr else []
                    self.flags[d].append("항상켜짐PC")
                base += b_pc
            base = U(base)
            b2 = []
            if base and (gate or gate_do):
                b2 = trim_edges(base, tr, self.trim)
                before = L(b2)
                b2 = meal_cut(b2, lunch_ix)
                self.note(d, "점심차감", before - L(b2))
                (floor_iv if gate else floor_do_iv).extend(b2)
                if gate_do:
                    self.flags[d].append("date-only 게이트 하한(낮은 신뢰)")
            if base:                                      # R7 수신 연속형 — 게이트와 무관하게 늘(합집합)
                ps = [t for t in direct_in if z <= t < z + DAY and any(a <= t < b for a, b in Sd)]
                chains, cur = [], []
                for t in ps:
                    if cur and t - cur[-1] > self.chain_gap:
                        chains.append(cur)
                        cur = []
                    cur.append(t)
                if cur:
                    chains.append(cur)
                for c in chains:
                    if len(c) >= self.chain_n:
                        pchain_iv += meal_cut(I([(c[0] - pad, c[-1] + pad)], base), lunch_ix)
            if len(day_pts) >= self.tw_min:               # C10 흔적 창(조건 없는 합집합)
                span = I([(day_pts[0] - self.tpad, day_pts[-1] + self.tpad)], Sd)
                add = meal_cut(SUB(span, all_cov_ix.clip(span[0][0], span[-1][1])) if span else [], lunch_ix)
                tw_iv += add
                if SUB(add, U(b2)):
                    self.flags[d].append("흔적창(낮은 신뢰)")
            r_pts = [t for t in pts_in(sent_ex, z, z + DAY - 1) if lock_any_ix.has(t)]
            if len(r_pts) >= self.remote_min:             # C10r 원격 흔적 창
                span = I([(r_pts[0] - self.tpad, r_pts[-1] + self.tpad)], Sd)
                wv = meal_cut(SUB(span, unl_ix.clip(span[0][0], span[-1][1])) if span else [], lunch_ix)
                if wv:
                    twr_iv += wv
                    self.flags[d].append("원격발신 흔적창(낮은 신뢰)")
            if date_only_out[d] and not trace_ix.hit(z, z + DAY):
                self.flags[d].append(f"date-only 발신 {date_only_out[d]}건(시각 근거 아님)")
            if summary_days[d]:
                self.flags[d].append(f"코파일럿 요약 {summary_days[d]}건(존재만)")

        # ── (C12) 솔버 cap(옵션) — 기본 anchor 모드는 기계 시간을 봉투에 넣지 않는다 ──
        solver_iv = []
        if self.solver_mode == "cap":
            for c in ev.comps:
                out = SUB([(c.a, c.b)], S_all)
                if not out:
                    continue
                if any(act_ix.hit(x, y) for x, y in out):
                    solver_iv += out
                else:
                    solver_iv += I(out, [(c.b - self.solver_cap, c.b)])

        comps = [("C11", U(manual_iv + offsite_iv)), ("C2", meet_iv), ("C1", sampler_core), ("C3", U(sess_iv)),
                 ("C4", U(remote_iv)), ("C1b", samp_bridge), ("C4L", U(link_iv)), ("C6", U(bridge_iv)),
                 ("C7", U(bridge_pc_iv)), ("C8", U(floor_iv)), ("C8d", U(floor_do_iv)), ("C9", U(pchain_iv)),
                 ("C10", U(tw_iv)), ("C10r", U(twr_iv)), ("C12", U(solver_iv))]
        union = U([iv for _, v in comps for iv in v])
        cover = slot_cover(union)
        slots = {s for s, c in cover.items() if c >= self.cover_min}
        comp_cov = {name: slot_cover(ivs, slots) for name, ivs in comps}
        basis: dict[int, str] = {}
        for s in slots:
            best = None
            for name in PRIO:
                if name in comp_cov and comp_cov[name].get(s, 0) >= 60:
                    best = name
                    break
            if best is None:
                best = max(comp_cov, key=lambda n: (comp_cov[n].get(s, 0), -PRIO.index(n)))
            basis[s] = best

        # ── (C5) 수신 크레딧 — '아직 봉투가 아닌 슬롯'만, 이른 순, 하루 상한 ──
        neg_ix = IvIx(SUB(neg_all, fallback_on))
        used: Counter = Counter()
        reg_ix = IvIx(reg)
        for t in direct_in:
            if not reg_ix.has(t) or neg_ix.has(t):
                continue
            d = d_of(t)
            if not days.get(d, {}).get("in_range"):
                continue
            for s in range(t // SLOT, t // SLOT + max(1, round(self.credit / SLOT))):
                if s in slots or not reg_ix.has(s * SLOT):
                    continue
                if used[d] + SLOT > self.day_cap:
                    self.note(d, "수신상한_제외", SLOT)
                    break
                slots.add(s)
                basis[s] = "C5"
                used[d] += SLOT

        # ── 마지막 단계 차감(R-P9): 사적 전용 슬롯 — 정규 구역 연속 ≥ regularPrivateRunMin, 그 밖 전부 ──
        priv_cov = slot_cover(SUB(all_priv, all_act))
        work_cov = slot_cover(U(all_act + meet_iv + manual_iv + offsite_iv))
        pt_slots = {t // SLOT for t in pts}
        ponly = sorted(s for s in slots if priv_cov.get(s, 0) >= SLOT // 2 and work_cov.get(s, 0) < 60
                       and s not in pt_slots and basis[s] not in ("C11", "C11u", "C2"))
        run_min = self.priv_run // SLOT
        runs, cur = [], []
        for s in ponly:
            if cur and s != cur[-1] + 1:
                runs.append(cur)
                cur = []
            cur.append(s)
        if cur:
            runs.append(cur)
        for r in runs:
            reg_part = [s for s in r if reg_ix.has(s * SLOT)]
            off_part = [s for s in r if not reg_ix.has(s * SLOT)]
            drop = off_part + (reg_part if len(reg_part) >= run_min else [])
            per_day: Counter = Counter()
            for s in drop:
                slots.discard(s)
                per_day[d_of(s * SLOT)] += SLOT
            for d, sec in per_day.items():
                self.note(d, "사적차감", sec)
        # 개인 일정(R-P5): 정규 구역 → 개인 부재(그 슬롯에 능동 산출 앵커가 있으면 업무 우선)
        for a, b in U(personal_iv):
            per_day = Counter()
            for s in range(a // SLOT, (b - 1) // SLOT + 1):
                if s in slots and reg_ix.has(s * SLOT) and s not in pt_slots:
                    slots.discard(s)
                    per_day[d_of(s * SLOT)] += SLOT
            for d, sec in per_day.items():
                self.note(d, "개인일정차감", sec)
        # 사용자 '업무 아님' 확인(exclude) — 봉투가 줄어드는 유일한 사용자 경로
        for m in ev.manual:
            if m.kind == "exclude" and m.a is not None and m.b is not None and m.b > m.a:
                per_day = Counter()
                for s in range(m.a // SLOT, (m.b - 1) // SLOT + 1):
                    if s in slots:
                        slots.discard(s)
                        per_day[d_of(s * SLOT)] += SLOT
                for d, sec in per_day.items():
                    self.note(d, "사용자제외", sec)
        # 시각 없는 수동 기록: 그날 정규 구역의 빈 슬롯 → 모자라면 표준창 끝부터 연속
        manual_slots: dict[str, list[int]] = {}
        for m in manual_untimed:
            need = int(round(m.hours * 12))
            info = days.get(m.d)
            if not info or need <= 0:
                continue
            z = day0(m.d)
            S_d = info["S"] or [(z + self.std[0], z + self.std[1])]
            cand = []
            for a, b in SUB(S_d, info["lunch"]):
                cand += [s for s in range(a // SLOT, b // SLOT) if s not in slots]
            s_end = S_d[-1][1] // SLOT
            while len(cand) < need:
                if s_end not in slots and s_end not in cand:
                    cand.append(s_end)
                s_end += 1
            m_slots = cand[:need]
            for s in m_slots:
                slots.add(s)
                basis[s] = "C11u"
            manual_slots[m.id or m.key] = m_slots
            self.flags[m.d].append(f"수동 {m.hours:g}h 시각없음 배치")
        for s in list(basis):
            if s not in slots:
                del basis[s]
        for s in slots:
            self.note(d_of(s * SLOT), ENV_PREFIX + basis[s], SLOT)

        tags = {s: slot_tag(s, days, self.cfg) for s in sorted(slots)}
        on_leave = self._on_leave(slots)
        pcs_of = self._pcs(slots, pcs, cov, pcon)
        return Envelope(
            slots=slots, basis=basis, comp_cov=comp_cov, ledger=_freeze(self.led), flags=dict(self.flags),
            anchors=anchors, anchor_sessions=anchor_sess, counted_meetings=counted, tentative_unconfirmed=tentative_q,
            reg=reg, ledger_n=_freeze(self.led_n), s_all=S_all, pts=pts, remote_sends=remote_sends, meet_iv=meet_iv,
            cov={p: cov[p] for p in pcs}, act={p: act[p] for p in pcs}, all_cov=all_cov, all_act=all_act,
            manual_slots=manual_slots, tags=tags, on_leave=on_leave, pcs=pcs_of)

    def _on_leave(self, slots: set[int]) -> set[int]:
        """연차·반차 시간에 든 슬롯(보조 꼬리표 on_leave — W §3.13 · Q16)."""
        out = set()
        for s in slots:
            t = s * SLOT
            info = self.days.get(d_of(t))
            if not info or info["hol"] or info["lv"] not in ("full", "am", "pm"):
                continue
            if info["lv"] == "full":
                out.add(s)
                continue
            a, b = self.half_am if info["lv"] == "am" else self.half_pm
            m = t - day0(d_of(t))
            if a <= m < b:
                out.add(s)
        return out

    @staticmethod
    def _pcs(slots, pcs, cov, pcon) -> dict[int, tuple[str, ...]]:
        """슬롯마다 관측된 PC(샘플러 커버 ∪ 가동)."""
        ix = {pc: IvIx(cov.get(pc, []) + pcon.get(pc, [])) for pc in pcs}
        out = {}
        for s in sorted(slots):
            a = s * SLOT
            out[s] = tuple(pc for pc in pcs if ix[pc].hit(a, a + SLOT))
        return out



def _freeze(led: Mapping[date, Counter]) -> dict[date, Counter]:
    return {d: Counter(dict(sorted(c.items()))) for d, c in sorted(led.items()) if c}


def _fmt(t: int) -> str:
    d = d_of(t)
    m = (t - day0(d)) // MIN
    return f"{d.month:02d}-{d.day:02d} {m // 60:02d}:{m % 60:02d}"
