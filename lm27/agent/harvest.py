# -*- coding: utf-8 -*-
r"""수확 자식·수집기 연결자(계약 §2.4 · §7.3 · §8.2 · X-300 · X-303 · TAB §1.6.1 · §1.7 ②) — 에이전트 쪽 '연결자'.

연결자 = PS 수집기와 정제 파이프를 둘 다 띄우고 잇는 쪽(계약 §7.3). 한 흐름(경로 ID)마다:
  1. 수집기 stdin 에 제어 줄 한 줄 ``{"_in": {"cursor": <raw_cursor[src]>, "cfg": {<그 스크립트가 쓰는 §5.2 키>}, "self_names": [..]}}``
     을 쓰고 닫는다(커서·설정·이름을 명령줄에 싣지 않는다). 설정 값 = ``agent_config.json``(X-303), 정제 문맥 값
     (``privacy.path.excludeKeywords``·``episode.finalWords``)·본인 표시명 = ``context_cache.json``(X-306).
  2. 수집기 stdout(NDJSON + 마지막 ``_cursor``)을 정제 파이프 ``lm27_pipe.py --kind <kind> --src <src> --pc <pc_id> --mode append``
     stdin 으로 그대로 넘긴다(원문은 파이프에만 — 디스크 0). 파이프가 출력 기록 성공(0·2) 뒤에만 커서를 저장한다.
  3. 수집기가 상한(예산 + 기동 여유)을 넘기면 ``kill_tree``(→ R-TRANSPORT), 수집기 EOF 뒤 파이프가 ``privacy.pipe.waitSec`` 안에
     끝나지 않으면 ``kill_tree`` 하고 코드 99(계약 §8.2).
  4. 결과 = 수집기 rc · 파이프 종료 코드 · 요약 줄 · 수집기 상태 줄(stderr 마지막 ``{"_status": …}`` — C1, 모르는 필드 무시) —
     숫자·열거·사유 코드만(``ConnResult``).

수확(TAB §1.6.1): 감독 루프가 로그온 직후·``agent.harvestIntervalH`` 마다·``run\harvest_now.flag`` 때 **자식 프로세스**로
``agent_main.py --harvest <흐름>`` 을 띄운다(``start_harvest_child``). 자식은 ``run\.harvest.lock`` 을 쥐고(중복 방지) 흐름을
차례로 돌린 뒤 ``run\harvest_done.json``(``lm27.harvest_done/1`` — 흐름별 rc·파이프 코드·사유·저장 건수, 원문 없음)을 원자 기록한다.
전경 [수집]은 ``lm27.agent.install.request_harvest_now`` 로 깃발을 놓고 이 파일을 기다린다(TAB §1.7 ②).

이 모듈은 에이전트 bin 사본에 들어간다(표준 라이브러리 + 사본 안 ``lm27.store``·``lm27.util``·``lm27.privacy``·``lm27.paths``).
"""
from __future__ import annotations

import os
import subprocess
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta

from lm27.store import LockTimeout, file_lock, load_raw_cursor
from lm27.util import fsx, proc

__all__ = [
    "COLLECTORS", "HARVEST_DONE_SCHEMA", "HARVEST_SRCS", "HARVEST_STREAMS", "POLL", "Collector", "ConnResult", "Runtime",
    "harvest_window", "in_line", "load_settings", "parse_status", "parse_summary", "powershell_exe", "run_connector",
    "run_harvest", "runtime_for", "start_harvest_child", "window_args",
]

HARVEST_STREAMS = ("pc_session/pc.events", "pc_file/pc.files", "pc_file/pc.mru", "pc_file/pc.recent")
HARVEST_DONE_SCHEMA = "lm27.harvest_done/1"
AGENTCFG_SCHEMA = "lm27.agentcfg/1"
PS_SLACK_S = 30                 # PS 기동·Add-Type 컴파일 여유(WP-16 요청 — 예산 + 여유 뒤에 끊는다)
EVENTS_MAX_S = 60               # 이벤트 수확 한 번(계약 §5.3)
OOXML_TOTAL_S = 90              # 파일 수집기 OOXML 작성자 읽기 전체 예산(계약 §5.3)
SCAN_MAX_S = 120                # MRU·Recent·열린 문서 폴링 한 번
FWD_CHUNK = 65536
TAIL_LINES = 200
PIPE_FAIL = {3: "R-TRANSPORT", 5: "R-TRANSPORT", 6: "R-NOKEY", 99: "R-TRANSPORT"}   # 계약 §8.2


