# -*- coding: utf-8 -*-
"""WP-15 Import-MailCal.py(mail.import · cal.import) 시험 — 합성 EML·ICS·CSV(tests\\fixtures\\wp15)만 쓴다.

정제·저장 지점(WP-11 lm27.privacy.sanitize · lm27.store)은 계약 시그니처대로 만든 가짜로 바꿔 넣는다(Backend 주입).
CM-13(회의 응답 발신) · CM-14(헤더 단서 전달) · CM-15(사적 표시) · CM-16(UTC 정규화) · CM-18(.msg → skipped_msg, X-314) ·
P-T31(금지 원시 필드 0) · 계약 §3.5(CSV 헤더 = 원시 이름, ts_local) · §7.3(flush 성공 뒤 커서 저장) · §8.1(rc) · 무부작용.
"""
import importlib.util
import io
import json
import os
import shutil
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from lm27.config import load_config
from lm27.paths import Paths
from lm27.util import events, tz
from tests.fixtures.tree import CloneTestCase, guard_write
from tests.fixtures.wp15.mailkit import CAL_RAW, FORBIDDEN_RAW, MAIL_RAW, OFF_RX, UTC_RX, tree_snapshot

TREE = Path(__file__).resolve().parents[2]
FIX = TREE / "tests" / "fixtures" / "wp15"
PC = "pc_0123456789abcdef"
ME = "gildong.hong@corp.example"
NOW = datetime(2026, 10, 5, 0, 0, tzinfo=UTC)


