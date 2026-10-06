# -*- coding: utf-8 -*-
"""WP-26 진입점·정적 시험 — %TEMP% 복제 트리에서 동봉 파이썬 ``-X utf8 -I -B`` 로 수집기·탐침을 자식 프로세스로 돌린다
(계약 §7.3 PY 수집기 호출 형식 · v1.2 C1 상태 줄 · §8.6 progress 이벤트 · LM_NO_BROWSER 로 Edge 미기동).

정적: 소유 파일 4개의 인코딩(L-01 · L-02) · 진입 sys.path(L-05) · 수집기 import(L-10 — lm27.privacy 는 sanitize 만) ·
쓰기 0(L-07) · Edge 인자·프로필·포트 키·'office' 호스트 부분 문자열 0(L-16 · G-B12) · 폐지 설정 이름 0(§5.4) · 관문 훅 통과."""
import ast
import json
import re
import subprocess
import sys
import unittest
from datetime import date
from pathlib import Path

from lm27.paths import Paths
from lm27.store import read_store_since
from tests.fixtures.synth import inject, month
from tests.fixtures.tree import CloneTestCase
from tests.fixtures.wp26 import webkit as K

TREE = Path(__file__).resolve().parents[2]
OWNED = [TREE / "collect" / n for n in ("Get-OutlookWeb.py", "Get-TeamsWeb.py", "probe_owa.py", "probe_teamsweb.py")]
MINE = OWNED + sorted((TREE / "tests" / "collect").glob("test_web_*.py")) + sorted((TREE / "tests" / "fixtures" / "wp26").glob("*"))
CTRL = re.compile(rb"[\x00-\x08\x0b\x0c\x0e-\x1f]")
R_ = "R-"


def _status(err: bytes) -> dict:
    lines = [x for x in err.decode("utf-8", "replace").splitlines() if x.strip()]
    return json.loads(lines[-1])["_status"]


class CliTest(CloneTestCase):

    def paths(self) -> Paths:
        return Paths(self.clone.root, lad=self.clone.lad / "LoadMonitor27")

    def py(self, script, *args, env=None):
        return self.clone.run_py(["-I", self.clone.path("collect", script), *args],
                                 env=self.clone.env(env or {}), flags=("-X", "utf8", "-B"), timeout=300)

    def fake_file(self, name, obj) -> str:
        p = self.clone.sandbox / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(json.dumps(obj, ensure_ascii=False).encode("utf-8"))
        return str(p)

    def test_owa_mail_cli(self):
        plan = month.plan_month(2026, 9)
        fake = self.fake_file("owa.json", inject.owa_fake(plan))
        blanks = self.fake_file("blanks_mail.owa.json", [{"todo_id": "mail.owa:2026-09-01:2026-09-30",
                                                           "date_range": ["2026-09-01", "2026-09-30"],
                                                           "kind_axis": "mail_in"}])
        cp = self.py("Get-OutlookWeb.py", "--kind", "mail", "--pc", K.PC, "--blanks-file", blanks,
                     env={"LM_OWA_FAKE": fake})
        st = _status(cp.stderr)
        self.assertEqual((cp.returncode, st["rc"], st["src"], st["schema"]), (0, 0, "mail.owa", "lm27.collector_status/1"),
                         cp.stderr.decode("utf-8", "replace")[-800:])
        for ln in cp.stdout.decode("utf-8").splitlines():                              # stdout = 이벤트 줄(§8.6)만
            ev = json.loads(ln)
            self.assertEqual(ev["ev"], "progress")
            self.assertEqual(ev["stage"], "backfill_owa")
        rows, _cur, _gap = read_store_since(self.paths(), K.PC, "mail", "mail.owa", None)
        self.assertGreater(len(rows), 50)
        self.assertEqual(st["n"], len(rows))
        cur = json.loads((self.paths().raw_cursor(K.PC)).read_bytes())
        self.assertEqual(cur["mail.owa"]["done_ranges"], [["2026-09-01", "2026-09-30"]])

    def test_teams_cli_and_no_browser(self):
        d = date(2026, 9, 21)
        fake = self.fake_file("tw.json", K.tw_fake([K.tw_room(0, K.tid(1, "group"), "과제A 설계")],
                                                   {0: [{"items": [K.tw_sep(d), K.tw_msg(K.KIM, "도면 검토 부탁드립니다", d=d)]}]}))
        cp = self.py("Get-TeamsWeb.py", "--pc", K.PC, "--from", "2026-09-01", "--to", "2026-09-30", "--events", "off",
                     env={"LM_TEAMSWEB_FAKE": fake})
        st = _status(cp.stderr)
        self.assertEqual((cp.returncode, st["src"], st["n"]), (0, "teams.web", 1), cp.stderr.decode("utf-8", "replace")[-600:])
        self.assertEqual(cp.stdout, b"")
        cp = self.py("Get-TeamsWeb.py", "--pc", K.PC, "--events", "off", env={"LM_NO_BROWSER": "1"})
        st = _status(cp.stderr)
        self.assertEqual((cp.returncode, st["reasons"], st["counts"]["session"]), (3, [R_ + "TRANSPORT"], "edge_not_found"))
        cp = self.py("Get-OutlookWeb.py", "--kind", "cal", "--pc", K.PC, "--events", "off", env={"LM_NO_BROWSER": "1"})
        self.assertEqual((cp.returncode, _status(cp.stderr)["reasons"]), (3, [R_ + "TRANSPORT"]))

    def test_bad_args_and_help(self):
        cp = self.py("Get-OutlookWeb.py", "--kind", "mail", "--pc", "PC-1")
        st = _status(cp.stderr)
        self.assertEqual((cp.returncode, st["rc"], st["counts"]["error"]), (3, 3, "BadArguments"))
        cp = self.py("Get-TeamsWeb.py", "--pc", K.PC, "--budget-sec", "0")
        self.assertEqual((cp.returncode, _status(cp.stderr)["reasons"]), (3, [R_ + "TRANSPORT"]))
        for script in ("Get-OutlookWeb.py", "Get-TeamsWeb.py", "probe_owa.py", "probe_teamsweb.py"):
            cp = self.py(script, "--help")
            self.assertEqual(cp.returncode, 0, script)
            self.assertNotIn(b"_status", cp.stderr)

    def test_probes_cli(self):
        fake = self.fake_file("owa_probe.json", {"login": True})
        cp = self.py("probe_owa.py", env={"LM_OWA_FAKE": fake})
        lines = cp.stdout.decode("utf-8").splitlines()
        self.assertEqual((cp.returncode, len(lines)), (0, 1))
        res = json.loads(lines[0])
        self.assertEqual((res["schema"], res["caps"]["web_login"]["reasons"]), ("lm27.probe/1", [R_ + "LOGIN"]))
        cp = self.py("probe_teamsweb.py", env={"LM_NO_BROWSER": "1"})
        res = json.loads(cp.stdout.decode("utf-8").splitlines()[0])
        self.assertEqual((cp.returncode, res["groups"]["P-WEB"]), (0, "skipped"))