@dataclass(frozen=True)
class Collector:
    """수집기 한 흐름. ``cfg`` = ``_in.cfg`` 로 넘길 agent_config 키, ``ctx`` = (설정 키, context_cache 칸) — 정제 문맥 값,
    ``need`` = 없으면 그 흐름을 돌리지 않는 키(빠지면 수집기가 '모든 확장자' 등 다른 뜻으로 돈다)."""
    src: str
    kind: str
    script: str
    cfg: tuple
    ctx: tuple = ()
    self_names: bool = False
    args: tuple = ()
    need: tuple = ()


_FILE_KEYS = ("pc.watchExtensions", "pc.excludeFolderNames", "pc.excludePackageDirs", "collect.lookbackDays")
COLLECTORS = {
    "pc.events": Collector("pc.events", "pc_session", "Get-EventActivity.ps1", ("collect.lookbackDays",)),
    "pc.files": Collector("pc.files", "pc_file", "Get-FileActivity.ps1",
                          ("pc.watchFolders", "pc.autoDiscoverFolders", "pc.files.burstN", "pc.files.budgetSec") + _FILE_KEYS,
                          (("privacy.path.excludeKeywords", "path_exclude"), ("episode.finalWords", "final_words")),
                          need=("pc.watchExtensions",)),
    "pc.mru": Collector("pc.mru", "pc_file", "Get-OfficeMru.ps1", ("pc.mru.officeVersions", "pc.mru.jumpList") + _FILE_KEYS,
                        (("episode.finalWords", "final_words"),), need=("pc.watchExtensions",)),
    "pc.recent": Collector("pc.recent", "pc_file", "Get-RecentFiles.ps1", _FILE_KEYS,
                           (("episode.finalWords", "final_words"),), need=("pc.watchExtensions",)),
    "teams.uia": Collector("teams.uia", "teams", "Get-TeamsWindow.ps1",
                           ("teams.timeRegex", "teams.uia.visibleOnly", "teams.uia.maxElements",
                            "teams.uia.windowWatchdogSec", "teams.uia.budgetSec"), self_names=True),
}
# 열린 문서 저장 폴링(CP §5.2 — agent.filePoll.intervalSec 마다 Get-FileActivity.ps1 -Poll, 커서는 pc.files 와 같은 칸)
POLL = Collector("pc.files", "pc_file", "Get-FileActivity.ps1", ("agent.filePoll.topN", "pc.watchFolders") + _FILE_KEYS,
                 (("privacy.path.excludeKeywords", "path_exclude"), ("episode.finalWords", "final_words")),
                 args=("-Poll",), need=("pc.watchExtensions",))


def _utc(now=None) -> str:
    n = now or datetime.now(UTC)
    return n.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# ───────────────────────────── 설정·문맥 ─────────────────────────────
def load_settings(paths) -> dict:
    """``agent_config.json``(``lm27.agentcfg/1``) → 설정 키·값 사전(메타 칸 제외). 없거나 깨졌으면 빈 사전."""
    obj = fsx.read_json(paths.agent_config(), default={})
    if not isinstance(obj, dict) or obj.get("schema") not in (None, AGENTCFG_SCHEMA):
        return {}
    return {k: v for k, v in obj.items() if isinstance(k, str) and "." in k}


def load_ctxcache(paths) -> dict:
    """``context_cache.json``(해시 확인) — 없거나 맞지 않으면 빈 사전."""
    from lm27.privacy.context import read_context_cache        # 지연 import(사본 안 모듈)
    return read_context_cache(paths.agent_dir()) or {}


def in_line(spec: Collector, settings: dict, ctxcache: dict, cursor) -> dict | None:
    """수집기 stdin 제어 줄 ``{"_in": {...}}``(계약 §7.3). 필요한 키(``spec.need``)가 설정에 없으면 None(그 흐름을 건너뛴다)."""
    if any(k not in settings for k in spec.need):
        return None
    cfg = {k: settings[k] for k in spec.cfg if k in settings}
    for key, slot in spec.ctx:
        v = (ctxcache or {}).get(slot)
        if isinstance(v, list):
            cfg[key] = list(v)
    body = {"cursor": cursor, "cfg": dict(sorted(cfg.items()))}
    if spec.self_names:
        names = (ctxcache or {}).get("self_names")
        body["self_names"] = [n for n in names if isinstance(n, str)] if isinstance(names, list) else []
    return {"_in": body}


