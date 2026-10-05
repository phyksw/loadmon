# -*- coding: utf-8 -*-
"""WP-03 watch — 생존(하트비트)과 진전(done 증가) 분리 감시(계약 §2.5·§8.6·§8.7, C §8.4).

가상 시계: 감시 루프의 ``clock.wait(q, timeout)`` 이 각본(시각, 줄)을 큐 대신 내주며 시각을 앞으로 민다 —
45분짜리 시나리오도 실제로는 수 밀리초에 끝난다. 실제 프로세스 시험은 짧은 한도(초 단위)로 두 개만 돈다.
"""
import json
import queue
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path

from lm27.collect import rcmap
from lm27.collect import watch as w

ROOT = Path(__file__).resolve().parents[2]
PID = 4242


class _Exit:
    def __init__(self, rc):
        self.rc = rc


class _BlockingStream:
    """읽기 스레드가 붙잡혀 있게 하는 stdout — 시험 끝에 풀어 준다(줄은 가상 시계가 직접 내준다)."""

    def __init__(self):
        self._ev = threading.Event()

    def __iter__(self):
        self._ev.wait(10)
        return iter(())

    def release(self):
        self._ev.set()


class FakeChild:
    def __init__(self, pid=PID):
        self.pid = pid
        self.stdout = _BlockingStream()
        self.stderr = None
        self._rc = None

    def poll(self):
        return self._rc

    def wait(self, timeout=None):
        return self._rc

    def finish(self, rc):
        if self._rc is None:
            self._rc = rc


class VClock:
    """가상 시계 + 각본. 각본 항목: (시각, 줄 문자열 | w.EOF | _Exit(rc))."""

    def __init__(self, child, script):
        self.t = 0.0
        self.child = child
        self.script = sorted(script, key=lambda x: x[0])
        self.i = 0
        self.calls = 0

    def now(self):
        return self.t

    def wait(self, q, timeout):
        self.calls += 1
        if self.calls > 500000:
            raise AssertionError("감시 루프가 멈추지 않습니다")
        try:
            return q.get_nowait()
        except queue.Empty:
            pass
        assert timeout >= 0, timeout
        deadline = self.t + timeout
        while self.i < len(self.script) and self.script[self.i][0] <= deadline:
            t, item = self.script[self.i]
            self.i += 1
            self.t = max(self.t, t)
            if isinstance(item, _Exit):
                self.child.finish(item.rc)
                continue
            return item
        self.t = deadline
        raise queue.Empty


def ev(name="progress", **f):
    return json.dumps(dict(f, ev=name), ensure_ascii=False, sort_keys=True)


class Rig:
    """가짜 자식 + 가상 시계 + kill·emit 기록."""

    def __init__(self, script, **policy):
        self.child = FakeChild()
        self.clock = VClock(self.child, script)
        self.kills = []
        self.beats = []
        self.lines = []
        self.events = []
        p = {"stage": "mail_local"}
        p.update(policy)
        self.policy = w.WatchPolicy(**p)

    def kill(self, pid):
        self.kills.append((self.clock.now(), pid))
        self.child.finish(1)                      # taskkill /F 뒤의 종료 코드

    def emit(self, name, **fields):
        self.beats.append((self.clock.now(), name, fields))

    def run(self, **kw):
        try:
            return w.watch(self.child, self.policy, clock=self.clock, kill=self.kill, emit=self.emit,
                           on_line=self.lines.append, on_event=self.events.append, **kw)
        finally:
            self.child.stdout.release()


def periodic(every, until, make, start=None):
    t = every if start is None else start
    out = []
    while t <= until:
        out.append((t, make(t)))
        t += every
    return out


def finish_at(t, rc=0):
    return [(t, _Exit(rc)), (t, w.EOF)]


