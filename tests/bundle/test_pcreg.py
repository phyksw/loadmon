# -*- coding: utf-8 -*-
"""WP-12 pcreg — pc.json lm27.pc/1(계약 §3.8, TAB §1.5): 최소 기록 · label_auto 순서 · 능력 기록(history 30) ·
verdict 6단계(계약 §6.4 — 확정 ✔ 사유 · 서로 다른 날 N회 · probe_sig · TTL) · 번들 도착 경로 탐침(TAB B23) · GUID 충돌(B08)."""
import unittest

from lm27.bundle import manifest as mf
from lm27.bundle import pcreg
from lm27.bundle import segment as seg
from lm27.util import fsx
from tests.fixtures.wp12 import builders as B

NOW = "2026-10-05T00:00:00Z"
TODAY = "2026-10-05"


def h(date, status, reasons=(), sig=None):
    return {"date": date, "status": status, "reasons": list(reasons), "probe_sig": sig}


class PcJsonTest(B.BundleTestCase):
    def test_ensure_pc_dir_min_record_and_labels(self):
        i1 = B.ident("PC1")
        d1 = pcreg.ensure_pc_dir(self.paths, i1, host="HOST-A", anchor_since="2026-09-01T00:00:00Z", now=NOW)
        pc = pcreg.load_pc(d1)
        self.assertEqual(d1, self.paths.pc_dir(i1.pc_id))
        self.assertEqual(pc["schema"], "lm27.pc/1")
        self.assertEqual((pc["pc_id"], pc["id_source"], pc["kind"], pc["label_auto"]),
                         (i1.pc_id, "machineguid", "desktop", "PC1"))
        self.assertEqual(pc["tz"], {"utc_offset_min": 540, "windows_tz": "", "changes": []})
        self.assertEqual(pc["roles"], ["pc_usage", "mail_local", "teams_window"])
        self.assertEqual(pc["installs"][0]["install_id"], i1.install_id)
        self.assertEqual(pc["installs"][0]["task"], "LM27-" + i1.install_id)
        self.assertEqual((pc["first_seen"], pc["last_seen"], pc["anchor_since"]), (NOW, NOW, "2026-09-01T00:00:00Z"))
        self.assertEqual(pc["capabilities"], {})
        self.assertEqual(sorted(p.name for p in d1.iterdir()), ["pc.json"], "설치 전용 — pc.json 만")
        c = B.ident("CLOUD", kind="cloud", off=0)
        dc = pcreg.ensure_pc_dir(self.paths, c, host="", now=NOW)
        self.assertEqual(pcreg.load_pc(dc)["label_auto"], "클라우드PC")
        self.assertEqual(pcreg.load_pc(dc)["roles"], ["pc_usage", "account_backfill", "copilot"])
        d2 = pcreg.ensure_pc_dir(self.paths, B.ident("PC2", kind="laptop"), host="", now=NOW)
        self.assertEqual(pcreg.load_pc(d2)["label_auto"], "PC2")
        c2 = pcreg.ensure_pc_dir(self.paths, B.ident("CLOUD2", kind="cloud"), host="", now=NOW)
        self.assertEqual(pcreg.load_pc(c2)["label_auto"], "클라우드PC2")

    def test_ensure_again_updates_only_own(self):
        i1, i2 = B.ident("PC1"), B.ident("PC2")
        pcreg.ensure_pc_dir(self.paths, i1, host="", anchor_since="2026-09-01T00:00:00Z", now=NOW)
        d2 = pcreg.ensure_pc_dir(self.paths, i2, host="", now=NOW)
        before = self.b.snapshot(d2)
        moved = B.ident("PC1", inst=B.install_of("PC1-new"), off=0)
        pcreg.ensure_pc_dir(self.paths, moved, host="", now="2026-10-06T00:00:00Z")
        pc = pcreg.load_pc(self.paths.pc_dir(i1.pc_id))
        self.assertEqual(pc["last_seen"], "2026-10-06T00:00:00Z")
        self.assertEqual(pc["first_seen"], NOW)
        self.assertEqual(pc["anchor_since"], "2026-09-01T00:00:00Z", "anchor_since 는 처음 한 번만")
        self.assertEqual([x["install_id"] for x in pc["installs"]], [i1.install_id, moved.install_id])
        self.assertEqual(pc["tz"]["utc_offset_min"], 0)
        self.assertEqual(pc["tz"]["changes"][0]["from"], 540)
        self.assertEqual(self.b.snapshot(d2), before, "다른 pc_id 폴더 바이트 불변")

    def test_unchanged_pc_json_not_rewritten(self):
        d = pcreg.ensure_pc_dir(self.paths, B.ident("PC1"), host="", now=NOW)
        pc = pcreg.load_pc(d)
        self.assertFalse(pcreg.save_pc(d, pc))
        with self.assertRaises(ValueError):
            pcreg.save_pc(d, dict(pc, pc_id=B.pc_id_of("PC9")))

    def test_touch_visit(self):
        i1 = B.ident("PC1")
        d = pcreg.ensure_pc_dir(self.paths, i1, host="", now=NOW)
        pc = pcreg.touch_visit(d, i1, manifest_gen=3, impl="py", now="2026-10-05T01:00:00Z")
        self.assertEqual(pc["visits"][-1], {"at": "2026-10-05T01:00:00Z", "install_id": i1.install_id,
                                            "agent_ver": "0.1.0", "manifest_gen": 3})
        self.assertEqual(pc["installs"][0]["impl"], "py")

    def test_list_pcs_ignores_probe_files(self):
        pcreg.ensure_pc_dir(self.paths, B.ident("PC1"), host="", now=NOW)
        fsx.atomic_write(self.paths.pcs() / ".probe_abcd", b"")
        (self.paths.pcs() / "not_a_pc").mkdir()
        self.assertEqual(pcreg.list_pcs(self.paths), [B.pc_id_of("PC1")])


