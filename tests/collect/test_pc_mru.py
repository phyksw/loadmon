# -*- coding: utf-8 -*-
"""WP-14 pc.mru 수집기 시험 — collect\\Get-OfficeMru.ps1 을 reg 내보내기 재생(-MruRegFile, 계약 §11.3 · X-142)과 합성 Jump List
(%APPDATA% 를 복제 안 폴더로 돌림)로만 돌린다(실제 레지스트리·Jump List 를 읽지 않는다).

CP §5.3 · CP-8(Office 2013·2010 MRU 건수 > 0 — 16.0 하드코딩 회귀) · User MRU 전수 · Place MRU 제외 · op(open·modify) ·
R-MRUEMPTY · 커서·rc 4 · 자기 제외(X-316) · P-T31.
"""
import json
import os
import unittest
from datetime import UTC, datetime

from tests.fixtures.synth.inject import write_mru_reg
from tests.fixtures.synth.month import plan_month
from tests.fixtures.tree import CloneTestCase
from tests.fixtures.wp14.runner import FORBIDDEN_RAW, run_ps, snapshot
from tests.fixtures.wp14.shell_files import filetime, write_jumplist

SCRIPT = "Get-OfficeMru.ps1"
RAW_KEYS = {"path", "op", "size", "target_mtime", "pdf_sibling", "folder_role", "root_id", "ts_utc", "ts_local_offset",
            "ts_precision", "observed_at", "confidence", "flags"}
NOW = "2026-10-01 12:00"


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def reg_text(items) -> bytes:
    """[(키 꼬리, [(값 이름, 경로, 시각)])] → reg.exe export 모양(UTF-16 LE BOM)."""
    lines = ["Windows Registry Editor Version 5.00", ""]
    for key, vals in items:
        lines.append(f"[HKEY_CURRENT_USER\\Software\\Microsoft\\Office\\{key}]")
        for name, path, when in vals:
            esc = path.replace("\\", "\\\\").replace('"', '\\"')
            lines.append(f'"{name}"="[F00000000][T{filetime(when):016X}][O00000000]*{esc}"')
        lines.append("")
    return b"\xff\xfe" + ("\r\n".join(lines) + "\r\n").encode("utf-16-le")