class Heartbeat(unittest.TestCase):
    def test_30s_progress_events_on_virtual_clock(self):
        script = periodic(60, 600, lambda t: ev(done=int(t // 60), total=10)) + finish_at(600)
        rig = Rig(script)
        r = rig.run()
        times = [t for t, name, _ in rig.beats]
        self.assertTrue(all(name == "progress" for _, name, _ in rig.beats))
        self.assertEqual(times, [30.0 * k for k in range(1, 21)])          # 30초마다, 600초까지 20번
        self.assertEqual(r.heartbeats, 20)
        dones = [f["done"] for _, _, f in rig.beats]
        self.assertEqual(dones, sorted(dones))                              # 단조 증가
        self.assertEqual(rig.beats[-1][2], {"done": 10, "stage": "mail_local", "total": 10})
        self.assertEqual((r.rc, r.exit_code, r.killed, r.stop_kind, r.reason), (0, 0, False, None, None))
        self.assertEqual((r.done, r.total, r.events, r.lines, r.elapsed_s), (10, 10, 10, 10, 600.0))
        self.assertEqual(rig.kills, [])
        self.assertEqual(len(rig.lines), 10)
        self.assertEqual(len(rig.events), 10)

    def test_from_cfg_reads_registry_keys(self):
        class RecCfg(dict):
            def __init__(self, *a):
                super().__init__(*a)
                self.read = []

            def __getitem__(self, k):
                self.read.append(k)
                return super().__getitem__(k)

        cfg = RecCfg({"collect.watch.heartbeatSec": 30, "collect.watch.stallMin": 15,
                      "collect.watch.noProgressMin": 45})
        p = w.WatchPolicy.from_cfg(cfg, stage="probe")
        self.assertEqual(sorted(cfg.read), ["collect.watch.heartbeatSec", "collect.watch.noProgressMin",
                                            "collect.watch.stallMin"])
        self.assertEqual((p.heartbeat_s, p.stall_s, p.no_progress_s, p.stage), (30.0, 900.0, 2700.0, "probe"))
        self.assertEqual(p, w.WatchPolicy(stage="probe"))                   # 기본값 = 계약 기본값
        cfg2 = RecCfg({"collect.watch.heartbeatSec": 10, "collect.watch.stallMin": 1,
                       "collect.watch.noProgressMin": 2})
        p2 = w.WatchPolicy.from_cfg(cfg2)                                    # 값을 바꾸면 결과가 바뀐다(죽은 키 아님)
        self.assertEqual((p2.heartbeat_s, p2.stall_s, p2.no_progress_s), (10.0, 60.0, 120.0))


class StallAndNoProgress(unittest.TestCase):
    def test_stall_after_15_min_silence(self):
        rig = Rig([(60, "합성 진행 문구")])
        r = rig.run()
        self.assertEqual(rig.kills, [(960.0, PID)])                         # 마지막 줄 60초 + 15분
        self.assertEqual((r.stop_kind, r.killed, r.rc, r.reason, r.exit_code), ("stall", True, 3, "R-TRANSPORT", 1))
        self.assertEqual(r.elapsed_s, 960.0)
        self.assertEqual(r.heartbeats, 32)                                  # 침묵 중에도 감시 하트비트는 뛴다
        o = rcmap.stage_outcome(r.rc, [r.reason], {"stop_kind": r.stop_kind})
        self.assertEqual((o["state"], o["stop_kind"], o["rc"]), ("partial", "stall", 3))
        self.assertEqual(rcmap.cell_status(r.rc, [r.reason], {"stop_kind": r.stop_kind}), "transport_fail")

    def test_no_progress_after_45_min(self):
        # 1분마다 같은 done 의 progress — 살아 있지만(정체 아님) 진전이 없다
        script = periodic(60, 3 * 3600, lambda t: ev(stage="x", done=5))
        rig = Rig(script)
        r = rig.run()
        self.assertEqual(rig.kills, [(60.0 + 2700.0, PID)])
        self.assertEqual((r.stop_kind, r.killed, r.rc, r.reason), ("no_progress", True, 3, "R-TRANSPORT"))
        self.assertEqual(r.done, 5)

    def test_only_done_increase_is_progress(self):
        # 글 줄·done 없는 이벤트·같은 done 은 진전이 아니다 → 시작부터 45분에 무진전
        def make(t):
            k = int(t // 60) % 3
            return ["합성 상태 문구", ev("msg"), ev(done=0)][k]
        rig = Rig(periodic(60, 3 * 3600, make))
        r = rig.run()
        self.assertEqual((r.stop_kind, rig.kills[0][0]), ("no_progress", 2700.0))

    def test_slow_but_steady_progress_survives(self):
        # done 이 40분마다만 늘어도(45분 안) 끊지 않는다 — 긴 왕복을 죽이던 LM24 결함 방지
        script = periodic(60, 3 * 3600, lambda t: ev(done=1 + int(t // 2400))) + finish_at(3 * 3600 + 30, rc=0)
        rig = Rig(script)
        r = rig.run()
        self.assertEqual((r.killed, r.stop_kind, r.rc), (False, None, 0))
        self.assertEqual(r.done, 1 + int(3 * 3600 // 2400))

    def test_done_tracked_per_stage(self):
        # 단계 a 가 done 100 에서 끝나고 단계 b 가 1부터 다시 센다 — b 의 증가도 진전이다(살아 있음 신호는 1분마다)
        script = [(60, ev(stage="a", done=100))]
        script += [(60 + 1200 * k, ev(stage="b", done=k)) for k in range(1, 5)]
        script += periodic(60, 4980, lambda t: ev("msg"), start=90)
        script += finish_at(5000)
        rig = Rig(script)
        r = rig.run()
        self.assertEqual((r.killed, r.done, r.rc), (False, 104, 0))

    def test_stall_checked_before_no_progress(self):
        rig = Rig([], stall_s=100.0, no_progress_s=100.0)
        r = rig.run()
        self.assertEqual((r.stop_kind, rig.kills[0][0]), ("stall", 100.0))

    def test_eof_but_alive_still_stalls(self):
        rig = Rig([(10, "합성"), (11, w.EOF)])
        r = rig.run()
        self.assertEqual((r.stop_kind, rig.kills[0][0]), ("stall", 910.0))

    def test_exit_without_eof_does_not_hang(self):
        rig = Rig([(5, "합성"), (6, _Exit(0))])
        r = rig.run()
        self.assertEqual((r.killed, r.rc, r.exit_code), (False, 0, 0))
        self.assertLess(r.elapsed_s, 6 + w.EXIT_DRAIN_S + 2)

    def test_slow_consumer_after_exit_gets_every_line(self):
        """자식은 이미 끝났고 읽기 스레드가 줄을 다 큐에 넣었는데 소비자(on_line → 정제 파이프 stdin)가 느리면
        EXIT_DRAIN_S 는 마감이 아니라 유휴 한도다 — 꼬리를 버리고 rc 0(성공 위장)으로 끝나면 안 된다."""
        n = 1000

        class _Lines:
            def __init__(self, child):
                self.child = child

            def __iter__(self):
                for k in range(n):
                    yield json.dumps({"kind": "pc_file", "i": k})
                self.child.finish(0)                 # 다 쓰고 나서 끝남

        child = FakeChild()
        child.stdout = _Lines(child)
        clock = VClock(child, [])
        got = []

        def slow(line):
            got.append(line)
            clock.t += 0.01                          # 줄마다 10ms(가상) — 1000줄이면 EXIT_DRAIN_S 의 5배
        r = w.watch(child, w.WatchPolicy(heartbeat_s=0, progress_on_lines=True), clock=clock,
                    kill=lambda pid: self.fail("끊으면 안 됨"), emit=None, on_line=slow)
        self.assertEqual((len(got), r.lines, r.done, r.rc, r.killed), (n, n, n, 0, False))
        self.assertGreater(r.elapsed_s, w.EXIT_DRAIN_S)

    def test_deeply_nested_line_does_not_kill_watcher(self):
        deep = '{"ev": "progress", "x": ' + "[" * 100000 + "]" * 100000 + "}"
        self.assertIsNone(w.parse_event(deep))
        rig = Rig([(1, deep), (2, ev(done=1))] + finish_at(3))
        r = rig.run()
        self.assertEqual((r.killed, r.rc, r.done, r.lines), (False, 0, 1, 2))

    def test_disabled_limits_never_kill(self):
        rig = Rig([(5, "합성")] + finish_at(10 * 3600, rc=4), heartbeat_s=0, stall_s=0, no_progress_s=0,
                  poll_s=60.0)
        r = rig.run()
        self.assertEqual((r.killed, r.rc, r.heartbeats, rig.beats), (False, 4, 0, []))


class WatcherFailure(unittest.TestCase):
    def test_callback_error_kills_child_and_propagates(self):
        rig = Rig(periodic(10, 600, lambda t: ev(done=int(t))))

        def broken(line):
            if rig.clock.now() >= 50:
                raise BrokenPipeError("합성")                                  # 정제 파이프 stdin 이 끊긴 경우

        with self.assertRaises(BrokenPipeError):
            w.watch(rig.child, rig.policy, clock=rig.clock, kill=rig.kill, emit=rig.emit, on_line=broken)
        rig.child.stdout.release()
        self.assertEqual(rig.kills, [(50.0, PID)])


class RecordStream(unittest.TestCase):
    CANARY = "합성카나리아" + "원문제목"

    def script(self):
        out = [(1, '{"_meta":{"my_addrs":[]}}')]
        out += periodic(60, 3600, lambda t: json.dumps({"kind": "mail", "subject": self.CANARY, "n": int(t)},
                                                       ensure_ascii=False))
        out += [(3601, '{"_cursor":{"last_ts_utc":"2026-10-05T00:00:00Z"}}')] + finish_at(3602)
        return out

    def test_records_count_as_progress_when_enabled(self):
        rig = Rig(self.script(), progress_on_lines=True)
        r = rig.run()
        self.assertEqual((r.killed, r.done, r.lines, r.events, r.rc), (False, 60, 62, 0, 0))
        self.assertEqual(len(rig.lines), 62)                                 # 제어 줄도 연결자에게 그대로 넘긴다
        self.assertNotIn(self.CANARY, repr(r))                               # 결과에 원문 0
        self.assertNotIn(self.CANARY, repr(rig.beats))

    def test_records_are_not_progress_by_default(self):
        rig = Rig(self.script())
        r = rig.run()
        self.assertEqual((r.stop_kind, r.done), ("no_progress", 0))

    def test_line_helpers(self):
        self.assertIsNone(w.parse_event("합성"))
        self.assertIsNone(w.parse_event('{"ev":"nope"}'))
        self.assertIsNone(w.parse_event('{"ev": 1}'))
        self.assertIsNone(w.parse_event('{"ev":"progress"'))
        self.assertEqual(w.parse_event(' {"done":3,"ev":"progress","seq":1} ')["done"], 3)
        self.assertTrue(w.is_record_line('{"kind":"mail"}'))
        self.assertTrue(w.is_record_line('{"_kind":"mail"}'))               # 경로 나누기 줄은 레코드
        for ctl in ('{"_meta":{}}', '{"_cursor":{}}', '{"_in":{}}', "", "합성"):
            self.assertFalse(w.is_record_line(ctl), ctl)


class Cancel(unittest.TestCase):
    def test_cancel_kills_after_grace(self):
        rig = Rig(periodic(10, 3600, lambda t: ev(done=int(t))))
        r = rig.run(cancel=lambda: rig.clock.now() >= 100)
        self.assertEqual(rig.kills, [(105.0, PID)])
        self.assertEqual((r.stop_kind, r.killed, r.rc, r.reason), ("cancelled", True, 3, "R-TRANSPORT"))

    def test_cancel_honoured_by_child(self):
        rig = Rig(periodic(10, 100, lambda t: ev(done=int(t))) + finish_at(102, rc=0))
        r = rig.run(cancel=lambda: rig.clock.now() >= 100)
        self.assertEqual((r.stop_kind, r.killed, r.rc, rig.kills), ("cancelled", False, 0, []))
        o = rcmap.stage_outcome(r.rc, [], {"stop_kind": r.stop_kind})
        self.assertEqual((o["state"], o["stop_kind"], o["rc"]), ("partial", "cancelled", 0))


class MonitorUnit(unittest.TestCase):
    def test_next_wake_and_verdict(self):
        p = w.WatchPolicy(heartbeat_s=30, stall_s=900, no_progress_s=2700, poll_s=5)
        m = w.Monitor(p, 0.0)
        self.assertEqual(m.next_wake(0.0), 5.0)
        self.assertEqual(m.next_wake(28.0), 2.0)
        self.assertIsNone(m.verdict(899.0))
        self.assertEqual(m.verdict(900.0), "stall")
        m.feed(ev(done=1), 899.0)
        self.assertIsNone(m.verdict(1500.0))
        self.assertEqual(m.verdict(899.0 + 2700.0), "stall")
        m.feed("합성", 3000.0)
        self.assertEqual(m.verdict(899.0 + 2700.0), "no_progress")
        m.feed(ev(done=1), 3500.0)                                          # 같은 done — 진전 아님
        self.assertEqual(m.prog_at, 899.0)
        m.feed(ev(done=0, total=9), 3550.0)
        self.assertEqual((m.done, m.total), (1, 9))
        m.feed(ev("result", rows=3), 3560.0)
        self.assertEqual(m.last_result["rows"], 3)


class Defaults(unittest.TestCase):
    def test_default_kill_and_emit_are_util(self):
        if not (ROOT / "lm27" / "util" / "proc.py").is_file():
            self.skipTest("lm27.util.proc 아직 없음(WP-00)")
        from lm27.util import events, proc
        self.assertIs(w._default_kill(), proc.kill_tree)
        self.assertIs(w._default_emit(), events.emit)


class RealProcess(unittest.TestCase):
    def _py_child(self, code):
        flags = 0x08000000 if sys.platform == "win32" else 0
        child = subprocess.Popen([sys.executable, "-X", "utf8", "-B", "-I", "-c", code], stdin=subprocess.DEVNULL,
                                 stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=flags)
        self.addCleanup(self._close, child)
        return child

    @staticmethod
    def _close(child):
        if child.poll() is None:
            child.kill()
        child.wait(timeout=30)
        child.stdout.close()

    def _kill(self):
        if (ROOT / "lm27" / "util" / "proc.py").is_file():
            from lm27.util import proc
            return proc.kill_tree
        return None

    def test_normal_child(self):
        code = ("import json,time\n"
                "for i in range(1, 4):\n"
                "    print(json.dumps({'ev': 'progress', 'done': i, 'total': 3}), flush=True)\n"
                "    time.sleep(0.05)\n"
                "print('합성 끝', flush=True)\n"
                "raise SystemExit(4)\n")
        child = self._py_child(code)
        beats = []
        kill = self._kill() or (lambda pid: child.kill())
        r = w.watch(child, w.WatchPolicy(heartbeat_s=0.05, stall_s=20, no_progress_s=20, poll_s=0.05),
                    kill=kill, emit=lambda e, **f: beats.append(f))
        self.assertEqual((r.rc, r.exit_code, r.killed, r.done, r.total, r.events, r.lines), (4, 4, False, 3, 3, 3, 4))

    def test_stalled_child_is_killed(self):
        child = self._py_child("import time\nprint('합성 시작', flush=True)\ntime.sleep(60)\n")
        kill = self._kill() or (lambda pid: child.kill())
        t0 = time.monotonic()
        r = w.watch(child, w.WatchPolicy(heartbeat_s=0, stall_s=1.0, no_progress_s=0, poll_s=0.1), kill=kill)
        self.assertLess(time.monotonic() - t0, 30)
        self.assertEqual((r.stop_kind, r.killed, r.rc, r.lines), ("stall", True, 3, 1))
        self.assertIsNotNone(child.poll())                                  # 트리째 끝남


if __name__ == "__main__":
    unittest.main()
