# -*- coding: utf-8 -*-
"""WP-15 Get-OutlookCom.ps1(mail.com · cal.com) 시험 — %TEMP% 복제 트리에서 LM_OUTLOOK_SELFTEST 주입점만으로(실 Outlook 0).

CM §15 의 수집기 측 단언: CM-1(새 Outlook) · 2(프로필 0·마법사 — New-Object 미호출, 20초 안) · 3(폴더 재귀·역할 태그·
subfolder_ratio) · 4(보관 사서함 설정) · 7(OMG — B단 생략, A단 행 유지, R-OMG) · 8(DASL ISO·R-CLM) · 10(상한 → partial·R-CAP) ·
13(회의 응답 발신 능동 신호) · 14(헤더 단서 전달) · 15(사적 표시 원시 전달) · 16(UTC·오프셋 정합) · 20(내 주소 미확정).
계약 §7.3(stdin _in · 첫 줄 _meta · 끝 줄 _cursor) · §8.1(rc) · X-300 · L-09(디스크 쓰기 0).
"""
import re
import unittest
from datetime import datetime

from lm27.util import tz
from tests.fixtures.tree import CloneTestCase
from tests.fixtures.wp15.mailkit import (CAL_FLAGS, CAL_RAW, FORBIDDEN_RAW, MAIL_FLAGS, MAIL_RAW, OFF_RX, UTC_RX, ps_exe,
                                         run_ps, selftest_mail_expect, tree_snapshot)

SCRIPT = "Get-OutlookCom.ps1"
RANGE = ["-Since", "2026-08-01", "-Until", "2026-09-30", "-TestNow", "2026-10-05 09:00"]
B_FIELDS = ("to", "cc", "sender_addr", "sender_name", "headers_text", "body_text")