class VerdictTest(B.BundleTestCase):
    def v(self, hist, cfg=None, today=TODAY):
        return pcreg.verdict(hist, cfg if cfg is not None else self.b.cfg(), today=today)

    def test_six_steps(self):
        self.assertEqual(self.v([]), "미확인")
        self.assertEqual(self.v([h("2026-10-01", "fail", ["R-EDGEPOL"]), h("2026-10-02", "ok")]), "가능")
        two_days = [h("2026-10-02", "fail", ["R-EDGEPOL"]), h("2026-10-05", "fail", ["R-EDGEPOL"])]
        self.assertEqual(self.v(two_days), "불가(확정)")
        same_day = [h("2026-10-05", "fail", ["R-EDGEPOL"]), h("2026-10-05", "fail", ["R-EDGEPOL"])]
        self.assertEqual(self.v(same_day), "불가(잠정)")
        human = [h(f"2026-10-0{d}", "fail", ["R-LOGIN"]) for d in (1, 2, 3)]
        self.assertEqual(self.v(human), "불가(잠정)", "R-LOGIN 은 확정 ✘")
        transport = [h("2026-10-01", "transport_fail", ["R-TRANSPORT"]), h("2026-10-02", "unknown")]
        self.assertEqual(self.v(transport), "미확인")
        mixed = [h("2026-10-02", "fail", ["R-EDGEPOL"]), h("2026-10-03", "fail", ["R-NOIDX"])]
        self.assertEqual(self.v(mixed), "불가(잠정)", "같은 사유가 서로 다른 날 N회여야 확정")

    def test_window_after_last_ok_and_probe_sig_release(self):
        hist = [h("2026-09-20", "fail", ["R-EDGEPOL"], "s1"), h("2026-09-21", "fail", ["R-EDGEPOL"], "s1"),
                h("2026-09-22", "ok", [], "s1"), h("2026-10-05", "fail", ["R-EDGEPOL"], "s1")]
        self.assertEqual(self.v(hist), "불가(잠정)", "마지막 ok 이전 실패는 세지 않는다")
        hist = [h("2026-10-01", "fail", ["R-EDGEPOL"], "s1"), h("2026-10-02", "fail", ["R-EDGEPOL"], "s1"),
                h("2026-10-05", "fail", ["R-EDGEPOL"], "s2")]
        self.assertEqual(self.v(hist), "불가(잠정)", "탐침 값이 바뀌면 그 전 실패는 자동 해제")
        hist.append(h("2026-10-05", "transport_fail", [], "s2"))
        self.assertEqual(self.v(hist), "불가(잠정)")

    def test_ttl(self):
        hist = [h("2026-09-01", "fail", ["R-NOEVT"]), h("2026-09-02", "fail", ["R-NOEVT"])]
        self.assertEqual(self.v(hist, today="2026-09-16"), "불가(확정)")
        self.assertEqual(self.v(hist, today="2026-09-17"), "불가(잠정)", "TTL 14일이 지나면 한 번 다시 시도")
        cfg = self.b.cfg(**{"collect.confirmTtlDays": 30})
        self.assertEqual(self.v(hist, cfg, today="2026-09-17"), "불가(확정)")

    def test_confirm_count_from_cfg(self):
        hist = [h("2026-10-04", "fail", ["R-CLM"]), h("2026-10-05", "fail", ["R-CLM"])]
        self.assertEqual(self.v(hist, self.b.cfg(**{"collect.confirmBlockedCount": 3})), "불가(잠정)")
        hist.insert(0, h("2026-10-03", "fail", ["R-CLM"]))
        self.assertEqual(self.v(hist, self.b.cfg(**{"collect.confirmBlockedCount": 3})), "불가(확정)")

    def test_latest_transport_fail_after_ok(self):
        hist = [h("2026-10-04", "ok"), h("2026-10-05", "transport_fail", ["R-TRANSPORT"])]
        self.assertEqual(self.v(hist), "미확인")

    def test_confirmable_single_source(self):
        from lm27.collect import rcmap
        self.assertIs(pcreg.CONFIRMABLE, rcmap.CONFIRMABLE, "X-336 — 확정 ✔ 집합은 rcmap 한 벌")
        self.assertIn("R-EDGEPOL", pcreg.CONFIRMABLE)
        self.assertNotIn("R-LOGIN", pcreg.CONFIRMABLE)

    def test_verdict_without_cfg_uses_declared_defaults(self):
        hist = [h("2026-10-02", "fail", ["R-EDGEPOL"]), h("2026-10-05", "fail", ["R-EDGEPOL"])]
        self.assertEqual(pcreg.verdict(hist, None, today=TODAY), "불가(확정)")


