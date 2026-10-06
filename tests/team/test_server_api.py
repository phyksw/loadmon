# -*- coding: utf-8 -*-
"""WP-27 팀 서버 API — 신원·보안 헤더·권한·레지스트리·명단·정적 고정 사전·보고서·드릴다운
(TAB §3.5·§3.6·§3.10~§3.12, TAB-S01 · S07 · S09 · S10 · S11 · S12 · S14 · S15). 같은 프로세스 시험 서버 + 임시 저장소.
"""
import hashlib
import http.client
import json
import os
import socket
import unittest

from lm27.util import fsx
from tests.fixtures.wp27 import bundles as B
from tests.fixtures.wp27.helpers import running_server

PK1 = B.person_key(1)
REMOTE = ".".join(("203", "0", "113", "7"))          # 문서 예시 대역(공인·비사설) — 원격 출발지 모사


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def _err_shape(t, obj, code):
    t.assertEqual((obj["ok"], obj["code"]), (False, code))
    t.assertIsInstance(obj["error"], str)
    t.assertIsInstance(obj["detail"], list)


class ApiCase(unittest.TestCase):
    over: dict = {}

    def setUp(self):
        self._td = B.temp_dir()
        self.dir = self._td.__enter__()
        self._cm = running_server(self.dir, **self.over)
        self.ts = self._cm.__enter__()

    def tearDown(self):
        self._cm.__exit__(None, None, None)
        self._td.__exit__(None, None, None)

    def remote(self, ip=REMOTE):
        self.ts.app.client_ip = lambda h: ip


class TestIdentityAndHeaders(ApiCase):
    def test_s01_hello_no_path_pid_token_host(self):
        code, h, hdr = self.ts.call("GET", "/api/hello")
        self.assertEqual(code, 200)
        self.assertEqual((h["app"], h["proto"], h["accepts"]), ("-".join(("LM27", "team")), "lm27-team/1", {"team_bundle": {"1": 0}}))   # 계약 §4.7 신원
        self.assertEqual(set(h), {"app", "proto", "version", "api", "accepts", "auth", "max_body_mb", "instance_id",
                                  "store_id", "name", "registry_version", "pepper_id", "server_time"})
        text = json.dumps(h, ensure_ascii=False)
        self.assertNotIn(str(self.dir), text)
        self.assertNotIn(socket.gethostname(), text)
        self.assertNotIn(self.ts.store.pepper, text)
        self.assertEqual(hdr["Cache-Control"], "no-store")
        self.assertEqual(hdr["X-Content-Type-Options"], "nosniff")
        self.assertIsNone(hdr["Access-Control-Allow-Origin"])

    def test_s14_host_header(self):
        code, obj, _ = self.ts.call("GET", "/api/hello", headers={"Host": "evil.example:9310"})
        self.assertEqual(code, 421)
        _err_shape(self, obj, "bad_host")
        self.assertEqual(self.ts.call("GET", "/api/hello", headers={"Host": f"localhost:{self.ts.port}"})[0], 200)
        self.assertEqual(self.ts.call("GET", "/api/hello", headers={"Host": "localhost:1"})[0], 421)

    def test_s15_options_and_form_post(self):
        code, obj, _ = self.ts.call("OPTIONS", "/api/bundles")
        self.assertEqual(code, 405)
        code, obj, _ = self.ts.call("POST", "/api/bundles", b"a=1", {"Content-Type": "application/x-www-form-urlencoded"})
        self.assertEqual(code, 415)
        _err_shape(self, obj, "content_type")

    def test_s09_content_type_and_length(self):
        code, obj, _ = self.ts.call("POST", "/api/bundles", b"{}", {"Content-Type": "text/plain"})
        self.assertEqual(code, 415)
        c = http.client.HTTPConnection("127.0.0.1", self.ts.port, timeout=10)
        c.putrequest("POST", "/api/bundles")
        c.putheader("Content-Type", "application/json")
        c.endheaders()
        r = c.getresponse()
        self.assertEqual((r.status, json.loads(r.read())["code"]), (411, "length_required"))
        c.close()

    def test_s12_lm24_upload_endpoint(self):
        code, obj, _ = self.ts.call("POST", "/api/upload", b'{"member":{}}', {"Content-Type": "application/json"})
        self.assertEqual(code, 410)
        _err_shape(self, obj, "lm24_endpoint")
        self.assertIn("LM24", obj["error"])

    def test_s11_shutdown_remote_forbidden(self):
        self.remote()
        code, obj, _ = self.ts.call("POST", "/api/shutdown", b"{}", {"Content-Type": "application/json"})
        self.assertEqual(code, 403)
        self.assertEqual(self.ts.call("GET", "/api/hello")[0], 200)                # 서버 계속

    def test_static_fixed_dictionary(self):
        for p in ("/static/team.css", "/static/../config/settings_registry.json", "/static/%2e%2e/lm27_cli.py",
                  "/web/team/index.html"):
            self.assertEqual(self.ts.call("GET", p)[0], 404, p)
        code, body, hdr = self.ts.call("GET", "/")
        if code == 200:                                                             # 화면 파일(WP-37)이 있을 때
            self.assertIn("default-src 'self'", hdr["Content-Security-Policy"])
            self.assertEqual(hdr["Referrer-Policy"], "no-referrer")
        else:
            self.assertEqual(code, 404)

    def test_status(self):
        code, st, _ = self.ts.call("GET", "/api/status")
        self.assertEqual(code, 200)
        self.assertEqual(set(st), {"uploads_today", "last_upload_at", "aggregate", "members", "inbox",
                                   "external_requests", "firewall_hint"})
        self.remote()
        self.ts.call("GET", "/api/status")
        self.assertEqual(self.ts.app.external, 1)


