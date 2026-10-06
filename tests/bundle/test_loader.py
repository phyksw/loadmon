# -*- coding: utf-8 -*-
"""WP-12 loader — 단일 로더(TAB §1.15): T-11 dedupe(같은 id 는 observed_at 최대) · B05 변조 세그먼트 건너뜀·보고 ·
B09 일자 경계는 사람 시간대 · 기간·PC 제한 · 논리 PC · 소급 가림 읽기 오버레이 · 무덤표 · 없는 파일 · 상태·검증."""
import unittest

from lm27.bundle import aliases as al
from lm27.bundle import loader
from lm27.bundle import manifest as mf
from lm27.bundle import pcreg
from lm27.bundle import segment as seg
from lm27.util import fsx
from tests.fixtures.wp12 import builders as B

CREATED = "2026-10-05T09:02:11Z"


class LoaderBase(B.BundleTestCase):
    def setUp(self):
        super().setUp()
        self.i1 = B.ident("PC1")
        self.d1 = pcreg.ensure_pc_dir(self.paths, self.i1, host="", now="2026-09-01T00:00:00Z")

    def put(self, ident, kind, rows, created=CREATED):
        d = self.paths.pc_dir(ident.pc_id)
        pcreg.ensure_pc_dir(self.paths, ident, host="", now="2026-09-01T00:00:00Z")
        m = mf.load_manifest(d)
        info = seg.write_segment(d, kind, ident, rows, rules_ver=B.RULES_VER, kid=B.KID, created=created, manifest=m)
        m["segments"].append(info)
        mf.save_manifest(d, m)
        return info


