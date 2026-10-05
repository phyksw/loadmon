# -*- coding: utf-8 -*-
r"""WP-17 능력 탐침 정적 관문 — collect\Invoke-CapabilityProbe.ps1 (계약 §2.17 · §6.7 · §7.3 · §9.2 · §11.1 · §11.3).

- 인코딩: UTF-8 BOM + CRLF, 제어문자 0(L-01 · L-02).
- PowerShell 5.1 구문 해석 오류 0.
- hook_check 파일 규칙(L-01·02·09·13·14·15·16·21·26·28·29) 무지적 — %TEMP% 복제 트리에서(계약 §11.3).
- 사유 코드 ⊂ 계약 §6.1(L-13), 주입 변수 ⊂ 계약 §11.3 + LM_PROBE_FAKE(CR), 경로 조립 인자(-Root·-OutDir·-CursorFile) 0,
  New-Object Outlook.Application 0(C §4.3 — 떠 있는 Outlook 에 붙기만), Stop-Job 0(CM §5.2), Write-Host 0(stdout 오염),
  'exit 0' 고정 0, 설정 기본값 = 설정 레지스트리 기본값(죽은 기본값·어긋난 기본값 방지).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import unittest
from pathlib import Path

from lm27.collect import rcmap
from tests.fixtures.tree import CloneTestCase

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "collect" / "Invoke-CapabilityProbe.ps1"
REGISTRY = ROOT / "config" / "settings_registry.json"
PS = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
CREATE_NO_WINDOW = 0x08000000
INJECT_11_3 = {"LM_OUTLOOK_SELFTEST", "LM_INDEX_FAKE", "LM_OWA_FAKE", "LM_TEAMSWEB_FAKE", "LM_COPILOT_STUB", "LM_NO_BROWSER"}
PROBE_FAKE = "LM_PROBE_FAKE"          # 이 WP 가 계약 §11.3 에 등재를 요청한 주입점(CR)
FILE_RULES = "L-01,L-02,L-09,L-13,L-14,L-15,L-16,L-21,L-26,L-28,L-29"


def _text() -> str:
    return SCRIPT.read_bytes().decode("utf-8-sig")


def _code_lines() -> list[str]:
    """주석(줄 주석·블록 주석)을 뺀 코드 줄 — here-string(C# 정의)은 그대로 둔다."""
    out, block = [], False
    for ln in _text().splitlines():
        s = ln.strip()
        if block:
            if "#>" in s:
                block = False
            continue
        if s.startswith("<#"):
            block = "#>" not in s[2:]
            continue
        if s.startswith("#"):
            continue
        out.append(ln)
    return out


class Encoding(unittest.TestCase):
    def test_bom_crlf_no_control(self):
        raw = SCRIPT.read_bytes()
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"), "UTF-8 BOM 없음 — PowerShell 5.1 이 CP949 로 오독")
        body = raw[3:]
        self.assertEqual(body.count(b"\n"), body.count(b"\r\n"), "LF 단독 줄끝")
        self.assertEqual(body.count(b"\r"), body.count(b"\r\n"), "CR 단독 줄끝")
        bad = re.findall(rb"[\x00-\x08\x0b\x0c\x0e-\x1f]", body)
        self.assertEqual(bad, [], "제어문자")
        body.decode("utf-8")


@unittest.skipUnless(os.name == "nt" and PS.is_file(), "Windows PowerShell 5.1 없음")
class Parse(unittest.TestCase):
    def test_parser_errors_zero(self):
        cmd = ("$e=$null; $t=$null; [void][System.Management.Automation.Language.Parser]::ParseFile($env:LM27T_PROBE_PS, "
               "[ref]$t, [ref]$e); foreach($x in $e){ '{0}: {1}' -f $x.Extent.StartLineNumber, $x.Message }; exit $e.Count")
        env = dict(os.environ, LM27T_PROBE_PS=str(SCRIPT))
        cp = subprocess.run([str(PS), "-NoProfile", "-NonInteractive", "-Command", cmd], capture_output=True, env=env,
                            timeout=120, creationflags=CREATE_NO_WINDOW, check=False)
        self.assertEqual(cp.returncode, 0, cp.stdout.decode("utf-8", "replace")[-2000:])


class HookCheck(CloneTestCase):
    clone_extra = ("docs",)

    def test_file_rules_clean(self):
        target = self.clone.path("collect", "Invoke-CapabilityProbe.ps1")
        self.assertTrue(target.is_file())
        cp = self.clone.run_py([self.clone.path("tools", "hook_check.py"), "--rules", FILE_RULES, target], timeout=300)
        out = (cp.stdout + cp.stderr).decode("utf-8", "replace")
        self.assertEqual(cp.returncode, 0, out[-3000:])


class Content(unittest.TestCase):
    def test_reason_codes_in_contract_table(self):
        codes = set(re.findall(r"\bR-[A-Z]{2,}(?:-[A-Z0-9]+)*\b", _text()))
        self.assertTrue(codes, "사유 코드를 하나도 찾지 못함")
        self.assertEqual(sorted(codes - set(rcmap.REASONS)), [], "계약 §6.1 밖 사유 코드(L-13)")
        # 계약 §6.7 · 계획 WP-17 완료 기준의 사유 코드를 모두 낼 수 있어야 한다
        need = {"R-NEWOL", "R-NOPROF", "R-WIZARD", "R-DIALOG", "R-OMG", "R-CLM", "R-ELEV", "R-ONLINE", "R-NOIDX",
                "R-IDXPOLICY", "R-IDXPAUSED", "R-EDGEPOL", "R-SUBFOLDER", "R-STALE", "R-OFFICE", "R-TZ"}
        self.assertEqual(sorted(need - codes), [])

    def test_injection_names_registered(self):
        names = set(re.findall(r"\bLM_[A-Z_]+\b", _text()))
        self.assertIn(PROBE_FAKE, names)
        self.assertEqual(sorted(names - INJECT_11_3 - {PROBE_FAKE}), [], "계약 §11.3 밖 주입 변수")
        self.assertIn("-TestNow", _text())

    def test_no_path_assembly_params(self):
        m = re.search(r"(?is)\bparam\s*\((.*?)\)\s*\n\s*\n", _text())
        self.assertIsNotNone(m, "param 블록을 찾지 못함")
        params = set(re.findall(r"\$(\w+)", m.group(1)))
        self.assertEqual(params & {"Root", "PcId", "OutDir", "CursorFile"}, set(), "경로 조립 인자 금지(계약 §7.3)")
        self.assertIn("Pc", params)

    def test_forbidden_constructs(self):
        code = "\n".join(_code_lines())
        self.assertIsNone(re.search(r"(?i)New-Object\s+-ComObject\s+['\"]?Outlook\.Application", code),
                          "탐침은 New-Object 로 Outlook 을 띄우지 않는다(C §4.3)")
        self.assertIsNone(re.search(r"(?i)\bStop-Job\b", code), "Stop-Job 금지(CM §5.2)")
        self.assertIsNone(re.search(r"(?i)\bWrite-Host\b", code), "Write-Host 는 stdout 을 오염시킨다")
        self.assertIsNone(re.search(r"(?im)^\s*exit\s+0\s*$", code), "'exit 0' 고정 금지(계약 §8.1)")
        self.assertIn("GetActiveObject('Outlook.Application')", code)

    def test_cfg_defaults_match_registry(self):
        m = re.search(r"(?s)\$CFG_DEFAULT\s*=\s*\[ordered\]@\{(.*?)\n\}", _text())
        self.assertIsNotNone(m)
        pairs = dict(re.findall(r"'([\w.]+)'\s*=\s*('[^']*'|[-\d.]+)", m.group(1)))
        self.assertTrue(pairs)
        reg = json.loads(REGISTRY.read_bytes().decode("utf-8-sig"))["keys"]
        for k, v in pairs.items():
            with self.subTest(key=k):
                self.assertIn(k, reg, "설정 레지스트리에 없는 키(L-12)")
                val = v.strip("'") if v.startswith("'") else json.loads(v)
                self.assertEqual(val, reg[k]["default"], "탐침 기본값이 레지스트리 기본값과 다름")


if __name__ == "__main__":
    unittest.main()