def load_module():
    spec = importlib.util.spec_from_file_location("lm27t_import_mailcal", TREE / "collect" / "Import-MailCal.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


M = load_module()


# ── WP-11 계약 시그니처 가짜(lm27.privacy.sanitize · lm27.store) ───────────────────────────────────────
class FakeOutcome:
    def __init__(self, status, row=None, reason=None):
        self.status, self.row, self.reason, self.hits = status, row, reason, {}


class FakeAudit:
    def __init__(self, log):
        self.log = log

    def add(self, counter, key, n=1):
        self.log.append(("audit.add", counter, key, n))

    def flush(self, **numbers):
        self.log.append(("audit.flush", dict(numbers)))


class FakeBackend:
    """make_record_context · sanitize_record · SegmentWriter · load_raw_cursor · save_raw_cursor 의 기록용 가짜."""

    def __init__(self, *, drop=None, fail_flush=False, cursor=None):
        self.log, self.rows, self.raws, self.saved = [], [], [], {}
        self.drop = drop or (lambda kind, raw: None)
        self.fail_flush = fail_flush
        self.cursor = dict(cursor or {})
        be = self

        class Writer:
            def __init__(self, paths, pc_id, kind, src):
                be.log.append(("writer", pc_id, kind, src))

            def append(self, row):
                be.rows.append(row)

            def flush(self):
                be.log.append(("flush",))
                if be.fail_flush:
                    raise OSError("disk")
                return len(be.rows)

            def close(self):
                be.log.append(("close",))

        self.Backend = M.Backend(self.make_record_context, self.sanitize_record, Writer, self.load_raw_cursor,
                                 self.save_raw_cursor)

    def make_record_context(self, root, src, pc_id, *, my_addrs=(), **_kw):
        self.log.append(("ctx", src, pc_id, tuple(my_addrs)))
        return type("RC", (), {"audit": FakeAudit(self.log), "src": src, "my_addrs": frozenset(my_addrs)})()

    def sanitize_record(self, kind, raw, rc):
        self.raws.append((kind, raw))
        why = self.drop(kind, raw)
        if why:
            return FakeOutcome("dropped", None, why)
        return FakeOutcome("stored", {"kind": kind, "n": len(self.raws)})

    def load_raw_cursor(self, paths, pc_id):
        return dict(self.cursor)

    def save_raw_cursor(self, paths, pc_id, src, value):
        self.log.append(("save_cursor", src))
        self.cursor[src] = value
        self.saved[src] = value


def read_eml(name):
    return (FIX / "import" / name).read_bytes()


class ParseEmlTest(unittest.TestCase):

    def test_plain_inbox_fields(self):
        r = M.parse_eml(read_eml("inbox_plain.eml"), (ME,), now=NOW)
        self.assertLessEqual(set(r), MAIL_RAW)
        self.assertEqual(r["ts_utc"], "2026-09-15T01:00:00Z")              # +0900 → UTC(CM-16)
        self.assertEqual(r["ts_local_offset"], tz.fmt_offset(tz.capture_offset_min(r["ts_utc"])))
        self.assertEqual((r["box"], r["folder_role"]), ("inbox", "inbox"))
        self.assertEqual(r["sender_addr"], "chulsoo.kim@corp.example")
        self.assertEqual(r["sender_name"], "김철수")
        self.assertEqual(r["to"], [{"addr": ME, "name": "홍길동"}, {"addr": "peer.b@corp.example", "name": "동료B"}])
        self.assertEqual(r["cc"], [{"addr": "peer.c@corp.example", "name": "동료C"}])
        self.assertEqual(r["subject"], "RE: 과제A 회로 검토 요청")
        self.assertEqual(r["conversation_topic"], "과제A 회로 검토 요청")
        self.assertEqual(r["conversation_id"], "00112233445566778899AABBCCDDEEFF")   # Thread-Index → COM 과 같은 대화 재료
        self.assertEqual(r["attach_names"], ["회로도_v2.pptx"])
        self.assertTrue(r["has_attach"])
        self.assertEqual(r["importance"], 2)
        self.assertEqual(r["categories"], ["과제A", "검토"])
        self.assertTrue(r["in_reply_to"])
        self.assertIn("회로 검토", r["body_text"])
        self.assertEqual(r["internet_message_id"], "<wp15-plain-0001@corp.example>")
        self.assertEqual((r["ts_precision"], r["confidence"]), ("minute", 1.0))

    def test_cm14_ad_headers_passed_for_sanitizer(self):
        r = M.parse_eml(read_eml("ad_newsletter.eml"), (ME,), now=NOW)
        self.assertIn("List-Unsubscribe:", r["headers_text"])
        self.assertIn("Precedence: bulk", r["headers_text"])
        self.assertNotIn("<p>", r["body_text"])                            # HTML 은 글자만
        self.assertNotIn("color", r["body_text"])
        self.assertEqual(r["subject"], "(광고) 가을 할인 안내")

    def test_cm13_meeting_reply_flag_and_sent_box(self):
        r = M.parse_eml(read_eml("sub/sent_reply.eml"), (ME,), now=NOW)
        self.assertEqual(r["box"], "sent")
        self.assertTrue(r["flags"]["meeting_response"])

    def test_cm15_private_sensitivity(self):
        r = M.parse_eml(read_eml("private_note.eml"), (ME,), now=NOW)
        self.assertEqual(r["sensitivity"], 2)
        self.assertEqual(r["importance"], 0)

    def test_no_date_is_skipped(self):
        self.assertIsNone(M.parse_eml(read_eml("no_date.eml"), (ME,), now=NOW))

    def test_unknown_owner_box_other(self):
        r = M.parse_eml(read_eml("inbox_plain.eml"), (), now=NOW)
        self.assertEqual((r["box"], r["folder_role"]), ("other", "other"))

    def test_body_window_and_minus0000(self):
        body = "가" * 3000 + "나" * 3000
        raw = ("Date: Tue, 01 Sep 2026 10:00:00 -0000\r\nFrom: a@corp.example\r\nSubject: x\r\n"
               "Content-Type: text/plain; charset=utf-8\r\n\r\n" + body).encode("utf-8")
        r = M.parse_eml(raw, (ME,), now=NOW)
        self.assertEqual(len(r["body_text"]), 1000 + 1 + 4000)
        self.assertEqual(r["body_text"], "가" * 1000 + "\n" + "가" * 1000 + "나" * 3000)   # 앞 1,000 + 끝 4,000
        self.assertTrue(r["flags"]["utc_suspect"])                         # -0000 = 시간대 모름
        self.assertEqual(r["ts_utc"], "2026-09-01T10:00:00Z")

    def test_raw_8bit_header_is_decoded(self):
        raw = ("Date: Tue, 01 Sep 2026 10:00:00 +0900\r\nFrom: 김철수 <chulsoo.kim@corp.example>\r\n"
               "Subject: 과제B 일정\r\n\r\nbody").encode()
        r = M.parse_eml(raw, (ME,), now=NOW)
        self.assertEqual(r["subject"], "과제B 일정")
        self.assertEqual(r["sender_name"], "김철수")


class ParseIcsTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        win = (datetime(2026, 8, 1, tzinfo=UTC), datetime(2026, 12, 31, tzinfo=UTC))
        cls.recs, cls.st = M.parse_ics((FIX / "import" / "calendar.ics").read_bytes(), (ME,), now=NOW, window=win)

    def by_uid(self, uid):
        return [r for r in self.recs if r.get("global_appointment_id") == uid]

    def test_fields_subset_and_times(self):
        for r in self.recs:
            self.assertLessEqual(set(r), CAL_RAW)
            self.assertRegex(r["start_utc"], UTC_RX)
            self.assertRegex(r["ts_local_offset"], OFF_RX)
            self.assertLessEqual(r["start_utc"], r["end_utc"])

    def test_single_event_vtimezone(self):
        r = self.by_uid("wp15-single-0001")[0]
        self.assertEqual((r["start_utc"], r["end_utc"]), ("2026-09-15T05:00:00Z", "2026-09-15T06:30:00Z"))
        self.assertEqual(r["subject"], "과제A 설계 검토, 1차")
        self.assertEqual(r["response_status"], 3)                          # 내 PARTSTAT=ACCEPTED
        self.assertEqual(r["meeting_status"], 1)
        self.assertTrue(r["online"])                                       # 접힌 줄의 Teams 참가 링크
        self.assertEqual(r["organizer"], {"addr": "chulsoo.kim@corp.example", "name": "김철수"})
        self.assertEqual(len(r["attendees"]), 2)
        self.assertEqual(r["categories"], ["과제A", "검토"])
        self.assertEqual(r["location"], "회의실 3")

    def test_all_day_private_oof(self):
        r = self.by_uid("wp15-allday-0001")[0]
        self.assertTrue(r["all_day"])
        self.assertEqual(r["ts_precision"], "date")
        self.assertEqual(r["busy_status"], "oof")
        self.assertEqual(r["sensitivity"], 2)
        self.assertEqual(r["start_utc"], M.utc_iso(M.local_to_utc(datetime(2026, 9, 18))))

    def test_weekly_count_exdate_and_override(self):
        rs = sorted(self.by_uid("wp15-weekly-0001"), key=lambda x: x["start_utc"])
        self.assertEqual([x["start_utc"] for x in rs],
                         ["2026-09-07T00:00:00Z", "2026-09-21T01:00:00Z", "2026-09-28T00:00:00Z"])
        self.assertEqual(rs[1]["subject"], "주간 회의(변경)")
        self.assertTrue(all(x["is_recurring"] for x in rs))
        self.assertTrue(all(x["response_status"] == 1 for x in rs))        # 주최자 = 나

    def test_monthly_nth_weekday_until_utc(self):
        rs = sorted(x["start_utc"] for x in self.by_uid("wp15-monthly-0001"))
        self.assertEqual(rs, ["2026-09-08T01:00:00Z", "2026-10-13T01:00:00Z", "2026-11-10T01:00:00Z",
                              "2026-12-08T01:00:00Z"])

    def test_complex_rule_is_master_with_incomplete(self):
        rs = self.by_uid("wp15-complex-0001")
        self.assertEqual(len(rs), 1)
        self.assertTrue(rs[0]["recurrence_incomplete"])
        self.assertEqual(self.st["recurrence_incomplete"], 1)

    def test_cancelled_meeting(self):
        r = self.by_uid("wp15-cancel-0001")[0]
        self.assertEqual(r["meeting_status"], 5)
        self.assertEqual(r["response_status"], 4)
        self.assertEqual(r["end_utc"], "2026-09-16T04:45:00Z")             # DURATION

    def test_daylight_vtimezone_without_zoneinfo(self):
        win = (datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 12, 31, tzinfo=UTC))
        recs, _st = M.parse_ics((FIX / "ics_extra" / "dst.ics").read_bytes(), (ME,), now=NOW, window=win)
        got = {(r["global_appointment_id"], r["start_utc"]) for r in recs}
        self.assertIn(("wp15-dst-winter", "2026-01-15T17:00:00Z"), got)   # -08:00
        self.assertIn(("wp15-dst-summer", "2026-07-15T16:00:00Z"), got)   # -07:00
        daily = sorted(s for u, s in got if u == "wp15-dst-daily")
        self.assertEqual(daily[1], "2026-10-31T16:00:00Z")
        self.assertEqual(daily[2], "2026-11-01T17:00:00Z")                 # 서머타임 끝 — 벽시계 09:00 유지
        unk = [r for r in recs if r["global_appointment_id"] == "wp15-unknown-tz"][0]
        self.assertTrue(unk["flags"]["utc_suspect"])

    def test_reply_calendar_skipped(self):
        recs, st = M.parse_ics((FIX / "ics_extra" / "reply.ics").read_bytes(), (ME,), now=NOW)
        self.assertEqual((recs, st["replies_skipped"]), ([], 1))

    def test_expand_rrule_unsupported_returns_none(self):
        s = datetime(2026, 9, 1, 9)
        lo, hi = datetime(2026, 1, 1), datetime(2027, 1, 1)
        for rule in ("FREQ=HOURLY", "FREQ=MONTHLY;BYDAY=MO,TU", "FREQ=WEEKLY;BYDAY=1MO", "FREQ=DAILY;BYHOUR=9",
                     "FREQ=YEARLY;BYMONTH=3"):
            self.assertIsNone(M.expand_rrule(s, M.parse_rrule(rule), until_local=None, lo=lo, hi=hi, all_day=False), rule)
        occ = M.expand_rrule(s, M.parse_rrule("FREQ=DAILY;INTERVAL=2;COUNT=3"), until_local=None, lo=lo, hi=hi,
                             all_day=False)
        self.assertEqual(occ, [datetime(2026, 9, 1, 9), datetime(2026, 9, 3, 9), datetime(2026, 9, 5, 9)])

    def test_old_series_window_occurrences_not_truncated(self):
        """W1 통합 창 결함 회귀: 상한은 창 안 회차에 건다 — 2022년 시작 '매 평일'·'매일' 반복이 시작부터 센 1,000번째에서
        끊겨 창 안 회차가 조용히 사라지던 결함(310 → 45건, 매일 0건 · recurrence_incomplete 0)."""
        lo, hi = datetime(2025, 9, 1), datetime(2026, 11, 7)
        old, new = datetime(2022, 1, 3, 9), datetime(2025, 9, 1, 9)
        wk = M.parse_rrule("FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR;WKST=SU")
        a = M.expand_rrule(old, wk, until_local=None, lo=lo, hi=hi, all_day=False)
        b = M.expand_rrule(new, wk, until_local=None, lo=lo, hi=hi, all_day=False)
        self.assertEqual(a, b)
        self.assertEqual(len(a), 310)
        self.assertEqual((a[0], a[-1]), (datetime(2025, 9, 1, 9), datetime(2026, 11, 6, 9)))
        d = M.expand_rrule(old, M.parse_rrule("FREQ=DAILY"), until_local=None, lo=lo, hi=hi, all_day=False)
        self.assertEqual(len(d), (hi.date() - lo.date()).days)
        self.assertEqual(d[0], datetime(2025, 9, 1, 9))
        m = M.expand_rrule(datetime(2020, 1, 15, 10), M.parse_rrule("FREQ=MONTHLY;INTERVAL=2"), until_local=None,
                           lo=lo, hi=hi, all_day=False)
        self.assertEqual(m[0], datetime(2025, 9, 15, 10))
        y = M.expand_rrule(datetime(2001, 10, 1, 9), M.parse_rrule("FREQ=YEARLY"), until_local=None, lo=lo, hi=hi,
                           all_day=False)
        self.assertEqual(y, [datetime(2025, 10, 1, 9), datetime(2026, 10, 1, 9)])
        u = M.expand_rrule(old, wk, until_local=datetime(2025, 9, 3, 23, 59), lo=lo, hi=hi, all_day=False)
        self.assertEqual(len(u), 3)                                               # UNTIL 은 건너뛴 뒤에도 지킨다
        c = M.expand_rrule(old, M.parse_rrule("FREQ=DAILY;COUNT=2000"), until_local=None, lo=lo, hi=hi, all_day=False)
        self.assertEqual(c[0], datetime(2025, 9, 1, 9))                           # COUNT 는 시작부터 센다(1,338번째부터)
        self.assertEqual(c[-1], datetime(2026, 11, 6, 9))                         # 2,000번째(2027-06-25)보다 hi 가 먼저
        c2 = M.expand_rrule(old, M.parse_rrule("FREQ=DAILY;COUNT=1340"), until_local=None, lo=lo, hi=hi, all_day=False)
        want = [x for x in (old + timedelta(days=i) for i in range(1340)) if x >= lo]
        self.assertEqual(c2, want)                                                # 창 안은 1,338~1,340번째 3건
        self.assertEqual(len(want), 3)

    def test_window_occurrences_over_cap_is_incomplete(self):
        """창 안 회차가 RRULE_MAX 를 넘으면 조용히 자르지 않고 None(→ 마스터 1건 + recurrence_incomplete)."""
        lo, hi = datetime(2023, 1, 1), datetime(2026, 1, 1)
        self.assertIsNone(M.expand_rrule(datetime(2022, 1, 3, 9), M.parse_rrule("FREQ=DAILY"), until_local=None,
                                         lo=lo, hi=hi, all_day=False))
        ics = ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:wp15-long-daily\r\n"
               "DTSTART:20220103T000000Z\r\nDTEND:20220103T001500Z\r\nRRULE:FREQ=DAILY\r\nSUMMARY:x\r\n"
               "END:VEVENT\r\nEND:VCALENDAR\r\n").encode("ascii")
        recs, st = M.parse_ics(ics, (ME,), now=NOW, window=(datetime(2023, 1, 1, tzinfo=UTC), datetime(2026, 1, 1, tzinfo=UTC)))
        self.assertEqual(len(recs), 1)
        self.assertTrue(recs[0]["recurrence_incomplete"])
        self.assertEqual(st["recurrence_incomplete"], 1)


