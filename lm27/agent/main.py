# -*- coding: utf-8 -*-
r"""PC 상주 에이전트 감독 루프(계약 §2.4 · TAB §1.6.7 · CP §1·§3 · X-017 · X-026 · X-303 · CR-04) — 저장소 원본.

설치(``lm27.agent.install``)가 이 파일을 ``agent\bin\<ver>\agent_main.py`` 로 복사하고, 작업 스케줄러 ``LM27-<install_id>`` 가
``py311\pythonw.exe -X utf8 -I -B agent_main.py --install-id <id>`` 로 로그온마다 1개 띄운다. 스크립트로 돌 때는 자기 폴더
(bin 사본 루트)를 sys.path 에 넣고 ``main(install_id)`` 를 부른다. **ROOT 의 어떤 파일도 읽지 않는다**(TAB §1.9) — 실행 파일·
정제기·수집기는 사본, 설정은 ``agent_config.json``·``context_cache.json``·``keys\subkeys.json``, cwd 는 ``agent\``.

감독 루프 한 틱(``agent.sampleIntervalSec`` 60초, 1초 단위로 깨어 정지 깃발·절전 복귀를 본다):
  · 뮤텍스 ``Local\LM27-<install_id>-agent`` — 이미 있으면 바로 끝(단일 인스턴스).
  · 샘플(``lm27.agent.sampler`` — 원문은 메모리에서만) → 직전 틱의 레코드를 **실제 간격**으로 확정(절전·멈춤으로 명목의 1.5배를
    넘으면 명목 간격만 — CP §3.7·X-080) → 버퍼. 플러시 = 첫 레코드 · ``agent.flushIntervalSec``(300) · ``agent.flushMaxRows``(120)
    · 세션 잠금·끊김 · 절전 복귀 · 종료 때: ``sanitize_record`` 를 이 프로세스 안에서 → ``SegmentWriter`` 가 gzip 멤버 하나로 덧붙임
    (py 구현 — TAB §1.6.1 ①). 연산 구간(솔버 CPU)은 ``pc_compute``(pc.compute)로 같은 방식.
  · heartbeat.json 매 틱 원자 교체(``last_error`` 는 유형·코드만 — R-RULESMISMATCH · R-NOKEY · unflushed_lost · 예외 유형).
  · 자식: 수확(로그온 직후 · ``agent.harvestIntervalH`` · ``run\harvest_now.flag``) = 별도 프로세스(``--harvest``) ·
    teams.uia(``teams.uia.intervalSec``) · 열린 문서 폴링(``agent.filePoll.intervalSec``) = 연결자 스레드(세션이 잠기면 쉰다).
    ``lm27.collect.watch`` 는 사본 밖이므로 자식 감시는 ``lm27.util.proc`` + 정지 플래그로 따로 한다(계획 v1.1).
  · 보존(하루 한 번): store ``agent.storeKeepDays``(``lm27.store.prune_store``) · 감사 ``privacy.audit.retentionMonths``
    (``lm27.privacy.audit.prune_audit``) · 에이전트 로그 30일.
  · 시작 때: 사본 규칙 해시가 ``rules.lock.json`` 과 다르면 수집을 멈추고 heartbeat 에 R-RULESMISMATCH(조용한 축약 정제 금지,
    P §3.6·P-T34) · 하위 키가 없으면 키 없음 모드(행은 저장, 키 열 null + flags.no_key, heartbeat R-NOKEY — P §9.4·P-T29) ·
    지금 pc_id 가 ``agent.json.pc_id`` 와 다르면(풀링 VDI·프로필 이동) agent.json 을 고치고 새 pc_id 의 store 에 쓴다(TAB-B26).

명령줄(사본 진입 ``agent_main.py``): ``--install-id <id>`` [``--test-samples N``(자기 시험 — 저장 없음) · ``--harvest <흐름,…>``
(수확 자식) · ``--check-rules`` · ``--classify``(stdin 실행 파일 이름 → 카탈로그 판정, ps 구현용) · ``--in-line <src> [--poll]``
(수집기 제어 줄 ``_in`` 한 줄, ps 구현용) · ``--maintain``(보존 정리)].

이 파일은 패키지 모듈로도 import 되므로 최상위에서는 표준 라이브러리만 import 하고 ``lm27`` 은 함수 안에서 지연 import 한다(L-05).
"""
import argparse
import os
import sys
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

