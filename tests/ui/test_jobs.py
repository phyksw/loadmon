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