class ParseCsvTest(unittest.TestCase):

    def test_mail_csv(self):
        kind, recs, st = M.parse_csv((FIX / "import" / "mail_extra.csv").read_bytes(), (ME,), now=NOW)
        self.assertEqual(kind, "mail")
        self.assertEqual((st["rows"], st["bad_rows"]), (4, 1))
        self.assertEqual(len(recs), 3)
        a, b, c = recs
        self.assertEqual(a["ts_utc"], "2026-09-21T05:05:00Z")
        self.assertEqual(a["attach_names"], ["견적서_최종.xlsx", "사양.pdf"])
        self.assertTrue(a["has_attach"])
        self.assertEqual(b["ts_utc"], "2026-09-21T16:30:00Z")              # 'Z' 도 받는다
        self.assertEqual(b["box"], "sent")
        self.assertTrue(b["flags"]["meeting_response"])
        self.assertEqual(b["cc"], [{"addr": "chulsoo.kim@corp.example", "name": "김철수"}])
        self.assertEqual(c["subject"], "")                                 # 모자란 열 = 빈칸
        for r in recs:
            self.assertLessEqual(set(r), MAIL_RAW)
            self.assertNotIn("unknown_extra", r)                           # 남는 열 버림

    def test_cal_csv(self):
        kind, recs, st = M.parse_csv((FIX / "import" / "cal_rows.csv").read_bytes(), (ME,), now=NOW)
        self.assertEqual(kind, "cal")
        self.assertEqual(len(recs), 3)
        a, b, c = recs
        self.assertEqual((a["start_utc"], a["end_utc"]), ("2026-09-23T01:00:00Z", "2026-09-23T02:00:00Z"))
        self.assertEqual(a["response_status"], 1)                          # 주최자 = 나
        self.assertEqual(len(a["attendees"]), 2)
        self.assertTrue(b["all_day"])
        self.assertEqual((b["busy_status"], b["ts_precision"]), ("oof", "date"))
        self.assertEqual(c["response_status"], 3)                          # 'accepted'
        self.assertEqual(c["end_utc"], c["start_utc"])
        for r in recs:
            self.assertLessEqual(set(r), CAL_RAW)

    def test_unknown_header_is_skipped(self):
        kind, recs, _st = M.parse_csv(b"a,b\n1,2\n", (ME,), now=NOW)
        self.assertEqual((kind, recs), (None, []))

    def test_cp949_csv(self):
        data = "ts_local,box,sender_addr,subject\n2026-09-01T09:00:00+09:00,inbox,a@corp.example,한글 제목\n".encode("cp949")
        kind, recs, _st = M.parse_csv(data, (ME,), now=NOW)
        self.assertEqual(recs[0]["subject"], "한글 제목")


