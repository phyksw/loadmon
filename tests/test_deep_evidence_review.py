"""Deep evidence audit: copied code and synthetic TEMP records, no live services.

Result contracts cover independently reproduced audit findings and safeguards.
"""
import csv
from datetime import date, datetime
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock


APP = Path(__file__).resolve().parents[1] / "LoadMonitor25"
DAY = date(2026, 9, 7)


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DeepEvidenceReviewTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="lm25-deep-evidence-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "core").mkdir()
        (self.root / "config").mkdir()
        for path in (APP / "core").glob("*.py"):
            shutil.copyfile(path, self.root / "core" / path.name)
        self.cfg = json.loads((APP / "config/config.default.json").read_text("utf-8-sig"))
        self.cfg.update(owner="Synthetic", teamsSelfNames=["Synthetic"], projects=[])
        (self.root / "config/config.json").write_text(json.dumps(self.cfg), "utf-8")
        self.state = load_module("deep_state", self.root / "core/collection_state.py")
        context = load_module("deep_context", self.root / "core/communication_context.py")
        with mock.patch.dict(sys.modules, {"collection_state": self.state, "communication_context": context}):
            self.extract = load_module("deep_extract", self.root / "core/extract.py")
            self.evidence = load_module("deep_evidence", self.root / "core/communication_evidence.py")

    def write(self, path, rows):
        destination = self.root / "data" / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        fields = list(dict.fromkeys(key for row in rows for key in row))
        with destination.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    def signals(self):
        return self.extract.load_signals(str(self.root / "data"), DAY, DAY,
                                         exclude=self.cfg["excludePathKeywords"], cfg=self.cfg)

    @staticmethod
    def mail(**changes):
        return {"box": "inbox", "time": "2026-09-07 10:00:10", "sender": "Person A",
                "subject": "Design decision", "conversation": "Design decision", "rcv": "to", **changes}

    @staticmethod
    def teams(**changes):
        return {"time": "2026-09-07 10:00:10", "from": "Synthetic", "chat": "Design room",
                "kind": "sent", "summary": "Design decision", "account": "synthetic-account",
                "conversation_id": "chat-1", "source_id": "graph:chat-1/message-1",
                "source_kind": "teams_graph", "time_precision": "second", **changes}

    def test_exact_identity_keeps_different_accounts_and_rejects_outside_period(self):
        first = self.teams(context_excerpt="Account A decision")
        second = dict(first, account="another-account", context_excerpt="Account B decision")
        outside = dict(first, time="2026-09-06 10:00:10", context_excerpt="OUTSIDE_PERIOD")
        self.write("m365/teams_graph.csv", [outside, first, second])
        signals, metadata = self.signals()
        self.assertEqual(len(signals), 2)
        self.assertEqual({row["context_excerpt"] for row in metadata["signal_contexts"]},
                         {"Account A decision", "Account B decision"})

    def test_old_pc_graph_snapshot_must_not_replace_newer_edited_body(self):
        current = self.teams(context_excerpt="CURRENT_APPROVED", modified_time="2026-09-07T09:00:00Z")
        old = self.teams(context_excerpt="OLD_REJECTED_DRAFT " * 30, modified_time="2026-09-06T09:00:00Z")
        self.write("m365/teams_graph.csv", [current])
        self.write("추가PC/PC-B/m365/teams_graph.csv", [old])
        signals, metadata = self.signals()
        self.assertEqual(len(signals), 1)
        self.assertEqual(metadata["signal_contexts"][0]["context_excerpt"], "CURRENT_APPROVED")
        self.assertEqual(metadata["signal_contexts"][0]["modified_time"], current["modified_time"])

    def test_latest_confirmed_empty_body_cannot_be_restored_by_older_pc(self):
        for family in ("mail", "teams"):
            with self.subTest(family=family):
                raw = self.mail(source_id="outlook-graph:message-1", account="synthetic-account",
                                source_kind="outlook_graph") if family == "mail" else self.teams()
                current = dict(raw, context_excerpt="", context_available="true",
                               modified_time="2026-09-07T09:00:00Z")
                old = dict(raw, context_excerpt="OLD_REJECTED_DRAFT", context_available="true",
                           modified_time="2026-09-06T09:00:00Z")
                suffix = "outlook/mail.csv" if family == "mail" else "m365/teams_graph.csv"
                self.write(suffix, [current])
                self.write("추가PC/PC-B/" + suffix, [old])
                _, metadata = self.signals()
                context = next(row for row in metadata["signal_contexts"] if row["source_id"] == raw["source_id"])
                self.assertEqual(context["context_excerpt"], "")
                report = self.evidence.build_report(self.root, DAY, DAY, self.cfg)["families"][family]
                self.assertEqual((report["unique_rows"], report["context_rows"]), (1, 0))

    def test_latest_revision_applies_before_period_and_body_privacy_checks(self):
        old = self.teams(context_excerpt="OLDER_SAFE_BODY", modified_time="2026-09-06T09:00:00Z")
        for changes in ({"time": "2026-09-08 10:00:10", "context_excerpt": "NEXT_DAY_BODY"},
                        {"summary": "개인 일정", "context_excerpt": "PRIVATE_TITLE_BODY"}):
            current = dict(old, modified_time="2026-09-07T09:00:00Z", **changes)
            self.write("m365/teams_graph.csv", [current])
            self.write("추가PC/PC-B/m365/teams_graph.csv", [old])
            self.assertEqual(self.signals()[0], [])
        current = dict(old, modified_time="2026-09-07T09:00:00Z", context_excerpt="PRIVATE_BODY 개인정보 처리 안내")
        self.write("m365/teams_graph.csv", [current])
        signals, metadata = self.signals()
        self.assertEqual(len(signals), 1)
        self.assertEqual(metadata["signal_contexts"][0]["context_excerpt"], "")
        self.assertEqual(metadata["signal_contexts"][0]["context_filtered"], "true")

    def test_missing_body_retry_keeps_last_body_version_across_pc(self):
        current = self.teams(context_excerpt="CURRENT", modified_time="2026-09-07T09:00:00Z")
        old = self.teams(context_excerpt="OLDER_LONG_BODY " * 30, modified_time="2026-09-06T09:00:00Z")
        missing = dict(current, context_excerpt="", context_available="false", modified_time="2026-09-08T09:00:00Z")
        stored = self.state.merge_rows([current], [missing], "teams")
        self.write("m365/teams_graph.csv", stored)
        self.write("추가PC/PC-B/m365/teams_graph.csv", [old, missing])
        signals, metadata = self.signals()
        self.assertEqual(len(signals), 1)
        self.assertEqual(metadata["signal_contexts"][0]["context_excerpt"], "CURRENT")

    def test_distinct_legacy_mail_senders_same_minute_are_not_one_message(self):
        self.write("outlook/mail.csv", [self.mail(), self.mail(sender="Person B", time="2026-09-07 10:00:40")])
        signals, _ = self.signals()
        self.assertEqual(len(signals), 2)

    def test_legacy_distinct_seconds_title_tails_accounts_and_exact_copies(self):
        first = self.mail(subject="Shared prefix " * 5 + "decision A", conversation="Shared conversation")
        rows = [first, dict(first, time="2026-09-07 10:00:40"),
                dict(first, subject="Shared prefix " * 5 + "decision B"), dict(first, account="another-account")]
        self.write("outlook/mail.csv", rows)
        self.write("추가PC/PC-B/outlook/mail.csv", rows)
        self.assertEqual(len(self.signals()[0]), 4)

    def test_ambiguous_date_only_supplement_is_not_assumed_to_be_a_precise_message(self):
        self.write("outlook/mail.csv", [self.mail(), self.mail(time="2026-09-07 11:00:10"),
                                       self.mail(time="2026-09-07", time_precision="date")])
        self.assertEqual(len(self.signals()[0]), 3)

    def test_unknown_time_context_does_not_open_pc_floor_or_session(self):
        rows = [self.teams(source_id=f"unknown-{index}", time_precision=precision)
                for index, precision in enumerate(("unknown", "estimated", "ai_reported", "date"))]
        self.write("m365/teams_graph.csv", rows)
        self.write("pc/pc_on.csv", [{"date": str(DAY), "on_hours": 10, "first_on": "09:00",
                                     "last_off": "20:00", "night_hours": 1, "weekend": 0}])
        signals, metadata = self.signals()
        hours, info = self.extract.day_work_hours(str(self.root / "data"), signals, DAY, DAY,
                                                  self.cfg, now=datetime(2026, 9, 8),
                                                  file_times=metadata["file_times"])
        self.assertEqual(sum(hours.values()), 0)
        self.assertEqual(info["unverified_time_signals"], 4)

    def test_protected_body_never_reenters_ai_excerpt_from_extra_pc(self):
        allowed = self.teams(context_excerpt="SAFE_CONTEXT")
        filtered = dict(allowed, context_excerpt="PRIVATE_PROTECTED_CONTENT " * 30, context_filtered="true")
        self.write("m365/teams_graph.csv", [allowed])
        self.write("추가PC/PC-B/m365/teams_graph.csv", [filtered])
        _, metadata = self.signals()
        context = metadata["signal_contexts"][0]
        self.assertEqual(context["context_excerpt"], "SAFE_CONTEXT")
        row = {"source": "팀즈(발신)", "text": "Design decision", **context}
        self.assertNotIn("PRIVATE_PROTECTED", self.extract.context_preview(row))
        self.assertNotIn("PRIVATE_PROTECTED", self.evidence.evidence_line(row))

    def test_store_merge_preserves_missing_body_but_accepts_verified_empty_edit(self):
        current = self.teams(context_excerpt="OLD_BODY", modified_time="2026-09-06T09:00:00Z")
        missing = dict(current, context_excerpt="", context_available="false", modified_time="2026-09-07T09:00:00Z")
        empty = dict(missing, context_available="true")
        self.assertEqual(self.state.merge_rows([current], [missing], "teams")[0]["context_excerpt"], "OLD_BODY")
        self.assertEqual(self.state.merge_rows([current], [empty], "teams")[0]["context_excerpt"], "")

    def test_verified_empty_graph_message_clears_old_summary_and_analysis_signal(self):
        current = self.teams(context_excerpt="OLD_INSTRUCTION", summary="OLD_INSTRUCTION",
                             modified_time="2026-09-06T09:00:00Z")
        missing = dict(current, context_excerpt="", summary="", context_available="false", modified_time="2026-09-07T09:00:00Z")
        self.assertEqual(self.state.merge_rows([current], [missing], "teams")[0]["summary"], "OLD_INSTRUCTION")
        empty = dict(missing, context_available="true")
        stored = self.state.merge_rows([current], [empty], "teams")
        self.assertEqual(stored[0]["summary"], "")
        self.write("m365/teams_graph.csv", stored)
        self.write("추가PC/PC-B/m365/teams_graph.csv", [current])
        self.assertEqual(self.signals()[0], [])

    def test_readiness_never_labels_ai_report_as_verified_fact(self):
        row = {"source": "팀즈(발신·시각미확인)", "source_kind": "teams_copilot",
               "time_precision": "ai_reported", "context_excerpt": "An AI generated completion summary"}
        readiness = self.evidence.unit_readiness([row])
        self.assertFalse(readiness["allows_interpretation"])
        self.assertFalse(readiness["fact_verified"])
        direct = self.evidence.unit_readiness([dict(row, source_kind="teams_graph", time_precision="second")])
        self.assertTrue(direct["allows_interpretation"])
        self.assertFalse(direct["fact_verified"])

    def test_teams_saved_evidence_period_matches_configured_analysis_offset(self):
        self.cfg["mm"]["mailTimeOffsetH"] = 9
        self.write("m365/teams_graph.csv", [self.teams(time="2026-09-06 19:00:00")])
        signals, _ = self.signals()
        self.assertEqual(len(signals), 1)
        report = self.evidence.build_report(self.root, DAY, DAY, self.cfg)
        self.assertEqual(report["families"]["teams"]["unique_rows"], 1)

    def test_locked_current_run_status_cannot_redisplay_old_scope_completion(self):
        self.state.write_status(self.root, "teams_graph", DAY, DAY, status="complete", scope="Synthetic original scope")
        with mock.patch.dict(sys.modules, {"collection_state": self.state}):
            communication = load_module("deep_communication", self.root / "core/communication.py")
            diagnostics = load_module("deep_diagnostics", self.root / "core/collection_diagnostics.py")
        started = time.time()
        runner = communication.CommunicationCollection(self.root, {"graph": {"clientId": "synthetic"}}, DAY, DAY,
            lambda *_args: False, lambda *_args: None, argv=["--no-teams-copilot"])
        with mock.patch.object(communication, "write_status", side_effect=PermissionError("synthetic lock")):
            result = runner.teams()
        run = {"started_at": started, "period": [str(DAY), str(DAY)], "collection": {"teams": result}}
        report_dir = self.root / "report"
        report_dir.mkdir()
        (report_dir / "last_run.json").write_text(json.dumps(run), encoding="utf-8")
        diagnosis = diagnostics.build_diagnostics(self.root, str(DAY), str(DAY), run)
        graph = next(row for row in diagnosis["routes"] if row["source"] == "teams_graph")
        self.assertNotEqual(graph["status"], "complete")
        self.assertNotEqual(self.evidence.build_report(self.root, DAY, DAY, self.cfg)["families"]["teams"]["scope_status"], "scoped_complete")
        self.assertNotEqual(self.evidence.write_report(self.root, DAY, DAY, self.cfg, current_run=run)["families"]["teams"]["scope_status"], "scoped_complete")

    def test_current_scope_requires_same_period_valid_run_time_and_newest_receipt(self):
        disk = self.state.write_status(self.root, "teams_graph", DAY, DAY, status="complete", scope="Synthetic scope")
        state = dict(disk, status="failed", finished_at=disk["finished_at"] + 2)
        valid = {"period": [str(DAY), str(DAY)], "started_at": disk["finished_at"] + 1,
                 "collection": {"teams": {"sources": [state]}}}
        def coverage(run):
            return self.evidence.build_report(self.root, DAY, DAY, self.cfg, current_run=run)["families"]["teams"]["scope_status"]
        self.assertEqual(coverage(valid), "partial")
        for invalid in ({**valid, "period": ["2026-08-01", "2026-08-31"]},
                        {**valid, "started_at": float("nan")}, {**valid, "started_at": state["finished_at"] + 1},
                        {**valid, "collection": {"teams": {"sources": None}}},
                        {**valid, "collection": {"teams": {"sources": [dict(state, source=[])]}}},
                        {**valid, "collection": {"teams": {"sources": [dict(state, finished_at=float("nan"))]}}}):
            self.assertEqual(coverage(invalid), "scoped_complete")
        newer = dict(disk, finished_at=state["finished_at"] + 1)
        status_file = self.root / "data/collection_status/teams_graph.json"
        status_file.write_text(json.dumps(newer), encoding="utf-8")
        self.assertEqual(coverage(valid), "scoped_complete")
        status_file.write_text(json.dumps(dict(newer, requested_from="2026-08-01")), encoding="utf-8")
        self.assertEqual(coverage(valid), "partial")

    def test_pending_originals_are_period_scoped_deduplicated_and_never_ai_evidence(self):
        for family, filename in (("mail", "outlook_web_undated.csv"), ("teams", "teams_web_undated.csv")):
            raw = self.mail() if family == "mail" else self.teams()
            pending = dict(raw, time="", time_precision="unknown", requested_from=str(DAY), requested_to=str(DAY),
                           account="synthetic-account", source_id="pending-original-1",
                           context_excerpt="PENDING_PRIVATE_BODY_DO_NOT_ANALYZE")
            self.write("collection_pending/" + filename, [pending,
                dict(pending, source_id="another-period", requested_from="2026-08-01"),
                dict(pending, source_id="resolved", time="2026-09-07 10:00:00", time_precision="second"),
                dict(pending, source_id="estimated", time_precision="estimated")])
            self.write("추가PC/PC-B/collection_pending/" + filename,
                       [dict(pending, account="SYNTHETIC-ACCOUNT"), dict(pending, account="another-account")])
        report = self.evidence.build_report(self.root, DAY, DAY, self.cfg)
        for item in report["families"].values():
            self.assertEqual(item["pending_rows"], 2)
            self.assertEqual(item["pending_unreadable_files"], 0)
            for field in ("raw_rows", "unique_rows", "in_period_rows", "context_rows", "dated_rows", "unknown_date_rows"):
                self.assertEqual(item[field], 0, field)
            self.assertEqual(item["status"], "unavailable")
        self.assertNotIn("PENDING_PRIVATE_BODY", json.dumps(report))
        self.assertNotIn("pending-original-1", json.dumps(report))
        self.assertNotIn("PENDING_PRIVATE_BODY", self.evidence.prompt_notice(report))
        self.assertEqual(self.signals()[0], [])

    def test_unreadable_pending_file_is_separate_from_known_saved_evidence(self):
        self.write("outlook/mail.csv", [self.mail(context_excerpt="KNOWN_DATED_BODY")])
        self.write("collection_pending/outlook_web_undated.csv", [dict(self.mail(), time="", time_precision="unknown",
                   requested_from=str(DAY), requested_to=str(DAY), source_id="pending-1")])
        bad_path = self.root / "data/추가PC/PC-B/collection_pending/outlook_web_undated.csv"
        bad_path.parent.mkdir(parents=True)
        bad_path.write_text("time,time_precision,requested_from,requested_to\n,unknown,2026-09-07,2026-09-07,UNEXPECTED_COLUMN\n", encoding="utf-8")
        report = self.evidence.build_report(self.root, DAY, DAY, self.cfg)["families"]["mail"]
        self.assertEqual((report["pending_rows"], report["pending_unreadable_files"]), (1, 1))
        self.assertEqual((report["raw_rows"], report["unique_rows"], report["context_rows"], report["unreadable_files"]), (1, 1, 1, 0))
        self.assertEqual(len(self.signals()[0]), 1)

    def test_pending_copy_only_resolves_with_exact_scoped_id_and_precise_original(self):
        for family, filename in (("mail", "outlook_web_undated.csv"), ("teams", "teams_web_undated.csv")):
            raw = self.mail() if family == "mail" else self.teams()
            pending = dict(raw, time="", time_precision="unknown", requested_from=str(DAY), requested_to=str(DAY),
                           source_id="observed-original", source_kind="outlook_web" if family == "mail" else "teams_web",
                           account="synthetic-account", conversation_id="room-1")
            self.write("추가PC/PC-B/collection_pending/" + filename, [pending])
            suffix = "outlook/mail.csv" if family == "mail" else "m365/teams_web.csv"
            precise = dict(pending, time="2026-09-06 10:00:00", time_precision="minute")
            for unproven in (dict(precise, source_id=""), dict(precise, source_id="different-original"),
                             dict(precise, account="another-account"), dict(precise, conversation_id="another-room"),
                             dict(precise, source_kind="another-route"), dict(precise, time_precision="estimated"),
                             dict(precise, time_precision="unknown"), dict(precise, time_precision="date"),
                             dict(precise, time_precision="minute", time="2026-09-06")):
                self.write(suffix, [unproven])
                report = self.evidence.build_report(self.root, DAY, DAY, self.cfg)["families"][family]
                self.assertEqual(report["pending_rows"], 1, unproven)
            # Once the exact original is dated, even an out-of-period original
            # resolves the pending question; it does not become in-period data.
            self.write(suffix, [precise])
            report = self.evidence.build_report(self.root, DAY, DAY, self.cfg)["families"][family]
            self.assertEqual((report["pending_rows"], report["unique_rows"]), (0, 0))


if __name__ == "__main__":
    unittest.main()