class TestCidr(ApiCase):
    over = {"teamServer.allowCidrs": [".".join(("10", "0", "0", "0")) + "/8"]}

    def test_s10_allow_cidrs(self):
        self.assertEqual(self.ts.call("GET", "/api/hello")[0], 200)                # 루프백은 항상
        self.remote()
        code, obj, _ = self.ts.call("GET", "/api/hello")
        self.assertEqual(code, 403)
        _err_shape(self, obj, "forbidden_ip")
        self.remote(".".join(("10", "1", "2", "3")))
        self.assertEqual(self.ts.call("GET", "/api/hello")[0], 200)


class TestRegistryApi(ApiCase):
    over = {"teamServer.adminTokenSha256": _sha("관리-토큰")}

    def put(self, obj, headers=None):
        h = {"Content-Type": "application/json"}
        h.update(headers or {})
        return self.ts.call("PUT", "/api/registry", json.dumps(obj, ensure_ascii=False).encode(), h)

    def test_s07_registry_put_get_etag(self):
        code, obj, _ = self.put(B.registry(1))
        self.assertEqual((code, obj), (200, {"ok": True, "version": 1}))
        code, obj, _ = self.put(B.registry(1))
        self.assertEqual(code, 409)
        _err_shape(self, obj, "registry_version_conflict")
        cyc = B.registry(2, projects=[{"id": "P-0003", "name": "과제C", "domain": "DEV", "merged_into": "P-0004"},
                                      {"id": "P-0004", "name": "과제D", "domain": "DEV", "merged_into": "P-0003"}])
        code, obj, _ = self.put(cyc)
        self.assertEqual((code, obj["code"]), (422, "cycle_merge"))
        self.assertTrue(all(":" in d for d in obj["detail"]))
        self.remote()
        code, obj, _ = self.put(B.registry(2))
        self.assertEqual((code, obj["code"]), (403, "admin_only"))
        code, obj, _ = self.put(B.registry(2), {"X-LM27-Admin-Token": "관리-토큰".encode().decode("latin-1")})
        self.assertEqual(code, 403)                                                  # 헤더는 ASCII — 다른 값
        self.ts.app.cfg = self.ts.app.cfg.derive({"teamServer.adminTokenSha256": _sha("admin-tok")})
        code, obj, _ = self.put(B.registry(2), {"X-LM27-Admin-Token": "admin-tok"})
        self.assertEqual(code, 200)
        code, reg, hdr = self.ts.call("GET", "/api/registry")
        self.assertEqual((code, reg["version"], hdr["ETag"]), (200, 2, '"2"'))
        self.assertEqual(len(reg["pepper"]), 64)
        code, body, _ = self.ts.call("GET", "/api/registry", headers={"If-None-Match": '"2"'})
        self.assertEqual(code, 304)

    def test_patch_members(self):
        self.ts.post_bundle(B.make_bundle(PK1, "2026-07-01", "2026-07-31", built_at="2026-08-01T09:00:00+09:00"))
        body = json.dumps({"label": "팀원갑"}).encode()
        h = {"Content-Type": "application/json"}
        self.assertEqual(self.ts.call("PATCH", f"/api/members/{PK1}", body, h)[0], 200)
        code, mv, _ = self.ts.call("GET", "/api/members")
        self.assertEqual((code, mv["members"][0]["label"]), (200, "팀원갑"))
        self.assertEqual(self.ts.call("PATCH", "/api/members/p_bad", body, h)[0], 404)
        self.remote()
        self.assertEqual(self.ts.call("PATCH", f"/api/members/{PK1}", body, h)[0], 403)

    def test_aggregate_admin(self):
        self.remote()
        self.assertEqual(self.ts.call("POST", "/api/aggregate", b"{}", {"Content-Type": "application/json"})[0], 403)
        self.ts.app.client_ip = lambda h: h.client_address[0]
        code, obj, _ = self.ts.call("POST", "/api/aggregate", b"{}", {"Content-Type": "application/json"})
        self.assertEqual((code, obj["ok"]), (200, True))


