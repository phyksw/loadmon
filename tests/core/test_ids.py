# -*- coding: utf-8 -*-
"""WP-00 lm27.bundle.ids — pc_id · install_id · kind 추정(계약 §2.6·§4.1, TAB §1.2·§1.5) 시험.

실기계 값은 읽기만 한다(MachineGuid 는 해시해 비교만 하고 출력·저장하지 않는다). 그 밖은 가짜 조회(probe)로."""
import ast
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

from lm27 import LM27_VERSION
from lm27.bundle import ids
from lm27.paths import Paths
from lm27.util import fsx

TREE = Path(__file__).resolve().parents[2]
GUID = "3F2504E0-4F89-11D3-9A0C-0305E82C3301"           # 합성 GUID(문서 예시값)


class FakeProbe:
    def __init__(self, guid=GUID, host="DESK-0001", ctime="1700000000", model="Example Desktop 5000",
                 battery=False, rdp=False, offset=540, wtz="Korea Standard Time", chassis=()):
        self.v = {"guid": guid, "host": host, "ctime": ctime, "model": model, "battery": battery, "rdp": rdp,
                  "offset": offset, "wtz": wtz, "chassis": chassis}
        self.calls = 0

    def machine_guid(self):
        self.calls += 1
        return self.v["guid"]

    def computer_name(self):
        return self.v["host"]

    def profile_ctime(self):
        return self.v["ctime"]

    def offset_min(self):
        return self.v["offset"]

    def windows_tz(self):
        return self.v["wtz"]

    def model(self):
        return self.v["model"]

    def battery(self):
        return self.v["battery"]

    def rdp_session(self):
        return self.v["rdp"]

    def chassis(self):
        return self.v["chassis"]


class IdsCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="lm27t_wp00_ids_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.paths = Paths(os.path.join(self.tmp, "root"), lad=os.path.join(self.tmp, "lad"))
        self._saved = ids._process_install_id
        ids._process_install_id = None
        self.addCleanup(setattr, ids, "_process_install_id", self._saved)

    def write_agent_json(self, obj):
        fsx.atomic_write(self.paths.agent_json(), fsx.canon_bytes(obj))


class PcIdTest(IdsCase):
    def test_formula_and_format(self):
        ident = ids.identify_pc(self.paths, probe=FakeProbe())
        want = "pc_" + hashlib.sha256(("LM27.pc|" + GUID.lower()).encode()).hexdigest()[:16]
        self.assertEqual(ident.pc_id, want)
        self.assertRegex(ident.pc_id, r"^pcx?_[0-9a-f]{16}$")
        self.assertEqual(ident.id_source, "machineguid")
        self.assertEqual(ident.reasons, ())

    def test_case_insensitive_and_stable(self):
        a = ids.identify_pc(self.paths, probe=FakeProbe(guid=GUID.lower()))
        b = ids.identify_pc(self.paths, probe=FakeProbe(guid=GUID.upper()))
        self.assertEqual(a.pc_id, b.pc_id)
        self.assertEqual(ids.pc_id_from_guid(GUID), a.pc_id)
        self.assertNotEqual(ids.pc_id_from_guid(str(uuid.UUID(int=1))), a.pc_id)

    def test_fallback_when_guid_missing(self):
        for missing in (None, "", "   "):
            with self.subTest(missing=missing):
                ident = ids.identify_pc(self.paths, probe=FakeProbe(guid=missing))
                want = "pcx_" + hashlib.sha256(b"LM27.pcx|DESK-0001|1700000000").hexdigest()[:16]
                self.assertEqual(ident.pc_id, want)
                self.assertEqual(ident.id_source, "fallback")
                self.assertEqual(ident.reasons, ("R-NOMACHGUID",))
                self.assertRegex(ident.pc_id, r"^pcx?_[0-9a-f]{16}$")

    def test_pure_helpers(self):
        self.assertRaises(ValueError, ids.pc_id_from_guid, "")
        self.assertRaises(ValueError, ids.pc_id_from_guid, None)
        self.assertTrue(ids.pc_id_fallback("", "").startswith("pcx_"))

    def test_raw_values_not_in_identity(self):
        ident = ids.identify_pc(self.paths, probe=FakeProbe(host="CPC-holder-ab12", model="Example Cloud PC"))
        blob = repr(ident).lower()
        for raw in (GUID.lower(), "cpc-holder-ab12", "example"):
            self.assertNotIn(raw, blob)


class InstallIdTest(IdsCase):
    def test_kept_from_agent_json(self):
        iid = uuid.uuid4().hex
        self.write_agent_json({"schema": "lm27.agent/1", "install_id": iid, "agent_ver": "0.0.9"})
        ident = ids.identify_pc(self.paths, probe=FakeProbe())
        self.assertEqual(ident.install_id, iid)
        self.assertEqual(ident.agent_ver, "0.0.9")
        self.assertEqual(ident.install_source, "agent_json")
        self.assertEqual(ids.identify_pc(self.paths, probe=FakeProbe()).install_id, iid)

    def test_new_id_stable_within_process(self):
        a = ids.identify_pc(self.paths, probe=FakeProbe())
        b = ids.identify_pc(self.paths, probe=FakeProbe())
        self.assertRegex(a.install_id, r"^[0-9a-f]{32}$")
        self.assertEqual(a.install_id, b.install_id)
        self.assertEqual(a.install_source, "new")
        self.assertEqual(a.agent_ver, LM27_VERSION)
        self.assertFalse(os.path.exists(self.paths.agent_json()))       # 저장은 에이전트 설치가 한다

    def test_bad_agent_json_ignored(self):
        self.write_agent_json({"install_id": "XYZ", "agent_ver": 3})
        ident = ids.identify_pc(self.paths, probe=FakeProbe())
        self.assertRegex(ident.install_id, r"^[0-9a-f]{32}$")
        self.assertNotEqual(ident.install_id, "XYZ")
        self.assertEqual(ident.agent_ver, LM27_VERSION)


