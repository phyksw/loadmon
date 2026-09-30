"""Full-text/excerpt contracts using copied code and synthetic TEMP evidence."""
from datetime import date, datetime
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest import mock


APP = Path(__file__).resolve().parents[1] / "LoadMonitor25"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CommunicationContextTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="lm25-body-context-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "core").mkdir()
        for name in ("collection_state", "communication_archive", "communication_context", "communication_evidence", "extract"):
            shutil.copyfile(APP / "core" / (name + ".py"), self.root / "core" / (name + ".py"))
        self.context = load("synthetic_context", self.root / "core/communication_context.py")
        self.state = load("synthetic_state", self.root / "core/collection_state.py")
        with mock.patch.dict(sys.modules, {"collection_state": self.state, "communication_context": self.context}):
            self.archive = load("synthetic_archive", self.root / "core/communication_archive.py")
            self.extract = load("synthetic_extract", self.root / "core/extract.py")
            self.evidence = load("synthetic_evidence", self.root / "core/communication_evidence.py")

    @staticmethod
    def long_body():
        return "BEGIN_DECISION " + "A" * 12000 + " MIDDLE_ACTION " + "B" * 12000 + " FINAL_RESULT"

    def originals(self):
        return [json.loads(path.read_text("utf-8")) for path in (self.root / "data/communication_originals").rglob("*.json")]

    def test_short_excerpt_normalizes_spaces_without_summarizing(self):
        self.assertEqual(self.context.make_excerpt("원문 첫줄\n\t둘째줄", 50), "원문 첫줄 둘째줄")
        self.assertEqual(self.context.make_excerpt("", 50), "")

    def test_long_excerpt_and_ai_excerpt_keep_beginning_middle_end(self):
        text = self.long_body()
        excerpt = self.context.make_excerpt(text, 4000)
        smaller = self.context.make_excerpt(excerpt, 800)
        for limit, value in ((4000, excerpt), (800, smaller)):
            self.assertLessEqual(len(value), limit)
            for token in ("BEGIN_DECISION", "MIDDLE_ACTION", "FINAL_RESULT"):
                self.assertIn(token, value)
            self.assertEqual(value.count(self.context.OMISSION), 2)
        self.assertEqual(smaller, self.context.make_excerpt(excerpt, 800))

    def test_every_small_budget_obeys_limit_without_negative_slice_leak(self):
        for limit in range(65):
            self.assertLessEqual(len(self.context.make_excerpt(self.long_body(), limit)), limit)
        self.assertEqual(self.context.make_excerpt("ABC", -1), "")

    def test_privacy_checks_the_full_body_with_existing_word_boundary_policy(self):
        secret_body = "START " + "A" * 4000 + " PRIVATE " + "B" * 16000 + " END"
        self.assertNotIn("PRIVATE", self.context.make_excerpt(secret_body, 4000))
        self.assertTrue(self.context.body_is_filtered(secret_body, ["private"]))
        self.assertFalse(self.context.body_is_filtered("PRIVATEly templating downloads 임시", ["private", "temp", "downloads", "임시"]))
        self.assertTrue(self.context.body_is_filtered("본문의 개인자료 포함", ["개인"]))
        self.assertTrue(self.context.body_is_filtered("부호(secret)", ["secret"]))
        self.assertFalse(self.context.body_is_filtered("secretary", ["secret"]))

    def test_full_body_archive_preserves_layout_and_capture_limits(self):
        body = "FIRST\n" + self.long_body() + "\nLAST"
        row = {"body": body, "source_id": "web-original", "source_kind": "teams_web", "body_capture_status": "partial",
               "body_truncated": True, "capture_method": "web_dom", "capture_limit": 300000,
               "capture_scope": "rendered_message", "full_body_chars": 1, "cookie": "DO_NOT_STORE"}
        self.assertEqual(self.archive.archive_records(self.root, "teams", [row]), 1)
        saved, = self.originals()
        self.assertEqual(saved["body"], body)
        self.assertEqual(saved["full_body_chars"], len(body))
        self.assertEqual(saved["capture_limit"], 300000)
        self.assertTrue(saved["body_truncated"])
        self.assertNotIn("cookie", saved)

    def test_web_same_id_cannot_replace_graph_or_other_web_original(self):
        row = {"body": "GRAPH ORIGINAL", "source_kind": "teams_graph", "source_id": "same-id", "account": "same-account",
               "conversation_id": "same-room", "modified_time": "2026-10-01T09:00:00Z"}
        self.archive.archive_records(self.root, "teams", [row])
        self.archive.archive_records(self.root, "teams", [dict(row, body="WEB OBSERVATION", source_kind="teams_web")])
        self.assertEqual({item["body"] for item in self.originals()}, {"GRAPH ORIGINAL", "WEB OBSERVATION"})
        self.archive.archive_records(self.root, "teams", [dict(row, body="GRAPH REVISION", modified_time="2026-10-01T10:00:00Z")])
        self.assertEqual({item["body"] for item in self.originals()}, {"GRAPH REVISION", "WEB OBSERVATION"})

    def test_collapsed_or_truncated_capture_does_not_erase_rendered_body(self):
        row = {"body": self.long_body(), "source_kind": "outlook_web", "source_id": "message", "body_capture_status": "rendered"}
        self.archive.archive_records(self.root, "mail", [row])
        for weaker in (dict(row, body="PREVIEW", body_capture_status="collapsed"),
                       dict(row, body="CLIPPED", body_capture_status="partial"),
                       dict(row, body="CAPPED", capture_truncated=True)):
            self.archive.archive_records(self.root, "mail", [weaker])
            self.assertEqual(self.originals()[0]["body"], row["body"])
        self.archive.archive_records(self.root, "mail", [dict(row, body="SHORTER UNVERIFIED EDIT")])
        self.assertEqual(self.originals()[0]["body"], row["body"])
        self.archive.archive_records(self.root, "mail", [dict(row, body=row["body"] + " MORE OBSERVED TEXT")])
        self.assertEqual(self.originals()[0]["body"], row["body"] + " MORE OBSERVED TEXT")

    def test_filtered_body_never_enters_original_store_or_prompt(self):
        row = {"body": "PRIVATE_CONTENT", "context_excerpt": "PRIVATE_CONTENT", "context_filtered": "true",
               "source_kind": "teams_web", "source_id": "blocked"}
        self.assertEqual(self.archive.archive_records(self.root, "teams", [row]), 0)
        self.assertEqual(self.originals(), [])
        self.assertNotIn("PRIVATE_CONTENT", self.extract.context_preview(row))

    def test_extract_does_not_revert_excerpt_to_prefix_and_exposes_partial_capture(self):
        row = {"context_excerpt": self.long_body(), "source_kind": "teams_web", "body_capture_status": "partial",
               "full_body_chars": len(self.long_body()), "capture_method": "web_dom"}
        context = self.extract.collection_context(row)
        preview = self.extract.context_preview(context, 800)
        for token in ("BEGIN_DECISION", "MIDDLE_ACTION", "FINAL_RESULT"):
            self.assertIn(token, context["context_excerpt"])
            self.assertIn(token, preview)
        self.assertEqual(context["context_truncated"], "true")
        self.assertIn("일부 발췌", preview)
        self.assertIn('본문캡처="partial"', preview)

    def test_more_body_context_does_not_change_signal_weights_or_hours(self):
        day = date(2026, 9, 7)
        cfg = json.loads((APP / "config/config.default.json").read_text("utf-8-sig"))
        cfg.update(owner="Synthetic", teamsSelfNames=["Synthetic"])
        path = self.root / "data/m365/teams_web.csv"
        row = dict(time="2026-09-07 10:00:00", time_precision="minute", **{"from": "Synthetic"}, chat="Project",
                   kind="sent", summary="Project decision", source_id="same", source_kind="teams_web")
        results = []
        for body in ("SHORT", self.long_body()):
            record = dict(row, context_excerpt=self.context.make_excerpt(body, 4000), context_truncated=len(body) > 4000)
            self.state.write_csv(path, [record], list(record))
            signals, metadata = self.extract.load_signals(str(self.root / "data"), day, day, cfg=cfg)
            hours, _ = self.extract.day_work_hours(str(self.root / "data"), signals, day, day, cfg,
                now=datetime(2026, 9, 8), file_times=metadata["file_times"])
            results.append((signals, hours))
        self.assertEqual(results[0], results[1])

    def test_saved_body_privacy_is_checked_before_analysis_excerpt_and_date_copy_merge(self):
        day = date(2026, 9, 7)
        cfg = json.loads((APP / "config/config.default.json").read_text("utf-8-sig"))
        private_body = "START " + "A" * 4000 + " PRIVATE " + "B" * 16000 + " END"
        path = self.root / "data/outlook/mail.csv"
        base = {"box": "inbox", "time": "2026-09-07 10:00:00", "time_precision": "second", "sender": "Synthetic",
                "subject": "Safe project decision", "conversation": "Project", "rcv": "to", "source_id": "mail-1"}
        for rows in ([dict(base, context_excerpt=private_body)],
                     [base, dict(base, time="2026-09-07", time_precision="date", context_excerpt=private_body)]):
            fields = list(dict.fromkeys(key for row in rows for key in row))
            self.state.write_csv(path, rows, fields)
            signals, metadata = self.extract.load_signals(str(self.root / "data"), day, day, exclude=["private"], cfg=cfg)
            self.assertEqual(len(signals), 1)
            self.assertEqual(metadata["signal_contexts"][0]["context_excerpt"], "")

    def test_web_csv_retains_rendered_context_metadata_but_can_upgrade_date(self):
        old = {"source_id": "same-web", "source_kind": "teams_web", "time": "2026-09-07",
               "time_precision": "date", "context_excerpt": "FULL" * 1000, "summary": "Full original summary",
               "context_truncated": "true", "body_capture_status": "rendered", "full_body_chars": "25000",
               "capture_method": "web_dom", "body_truncated": "false", "capture_limit": "300000"}
        partial = dict(old, time="2026-09-07 10:00:00", time_precision="minute", context_excerpt="PART" * 1000,
                       summary="Preview summary", body_capture_status="partial", full_body_chars="4000", body_truncated="true")
        for weak in (partial, dict(partial, context_excerpt="", full_body_chars="0", body_capture_status="unavailable")):
            merged, = self.state.merge_rows([old], [weak], "teams")
            for field in self.state.WEB_CONTEXT_FIELDS & old.keys():
                self.assertEqual(merged[field], old[field], field)
            self.assertEqual((merged["time"], merged["time_precision"]), (partial["time"], "minute"))

    def test_web_csv_same_quality_prefers_richer_body_and_updates_bundle_together(self):
        old = {"source_id": "same-web", "source_kind": "outlook_web", "time": "2026-09-07 10:00:00",
               "time_precision": "minute", "context_excerpt": "PREVIEW" * 500, "body_capture_status": "partial",
               "full_body_chars": "8000", "body_truncated": "true", "capture_limit": "8000"}
        richer = dict(old, context_excerpt="DETAIL" * 500, full_body_chars="16000", capture_limit="16000")
        merged, = self.state.merge_rows([old], [richer], "mail")
        self.assertEqual(merged["context_excerpt"], richer["context_excerpt"])
        self.assertEqual(merged["full_body_chars"], "16000")
        poorer = dict(old, context_excerpt="OTHER" * 800)
        merged, = self.state.merge_rows([merged], [poorer], "mail")
        self.assertEqual(merged["context_excerpt"], richer["context_excerpt"])
        rendered = {"source_id": "same-web", "source_kind": "outlook_web", "time": "2026-09-07 10:00:00",
                    "time_precision": "minute", "context_excerpt": "ALL TEXT", "body_capture_status": "rendered",
                    "full_body_chars": "8", "context_filtered": "", "context_truncated": "false"}
        merged, = self.state.merge_rows([merged], [rendered], "mail")
        self.assertEqual(merged["context_excerpt"], "ALL TEXT")
        self.assertEqual(merged["body_capture_status"], "rendered")
        self.assertNotIn("body_truncated", merged)
        self.assertNotIn("capture_limit", merged)

    def test_new_full_body_privacy_block_overrides_retained_excerpt_and_survives_metadata_retry(self):
        old = {"source_id": "same-web", "source_kind": "teams_web", "time": "2026-09-07 10:00:00",
               "time_precision": "minute", "context_excerpt": "OLD_VISIBLE_CONTEXT", "summary": "Old summary",
               "body_capture_status": "rendered", "full_body_chars": "20000"}
        blocked = dict(old, context_excerpt="", summary="", context_filtered="true", full_body_chars="30000")
        merged, = self.state.merge_rows([old], [blocked], "teams")
        self.assertEqual((merged["context_excerpt"], merged["summary"], merged["context_filtered"]), ("", "", "true"))
        for retry in (dict(old, context_excerpt="", context_filtered="", full_body_chars="0"),
                      dict(old, context_excerpt="SHORT PREVIEW", context_filtered="", body_capture_status="partial")):
            saved, = self.state.merge_rows([merged], [retry], "teams")
            self.assertEqual((saved["context_excerpt"], saved["summary"], saved["context_filtered"]), ("", "", "true"))
            self.assertNotIn("OLD_VISIBLE_CONTEXT", self.extract.context_preview(saved))

    def test_archive_body_retention_still_upgrades_unknown_date_from_same_original(self):
        row = {"source_id": "pending-web", "source_kind": "teams_web", "body": self.long_body(),
               "time": "", "time_precision": "unknown", "body_capture_status": "rendered"}
        self.archive.archive_records(self.root, "teams", [row])
        partial = dict(row, body="SHORTER PREVIEW", body_capture_status="partial", time="2026-09-07 10:00:00")
        self.archive.archive_records(self.root, "teams", [dict(partial, time_precision="estimated")])
        self.assertEqual(self.originals()[0]["time"], "")
        self.archive.archive_records(self.root, "teams", [dict(partial, time_precision="minute")])
        saved, = self.originals()
        self.assertEqual((saved["body"], saved["body_capture_status"]), (row["body"], "rendered"))
        self.assertEqual((saved["time"], saved["time_precision"]), (partial["time"], "minute"))

    def test_archive_richer_body_does_not_erase_previous_proven_date(self):
        row = {"source_id": "dated-web", "source_kind": "teams_web", "body": "SHORT RENDERED BODY",
               "time": "2026-09-07 10:00:00", "time_precision": "minute", "body_capture_status": "rendered"}
        self.archive.archive_records(self.root, "teams", [row])
        richer = dict(row, body=self.long_body(), time="", time_precision="unknown")
        self.archive.archive_records(self.root, "teams", [richer])
        saved, = self.originals()
        self.assertEqual(saved["body"], richer["body"])
        self.assertEqual((saved["time"], saved["time_precision"]), (row["time"], "minute"))

    def test_web_privacy_block_applies_across_pcs_without_crossing_identity_scope(self):
        day = date(2026, 9, 7)
        row = {"source_id": "same-web", "source_kind": "outlook_web", "account": "same-account",
               "conversation_id": "same-thread", "time": "2026-09-07 10:00:00", "time_precision": "minute",
               "box": "unknown", "sender": "Synthetic sender", "subject": "Synthetic project decision",
               "context_excerpt": "OLD_VISIBLE_CONTEXT", "body_capture_status": "rendered", "context_filtered": ""}
        blocked = dict(row, context_excerpt="", context_filtered="true", body_capture_status="filtered")
        self.state.write_csv(self.root / "data/outlook/mail.csv", [blocked], list(blocked))
        self.state.write_csv(self.root / "data/추가PC/old/outlook/mail.csv", [row], list(row))
        cfg = json.loads((APP / "config/config.default.json").read_text("utf-8-sig"))
        signals, metadata = self.extract.load_signals(str(self.root / "data"), day, day, cfg=cfg)
        self.assertEqual(len(signals), 1)
        self.assertEqual(metadata["signal_contexts"][0]["context_excerpt"], "")
        self.assertEqual(metadata["signal_contexts"][0]["context_filtered"], "true")
        report = self.evidence.build_report(self.root, day, day, cfg)["families"]["mail"]
        self.assertEqual((report["context_rows"], report["context_filtered_rows"]), (0, 1))
        for other in (dict(row, account="another-account"), dict(row, conversation_id="another-thread"),
                      dict(row, source_id="another-id"), dict(row, source_kind="outlook_graph")):
            selected = self.state.latest_original_rows([blocked, other], "mail")
            self.assertIn("OLD_VISIBLE_CONTEXT", [value.get("context_excerpt") for value in selected])
        self.assertEqual(row["context_excerpt"], "OLD_VISIBLE_CONTEXT")  # No mutation of caller data.

    def test_web_cross_pc_body_and_capture_metadata_follow_same_best_observation(self):
        base = {"source_id": "same-web", "source_kind": "teams_web", "account": "same", "conversation_id": "room",
                "time": "2026-09-07 10:00:00", "time_precision": "minute", "context_excerpt": "P" * 4000,
                "body_capture_status": "partial", "body_truncated": "true", "full_body_chars": "5000"}
        rendered = dict(base, context_excerpt="R" * 4000, body_capture_status="rendered", body_truncated="false",
                        full_body_chars="25000", time="2026-09-07", time_precision="date")
        selected = self.state.latest_original_rows([base, rendered], "teams")
        self.assertEqual([value["time"] for value in selected], [base["time"], rendered["time"]])
        for value in selected:
            self.assertEqual((value["context_excerpt"], value["body_capture_status"], value["full_body_chars"]),
                             (rendered["context_excerpt"], "rendered", "25000"))

    def test_repeated_identical_web_capture_does_not_rewrite_original(self):
        row = {"source_id": "web-1", "source_kind": "teams_web", "body": self.long_body(),
               "body_capture_status": "rendered", "time": "2026-09-07 10:00:00", "time_precision": "minute"}
        self.archive.archive_records(self.root, "teams", [row])
        with mock.patch.object(self.archive, "_atomic_text", side_effect=AssertionError("Unnecessary rewrite")):
            self.assertEqual(self.archive.archive_records(self.root, "teams", [row]), 1)


if __name__ == "__main__":
    unittest.main()
