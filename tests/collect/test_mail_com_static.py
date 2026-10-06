# -*- coding: utf-8 -*-
r"""COM 수집기·탐침의 정적 관문 — Microsoft 공식 문서와 어긋나던 호출이 다시 들어오지 않게(M365 조사 H6·H8·L5).

- H6: 보호 속성·메서드(Object Model Guard 보호 목록 — Account.SmtpAddress·NameSpace.CurrentUser·MailItem.Recipients·
  PropertyAccessor·Sender*·Body·AppointmentItem.Organizer 등)는 B단 함수 안에서만 읽는다. B단을 끈 실행(readProt 0)이 붙기
  단계에서 주소록 경고창을 띄우던 결함(Get-WorkerAddrs 의 Accounts.SmtpAddress) 회귀 방지.
  https://learn.microsoft.com/en-us/office/vba/outlook/how-to/security/protected-properties-and-methods
  (Columns.Add 도 목록에 있으나 A단 GetTable 이 쓰는 문서화된 방법이라 여기서 막지 않는다 — 회사 PC 실측 항목)
- H8: Namespace.Logon 을 부르지 않는다(프로필이 여럿이면 기본 프로필이 있어도 선택 창 — 문서 권장은 GetNamespace +
  GetDefaultFolder). https://learn.microsoft.com/en-us/office/vba/api/outlook.namespace.logon
- L5: 일정 회차 전개 순서 = Sort('[Start]') → IncludeRecurrences=True → Restrict.
  https://learn.microsoft.com/en-us/office/vba/api/outlook.items.includerecurrences
- PowerShell 5.1 구문 해석 오류 0.
"""
from __future__ import annotations

import os
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COM = ROOT / "collect" / "Get-OutlookCom.ps1"
PROBE = ROOT / "collect" / "Invoke-CapabilityProbe.ps1"
PS = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
CREATE_NO_WINDOW = 0x08000000

# Object Model Guard 보호 목록 중 이 수집기가 닿을 수 있는 멤버(문서 표 — Account·NameSpace·MailItem·AppointmentItem·
# Recipient(s)·AddressEntry·ExchangeUser). 멤버 이름은 대소문자를 가리지 않는다(PowerShell).
PROTECTED_RX = re.compile(
    r"(?i)\.(SmtpAddress|CurrentUser|Recipients|PropertyAccessor|SenderEmailAddress|SenderEmailType|SenderName|Sender|"
    r"Organizer|Body|HTMLBody|RTFBody|To|Cc|Bcc|RequiredAttendees|OptionalAttendees|Resources|ReceivedByName|"
    r"SentOnBehalfOfName|ReplyRecipientNames|GetExchangeUser|GetAddressEntryFromID|GetRecipientFromID|AddressEntry|"
    r"PrimarySmtpAddress)\b")
COM_B_FUNCS = {"Read-Protected", "Convert-CalItem", "Get-ProtectedAddrs"}      # B단(readProt 1 + 카나리아 뒤)만
PROBE_B_FUNCS = {"Invoke-ComChildReal"}                                       # pr_start 단계 워치독 안의 시험 읽기 1회


def _text(p: Path) -> str:
    return p.read_bytes().decode("utf-8-sig").replace("\r\n", "\n")


def _strip_comments(lines):
    out, block = [], False
    for ln in lines:
        s = ln.strip()
        if block:
            if "#>" in s:
                block = False
            out.append("")
            continue
        if s.startswith("<#"):
            block = "#>" not in s[2:]
            out.append("")
            continue
        if s.startswith("#"):
            out.append("")
            continue
        # 줄 끝 주석('  # …') — 문자열 안의 '#'는 이 수집기 코드에 없다(시험이 보는 멤버 접근에는 영향 없음)
        out.append(re.sub(r"\s#\s.*$", "", ln))
    return out


def functions(p: Path) -> dict[str, str]:
    """맨 앞 칸 'function 이름' 부터 다음 맨 앞 칸 '}' 까지 → {이름: 주석 뺀 본문}. 함수 밖 코드는 키 ''."""
    lines = _strip_comments(_text(p).split("\n"))
    out: dict[str, list[str]] = {"": []}
    cur = ""
    for ln in lines:
        m = re.match(r"^function ([\w-]+)", ln)
        if m:
            cur = m.group(1)
            out[cur] = [ln]
            continue
        out.setdefault(cur, []).append(ln)
        if cur and ln.startswith("}"):
            cur = ""
    return {k: "\n".join(v) for k, v in out.items()}


