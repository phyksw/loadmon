# -*- coding: utf-8 -*-
"""WP-27 팀 서버 업로드·기동 — 미리보기=실전송 sha·초과 본문·동시 업로드·토큰·혼잡·악성 라벨·배타 바인드·포트 점유 진단·
재취합 하위 프로세스(TAB §3.3·§3.4·§3.8·§3.9, TAB-S02 · S03 · S04 · S05 · S06 · U01 · U04 · U08). 같은 프로세스 시험 서버.
"""
import contextlib
import hashlib
import io
import json
import os
import socket
import threading
import time
import unittest

from lm27.team import aggregate as A
from lm27.team import portdiag, server
from lm27.util import fsx
from tests.fixtures.wp27 import bundles as B
from tests.fixtures.wp27.helpers import LM24_ROUTES, fake_server, free_port, http, running_server

PKS = [B.person_key(n) for n in range(1, 5)]


def _b(pk=PKS[0], d0="2026-07-01", d1="2026-07-31", built="2026-08-01T09:00:00+09:00", **kw):
    return B.make_bundle(pk, d0, d1, built_at=built, **kw)


class UploadCase(unittest.TestCase):
    over: dict = {}

    def setUp(self):
        self._td = B.temp_dir()
        self.dir = self._td.__enter__()
        self.runs = []

        def runner(st, gen):
            self.runs.append(gen)
            return A.aggregate(st, gen)
        self._cm = running_server(self.dir, runner=runner, **self.over)
        self.ts = self._cm.__enter__()

    def tearDown(self):
        self._cm.__exit__(None, None, None)
        self._td.__exit__(None, None, None)


class TestUpload(UploadCase):
    def test_u01_sent_equals_stored_sha_and_idempotent(self):
        raw = B.canon(_b())
        code, obj, _ = self.ts.post_bundle(raw)
        self.assertEqual((code, obj["status"]), (200, "stored"))
        self.assertEqual(obj["sha256"], B.sha(raw))
        ent = self.ts.store.read_current(PKS[0])["2026-07-01_2026-07-31"]
        self.assertEqual(fsx.sha256_hex(self.ts.store.bundle_bytes(PKS[0], ent["file"])), B.sha(raw))
        self.assertEqual(obj["aggregate"]["state"], "done")
        code, obj, _ = self.ts.post_bundle(raw)
        self.assertEqual((code, obj["status"]), (200, "already_have"))

    def test_sha_header_rules(self):
        raw = B.canon(_b())
        code, obj, _ = self.ts.post_bundle(raw, sha="")
        self.assertEqual((code, obj["code"]), (400, "sha_missing"))
        code, obj, _ = self.ts.post_bundle(raw, sha="0" * 64)
        self.assertEqual((code, obj["code"]), (400, "sha_mismatch"))

    def test_u04_forbidden_content_no_value_in_response(self):
        o = _b(title="메모 x" + "@" + "team.example.com")
        code, obj, _ = self.ts.post_bundle(o)
        self.assertEqual((code, obj["code"]), (422, "forbidden_content"))
        self.assertNotIn("example", json.dumps(obj, ensure_ascii=False))
        self.assertEqual(self.ts.store.member_keys(), [])

    def test_s06_malicious_label(self):
        """S06: 정제 라벨 위반이면 422(값 없음). 통과하는 변형은 저장되고 JSON 응답으로만 나간다(nosniff)."""
        evil = "</script><script>"
        self.ts.store.payload_check = lambda o: [("person.self_label", "label:not_clean")] if "<" in \
            o["person"]["self_label"] else []
        code, obj, _ = self.ts.post_bundle(_b(self_label=evil))
        self.assertEqual((code, obj["code"]), (422, "forbidden_content"))
        self.assertNotIn("script", json.dumps(obj))
        self.ts.store.payload_check = B.pass_check
        code, obj, _ = self.ts.post_bundle(_b(self_label=evil))
        self.assertEqual(code, 200)
        code, td, hdr = self.ts.call("GET", "/api/team")
        self.assertEqual(hdr["Content-Type"], "application/json; charset=utf-8")
        self.assertEqual(hdr["X-Content-Type-Options"], "nosniff")
        self.assertEqual(td["people"][0]["label"], evil)                            # 데이터 그대로(렌더러가 textContent)

    def test_busy_429(self):
        sem = self.ts.app.upload_sem
        held = 0
        while sem.acquire(blocking=False):
            held += 1
        try:
            code, obj, hdr = self.ts.post_bundle(_b())
            self.assertEqual((code, obj["code"], hdr["Retry-After"]), (429, "busy", "30"))
        finally:
            for _ in range(held):
                sem.release()


