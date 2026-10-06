# -*- coding: utf-8 -*-
r"""L3 배치 실행기(B §7) — 모든 단계 공용 한 벌: 패킹 · 반분 · 누락 재질의 · 연기 · 서킷브레이커 · 2-strike · 예산 ·
항목 단위 커밋 · 재개(입력 서명 = 내용 키) · 접기 · 결과 봉투.

    rt = make_runtime(paths, run_id, cfg=…, clock=…, transport=…, gate_base=…, env=…)   # 시험·내부
    results = run_stages(rt, [spec, …])                                               # 단계마다 결과 봉투 dict
    rc = worst_rc(results)                                                            # failed 1 > partial 2 > 0

단계 하나(``run_stage``, B §7.16):
  꺼짐·mode=off → skipped(disabled) · 웹 노출 + 정책 block → skipped(web_exposed, BR-WEB-BLOCK) · 조회 능력 unavailable
  (또는 오늘 이미 거절을 본 suspect) → skipped(capability_unavailable) · 업무 모드가 web 확정 → skipped(mode_web) →
  ai_in 적재(보낼 필드만 — ck 는 게이트 전 필드로) → 재개 거르기(이미 답한 항목은 게이트도 전송도 건너뜀) → ① 항목 게이트
  (+ 웹 노출이면 ①' 엄격 규칙 — 걸린 항목은 ``gated:<사유>`` 규칙 커밋) → 패킹 → ``exchange.ask`` → 커밋·재큐 → … →
  finally: 접기(ai_out — 저장소 기준, 멱등) + 결과 봉투(``lm27.stage/1`` 공통 필드 + B §7.11, 모든 종료 경로).

수동 경로(B §10)도 같은 함수다 — ``ManualTransport`` 가 ``manual_pending`` 을 돌려주면 묶음을 내보낸 채 계속 패킹하고,
열린 묶음이 ``bridge.manual.maxOpenBatches`` 가 되거나 대기열이 비면 ``stop_kind=manual_wait``(rc 2). 반입
(``manual_import``)은 같은 분류(``exchange.classify``)·같은 커밋·재큐 규칙(``after_ask``)을 쓴다.

브리지는 시간·MM 을 계산하거나 보내지 않는다(B1 — 보낼 필드는 단계 ``send_fields`` 허용 목록만).
"""
from __future__ import annotations

import os
from collections import Counter, deque
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime

from lm27.bridge import budget as BG
from lm27.bridge import exchange as X
from lm27.bridge import fsio
from lm27.bridge import journal as J
from lm27.bridge.clock import iso_now
from lm27.bridge.gate import StageGateError
from lm27.bridge.messages import MANUAL_SWITCH_PHASES, PHASE_BR, Notices, render
from lm27.bridge.stages import base as B

LOGIN_RECHECK_S = 60.0          # login_required 1차 복구: 탭 재진입 뒤 60초 폴링(B §7.7)
FATAL_STRIKES = 2               # 연속 치명 실패 2회 → 단계 중지(2-strike)
NOTE_RESERVE = 160              # '주의' 줄 자리(패킹 예산)
KEY_MAX = 80
GROUP_MAX = 40
MANUAL_RESEND = ("echo", "format", "empty", "service_error")
ITEM_BY = ("ai", "manual", "rule")
_BR_STOP = {"budget": "BR-BUDGET", "circuit": "BR-CIRCUIT", "gate": "BR-GATE-BLOCKED", "header": "BR-HEADER",
            "manual_wait": "BR-MANUAL-SWITCH"}


class StageConfigError(Exception):
    """머리말이 입력 한도를 넘는 등 설정 문제 — 다시 해도 같다(stop_kind=header, BR-HEADER)."""


# ───────────────────────── 자료구조(B §7.1) ─────────────────────────
@dataclass
class WorkItem:
    key: str
    group: str
    fields: dict                 # send_fields 만 남긴 것(게이트 뒤에는 재가림 값)
    rule: dict                   # 폴백 재료(보내지 않음)
    ck: str                      # 내용 키(§7.9 — 게이트 전 필드로)
    meta: dict = field(default_factory=dict)
    asks: int = 0                # 이번 실행에서 물은 횟수(수동 경로는 반입한 묶음 수부터)
    notes: tuple = ()            # 직전 무효 사유(다음 질의 '주의' 줄)
    retry_runs: int = 0
    deferred: bool = False
    parent: str = ""             # 조회 구간 쪼개기의 부모 key
    src_ver: str = ""


@dataclass
class Pinned:                    # 반분·재전송으로 만든 '묶음 고정' 단위
    items: list
    depth: int
    deferred: int = 0
    resend: int = 0


@dataclass
class Runtime:
    """호출 1회의 공용 상태(전송·게이트·환경·능력·계측). ``make_runtime`` 이 만든다."""
    paths: object
    cfg: object                  # BridgeSettings
    clock: object
    run_id: str
    transport: object = None
    gate_base: object = None
    env: object = None           # CopilotEnv
    caps: object = None          # capability.Capabilities
    profile: object = None       # session.BridgeProfile
    tracer: object = None
    notices: Notices | None = None
    emit: object = None
    registry: object = None
    registry_version: str = ""
    raw_cfg: object = None       # lm27.config.Cfg(PC 능력 판정 설정)
    pc_id: str | None = None
    used_rids: set = field(default_factory=set)
    fatal_stop: str = ""
    calib: dict | None = None
    edge_major: int = 0
    profile_id: str = ""
    manual_switched: bool = False
    write_files: bool = True
    seq: int = 0
    heartbeat: bool = False

    def notify(self, code: str, **kw) -> None:
        if self.notices is not None:
            self.notices.notify(code, **kw)

    def ev(self, name: str, **fields) -> None:
        if self.emit is not None:
            self.emit(name, **fields)


class StageRun:
    """단계 하나의 실행 상태(B §7.1 StageRun)."""

    def __init__(self, spec, rt: Runtime, ctx: B.StageCtx):
        self.spec = spec
        self.rt = rt
        self.ctx = ctx
        self.pending: deque = deque()
        self.pinned: deque = deque()
        self.items: list = []                     # ai_in 항목 전부(+ 조회 쪼갠 구간) — 접기 대상
        self.by_key: dict = {}
        self.committed: set = set()
        self.pack_in = 0
        self.pack_out = 0
        self.zero_streak = 0
        self.circuit_soft = False
        self.fatal_strikes = 0
        self.trunc_out_count = 0
        self.ok_streak = 0
        self.deadline = float("inf")
        self.stop_kind = None
        self.stop_reason = None
        self.resumable = False
        self.hint = ""
        self.error_type = ""
        self.stats: Counter = Counter()
        self.rungs: Counter = Counter()
        self.statuses: Counter = Counter()
        self.caps_hit: Counter = Counter()
        self.dropped: Counter = Counter()
        self.names: Counter = Counter()
        self.last_answers: list = []              # [(항목, 답)] — 겹침 줄
        self.models: list = []
        self.est_scale = 1.0
        self.chat = X.ChatState(rt.cfg)
        self.sgate = None
        self.sgate_prev = None                    # 수동 전환 전 게이트(건수 이어받기)
        self.store = None
        self.journal = None
        self.text_fields: tuple = ()
        self.t0 = rt.clock.mono()
        self.skipped = None
        self.lookup_ok_seen = False
        self.result: dict = {}

    @property
    def stopped(self) -> bool:
        return self.stop_kind is not None

    def stop(self, kind: str, *, resumable: bool, reason: str | None = None, br: str = "", **kw) -> None:
        if self.stopped:
            return
        self.stop_kind = kind
        self.resumable = resumable
        self.stop_reason = reason
        code = br or _BR_STOP.get(kind, "")
        if code:
            self.hint = render(code, **kw)["title"]
            self.rt.notify(code, **kw)


