# -*- coding: utf-8 -*-
"""WP-00 진입점 시험 — %TEMP% 복제 트리에서 동봉 파이썬으로 lm27_cli.py 실행(계약 §7.1·§9.1),
WP-00 소유 소스의 정적 규칙(L-04 · L-05 · L-06 · L-07 · L-16 · L-28), bat 5개 인코딩·내용(L-02, 계약 §7.2).

bat 은 복제 트리에서만 돌린다. 복제에는 동봉 파이썬이 없으므로(원본 경로를 쓴다) bat 은 '파이썬 없음' 갈래로
끝난다 — 실제 수집·설치·서버 기동은 일어나지 않는다.
"""
import ast
import json
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

from tests.fixtures.tree import CloneTestCase

TREE = Path(__file__).resolve().parents[2]
JOB = "j20261005180000a1b2"

WP00_PY = ["lm27_cli.py", "lm27/__init__.py", "lm27/cli.py", "lm27/paths.py", "lm27/util/__init__.py",
           "lm27/util/fsx.py", "lm27/util/proc.py", "lm27/util/events.py", "lm27/bundle/ids.py"]
WP00_MARKERS = [f"lm27/{d}/__init__.py" for d in ("agent", "collect", "bundle", "normalize", "vocab", "pipeline", "ui",
                                                  "team")]
BATS = {
    "LoadMonitor27-UI.bat": ["pythonw.exe", "ui --check", 'start "" "%LM27_PYW%" -X utf8 -B "%LM27_CLI%" ui %*'],
    "LoadMonitor27-수집.bat": ["collect --auto"],
    "LoadMonitor27-에이전트설치.bat": ["agent install --only"],
    "LoadMonitor27-이동준비.bat": ["Prepare-Move.ps1", "lm27_move_", "start ", "-NoProfile -ExecutionPolicy Bypass -File"],
    "LoadMonitor27-팀서버.bat": ["team-server %*"],
}
CTRL = set(range(0, 9)) | {11, 12} | set(range(14, 32))


def _commands():
    p = TREE / "tests" / "fixtures" / "wp00" / "cli_commands.json"
    return json.loads(p.read_bytes().decode("utf-8"))["commands"]


class CloneCliTest(CloneTestCase):
    """복제 트리에서 동봉 파이썬으로 진입점을 실행한다."""

    def _txt(self, cp):
        return cp.stdout.decode("utf-8", "replace"), cp.stderr.decode("utf-8", "replace")

    def test_help_lists_all_commands_rc0(self):
        cp = self.clone.run_cli("--help", timeout=120)
        out, err = self._txt(cp)
        self.assertEqual(cp.returncode, 0, err)
        for name in _commands():
            self.assertIn(name, out)

    def test_unknown_command_rc1(self):
        cp = self.clone.run_cli("nosuch-command", timeout=120)
        _out, err = self._txt(cp)
        self.assertEqual(cp.returncode, 1)
        self.assertIn("[!]", err)

    def test_no_command_rc1(self):
        cp = self.clone.run_cli(timeout=120)
        self.assertEqual(cp.returncode, 1)

    def test_isolated_mode_inserts_root(self):
        """-I(격리)에서도 진입점이 ROOT 를 sys.path 에 넣는다(수집기·파이프 플래그와 같은 조건)."""
        cp = self.clone.run_py([self.clone.path("lm27_cli.py"), "--version"], flags=("-X", "utf8", "-I", "-B"), timeout=120)
        out, err = self._txt(cp)
        self.assertEqual(cp.returncode, 0, err)
        self.assertIn("LoadMonitor27", out)

    def test_events_jsonl_from_subprocess(self):
        cp = self.clone.run_cli("analyze", "--from", "2026-10-01", "--job", JOB, "--events", "jsonl", timeout=120)
        out, _err = self._txt(cp)
        self.assertEqual(cp.returncode, 1)
        evs = [json.loads(x) for x in out.strip().splitlines()]
        self.assertEqual(evs[-1]["ev"], "run_end")
        self.assertEqual(evs[-1]["rc"], 1)

    def test_no_pycache_written(self):
        self.clone.run_cli("--help", timeout=120)
        caches = list(self.clone.root.rglob("__pycache__"))
        self.assertEqual(caches, [])

    def test_bats_without_python_stop_rc3(self):
        """복제에는 python\\ 이 없다 → bat 은 '동봉 파이썬 없음' 안내 후 rc 3(아무것도 실행하지 않는다)."""
        self.assertFalse(self.clone.path("python", "python.exe").exists())
        for name in ("LoadMonitor27-UI.bat", "LoadMonitor27-수집.bat", "LoadMonitor27-에이전트설치.bat",
                     "LoadMonitor27-팀서버.bat"):
            with self.subTest(bat=name):
                bat = self.clone.path(name)
                self.assertTrue(bat.is_file())
                cp = subprocess.run(["cmd.exe", "/d", "/c", str(bat)], stdin=subprocess.DEVNULL, capture_output=True,
                                    env=self.clone.env(), cwd=str(self.clone.temp), timeout=60,
                                    creationflags=0x08000000)
                self.assertEqual(cp.returncode, 3)
                self.assertIn("python\\python.exe".encode("cp949"), cp.stdout)


