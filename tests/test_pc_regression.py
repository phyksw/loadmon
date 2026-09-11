"""PC-input compatibility and preservation checks using only synthetic TEMP data."""

import ast
import contextlib
import copy
from datetime import date, datetime
import io
import json
import os
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest import mock


PROJECT = Path(__file__).resolve().parents[1]


class PcRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = Path(tempfile.mkdtemp(prefix="lm25-pc-regression-"))
        cls.modules = {}
        for version in ("LoadMonitor24", "LoadMonitor25"):
            target = cls.base / "source" / version / "core" / "extract.py"
            target.parent.mkdir(parents=True)
            source = (PROJECT / version / "core" / "extract.py").read_text(encoding="utf-8-sig")
            target.write_text(source, encoding="utf-8")
            env = {"__file__": str(target), "__name__": f"synthetic_{version}_extract"}
            exec(compile(source, str(target), "exec"), env)
            cls.modules[version] = env
        cls.cfg = json.loads((PROJECT / "LoadMonitor25/config/config.default.json").read_text(encoding="utf-8-sig"))
        cls.run_tree = ast.parse((PROJECT / "LoadMonitor25/run.py").read_text(encoding="utf-8-sig"))

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="case-", dir=self.base))
        self.data = self.root / "data"
        self.data.mkdir()
        self.new = self.modules["LoadMonitor25"]
        self.old = self.modules["LoadMonitor24"]

    def write(self, relative, text):
        path = self.data / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8-sig")
        return path

    def pc(self, relative="pc/pc_on.csv", day="2026-08-31", start="09:00", end="17:00", hours=8):
        return self.write(relative, "date,on_hours,first_on,last_off,night_hours,weekend\n"
                          f"{day},{hours},{start},{end},0,0\n")

    def run_env(self):
        names = {"_archive_path", "_write_pc_name", "archive_other_pc", "main", "arg"}
        body = [copy.deepcopy(node) for node in self.run_tree.body
                if isinstance(node, ast.FunctionDef) and node.name in names]
        calls = []
        env = {"os": os, "time": time, "date": date, "ROOT": str(self.root),
               "sys": SimpleNamespace(argv=["run.py", "--from", "2026-08-01", "--to", "2026-08-31"]),
               "RUN": {}, "_ACTIVE_CACHE": None, "_CAPTURE_RESULTS": {}, "cfg": lambda: {},
               "record": lambda *args: calls.append(("record", args)),
               "ensure_sampler": lambda *args: self.fail("sampler must not start after archive failure"),
               "step": lambda *args: self.fail("collector must not start after archive failure")}
        exec(compile(ast.Module(body=body, type_ignores=[]), "synthetic_run", "exec"), env)
        return env, calls

    def test_standard_pc_and_monthly_mm_match_lm24(self):
        self.pc()
        self.pc("추가PC/PC-B/pc/pc_on.csv", day="2026-09-01")
        self.write("pc/pc_spans.csv", "start,end,src\n2026-08-31 09:00:00,2026-08-31 17:00:00,event\n")
        self.write("추가PC/PC-B/pc/pc_spans.csv", "start,end,src\n2026-09-01 09:00:00,2026-09-01 17:00:00,event\n")
        start, end = date(2026, 8, 31), date(2026, 9, 1)
        signals = [(datetime(2026, month, day, 10), "파일", "synthetic.docx", 1.0, "self")
                   for month, day in ((8, 31), (9, 1))]
        results = []
        for module in (self.old, self.new):
            hours, info = module["day_work_hours"](str(self.data), signals, start, end,
                                                   cfg=self.cfg, now=datetime(2026, 9, 10), file_times={})
            mm = module["mm_from_hours"](hours, start, end, cfg=self.cfg, now=datetime(2026, 9, 10))
            self.assertEqual(info["pc_record_days"], 2)
            self.assertTrue(all(hours[day] > 0 for day in (start, end)))
            self.assertGreater(mm[1], 0)
            results.append((hours, info["pc_coverage_by_month"], mm))
        self.assertEqual(results[0], results[1])

    def test_flat_pc_on_compatibility_and_duplicates_do_not_add_hours(self):
        day = date(2026, 8, 31)
        self.pc("pc_on.csv")
        pc, windows, _spans, _all = self.new["pc_daily"](str(self.data), day, day)
        self.assertEqual(pc[day][0], 8)
        self.assertEqual(self.new["_union_min"](windows[day]), 480)
        signals = [(datetime(2026, 8, 31, 10), "파일", "synthetic.docx", 1.0, "self")]
        flat_hours, flat_info = self.new["day_work_hours"](
            str(self.data), signals, day, day, cfg=self.cfg, now=datetime(2026, 9, 10), file_times={})
        self.assertEqual(flat_info["pc_record_days"], 1)
        self.pc()
        canonical_hours, _info = self.old["day_work_hours"](
            str(self.data), signals, day, day, cfg=self.cfg, now=datetime(2026, 9, 10), file_times={})
        self.assertEqual(flat_hours, canonical_hours)
        self.pc("추가PC/PC-B/pc_on.csv")
        pc, windows, _spans, _all = self.new["pc_daily"](str(self.data), day, day)
        self.assertEqual(pc[day][0], 8)
        self.assertEqual(self.new["_union_min"](windows[day]), 480)

    def test_old_three_column_pc_rows_remain_supported(self):
        self.write("pc/pc_on.csv", "date,on_hours,night_hours\n2026-08-31,8,0\n")
        day = date(2026, 8, 31)
        self.assertEqual(self.new["pc_daily"](str(self.data), day, day),
                         self.old["pc_daily"](str(self.data), day, day))
        self.assertEqual(self.new["pc_daily"](str(self.data), day, day)[0][day][0], 8)

    def test_multi_pc_spans_union_and_cross_midnight_are_preserved(self):
        self.write("pc/pc_spans.csv", "start,end,src\n2026-08-31 22:00:00,2026-09-01 02:00:00,event\n")
        self.write("추가PC/PC-B/pc_spans.csv", "start,end,src\n2026-08-31 23:00:00,2026-09-01 03:00:00,event\n")
        start, end = date(2026, 8, 31), date(2026, 9, 1)
        result = self.new["pc_daily"](str(self.data), start, end)
        self.assertEqual(result, self.old["pc_daily"](str(self.data), start, end))
        self.assertEqual(result[0][start][0], 2)
        self.assertEqual(result[0][end][0], 3)

    def test_archive_failure_keeps_identity_and_stops_all_collection(self):
        self.write("pc_name.txt", "PC-A")
        original = self.pc()
        source_bytes = original.read_bytes()
        env, calls = self.run_env()
        with mock.patch.dict(os.environ, {"COMPUTERNAME": "PC-B"}), \
                mock.patch.object(os, "rename", side_effect=PermissionError("synthetic lock")), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(env["main"](), 1)
        self.assertEqual((self.data / "pc_name.txt").read_text(encoding="utf-8-sig"), "PC-A")
        self.assertEqual(original.read_bytes(), source_bytes)
        self.assertTrue(any(not args[1] for kind, args in calls if kind == "record"))

    def test_partial_archive_failure_keeps_all_evidence_and_identity(self):
        self.write("pc_name.txt", "PC-A")
        mail = self.write("outlook/mail.csv", "time,subject\n2026-08-31 10:00,synthetic\n")
        original = self.pc()
        mail_bytes, pc_bytes = mail.read_bytes(), original.read_bytes()
        rename = os.rename
        def partial(src, dst):
            if Path(src).name == "pc":
                raise PermissionError("synthetic PC lock")
            return rename(src, dst)
        env, _calls = self.run_env()
        with mock.patch.dict(os.environ, {"COMPUTERNAME": "PC-B"}), \
                mock.patch.object(os, "rename", side_effect=partial), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(env["main"](), 1)
        self.assertEqual((self.data / "pc_name.txt").read_text(encoding="utf-8-sig"), "PC-A")
        self.assertEqual(original.read_bytes(), pc_bytes)
        archived = list((self.data / "추가PC").glob("*/outlook/mail.csv"))
        self.assertEqual(len(archived), 1)
        self.assertEqual(archived[0].read_bytes(), mail_bytes)
        with mock.patch.dict(os.environ, {"COMPUTERNAME": "PC-B"}), contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(env["archive_other_pc"](str(self.data)))
        self.assertEqual(archived[0].read_bytes(), mail_bytes)
        archived_pc = list((self.data / "추가PC").glob("*/pc/pc_on.csv"))
        self.assertEqual(len(archived_pc), 1)
        self.assertEqual(archived_pc[0].read_bytes(), pc_bytes)
        self.assertEqual((self.data / "pc_name.txt").read_text(encoding="utf-8-sig"), "PC-B")

    def test_identity_replace_failure_preserves_label_and_blocks_collectors(self):
        label = self.write("pc_name.txt", "PC-A")
        self.pc()
        label_bytes = label.read_bytes()
        env, _calls = self.run_env()
        with mock.patch.dict(os.environ, {"COMPUTERNAME": "PC-B"}), \
                mock.patch.object(os, "replace", side_effect=PermissionError("synthetic identity lock")), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(env["main"](), 1)
        self.assertEqual(label.read_bytes(), label_bytes)
        self.assertEqual(list(self.data.glob(".pc-name-*.tmp")), [])
        self.assertEqual(len(list((self.data / "추가PC").glob("*/pc/pc_on.csv"))), 1)

    def test_invalid_pc_label_cannot_move_outside_data(self):
        self.write("pc_name.txt", "../outside")
        original = self.pc()
        env, _calls = self.run_env()
        with mock.patch.dict(os.environ, {"COMPUTERNAME": "PC-B"}), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(env["main"](), 1)
        self.assertTrue(original.exists())
        self.assertFalse((self.root / "outside").exists())

    def test_successful_archive_preserves_existing_archive_and_flat_pc_files(self):
        self.write("pc_name.txt", "PC-A")
        current = self.pc("pc_on.csv")
        previous = self.pc("추가PC/PC-A/pc/pc_on.csv", day="2026-08-28")
        current_bytes, previous_bytes = current.read_bytes(), previous.read_bytes()
        env, _calls = self.run_env()
        with mock.patch.dict(os.environ, {"COMPUTERNAME": "PC-B"}), contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(env["archive_other_pc"](str(self.data)))
        self.assertEqual(previous.read_bytes(), previous_bytes)
        self.assertEqual((self.data / "pc_name.txt").read_text(encoding="utf-8-sig"), "PC-B")
        copies = list((self.data / "추가PC").glob("*/pc_on.csv"))
        self.assertEqual(len(copies), 1)
        self.assertEqual(copies[0].read_bytes(), current_bytes)
        self.assertFalse(current.exists())

    def junction(self, link, target):
        import _winapi
        self.assertTrue(link.parent.resolve().is_relative_to(self.root.resolve()))
        self.assertTrue(target.resolve().is_relative_to(self.root.resolve()))
        _winapi.CreateJunction(str(target), str(link))

    @unittest.skipUnless(os.name == "nt", "Windows junction safety")
    def test_archive_parent_junction_cannot_move_data_to_external_folder(self):
        self.write("pc_name.txt", "PC-A")
        original = self.pc()
        mail = self.write("outlook/mail.csv", "time,subject\n2026-08-31 10:00,synthetic\n")
        outside = self.root / "outside"
        outside.mkdir()
        self.junction(self.data / "추가PC", outside)
        env, _calls = self.run_env()
        with mock.patch.dict(os.environ, {"COMPUTERNAME": "PC-B"}), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(env["main"](), 1)
        self.assertTrue(original.is_file())
        self.assertTrue(mail.is_file(), "Validate all paths before moving the first folder")
        self.assertEqual(list(outside.iterdir()), [])
        self.assertEqual((self.data / "pc_name.txt").read_text(encoding="utf-8-sig"), "PC-A")

    @unittest.skipUnless(os.name == "nt", "Windows junction safety")
    def test_source_junction_is_rejected_before_any_archive_move(self):
        self.write("pc_name.txt", "PC-A")
        mail = self.write("outlook/mail.csv", "time,subject\n2026-08-31 10:00,synthetic\n")
        outside = self.root / "outside"
        outside.mkdir()
        original = outside / "pc_on.csv"
        original.write_bytes(b"synthetic protected PC source")
        self.junction(self.data / "pc", outside)
        env, _calls = self.run_env()
        with mock.patch.dict(os.environ, {"COMPUTERNAME": "PC-B"}), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(env["main"](), 1)
        self.assertTrue(mail.is_file())
        self.assertEqual(original.read_bytes(), b"synthetic protected PC source")
        self.assertFalse((self.data / "추가PC").exists())
        self.assertEqual((self.data / "pc_name.txt").read_text(encoding="utf-8-sig"), "PC-A")

    @unittest.skipUnless(os.name == "nt", "Windows junction safety")
    def test_archive_parent_junction_is_rejected_even_within_data(self):
        self.write("pc_name.txt", "PC-A")
        original = self.pc()
        inside = self.data / "archive"
        inside.mkdir()
        self.junction(self.data / "추가PC", inside)
        env, _calls = self.run_env()
        with mock.patch.dict(os.environ, {"COMPUTERNAME": "PC-B"}), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(env["main"](), 1)
        self.assertTrue(original.is_file())
        self.assertEqual(list(inside.iterdir()), [])
        self.assertEqual((self.data / "pc_name.txt").read_text(encoding="utf-8-sig"), "PC-A")


if __name__ == "__main__":
    unittest.main()
