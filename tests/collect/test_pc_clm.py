# -*- coding: utf-8 -*-
"""WP-14 PS 수집기 6종 — 제한 언어 모드(CLM) 회귀와 상태 줄 한 모양(계약 v1.2 §0.7 C1) 시험(W1 통합 창).

결함(W1a 반증 검토 확정): 최상위 ``New-Object`` 가 CLM 에서 막혀 수집기가 상태 줄 없이 rc 1 · 출력 0바이트로 끝났고,
연결자 번역(``rcmap.translate_cell(1, [])`` = ``zero_ok``)이 미관측을 '0건 관측'으로 원장에 넣었다. 수정: 각 스크립트의 첫
실행문이 언어 모드를 보고 stdout 제어 줄 ``{"_status": {…, "rc": 3, "reasons": ["R-CLM"]}}`` + exit 3(C1 · C4 · §8.1).

C1 필수 필드(schema·src·rc·reasons·partial·cap_hit·budget_hit·n·counts{})는 정상 경로(stderr 마지막 줄)·CLM 경로(stdout
제어 줄) 모두에서 확인한다. 실제 이벤트 로그·레지스트리·사용자 폴더는 읽지 않는다(주입 인자 — 계약 §11.3).
"""
import json
import os
import subprocess
import unittest

from lm27.collect import rcmap
from tests.fixtures.tree import CloneTestCase
from tests.fixtures.wp14.runner import CREATE_NO_WINDOW, powershell, run_ps

C1_KEYS = frozenset({"schema", "src", "rc", "reasons", "partial", "cap_hit", "budget_hit", "n", "counts"})
SCRIPTS = {"Get-EventActivity.ps1": "pc.events", "Get-FileActivity.ps1": "pc.files", "Get-OfficeMru.ps1": "pc.mru",
           "Get-RecentFiles.ps1": "pc.recent", "Get-LicenseUsage.ps1": "pc.compute", "Add-WorkLog.ps1": "manual"}
NOW = "2026-09-20 12:00"


