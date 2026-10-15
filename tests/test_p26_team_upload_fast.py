# -*- coding: utf-8 -*-
r"""tests\test_p26_team_upload_fast.py — 팀 서버 업로드가 오래 붙잡지 않는다(LM28 사용자 요청:
"시도 1-2번 해서 안 되면 아닌 값… 업로드 부분에서 기다리는 건 너무 로스").

  · teamup.wait_limits — 기본 연결 확인 3초 × 2번 · 답 45초 · 범위 밖은 접힘 · 가장 긴 설정도 run.py 상한 안
  · teamup.ping — 최대 2번(사이 쉼) · 두 번째에 닿으면 성공
  · teamup.upload_one/upload_all — 연결 실패만 1번 다시 · 본문을 보낸 뒤 답이 늦으면(slow) 다시 보내지 않음 ·
    닿지 않거나 늦으면 남은 묶음을 멈추고 대기로 남김(left·stopped) · 거부(rejected)는 다음 묶음으로 넘어감 ·
    시간 상한(budget)을 넘기면 새 묶음을 시작하지 않음 · 예전 서버(aggregated)·새 서버(queued) 답 둘 다 이해
  · run.team_report_outcome — slow 갈래 · 멈춘 사유가 이번 실패의 사유 · 시간 상한으로 남김 · run.team_report 상한 150초
  · teamserver — 저장하자마자 답(queued:true · aggregated:"queued") · 취합은 일꾼 하나가 돌리고 몰린 업로드는 한 번으로 합침 ·
    취합은 늘 하나 · /api/team·GET / 에 '취합 중' · [지금 다시 취합]은 그대로 직접 · 꺼진 사이 남은 취합은 다음 시작 때 이어서
새 프로세스를 띄우지 않는다(서버는 같은 프로세스의 스레드 · aggregate.py 는 가짜). 시간 상한은 1초 아래로 줄여 잰다.
임시 폴더만 쓴다. 이름은 합성(홍길동)."""
import contextlib
import http.client
import io
import json
import os
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

import _boot

import run as R  # noqa: E402
import teamserver as TS  # noqa: E402
import teamup  # noqa: E402

ROOT = _boot.ROOT
TAGS = ("20250101-20250630", "20250701-20251231", "20260101-20260930")


def _until(cond, sec=3.0):
    """cond() 가 참이 될 때까지 짧게 기다린다(최대 sec) → 마지막 값"""
    end = time.monotonic() + sec
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return bool(cond())


# ── 가짜 팀 서버(클라이언트 시험용) ─────────────────────────────────────────────────────────────
class _Stub(BaseHTTPRequestHandler):
    mode = "new"                 # new(queued) · old_ok · old_fail · slow · drop · reject
    posts = []
    release = threading.Event()

    def log_message(self, *a):
        pass

    def _j(self, code, obj):
        b = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        try:
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)
        except OSError:          # 늦은 답 — 클라이언트는 이미 끊고 갔다
            pass

    def do_GET(self):
        self._j(200, {"ok": True})

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0) or 0))
        _Stub.posts.append(json.loads(body.decode("utf-8")).get("member", {}).get("tag"))
        m = _Stub.mode
        if m == "slow":
            _Stub.release.wait(3)                     # 본문은 받았는데 답이 늦다(취합에 줄 선 예전 서버)
            self._j(200, {"ok": True, "saved": 1, "aggregated": True})
        elif m == "drop":
            self.close_connection = True              # 받기만 하고 답 없이 끊는다
        elif m == "reject":
            self._j(400, {"ok": False, "error": "member 객체 아님"})
        elif m == "new":
            self._j(200, {"ok": True, "saved": 1, "aggregated": None, "queued": True})
        else:
            self._j(200, {"ok": True, "saved": 1, "aggregated": m == "old_ok"})


