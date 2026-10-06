# -*- coding: utf-8 -*-
"""Get-OutlookCom.ps1 — 계정 있는 회사 PC 위험(M365 조사 .wf\\m365_research.json)의 가짜 세계 재현·회귀 시험.

실 Outlook 0: LM_OUTLOOK_SELFTEST 시험 모델(같은 스크립트 안)이 실물 COM 과 같은 모양의 폴더·항목·필터 해석을 흉내 낸다.
선택(이 파일이 쓰는 것): daslok=<g+plain+iso|none>(모델 Outlook 이 받는 DASL 날짜 형식 — 밖이면 예외 없이 0건) ·
daslshift=<분>(리터럴을 어긋나게 읽음) · stale=YYYY-MM-DD(그날 0시 뒤 메일이 OST 에 아직 없음) · syncafter=<초>(기다리면
동기화됨) · syncwait=<초>(이 수집이 띄운 Outlook 의 동기화 대기 상한) · online(캐시 모드 아님) · folders=<N> · fdelay=<ms>
(폴더 하나 여는 데 걸리는 시간) · horizon=YYYY-MM-DD(캐시 지평선) · archive(개인 데이터 파일 PST = OlExchangeStoreType 3) ·
omg(보호 멤버 자동 거부) · omghang(보호 멤버에서 경고창으로 멈춤) · omgitem(항목 단위 보호 읽기만 거부) · automig(관리자
전환 정책 DoNewOutlookAutoMigration=1) · recurleak(Restrict 가 창 앞 회차를 함께 돌려줌) · hang=attach.

근거 문서(조사 파일 areas[1].facts): DASL 날짜 형식(초 없이 — filtering-items-using-a-date-time-comparison) · Object Model
Guard 보호 목록 · Namespace.Logon · OlExchangeStoreType · 캐시 모드 동기화 범위(only-subset-items-synchronized) ·
관리자 주도 새 Outlook 전환 정책(admin-controlled-migration-policy) · Items.IncludeRecurrences.
"""
import unittest

from tests.fixtures.tree import CloneTestCase
from tests.fixtures.wp15.mailkit import ps_exe, run_ps, selftest_mail_expect

SCRIPT = "Get-OutlookCom.ps1"
NOW = ["-TestNow", "2026-10-05 09:00"]
RANGE = ["-Since", "2026-08-01", "-Until", "2026-09-30"] + NOW
B_FIELDS = ("to", "cc", "sender_addr", "sender_name", "headers_text", "body_text")
FULL = 2 * selftest_mail_expect(12)["emit"]                      # 8·9월 두 달