def run_clm(clone, script, args=()):
    """같은 스크립트를 제한 언어 모드 세션에서 실행(-Command 로 언어 모드를 먼저 바꾼다 — test_mail_com CM-08 과 같은 방식)."""
    path = clone.path("collect", script)
    # 매개변수 이름(-X)은 따옴표 없이, 값만 작은따옴표로(따옴표 친 '-X' 는 위치 인자로 묶인다)
    quoted = " ".join(str(a) if str(a).startswith("-") else "'" + str(a).replace("'", "''") + "'" for a in args)
    cmd = ("$ExecutionContext.SessionState.LanguageMode='ConstrainedLanguage'; & '" + str(path).replace("'", "''")
           + "' " + quoted + "; exit $LASTEXITCODE")
    clone.temp.mkdir(parents=True, exist_ok=True)
    return subprocess.run([powershell(), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", cmd],
                          input=b"", capture_output=True, env=clone.env({}), cwd=str(clone.temp), timeout=240,
                          creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0, check=False)


class PcClmTest(CloneTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        b = cls.clone.temp / "wp14_clm"
        cls.empty = b / "empty"
        cls.empty.mkdir(parents=True, exist_ok=True)
        cls.csv = b / "ev.csv"
        cls.csv.write_bytes(b"t,kind,src\n2026-09-01 08:50,on,6005\n2026-09-01 18:10,off,6006\n")
        hdr = "Windows Registry Editor Version 5.00\r\n\r\n"
        cls.reg = b / "empty.reg"
        cls.reg.write_bytes(b"\xff\xfe" + hdr.encode("utf-16-le"))

    def test_clm_each_collector_rc3_r_clm_status_on_stdout(self):
        """CP §15 #9 · T-09: CLM 이면 rc 3 + R-CLM(막힘 — 원장 blocked, '0건 관측' 아님). 출력은 상태 제어 줄 하나뿐."""
        for script, src in SCRIPTS.items():
            with self.subTest(script=script):
                cp = run_clm(self.clone, script, ["-TestNow", NOW])
                self.assertEqual(cp.returncode, 3, cp.stderr.decode("utf-8", "replace")[-400:])
                lines = [ln for ln in cp.stdout.decode("utf-8").splitlines() if ln.strip()]
                self.assertEqual(len(lines), 1, lines)
                st = json.loads(lines[0])["_status"]
                self.assertLessEqual(C1_KEYS, set(st))
                self.assertEqual((st["schema"], st["src"], st["rc"], st["reasons"]),
                                 ("lm27.collector_status/1", src, 3, ["R-CLM"]))
                self.assertEqual((st["partial"], st["cap_hit"], st["budget_hit"], st["n"], st["counts"]),
                                 (False, False, False, 0, {}))
                self.assertEqual(rcmap.translate_cell(st["rc"], st["reasons"], st["counts"])["status"], "blocked")

    def _normal_runs(self):
        cfg_files = {"pc.watchFolders": [str(self.empty)], "pc.autoDiscoverFolders": False}
        yield "Get-EventActivity.ps1", ["-EventsCsv", str(self.csv), "-Now", "2026-09-02 09:00", "-Since", "2026-09-01",
                                        "-Until", "2026-09-30"], {}, None
        yield "Get-FileActivity.ps1", ["-TestNow", NOW, "-Since", "2026-09-01", "-Until", "2026-09-20", "-RecentDir",
                                       str(self.empty), "-NoToolMru"], cfg_files, None
        yield "Get-OfficeMru.ps1", ["-MruRegFile", str(self.reg), "-TestNow", NOW, "-Since", "2026-09-01", "-Until",
                                    "2026-09-30"], {}, {"APPDATA": str(self.empty)}
        yield "Get-RecentFiles.ps1", ["-RecentDir", str(self.empty), "-MruRegFile", str(self.reg), "-TestNow", NOW,
                                      "-Since", "2026-09-01", "-Until", "2026-09-30"], {}, None
        yield "Get-LicenseUsage.ps1", ["-TestNow", NOW], {"pc.license.enabled": False}, None
        yield "Add-WorkLog.ps1", ["-TestNow", NOW], None, None                      # 입력 없음 → rc 1(입력 오류)

    def test_status_line_c1_required_fields_normal_paths(self):
        """C1 — 정상·대상 없음·입력 오류 경로의 stderr 상태 줄도 필수 필드 ⊇ C1(counts 는 사전, 숫자 건수 포함)."""
        for script, args, cfg, env in self._normal_runs():
            with self.subTest(script=script):
                r = run_ps(self.clone, script, args, cfg=cfg, env=env)
                self.assertIsNotNone(r.status, r.err()[-400:])
                self.assertLessEqual(C1_KEYS, set(r.status), sorted(C1_KEYS - set(r.status)))
                self.assertEqual((r.status["schema"], r.status["src"]), ("lm27.collector_status/1", SCRIPTS[script]))
                self.assertIsInstance(r.status["counts"], dict)
                self.assertEqual(r.status["rc"], r.rc)
                for v in r.status["counts"].values():
                    self.assertTrue(isinstance(v, (int, dict)) and not isinstance(v, bool), r.status["counts"])

    def test_events_counts_carry_numbers(self):
        r = run_ps(self.clone, "Get-EventActivity.ps1", ["-EventsCsv", str(self.csv), "-Now", "2026-09-02 09:00", "-Since",
                                                         "2026-09-01", "-Until", "2026-09-30"], cfg={})
        self.assertEqual(r.rc, 0, r.err())
        self.assertEqual(r.status["counts"]["events"], 2)
        self.assertEqual(r.status["counts"]["spans"], {"L0": 1, "L1": 0})


if __name__ == "__main__":
    unittest.main()
