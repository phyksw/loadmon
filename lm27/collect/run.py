# -*- coding: utf-8 -*-
r"""[수집] 한 번의 흐름 — ``collect_here``(계약 §2.5 · §7.1 · §7.3 · §8.1~§8.5 · X-300 · X-311 · X-315, TAB §1.7 · C §8 ·
D-6 · D-7 · D-14). ``lm27 collect`` · ``LoadMonitor27-수집.bat``(``collect --auto``) · 화면 [수집]이 부른다. 무질문.

흐름(계약 §2.5 순서 — 번들 확인 → 에이전트 확인 → 탐침 → 수확 요청 → 전경 수집기 → 내보내기 → 파생 재생성 → 대기 업로드):
  0. ``identify_pc`` · P-BUNDLE(``probe_bundle_location``). 번들이 읽기 전용이면 번들 쓰기를 하지 않고 rc 3 +
     R-BUNDLE-READONLY 로 끝낸다(단계 결과도 ``data\`` 아래라 쓰지 못한다).
  1. ``lock("collect-init")``: ``bundle.json``·키링(없으면 만든다 — P §9.5) · ``ensure_pc_dir``(host_class 포함) ·
     미처리 소급 가림(``redact_rewrite_own``).
  2. ``ensure_agent``(번들 잠금 없이 — 설치·판 올림·등록·생존 자동 복구, 사람에게 묻지 않는다).
  3. ``probe`` 단계: 탐침 → ``lock("fg-write")`` 안에서 pc.json 능력 기록(``record_probes``).
  4. 계획(``lm27.collect.plan.stage_plan``) — 역할(백필 PC·클라우드PC)·탐침·'불가(확정)'.
  5. ``pc_bundle``: 상주 샘플러 생존 · 수확(``request_harvest_now`` → ``harvest_done.json`` — 에이전트가 없거나 시간 안에 끝나지
     않으면 ``.harvest.lock`` 을 쥐고 전경이 같은 수집기를 대신 돌린다) · git · 라이선스(옵트인).
     ``mail_local`` · ``cal_local``(COM → 색인, kind 마다 파이프 하나) · ``teams_uia_check``(에이전트가 살아 있으면 확인만,
     아니면 전경 1회) · ``import``.
  6. ``export``(``lock("export")`` — 로컬 원장 → 번들 세그먼트, 현재 규칙 재정제 훅, 사람 사전 추가분 병합) → ``derive``
     (커버리지 원장·빈칸 계획 — 잠금 없이 원자 교체).
  7. 백필 PC 면 ``backfill_owa``(메일 = 빈칸 파일, 일정 = 기간 전체) · ``backfill_teams_web`` → 내보내기·파생 다시.
     클라우드PC 면 ``copilot_lookup``(남은 빈칸만) → 내보내기·파생 다시. '첫 성공에서 멈추는 사슬'이 아니라 셀이
     ok·zero_ok 가 될 때까지 싼 경로부터 빈칸만 비싼 경로로(D-6).
  8. ``lock("collect-finish")``: 방문 기록(``touch_visit``)·논리 PC 별칭(``auto_alias``) → ``upload``(승인된 팀 묶음 대기분
     자동 전송 — ``lm27.team.queue.send_due``). 명령 rc = ``rcmap.collect_rc``(계약 §8.3 — 원장과 같은 번역).

전경 연결자(계약 §7.3 · X-300): PS 수집기와 정제 파이프(``lm27_pipe.py --kind --src --pc --mode append`` — 로컬 원장에 쓴다)를
둘 다 띄우고 잇는다. 수집기 stdin 에 ``{"_in": {"cursor", "cfg", "self_names"}}`` 한 줄을 쓰고 닫는다(커서·설정·이름을 명령줄에
싣지 않는다). 수집기 stdout 은 ``lm27.collect.watch.watch`` 로 줄마다 파이프 stdin 에 넘기고(레코드 줄 = 진전 — 정체·무진전이면
kill_tree, rc 3 + R-TRANSPORT), 수집기 EOF 뒤 파이프가 ``privacy.pipe.waitSec`` 안에 끝나지 않으면 kill_tree 하고 코드 99
(→ rc 3 + R-TRANSPORT, 계약 §8.2). 상태는 stderr 마지막 ``{"_status": {...}}``(C1 — 모르는 필드 무시, CLM 이면 파이프 요약의
``collector_status``). PY 수집기는 자식 프로세스(in-process 정제)로 띄우고 stderr ``_status`` 를 읽는다. ``--mode recollect`` 는
커서를 넘기지 않고 ``_cursor`` 줄을 파이프에 넘기지 않는다(다시 읽은 구간이 커서를 되돌리지 않게).

단계마다 ``lm27.collect.stage_result.stage_scope`` 가 finally 에서 ``stage_result_<stage>.json`` 을 남긴다(계약 §8.5). 경로별
관측(``srcs`` — ``lm27.collect.ledger.observation``)을 함께 실어 원장이 다시 만들 수 있게 한다. 원문 0: 결과·이벤트에는 숫자·
열거·사유 코드·고정 한국어 문구만 둔다.
"""
from __future__ import annotations

import collections
import concurrent.futures
import dataclasses
import importlib.util
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from lm27.collect import ledger, plan, rcmap
from lm27.collect import probe as probe_mod
from lm27.collect import stage_result as sr
from lm27.collect import todo as todo_mod
from lm27.collect.watch import WatchPolicy, watch
from lm27.util import events, fsx, proc

__all__ = [
    "MODES", "CollectResult", "Deps", "SrcRun", "collect_here", "harvest_run", "in_line", "parse_status",
    "parse_summary", "run_ps", "run_py",
]

MODES = ("auto", "probe-only", "recollect")
STATUS_SCHEMA = "lm27.collector_status/1"
HARVEST_SRCS = tuple(s for s, sp in plan.COLLECTORS.items() if sp.harvest)
COM_SRCS = ("mail.com", "cal.com")
BACKFILL_STAGES = ("backfill_owa", "backfill_teams_web")
WEB_SRCS = frozenset({"mail.owa", "cal.owa", "teams.web"})
TAIL = 200
_STATUS_NUM = ("subfolder_ratio", "recurrence_incomplete", "skipped_msg", "items_total", "items_ok", "new")
_SAFE_STR_MAX = 64

HINT_BUDGET = "전체 시간 예산에 닿아 이 단계를 돌리지 않았습니다 — 다음 수집이 이어서 읽습니다"
HINT_AGENT_ALIVE = "상주 에이전트가 팀즈 창을 주기적으로 읽습니다"
HINT_BUSY = "번들이 다른 작업에 잠겨 있어 이번에는 건너뜁니다 — 다음 수집이 이어서 합니다"
HINT_NOT_READY = "아직 설치되지 않은 수집 경로입니다"
NOTICE_LOGIN = "웹 로그인이 필요합니다 — 전용 창에서 한 번 로그인하면 다음 수집이 이어서 읽습니다"


