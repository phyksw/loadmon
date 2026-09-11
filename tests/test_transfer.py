"""Safety tests for PC-transfer archives; all inputs are synthetic TEMP files."""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zipfile


SOURCE = Path(__file__).resolve().parents[1] / "LoadMonitor25" / "tools" / "transfer.py"
SPEC = importlib.util.spec_from_file_location("lm25_transfer_test_module", SOURCE)
TRANSFER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TRANSFER)


class TransferTests(unittest.TestCase):
    def setUp(self):
        # Retain exclusively synthetic folders; never recursively delete paths.
        self.base = Path(tempfile.mkdtemp(prefix="lm25-transfer-test-"))
        self.root = self.base / "LoadMonitor25"
        self.root.mkdir()
        self.output = self.base / "transfer.zip"
        self.write("config/config.json", '{"owner":"Synthetic"}')
        self.write("data/files/files.csv", "name,time\nexample,2026-09-01\n")

    def write(self, relative, text="synthetic"):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def assert_no_archive(self):
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.base.glob(".lm25-transfer-*.tmp")), [])

    def test_core_state_preserved_manifest_hashes_and_single_root(self):
        keep = ["data/pc_name.txt", "data/추가PC/PC-A/pc/pc_on.csv", "data/manual/worklog.csv",
                "data/graph_token.json", "data/custom_cache.json", "report/upload_pending/p.json",
                "report/upload_sent/s.json", "report/ai_judgments.json", "report/보완툴/detail_aliases.json",
                "config/excluded_work.json", "config/detail_aliases.json", "teamdata/member.json",
                "python/python.exe", "logs/anything.log", "cache/important.json", "docs/copilot_profile/keep.txt"]
        for name in keep:
            self.write(name)
        (self.root / "empty_directory").mkdir()
        excluded = ["data/copilot_profile/Default/cache", "data/추가PC/PC-A/copilot_profile/Cookies",
                    "core/__pycache__/x.pyc", ".git/objects/large", ".ruff_cache/file", ".pytest_cache/file"]
        for name in excluded:
            self.write(name, "omit")
        before = {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        result = TRANSFER.create_transfer(self.root, self.output)
        with zipfile.ZipFile(self.output) as archive:
            names = archive.namelist()
            self.assertEqual(len(names), len(set(names)))
            self.assertTrue(all(name.startswith("LoadMonitor25/") for name in names))
            self.assertIn("LoadMonitor25/empty_directory/", names)
            for name in keep:
                self.assertIn("LoadMonitor25/" + name, names)
            for name in excluded:
                self.assertNotIn("LoadMonitor25/" + name, names)
            manifest = json.loads(archive.read(result["manifest_entry"]))
            for item in manifest["files"]:
                content = archive.read("LoadMonitor25/" + item["path"])
                self.assertEqual(hashlib.sha256(content).hexdigest(), item["sha256"])
                self.assertEqual(len(content), item["size"])
                self.assertEqual((self.root / item["path"]).stat().st_mtime_ns, item["mtime_ns"])
        self.assertEqual(result["processed_files"], result["file_count"])
        self.assertEqual(result["processed_bytes"], result["total_bytes"])
        self.assertEqual(result["zip_sha256"], hashlib.sha256(self.output.read_bytes()).hexdigest())
        after = {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(before, after)

    def test_plan_does_not_write_or_traverse_profiles(self):
        profile = self.write("data/copilot_profile/Default/large", "x").parents[1]
        scan = os.scandir

        def guarded(path):
            self.assertFalse(Path(path).is_relative_to(profile))
            return scan(path)

        with mock.patch.object(TRANSFER.os, "scandir", side_effect=guarded):
            plan = TRANSFER.plan_transfer(self.root, self.output)
        self.assertEqual(plan["status"], "planned")
        self.assertFalse(plan["excluded_contents_scanned"])
        self.assert_no_archive()

    def test_cache_names_preserved_in_data_and_user_folders(self):
        names = ("__pycache__", ".ruff_cache", ".pytest_cache", ".git")
        parents = ("data/추가PC", "data", "config", "report", "teamdata",
                   "user research", "docs", "saved/core")
        keep = [f"{parent}/{name}/manual/worklog.csv" for parent in parents for name in names]
        for path in keep:
            self.write(path, "user evidence")
        result = TRANSFER.create_transfer(self.root, self.output)
        with zipfile.ZipFile(self.output) as archive:
            for path in keep:
                self.assertEqual(archive.read("LoadMonitor25/" + path), b"user evidence")
            manifest = json.loads(archive.read(result["manifest_entry"]))
        self.assertEqual(result["excluded_dirs"], [])
        self.assertTrue(set(keep).issubset(item["path"] for item in manifest["files"]))

    def test_cache_exclusion_scoped_to_root_and_known_code_trees(self):
        names = ("__pycache__", ".ruff_cache", ".pytest_cache", ".git")
        parents = ("", "core/package", "ui", "tools/package", "collect", "python/Lib/pkg")
        omitted = [f"{parent + '/' if parent else ''}{name}/generated" for parent in parents for name in names]
        for path in omitted:
            self.write(path, "regenerable")
        result = TRANSFER.create_transfer(self.root, self.output)
        with zipfile.ZipFile(self.output) as archive:
            for path in omitted:
                self.assertNotIn("LoadMonitor25/" + path, archive.namelist())
            manifest = json.loads(archive.read(result["manifest_entry"]))
        self.assertEqual(len(result["excluded_dirs"]), len(omitted))
        self.assertEqual(manifest["policy"]["cache_scope"], {
            "application_root": True, "code_trees": ["collect", "core", "python", "tools", "ui"],
            "other_directories": "preserved",
        })

    def test_custom_profile_exact_boundary(self):
        profile = self.root / "data" / "custom_browser"
        self.write("config/config.json", json.dumps({"copilotAuto": {"profileDir": str(profile)}}))
        self.write("data/custom_browser/private", "omit")
        self.write("data/custom_browser_backup/keep", "keep")
        result = TRANSFER.create_transfer(self.root, self.output)
        with zipfile.ZipFile(self.output) as archive:
            self.assertNotIn("LoadMonitor25/data/custom_browser/private", archive.namelist())
            self.assertIn("LoadMonitor25/data/custom_browser_backup/keep", archive.namelist())
        self.assertEqual(result["excluded_dirs"][0]["path"], "data/custom_browser")

    def test_deep_same_named_profile_is_user_data_and_preserved(self):
        kept = "data/추가PC/PC-A/files/copilot_profile/research.csv"
        omitted = "data/추가PC/PC-A/copilot_profile/Cookies"
        self.write(kept, "important research")
        self.write(omitted, "browser state")
        TRANSFER.create_transfer(self.root, self.output)
        with zipfile.ZipFile(self.output) as archive:
            self.assertEqual(archive.read("LoadMonitor25/" + kept), b"important research")
            self.assertNotIn("LoadMonitor25/" + omitted, archive.namelist())

    def test_ambiguous_or_broad_custom_profile_fails(self):
        for path in ("relative/browser", str(self.root), str(self.root / "data"), str(self.root / "config")):
            self.write("config/config.json", json.dumps({"copilotAuto": {"profileDir": path}}))
            with self.assertRaises(TRANSFER.TransferError):
                TRANSFER.plan_transfer(self.root, self.output)
        self.assert_no_archive()

    def test_output_inside_source_and_existing_output_rejected(self):
        with self.assertRaises(TRANSFER.TransferError):
            TRANSFER.create_transfer(self.root, self.root / "recursive.zip")
        self.output.write_bytes(b"existing")
        with self.assertRaises(TRANSFER.TransferError):
            TRANSFER.create_transfer(self.root, self.output)
        self.assertEqual(self.output.read_bytes(), b"existing")
        self.assertFalse((self.root / "recursive.zip").exists())

    def test_existing_output_created_during_archive_is_not_overwritten(self):
        def race(_update):
            if not self.output.exists():
                self.output.write_bytes(b"another writer")
        with self.assertRaises(TRANSFER.TransferError):
            TRANSFER.create_transfer(self.root, self.output, progress=race)
        self.assertEqual(self.output.read_bytes(), b"another writer")
        self.assertEqual(list(self.base.glob(".lm25-transfer-*.tmp")), [])

    def test_file_changed_after_copy_fails(self):
        changed = [False]
        def mutate(_update):
            if not changed[0]:
                self.write("config/config.json", '{"owner":"changed-longer"}')
                changed[0] = True
        with self.assertRaises(TRANSFER.TransferError):
            TRANSFER.create_transfer(self.root, self.output, progress=mutate)
        self.assert_no_archive()

    def test_added_file_during_copy_fails(self):
        with self.assertRaises(TRANSFER.TransferError):
            TRANSFER.create_transfer(self.root, self.output, progress=lambda _: self.write("data/new.csv"))
        self.assert_no_archive()

    def test_read_failure_removes_only_generated_temp(self):
        other_temp = self.base / ".lm25-transfer-unrelated.tmp"
        other_temp.write_text("keep", encoding="utf-8")
        with mock.patch.object(TRANSFER, "_copy_file", side_effect=PermissionError("locked")):
            with self.assertRaises(TRANSFER.TransferError):
                TRANSFER.create_transfer(self.root, self.output)
        self.assertFalse(self.output.exists())
        self.assertEqual(other_temp.read_text(encoding="utf-8"), "keep")
        self.assertEqual(list(self.base.glob(".lm25-transfer-*.tmp")), [other_temp])

    def test_change_while_reading_detected(self):
        real_write = zipfile._ZipWriteFile.write
        changed = [False]
        def changing_write(target, data):
            result = real_write(target, data)
            if target._zinfo.filename.endswith("data/files/files.csv") and not changed[0]:
                self.write("data/files/files.csv", "changed while open and longer")
                changed[0] = True
            return result
        with mock.patch.object(zipfile._ZipWriteFile, "write", changing_write):
            with self.assertRaises(TRANSFER.TransferError):
                TRANSFER.create_transfer(self.root, self.output)
        self.assert_no_archive()

    def test_reserved_manifest_collision_fails(self):
        self.write(TRANSFER.MANIFEST_NAME)
        with self.assertRaises(TRANSFER.TransferError):
            TRANSFER.plan_transfer(self.root, self.output)
        self.assert_no_archive()

    def test_second_pc_can_repackage_extracted_transfer(self):
        self.write("config/excluded_work.json", "{\"keep\":true}")
        self.write("report/upload_pending/period.json", "{\"pending\":true}")
        self.write("data/추가PC/PC-A/activity/activity_20260901.csv", "old pc")
        first = TRANSFER.create_transfer(self.root, self.output)
        destination = self.base / "next_pc"
        destination.mkdir()
        with zipfile.ZipFile(self.output) as archive:
            # Only this test's just-created, fixed-path synthetic ZIP is read.
            archive.extractall(destination)
        second_root = destination / self.root.name
        previous = (second_root / TRANSFER.MANIFEST_NAME).read_bytes()
        second_output = self.base / "second_transfer.zip"
        result = TRANSFER.create_transfer(second_root, second_output)
        with zipfile.ZipFile(self.output) as first_zip, zipfile.ZipFile(second_output) as second_zip:
            original = json.loads(first_zip.read(first["manifest_entry"]))
            for item in original["files"]:
                name = self.root.name + "/" + item["path"]
                self.assertEqual(first_zip.read(name), second_zip.read(name))
            generated = json.loads(second_zip.read(result["manifest_entry"]))
            self.assertEqual(generated["previous_manifest"][0]["sha256"], hashlib.sha256(previous).hexdigest())
            self.assertEqual(len(second_zip.namelist()), len(set(second_zip.namelist())))
        self.assertEqual((second_root / TRANSFER.MANIFEST_NAME).read_bytes(), previous)

    def test_cancel_during_large_file_copy_removes_temp_and_preserves_source(self):
        payload = b"synthetic data\n" * (TRANSFER.CHUNK_SIZE // 4)
        large = self.root / "data" / "large.bin"
        large.write_bytes(payload)
        requested = [False]
        real_write = zipfile._ZipWriteFile.write

        def cancel_after_chunk(target, data):
            result = real_write(target, data)
            if target._zinfo.filename.endswith("data/large.bin"):
                requested[0] = True
            return result

        with mock.patch.object(zipfile._ZipWriteFile, "write", cancel_after_chunk):
            with self.assertRaisesRegex(TRANSFER.TransferError, "이동 ZIP 취소"):
                TRANSFER.create_transfer(self.root, self.output, cancelled=lambda: requested[0])
        self.assertTrue(requested[0])
        self.assert_no_archive()
        self.assertEqual(large.read_bytes(), payload)

    def test_cancel_during_verify_removes_temp(self):
        self.write("data/large.txt", "x" * (TRANSFER.CHUNK_SIZE * 3))
        requested = [False]
        real_read = zipfile.ZipExtFile.read

        def cancel_after_read(entry, size=-1):
            result = real_read(entry, size)
            if entry.name.endswith("data/large.txt"):
                requested[0] = True
            return result

        with mock.patch.object(zipfile.ZipExtFile, "read", cancel_after_read):
            with self.assertRaisesRegex(TRANSFER.TransferError, "이동 ZIP 취소"):
                TRANSFER.create_transfer(self.root, self.output, cancelled=lambda: requested[0])
        self.assert_no_archive()

    def test_cancel_immediately_before_publish(self):
        requested = [False]
        scans = [0]
        real_scan = TRANSFER._scan

        def cancel_after_final_scan(*args, **kwargs):
            result = real_scan(*args, **kwargs)
            scans[0] += 1
            if scans[0] == 2:
                requested[0] = True
            return result

        with mock.patch.object(TRANSFER, "_scan", cancel_after_final_scan):
            with self.assertRaisesRegex(TRANSFER.TransferError, "이동 ZIP 취소"):
                TRANSFER.create_transfer(self.root, self.output, cancelled=lambda: requested[0])
        self.assert_no_archive()

    def test_cli_cancel_marker_is_not_deleted(self):
        marker = self.base / "cancel-requested"
        marker.write_text("cancel", encoding="utf-8")
        result = subprocess.run([sys.executable, "-B", str(SOURCE), "--root", str(self.root),
                                 "--output", str(self.output), "--cancel-file", str(marker), "--json"],
                                capture_output=True, text=True, encoding="utf-8", check=False)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("이동 ZIP 취소", json.loads(result.stdout)["error"])
        self.assertEqual(marker.read_text(encoding="utf-8"), "cancel")
        self.assert_no_archive()

    def test_symbolic_link_rejected(self):
        outside = self.base / "outside.txt"
        outside.write_text("outside", encoding="utf-8")
        try:
            (self.root / "linked.txt").symlink_to(outside)
        except OSError as error:
            self.skipTest(f"OS symlink creation unavailable: {error}")
        with self.assertRaises(TRANSFER.TransferError):
            TRANSFER.create_transfer(self.root, self.output)
        self.assert_no_archive()

    @unittest.skipUnless(os.name == "nt", "Windows junction check")
    def test_junction_rejected_even_when_named_excluded_profile(self):
        outside = self.base / "outside"
        outside.mkdir()
        junction = self.root / "data" / "copilot_profile"
        # All paths are newly created TEMP paths. No deletion or moving occurs.
        result = subprocess.run(["cmd", "/d", "/c", "mklink", "/J", str(junction), str(outside)],
                                capture_output=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        with self.assertRaises(TRANSFER.TransferError):
            TRANSFER.create_transfer(self.root, self.output)
        self.assert_no_archive()

    def test_cli_json_and_unique_default_output(self):
        first = TRANSFER.plan_transfer(self.root)
        second = TRANSFER.plan_transfer(self.root)
        self.assertNotEqual(first["output"], second["output"])
        result = subprocess.run([sys.executable, "-B", str(SOURCE), "--root", str(self.root),
                                 "--output", str(self.output), "--plan", "--json"],
                                capture_output=True, text=True, encoding="utf-8", check=False,
                                env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "planned")
        self.assert_no_archive()


if __name__ == "__main__":
    unittest.main()
