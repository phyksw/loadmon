"""Measurement contracts exercised only against source copies and synthetic TEMP CSVs."""

import ast
import contextlib
import copy
import csv
from collections import Counter
from datetime import date, datetime, timedelta
import hashlib
import io
import json
import math
import os
import re
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest


PROJECT = Path(__file__).resolve().parents[1]


class MeasurementContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="lm25-measurement-contract-")
        cls.base = Path(cls.temp.name)
        cls.modules = {}
        for version in ("LoadMonitor24", "LoadMonitor25"):
            path = cls.base / "source" / version / "core" / "extract.py"
            path.parent.mkdir(parents=True)
            source = (PROJECT / version / "core/extract.py").read_text(encoding="utf-8-sig")
            path.write_text(source, encoding="utf-8")
            env = {"__file__": str(path), "__name__": "synthetic_extract"}
            exec(compile(source, str(path), "exec"), env)
            cls.modules[version] = env
        cls.defaults = json.loads((PROJECT / "LoadMonitor25/config/config.default.json").read_text(encoding="utf-8-sig"))
        cls.refine_tree = ast.parse((PROJECT / "LoadMonitor25/refine.py").read_text(encoding="utf-8-sig"))
        identity_tree = ast.parse((PROJECT / "LoadMonitor25/core/details.py").read_text(encoding="utf-8-sig"))
        cls.identity = {"json": json, "hashlib": hashlib}
        identity_functions = [n for n in identity_tree.body if isinstance(n, ast.FunctionDef)
                              and n.name in {"stable_id", "stable_work_id"}]
        exec(compile(ast.Module(body=identity_functions, type_ignores=[]), "synthetic_identity", "exec"), cls.identity)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.data = Path(tempfile.mkdtemp(prefix="case-", dir=self.base)) / "data"
        self.data.mkdir()
        self.new = self.modules["LoadMonitor25"]
        self.old = self.modules["LoadMonitor24"]
        self.day = date(2026, 9, 7)
        self.now = datetime(2026, 9, 30, 23, 59)
        self.cfg = copy.deepcopy(self.defaults)
        self.cfg["owner"] = "Synthetic"

    def csv(self, relative, rows, fields=None):
        path = self.data / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields or list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        return path

    def pc(self, day=None, start="09:00", end="17:00", hours=8):
        return {"date": (day or self.day).isoformat(), "on_hours": hours,
                "first_on": start, "last_off": end, "night_hours": 0, "weekend": 0}

    def samples(self, start, count, title, step=1):
        return [{"time": (start + timedelta(minutes=i * step)).isoformat(sep=" "),
                 "idle_sec": 1, "process": "editor.exe", "title": title} for i in range(count)]

    def signals(self, module=None, end=None):
        return (module or self.new)["load_signals"](
            str(self.data), self.day, end or self.day,
            exclude=self.cfg.get("excludePathKeywords", []), cfg=self.cfg)

    def hours(self, signals=(), module=None, end=None, file_times=None):
        return (module or self.new)["day_work_hours"](
            str(self.data), list(signals), self.day, end or self.day,
            cfg=self.cfg, now=self.now, file_times=file_times or {})

    def refine_env(self):
        wanted = {"_f", "_refined_amounts", "_refine_totals", "_source_work_mm", "_check_refined_sources",
                  "slice_for_chunk", "_evidence_slice"}
        nodes = [n for n in self.refine_tree.body if isinstance(n, ast.FunctionDef) and n.name in wanted]
        env = {"OV_EV_LINES": 2, "math": math, "stable_work_id": self.identity["stable_work_id"]}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), "synthetic_refine", "exec"), env)
        return env

    def test_unattended_solver_is_machine_time_only(self):
        nxt = self.day + timedelta(days=1)
        sim = {self.day: [(1200, 1440)], nxt: [(0, 420)]}
        inputs = (sim, {}, {}, {}, {}, self.day, nxt, (480, 1140))
        before, _ = self.old["_sim_night_credit"](*inputs)
        self.assertEqual(sum(self.old["_union_min"](s) for s in before.values()) / 60, 4)
        for mode in ("span", "anchor", "off"):
            for human in ({}, {self.day: [1320]}):
                human_spans, stats = self.new["_sim_night_credit"](
                    sim, human, {}, {}, {}, self.day, nxt, (480, 1140), mode=mode)
                self.assertEqual(human_spans, {})
                self.assertEqual(stats["machine_night_h"], 11)
                self.assertEqual(stats["unlocked"], 0)

    def test_daytime_solver_cannot_open_pc_floor_or_human_session(self):
        self.csv("pc/pc_on.csv", [self.pc()])
        signal = [(datetime(2026, 9, 7, 10), "파일(해석출력)", "solver output", 1.5, "")]
        files = {self.day: [(600, ("sim", 1020))]}
        old, _ = self.hours(signal, self.old, file_times=files)
        new, info = self.hours(signal, file_times=files)
        self.assertGreater(sum(old.values()), 0)
        self.assertEqual(sum(new.values()), 0)
        self.assertEqual(info["machine_runtime_h"], 7)
        self.assertEqual(info["sim_night_h"], 0)

    def test_solver_does_not_remove_real_human_activity(self):
        self.cfg["mm"]["usePcFloor"] = False
        self.csv("activity/activity_a.csv", self.samples(datetime(2026, 9, 7, 20), 30, "work review"))
        hours, _ = self.hours(file_times={self.day: [(1200, ("sim", 1440))]})
        self.assertEqual(hours[self.day], 0.5)

    def test_private_window_excluded_from_signal_and_raw_time(self):
        self.cfg["excludePathKeywords"] = ["개인"]
        self.csv("pc/pc_on.csv", [self.pc(end="10:30", hours=1.5)])
        self.csv("activity/activity_a.csv", self.samples(datetime(2026, 9, 7, 9), 30, "업무 설계")
                 + self.samples(datetime(2026, 9, 7, 9, 30), 60, "개인 활동"))
        signals, _ = self.signals()
        hours, _ = self.hours(signals)
        self.assertEqual(len(signals), 1)
        self.assertEqual(hours[self.day], 0.5)

    def test_review_excluded_window_time_stays_out_of_pc_floor(self):
        self.csv("pc/pc_on.csv", [self.pc(end="10:30", hours=1.5)])
        self.csv("activity/activity_a.csv", self.samples(datetime(2026, 9, 7, 9), 30, "work")
                 + self.samples(datetime(2026, 9, 7, 9, 30), 60, "private"))
        signals, _ = self.signals()
        rows = [dict(zip(("time", "source", "text", "weight", "who"), (str(t), s, x, w, who), strict=True))
                for t, s, x, w, who in signals]
        result = self.new["rehours_after_judge"](str(self.data), rows[:1], rows[1:],
                                                self.day, self.day, self.cfg)
        self.assertEqual(result["day_hours"][str(self.day)], 0.5)
        self.assertEqual(result["dropped_h"], 1.0)

    def test_excluded_window_gap_is_not_bridged(self):
        self.cfg["excludePathKeywords"] = ["private"]
        self.csv("activity/activity_a.csv", self.samples(datetime(2026, 9, 7, 9), 10, "work")
                 + self.samples(datetime(2026, 9, 7, 9, 10), 10, "private")
                 + self.samples(datetime(2026, 9, 7, 9, 20), 10, "work"))
        hours, info = self.hours()
        self.assertEqual(hours[self.day], 0.33)
        self.assertEqual(info["sampler_bridge_h"], 0)

    def test_excluded_meeting_is_not_reread_after_judge(self):
        self.cfg["mm"]["usePcFloor"] = False
        self.csv("outlook/calendar.csv", [{"start": "2026-09-07 09:00", "end": "2026-09-07 10:00",
                                           "subject": "private appointment", "busy_status": "2"}])
        row = {"time": "2026-09-07 09:00", "source": "회의", "text": "private appointment", "weight": 2}
        result = self.new["rehours_after_judge"](str(self.data), [], [row], self.day, self.day, self.cfg)
        self.assertEqual(result["day_hours"], {})
        self.assertEqual(result["dropped_h"], 1)

    def test_collection_gaps_keep_calendar_denominator_and_availability(self):
        end = self.day + timedelta(days=4)
        self.csv("pc/pc_on.csv", [self.pc(), self.pc(self.day + timedelta(days=1))])
        signals = [(datetime(2026, 9, d, 10), "파일", "work.docx", 1, "") for d in (7, 8)]
        hours, info = self.hours(signals, end=end)
        self.assertEqual(info["collection_gap_days"], 3)
        self.assertEqual(info["inferred_absence"], {})
        self.assertNotEqual(info["coverage"]["grade"], "reliable")
        normal = self.new["mm_from_hours"](hours, self.day, end, cfg=self.cfg, now=self.now)
        legacy = {self.day + timedelta(days=i): 1.0 for i in (2, 3, 4)}
        ignored = self.new["mm_from_hours"](hours, self.day, end, cfg=self.cfg, now=self.now,
                                              inferred=legacy, absence=legacy)
        self.assertEqual(normal, ignored)
        self.assertEqual(normal[0]["2026-09"]["covered"], 5)

    def test_confirmed_absence_reduces_only_available_days(self):
        kwargs = {"cfg": self.cfg, "now": self.now}
        clean = self.new["mm_from_hours"]({self.day: 4}, self.day, self.day, **kwargs)[0]["2026-09"]
        absent = self.new["mm_from_hours"]({self.day: 4}, self.day, self.day,
                                              absence={self.day: 0.5}, **kwargs)[0]["2026-09"]
        self.assertEqual(clean["capacity_h"], absent["capacity_h"])
        self.assertEqual(clean["mm"], absent["mm"])
        self.assertEqual(absent["absent"], 0.5)

    def test_outside_period_mail_cannot_change_sender_weights(self):
        row = {"time": "2026-09-07 10:00", "box": "inbox", "sender": "Synthetic peer",
               "subject": "work request", "conversation": "active", "rcv": "to"}
        path = self.csv("outlook/mail.csv", [row])
        first, _ = self.signals()
        outside = [dict(row, time=f"2026-08-{d:02d} 10:00", conversation=f"old-{d}") for d in range(1, 5)]
        self.csv(path.relative_to(self.data), [row] + outside)
        second, _ = self.signals()
        self.assertEqual(first, second)
        before, _ = self.signals(self.old)
        self.assertEqual(before[0][3], 0.2)
        self.assertEqual(second[0][3], 1.0)

    def test_outside_period_sampler_cannot_change_current_interval(self):
        current = self.samples(datetime(2026, 9, 7, 9), 5, "work")
        path = self.csv("activity/activity_a.csv", current)
        first, _ = self.signals()
        self.csv(path.relative_to(self.data), current + self.samples(datetime(2026, 8, 1, 9), 20, "old", step=5))
        second, _ = self.signals()
        self.assertEqual(first, second)

    def test_explicit_manual_intervals_union_with_pc_and_each_other(self):
        self.cfg["mm"].update(trimIdleEdgesMin=0, flexEdgeH=0)
        self.csv("pc/pc_on.csv", [self.pc(end="12:00", hours=3)])
        self.csv("manual/worklog.csv", [
            {"date": str(self.day), "hours": 4, "category": "field", "start": "13:00", "end": "17:00"},
            {"date": str(self.day), "hours": 2, "category": "assembly", "start": "16:00", "end": "18:00"}])
        signals = [(datetime(2026, 9, 7, 10), "파일", "work.docx", 1, "")]
        hours, _ = self.hours(signals)
        self.assertEqual(hours[self.day], 8)
        self.assertEqual(self.new["manual_hours"](str(self.data), self.day, self.day)[self.day][0], 5)

    def test_unplaced_manual_time_is_visible_without_assumed_nonoverlap(self):
        self.csv("manual/worklog.csv", [{"date": str(self.day), "hours": 4, "category": "field"}])
        self.csv("activity/activity_a.csv", self.samples(datetime(2026, 9, 7, 9), 240, "work"))
        hours, info = self.hours()
        self.assertEqual(hours[self.day], 4)
        self.assertEqual(info["manual_unplaced_h"], 4)
        self.assertEqual(info["manual_unplaced_days"], 1)

    def test_manual_private_rows_and_review_rejection_are_excluded(self):
        self.cfg["excludePathKeywords"] = ["private"]
        self.csv("manual/worklog.csv", [
            {"date": str(self.day), "hours": 2, "category": "work"},
            {"date": str(self.day), "hours": 6, "category": "private"}])
        signals, _ = self.signals()
        self.assertEqual(len(signals), 1)
        hours, _ = self.hours(signals)
        self.assertEqual(hours[self.day], 2)
        dropped = [{"time": str(signals[0][0]), "source": "수동기록", "text": "work", "weight": 4}]
        result = self.new["rehours_after_judge"](str(self.data), [], dropped, self.day, self.day, self.cfg)
        self.assertEqual(result["day_hours"], {})

    def test_refine_keeps_original_mm_after_exclusion_and_merge(self):
        env = self.refine_env()
        rows = [{"share": 0.8, "mm": 0.8}, {"share": 0.2, "mm": 0.2}]
        self.assertEqual(env["_refined_amounts"](rows, [1]), (0.2, 0.2))
        self.assertEqual(env["_refined_amounts"](rows, [0, 1, 1]), (1, 1))
        self.assertEqual(env["_refined_amounts"](rows, []), (0, 0))
        self.assertEqual(env["_refine_totals"](rows, [rows[1]], [0]),
                         {"source_total_mm": 1, "retained_total_mm": 0.2, "excluded_candidate_mm": 0.8})

    def test_refine_main_exclusion_does_not_renormalize_remaining_rows(self):
        wanted = {"_f", "_i", "_g", "_majority", "merge_groups", "_refined_amounts", "_source_work_mm",
                  "_check_refined_sources"}
        nodes = [copy.deepcopy(n) for n in self.refine_tree.body
                 if isinstance(n, ast.FunctionDef) and n.name in wanted]
        nodes += [copy.deepcopy(n) for n in self.refine_tree.body
                  if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "_KEYS" for t in n.targets)]
        main = next(n for n in self.refine_tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
        start = next(i for i, n in enumerate(main.body) if isinstance(n, ast.Assign)
                     and any(isinstance(t, ast.Name) and t.id == "known_lv2" for t in n.targets))
        end = next(i for i, n in enumerate(main.body) if isinstance(n, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == "dst" for t in n.targets))
        function = ast.parse("def transform():\n    pass\n").body[0]
        function.body = copy.deepcopy(main.body[start:end]) + [ast.Return(value=ast.Name(id="final", ctx=ast.Load()))]
        nodes.append(function)
        env = {"Counter": Counter, "re": re, "ACT_CATS": (), "DETAIL_MAX": 90, "math": math,
               "stable_work_id": self.identity["stable_work_id"],
               "ukey2": lambda x: str(x or "").lower(), "snap1": lambda x: x or "",
               "model_names": [], "rows": [
                   {"Level 2": "A", "Level 3": "excluded", "share": 0.8, "mm": 0.8},
                   {"Level 2": "B", "Level 3": "retained", "share": 0.2, "mm": 0.2}],
               "rf": SimpleNamespace(items=[({0, 1}, set(), {"m": [0], "w": False}),
                                             ({0, 1}, set(), {"m": [1], "w": True, "l2": "B", "l3": "retained"})])}
        exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), "refine_transform", "exec"), env)
        result = env["transform"]()
        self.assertEqual([(r["share"], r["mm"]) for r in result], [(0.2, 0.2)])
        env["rf"].items = [({0, 1}, set(), {"m": [0, 1], "w": False})]
        self.assertEqual(env["transform"](), [])
        env["rf"].items = []
        self.assertEqual(sum(r["mm"] for r in env["transform"]()), 1)

    def test_review_excluded_all_day_field_record_cannot_restore_workday_floor(self):
        self.csv("outlook/calendar.csv", [{"start": "2026-09-07 00:00", "end": "2026-09-08 00:00",
                                           "subject": "field 출장", "busy_status": "3", "all_day": 1}])
        signal = {"time": "2026-09-07 09:00", "source": "회의", "text": "field 출장", "weight": 16}
        result = self.new["rehours_after_judge"](str(self.data), [], [signal], self.day, self.day, self.cfg)
        self.assertEqual(result["day_hours"], {})
        self.assertEqual(result["dropped_h"], 8)

    def test_outside_period_authors_cannot_change_self_inference(self):
        self.cfg["owner"] = ""
        self.cfg["teamsSelfNames"] = []
        current = [{"mtime": "2026-09-07 10:00", "name": f"work{i}.docx", "ext": ".docx",
                    "folder": f"C:/Work/project{i}", "author": "SyntheticAlpha"} for i in range(3)]
        path = self.csv("files/files.csv", current)
        first, _ = self.signals()
        outside = [dict(current[0], mtime="2026-08-01 10:00", folder=f"C:/Old/project{i}",
                        author="SyntheticBeta") for i in range(4)]
        self.csv(path.relative_to(self.data), current + outside)
        second, _ = self.signals()
        self.assertTrue(first)
        self.assertEqual(first, second)

    def test_refine_missing_task_evidence_cannot_borrow_neighbor(self):
        env = self.refine_env()
        text, hits = env["slice_for_chunk"]({("A", "other"): ["unrelated"]}, [(1, {"Level 2": "A", "Level 3": "work"})])
        self.assertEqual((text, hits), ("", 0))
        self.assertEqual(env["_evidence_slice"]("## A backup / work\nunrelated", [("A", "work")]), "")
        self.assertEqual(env["_evidence_slice"]("## A / other\nunrelated", [("A", "work")]), "")
        self.assertIn("supported", env["_evidence_slice"]("## A / work — 1MM\nsupported", [("A", "work")]))

    def run_refine_csv(self, rows, items):
        """Execute the actual main function's reader/transform/writer; only AI transport is replaced."""
        root = self.data.parent
        report = root / "report"
        report.mkdir(exist_ok=True)
        tag = "20260901-20260930"
        source = report / f"mm_rows_{tag}.csv"
        with source.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        class FakeRefiner:
            def __init__(self, *_args):
                self.items = []
                self.soft = False
                self.st = {"roundtrips": 1, "repaired": 0, "retries": 0, "failed_items": 0}

            def run(self, chunk, overlap, _label):
                self.items.extend(({i for i, _r in chunk}, overlap, it) for it in items)

        functions = {"_f", "_i", "_g", "_num_ok", "_majority", "merge_groups", "_refined_amounts",
                     "_refine_totals", "_source_work_mm", "_check_refined_sources", "load_signal_evidence",
                     "plan_chunks", "item_line", "main"}
        constants = {"_KEYS", "ACT_CATS", "OV_N", "OV_CHARS", "DETAIL_MAX", "FAIL_STOP_RETRY"}
        nodes = [copy.deepcopy(n) for n in self.refine_tree.body
                 if (isinstance(n, ast.FunctionDef) and n.name in functions)
                 or (isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id in constants for t in n.targets))]
        env = {"ROOT": str(root), "os": os, "csv": csv, "json": json, "math": math, "time": time,
               "Counter": Counter, "re": re, "PROMPT_BUDGET": 8400, "Refiner": FakeRefiner,
               "stable_work_id": self.identity["stable_work_id"], "snap1": lambda value: value or "",
               "ukey2": lambda value: str(value or "").lower(), "chunk_default": lambda *_args: 20,
               "progress": lambda *_args: None,
               "arg": lambda flag: "2026-09-01" if flag == "--from" else "2026-09-30"}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), "synthetic_refine_main", "exec"), env)
        with contextlib.redirect_stdout(io.StringIO()):
            result = env["main"]()
        output = report / f"mm_rows_{tag}_refined.csv"
        final = []
        if output.exists():
            with output.open(encoding="utf-8-sig", newline="") as stream:
                final = list(csv.DictReader(stream))
        return result, final, report / f"refine_map_{tag}.json"

    def lineage_rows(self):
        return [{"Level 2": "Alpha", "Level 3": "design review", "유형": "개발", "share": 0.2,
                 "mm": 0.2, "활동일수": 3, "이름": "Synthetic", "Function": "Design"},
                {"Level 2": "Beta", "Level 3": "design review", "유형": "협업", "share": 0.8,
                 "mm": 0.8, "활동일수": 4, "이름": "Synthetic", "Function": "Design"}]

    def test_refine_main_csv_preserves_original_lineage_after_rename_merge_and_fallback(self):
        rows = self.lineage_rows()
        ids = [self.identity["stable_work_id"](row) for row in rows]
        for items, expected in (([{"m": [0], "l2": "Renamed Alpha", "l3": "new task", "w": True},
                                  {"m": [1], "l2": "Renamed Beta", "l3": "new task", "w": True}],
                                 [{ids[0]: 0.2}, {ids[1]: 0.8}]),
                                ([{"m": [0, 1], "l2": "Combined", "l3": "merged work", "w": True}],
                                 [{ids[0]: 0.2, ids[1]: 0.8}]),
                                ([{"m": [0], "l2": "Renamed", "l3": "new task", "w": True}],
                                 [{ids[0]: 0.2}, {ids[1]: 0.8}])):
            with self.subTest(items=items):
                code, final, mapping = self.run_refine_csv(rows, items)
                self.assertEqual(code, 0)
                lineage = [json.loads(row["source_work_mm"]) for row in final]
                self.assertCountEqual(lineage, expected)
                self.assertAlmostEqual(sum(float(row["mm"]) for row in final), 1)
                self.assertEqual(json.loads(mapping.read_text(encoding="utf-8"))["retained_total_mm"], 1)
                self.assertTrue(all(abs(sum(json.loads(row["source_work_mm"]).values()) - float(row["mm"])) < 1e-6
                                    for row in final))

    def test_refine_main_csv_excluded_source_never_reappears(self):
        rows = self.lineage_rows()
        ids = [self.identity["stable_work_id"](row) for row in rows]
        code, final, mapping = self.run_refine_csv(rows, [{"m": [0], "l3": "renamed work", "w": True},
                                                        {"m": [1], "w": False}])
        self.assertEqual(code, 0)
        self.assertEqual([json.loads(row["source_work_mm"]) for row in final], [{ids[0]: 0.2}])
        self.assertEqual(float(final[0]["mm"]), 0.2)
        self.assertEqual(json.loads(mapping.read_text(encoding="utf-8"))["excluded_candidate_mm"], 0.8)

    def test_refine_ambiguous_duplicate_source_id_preserves_previous_csv(self):
        rows = self.lineage_rows()
        code, _final, mapping = self.run_refine_csv(rows, [{"m": [0, 1], "w": True}])
        self.assertEqual(code, 0)
        output = mapping.with_name("mm_rows_20260901-20260930_refined.csv")
        before = output.read_bytes()
        self.assertEqual(self.run_refine_csv([rows[0], dict(rows[0], mm=0.8)], [{"m": [0, 1], "w": True}])[0], 1)
        self.assertEqual(output.read_bytes(), before)

    def test_refine_prompt_does_not_fallback_to_unrelated_raw_sample(self):
        env = self.refine_env()
        env.update(os=os, PROMPT_BUDGET=8400, load_exclude=lambda: [],
                   sanitize_evidence=lambda text, _exclude: (text, 0, []),
                   build_prompt=lambda _ch, text, _names, mode, _ov: f"mode={mode}\n{text}")
        node = next(n for n in self.refine_tree.body if isinstance(n, ast.ClassDef) and n.name == "Refiner")
        exec(compile(ast.Module(body=[node], type_ignores=[]), "refiner_prompt", "exec"), env)
        refiner = env["Refiner"]("synthetic", str(self.data.parent), None,
                                 "## Other / Task\nSECRET_OTHER_SAMPLE", [], say=lambda *_a: None)
        prompt = refiner.make_prompt([(0, {"Level 2": "A", "Level 3": "work"})], set(), "case")
        self.assertIn("mode=none", prompt)
        self.assertNotIn("SECRET_OTHER_SAMPLE", prompt)


if __name__ == "__main__":
    unittest.main()