# ───────────────────────────── 실행 환경(주입점) ─────────────────────────────
class Deps:
    """실기계·이웃 모듈 호출 한 곳 — 시험은 같은 이름의 메서드를 가진 하위 클래스를 ``collect_here(..., deps=)`` 로 넣는다
    (실제 작업 등록·메일·팀즈·PC 수집·네트워크 0)."""

    def __init__(self, paths, cfg):
        self.paths, self.cfg = paths, cfg

    # 시각
    def now(self) -> datetime:
        return datetime.now(UTC)

    def monotonic(self) -> float:
        return time.monotonic()

    # 식별·번들
    def identify(self):
        from lm27.bundle.ids import identify_pc
        return identify_pc(self.paths)

    def bundle_location(self) -> dict:
        from lm27.bundle.pcreg import probe_bundle_location
        return probe_bundle_location(self.paths)

    # 에이전트(계약 §2.4)
    def ensure_agent(self, ident) -> dict:
        from lm27.agent.install import ensure_agent
        return ensure_agent(ident, paths=self.paths, cfg=self.cfg)

    def agent_health(self, ident) -> dict:
        from lm27.agent.install import agent_health
        return agent_health(ident, paths=self.paths, cfg=self.cfg)

    def request_harvest_now(self, ident, wait_s: float) -> dict:
        from lm27.agent.install import request_harvest_now
        return request_harvest_now(ident, wait_s, paths=self.paths)

    # 탐침·내보내기·업로드
    def probe(self, ident):
        return probe_mod.probe_capabilities(self.paths, ident, self.cfg)

    def export(self, pcdir, ident, **kw):
        from lm27.bundle.export import export_agent_streams
        return export_agent_streams(pcdir, ident, self.cfg, paths=self.paths, **kw)

    def send_due(self):
        """승인된 팀 묶음 대기분 전송(``lm27.team.queue.send_due`` — TAB §2.8). 그 모듈이 아직 없으면 None."""
        if importlib.util.find_spec("lm27.team.queue") is None:
            return None
        from lm27.team.queue import send_due
        return send_due(self.cfg)

    # 자식 프로세스
    def spawn(self, argv, **kw):
        return proc.spawn(argv, **kw)

    def kill(self, pid: int) -> bool:
        return proc.kill_tree(pid)

    def watch_clock(self):
        return None                                     # None = lm27.collect.watch.MonoClock

    def python_exe(self) -> str:
        p = self.paths.python_exe()
        return str(p) if os.path.isfile(p) else sys.executable

    def powershell_exe(self) -> str:
        return probe_mod.powershell_exe()

    def child_env(self) -> dict | None:
        return None

    def child_cwd(self) -> str | None:
        return None


# ───────────────────────────── 결과 형 ─────────────────────────────
@dataclass
class SrcRun:
    """경로 하나의 실행 결과(숫자·열거·사유 코드만). ``rc`` = 원장·단계에 쓰는 수집기 rc(파이프 실패·감시 종료를 반영 —
    돌지 않았으면 None), ``exit_code`` = 수집기 실제 종료 코드."""
    src: str
    kind: str
    rc: int | None = None
    exit_code: int | None = None
    pipe: int | None = None
    reasons: list = field(default_factory=list)
    stored: int = 0
    rows_in: int = 0
    dropped: int = 0
    cap_hit: bool = False
    budget_hit: bool = False
    stop_kind: str | None = None
    horizon_oldest: str | None = None
    horizon_newest: str | None = None
    ranges: list = field(default_factory=list)
    months: dict = field(default_factory=dict)
    skipped: str = ""
    cursor_saved: bool = False
    elapsed_s: float = 0.0
    extra: dict = field(default_factory=dict)

    def counts(self) -> dict:
        c = {"n": self.stored, "cap_hit": self.cap_hit, "budget_hit": self.budget_hit}
        if self.stop_kind:
            c["stop_kind"] = self.stop_kind
        return c

    def outcome(self) -> dict:
        """단계 결과 공통 필드 일부(``rcmap.stage_outcome`` — 원장과 같은 번역)."""
        return rcmap.stage_outcome(self.rc, self.reasons, self.counts())

    def obs(self, probe_sig=None) -> dict:
        return ledger.observation(self.rc, self.reasons, n=self.stored, ranges=self.ranges, cap_hit=self.cap_hit,
                                  budget_hit=self.budget_hit, stop_kind=self.stop_kind,
                                  horizon_oldest=self.horizon_oldest, horizon_newest=self.horizon_newest,
                                  months=self.months, probe_sig=probe_sig, skipped=self.skipped)


@dataclass
class CollectResult:
    """[수집] 한 번의 결과. ``rc`` = 계약 §8.3(0 새 레코드 · 4 새것 없음 · 2 부분 · 3 환경 실패 · 1 실패)."""
    rc: int
    run_id: str
    mode: str
    pc_id: str | None = None
    stages: list = field(default_factory=list)
    new: dict = field(default_factory=dict)
    reasons: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    todos: int = 0
    elapsed_s: float = 0.0

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


# ───────────────────────────── 출력 해석 ─────────────────────────────
def _json_lines(lines):
    for ln in reversed(list(lines or ())):
        s = (ln.decode("utf-8", "replace") if isinstance(ln, (bytes, bytearray)) else str(ln)).strip().lstrip("﻿")
        if s.startswith("{") and s.endswith("}"):
            try:
                obj = fsx.loads_strict(s)
            except ValueError:
                continue
            if isinstance(obj, dict):
                yield obj


def parse_status(lines, src: str | None = None) -> dict | None:
    """stderr 줄들에서 그 경로의 마지막 상태 줄 ``{"_status": {...}}``(계약 v1.2 C1 — 경로마다 한 줄, 모르는 필드 무시).
    ``src`` 를 주면 그 경로의 줄만(상태에 src 가 없으면 받아 준다)."""
    for obj in _json_lines(lines):
        st = obj.get("_status") if len(obj) == 1 else None
        if isinstance(st, dict) and (src is None or st.get("src") in (None, src)):
            return st
    return None


def parse_summary(text) -> dict | None:
    """정제 파이프 stdout 의 요약 줄(P §3.5 형 + cursor_saved·collector_status)."""
    lines = text.splitlines() if isinstance(text, str) else (text or b"").splitlines()
    for obj in _json_lines(lines):
        if "rows_in" in obj or "ok" in obj:
            return obj
    return None


def _int(v) -> int:
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else 0


def _date10(v):
    return v[:10] if isinstance(v, str) and len(v) >= 10 and v[4] == "-" and v[7] == "-" else None


def _apply_status(r: SrcRun, st: dict | None) -> None:
    """상태 줄 → SrcRun(사유·상한·예산·지평선·추가 숫자). 원문 없는 값만 옮긴다."""
    if not isinstance(st, dict):
        return
    r.reasons = sorted(set(r.reasons) | set(rcmap.norm_reasons(st.get("reasons"))))
    cnt = st.get("counts") if isinstance(st.get("counts"), dict) else {}
    r.cap_hit = r.cap_hit or st.get("cap_hit") is True or cnt.get("cap_hit") is True
    r.budget_hit = r.budget_hit or st.get("budget_hit") is True or cnt.get("budget_hit") is True
    for k in ("horizon_oldest", "horizon_newest"):
        v = _date10(st.get(k)) or _date10(cnt.get(k))
        if v:
            setattr(r, k, v)
    for k in _STATUS_NUM:
        v = st.get(k, cnt.get(k))
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            r.extra[k] = v


# ───────────────────────────── 실행 문맥 ─────────────────────────────
@dataclass
class _Ctx:
    paths: object
    cfg: object
    deps: Deps
    run_id: str
    mode: str
    since: str | None
    until: str | None
    only: tuple | None
    t0: float
    deadline: float | None
    ident: object = None
    pcdir: object = None
    pc: dict = field(default_factory=dict)
    roles: tuple = ()
    caps: dict = field(default_factory=dict)
    agent: dict = field(default_factory=dict)
    agent_info: dict = field(default_factory=dict)
    today: date | None = None
    results: dict = field(default_factory=dict)
    order: list = field(default_factory=list)
    new: dict = field(default_factory=dict)
    notes: list = field(default_factory=list)
    todos: list = field(default_factory=list)
    export_total: dict = field(default_factory=dict)
    self_names_cache: list | None = None
    loc_cache: dict | None = None

    @property
    def recollect(self) -> bool:
        return self.mode == "recollect"

    def lock(self, purpose: str):
        from lm27.bundle.lock import BundleLock
        return BundleLock(self.paths, purpose, cfg=self.cfg)

    def over_budget(self) -> bool:
        return self.deadline is not None and self.deps.monotonic() >= self.deadline

    def budget_left(self) -> int | None:
        if self.deadline is None:
            return None
        return max(1, int(self.deadline - self.deps.monotonic()))

    def remember(self, stage: str, res: dict | None) -> None:
        if isinstance(res, dict):
            if stage not in self.results:
                self.order.append(stage)
            self.results[stage] = res

    def window(self) -> list:
        """lookback 창 ``[d0, d1]``(로컬 — 근무 시간대)."""
        d1 = date.fromisoformat(self.until) if self.until else self.today
        d0 = date.fromisoformat(self.since) if self.since else \
            self.today - timedelta(days=int(self.cfg["collect.lookbackDays"]) - 1)
        return [d0.isoformat(), d1.isoformat()]

    def ranges_for(self, spec, blanks=None) -> list:
        if spec.window == plan.WIN_NONE:
            return []
        if spec.window == plan.WIN_TODAY:
            return [[self.today.isoformat(), self.today.isoformat()]]
        if spec.window == plan.WIN_BLANKS and not self.recollect:      # 다시 읽기는 빈칸이 아니라 요청 구간 전체
            return [list(b["date_range"]) for b in blanks or ()]
        return [self.window()]

    def self_names(self) -> list:
        if self.self_names_cache is None:
            from lm27.privacy import LocalOnly, self_name_set
            self.self_names_cache = list(self_name_set(LocalOnly.load(self.paths), self.cfg))
        return self.self_names_cache

    def probe_sig(self, src: str):
        spec = plan.COLLECTORS.get(src)
        for key in (src, spec.probe_key if spec else ""):
            c = self.caps.get(key) if key else None
            if isinstance(c, dict):
                hist = c.get("history")
                if isinstance(hist, list) and hist and isinstance(hist[-1], dict) and hist[-1].get("probe_sig"):
                    return hist[-1]["probe_sig"]
                if c.get("sig"):
                    return c["sig"]
        return None


