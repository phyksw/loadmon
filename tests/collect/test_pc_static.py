# -*- coding: utf-8 -*-
"""WP-14 PC 수집기 정적 관문 시험 — 인코딩(계약 §9.2 · L-02), 제어문자 0(L-01 · CP-10 'BEL 류 깨진 경로'), 수집기 PS 디스크 쓰기 0
(L-09), stdout 오염 금지(Write-Host 0), 시험 주입점(계약 §11.3)·공통 인자(§7.3 — -Root·-PcId·-CursorFile 금지), 사유 코드 ⊂ §6.1
(L-13), 경로 ID ⊂ §6.5(L-14), 폐기 산출물 이름 0(L-29), 에이전트 bin 사본(ps\\)에서 단독 실행(계약 §1.3 — ROOT 를 참조하지 않는다).
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from lm27.collect import rcmap
from tests.fixtures.tree import CloneTestCase
from tests.fixtures.wp14.runner import CREATE_NO_WINDOW, run_ps
from tests.fixtures.wp14.shell_files import filetime

TREE = Path(__file__).resolve().parents[2]
PS = ["Get-EventActivity.ps1", "Get-FileActivity.ps1", "Get-OfficeMru.ps1", "Get-RecentFiles.ps1",
      "Get-LicenseUsage.ps1", "Add-WorkLog.ps1"]
PY = ["collect/Get-GitActivity.py", "lm27/catalog.py"]
AGENT_PS = ["Get-EventActivity.ps1", "Get-FileActivity.ps1", "Get-OfficeMru.ps1", "Get-RecentFiles.ps1"]   # bin\<ver>\ps\
CTRL = re.compile(rb"[\x00-\x08\x0b\x0c\x0e-\x1f]")
INJECT = {"Get-EventActivity.ps1": ["EventsCsv", "Now", "BootTime", "OutDir", "TestNow"],
          "Get-FileActivity.ps1": ["RecentDir", "MruTextDir", "NoToolMru", "TestNow"],
          "Get-OfficeMru.ps1": ["MruRegFile", "NoJumpList", "TestNow"],
          "Get-RecentFiles.ps1": ["RecentDir", "MruRegFile", "TestNow"],
          "Get-LicenseUsage.ps1": ["TestNow"], "Add-WorkLog.ps1": ["TestNow"]}
# 폐기 산출물 이름(L-29 ① 과 이전 판 PC 수집기 산출물) — 저장소 텍스트에 이름이 그대로 남지 않게 실행 때 조립한다
DEAD_NAMES = tuple(".".join(p) for p in (("mail", "csv"), ("coverage", "json"), ("sanitize_audit", "jsonl"),
                                         ("completion_ledger", "jsonl"), ("git_source", "json"), ("files", "csv"),
                                         ("recent", "csv"), ("worklog", "csv"))) + ("teams_window", "files_excluded")


def read(rel) -> bytes:
    return (TREE / rel).read_bytes()


def params(text: str) -> list:
    m = re.search(r"(?ms)^param\((.*?)^\)", text)
    return re.findall(r"\$([A-Za-z]+)", m.group(1)) if m else []


def contract_path_ids() -> set:
    doc = TREE / "docs" / "CONTRACT.md"
    if not doc.is_file():
        return set()
    text = doc.read_bytes().decode("utf-8")
    sec = text[text.index("### 6.5"):text.index("### 6.6")]
    return set(re.findall(r"^\| `((?:mail|cal|teams|pc)\.[a-z]+|manual)` \|", sec, re.M))


class EncodingTest(unittest.TestCase):
    def test_ps1_bom_crlf_no_ctrl(self):
        for n in PS:
            b = read(f"collect/{n}")
            self.assertTrue(b.startswith(b"\xef\xbb\xbf"), n)
            body = b[3:]
            self.assertEqual(body.count(b"\n"), body.count(b"\r\n"), f"{n}: CRLF 아님")
            self.assertNotIn(b"\r\r", body, n)
            self.assertIsNone(CTRL.search(body), n)
            body.decode("utf-8")

    def test_py_utf8_lf_no_ctrl(self):
        for rel in PY:
            b = read(rel)
            self.assertFalse(b.startswith(b"\xef\xbb\xbf"), rel)
            self.assertNotIn(b"\r", b, rel)
            self.assertIsNone(CTRL.search(b), rel)

    def test_hook_check_clean(self):
        files = [f"collect/{n}" for n in PS] + PY
        cp = subprocess.run([sys.executable, "-X", "utf8", "-B", str(TREE / "tools" / "hook_check.py"), *files],
                            cwd=str(TREE), capture_output=True, timeout=300, check=False,
                            creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0)
        self.assertEqual(cp.returncode, 0, cp.stdout.decode("utf-8", "replace") + cp.stderr.decode("utf-8", "replace"))


class ContractStaticTest(unittest.TestCase):
    def test_injection_and_common_params(self):
        for n in PS:
            text = read(f"collect/{n}").decode("utf-8-sig")
            ps = params(text)
            for p in INJECT[n]:
                self.assertIn(p, ps, f"{n}: 시험 주입 -{p}")
            self.assertIn("Pc", ps, n)
            for bad in ("Root", "PcId", "CursorFile"):
                self.assertNotIn(bad, ps, f"{n}: 경로 조립 인자 -{bad} 금지(계약 §7.3)")
        ev = read("collect/Get-EventActivity.ps1").decode("utf-8-sig")
        self.assertRegex(ev, r"\[string\]\$OutDir = ''")

    def test_no_write_host_and_no_disk_cmdlets(self):
        for n in PS:
            code = "\n".join(ln for ln in read(f"collect/{n}").decode("utf-8-sig").splitlines()
                             if not ln.strip().startswith("#"))
            self.assertNotRegex(code, r"(?i)\bWrite-Host\b", n)
            self.assertNotRegex(code, r"(?i)\b(Out-File|Set-Content|Add-Content|Export-Csv|Start-Transcript)\b", n)
            if n != "Get-EventActivity.ps1":                                   # 이것만 시험 주입 -OutDir 예외(계약 §11.3)
                self.assertNotRegex(code, r"(?i)\[IO\.File\]::(Write|Append|Create)", n)

    def test_reason_codes_registered(self):
        rx = re.compile(r"(?<![A-Za-z0-9_-])R-[A-Z]{2,}(?:-[A-Z0-9]+)*(?![A-Za-z0-9_])")      # L-13 과 같은 경계
        for rel in [f"collect/{n}" for n in PS] + PY:
            for code in set(rx.findall(read(rel).decode("utf-8-sig"))):
                self.assertIn(code, rcmap.REASONS, f"{rel}: {code}")

    def test_path_ids_in_contract(self):
        ids = contract_path_ids()
        if not ids:
            self.skipTest("docs\\CONTRACT.md 없음")
        rx = re.compile(r"""['"]((?:mail|cal|teams|pc)\.[a-z]{2,10})['"]""")
        for rel in [f"collect/{n}" for n in PS] + PY:
            for v in rx.findall(read(rel).decode("utf-8-sig")):
                self.assertIn(v, ids, f"{rel}: {v}")

    def test_no_dead_artifact_names(self):
        for rel in [f"collect/{n}" for n in PS] + PY:
            text = read(rel).decode("utf-8-sig").lower()
            for name in DEAD_NAMES:
                self.assertNotIn(name, text, f"{rel}: {name}")

    def test_agent_scripts_do_not_reference_root(self):
        for n in AGENT_PS:
            text = read(f"collect/{n}").decode("utf-8-sig")
            for bad in ("PSScriptRoot", "lm27_cli", "config\\", "MyInvocation", "data\\pcs"):
                self.assertNotIn(bad, text, f"{n}: {bad}")


