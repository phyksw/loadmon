# -*- coding: utf-8 -*-
"""WP-33 전경 연결자(lm27.collect.run — run_ps · run_py · harvest_run) — 계약 §7.3 · §8.1 · §8.2 · X-300 · v1.2 C1.

  · 수집기 stdin 제어 줄 ``_in``(커서·설정·본인 이름) — 명령줄에 싣지 않는다.
  · 수집기 stdout → 정제 파이프 stdin, stderr 마지막 ``{"_status": …}``(CLM 이면 파이프 요약의 collector_status).
  · 파이프 실패 3·5 → rc 3 + R-TRANSPORT, 6 → R-NOKEY, ``privacy.pipe.waitSec`` 초과 → kill_tree + 99 → R-TRANSPORT.
  · 감시: 정체(stall)면 kill_tree → rc 3 + R-TRANSPORT + stop_kind stall(시험 설정으로 정체 한도만 짧게).
  · recollect: 커서 없이, ``_cursor`` 줄을 파이프에 넘기지 않는다.
  · 수확: 에이전트 harvest_done → 결과, 시간 안에 안 끝나면 ``.harvest.lock`` 을 쥐고 전경, 잠금이 잡혀 있으면 건너뜀.
수집기·파이프는 가짜(tests\\fixtures\\wp33\\fake_*.py) — 실제 메일·팀즈·PC 수집 0.
"""
from __future__ import annotations

import json
import threading
import time
import unittest
from datetime import date

from lm27.collect import plan, rcmap
from lm27.collect import run as R
from lm27.store import file_lock, save_raw_cursor
from lm27.util import events
from tests.fixtures.wp33.helpers import FakeDeps, Sandbox, ident

REC = [{"subject": "과제A 회의", "ts_utc": "2026-10-01T01:00:00Z"}, {"subject": "과제A 보고", "ts_utc": "2026-10-01T02:00:00Z"},
       {"subject": "고객사A 회신", "ts_utc": "2026-10-02T01:00:00Z"}]


class CfgOver:
    """설정 덮어쓰기(레지스트리 범위 밖 시험 값 — 대기 초과 시험을 짧게)."""

    def __init__(self, base, **over):
        self.base, self.over = base, over

    def __getitem__(self, k):
        return self.over[k] if k in self.over else self.base[k]


def make_ctx(sb, cfg, deps, *, mode="auto", caps=None, agent=None, since=None, until=None):
    ctx = R._Ctx(paths=sb.paths, cfg=cfg, deps=deps, run_id="20261005-120000-00aa", mode=mode, since=since,
                 until=until, only=None, t0=0.0, deadline=None)
    ctx.ident = deps.ident_
    ctx.today = date(2026, 10, 5)
    ctx.caps = caps or {}
    ctx.agent = agent if agent is not None else {}
    return ctx