DEFAULTS = {                     # agent_config.json 이 없을 때의 값(설정 레지스트리 기본값과 같다)
    "agent.sampleIntervalSec": 60, "agent.flushIntervalSec": 300, "agent.flushMaxRows": 120,
    "agent.harvestIntervalH": 6, "agent.storeKeepDays": 400, "agent.filePoll.intervalSec": 300,
    "agent.filePoll.topN": 40, "teams.uia.intervalSec": 300, "teams.uia.budgetSec": 60, "privacy.pipe.waitSec": 120,
    "privacy.audit.retentionMonths": 24, "pc.compute.cpuCoreThreshold": 0.5, "pc.compute.consecutiveTicks": 3,
}
GAP_CAP = 1.5                    # 실제 간격이 명목 × 1.5 를 넘으면 절전·멈춤 — 그 틱은 명목 간격만 인정
WAKE_S = 1.0                     # 루프가 깨어나는 단위(정지 깃발·절전 복귀를 1초 안에 본다)
HARVEST_MAX_S = 1800             # 수확 자식 상한(넘으면 kill_tree)
HARVEST_STREAMS = ("pc_session/pc.events", "pc_file/pc.files", "pc_file/pc.mru", "pc_file/pc.recent")
MAINT_EVERY_S = 86400
MAINT_FIRST_S = 120              # 시작 뒤 첫 보존 정리까지
AUDIT_EVERY_S = 3600             # 감사 이벤트는 한 시간에 한 줄(건수 누적)
RELOAD_EVERY_S = 60              # 설정·문맥·하위 키 바뀜 확인 주기
LOG_KEEP_DAYS = 30
ERR_HOLD_S = 3600                # 일시 오류 유형을 heartbeat 에 남겨 두는 시간
BUF_CAP_FACTOR = 20              # 저장 실패가 이어질 때 버퍼 상한(= flushMaxRows × 이 값)
TEST_GAP_S = 1.0                 # 자기 시험 표본 간격(설치 5초 안팎 — TAB §1.6.6)
HB_SCHEMA = "lm27.hb/1"
LOCKED_STATES = ("locked", "disconnected")


@dataclass(frozen=True)
class AgentIdent:
    """수확 자식 기동에 쓰는 식별(``install_id``·``pc_id``)."""
    install_id: str
    pc_id: str


def _lm():
    """지연 import 묶음 — 사본 안 모듈만(계약 §1.3)."""
    from types import SimpleNamespace

    from lm27 import catalog
    from lm27.agent import exemeta, harvest, sampler
    from lm27.bundle import ids
    from lm27.paths import Paths
    from lm27.privacy import audit as paudit
    from lm27.privacy.context import read_context_cache
    from lm27.privacy.sanitize import make_record_context, sanitize_record
    from lm27.privacy.selftest import lock_matches
    from lm27.store import SegmentWriter, prune_store
    from lm27.util import fsx, proc, tz
    return SimpleNamespace(catalog=catalog, exemeta=exemeta, harvest=harvest, sampler=sampler, ids=ids, Paths=Paths,
                           paudit=paudit, read_context_cache=read_context_cache, make_record_context=make_record_context,
                           sanitize_record=sanitize_record, lock_matches=lock_matches, SegmentWriter=SegmentWriter,
                           prune_store=prune_store, fsx=fsx, proc=proc, tz=tz)


def bin_paths():
    """이 프로세스의 ``Paths`` — 사본(``agent\\bin\\<ver>\\``)에서 돌면 LAD 를 사본 위치에서 정한다(환경 변수와 무관하게 자기 에이전트
    폴더를 쓴다). 저장소 원본에서 돌면(시험) 기본 Paths."""
    import lm27
    from lm27.paths import Paths
    root = Path(lm27.__file__).resolve().parent.parent
    p = Paths(root)
    if p.mode() == "agent" and root.parent.name.lower() == "bin" and root.parent.parent.name.lower() == "agent":
        return Paths(root, lad=root.parent.parent.parent)
    return p


def mutex_name(install_id: str) -> str:
    return f"Local\\LM27-{install_id}-agent"


def win_mutex(name: str):
    """이름 있는 뮤텍스를 만든다 → (핸들, 이미 있었나). 만들지 못하면 (None, False)."""
    import ctypes
    from ctypes import wintypes
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateMutexW.restype = wintypes.HANDLE
    k.CreateMutexW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
    h = k.CreateMutexW(None, False, name)
    err = ctypes.get_last_error()
    if not h:
        return None, False
    return h, err == 183                                     # ERROR_ALREADY_EXISTS


def _close_handle(h) -> None:
    if not h:
        return
    import ctypes
    from ctypes import wintypes
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CloseHandle.argtypes = (wintypes.HANDLE,)
    k.CloseHandle(h)


