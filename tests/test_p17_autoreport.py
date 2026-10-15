# -*- coding: utf-8 -*-
r"""tests\test_p17_autoreport.py — [분석 실행] 끝 팀 서버 자동 보고(LM28 B3·B4) · 버튼 [로컬PC 자료수집](B1·B2).

  · teamup.auto_report_on — 기본 켬 · autoReport=false 끔 · 옛 auto(true·false)는 끄기로 보지 않음 · 배포 설정 두 벌
  · run.team_report_outcome — teamup --upload --json 갈래(닿지 않음·거부·보낼 수 없음·보냄·대기 없음·주소 없음·JSON 없음)
  · run.team_report — _RUN_STEP 주입(실제 teamup·서버 없음) → last_run.json 단계 · report\team_report_status.json · 콘솔
  · teamup --upload --json 의 기계용 표식(kind·no_url·pending)과 '다 보냄' 기록 — 같은 프로세스의 임시 포트 가짜 서버
  · [로컬PC 자료수집](--collect-only)은 teamup 을 부르지 않는다(run._main · 임시 ROOT · 가짜 수집기) ·
    [분석 실행]과 같은 수집기를 돌리고 Copilot 경로만 뺀다(B2)
  · 화면(PAGE) — 버튼 순서·id·글자·툴팁·색 · 알림/배너 배선 · /api/teamreport · 얼린 사본에 굽지 않음
새 프로세스를 띄우지 않는다(서버는 ThreadingHTTPServer 스레드). 임시 폴더만 쓴다. 이름은 합성(홍길동)."""
import contextlib
import http.client
import io
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

import _boot

import app  # noqa: E402  — ui\app.py (임포트 부작용 없음)
import run as R  # noqa: E402
import teamup  # noqa: E402

ROOT = _boot.ROOT
D0, D1 = "2026-01-01", "2026-09-30"
TAG = "20260101-20260930"
OLD = "20250101-20251231"
PEND_HINT = "결과 묶음은 대기로 남았습니다. 사내망에서 [팀 서버 업로드]를 누르면 밀린 것까지 보내집니다."


def _quiet():
    return contextlib.redirect_stdout(io.StringIO())


def _status(rep):
    with open(os.path.join(rep, teamup.REPORT_STATUS), encoding="utf-8") as f:
        return json.load(f)


# ── 켜고 끄기 ─────────────────────────────────────────────────────────────────────────────────
class AutoReportSwitch(unittest.TestCase):
    def test_defaults_and_legacy(self):
        on = teamup.auto_report_on
        for c in ({}, None, "x", {"teamUpload": {}}, {"teamUpload": "x"}, {"teamUpload": {"autoReport": None}},
                  {"teamUpload": {"autoReport": ""}}, {"teamUpload": {"autoReport": True}},
                  {"teamUpload": {"autoReport": "true"}}, {"teamUpload": {"autoReport": 1}},
                  {"teamUpload": {"auto": True}}, {"teamUpload": {"auto": False}}):     # 옛 auto:false = 옛 기본값
            self.assertTrue(on(c), c)
        for v in (False, "false", "FALSE", " off ", "no", 0, "0"):
            self.assertFalse(on({"teamUpload": {"autoReport": v}}), v)
        self.assertFalse(on({"teamUpload": {"autoReport": False, "auto": True}}))       # 새 키가 이긴다
        self.assertTrue(R.team_report_wanted({"teamUpload": {"auto": False}}))          # run.py 도 같은 한 함수
        self.assertFalse(R.team_report_wanted({"teamUpload": {"autoReport": False}}))

    def test_config_files_ship_on(self):
        for name in ("config.default.json", "config.json"):
            with open(os.path.join(ROOT, "config", name), encoding="utf-8-sig") as f:
                c = json.load(f)
            self.assertIs(c["teamUpload"].get("autoReport"), True, name)
            self.assertNotIn("auto", c["teamUpload"], name)
            self.assertIn("autoReport", c["_팀업로드_설명"], name)
            self.assertIn("로컬PC 자료수집", c["_수집만무창_설명"], name)

    def test_status_auto_uses_switch(self):
        with tempfile.TemporaryDirectory(prefix="lm28_p17_") as tmp, \
                mock.patch.object(teamup, "REPORT", tmp), \
                mock.patch.object(teamup, "PENDING", os.path.join(tmp, "upload_pending")), \
                mock.patch.object(teamup, "SENT", os.path.join(tmp, "upload_sent")):
            self.assertTrue(teamup.status({"teamUpload": {"auto": False}})["auto"])
            self.assertFalse(teamup.status({"teamUpload": {"autoReport": False}})["auto"])


