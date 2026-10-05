# -*- coding: utf-8 -*-
"""WP-27 store — 사람 × 기간 원자 교체·stale_kept·멱등·거절 코드·손상 복구·레지스트리·명단(TAB §3.7·§3.8·§3.10·§3.11).

TAB-S07(레지스트리 판·순환)·S08(current 손상)·S13(옛 묶음 역전)·U04(금지 문자열 거절). 합성 자료·임시 폴더만.
"""
import json
import os
import subprocess
import sys
import unittest

from lm27.team import store as T
from lm27.util import fsx
from tests.fixtures.wp27 import bundles as B

PK1, PK2 = B.person_key(1), B.person_key(2)


def _b(pk=PK1, d0="2026-07-01", d1="2026-07-31", built="2026-08-03T09:12:00+09:00", **kw):
    return B.make_bundle(pk, d0, d1, built_at=built, **kw)


class StoreCase(unittest.TestCase):
    def setUp(self):
        self._td = B.temp_dir()
        self.dir = self._td.__enter__()
        self.st = B.new_store(self.dir)

    def tearDown(self):
        self.st.release_server()
        self._td.__exit__(None, None, None)


class TestIngest(StoreCase):
    def test_stored_then_already_have(self):
        r = B.put_bundle(self.st, _b())
        self.assertEqual((r.ok, r.status), (True, "stored"))
        r2 = B.put_bundle(self.st, _b())
        self.assertEqual(r2.status, "already_have")
        cur = self.st.read_current(PK1)
        self.assertEqual(list(cur), ["2026-07-01_2026-07-31"])
        ent = cur["2026-07-01_2026-07-31"]
        raw = self.st.bundle_bytes(PK1, ent["file"])
        self.assertEqual(fsx.sha256_hex(raw), ent["sha256"])                 # 받은 바이트 그대로
        self.assertEqual(r.body()["sha256"], ent["sha256"])

    def test_replace_keeps_old_and_stale_kept(self):
        """S13: 10/5 빌드 저장 후 10/1 빌드 반입 → stale_kept, current 그대로, 10/1 파일은 보관."""
        new = _b(built="2026-10-05T09:00:00+09:00", seed=2)
        old = _b(built="2026-10-01T09:00:00+09:00", seed=3)
        first = _b(built="2026-09-01T09:00:00+09:00", seed=1)
        self.assertEqual(B.put_bundle(self.st, first).status, "stored")
        r = B.put_bundle(self.st, new)
        self.assertEqual((r.status, r.replaced), ("stored", B.sha(B.canon(first))[:12]))
        r = B.put_bundle(self.st, old)
        self.assertEqual(r.status, "stale_kept")
        cur = self.st.read_current(PK1)["2026-07-01_2026-07-31"]
        self.assertEqual(cur["sha256"], B.sha(B.canon(new)))
        files = sorted(os.listdir(self.st.bundles_dir(PK1)))
        self.assertEqual(len(files), 3)                                       # 옛 묶음 보관(historyKeep=5)
        self.assertTrue(self.st.current_json(PK1).with_name("current.json.bak").is_file())
        self.assertFalse([f for _r, _d, fs in os.walk(self.dir) for f in fs if f.endswith(".part")])

    def test_history_keep(self):
        st = B.new_store(self.dir / "h", **{"teamServer.historyKeep": 1})
        for k in range(4):
            B.put_bundle(st, _b(built=f"2026-08-0{k + 1}T09:00:00+09:00", seed=10 + k))
        self.assertEqual(len(os.listdir(st.bundles_dir(PK1))), 2)             # current + 옛 1

    def test_reject_codes_no_store(self):
        raw = B.canon(_b())
        cases = [
            ({"source": "http", "claimed_sha": None}, 400, "sha_missing"),
            ({"source": "http", "claimed_sha": "0" * 64}, 400, "sha_mismatch"),
        ]
        for kw, http, code in cases:
            r = T.ingest_bytes(self.st, raw, **kw)
            self.assertEqual((r.http, r.code), (http, code))
        for body, code in ((b"\xff\xfe", "bad_json"), (b'{"a":1,"a":2}', "dup_key"), (b"[1,2]", "not_object"),
                           (b'{"a": NaN}', "bad_json"), (b"\xef\xbb\xbf{}", "bad_json")):
            r = T.ingest_bytes(self.st, body, source="http", claimed_sha=fsx.sha256_hex(body))
            self.assertEqual((r.http, r.code), (400, code), body)
        self.assertEqual(self.st.member_keys(), [])

    def test_forbidden_content_bytes_guard(self):
        """U04: 빌더를 우회해 이메일이 든 묶음을 직접 → 422 forbidden_content, 저장 없음, 응답에 값 없음."""
        o = _b(title="회의 메모 a" + "@" + "team.example.com")
        r = B.put_bundle(self.st, o)
        self.assertEqual((r.http, r.code), (422, "forbidden_content"))
        self.assertNotIn("example", json.dumps(r.body(), ensure_ascii=False))
        self.assertEqual(self.st.member_keys(), [])

    def test_payload_check_violation_and_failure(self):
        self.st.payload_check = lambda _o: [("units[0].title", "label:not_clean")]
        r = B.put_bundle(self.st, _b())
        self.assertEqual((r.http, r.code), (422, "forbidden_content"))
        self.assertEqual(r.detail, ["units[0].title: forbidden_content"])

        def boom(_o):
            raise RuntimeError("x")
        self.st.payload_check = boom
        r = B.put_bundle(self.st, _b())
        self.assertEqual((r.http, r.code), (500, "store_failed"))             # fail-closed
        self.assertEqual(self.st.member_keys(), [])

    def test_integrity_rejected(self):
        """A03: alloc 합 > env 인 묶음 → 422 integrity."""
        o = _b()
        d, _u, t, _m = o["alloc_daily"]["rows"][0]
        env = next(r for r in o["envelope_daily"]["rows"] if r[0] == d)
        o["alloc_daily"]["rows"][0][3] = env[1 + B.TAGS.index(t)] + 1
        B.finalize(o)
        r = B.put_bundle(self.st, o)
        self.assertEqual((r.http, r.code), (422, "integrity"))

    def test_too_large(self):
        st = B.new_store(self.dir / "s", **{"teamServer.maxBodyMb": 1})
        raw = b'{"x":"' + b"a" * (1024 * 1024 + 10) + b'"}'
        r = T.ingest_bytes(st, raw, source="inbox:x", claimed_sha=None)
        self.assertEqual((r.http, r.code), (413, "too_large"))

    def test_warnings_recorded(self):
        r = B.put_bundle(self.st, _b(workdays_override={"2026-07": 23}))
        self.assertEqual(r.status, "stored")
        self.assertIn("calendar_mismatch", r.warnings)
        ent = self.st.read_current(PK1)["2026-07-01_2026-07-31"]
        self.assertIn("calendar_mismatch", ent["warn"])

    def test_log_has_no_values(self):
        B.put_bundle(self.st, _b(self_label="라벨ZQ"))
        logs = "".join(fsx.read_bytes(p).decode("utf-8") for p in self.st.logs_dir().iterdir())
        self.assertNotIn("라벨ZQ", logs)
        self.assertNotIn(str(self.dir), logs)
        self.assertIn(PK1, logs)