class _ClientBase(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(prefix="lm29_p26_")
        self.rep = os.path.join(self._td.name, "report")
        self.pend = os.path.join(self.rep, "upload_pending")
        os.makedirs(self.pend)
        self._pt = [mock.patch.object(teamup, "REPORT", self.rep), mock.patch.object(teamup, "PENDING", self.pend),
                    mock.patch.object(teamup, "SENT", os.path.join(self.rep, "upload_sent")),
                    mock.patch.object(teamup, "RETRY_PAUSE", 0.0),
                    mock.patch.object(teamup, "load_cfg", lambda: {})]
        for p in self._pt:
            p.start()
        # 시스템 프록시가 127.0.0.1 요청을 가로채지 않게(이 시험 동안만) — 업로드 오프너도 이 설정을 따른다(_proxy_handler)
        urllib.request.install_opener(urllib.request.build_opener(urllib.request.ProxyHandler({})))
        _Stub.mode, _Stub.posts = "new", []
        _Stub.release = threading.Event()
        self.srv = None

    def tearDown(self):
        _Stub.release.set()
        if self.srv:
            self.srv.shutdown()
            self.srv.server_close()
        urllib.request.install_opener(None)
        for p in reversed(self._pt):
            p.stop()
        self._td.cleanup()

    def serve(self, mode="new"):
        _Stub.mode = mode
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), _Stub)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        return f"http://127.0.0.1:{self.srv.server_address[1]}"

    def bundles(self, *tags):
        for t in tags:
            with open(os.path.join(self.pend, f"{t}.json"), "w", encoding="utf-8") as f:
                json.dump({"member": {"owner": "홍길동", "tag": t}, "files": {f"mm_meta_{t}.json": "{}"},
                           "built": "2026-10-15 09:00", "blocked": []}, f, ensure_ascii=False)

    def pending(self):
        return sorted(n for n in os.listdir(self.pend) if n.endswith(".json"))

    def up(self, url, timeout=0.4, connect_timeout=0.5, budget=60.0):
        with contextlib.redirect_stdout(io.StringIO()):
            return teamup.upload_all(url, timeout=timeout, connect_timeout=connect_timeout, budget=budget)


# ── 기다림 값 ──────────────────────────────────────────────────────────────────────────────────
class WaitLimits(unittest.TestCase):
    def test_defaults(self):
        for c in ({}, None, "x", {"teamUpload": "x"}, {"teamUpload": {"autoReport": True}}):
            self.assertEqual(teamup.wait_limits(c), {"ping_tries": 2, "ping_timeout": 3.0, "timeout": 45.0}, c)

    def test_clamp_and_bad_values(self):
        w = teamup.wait_limits({"teamUpload": {"pingTries": 9, "pingTimeoutSec": 0, "timeoutSec": "600"}})
        self.assertEqual(w, {"ping_tries": 3, "ping_timeout": 1.0, "timeout": 90.0})
        w = teamup.wait_limits({"teamUpload": {"pingTries": True, "pingTimeoutSec": "abc", "timeoutSec": float("nan")}})
        self.assertEqual(w, {"ping_tries": 2, "ping_timeout": 3.0, "timeout": 45.0})
        self.assertEqual(teamup.wait_limits({"teamUpload": {"pingTries": 1, "timeoutSec": 20}})["timeout"], 20.0)

    def test_worst_case_fits_run_cap(self):
        hi_t = teamup._WAIT_RANGE["pingTries"][1]
        hi_p = teamup._WAIT_RANGE["pingTimeoutSec"][1]
        hi_w = teamup._WAIT_RANGE["timeoutSec"][1]
        ping = hi_t * hi_p + (hi_t - 1) * teamup.RETRY_PAUSE
        first = max(2 * hi_p + teamup.RETRY_PAUSE, hi_w)          # 첫 묶음: 연결 2번 또는 답 기다림
        self.assertLess(ping + first + 10, R.TR_CAP_SEC)           # 10초 = 파이썬 시작·묶음 변환 여유
        d = teamup.wait_limits({})
        self.assertLessEqual(d["ping_tries"] * d["ping_timeout"] + teamup.RETRY_PAUSE, 8.0)   # 닿지 않는 망 8초 안
        self.assertLessEqual(R.TR_CAP_SEC, 180)

    def test_config_default_ships_keys(self):
        with open(os.path.join(ROOT, "config", "config.default.json"), "rb") as f:
            raw = f.read()
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))           # config 는 BOM 을 지킨다
        c = json.loads(raw.decode("utf-8-sig"))
        self.assertEqual({k: c["teamUpload"][k] for k in ("pingTries", "pingTimeoutSec", "timeoutSec")},
                         {"pingTries": 2, "pingTimeoutSec": 3, "timeoutSec": 45})
        for k in ("pingTries", "pingTimeoutSec", "timeoutSec"):
            self.assertIn(k, c["_팀업로드_설명"])