class ProtectedMembers(unittest.TestCase):
    def check(self, path: Path, allowed: set[str]):
        bad = []
        for name, body in functions(path).items():
            if name in allowed:
                continue
            for m in PROTECTED_RX.finditer(body):
                bad.append(f"{name or '(본문)'}: .{m.group(1)}")
        self.assertEqual(bad, [], f"{path.name}: B단 밖의 보호 멤버 접근(Object Model Guard 경고창)")

    def test_com_protected_only_in_b_stage(self):
        self.check(COM, COM_B_FUNCS)
        fns = functions(COM)
        for f in COM_B_FUNCS:
            self.assertIn(f, fns)

    def test_com_worker_addrs_reads_accounts_only_when_b_stage(self):
        # H6 — Get-WorkerAddrs 는 보호 주소(Accounts·CurrentUser)를 readProt 1 일 때만 Get-ProtectedAddrs 로 읽는다
        body = functions(COM)["Get-WorkerAddrs"]
        m = re.search(r"if \(\$script:W\.readProt\) \{\n(.*?)\n    \}", body, re.S)
        self.assertIsNotNone(m, "readProt 블록 없음")
        self.assertIn("Get-ProtectedAddrs", m.group(1))
        self.assertIn("'pr_start'", m.group(1))                          # 부모의 짧은 워치독 단계 안에서
        self.assertEqual(body.count("Get-ProtectedAddrs"), 1)
        self.assertNotRegex(body, r"(?i)\.Accounts\b")
        self.assertNotRegex(functions(COM)["Get-AccountNames"], PROTECTED_RX)

    def test_probe_protected_only_in_pr_phase(self):
        self.check(PROBE, PROBE_B_FUNCS)


class DocumentedCalls(unittest.TestCase):
    def test_no_namespace_logon(self):
        code = "\n".join(functions(COM).values())
        self.assertIsNone(re.search(r"(?i)\.Logon\s*\(", code), "Namespace.Logon 금지(H8 — 프로필 선택 창)")
        self.assertRegex(code, r"(?i)GetNamespace\('MAPI'\)")
        self.assertRegex(functions(COM)["Connect-Outlook"], r"GetDefaultFolder\(6\)")   # 문서 권장 MAPI 초기화

    def test_recurrence_order(self):
        body = functions(COM)["Get-CalEntries"]
        i_sort = body.find(".Sort('[Start]')")
        i_rec = body.find(".IncludeRecurrences = $true")
        i_res = body.find(".Restrict(")
        self.assertTrue(0 <= i_sort < i_rec < i_res, "Sort → IncludeRecurrences → Restrict 순서(L5)")

    def test_store_type_3_is_not_archive(self):
        # M16 — OlExchangeStoreType 3 = olNotExchange(PST·IMAP). 보관 사서함으로 읽지 않는다
        body = functions(COM)["Resolve-StoreRole"]
        self.assertRegex(body, r"-eq 3\)[^\n]*non_exchange")
        self.assertNotRegex(_text(COM), r"(?i)ExchangeStoreType -eq 3\)\s*\}\s*#\s*olExchangeArchiveMailbox")


@unittest.skipUnless(os.name == "nt" and PS.is_file(), "Windows PowerShell 5.1 없음")
class Parse(unittest.TestCase):
    def test_parser_errors_zero(self):
        cmd = ("$e=$null; $t=$null; [void][System.Management.Automation.Language.Parser]::ParseFile($env:LM27T_PS, "
               "[ref]$t, [ref]$e); foreach($x in $e){ '{0}: {1}' -f $x.Extent.StartLineNumber, $x.Message }; exit $e.Count")
        for p in (COM, PROBE):
            cp = subprocess.run([str(PS), "-NoProfile", "-NonInteractive", "-Command", cmd], capture_output=True,
                                env=dict(os.environ, LM27T_PS=str(p)), timeout=120, creationflags=CREATE_NO_WINDOW,
                                check=False)
            self.assertEqual(cp.returncode, 0, p.name + ": " + cp.stdout.decode("utf-8", "replace")[-2000:])


if __name__ == "__main__":
    unittest.main()