class TestRepair(StoreCase):
    def test_current_corrupt_bak_then_rebuild(self):
        """S08: current.json 을 [] 로 → .bak 복구, 그것도 깨지면 묶음에서 재구성. 다른 사람은 영향 없음."""
        B.put_bundle(self.st, _b(built="2026-08-01T09:00:00+09:00"))
        B.put_bundle(self.st, _b(built="2026-08-02T09:00:00+09:00", seed=9))
        B.put_bundle(self.st, _b(pk=PK2))
        cp = self.st.current_json(PK1)
        good = json.loads(fsx.read_bytes(cp))
        fsx.atomic_write(cp, b"[]")
        w = []
        cur = self.st.read_current(PK1, w)
        self.assertEqual(set(cur), {"2026-07-01_2026-07-31"})
        self.assertTrue(w and ".bak" in w[0])
        fsx.atomic_write(cp, b"{bad")
        fsx.atomic_write(cp.with_name("current.json.bak"), b"null")
        w = []
        cur = self.st.read_current(PK1, w)
        self.assertEqual(cur["2026-07-01_2026-07-31"]["sha256"], good["2026-07-01_2026-07-31"]["sha256"])
        self.assertIn("재구성", w[0])
        self.assertEqual(len(self.st.read_current(PK2)), 1)