# ── 연결 확인 ──────────────────────────────────────────────────────────────────────────────────
class Ping(_ClientBase):
    def test_two_tries_then_gives_up(self):
        seen = []

        def boom(req, timeout=None):
            seen.append(timeout)
            raise urllib.error.URLError(ConnectionRefusedError(10061, "refused"))
        with mock.patch.object(urllib.request, "urlopen", boom):
            r = teamup.ping("http://127.0.0.1:9")
        self.assertEqual((r["ok"], r["tries"], seen), (False, 2, [3.0, 3.0]))   # 설정 없으면 3초 × 2번
        self.assertIn("대기", r["hint"])

    def test_second_try_reaches(self):
        url = self.serve()
        real, n = urllib.request.urlopen, []

        def flaky(req, timeout=None):
            n.append(1)
            if len(n) == 1:
                raise urllib.error.URLError(TimeoutError("timed out"))
            return real(req, timeout=timeout)
        with mock.patch.object(urllib.request, "urlopen", flaky):
            r = teamup.ping(url, timeout=0.5)
        self.assertEqual((r["ok"], r["tries"]), (True, 2))

    def test_bad_address_no_retry(self):
        r = teamup.ping("x", timeout=0.2, tries=2)                 # 주소 형식 오류 — 다시 해도 같다
        self.assertEqual((r["ok"], r["tries"]), (False, 1))


