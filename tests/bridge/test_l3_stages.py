# -*- coding: utf-8 -*-
"""WP-24 단계 기반·관문 — G-B4 단계 완결성(시험 전용 단계로) · G-B8 시간 정보 미전송 · L-30 import 무부작용 ·
'lm27.privacy 를 import 하는 브리지 파일은 gate.py 하나' · G-B1(시계 주입)·G-B2(한도 숫자)·G-B7(쓰기는 fsio) AST 대조 ·
G-B11 엄격 규칙 ID 글자판 = P §5 보호 구간."""
from __future__ import annotations

import ast
import re
import subprocess
import sys
import unittest
from pathlib import Path

from lm27.bridge import gate as G
from lm27.bridge.stages import base as B
from lm27.privacy import rules as PR

from tests.fixtures.wp24 import stages as TS
from tests.fixtures.wp24.rig import REG

ROOT = Path(__file__).resolve().parents[2]
BRIDGE = ROOT / "lm27" / "bridge"
WP24_FILES = ("__init__.py", "jsonx.py", "exchange.py", "gate.py", "runner.py", "budget.py", "journal.py",
              "calibrate.py", "capability.py", "manual.py", "cli.py", "stages/base.py")
GB2 = {9000, 8400, 8300, 8000, 7000, 5500, 5000, 900, 480, 180}
L30_PROBE = r'''
import os, sys
sys.path.insert(0, ROOT)
BAD = {"subprocess.Popen", "os.system", "socket.connect", "socket.bind", "os.mkdir", "os.rename", "os.remove",
       "shutil.rmtree", "winreg.SetValue"}
W = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC
def hook(ev, args):
    if ev == "open":
        mode, flags = args[1], args[2]
        if (isinstance(mode, str) and any(c in mode for c in "wax+")) or (mode is None and isinstance(flags, int)
                                                                          and flags & W):
            raise RuntimeError("부작용: 파일 쓰기")
    elif ev in BAD:
        raise RuntimeError("부작용: " + ev)
sys.addaudithook(hook)
import importlib
for m in MODS:
    importlib.import_module(m)
print("ok")
'''


def _ctx():
    return B.StageCtx(registry=REG, codes_map={k: frozenset(v) for k, v in REG["codes"].items()})


class Completeness(unittest.TestCase):
    def test_G_B4_test_stages_complete(self):
        for cls in TS.ALL + (TS.LookupTeams,):
            self.assertEqual(B.check_stage(cls(), _ctx(), codename_words=("가상코드명",)), [], cls.__name__)

    def test_check_stage_finds_problems(self):
        class Bad(TS.ActStage):
            id = "Bad-Id"
            prompt_ver = ""
            send_fields = ("text", "start_date")

            def header(self, ctx, compact=False):
                ip = ".".join(("10", "0", "0", "1"))                  # 사설 IP 는 런타임 조립(L-21)
                return f"문의: tester@example.com · {ip} · 회의 3시간 · 가상코드명"

            def format_line(self):
                return '{"items": []}'

            def fallback(self, it, ctx, why):
                return None
        probs = B.check_stage(Bad(), _ctx(), codename_words=("가상코드명",))
        for frag in ("id 형식", "prompt_ver", "시간형 키", "<요청번호>", "메일 주소", "IPv4", "시간 수치", "코드네임", "폴백"):
            self.assertTrue(any(frag in p for p in probs), (frag, probs))

    def test_G_B8_privacy_spec_rejects_time_fields(self):
        class TimeStage(TS.ActStage):
            send_fields = ("text", "hours")
        with self.assertRaises(G.StageGateError) as cm:
            G.privacy_spec(TimeStage())
        self.assertEqual(cm.exception.reason, "gate_spec")
        self.assertEqual(G.privacy_spec(TS.ActStage()).allowed_fields, frozenset(TS.ActStage.send_fields))

    def test_G_B11_id_charset_matches_protected_tokens(self):
        m = re.search(r"고객사:(\[[^\]]+\]\{\d+,\d+\})", PR.TOKEN_RX.pattern)
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), G.ID_CHARS)
        for name in ("RX_MAIL_ORG", "RX_ORG_ID", "RX_CUSTOMER"):
            self.assertIn(G.ID_CHARS, getattr(G, name).pattern)