@unittest.skipUnless(ps_exe(), "Windows PowerShell 없음")
class ComM365Test(CloneTestCase):

    def run_com(self, selftest, *args, cfg=None, cursor=None, only="mail", rng=RANGE):
        a = ["-Only", only] + list(rng) + list(args) if only else list(rng) + list(args)
        return run_ps(self.clone, SCRIPT, a, env={"LM_OUTLOOK_SELFTEST": selftest}, cfg=cfg, cursor=cursor)

    # ── H9 DASL 날짜 리터럴 ────────────────────────────────────────────────────────────────────────────
    def test_h9_seconds_literal_silently_rejected(self):
        """초가 든 ISO 리터럴을 예외 없이 0건으로 돌려주는 Outlook — 예전에는 모든 달을 0건 done 으로 굳혔다(rc 1)."""
        r = self.run_com("12,daslok=g+plain")
        self.assertEqual(r.rc, 0, r.err_text)
        res = r.result("mail.com")
        self.assertEqual(len(r.records), FULL)
        self.assertEqual(res["counts"]["filter_canary"], "ok")
        self.assertIn(res["counts"]["filter_fmt"], ("g", "plain"))
        self.assertEqual(r.cursor["cov_months"]["2026-09"]["status"], "done")

    def test_h9_canary_picks_the_working_format(self):
        r = self.run_com("12,daslok=iso")
        self.assertEqual(r.rc, 0, r.err_text)
        self.assertEqual(r.result("mail.com")["counts"]["filter_fmt"], "iso")
        self.assertEqual(len(r.records), FULL)

    def test_h9_no_working_format_is_not_zero(self):
        """어떤 형식도 맞지 않으면 0건을 '그 달 없음'으로 굳히지 않는다 — rc 3 + R-TRANSPORT, done 달 0."""
        r = self.run_com("12,daslok=none")
        self.assertEqual(r.rc, 3, r.err_text)
        res = r.result("mail.com")
        self.assertIn("R-TRANSPORT", res["reasons"])
        self.assertEqual(res["counts"]["filter_canary"], "fail")
        self.assertEqual(r.records, [])
        months = (r.cursor or {}).get("cov_months") or {}
        self.assertFalse([k for k, v in months.items() if v.get("status") == "done"])

    def test_h9_calendar_falls_back_to_jet(self):
        r = self.run_com("12,daslok=none", only="cal")
        self.assertEqual(r.rc, 0, r.err_text)
        self.assertTrue(r.records)                                          # Jet(로컬 'g')이 단발·반복 모두
        self.assertEqual(r.result("cal.com")["counts"]["filter_canary"], "fail")

    def test_h9_shifted_literal_holds_month(self):
        """리터럴을 1분 어긋나게 읽는 Outlook — 범위 밖 행은 버리고 그 달은 done 으로 적지 않는다(다음 실행이 다시 읽음)."""
        r = self.run_com("12,daslshift=-1")
        self.assertEqual(r.rc, 0, r.err_text)
        res = r.result("mail.com")
        self.assertGreater(res["counts"]["filter_mismatch"], 0)
        held = [k for k in ("2026-08", "2026-09") if k not in r.cursor["cov_months"]]
        self.assertTrue(held)
        self.assertTrue(all("2026-07-31T15:00:00Z" <= x["ts_utc"] < "2026-09-30T15:00:00Z" for x in r.records))

    # ── H10 낡은 OST ──────────────────────────────────────────────────────────────────────────────────
    def test_h10_stale_ost_months_not_done(self):
        """OST 가 9월 15일에 멈춤(새 Outlook 전환·Outlook 꺼짐) — 예전에는 9월을 done 으로 굳혀 OWA 백필이 배정되지 않았다."""
        r = self.run_com("12,stale=2026-09-15")
        self.assertEqual(r.rc, 0, r.err_text)
        res = r.result("mail.com")
        self.assertIn("R-STALE", res["reasons"])
        self.assertTrue("2026-09-01" <= res["horizon_newest"] < "2026-09-15", res["horizon_newest"])
        self.assertGreater(res["counts"]["newest_age_h"], 72)
        cm = r.cursor["cov_months"]
        self.assertEqual(cm["2026-08"]["status"], "done")
        self.assertNotIn("2026-09", cm)                                    # 원장이 9/15 뒤 0건 날을 미관측으로

    def test_h10_stale_threshold_from_cfg(self):
        self.assertIn("R-STALE", self.run_com("6,stale=2026-09-28").result("mail.com")["reasons"])
        r = self.run_com("6,stale=2026-09-28", cfg={"probe.ostStaleH": 400})
        self.assertNotIn("R-STALE", r.result("mail.com")["reasons"])

    def test_h10_started_outlook_waits_for_sync(self):
        r = self.run_com("12,notrunning,stale=2026-09-15,syncafter=2")
        self.assertEqual(r.rc, 0, r.err_text)
        res = r.result("mail.com")
        self.assertNotIn("R-STALE", res["reasons"])
        self.assertGreaterEqual(res["counts"]["sync_wait_s"], 2)
        self.assertEqual(r.cursor["cov_months"]["2026-09"]["status"], "done")
        self.assertTrue(res["counts"]["started_outlook"])

    def test_h10_started_outlook_gives_up(self):
        r = self.run_com("12,notrunning,stale=2026-09-15,syncwait=2")
        res = r.result("mail.com")
        self.assertIn("R-STALE", res["reasons"])
        self.assertNotIn("2026-09", r.cursor["cov_months"])

    def test_h10_online_mode_is_not_stale(self):
        self.assertNotIn("R-STALE", self.run_com("12,online,stale=2026-09-15").result("mail.com")["reasons"])

    # ── M15 지평선이 걸친 달 ──────────────────────────────────────────────────────────────────────────
    def test_m15_horizon_inside_month_not_done(self):
        r = self.run_com("12,horizon=2026-08-20")
        self.assertEqual(r.rc, 0, r.err_text)
        res = r.result("mail.com")
        self.assertIn("R-HORIZON", res["reasons"])
        self.assertGreaterEqual(res["horizon_oldest"], "2026-08-20")
        self.assertNotIn("2026-08", r.cursor["cov_months"])                # 지평선 앞 8월 날은 원장이 out_of_horizon
        self.assertEqual(r.cursor["cov_months"]["2026-09"]["status"], "done")
        self.assertEqual(res["counts"]["horizon_month"], "2026-08")

    # ── M14 폴더 열거 하트비트 ────────────────────────────────────────────────────────────────────────
    def test_m14_many_slow_folders_keep_heartbeat(self):
        r = self.run_com("12,folders=300,fdelay=40", "-WatchdogSec", "5")
        self.assertEqual(r.rc, 0, r.err_text)
        self.assertEqual(len(r.records), FULL)

    def test_m14_folder_cap(self):
        r = self.run_com("3,folders=3100")
        self.assertEqual(r.rc, 0, r.err_text)
        self.assertTrue(r.result("mail.com")["counts"]["folders_capped"])

    # ── M16 PST(olNotExchange) ────────────────────────────────────────────────────────────────────────
    def test_m16_pst_store_never_read_as_archive(self):
        r = self.run_com("12,archive", cfg={"mail.includeArchiveStore": True})
        self.assertEqual(r.rc, 0, r.err_text)
        self.assertFalse(any(x["folder_role"] == "archive" for x in r.records))
        self.assertFalse(any("[arch]" in x["subject"] for x in r.records))
        c = r.result("mail.com")["counts"]
        self.assertEqual(c["stores_non_exchange"], 1)
        self.assertEqual(c["archive_store"], "unverified")

    # ── H6 · M17 보호 멤버 · B단 카나리아 ──────────────────────────────────────────────────────────────
    def test_h6_b_off_never_touches_protected_members(self):
        r = self.run_com("12,omghang")                                     # 보호 멤버를 건드리면 1시간 멈추는 Outlook
        self.assertEqual(r.rc, 0, r.err_text)
        self.assertLess(r.elapsed, 60)
        res = r.result("mail.com")
        self.assertNotIn("R-OMG", res["reasons"])
        self.assertEqual(r.meta["my_addrs"], ["gildong.hong@corp.example"])   # 계정 표시 이름(비보호)에서
        self.assertEqual(len(r.records), FULL)

    def test_m17_b_canary_timeout_relaunches_without_b(self):
        r = self.run_com("12,omghang", "-ReadProtected", "1")
        self.assertEqual(r.rc, 0, r.err_text)
        self.assertLess(r.elapsed, 90)
        res = r.result("mail.com")
        self.assertIn("R-OMG", res["reasons"])
        self.assertEqual(res["counts"]["omg_canary"], "timeout")
        self.assertFalse(res["counts"]["protected_read"])
        self.assertEqual(len(r.records), FULL)
        self.assertTrue(all(b not in x for x in r.records for b in B_FIELDS))
        self.assertEqual(sum(1 for x in r.lines if "_meta" in x), 1)

    def test_m17_b_canary_denied(self):
        r = self.run_com("12,omg", "-ReadProtected", "1")
        self.assertEqual(r.rc, 0, r.err_text)
        res = r.result("mail.com")
        self.assertIn("R-OMG", res["reasons"])
        self.assertEqual(res["counts"]["omg_canary"], "denied")
        self.assertTrue(all(b not in x for x in r.records for b in B_FIELDS))

    # ── H8 · L6 붙기 세부 단계 ────────────────────────────────────────────────────────────────────────
    def test_l6_attach_step_recorded(self):
        r = self.run_com("12,hang=attach", "-WatchdogSec", "3")
        self.assertEqual(r.rc, 3)
        c = r.result("mail.com")["counts"]
        self.assertEqual(c["attach_step"], "attach:inbox")
        self.assertTrue(c["watchdog"])

    # ── M13 관리자 전환 정책 ──────────────────────────────────────────────────────────────────────────
    def test_m13_auto_migration_does_not_launch_classic(self):
        r = self.run_com("12,notrunning,automig")
        self.assertEqual(r.rc, 3)
        res = r.result("mail.com")
        self.assertEqual(res["reasons"], ["R-NEWOL"])
        self.assertEqual(res["counts"]["attach"], "skipped")
        self.assertEqual(res["counts"]["migration_auto"], 1)
        self.assertEqual(r.records, [])
        ok = self.run_com("12,automig")                                    # 이미 떠 있는 클래식에는 붙는다
        self.assertEqual(ok.rc, 0, ok.err_text)

    # ── L5 일정 회차 ─────────────────────────────────────────────────────────────────────────────────
    def test_l5_no_occurrence_before_window(self):
        r = self.run_com("12,recurleak", only="cal")
        self.assertEqual(r.rc, 0, r.err_text)
        early = [x for x in r.records if x["end_utc"] <= "2026-07-31T15:00:00Z"]   # 8월 1일 0시(KST) 전에 끝난 회차
        self.assertEqual(early, [])
        self.assertGreater(r.result("cal.com")["counts"]["cal_out_of_range"], 0)


if __name__ == "__main__":
    unittest.main()
