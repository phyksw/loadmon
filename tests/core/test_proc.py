# -*- coding: utf-8 -*-
"""WP-00 lm27.util.proc — 자식 실행·시간 초과·트리 종료(계약 §8.7·§9.1) 시험.
자식은 시험용 파이썬 한 줄 스크립트뿐이다(수집기·외부 도구를 띄우지 않는다)."""
import ast
import os
import subprocess
import sys
import time
import unittest
from unittest import mock

from lm27.util import fsx, proc

PY = sys.executable
SLEEPER = "import time; time.sleep(60)"
# 손자를 띄우고 그 pid 를 한 줄 출력한 뒤 잠든다
PARENT = ("import subprocess,sys,time;"
          "g=subprocess.Popen([sys.executable,'-B','-c','import time; time.sleep(60)'],creationflags=0x08000000);"
          "print(g.pid,flush=True);time.sleep(60)")


def _wait_gone(pid, limit=10.0):
    end = time.monotonic() + limit
    while proc.pid_alive(pid) and time.monotonic() < end:
        time.sleep(0.05)
    return not proc.pid_alive(pid)


class RunChildTest(unittest.TestCase):
    def test_stdout_rc_and_stdin_roundtrip(self):
        r = proc.run_child([PY, "-B", "-c", "import sys;d=sys.stdin.buffer.read();sys.stdout.buffer.write(d[::-1]);"
                                         "sys.exit(3)"], timeout_s=60, stdin=b"abc")
        self.assertEqual((r.rc, r.stdout, r.timed_out), (3, b"cba", False))
        self.assertGreater(r.pid, 0)
        r = proc.run_child([PY, "-B", "-X", "utf8", "-c", "import sys;print(sys.stdin.read())"], timeout_s=60,
                           stdin="한글")
        self.assertEqual(r.out_text().strip(), "한글")

    def test_no_stdin_means_devnull(self):
        r = proc.run_child([PY, "-B", "-c", "import sys;print(repr(sys.stdin.read()))"], timeout_s=60)
        self.assertEqual(r.rc, 0)
        self.assertEqual(r.out_text().strip(), "''")

    def test_stderr_captured(self):
        r = proc.run_child([PY, "-B", "-c", "import sys;sys.stderr.write('e1')"], timeout_s=60)
        self.assertEqual(r.stderr, b"e1")
        self.assertEqual(r.err_text(), "e1")

    def test_timeout_kills_tree(self):
        t0 = time.monotonic()
        r = proc.run_child([PY, "-B", "-c", PARENT], timeout_s=2)
        self.assertTrue(r.timed_out)
        self.assertIsNone(r.rc)
        self.assertLess(time.monotonic() - t0, 30)
        grandchild = int(r.out_text().split()[0])
        self.assertTrue(_wait_gone(r.pid))
        self.assertTrue(_wait_gone(grandchild), "손자 프로세스가 남았습니다")

    def test_grandchild_holding_pipe_does_not_block(self):
        """자식이 stdout 을 상속한 손자(Start-Process·.NET Process.Start 와 같은 모양)를 남기고 곧바로 끝나면,
        run_child 는 손자가 끝날 때까지 기다리지 않는다 — 자식의 종료로 판정하고 rc 를 그대로 돌려준다(timed_out 아님)."""
        child = ("import subprocess, sys\n"
                 "g = subprocess.Popen([sys.executable, '-B', '-c', 'import time; time.sleep(40)'], stdout=sys.stdout,"
                 " stderr=sys.stderr, close_fds=False, creationflags=0x08000000)\n"
                 "print(g.pid, flush=True)\nsys.exit(4)\n")
        t0 = time.monotonic()
        r = proc.run_child([PY, "-B", "-c", child], timeout_s=3)
        took = time.monotonic() - t0
        gpid = int(r.out_text().split()[0])
        self.addCleanup(proc.kill_tree, gpid)
        self.assertEqual((r.rc, r.timed_out), (4, False))
        self.assertLess(took, 3 + proc.DRAIN_S + 3, "손자가 파이프를 쥔 동안 막혔습니다")
        self.assertTrue(proc.pid_alive(gpid), "정상 종료 때는 자손을 끝내지 않는다(의도한 자손일 수 있다)")

    def test_timeout_reaches_orphaned_grandchild(self):
        """부모(중간 프로세스)가 먼저 끝나 taskkill /T 가 닿지 않는 고아 손자도 시간 초과 때 끝난다(Job Object)."""
        mid = ("import subprocess, sys\n"
               "g = subprocess.Popen([sys.executable, '-B', '-c', 'import time; time.sleep(60)'],"
               " stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=0x08000000)\n"
               "print(g.pid, flush=True)\n")
        child = ("import subprocess, sys, time\n"
                 "out = subprocess.run([sys.executable, '-B', '-c', sys.argv[1]], capture_output=True).stdout\n"
                 "print(out.decode().strip(), flush=True)\ntime.sleep(60)\n")
        t0 = time.monotonic()
        r = proc.run_child([PY, "-B", "-c", child, mid], timeout_s=4)
        self.assertLess(time.monotonic() - t0, 4 + proc.KILL_DRAIN_S + proc.KILL_TIMEOUT_S)
        self.assertTrue(r.timed_out)
        orphan = int(r.out_text().split()[0])
        self.addCleanup(lambda: proc.pid_alive(orphan) and proc.kill_tree(orphan))
        self.assertTrue(_wait_gone(orphan), "부모 없는 손자가 남았습니다")

    def test_timeout_required(self):
        self.assertRaises(ValueError, proc.run_child, [PY, "-c", "pass"], timeout_s=0)
        self.assertRaises(ValueError, proc.run_child, [PY, "-c", "pass"], timeout_s=None)

    def test_env_merge_and_remove(self):
        code = "import os;print(os.environ.get('LM27T_X'), os.environ.get('LM27T_Y'), bool(os.environ.get('PATH')))"
        with mock.patch.dict(os.environ, {"LM27T_Y": "1"}):
            r = proc.run_child([PY, "-B", "-c", code], timeout_s=60, env={"LM27T_X": "abc", "lm27t_y": None})
        self.assertEqual(r.out_text().split(), ["abc", "None", "True"])