class TestOversize(UploadCase):
    over = {"teamServer.maxBodyMb": 1}

    def test_s04_413_arrives(self):
        """S04: 상한 초과 본문(3MB) — 본문을 읽고(drain) 413 을 돌려준다(RST 아님)."""
        big = b'{"x":"' + b"a" * (3 * 1024 * 1024) + b'"}'
        code, obj, _ = self.ts.post_bundle(big)
        self.assertEqual((code, obj["code"]), (413, "too_large"))
        self.assertEqual(self.ts.call("GET", "/api/hello")[0], 200)


class TestConcurrent(UploadCase):
    over = {"teamServer.maxConcurrentUploads": 16, "teamServer.aggregateDebounceSec": 1,
            "teamServer.aggregateWaitSec": 10}

    def test_s05_concurrent(self):
        """S05: 같은 사람 2기간 × 3변형 + 다른 사람 3건 동시 → current 일관(기간마다 built_at 최신), 손상·.part 0, 재취합 1~2회."""
        raws = []
        for k in range(3):
            raws.append(B.canon(_b(built=f"2026-10-0{k + 1}T09:00:00+09:00", seed=10 + k)))
            raws.append(B.canon(_b(d0="2026-08-01", d1="2026-08-31", built=f"2026-10-0{k + 1}T09:00:00+09:00",
                                   seed=20 + k)))
        for k in range(3):
            raws.append(B.canon(_b(pk=PKS[k + 1], seed=30 + k)))
        res = [None] * len(raws)

        def send(i):
            res[i] = self.ts.post_bundle(raws[i])[:2]
        ths = [threading.Thread(target=send, args=(i,)) for i in range(len(raws))]
        for t in ths:
            t.start()
        for t in ths:
            t.join(60)
        self.assertTrue(all(r[0] == 200 for r in res), [r[0] for r in res])
        cur = self.ts.store.read_current(PKS[0])
        self.assertEqual(sorted(cur), ["2026-07-01_2026-07-31", "2026-08-01_2026-08-31"])
        self.assertEqual(cur["2026-07-01_2026-07-31"]["sha256"], B.sha(raws[4]))     # 10-03 빌드가 남는다
        self.assertEqual(cur["2026-08-01_2026-08-31"]["sha256"], B.sha(raws[5]))
        for pk in PKS:
            for ent in self.ts.store.read_current(pk).values():
                self.assertEqual(fsx.sha256_hex(self.ts.store.bundle_bytes(pk, ent["file"])), ent["sha256"])
        self.assertFalse([f for _r, _d, fs in os.walk(self.dir) for f in fs if f.endswith(".part")])
        deadline = time.time() + 15
        while self.ts.app.agg.status()["state"] in ("queued", "running") and time.time() < deadline:
            time.sleep(0.1)
        self.assertIn(len(self.runs), (1, 2), self.runs)
        self.assertEqual(self.ts.store.current_gen()["members"], 4)


class TestUploadToken(UploadCase):
    over = {"teamServer.uploadTokenSha256": hashlib.sha256(b"up-tok").hexdigest()}

    def test_u08_tokens(self):
        code, obj, _ = self.ts.post_bundle(_b())
        self.assertEqual((code, obj["code"]), (401, "token_required"))
        code, obj, _ = self.ts.post_bundle(_b(), headers={"X-LM27-Upload-Token": "nope"})
        self.assertEqual((code, obj["code"]), (401, "token_invalid"))
        code, obj, _ = self.ts.post_bundle(_b(), headers={"X-LM27-Upload-Token": "up-tok"})
        self.assertEqual(code, 200)
        self.assertTrue(self.ts.call("GET", "/api/hello")[1]["auth"]["upload"])