class IterRecordsTest(LoaderBase):
    def test_t11_dedupe_max_observed_at(self):
        r = B.row("pc_session", self.i1.pc_id, "2026-09-01T00:00:00Z", observed="2026-09-01T00:01:00Z")
        r2 = dict(r, observed_at="2026-09-01T02:00:00Z", ts_end="2026-09-01T02:00:00Z")
        r3 = dict(r, observed_at="2026-09-01T01:00:00Z")
        self.put(self.i1, "pc_session", [r], created="2026-09-01T00:02:00Z")
        self.put(self.i1, "pc_session", [r2], created="2026-09-01T02:01:00Z")
        self.put(self.i1, "pc_session", [r3], created="2026-09-01T03:00:00Z")
        got = list(loader.iter_records(self.paths, "pc_session"))
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["observed_at"], "2026-09-01T02:00:00Z")
        self.assertEqual(loader.load_report()["duplicates"], 2)
        self.assertEqual(len(list(loader.iter_records(self.paths, "pc_session", dedupe=False))), 3)

    def test_b05_tampered_segment_skipped_and_reported(self):
        good = self.put(self.i1, "mail", B.rows("mail", self.i1.pc_id, 4))
        bad = self.put(self.i1, "mail", B.rows("mail", self.i1.pc_id, 7, start="2026-09-02T00:00:00Z"))
        p = self.d1 / bad["file"]
        data = bytearray(p.read_bytes())
        data[30] ^= 0x01
        p.write_bytes(bytes(data))
        got = list(loader.iter_records(self.paths, "mail"))
        self.assertEqual(len(got), 4)
        rep = loader.load_report()
        self.assertEqual(len(rep["skipped"]), 1)
        self.assertEqual(rep["skipped"][0]["n_est"], 7)
        self.assertEqual(rep["skipped"][0]["reason"], "sha_mismatch")
        self.assertEqual(rep["segments_read"], 1)
        self.assertTrue(p.exists(), "로더는 파일을 옮기지 않는다(논리 격리)")
        self.assertEqual(good["n"], 4)

    def test_b09_day_boundary_uses_person_tz(self):
        cloud = B.ident("CLOUD", kind="cloud", off=0)
        a = B.row("mail", cloud.pc_id, "2026-09-01T16:00:00Z", off=0)          # KST 09-02 01:00
        b = B.row("mail", self.i1.pc_id, "2026-09-01T16:30:00Z", off=540)      # KST 09-02 01:30
        c = B.row("mail", self.i1.pc_id, "2026-09-01T14:00:00Z", off=540)      # KST 09-01 23:00
        self.put(cloud, "mail", [a])
        self.put(self.i1, "mail", [b, c])
        got = list(loader.iter_records(self.paths, "mail", "2026-09-02", "2026-09-02", cfg=self.b.cfg()))
        self.assertEqual(sorted(r["id"] for r in got), sorted([a["id"], b["id"]]))
        got = list(loader.iter_records(self.paths, "mail", "2026-09-01", "2026-09-01", off_min=0))
        self.assertEqual(len(got), 3, "UTC 기준이면 셋 다 09-01")

    def test_period_pcs_and_annotations(self):
        i2 = B.ident("PC2")
        self.put(self.i1, "pc_file", B.rows("pc_file", self.i1.pc_id, 3, start="2026-09-01T00:00:00Z"))
        self.put(self.i1, "pc_file", B.rows("pc_file", self.i1.pc_id, 2, start="2026-10-10T00:00:00Z"))
        self.put(i2, "pc_file", B.rows("pc_file", i2.pc_id, 4, start="2026-09-05T00:00:00Z"))
        al.record_alias(self.paths, i2.pc_id, self.i1.pc_id, at="2026-09-06T00:00:00Z")
        got = list(loader.iter_records(self.paths, "pc_file", "2026-09-01", "2026-09-30", cfg=self.b.cfg()))
        self.assertEqual(len(got), 7)
        self.assertEqual({(r["_pc"], r["_lpc"]) for r in got},
                         {(self.i1.pc_id, self.i1.pc_id), (i2.pc_id, self.i1.pc_id)})
        self.assertEqual({r["_inst"] for r in got}, {self.i1.install_id, i2.install_id})
        keys = [(r["ts_utc"], r["id"]) for r in got]
        self.assertEqual(keys, sorted(keys))
        only2 = list(loader.iter_records(self.paths, "pc_file", pcs=[i2.pc_id]))
        self.assertEqual({r["_pc"] for r in only2}, {i2.pc_id})
        self.assertEqual(len(list(loader.iter_records(self.paths, "pc_file", d0="2026-10-01"))), 2)
        with self.assertRaises(ValueError):
            list(loader.iter_records(self.paths, "window"))

    def test_overlay_read_side(self):
        rows = B.rows("teams", self.i1.pc_id, 4, start="2026-09-01T00:00:00Z")
        mrows = B.rows("mail", self.i1.pc_id, 2)
        self.put(self.i1, "teams", rows)
        self.put(self.i1, "mail", mrows)
        ov = {"chat": {rows[0]["chat_key"]: rows[2]["ts_utc"]}, "msg": [mrows[1]["msg_key"]]}
        fsx.atomic_write(self.paths.local_only_file("redact_overlay.json"), fsx.canon_bytes(ov))
        got = list(loader.iter_records(self.paths, "teams"))
        self.assertEqual([r["body_masked"] == "" for r in got], [False, False, True, True])
        self.assertEqual([r["ts_utc"] for r in got], [r["ts_utc"] for r in rows], "행 수·시간 열 불변")
        self.assertEqual(loader.load_report()["overlay_rows"], 2)
        mail = list(loader.iter_records(self.paths, "mail"))
        self.assertEqual([r["subject_masked"] == "" for r in mail], [False, True])
        raw = list(loader.iter_records(self.paths, "teams", overlay=False))
        self.assertTrue(all(r["body_masked"] for r in raw))

    def test_blank_text_uses_redact_fields_single_source_C11(self):
        """계약 v1.2 §0.7 C11(W1 통합 창): 비울 열 = lm27.privacy.records.redact_fields(kind) — 정제문 열 + act_cues
        (옛 '_masked 로 끝나는 열' 규칙은 act_cues 를 남겼다). 키·시간·id 는 그대로, 저장 kind 가 아니면 바꾸지 않는다."""
        from lm27.privacy.records import redact_fields
        row = {"id": "0123456789abcdef", "kind": "teams", "ts_utc": "2026-09-01T00:00:00Z", "msg_key": "m0123456789abcdef",
               "chat_key": "c0123456789abcdef", "body_masked": "본문", "file_names_masked": ["a.xlsx"],
               "chat_title_masked": "방", "act_cues": ["req"], "direction": "received"}
        out, ch = loader.blank_text(row)
        self.assertTrue(ch)
        self.assertEqual((out["body_masked"], out["file_names_masked"], out["chat_title_masked"], out["act_cues"]),
                         ("", [], "", []))
        for k in ("id", "kind", "ts_utc", "msg_key", "chat_key", "direction"):
            self.assertEqual(out[k], row[k])
        self.assertEqual(row["act_cues"], ["req"], "원본은 바꾸지 않는다")
        self.assertIn("act_cues", redact_fields("teams"))
        again, ch2 = loader.blank_text(out)
        self.assertFalse(ch2)
        self.assertEqual(loader.blank_text({"kind": "privacy_audit", "x_masked": "y"}), ({"kind": "privacy_audit",
                                                                                            "x_masked": "y"}, False))

    def test_tombstoned_and_missing(self):
        a = self.put(self.i1, "teams", B.rows("teams", self.i1.pc_id, 2))
        b = self.put(self.i1, "teams", B.rows("teams", self.i1.pc_id, 3, start="2026-09-03T00:00:00Z"))
        m = mf.load_manifest(self.d1)
        mf.add_tombstone(m, seq=a["seq"], kind="teams", old_sha256=a["sha256"], new_sha256="0" * 64)
        mf.save_manifest(self.d1, m)
        (self.d1 / b["file"]).unlink()
        got = list(loader.iter_records(self.paths, "teams"))
        self.assertEqual(got, [])
        rep = loader.load_report()
        self.assertEqual(rep["tombstoned"], 1)
        self.assertEqual(rep["missing"], [{"pc_id": self.i1.pc_id, "file": b["file"], "n_est": 3}])

    def test_other_pc_tombstone_applies_bundle_wide(self):
        i2 = B.ident("PC2")
        a = self.put(i2, "teams", B.rows("teams", i2.pc_id, 2))
        m = mf.load_manifest(self.d1)
        mf.add_tombstone(m, seq=1, kind="teams", old_sha256=a["sha256"], new_sha256="0" * 64)
        mf.save_manifest(self.d1, m)
        self.assertEqual(list(loader.iter_records(self.paths, "teams", pcs=[i2.pc_id])), [])

    def test_resanitize_hook(self):
        self.put(self.i1, "manual", B.rows("manual", self.i1.pc_id, 3))
        seen = []

        def hook(kind, row):
            seen.append(kind)
            return None if row["text_masked"].endswith("1") else dict(row, text_masked="[재정제]")
        got = list(loader.iter_records(self.paths, "manual", resanitize=hook))
        self.assertEqual([r["text_masked"] for r in got], ["[재정제]", "[재정제]"])
        self.assertEqual(seen, ["manual"] * 3)

    def test_session_spans(self):
        self.put(self.i1, "pc_session", B.rows("pc_session", self.i1.pc_id, 3, start="2026-09-01T00:00:00Z"))
        self.assertEqual(loader.session_spans(self.paths, self.i1.pc_id),
                         [("2026-09-01T00:00:00Z", "2026-09-01T00:02:00Z")])
        self.assertEqual(loader.session_spans(self.paths, B.pc_id_of("none")), [])


