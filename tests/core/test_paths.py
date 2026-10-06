# -*- coding: utf-8 -*-
"""WP-00 lm27.paths — 경로 로더 단일원(계약 §1·§2.1, L-08) 시험. 임시 폴더만 쓴다."""
import os
import shutil
import tempfile
import unittest
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from lm27.paths import Paths
from lm27.util import fsx

PC = "pc_0123456789abcdef"
PCX = "pcx_fedcba9876543210"
RUN = "20261005-180000-a1b2"
JOB = "j20261005180000a1b2"

# 계약 §2.1 Paths 공개 메서드(빠짐 없이 있어야 한다)
CONTRACT_METHODS = (
    "mode", "data", "bundle_json", "pcs", "pc_dir", "seg_dir", "keys", "keyring", "secrets", "local_only", "hier_local",
    "team_dir", "registry_cache", "outbox", "ai_store", "ai_run", "import_dir", "derived", "coverage_ledger",
    "teams_coverage", "todo", "collect_stage_results", "ai_in", "ai_out", "analysis", "analysis_current",
    "out_personal", "logs", "lad", "agent_dir", "agent_bin", "store_dir", "store_file", "raw_cursor",
    "privacy_audit_file", "edge_profile", "bridge_dir", "edge_lock", "ui_dir", "teamserver_default")


class PathsCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="lm27t_wp00_paths_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = Path(self.tmp) / "LoadMonitor27"
        self.lad = Path(self.tmp) / "lad" / "LoadMonitor27"
        self.p = Paths(self.root, lad=self.lad)

    def rel(self, path, base):
        return Path(path).relative_to(base).as_posix()


