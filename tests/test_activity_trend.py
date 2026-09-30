"""Period-wide activity counts, actual PC parsing, and UI layering with synthetic data only."""
import ast
from collections import Counter
import csv
from datetime import date, timedelta
import glob
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest import mock


PROJECT = Path(__file__).resolve().parents[1]
SOURCE = PROJECT / "LoadMonitor25" / "ui" / "app.py"
TAG = "20260101-20260913"


class ActivityTrendTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="lm25-trend-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = self.root / "data"
        self.report = self.root / "report"
        self.data.mkdir()
        self.report.mkdir()
        tree = ast.parse(SOURCE.read_text(encoding="utf-8-sig"))
        names = {"_rows", "_mtime", "_source_files", "_source_rows", "_tag_period", "dash_period", "trend",
                 "outlook_coverage", "sources", "mtime_clumps", "_age", "activity_payload", "_activity_read_issues"}
        body = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
        self.assertEqual({n.name for n in body}, names)
        self.ns = {"os": os, "csv": csv, "glob": glob, "json": json, "re": re, "time": time,
                   "Counter": Counter, "DATA": str(self.data), "REPORT": str(self.report),
                   "_DASH_EXTENT": {}, "latest_signals": lambda: "",
                   "communication_coverage": lambda period: []}
        exec(compile(ast.Module(body=body, type_ignores=[]), str(SOURCE), "exec"), self.ns)
        # Actual PC parser copied to TEMP; its ROOT and every supplied input are synthetic.
        code = self.root / "code" / "core" / "extract.py"
        code.parent.mkdir(parents=True)
        shutil.copyfile(PROJECT / "LoadMonitor25" / "core" / "extract.py", code)
        spec = importlib.util.spec_from_file_location("lm25_synthetic_extract", code)
        self.extract = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.extract)
        self.modules = mock.patch.dict(sys.modules, {"extract": self.extract})
        self.modules.start()
        self.addCleanup(self.modules.stop)

    def write(self, relative, rows, fields=None, report=False):
        path = (self.report if report else self.data) / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields or list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        return path

    def signals(self, rows, tag=TAG):
        return self.write(f"signals_{tag}.csv", rows, ["time", "source", "text", "who"], report=True)

    def test_empty_mail_hint_identifies_each_actual_route(self):
        stages = [{"name": name, "ok": False, "note": "synthetic failure"} for name in (
            "Outlook COM", "Outlook 보충 · Windows Search 색인", "Outlook 보충 · 웹",
            "Outlook 보충 · Copilot 조회", "Outlook 수집 범위")]
        (self.report / "last_run.json").write_text(json.dumps({"stages": stages}), encoding="utf-8")
        sources = self.ns["sources"]()
        mail = next(row for row in sources if row["name"] == "메일·일정")
        for name in ("COM", "색인", "Outlook 웹", "Copilot", "수집 범위"):
            self.assertIn(name + ": 실패", mail["hint"])
        self.assertEqual(mail["hint"].count("COM: 실패"), 1)

    def trend(self, start="2026-01-01", end="2026-09-13", tag=TAG):
        info = {}
        return self.ns["trend"](start, end, tag, info), info

    @staticmethod
    def totals(rows, key):
        return sum(row["counts"][key] for row in rows)

    def test_additional_pc_mail_and_file_history_cover_every_month(self):
        self.write("추가PC/A/outlook/mail.csv", [
            {"time": f"2026-{m:02d}-01 09:00", "subject": f"Month {m}", "sender": "Synthetic"}
            for m in range(1, 10)])
        self.write("추가PC/A/files/files_history.csv", [
            {"mtime": "2026-01-03 12:00", "folder": "Synthetic", "name": "old.txt"}])
        rows, info = self.trend()
        self.assertEqual(len(rows), 9)
        self.assertEqual([r["메일"] for r in rows], [1] * 9)
        self.assertEqual(self.totals(rows, "파일"), 1)
        self.assertEqual(info["counted"], 10)
        self.assertEqual(info["period"], ["2026-01-01", "2026-09-13"])

    def test_duplicate_copies_are_removed_without_capping_collected_events(self):
        files = [{"mtime": "2026-01-05 09:00", "folder": "Synthetic", "name": f"doc-{i}.txt"}
                 for i in range(12)]
        for location in ["files/files.csv", "files/files_history.csv", "추가PC/A/files/files.csv"]:
            self.write(location, files)
        rows, info = self.trend()
        self.assertEqual((info["raw_n"], info["duplicates"], info["counted"], info["displayed"], info["capped"]),
                         (36, 24, 12, 12, 0))
        self.assertEqual(self.totals(rows, "파일"), 12)

    def test_empty_or_foreign_ai_samples_do_not_erase_collected_activity(self):
        self.write("outlook/mail.csv", [{"time": "2026-01-05 09:00", "subject": "Collected evidence"}])
        for signals in [[], [{"time": "2025-12-31", "source": "메일", "text": "Foreign", "who": ""}]]:
            self.signals(signals)
            rows, info = self.trend()
            self.assertEqual(info["src"], "raw")
            self.assertEqual(self.totals(rows, "메일"), 1)
            self.assertEqual(info["signals_n"], 0)

    def test_selected_period_signals_never_fall_back_to_other_period(self):
        other = self.signals([{"time": "2026-01-05", "source": "메일", "text": "Wrong period", "who": ""}],
                             tag="20260101-20260131")
        self.ns["latest_signals"] = lambda: str(other)
        rows, info = self.trend()
        self.assertEqual((info["src"], self.totals(rows, "메일")), ("raw", 0))
        self.assertEqual(info["signals_n"], 0)

    def test_tagless_period_does_not_borrow_latest_overlapping_ai_samples(self):
        other = self.signals([{"time": "2026-01-05", "source": "메일", "text": "Overlap", "who": ""}],
                             tag="20260101-20260331")
        self.ns["latest_signals"] = lambda: str(other)
        _rows, info = self.trend("2026-01-01", "2026-01-31", "")
        self.assertEqual(info["signals_n"], 0)
        self.signals([{"time": "2026-01-05", "source": "메일", "text": "Matching", "who": ""}],
                     tag="20260101-20260131")
        _rows, info = self.trend("2026-01-01", "2026-01-31", "")
        self.assertEqual(info["signals_n"], 1)

    def test_window_samples_and_ai_classifications_do_not_inflate_collected_events(self):
        self.signals([{"time": "2026-01-05 09:00", "source": src, "text": f"item-{i}", "who": ""}
                      for src in ["작업창", "수동", "알수없음", "파일"] for i in range(10)])
        windows = [{"time": "2026-01-05 09:00", "process": "synthetic", "title": f"Window {i}"} for i in range(10)]
        for path in ["activity/activity_20260105.csv", "추가PC/A/activity/activity_20260105.csv"]:
            self.write(path, windows)
        self.write("manual/worklog.csv", [{"date": "2026-01-05", "note": f"Task {i}"} for i in range(10)])
        self.write("files/files.csv", [{"mtime": "2026-01-05", "name": f"file-{i}.txt"} for i in range(10)])
        rows, info = self.trend()
        self.assertEqual([self.totals(rows, k) for k in ["작업창", "수동", "기타", "파일"]], [0, 10, 0, 10])
        self.assertEqual((info["counted"], info["displayed"], info["capped"]), (20, 20, 0))
        self.assertEqual((info["window_samples"], info["signals_n"]), (10, 40))

    def test_180_workdays_count_all_collected_records_despite_small_ai_sample(self):
        days, current = [], date(2026, 1, 1)
        while len(days) < 180:
            if current.weekday() < 5:
                days.append(current.isoformat())
            current += timedelta(days=1)
        self.write("files/files.csv", [{"mtime": d + f" 09:{i:02d}", "name": f"doc-{i}.txt"}
                                        for d in days for i in range(30)])
        self.write("outlook/mail.csv", [{"time": d + f" 10:{i:02d}", "subject": f"Mail {i}"}
                                          for d in days for i in range(10)])
        self.signals([{"time": d, "source": src, "text": f"Sample {i}", "who": ""}
                      for d in days for src, limit in [("파일", 8), ("메일", 2)] for i in range(limit)])
        rows, info = self.trend()
        self.assertEqual((self.totals(rows, "파일"), self.totals(rows, "메일")), (5400, 1800))
        self.assertEqual((info["counted"], info["displayed"], info["signals_n"]), (7200, 7200, 1800))
        self.assertEqual(sum(r["파일"] for r in rows), 5400)

    def test_file_burst_is_reported_without_silently_discarding_collected_records(self):
        self.write("files/files.csv", [{"mtime": "2026-01-05 09:00", "folder": "Synthetic", "name": f"doc-{i}.txt"}
                                        for i in range(4000)])
        rows, info = self.trend()
        clumps = self.ns["mtime_clumps"]("2026-01-01", "2026-09-13")
        self.assertEqual((info["counted"], info["displayed"], sum(r["파일"] for r in rows)), (4000,) * 3)
        self.assertEqual(clumps[0]["n"], 4000)

    def test_file_snapshot_history_and_recent_merge_without_redundant_extension(self):
        self.write("files/files.csv", [{"mtime": "2026-02-02 09:00", "name": "same.txt", "folder": "Synthetic", "ext": ".txt"}])
        self.write("files/files_history.csv", [
            {"mtime": "2026-01-05 09:00", "name": "same.txt", "folder": "Synthetic"},
            {"mtime": "2026-02-02 09:00", "name": "same.txt", "folder": "Synthetic"}])
        self.write("files/recent.csv", [{"mtime": "2026-02-02 09:00", "name": "same.txt", "folder": "Synthetic"}])
        rows, info = self.trend()
        self.assertEqual((info["counted"], info["duplicates"]), (2, 2))
        self.assertEqual([r["파일"] for r in rows[:2]], [1, 1])

    def test_day_boundaries_and_year_boundary_keep_every_event(self):
        tag = "20251228-20260104"
        self.write("outlook/mail.csv", [{"time": t, "subject": t} for t in
                   ["2025-12-27 23:59", "2025-12-28 00:00", "2026-01-04 23:59", "2026-01-05 00:00"]])
        rows, info = self.trend("2025-12-28", "2026-01-04", tag)
        self.assertEqual(info["counted"], 2)
        self.assertEqual([r["메일"] for r in rows], [1, 1])
        self.assertEqual((rows[0]["from"], rows[-1]["to"]), ("2025-12-28", "2026-01-04"))

    def test_six_months_monthly_three_months_weekly_with_empty_buckets(self):
        rows, info = self.trend("2026-01-01", "2026-06-30", "20260101-20260630")
        self.assertEqual((info["gran"], len(rows)), ("month", 6))
        rows, info = self.trend("2026-01-01", "2026-03-31", "20260101-20260331")
        self.assertEqual((info["gran"], len(rows)), ("week", 14))
        self.assertTrue(all(r["raw_n"] == 0 for r in rows))

    def test_period_inference_includes_old_additional_pc_and_refreshes_on_new_file(self):
        self.write("추가PC/A/files/files_history.csv", [{"mtime": "2024-01-05", "name": "older.txt"}])
        self.assertEqual(self.ns["dash_period"]({}, {}), ["2024-01-05", "2024-01-05"])
        self.write("추가PC/B/m365/teams_web.csv", [{"time": "2026-08-20", "summary": "New"}])
        self.assertEqual(self.ns["dash_period"]({}, {}), ["2024-01-05", "2026-08-20"])
        self.assertEqual(self.ns["dash_period"]({"period": ["2026-01-01", "2026-01-31"]}, {}),
                         ["2026-01-01", "2026-01-31"])

    def test_span_only_period_handles_midnight_exclusive_end(self):
        self.write("추가PC/A/pc_spans.csv", [{"start": "2026-01-05 12:00", "end": "2026-01-06 00:00", "src": "event"}])
        self.assertEqual(self.ns["dash_period"]({}, {}), ["2026-01-05", "2026-01-05"])
        rows, info = self.trend()
        self.assertEqual(sum(row["pc_h"] for row in rows), 12)
        self.assertEqual(info["pc_buckets"], 1)

    def test_no_source_has_no_invented_recent_13_weeks(self):
        rows, info = self.trend("", "", "")
        self.assertEqual((rows, info["src"], info["period"]), ([], "none", ["", ""]))

    def test_observation_browsing_uses_requested_range_without_analysis(self):
        self.write("추가PC/A/outlook/mail.csv", [{"time": f"2026-{m:02d}-05", "subject": f"Month {m}"}
                                                for m in range(1, 10)])
        self.ns["result_rows"] = lambda: self.fail("Browsing collected records must not invoke analysis results")
        payload = self.ns["activity_payload"]("2026-01-01", "2026-03-31")
        self.assertEqual(payload["trend_info"]["counted"], 3)
        self.assertEqual(payload["period"], ["2026-01-01", "2026-03-31"])
        self.assertNotIn("meta", payload)
        self.assertNotIn("total", payload)
        complete = self.ns["activity_payload"]()
        self.assertEqual(complete["period"], ["2026-01-05", "2026-09-05"])
        self.assertEqual(complete["trend_info"]["counted"], 9)

    def test_observation_endpoint_rejects_invalid_and_duplicate_range_parameters(self):
        tree = ast.parse(SOURCE.read_text(encoding="utf-8-sig"))
        handler = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "H")
        method = next(n for n in handler.body if isinstance(n, ast.FunctionDef) and n.name == "do_GET")
        exec(compile(ast.Module(body=[method], type_ignores=[]), str(SOURCE), "exec"), self.ns)
        for query in ["from=2026-02-30&to=2026-03-01", "from=2026-03-01&to=2026-01-01",
                      "from=2026-01-01", "from=2026-01-01&from=2026-02-01&to=2026-03-01",
                      "tag=20260101-20260331"]:
            replies = []
            self.ns["do_GET"](SimpleNamespace(path="/api/activity?" + query, _send=lambda *r: replies.append(r)))
            self.assertEqual(replies[0][0], 400, query)
        replies = []
        self.ns["do_GET"](SimpleNamespace(path="/api/activity", _send=lambda *r: replies.append(r)))
        self.assertEqual(replies[0][0], 200)
        self.assertEqual(replies[0][1]["trend"], [])

    def test_browse_button_updates_only_activity_and_reset_restores_analysis_period(self):
        from test_improvement_audit import ImprovementAuditTests
        self.write("outlook/mail.csv", [{"time": "2026-01-05", "subject": "January"}])
        observation = self.ns["activity_payload"]("2026-01-01", "2026-01-31")
        baseline = {"version": "synthetic", "port": 0, "rows": [], "sources": [], "total": 0,
                    "meta": {"period": ["2026-08-01", "2026-08-31"], "signals": 0},
                    "period": ["2026-08-01", "2026-08-31"], "trend": [],
                    "trend_info": {"gran": "month", "period": ["2026-08-01", "2026-08-31"]}}
        action = "const observation=" + json.dumps(observation, ensure_ascii=False) + r''';
const calls=[];
context.fetch=async(url,opt)=>{calls.push({url,method:opt&&opt.method||'GET'});
 return {ok:true,json:async()=>url.startsWith('/api/activity')?observation:payload};};
await context.refresh();const metaBefore=byId.metaper.textContent;
byId.activityfrom.value='2026-01-01';byId.activityto.value='2026-01-31';
await context.browseActivity();
const viewed={subtitle:byId.wsub.textContent,note:byId.wnote.innerHTML,meta:byId.metaper.textContent};
await context.refresh();const retained=byId.wsub.textContent;
await byId.activityreset.onclick();
process.stdout.write(JSON.stringify({calls,metaBefore,viewed,retained,reset:byId.wsub.textContent}));
'''
        result = ImprovementAuditTests().render_page(baseline, action)
        self.assertIn("2026-01-01 ~ 2026-01-31", result["viewed"]["subtitle"])
        self.assertEqual(result["viewed"]["meta"], result["metaBefore"])
        self.assertEqual(result["retained"], result["viewed"]["subtitle"])
        self.assertIn("수집 기록 조회 결과", result["viewed"]["note"])
        self.assertIn("2026-08-01 ~ 2026-08-31", result["reset"])
        self.assertTrue(all(call["method"] == "GET" for call in result["calls"]))
        self.assertTrue(all(call["url"].startswith(("/api/activity", "/api/dash")) for call in result["calls"]))

    def test_slow_activity_response_cannot_overwrite_reset_or_newer_range(self):
        from test_improvement_audit import ImprovementAuditTests
        payload = {"version": "synthetic", "port": 0, "rows": [], "sources": [], "total": 0,
                   "meta": {}, "period": ["2026-08-01", "2026-08-31"], "trend": [],
                   "trend_info": {"gran": "month", "period": ["2026-08-01", "2026-08-31"]}}
        result = ImprovementAuditTests().render_page(payload, r'''
let resolve;
context.fetch=async url=>url.startsWith('/api/activity')?new Promise(r=>{resolve=r}):{ok:true,json:async()=>payload};
byId.activityfrom.value='2026-01-01';byId.activityto.value='2026-01-31';
const slow=context.browseActivity();await byId.activityreset.onclick();
resolve({ok:true,json:async()=>({ok:true,period:['2026-01-01','2026-01-31'],trend:[]})});await slow;
process.stdout.write(JSON.stringify({subtitle:byId.wsub.textContent,status:byId.activitystatus.textContent}));
''')
        self.assertIn("2026-08-01 ~ 2026-08-31", result["subtitle"])
        self.assertEqual(result["status"], "")

    def test_overlapping_failed_activity_requests_do_not_lock_out_the_dashboard(self):
        from test_improvement_audit import ImprovementAuditTests
        payload = {"version": "synthetic", "port": 0, "rows": [], "sources": [], "total": 0,
                   "meta": {}, "period": ["2026-08-01", "2026-08-31"], "trend": [],
                   "trend_info": {"gran": "month", "period": ["2026-08-01", "2026-08-31"]}}
        result = ImprovementAuditTests().render_page(payload, r'''
const finish=[];
context.fetch=async url=>url.startsWith('/api/activity')?new Promise(r=>finish.push(r)):{ok:true,json:async()=>payload};
byId.activityfrom.value='2026-01-01';byId.activityto.value='2026-01-31';
const first=context.browseActivity();const second=context.browseActivity();
finish[0]({ok:true,json:async()=>({ok:true,period:['2026-01-01','2026-01-31'],trend:[]})});await first;
finish[1]({ok:false,json:async()=>({ok:false,error:'Synthetic unavailable'})});await second;
await context.refresh();
process.stdout.write(JSON.stringify({subtitle:byId.wsub.textContent,status:byId.activitystatus.textContent}));
''')
        self.assertIn("2026-08-01 ~ 2026-08-31", result["subtitle"])
        self.assertIn("Synthetic unavailable", result["status"])

    def test_pc_union_and_weekend_only_records_are_visible(self):
        for folder, start, end in [("pc", "09:00", "12:00"), ("추가PC/A/pc", "11:00", "17:00")]:
            self.write(folder + "/pc_spans.csv", [{"start": "2026-01-03 " + start,
                                                    "end": "2026-01-03 " + end, "src": "event"}])
        rows, info = self.trend("2026-01-03", "2026-01-03", "20260103-20260103")
        self.assertEqual(rows[0]["pc_h"], 8)
        self.assertEqual((rows[0]["pc_days"], rows[0]["pc_record_days"], info["pc_buckets"]), (0, 1, 1))

    def test_partial_first_week_label_stays_inside_the_selected_period(self):
        self.write("outlook/mail.csv", [{"time": "2026-09-02 10:00", "subject": "Synthetic"}])
        payload = self.ns["activity_payload"]("2026-09-01", "2026-09-13")
        self.assertEqual(payload["trend"][0]["label"], "09/01")
        self.assertEqual(payload["trend"][0]["from"], "2026-09-01")
        self.assertEqual(payload["trend_info"]["counted"], 1)

    def test_small_counts_have_unique_ticks_and_no_unknown_pc_hours_axis(self):
        from test_improvement_audit import ImprovementAuditTests
        for count in (1, 2):
            with self.subTest(count=count):
                rows = [{"label": "09/01", "메일": count, "pc_h": 0, "pc_record_days": 0}]
                result = ImprovementAuditTests().render_page(rows, "context.weekly(byId.weekly,payload);"
                         "process.stdout.write(JSON.stringify({html:byId.weekly.innerHTML}));")
                ticks = re.findall(r'<text[^>]*>(\d+)</text>', result["html"])
                self.assertEqual(ticks, [str(value) for value in range(count, -1, -1)])
                self.assertNotIn("h</text>", result["html"])

    def test_pc_parser_failure_uses_all_roots_without_double_counting(self):
        for path in ["pc/pc_on.csv", "추가PC/A/pc_on.csv"]:
            self.write(path, [{"date": "2026-01-05", "on_hours": "8"}])
        with mock.patch.object(self.extract, "pc_daily", side_effect=ValueError("Synthetic corrupt span")):
            rows, info = self.trend()
        self.assertEqual(sum(r["pc_h"] for r in rows), 8)
        self.assertIn("ValueError", info["pc_note"])

    def test_coverage_combines_different_months_and_sources_across_pcs(self):
        for prefix, cov in [("", {"mail": {"2026-01": 1}, "calendar": {"2026-02": 1}}),
                            ("추가PC/A/", {"mail": {"2026-02": 1}, "calendar": {"2026-01": 1}})]:
            folder = self.data / prefix / "outlook"
            folder.mkdir(parents=True)
            (folder / "mail_source.json").write_text(json.dumps({"source": "com"}), encoding="utf-8")
            (folder / "coverage.json").write_text(json.dumps(cov), encoding="utf-8")
        coverage = self.ns["outlook_coverage"](["2026-01-01", "2026-02-28"])
        self.assertEqual(coverage["uncovered"], [])

    def test_sources_count_archived_mail_while_identifying_current_pc(self):
        self.write("추가PC/A/outlook/mail.csv", [{"time": "2026-01-05", "subject": "Synthetic"}])
        found = next(row for row in self.ns["sources"]() if row["name"] == "메일·일정")
        self.assertEqual((found["rows"], found["here"]), (1, 0))
        self.assertIn("추가 PC 1건", found["hint"])

    def test_dashboard_get_never_labels_rows_with_foreign_metadata(self):
        tree = ast.parse(SOURCE.read_text(encoding="utf-8-sig"))
        handler = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "H")
        method = next(n for n in handler.body if isinstance(n, ast.FunctionDef) and n.name == "do_GET")
        self.ns.update(result_rows=lambda: ("mm_rows_20260101-20260131.csv", [{"mm": 0.2}]),
                       latest=lambda _: str(self.report / "mm_meta_20260401-20260430.json"),
                       _judged_info=lambda _: (True, 1, 1, {}), _stub_note=lambda _: "",
                       VERSION="synthetic", PORT=[0], JOB={"running": False}, STUB_MARK="LM_COPILOT_STUB",
                       _has_collected=lambda: True)
        exec(compile(ast.Module(body=[method], type_ignores=[]), str(SOURCE), "exec"), self.ns)
        self.signals([{"time": "2026-01-05", "source": "메일", "text": "January", "who": ""}],
                     "20260101-20260131")
        self.write("outlook/mail.csv", [{"time": "2026-01-05", "subject": "January"}])
        foreign = {"period": ["2026-04-01", "2026-04-30"], "worked_h": 999}
        (self.report / "mm_meta_20260401-20260430.json").write_text(json.dumps(foreign), encoding="utf-8")
        for metadata in (None, foreign, []):
            with self.subTest(metadata=metadata):
                if metadata is not None:
                    (self.report / "mm_meta_20260101-20260131.json").write_text(json.dumps(metadata), encoding="utf-8")
                replies = []
                self.ns["do_GET"](SimpleNamespace(path="/api/dash", _send=lambda *reply: replies.append(reply)))
                self.assertEqual(replies[0][0], 200)
                payload = replies[0][1]
                self.assertEqual(payload["meta"], {})
                self.assertEqual(payload["period"], ["2026-01-01", "2026-01-31"])
                self.assertEqual(payload["trend_info"]["counted"], 1)

    def test_default_run_and_batch_periods_match_ui_year_to_date(self):
        source = (PROJECT / "LoadMonitor25" / "run.py").read_text(encoding="utf-8-sig")
        tree = ast.parse(source)
        main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
        statement = next(n for n in main.body if isinstance(n, ast.Assign)
                         and any(isinstance(t, ast.Name) and t.id == "d0" for t in n.targets))
        ns = {"date": date, "arg": lambda _: None}
        exec(compile(ast.Module(body=[statement], type_ignores=[]), "run period", "exec"), ns)
        self.assertEqual(ns["d0"], date.today().replace(month=1, day=1).isoformat())
        batch = (PROJECT / "LoadMonitor25" / "LoadMonitor25.bat").read_text(encoding="cp949")
        expression = re.search(r'-c "(import datetime,sys;[^\n]+?)" %DAYS% %SEL%', batch).group(1)
        result = subprocess.run([sys.executable, "-c", expression, "90", "0"], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.stdout.strip(), ns["d0"])


if __name__ == "__main__":
    unittest.main()
