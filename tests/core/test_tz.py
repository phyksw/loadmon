# -*- coding: utf-8 -*-
"""WP-02 시간대 시험 — 계약 §2.1 `tz.py` · §4.1(run_id·job_id, CR-01) · §9.4 · X-172 · CP §13.2 · L-04.

PC 시간대를 바꾸지 않는다. 일광 절약 규칙은 합성 TIME_ZONE_INFORMATION 으로 Win32 변환을 시험한다.
"""
import ast
import re
import sys
import unittest
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path

from lm27.util import tz

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "lm27" / "util" / "tz.py"
RUN_RE = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{4}$")
JOB_RE = re.compile(r"^j\d{14}[0-9a-f]{4}$")
WIN = sys.platform == "win32"


def u(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=UTC)


def tzi(bias, std=None, dst=None, std_bias=0, dst_bias=-60):
    """합성 TIME_ZONE_INFORMATION — std/dst = (월, 요일 0=일, 몇째 1~5(5=마지막), 시)."""
    t = tz._TZI()
    t.Bias, t.StandardBias, t.DaylightBias = bias, std_bias, (dst_bias if dst else 0)
    if std and dst:
        t.StandardDate = tz._SYSTEMTIME(0, std[0], std[1], std[2], std[3], 0, 0, 0)
        t.DaylightDate = tz._SYSTEMTIME(0, dst[0], dst[1], dst[2], dst[3], 0, 0, 0)
    return t


class CaptureOffsetTest(unittest.TestCase):
    SAMPLES = ("2025-01-15T03:00:00", "2025-07-15T03:00:00", "2026-03-10T00:00:00", "2026-10-05T00:00:00",
               "2026-12-31T23:30:00", "2027-06-30T12:00:00")

    def test_int_and_matches_crt(self):
        for s in self.SAMPLES:
            off = tz.capture_offset_min(u(s))
            self.assertIsInstance(off, int)
            self.assertNotIsInstance(off, bool)
            self.assertLessEqual(abs(off), tz.OFFSET_LIMIT_MIN)
            self.assertEqual(off, tz._offset_crt(u(s)), s)

    @unittest.skipUnless(WIN, "Win32 전용")
    def test_win32_ctypes_path_used(self):
        for s in self.SAMPLES:
            self.assertEqual(tz._offset_win(u(s)), tz.capture_offset_min(u(s)))
        self.assertIsInstance(tz._offset_win(datetime.now(UTC)), int)

    def test_input_forms(self):
        a = tz.capture_offset_min(u("2026-07-01T12:00:00"))
        self.assertEqual(tz.capture_offset_min(datetime(2026, 7, 1, 12, 0)), a, "naive = UTC")
        self.assertEqual(tz.capture_offset_min(datetime(2026, 7, 1, 21, 0, tzinfo=timezone(timedelta(hours=9)))), a)
        self.assertEqual(tz.capture_offset_min("2026-07-01T12:00:00Z"), a)
        now = tz.capture_offset_min()
        self.assertIsInstance(now, int)
        with self.assertRaises(TypeError):
            tz.capture_offset_min(12345)
        with self.assertRaises(TypeError):
            tz.capture_offset_min(date(2026, 7, 1))
        with self.assertRaises(ValueError):
            tz.capture_offset_min("어제 저녁")

    @unittest.skipUnless(WIN, "Win32 전용")
    def test_dst_rules_northern(self):
        east = tzi(300, std=(11, 0, 1, 2), dst=(3, 0, 2, 2))      # 미국 동부형: 3월 둘째 일 2시 ~ 11월 첫째 일 2시
        want = {"2026-07-01T12:00:00": -240, "2026-01-15T12:00:00": -300,
                "2026-03-08T06:59:00": -300, "2026-03-08T07:00:00": -240,
                "2026-11-01T05:59:00": -240, "2026-11-01T06:00:00": -300}
        self.assertEqual({k: tz._offset_with_tzi(u(k), east) for k in want}, want)

    @unittest.skipUnless(WIN, "Win32 전용")
    def test_dst_rules_southern_and_fractional(self):
        south = tzi(-600, std=(4, 0, 1, 3), dst=(10, 0, 1, 2))    # 남반구형: 10월 첫째 일 ~ 4월 첫째 일
        self.assertEqual(tz._offset_with_tzi(u("2026-07-01T00:00:00"), south), 600)
        self.assertEqual(tz._offset_with_tzi(u("2026-01-15T00:00:00"), south), 660)
        self.assertEqual(tz._offset_with_tzi(u("2026-01-01T00:00:00"), tzi(-330)), 330)
        self.assertEqual(tz._offset_with_tzi(u("2026-01-01T00:00:00"), tzi(-345)), 345)
        self.assertEqual(tz._offset_with_tzi(u("2026-01-01T00:00:00"), tzi(-540)), 540)
        self.assertIsNone(tz._offset_with_tzi(datetime(1500, 1, 1), tzi(-540)), "SYSTEMTIME 범위 밖")


