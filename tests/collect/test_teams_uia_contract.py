# -*- coding: utf-8 -*-
"""WP-16 teams.uia(Get-TeamsWindow.ps1) — 입출력 계약(계약 §3.5 · §7.3 · §8.1 · §9.2 · L-09) 시험.

모든 실행은 %TEMP% 복제 트리에서 -RawFile 주입(계약 §11.3)으로만 한다 — 실제 Teams 창·UIA 는 읽지 않는다.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import unittest
from collections import Counter
from datetime import UTC, date
from pathlib import Path

from lm27.collect import rcmap
from tests.fixtures import synth
from tests.fixtures.canary import canaries
from tests.fixtures.synth import inject
from tests.fixtures.synth.month import at_local
from tests.fixtures.tree import CREATE_NO_WINDOW, TREE_ROOT, CloneTestCase
from tests.fixtures.wp16 import uia

SCRIPT = TREE_ROOT.joinpath(*uia.SCRIPT_REL)
UTC_RX = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
OFF_RX = re.compile(r"^[+-](?:0\d|1[0-4]):[0-5]\d$")
CHAT_TYPES = {"1:1", "group", "channel", "meeting", "self"}
FLAG_KEYS = {"n_part_est", "author_inherited"}           # 계약 §3.3 teams 허용 키 중 수집기가 내는 것


def _need_ps(case: unittest.TestCase) -> None:
    if not uia.powershell_exe():
        case.skipTest("powershell 없음")


# ── 정적 검사(스크립트 텍스트) ─────────────────────────────────────────────
class TestScriptStatic(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.raw = SCRIPT.read_bytes()
        cls.text = cls.raw.decode("utf-8-sig")
        # 주석(<# … #> · # 줄)을 뺀 코드 줄
        code, block = [], False
        for ln in cls.text.splitlines():
            t = ln.strip()
            if block:
                block = "#>" not in t
                continue
            if t.startswith("<#"):
                block = "#>" not in t[2:]
                continue
            if t.startswith("#"):
                continue
            code.append(ln)
        cls.code = "\n".join(code)

    def test_encoding_bom_crlf_no_control_chars(self):
        self.assertTrue(self.raw.startswith(b"\xef\xbb\xbf"), "ps1 은 UTF-8 BOM(계약 §9.2)")
        body = self.raw[3:]
        self.assertEqual(body.count(b"\n"), body.count(b"\r\n"), "LF 단독 줄끝 없음 — CRLF 만")
        self.assertEqual(body.count(b"\r"), body.count(b"\r\n"), "CR 단독 없음")
        bad = [c for c in body.decode("utf-8") if ord(c) < 0x20 and c not in "\r\n"]
        self.assertEqual(bad, [], "제어문자 0(L-01)")

    def test_hook_check_file_rules_pass(self):
        hc = TREE_ROOT / "tools" / "hook_check.py"
        if not hc.is_file():
            self.skipTest("hook_check.py 없음")
        p = subprocess.run([sys.executable, "-X", "utf8", "-B", str(hc), "--rules", "L-01,L-02,L-05,L-09",
                            str(SCRIPT)], capture_output=True, timeout=120, cwd=str(Path(os.environ.get("TEMP", "."))),
                           creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0, check=False)
        self.assertEqual(p.returncode, 0, p.stdout.decode("utf-8", "replace") + p.stderr.decode("utf-8", "replace"))

    def test_params_follow_contract_7_3(self):
        m = re.search(r"(?is)\bparam\s*\((.*?)\n\)", self.text)
        self.assertIsNotNone(m)
        names = set(re.findall(r"\$([A-Za-z]+)\s*(?:=|,|$)", m.group(1), re.M))
        self.assertEqual(names, {"Pc", "Since", "Until", "KeepChatList", "RawFile", "TestNow"})
        for bad in ("Root", "PcId", "CursorFile", "OutDir", "MaxElements"):   # 경로 조립·설정 값은 인자로 받지 않는다
            self.assertNotIn(bad, names)

    def test_reason_codes_registered(self):
        codes = set(re.findall(r"(?<![A-Za-z0-9_-])R-[A-Z]{2,}(?:-[A-Z0-9]+)*(?![A-Za-z0-9_])", self.text))
        self.assertTrue(codes)
        self.assertEqual(sorted(codes - set(rcmap.REASONS)), [], "계약 §6.1 에 없는 사유 코드(L-13)")
        for need in ("R-UIAEMPTY", "R-UIAELEV", "R-CAP", "R-BUDGET", "R-NOADDR", "R-TRANSPORT"):
            self.assertIn(need, codes)

    def test_structure_rules(self):
        code = self.code
        self.assertNotIn("MainWindowHandle", code, "주 창 하나만 읽지 않는다 — 모든 최상위 창 열거(CT §7.2)")
        self.assertIn("EnumWindows", code)
        self.assertIn("IsIconic", code)
        self.assertIn("IsWindowVisible", code)
        self.assertNotRegex(code, r"(?i)\bWrite-(?:Host|Output|Information)\b", "stdout 은 NDJSON 만 — 안내 출력 금지")
        self.assertNotRegex(code, r"(?im)^\s*exit\s+0\s*$", "exit 0 고정 금지(계약 §8.1)")
        self.assertNotRegex(code, r"(?i)\bConvertTo-Json\b", "결정적 JSON 직렬화(배열 풀림·깊이 제한 회피)")
        retired = ["teams" + "_window.csv", "teams" + "_window_raw.txt", "teams" + "_window_skipped.txt"]
        banned = ["Indexed" + "DB", "Level" + "DB", "wpn" + "database", "graph." + "microsoft.com"]
        for word in retired + banned:
            self.assertNotIn(word.lower(), self.text.lower())
        self.assertNotRegex(code, r"(?i)\$env:USERNAME|LogonUI|UserPrincipal",
                            "본인 이름은 호출자(_in.self_names)가 넘긴 값만(X-306)")

    def test_config_keys_registered(self):
        reg_path = TREE_ROOT / "config" / "settings_registry.json"
        if not reg_path.is_file():
            self.skipTest("레지스트리 없음")
        doc = json.loads(reg_path.read_text(encoding="utf-8"))
        reg = doc.get("keys", doc)
        keys = set(re.findall(r"'((?:teams|time|collect|privacy)\.[A-Za-z0-9.]+)'", self.code)) - {"teams.uia"}
        self.assertEqual(keys, {"teams.timeRegex", "teams.uia.visibleOnly", "teams.uia.maxElements",
                                "teams.uia.windowWatchdogSec", "teams.uia.budgetSec"})
        for k in keys:
            self.assertIn(k, reg)

    def test_uia_helper_compiles(self):
        """실모드 도우미(C# — 창 열거·권한 상승·UIA 캐시 판독)가 컴파일되는지만 본다. 창을 열거하거나 읽지 않는다."""
        _need_ps(self)
        m = re.search(r"(?s)\$script:UiaSource = @'\r?\n(.*?)\r?\n'@", self.text)
        self.assertIsNotNone(m)
        src = m.group(1)
        self.assertNotIn("'@", src)
        probe = (
            "$ErrorActionPreference = 'Stop'\r\n"
            "$src = @'\r\n" + src.replace("\n", "\r\n").replace("\r\r\n", "\r\n") + "\r\n'@\r\n"
            "Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes, WindowsBase\r\n"
            "$refs = @([System.Windows.Automation.AutomationElement].Assembly.Location,"
            " [System.Windows.Automation.ControlType].Assembly.Location, [System.Windows.Rect].Assembly.Location)\r\n"
            "Add-Type -TypeDefinition $src -ReferencedAssemblies $refs -Language CSharp\r\n"
            "$t = @('Lm27Teams.Native', 'Lm27Teams.Reader', 'Lm27Teams.UiaRead') | ForEach-Object { [bool]($_ -as [type]) }\r\n"
            "[Console]::Out.Write(($t -join ','))\r\n")
        tmp = Path(os.environ.get("TEMP") or os.environ.get("TMP") or ".")
        d = tmp / f"lm27t_wp16_cs_{os.getpid()}"
        d.mkdir(parents=True, exist_ok=True)
        try:
            f = d / "compile_probe.ps1"
            f.write_bytes(b"\xef\xbb\xbf" + probe.encode("utf-8"))
            p = subprocess.run([uia.powershell_exe(), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(f)],
                               capture_output=True, timeout=180, cwd=str(d),
                               creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0, check=False)
        finally:
            for x in d.glob("*"):
                x.unlink()
            d.rmdir()
        self.assertEqual(p.returncode, 0, p.stderr.decode("utf-8", "replace")[-2000:])
        self.assertEqual(p.stdout.decode("utf-8", "replace").strip(), "True,True,True")


# ── 실행: 출력 계약 ─────────────────────────────────────────────────────────
class TestOutputContract(CloneTestCase):
    """WP-05 합성 원문 재생 파일(일반 텍스트) — 날짜 있는 줄 + 끝의 날짜 없는 줄 2개."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        if not uia.powershell_exe():
            raise unittest.SkipTest("powershell 없음")
        cls.plan = synth.plan_month(2026, 9)
        cls.raw = inject.write_teams_rawfile(cls.clone.temp / "teams_raw.txt", cls.plan)
        cls.res = uia.run(cls.clone, cls.raw)
        cls.evs = sorted((ev for ev in cls.plan.chats if ev.pc == "PC1"), key=lambda e: (e.utc, e.mid))

    def test_rc_and_status(self):
        r = self.res
        self.assertEqual(r.rc, 0, r.stderr.decode("utf-8", "replace"))
        self.assertIsNotNone(r.status)
        self.assertEqual(r.status["src"], "teams.uia")
        self.assertEqual(r.status["rc"], r.rc)
        self.assertEqual(sorted(set(r.reasons) - set(rcmap.REASONS)), [])
        err = [x for x in r.stderr.decode("utf-8").splitlines() if x.strip()]
        self.assertEqual(len(err), 1, "stderr = 상태 한 줄(숫자·사유 코드만)")
        self.assertTrue(r.stderr.decode("utf-8").isascii(), "상태 줄에 원문 없음")

    def test_status_c1_required_fields(self):
        """계약 v1.2 §0.7 C1 — 상태 줄 한 모양(schema·src·rc·reasons·partial·cap_hit·budget_hit·n·counts, W1 통합 창 정렬)."""
        st = self.res.status
        self.assertLessEqual({"schema", "src", "rc", "reasons", "partial", "cap_hit", "budget_hit", "n", "counts"}, set(st))
        self.assertEqual(st["schema"], "lm27.collector_status/1")
        self.assertEqual(st["n"], len(self.res.records))
        self.assertEqual((st["partial"], st["cap_hit"], st["budget_hit"]), (False, False, False))
        self.assertIsInstance(st["counts"], dict)

    def test_stdout_is_ndjson_with_cursor_last(self):
        r = self.res
        self.assertGreater(len(r.records), 0)
        self.assertIn("_cursor", r.lines[-1])
        self.assertEqual([x for x in r.lines[:-1] if any(k.startswith("_") for k in x)], [],
                         "제어 줄은 마지막 _cursor 하나(팀즈 UIA 는 _meta 없음)")
        self.assertFalse(r.stdout.startswith(b"\xef\xbb\xbf"), "stdout UTF-8 BOM 없음")
        self.assertNotIn(b"\r\n", r.stdout)

    def test_record_shape_is_p_10_2_raw(self):
        for rec in self.res.records:
            self.assertEqual(set(rec), uia.RAW_FIELDS)
            self.assertTrue(set(rec) <= synth.raw_teams.FIELDS)
            self.assertNotIn("act", rec)                              # 화행은 정규화 단계(X-090)
            self.assertIsNone(rec["message_id"])
            self.assertIsNone(rec["reply_to_id"])
            self.assertIsNone(rec["author_addr"])
            self.assertIn(rec["chat_type"], CHAT_TYPES)
            self.assertIsInstance(rec["n_participants"], int)
            self.assertTrue(rec["chat_id"].startswith("uia:"))
            self.assertRegex(rec["ts_utc"], UTC_RX)
            self.assertRegex(rec["observed_at"], UTC_RX)
            self.assertRegex(rec["ts_local_offset"], OFF_RX)
            self.assertIn(rec["ts_precision"], ("minute", "unknown"))
            self.assertIn(rec["is_me"], (True, False, None))
            self.assertIsInstance(rec["mentions_me"], bool)
            self.assertIsInstance(rec["file_names"], list)
            self.assertIsInstance(rec["participants"], list)
            self.assertTrue(set(rec["flags"]) <= FLAG_KEYS)
            self.assertTrue(all(v is True for v in rec["flags"].values()))
            self.assertIn(rec["confidence"], (0.8, 0.3))
            self.assertEqual(rec["observed_at"], "2026-10-01T00:00:00Z")
            self.assertEqual(rec["ts_local_offset"], "+09:00")

    def test_dated_lines_match_plan(self):
        dated = [x for x in self.res.records if x["ts_precision"] == "minute"]
        self.assertEqual(len(dated), len(self.evs))
        want = Counter((ev.utc.astimezone(UTC).replace(second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        self.plan.persona.person(ev.author).name) for ev in self.evs)
        got = Counter((x["ts_utc"], x["author_name"]) for x in dated)
        self.assertEqual(got, want)
        for x in dated:
            self.assertEqual(x["is_me"], x["author_name"] == "홍길동")
            self.assertEqual(x["confidence"], 0.8)

    def test_undated_lines_isolated_not_estimated(self):
        """CT-4: 날짜 표기 없는 줄은 unknown 으로 격리하고 버리지 않는다. ts_utc 는 수집일 00:00 자리값(그 메시지 시각 아님)."""
        und = [x for x in self.res.records if x["ts_precision"] == "unknown"]
        self.assertEqual(len(und), 2)
        self.assertEqual(self.res.counts["n_unknown"], 2)
        P = self.plan.persona
        for x, ev in zip(und, self.evs[-2:], strict=True):
            self.assertEqual(x["ts_utc"], "2026-09-30T15:00:00Z")          # 2026-10-01 00:00 +09:00
            self.assertEqual(x["confidence"], 0.3)
            self.assertEqual(x["author_name"], P.person(ev.author).name)
            self.assertEqual(x["body_text"], P.render(ev.body)[0])
            msg_utc = ev.utc.astimezone(UTC).replace(second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")
            self.assertNotEqual(x["ts_utc"], msg_utc, "수집일·메시지 시각으로 추정하지 않는다")

    def test_cursor_is_max_minute_ts(self):
        dated = [x["ts_utc"] for x in self.res.records if x["ts_precision"] == "minute"]
        self.assertEqual(self.res.cursor, {"last_ts_utc": max(dated)})
        self.assertEqual(self.res.counts["n_new"], len(self.res.records))

    def test_deterministic_rerun(self):
        again = uia.run(self.clone, self.raw)
        self.assertEqual(again.stdout, self.res.stdout)
        self.assertEqual(again.rc, self.res.rc)


class TestCursorAndControl(CloneTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        if not uia.powershell_exe():
            raise unittest.SkipTest("powershell 없음")
        cls.raw = uia.write_lines(cls.clone.temp / "c.txt", [
            "김철수, 2026년 9월 29일 오전 10:05, 과제A 검토 부탁드립니다",
            "홍길동, 2026년 9월 30일 오후 2:10, 과제A 검토본 공유드립니다",
        ])

    def test_cursor_after_all_rows_gives_rc4_and_keeps_cursor(self):
        r = uia.run(self.clone, self.raw, cursor={"last_ts_utc": "2026-09-30T06:00:00Z"})
        self.assertEqual(r.rc, 4)
        self.assertEqual(r.counts["n_new"], 0)
        self.assertEqual(len(r.records), 2, "커서 이전 줄도 넘긴다 — 중복은 id 로 흡수(계약 §8.2)")
        self.assertEqual(r.cursor, {"last_ts_utc": "2026-09-30T06:00:00Z"})

    def test_cursor_before_advances(self):
        r = uia.run(self.clone, self.raw, cursor={"last_ts_utc": "2026-09-29T12:00:00Z"})
        self.assertEqual(r.rc, 0)
        self.assertEqual(r.counts["n_new"], 1)
        self.assertEqual(r.cursor, {"last_ts_utc": "2026-09-30T05:10:00Z"})

    def test_no_control_line_runs_with_defaults_and_noaddr(self):
        r = uia.run(self.clone, self.raw, inp=b"")
        self.assertEqual(r.rc, 0)
        self.assertEqual(r.counts["in_given"], 0)
        self.assertIn("R-NOADDR", r.reasons)
        self.assertEqual([x["is_me"] for x in r.records], [None, None], "이름 집합 없으면 수신 단정 금지")

    def test_bad_control_line_is_ignored(self):
        r = uia.run(self.clone, self.raw, inp=b"{not json\n")
        self.assertEqual(r.rc, 0)
        self.assertEqual(r.counts["in_given"], -1)

    def test_since_until_filter(self):
        r = uia.run(self.clone, self.raw, args=("-Since", "2026-09-30", "-Until", "2026-09-30"))
        self.assertEqual([x["body_text"] for x in r.records], ["과제A 검토본 공유드립니다"])
        self.assertEqual(r.counts["out_of_range"], 1)

    def test_clm_rc3_status_on_stdout(self):
        """W1 통합 창 결함 회귀(CT §15 · C1·C4): 제한 언어 모드면 첫 실행문에서 rc 3 + R-CLM 을 stdout 상태 제어 줄로 —
        이전에는 최상위 New-Object 에서 멈춰 rc 1·출력 0바이트였고 원장이 '0건 관측(zero_ok)'으로 적었다."""
        path = str(self.clone.path(*uia.SCRIPT_REL)).replace("'", "''")
        raw = str(self.raw).replace("'", "''")
        cmd = ("$ExecutionContext.SessionState.LanguageMode='ConstrainedLanguage'; & '" + path + "' -RawFile '" + raw
               + "'; exit $LASTEXITCODE")
        p = subprocess.run([uia.powershell_exe(), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command",
                            cmd], input=b"", capture_output=True, timeout=180, cwd=str(self.clone.temp),
                           env=self.clone.env(), creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0, check=False)
        self.assertEqual(p.returncode, 3, p.stderr.decode("utf-8", "replace")[-300:])
        lines = [x for x in p.stdout.decode("utf-8").splitlines() if x.strip()]
        self.assertEqual(len(lines), 1, lines)
        st = json.loads(lines[0])["_status"]
        self.assertEqual((st["schema"], st["src"], st["rc"], st["reasons"], st["n"]),
                         ("lm27.collector_status/1", "teams.uia", 3, ["R-CLM"], 0))
        self.assertEqual(rcmap.translate_cell(st["rc"], st["reasons"])["status"], "blocked")

    def test_missing_rawfile_is_rc3_and_cursor_unchanged(self):
        r = uia.run(self.clone, self.clone.temp / "없는파일.txt", cursor={"last_ts_utc": "2026-09-01T00:00:00Z"})
        self.assertEqual(r.rc, 3)
        self.assertIn("R-TRANSPORT", r.reasons)
        self.assertEqual(r.records, [])
        self.assertEqual(r.cursor, {"last_ts_utc": "2026-09-01T00:00:00Z"})
        self.assertEqual(r.counts.get("fatal"), "FileNotFoundException")


class TestNoDiskNoLeak(CloneTestCase):
    """원문은 stdout(파이프)으로만 — 디스크·stderr 에 0(P §3.4 · L-09 · 계약 §1.5)."""

    def _tree_state(self) -> dict:
        out = {}
        for p in self.clone.root.rglob("*"):
            rel = p.relative_to(self.clone.root)
            if rel.parts and rel.parts[0] == "_sandbox":
                continue
            if p.is_file():
                out[rel.as_posix()] = p.stat().st_size
        return out

    def test_canaries_only_on_stdout(self):
        if not uia.powershell_exe():
            self.skipTest("powershell 없음")
        cs = [c for c in canaries() if c.group == "pii" and not c.weak and c.slot == "text"][:8]
        self.assertTrue(cs)
        lines = [f"김철수, 2026년 9월 30일 오전 10:{i:02d}, 확인 부탁드립니다 {c.sentence}" for i, c in enumerate(cs)]
        raw = uia.write_lines(self.clone.temp / "canary_raw.txt", lines)
        before = self._tree_state()
        lad_before = sorted(p.relative_to(self.clone.lad).as_posix() for p in self.clone.lad.rglob("*"))
        work = self.clone.temp / "cwd"
        work.mkdir(exist_ok=True)
        r = uia.run(self.clone, raw, cwd=work)
        self.assertEqual(r.rc, 0)
        out = r.stdout.decode("utf-8")
        err = r.stderr.decode("utf-8", "replace")
        bodies = [x["body_text"] for x in r.records]
        self.assertEqual(len(bodies), len(cs))
        for c in cs:
            self.assertTrue(any(c.value in b for b in bodies), f"{c.cid}: 원문은 정제 파이프로 그대로 넘어가야 한다")
            self.assertNotIn(c.value, err, f"{c.cid}: stderr 에 원문")
        self.assertTrue(out.endswith(chr(10)))
        self.assertEqual(self._tree_state(), before, "트리 안에 쓴 파일 없음")
        # PowerShell 5.1 자체의 시작 정보(Microsoft\Windows\PowerShell\StartupProfileData-*)는 이 수집기의 쓰기가 아니다
        lad_after = sorted(p.relative_to(self.clone.lad).as_posix() for p in self.clone.lad.rglob("*")
                           if not p.relative_to(self.clone.lad).as_posix().startswith("Microsoft"))
        lad_before = [x for x in lad_before if not x.startswith("Microsoft")]
        self.assertEqual(lad_after, lad_before, "%LOCALAPPDATA% 에 쓴 파일 없음")
        self.assertEqual(list(work.iterdir()), [], "작업 폴더에 쓴 파일 없음")
        for p in self.clone.sandbox.rglob("*"):
            if p.is_file() and p != raw:
                data = p.read_bytes()
                for c in cs:
                    self.assertNotIn(c.value.encode("utf-8"), data, f"{c.cid}: {p.name} 에 원문")


class TestTimeOffset(CloneTestCase):
    def test_capture_offset_from_now(self):
        if not uia.powershell_exe():
            self.skipTest("powershell 없음")
        raw = uia.write_lines(self.clone.temp / "o.txt", ["김철수, 2026년 9월 30일 오전 10:05, 과제A 회의록 공유드립니다"])
        r = uia.run(self.clone, raw, now="2026-10-01T09:00:00-05:00")
        rec = r.records[0]
        self.assertEqual(rec["ts_local_offset"], "-05:00")
        self.assertEqual(rec["ts_utc"], "2026-09-30T15:05:00Z")       # 로컬 10:05 - (-5h)
        self.assertEqual(rec["observed_at"], "2026-10-01T14:00:00Z")
        utc0 = at_local(date(2026, 9, 30), 10 * 60 + 5, -300)
        self.assertEqual(rec["ts_utc"], utc0.strftime("%Y-%m-%dT%H:%M:%SZ"))


if __name__ == "__main__":
    unittest.main()
