# -*- coding: utf-8 -*-
r"""tests\test_p21_close_stop.py — 창을 닫으면 작업도 멈춘다 · 강제종료 bat (LM28 2026-10-14).

  (1) 판정(ui_close_decision) 표 — 첫 신호 전 · 살아 있음 · 작별 뒤 새로고침 · 작별 뒤 조용함 · 최소화(1분에 1번) · 3분 조용 ·
      조용한 숨긴 탭 · 잠든 탭(freeze) · 설정 끔 · 작별 뒤 늦게 온 신호
  (2) 서버 배선 — /api/alive·/api/bye 가 상태를 바꾼다(sendBeacon 의 text/plain 도) · 감시 스레드는 임포트로 뜨지 않는다 ·
      감시 루프가 'exit' 에서 정리 함수를 부른다 · 정리(ui_close_exit)가 [중지]와 같은 길 + last_run.json '중단(창 닫힘)'
  (3) 콘솔 창 닫기 — proc.console_event·kill_all·run_within, app.console_close_cleanup·run.console_close(빠른 Edge 닫기 tidy=False ·
      예외 삼킴 · 로그인 대기면 Edge 를 둔다)
  (4) 파일 — 새 bat(CP949·CRLF·BOM 없음) · UI·팀취합 bat 은 오류일 때만 멈춘다 · Stop-LM28.ps1(UTF-8 BOM·CRLF·묻지 않음) ·
      화면 스크립트 배선 · 설정 uiAutoExit · 자가점검 NEED
  (5) --ps: Select-LmTargets(가짜 프로세스 목록) — 이 폴더 / 이웃 폴더 / LM24 / 같은 파일 이름 · 팀 서버 둠·포함 · 전용/사람 Edge ·
      자손 · PID 재사용 · 자기 줄기
새 프로세스를 띄우지 않는다(서버는 같은 프로세스의 스레드). 임시 폴더만 쓴다. 실제 Job·Edge·콘솔 처리기는 건드리지 않는다(모두 바꿔 끼운다).
"""
import ast
import http.client
import json
import os
import re
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from unittest import mock

import _boot

import app  # noqa: E402  — ui\app.py(임포트 부작용 없음 — 감시 스레드·콘솔 처리기는 main 에서만)
import proc  # noqa: E402
import run as R  # noqa: E402

ROOT = _boot.ROOT
D = app.ui_close_decision


def _bytes(rel):
    with open(os.path.join(ROOT, rel), "rb") as f:
        return f.read()


class _CloseState(unittest.TestCase):
    """UI_CLOSE·JOB 을 시험마다 비우고 되돌린다."""

    def setUp(self):
        self._saved = json.loads(json.dumps(app.UI_CLOSE))
        self._job = {k: (list(v) if isinstance(v, list) else v) for k, v in app.JOB.items()}
        app.UI_CLOSE.update(tabs={}, vis={}, gone={}, bye=0.0, armed=False)

    def tearDown(self):
        app.UI_CLOSE.clear()
        app.UI_CLOSE.update(self._saved)
        app.JOB.clear()
        app.JOB.update(self._job)