class ContractTest(PathsCase):
    def test_all_contract_methods_exist(self):
        for m in CONTRACT_METHODS:
            self.assertTrue(callable(getattr(self.p, m, None)), m)

    def test_data_paths(self):
        d = self.root / "data"
        exp = {
            "data": "", "bundle_json": "bundle.json", "bundle_lock": ".bundle.lock", "pc_aliases": "pc_aliases.json",
            "pcs": "pcs", "keys": "keys", "keyring": "keys/privacy_keyring.json", "secrets": "keys/secrets.json",
            "local_only": "local_only", "hier_local": "local_only/hier", "team_dir": "team",
            "registry_cache": "team/registry.json", "registry_etag": "team/registry.etag",
            "team_overrides": "team/overrides.json", "import_dir": "import", "derived": "derived",
            "coverage_ledger": "derived/coverage_ledger.jsonl", "teams_coverage": "derived/teams_coverage.jsonl",
            "todo": "derived/todo.json", "verify_cache": "derived/verify_cache.json",
            "analysis_current": "derived/analysis/current.json", "logs": "logs",
        }
        for m, r in exp.items():
            with self.subTest(m=m):
                got = getattr(self.p, m)()
                self.assertIsInstance(got, Path)
                self.assertEqual(got, d / r if r else d)

    def test_parametrized_data_paths(self):
        d = self.root / "data"
        self.assertEqual(self.rel(self.p.pc_dir(PC), d), f"pcs/{PC}")
        self.assertEqual(self.rel(self.p.pc_dir(PCX), d), f"pcs/{PCX}")
        self.assertEqual(self.rel(self.p.pc_json(PC), d), f"pcs/{PC}/pc.json")
        self.assertEqual(self.rel(self.p.manifest(PC), d), f"pcs/{PC}/manifest.json")
        self.assertEqual(self.rel(self.p.manifest_prev(PC), d), f"pcs/{PC}/manifest.prev.json")
        self.assertEqual(self.rel(self.p.move_ready(PC), d), f"pcs/{PC}/move_ready.json")
        self.assertEqual(self.rel(self.p.quarantine(PC), d), f"pcs/{PC}/quarantine")
        self.assertEqual(self.rel(self.p.seg_dir(PC, "pc_session"), d), f"pcs/{PC}/seg/pc_session")
        self.assertEqual(self.rel(self.p.seg_dir(PC, "privacy_audit"), d), f"pcs/{PC}/seg/privacy_audit")
        for st in ("pending", "sent", "failed", "dropped"):
            self.assertEqual(self.rel(self.p.outbox(st), d), f"outbox/team/{st}")
        self.assertEqual(self.rel(self.p.ai_store("task_label"), d), "ai/store/task_label.items.jsonl")
        self.assertEqual(self.rel(self.p.ai_run(RUN), d), f"ai/runs/{RUN}")
        self.assertEqual(self.rel(self.p.collect_stage_results(RUN), d), f"derived/collect/{RUN}")
        self.assertEqual(self.rel(self.p.stage_result_file(RUN, "mail_local"), d),
                         f"derived/collect/{RUN}/stage_result_mail_local.json")
        self.assertEqual(self.rel(self.p.blanks_file(RUN, "mail.owa"), d), f"derived/collect/{RUN}/blanks_mail.owa.json")
        self.assertEqual(self.rel(self.p.ai_in("task_label"), d), "derived/ai_in/task_label.jsonl")
        self.assertEqual(self.rel(self.p.ai_out("task_label"), d), "derived/ai_out/task_label.json")
        self.assertEqual(self.rel(self.p.analysis(RUN), d), f"derived/analysis/{RUN}")
        # W2 통합 — 분석·수집·내보내기 하위 경로(WP-31·32·33·35 CR)
        self.assertEqual(self.rel(self.p.analysis_root(), d), "derived/analysis")
        self.assertEqual(self.rel(self.p.collect_runs(), d), "derived/collect")
        self.assertEqual(self.p.collect_stage_results(RUN).parent, self.p.collect_runs())
        self.assertEqual(self.rel(self.p.run_status_file(RUN), d), f"derived/analysis/{RUN}/run_status.json")
        self.assertEqual(self.rel(self.p.analysis_hier_file(RUN, "labels.json"), d), f"derived/analysis/{RUN}/hier/labels.json")
        self.assertEqual(self.rel(self.p.analysis_report(RUN), d), f"derived/analysis/{RUN}/report")
        self.assertEqual(self.rel(self.p.analysis_report_file(RUN, "report_model.json"), d),
                         f"derived/analysis/{RUN}/report/report_model.json")
        self.assertEqual(self.rel(self.p.calibration_report(), d), "derived/calibration_report.json")
        self.assertEqual(self.rel(self.p.out_personal_file("2026-07-01", "2026-09-30", RUN, "csv_full/units.csv"),
                                  self.root), "out/personal/2026-07-01_2026-09-30_000-a1b2/csv_full/units.csv")
        for bad in ("../x", "a/../b", "C:/x", "", "\\\\srv\\x"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.p.out_personal_file("2026-07-01", "2026-09-30", RUN, bad)
        with self.assertRaises(ValueError):
            self.p.analysis_report_file(RUN, "..")
        self.assertEqual(self.rel(self.p.local_only_file("person_dir.json"), d), "local_only/person_dir.json")
        self.assertEqual(self.rel(self.p.hier_local_file("corrections.jsonl"), d), "local_only/hier/corrections.jsonl")

    def test_out_personal_run8(self):
        got = self.p.out_personal("2026-07-01", date(2026, 9, 30), RUN)
        self.assertEqual(self.rel(got, self.root), "out/personal/2026-07-01_2026-09-30_000-a1b2")
        self.assertEqual(RUN[-8:], "000-a1b2")

    def test_program_files(self):
        r = self.root
        self.assertEqual(self.p.config_dir(), r / "config")
        self.assertEqual(self.p.settings_registry(), r / "config" / "settings_registry.json")
        self.assertEqual(self.p.calendar_json(), r / "config" / "calendar.json")
        self.assertEqual(self.p.config_json(), r / "config" / "config.json")
        self.assertEqual(self.p.cli_script(), r / "lm27_cli.py")
        self.assertEqual(self.p.pipe_script(), r / "lm27_pipe.py")
        self.assertEqual(self.p.web_file("app/index.html"), r / "web" / "app" / "index.html")
        self.assertEqual(self.p.out_dir(), r / "out")

    def test_lad_paths(self):
        L = self.lad
        a = L / "agent"
        self.assertEqual(self.p.lad(), L)
        exp = {
            "agent_dir": a, "agent_json": a / "agent.json", "agent_config": a / "agent_config.json",
            "context_cache": a / "context_cache.json", "heartbeat": a / "heartbeat.json",
            "person_dir_delta": a / "person_dir_delta.json", "export_log": a / "export_log.jsonl",
            "agent_subkeys": a / "keys" / "subkeys.json", "agent_bin_root": a / "bin", "agent_run": a / "run",
            "stop_flag": a / "run" / "stop.flag", "harvest_now_flag": a / "run" / "harvest_now.flag",
            "harvest_done": a / "run" / "harvest_done.json", "harvest_lock": a / "run" / ".harvest.lock",
            "harvest_pid": a / "run" / "harvest.pid",
            "agent_logs": a / "logs", "copilot_manual": a / "copilot_manual", "store_root": a / "store",
            "edge_profile": L / "edge_copilot", "bridge_dir": L / "bridge", "edge_lock": L / "bridge" / "session.lock.json",
            "ui_dir": L / "ui", "ui_server_json": L / "ui" / "ui_server.json",
            "ui_start_error": L / "ui" / "ui_start_error.txt", "ui_logs": L / "ui" / "logs", "ui_jobs": L / "ui" / "jobs",
            "teamserver_default": L / "teamserver",
        }
        for m, want in exp.items():
            with self.subTest(m=m):
                self.assertEqual(getattr(self.p, m)(), want)
        self.assertEqual(self.p.agent_bin("0.1.0"), a / "bin" / "0.1.0")
        self.assertEqual(self.p.store_dir(PC), a / "store" / PC)
        self.assertEqual(self.p.raw_cursor(PC), a / "store" / PC / "raw_cursor.json")
        self.assertEqual(self.p.raw_cursor_lock(PC), a / "store" / PC / "raw_cursor.json.lock")
        self.assertEqual(self.p.exe_meta(PC), a / "store" / PC / "exe_meta.json")
        self.assertEqual(self.p.ui_job_file(JOB), L / "ui" / "jobs" / f"{JOB}.json")
        self.assertEqual(self.p.ui_job_stop_flag(JOB), L / "ui" / "jobs" / f"{JOB}.stop")          # W2 통합(협조형 취소)
        kst = timezone(timedelta(hours=9))
        self.assertEqual(self.p.ui_log_file(datetime(2026, 10, 6, 8, 0, tzinfo=kst)), L / "ui" / "logs" / "ui_20261005.log")
        with self.assertRaises(ValueError):
            self.p.ui_job_stop_flag("../x")
        self.assertEqual(self.p.agent_log_file("2026-10-05"), a / "logs" / "agent_20261005.log")

    def test_store_file_is_utc_write_date(self):
        a = self.lad / "agent" / "store"
        want = a / PC / "evidence" / "pc_session" / "pc.sampler" / "202610" / "20261005.jsonl.gz"
        self.assertEqual(self.p.store_file(PC, "pc_session", "pc.sampler", date(2026, 10, 5)), want)
        self.assertEqual(self.p.store_file(PC, "pc_session", "pc.sampler", "2026-10-05"), want)
        self.assertEqual(self.p.store_file(PC, "pc_session", "pc.sampler", "20261005"), want)
        # aware datetime 은 UTC 날짜로 — KST 10-06 08:00 = UTC 10-05 23:00
        kst = timezone(timedelta(hours=9))
        self.assertEqual(self.p.store_file(PC, "pc_session", "pc.sampler", datetime(2026, 10, 6, 8, 0, tzinfo=kst)), want)
        self.assertEqual(self.p.store_file(PC, "pc_session", "pc.sampler", datetime(2026, 10, 5, 23, 0, tzinfo=UTC)), want)
        self.assertEqual(self.p.store_file(PC, "mail", "manual", "2026-10-05").parts[-4:],
                         ("mail", "manual", "202610", "20261005.jsonl.gz"))

    def test_privacy_audit_file(self):
        want = self.lad / "agent" / "store" / "privacy_audit" / "202610" / "20261005.jsonl"
        self.assertEqual(self.p.privacy_audit_file("2026-10-05"), want)

    def test_v12_c19_and_w1_methods(self):
        """계약 v1.2 §0.7 C19 + W1 경로 CR(W1 통합 창): 브리지 상태 파일 6 · 오프라인 레지스트리 · outbox 파일 · AI 보존소
        폴더 · 번들 탐침 · 브리지 실행 파일 3 · 분석 time/hier 하위 — 모두 순수(폴더를 만들지 않음)·인자 검증."""
        d, b = self.root / "data", self.lad / "bridge"
        want = {
            self.p.bridge_profile(): b / "bridge_profile.json", self.p.bridge_profile_id(): b / "profile_id.txt",
            self.p.bridge_trace(): b / "trace.jsonl", self.p.bridge_probe_last(): b / "probe_last.json",
            self.p.bridge_rawcap(): b / "rawcap", self.p.bridge_diagnose(): b / "diagnose",
            self.p.outbox_file("pending", "lm27_team_bundle_x_0123456789ab.json"):
                d / "outbox" / "team" / "pending" / "lm27_team_bundle_x_0123456789ab.json",
            self.p.ai_store_dir(): d / "ai" / "store",
            self.p.bundle_probe("a1b2c3d4"): d / ".probe_a1b2c3d4",
            self.p.ai_journal(RUN, "task_label"): d / "ai" / "runs" / RUN / "task_label.jsonl",
            self.p.ai_result(RUN, "task_label"): d / "ai" / "runs" / RUN / "task_label.result.json",
            self.p.ai_capabilities(RUN): d / "ai" / "runs" / RUN / "capabilities.json",
            self.p.analysis_time(RUN): d / "derived" / "analysis" / RUN / "time",
            self.p.analysis_time_file(RUN, "env_slots.jsonl"): d / "derived" / "analysis" / RUN / "time" / "env_slots.jsonl",
            self.p.analysis_hier(RUN): d / "derived" / "analysis" / RUN / "hier",
            self.p.offline_registry(self.tmp): Path(self.tmp) / "lm27_registry.json",
        }
        for got, exp in want.items():
            self.assertEqual(got, exp)
        self.assertEqual(self.p.ai_store_dir(), self.p.ai_store("task_label").parent)
        for fn in (lambda: self.p.outbox_file("pending", "..\\x"), lambda: self.p.outbox_file("all", "a.json"),
                   lambda: self.p.bundle_probe("../x"), lambda: self.p.bundle_probe("XYZ"),
                   lambda: self.p.ai_journal(RUN, "../x"), lambda: self.p.ai_result("r1", "s"),
                   lambda: self.p.analysis_time_file(RUN, "..\\x"), lambda: self.p.analysis_hier("x"),
                   lambda: self.p.offline_registry(""), lambda: self.p.offline_registry(None)):
            self.assertRaises(ValueError, fn)
        self.assertEqual(os.listdir(self.tmp), [])


class ValidationTest(PathsCase):
    def test_bad_ids_rejected(self):
        bad = [
            lambda: self.p.pc_dir("PC_0123456789ABCDEF"), lambda: self.p.pc_dir("pc_0123"), lambda: self.p.pc_dir("..\\x"),
            lambda: self.p.pc_dir(None), lambda: self.p.seg_dir(PC, "../keys"), lambda: self.p.seg_dir(PC, "Mail"),
            lambda: self.p.ai_run("r1"), lambda: self.p.analysis("../../x"), lambda: self.p.outbox("all"),
            lambda: self.p.ai_store("../keys"), lambda: self.p.agent_bin(".."), lambda: self.p.agent_bin("a\\b"),
            lambda: self.p.store_file(PC, "pc_session", "pc/sampler", "2026-10-05"),
            lambda: self.p.store_file(PC, "pc_session", "pc.sampler", "2026-02-30"),
            lambda: self.p.store_file(PC, "pc_session", "pc.sampler", "어제"),
            lambda: self.p.local_only_file("..\\keys\\x.json"), lambda: self.p.local_only_file("a/b.json"),
            lambda: self.p.collect_script("..\\..\\x.ps1"), lambda: self.p.collect_script("C:\\x.ps1"),
            lambda: self.p.web_file("/etc/x"), lambda: self.p.ui_job_file("job1"),
            lambda: self.p.blanks_file(RUN, "mail.owa/../x"), lambda: self.p.out_personal("2026-07-01", "x", RUN),
        ]
        for i, fn in enumerate(bad):
            with self.subTest(i=i):
                self.assertRaises(ValueError, fn)

    def test_pure_no_filesystem_writes(self):
        for m in CONTRACT_METHODS:
            fn = getattr(self.p, m)
            try:
                fn()
            except TypeError:
                pass                        # 인자가 필요한 메서드 — 위 시험들이 따로 부른다
        self.p.store_file(PC, "pc_session", "pc.sampler", "2026-10-05")
        self.assertEqual(os.listdir(self.tmp), [])


class ModeTest(PathsCase):
    def test_default_root_is_package_parent(self):
        import lm27
        want = Path(os.path.dirname(os.path.dirname(os.path.abspath(lm27.__file__))))
        self.assertEqual(Paths().root, want)

    def test_mode_program_vs_agent(self):
        os.makedirs(self.root)
        self.assertEqual(self.p.mode(), "agent")
        fsx.atomic_write(self.root / "agent_main.py", b"")
        self.assertEqual(self.p.mode(), "agent")
        self.assertEqual(self.p.python_exe(), self.root / "py311" / "python.exe")
        self.assertEqual(self.p.collect_script("agent/agent.ps1"), self.root / "ps" / "agent.ps1")
        fsx.atomic_write(self.root / "lm27_cli.py", b"")
        self.assertEqual(self.p.mode(), "program")
        self.assertEqual(self.p.python_exe(), self.root / "python" / "python.exe")
        self.assertEqual(self.p.pythonw_exe(), self.root / "python" / "pythonw.exe")
        self.assertEqual(self.p.collect_script("agent/agent.ps1"), self.root / "collect" / "agent" / "agent.ps1")
        self.assertEqual(self.p.collect_script("Get-OfficeMru.ps1"), self.root / "collect" / "Get-OfficeMru.ps1")

    def test_mode_program_when_data_exists(self):
        os.makedirs(self.root / "data")
        self.assertEqual(self.p.mode(), "program")

    def test_lad_from_environment(self):
        fake = os.path.join(self.tmp, "LocalAppData")
        with mock.patch.dict(os.environ, {"LOCALAPPDATA": fake}):
            p = Paths(self.root)
            self.assertEqual(p.lad(), Path(fake) / "LoadMonitor27")
            self.assertEqual(p.agent_json(), Path(fake) / "LoadMonitor27" / "agent" / "agent.json")

    def test_lad_from_agent_copy_location_wp13_cr(self):
        """W1 통합 창(WP-13 CR): 에이전트 사본 ``…\\LoadMonitor27\\agent\\bin\\<ver>\\`` 에서는 LAD = 사본 위치(환경 변수 무관) —
        파이프와 감독 루프가 같은 LAD 를 쓴다. 프로그램 폴더 모드·다른 배치는 그대로 환경 변수."""
        lad = Path(self.tmp) / "LoadMonitor27"
        b = lad / "agent" / "bin" / "0.1.0-0123abcd"
        os.makedirs(b)
        with mock.patch.dict(os.environ, {"LOCALAPPDATA": os.path.join(self.tmp, "Other")}):
            p = Paths(b)
            self.assertEqual(p.mode(), "agent")
            self.assertEqual(p.lad(), lad)
            self.assertEqual(p.heartbeat().parent, lad / "agent")
            fsx.atomic_write(b / "lm27_cli.py", b"")                     # 프로그램 폴더 모양이면 환경 변수
            self.assertEqual(Paths(b).lad(), Path(self.tmp) / "Other" / "LoadMonitor27")
            self.assertEqual(Paths(b, lad=lad / "x").lad(), lad / "x")      # 명시 인자가 늘 이긴다

    def test_relative_root_is_absolutized(self):
        p = Paths(".")
        self.assertTrue(p.root.is_absolute())

    def test_repr(self):
        self.assertIn("Paths(", repr(self.p))


if __name__ == "__main__":
    unittest.main()