# ───────────────────────── 적재·재개(B §2.5 · §7.9) ─────────────────────────
def load_ai_in(paths, spec) -> tuple[list, Counter]:
    r"""``data\derived\ai_in\<stage>.jsonl`` → (WorkItem 목록, 버린 건수). 보낼 필드 밖 키는 버리고 센다(보내지 않음)."""
    rows, torn = J._parse_lines(fsio.read_text(paths.ai_in(spec.id)))
    dropped: Counter = Counter()
    if torn:
        dropped["bad_input"] += torn
    allowed = set(spec.send_fields)
    items, seen = [], set()
    for r in rows:
        key = r.get("key")
        if not isinstance(key, str) or not key or len(key) > KEY_MAX:
            dropped["bad_input"] += 1
            continue
        if key in seen:
            dropped["dup_input"] += 1
            continue
        seen.add(key)
        raw = r.get("fields") if isinstance(r.get("fields"), dict) else {}
        extra = [k for k in raw if k not in allowed]
        if extra:
            dropped["extra_input_fields"] += len(extra)
        fields = {k: v for k, v in raw.items() if k in allowed}
        meta = r.get("meta") if isinstance(r.get("meta"), dict) else {}
        meta = {k: meta[k] for k in ("priv_class", "ad_band", "rules_ver") if k in meta}
        items.append(WorkItem(key=key, group=str(r.get("group") or "")[:GROUP_MAX], fields=fields,
                              rule=dict(r.get("rule") if isinstance(r.get("rule"), dict) else {}),
                              ck=B.content_key(spec, fields), meta=meta, src_ver=str(r.get("src_ver") or "")))
    return items, dropped


def _codes_gone(spec, ans, ctx) -> bool:
    """답의 코드 필드 값이 지금 레지스트리에 없는가(재개 규칙 (c))."""
    if not isinstance(ans, dict):
        return False

    def bad(f, v):
        allowed = ctx.codes(f.codes) if f.codes else None
        return allowed is not None and v not in allowed and v not in f.extra_codes
    for f in spec.item_schema:
        v = ans.get(f.name)
        if f.kind == "code" and isinstance(v, str) and bad(f, v):
            return True
        if f.kind == "list" and f.item and isinstance(v, list):
            for el in v:
                for g in f.item:
                    if g.kind == "code" and isinstance(el, dict) and isinstance(el.get(g.name), str) \
                            and bad(g, el[g.name]):
                        return True
    return False


def _child_items(run, it) -> list:
    out = []
    for ch in run.spec.split(it, run.ctx) or ():
        if not isinstance(ch, dict) or not isinstance(ch.get("key"), str):
            continue
        fields = {k: v for k, v in (ch.get("fields") or {}).items() if k in set(run.spec.send_fields)}
        out.append(WorkItem(key=ch["key"][:KEY_MAX], group=str(ch.get("group", it.group) or "")[:GROUP_MAX],
                            fields=fields, rule=dict(it.rule), ck=B.content_key(run.spec, fields), meta=dict(it.meta),
                            parent=it.key))
    return out


def resume_filter(run, items, *, awaiting=frozenset()) -> list:
    """다시 물을 항목(B §7.9): (a) 커밋 없음 (b) 마지막 커밋이 rule·final=false·retry_runs<1 (c) 레지스트리가 바뀌었고 답의
    코드가 새 레지스트리에 없음 (d) ``gated:web_combo`` 였고 이번 호출은 웹 노출이 아님. 조회 구간을 쪼갠 부모는 자식을 본다."""
    spec, ctx, store = run.spec, run.ctx, run.store
    queue = []
    for it in items:
        if it.ck in awaiting:
            run.stats["awaiting"] += 1
            continue
        c = store.last(it.ck)
        if c is None:
            queue.append(it)
            continue
        why = str(c.get("why") or "")
        if c.get("by") == "rule" and why == "split":
            kids = _child_items(run, it)
            for k in kids:
                run.items.append(k)
                run.by_key[k.key] = k
            queue.extend(resume_filter(run, kids, awaiting=awaiting))
            continue
        if c.get("by") == "rule" and c.get("final") is False and int(c.get("retry_runs") or 0) < 1:
            it.retry_runs = int(c.get("retry_runs") or 0) + 1
            queue.append(it)
            continue
        if spec.uses_registry and str(c.get("reg") or "") != ctx.registry_version and _codes_gone(spec, c.get("ans"),
                                                                                                  ctx):
            queue.append(it)
            continue
        if why == "gated:web_combo" and not ctx.web_exposed:
            queue.append(it)
            continue
        run.stats["resume_skipped"] += 1
    return queue


# ───────────────────────── 커밋(B §7.8) ─────────────────────────
def _reg(run):
    return run.ctx.registry_version or None


def commit_answer(run, it, ans, rid: str) -> None:
    by = "manual" if getattr(run.rt.transport, "kind", "") == "manual" else "ai"
    rec = {"schema": run.spec.schema, "ck": it.ck, "key": it.key, "reg": _reg(run), "run": run.rt.run_id, "rid": rid,
           "by": by, "asks": it.asks + 1, "final": True, "ans": ans}
    rs = it.rule.get("reg_set") if isinstance(it.rule, dict) else None
    if isinstance(rs, str) and 0 < len(rs) <= 16:
        rec["reg_set"] = rs
    run.store.commit(rec)
    run.committed.add(it.ck)
    run.stats["commits"] += 1
    nf = run.spec.names_field
    if nf and isinstance(ans, dict) and isinstance(ans.get(nf), str) and ans.get(nf):
        run.names[ans[nf]] += 1
        run.last_answers.append((it, ans))
        run.last_answers = run.last_answers[-max(1, run.rt.cfg.overlap_items):]


def commit_rule(run, it, why: str, *, final: bool | None = None, confirm: bool = False, ans=None) -> None:
    """규칙 커밋(by=rule). ai_failed 는 final=false(다음 실행에서 1회 더 — retry_runs), 나머지는 final=true."""
    if final is None:
        final = not (why == "ai_failed" and it.retry_runs < 1)
    if ans is None and why != "split":
        ans = run.spec.fallback(it, run.ctx, why)
    rec = {"schema": run.spec.schema, "ck": it.ck, "key": it.key, "reg": _reg(run), "run": run.rt.run_id, "rid": None,
           "by": "rule", "asks": it.asks, "final": bool(final), "ans": ans, "why": why, "retry_runs": it.retry_runs}
    if confirm:
        rec["confirm"] = True
    run.store.commit(rec)
    run.committed.add(it.ck)
    run.stats["rule_commits"] += 1


# ───────────────────────── 패킹(B §7.3 · §7.4) ─────────────────────────
def _fixed_len(run, compact: bool) -> int:
    spec = run.spec
    title = spec.title_line("R" + "Z" * X.RID_LEN, max(1, spec.max_items), [], run.ctx)
    head = spec.header(run.ctx, compact) or ""
    cols = spec.columns() or ""
    return len(title) + 1 + len(head) + 1 + len(cols) + 1 + X.footer_len(spec, spec.max_items) + NOTE_RESERVE


def context_block(run) -> str:
    """앞서 쓴 이름(빈도순, seenNamesMax·seenNamesChars) + 겹침(직전 묶음 끝 overlapItems, overlapChars)."""
    spec, cfg = run.spec, run.rt.cfg
    parts = []
    if spec.names_field and cfg.seen_names_max > 0 and cfg.seen_names_chars > 0 and run.names:
        names, size = [], 0
        for name, _n in sorted(run.names.items(), key=lambda kv: (-kv[1], kv[0])):
            add = len(name) + (3 if names else 0)
            if len(names) >= cfg.seen_names_max or size + add > cfg.seen_names_chars:
                run.caps_hit["seen_names"] += 1
                break
            names.append(name)
            size += add
        if names:
            parts.append(B.SEEN_NAMES_PROMPT.format(names=" / ".join(names)))
    if cfg.overlap_items > 0 and cfg.overlap_chars > 0 and run.last_answers:
        lines, size = [], 0
        for it, ans in run.last_answers[-cfg.overlap_items:]:
            ln = spec.overlap_line(it, ans)
            if not ln:
                continue
            if size + len(ln) + 1 > cfg.overlap_chars:
                break
            lines.append(ln)
            size += len(ln) + 1
        if lines:
            parts.append(B.OVERLAP_PROMPT)
            parts.extend(lines)
    return "\n".join(parts)