class TestBindAndServe(unittest.TestCase):
    def test_s03_exclusive_bind(self):
        with B.temp_dir() as d, running_server(d) as ts:
            for opt in (socket.SO_REUSEADDR, None):
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                try:
                    if opt is not None:
                        s.setsockopt(socket.SOL_SOCKET, opt, 1)
                    with self.assertRaises(OSError) as cm:
                        s.bind(("127.0.0.1", ts.port))
                    self.assertIn(portdiag.winerror_of(cm.exception), (10013, 10048))
                finally:
                    s.close()
            self.assertFalse(server.LM27HTTPServer.allow_reuse_address)

    def test_s02_lm24_occupies_port(self):
        """S02: 시험 포트에 LM24 흉내 → rc 3, kind lm24, 프로세스 이름 표시, 대체 포트 제안(회피 대역·임시 범위 밖), 자동 전환 없음."""
        portdiag.clear_cache()
        with B.temp_dir() as d, fake_server(LM24_ROUTES) as port:
            st = B.new_store(d, **{"teamServer.bindHost": "127.0.0.1", "teamServer.bindPort": port})
            fake_exe = os.path.join(str(d), "python.exe")
            pid = os.getpid()

            def run(argv, timeout):
                cmd = " ".join(argv).lower()
                if "netstat" in cmd:
                    return 0, f"  TCP    127.0.0.1:{port}   0.0.0.0:0   LISTENING   {pid}\r\n".encode()
                if "get-ciminstance" in cmd:
                    return 0, json.dumps({"ProcessId": pid, "Name": "python.exe", "ExecutablePath": fake_exe}).encode()
                if "dynamicport" in cmd:
                    return 0, b"Start Port      : 1024\r\nNumber of Ports : 13977\r\n"
                if "excludedportrange" in cmd:
                    return 0, b"\r\n"
                return None

            def diag(p, c, cfg, sid):
                return portdiag.diagnose_port(p, c, cfg, store_id=sid, run=run,
                                              bind=lambda q: q not in portdiag.AVOID)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = server.serve(st.cfg, store=st, diag=diag)
            self.assertEqual(rc, 3)
            pd = json.loads(fsx.read_bytes(st.run_file("port_diag.json")))
            self.assertEqual(pd["kind"], "lm24")
            self.assertEqual(pd["procs"][0]["name"], "python.exe")
            self.assertEqual(pd["suggest"], 19310)
            self.assertNotIn(pd["suggest"], portdiag.AVOID)
            self.assertIn("python.exe", out.getvalue())
            self.assertIn("LM24", pd["message"])
            self.assertEqual(st.cfg["teamServer.bindPort"], port)                    # 설정 불변(몰래 바꾸지 않음)
            self.assertIsNone(st.server_info())
            self.assertTrue(st.lock_server())                                         # 잠금은 풀렸다
            st.release_server()

    def test_serve_lifecycle_and_shutdown(self):
        """serve: 저장소 잠금 → server.json → 로컬 /api/shutdown → rc 0, server.json 정리, 같은 저장소 두 번째 서버 rc 3."""
        with B.temp_dir() as d:
            port = free_port()
            st = B.new_store(d, **{"teamServer.bindHost": "127.0.0.1", "teamServer.bindPort": port})
            box = {}
            ready = threading.Event()

            def on_ready(srv):
                box["srv"] = srv
                ready.set()
            t = threading.Thread(target=lambda: box.setdefault("rc", server.serve(
                st.cfg, store=st, runner=lambda s, g: A.aggregate(s, g), ready=on_ready)), daemon=True)
            with contextlib.redirect_stdout(io.StringIO()):
                t.start()
                self.assertTrue(ready.wait(30))
                info = st.server_info()
                self.assertEqual((info["port"], info["pid"]), (port, os.getpid()))
                st2 = B.new_store(d)
                self.assertEqual(server.serve(st2.cfg, store=st2), 3)                 # 이 저장소를 이미 쓰는 서버
                code, obj, _ = http("POST", f"http://127.0.0.1:{port}/api/shutdown", b"{}",
                                    {"Content-Type": "application/json"})
                self.assertEqual((code, obj["stopping"]), (200, True))
                t.join(30)
            self.assertEqual(box.get("rc"), 0)
            self.assertIsNone(st.server_info())

    def test_subprocess_aggregate_runner(self):
        """재취합 하위 프로세스(lm27 team-aggregate --store D --gen N) — 서버는 result.json 만 읽는다."""
        with B.temp_dir() as d:
            st = B.new_store(d)
            B.put_bundle(st, _b())
            res = server.subprocess_runner(st, 1, st.cfg)
            self.assertTrue(res["ok"], res)
            self.assertEqual(res["members"], 1)
            self.assertTrue((st.gen_dir(1) / "team_data.json").is_file())


