# -*- coding: utf-8 -*-
r"""tests\test_p24_stop_startfail.py — 강제종료가 'PowerShell 시작 실패(0xc0000142)' 에도 끝까지 한다 (LM28 2026-10-15).

  (1) tools\ps_launch — 켜지다 실패(부호 있는/없는 0xC0000142)면 3초·8초 쉬고 두 번 다시 띄운다 · 다른 종료 코드는 그대로 ·
      켜질 시간(proc.START_FAIL_SEC)이 지난 뒤의 실패는 다시 띄우지 않는다 · 띄우기 OSError 는 바로 '켜지지 못함' · CLI · 종료 코드
  (2) tools\stop_lm28.main — Stop-LM28.ps1 에 인자 + -KeepPid <자기 pid> · 파이썬 대안은 다시 띄우기를 모두 쓴 뒤에만 · 스위치 읽기
  (3) select_targets — Stop-LM28.ps1 시험(tests\ps\Test-StopLM28.ps1)과 같은 가짜 프로세스 목록 · 같은 답(이 폴더 python·powershell·
      bat 창·전용 Edge·자손 / 다른 폴더·사람 Edge·LM24·팀 서버(플래그 없으면)·이동 준비 창·자기와 부모 줄기는 빼기 · PID 재사용)
  (4) 파이썬 대안 실행(run_fallback) — -Status 는 목록만 · 끝내는 순서 · 남은 것과 사유 · 오류 · 화면 문구
  (5) 실제 프로세스 목록 읽기(ctypes — 읽기만, 아무것도 끝내지 않는다) · bat(CP949·CRLF) · 자가점검 NEED · 문서 한 줄
  (6) --ps: Select-LmTargets 의 런처 줄기·-KeepPid 와 (3) 의 파이썬 답이 같은지
실제 powershell·강제종료는 띄우지 않는다 — runner·sleep·clock·osapi 는 가짜다. 새 프로세스를 띄우지 않는다.
"""
import ast
import os
import re
import sys
import time
import unittest
from datetime import datetime

import _boot

import proc  # noqa: E402
import ps_launch  # noqa: E402
import stop_lm28 as S  # noqa: E402

ROOT = _boot.ROOT
SF = 0xC0000142
SF_SIGNED = 0xC0000142 - (1 << 32)


def _bytes(rel):
    with open(os.path.join(ROOT, rel), "rb") as f:
        return f.read()


# ── (1) 실행기 ───────────────────────────────────────────────────────────────────────────
class _Fake:
    """runner·sleep·clock·say 가짜 — results 를 차례로 돌려준다(마지막 것을 되풀이). step = 한 번 실행에 흐르는 초."""

    def __init__(self, results, step=0.0):
        self.results, self.step = list(results), step
        self.calls, self.waits, self.said, self.t = [], [], [], 1000.0

    def runner(self, cmd, cwd):
        self.calls.append((list(cmd), cwd))
        r = self.results[min(len(self.calls) - 1, len(self.results) - 1)]
        self.t += self.step
        if isinstance(r, BaseException):
            raise r
        return r

    def clock(self):
        return self.t

    def kw(self):
        return {"runner": self.runner, "sleep": self.waits.append, "clock": self.clock, "say": self.said.append}


