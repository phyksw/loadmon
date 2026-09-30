"""Synthetic export imports; no installed mail client, account, or real mailbox."""
from datetime import date
from email.message import EmailMessage
import importlib.util
import json
import mailbox
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1] / "LoadMonitor25"
with patch.object(sys, "path", [str(ROOT / "core"), *sys.path]):
    spec = importlib.util.spec_from_file_location("_communication_import", ROOT / "core/communication_import.py")
    MODULE = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(MODULE)


def message(identity="one", when="Tue, 15 Sep 2026 12:00:00 +0900", body="Please review the specification."):
    result = EmailMessage()
    result["From"] = "Synthetic Manager <manager@example.invalid>"
    result["To"] = "owner@example.invalid"
    result["Subject"] = "Synthetic delivery"
    result["Message-ID"] = f"<{identity}@example.invalid>"
    if when:
        result["Date"] = when
    result.set_content(body)
    return result


class CommunicationImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="lm25-import-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.inputs = self.root / "selected"
        self.inputs.mkdir()
        self.config = {"collection": {"communicationImportOwnAddresses": ["owner@example.invalid"]}}

    def save(self, item, name="one.eml"):
        path = self.inputs / name
        path.write_bytes(item.as_bytes())
        return path

    def run_import(self, paths, **kwargs):
        return MODULE.import_paths(self.root, paths, "2026-09-01", "2026-09-30", kwargs.get("config", self.config))

    def rows(self):
        return MODULE.read_csv(self.root / "data/outlook/mail.csv")

    def test_reply_headers_context_and_origin_survive_idempotent_import(self):
        first = message()
        reply = message("two", body="The specification is approved; proceed with delivery.")
        reply.replace_header("From", "owner@example.invalid")
        reply.replace_header("To", "manager@example.invalid")
        reply["In-Reply-To"] = first["Message-ID"]
        reply["References"] = first["Message-ID"]
        paths = [self.save(first), self.save(reply, "two.eml")]
        originals = [path.read_bytes() for path in paths]
        result = self.run_import(paths)
        self.assertEqual((result["status"], result["imported_rows"]), ("complete", 2))
        records = {row["message_id"]: row for row in self.rows()}
        self.assertEqual(records[str(reply["Message-ID"])]["in_reply_to"], str(first["Message-ID"]))
        self.assertEqual(records[str(reply["Message-ID"])]["box"], "sent")
        self.assertIn("approved", records[str(reply["Message-ID"])]["context_excerpt"])
        again = self.run_import(paths)
        self.assertEqual((again["imported_rows"], again["existing_total"]), (0, 2))
        self.assertEqual([path.read_bytes() for path in paths], originals)
        self.assertNotIn("example.invalid", str(result))
        self.assertNotIn(str(self.inputs), str(result))

    def test_partial_and_narrow_import_preserve_existing_history(self):
        first = self.save(message())
        self.run_import([first])
        outside = self.save(message("older", "Tue, 01 Sep 2025 12:00:00 +0900"), "outside.eml")
        undated = self.save(message("undated", when=""), "undated.eml")
        unsupported = self.inputs / "mail.pst"
        unsupported.write_bytes(b"unsupported synthetic export")
        result = self.run_import([outside, undated, unsupported])
        self.assertEqual((result["counts"]["outside_range"], result["counts"]["undated"], result["counts"]["unsupported"]), (1, 1, 1))
        self.assertEqual(result["status"], "failed")
        self.assertEqual(len(self.rows()), 1)

    def test_mbox_multiple_messages_no_attachments_or_remote_html_execution(self):
        path = self.inputs / "export.mbox"
        box = mailbox.mbox(path)
        first = message(body="Visible plain text")
        first.add_attachment(b"secret attachment", maintype="application", subtype="octet-stream", filename="sample.bin")
        second = message("html")
        second.set_content('<p>Approved work</p><script>dangerous()</script><img src="https://example.invalid/tracker">', subtype="html")
        box.add(first)
        box.add(second)
        box.close()
        original = path.read_bytes()
        self.run_import([path])
        self.assertEqual(len(self.rows()), 2)
        all_context = " ".join(row["context_excerpt"] for row in self.rows())
        self.assertIn("Approved work", all_context)
        self.assertNotIn("dangerous", all_context)
        self.assertNotIn("secret attachment", all_context)
        self.assertEqual(path.read_bytes(), original)

    def test_nonrecursive_by_default_and_body_bound_explicit(self):
        self.save(message(body="x" * 8000))
        nested = self.inputs / "nested"
        nested.mkdir()
        (nested / "two.eml").write_bytes(message("two").as_bytes())
        result = self.run_import([self.inputs], config={"collection": {"contextChars": 100}})
        self.assertEqual(result["counts"]["files"], 1)
        self.assertEqual(len(self.rows()[0]["context_excerpt"]), 100)
        self.assertEqual(self.rows()[0]["context_truncated"], "true")
        self.assertEqual(self.rows()[0]["box"], "unknown")
        result = self.run_import([self.inputs], config={"collection": {"communicationImportRecursive": True}})
        self.assertEqual(result["existing_total"], 2)

    def test_same_id_different_content_is_not_silently_overwritten(self):
        first = self.save(message(body="Original instruction"))
        other = self.save(message(body="Conflicting instruction"), "other.eml")
        result = self.run_import([first, other])
        self.assertEqual(len(self.rows()), 2)
        self.assertIn("conflicting_message_id_retained_separately", result["reasons"])

    def test_same_message_repackaged_as_mbox_deduplicates_without_raw_hash_identity(self):
        item = message()
        eml = self.save(item)
        self.run_import([eml])
        item["X-Export-Tool"] = "synthetic new packaging"
        path = self.inputs / "repackaged.mbox"
        box = mailbox.mbox(path)
        box.add(item)
        box.close()
        result = self.run_import([path])
        self.assertEqual((result["imported_rows"], result["existing_total"]), (0, 1))

    def test_invalid_range_does_not_create_output(self):
        with self.assertRaises(ValueError):
            MODULE.import_paths(self.root, [], date(2026, 9, 30), date(2026, 9, 1))
        self.assertFalse((self.root / "data").exists())


class OutlookSearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("_outlook_search", ROOT / "collect/Get-OutlookWeb.py")
        cls.module = importlib.util.module_from_spec(spec)
        with patch.object(sys, "path", list(sys.path)):
            spec.loader.exec_module(cls.module)

    def test_documented_received_and_sent_ranges_and_week_windows(self):
        d0, d1 = date(2026, 9, 1), date(2026, 9, 30)
        self.assertEqual(self.module.mail_search_query(d0, d1, "inbox"), "received:09/01/2026..09/30/2026")
        self.assertEqual(self.module.mail_search_query(d0, d1, "sent"), "sent:09/01/2026..09/30/2026")
        windows = list(self.module.mail_search_windows(d0, d1))
        self.assertEqual(len(windows), 5)
        self.assertEqual(sum((end - start).days + 1 for start, end in windows), 30)

    def test_failed_search_does_not_read_stale_message_list(self):
        class Browser:
            def goto(self, url):
                return "ok"

            def search(self, query):
                return False

            def eval_json(self, js):
                raise AssertionError("stale list must not be read")
        rows, _, diag = self.module.collect_mail(Browser(), date(2026, 9, 1), date(2026, 9, 1))
        self.assertEqual(rows, [])
        self.assertEqual(diag["search_failed"], 2)
        self.assertIn("search_input_failed; stale_visible_list_skipped", diag["reasons"])

    def test_two_budget_runs_resume_untraversed_ranges_then_refresh_latest(self):
        clock = [0.0]
        module = self.module

        class Browser:
            def __init__(self):
                self.cdp = self
                self.queries = []

            def goto(self, url):
                return "ok"

            def search(self, query):
                self.queries.append(query)
                return "query_entered_unverified"

            def eval_json(self, js):
                return {"items": [{"key": self.queries[-1], "item_id": self.queries[-1],
                                    "label": "2026-09-03 10:00", "texts": ["Synthetic sender", "Synthetic subject"]}]}

            def eval(self, js):
                return "end"

        with tempfile.TemporaryDirectory(prefix="lm25-owa-resume-") as directory:
            path = str(Path(directory) / "jobs.json")
            first = Browser()
            with patch.object(module.time, "monotonic", side_effect=lambda: clock[0]), \
                    patch.object(module.time, "sleep", side_effect=lambda seconds: clock.__setitem__(0, clock[0] + seconds)):
                rows, state, _ = module.collect_mail(first, date(2026, 9, 1), date(2026, 9, 14),
                                                    checkpoint=lambda rows: None, deadline=2.0, state_path=path)
                self.assertEqual(state, "partial")
                self.assertEqual(rows[0][0], "unknown")
                second = Browser()
                module.collect_mail(second, date(2026, 9, 1), date(2026, 9, 14),
                                    checkpoint=lambda rows: None, deadline=30.0, state_path=path)
                self.assertTrue(second.queries[0].startswith("sent:09/01/2026"))
                self.assertNotIn("received:09/01/2026..09/07/2026", second.queries)
                third = Browser()
                module.collect_mail(third, date(2026, 9, 1), date(2026, 9, 14),
                                    checkpoint=lambda rows: None, deadline=60.0, state_path=path)
                self.assertEqual(third.queries[0], "sent:09/08/2026..09/14/2026")
            saved = json.loads(Path(path).read_text())
            self.assertEqual(len(saved["units"]), 4)
            self.assertTrue(all(value["traversed"] for value in saved["units"].values()))
            self.assertNotIn("Synthetic subject", Path(path).read_text())


if __name__ == "__main__":
    unittest.main()
