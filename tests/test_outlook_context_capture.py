"""Read-pane conversation evidence using synthetic DOM and temporary stores only."""
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

import test_outlook_web_compatibility as compatibility

node = compatibility.node


PRODUCT = Path(__file__).resolve().parents[1] / "LoadMonitor25"


class OutlookContextCapture(unittest.TestCase):
    javascript = compatibility.OutlookWebCompatibility.javascript

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="lm25-mail-context-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for folder, names in (("collect", ["Get-OutlookWeb.py"]),
                              ("core", ["collection_state.py", "communication_archive.py", "communication_context.py"])):
            (self.root / folder).mkdir()
            for name in names:
                shutil.copyfile(PRODUCT / folder / name, self.root / folder / name)
        spec = importlib.util.spec_from_file_location("outlook_context", self.root / "collect/Get-OutlookWeb.py")
        self.mod = importlib.util.module_from_spec(spec)
        with patch.object(sys, "path", list(sys.path)):
            spec.loader.exec_module(self.mod)

    def card(self, identity, body="Original body", stamp="2026-09-03T10:00:00", **kwargs):
        return node("article", {"data-itemid": identity}, children=[
            node("h2", {"role": "heading"}, "Synthetic subject"),
            node("span", {"data-testid": "sender"}, "Synthetic sender"),
            node("time", {"datetime": stamp}, stamp),
            node(attrs={"data-testid": "message-body"}, text=body),
        ], **kwargs)

    def fixture(self, cards):
        return node(children=[node(attrs={"role": "grid"}, children=[
            node(attrs={"role": "row", "data-itemid": "m1", "data-convid": "thread1", "aria-selected": "true"}, children=[
                node("span", {"data-testid": "subject"}, "Synthetic subject"),
                node("span", {"data-testid": "sender"}, "Synthetic sender"),
            ])]), node(attrs={"data-testid": "reading-pane", "data-convid": "thread1"}, children=cards)])

    def detail(self, fixture, **kwargs):
        expected = {"key": "item:m1", "item_id": "m1", "conversation_id": "thread1", "subject": "Synthetic subject", "limit": 4000}
        expected.update(kwargs)
        return self.javascript(fixture, [self.mod.JS_MAIL_DETAIL % json.dumps(expected)])[0]

    def test_one_message_multiple_body_fragments_are_kept_in_dom_order(self):
        card = self.card("m1", "First paragraph")
        card["children"].append(node(attrs={"data-testid": "message-body-content"}, text="Middle decision"))
        detail = self.detail(self.fixture([card]))
        self.assertEqual(detail.get("body"), "First paragraph\nMiddle decision")

    def test_thread_messages_keep_individual_identity_and_header_date(self):
        cards = [self.card("m1", "First instruction"), self.card("m2", "Middle response", "2026-09-04T11:15:00"),
                 self.card("m3", "Final decision", "2026-09-05T12:30:00")]
        cards[1]["children"][-1]["children"] = [node("time", {"datetime": "2000-01-01T00:00:00"}, "quoted date")]
        detail = self.detail(self.fixture(cards))
        self.assertEqual([x["item_id"] for x in detail.get("messages", [])], ["m1", "m2", "m3"])
        self.assertEqual(detail["messages"][1]["date_texts"], ["2026-09-04T11:15:00"])

    def test_long_rendered_body_is_not_cut_to_csv_excerpt_before_archiving(self):
        body = "Beginning\n" + "x" * 9000 + "\nMiddle decision\n" + "y" * 9000 + "\nFinal action"
        detail = self.detail(self.fixture([self.card("m1", body)]))
        self.assertEqual(detail.get("body"), body)
        self.assertEqual(detail["body_capture_status"], "rendered")

    def test_other_reading_pane_and_quote_message_are_not_thread_members(self):
        card = self.card("m1")
        card["children"][-1]["children"].append(node("blockquote", children=[self.card("quoted", "Quoted mail")]))
        fixture = self.fixture([card])
        fixture["children"].append(node(attrs={"data-testid": "reading-pane", "data-convid": "another"},
                                        children=[self.card("foreign", "Other mailbox")]))
        detail = self.detail(fixture)
        self.assertEqual([x["item_id"] for x in detail.get("messages", [])], ["m1"])

    def collect(self, cards, *, body=True, exclude=(), store_subject=True):
        fixture = self.fixture(cards)
        page, = self.javascript(fixture, [self.mod.JS_MAIL])
        item = page["items"][0]
        item["detail"] = self.detail(fixture)
        return self.mod.collect_mail(None, date(2026, 9, 1), date(2026, 9, 30),
                                     {"mail": {"2026-09": [item]}}, body=body,
                                     store_subject=store_subject, exclude_keywords=exclude,
                                     checkpoint=lambda rows: self.mod._save("mail", rows, store_subject))

    def test_undated_list_recovers_own_dates_and_archives_middle_mail_without_date_inheritance(self):
        long_body = "Beginning\n" + "x" * 9000 + "\nMiddle decision\n" + "y" * 9000 + "\nFinal action"
        cards = [self.card("m1"), self.card("m2", long_body, "2026-09-04T11:15:00"),
                 self.card("outside", "Older", "2026-08-31T10:00:00"), self.card("undated", "Unknown date", "")]
        rows, status, diag = self.collect(cards)
        self.assertEqual(status, "ok")
        self.assertEqual({row[9] for row in rows}, {"m1", "m2"})
        self.assertEqual(diag["detail_dates_recovered"], 1)
        self.assertEqual((diag["body_rows"], diag["pending_body_rows"]), (2, 1))
        saved = {r["source_id"]: r for r in self.mod.read_csv(self.root / "data/outlook/mail.csv")}
        middle = saved["m2"]
        self.assertEqual(middle["time"], "2026-09-04 11:15")
        self.assertLessEqual(len(middle["context_excerpt"]), 4000)
        self.assertIn("Middle decision", middle["context_excerpt"])
        self.assertIn("Final action", middle["context_excerpt"])
        self.assertNotIn("_full_body", middle)
        originals = [json.loads(p.read_text()) for p in (self.root / "data/communication_originals/mail").rglob("*.json")]
        by_id = {row["source_id"]: row for row in originals}
        self.assertEqual(by_id["m2"]["body"], long_body)
        self.assertFalse(by_id["m2"]["body_truncated"])
        self.assertEqual(by_id["undated"]["time"], "")
        pending = self.mod.read_csv(self.root / "data/collection_pending/outlook_web_undated.csv")
        self.assertEqual([(r["source_id"], r["time"]) for r in pending], [("undated", "")])
        self.assertNotIn("outside", by_id)

    def test_collapsed_message_expansion_is_scoped_to_verified_read_pane(self):
        collapsed = self.card("m2", "Middle response", "2026-09-04T11:15:00")
        collapsed["children"][-1]["hidden"] = True
        collapsed["children"].insert(0, node("button", {"data-testid": "message-header", "aria-expanded": "false"}, "Open message"))
        fixture = self.fixture([self.card("m1"), collapsed])
        fixture["children"].append(node("button", {"aria-expanded": "false", "data-testid": "message-header"}, "Outside"))
        expected = {"key": "item:m1", "item_id": "m1", "conversation_id": "thread1", "subject": "Synthetic subject", "expand": True}
        action = "Element.prototype.click=function(){this.attrs['aria-expanded']='true'; for(const e of this.parentElement.querySelectorAll('[data-testid=\"message-body\"]')){e.width=600;e.height=40;}}; true"
        _, first, second, outside = self.javascript(fixture, [action,
            self.mod.JS_MAIL_DETAIL % json.dumps(expected), self.mod.JS_MAIL_DETAIL % json.dumps(expected),
            "document.children[2].getAttribute('aria-expanded')"])
        self.assertEqual(first["expanded"], 1)
        self.assertEqual(second["expanded"], 0)
        self.assertEqual(second["messages"][1]["body"], "Middle response")
        self.assertEqual(second["messages"][1]["body_capture_status"], "rendered")
        self.assertEqual(outside, "false")

    def test_full_body_privacy_filter_precedes_archive_and_excerpt_storage(self):
        secret = "Beginning " + "x" * 6000 + " SENSITIVE_PRIVATE " + "y" * 12000 + " end"
        rows, _, diag = self.collect([self.card("m1", secret)], exclude=["sensitive_private"])
        self.assertEqual(diag["context_filtered"], 1)
        saved = self.mod.read_csv(self.root / "data/outlook/mail.csv")[0]
        self.assertEqual((saved["context_excerpt"], saved["context_filtered"]), ("", "true"))
        self.assertEqual(rows[0][-1], "")
        self.assertFalse(list((self.root / "data/communication_originals").rglob("*.json")))

    def test_body_opt_out_and_subject_privacy_do_not_open_detail_or_archive(self):
        item = {"key": "item:m1", "item_id": "m1", "subject": "Synthetic subject", "sender": "Sender", "label": "2026-09-03 10:00"}
        for body, store_subject in ((False, True), (True, False)):
            with self.subTest(body=body, store_subject=store_subject), \
                    patch.object(self.mod, "read_mail_detail", side_effect=AssertionError("must not open")):
                rows, _, _ = self.mod.collect_mail(None, date(2026, 9, 1), date(2026, 9, 30),
                    {"mail": {"2026-09": [item]}}, body=body, store_subject=store_subject,
                    checkpoint=lambda rows: self.mod._save("mail", rows, store_subject))
                self.assertEqual(rows[0][-1], "")
        self.assertFalse(list((self.root / "data/communication_originals").rglob("*.json")))

    def browser(self, item):
        navigations = []
        def goto(url):
            navigations.append(url)
            return "ok" if len(navigations) == 1 else "login"
        return SimpleNamespace(goto=goto, search=lambda query: True,
                               eval_json=lambda js: {"items": [item]}, cdp=SimpleNamespace(eval=lambda js: "end"))

    def test_archive_failure_does_not_advance_resume_cursor_and_next_run_retries(self):
        fixture = self.fixture([self.card("m1")])
        page, = self.javascript(fixture, [self.mod.JS_MAIL])
        item, detail = page["items"][0], self.detail(fixture)
        state = self.root / "data/outlook/web_mail_jobs.json"
        def collect():
            return self.mod.collect_mail(self.browser(item), date(2026, 9, 1), date(2026, 9, 7), body=True,
                state_path=state, checkpoint=lambda rows: self.mod._save("mail", rows, True))
        with patch.object(self.mod, "read_mail_detail", return_value=(detail, "")), \
                patch.object(self.mod, "archive_records", side_effect=OSError("synthetic disk failure")):
            with self.assertRaises(OSError):
                collect()
        saved = json.loads(state.read_text())
        self.assertFalse(any(unit.get("seen_hashes") or unit.get("traversed") for unit in saved["units"].values()))
        self.assertFalse((self.root / "data/outlook/mail.csv").exists())
        with patch.object(self.mod, "read_mail_detail", return_value=(detail, "")) as reader, patch.object(self.mod.time, "sleep"):
            rows, _, _ = collect()
        self.assertEqual(len(rows), 1)
        self.assertEqual(reader.call_count, 1)
        self.assertEqual(len(self.mod.read_csv(self.root / "data/outlook/mail.csv")), 1)

    def test_partial_conversation_stays_pending_and_retries_missing_middle_body(self):
        fixture = self.fixture([self.card("m1"), self.card("m2", "", "2026-09-04T11:15:00")])
        page, = self.javascript(fixture, [self.mod.JS_MAIL])
        item, first = page["items"][0], self.detail(fixture)
        first["messages"][1]["body_capture_status"] = "collapsed"
        state = self.root / "data/outlook/web_mail_jobs.json"
        def collect(detail):
            with patch.object(self.mod, "read_mail_detail", return_value=(detail, "")), patch.object(self.mod.time, "sleep"):
                return self.mod.collect_mail(self.browser(item), date(2026, 9, 1), date(2026, 9, 7), body=True,
                    state_path=state, checkpoint=lambda rows: self.mod._save("mail", rows, True))
        collect(first)
        saved = json.loads(state.read_text())
        attempted = [u for u in saved["units"].values() if u.get("finished_at")]
        self.assertTrue(attempted)
        self.assertFalse(any(u["traversed"] or u.get("seen_hashes") for u in attempted))
        final = self.detail(self.fixture([self.card("m1"), self.card("m2", "Middle body now visible", "2026-09-04T11:15:00")]))
        collect(final)
        by_id = {r["source_id"]: r for r in self.mod.read_csv(self.root / "data/outlook/mail.csv")}
        self.assertEqual(by_id["m2"]["context_excerpt"], "Middle body now visible")

    def test_body_without_message_id_is_explicitly_partial_and_not_invented(self):
        fixture = self.fixture([self.card("m1"), node("article", children=[
            node("time", {"datetime": "2026-09-04T11:15:00"}),
            node(attrs={"data-testid": "message-body"}, text="Unidentified middle response")])])
        detail = self.detail(fixture)
        self.assertEqual(detail["ambiguous_messages"], 1)
        self.assertEqual([m["item_id"] for m in detail["messages"]], ["m1"])

    def test_detail_timeout_keeps_verified_observations_for_checkpoint(self):
        fixture = self.fixture([self.card("m1")])
        page, = self.javascript(fixture, [self.mod.JS_MAIL])
        item, detail = page["items"][0], self.detail(fixture)
        detail["expanded"] = 1
        browser = SimpleNamespace(cdp=SimpleNamespace(eval=lambda *a, **kw: "opened"))
        with patch.object(self.mod.time, "sleep"):
            browser.eval_json = unittest.mock.Mock(side_effect=[detail, TimeoutError("synthetic route deadline")])
            observed, reason = self.mod.read_mail_detail(browser, item, None, 4000)
        self.assertEqual(reason, "")
        self.assertEqual(observed["body"], "Original body")
        self.assertTrue(observed["read_interrupted"])

    def test_capture_ceiling_is_separate_from_excerpt_truncation(self):
        detail = self.detail(self.fixture([self.card("m1", "x" * 100)]), capture_limit=20)
        self.assertEqual(len(detail["body"]), 20)
        self.assertEqual(detail["body_capture_status"], "partial")
        self.assertTrue(detail["body_truncated"])

    def test_incomplete_list_mail_can_be_enriched_from_later_thread_in_same_run(self):
        fixture = self.fixture([self.card("m1"), self.card("m2", "Middle complete", "2026-09-04T11:15:00")])
        detail = self.detail(fixture)
        first = {"key": "item:m2", "item_id": "m2", "conversation_id": "thread1", "subject": "Synthetic subject",
                 "label": "2026-09-04 11:15", "detail": {}}
        second = {"key": "item:m1", "item_id": "m1", "conversation_id": "thread1", "subject": "Synthetic subject", "detail": detail}
        self.mod.collect_mail(None, date(2026, 9, 1), date(2026, 9, 30),
            {"mail": {"2026-09": [first, second]}}, body=True,
            checkpoint=lambda rows: self.mod._save("mail", rows, True))
        by_id = {r["source_id"]: r for r in self.mod.read_csv(self.root / "data/outlook/mail.csv")}
        self.assertEqual(by_id["m2"]["context_excerpt"], "Middle complete")

    def test_interrupted_detail_keeps_unit_pending_even_when_observed_body_is_rendered(self):
        fixture = self.fixture([self.card("m1")])
        page, = self.javascript(fixture, [self.mod.JS_MAIL])
        item, detail = page["items"][0], self.detail(fixture)
        detail["read_interrupted"] = True
        state = self.root / "data/outlook/web_mail_jobs.json"
        with patch.object(self.mod, "read_mail_detail", return_value=(detail, "")), patch.object(self.mod.time, "sleep"):
            rows, _, diag = self.mod.collect_mail(self.browser(item), date(2026, 9, 1), date(2026, 9, 7), body=True,
                state_path=state, checkpoint=lambda rows: self.mod._save("mail", rows, True))
        self.assertEqual(len(rows), 1)
        self.assertIn("thread_detail_interrupted; verified_observations_retained", diag["reasons"])
        state_data = json.loads(state.read_text())
        self.assertFalse(any(u.get("traversed") or u.get("seen_hashes") for u in state_data["units"].values()))

    def test_partial_body_marks_short_excerpt_incomplete(self):
        item = {"key": "item:m1", "item_id": "m1"}
        detail = {"item_id": "m1", "selected_key": "item:m1", "subject": "Subject", "container": "message-body",
                  "body": "Only visible beginning", "body_capture_status": "partial", "body_truncated": True}
        result = self.mod.detail_context(item, ["", "", "", "Subject"], detail, 4000)
        self.assertEqual(result[:3], ("Only visible beginning", "true", ""))

    def test_message_content_links_forms_and_quoted_buttons_are_never_clicked(self):
        card = self.card("m1")
        card["children"][-1]["children"] = [
            node("button", {"aria-expanded": "false", "data-testid": "message-header"}, "Show more"),
            node("a", {"href": "https://external.invalid/submit", "role": "button", "aria-expanded": "false"}, "Show more"),
            node("form", children=[node("button", {"type": "submit", "aria-expanded": "false"}, "Read more")]),
            node("blockquote", children=[node("button", {"aria-expanded": "false", "data-testid": "message-header"}, "Open message")]),
        ]
        card["children"].append(node("form", children=[
            node("button", {"data-testid": "message-header", "aria-expanded": "false"}, "Read more")]))
        card["children"].append(node("a", {"href": "https://external.invalid/", "data-testid": "message-header", "aria-expanded": "false"}, "Open message"))
        card["children"].append(node("button", {"form": "outside-form", "formaction": "https://external.invalid/submit",
                                                "data-testid": "message-header", "aria-expanded": "false"}, "Open message"))
        fixture = self.fixture([card])
        expected = {"key": "item:m1", "item_id": "m1", "conversation_id": "thread1", "subject": "Synthetic subject", "expand": True}
        _, detail, clicked = self.javascript(fixture, ["window.clicks=0; Element.prototype.click=function(){window.clicks++}; true",
            self.mod.JS_MAIL_DETAIL % json.dumps(expected), "window.clicks"])
        self.assertEqual(clicked, 0)
        self.assertEqual(detail["expanded"], 0)

    def test_out_of_period_conversation_preview_can_contain_in_period_middle_mail(self):
        fixture = self.fixture([self.card("m1", "Latest reply", "2026-10-02T10:00:00"),
                                self.card("m2", "September middle response", "2026-09-04T11:15:00")])
        page, = self.javascript(fixture, [self.mod.JS_MAIL])
        item = dict(page["items"][0], date_texts=["2026-10-02T10:00:00"], detail=self.detail(fixture))
        for enabled in (False, True):
            with self.subTest(body=enabled):
                rows, _, diag = self.mod.collect_mail(None, date(2026, 9, 1), date(2026, 9, 30),
                    {"mail": {"2026-09": [item]}}, body=enabled,
                    checkpoint=lambda rows: self.mod._save("mail", rows, True))
                self.assertEqual([row[9] for row in rows], ["m2"] if enabled else [])
                self.assertEqual(diag["period_filtered"], 1)
        saved = self.mod.read_csv(self.root / "data/outlook/mail.csv")
        self.assertEqual([(r["source_id"], r["time"]) for r in saved], [("m2", "2026-09-04 11:15")])

    def test_previous_capture_strategy_checkpoint_is_not_reused(self):
        state = self.root / "data/outlook/web_mail_jobs.json"
        state.parent.mkdir(parents=True)
        old = {"schema": 2, "requested_from": "2026-09-01", "requested_to": "2026-09-30", "body": True,
               "context_chars": 4000, "units": {"inbox:2026-09-01:2026-09-07": {"traversed": True, "seen_hashes": ["old"]}}}
        state.write_text(json.dumps(old))
        observed = []
        browser = SimpleNamespace(goto=lambda url: "login", search=lambda query: observed.append(query))
        self.mod.collect_mail(browser, date(2026, 9, 1), date(2026, 9, 30), body=True, state_path=state)
        fresh = json.loads(state.read_text())
        self.assertEqual(fresh["schema"], 3)
        self.assertFalse(fresh["units"]["inbox:2026-09-01:2026-09-07"]["traversed"])
        self.assertEqual(fresh["units"]["inbox:2026-09-01:2026-09-07"]["seen_hashes"], [])

    def test_undated_message_can_gain_exact_date_later_in_same_run_with_body_enabled(self):
        fixture = self.fixture([self.card("m1", "Observed body", "")])
        page, = self.javascript(fixture, [self.mod.JS_MAIL])
        item, detail = page["items"][0], self.detail(fixture)
        exact = dict(item, date_texts=["2026-09-03T10:00:00"])
        pages = iter([{"items": [item]}, {"items": [exact]}])
        browser = self.browser(item)
        browser.eval_json = lambda js: next(pages, {"items": [exact]})
        browser.wait_list_change = lambda *args, **kwargs: None
        with patch.object(self.mod, "read_mail_detail", return_value=(detail, "")):
            rows, state, diag = self.mod.collect_mail(browser, date(2026, 9, 1), date(2026, 9, 7), body=True,
                checkpoint=lambda rows: self.mod._save("mail", rows, True))
        self.assertEqual((len(rows), state, rows[0][1]), (1, "login", "2026-09-03 10:00"))
        self.assertEqual((diag["undated"], diag["body_rows"]), (1, 1))
        self.assertEqual(self.mod.read_csv(self.root / "data/collection_pending/outlook_web_undated.csv"), [])
        original, = [json.loads(path.read_text()) for path in (self.root / "data/communication_originals/mail").rglob("*.json")]
        self.assertEqual((original["time"], original["body"]), ("2026-09-03 10:00", "Observed body"))


if __name__ == "__main__":
    unittest.main()
