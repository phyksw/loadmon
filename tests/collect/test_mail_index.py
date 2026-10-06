# -*- coding: utf-8 -*-
"""WP-15 Get-OutlookIndex.ps1(mail.index · cal.index) 시험 — %TEMP% 복제 트리에서 LM_INDEX_FAKE 주입점만으로(실 색인 0).

CM §15 수집기 측: CM-1(새 Outlook — 색인은 시도, Outlook 항목 0 이면 R-NEWOL) · 5(색인 꺼짐 R-NOIDX) · 6(온라인 모드
R-ONLINE) · 10(상한 → cap_hit·R-CAP) · 12(반복 마스터만 → recurrence_incomplete·rc 3) · 16(UTC 리터럴·오프셋) · 20(내 주소
미확정). 계약 §7.3(_in·_meta·_cursor) · §8.1 · X-120(막힌 사유면 rc 3) · X-124 · X-125.
"""
import json
import unittest
from datetime import datetime, timedelta

from lm27.collect import rcmap
from lm27.util import tz
from tests.fixtures import synth
from tests.fixtures.synth import inject
from tests.fixtures.tree import CloneTestCase
from tests.fixtures.wp15.mailkit import CAL_RAW, FORBIDDEN_RAW, MAIL_RAW, OFF_RX, UTC_RX, ps_exe, run_ps, tree_snapshot

SCRIPT = "Get-OutlookIndex.ps1"
RANGE = ["-Since", "2026-09-01", "-Until", "2026-09-30", "-TestNow", "2026-10-05 09:00"]
ME = "gildong.hong@corp.example"


def _row(folder, subject, when, *, sent=False, url_prefix="mapi://lm27t", to=("peer.b@corp.example",), to_name=("동료B",)):
    r = {"System.ItemUrl": f"{url_prefix}/{folder}/{subject}", "System.ItemFolderPathDisplay": folder,
         "System.Subject": subject, "System.ItemDate": when, "System.Message.FromName": ["김철수"],
         "System.Message.FromAddress": ["Chulsoo.Kim@corp.example"], "System.Message.ToAddress": list(to),
         "System.Message.ToName": list(to_name), "System.Message.CcAddress": [], "System.Message.CcName": [],
         "System.Kind": ["email"]}
    r["System.Message.DateSent" if sent else "System.Message.DateReceived"] = when
    return r


def local_to_utc_iso(s: str) -> str:
    """'yyyy-MM-dd HH:mm'(이 PC 로컬) → UTC ISO — 시험 쪽 독립 계산(lm27.util.tz)."""
    naive = datetime.strptime(s, "%Y-%m-%d %H:%M")
    off = tz.capture_offset_min(naive - timedelta(hours=9))
    u = naive - timedelta(minutes=off)
    off2 = tz.capture_offset_min(u)
    return (naive - timedelta(minutes=off2)).strftime("%Y-%m-%dT%H:%M:%SZ")


