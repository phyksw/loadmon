# -*- coding: utf-8 -*-
"""WP-34 미리보기 가림·동료 키 — U12(제목 가림 · 세부 가림 · 니즈 빼기: 시간 수치 불변 + 서버 I2·I3 통과), 가림 편집 함수
(형식·멱등·되돌리기·깨진 파일), U15(pepper 없음 → 개인 범위 키 · 두 팀원 키가 연결되지 않음), U16(같은 pepper 로 두 팀원 —
서로의 self_peer_key 가 상대 peers 에 그대로)."""
import contextlib
import io
import shutil
import tempfile
import unittest
from datetime import UTC, datetime

from lm27 import privacy as P
from lm27.team import build as B
from lm27.team import queue as Q
from lm27.team import schema as S
from lm27.util import events, fsx
from tests.fixtures.wp34 import servers as SV
from tests.fixtures.wp34 import world as W

PERIOD = {"from": W.D0, "to": W.D1}
PER = f"{W.D0}_{W.D1}"
NOW = datetime(2026, 10, 1, 1, 0, 0, tzinfo=UTC)


class MCase(unittest.TestCase):
    def setUp(self):
        self._mode = events.mode()
        events.configure("off")
        self.worlds = []

    def tearDown(self):
        for w in self.worlds:
            w.cleanup()
        events.configure(self._mode)

    def world(self, **kw):
        w = W.World(**kw)
        self.worlds.append(w)
        return w

    def build(self, w, cfg=None, overrides=None, registry=None):
        c = cfg or W.cfg()
        reg = registry if registry is not None else B.registry_cache(w.paths)
        return B.build_team_bundle(W.model(), PERIOD, reg, B.pepper_of(reg),
                                   overrides if overrides is not None else B.load_overrides(w.paths), c,
                                   env=w.env(c), now=NOW)


def _need_ids():
    return [n["need_id"] for n in W.model()["agentic"]["needs"] if not n["dropped"]]


class TestEditors(MCase):
    def test_set_mask_rules(self):
        p = self.world().paths
        self.assertEqual(B.set_mask(p, "u_bad", "title")["rc"], 1)
        self.assertEqual(B.set_mask(p, W.U[1], "everything")["rc"], 1)
        self.assertEqual(B.set_mask(p, W.U[1], "title")["rc"], 0)
        self.assertEqual(B.set_mask(p, W.U[1], "title")["rc"], 4)
        self.assertEqual(B.set_mask(p, W.U[1], "detail")["rc"], 0)
        self.assertEqual(B.set_mask(p, W.U[2], "title")["rc"], 0)
        ov = fsx.read_json(p.team_overrides(), None)
        self.assertEqual(ov["schema"], B.OVERRIDES_SCHEMA)
        self.assertEqual(ov["units"], {W.U[1]: "detail", W.U[2]: "title"})
        self.assertEqual(B.set_mask(p, W.U[1], "none")["rc"], 0)
        self.assertEqual(B.set_mask(p, W.U[1], "none")["rc"], 4)
        self.assertEqual(B.load_overrides(p)["units"], {W.U[2]: "title"})

    def test_drop_need_rules(self):
        p = self.world().paths
        nid = _need_ids()[0]
        self.assertEqual(B.drop_need(p, "n_xyz")["rc"], 1)
        self.assertEqual(B.drop_need(p, nid)["rc"], 0)
        self.assertEqual(B.drop_need(p, nid)["rc"], 4)
        self.assertEqual(B.load_overrides(p)["needs"], {nid: "drop"})

    def test_broken_overrides_file_is_empty(self):
        p = self.world().paths
        fsx.atomic_write(p.team_overrides(), b"{not json")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            ov = B.load_overrides(p)
        self.assertNotIn("not json", err.getvalue())                                   # 경고에 내용을 싣지 않는다
        self.assertEqual({k: v for k, v in ov.items() if k != "schema"},
                         {"units": {}, "needs": {}, "matches": {}, "subagents": {}, "proposals": {}})
        fsx.atomic_write(p.team_overrides(), fsx.canon_bytes({"units": {W.U[1]: 3, W.U[2]: "title"}, "needs": []}))
        self.assertEqual(B.load_overrides(p)["units"], {W.U[2]: "title"})


