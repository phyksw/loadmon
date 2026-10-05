# -*- coding: utf-8 -*-
"""WP-12 lock — 번들 쓰기 잠금 BundleLock(TAB §1.9): 0번 바이트 msvcrt 잠금 · 보유자 표시 줄 · 죽은 보유자 자동 해제 ·
같은 스레드 중첩 · 다른 스레드 대기 · 설정 bundle.lockTimeoutSec."""
import os
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path

from lm27.bundle import lock as lk
from tests.fixtures.wp12.builders import BundleTestCase

TREE = Path(__file__).resolve().parents[2]
CREATE_NO_WINDOW = 0x08000000


class LockTest(BundleTestCase):
    def _child_holder(self, purpose="export"):
        code = ("import sys,time;sys.path.insert(0, sys.argv[1]);from lm27.paths import Paths;"
                "from lm27.bundle.lock import BundleLock;"
                "l=BundleLock(Paths(sys.argv[2], lad=sys.argv[3]), sys.argv[4], 5);l.acquire();"
                "print('locked', flush=True);time.sleep(60)")
        p = subprocess.Popen([sys.executable, "-X", "utf8", "-B", "-c", code, str(TREE), str(self.b.root),
                              str(self.b.lad), purpose], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             creationflags=CREATE_NO_WINDOW)
        def _stop():
            p.kill()
            p.communicate(timeout=10)
        self.addCleanup(_stop)
        line = p.stdout.readline().decode().strip()
        self.assertEqual(line, "locked", p.stderr.read(2000) if line != "locked" else "")
        return p

    def test_acquire_release_and_holder_line(self):
        with lk.BundleLock(self.paths, "fg-write", 1) as lock:
            self.assertTrue(lock.held)
            self.assertTrue(lk.is_held_here(self.paths))
            h = lk.read_holder(self.paths.bundle_lock())
            self.assertEqual(h["pid"], os.getpid())
            self.assertEqual(h["purpose"], "fg-write")
        self.assertFalse(lk.is_held_here(self.paths))
        raw = self.paths.bundle_lock().read_bytes()
        self.assertEqual(raw[:1], b"\x00", "0번 바이트는 잠금 전용")

    def test_busy_reports_holder_then_auto_release_on_kill(self):
        child = self._child_holder("merge")
        t0 = time.monotonic()
        with self.assertRaises(lk.BundleBusy) as cm:
            lk.BundleLock(self.paths, "export", 0.6).acquire()
        self.assertGreaterEqual(time.monotonic() - t0, 0.5)
        self.assertEqual(cm.exception.holder["pid"], child.pid)
        self.assertEqual(cm.exception.holder["purpose"], "merge")
        self.assertIn("merge", str(cm.exception))
        child.kill()
        child.wait(10)
        with lk.BundleLock(self.paths, "export", 5) as lock:      # OS 잠금 — 보유자가 죽으면 즉시 풀린다
            self.assertTrue(lock.held)

    def test_nested_same_thread_is_reentrant(self):
        with lk.BundleLock(self.paths, "collect-init", 1):
            with lk.BundleLock(self.paths, "export", 0):
                self.assertTrue(lk.is_held_here(self.paths))
            self.assertTrue(lk.is_held_here(self.paths))
        self.assertFalse(lk.is_held_here(self.paths))

    def test_other_thread_waits(self):
        got = []
        outer = lk.BundleLock(self.paths, "export", 1).acquire()

        def worker():
            with lk.BundleLock(self.paths, "fg-write", 5):
                got.append(time.monotonic())
        t = threading.Thread(target=worker)
        t.start()
        time.sleep(0.5)
        self.assertEqual(got, [])
        released = time.monotonic()
        outer.release()
        t.join(10)
        self.assertEqual(len(got), 1)
        self.assertGreaterEqual(got[0], released)

    def test_other_thread_times_out(self):
        outer = lk.BundleLock(self.paths, "export", 1).acquire()
        self.addCleanup(outer.release)
        err = []

        def worker():
            try:
                lk.BundleLock(self.paths, "fg-write", 0.3).acquire()
            except lk.BundleBusy as e:
                err.append(e)
        t = threading.Thread(target=worker)
        t.start()
        t.join(10)
        self.assertEqual(len(err), 1)

    def test_timeout_from_cfg(self):
        cfg = self.b.cfg(**{"bundle.lockTimeoutSec": 7})
        self.assertEqual(lk.lock_timeout(cfg), 7)
        self.assertEqual(lk.BundleLock(self.paths, "export", cfg=cfg).timeout_s, 7)
        self.assertEqual(lk.BundleLock(self.paths, "export").timeout_s, lk.DEFAULT_TIMEOUT_S)
        self.assertEqual(lk.BundleLock(self.paths, "export", 2, cfg=cfg).timeout_s, 2)

    def test_bad_purpose(self):
        for bad in ("", "Export", "a b", "x" * 40, None):
            with self.assertRaises(ValueError):
                lk.BundleLock(self.paths, bad, 1)

    def test_compaction_when_large(self):
        p = self.paths.bundle_lock()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"\x00" + b'{"pid":1,"purpose":"export","at":"2026-10-01T00:00:00Z"}\n' * 200)
        old = lk.COMPACT_BYTES
        lk.COMPACT_BYTES = 1000
        self.addCleanup(setattr, lk, "COMPACT_BYTES", old)
        with lk.BundleLock(self.paths, "export", 1):
            pass
        self.assertLess(p.stat().st_size, 200)
        self.assertEqual(lk.read_holder(p)["purpose"], "export")


if __name__ == "__main__":
    unittest.main()
