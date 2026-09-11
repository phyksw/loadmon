"""Unified move preparation using TEMP data and mocked process/UI operations."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile


APP = Path(__file__).resolve().parents[1] / "LoadMonitor25"
PREPARE = APP / "tools" / "Prepare-Move.ps1"


def ps_quote(value):
    return "'" + str(value).replace("'", "''") + "'"


@unittest.skipUnless(os.name == "nt", "Windows PowerShell/BAT integration")
class PrepareMoveTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="lm25-prepare-move-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / "LoadMonitor25 synthetic"
        self.root.mkdir()
        self.write("tools/transfer.py", (APP / "tools" / "transfer.py").read_bytes())
        self.write("config/config.json", b'{"owner":"Synthetic"}')
        self.write("data/manual/worklog.csv", b"date,hours\n2026-01-05,3\n")
        self.write("data/pc_name.txt", b"SYNTHETIC-PC-A")
        self.write("data/추가PC/PC-B/files/files.csv", b"name,folder\n")
        self.write("data/copilot_profile/Default/Cookies", b"synthetic profile")
        self.write("report/results.csv", b"value\nsynthetic\n")
        self.write("report/upload_pending/queued.json", b'{"synthetic":true}')
        self.write("teamdata/Synthetic/member.json", b'{"synthetic":true}')
        self.before = {p.relative_to(self.root): p.read_bytes()
                       for p in self.root.rglob("*") if p.is_file()}
        self.script = self.base / "Prepare-Move.ps1"
        shutil.copy2(PREPARE, self.script)
        self.calls = self.base / "mock-calls.txt"

    def write(self, relative, data):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def invoke(self, *, check=False, fail_restore=False, output=None):
        # The harness replaces every process enumeration/termination and Shell
        # automation call before executing the real PS1. Rename and ZIP I/O are
        # real but confined to our synthetic TEMP tree. No app/server starts.
        harness = self.base / "harness.ps1"
        source = r"""
