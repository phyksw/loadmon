# -*- coding: utf-8 -*-
"""운반 번들 누수 관문(W1 통합 창): 번들 잠금 잡기·놓기(중첩 포함)와 단일 로더 읽기(``iter_records``·``bundle_status``)를
반복해도 핸들(잠금 파일·세그먼트 파일)·스레드·메모리가 반복 수에 비례해 늘지 않는다. 합성 세그먼트만. 30초 이내."""
from lm27.bundle import loader, pcreg
from lm27.bundle import lock as lk
from lm27.bundle import manifest as mf
from lm27.bundle import segment as seg
from tests.fixtures.leak import assert_bounded
from tests.fixtures.wp12 import builders as B


class BundleLeak(B.BundleTestCase):
    def test_lock_acquire_release_repeated(self):
        lock = lk.BundleLock(self.paths, "fg-write", 1)

        def step(_i):
            with lock, lock:                                   # 같은 인스턴스 중첩도(W1a 반증 #3 회귀)
                self.assertTrue(lk.is_held_here(self.paths))
            self.assertFalse(lk.is_held_here(self.paths))
        assert_bounded(self, step, warm=10, n=200, mem_per_iter=1024, handle_slack=8)

    def test_loader_reads_repeated(self):
        ident = B.ident("PC1")
        d = pcreg.ensure_pc_dir(self.paths, ident, host="", now="2026-09-01T00:00:00Z")
        m = mf.load_manifest(d)
        rows = [B.row("pc_session", ident.pc_id, f"2026-09-01T0{h}:00:00Z") for h in range(6)]
        m["segments"].append(seg.write_segment(d, "pc_session", ident, rows, rules_ver=B.RULES_VER, kid=B.KID,
                                               created="2026-09-02T00:00:00Z", manifest=m))
        mf.save_manifest(d, m)

        def step(_i):
            self.assertEqual(len(list(loader.iter_records(self.paths, "pc_session"))), 6)
            loader.bundle_status(self.paths)
        assert_bounded(self, step, warm=5, n=60, mem_per_iter=16384, handle_slack=8)
