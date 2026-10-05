# -*- coding: utf-8 -*-
r"""단계 감시 — **생존**(하트비트)과 **진전**(done 증가)을 따로 본다(계약 §2.5 · §8.6 · §8.7, C §8.4).

* 생존: 자식 stdout 의 어떤 줄이든(이벤트·레코드·글) 오면 산 것이다. ``collect.watch.stallMin``(15분) 동안
  한 줄도 없으면 **정체**(stop_kind ``stall``).
* 진전: §8.6 이벤트(``{"ev": …, "done": n}``)의 ``done`` 이 그 이벤트의 ``stage`` 별로 이전 최댓값보다 커질 때만이다
  (하트비트만 뛰고 done 이 그대로면 진전이 아니다 — LM24 의 '하트비트와 진전을 섞어 오진' 결함 방지).
  ``collect.watch.noProgressMin``(45분) 동안 진전이 없으면 **무진전**(stop_kind ``no_progress``).
  수집기 → 정제 파이프 연결자처럼 자식 stdout 이 레코드 줄인 경우는 ``WatchPolicy.progress_on_lines=True`` 로
  레코드 한 줄을 진전 1로 센다(제어 줄 ``_meta``·``_cursor``·``_in`` 은 세지 않는다).
* 정체·무진전이면 ``lm27.util.proc.kill_tree(pid)`` 로 트리째 끊는다(``os.kill`` 금지). 절대 시간 상한은 없다(계약 §5.3).
* 감시 자신은 ``collect.watch.heartbeatSec``(30초)마다 ``progress`` 이벤트를 낸다 — 이 프로세스를 지켜보는 쪽
  (화면 작업·상위 감시)에 대한 생존 신호다. ``done`` 은 지금까지 본 진전 단위 누계(단조 증가).
* 취소(§8.7): ``cancel()`` 이 참이 되면 ``cancel_grace_s``(5초) 기다린 뒤에도 자식이 살아 있으면 kill_tree.
* 원문 0: 자식 줄은 ``on_line`` 콜백으로 넘기기만 하고 보관하지 않는다. 결과에는 수·열거만 남는다.

시험: 시계(`MonoClock` 대신 ``now()``·``wait(q, timeout)`` 을 가진 가상 시계), 종료 함수(``kill``), 이벤트 출력
(``emit``)을 주입한다. ``child`` 는 ``subprocess.Popen`` 호환(``pid`` · ``stdout`` · ``stderr`` · ``poll()`` · ``wait()``)이면 된다.
에이전트 bin 사본(계약 §1.3)에는 ``lm27.collect`` 가 없으므로 에이전트 감독 루프는 이 모듈을 쓰지 않는다.
"""
import json
import queue
import subprocess
import threading
import time
from dataclasses import dataclass

from lm27.collect.rcmap import RC_KILLED

EVENT_NAMES = frozenset({"stage_start", "progress", "notice", "warn", "msg", "stage_end", "run_end", "result",
                         "check"})                     # 계약 §8.6
CONTROL_PREFIXES = ('{"_meta"', '{"_cursor"', '{"_in"')  # 수집기 제어 줄(계약 §7.3) — 레코드가 아니다
STOP_STALL = "stall"
STOP_NO_PROGRESS = "no_progress"
STOP_CANCELLED = "cancelled"
KILL_REASON = "R-TRANSPORT"
REAP_TIMEOUT_S = 30.0
# 자식이 끝났는데 EOF 가 안 오면(손주가 핸들 보유) — 큐가 비고 마지막 줄 뒤로 이만큼 조용하면 끝낸다(유휴 한도).
# 절대 마감이 아니다: 이미 읽어 둔 줄은 소비자(on_line)가 느려도 끝까지 넘긴다(꼬리 유실 = 성공으로 위장된 자료 손실).
EXIT_DRAIN_S = 2.0

EOF = object()                                          # stdout 끝 표지(읽기 스레드 → 감시 루프)


@dataclass(frozen=True)
class WatchPolicy:
    """감시 한도(초). 0 이하면 그 검사를 끈다."""
    heartbeat_s: float = 30.0
    stall_s: float = 900.0
    no_progress_s: float = 2700.0
    cancel_grace_s: float = 5.0
    poll_s: float = 1.0
    stage: str = ""
    progress_on_lines: bool = False

    @classmethod
    def from_cfg(cls, cfg, *, stage="", progress_on_lines=False):
        """설정 레지스트리(``lm27.config.Cfg``)에서 한도를 읽는다 — 이 모듈이 ``collect.watch.*`` 의 읽는 곳이다."""
        return cls(heartbeat_s=float(cfg["collect.watch.heartbeatSec"]),
                   stall_s=60.0 * float(cfg["collect.watch.stallMin"]),
                   no_progress_s=60.0 * float(cfg["collect.watch.noProgressMin"]),
                   stage=stage, progress_on_lines=progress_on_lines)