def collector_timeout(spec: Collector, settings: dict) -> float:
    """수집기를 끊는 시각(초) = 그 수집기 예산 + PS 기동 여유."""
    if spec.src == "teams.uia":
        return _int(settings.get("teams.uia.budgetSec"), 60, 5, 300) + PS_SLACK_S
    if spec.src == "pc.events":
        return EVENTS_MAX_S + PS_SLACK_S
    if spec.src == "pc.files" and "-Poll" not in spec.args:
        return _int(settings.get("pc.files.budgetSec"), 180, 10, 3600) + OOXML_TOTAL_S + PS_SLACK_S
    return SCAN_MAX_S + PS_SLACK_S


def pipe_wait(settings: dict) -> float:
    """``privacy.pipe.waitSec``(30~1800, 기본 120)."""
    return float(_int(settings.get("privacy.pipe.waitSec"), 120, 30, 1800))


HARVEST_SRCS = frozenset(s.partition("/")[2] for s in HARVEST_STREAMS)


def harvest_window(settings: dict, now=None) -> tuple:
    """수확 창 ``(since, until)``(로컬 날짜 ``YYYY-MM-DD``, 근무 시간대 ``time.tzOffsetMin``) — 전경 수집의
    ``lm27.collect.ledger.default_since`` 와 같은 셈(에이전트 사본에는 ``lm27.collect`` 가 없어 여기서 다시 센다 — 계약
    v1.3 §0.8 V6): 오늘 − ``collect.lookbackDays`` + 1 과 (``collect.sinceYearStart`` 가 켜져 있거나 없으면) 올해 1월 1일
    중 이른 날 ~ 오늘. PS 수집기는 이 창을 ``-Since``·``-Until`` 로 받고 커서 ``read_from`` 으로 앞쪽 공백을 다시 낸다."""
    lb = _int(settings.get("collect.lookbackDays"), 120, 1, 1825)
    off = _int(settings.get("time.tzOffsetMin"), 540, -720, 840)
    n = now if isinstance(now, datetime) else datetime.now(UTC)
    if n.tzinfo is None:
        n = n.replace(tzinfo=UTC)
    today = (n.astimezone(UTC) + timedelta(minutes=off)).date()
    d0 = today - timedelta(days=lb - 1)
    if settings.get("collect.sinceYearStart", True) is not False:
        d0 = min(d0, date(today.year, 1, 1))
    return d0.isoformat(), today.isoformat()


def window_args(spec: Collector, settings: dict, now=None, extra_args=()) -> tuple:
    """수확 흐름(폴링 제외) 수집기에 늘 넘기는 ``-Since <d0> -Until <d1>``. 시험 주입 인자에 이미 있으면 그대로(두 번 넘기지 않음)."""
    if spec.src not in HARVEST_SRCS or "-Poll" in spec.args or "-Since" in tuple(str(a) for a in extra_args):
        return ()
    d0, d1 = harvest_window(settings, now)
    return ("-Since", d0, "-Until", d1)


def _int(v, default: int, lo: int, hi: int) -> int:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return default
    return int(min(hi, max(lo, v)))