@unittest.skipUnless(ps_exe(), "Windows PowerShell 없음")
class MailIndexTest(CloneTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.plan = synth.plan_month(2026, 9)
        base = inject.index_fake(cls.plan)
        cls.n_plan_mail = len(base["mail"])
        cls.n_plan_cal = len(base["calendar"])
        extra = [
            _row("\\받은 편지함\\규칙 폴더", "WP15 rule folder item", "2026-09-10 10:00"),
            _row("\\보낸 편지함", "WP15 sent item", "2026-09-10 11:00", sent=True),
            _row("\\Presentations", "WP15 presentations not sent", "2026-09-10 12:00"),
            _row("\\지운 편지함", "WP15 deleted item", "2026-09-10 13:00"),
            _row("\\Junk Email", "WP15 junk item", "2026-09-10 13:30"),
            _row("\\임시 보관함", "WP15 draft item", "2026-09-10 14:00"),
            _row("\\받은 편지함", "WP15 disk file", "2026-09-10 15:00", url_prefix="file:///C:/x"),
            _row("\\받은 편지함\\과제폴더", "WP15 custom excluded", "2026-09-10 16:00"),
        ]
        # 합성 계획은 반복 회차마다 IsRecurring=True 를 단다 — 실제 색인은 마스터 1행이므로 회차 행은 단발로 바꿔 둔다
        cal = [dict(r, **{"System.Calendar.IsRecurring": False}) for r in base["calendar"]]
        cls.fake = dict(base, mail=base["mail"] + extra, calendar=cal, _my_addrs=[ME])
        cls.fake_masters = dict(cls.fake, calendar=cal + [{
            "System.ItemUrl": "mapi://lm27t/일정/master", "System.Subject": "WP15 weekly master",
            "System.StartDate": "2026-09-01 10:00", "System.EndDate": "2026-09-01 10:30",
            "System.Calendar.IsRecurring": True, "System.Kind": ["calendar"]}])
        cls.dir = cls.clone.sandbox / "wp15"
        cls.dir.mkdir(parents=True, exist_ok=True)
        cls.files = {}

    def fake_file(self, name, obj):
        p = self.dir / name
        p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
        return str(p)

    def run_idx(self, fake, *args, only="mail", cfg=None, cursor=None, rng=RANGE):
        path = self.fake_file(f"fake_{abs(hash(json.dumps(fake, sort_keys=True, ensure_ascii=False)))}.json", fake)
        a = list(rng) + list(args)
        if only is not None:
            a = ["-Only", only] + a
        return run_ps(self.clone, SCRIPT, a, env={"LM_INDEX_FAKE": path}, cfg=cfg, cursor=cursor)

    # ── 메일 ─────────────────────────────────────────────────────────────────────────────────────
    def test_mail_rows_folders_and_shape(self):
        r = self.run_idx(self.fake)
        self.assertEqual(r.rc, 0, r.err_text)
        self.assertEqual(r.meta["my_addrs"], [ME])
        recs = r.records
        subj = {x["subject"] for x in recs}
        self.assertIn("WP15 rule folder item", subj)
        self.assertIn("WP15 sent item", subj)
        for bad in ("WP15 deleted item", "WP15 junk item", "WP15 draft item", "WP15 disk file"):
            self.assertNotIn(bad, subj)                                    # 폴더 조각 정확 일치 제외 · mapi 항목만
        self.assertEqual(len(recs), self.n_plan_mail + 4)                  # 합성 계획 + 규칙·보낸·Presentations·과제폴더
        by = {x["subject"]: x for x in recs}
        self.assertEqual((by["WP15 rule folder item"]["box"], by["WP15 rule folder item"]["folder_role"]), ("inbox", "subfolder"))
        self.assertEqual((by["WP15 sent item"]["box"], by["WP15 sent item"]["folder_role"]), ("sent", "sent"))
        self.assertEqual(by["WP15 presentations not sent"]["box"], "inbox")    # 'Presentations' 를 Sent 로 오인하지 않음
        self.assertEqual(by["WP15 sent item"]["sender_addr"], "chulsoo.kim@corp.example")
        self.assertEqual(by["WP15 sent item"]["to"], [{"addr": "peer.b@corp.example", "name": "동료B"}])
        first_inbox = next(i for i, x in enumerate(recs) if x["box"] == "inbox")
        self.assertFalse(any(x["box"] == "sent" for x in recs[first_inbox:]))  # 보낸 편지함 먼저(CM §10)
        for x in recs:
            self.assertLessEqual(set(x), MAIL_RAW)
            self.assertFalse(set(x) & FORBIDDEN_RAW)
            self.assertNotIn("headers_text", x)                            # 색인은 헤더가 없다(ad_partial 은 정제기)
        res = r.result("mail.index")
        self.assertEqual(res["counts"]["excluded_folder"], 3)              # 지운 편지함 · Junk Email · 임시 보관함
        self.assertEqual(res["counts"]["non_outlook"], 1)
        self.assertEqual(res["items_ok"], len(recs))

    def test_exclude_list_from_cfg(self):
        cfg = {"mail.index.excludeFolderNames": ["지운 편지함", "Junk Email", "임시 보관함", "과제폴더"]}
        r = self.run_idx(self.fake, cfg=cfg)
        subj = {x["subject"] for x in r.records}
        self.assertNotIn("WP15 custom excluded", subj)
        self.assertEqual(r.result("mail.index")["counts"]["excluded_folder"], 4)

    def test_cm16_utc_conversion_and_offsets(self):
        r = self.run_idx(self.fake)
        by = {x["subject"]: x for x in r.records}
        self.assertEqual(by["WP15 sent item"]["ts_utc"], local_to_utc_iso("2026-09-10 11:00"))
        for x in r.records:
            self.assertRegex(x["ts_utc"], UTC_RX)
            self.assertRegex(x["ts_local_offset"], OFF_RX)
            self.assertEqual(x["ts_local_offset"], tz.fmt_offset(tz.capture_offset_min(x["ts_utc"])))
            self.assertEqual(x["ts_precision"], "minute")

    def test_conversation_topic_strips_prefix(self):
        fake = dict(self.fake, mail=[_row("\\받은 편지함", "RE: FW: 회신: 과제A 검토", "2026-09-11 09:00")])
        r = self.run_idx(fake)
        self.assertEqual(r.records[0]["conversation_topic"], "과제A 검토")
        self.assertEqual(r.records[0]["subject"], "RE: FW: 회신: 과제A 검토")

    def test_cm10_cap_partial(self):
        rows = [_row("\\받은 편지함", f"WP15 bulk {i}", f"2026-09-{1 + i % 28:02d} {8 + i % 10:02d}:{i % 60:02d}") for i in range(130)]
        r = self.run_idx(dict(self.fake, mail=rows), cfg={"mail.index.capMail": 100})
        self.assertEqual(r.rc, 0, r.err_text)
        res = r.result("mail.index")
        self.assertTrue(res["cap_hit"])
        self.assertIn("R-CAP", res["reasons"])
        self.assertEqual(len(r.records), 100)

    def test_cursor_rerun_rc4_and_overlap(self):
        r1 = self.run_idx(self.fake)
        c = r1.cursor
        self.assertRegex(c["last_item_ts_utc"], UTC_RX)
        self.assertRegex(c["read_from"], UTC_RX)
        r2 = self.run_idx(self.fake, cursor=c)
        self.assertEqual(r2.rc, 4, r2.err_text)
        last = datetime.strptime(c["last_item_ts_utc"], "%Y-%m-%dT%H:%M:%SZ")
        for x in r2.records:                                               # 마지막 시각 −1일 겹침만 다시 낸다
            self.assertGreaterEqual(datetime.strptime(x["ts_utc"], "%Y-%m-%dT%H:%M:%SZ"), last - timedelta(days=1))
        self.assertLess(len(r2.records), len(r1.records))

    def test_cm20_unknown_address(self):
        fake = {k: v for k, v in self.fake.items() if k != "_my_addrs"}
        r = self.run_idx(fake)
        self.assertEqual(r.meta["my_addrs"], [])
        self.assertIn("R-NOADDR", r.result("mail.index")["reasons"])
        self.assertTrue(r.records)                                         # rcv 는 정제기가 unknown 으로(행은 낸다)
        r2 = self.run_idx(fake, cfg={"collect.ownerAddress": "Owner@Corp.Example"})
        self.assertEqual(r2.meta["my_addrs"], ["owner@corp.example"])

    def test_horizon_reason(self):
        r = self.run_idx(self.fake, rng=["-Since", "2026-06-01", "-Until", "2026-09-30", "-TestNow", "2026-10-05 09:00"])
        res = r.result("mail.index")
        self.assertIn("R-HORIZON", res["reasons"])
        self.assertRegex(res["horizon_oldest"], r"^2026-09-\d{2}$")
        r2 = self.run_idx(self.fake)
        self.assertNotIn("R-HORIZON", r2.result("mail.index")["reasons"])

    def test_extended_properties_rejected_fallback(self):
        r = self.run_idx(dict(self.fake, _ext_rejected=True))
        self.assertEqual(r.rc, 0, r.err_text)
        self.assertTrue(r.result("mail.index")["counts"]["fallback"])
        self.assertTrue(all(p["name"] is None for x in r.records for p in x["to"]))

    # ── 막힘(rc 3 + 사유) ───────────────────────────────────────────────────────────────────────
    def test_cm05_index_off_and_paused(self):
        for err, code in (("noidx", "R-NOIDX"), ("paused", "R-IDXPAUSED")):
            r = self.run_idx(dict(self.fake, _error=err))
            self.assertEqual(r.rc, 3)
            self.assertIn(code, r.result("mail.index")["reasons"])
            self.assertEqual(r.records, [])

    def test_cm06_cm01_no_outlook_items(self):
        empty = {"mail": [], "calendar": [], "_my_addrs": [ME]}
        for extra, code in (({}, "R-ONLINE"), ({"_policy": True}, "R-IDXPOLICY"), ({"_newol": True}, "R-NEWOL")):
            r = self.run_idx(dict(empty, **extra))
            self.assertEqual(r.rc, 3)
            self.assertIn(code, r.result("mail.index")["reasons"])

    def test_zero_rows_in_range_is_rc1(self):
        r = self.run_idx(self.fake, rng=["-Since", "2026-11-01", "-Until", "2026-11-30", "-TestNow", "2026-12-05 09:00"])
        self.assertEqual(r.rc, 1, r.err_text)
        self.assertEqual(r.records, [])

    def test_cm08_clm_blocked(self):
        cmd = "$ExecutionContext.SessionState.LanguageMode='ConstrainedLanguage'; & '@SCRIPT@' -Only cal; exit $LASTEXITCODE"
        r = run_ps(self.clone, SCRIPT, [], env={"LM_INDEX_FAKE": "x"}, stdin=False, command=cmd)
        self.assertEqual(r.rc, 3)
        self.assertEqual(r.result("cal.index")["reasons"], ["R-CLM"])

    # ── 일정 ─────────────────────────────────────────────────────────────────────────────────────
    def test_calendar_without_masters_rc0(self):
        r = self.run_idx(self.fake, only="cal")
        self.assertEqual(r.rc, 0, r.err_text)
        self.assertEqual(len(r.records), self.n_plan_cal)
        for x in r.records:
            self.assertLessEqual(set(x), CAL_RAW)
            self.assertFalse(x["recurrence_incomplete"])
            self.assertIn(x["busy_status"], {"free", "tentative", "busy", "oof", "elsewhere"})
        self.assertEqual(r.result("cal.index")["recurrence_incomplete"], 0)

    def test_cm12_recurring_master_only_recurinc_partial(self):
        """CM-12 · 계약 v1.2 §0.7 C4(W1 통합 창): 반복 마스터만(회차 미전개) → R-RECURINC + partial(부분 결과 — rc 는 새 레코드
        기준 0). 예전 'rc 3·사유 없음' 은 연결자에서 R-TRANSPORT 로 접혀 cal.owa 배정 근거가 수송 실패로 왜곡됐다."""
        r = self.run_idx(self.fake_masters, only="cal")
        self.assertEqual(r.rc, 0, r.err_text)
        res = r.result("cal.index")
        self.assertEqual(res["recurrence_incomplete"], 1)
        self.assertEqual(res["reasons"], ["R-RECURINC"])
        self.assertTrue(res["partial"])
        self.assertEqual(rcmap.translate_cell(res["rc"], res["reasons"], res)["status"], "partial")
        m = [x for x in r.records if x["subject"] == "WP15 weekly master"]
        self.assertEqual(len(m), 1)
        self.assertTrue(m[0]["recurrence_incomplete"] and m[0]["is_recurring"])
        self.assertEqual(len(r.records), self.n_plan_cal + 1)              # 저장은 한다(불완전 신호와 함께)

    def test_calendar_fallback_is_incomplete(self):
        r = self.run_idx(dict(self.fake, _ext_rejected=True), only="cal")
        self.assertEqual(r.rc, 0, r.err_text)
        res = r.result("cal.index")
        self.assertTrue(res["counts"].get("recurrence_unknown"))
        self.assertIn("R-RECURINC", res["reasons"])
        self.assertTrue(res["partial"])

    def test_status_line_c1_shape(self):
        """계약 v1.2 §0.7 C1 — 경로마다 _status 한 줄, 필수 필드 ⊇ C1 집합, _result 키 없음."""
        r = self.run_idx(self.fake, only=None)
        self.assertNotIn('"_result"', r.err_text)
        for src in ("mail.index", "cal.index"):
            res = r.result(src)
            self.assertLessEqual({"schema", "src", "rc", "reasons", "partial", "cap_hit", "budget_hit", "n", "counts"},
                                 set(res))
            self.assertEqual((res["schema"], res["n"]), ("lm27.collector_status/1", res["new"]))

    # ── 혼합 · 인자 · 무부작용 ───────────────────────────────────────────────────────────────────
    def test_mixed_mode(self):
        r = self.run_idx(self.fake, only=None)
        self.assertEqual(r.rc, 0, r.err_text)
        self.assertEqual({x["_kind"] for x in r.records}, {"mail", "cal"})
        self.assertEqual(set(r.cursor), {"mail.index", "cal.index"})

    def test_bad_arguments_rc3(self):
        for rng in (RANGE + ["-Pc", "bad"], ["-Since", "2026-09-01", "-Until", "2026-13-40"],
                    ["-Since", "2026-09-30", "-Until", "2026-09-01"]):
            r = self.run_idx(self.fake, rng=rng)
            self.assertEqual(r.rc, 3, rng)
            self.assertIn("R-TRANSPORT", r.result("mail.index")["reasons"])

    def test_no_disk_writes(self):
        before = tree_snapshot(self.clone.root)
        r = self.run_idx(self.fake, only=None)
        self.assertEqual(r.rc, 0)
        self.assertEqual(before, tree_snapshot(self.clone.root))
        self.assertFalse(self.clone.path("data").exists())


if __name__ == "__main__":
    unittest.main()
