# -*- coding: utf-8 -*-
"""WP-12 manifest — lm27.manifest/1(계약 §3.7, TAB §1.4): 저장(gen·prev) · 손상 복구(prev → 재구성, TAB B04) ·
고아 편입(B03) · 격리 · 무덤표 사본 · 커서는 앞으로만."""
import unittest

from lm27.bundle import manifest as mf
from lm27.bundle import segment as seg
from lm27.util import fsx
from tests.fixtures.wp12 import builders as B

CREATED = "2026-10-05T09:02:11Z"


def cur(day, off, ts=None):
    return {"file": f"pc_x/evidence/pc_session/pc.sampler/202610/202610{day:02d}.jsonl.gz", "offset": off,
            "last_ts": ts}


class ManifestTest(B.BundleTestCase):
    def setUp(self):
        super().setUp()
        self.id1 = B.ident("PC1")
        self.pcdir = self.b.pcdir(self.id1.pc_id)

    def seg(self, n=3, start="2026-10-01T00:00:00Z", kind="pc_session", src_to=None):
        return seg.write_segment(self.pcdir, kind, self.id1, B.rows(kind, self.id1.pc_id, n, start=start),
                                 rules_ver=B.RULES_VER, kid=B.KID, created=CREATED, src_to=src_to)

    def test_new_and_save_gen_prev(self):
        m = mf.load_manifest(self.pcdir)
        self.assertEqual(m, mf.new_manifest(self.id1.pc_id))
        m["segments"].append(self.seg())
        mf.save_manifest(self.pcdir, m, now="2026-10-05T00:00:00Z")
        self.assertEqual(m["gen"], 1)
        self.assertFalse((self.pcdir / "manifest.prev.json").exists())
        first = (self.pcdir / "manifest.json").read_bytes()
        m["segments"].append(self.seg(start="2026-10-02T00:00:00Z"))
        mf.save_manifest(self.pcdir, m, now="2026-10-05T00:01:00Z")
        self.assertEqual(m["gen"], 2)
        self.assertEqual((self.pcdir / "manifest.prev.json").read_bytes(), first)
        on_disk = fsx.read_json(self.pcdir / "manifest.json")
        self.assertEqual(on_disk["gen"], 2)
        self.assertEqual(len(on_disk["segments"]), 2)
        self.assertEqual((self.pcdir / "manifest.json").read_bytes(), fsx.canon_bytes(on_disk))

    def test_private_keys_not_saved_and_pc_mismatch(self):
        m = mf.load_manifest(self.pcdir)
        m["_recovered"] = "prev"
        mf.save_manifest(self.pcdir, m)
        self.assertNotIn("_recovered", fsx.read_json(self.pcdir / "manifest.json"))
        bad = mf.new_manifest(B.pc_id_of("PC2"))
        bad["segments"] = "x"
        with self.assertRaises(ValueError):
            mf.save_manifest(self.pcdir, bad)

    def test_b04_corrupt_and_no_prev_rebuilds(self):
        notes = []
        m = mf.load_manifest(self.pcdir)
        c1 = cur(1, 100, "2026-10-01T00:02:00Z")
        c2 = cur(2, 50, "2026-10-02T00:02:00Z")
        m["segments"] += [self.seg(src_to={"pc.sampler": c1}),
                          self.seg(start="2026-10-02T00:00:00Z", src_to={"pc.sampler": c2})]
        mf.add_tombstone(m, seq=9, kind="teams", old_sha256="ab" * 32, new_sha256="cd" * 32, pcdir=self.pcdir)
        mf.save_manifest(self.pcdir, m)
        (self.pcdir / "manifest.json").write_bytes(b"\x00garbage{")
        (self.pcdir / "manifest.prev.json").unlink(missing_ok=True)
        r = mf.load_manifest(self.pcdir, notes=notes)
        self.assertEqual(r["_recovered"], "rebuilt")
        self.assertEqual(sorted(s["sha256"] for s in r["segments"]), sorted(s["sha256"] for s in m["segments"]))
        self.assertEqual(r["cursors"][self.id1.install_id]["pc_session/pc.sampler"], c2)
        self.assertEqual([t["old_sha256"] for t in r["tombstones"]], ["ab" * 32])
        self.assertEqual(notes[0]["code"], "manifest_rebuilt")
        self.assertEqual(notes[0]["n"], 2)

    def test_corrupt_uses_prev(self):
        m = mf.load_manifest(self.pcdir)
        m["segments"].append(self.seg())
        mf.save_manifest(self.pcdir, m)
        mf.save_manifest(self.pcdir, m)
        (self.pcdir / "manifest.json").write_text("[]", encoding="utf-8")
        r = mf.load_manifest(self.pcdir)
        self.assertEqual(r["_recovered"], "prev")
        self.assertEqual(len(r["segments"]), 1)

    def test_rebuild_quarantines_bad_only_when_asked(self):
        a = self.seg()
        b = self.seg(start="2026-10-03T00:00:00Z")
        p = self.pcdir / b["file"]
        p.write_bytes(p.read_bytes()[:-8])
        r = mf.rebuild_manifest(self.pcdir)
        self.assertEqual([s["sha256"] for s in r["segments"]], [a["sha256"]])
        self.assertTrue(p.exists(), "읽기 전용 재구성은 옮기지 않는다")
        self.assertEqual(r["_bad"][0]["file"], b["file"])
        r = mf.rebuild_manifest(self.pcdir, quarantine=True)
        self.assertFalse(p.exists())
        self.assertTrue((self.pcdir / "quarantine" / p.name).exists())
        self.assertEqual(r["quarantine"][0]["file"], "quarantine/" + p.name)

    def test_b03_adopt_orphans(self):
        m = mf.load_manifest(self.pcdir)
        m["segments"].append(self.seg())
        mf.save_manifest(self.pcdir, m)
        c = cur(5, 999, "2026-10-05T00:00:00Z")
        orphan = self.seg(start="2026-10-05T00:00:00Z", src_to={"pc.sampler": c})
        m = mf.load_manifest(self.pcdir)
        self.assertEqual(mf.adopt_orphans(self.pcdir, m), 1)
        self.assertIn(orphan["sha256"], [s["sha256"] for s in m["segments"]])
        self.assertEqual(m["cursors"][self.id1.install_id]["pc_session/pc.sampler"], c)
        self.assertEqual(mf.adopt_orphans(self.pcdir, m), 0, "두 번째는 할 일 없음")

    def test_adopt_quarantines_corrupt_and_tombstoned(self):
        m = mf.load_manifest(self.pcdir)
        bad = self.seg()
        dead = self.seg(start="2026-10-06T00:00:00Z")
        p = self.pcdir / bad["file"]
        p.write_bytes(b"not gzip")
        mf.add_tombstone(m, seq=dead["seq"], kind="pc_session", old_sha256=dead["sha256"], new_sha256="0" * 64)
        self.assertEqual(mf.adopt_orphans(self.pcdir, m), 0)
        reasons = sorted(q["reason"] for q in m["quarantine"])
        self.assertEqual(len(reasons), 2)
        self.assertIn("tombstoned", reasons)
        self.assertEqual(m["segments"], [])
        self.assertEqual(sorted(x.name for x in (self.pcdir / "quarantine").iterdir()),
                         sorted([p.name, dead["file"].split("/")[-1]]))

    def test_cursor_only_forward(self):
        m = mf.new_manifest(self.id1.pc_id)
        self.assertTrue(mf.advance_cursor(m, self.id1.install_id, "pc_session/pc.sampler", cur(2, 10)))
        self.assertFalse(mf.advance_cursor(m, self.id1.install_id, "pc_session/pc.sampler", cur(1, 999)))
        self.assertFalse(mf.advance_cursor(m, self.id1.install_id, "pc_session/pc.sampler", cur(2, 5)))
        self.assertTrue(mf.advance_cursor(m, self.id1.install_id, "pc_session/pc.sampler", cur(2, 11)))
        self.assertEqual(m["cursors"][self.id1.install_id]["pc_session/pc.sampler"]["offset"], 11)

    def test_tomb_copy_union(self):
        m = mf.new_manifest(self.id1.pc_id)
        mf.add_tombstone(m, seq=1, kind="teams", old_sha256="aa" * 32, new_sha256="bb" * 32, pcdir=self.pcdir)
        mf.add_tombstone(m, seq=2, kind="teams", old_sha256="cc" * 32, new_sha256="dd" * 32, pcdir=self.pcdir)
        mf.add_tombstone(m, seq=2, kind="teams", old_sha256="cc" * 32, new_sha256="dd" * 32, pcdir=self.pcdir)
        copy = fsx.read_json(self.pcdir / "quarantine" / "tombstones.json", want=list)
        self.assertEqual([t["old_sha256"] for t in copy], ["aa" * 32, "cc" * 32])
        self.assertEqual(len(m["tombstones"]), 2)


if __name__ == "__main__":
    unittest.main()
