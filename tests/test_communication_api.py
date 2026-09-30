"""Exercise real API handler definitions with synthetic config and no services."""
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest

from test_transfer_ui import definitions

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "LoadMonitor25/core"))


class CommunicationApiTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="lm25-comm-api-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "config").mkdir()
        (self.root / "config/config.json").write_text('{"owner":"SYNTHETIC","graph":{}}', encoding="utf-8")
        self.env = definitions({"validate_run_request", "do_POST", "communication_watchdog"})
        self.started = []
        self.env.update(ROOT=str(self.root), cfg=lambda: json.loads((self.root / "config/config.json").read_text()),
                        run_job=lambda *args: None, import_communication_job=lambda *args: None,
                        communication_connection_job=lambda: None, communication_msg_job=lambda *args: None)
        self.env["threading"].Thread = lambda **kwargs: SimpleNamespace(start=lambda: self.started.append(kwargs))

    def post(self, route, extra=None, origin="http://127.0.0.1:8123"):
        body = {"from": "2026-09-01", "to": "2026-09-20", **(extra or {})}
        raw = json.dumps(body).encode()
        replies = []
        handler = SimpleNamespace(path="/api/communication/" + route, rfile=io.BytesIO(raw),
                headers={"Content-Length": str(len(raw)), "Content-Type": "application/json",
                         "Origin": origin, "Host": "127.0.0.1:8123"},
                _send=lambda *args: replies.append(args), _freezing=lambda: False)
        handler._do_POST = lambda: self.env["_do_POST"](handler)
        self.env["do_POST"](handler)
        return replies[0]

    def test_connect_saves_approved_settings_and_serializes_worker(self):
        response = self.post("connect", {"client_id": "00000000-0000-4000-8000-000000000001",
                                        "tenant_id": "example.invalid", "include_channels": True})
        self.assertEqual(response[0], 202)
        config = self.env["cfg"]()
        self.assertEqual(config["owner"], "SYNTHETIC")
        self.assertIn("Mail.Read", config["graph"]["scopes"])
        self.assertIn("ChannelMessage.Read.All", config["graph"]["scopes"])
        self.assertIs(self.started[0]["target"], self.env["communication_connection_job"])
        self.assertEqual(self.post("collect")[0], 409)
        self.assertEqual(len(self.started), 1)

    def test_invalid_and_cross_origin_input_never_starts_a_job(self):
        for route, body in (("connect", {"client_id": "invalid"}),
                            ("msg", {"paths": ["synthetic.pst"]}),
                            ("import", {"paths": ["synthetic.json"], "expected_count": True}),
                            ("import", {"paths": ["synthetic.json"], "own_addresses": ["invalid"]})):
            self.assertEqual(self.post(route, body)[0], 400)
            self.assertFalse(self.env["JOB"]["running"])
        self.assertEqual(self.post("collect", origin="https://example.invalid")[0], 400)
        self.assertEqual(self.started, [])

    def test_msg_is_explicit_and_keeps_options_in_worker(self):
        body = {"paths": ["D:/synthetic/message.msg"], "own_addresses": ["self@example.invalid"], "expected_count": 1}
        self.assertEqual(self.post("msg", body)[0], 202)
        request = self.started[0]
        self.assertIs(request["target"], self.env["communication_msg_job"])
        self.assertEqual(request["args"][0], body["paths"])
        self.assertEqual(request["args"][3]["expected_count"], 1)

    def test_watchdog_kills_only_its_live_worker(self):
        scheduled = []
        self.env["threading"].Event = threading.Event
        self.env["threading"].Timer = lambda delay, callback: SimpleNamespace(
            start=lambda: scheduled.append((delay, callback)), cancel=lambda: None)
        killed = []
        process = SimpleNamespace(poll=lambda: None, kill=lambda: killed.append("own-worker"))
        _, expired = self.env["communication_watchdog"](process, 330)
        self.assertEqual(scheduled[0][0], 330)
        scheduled[0][1]()
        self.assertTrue(expired.is_set())
        self.assertEqual(killed, ["own-worker"])
        process.poll = lambda: 0
        scheduled[0][1]()
        self.assertEqual(killed, ["own-worker"])


if __name__ == "__main__":
    unittest.main()
