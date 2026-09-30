"""Failure isolation across collection routes; only synthetic TEMP state is used."""
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest import mock

import test_collection_ui as page_harness
import test_additional_pc_collection as runner_harness

CORE = Path(__file__).resolve().parents[1] / "LoadMonitor25/core"
sys.path.insert(0, str(CORE))
import communication as C  # noqa: E402
import collection_diagnostics as D  # noqa: E402
from collection_state import write_status  # noqa: E402


class OrchestrationReviewTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="lm25-orchestration-review-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.period = ("2026-09-01", "2026-09-30")
        self.calls, self.records = [], []
        self.started = time.time()

    def runner(self, config=None, result=None):
        def step(label, command, timeout):
            name = next(Path(x).name for x in command if str(x).endswith((".py", ".ps1")))
            self.calls.append(name)
            if result:
                result(name)
            return True
        return C.CommunicationCollection(self.root, config or {}, *self.period, step,
            lambda *args: self.records.append(args), argv=["--no-mail-copilot", "--no-teams-copilot"])

    def test_locked_graph_skip_status_does_not_prevent_mail_web_or_teams(self):
        original = C.write_status
        def locked(root, source, *args, **kwargs):
            if source in {"outlook_graph", "teams_graph"}:
                raise PermissionError("synthetic status file locked")
            return original(root, source, *args, **kwargs)
        with mock.patch.object(C, "write_status", side_effect=locked):
            mail = self.runner().mail(self.started)
            teams = self.runner().teams()
        self.assertIn("Get-OutlookWeb.py", self.calls)
        self.assertIn("Get-TeamsWeb.py", self.calls)
        self.assertEqual((mail["status"], teams["status"]), ("partial", "partial"))
        self.assertTrue(any(not row[1] and "저장" in row[0] for row in self.records))

    def test_unwritable_status_directory_keeps_all_available_routes_running(self):
        with mock.patch.object(C, "write_status", side_effect=PermissionError("synthetic")):
            result = self.runner().mail(self.started)
        self.assertEqual(self.calls, ["Get-OutlookIndex.ps1", "Get-OutlookWeb.py"])
        self.assertEqual(result["status"], "partial")
        self.assertTrue(all("status_write_failed" in s["reasons"] for s in result["sources"]))

    def test_unpersisted_graph_completion_cannot_suppress_supplements(self):
        def report(name):
            if name == "Get-TeamsChats.py":
                write_status(self.root, "teams_graph", *self.period, "complete", scope="synthetic chats",
                             full_requested_scope_complete=True)
        with mock.patch.object(C, "write_status", side_effect=PermissionError("synthetic")):
            result = self.runner({"graph": {"clientId": "synthetic"}}, report).teams()
        self.assertIn("Get-TeamsWeb.py", self.calls)
        self.assertEqual(result["status"], "partial")

    def test_failed_interrupted_status_write_keeps_calendar_pending(self):
        write_status(self.root, "outlook_com", *self.period, "complete", scope="synthetic local store",
                     mail_status="complete", calendar_status="complete")
        with mock.patch.object(C, "write_status", side_effect=PermissionError("synthetic")):
            result = self.runner().mail(self.started, process_ok=False)
        self.assertIn("Get-OutlookWeb.py", self.calls)
        self.assertEqual(result["sources"][0]["calendar_status"], "partial")

    def test_diagnostics_uses_current_in_memory_failure_instead_of_old_complete_file(self):
        write_status(self.root, "teams_graph", *self.period, "complete", scope="synthetic old record")
        run = {"started_at": time.time(), "collection": {"teams": {"sources": [{
            "source": "teams_graph", "status": "partial", "requested_from": self.period[0],
            "requested_to": self.period[1], "finished_at": time.time(), "rows": 3,
            "reasons": ["status_write_failed", "SECRET_BODY"], "account": "SECRET_ACCOUNT"}]}}}
        result = D.build_diagnostics(self.root, *self.period, run)
        route = next(row for row in result["routes"] if row["source"] == "teams_graph")
        self.assertTrue(route["current_run"])
        self.assertEqual(route["status"], "partial")
        self.assertIn("status_write_failed", route["causes"])
        self.assertIn("저장", " ".join(result["summary"]))
        self.assertNotIn("SECRET", json.dumps(result))

    def test_unknown_failed_route_is_visible_without_exposing_raw_exception(self):
        write_status(self.root, "teams_web", *self.period, "failed", reasons=["SECRET_OTHER_ERROR"])
        result = D.build_diagnostics(self.root, *self.period, {"started_at": self.started})
        self.assertIn("추가 확인", " ".join(result["summary"]))
        self.assertNotIn("SECRET", json.dumps(result))

    def test_ui_distinguishes_pending_dates_from_zero_period_records(self):
        page_harness.CollectionUiTests.setUpClass()
        page = page_harness.CollectionUiTests()
        page.run_js(r'''
context.renderCommunicationEvidence({families:{mail:{unique_rows:0,context_rows:0,pending_rows:7},
 teams:{unique_rows:2,context_rows:1,pending_rows:3,pending_unreadable_files:1}}});
const shown=byId.communicationevidence.innerHTML;
assert.match(shown,/날짜 미확정·별도 보류/);
assert.match(shown,/<td>0건<\/td><td>0건<\/td><td>7건/);
assert.match(shown,/<td>2건<\/td><td>1건<\/td><td>3건/);
assert.match(shown,/보류 자료 읽기 실패 1파일/);
assert.match(shown,/AI 분석에 포함하지 않습니다/);
''')

    def test_pending_files_reach_finish_message_without_becoming_period_evidence(self):
        from collection_state import write_csv
        from communication_evidence import write_report
        fixture = runner_harness.AdditionalPcCollectionTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        folder = fixture.root / "data/collection_pending"
        fields = ["time", "source_id", "time_precision", "requested_from", "requested_to", "subject"]
        for name, count in (("outlook_web_undated.csv", 7), ("teams_web_undated.csv", 3)):
            write_csv(folder / name, [{"time": "", "source_id": str(i), "time_precision": "unknown",
                "requested_from": self.period[0], "requested_to": self.period[1], "subject": "Synthetic pending"}
                for i in range(count)], fields)
        def process(command, **kwargs):
            write_report(fixture.root, *self.period)
            return fixture.process(command, **kwargs)
        fixture.env["subprocess"].Popen = process
        fixture.env["run_job"](*self.period, False, False, collect_only=True)
        message = fixture.env["JOB"]["run_result"]["message"]
        self.assertIn("메일 0건 / 본문 발췌 0건 / 날짜 미확정 별도 보류 7건", message)
        self.assertIn("Teams 0건 / 본문 발췌 0건 / 날짜 미확정 별도 보류 3건", message)


if __name__ == "__main__":
    unittest.main()