class TestCrossOrigin(ApiCase):
    """L08 회귀: 팀 서버 PC 의 브라우저가 연 남의 웹페이지가 루프백으로 보내는 교차 출처 요청(단순 POST·다른 Origin)은
    끄기·재취합·레지스트리·명단을 건드리지 못한다. 이 서버 화면(같은 출처)·화면 서버·CLI(Origin 없음, JSON)는 그대로 된다."""

    EVIL = {"Origin": "http://evil.example", "Content-Type": "application/json"}

    def test_simple_cross_site_posts_refused(self):
        for path in ("/api/aggregate", "/api/shutdown"):
            code, obj, _ = self.ts.call("POST", path, b"x", {"Content-Type": "text/plain"})
            self.assertEqual((code, obj["code"]), (415, "content_type"), path)
            code, obj, _ = self.ts.call("POST", path, b"a=1", {"Content-Type": "application/x-www-form-urlencoded"})
            self.assertEqual(code, 415, path)
            code, obj, _ = self.ts.call("POST", path, b"{}", self.EVIL)
            self.assertEqual((code, obj["code"]), (403, "cross_origin"), path)
            code, obj, _ = self.ts.call("POST", path, b"{}", {"Content-Type": "application/json", "Origin": "null"})
            self.assertEqual(code, 403, path)
            code, obj, _ = self.ts.call("POST", path, b"{}", {"Content-Type": "application/json",
                                                              "Sec-Fetch-Site": "cross-site"})
            self.assertEqual(code, 403, path)
        self.assertEqual(self.ts.call("GET", "/api/hello")[0], 200)                # 서버 계속
        self.assertEqual(self.ts.app.agg.req, 0, "재취합을 걸지 않았다")

    def test_admin_writes_refuse_other_origin(self):
        body = json.dumps({"label": "x"}).encode()
        self.assertEqual(self.ts.call("PATCH", f"/api/members/{PK1}", body, self.EVIL)[0], 403)
        self.assertEqual(self.ts.call("PUT", "/api/registry", b"{}", self.EVIL)[0], 403)

    def test_same_origin_and_local_tools_allowed(self):
        same = {"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{self.ts.port}",
                "Sec-Fetch-Site": "same-origin"}
        code, obj, _ = self.ts.call("POST", "/api/aggregate", b"{}", same)
        self.assertEqual((code, obj["ok"]), (200, True))
        code, obj, _ = self.ts.call("POST", "/api/aggregate", b"{}", {"Content-Type": "application/json"})
        self.assertEqual(code, 200)                                                  # 화면 서버·CLI(Origin 없음)
        code, obj, _ = self.ts.call("POST", "/api/shutdown", b"{}", {"Content-Type": "application/json"})
        self.assertEqual((code, obj["stopping"]), (200, True))


