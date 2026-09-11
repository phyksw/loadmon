"""Immutable team snapshots, synthetic files only; no server or upload."""
import ast
import importlib.util
import json
import os
from pathlib import Path
import shutil
import tempfile
import threading
import unittest
from unittest import mock


APP = Path(__file__).resolve().parents[1] / "LoadMonitor25"
SPEC = importlib.util.spec_from_file_location("lm25_bundles_test", APP / "core" / "bundles.py")
B = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(B)
TAG = "20260901-20260930"
MEMBER = {"owner": "Synthetic", "tag": TAG, "total_mm": 1}
FILES = {f"mm_rows_{TAG}.csv": "Level3,MM\nSynthetic,1\n", f"mm_meta_{TAG}.json": '{"total_mm":1}'}


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="lm25-bundle-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "Synthetic"

    def test_legacy_remains_readable_and_unmodified(self):
        self.root.mkdir()
        old = self.root / "member.json"
        old.write_text(json.dumps(MEMBER), encoding="utf-8")
        self.assertTrue(os.path.samefile(B.resolve_member_dir(self.root), self.root))
        previous = old.read_bytes()
        new = B.write_bundle(self.root, MEMBER, FILES)
        self.assertEqual(B.resolve_member_dir(self.root), new)
        self.assertEqual(old.read_bytes(), previous)

    def test_reader_pins_complete_old_generation_during_write(self):
        first = B.write_bundle(self.root, MEMBER, FILES)
        observed = []
        original = B._write

        def observe(path, body):
            original(path, body)
            observed.append(B.resolve_member_dir(self.root))

        with mock.patch.object(B, "_write", side_effect=observe):
            second = B.write_bundle(self.root, dict(MEMBER, total_mm=2), {k: v + " " for k, v in FILES.items()})
        self.assertEqual(set(observed), {first})
        self.assertEqual(B.resolve_member_dir(self.root), second)
        self.assertEqual(json.loads((Path(first) / "member.json").read_text())["total_mm"], 1)

    def test_second_file_failure_and_pointer_failure_preserve_old(self):
        first = B.write_bundle(self.root, MEMBER, FILES)
        original = B._write

        def fail_second(path, body):
            if Path(path).name.startswith("mm_meta"):
                raise OSError("synthetic file locked")
            original(path, body)

        for target, effect in (("_write", fail_second), ("os.replace", OSError("synthetic pointer locked"))):
            with self.subTest(target=target):
                patcher = mock.patch.object(B, "_write", side_effect=effect) if target == "_write" else mock.patch.object(B.os, "replace", side_effect=effect)
                with patcher, self.assertRaises(OSError):
                    B.write_bundle(self.root, MEMBER, FILES)
                self.assertEqual(B.resolve_member_dir(self.root), first)

    def test_corrupt_pointer_never_falls_back_to_legacy(self):
        B.write_bundle(self.root, MEMBER, FILES)
        (self.root / "member.json").write_text(json.dumps(MEMBER))
        for value in ({"schema": 1, "run_id": "../other"}, [], {"schema": 99, "run_id": "a" * 32}):
            (self.root / "current.json").write_text(json.dumps(value))
            with self.assertRaises(ValueError):
                B.resolve_member_dir(self.root)

    def test_changed_or_added_artifact_is_rejected(self):
        run = Path(B.write_bundle(self.root, MEMBER, FILES))
        target = run / next(iter(FILES))
        target.write_text("tampered")
        with self.assertRaises(ValueError):
            B.resolve_member_dir(self.root)
        target.write_text(FILES[target.name], encoding="utf-8", newline="")
        (run / "extra.json").write_text("{}")
        with self.assertRaises(ValueError):
            B.resolve_member_dir(self.root)

    def test_cross_period_and_path_escape_cannot_publish(self):
        for files in ({"mm_rows_20260801-20260831.csv": "old"}, {"../member.json": "{}"}, {}):
            with self.subTest(files=files), self.assertRaises(ValueError):
                B.write_bundle(self.root, MEMBER, files)
        self.assertFalse((self.root / "current.json").exists())

    def test_colliding_name_cannot_overwrite_another_identity(self):
        first = B.write_bundle(self.root, dict(MEMBER, member_id="first", owner_source="a.b"), FILES)
        for identity in ("second", None):
            with self.assertRaises(ValueError):
                B.write_bundle(self.root, dict(MEMBER, member_id=identity), FILES)
        self.assertEqual(B.resolve_member_dir(self.root), first)

    def test_os_publication_lock_blocks_competing_writer_and_releases(self):
        outcomes = []
        with B._publication_lock(self.root):
            def competing():
                try:
                    B.write_bundle(self.root, MEMBER, FILES)
                    outcomes.append("unexpected success")
                except OSError:
                    outcomes.append("busy")
            worker = threading.Thread(target=competing)
            worker.start()
            worker.join(3)
            self.assertFalse(worker.is_alive())
            self.assertEqual(outcomes, ["busy"])
        B.write_bundle(self.root, MEMBER, FILES)

    @unittest.skipUnless(os.name == "nt", "Windows extended path regression")
    def test_long_member_paths_and_failure_preserve_published_generation(self):
        base = os.path.abspath(self.temp.name)
        self.addCleanup(lambda: shutil.rmtree("\\\\?\\" + base, ignore_errors=True))
        for size in (215, 280):
            root = Path(base)
            while len(str(root)) + 61 < size:
                root = root / ("d" * 60)
            root = root / ("n" * (size - len(str(root)) - 1))
            self.assertEqual(len(str(root)), size)
            first = B.write_bundle(root, MEMBER, FILES)
            self.assertEqual(B.resolve_member_dir(root), first)
            with mock.patch.object(B.os, "replace", side_effect=OSError("synthetic pointer lock")):
                with self.assertRaises(OSError):
                    B.write_bundle(root, MEMBER, FILES)
            self.assertEqual(B.resolve_member_dir(root), first)


class PayloadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="lm25-payload-")
        self.addCleanup(self.temp.cleanup)
        spec = importlib.util.spec_from_file_location("teamup_synthetic", APP / "teamup.py")
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.module.REPORT = self.temp.name
        self.root = Path(self.temp.name)
        self.meta = self.root / f"mm_meta_{TAG}.json"
        for name, value in FILES.items():
            (self.root / name).write_text(value, encoding="utf-8")

    def payload(self):
        return self.module.make_payload({"owner": "Synthetic"}, "2026-09-01", "2026-09-30")

    def test_member_uses_exact_captured_meta_bytes(self):
        result = self.payload()
        self.assertEqual(result["member"]["total_mm"], json.loads(result["files"][self.meta.name])["total_mm"])
        self.assertEqual(set(result["member"]["source_artifacts"]), set(FILES))

    def test_change_after_meta_read_aborts_even_with_restored_mtime(self):
        real_open = open
        reads = []
        original_stat = self.meta.stat()
        def changing_open(path, *args, **kwargs):
            if os.path.normcase(os.path.abspath(path)) == os.path.normcase(str(self.meta)) and args == ("rb",):
                reads.append(path)
                if len(reads) == 2:
                    self.meta.write_text('{"total_mm":2}', encoding="utf-8")
                    os.utime(self.meta, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
            return real_open(path, *args, **kwargs)
        with mock.patch("builtins.open", side_effect=changing_open), self.assertRaises(ValueError):
            self.payload()

    def test_file_added_during_capture_aborts(self):
        original = self.module._source_snapshot
        count = []
        def snapshot(tag):
            count.append(tag)
            if len(count) == 2:
                (self.root / f"workflow_{TAG}.json").write_text("{}")
            return original(tag)
        with mock.patch.object(self.module, "_source_snapshot", side_effect=snapshot), self.assertRaises(ValueError):
            self.payload()

    def test_stale_refined_and_ai_results_do_not_become_fresh_when_copied(self):
        raw = self.root / f"mm_rows_{TAG}.csv"
        stamp = raw.stat().st_mtime
        for prefix, suffix in (("mm_rows", "_refined.csv"), ("agentic", ".json"), ("workflow", ".json")):
            path = self.root / f"{prefix}_{TAG}{suffix}"
            path.write_text("{}")
            os.utime(path, (stamp - 20, stamp - 20))
        self.assertEqual(set(self.payload()["files"]), set(FILES))

    def test_server_save_uses_same_atomic_writer(self):
        tree = ast.parse((APP / "teamserver.py").read_text(encoding="utf-8-sig"))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "H")
        fn = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "_save")
        fn.decorator_list = []
        env = {"TEAMDATA": self.temp.name, "os": os, "write_bundle": B.write_bundle}
        exec(compile(ast.Module(body=[fn], type_ignores=[]), "server-save", "exec"), env)
        bad, saved = env["_save"]("Synthetic", MEMBER, FILES)
        self.assertEqual(bad, [])
        self.assertEqual(len(saved), len(FILES) + 1)
        self.assertIn(".runs", B.resolve_member_dir(self.root / "Synthetic"))


if __name__ == "__main__":
    unittest.main()