def _utc(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_utc(s):
    if not isinstance(s, str):
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        return None


def _mtime(p) -> float:
    try:
        return os.stat(p).st_mtime
    except OSError:
        return 0.0


class Agent:
    """감독 루프(py 구현). 시험은 ``api``(가짜 Win32)·``clock``(지금 UTC)·``wait``(초)·``mutex``·``spawn_harvest``·
    ``run_conn``·``probe``·``rules_ok``·``exe_reader``·``recent_dir`` 를 주입한다."""

    def __init__(self, install_id: str, *, paths=None, api=None, clock=None, wait=None, mutex=None, spawn_harvest=None,
                 run_conn=None, probe=None, rules_ok=None, exe_reader=None, recent_dir=None):
        self.L = _lm()
        self.install_id = install_id
        self.paths = paths or bin_paths()
        self.api = api
        self.clock = clock or (lambda: datetime.now(UTC))
        self._stop_ev = threading.Event()
        self.wait = wait or (lambda s: self._stop_ev.wait(s))
        self.mutex = mutex or win_mutex
        self.spawn_harvest = spawn_harvest
        self.run_conn = run_conn or self.L.harvest.run_connector
        self.probe = probe
        self.rules_ok_fn = rules_ok
        self.exe_reader = exe_reader
        self.docs = self.L.sampler.DocIndex(recent_dir)
        self.cfg = dict(DEFAULTS)
        self.pc_id = ""
        self.impl = "py"
        self.agent_ver = ""
        self.started_at = None
        self.pending = None                      # 아직 간격을 모르는 마지막 틱
        self.last_off = 0                        # 마지막 틱의 수집 순간 오프셋(분)
        self.buf_s: list = []                    # 확정된 pc.sampler 원시 레코드(메모리 — 원문 포함)
        self.buf_c: list = []                    # 닫힌 연산 구간 원시 레코드
        self.first_flush_done = False
        self.flush_reason = ""
        self.last_flush = None
        self.rcs: dict = {}
        self.rc_sig = None
        self.rc_checked = None
        self.audit_at = None
        self.no_key = False
        self.rules_ok = True
        self.err = ("", None)                    # (유형·코드, 시각)
        self.samples_today = 0
        self.day = None
        self.harvest_child = None
        self.harvest_started = None
        self.next_harvest = None
        self.last_harvest = {}
        self.jobs: dict = {}                     # 이름 → (스레드, 결과 상자)
        self.job_at: dict = {}
        self.abort = threading.Event()
        self.maint_at = None
        self.exe_seen: set = set()
        self.compute = None
        self.solvers = frozenset()
        self.extra = ()
        self.ticks = 0
        self.mutex_handle = None
        self.state = "init"

    # ── 설정 ──────────────────────────────────────────────────────────
    def _num(self, key: str, lo, hi, kind=int):
        v = self.cfg.get(key, DEFAULTS.get(key))
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            v = DEFAULTS.get(key, lo)
        return kind(min(hi, max(lo, v)))

    @property
    def interval(self) -> int:
        return self._num("agent.sampleIntervalSec", 5, 600)

    def _load_settings(self) -> None:
        L = self.L
        self.cfg = dict(DEFAULTS)
        self.cfg.update(L.harvest.load_settings(self.paths))
        self.extra = L.catalog.programs_extra(self.cfg)
        self.solvers = L.catalog.solver_set(self.cfg)
        th = self._num("pc.compute.cpuCoreThreshold", 0.05, 256.0, float)
        n = self._num("pc.compute.consecutiveTicks", 1, 100)
        if self.compute is None or (self.compute.threshold, self.compute.need) != (th, n):
            self.compute = L.sampler.ComputeTracker(th, n, self.extra)

    # ── 시작 ──────────────────────────────────────────────────────────
    def _agent_json(self) -> dict:
        return self.L.fsx.read_json(self.paths.agent_json(), default={}) or {}

    def _start(self, now: datetime) -> bool:
        L = self.L
        aj = self._agent_json()
        if aj.get("install_id") not in (None, self.install_id):
            return False                                     # 다른 설치의 에이전트 폴더 — 손대지 않는다
        self.impl = "py"
        self.agent_ver = str(aj.get("agent_ver") or "")
        ident = L.ids.identify_pc(self.paths, probe=self.probe)
        self.pc_id = ident.pc_id
        if aj and aj.get("pc_id") != ident.pc_id:              # 풀링 VDI·프로필 이동(TAB §1.8 · B26)
            aj = dict(aj, pc_id=ident.pc_id)
            L.fsx.atomic_write(self.paths.agent_json(), L.fsx.canon_bytes(aj) + b"\n")
            self._log(now, "pc_id_changed")
        old = L.fsx.read_json(self.paths.heartbeat(), default={}) or {}
        if old.get("install_id") == self.install_id and isinstance(old.get("buffered"), int) and old["buffered"] > 0 \
                and old.get("pid") != os.getpid():
            self.err = ("unflushed_lost", now)               # 비정상 종료 — 버퍼(최대 플러시 주기분)만 잃었다(TAB §1.6.7)
        self.rules_ok = bool(self.rules_ok_fn() if self.rules_ok_fn is not None else L.lock_matches())
        self._load_settings()
        self.exe_seen = set(L.exemeta.load_exe_meta(self.paths, self.pc_id))
        self.started_at = now
        self.rc_checked = now
        done = L.fsx.read_json(self.paths.harvest_done(), default={}) or {}
        last = _parse_utc(done.get("finished_at")) if done.get("install_id") == self.install_id else None
        if last is not None:
            self.last_harvest = {"last_at": done.get("finished_at"), "last_rc": done.get("rc")}
        hours = self._num("agent.harvestIntervalH", 1, 48)
        self.next_harvest = now if last is None or now - last >= timedelta(hours=hours) else last + timedelta(hours=hours)
        self.maint_at = now + timedelta(seconds=MAINT_FIRST_S)
        self.state = "running" if self.rules_ok else "rules_mismatch"
        self._log(now, "start", impl=self.impl, rules=int(self.rules_ok))
        return True

    # ── 레코드 문맥(정제기) ─────────────────────────────────────────────
    def _rc_sig(self):
        return (_mtime(self.paths.context_cache()), _mtime(self.paths.agent_subkeys()))

    def _rc(self, src: str):
        sig = self._rc_sig()
        if sig != self.rc_sig:
            self._flush_audit()
            self.rcs = {}
            self.rc_sig = sig
        rc = self.rcs.get(src)
        if rc is None:
            rc = self.rcs[src] = self.L.make_record_context(None, src, self.pc_id, agent_dir=self.paths.agent_dir())
            self.no_key = bool(getattr(rc, "no_key", False))
        return rc

    def _flush_audit(self) -> None:
        """감사 계수가 있는 문맥만 이벤트 1줄(건수·판·해시만 — P §15)."""
        for rc in self.rcs.values():
            c = rc.audit.counts()
            if c.get("rows_in") or any(c.get(k) for k in ("masked", "dropped", "priv", "ad", "err")):
                rc.audit.flush()

    # ── 틱 ────────────────────────────────────────────────────────────
    def _finalize(self, tick, interval_s: float) -> None:
        L = self.L
        _fg, _aid, ac = L.sampler.app_of(tick.fg_exe, self.extra)
        doc = self.docs.path_for(tick.fg_title, ac) if tick.fg_title else None
        self.buf_s.append(L.sampler.tick_record(tick, int(round(interval_s)), extra=self.extra, doc_path=doc))

    def _tick(self, now: datetime) -> None:
        L = self.L
        if not self.rules_ok:
            self._heartbeat(now)
            return
        tick = L.sampler.take_sample(self.pending, api=self.api, now=now, solvers=self.solvers, cfg=self.cfg)
        nominal = self.interval
        if self.pending is None and not self.first_flush_done:
            self._finalize(tick, nominal)                    # 첫 표본은 바로 확정·플러시 — 기동 직후 store 신선(생존 조건 ③)
            self.flush_reason = "first"
        else:
            if self.pending is not None:
                dt = (tick.ts - self.pending.ts).total_seconds()
                gap = dt > nominal * GAP_CAP
                self._finalize(self.pending, nominal if gap or dt <= 0 else dt)
                if gap:
                    self.flush_reason = "gap"
                if tick.session_state != self.pending.session_state and tick.session_state in LOCKED_STATES:
                    self.flush_reason = self.flush_reason or "session"
            self.pending = tick
        self.last_off = tick.off_min
        day = L.tz.to_local(tick.ts, tick.off_min).date()
        if day != self.day:
            self.day, self.samples_today = day, 0
        self.samples_today += 1
        for run in self.compute.observe(tick.ts, tick.cpu):
            self.buf_c.append(L.sampler.compute_record(run, tick.off_min, tick.ts, final=True))
        if tick.errors:
            self.err = (tick.errors[-1], now)
        self._exe_meta(tick)
        self._maybe_flush(now)
        self._heartbeat(now)
        self._children(now, tick)
        self._maintain(now)

    def _maybe_flush(self, now: datetime) -> None:
        if not self.buf_s and not self.buf_c:
            return
        age = (now - self.last_flush).total_seconds() if self.last_flush else None
        due = (not self.first_flush_done or self.flush_reason or age is None
               or age >= self._num("agent.flushIntervalSec", 30, 3600)
               or len(self.buf_s) >= self._num("agent.flushMaxRows", 1, 10000))
        if due:
            self._flush(now)

    def _write(self, kind: str, src: str, raws: list) -> int:
        L = self.L
        if not raws:
            return 0
        rc = self._rc(src)
        w = L.SegmentWriter(self.paths, self.pc_id, kind, src)
        for raw in raws:
            out = L.sanitize_record(kind, raw, rc)
            if out.status == "stored":
                w.append(out.row)
        n = w.flush()
        w.close()
        return n

    def _flush(self, now: datetime, *, final: bool = False) -> int:
        L = self.L
        open_runs = self.compute.close_all() if final else self.compute.open_intervals()
        comp = self.buf_c + [L.sampler.compute_record(r, self.last_off, now, final=final) for r in open_runs]
        try:
            n = self._write("pc_session", "pc.sampler", self.buf_s)
            n += self._write("pc_compute", "pc.compute", comp)
        except (OSError, ValueError) as e:
            self.err = (type(e).__name__, now)
            cap = self._num("agent.flushMaxRows", 1, 10000) * BUF_CAP_FACTOR
            if len(self.buf_s) > cap:
                del self.buf_s[:len(self.buf_s) - cap]
            self._log(now, "flush_failed", err=type(e).__name__)
            return 0
        self.buf_s, self.buf_c = [], []
        self.first_flush_done = True
        self.flush_reason = ""
        self.last_flush = now
        if self.audit_at is None or (now - self.audit_at).total_seconds() >= AUDIT_EVERY_S or final:
            self._flush_audit()
            self.audit_at = now
        return n

    def _exe_meta(self, tick) -> None:
        L = self.L
        exe = tick.fg_exe
        if not exe or exe in self.exe_seen or not tick.fg_path:
            return
        self.exe_seen.add(exe)
        if L.catalog.is_noise(exe) or L.catalog.classify(exe, self.extra) is not None:
            return
        try:
            meta = L.exemeta.observe_exe(tick.fg_path, reader=self.exe_reader, sctx=self._rc("pc.sampler").sctx)
            L.exemeta.save_exe_meta(self.paths, self.pc_id, meta)
        except (OSError, ValueError, TypeError) as e:
            self.err = (type(e).__name__, datetime.now(UTC))

    # ── heartbeat ─────────────────────────────────────────────────────
    def _last_error(self, now: datetime) -> str:
        if not self.rules_ok:
            return "R-RULESMISMATCH"
        if self.no_key:
            return "R-NOKEY"
        code, at = self.err
        if code and at is not None and (now - at).total_seconds() <= ERR_HOLD_S:
            return code[:200]
        return ""

    def _heartbeat(self, now: datetime, *, stopping: bool = False) -> None:
        L = self.L
        buffered = 0 if stopping else len(self.buf_s) + (1 if self.pending is not None else 0)
        hb = {"schema": HB_SCHEMA, "install_id": self.install_id, "pc_id": self.pc_id, "pid": os.getpid(),
              "agent_ver": self.agent_ver, "impl": self.impl, "started_at": _utc(self.started_at or now),
              "last_tick": _utc(now), "interval_s": self.interval, "samples_today": self.samples_today,
              "harvest": {"last_at": self.last_harvest.get("last_at"), "last_rc": self.last_harvest.get("last_rc"),
                          "next_at": _utc(self.next_harvest) if self.next_harvest else None},
              "last_error": self._last_error(now), "buffered": buffered, "state": "stopped" if stopping else self.state}
        try:
            L.fsx.atomic_write(self.paths.heartbeat(), L.fsx.canon_bytes(hb) + b"\n", fsync=False)
        except OSError as e:
            self.err = (type(e).__name__, now)

    # ── 자식(수확·teams.uia·열린 문서 폴링) ───────────────────────────────
    def _children(self, now: datetime, tick) -> None:
        self._harvest(now)
        active = tick.session_state not in LOCKED_STATES
        if active:
            self._job(now, "teams.uia", self._num("teams.uia.intervalSec", 120, 300), poll=False)
            self._job(now, "poll", self._num("agent.filePoll.intervalSec", 30, 3600), poll=True)
        self._reap_jobs(now)

    def _harvest(self, now: datetime) -> None:
        L = self.L
        ch = self.harvest_child
        if ch is not None:
            if ch.poll() is None:
                if (now - self.harvest_started).total_seconds() > HARVEST_MAX_S:
                    ch.kill_tree()
                    self._log(now, "harvest_killed")
                else:
                    return
            done = L.fsx.read_json(self.paths.harvest_done(), default={}) or {}
            if done.get("install_id") == self.install_id and done.get("started_at", "") >= _utc(self.harvest_started):
                self.last_harvest = {"last_at": done.get("finished_at"), "last_rc": done.get("rc")}
            else:
                self.last_harvest = {"last_at": _utc(now), "last_rc": ch.returncode if ch.returncode is not None else 3}
            self._log(now, "harvest_end", rc=self.last_harvest.get("last_rc"))
            self.harvest_child = None
        flag = self.paths.harvest_now_flag()
        requested = flag.is_file()
        if not requested and (self.next_harvest is None or now < self.next_harvest):
            return
        spawn = self.spawn_harvest or (lambda ident, streams, requested: L.harvest.start_harvest_child(
            ident, streams, paths=self.paths, impl="py", requested=requested))
        try:
            self.harvest_child = spawn(AgentIdent(self.install_id, self.pc_id), HARVEST_STREAMS, requested)
        except OSError as e:
            self.err = (type(e).__name__, now)
            self.next_harvest = now + timedelta(minutes=10)
            return
        self.harvest_started = now
        self.next_harvest = now + timedelta(hours=self._num("agent.harvestIntervalH", 1, 48))
        if requested:
            try:
                os.remove(flag)
            except OSError:
                pass
        self._log(now, "harvest_start", requested=int(requested))

    def _job(self, now: datetime, name: str, every_s: int, *, poll: bool) -> None:
        if name in self.jobs:
            return
        last = self.job_at.get(name)
        if last is not None and (now - last).total_seconds() < every_s:
            return
        self.job_at[name] = now
        box: dict = {}
        src = "pc.files" if poll else name

        def run():
            try:
                box["res"] = self.run_conn(self.paths, self.pc_id, src, settings=dict(self.cfg),
                                           ctxcache=self.L.read_context_cache(self.paths.agent_dir()) or {},
                                           poll=poll, abort=self.abort)
            except Exception as e:                       # noqa: BLE001 — 자식 실패로 감독 루프가 죽지 않는다(유형만)
                box["err"] = type(e).__name__
        t = threading.Thread(target=run, name=f"lm27-agent-{name}", daemon=True)
        self.jobs[name] = (t, box)
        t.start()

    def _reap_jobs(self, now: datetime) -> None:
        for name, (t, box) in list(self.jobs.items()):
            if t.is_alive():
                continue
            del self.jobs[name]
            r = box.get("res")
            if r is not None:
                self._log(now, name, rc=r.rc, pipe=r.pipe, stored=r.stored, skipped=r.skipped or None,
                          reasons=",".join(r.reasons) or None)
                if r.pipe == 6:
                    self.no_key = True
            elif box.get("err"):
                self.err = (box["err"], now)

    # ── 보존 정리 ──────────────────────────────────────────────────────
    def _maintain(self, now: datetime) -> None:
        if self.maint_at is None or now < self.maint_at:
            return
        self.maint_at = now + timedelta(seconds=MAINT_EVERY_S)
        self.maintain(now)

    def maintain(self, now: datetime) -> dict:
        L = self.L
        out = {}
        try:
            out["store"] = L.prune_store(self.paths, self.pc_id, self._num("agent.storeKeepDays", 30, 3650),
                                         today=now.astimezone(UTC).date())
            out["audit"] = L.paudit.prune_audit(self.paths, self._num("privacy.audit.retentionMonths", 1, 120),
                                                today=now.astimezone(UTC).date())
            out["logs"] = prune_logs(self.paths, now)
        except (OSError, ValueError) as e:
            self.err = (type(e).__name__, now)
        self._log(now, "maintain", **{k: v for k, v in out.items() if isinstance(v, int)})
        return out

    # ── 로그 ──────────────────────────────────────────────────────────
    def _log(self, now: datetime, code: str, **kv) -> None:
        parts = [_utc(now), code] + [f"{k}={v}" for k, v in sorted(kv.items()) if v is not None]
        try:
            self.L.fsx.append_line(self.paths.agent_log_file(now), " ".join(parts))
        except (OSError, ValueError):
            pass

    # ── 실행 ──────────────────────────────────────────────────────────
    def _stopping(self) -> bool:
        return self._stop_ev.is_set() or self.paths.stop_flag().is_file()

    def _reload(self, now: datetime) -> None:
        if self.rc_checked is not None and (now - self.rc_checked).total_seconds() < RELOAD_EVERY_S:
            return
        self.rc_checked = now
        self._load_settings()

    def run(self, max_ticks: int | None = None) -> int:
        """감독 루프. 반환 0(정상 종료·이미 실행 중). ``max_ticks`` = 시험용 틱 상한."""
        h, exists = self.mutex(mutex_name(self.install_id))
        own = self.mutex is win_mutex
        if exists:
            if own:
                _close_handle(h)
            return 0
        self.mutex_handle = h
        try:
            now = self.clock()
            if self._stopping() or not self._start(now):
                return 0
            next_tick = now
            self._heartbeat(now)
            while not self._stopping():
                now = self.clock()
                if now >= next_tick:
                    self._reload(now)
                    try:
                        self._tick(now)
                    except Exception as e:               # noqa: BLE001 — 루프 안 예외로 죽지 않는다(유형만 기록)
                        self.err = (type(e).__name__, now)
                        self._log(now, "tick_error", err=type(e).__name__)
                    self.ticks += 1
                    if max_ticks is not None and self.ticks >= max_ticks:
                        break
                    next_tick += timedelta(seconds=self.interval)
                    if next_tick <= now:                     # 절전·멈춤 뒤 — 지금부터 다시 센다
                        next_tick = now + timedelta(seconds=self.interval)
                else:
                    self.wait(min(WAKE_S, max(0.0, (next_tick - now).total_seconds())))
            self._shutdown(self.clock())
            return 0
        finally:
            if own:
                _close_handle(self.mutex_handle)

    def _shutdown(self, now: datetime) -> None:
        self.abort.set()
        if self.pending is not None and self.rules_ok:
            dt = (now - self.pending.ts).total_seconds()
            self._finalize(self.pending, min(max(dt, 1.0), float(self.interval)))
            self.pending = None
        if self.rules_ok and self.started_at is not None:
            self._flush(now, final=True)
        for t, _box in list(self.jobs.values()):
            t.join(10)
        self._reap_jobs(now)
        self._heartbeat(now, stopping=True)
        self._log(now, "stop")

    def stop(self) -> None:
        self._stop_ev.set()


def prune_logs(paths, now: datetime, keep_days: int = LOG_KEEP_DAYS) -> int:
    """에이전트 로그 ``logs\\agent_YYYYMMDD.log`` 중 keep_days 보다 오래된 것을 지운다. 지운 수."""
    d = paths.agent_logs()
    if not d.is_dir():
        return 0
    cut = (now.astimezone(UTC) - timedelta(days=keep_days)).strftime("%Y%m%d")
    n = 0
    for f in d.iterdir():
        name = f.name
        if name.startswith("agent_") and name.endswith(".log") and len(name) == 18 and name[6:14].isdigit() \
                and name[6:14] < cut:
            try:
                os.remove(f)
                n += 1
            except OSError:
                continue
    return n


def main(install_id: str, **kw) -> int:
    """에이전트 감독 루프 진입(계약 §2.4). 키워드 인자는 시험 주입(``Agent`` 참조)."""
    return Agent(install_id, **kw).run()


# ───────────────────────────── 보조 명령(자기 시험 · 수확 자식 · ps 구현 도우미) ─────────────────────────────
def corpus_ok(n: int = 5) -> int:
    """회귀 말뭉치 양성(문맥 없음) 앞 n 건을 사본 정제기로 돌려 기대와 같은 건수(TAB §1.6.1 자기 시험 '정제 회귀 표본 5건')."""
    from lm27.privacy.detect import SanitizeContext, sanitize
    from lm27.privacy.selftest import load_corpus
    ok = 0
    rows = [r for r in load_corpus() if r.get("type") == "pos" and not r.get("ctx") and "#*" not in r.get("expect", "")]
    for r in rows[:n]:
        res = sanitize(r["text"], ctx=SanitizeContext())
        if res.text == r["expect"] and res.hits == r.get("hits", {}) and not res.drop:
            ok += 1
    return ok


def self_test(n: int = 3, *, api=None, gap: float = TEST_GAP_S, sleep=time.sleep, out=None) -> int:
    """py 구현 자기 시험(``--test-samples N``): 표본 N 개(뮤텍스·저장 없음) + 규칙 잠금 + 말뭉치 5건. 출력은 숫자·참거짓 한 줄."""
    L = _lm()
    res = {"impl": "py", "samples": 0, "fg": 0, "idle": 0, "session": 0, "rules": False, "corpus": 0, "ok": False}
    try:
        for i in range(max(1, n)):
            if i:
                sleep(gap)
            t = L.sampler.take_sample(None, api=api)
            res["samples"] += 1
            res["fg"] += int(bool(t.ok.get("fg")))
            res["idle"] += int(bool(t.ok.get("idle")))
            res["session"] += int(bool(t.ok.get("session")))
        res["rules"] = bool(L.lock_matches())
        res["corpus"] = corpus_ok(5)
        res["ok"] = (res["samples"] == max(1, n) and res["fg"] > 0 and res["idle"] > 0 and res["session"] > 0
                     and res["rules"] and res["corpus"] >= 5)
    except Exception as e:                               # noqa: BLE001 — 자기 시험: 실패 유형만 보고
        res["error"] = type(e).__name__
    st = out if out is not None else sys.stdout
    if st is not None:
        st.write(L.fsx.canon_bytes({"_selftest": res}).decode("utf-8") + "\n")
        st.flush()
    return 0 if res["ok"] else 1


def start_check(paths, install_id: str, *, probe=None, rules_ok=None) -> dict:
    """ps 구현 시작 점검(``--start-check``): 사본 규칙 잠금 일치(P §3.6) + 지금 pc_id(바뀌었으면 agent.json 을 고친다 — TAB-B26).
    반환 ``{rules_ok, pc_id, pc_id_changed}``."""
    L = _lm()
    ident = L.ids.identify_pc(paths, probe=probe)
    aj = L.fsx.read_json(paths.agent_json(), default={}) or {}
    changed = False
    if aj and aj.get("install_id") == install_id and aj.get("pc_id") != ident.pc_id:
        L.fsx.atomic_write(paths.agent_json(), L.fsx.canon_bytes(dict(aj, pc_id=ident.pc_id)) + b"\n")
        changed = True
    ok = rules_ok() if rules_ok is not None else L.lock_matches()
    return {"rules_ok": bool(ok), "pc_id": ident.pc_id, "pc_id_changed": changed}


def classify_lines(lines, settings: dict) -> list:
    """실행 파일 이름들 → [{exe, fg_exe, app_id, app_class, solver}](ps 구현의 카탈로그 판정 — 카탈로그는 파이썬 한 곳)."""
    from lm27 import catalog
    from lm27.agent.sampler import app_of
    extra = catalog.programs_extra(settings)
    solvers = catalog.solver_set(settings)
    out = []
    for raw in lines:
        name = str(raw).strip().strip("﻿")
        if not name or len(name) > 260:
            continue
        fg, aid, ac = app_of(catalog.exe_name(name), extra)
        out.append({"exe": name.lower(), "fg_exe": fg, "app_id": aid, "app_class": ac,
                    "solver": catalog.is_solver(name, settings, solvers=solvers)})
    return out


def _cli(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="agent_main.py", add_help=False)
    ap.add_argument("--install-id", required=True)
    ap.add_argument("--test-samples", type=int)
    ap.add_argument("--harvest")
    ap.add_argument("--requested", action="store_true")
    ap.add_argument("--check-rules", action="store_true")
    ap.add_argument("--start-check", action="store_true")
    ap.add_argument("--classify", action="store_true")
    ap.add_argument("--in-line")
    ap.add_argument("--poll", action="store_true")
    ap.add_argument("--maintain", action="store_true")
    try:
        a = ap.parse_args(argv)
    except SystemExit:
        return 5
    iid = a.install_id.strip().lower()
    if len(iid) != 32 or any(c not in "0123456789abcdef" for c in iid):
        return 5
    if a.test_samples is not None:
        return self_test(a.test_samples)
    L = _lm()
    paths = bin_paths()
    if a.check_rules:
        return 0 if L.lock_matches() else 1
    aj = L.fsx.read_json(paths.agent_json(), default={}) or {}
    if aj.get("install_id") not in (None, iid):
        return 3
    if a.classify:
        out = classify_lines(sys.stdin.read().splitlines(), L.harvest.load_settings(paths))
        for o in out:
            sys.stdout.write(L.fsx.canon_bytes(o).decode("utf-8") + "\n")
        return 0
    if a.start_check:
        sys.stdout.write(L.fsx.canon_bytes(start_check(paths, iid)).decode("utf-8") + "\n")
        return 0
    pc_id = aj.get("pc_id") or L.ids.identify_pc(paths).pc_id
    if a.in_line:
        spec = L.harvest.POLL if a.poll else L.harvest.COLLECTORS.get(a.in_line)
        if spec is None:
            return 5
        from lm27.store import load_raw_cursor
        line = L.harvest.in_line(spec, L.harvest.load_settings(paths), L.harvest.load_ctxcache(paths),
                                 load_raw_cursor(paths, pc_id).get(spec.src))
        if line is None:
            return 4
        sys.stdout.write(L.fsx.canon_bytes(line).decode("utf-8") + "\n")
        return 0
    if a.maintain:
        ag = Agent(iid, paths=paths)
        ag.pc_id = pc_id
        ag._load_settings()
        ag.maintain(datetime.now(UTC))
        return 0
    if a.harvest:
        done = L.harvest.run_harvest(paths, iid, pc_id, [s for s in a.harvest.split(",") if s],
                                     requested=a.requested)
        return int(done.get("rc", 3)) if isinstance(done.get("rc"), int) else 3
    return main(iid, paths=paths)


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    _here = os.path.dirname(os.path.abspath(__file__))
    if os.path.basename(_here).lower() == "agent" and os.path.isfile(os.path.join(os.path.dirname(_here), "paths.py")):
        sys.path.insert(0, os.path.dirname(os.path.dirname(_here)))   # 저장소 원본 위치(lm27\agent\main.py)에서 직접 실행
    sys.exit(_cli(sys.argv[1:]))