# ───────────────────────────── 실행 환경 ─────────────────────────────
def powershell_exe() -> str:
    """Windows PowerShell 5.1 절대 경로(PATH 에 흔들리지 않게 — 시스템 경로이지 데이터 경로가 아니다)."""
    sysroot = os.environ.get("SystemRoot") or os.environ.get("windir") or "C:\\Windows"
    return os.path.join(sysroot, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")


@dataclass(frozen=True)
class Runtime:
    """연결자가 띄우는 프로그램 위치. 기본 = ``Paths`` 의 동봉 파이썬·파이프(에이전트 사본이면 ``py311``·사본 파이프).
    명령줄은 ``collector_argv``·``pipe_argv`` 두 곳에서만 만든다(시험은 이 둘을 바꾼 하위 클래스로 가짜 수집기를 넣는다)."""
    paths: object
    python: str
    pipe: str
    powershell: str
    cwd: str
    env: dict | None = None

    def script(self, name: str) -> str:
        return str(self.paths.collect_script(name))

    def collector_argv(self, spec: Collector, pc_id: str, extra_args=()) -> list:
        return [self.powershell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
                self.script(spec.script), "-Pc", pc_id, *spec.args, *(str(a) for a in extra_args)]

    def pipe_argv(self, spec: Collector, pc_id: str) -> list:
        return [self.python, "-X", "utf8", "-I", "-B", self.pipe, "--kind", spec.kind, "--src", spec.src, "--pc", pc_id,
                "--mode", "append"]


def runtime_for(paths, *, python=None, env=None, cwd=None) -> Runtime:
    c = cwd or str(paths.agent_dir())
    if not os.path.isdir(c):
        c = None
    return Runtime(paths=paths, python=str(python or paths.python_exe()), pipe=str(paths.pipe_script()),
                   powershell=powershell_exe(), cwd=c or os.getcwd(), env=env)


# ───────────────────────────── 출력 해석 ─────────────────────────────
def _json_lines(text: str):
    for ln in reversed((text or "").splitlines()):
        s = ln.strip().lstrip("\ufeff")
        if s.startswith("{") and s.endswith("}"):
            try:
                obj = fsx.loads_strict(s)
            except ValueError:
                continue
            if isinstance(obj, dict):
                yield obj


def parse_status(stderr_text: str) -> dict | None:
    """수집기 stderr 의 마지막 ``{"_status": {...}}``(C1 — 경로마다 한 줄). 없으면 None."""
    for obj in _json_lines(stderr_text):
        st = obj.get("_status") if len(obj) == 1 else None
        if isinstance(st, dict):
            return st
    return None


def parse_summary(stdout_text: str) -> dict | None:
    """정제 파이프 stdout 의 요약 줄(마지막 JSON 한 줄 — P §3.5 형). 없으면 None."""
    for obj in _json_lines(stdout_text):
        if "rows_in" in obj or "ok" in obj:
            return obj
    return None


@dataclass
class ConnResult:
    """연결자 한 번의 결과(숫자·열거·사유 코드만)."""
    src: str
    kind: str
    rc: int | None = None              # 수집기 종료 코드(끊었으면 None)
    pipe: int | None = None            # 정제 파이프 종료 코드(99 = 대기 초과로 끊음)
    stored: int = 0
    cursor_saved: bool = False
    timed_out: bool = False
    skipped: str = ""                  # 돌지 않은 까닭(설정 없음 등 — 사유 코드 아님)
    reasons: list = field(default_factory=list)
    status: dict | None = None
    elapsed_s: float = 0.0

    def as_dict(self) -> dict:
        d = asdict(self)
        d["elapsed_s"] = round(self.elapsed_s, 1)
        st = d.pop("status")
        if isinstance(st, dict):
            d["status"] = {k: v for k, v in st.items() if isinstance(v, (int, float, bool, str, list, dict)) or v is None}
        return d


def _reader(stream, sink: list, tail: int | None = None):
    def run():
        try:
            for raw in iter(stream.readline, b""):
                sink.append(raw)
                if tail and len(sink) > tail:
                    del sink[:len(sink) - tail]
        except (OSError, ValueError):
            pass
    t = threading.Thread(target=run, name="lm27-agent-read", daemon=True)
    t.start()
    return t


def _forward(src_stream, dst_stream, state: dict):
    """수집기 stdout → 파이프 stdin(바이트 그대로). 파이프가 먼저 죽으면(깨진 파이프) 넘기기는 멈추고 수집기 출력은 버린다."""
    def run():
        broken = False
        try:
            while True:
                b = src_stream.read1(FWD_CHUNK) if hasattr(src_stream, "read1") else src_stream.read(FWD_CHUNK)
                if not b:
                    break
                if broken:
                    continue
                try:
                    dst_stream.write(b)
                    state["bytes"] = state.get("bytes", 0) + len(b)
                except (OSError, ValueError):
                    broken = True
                    state["broken"] = True
        except (OSError, ValueError):
            pass
        finally:
            try:
                dst_stream.close()
            except (OSError, ValueError):
                state["broken"] = True
    t = threading.Thread(target=run, name="lm27-agent-forward", daemon=True)
    t.start()
    return t


def _wait(child, limit_s: float, abort, clock) -> bool:
    """자식이 끝날 때까지(최대 limit_s). 끝났으면 True. ``abort`` 이벤트가 서면 False."""
    end = clock() + max(0.0, limit_s)
    while True:
        try:
            child.wait(timeout=0.25)
            return True
        except subprocess.TimeoutExpired:
            pass
        if (abort is not None and abort.is_set()) or clock() >= end:
            return False


def _kill(child) -> None:
    try:
        child.kill_tree()
    except (OSError, ValueError):
        pass


def run_connector(paths, pc_id: str, src: str, *, settings: dict | None = None, ctxcache: dict | None = None,
                  poll: bool = False, rt: Runtime | None = None, extra_args=(), abort=None, clock=time.monotonic,
                  spawn=proc.spawn, collector_timeout_s: float | None = None,
                  pipe_wait_s: float | None = None, now=None) -> ConnResult:
    """수집기 하나 → 정제 파이프(계약 §7.3). ``extra_args`` = 시험 주입 인자(계약 §11.3 — ``-EventsCsv`` 등).
    ``collector_timeout_s``·``pipe_wait_s`` = 시험용 상한(없으면 설정·예산에서). 수확 흐름은 창(``window_args`` —
    ``now`` 기준, 없으면 지금)을 늘 넘긴다(v1.3 §0.8 V6 — 수집기 상태 줄 ``range`` 가 원장 관측 창이 된다)."""
    spec = POLL if poll else COLLECTORS[src]
    st = settings if settings is not None else load_settings(paths)
    cc = ctxcache if ctxcache is not None else load_ctxcache(paths)
    res = ConnResult(src=spec.src, kind=spec.kind)
    t0 = clock()
    cursor = load_raw_cursor(paths, pc_id).get(spec.src)
    line = in_line(spec, st, cc, cursor)
    if line is None:
        res.skipped = "settings_missing"
        return res
    r = rt or runtime_for(paths)
    col_argv = r.collector_argv(spec, pc_id, (*window_args(spec, st, now, extra_args), *extra_args))
    pipe_argv = r.pipe_argv(spec, pc_id)
    try:
        pipe = spawn(pipe_argv, stdin=proc.PIPE, stdout=proc.PIPE, stderr=proc.PIPE, env=r.env, cwd=r.cwd)
    except OSError as e:
        res.skipped, res.reasons = "spawn_" + type(e).__name__, ["R-TRANSPORT"]
        return res
    try:
        col = spawn(col_argv, stdin=proc.PIPE, stdout=proc.PIPE, stderr=proc.PIPE, env=r.env, cwd=r.cwd)
    except OSError as e:
        _kill(pipe)
        res.skipped, res.reasons = "spawn_" + type(e).__name__, ["R-TRANSPORT"]
        return res
    col_err, pipe_out, pipe_err, state = [], [], [], {}
    readers = [_reader(col.stderr, col_err, TAIL_LINES), _reader(pipe.stdout, pipe_out), _reader(pipe.stderr, pipe_err,
                                                                                                    TAIL_LINES)]
    try:
        col.stdin.write(fsx.canon_bytes(line) + b"\n")
        col.stdin.close()
    except (OSError, ValueError):
        pass
    fwd = _forward(col.stdout, pipe.stdin, state)
    limit = collector_timeout_s if collector_timeout_s is not None else collector_timeout(spec, st)
    if _wait(col, limit, abort, clock):
        res.rc = col.returncode
    else:
        _kill(col)
        res.timed_out = True
    fwd.join(10)
    if fwd.is_alive():                                # 손주가 stdout 을 쥐고 있으면 파이프 입력을 여기서 닫는다
        try:
            pipe.stdin.close()
        except (OSError, ValueError):
            pass
    if _wait(pipe, pipe_wait_s if pipe_wait_s is not None else pipe_wait(st), abort, clock):
        res.pipe = pipe.returncode
    else:
        _kill(pipe)
        res.pipe = 99
    for t in readers:
        t.join(5)
    res.status = parse_status(b"".join(col_err).decode("utf-8", errors="replace"))
    sm = parse_summary(b"".join(pipe_out).decode("utf-8", errors="replace"))
    if res.status is None and isinstance(sm, dict) and isinstance(sm.get("collector_status"), dict):
        res.status = sm["collector_status"]          # CLM 모드: 상태 줄이 stdout 제어 줄로 와 파이프 요약에 실린다(C1)
    if isinstance(sm, dict):
        res.stored = sm["stored"] if isinstance(sm.get("stored"), int) and not isinstance(sm["stored"], bool) else 0
        res.cursor_saved = sm.get("cursor_saved") is True
    reasons = []
    if isinstance(res.status, dict):
        reasons += [x for x in res.status.get("reasons") or () if isinstance(x, str) and x.startswith("R-")]
    if res.timed_out:
        reasons.append("R-TRANSPORT")
    if res.pipe in PIPE_FAIL:
        reasons.append(PIPE_FAIL[res.pipe])
    res.reasons = sorted(set(reasons))
    res.elapsed_s = clock() - t0
    for ch in (col, pipe):
        try:
            ch.close()
        except (OSError, ValueError):
            pass
    return res


# ───────────────────────────── 수확 ─────────────────────────────
def _streams(streams) -> list:
    out = []
    for s in streams:
        kind, _, src = str(s).partition("/")
        spec = COLLECTORS.get(src)
        if spec is None or spec.kind != kind:
            raise ValueError("수확 흐름 형식이 아닙니다")
        out.append(spec)
    return out


def run_harvest(paths, install_id: str, pc_id: str, streams=HARVEST_STREAMS, *, requested: bool = False,
                rt: Runtime | None = None, settings: dict | None = None, ctxcache: dict | None = None, extra_args=None,
                now=None, clock=time.monotonic) -> dict:
    """수확 한 번(자식 프로세스 본체): ``.harvest.lock`` 을 쥐고 흐름을 차례로 돌린 뒤 ``harvest_done.json`` 을 원자 기록한다.
    잠금을 못 잡으면(이미 수확 중) ``{"rc": 4, "busy": True}`` — 파일은 쓰지 않는다. ``extra_args`` = {src: [시험 주입 인자]},
    ``now`` = 지금 UTC 를 돌려주는 함수(시험 주입)."""
    specs = _streams(streams)
    st = settings if settings is not None else load_settings(paths)
    cc = ctxcache if ctxcache is not None else load_ctxcache(paths)
    tick = now or (lambda: datetime.now(UTC))
    try:
        with file_lock(paths.harvest_lock(), 0):
            t_start = tick()
            started = _utc(t_start)
            out = {}
            for spec in specs:
                r = run_connector(paths, pc_id, spec.src, settings=st, ctxcache=cc, rt=rt,
                                  extra_args=(extra_args or {}).get(spec.src, ()), clock=clock, now=t_start)
                out[spec.src] = r.as_dict()
            bad = [v for v in out.values() if v["skipped"] or v["timed_out"] or v["pipe"] not in (0, 2)
                   or v["rc"] not in (0, 1, 4)]
            done = {"schema": HARVEST_DONE_SCHEMA, "install_id": install_id, "pc_id": pc_id, "requested": bool(requested),
                    "started_at": started, "finished_at": _utc(tick()), "rc": 3 if bad else 0, "streams": out}
            fsx.atomic_write(paths.harvest_done(), fsx.canon_bytes(done) + b"\n")
            return done
    except LockTimeout:
        return {"rc": 4, "busy": True}


def start_harvest_child(ident, streams=HARVEST_STREAMS, *, paths=None, impl: str = "py", requested: bool = False,
                        spawn=proc.spawn):
    """수확 자식을 띄우고 기다리지 않는다(창 없음). py = 사본 ``agent_main.py --harvest``, ps = ``ps\\harvest.ps1``.
    ``ident`` = ``install_id``·``pc_id`` 를 가진 객체(PcIdentity 등)."""
    if paths is None:
        from lm27.agent.main import bin_paths                   # 지연 import(사본 안 모듈)
        paths = bin_paths()
    _streams(streams)
    joined = ",".join(streams)
    cwd = str(paths.agent_dir()) if os.path.isdir(paths.agent_dir()) else None
    if impl == "ps":
        argv = [powershell_exe(), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden",
                "-File", str(paths.collect_script("agent/harvest.ps1")), "-InstallId", ident.install_id, "-Streams", joined]
    else:
        argv = [str(paths.python_exe()), "-X", "utf8", "-I", "-B", str(paths.agent_main_script()), "--install-id",
                ident.install_id, "--harvest", joined]
        if requested:
            argv.append("--requested")
    if impl == "ps" and requested:
        argv.append("-Requested")
    return spawn(argv, stdin=proc.DEVNULL, stdout=proc.DEVNULL, stderr=proc.DEVNULL, cwd=cwd)
