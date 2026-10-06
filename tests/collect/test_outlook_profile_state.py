# -*- coding: utf-8 -*-
"""계약 v1.3 §0.8 V7 — '쓸 수 있는 Outlook 프로필' 판정(Get-OutlookProfileState)을 계정 관리자 값 모양으로 확인.

계정 관리자 레지스트리 모양은 문서화돼 있지 않다(계정 관리 API 는 CLSID 상수만 정의 —
https://learn.microsoft.com/en-us/office/client-developer/outlook/auxiliary/constants-account-management-api). 그래서 판정은
'주소록만 든' 긍정 증거가 있을 때만 쓸 수 없다고 센다(M365 조사 H7): 실제 Exchange 계정(OlkMAPIAccount {ED475414} ·
'Service Name' 없음 · 목록 값 모양 다름)을 쓸 수 없음으로 오판하면 탐침 R-NOPROF → 계획기가 COM 을 통째로 건너뛰었다.
CLSID 는 문서 값(POP3 {ED475411} · IMAP4 {ED475412} · MAPI {ED475414} · Hotmail/EAS {4DB5CBF0-3B77-…} · LDAP
{4DB5CBF2-3B77-…} · 범주 OlkMail {ED475418} · OlkAddressBook {ED475419} · OlkStore {ED475420}).

레지스트리에 쓰지 않는다: 함수의 시험 주입점 ``-Shapes``(레지스트리에서 읽은 것과 같은 모양 — 값 원본 byte[]·계정 하위 키의
clsid·Service Name)로 판정만 부른다. COM 수집기·탐침 두 파일의 함수 글을 그대로 떼어 같은 결과인지 본다. 레지스트리 읽기
쪽은 없는 키(빈 결과)로만 확인한다 — 실제 모양은 회사 PC 첫 실측 항목. Outlook·실제 프로필은 읽지 않는다."""
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
MAPI = "{ED475414-B0D6-11D2-8C3B-00104B2A6676}"
POP = "{ED475411-B0D6-11D2-8C3B-00104B2A6676}"
IMAP = "{ED475412-B0D6-11D2-8C3B-00104B2A6676}"
EAS = "{4DB5CBF0-3B77-4852-BC8E-BB81908861F3}"
LDAP = "{4DB5CBF2-3B77-4852-BC8E-BB81908861F3}"
MAIL_LIST = "{ED475418-B0D6-11D2-8C3B-00104B2A6676}"
AB_LIST = "{ED475419-B0D6-11D2-8C3B-00104B2A6676}"
STORE_LIST = "{ED475420-B0D6-11D2-8C3B-00104B2A6676}"
SCRIPTS = ("Get-OutlookCom.ps1", "Invoke-CapabilityProbe.ps1")

# 프로필 이름 → (기대 usable, 설명)
CASES = {
    "p1": (0, "주소록만(계정 설정 전 — 개발 PC 실측 모양): 메일·저장소 목록 비어 있음 + CONTAB"),
    "p2": (1, "Exchange: 메일 목록에 계정"),
    "p3": (1, "계정 관리자 키 없음(판을 모름)"),
    "p4": (1, "POP3 계정(문서 CLSID {ED475411}) — 목록 값 없음"),
    "p5": (1, "빈 계정 관리자 키(주소록이라는 긍정 증거 없음)"),
    "p6": (0, "LDAP 주소록만(MAPI + EMABLT)"),
    "p7": (1, "Exchange 계정(MAPI CLSID)인데 Service Name 없음·목록 없음 — H7 핵심"),
    "p8": (0, "실제 LDAP 계정 CLSID {4DB5CBF2…} + 주소록 목록만"),
    "p9": (1, "목록이 비어 있어도 Exchange(MSEMS) 계정이 있음"),
    "p10": (1, "IMAP4 계정 + CONTAB, 목록 비어 있음"),
    "p11": (1, "Hotmail/EAS 계정"),
    "p12": (0, "주소록 목록만 있고 계정 하위 키 없음"),
    "p13": (1, "모르는 하위 키(clsid 없음)만 — 모르면 쓸 수 있다고 본다"),
}

