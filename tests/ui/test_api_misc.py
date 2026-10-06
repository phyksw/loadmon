# -*- coding: utf-8 -*-
"""화면 API 잡동사니 — 설정 검증·저장(단일 레지스트리)·G-R9 ui.* 섭동 · 수동 업무 기록(정제 파이프로만)·취소 기록 ·
수집·분석 작업 인자(cli 어댑터 형) · 이 PC 라벨·역할(pc.json, 번들 잠금) · 분석 이력·결과 선택. 합성 자료만."""
import json
import time
import unittest

from lm27.bundle import loader, pcreg
from lm27.ui import jobs as J
from lm27.util import fsx
from tests.fixtures.wp35.harness import PC_ID, RUN_ID, Running, Sandbox, seed_analysis


def _wait_job(app, jid, timeout=20.0):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        v = app.jobs.get(jid)
        if v and v["state"] in J.FINISHED:
            return v
        time.sleep(0.05)
    return app.jobs.get(jid)


class SettingsTest(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()
        self.addCleanup(self.sb.cleanup)
        self.app = self.sb.app()
        self.srv = Running(self.app).__enter__()
        self.addCleanup(self.srv.close)

    def test_get_put_reset(self):
        st, b, _ = self.srv.req("GET", "/api/settings")
        self.assertEqual(st, 200)
        it = {x["key"]: x for x in b["items"]}
        self.assertEqual(it["ui.jobPollMs"]["value"], 1000)
        self.assertEqual(it["ui.jobPollMs"]["group"], "ui")
        self.assertEqual(it["time.window.std"]["group"], "work")
        st, b, _ = self.srv.req("PUT", "/api/settings", {"ui.jobPollMs": 1500})
        self.assertEqual(st, 200, b)
        self.assertEqual(fsx.read_json(self.sb.paths.config_json(), None)["ui.jobPollMs"], 1500)
        st, h, _ = self.srv.req("GET", "/api/hello")
        self.assertEqual(h["job_poll_ms"], 1500)                         # G-R9: 섭동하면 화면 상태가 바뀐다
        st, b, _ = self.srv.req("POST", "/api/settings/reset", {"key": "ui.jobPollMs"})
        self.assertEqual(st, 200)
        st, h, _ = self.srv.req("GET", "/api/hello")
        self.assertEqual(h["job_poll_ms"], 1000)

    def test_put_rejects_unknown_and_bad_type(self):
        st, b, _ = self.srv.req("PUT", "/api/settings", {"ui.nope": 1})
        self.assertEqual(st, 400)
        self.assertEqual(b["detail"][0]["key"], "ui.nope")
        st, b, _ = self.srv.req("PUT", "/api/settings", {"ui.jobPollMs": "빠르게"})
        self.assertEqual(st, 400)
        st, b, _ = self.srv.req("PUT", "/api/settings", {"ui.jobPollMs": 10})
        self.assertEqual(st, 400)                                        # 범위 200~10000
        self.assertIsNone(fsx.read_json(self.sb.paths.config_json(), None))   # 하나도 쓰지 않음

    def test_restart_flag(self):
        st, b, _ = self.srv.req("PUT", "/api/settings", {"ui.port": 19281})
        self.assertEqual(st, 200, b)
        self.assertEqual(b["restart"], ["ui.port"])

    def test_gr9_perturb_home_and_report(self):
        seed_analysis(self.sb)
        st, h1, _ = self.srv.req("GET", "/api/home")
        self.srv.req("PUT", "/api/settings", {"ui.homeCoverageDays": 7, "ui.tableMaxRows": 77})
        st, h2, _ = self.srv.req("GET", "/api/home")
        self.assertNotEqual(h1["coverage"]["from"], h2["coverage"]["from"])
        st, r, _ = self.srv.req("GET", "/api/report?variant=full")
        self.assertEqual(r["table_max_rows"], 77)
        st, runs, _ = self.srv.req("GET", "/api/analysis/runs")
        self.assertEqual(runs["defaults"]["months"], 3)
        self.srv.req("PUT", "/api/settings", {"report.defaultRangeMonths": 6})
        st, runs, _ = self.srv.req("GET", "/api/analysis/runs")
        self.assertEqual(runs["defaults"]["months"], 6)


class WorklogTest(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()
        self.addCleanup(self.sb.cleanup)
        self.app = self.sb.app()
        self.srv = Running(self.app).__enter__()
        self.addCleanup(self.srv.close)

    def test_span_record_through_pipe(self):
        memo = "시험 지그 점검 — 담당 김철수"
        st, b, _ = self.srv.req("POST", "/api/worklog", {"date": "2026-10-02", "kind": "offsite", "a": "13:00",
                                                         "b": "15:30", "project": "P-0007", "memo": memo})
        self.assertEqual(st, 200, b)
        call = self.app.deps.pipe_calls[0]
        self.assertEqual((call["kind"], call["src"], call["pc_id"]), ("manual", "manual", PC_ID))
        raw = call["raws"][0]
        self.assertEqual((raw["man_kind"], raw["date"], raw["start"], raw["end"]), ("offsite", "2026-10-02", "13:00",
                                                                                   "15:30"))
        self.assertIsNone(raw["hours"])
        self.assertEqual(raw["note"], memo)                              # 원문은 파이프 stdin(메모리)으로만 — 디스크 0
        self.assertFalse(any(memo in p.read_text(encoding="utf-8", errors="replace")
                             for p in self.sb.dir.rglob("*") if p.is_file() and p.suffix in (".json", ".jsonl", ".log")))

    def test_hours_record_and_validation(self):
        st, b, _ = self.srv.req("POST", "/api/worklog", {"date": "2026-10-02", "kind": "work", "hours": 1.25})
        self.assertEqual(st, 200, b)
        self.assertEqual(self.app.deps.pipe_calls[0]["raws"][0]["hours"], 1.25)
        for body in ({"date": "2026-10-02", "kind": "work", "hours": 0.3},
                     {"date": "2026-10-02", "kind": "work"},
                     {"date": "2026-10-02", "kind": "work", "a": "15:00", "b": "14:00"},
                     {"date": "20261002", "kind": "work", "hours": 1},
                     {"date": "2026-10-02", "kind": "retract", "hours": 1},
                     {"date": "2026-10-02", "kind": "work", "hours": 1, "memo": "가" * 201}):
            st, b, _ = self.srv.req("POST", "/api/worklog", body)
            self.assertEqual(st, 400, body)
        self.assertEqual(len(self.app.deps.pipe_calls), 1)

    def test_retract(self):
        st, b, _ = self.srv.req("POST", "/api/worklog", {"retract": "0123456789abcdef"})
        self.assertEqual(st, 200, b)
        raw = self.app.deps.pipe_calls[0]["raws"][0]
        self.assertEqual((raw["man_kind"], raw["retract_of"]), ("retract", "0123456789abcdef"))
        st, b, _ = self.srv.req("POST", "/api/worklog", {"retract": "nope"})
        self.assertEqual(st, 400)

    def test_pipe_failure_and_no_key(self):
        self.app.deps.pipe_rc = 6
        st, b, _ = self.srv.req("POST", "/api/worklog", {"date": "2026-10-02", "kind": "work", "hours": 1})
        self.assertEqual((st, b["code"]), (409, "no_key"))
        self.app.deps.pipe_rc = 3
        st, b, _ = self.srv.req("POST", "/api/worklog", {"date": "2026-10-02", "kind": "work", "hours": 1})
        self.assertEqual((st, b["code"]), (500, "pipe_failed"))
        self.app.deps.pipe_rc, self.app.deps.stored = 0, 0
        st, b, _ = self.srv.req("POST", "/api/worklog", {"date": "2026-10-02", "kind": "work", "hours": 1})
        self.assertEqual((st, b["code"]), (400, "rejected"))


class JobArgvTest(unittest.TestCase):
    """작업 인자 = cli 어댑터 형(계약 §7.1) — 가짜 하위 명령이 받은 argv 를 결과로 돌려준다."""

    def setUp(self):
        self.sb = Sandbox()
        self.addCleanup(self.sb.cleanup)
        self.app = self.sb.app(behaviour={k: {"sleep": 0} for k in ("collect", "analyze", "report", "bundle", "team",
                                                                    "move-prepare", "agent")})
        self.srv = Running(self.app).__enter__()
        self.addCleanup(self.srv.close)

    def _argv(self, method, path, body):
        st, b, _ = self.srv.req(method, path, body)
        self.assertEqual(st, 200, b)
        return _wait_job(self.app, b["job_id"])["result"]["argv"]

    def test_collect_modes(self):
        self.assertEqual(self._argv("POST", "/api/collect/run", {"mode": "auto"}), ["collect", "--auto"])
        self.assertEqual(self._argv("POST", "/api/collect/run", {"mode": "probe-only"}),
                         ["collect", "--mode", "probe-only"])
        self.assertEqual(self._argv("POST", "/api/collect/run", {"mode": "recollect", "since": "2026-09-01",
                                                                 "until": "2026-09-30"}),
                         ["collect", "--mode", "recollect", "--since", "2026-09-01", "--until", "2026-09-30"])
        st, b, _ = self.srv.req("POST", "/api/collect/run", {"mode": "recollect"})
        self.assertEqual(st, 400)

    def test_analysis_argv(self):
        self.assertEqual(self._argv("POST", "/api/analysis/run", {"from": "2026-07-01", "to": "2026-09-30", "ai": False,
                                                                  "as_of": "2026-09-30T18:00",
                                                                  "period_source": "default", "period_months": 3}),
                         ["analyze", "--from", "2026-07-01", "--to", "2026-09-30", "--as-of", "2026-09-30T18:00",
                          "--period-source", "default", "--period-months", "3", "--no-ai"])     # W2 통합 — 기간 출처 전달
        for bad in ({"period_source": "rerun"}, {"period_months": 0}, {"period_months": "3"}):
            st, b, _ = self.srv.req("POST", "/api/analysis/run", dict({"from": "2026-07-01", "to": "2026-09-30"}, **bad))
            self.assertEqual(st, 400, bad)
        self.assertEqual(self._argv("POST", "/api/analysis/run", {"rerun": RUN_ID,
                                                                  "stages": ["classify", "time", "mining", "report"],
                                                                  "ai": False}),
                         ["analyze", "--rerun", RUN_ID, "--stages", "classify,time,mining,report", "--no-ai"])
        st, b, _ = self.srv.req("POST", "/api/analysis/run", {"from": "2026-09-30", "to": "2026-09-01"})
        self.assertEqual(st, 400)

    def test_auto_team_send_triggers(self):
        """TAB §2.8 재시도 계기(W2 통합): 화면 기동·15분 타이머 — 승인된 막힘 없는 대기분이 있을 때만 작업
        'team send --all --trigger <계기>'. 대기분이 없거나 막혔거나 모르는 계기면 작업 0."""
        from types import SimpleNamespace
        from unittest import mock
        self.assertIsNone(self.app.auto_team_send("timer"))                            # 빈 대기열
        ok = SimpleNamespace(folder="pending", meta={"approved": True})
        blocked = SimpleNamespace(folder="pending", meta={"approved": True, "blockers": ["team_text_rejected"]})
        sent = SimpleNamespace(folder="sent", meta={"approved": True})
        with mock.patch("lm27.team.queue.list_items", lambda paths=None: [blocked, sent]):
            self.assertIsNone(self.app.auto_team_send("startup"))
        with mock.patch("lm27.team.queue.list_items", lambda paths=None: [ok]):
            self.assertIsNone(self.app.auto_team_send("manual"))
            jid = self.app.auto_team_send("timer")
        self.assertIsNotNone(jid)
        self.assertEqual(_wait_job(self.app, jid)["result"]["argv"], ["team", "send", "--all", "--trigger", "timer"])

    def test_move_prepare_waits_for_ui_server(self):
        """통합(W2 C21 handoff): [이동 준비]는 도우미가 화면 서버의 정상 종료를 기다리게 서버 pid 를 넘긴다(move-prepare --wait-pid)."""
        import os
        from unittest import mock
        seen = []
        with mock.patch.object(self.app, "start_job", lambda kind, argv: seen.append((kind, list(argv))) or
                               {"ok": True, "job_id": "j1"}):
            st, b, _ = self.srv.req("POST", "/api/move/prepare", {})
        self.assertEqual(st, 200, b)
        self.assertEqual(seen, [("move_prepare", ["move-prepare", "--wait-pid", str(os.getpid())])])

    def test_report_export_and_team_argv(self):
        self.assertEqual(self._argv("POST", "/api/report/export", {"run_id": RUN_ID}),
                         ["report", "export", "--run", RUN_ID, "--formats", "html,csv,json", "--variant", "full,redacted"])
        self.assertEqual(self._argv("POST", "/api/team/registry/fetch", {}), ["team", "registry-fetch"])
        self.assertEqual(self._argv("POST", "/api/agent/repair", {}), ["agent", "repair"])
        st, b, _ = self.srv.req("POST", "/api/report/export", {"run_id": RUN_ID, "formats": ["pdf"]})
        self.assertEqual(st, 400)


class PcAndRunsTest(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()
        self.addCleanup(self.sb.cleanup)
        self.app = self.sb.app()
        self.srv = Running(self.app).__enter__()
        self.addCleanup(self.srv.close)

    def test_label_roles_kind(self):
        st, b, _ = self.srv.req("POST", "/api/pc/label", {"label_user": "내 데스크톱"})
        self.assertEqual(st, 409)                                        # 번들에 이 PC 기록이 아직 없다
        pcreg.update_pc(loader.pc_dir_of(self.sb.paths, PC_ID), {"label_auto": "PC1"})
        st, b, _ = self.srv.req("POST", "/api/pc/label", {"label_user": "내 데스크톱"})
        self.assertEqual(st, 200, b)
        st, b, _ = self.srv.req("POST", "/api/pc/roles", {"roles": ["pc_usage", "copilot"]})
        self.assertEqual(st, 200, b)
        st, b, _ = self.srv.req("POST", "/api/pc/kind", {"kind": "laptop", "confirmed": True})
        self.assertEqual(st, 200, b)
        pc = pcreg.load_pc(loader.pc_dir_of(self.sb.paths, PC_ID))
        self.assertEqual((pc["label_user"], pc["roles"], pc["kind"], pc["kind_confirmed"]),
                         ("내 데스크톱", ["copilot", "pc_usage"], "laptop", True))
        st, b, _ = self.srv.req("POST", "/api/pc/roles", {"roles": ["root"]})
        self.assertEqual(st, 400)
        st, b, _ = self.srv.req("POST", "/api/pc/label", {"label_user": "가" * 21})
        self.assertEqual(st, 400)
        st, h, _ = self.srv.req("GET", "/api/hello")
        self.assertEqual(h["pc"]["label_auto"], "내 데스크톱")

    def test_runs_and_choose_current(self):
        seed_analysis(self.sb)
        st, b, _ = self.srv.req("GET", "/api/analysis/runs")
        self.assertEqual(st, 200)
        self.assertEqual([r["run_id"] for r in b["runs"]], [RUN_ID])
        self.assertTrue(b["runs"][0]["current"])
        st, b, _ = self.srv.req("GET", f"/api/analysis/run/{RUN_ID}")
        self.assertEqual(st, 200, b)
        self.assertEqual(b["queue"], {"open": 2, "answered": 0})
        st, b, _ = self.srv.req("POST", "/api/analysis/current", {"run_id": RUN_ID})
        self.assertEqual(st, 200, b)
        cur = fsx.read_json(self.sb.paths.analysis_current(), None)
        self.assertEqual(cur["chosen"], "explicit")
        st, b, _ = self.srv.req("POST", "/api/analysis/current", {"run_id": "20261001-090000-1b2c"})
        self.assertEqual(st, 409)
        st, b, _ = self.srv.req("GET", "/api/analysis/run/20261001-090000-1b2c")
        self.assertEqual(st, 404)

    def test_interrupted_run_shown_cancelled(self):
        seed_analysis(self.sb)
        st0 = fsx.read_json(self.sb.paths.run_status_file(RUN_ID), None)
        st0.update(state="running", pid=999999)
        fsx.atomic_write(self.sb.paths.run_status_file(RUN_ID), fsx.canon_bytes(st0))
        st, b, _ = self.srv.req("GET", "/api/analysis/runs")
        self.assertEqual(b["runs"][0]["state"], "cancelled")

    def test_run_time_shown_in_work_timezone(self):
        """이력 표의 '분석 시각' — run_status 의 UTC('…Z')를 근무 시간대 벽시계로(머리 띠와 같은 시각, 9시간 어긋남 없음)."""
        seed_analysis(self.sb)
        st0 = fsx.read_json(self.sb.paths.run_status_file(RUN_ID), None)
        st0.update(started="2026-10-06T05:00:10Z", ended="2026-10-06T05:05:59Z")
        fsx.atomic_write(self.sb.paths.run_status_file(RUN_ID), fsx.canon_bytes(st0))
        st, b, _ = self.srv.req("GET", "/api/analysis/runs")
        self.assertEqual(b["runs"][0]["built_at"], "2026-10-06T14:05:59+09:00")
        st0["ended"] = "2026-10-06T14:05:59+09:00"                          # 이미 로컬 형식이면 그대로
        fsx.atomic_write(self.sb.paths.run_status_file(RUN_ID), fsx.canon_bytes(st0))
        st, b, _ = self.srv.req("GET", "/api/analysis/runs")
        self.assertEqual(b["runs"][0]["built_at"], "2026-10-06T14:05:59+09:00")

    def test_collect_status_empty_bundle(self):
        st, b, _ = self.srv.req("GET", "/api/collect/status")
        self.assertEqual(st, 200, b)
        self.assertEqual(b["pc"]["agent"]["state"], "missing")
        self.assertEqual(b["import"]["dir"].replace("/", "\\"), "data\\import")
        self.assertEqual(b["pcs"], [])
        self.assertEqual(b["worklog"], [])
        self.assertNotIn(str(self.sb.root), json.dumps(b, ensure_ascii=False))   # 절대 경로 없음


if __name__ == "__main__":
    unittest.main()
