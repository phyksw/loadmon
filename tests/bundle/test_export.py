# -*- coding: utf-8 -*-
"""WP-12 export — 에이전트 로컬 원장 → 번들 세그먼트(TAB §1.7 ③): B01 PC1→PC2→PC1 · B02 커서 멱등 · B03 고아 편입 ·
B10 store 정리 gap · B11 늦은 수확 · B25 잘린 gzip 멤버 · anchor_since · 감사 봉투 · 달 분할 · 같은 id 새 판 · T-12.
로컬 원장 읽기는 계약 §3.10 형 가짜(tests.fixtures.wp12.fake_store — WP-11 완료 전 이음매 가짜)."""
import os
import unittest
from unittest import mock

from lm27.bundle import export as ex
from lm27.bundle import loader
from lm27.bundle import manifest as mf
from lm27.bundle import pcreg
from lm27.paths import Paths
from lm27.util import fsx
from tests.fixtures.wp12 import builders as B
from tests.fixtures.wp12 import fake_store as fs

ANCHOR = "2026-01-01T00:00:00Z"


class ExportTest(B.BundleTestCase):
    def setUp(self):
        super().setUp()
        self.cfg = self.b.cfg()
        self.i1 = B.ident("PC1")
        self.d1 = pcreg.ensure_pc_dir(self.paths, self.i1, host="", anchor_since=ANCHOR, now="2026-09-01T00:00:00Z")

    def export(self, ident=None, paths=None, **kw):
        ident = ident or self.i1
        paths = paths or self.paths
        kw.setdefault("now", "2026-10-05T09:00:00Z")
        return ex.export_agent_streams(paths.pc_dir(ident.pc_id), ident, self.cfg, paths=paths,
                                       reader=fs.read_store_since, **kw)

    def load(self, kind="pc_session"):
        return list(loader.iter_records(self.paths, kind))

    def test_b01_pc1_pc2_pc1(self):
        p2 = Paths(self.b.root, lad=self.b.root / "_lad2")
        i2 = B.ident("PC2", kind="laptop")
        d2 = pcreg.ensure_pc_dir(self.paths, i2, host="", anchor_since=ANCHOR, now="2026-09-02T00:00:00Z")
        r1 = B.rows("pc_session", self.i1.pc_id, 30, start="2026-09-01T00:00:00Z")
        r2 = B.rows("pc_session", i2.pc_id, 20, start="2026-09-02T00:00:00Z")
        fs.append_member(self.paths, self.i1.pc_id, "pc_session", "pc.sampler", "2026-09-01", r1)
        fs.append_member(p2, i2.pc_id, "pc_session", "pc.sampler", "2026-09-02", r2)
        ctime1 = os.stat(self.d1).st_ctime_ns
        self.assertEqual(self.export().rc, 0)
        self.assertEqual(self.export(i2, p2).rc, 0)
        more = B.rows("pc_session", self.i1.pc_id, 10, start="2026-09-03T00:00:00Z")
        fs.append_member(self.paths, self.i1.pc_id, "pc_session", "pc.sampler", "2026-09-03", more)
        before = len(mf.load_manifest(self.d1)["segments"])
        res = self.export()
        self.assertEqual(res.new, {"pc_session": 10})
        self.assertGreater(len(mf.load_manifest(self.d1)["segments"]), before)
        self.assertEqual(sorted(x.name for x in self.paths.pcs().iterdir()), sorted([self.i1.pc_id, i2.pc_id]))
        self.assertEqual(os.stat(self.d1).st_ctime_ns, ctime1, "폴더 rename 없음")
        self.assertTrue(d2.is_dir())
        got = self.load()
        self.assertEqual(len(got), 60, "로더 레코드 수 = store 총합")
        self.assertEqual(len({r["id"] for r in got}), 60, "중복 0")
        self.assertEqual({r["_pc"] for r in got}, {self.i1.pc_id, i2.pc_id})

    def test_b02_cursor_idempotent(self):
        fs.append_member(self.paths, self.i1.pc_id, "pc_session", "pc.sampler", "2026-09-01",
                         B.rows("pc_session", self.i1.pc_id, 5))
        self.assertEqual(self.export().rc, 0)
        mbytes = (self.d1 / "manifest.json").read_bytes()
        for _ in range(2):
            res = self.export(now="2026-10-05T10:00:00Z")
            self.assertEqual((res.rc, res.new, res.segments, res.saved), (4, {}, [], False))
        self.assertEqual((self.d1 / "manifest.json").read_bytes(), mbytes)

    def test_b03_orphan_adopted_no_dup(self):
        rows = B.rows("pc_session", self.i1.pc_id, 8)
        fs.append_member(self.paths, self.i1.pc_id, "pc_session", "pc.sampler", "2026-09-01", rows[:3])
        self.export(now="2026-10-05T08:00:00Z")
        fs.append_member(self.paths, self.i1.pc_id, "pc_session", "pc.sampler", "2026-09-02", rows[3:])
        mbytes = (self.d1 / "manifest.json").read_bytes()
        with mock.patch.object(mf, "save_manifest", side_effect=RuntimeError("죽음 모사")):
            with self.assertRaises(RuntimeError):
                self.export()
        self.assertEqual(len(list((self.d1 / "seg" / "pc_session").iterdir())), 2)
        self.assertEqual((self.d1 / "manifest.json").read_bytes(), mbytes, "세그먼트를 쓴 뒤 manifest 전에 죽음")
        res = self.export(now="2026-10-05T09:30:00Z")
        self.assertEqual(res.adopted, 1)
        self.assertEqual(res.new, {}, "고아의 src_to 로 커서가 이미 끝 — 다시 내보내지 않는다")
        got = self.load()
        self.assertEqual(sorted(r["id"] for r in got), sorted(r["id"] for r in rows))
        m = mf.load_manifest(self.d1)
        cur = m["cursors"][self.i1.install_id]["pc_session/pc.sampler"]
        self.assertTrue(cur["file"].endswith("20260902.jsonl.gz"))

    def test_crash_before_first_manifest_rebuilds(self):
        rows = B.rows("pc_session", self.i1.pc_id, 4)
        fs.append_member(self.paths, self.i1.pc_id, "pc_session", "pc.sampler", "2026-09-01", rows)
        with mock.patch.object(mf, "save_manifest", side_effect=RuntimeError("죽음 모사")):
            with self.assertRaises(RuntimeError):
                self.export()
        res = self.export(now="2026-10-05T09:30:00Z")
        self.assertEqual(res.new, {})
        self.assertTrue(res.saved)
        self.assertEqual(len(self.load()), 4)

    def test_b10_store_pruned_gap(self):
        f1 = fs.append_member(self.paths, self.i1.pc_id, "pc_session", "pc.sampler", "2026-09-01",
                              B.rows("pc_session", self.i1.pc_id, 3))
        self.export()
        fs.append_member(self.paths, self.i1.pc_id, "pc_session", "pc.sampler", "2026-09-01",
                         B.rows("pc_session", self.i1.pc_id, 3, start="2026-09-01T05:00:00Z"))
        fs.append_member(self.paths, self.i1.pc_id, "pc_session", "pc.sampler", "2026-09-03",
                         B.rows("pc_session", self.i1.pc_id, 4, start="2026-09-03T00:00:00Z"))
        f1.unlink()
        res = self.export(now="2026-10-06T00:00:00Z")
        self.assertEqual(len(res.gaps), 1)
        g = mf.load_manifest(self.d1)["gaps"]
        self.assertEqual(len(g), 1)
        self.assertEqual((g[0]["reason"], g[0]["stream"], g[0]["install_id"]),
                         ("store_pruned", "pc_session/pc.sampler", self.i1.install_id))
        self.assertEqual(res.new, {"pc_session": 4})
        self.export(now="2026-10-07T00:00:00Z")
        self.assertEqual(len(mf.load_manifest(self.d1)["gaps"]), 1, "같은 gap 을 두 번 적지 않는다")

    def test_b11_late_harvest_file_offset_cursor(self):
        today = B.rows("pc_session", self.i1.pc_id, 5, start="2026-10-05T01:00:00Z", src="pc.events")
        fs.append_member(self.paths, self.i1.pc_id, "pc_session", "pc.events", "2026-10-05", today)
        self.export()
        last_ts = mf.load_manifest(self.d1)["cursors"][self.i1.install_id]["pc_session/pc.events"]["last_ts"]
        late = B.rows("pc_session", self.i1.pc_id, 7, start="2026-10-04T08:00:00Z", src="pc.events")
        fs.append_member(self.paths, self.i1.pc_id, "pc_session", "pc.events", "2026-10-05", late)
        res = self.export(now="2026-10-05T15:00:00Z")
        self.assertEqual(res.new, {"pc_session": 7})
        missed_by_time_cursor = sum(1 for r in late if r["ts_utc"] <= last_ts)
        self.assertGreater(missed_by_time_cursor, 0)
        self.assertEqual(len(self.load()), 12)

    def test_b25_truncated_member(self):
        first = B.rows("pc_session", self.i1.pc_id, 4)
        fs.append_member(self.paths, self.i1.pc_id, "pc_session", "pc.sampler", "2026-09-01", first)
        tail = B.rows("pc_session", self.i1.pc_id, 6, start="2026-09-01T06:00:00Z")
        whole = len(fs.member_bytes(tail))
        p = fs.append_member(self.paths, self.i1.pc_id, "pc_session", "pc.sampler", "2026-09-01", tail,
                             truncate_to=whole // 2)
        res = self.export()
        self.assertEqual(res.new, {"pc_session": 4})
        cur = mf.load_manifest(self.d1)["cursors"][self.i1.install_id]["pc_session/pc.sampler"]
        self.assertEqual(cur["offset"], len(fs.member_bytes(first)), "오프셋은 잘린 멤버 앞")
        fs.finish_member(p, tail, whole // 2)
        res = self.export(now="2026-10-05T10:00:00Z")
        self.assertEqual(res.new, {"pc_session": 6})
        got = self.load()
        self.assertEqual(len(got), 10)
        self.assertEqual(len({r["id"] for r in got}), 10)

    def test_anchor_since_filter(self):
        pcreg.update_pc(self.d1, {"anchor_since": "2026-09-15T00:00:00Z"})
        rows = (B.rows("pc_file", self.i1.pc_id, 3, start="2026-09-10T00:00:00Z")
                + B.rows("pc_file", self.i1.pc_id, 2, start="2026-09-20T00:00:00Z"))
        fs.append_member(self.paths, self.i1.pc_id, "pc_file", "pc.files", "2026-09-21", rows)
        res = self.export()
        self.assertEqual(res.new, {"pc_file": 2})
        self.assertEqual(res.skipped["before_anchor"], 3)

    def test_audit_envelope_and_foreign(self):
        ev = {"ev": "collect_batch", "ts_utc": "2026-10-05T01:02:03Z", "pc_id": self.i1.pc_id, "stage": "agent",
              "src": "pc.sampler", "rules_ver": B.RULES_VER, "kid": B.KID, "rows_in": 10, "rows_out": 9,
              "dropped": {"ad": 1}, "dur_ms": 12}
        other = dict(ev, pc_id=B.pc_id_of("PC9"))
        fs.append_audit(self.paths, "2026-10-05", [ev, other])
        res = self.export()
        self.assertEqual(res.new, {"privacy_audit": 1})
        self.assertEqual(res.skipped["foreign"], 1)
        got = list(loader.iter_records(self.paths, "privacy_audit"))
        self.assertEqual(len(got), 1)
        r = got[0]
        self.assertEqual(r["id"], fsx.sha256_hex(fsx.canon_bytes(ev))[:16])
        self.assertEqual((r["kind"], r["src"], r["rows_in"]), ("privacy_audit", "agent", 10))
        self.assertEqual(list(loader.iter_records(self.paths, "pc_session")), [], "증거 조회에 감사 스트림 없음")

    def test_month_split_and_chunk_cursor(self):
        rows = B.rows("pc_session", self.i1.pc_id, 6, start="2026-09-30T13:00:00Z", step_min=60)
        fs.append_member(self.paths, self.i1.pc_id, "pc_session", "pc.sampler", "2026-10-01", rows)
        res = self.export()
        self.assertEqual(len(res.segments), 2)
        self.assertIsNone(res.segments[0]["src_to"])
        self.assertTrue(res.segments[1]["src_to"]["pc.sampler"]["file"].endswith("20261001.jsonl.gz"))
        self.assertEqual(sum(s["n"] for s in res.segments), 6)

    def test_same_id_new_version_in_batch(self):
        r = B.row("pc_session", self.i1.pc_id, "2026-09-01T00:00:00Z", observed="2026-09-01T00:05:00Z")
        newer = dict(r, observed_at="2026-09-01T03:00:00Z", ts_end="2026-09-01T03:00:00Z")
        fs.append_member(self.paths, self.i1.pc_id, "pc_session", "pc.sampler", "2026-09-01", [r])
        fs.append_member(self.paths, self.i1.pc_id, "pc_session", "pc.sampler", "2026-09-01", [newer])
        res = self.export()
        self.assertEqual(res.new, {"pc_session": 1})
        self.assertEqual(self.load()[0]["observed_at"], "2026-09-01T03:00:00Z")

    def test_t12_other_pc_bytes_unchanged_and_own_only(self):
        i2 = B.ident("PC2")
        d2 = pcreg.ensure_pc_dir(self.paths, i2, host="", anchor_since=ANCHOR, now="2026-09-02T00:00:00Z")
        p2 = Paths(self.b.root, lad=self.b.root / "_lad2")
        fs.append_member(p2, i2.pc_id, "pc_session", "pc.sampler", "2026-09-01", B.rows("pc_session", i2.pc_id, 3))
        self.export(i2, p2)
        snap = self.b.snapshot(d2)
        fs.append_member(self.paths, self.i1.pc_id, "pc_session", "pc.sampler", "2026-09-01",
                         B.rows("pc_session", self.i1.pc_id, 3))
        self.export()
        self.assertEqual(self.b.snapshot(d2), snap)
        with self.assertRaises(ValueError):
            ex.export_agent_streams(self.d1, i2, self.cfg, paths=self.paths, reader=fs.read_store_since)

    def test_foreign_rows_in_store_skipped(self):
        rows = B.rows("pc_session", self.i1.pc_id, 2) + B.rows("pc_session", B.pc_id_of("PC7"), 2)
        fs.append_member(self.paths, self.i1.pc_id, "pc_session", "pc.sampler", "2026-09-01", rows)
        res = self.export()
        self.assertEqual((res.new, res.skipped.get("foreign")), ({"pc_session": 2}, 2))

    def test_resanitize_hook_and_observed_from(self):
        fs.append_member(self.paths, self.i1.pc_id, "teams", "teams.uia", "2026-09-01",
                         B.rows("teams", self.i1.pc_id, 3))
        aj = {"install_id": self.i1.install_id, "installed_at": "2026-08-31T23:00:00Z"}
        fsx.atomic_write(self.paths.agent_json(), fsx.canon_bytes(aj))

        def hook(kind, row):
            if row["id"].startswith(("0", "1", "2", "3")):
                return None
            return dict(row, rules_ver="2026.10.1")
        res = self.export(resanitize=hook)
        got = list(loader.iter_records(self.paths, "teams"))
        self.assertTrue(all(r["rules_ver"] == "2026.10.1" for r in got))
        self.assertEqual(len(got) + res.skipped.get("dropped", 0), 3)
        m = mf.load_manifest(self.d1)
        self.assertEqual(m["observed_from"][self.i1.install_id], "2026-08-31T23:00:00Z")


if __name__ == "__main__":
    unittest.main()