DRIVER = r"""
$ErrorActionPreference = 'Stop'
function Svc([string]$s) { return [Text.Encoding]::Unicode.GetBytes($s + [char]0) }
function A($clsid, $svc) { $s = $null; if ($svc) { $s = [byte[]](Svc $svc) }; return @{ clsid = $clsid; svc = $s } }   # 레지스트리 REG_BINARY 처럼 byte[]
function Shape([bool]$am, $ml, $sl, $al, $accts) {
    $v = @{}
    if ($null -ne $ml) { $v['@ML@'] = [byte[]]$ml }
    if ($null -ne $sl) { $v['@SL@'] = [byte[]]$sl }
    if ($null -ne $al) { $v['@AL@'] = [byte[]]$al }
    return @{ am = $am; vals = $v; accts = @($accts) }
}
$S = [ordered]@{}
$S['p1'] = Shape $true @() @() $null @((A '@MAPI@' 'CONTAB'))
$S['p2'] = Shape $true @(2, 0, 0, 0) @() $null @((A '@MAPI@' 'CONTAB'), (A '@MAPI@' 'MSEMS'))
$S['p3'] = @{ am = $false }
$S['p4'] = Shape $true $null $null $null @((A '@POP@' $null))
$S['p5'] = Shape $true $null $null $null @()
$S['p6'] = Shape $true $null $null $null @((A '@MAPI@' 'EMABLT'))
$S['p7'] = Shape $true $null $null $null @((A '@MAPI@' $null))
$S['p8'] = Shape $true $null $null @(1, 0, 0, 0) @((A '@LDAP@' $null))
$S['p9'] = Shape $true @() @() $null @((A '@MAPI@' 'CONTAB'), (A '@MAPI@' 'MSEMS'))
$S['p10'] = Shape $true @() @() $null @((A '@MAPI@' 'CONTAB'), (A '@IMAP@' $null))
$S['p11'] = Shape $true $null $null $null @((A '@EAS@' $null))
$S['p12'] = Shape $true $null $null @(1, 0, 0, 0) @()
$S['p13'] = Shape $true $null $null $null @(@{ clsid = $null; svc = $null })
@FN@
$all = Get-OutlookProfileState -Shapes @($S.Values)
$none = Get-OutlookProfileState -Roots @('HKCU:\Software\@KEY@')
$empty = Get-OutlookProfileState -Roots @()
$one = [ordered]@{}
foreach ($n in $S.Keys) { $one[$n] = (Get-OutlookProfileState -Shapes @($S[$n])).usable }
[Console]::Out.WriteLine((ConvertTo-Json -Compress @{ total = $all.total; usable = $all.usable; none = $none; empty = $empty; one = $one }))
"""


def function_text(script: str) -> str:
    t = (ROOT / "collect" / script).read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    m = re.search(r"\nfunction Get-OutlookProfileState \{\n.*?\n\}\n", t, re.S)
    assert m, f"{script}: Get-OutlookProfileState 없음"
    return m.group(0)


def run_driver(fn: str) -> tuple[dict | None, str]:
    key = "LM27T-profstate-none-" + uuid.uuid4().hex[:12]           # 만들지 않는 키(읽기 쪽 빈 결과 확인)
    script = (DRIVER.replace("@KEY@", key).replace("@MAPI@", MAPI).replace("@POP@", POP).replace("@IMAP@", IMAP)
              .replace("@EAS@", EAS).replace("@LDAP@", LDAP).replace("@ML@", MAIL_LIST).replace("@SL@", STORE_LIST)
              .replace("@AL@", AB_LIST).replace("@FN@", fn))
    tmp = Path(tempfile.mkdtemp(prefix="lm27t_profstate_"))
    try:
        f = tmp / "drive.ps1"
        f.write_bytes(script.replace("\n", "\r\n").encode("utf-8-sig"))     # BOM — 한글 주석이 든 함수 글
        cp = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(f)],
                            capture_output=True, timeout=120, creationflags=0x08000000)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    out = cp.stdout.decode("utf-8", "replace").strip().splitlines()
    res = json.loads(out[-1]) if out and out[-1].startswith("{") else None
    return res, cp.stderr.decode("utf-8", "replace")


class ProfileStateCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.res = {}
        cls.err = {}
        for s in SCRIPTS:
            cls.res[s], cls.err[s] = run_driver(function_text(s))

    def test_counts(self):
        for s in SCRIPTS:
            with self.subTest(script=s):
                r = self.res[s]
                self.assertIsNotNone(r, self.err[s])
                self.assertEqual(r["total"], len(CASES))
                self.assertEqual(r["usable"], sum(v for v, _d in CASES.values()))
                self.assertEqual(r["none"], {"total": 0, "usable": 0})
                self.assertEqual(r["empty"], {"total": 0, "usable": 0})

    def test_each_profile(self):
        want = {k: v for k, (v, _d) in CASES.items()}
        for s in SCRIPTS:
            with self.subTest(script=s):
                self.assertIsNotNone(self.res[s], self.err[s])
                self.assertEqual(self.res[s]["one"], want)

    def test_exchange_without_service_name_is_usable(self):
        # H7 회귀 — 예전 판정은 p7(Service Name 없는 MAPI 계정)을 0 으로, p8(실제 LDAP CLSID)을 1 로 셌다
        for s in SCRIPTS:
            self.assertIsNotNone(self.res[s], self.err[s])
            self.assertEqual((self.res[s]["one"]["p7"], self.res[s]["one"]["p8"]), (1, 0), s)

    def test_function_does_not_write_registry(self):
        for s in SCRIPTS:
            fn = function_text(s)
            self.assertIsNone(re.search(r"(?i)\b(New-Item|New-ItemProperty|Set-ItemProperty|Remove-Item|Set-Item)\b", fn))


if __name__ == "__main__":
    unittest.main()