class TestU12(MCase):
    def test_masks_keep_time_numbers(self):
        w = self.world()
        base, _a = self.build(w)
        nid = _need_ids()[0]
        B.set_mask(w.paths, W.U[1], "title")
        B.set_mask(w.paths, W.U[2], "detail")
        B.drop_need(w.paths, nid)
        obj, _a = self.build(w)
        u = {x["unit_id"]: x for x in obj["units"]}
        bu = {x["unit_id"]: x for x in base["units"]}
        self.assertEqual(u[W.U[1]]["title_mode"], "generic")
        self.assertNotEqual(u[W.U[1]]["title"], bu[W.U[1]]["title"])
        self.assertTrue(bu[W.U[2]]["peers"] and bu[W.U[2]]["apps"])
        self.assertEqual((u[W.U[2]]["peers"], u[W.U[2]]["apps"], u[W.U[2]]["apps_unknown_min"], u[W.U[2]]["evidence_n"]),
                         ([], [], 0, {}))
        self.assertEqual(u[W.U[3]], bu[W.U[3]])                                        # 다른 단위업무는 그대로
        self.assertNotIn(nid, [n["need_id"] for n in obj["agentic"]["needs"]])
        self.assertEqual(len(obj["agentic"]["needs"]), len(base["agentic"]["needs"]) - 1)
        for k in ("envelope_daily", "alloc_daily", "summary", "integrity", "period", "peers"):
            self.assertEqual(obj[k], base[k], k)                                      # 시간 수치·동료 합계 불변
        self.assertEqual({x: u[x]["effort_min"] for x in u}, {x: bu[x]["effort_min"] for x in bu})
        ra = next(x for x in obj["workflows"] if u[W.U[2]]["role_id"] == x["role_id"])
        self.assertEqual([s["label"] for s in ra["steps"]], ["의뢰 수신", "해석 프로그램", "표 계산", "보고 발신"])
        self.assertEqual([e for e in S.validate_team_bundle(obj, registry=W.registry(), side="client",
                                                            calendar=W.cal()) if e.blocking], [])

    def test_masked_bundle_passes_server_invariants(self):
        """서버 실물에 올리고 재취합 — I2(개인=팀)·I3(계층 보존) 위반 0, 달력 판 같음(대조가 실제로 일어남)."""
        from lm27.team import aggregate as A
        w = self.world()
        B.set_mask(w.paths, W.U[1], "title")
        B.set_mask(w.paths, W.U[2], "detail")
        B.drop_need(w.paths, _need_ids()[0])
        store = tempfile.mkdtemp(prefix="lm27t_wp34_store_")
        try:
            with SV.real_team(store) as ts:
                c = W.cfg(**{"team.serverHost": SV.HOST, "team.serverPort": ts.port})
                it = B.build_and_queue(W.model(), PERIOD, c, paths=w.paths, now=NOW, env=w.env(c))
                out = Q.send_item(it, c, now=NOW)
                self.assertEqual(out.state, "sent", out.message)
                res = A.aggregate(ts.store, ts.store.next_gen(), write=False)
            self.assertTrue(res.ok)
            self.assertEqual([x for x in res.warnings if x[:2] in {f"I{i}" for i in range(1, 8)}], [])
            self.assertEqual(A.check_invariants(res.td), [])
            person = res.td["people"][0]
            self.assertNotIn("calendar_mismatch", person["flags"])
            obj = S.loads_bundle(fsx.read_bytes(out.path))
            self.assertEqual([e["mm"] for e in person["months"]], [m["mm"] for m in obj["summary"]["months"]])
        finally:
            shutil.rmtree(store, ignore_errors=True)


class TestPeerKeys(MCase):
    def test_u15_no_pepper_personal_scope(self):
        a = self.world(with_registry=False)
        b_dir = W.deep(W.PERSON_DIR)
        b_dir["people"][W.KIM]["smtp"] = ["me@" + W.INTERNAL]
        b_dir["people"][W.ME]["smtp"] = ["user01@" + W.INTERNAL]
        b = self.world(with_registry=False, person_dir=b_dir)
        oa, _ = self.build(a, registry={})
        ob, _ = self.build(b, registry={})
        for o in (oa, ob):
            self.assertEqual((o["person"]["peer_scope"], o["person"]["pepper_id"]), ("personal", None))
            self.assertEqual({p["scope"] for p in o["peers"]}, {"personal"})
        kr = P.load_keyring(a.paths.data(), None, create=False)
        want = P.peer_key(None, "user01@" + W.INTERNAL, [W.INTERNAL], kr)
        self.assertEqual(want[1], "personal")
        self.assertIn(want[0], [p["peer_key"] for p in oa["peers"]])
        # 개인 키링 범위 키는 팀원끼리 맞지 않는다(서버가 연결에 쓰지 않음)
        self.assertNotIn(ob["person"]["self_peer_key"], [p["peer_key"] for p in oa["peers"]])
        self.assertNotIn(oa["person"]["self_peer_key"], [p["peer_key"] for p in ob["peers"]])
        it = B.build_and_queue(W.model(), PERIOD, W.cfg(), paths=a.paths, now=NOW, env=a.env(W.cfg()))
        self.assertEqual(it.rc, 0)

    def test_u16_same_pepper_keys_match(self):
        a = self.world()
        b_dir = W.deep(W.PERSON_DIR)
        b_dir["people"][W.KIM]["smtp"] = ["me@" + W.INTERNAL]                         # B 에게 동료 KIM = A
        b_dir["people"][W.ME]["smtp"] = ["user01@" + W.INTERNAL]                      # B 본인 = A 의 동료 KIM
        b = self.world(person_dir=b_dir)
        oa, _ = self.build(a)
        ob, _ = self.build(b)
        self.assertEqual((oa["person"]["peer_scope"], ob["person"]["peer_scope"]), ("team", "team"))
        self.assertEqual(oa["person"]["pepper_id"], ob["person"]["pepper_id"])
        self.assertIn(ob["person"]["self_peer_key"], [p["peer_key"] for p in oa["peers"]])
        self.assertIn(oa["person"]["self_peer_key"], [p["peer_key"] for p in ob["peers"]])
        self.assertEqual(oa["person"]["self_peer_key"],
                         P.peer_key(W.PEPPER, "me@" + W.INTERNAL, [W.INTERNAL], None)[0])


if __name__ == "__main__":
    unittest.main()