def _today_of(cfg, now: datetime) -> date:
    return (now.astimezone(UTC) + timedelta(minutes=int(cfg["time.tzOffsetMin"]))).date()


# ───────────────────────────── 전경 연결자(계약 §7.3) ─────────────────────────────
def in_line(ctx: _Ctx, spec) -> dict:
    """PS 수집기 stdin 제어 줄 ``{"_in": {"cursor", "cfg", "self_names"?}}``(계약 §7.3 · X-300). recollect 면 커서 없음."""
    cursor = None
    if not ctx.recollect:
        from lm27.store import load_raw_cursor
        cursor = load_raw_cursor(ctx.paths, ctx.ident.pc_id).get(spec.src)
    cfg = {}
    for k in spec.cfg:
        cfg[k] = plan.read_protected(ctx.cfg, ctx.caps) if k == "mail.com.readProtected" else ctx.cfg[k]
    body = {"cursor": cursor, "cfg": dict(sorted(cfg.items()))}
    if spec.self_names:
        body["self_names"] = ctx.self_names()
    return {"_in": body}


class _Forward:
    """수집기 stdout 줄 → 파이프 stdin(UTF-8 한 줄씩). 파이프가 먼저 죽으면 넘기기를 멈춘다(수집기 출력은 버림)."""

    def __init__(self, stream, *, drop_cursor: bool):
        self.stream, self.drop_cursor = stream, drop_cursor
        self.broken = False
        self.lines = 0

    def __call__(self, line: str) -> None:
        if self.broken or self.stream is None:
            return
        if self.drop_cursor and line.lstrip().startswith('{"_cursor"'):
            return
        try:
            self.stream.write(line.encode("utf-8") + b"\n")
            self.lines += 1
        except (OSError, ValueError):
            self.broken = True

    def close(self) -> None:
        if self.stream is None:
            return
        try:
            self.stream.close()
        except (OSError, ValueError):
            self.broken = True


def _policy(ctx: _Ctx, spec, *, lines: bool) -> WatchPolicy:
    p = WatchPolicy.from_cfg(ctx.cfg, stage=spec.stage, progress_on_lines=lines)
    lim = spec.limit_s(ctx.cfg)
    if spec.src in WEB_SRCS:                                   # 로그인 대기(bridge.loginWaitMin)를 무진전으로 끊지 않게
        wait = 60.0 * float(ctx.cfg["bridge.loginWaitMin"]) + plan.PS_SLACK_S
        return dataclasses.replace(p, no_progress_s=max(p.no_progress_s, wait))
    if lim is not None:
        return dataclasses.replace(p, stall_s=min(p.stall_s, lim), no_progress_s=min(p.no_progress_s, lim))
    return p


def _since_args(ctx: _Ctx, spec) -> list:
    if not spec.since_args or not (ctx.since or ctx.until):
        return []
    d0, d1 = ctx.window()
    return [spec.since_args[0], d0, spec.since_args[1], d1]


def _cov_months(ctx: _Ctx, src: str) -> dict:
    """COM 커서의 달 상태(원장이 달 단위로 판단 — 원 ID 없음)."""
    from lm27.store import load_raw_cursor
    cur = load_raw_cursor(ctx.paths, ctx.ident.pc_id).get(src)
    cm = cur.get("cov_months") if isinstance(cur, dict) else None
    if not isinstance(cm, dict):
        return {}
    return {m: v.get("status") for m, v in cm.items() if isinstance(v, dict) and isinstance(v.get("status"), str)}


def _finish(r: SrcRun, w, err_lines, summary, ctx: _Ctx, *, piped: bool = True) -> SrcRun:
    """감시 결과·상태 줄·파이프 요약 → rc·사유(계약 §8.1 (b) · §8.2). ``piped`` = 정제 파이프를 거쳤나(PS 수집기)."""
    st = parse_status(err_lines, r.src)
    if st is None and isinstance(summary, dict) and isinstance(summary.get("collector_status"), dict):
        st = summary["collector_status"]                       # CLM: 상태 줄이 stdout 제어 줄로 와 파이프 요약에 실림(C1)
    _apply_status(r, st)
    r.exit_code = w.exit_code
    if w.killed:
        r.rc, r.stop_kind = rcmap.RC_KILLED, w.stop_kind
        r.reasons = sorted(set(r.reasons) | {"R-TRANSPORT"})
    else:
        r.rc = w.exit_code if isinstance(w.exit_code, int) else rcmap.RC_KILLED
    if isinstance(summary, dict):
        r.stored = _int(summary.get("stored"))
        r.rows_in = _int(summary.get("rows_in"))
        dr = summary.get("dropped")
        r.dropped = sum(_int(v) for v in dr.values()) if isinstance(dr, dict) else _int(dr)
        r.cursor_saved = summary.get("cursor_saved") is True
    if piped:
        r.rc, r.reasons = rcmap.apply_pipe(r.rc, r.reasons, r.pipe)
    if r.src in COM_SRCS and not ctx.recollect:
        r.months = _cov_months(ctx, r.src)
    return r


def run_ps(ctx: _Ctx, spec, *, extra_args=()) -> SrcRun:
    """PS 수집기 하나 → 정제 파이프(로컬 원장). 감시·파이프 대기·kill_tree 를 맡는다(계약 §7.3 · §8.2)."""
    d = ctx.deps
    r = SrcRun(spec.src, spec.kind, ranges=ctx.ranges_for(spec))
    t0 = d.monotonic()
    pc_id = ctx.ident.pc_id
    script = ctx.paths.collect_script(spec.script)
    if not os.path.isfile(script):
        r.skipped = "script_missing"
        return r
    argv = [d.powershell_exe(), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script),
            "-Pc", pc_id, *spec.args, *_since_args(ctx, spec), *(str(a) for a in extra_args)]
    pipe_argv = [d.python_exe(), "-X", "utf8", "-I", "-B", str(ctx.paths.pipe_script()), "--kind", spec.kind,
                 "--src", spec.src, "--pc", pc_id, "--mode", "append"]
    env, cwd = d.child_env(), d.child_cwd()
    try:
        pipe = d.spawn(pipe_argv, stdin=proc.PIPE, stdout=proc.PIPE, stderr=proc.STDERR_TAIL, env=env, cwd=cwd)
    except OSError as e:
        r.rc, r.reasons, r.skipped = rcmap.RC_KILLED, ["R-TRANSPORT"], "spawn_" + type(e).__name__
        return r
    try:
        col = d.spawn(argv, stdin=proc.PIPE, stdout=proc.PIPE, stderr=proc.PIPE, env=env, cwd=cwd)
    except OSError as e:
        _close_kill(d, pipe)
        r.rc, r.reasons, r.skipped = rcmap.RC_KILLED, ["R-TRANSPORT"], "spawn_" + type(e).__name__
        return r
    err = collections.deque(maxlen=TAIL)
    fwd = _Forward(pipe.stdin, drop_cursor=ctx.recollect)
    try:
        try:
            col.stdin.write(fsx.canon_bytes(in_line(ctx, spec)) + b"\n")
            col.stdin.close()
        except (OSError, ValueError):
            pass
        w = watch(col, _policy(ctx, spec, lines=True), clock=d.watch_clock(), kill=d.kill, on_line=fwd,
                  on_err=err.append)
    except BaseException:
        _close_kill(d, pipe)
        raise
    finally:
        fwd.close()
    r.pipe, out = _wait_pipe(ctx, pipe)
    _finish(r, w, err, parse_summary(out), ctx)
    r.elapsed_s = round(d.monotonic() - t0, 1)
    for ch in (col, pipe):
        _close(ch)
    return r


