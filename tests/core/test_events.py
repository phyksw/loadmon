# -*- coding: utf-8 -*-
"""WP-00 lm27.util.events — 표준 출력 이벤트 한 줄 JSON · seq 단조 · 30초 Heartbeat(가상 시계) 시험(계약 §8.6)."""
import io
import json
import threading
import time
import unittest

from lm27.util import events

TS_RX = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"


class EventsCase(unittest.TestCase):
    def setUp(self):
        self.out, self.err = io.StringIO(), io.StringIO()
        events.configure("jsonl", stream=self.out, err_stream=self.err)
        self.addCleanup(events.configure, "text")

    def lines(self):
        return [json.loads(x) for x in self.out.getvalue().splitlines()]


class JsonlTest(EventsCase):
    def test_one_line_json_with_monotonic_seq(self):
        events.emit("stage_start", stage="time", text_ko="시간 계산을 시작합니다")
        events.emit("progress", stage="time", done=3, total=10)
        events.emit("stage_end", stage="time", state="done", rc=0)
        raw = self.out.getvalue()
        self.assertEqual(raw.count("\n"), 3)
        evs = self.lines()
        self.assertEqual([e["ev"] for e in evs], ["stage_start", "progress", "stage_end"])
        seqs = [e["seq"] for e in evs]
        self.assertEqual(seqs, sorted(seqs))
        self.assertEqual(len(set(seqs)), 3)
        for e in evs:
            self.assertRegex(e["ts"], TS_RX)
        self.assertEqual(evs[1]["done"], 3)
        self.assertEqual(self.err.getvalue(), "")

    def test_text_with_newline_stays_one_line(self):
        events.emit("msg", text_ko="첫 줄\n둘째 줄")
        self.assertEqual(self.out.getvalue().count("\n"), 1)
        self.assertEqual(self.lines()[0]["text_ko"], "첫 줄\n둘째 줄")

    def test_none_fields_dropped_and_return_value(self):
        rec = events.emit("notice", stage=None, text_ko="알림")
        self.assertNotIn("stage", rec)
        self.assertEqual(rec, self.lines()[0])

    def test_validation(self):
        self.assertRaises(ValueError, events.emit, "bogus")
        self.assertRaises(ValueError, events.emit, "msg", seq=1)
        self.assertRaises(ValueError, events.emit, "msg", ev="x")
        self.assertRaises(TypeError, events.emit, "result", data=object())
        self.assertRaises(ValueError, events.emit, "result", data=float("nan"))
        self.assertRaises(ValueError, events.configure, "xml")

    def test_all_contract_event_names(self):
        for ev in ("stage_start", "progress", "notice", "warn", "msg", "stage_end", "run_end", "result", "check"):
            events.emit(ev)
        self.assertEqual(len(self.lines()), 9)

    def test_seq_monotonic_across_threads(self):
        def worker():
            for _ in range(100):
                events.emit("progress", stage="t")

        ts = [threading.Thread(target=worker) for _ in range(8)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        seqs = [e["seq"] for e in self.lines()]
        self.assertEqual(len(seqs), 800)
        self.assertEqual(seqs, sorted(seqs))
        self.assertEqual(len(set(seqs)), 800)

    def test_injected_clock_and_job(self):
        events.configure("jsonl", job="j20261005180000a1b2", stream=self.out, now=lambda: "2026-10-05T09:00:00Z")
        events.emit("msg")
        self.assertEqual(self.lines()[0]["ts"], "2026-10-05T09:00:00Z")
        self.assertEqual(events.job_id(), "j20261005180000a1b2")
        self.assertEqual(events.mode(), "jsonl")

    def test_reset_seq(self):
        events.emit("msg")
        events.configure("jsonl", stream=self.out, reset_seq=True)
        events.emit("msg")
        self.assertEqual(self.lines()[-1]["seq"], 1)
        self.assertEqual(events.last_seq(), 1)


class TextModeTest(EventsCase):
    def test_text_goes_to_stderr_only(self):
        events.configure("text", stream=self.out, err_stream=self.err)
        events.emit("warn", text_ko="경고 문장")
        events.emit("progress", stage="수집", done=1, total=3)
        events.emit("result", data={"a": 1})
        self.assertEqual(self.out.getvalue(), "")
        lines = self.err.getvalue().splitlines()
        self.assertEqual(lines[0], "[경고] 경고 문장")
        self.assertIn("수집 진행 중 1/3", lines[1])
        self.assertEqual(len(lines), 2)

    def test_off_writes_nothing(self):
        events.configure("off", stream=self.out, err_stream=self.err)
        rec = events.emit("warn", text_ko="x")
        self.assertEqual((self.out.getvalue(), self.err.getvalue()), ("", ""))
        self.assertEqual(rec["ev"], "warn")

    def test_closed_stream_does_not_raise(self):
        s = io.StringIO()
        s.close()
        events.configure("jsonl", stream=s)
        events.emit("msg")                     # 받는 쪽이 닫혀도 본 작업을 죽이지 않는다


class HeartbeatTest(EventsCase):
    def test_virtual_clock_30s(self):
        now = [1000.0]
        hb = events.Heartbeat(30, stage="analyze", total=10, clock=lambda: now[0])
        now[0] = 1029.9
        self.assertFalse(hb.tick())
        now[0] = 1030.0
        self.assertTrue(hb.tick())
        hb.update(done=5)
        now[0] = 1059.0
        self.assertFalse(hb.tick())
        now[0] = 1060.0
        self.assertTrue(hb.tick())
        now[0] = 1200.0
        self.assertTrue(hb.tick())              # 늦게 불려도 한 번만 낸다(밀린 수만큼 쏟지 않음)
        evs = self.lines()
        self.assertEqual([e["ev"] for e in evs], ["progress"] * 3)
        self.assertEqual([e["done"] for e in evs], [0, 5, 5])
        self.assertTrue(all(e["stage"] == "analyze" and e["total"] == 10 for e in evs))
        self.assertEqual(hb.count, 3)

    def test_default_interval_is_30(self):
        self.assertEqual(events.HEARTBEAT_SEC, 30)
        self.assertEqual(events.Heartbeat().interval_s, 30.0)
        self.assertRaises(ValueError, events.Heartbeat, 0)

    def test_beat_and_extra_fields(self):
        hb = events.Heartbeat(30, stage="s", clock=lambda: 0.0)
        hb.update(done=2, total=4, unit="건")
        rec = hb.beat()
        self.assertEqual((rec["done"], rec["total"], rec["unit"]), (2, 4, "건"))

    def test_background_thread(self):
        with events.Heartbeat(0.05, stage="bg") as hb:
            hb.update(done=1)
            time.sleep(0.4)
        n = hb.count
        self.assertGreaterEqual(n, 2)
        time.sleep(0.2)
        self.assertEqual(hb.count, n)           # 멈춘 뒤에는 더 내지 않는다
        self.assertTrue(all(e["stage"] == "bg" for e in self.lines()))


if __name__ == "__main__":
    unittest.main()
