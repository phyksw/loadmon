# -*- coding: utf-8 -*-
"""WP-12 aliases — 논리 PC 별칭(TAB §1.8): VDI 자동 별칭(B07) · 겹치면 안 함 · 사람 지정·되돌리기 · 사슬·순환 ·
설정 bundle.autoAliasVdi · bundle.overlapToleranceMin."""
import unittest

from lm27.bundle import aliases as al
from lm27.bundle import manifest as mf
from lm27.bundle import pcreg
from lm27.bundle import segment as seg
from lm27.util import fsx
from tests.fixtures.wp12 import builders as B


class AliasTest(B.BundleTestCase):
    def vdi(self, tag, first_seen, *, host_class="a3f9", kind="vdi", off=540):
        i = B.ident(tag, kind=kind, off=off)
        d = pcreg.ensure_pc_dir(self.paths, i, host="", host_class=host_class, now=first_seen)
        return i, d

    def session(self, ident, d, start, n):
        m = mf.load_manifest(d)
        m["segments"].append(seg.write_segment(d, "pc_session", ident,
                                               B.rows("pc_session", ident.pc_id, n, start=start),
                                               rules_ver=B.RULES_VER, kid=B.KID, created=start))
        mf.save_manifest(d, m)

    def test_b07_three_vdi_sessions_one_logical(self):
        a = self.vdi("V1", "2026-09-01T00:00:00Z")
        b = self.vdi("V2", "2026-09-02T00:00:00Z")
        c = self.vdi("V3", "2026-09-03T00:00:00Z")
        self.session(*a, "2026-09-01T00:00:00Z", 120)
        self.session(*b, "2026-09-02T00:00:00Z", 120)
        self.session(*c, "2026-09-03T00:00:00Z", 120)
        made = al.auto_alias(self.paths, self.b.cfg(), now="2026-09-04T00:00:00Z")
        self.assertEqual(len(made), 2)
        amap = al.logical_map(self.paths)
        self.assertEqual({amap[b[0].pc_id], amap[c[0].pc_id]}, {a[0].pc_id})
        self.assertNotIn(a[0].pc_id, amap)
        self.assertEqual(al.auto_alias(self.paths, self.b.cfg(), now="2026-09-05T00:00:00Z"), [], "멱등")
        decs = fsx.read_json(self.paths.pc_aliases())["decisions"]
        self.assertTrue(all(d["rule"] == "auto_vdi" for d in decs))
        self.assertEqual(decs[0]["why"], {"kind": "vdi", "host_class": "a3f9", "tz": 540})

    def test_b07_overlap_20min_no_alias(self):
        a = self.vdi("V1", "2026-09-01T00:00:00Z")
        b = self.vdi("V2", "2026-09-01T00:30:00Z")
        self.session(*a, "2026-09-01T00:00:00Z", 60)
        self.session(*b, "2026-09-01T00:40:00Z", 60)          # 00:40~01:39 vs 00:00~00:59 → 19분 겹침
        self.assertEqual(al.auto_alias(self.paths, self.b.cfg(**{"bundle.overlapToleranceMin": 30}),
                                       now="2026-09-04T00:00:00Z")[0]["pc_id"], b[0].pc_id)
        al.undo_alias(self.paths, b[0].pc_id, at="2026-09-04T00:00:01Z")
        self.assertNotIn(b[0].pc_id, {k for k, v in al.logical_map(self.paths).items() if v != k})

    def test_overlap_blocks(self):
        a = self.vdi("V1", "2026-09-01T00:00:00Z")
        b = self.vdi("V2", "2026-09-01T00:30:00Z")
        self.session(*a, "2026-09-01T00:00:00Z", 60)
        self.session(*b, "2026-09-01T00:39:00Z", 60)          # 20분 겹침 > 10분
        self.assertEqual(al.auto_alias(self.paths, self.b.cfg(), now="2026-09-04T00:00:00Z"), [])

    def test_switch_off_and_ineligible(self):
        self.vdi("V1", "2026-09-01T00:00:00Z")
        self.vdi("V2", "2026-09-02T00:00:00Z")
        self.assertEqual(al.auto_alias(self.paths, self.b.cfg(**{"bundle.autoAliasVdi": False})), [])
        self.vdi("D1", "2026-09-03T00:00:00Z", kind="desktop")
        self.vdi("D2", "2026-09-04T00:00:00Z", kind="desktop")
        self.vdi("N1", "2026-09-05T00:00:00Z", host_class="", kind="cloud")
        self.vdi("N2", "2026-09-06T00:00:00Z", host_class="", kind="cloud")
        self.vdi("T1", "2026-09-07T00:00:00Z", host_class="bbbb", off=0)
        made = al.auto_alias(self.paths, self.b.cfg(), now="2026-09-09T00:00:00Z")
        self.assertEqual([d["pc_id"] for d in made], [B.pc_id_of("V2")])

    def test_user_undo_not_re_aliased(self):
        a = self.vdi("V1", "2026-09-01T00:00:00Z")
        b = self.vdi("V2", "2026-09-02T00:00:00Z")
        al.auto_alias(self.paths, self.b.cfg(), now="2026-09-03T00:00:00Z")
        self.assertEqual(al.undo_alias(self.paths, b[0].pc_id, at="2026-09-03T00:00:01Z")["rc"], 0)
        self.assertEqual(al.logical_map(self.paths)[b[0].pc_id], b[0].pc_id)
        self.assertEqual(al.auto_alias(self.paths, self.b.cfg(), now="2026-09-04T00:00:00Z"), [])
        self.assertEqual(al.undo_alias(self.paths, b[0].pc_id)["rc"], 4)
        self.assertEqual(a[0].pc_id, B.pc_id_of("V1"))

    def test_manual_chain_cycle_label(self):
        p1, p2, p3 = B.pc_id_of("A"), B.pc_id_of("B"), B.pc_id_of("C")
        self.assertEqual(al.record_alias(self.paths, p2, p1, at="2026-09-01T00:00:00Z")["rc"], 0)
        self.assertEqual(al.record_alias(self.paths, p3, p2, at="2026-09-01T00:00:01Z")["rc"], 0)
        self.assertEqual(al.logical_map(self.paths), {p2: p1, p3: p1})
        self.assertEqual(al.record_alias(self.paths, p3, p1)["rc"], 4, "이미 같은 논리 PC")
        with self.assertRaises(ValueError):
            al.record_alias(self.paths, p1, p3)                # p3 → p1 이므로 p1 → p3 은 자기 자신
        self.assertEqual(al.record_alias(self.paths, p1, "회사 노트북", at="2026-09-02T00:00:00Z")["rc"], 0)
        self.assertEqual(al.logical_map(self.paths)[p3], "회사 노트북")
        for bad in ("a/b", "x" * 41, " lead", "c:x"):
            with self.assertRaises(ValueError):
                al.record_alias(self.paths, p1, bad)
        with self.assertRaises(ValueError):
            al.record_alias(self.paths, "pc_bad", p1)

    def test_aliases_file_shape(self):
        p1, p2 = B.pc_id_of("A"), B.pc_id_of("B")
        al.record_alias(self.paths, p2, p1, at="2026-09-01T00:00:00Z", rule="manual")
        obj = fsx.read_json(self.paths.pc_aliases())
        self.assertEqual(obj, {"schema": "lm27.pcalias/1", "decisions": [
            {"at": "2026-09-01T00:00:00Z", "pc_id": p2, "logical": p1, "rule": "manual"}]})


if __name__ == "__main__":
    unittest.main()
