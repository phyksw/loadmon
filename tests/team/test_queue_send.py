# -*- coding: utf-8 -*-
"""WP-34 보내기 — U01(미리보기 = 실전송 = 서버 저장 sha, WP-27 서버 실물), U05 대기·재시도 후 재개, U06 LM24 서버(POST 0 ·
응답 값 기록 0), U07 판 불일치, U08 토큰(없음·틀림·맞음 → 토큰이 바뀌면 자동 재개), U10 동시 전송(lease 로 POST 1회 ·
겹쳐도 already_have), U13 대체 주소(last_target · 설정 불변), U14 클라우드→사내([수집] 계기 · 시도 횟수 0 · 폴더 복사 후 자동
sent), O01 내보내기 바이트, O05 전달 확인, HTTP 거절 대응표, 자동 전송(team.autoSend). 서버는 127.0.0.1 시험 포트만."""
import json
import os
import shutil
import tempfile
import threading
import unittest
from datetime import UTC, datetime, timedelta

from lm27.team import build as B
from lm27.team import client as C
from lm27.team import queue as Q
from lm27.util import events, fsx
from tests.fixtures.wp34 import servers as SV
from tests.fixtures.wp34 import world as W

PERIOD = {"from": W.D0, "to": W.D1}
PER = f"{W.D0}_{W.D1}"
NOW = datetime(2026, 10, 1, 1, 0, 0, tzinfo=UTC)


def _cfg(port, **over):
    ov = {"team.serverHost": SV.HOST, "team.serverPort": port}
    ov.update(over)
    return W.cfg(**ov)


class SCase(unittest.TestCase):
    def setUp(self):
        self._mode = events.mode()
        events.configure("off")
        self.w = W.World()
        self.p = self.w.paths

    def tearDown(self):
        self.w.cleanup()
        events.configure(self._mode)

    def make(self, cfg, *, now=NOW, paths=None, world=None):
        w = world or self.w
        return B.build_and_queue(W.model(), PERIOD, cfg, paths=paths or w.paths, now=now, env=w.env(cfg))

    def all_bytes(self, root):
        out = []
        for dp, _dn, fns in os.walk(root):
            for fn in fns:
                with open(os.path.join(dp, fn), "rb") as f:
                    out.append(f.read())
        return b"\n".join(out)


class TestRealServer(SCase):
    def test_u01_preview_equals_sent_equals_stored(self):
        store = tempfile.mkdtemp(prefix="lm27t_wp34_store_")
        try:
            with SV.real_team(store) as ts:
                c = _cfg(ts.port)
                it = self.make(c)
                pv = Q.preview(it)
                out = Q.send_item(it, c, now=NOW)
                self.assertEqual((out.rc, out.state, out.folder), (0, "sent", "sent"), out.message)
                self.assertEqual(out.meta["server_status"], "stored")
                cur = ts.store.read_current(W.PERSON_KEY)
                self.assertEqual(sorted(cur), [PER])
                stored = ts.store.bundle_bytes(W.PERSON_KEY, cur[PER]["file"])
                self.assertEqual({pv["sha256"], it.sha256, cur[PER]["sha256"], fsx.sha256_hex(stored)}, {it.sha256})
                self.assertEqual(stored, fsx.read_bytes(out.path))
                again = self.make(c)                                                # 같은 바이트를 다시(보낸 뒤)
                out2 = Q.send_item(again, c, now=NOW)
                self.assertEqual((out2.rc, out2.meta["server_status"]), (0, "already_have"))
        finally:
            shutil.rmtree(store, ignore_errors=True)


    def test_u04_server_rejects_forbidden_content(self):
        """U04: 빌더를 우회해 이메일이 든 묶음을 직접 POST → 422 forbidden_content, 저장 없음, 응답에 값 없음."""
        store = tempfile.mkdtemp(prefix="lm27t_wp34_store_")
        try:
            with SV.real_team(store) as ts:
                c = _cfg(ts.port)
                it = self.make(c)
                obj = json.loads(fsx.read_bytes(it.path))
                mail = "user09@" + W.INTERNAL
                obj["units"][0]["title"] = f"{mail} 회신"
                raw = fsx.canon_bytes(obj)
                r = C.http_post(f"http://{SV.HOST}:{ts.port}/api/bundles", raw,
                                {"Content-Type": "application/json; charset=utf-8", C.SHA_HEADER: fsx.sha256_hex(raw),
                                 C.CLIENT_HEADER: "0.1.0"}, 10)
                self.assertEqual((r.status, (r.obj or {}).get("code")), (422, "forbidden_content"))
                self.assertNotIn(mail.encode(), r.body or b"")
                self.assertEqual(ts.store.read_current(W.PERSON_KEY), {})
        finally:
            shutil.rmtree(store, ignore_errors=True)