class RunTest(unittest.TestCase):
    """collect()/run() — 정제·저장은 가짜, 반입 폴더는 %TEMP% 사본."""

    @classmethod
    def setUpClass(cls):
        cls.paths = Paths(TREE)
        cls.cfg = load_config(cls.paths, overrides={"collect.ownerAddress": ME})
        cls.cfg_noaddr = load_config(cls.paths)

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="lm27t_wp15_"))
        guard_write(self.tmp)
        self.inbox = self.tmp / "import"
        shutil.copytree(FIX / "import", self.inbox)
        events.configure("off")

    def tearDown(self):
        events.configure("text")
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_cli(self, args, backend, cfg=None):
        err = io.StringIO()
        rc = M.run(["--pc", PC, "--in-dir", str(self.inbox), "--events", "off", *args], backend=backend.Backend,
                   paths=self.paths, cfg=cfg or self.cfg, now=NOW, err=err)
        lines = err.getvalue().splitlines()
        res = json.loads(lines[-1])["_status"]
        return rc, res, lines

    def test_mail_run_cm18_and_cursor_after_flush(self):
        be = FakeBackend()
        rc, res, _ = self.run_cli(["--kind", "mail"], be)
        self.assertEqual(rc, 0)
        self.assertEqual(res["src"], "mail.import")
        self.assertEqual(res["skipped_msg"], 1)                            # CM-18 · X-314
        self.assertEqual(res["items_total"], 4 + 3)                        # EML 4(날짜 없는 1 제외) + CSV 3
        self.assertEqual(res["items_ok"], 7)
        self.assertEqual(res["counts"]["bad_rows"], 2)
        self.assertEqual(len(be.rows), 7)
        kinds = {k for k, _r in be.raws}
        self.assertEqual(kinds, {"mail"})
        names = [x[0] for x in be.log]
        self.assertLess(names.index("flush"), names.index("save_cursor"))  # 기록 성공 뒤에만 커서(계약 §7.3)
        done = be.saved["mail.import"]["done"]
        self.assertEqual(len(done), 6)                                     # eml 5(날짜 없는 것도 처리 표식) + csv 1
        for k, v in done.items():
            self.assertRegex(k, r"^[0-9a-f]{16}$")
            self.assertEqual(len(v), 2)
        self.assertNotIn("calendar", json.dumps(be.saved))                 # 파일 이름·경로를 커서에 넣지 않는다
        ctx = [x for x in be.log if x[0] == "ctx"][0]
        self.assertEqual(ctx[1:], ("mail.import", PC, (ME,)))
        self.assertIn(("audit.flush", {"rows_in": 7, "rows_out": 7}), be.log)
        for _k, raw in be.raws:
            self.assertFalse(set(raw) & FORBIDDEN_RAW)                     # P-T31

    def test_second_run_is_rc4(self):
        be = FakeBackend()
        self.run_cli(["--kind", "mail"], be)
        be2 = FakeBackend(cursor=be.cursor)
        rc, res, _ = self.run_cli(["--kind", "mail"], be2)
        self.assertEqual(rc, 4)
        self.assertEqual(be2.raws, [])
        self.assertEqual(res["counts"]["done_files"], 6)

    def test_cal_run(self):
        be = FakeBackend()
        rc, res, _ = self.run_cli(["--kind", "cal", "--from", "2026-09-01", "--to", "2026-12-31"], be)
        self.assertEqual(rc, 0)
        self.assertEqual(res["src"], "cal.import")
        self.assertEqual(res["skipped_msg"], 0)
        self.assertEqual(res["recurrence_incomplete"], 1)
        self.assertGreaterEqual(res["items_total"], 10)
        self.assertEqual({k for k, _r in be.raws}, {"cal"})
        self.assertIn("cal.import", be.saved)

    def test_from_to_filter(self):
        be = FakeBackend()
        rc, res, _ = self.run_cli(["--kind", "mail", "--from", "2026-09-16", "--to", "2026-09-17"], be)
        self.assertEqual(rc, 0)
        days = sorted(raw["ts_utc"][:10] for _k, raw in be.raws)
        self.assertTrue(days)
        self.assertGreater(res["counts"]["out_of_range"], 0)
        for d in days:
            self.assertTrue("2026-09-15" <= d <= "2026-09-17")

    def test_dropped_reasons_counted(self):
        be = FakeBackend(drop=lambda kind, raw: "ad" if "광고" in raw.get("subject", "") else None)
        rc, res, _ = self.run_cli(["--kind", "mail"], be)
        self.assertEqual(rc, 0)                                            # 버려도 '관측'은 했다
        self.assertEqual(res["counts"]["dropped"], {"ad": 1})
        self.assertEqual(res["items_ok"], 6)
        self.assertIn(("audit.add", "dropped", "ad", 1), be.log)

    def test_store_failure_rc3_cursor_untouched(self):
        be = FakeBackend(fail_flush=True)
        rc, res, _ = self.run_cli(["--kind", "mail"], be)
        self.assertEqual(rc, 3)
        self.assertIn("R-TRANSPORT", res["reasons"])
        self.assertEqual(be.saved, {})
        self.assertEqual(res["counts"]["store_error"], "OSError")

    def test_noaddr_reason(self):
        be = FakeBackend()
        rc, res, _ = self.run_cli(["--kind", "mail"], be, cfg=self.cfg_noaddr)
        self.assertEqual(rc, 0)
        self.assertIn("R-NOADDR", res["reasons"])

    def test_empty_missing_and_msg_only_dirs_rc1(self):
        be = FakeBackend()
        shutil.rmtree(self.inbox)
        self.assertEqual(self.run_cli(["--kind", "mail"], be)[0], 1)       # 폴더 없음
        self.inbox.mkdir()
        self.assertEqual(self.run_cli(["--kind", "mail"], be)[0], 1)       # 빈 폴더
        (self.inbox / "only.msg").write_bytes(b"\xd0\xcf\x11\xe0")
        rc, res, _ = self.run_cli(["--kind", "mail"], be)
        self.assertEqual((rc, res["skipped_msg"]), (1, 1))

    def test_bad_file_does_not_stop_import(self):
        orig = M.parse_eml

        def boom(data, *a, **k):
            if b"wp15-ad-0001" in data:
                raise RuntimeError("synthetic")
            return orig(data, *a, **k)
        M.parse_eml = boom
        try:
            be = FakeBackend()
            rc, res, _ = self.run_cli(["--kind", "mail"], be)
        finally:
            M.parse_eml = orig
        self.assertEqual(rc, 0)
        self.assertEqual(res["counts"]["bad_files"], 1)
        self.assertEqual(res["counts"]["bad_file_errors"], {"RuntimeError": 1})
        self.assertEqual(res["items_total"], 6)
        self.assertEqual(len(be.saved["mail.import"]["done"]), 5)          # 실패한 파일은 표식 없음 — 다음 실행이 다시 읽는다

    def test_unexpected_error_is_rc3_not_traceback(self):
        orig = M.scan_files
        M.scan_files = lambda _d: (_ for _ in ()).throw(PermissionError("synthetic"))
        try:
            rc, res, _ = self.run_cli(["--kind", "mail"], FakeBackend())
        finally:
            M.scan_files = orig
        self.assertEqual(rc, 3)
        self.assertIn("R-TRANSPORT", res["reasons"])
        self.assertEqual(res["counts"]["error"], "PermissionError")

    def test_long_csv_field(self):
        big = "x" * 300000
        (self.inbox / "big.csv").write_text("ts_local,box,sender_addr,subject,headers_text\n"
                                            f"2026-09-02T09:00:00+09:00,inbox,a@corp.example,big,\"{big}\"\n", encoding="utf-8")
        be = FakeBackend()
        rc, res, _ = self.run_cli(["--kind", "mail"], be)
        self.assertEqual(rc, 0)
        raw = [r for _k, r in be.raws if r.get("subject") == "big"][0]
        self.assertEqual(len(raw["headers_text"]), M.HEADERS_MAX)

    def test_argument_errors_rc3(self):
        for args in (["--kind", "mail", "--pc", "PC-1"], ["--kind", "x"], ["--kind", "mail", "--from", "2026/09/01"],
                     ["--kind", "mail", "--from", "2026-09-10", "--to", "2026-09-01"]):
            err = io.StringIO()
            rc = M.run([*args, "--pc", PC] if "--pc" not in args else args, backend=FakeBackend().Backend,
                       paths=self.paths, cfg=self.cfg, now=NOW, err=err)
            self.assertEqual(rc, 3, args)
            self.assertIn("R-TRANSPORT", json.loads(err.getvalue().splitlines()[-1])["_status"]["reasons"])

    def test_sources_untouched_and_no_disk_writes(self):
        before = tree_snapshot(self.tmp)
        root_before = tree_snapshot(TREE, skip=("_sandbox", ".git", "python"))
        be = FakeBackend()
        self.run_cli(["--kind", "mail"], be)
        self.run_cli(["--kind", "cal"], be)
        self.assertEqual(before, tree_snapshot(self.tmp))                  # 원본 무변경 · 반입 폴더에 표식 파일 없음
        self.assertEqual(root_before, tree_snapshot(TREE, skip=("_sandbox", ".git", "python")))