class StatusVerifyTest(LoaderBase):
    def test_status_empty_and_counts(self):
        empty = B.BundleRoot()
        self.addCleanup(empty.remove)
        self.assertEqual(loader.bundle_status(empty.paths)["rc"], 4)
        self.assertEqual(loader.verify_bundle(empty.paths)["rc"], 4)
        self.b.write_bundle_json()
        self.put(self.i1, "mail", B.rows("mail", self.i1.pc_id, 5))
        pcreg.record_probe(self.d1, "mail.com", True, {}, [], date="2026-10-05", cfg=self.b.cfg(), today="2026-10-05")
        st = loader.bundle_status(self.paths, self.b.cfg())
        self.assertEqual(st["rc"], 0)
        self.assertEqual(st["bundle"]["created_on_pc"], B.pc_id_of("PC1"))
        self.assertNotIn("person_key", st["bundle"])
        pc = st["pcs"][0]
        self.assertEqual((pc["pc_id"], pc["label_auto"], pc["kinds"]["mail"]["records"]), (self.i1.pc_id, "PC1", 5))
        self.assertEqual(pc["verdicts"], {"mail.com": "가능"})
        self.assertEqual((st["warn_size_mb"], st["over_size"]), (300, False))
        self.assertNotIn("host_display", pc)

    def test_verify_bundle(self):
        a = self.put(self.i1, "mail", B.rows("mail", self.i1.pc_id, 2))
        self.put(self.i1, "mail", B.rows("mail", self.i1.pc_id, 2, start="2026-09-04T00:00:00Z"))
        r = loader.verify_bundle(self.paths)
        self.assertEqual((r["rc"], r["checked"], r["bad"]), (0, 2, []))
        self.assertTrue(self.paths.verify_cache().is_file())
        p = self.d1 / a["file"]
        data = bytearray(p.read_bytes())
        data[20] ^= 0x01
        p.write_bytes(bytes(data))
        r = loader.verify_bundle(self.paths)
        self.assertEqual(r["rc"], 2)
        self.assertEqual([(x["file"], x["reason"]) for x in r["bad"]], [(a["file"], "sha_mismatch")])
        st = loader.bundle_status(self.paths)
        self.assertEqual(st["rc"], 0, "상태는 크기·존재만(sha 는 verify)")


class UtcParseTest(unittest.TestCase):
    """통합(W2 성능 handoff): 행마다 부르는 시각 파서의 빠른 길이 예전 strptime 과 같은 값·같은 거부."""

    def test_fast_path_same_as_strptime(self):
        from datetime import UTC, datetime
        for ts in ("2026-10-05T01:02:03Z", "2026-02-28T23:59:59Z", "2024-02-29T00:00:00Z", "2026-1-5T01:02:03Z"):
            self.assertEqual(loader._utc(ts), datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC), ts)
        for bad in ("2026-02-30T00:00:00Z", "2026-10-05T24:00:00Z", "2026-10-05 01:02:03", "2026-10-05T01:02:03+09:00", ""):
            with self.assertRaises(ValueError, msg=bad):
                loader._utc(bad)
        with self.assertRaises(TypeError):
            loader._utc(None)


if __name__ == "__main__":
    unittest.main()