class RecordProbeTest(B.BundleTestCase):
    def setUp(self):
        super().setUp()
        self.d = pcreg.ensure_pc_dir(self.paths, B.ident("PC1"), host="", now=NOW)
        self.cfg = self.b.cfg()

    def test_record_and_history_cap(self):
        e = pcreg.record_probe(self.d, "mail.owa", False, None, ["R-EDGEPOL"], date="2026-10-02", cfg=self.cfg,
                               today=TODAY)
        self.assertEqual(e["verdict"], "불가(잠정)")
        e = pcreg.record_probe(self.d, "mail.owa", False, None, ["R-EDGEPOL"], date="2026-10-05", cfg=self.cfg,
                               today=TODAY)
        self.assertEqual(e["verdict"], "불가(확정)")
        pc = pcreg.load_pc(self.d)
        ent = pc["capabilities"]["mail.owa"]
        self.assertEqual(ent["history"][-1], {"date": "2026-10-05", "status": "fail", "reasons": ["R-EDGEPOL"],
                                              "probe_sig": None})
        self.assertEqual((ent["ok"], ent["value"], ent["reasons"]), (False, None, ["R-EDGEPOL"]))
        for _ in range(35):
            pcreg.record_probe(self.d, "env", True, {"ctypes_ok": True}, [], date="2026-10-05", cfg=self.cfg,
                               today=TODAY)
        ent = pcreg.load_pc(self.d)["capabilities"]["env"]
        self.assertEqual(len(ent["history"]), 30)
        self.assertEqual(ent["history_dropped"], 5)
        self.assertEqual(ent["verdict"], "가능")

    def test_status_derivation_and_validation(self):
        e = pcreg.record_probe(self.d, "mail.com", None, {"hresult": "0x8001010A"}, ["R-COM-BUSY"],
                               "transport_fail", date=TODAY, cfg=self.cfg, today=TODAY)
        self.assertEqual(e["verdict"], "미확인")
        e = pcreg.record_probe(self.d, "teams.uia", None, None, [], date=TODAY, cfg=self.cfg, today=TODAY)
        self.assertEqual(e["history"][-1]["status"], "unknown")
        with self.assertRaises(ValueError):
            pcreg.record_probe(self.d, "Bad Key", True, None, [])
        with self.assertRaises(ValueError):
            pcreg.record_probe(self.d, "env", False, None, ["not-a-code"])
        with self.assertRaises(ValueError):
            pcreg.record_probe(self.d, "env", False, None, [], "maybe")

    def test_refresh_verdicts_ttl(self):
        for d in ("2026-09-01", "2026-09-02"):
            pcreg.record_probe(self.d, "pc.events", False, None, ["R-NOEVT"], date=d, cfg=self.cfg, today=d)
        self.assertEqual(pcreg.load_pc(self.d)["capabilities"]["pc.events"]["verdict"], "불가(확정)")
        out = pcreg.refresh_verdicts(self.d, self.cfg, today="2026-10-05")
        self.assertEqual(out["pc.events"], "불가(잠정)")