class Launcher(unittest.TestCase):

    def test_retries_signed_and_unsigned_then_ok(self):
        f = _Fake([SF, SF_SIGNED, 0])
        rc, failed = ps_launch.launch("x.ps1", ["-A"], **f.kw())
        self.assertEqual((rc, failed), (0, False))
        self.assertEqual(len(f.calls), 3)
        self.assertEqual(f.waits, [3.0, 8.0])
        self.assertEqual(f.waits, list(proc.START_WAIT))
        self.assertEqual(f.said, ["  PowerShell 이 켜지지 못했습니다(Windows 오류 0xc0000142) — 3초 뒤 다시 띄웁니다(1/2)",
                                  "  PowerShell 이 켜지지 못했습니다(Windows 오류 0xc0000142) — 8초 뒤 다시 띄웁니다(2/2)"])
        self.assertEqual(ps_launch.run_ps("x.ps1", **_Fake([0]).kw()), 0)

    def test_other_rc_passes_through(self):
        for rc0 in (1, 0xC0000005, -196608, 2):
            f = _Fake([rc0])
            self.assertEqual(ps_launch.launch("x.ps1", **f.kw()), (rc0, False), rc0)
            self.assertEqual((len(f.calls), f.waits, f.said), (1, [], []), rc0)

    def test_failure_after_start_window_not_retried(self):
        f = _Fake([SF], step=proc.START_FAIL_SEC + 1)          # 일하다 같은 코드로 끝났다 — '켜지다 실패' 가 아니다
        self.assertEqual(ps_launch.launch("x.ps1", **f.kw()), (SF, False))
        self.assertEqual((len(f.calls), f.waits), (1, []))

    def test_gives_up_after_retries(self):
        f = _Fake([SF_SIGNED])
        self.assertEqual(ps_launch.launch("x.ps1", **f.kw()), (SF_SIGNED, True))
        self.assertEqual(len(f.calls), 1 + proc.START_RETRY)
        self.assertEqual(f.waits, [3.0, 8.0])

    def test_oserror_is_start_failure_without_retry(self):
        f = _Fake([FileNotFoundError(2, "없음")])
        self.assertEqual(ps_launch.launch("x.ps1", **f.kw()), (ps_launch.OSERR_RC, True))
        self.assertEqual((len(f.calls), f.waits), (1, []))
        self.assertIn("PowerShell 을 띄우지 못했습니다", f.said[0])

    def test_command_shape_and_cwd(self):
        f = _Fake([0])
        ps_launch.launch(r"collect\Diagnose-Collectors.ps1", ["-OutFile", "a b.txt"], cwd="C:\\x", **f.kw())
        cmd, cwd = f.calls[0]
        self.assertEqual(cmd, ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                               r"collect\Diagnose-Collectors.ps1", "-OutFile", "a b.txt"])
        self.assertEqual(cwd, "C:\\x")

    def test_cli(self):
        self.assertEqual(ps_launch.main([]), 2)
        f = _Fake([SF])
        rc = ps_launch.main(["x.ps1", "-A"], **f.kw())
        self.assertEqual(rc, SF_SIGNED)                         # sys.exit 가 넘치지 않는 값 — 윈도 종료 코드는 같다
        self.assertEqual(f.said[-1], ps_launch.GIVEUP_LINE)
        self.assertEqual(f.calls[0][0][-2:], ["x.ps1", "-A"])
        f = _Fake([3])
        self.assertEqual(ps_launch.main(["x.ps1"], **f.kw()), 3)
        self.assertNotIn(ps_launch.GIVEUP_LINE, f.said)

    def test_exit_code(self):
        for rc, want in ((0, 0), (1, 1), (SF, SF_SIGNED), (SF_SIGNED, SF_SIGNED), (-2, -2), (0xFFFFFFFF, -1)):
            self.assertEqual(ps_launch.exit_code(rc), want, rc)

    def test_reuses_proc_constants(self):
        src = _boot.read_text(os.path.join(ROOT, "tools", "ps_launch.py"))
        code = re.sub(r'(?s)""".*?"""|"[^"\n]*"', '""', src)          # 문자열 밖만
        for name in ("proc.START_FAIL_RC", "proc.START_FAIL_SEC", "proc.START_RETRY", "proc.START_WAIT", "proc.quiet_errors()"):
            self.assertIn(name, code)
        self.assertNotRegex(code, r"(?i)0xc0000142|3221225794|\(3\.0, 8\.0\)")