$global:FixtureRoot = __ROOT__
$global:FixtureParent = __PARENT__
$global:FixtureCalls = __CALLS__
$global:FixturePython = __PYTHON__
$global:FailRestore = __RESTORE__
function global:Get-CimInstance {
    param($ClassName, $Filter, $ErrorAction)
    $all = @(
        [pscustomobject]@{ ProcessId = 101; Name = 'python.exe'; ExecutablePath = $FixtureRoot + '\python\python.exe'; CommandLine = $FixtureRoot + '\ui\app.py' },
        [pscustomobject]@{ ProcessId = 102; Name = 'msedge.exe'; ExecutablePath = 'C:\Synthetic\msedge.exe'; CommandLine = 'msedge --user-data-dir="' + $FixtureRoot + '\data\copilot_profile"' },
        [pscustomobject]@{ ProcessId = 103; Name = 'powershell.exe'; ExecutablePath = 'C:\Synthetic\powershell.exe'; CommandLine = 'powershell -File "' + $FixtureRoot + '\collect\Start-Sampler.ps1"' },
        [pscustomobject]@{ ProcessId = 201; Name = 'python.exe'; ExecutablePath = $FixtureRoot + '_other\python\python.exe'; CommandLine = $FixtureRoot + '_other\ui\app.py' },
        [pscustomobject]@{ ProcessId = 202; Name = 'msedge.exe'; ExecutablePath = 'C:\Synthetic\msedge.exe'; CommandLine = 'msedge --user-data-dir="C:\Synthetic\another\copilot_profile"' },
        [pscustomobject]@{ ProcessId = 203; Name = 'python.exe'; ExecutablePath = $FixtureRoot + ' backup\python\python.exe'; CommandLine = '"' + $FixtureRoot + ' backup\python\python.exe" app.py' },
        [pscustomobject]@{ ProcessId = 204; Name = 'powershell.exe'; ExecutablePath = 'C:\Synthetic\powershell.exe'; CommandLine = 'powershell -File "' + $FixtureRoot + ' archive\collect\Start-Sampler.ps1"' },
        [pscustomobject]@{ ProcessId = 205; Name = 'msedge.exe'; ExecutablePath = 'C:\Synthetic\msedge.exe'; CommandLine = 'msedge --user-data-dir="' + $FixtureRoot + ' archive\data\copilot_profile"' },
        [pscustomobject]@{ ProcessId = 206; Name = 'msedge.exe'; ExecutablePath = 'C:\Synthetic\msedge.exe'; CommandLine = 'msedge --user-data-dir="' + $FixtureRoot + '\data\copilot_profile_backup"' }
    )
    if ($Filter) { return @($all | Where-Object { $_.Name -eq 'msedge.exe' }) }
    return $all
}
function global:Stop-Process {
    param($Id, [switch]$Force, $ErrorAction)
    Add-Content -LiteralPath $FixtureCalls -Value ('stop:' + $Id)
}
function global:Start-Sleep { param($Milliseconds, $Seconds) }
function global:New-Object {
    param($TypeName, $ComObject)
    if ($ComObject) { throw 'Shell automation is disabled in synthetic tests' }
    Microsoft.PowerShell.Utility\New-Object -TypeName $TypeName
}
function global:Get-Command {
    param($Name, $CommandType, $ErrorAction)
    if ($Name -ne 'python') { throw 'Unexpected command lookup' }
    [pscustomobject]@{ Source = $FixturePython }
}
function global:Rename-Item {
    param($LiteralPath, $NewName, $ErrorAction)
    $full = [System.IO.Path]::GetFullPath($LiteralPath)
    $destination = [System.IO.Path]::GetFullPath((Join-Path (Split-Path -Parent $full) $NewName))
    $allowed = @($FixtureRoot, ($FixtureRoot + '_이동확인_임시'))
    if ($full -notin $allowed -or $destination -notin $allowed -or
        (Split-Path -Parent $destination) -ne $FixtureParent) { throw 'Unsafe fixture rename' }
    Add-Content -LiteralPath $FixtureCalls -Value 'rename'
    if ($FailRestore -and $full -ne $FixtureRoot) { throw 'Synthetic restoration failure' }
    Microsoft.PowerShell.Management\Rename-Item -LiteralPath $full -NewName $NewName -ErrorAction Stop
}
& __SCRIPT__ -Root __ROOT__ -NoWait -CloseSec 0 __ARGS__
exit $LASTEXITCODE
"""
        replacements = {
            "__ROOT__": ps_quote(self.root), "__PARENT__": ps_quote(self.base),
            "__CALLS__": ps_quote(self.calls), "__PYTHON__": ps_quote(sys.executable),
            "__SCRIPT__": ps_quote(self.script), "__RESTORE__": "$true" if fail_restore else "$false",
            "__ARGS__": "-CheckOnly" if check else ("-Output " + ps_quote(output) if output else ""),
        }
        for old, new in replacements.items():
            source = source.replace(old, new)
        harness.write_text(source, encoding="utf-8-sig")
        return subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                               "-File", str(harness)], cwd=self.base, capture_output=True, timeout=60,
                              creationflags=0x08000000)

    def assert_originals(self, root=None):
        root = root or self.root
        for relative, original in self.before.items():
            self.assertEqual((root / relative).read_bytes(), original, relative)

    def test_default_preparation_creates_one_verified_zip_and_preserves_state(self):
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assert_originals()
        archives = list(self.base.glob("*.zip"))
        self.assertEqual(len(archives), 1)
        with zipfile.ZipFile(archives[0]) as archive:
            names = archive.namelist()
            prefix = self.root.name + "/"
            for relative, original in self.before.items():
                name = prefix + relative.as_posix()
                if "copilot_profile" in relative.parts:
                    self.assertNotIn(name, names)
                else:
                    self.assertEqual(archive.read(name), original)
            manifest = json.loads(archive.read(prefix + "_LM25_TRANSFER_MANIFEST.json"))
            for item in manifest["files"]:
                payload = archive.read(prefix + item["path"])
                self.assertEqual(hashlib.sha256(payload).hexdigest(), item["sha256"])
        self.assertIn("PC 이동 준비와 ZIP 검증이 끝났습니다", result.stdout.decode("utf-8-sig"))
        calls = self.calls.read_text().splitlines()
        self.assertEqual([line for line in calls if line.startswith("stop:")], ["stop:101", "stop:103", "stop:102"])
        self.assertEqual(calls.count("rename"), 2)

    def test_zip_failure_is_not_success_and_does_not_replace_existing_output(self):
        output = self.base / "existing.zip"
        output.write_bytes(b"Existing unrelated artifact")
        result = self.invoke(output=output)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(output.read_bytes(), b"Existing unrelated artifact")
        self.assert_originals()
        self.assertNotIn("[완료]", result.stdout.decode("utf-8-sig"))
        self.assertEqual(list(self.base.glob(".lm25-transfer-*.tmp")), [])

    def test_restore_failure_keeps_source_at_probe_and_never_creates_zip(self):
        result = self.invoke(fail_restore=True)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertFalse(self.root.exists(), "Do not recreate an empty original folder")
        self.assert_originals(Path(str(self.root) + "_이동확인_임시"))
        self.assertEqual(list(self.base.glob("*.zip")), [])
        self.assertNotIn("[완료]", result.stdout.decode("utf-8-sig"))

    def test_check_only_keeps_rename_diagnostic_without_stop_or_zip(self):
        result = self.invoke(check=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assert_originals()
        self.assertEqual(self.calls.read_text().splitlines(), ["rename", "rename"])
        self.assertEqual(list(self.base.glob("*.zip")), [])

    def test_compatibility_bat_redirects_old_cli_flags_without_starting_preparation(self):
        for name in ("LoadMonitor25-이동준비.bat", "LoadMonitor25-빠른이동.bat"):
            shutil.copy2(APP / name, self.root / name)
        for name in ("LoadMonitor25-이동준비.bat", "LoadMonitor25-빠른이동.bat"):
            for flag in ("--plan", "--json", "--root", "--output"):
                with self.subTest(name=name, flag=flag):
                    result = subprocess.run(["cmd.exe", "/d", "/c", str(self.root / name), flag],
                                            cwd=self.base, capture_output=True, timeout=10,
                                            creationflags=0x08000000)
                    self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                    self.assertIn(b"tools\\transfer.py", result.stdout)
        self.assertFalse(self.calls.exists())
        self.assertEqual(list(self.base.glob("*.zip")), [])


if __name__ == "__main__":
    unittest.main()
