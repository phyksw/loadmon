"""Graph OAuth, pagination, mail and channel fixtures; never real tokens/services."""
import contextlib
from datetime import UTC
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

PRODUCT = Path(__file__).resolve().parents[1] / "LoadMonitor25"
sys.path.insert(0, str(PRODUCT / "core"))
from collection_state import read_csv  # noqa: E402
from graph_client import GraphAuth, GraphBudget, GraphClient, GraphError, GRAPH  # noqa: E402


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), PRODUCT / "collect" / name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class GraphFixture(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="lm25-graph-server-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.config = {"graph": {"clientId": "12345678-1234-1234-1234-123456789012", "tenantId": "organizations",
                                 "scopes": ["User.Read", "Mail.Read", "Chat.Read", "offline_access"]},
                       "collection": {"contextChars": 4000}}
        self.mail = load("Get-OutlookGraph.py")
        self.teams = load("Get-TeamsChats.py")
        self.teams.ROOT = str(self.root)
        self.teams.OUT_DIR = str(self.root / "data/m365")
        self.teams.LOCAL_TZ = UTC

    def status(self, source):
        return json.loads((self.root / "data/collection_status" / (source + ".json")).read_text("utf-8"))

    def mail_message(self, identity="one", sender="manager@example.invalid", recipient="me@example.invalid"):
        return {"id": identity, "subject": "Review", "from": {"emailAddress": {"address": sender}},
                "toRecipients": [{"emailAddress": {"address": recipient}}], "parentFolderId": "custom-folder",
                "receivedDateTime": "2026-06-03T10:00:00Z", "sentDateTime": "2026-06-03T09:59:00Z",
                "conversationId": "thread", "internetMessageId": "<one@example.invalid>",
                "body": {"contentType": "text", "content": "first " + "body " * 1300 + "FINAL DECISION"}}

    def mail_client(self, responder, clock=None):
        def getter(url, token, **kwargs):
            if "/me?" in url:
                return {"id": "me", "mail": "me@example.invalid", "otherMails": ["alias@example.invalid"]}
            if "/mailFolders/sentitems?" in url:
                return {"id": "sent-folder"}
            return responder(url, token, **kwargs)
        return GraphClient("synthetic-token", getter=getter, headers=self.mail.HEADERS, clock=clock)

    def collect_mail(self, client, **kwargs):
        return self.mail.collect(self.root, self.config, "2026-06-01", "2026-06-30", client=client, tz=UTC, **kwargs)

    def collect_teams(self, responder, **kwargs):
        with patch.object(self.teams, "load_cfg", return_value=self.config), \
                patch.object(self.teams, "acquire_token", return_value=("synthetic-token", None)), \
                patch.object(self.teams, "get_json", side_effect=responder), contextlib.redirect_stdout(io.StringIO()):
            return self.teams.collect("2026-06-01", "2026-06-30", interactive=False, **kwargs)

    @staticmethod
    def team_message(identity, day="2026-06-03", body="Review then approve."):
        return {"id": identity, "createdDateTime": day + "T10:00:00Z", "body": {"contentType": "text", "content": body},
                "from": {"user": {"id": "person", "displayName": "Synthetic person"}}}

    def test_mail_all_folder_ranges_dedup_immutable_header_and_full_body(self):
        requests = []
        def response(url, token, **kwargs):
            requests.append((url, kwargs))
            return {"value": [self.mail_message()]}
        result = self.collect_mail(self.mail_client(response))
        self.assertEqual((result["status"], result["rows"], result["observed_records"]), ("complete", 1, 2))
        self.assertTrue(any("receivedDateTime" in url for url, _ in requests))
        self.assertTrue(any("sentDateTime" in url for url, _ in requests))
        self.assertTrue(all('IdType="ImmutableId"' in kw["headers"]["Prefer"] for _, kw in requests))
        rows = read_csv(self.root / "data/outlook/mail.csv")
        self.assertEqual((rows[0]["folder"], len(rows[0]["context_excerpt"])), ("custom-folder", 4000))
        original = json.loads(next((self.root / "data/communication_originals/mail").rglob("*.json")).read_text("utf-8"))
        self.assertTrue(original["body"].endswith("FINAL DECISION"))

    def test_mail_sent_moved_to_custom_folder_uses_sent_date_and_alias(self):
        message = self.mail_message(sender="alias@example.invalid", recipient="other@example.invalid")
        message["receivedDateTime"] = "2026-05-31T23:00:00Z"
        result = self.collect_mail(self.mail_client(lambda *a, **k: {"value": [message]}))
        self.assertEqual(result["rows"], 1)
        row = read_csv(self.root / "data/outlook/mail.csv")[0]
        self.assertEqual((row["box"], row["time"]), ("sent", "2026-06-03 09:59:00"))

    def test_mail_local_period_excludes_end_midnight_even_if_server_returns_it(self):
        inside = self.mail_message("inside")
        inside["receivedDateTime"] = "2026-06-30T23:59:59.9999997Z"
        outside = self.mail_message("outside")
        outside["receivedDateTime"] = "2026-07-01T00:00:00Z"
        self.collect_mail(self.mail_client(lambda *a, **k: {"value": [inside, outside]}))
        rows = read_csv(self.root / "data/outlook/mail.csv")
        self.assertEqual([row["source_id"] for row in rows], ["outlook-graph:inside"])

    def test_token_with_missing_granted_scope_cannot_satisfy_new_permission_request(self):
        auth = GraphAuth(self.root, self.config, clock=lambda: 1000)
        with patch("graph_client.subprocess.run"):
            auth.save({"access_token": "synthetic-chat-only", "expires_in": 3600, "scope": "User.Read Chat.Read"})
        token, reason = auth.acquire(False)
        self.assertIsNone(token)
        self.assertIn("consent_required", reason)

    def test_mail_body_privacy_option_and_zero_context_do_not_archive_or_request_body(self):
        for options in ({"mailBody": False}, {"contextChars": 0}):
            with self.subTest(options=options):
                self.config["collection"] = options
                requests = []
                def response(url, token, **kwargs):
                    requests.append(url)
                    return {"value": [self.mail_message()]}
                result = self.collect_mail(self.mail_client(response))
                self.assertFalse(result["body_requested"])
                self.assertTrue(result["enumeration_complete"])
                self.assertEqual(result["status"], "partial")
                self.assertTrue(all(",body," not in url for url in requests))
                self.assertFalse((self.root / "data/communication_originals/mail").exists())
                self.assertTrue(all(not row["context_excerpt"] for row in read_csv(self.root / "data/outlook/mail.csv")))

    def test_newer_missing_body_keeps_saved_original_but_explicit_empty_updates_it(self):
        message = self.mail_message()
        message["lastModifiedDateTime"] = "2026-06-03T10:00:00Z"
        client = self.mail_client(lambda *a, **k: {"value": [message]})
        self.collect_mail(client)
        original_path = next((self.root / "data/communication_originals/mail").rglob("*.json"))
        original_body = json.loads(original_path.read_text("utf-8"))["body"]
        message["lastModifiedDateTime"] = "2026-06-04T10:00:00Z"
        message.pop("body")
        missing = self.collect_mail(client)
        self.assertEqual(missing["status"], "partial")
        self.assertTrue(read_csv(self.root / "data/outlook/mail.csv")[0]["context_excerpt"])
        self.assertEqual(json.loads(original_path.read_text("utf-8"))["body"], original_body)
        message["lastModifiedDateTime"] = "2026-06-05T10:00:00Z"
        message["body"] = {"contentType": "text", "content": ""}
        self.collect_mail(client)
        row = read_csv(self.root / "data/outlook/mail.csv")[0]
        self.assertEqual((row["context_available"], row["context_excerpt"]), ("true", ""))
        self.assertEqual(json.loads(original_path.read_text("utf-8"))["body"], "")

    def test_mail_resume_second_page_without_starting_first_again(self):
        clock, calls = [0.0], []
        following = GRAPH + "/me/messages?$skiptoken=next"
        def response(url, token, **kwargs):
            calls.append(url)
            clock[0] += 1
            if "$skiptoken" in url:
                return {"value": [self.mail_message("two")]}
            if "$filter=received" in url:
                return {"value": [self.mail_message()], "@odata.nextLink": following}
            return {"value": []}
        client = self.mail_client(response, clock=lambda: clock[0])
        first = self.collect_mail(client, budget=1)
        self.assertEqual(first["status"], "partial")
        calls.clear()
        second = self.collect_mail(client, budget=10)
        self.assertEqual((second["status"], second["rows"]), ("complete", 2))
        self.assertIn(following, calls)
        self.assertFalse(any("$filter=received" in url for url in calls))

    def test_failed_archive_does_not_advance_page_checkpoint(self):
        client = self.mail_client(lambda *a, **k: {"value": [self.mail_message()]})
        with patch.object(self.mail, "archive_records", side_effect=OSError("synthetic write failure")):
            first = self.collect_mail(client)
        self.assertNotEqual(first["status"], "complete")
        self.assertFalse(list((self.root / "data/graph_checkpoints").glob("*.json")))
        second = self.collect_mail(client)
        self.assertEqual((second["status"], second["rows"]), ("complete", 1))

    def test_channels_old_root_replies_all_pages_and_separate_chat_scope(self):
        more = GRAPH + "/teams/t/channels/c/messages/old/replies?$skiptoken=next"
        def response(url, token, **kwargs):
            if url.endswith("/me"):
                return {"id": "me"}
            if "/me/chats" in url:
                return {"value": []}
            if "/me/joinedTeams" in url:
                return {"value": [{"id": "t", "displayName": "Team"}]}
            if "/channels?" in url:
                return {"value": [{"id": "c", "displayName": "Channel"}]}
            if url == more:
                return {"value": [self.team_message("r2", body="Approved.")]}
            if "/replies" in url:
                return {"value": [self.team_message("r1")], "@odata.nextLink": more}
            return {"value": [self.team_message("old", "2026-05-01")]}
        self.collect_teams(response, include_channels=True)
        result = self.status("teams_graph")
        self.assertEqual((result["status"], result["chats_status"], result["channels_status"]), ("complete", "complete", "complete"))
        rows = read_csv(self.root / "data/m365/teams_chats.csv")
        self.assertEqual({row["message_id"] for row in rows}, {"r1", "r2"})
        self.assertTrue(all(row["reply_to_id"] == "old" for row in rows))

    def test_channels_denied_does_not_certify_complete_teams(self):
        def response(url, token, **kwargs):
            if url.endswith("/me"):
                return {"id": "me"}
            if "/me/chats" in url:
                return {"value": []}
            raise HTTPError(url, 403, "forbidden", {}, None)
        self.collect_teams(response, include_channels=True)
        result = self.status("teams_graph")
        self.assertEqual(result["chats_status"], "complete")
        self.assertNotEqual(result["channels_status"], "complete")
        self.assertFalse(result["full_requested_scope_complete"])
        self.assertEqual(result["denied_units"], 1)

    def test_denied_channel_does_not_freeze_successful_chats_on_next_run(self):
        current = ["one"]
        def response(url, token, **kwargs):
            if url.endswith("/me"):
                return {"id": "me"}
            if "/me/chats" in url:
                return {"value": [{"id": "chat"}]}
            if "/me/joinedTeams" in url:
                raise HTTPError(url, 403, "forbidden", {}, None)
            return {"value": [self.team_message(identity) for identity in current]}
        self.collect_teams(response, include_channels=True)
        current.append("two")
        self.collect_teams(response, include_channels=True)
        self.assertEqual(self.status("teams_graph")["rows"], 2)
        self.assertFalse(self.status("teams_graph")["full_requested_scope_complete"])

    def test_unknown_mail_direction_is_not_assigned_to_inbox_or_timed_work(self):
        message = self.mail_message(sender="unrecognized@example.invalid", recipient="elsewhere@example.invalid")
        self.collect_mail(self.mail_client(lambda *a, **k: {"value": [message]}))
        row = read_csv(self.root / "data/outlook/mail.csv")[0]
        self.assertEqual((row["box"], row["time_precision"]), ("unknown", "unknown"))

    def test_explicit_message_cap_resumes_inside_page(self):
        def response(url, token, **kwargs):
            if url.endswith("/me"):
                return {"id": "me"}
            if "/me/chats" in url:
                return {"value": [{"id": "chat"}]}
            return {"value": [self.team_message("one"), self.team_message("two")]}
        self.collect_teams(response, max_msgs=1)
        self.assertEqual(self.status("teams_graph")["rows"], 1)
        self.collect_teams(response, max_msgs=1)
        self.assertEqual(self.status("teams_graph")["rows"], 2)
        self.assertEqual(self.status("teams_graph")["status"], "complete")
        self.assertFalse(self.status("teams_graph")["full_requested_scope_complete"])

    def test_token_binding_prevents_other_app_refresh_and_retains_omitted_refresh_token(self):
        now = 1000
        auth = GraphAuth(self.root, self.config, clock=lambda: now)
        with patch("graph_client.subprocess.run"):
            auth.save({"access_token": "synthetic-old", "refresh_token": "synthetic-refresh", "expires_in": 0,
                       "scope": "User.Read Mail.Read Chat.Read"})
        other = dict(self.config, graph=dict(self.config["graph"], clientId="22345678-1234-1234-1234-123456789012"))
        poster_calls = []
        other_auth = GraphAuth(self.root, other, poster=lambda *a: poster_calls.append(a), clock=lambda: now)
        self.assertIsNone(other_auth.acquire(False)[0])
        self.assertEqual(poster_calls, [])
        auth.poster = lambda *args: ({"access_token": "synthetic-new", "expires_in": 3600,
                                      "scope": "User.Read Mail.Read Chat.Read"}, None)
        with patch("graph_client.subprocess.run"):
            self.assertEqual(auth.acquire(False)[0], "synthetic-new")
        self.assertEqual(auth.load()["refresh_token"], "synthetic-refresh")