# ── 업로드 ─────────────────────────────────────────────────────────────────────────────────────
class Upload(_ClientBase):
    def test_new_server_queued(self):
        self.bundles(TAGS[2])
        r = self.up(self.serve("new"))
        x = r["results"][0]
        self.assertEqual((r["ok"], r["sent"], r["left"], x["kind"]), (True, 1, 0, "sent"))
        self.assertIn("저장됨 — 팀 취합은 서버가 이어서 갱신합니다", x["msg"])
        self.assertNotIn("갱신 실패", x["msg"])
        self.assertEqual(self.pending(), [])

    def test_old_server_reply(self):
        self.bundles(TAGS[2])
        self.assertIn("팀 취합 갱신됨", self.up(self.serve("old_ok"))["results"][0]["msg"])
        self.srv.shutdown()
        self.srv.server_close()
        self.bundles(TAGS[1])
        x = self.up(self.serve("old_fail"))["results"][0]
        self.assertEqual(x["kind"], "sent")                        # 저장은 됐다 — 취합 실패는 문구로만
        self.assertIn("갱신 실패", x["msg"])

    def test_slow_reply_not_resent_and_stops_rest(self):
        self.bundles(*TAGS)
        t0 = time.monotonic()
        r = self.up(self.serve("slow"), timeout=0.3)
        self.assertLess(time.monotonic() - t0, 2.5)
        self.assertEqual(_Stub.posts, [TAGS[0]])                   # 한 번만 보냈다(서버가 저장했을 수 있다)
        self.assertEqual((r["ok"], r["sent"], r["failed"], r["left"]), (False, 0, 1, 2))
        x = r["results"][0]
        self.assertEqual(x["kind"], "slow")
        self.assertIn("서버에 저장됐을 수 있습니다", x["msg"])
        self.assertIn("덮어쓰기라 결과는 같습니다", x["msg"])
        self.assertIn("나머지 2건", r["stopped"])
        self.assertEqual(self.pending(), [f"{t}.json" for t in TAGS])   # 전부 대기 그대로
        st = R.team_report_outcome(dict(r, pending=3), TAGS[2])
        self.assertEqual((st["ok"], st["reason"]), (False, "서버 응답 지연"))
        self.assertIn("다음 실행 때 다시", st["hint"])

    def test_drop_after_send_not_resent(self):
        self.bundles(TAGS[0], TAGS[1])
        r = self.up(self.serve("drop"))
        self.assertEqual(_Stub.posts, [TAGS[0]])
        self.assertEqual((r["results"][0]["kind"], r["left"]), ("unreachable", 1))
        self.assertIn("저장됐을 수 있습니다", r["results"][0]["msg"])

    def test_connect_failure_retried_once(self):
        self.bundles(TAGS[2])
        url = self.serve("new")
        orig, calls = teamup._PhaseConn.connect, []

        def flaky(conn):
            calls.append(conn._phase[0])
            if len(calls) == 1:
                raise ConnectionRefusedError(10061, "refused")
            return orig(conn)
        with mock.patch.object(teamup._PhaseConn, "connect", flaky):
            r = self.up(url)
        self.assertEqual((r["ok"], r["sent"], len(calls), _Stub.posts), (True, 1, 2, [TAGS[2]]))

    def test_connect_failure_twice_stops(self):
        self.bundles(*TAGS)
        url = self.serve("new")
        calls = []

        def dead(conn):
            calls.append(1)
            raise TimeoutError("timed out")
        with mock.patch.object(teamup._PhaseConn, "connect", dead):
            r = self.up(url)
        self.assertEqual(len(calls), 2)                            # 1번만 다시 — 남은 묶음은 시도하지 않는다
        self.assertEqual((r["results"][0]["kind"], r["left"], _Stub.posts), ("unreachable", 2, []))
        self.assertIn("2번 시도", r["results"][0]["msg"])
        self.assertIn("서버 연결 실패로 나머지 2건", r["stopped"])
        self.assertEqual(len(self.pending()), 3)

    def test_rejected_moves_on(self):
        self.bundles(TAGS[0], TAGS[1])
        r = self.up(self.serve("reject"))
        self.assertEqual([x["kind"] for x in r["results"]], ["rejected", "rejected"])   # 서버는 답했다 — 다음 묶음으로
        self.assertEqual((r["left"], len(_Stub.posts)), (0, 2))
        self.assertNotIn("stopped", r)

    def test_budget_stops_new_bundles(self):
        self.bundles(*TAGS)
        r = self.up(self.serve("new"), timeout=1.0, budget=0.5)    # 첫 묶음은 늘 보낸다 — 다음은 답 상한까지 여유가 없다
        self.assertEqual((r["ok"], r["sent"], r["failed"], r["left"]), (False, 1, 0, 2))
        self.assertIn("시간 상한", r["stopped"])
        self.assertEqual(len(self.pending()), 2)
        st = R.team_report_outcome(dict(r, pending=2), TAGS[2])
        self.assertEqual((st["ok"], st["reason"]), (False, "시간 상한으로 남김"))
        self.assertIn("[팀 서버 업로드]", st["hint"])
        ok = R.team_report_outcome(dict(r, pending=2), TAGS[0])
        self.assertTrue(ok["ok"])
        self.assertIn("2건은 이번에 보내지 않고", ok["detail"])

    def test_main_upload_json(self):
        self.bundles(TAGS[2])
        url = self.serve("new")
        out = io.StringIO()
        with mock.patch.object(sys, "argv", ["teamup.py", "--upload", "--json", "--url", url]), \
                contextlib.redirect_stdout(out):
            rc = teamup.main()
        res = json.loads([x for x in out.getvalue().splitlines() if x.strip()][-1])
        self.assertEqual((rc, res["sent"], res["left"], res["pending"]), (0, 1, 0, 0))
        self.assertTrue(R.team_report_outcome(res, TAGS[2])["ok"])

    def test_proxy_follows_installed_opener(self):
        self.assertEqual(teamup._proxy_handler().proxies, {})
        urllib.request.install_opener(None)
        with mock.patch.object(urllib.request, "getproxies", lambda: {"http": "http://proxy.invalid:8080"}):
            self.assertEqual(teamup._proxy_handler().proxies, {"http": "http://proxy.invalid:8080"})