class EntrySourceTest(unittest.TestCase):
    """진입 스크립트·WP-00 소스의 정적 규칙."""

    def _tree(self, rel):
        src = (TREE / rel).read_bytes().decode("utf-8")
        return src, ast.parse(src)

    def test_entry_first_statement_inserts_root(self):
        _src, tree = self._tree("lm27_cli.py")
        body = [n for n in tree.body if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))]
        first = next(n for n in body if not isinstance(n, (ast.Import, ast.ImportFrom)))
        self.assertIsInstance(first, ast.Expr)
        call = first.value
        self.assertEqual(ast.unparse(call.func), "sys.path.insert")
        self.assertEqual(ast.unparse(call.args[0]), "0")
        self.assertIn("__file__", ast.unparse(call.args[1]))
        imports = [n for n in body if isinstance(n, (ast.Import, ast.ImportFrom))]
        before = [n for n in imports if n.lineno < first.lineno]
        self.assertTrue(all(isinstance(n, ast.Import) and {a.name for a in n.names} <= {"os", "sys"} for n in before))

    def test_no_python_dash_m_lm27(self):
        rx = re.compile(r"python[w]?(\.exe)?\"?\s+(-\S+\s+)*-m\s+lm27\b", re.I)
        for rel in WP00_PY + list(BATS):
            with self.subTest(file=rel):
                raw = (TREE / rel).read_bytes()
                txt = raw.decode("cp949" if rel.endswith(".bat") else "utf-8")
                self.assertIsNone(rx.search(txt))

    def test_static_rules_in_wp00_python(self):
        for rel in WP00_PY + WP00_MARKERS:
            src, tree = self._tree(rel)
            with self.subTest(file=rel):
                self.assertNotIn("zoneinfo.ZoneInfo", src)            # L-04
                self.assertIsNone(re.search(r"^\s*(import|from)\s+zoneinfo", src, re.M))
                self.assertNotIn("os.kill(", src)                     # L-16
                for n in ast.walk(tree):
                    if isinstance(n, ast.ExceptHandler) and n.type is not None:
                        names = {ast.unparse(t) for t in (n.type.elts if isinstance(n.type, ast.Tuple) else [n.type])}
                        self.assertFalse(names & {"ImportError", "ModuleNotFoundError"}, rel)   # L-06
                    if isinstance(n, ast.Call) and ast.unparse(n.func) in ("open", "io.open", "os.open") \
                            and rel != "lm27/util/fsx.py":
                        mode = n.args[1] if len(n.args) > 1 else next((k.value for k in n.keywords if k.arg == "mode"),
                                                                      None)
                        if mode is not None:
                            self.assertFalse(isinstance(mode, ast.Constant) and set(str(mode.value)) & set("wax+"),
                                             rel)                                                  # L-07

    def test_markers_are_docstring_only(self):
        for rel in WP00_MARKERS:
            with self.subTest(file=rel):
                _src, tree = self._tree(rel)
                self.assertEqual(len(tree.body), 1)
                self.assertIsInstance(tree.body[0], ast.Expr)
                self.assertIsInstance(tree.body[0].value, ast.Constant)

    def test_no_avoided_ports(self):
        rx = re.compile(r"\b(876[5-7]|9333)\b")                      # L-28
        for rel in WP00_PY + list(BATS):
            with self.subTest(file=rel):
                raw = (TREE / rel).read_bytes()
                txt = raw.decode("cp949" if rel.endswith(".bat") else "utf-8")
                self.assertIsNone(rx.search(txt))


