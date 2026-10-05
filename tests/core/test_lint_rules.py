# -*- coding: utf-8 -*-
"""WP-04 관문 규칙 시험 — L-01~L-30 마다 '위반 표본 → 실패, 정상 표본 → 통과' 한 쌍 이상.

위반 표본은 시험 중 %TEMP% 의 작은 트리에만 만든다(저장소에 위반 파일을 두지 않는다 — X-313).
이 파일 자체도 관문을 통과해야 하므로 금지 문자열(옛 포트·금지 접근 경로·폐기 이름·사설 IP 등)은
런타임에 조각을 이어 만든다.
"""
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HC_PATH = ROOT / "tools" / "hook_check.py"


def load_hc():
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location("lm27_tools_hook_check", str(HC_PATH))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


HC = load_hc()
WORDS = ("qzx" + "canaryalpha", "qzx" + "canarybeta")  # 합성 금지어(실명 아님) — 이 파일에 통째로 두지 않는다
J = "".join                                           # 금지 문자열 조립용


class Tree:
    """%TEMP% 아래 검사용 작은 트리 — 계약 문서 사본·ruff.toml·합성 금지어 목록(트리 밖)."""

    def __init__(self, docs=("CONTRACT.md",), prefix="lm27t_lint_"):
        self.root = tempfile.mkdtemp(prefix=prefix)
        self.aux = tempfile.mkdtemp(prefix="lm27t_aux_")
        assert os.path.normcase(self.root) != os.path.normcase(str(ROOT))
        for d in docs:
            self.copy(ROOT / "docs" / d, "docs/" + d)
        self.copy(ROOT / "ruff.toml", "ruff.toml")
        self.forbidden = os.path.join(self.aux, "LoadMonitor27", "dev", "forbidden_words.txt")
        os.makedirs(os.path.dirname(self.forbidden))
        with open(self.forbidden, "wb") as fh:
            fh.write(("# 합성 금지어 목록\n" + "\n".join(WORDS) + "\n").encode("utf-8"))

    def copy(self, src, rel):
        dst = os.path.join(self.root, *rel.split("/"))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(str(src), dst)
        return dst

    def write(self, rel, data, enc="utf-8"):
        p = os.path.join(self.root, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        if isinstance(data, str):
            data = data.encode(enc)
        with open(p, "wb") as fh:
            fh.write(data)
        return p

    def remove(self, rel):
        os.remove(os.path.join(self.root, *rel.split("/")))

    def ctx(self, **kw):
        kw.setdefault("forbidden_path", self.forbidden)
        return HC.Ctx(self.root, **kw)

    def file(self, rel, rules, **kw):
        return HC.check_file(os.path.join(self.root, *rel.split("/")), ctx=self.ctx(**kw), rules=rules)

    def repo(self, rules, **kw):
        return HC.check_repo(ctx=self.ctx(**kw), rules=rules)

    def close(self):
        shutil.rmtree(self.root, ignore_errors=True)
        shutil.rmtree(self.aux, ignore_errors=True)


def errs(found, rule=None):
    return [f for f in found if not f.warn and (rule is None or f.rule == rule)]


def warns(found, rule=None):
    return [f for f in found if f.warn and (rule is None or f.rule == rule)]


def registry_obj(keys, owner="lm27.nothere.mod", **defaults):
    ent = {k: {"default": defaults.get(k), "owner": owner} for k in sorted(keys)}
    return {"schema": "lm27.settings_registry/1", "keys": ent}


class RuleCase(unittest.TestCase):
    docs = ("CONTRACT.md",)

    def setUp(self):
        self.t = Tree(self.docs)

    def tearDown(self):
        self.t.close()

    def hit(self, found, rule, n=None):
        e = errs(found, rule)
        self.assertTrue(e, f"{rule} 위반을 잡지 못함: {found}")
        if n is not None:
            self.assertEqual(len(e), n, e)

    def clean(self, found, rule):
        self.assertEqual(errs(found, rule), [], f"{rule} 정상 표본이 실패: {errs(found, rule)}")


class TestEncodingRules(RuleCase):
    def test_L01_control_char(self):
        self.t.write("lm27/a.py", "x = 'data" + chr(7) + "ctivity'\n")
        self.t.write("lm27/b.py", "x = 'data\\\\activity'\n")
        self.hit(self.t.file("lm27/a.py", ["L-01"]), "L-01")
        self.clean(self.t.file("lm27/b.py", ["L-01"]), "L-01")

    def test_L02_ps1_bom_crlf(self):
        body = "Write-Output '한글'\nexit 0\n"
        self.t.write("collect/bad.ps1", body)
        self.t.write("collect/good.ps1", b"\xef\xbb\xbf" + body.replace("\n", "\r\n").encode("utf-8"))
        self.hit(self.t.file("collect/bad.ps1", ["L-02"]), "L-02")
        self.clean(self.t.file("collect/good.ps1", ["L-02"]), "L-02")

    def test_L02_bat_cp949_crlf_header(self):
        good = '@echo off\r\n>nul chcp 949\r\npushd "%TEMP%"\r\necho 한글\r\npopd\r\n'
        self.t.write("good.bat", good, enc="cp949")
        self.t.write("lf.bat", good.replace("\r\n", "\n"), enc="cp949")
        self.t.write("nochcp.bat", '@echo off\r\npushd "%TEMP%"\r\n', enc="cp949")
        self.t.write("utf8.bat", good, enc="utf-8")
        self.clean(self.t.file("good.bat", ["L-02"]), "L-02")
        for bad in ("lf.bat", "nochcp.bat", "utf8.bat"):
            self.hit(self.t.file(bad, ["L-02"]), "L-02")

    def test_L02_lf_text_files(self):
        self.t.write("lm27/crlf.py", "x = 1\r\n")
        self.t.write("config/bom.json", b"\xef\xbb\xbf{}\n")
        self.t.write("lm27/ok.py", "x = 1\n")
        self.t.write(".gitignore", "data/\r\n")
        self.hit(self.t.file("lm27/crlf.py", ["L-02"]), "L-02")
        self.hit(self.t.file("config/bom.json", ["L-02"]), "L-02")
        self.hit(self.t.file(".gitignore", ["L-02"]), "L-02")
        self.clean(self.t.file("lm27/ok.py", ["L-02"]), "L-02")

    def test_L03_ruff_no_cache(self):
        if not self.t.ctx().ruff_cmd():
            self.skipTest("ruff 없음 — 개발 PC 도구")
        self.t.write("lm27/bad.py", "import os\n")
        self.t.write("lm27/good.py", "import os\n\nprint(os.sep)\n")
        # 진입 스크립트(tools\*.py)는 sys.path 삽입 뒤 import — ruff.toml 의 E402 예외가 먹어야 한다
        self.t.write("tools/entry.py", "import os\nimport sys\n\nsys.path.insert(0, os.getcwd())\nimport json\n\n"
                                       "print(json.dumps(1))\n")
        # 계약 §9.1 형식(datetime.now(timezone.utc))과 같은 객체 별칭(datetime.UTC) 둘 다 통과해야 한다(UP017 끔)
        self.t.write("lm27/utc.py", "from datetime import UTC, datetime, timezone\n\n"
                                    "A = datetime.now(timezone.utc)\nB = datetime.now(UTC)\n")
        self.hit(self.t.file("lm27/bad.py", ["L-03"]), "L-03")
        self.clean(self.t.file("lm27/good.py", ["L-03"]), "L-03")
        self.clean(self.t.file("tools/entry.py", ["L-03"]), "L-03")
        self.clean(self.t.file("lm27/utc.py", ["L-03"]), "L-03")
        found = self.t.repo(["L-03"])
        self.assertTrue(any(f.rel.endswith("bad.py") for f in errs(found, "L-03")))
        self.assertFalse(os.path.exists(os.path.join(self.t.root, ".ruff_cache")), "ruff 캐시가 트리에 생김")
        self.assertIn("--no-cache", HC.ruff_args(self.t.ctx(), ["x.py"]))


class TestPythonRules(RuleCase):
    def test_L04_zoneinfo(self):
        self.t.write("lm27/a.py", J(["from zoneinfo import ", "Zone", "Info\n"]))
        self.t.write("lm27/b.py", J(["import zoneinfo\n", "z = zoneinfo.", "Zone", "Info('Asia/Seoul')\n"]))
        self.t.write("lm27/c.py", "from datetime import timezone\nU = timezone.utc\n")
        self.hit(self.t.file("lm27/a.py", ["L-04"]), "L-04")
        self.hit(self.t.file("lm27/b.py", ["L-04"]), "L-04")
        self.clean(self.t.file("lm27/c.py", ["L-04"]), "L-04")

    def test_L05_dash_m_and_entry_insert(self):
        dm = J(["-", "m lm", "27"])
        self.t.write("x.bat", '@echo off\r\n>nul chcp 949\r\npushd "%TEMP%"\r\npython ' + dm + ' collect\r\n', enc="cp949")
        self.t.write("lm27/run.py", "import subprocess\nsubprocess.run(['py', '-" + "m', 'lm" + "27', 'ui'])\n")
        self.t.write("tools/late.py", "import sys\nfrom lm27 import cli\nsys.path.insert(0, 'x')\n")
        self.t.write("tools/none.py", "import json\nprint(json.dumps(1))\n")
        self.t.write("tools/ok.py", '"""도구."""\nimport os\nimport sys\n\nROOT = os.path.dirname(os.path.dirname('
                                    'os.path.abspath(__file__)))\nsys.path.insert(0, ROOT)\nfrom lm27 import cli  # noqa\n')
        self.t.write("lm27_cli.py", "import os\nimport sys\nsys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))\n"
                                    "from lm27.cli import main\nsys.exit(main())\n")
        for bad in ("x.bat", "lm27/run.py", "tools/late.py", "tools/none.py"):
            self.hit(self.t.file(bad, ["L-05"]), "L-05")
        self.clean(self.t.file("tools/ok.py", ["L-05"]), "L-05")
        self.clean(self.t.file("lm27_cli.py", ["L-05"]), "L-05")

    def test_L06_import_error_swallow(self):
        self.t.write("lm27/a.py", "try:\n    import foo\nexcept ImportError:\n    foo = None\n")
        self.t.write("lm27/b.py", "try:\n    import foo\nexcept (OSError, ModuleNotFoundError):\n    pass\n")
        self.t.write("lm27/c.py", "def run():\n    try:\n        import foo  # noqa: F401\n    except ImportError as e:\n"
                                  "        print(type(e).__name__)\n        return 1\n    return 0\n")
        self.t.write("lm27/d.py", "try:\n    import foo\nexcept ImportError as e:\n    raise SystemExit(1) from e\n")
        self.t.write("tests/core/test_x.py", "try:\n    import foo\nexcept ImportError:\n    foo = None\n")
        self.hit(self.t.file("lm27/a.py", ["L-06"]), "L-06")
        self.hit(self.t.file("lm27/b.py", ["L-06"]), "L-06")
        self.clean(self.t.file("lm27/c.py", ["L-06"]), "L-06")
        self.clean(self.t.file("lm27/d.py", ["L-06"]), "L-06")
        self.clean(self.t.file("tests/core/test_x.py", ["L-06"]), "L-06")

    def test_L07_final_write_open(self):
        w = "def f(p):\n    with open(p, 'w', encoding='utf-8') as fh:\n        fh.write('x')\n"
        self.t.write("lm27/report/x.py", w)
        self.t.write("lm27/util/fsx.py", w)
        self.t.write("lm27/a.py", "from pathlib import Path\nPath('x').write_text('y')\n")
        self.t.write("lm27/b.py", "import gzip\ngzip.open('x.gz', 'ab')\n")
        self.t.write("lm27/bridge/runner.py", "from lm27.bridge.fsio import write_text_ttl\nwrite_text_ttl('p', 't')\n")
        self.t.write("lm27/bridge/manual.py", "from lm27.bridge.fsio import write_text_ttl\nwrite_text_ttl('p', 't')\n")
        self.t.write("lm27/collect/plan.py", "import json\nimport sys\njson.dump({}, sys.stdout)\n")
        self.t.write("lm27/r.py", "def f(p):\n    with open(p, 'rb') as fh:\n        return fh.read()\n")
        for bad in ("lm27/report/x.py", "lm27/a.py", "lm27/b.py", "lm27/bridge/runner.py", "lm27/collect/plan.py"):
            self.hit(self.t.file(bad, ["L-07"]), "L-07")
        for good in ("lm27/util/fsx.py", "lm27/bridge/manual.py", "lm27/r.py"):
            self.clean(self.t.file(good, ["L-07"]), "L-07")

    def test_L08_single_loader(self):
        self.t.write("lm27/report/x.py", "import os\ndef f(r):\n    return os.path.join(r, 'data', 'derived')\n")
        self.t.write("lm27/ui/y.py", "from pathlib import Path\ndef f(r):\n    return Path(r) / 'data'\n")
        self.t.write("lm27/normalize/z.py", "import os\ndef f(r):\n    return os.path.join(r, 'pcs')\n")
        self.t.write("lm27/team/s.py", "P = 'data\\\\pcs\\\\x'\n")
        self.t.write("lm27/paths.py", "import os\ndef f(r):\n    return os.path.join(r, 'data', 'pcs')\n")
        self.t.write("lm27/bundle/loader.py", "import os\ndef f(d):\n    return os.path.join(d, 'pcs')\n")
        self.t.write("tools/pkg.py", "def skip(rel):\n    return rel.startswith('data/')\n")
        found = self.t.repo(["L-08"])
        bad = {f.rel.replace("\\", "/") for f in errs(found, "L-08")}
        self.assertEqual(bad, {"lm27/report/x.py", "lm27/ui/y.py", "lm27/normalize/z.py", "lm27/team/s.py"}, found)

    def test_L09_collector_ps_write(self):
        bom = b"\xef\xbb\xbf"
        bad = "$x | Out-File \"$env:LOCALAPPDATA\\LoadMonitor27\\x.json\"\r\n"
        bad2 = "$rows | Export-Csv -Path 'data\\pcs\\x.csv'\r\n"
        ok = "# Set-Content data\\x — 주석은 보지 않는다\r\n$rows | ConvertTo-Json -Compress\r\n"
        hb = "Set-Content -Path (Join-Path $env:LOCALAPPDATA 'LoadMonitor27\\agent\\heartbeat.json') -Value $j\r\n"
        self.t.write("collect/Get-Bad.ps1", bom + bad.encode("utf-8"))
        self.t.write("collect/Get-Bad2.ps1", bom + bad2.encode("utf-8"))
        self.t.write("collect/Get-Ok.ps1", bom + ok.encode("utf-8"))
        self.t.write("collect/agent/agent.ps1", bom + hb.encode("utf-8"))
        self.t.write("collect/Get-Hb.ps1", bom + hb.encode("utf-8"))
        for b in ("collect/Get-Bad.ps1", "collect/Get-Bad2.ps1", "collect/Get-Hb.ps1"):
            self.hit(self.t.file(b, ["L-09"]), "L-09")
        for g in ("collect/Get-Ok.ps1", "collect/agent/agent.ps1"):
            self.clean(self.t.file(g, ["L-09"]), "L-09")

    def test_L10_collector_imports(self):
        self.t.write("collect/Get-A.py", "from lm27.privacy.detect import scan\n")
        self.t.write("collect/Get-B.py", "import lm27.normalize.act\n")
        self.t.write("collect/Get-C.py", "from lm27.privacy import sanitize_record\n")
        self.t.write("collect/Get-Ok.py", "from lm27.privacy.sanitize import sanitize_record\nfrom lm27.store import "
                                          "SegmentWriter\nfrom lm27 import paths, config\nfrom lm27.privacy import sanitize\n")
        for b in ("collect/Get-A.py", "collect/Get-B.py", "collect/Get-C.py"):
            self.hit(self.t.file(b, ["L-10"]), "L-10")
        self.clean(self.t.file("collect/Get-Ok.py", ["L-10"]), "L-10")

    def test_L11_store_bypass(self):
        self.t.write("lm27/collect/x.py", "from lm27.privacy.records import SanitizedRow\nr = SanitizedRow('mail', {}, None)\n")
        self.t.write("lm27/agent/y.py", "from lm27.privacy import records\nS = records._SEAL\n")
        self.t.write("lm27/agent/z.py", "def f(paths):\n    return paths.store_file('pc_x', 'mail', 'mail.com', '20261005')\n")
        self.t.write("lm27/privacy/records.py", "_SEAL = object()\nclass SanitizedRow:\n    pass\nr = SanitizedRow()\n")
        self.t.write("lm27/store/writer.py", "from lm27.privacy import records\ndef ok(x):\n    return x._seal is records._SEAL\n")
        for b in ("lm27/collect/x.py", "lm27/agent/y.py", "lm27/agent/z.py"):
            self.hit(self.t.file(b, ["L-11"]), "L-11")
        for g in ("lm27/privacy/records.py", "lm27/store/writer.py"):
            self.clean(self.t.file(g, ["L-11"]), "L-11")


class TestConfigKeys(RuleCase):
    def setUp(self):
        super().setUp()
        self.keys = HC.parse_cfg_keys((ROOT / "docs" / "CONTRACT.md").read_text(encoding="utf-8"))

    def put_registry(self, obj):
        self.t.write("config/settings_registry.json", json.dumps(obj, ensure_ascii=False, indent=1) + "\n")

    def test_contract_table_parse(self):
        self.assertGreater(len(self.keys), 400)
        for k in ("team.serverHost", "hier.merge.ask", "time.envelope.preWindowMin.teams", "bridge.dom.assistantSelectors"):
            self.assertIn(k, self.keys)
        self.assertTrue(all(HC.CAMEL_KEY.match(k) for k in self.keys))

    def test_L12_complete_registry_passes(self):
        self.put_registry(registry_obj(self.keys))
        self.t.write("lm27/x/reader.py", "def f(cfg):\n    return cfg['collect.parallelMax']\n")
        found = self.t.repo(["L-12"])
        self.clean(found, "L-12")
        self.assertTrue(warns(found, "L-12"), "owner 미생성 키는 경고로 남아야 함")

    def test_L12_missing_and_extra_and_snake(self):
        reg = registry_obj(self.keys - {"collect.parallelMax"})
        reg["keys"]["collect.bad_key"] = {"default": 1, "owner": "lm27.nothere.mod"}
        self.put_registry(reg)
        msgs = " ".join(str(f) for f in errs(self.t.repo(["L-12"]), "L-12"))
        self.assertIn("collect.parallelMax", msgs)
        self.assertIn("collect.bad_key", msgs)

    def test_L12_unregistered_and_old_reads(self):
        self.put_registry(registry_obj(self.keys))
        self.t.write("lm27/x/reader.py", "def f(cfg):\n    return cfg['collect.notAKeyX'], cfg.get('mail.owa.port')\n")
        e = errs(self.t.repo(["L-12"]), "L-12")
        self.assertEqual(len(e), 2, e)

    def test_L12_dead_key_staged_by_owner(self):
        reg = registry_obj(self.keys)
        reg["keys"]["collect.budgetSec"]["owner"] = "lm27.x.reader"
        self.put_registry(reg)
        self.t.write("lm27/x/reader.py", "def f(cfg):\n    return cfg['collect.parallelMax']\n")
        e = errs(self.t.repo(["L-12"]), "L-12")
        self.assertTrue(any("collect.budgetSec" in f.msg for f in e), e)
        self.t.write("lm27/x/reader.py", "def f(cfg):\n    return cfg['collect.budgetSec']\n")
        self.clean(self.t.repo(["L-12"]), "L-12")
        # W2 통합 창부터는 owner 미생성이어도 실패(CR-05)
        self.assertTrue(errs(self.t.repo(["L-12"], l12_full=True), "L-12"))

    def test_L12_prefix_read_counts(self):
        reg = registry_obj(self.keys)
        for k in reg["keys"]:
            if k.startswith("time.envelope.preWindowMin."):
                reg["keys"][k]["owner"] = "lm27.x.reader"
        self.put_registry(reg)
        self.t.write("lm27/x/reader.py", "def f(cfg, k):\n    return cfg[f'time.envelope.preWindowMin.{k}']\n")
        self.clean(self.t.repo(["L-12"]), "L-12")


class TestCodeTables(RuleCase):
    def test_L13_reason_codes(self):
        dep = J(["R", "-SAMPLER-CLM"])
        bogus = J(["R-", "ZZBOGUS"])
        self.t.write("lm27/ok.py", "A = 'R-NEWOL'\nB = 'R-BUNDLE-*'\nC = 'R-P3'\nD = 'TAB R-4'\n")
        self.t.write("docs/x.md", "폐지 " + dep + "\n")
        self.t.write("lm27/bad.py", "A = '" + bogus + "'\n")
        self.t.write("web/app/app.js", "const c = '" + dep + "';\n")
        found = self.t.repo(["L-13"])
        bad = {f.rel.replace("\\", "/") for f in errs(found, "L-13")}
        self.assertEqual(bad, {"lm27/bad.py", "web/app/app.js"}, found)

    def test_L14_path_ids_and_kinds(self):
        self.t.write("lm27/a.py", "SRC = 'mail.outlook'\n")
        self.t.write("lm27/b.py", "KINDS = ('mail', 'cal', 'pc_window')\n")
        self.t.write("lm27/c.py", "def f(rec):\n    return rec['kind'] == 'pc_sessions'\n")
        self.t.write("collect/Get-X.ps1", b"\xef\xbb\xbf& $py $pipe --src mail.bogus --kind mail\r\n")
        self.t.write("lm27/ok.py", "SRC = 'mail.com'\nKINDS = ('mail', 'cal', 'teams', 'pc_session')\n"
                                   "STOP_KINDS = ('budget', 'stall')\nF = 'pc.json'\n"
                                   "def f(r):\n    return r['kind'] in ('pc_file', 'manual') or r.get('kind') == 'single'\n")
        found = self.t.repo(["L-14"])
        bad = {f.rel.replace("\\", "/") for f in errs(found, "L-14")}
        self.assertEqual(bad, {"lm27/a.py", "lm27/b.py", "lm27/c.py", "collect/Get-X.ps1"}, found)

    def test_L15_task_and_mutex_names(self):
        fixed = J(["LM27", "-Agent"])
        self.t.write("lm27/agent/install.py", "TASK = '" + fixed + "'\n")
        self.t.write("collect/agent/Register-Agent.ps1", b"\xef\xbb\xbf" + ("$n = '" + fixed + "'\r\n").encode())
        self.t.write("tests/agent/test_reg.py", "NAME = '" + J(["LM27", "-abc"]) + "'\n")
        self.t.write("lm27/agent/xml.py", "def x(ROOT):\n    return f'<WorkingDirectory>{ROOT}</WorkingDirectory>'\n")
        self.t.write("lm27/agent/ok.py", "def name(install_id):\n    return f'LM27-{install_id}', 'Local\\\\LM27-' + install_id\n")
        self.t.write("collect/agent/ok.ps1", b'\xef\xbb\xbf$n = "LM27-$InstallId"\r\n')
        self.t.write("tests/agent/test_ok.py", "NAME = 'LM27T-abc'\n")
        found = self.t.repo(["L-15"])
        bad = {f.rel.replace("\\", "/") for f in errs(found, "L-15")}
        self.assertEqual(bad, {"lm27/agent/install.py", "collect/agent/Register-Agent.ps1", "tests/agent/test_reg.py",
                               "lm27/agent/xml.py"}, found)


class TestBridgeAndScreen(RuleCase):
    def test_L16_edge_flags(self):
        self.t.write("collect/Get-W.py", "ARGS = ['--user-data-dir=x']\n")
        self.t.write("lm27/collect/plan.py", "K = 'bridge.edge.port'\n")
        self.t.write("lm27/a.py", "import os\nos.kill(1, 9)\n")
        self.t.write("lm27/b.py", "H = 'https://www.office.com'\n")
        self.t.write("lm27/bridge/cdp.py", "A = '--remote-allow-origins=" + "*'\n")
        self.t.write("lm27/bridge/session.py", "ARGS = ['--user-data-dir=x', '--remote-debugging-port=1']\nK = 'bridge.edge.port'\n")
        for b in ("collect/Get-W.py", "lm27/collect/plan.py", "lm27/a.py", "lm27/b.py", "lm27/bridge/cdp.py"):
            self.hit(self.t.file(b, ["L-16"]), "L-16")
        self.clean(self.t.file("lm27/bridge/session.py", ["L-16"]), "L-16")

    def test_L17_bridge_clock_and_limits(self):
        self.t.write("lm27/bridge/runner.py", "import time\ntime.sleep(1)\nLIMIT = 8000\n")
        self.t.write("lm27/bridge/clock.py", "import time\ndef now():\n    return time.monotonic()\n")
        self.t.write("lm27/bridge/settings.py", "LIMIT = 8000\nANS = 5000\n")
        self.t.write("lm27/bridge/jsonx.py", "N = 8000  # noqa: G-B2\n")
        found = self.t.repo(["L-17"])
        bad = {f.rel.replace("\\", "/") for f in errs(found, "L-17")}
        self.assertEqual(bad, {"lm27/bridge/runner.py"}, found)
        self.assertEqual(len(errs(found, "L-17")), 3, found)

    def test_L18_no_time_to_copilot(self):
        self.t.write("lm27/bridge/stages/speech_act.py", "SEND_FIELDS = ('text', 'ts_utc')\n")
        self.t.write("lm27/bridge/stages/task_label.py", "HEAD = '총 3시간 걸린 작업'\n")
        self.t.write("lm27/hier/prompts.py", "T = '투입 0.5MM 기준'\n")
        self.t.write("lm27/bridge/stages/review_text.py", "SEND_FIELDS = ('text', 'chan', 'dir', 'prev_act')\nH = '항목 3개'\n")
        for b in ("lm27/bridge/stages/speech_act.py", "lm27/bridge/stages/task_label.py", "lm27/hier/prompts.py"):
            self.hit(self.t.file(b, ["L-18"]), "L-18")
        self.clean(self.t.file("lm27/bridge/stages/review_text.py", ["L-18"]), "L-18")

    def test_L19_screen_rules(self):
        inner = J(["el.inner", "HTML = v;\n"])
        self.t.write("web/app/a.js", inner)
        self.t.write("web/app/b.js", "const s = (x).toFixed(1);\n")
        self.t.write("web/app/c.css", ".a { color: #ff0000; }\n")
        self.t.write("web/app/d.html", '<script src="https://cdn.' + 'example.com/x.js"></script>\n')
        self.t.write("web/app/e.js", "const s = '</scr' + 'ipt>';\nconst t = '</script>';\n")
        self.t.write("lm27/report/model.py", "def f(total_min):\n    return round(total_min / 60, 1)\n")
        self.t.write("lm27/ui/api_home.py", "def f(x):\n    return f'<div>{x}</div>'\n")
        self.t.write("web/common/lm27.css", ":root { --blue: #2a78d6; }\n")
        self.t.write("web/common/lm27charts.js", "const NS = 'http://www.w3.org/2000/svg';\n"
                                                 "function g() { return document.createElementNS(NS, 'g'); }\n")
        self.t.write("lm27/report/fmt.py", "def h1(m):\n    return round(m / 60, 1)\n")
        self.t.write("lm27/report/export.py", "def island(x):\n    return f'<script>{x}</script>'\n")
        self.t.write("lm27/report/drill.py", "from pathlib import Path\ndef p(out, name):\n    return out / name\n")
        for b in ("web/app/a.js", "web/app/b.js", "web/app/c.css", "web/app/d.html", "web/app/e.js",
                  "lm27/report/model.py", "lm27/ui/api_home.py"):
            self.hit(self.t.file(b, ["L-19"]), "L-19")
        for g in ("web/common/lm27.css", "web/common/lm27charts.js", "lm27/report/fmt.py", "lm27/report/export.py",
                  "lm27/report/drill.py"):
            self.clean(self.t.file(g, ["L-19"]), "L-19")

    def test_L19_domain_meta_colors(self):
        dm = {c: {"name": n, "color": col} for c, (n, col) in HC.FALLBACK_DOMAINS.items()}
        self.t.write("lm27/hier/vocab.py", "DOMAIN_META = " + repr(dm) + "\n")
        self.clean(self.t.repo(["L-19"]), "L-19")
        dm["DEV"]["color"] = "#000000"
        self.t.write("lm27/hier/vocab.py", "DOMAIN_META = " + repr(dm) + "\n")
        self.hit(self.t.repo(["L-19"]), "L-19")

    def test_L20_exclusive_bind(self):
        self.t.write("lm27/team/a.py", "import socket\ndef f(s):\n    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)\n")
        self.t.write("lm27/team/b.py", "from http.server import HTTPServer\nclass S(HTTPServer):\n    pass\n")
        self.t.write("lm27/team/c.py", "from http.server import HTTPServer\ndef f(h):\n    return HTTPServer(('127.0.0.1', 0), h)\n")
        self.t.write("lm27/team/d.py", "class S:\n    allow_reuse_address = True\n")
        self.t.write("lm27/team/ok.py", "from http.server import ThreadingHTTPServer\nclass S(ThreadingHTTPServer):\n"
                                        "    allow_reuse_address = False\n")
        for b in ("lm27/team/a.py", "lm27/team/b.py", "lm27/team/c.py", "lm27/team/d.py"):
            self.hit(self.t.file(b, ["L-20"]), "L-20")
        self.clean(self.t.file("lm27/team/ok.py", ["L-20"]), "L-20")


class TestTeamAndPrivacy(RuleCase):
    docs = ("CONTRACT.md", "TEAM_AND_BUNDLE.md", "PRIVACY.md")

    def test_L21_team_url_and_private_ip(self):
        priv = ".".join(["192", "168", "1", "10"])
        host = HC.TEAM_HOST
        keys = HC.parse_cfg_keys((ROOT / "docs" / "CONTRACT.md").read_text(encoding="utf-8"))
        reg = registry_obj(keys)
        reg["keys"]["team.serverHost"]["default"] = host
        reg["keys"]["team.serverPort"]["default"] = HC.TEAM_PORT
        self.t.write("config/settings_registry.json", json.dumps(reg) + "\n")
        self.t.write("lm27/team/client.py", "DEFAULT_TEAM_URL = 'http://" + host + ":" + str(HC.TEAM_PORT) + "'\n")
        self.t.write("docs/x.md", "예시 " + priv + "\n")
        self.clean(self.t.repo(["L-21"]), "L-21")
        self.t.write("lm27/a.py", "H = '" + priv + "'\n")
        self.t.write("lm27/ui/b.py", "H = '" + host + "'\n")
        reg["keys"]["team.serverHost"]["default"] = "127.0.0.1"
        self.t.write("config/settings_registry.json", json.dumps(reg) + "\n")
        self.t.write("lm27/team/client.py", "DEFAULT_TEAM_URL = 'http://127.0.0.1:1'\n")
        found = self.t.repo(["L-21"])
        bad = {f.rel.replace("\\", "/") for f in errs(found, "L-21")}
        self.assertEqual(bad, {"lm27/a.py", "lm27/ui/b.py", "config/settings_registry.json", "lm27/team/client.py"}, found)

    def test_L22_team_builder(self):
        self.t.write("lm27/team/build.py", "def b(a, an):\n    x = {**a}\n    y = dict(a)\n    return x, y, an.host_display\n")
        self.t.write("lm27/report/x.py", "def f(paths):\n    return paths.registry_cache()\n")
        self.t.write("lm27/team/client.py", "def f(paths):\n    return paths.registry_cache()\n")
        found = self.t.repo(["L-22"])
        bad = {f.rel.replace("\\", "/") for f in errs(found, "L-22")}
        self.assertEqual(bad, {"lm27/team/build.py", "lm27/report/x.py"}, found)
        self.assertGreaterEqual(len([f for f in errs(found) if f.rel.endswith("build.py")]), 3)
        self.t.write("lm27/team/build.py", "def b(a):\n    return {'schema': 'lm27.team_bundle', 'units': list(a)}\n")
        self.t.remove("lm27/report/x.py")
        self.clean(self.t.repo(["L-22"]), "L-22")

    def test_L23_team_spec_single_source(self):
        tab, pri = HC.parse_team_fields((ROOT / "docs" / "TEAM_AND_BUNDLE.md").read_text(encoding="utf-8"),
                                        (ROOT / "docs" / "PRIVACY.md").read_text(encoding="utf-8"))
        self.assertIn("envelope_daily", tab)
        fields = sorted(tab | pri)
        body = "TEAM_SPEC_V1 = {" + ", ".join(f"{k!r}: None" for k in fields) + "}\n"
        self.t.write("lm27/team/schema.py", body)
        self.clean(self.t.repo(["L-23"]), "L-23")
        self.t.write("lm27/team/schema.py", body.replace("'units': None, ", ""))
        self.hit(self.t.repo(["L-23"]), "L-23")
        self.t.write("lm27/team/schema.py", body)
        self.t.write("lm27/privacy/gate.py", "TEAM_SPEC_V1 = {}\n")
        self.hit(self.t.repo(["L-23"]), "L-23")

    def test_L24_rules_lock_and_empty_defaults(self):
        self.t.write("lm27/privacy/rules.py", "RULES_VERSION = '2026.10.0'\nRULES_HASH = 'abcdef0123456789'\n")
        lock = {"rules_ver": "2026.10.0", "rules_hash": "abcdef0123456789"}
        self.t.write("lm27/privacy/rules.lock.json", json.dumps(lock) + "\n")
        self.t.write(".gitignore", "data/\nout/\nconfig/config.json\n")
        self.clean(self.t.repo(["L-24"]), "L-24")
        lock["rules_hash"] = "0000000000000000"
        self.t.write("lm27/privacy/rules.lock.json", json.dumps(lock) + "\n")
        self.hit(self.t.repo(["L-24"]), "L-24")
        lock["rules_hash"] = "abcdef0123456789"
        self.t.write("lm27/privacy/rules.lock.json", json.dumps(lock) + "\n")
        reg = registry_obj({"privacy.customers"})
        reg["keys"]["privacy.customers"]["default"] = [{"id": "C01", "names": ["고객사A"], "domains": []}]
        self.t.write("config/settings_registry.json", json.dumps(reg, ensure_ascii=False) + "\n")
        self.hit(self.t.repo(["L-24"]), "L-24")
        self.t.remove("config/settings_registry.json")
        self.t.write(".gitignore", "out/\n")
        self.hit(self.t.repo(["L-24"]), "L-24")

    def test_L25_hier_feedback_and_domain_literals(self):
        self.t.write("lm27/hier/learn.py", "from lm27.hier.proposals import ProposalQueue\n")
        self.t.write("lm27/hier/rules.py", "P = 'ai_out'\n")
        self.t.write("lm27/report/x.py", "NAME = '개발 프로젝트'\n")
        self.t.write("web/app/app.js", "const c = '#2a78d6';\n")
        self.t.write("lm27/hier/vocab.py", "DOMAIN_META = {'DEV': {'name': '개발 프로젝트', 'color': '#2a78d6'}}\n")
        self.t.write("lm27/hier/match.py", "def f(reg):\n    return reg.domain_name('DEV') + ' 프로젝트 목록'\n")
        for b in ("lm27/hier/learn.py", "lm27/hier/rules.py", "lm27/report/x.py", "web/app/app.js"):
            self.hit(self.t.file(b, ["L-25"]), "L-25")
        for g in ("lm27/hier/vocab.py", "lm27/hier/match.py"):
            self.clean(self.t.file(g, ["L-25"]), "L-25")

    def test_L26_forbidden_words_and_email(self):
        self.t.write("lm27/a.py", "OWNER = 'x " + WORDS[0].upper() + " y'\n")
        self.t.write("lm27/b.py", "M = 'someone@" + "corp-mail.co.kr'\n")
        self.t.write("lm27/ok.py", "M = ('hong@example.com', 'kim@team.example', 'a@mail.example.com')\n")
        self.t.write("docs/x.md", "예 someone@" + "corp-mail.co.kr\n")
        found_a = self.t.file("lm27/a.py", ["L-26"])
        self.hit(found_a, "L-26")
        for f in found_a:
            self.assertNotIn(WORDS[0], str(f).lower(), "금지어 낱말을 출력하면 안 된다")
        self.hit(self.t.file("lm27/b.py", ["L-26"]), "L-26")
        self.clean(self.t.file("lm27/ok.py", ["L-26"]), "L-26")
        self.clean(self.t.file("docs/x.md", ["L-26"]), "L-26")

    def test_CR14_exception_table_is_path_based(self):
        priv = ".".join(["10", "1", "2", "3"])
        mail = "someone@" + "corp-mail.co.kr"
        line = json.dumps({"input": mail + " " + priv}, ensure_ascii=False) + "\n"
        self.t.write("lm27/privacy/corpus/regress_v1.jsonl", line)
        self.t.write("lm27/privacy/corpus/other.jsonl", line)
        ok = self.t.repo(["L-21", "L-26"])
        bad = {(f.rule, f.rel.replace("\\", "/")) for f in errs(ok)}
        self.assertEqual(bad, {("L-21", "lm27/privacy/corpus/other.jsonl"), ("L-26", "lm27/privacy/corpus/other.jsonl")},
                         ok)

    def test_L26_missing_list_fails_closed(self):
        self.t.write("lm27/ok.py", "X = 1\n")
        found = self.t.file("lm27/ok.py", ["L-26"], forbidden_path=os.path.join(self.t.aux, "없음.txt"))
        self.hit(found, "L-26")


class TestRepoWideRules(RuleCase):
    def test_L27_node_check(self):
        self.t.write("web/app/bad.js", "function (\n")
        self.t.write("web/app/good.js", "'use strict';\nconst a = 1;\nconsole.log(a);\n")
        found = self.t.repo(["L-27"])
        if not self.t.ctx().node():
            self.assertTrue(warns(found, "L-27"), "node 가 없으면 '건너뜀' 경고")
            return
        bad = {f.rel.replace("\\", "/") for f in errs(found, "L-27")}
        self.assertEqual(bad, {"web/app/bad.js"}, found)

    def test_L28_old_ports_and_names(self):
        p = 9000 + 333
        q = 8000 + 765
        self.t.write("lm27/ui/server.py", "PORT = " + str(p) + "\n")
        self.t.write("collect/Get-X.ps1", b"\xef\xbb\xbf" + ("$u = 'http://127.0.0.1:" + str(q) + "/'\r\n").encode())
        self.t.write("lm27/agent/n.py", "TASK = '" + J(["LoadMonitor", "26"]) + "'\n")
        self.t.write("lm27/ui/ok.py", "PORT = 19280\nCDP = 9343\nTEAM = 9310\n")
        found = self.t.repo(["L-28"])
        bad = {f.rel.replace("\\", "/") for f in errs(found, "L-28")}
        self.assertEqual(bad, {"lm27/ui/server.py", "collect/Get-X.ps1", "lm27/agent/n.py"}, found)

    def test_L29_retired_outputs(self):
        self.t.write("lm27/collect/x.py", "OUT = '" + J(["mail", ".csv"]) + "'\n")
        self.t.write("collect/Get-Y.ps1", b"\xef\xbb\xbf" + ("$o = 'teams_window" + "_raw.txt'\r\n").encode())
        self.t.write("lm27/collect/ok.py", "OUT = ('teams_coverage.jsonl', 'coverage_ledger.jsonl')\n")
        found = self.t.repo(["L-29"])
        bad = {f.rel.replace("\\", "/") for f in errs(found, "L-29")}
        self.assertEqual(bad, {"lm27/collect/x.py", "collect/Get-Y.ps1"}, found)

    def test_L29_banned_access_paths(self):
        self.t.write("collect/Get-Q.py", "URL = 'https://" + J(["graph.", "microsoft", ".com"]) + "/v1.0/me'\n")
        self.t.write("collect/Get-R.ps1", b"\xef\xbb\xbf" + ("$d = 'User Data\\Default\\" + J(["Indexed", "DB"]) + "'\r\n").encode())
        self.t.write("collect/Get-S.ps1", b"\xef\xbb\xbf" + ("$b = Get-Content -Encoding Byte $p\\box" + ".ost\r\n").encode())
        self.t.write("lm27/c.py", "def f(p):\n    return open(p + 'x" + ".pst', 'rb')\n")
        self.t.write("collect/Get-Ok.py", "SKIP_EXT = ('.ost', '.pst')\n")
        self.t.write("tests/collect/test_ok.py", "BAD = ('graph.' + 'microsoft' + '.com',)\n")
        found = self.t.repo(["L-29"])
        bad = {f.rel.replace("\\", "/") for f in errs(found, "L-29")}
        self.assertEqual(bad, {"collect/Get-Q.py", "collect/Get-R.ps1", "collect/Get-S.ps1", "lm27/c.py"}, found)

    def test_L30_stage_import_side_effects(self):
        self.t.write("lm27/bridge/stages/good.py", "X = 1\n\n\ndef fallback(items):\n    return [None for _ in items]\n")
        self.clean(self.t.repo(["L-30"]), "L-30")
        self.t.write("lm27/bridge/stages/bad.py", "open(__file__ + '.side', 'w').close()\n")
        found = self.t.repo(["L-30"])
        bad = {f.rel.replace("\\", "/") for f in errs(found, "L-30")}
        self.assertEqual(bad, {"lm27/bridge/stages/bad.py"}, found)
        self.assertFalse(os.path.exists(os.path.join(self.t.root, "lm27", "bridge", "stages", "bad.py.side")))


BOM = b"\xef\xbb\xbf"


def ps1(*lines):
    """수집기 .ps1 표본 바이트(UTF-8 BOM + CRLF)."""
    return BOM + ("\r\n".join(lines) + "\r\n").encode("utf-8")


class TestW0GateHardening(RuleCase):
    """W0 반증 점검에서 확정된 관문 구멍의 회귀 시험 — 지적마다 '구멍 표본 → 실패, 정상 표본 → 통과'."""

    def files_hit(self, found, rule):
        return {f.rel.replace("\\", "/") for f in errs(found, rule)}

    # ── L-08: Paths 메서드 뒤 조립 · bundle 밖 data\pcs 열기 ──
    def test_L08_paths_method_assembly_and_pcs_open(self):
        self.t.write("lm27/report/a.py", "def a(paths, pc_id, name):\n    return paths.pcs() / pc_id / 'seg' / 'mail' / name\n")
        self.t.write("lm27/report/b.py", "import os\ndef b(paths, pc_id):\n"
                                         "    return os.path.join(paths.pc_dir(pc_id), 'manifest.json')\n")
        self.t.write("lm27/report/c.py", "def c(paths, run_id):\n"
                                         "    return paths.derived() / 'collect' / run_id / 'stage_result_x.json'\n")
        self.t.write("lm27/report/d.py", "def d(paths, pc_id):\n"
                                         "    with open(paths.pcs() / pc_id / 'manifest.json', 'rb') as fh:\n"
                                         "        return fh.read()\n")
        self.t.write("lm27/ui/e.py", "def e(paths, pid):\n    return list(paths.pc_dir(pid).iterdir())\n")
        self.t.write("lm27/ui/f.py", "from lm27.util import fsx\ndef f(paths, pid):\n"
                                     "    return fsx.read_json(paths.pc_json(pid), {})\n")
        self.t.write("lm27/ui/g.py", "def g(self):\n    return self.paths.analysis('x').joinpath('time')\n")
        # 정상: bundle 7모듈 안의 data\pcs 조립·열기, 수 나눗셈, 경로 변환만, 메서드 결과를 그대로 쓰기
        self.t.write("lm27/bundle/manifest.py", "def m(paths, pid):\n    p = paths.pc_dir(pid) / 'manifest.json'\n"
                                                "    return open(p, 'rb').read(), list(paths.pcs().iterdir())\n")
        self.t.write("lm27/report/ok.py", "from pathlib import Path\nfrom lm27.util import fsx\n"
                                          "def ok(paths, stats, total, run_id):\n"
                                          "    a = stats.data() / total\n    b = Path(paths.data())\n"
                                          "    c = fsx.read_json(paths.analysis_current(), None)\n"
                                          "    return a, b, c, paths.stage_result_file(run_id, 'probe')\n")
        bad = self.files_hit(self.t.repo(["L-08"]), "L-08")
        self.assertEqual(bad, {"lm27/report/a.py", "lm27/report/b.py", "lm27/report/c.py", "lm27/report/d.py",
                               "lm27/ui/e.py", "lm27/ui/f.py", "lm27/ui/g.py"})
        found = self.t.repo(["L-08"])
        self.assertTrue(any("paths.derived()" in f.msg for f in errs(found)))
        # bundle 7모듈이라도 data\pcs 가 아닌 데이터 경로 조립은 paths.py 로
        self.t.write("lm27/bundle/loader.py", "def r(paths):\n    return paths.derived() / 'x.json'\n")
        self.assertIn("lm27/bundle/loader.py", self.files_hit(self.t.repo(["L-08"]), "L-08"))

    # ── L-28: 레지스트리 기본값 · '…Port = 9333' ──
    def test_L28_registry_default_and_identifier_ports(self):
        old, ui_old, ok = 9000 + 333, 8000 + 765, 9000 + 343
        keys = HC.parse_cfg_keys((ROOT / "docs" / "CONTRACT.md").read_text(encoding="utf-8"))
        reg = registry_obj(keys)
        reg["keys"]["bridge.edge.port"].update(default=ok, type="int", range={"min": 1024, "max": 65535})
        self.t.write("config/settings_registry.json", json.dumps(reg) + "\n")
        self.t.write("collect/Probe-Ok.ps1", ps1("$cdpPort = " + str(ok), "$n = 'report " + str(ui_old) + " rows'"))
        self.t.write("web/common/ok.js", "const cdpPort = " + str(ok) + ";\n")
        self.clean(self.t.repo(["L-28"]), "L-28")                 # 범위 1024~65535 는 옛 포트를 품어도 실패가 아니다
        reg["keys"]["bridge.edge.port"]["default"] = old
        self.t.write("config/settings_registry.json", json.dumps(reg) + "\n")
        self.t.write("collect/Probe-Port.ps1", ps1("$cdpPort = " + str(old), "$uiPort=" + str(ui_old)))
        self.t.write("web/common/probe.js", "const cdpPort = " + str(old) + ";\nconst p2 = {port: " + str(ui_old + 1) + "};\n")
        found = self.t.repo(["L-28"])
        self.assertEqual(self.files_hit(found, "L-28"),
                         {"config/settings_registry.json", "collect/Probe-Port.ps1", "web/common/probe.js"})
        self.assertEqual(len([f for f in errs(found, "L-28") if f.rel.endswith("Probe-Port.ps1")]), 2)
        self.assertTrue(any("bridge.edge.port" in f.msg for f in errs(found, "L-28")))

    # ── L-05: CR-04 에이전트 진입 원본 ──
    def test_L05_agent_main_source(self):
        rel = "lm27/agent/main.py"
        bad_top = ('"""에이전트."""\nimport sys\n\nfrom lm27.agent.sampler import take_sample\n\n\n'
                   "def main(install_id):\n    return take_sample(install_id)\n\n\n"
                   "if __name__ == '__main__':\n    sys.exit(main(sys.argv[1]))\n")
        bad_rel = bad_top.replace("from lm27.agent.sampler import", "from .sampler import")
        bad_noguard = '"""에이전트."""\n\n\ndef main(install_id):\n    from lm27.agent import sampler\n    return sampler\n'
        bad_late = ('"""에이전트."""\nimport os\nimport sys\n\n\ndef main(install_id):\n    from lm27.agent import sampler\n'
                    "    return sampler.take_sample(install_id)\n\n\nif __name__ == '__main__':\n"
                    "    rc = main(sys.argv[1])\n    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))\n")
        good_lazy = ('"""에이전트."""\nimport os\nimport sys\n\n\ndef main(install_id):\n'
                     "    from lm27.agent import sampler\n    return sampler.take_sample(install_id)\n\n\n"
                     "if __name__ == '__main__':\n    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))\n"
                     "    sys.exit(main(sys.argv[1]))\n")
        good_top = ('"""에이전트."""\nimport os\nimport sys\n\nsys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))\n'
                    "from lm27.agent.sampler import take_sample  # noqa: E402\n\n\ndef main(install_id):\n"
                    "    return take_sample(install_id)\n\n\nif __name__ == '__main__':\n    sys.exit(main(sys.argv[1]))\n")
        for body in (bad_top, bad_rel, bad_noguard, bad_late):
            self.t.write(rel, body)
            self.hit(self.t.file(rel, ["L-05"]), "L-05")
        for body in (good_lazy, good_top):
            self.t.write(rel, body)
            self.clean(self.t.file(rel, ["L-05"]), "L-05")
        # 같은 내용이 패키지 안 다른 모듈이면 진입 규칙을 적용하지 않는다
        self.t.write("lm27/agent/sampler.py", bad_top)
        self.clean(self.t.file("lm27/agent/sampler.py", ["L-05"]), "L-05")

    # ── L-09: 수집기 PS 쓰기는 대상 무관 실패 ──
    def test_L09_collector_writes_fail_closed(self):
        lad = "$env:LOCALAPPDATA\\LoadMonitor27"
        bad = {
            "two_line_var": ("$p = Join-Path $env:LOCALAPPDATA 'LoadMonitor27\\agent\\raw.json'",
                             "$body | Out-File -FilePath $p -Encoding utf8"),
            "dotnet": ('[IO.File]::WriteAllText("' + lad + '\\raw2.txt", $subject)',),
            "tee": ('$subject | Tee-Object -FilePath "' + lad + '\\tee.txt"',),
            "transcript": ('Start-Transcript -Path "$env:TEMP\\lm27_trace.txt" | Out-Null',),
            "temp_set": ('$subject | Set-Content "$env:TEMP\\lm27_dump.txt"',),
            "redirect": ('$subject > "$env:TEMP\\x.txt"',),
            "append_redirect": ("$subject >> $log",),
            "streamwriter": ("$w = New-Object 'System.IO.StreamWriter' $p",),
            "newitem": ("New-Item -ItemType 'File' -Path $p -Value $raw | Out-Null",),
            "filestream_mode": ("$fs = [IO.File]::Open($p, [IO.FileMode]::Create)",),
            "outdir_default": ("param([string]$OutDir = $env:TEMP)", "$x | Out-File (Join-Path $OutDir 'a.json')"),
            "here_csharp_write": ("Add-Type @'", "public static class W { public static void F(string p, string s) {",
                                  "  System.IO.File.WriteAllText(p, s); } }", "'@"),
            "at_string_not_heredoc": ("$m = 'a@'", "$x | Out-File $p"),
        }
        for name, lines in bad.items():
            rel = f"collect/Get-Zz{name.replace('_', '')}.ps1"
            self.t.write(rel, ps1(*lines))
            with self.subTest(case=name):
                self.hit(self.t.file(rel, ["L-09"]), "L-09")
        good = {
            "stdout_only": ("$rows | ConvertTo-Json -Compress", "Write-Output '{\"_cursor\": {}}'"),
            "null_redirects": ("& git log 2>$null", "& cmd /c ver *>$null", "$x = & where.exe py 2>&1",
                               "Get-Thing > $null"),
            "strings_and_comments": ('Write-Output "a > b"  # Out-File 은 주석', "$s = 'Set-Content 는 문자열'",
                                     "$y = 1 <# > 블록 주석 #> + 2"),
            "here_csharp_compare": ("Add-Type @'", "public static class C { public static bool F(int a) { return a > 1; } }",
                                    "'@"),
            "tee_variable": ("$rows | Tee-Object -Variable keep | Out-Null",),
            "outdir_injection": ("param([string]$OutDir = '')", "if ($OutDir) {",
                                 "  $dst = Join-Path $OutDir 'events.json'", "  $rows | Out-File -FilePath $dst", "}"),
            "read_open": ("$fs = [IO.File]::Open($p, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::ReadWrite)",),
        }
        for name, lines in good.items():
            rel = f"collect/Get-Ok{name.replace('_', '')}.ps1"
            self.t.write(rel, ps1(*lines))
            with self.subTest(case=name):
                self.clean(self.t.file(rel, ["L-09"]), "L-09")
        # 운영 파일: 허용 이름이 변수로 대입돼 쓰여도 통과, 다른 대상은 실패
        self.t.write("collect/agent/agent.ps1", ps1("$hb = Join-Path $AgentDir 'heartbeat.json'",
                                                    "$j | Set-Content -Path $hb -Encoding utf8",
                                                    "$lg = Join-Path $AgentDir 'logs'", "$line | Add-Content (Join-Path $lg 'a.log')"))
        self.clean(self.t.file("collect/agent/agent.ps1", ["L-09"]), "L-09")
        self.t.write("collect/agent/harvest.ps1", ps1("$raw | Out-File (Join-Path $env:TEMP 'dump.txt')"))
        self.hit(self.t.file("collect/agent/harvest.ps1", ["L-09"]), "L-09")
        self.t.write("collect/agent/Register-Agent.ps1", ps1("$tmp = Join-Path $env:TEMP \"lm27_task_$InstallId.xml\"",
                                                             "$xml | Set-Content -Path $tmp -Encoding Unicode"))
        self.clean(self.t.file("collect/agent/Register-Agent.ps1", ["L-09"]), "L-09")

    # ── L-07: 쓰기 판정 fail-closed + open 이 아닌 쓰기 API ──
    def test_L07_variable_modes_and_other_write_apis(self):
        bad = {
            "mode_var": 'def f(p, raw):\n    m = "w"\n    with open(p, m, encoding="utf-8") as fh:\n        fh.write(raw)\n',
            "mode_ifexp": 'def f(p, raw, a):\n    with open(p, "a" if a else "w") as fh:\n        fh.write(raw)\n',
            "mode_param": 'def f(p, mode):\n    return open(p, mode)\n',
            "os_open_var": 'import os\ndef f(p, flags):\n    return os.open(p, flags)\n',
            "log_handler": 'import logging\nlog = logging.getLogger("x")\nlog.addHandler(logging.FileHandler("trace.log"))\n',
            "rot_handler": 'from logging.handlers import RotatingFileHandler\nH = RotatingFileHandler("a.log")\n',
            "basic_config": 'import logging\nlogging.basicConfig(filename="a.log")\n',
            "named_temp": 'import tempfile\ndef f(raw):\n    t = tempfile.NamedTemporaryFile("w", delete=False)\n    t.write(raw)\n',
            "mkstemp": 'import os\nimport tempfile\ndef f(raw):\n    fd, _p = tempfile.mkstemp()\n    os.write(fd, raw)\n',
            "sqlite": 'import sqlite3\ndef f(p):\n    return sqlite3.connect(p)\n',
            "shutil_copy": 'import shutil\ndef f(a, b):\n    shutil.copyfile(a, b)\n',
            "shutil_move": 'import shutil\ndef f(a, b):\n    shutil.move(a, b)\n',
            "zip_write": 'import zipfile\ndef f(p):\n    return zipfile.ZipFile(p, "w")\n',
            "shelve": 'import shelve\ndef f(p):\n    return shelve.open(p)\n',
            "fileio": 'import io\ndef f(p):\n    return io.FileIO(p, "w")\n',
        }
        for name, body in bad.items():
            rel = f"lm27/collect/zz_{name}.py"
            self.t.write(rel, body)
            with self.subTest(case=name):
                self.hit(self.t.file(rel, ["L-07"]), "L-07")
        good = {
            "read_modes": 'import gzip\nimport os\ndef f(p):\n    a = open(p)\n    b = open(p, "rb")\n'
                          '    c = gzip.open(p, mode="rt")\n    d = os.open(p, os.O_RDONLY | os.O_BINARY)\n    return a, b, c, d\n',
            "same_name_methods": 'import webbrowser\ndef f(sess, url, role):\n    webbrowser.open(url)\n'
                                 '    return sess.open(role), sess.open("owa"), sess.open(role="bridge")\n',
            "path_read": 'from pathlib import Path\ndef f(p):\n    with Path(p).open("r", encoding="utf-8") as fh:\n'
                         '        return fh.read()\n',
            "sqlite_ro": 'import sqlite3\ndef f(p):\n    a = sqlite3.connect(":memory:")\n'
                         '    b = sqlite3.connect(f"file:{p}?mode=ro", uri=True)\n    return a, b\n',
            "zip_mem": 'import io\nimport zipfile\ndef f():\n    bio = io.BytesIO()\n    with zipfile.ZipFile(bio, "w") as z:\n'
                       '        z.writestr("a", "b")\n    return bio.getvalue(), zipfile.ZipFile("x.zip")\n',
            "dict_copy": 'def f(d, xs):\n    return d.copy(), xs.copy()\n',
        }
        for name, body in good.items():
            rel = f"lm27/collect/zz_{name}.py"
            self.t.write(rel, body)
            with self.subTest(case=name):
                self.clean(self.t.file(rel, ["L-07"]), "L-07")
        self.t.write("lm27/util/fsx.py", bad["mode_var"] + bad["named_temp"])
        self.clean(self.t.file("lm27/util/fsx.py", ["L-07"]), "L-07")

    # ── L-11: 봉인 행 복제·변경 · store 경로 직접 사용 ──
    def test_L11_sealed_row_bypass(self):
        bad = {
            "replace": "import dataclasses\ndef f(row, raw):\n    return dataclasses.replace(row, data={'title': raw})\n",
            "replace_from": "from dataclasses import replace\ndef f(rec_row, raw):\n    return replace(rec_row, data={})\n",
            "copy": "import copy\ndef f(res):\n    return copy.copy(res.row)\n",
            "deepcopy": "import copy\ndef f(row):\n    return copy.deepcopy(row)\n",
            "mutate": "def f(row, raw):\n    row.data['subject'] = raw\n",
            "mutate_update": "def f(row, raw):\n    row.data.update(subject=raw)\n",
            "setattr": "def f(row, raw):\n    object.__setattr__(row, 'data', {'subject': raw})\n",
            "new": "from lm27.privacy.records import SanitizedRow\ndef f():\n    return object.__new__(SanitizedRow)\n",
            "store_dir": "from lm27.util import fsx\ndef f(paths, pc_id, raw):\n"
                         "    fsx.append_line(paths.store_dir(pc_id) / 'evidence' / 'raw.jsonl', raw)\n",
            "raw_cursor": "def f(paths, pc_id):\n    return paths.raw_cursor(pc_id)\n",
            "audit": "def f(paths, d):\n    return paths.privacy_audit_file(d)\n",
        }
        for name, body in bad.items():
            rel = f"lm27/collect/zz_{name}.py"
            self.t.write(rel, body)
            with self.subTest(case=name):
                self.hit(self.t.file(rel, ["L-11"]), "L-11")
        good = {
            "plural_rows": "import copy\ndef f(rows, cfg):\n    return copy.deepcopy(rows), copy.copy(cfg)\n",
            "read_data": "def f(row):\n    return dict(row.data), row.data.get('kind')\n",
            "other_obj": "def f(item, raw):\n    item.data['x'] = raw\n",
        }
        for name, body in good.items():
            rel = f"lm27/collect/zz_{name}.py"
            self.t.write(rel, body)
            with self.subTest(case=name):
                self.clean(self.t.file(rel, ["L-11"]), "L-11")
        # 봉인 행이 없는 분석 층·store·records 자신은 대상 밖
        for rel in ("lm27/time/evidence.py", "lm27/privacy/records.py"):
            self.t.write(rel, bad["replace"] + bad["mutate"])
            self.clean(self.t.file(rel, ["L-11"]), "L-11")
        self.t.write("lm27/store/writer.py", bad["store_dir"])
        self.clean(self.t.file("lm27/store/writer.py", ["L-11"]), "L-11")

    # ── L-29: 간접 OST/PST 열기 · 자격 증명 · 브라우저 내부 DB ──
    def test_L29_indirect_ost_and_credentials(self):
        ost, pst = "." + "ost", "." + "pst"
        cred = J(["Cred", "ReadW"])
        unprotect = J(["CryptUn", "protectData"])
        bad_py = {
            "glob_read": f"from pathlib import Path\ndef f(d):\n    for p in Path(d).glob('*{ost}'):\n        return p.read_bytes()\n",
            "suffix_default": f"import os\ndef f(d, ext='{pst}'):\n    for n in os.listdir(d):\n"
                              "        if n.endswith(ext):\n            return open(os.path.join(d, n), 'rb').read()\n",
            "cookies_db": "import sqlite3\ndef f(prof):\n    return sqlite3.connect(prof + '/Default/" + J(["Net", "work/Coo", "kies"])
                          + "?mode=ro', uri=True)\n",
            "login_data": "import shutil\ndef f(prof, dst):\n    shutil.copyfile(prof + '/Default/" + J(["Login", " Data"]) + "', dst)\n",
            "cred_read": f"import ctypes\ndef f(t):\n    return ctypes.windll.advapi32.{cred}(t, 1, 0, None)\n",
            "dpapi": f"import ctypes\ndef f(b):\n    return ctypes.windll.crypt32.{unprotect}(b, None, None, None, None, 0, None)\n",
        }
        for name, body in bad_py.items():
            rel = f"collect/zz_{name}.py"
            self.t.write(rel, body)
            with self.subTest(case=name):
                self.hit(self.t.file(rel, ["L-29"]), "L-29")
        bad_ps = {
            "ost_pipeline": (f"$f = Get-ChildItem \"$env:LOCALAPPDATA\\Microsoft\\Outlook\" -Filter *{ost} | Select-Object -First 1",
                             "$s = [IO.File]::OpenRead($f.FullName)"),
            "cred_cli": ("$c = " + J(["cmd", "key"]) + " /list",),
            "vault": ("$v = New-Object Windows.Security.Credentials." + J(["Password", "Vault"]), "$all = $v.RetrieveAll()"),
            "cookies_copy": ("Copy-Item \"$env:LOCALAPPDATA\\Microsoft\\Edge\\User Data\\Default\\" + J(["Net", "work\\Coo", "kies"])
                             + "\" $env:TEMP",),
        }
        for name, lines in bad_ps.items():
            rel = f"collect/Get-Zz{name.replace('_', '')}.ps1"
            self.t.write(rel, ps1(*lines))
            with self.subTest(case=name):
                self.hit(self.t.file(rel, ["L-29"]), "L-29")
        good_py = {
            "skip_tuple": f"import os\nSKIP_EXT = ('{ost}', '{pst}')\ndef f(d):\n    for n in os.listdir(d):\n"
                          "        if not n.lower().endswith(SKIP_EXT):\n            return open(os.path.join(d, n), 'rb')\n",
            "exclude_key": f"CFG = {{'excludeExt': '{ost}'}}\n\ndef f(p):\n    return open(p, 'rb')\n",
            "count_only": f"from pathlib import Path\ndef f(d):\n    return len(list(Path(d).glob('*{ost}')))\n",
            "profile_traces": "TRACES = ('User Data', 'Local State', 'Cookies')\n",
        }
        for name, body in good_py.items():
            rel = f"collect/zz_{name}.py"
            self.t.write(rel, body)
            with self.subTest(case=name):
                self.clean(self.t.file(rel, ["L-29"]), "L-29")
        self.t.write("collect/Get-OkSkip.ps1", ps1(f"$files = Get-ChildItem $d -File -Exclude *{ost},*{pst}",
                                                   "$b = [IO.File]::ReadAllBytes($files[0].FullName)"))
        self.clean(self.t.file("collect/Get-OkSkip.ps1", ["L-29"]), "L-29")

    # ── L-21·L-26: 확장자가 아니라 내용으로 텍스트 판정 ──
    def test_L21_L26_any_text_extension(self):
        word = WORDS[1]
        ip = ".".join(["192", "168", "7", "21"])
        mail = "kim" + "@" + "realcorp" + ".co.kr"
        line = f"{word},{ip},{mail}\n"
        files = {"tests/fixtures/wp99/sample.csv": line.encode("utf-8"),
                 "tests/fixtures/wp99/task.xml": f"<T><A>{word}</A><H>{ip}</H><M>{mail}</M></T>\n".encode(),
                 "tests/fixtures/wp99/mail.eml": f"From: {word} <{mail}>\nX-Host: {ip}\n".encode(),
                 "tests/fixtures/wp99/helper.psm1": BOM + f"$h = '{ip}'; $o = '{word}'; $m = '{mail}'\r\n".encode(),
                 "tests/fixtures/wp99/notes.cmd": f"@echo off\r\nrem {word} {ip} {mail}\r\n".encode("cp949"),
                 "tests/fixtures/wp99/mru.reg": "\ufeff".encode("utf-16-le") + line.encode("utf-16-le"),
                 "tests/fixtures/wp99/NOEXT": line.encode("utf-8"),
                 "tests/fixtures/wp99/rows.jsonl.gz": gzip_bytes(line.encode("utf-8")),
                 "tests/fixtures/wp99/escaped.json": (json.dumps({"o": word.upper() + "한"}) + "\n").encode("utf-8")}
        for rel, data in files.items():
            self.t.write(rel, data)
        found = self.t.repo(["L-21", "L-26"])
        for rel in files:
            with self.subTest(rel=rel):
                rules = {f.rule for f in errs(found) if f.rel.replace("\\", "/") == rel}
                want = {"L-26"} if rel.endswith("escaped.json") else {"L-21", "L-26"}
                self.assertEqual(rules, want)
        for f in found:
            self.assertNotIn(word, str(f).lower(), "금지어 낱말을 출력하면 안 된다")
        # 훅(파일) 모드도 같은 판정
        self.hit(self.t.file("tests/fixtures/wp99/sample.csv", ["L-26"]), "L-26")
        # 바이너리는 건너뛴다(NUL), 깨끗한 csv 는 통과
        self.t.write("tests/fixtures/wp99/blob.bin", b"\x00\x01" + line.encode("utf-8"))
        self.t.write("tests/fixtures/wp99/clean.csv", "a,b\nhong@example.com,1\n")
        found = self.t.repo(["L-21", "L-26"])
        rels = {f.rel.replace("\\", "/") for f in errs(found)}
        self.assertNotIn("tests/fixtures/wp99/blob.bin", rels)
        self.assertNotIn("tests/fixtures/wp99/clean.csv", rels)


def gzip_bytes(raw):
    import gzip
    import io
    bio = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=bio, mtime=0) as gz:
        gz.write(raw)
    return bio.getvalue()


