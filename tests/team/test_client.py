# -*- coding: utf-8 -*-
"""WP-34 팀 클라이언트 — hello 판정(TAB §2.9 · 계약 §6.1 매핑)·보낼 곳(기본 주소 고정·대체 주소·사설 주소 규칙)·
레지스트리 받기(ETag·캐시 교체·오프라인 사본 채택 — O-14 ②)·업로드 토큰 보관·P-TEAM 탐침 값·L-21 기본 주소 단일원.
시험 서버는 127.0.0.1 의 시험 전용 포트(19400~19449)만 쓴다."""
import os
import socket
import tempfile
import unittest

from lm27.team import client as C
from lm27.team import schema as S
from lm27.util import events, fsx
from tests.fixtures.wp34 import servers as SV
from tests.fixtures.wp34 import world as W


def _cfg(port, **over):
    # 연결 시간 제한은 기본값(4초) 그대로 — Windows 루프백의 '연결 거부'는 재시도 때문에 약 2초 뒤에 온다(실측)
    ov = {"team.serverHost": SV.HOST, "team.serverPort": port}
    ov.update(over)
    return W.cfg(**ov)


class _Quiet(unittest.TestCase):
    def setUp(self):
        self._mode = events.mode()
        events.configure("off")

    def tearDown(self):
        events.configure(self._mode)


class TestDefaultAddress(unittest.TestCase):
    def test_l21_default_url_matches_registry_defaults(self):
        """L-21 · CR-13: DEFAULT_TEAM_URL(client.py 한 곳) = 설정 레지스트리 team.serverHost·serverPort 기본값(바이트 일치)."""
        from lm27.config import registry_meta
        host = registry_meta("team.serverHost", path=W.TREE / "config" / "settings_registry.json").default
        port = registry_meta("team.serverPort", path=W.TREE / "config" / "settings_registry.json").default
        self.assertEqual(C.DEFAULT_TEAM_URL, f"http://{host}:{port}")
        self.assertEqual((C.DEFAULT_HOST, C.DEFAULT_PORT), (host, port))
        c = W.cfg()
        ts, notes = C.targets(c)
        self.assertEqual(ts[0].base, C.DEFAULT_TEAM_URL)
        self.assertEqual((ts[0].name, notes), ("primary", []))


class TestAddressRules(unittest.TestCase):
    def test_split_hostport(self):
        self.assertEqual(C.split_hostport("127.0.0.1:19400"), ("127.0.0.1", 19400))
        self.assertEqual(C.split_hostport("[::1]:9"), ("::1", 9))
        self.assertEqual(C.split_hostport("nohost"), ("", None))
        self.assertEqual(C.split_hostport("h:x"), ("", None))

    def test_host_allowed_private_and_loopback_only(self):
        """TAB §7.1: allowPublicHost=false 면 사설 IPv4(10/8·172.16/12·192.168/16)·루프백만, 호스트 이름 불가."""
        p10 = ".".join(("10", "1", "2", "3"))
        p172 = ".".join(("172", "20", "0", "5"))
        p192 = ".".join(("192", "168", "7", "8"))
        pub = ".".join(("203", "0", "113", "9"))
        for h in (p10, p172, p192, "127.0.0.1", "::1"):
            self.assertTrue(C.host_allowed(h, False), h)
        for h in (pub, "team.example.com", ".".join(("172", "40", "0", "1")), ""):
            self.assertFalse(C.host_allowed(h, False), h)
        self.assertTrue(C.host_allowed(pub, True))
        self.assertTrue(C.host_allowed("team.example.com", True))

    def test_targets_order_and_skips(self):
        c = W.cfg(**{"team.serverHost": "127.0.0.1", "team.serverPort": 19401,
                     "team.serverAlternates": ["team.example.com:9310", "127.0.0.1:19402", "[::1]:19403"]})
        ts, notes = C.targets(c)
        self.assertEqual([t.name for t in ts], ["primary", "alt2", "alt3"])
        self.assertEqual(ts[2].base, "http://[::1]:19403")
        self.assertEqual(len(notes), 1)
        self.assertNotIn("example", notes[0])                        # 사유 문구에 주소를 싣지 않는다
        self.assertEqual(C.base_of("::1", 5), "http://[::1]:5")


