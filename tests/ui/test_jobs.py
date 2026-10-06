# -*- coding: utf-8 -*-
"""RPT-39 작업 — ① 같은 lane 두 번째 작업 409 busy ② 취소 → cancelled(5초 뒤 kill_tree, 자식 없음) ③ 서버 재기동 뒤 최근 작업.
가짜 하위 명령(tests\\fixtures\\wp35\\fake_cli.py — 실제 자식 프로세스)으로 띄운다. 끝나면 작업·스레드·폴더 정리."""
import time
import unittest

from lm27.ui import jobs as J
from lm27.util import fsx, proc
from tests.fixtures.wp35.harness import FAKE_CLI, Running, Sandbox, fake_spawn


def _wait(fn, timeout=20.0, step=0.05):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        v = fn()
        if v:
            return v
        time.sleep(step)
    return fn()


class JobsApiTest(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()
        self.addCleanup(self.sb.cleanup)

    def _srv(self, behaviour):
        app = self.sb.app(behaviour=behaviour)
        srv = Running(app).__enter__()
        self.addCleanup(srv.close)
        return app, srv

    def _done(self, srv, jid):
        def f():
            st, v, _ = srv.req("GET", f"/api/jobs/{jid}?since=0")
            return v if st == 200 and v["state"] in J.FINISHED else None
        return _wait(f)

    def test_rpt39_busy_same_lane_409(self):
        app, srv = self._srv({"collect": {"sleep": 3.0}})
        st, b, _ = srv.req("POST", "/api/collect/run", {"mode": "auto"})
        self.assertEqual(st, 200)
        jid = b["job_id"]
        st, b2, _ = srv.req("POST", "/api/analysis/run", {"from": "2026-09-01", "to": "2026-09-30", "ai": False})
        self.assertEqual(st, 409)
        self.assertEqual(b2["code"], "busy")
        self.assertIn("지금 '수집'이 진행 중입니다", b2["error"])
        st, b3, _ = srv.req("POST", "/api/report/build", {"run_id": "20261005-101500-3fa2"})
        self.assertEqual(st, 200)                                       # 다른 lane(local)은 같이 돈다
        srv.req("POST", f"/api/jobs/{jid}/cancel", {})
        self._done(srv, jid)
        self._done(srv, b3["job_id"])

    def test_rpt39_cancel_kills_tree(self):
        app, srv = self._srv({"analyze": {"sleep": 60}})
        st, b, _ = srv.req("POST", "/api/analysis/run", {"from": "2026-09-01", "to": "2026-09-30", "ai": False})
        self.assertEqual(st, 200)
        jid = b["job_id"]
        pid = _wait(lambda: app.jobs._jobs[jid].pid)
        self.assertTrue(proc.pid_alive(pid))
        t0 = time.monotonic()
        st, b, _ = srv.req("POST", f"/api/jobs/{jid}/cancel", {})
        self.assertEqual(st, 200)
        v = self._done(srv, jid)
        self.assertEqual(v["state"], "cancelled")
        self.assertLess(time.monotonic() - t0, J.CANCEL_GRACE_S + 15)
        self.assertFalse(_wait(lambda: not proc.pid_alive(pid), 10) is False)
        self.assertFalse(proc.pid_alive(pid))
        st, b, _ = srv.req("POST", f"/api/jobs/{jid}/cancel", {})
        self.assertEqual(st, 404)                                       # 끝난 작업은 취소 대상이 아니다

    def test_events_since_and_result(self):
        app, srv = self._srv({"team": {"sleep": 0.3, "result": {"path": "x\\lm27_team_bundle_2026-09-01_2026-09-30_"
                                                                        "0123456789ab.json", "name": "n"}}})
        st, b, _ = srv.req("POST", "/api/team/build", {"from": "2026-09-01", "to": "2026-09-30"})
        self.assertEqual(st, 200)
        v = self._done(srv, b["job_id"])
        self.assertEqual(v["state"], "done")
        self.assertEqual(v["rc"], 0)
        self.assertEqual(v["result"]["item"], "lm27_team_bundle_2026-09-01_2026-09-30_0123456789ab")
        seqs = [e["seq"] for e in v["events"]]
        self.assertEqual(seqs, list(range(1, len(seqs) + 1)))
        self.assertTrue(all(e["ev"] in ("stage_start", "progress", "result", "run_end") for e in v["events"]))
        st, v2, _ = srv.req("GET", f"/api/jobs/{b['job_id']}?since={seqs[-2]}")
        self.assertEqual([e["seq"] for e in v2["events"]], [seqs[-1]])

    def test_failed_rc_and_partial(self):
        app, srv = self._srv({"collect": {"sleep": 0.1, "rc": 2}, "agent": {"sleep": 0.1, "rc": 1}})
        st, b, _ = srv.req("POST", "/api/collect/run", {"mode": "probe-only"})
        self.assertEqual(self._done(srv, b["job_id"])["state"], "partial")
        st, b, _ = srv.req("POST", "/api/agent/repair", {})
        self.assertEqual(self._done(srv, b["job_id"])["state"], "failed")

    def test_rpt39_restart_shows_recent(self):
        app, srv = self._srv({"report": {"sleep": 0.1}})
        ids = []
        for _ in range(3):
            st, b, _ = srv.req("POST", "/api/report/build", {"run_id": "20261005-101500-3fa2"})
            self.assertEqual(st, 200)
            ids.append(b["job_id"])
            self._done(srv, b["job_id"])
        srv.close()
        app.close()
        jm2 = J.JobManager(self.sb.paths, self.sb.cfg(), spawn=fake_spawn({}))
        self.addCleanup(jm2.close)
        listed = [j["job_id"] for j in jm2.list()]
        for i in ids:
            self.assertIn(i, listed)
        rec = fsx.read_json(self.sb.paths.ui_job_file(ids[0]), None)
        self.assertEqual(set(rec), {"job_id", "kind", "lane", "name_ko", "state", "started", "ended", "rc", "events",
                                    "result", "seq"})
        self.assertNotIn("argv", rec)

    def test_restart_marks_unfinished_lost(self):
        jm = J.JobManager(self.sb.paths, self.sb.cfg(), spawn=fake_spawn({}))
        job = jm._new("analyze", "bundle", "분석", [])
        job.state, job.started = "running", "2026-10-06T00:00:00Z"
        jm._persist(job)
        jm.close()
        jm2 = J.JobManager(self.sb.paths, self.sb.cfg(), spawn=fake_spawn({}))
        self.addCleanup(jm2.close)
        v = jm2.get(job.job_id)
        self.assertEqual(v["state"], "failed")
        self.assertTrue(v["lost"])


class ScheduleTest(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()
        self.addCleanup(self.sb.cleanup)
        self.jm = J.JobManager(self.sb.paths, self.sb.cfg(), spawn=fake_spawn({"analyze": {"sleep": 0.1}}),
                               cli=str(FAKE_CLI))
        self.addCleanup(self.jm.close)

    def test_debounce_same_key_one_job(self):
        calls = []

        def argv():
            calls.append(1)
            return ["analyze", "--rerun", "20261005-101500-3fa2", "--stages", "classify,time,mining,report", "--no-ai"]
        a = self.jm.schedule("quick_reanalyze", argv, delay_s=0.4, key="qr")
        time.sleep(0.2)
        b = self.jm.schedule("quick_reanalyze", argv, delay_s=0.4, key="qr")
        self.assertEqual(a.job_id, b.job_id)
        self.assertEqual(self.jm.get(a.job_id)["state"], "queued")
        v = _wait(lambda: (self.jm.get(a.job_id) or {}).get("state") in J.FINISHED and self.jm.get(a.job_id))
        self.assertEqual(v["state"], "done")
        self.assertEqual(len(calls), 1)

    def test_schedule_no_argv_fails_quietly(self):
        j = self.jm.schedule("quick_reanalyze", lambda: None, delay_s=0.05, key="qr")
        v = _wait(lambda: (self.jm.get(j.job_id) or {}).get("state") in J.FINISHED and self.jm.get(j.job_id))
        self.assertEqual(v["state"], "failed")
        self.assertEqual(v["rc"], 4)

    def test_cancel_queued(self):
        j = self.jm.schedule("quick_reanalyze", lambda: ["analyze"], delay_s=30, key="qr")
        self.assertTrue(self.jm.cancel(j.job_id))
        self.assertEqual(self.jm.get(j.job_id)["state"], "cancelled")

    def test_close_cancels_and_joins(self):
        self.jm.schedule("quick_reanalyze", lambda: ["analyze"], delay_s=30, key="qr")
        self.jm.close()
        self.assertTrue(all(not t.is_alive() for t in self.jm._threads))
        with self.assertRaises(RuntimeError):
            self.jm.start("analyze", ["analyze"])


_HELPER_CLI = r'''
import json, os, subprocess, sys
# 이동 준비처럼: 손주(도우미)가 표준 출력·오류를 물려받은 채(stdin 만 DEVNULL) 오래 살고, 하위 명령은 결과를 내고 바로 끝난다
p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], stdin=subprocess.DEVNULL,
                     creationflags=0x08000000)
with open(os.environ["LM27T_GC_PID"], "w", encoding="utf-8") as f:
    f.write(str(p.pid))
print(json.dumps({"ev": "result", "data": {"ok": True}}), flush=True)
print(json.dumps({"ev": "run_end", "rc": 0}), flush=True)
'''


class GrandchildPipeTest(unittest.TestCase):
    """C21 회귀: 하위 명령이 출력 파이프를 물려받은 손주를 남기고 끝나도, 작업은 곧 끝나고(done) on_done 이 불린다
    (예전: 손주가 끝날 때까지 '진행 중' — 이동 준비면 서버 정상 종료가 돌지 않았다). 결과 이벤트는 잃지 않는다."""

    def setUp(self):
        self.sb = Sandbox()
        self.addCleanup(self.sb.cleanup)
        self.cli = self.sb.dir / "helper_cli.py"
        self.cli.write_text(_HELPER_CLI, encoding="utf-8")
        self.pidf = self.sb.dir / "gc.pid"

    def _kill_gc(self):
        try:
            pid = int(self.pidf.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if proc.pid_alive(pid):
            proc.kill_tree(pid)

    def test_job_done_while_grandchild_holds_pipe(self):
        import os
        import sys
        done = []
        t0 = time.monotonic()

        def spawn(argv, **kw):
            kw["env"] = {"LM27T_GC_PID": os.fspath(self.pidf)}
            return proc.spawn(argv, **kw)

        jm = J.JobManager(self.sb.paths, None, spawn=spawn, cli=os.fspath(self.cli), python=sys.executable,
                          on_done=lambda j: done.append((time.monotonic() - t0, j.state)))
        self.addCleanup(self._kill_gc)
        self.addCleanup(jm.close)
        job = jm.start("move_prepare", ["move-prepare"])
        _wait(lambda: done, timeout=25)
        self.assertTrue(done, "on_done 이 불려야 한다")
        self.assertEqual(done[0][1], "done")
        self.assertLess(done[0][0], 8.0, "손주(30초)가 끝날 때까지 기다리지 않는다")
        pid = int(self.pidf.read_text(encoding="utf-8"))
        self.assertTrue(proc.pid_alive(pid), "손주는 아직 산다(작업은 그와 상관없이 끝났다)")
        v = jm.get(job.job_id)
        self.assertEqual((v["state"], v["rc"]), ("done", 0))
        self.assertEqual(v["result"], {"ok": True}, "결과 이벤트를 잃지 않는다")
        self.assertEqual(fsx.read_json(self.sb.paths.ui_job_file(job.job_id), {})["state"], "done")
        t1 = time.monotonic()
        jm.close()
        self.assertLess(time.monotonic() - t1, 5.0, "서버 종료(close)가 손주가 쥔 파이프의 읽기 스레드를 기다리지 않는다")


class StateTest(unittest.TestCase):
    def test_state_of(self):
        self.assertEqual(J.state_of(0), "done")
        self.assertEqual(J.state_of(4), "done")
        self.assertEqual(J.state_of(2), "partial")
        self.assertEqual(J.state_of(1), "failed")
        self.assertEqual(J.state_of(3), "failed")
        self.assertEqual(J.state_of(None), "failed")
        self.assertEqual(J.state_of(0, True), "cancelled")

    def test_clean_event(self):
        self.assertIsNone(J._clean_event({"ev": "nope"}))
        e = J._clean_event({"ev": "progress", "done": 1, "total": 2, "text_ko": "가" * 999, "extra": {"x": 1}})
        self.assertEqual(set(e), {"ev", "done", "total", "text_ko"})
        self.assertEqual(len(e["text_ko"]), 300)


if __name__ == "__main__":
    unittest.main()
