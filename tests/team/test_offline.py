# -*- coding: utf-8 -*-
"""WP-27 오프라인 대체 — 내보내기 바이트·반입(done/rejected/이름 위반/복사 중)·읽기 전용 감시 폴더·서버 실행 중 CLI 반입·
레지스트리 게시(TAB §5, TAB-O01(내보내기 쪽) · O02 · O03 · O04). 임시 폴더·합성 묶음만.
"""
import json
import os
import subprocess
import sys
import time
import types
import unittest

from lm27.team import offline as O
from lm27.util import fsx
from tests.fixtures.wp27 import bundles as B
from tests.fixtures.wp27.helpers import running_server

PK1, PK2 = B.person_key(1), B.person_key(2)
OLD = time.time() - 3600


def _b(pk=PK1, built="2026-08-01T09:00:00+09:00", **kw):
    return B.make_bundle(pk, "2026-07-01", "2026-07-31", built_at=built, **kw)


def _drop(folder, name, raw, mtime=OLD):
    p = os.path.join(str(folder), name)
    fsx.atomic_write(p, raw)
    os.utime(p, (mtime, mtime))
    return p


class OfflineCase(unittest.TestCase):
    def setUp(self):
        self._td = B.temp_dir()
        self.dir = self._td.__enter__()
        self.st = B.new_store(self.dir / "store")

    def tearDown(self):
        self.st.release_server()
        self._td.__exit__(None, None, None)


class TestInbox(OfflineCase):
    def test_o02_store_inbox(self):
        """O02: 정상 1 · 변조 1 · 이름 위반 1 · 복사 중 1 → done 1, rejected 1(+사유), 이름 위반 무시, 복사 중은 다음 회차."""
        good = B.canon(_b())
        bad = bytearray(B.canon(_b(pk=PK2)))
        bad[bad.index(b'"envelope_min":') + 15] = ord("9")                        # 요약 숫자 변조 → integrity
        _drop(self.st.inbox(), f"lm27_team_bundle_{PK1}_2026-07-01_2026-07-31_aaaaaaaaaaaa.json", good)
        _drop(self.st.inbox(), "lm27_team_bundle_x2.json", bytes(bad))
        _drop(self.st.inbox(), "lm27_team_bundle_x.json\n", good) if os.name != "nt" else \
            _drop(self.st.inbox(), "other_bundle.json", good)
        _drop(self.st.inbox(), "lm27_team_bundle_x3.json", B.canon(_b(seed=7)), mtime=time.time())
        r = O.scan_inboxes(self.st, self.st.cfg)
        self.assertEqual((r["stored"], r["rejected"], r["ignored"], r["copying"]), (1, 1, 1, 1))
        self.assertEqual(len(os.listdir(self.st.inbox("done"))), 1)
        rej = sorted(os.listdir(self.st.inbox("rejected")))
        self.assertEqual(rej, ["lm27_team_bundle_x2.json", "lm27_team_bundle_x2.json.reason.json"])
        reason = json.loads(fsx.read_bytes(self.st.inbox("rejected", rej[1])))
        self.assertEqual(reason["code"], "integrity")
        self.assertIn("other_bundle.json", os.listdir(self.st.inbox()))           # 이름 위반은 건드리지 않는다
        self.assertEqual(self.st.member_keys(), [PK1])
        later = O.scan_inboxes(self.st, self.st.cfg, now=time.time() + 120)
        self.assertEqual(later["stale"] + later["stored"] + later["already"], 1)  # 복사 중이던 것은 다음 회차에

    def test_name_whitelist_fullmatch(self):
        for n in ("lm27_team_bundle.json", "lm27_team_bundle_p_0123_2026-07-01_2026-07-31_ab.json"):
            self.assertTrue(O.name_ok(n), n)
        for n in ("lm27_team_bundle.json\n", "x_lm27_team_bundle.json", "lm27_team_bundle_a b.json",
                  "lm27_team_bundle_..json", "lm27_team_bundle.json.part"):
            self.assertFalse(O.name_ok(n), n)

    def test_o03_readonly_watch_dir(self):
        """O03: 감시 폴더의 같은 파일이 반복돼도 1회만 반입(seen), 원본 그대로."""
        share = self.dir / "share"
        fsx.ensure_dir(share)
        raw = B.canon(_b())
        p = _drop(share, "lm27_team_bundle_s1.json", raw)
        cfg = self.st.cfg.derive({"teamServer.inboxDirs": [str(share)]})
        r1 = O.scan_inboxes(self.st, cfg)
        r2 = O.scan_inboxes(self.st, cfg)
        self.assertEqual((r1["stored"], r2["stored"], r2["already"]), (1, 0, 0))
        self.assertEqual(fsx.read_bytes(p), raw)
        seen = json.loads(fsx.read_bytes(self.st.run_file("inbox_seen.json")))
        self.assertEqual(list(seen), [B.sha(raw)])
        self.assertNotIn(str(share), json.dumps(seen, ensure_ascii=False))