# ── run.py 자동 보고 ───────────────────────────────────────────────────────────────────────────
class RunReport(unittest.TestCase):
    def test_kind_and_halt_priority(self):
        self.assertEqual(R.TR_KIND["slow"], "서버 응답 지연")
        self.assertIn("서버 응답 지연", R.TR_HINT)
        res = {"ok": False, "sent": 0, "failed": 2, "left": 1, "pending": 3, "results": [
            {"file": "a.json", "tag": TAGS[0], "ok": False, "msg": "파일명", "kind": "blocked"},
            {"file": "b.json", "tag": TAGS[1], "ok": False, "msg": "늦음", "kind": "slow"}]}
        st = R.team_report_outcome(res, TAGS[2])                   # 이번 묶음은 멈춘 뒤 남았다
        self.assertEqual((st["reason"], st["detail"]), ("서버 응답 지연", "늦음"))

    def test_cap_passed_to_run_step(self):
        seen = []
        saved = (R._RUN_STEP, dict(R.REPORT_DIR), list(R.RUN["stages"]))
        with tempfile.TemporaryDirectory(prefix="lm29_p26_") as tmp:
            R.REPORT_DIR["p"] = tmp
            R.RUN["stages"] = []

            def f(cmd, timeout, name=""):
                seen.append(timeout)
                return -1, ["시간 초과"], "timeout"
            R._RUN_STEP = f
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    st = R.team_report({}, "2026-01-01", "2026-09-30")
            finally:
                R._RUN_STEP, rep, R.RUN["stages"] = saved[0], saved[1], saved[2]
                R.REPORT_DIR.clear()
                R.REPORT_DIR.update(rep)
        self.assertEqual(seen, [R.TR_CAP_SEC])
        self.assertEqual(st["detail"], f"{R.TR_CAP_SEC}초 안에 끝나지 않아 끊었습니다")