class TestContractParsing(unittest.TestCase):
    """사본 상수(FALLBACK_*)가 계약 표와 같은지 — 계약이 바뀌면 여기서 먼저 드러난다."""

    @classmethod
    def setUpClass(cls):
        cls.c = (ROOT / "docs" / "CONTRACT.md").read_text(encoding="utf-8")

    def test_path_ids_kinds_domains(self):
        self.assertEqual(HC.parse_path_ids(self.c), set(HC.FALLBACK_PATH_IDS))
        self.assertEqual(HC.parse_kinds(self.c), set(HC.FALLBACK_KINDS))
        self.assertEqual(HC.parse_domains(self.c), HC.FALLBACK_DOMAINS)

    def test_reason_codes(self):
        reg, dep = HC.parse_rcodes(self.c)
        self.assertIn("R-COMGAP", reg)
        self.assertIn("R-BUNDLE-LONGPATH", reg)
        self.assertEqual(dep, {J(["R", "-SAMPLER-CLM"]), J(["R", "-WEB-BLOCK"])})

    def test_rule_tables(self):
        self.assertEqual(len(HC.ALL_RULES), 30)
        self.assertEqual(set(HC.RULE_TITLES), set(HC.ALL_RULES))
        covered = set(HC.FILE_RULES) | set(HC.REPO_RULES)
        self.assertEqual(covered, set(HC.ALL_RULES), "규칙마다 구현이 하나 이상")
        self.assertTrue(set(HC.HOOK_RULES) <= set(HC.FILE_RULES))
        # 파일 하나만 볼 수 있는 패턴 규칙은 check_file(rules=…) 로도 돈다(자기 검사·편집 즉시 검사용)
        per_file = set(HC.FILE_RULES) | set(HC._FILE_PART_IN_REPO)
        self.assertTrue({"L-08", "L-13", "L-14", "L-15", "L-21", "L-22", "L-25", "L-28", "L-29"} <= per_file)


if __name__ == "__main__":
    unittest.main()