class Imports(unittest.TestCase):
    def test_L30_import_has_no_side_effects(self):
        mods = ["lm27.bridge", "lm27.bridge.stages.base"]
        code = L30_PROBE.replace("ROOT", repr(str(ROOT)), 1).replace("MODS", repr(mods))
        r = subprocess.run([sys.executable, "-X", "utf8", "-B", "-c", code], capture_output=True, text=True,
                           encoding="utf-8", timeout=120)
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "ok"), r.stderr[-400:])

    def test_only_gate_imports_privacy(self):
        hits = []
        for p in sorted(BRIDGE.rglob("*.py")):
            tree = ast.parse(p.read_text(encoding="utf-8"))
            for n in ast.walk(tree):
                mods = []
                if isinstance(n, ast.Import):
                    mods = [a.name for a in n.names]
                elif isinstance(n, ast.ImportFrom) and n.module:
                    mods = [n.module] + [f"{n.module}.{a.name}" for a in n.names]
                    if n.module == "lm27":
                        mods += [f"lm27.{a.name}" for a in n.names]
                if any(m == "lm27.privacy" or m.startswith("lm27.privacy.") for m in mods):
                    hits.append(p.relative_to(BRIDGE).as_posix())
        self.assertEqual(sorted(set(hits)), ["gate.py"])

    def test_package_init_lazy(self):
        tree = ast.parse((BRIDGE / "__init__.py").read_text(encoding="utf-8"))
        top = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
        self.assertEqual([getattr(n, "module", None) for n in top], ["__future__"])

    def test_calibrate_name_is_callable_module(self):
        import importlib

        import lm27.bridge as pkg
        mod = importlib.import_module("lm27.bridge.calibrate")
        self.assertIs(pkg.calibrate, mod)
        self.assertTrue(callable(pkg.calibrate))
        self.assertTrue(callable(mod.current))


class StaticGates(unittest.TestCase):
    def test_G_B3_keys_registered(self):
        """G-B3: 이 WP 파일이 이름으로 부르는 bridge.* 키는 모두 레지스트리에 있고, 레지스트리의 bridge.* 는 설정 한 벌이 읽는다."""
        import json

        from lm27.bridge import settings as S
        reg = json.loads((ROOT / "config" / "settings_registry.json").read_text(encoding="utf-8"))["keys"]
        rx = re.compile(r"[\"'](bridge\.[A-Za-z][A-Za-z.]*)[\"']")
        for rel in WP24_FILES:
            for k in rx.findall((BRIDGE / rel).read_text(encoding="utf-8")):
                self.assertIn(k, reg, (rel, k))
        self.assertEqual({k for k in reg if k.startswith("bridge.")}, {k for k, _a in S.KEYS if k.startswith("bridge.")})

    def test_G_B1_G_B2_G_B7(self):
        for rel in WP24_FILES:
            src = (BRIDGE / rel).read_text(encoding="utf-8")
            tree = ast.parse(src)
            lines = src.splitlines()
            for n in ast.walk(tree):
                if isinstance(n, ast.Import):
                    self.assertNotIn("time", [a.name for a in n.names], rel)
                if isinstance(n, ast.ImportFrom):
                    self.assertNotEqual(n.module, "time", rel)
                if isinstance(n, ast.Constant) and type(n.value) in (int, float) and n.value in GB2:
                    self.assertIn("noqa: G-B2", lines[n.lineno - 1], f"{rel}:{n.lineno}")
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "open":
                    mode = n.args[1].value if len(n.args) > 1 and isinstance(n.args[1], ast.Constant) else "r"
                    self.assertFalse(any(c in str(mode) for c in "wax+"), f"{rel}:{n.lineno}")
                if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "write_text_ttl":
                    self.assertIn(rel, ("exchange.py", "manual.py"), rel)


if __name__ == "__main__":
    unittest.main()