def _wait_pipe(ctx: _Ctx, pipe) -> tuple:
    """수집기 EOF 뒤 파이프를 ``privacy.pipe.waitSec`` 까지 기다린다. 넘으면 kill_tree + 99(계약 §8.2)."""
    wait = float(ctx.cfg["privacy.pipe.waitSec"])
    out = []

    def rd():
        try:
            if pipe.stdout is not None:
                out.append(pipe.stdout.read())
        except (OSError, ValueError):
            pass
    t = threading.Thread(target=rd, name="lm27-collect-pipe-out", daemon=True)
    t.start()
    try:
        pipe.wait(timeout=wait)
        code = pipe.returncode if pipe.returncode is not None else pipe.poll()
    except subprocess.TimeoutExpired:
        ctx.deps.kill(pipe.pid)
        code = rcmap.PIPE_WAIT_KILLED
        try:
            pipe.wait(timeout=10)                               # 끊은 파이프를 거둔다(좀비·핸들 남기지 않게)
        except (subprocess.TimeoutExpired, OSError, ValueError):
            pass
    t.join(5)
    return code, b"".join(x for x in out if isinstance(x, (bytes, bytearray)))


def _close(ch) -> None:
    try:
        ch.close()
    except (OSError, ValueError, AttributeError):
        pass


def _close_kill(d: Deps, ch) -> None:
    try:
        if ch.poll() is None:
            d.kill(ch.pid)
    except (OSError, ValueError):
        pass
    _close(ch)


def run_py(ctx: _Ctx, spec, *, extra_args=(), blanks=None) -> SrcRun:
    """PY 수집기 하나(in-process 정제·SegmentWriter — 계약 §7.3)를 자식으로 돌린다. stdout = §8.6 이벤트(진전), stderr =
    상태 줄. 스크립트가 아직 없으면(다른 작업 패키지 미완) 돌지 않음."""
    d = ctx.deps
    r = SrcRun(spec.src, spec.kind, ranges=ctx.ranges_for(spec, blanks))
    script = ctx.paths.collect_script(spec.script)
    if not os.path.isfile(script):
        r.skipped = "script_missing"
        return r
    t0 = d.monotonic()
    argv = [d.python_exe(), "-X", "utf8", "-I", "-B", str(script), "--pc", ctx.ident.pc_id, *spec.args,
            *_since_args(ctx, spec), *(str(a) for a in extra_args)]
    try:
        child = d.spawn(argv, stdin=proc.DEVNULL, stdout=proc.PIPE, stderr=proc.PIPE, env=d.child_env(),
                        cwd=d.child_cwd())
    except OSError as e:
        r.rc, r.reasons, r.skipped = rcmap.RC_KILLED, ["R-TRANSPORT"], "spawn_" + type(e).__name__
        return r
    err = collections.deque(maxlen=TAIL)
    result_ev = {}

    def on_event(ev):
        if ev.get("ev") == "result":
            result_ev.clear()
            result_ev.update({k: v for k, v in ev.items() if isinstance(v, (int, float, bool))})
    try:
        w = watch(child, _policy(ctx, spec, lines=False), clock=d.watch_clock(), kill=d.kill, on_event=on_event,
                  on_err=err.append)
    finally:
        _close(child)
    _finish(r, w, err, None, ctx, piped=False)
    st = parse_status(err, r.src) or {}
    r.stored = _int(st.get("items_ok", st.get("n", result_ev.get("items_ok", 0))))
    r.rows_in = _int(st.get("items_total", result_ev.get("items_total", 0)))
    r.elapsed_s = round(d.monotonic() - t0, 1)
    return r


def _from_harvest(src: str, ctx: _Ctx, d: dict) -> SrcRun:
    """``harvest_done.json`` 흐름 하나(lm27.harvest_done/1 — WP-13) → SrcRun."""
    spec = plan.COLLECTORS[src]
    r = SrcRun(src, spec.kind, ranges=ctx.ranges_for(spec))
    if not isinstance(d, dict):
        r.skipped = "harvest_missing"
        return r
    if d.get("skipped"):
        r.skipped = str(d["skipped"])[:_SAFE_STR_MAX]
        if r.skipped.startswith("spawn_"):
            r.rc, r.reasons = rcmap.RC_KILLED, ["R-TRANSPORT"]
        return r
    r.reasons = rcmap.norm_reasons(d.get("reasons"))
    _apply_status(r, d.get("status") if isinstance(d.get("status"), dict) else None)
    rc = d.get("rc") if isinstance(d.get("rc"), int) and not isinstance(d.get("rc"), bool) else None
    if d.get("timed_out") is True or rc is None:
        rc, r.stop_kind = rcmap.RC_KILLED, "stall"
        r.reasons = sorted(set(r.reasons) | {"R-TRANSPORT"})
    r.exit_code = rc
    r.pipe = d.get("pipe") if isinstance(d.get("pipe"), int) else None
    r.stored = _int(d.get("stored"))
    r.cursor_saved = d.get("cursor_saved") is True
    r.rc, r.reasons = rcmap.apply_pipe(rc, r.reasons, r.pipe)
    r.elapsed_s = float(d.get("elapsed_s") or 0.0) if isinstance(d.get("elapsed_s"), (int, float)) else 0.0
    return r


def harvest_run(ctx: _Ctx, srcs) -> tuple:
    """수확 흐름(pc.events·files·mru·recent) → ([SrcRun], 경로 'agent'|'foreground'|'busy'). 에이전트가 살아 있으면 수확을
    요청해 ``harvest_done.json`` 을 쓰고, 아니면(없음·impl none·시간 안에 안 끝남) ``.harvest.lock`` 을 쥐고 전경이 돌린다
    (TAB §1.6.1 none · WP-13 rc 2 '전경 경로가 채운다'). 잠금이 다른 수확에 잡혀 있으면 이번에는 건너뛴다."""
    srcs = [s for s in srcs if s in HARVEST_SRCS]
    if not srcs:
        return [], "none"
    if ctx.agent.get("impl") in ("py", "ps") and not ctx.recollect and ctx.agent.get("rc") in (0, 4):
        hv = ctx.deps.request_harvest_now(ctx.ident, float(ctx.cfg["agent.harvestWaitSec"]))
        res = hv.get("result") if isinstance(hv, dict) and hv.get("done") else None
        if isinstance(res, dict) and isinstance(res.get("streams"), dict):
            return [_from_harvest(s, ctx, res["streams"].get(s)) for s in srcs], "agent"
        ctx.notes.append("harvest_wait_timeout")
    from lm27.store import LockTimeout, file_lock
    try:
        with file_lock(ctx.paths.harvest_lock(), 0):
            return _run_many(ctx, [plan.COLLECTORS[s] for s in srcs], parallel=True), "foreground"
    except LockTimeout:
        out = []
        for s in srcs:
            spec = plan.COLLECTORS[s]
            out.append(SrcRun(s, spec.kind, ranges=[], skipped="harvest_busy"))
        return out, "busy"