class TestRegistry(StoreCase):
    def test_put_versions_and_pepper(self):
        """S07: version 현재+1 → 200, 같은 판 → 409. pepper 는 저장본에 없고 응답에만."""
        code, body = self.st.put_registry(B.registry(1))
        self.assertEqual((code, body["version"]), (200, 1))
        code, body = self.st.put_registry(B.registry(1))
        self.assertEqual((code, body["code"]), (409, "registry_version_conflict"))
        saved = json.loads(fsx.read_bytes(self.st.registry_json()))
        self.assertNotIn("pepper", saved)
        cl = self.st.registry_for_client()
        self.assertEqual(len(cl["pepper"]), 64)
        self.assertEqual(cl["pepper_id"], self.st.pepper_id)
        evil = B.registry(2)
        evil["pepper"] = "0" * 64
        self.assertEqual(self.st.put_registry(evil)[0], 200)
        self.assertNotEqual(self.st.registry_for_client()["pepper"], "0" * 64)    # PUT 으로 못 바꾼다
        self.assertTrue(self.st.registry_history(2).is_file())

    def test_put_validation(self):
        cyc = B.registry(1, projects=[
            {"id": "P-0003", "name": "과제C", "domain": "DEV", "merged_into": "P-0004"},
            {"id": "P-0004", "name": "과제D", "domain": "DEV", "merged_into": "P-0003"}])
        code, body = self.st.put_registry(cyc)
        self.assertEqual((code, body["code"]), (422, "cycle_merge"))
        for projects, want in (([{"id": "P-9901", "name": "x", "domain": "DEV"}], "reserved_id"),
                               ([{"id": "P-0001", "name": "x", "domain": "UNC"}], "bad_domain"),
                               ([{"id": "P-0001", "name": "과제 A", "domain": "DEV"},
                                 {"id": "P-0002", "name": "과제  a", "domain": "MP"}], "dup_alias"),
                               ([{"id": "P-1", "name": "x", "domain": "DEV"}], "bad_id")):
            code, body = self.st.put_registry(B.registry(1, projects=projects))
            self.assertEqual((code, body["code"]), (422, want), want)
        cal = {"version": "x", "std_day_min": 480, "weekdays": [0, 1, 2, 3, 4], "note": "",
               "years": [{"year": 2026, "holidays": [{"date": "2026-07-17", "name": "제헌절", "kind": "법정"}]}],
               "company_off": []}
        code, body = self.st.put_registry(B.registry(1, calendar_obj=cal))
        self.assertEqual((code, body["code"]), (422, "bad_holiday_source"))
        self.assertEqual(self.st.registry_version(), 0)

    def test_semantic_validator_called(self):
        st = B.new_store(self.dir / "v", validator=lambda o, side: [{"path": "vocab", "code": "bad_vocab",
                                                                    "blocking": side == "server"}])
        code, body = st.put_registry(B.registry(1))
        self.assertEqual((code, body["code"]), (422, "bad_vocab"))


    def test_validator_unavailable_fail_closed(self):
        import importlib.util
        st = T.TeamStore(self.dir / "nv", self.st.cfg, payload_check=B.pass_check).ensure()
        code, body = st.put_registry(B.registry(1))
        if importlib.util.find_spec("lm27.hier") is None:
            self.assertEqual((code, body["code"]), (422, "validator_unavailable"))
        else:
            self.assertIn(code, (200, 422))


class TestLogs(StoreCase):
    def test_cleanup_logs(self):
        for name in ("server_20200101.log", "aggregate_20200101.log", "server_29990101.log", "uploads.jsonl"):
            fsx.atomic_write(self.st.logs_dir() / name, b"x")
        self.assertEqual(self.st.cleanup_logs(30), 2)
        self.assertEqual(sorted(os.listdir(self.st.logs_dir())), ["server_29990101.log", "uploads.jsonl"])