class TestFake(SCase):
    def test_u05_retry_then_sent_when_server_returns(self):
        port = SV.dead_port()
        c = _cfg(port)
        it = self.make(c)
        Q.approve(it, now=NOW)
        r = Q.send_due(c, paths=self.p, now=NOW, trigger="manual")
        self.assertEqual((r.rc, r.retry), (2, 1))
        cur = Q.find_item(self.p, it.name)
        self.assertEqual((cur.state, cur.meta["attempts"]), ("retry_wait", 1))
        nxt = datetime.strptime(cur.meta["next_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        self.assertTrue(54 <= (nxt - NOW).total_seconds() <= 66)
        with SV.fake_team("lm27", port=port) as fs:
            r = Q.send_due(c, paths=self.p, now=NOW + timedelta(seconds=30), trigger="timer")
            self.assertEqual((r.rc, r.skipped, fs.posts), (4, 1, []))
            r = Q.send_due(c, paths=self.p, now=NOW + timedelta(seconds=70), trigger="timer")
            self.assertEqual((r.rc, r.sent), (0, 1))
            self.assertEqual([(p["sha"], p["claimed"]) for p in fs.posts], [(it.sha256, it.sha256)])
            self.assertEqual(fs.posts[0]["client"], __import__("lm27").LM27_VERSION)
            self.assertEqual(fs.posts[0]["sent_at"], "2026-10-01T01:01:10Z")       # 보낸 시각은 헤더로만
        cur = Q.find_item(self.p, it.name)
        self.assertEqual((cur.state, cur.folder, cur.meta["last_target"]), ("sent", "sent", "primary"))
        self.assertEqual(fsx.sha256_hex(fsx.read_bytes(cur.path)), it.sha256)       # 본문은 고치지 않는다

    def test_u06_lm24_wrong_server_no_post_no_trace(self):
        with SV.fake_team("lm24") as fs, SV.fake_team("lm27") as good:
            c = _cfg(fs.port)
            it = self.make(c)
            out = Q.send_item(it, c, now=NOW)
            self.assertEqual((out.rc, out.state), (2, "wrong_server"))
            self.assertEqual(fs.posts, [])
            self.assertIn("/api/whoami", fs.gets)
            self.assertIn("LM24", out.meta["last_error"])
            self.assertNotIn(b"CANARY", self.all_bytes(self.w.root))                # 응답 본문 기록 0
            # 주소가 그대로면 계기 전송이 다시 묻지 않고, 주소를 바꾸면 자동 재개
            n = len(fs.gets)
            r = Q.send_due(c, paths=self.p, now=NOW, trigger="timer")
            self.assertEqual((r.rc, r.skipped, len(fs.gets)), (4, 1, n))
            r = Q.send_due(_cfg(good.port), paths=self.p, now=NOW, trigger="timer")
            self.assertEqual((r.rc, r.sent), (0, 1))
            self.assertEqual((len(good.posts), fs.posts), (1, []))

    def test_u07_version_mismatch_failed(self):
        with SV.fake_team("v2") as fs:
            c = _cfg(fs.port)
            out = Q.send_item(self.make(c), c, now=NOW)
            self.assertEqual((out.rc, out.state, out.folder), (1, "failed", "failed"))
            self.assertEqual(fs.posts, [])

    def test_other_app_wrong_server(self):
        with SV.fake_team("other_app") as fs:
            c = _cfg(fs.port)
            out = Q.send_item(self.make(c), c, now=NOW)
            self.assertEqual((out.rc, out.state), (2, "wrong_server"))
            self.assertEqual(fs.posts, [])

    def test_u08_tokens(self):
        with SV.fake_team("lm27") as fs:
            fs.auth_upload, fs.token = True, "tok-right"
            c = _cfg(fs.port)
            it = self.make(c)
            out = Q.send_item(it, c, now=NOW)                                       # 토큰 없음 → 묻기만, POST 0
            self.assertEqual((out.rc, out.state, fs.posts), (2, "auth_needed", []))
            C.set_upload_token(self.p, "tok-wrong")
            r = Q.send_due(c, paths=self.p, now=NOW, trigger="timer")               # 토큰이 바뀜 → 자동 재개
            self.assertEqual((r.rc, r.auth_needed), (2, 1))
            self.assertEqual([p["token"] for p in fs.posts], ["tok-wrong"])
            cur = Q.find_item(self.p, it.name)
            self.assertIn("token_invalid", cur.meta["last_error"])
            self.assertNotIn("tok-wrong", fsx.canon_bytes(cur.meta).decode("utf-8"))  # meta 엔 토큰 지문만
            r = Q.send_due(c, paths=self.p, now=NOW, trigger="timer")               # 같은 토큰 — 다시 묻지 않음
            self.assertEqual((r.rc, r.skipped, len(fs.posts)), (4, 1, 1))
            C.set_upload_token(self.p, "tok-right")
            r = Q.send_due(c, paths=self.p, now=NOW, trigger="timer")
            self.assertEqual((r.rc, r.sent), (0, 1))
            self.assertEqual(fs.posts[-1]["token"], "tok-right")

    def test_u10_concurrent_send_one_post(self):
        with SV.fake_team("lm27") as fs:
            fs.post_delay = 0.6
            c = _cfg(fs.port)
            it = self.make(c)
            Q.approve(it, now=NOW)
            bar = threading.Barrier(2)
            outs = []

            def go():
                bar.wait()
                outs.append(Q.send_item(Q.find_item(self.p, it.name), c, now=NOW))
            ts = [threading.Thread(target=go) for _ in range(2)]
            for t in ts:
                t.start()
            for t in ts:
                t.join(30)
            self.assertEqual(len(fs.posts), 1)
            self.assertEqual(sorted(o.rc for o in outs), [0, 4])
        self.assertEqual(Q.find_item(self.p, it.name).state, "sent")
        self.assertEqual([f for f in os.listdir(self.p.outbox("sent")) if f.endswith(Q.LEASE_SUFFIX)], [])

    def test_u13_alternates(self):
        with SV.fake_team("lm24") as old, SV.fake_team("lm27") as new:
            c = _cfg(old.port, **{"team.serverAlternates": [f"{SV.HOST}:{SV.dead_port()}", f"{SV.HOST}:{new.port}"]})
            it = self.make(c)
            out = Q.send_item(it, c, now=NOW)
            self.assertEqual((out.rc, out.state, out.meta["last_target"]), (0, "sent", "alt2"))
            self.assertEqual((old.posts, len(new.posts)), ([], 1))
            self.assertEqual((c["team.serverHost"], c["team.serverPort"]), (SV.HOST, old.port))

    def test_u14_cloud_to_office(self):
        """클라우드 모사(서버 안 닿음): 빌드·승인 → [수집] 계기 여러 번 → 시도 0. 폴더 복사 → 사내 모사 [수집] 끝 → sent."""
        port = SV.dead_port()
        c = _cfg(port)
        it = self.make(c)
        Q.approve(it, now=NOW)
        for i in range(5):
            r = Q.send_due(c, paths=self.p, now=NOW + timedelta(days=i), trigger="collect")
            self.assertEqual((r.rc, r.waiting), (2, 1))
        cur = Q.find_item(self.p, it.name)
        self.assertEqual((cur.state, cur.meta["attempts"]), ("pending", 0))
        office = tempfile.mkdtemp(prefix="lm27t_wp34_office_")
        try:
            dst = os.path.join(office, "root")
            shutil.copytree(self.w.root, dst)
            op = W.TPaths(dst, lad=os.path.join(dst, "lad"))
            with SV.fake_team("lm27", port=port) as fs:
                r = Q.send_due(c, paths=op, now=NOW + timedelta(days=6), trigger="collect")
                self.assertEqual((r.rc, r.sent), (0, 1))
                self.assertEqual([p["sha"] for p in fs.posts], [it.sha256])
            got = Q.find_item(op, it.name)
            self.assertEqual((got.state, got.meta["attempts"]), ("sent", 0))
        finally:
            shutil.rmtree(office, ignore_errors=True)

    def test_http_rejections(self):
        cases = ((422, "failed", 1), (400, "failed", 1), (500, "retry_wait", 2), (503, "retry_wait", 2),
                 (429, "retry_wait", 2), (404, "wrong_server", 2), (410, "wrong_server", 2))
        for code, state, rc in cases:
            w = W.World()
            try:
                with SV.fake_team("lm27") as fs:
                    fs.post_status = code
                    c = _cfg(fs.port)
                    out = Q.send_item(self.make(c, world=w), c, now=NOW)
                self.assertEqual((out.state, out.rc), (state, rc), code)
                self.assertEqual(len(fs.posts), 1)
                if state == "failed":
                    self.assertEqual(out.meta["reject_detail"], ["units[0].title: schema"])
                    self.assertIn("다시 만들기", out.meta["last_error"])
            finally:
                w.cleanup()

    def test_bad_sha_echo_retries(self):
        with SV.fake_team("lm27") as fs:
            fs.bad_sha = True
            c = _cfg(fs.port)
            out = Q.send_item(self.make(c), c, now=NOW)
        self.assertEqual((out.state, out.rc), ("retry_wait", 2))
        self.assertIn("바이트가 다릅니다", out.meta["last_error"])

    def test_auto_send(self):
        """team.autoSend=true — 빌드 직후 승인 없이 보낸다(TAB §2.8)."""
        with SV.fake_team("lm27") as fs:
            c = _cfg(fs.port, **{"team.autoSend": True})
            it = self.make(c)
            self.assertEqual((it.rc, it.state), (0, "sent"))
            self.assertIn("자동 전송", it.message)
            self.assertEqual(len(fs.posts), 1)

    def test_manual_send_due_reports_counts(self):
        with SV.fake_team("lm27") as fs:
            c = _cfg(fs.port)
            it = self.make(c)
            Q.approve(it, now=NOW)
            r = Q.send_due(c, paths=self.p, now=NOW)
            self.assertEqual((r.rc, r.sent, r.items[0]["name"]), (0, 1, it.name))
            self.assertIn("보냄 1", r.message)


class TestOffline(SCase):
    def test_o01_export_bytes_then_o05_delivered(self):
        from lm27.team import offline as O
        share = tempfile.mkdtemp(prefix="lm27t_wp34_share_")
        try:
            c = _cfg(SV.dead_port())
            it = self.make(c)
            dst = O.export_to_dir(it, share)
            self.assertEqual(fsx.sha256_hex(fsx.read_bytes(dst)), it.sha256)
            self.assertEqual(os.listdir(share), [os.path.basename(dst)])               # .part 잔존 0 · keys 동반 0
            self.assertNotIn("keys", os.listdir(share))
            cur = Q.find_item(self.p, it.name)
            self.assertEqual((cur.state, cur.folder), ("exported", "pending"))
            self.assertTrue(Q.preview(cur)["can_send"])
            with SV.fake_team("lm27") as fs:
                fs.members = {"members": [{"person_key": W.PERSON_KEY,
                                           "periods": [{"period_key": PER, "sha12": it.sha256[:12]}]}]}
                r = Q.send_due(_cfg(fs.port), paths=self.p, now=NOW)
                self.assertEqual((r.rc, r.delivered, r.sent), (0, 1, 0))
                self.assertEqual(fs.posts, [])
            cur = Q.find_item(self.p, it.name)
            self.assertEqual((cur.state, cur.folder), ("delivered", "sent"))
            self.assertIn("delivered_at", cur.meta)
        finally:
            shutil.rmtree(share, ignore_errors=True)

    def test_reconcile_ignores_other_person_and_sha(self):
        it = self.make(_cfg(SV.dead_port()))
        Q.mark(it, "exported", "내보냄", now=NOW)
        n = Q.reconcile_delivered({"members": [{"person_key": "p_000000000001",
                                                "periods": [{"sha12": it.sha256[:12]}]},
                                               {"person_key": W.PERSON_KEY, "periods": [{"sha12": "0" * 12}]}]},
                                  paths=self.p, now=NOW)
        self.assertEqual(n, 0)
        n = Q.reconcile_delivered({"members": [{"person_key": "p_000000000001", "linked": [W.PERSON_KEY],
                                                "periods": [{"sha12": it.sha256[:12]}]}]}, paths=self.p, now=NOW)
        self.assertEqual(n, 1)


if __name__ == "__main__":
    unittest.main()