class Decision(unittest.TestCase):
    """(1) 판정 표"""

    def test_never_armed_keeps(self):
        self.assertEqual(D(10_000, {}, 0.0, False), ("keep", "not_armed"))
        self.assertEqual(D(10_000, {}, 100.0, False), ("keep", "not_armed"))      # 첫 신호 전의 작별도 무시

    def test_alive_keeps(self):
        self.assertEqual(D(1000, {"a": 995}, 0.0, True), ("keep", "alive"))

    def test_bye_then_reload_within_grace(self):
        # 작별 직후(탭 표는 비었다) — 20초까지는 기다린다
        self.assertEqual(D(1010, {}, 1000.0, True), ("keep", "grace"))
        # 새로고침한 새 탭이 알렸다 — 계속
        self.assertEqual(D(1030, {"new": 1002}, 1000.0, True), ("keep", "alive"))

    def test_bye_then_silence_exits(self):
        self.assertEqual(D(1021, {}, 1000.0, True), ("exit", "bye"))

    def test_one_of_two_tabs_closed_keeps(self):
        self.assertEqual(D(1100, {"other": 1095}, 1090.0, True), ("keep", "alive"))

    def test_minimized_tab_pinging_once_a_minute_keeps(self):
        t, last = 0.0, 0.0
        for _ in range(30):                     # 30분 동안 1분에 1번(숨긴 탭 타이머 상한) — 매 순간 판정
            for sec in range(0, 60, 5):
                self.assertEqual(D(t + sec, {"m": (last, "hidden")}, 0.0, True)[0], "keep", t + sec)
            t += 60
            last = t
        self.assertEqual(D(last + 170, {"m": (last, "hidden")}, 0.0, True), ("keep", "alive"))

    def test_silence_timeout_exits(self):
        self.assertEqual(D(1000 + 181, {"v": (1000, "visible")}, 0.0, True), ("exit", "silence"))
        self.assertEqual(D(1000 + 179, {"v": (1000, "visible")}, 0.0, True), ("keep", "alive"))
        # 작별이 마지막 신호보다 먼저였으면 사유는 '조용함'
        self.assertEqual(D(1000 + 200, {"v": 1000}, 900.0, True), ("exit", "silence"))

    def test_silent_hidden_tab_exits(self):
        # 숨긴 탭도 1분에 1번은 알린다 — 3분 넘게 조용하면(브라우저째 꺼짐) 숨김이었어도 닫힌 것이다
        self.assertEqual(D(1000 + 181, {"h": (1000, "hidden")}, 0.0, True), ("exit", "silence"))

    def test_frozen_tab_kept_for_hours_then_exit(self):
        st = {"f": (1000, "frozen")}
        self.assertEqual(D(1000 + 3600, st, 0.0, True), ("keep", "asleep"))
        self.assertEqual(D(1000 + app.CLOSE_ASLEEP + 1, st, 0.0, True), ("exit", "silence"))

    def test_switch_off_keeps(self):
        self.assertEqual(D(99_999, {}, 1.0, True, {"on": False}), ("keep", "off"))
        self.assertFalse(app._close_cfg({"uiAutoExit": False})["on"])
        self.assertFalse(app._close_cfg({"uiAutoExit": "false"})["on"])
        self.assertTrue(app._close_cfg({})["on"])
        self.assertEqual(app.CLOSE_GRACE, 20.0)
        self.assertEqual(app.CLOSE_SILENCE, 180.0)


class _Srv:
    def __init__(self):
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), app.H)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def post(self, path, raw, ctype="application/json"):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        try:
            c.request("POST", path, body=raw, headers={"Content-Type": ctype})
            r = c.getresponse()
            return r.status, json.loads(r.read().decode("utf-8") or "{}")
        finally:
            c.close()

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