class FmtParseTest(unittest.TestCase):
    def test_fmt(self):
        self.assertEqual(tz.fmt_offset(540), "+09:00")
        self.assertEqual(tz.fmt_offset(-330), "-05:30")
        self.assertEqual(tz.fmt_offset(0), "+00:00")
        self.assertEqual(tz.fmt_offset(345), "+05:45")
        self.assertEqual(tz.fmt_offset(-720), "-12:00")
        self.assertEqual(tz.fmt_offset(840), "+14:00")
        for bad, exc in ((841, ValueError), (-841, ValueError), (9.0, TypeError), (True, TypeError),
                         ("+09:00", TypeError), (None, TypeError)):
            with self.assertRaises(exc, msg=repr(bad)):
                tz.fmt_offset(bad)

    def test_parse(self):
        good = {"+09:00": 540, "-05:30": -330, "+00:00": 0, "-00:00": 0, "Z": 0, "+0900": 540,
                " +09:00 ": 540, "+14:00": 840, "-12:00": -720}
        self.assertEqual({k: tz.parse_offset(k) for k in good}, good)
        for bad in ("09:00", "+9:00", "+09:60", "+15:00", "", "+09", "UTC", "z", "+09:00:00", "−09:00"):
            with self.assertRaises(ValueError, msg=repr(bad)):
                tz.parse_offset(bad)
        with self.assertRaises(TypeError):
            tz.parse_offset(540)

    def test_round_trip_every_minute(self):
        for m in range(-tz.OFFSET_LIMIT_MIN, tz.OFFSET_LIMIT_MIN + 1):
            s = tz.fmt_offset(m)
            self.assertRegex(s, r"^[+-]\d{2}:\d{2}$")
            self.assertEqual(tz.parse_offset(s), m)
        self.assertEqual(tz.fmt_offset(tz.parse_offset("-00:00")), "+00:00")


class ToLocalTest(unittest.TestCase):
    def test_conversion(self):
        loc = tz.to_local("2026-10-05T00:30:00Z", 540)
        self.assertEqual(loc.replace(tzinfo=None), datetime(2026, 10, 5, 9, 30))
        self.assertEqual(loc.utcoffset(), timedelta(minutes=540))
        loc = tz.to_local("2026-09-30T15:30:00Z", "+09:00")
        self.assertEqual((loc.date(), loc.hour, loc.minute), (date(2026, 10, 1), 0, 30), "날짜가 바뀐다")
        loc = tz.to_local(datetime(2026, 1, 1, 3, 0), -300)
        self.assertEqual(loc.replace(tzinfo=None), datetime(2025, 12, 31, 22, 0), "naive = UTC")
        loc = tz.to_local(datetime(2026, 1, 1, 12, 0, tzinfo=timezone(timedelta(hours=9))), 0)
        self.assertEqual(loc.replace(tzinfo=None), datetime(2026, 1, 1, 3, 0))
        self.assertEqual(tz.to_local("2026-10-05T00:30:00+00:00", 540), tz.to_local("2026-10-05T00:30:00Z", 540))

    def test_errors(self):
        with self.assertRaises(ValueError):
            tz.to_local("2026-13-01T00:00:00Z", 540)
        with self.assertRaises(ValueError):
            tz.to_local("2026-10-05T00:30:00Z", 900)
        with self.assertRaises(ValueError):
            tz.to_local("2026-10-05T00:30:00Z", "KST")
        with self.assertRaises(TypeError):
            tz.to_local(1759622400, 540)


class IdTest(unittest.TestCase):
    def test_run_id(self):
        now = u("2026-10-04T15:30:05")
        local = now + timedelta(minutes=tz.capture_offset_min(now))
        rid = tz.new_run_id(now)
        self.assertRegex(rid, RUN_RE)
        self.assertTrue(rid.startswith(local.strftime("%Y%m%d-%H%M%S-")), (rid, local))
        self.assertRegex(tz.new_run_id(), RUN_RE)
        self.assertRegex(tz.new_run_id("2026-10-04T15:30:05Z"), RUN_RE)
        self.assertGreater(len({tz.new_run_id(now)[-4:] for _ in range(50)}), 1, "무작위 4hex")
        self.assertEqual(len(rid[-8:]), 8, "run8 = 끝 8자")

    def test_job_id(self):
        now = u("2026-10-04T15:30:05")
        local = now + timedelta(minutes=tz.capture_offset_min(now))
        jid = tz.new_job_id(now)
        self.assertRegex(jid, JOB_RE)
        self.assertEqual(jid[1:15], local.strftime("%Y%m%d%H%M%S"))
        self.assertRegex(tz.new_job_id(), JOB_RE)
        self.assertGreater(len({tz.new_job_id(now)[-4:] for _ in range(50)}), 1)


class SourceRulesTest(unittest.TestCase):
    def setUp(self):
        self.text = SRC.read_bytes().decode("utf-8")

    def test_l04_no_tz_database(self):
        for needle in ("zoneinfo" + ".ZoneInfo", "import " + "zoneinfo", "from " + "zoneinfo"):
            self.assertNotIn(needle, self.text)

    def test_stdlib_only_for_agent_bin(self):
        tree = ast.parse(self.text)
        mods = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                mods |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                mods.add((node.module or "").split(".")[0])
        self.assertTrue(mods <= set(sys.stdlib_module_names) | {"__future__"}, mods)

    def test_no_file_writes_no_kill(self):
        self.assertIsNone(re.search(r"\bopen\(", self.text))
        self.assertNotIn("os.kill" + "(", self.text)


if __name__ == "__main__":
    unittest.main()