class TestHello(_Quiet):
    def test_ok_and_info_allowlist(self):
        with SV.fake_team("lm27") as fs:
            h = C.hello(f"http://{SV.HOST}:{fs.port}", 2)
        self.assertTrue(h.ok)
        self.assertEqual((h.result, h.reason), ("ok", None))
        self.assertTrue(h.accepts_v1)
        self.assertNotIn("instance_id", h.info)
        self.assertNotIn("store_id", h.info)
        self.assertNotIn("server_time", h.info)

    def test_lm24_shape_is_read_and_dropped(self):
        """U06 판정: /api/hello 404 + /api/whoami 의 root 키 → lm24. 그 응답 값(경로·토큰)은 결과에 남지 않는다."""
        with SV.fake_team("lm24") as fs:
            h = C.hello(f"http://{SV.HOST}:{fs.port}", 2)
            self.assertIn("/api/whoami", fs.gets)
        self.assertEqual((h.result, h.reason), ("lm24", S.HELLO_REASON["lm24"]))
        self.assertEqual(h.info, {})
        self.assertNotIn("CANARY", repr(vars(h)))
        self.assertIn("LM24", h.text_ko)

    def test_other_lm_other_app_wrong_major(self):
        cases = (("other_lm", "other_lm"), ("other_app", "other_app"), ("v2", "wrong_major"))
        for mode, want in cases:
            with SV.fake_team(mode) as fs:
                h = C.hello(f"http://{SV.HOST}:{fs.port}", 2)
            self.assertEqual(h.result, want, mode)
            self.assertEqual(h.reason, S.HELLO_REASON[want])
            self.assertFalse(h.ok)

    def test_refused(self):
        h = C.hello(f"http://{SV.HOST}:{SV.dead_port()}", 4)
        self.assertEqual((h.result, h.reason), ("refused", S.HELLO_REASON["refused"]))
        self.assertNotIn("127.0.0.1", h.text_ko)

    def test_timeout(self):
        """연결은 되지만 답이 없는 상대 → timeout(방화벽·망 분리 의심 문구)."""
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        port = None
        for p in reversed(SV.PORTS):
            try:
                s.bind((SV.HOST, p))
                port = p
                break
            except OSError:
                continue
        s.listen(5)
        try:
            h = C.hello(f"http://{SV.HOST}:{port}", 1)
        finally:
            s.close()
        self.assertEqual(h.result, "timeout")
        self.assertIn("방화벽", h.text_ko)

    def test_proxy_header(self):
        with SV.fake_team("other_app") as fs:
            fs.via = True
            h = C.hello(f"http://{SV.HOST}:{fs.port}", 2)
        self.assertEqual((h.result, h.reason), ("proxy", S.HELLO_REASON["proxy"]))

    def test_err_kind(self):
        self.assertEqual(C._err_kind(socket.gaierror(11001, "x")), "dns")
        self.assertEqual(C._err_kind(TimeoutError()), "timeout")
        self.assertEqual(C._err_kind(ConnectionRefusedError()), "refused")
        self.assertEqual(C._err_kind("timed out"), "timeout")