class GraphHttpTests(unittest.TestCase):
    def test_expired_access_token_refreshes_once_without_leaking_raw_error(self):
        tokens = []
        def getter(url, token, **kwargs):
            tokens.append(token)
            if token == "synthetic-expired":
                raise HTTPError(url, 401, "PRIVATE ERROR SHOULD NOT BE LOGGED", {}, None)
            return {"id": "me"}
        client = GraphClient("synthetic-expired", getter=getter, refresh=lambda: ("synthetic-fresh", None))
        self.assertEqual(client.get(GRAPH + "/me", float("inf")), {"id": "me"})
        self.assertEqual(tokens, ["synthetic-expired", "synthetic-fresh"])

    def test_retry_after_429_and_503_then_success(self):
        clock, sleeps, calls = [0.0], [], []
        def getter(url, token, **kwargs):
            calls.append(url)
            if len(calls) < 3:
                raise HTTPError(url, 429 if len(calls) == 1 else 503, "retry", {"Retry-After": "2"}, None)
            return {"value": []}
        def sleep(seconds):
            sleeps.append(seconds)
            clock[0] += seconds
        client = GraphClient("synthetic", getter=getter, clock=lambda: clock[0], sleep=sleep)
        self.assertEqual(client.get(GRAPH + "/me/messages", 10), {"value": []})
        self.assertEqual((len(calls), sleeps), (3, [2, 2]))

    def test_untrusted_nextlink_never_reaches_transport_and_retry_budget_honored(self):
        calls = []
        client = GraphClient("synthetic", getter=lambda *a, **k: calls.append(a))
        for url in ("next-page", "http://graph.microsoft.com/v1.0/me", "https://evil.invalid/v1.0/me",
                    "https://graph.microsoft.com@evil.invalid/v1.0/me"):
            with self.assertRaises(GraphError):
                client.get(url, float("inf"))
        self.assertEqual(calls, [])
        def throttled(url, token, **kwargs):
            raise HTTPError(url, 429, "retry", {"Retry-After": "600"}, None)
        client = GraphClient("synthetic", getter=throttled, clock=lambda: 0,
                             sleep=lambda _: self.fail("must not sleep beyond budget"))
        with self.assertRaises(GraphBudget):
            client.get(GRAPH + "/me/messages", 30)


if __name__ == "__main__":
    unittest.main()