@unittest.skipUnless(ps_exe(), "Windows PowerShell 없음")
class MailComTest(CloneTestCase):
    """한 복제 트리에서 수집기를 여러 번 돌린다(시나리오마다 자식 PowerShell 2개)."""

    def run_com(self, selftest, *args, cfg=None, cursor=None, stdin=True, only="mail", rng=RANGE):
        a = list(rng) + list(args)
        if only is not None:
            a = ["-Only", only] + a
        return run_ps(self.clone, SCRIPT, a, env={"LM_OUTLOOK_SELFTEST": selftest}, cfg=cfg, cursor=cursor, stdin=stdin)

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.base = None
        cls.prot = None

    def basic(self):
        if MailComTest.base is None:
            MailComTest.base = self.run_com("12")
        return MailComTest.base

    def protected(self):
        """B단(ReadProtected 1) 실행 1회 — 앞뒤 복제 트리 스냅숏과 함께(쓰기 0 검사 공용)."""
        if MailComTest.prot is None:
            before = tree_snapshot(self.clone.root)
            r = self.run_com("12", "-ReadProtected", "1")
            MailComTest.prot = (r, before, tree_snapshot(self.clone.root))
        return MailComTest.prot

    # ── CM-3 · 계약 §7.3 · P §10.2 ────────────────────────────────────────────────────────────────
    def test_cm03_recursive_folders_roles_and_output_shape(self):
        r = self.basic()
        self.assertEqual(r.rc, 0, r.err_text)
        ls = r.lines
        self.assertIn("_meta", ls[0])
        self.assertEqual(ls[0]["_meta"]["my_addrs"], ["gildong.hong@corp.example"])
        self.assertIn("_cursor", ls[-1])
        recs = r.records
        exp = selftest_mail_expect(12)
        self.assertEqual(len(recs), 2 * exp["emit"])                       # 8·9월 두 달
        subj = " ".join(x["subject"] for x in recs)
        for k in ("[inbox]", "[rules]", "[sent]", "[project]"):
            self.assertIn(k, subj)                                         # 하위·규칙·사용자 폴더까지 재귀(LM24 결함 수정)
        for k in ("[deleted]", "[junk]", "[drafts]", "[outbox]"):
            self.assertNotIn(k, subj)                                      # 지운·정크·임시 보관·보낼 편지함 제외(X-067)
        roles = {x["folder_role"] for x in recs}
        self.assertLessEqual(roles, {"inbox", "sent", "subfolder"})
        self.assertIn("subfolder", roles)
        for x in recs:
            self.assertLessEqual(set(x), MAIL_RAW, x.keys())
            self.assertFalse(set(x) & FORBIDDEN_RAW)
            self.assertNotIn("_kind", x)                                   # kind 단일 모드에는 라우팅 표지 없음
            self.assertEqual(x["box"], "sent" if "[sent]" in x["subject"] else "inbox")
            self.assertLessEqual(set(x.get("flags", {})), MAIL_FLAGS)
            for b in B_FIELDS:
                self.assertNotIn(b, x)                                     # ReadProtected 0 → B단 생략(CM §5.4)
        res = r.result("mail.com")
        self.assertEqual(res["items_ok"], len(recs))
        self.assertAlmostEqual(res["subfolder_ratio"], 0.3)
        # 지운·정크·임시 보관·보낼 편지함 4 + '대화 기록'(IM 대화록 — CM §5.3, W1 통합 창 결함 수정) 1
        self.assertEqual(res["counts"]["excluded_folders"], 5)
        self.assertFalse(res["counts"]["protected_read"])
        # 계약 v1.2 §0.7 C1 — 상태 줄 한 모양(_status): 필수 필드 + n = 새 레코드 수
        self.assertLessEqual({"schema", "src", "rc", "reasons", "partial", "cap_hit", "budget_hit", "n", "counts"}, set(res))
        self.assertEqual((res["schema"], res["partial"], res["n"]), ("lm27.collector_status/1", False, res["new"]))

    def test_conversation_history_and_im_classes_excluded(self):
        """W1 통합 창 결함 회귀(CM §5.3): '대화 기록' 폴더(이름으로)와 IM 대화록 클래스 IPM.Note.Microsoft.Conversation·
        Missed(언어 무관 — 클래스로)는 메일로 읽지 않는다. 이전에는 대화 기록 폴더가 subfolder 로 수집됐다."""
        r = self.basic()
        subj = " ".join(x["subject"] for x in r.records)
        self.assertNotIn("[convhist]", subj)
        self.assertNotIn("selftest im", subj)
        self.assertGreaterEqual(r.result("mail.com")["counts"]["skipped_class"], 2)   # 월마다 IM 클래스 1건 이상

    def test_sent_rows_first_within_each_month(self):
        recs = self.basic().records
        months = {}
        for x in recs:
            months.setdefault(x["ts_utc"][:7], []).append(x["box"])
        for seq in months.values():
            if "sent" in seq and "inbox" in seq:
                self.assertLess(max(i for i, b in enumerate(seq) if b == "sent"), seq.index("inbox"))

    def test_cm16_timestamps_offsets_precision(self):
        for x in self.basic().records:
            self.assertRegex(x["ts_utc"], UTC_RX)
            self.assertRegex(x["ts_local_offset"], OFF_RX)
            self.assertEqual(x["ts_local_offset"], tz.fmt_offset(tz.capture_offset_min(x["ts_utc"])))
            self.assertEqual(x["ts_precision"], "minute")
            self.assertIsInstance(x["confidence"], float)
            self.assertRegex(x["observed_at"], UTC_RX)
            self.assertLess(datetime.fromisoformat(x["ts_utc"][:-1]), datetime(2026, 10, 1))

    def test_cm13_meeting_response_is_active_signal(self):
        recs = self.basic().records
        resp = [x for x in recs if x.get("flags", {}).get("meeting_response")]
        self.assertTrue(resp)
        self.assertTrue(all(x["box"] == "sent" for x in resp))
        self.assertEqual(self.basic().result("mail.com")["counts"]["meeting_response"], len(resp))

    def test_cm15_sensitivity_categories_and_attachments_pass_through(self):
        recs = self.basic().records
        self.assertTrue(any(x["sensitivity"] == 2 for x in recs))
        self.assertTrue(any(x["categories"] == ["개인"] for x in recs))
        att = [x for x in recs if x.get("attach_names")]
        self.assertTrue(att)
        self.assertTrue(all(x["has_attach"] for x in att))

    def test_cursor_shape_and_rerun_rc4(self):
        r = self.basic()
        c = r.cursor
        self.assertEqual(set(c), {"box", "cov_months"})
        for b in ("inbox", "sent", "other"):
            self.assertIn("last_ts_utc", c["box"][b])
            self.assertIsNone(c["box"][b]["last_msg_key"])                 # HMAC 은 파이프가 채운다(계약 §3.10)
        self.assertEqual(c["cov_months"]["2026-09"]["status"], "done")
        self.assertEqual(c["cov_months"]["2026-08"]["status"], "done")
        r2 = self.run_com("12", cursor=c)
        self.assertEqual(r2.rc, 4, r2.err_text)                            # 읽었지만 새것 0
        self.assertEqual(r2.records, [])
        self.assertEqual(r2.result("mail.com")["counts"]["months_skipped"], 2)

    def test_status_range_and_default_window(self):
        """W2 검토 C03(V6): 상태 줄 range = 이번에 맡은 창. -Since 가 없으면 collect.lookbackDays(오늘 포함 n 일) — 89일 고정 아님."""
        self.assertEqual(self.basic().result("mail.com")["range"], ["2026-08-01", "2026-09-30"])
        r = self.run_com("3", rng=["-TestNow", "2026-10-05 09:00"], cfg={"collect.lookbackDays": 20})
        self.assertEqual(r.result("mail.com")["range"], ["2026-09-16", "2026-10-05"])

    # ── CM-14 · CM-7 ──────────────────────────────────────────────────────────────────────────────
    def test_cm14_b_stage_passes_header_and_recipient_clues(self):
        r = self.protected()[0]
        self.assertEqual(r.rc, 0, r.err_text)
        recs = r.records
        self.assertTrue(all(isinstance(x.get("to"), list) and isinstance(x.get("cc"), list) for x in recs))
        self.assertTrue(any("List-Unsubscribe" in x.get("headers_text", "") for x in recs))
        self.assertTrue(all(x.get("body_text") for x in recs))
        for x in recs:
            for p in x["to"] + x["cc"]:
                self.assertEqual(set(p), {"addr", "name"})
                self.assertEqual(p["addr"], p["addr"].lower())
        self.assertTrue(r.result("mail.com")["counts"]["protected_read"])

    def test_cm14_read_protected_from_cfg(self):
        r = self.run_com("12", cfg={"mail.com.readProtected": "1"})
        self.assertTrue(all("to" in x for x in r.records))
        r0 = self.run_com("12", cfg={"mail.com.readProtected": "auto"})     # auto 는 연결자가 정한다 — 못 받으면 0
        self.assertTrue(all("to" not in x for x in r0.records))

    def test_cm07_omg_keeps_a_rows(self):
        # 항목 단위 B단만 거부(omgitem — 카나리아인 내 주소 읽기는 됨): 연속 3회 거부면 B단을 멈추고 A단 행은 그대로.
        # 보호 멤버 전체 거부(omg)는 B단 카나리아에서 걸린다 — test_mail_com_m365(M17)
        r = self.run_com("12,omgitem", "-ReadProtected", "1")
        self.assertEqual(r.rc, 0, r.err_text)
        res = r.result("mail.com")
        self.assertIn("R-OMG", res["reasons"])
        self.assertEqual(len(r.records), 2 * selftest_mail_expect(12)["emit"])   # 행 폐기 0
        self.assertTrue(all("to" not in x for x in r.records))
        self.assertGreaterEqual(res["counts"]["protected_fail"], 1)
        self.assertNotIn("omg_canary", res["counts"])

    def test_cm07_slow_protected_read_stops_b_stage(self):
        r = self.run_com("12,slowb", "-ReadProtected", "1")
        res = r.result("mail.com")
        self.assertIn("R-OMG", res["reasons"])
        self.assertTrue(res["counts"].get("omg_slow"))
        self.assertEqual(len(r.records), 2 * selftest_mail_expect(12)["emit"])

    # ── CM-10 · 예산 ─────────────────────────────────────────────────────────────────────────────
    def test_cm10_cap_is_partial_not_silent(self):
        r = self.run_com("120", cfg={"mail.com.capMail": 100})
        self.assertEqual(r.rc, 0, r.err_text)
        res = r.result("mail.com")
        self.assertTrue(res["cap_hit"])
        self.assertIn("R-CAP", res["reasons"])
        self.assertEqual(len(r.records), 100)
        self.assertNotEqual(r.cursor["cov_months"].get("2026-08", {}).get("status"), "done")

    def test_budget_partial_then_resume_without_loss(self):
        r1 = self.run_com("40,delay=100", "-BudgetSec", "4")
        self.assertEqual(r1.rc, 0, r1.err_text)
        res = r1.result("mail.com")
        self.assertTrue(res["budget_hit"])
        self.assertIn("R-BUDGET", res["reasons"])
        self.assertNotEqual(r1.cursor["cov_months"].get("2026-09", {}).get("status"), "done")
        r2 = self.run_com("40", "-BudgetSec", "120", cursor=r1.cursor)
        self.assertEqual(r2.rc, 0, r2.err_text)
        self.assertEqual(r2.cursor["cov_months"]["2026-09"]["status"], "done")
        self.assertEqual(r2.cursor["cov_months"]["2026-08"]["status"], "done")
        got = {x["internet_message_id"] for x in r1.records + r2.records}
        full = {x["internet_message_id"] for x in self.run_com("40", "-BudgetSec", "120").records}
        self.assertEqual(got, full)                                        # 이어 읽기로 빠짐 0

    # ── CM-1 · CM-2 · 워치독 ─────────────────────────────────────────────────────────────────────
    def test_cm01_new_outlook_blocked(self):
        r = self.run_com("12,newol")
        self.assertEqual(r.rc, 3)
        res = r.result("mail.com")
        self.assertEqual(res["reasons"], ["R-NEWOL"])
        self.assertEqual(res["counts"]["attach"], "skipped")
        self.assertEqual(r.records, [])

    def test_cm02_no_profile_and_wizard_skip_fast(self):
        for opt, code in (("noprof", "R-NOPROF"), ("wizard", "R-WIZARD")):
            r = self.run_com("12," + opt)
            self.assertEqual(r.rc, 3)
            res = r.result("mail.com")
            self.assertEqual(res["reasons"], [code])
            self.assertEqual(res["counts"]["attach"], "skipped")            # 자식(COM)을 띄우지 않음 = New-Object 미호출
            self.assertLess(r.elapsed, 20)

    def test_watchdog_kills_hung_attach(self):
        r = self.run_com("12,hang=attach", "-WatchdogSec", "3")
        self.assertEqual(r.rc, 3)
        res = r.result("mail.com")
        self.assertEqual(res["reasons"], ["R-DIALOG"])
        self.assertTrue(res["counts"]["watchdog"])
        self.assertLess(r.elapsed, 20)
        r2 = self.run_com("12,hang=attach,notrunning", "-WatchdogSec", "3")
        self.assertEqual(r2.result("mail.com")["reasons"], ["R-WIZARD"])

    def test_watchdog_hung_read_keeps_progress(self):
        # 워치독 8초(W1 통합 창 — 부하 민감 시험 보정): 3초면 기기 부하로 자식 PowerShell 이 첫 줄(붙기 단계)을 내기 전에
        # 워치독이 먼저 터져 'attach' 단계(R-DIALOG)로 판정됐다. 읽기 중 무응답은 여전히 워치독이 끊는다(무한 대기 가짜).
        r = self.run_com("12,hang=read", "-WatchdogSec", "8")
        self.assertEqual(r.rc, 3)
        res = r.result("mail.com")
        self.assertIn("R-TRANSPORT", res["reasons"])
        self.assertEqual(res["counts"]["phase"], "read")
        self.assertGreater(len(r.records), 0)
        self.assertEqual(res["items_ok"], len(r.records))
        self.assertEqual(r.cursor["cov_months"]["2026-09"]["status"], "done")   # 끝낸 달의 진행은 남는다

    def test_attach_failure_reasons(self):
        for opt, code in (("dialog", "R-DIALOG"), ("elev", "R-ELEV"), ("busyall", "R-COM-BUSY")):
            r = self.run_com("12," + opt)
            self.assertEqual(r.rc, 3)
            self.assertEqual(r.result("mail.com")["reasons"], [code])
            self.assertEqual(r.records, [])

    def test_cm08_clm_is_blocked_rc3(self):
        cmd = "$ExecutionContext.SessionState.LanguageMode='ConstrainedLanguage'; & '@SCRIPT@' -Only mail; exit $LASTEXITCODE"
        r = run_ps(self.clone, SCRIPT, [], env={"LM_OUTLOOK_SELFTEST": "3"}, stdin=False, command=cmd)
        self.assertEqual(r.rc, 3)
        self.assertEqual(r.result("mail.com")["reasons"], ["R-CLM"])

    # ── CM-20 · 지평선 · 보관 사서함 ──────────────────────────────────────────────────────────────
    def test_cm20_unknown_address(self):
        r = self.run_com("12,noaddr")
        self.assertEqual(r.rc, 0, r.err_text)
        self.assertEqual(r.meta["my_addrs"], [])
        self.assertIn("R-NOADDR", r.result("mail.com")["reasons"])
        self.assertEqual(len(r.records), 2 * selftest_mail_expect(12)["emit"])   # bulk 로 버리지 않는다
        r2 = self.run_com("12,noaddr", cfg={"collect.ownerAddress": "Owner@Corp.Example"})
        self.assertEqual(r2.meta["my_addrs"], ["owner@corp.example"])
        self.assertNotIn("R-NOADDR", r2.result("mail.com")["reasons"])

    def test_horizon_months_are_not_zero(self):
        r = self.run_com("12,horizon=2026-09")
        self.assertEqual(r.rc, 0, r.err_text)
        res = r.result("mail.com")
        self.assertIn("R-HORIZON", res["reasons"])
        self.assertRegex(res["horizon_oldest"], r"^2026-09-\d{2}$")
        self.assertEqual(r.cursor["cov_months"]["2026-08"]["status"], "out_of_horizon")
        self.assertFalse(any(x["ts_utc"].startswith("2026-08") for x in r.records))

    def test_cm04_archive_store_toggle(self):
        # M365 조사 M16: OlExchangeStoreType 3 = olNotExchange(PST·IMAP 개인 데이터 파일) — 보관 사서함이 아니다. 보관 사서함
        # 식별은 회사 PC 실측 전까지 미정이라 설정을 켜도 기본 사서함만 읽고 counts.archive_store=unverified 로 알린다
        on = self.run_com("12,archive", cfg={"mail.includeArchiveStore": True})
        off = self.run_com("12,archive", cfg={"mail.includeArchiveStore": False})
        for r in (on, off):
            self.assertEqual(r.rc, 0, r.err_text)
            self.assertFalse(any(x["folder_role"] == "archive" for x in r.records))
            self.assertEqual(r.result("mail.com")["counts"]["stores_non_exchange"], 1)
        self.assertEqual(len(on.records), len(off.records))
        self.assertEqual(on.result("mail.com")["counts"]["archive_store"], "unverified")
        self.assertNotIn("archive_store", off.result("mail.com")["counts"])

    def test_subfolder_ratio_warning_from_cfg(self):
        r = self.run_com("12", cfg={"probe.subfolderRatio": 0.2})
        self.assertIn("R-SUBFOLDER", r.result("mail.com")["reasons"])

    # ── cal.com ──────────────────────────────────────────────────────────────────────────────────
    def test_calendar_records_and_cursor(self):
        r = self.run_com("12", only="cal")
        self.assertEqual(r.rc, 0, r.err_text)
        recs = r.records
        self.assertTrue(recs)
        for x in recs:
            self.assertLessEqual(set(x), CAL_RAW, x.keys())
            self.assertRegex(x["start_utc"], UTC_RX)
            self.assertRegex(x["end_utc"], UTC_RX)
            self.assertLessEqual(x["start_utc"], x["end_utc"])
            self.assertEqual(x["ts_precision"], "date" if x["all_day"] else "minute")
            self.assertEqual(bool(x.get("flags", {}).get("organizer_me")), x["response_status"] == 1)
            self.assertLessEqual(set(x.get("flags", {})), CAL_FLAGS)
            self.assertIn(x["busy_status"], {"free", "tentative", "busy", "oof", "elsewhere"})
        weekly = [x for x in recs if x.get("global_appointment_id") == "ST-SERIES-0001"]
        self.assertGreaterEqual(len(weekly), 8)                            # 반복 회차 전개(IncludeRecurrences)
        self.assertEqual(len({x["start_utc"] for x in weekly}), len(weekly))
        self.assertTrue(all(x["is_recurring"] for x in weekly))
        self.assertTrue(any(x["online"] for x in recs))
        c = r.cursor
        self.assertEqual(set(c), {"last_start_utc", "cov_months"})
        self.assertEqual(c["cov_months"]["2026-09"]["status"], "done")
        r2 = self.run_com("12", only="cal", cursor=c)
        self.assertEqual(r2.rc, 4, r2.err_text)

    def test_calendar_union_of_dasl_and_jet(self):
        full = self.run_com("12", only="cal")
        nojet = self.run_com("12,jetfail", only="cal")                     # 로캘 불일치로 Jet 필터 0건인 PC
        self.assertEqual(nojet.rc, 0, nojet.err_text)

        def weekly(r):
            return [x for x in r.records if x.get("global_appointment_id") == "ST-SERIES-0001"]

        def singles(r):
            return {(x["global_appointment_id"], x["start_utc"]) for x in r.records if not x["is_recurring"]}
        self.assertTrue(weekly(full))
        self.assertEqual(weekly(nojet), [])                                # 시험 모델의 DASL 은 회차를 전개하지 않는다
        self.assertEqual(singles(full), singles(nojet))                    # 단발 일정은 DASL 만으로도 빠짐 0
        keys = [(x.get("global_appointment_id"), x["start_utc"], x["end_utc"]) for x in full.records]
        self.assertEqual(len(keys), len(set(keys)))                        # 합집합 중복 0

    def test_calendar_b_stage_organizer_and_attendees(self):
        r = self.run_com("12", "-ReadProtected", "1", only="cal")
        recs = r.records
        self.assertTrue(all("attendees" in x and "organizer" in x for x in recs))
        self.assertTrue(all(set(p) == {"addr", "name"} for x in recs for p in x["attendees"]))

    def test_calendar_omg_keeps_rows(self):
        full = self.run_com("12", only="cal")
        r = self.run_com("12,omgitem", "-ReadProtected", "1", only="cal")
        self.assertEqual(r.rc, 0, r.err_text)
        res = r.result("cal.com")
        self.assertIn("R-OMG", res["reasons"])
        self.assertEqual(res["counts"]["protected_fail"], 3)               # 연속 거부 3회면 B단을 멈춘다
        self.assertEqual(len(r.records), len(full.records))                # 행 폐기 0
        self.assertTrue(all("attendees" not in x for x in r.records))

    def test_calendar_cap(self):
        r = self.run_com("200", only="cal", cfg={"mail.com.capCal": 100})
        res = r.result("cal.com")
        self.assertTrue(res["cap_hit"])
        self.assertIn("R-CAP", res["reasons"])
        self.assertEqual(len(r.records), 100)

    # ── 혼합 · 인자 · 무부작용 ───────────────────────────────────────────────────────────────────
    def test_mixed_mode_routes_by_kind(self):
        r = self.run_com("12", only=None, rng=["-Since", "2026-09-01", "-Until", "2026-09-30", "-TestNow", "2026-10-05 09:00"])
        self.assertEqual(r.rc, 0, r.err_text)
        kinds = {x.get("_kind") for x in r.records}
        self.assertEqual(kinds, {"mail", "cal"})
        self.assertEqual(set(r.cursor), {"mail.com", "cal.com"})
        self.assertEqual({x["src"] for x in r.results}, {"mail.com", "cal.com"})

    def test_bad_arguments_rc3(self):
        for rng in (RANGE + ["-Pc", "PC-1"], ["-Since", "2026/09/01"], RANGE + ["-Extra", "1"],
                    ["-Since", "2026-09-30", "-Until", "2026-09-01"]):
            r = self.run_com("3", rng=rng)
            self.assertEqual(r.rc, 3, rng)
            self.assertIn("R-TRANSPORT", r.result("mail.com")["reasons"])
        r = run_ps(self.clone, SCRIPT, ["-Only", "bogus"], env={"LM_OUTLOOK_SELFTEST": "3"})
        self.assertEqual(r.rc, 3)

    def test_valid_pc_and_no_stdin_defaults(self):
        r = self.run_com("6", "-Pc", "pc_0123456789abcdef", stdin=False)
        self.assertEqual(r.rc, 0, r.err_text)
        self.assertTrue(r.records)

    def test_no_disk_writes(self):
        r, before, after = self.protected()
        self.assertEqual(r.rc, 0)
        self.assertEqual(before, after)                                    # L-09 — 원문은 stdout 으로만
        self.assertFalse(self.clone.path("data").exists())

    def test_stderr_has_no_raw_text(self):
        r = self.protected()[0]
        self.assertNotIn("selftest mail", r.err_text)
        self.assertNotIn("@corp.example", r.err_text)
        self.assertIsNone(re.search(r"[가-힣]+@", r.err_text))


if __name__ == "__main__":
    unittest.main()
