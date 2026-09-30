"""PC recollection keeps older evidence; all collector runs use synthetic TEMP input."""

import contextlib
import csv
from datetime import datetime
import importlib.util
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock


PROJECT = Path(__file__).resolve().parents[1]
PC_FIELDS = ["date", "on_hours", "first_on", "last_off", "night_hours", "weekend"]


class PcHistoryPreservationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="lm25-pc-history-")
        cls.base = Path(cls.temp.name).resolve()
        assert cls.base.parent == Path(tempfile.gettempdir()).resolve()
        cls.collect = cls.base / "source" / "collect"
        cls.collect.mkdir(parents=True)
        for name in ("Get-PcOnHistory.ps1", "Get-PcOnHints.py"):
            shutil.copyfile(PROJECT / "LoadMonitor25" / "collect" / name, cls.collect / name)
        spec = importlib.util.spec_from_file_location("synthetic_pc_hints", cls.collect / "Get-PcOnHints.py")
        cls.hints = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.hints)
        cls.ps = shutil.which("powershell") or shutil.which("pwsh")
        if cls.ps is None:
            raise RuntimeError("PowerShell is required for the synthetic event collector tests")

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.case = Path(tempfile.mkdtemp(prefix="case-", dir=self.base))
        self.pc = self.case / "pc"
        self.pc.mkdir()
        self.csv_path = self.pc / "pc_on.csv"
        self.spans_path = self.pc / "pc_spans.csv"

    def write_csv(self, path, fields, rows):
        with path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    def seed(self, spans=(), daily=()):
        parsed = [(datetime.fromisoformat(a), datetime.fromisoformat(b), source) for a, b, source in spans]
        self.hints.write_spans_csv(str(self.spans_path), parsed)
        rows = {k: self.hints._row(k, d) for k, d in self.hints.daily_from_spans(
            self.hints.merge_spans([(a, b) for a, b, _ in parsed])).items()}
        rows.update({r["date"]: r for r in daily})
        self.write_csv(self.csv_path, PC_FIELDS, rows.values())

    def run_history(self, events=(), start="2026-08-01", end="2026-08-31",
                    now="2026-09-01 12:00", boot="2026-12-01 00:00", success=True):
        path = self.case / "events.csv"
        self.write_csv(path, ["t", "kind", "src"],
                       [{"t": t, "kind": kind, "src": src} for t, kind, src in events])
        result = subprocess.run([
            self.ps, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
            str(self.collect / "Get-PcOnHistory.ps1"), "-EventsCsv", str(path), "-OutDir", str(self.pc),
            "-From", start, "-To", end, "-Now", now, "-BootTime", boot,
        ], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=25, check=False)
        if success:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0)
        return result

    def rows(self):
        return self.hints._read_pc_on(str(self.csv_path))

    def spans(self):
        return self.hints.read_spans_csv(str(self.spans_path))

    def assert_consistent(self):
        derived = self.hints.daily_from_spans(self.hints.merge_spans([(a, b) for a, b, _ in self.spans()]))
        rows = self.rows()
        self.assertEqual(set(rows), set(derived))
        for key, value in derived.items():
            expected = self.hints._row(key, value)
            self.assertAlmostEqual(float(rows[key]["on_hours"]), float(expected["on_hours"]))
            self.assertAlmostEqual(float(rows[key]["night_hours"]), float(expected["night_hours"]))
            self.assertEqual(rows[key]["first_on"], expected["first_on"])
            self.assertEqual(rows[key]["last_off"], expected["last_off"])

    def test_rolled_over_log_preserves_months_already_collected(self):
        self.seed([("2026-01-05 09:00", "2026-01-05 17:00", "event")])
        self.run_history([("2026-08-24 09:00", "on", "6005"), ("2026-08-24 17:00", "off", "6006")],
                         start="2026-01-01")
        self.assertEqual(set(self.rows()), {"2026-01-05", "2026-08-24"})
        self.assert_consistent()

    def test_same_day_prefix_and_tail_outside_query_are_both_kept(self):
        self.seed([("2026-08-23 22:00", "2026-08-25 02:00", "event")])
        self.run_history([("2026-08-24 10:00", "on", "6005"), ("2026-08-24 12:00", "off", "6006")],
                         start="2026-08-24", end="2026-08-24")
        rows = self.rows()
        self.assertEqual([float(rows[d]["on_hours"]) for d in sorted(rows)], [2, 12, 2])
        self.assert_consistent()

    def test_first_event_off_keeps_the_earlier_part_of_that_day(self):
        self.seed([("2026-08-24 09:00", "2026-08-24 17:00", "event")])
        self.run_history([("2026-08-24 12:00", "off", "6006"), ("2026-08-24 14:00", "on", "6005"),
                          ("2026-08-24 18:00", "off", "6006")])
        self.assertEqual(float(self.rows()["2026-08-24"]["on_hours"]), 7)
        self.assert_consistent()

    def test_no_events_and_no_reachable_boot_preserve_all_known_evidence(self):
        self.seed([("2026-01-05 09:00", "2026-01-05 17:00", "event"),
                   ("2026-08-24 21:00", "2026-08-24 22:00", "hint")])
        before = self.spans()
        self.run_history(start="2026-01-01")
        self.assertEqual(before, self.spans())
        self.assert_consistent()
        diagnostic = json.loads((self.pc / "pc_source.json").read_text(encoding="utf-8-sig"))
        self.assertEqual(diagnostic["replaced_from"], "")

    def test_empty_log_boot_fallback_does_not_expand_existing_observed_day(self):
        self.seed([("2026-08-24 09:00", "2026-08-24 10:00", "event")])
        self.run_history(start="2026-08-24", end="2026-08-25", now="2026-08-25 12:00",
                         boot="2026-08-24 07:00")
        self.assertEqual(float(self.rows()["2026-08-24"]["on_hours"]), 1)
        self.assertEqual(float(self.rows()["2026-08-25"]["on_hours"]), 12)
        self.assert_consistent()

    def test_event_refresh_keeps_independent_hints_inside_the_reached_window(self):
        self.seed([("2026-08-24 13:00", "2026-08-24 14:00", "hint")])
        self.run_history([("2026-08-24 10:00", "on", "6005"), ("2026-08-24 12:00", "off", "6006")])
        self.assertEqual(float(self.rows()["2026-08-24"]["on_hours"]), 3)
        self.assertIn("hint", [src for _, _, src in self.spans()])
        self.assert_consistent()

    def test_future_events_and_future_stored_spans_do_not_become_pc_time(self):
        self.seed([("2026-08-26 09:00", "2026-08-26 17:00", "event")])
        self.run_history([("2026-08-25 10:00", "on", "6005"), ("2026-08-25 17:00", "off", "6006")],
                         end="2026-08-27", now="2026-08-25 12:00", boot="2026-08-25 08:00")
        self.assertEqual(set(self.rows()), {"2026-08-25"})
        self.assertEqual(float(self.rows()["2026-08-25"]["on_hours"]), 2)
        self.assertTrue(all(b <= datetime(2026, 8, 25, 12) for _, b, _ in self.spans()))
        self.assert_consistent()

    def test_recollection_is_idempotent_with_overlapping_hints(self):
        self.seed([("2026-01-05 09:00", "2026-01-05 17:00", "event"),
                   ("2026-08-24 11:00", "2026-08-24 13:00", "hint")])
        events = [("2026-08-24 10:00", "on", "6005"), ("2026-08-24 12:00", "off", "6006")]
        self.run_history(events)
        before = self.rows(), self.spans()
        self.run_history(events)
        self.assertEqual(before, (self.rows(), self.spans()))
        self.assert_consistent()

    def test_legacy_daily_rows_outside_reach_are_not_discarded_or_invented_as_spans(self):
        self.seed(daily=[{"date": "2026-01-05", "on_hours": "8", "first_on": "09:00", "last_off": "17:00",
                         "night_hours": "0", "weekend": "0"}])
        self.run_history([("2026-08-24 10:00", "on", "6005"), ("2026-08-24 12:00", "off", "6006")],
                         start="2026-01-01")
        self.assertEqual(float(self.rows()["2026-01-05"]["on_hours"]), 8)
        self.assertTrue(all(a.month == 8 for a, _, _ in self.spans()))

    def test_invalid_period_does_not_replace_existing_files(self):
        self.seed([("2026-08-24 09:00", "2026-08-24 17:00", "event")])
        before = self.csv_path.read_bytes(), self.spans_path.read_bytes()
        self.run_history(start="2026-08-31", end="2026-08-01", success=False)
        self.assertEqual(before, (self.csv_path.read_bytes(), self.spans_path.read_bytes()))

    def test_partial_event_recollection_keeps_legacy_daily_bound_on_every_repeat(self):
        self.seed(daily=[{"date": "2026-08-24", "on_hours": "8", "first_on": "09:00", "last_off": "17:00",
                         "night_hours": "0", "weekend": "0"}])
        events = [("2026-08-24 14:00", "on", "6005"), ("2026-08-24 16:00", "off", "6006")]
        for _ in range(2):
            self.run_history(events)
            row = self.rows()["2026-08-24"]
            self.assertEqual((float(row["on_hours"]), row["first_on"], row["last_off"]), (8, "09:00", "17:00"))
            self.assertEqual(sum((b - a).total_seconds() for a, b, _ in self.spans()) / 3600, 2)
        diagnostic = json.loads((self.pc / "pc_source.json").read_text(encoding="utf-8-sig"))
        self.assertEqual(diagnostic["preserved_legacy_days"], 1)

    def test_future_span_correction_is_not_mistaken_for_legacy_daily_bound(self):
        self.seed([("2026-08-24 09:00", "2026-08-24 17:00", "event")])
        self.run_history([("2026-08-24 10:00", "on", "6005"), ("2026-08-24 11:00", "off", "6006")],
                         start="2026-08-24", end="2026-08-24", now="2026-08-24 12:00")
        self.assertEqual(float(self.rows()["2026-08-24"]["on_hours"]), 2)
        self.assert_consistent()

    def merge_hints(self, incoming=(), start="2026-08-24", end="2026-08-25", now="2026-09-01 12:00"):
        spans = [(datetime.fromisoformat(a), datetime.fromisoformat(b)) for a, b in incoming]
        return self.hints.merge_pc_on(str(self.csv_path), self.hints.daily_from_spans(spans), spans,
                                     str(self.spans_path), datetime.fromisoformat(start),
                                     datetime.fromisoformat(end), datetime.fromisoformat(now))

    def test_narrow_hint_refresh_keeps_both_midnight_boundary_pieces(self):
        self.seed([("2026-08-23 23:00", "2026-08-24 01:00", "hint"),
                   ("2026-08-24 23:00", "2026-08-25 01:00", "hint")])
        self.merge_hints([("2026-08-24 10:00", "2026-08-24 11:00")])
        self.assertEqual([float(self.rows()[d]["on_hours"]) for d in sorted(self.rows())], [1, 3, 1])
        self.assert_consistent()

    def test_hint_rollover_or_empty_read_does_not_erase_same_period_observations(self):
        self.seed([("2026-08-24 09:00", "2026-08-24 10:00", "hint")])
        self.merge_hints([("2026-08-24 14:00", "2026-08-24 15:00")])
        before = self.rows(), self.spans()
        self.merge_hints()
        self.assertEqual(before, (self.rows(), self.spans()))
        self.assertEqual(float(self.rows()["2026-08-24"]["on_hours"]), 2)
        self.assert_consistent()

    def test_partial_hint_recollection_keeps_legacy_daily_bound_on_every_repeat(self):
        self.seed(daily=[{"date": "2026-08-24", "on_hours": "8", "first_on": "09:00", "last_off": "17:00",
                         "night_hours": "0", "weekend": "0"}])
        for _ in range(2):
            self.merge_hints([("2026-08-24 14:00", "2026-08-24 15:00")])
            self.assertEqual(float(self.rows()["2026-08-24"]["on_hours"]), 8)
            self.assertEqual(sum((b - a).total_seconds() for a, b, _ in self.spans()) / 3600, 1)

    def test_hint_future_span_correction_is_not_mistaken_for_legacy_daily_bound(self):
        self.seed([("2026-08-24 09:00", "2026-08-24 17:00", "event")])
        self.merge_hints([("2026-08-24 10:00", "2026-08-24 10:05")], now="2026-08-24 12:00")
        self.assertEqual(float(self.rows()["2026-08-24"]["on_hours"]), 3)
        self.assert_consistent()

    def test_discarded_future_hint_spans_do_not_leave_phantom_daily_rows(self):
        self.seed([("2026-08-23 09:00", "2026-08-23 10:00", "hint"),
                   ("2026-08-24 14:00", "2026-08-24 16:00", "hint"),
                   ("2026-08-25 09:00", "2026-08-25 17:00", "event")])
        self.merge_hints(now="2026-08-24 12:00")
        self.assertEqual(set(self.rows()), {"2026-08-23"})
        self.assert_consistent()

    def test_hint_union_does_not_double_count_or_grow_on_repeat(self):
        self.seed([("2026-08-24 09:00", "2026-08-24 12:00", "event"),
                   ("2026-08-24 11:00", "2026-08-24 14:00", "hint")])
        incoming = [("2026-08-24 13:00", "2026-08-24 15:00")]
        self.merge_hints(incoming)
        before = self.rows(), self.spans()
        self.merge_hints(incoming)
        self.assertEqual(before, (self.rows(), self.spans()))
        self.assertEqual(float(self.rows()["2026-08-24"]["on_hours"]), 6)
        self.assert_consistent()

    def test_hint_tail_stops_at_query_end_and_now(self):
        self.seed()
        self.merge_hints([("2026-08-24 23:59", "2026-08-25 00:04")], now="2026-08-24 23:59:30")
        self.assertEqual(set(self.rows()), {"2026-08-24"})
        self.assertEqual(self.spans()[0][1], datetime(2026, 8, 24, 23, 59, 30))
        self.assert_consistent()

    def test_no_new_browser_or_sampler_evidence_leaves_prior_files_unchanged(self):
        self.seed([("2026-08-24 09:00", "2026-08-24 10:00", "hint")])
        before = self.csv_path.read_bytes(), self.spans_path.read_bytes()
        with mock.patch.object(self.hints, "ROOT", str(self.case)), \
                mock.patch.object(self.hints, "history_files", return_value=[]), \
                mock.patch.object(self.hints, "sampler_times", return_value=[]), \
                mock.patch.object(self.hints.sys, "argv", ["Get-PcOnHints.py", "--from", "2026-08-01", "--to", "2026-08-31"]), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.hints.main(), 0)
        self.assertEqual(before, (self.csv_path.read_bytes(), self.spans_path.read_bytes()))


if __name__ == "__main__":
    unittest.main()
