# -*- coding: utf-8 -*-
"""WP-25 수집 어댑터 정적 대조 — L-05(첫 실행문에서 자기 루트를 sys.path 에) · L-10(수집기 파이썬 import 허용 목록:
lm27.privacy 는 sanitize 만) · L-07(쓰기 open 0 — 쓰기는 fsx·SegmentWriter·브리지 몫) · L-11(로컬 원장 경로 메서드 직접
사용 0) · L-16/G-B12(Edge 프로필·포트 인자·키 0) · 인코딩(UTF-8 BOM 없음 · LF · 제어문자 0) · 실명·메일 주소 0."""
from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ("Get-MailViaCopilot.py", "Get-TeamsViaCopilot.py", "Get-CalViaCopilot.py", "probe_copilot.py")
ALLOWED = ("lm27.privacy.sanitize", "lm27.store", "lm27.paths", "lm27.config", "lm27.util", "lm27.catalog",
           "lm27.bridge")
STORE_PATH_M = {"store_file", "store_dir", "store_root", "privacy_audit_file", "raw_cursor", "raw_cursor_lock"}
CTRL_RX = re.compile(rb"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _ok(mod: str) -> bool:
    return any(mod == a or mod.startswith(a + ".") for a in ALLOWED)


class Static(unittest.TestCase):
    def setUp(self):
        self.src = {s: (ROOT / "collect" / s).read_bytes() for s in SCRIPTS}
        self.tree = {s: ast.parse(b.decode("utf-8")) for s, b in self.src.items()}

    def test_L05_root_first(self):
        for s, tree in self.tree.items():
            body = [n for n in tree.body if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))]
            insert = next(i for i, n in enumerate(body) if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
                          and ast.unparse(n.value.func) == "sys.path.insert")
            self.assertEqual(ast.unparse(body[insert]), "sys.path.insert(0, ROOT)", s)
            self.assertTrue(all(isinstance(n, (ast.Import, ast.Assign)) for n in body[:insert]), s)
            early = [a.name for n in body[:insert] if isinstance(n, ast.Import) for a in n.names]
            self.assertEqual(sorted(early), ["os", "sys"], s)

    def test_L10_imports(self):
        for s, tree in self.tree.items():
            for n in ast.walk(tree):
                if isinstance(n, ast.Import):
                    for a in n.names:
                        if a.name.split(".")[0] == "lm27":
                            self.assertTrue(_ok(a.name), (s, a.name))
                elif isinstance(n, ast.ImportFrom) and n.module and n.module.split(".")[0] == "lm27":
                    if n.module == "lm27.privacy":
                        self.assertEqual([a.name for a in n.names], ["sanitize"], s)
                    elif n.module == "lm27":
                        self.assertTrue(all(_ok("lm27." + a.name) for a in n.names), (s, n.module))
                    else:
                        self.assertTrue(_ok(n.module), (s, n.module))

    def test_L07_L11_no_direct_writes(self):
        for s, tree in self.tree.items():
            for n in ast.walk(tree):
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "open":
                    mode = n.args[1].value if len(n.args) > 1 and isinstance(n.args[1], ast.Constant) else "r"
                    self.assertFalse(any(c in str(mode) for c in "wax+"), s)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
                    self.assertNotIn(n.func.attr, STORE_PATH_M, s)
                    self.assertNotIn(n.func.attr, ("write_text", "write_bytes", "mkdir"), s)

    def test_L16_no_edge_args(self):
        for s, b in self.src.items():
            t = b.decode("utf-8")
            for bad in ("--user-data-dir", "--remote-debugging-port", "remote-allow-origins", "bridge.edge.",
                        "office.com", "os.kill("):
                self.assertNotIn(bad, t, s)

    def test_encoding(self):
        for s, b in self.src.items():
            self.assertFalse(b.startswith(b"\xef\xbb\xbf"), s)
            self.assertNotIn(b"\r\n", b, s)
            self.assertIsNone(CTRL_RX.search(b), s)
            self.assertIsNone(re.search(rb"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+\.[A-Za-z]{2,}", b), s)


if __name__ == "__main__":
    unittest.main()
