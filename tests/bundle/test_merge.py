# -*- coding: utf-8 -*-
"""WP-12 merge — 사본 분기 번들 합치기(TAB §1.13, B18)·소급 가림 재작성(§1.14, B19): sha 합집합 · 멱등(2회째 변화 0) ·
다른 사람 거부 · 무덤표의 옛 sha 는 다시 들이지 않음 · 별칭·outbox·AI 답 보존소 합집합 · T-12(다른 PC 폴더 불변)."""
import shutil
import unittest

from lm27.bundle import aliases as al
from lm27.bundle import loader
from lm27.bundle import manifest as mf
from lm27.bundle import merge as mg
from lm27.bundle import pcreg
from lm27.bundle import segment as seg
from lm27.paths import Paths
from lm27.util import fsx
from tests.fixtures.wp12 import builders as B

CREATED = "2026-10-05T09:02:11Z"


class PathsCR(Paths):
    """CR(계약 §2.1 Paths 보강) 반영 모사 — outbox 상태 폴더 안 파일 경로."""

    def outbox_file(self, state, name):
        return self.outbox(state) / name


def put(paths, ident, kind, rows, created=CREATED):
    d = paths.pc_dir(ident.pc_id)
    pcreg.ensure_pc_dir(paths, ident, host="", now="2026-09-01T00:00:00Z")
    m = mf.load_manifest(d)
    info = seg.write_segment(d, kind, ident, rows, rules_ver=B.RULES_VER, kid=B.KID, created=created, manifest=m)
    m["segments"].append(info)
    mf.save_manifest(d, m, now=created)
    return info


class MergeTest(B.BundleTestCase):
    def setUp(self):
        super().setUp()
        self.b.write_bundle_json()
        self.i1, self.i2, self.i3 = B.ident("PC1"), B.ident("PC2"), B.ident("PC3")
        put(self.paths, self.i1, "pc_session", B.rows("pc_session", self.i1.pc_id, 5))
        put(self.paths, self.i1, "teams", B.rows("teams", self.i1.pc_id, 4))
        self.other = B.BundleRoot()
        self.addCleanup(self.other.remove)
        shutil.rmtree(self.other.root / "data")
        shutil.copytree(self.paths.data(), self.other.root / "data")
        put(self.paths, self.i2, "mail", B.rows("mail", self.i2.pc_id, 3))                 # A 에만 있는 PC2
        put(self.paths, self.i1, "pc_session", B.rows("pc_session", self.i1.pc_id, 2, start="2026-09-05T00:00:00Z"),
            created="2026-10-05T10:00:00Z")
        put(self.other.paths, self.i1, "pc_session",
            B.rows("pc_session", self.i1.pc_id, 3, start="2026-09-07T00:00:00Z"), created="2026-10-05T11:00:00Z")
        put(self.other.paths, self.i3, "pc_file", B.rows("pc_file", self.i3.pc_id, 6))       # B 에만 있는 PC3

    def shas(self, paths, pid):
        return {s["sha256"] for s in mf.load_manifest(paths.pc_dir(pid))["segments"]}

    def test_b18_union_idempotent(self):
        want1 = self.shas(self.paths, self.i1.pc_id) | self.shas(self.other.paths, self.i1.pc_id)
        pc2 = self.b.snapshot(self.paths.pc_dir(self.i2.pc_id))
        other_before = self.other.snapshot()
        r = mg.merge_bundle(self.paths, self.other.paths.data())
        self.assertEqual(r.rc, 0)
        self.assertEqual(r.pcs_added, [self.i3.pc_id])
        self.assertEqual(self.shas(self.paths, self.i1.pc_id), want1)
        self.assertEqual(self.shas(self.paths, self.i3.pc_id), self.shas(self.other.paths, self.i3.pc_id))
        self.assertEqual(len(list(loader.iter_records(self.paths, "pc_session"))), 10)
        self.assertEqual(len(list(loader.iter_records(self.paths, "pc_file"))), 6)
        self.assertEqual(pcreg.load_pc(self.paths.pc_dir(self.i3.pc_id))["pc_id"], self.i3.pc_id)
        self.assertEqual(self.b.snapshot(self.paths.pc_dir(self.i2.pc_id)), pc2, "T-12 다른 PC 폴더 바이트 불변")
        self.assertEqual(self.other.snapshot(), other_before, "상대 쪽은 읽기만")
        snap = self.b.snapshot()
        r2 = mg.merge_bundle(self.paths, self.other.root)              # 프로그램 폴더로 줘도 같다
        self.assertEqual(r2.rc, 4)
        self.assertEqual(self.b.snapshot(), snap, "2회째 변화 0")
        r3 = mg.merge_bundle(self.other.paths, self.paths.data())      # 반대 방향도 합집합
        self.assertEqual(r3.rc, 0)
        self.assertEqual(self.shas(self.other.paths, self.i1.pc_id), want1)
        snap_o = self.other.snapshot()
        self.assertEqual(mg.merge_bundle(self.other.paths, self.paths.data()).rc, 4)
        self.assertEqual(self.other.snapshot(), snap_o)

    def test_refuse_other_person_and_non_bundle(self):
        c = B.BundleRoot()
        self.addCleanup(c.remove)
        c.write_bundle_json("p_ffffffffffff")
        put(c.paths, B.ident("PC9"), "mail", B.rows("mail", B.pc_id_of("PC9"), 2))
        snap = self.b.snapshot()
        r = mg.merge_bundle(self.paths, c.paths.data())
        self.assertEqual((r.rc, r.reason), (2, "other_person"))
        self.assertEqual(self.b.snapshot(), snap)
        empty = B.BundleRoot()
        self.addCleanup(empty.remove)
        self.assertEqual(mg.merge_bundle(self.paths, empty.root).reason, "not_bundle")
        self.assertEqual(mg.merge_bundle(self.paths, self.paths.data()).reason, "same_bundle")

    def test_adopts_bundle_json_when_missing(self):
        self.paths.bundle_json().unlink()
        r = mg.merge_bundle(self.paths, self.other.paths.data())
        self.assertTrue(r.bundle_json_adopted)
        self.assertEqual(fsx.read_json(self.paths.bundle_json())["person_key"], "p_0123456789ab")

    def test_b19_redact_then_merge_never_reintroduces(self):
        rows = list(loader.iter_records(self.paths, "teams"))
        ov = {"chat": {rows[0]["chat_key"]: rows[0]["ts_utc"]}, "msg": []}
        fsx.atomic_write(self.paths.local_only_file("redact_overlay.json"), fsx.canon_bytes(ov))
        old = {s["sha256"] for s in mf.load_manifest(self.paths.pc_dir(self.i1.pc_id))["segments"]
               if s["kind"] == "teams"}
        r = mg.redact_rewrite_own(self.paths.pc_dir(self.i1.pc_id), now="2026-10-06T00:00:00Z")
        self.assertEqual((r["rc"], r["rewritten"], r["rows_changed"]), (0, 1, 4))
        res = mg.merge_bundle(self.paths, self.other.paths.data())
        self.assertGreaterEqual(res.segments_skipped_tombstoned, 1)
        self.assertFalse(old & self.shas(self.paths, self.i1.pc_id), "무덤표의 옛 sha 는 들어오지 않음")
        self.assertTrue(all(r["body_masked"] == "" for r in loader.iter_records(self.paths, "teams", overlay=False)))
        mg.merge_bundle(self.other.paths, self.paths.data())          # 가리기 전 사본에 가린 판을 합침
        got = list(loader.iter_records(self.other.paths, "teams", overlay=False))
        self.assertEqual(len(got), 4)
        self.assertTrue(all(r["body_masked"] == "" for r in got), "가린 판만 읽힌다(옛 sha 는 무덤표로 제외)")


