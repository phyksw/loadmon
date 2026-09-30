"""Independent saved-ledger review acceptance: TEMP files and actual page JS only."""
import ast
from collections import Counter, defaultdict
import copy
import csv
from datetime import date, datetime
from html.parser import HTMLParser
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
from types import ModuleType, SimpleNamespace
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1] / "LoadMonitor25"
TAG = "20260101-20260228"


def selected(relative, names=(), env=None, methods=()):
    path = ROOT / relative
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    body = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    for cls in tree.body:
        if isinstance(cls, ast.ClassDef) and cls.name == "H":
            body += [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in methods]
    ns = {"os": os, "json": json, "re": re, "csv": csv, "date": date, "datetime": datetime, "time": time,
          "Counter": Counter, "defaultdict": defaultdict}
    ns.update(env or {})
    exec(compile(ast.Module(body=body, type_ignores=[]), str(path), "exec"), ns)
    return ns


def meta(tag=TAG, days=None, capacities=None):
    days = {"2026-01-05": 8, "2026-02-05": 16} if days is None else days
    lo, hi = (date.fromisoformat(value) for value in tag.split("-"))
    cursor = lo.replace(day=1)
    months = {}
    while cursor <= hi:
        key = cursor.strftime("%Y-%m")
        worked = sum(value for day, value in days.items() if day.startswith(key))
        capacity = (capacities or {}).get(key, 160)
        months[key] = {"worked": worked, "capacity_h": capacity, "mm": round(worked / capacity, 3)}
        cursor = date(cursor.year + 1, 1, 1) if cursor.month == 12 else date(cursor.year, cursor.month + 1, 1)
    return {"period": [lo.isoformat(), hi.isoformat()], "day_hours": dict(days),
            "mm_months": months, "total_mm": round(sum(m["mm"] for m in months.values()), 3)}


def rows():
    return [{"time": day + " 09:00", "weight": "1", "project": "Synthetic project",
             "source": "메일", "text": "Synthetic evidence", "who": "나", "detail": "Review", "worktype": "사무"}
            for day in ("2026-01-05", "2026-02-05")]


