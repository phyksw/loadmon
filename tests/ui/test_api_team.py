# -*- coding: utf-8 -*-
"""RPT-43 팀 주소(R §5.5.1) — ① 공개 IP(allowPublicHost=false) 저장 거부 ② 포트 70000 거부 ③ [기본값으로] 정확히 기본 주소
④ 토큰 저장 뒤 응답에 토큰 값 없음. 연결 확인은 가짜 hello(네트워크 0)."""
import json
import unittest

from lm27.util import fsx
from tests.fixtures.wp35.harness import Running, Sandbox

DEFAULT_HOST, DEFAULT_PORT = "10.115.147.68", 9310          # 팀 서버 기본 주소(사용자 지시 고정값 — 기본값 대조 시험, CR-14)


class TeamAddressTest(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()
        self.addCleanup(self.sb.cleanup)
        self.app = self.sb.app()
        self.srv = Running(self.app).__enter__()
        self.addCleanup(self.srv.close)

    def _cfg_json(self):
        return fsx.read_json(self.sb.paths.config_json(), {}) or {}

    def test_rpt43_public_ip_rejected(self):
        st, b, _ = self.srv.req("PUT", "/api/team/settings", {"server_host": "8.8.8.8", "server_port": 9310})
        self.assertEqual(st, 400)
        self.assertEqual(b["code"], "invalid")
        self.assertEqual(b["detail"][0]["field"], "server_host")
        self.assertIn("사설", b["detail"][0]["error"])
        self.assertNotIn("team.serverHost", self._cfg_json())          # 저장하지 않음
        st, b, _ = self.srv.req("PUT", "/api/team/settings", {"server_host": "team.example.com"})
        self.assertEqual(st, 400)
        self.assertIn("호스트 이름", b["detail"][0]["error"])

    def test_rpt43_port_out_of_range(self):
        st, b, _ = self.srv.req("PUT", "/api/team/settings", {"server_port": 70000})
        self.assertEqual(st, 400)
        self.assertEqual(b["detail"][0]["field"], "server_port")
        st, b, _ = self.srv.req("PUT", "/api/team/settings", {"server_port": "9310"})
        self.assertEqual(st, 400)

    def test_rpt43_reset_address_exact(self):
        st, b, _ = self.srv.req("PUT", "/api/team/settings", {"server_host": "127.0.0.1", "server_port": 9311})
        self.assertEqual(st, 200, b)
        self.assertEqual(self._cfg_json()["team.serverHost"], "127.0.0.1")
        st, b, _ = self.srv.req("POST", "/api/team/settings/reset-address", {})
        self.assertEqual(st, 200)
        self.assertEqual(f"{b['server_host']}:{b['server_port']}", f"{DEFAULT_HOST}:{DEFAULT_PORT}")
        st, s, _ = self.srv.req("GET", "/api/team/status")
        self.assertEqual(s["settings"]["server_host"], DEFAULT_HOST)
        self.assertEqual(s["settings"]["server_port"], DEFAULT_PORT)
        self.assertNotIn("team.serverHost", self._cfg_json())

    def test_rpt43_token_not_echoed(self):
        tok = "tk-" + "a1b2" * 8
        st, b, _ = self.srv.req("POST", "/api/team/token", {"token": tok})
        self.assertEqual(st, 200)
        self.assertNotIn(tok, json.dumps(b, ensure_ascii=False))
        self.assertTrue(b["token_set"])
        st, s, _ = self.srv.req("GET", "/api/team/status")
        self.assertEqual(st, 200)
        self.assertNotIn(tok, json.dumps(s, ensure_ascii=False))
        self.assertTrue(s["settings"]["token_set"])
        st, s, _ = self.srv.req("GET", "/api/settings")
        self.assertNotIn(tok, json.dumps(s, ensure_ascii=False))
        sec = fsx.read_json(self.sb.paths.secrets(), None)
        self.assertEqual(sec["team"]["upload_token"], tok)              # 값은 data\keys\secrets.json 에만

    def test_alternates_and_label(self):
        st, b, _ = self.srv.req("PUT", "/api/team/settings", {"server_alternates": ["127.0.0.1:9312", "8.8.4.4:9310"]})
        self.assertEqual(st, 400)
        self.assertIn("2번째", b["detail"][0]["error"])
        st, b, _ = self.srv.req("PUT", "/api/team/settings", {"server_alternates": ["127.0.0.1:9312"],
                                                              "self_label": "홍길동", "auto_send": False})
        self.assertEqual(st, 200, b)
        self.assertEqual(b["settings"]["server_alternates"], ["127.0.0.1:9312"])
        st, b, _ = self.srv.req("PUT", "/api/team/settings", {"nope": 1})
        self.assertEqual(st, 400)

    def test_ping_uses_hello(self):
        st, b, _ = self.srv.req("POST", "/api/team/ping", {"host": "127.0.0.1", "port": 9310})
        self.assertEqual(st, 200)
        self.assertEqual(b["result"], "ok")
        self.assertEqual(self.app.deps.hellos, ["http://127.0.0.1:9310"])
        st, b, _ = self.srv.req("POST", "/api/team/ping", {"host": "8.8.8.8", "port": 9310})
        self.assertEqual(st, 400)

    def test_outbox_empty_and_unknown_item(self):
        st, b, _ = self.srv.req("GET", "/api/team/outbox")
        self.assertEqual(st, 200)
        self.assertEqual(b["items"], [])
        st, b, _ = self.srv.req("GET", "/api/team/preview/lm27_team_bundle_x")
        self.assertEqual(st, 404)
        st, b, _ = self.srv.req("POST", "/api/team/mask", {"unit_id": "u_0123456789", "mode": "bad"})
        self.assertEqual(st, 400)

    def test_teamserver_start_saves_and_spawns(self):
        st, b, _ = self.srv.req("POST", "/api/teamserver/start", {"bind_host": "127.0.0.1", "bind_port": 45999,
                                                                   "display_name": "팀서버A"})
        self.assertEqual(st, 200, b)
        argv = self.app.deps.detached_argv
        self.assertEqual(argv[-5:], ["team-server", "--host", "127.0.0.1", "--port", "45999"])
        cfg = self._cfg_json()
        self.assertEqual((cfg["teamServer.bindHost"], cfg["teamServer.bindPort"], cfg["teamServer.displayName"]),
                         ("127.0.0.1", 45999, "팀서버A"))
        self.app.deps.detached_rc = 3
        st, b, _ = self.srv.req("POST", "/api/teamserver/start", {"bind_host": "127.0.0.1", "bind_port": 45999})
        self.assertEqual((st, b["code"]), (409, "start_failed"))
        for body in ({"bind_host": "my-pc", "bind_port": 9310}, {"bind_host": "127.0.0.1", "bind_port": 80}):
            st, b, _ = self.srv.req("POST", "/api/teamserver/start", body)
            self.assertEqual(st, 400, body)

    def test_teamserver_local_not_running(self):
        st, b, _ = self.srv.req("GET", "/api/teamserver/local")
        self.assertEqual(st, 200)
        self.assertFalse(b["running"])
        st, b, _ = self.srv.req("POST", "/api/teamserver/stop", {})
        self.assertEqual(st, 409)


if __name__ == "__main__":
    unittest.main()