class CliTest(CloneTestCase):
    """복제 트리에서 스크립트로 실행(-X utf8 -I -B, 계약 §7.3). WP-11 실물이 없으면 계약 시그니처 스텁을 복제에만 둔다."""

    STUB_SANITIZE = '''
import json, os
class _O:
    def __init__(self, row):
        self.status, self.row, self.reason, self.hits = "stored", row, None, {}
class _A:
    def add(self, *a, **k): pass
    def flush(self, **k): pass
class _RC:
    audit = _A()
def make_record_context(root, src, pc_id, *, agent_dir=None, stage="collect", my_addrs=()):
    return _RC()
def sanitize_record(kind, raw, rc):
    return _O({"kind": kind})
'''
    STUB_STORE = '''
import json, os
_LOG = os.path.join(os.environ["LM27T_CLONE"], "_sandbox", "wp15_store.json")
class SegmentWriter:
    def __init__(self, paths, pc_id, kind, src):
        self.n, self.kind, self.src = 0, kind, src
    def append(self, row):
        self.n += 1
    def flush(self):
        with open(_LOG, "w", encoding="utf-8") as fh:
            json.dump({"kind": self.kind, "src": self.src, "n": self.n}, fh)
        return self.n
    def close(self):
        pass
'''
    STUB_CURSOR = '''
import json, os
_C = os.path.join(os.environ["LM27T_CLONE"], "_sandbox", "wp15_cursor.json")
def load_raw_cursor(paths, pc_id):
    if os.path.exists(_C):
        with open(_C, encoding="utf-8") as fh:
            return json.load(fh)
    return {}
def save_raw_cursor(paths, pc_id, src, value):
    c = load_raw_cursor(paths, pc_id)
    c[src] = value
    with open(_C, "w", encoding="utf-8") as fh:
        json.dump(c, fh)
'''

    def test_script_run(self):
        c = self.clone
        real = c.path("lm27", "privacy", "sanitize.py").exists() and c.path("lm27", "store", "__init__.py").exists()
        # 스텁은 복제에만, 그리고 실물과 섞이지 않을 때만(privacy 가 아직 namespace 패키지이고 store 가 없을 때)
        partial = (c.path("lm27", "privacy", "__init__.py").exists() or c.path("lm27", "privacy", "sanitize.py").exists()
                   or c.path("lm27", "store").exists())
        if not real and partial:
            self.skipTest("WP-11 일부만 있음 — 통합 창에서 다시")
        if not real:
            for rel, txt in ((("lm27", "privacy", "sanitize.py"), self.STUB_SANITIZE),
                             (("lm27", "store", "__init__.py"), self.STUB_STORE),
                             (("lm27", "store", "cursor.py"), self.STUB_CURSOR)):
                p = c.path(*rel)
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(txt, encoding="utf-8")
        inbox = c.sandbox / "import"
        shutil.copytree(FIX / "import", inbox)
        cp = c.run_py(["-I", c.path("collect", "Import-MailCal.py"), "--kind", "mail", "--pc", PC, "--in-dir", inbox],
                      flags=("-X", "utf8", "-B"))
        err = cp.stderr.decode("utf-8", "replace").splitlines()
        res = json.loads(err[-1])["_status"]
        self.assertEqual(res["skipped_msg"], 1)
        out = [json.loads(x) for x in cp.stdout.decode("utf-8").splitlines() if x.strip()]
        self.assertEqual(out[-1]["ev"], "result")                          # --events jsonl(기본) — stdout 은 이벤트만
        if real:
            self.assertIn(cp.returncode, (0, 3), err)
            return
        self.assertEqual(cp.returncode, 0, err)
        self.assertEqual(res["items_ok"], 7)
        st = json.loads((c.sandbox / "wp15_store.json").read_text(encoding="utf-8"))
        self.assertEqual((st["kind"], st["src"], st["n"]), ("mail", "mail.import", 7))
        cur = json.loads((c.sandbox / "wp15_cursor.json").read_text(encoding="utf-8"))
        self.assertEqual(len(cur["mail.import"]["done"]), 6)
        cp2 = c.run_py(["-I", c.path("collect", "Import-MailCal.py"), "--kind", "mail", "--pc", PC, "--in-dir", inbox],
                       flags=("-X", "utf8", "-B"))
        self.assertEqual(cp2.returncode, 4)
        self.assertFalse(c.path("data").exists())

    def test_bad_args_rc3_not_argparse_2(self):
        cp = self.clone.run_py(["-I", self.clone.path("collect", "Import-MailCal.py"), "--kind", "mail"],
                               flags=("-X", "utf8", "-B"))
        self.assertEqual(cp.returncode, 3)                                 # argparse 의 2(=로그인 필요)와 겹치지 않게


@unittest.skipUnless(os.name == "nt", "Windows 전용")
class ImportErrorTest(unittest.TestCase):
    def test_missing_sanitizer_is_rc3(self):
        if (TREE / "lm27" / "privacy" / "sanitize.py").exists():
            self.skipTest("정제기 실물 있음")
        err = io.StringIO()
        tmp = Path(tempfile.mkdtemp(prefix="lm27t_wp15_"))
        try:
            rc = M.run(["--kind", "mail", "--pc", PC, "--in-dir", str(tmp), "--events", "off"], paths=Paths(TREE),
                       cfg=load_config(Paths(TREE)), now=NOW, err=err)
        finally:
            events.configure("text")
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertEqual(rc, 3)
        res = json.loads(err.getvalue().splitlines()[-1])["_status"]
        self.assertIn("R-TRANSPORT", res["reasons"])
        self.assertIn("import_error", res["counts"])


if __name__ == "__main__":
    unittest.main()
