# -*- coding: utf-8 -*-
"""WP-13 PS 스크립트 시험 — ``collect\\agent\\{agent.ps1, harvest.ps1, Register-Agent.ps1}``(계약 §7.3 · §9.2 · L-09 · L-15 ·
X-307 · O-13, TAB §1.6.4 · TAB-B16 · B22).

  · 인코딩(UTF-8 BOM + CRLF · 제어문자 0) · 구문 오류 0(PS 파서 — 실행하지 않는다, 계약 O-13) · 관문 hook_check 통과.
  · 순수 함수를 AST 로 꺼내(스크립트 본문은 돌리지 않는다) 파이썬 구현과 같은 값인지: 유휴 모듈로 · 세션 대응 · 간격 확정 ·
    pc.sampler·pc.compute 원시 레코드(TAB-B22 — 같은 입력이면 정제 뒤 같은 id·doc_key) · 연결자 계획·상한·사유.
  · Register-Agent: 옛 작업 정리 대상(TAB-B16 — prior_install_ids 이고 Action 이 이 에이전트 폴더인 것만) · Action 문자열 =
    파이썬 ``agent_entry`` · -DryRun(등록 0 — XML 의 Action·WorkingDirectory 가 에이전트 폴더, 임시 XML 남김 0).
실제 작업 등록·샘플링·수집은 하지 않는다.
"""
import html
import json
import os
import re
import subprocess
import sys
import unittest
from datetime import UTC, datetime

from lm27.agent import harvest as HV
from lm27.agent import install as I
from lm27.agent import main as M
from lm27.agent import sampler as S
from lm27.paths import Paths
from lm27.privacy.sanitize import make_record_context, sanitize_record
from tests.fixtures.tree import CloneTestCase
from tests.fixtures.wp13 import helpers as H

ROOT = H.REAL_ROOT
AGENT_PS = ROOT / "collect" / "agent" / "agent.ps1"
HARVEST_PS = ROOT / "collect" / "agent" / "harvest.ps1"
REGISTER_PS = ROOT / "collect" / "agent" / "Register-Agent.ps1"
SCRIPTS = (AGENT_PS, HARVEST_PS, REGISTER_PS)
JSON_FUNCS = ["ConvertTo-LmJson", "ConvertTo-LmJsonString", "Format-LmUtc", "Format-LmOffset"]


def lines(cp) -> list:
    return [json.loads(x) for x in cp.stdout.decode("utf-8").splitlines() if x.strip().startswith(("{", "["))]


class StaticTest(unittest.TestCase):
    def test_encoding_bom_crlf(self):
        for p in SCRIPTS:
            b = p.read_bytes()
            self.assertTrue(b.startswith(b"\xef\xbb\xbf"), p.name)
            self.assertEqual(b.count(b"\n"), b.count(b"\r\n"), p.name)
            self.assertIsNone(re.search(rb"[\x00-\x08\x0b\x0c\x0e-\x1f]", b), p.name)

    def test_parse_and_hook(self):
        sb = H.Sandbox()
        self.addCleanup(sb.cleanup)
        body = ("foreach ($f in @(" + ",".join(f"'{p}'" for p in SCRIPTS) + ")) {\n"
                "  $t = $null; $e = $null\n"
                "  [void][System.Management.Automation.Language.Parser]::ParseFile($f, [ref]$t, [ref]$e)\n"
                "  [Console]::Out.WriteLine((ConvertTo-LmJson ([ordered]@{ f = [IO.Path]::GetFileName($f); n = $e.Count })))\n"
                "}\n")
        cp = H.run_ps_funcs(sb, AGENT_PS, JSON_FUNCS, body)
        self.assertEqual(cp.returncode, 0, cp.stderr.decode("utf-8", "replace"))
        self.assertEqual({d["f"]: d["n"] for d in lines(cp)}, {p.name: 0 for p in SCRIPTS})
        r = subprocess.run([sys.executable, "-X", "utf8", "-B", str(ROOT / "tools" / "hook_check.py"),
                            *(str(p) for p in SCRIPTS)], capture_output=True, timeout=120, cwd=str(sb.dir),
                           creationflags=H.CREATE_NO_WINDOW)
        self.assertEqual(r.returncode, 0, r.stdout.decode("utf-8", "replace") + r.stderr.decode("utf-8", "replace"))

    def test_no_store_paths_and_names(self):
        for p in (AGENT_PS, HARVEST_PS):
            t = p.read_text(encoding="utf-8-sig")
            self.assertNotRegex(t, r"(?i)'(?:store|evidence)'")              # store 는 파이프만 쓴다(TAB-B22)
            self.assertIn("--mode append", t)
            self.assertNotRegex(t, r"(?i)\bOut-File\b|\bSet-Content\b|\bAdd-Content\b")
        t = REGISTER_PS.read_text(encoding="utf-8-sig")
        self.assertIn("ExecutionTimeLimit>PT0S", t)
        self.assertIn("IgnoreNew", t)
        self.assertIn("InteractiveToken", t)
        self.assertIn("RestartOnFailure", t)
        self.assertNotRegex(t, r"PSScriptRoot")                            # 등록 Action 은 에이전트 폴더(사본)만

    def test_loop_schedule_monotonic_and_children_stopped(self):
        """W1b 회귀(정적 — ps 는 벽시계를 흉내 낼 수 없다): 감독 루프 일정은 Stopwatch(단조 초)로 잡고 벽시계 비교로 틱·수확·
        자식·플러시·보존 정리를 잡지 않는다(시계가 뒤로 가면 그 폭만큼 멈추던 결함). 루프가 끝나면 세 자식(수확·teams.uia·
        폴링)을 Stop-LmTree 로 끈다(정지·제거 뒤 고아 수집 0)."""
        t = AGENT_PS.read_text(encoding="utf-8-sig")
        body = t[t.index("function Invoke-LmAgent"):]
        start = body.index("while (-not [IO.File]::Exists($stopFlag))")
        stop = body.index("# 종료: 살아 있는 자식")
        loop, tail = body[start:stop], body[stop:body.index("# 종료: 마지막 틱")]
        self.assertIn("[Diagnostics.Stopwatch]::StartNew()", body)
        self.assertNotRegex(loop, r"\$(?:nextTick|nextHarvest|maintAt|cfgAt|catAt|teamsAt|pollAt|lastFlush|harvestStarted)\b")
        self.assertIn("$m -lt $nextTickM", loop)
        for v in ("$harvestChild", "$teamsChild", "$pollChild"):
            self.assertIn(v, tail)
        self.assertIn("Stop-LmTree $ch.Id", tail)

    def test_bad_args_exit_without_work(self):
        sb = H.Sandbox()
        self.addCleanup(sb.cleanup)
        env = dict(os.environ, LOCALAPPDATA=str(sb.lad), TEMP=str(sb.dir), TMP=str(sb.dir))
        for p, args, want in ((AGENT_PS, ["-InstallId", "bad", "-TestSamples", "1"], 5),
                              (HARVEST_PS, ["-InstallId", "bad", "-Streams", "teams/teams.uia"], 5),
                              (REGISTER_PS, ["-InstallId", "bad", "-DryRun"], 1)):
            cp = subprocess.run([H.powershell(), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(p),
                                 *args], capture_output=True, timeout=120, env=env, cwd=str(sb.dir),
                                creationflags=H.CREATE_NO_WINDOW)
            self.assertEqual(cp.returncode, want, (p.name, cp.stderr.decode("utf-8", "replace")))
        self.assertEqual(lines(cp)[0]["_register"]["reason"], "bad_args")
        self.assertFalse(sb.lad.exists())


class AgentFuncTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sb = H.Sandbox()
        cls.addClassCleanup(cls.sb.cleanup)

    def ps(self, names, body):
        cp = H.run_ps_funcs(self.sb, AGENT_PS, list(names) + JSON_FUNCS, body)
        self.assertEqual(cp.returncode, 0, cp.stderr.decode("utf-8", "replace"))
        return lines(cp)

    def test_idle_same_as_python(self):
        cases = [(10_000, 7_000), ((1 << 32) + 5_000, 2_000), ((1 << 32) + 1_000, (1 << 32) - 2_000), (2_500, 0), (3_500, 0),
                 (1_500, 0), (10 ** 12, 1), (60_000, 60_000)]
        body = "\n".join(f"[Console]::Out.WriteLine((ConvertTo-LmJson @(Get-LmIdleSec {a} {b})))" for a, b in cases)
        got = [x[0] for x in self.ps(["Get-LmIdleSec"], body)]
        self.assertEqual(got, [S.idle_sec(a, b) for a, b in cases])

    def test_session_same_as_python(self):
        combos = [(st, fl, pr) for st in (0, 4, None) for fl in (0, 1, -1, None) for pr in (0, 2, None)]
        ps_val = lambda v: "$null" if v is None else str(v)                 # noqa: E731
        body = "\n".join(f"$r = Get-LmSession {ps_val(a)} {ps_val(b)} {ps_val(c)}; "
                         "[Console]::Out.WriteLine((ConvertTo-LmJson @([string]$r[0], [bool]$r[1])))" for a, b, c in combos)
        got = [tuple(x) for x in self.ps(["Get-LmSession"], body)]
        self.assertEqual(got, [S.map_session(*c) for c in combos])

    def test_interval_same_as_loop(self):
        cases = [(60.0, 60), (59.4, 60), (89.0, 60), (91.0, 60), (0.0, 60), (-5.0, 60), (30.5, 30), (179.0, 120)]
        body = "\n".join(f"[Console]::Out.WriteLine((ConvertTo-LmJson @(Get-LmInterval {d} {n})))" for d, n in cases)
        got = [x[0] for x in self.ps(["Get-LmInterval"], body)]
        want = [n if d <= 0 or d > n * M.GAP_CAP else int(round(d)) for d, n in cases]
        self.assertEqual(got, want)

    def test_tick_record_same_as_python_b22(self):
        """TAB-B22 — 같은 원시 틱이면 ps 구현과 py 구현이 같은 원시 레코드, 정제 뒤 같은 id·doc_key."""
        keys = ("fg_exe", "fg_title", "session_state", "remote", "idle_sec", "off_min", "interval", "doc")
        rows = [("excel.exe", "견적_v2.xlsx - Excel", "active", False, 12, 540, 60, None),
                ("", "", "locked", False, 900, 540, 60, None),
                ("lockapp.exe", "", "locked", True, None, 0, 0, None),
                ("사내 도구.exe", "과제A - 해석", "remote", True, 3, -300, 59, None),
                ("winword.exe", "회의록.docx - Word", "active", False, 0, 540, 60, r"C:\work\과제A\회의록.docx")]
        cases = [dict(zip(keys, r, strict=True)) for r in rows]
        cats = {o["exe"]: o for o in M.classify_lines([c["fg_exe"] for c in cases if c["fg_exe"]], {})}
        for c in cases:
            c["ts"] = "2026-10-05T01:00:00"
            c["cat"] = cats.get(c["fg_exe"].lower()) if c["fg_exe"] else None
        cf = self.sb.dir / "cases.json"
        cf.write_text(json.dumps(cases, ensure_ascii=False), encoding="utf-8")
        body = (f"$cases = ConvertFrom-Json -InputObject ([IO.File]::ReadAllText('{cf}', $script:Utf8))\n"
                "foreach ($c in $cases) {\n"
                "  $ts = [datetime]::SpecifyKind([datetime]::ParseExact($c.ts, 'yyyy-MM-ddTHH:mm:ss', $script:Inv), 'Utc')\n"
                "  $tick = [pscustomobject]@{ ts = $ts; off_min = [int]$c.off_min; fg_exe = [string]$c.fg_exe;\n"
                "     fg_title = [string]$c.fg_title; session_state = [string]$c.session_state; remote = [bool]$c.remote;\n"
                "     idle_sec = $c.idle_sec }\n"
                "  $cat = $null\n"
                "  if ($null -ne $c.cat) { $cat = @{ fg_exe = $c.cat.fg_exe; app_id = $c.cat.app_id; app_class = [string]$c.cat.app_class } }\n"
                "  [Console]::Out.WriteLine((ConvertTo-LmJson (New-LmTickRecord $tick ([int]$c.interval) $cat ([string]$c.doc))))\n"
                "}\n")
        got = self.ps(["New-LmTickRecord"], body)
        self.assertEqual(len(got), len(cases))
        sb = H.Sandbox()
        self.addCleanup(sb.cleanup)
        sb.agent_files()
        rc = make_record_context(None, "pc.sampler", "pc_0a1b2c3d4e5f6a7b", agent_dir=sb.paths.agent_dir())
        for c, ps_rec in zip(cases, got, strict=True):
            tick = S.RawTick(ts=datetime(2026, 10, 5, 1, 0, tzinfo=UTC), off_min=c["off_min"],
                             fg_exe=S.catalog.exe_name(c["fg_exe"]) if c["fg_exe"] else "", fg_title=c["fg_title"],
                             session_state=c["session_state"], remote=c["remote"], idle_sec=c["idle_sec"])
            py_rec = S.tick_record(tick, c["interval"], doc_path=c["doc"])
            self.assertEqual(ps_rec, py_rec, c["fg_exe"])
            a, b = sanitize_record("pc_session", ps_rec, rc), sanitize_record("pc_session", py_rec, rc)
            self.assertEqual(a.status, "stored")
            self.assertEqual((a.row.data["id"], a.row.data.get("doc_key")), (b.row.data["id"], b.row.data.get("doc_key")))

    def test_compute_record_same_as_python(self):
        body = ("$script:Cat = @{ 'fluent.exe' = @{ fg_exe = 'fluent.exe'; app_id = 'ansys_fluent'; app_class = 'sim'; solver = $true } }\n"
                "$s = [datetime]::SpecifyKind([datetime]'2026-10-05T01:00:00', 'Utc')\n"
                "$run = @{ app_id = 'ansys_fluent'; exe = 'fluent.exe'; start = $s; last = $s.AddMinutes(4); ticks = 4; core = 360.0; wall = 240.0 }\n"
                "[Console]::Out.WriteLine((ConvertTo-LmJson (New-LmComputeRecord $run 540 $s.AddMinutes(5) $true)))\n"
                "[Console]::Out.WriteLine((ConvertTo-LmJson (New-LmComputeRecord $run 540 $s.AddMinutes(5) $false)))\n")
        got = self.ps(["New-LmComputeRecord"], body)
        t0 = datetime(2026, 10, 5, 1, 0, tzinfo=UTC)
        run = S._Run(app_id="ansys_fluent", exe="fluent", start=t0, last=t0.replace(minute=4), ticks=4, core_s=360.0,
                     wall_s=240.0)
        self.assertEqual(got[0], S.compute_record(run, 540, t0.replace(minute=5), final=True))
        self.assertEqual(got[1], S.compute_record(run, 540, t0.replace(minute=5), final=False))


class HarvestFuncTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sb = H.Sandbox()
        cls.addClassCleanup(cls.sb.cleanup)

    def ps(self, names, body):
        cp = H.run_ps_funcs(self.sb, HARVEST_PS, list(names) + JSON_FUNCS, body)
        self.assertEqual(cp.returncode, 0, cp.stderr.decode("utf-8", "replace"))
        return lines(cp)

    def test_plan_timeout_reason_lastjson(self):
        spec = "$spec = @{ 'pc.events' = @{ kind = 'pc_session'; script = 'Get-EventActivity.ps1'; harvest = $true }; " \
               "'teams.uia' = @{ kind = 'teams'; script = 'Get-TeamsWindow.ps1'; harvest = $false }; " \
               "'pc.files' = @{ kind = 'pc_file'; script = 'Get-FileActivity.ps1'; harvest = $true } }\n"
        body = spec + (
            "$pl = Get-LmPlan 'pc_session/pc.events, teams/teams.uia,pc_file/pc.events,x' $false $spec\n"
            "[Console]::Out.WriteLine((ConvertTo-LmJson $pl))\n"
            "$pl = Get-LmPlan '' $true $spec\n"
            "[Console]::Out.WriteLine((ConvertTo-LmJson $pl))\n"
            "$cfg = ConvertFrom-Json '{\"teams.uia.budgetSec\": 40, \"pc.files.budgetSec\": 100}'\n"
            "$o = @()\n"
            "foreach ($p in @(@{src='teams.uia';poll=$false}, @{src='pc.events';poll=$false}, @{src='pc.files';poll=$false}, @{src='pc.files';poll=$true}, @{src='pc.mru';poll=$false})) { $o += (Get-LmCollectorTimeout $p $cfg) }\n"
            "[Console]::Out.WriteLine((ConvertTo-LmJson $o))\n"
            "[Console]::Out.WriteLine((ConvertTo-LmJson @((Get-LmPipeReason 6), (Get-LmPipeReason 99), (Get-LmPipeReason 3), (Get-LmPipeReason 0), (Get-LmPipeReason $null))))\n"
            "$t = \"x`n{`\"_status`\": {`\"rc`\": 1}}`n잡음`n{`\"_status`\": {`\"rc`\": 3, `\"reasons`\": [`\"R-UIAEMPTY`\"]}}`n\"\n"
            "[Console]::Out.WriteLine((ConvertTo-LmJson (Get-LmLastJson $t '_status')))\n")
        plan, poll, tmo, reasons, st = self.ps(["Get-LmPlan", "Get-LmCollectorTimeout", "Get-LmCfgInt", "Get-LmPipeReason",
                                                "Get-LmLastJson"], body)
        self.assertEqual([(p["src"], p["kind"], p["harvest"]) for p in plan],
                         [("pc.events", "pc_session", True), ("teams.uia", "teams", False)])   # 형식이 틀린 흐름은 뺀다
        self.assertEqual((len(poll), poll[0]["src"], poll[0]["poll"], poll[0]["harvest"]), (1, "pc.files", True, False))
        st_py = {"teams.uia.budgetSec": 40, "pc.files.budgetSec": 100}
        want = [HV.collector_timeout(HV.COLLECTORS["teams.uia"], st_py), HV.collector_timeout(HV.COLLECTORS["pc.events"], st_py),
                HV.collector_timeout(HV.COLLECTORS["pc.files"], st_py), HV.collector_timeout(HV.POLL, st_py),
                HV.collector_timeout(HV.COLLECTORS["pc.mru"], st_py)]
        self.assertEqual(tmo, want)
        self.assertEqual(reasons, [HV.PIPE_FAIL[6], HV.PIPE_FAIL[99], HV.PIPE_FAIL[3], None, None])
        self.assertEqual(st, {"rc": 3, "reasons": ["R-UIAEMPTY"]})

    def test_window_same_as_python(self):
        """수확 창(-Since·-Until) — ps 구현 Get-LmWindow 가 파이썬 harvest_window 와 같은 값(통합 — W2 C03 에이전트 쪽)."""
        cases = [({"collect.lookbackDays": 120, "time.tzOffsetMin": 540}, "2026-10-06T15:30:00"),
                 ({"collect.lookbackDays": 120, "time.tzOffsetMin": 540, "collect.sinceYearStart": False}, "2026-10-06T15:30:00"),
                 ({"collect.lookbackDays": 400, "time.tzOffsetMin": 540}, "2026-10-06T15:30:00"),
                 ({"collect.lookbackDays": 30, "time.tzOffsetMin": 0, "collect.sinceYearStart": True}, "2026-01-01T03:00:00"),
                 ({}, "2026-12-31T23:59:00")]
        body = ""
        for cfg, now in cases:
            js = json.dumps(cfg).replace("'", "''")
            body += (f"$cfg = ConvertFrom-Json '{js}'\n"
                     f"$n = [datetime]::SpecifyKind([datetime]::ParseExact('{now}', 'yyyy-MM-ddTHH:mm:ss', $script:Inv), 'Utc')\n"
                     "[Console]::Out.WriteLine((ConvertTo-LmJson (Get-LmWindow $cfg $n)))\n")
        got = self.ps(["Get-LmWindow", "Get-LmCfgInt"], body)
        want = [list(HV.harvest_window(cfg, datetime.fromisoformat(now).replace(tzinfo=UTC))) for cfg, now in cases]
        self.assertEqual(got, want)