class ConnectorCase(unittest.TestCase):
    def setUp(self):
        events.configure("off")
        self.addCleanup(events.configure, "text")
        self.sb = Sandbox()
        self.addCleanup(self.sb.cleanup)
        self.cfg = self.sb.cfg()

    def deps(self, specs=None, pipe=None, **kw):
        return FakeDeps(self.sb, self.cfg, specs=specs, pipe=pipe, **kw)

    def test_in_line_cursor_cfg_not_on_command_line(self):
        echo = self.sb.work / "in.txt"
        d = self.deps({"mail.com": {"rc": 0, "records": REC, "cursor": {"box": {}}, "echo_in": str(echo),
                                    "status": {"rc": 0, "reasons": []}}})
        save_raw_cursor(self.sb.paths, d.ident_.pc_id, "mail.com", {"box": {"inbox": {"last_ts_utc": "2026-09-30T00:00:00Z"}}})
        caps = {"mail.com": {"value": {"omg": False, "attach": "ok"}}}
        r = R.run_ps(make_ctx(self.sb, self.cfg, d, caps=caps), plan.COLLECTORS["mail.com"])
        self.assertEqual((r.rc, r.stored, r.rows_in), (0, 3, 3))
        line = json.loads(echo.read_bytes())
        self.assertEqual(line["_in"]["cursor"], {"box": {"inbox": {"last_ts_utc": "2026-09-30T00:00:00Z"}}})
        self.assertEqual(sorted(line["_in"]["cfg"]), sorted(plan.COLLECTORS["mail.com"].cfg))
        self.assertEqual(line["_in"]["cfg"]["mail.com.readProtected"], "1")       # 탐침 OMG 없음 → B단 허용
        self.assertNotIn("self_names", line["_in"])
        argv = d.collector_calls("mail.com")[0][2]
        self.assertNotIn("mail.com.budgetSec", " ".join(argv))
        pipe_argv = [c for c in d.calls if c[0] == "pipe"][0][2]
        self.assertEqual(pipe_argv[pipe_argv.index("--src") + 1], "mail.com")
        self.assertEqual(pipe_argv[pipe_argv.index("--mode") + 1], "append")
        self.assertNotIn("--out", pipe_argv)                                       # store 경로를 조립하지 않는다(L-11)

    def test_status_partial_cap_and_months(self):
        save_raw_cursor(self.sb.paths, ident().pc_id, "mail.com",
                        {"cov_months": {"2026-10": {"status": "done"}, "2026-09": {"status": "partial"}}})
        d = self.deps({"mail.com": {"rc": 0, "records": REC, "status": {
            "schema": "lm27.collector_status/1", "rc": 0, "reasons": ["R-CAP"], "partial": True, "cap_hit": True,
            "budget_hit": False, "n": 3, "counts": {"horizon_oldest": "2026-07-01"}, "subfolder_ratio": 0.4,
            "unknown_field": "x"}}})
        r = R.run_ps(make_ctx(self.sb, self.cfg, d), plan.COLLECTORS["mail.com"])
        self.assertTrue(r.cap_hit)
        self.assertEqual(r.horizon_oldest, "2026-07-01")
        self.assertEqual(r.extra["subfolder_ratio"], 0.4)
        self.assertEqual(r.months, {"2026-10": "done", "2026-09": "partial"})
        o = r.outcome()
        self.assertEqual((o["state"], o["caps_hit"], o["reason"]), ("partial", True, "R-CAP"))       # T-10

    def test_pipe_failures_translate(self):
        for code, why in ((3, "R-TRANSPORT"), (5, "R-TRANSPORT"), (6, "R-NOKEY")):
            d = self.deps({"mail.index": {"rc": 0, "records": REC, "status": {"rc": 0, "reasons": []}}},
                          pipe={"exit": code})
            r = R.run_ps(make_ctx(self.sb, self.cfg, d), plan.COLLECTORS["mail.index"])
            self.assertEqual((r.rc, r.pipe, r.exit_code), (3, code, 0))
            self.assertIn(why, r.reasons)
            self.assertEqual(r.stored, 0)

    def test_pipe_wait_exceeded_is_99(self):
        d = self.deps({"mail.index": {"rc": 0, "records": REC, "status": {"rc": 0}}}, pipe={"exit": 0, "hang_s": 30})
        cfg = CfgOver(self.cfg, **{"privacy.pipe.waitSec": 1})
        t0 = time.monotonic()
        r = R.run_ps(make_ctx(self.sb, cfg, d), plan.COLLECTORS["mail.index"])
        self.assertLess(time.monotonic() - t0, 25)
        self.assertEqual((r.pipe, r.rc), (rcmap.PIPE_WAIT_KILLED, 3))
        self.assertIn("R-TRANSPORT", r.reasons)

    def test_stall_kills_collector(self):
        d = self.deps({"mail.index": {"rc": 0, "records": [], "hang_s": 60, "status": {"rc": 0}}})
        cfg = CfgOver(self.cfg, **{"collect.watch.stallMin": 0.05})              # 3초 — 정체 판정만 짧게
        t0 = time.monotonic()
        r = R.run_ps(make_ctx(self.sb, cfg, d), plan.COLLECTORS["mail.index"])
        self.assertLess(time.monotonic() - t0, 30)
        self.assertEqual((r.rc, r.stop_kind), (rcmap.RC_KILLED, "stall"))
        self.assertIn("R-TRANSPORT", r.reasons)
        o = r.outcome()
        self.assertEqual((o["state"], o["stop_kind"]), ("partial", "stall"))
        self.assertEqual(rcmap.translate_cell(r.rc, r.reasons, r.counts())["status"], "transport_fail")

    def test_clm_status_via_pipe_summary(self):
        d = self.deps({"mail.index": {"rc": 3, "records": [], "stdout_status": True,
                                      "status": {"rc": 3, "reasons": ["R-CLM"]}}})
        r = R.run_ps(make_ctx(self.sb, self.cfg, d), plan.COLLECTORS["mail.index"])
        self.assertEqual(r.rc, 3)
        self.assertEqual(r.reasons, ["R-CLM"])
        self.assertEqual(rcmap.translate_cell(r.rc, r.reasons, r.counts())["status"], "blocked")

    def test_recollect_drops_cursor_and_sends_none(self):
        rec = self.sb.work / "pipe_got.txt"
        echo = self.sb.work / "in.txt"
        d = self.deps({"mail.index": {"rc": 0, "records": REC, "cursor": {"last_item_ts_utc": "x"},
                                      "echo_in": str(echo), "status": {"rc": 0}}}, pipe={"exit": 0, "record_to": str(rec)})
        save_raw_cursor(self.sb.paths, d.ident_.pc_id, "mail.index", {"last_item_ts_utc": "2026-09-01T00:00:00Z"})
        ctx = make_ctx(self.sb, self.cfg, d, mode="recollect", since="2026-09-01", until="2026-09-30")
        r = R.run_ps(ctx, plan.COLLECTORS["mail.index"])
        self.assertIsNone(json.loads(echo.read_bytes())["_in"]["cursor"])
        self.assertNotIn(b"_cursor", rec.read_bytes())
        self.assertFalse(r.cursor_saved)
        argv = d.collector_calls("mail.index")[0][2]
        self.assertEqual(argv[argv.index("-Since") + 1], "2026-09-01")
        self.assertEqual(r.ranges, [["2026-09-01", "2026-09-30"]])

    def test_teams_gets_self_names(self):
        echo = self.sb.work / "in.txt"
        d = self.deps({"teams.uia": {"rc": 4, "records": [], "echo_in": str(echo), "status": {"rc": 4}}})
        r = R.run_ps(make_ctx(self.sb, self.cfg, d), plan.COLLECTORS["teams.uia"])
        line = json.loads(echo.read_bytes())
        self.assertIsInstance(line["_in"]["self_names"], list)
        self.assertEqual(r.ranges, [["2026-10-05", "2026-10-05"]])

    def test_run_py_status_and_no_pipe(self):
        d = self.deps({"pc.git": {"rc": 0, "status": {"rc": 0, "reasons": [], "n": 5, "items_ok": 5, "items_total": 7}}})
        r = R.run_py(make_ctx(self.sb, self.cfg, d), plan.COLLECTORS["pc.git"])
        self.assertEqual((r.rc, r.stored, r.rows_in, r.pipe), (0, 5, 7, None))
        self.assertFalse([c for c in d.calls if c[0] == "pipe"])
        d = self.deps({"mail.import": {"rc": 3, "status": {"rc": 3, "reasons": ["R-TRANSPORT"]}}})
        r = R.run_py(make_ctx(self.sb, self.cfg, d), plan.COLLECTORS["mail.import"])
        self.assertEqual((r.rc, r.reasons, r.ranges), (3, ["R-TRANSPORT"], []))

    def test_missing_script_not_run(self):
        d = self.deps()
        r = R.run_py(make_ctx(self.sb, self.cfg, d), plan.COLLECTORS["mail.copilot"], blanks=[])
        self.assertEqual((r.rc, r.skipped), (None, "script_missing"))
        self.assertEqual(r.outcome()["state"], "skipped")