def _run_one(ctx: _Ctx, spec, blanks=None, extra_args=()) -> SrcRun:
    if spec.lang == "ps":
        return run_ps(ctx, spec, extra_args=extra_args)
    if spec.lang == "py":
        return run_py(ctx, spec, extra_args=extra_args, blanks=blanks)
    raise ValueError(f"실행할 수 없는 수집기 종류: {spec.lang}")


def _run_many(ctx: _Ctx, specs, *, parallel: bool, args_of=None) -> list:
    """수집기 여러 개 — ``collect.parallelMax`` 까지 동시에(같은 단계 안, C §8.2). 순서는 입력 순서로 돌려준다."""
    args_of = args_of or (lambda s: ((), None))
    n = min(plan.parallel_max(ctx.cfg), len(specs)) if parallel else 1
    if n <= 1:
        return [_run_one(ctx, s, args_of(s)[1], args_of(s)[0]) for s in specs]
    with concurrent.futures.ThreadPoolExecutor(max_workers=n, thread_name_prefix="lm27-collect") as ex:
        futs = [ex.submit(_run_one, ctx, s, args_of(s)[1], args_of(s)[0]) for s in specs]
        return [f.result() for f in futs]


# ───────────────────────────── 단계 결과 묶기 ─────────────────────────────
_STATE_RANK = {"failed": 0, "partial": 1, "done": 2, "skipped": 3}


def _planned(src: str, sk: dict, ctx: _Ctx) -> SrcRun:
    """계획에서 건너뛴 경로(탐침 막힘·불가 확정) → '막힘' 결과(rc 3 + 사유) — 원장 blocked."""
    spec = plan.COLLECTORS[src]
    rc = sk.get("rc")
    return SrcRun(src, spec.kind, rc=rc if isinstance(rc, int) else None, reasons=list(sk.get("reasons") or ()),
                  ranges=ctx.ranges_for(spec), skipped="planned_" + str(sk.get("why") or "skip"))


def _combine(ctx: _Ctx, runs) -> dict:
    """경로별 결과 → 단계 결과 필드(state = 가장 나쁜 경로 — failed > partial > done > skipped)."""
    outs = [(r, r.outcome()) for r in runs]
    if not outs:
        return {"state": "skipped", "rc": rcmap.RC_NOT_RUN, "hint": rcmap.HINTS["not_run"]}
    main_r, main = min(outs, key=lambda x: _STATE_RANK.get(x[1]["state"], 9))
    reasons = sorted({x for _r, o in outs for x in o.get("reasons") or ()})
    fields = {k: main[k] for k in ("state", "stop_kind", "reason", "resumable", "rc", "hint")}
    fields["resumable"] = any(o.get("resumable") for _r, o in outs)
    fields["caps_hit"] = any(o.get("caps_hit") for _r, o in outs)
    if main["state"] == "done":
        fields["stop_kind"] = None
    fields["reasons"] = reasons
    unk = sum(int(o.get("unknown_reasons") or 0) for _r, o in outs)
    if unk:
        fields["unknown_reasons"] = unk
    fields["items_total"] = sum(r.rows_in for r in runs)
    fields["items_ok"] = sum(r.stored for r in runs)
    fields["items_failed"] = sum(r.dropped for r in runs)
    fields["counts"] = {"stored": {r.src: r.stored for r in runs}, "rows_in": {r.src: r.rows_in for r in runs}}
    fields["srcs"] = {r.src: r.obs(ctx.probe_sig(r.src)) for r in runs}
    fields["pc_id"] = ctx.ident.pc_id
    if len(runs) == 1:
        fields["src"] = runs[0].src
    for k in ("subfolder_ratio", "recurrence_incomplete", "skipped_msg"):
        vals = [r.extra[k] for r in runs if k in r.extra]
        if vals:
            fields[k] = max(vals)
    skipped = {r.src: r.skipped for r in runs if r.skipped}
    if skipped:
        fields["skipped_srcs"] = skipped
    return fields


def _emit(ev: str, **f) -> None:
    events.emit(ev, **f)


def _stage(ctx: _Ctx, name: str, body):
    """단계 하나를 ``stage_scope`` 로 감싸 돌린다(finally 기록 — 계약 §8.5). body(ctx, scope) 는 필드를 정한다.
    단계 안 예외는 scope 가 failed(R-TRANSPORT·error_type)로 남긴 뒤 여기서 멈춘다 — 다음 단계(내보내기·원장)는 계속 돈다
    (이미 모은 자료를 번들에 넣는다). 명령 rc 는 그 failed 단계 때문에 1 이 된다. 사용자 중단(Ctrl+C)은 그대로 올린다."""
    _emit("stage_start", stage=name)
    res = None
    try:
        with sr.stage_scope(ctx.paths, ctx.run_id, name, pc_id=ctx.ident.pc_id, run_mode=ctx.mode) as st:
            body(ctx, st)
        res = st.result
    except Exception as e:                       # noqa: BLE001 — 기록은 scope 가 했다(failed + 유형 이름), 흐름은 계속
        ctx.notes.append(f"{name}_{type(e).__name__}")
    finally:
        if res is None:
            res = sr.read_stage_result(ctx.paths, ctx.run_id, name)
        ctx.remember(name, res)
        _emit("stage_end", stage=name, state=(res or {}).get("state"))
    return res


def _budget_stage(ctx: _Ctx, name: str, srcs) -> None:
    """전체 예산이 바닥나 돌리지 않은 단계(partial + budget — 셀은 not_attempted, T-10)."""
    def body(_c, st):
        obs = {}
        for s in srcs:
            spec = plan.COLLECTORS[s]
            obs[s] = SrcRun(s, spec.kind, ranges=[], skipped="budget").obs(None)
        st.set(state="partial", stop_kind="budget", resumable=True, reason="R-BUDGET", rc=rcmap.RC_NOT_RUN,
               hint=HINT_BUDGET, reasons=["R-BUDGET"], srcs=obs)
    _stage(ctx, name, body)


# ───────────────────────────── 단계 몸통 ─────────────────────────────
def _probe_body(ctx: _Ctx, st) -> None:
    pr = ctx.deps.probe(ctx.ident)
    with ctx.lock("fg-write"):
        from lm27.collect.probe import record_probes
        ents = record_probes(ctx.pcdir, pr, ctx.loc_cache, cfg=ctx.cfg, today=ctx.today, agent=ctx.agent_info)
    from lm27.bundle import pcreg
    pc = pcreg.load_pc(ctx.pcdir) or {}
    caps = {k: dict(v) for k, v in (pc.get("capabilities") or {}).items() if isinstance(v, dict)}
    for k, v in pr.caps.items():
        caps.setdefault(k, {}).update({"status": v.get("status"), "sig": v.get("sig"), "value": v.get("value")})
    ctx.caps, ctx.pc = caps, pc
    rs = sorted(r for r in pr.reasons() if rcmap.is_reason(r))
    fields = {"items_total": len(pr.caps), "reasons": rs,
              "counts": {"caps": len(pr.caps), "recorded": len(ents), "elapsed_ms": pr.elapsed_ms or 0,
                         "unknown_reasons": pr.unknown_reasons}}
    if pr.rc != 0:
        fields.update(state="partial", stop_kind="fatal", resumable=True, reason="R-TRANSPORT", rc=3,
                      hint=rcmap.HINTS["transport"], reasons=sorted(set(rs) | {"R-TRANSPORT"}),
                      error_type=str(pr.error or "probe")[:_SAFE_STR_MAX])
    elif pr.budget_hit:
        fields.update(state="partial", stop_kind="budget", resumable=True, reason="R-BUDGET", rc=0,
                      hint=rcmap.HINTS["budget"], reasons=sorted(set(rs) | {"R-BUDGET"}))
    else:
        fields.update(state="done", rc=0, hint="")
    if pr.warnings:
        fields["warnings"] = list(pr.warnings)
    st.set(**fields)


