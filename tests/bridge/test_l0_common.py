# -*- coding: utf-8 -*-
"""WP-23 공용층 — 시계(B §11.1)·fsio(G-B7)·사용자 문구(B §13)·전송 계측(B §5.9)."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from lm27.bridge import fsio, messages, trace
from lm27.bridge.clock import INF, Deadline, RealClock, VirtualClock, iso_now, iso_to_epoch, stamp, today
from lm27.bridge.transport import SendRequest, SendResult
from lm27.paths import Paths

from tests.bridge.fake_http import bridge_settings


class TestClock(unittest.TestCase):
    def test_virtual_clock_does_not_sleep(self):
        c = VirtualClock()
        c.sleep(480)
        c.sleep(-5)
        self.assertEqual(c.mono(), 480.0)
        self.assertEqual(c.now(), 1_790_000_000.0 + 480)
        self.assertEqual((c.sleeps, c.slept), (2, 480.0))
        seen = []
        c.on_sleep = seen.append
        c.sleep(1)
        self.assertEqual(seen, [481.0])

    def test_deadline(self):
        c = VirtualClock()
        d = Deadline.after(c, 900)
        c.sleep(30)
        self.assertEqual(d.left(), 870.0)
        self.assertEqual(d.cap(1000), 870.0)
        self.assertEqual(d.cap(10), 10.0)
        self.assertEqual(d.sub(5).at, 35.0)
        self.assertEqual(d.earlier(100).at, 100)
        c.sleep(900)
        self.assertTrue(d.expired())
        self.assertEqual(Deadline.after(c, None).at, INF)
        self.assertEqual(Deadline.after(c, INF).left(), INF)

    def test_iso_and_stamp(self):
        c = VirtualClock()
        s = iso_now(c)
        self.assertRegex(s, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+09:00$")
        self.assertEqual(today(c), s[:10])
        self.assertRegex(stamp(c), r"^\d{8}T\d{4}Z$")
        self.assertEqual(iso_to_epoch(s), float(int(c.now())))
        self.assertEqual(iso_to_epoch("2026-10-05T00:00:00Z"), iso_to_epoch("2026-10-05T09:00:00+09:00"))
        self.assertIsNone(iso_to_epoch("2026-10-05T00:00:00"))
        self.assertIsNone(iso_to_epoch("garbage"))

    def test_real_clock(self):
        r = RealClock()
        a = r.mono()
        r.sleep(0)
        self.assertGreaterEqual(r.mono(), a)
        self.assertRegex(iso_now(r), r"[+-]\d{2}:\d{2}$")


class TestFsio(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="lm27t_fsio_"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_append_and_atomic(self):
        p = self.tmp / "a" / "j.jsonl"
        fsio.append_line(p, {"b": 1, "a": "가"})
        fsio.append_line(p, '{"x":2}')
        self.assertEqual(p.read_bytes(), '{"a":"가","b":1}\n{"x":2}\n'.encode())
        with self.assertRaises(ValueError):
            fsio.append_line(p, "두\n줄")
        q = self.tmp / "b" / "o.json"
        fsio.write_atomic(q, {"z": [1, 2]})
        self.assertEqual(fsio.read_json(q), {"z": [1, 2]})
        self.assertFalse(list(q.parent.glob("*.part")))

    def test_write_text_ttl_bom_crlf_and_prune(self):
        c = VirtualClock(start_epoch=os.path.getmtime(self.tmp) + 30 * 86400)
        d = self.tmp / "manual"
        old = d / "old.prompt.txt"
        fsio.write_atomic(old, "x")
        os.utime(old, (c.now() - 8 * 86400, c.now() - 8 * 86400))
        n = fsio.write_text_ttl(d / "new.prompt.txt", "첫 줄\n둘째 줄", ttl_days=7, clock=c)
        self.assertEqual(n, 1)
        self.assertFalse(old.exists())
        raw = (d / "new.prompt.txt").read_bytes()
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
        self.assertIn(b"\r\n", raw)
        self.assertNotIn(b"\n\n", raw.replace(b"\r\n", b""))

    def test_exclusive_move_rotate_remove(self):
        p = self.tmp / "lock.json"
        self.assertTrue(fsio.create_exclusive(p, {"pid": 1}))
        self.assertFalse(fsio.create_exclusive(p, {"pid": 2}))
        self.assertEqual(fsio.read_json(p), {"pid": 1})
        self.assertTrue(fsio.move_aside(p, str(p) + ".stale"))
        self.assertFalse(p.exists())
        self.assertFalse(fsio.move_aside(p, str(p) + ".stale"))
        t = self.tmp / "trace.jsonl"
        fsio.write_atomic(t, "x" * 100)
        self.assertFalse(fsio.rotate(t, 1000))
        self.assertTrue(fsio.rotate(t, 10))
        self.assertTrue((self.tmp / "trace.jsonl.1").exists())
        self.assertTrue(fsio.remove(self.tmp / "trace.jsonl.1"))
        self.assertFalse(fsio.remove(self.tmp / "nope"))
        dd = self.tmp / "prof"
        dd.mkdir()
        self.assertTrue(fsio.rename_dir(dd, self.tmp / "prof.bad-1"))
        self.assertTrue(fsio.remove_tree(self.tmp / "prof.bad-1"))

    def test_bridge_file_and_child(self):
        paths = Paths(self.tmp / "root", lad=self.tmp / "lad")
        self.assertEqual(fsio.bridge_file(paths, "trace"), Path(paths.bridge_dir()) / "trace.jsonl")
        self.assertEqual(fsio.bridge_file(paths, "bridge_profile").name, "bridge_profile.json")
        with self.assertRaises(ValueError):
            fsio.child(self.tmp, "../x")
        with self.assertRaises(ValueError):
            fsio.child(self.tmp, "a\\b")


class TestMessages(unittest.TestCase):
    def test_codes_and_render(self):
        for code in ("BR-LOGIN", "BR-LOGIN-OK", "BR-EDGE", "BR-POLICY", "BR-LOCK-BUSY", "BR-DEAD-PROFILE",
                     "BR-PROFILE-BUSY", "BR-INPUT", "BR-TAB", "BR-LAUNCH", "BR-NOLIC", "BR-WEB-STRICT", "BR-WEB-BLOCK",
                     "BR-WEB-MODE", "BR-MANUAL-SWITCH", "BR-MANUAL-RID", "BR-GATE-BLOCKED", "BR-HEADER"):
            self.assertIn(code, messages.BR)
        r = messages.render("BR-LOGIN", loginWaitMin=10)
        self.assertEqual(r["title"], "Copilot 로그인이 필요합니다")
        self.assertIn("최대 10분", r["action"])
        self.assertIn(r["title"], r["text_ko"])
        r2 = messages.render("BR-BUDGET", stage="task_label")
        self.assertIn("-/-건", r2["body"])                 # 빠진 자리 값은 '-'
        with self.assertRaises(KeyError):
            messages.render("BR-NOPE")

    def test_notices_once(self):
        got = []
        n = messages.Notices(lambda ev, **kw: got.append((ev, kw["code"])))
        self.assertTrue(n.notify("BR-LOGIN", loginWaitMin=10))
        self.assertFalse(n.notify("BR-LOGIN"))
        self.assertTrue(n.notify("BR-LOGIN-OK"))
        self.assertEqual(got, [("notice", "BR-LOGIN"), ("notice", "BR-LOGIN-OK")])
        self.assertEqual(n.shown, ["BR-LOGIN", "BR-LOGIN-OK"])

    def test_explain_phase(self):
        self.assertEqual(messages.explain_phase("login_required"), ("BR-LOGIN", True))
        self.assertEqual(messages.explain_phase("edge_not_found"), ("BR-EDGE", True))
        self.assertEqual(messages.explain_phase("policy_blocked"), ("BR-POLICY", True))
        self.assertEqual(messages.explain_phase("send_failed"), ("BR-SERVICE", False))
        self.assertEqual(messages.explain_phase("replied"), ("", False))
        self.assertTrue(messages.MANUAL_SWITCH_PHASES <= messages.FATAL_PHASES)
        self.assertEqual(len(set(messages.ALL_PHASES)), len(messages.ALL_PHASES))


class TestTrace(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="lm27t_trace_"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.paths = Paths(self.tmp / "root", lad=self.tmp / "lad")
        self.cfg = bridge_settings(str(self.tmp))

    def test_whitelist_no_raw_text(self):
        t = trace.Tracer(self.paths, self.cfg, VirtualClock(), run_id="20261005-101500-3fa2")
        secret = "프롬프트 원문 " * 20
        row = t.write(stage="task_label", rid="R7F3QK", phase="replied", body=secret, prompt=secret, text=secret,
                      model_used="빠른 응답\n줄", sec=12.345)
        self.assertNotIn("body", row)
        self.assertNotIn("prompt", row)
        self.assertEqual(row["model_used"], "빠른 응답 줄")
        self.assertEqual(row["sec"], 12.3)
        raw = fsio.bridge_file(self.paths, "trace").read_text(encoding="utf-8")
        self.assertNotIn("프롬프트 원문", raw)
        self.assertEqual([r["seq"] for r in trace.iter_rows(fsio.bridge_file(self.paths, "trace"))], [1])

    def test_send_row_and_rotation(self):
        cfg = self.cfg.replace(trace_max_bytes=600)
        t = trace.Tracer(self.paths, cfg, VirtualClock(), run_id="20261005-101500-3fa2")
        req = SendRequest("R7F3QK", "글" * 100, False, "빠른 응답", 480, 180, 900, "speech_act", True)
        res = SendResult(phase="replied", body="답" * 50, done_by="pledge", pick="dom", busy_seen=True, gen_sec=33.04,
                         in_chars=100, injected_chars=100, model_used="빠른 응답", work_mode="work", chat_seq=2)
        for _ in range(6):
            row = t.send(req, res, rung=1, status="ok", sec=40.0, chat_turn=3, web_exposed=True)
        self.assertEqual((row["in"], row["reply"], row["done_by"], row["rung"]), (100, 50, "pledge", 1))
        self.assertTrue(Path(str(fsio.bridge_file(self.paths, "trace")) + ".1").exists())
        self.assertNotIn("글글", json.dumps(t.rows, ensure_ascii=False))

    def test_disabled_and_failure_tolerant(self):
        t = trace.Tracer(self.paths, self.cfg, VirtualClock(), enabled=False)
        t.write(phase="replied")
        self.assertFalse(fsio.bridge_file(self.paths, "trace").exists())
        self.assertEqual(len(t.rows), 1)


if __name__ == "__main__":
    unittest.main()
