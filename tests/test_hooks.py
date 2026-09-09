"""Synthetic hook and Git-index checks; never invoke the LoadMonitor app."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


HOOK = load_script("codex_hook")
GIT_GATE = load_script("git_gate")


class HookTests(unittest.TestCase):
    def setUp(self):
        # Retain these small, exclusively synthetic folders; no recursive deletion.
        self.root = Path(tempfile.mkdtemp(prefix="lm25-hook-test-"))
        (self.root / "LoadMonitor25").mkdir()
        (self.root / "scripts").mkdir()
        self.source = self.root / "LoadMonitor25" / "sample.py"
        self.source.write_text("value = 1\n", encoding="utf-8")

    def test_fingerprint_tracks_edits_and_deletions(self):
        initial = HOOK.fingerprint(self.root)
        self.source.write_text("value = 2\n", encoding="utf-8")
        self.assertNotEqual(initial, HOOK.fingerprint(self.root))
        self.source.unlink()
        self.assertNotEqual(initial, HOOK.fingerprint(self.root))

    def test_private_data_never_changes_validation_input(self):
        initial = HOOK.fingerprint(self.root)
        for directory in ("DATA", "Report", "teamdata", "python", "copilot_profile"):
            folder = self.root / "LoadMonitor25" / directory
            folder.mkdir()
            (folder / "private.py").write_text("not even valid Python", encoding="utf-8")
        (self.root / "LoadMonitor25" / "config").mkdir()
        (self.root / "LoadMonitor25" / "config" / "config.json").write_text("personal", encoding="utf-8")
        self.assertEqual(initial, HOOK.fingerprint(self.root))

    def test_root_file_and_uppercase_extension_invalidate_cache(self):
        before = HOOK.fingerprint(self.root)
        (self.root / "broken.PY").write_text("broken (", encoding="utf-8")
        self.assertNotEqual(before, HOOK.fingerprint(self.root))
        self.assertTrue(HOOK.project_files(self.root))

    def test_package_document_change_invalidates_full_cache(self):
        before = HOOK.fingerprint(self.root)
        (self.root / "LoadMonitor25" / "README.md").write_text("changed", encoding="utf-8")
        self.assertNotEqual(before, HOOK.fingerprint(self.root))

    def test_stop_requests_one_continuation_then_reports_failure(self):
        with mock.patch.object(HOOK, "check", return_value=(False, "bad syntax", False)):
            first = HOOK.handle({"hook_event_name": "Stop"}, self.root)
            second = HOOK.handle({"hook_event_name": "Stop", "stop_hook_active": True}, self.root)
        self.assertEqual(first["decision"], "block")
        self.assertIn("bad syntax", first["reason"])
        self.assertNotIn("decision", second)
        self.assertIn("systemMessage", second)

    def test_edit_feedback_does_not_discard_original_tool_output(self):
        with mock.patch.object(HOOK, "check", return_value=(False, "lint failed", False)):
            result = HOOK.handle({"hook_event_name": "PostToolUse"}, self.root)
        self.assertNotIn("decision", result)
        self.assertIn("lint failed", result["hookSpecificOutput"]["additionalContext"])

    def test_pass_is_cached_but_failures_are_not(self):
        runner = self.root / "scripts" / "quality.py"
        runner.write_text("print('OK')\n", encoding="utf-8")
        key = HOOK.fingerprint(self.root)
        self.assertEqual(HOOK.check(self.root, "quick", key), (True, "OK\n", False))
        self.assertEqual(HOOK.check(self.root, "quick", key), (True, "", True))
        runner.write_text("raise SystemExit(1)\n", encoding="utf-8")
        key = HOOK.fingerprint(self.root)
        self.assertFalse(HOOK.check(self.root, "quick", key)[0])
        self.assertFalse(HOOK.check(self.root, "quick", key)[2])

    def test_concurrent_source_edit_cannot_cache_success(self):
        runner = self.root / "scripts" / "quality.py"
        runner.write_text("print('OK')\n", encoding="utf-8")
        key = HOOK.fingerprint(self.root)
        with mock.patch.object(HOOK, "fingerprint", return_value="changed"):
            passed, message, _cached = HOOK.check(self.root, "quick", key)
        self.assertFalse(passed)
        self.assertIn("changed during validation", message)

    def test_plan_mode_does_not_run_validation(self):
        with mock.patch.object(HOOK, "check") as checker:
            self.assertEqual(HOOK.handle({"hook_event_name": "Stop", "permission_mode": "plan"}, self.root), {})
        checker.assert_not_called()

    def test_invalid_stdin_is_reported(self):
        result = subprocess.run([sys.executable, "-B", str(ROOT / "scripts" / "codex_hook.py")], input="not json", capture_output=True, text=True, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("systemMessage", json.loads(result.stdout))


@unittest.skipUnless(shutil.which("git"), "Git is required for index integration tests")
class GitIndexTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="lm25-index-test-"))
        self.git("init", "--quiet")
        self.git("config", "core.autocrlf", "false")
        scripts = self.root / "scripts"
        scripts.mkdir()
        # The test checker validates syntax from its snapshot cwd, not the working tree.
        (scripts / "quality.py").write_text("from pathlib import Path\ncompile(Path('sample.py').read_text(), 'sample.py', 'exec')\n", encoding="utf-8")
        self.sample = self.root / "sample.py"

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.root, capture_output=True, check=True)

    def run_gate(self):
        original_run = subprocess.run

        def capture(*args, **kwargs):
            kwargs.setdefault("capture_output", True)
            return original_run(*args, **kwargs)

        with mock.patch.object(GIT_GATE.subprocess, "run", side_effect=capture):
            with contextlib.redirect_stdout(io.StringIO()):
                return GIT_GATE.main(self.root)

    def test_invalid_index_is_rejected_even_if_working_file_is_fixed(self):
        self.sample.write_text("broken (\n", encoding="utf-8")
        self.git("add", "scripts", "sample.py")
        self.sample.write_text("fixed = 1\n", encoding="utf-8")
        self.assertNotEqual(self.run_gate(), 0)

    def test_valid_index_passes_even_if_working_file_has_later_error(self):
        self.sample.write_text("valid = 1\n", encoding="utf-8")
        self.git("add", "scripts", "sample.py")
        self.sample.write_text("broken (\n", encoding="utf-8")
        self.assertEqual(self.run_gate(), 0)

    def test_personal_files_are_rejected_case_insensitively(self):
        folder = self.root / "LoadMonitor25" / "DATA"
        folder.mkdir(parents=True)
        (folder / "private.csv").write_text("synthetic", encoding="utf-8")
        self.git("add", "LoadMonitor25")
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(GIT_GATE.main(self.root), 1)


if __name__ == "__main__":
    unittest.main()
