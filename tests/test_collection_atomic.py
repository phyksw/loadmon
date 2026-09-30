"""Windows file sharing retries preserve an existing collection snapshot."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "LoadMonitor25" / "core"))
import collection_state


class AtomicCollectionTests(unittest.TestCase):
    @staticmethod
    def windows_error(code):
        error = PermissionError("synthetic Windows sharing failure")
        error.winerror = code
        return error

    def test_transient_windows_locks_retry_without_removing_old_snapshot(self):
        replace = collection_state.os.replace
        for code in (5, 32, 33):
            with self.subTest(code=code), tempfile.TemporaryDirectory(prefix="lm25-atomic-") as folder:
                target = Path(folder) / "status.json"
                target.write_text("previous", "utf-8")
                calls = []

                def replace_after_locks(source, destination):
                    self.assertEqual(target.read_text("utf-8"), "previous")
                    self.assertEqual(Path(source).read_text("utf-8"), "next")
                    calls.append(source)
                    if len(calls) < 3:
                        raise self.windows_error(code)
                    replace(source, destination)

                with patch.object(collection_state.os, "replace", side_effect=replace_after_locks), \
                        patch.object(collection_state.time, "sleep") as sleep:
                    collection_state._atomic_text(target, "next")
                self.assertEqual(target.read_text("utf-8"), "next")
                self.assertEqual(len(set(calls)), 1)
                self.assertEqual([call.args[0] for call in sleep.call_args_list], [0.05, 0.1])
                self.assertEqual(list(Path(folder).iterdir()), [target])

    def test_persistent_lock_is_bounded_preserves_old_snapshot_and_cleans_temporary(self):
        with tempfile.TemporaryDirectory(prefix="lm25-atomic-") as folder:
            target = Path(folder) / "status.json"
            target.write_text("previous", "utf-8")
            error = self.windows_error(5)
            with patch.object(collection_state.os, "replace", side_effect=error) as replace, \
                    patch.object(collection_state.time, "sleep") as sleep:
                with self.assertRaises(PermissionError) as raised:
                    collection_state._atomic_text(target, "next")
            self.assertIs(raised.exception, error)
            self.assertEqual(replace.call_count, 6)
            self.assertAlmostEqual(sum(call.args[0] for call in sleep.call_args_list), 1.55)
            self.assertEqual(target.read_text("utf-8"), "previous")
            self.assertEqual(list(Path(folder).iterdir()), [target])

    def test_other_filesystem_errors_fail_immediately_without_data_loss(self):
        for error in (PermissionError("POSIX denied"), self.windows_error(112)):
            with self.subTest(error=error), tempfile.TemporaryDirectory(prefix="lm25-atomic-") as folder:
                target = Path(folder) / "status.json"
                target.write_text("previous", "utf-8")
                with patch.object(collection_state.os, "replace", side_effect=error) as replace, \
                        patch.object(collection_state.time, "sleep") as sleep:
                    with self.assertRaises(OSError):
                        collection_state._atomic_text(target, "next")
                self.assertEqual(replace.call_count, 1)
                sleep.assert_not_called()
                self.assertEqual(target.read_text("utf-8"), "previous")
                self.assertEqual(list(Path(folder).iterdir()), [target])


if __name__ == "__main__":
    unittest.main()