# ── 사유 가르기 ───────────────────────────────────────────────────────────────────────────────
def _res(*items, ok=None, pending=0):
    rs = [{"file": f"{t}.json", "tag": t, "ok": k == "sent", "msg": m, "kind": k} for t, k, m in items]
    sent = sum(1 for x in rs if x["ok"])
    return {"ok": (len(rs) == sent) if ok is None else ok, "sent": sent, "failed": len(rs) - sent,
            "results": rs, "pending": pending}


class Outcome(unittest.TestCase):
    def test_unreachable(self):
        st = R.team_report_outcome({"ok": False, "error": "timed out", "hint": "x", "unreachable": True, "pending": 2}, TAG)
        self.assertEqual((st["ok"], st["reason"], st["pending"], st["detail"]), (False, "서버에 닿지 않음", 2, "timed out"))
        self.assertEqual(st["hint"], PEND_HINT)

    def test_kinds(self):
        for kind, want in (("rejected", "서버 거부"), ("blocked", "보낼 수 없는 묶음"), ("unreachable", "서버에 닿지 않음"),
                           ("", "보고 실패")):
            st = R.team_report_outcome(_res((TAG, kind, "사유 문구"), pending=1), TAG)
            self.assertEqual((st["ok"], st["reason"], st["detail"], st["pending"]), (False, want, "사유 문구", 1), kind)
            self.assertTrue(st["hint"])
        self.assertTrue(R.team_report_outcome(_res((TAG, "rejected", "")), TAG)["hint"].startswith(PEND_HINT))

    def test_ok(self):
        st = R.team_report_outcome(_res((TAG, "sent", "9개 파일 저장")), TAG)
        self.assertEqual((st["ok"], st["sent"], st["failed"], st["reason"], st["hint"]), (True, 1, 0, "", ""))

    def test_ok_even_if_old_bundle_failed(self):
        st = R.team_report_outcome(_res((OLD, "blocked", "서버가 받지 않는 파일명"), (TAG, "sent", "저장"), pending=1), TAG)
        self.assertTrue(st["ok"])
        self.assertIn("다른 묶음 1건", st["detail"])

    def test_this_bundle_failed_even_if_old_sent(self):
        st = R.team_report_outcome(_res((OLD, "sent", "저장"), (TAG, "rejected", "HTTP 500")), TAG)
        self.assertEqual((st["ok"], st["reason"], st["sent"]), (False, "서버 거부", 1))

    def test_nothing_pending(self):
        res = {"ok": True, "sent": 0, "failed": 0, "results": [], "note": "보낼 대기 묶음이 없습니다", "pending": 0}
        st = R.team_report_outcome(res, TAG)
        self.assertEqual((st["ok"], st["reason"]), (False, "대기 묶음 없음"))
        self.assertEqual(R.team_report_outcome(res, TAG, built=False)["reason"], "대기 묶음 없음")

    def test_not_built(self):
        st = R.team_report_outcome(_res((OLD, "sent", "저장")), TAG, built=False)
        self.assertEqual((st["ok"], st["reason"]), (False, "이번 결과 묶음 없음"))
        self.assertIn("1건은 보냈습니다", st["hint"])
        # 같은 기간의 지난 묶음이 대신 갔어도 이번 결과가 아니다
        self.assertFalse(R.team_report_outcome(_res((TAG, "sent", "저장")), TAG, built=False)["ok"])

    def test_no_url_and_no_json(self):
        st = R.team_report_outcome({"ok": False, "error": "주소 형식", "no_url": True, "pending": 1}, TAG)
        self.assertEqual((st["reason"], st["pending"]), ("주소 없음", 1))
        self.assertIn("LoadMonitor29-팀서버주소.bat", st["hint"])
        for res in ({}, None, "x"):
            self.assertEqual(R.team_report_outcome(res, TAG)["reason"], "보고 결과를 읽지 못함")
        self.assertEqual(R.team_report_outcome({"ok": False, "error": "그 밖"}, TAG)["reason"], "보고 실패")


