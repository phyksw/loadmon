# -*- coding: utf-8 -*-
"""WP-14 pc.compute 라이선스(옵트인)·manual 수동 기록 수집기 시험 — collect\\Get-LicenseUsage.ps1 · Add-WorkLog.ps1.

라이선스: 가짜 lmutil(복제 안 .cmd — 합성 lmstat 출력을 그대로 낸다)과 자리표시자 계정·호스트(환경 변수)로만 돌린다(실제 라이선스
서버 접속 없음). 본인 사용자·본인 호스트 행만(X-146), 원시에 user·host·server 없음(P §10.2), app_id 는 카탈로그 slug(X-071).
수동 기록: 원시 레코드 한 줄 + _cursor(X-300), 입력 오류는 rc 1 · 아무것도 내지 않음, 디스크 쓰기 0(이전 판 CSV 폐지).
"""
import unittest
from datetime import UTC, datetime

from lm27 import catalog
from tests.fixtures.tree import CloneTestCase
from tests.fixtures.wp14.runner import FORBIDDEN_RAW, run_ps, snapshot

LMSTAT = "\r\n".join([
    "lmutil - Copyright (c) 1989-2023 Flexera. All Rights Reserved.",
    "Flexible License Manager status on Mon 9/7/2026 16:00",
    "License server status: 1055@licsrv.example",
    "Users of elec_solve_hfss:  (Total of 4 licenses issued;  Total of 2 licenses in use)",
    "",
    '  "elec_solve_hfss" v2024.0512, vendor: ansyslmd, expiry: permanent(no expiration date)',
    "  floating license",
    "",
    "    tester01 PCEXAMPLE01 PCEXAMPLE01 (v2024.0512) (licsrv.example/1055 1234), start Mon 9/7 9:05",
    "    tester02 PCEXAMPLE02 PCEXAMPLE02 (v2024.0512) (licsrv.example/1055 2201), start Mon 9/7 10:15",
    "    tester01 PCEXAMPLE09 PCEXAMPLE09 (v2024.0512) (licsrv.example/1055 2202), start Mon 9/7 10:20",
    "",
    "Users of acfd_solver:  (Total of 2 licenses issued;  Total of 1 license in use)",
    "",
    "    tester01 PCEXAMPLE01 PCEXAMPLE01 (v2024.0512) (licsrv.example/1055 1301), start Tue 9/8 14:30, 4 licenses",
    "",
    "Users of zz_custom_feature:  (Total of 1 license issued;  Total of 1 license in use)",
    "",
    "    tester01 PCEXAMPLE01 PCEXAMPLE01 (v1.0) (licsrv.example/1055 1401), start Tue 9/8 15:00",
    "",
]) + "\r\n"
ME = {"USERNAME": "tester01", "COMPUTERNAME": "PCEXAMPLE01"}