class ServerWiring(_CloseState):
    """(2) 서버 배선"""

    def test_alive_and_bye_update_state(self):
        s = _Srv()
        try:
            st, b = s.post("/api/alive", json.dumps({"id": "t1", "vis": "hidden"}).encode())
            self.assertEqual((st, b), (200, {"ok": True}))
            self.assertTrue(app.UI_CLOSE["armed"])
            self.assertIn("t1", app.UI_CLOSE["tabs"])
            self.assertEqual(app.UI_CLOSE["vis"]["t1"], "hidden")
            s.post("/api/alive", json.dumps({"id": "t2", "vis": "이상한값"}).encode())
            self.assertEqual(app.UI_CLOSE["vis"]["t2"], "visible")
            # sendBeacon 은 text/plain 으로 보낸다
            st, b = s.post("/api/bye", json.dumps({"id": "t1"}).encode(), "text/plain;charset=UTF-8")
            self.assertEqual(st, 200)
            self.assertNotIn("t1", app.UI_CLOSE["tabs"])
            self.assertIn("t2", app.UI_CLOSE["tabs"])
            self.assertGreater(app.UI_CLOSE["bye"], 0)
            st, b = s.post("/api/alive", b"not json")
            self.assertEqual((st, b), (200, {"ok": False}))
        finally:
            s.close()

    def test_late_alive_after_bye_is_ignored(self):
        # 탭을 닫을 때 visibilitychange('숨김') 신호가 작별보다 늦게 와도 닫힌 탭이 되살아나지 않는다
        self.assertTrue(app.ui_tab_alive("t1", "visible", now=1000.0))
        app.ui_tab_bye("t1", now=1001.0)
        self.assertFalse(app.ui_tab_alive("t1", "hidden", now=1001.5))
        self.assertNotIn("t1", app.UI_CLOSE["tabs"])
        self.assertEqual(D(1022.0, *app._close_snapshot()), ("exit", "bye"))
        for i in range(300):
            app.ui_tab_bye(f"g{i}", now=2000.0 + i)
        self.assertEqual(len(app.UI_CLOSE["gone"]), 256)

    def test_tab_table_is_capped(self):
        for i in range(80):
            app.ui_tab_alive(f"t{i}", now=1000.0 + i)
        self.assertEqual(len(app.UI_CLOSE["tabs"]), 64)
        self.assertNotIn("t0", app.UI_CLOSE["tabs"])
        self.assertIn("t79", app.UI_CLOSE["tabs"])

    def test_watchdog_not_started_on_import(self):
        self.assertFalse([t for t in threading.enumerate() if t.name == "lm-close-watch"])
        self.assertIsNone(proc._CTRL["cb"], "콘솔 처리기가 임포트로 걸렸다")
        src = _boot.read_text(os.path.join(ROOT, "ui", "app.py"))
        tree = ast.parse(src)
        main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
        body = ast.get_source_segment(src, main)
        self.assertIn('name="lm-close-watch"', body)
        self.assertIn("proc.on_console_close(console_close_cleanup)", body)
        top = [ast.get_source_segment(src, n) for n in tree.body if not isinstance(n, (ast.FunctionDef, ast.ClassDef))]
        self.assertFalse([t for t in top if "close_watch" in (t or "") or "on_console_close" in (t or "")])

    def test_watch_loop_exits_and_calls_cleanup(self):
        app.ui_tab_alive("old", now=time.time() - 1000)
        app.ui_tab_bye("old", now=time.time() - 900)
        srv = mock.Mock()
        with mock.patch.object(app, "ui_close_exit") as ex:
            why = app.close_watch(srv, {"on": True}, every=0.01)
        self.assertEqual(why, "bye")
        ex.assert_called_once_with(srv, "bye")

    def test_watch_loop_keeps_when_not_armed(self):
        stop = threading.Event()
        threading.Timer(0.15, stop.set).start()
        with mock.patch.object(app, "ui_close_exit") as ex:
            self.assertIsNone(app.close_watch(mock.Mock(), {"on": True}, every=0.01, stop=stop))
        ex.assert_not_called()

    def test_resume_shift(self):
        app.ui_tab_alive("a", now=1000.0)
        app.ui_tab_bye("b", now=1001.0)
        app._close_shift(3600.0)
        self.assertEqual(app.UI_CLOSE["tabs"]["a"], 4600.0)
        self.assertEqual(app.UI_CLOSE["bye"], 4601.0)

    def test_exit_stops_job_like_stop_button_and_marks_last_run(self):
        with tempfile.TemporaryDirectory(prefix="lm28_p21_") as td:
            lr = os.path.join(td, "last_run.json")
            with open(lr, "w", encoding="utf-8") as f:
                json.dump({"started": "2026-10-14 09:00", "finished": None,
                           "stages": [{"name": "시작", "ok": True}, {"name": "AI 판정", "ok": True}]}, f)
            app.JOB.update(running=True, pid=4321, started=time.time() - 30)
            said, done = [], threading.Event()
            srv = mock.Mock()
            srv.shutdown.side_effect = lambda: done.set()
            with mock.patch.object(app, "REPORT", td), mock.patch.object(app, "kill_job") as kj, \
                    mock.patch.object(app.proc, "kill_all") as ka, mock.patch.object(app, "close_edge") as ce:
                app.ui_close_exit(srv, "bye", out=said.append)
            kj.assert_called_once_with()
            ka.assert_called_once_with()
            ce.assert_called_once_with("ui_close")          # 보통 길(채팅 정리 포함) — tidy 를 끄지 않는다
            self.assertTrue(done.wait(5), "서버를 끝내지 않았다")
            self.assertEqual(len(said), 1)
            self.assertTrue(said[0].startswith(app.CLOSE_LINE_BUSY), said)
            self.assertIn("창 닫힘", said[0])
            with open(lr, encoding="utf-8") as f:
                st = json.load(f)["stages"]
            self.assertEqual(st[-1]["name"], app.STOP_STAGE)
            self.assertFalse(st[-1]["ok"])
            self.assertIn("대시보드 창이 닫혀", st[-1]["note"])
            self.assertTrue(any("대시보드 창이 닫혀" in x for x in app.JOB["log"]))

    def test_mark_last_run_only_for_this_unfinished_run(self):
        with tempfile.TemporaryDirectory(prefix="lm28_p21_") as td:
            lr = os.path.join(td, "last_run.json")
            base = {"started": "2026-10-14 09:00", "finished": "2026-10-14 09:30", "stages": [{"name": "완료", "ok": True}]}
            with open(lr, "w", encoding="utf-8") as f:
                json.dump(base, f)
            self.assertFalse(app._mark_last_run_stopped(time.time() - 5, "x", td))      # 끝난 실행
            base["finished"] = None
            with open(lr, "w", encoding="utf-8") as f:
                json.dump(base, f)
            self.assertFalse(app._mark_last_run_stopped(time.time() + 600, "x", td))    # 이 작업보다 오래된 기록
            self.assertTrue(app._mark_last_run_stopped(time.time() - 5, "x", td))
            self.assertTrue(app._mark_last_run_stopped(time.time() - 5, "y", td))       # 두 번 붙이지 않는다
            with open(lr, encoding="utf-8") as f:
                st = json.load(f)["stages"]
            self.assertEqual([x["name"] for x in st].count(app.STOP_STAGE), 1)
            self.assertFalse(os.path.exists(lr + ".tmp"))
            with open(lr, "w", encoding="utf-8") as f:
                f.write("{깨진")
            self.assertFalse(app._mark_last_run_stopped(time.time() - 5, "x", td))