class RedactTest(B.BundleTestCase):
    def setUp(self):
        super().setUp()
        self.i1 = B.ident("PC1")
        self.rows = B.rows("teams", self.i1.pc_id, 5)
        self.info = put(self.paths, self.i1, "teams", self.rows)
        self.mail = put(self.paths, self.i1, "mail", B.rows("mail", self.i1.pc_id, 2))
        self.d1 = self.paths.pc_dir(self.i1.pc_id)

    def test_rewrite_same_seq_tombstone_and_idempotent(self):
        ov = {"chat": {}, "msg": [self.rows[1]["msg_key"], self.rows[3]["msg_key"]]}
        r = mg.redact_rewrite_own(self.d1, overlay=ov, now="2026-10-06T00:00:00Z")
        self.assertEqual((r["rc"], r["rewritten"], r["rows_changed"]), (0, 1, 2))
        m = mf.load_manifest(self.d1)
        new = [s for s in m["segments"] if s["kind"] == "teams"]
        self.assertEqual(len(new), 1)
        self.assertEqual(new[0]["seq"], self.info["seq"])
        self.assertNotEqual(new[0]["sha256"], self.info["sha256"])
        self.assertFalse((self.d1 / self.info["file"]).exists(), "옛 파일 삭제")
        head, recs = seg.read_segment_full(self.d1 / new[0]["file"])
        self.assertEqual(head["redacted_from"], self.info["sha256"])
        self.assertEqual([x["id"] for x in recs], [x["id"] for x in sorted(self.rows, key=lambda x: (x["ts_utc"],
                                                                                                       x["id"]))])
        self.assertEqual([x["body_masked"] == "" for x in recs], [False, True, False, True, False])
        self.assertEqual([x["ts_utc"] for x in recs], [x["ts_utc"] for x in self.rows])
        self.assertEqual(m["tombstones"][0]["old_sha256"], self.info["sha256"])
        self.assertEqual(m["tombstones"][0]["reason"], "redact")
        copy = fsx.read_json(self.d1 / "quarantine" / "tombstones.json", want=list)
        self.assertEqual(copy[0]["old_sha256"], self.info["sha256"])
        mail_after = [s for s in m["segments"] if s["kind"] == "mail"]
        self.assertEqual(mail_after[0]["sha256"], self.mail["sha256"], "걸리지 않은 세그먼트 불변")
        self.assertEqual(mg.redact_rewrite_own(self.d1, overlay=ov)["rc"], 4)
        reb = mf.rebuild_manifest(self.d1)
        self.assertEqual(mf.tombstoned_shas(reb), {self.info["sha256"]}, "재구성도 무덤표를 안다")

    def test_no_overlay_nothing(self):
        self.assertEqual(mg.redact_rewrite_own(self.d1)["rc"], 4)
        with self.assertRaises(ValueError):
            mg.redact_rewrite_own(self.paths.pcs() / "x")


