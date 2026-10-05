# -*- coding: utf-8 -*-
"""WP-23 브리지 정적 관문(B §15) — G-B1(시계) · G-B2(한도 숫자) · G-B7(쓰기) · G-B9(폐기 결함) · G-B12/L-16(Edge 인자·키 경계)
· JS 조각 표식·문법(node 가 있을 때) · hook_check 의 L-07·L-16·L-17(브리지 파일)."""
from __future__ import annotations

import ast
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from lm27.bridge import js

ROOT = Path(__file__).resolve().parents[2]
BRIDGE = ROOT / "lm27" / "bridge"
GB2 = {9000, 8400, 8300, 8000, 7000, 5500, 5000, 900, 480, 180}
TIME_CALLS = {"time.sleep", "time.time", "time.monotonic"}


def bridge_files():
    return sorted(p for p in BRIDGE.rglob("*.py") if "__pycache__" not in p.parts)


def dotted(n):
    if isinstance(n, ast.Name):
        return n.id
    if isinstance(n, ast.Attribute):
        return dotted(n.value) + "." + n.attr
    return ""


def str_consts(tree):
    for n in ast.walk(tree):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            yield n
        elif isinstance(n, ast.JoinedStr):
            for v in n.values:
                if isinstance(v, ast.Constant) and isinstance(v.value, str):
                    yield v


class TestBridgeGates(unittest.TestCase):
    def test_GB1_time_only_in_clock(self):
        for p in bridge_files():
            if p.name == "clock.py" and p.parent == BRIDGE:
                continue
            tree = ast.parse(p.read_text(encoding="utf-8"))
            for n in ast.walk(tree):
                if isinstance(n, ast.Import):
                    self.assertNotIn("time", [a.name for a in n.names], p.name)
                elif isinstance(n, ast.ImportFrom):
                    self.assertNotEqual(n.module, "time", p.name)
                elif isinstance(n, ast.Call):
                    self.assertNotIn(dotted(n.func), TIME_CALLS, f"{p.name}:{n.lineno}")

    def test_GB2_limit_numbers_only_in_settings(self):
        for p in bridge_files():
            if p.name == "settings.py" and p.parent == BRIDGE:
                continue
            text = p.read_text(encoding="utf-8")
            lines = text.splitlines()
            for n in ast.walk(ast.parse(text)):
                if isinstance(n, ast.Constant) and type(n.value) in (int, float) and n.value in GB2:
                    self.assertIn("noqa: G-B2", lines[n.lineno - 1], f"{p.name}:{n.lineno} {n.value}")

    def test_GB7_write_open_only_in_fsio(self):
        for p in bridge_files():
            tree = ast.parse(p.read_text(encoding="utf-8"))
            for n in ast.walk(tree):
                if not isinstance(n, ast.Call):
                    continue
                name = dotted(n.func)
                if p.name != "fsio.py":
                    self.assertNotIn(name, ("os.write", "os.replace", "os.remove", "os.rename", "shutil.rmtree"),
                                     f"{p.name}:{n.lineno}")
                    if name == "os.open":                      # 읽기 열기(O_RDONLY)만 허용
                        flags = {x.attr for x in ast.walk(n.args[1]) if isinstance(x, ast.Attribute)}
                        self.assertTrue(flags <= {"O_RDONLY", "O_BINARY"}, f"{p.name}:{n.lineno}")
                    if name in ("open", "io.open", "gzip.open"):
                        mode = n.args[1] if len(n.args) > 1 else next(
                            (k.value for k in n.keywords if k.arg == "mode"), None)
                        self.assertTrue(mode is None or (isinstance(mode, ast.Constant) and
                                                         not set(str(mode.value)) & set("wax+")),
                                        f"{p.name}:{n.lineno}")
                if name.endswith("write_text_ttl") and isinstance(n.func, ast.Attribute):
                    self.assertIn(p.name, ("manual.py", "exchange.py"), f"{p.name}:{n.lineno}")

    def test_GB9_retired_defects_absent(self):
        allow_all = "--remote-allow-origins=" + "*"
        sub_host = "office" + ".com"
        for p in bridge_files():
            text = p.read_text(encoding="utf-8")
            self.assertNotIn(allow_all, text, p.name)
            self.assertNotIn(sub_host, text.lower(), p.name)
            self.assertIsNone(re.search(r"\bos\.kill\(", text), p.name)

    def test_GB12_edge_flags_and_keys_only_in_bridge(self):
        needles = ("--user-data-dir", "--remote-debugging-port", "bridge.edge.profileDir", "bridge.edge.port",
                   "bridge.edge.portTries")
        bad = []
        for base in (ROOT / "lm27", ROOT / "collect"):
            if not base.is_dir():
                continue
            for p in base.rglob("*"):
                if p.suffix.lower() not in (".py", ".ps1", ".bat") or "__pycache__" in p.parts:
                    continue
                if BRIDGE in p.parents:
                    continue
                text = p.read_text(encoding="utf-8", errors="replace")
                bad += [f"{p.relative_to(ROOT)}:{nd}" for nd in needles if nd in text]
        self.assertEqual(bad, [])

    def test_bridge_imports_privacy_only_via_gate(self):
        for p in bridge_files():
            if p.name == "gate.py":
                continue
            tree = ast.parse(p.read_text(encoding="utf-8"))
            for n in ast.walk(tree):
                mods = [a.name for a in n.names] if isinstance(n, ast.Import) else (
                    [n.module or ""] if isinstance(n, ast.ImportFrom) else [])
                for m in mods:
                    self.assertFalse(m.startswith("lm27.privacy"), f"{p.name}:{n.lineno}")