class TestRosterMembers(StoreCase):
    def test_members_view_labels_and_patch(self):
        B.put_bundle(self.st, _b(member_id="M003", self_label="팀원A"))
        B.put_bundle(self.st, _b(pk=PK2, self_label=""))
        self.st.put_registry(B.registry(1))
        mv = {m["person_key"]: m for m in self.st.members_view()["members"]}
        self.assertEqual((mv[PK1]["label"], mv[PK1]["label_source"]), ("홍길동", "member"))
        self.assertEqual(mv[PK2]["label"], "팀원-" + PK2[2:6].upper())
        code, _ = self.st.patch_member(PK2, {"label": " 김철수​ ", "retired": True, "link_to": PK1})
        self.assertEqual(code, 200)
        mv = {m["person_key"]: m for m in self.st.members_view()["members"]}
        self.assertEqual((mv[PK2]["label"], mv[PK2]["retired"]), ("김철수", True))
        self.assertEqual(self.st.patch_member(PK2, {"link_to": "p_000000000000"})[0], 422)
        self.assertEqual(self.st.patch_member(PK2, {"owner": "x"})[0], 400)
        code, _ = self.st.patch_member(PK1, {"drop_period": "2026-07-01_2026-07-31"})
        self.assertEqual((code, self.st.read_current(PK1)), (200, {}))
        text = json.dumps(self.st.members_view(), ensure_ascii=False)
        self.assertNotIn(str(self.dir), text)
        for bad in ("pid", "root", "host", "token", "store"):
            self.assertNotIn(f'"{bad}"', text)

    def test_display_label_priority(self):
        roster = {"labels": {PK1: "라벨R"}}
        self.assertEqual(T.display_label(PK1, "M1", "S", roster, {"M1": "라벨M"}), ("라벨R", "roster"))
        self.assertEqual(T.display_label(PK2, "M1", "S", roster, {"M1": "라벨M"}), ("라벨M", "member"))
        self.assertEqual(T.display_label(PK2, None, "S", roster, {}), ("S", "self"))


class TestLock(StoreCase):
    def test_server_lock_exclusive_across_processes(self):
        self.assertTrue(self.st.lock_server())
        code = ("import sys; sys.path.insert(0, sys.argv[1]); from tests.fixtures.wp27 import bundles as B; "
                "st = B.new_store(sys.argv[2]); print('got' if st.lock_server() else 'busy')")
        r = subprocess.run([sys.executable, "-X", "utf8", "-B", "-c", code, str(B.TREE), str(self.dir)],
                           capture_output=True, timeout=60, check=False)
        self.assertEqual(r.stdout.decode().strip(), "busy", r.stderr.decode("utf-8", "replace")[-300:])
        self.st.release_server()
        r = subprocess.run([sys.executable, "-X", "utf8", "-B", "-c", code, str(B.TREE), str(self.dir)],
                           capture_output=True, timeout=60, check=False)
        self.assertEqual(r.stdout.decode().strip(), "got")

    def test_server_json_cleared_only_if_mine(self):
        self.st.write_server_json(pid=1234, port=19355, host="127.0.0.1", instance_id="aa", exe="python.exe")
        self.assertFalse(self.st.clear_server_json_if_mine(999, "aa"))
        self.assertTrue(self.st.clear_server_json_if_mine(1234, "aa"))
        self.assertIsNone(self.st.server_info())


class TestGens(StoreCase):
    def test_publish_and_prune(self):
        st = B.new_store(self.dir / "g", **{"teamServer.genKeep": 2})
        for g in range(1, 5):
            fsx.atomic_write(st.gen_dir(g) / "team_data.json", b"{}")
            st.publish_gen(g, {"members": 0, "warnings": []})
        self.assertEqual(st.current_gen()["gen"], 4)
        self.assertEqual(st.gens(), [3, 4])
        self.assertEqual(st.next_gen(), 5)
        self.assertEqual(st.current_file("team_data.json"), b"{}")
