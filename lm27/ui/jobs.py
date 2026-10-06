# -*- coding: utf-8 -*-
r"""화면 작업(job) 관리자 — R §2.3.5 · 계약 §3.23(``ui\jobs\<job_id>.json``) · §7.1 · §8.3 · §8.6 · §8.7.

    jm = JobManager(paths, cfg)
    job = jm.start("analyze", ["analyze", "--from", D, "--to", D])     # 같은 lane 이 돌고 있으면 BusyError(→ 409 busy)
    jm.get(job.job_id, since=0)                                       # {job_id, kind, lane, state, rc, events[…], result}
    jm.cancel(job.job_id)                                             # 정지 플래그 → 5초 → kill_tree(§8.7)
    jm.schedule("quick_reanalyze", argv_fn, delay_s=20, key="qr")     # 디바운스(같은 key 면 시각만 미룬다)
    jm.close()                                                        # 서버 종료 — 돌던 작업을 끝내고 스레드를 합류

- 오래 걸리는 일은 서버 안에서 하지 않고 ``lm27_cli.py`` 하위 프로세스로 띄운다(화면이 멈추지 않고, 작업이 죽어도 서버는 산다).
  argv = ``[python, -X utf8 -B, lm27_cli.py, <명령…>, --job <id>, --events jsonl]``(계약 §7.1 — 실행 플래그 §9.1). 작업 폴더는
  ``%TEMP%``(폴더 이동을 막지 않게 — TAB §1.9).
- lane: ``bundle``(번들 쓰기 — 동시에 하나) · ``net``(팀 전송·레지스트리) · ``local``(읽기 전용·빠른 일). 같은 lane 의 두 번째
  작업은 몰래 쌓지 않고 ``BusyError`` 다(R §2.3.5 — 409 busy).
- 이벤트: 하위 명령의 한 줄 JSON(§8.6)을 허용 필드만 남겨 작업별 seq 를 다시 매긴다(``ui.jobEventsKeep`` 줄 보관). 사람용 줄·
  모르는 ``ev`` 는 버린다. ``text_ko`` 는 각 명세 사용자 문구 표 문장만 온다(원문·경로 없음 — 하위 명령의 의무).
- rc → state: 0·4 ``done`` · 2 ``partial`` · 그 밖 ``failed``(결과 없이 끝나도 rc·마지막 이벤트 보존 — R §11) · 취소 ``cancelled``.
- 기록: ``ui\jobs\<job_id>.json`` = ``{job_id, kind, lane, state, started, ended, rc, events(꼬리 200), result, name_ko}`` —
  argv·경로·이름·원문 없음(계약 §3.23). 서버가 다시 떠도 마지막 20건을 '최근 작업'으로 보인다(RPT-39 ③). 파일은 최근
  ``KEEP_FILES`` 개만 남긴다.
- 취소(§8.7): 작업별 정지 플래그(``Paths.ui_job_stop_flag`` — CR, 없으면 ``ui\jobs\<job_id>.stop``)를 쓰고 ``CANCEL_GRACE_S``
  (5초) 기다린 뒤 살아 있으면 ``lm27.util.proc.kill_tree``. 모든 작업 명령은 재개 가능하다(각 명세의 저널·커서 계약).
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

from lm27.util import fsx, proc
from lm27.util.events import EVENTS
from lm27.util.tz import new_job_id

__all__ = ["CANCEL_GRACE_S", "FINISHED", "KINDS", "LANES", "BusyError", "Job", "JobManager", "state_of", "stop_flag_path"]

LANES = ("bundle", "net", "local")
# kind → (lane, 한국어 이름) — R §2.3.5 표(team_server 는 분리 프로세스라 작업 관리자가 띄우지 않는다 — api_team)
KINDS = {
    "collect": ("bundle", "수집"),
    "move_prepare": ("bundle", "이동 준비"),
    "bundle_merge": ("bundle", "번들 합치기"),
    "analyze": ("bundle", "분석"),
    "quick_reanalyze": ("bundle", "빠른 재분석"),
    "team_build": ("bundle", "팀 묶음 만들기"),
    "report_build": ("local", "보고서 만들기"),
    "report_export": ("local", "보고서 내보내기"),
    "agent_repair": ("local", "에이전트 복구"),
    "team_send": ("net", "팀 묶음 보내기"),
    "registry_fetch": ("net", "레지스트리 받기"),
}
STATES = ("queued", "running", "done", "partial", "failed", "cancelled")
FINISHED = frozenset({"done", "partial", "failed", "cancelled"})
CANCEL_GRACE_S = 5.0
RECORD_EVENTS = 200                      # 작업 기록 파일의 이벤트 꼬리(계약 §3.23)
RECENT = 20                              # 서버 재기동 뒤 보일 최근 작업 수(R §2.3.5)
KEEP_FILES = 100                         # ui\jobs\ 에 남길 작업 기록 파일 수(오래된 것부터 지움)
KEEP_MEMORY = 60                         # 메모리에 둘 끝난 작업 수
BUSY_RETRY_S = 5.0                       # 예약 작업이 lane 이 비기를 기다리는 간격
_EVENT_KEYS = ("ts", "ev", "stage", "name_ko", "text_ko", "done", "total", "rc", "code", "level", "reason", "state")
_TEXT_MAX = 300
_RESULT_MAX = 64 * 1024


class BusyError(Exception):
    """같은 lane 의 작업이 이미 돈다 — 화면은 409 busy + '지금 '<작업 이름>'이 진행 중입니다'."""

    def __init__(self, job: Job):
        super().__init__(f"지금 '{job.name_ko}'이 진행 중입니다 — 끝나면 다시 눌러 주세요")
        self.job = job


def state_of(rc, cancelled: bool = False) -> str:
    """하위 명령 rc(계약 §8.3) → 작업 상태."""
    if cancelled:
        return "cancelled"
    if rc in (0, 4):
        return "done"
    if rc == 2:
        return "partial"
    return "failed"


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def stop_flag_path(paths, job_id: str):
    r"""작업별 정지 플래그 — ``Paths.ui_job_stop_flag(job_id)``(CR). 그 메서드가 아직 없으면 작업 기록 폴더의 ``<job_id>.stop``."""
    fn = getattr(paths, "ui_job_stop_flag", None)
    if callable(fn):
        return fn(job_id)
    rec = paths.ui_job_file(job_id)                     # job_id 형식 검증(ValueError)
    return rec.with_name(rec.stem + ".stop")


def _clean_event(raw) -> dict | None:
    """하위 명령의 한 줄 이벤트 → 허용 필드만(§8.6). 모르는 ev·형식 아닌 줄은 None."""
    if not isinstance(raw, dict) or raw.get("ev") not in EVENTS:
        return None
    out = {}
    for k in _EVENT_KEYS:
        v = raw.get(k)
        if v is None:
            continue
        if isinstance(v, str):
            out[k] = v[:_TEXT_MAX]
        elif isinstance(v, (int, float)) and not isinstance(v, bool):
            out[k] = v
        elif isinstance(v, bool):
            out[k] = v
    if raw.get("ev") == "result" and isinstance(raw.get("data"), (dict, list)):
        try:
            if len(json.dumps(raw["data"], ensure_ascii=False, allow_nan=False)) <= _RESULT_MAX:
                out["data"] = raw["data"]
        except (TypeError, ValueError):
            pass
    return out


def _adapt_result(kind: str, data):
    """작업 kind 별 결과 모양(화면이 읽는 형 — WP-36): team_build → item, report_export → files·dir."""
    if not isinstance(data, dict):
        return {"data": data} if data is not None else None
    out = dict(data)
    if kind == "team_build":
        p = data.get("path") or data.get("name") or ""
        name = os.path.basename(str(p))
        if name.endswith(".json"):
            name = name[:-5]
        if name:
            out["item"] = name
    elif kind == "report_export":
        files = data.get("files")
        if isinstance(files, list):
            out["files"] = [{k: f.get(k) for k in ("path", "variant", "format", "bytes") if k in f}
                            for f in files if isinstance(f, dict)]
        if data.get("out_dir") and not data.get("dir"):
            out["dir"] = data.get("out_dir")
    return out


@dataclass
class Job:
    job_id: str
    kind: str
    lane: str
    name_ko: str
    argv: list = field(default_factory=list, repr=False)
    state: str = "queued"
    started: str | None = None
    ended: str | None = None
    rc: int | None = None
    events: list = field(default_factory=list)
    result: dict | None = None
    seq: int = 0
    lost: bool = False
    pid: int | None = None
    keep: int = 500
    # 내부
    child: object = field(default=None, repr=False)
    cancel_req: bool = False
    due: float | None = None
    argv_fn: object = field(default=None, repr=False)
    key: str | None = None

    def add_event(self, ev: dict) -> None:
        self.seq += 1
        ev["seq"] = self.seq
        self.events.append(ev)
        if len(self.events) > self.keep:
            del self.events[: len(self.events) - self.keep]
        if ev.get("ev") == "result" and "data" in ev:
            self.result = _adapt_result(self.kind, ev["data"])

    def view(self, since: int = 0) -> dict:
        evs = [dict(e) for e in self.events if int(e.get("seq", 0)) > since]
        out = {"job_id": self.job_id, "kind": self.kind, "lane": self.lane, "name_ko": self.name_ko, "state": self.state,
               "started": self.started, "ended": self.ended, "rc": self.rc, "events": evs, "result": self.result,
               "seq": self.seq}
        if self.lost:
            out["lost"] = True
        return out

    def record(self) -> dict:
        """작업 기록 파일(계약 §3.23) — argv·pid·경로 없음."""
        return {"job_id": self.job_id, "kind": self.kind, "lane": self.lane, "name_ko": self.name_ko, "state": self.state,
                "started": self.started, "ended": self.ended, "rc": self.rc,
                "events": self.events[-RECORD_EVENTS:], "result": self.result, "seq": self.seq}


class JobManager:
    """작업 실행·추적. 스레드 안전(RLock). ``spawn`` 은 시험 주입점(기본 ``lm27.util.proc.spawn``)."""

    def __init__(self, paths, cfg=None, *, spawn=None, python=None, cli=None, cwd=None, on_done=None,
                 keep_events=None):
        self.paths = paths
        self._spawn = spawn or proc.spawn
        self._python = python
        self._cli = cli
        self._cwd = cwd or tempfile.gettempdir()
        self._on_done = on_done
        self._keep = int(keep_events if keep_events is not None else
                         (cfg["ui.jobEventsKeep"] if cfg is not None else 500))
        self.poll_ms = int(cfg["ui.jobPollMs"]) if cfg is not None else 1000
        self._lock = threading.RLock()
        self._cv = threading.Condition(self._lock)
        self._jobs: dict[str, Job] = {}
        self._threads: list[threading.Thread] = []
        self._closed = False
        self._sched = None
        self._load_recent()

    # ── 실행 파일 ────────────────────────────────────────────────────────
    def base_argv(self) -> list:
        """``[python, -X utf8 -B, lm27_cli.py]``(계약 §7.1 · §9.1 — CLI·화면 플래그)."""
        py = self._python
        if py is None:
            exe = self.paths.python_exe()
            py = os.fspath(exe) if os.path.isfile(fsx.longp(exe)) else _sys_python()
        cli = self._cli or os.fspath(self.paths.cli_script())
        return [os.fspath(py), "-X", "utf8", "-B", cli]

    # ── 공개 ────────────────────────────────────────────────────────────
    def start(self, kind: str, argv, lane: str | None = None) -> Job:
        lane_, name = self._kind(kind, lane)
        with self._lock:
            self._check_open()
            busy = self.busy_in(lane_)
            if busy is not None:
                raise BusyError(busy)
            job = self._new(kind, lane_, name, list(argv))
            self._launch(job)
            return job

    def schedule(self, kind: str, argv_fn, *, delay_s: float, lane: str | None = None, key: str | None = None) -> Job:
        """``delay_s`` 뒤에 띄울 작업(디바운스 — 같은 key 의 대기 작업이 있으면 시각만 미루고 그 작업을 돌려준다).
        ``argv_fn()`` 은 띄우는 순간 부른다(None 이면 띄우지 않고 failed — 할 일이 없어짐)."""
        lane_, name = self._kind(kind, lane)
        with self._lock:
            self._check_open()
            due = time.monotonic() + max(0.0, float(delay_s))
            if key is not None:
                for j in self._jobs.values():
                    if j.key == key and j.state == "queued" and j.child is None:
                        j.due = due
                        j.argv_fn = argv_fn
                        self._cv.notify_all()
                        return j
            job = self._new(kind, lane_, name, [])
            job.due, job.argv_fn, job.key = due, argv_fn, key
            self._persist(job)
            self._ensure_scheduler()
            self._cv.notify_all()
            return job

    def get(self, job_id: str, since: int = 0) -> dict | None:
        with self._lock:
            j = self._jobs.get(job_id)
            return j.view(since) if j is not None else None

    def list(self) -> list:
        with self._lock:
            js = sorted(self._jobs.values(), key=lambda j: j.job_id, reverse=True)
            live = [j for j in js if j.state not in FINISHED]
            done = [j for j in js if j.state in FINISHED][:RECENT]
            return [j.view(j.seq) | {"events": j.events[-1:]} for j in live + done]

    def running(self) -> list:
        with self._lock:
            return [j for j in self._jobs.values() if j.state not in FINISHED]

    def busy_in(self, lane: str) -> Job | None:
        with self._lock:
            for j in sorted(self._jobs.values(), key=lambda x: x.job_id):
                if j.lane == lane and j.state == "running":
                    return j
            return None

    def cancel(self, job_id: str) -> bool:
        """취소 요청. 끝난 작업·없는 작업이면 False. 대기(예약) 작업은 바로 cancelled."""
        with self._lock:
            j = self._jobs.get(job_id)
            if j is None or j.state in FINISHED:
                return False
            if j.child is None:
                j.state, j.ended = "cancelled", _now_iso()
                j.cancel_req = True
                self._persist(j)
                self._cv.notify_all()
                return True
            if j.cancel_req:
                return True
            j.cancel_req = True
            child = j.child
        try:
            fsx.atomic_write(stop_flag_path(self.paths, job_id), b"stop\n")
        except (OSError, ValueError):
            pass                                        # 플래그를 못 써도 5초 뒤 kill_tree 로 끝낸다
        self._spawn_thread(self._cancel_after, (j, child), "lm27-ui-job-cancel")
        return True

    def close(self, *, kill: bool = True, timeout: float = 15.0) -> None:
        """서버 종료: 대기 작업 취소, 돌던 작업은 kill_tree(kill=True) 후 모든 스레드 합류."""
        with self._lock:
            self._closed = True
            for j in self._jobs.values():
                if j.state == "queued" and j.child is None:
                    j.state, j.ended, j.cancel_req = "cancelled", _now_iso(), True
                    self._persist(j)
                elif j.child is not None and j.state not in FINISHED and kill:
                    j.cancel_req = True
            kids = [j.child for j in self._jobs.values() if j.child is not None and j.state not in FINISHED and kill]
            self._cv.notify_all()
        for ch in kids:
            try:
                ch.kill_tree()
            except (OSError, ValueError):
                pass
        deadline = time.monotonic() + timeout
        for t in list(self._threads):
            t.join(max(0.0, deadline - time.monotonic()))
        with self._lock:
            self._threads = [t for t in self._threads if t.is_alive()]

    # ── 내부 ────────────────────────────────────────────────────────────
    def _kind(self, kind, lane):
        if kind not in KINDS:
            raise ValueError("jobs: 모르는 작업 종류입니다")
        lane_, name = KINDS[kind]
        if lane is not None:
            if lane not in LANES:
                raise ValueError("jobs: lane 은 bundle·net·local")
            lane_ = lane
        return lane_, name

    def _check_open(self):
        if self._closed:
            raise RuntimeError("jobs: 작업 관리자가 닫혔습니다")

    def _new(self, kind, lane, name, argv) -> Job:
        jid = new_job_id()
        while jid in self._jobs:
            jid = new_job_id()
        job = Job(job_id=jid, kind=kind, lane=lane, name_ko=name, argv=argv, keep=self._keep)
        self._jobs[jid] = job
        self._prune_memory()
        return job

    def _launch(self, job: Job) -> None:
        argv = self.base_argv() + list(job.argv) + ["--job", job.job_id, "--events", "jsonl"]
        try:
            child = self._spawn(argv, stdin=proc.DEVNULL, stdout=proc.PIPE, stderr=proc.STDERR_TAIL, cwd=self._cwd)
        except OSError as e:
            job.state, job.rc, job.started, job.ended = "failed", 1, _now_iso(), _now_iso()
            job.add_event({"ev": "warn", "text_ko": f"작업을 띄우지 못했습니다({type(e).__name__})"})
            self._persist(job)
            self._done(job)
            return
        job.child, job.pid, job.state, job.started = child, getattr(child, "pid", None), "running", _now_iso()
        job.argv = []                                   # 실행 뒤에는 argv 를 들고 있지 않는다(경로 등)
        self._persist(job)
        reader = self._spawn_thread(self._pump, (job, child), "lm27-ui-job-out")
        self._spawn_thread(self._wait, (job, child, reader), "lm27-ui-job-wait")

    def _spawn_thread(self, fn, args, name) -> threading.Thread:
        t = threading.Thread(target=fn, args=args, name=name, daemon=True)
        with self._lock:
            self._threads = [x for x in self._threads if x.is_alive()]
            self._threads.append(t)
        t.start()
        return t

    def _pump(self, job: Job, child) -> None:
        try:
            for line in child.iter_lines():
                s = line.strip()
                if not s.startswith("{"):
                    continue
                try:
                    ev = _clean_event(json.loads(s))
                except ValueError:
                    continue
                if ev is not None:
                    with self._lock:
                        job.add_event(ev)
        except (OSError, ValueError):
            pass

    def _wait(self, job: Job, child, reader: threading.Thread) -> None:
        try:
            rc = child.wait()
        except OSError:
            rc = None
        reader.join(proc.DRAIN_S)
        try:
            child.close()
        except OSError:
            pass
        with self._lock:
            job.rc = rc if isinstance(rc, int) else None
            job.state = state_of(job.rc, job.cancel_req)
            job.ended = _now_iso()
            job.child = None
            if job.state == "failed" and not any(e.get("text_ko") for e in job.events):
                job.add_event({"ev": "warn", "text_ko": "작업이 결과 없이 끝났습니다(rc " + str(job.rc) + ") — 다시 누르면 "
                                                         "남은 것부터 이어 합니다"})
            self._persist(job)
            self._cv.notify_all()
        try:
            os.remove(fsx.longp(stop_flag_path(self.paths, job.job_id)))
        except (OSError, ValueError):
            pass
        self._done(job)

    def _cancel_after(self, job: Job, child) -> None:
        deadline = time.monotonic() + CANCEL_GRACE_S
        while time.monotonic() < deadline:
            if child.poll() is not None:
                return
            time.sleep(0.1)
        try:
            child.kill_tree()
        except (OSError, ValueError):
            pass

    def _done(self, job: Job) -> None:
        if self._on_done is not None:
            try:
                self._on_done(job)
            except Exception:                           # 콜백 실패가 작업 기록을 망가뜨리지 않게(유형만 남길 곳이 없음)
                pass

    # 예약 ---------------------------------------------------------------
    def _ensure_scheduler(self) -> None:
        if self._sched is None or not self._sched.is_alive():
            self._sched = self._spawn_thread(self._sched_loop, (), "lm27-ui-job-sched")

    def _sched_loop(self) -> None:
        with self._lock:
            while not self._closed:
                pend = [j for j in self._jobs.values() if j.state == "queued" and j.child is None and j.due is not None]
                if not pend:
                    return
                now = time.monotonic()
                j = min(pend, key=lambda x: x.due)
                if j.due > now:
                    self._cv.wait(min(j.due - now, 5.0))
                    continue
                if self.busy_in(j.lane) is not None:
                    j.due = now + BUSY_RETRY_S
                    continue
                fn, j.argv_fn, j.due = j.argv_fn, None, None
                try:
                    argv = fn() if callable(fn) else None
                except Exception:                       # 인자를 만들지 못함(분석 결과 없음 등)
                    argv = None
                if not argv:
                    j.state, j.rc, j.started, j.ended = "failed", 4, _now_iso(), _now_iso()
                    j.add_event({"ev": "msg", "text_ko": "다시 분석할 결과가 없어 빠른 재분석을 건너뛰었습니다"})
                    self._persist(j)
                    continue
                j.argv = list(argv)
                self._launch(j)

    # 기록 ---------------------------------------------------------------
    def _persist(self, job: Job) -> None:
        try:
            fsx.atomic_write(self.paths.ui_job_file(job.job_id), fsx.canon_bytes(job.record()), fsync=False)
        except (OSError, ValueError):
            pass                                        # 기록 실패가 작업을 멈추지 않는다(다음 상태 변화에서 다시 쓴다)

    def _prune_memory(self) -> None:
        done = sorted((j for j in self._jobs.values() if j.state in FINISHED), key=lambda j: j.job_id)
        for j in done[: max(0, len(done) - KEEP_MEMORY)]:
            self._jobs.pop(j.job_id, None)

    def _load_recent(self) -> None:
        """지난 서버의 작업 기록(최근 20건). 끝나지 않은 채 남은 작업은 진행을 더 볼 수 없으므로 failed + lost 로 고쳐 둔다
        (그 명령은 재개 가능하다 — 다시 누르면 남은 것부터)."""
        d = self.paths.ui_jobs()
        try:
            names = sorted((n for n in os.listdir(fsx.longp(d)) if n.endswith(".json")), reverse=True)
        except OSError:
            return
        for n in names[KEEP_FILES:]:
            try:
                os.remove(fsx.longp(d / n))
            except OSError:
                pass
        for n in names[:RECENT]:
            obj = fsx.read_json(d / n, None, want=dict)
            if not isinstance(obj, dict) or obj.get("kind") not in KINDS or obj.get("state") not in STATES:
                continue
            try:
                self.paths.ui_job_file(str(obj.get("job_id")))
            except ValueError:
                continue
            lane, name = KINDS[obj["kind"]]
            j = Job(job_id=obj["job_id"], kind=obj["kind"], lane=obj.get("lane") if obj.get("lane") in LANES else lane,
                    name_ko=name, state=obj["state"], started=obj.get("started"), ended=obj.get("ended"),
                    rc=obj.get("rc") if isinstance(obj.get("rc"), int) else None, keep=self._keep,
                    result=obj.get("result") if isinstance(obj.get("result"), dict) else None,
                    seq=int(obj.get("seq") or 0) if isinstance(obj.get("seq"), int) else 0)
            j.events = [e for e in obj.get("events") or () if isinstance(e, dict)][-RECORD_EVENTS:]
            if j.state not in FINISHED:
                j.state, j.lost = "failed", True
                j.ended = j.ended or _now_iso()
                self._persist(j)
            self._jobs[j.job_id] = j


def _sys_python() -> str:
    import sys
    exe = sys.executable or "python"
    base = os.path.basename(exe).lower()
    if base == "pythonw.exe":                           # 화면 서버가 pythonw 로 떠 있어도 자식은 콘솔 파이썬(창은 없음)
        cand = os.path.join(os.path.dirname(exe), "python.exe")
        if os.path.isfile(cand):
            return cand
    return exe