class AgentCopyRunTest(CloneTestCase):
    """에이전트 bin 사본처럼 ps\\ 폴더에 낱개로 복사한 스크립트가 프로그램 폴더 없이 돈다(계약 §1.3)."""

    def test_runs_from_bin_ps_copy(self):
        tmp = Path(tempfile.mkdtemp(prefix="lm27t_wp14bin_", dir=str(self.clone.temp)))
        try:
            ps = tmp / "bin" / "0.1.0" / "ps"
            ps.mkdir(parents=True)
            for n in AGENT_PS:
                shutil.copy2(self.clone.path("collect", n), ps / n)
            when = datetime(2026, 9, 15, 2, 0, tzinfo=UTC)
            reg = tmp / "m.reg"
            lines = ["Windows Registry Editor Version 5.00", "",
                     "[HKEY_CURRENT_USER\\Software\\Microsoft\\Office\\16.0\\Word\\File MRU]",
                     f'"Item 1"="[F00000000][T{filetime(when):016X}][O00000000]*C:\\\\Users\\\\hong\\\\Documents\\\\a.docx"', ""]
            reg.write_bytes(b"\xff\xfe" + "\r\n".join(lines).encode("utf-16-le"))
            empty_app = tmp / "appdata"
            empty_app.mkdir()
            r = run_ps(self.clone, "Get-OfficeMru.ps1", ["-MruRegFile", str(reg), "-TestNow", "2026-09-20 12:00",
                                                         "-Since", "2026-09-01", "-Until", "2026-09-30"],
                       cfg={}, env={"APPDATA": str(empty_app)}, script_path=ps / "Get-OfficeMru.ps1")
            self.assertEqual(r.rc, 0, r.err())
            self.assertEqual(len(r.records), 1)
            self.assertEqual(r.cursor["last_ts_utc"], "2026-09-15T02:00:00Z")
            self.assertEqual(sorted(os.listdir(ps)), sorted(AGENT_PS))            # 사본 폴더에 아무것도 쓰지 않음
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