class RegisterTest(unittest.TestCase):
    def setUp(self):
        self.sb = H.Sandbox()
        self.addCleanup(self.sb.cleanup)
        self.lad_base = self.sb.dir / "LocalAppData"                    # %LOCALAPPDATA% 대역
        self.paths = Paths(self.sb.root, lad=self.lad_base / "LoadMonitor27")
        self.agent = self.paths.agent_dir()

    def ps(self, names, body):
        cp = H.run_ps_funcs(self.sb, REGISTER_PS, list(names) + ["ConvertTo-LmJson", "ConvertTo-LmJsonString"], body)
        self.assertEqual(cp.returncode, 0, cp.stderr.decode("utf-8", "replace"))
        return lines(cp)

    def test_stale_selection_b16(self):
        """TAB-B16 — 지우는 것: prior_install_ids 에 있고 Action 이 이 에이전트 폴더를 가리키는 작업만."""
        a = str(self.agent)
        cur, old1, old2, stranger = H.IID, "a" * 32, "b" * 32, "c" * 32
        tasks = [
            {"name": "LM27T-" + old1, "command": a + "\\bin\\0.1.0-x\\py311\\pythonw.exe", "arguments": "--install-id " + old1},
            {"name": "LM27T-" + old2, "command": "C:\\Elsewhere\\py311\\pythonw.exe", "arguments": "--install-id " + old2},
            {"name": "LM27T-" + cur, "command": a + "\\bin\\0.1.0-x\\py311\\pythonw.exe", "arguments": ""},
            {"name": "LM27T-" + stranger, "command": a + "\\bin\\x\\py311\\pythonw.exe", "arguments": ""},
            {"name": "LoadMonitor24-Sampler", "command": "powershell.exe", "arguments": "-File " + a},
            {"name": "LM27T-" + old2 + "x", "command": "powershell.exe", "arguments": '-File "' + a.upper() + '\\BIN\\ps\\agent.ps1"'},
        ]
        tf = self.sb.dir / "tasks.json"
        tf.write_text(json.dumps(tasks), encoding="utf-8")
        body = (f"$tasks = ConvertFrom-Json -InputObject ([IO.File]::ReadAllText('{tf}', $script:Utf8))\n"
                f"$r = Select-LmStaleTask $tasks '{a}' '{cur}' @('{old1}', '{old2}', '{cur}', 'zz') 'LM27T'\n"
                "[Console]::Out.WriteLine((ConvertTo-LmJson @($r)))\n"
                f"$r = Select-LmStaleTask @([pscustomobject]@{{ name = 'LM27T-{old2}'; command = 'powershell.exe';"
                f" arguments = '-File \"{a}\\bin\\ps\\agent.ps1\"' }}) '{a}' '{cur}' @('{old2}') 'LM27T'\n"
                "[Console]::Out.WriteLine((ConvertTo-LmJson @($r)))\n")
        r1, r2 = self.ps(["Select-LmStaleTask", "Test-LmInstallId"], body)
        self.assertEqual(r1, ["LM27T-" + old1])
        self.assertEqual(r2, ["LM27T-" + old2])                             # ps 구현 — 인자에 에이전트 폴더

    def test_entry_same_as_python(self):
        body = "\n".join(f"[Console]::Out.WriteLine((ConvertTo-LmJson (Get-LmEntry '{self.agent}' '0.1.0-abcdef12' '{impl}' "
                         f"'{H.IID}')))" for impl in ("py", "ps"))
        got = self.ps(["Get-LmEntry"], body)
        for impl, g in zip(("py", "ps"), got, strict=True):
            self.assertEqual(g, I.agent_entry(self.paths, "0.1.0-abcdef12", impl, H.IID), impl)

    def test_dry_run_xml(self):
        """-DryRun: 등록·삭제 0, 작업 스케줄러 파서 검증만. Action·WorkingDirectory = 에이전트 폴더(사본), 임시 XML 남김 0."""
        tmp = self.sb.dir / "Temp"
        tmp.mkdir()
        env = dict(os.environ, LOCALAPPDATA=str(self.lad_base), TEMP=str(tmp), TMP=str(tmp))
        cp = subprocess.run([H.powershell(), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
                             str(REGISTER_PS), "-InstallId", H.IID, "-AgentVer", "0.1.0-abcdef12", "-Impl", "py", "-DryRun",
                             "-TaskPrefix", "LM27T"], capture_output=True, timeout=120, env=env, cwd=str(self.sb.dir),
                            creationflags=H.CREATE_NO_WINDOW)
        self.assertEqual(cp.returncode, 0, cp.stderr.decode("utf-8", "replace"))
        r = lines(cp)[0]["_register"]
        self.assertEqual((r["task"], r["op"], r["ok"], r["started"], r["removed_prior"]),
                         ("LM27T-" + H.IID, "dry_run", True, False, 0))
        self.assertIn(r["valid"], (True, None))
        self.assertEqual(r["entry"], I.agent_entry(self.paths, "0.1.0-abcdef12", "py", H.IID))
        xml = r["xml"]
        self.assertIn(f"<WorkingDirectory>{self.agent}</WorkingDirectory>", xml)
        self.assertIn("<ExecutionTimeLimit>PT0S</ExecutionTimeLimit>", xml)
        self.assertIn("<MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>", xml)
        self.assertIn("<LogonType>InteractiveToken</LogonType>", xml)
        self.assertIn("<Count>99</Count>", xml)
        # Action 의 경로는 모두 에이전트 폴더 안(사본) — 복제 시험에서는 샌드박스가 ROOT 아래라 단순 부분 문자열 검사는 쓰지 않는다
        act = {t: html.unescape(m.group(1)) for t in ("Command", "Arguments", "WorkingDirectory")
               for m in [re.search(f"<{t}>(.*?)</{t}>", xml, re.S)] if m}
        agent, bin_dir = str(self.agent), str(self.agent / "bin") + "\\"
        self.assertEqual(act["WorkingDirectory"], agent)
        self.assertTrue(act["Command"].startswith(bin_dir), act)                      # 사본 파이썬
        quoted = re.findall(r'"([^"]+)"', act["Arguments"])
        self.assertTrue(quoted and all(q.startswith(bin_dir) for q in quoted), act)   # 사본 진입 스크립트만
        for prog in ("python", "lm27", "collect", "lm27_cli.py", "lm27_pipe.py", "agent_main.py"):
            self.assertNotIn(str(ROOT / prog), xml)                                   # 프로그램 폴더(ROOT) 진입점 0
        self.assertEqual(list(tmp.iterdir()), [])
        self.assertFalse(self.agent.exists())                               # 아무것도 만들지 않는다


