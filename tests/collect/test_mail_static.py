# -*- coding: utf-8 -*-
"""WP-15 정적 시험 — 소유 파일 3개(collect\\Get-OutlookCom.ps1 · Get-OutlookIndex.ps1 · Import-MailCal.py)와 자료(wp15)의
인코딩(L-02, 계약 §9.2) · 제어문자(L-01) · 수집기 쓰기 0(L-09) · 수집기 import(L-10) · 경로 조립 인자 금지(X-300, 계약 §7.3) ·
관문 훅 통과(hook_check — 계약 §11.4) · 자료의 이메일은 example 도메인만(L-26)."""
import ast
import re
import subprocess
import sys
import unittest
from pathlib import Path

TREE = Path(__file__).resolve().parents[2]
PS = [TREE / "collect" / "Get-OutlookCom.ps1", TREE / "collect" / "Get-OutlookIndex.ps1"]
PY = TREE / "collect" / "Import-MailCal.py"
FIX = TREE / "tests" / "fixtures" / "wp15"
CTRL = re.compile(rb"[\x00-\x08\x0b\x0c\x0e-\x1f]")
EMAIL = re.compile(r"(?<![\w.%+-])[A-Za-z0-9._%+-]+@((?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,})")


def _param_names(text: str) -> set:
    m = re.search(r"(?is)^param\s*\((.*?)\n\)", text, re.M)
    return set(re.findall(r"\$([A-Za-z]+)\b", m.group(1))) if m else set()


class StaticTest(unittest.TestCase):

    def test_ps1_bom_crlf_no_control(self):
        for p in PS:
            raw = p.read_bytes()
            self.assertTrue(raw.startswith(b"\xef\xbb\xbf"), p.name)
            self.assertEqual(raw.count(b"\n"), raw.count(b"\r\n"), p.name)
            self.assertIsNone(CTRL.search(raw), p.name)
            raw.decode("utf-8")

    def test_py_utf8_lf_no_bom(self):
        raw = PY.read_bytes()
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
        self.assertNotIn(b"\r", raw)
        self.assertIsNone(CTRL.search(raw))

    def test_x300_no_path_assembly_parameters(self):
        for p in PS:
            names = {n.lower() for n in _param_names(p.read_text(encoding="utf-8-sig"))}
            self.assertTrue(names, p.name)
            for bad in ("root", "pcid", "cursorfile", "outdir"):
                self.assertNotIn(bad, names, p.name)                       # 커서·설정은 stdin _in(계약 §7.3)
            self.assertIn("pc", names)

    def test_l09_no_write_cmdlets(self):
        rx = re.compile(r"(?i)\b(Out-File|Set-Content|Add-Content|Export-Csv|Export-Clixml|Tee-Object|Start-Transcript)\b|"
                        r"\[(?:System\.)?IO\.File\]::(?:Write|Append|Create|OpenWrite)|IO\.(?:StreamWriter|FileStream)")
        for p in PS:
            for i, ln in enumerate(p.read_text(encoding="utf-8-sig").splitlines(), 1):
                s = ln.split("#", 1)[0] if not ln.lstrip().startswith("#") else ""
                self.assertIsNone(rx.search(s), f"{p.name}:{i}")

    def test_l10_collector_imports(self):
        tree = ast.parse(PY.read_text(encoding="utf-8"))
        ok = ("lm27.store", "lm27.paths", "lm27.config", "lm27.util", "lm27.catalog", "lm27.bridge")
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom) and n.module and n.module.startswith("lm27"):
                self.assertTrue(n.module == "lm27.privacy.sanitize" or n.module.startswith(ok), n.module)
            if isinstance(n, ast.Import):
                for a in n.names:
                    self.assertFalse(a.name.startswith("lm27") and not a.name.startswith(ok), a.name)

    def test_l05_entry_inserts_root_first(self):
        tree = ast.parse(PY.read_text(encoding="utf-8"))
        first_lm27 = min(n.lineno for n in tree.body if isinstance(n, ast.ImportFrom) and (n.module or "").startswith("lm27"))
        ins = [n.lineno for n in tree.body if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
               and ast.unparse(n.value.func) == "sys.path.insert"]
        self.assertTrue(ins and ins[0] < first_lm27)

    def test_fixture_emails_are_examples_only(self):
        for p in FIX.rglob("*"):
            if not p.is_file() or p.suffix == ".pyc":
                continue
            text = p.read_bytes().decode("utf-8", "replace")
            for m in EMAIL.finditer(text):
                d = m.group(1).lower()
                self.assertTrue(d == "example.com" or d.endswith(".example") or d.endswith(".example.com"), f"{p.name}: {d}")

    def test_hook_check_passes(self):
        files = [str(p) for p in PS + [PY]] + [str(p) for p in (TREE / "tests" / "collect").glob("test_mail_*.py")]
        files.append(str(FIX / "mailkit.py"))
        cp = subprocess.run([sys.executable, "-X", "utf8", "-B", str(TREE / "tools" / "hook_check.py"), *files],
                            capture_output=True, timeout=300, cwd=str(TREE))
        self.assertEqual(cp.returncode, 0, cp.stderr.decode("utf-8", "replace"))


if __name__ == "__main__":
    unittest.main()