# ── 팀 서버 — 먼저 답하고 취합은 뒤에서 ────────────────────────────────────────────────────────
class Server(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(prefix="lm29_p26_srv_")
        self.gate = threading.Event()
        self.calls, self.live, self.peak = [], [0], [0]
        self._pt = [mock.patch.object(TS, "TEAMDATA", self._td.name),
                    mock.patch.object(TS, "_run_aggregate_once", self.fake_agg),
                    mock.patch.object(TS, "print", lambda *a, **k: None, create=True)]
        for p in self._pt:
            p.start()
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), TS.H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.port = self.srv.server_address[1]

    def tearDown(self):
        self.gate.set()
        _until(self.idle)
        self.srv.shutdown()
        self.srv.server_close()
        for p in reversed(self._pt):
            p.stop()
        self._td.cleanup()

    def fake_agg(self):
        self.live[0] += 1
        self.peak[0] = max(self.peak[0], self.live[0])
        self.calls.append(time.monotonic())
        self.gate.wait(3)
        self.live[0] -= 1
        with TS.LOCK:
            TS.STATE["agg_note"] = "OK (0s) 가짜 취합"
        return True

    def idle(self):
        with TS.AGG_CV:
            return not TS.AGG_Q["busy"] and not TS.AGG_Q["dirty"] and not TS.AGG_LOCK.locked()

    def req(self, method, path, obj=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8") if obj is not None else None
        c.request(method, path, body=body, headers={"Content-Type": "application/json"} if body else {})
        r = c.getresponse()
        data = r.read()
        c.close()
        return r.status, data.decode("utf-8", "replace")

    def upload(self, owner):
        t0 = time.monotonic()
        code, txt = self.req("POST", "/api/upload", {"member": {"owner": owner},
                                                     "files": {"mm_meta_20260101-20260930.json": "{}"}})
        return code, json.loads(txt), time.monotonic() - t0

    def test_replies_before_aggregation_and_coalesces(self):
        code, res, dt = self.upload("홍길동")
        self.assertEqual(code, 200)
        self.assertEqual((res["ok"], res["saved"], res["aggregated"], res["queued"]), (True, 1, "queued", True))
        self.assertLess(dt, 2.0)                                   # 취합(막혀 있음)을 기다리지 않았다
        self.assertTrue(os.path.isfile(os.path.join(self._td.name, "홍길동", "member.json")))
        self.assertTrue(_until(lambda: len(self.calls) == 1))
        for who in ("김철수", "이영희", "박민수"):                     # 취합 중에 몰린 업로드
            code, res, dt = self.upload(who)
            self.assertEqual((code, res["queued"]), (200, True))
            self.assertLess(dt, 2.0)
        _c, team = self.req("GET", "/api/team")
        t = json.loads(team)
        self.assertTrue(t["agg_status"].startswith("취합 중"))
        self.assertIn("한 번 더", t["agg_status"])
        self.assertTrue(t["agg_note"].startswith("취합 중"))
        _c, page = self.req("GET", "/")
        self.assertIn("취합 중", page)
        self.gate.set()
        self.assertTrue(_until(self.idle))
        time.sleep(0.05)
        self.assertEqual(len(self.calls), 2)                       # 처음 1번 + 몰린 3건을 합친 1번
        self.assertEqual(self.peak[0], 1)                          # aggregate 는 늘 하나
        t = json.loads(self.req("GET", "/api/team")[1])
        self.assertEqual((t["agg_status"], t["agg_note"]), ("", "OK (0s) 가짜 취합"))
        self.assertEqual(sum(1 for th in threading.enumerate() if th.name == "team-aggregate"), 1)

    def test_request_burst_one_worker(self):
        for _ in range(5):
            TS.request_aggregate()
        self.assertTrue(_until(lambda: len(self.calls) == 1))
        for _ in range(5):                                         # 도는 중에 다시 몰림 — 예약은 하나로 접힌다
            TS.request_aggregate()
        self.assertEqual(TS.agg_status(), "취합 중 — 끝나면 한 번 더 돕니다")
        self.gate.set()
        self.assertTrue(_until(self.idle))
        time.sleep(0.05)
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(TS.agg_status(), "")

    def test_refresh_still_direct(self):
        self.gate.set()
        code, _t = self.req("GET", "/refresh")
        self.assertIn(code, (200, 302))
        self.assertEqual(len(self.calls), 1)                       # 답하기 전에 끝났다(화면이 새 결과를 본다)

    def test_stale_after_restart(self):
        d = self._td.name
        self.assertFalse(TS.agg_stale())                           # 인원 없음
        os.makedirs(os.path.join(d, "홍길동"))
        mj = os.path.join(d, "홍길동", "member.json")
        with open(mj, "w", encoding="utf-8") as f:
            f.write("{}")
        self.assertTrue(TS.agg_stale())                           # 리포트 없음
        rep = os.path.join(d, "team_report.html")
        with open(rep, "w", encoding="utf-8") as f:
            f.write("<html></html>")
        os.utime(mj, (time.time() - 60, time.time() - 60))
        self.assertFalse(TS.agg_stale())
        os.utime(mj, (time.time() + 60, time.time() + 60))
        self.assertTrue(TS.agg_stale())


if __name__ == "__main__":
    unittest.main()
