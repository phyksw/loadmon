"""Measurement evidence contracts: partial PC history and generated artifacts, synthetic only."""

import copy
import csv
from datetime import date, datetime, timedelta
import importlib.util
import json
import math
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest import mock


PROJECT = Path(__file__).resolve().parents[1]


class MeasurementRedesignTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="lm25-measurement-redesign-")
        cls.base = Path(cls.temp.name).resolve()
        assert cls.base.parent == Path(tempfile.gettempdir()).resolve()
        target = cls.base / "source" / "core" / "extract.py"
        target.parent.mkdir(parents=True)
        shutil.copyfile(PROJECT / "LoadMonitor25/core/extract.py", target)
        shutil.copyfile(PROJECT / "LoadMonitor25/core/collection_state.py", target.parent / "collection_state.py")
        spec = importlib.util.spec_from_file_location("synthetic_measurement_redesign", target)
        cls.module = importlib.util.module_from_spec(spec)
        with mock.patch.object(sys, "path", [str(target.parent), *sys.path]):
            spec.loader.exec_module(cls.module)
        cls.defaults = json.loads((PROJECT / "LoadMonitor25/config/config.default.json").read_text(encoding="utf-8-sig"))

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.data = Path(tempfile.mkdtemp(prefix="case-", dir=self.base)) / "data"
        self.data.mkdir()
        self.cfg = copy.deepcopy(self.defaults)
        self.cfg["owner"] = "SYNTHETIC"
        self.cfg["excludePathKeywords"] = []
        self.day = date(2026, 8, 24)
        self.now = datetime(2026, 9, 1, 12)
        self.m = self.module

    def write(self, relative, fields, rows):
        target = self.data / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        return target

    def pc(self, hours=8, first="09:00", last="17:00", night=0, root=""):
        self.write(root + "pc/pc_on.csv", ["date", "on_hours", "night_hours", "first_on", "last_off", "weekend"],
                   [{"date": str(self.day), "on_hours": hours, "night_hours": night,
                     "first_on": first, "last_off": last, "weekend": 0}])

    def spans(self, ranges=(), root=""):
        self.write(root + "pc/pc_spans.csv", ["start", "end", "src"],
                   [{"start": f"{self.day} {a}:00", "end": f"{self.day} {b}:00", "src": "event"} for a, b in ranges])

    def signal(self, hour=15):
        return [(datetime(2026, 8, 24, hour), "파일", "synthetic_design.docx", 3, "SYNTHETIC")]

    def measure(self, signals=None, file_times=None):
        return self.m.day_work_hours(str(self.data), signals if signals is not None else self.signal(),
                                     self.day, self.day, self.cfg, now=self.now,
                                     file_times={} if file_times is None else file_times)

    def total(self, result):
        return round(sum(result[0].values()), 4)

    def test_partial_pc_spans_do_not_discard_legacy_daily_total(self):
        for hours, expected in ((8, 6.67), (6, 6.0)):
            with self.subTest(hours=hours):
                self.pc(hours)
                self.spans()
                baseline = self.measure()
                self.spans([("14:00", "16:00")])
                actual = self.measure()
                self.assertEqual(self.total(baseline), expected)
                self.assertEqual(self.total(actual), expected)
                info = actual[1]
                self.assertEqual(info["pc_partial_observation_days"], 1)
                self.assertEqual(info["pc_unplaced_h"], hours - 2)
                self.assertTrue(info["pc_observation_basis"][str(self.day)]["partial"])
                self.assertTrue(any("위치 미확인" in text for text in info["coverage"]["reasons"]))
                self.assertNotEqual(info["coverage"]["grade"], "reliable")
                # A repeat is deterministic; the source aggregate and partial intervals remain unchanged.
                self.assertEqual(actual, self.measure())

    def test_complete_pc_spans_keep_existing_estimate_and_four_result_contract(self):
        self.pc()
        self.spans([("09:00", "17:00")])
        basis = {}
        result = self.m.pc_daily(str(self.data), self.day, self.day, basis=basis)
        self.assertEqual(len(result), 4)
        self.assertEqual(self.total(self.measure()), 6.67)
        self.assertFalse(basis[self.day]["partial"])
        self.assertEqual(basis[self.day]["unplaced_h"], 0)

    def test_signal_outside_partial_pc_range_is_preserved(self):
        self.pc()
        baseline = self.measure(self.signal(10))
        self.spans([("14:00", "16:00")])
        self.assertEqual(self.total(self.measure(self.signal(10))), self.total(baseline))

    def test_legacy_total_without_first_or_last_keeps_its_unplaced_budget(self):
        self.pc(first="", last="")
        baseline = self.total(self.measure())
        self.assertEqual(baseline, 7.0)
        for ranges in ([("14:00", "16:00")], [("21:00", "23:00")]):
            with self.subTest(ranges=ranges):
                self.spans(ranges)
                for _ in range(3):
                    actual = self.measure()
                    self.assertEqual(self.total(actual), baseline)
                    self.assertTrue(actual[1]["pc_observation_basis"][str(self.day)]["floor_window_unknown"])

    def test_partial_night_spans_do_not_relocate_legacy_day_total(self):
        self.pc()
        baseline = self.total(self.measure())
        self.spans([("21:00", "23:00")])
        actual = self.measure()
        self.assertEqual(self.total(actual), baseline)
        self.assertEqual(actual[1]["evening_credit_h"], 0)
        self.assertEqual(actual[1]["pc_unplaced_h"], 8)
        pc, _, known, _ = self.m.pc_daily(str(self.data), self.day, self.day)
        self.assertEqual(pc[self.day][:2], (8.0, 0.0))
        self.assertEqual(known[self.day], [(21 * 60.0, 23 * 60.0)])

    def test_equal_span_total_in_a_different_time_zone_is_still_partial(self):
        self.pc()
        baseline = self.total(self.measure())
        self.spans([("09:00", "13:00"), ("19:00", "23:00")])
        actual = self.measure()
        self.assertEqual(self.total(actual), baseline)
        basis = actual[1]["pc_observation_basis"][str(self.day)]
        self.assertTrue(basis["partial"])
        self.assertEqual(basis["roots"][0]["observed_span_h"], 8)
        self.assertEqual(basis["roots"][0]["represented_aggregate_h"], 4)
        self.assertEqual(basis["unplaced_h"], 4)

    def test_partial_night_and_human_trace_preserve_existing_night_budget(self):
        self.pc(10, last="22:00", night=2)
        baseline = self.measure(self.signal(20))
        self.spans([("20:00", "22:00")])
        actual = self.measure(self.signal(20))
        self.assertEqual(self.total(actual), self.total(baseline))
        self.assertEqual(actual[1]["evening_credit_h"], baseline[1]["evening_credit_h"])
        self.assertLessEqual(actual[1]["evening_credit_h"], 2)

    def test_overlapping_complete_and_partial_pc_do_not_double_legacy_budget(self):
        self.pc()
        self.pc(root="추가PC/PC-B/")
        self.spans([("09:00", "17:00")], root="추가PC/PC-B/")
        baseline = self.total(self.measure())
        self.spans([("14:00", "16:00")])
        self.assertEqual(self.total(self.measure()), baseline)
        pc, _, known, _ = self.m.pc_daily(str(self.data), self.day, self.day)
        self.assertEqual(pc[self.day][0], 8)
        self.assertEqual(self.m._union_min(known[self.day]) / 60, 8)

    def test_two_pc_partial_evidence_does_not_replace_other_pc_or_expand_raw_spans(self):
        self.pc()
        self.pc(4, "00:00", "04:00", night=4, root="추가PC/PC-B/")
        self.spans([("00:00", "04:00")], root="추가PC/PC-B/")
        before = self.total(self.measure())
        self.spans([("14:00", "16:00")])
        actual = self.measure()
        self.assertEqual(self.total(actual), before)
        result = self.m.pc_daily(str(self.data), self.day, self.day)
        self.assertEqual(self.m._union_min(result[2][self.day]) / 60, 6)
        self.assertEqual(actual[1]["pc_unplaced_h"], 6)

    def test_meeting_outside_pc_window_is_not_absorbed_by_partial_fallback(self):
        self.pc()
        self.write("outlook/calendar.csv", ["start", "end", "subject", "busy_status", "meeting_status", "response_status", "all_day"],
                   [{"start": "2026-08-24 08:00", "end": "2026-08-24 09:00", "subject": "SYNTHETIC REVIEW",
                     "busy_status": 2, "meeting_status": 1, "response_status": 3, "all_day": False}])
        before = self.total(self.measure())
        self.spans([("14:00", "16:00")])
        self.assertEqual(self.total(self.measure()), before)
        self.assertGreater(before, 6.67)

    def samples(self, idle=1, title="SYNTHETIC REVIEW", process="femap", count=60):
        start = datetime(2026, 8, 24, 14)
        self.write("activity/activity_20260824.csv", ["time", "process", "title", "idle_sec", "solvers_running"],
                   [{"time": (start + timedelta(minutes=i)).isoformat(sep=" "), "process": process,
                     "title": title, "idle_sec": idle, "solvers_running": "nastran"} for i in range(count)])

    def test_partial_aggregate_floor_does_not_restore_excluded_sampler_activity(self):
        self.pc()
        self.samples(title="PRIVATE_SYNTHETIC")
        self.cfg["excludePathKeywords"] = ["PRIVATE_SYNTHETIC"]
        before = self.total(self.measure(self.signal(10)))
        self.spans([("14:00", "16:00")])
        actual = self.total(self.measure(self.signal(10)))
        self.assertEqual(actual, before)
        self.assertLess(actual, 6.67)

    def test_partial_evidence_and_daily_scalar_are_clamped_at_now(self):
        self.pc()
        self.spans([("14:00", "16:00")])
        self.now = datetime(2026, 8, 24, 12)
        basis = {}
        pc, _, spans, _ = self.m.pc_daily(str(self.data), self.day, self.day, basis=basis, now=self.now)
        self.assertLessEqual(pc[self.day][0], 3)
        self.assertFalse(spans)
        self.assertLessEqual(self.total(self.measure(self.signal(10))), 3)

    def test_nonfinite_pc_scalar_cannot_become_an_unplaced_budget(self):
        for bad in ("nan", "inf", "-inf"):
            with self.subTest(bad=bad):
                self.pc(bad)
                self.spans([("14:00", "16:00")])
                basis = {}
                result = self.m.pc_daily(str(self.data), self.day, self.day, basis=basis)
                self.assertNotIn(self.day, result[0])
                self.assertEqual(basis[self.day]["unplaced_h"], 0)
                self.assertTrue(math.isfinite(self.total(self.measure())))

    def test_current_day_unplaced_budget_cannot_fill_future_daytime(self):
        self.pc(first="", last="")
        self.spans([("10:00", "11:00")])
        self.now = datetime(2026, 8, 24, 12)
        result = self.measure(self.signal(10))
        self.assertLessEqual(self.total(result), 4)
        self.assertGreater(self.total(result), 0)

    def outputs(self, count, ext=".op2", human_document=False, origin=""):
        rows = [{"name": f"job{i}{ext}", "ext": ext, "folder": str(self.data / "synthetic_outputs"),
                 "mtime": "2026-08-24 10:00:00", "author": "SYNTHETIC", "origin": origin} for i in range(count)]
        if human_document:
            rows.append({"name": "review.docx", "ext": ".docx", "folder": str(self.data / "synthetic_outputs"),
                         "mtime": "2026-08-24 10:00:00", "author": "SYNTHETIC", "origin": ""})
        return self.write("files/files.csv", ["name", "ext", "folder", "mtime", "author", "origin"], rows)

    def measure_files(self):
        signals, meta = self.m.load_signals(str(self.data), self.day, self.day, cfg=self.cfg)
        return self.measure(signals, meta["file_times"]), signals, meta

    def test_generated_result_count_never_creates_a_human_session(self):
        self.pc(9, last="18:00")
        for count in (1, 7, 8, 39, 40, 80):
            with self.subTest(count=count):
                path = self.outputs(count)
                before = path.read_bytes()
                result, signals, meta = self.measure_files()
                self.assertEqual(self.total(result), 0)
                self.assertEqual(dict(meta["counted"]), {"파일(해석출력)": 1})
                self.assertEqual(sum(s[3] for s in signals), 1.5)
                self.assertEqual(path.read_bytes(), before, "Raw artifact evidence must remain intact")

    def test_explicit_generated_origin_handles_generic_file_without_blanket_extension_rule(self):
        self.pc(9, last="18:00")
        for count in (1, 39, 40):
            with self.subTest(count=count):
                self.outputs(count, ext=".csv", origin="generated")
                self.assertEqual(self.total(self.measure_files()[0]), 0)
        self.outputs(1, ext=".csv")
        self.assertGreater(self.total(self.measure_files()[0]), 0)

    def test_solver_results_do_not_hide_a_human_document_saved_in_the_same_minute(self):
        self.pc(9, last="18:00")
        totals = []
        for count in (1, 39, 40, 80):
            self.outputs(count, human_document=True)
            result, signals, meta = self.measure_files()
            totals.append(self.total(result))
            self.assertEqual(dict(meta["counted"]), {"파일(해석출력)": 1, "파일": 1})
            self.assertEqual(sum(s[3] for s in signals), 4.5)
        self.assertEqual(totals, [7.67] * 4)

    def test_independent_active_gui_review_still_counts_with_any_result_count(self):
        self.pc(9, last="18:00")
        self.samples()
        totals = []
        for count in (1, 39, 40):
            self.outputs(count)
            result, _, _ = self.measure_files()
            totals.append(self.total(result))
        self.assertGreater(totals[0], 0)
        self.assertEqual(totals, [totals[0]] * 3)

    def test_idle_background_solver_is_not_a_human_review(self):
        self.pc(9, last="18:00")
        self.samples(idle=3600, process="nastran")
        for count in (1, 39, 40):
            self.outputs(count)
            self.assertEqual(self.total(self.measure_files()[0]), 0)

    def test_recent_result_view_stays_a_weak_view_signal_not_a_whole_workday(self):
        self.pc(9, last="18:00")
        self.write("files/recent.csv", ["name", "ext", "folder", "mtime", "target_mtime", "author"],
                   [{"name": "job.op2", "ext": ".op2", "folder": str(self.data / "synthetic_outputs"),
                     "mtime": "2026-08-24 10:00:00", "target_mtime": "2026-08-23 10:00:00", "author": "SYNTHETIC"}])
        result, _, meta = self.measure_files()
        self.assertEqual(dict(meta["counted"]), {"파일(열람)": 1})
        self.assertLessEqual(self.total(result), 0.09)
        self.assertEqual(result[1]["pc_floor_h"], 0)

    def test_normal_document_and_code_file_evidence_stays_productive(self):
        self.pc(9, last="18:00")
        for ext in (".docx", ".pptx", ".py", ".rst", ".odb"):
            with self.subTest(ext=ext):
                self.outputs(1, ext=ext)
                result, _, meta = self.measure_files()
                self.assertGreater(self.total(result), 0)
                self.assertNotIn("파일(해석출력)", meta["counted"])


if __name__ == "__main__":
    unittest.main()
