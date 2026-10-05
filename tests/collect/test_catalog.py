# -*- coding: utf-8 -*-
"""WP-14 프로그램 카탈로그 시험(계약 §2.8 · X-245, CP §6) — 판정 순서·범주 9종·app_id 형식·미지 프로그램·솔버·휴리스틱,
에이전트 bin 사본 조건(표준 라이브러리만)과 설정 레지스트리 기본값 일치."""
import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from lm27 import catalog as C

TREE = Path(__file__).resolve().parents[2]
REG = TREE / "config" / "settings_registry.json"
CREATE_NO_WINDOW = 0x08000000


class ClassifyTest(unittest.TestCase):
    def test_prefix_with_version_suffix(self):
        it = C.classify("ANSYS231.exe")
        self.assertEqual(it.app_id, "ansys_mechanical_apdl")
        self.assertEqual(it.cat, "해석")
        self.assertEqual(it.kind, "상용")
        self.assertEqual(it.app_class, "sim")

    def test_longest_prefix_wins(self):
        self.assertEqual(C.classify("ansysedt.exe").app_id, "ansys_electronics_desktop")
        self.assertEqual(C.classify("ansyswbu.exe").app_id, "ansys_workbench")
        self.assertEqual(C.classify("cfx5solve.exe").app_id, "ansys_cfx")

    def test_exclude_first(self):
        for p in ("ansysli_client.exe", "lmgrd", "svchost.exe", "ctfmon.exe", ""):
            self.assertTrue(C.is_noise(p), p)
            self.assertIsNone(C.classify(p), p)
            self.assertIsNone(C.app_id_for(p), p)

    def test_exact_vs_prefix(self):
        self.assertEqual(C.classify("edge.exe").app_id, "solid_edge")      # Solid Edge(정확 일치)
        self.assertEqual(C.classify("msedge.exe").app_id, "edge")         # MS Edge
        self.assertEqual(C.classify("code.exe").app_id, "vscode")
        self.assertEqual(C.classify("codev.exe").app_id, "code_v")
        self.assertIsNone(C.classify("codexyz.exe"))                        # 'code' 는 정확 일치만
        self.assertEqual(C.classify("ads.exe").app_id, "keysight_ads")
        self.assertIsNone(C.classify("adsl_tool.exe"))

    def test_path_and_case_normalized(self):
        a = C.classify(r"C:\Program Files\Microsoft Office\root\Office16\EXCEL.EXE")
        self.assertEqual(a.app_id, "excel")
        self.assertEqual(C.exe_norm('"WINWORD.EXE"'), "winword")
        self.assertEqual(C.exe_name("WinWord"), "winword.exe")

    def test_extra_first_and_namespaced(self):
        extra = [{"match": "myfea", "name": "사내 해석기", "kind": "비상용", "cat": "해석", "vendor": "사내"},
                 {"match": "ansys", "name": "덮어쓰기", "cat": "SW개발"}, {"bad": 1}, "문자열"]
        it = C.classify("MyFea_v2.exe", extra)
        self.assertEqual(it.app_id, "x.myfea")
        self.assertEqual((it.cat, it.kind, it.app_class), ("해석", "비상용", "sim"))
        self.assertEqual(C.classify("ansys231.exe", extra).app_id, "x.ansys")     # 설정이 카탈로그보다 먼저
        self.assertEqual(C.classify("ansys231.exe", extra).cat, "SW")
        self.assertEqual(C.cat_of("x.myfea", extra), "해석")
        self.assertEqual(C.cat_of("x.myfea"), "")
        self.assertEqual(C.app_class_of("x.myfea", extra), "sim")
        self.assertTrue(C.APP_ID_RX.match(it.app_id))

    def test_extra_korean_match_gets_ascii_id_or_skipped(self):
        it = C.classify("설계툴.exe", [{"match": "설계툴", "id": "design_tool", "cat": "CAD"}])
        self.assertEqual(it.app_id, "x.design_tool")
        self.assertIsNone(C.classify("설계툴.exe", [{"match": "설계툴", "cat": "CAD"}]))   # ASCII id 를 만들 수 없음