# ── (2) 강제종료 입구 ───────────────────────────────────────────────────────────────────────
class StopMain(unittest.TestCase):

    def _main(self, argv, results):
        f, fb = _Fake(results), []

        def fallback(root, status, team, say=None):
            fb.append((root, status, team))
            say("FALLBACK-RAN")
            return 0
        rc = S.main(argv, fallback=fallback, **f.kw())
        return rc, f, fb

    def test_fallback_only_after_all_retries(self):
        rc, f, fb = self._main(["-Status"], [SF])
        self.assertEqual(rc, 0)
        self.assertEqual(len(f.calls), 1 + proc.START_RETRY)
        self.assertEqual(f.waits, [3.0, 8.0])
        self.assertEqual(fb, [(S.ROOT, True, False)])
        self.assertEqual(f.said[-2:], [S.FALLBACK_LINE, "FALLBACK-RAN"])
        self.assertEqual(S.FALLBACK_LINE, "  PowerShell 을 끝내 띄우지 못해 파이썬으로 같은 규칙대로 끝냅니다")
        self.assertEqual(sum("다시 띄웁니다" in x for x in f.said), 2)
        cmd = f.calls[0][0]
        self.assertEqual(cmd[:6], ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", S.STOP_PS1])
        self.assertEqual(cmd[6:], ["-Status", "-KeepPid", str(os.getpid())])
        self.assertEqual(os.path.normcase(S.STOP_PS1), os.path.normcase(os.path.join(ROOT, "tools", "Stop-LM28.ps1")))

    def test_no_fallback_when_powershell_runs(self):
        rc, f, fb = self._main([], [SF, SF_SIGNED, 1])             # 세 번째에 켜져 '남은 것 있음'(1)으로 끝남
        self.assertEqual((rc, fb, len(f.calls)), (1, [], 3))
        self.assertNotIn(S.FALLBACK_LINE, f.said)
        rc, f, fb = self._main(["-IncludeTeamServer"], [0])
        self.assertEqual((rc, fb, f.waits, f.said), (0, [], [], []))
        self.assertEqual(f.calls[0][0][6:], ["-IncludeTeamServer", "-KeepPid", str(os.getpid())])
        f2, fb2 = _Fake([SF], step=proc.START_FAIL_SEC + 1), []     # 늦은 실패(일하다 끝남)는 대안을 부르지 않는다
        rc2 = S.main([], fallback=lambda *a, **k: fb2.append("x"), **f2.kw())
        self.assertEqual((rc2, len(f2.calls), fb2), (SF_SIGNED, 1, []))

    def test_oserror_goes_to_fallback(self):
        rc, f, fb = self._main(["-inc", "-s"], [OSError(5, "막힘")])
        self.assertEqual((rc, fb, len(f.calls)), (0, [(S.ROOT, True, True)], 1))

    def test_parse_opts(self):
        P = S.parse_opts
        self.assertEqual(P([]), (False, False))
        self.assertEqual(P(["-Status"]), (True, False))
        self.assertEqual(P(["-STATUS", "-IncludeTeamServer"]), (True, True))
        self.assertEqual(P(["-sta", "-incl"]), (True, True))
        self.assertEqual(P(["-Status:$false", "-IncludeTeamServer:$true"]), (False, True))
        self.assertEqual(P(["Status", "-", "-x", "-KeepPid", "12"]), (False, False))


# ── (3) 고르기 — Test-StopLM28.ps1 과 같은 가짜 목록 ──────────────────────────────────────────────
T0 = datetime(2026, 10, 14, 9, 0, 0).timestamp()
R = r"C:\LM28test\Load Monitor28"
OLD = r"C:\LM28test\Load Monitor28-old"
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
PSX = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
CMDX = r"C:\Windows\System32\cmd.exe"
PY = R + r"\python\python.exe"
SYSPY = r"C:\Python311\python.exe"


def P(pid, ppid, name, cmd, exe, minutes):
    return S.Proc(pid, ppid, name, cmd, exe, T0 + minutes * 60)


def _bat(name):
    return 'C:\\Windows\\system32\\cmd.exe /c ""' + R + "\\" + name + '" "'


FAKE = [
    P(50, 4, "explorer.exe", r"C:\Windows\Explorer.EXE", r"C:\Windows\explorer.exe", 0),
    # 대시보드(UI bat → 동봉 python ui\app.py) → run.py → 수집기·copilot_auto → 전용 Edge(+렌더러)
    P(100, 50, "cmd.exe", _bat("LoadMonitor28-UI.bat"), CMDX, 1),
    P(101, 100, "python.exe", '"' + PY + '"  ui\\app.py', PY, 2),
    P(107, 101, "conhost.exe", r"\??\C:\Windows\system32\conhost.exe 0xffffffff -ForceV1", r"C:\Windows\System32\conhost.exe", 2),
    P(102, 101, "python.exe", '"' + PY + '" "' + R + '\\run.py" --from 2026-01-01 --to 2026-10-14 --ai', PY, 3),
    P(103, 102, "powershell.exe",
      'powershell -NoProfile -ExecutionPolicy Bypass -File "' + R + '\\collect\\Get-OutlookData.ps1" -From 2026-01-01', PSX, 4),
    P(104, 102, "python.exe", '"' + PY + '" "' + R + '\\tools\\copilot_auto.py" --send x.txt', PY, 4),
    P(105, 104, "msedge.exe",
      '"' + EDGE + '" --remote-debugging-port=9533 --user-data-dir="' + R + '\\data\\lm28_edge" --no-first-run', EDGE, 5),
    P(106, 105, "msedge.exe", '"' + EDGE + '" --type=renderer --lang=ko', EDGE, 5),
    # 팀 서버(대시보드가 띄움) · 사람의 Edge(webbrowser.open) · 이동 준비 창 · 탐색기
    P(108, 101, "python.exe", '"' + PY + '" "' + R + '\\teamserver.py" --port 9310', PY, 6),
    P(109, 101, "msedge.exe", '"' + EDGE + '" --single-argument http://127.0.0.1:9248/', EDGE, 2),
    P(150, 101, "powershell.exe", 'powershell -NoProfile -ExecutionPolicy Bypass -File '
      '"C:\\Users\\홍길동\\AppData\\Local\\Temp\\LM28-Prepare-Move.ps1" -Root "' + R + '"', PSX, 7),
    P(160, 101, "explorer.exe", 'explorer "' + R + '\\report"', r"C:\Windows\explorer.exe", 7),
    # PID 재사용 — 부모(102)보다 먼저 생긴 '자식' 은 102 가 띄운 것이 아니다
    P(140, 102, "python.exe", r"python C:\other\x.py", SYSPY, -30),
    # 다른 폴더·다른 판·같은 파일 이름
    P(110, 50, "msedge.exe", '"' + EDGE + '" --user-data-dir="C:\\Users\\홍길동\\AppData\\Local\\Microsoft\\Edge\\User Data"',
      EDGE, 0),
    P(111, 50, "python.exe", '"' + OLD + '\\python\\python.exe" "' + OLD + '\\run.py"', OLD + "\\python\\python.exe", 1),
    P(112, 50, "python.exe", r'"C:\LM24\LoadMonitor24\python\python.exe" ui\app.py', r"C:\LM24\LoadMonitor24\python\python.exe", 1),
    P(113, 50, "python.exe", r"python C:\work\run.py --from 2026-01-01", SYSPY, 1),
    P(114, 50, "msedge.exe", r"msedge.exe --user-data-dir=C:\LM24\LoadMonitor24\data\lm24_edge", EDGE, 1),
    P(170, 50, "powershell.exe", 'powershell -NoProfile -File "' + OLD + '\\collect\\Get-OutlookData.ps1"', PSX, 1),
    # 이 스크립트 자신(강제종료 bat → powershell)
    P(119, 50, "cmd.exe", _bat("LoadMonitor28-강제종료.bat"), CMDX, 10),
    P(120, 119, "powershell.exe", 'powershell -NoProfile -ExecutionPolicy Bypass -File "' + R + '\\tools\\Stop-LM28.ps1"', PSX, 10),
    # PC 에 깔린 python 으로 LoadMonitor28.bat 을 돌린 경우(명령줄에 폴더가 없다 — 부모 bat 으로 안다)
    P(129, 50, "cmd.exe", _bat("LoadMonitor28.bat"), CMDX, 1),
    P(130, 129, "python.exe", "python  run.py --from 2026-01-01 --to 2026-10-14", SYSPY, 2),
    P(131, 130, "powershell.exe", 'powershell -NoProfile -File "' + R + '\\collect\\Get-PcOnHistory.ps1"', PSX, 3),
    P(171, 50, "pwsh.exe", 'pwsh -File "' + R.upper() + '/collect/Get-RecentFiles.ps1"', r"C:\Program Files\PowerShell\7\pwsh.exe", 1),
    # 팀서버 bat 으로 띄운 팀 서버
    P(180, 50, "cmd.exe", _bat("LoadMonitor28-팀서버.bat"), CMDX, 1),
    P(181, 180, "python.exe", '"' + PY + '" teamserver.py --port 9310', PY, 2),
]
# 파이썬 런처를 거친 강제종료(2026-10-15): 강제종료 bat(190) → 동봉 python tools\stop_lm28.py(191) → powershell(192)
LAUNCH = [p for p in FAKE if p.pid not in (119, 120)] + [
    P(190, 50, "cmd.exe", _bat("LoadMonitor28-강제종료.bat"), CMDX, 10),
    P(191, 190, "python.exe", '"' + PY + '" -X utf8 -B "' + R + '\\tools\\stop_lm28.py"', PY, 10),
    P(192, 191, "powershell.exe",
      'powershell -NoProfile -ExecutionPolicy Bypass -File "' + R + '\\tools\\Stop-LM28.ps1" -KeepPid 191', PSX, 10),
]
# PowerShell 이 끝내 못 켜져 파이썬(191)이 직접 끝내는 때 — 192 가 없다
FALLBACK = [p for p in LAUNCH if p.pid != 192]

BASE = "100,101,102,103,104,105,106,129,130,131,171"
WANT = {
    "targets": BASE,
    "kept": "108,150,181",
    "targets_ts": "100,101,102,103,104,105,106,108,129,130,131,171,180,181",
    "kept_ts": "150",
    "kinds": "100:console,101:python,102:python,103:powershell,104:python,105:edge,106:edge,"
             "129:console,130:python,131:powershell,171:powershell",
    "launcher": BASE,
    "keep_only": BASE + ",192",
    "no_keep": BASE + ",191,192",
    "self_only": BASE,
}


def _pids(items):
    return ",".join(str(x.pid) for x in sorted(items, key=lambda x: x.pid))


def py_answers():
    """Test-StopLM28.ps1 이 돌려주는 것과 같은 열쇠의 파이썬 답."""
    a = S.select_targets(FAKE, R, self_pid=120)
    b = S.select_targets(FAKE, R + "\\", include_team=True, self_pid=120)
    return {
        "targets": _pids(a["targets"]), "kept": _pids(a["kept"]),
        "targets_ts": _pids(b["targets"]), "kept_ts": _pids(b["kept"]),
        "kinds": ",".join(f"{x.pid}:{x.kind}" for x in a["targets"]),
        "launcher": _pids(S.select_targets(LAUNCH, R, self_pid=192, keep_pids=[191])["targets"]),
        "keep_only": _pids(S.select_targets(LAUNCH, R, self_pid=0, keep_pids=[191])["targets"]),
        "no_keep": _pids(S.select_targets(LAUNCH, R, self_pid=0)["targets"]),
        "self_only": _pids(S.select_targets(LAUNCH, R, self_pid=192)["targets"]),
    }


class Select(unittest.TestCase):

    def test_same_answers_as_ps_rules(self):
        self.assertEqual(py_answers(), WANT)

    def test_not_selected(self):
        t = {x.pid for x in S.select_targets(FAKE, R, self_pid=120)["targets"]}
        for pid, why in ((107, "conhost"), (109, "사람의 Edge(대시보드가 연 브라우저)"), (110, "사람의 Edge"),
                         (111, "이웃 폴더(-old)"), (112, "LM24"), (113, "같은 파일 이름 다른 폴더"), (114, "LM24 Edge"),
                         (170, "이웃 폴더 수집기"), (140, "PID 재사용"), (160, "탐색기"), (108, "팀 서버"), (181, "팀 서버"),
                         (150, "이동 준비 창"), (119, "강제종료 bat(자기 줄기)"), (120, "자기"), (50, "탐색기"), (180, "팀서버 bat")):
            self.assertNotIn(pid, t, why)

    def test_fallback_self_chain(self):
        # 파이썬 대안: 자기(191)와 강제종료 bat 창(190)은 빼고 나머지는 같다
        a = S.select_targets(FALLBACK, R, self_pid=191)
        self.assertEqual(_pids(a["targets"]), BASE)
        self.assertEqual(_pids(a["kept"]), "108,150,181")
        # 자기 줄기가 없어도 강제종료 bat 창은 콘솔 단계에서 빠진다(파이썬 191 은 '이 폴더 python' 이라 고른다)
        self.assertEqual(_pids(S.select_targets(FALLBACK, R)["targets"]), BASE + ",191")

    def test_pid_reuse_breaks_self_chain(self):
        # 부모 pid 가 재사용됐으면(부모가 자식보다 늦게 생김) 그 위로 올라가지 않는다 — 남의 cmd 를 '자기' 로 보지 않는다
        procs = [P(50, 4, "explorer.exe", "", "", 0), P(300, 50, "cmd.exe", _bat("LoadMonitor28-UI.bat"), CMDX, 20),
                 P(301, 300, "python.exe", '"' + PY + '" ui\\app.py', PY, 5)]
        a = S.select_targets(procs, R, self_pid=301)
        self.assertEqual(a["targets"], [])
        self.assertEqual(S.self_chain({p.pid: p for p in procs}, [301]), {301})
        # 시각을 모르면 믿는다(Test-LmOlder)
        unk = [p._replace(created=None) for p in procs]
        self.assertEqual(S.self_chain({p.pid: p for p in unk}, [301]), {301, 300, 50})

    def test_rules_helpers(self):
        self.assertEqual(S.root_key(R + "\\"), r"c:\lm28test\load monitor28" + "\\")
        self.assertEqual(S.root_key("C:/LM28test/Load Monitor28"), S.root_key(R))
        key = S.root_key(R)
        self.assertTrue(S.root_bat(S.norm(_bat("LoadMonitor28-UI.bat")), key))
        self.assertFalse(S.root_bat(S.norm('cmd /c ""' + OLD + '\\LoadMonitor28-UI.bat"'), key))
        self.assertTrue(S.dedicated_edge(S.norm("--user-data-dir=" + R + "\\data\\lm28_edge"), key + "data\\"))
        self.assertEqual(S.get_keep(P(1, 0, "Python.EXE", "x\\TeamServer.py", "", 0)), "teamserver")
        self.assertEqual(S.get_keep(P(1, 0, "pwsh.exe", "C:\\t\\LM28-Prepare-Move.ps1", "", 0)), "move")
        self.assertEqual(S.get_keep(P(1, 0, "cmd.exe", "teamserver.py", "", 0)), "")
        # .ps1 은 이 폴더 안에서 돌아야 한다 — 인자로만 나오는 폴더(-Root) 는 아니다
        self.assertEqual(S.get_kind(P(1, 0, "powershell.exe", 'powershell -File "C:\\t\\x.ps1" -Root "' + R + '"', "", 0),
                                    key, key + "data\\"), "")
        self.assertEqual(S.get_kind(P(1, 0, "powershell.exe", "powershell -File '" + R + "\\collect\\a.ps1'", "", 0),
                                    key, key + "data\\"), "powershell")

    def test_format(self):
        a = S.select_targets(FAKE, R, self_pid=120)
        now = datetime(2026, 10, 14, 10, 0, 0).timestamp()
        lines = " | ".join(S.format_state(a, now))
        for frag in ("끝낼 것 11개", "콘솔 창(bat) 2개", "전용 Edge(Copilot·웹 읽기) 2개", "[둠] 팀 서버 pid 108(54분)",
                     "PC 이동 준비 창 pid 150", "-IncludeTeamServer", "   · 콘솔 창(bat) 2개 - pid 100(59분) 129(59분)"):
            self.assertIn(frag, lines)
        self.assertEqual(S.format_state({"targets": [], "kept": []}, now), ["  끝낼 LM28 작업이 없습니다."])
        at = datetime(2026, 10, 14, 10, 5, 0).timestamp()
        self.assertEqual(S.format_age(datetime(2026, 10, 14, 8, 0, 0).timestamp(), at), "2시간 5분")
        self.assertEqual((S.format_age(None, at), S.format_age(at - 59, at), S.format_age(at - 61, at),
                          S.format_age(at + 30, at)), ("?", "59초", "1분", "0초"))


# ── (4) 파이썬 대안 실행 ─────────────────────────────────────────────────────────────────
class FakeOS:
    def __init__(self, procs, refuse=(), boom=False):
        self.procs, self.refuse, self.boom, self.stopped = list(procs), dict(refuse), boom, []

    def list(self):
        if self.boom:
            raise OSError(5, "목록 거부")
        return list(self.procs)

    def stop(self, pid, created):
        self.stopped.append(pid)
        if pid in self.refuse:
            return self.refuse[pid]
        self.procs = [p for p in self.procs if p.pid != pid]
        return None


class Fallback(unittest.TestCase):

    def _run(self, os_, status=False, team=False):
        said, waits = [], []
        rc = S.run_fallback(R, status, team, osapi=os_, say=said.append, sleep=waits.append,
                            now=lambda: T0 + 3600, self_pid=191)
        return rc, said, waits

    def test_status_lists_only(self):
        os_ = FakeOS(FALLBACK)
        rc, said, waits = self._run(os_, status=True)
        self.assertEqual((rc, os_.stopped, waits), (0, [], []))
        self.assertIn("  (-Status - 목록만 보여 주고 아무것도 끝내지 않았습니다)", said)
        self.assertIn("  끝낼 것 11개", said)
        self.assertIn("  LoadMonitor28 강제 종료 - 이 폴더의 LM28 작업만 끝냅니다", said)
        self.assertIn(f"  폴더: {R}", said)
        self.assertNotIn("  끝내는 중...", said)

    def test_stops_in_order_and_reports(self):
        os_ = FakeOS(FALLBACK)
        rc, said, waits = self._run(os_)
        self.assertEqual(rc, 0)
        self.assertEqual(os_.stopped, [100, 129, 101, 102, 104, 130, 103, 131, 171, 105, 106])   # 콘솔→파이썬→PS→Edge
        self.assertEqual(waits, [2])
        self.assertNotIn(191, os_.stopped)
        self.assertNotIn(190, os_.stopped)
        self.assertIn("  [결과] LM28 작업을 모두 끝냈습니다(11개).", said)
        self.assertIn("         팀 서버는 팀 전체가 쓰므로 그대로 두었습니다.", said)
        self.assertLess(said.index("  [지금]"), said.index("  끝내는 중..."))
        self.assertLess(said.index("  끝내는 중..."), said.index("  [끝낸 뒤]"))

    def test_include_team_server(self):
        os_ = FakeOS(FALLBACK)
        rc, said, _w = self._run(os_, team=True)
        self.assertEqual(rc, 0)
        self.assertIn(108, os_.stopped)
        self.assertIn(181, os_.stopped)
        self.assertIn(180, os_.stopped)
        self.assertNotIn(150, os_.stopped)

    def test_left_over_exit_1(self):
        os_ = FakeOS(FALLBACK, refuse={103: "액세스가 거부되었습니다. (5)"})
        rc, said, _w = self._run(os_)
        self.assertEqual(rc, 1)
        self.assertIn("  [결과] 1개가 아직 남아 있습니다:", said)
        self.assertIn("   · pid 103 powershell.exe - 끝내지 못했습니다(액세스가 거부되었습니다. (5))", said)
        self.assertIn("         다른 계정으로 실행됐거나 보안 프로그램이 막았을 수 있습니다. PC 를 다시 시작하면 모두 끝납니다.", said)

    def test_nothing_and_error(self):
        rc, said, waits = self._run(FakeOS([p for p in FALLBACK if p.pid in (50, 190, 191, 110)]))
        self.assertEqual((rc, waits), (0, []))
        self.assertIn("  [결과] 이미 모두 끝나 있습니다 - 끝낼 LM28 작업이 없습니다.", said)
        rc, said, _w = self._run(FakeOS([], boom=True))
        self.assertEqual(rc, 1)
        self.assertTrue(said[-1].startswith("  [!] 강제 종료 중 오류:"), said[-1])


# ── (5) 실제 목록 · 파일 ───────────────────────────────────────────────────────────────────
@unittest.skipUnless(os.name == "nt", "윈도 전용")
class RealList(unittest.TestCase):
    """ctypes 로 실제 프로세스 목록을 한 번 읽는다(읽기만 — 아무것도 끝내지 않는다 · 새 프로세스 없음)."""

    def test_reads_own_process(self):
        procs = S.WinProcs().list()
        self.assertGreater(len(procs), 5)
        me = [p for p in procs if p.pid == os.getpid()]
        self.assertEqual(len(me), 1)
        me = me[0]
        self.assertEqual(me.ppid, os.getppid())
        self.assertEqual(os.path.normcase(me.exe), os.path.normcase(os.path.abspath(sys.executable)))
        self.assertEqual(me.name.lower(), os.path.basename(sys.executable).lower())
        self.assertTrue(me.cmd)
        self.assertNotEqual(me.cmd, me.exe, "명령줄을 읽지 못했다(ProcessCommandLineInformation)")
        self.assertIsNotNone(me.created)
        self.assertLess(me.created, time.time() + 5)
        self.assertGreater(me.created, time.time() - 30 * 86400)
        self.assertEqual(S.select_targets(procs, r"C:\LM28test\nonexistent folder 9f3c", self_pid=os.getpid())["targets"], [])


class Files(unittest.TestCase):

    def _bat(self, name):
        b = _bytes(name)
        self.assertFalse(b.startswith(b"\xef\xbb\xbf"), name)
        self.assertEqual(b.count(b"\n"), b.count(b"\r\n"), name)
        return b.decode("cp949")

    def test_force_stop_bat(self):
        s = self._bat("LoadMonitor28-강제종료.bat")
        via = '"%PY_EXE%" %PY_ARGS% -X utf8 -B "%~dp0tools\\stop_lm28.py" %*'
        old = 'powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\\Stop-LM28.ps1" %*'
        for frag in (via, old, 'if exist "%~dp0python\\python.exe" set "PY_EXE=%~dp0python\\python.exe"', "python --version",
                     "rem 창을 닫았는데 뒤에서 계속 도는 것 같을 때 쓰는 비상 단추다.", 'if not exist "tools\\Stop-LM28.ps1" (',
                     "exit /b %RC%"):
            self.assertIn(frag, s)
        # 파이썬이 있으면 파이썬 길, 없으면 예전 줄 — 둘 다 결과를 보이게 멈춘다(pause 하나)
        self.assertLess(s.index("goto VIA_PY"), s.index(old))
        self.assertLess(s.index(":VIA_PY"), s.index(via))
        tail = s[s.index(":DONE"):]
        self.assertIn("pause", tail)
        self.assertEqual(s.count("pause"), 2)                     # 파일 없음 안내 + 끝
        self.assertNotIn("set /p", s.lower())

    def test_diag_bat(self):
        s = self._bat("LoadMonitor28-수집진단.bat")
        via = '"%PY_EXE%" -X utf8 -B tools\\ps_launch.py "collect\\Diagnose-Collectors.ps1"'
        old = 'powershell -NoProfile -ExecutionPolicy Bypass -File "collect\\Diagnose-Collectors.ps1"'
        for frag in (via, old, '"%PY_EXE%" -X utf8 -B tools\\diag_bundle.py', "rem (실측: SetConsoleOutputCP(65001) 까지 수행)."):
            self.assertIn(frag, s)
        self.assertLess(s.index(via), s.index(">nul chcp 949\r\necho.\r\necho  [진단 묶음]"))
        self.assertLess(s.index('if not defined PY_EXE set "PY_EXE=python"'), s.index("tools\\diag_bundle.py"))
        mv = self._bat("LoadMonitor28-이동준비.bat")              # 이동 준비는 %TEMP% 에서 돌아 그대로 둔다
        self.assertNotIn("ps_launch", mv)

    def test_need_and_ps1(self):
        src = _boot.read_text(os.path.join(ROOT, "자가점검.py"))
        need = next(ast.literal_eval(n.value) for n in ast.parse(src).body
                    if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "NEED")
        for rel in ("tools/ps_launch.py", "tools/stop_lm28.py"):
            self.assertIn(rel, need)
            self.assertTrue(os.path.isfile(os.path.join(ROOT, rel)), rel)
        b = _bytes(os.path.join("tools", "Stop-LM28.ps1"))
        self.assertTrue(b.startswith(b"\xef\xbb\xbf"))
        self.assertEqual(b.count(b"\n"), b.count(b"\r\n"))
        ps = b.decode("utf-8-sig")
        for frag in ("[string]$KeepPid = ''", "[int[]]$KeepPid = @()", "@(@($SelfPid) + @($KeepPid))",
                     "-SelfPid $PID -KeepPid $Keep", "(ConvertTo-LmPids $KeepPid)"):
            self.assertIn(frag, ps)
        for rel in (os.path.join("tools", "ps_launch.py"), os.path.join("tools", "stop_lm28.py")):
            b = _bytes(rel)
            self.assertFalse(b.startswith(b"\xef\xbb\xbf"), rel)
            self.assertNotIn(b"\r\n", b, rel)

    def test_docs(self):
        readme = _boot.read_text(os.path.join(ROOT, "README.md"))
        self.assertIn("**2026-10-15 — 강제종료", readme)
        guide = _boot.read_text(os.path.join(ROOT, "docs", "설정가이드.md"))
        sec = guide[guide.index("## 8-4."):guide.index("## 무엇부터 하면 되나")]
        self.assertIn("LoadMonitor28-강제종료.bat", sec[sec.index("0xc0000142"):])
        field = _boot.read_text(os.path.join(ROOT, "docs", "현장점검_LM28.md"))
        sec = field[field.index("## 4-8."):field.index("## 4-9.")]
        self.assertIn("PowerShell 을 끝내 띄우지 못해 파이썬으로 같은 규칙대로 끝냅니다", sec)


# ── (6) --ps ──────────────────────────────────────────────────────────────────────────
class PsParity(unittest.TestCase):

    def test_launcher_chain_and_parity(self):
        r = _boot.ps_result("StopLM28")
        if r is None:
            self.skipTest("PowerShell 결과 없음 — tests\\run_tests.py p24 --ps-only=StopLM28 로 실행")
        self.assertNotIn("error", r, r)
        for k, v in WANT.items():
            self.assertEqual(r[k], v, k)
        self.assertEqual({k: r[k] for k in WANT}, py_answers())          # 파이썬 사본과 같은 답
        self.assertEqual(r["keep_parse"], "191,7")
        self.assertEqual(r["keep_empty"], 0)


if __name__ == "__main__":
    unittest.main()