class SideStoresTest(B.BundleTestCase):
    def setUp(self):
        super().setUp()
        self.b.write_bundle_json()
        self.o = B.BundleRoot()
        self.addCleanup(self.o.remove)
        self.o.write_bundle_json()

    def test_aliases_union(self):
        p1, p2, p3 = B.pc_id_of("A"), B.pc_id_of("B"), B.pc_id_of("C")
        al.record_alias(self.paths, p2, p1, at="2026-09-01T00:00:00Z")
        al.record_alias(self.o.paths, p2, p1, at="2026-09-01T00:00:00Z")
        al.record_alias(self.o.paths, p3, p1, at="2026-09-02T00:00:00Z")
        r = mg.merge_bundle(self.paths, self.o.paths.data())
        self.assertEqual(r.aliases_added, 1)
        self.assertEqual(al.logical_map(self.paths), {p2: p1, p3: p1})
        self.assertEqual(mg.merge_bundle(self.paths, self.o.paths.data()).rc, 4)

    def _outbox_items(self):
        def item(paths, state, body):
            sha = fsx.sha256_hex(body)[:12]
            name = f"lm27_team_bundle_2026-09-01_2026-09-30_{sha}.json"
            fsx.atomic_write(paths.outbox(state) / name, body)
            fsx.atomic_write(paths.outbox(state) / (name + ".meta.json"), b"{}")
            return name
        same = item(self.paths, "sent", b'{"x":1}')
        item(self.o.paths, "pending", b'{"x":1}')                       # 같은 sha 는 하나
        new = item(self.o.paths, "pending", b'{"x":2}')
        return same, new

    def test_outbox_union_by_sha(self):
        same, new = self._outbox_items()
        mine = PathsCR(self.b.root, lad=self.b.lad)                   # 계약 §2.1 보강 CR(outbox_file) 반영 모사
        r = mg.merge_bundle(mine, self.o.paths.data())
        self.assertEqual(r.outbox_added, 2)
        self.assertTrue((self.paths.outbox("pending") / new).is_file())
        self.assertTrue((self.paths.outbox("pending") / (new + ".meta.json")).is_file())
        self.assertFalse((self.paths.outbox("pending") / same).exists())
        self.assertEqual(mg.merge_bundle(mine, self.o.paths.data()).rc, 4)

    def test_outbox_union_with_real_paths_method_C19(self):
        """계약 v1.2 §0.7 C19(W1 통합 창): ``Paths.outbox_file`` 이 생겨 실물 Paths 로도 합집합 — 'outbox_merge_unavailable' 없음."""
        _same, new = self._outbox_items()
        r = mg.merge_bundle(self.paths, self.o.paths.data())
        self.assertEqual(r.outbox_added, 2)
        self.assertNotIn("outbox_merge_unavailable", [n.get("code") for n in r.notes])
        self.assertTrue((self.paths.outbox("pending") / new).is_file())
        self.assertEqual(self.paths.outbox_file("pending", new), self.paths.outbox("pending") / new)

    def test_ai_store_union_sorted(self):
        def commit(ts, ck, ans, rid="R2ABCD"):
            return {"t": "commit", "ts": ts, "stage": "task_label", "ck": ck, "key": "k", "rid": rid, "by": "ai",
                    "final": True, "ans": ans}
        mine = [commit("2026-10-05T10:00:00+09:00", "c1", {"a": 1})]
        theirs = [commit("2026-10-05T09:00:00+09:00", "c1", {"a": 0}), mine[0],
                  commit("2026-10-05T11:00:00+09:00", "c1", {"a": 2})]
        body = lambda xs: "".join(fsx.canon_bytes(x).decode() + "\n" for x in xs).encode()   # noqa: E731
        fsx.atomic_write(self.paths.ai_store("task_label"), body(mine))
        fsx.atomic_write(self.o.paths.ai_store("task_label"), body(theirs) + b'{"torn')
        r = mg.merge_bundle(self.paths, self.o.paths.data())
        self.assertEqual(r.ai_lines_added, 2)
        lines = [fsx.loads_strict(x) for x in self.paths.ai_store("task_label").read_bytes().splitlines()]
        self.assertEqual([x["ans"]["a"] for x in lines], [0, 1, 2], "ts 순 — ck 의 마지막 줄 = 최신 커밋")
        snap = self.b.snapshot()
        self.assertEqual(mg.merge_bundle(self.paths, self.o.paths.data()).rc, 4)
        self.assertEqual(self.b.snapshot(), snap)


if __name__ == "__main__":
    unittest.main()