class StaticTest(unittest.TestCase):

    def test_encoding_lf_no_bom_no_control(self):
        for p in MINE:
            if p.is_dir() or p.suffix == ".pyc":
                continue
            raw = p.read_bytes()
            self.assertFalse(raw.startswith(b"\xef\xbb\xbf"), p.name)
            self.assertNotIn(b"\r", raw, p.name)
            self.assertIsNone(CTRL.search(raw), p.name)
            raw.decode("utf-8")

    def test_entry_sys_path_and_imports(self):
        ok = ("lm27.store", "lm27.paths", "lm27.config", "lm27.util", "lm27.catalog", "lm27.bridge")
        for p in OWNED:
            tree = ast.parse(p.read_text(encoding="utf-8"))
            ins = [n.lineno for n in tree.body if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
                   and ast.unparse(n.value.func) == "sys.path.insert"]
            first = min((n.lineno for n in tree.body if isinstance(n, ast.ImportFrom) and (n.module or "").startswith("lm27")),
                        default=10 ** 9)
            self.assertTrue(ins and ins[0] < first, p.name)
            for n in ast.walk(tree):
                if isinstance(n, ast.ImportFrom) and (n.module or "").startswith("lm27"):
                    self.assertTrue(n.module == "lm27.privacy.sanitize" or n.module.startswith(ok), (p.name, n.module))
                if isinstance(n, ast.Import):
                    self.assertFalse(any(a.name.startswith("lm27") for a in n.names), p.name)
                if isinstance(n, ast.Call) and ast.unparse(n.func) in ("open", "json.dump", "csv.writer"):
                    self.assertNotIn(ast.unparse(n.func), ("json.dump", "csv.writer"), p.name)
                    mode = n.args[1] if len(n.args) > 1 else next((k.value for k in n.keywords if k.arg == "mode"), None)
                    self.assertFalse(mode is not None and any(c in str(getattr(mode, "value", "w")) for c in "wax+"), p.name)

    def test_no_edge_flags_keys_or_retired_names(self):
        bad = ["--user-" + "data-dir", "--remote-" + "debugging-port", "--remote-allow-" + "origins", "bridge.edge" + ".",
               "office" + ".com", "os.kill" + "(", "graph." + "microsoft.com", "python -m " + "lm27", "_res" + "ult\"",
               "mail.owa" + ".loginWaitSec", "teams.web" + ".loginWaitSec", "mail.owa" + ".profileDir",
               "teams.web" + ".profileDir", "mail.owa" + ".port", "teams.web" + ".port", "teams" + ".selfNames"]
        for p in OWNED:
            text = p.read_text(encoding="utf-8").lower()
            for b in bad:
                self.assertNotIn(b.lower(), text, (p.name, b))

    def test_hook_check_passes(self):
        cp = subprocess.run([sys.executable, "-X", "utf8", "-B", str(TREE / "tools" / "hook_check.py"),
                             *(str(p) for p in OWNED)], capture_output=True, timeout=300, cwd=str(TREE))
        self.assertEqual(cp.returncode, 0, cp.stdout.decode("utf-8", "replace")[-1500:])


if __name__ == "__main__":
    unittest.main()