class KillTreeTest(unittest.TestCase):
    def test_kill_tree_leaves_no_descendants(self):
        ch = proc.spawn([PY, "-B", "-c", PARENT])
        try:
            grandchild = int(ch.stdout.readline().decode().strip())
            self.assertTrue(proc.pid_alive(ch.pid))
            self.assertTrue(proc.pid_alive(grandchild))
            self.assertTrue(proc.kill_tree(ch.pid))
            self.assertTrue(_wait_gone(ch.pid))
            self.assertTrue(_wait_gone(grandchild), "손자 프로세스가 남았습니다")
        finally:
            if ch.alive():
                ch.kill_tree()
            ch.close()

    def test_child_kill_tree_and_context_manager(self):
        with proc.spawn([PY, "-B", "-c", SLEEPER]) as ch:
            pid = ch.pid
            self.assertTrue(ch.alive())
        self.assertTrue(_wait_gone(pid))

    def test_kill_tree_rejects_self_and_bad_pid(self):
        self.assertRaises(ValueError, proc.kill_tree, os.getpid())
        self.assertRaises(ValueError, proc.kill_tree, 0)
        self.assertRaises(ValueError, proc.kill_tree, "123")
        self.assertRaises(ValueError, proc.kill_tree, True)

    def test_kill_tree_on_finished_process(self):
        p = subprocess.Popen([PY, "-B", "-c", "pass"], creationflags=0x08000000)
        p.wait(timeout=60)
        self.assertTrue(proc.kill_tree(p.pid))

    def test_pid_alive(self):
        self.assertTrue(proc.pid_alive(os.getpid()))
        self.assertFalse(proc.pid_alive(0))
        self.assertFalse(proc.pid_alive(-5))
        p = subprocess.Popen([PY, "-B", "-c", "pass"], creationflags=0x08000000)
        p.wait(timeout=60)
        self.assertFalse(proc.pid_alive(p.pid))


class SpawnTest(unittest.TestCase):
    def test_no_window_flag_by_default(self):
        seen = {}

        class FakePopen:
            pid = 4321
            stdin = stdout = stderr = None
            returncode = None

            def __init__(self, argv, **kw):
                seen.update(kw)
                seen["argv"] = argv

        with mock.patch.object(proc.subprocess, "Popen", FakePopen):
            ch = proc.spawn(["x.exe", "a"], stderr=proc.DEVNULL)
            self.assertEqual(ch.pid, 4321)
            self.assertEqual(seen["creationflags"], proc.CREATE_NO_WINDOW)
            self.assertEqual(seen["stdin"], proc.DEVNULL)
            self.assertEqual(seen["argv"], ["x.exe", "a"])
            proc.spawn(["y.exe"], stderr=proc.DEVNULL, new_console=True)
            self.assertEqual(seen["creationflags"], proc.CREATE_NEW_CONSOLE)
        self.assertEqual(proc.CREATE_NO_WINDOW, 0x08000000)

    def test_iter_lines_and_stderr_tail(self):
        code = ("import sys\n"
                "for i in range(3): print('줄', i)\n"
                "for i in range(5000): sys.stderr.write('e%d\\n' % i)\n")
        with proc.spawn([PY, "-B", "-X", "utf8", "-c", code]) as ch:
            lines = list(ch.iter_lines())
            self.assertEqual(ch.wait(timeout=60), 0)
            ch._drain.join(timeout=10)
        self.assertEqual(lines, ["줄 0", "줄 1", "줄 2"])
        self.assertEqual(len(ch.stderr_tail), proc.TAIL_LINES)
        self.assertEqual(ch.stderr_tail[-1], "e4999")

    def test_stdin_pipe_for_control_line(self):
        code = "import sys,json;d=json.loads(sys.stdin.readline());print(d['_in']['cursor'])"
        ch = proc.spawn([PY, "-B", "-c", code], stdin=proc.PIPE)
        try:
            ch.stdin.write(b'{"_in":{"cursor":7}}\n')
            ch.stdin.close()
            self.assertEqual(list(ch.iter_lines()), ["7"])
            self.assertEqual(ch.wait(timeout=60), 0)
        finally:
            ch.close()


class SourceRuleTest(unittest.TestCase):
    def test_no_os_kill(self):
        src = fsx.read_bytes(proc.__file__).decode("utf-8")
        tree = ast.parse(src)
        calls = {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
        self.assertNotIn("os.kill", calls)
        self.assertNotIn("os.killpg", calls)


if __name__ == "__main__":
    unittest.main()
