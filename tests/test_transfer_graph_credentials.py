"""Transfer only synthetic evidence, never app-owned Graph credentials."""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import zipfile


SOURCE = Path(__file__).resolve().parents[1] / "LoadMonitor25" / "tools" / "transfer.py"
SPEC = importlib.util.spec_from_file_location("lm25_transfer_credentials", SOURCE)
TRANSFER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TRANSFER)


class TransferGraphCredentialsTests(unittest.TestCase):
    def test_tokens_omitted_without_reading_but_data_and_resume_checkpoints_preserved(self):
        base = Path(tempfile.mkdtemp(prefix="lm25-transfer-credentials-"))
        root = base / "LoadMonitor25"
        output = base / "transfer.zip"
        excluded = ["data/graph_token.json", "data/추가PC/PC-A/graph_token.json",
                    "data/추가PC/PC-B/archive/GRAPH_TOKEN.JSON"]
        keep = {
            "config/config.json": '{"owner":"Synthetic"}',
            "data/outlook/mail.csv": "time,subject\n2026-09-01,Synthetic evidence\n",
            "data/graph_checkpoints/mail.json": '{"nextLink":"https://graph.microsoft.com/v1.0/me/messages?$skiptoken=synthetic-pagination"}',
            "data/추가PC/PC-A/graph_checkpoint.json": '{"completed":["synthetic-folder"]}',
            "data/communication_originals/mail/example.json": '{"body":"Synthetic original body"}',
            "docs/graph_token.json": '{"example":"documentation only"}',
        }
        for relative, content in {**keep, **dict.fromkeys(excluded, '{"access_token":"SYNTHETIC_SECRET_SENTINEL"}')}.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content.encode("utf-8"))
        before = {relative: (root / relative).read_bytes() for relative in excluded}
        token_paths = {(root / relative).resolve() for relative in excluded}
        original_open = Path.open

        def guarded_open(path, *args, **kwargs):
            self.assertNotIn(path.resolve(), token_paths, "Excluded tokens must never be opened")
            return original_open(path, *args, **kwargs)

        progress = []
        with mock.patch.object(Path, "open", guarded_open):
            plan = TRANSFER.plan_transfer(root, output)
            result = TRANSFER.create_transfer(root, output, progress=progress.append)
        self.assertEqual(plan["excluded_credentials"], {"graph_oauth_cache": 3})
        self.assertEqual(result["excluded_credentials"], plan["excluded_credentials"])
        self.assertEqual(result["file_count"], len(keep))
        self.assertEqual(result["total_bytes"], sum(len(value.encode("utf-8")) for value in keep.values()))
        with zipfile.ZipFile(output) as archive:
            for relative in excluded:
                self.assertNotIn(f"LoadMonitor25/{relative}", archive.namelist())
            for relative, content in keep.items():
                self.assertEqual(archive.read(f"LoadMonitor25/{relative}"), content.encode("utf-8"))
            manifest = json.loads(archive.read(result["manifest_entry"]))
            self.assertEqual(manifest["excluded_credentials"], {"graph_oauth_cache": 3})
            self.assertEqual({item["path"] for item in manifest["files"]}, set(keep))
            self.assertFalse(any(b"SYNTHETIC_SECRET_SENTINEL" in archive.read(name)
                                 for name in archive.namelist() if not name.endswith("/")))
        public = json.dumps([plan, result, manifest, progress], ensure_ascii=False)
        for relative in excluded:
            self.assertNotIn(relative, public)
        self.assertNotIn("SYNTHETIC_SECRET_SENTINEL", public)
        self.assertEqual(before, {relative: (root / relative).read_bytes() for relative in excluded})


if __name__ == "__main__":
    unittest.main()
