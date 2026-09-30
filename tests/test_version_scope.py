"""Only LM25 may enter the development tree or a Git commit."""
import contextlib
import importlib.util
import io
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location('scope_' + name, ROOT / 'scripts' / (name + '.py'))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


QUALITY = module('quality')
GATE = module('git_gate')


class VersionScopeTests(unittest.TestCase):
    def test_lm25_development_directories_are_allowed(self):
        with tempfile.TemporaryDirectory(prefix='lm25-version-scope-') as temporary:
            root = Path(temporary)
            for name in ('LoadMonitor25', 'scripts', 'tests', 'docs'):
                (root / name).mkdir()
            self.assertEqual(QUALITY.check_product_scope(root), [])

    def test_other_product_folders_fail_even_without_source_files(self):
        with tempfile.TemporaryDirectory(prefix='lm25-version-scope-') as temporary:
            root = Path(temporary)
            for name in ('LoadMonitor24', 'loadmonitor26'):
                (root / name).mkdir()
            self.assertEqual(len(QUALITY.check_product_scope(root)), 2)

    def test_force_added_old_version_is_rejected_before_running_checks(self):
        with tempfile.TemporaryDirectory(prefix='lm25-version-index-') as temporary:
            root = Path(temporary)
            subprocess.run(['git', 'init', '--quiet'], cwd=root, check=True, capture_output=True)
            (root / '.gitignore').write_text('/LoadMonitor[0-9]*/\n!/LoadMonitor25/\n', 'utf-8')
            old = root / 'LoadMonitor24'
            old.mkdir()
            (old / 'sample.py').write_text('synthetic = True\n', 'utf-8')
            subprocess.run(['git', 'add', '-f', 'LoadMonitor24/sample.py'], cwd=root, check=True, capture_output=True)
            output = io.StringIO()
            with contextlib.redirect_stderr(output):
                self.assertEqual(GATE.main(root), 1)
            self.assertIn('non-LM25', output.getvalue())
            self.assertIn('LoadMonitor24/sample.py', output.getvalue())
        self.assertFalse(GATE.forbidden('LoadMonitor25/core/extract.py'))
        self.assertTrue(GATE.forbidden('loadmonitor26/sample.py'))


if __name__ == '__main__':
    unittest.main()