class FakeLoc:
    def __init__(self, **kw):
        self.kw = {"drive": 3, "onedrive": [], "attrs": 0, "known": [], "free": 50000, "write": True}
        self.kw.update(kw)

    def drive_type(self, root):
        return self.kw["drive"]

    def onedrive_roots(self):
        return self.kw["onedrive"]

    def file_attrs(self, path):
        return self.kw["attrs"]

    def known_folders(self):
        return self.kw["known"]

    def free_mb(self, path):
        return self.kw["free"]

    def try_write(self, paths):
        return self.kw["write"]


class BundleLocationTest(B.BundleTestCase):
    def test_clean(self):
        r = pcreg.probe_bundle_location(self.paths, probe=FakeLoc())
        self.assertTrue(r["ok"])
        self.assertEqual(r["reasons"], [])
        self.assertEqual(r["value"]["drive_type"], "fixed")
        self.assertEqual(r["value"]["root_len"], len(str(self.paths.root)))

    def test_b23_onedrive_and_warnings(self):
        parent = str(self.paths.root.parent)
        r = pcreg.probe_bundle_location(self.paths, probe=FakeLoc(onedrive=[parent]))
        self.assertIn("R-BUNDLE-ONEDRIVE", r["reasons"])
        self.assertTrue(r["ok"], "경고는 수집을 막지 않는다")
        r = pcreg.probe_bundle_location(self.paths, probe=FakeLoc(attrs=0x400000))
        self.assertIn("R-BUNDLE-ONEDRIVE", r["reasons"])
        r = pcreg.probe_bundle_location(self.paths, probe=FakeLoc(drive=4, free=100))
        self.assertEqual(sorted(r["reasons"]), ["R-BUNDLE-LOWSPACE", "R-BUNDLE-NETWORK"])
        r = pcreg.probe_bundle_location(self.paths, probe=FakeLoc(write=False))
        self.assertFalse(r["ok"])
        self.assertEqual(r["status"], "fail")
        self.assertIn("R-BUNDLE-READONLY", r["reasons"])
        r = pcreg.probe_bundle_location(self.paths, probe=FakeLoc(known=["\\\\srv\\share"]))
        self.assertNotIn("R-BUNDLE-REDIRECT", r["reasons"], "ROOT 가 리디렉션 폴더 아래가 아니면 경고 없음")

    def test_real_probe_smoke(self):
        r = pcreg.probe_bundle_location(self.paths)
        self.assertTrue(r["value"]["writable"])
        self.assertTrue(r["ok"])
        self.assertEqual([p.name for p in self.paths.pcs().iterdir()], [], "쓰기 시험 파일은 지운다")
        self.assertEqual(set(r["value"]), {"drive_type", "onedrive", "redirected", "network", "writable", "free_mb",
                                           "root_len"})


class CollisionTest(B.BundleTestCase):
    def _seg(self, ident, start, n):
        d = self.paths.pc_dir(ident.pc_id)
        return seg.write_segment(d, "pc_session", ident, B.rows("pc_session", ident.pc_id, n, start=start),
                                 rules_ver=B.RULES_VER, kid=B.KID, created=NOW)

    def test_b08_overlap_flags(self):
        a = B.ident("PC1")
        b = B.ident("PC1", inst=B.install_of("clone"))
        d = pcreg.ensure_pc_dir(self.paths, a, host="", now=NOW)
        m = mf.load_manifest(d)
        m["segments"] += [self._seg(a, "2026-10-01T00:00:00Z", 60), self._seg(b, "2026-10-01T03:00:00Z", 60)]
        self.assertFalse(pcreg.mark_collisions(d, manifest=m))
        m["segments"].append(self._seg(b, "2026-10-01T00:10:00Z", 40))
        self.assertTrue(pcreg.mark_collisions(d, manifest=m))
        self.assertEqual(pcreg.load_pc(d)["flags"], ["pc_id_collision"])
        self.assertTrue(pcreg.mark_collisions(d, manifest=m))
        self.assertEqual(pcreg.load_pc(d)["flags"], ["pc_id_collision"])


if __name__ == "__main__":
    unittest.main()
