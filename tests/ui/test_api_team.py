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



UNIT = "u_a1a1a1a1a1"
PER = "2026-08-01_2026-09-30"
TITLE = "전원부 검증"


def _bundle(title_mode="label", title=TITLE, needs=()):
    return {"schema": "lm27.team_bundle", "schema_version": "1.0",
            "units": [{"unit_id": UNIT, "title": title, "title_mode": title_mode, "role_id": "r_000001",
                       "effort_min": 600, "grade": "B", "status": "done", "peers": ["k0000000001"],
                       "apps": ["excel"], "evidence_n": {"file": 1, "app": 1}}],
            "agentic": {"needs": [{"need_id": n, "step_type": "DOC_XLS", "label": "표 자동화", "grade": "중"} for n in needs]}}


class TeamQueueApiTest(unittest.TestCase):
    """C16·C17 회귀 — 대기열 화면 API.
    C17: 미리보기를 연 적 없는 승인 전 묶음은 [보내기]·[승인만]이 409 preview_first(예전: 바로 승인·전송).
    C16: [제목 가림] 은 가림을 저장하고 덜 가려진 대기 묶음의 승인을 풀며 그 기간을 다시 만드는 작업(job_id)을 띄운다. 작업을
    못 띄우면 job_id 없이 그 이유(예전: 아무 작업 없이 ok — 화면은 '다시 만들었다'고 거짓 안내, 옛 바이트가 자동 전송)."""

    def setUp(self):
        self.sb = Sandbox()
        self.addCleanup(self.sb.cleanup)
        self.app = self.sb.app(behaviour={"team": {"sleep": 0.2}, "collect": {"sleep": 30}})
        self.srv = Running(self.app).__enter__()
        self.addCleanup(self.srv.close)

    def _put(self, obj, *, approved=False):
        from lm27.team import queue as Q
        raw = fsx.canon_bytes(obj)
        meta = Q.new_meta(fsx.sha256_hex(raw), len(raw), PER, "p_000000000000", "2026-10-01T00:00:00Z", "PC1", [])
        it = Q.write_pending(self.sb.paths, PER, raw, meta)
        if approved:
            self.assertEqual(Q.approve(it).rc, 0)
        return it.name[:-5]

    def _meta(self, name):
        from lm27.team import queue as Q
        return Q.find_item(self.sb.paths, name + ".json").meta

    def _job_argv(self, jid, timeout=20.0):
        import time

        from lm27.ui import jobs as J
        t0 = time.monotonic()
        while time.monotonic() - t0 < timeout:
            v = self.app.jobs.get(jid)
            if v and v["state"] in J.FINISHED:
                return (v.get("result") or {}).get("argv")
            time.sleep(0.05)
        self.fail("작업이 끝나지 않았습니다")

    def test_c17_send_and_approve_need_preview_first(self):
        name = self._put(_bundle())
        for path in (f"/api/team/send/{name}", f"/api/team/approve/{name}"):
            st, b, _ = self.srv.req("POST", path, {})
            self.assertEqual((st, b["code"]), (409, "preview_first"), path)
        self.assertFalse(self._meta(name)["approved"], "미리보기 없이 승인하지 않는다")
        self.assertEqual(self.app.jobs.list(), [], "보내기 작업을 띄우지 않았다")
        st, pv, _ = self.srv.req("GET", f"/api/team/preview/{name}")
        self.assertEqual(st, 200, pv)
        self.assertTrue(pv["can_send"])
        m = self._meta(name)
        self.assertEqual((m["previewed_sha"], m["approved"]), (m["sha256"], False))
        st, b, _ = self.srv.req("POST", f"/api/team/send/{name}", {})
        self.assertEqual(st, 200, b)
        self.assertEqual(self._job_argv(b["job_id"]), ["team", "send", name + ".json"])
        self.assertTrue(self._meta(name)["approved"])

    def test_c17_approved_item_resend_without_preview(self):
        name = self._put(_bundle(), approved=True)                   # 이미 승인(보내다 실패) — [다시 시도]는 미리보기 없이
        st, b, _ = self.srv.req("POST", f"/api/team/send/{name}", {})
        self.assertEqual(st, 200, b)
        self._job_argv(b["job_id"])

    def test_c16_mask_unapproves_and_rebuilds_that_period(self):
        name = self._put(_bundle(), approved=True)
        st, b, _ = self.srv.req("POST", "/api/team/mask", {"unit_id": UNIT, "mode": "title", "item": name})
        self.assertEqual(st, 200, b)
        self.assertEqual((b["changed"], b["stale_n"]), (True, 1))
        self.assertTrue(b.get("job_id"), "그 기간을 다시 만드는 작업")
        self.assertIn("다시 만듭니다", b["text_ko"])
        self.assertEqual(self._job_argv(b["job_id"]), ["team", "build", "--from", "2026-08-01", "--to", "2026-09-30"])
        m = self._meta(name)
        self.assertEqual((m["approved"], m["history"][-1]["event"]), (False, "mask_changed"))
        from lm27.team import queue as Q
        self.assertFalse(self.app._team_due(), "자동 전송 대상이 아니다")
        res = Q.send_due(self.app.cfg(), paths=self.sb.paths, trigger="startup")
        self.assertEqual(res.sent, 0)
        st, pv, _ = self.srv.req("GET", f"/api/team/preview/{name}")
        self.assertEqual(st, 200, pv)
        self.assertEqual((pv["can_send"], pv["stale_mask"], pv["mask_gaps"]), (False, True, [f"unit:{UNIT}:title"]))
        self.assertEqual(pv["units"][0]["mask"], "title")
        self.assertFalse(pv["units"][0]["mask_applied"])
        for path in (f"/api/team/send/{name}", f"/api/team/approve/{name}"):
            st, b, _ = self.srv.req("POST", path, {})
            self.assertEqual((st, b["code"]), (409, "blocked"), path)
            self.assertIn("다시 만들지 않은", b["error"])
        st, b, _ = self.srv.req("POST", "/api/team/mask", {"unit_id": UNIT, "mode": "title", "item": name})
        self.assertEqual((st, b["changed"]), (200, False))
        self.assertNotIn("job_id", b, "바뀐 것이 없으면 다시 만들지 않는다")

    def test_c16_busy_lane_no_false_rebuilt_claim(self):
        name = self._put(_bundle(), approved=True)
        st, c, _ = self.srv.req("POST", "/api/collect/run", {"mode": "auto"})   # 번들 차선을 잡아 둔다
        self.assertEqual(st, 200, c)
        self.addCleanup(lambda: self.app.jobs.cancel(c["job_id"]))
        st, b, _ = self.srv.req("POST", "/api/team/mask", {"unit_id": UNIT, "mode": "detail", "item": name})
        self.assertEqual(st, 200, b)
        self.assertNotIn("job_id", b)
        self.assertIn("아직 다시 만들지 못했습니다", b["text_ko"])
        self.assertIn("보내지 않습니다", b["text_ko"])
        self.assertFalse(self._meta(name)["approved"])

    def test_c16_need_drop_from_preview_rebuilds(self):
        nid = "n_1a2b3c"
        name = self._put(_bundle(title_mode="generic", needs=(nid,)), approved=True)
        st, b, _ = self.srv.req("POST", "/api/agentic/need/drop", {"need_id": nid, "drop": True, "item": name})
        self.assertEqual(st, 200, b)
        self.assertEqual((b["changed"], b["stale_n"]), (True, 1))
        self.assertEqual(self._job_argv(b["job_id"]), ["team", "build", "--from", "2026-08-01", "--to", "2026-09-30"])
        self.assertFalse(self._meta(name)["approved"])
        st, b, _ = self.srv.req("POST", "/api/team/mask", {"unit_id": UNIT, "mode": "title", "item": "../x"})
        self.assertEqual(st, 400)

if __name__ == "__main__":
    unittest.main()
