"""Teams collection contracts; copied code and synthetic TEMP data only."""
import contextlib
import csv
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import HTTPError

PROJECT = Path(__file__).resolve().parents[1]
PRODUCT = PROJECT / "LoadMonitor25"


class TeamsCollectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="lm25-teams-fixture-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for folder in ("collect", "core", "config"):
            (self.root / folder).mkdir()
        for name in ("Get-TeamsWeb.py", "Get-OutlookWeb.py", "Get-TeamsChats.py",
                     "Get-TeamsViaCopilot.py", "Get-TeamsWindow.ps1"):
            shutil.copyfile(PRODUCT / "collect" / name, self.root / "collect" / name)
        shutil.copyfile(PRODUCT / "core/collection_state.py", self.root / "core/collection_state.py")
        (self.root / "config/config.json").write_text(json.dumps({
            "owner": "Synthetic", "teamsSelfNames": ["Synthetic"],
            "collection": {"contextChars": 4000}, "teamsWebMaxChats": 200}), encoding="utf-8")

    def module(self, filename):
        spec = importlib.util.spec_from_file_location("synthetic_" + filename.replace("-", "_"),
                                                     self.root / "collect" / filename)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def read_rows(self, filename):
        with (self.root / "data/m365" / filename).open(encoding="utf-8-sig", newline="") as stream:
            return list(csv.DictReader(stream))

    def status(self, source):
        return json.loads((self.root / f"data/collection_status/{source}.json").read_text("utf-8-sig"))

    @staticmethod
    def message(day, body="Synthetic message", mid=""):
        return {"n": 1, "chat": "Synthetic chat", "how": "fixture", "items": [
            {"t": "msg", "author": "Person", "ts": day + " 09:00", "body": body, "id": mid}]}

    def web_fake(self, data, *args):
        fixture = self.root / "fixture.json"
        fixture.write_text(json.dumps(data), encoding="utf-8")
        result = subprocess.run([sys.executable, "-B", str(self.root / "collect/Get-TeamsWeb.py"),
                                 "--from", "2026-06-01", "--to", "2026-06-30", *args],
                                env=dict(os.environ, LM_NO_BROWSER="1", LM_TEAMSWEB_FAKE=str(fixture)),
                                capture_output=True, text=True, encoding="utf-8", timeout=30, check=False)
        return result

    def test_old_period_keeps_scrolling_past_two_recent_screens(self):
        m = self.module("Get-TeamsWeb.py")
        fake = {"0": [self.message("2026-09-20"), self.message("2026-09-19"), self.message("2026-06-03")]}
        rows, _ = m.read_chat(None, 0, "Synthetic chat", date(2026, 6, 1), date(2026, 6, 30),
                              date(2026, 9, 30), fake=fake)
        self.assertEqual([r["time"] for r in rows], ["2026-06-03 09:00"])

    def test_same_time_body_on_different_days_is_not_deduplicated(self):
        m = self.module("Get-TeamsWeb.py")
        rows, _ = m.read_chat(None, 0, "Synthetic chat", date(2026, 6, 1), date(2026, 6, 30),
                              date(2026, 9, 30), fake={"0": [self.message("2026-06-03"), self.message("2026-06-02")]})
        self.assertEqual(len(rows), 2)
        self.assertNotEqual(m.key_of(rows[0]["time"], "Person", "chat", "same"),
                            m.key_of(rows[1]["time"], "Person", "chat", "same"))

    def test_web_top_waits_for_lazy_history_and_never_assumes_today(self):
        m = self.module("Get-TeamsWeb.py")
        screens = iter([self.message("2026-09-20"), self.message("2026-06-03"), self.message("2026-05-31")])
        browser = SimpleNamespace(eval_json=lambda _: next(screens), cdp=SimpleNamespace(eval=lambda _: "top"))
        with patch.object(m, "wait_pane", return_value=("Synthetic chat", 1)):
            rows, _ = m.read_chat(browser, 0, "Synthetic chat", date(2026, 6, 1), date(2026, 6, 30),
                                  date(2026, 9, 30))
        self.assertEqual([r["time"] for r in rows], ["2026-06-03 09:00"])
        stamp, reason = m.stamp(["09:00"], ["yesterday meeting"], None, date(2026, 9, 1),
                                date(2026, 9, 30), date(2026, 9, 30))
        self.assertIsNone(stamp, reason)

    def test_web_does_not_attribute_old_pane_to_new_chat_when_count_changes(self):
        m = self.module("Get-TeamsWeb.py")
        item = {"idx": 0, "key": "new", "name": "New room", "conversation_id": "new-id"}
        browser = SimpleNamespace(start=lambda: True, goto=lambda _: "ok", close=lambda: None,
                                  cdp=SimpleNamespace(eval=lambda js: "ok" if "const key" in js else "end"),
                                  eval_json=lambda js: {"items": [item]} if js == m.JS_CHATS else {"chat": "Old room", "n": 2})
        with patch.object(m, "Browser", return_value=browser), patch.object(m, "read_chat") as read, \
                patch.object(m, "wait_pane", return_value=("Old room", 2)), \
                patch.dict(os.environ, {"LM_NO_BROWSER": "", "LM_TEAMSWEB_FAKE": ""}), \
                patch.object(sys, "argv", ["collector", "--from", "2026-06-01", "--to", "2026-06-30"]), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(m.main(), 1)
            read.assert_not_called()
        self.assertIn("chat_switch_unconfirmed", self.status("teams_web")["reasons"])
        self.assertFalse(m.pane_matches(item, "New room", {"chat": "New room", "conversation_id": "wrong-id"}))
        self.assertTrue(m.pane_matches(item, "New room", {"chat": "New room"}))

    def test_virtual_list_second_page_with_reused_indices_and_context(self):
        body = "Detailed context " * 400
        fake = {"chat_pages": [{"items": [{"idx": 0, "key": "chat-a", "label": "A"}]},
                               {"items": [{"idx": 0, "key": "chat-b", "label": "B"}]}],
                "msgs": {"chat-a": [self.message("2026-06-03", body, "a")],
                         "chat-b": [self.message("2026-06-02", "second conversation", "b")]}}
        result = self.web_fake(fake)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        rows = self.read_rows("teams_web.csv")
        self.assertEqual(len(rows), 2)
        first = next(r for r in rows if r["source_id"].endswith("/a"))
        self.assertEqual(len(first["summary"]), 200)
        self.assertEqual(len(first["context_excerpt"]), 4000)
        self.assertEqual(first["context_truncated"], "true")
        self.assertEqual(self.status("teams_web")["status"], "partial")

    def test_page_failure_keeps_first_saved_page_and_previous_legacy_rows(self):
        target = self.root / "data/m365/teams_web.csv"
        target.parent.mkdir(parents=True)
        target.write_text("time,from,chat,kind,replied_time,summary\n2026-05-01 09:00,Old,Old,msg,,old text\n", "utf-8")
        fake = {"chats": {"items": [{"idx": 0, "key": "a"}]},
                "msgs": {"a": [self.message("2026-06-03"), 42]}}
        result = self.web_fake(fake)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(len(self.read_rows("teams_web.csv")), 2)
        status = self.status("teams_web")
        self.assertEqual(status["status"], "partial")
        self.assertTrue(any("collection_error" in r for r in status["reasons"]))

    def test_chat_cap_persists_progress_and_next_run_reaches_remaining_chat(self):
        fake = {"chats": {"items": [{"idx": 0, "key": "a"}, {"idx": 1, "key": "b"}]},
                "msgs": {"a": [self.message("2026-06-03")], "b": [self.message("2026-06-02")]}}
        result = self.web_fake(fake, "--max-chats", "1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("chat_limit", self.status("teams_web")["reasons"])
        self.assertEqual(self.status("teams_web")["processed_chat_keys"], ["a"])
        result = self.web_fake(fake, "--max-chats", "1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.read_rows("teams_web.csv")), 2)

    def graph(self, responder, **kwargs):
        m = self.module("Get-TeamsChats.py")
        m.LOCAL_TZ = UTC
        with patch.object(m, "acquire_token", return_value=("synthetic-token", None)), \
                patch.object(m, "get_json", side_effect=responder), contextlib.redirect_stdout(io.StringIO()):
            result = m.collect("2026-06-01", "2026-06-30", interactive=False, **kwargs)
        return m, result

    @staticmethod
    def graph_message(mid, day="2026-06-03"):
        return {"id": mid, "createdDateTime": day + "T09:00:00Z", "body": {"content": "Synthetic body"},
                "from": {"user": {"id": "person", "displayName": "Person"}}}

    def test_graph_keeps_existing_bom_config_and_context_settings(self):
        (self.root / "config/config.json").write_text(json.dumps({
            "graph": {"clientId": "synthetic-client", "tenantId": "synthetic-tenant", "scopes": ["Chat.Read"]},
            "collection": {"contextChars": 1200}}), encoding="utf-8-sig")
        m = self.module("Get-TeamsChats.py")
        self.assertEqual(m.graph_cfg(), ("synthetic-client", "synthetic-tenant", ["Chat.Read"]))
        self.assertEqual(m.load_cfg()["collection"]["contextChars"], 1200)

    def test_graph_forbidden_message_page_is_partial_and_preserves_earlier_page(self):
        def response(url, _token, **_):
            if url.endswith("/me"):
                return {"id": "me"}
            if "/me/chats" in url:
                return {"value": [{"id": "chat"}]}
            if url == "next-page":
                raise HTTPError(url, 403, "Forbidden", None, None)
            return {"value": [self.graph_message("1")], "@odata.nextLink": "next-page"}
        self.graph(response)
        self.assertEqual(len(self.read_rows("teams_chats.csv")), 1)
        self.assertEqual(self.status("teams_graph")["status"], "partial")
        self.assertIn("messages_failed:403", self.status("teams_graph")["reasons"])

    def test_graph_old_creation_on_page_does_not_hide_newer_next_message(self):
        def response(url, _token, **_):
            if url.endswith("/me"):
                return {"id": "me"}
            if "/me/chats" in url:
                return {"value": [{"id": "chat"}]}
            return {"value": [self.graph_message("old", "2026-05-01"), self.graph_message("new")]}
        self.graph(response)
        self.assertEqual([r["source_id"] for r in self.read_rows("teams_chats.csv")], ["graph:chat/new"])
        self.assertEqual(self.status("teams_graph")["status"], "complete")

    def test_graph_zero_error_is_not_complete_but_successful_empty_is(self):
        def error(url, _token, **_):
            if url.endswith("/me"):
                return {"id": "me"}
            raise HTTPError(url, 403, "Forbidden", None, None)
        self.graph(error)
        self.assertEqual(self.status("teams_graph")["status"], "failed")
        self.graph(lambda url, _token, **_: {"id": "me"} if url.endswith("/me") else {"value": []})
        self.assertEqual(self.status("teams_graph")["status"], "complete")
        self.assertEqual(self.read_rows("teams_chats.csv"), [])

    def test_graph_cap_does_not_claim_complete(self):
        def response(url, _token, **_):
            if url.endswith("/me"):
                return {"id": "me"}
            if "/me/chats" in url:
                return {"value": [{"id": "chat"}]}
            return {"value": [self.graph_message("1"), self.graph_message("2")]}
        self.graph(response, max_msgs=1)
        self.assertEqual(len(self.read_rows("teams_chats.csv")), 1)
        self.assertIn("message_limit", self.status("teams_graph")["reasons"])

    def test_graph_rejected_filter_falls_back_and_includes_midnight(self):
        urls = []

        def response(url, _token, **_):
            urls.append(url)
            if url.endswith("/me"):
                return {"id": "me"}
            if "/me/chats" in url:
                return {"value": [{"id": "chat"}]}
            if "$filter" in url:
                raise HTTPError(url, 400, "Unsupported filter", None, None)
            message = self.graph_message("midnight")
            message["createdDateTime"] = "2026-06-01T00:00:00Z"
            return {"value": [message]}

        self.graph(response)
        self.assertTrue(any("2026-05-31T23:59:59Z" in url for url in urls))
        self.assertEqual(self.status("teams_graph")["status"], "complete")
        self.assertEqual(self.read_rows("teams_chats.csv")[0]["time"], "2026-06-01 00:00")

    def test_graph_invalid_response_is_reported_without_claiming_complete(self):
        self.graph(lambda url, _token, **_: {"id": "me"} if url.endswith("/me") else [])
        self.assertEqual(self.status("teams_graph")["status"], "failed")
        self.assertIn("chat_list_invalid", self.status("teams_graph")["reasons"])

    def test_copilot_save_is_union_not_replacement_and_does_not_invent_ids(self):
        m = self.module("Get-TeamsViaCopilot.py")
        m._save_rows([["2026-06-03 09:00", "Person", "Room", "msg", "", "First"]])
        m._save_rows([["2026-06-04 09:00", "Person", "Room", "msg", "", "Second"]])
        rows = self.read_rows("teams_copilot.csv")
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r["source_id"] == "" and r["time_precision"] == "ai_reported" for r in rows))

    def test_app_replay_preserves_extended_csv_and_marks_estimated_dates(self):
        shell = shutil.which("powershell")
        self.assertIsNotNone(shell, "PowerShell is required for the app CSV compatibility test")
        replay = self.root / "data/m365/replay"
        replay.mkdir(parents=True)
        target = replay / "teams_window.csv"
        target.write_text("time,from,chat,kind,replied_time,summary,context_excerpt,source_id\n"
                          "2026-06-01 09:00,Old,Old,msg,,old summary,old context,old-id\n", "utf-8")
        raw = self.root / "synthetic_raw.txt"
        raw.write_text("Synthetic chat\nPerson, 9:00 AM " + "Detailed body " * 250 + "\n", "utf-8")
        now = time.time()
        os.utime(raw, (now, now))
        result = subprocess.run([shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                                 str(self.root / "collect/Get-TeamsWindow.ps1"), "-RawFile", str(raw),
                                 "-From", "2026-01-01", "-To", datetime.now(UTC).date().isoformat()],
                                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        with target.open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(rows[0]["summary"], "old summary")
        self.assertEqual(rows[0]["source_id"], "old-id")
        new = next(r for r in rows if r["source_kind"] == "teams_app")
        self.assertGreater(len(new["context_excerpt"]), 200)
        self.assertEqual(new["time_precision"], "estimated")
        status = json.loads((replay / "collection_status/teams_app.json").read_text("utf-8-sig"))
        self.assertEqual(status["status"], "partial")
        # A previous six-column observation must gain context when seen again.
        with target.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=["time", "from", "chat", "kind", "replied_time", "summary"],
                                    extrasaction="ignore")
            writer.writeheader()
            writer.writerow(new)
        second = subprocess.run(result.args, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                timeout=30, check=False)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        with target.open(encoding="utf-8-sig", newline="") as stream:
            refreshed = list(csv.DictReader(stream))
        self.assertEqual(len(refreshed), 1)
        self.assertGreater(len(refreshed[0]["context_excerpt"]), 200)

    def test_app_preserves_same_summary_with_different_long_context_across_runs(self):
        shell = shutil.which("powershell")
        raw = self.root / "synthetic_long_messages.txt"
        prefix = "Common body context " * 25
        raw.write_text("Synthetic chat\nPerson, 9:00 AM " + prefix + "Alpha decision\n"
                       "Person, 9:00 AM " + prefix + "Beta decision\n", encoding="utf-8")
        args = [shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                str(self.root / "collect/Get-TeamsWindow.ps1"), "-RawFile", str(raw),
                "-From", "2026-01-01", "-To", datetime.now(UTC).date().isoformat()]
        for _ in range(2):
            result = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                    timeout=30, check=False)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            with (self.root / "data/m365/replay/teams_window.csv").open(encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["summary"], rows[1]["summary"])
            self.assertEqual(len({r["context_excerpt"] for r in rows}), 2)


if __name__ == "__main__":
    unittest.main()