class ConsoleClose(_CloseState):
    """(3) 콘솔 창 닫기"""

    def test_console_event_swallows_and_passes_ctrl_c(self):
        calls = []

        def boom(ev):
            calls.append(ev)
            raise RuntimeError("x")

        with mock.patch.dict(proc._CTRL, {"fn": boom}):
            self.assertEqual(proc.console_event(0), 0)          # Ctrl+C — 파이썬 KeyboardInterrupt 로 넘긴다
            self.assertEqual(proc.console_event(1), 0)          # Ctrl+Break
            self.assertEqual(proc.console_event(2), 1)          # 창 닫기 — 예외를 내지 않는다
            self.assertEqual(proc.console_event(6), 1)          # 윈도 종료
        self.assertEqual(calls, [2, 6])
        with mock.patch.object(proc.os, "name", "posix"):
            self.assertFalse(proc.on_console_close(lambda ev: None))

    def test_kill_all_and_run_within(self):
        with mock.patch.dict(proc._JOBS, {11: 901, 12: 901, 13: 902}, clear=True), \
                mock.patch.object(proc, "release") as rel:
            self.assertEqual(proc.kill_all(), 2)
        rel.assert_has_calls([mock.call(901, None, kill=True), mock.call(902, None, kill=True)])
        t0 = time.monotonic()
        self.assertFalse(proc.run_within(lambda: time.sleep(2), 0.05))
        self.assertLess(time.monotonic() - t0, 1.0)
        self.assertTrue(proc.run_within(lambda: 1 / 0, 1.0))

    def test_app_console_cleanup_fast_edge_and_errors_swallowed(self):
        app.JOB.update(running=True, pid=77, started=time.time())
        slow = mock.Mock(side_effect=lambda *a, **k: time.sleep(1.5))
        with mock.patch.object(app, "kill_job", side_effect=RuntimeError("x")) as kj, \
                mock.patch.object(app.proc, "kill_all") as ka, mock.patch.object(app, "close_edge", slow), \
                mock.patch.object(app, "_mark_last_run_stopped") as mk:
            t0 = time.monotonic()
            app.console_close_cleanup(2, budget=0.1)
            self.assertLess(time.monotonic() - t0, 1.0, "Edge 닫기를 상한보다 오래 기다렸다")
            time.sleep(0.05)
        kj.assert_called_once_with()
        ka.assert_called_once_with()
        slow.assert_called_once_with("console_close", tidy=False)
        mk.assert_called_once()
        with mock.patch.object(app, "kill_job", side_effect=BaseException("y")), mock.patch.object(app, "close_edge"):
            app.console_close_cleanup(2, budget=0.01)            # 무엇이 터져도 처리기 밖으로 내지 않는다

    def test_run_console_close(self):
        with tempfile.TemporaryDirectory(prefix="lm28_p21_") as td:
            mod = mock.Mock()
            with mock.patch.dict(R.RUN, {"stages": [{"name": "시작", "ok": True}], "started": "2026-10-14 09:00",
                                         "finished": None}), \
                    mock.patch.dict(R.REPORT_DIR, {"p": td}), mock.patch.dict(R.STATE, {"login_pending": False}), \
                    mock.patch.object(R.proc, "kill_all") as ka, mock.patch.object(R, "_copilot_mod", return_value=mod):
                R.console_close(2, budget=1.0)
                ka.assert_called_once_with()
                mod.close_own_edge.assert_called_once_with(None, "console_close", tidy=False)
                with open(os.path.join(td, "last_run.json"), encoding="utf-8") as f:
                    st = json.load(f)["stages"]
                self.assertEqual(st[-1]["name"], R.STOP_STAGE)
                self.assertEqual(R.STOP_STAGE, app.STOP_STAGE)
                # 로그인 대기 중이면 Edge 를 두고, 정리 실패는 삼킨다
                mod.reset_mock()
                R.STATE["login_pending"] = True
                ka.side_effect = RuntimeError("x")
                R.console_close(2, budget=0.1)
                mod.close_own_edge.assert_not_called()
        src = _boot.read_text(os.path.join(ROOT, "run.py"))
        self.assertIn("proc.on_console_close(console_close)", src)


