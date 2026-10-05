# -*- coding: utf-8 -*-
"""WP-12 segment — 세그먼트 lm27.seg/1(계약 §3.6, TAB §1.3): 이름·머리말·꼬리말·결정적 gzip·정렬·id 중복·남의 레코드 거부·
같은 이름 멱등·충돌·자기 검증·분할(로컬 달·건수·크기 — bundle.segmentMaxRecords·segmentMaxRawMb)."""
import gzip
import json
import random
import re
import unittest

from lm27.bundle import segment as seg
from lm27.util import fsx
from tests.fixtures.wp12 import builders as B

NAME_RX = re.compile(r"^\d{6}-[0-9a-f]{8}-\d{8}T\d{4}Z-\d{8}T\d{4}Z-[0-9a-f]{8}\.jsonl\.gz$")
CREATED = "2026-10-05T09:02:11Z"


class SegmentWriteTest(B.BundleTestCase):
    def setUp(self):
        super().setUp()
        self.id1 = B.ident("PC1")
        self.pcdir = self.b.pcdir(self.id1.pc_id)
        self.recs = B.rows("pc_session", self.id1.pc_id, 5, start="2026-10-04T23:00:00Z")

    def write(self, recs=None, **kw):
        kw.setdefault("rules_ver", B.RULES_VER)
        kw.setdefault("kid", B.KID)
        kw.setdefault("created", CREATED)
        return seg.write_segment(self.pcdir, "pc_session", self.id1, self.recs if recs is None else recs, **kw)

    def test_name_head_foot(self):
        cur = {"file": "x/evidence/pc_session/pc.sampler/202610/20261005.jsonl.gz", "offset": 10, "last_ts": None}
        info = self.write(src_from={"pc.sampler": None}, src_to={"pc.sampler": cur})
        name = info["file"].split("/")[-1]
        self.assertTrue(info["file"].startswith("seg/pc_session/"))
        self.assertRegex(name, NAME_RX)
        self.assertEqual(name, f"000001-{self.id1.install_id[:8]}-20261004T2300Z-20261004T2304Z-{info['sha256'][:8]}"
                               ".jsonl.gz")
        p = self.pcdir / "seg" / "pc_session" / name
        raw = gzip.decompress(p.read_bytes()).split(b"\n")
        head, foot = json.loads(raw[0]), json.loads(raw[-2])
        self.assertEqual(raw[-1], b"")
        self.assertEqual(head["_h"], 1)
        self.assertEqual(head["schema"], "lm27.seg/1")
        self.assertEqual((head["kind"], head["pc_id"], head["install_id"], head["seq"]),
                         ("pc_session", self.id1.pc_id, self.id1.install_id, 1))
        self.assertEqual((head["t0"], head["t1"], head["n"]), ("2026-10-04T23:00:00Z", "2026-10-04T23:04:00Z", 5))
        self.assertEqual(head["srcs"], ["pc.sampler"])
        self.assertEqual((head["rules_ver"], head["kid"], head["agent_ver"], head["created"]),
                         (B.RULES_VER, B.KID, "0.1.0", CREATED))
        self.assertEqual(head["src_to"], {"pc.sampler": cur})
        self.assertEqual(foot, {"_f": 1, "n": 5})
        for ln in raw[:-1]:                       # 줄마다 정규 JSON 바이트
            self.assertEqual(ln, fsx.canon_bytes(json.loads(ln)))
        self.assertEqual(info["n"], 5)
        self.assertEqual(info["bytes"], p.stat().st_size)
        self.assertEqual(info["sha256"], fsx.sha256_hex(p.read_bytes()))
        self.assertEqual(info["src_to"], {"pc.sampler": cur})

    def test_gzip_deterministic_header(self):
        info = self.write()
        data = (self.pcdir / info["file"]).read_bytes()
        self.assertEqual(data[:3], b"\x1f\x8b\x08")
        self.assertEqual(data[3] & 0x08, 0, "파일 이름(FNAME) 없음")
        self.assertEqual(data[4:8], b"\x00\x00\x00\x00", "mtime 0")

    def test_deterministic_across_roots_and_input_order(self):
        a = self.write()
        other = B.BundleRoot()
        self.addCleanup(other.remove)
        shuffled = list(self.recs)
        random.Random(3).shuffle(shuffled)
        b = seg.write_segment(other.pcdir(self.id1.pc_id), "pc_session", self.id1, shuffled, rules_ver=B.RULES_VER,
                              kid=B.KID, created=CREATED)
        self.assertEqual(a["sha256"], b["sha256"])
        self.assertEqual(a["file"], b["file"])

    def test_records_sorted_ts_then_id(self):
        same_ts = [B.row("pc_session", self.id1.pc_id, "2026-10-01T00:00:00Z", seq=i) for i in range(4)]
        info = self.write(same_ts + self.recs)
        got = list(seg.read_segment(self.pcdir / info["file"]))
        keys = [(r["ts_utc"], r["id"]) for r in got]
        self.assertEqual(keys, sorted(keys))
        self.assertEqual(len(got), 9)

    def test_rejects(self):
        with self.assertRaisesRegex(ValueError, "empty"):
            self.write([])
        with self.assertRaisesRegex(ValueError, "dup id"):
            self.write(self.recs + [dict(self.recs[0])])
        foreign = B.rows("pc_session", B.pc_id_of("PC9"), 1)
        with self.assertRaisesRegex(ValueError, "foreign"):
            self.write(foreign)
        with self.assertRaisesRegex(ValueError, "foreign"):
            self.write(B.rows("pc_file", self.id1.pc_id, 1))
        bad = dict(self.recs[0])
        bad["_pc"] = self.id1.pc_id
        with self.assertRaises(ValueError):
            self.write([bad])
        bad = dict(self.recs[0])
        bad["id"] = "XYZ"
        with self.assertRaises(ValueError):
            self.write([bad])
        with self.assertRaises(ValueError):
            seg.write_segment(self.b.paths.pcs() / "notapc", "pc_session", self.id1, self.recs, rules_ver="x",
                              kid="y")
        with self.assertRaises(ValueError):
            seg.write_segment(self.pcdir, "window", self.id1, self.recs, rules_ver="x", kid="y")
        self.assertFalse((self.pcdir / "seg").exists(), "거부한 쓰기는 파일을 남기지 않는다")

    def test_same_name_idempotent_and_conflict(self):
        a = self.write(seq=1)
        b = self.write(seq=1)
        self.assertEqual(a, b)
        p = self.pcdir / a["file"]
        data = bytearray(p.read_bytes())
        data[-5] ^= 0xFF
        p.write_bytes(bytes(data))
        with self.assertRaises(seg.SegmentConflict):
            self.write(seq=1)
        self.assertEqual(p.read_bytes(), bytes(data), "덮어쓰지 않는다")

    def test_seq_counts_disk_orphans(self):
        a = self.write()
        b = self.write(self.recs[:2])
        c = seg.write_segment(self.pcdir, "pc_file", self.id1, B.rows("pc_file", self.id1.pc_id, 1),
                              rules_ver=B.RULES_VER, kid=B.KID, created=CREATED)
        self.assertEqual((a["seq"], b["seq"], c["seq"]), (1, 2, 1))

    def test_verify_segment(self):
        info = self.write()
        p = self.pcdir / info["file"]
        self.assertEqual(seg.verify_segment(p), (True, ""))
        self.assertEqual(seg.verify_segment(p, info["sha256"]), (True, ""))
        good = p.read_bytes()
        bad = bytearray(good)
        bad[len(bad) // 2] ^= 0x01
        p.write_bytes(bytes(bad))
        ok, why = seg.verify_segment(p)
        self.assertFalse(ok)
        self.assertIn(why, ("sha_name_mismatch", "gzip_error"))
        p.write_bytes(good[:-6])
        self.assertFalse(seg.verify_segment(p)[0])
        p.write_bytes(good)
        self.assertEqual(seg.verify_segment(p, "0" * 64), (False, "sha_mismatch"))
        self.assertEqual(seg.verify_segment(self.pcdir / "seg" / "pc_session" / "nope.jsonl.gz"), (False, "missing"))

    def test_parse_rejects_bad_body(self):
        head = {"_h": 1, "schema": "lm27.seg/1", "kind": "pc_session", "pc_id": self.id1.pc_id,
                "install_id": self.id1.install_id, "seq": 1, "t0": self.recs[0]["ts_utc"],
                "t1": self.recs[-1]["ts_utc"], "n": 5}
        lines = [head] + self.recs + [{"_f": 1, "n": 4}]
        gz = fsx.gzip_bytes(b"\n".join(fsx.canon_bytes(x) for x in lines) + b"\n")
        with self.assertRaises(seg.SegmentCorrupt) as cm:
            seg.parse_segment_bytes(gz)
        self.assertEqual(cm.exception.reason, "count_mismatch")
        lines = [head] + list(reversed(self.recs)) + [{"_f": 1, "n": 5}]
        gz = fsx.gzip_bytes(b"\n".join(fsx.canon_bytes(x) for x in lines) + b"\n")
        with self.assertRaises(seg.SegmentCorrupt) as cm:
            seg.parse_segment_bytes(gz)
        self.assertEqual(cm.exception.reason, "order")


class SplitTest(B.BundleTestCase):
    def test_local_month_boundary(self):
        pc = B.pc_id_of("PC1")
        a = B.row("pc_session", pc, "2026-09-30T14:00:00Z", seq=1)          # 로컬 09-30 23:00
        b = B.row("pc_session", pc, "2026-09-30T15:30:00Z", seq=2)          # 로컬 10-01 00:30
        c = B.row("pc_session", pc, "2026-09-30T15:30:00Z", seq=3, off=0)   # UTC PC — 로컬 09-30
        self.assertEqual(seg.local_month(b), "2026-10")
        self.assertEqual(seg.local_month(c), "2026-09")
        chunks = seg.split_records([b, a], None)
        self.assertEqual([[r["id"] for r in ch] for ch in chunks], [[a["id"]], [b["id"]]])

    def test_count_and_size_limits_from_cfg(self):
        pc = B.pc_id_of("PC1")
        recs = B.rows("pc_session", pc, 250, start="2026-09-02T00:00:00Z")
        cfg = self.b.cfg(**{"bundle.segmentMaxRecords": 100})
        chunks = seg.split_records(recs, cfg)
        self.assertEqual([len(c) for c in chunks], [100, 100, 50])
        self.assertEqual(seg.split_limits(cfg), (100, 16 << 20))
        one = len(fsx.canon_bytes(recs[0])) + 1
        chunks = seg.split_records(recs[:10], None, max_raw_bytes=one * 3 + 5)
        self.assertTrue(all(len(c) <= 3 for c in chunks))
        self.assertEqual(sum(len(c) for c in chunks), 10)
        self.assertEqual(seg.split_records([], None), [])


if __name__ == "__main__":
    unittest.main()