class UnknownTest(unittest.TestCase):
    def test_unknown_app_id_form(self):
        self.assertEqual(C.app_id_for("CadTool.exe"), "unknown:cadtool.exe")
        self.assertEqual(C.cat_of("unknown:cadtool.exe"), "")
        self.assertEqual(C.app_class_of("unknown:cadtool.exe"), "other")
        long = "a" * 90 + ".exe"
        aid = C.app_id_for(long)
        self.assertLessEqual(len(aid), 48)
        self.assertTrue(C.APP_ID_RX.match(aid), aid)
        ko = C.app_id_for("설계도구.exe")
        self.assertTrue(C.APP_ID_RX.match(ko), ko)
        self.assertTrue(ko.startswith("unknown:"))

    def test_synth_persona_apps_consistent(self):
        """WP-05 합성 페르소나 APPS 의 app_id·app_class 모양과 카탈로그가 같다(하네스와 실물이 어긋나지 않게)."""
        from tests.fixtures.synth.month import APPS
        for exe, app_id, app_class, _ext, _tail in APPS:
            self.assertEqual(C.app_id_for(exe), app_id, exe)
            if not app_id.startswith("unknown:"):
                self.assertEqual(C.app_class_of(app_id), app_class, exe)


class TableTest(unittest.TestCase):
    def test_categories_contract(self):
        self.assertEqual(C.CATEGORIES, ("CAD", "해석", "광학", "EDA", "FPGA", "SW", "계측", "사무", "소통"))
        self.assertEqual(len(C.APP_CLASSES), 18)
        self.assertIn("remote", C.APP_CLASSES)
        self.assertIn("meeting", C.APP_CLASSES)

    def test_every_entry_valid(self):
        seen = {}
        for names, app_id, disp, vendor, kind, cat, app_class, how in C._CATALOG:
            self.assertTrue(C.APP_ID_RX.match(app_id), app_id)
            self.assertNotIn(":", app_id)
            self.assertFalse(app_id.startswith(C.EXTRA_PREFIX))
            self.assertIn(cat, C.CATEGORIES + ("",), app_id)
            self.assertIn(app_class, C.APP_CLASSES, app_id)
            self.assertIn(kind, C.KINDS, app_id)
            self.assertIn(how, ("exact", "prefix"), app_id)
            self.assertTrue(names and all(n == n.lower() for n in names), app_id)
            prev = seen.setdefault(app_id, (disp, vendor, kind, cat, app_class))
            self.assertEqual(prev, (disp, vendor, kind, cat, app_class), f"같은 app_id 다른 정의: {app_id}")

    def test_cat_of_all_entries_nine_or_empty(self):
        for it in C.entries():
            self.assertEqual(C.cat_of(it.app_id), it.cat)
            self.assertEqual(C.app_class_of(it.app_id), it.app_class)
        cats = {it.cat for it in C.entries()} - {""}
        self.assertEqual(cats, set(C.CATEGORIES))

    def test_entries_sorted_deterministic(self):
        ids = [e.app_id for e in C.entries()]
        self.assertEqual(ids, sorted(ids))
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIsInstance(C.entries()[0].as_dict(), dict)

    def test_norm_cat_aliases(self):
        self.assertEqual(C.norm_cat("FPGA·펌웨어"), "FPGA")
        self.assertEqual(C.norm_cat("SW개발"), "SW")
        self.assertEqual(C.norm_cat("기타"), "")
        self.assertEqual(C.norm_cat("광학"), "광학")

    def test_version_constant(self):
        self.assertRegex(C.CATALOG_VERSION, r"^\d{4}\.\d{1,2}\.\d{1,3}$")


class SolverTest(unittest.TestCase):
    def test_solver_names_default(self):
        self.assertEqual(C.solver_names(), list(C.SOLVER_HINTS))
        self.assertNotIn("hypermesh", C.solver_names())                   # GUI 전용 제외

    def test_solver_set_and_exclude(self):
        self.assertTrue(C.is_solver("fluent.exe"))
        self.assertTrue(C.is_solver("FL_MPI.exe"))
        self.assertFalse(C.is_solver("ansysli_client.exe"))               # 상주 대리자(접두 'ansys' 지만 제외)
        self.assertFalse(C.is_solver("excel.exe"))
        cfg = {"pc.solverProcesses": ["fluent", "mysolver"], "pc.solverProcessesExclude": ["fluent"]}
        self.assertEqual(C.solver_set(cfg), frozenset({"mysolver"}))
        self.assertTrue(C.is_solver("MySolver64.exe", cfg))
        self.assertFalse(C.is_solver("fluent.exe", cfg))

    def test_registry_defaults_match_catalog(self):
        reg = json.loads(REG.read_bytes().decode("utf-8"))["keys"]
        self.assertEqual(reg["pc.solverProcesses"]["default"], list(C.SOLVER_HINTS))
        self.assertEqual(reg["pc.solverProcessesExclude"]["default"], list(C.SOLVER_EXCLUDE))
        for k in (C.KEY_EXTRA, C.KEY_SOLVERS, C.KEY_SOLVERS_EXCLUDE):
            self.assertEqual(reg[k]["owner"], "lm27.catalog", k)

    def test_reads_real_cfg_object(self):
        from lm27.config import load_config
        tmp = tempfile.mkdtemp(prefix="lm27t_cat_")
        try:
            cfg = load_config(registry_path=REG, config_path=os.path.join(tmp, "none.json"),
                              overrides={"pc.solverProcesses": ["abaqus"], "pc.programsExtra": [{"match": "myfea"}]})
            self.assertEqual(C.solver_set(cfg), frozenset({"abaqus"}))
            self.assertEqual(C.programs_extra(cfg)[0]["match"], "myfea")
            self.assertIn("pc.solverProcesses", cfg.used())
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertEqual(C.programs_extra(None), ())
        self.assertEqual(C.solver_set(None), C.solver_set({}))