class Files(unittest.TestCase):
    """(4) 파일·배선"""

    def _bat(self, name):
        b = _bytes(name)
        self.assertFalse(b.startswith(b"\xef\xbb\xbf"), name)
        self.assertEqual(b.count(b"\n"), b.count(b"\r\n"), name)
        return b.decode("cp949")

    def test_force_stop_bat(self):
        s = self._bat("LoadMonitor28-강제종료.bat")
        for frag in (">nul chcp 949", 'cd /d "%~dp0"', "powershell -NoProfile -ExecutionPolicy Bypass -File",
                     "tools\\Stop-LM28.ps1", "%*", "pause"):
            self.assertIn(frag, s)
        self.assertNotIn("set /p", s.lower())                # 묻지 않는다

    def test_ui_bats_pause_only_on_error(self):
        for name, run_line in (("LoadMonitor28-UI.bat", "ui\\app.py\r\n"), ("LoadMonitor28-팀취합.bat", "ui\\app.py --team")):
            s = self._bat(name)
            seg = s[s.index(run_line):s.index(":MISSING")]
            m = re.search(r"if errorlevel 1 \((.*?)\r\n\)", seg, re.S)
            self.assertIsNotNone(m, name)
            self.assertEqual(seg.count("pause"), 1, name)
            self.assertIn("pause", m.group(1), name)
            self.assertIn("ui_error.log", m.group(1), name)
            self.assertTrue(seg.rstrip().endswith("exit /b 0"), name)

    def test_stop_ps1(self):
        b = _bytes(os.path.join("tools", "Stop-LM28.ps1"))
        self.assertTrue(b.startswith(b"\xef\xbb\xbf"))
        self.assertEqual(b.count(b"\n"), b.count(b"\r\n"))
        s = b.decode("utf-8-sig")
        for frag in ("function Select-LmTargets", "[switch]$IncludeTeamServer", "[switch]$Status", "Get-CimInstance",
                     "Get-WmiObject", "$MyInvocation.InvocationName -ne '.'", "Stop-Process -Id", "CreationDate",
                     "LM28 작업을 모두 끝냈습니다", "exit "):
            self.assertIn(frag, s)
        for bad in ("Read-Host", "Out-File", "Set-Content", "$env:TEMP", "Register-ScheduledTask", "RunAs"):
            self.assertNotIn(bad, s)

    def test_page_wiring(self):
        for frag in ('"/api/alive"', '"/api/bye"', "sendBeacon", '"pagehide"', '"beforeunload"', "leaveGuard(!!s.running)",
                     "document.visibilityState", "lm-frozen-data", '"freeze"', "10000", "e.persisted){LM_TAB="):
            self.assertIn(frag, app.PAGE, frag)
        for frag in ('"/api/alive"', '"/api/bye"', "sendBeacon", '"pagehide"', "lm-frozen-data", "e.persisted){LM_TAB="):
            self.assertIn(frag, app.TEAM_PAGE, frag)
        # 관문 3 — PAGE/TEAM_PAGE 소스에 이스케이프 안 된 \n 이 없다(JS 문자열 안의 개행 → 버튼 전멸)
        src = _boot.read_text(os.path.join(ROOT, "ui", "app.py"))
        for name in ("PAGE", "TEAM_PAGE"):
            i0 = src.index("\n" + name + ' = """')
            i1 = src.index('"""', i0 + len(name) + 8)
            self.assertEqual(len(re.findall(r"(?<!\\)\\n", src[i0:i1])), 0, name)

    def test_config_switch(self):
        for name in ("config.default.json", "config.json"):
            with open(os.path.join(ROOT, "config", name), encoding="utf-8-sig") as f:
                c = json.load(f)
            self.assertIs(c.get("uiAutoExit"), True, name)
            self.assertIn("false", c.get("_uiAutoExit_설명", ""), name)
            self.assertIn("강제종료", c.get("_uiAutoExit_설명", ""), name)

    def test_need_lists_new_files(self):
        src = _boot.read_text(os.path.join(ROOT, "자가점검.py"))
        need = next(ast.literal_eval(n.value) for n in ast.parse(src).body
                    if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "NEED")
        for rel in ("LoadMonitor28-강제종료.bat", "tools/Stop-LM28.ps1"):
            self.assertIn(rel, need)
            self.assertTrue(os.path.isfile(os.path.join(ROOT, rel)), rel)


