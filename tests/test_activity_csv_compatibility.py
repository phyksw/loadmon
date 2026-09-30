"""Collected activity must survive supported CSV encodings and long, valid fields."""

import ast
import csv
import unittest

import test_activity_trend as activity_fixture


class ActivityCsvCompatibilityTests(unittest.TestCase):
    def setUp(self):
        # Reuse only the isolated harness, not its test cases. All source inputs are TEMP CSVs.
        self.fixture = activity_fixture.ActivityTrendTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.addCleanup(csv.field_size_limit, csv.field_size_limit())
        self.ns = self.fixture.ns
        tree = ast.parse(activity_fixture.SOURCE.read_text(encoding="utf-8-sig"))
        exists = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_has_collected")
        exec(compile(ast.Module(body=[exists], type_ignores=[]), str(activity_fixture.SOURCE), "exec"), self.ns)

    def write(self, rows, encoding):
        target = self.fixture.data / "files" / "files.csv"
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding=encoding, newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        return target

    def assert_collected(self, target, expected):
        before = target.read_bytes()
        payload = self.ns["activity_payload"]("2026-01-01", "2026-01-31")
        self.assertEqual(payload["trend_info"]["raw_n"], expected)
        self.assertEqual(payload["trend_info"]["counted"], expected)
        self.assertEqual(payload["trend_info"]["duplicates"], 0)
        self.assertEqual(payload["trend_info"]["read_issues"], [])
        self.assertTrue(self.ns["_has_collected"]())
        self.assertEqual(target.read_bytes(), before)

    def test_cp949_distinct_names_are_not_decoded_into_false_duplicates(self):
        rows = [{"mtime": "2026-01-05 09:00", "folder": "SYNTHETIC", "name": name}
                for name in ("가.docx", "나.docx")]
        target = self.write(rows, "cp949")
        decoded = self.ns["_rows"](str(target))
        self.assertEqual([row["name"] for row in decoded], [row["name"] for row in rows])
        self.assert_collected(target, 2)

    def test_utf16_bom_keeps_date_columns_and_activity_counts(self):
        rows = [{"mtime": f"2026-01-{day:02d} 09:00", "folder": "SYNTHETIC", "name": f"기록-{day}.docx"}
                for day in (5, 7)]
        target = self.write(rows, "utf-16")
        self.assertEqual(self.ns["dash_period"]({}, {}), ["2026-01-05", "2026-01-07"])
        self.assert_collected(target, 2)

    def test_one_long_valid_field_does_not_discard_the_entire_file(self):
        rows = [{"mtime": f"2026-01-{day:02d} 09:00", "folder": "SYNTHETIC", "name": f"design-{day}.docx",
                 "observation_note": "X" * 140000 if day == 6 else "synthetic note"}
                for day in (5, 6, 7)]
        target = self.write(rows, "utf-8-sig")
        decoded = self.ns["_rows"](str(target))
        self.assertEqual(len(decoded), 3)
        self.assertEqual(len(decoded[1]["observation_note"]), 140000)
        self.assertEqual(self.ns["dash_period"]({}, {}), ["2026-01-05", "2026-01-07"])
        self.assert_collected(target, 3)

    def test_read_failure_is_visible_then_clears_after_successful_reread(self):
        target = self.fixture.data / "files" / "files.csv"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"mtime,folder,name\n2026-01-05 09:00,SYNTHETIC,\xff\n")
        bad = self.ns["activity_payload"]("2026-01-01", "2026-01-31")
        self.assertEqual(bad["trend_info"]["counted"], 0)
        self.assertEqual(len(bad["trend_info"]["read_issues"]), 1)
        self.assertTrue(bad["trend_info"]["read_issues"][0]["file"].endswith("files.csv"))
        self.assertFalse(self.ns["_has_collected"]())
        self.write([{"mtime": "2026-01-05 09:00", "folder": "SYNTHETIC", "name": "recovered.docx"}], "utf-8-sig")
        self.assert_collected(target, 1)


if __name__ == "__main__":
    unittest.main()