class TestImport(OfflineCase):
    def test_o04_server_running_copy_only(self):
        """O04: 서버 실행 중(잠금 점유) team-import → inbox 로 복사만 + 안내, 서버의 다음 감시가 반영."""
        holder = B.new_store(self.dir / "store")
        self.assertTrue(holder.lock_server())
        try:
            src = self.dir / "usb"
            fsx.ensure_dir(src)
            _drop(src, "lm27_team_bundle_u1.json", B.canon(_b()))
            r = O.import_files(self.st, str(src), self.st.cfg)
            self.assertEqual((r["rc"], r["mode"]), (0, "queued"))
            self.assertIn("30초", r["message_ko"])
            self.assertEqual(self.st.member_keys(), [])
            self.assertEqual(O.scan_inboxes(holder, holder.cfg)["stored"], 1)    # 다음 감시 회차(복사 중 대기 없음)
        finally:
            holder.release_server()

    def test_import_direct_with_aggregate(self):
        src = self.dir / "usb"
        fsx.ensure_dir(src)
        _drop(src, "lm27_team_bundle_u1.json", B.canon(_b()))
        _drop(src, "lm27_team_bundle_u2.json", b"{bad")
        r = O.import_files(self.st, str(src), self.st.cfg)
        self.assertEqual((r["rc"], r["mode"], r["aggregate"]["state"]), (2, "direct", "done"))
        self.assertEqual(self.st.current_gen()["gen"], r["aggregate"]["gen"])
        self.assertTrue(self.st.lock_server())                                     # 잠금 해제됨
        self.st.release_server()
        self.assertEqual(O.import_files(self.st, str(self.dir / "없음"), self.st.cfg)["rc"], 3)
        empty = self.dir / "empty"
        fsx.ensure_dir(empty)
        self.assertEqual(O.import_files(self.st, str(empty), self.st.cfg)["rc"], 4)


class TestServerInboxAndCli(OfflineCase):
    def test_server_inbox_loop(self):
        """서버 반입 감시(시작 즉시 한 바퀴) → 저장 → 재취합 요청 → 현재 세대."""
        root = self.dir / "srv"
        st0 = B.new_store(root)
        _drop(st0.inbox(), "lm27_team_bundle_i1.json", B.canon(_b()))
        with running_server(root, inbox=True) as ts:
            deadline = time.time() + 20
            while time.time() < deadline and ts.store.current_gen() is None:
                time.sleep(0.1)
            self.assertEqual(ts.store.member_keys(), [PK1])
            self.assertIsNotNone(ts.store.current_gen())
            self.assertEqual(os.listdir(ts.store.inbox("done")), ["lm27_team_bundle_i1.json"])

    def test_cli_team_import(self):
        """lm27 team-import <파일> --store DIR — CLI 배선(open_store → import_files) 과 rc."""
        src = self.dir / "usb"
        fsx.ensure_dir(src)
        f = _drop(src, "lm27_team_bundle_c1.json", B.canon(_b()))
        store = self.dir / "cli_store"
        r = subprocess.run([sys.executable, "-X", "utf8", "-B", str(B.TREE / "lm27_cli.py"), "team-import", f,
                            "--store", str(store)], capture_output=True, timeout=120, cwd=str(self.dir), check=False)
        st = B.new_store(store)
        from lm27.team import schema
        try:                                         # CLI 는 실물 정제 재검사기(WP-11)를 쓴다 — 같은 판정을 미리 본다
            clean = not schema.privacy_payload_check(st.cfg)(_b())
        except Exception:                            # 재검사기가 아직 없거나 서버 모드 미지원 → 저장 안 함(fail-closed)
            clean = False
        if not clean:
            self.assertEqual(r.returncode, 2, r.stderr.decode("utf-8", "replace")[-400:])
            self.assertEqual(st.member_keys(), [])
            return
        self.assertEqual(r.returncode, 0, r.stderr.decode("utf-8", "replace")[-400:])
        self.assertEqual(st.member_keys(), [PK1])
        self.assertIsNotNone(st.current_gen())


class TestExportRegistry(OfflineCase):
    def _item(self, raw, pk=PK1):
        p = self.dir / "pending.json"
        fsx.atomic_write(p, raw)
        return types.SimpleNamespace(path=str(p), meta={"sha256": B.sha(raw), "person_key": pk,
                                                        "period_key": "2026-07-01_2026-07-31"})

    def test_export_to_dir(self):
        raw = B.canon(_b())
        item = self._item(raw)
        marks = []
        out = self.dir / "share"
        fsx.ensure_dir(out)
        dst = O.export_to_dir(item, str(out), mark=lambda it, st, msg: marks.append(st))
        self.assertEqual(fsx.read_bytes(dst), raw)
        self.assertEqual(os.path.basename(dst), f"lm27_team_bundle_{PK1}_2026-07-01_2026-07-31_{B.sha(raw)[:12]}.json")
        self.assertTrue(O.name_ok(os.path.basename(dst)))
        self.assertEqual(marks, ["exported"])
        self.assertEqual(sorted(os.listdir(out)), [os.path.basename(dst)])         # 키·보고서 동반 0, .part 0
        with self.assertRaises(O.UserError):
            O.export_to_dir(item, "relative\\dir", mark=lambda *a: None)
        with self.assertRaises(O.UserError):
            O.export_to_dir(item, str(self.dir / "없는폴더"), mark=lambda *a: None)
        fsx.atomic_write(item.path, raw + b" ")
        with self.assertRaises(O.UserError):
            O.export_to_dir(item, str(out), mark=lambda *a: None)

    def test_publish_and_read_offline_registry(self):
        self.st.put_registry(B.registry(1))
        pub = self.dir / "pub"
        fsx.ensure_dir(pub)
        cfg = self.st.cfg.derive({"teamServer.publishDir": str(pub), "team.offlineDir": str(pub)})
        self.assertTrue(O.publish_registry(self.st, cfg))
        got = O.read_offline_registry(cfg)
        self.assertEqual((got["version"], got["pepper"]), (1, self.st.pepper))
        self.assertFalse(O.publish_registry(self.st, self.st.cfg))                 # 게시 폴더 없음
        self.assertIsNone(O.read_offline_registry(self.st.cfg))
        fsx.atomic_write(pub / O.REGISTRY_FILE, b'{"schema":"x","version":1}')
        self.assertIsNone(O.read_offline_registry(cfg))
        self.assertEqual(O.default_export_dir(cfg), str(pub))