class PsSelect(unittest.TestCase):
    """(5) --ps: Select-LmTargets"""

    def test_select_targets(self):
        r = _boot.ps_result("StopLM28")
        if r is None:
            self.skipTest("PowerShell 결과 없음 — tests\\run_tests.py --ps-only=StopLM28 로 실행")
        self.assertNotIn("error", r, r)
        self.assertEqual(r["targets"], "100,101,102,103,104,105,106,129,130,131,171")
        self.assertEqual(r["kept"], "108,150,181")
        self.assertEqual(r["targets_ts"], "100,101,102,103,104,105,106,108,129,130,131,171,180,181")
        self.assertEqual(r["kept_ts"], "150")
        self.assertEqual(r["kinds"], "100:console,101:python,102:python,103:powershell,104:python,105:edge,106:edge,"
                                     "129:console,130:python,131:powershell,171:powershell")
        for frag in ("끝낼 것 11개", "콘솔 창(bat) 2개", "전용 Edge(Copilot·웹 읽기) 2개", "[둠] 팀 서버 pid 108",
                     "PC 이동 준비 창 pid 150", "-IncludeTeamServer"):
            self.assertIn(frag, r["lines"])
        self.assertIn("끝낼 LM28 작업이 없습니다", r["none"])
        self.assertEqual(r["age"], "2시간 5분")
        self.assertGreater(r["real_n"], 5)
        self.assertEqual(r["real_self"], 1)
        self.assertEqual(r["real_sel"], 0)