class Elements(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.items = []
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        self.items.append({"tag": tag, **dict(attrs)})


class ReviewMeasurementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="lm25-measured-review-")
        self.addCleanup(self.temp.cleanup)
        self.rep = Path(self.temp.name)
        module_path = self.rep / "review_basis.py"
        shutil.copyfile(ROOT / "core/review_basis.py", module_path)
        spec = importlib.util.spec_from_file_location("review_basis", module_path)
        self.basis = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.basis)
        self.patcher = mock.patch.dict(sys.modules, {"review_basis": self.basis})
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def groups(self, gran="month", source_rows=None, tag=TAG):
        ns = selected("ui/app.py", {"review"}, {"REPORT": str(self.rep),
                      "_rows": lambda _path: copy.deepcopy(rows() if source_rows is None else source_rows)})
        return ns["review"](gran, tag)

    def project(self, gran="month", saved=None, source_rows=None, tag=TAG):
        return self.basis.project(self.groups(gran, source_rows, tag), saved, tag, gran)

    def render(self, groups, kind="month", tag=TAG):
        tree = ast.parse((ROOT / "ui/app.py").read_text(encoding="utf-8-sig"))
        page = ast.literal_eval(next(n.value for n in tree.body if isinstance(n, ast.Assign)
                                     and any(isinstance(t, ast.Name) and t.id == "PAGE" for t in n.targets)))
        script = page.split("<script>", 1)[1].split("</script>", 1)[0]
        payload = {"gran": kind, "groups": groups, "tag": tag, "available_periods": [tag], "missing_signals": False}
        program = ("const source=" + json.dumps(script) + ";const elements=" + json.dumps(Elements(page).items)
                   + ";const payload=" + json.dumps(payload, ensure_ascii=False) + ";const kind=" + json.dumps(kind) + ";\n" + r'''
const vm=require('node:vm');
const nodes=elements.map(e=>({...e,value:'',checked:false,disabled:false,style:{},dataset:{},
 innerHTML:'',classList:{toggle(){}},addEventListener(){},querySelectorAll(){return []}}));
const byId=Object.fromEntries(nodes.filter(n=>n.id).map(n=>[n.id,n]));
const context={console,AbortController,
 document:{getElementById:id=>byId[id]||null,querySelector:()=>null,
  querySelectorAll:selector=>selector==='details'?nodes.filter(n=>n.tag==='details'):[]},
 fetch:()=>new Promise(()=>{}),setInterval:()=>1,clearInterval(){},setTimeout:()=>1,clearTimeout(){},
 confirm:()=>{throw Error('Unexpected modal')},alert:()=>{throw Error('Unexpected modal')},window:{}};
vm.createContext(context);vm.runInContext(source,context);
const calls=[];
context.fetch=async url=>{
 calls.push(url);
 if(url.startsWith('/api/review?'))return {json:async()=>payload};
 if(url.startsWith('/api/extra?'))return {json:async()=>({narratives:{}})};
 throw Error('Unexpected request '+url);
};
(async()=>{await context.loadReview(kind);
 process.stdout.write(JSON.stringify({html:byId['rv-'+kind].innerHTML,calls,payload}));
})().catch(error=>{console.error(error.stack);process.exitCode=1});
''')
        node = shutil.which("node")
        self.assertIsNotNone(node, "Node.js is required for actual page acceptance")
        proc = subprocess.run([node, "-"], input=program, capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        return json.loads(proc.stdout)

    def assert_unknown(self, result):
        self.assertTrue(result)
        for group in result:
            measured = group["measurement"]
            self.assertFalse(measured["available"])
            self.assertIsNone(measured["worked_h"])
            self.assertIsNone(measured["mm"])
            self.assertTrue(measured["reason"])
            self.assertTrue(all(p["mm"] is None for p in group["projects"]))

    def test_two_months_saved_hours_and_mm_agree_across_month_week_and_all(self):
        saved = meta()
        monthly = {g["key"]: g for g in self.project(saved=saved)}
        self.assertEqual(monthly["2026-01"]["measurement"]["worked_h"], 8)
        self.assertEqual(monthly["2026-01"]["measurement"]["mm"], .05)
        self.assertEqual(monthly["2026-02"]["measurement"]["worked_h"], 16)
        self.assertEqual(monthly["2026-02"]["measurement"]["mm"], .10)
        for gran in ("month", "week", "all"):
            projected = self.project(gran, saved)
            self.assertEqual(sum(g["measurement"]["worked_h"] for g in projected), 24)
            self.assertAlmostEqual(sum(g["measurement"]["mm"] for g in projected), .15, places=6)

    def test_large_signal_weight_and_count_do_not_create_project_or_period_mm(self):
        source = rows() * 2000
        for row in source:
            row["weight"] = "100000"
        result = self.project(saved=meta(), source_rows=source)
        self.assertEqual(sum(g["signals"] for g in result), 4000)
        self.assertAlmostEqual(sum(g["measurement"]["mm"] for g in result), .15)
        for group in result:
            self.assertEqual(group["projects"][0]["share"], 1)
            self.assertIsNone(group["projects"][0]["mm"])
            self.assertEqual(group["projects"][0]["share_basis"], "signal_weight")

    def test_unknown_missing_wrong_period_and_inconsistent_meta_are_not_zero(self):
        cases = [None, [], {}, dict(meta(), period=["2025-01-01", "2025-02-28"]),
                 dict(meta(), day_hours=None), dict(meta(), mm_months={}), dict(meta(), total_mm=1)]
        for saved in cases:
            with self.subTest(saved=saved):
                self.assert_unknown(self.project(saved=saved))

    def test_invalid_daily_values_and_explicit_invalid_totals_are_rejected(self):
        for invalid in (float("nan"), float("inf"), -1, 25, True, "bad"):
            saved = meta()
            saved["day_hours"]["2026-01-05"] = invalid
            with self.subTest(day=invalid):
                self.assert_unknown(self.project(saved=saved))
        for invalid in (float("nan"), float("inf"), -1, True, None, "bad"):
            with self.subTest(total=invalid):
                self.assert_unknown(self.project(saved=dict(meta(), total_mm=invalid)))

    def test_complete_zero_ledger_is_measured_zero_and_positive_without_signals_is_visible(self):
        zero = self.project(saved=meta(days={}), source_rows=[])
        self.assertEqual(len(zero), 2)
        self.assertTrue(all(g["measurement"]["available"] for g in zero))
        self.assertEqual(sum(g["measurement"]["worked_h"] for g in zero), 0)
        self.assertEqual(sum(g["measurement"]["mm"] for g in zero), 0)
        result = self.project(saved=meta(), source_rows=rows()[:1])
        february = next(g for g in result if g["key"] == "2026-02")
        self.assertEqual(february["signals"], 0)
        self.assertEqual(february["projects"], [])
        self.assertEqual(february["measurement"]["worked_h"], 16)
        html = self.render(result)["html"]
        self.assertIn("2026년 02월", html)
        self.assertIn("16.0h · 0.100 MM", html)

    def test_partial_month_preserves_whole_month_denominator(self):
        tag = "20260115-20260120"
        saved = meta(tag, {"2026-01-15": 8}, {"2026-01": 160})
        result = self.project(saved=saved, source_rows=[], tag=tag)
        self.assertEqual(result[0]["period"], ["2026-01-15", "2026-01-20"])
        self.assertEqual(result[0]["measurement"]["worked_h"], 8)
        self.assertEqual(result[0]["measurement"]["mm"], .05)

    def test_week_crossing_year_and_month_sums_both_saved_months(self):
        tag = "20251229-20260104"
        saved = meta(tag, {"2025-12-31": 8, "2026-01-02": 16}, {"2025-12": 160, "2026-01": 200})
        weekly = self.project("week", saved, [], tag)
        self.assertEqual(len(weekly), 1)
        self.assertEqual(weekly[0]["period"], ["2025-12-29", "2026-01-04"])
        self.assertEqual(weekly[0]["measurement"]["worked_h"], 24)
        self.assertEqual(weekly[0]["measurement"]["mm"], .13)
        self.assertAlmostEqual(sum(g["measurement"]["mm"] for g in self.project("month", saved, [], tag)), .13)

    def test_projection_does_not_change_source_groups_or_metadata(self):
        groups, saved = self.groups(), meta()
        before = copy.deepcopy((groups, saved))
        result = self.basis.project(groups, saved, TAG, "month")
        result[0]["projects"][0]["name"] = "Changed copy"
        self.assertEqual((groups, saved), before)

    def test_actual_api_uses_exact_period_metadata_and_corrupt_missing_remain_unknown(self):
        for tag, scale in ((TAG, 1), ("20260301-20260430", 10)):
            (self.rep / f"mm_meta_{tag}.json").write_text(json.dumps(meta() if scale == 1 else {"total_mm": 999}), encoding="utf-8")
        signals = self.rep / f"signals_{TAG}.csv"
        with signals.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=rows()[0])
            writer.writeheader()
            writer.writerows(rows())
        ns = selected("ui/app.py", {"review", "measured_review", "_rows"},
                      {"REPORT": str(self.rep), "TEAM_FILES": {}, "review_source": lambda tag: {"tag": tag}}, {"do_GET"})
        handler = SimpleNamespace(path=f"/api/review?g=month&tag={TAG}", _send=mock.Mock())
        before = {p.name: p.read_bytes() for p in self.rep.iterdir() if p.is_file()}
        ns["do_GET"](handler)
        status, payload = handler._send.call_args.args
        self.assertEqual(status, 200)
        self.assertEqual(payload["tag"], TAG)
        self.assertAlmostEqual(sum(g["measurement"]["mm"] for g in payload["groups"]), .15)
        self.assertEqual({p.name: p.read_bytes() for p in self.rep.iterdir() if p.is_file()}, before)
        target = self.rep / f"mm_meta_{TAG}.json"
        target.write_text("{", encoding="utf-8")
        self.assert_unknown(ns["measured_review"]("month", TAG))
        target.unlink()
        self.assert_unknown(ns["measured_review"]("month", TAG))

    def test_actual_page_shows_measured_hours_mm_and_project_evidence_share(self):
        groups = self.project(saved=meta())
        result = self.render(groups)
        for text in ("8.0h · 0.050 MM", "16.0h · 0.100 MM", "근거 비중 100%", "신호 1건"):
            self.assertIn(text, result["html"])
        self.assertEqual(result["payload"]["groups"], groups)
        self.assertNotIn("NaN", result["html"])
        unknown = self.render(self.project(saved=None))["html"]
        self.assertIn("시간 산정 자료 없음", unknown)
        self.assertNotIn("1.000 MM", unknown)
        self.assertNotIn("0.000 MM", unknown)

    def test_actual_rehours_clears_previous_day_ledger_when_all_work_is_removed(self):
        target = self.rep / f"mm_meta_{TAG}.json"
        target.write_text(json.dumps(dict(meta(), worked_h=24)), encoding="utf-8")
        extract = ModuleType("extract")
        extract.rehours_after_judge = mock.Mock(return_value={"day_hours": {}, "total_mm": 0, "avail_mm": 2,
                                                             "months": meta(days={})["mm_months"]})
        ns = selected("judge.py", {"rehours_meta"}, {"ROOT": str(self.rep),
                      "_period_of": lambda _m, _t: (date(2026, 1, 1), date(2026, 2, 28)),
                      "_mine_exclude": lambda _cfg: [], "_read_dropped": lambda *_a: [],
                      "_write_dropped": mock.Mock()})
        with mock.patch.dict(sys.modules, {"extract": extract}):
            result = ns["rehours_meta"]([], rows(), TAG, {}, str(self.rep), str(self.rep / "synthetic-data"))
        saved = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(result["total_mm"], 0)
        self.assertEqual(saved["day_hours"], {})
        self.assertEqual(saved["worked_h"], 0)
        projected = self.project(saved=saved, source_rows=[])
        self.assertTrue(all(g["measurement"]["available"] for g in projected))
        self.assertTrue(all(g["measurement"]["mm"] == 0 for g in projected))


if __name__ == "__main__":
    unittest.main()