class PsBinEndToEndTest(CloneTestCase):
    """ps 구현 실물 이음 — 복제 트리에서 만든 bin 사본(샌드박스 LAD)의 사본 파이썬·사본 파이프로:
    agent.ps1 의 플러시 함수가 파이프(--mode append)로만 기록하고 py 구현과 같은 id·doc_key(TAB-B22), harvest.ps1 전체 실행
    (사본의 이벤트 수집기 자리에 합성 PS 수집기 — 실제 이벤트 로그 0) → store·커서·harvest_done.json·잠금 해제."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        import shutil
        shutil.copytree(cls.clone.py_home, cls.clone.path("python"), ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        cls.sb = H.Sandbox()
        cls.addClassCleanup(cls.sb.cleanup)
        cls.base = cls.sb.dir / "LocalAppData"
        cls.paths = Paths(cls.clone.root, lad=cls.base / "LoadMonitor27")
        cls.sb.paths = cls.paths
        files, missing = I.bin_files(cls.paths)
        assert not missing, missing
        hashed = I._hashed(files)
        cls.ver = I.build_ver(hashed)
        I.install_bin(cls.paths, hashed, cls.ver)
        cls.bin = cls.paths.agent_bin(cls.ver)
        cls.sb.agent_files()
        cls.pc = "pc_0a1b2c3d4e5f6a7b"
        cls.aj = {"schema": "lm27.agent/1", "install_id": H.IID, "pc_id": cls.pc, "agent_ver": cls.ver, "impl": "ps"}
        cls.sb.write_json(cls.paths.agent_json(), cls.aj)
        cls.env = dict(os.environ, LOCALAPPDATA=str(cls.base), TEMP=str(cls.sb.dir), TMP=str(cls.sb.dir))

    def setUp(self):
        # --start-check 는 지금 pc_id 로 agent.json 을 고친다(TAB-B26) — 테스트마다 고정 pc_id 로 되돌려 순서와 무관하게
        self.sb.write_json(self.paths.agent_json(), self.aj)

    def test_agent_flush_through_pipe_b22(self):
        b, agent = self.bin, self.paths.agent_dir()
        body = (f"$script:Py = '{b}\\py311\\python.exe'; $script:Pipe = '{b}\\lm27_pipe.py'; $script:Main = '{b}\\agent_main.py'\n"
                f"$script:AgentDir = '{agent}'; $InstallId = '{H.IID}'\n"
                "$script:Cat = @{}; $script:DocMap = @{}; $script:DocAt = [datetime]::UtcNow\n"
                "$script:KeepClasses = @('office', 'cad', 'sim', 'eda', 'ide', 'pdf', 'viewer')\n"
                "$ts = [datetime]::SpecifyKind([datetime]'2026-10-05T01:00:00', 'Utc')\n"
                "$buf = New-Object 'Collections.Generic.List[object]'\n"
                "$buf.Add(@{ tick = [pscustomobject]@{ ts = $ts; off_min = 540; fg_exe = 'excel.exe'; fg_title = '견적_v2.xlsx - Excel';"
                " session_state = 'active'; remote = $false; idle_sec = 5 }; interval = 60 })\n"
                "$buf.Add(@{ tick = [pscustomobject]@{ ts = $ts.AddMinutes(1); off_min = 540; fg_exe = 'acad.exe';"
                " fg_title = 'C:\\work\\과제A\\도면.dwg - AutoCAD'; session_state = 'active'; remote = $false; idle_sec = 1 }; interval = 60 })\n"
                "$buf.Add(@{ tick = [pscustomobject]@{ ts = $ts.AddMinutes(2); off_min = 540; fg_exe = ''; fg_title = '';"
                " session_state = 'locked'; remote = $false; idle_sec = 70 }; interval = 60 })\n"
                "$comp = New-Object 'Collections.Generic.List[object]'\n"
                "$code = Invoke-LmFlush $buf $comp @{} 3 '" + self.pc + "' $null 540 $ts.AddMinutes(3) $false\n"
                "[Console]::Out.WriteLine((ConvertTo-LmJson @($code)))\n")
        names = ["Invoke-LmFlush", "Send-LmPipe", "Invoke-LmPy", "Start-LmProc", "Stop-LmTree", "Update-LmCatalog",
                 "New-LmTickRecord", "New-LmComputeRecord", "Get-LmDocPath", "Get-LmCfgNum", "Get-LmLastJson"] + JSON_FUNCS
        cp = H.run_ps_funcs(self.sb, AGENT_PS, names, body, env=self.env, timeout=180)
        self.assertEqual(cp.returncode, 0, cp.stderr.decode("utf-8", "replace"))
        self.assertEqual(lines(cp)[-1], [0])
        from lm27.store import read_store_since
        recs, _c, _g = read_store_since(self.paths, self.pc, "pc_session", "pc.sampler", None)
        self.assertEqual(len(recs), 3)
        rc = make_record_context(None, "pc.sampler", self.pc, agent_dir=self.paths.agent_dir())
        ticks = [("excel.exe", "견적_v2.xlsx - Excel", "active", 5), ("acad.exe", "C:\\work\\과제A\\도면.dwg - AutoCAD", "active", 1),
                 ("", "", "locked", 70)]
        di = S.DocIndex(str(self.sb.dir / "no_recent"))
        for i, (exe, title, state, idle) in enumerate(ticks):
            t = S.RawTick(ts=datetime(2026, 10, 5, 1, i, tzinfo=UTC), off_min=540, fg_exe=exe, fg_title=title,
                          session_state=state, idle_sec=idle)
            raw = S.tick_record(t, 60, doc_path=di.path_for(title, S.app_of(exe)[2]))
            row = sanitize_record("pc_session", raw, rc).row.data
            got = next(r for r in recs if r["ts_utc"] == row["ts_utc"])
            for k in ("id", "doc_key", "dir_keys", "app_id", "app_class", "layer", "title_masked", "ts_end", "session_state"):
                self.assertEqual(got.get(k), json.loads(json.dumps(row.get(k))), (exe, k))
        self.assertTrue(next(r for r in recs if r.get("app_id") == "autocad").get("dir_keys"))     # C15 — 제목 경로

    def test_agent_loop_with_fake_tick(self):
        """ps 감독 루프 전체(Invoke-LmAgent)를 실제 PS 5.1 에서 — 표본·프로세스 조회·자식 기동만 가짜(실 창·실 수집 0)."""
        orig_aj = self.paths.agent_json().read_bytes()
        orig_cfg = self.paths.agent_config().read_bytes()
        self.addCleanup(self.paths.agent_json().write_bytes, orig_aj)
        self.addCleanup(self.paths.agent_config().write_bytes, orig_cfg)
        I.write_agent_config(self.paths, self.sb.cfg(**{"agent.sampleIntervalSec": 5}),
                             H.read_json(self.paths.agent_config()).get("config_hash"))
        run = self.paths.agent_run()
        run.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: self.paths.stop_flag().unlink(missing_ok=True))
        b, agent = self.bin, self.paths.agent_dir()
        body = (f"$script:PsDir = '{b}\\ps'; $script:Bin = '{b}'; $script:AgentDir = '{agent}'; $script:RunDir = '{run}'\n"
                f"$script:Py = '{b}\\py311\\python.exe'; $script:Pipe = '{b}\\lm27_pipe.py'; $script:Main = '{b}\\agent_main.py'\n"
                f"$script:PsExe = '{H.powershell()}'; $InstallId = '{H.IID}'\n"
                "$TitleMax = 1024; $HarvestStreams = 'pc_session/pc.events,pc_file/pc.files,pc_file/pc.mru,pc_file/pc.recent'\n"
                "$HarvestMaxSec = 1800; $MaintEverySec = 86400; $TestGapMs = 1000\n"
                "$script:Cat = @{}; $script:DocMap = @{}; $script:DocAt = [datetime]::UtcNow\n"
                "$script:KeepClasses = @('office', 'cad', 'sim', 'eda', 'ide', 'pdf', 'viewer')\n"
                "$script:N = 0; $script:Children = New-Object 'Collections.Generic.List[string]'\n"
                "function Initialize-LmNative { return $null }\n"
                "function Get-Process { return @() }\n"
                "function Start-LmChild([string]$streams, [bool]$poll, [bool]$requested) { $script:Children.Add($streams + '|' + $poll); return $null }\n"
                "function Get-LmTick([datetime]$nowUtc) {\n"
                "  $script:N++\n"
                "  if ($script:N -ge 3) { [IO.File]::WriteAllText((Join-Path $script:RunDir 'stop.flag'), '') }\n"
                "  $t = $nowUtc.AddTicks(-($nowUtc.Ticks % [TimeSpan]::TicksPerSecond))\n"
                "  return [pscustomobject]@{ ts = $t; off_min = 540; fg_exe = 'excel.exe'; fg_title = (@('견적', '회의록', '도면', '기타')[[math]::Min(3, $script:N - 1)] + '.xlsx - Excel');"
                " session_state = 'active'; remote = $false; idle_sec = 3; ok_fg = $true; ok_idle = $true; ok_session = $true }\n"
                "}\n"
                "$rc = Invoke-LmAgent\n"
                "[Console]::Out.WriteLine((ConvertTo-LmJson ([ordered]@{ rc = $rc; children = $script:Children.ToArray() })))\n")
        names = ["Get-LmIdleSec", "Get-LmSession", "New-LmTickRecord", "Get-LmInterval", "Start-LmProc", "Stop-LmTree",
                 "Invoke-LmPy", "Get-LmLastJson", "Update-LmCatalog", "Send-LmPipe", "Get-LmDocPath", "Write-LmLog",
                 "Save-LmHeartbeat", "Read-LmJsonFile", "Get-LmCfgNum", "Invoke-LmAgent", "New-LmComputeRecord",
                 "Invoke-LmFlush"] + JSON_FUNCS
        cp = H.run_ps_funcs(self.sb, AGENT_PS, names, body, env=self.env, timeout=300)
        self.assertEqual(cp.returncode, 0, cp.stderr.decode("utf-8", "replace"))
        out = lines(cp)[-1]
        self.assertEqual(out["rc"], 0, cp.stderr.decode("utf-8", "replace"))
        self.assertEqual(sorted(out["children"]), sorted([
            "pc_session/pc.events,pc_file/pc.files,pc_file/pc.mru,pc_file/pc.recent|False", "teams/teams.uia|False",
            "pc_file/pc.files|True"]))
        hb = H.read_json(self.paths.heartbeat())
        self.assertEqual((hb["impl"], hb["state"], hb["buffered"], hb["install_id"], hb["interval_s"]), ("ps", "stopped", 0, H.IID, 5))
        from lm27.store import read_store_since
        recs, _c, _g = read_store_since(self.paths, hb["pc_id"], "pc_session", "pc.sampler", None)
        self.assertEqual(len(recs), 3)
        self.assertEqual({r["app_id"] for r in recs}, {"excel"})
        self.assertEqual(len({r["doc_key"] for r in recs}), 3)
        log = "\n".join(p.read_text(encoding="utf-8") for p in self.paths.agent_logs().glob("agent_*.log"))
        self.assertIn("start impl=ps", log)
        self.assertNotIn("견적", log + json.dumps(hb, ensure_ascii=False))
        self.assertNotIn("회의록", log)

    def test_bin_cli_helpers(self):
        """사본 agent_main.py 의 보조 명령(ps 구현이 부른다) — 사본 파이썬 -I 로, 프로그램 폴더 없이. P-T34: 사본 rules.py 를
        바꾸면 --check-rules 가 1."""
        py, main = str(self.bin / "py311" / "python.exe"), str(self.bin / "agent_main.py")

        def run(*args, stdin=b""):
            return subprocess.run([py, "-X", "utf8", "-I", "-B", main, "--install-id", H.IID, *args], input=stdin,
                                  capture_output=True, timeout=120, env=self.env, cwd=str(self.sb.dir),
                                  creationflags=H.CREATE_NO_WINDOW)
        self.assertEqual(run("--check-rules").returncode, 0)
        cp = run("--in-line", "pc.events")
        self.assertEqual(cp.returncode, 0, cp.stderr.decode("utf-8", "replace"))
        line = json.loads(cp.stdout.decode("utf-8"))
        self.assertEqual(set(line["_in"]["cfg"]), {"collect.lookbackDays"})
        cp = run("--classify", stdin=b"EXCEL.EXE\nfluent.exe\n")
        got = [json.loads(x) for x in cp.stdout.decode("utf-8").splitlines()]
        self.assertEqual([(g["exe"], g["app_id"], g["solver"]) for g in got],
                         [("excel.exe", "excel", False), ("fluent.exe", S.catalog.app_id_for("fluent"), True)])
        self.assertEqual(run("--maintain").returncode, 0)
        self.assertEqual(subprocess.run([py, "-X", "utf8", "-I", "-B", main, "--install-id", "x"], capture_output=True,
                                        timeout=60, creationflags=H.CREATE_NO_WINDOW).returncode, 5)
        rp = self.bin / "lm27" / "privacy" / "rules.py"
        good = rp.read_bytes()
        self.addCleanup(rp.write_bytes, good)
        rp.write_bytes(good + b"\nRX_EXTRA_FOR_TEST = __import__('re').compile('x')\n")
        self.assertEqual(run("--check-rules").returncode, 1)                 # 조용한 축약 정제 금지 — 사본이 다르면 멈춘다
        sc = json.loads(run("--start-check").stdout.decode("utf-8"))
        self.assertFalse(sc["rules_ok"])

    def test_harvest_ps_clm_status(self):
        """CLM 모드 수집기(상태 줄이 stdout 제어 줄) — 실제 사본 파이프가 요약의 collector_status 로 넘기고 harvest.ps1 이
        py 구현처럼 읽어 harvest_done.json 에 싣는다(C1). 다른 pc_id 로 돌려 다른 시험의 원장·커서와 섞이지 않는다."""
        pc = "pc_1111222233334444"
        self.sb.write_json(self.paths.agent_json(), dict(self.aj, pc_id=pc))
        ps = self.bin / "ps" / "Get-EventActivity.ps1"
        self.addCleanup(ps.write_bytes, ps.read_bytes())
        H.write_ps(ps, H.FAKE_EVENTS_PS_CLM)
        cp = subprocess.run([H.powershell(), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
                             str(self.bin / "ps" / "harvest.ps1"), "-InstallId", H.IID, "-Streams", "pc_session/pc.events"],
                            capture_output=True, timeout=300, env=self.env, cwd=str(self.sb.dir),
                            creationflags=H.CREATE_NO_WINDOW)
        self.assertEqual(cp.returncode, 0, cp.stderr.decode("utf-8", "replace"))
        done = H.read_json(self.paths.harvest_done())
        ev = done["streams"]["pc.events"]
        self.assertEqual((done["pc_id"], done["requested"], ev["rc"], ev["pipe"], ev["stored"], ev["reasons"]),
                         (pc, False, 0, 0, 2, []))
        self.assertEqual((ev["status"]["src"], ev["status"]["n"], ev["status"]["in_ok"]), ("pc.events", 2, True))

    def test_harvest_ps_full_run(self):
        H.write_ps(self.bin / "ps" / "Get-EventActivity.ps1", H.FAKE_EVENTS_PS)
        cp = subprocess.run([H.powershell(), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
                             str(self.bin / "ps" / "harvest.ps1"), "-InstallId", H.IID, "-Streams", "pc_session/pc.events",
                             "-Requested"], capture_output=True, timeout=300, env=self.env, cwd=str(self.sb.dir),
                            creationflags=H.CREATE_NO_WINDOW)
        self.assertEqual(cp.returncode, 0, cp.stderr.decode("utf-8", "replace"))
        done = H.read_json(self.paths.harvest_done())
        self.assertEqual((done["schema"], done["install_id"], done["pc_id"], done["requested"], done["rc"]),
                         ("lm27.harvest_done/1", H.IID, self.pc, True, 0))
        ev = done["streams"]["pc.events"]
        self.assertEqual((ev["rc"], ev["pipe"], ev["stored"], ev["cursor_saved"], ev["timed_out"]), (0, 0, 2, True, False))
        self.assertEqual((ev["status"]["n"], ev["status"]["in_ok"]), (2, True))     # stderr 상태 줄(_in 을 받았다)
        from lm27.store import file_lock, load_raw_cursor, read_store_since
        recs, _c, _g = read_store_since(self.paths, self.pc, "pc_session", "pc.events", None)
        self.assertEqual(sorted(r["event_class"] for r in recs), ["boot", "wake"])
        self.assertEqual(load_raw_cursor(self.paths, self.pc)["pc.events"], {"last_ts_utc": "2026-09-01T09:00:00Z"})
        with file_lock(self.paths.harvest_lock(), 1):                       # 잠금은 풀려 있다
            pass
        logs = list(self.paths.agent_logs().glob("agent_*.log"))
        self.assertTrue(logs)
        self.assertNotIn("C:\\", logs[0].read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