class KindTest(IdsCase):
    def test_kind_rules(self):
        cases = [
            ({"model": "Example Cloud PC Enterprise"}, "cloud"),
            ({"host": "CPC-user-0a1b"}, "cloud"),
            ({"model": "Virtual Machine", "rdp": True}, "vdi"),
            ({"model": "VMware7,1", "rdp": True}, "vdi"),
            ({"model": "Virtual Machine", "rdp": False}, "desktop"),
            ({"battery": True}, "laptop"),
            ({"chassis": (10,)}, "laptop"),
            ({"battery": None}, "desktop"),
            ({}, "desktop"),
        ]
        for kw, want in cases:
            with self.subTest(kw=kw):
                ident = ids.identify_pc(self.paths, probe=FakeProbe(**kw))
                self.assertEqual(ident.kind_guess, want)
                self.assertIn(ident.kind_guess, ids.KINDS)
        ev = ids.identify_pc(self.paths, probe=FakeProbe(battery=True)).kind_evidence
        self.assertEqual(set(ev), {"battery", "chassis", "model_virtual", "model_cloud", "rdp_session",
                                   "host_prefix_cloud"})

    def test_tz(self):
        ident = ids.identify_pc(self.paths, probe=FakeProbe(offset=-300, wtz="Eastern Standard Time"))
        self.assertEqual(ident.tz, {"utc_offset_min": -300, "windows_tz": "Eastern Standard Time"})


class RealMachineTest(IdsCase):
    """이 PC 에서 실제 조회 — 값은 출력하지 않고 형식·재현성만 본다."""

    def test_same_machine_same_id(self):
        a = ids.identify_pc(self.paths)
        b = ids.identify_pc(self.paths)
        self.assertRegex(a.pc_id, r"^pcx?_[0-9a-f]{16}$")
        self.assertEqual(a.pc_id, b.pc_id)
        self.assertEqual(a.install_id, b.install_id)
        self.assertIn(a.kind_guess, ids.KINDS)
        self.assertIsInstance(a.tz["utc_offset_min"], int)
        self.assertTrue(-14 * 60 <= a.tz["utc_offset_min"] <= 14 * 60)
        self.assertIn(a.id_source, ("machineguid", "fallback"))


class BinCopyTest(unittest.TestCase):
    """에이전트 bin 사본(계약 §1.3 · X-305): 사본 안 모듈과 표준 라이브러리만으로 import·실행된다."""

    COPY = ["lm27/__init__.py", "lm27/paths.py", "lm27/bundle/__init__.py", "lm27/bundle/ids.py"]

    def test_imports_are_stdlib_or_bin_modules(self):
        src = fsx.read_bytes(ids.__file__).decode("utf-8")
        allowed_lm27 = {"lm27", "lm27.util", "lm27.paths"}
        for n in ast.walk(ast.parse(src)):
            names = []
            if isinstance(n, ast.Import):
                names = [a.name for a in n.names]
            elif isinstance(n, ast.ImportFrom):
                names = [n.module or ""]
            for name in names:
                top = name.split(".")[0]
                if top == "lm27":
                    self.assertTrue(name in allowed_lm27 or name.startswith("lm27.util."), name)
                else:
                    self.assertIn(top, sys.stdlib_module_names, name)

    def test_import_and_identify_in_minimal_copy(self):
        tmp = tempfile.mkdtemp(prefix="lm27t_wp00_bin_")
        self.addCleanup(shutil.rmtree, tmp, True)
        files = list(self.COPY) + [p.relative_to(TREE).as_posix() for p in (TREE / "lm27" / "util").glob("*.py")]
        for rel in files:
            dst = os.path.join(tmp, *rel.split("/"))
            fsx.atomic_write(dst, fsx.read_bytes(TREE / rel))
        code = ("import sys;sys.path.insert(0, sys.argv[1]);import lm27.bundle.ids as m;"
                "i=m.identify_pc();print(i.pc_id, len(i.install_id), m.__file__.startswith(sys.argv[1]))")
        env = dict(os.environ, LOCALAPPDATA=os.path.join(tmp, "lad"))
        cp = subprocess.run([sys.executable, "-X", "utf8", "-I", "-B", "-c", code, tmp], capture_output=True,
                            env=env, timeout=120, creationflags=0x08000000)
        self.assertEqual(cp.returncode, 0, cp.stderr.decode("utf-8", "replace")[-400:])
        pc_id, n, inside = cp.stdout.decode().split()
        self.assertRegex(pc_id, r"^pcx?_[0-9a-f]{16}$")
        self.assertEqual((n, inside), ("32", "True"))
        self.assertEqual(list(Path(tmp).rglob("__pycache__")), [])


if __name__ == "__main__":
    unittest.main()
