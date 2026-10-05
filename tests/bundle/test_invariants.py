# -*- coding: utf-8 -*-
"""WP-12 불변식 — T-12(세그먼트 불변·다른 pc_id 폴더 바이트 불변) · TAB B06/CP-6(두 프로세스 동시 내보내기:
대기 후 진행·seq 중복 0·레코드 중복 0·PermissionError 0) · L-07/L-08(번들 모듈의 쓰기·data\\pcs 접근)."""
import subprocess
import sys
import unittest
from collections import Counter
from pathlib import Path

from lm27.bundle import export as ex
from lm27.bundle import loader
from lm27.bundle import manifest as mf
from lm27.bundle import merge as mg
from lm27.bundle import pcreg
from lm27.util import fsx
from tests.fixtures.wp12 import builders as B
from tests.fixtures.wp12 import fake_store as fs

TREE = Path(__file__).resolve().parents[2]
CREATE_NO_WINDOW = 0x08000000
CHILD = r"""
import sys
sys.path.insert(0, sys.argv[1])
from lm27.paths import Paths
from lm27.bundle.ids import PcIdentity
from lm27.bundle.lock import BundleLock
from lm27.bundle.export import export_agent_streams
from lm27.config import load_config
from tests.fixtures.wp12 import fake_store as fs
from tests.fixtures.wp12 import builders as B
root, lad, tag = sys.argv[2], sys.argv[3], sys.argv[4]
paths = Paths(root, lad=lad)
ident = B.ident(tag)
cfg = load_config(registry_path=B.REGISTRY, config_path=root + "\\no_config.json")
for i in range(int(sys.argv[5])):
    with BundleLock(paths, "export", 60):
        r = export_agent_streams(paths.pc_dir(ident.pc_id), ident, cfg, paths=paths, reader=fs.read_store_since)
print("ok", flush=True)
"""


class InvariantTest(B.BundleTestCase):
    def setUp(self):
        super().setUp()
        self.cfg = self.b.cfg()
        self.i1 = B.ident("PC1")
        self.d1 = pcreg.ensure_pc_dir(self.paths, self.i1, host="", anchor_since="2026-01-01T00:00:00Z",
                                      now="2026-09-01T00:00:00Z")

    def export(self, ident=None, **kw):
        ident = ident or self.i1
        return ex.export_agent_streams(self.paths.pc_dir(ident.pc_id), ident, self.cfg, paths=self.paths,
                                       reader=fs.read_store_since, **kw)

    def test_t12_segments_immutable_across_operations(self):
        fs.append_member(self.paths, self.i1.pc_id, "pc_session", "pc.sampler", "2026-09-01",
                         B.rows("pc_session", self.i1.pc_id, 10))
        fs.append_member(self.paths, self.i1.pc_id, "mail", "mail.com", "2026-09-01", B.rows("mail", self.i1.pc_id, 3))
        self.export(streams=["pc_session/pc.sampler"])
        segs0 = {p: p.read_bytes() for p in (self.d1 / "seg").rglob("*.jsonl.gz")}
        i2 = B.ident("PC2")
        pcreg.ensure_pc_dir(self.paths, i2, host="", now="2026-09-01T00:00:00Z")
        fs.append_member(self.paths, i2.pc_id, "pc_file", "pc.files", "2026-09-02", B.rows("pc_file", i2.pc_id, 4))
        self.export(i2)
        pc2 = self.b.snapshot(self.paths.pc_dir(i2.pc_id))
        for day in ("2026-09-02", "2026-09-03"):
            fs.append_member(self.paths, self.i1.pc_id, "pc_session", "pc.sampler", day,
                             B.rows("pc_session", self.i1.pc_id, 5, start=day + "T01:00:00Z"))
            self.export()
        ov = {"chat": {}, "msg": ["m" + "0" * 24]}
        mg.redact_rewrite_own(self.d1, overlay=ov)
        other = B.BundleRoot()
        self.addCleanup(other.remove)
        self.b.write_bundle_json()
        other.write_bundle_json()
        mg.merge_bundle(self.paths, other.paths.data())
        for p, data in segs0.items():
            self.assertEqual(p.read_bytes(), data, f"세그먼트 불변: {p.name}")
        self.assertEqual(self.b.snapshot(self.paths.pc_dir(i2.pc_id)), pc2, "다른 pc_id 폴더 바이트 불변")
        self.assertEqual(len(list(loader.iter_records(self.paths, "pc_session"))), 20)

    def _children(self, specs):
        procs = []
        for lad, tag, n in specs:
            procs.append(subprocess.Popen([sys.executable, "-X", "utf8", "-B", "-c", CHILD, str(TREE),
                                           str(self.b.root), str(lad), tag, str(n)],
                                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                          creationflags=CREATE_NO_WINDOW))
        outs = []
        for p in procs:
            o, e = p.communicate(timeout=300)
            outs.append((p.returncode, o.decode("utf-8", "replace"), e.decode("utf-8", "replace")))
        return outs

    def test_b06_cp6_two_processes_same_pc(self):
        total = 0
        for d in range(1, 6):
            rows = B.rows("pc_session", self.i1.pc_id, 40, start=f"2026-09-0{d}T00:00:00Z")
            fs.append_member(self.paths, self.i1.pc_id, "pc_session", "pc.sampler", f"2026-09-0{d}", rows)
            total += len(rows)
        outs = self._children([(self.b.lad, "PC1", 3), (self.b.lad, "PC1", 3)])
        for rc, out, err in outs:
            self.assertEqual((rc, out.strip()), (0, "ok"), err[-2000:])
            self.assertNotIn("PermissionError", err)
        m = mf.load_manifest(self.d1)
        seqs = Counter((s["kind"], s["seq"]) for s in m["segments"])
        self.assertTrue(all(v == 1 for v in seqs.values()), f"seq 중복 0: {seqs}")
        got = list(loader.iter_records(self.paths, "pc_session"))
        self.assertEqual(len(got), total)
        self.assertEqual(loader.load_report()["duplicates"], 0, "레코드 중복 0")

    def test_two_pcs_concurrently(self):
        i2 = B.ident("PC2")
        lad2 = self.b.root / "_lad2"
        from lm27.paths import Paths
        p2 = Paths(self.b.root, lad=lad2)
        pcreg.ensure_pc_dir(self.paths, i2, host="", anchor_since="2026-01-01T00:00:00Z", now="2026-09-01T00:00:00Z")
        fs.append_member(self.paths, self.i1.pc_id, "pc_file", "pc.files", "2026-09-01",
                         B.rows("pc_file", self.i1.pc_id, 30))
        fs.append_member(p2, i2.pc_id, "pc_file", "pc.files", "2026-09-01", B.rows("pc_file", i2.pc_id, 25))
        outs = self._children([(self.b.lad, "PC1", 2), (lad2, "PC2", 2)])
        for rc, out, err in outs:
            self.assertEqual((rc, out.strip()), (0, "ok"), err[-2000:])
        self.assertEqual(Counter(r["_pc"] for r in loader.iter_records(self.paths, "pc_file")),
                         Counter({self.i1.pc_id: 30, i2.pc_id: 25}))