def _group_fits(run, group: str, room: int) -> bool:
    size = 0
    for it in run.pending:
        if it.group != group:
            break
        size += len(run.spec.item_line(it, 0)) + 1
    return size <= room


def next_batch(run):
    """다음 묶음 — 고정 묶음(반분·재전송)이 먼저. → (항목 목록, 깊이, 고정 묶음 또는 None, 축약 머리말, 겹침 글) 또는 None."""
    while True:
        if run.pinned:
            p = run.pinned.popleft()
            if p.items:
                return p.items, p.depth, p, False, context_block(run)
            continue
        if not run.pending:
            return None
        nb = _pack(run)
        if nb is not None:
            return nb


def _pack(run):
    """일반 대기열에서 한 묶음(B §7.3). 앞 항목이 모두 크기 초과로 빠졌으면 None(호출자가 다시 본다)."""
    spec = run.spec
    ctxb = context_block(run)
    compact = False
    room = run.pack_in - _fixed_len(run, False) - len(ctxb)
    if room < run.pack_in * BG.ROOM_COMPACT_RATIO:
        compact = True
        room = run.pack_in - _fixed_len(run, True) - len(ctxb)
        if room < run.pack_in * BG.ROOM_COMPACT_RATIO:
            raise StageConfigError("header_too_large")
    batch, used_in, used_out, cur = [], 0, BG.ENVELOPE_OVERHEAD + int(spec.est_out_fixed), None
    while run.pending and len(batch) < max(1, int(spec.max_items)):
        it = run.pending[0]
        line = spec.item_line(it, len(batch) + 1)
        if len(line) > room:
            nf = spec.shrink(it, room)
            if isinstance(nf, dict):
                it.fields = {k: v for k, v in nf.items() if k in set(spec.send_fields)}
                line = spec.item_line(it, len(batch) + 1)
            if not isinstance(nf, dict) or len(line) > room:
                run.pending.popleft()
                commit_rule(run, it, "oversize")
                run.caps_hit["oversize"] += 1
                continue
        est = int(spec.est_out(it) * run.est_scale)
        if batch and (used_in + len(line) + 1 > room or used_out + est > run.pack_out):
            break
        if batch and spec.group_strict and it.group != cur and not _group_fits(run, it.group, room - used_in):
            break
        run.pending.popleft()
        batch.append(it)
        used_in += len(line) + 1
        used_out += est
        cur = it.group
    if not batch:
        return None
    return batch, 0, None, compact, ctxb


# ───────────────────────── 질의 뒤(B §7.5~§7.7) ─────────────────────────
def _requeue_front(run, items) -> None:
    for it in reversed(items):
        run.pending.appendleft(it)


def _update_est(run, ar, n_items: int) -> None:
    """답 길이 지수 이동 평균(α=0.3)으로 항목당 추정을 보정(하한 0.7배·상한 2배, B §7.3)."""
    if ar.status not in ("ok", "partial") or n_items <= 0 or ar.reply_len <= 0:
        return
    design = max(1, int(run.spec.est_out_per_item) * n_items + int(run.spec.est_out_fixed) + BG.ENVELOPE_OVERHEAD)
    ratio = ar.reply_len / design
    s = (1 - BG.EST_ALPHA) * run.est_scale + BG.EST_ALPHA * ratio
    run.est_scale = max(BG.EST_MIN_SCALE, min(BG.EST_MAX_SCALE, s))


def update_circuit(run, ar, newly: int) -> None:
    """연속 0건 질의(B §7.6). 크기·세션·거절은 셈하지 않는다."""
    if ar.status in ("transport_fatal", "refusal") or (ar.status == "truncated" and ar.side == "input"):
        return
    if newly > 0:
        run.zero_streak = 0
        return
    run.zero_streak += 1
    cfg = run.rt.cfg
    if run.zero_streak >= cfg.circuit_soft and not run.circuit_soft:
        run.circuit_soft = True
        run.rt.notify("BR-CIRCUIT-SOFT", n=run.zero_streak)
    if run.zero_streak >= cfg.circuit_abort:
        run.stop("circuit", resumable=True, n=run.zero_streak, done=len(run.committed))


def recover(rt: Runtime, phase: str) -> None:
    """치명 실패 1차 복구(B §7.7) — 세션이 ``recover(phase)`` 를 가지면 그것, 아니면 공개 메서드로 최소한만."""
    s = getattr(rt.transport, "s", None)
    if s is None:
        return
    fn = getattr(s, "recover", None)
    if callable(fn):
        fn(phase)
        return
    from lm27.bridge import cdp as C
    from lm27.bridge.session import PhaseError
    try:
        if phase == "login_required":
            s.navigate()
            s.poll_identity(LOGIN_RECHECK_S, until=lambda st: st not in ("login_required", "loading"))
        elif phase in ("input_not_found", "dead_session"):
            s.reload()
            s.poll_identity(float(rt.cfg.ready_wait_sec))
    except (OSError, C.CdpError, PhaseError):
        pass


def switch_to_manual(rt: Runtime, phase: str) -> bool:
    """policy_blocked·edge_not_found + autoManualFallback → 이 호출부터 수동 경로(B §10.1, BR-MANUAL-SWITCH)."""
    if not rt.cfg.auto_manual_fallback or getattr(rt.transport, "kind", "") == "manual":
        return False
    from lm27.bridge.env import manual_env
    from lm27.bridge.manual import ManualTransport
    try:
        if rt.transport is not None:
            rt.transport.close()
    except OSError:
        pass
    rt.transport = ManualTransport(rt.paths, rt.cfg, rt.clock, run_id=rt.run_id)
    rt.transport.open()
    rt.env = manual_env(rt.clock)
    rt.manual_switched = True
    rt.notify(PHASE_BR.get(phase, "BR-EDGE"))
    return True


def handle_fatal(run, ar) -> None:
    rt, phase = run.rt, ar.reason or ar.transport_phase
    if phase in MANUAL_SWITCH_PHASES and switch_to_manual(rt, phase):
        run.fatal_strikes = 0
        run.sgate_prev = run.sgate                         # 건수는 새 게이트가 이어받는다(carry)
        run.sgate = None                                   # 수동 경로 = 웹 노출(엄격 규칙) — 게이트를 다시 연다
        return
    run.fatal_strikes += 1
    if run.fatal_strikes >= FATAL_STRIKES:
        left = len(run.pending) + sum(len(p.items) for p in run.pinned)
        br = "BR-LOGIN-TIMEOUT" if phase == "login_required" else PHASE_BR.get(phase, "")
        run.stop("fatal", resumable=True, reason=phase if phase else None, br=br, done=len(run.committed), left=left)
        rt.fatal_stop = phase or "fatal"
        return
    recover(rt, phase)