class MruTest(CloneTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        b = cls.clone.temp / "wp14_mru"
        cls.base = b
        b.mkdir(parents=True, exist_ok=True)
        cls.appdata = b / "appdata"
        (cls.appdata / "Microsoft" / "Windows" / "Recent" / "AutomaticDestinations").mkdir(parents=True, exist_ok=True)
        cls.empty_appdata = b / "appdata_empty"
        cls.empty_appdata.mkdir(parents=True, exist_ok=True)
        docs = b / "docs"
        docs.mkdir(parents=True, exist_ok=True)
        cls.edited = docs / "편집함.docx"
        cls.viewed = docs / "열람만.xlsx"
        cls.edited.write_bytes(b"x")
        cls.viewed.write_bytes(b"x")
        ts_e = datetime(2026, 9, 15, 2, 0, tzinfo=UTC).timestamp()
        ts_v = datetime(2026, 9, 1, 2, 0, tzinfo=UTC).timestamp()
        os.utime(cls.edited, (ts_e, ts_e))
        os.utime(cls.viewed, (ts_v, ts_v))
        prog = b / "prog"
        (prog / "data").mkdir(parents=True, exist_ok=True)
        (prog / "data" / "bundle.json").write_bytes(b"{}")
        cls.selfdoc = prog / "out" / "report.docx"
        when = datetime(2026, 9, 15, 2, 0, tzinfo=UTC)
        cls.reg_custom = b / "custom.reg"
        cls.reg_custom.write_bytes(reg_text([
            ("16.0\\Word\\File MRU", [("Item 1", str(cls.edited), when), ("Max Display", "x", when)]),
            ("16.0\\Excel\\User MRU\\LiveId_LM27T0001\\File MRU", [("Item 1", str(cls.viewed), when),
                                                                    ("Item 2", str(docs / "없는파일.pptx"), when)]),
            ("16.0\\Word\\Place MRU", [("Item 1", str(docs / "폴더표시.docx"), when)]),
            ("17.0\\Word\\File MRU", [("Item 1", str(docs / "미등록판.docx"), when)]),
            ("16.0\\Word\\User MRU\\ADAL_LM27T0002\\File MRU", [("Item 1", str(cls.selfdoc), when)]),
        ]))
        cls.plan = plan_month(2026, 9)
        cls.reg_old = write_mru_reg(b / "office_old.reg", cls.plan, versions=("14.0", "15.0"), limit=6)
        cls.reg_16 = write_mru_reg(b / "office_16.reg", cls.plan, versions=("16.0",), limit=6)

    def run_mru(self, reg, *, cfg=None, cursor=None, appdata=None, extra=(), since="2026-09-01", until="2026-09-30"):
        args = ["-MruRegFile", str(reg), "-TestNow", NOW, "-Since", since, "-Until", until, *extra]
        r = run_ps(self.clone, SCRIPT, args, cfg=cfg if cfg is not None else {}, cursor=cursor,
                   env={"APPDATA": str(appdata or self.empty_appdata)})
        self.assertIsNotNone(r.status, r.err())
        self.assertEqual(r.controls[-1].keys(), {"_cursor"})
        for rec in r.records:
            self.assertTrue(set(rec) <= RAW_KEYS, set(rec) - RAW_KEYS)
            self.assertFalse(set(rec) & FORBIDDEN_RAW)
            self.assertIn(rec["op"], ("open", "modify"))
            self.assertEqual(rec["confidence"], 0.8)
            self.assertEqual(rec["ts_precision"], "minute")
        return r

    def test_office_2010_2013_versions_cp8(self):
        r = self.run_mru(self.reg_old)
        self.assertEqual(r.rc, 0, r.status)
        self.assertGreater(len(r.records), 0)
        self.assertEqual(r.status["mru"]["key_count"], 6)                    # 2판 × Word·Excel·PowerPoint User MRU
        r16 = self.run_mru(self.reg_old, cfg={"pc.mru.officeVersions": ["16.0"]}, extra=["-NoJumpList"])
        self.assertEqual((r16.rc, r16.records), (1, []))
        self.assertIn("R-MRUEMPTY", r16.status["reasons"])
        self.assertEqual(len(self.run_mru(self.reg_16).records), len(r.records))      # 같은 항목(경로·시각)은 한 번

    def test_user_mru_top_level_place_mru_and_versions(self):
        r = self.run_mru(self.reg_custom)
        names = sorted(os.path.basename(x["path"]) for x in r.records)
        self.assertEqual(names, sorted(["편집함.docx", "열람만.xlsx", "없는파일.pptx"]))     # Place MRU·17.0·자기 폴더 제외
        self.assertEqual(r.status["mru"]["key_count"], 3)
        self.assertEqual(r.status["excluded"]["self"], 1)
        by = {os.path.basename(x["path"]): x for x in r.records}
        self.assertEqual(by["편집함.docx"]["op"], "modify")                      # 대상 수정 ≥ 열람 − 2분
        self.assertEqual(by["열람만.xlsx"]["op"], "open")                        # 대상 수정이 열람보다 오래됨
        self.assertEqual(by["열람만.xlsx"]["target_mtime"], iso(datetime(2026, 9, 1, 2, 0, tzinfo=UTC)))
        self.assertEqual(by["없는파일.pptx"]["op"], "open")
        self.assertIsNone(by["없는파일.pptx"]["size"])
        self.assertIsNone(by["없는파일.pptx"]["target_mtime"])
        self.assertEqual(by["편집함.docx"]["ts_utc"], iso(datetime(2026, 9, 15, 2, 0, tzinfo=UTC)))
        self.assertEqual(by["편집함.docx"]["size"], 1)

    def test_cursor_rc4(self):
        r1 = self.run_mru(self.reg_custom)
        r2 = self.run_mru(self.reg_custom, cursor=r1.cursor)
        self.assertEqual((r2.rc, r2.records), (4, []))
        self.assertEqual(r2.cursor, r1.cursor)

    def test_jump_lists(self):
        ad = self.appdata / "Microsoft" / "Windows" / "Recent" / "AutomaticDestinations"
        work = self.base / "cad"
        cad = work / "브래킷_과제B.sldprt"
        write_jumplist(ad / "1111111111111111.automaticDestinations-ms",
                       [(str(cad), datetime(2026, 9, 20, 3, 0, tzinfo=UTC)),
                        (str(work), datetime(2026, 9, 20, 3, 1, tzinfo=UTC)),                 # 폴더 → 건너뜀
                        ("knownfolder:{FDD39AD0-238F-46AF-ADB4-6C85480369C7}", datetime(2026, 9, 20, 3, 2, tzinfo=UTC))])
        write_jumplist(ad / "2222222222222222.automaticDestinations-ms",
                       [(str(work / f"결과_{i:02d}_설계해석_과제C.wbpj"), datetime(2026, 9, 21, 1, i, tzinfo=UTC))
                        for i in range(40)])                                                  # 4,096바이트 넘음(일반 섹터)
        write_jumplist(ad / "3333333333333333.automaticDestinations-ms",
                       [(str(work / "옛판형식.dwg"), datetime(2026, 9, 22, 1, 0, tzinfo=UTC))], version=1)
        (ad / "4444444444444444.automaticDestinations-ms").write_bytes(b"not a compound file")
        r = self.run_mru(self.reg_custom, appdata=self.appdata, since="2026-09-16")
        names = sorted(os.path.basename(x["path"]) for x in r.records)
        self.assertEqual(len(names), 42, r.status)
        self.assertIn("브래킷_과제B.sldprt", names)
        self.assertIn("옛판형식.dwg", names)
        self.assertEqual(r.status["jumplist"], {"on": True, "files": 3, "items": 42, "errors": 1})
        cfg = {"pc.watchExtensions": [".dwg"]}
        r2 = self.run_mru(self.reg_custom, appdata=self.appdata, since="2026-09-16", cfg=cfg)
        self.assertEqual([os.path.basename(x["path"]) for x in r2.records], ["옛판형식.dwg"])
        r3 = self.run_mru(self.reg_custom, appdata=self.appdata, since="2026-09-16", extra=["-NoJumpList"])
        self.assertEqual(r3.records, [])
        r4 = self.run_mru(self.reg_custom, appdata=self.appdata, since="2026-09-16", cfg={"pc.mru.jumpList": False})
        self.assertEqual(r4.records, [])
        self.assertFalse(r4.status["jumplist"]["on"])

    def test_final_name_flag(self):
        when = datetime(2026, 9, 18, 2, 0, tzinfo=UTC)
        reg = self.base / "final.reg"
        reg.write_bytes(reg_text([("16.0\\Word\\File MRU", [("Item 1", "C:\\Users\\hong\\Documents\\계약서_확정.docx", when),
                                                             ("Item 2", "C:\\Users\\hong\\Documents\\메모.docx", when)])]))
        r = self.run_mru(reg, cfg={"episode.finalWords": ["최종", "확정"]})
        flags = {os.path.basename(x["path"]): x["flags"] for x in r.records}
        self.assertEqual(flags, {"계약서_확정.docx": {"final_name": True}, "메모.docx": {}})

    def test_no_disk_writes(self):
        before = snapshot(self.base)
        before_lad = snapshot(self.clone.lad)
        self.run_mru(self.reg_custom, appdata=self.appdata)
        self.assertEqual(snapshot(self.base), before)
        self.assertEqual(snapshot(self.clone.lad), before_lad)


REG_WRAPPER = r"""
$ErrorActionPreference = 'Stop'
$global:FakeReg = [IO.File]::ReadAllText($env:LM27T_FAKE_REG, [Text.Encoding]::UTF8) | ConvertFrom-Json
$global:RegQueries = 0
function global:ConvertTo-FakeKey([string]$p) {
    $p = $p -replace '^Microsoft\.PowerShell\.Core\\Registry::', ''
    $p = $p -replace '^HKCU:\\?', 'HKEY_CURRENT_USER\'
    return $p.TrimEnd('\')
}
function global:Test-FakeReg([string]$p) { return ($p -match '^(?:HKCU:|Microsoft\.PowerShell\.Core\\Registry::)') }
function global:Get-FakeKeys { return @($global:FakeReg.keys.PSObject.Properties | ForEach-Object { $_.Name }) }
function Test-Path {
    [CmdletBinding()] param([string]$LiteralPath, [string]$Path, [string]$PathType)
    $lp = $LiteralPath
    if (-not $lp) { $lp = $Path }
    if (Test-FakeReg $lp) {
        $global:RegQueries++
        $k = (ConvertTo-FakeKey $lp).ToLower()
        foreach ($x in (Get-FakeKeys)) { $xl = $x.ToLower(); if ($xl -eq $k -or $xl.StartsWith($k + '\')) { return $true } }
        return $false
    }
    return (Microsoft.PowerShell.Management\Test-Path @PSBoundParameters)
}
function Get-ChildItem {
    [CmdletBinding()] param([string]$LiteralPath, [string]$Path, [string]$Filter, [switch]$File, [switch]$Recurse, $Depth)
    $lp = $LiteralPath
    if (-not $lp) { $lp = $Path }
    if (Test-FakeReg $lp) {
        $global:RegQueries++
        $k = ConvertTo-FakeKey $lp
        $seen = @{}
        foreach ($x in (Get-FakeKeys)) {
            if (-not $x.ToLower().StartsWith($k.ToLower() + '\')) { continue }
            $name = $x.Substring($k.Length + 1).Split('\')[0]
            if ($seen.ContainsKey($name.ToLower())) { continue }
            $seen[$name.ToLower()] = 1
            [pscustomobject]@{ PSPath = 'Microsoft.PowerShell.Core\Registry::' + $k + '\' + $name; PSChildName = $name }
        }
        return
    }
    Microsoft.PowerShell.Management\Get-ChildItem @PSBoundParameters
}
function Get-ItemProperty {
    [CmdletBinding()] param([string]$LiteralPath, [string]$Path)
    $lp = $LiteralPath
    if (-not $lp) { $lp = $Path }
    if (Test-FakeReg $lp) {
        $global:RegQueries++
        $k = (ConvertTo-FakeKey $lp).ToLower()
        foreach ($p in $global:FakeReg.keys.PSObject.Properties) {
            if ($p.Name.ToLower() -eq $k) { return $p.Value }
        }
        throw (New-Object Management.Automation.ItemNotFoundException)
    }
    return (Microsoft.PowerShell.Management\Get-ItemProperty @PSBoundParameters)
}
& $env:LM27T_COLLECTOR @args
$code = $LASTEXITCODE
[Console]::Error.WriteLine('{"_fake_reg_queries":' + $global:RegQueries + '}')
exit $code
"""


class RegistryMockTest(CloneTestCase):
    """실제 레지스트리 대신 Test-Path·Get-ChildItem·Get-ItemProperty 의 레지스트리 경로만 시험 함수로 가린 감싸개로 '실제
    레지스트리' 갈래(판 전수 · 앱 열거 · User MRU 열거 · Place MRU 제외)를 돈다. 레지스트리에 쓰지도 읽지도 않는다."""

    def test_registry_branch_enumerates_versions_apps_user_mru(self):
        d = self.clone.temp / "wp14_regmock"
        d.mkdir(parents=True, exist_ok=True)
        when = datetime(2026, 9, 15, 2, 0, tzinfo=UTC)

        def item(path):
            return f"[F00000000][T{filetime(when):016X}][O00000000]*{path}"

        base = "HKEY_CURRENT_USER\\Software\\Microsoft\\Office\\"
        keys = {
            base + "14.0\\Word\\File MRU": {"Item 1": item("C:\\Users\\hong\\Documents\\옛판_2010.docx"), "Max Display": 25},
            base + "15.0\\Excel\\User MRU\\LiveId_LM27T0001\\File MRU": {"Item 1": item("C:\\Users\\hong\\Documents\\2013.xlsx")},
            base + "16.0\\PowerPoint\\User MRU\\ADAL_LM27T0002\\File MRU": {"Item 1": item("C:\\Users\\hong\\Documents\\발표.pptx"),
                                                                           "Item 2": item("C:\\Users\\hong\\Documents\\발표2.pptx")},
            base + "16.0\\PowerPoint\\User MRU\\ADAL_LM27T0002\\Place MRU": {"Item 1": item("C:\\Users\\hong\\Documents")},
            base + "16.0\\Common\\General": {"Something": "x"},
            base + "17.0\\Word\\File MRU": {"Item 1": item("C:\\Users\\hong\\Documents\\미등록판.docx")},
        }
        data = d / "reg.json"
        data.write_bytes(json.dumps({"keys": keys}, ensure_ascii=False).encode("utf-8"))
        wrapper = d / "fake_reg.ps1"
        wrapper.write_bytes(REG_WRAPPER.replace("\n", "\r\n").encode("ascii"))
        app = d / "appdata"
        app.mkdir(exist_ok=True)
        env = {"LM27T_FAKE_REG": str(data), "LM27T_COLLECTOR": str(self.clone.path("collect", "Get-OfficeMru.ps1")),
               "APPDATA": str(app)}
        r = run_ps(self.clone, "Get-OfficeMru.ps1", ["-TestNow", NOW, "-Since", "2026-09-01", "-Until", "2026-09-30"],
                   cfg={}, env=env, script_path=wrapper)
        self.assertEqual(r.rc, 0, r.err())
        self.assertIn('"_fake_reg_queries"', r.err())
        names = sorted(os.path.basename(x["path"]) for x in r.records)
        self.assertEqual(names, sorted(["옛판_2010.docx", "2013.xlsx", "발표.pptx", "발표2.pptx"]))
        self.assertEqual(r.status["mru"]["key_count"], 3)
        self.assertEqual(r.status["mru"]["items"], 4)


if __name__ == "__main__":
    unittest.main()