def iso_local(s: str) -> str:
    return datetime.strptime(s, "%Y-%m-%d %H:%M").astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class LicenseTest(CloneTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        d = cls.clone.temp / "wp14_lic"
        d.mkdir(parents=True, exist_ok=True)
        (d / "lmstat.txt").write_bytes(LMSTAT.encode("ascii"))
        cls.lmutil = d / "lmutil.cmd"
        cls.lmutil.write_bytes(b'@echo off\r\ntype "%~dp0lmstat.txt"\r\n')
        cls.fail = d / "lmfail.cmd"
        cls.fail.write_bytes(b"@echo off\r\nexit /b 1\r\n")
        cls.dir = d

    def cfg(self, **kw):
        c = {"pc.license.enabled": True, "pc.license.lmutilPath": str(self.lmutil), "pc.license.servers": ["1055@licsrv.example"]}
        c.update(kw)
        return c

    def run_lic(self, cfg, env=None):
        r = run_ps(self.clone, "Get-LicenseUsage.ps1", ["-TestNow", "2026-09-08 16:00"], cfg=cfg, env={**ME, **(env or {})})
        self.assertIsNotNone(r.status, r.err())
        for rec in r.records:
            self.assertFalse(set(rec) & FORBIDDEN_RAW, rec)
            self.assertEqual(set(rec), {"app_id", "ts_utc", "ts_end", "ts_local_offset", "ts_precision", "observed_at",
                                        "confidence", "flags"})
            self.assertTrue(catalog.APP_ID_RX.match(rec["app_id"]), rec["app_id"])
            self.assertEqual(rec["flags"], {"license": True, "end_uncertain": True})
        return r

    def test_own_rows_only(self):
        r = self.run_lic(self.cfg())
        self.assertEqual(r.rc, 0, r.status)
        got = [(x["app_id"], x["ts_utc"]) for x in r.records]
        self.assertEqual(got, [("ansys_electronics_desktop", iso_local("2026-09-07 09:05")),
                               ("ansys_fluent", iso_local("2026-09-08 14:30")),
                               ("unknown:lic_zz_custom_feature", iso_local("2026-09-08 15:00"))])
        self.assertEqual(r.status["others_excluded"], 2)                    # 동료 행 · 내 계정의 다른 호스트 행
        for x in r.records:
            self.assertEqual(x["ts_end"], iso_local("2026-09-08 16:00"))
        known = {e.app_id for e in catalog.entries()}
        self.assertIn("ansys_electronics_desktop", known)
        self.assertIn("ansys_fluent", known)
        out = r.stdout.decode("utf-8")
        for bad in ("tester02", "PCEXAMPLE", "licsrv"):
            self.assertNotIn(bad, out)

    def test_not_configured_or_disabled_rc1(self):
        for cfg in (self.cfg(**{"pc.license.servers": []}), self.cfg(**{"pc.license.lmutilPath": ""}),
                    self.cfg(**{"pc.license.enabled": False})):
            r = self.run_lic(cfg)
            self.assertEqual((r.rc, r.records), (1, []))
            self.assertFalse(r.status["configured"])

    def test_missing_lmutil_rc3(self):
        r = self.run_lic(self.cfg(**{"pc.license.lmutilPath": str(self.dir / "없는.exe")}))
        self.assertEqual(r.rc, 3)
        self.assertEqual(r.status["reasons"], ["R-TRANSPORT"])

    def test_server_failure_rc3(self):
        r = self.run_lic(self.cfg(**{"pc.license.lmutilPath": str(self.fail)}))
        self.assertEqual(r.rc, 3)
        self.assertEqual(r.status["servers_failed"], 1)

    def test_other_user_sees_nothing(self):
        r = self.run_lic(self.cfg(), env={"USERNAME": "tester03"})
        self.assertEqual((r.rc, r.records), (1, []))


class WorkLogTest(CloneTestCase):
    KEYS = {"category", "hours", "date", "start", "end", "note", "entity", "project_id", "role_field", "role_func",
            "man_kind", "ref_keys", "retract_of", "ts_local_offset", "observed_at", "confidence"}

    def wl(self, *args):
        return run_ps(self.clone, "Add-WorkLog.ps1", [*args, "-TestNow", "2026-09-10 18:00"])

    def test_interval_record(self):
        r = self.wl("-Category", "현장 지원", "-Hours", "2", "-Date", "2026-09-10", "-Start", "13:00", "-End", "15:00",
                    "-Note", "고객사A 방문 시험 지원", "-Entity", "과제A", "-Kind", "offsite", "-ProjectId", "P-0003",
                    "-RoleField", "ELEC", "-RoleFunc", "TEST")
        self.assertEqual(r.rc, 0, r.err())
        self.assertEqual(len(r.records), 1)
        rec = r.records[0]
        self.assertEqual(set(rec), self.KEYS)
        self.assertEqual((rec["category"], rec["hours"], rec["date"], rec["start"], rec["end"]),
                         ("현장 지원", 2.0, "2026-09-10", "13:00", "15:00"))
        self.assertEqual((rec["man_kind"], rec["project_id"], rec["role_field"], rec["role_func"]),
                         ("offsite", "P-0003", "ELEC", "TEST"))
        self.assertEqual(rec["note"], "고객사A 방문 시험 지원")                    # 원문은 파이프로만(정제기가 text_masked)
        self.assertEqual(rec["observed_at"], iso_local("2026-09-10 18:00"))
        self.assertEqual(r.cursor, {"last_ts_utc": iso_local("2026-09-10 18:00")})
        self.assertFalse(set(rec) & FORBIDDEN_RAW)

    def test_date_only_defaults(self):
        r = self.wl("-Category", "교육", "-Hours", "1.5")
        rec = r.records[0]
        self.assertEqual((rec["date"], rec["start"], rec["end"], rec["man_kind"]), ("2026-09-10", None, None, "work"))
        self.assertEqual(rec["hours"], 1.5)

    def test_invalid_inputs_emit_nothing(self):
        cases = [(("-Category", "", "-Hours", "1"), "category"), (("-Category", "교육", "-Hours", "25"), "hours"),
                 (("-Category", "교육", "-Hours", "1", "-Date", "9/10"), "date"),
                 (("-Category", "교육", "-Hours", "1", "-Start", "13:00"), "start_end"),
                 (("-Category", "교육", "-Hours", "1", "-Start", "15:00", "-End", "13:00"), "start_end"),
                 (("-Category", "교육", "-Hours", "1", "-Kind", "holiday"), "kind"),
                 (("-Category", "교육", "-Hours", "1", "-ProjectId", "과제A 코드"), "project_id")]
        for args, field in cases:
            r = self.wl(*args)
            self.assertEqual(r.rc, 1, args)
            self.assertEqual(r.stdout, b"", args)
            self.assertIn(field, r.status["invalid"], args)

    def test_no_disk_writes(self):
        before = snapshot(self.clone.root)
        self.wl("-Category", "교육", "-Hours", "1")
        after = snapshot(self.clone.root)
        self.assertEqual({k: v for k, v in after.items() if not k.startswith("_sandbox")},
                         {k: v for k, v in before.items() if not k.startswith("_sandbox")})


if __name__ == "__main__":
    unittest.main()