def after_ask(run, items, depth: int, ar, *, pinned: Pinned | None = None, resend_done: int = 0) -> int:
    """질의 결과 반영 — 답 커밋 · 빠진·무효 재큐 · 반분 · 연기 · 서킷 · 예산 적응. 반환: 새 커밋 수."""
    spec, rt, cfg = run.spec, run.rt, run.rt.cfg
    run.statuses[ar.status] += 1
    run.rungs.update(ar.rungs)
    run.stats["asks"] += 1
    run.stats["sends"] += ar.sends
    run.stats["rung_skipped"] += ar.rung_skipped
    run.dropped.update(ar.dropped)
    if ar.model_used and ar.model_used not in run.models:
        run.models.append(ar.model_used)
    if ar.status != "transport_fatal":
        run.fatal_strikes = 0
    newly = 0
    by_n = dict(enumerate(items, 1))
    rid = ar.rids[-1] if ar.rids else ""
    if spec.kind == "lookup" and ar.status in ("ok", "partial", "truncated") and ar.answers and ar.side != "input":
        it, ans = items[0], ar.answers.get(1) or next(iter(ar.answers.values()))
        if rt.caps is not None and not run.lookup_ok_seen:
            run.lookup_ok_seen = True
            rt.caps.observe_ok(spec.id)
            _recompute_env(rt)
        if spec.is_full(ans, ar.status, run.ctx):
            kids = _child_items(run, it)
            if kids:
                commit_rule(run, it, "split", ans={"split": [k.key for k in kids]})
                for k in kids:
                    run.items.append(k)
                    run.by_key[k.key] = k
                for k in reversed(kids):                          # 조회는 구간 하나 = 질의 하나
                    run.pinned.appendleft(Pinned([k], depth + 1))
                newly = 1
            else:
                ans = dict(ans, capped=True)
                run.caps_hit["lookup_rows"] += 1
                commit_answer(run, it, ans, rid)
                newly = 1
        else:
            commit_answer(run, it, ans, rid)
            newly = 1
        update_circuit(run, ar, newly)
        return newly
    for n, ans in sorted(ar.answers.items()):
        it = by_n.get(n)
        if it is not None and it.ck not in run.committed:
            commit_answer(run, it, ans, rid)
            newly += 1
    _update_est(run, ar, len(items))
    unresolved = [it for it in items if it.ck not in run.committed]
    if ar.status == "truncated" and ar.side == "input":
        run.pack_in = BG.shrink_in(ar.injected_chars or ar.in_chars, cfg)
        _requeue_front(run, unresolved)
        return newly
    if ar.status == "transport_fatal":
        _requeue_front(run, unresolved)
        handle_fatal(run, ar)
        return newly
    if ar.status == "refusal":
        if spec.kind == "lookup" and ar.reason == "unavailable":
            reason = "R-NOLIC" if ar.lic == "nolic" else "R-NOCONN"
            if rt.caps is not None:
                from lm27.bridge.capability import LABEL_KO
                rt.caps.observe_unavailable(spec.id, reason)
                for code, sid in rt.caps.events:
                    label = LABEL_KO.get(sid, sid)
                    rt.notify(code, source=label, target=label, confirmDays=cfg.confirm_count,
                              ttlDays=cfg.confirm_ttl_days)
                rt.caps.events = []
                _recompute_env(rt)
            _requeue_front(run, unresolved)
            run.stop("refused", resumable=True, reason=reason)
            return newly
        for it in unresolved:
            commit_rule(run, it, "ai_refused")
        if unresolved:
            rt.notify("BR-REFUSED", n=len(unresolved))
        return newly
    inv = {by_n[n].key: code for n, code in ar.invalid.items() if n in by_n}
    for it in unresolved:
        it.asks += 1
        code = inv.get(it.key)
        it.notes = (B.note_for(code),) if code and B.note_for(code) else ()
    alive = [it for it in unresolved if it.asks < cfg.max_asks_per_item]
    for it in unresolved:
        if it.asks >= cfg.max_asks_per_item:
            commit_rule(run, it, "ai_failed")
    manual = getattr(rt.transport, "kind", "") == "manual"
    deferred_once = any(it.deferred for it in items) or bool(pinned and pinned.deferred)
    if manual and ar.status in MANUAL_RESEND and not resend_done and alive:
        run.pinned.appendleft(Pinned(alive, depth, resend=1))            # 수동: 같은 묶음을 새 rid 로 1회
    elif ar.status in ("partial", "truncated"):
        _requeue_front(run, alive)
    elif ar.status == "service_error" and not deferred_once:
        for it in alive:
            it.deferred = True
        run.pending.extend(alive)
    elif ar.status in X.WHOLE_FAIL or ar.status == "service_error":
        floor = spec.split_floor(cfg)
        can_split = (not run.circuit_soft) and depth < cfg.split_max_depth and len(alive) >= 2 * floor
        if can_split:
            h = len(alive) // 2
            run.pinned.appendleft(Pinned(alive[h:], depth + 1))
            run.pinned.appendleft(Pinned(alive[:h], depth + 1))
        else:
            run.pending.extend(alive)
    if ar.status == "truncated":
        run.trunc_out_count += 1
        run.chat.force_fresh = True
        if run.trunc_out_count % BG.TRUNC_SHRINK_EVERY == 0:
            run.pack_out = BG.shrink_out(run.pack_out)
            if getattr(run, "ctx", None) is not None:
                run.ctx.pack_out = run.pack_out           # 조회 머리말 '최대 N행' 도 줄인 예산으로(W1 통합 창 — WP-25 CR)
            BG.Adjust(rt.profile, rt.clock).shrink(spec.id)
    if ar.status == "ok":
        run.ok_streak += 1
        if run.ok_streak >= BG.OK_RECOVER_STREAK:
            run.ok_streak = 0
            BG.Adjust(rt.profile, rt.clock).recover(spec.id)
    else:
        run.ok_streak = 0
    update_circuit(run, ar, newly)
    return newly


def _recompute_env(rt: Runtime) -> None:
    """조회 결과(R-NOLIC·성공)가 기록되면 화면을 다시 읽지 않고 env 를 다시 계산(B §4.11-6)."""
    if rt.env is None or rt.caps is None:
        return
    from lm27.bridge.env import recompute
    rt.env = recompute(rt.env, rt.caps, rt.cfg, rt.clock)


# ───────────────────────── 접기·결과 봉투(B §7.10 · §7.11) ─────────────────────────
def _expand_splits(run) -> None:
    """쪼갠 조회 구간(부모 커밋 why=split)의 자식을 접기 대상에 넣는다 — 단계가 건너뛰어진 호출에서도 산출이 같게."""
    seen = {it.key for it in run.items}
    i = 0
    while i < len(run.items):
        it = run.items[i]
        c = run.store.last(it.ck)
        if c is not None and c.get("by") == "rule" and c.get("why") == "split":
            for k in _child_items(run, it):
                if k.key not in seen:
                    seen.add(k.key)
                    run.items.append(k)
                    run.by_key[k.key] = k
        i += 1


def fold(run) -> dict:
    """저장소 기준으로 ai_out 을 다시 접는다(멱등). 답이 빈 항목은 이전 산출의 같은 key 값을 덮지 않는다(B8)."""
    spec, rt = run.spec, run.rt
    if spec.kind == "lookup":
        _expand_splits(run)
    latest = {}
    for it in run.items:
        c = run.store.last(it.ck)
        if c is not None and c.get("by") in ITEM_BY:
            e = {"ans": c.get("ans"), "by": c["by"], "rid": c.get("rid"), "asks": c.get("asks"), "at": c.get("ts")}
            for k in ("why", "confirm", "reg_set"):
                if c.get(k) is not None:
                    e[k] = c[k]
        else:
            e = {"ans": spec.fallback(it, run.ctx, "pending"), "by": "rule_pending", "rid": None, "asks": it.asks,
                 "at": None}
        latest[it.key] = e
    path = rt.paths.ai_out(spec.id)
    prev = fsio.read_json(path, None)
    prev_items = prev.get("items") if isinstance(prev, dict) and isinstance(prev.get("items"), dict) else {}
    for k, e in latest.items():
        p = prev_items.get(k)
        if e.get("ans") is None and isinstance(p, dict) and p.get("ans") is not None and e.get("why") != "split":
            latest[k] = p
    out = spec.fold(run.ctx, latest)
    try:
        rel = os.path.relpath(J.run_file(rt.paths, rt.run_id, "result", spec.id), rt.paths.root)
    except ValueError:
        rel = ""
    out["result"] = rel.replace("\\", "/")
    if rt.write_files and run.items:                      # 입력이 없으면 이전 산출을 빈 값으로 덮지 않는다(B8)
        try:
            fsio.write_atomic(path, out)
        except OSError:
            run.stats["fold_write_failed"] += 1           # 실패하면 이전 파일 유지(B8)
    return latest