def _sampler_run(ctx: _Ctx) -> SrcRun:
    """상주 샘플러 생존(계약 §8.1 — 확인만): 살아 있으면 rc 4(오늘 읽음), impl none 이면 rc 3 + R-CLM·R-APPLOCKER,
    그 밖(설치·기동 실패·heartbeat 낡음)은 rc 3 + 수송(다음 수집에서 다시)."""
    spec = plan.COLLECTORS["pc.sampler"]
    r = SrcRun("pc.sampler", spec.kind, ranges=ctx.ranges_for(spec))
    a = ctx.agent
    h = a.get("health") if isinstance(a.get("health"), dict) else {}
    if a.get("impl") == "none":
        r.rc, r.reasons = 3, sorted({x for x in a.get("reasons") or () if x in ("R-CLM", "R-APPLOCKER")} or {"R-CLM"})
    elif h.get("healthy"):
        r.rc = 4
    elif not a:
        r.skipped = "agent_skipped"
    else:
        r.rc = 3
        r.reasons = sorted({x for x in h.get("reasons") or a.get("reasons") or () if rcmap.is_reason(x)}
                           | {"R-TRANSPORT"})
    return r


def _pc_bundle_body(stage):
    def body(ctx: _Ctx, st) -> None:
        runs = []
        if "pc.sampler" in stage.srcs:
            runs.append(_sampler_run(ctx))
        hv, how = harvest_run(ctx, [s for s in stage.srcs if s in HARVEST_SRCS])
        runs += hv
        rest = [plan.COLLECTORS[s] for s in stage.srcs if s not in HARVEST_SRCS and s != "pc.sampler"]
        runs += _run_many(ctx, rest, parallel=True)
        runs += [_planned(s, sk, ctx) for s, sk in sorted(stage.skip.items())]
        fields = _combine(ctx, runs)
        fields["harvest"] = how
        if ctx.agent.get("impl") == "none" and hv and all(
                (r.rc is not None and set(r.reasons) & {"R-CLM", "R-APPLOCKER"}) or r.skipped.startswith("spawn_")
                for r in hv):
            why = "R-APPLOCKER" if "R-APPLOCKER" in (ctx.agent.get("reasons") or ()) else "R-CLM"
            fields.update(state="failed", stop_kind="fatal", reason=why, rc=3, resumable=False,
                          hint="실행 차단 정책으로 이 PC 의 사용 기록을 수집하지 못했습니다",
                          reasons=sorted(set(fields.get("reasons") or ()) | {why}))
        st.set(**fields)
    return body


def _collectors_body(stage, *, blanks_of=None, args_of=None):
    def body(ctx: _Ctx, st) -> None:
        bl = blanks_of(ctx) if blanks_of else {}
        specs, runs = [], []
        for s in stage.srcs:
            spec = plan.COLLECTORS[s]
            if spec.blanks and not ctx.recollect and not (bl.get(s) or {}).get("rows"):
                runs.append(SrcRun(s, spec.kind, ranges=[], skipped="no_blanks"))
                continue
            specs.append(spec)

        def per(spec):
            b = bl.get(spec.src) or {}
            extra = list(args_of(ctx, spec, b) if args_of else ())
            return extra, b.get("rows")
        runs += _run_many(ctx, specs, parallel=stage.parallel, args_of=per)
        runs += [_planned(s, sk, ctx) for s, sk in sorted(stage.skip.items())]
        if any("R-LOGIN" in r.reasons for r in runs):
            _emit("notice", stage=stage.name, text_ko=NOTICE_LOGIN)
        st.set(**_combine(ctx, runs))
    return body


def _teams_body(stage):
    def body(ctx: _Ctx, st) -> None:
        h = ctx.agent.get("health") if isinstance(ctx.agent.get("health"), dict) else {}
        runs = []
        if "teams.uia" in stage.srcs:
            if h.get("healthy"):                           # 화면 판독은 지금 보이는 것뿐 — 다시 읽기(recollect)도 같다
                spec = plan.COLLECTORS["teams.uia"]
                runs.append(SrcRun("teams.uia", spec.kind, ranges=[], skipped="agent_alive"))
            else:
                runs += _run_many(ctx, [plan.COLLECTORS["teams.uia"]], parallel=False)
        runs += [_planned(s, sk, ctx) for s, sk in sorted(stage.skip.items())]
        fields = _combine(ctx, runs)
        if runs and all(r.skipped == "agent_alive" for r in runs):
            fields.update(hint=HINT_AGENT_ALIVE)
        st.set(**fields)
    return body


# 내보낼 흐름 = 에이전트 흐름 + 전경 수집기 흐름(로컬 원장에 쓴 모든 경로)
FG_STREAMS = tuple(sorted({f"{s.kind}/{s.src}" for s in plan.COLLECTORS.values()}))


class _Resanitize:
    """내보낼 때 현재 규칙으로 한 번 더(P §10.5 — G2, 단조: 가린 값은 되살아나지 않음). 규칙 판이 낮은 행만, 문맥은 처음
    필요할 때 만든다(유효 레지스트리·로컬 사전·키링 — 프로그램 폴더 모드)."""

    def __init__(self, ctx: _Ctx):
        self.ctx = ctx
        self.sctx = None
        self.n = 0
        self.failed = None

    def _context(self):
        if self.sctx is None and self.failed is None:
            from lm27.hier.registry import load_effective
            from lm27.privacy import LocalOnly, build_context, load_keyring
            p, cfg = self.ctx.paths, self.ctx.cfg
            try:
                kr = load_keyring(p.data(), None, create=False)
                reg, _st = load_effective(p, cfg, kr=kr, persist=False)
                self.sctx = build_context(cfg, reg, LocalOnly.load(p), kr)
            except (OSError, ValueError, KeyError) as e:
                self.failed = type(e).__name__
        return self.sctx

    def __call__(self, kind, row):
        from lm27.privacy import RULES_VERSION, SCHEMAS, resanitize_row
        if kind not in SCHEMAS or row.get("rules_ver") == RULES_VERSION:
            return row
        ctx = self._context()
        if ctx is None:
            return row
        new, _hits = resanitize_row(kind, row, ctx)
        if new is not row:
            self.n += 1
        return new


def _export_streams(ctx: _Ctx) -> list:
    from lm27.bundle import export as ex
    from lm27.bundle.manifest import load_manifest
    m = load_manifest(ctx.pcdir, quarantine=False)
    return sorted(set(ex.agent_streams(ctx.ident, m)) | set(FG_STREAMS))


def _merge_person_delta(ctx: _Ctx) -> int:
    r"""에이전트가 본 (주소·표시명) 추가분 → 번들 사람 사전(TAB §1.7 · P §9.6). 합집합이라 몇 번을 해도 같다."""
    from lm27.privacy.context import merge_person_dir
    from lm27.store import file_lock
    p = ctx.paths
    delta = fsx.read_json(p.person_dir_delta(), None, want=dict)
    people = delta.get("people") if isinstance(delta, dict) else None
    if not isinstance(people, dict) or not people:
        return 0
    with file_lock(p.local_only_file("person_dir.json.lock")):
        cur = fsx.read_json(p.local_only_file("person_dir.json"), default={}) or {}
        merged = merge_person_dir(cur, people)
        if merged != cur:
            fsx.atomic_write(p.local_only_file("person_dir.json"), fsx.canon_bytes(merged) + b"\n")
            return len(people)
    return 0


def _agent_status(ctx: _Ctx) -> dict | None:
    h = ctx.agent.get("health") if isinstance(ctx.agent.get("health"), dict) else None
    if h is None:
        return None
    return {"install_id": ctx.ident.install_id, "impl": ctx.agent.get("impl"), "last_tick": h.get("last_tick"),
            "healthy": bool(h.get("healthy")), "checked_at": ctx.deps.now().strftime("%Y-%m-%dT%H:%M:%SZ")}