# ── run.team_report — 단계·상태 파일·콘솔 ──────────────────────────────────────────────────────
class TeamReportStage(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(prefix="lm28_p17_")
        self.rep = os.path.join(self._td.name, "report")
        self._saved = (R._RUN_STEP, dict(R.REPORT_DIR), list(R.RUN["stages"]))
        R.REPORT_DIR["p"] = self.rep
        R.RUN["stages"] = []
        self.calls = []

    def tearDown(self):
        R._RUN_STEP, rep, stages = self._saved
        R.REPORT_DIR.clear()
        R.REPORT_DIR.update(rep)
        R.RUN["stages"] = stages
        self._td.cleanup()

    def fake(self, lines, rc=0, how="ok"):
        def f(cmd, timeout, name=""):
            self.calls.append([str(x) for x in cmd])
            return rc, list(lines), how
        R._RUN_STEP = f

    def stage(self):
        got = [x for x in R.RUN["stages"] if x["name"] == "팀 서버 자동 보고"]
        self.assertEqual(len(got), 1)
        return got[0]

    def go(self, c=None, built=True):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            st = R.team_report(c or {}, D0, D1, built=built)
        return st, out.getvalue()

    def test_unreachable(self):
        js = json.dumps({"ok": False, "error": "timed out", "hint": "x", "unreachable": True, "pending": 1}, ensure_ascii=False)
        self.fake(["[teamup] 이 망에서 서버에 닿지 않습니다 — timed out", "묶음 1건은 그대로 대기합니다.", js], rc=1)
        st, printed = self.go()
        self.assertEqual(os.path.basename(self.calls[0][1]), "teamup.py")
        self.assertEqual(self.calls[0][2:], ["--upload", "--json"])
        s = _status(self.rep)
        self.assertEqual((s["ok"], s["reason"], s["hint"], s["via"], s["tag"], s["pending"]),
                         (False, "서버에 닿지 않음", PEND_HINT, "auto", TAG, 1))
        self.assertRegex(s["at"], r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d$")
        self.assertEqual(st["reason"], "서버에 닿지 않음")
        sg = self.stage()
        self.assertFalse(sg["ok"])
        self.assertIn("실패: 서버에 닿지 않음", sg["note"])
        self.assertNotIn("timed out", sg["note"])               # 응답 원문은 last_run.json(얼린 사본에 굳는다)에 싣지 않는다
        self.assertNotIn('{"ok"', printed)                       # 기계용 JSON 줄은 콘솔에 찍지 않는다
        self.assertIn("   [teamup] 이 망에서 서버에 닿지 않습니다", printed)
        self.assertIn("[!] 팀 서버 자동 보고 실패 — 서버에 닿지 않음", printed)

    def test_ok(self):
        res = _res((TAG, "sent", "1개 파일 저장, 팀 취합 갱신됨"))
        self.fake(["[teamup] 전송 완료: 성공 1 / 실패 0", json.dumps(res, ensure_ascii=False)])
        st, printed = self.go()
        s = _status(self.rep)
        self.assertEqual((s["ok"], s["sent"], s["reason"], s["via"]), (True, 1, "", "auto"))
        self.assertTrue(self.stage()["ok"])
        self.assertIn("보냄 1건", self.stage()["note"])
        self.assertIn("팀 서버 보고 완료 — 1건", printed)

    def test_off_and_stub_never_call_teamup(self):
        self.fake([])
        st, printed = self.go({"teamUpload": {"autoReport": False}})
        self.assertIsNone(st)
        self.assertEqual(self.calls, [])
        s = _status(self.rep)
        self.assertEqual((s["ok"], s["off"]), (None, True))
        self.assertTrue(self.stage()["ok"])
        self.assertIn("꺼짐", self.stage()["note"])
        R.RUN["stages"] = []
        with mock.patch.dict(os.environ, {"LM_COPILOT_STUB": "1"}):
            self.assertIsNone(self.go()[0])
        self.assertEqual(self.calls, [])                          # 스텁 판정 결과는 팀 서버로 가지 않는다
        self.assertIn("스텁", self.stage()["note"])

    def test_timeout_without_json(self):
        self.fake(["시간 초과(150s) — 트리째 정리하고 건너뜀"], rc=-1, how="timeout")
        st, _p = self.go()
        s = _status(self.rep)
        self.assertEqual((s["ok"], s["reason"], s["detail"]), (False, "보고 결과를 읽지 못함", "150초 안에 끝나지 않아 끊었습니다"))
        self.assertTrue(s["hint"].startswith(PEND_HINT))

    def test_build_failed(self):
        self.fake([json.dumps({"ok": True, "sent": 0, "failed": 0, "results": [], "pending": 0})])
        st, _p = self.go(built=False)
        self.assertEqual((st["ok"], st["reason"]), (False, "대기 묶음 없음"))

    def test_ai_failed_holds_with_alarm(self):
        # AI 판정이 전부 실패한 실행 — 규칙 임시 결과가 서버의 지난 결과를 덮지 않게 보내지 않고, 실패(알림·배너)로 남긴다
        self.fake([])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            st = R.team_report({}, D0, D1, built=True, hold="AI 판정 실패")
        self.assertEqual(self.calls, [])                          # teamup 을 부르지 않는다
        self.assertEqual((st["ok"], st["reason"]), (False, "AI 판정 실패로 보내지 않음"))
        s = _status(self.rep)
        self.assertEqual((s["ok"], s["reason"], s["via"], s["tag"]), (False, "AI 판정 실패로 보내지 않음", "auto", TAG))
        self.assertRegex(s["at"], r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d$")   # 화면이 이 값으로 '실행 1번당 알림 1번' 을 가른다
        self.assertIn("[팀 서버 업로드]", s["hint"])
        self.assertFalse(self.stage()["ok"])
        self.assertIn("보내지 않음", out.getvalue())

    def test_no_ai_run_skips_quietly(self):
        self.fake([])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            st = R.team_report({}, D0, D1, built=True, hold="AI 없이 실행")
        self.assertIsNone(st)                                     # 알림 없음 — 카드에 '건너뜀' 만
        self.assertEqual(self.calls, [])
        s = _status(self.rep)
        self.assertEqual((s["ok"], s["reason"]), (None, "AI 정제 없이 실행해 보내지 않음"))
        self.assertTrue(self.stage()["ok"])

    def test_hold_respects_off_switch(self):
        self.fake([])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            st = R.team_report({"teamUpload": {"autoReport": False}}, D0, D1, hold="AI 판정 실패")
        self.assertIsNone(st)                                     # 끈 사람에게는 판정 실패여도 알림을 띄우지 않는다
        self.assertEqual(_status(self.rep)["off"], True)


# ── teamup --upload --json 의 기계용 표식 ─────────────────────────────────────────────────────
class _FakeTeamServer(BaseHTTPRequestHandler):
    mode = "ok"

    def log_message(self, *a):
        pass

    def _j(self, code, obj):
        b = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):                    # teamup ping(/api/team)
        self._j(200, {"ok": True})

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", 0) or 0))
        if _FakeTeamServer.mode == "reject":
            self._j(400, {"ok": False, "error": "member 객체 아님"})
        else:
            self._j(200, {"ok": True, "saved": 1, "aggregated": True})


class TeamupJson(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(prefix="lm28_p17_")
        self.rep = os.path.join(self._td.name, "report")
        self.pend = os.path.join(self.rep, "upload_pending")
        os.makedirs(self.pend)
        self._pt = [mock.patch.object(teamup, "REPORT", self.rep), mock.patch.object(teamup, "PENDING", self.pend),
                    mock.patch.object(teamup, "SENT", os.path.join(self.rep, "upload_sent"))]
        for p in self._pt:
            p.start()
        # 시스템 프록시가 127.0.0.1 요청을 가로채지 않게(이 시험 동안만)
        urllib.request.install_opener(urllib.request.build_opener(urllib.request.ProxyHandler({})))
        self.srv = None

    def tearDown(self):
        if self.srv:
            self.srv.shutdown()
            self.srv.server_close()
        urllib.request.install_opener(None)
        for p in reversed(self._pt):
            p.stop()
        _FakeTeamServer.mode = "ok"
        self._td.cleanup()

    def bundle(self, files=None):
        with open(os.path.join(self.pend, f"{TAG}.json"), "w", encoding="utf-8") as f:
            json.dump({"member": {"owner": "홍길동", "tag": TAG, "period": [D0, D1]},
                       "files": files or {f"mm_meta_{TAG}.json": "{}"}, "built": "2026-10-14 09:00", "blocked": []},
                      f, ensure_ascii=False)

    def serve(self, mode="ok"):
        _FakeTeamServer.mode = mode
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), _FakeTeamServer)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        return f"http://127.0.0.1:{self.srv.server_address[1]}"

    def main(self, *args):
        out = io.StringIO()
        with mock.patch.object(sys, "argv", ["teamup.py", *args]), contextlib.redirect_stdout(out):
            rc = teamup.main()
        lines = [x for x in out.getvalue().splitlines() if x.strip()]
        return rc, json.loads(lines[-1])

    def test_sent_marks_status(self):
        self.bundle()
        rc, res = self.main("--upload", "--json", "--url", self.serve())
        self.assertEqual((rc, res["sent"], res["pending"], res["results"][0]["kind"]), (0, 1, 0, "sent"))
        s = teamup.read_report_status(self.rep)
        self.assertEqual((s["ok"], s["sent"], s["via"], s["pending"]), (True, 1, "upload", 0))   # 배너는 다음 성공에 내려간다
        self.assertTrue(R.team_report_outcome(res, TAG)["ok"])

    def test_rejected_kind_keeps_status(self):
        self.bundle()
        rc, res = self.main("--upload", "--json", "--url", self.serve("reject"))
        self.assertEqual((rc, res["results"][0]["kind"], res["pending"]), (1, "rejected", 1))
        self.assertEqual(teamup.read_report_status(self.rep), {})               # 실패는 teamup 이 쓰지 않는다
        self.assertEqual(R.team_report_outcome(res, TAG)["reason"], "서버 거부")

    def test_blocked_kind(self):
        self.bundle({"evil.html": "<script></script>"})
        rc, res = self.main("--upload", "--json", "--url", self.serve())
        self.assertEqual((rc, res["results"][0]["kind"]), (1, "blocked"))
        self.assertEqual(R.team_report_outcome(res, TAG)["reason"], "보낼 수 없는 묶음")

    def test_no_url(self):
        self.bundle()
        rc, res = self.main("--upload", "--json", "--url", "http://bad host")
        self.assertEqual((rc, res.get("no_url"), res.get("pending")), (1, True, 1))
        self.assertEqual(R.team_report_outcome(res, TAG)["reason"], "주소 없음")

    def test_write_read_roundtrip(self):
        p = teamup.write_report_status(self.rep, {"ok": False, "reason": "서버 거부"})
        self.assertTrue(p and os.path.isfile(p))
        s = teamup.read_report_status(self.rep)
        self.assertEqual(s["reason"], "서버 거부")
        self.assertRegex(s["at"], r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d$")
        with open(p, "w", encoding="utf-8") as f:
            f.write("{깨짐")
        self.assertEqual(teamup.read_report_status(self.rep), {})


# ── [로컬PC 자료수집] — 보고하지 않음 · [분석 실행]과 같은 수집기(Copilot 만 뺌) ────────────────────
def _lm(src, counts=None):
    return "LMSTATUS " + json.dumps({"v": 1, "src": src, "rc": 0, "reason": "", "counts": counts or {}, "ranges": []})


class _Steps:
    """_RUN_STEP 자리 — 스크립트 이름만 적고 정상 종료로 답한다(프로세스 0개). 팀즈 앱 창은 '흔적 있음'."""

    def __init__(self):
        self.names, self.cmds = [], []

    def __call__(self, cmd, timeout, name=""):
        base = next((os.path.basename(str(x)) for x in cmd if str(x).lower().endswith((".ps1", ".py"))), "")
        self.names.append(base)
        self.cmds.append([str(x) for x in cmd])
        return 0, ["끝", _lm(base, {"teams_present": 1} if base == "Get-TeamsWindow.ps1" else None)], "ok"


class LocalCollect(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(prefix="lm28_p17_")
        self.tmp = self._td.name
        self._saved = (R._RUN_STEP, R._CLOSE_EDGE, dict(R.REPORT_DIR), list(R.RUN["stages"]), dict(R.RUN),
                       dict(R.EDGE), dict(R.STATE))
        R.REPORT_DIR["p"] = os.path.join(self.tmp, "report")
        R.RUN["stages"] = []
        R.EDGE["closed"] = False
        R.STATE["login_pending"] = False
        R._CLOSE_EDGE = lambda cfg, why: {"closed": True, "why": why}

    def tearDown(self):
        R._RUN_STEP, R._CLOSE_EDGE, rep, stages, run, edge, state = self._saved
        R.REPORT_DIR.clear()
        R.REPORT_DIR.update(rep)
        R.RUN.clear()
        R.RUN.update(run)
        R.RUN["stages"] = stages
        R.EDGE.clear()
        R.EDGE.update(edge)
        R.STATE.clear()
        R.STATE.update(state)
        self._td.cleanup()

    def chain(self, extra, c):
        steps = _Steps()
        R._RUN_STEP = steps
        data = os.path.join(self.tmp, "data" + str(len(extra)))
        os.makedirs(data, exist_ok=True)
        ps, col = ["powershell", "-File"], os.path.join(ROOT, "collect")
        with mock.patch.object(sys, "argv", ["run.py", "--from", D0, "--to", D1] + extra), _quiet():
            led = R.open_ledger(c, data)
            R.collect_outlook(c, D0, D1, data, ps, col, led)
            R.mail_fallbacks(c, D0, D1, data, ps, col, None, led, {"login_pending": False})
            R.collect_teams(c, D0, D1, data, ps, col, led, {"login_pending": False})
        return steps.names

    def test_same_collectors_except_copilot(self):
        c = {"teamsViaCopilot": True}
        full, local = self.chain([], c), self.chain(["--collect-only"], c)
        self.assertEqual(sorted(set(full) - set(local)), ["Get-MailViaCopilot.py", "Get-TeamsViaCopilot.py"])
        self.assertEqual(set(local) - set(full), set())
        for must in ("Get-OutlookData.ps1", "Get-OutlookIndex.ps1", "Get-OutlookWeb.py", "Get-TeamsWindow.ps1",
                     "Get-TeamsWeb.py"):
            self.assertIn(must, local)

    def test_collect_only_never_reports(self):
        root = os.path.join(self.tmp, "root")
        os.makedirs(os.path.join(root, "data"))
        steps = _Steps()
        R._RUN_STEP = steps
        spawned = []

        def no_spawn(*a, **k):
            spawned.append([str(x) for x in (a[0] if a else k.get("args") or [])])
            raise OSError("시험 — 프로세스를 띄우지 않는다")

        with mock.patch.object(R, "ROOT", root), \
                mock.patch.object(sys, "argv", ["run.py", "--from", D0, "--to", D1, "--collect-only"]), \
                mock.patch.object(R.subprocess, "run", no_spawn), mock.patch.object(R.subprocess, "Popen", no_spawn), \
                _quiet() as out:
            rc = R._main()
        self.assertEqual(rc, 0)
        self.assertFalse([c for c in steps.cmds + spawned if any("teamup" in os.path.basename(x) for x in c)])
        names = [x["name"] for x in R.RUN["stages"]]
        self.assertIn("완료(로컬PC 자료수집)", names)
        self.assertNotIn("팀 서버 자동 보고", names)
        self.assertFalse(os.path.exists(os.path.join(R.REPORT_DIR["p"], teamup.REPORT_STATUS)))
        self.assertIn("[로컬PC 자료수집] 이 PC 의 자료 수집을 마쳤습니다", out.getvalue())


# ── 화면 ──────────────────────────────────────────────────────────────────────────────────────
class PageWiring(unittest.TestCase):
    def test_buttons(self):
        p = app.PAGE
        idx = [p.index(s) for s in ('id="go"', 'id="collect2"', 'id="stop"', 'id="state"')]
        self.assertEqual(idx, sorted(idx))                                    # 분석 실행 바로 뒤 · 중지/상태 앞
        self.assertEqual(p.count('id="collect2"'), 1)
        self.assertIn('<button class="run local" id="collect2" title="이 PC 의 자료만 모읍니다(분석·보고 없음). '
                      '폴더째 분석할 PC 로 옮겨 [분석 실행]을 누르면 합쳐집니다">로컬PC 자료수집</button>', p)
        self.assertIn('<button class="run" id="go" title="로컬PC 자료수집 + AI 분석 + 팀 서버 보고까지 한 번에 합니다">'
                      '분석 실행</button>', p)
        self.assertIn("button.run.local{background:#0e8c7a}button.run.local:disabled{background:#c9cfd8}", p)
        self.assertIn('$("collect2").disabled=s.running', p)
        self.assertIn('$("go").disabled=true;$("collect2").disabled=true;', p)
        self.assertNotIn("추가 PC 수집</button>", p)
        src = _boot.read_text(os.path.join(ROOT, "ui", "app.py")) + _boot.read_text(os.path.join(ROOT, "run.py"))
        for old in ("수집만(추가 PC)", "추가 PC 수집 모드", "완료(수집만)", "[수집만] 이 PC", "[추가 PC 수집] →", "/[수집만]이"):
            self.assertNotIn(old, src, old)                                   # 옛 버튼 이름을 말하는 화면·기록 문구 없음
        for page in (p, app.TEAM_PAGE):
            self.assertIn("③ 팀 서버 보고(자동) / 공유폴더 저장", page)
            self.assertNotIn("③ 팀 업로드 / 공유폴더 저장", page)

    def test_alert_and_banner(self):
        p = app.PAGE
        for s in ('id="tr_banner"', 'id="tureport"', 'id="tuhead"', 'fetch("/api/teamreport")', "tuLoad();trLoad(true);",
                  '"팀 서버 자동 보고 실패 — "', "lm28_tr_alerted", "lm28_tr_dismiss", PEND_HINT, "팀 서버 보고 완료 (",
                  "window.__trIdle", "if(fromRun&&k&&k!==T.seen)", "trLoad(false);"):
            self.assertIn(s, p, s)

    def test_freeze_never_bakes_report_status(self):
        self.assertNotIn("/api/teamreport", _boot.read_text(os.path.join(ROOT, "freeze.py")))


class ApiTeamReport(unittest.TestCase):
    def test_get(self):
        with tempfile.TemporaryDirectory(prefix="lm28_p17_") as rep, mock.patch.object(app, "REPORT", rep), \
                mock.patch.object(app, "cfg", lambda: {"teamUpload": {"autoReport": False}}):
            teamup.write_report_status(rep, {"ok": False, "reason": "서버에 닿지 않음", "hint": PEND_HINT, "via": "auto"})
            srv = ThreadingHTTPServer(("127.0.0.1", 0), app.H)
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            try:
                c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=30)
                c.request("GET", "/api/teamreport")
                out = json.loads(c.getresponse().read().decode("utf-8"))
                c.close()
            finally:
                srv.shutdown()
                srv.server_close()
        self.assertEqual((out["ok"], out["auto"], out["report"]["reason"]), (True, False, "서버에 닿지 않음"))


if __name__ == "__main__":
    unittest.main()
