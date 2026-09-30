"""Synthetic explicit consent settings and full-text retention; no real tokens."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "LoadMonitor25/core"))
from communication_archive import archive_records
from communication_setup import connection_settings, import_options, save_connection


class CommunicationSetupTests(unittest.TestCase):
    def test_read_permissions_and_channels_are_explicit(self):
        body = {"client_id": "00000000-0000-4000-8000-000000000001", "tenant_id": "example.invalid"}
        base = connection_settings(body)
        self.assertIn("Mail.Read", base["scopes"])
        self.assertIn("Chat.Read", base["scopes"])
        self.assertNotIn("ChannelMessage.Read.All", base["scopes"])
        extended = connection_settings(dict(body, include_channels=True))
        self.assertIn("ChannelMessage.Read.All", extended["scopes"])
        self.assertFalse(any("Write" in scope for scope in extended["scopes"]))
        for invalid in (dict(body, tenant_id="../../outside"), dict(body, client_id="not-an-id"),
                        dict(body, include_channels="false")):
            with self.assertRaises(ValueError):
                connection_settings(invalid)

    def test_atomic_settings_preserve_unrelated_config_and_never_read_token(self):
        with tempfile.TemporaryDirectory(prefix="lm25-setup-") as temp:
            root = Path(temp)
            (root / "config").mkdir()
            path = root / "config/config.json"
            path.write_text(json.dumps({"owner": "Synthetic", "graph": {"advanced": 1}}), encoding="utf-8")
            save_connection(root, {"clientId": "SYNTHETIC"})
            self.assertEqual(json.loads(path.read_text()), {"owner": "Synthetic", "graph": {"advanced": 1, "clientId": "SYNTHETIC"}})
            self.assertFalse((root / "data").exists())

    def test_import_identity_is_per_request_and_count_zero_is_valid(self):
        config = {"collection": {"contextChars": 4000}}
        result = import_options({"own_addresses": ["synthetic@example.invalid"], "expected_count": 0}, config)
        self.assertEqual(result["collection"]["communicationImportExpectedCount"], 0)
        self.assertNotIn("communicationImportExpectedCount", config["collection"])
        for body in ({"expected_count": True}, {"expected_count": -1}, {"own_addresses": "a@b.invalid"},
                     {"own_addresses": ["not-an-email"]}):
            with self.assertRaises(ValueError):
                import_options(body, config)

    def test_long_body_retained_separately_and_update_is_idempotent(self):
        with tempfile.TemporaryDirectory(prefix="lm25-original-") as temp:
            row = {"body": "BEGIN " + "내용" * 30000 + " END", "source_id": "../../../hostile-id",
                   "account": "synthetic", "conversation_id": "room", "access_token": "NEVER STORE", "cookie": "NEVER STORE"}
            self.assertEqual(archive_records(temp, "teams", [row]), 1)
            archive_records(temp, "teams", [dict(row, body=row["body"] + " UPDATED")])
            files = list(Path(temp).rglob("*.json"))
            self.assertEqual(len(files), 1)
            saved = json.loads(files[0].read_text("utf-8"))
            self.assertEqual(saved["body"], row["body"] + " UPDATED")
            self.assertNotIn("NEVER STORE", json.dumps(saved))
            self.assertEqual(saved["schema"], "lm25.communication.original.v1")


if __name__ == "__main__":
    unittest.main()