def _export_body(final: bool):
    def body(ctx: _Ctx, st) -> None:
        from lm27.bundle.lock import BundleBusy
        tot = ctx.export_total
        hook = _Resanitize(ctx)
        try:
            with ctx.lock("export"):
                res = ctx.deps.export(ctx.pcdir, ctx.ident, streams=_export_streams(ctx), resanitize=hook,
                                      agent_status=_agent_status(ctx))
                merged = _merge_person_delta(ctx)
        except BundleBusy:
            st.set(state="partial", resumable=True, reason="bundle_busy", rc=rcmap.RC_NOT_RUN, hint=HINT_BUSY,
                   items_ok=_evidence_new(tot), counts=_export_counts(tot))
            ctx.notes.append("export_bundle_busy")
            return
        for k, n in (res.new or {}).items():
            tot.setdefault("new", {})[k] = tot.get("new", {}).get(k, 0) + n
            ctx.new[k] = ctx.new.get(k, 0) + n
        tot["gaps"] = tot.get("gaps", 0) + len(res.gaps or ())
        tot["adopted"] = tot.get("adopted", 0) + int(res.adopted or 0)
        tot["resanitized"] = tot.get("resanitized", 0) + hook.n
        tot["people"] = tot.get("people", 0) + merged
        tot["manifest_gen"] = int(res.manifest_gen or 0)
        tot["passes"] = tot.get("passes", 0) + 1
        if final:
            _finish_visit(ctx, tot)
        new = _evidence_new(tot)
        fields = {"state": "done", "rc": 0 if new else 4, "hint": "", "items_ok": new, "counts": _export_counts(tot)}
        if hook.failed:
            fields["resanitize_unavailable"] = hook.failed
        if res.collision:
            fields["pc_id_collision"] = True
        st.set(**fields)
    return body


def _evidence_new(tot: dict) -> int:
    """내보낸 새 증거 레코드 수(정제 감사 ``privacy_audit`` 줄은 증거가 아니라 빼고 센다 — collect rc 0/4 판정)."""
    return sum(n for k, n in (tot.get("new") or {}).items() if k != "privacy_audit")


def _export_counts(tot: dict) -> dict:
    return {"new": dict(sorted((tot.get("new") or {}).items())), "gaps": tot.get("gaps", 0),
            "adopted": tot.get("adopted", 0), "resanitized": tot.get("resanitized", 0), "people": tot.get("people", 0),
            "manifest_gen": tot.get("manifest_gen", 0), "passes": tot.get("passes", 0),
            "aliases": tot.get("aliases", 0)}


def _finish_visit(ctx: _Ctx, tot: dict) -> None:
    """방문 기록·논리 PC 별칭(TAB §1.7 ⑥⑦ — ``collect-finish`` 잠금)."""
    from lm27.bundle import aliases, pcreg
    from lm27.bundle.lock import BundleBusy
    try:
        with ctx.lock("collect-finish"):
            pcreg.touch_visit(ctx.pcdir, ctx.ident, manifest_gen=tot.get("manifest_gen"),
                              impl=ctx.agent.get("impl") if ctx.agent.get("impl") in ("py", "ps", "none") else None)
            made = aliases.auto_alias(ctx.paths, ctx.cfg)
            tot["aliases"] = tot.get("aliases", 0) + len(made or ())
    except BundleBusy:
        ctx.notes.append("visit_bundle_busy")


def _derive_body(ctx: _Ctx, st) -> None:
    now = ctx.deps.now()
    n = ledger.rebuild_coverage(ctx.paths, cfg=ctx.cfg, now=now)
    ctx.todos = todo_mod.plan_todo(ctx.paths, ctx.cfg, now=now)
    states = collections.Counter(t.state for t in ctx.todos)
    st.set(state="done", rc=0, hint="", items_total=n,
           counts={"cells": n, "todos": len(ctx.todos), "todo_states": dict(sorted(states.items()))})


def _upload_body(ctx: _Ctx, st) -> None:
    try:
        r = ctx.deps.send_due()
    except (OSError, ValueError, RuntimeError) as e:
        st.set(state="partial", resumable=True, reason="upload_failed", rc=1, hint="팀 업로드를 끝내지 못했습니다 — "
               "묶음은 대기열에 남아 다음 수집에서 다시 보냅니다", error_type=type(e).__name__)
        return
    if r is None:
        st.set(state="skipped", rc=rcmap.RC_NOT_RUN, hint=HINT_NOT_READY, reason="team_queue_missing")
        return
    rc = r.get("rc") if isinstance(r, dict) else getattr(r, "rc", r if isinstance(r, int) else None)
    rc = rc if isinstance(rc, int) and not isinstance(rc, bool) else 0
    if rc in (0, 4):
        st.set(state="done", rc=rc, hint="")
    else:
        st.set(state="partial", resumable=True, reason="upload_retry", rc=rc,
               hint="보내지 못한 팀 묶음은 대기열에 남아 다음 수집에서 다시 보냅니다")


# ───────────────────────────── 백필·코파일럿 입력 ─────────────────────────────
def _blanks(ctx: _Ctx) -> dict:
    """백필·코파일럿 경로별 빈칸(이 PC 가 맡은 작업) → ``{src: {"rows": [...], "file": 경로}}``(빈칸 파일 — X-315)."""
    out = {}
    for src, spec in plan.COLLECTORS.items():
        if not spec.blanks:
            continue
        rows = todo_mod.blanks_for(ctx.todos, src, ctx.ident.pc_id)
        if rows:
            p = todo_mod.write_blanks(ctx.paths, ctx.run_id, src, ctx.todos, pc_id=ctx.ident.pc_id)
            out[src] = {"rows": rows, "file": str(p) if p is not None else ""}
    return out


def _web_args(ctx: _Ctx, spec, b: dict) -> list:
    """백필·코파일럿 PY 수집기 인자(계약 §7.3): ``--run-id`` · 빈칸 파일(X-315) 또는 다시 읽기 구간 · 예산 · ``--force``."""
    args = []
    if spec.src in ("mail.owa", "cal.owa", "teams.web") or spec.stage == "copilot_lookup":
        args += ["--run-id", ctx.run_id]
    if spec.blanks and ctx.recollect:                              # 다시 읽기 = 요청 구간 전체(빈칸 파일 없이 — CM §11.3)
        d0, d1 = ctx.window()
        args += ["--from", d0, "--to", d1, "--force"]
    elif spec.blanks and b.get("file"):
        args += ["--blanks-file", b["file"]]
    if spec.src in ("mail.owa", "cal.owa", "teams.web"):
        left = ctx.budget_left()
        if left is not None:
            args += ["--budget-sec", str(left)]
        if ctx.recollect and not spec.blanks:
            args.append("--force")
    return args


# ───────────────────────────── 번들 초기화 ─────────────────────────────
def _ensure_bundle(ctx: _Ctx):
    r"""``bundle.json``(lm27.bundle/1 — person_key 최초 1회·불변)과 키링(P §9.5)이 없으면 만든다. → 키링."""
    import secrets
    import uuid

    from lm27 import LM27_VERSION
    from lm27.privacy import AuditSink, load_keyring
    p = ctx.paths
    bj = fsx.read_json(p.bundle_json(), None, want=dict)
    if not bj or not isinstance(bj.get("person_key"), str):
        if bj is None and os.path.isfile(fsx.longp(p.bundle_json())):
            raise ValueError("bundle.json 형식이 깨졌습니다")
        fsx.atomic_write(p.bundle_json(), fsx.canon_bytes({
            "schema": "lm27.bundle/1", "bundle_id": uuid.uuid4().hex, "person_key": "p_" + secrets.token_hex(6),
            "created_at": ctx.deps.now().strftime("%Y-%m-%dT%H:%M:%SZ"), "created_on_pc": ctx.ident.pc_id,
            "lm27_version": LM27_VERSION}) + b"\n")
        ctx.notes.append("bundle_created")
    audit = AuditSink.open(p.data(), ctx.ident.pc_id, "collect", "bundle", paths=p)
    kr = load_keyring(p.data(), audit, create=True, origin=ctx.ident.pc_id)
    c = audit.counts()
    if any(c.get(k) for k in ("masked", "dropped", "priv", "ad", "err")):
        audit.flush("key")
    return kr


def _host_class(kr) -> str:
    """``host_class`` = keyed(kr, "host", 호스트 이름 앞 4자 대문자)[:4](계약 §4.2 — VDI 자동 별칭 판단에만)."""
    from lm27.privacy import keyed
    name = (os.environ.get("COMPUTERNAME") or "").strip()[:4].upper()
    return keyed(kr, "host", name, 4) if name else ""