class StaticGateTest(unittest.TestCase):
    def test_l07_l08_bundle_modules_clean(self):
        files = sorted(str(p) for p in (TREE / "lm27" / "bundle").glob("*.py"))
        cp = subprocess.run([sys.executable, "-X", "utf8", "-B", str(TREE / "tools" / "hook_check.py"), *files],
                            capture_output=True, timeout=300, creationflags=CREATE_NO_WINDOW)
        self.assertEqual(cp.returncode, 0, cp.stdout.decode("utf-8", "replace")[-3000:])
        cp = subprocess.run([sys.executable, "-X", "utf8", "-B", str(TREE / "tools" / "hook_check.py"), "--repo",
                             "L-08"], capture_output=True, timeout=300, creationflags=CREATE_NO_WINDOW)
        out = cp.stdout.decode("utf-8", "replace") + cp.stderr.decode("utf-8", "replace")
        mine = [ln for ln in out.splitlines() if "lm27\\bundle\\" in ln or "lm27/bundle/" in ln]
        self.assertEqual(mine, [])

    def test_b24_no_control_chars(self):
        """TAB B24 — 이 WP 의 소스 바이트에 0x00–0x08·0x0B·0x0C·0x0E–0x1F 없음(이전 판 BEL 결함)."""
        bad = bytes(list(range(0, 9)) + [0x0B, 0x0C] + list(range(0x0E, 0x20)))
        files = [*(TREE / "lm27" / "bundle").glob("*.py"), *(TREE / "collect" / "move").glob("*.ps1"),
                 *(TREE / "tests" / "bundle").glob("*.py"), *(TREE / "tests" / "fixtures" / "wp12").glob("*.py")]
        self.assertGreater(len(files), 20)
        for p in files:
            data = p.read_bytes()
            self.assertFalse(any(b in data for b in bad), p.name)

    def test_only_bundle_modules_read_pcs(self):
        """data\\pcs 를 다루는 모듈 이름이 계약 §9.3 의 7개 안에 있다(이 WP 쪽 확인)."""
        allowed = {"loader", "segment", "manifest", "export", "pcreg", "merge", "move"}
        for p in sorted((TREE / "lm27" / "bundle").glob("*.py")):
            text = p.read_text(encoding="utf-8")
            touches = any(s in text for s in (".pc_dir(", ".pcs()", ".seg_dir(", ".move_ready(", ".pc_json("))
            if p.stem not in allowed:
                self.assertFalse(touches, f"{p.name} 는 data\\pcs 를 직접 다루지 않는다(loader·pcreg 를 부른다)")
        self.assertEqual(fsx.canon_bytes({}), b"{}")


if __name__ == "__main__":
    unittest.main()