class TestPickTarget(_Quiet):
    def test_u13_alternates_in_order_settings_unchanged(self):
        """U13: 기본 = LM24 흉내, 대체 1 = 응답 없음(거부), 대체 2 = LM27 → 대체 2. 설정 값은 바뀌지 않는다."""
        with SV.fake_team("lm24") as old, SV.fake_team("lm27") as new:
            c = _cfg(old.port, **{"team.serverAlternates": [f"{SV.HOST}:{SV.dead_port()}", f"{SV.HOST}:{new.port}"]})
            tgt, h, pick = C.pick_target(c)
            self.assertEqual(tgt.name, "alt2")
            self.assertTrue(h.ok)
            self.assertEqual([r for _t, r in pick.results], ["lm24", "refused", "ok"])
            self.assertEqual((c["team.serverHost"], c["team.serverPort"]), (SV.HOST, old.port))
            self.assertEqual(old.posts, [])

    def test_all_unreachable_vs_other_server(self):
        c = _cfg(SV.dead_port())
        tgt, h, pick = C.pick_target(c)
        self.assertIsNone(tgt)
        self.assertTrue(pick.all_unreachable)
        self.assertFalse(pick.other_server)
        with SV.fake_team("other_app") as fs:
            tgt, _h, pick = C.pick_target(_cfg(fs.port))
        self.assertIsNone(tgt)
        self.assertFalse(pick.all_unreachable)
        self.assertTrue(pick.other_server)
        self.assertIn("기본 주소", pick.describe_ko())

    def test_reach_probe_value(self):
        """P-TEAM(계약 §6.7): 값에 주소 없이 대상 이름·판정·ms, 연결 실패는 transport_fail(확정 근거 아님)."""
        with SV.fake_team("lm27") as fs:
            r = C.reach(_cfg(fs.port))
        self.assertEqual((r["ok"], r["status"], r["value"]["target"], r["value"]["result"]), (True, "ok", "primary", "ok"))
        r = C.reach(_cfg(SV.dead_port()))
        self.assertEqual((r["ok"], r["status"], r["reasons"]), (False, "transport_fail", [S.HELLO_REASON["refused"]]))
        with SV.fake_team("lm24") as fs:
            r = C.reach(_cfg(fs.port))
        self.assertEqual((r["status"], r["reasons"]), ("fail", [S.HELLO_REASON["lm24"]]))


class TestToken(unittest.TestCase):
    def setUp(self):
        self.w = W.World()

    def tearDown(self):
        self.w.cleanup()

    def test_secrets_roundtrip_and_fp(self):
        p = self.w.paths
        self.assertIsNone(C.upload_token(p))
        self.assertEqual(C.token_state(p), "없음")
        self.assertTrue(C.set_upload_token(p, "tok-wp34"))
        self.assertFalse(C.set_upload_token(p, "tok-wp34"))
        self.assertEqual(C.upload_token(p), "tok-wp34")
        self.assertEqual(C.token_state(p), "설정됨")
        obj = fsx.read_json(p.secrets(), None)
        self.assertEqual(obj["schema"], C.SECRETS_SCHEMA)
        fp = C.token_fp("tok-wp34")
        self.assertEqual(len(fp), 8)
        self.assertNotIn("tok", fp)
        self.assertNotEqual(fp, C.token_fp("tok-other"))
        self.assertEqual(C.token_fp(None), "")
        self.assertTrue(C.set_upload_token(p, None))
        self.assertIsNone(C.upload_token(p))