class TestReadToken(ApiCase):
    over = {"teamServer.readRequiresToken": True, "teamServer.uploadTokenSha256": _sha("read-tok")}

    def test_read_token_mode(self):
        self.assertEqual(self.ts.call("GET", "/api/hello")[0], 200)                # 신원 확인이 먼저
        code, obj, _ = self.ts.call("GET", "/api/team")
        self.assertEqual((code, obj["code"]), (401, "token_required"))
        code, obj, _ = self.ts.call("GET", "/api/members", headers={"X-LM27-Upload-Token": "wrong"})
        self.assertEqual((code, obj["code"]), (401, "token_invalid"))
        self.assertEqual(self.ts.call("GET", "/api/members", headers={"X-LM27-Upload-Token": "read-tok"})[0], 200)
        code, obj, _ = self.ts.call("GET", "/report")
        self.assertEqual((code, obj["code"]), (403, "read_token_mode"))


class TestTeamData(ApiCase):
    def test_team_detail_and_report_csp(self):
        self.assertEqual(self.ts.call("GET", "/api/team")[0], 404)
        self.ts.post_bundle(B.make_bundle(PK1, "2026-07-01", "2026-07-31", built_at="2026-08-01T09:00:00+09:00"))
        code, td, hdr = self.ts.call("GET", "/api/team")
        self.assertEqual((code, td["schema"]), (200, "lm27.teamdata/1"))
        self.assertEqual(hdr["Content-Type"], "application/json; charset=utf-8")
        rid = td["gantt"][0]["role_id"]
        code, d, _ = self.ts.call("GET", f"/api/team/detail?person={PK1}&role={rid}")
        self.assertEqual((code, d["person"]["i"], d["role"]["role_id"]), (200, 0, rid))
        self.assertEqual(self.ts.call("GET", f"/api/team/detail?person={PK1}&role=r_000000")[0], 404)
        self.assertEqual(self.ts.call("GET", "/api/team/detail?person=../x&role=r_1")[0], 404)
        g = self.ts.store.current_gen()["gen"]
        fsx.atomic_write(self.ts.store.gen_dir(g) / "team_report.html", "<!doctype html><p>시험</p>".encode())
        code, body, hdr = self.ts.call("GET", "/report")
        self.assertEqual(code, 200)
        self.assertEqual(hdr["Content-Security-Policy"], "sandbox allow-scripts allow-popups allow-popups-to-escape-sandbox")
        # 공유본은 취합이 함께 만든다(WP-37 렌더러 — W1 통합 창). 같은 CSP, 파일이 없으면 404
        code, body, hdr = self.ts.call("GET", "/report/share")
        self.assertEqual(code, 200)
        self.assertEqual(hdr["Content-Security-Policy"], "sandbox allow-scripts allow-popups allow-popups-to-escape-sandbox")
        os.remove(self.ts.store.gen_dir(g) / "team_report_share.html")
        self.assertEqual(self.ts.call("GET", "/report/share")[0], 404)
