"""Small and multi-PC CSV visibility, isolated from application startup and user data."""

import ast
import copy
import csv
import glob
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "LoadMonitor25" / "ui" / "app.py"
PC_HEADER = "date,on_hours,first_on,last_off,night_hours,weekend\n"
PC_ROW = "2026-08-31,8,09:00,17:00,0,0\n"
PC_PATTERNS = ["pc/pc_on.csv", "pc_on.csv", "pc/pc_spans.csv", "pc_spans.csv"]


class DataVisibilityTests(unittest.TestCase):
    def setUp(self):
        # Retain only these synthetic TEMP files; never open an installed data directory.
        self.root = Path(tempfile.mkdtemp(prefix="lm25-data-visibility-"))
        self.data = self.root / "data"
        self.data.mkdir()
        tree = ast.parse(SOURCE.read_text(encoding="utf-8-sig"))
        names = {"_source_files", "_has_collected", "_rows"}
        body = [copy.deepcopy(node) for node in tree.body
                if isinstance(node, ast.FunctionDef) and node.name in names]
        self.assertEqual({node.name for node in body}, names)
        handler = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "H")
        body.append(copy.deepcopy(next(node for node in handler.body
                                       if isinstance(node, ast.FunctionDef) and node.name == "do_GET")))
        self.env = {"os": os, "glob": glob, "csv": csv, "ROOT": str(self.root), "DATA": str(self.data),
                    "TEAM_FILES": {}}
        exec(compile(ast.Module(body=body, type_ignores=[]), str(SOURCE), "exec"), self.env)

    def write(self, relative, text):
        path = self.data / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8-sig")
        return path

    def request(self, source):
        replies = []
        handler = SimpleNamespace(path="/api/data?src=" + source, _send=lambda *args: replies.append(args))
        self.env["do_GET"](handler)
        self.assertEqual(len(replies), 1)
        self.assertEqual(replies[0][0], 200)
        return replies[0][1]

    @staticmethod
    def relative_files(payload):
        return {name.replace("\\", "/") for name in payload["files"]}

    def test_small_standard_pc_csv_counts_as_collected(self):
        path = self.write("pc/pc_on.csv", PC_HEADER + PC_ROW)
        self.assertLess(path.stat().st_size, 200)
        self.assertTrue(self.env["_has_collected"]())

    def test_extra_pc_only_csv_counts_as_collected(self):
        self.write("추가PC/PC-A/pc/pc_on.csv", PC_HEADER + PC_ROW)
        self.assertTrue(self.env["_has_collected"]())
        paths = self.env["_source_files"](PC_PATTERNS)
        self.assertEqual([Path(path).relative_to(self.data).as_posix() for path in paths],
                         ["추가PC/PC-A/pc/pc_on.csv"])

    def test_header_only_csv_and_empty_extra_pc_are_not_collected(self):
        self.write("pc/pc_on.csv", PC_HEADER)
        self.write("추가PC/PC-A/pc/pc_spans.csv", "start,end,src\n")
        (self.data / "추가PC/PC-empty").mkdir()
        self.assertFalse(self.env["_has_collected"]())
        self.assertEqual(self.request("pc")["total"], 0)

    def test_browser_profiles_and_nested_arbitrary_roots_are_not_searched(self):
        ignored = ["copilot_profile/pc_on.csv", "copilot_profile/pc/pc_on.csv",
                   "archive/pc/pc_on.csv", "추가PC/PC-A/data/pc/pc_on.csv",
                   "추가PC/PC-A/copilot_profile/pc/pc_on.csv",
                   "추가PC/PC-B/LoadMonitor25/data/pc/pc_on.csv"]
        for relative in ignored:
            self.write(relative, PC_HEADER + PC_ROW)
        self.assertEqual(self.env["_source_files"](PC_PATTERNS), [])
        self.assertFalse(self.env["_has_collected"]())
        self.assertEqual(self.request("pc")["total"], 0)

    def test_source_files_are_sorted_and_unique_for_overlapping_patterns(self):
        expected = [self.write("pc/pc_on.csv", PC_HEADER + PC_ROW),
                    self.write("추가PC/PC-Z/pc/pc_on.csv", PC_HEADER + PC_ROW),
                    self.write("추가PC/PC-A/pc/pc_on.csv", PC_HEADER + PC_ROW)]
        actual = self.env["_source_files"](["pc/*.csv", "pc/pc_on.csv", "pc/*.csv"])
        self.assertEqual(actual, sorted({str(path) for path in expected}))

    def test_pc_api_shows_standard_flat_extra_and_span_columns(self):
        expected_files = set()
        expected_starts = set()
        for index, prefix in enumerate(("", "추가PC/PC-A/")):
            for relative in ("pc/pc_on.csv", "pc_on.csv"):
                expected_files.add(prefix + relative)
                self.write(prefix + relative, PC_HEADER + PC_ROW)
            for offset, relative in enumerate(("pc/pc_spans.csv", "pc_spans.csv")):
                start = f"2026-08-31 {9 + index * 2 + offset:02d}:00:00"
                expected_starts.add(start)
                expected_files.add(prefix + relative)
                self.write(prefix + relative, "start,end,src\n" + start + ",2026-08-31 18:00:00,event\n")
        payload = self.request("pc")
        self.assertEqual((payload["total"], payload["shown"]), (8, 8))
        self.assertEqual(self.relative_files(payload), expected_files)
        self.assertEqual(sum(bool(row.get("on_hours")) for row in payload["rows"]), 4)
        self.assertEqual({row["start"] for row in payload["rows"] if row.get("start")}, expected_starts)
        self.assertIn("end", payload["cols"])

    def test_files_api_includes_current_and_extra_pc(self):
        header = "mtime,ext,size_kb,folder,name\n"
        self.write("files/files.csv", header + "2026-08-31 10:00,.txt,1,Synthetic,root.txt\n")
        self.write("추가PC/PC-A/files/files.csv", header + "2026-08-31 11:00,.txt,1,Synthetic,extra.txt\n")
        payload = self.request("files")
        self.assertEqual(payload["total"], 2)
        self.assertEqual({row["name"] for row in payload["rows"]}, {"root.txt", "extra.txt"})
        self.assertEqual(self.relative_files(payload), {"files/files.csv", "추가PC/PC-A/files/files.csv"})


if __name__ == "__main__":
    unittest.main()
