# -*- coding: utf-8 -*-
r"""표준 출력 이벤트(계약 §8.6) — 한 줄 JSON ``{seq, ts, ev, stage?, text_ko?, done?, total?, …}``.

  · ``ev`` ∈ ``stage_start`` ``progress`` ``notice`` ``warn`` ``msg`` ``stage_end`` ``run_end`` ``result`` ``check``.
  · 출력 방식(``configure``):
      ``jsonl`` — stdout 에 한 줄 JSON(화면이 띄운 하위 명령 ``--events jsonl``). ``seq`` 는 프로세스 안에서 1부터 단조 증가.
      ``text``  — 사람용 한 줄을 stderr 로(기본, 계약 §8.6 '사람용 요약은 stderr'). stdout 에는 아무것도 쓰지 않는다.
      ``off``   — 아무것도 쓰지 않는다(시험·라이브러리 호출).
  · 장기 하위 명령은 **30초마다 ``progress``** 를 낸다(생존). ``done`` 증가가 진전이다(감시 lm27.collect.watch 가 구분).
    ``Heartbeat`` 가 그 일을 한다 — 가상 시계(``clock=``)를 넣으면 ``tick()`` 으로 시험한다.
  · ``text_ko`` 에는 명세 사용자 문구 표(B §13 BR-*, R §5.8)의 문장만 쓴다. 원문·경로를 넣지 않는다(호출자 책임).

이 모듈은 에이전트 bin 사본(계약 §1.3)에도 들어가므로 표준 라이브러리만 쓴다.
"""
import json
import sys
import threading
import time
from datetime import UTC, datetime

EVENTS = ("stage_start", "progress", "notice", "warn", "msg", "stage_end", "run_end", "result", "check")
MODES = ("text", "jsonl", "off")
HEARTBEAT_SEC = 30
_RESERVED = ("seq", "ts", "ev")

_lock = threading.RLock()
_state = {"mode": "text", "job": None, "stream": None, "err_stream": None, "now": None, "seq": 0}


def configure(mode="text", *, job=None, stream=None, err_stream=None, now=None, reset_seq=False) -> None:
    """출력 방식을 정한다. ``stream``/``err_stream`` 을 주지 않으면 쓸 때마다 ``sys.stdout``/``sys.stderr`` 를 본다.
    ``now`` = 시각 주입(시험): aware datetime 또는 'YYYY-MM-DDTHH:MM:SSZ' 문자열을 돌려주는 호출 가능 객체."""
    if mode not in MODES:
        raise ValueError(f"events.configure: mode 는 {MODES} 중 하나")
    with _lock:
        _state.update(mode=mode, job=job, stream=stream, err_stream=err_stream, now=now)
        if reset_seq:
            _state["seq"] = 0


def mode() -> str:
    return _state["mode"]


def job_id():
    """화면 작업 id(``--job``) — 없으면 None."""
    return _state["job"]


def last_seq() -> int:
    return _state["seq"]


def _ts() -> str:
    fn = _state["now"]
    if fn is None:
        return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    v = fn()
    if isinstance(v, datetime):
        return v.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(v)


def _human(rec: dict):
    """text 모드의 사람용 한 줄(없으면 None)."""
    ev = rec["ev"]
    txt = rec.get("text_ko")
    stage = rec.get("stage") or ""
    if ev == "warn":
        return "[경고] " + (txt or stage or "경고")
    if txt:
        return txt
    if ev == "stage_start" and stage:
        return f"[시작] {stage}"
    if ev == "stage_end" and stage:
        st = rec.get("state")
        return f"[끝] {stage}" + (f" ({st})" if st else "")
    if ev == "progress":
        done, total = rec.get("done"), rec.get("total")
        cnt = f" {done}/{total}" if total is not None else (f" {done}" if done is not None else "")
        return f"  ... {stage or '작업'} 진행 중{cnt}"
    return None


def _write(stream, line: str) -> None:
    if stream is None:
        return
    try:
        stream.write(line + "\n")
        stream.flush()
    except (OSError, ValueError):
        pass                    # 받는 쪽 파이프가 닫힘 — 이벤트 때문에 본 작업을 죽이지 않는다


def emit(ev: str, /, **fields) -> dict:
    """이벤트 1건을 내고 그 기록(dict)을 돌려준다. 값이 None 인 필드는 뺀다.
    알 수 없는 ``ev``·예약 필드(seq·ts·ev) 덮어쓰기는 ValueError, JSON 으로 못 바꾸는 값은 TypeError."""
    if ev not in EVENTS:
        raise ValueError(f"events.emit: 알 수 없는 ev {ev!r}")
    bad = [k for k in fields if k in _RESERVED]
    if bad:
        raise ValueError(f"events.emit: 예약 필드 {bad}")
    with _lock:
        _state["seq"] += 1
        rec = {"seq": _state["seq"], "ts": _ts(), "ev": ev}
        for k in sorted(fields):
            if fields[k] is not None:
                rec[k] = fields[k]
        m = _state["mode"]
        if m == "jsonl":
            line = json.dumps(rec, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
            _write(_state["stream"] or sys.stdout, line)
        elif m == "text":
            h = _human(rec)
            if h:
                _write(_state["err_stream"] or sys.stderr, h)
    return rec


class Heartbeat:
    """``interval_s``(기본 30초)마다 ``progress`` 이벤트를 낸다 — 생존 신호.
    ``update(done=…)`` 로 진전을 알린다(감시는 ``done`` 증가만 진전으로 본다).

    · 가상 시계: ``Heartbeat(30, clock=fake)`` 후 ``tick()`` 을 직접 부른다(간격이 지났을 때만 낸다).
    · 실제 사용: ``with Heartbeat(30, stage="analyze") as hb: … hb.update(done=n)`` — 배경 스레드가 ``tick()`` 한다.
    """

    def __init__(self, interval_s=HEARTBEAT_SEC, *, stage=None, total=None, clock=None):
        if interval_s is None or interval_s <= 0:
            raise ValueError("Heartbeat: interval_s 는 양수")
        self.interval_s = float(interval_s)
        self.stage = stage
        self.done = 0
        self.total = total
        self.extra = {}
        self.count = 0
        self._clock = clock or time.monotonic
        self._last = self._clock()
        self._lk = threading.Lock()
        self._stop = threading.Event()
        self._thread = None

    def update(self, done=None, total=None, **extra) -> None:
        with self._lk:
            if done is not None:
                self.done = done
            if total is not None:
                self.total = total
            self.extra.update(extra)

    def beat(self) -> dict:
        """지금 바로 progress 1건(간격과 무관)."""
        with self._lk:
            fields = dict(self.extra)
            fields.update(stage=self.stage, done=self.done, total=self.total)
            self._last = self._clock()
            self.count += 1
        return emit("progress", **fields)

    def tick(self) -> bool:
        """간격이 지났으면 progress 를 내고 True."""
        if self._clock() - self._last >= self.interval_s:
            self.beat()
            return True
        return False

    def _loop(self):
        step = min(1.0, self.interval_s)
        while not self._stop.wait(step):
            self.tick()

    def start(self) -> "Heartbeat":
        if self._thread is None:
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, name="lm27-heartbeat", daemon=True)
            self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        t, self._thread = self._thread, None
        if t is not None:
            t.join(timeout=5)

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()
        return False