class StartFail(unittest.TestCase):
    """수집기 프로그램이 켜지는 순간 실패(0xc0000142) — 오류 창 없이 잠깐 쉬었다 다시 띄우고, 그래도 같으면 사유를 남긴다."""

    def setUp(self):
        self._saved = (proc._run_step_once, proc._sleep)
        self.waits = []
        proc._sleep = self.waits.append

    def tearDown(self):
        proc._run_step_once, proc._sleep = self._saved

    def _script(self, results):
        calls = []

        def fake(cmd, timeout, name="", clock=None, **kw):
            calls.append(cmd)
            rc, tail, how = results[min(len(calls) - 1, len(results) - 1)]
            return rc, list(tail), how
        proc._run_step_once = fake
        return calls

    def test_retries_then_succeeds(self):
        calls = self._script([(0xC0000142, [], "ok"), (0, ["LMSTATUS {}"], "ok")])
        said = []
        rc, tail, how = proc.run_step(["powershell"], 60, "PC 가동 이력", on_line=said.append)
        self.assertEqual((rc, how, len(calls)), (0, "ok", 2))
        self.assertEqual(self.waits, [proc.START_WAIT[0]])
        self.assertTrue(any("0xc0000142" in x and "다시 띄웁니다(1/2)" in x for x in said))

    def test_gives_up_with_reason(self):
        signed = 0xC0000142 - (1 << 32)
        calls = self._script([(signed, [], "ok")])
        rc, tail, how = proc.run_step(["powershell"], 60, "색인", on_line=lambda s: None)
        self.assertEqual(len(calls), 1 + proc.START_RETRY)
        self.assertEqual(rc, signed)
        self.assertIn("0xc0000142", tail[-1])
        import collect_status as CS
        st = CS.parse(tail, rc, src="idx", how=how)
        self.assertEqual((st["rc"], st["reason"], st["ok"]), (3, "R-STARTFAIL", False))
        self.assertEqual(CS.parse([], 0xC0000142)["reason"], "R-STARTFAIL")

    def test_other_failures_are_not_retried(self):
        calls = self._script([(1, ["오류"], "ok")])
        proc.run_step(["powershell"], 60, "x", on_line=lambda s: None)
        self.assertEqual(len(calls), 1)
        calls2 = self._script([(0xC0000142, [], "timeout")])   # 시간 초과로 끊긴 것은 '켜지다 실패' 가 아니다
        proc.run_step(["powershell"], 60, "x", on_line=lambda s: None)
        self.assertEqual(len(calls2), 1)
        self.assertEqual(self.waits, [])

    def test_quiet_errors_idempotent(self):
        a = proc.quiet_errors()
        self.assertEqual(proc.quiet_errors(), a)
        if os.name == "nt":
            self.assertTrue(a)

    def test_entry_points_set_error_mode(self):
        for rel in ("run.py", os.path.join("ui", "app.py")):
            src = _boot.read_text(os.path.join(ROOT, rel))
            self.assertIn("proc.quiet_errors()", src, rel)


if __name__ == "__main__":
    unittest.main()