def _counts_of(latest: dict) -> dict:
    c = Counter()
    for e in latest.values():
        if e.get("why") == "split":
            continue
        c["total"] += 1
        by = e.get("by")
        c[by] += 1
        why = str(e.get("why") or "")
        if by == "rule":
            if why in ("ai_failed", "ai_refused"):
                c["failed"] += 1
            elif why.startswith("gated:"):
                c["gated"] += 1
            elif why == "oversize":
                c["oversize"] += 1
    return c


def _utc(clock) -> str:
    return datetime.fromtimestamp(int(clock.now()), tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_result(run, latest: dict) -> dict:
    """결과 봉투(계약 §8.5 공통 필드 + B §7.11). 항등식: total = ai + manual + rule + pending, ok = ai + manual,
    failed·gated·oversize ⊂ rule."""
    from lm27.collect.stage_result import build_stage_result
    rt, spec = run.rt, run.spec
    c = _counts_of(latest)
    total, ai, man, rule, pend = c["total"], c["ai"], c["manual"], c["rule"], c["rule_pending"]
    ok = ai + man
    if total != ai + man + rule + pend or ok != ai + man or c["failed"] + c["gated"] + c["oversize"] > rule:
        raise AssertionError("결과 봉투 항등식이 깨졌습니다")
    if run.skipped:
        state = "skipped"
    elif run.stop_kind in ("manual_wait", "budget"):
        state = "partial"
    elif run.stop_kind and total > 0 and ok == 0:
        state = "failed"
    elif run.stop_kind or pend > 0 or c["failed"] > 0:
        state = "partial"
    else:
        state = "done"
    stop_kind = run.stop_kind if state != "done" else None
    reason = run.skipped or run.stop_reason
    env = rt.env.brief() if rt.env is not None and hasattr(rt.env, "brief") else {}
    fields = {
        "state": state, "items_total": total, "items_ok": ok, "items_failed": c["failed"], "items_pending": pend,
        "stop_kind": stop_kind, "resumable": bool(run.resumable) if stop_kind else state == "partial",
        "reason": reason or None, "hint": run.hint[:200] if run.hint else "",
        "caps_hit": {k: int(v) for k, v in sorted(run.caps_hit.items()) if v} or {},
        "updated": _utc(rt.clock),
        "counts": {k: int(v) for k, v in sorted(run.stats.items())},
        "items_ai": ai, "items_manual": man, "items_rule": rule, "items_gated": c["gated"],
        "items_oversize": c["oversize"], "dropped": {k: int(v) for k, v in sorted(run.dropped.items())},
        "asks": int(run.stats["asks"]), "sends": int(run.stats["sends"]),
        "rungs": {k: int(run.rungs.get(k, 0)) for k in ("0", "1", "2")},
        "statuses": {k: int(v) for k, v in sorted(run.statuses.items())},
        "sec": round(rt.clock.mono() - run.t0, 1), "pack": {"in": int(run.pack_in), "out": int(run.pack_out)},
        "model": {"wanted": rt.cfg.model_for(spec.model_class), "used": list(run.models)},
        "transport": getattr(rt.transport, "kind", "none") or "none", "env": env,
        "gate": run.sgate.summary() if run.sgate is not None else {},
    }
    if run.error_type:
        fields["error_type"] = run.error_type[:80]
    return build_stage_result(rt.run_id, spec.id, **fields)


def write_result(run, obj: dict) -> None:
    if run.rt.write_files:
        J.write_json(J.run_file(run.rt.paths, run.rt.run_id, "result", run.spec.id), obj)


# ───────────────────────── 단계 실행(B §7.16) ─────────────────────────
def _stage_ctx(spec, rt: Runtime, pack_out: int) -> B.StageCtx:
    ctx = B.StageCtx(run_id=rt.run_id, registry=rt.registry, registry_version=rt.registry_version, env=rt.env,
                     cfg=rt.cfg, clock=rt.clock, pack_out=pack_out)
    ctx.codes_map = dict(spec.code_sets(ctx) or {})
    return ctx


def _calib_for(rt: Runtime, spec):
    from lm27.bridge import calibrate as CAL
    if rt.profile is None:
        return None
    return CAL.current(rt.profile.load(), rt.profile_id, rt.cfg.model_for(spec.model_class), rt.edge_major, rt.cfg,
                       rt.clock)


def _skip_reason(spec, rt: Runtime) -> str | None:
    cfg = rt.cfg
    if not cfg.stage_on(spec.id) or cfg.mode == "off" or rt.transport is None:
        return "disabled"
    if rt.fatal_stop:
        return "fatal"
    if rt.env is not None and rt.env.web_exposed and cfg.web_exposure_policy == "block":
        rt.notify("BR-WEB-BLOCK")
        return "web_exposed"
    if spec.kind == "lookup":
        if rt.caps is not None:
            st = rt.caps.state(spec.id)
            if st == "unavailable" or (st == "suspect" and rt.caps.checked_today(spec.id)):
                return "capability_unavailable"
        if rt.env is not None and rt.env.work_mode == "web":
            rt.notify("BR-WEB-MODE")
            return "mode_web"
    return None


def run_stage(spec, rt: Runtime, plan=None, idx: int = 0, n: int = 1, *, imports=()) -> dict:
    """단계 하나 → 결과 봉투 dict(파일도 쓴다). ``imports`` = 수동 반입 [(목록 묶음, 봉투)] — 같은 규칙으로 먼저 반영.
    모든 종료 경로(정상·예외·중지)에서 접기와 결과 봉투를 남긴다(G-B10)."""
    from lm27.bridge.journal import Journal, Store
    cfg, clock = rt.cfg, rt.clock
    plan = plan or BG.call_plan(cfg, clock, n)
    run = StageRun(spec, rt, _stage_ctx(spec, rt, cfg.answer_max_chars))
    run.store = Store(rt.paths, spec.id, clock).load()
    run.journal = Journal(rt.paths, rt.run_id, spec.id, clock, enabled=rt.write_files)
    box = {"hb": None}
    try:
        run.deadline = BG.stage_deadline(plan, idx, n, cfg, clock)
        _stage_body(run, imports, box)
    except StageConfigError as e:
        run.stop("header", resumable=False, reason=str(e) or "header_too_large", stage=spec.id)
    except StageGateError as e:
        run.stop("gate", resumable=False, reason=e.reason, stage=spec.id,
                 types=", ".join(sorted(e.counts)) or "-")
    except KeyboardInterrupt:
        run.stop("cancelled", resumable=True)
        raise
    except Exception as e:  # noqa: BLE001 — 예상 못 한 예외도 결과 봉투는 쓴다(B §7.16)
        run.error_type = type(e).__name__
        run.stop("fatal", resumable=True, reason="exception")
    finally:
        if box["hb"] is not None:
            box["hb"].stop()
        if run.sgate is None and run.sgate_prev is not None:     # 수동 전환 직후 끝남 — 앞 게이트 건수를 그대로
            run.sgate, run.sgate_prev = run.sgate_prev, None
        if run.sgate is not None:
            run.sgate.flush_answer_audit()
        latest = fold(run)
        result = build_result(run, latest)
        write_result(run, result)
        rt.ev("stage_end", stage=spec.id, state=result["state"], rc=result["rc"])
        run.result = result
    return run.result


def _stage_body(run, imports, box) -> None:
    spec, rt, cfg, clock = run.spec, run.rt, run.rt.cfg, run.rt.clock
    items, dropped = load_ai_in(rt.paths, spec)
    run.dropped.update(dropped)
    run.items = list(items)
    run.by_key = {it.key: it for it in items}
    if run.store.torn_lines:
        run.stats["torn_lines"] += run.store.torn_lines
    reason = _skip_reason(spec, rt)
    if reason == "fatal":                                     # 앞 단계가 2-strike 로 멈춤 — 남은 단계는 skipped(fatal)
        run.skipped = rt.fatal_stop or "fatal"
        run.stop_kind, run.resumable = "fatal", True
        return
    if reason:
        run.skipped = reason
        return
    if not items and not imports:
        run.skipped = "no_input"
        return
    run.store.compact()
    factor = BG.Adjust(rt.profile, clock).factor(spec.id)
    run.pack_in, run.pack_out = BG.initial_pack(cfg, _calib_for(rt, spec), factor)
    run.ctx.pack_out = run.pack_out
    awaiting, imported = frozenset(), set()
    if getattr(rt.transport, "kind", "") == "manual":
        mf = rt.transport.manifest
        asked = mf.asked(spec.id)
        for it in run.items:
            it.asks = int(asked.get(it.ck, 0))
        imported = {i.get("ck") for b, _env in imports for i in b.get("items") or []}
        awaiting = frozenset(ck for ck in mf.awaiting_cks(spec.id) if ck not in imported)
        rt.transport.ck_of = {it.key: it.ck for it in run.items}
    seen_names_from_store(run)
    queue = [it for it in resume_filter(run, items, awaiting=awaiting) if it.ck not in imported]
    run.text_fields = _text_fields(spec, queue or items)
    run.sgate = rt.gate_base.for_stage(spec.id, web_exposed=_web(rt)) if rt.gate_base is not None else None
    if imports:
        _apply_imports(run, imports)                      # 빠진·무효 항목은 대기열·고정 묶음으로 돌아온다
    queue = _gate_all(run, queue)                         # ① 항목 게이트(+ 웹 노출 엄격 규칙) — 보낼 항목 전부
    run.pending.extend(_order(spec, queue))
    rt.ev("stage_start", stage=spec.id, total=len(run.pending) + sum(len(p.items) for p in run.pinned),
          resume_skipped=int(run.stats["resume_skipped"]))
    box["hb"] = _heartbeat(rt, spec, len(run.pending))
    _loop(run, box["hb"])


def _gate_all(run, queue) -> list:
    """대기열(``queue``)과 이미 대기열·고정 묶음에 들어온 항목(수동 반입의 재질의)을 ① 게이트에 한 번에 통과시킨다.
    걸린 항목은 ``gated:<사유>`` 규칙 커밋(confirm). 반환: 게이트를 통과한 새 대기열 항목(재가림 값)."""
    spec, rt = run.spec, run.rt
    if run.sgate is None:
        return list(queue)
    back = list(run.pending)
    pins = list(run.pinned)
    run.pending.clear()
    run.pinned.clear()
    every = back + [it for p in pins for it in p.items] + list(queue)
    if not every:
        return []
    kept, gated = run.sgate.items(spec, every, run.text_fields)
    for key, why in gated:
        it = run.by_key.get(key)
        if it is not None and it.ck not in run.committed:
            commit_rule(run, it, f"gated:{why}", final=True, confirm=True)
    if gated:
        rt.notify("BR-GATE", n=len(gated),
                  hits=", ".join(f"{k} {v}" for k, v in sorted(Counter(w for _k, w in gated).items())))
    if run.sgate.web_exposed and rt.cfg.web_exposure_policy == "strict":
        rt.notify("BR-WEB-STRICT", n=sum(1 for _k, w in gated if w == "web_combo"))
    by = {it.key: it for it in kept}
    for it in kept:
        run.by_key[it.key] = it
    run.pending.extend(by[it.key] for it in back if it.key in by)
    for p in pins:
        its = [by[it.key] for it in p.items if it.key in by]
        if its:
            run.pinned.append(Pinned(its, p.depth, p.deferred, p.resend))
    return [by[it.key] for it in queue if it.key in by]


def _web(rt: Runtime) -> bool:
    return bool(getattr(rt.env, "web_exposed", True)) if rt.env is not None else True


def _text_fields(spec, items) -> tuple:
    from lm27.bridge.gate import text_fields_of
    return text_fields_of(spec, items)


def _order(spec, queue) -> list:
    """대기열 순서 — 같은 묶음 키를 한 질의에 모으는 단계는 group 끼리(안에서는 입력 순서), 그 밖은 입력 순서(상류의 우선순위)."""
    if spec.group_strict:
        first = {}
        for i, it in enumerate(queue):
            first.setdefault(it.group, i)
        return sorted(queue, key=lambda it: first[it.group])
    return list(queue)


def seen_names_from_store(run) -> None:
    nf = run.spec.names_field
    if not nf:
        return
    for c in run.store.all_last().values():
        a = c.get("ans")
        if c.get("by") in ("ai", "manual") and isinstance(a, dict) and isinstance(a.get(nf), str) and a.get(nf):
            run.names[a[nf]] += 1


class _NullHB:
    def update(self, **kw):
        pass

    def tick(self):
        return False

    def stop(self):
        pass


def _heartbeat(rt: Runtime, spec, total: int):
    """30초 progress(계약 §8.6) — 실제 시계일 때만 배경 스레드, 가상 시계는 질의마다 tick."""
    if rt.emit is None:
        return _NullHB()
    from lm27.util.events import HEARTBEAT_SEC, Heartbeat
    hb = Heartbeat(HEARTBEAT_SEC, stage=spec.id, total=total, clock=rt.clock.mono)
    if rt.heartbeat and not getattr(rt.clock, "virtual", False):
        hb.start()
    return hb


def _loop(run, hb) -> None:
    spec, rt, cfg = run.spec, run.rt, run.rt.cfg
    while not run.stopped:
        if not BG.can_ask(run.deadline, cfg, rt.clock):
            if run.pending or run.pinned:
                left = len(run.pending) + sum(len(p.items) for p in run.pinned)
                run.stop("budget", resumable=True, stage=spec.id, done=len(run.committed),
                         total=len(run.committed) + left, left=left)
            break
        nb = next_batch(run)
        if nb is None:
            break
        items, depth, pinned, compact, ctxb = nb
        manual = getattr(rt.transport, "kind", "") == "manual"
        if manual:
            rt.transport.hint = {"depth": depth, "resent": pinned.resend if pinned else 0}
        notes = sorted({x for it in items for x in it.notes if x})
        rt.seq += 1
        ac = X.AskCtx(cfg=cfg, clock=rt.clock, transport=rt.transport, gate=run.sgate, journal=run.journal,
                      tracer=rt.tracer, chat=run.chat, used_rids=rt.used_rids, stage_deadline=run.deadline,
                      circuit_soft=run.circuit_soft, stage_ctx=run.ctx, context_block=ctxb, compact=compact,
                      note="; ".join(notes), depth=depth, seq=rt.seq, raw_capture=bool(cfg.raw_capture),
                      rawcap_dir=fsio.bridge_file(rt.paths, "rawcap") if cfg.raw_capture else None,
                      web_exposed=_web(rt), run_id=rt.run_id)
        ar = X.ask(spec, items, ac)
        if ar.status == "manual_pending":
            run.stats["asks"] += 1
            run.stats["sends"] += ar.sends
            run.stats["exported"] += 1
            if rt.transport.open_count() >= cfg.manual.max_open_batches or not (run.pending or run.pinned):
                run.stop("manual_wait", resumable=True, k=rt.transport.open_count())
                break
            continue
        after_ask(run, items, depth, ar, pinned=pinned, resend_done=pinned.resend if pinned else 0)
        if run.sgate is None and rt.gate_base is not None:          # 수동 전환 뒤 — 웹 노출로 게이트를 다시 연다
            run.sgate = rt.gate_base.for_stage(spec.id, web_exposed=_web(rt))
            run.sgate.carry(run.sgate_prev)
            run.sgate_prev = None
            _gate_all(run, ())                                       # 남은 항목을 엄격 규칙으로 다시 거른다
            if getattr(rt.transport, "kind", "") == "manual":
                rt.transport.ck_of = {it.key: it.ck for it in run.items}
        hb.update(done=len(run.committed), total=len(run.items), asks=int(run.stats["asks"]), last=ar.status)
        rt.ev("progress", stage=spec.id, done=len(run.committed), total=len(run.items), asks=int(run.stats["asks"]),
              last=ar.status)
        hb.tick()


def _apply_imports(run, imports) -> None:
    """수동 반입(B §10.4) — 열린 묶음마다 같은 분류·같은 커밋·재큐 규칙. 반입한 묶음은 answered(프롬프트 파일 삭제)."""
    from lm27.bridge.transport import SendResult
    spec, rt = run.spec, run.rt
    mf = rt.transport.manifest
    ingest = (lambda a: run.sgate.answer(a, spec.item_schema)) if run.sgate is not None else None
    for b, env in imports:
        items, ids, id_to_key, by_n = [], [], {}, {}
        for i in b.get("items") or []:
            it = run.by_key.get(i.get("key"))
            if it is None or it.ck != i.get("ck"):
                continue                                     # 그 사이 입력이 바뀐 항목은 새로 묻는다
            n = int(i.get("n") or 0)
            items.append(it)
            ids.append(n)
            id_to_key[n] = it.key
            by_n[n] = it
        meta = X.AsmMeta(rid=b["rid"], item_ids=ids, id_to_key=id_to_key, items=by_n)
        res = SendResult(phase="replied", body=env.segment, done_by="manual", pick="manual")
        status, info = X.classify(spec, res, meta, run.ctx, ingest)
        ar = X.AskResult(status=status, reason=info.get("reason") or "", answers=info["answers"],
                         missing=list(info["missing"]), invalid=dict(info["invalid"]), dup=info["dup"],
                         extra=info["extra"], extra_fields=info["extra_fields"], rids=[b["rid"]], sends=0,
                         side=info.get("side") or "", lic=info.get("lic") or "", dropped=info["dropped"],
                         reply_len=len(env.segment))
        order = [by_n[n] for n in sorted(by_n)]
        before = len(run.committed)
        after_ask(run, order, int(b.get("depth") or 0), ar, resend_done=int(b.get("resent") or 0))
        mf.answer(b, status, {"ok": len(run.committed) - before, "retry": len(order) - (len(run.committed) - before)})
        run.stats["imported"] += 1
        run.journal.write("imported", rid=b["rid"], status=status, ok=len(info["answers"]),
                          missing=list(info["missing"]))
    mf.save()


# ───────────────────────── 호출 1회 ─────────────────────────
def make_runtime(paths, run_id: str, *, cfg, clock, transport=None, gate_base=None, env=None, caps=None, profile=None,
                 tracer=None, notices=None, emit=None, registry=None, raw_cfg=None, pc_id=None,
                 write_files: bool = True) -> Runtime:
    """시험·내부용 조립(의존을 모두 주입). 실제 호출은 ``open_runtime``."""
    from lm27.bridge.capability import Capabilities
    if caps is None:
        caps = Capabilities(profile, cfg, clock)
    rt = Runtime(paths=paths, cfg=cfg, clock=clock, run_id=run_id, transport=transport, gate_base=gate_base, env=env,
                 caps=caps, profile=profile, tracer=tracer, notices=notices or Notices(), emit=emit, registry=registry,
                 registry_version=B.registry_version(registry), raw_cfg=raw_cfg, pc_id=pc_id, write_files=write_files)
    if profile is not None:
        rt.profile_id = profile.profile_id()
    if env is None:
        from lm27.bridge.env import manual_env
        rt.env = manual_env(clock)
    return rt


def run_stages(rt: Runtime, specs) -> dict:
    """단계들을 차례로(같은 프로세스·같은 세션) → {단계 id: 결과 봉투}. 끝에 조회 능력 기록(capabilities.json·PC 기록)."""
    specs = list(specs)
    plan = BG.call_plan(rt.cfg, rt.clock, len(specs))
    results = {}
    for idx, spec in enumerate(specs):
        results[spec.id] = run_stage(spec, rt, plan, idx, len(specs))
    finish(rt, results)
    return results


def finish(rt: Runtime, results: dict) -> None:
    """호출 끝: 조회 능력 내보내기(조회 단계를 돌렸을 때만)."""
    if rt.caps is None or not rt.write_files:
        return
    if any(sid in results for sid in ("lookup_mail", "lookup_teams", "lookup_calendar")) or rt.caps.observed:
        J.write_json(J.run_file(rt.paths, rt.run_id, "capabilities"), rt.caps.export())
        rt.caps.record_pc(rt.paths, rt.pc_id, rt.raw_cfg)


def worst_rc(results: dict) -> int:
    from lm27.collect.stage_result import worst_rc as _w
    return _w([int(r.get("rc", 1)) for r in results.values() if isinstance(r, dict) and r])


def manual_import(text: str, *, rt: Runtime, specs: dict) -> dict:
    """붙여넣은 답 반입(B §10.4) → 보고 ``{results, rejected, error, open, committed, retry, rc}``.

    봉투를 rid 로 나눠 열린 묶음과 맞추고(순서 무관), 단계마다 ``run_stage(imports=…)`` 로 같은 규칙을 적용한 뒤 남은 항목을
    다음 수동 묶음으로 내보낸다. 목록에 없는 rid 는 반입하지 않는다(BR-MANUAL-RID — 저장소 변화 없음)."""
    from lm27.bridge import jsonx
    from lm27.bridge.env import manual_env
    from lm27.bridge.manual import ManualTransport
    if getattr(rt.transport, "kind", "") != "manual":
        mt = ManualTransport(rt.paths, rt.cfg, rt.clock, run_id=rt.run_id)
        mt.open()
        rt = replace(rt, transport=mt, env=manual_env(rt.clock))       # 반입은 수동 경로 규칙(웹 노출 가정)으로
    mf = rt.transport.manifest
    envs = jsonx.all_envelopes(text)
    report = {"results": [], "rejected": [], "error": None, "open": mf.open_count(), "committed": 0, "retry": 0,
              "rc": 1}
    if not envs:
        rt.notify("BR-MANUAL-NOENV")
        report["error"] = "BR-MANUAL-NOENV"
        return report
    opened = {b["rid"]: b for b in mf.open_batches()}
    by_stage: dict = {}
    for env in envs:
        b = opened.get(env.rid)
        if b is None or b.get("stage") not in specs:
            prev = mf.by_rid(env.rid)
            why = "already" if prev is not None and prev.get("state") == "answered" else "BR-MANUAL-RID"
            report["rejected"].append({"rid": env.rid, "why": why})
            if why == "BR-MANUAL-RID":
                rt.notify("BR-MANUAL-RID")
            continue
        by_stage.setdefault(b["stage"], []).append((b, env))
    for sid in sorted(by_stage):
        spec = specs[sid]
        before = {b["rid"]: b.get("state") for b, _e in by_stage[sid]}
        res = run_stage(spec, rt, None, 0, 1, imports=by_stage[sid])
        for b, _env in by_stage[sid]:
            r = b.get("result") or {}
            report["results"].append({"rid": b["rid"], "stage": sid, "status": r.get("status", ""),
                                      "ok": int(r.get("ok", 0)), "retry": int(r.get("retry", 0)),
                                      "was": before.get(b["rid"])})
            report["committed"] += int(r.get("ok", 0))
            report["retry"] += int(r.get("retry", 0))
        report.setdefault("stages", {})[sid] = {"state": res.get("state"), "rc": res.get("rc")}
    report["open"] = mf.open_count()
    imported = len(report["results"])
    report["rc"] = 1 if imported == 0 else (2 if report["open"] > 0 else 0)
    if imported:
        rt.notify("BR-MANUAL-DONE", ok=report["committed"], retry=report["retry"], k=report["open"])
    return report


def iso_stamp(rt: Runtime) -> str:
    return iso_now(rt.clock)


# ───────────────────────── 실제 호출 조립 ─────────────────────────
def resolve_specs(stage_ids=None) -> list:
    """단계 등록부(``lm27.bridge.stages.REGISTRY`` — WP-25)에서 단계 객체를 고른다. 등록부가 없으면 LookupError."""
    import importlib
    mod = importlib.import_module("lm27.bridge.stages")
    reg = getattr(mod, "REGISTRY", None)
    if reg is None:
        raise LookupError("단계 등록부(lm27.bridge.stages.REGISTRY)가 아직 없습니다")
    if isinstance(reg, dict):
        table = dict(reg)
    else:
        table = {getattr(s, "id", ""): s for s in reg}
    table = {k: (v() if isinstance(v, type) else v) for k, v in table.items()}
    if not stage_ids:
        return [table[k] for k in table if table[k].id]
    out = []
    for sid in stage_ids:
        if sid not in table:
            raise LookupError(f"모르는 단계: {sid}")
        out.append(table[sid])
    return out


def open_runtime(paths=None, run_id: str | None = None, *, mode: str | None = None, clock=None, environ=None,
                 session_factory=None, transport=None, emit=None, notices=None, env=None, registry=None, gate_base=None,
                 pc_id=None, calibrate_model: str | None = None, heartbeat: bool = True, raw_cfg=None) -> Runtime:
    """실제 호출 1회 조립: 설정 → 전송(스텁 ``LM_COPILOT_STUB`` · 수동 · CDP 세션) → 환경 → 레지스트리·게이트 → 자동 보정.
    ``raw_cfg``(``lm27.config.Cfg``)·``registry``·``gate_base``·``pc_id``·``session_factory`` 는 시험 주입점.
    전송을 연 뒤의 어느 단계(키·레지스트리·게이트·자동 보정 3~6분)에서든 예외(Ctrl+C·CdpError 포함)가 나면 여기서 연
    전송·세션을 닫고 다시 올린다 — 남은 Edge 를 다음 실행이 '재사용'해 closeOnExit 가 영영 적용되지 않던 결함(W1b) 방지."""
    from lm27.bridge import gate as G
    from lm27.bridge import settings as S
    from lm27.bridge import transport_stub
    from lm27.bridge.capability import Capabilities
    from lm27.bridge.clock import default_clock
    from lm27.bridge.env import manual_env
    from lm27.bridge.session import BridgeProfile
    from lm27.bridge.trace import Tracer
    from lm27.config import load_config
    from lm27.util import events
    from lm27.util.tz import new_run_id
    if paths is None:
        from lm27.paths import Paths
        paths = Paths()
    run_id = run_id or new_run_id()
    raw_cfg = raw_cfg if raw_cfg is not None else load_config(paths)
    cfg = S.from_cfg(raw_cfg)
    clock = clock or default_clock()
    emit = events.emit if emit is None else emit
    notices = notices or Notices(emit)
    environ = os.environ if environ is None else environ
    profile = BridgeProfile(paths)
    tracer = Tracer(paths, cfg, clock, run_id=run_id)
    mode = mode or cfg.mode
    sess = None
    owned = transport is None                          # 여기서 만든 전송·세션만 닫는다(주입은 호출자 몫)
    made: dict = {}
    try:
        if transport is None:
            transport = transport_stub.from_env(environ)
            made["transport"] = transport
        if transport is None and mode == "manual":
            from lm27.bridge.manual import ManualTransport
            transport = ManualTransport(paths, cfg, clock, run_id=run_id)
            made["transport"] = transport
            transport.open()
        elif transport is None and mode == "auto":
            from lm27.bridge.session import EdgeSession
            from lm27.bridge.transport import CdpTransport
            mk = session_factory or (lambda: EdgeSession.open("bridge", run_id, paths=paths, cfg=cfg, clock=clock,
                                                              notices=notices, tracer=tracer, environ=environ))
            sess = mk()
            made["sess"] = sess
            transport = CdpTransport(sess)
            made["transport"] = transport
            transport.open()
        if pc_id is None:
            pc_id = _pc_id(paths)
        kr = G.load_keys(paths) if (registry is None or gate_base is None) else None
        if registry is None:
            registry = _registry(paths, raw_cfg, kr)
        if gate_base is None:
            gate_base = G.GateBase.open(paths, raw_cfg, kr=kr, registry=registry, pc_id=pc_id,
                                        policy=cfg.web_exposure_policy, clock_iso=G.clock_iso_of(clock))
        caps = Capabilities(profile, cfg, clock)
        rt = make_runtime(paths, run_id, cfg=cfg, clock=clock, transport=transport, gate_base=gate_base, env=env,
                          caps=caps, profile=profile, tracer=tracer, notices=notices, emit=emit, registry=registry,
                          raw_cfg=raw_cfg, pc_id=pc_id)
        made["rt"] = rt
        rt.heartbeat = heartbeat
        if sess is not None:
            rt.edge_major = int(getattr(sess.edge, "major", 0) or 0)
            st = getattr(sess, "state", "")
            if st in MANUAL_SWITCH_PHASES and cfg.auto_manual_fallback:
                switch_to_manual(rt, st)
            elif env is None:
                rt.env = sess.env or manual_env(clock)
            if st == "ready" and cfg.auto_calibrate and calibrate_model:
                from lm27.bridge import calibrate as CAL
                CAL.run_calibration(rt, model_class=calibrate_model)
        return rt
    except BaseException:
        if owned:
            _close_opened(made.get("rt"), made.get("transport"), made.get("sess"))
        raise


def _close_opened(rt, transport, sess) -> None:
    """open_runtime 실패 정리 — 연 전송(수동 전환 뒤면 rt 의 새 전송)과 세션을 닫는다. 정리 중 오류는 삼키고 원 예외를
    올린다(W1b — 우리가 띄운 디버그 포트 Edge·CDP 소켓·session.lock.json 이 남지 않게)."""
    for t in dict.fromkeys(x for x in (getattr(rt, "transport", None), transport) if x is not None):
        try:
            t.close()
        except Exception:                                # noqa: BLE001 — 정리 실패가 원 예외를 가리지 않게
            pass
    if sess is not None and not getattr(sess, "_closed", True):
        try:
            sess.close()
        except Exception:                                # noqa: BLE001
            pass


def close_runtime(rt: Runtime) -> None:
    try:
        if rt.transport is not None:
            rt.transport.close()
    except OSError:
        pass
    if rt.manual_switched and getattr(rt.transport, "kind", "") == "manual":
        rt.notify("BR-MANUAL-SWITCH", k=rt.transport.open_count())


def _pc_id(paths):
    from lm27.bundle.ids import identify_pc
    try:
        return identify_pc(paths).pc_id
    except (OSError, ValueError):
        return None


def _registry(paths, raw_cfg, kr):
    """유효 레지스트리(네트워크 없음·자동 대응 기록 없음) — 단계 머리말·코드 검증·정제 사전 가명화 출처."""
    from lm27.hier.registry import load_effective
    reg, _status = load_effective(paths, raw_cfg, kr=kr, persist=False)
    return reg


def inbox_import(rt: Runtime, specs: dict) -> list:
    r"""``copilot_manual\inbox\*.txt`` 반입(브리지 시작 때마다). 반환: 보고 목록.

    훑은 파일은 **결과와 관계없이 1회 시도한 뒤 지운다** — 봉투 없는 답(BR-MANUAL-NOENV)·다른 rid·CP949(메모장 'ANSI')로
    저장한 답도. 붙여넣은 코파일럿 답 원문(조회 단계면 제목·이름·전화)이 디스크에 무기한 남지 않게(B9 · B §9.5 — W1b).
    UTF-8·CP949 둘 다 아닌 글은 봉투 없음과 같이 알리고 지운다. 잠겨 읽지 못한 파일만 다음 시작에 다시 본다. 확장자와
    관계없이 inbox 의 모든 파일은 ``bridge.manual.ttlDays`` 가 지나면 지운다(B §2.4 TTL)."""
    from lm27.bridge.manual import inbox_dir, scan_inbox
    fsio.prune_ttl(inbox_dir(rt.paths), rt.cfg.manual.ttl_days, rt.clock)
    out = []
    for p, text, st in scan_inbox(rt.paths):
        if st == "io":
            continue
        try:
            out.append(manual_import(text or "", rt=rt, specs=specs))
        finally:
            try:
                fsio.remove(p)
            except OSError:                                # 잠김(편집기가 연 채) — 다음 시작에 다시(이미 반입한 rid 는 거부)
                pass
    return out