class HarvestCase(unittest.TestCase):
    def setUp(self):
        events.configure("off")
        self.addCleanup(events.configure, "text")
        self.sb = Sandbox()
        self.addCleanup(self.sb.cleanup)
        self.cfg = self.sb.cfg()
        self.srcs = list(R.HARVEST_SRCS)

    def test_agent_harvest_done(self):
        done = {"rc": 3, "done": True, "result": {"schema": "lm27.harvest_done/1", "streams": {
            "pc.events": {"src": "pc.events", "rc": 0, "pipe": 0, "stored": 4, "reasons": [], "timed_out": False,
                          "skipped": "", "status": {"rc": 0, "reasons": [], "budget_hit": True}},
            "pc.files": {"src": "pc.files", "rc": 0, "pipe": 99, "stored": 0, "reasons": ["R-TRANSPORT"],
                         "timed_out": False, "skipped": ""},
            "pc.mru": {"src": "pc.mru", "rc": None, "pipe": 0, "stored": 0, "reasons": [], "timed_out": True,
                       "skipped": ""},
            "pc.recent": {"src": "pc.recent", "rc": None, "pipe": None, "stored": 0, "reasons": [], "timed_out": False,
                          "skipped": "settings_missing"}}}}
        d = FakeDeps(self.sb, self.cfg, harvest=done)
        ctx = make_ctx(self.sb, self.cfg, d, agent={"rc": 4, "impl": "py", "health": {"healthy": True}})
        runs, how = R.harvest_run(ctx, self.srcs)
        self.assertEqual(how, "agent")
        self.assertEqual(d.harvest_calls, [float(self.cfg["agent.harvestWaitSec"])])
        by = {r.src: r for r in runs}
        self.assertEqual((by["pc.events"].rc, by["pc.events"].stored, by["pc.events"].budget_hit), (0, 4, True))
        self.assertEqual((by["pc.files"].rc, by["pc.files"].reasons), (3, ["R-TRANSPORT"]))
        self.assertEqual((by["pc.mru"].rc, by["pc.mru"].stop_kind), (3, "stall"))
        self.assertEqual((by["pc.recent"].rc, by["pc.recent"].skipped), (None, "settings_missing"))
        self.assertFalse(d.collector_calls())                                    # 전경은 돌지 않았다

    def test_timeout_falls_back_to_foreground(self):
        specs = {s: {"rc": 4, "records": [], "status": {"rc": 4}} for s in self.srcs}
        d = FakeDeps(self.sb, self.cfg, specs=specs, harvest={"rc": 2, "done": False, "timed_out": True})
        ctx = make_ctx(self.sb, self.cfg, d, agent={"rc": 4, "impl": "py", "health": {"healthy": True}})
        runs, how = R.harvest_run(ctx, self.srcs)
        self.assertEqual(how, "foreground")
        self.assertEqual(sorted(c[1] for c in d.collector_calls()), sorted(self.srcs))
        self.assertTrue(all(r.rc == 4 for r in runs))
        self.assertIn("harvest_wait_timeout", ctx.notes)

    def test_impl_none_runs_foreground_without_asking(self):
        specs = {s: {"rc": 3, "records": [], "status": {"rc": 3, "reasons": ["R-CLM"]}} for s in self.srcs}
        d = FakeDeps(self.sb, self.cfg, specs=specs)
        ctx = make_ctx(self.sb, self.cfg, d, agent={"rc": 3, "impl": "none", "reasons": ["R-CLM"]})
        runs, how = R.harvest_run(ctx, self.srcs)
        self.assertEqual((how, d.harvest_calls), ("foreground", []))
        self.assertTrue(all(r.reasons == ["R-CLM"] for r in runs))

    def test_busy_lock_skips(self):
        d = FakeDeps(self.sb, self.cfg)
        ctx = make_ctx(self.sb, self.cfg, d, agent={"rc": 3, "impl": "none"})
        held, release = threading.Event(), threading.Event()

        def hold():
            with file_lock(self.sb.paths.harvest_lock(), 5):
                held.set()
                release.wait(20)
        t = threading.Thread(target=hold)
        t.start()
        held.wait(10)
        try:
            runs, how = R.harvest_run(ctx, self.srcs)
        finally:
            release.set()
            t.join(10)
        self.assertEqual(how, "busy")
        self.assertTrue(all(r.skipped == "harvest_busy" and r.rc is None for r in runs))
        self.assertFalse(d.collector_calls())


if __name__ == "__main__":
    unittest.main()