@dataclass
class WatchResult:
    """감시 결과(수·열거만). ``rc`` 는 단계 결과에 쓸 값 — 감시가 끊었으면 3(+ ``reason`` R-TRANSPORT),
    아니면 자식 종료 코드. ``rcmap.stage_outcome(r.rc, reasons, {"stop_kind": r.stop_kind})`` 로 번역한다."""
    rc: int | None
    exit_code: int | None
    stop_kind: str | None
    reason: str | None
    killed: bool
    done: int
    total: int | None
    lines: int
    events: int
    heartbeats: int
    elapsed_s: float
    last_result: dict | None = None


class MonoClock:
    """실제 시계 — ``time.monotonic`` 과 큐 대기."""

    def now(self) -> float:
        return time.monotonic()

    def wait(self, q, timeout):
        """큐에서 하나 꺼낸다. ``timeout`` 초 안에 없으면 ``queue.Empty``."""
        return q.get(timeout=max(0.0, timeout))


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def parse_event(line):
    """§8.6 이벤트 줄이면 dict, 아니면 None(레코드·글·깨진 JSON)."""
    s = line.strip() if isinstance(line, str) else ""
    if not s.startswith("{") or '"ev"' not in s:
        return None
    try:
        obj = json.loads(s)
    except (ValueError, RecursionError):                # 깊게 중첩된 줄 하나로 감시자가 죽지 않게
        return None
    if isinstance(obj, dict) and isinstance(obj.get("ev"), str) and obj["ev"] in EVENT_NAMES:
        return obj
    return None


def is_record_line(line) -> bool:
    """레코드 줄인가(빈 줄·제어 줄·이벤트가 아닌 JSON 객체 줄)."""
    s = line.strip() if isinstance(line, str) else ""
    return s.startswith("{") and not s.startswith(CONTROL_PREFIXES)


class Monitor:
    """감시 판정 상태 기계 — 시각(초)만 받아 판정한다. `watch` 가 쓰고, 시험이 가상 시각으로 직접 몰 수도 있다."""

    def __init__(self, policy, now):
        self.policy = policy
        self.t0 = self.alive_at = self.prog_at = self.beat_at = now
        self.done = 0                 # 진전 단위 누계(단조 증가)
        self.total = None
        self.lines = 0
        self.events = 0
        self.last_result = None
        self._max_done = {}           # 이벤트 stage → 지금까지 본 done 최댓값

    def feed(self, line, now):
        """자식 stdout 한 줄. 어떤 줄이든 생존을 갱신하고, 진전은 done 증가로만. 이벤트면 dict 를 돌려준다."""
        self.alive_at = now
        self.lines += 1
        ev = parse_event(line)
        if ev is None:
            if self.policy.progress_on_lines and is_record_line(line):
                self._advance(1, now)
            return None
        self.events += 1
        d = ev.get("done")
        if _is_int(d) and d >= 0:
            key = ev.get("stage") if isinstance(ev.get("stage"), str) else ""
            prev = self._max_done.get(key, 0)
            if d > prev:
                self._max_done[key] = d
                self._advance(d - prev, now)
        t = ev.get("total")
        if _is_int(t) and t >= 0:
            self.total = t
        if ev["ev"] == "result":
            self.last_result = dict(ev)
        return ev

    def _advance(self, n, now):
        self.done += n
        self.prog_at = now

    def verdict(self, now):
        """끊어야 하면 ``"stall"``·``"no_progress"``(정체가 먼저), 아니면 None."""
        p = self.policy
        if p.stall_s > 0 and now - self.alive_at >= p.stall_s:
            return STOP_STALL
        if p.no_progress_s > 0 and now - self.prog_at >= p.no_progress_s:
            return STOP_NO_PROGRESS
        return None

    def beat_due(self, now) -> bool:
        p = self.policy
        return p.heartbeat_s > 0 and now - self.beat_at >= p.heartbeat_s

    def beat(self, now):
        self.beat_at = now

    def next_wake(self, now) -> float:
        """다음 판정 시각까지 남은 초(최대 ``poll_s`` — 취소·종료 확인 주기)."""
        p = self.policy
        cands = [p.poll_s if p.poll_s > 0 else 1.0]
        if p.heartbeat_s > 0:
            cands.append(self.beat_at + p.heartbeat_s - now)
        if p.stall_s > 0:
            cands.append(self.alive_at + p.stall_s - now)
        if p.no_progress_s > 0:
            cands.append(self.prog_at + p.no_progress_s - now)
        return max(0.0, min(cands))


def _decode(raw):
    if isinstance(raw, (bytes, bytearray)):
        raw = bytes(raw).decode("utf-8", "replace")
    return raw.rstrip("\r\n")


def _start_reader(stream, q):
    """stdout 을 줄 단위로 큐에 넣고 끝나면 EOF 를 넣는 데몬 스레드."""
    def run():
        try:
            if stream is not None:
                for raw in stream:
                    q.put(_decode(raw))
        except (OSError, ValueError):
            pass
        finally:
            q.put(EOF)
    threading.Thread(target=run, name="lm27-watch-stdout", daemon=True).start()