_SLOW_AGG = r'''
import os, sys, time
store = sys.argv[sys.argv.index("--store") + 1]
with open(os.path.join(store, "agg_child.pid"), "w", encoding="utf-8") as f:
    f.write(str(os.getpid()))
time.sleep(60)
'''


class TestShutdownStopsAggregate(unittest.TestCase):
    """C22 회귀: 재취합 자식(team-aggregate)이 도는 중에 서버를 끄면 자식 트리를 끝내고 워커를 합류한다(예전: 자식이 고아로
    남아 잠금을 놓은 저장소의 같은 세대에 덮어썼다). 끄는 데 오래 걸리지 않는다."""

    def _store(self, d, **over):
        import sys

        from lm27.paths import Paths
        cli = d / "slow_agg.py"
        cli.write_text(_SLOW_AGG, encoding="utf-8")

        class FPaths(Paths):
            def cli_script(self):
                return cli

            def python_exe(self):
                from pathlib import Path
                return Path(sys.executable)

        from lm27.team.store import open_store
        cfg = B.test_cfg(d / "store", **{"teamServer.aggregateDebounceSec": 0, **over})
        return open_store(cfg, payload_check=B.pass_check, registry_validator=lambda _o, side: [],
                          paths=FPaths(B.TREE))

    def _child(self, st, timeout=20):
        pidf = st.dir / "agg_child.pid"
        t0 = time.monotonic()
        while not pidf.is_file() and time.monotonic() - t0 < timeout:
            time.sleep(0.05)
        return int(pidf.read_text(encoding="utf-8"))

    def test_close_kills_running_aggregate_child(self):
        from lm27.util import proc
        with B.temp_dir() as d:
            st = self._store(d)
            srv = server.TeamServer(st.cfg, st, host="127.0.0.1", port=free_port(), inbox=False,
                                    maintenance=False).bind().start()
            try:
                srv.app.agg.request()
                pid = self._child(st)
                self.addCleanup(lambda: proc.pid_alive(pid) and proc.kill_tree(pid))
                self.assertTrue(proc.pid_alive(pid))
                t0 = time.monotonic()
                srv.shutdown()
                srv.close()
                self.assertLess(time.monotonic() - t0, 15)
                self.assertFalse(proc.pid_alive(pid), "재취합 자식이 고아로 남지 않는다")
                self.assertFalse(srv.app.agg.thread.is_alive(), "워커 스레드 합류")
                self.assertEqual(srv.app.agg.status()["state"], "failed")
                self.assertIsNone(st.current_gen(), "멈춘 재취합은 세대를 내지 않는다")
            finally:
                srv.shutdown()
                srv.close()

    def test_serve_shutdown_ends_child_before_lock_release(self):
        from lm27.util import proc
        with B.temp_dir() as d:
            port = free_port()
            st = self._store(d, **{"teamServer.bindHost": "127.0.0.1", "teamServer.bindPort": port})
            box, ready = {}, threading.Event()

            def on_ready(srv):
                box["srv"] = srv
                srv.app.agg.request()
                ready.set()
            t = threading.Thread(target=lambda: box.setdefault("rc", server.serve(st.cfg, store=st, ready=on_ready)),
                                 daemon=True)
            with contextlib.redirect_stdout(io.StringIO()):
                t.start()
                self.assertTrue(ready.wait(30))
                pid = self._child(st)
                self.addCleanup(lambda: proc.pid_alive(pid) and proc.kill_tree(pid))
                code, obj, _ = http("POST", f"http://127.0.0.1:{port}/api/shutdown", b"{}",
                                    {"Content-Type": "application/json"})
                self.assertEqual(code, 200)
                t.join(30)
            self.assertEqual(box.get("rc"), 0)
            self.assertFalse(proc.pid_alive(pid), "serve 가 끝나 잠금을 놓을 때 재취합 자식은 이미 끝났다")
            self.assertTrue(st.lock_server(), "잠금이 풀렸다")
            st.release_server()
