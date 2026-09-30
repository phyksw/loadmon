"""Synthetic collection coverage/routing/union checks. Never runs collectors."""
from pathlib import Path
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "LoadMonitor25" / "core"))
from collection_state import load_status, merge_csv, merge_rows, read_csv, write_status
from communication import CommunicationCollection


class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="lm25-collection-routing-"))
        self.period = ("2026-09-01", "2026-09-30")
        self.calls, self.records = [], []

    def run_with(self, results=None, config=None, argv=None):
        results = results or {}
        def step(label, command, timeout):
            name = next(Path(x).name for x in command if str(x).endswith((".py", ".ps1")))
            self.calls.append((name, command, timeout))
            response = results.get(name)
            if response:
                source, state, extra, ok = response
                write_status(self.root, source, *self.period, state, scope="synthetic explicit scope", **extra)
                return ok
            return True
        return CommunicationCollection(self.root, config or {}, *self.period, step,
                                       lambda *args: self.records.append(args), argv=argv or [])

    def test_one_app_row_still_supplements_with_web(self):
        runner = self.run_with({"Get-TeamsWindow.ps1": ("teams_app", "partial", {"rows": 1}, True)})
        result = runner.teams()
        self.assertEqual([x[0] for x in self.calls], ["Get-TeamsWindow.ps1", "Get-TeamsWeb.py"])
        self.assertEqual(result["status"], "partial")

    def test_only_successful_scoped_graph_completion_stops_web(self):
        for process_ok in (True, False):
            self.calls.clear()
            runner = self.run_with({"Get-TeamsChats.py": ("teams_graph", "complete", {}, process_ok)},
                                   {"graph": {"clientId": "synthetic"}, "preferApp": False})
            result = runner.teams()
            names = [x[0] for x in self.calls]
            self.assertEqual("Get-TeamsWeb.py" in names, not process_ok)
            self.assertEqual(result["status"], "complete" if process_ok else "partial")

    def test_fresh_empty_csv_does_not_certify_mail_coverage(self):
        folder = self.root / "data" / "outlook"
        folder.mkdir(parents=True)
        (folder / "mail.csv").write_text("time,subject\n", "utf-8")
        result = self.run_with().mail(time.time() - 1)
        self.assertEqual([x[0] for x in self.calls], ["Get-OutlookIndex.ps1", "Get-OutlookWeb.py", "Get-MailViaCopilot.py"])
        self.assertEqual(result["status"], "partial")

    def test_zero_rows_with_proven_com_scope_can_be_complete(self):
        write_status(self.root, "outlook_com", *self.period, "complete", scope="default store",
                     mail_status="complete", calendar_status="complete")
        self.assertEqual(self.run_with().mail(time.time() - 1)["status"], "complete")
        self.assertFalse(self.calls)

    def test_interrupted_com_checkpoint_cannot_stop_supplements(self):
        write_status(self.root, "outlook_com", *self.period, "complete", scope="default store",
                     mail_status="complete", calendar_status="complete")
        self.assertEqual(self.run_with().mail(time.time() - 1, process_ok=False)["status"], "partial")
        self.assertEqual(len(self.calls), 3)

    def test_mail_and_calendar_are_supplemented_separately(self):
        write_status(self.root, "outlook_com", *self.period, "partial", scope="default store",
                     mail_status="complete", calendar_status="partial")
        self.run_with().mail(time.time() - 1)
        self.assertTrue(all(command[-1] == "cal" for _, command, _ in self.calls))

    def test_failed_process_cannot_claim_calendar_complete(self):
        response = ("outlook_index", "complete", {"mail_status": "complete", "calendar_status": "complete"}, False)
        result = self.run_with({"Get-OutlookIndex.ps1": response}).mail(time.time() - 1)
        self.assertEqual(len(self.calls), 3)
        self.assertEqual(result["status"], "partial")

    def test_stale_or_other_period_manifest_is_not_current_evidence(self):
        write_status(self.root, "outlook_com", "2026-08-01", "2026-08-31", "complete", scope="default store",
                     mail_status="complete", calendar_status="complete")
        self.assertIsNone(load_status(self.root, "outlook_com", *self.period))
        write_status(self.root, "outlook_com", *self.period, "complete", scope="default store",
                     mail_status="complete", calendar_status="complete")
        self.run_with().mail(time.time() + 100)
        self.assertEqual(len(self.calls), 3)

    def test_headless_collection_omits_web_and_copilot(self):
        runner = self.run_with(config={"teamsViaCopilot": True}, argv=["--collect-only"])
        runner.teams()
        runner.mail(time.time())
        self.assertEqual([x[0] for x in self.calls], ["Get-TeamsWindow.ps1", "Get-OutlookIndex.ps1"])

    def test_no_teams_invokes_no_collector(self):
        self.assertEqual(self.run_with(argv=["--no-teams"]).teams()["status"], "skipped")
        self.assertFalse(self.calls)


class UnionTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="lm25-collection-union-"))
        self.row = {"time": "2026-09-01 09:00:00", "sender": "synthetic", "box": "inbox", "subject": "Task", "conversation": "Task"}

    def test_narrower_retry_retains_previous_days_and_upgrades_legacy(self):
        path = self.root / "mail.csv"
        merge_csv(path, [self.row], self.row)
        richer = dict(self.row, source_id="mail-1", context_excerpt="Full task context", source_kind="outlook_com")
        next_day = dict(richer, time="2026-09-02 09:00:00", source_id="mail-2")
        merge_csv(path, [richer, next_day], self.row)
        merge_csv(path, [next_day], self.row)
        rows = read_csv(path)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["context_excerpt"], "Full task context")

    def test_distinct_source_ids_and_accounts_are_not_weakly_merged(self):
        rows = [dict(self.row, source_id="one"), dict(self.row, source_id="two"),
                dict(self.row, source_id="one", account="other")]
        self.assertEqual(len(merge_rows([], rows)), 3)

    def test_same_chat_summary_on_different_days_is_retained(self):
        row = dict(time="2026-09-01 09:00", chat="Room", summary="Repeat", **{"from": "A"})
        rows = merge_rows([row], [dict(row, time="2026-09-02 09:00")], "teams")
        self.assertEqual(len(rows), 2)

    def test_same_display_name_different_conversation_is_not_merged(self):
        row = dict(time="2026-09-01 09:00", chat="Room", summary="Repeat", conversation_id="A", source_id="A/1", **{"from": "A"})
        rows = merge_rows([row], [dict(row, source_id="", conversation_id="B")], "teams")
        self.assertEqual(len(rows), 2)

    def test_shorter_context_or_date_only_observation_cannot_degrade_record(self):
        row = dict(self.row, source_id="one", context_excerpt="Complete task context", context_truncated="false", time_precision="exact")
        weak = dict(row, time="2026-09-01", time_precision="date", context_excerpt="Complete", context_truncated="true")
        result = merge_rows([row], [weak])[0]
        self.assertEqual(result["context_excerpt"], row["context_excerpt"])
        self.assertEqual(result["time"], row["time"])
        self.assertEqual(result["context_truncated"], "false")

    def test_bad_csv_is_not_replaced(self):
        path = self.root / "bad.csv"
        before = "time,subject\na,b,c\n"
        path.write_text(before, "utf-8")
        with self.assertRaises(ValueError):
            merge_csv(path, [self.row], self.row)
        self.assertEqual(path.read_text("utf-8"), before)

    def test_ai_timestamp_cannot_downgrade_precise_observation(self):
        row = dict(self.row, source_id="one", time_precision="minute", source_kind="outlook_com")
        for precision in ("ai_reported", "unknown", "estimated"):
            result = merge_rows([row], [dict(row, time_precision=precision, source_kind="outlook_copilot")])[0]
            self.assertEqual(result["time_precision"], "minute")
            self.assertEqual(result["source_kind"], "outlook_com")


if __name__ == "__main__":
    unittest.main()