class GuessTest(unittest.TestCase):
    def test_signer_vendor(self):
        g = C.guess_meta(signer="Ansys, Inc.")
        self.assertEqual(g, {"guess_cat": "해석", "guess_kind": "상용", "source": "signer", "vendor": "Ansys"})
        self.assertEqual(C.guess_meta(company="Dassault Systemes")["guess_cat"], "CAD")
        self.assertEqual(C.guess_meta(company="Dassault Systemes")["source"], "company")

    def test_microsoft_family(self):
        self.assertEqual(C.guess_meta(company="Microsoft Corporation", product="Microsoft Excel")["guess_cat"], "사무")
        self.assertEqual(C.guess_meta(signer="Microsoft Corporation", product="Microsoft Teams")["guess_cat"], "소통")
        os_ = C.guess_meta(signer="Microsoft Windows", product="Windows host process")
        self.assertEqual((os_["guess_cat"], os_["source"]), ("", "signer"))

    def test_word_boundary_and_free(self):
        self.assertEqual(C.guess_meta(company="Captcha Labs")["source"], "none")       # 'ptc' 부분 일치 금지
        self.assertEqual(C.guess_meta(company="Free Software Foundation")["guess_kind"], "비상용")
        self.assertEqual(C.guess_meta(), {"guess_cat": "", "guess_kind": "", "source": "none", "vendor": ""})

    def test_guess_values_closed(self):
        for args in ({"signer": "Cadence Design Systems"}, {"company": "Keysight Technologies"},
                     {"product": "Xilinx Vivado"}, {"desc": "JetBrains IDE"}):
            g = C.guess_meta(**args)
            self.assertIn(g["guess_cat"], C.CATEGORIES + ("",))
            self.assertIn(g["guess_kind"], C.KINDS + ("",))
            self.assertIn(g["source"], ("signer", "company", "product", "desc", "none"))


class AgentCopyTest(unittest.TestCase):
    """에이전트 bin 사본(계약 §1.3)에 들어가므로 표준 라이브러리만 import 하고, 사본 안에서 단독으로 import 된다."""

    def test_stdlib_only_imports(self):
        tree = ast.parse((TREE / "lm27" / "catalog.py").read_bytes().decode("utf-8"))
        mods = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                mods |= {a.name.split(".")[0] for a in n.names}
            elif isinstance(n, ast.ImportFrom):
                self.assertEqual(n.level, 0)
                mods.add((n.module or "").split(".")[0])
        self.assertTrue(mods <= set(sys.stdlib_module_names), mods - set(sys.stdlib_module_names))

    def test_import_in_isolated_copy(self):
        tmp = Path(tempfile.mkdtemp(prefix="lm27t_catbin_"))
        try:
            (tmp / "lm27").mkdir()
            shutil.copy2(TREE / "lm27" / "__init__.py", tmp / "lm27" / "__init__.py")
            shutil.copy2(TREE / "lm27" / "catalog.py", tmp / "lm27" / "catalog.py")
            code = ("import sys; sys.path.insert(0, sys.argv[1]); import lm27.catalog as c; "
                    "print(c.app_id_for('excel.exe'), c.cat_of('excel'), sorted(m for m in sys.modules if m.startswith('lm27')))")
            cp = subprocess.run([sys.executable, "-X", "utf8", "-I", "-B", "-c", code, str(tmp)], capture_output=True,
                                timeout=60, creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0, check=False)
            out = cp.stdout.decode("utf-8", "replace")
            self.assertEqual(cp.returncode, 0, cp.stderr.decode("utf-8", "replace"))
            self.assertIn("excel 사무", out)
            self.assertIn("['lm27', 'lm27.catalog']", out)
            self.assertFalse(list(tmp.rglob("__pycache__")))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_no_config_import_text(self):
        src = (TREE / "lm27" / "catalog.py").read_bytes().decode("utf-8")
        self.assertIsNone(re.search(r"^\s*(?:from|import)\s+lm27", src, re.M))


if __name__ == "__main__":
    unittest.main()