class TestRegistry(_Quiet):
    def setUp(self):
        super().setUp()
        self.w = W.World(with_registry=False)

    def tearDown(self):
        self.w.cleanup()
        super().tearDown()

    def test_fetch_registry_http_only(self):
        with SV.fake_team("lm27") as fs:
            fs.registry = W.registry(version=5)
            base = f"http://{SV.HOST}:{fs.port}"
            r = C.fetch_registry(base, None, timeout=2)
            self.assertEqual((r.status, r.obj["version"], r.etag), (200, 5, '"5"'))
            r2 = C.fetch_registry(base, '"5"', timeout=2)
            self.assertEqual((r2.status, r2.obj), (304, None))
        self.assertFalse(os.path.exists(self.w.paths.registry_cache()))         # HTTP 만 — 파일을 쓰지 않는다

    def test_refresh_saves_cache_and_etag_then_fresh(self):
        """O-14 ② 결정: 저장 주체 = refresh_registry(캐시 원자 교체 + ETag). 주기 안이면 묻지 않는다(rc 4)."""
        p = self.w.paths
        with SV.fake_team("lm27") as fs:
            fs.registry = W.registry(version=5)
            c = _cfg(fs.port)
            r = C.refresh_registry(p, c, force=True)
            self.assertEqual((r.rc, r.status, r.version, r.source, r.saved), (0, 200, 5, "server", True))
            self.assertEqual(fsx.read_json(p.registry_cache(), None)["pepper"], W.PEPPER)
            self.assertEqual(fsx.read_bytes(p.registry_etag()), b'"5"')
            n = len(fs.gets)
            r = C.refresh_registry(p, c)
            self.assertEqual((r.rc, r.source), (4, "cache"))
            self.assertEqual(len(fs.gets), n)                               # 서버에 묻지 않았다
            r = C.refresh_registry(p, c, force=True)
            self.assertEqual((r.rc, r.status), (0, 200))                    # force = ETag 없이 새로 받음
            fs.registry = W.registry(version=6)
            r = C.refresh_registry(p, c, force=True)
            self.assertEqual((r.rc, r.version), (0, 6))

    def test_refresh_rejects_bad_registry(self):
        p = self.w.paths
        with SV.fake_team("lm27") as fs:
            bad = W.registry(version=5)
            bad["pepper"] = "zz"
            fs.registry = bad
            r = C.refresh_registry(p, _cfg(fs.port), force=True)
        self.assertEqual((r.rc, r.saved), (2, False))
        self.assertFalse(os.path.exists(p.registry_cache()))

    def test_offline_copy_adopted_when_unreachable(self):
        """TAB §5.3 · WP-21 요청: 서버에 닿지 않고 공유폴더 사본의 판이 캐시보다 크면 캐시로 채택."""
        p = self.w.paths
        off = tempfile.mkdtemp(prefix="lm27t_wp34_off_")
        try:
            fsx.atomic_write(os.path.join(off, "lm27_registry.json"), fsx.canon_bytes(W.registry(version=9)))
            c = _cfg(SV.dead_port(), **{"team.offlineDir": off})
            r = C.refresh_registry(p, c, force=True)
            self.assertEqual((r.rc, r.source, r.version, r.saved), (0, "offline", 9, True))
            self.assertFalse(C.adopt_offline(p, c))                         # 같은 판은 다시 채택하지 않는다
        finally:
            import shutil
            shutil.rmtree(off, ignore_errors=True)

    def test_registry_fetcher_for_load_effective(self):
        """H §3.1: load_effective(fetch=…) — 200 이면 팀 클라이언트가 캐시를 교체하고 유효 레지스트리 출처 = server."""
        from lm27.hier.registry import load_effective
        p = self.w.paths
        with SV.fake_team("lm27") as fs:
            fs.registry = W.registry(version=7)
            c = _cfg(fs.port)
            reg, st = load_effective(p, c, fetch=C.registry_fetcher(p, c), persist=False)
        self.assertEqual((st.source, reg.version), ("server", 7))
        self.assertEqual(fsx.read_json(p.registry_cache(), None)["version"], 7)
        reg, st = load_effective(p, _cfg(SV.dead_port()), fetch=C.registry_fetcher(p, _cfg(SV.dead_port())),
                                 persist=False)
        self.assertEqual(st.source, "cache")
        self.assertTrue(any(w.startswith("server_unreachable") for w in st.warnings))

    def test_registry_fetcher_adopts_newer_offline_copy(self):
        """닿지 않을 때 공유폴더 사본(판 9 > 캐시 판 3)을 팀 클라이언트가 캐시로 옮긴다 — 적재기는 그 캐시를 읽는다."""
        from lm27.hier.registry import load_effective
        p = self.w.paths
        fsx.atomic_write(p.registry_cache(), fsx.canon_bytes(W.registry(version=3)))
        off = tempfile.mkdtemp(prefix="lm27t_wp34_off_")
        try:
            fsx.atomic_write(os.path.join(off, "lm27_registry.json"), fsx.canon_bytes(W.registry(version=9)))
            c = _cfg(SV.dead_port(), **{"team.offlineDir": off})
            reg, _st = load_effective(p, c, fetch=C.registry_fetcher(p, c), persist=False)
            self.assertEqual(reg.version, 9)
            self.assertEqual(fsx.read_json(p.registry_cache(), None)["version"], 9)
            self.assertEqual(fsx.read_bytes(p.registry_etag()), b'"9"')
        finally:
            import shutil
            shutil.rmtree(off, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