class BatTest(unittest.TestCase):
    """bat 5개: CP949(BOM 없음) + CRLF, 1줄 @echo off · 2줄 >nul chcp 949, pushd "%TEMP%" … popd(계약 §7.2·§9.2)."""

    def test_encoding_and_header(self):
        for name in BATS:
            with self.subTest(bat=name):
                raw = (TREE / name).read_bytes()
                self.assertNotEqual(raw[:3], b"\xef\xbb\xbf")
                self.assertEqual(raw.count(b"\n"), raw.count(b"\r\n"))
                self.assertTrue(raw.endswith(b"\r\n"))
                txt = raw.decode("cp949")
                self.assertFalse([c for c in txt if ord(c) in CTRL])
                lines = txt.split("\r\n")
                self.assertEqual(lines[0], "@echo off")
                self.assertEqual(lines[1], ">nul chcp 949")
                self.assertIn('pushd "%TEMP%"', lines)
                self.assertIn("popd", lines)
                runs = [i for i, ln in enumerate(lines)
                        if ln.startswith(('"%LM27_PY%"', "start ", "copy "))]
                self.assertTrue(runs)
                self.assertLess(lines.index('pushd "%TEMP%"'), min(runs))   # 실행 전에 작업 폴더를 TEMP 로

    def test_contents(self):
        for name, needles in BATS.items():
            with self.subTest(bat=name):
                txt = (TREE / name).read_bytes().decode("cp949")
                for s in needles:
                    self.assertIn(s, txt)
                for ln in txt.split("\r\n"):
                    if ln.startswith(('"%LM27_PY%"', 'start "" "%LM27_PYW%"')):   # 파이썬 실행 줄
                        self.assertIn("-X utf8 -B", ln)
                self.assertNotIn("cd /d \"%~dp0\"", txt)            # 작업 폴더를 ROOT 로 옮기지 않는다(TAB §1.9)

    def test_python_invocations_use_root_python(self):
        for name in ("LoadMonitor27-UI.bat", "LoadMonitor27-수집.bat", "LoadMonitor27-에이전트설치.bat",
                     "LoadMonitor27-팀서버.bat"):
            with self.subTest(bat=name):
                txt = (TREE / name).read_bytes().decode("cp949")
                self.assertIn(r'set "LM27_PY=%LM27_ROOT%\python\python.exe"', txt)
                self.assertIn(r'"%LM27_CLI%"', txt)

    def test_hook_check_accepts_bats(self):
        hc = TREE / "tools" / "hook_check.py"
        if not hc.is_file():
            self.skipTest("tools\\hook_check.py 없음")
        for name in BATS:                                   # 파일 한 개 검사 모드(관문 도구의 고정 사용법)
            with self.subTest(bat=name):
                cp = subprocess.run([sys.executable, "-X", "utf8", "-B", str(hc), os.path.join(str(TREE), name)],
                                    capture_output=True, stdin=subprocess.DEVNULL, timeout=120,
                                    creationflags=0x08000000)
                self.assertEqual(cp.returncode, 0, cp.stderr.decode("utf-8", "replace")[-300:])


if __name__ == "__main__":
    unittest.main()