def _start_drain(stream, on_err):
    """``on_err`` 를 줬을 때만 stderr 를 읽어 넘긴다(보관하지 않는다). ``lm27.util.proc.spawn`` 의 기본 자식은
    stderr 를 이미 배수하므로 그때는 건드리지 않는다 — 같은 파이프를 두 스레드가 읽지 않게."""
    if stream is None or on_err is None:
        return

    def run():
        try:
            for raw in stream:
                on_err(_decode(raw))
        except (OSError, ValueError):
            pass
    threading.Thread(target=run, name="lm27-watch-stderr", daemon=True).start()


def _default_kill():
    from lm27.util import proc        # 지연 import — 시험은 kill 을 주입한다
    return proc.kill_tree


def _default_emit():
    from lm27.util import events      # 지연 import — 시험은 emit 을 주입한다
    return events.emit


def _reap(child):
    """끊은 뒤 종료 코드를 거둔다(최대 REAP_TIMEOUT_S). 모르면 None."""
    try:
        return child.wait(timeout=REAP_TIMEOUT_S)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def _beat_fields(policy, mon) -> dict:
    out = {"done": mon.done}
    if policy.stage:
        out["stage"] = policy.stage
    if mon.total is not None:
        out["total"] = mon.total
    return out


def watch(child, policy=None, *, clock=None, kill=None, emit=None, on_line=None, on_event=None, on_err=None,
          cancel=None) -> WatchResult:
    """계약 함수: 자식 하나를 끝날 때까지 감시한다 → `WatchResult`.

    * ``on_line(line)``: 자식 stdout 한 줄(줄바꿈 뗌) — 연결자가 정제 파이프 stdin 으로 넘길 때 쓴다.
    * ``on_event(ev)``: 그 줄이 §8.6 이벤트면 dict.
    * ``on_err(line)``: 자식 stderr 한 줄 — stderr 를 따로 배수하지 않는 자식(``spawn(stderr=PIPE)``)에만 준다.
    * ``cancel()``: 참이면 취소(``cancel_grace_s`` 뒤 kill_tree).
    * 감시 중 예외(KeyboardInterrupt·콜백 예외)가 나면 자식을 kill_tree 로 끝낸 뒤 그 예외를 그대로 올린다.
    * ``kill(pid)`` 기본 ``lm27.util.proc.kill_tree`` · ``emit(ev, **fields)`` 기본 ``lm27.util.events.emit`` ·
      ``clock`` 기본 `MonoClock`."""
    policy = policy or WatchPolicy()
    clock = clock or MonoClock()
    if kill is None:
        kill = _default_kill()
    if emit is None and policy.heartbeat_s > 0:
        emit = _default_emit()
    q = queue.Queue()
    _start_reader(getattr(child, "stdout", None), q)
    _start_drain(getattr(child, "stderr", None), on_err)

    now = clock.now()
    mon = Monitor(policy, now)
    eof = False
    exited_at = None
    last_item_at = None
    exit_code = None
    stop = None
    killed = False
    cancel_at = None
    beats = 0
    try:
        while True:
            code = child.poll()
            if code is not None:
                if eof:
                    exit_code = code
                    break
                if exited_at is None:
                    exited_at = now
                elif q.empty() and now - max(exited_at, last_item_at or exited_at) >= EXIT_DRAIN_S:
                    exit_code = code                     # 큐가 비었고 종료·마지막 줄 뒤로 조용함 — 손주가 파이프를 쥔 경우
                    break
            if cancel_at is not None:                # 취소 유예 중에는 정체·무진전 판정을 쉬므로 유예 끝까지만 기다린다
                wait = min(max(0.0, cancel_at + policy.cancel_grace_s - now), policy.poll_s if policy.poll_s > 0 else 1.0)
            else:
                wait = mon.next_wake(now)
            if exited_at is not None:
                wait = min(wait, EXIT_DRAIN_S)
            try:
                item = clock.wait(q, wait)
            except queue.Empty:
                item = None
            now = clock.now()
            if item is EOF:
                eof = True
            elif item is not None:
                last_item_at = now
                ev = mon.feed(item, now)
                if on_line is not None:
                    on_line(item)
                if ev is not None and on_event is not None:
                    on_event(ev)
            if mon.beat_due(now):
                mon.beat(now)
                beats += 1
                if emit is not None:
                    emit("progress", **_beat_fields(policy, mon))
            if cancel_at is None and cancel is not None and cancel():
                cancel_at = now
                stop = STOP_CANCELLED
            if cancel_at is not None:
                if now - cancel_at >= policy.cancel_grace_s and child.poll() is None:
                    kill(child.pid)
                    killed = True
                    break
                continue
            v = mon.verdict(now)
            if v is not None:
                stop = v
                kill(child.pid)
                killed = True
                break
    except BaseException:                        # 감시자가 멈추면(취소 키·연결자 콜백 예외) 자식을 고아로 남기지 않는다
        if child.poll() is None:
            kill(child.pid)
        raise
    if killed:
        exit_code = _reap(child)
    return WatchResult(rc=RC_KILLED if killed else exit_code, exit_code=exit_code, stop_kind=stop,
                       reason=KILL_REASON if killed else None, killed=killed, done=mon.done, total=mon.total,
                       lines=mon.lines, events=mon.events, heartbeats=beats, elapsed_s=now - mon.t0,
                       last_result=mon.last_result)