def _agent_info(ctx: _Ctx) -> dict:
    aj = fsx.read_json(ctx.paths.agent_json(), None, want=dict) or {}
    if aj.get("install_id") != ctx.ident.install_id:
        return {}
    return {"impl": aj.get("impl"), "impl_reasons": [r for r in aj.get("impl_reasons") or () if rcmap.is_reason(r)]}


def _ensure_agent(ctx: _Ctx) -> dict:
    try:
        a = ctx.deps.ensure_agent(ctx.ident)
    except Exception as e:                       # noqa: BLE001 — 에이전트는 [수집]의 일부일 뿐: 전경 경로로 계속하고 기록한다
        ctx.notes.append("agent_" + type(e).__name__)
        return {"rc": 1, "impl": None, "error_type": type(e).__name__}
    return a if isinstance(a, dict) else {"rc": 1}


def _needs_agent(stages) -> bool:
    return any(s.name == "pc_bundle" and (set(s.srcs) & (set(HARVEST_SRCS) | {"pc.sampler"})) for s in stages) or \
        any(s.name == "teams_uia_check" for s in stages)


# ───────────────────────────── 진입 ─────────────────────────────
def _result(ctx: _Ctx, rc=None, reasons=()) -> CollectResult:
    stages = [ctx.results[s] for s in ctx.order]
    rr = set(reasons)
    for s in stages:
        rr.update(x for x in s.get("reasons") or () if rcmap.is_reason(x))
    return CollectResult(rc=rcmap.collect_rc(stages) if rc is None else rc, run_id=ctx.run_id, mode=ctx.mode,
                         pc_id=getattr(ctx.ident, "pc_id", None), stages=stages, new=dict(sorted(ctx.new.items())),
                         reasons=sorted(rr), notes=list(ctx.notes), todos=len(ctx.todos),
                         elapsed_s=round(ctx.deps.monotonic() - ctx.t0, 1))


def collect_here(paths, cfg, *, mode="auto", since=None, until=None, pc_role=None, only=None, budget_sec=None,
                 deps=None) -> CollectResult:
    """계약 함수: [수집] 한 번(모듈 머리말 0~8). ``mode`` = auto(무질문 — 끝에 대기 업로드 전송) · probe-only(탐침·원장만) ·
    recollect(``since``·``until`` 구간을 커서 없이 다시 — 커서는 그대로). ``only`` = 경로 ID 목록(진단 — 업로드 없음),
    ``budget_sec`` = 전체 시간 예산(None = ``collect.budgetSec``, 0 = 끔), ``deps`` = 시험 주입(``Deps``). 반환 ``CollectResult``
    (``rc`` = 계약 §8.3)."""
    if mode not in MODES:
        raise ValueError(f"collect: mode 는 {MODES} 중 하나")
    if mode == "recollect" and not (since and until):
        raise ValueError("collect: recollect 에는 since·until 이 필요합니다")
    d = deps or Deps(paths, cfg)
    from lm27.util.tz import new_run_id
    now = d.now()
    budget = int(cfg["collect.budgetSec"]) if budget_sec is None else int(budget_sec)
    t0 = d.monotonic()
    ctx = _Ctx(paths=paths, cfg=cfg, deps=d, run_id=new_run_id(now), mode=mode, since=since, until=until,
               only=tuple(only) if only else None, t0=t0, deadline=(t0 + budget) if budget > 0 else None)
    ctx.today = _today_of(cfg, now)
    ctx.loc_cache = None
    try:
        plan.stage_plan((), {}, ctx.only, cfg=cfg)               # --only 형식 먼저 확인(모르는 경로 ID 면 rc 1)
    except ValueError:
        ctx.notes.append("only_unknown")
        return _result(ctx, rc=1)
    # 0. 식별 · 번들 도착 경로
    ctx.ident = d.identify()
    loc = d.bundle_location()
    ctx.loc_cache = loc
    if not loc.get("ok"):
        ctx.notes.append("bundle_readonly")
        _emit("warn", text_ko="번들 폴더에 쓸 수 없어 수집 결과를 남기지 않았습니다 — 쓸 수 있는 위치에서 다시 실행하세요")
        return _result(ctx, rc=3, reasons=["R-BUNDLE-READONLY"])
    # 1. 번들·PC 폴더(collect-init)
    from lm27.bundle import merge as bmerge
    from lm27.bundle import pcreg
    from lm27.bundle.lock import BundleBusy
    try:
        with ctx.lock("collect-init"):
            kr = _ensure_bundle(ctx)
            ctx.pcdir = pcreg.ensure_pc_dir(paths, ctx.ident, host_class=_host_class(kr))
            rd = bmerge.redact_rewrite_own(ctx.pcdir)
            if rd.get("rewritten"):
                ctx.notes.append("redacted_" + str(rd["rewritten"]))
    except BundleBusy:
        ctx.notes.append("bundle_busy")
        _emit("warn", text_ko=HINT_BUSY)
        return _result(ctx, rc=2)
    except ValueError:
        ctx.notes.append("bundle_json_corrupt")                  # person_key 를 새로 만들지 않는다(불변 — 번들 분기 방지)
        _emit("warn", text_ko="bundle.json 형식이 깨져 수집을 멈췄습니다 — 이 폴더의 사본에서 bundle.json 을 되살려 주세요")
        return _result(ctx, rc=1)
    ctx.pc = pcreg.load_pc(ctx.pcdir) or {}
    pcs = pcreg.load_all_pcs(paths)
    try:
        ctx.roles = plan.pc_roles(ctx.pc, pcs=pcs, cfg=cfg, pc_role=pc_role)
    except ValueError:
        ctx.notes.append("pc_role_unknown")
        return _result(ctx, rc=1)
    # 2. 에이전트(설치·복구 — 번들 잠금 없이)
    pre = plan.stage_plan(ctx.roles, {}, ctx.only, cfg=cfg)
    if mode != "probe-only" and _needs_agent(pre):
        ctx.agent = _ensure_agent(ctx)
    ctx.agent_info = _agent_info(ctx)
    if not ctx.agent.get("impl") and ctx.agent_info.get("impl"):
        ctx.agent["impl"] = ctx.agent_info["impl"]
    # 3. 탐침
    _stage(ctx, "probe", _probe_body)
    # 4. 계획
    stages = [] if mode == "probe-only" else plan.stage_plan(ctx.roles, ctx.caps, ctx.only, cfg=cfg)
    later = [s for s in stages if s.name in BACKFILL_STAGES + ("copilot_lookup",)]
    for s in stages:
        if s.name in ("probe", "derive", "upload") or s in later:
            continue
        if s.name == "export":
            _stage(ctx, "export", _export_body(final=not later))
            continue
        if ctx.over_budget():
            _budget_stage(ctx, s.name, s.all_srcs)
            continue
        if s.name == "pc_bundle":
            _stage(ctx, s.name, _pc_bundle_body(s))
        elif s.name == "teams_uia_check":
            _stage(ctx, s.name, _teams_body(s))
        else:
            _stage(ctx, s.name, _collectors_body(s))
    _stage(ctx, "derive", _derive_body)
    # 7. 백필·코파일럿(빈칸만 비싼 경로로) → 내보내기·파생 다시
    for grp in (BACKFILL_STAGES, ("copilot_lookup",)):
        todo_stages = [s for s in later if s.name in grp]
        if not todo_stages:
            continue
        for s in todo_stages:
            if ctx.over_budget():
                _budget_stage(ctx, s.name, s.all_srcs)
            else:
                _stage(ctx, s.name, _collectors_body(s, blanks_of=_blanks, args_of=_web_args))
        last = grp == ("copilot_lookup",) or not any(s.name == "copilot_lookup" for s in later)
        _stage(ctx, "export", _export_body(final=last))
        _stage(ctx, "derive", _derive_body)
    # 8. 대기 업로드
    if any(s.name == "upload" for s in stages):
        _stage(ctx, "upload", _upload_body)
    return _result(ctx)
