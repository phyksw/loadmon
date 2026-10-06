# -*- coding: utf-8 -*-
"""RPT-36 로컬 앱 보안(R §2.3.3) — Host 검사 421 · 토큰 없는 쓰기 403 · text/plain 415 · OPTIONS 405 · 경로 조합 404,
보안 머리·토큰 meta 채우기·본문 상한·종료 API 루프백. 127.0.0.1 임시 포트만, 끝나면 서버 종료·스레드 합류."""
import unittest

from tests.fixtures.wp35.harness import Running, Sandbox


class SecurityTest(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()
        self.addCleanup(self.sb.cleanup)
        self.app = self.sb.app()
        self.srv = Running(self.app).__enter__()
        self.addCleanup(self.srv.close)

    def test_rpt36_host_check_421(self):
        st, body, _ = self.srv.req("GET", "/api/hello", host="evil.example:19280")
        self.assertEqual(st, 421)
        self.assertEqual(body["code"], "bad_host")
        st, _b, _ = self.srv.req("GET", "/api/hello", host=f"localhost:{self.srv.port}")
        self.assertEqual(st, 200)
        st, _b, _ = self.srv.req("GET", "/api/hello", host=f"127.0.0.1:{self.srv.port + 1}")
        self.assertEqual(st, 421)

    def test_rpt36_post_without_token_403(self):
        st, body, _ = self.srv.req("POST", "/api/collect/run", {"mode": "auto"}, token=False)
        self.assertEqual(st, 403)
        self.assertEqual(body["code"], "ui_token")
        st, body, _ = self.srv.req("POST", "/api/collect/run", {"mode": "auto"}, token="0" * 32)
        self.assertEqual(st, 403)
        st, body, _ = self.srv.req("PUT", "/api/settings", {"ui.jobPollMs": 1500}, token=False)
        self.assertEqual(st, 403)

    def test_rpt36_text_plain_415(self):
        st, body, _ = self.srv.req("POST", "/api/collect/run", raw=b'{"mode":"auto"}', ctype="text/plain")
        self.assertEqual(st, 415)
        self.assertEqual(body["code"], "content_type")

    def test_rpt36_options_405_and_no_cors(self):
        st, body, hdr = self.srv.req("OPTIONS", "/api/hello")
        self.assertEqual(st, 405)
        self.assertFalse(any(k.startswith("access-control-") for k in hdr))
        st, _b, hdr = self.srv.req("GET", "/api/hello")
        self.assertFalse(any(k.startswith("access-control-") for k in hdr))

    def test_rpt36_static_traversal_404(self):
        st, body, _ = self.srv.req("GET", "/static/../config/config.json")
        self.assertEqual(st, 404)
        st, _b, _ = self.srv.req("GET", "/static/%2e%2e/config/settings_registry.json")
        self.assertEqual(st, 404)
        st, _b, _ = self.srv.req("GET", "/web/app/index.html")
        self.assertEqual(st, 404)

    def test_security_headers(self):
        st, _b, hdr = self.srv.req("GET", "/api/hello")
        self.assertEqual(st, 200)
        self.assertIn("default-src 'self'", hdr["content-security-policy"])
        self.assertIn("frame-ancestors 'none'", hdr["content-security-policy"])
        self.assertEqual(hdr["x-content-type-options"], "nosniff")
        self.assertEqual(hdr["referrer-policy"], "no-referrer")
        self.assertEqual(hdr["cache-control"], "no-store")

    def test_index_token_filled_file_untouched(self):
        st, body, hdr = self.srv.req("GET", "/")
        self.assertEqual(st, 200)
        self.assertTrue(hdr["content-type"].startswith("text/html"))
        self.assertIn(('<meta name="lm27-ui-token" content="' + self.app.token + '">').encode(), body)
        raw = self.sb.paths.web_file("app/index.html").read_bytes()
        self.assertNotIn(self.app.token.encode(), raw)                 # 파일은 바꾸지 않는다(응답만)
        st, js, hdr = self.srv.req("GET", "/static/app.js")
        self.assertEqual(st, 200)
        self.assertTrue(hdr["content-type"].startswith("text/javascript"))

    def test_body_limit_413_and_bad_json_400(self):
        big = b'{"x":"' + b"a" * (2 * 1024 * 1024 + 10) + b'"}'
        st, body, _ = self.srv.req("POST", "/api/collect/run", raw=big)
        self.assertEqual(st, 413)
        st, body, _ = self.srv.req("POST", "/api/collect/run", raw=b"{not json")
        self.assertEqual(st, 400)
        st, body, _ = self.srv.req("POST", "/api/collect/run", raw=b'{"a":1,"a":2}')
        self.assertEqual(st, 400)                                        # 중복 키 거부(loads_strict)

    def test_unknown_api_404_shape(self):
        st, body, _ = self.srv.req("GET", "/api/nope")
        self.assertEqual(st, 404)
        self.assertEqual(set(body), {"ok", "code", "error", "detail"})
        self.assertFalse(body["ok"])

    def test_hello_identity(self):
        st, body, _ = self.srv.req("GET", "/api/hello")
        self.assertEqual(body["app"], "LM27-ui")
        self.assertEqual(body["instance_id"], self.app.instance_id)
        self.assertEqual(body["root_id"], self.app.root_id)
        self.assertEqual(len(body["root_id"]), 8)
        self.assertEqual(body["port"], self.srv.port)                  # 머리·상태 줄의 '127.0.0.1:<포트>' 표시
        self.assertFalse(body["token_meta"])
        self.assertNotIn(self.app.token, str(body))

    def test_request_log_and_prune(self):
        from lm27.util import fsx
        old = self.sb.paths.ui_logs() / "ui_20000101.log"
        fsx.atomic_write(old, b"old\n")
        self.app.scratch.pop("_log_day", None)
        self.srv.req("GET", "/api/collect/coverage?from=2026-09-01&to=2026-09-02")
        self.srv.req("POST", "/api/worklog", {"date": "2026-09-01", "kind": "work", "hours": 1, "memo": "비밀 메모"})
        import time

        def logs():
            return "".join(p.read_text(encoding="utf-8") for p in self.sb.paths.ui_logs().glob("ui_*.log"))
        t0 = time.monotonic()                                           # 로그는 응답 뒤에 쓴다 — 잠깐 기다린다
        while (old.exists() or "POST /api/worklog" not in logs()) and time.monotonic() - t0 < 5:
            time.sleep(0.05)
        self.assertFalse(old.exists())                                  # ui.logKeepDays 지난 로그 정리
        txt = logs()
        self.assertIn("GET /api/collect/coverage 200", txt)
        self.assertIn("POST /api/worklog 200", txt)
        self.assertNotIn("from=", txt)                                  # 쿼리 제외
        self.assertNotIn("비밀", txt)                                    # 본문 금지

    def test_shutdown_needs_token_then_stops(self):
        st, _b, _ = self.srv.req("POST", "/api/shutdown", {}, token=False)
        self.assertEqual(st, 403)
        st, body, _ = self.srv.req("POST", "/api/shutdown", {})
        self.assertEqual(st, 200)
        self.assertTrue(body["stopping"])
        self.srv.thread.join(5)
        self.assertFalse(self.srv.thread.is_alive())


if __name__ == "__main__":
    unittest.main()