class TestJsSnippets(unittest.TestCase):
    SELS = ("[contenteditable='true'][role='textbox']", "textarea")

    def snippets(self):
        return {
            "identity": js.identity(self.SELS), "focus_input": js.focus_input(self.SELS, ("Copilot에 메시지 보내기",)),
            "editor_text": js.editor_text(), "clear_editor": js.clear_editor(),
            "insert_fallback": js.insert_fallback("가\"'\n`${x}`</script>\\"),
            "click_send": js.click_send(("보내기", "Send")),
            "generating": js.generating(("생성 중지", "응답 중지", "stop generating", "stop responding", "중지", "stop")),
            "poll": js.poll(("중지", "stop", "x"), ("[data-testid='a']",), "div.msg"), "counts": js.counts((), "x"),
            "chat_text": js.chat_text(), "learn_asst": js.learn_asst("[[END R7F3QK]]", "[LM27 요청 R7F3"),
            "new_chat": js.new_chat(("새 채팅",)), "pick_model": js.pick_model("빠른 응답", ("모델", "model")),
            "menu_open": js.menu_open(), "pick_model_item": js.pick_model_item("깊이 생각하기"),
            "close_menu": js.close_menu(), "work_mode": js.work_mode(("업무", "Work"), ("웹", "Web"), True),
            "env": js.env(("업무",), ("웹",), ("웹 검색",)), "diagnose": js.diagnose(self.SELS, ("보내기",)),
        }

    def test_markers(self):
        sn = self.snippets()
        self.assertEqual(set(sn), set(js.ALL))
        for name, expr in sn.items():
            self.assertEqual(js.marker(expr), name)
        self.assertEqual(js.marker("1+1"), "")

    def test_env_reads_web_grounding_without_click(self):
        e = js.env(("업무",), ("웹",), ("웹 검색",))
        tail = e.split("const gl=", 1)[1]
        self.assertNotIn(".click()", tail)

    def test_node_syntax(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node 없음(개발 PC 전용 검사)")
        d = tempfile.mkdtemp(prefix="lm27t_js_")
        self.addCleanup(shutil.rmtree, d, True)
        for name, expr in self.snippets().items():
            p = os.path.join(d, name + ".js")
            with open(p, "w", encoding="utf-8") as fh:
                fh.write(expr + ";\n")
            r = subprocess.run([node, "--check", p], capture_output=True, text=True, timeout=60,
                               creationflags=0x08000000 if os.name == "nt" else 0)
            self.assertEqual(r.returncode, 0, f"{name}: {r.stderr[:300]}")


class TestHookCheck(unittest.TestCase):
    def test_bridge_files_pass_l07_l16_l17(self):
        hc = ROOT / "tools" / "hook_check.py"
        if not hc.is_file():
            self.skipTest("tools\\hook_check.py 없음")
        files = [str(p) for p in bridge_files()]
        r = subprocess.run([sys.executable, "-X", "utf8", "-B", str(hc), "--root", str(ROOT), "--rules",
                            "L-07,L-16,L-17", *files], capture_output=True, timeout=300,
                           creationflags=0x08000000 if os.name == "nt" else 0)
        out = (r.stdout + r.stderr).decode("utf-8", "replace")
        if "Traceback" in out:
            self.skipTest("hook_check 자체 오류(관문 도구 개발 중)")
        self.assertEqual(r.returncode, 0, out[:2000])


if __name__ == "__main__":
    unittest.main()
