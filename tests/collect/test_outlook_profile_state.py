# -*- coding: utf-8 -*-
"""계약 v1.3 §0.8 V7 — '쓸 수 있는 Outlook 프로필' 판정(Get-OutlookProfileState)을 실제 레지스트리 모양으로 확인.

HKCU 아래 시험 전용 키(LM27T-profstate-<난수>)에 프로필 다섯 개를 만들고, COM 수집기 파일에서 함수 글을 그대로 떼어 그 키를
가리키게 해 부른다. 만들기·판정·지우기를 PowerShell 한 번 안에서 하고 finally 로 지운다(시험이 죽어도 키가 남지 않게).
Outlook·실제 프로필은 읽지 않는다."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AM = "9375CFF0413111d3B88A00104B2A6676"
MAPI = "{ED475414-B0D6-11D2-8C3B-00104B2A6676}"
POP = "{ED475410-B0D6-11D2-8C3B-00104B2A6676}"
MAIL_LIST = "{ED475418-B0D6-11D2-8C3B-00104B2A6676}"
STORE_LIST = "{ED475420-B0D6-11D2-8C3B-00104B2A6676}"

DRIVER = r"""
$ErrorActionPreference = 'Stop'
$base = 'HKCU:\Software\@KEY@'
function Svc([string]$s) { return [Text.Encoding]::Unicode.GetBytes($s + [char]0) }
function Acct($prof, $id, $clsid, $svc) {
    $k = New-Item -Path (Join-Path $base "$prof\@AM@\$id") -Force
    New-ItemProperty -LiteralPath $k.PSPath -Name 'clsid' -Value $clsid -PropertyType String | Out-Null
    if ($svc) { New-ItemProperty -LiteralPath $k.PSPath -Name 'Service Name' -Value (Svc $svc) -PropertyType Binary | Out-Null }
}
function Lists($prof, [byte[]]$mail, [byte[]]$store) {
    $k = New-Item -Path (Join-Path $base "$prof\@AM@") -Force
    New-ItemProperty -LiteralPath $k.PSPath -Name '@ML@' -Value $mail -PropertyType Binary | Out-Null
    New-ItemProperty -LiteralPath $k.PSPath -Name '@SL@' -Value $store -PropertyType Binary | Out-Null
}
try {
    # 1 주소록만(계정 설정 전 — 실측 모양): 목록 비어 있음 + CONTAB → 쓸 수 없음
    Lists 'p1' ([byte[]]@()) ([byte[]]@()); Acct 'p1' '00000001' '@MAPI@' 'CONTAB'
    # 2 Exchange: 메일 목록에 계정 → 쓸 수 있음
    Lists 'p2' ([byte[]]@(2, 0, 0, 0)) ([byte[]]@()); Acct 'p2' '00000001' '@MAPI@' 'CONTAB'; Acct 'p2' '00000002' '@MAPI@' 'MSEMS'
    # 3 계정 관리자 키 없음(판을 모름) → 예전처럼 쓸 수 있다고 본다
    New-Item -Path (Join-Path $base 'p3\0a0d020000000000c000000000000046') -Force | Out-Null
    # 4 POP 계정(MAPI 밖 clsid) — 목록 값이 없어도 → 쓸 수 있음
    Acct 'p4' '00000001' '@POP@' $null
    # 5 빈 계정 관리자 키(값·계정 없음) → 쓸 수 없음
    New-Item -Path (Join-Path $base 'p5\@AM@') -Force | Out-Null
    # 6 LDAP 주소록만 → 쓸 수 없음
    Acct 'p6' '00000001' '@MAPI@' 'EMABLT'
    @FN@
    $all = Get-OutlookProfileState -Roots @($base)
    $none = Get-OutlookProfileState -Roots @((Join-Path $base 'nope'))
    $one = @{}
    foreach ($n in 'p1', 'p2', 'p3', 'p4', 'p5', 'p6') {
        $tmp = 'HKCU:\Software\@KEY@-one'
        try {
            New-Item -Path $tmp -Force | Out-Null
            Copy-Item -LiteralPath (Join-Path $base $n) -Destination $tmp -Recurse
            $one[$n] = (Get-OutlookProfileState -Roots @($tmp)).usable
        } finally { Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue }
    }
    [Console]::Out.WriteLine((ConvertTo-Json -Compress @{ total = $all.total; usable = $all.usable; none = $none; one = $one }))
} finally {
    Remove-Item -LiteralPath $base -Recurse -Force -ErrorAction SilentlyContinue
}
"""


def function_text() -> str:
    t = (ROOT / "collect" / "Get-OutlookCom.ps1").read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    m = re.search(r"\nfunction Get-OutlookProfileState \{\n.*?\n\}\n", t, re.S)
    assert m, "Get-OutlookProfileState 없음"
    return m.group(0)


class ProfileStateCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        key = "LM27T-profstate-" + uuid.uuid4().hex[:12]
        cls.key = key
        script = (DRIVER.replace("@KEY@", key).replace("@AM@", AM).replace("@MAPI@", MAPI).replace("@POP@", POP)
                  .replace("@ML@", MAIL_LIST).replace("@SL@", STORE_LIST).replace("@FN@", function_text()))
        tmp = Path(tempfile.mkdtemp(prefix="lm27t_profstate_"))
        try:
            f = tmp / "drive.ps1"
            f.write_bytes(script.replace("\n", "\r\n").encode("utf-8-sig"))     # BOM — 한글 주석이 든 함수 글
            cp = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(f)],
                                capture_output=True, timeout=120)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        cls.err = cp.stderr.decode("utf-8", "replace")
        out = cp.stdout.decode("utf-8", "replace").strip().splitlines()
        cls.res = json.loads(out[-1]) if out and out[-1].startswith("{") else None

    def test_counts(self):
        self.assertIsNotNone(self.res, self.err)
        self.assertEqual(self.res["total"], 6)
        self.assertEqual(self.res["usable"], 3)
        self.assertEqual(self.res["none"], {"total": 0, "usable": 0})

    def test_each_profile(self):
        self.assertIsNotNone(self.res, self.err)
        self.assertEqual(self.res["one"], {"p1": 0, "p2": 1, "p3": 1, "p4": 1, "p5": 0, "p6": 0})

    def test_no_residue(self):
        cp = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                             f"[bool](Test-Path 'HKCU:\\Software\\{self.key}') -or [bool](Test-Path 'HKCU:\\Software\\{self.key}-one')"],
                            capture_output=True, timeout=60)
        self.assertEqual(cp.stdout.decode("utf-8", "replace").strip(), "False")


if __name__ == "__main__":
    unittest.main()
