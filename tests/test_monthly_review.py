"""Monthly review contracts: selected AST, fake Node DOM/fetch, synthetic TEMP only."""
import ast
from collections import Counter, defaultdict
import contextlib
import copy
import csv
from datetime import date, datetime
import glob
import html
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
TAG = "20260101-20260228"
ROWS = [
    {"time": "2026-01-05 09:00", "weight": "2", "project": "Synthetic project", "source": "파일",
     "text": "Synthetic design.txt", "who": "나", "detail": "Synthetic design", "worktype": "개발"},
    {"time": "2026-01-05 10:00", "weight": "1", "project": "Synthetic project", "source": "회의",
     "text": "Synthetic meeting", "who": "Synthetic colleague", "detail": "Synthetic review", "worktype": "협업"},
    {"time": "2026-02-05 09:00", "weight": "1", "project": "Synthetic project", "source": "메일",
     "text": "Synthetic request", "who": "Synthetic colleague", "detail": "Synthetic response", "worktype": "사무"},
]


def load(version, relative, names, env=None, methods=()):
    path = ROOT / version / relative
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    chosen = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in names for t in node.targets):
            chosen.append(node)
        if methods and isinstance(node, ast.ClassDef) and node.name == "H":
            chosen += [n for n in node.body if isinstance(n, ast.FunctionDef) and n.name in methods]
    ns = {"os": os, "json": json, "re": re, "time": time, "date": date, "datetime": datetime,
          "csv": csv, "glob": glob, "Counter": Counter, "defaultdict": defaultdict, **(env or {})}
    exec(compile(ast.Module(body=chosen, type_ignores=[]), str(path), "exec"), ns)
    return ns


def page(version="LoadMonitor25"):
    tree = ast.parse((ROOT / version / "ui/app.py").read_text(encoding="utf-8-sig"))
    return next(n.value.value for n in tree.body if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "PAGE" for t in n.targets))


def js_function(source, signature):
    start = source.index(signature)
    return source[start:source.index("\n}", start) + 2]


def node(code):
    runtime = shutil.which("node")
    if not runtime:
        raise unittest.SkipTest("Node is required for the synthetic UI contract")
    path = Path(tempfile.mkdtemp(prefix="lm25-monthly-node-")) / "probe.js"
    path.write_text(code, encoding="utf-8")
    result = subprocess.run([runtime, str(path)], capture_output=True, text=True, encoding="utf-8", timeout=20)
    if result.returncode:
        raise AssertionError(result.stderr)
    return json.loads(result.stdout)


def groups(version="LoadMonitor25"):
    ns = load(version, "ui/app.py", {"review"}, {"_rows": lambda _p: copy.deepcopy(ROWS),
                                                "latest_signals": lambda: "synthetic.csv"})
    return ns["review"]("month")


def render_month(version, narratives, frozen=False):
    source = page(version)
    constants = "\n".join(re.search(r"^const " + name + r"=.*;$", source, re.M)[0] for name in ("PAL", "WTCOL", "esc"))
    code = constants + "\n" + js_function(source, "function connSVG(") + "\n" + js_function(source, "async function loadReview(")
    payload = {"review": {"gran": "month", "groups": groups(version), "tag": TAG,
                          "available_periods": [TAG], "missing_signals": False},
               "extra": {"tag": TAG, "narratives": narratives}}
    transport = "const fetch=async url=>({json:async()=>url.startsWith('/api/review')?payload.review:payload.extra});\n"
    if frozen:
        intercept = load(version, "freeze.py", {"INTERCEPT_JS"})["INTERCEPT_JS"]
        transport = ("const baked={_lm:{tag:payload.review.tag},'/api/review?g=month':payload.review,'/api/extra':payload.extra};\n"
                     "const window=globalThis;const document={getElementById:()=>({textContent:JSON.stringify(baked)}),addEventListener:()=>{}};\n"
                     + intercept + "\n")
    return node("const payload=" + json.dumps(payload, ensure_ascii=False) + ";\n"
                + "const elements={};const $=id=>elements[id]||(elements[id]={innerHTML:''});\n"
                + "let reviewPeriod='',loaded={};const reloadVisibleTab=async()=>{};\n"
                + transport
                + code + "\n(async()=>{await loadReview('month');process.stdout.write(JSON.stringify({html:$('rv-month').innerHTML}));})().catch(e=>{console.error(e.stack);process.exitCode=1;});")


class MonthlySaveTests(unittest.TestCase):
    def setUp(self):
        self.rep = Path(tempfile.mkdtemp(prefix="lm25-monthly-save-"))
        self.path = self.rep / f"ai_narratives_{TAG}.json"
        self.old = {"2026-01": {"summary": "Previous January", "projects": []},
                    "2026-02": {"summary": "Previous February", "projects": []}}
        self.path.write_text(json.dumps(self.old), encoding="utf-8")
        self.save = load("LoadMonitor25", "judge.py", {"save_narratives"})["save_narratives"]

    def read(self):
        return json.loads(self.path.read_text(encoding="utf-8"))

    def test_partial_success_replaces_only_successful_month_and_marks_retained(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(self.save({"2026-01": {"summary": "New January", "projects": []}}, str(self.rep), TAG,
                                      {"2026-01", "2026-02"}))
        result = self.read()
        self.assertEqual(result["2026-01"]["summary"], "New January")
        self.assertEqual(result["2026-02"], self.old["2026-02"])
        self.assertEqual(result["_status"]["updated_months"], ["2026-01"])
        self.assertEqual(result["_status"]["retained_months"], ["2026-02"])
        self.assertTrue(result["_status"]["partial"])

    def test_all_failed_preserves_valid_months_without_claiming_new_success(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(self.save({}, str(self.rep), TAG, {"2026-01", "2026-02"}))
        result = self.read()
        self.assertEqual({k: v for k, v in result.items() if not k.startswith("_")}, self.old)
        self.assertEqual(result["_status"]["retained_months"], ["2026-01", "2026-02"])
        self.assertEqual(result["_status"]["updated_months"], [])

    def test_other_period_invalid_month_and_invalid_shape_never_replace_valid_entries(self):
        bad = {"2025-12": {"summary": "Foreign", "projects": []},
               "2026-13": {"summary": "Invalid month", "projects": []},
               "2026-01": {"summary": "Wrong projects", "projects": 123},
               "2026-02": {"summary": "", "projects": []}}
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(self.save(bad, str(self.rep), TAG))
        result = self.read()
        self.assertEqual({k: v for k, v in result.items() if not k.startswith("_")}, self.old)

    def test_foreign_tag_metadata_is_not_imported_and_inactive_month_is_not_missing(self):
        self.path.write_text(json.dumps({**self.old, "_status": {"tag": "20250101-20251231"}}), encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(self.save({"2026-01": self.old["2026-01"]}, str(self.rep), TAG, {"2026-01"}))
        result = self.read()
        self.assertNotIn("2026-02", result)
        self.assertFalse(result["_status"]["partial"])
        self.assertEqual(result["_status"]["missing_months"], [])

    def test_invalid_tag_and_failed_atomic_replace_leave_previous_file_intact(self):
        before = self.path.read_bytes()
        for tag in ("../wrong", "20260230-20260301", "20260201-20260101"):
            with self.assertRaises(ValueError):
                self.save({}, str(self.rep), tag)
        with mock.patch.object(os, "replace", side_effect=PermissionError("synthetic locked result")):
            with self.assertRaises(PermissionError):
                self.save({"2026-01": self.old["2026-01"]}, str(self.rep), TAG)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(list(self.rep.glob(".narratives-*.tmp")), [])

    def test_unreadable_previous_result_is_not_treated_as_missing(self):
        before = self.path.read_bytes()
        original_open = open

        def locked_open(path, *args, **kwargs):
            if os.path.abspath(path) == str(self.path):
                raise PermissionError("synthetic temporary read lock")
            return original_open(path, *args, **kwargs)

        with mock.patch("builtins.open", side_effect=locked_open), mock.patch.object(os, "replace") as replace:
            with self.assertRaises(PermissionError):
                self.save({"2026-01": {"summary": "New January", "projects": []}}, str(self.rep), TAG)
            replace.assert_not_called()
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(list(self.rep.glob(".narratives-*.tmp")), [])


class MonthlyViewTests(unittest.TestCase):
    def test_extra_api_returns_same_period_narratives_and_preservation_status(self):
        rep = Path(tempfile.mkdtemp(prefix="lm25-monthly-extra-"))
        narrative = {"2026-01": {"summary": "Synthetic previous summary", "projects": []},
                     "_status": {"schema": 1, "tag": TAG, "partial": True, "retained_months": ["2026-01"]}}
        (rep / f"ai_narratives_{TAG}.json").write_text(json.dumps(narrative), encoding="utf-8")
        (rep / "ai_narratives_20250101-20251231.json").write_text('{"foreign":true}', encoding="utf-8")
        (rep / f"signals_{TAG}.csv").write_text("time,weight,project,source,text,who,detail,worktype\n", encoding="utf-8")
        ns = load("LoadMonitor25", "ui/app.py", {"review_source"},
                  {"REPORT": str(rep), "TEAM_FILES": {}, "latest_signals": lambda: str(rep / f"signals_{TAG}.csv"),
                   "result_rows": lambda: ("", [])}, methods={"do_GET"})
        replies = []
        ns["do_GET"](SimpleNamespace(path="/api/extra", _send=lambda *args: replies.append(args)))
        self.assertEqual(replies[0][0], 200)
        self.assertEqual(replies[0][1]["narratives"], narrative)
        self.assertNotIn("foreign", replies[0][1]["narratives"])

    def test_current_and_explicit_periods_do_not_mix_signals_or_narratives(self):
        rep, ns = period_fixture("LoadMonitor25")
        raw = rep / "mm_rows_20260201-20260228.csv"
        raw.write_text("Level 2,Level 3,mm,share\nSynthetic,Work,0.1,1\n", encoding="utf-8")
        os.utime(raw, (40, 40))
        os.utime(rep / f"signals_{TAG}.csv", (50, 50))
        self.assertEqual(Path(ns["latest_signals"]()).name, "signals_20260201-20260228.csv")
        self.assertEqual([g["key"] for g in ns["review"]("month")], ["2026-02"])
        self.assertEqual([g["key"] for g in ns["review"]("month", TAG)], ["2026-02", "2026-01"])
        replies = []
        for selected, summary in ((TAG, "Full period"), ("20260201-20260228", "February only")):
            (rep / f"ai_narratives_{selected}.json").write_text(json.dumps({"2026-02": {"summary": summary}}), encoding="utf-8")
            ns["do_GET"](SimpleNamespace(path=f"/api/review?g=month&tag={selected}", _send=lambda *args: replies.append(args)))
            response = replies[-1][1]
            self.assertEqual(response["tag"], selected)
            self.assertEqual(response["missing_signals"], False)
            self.assertEqual(len(response["available_periods"]), 2)
            ns["do_GET"](SimpleNamespace(path=f"/api/extra?tag={selected}", _send=lambda *args: replies.append(args)))
            self.assertEqual(replies[-1][1]["narratives"]["2026-02"]["summary"], summary)

    def test_missing_current_signals_is_explicit_and_invalid_period_is_rejected(self):
        rep, ns = period_fixture("LoadMonitor25")
        (rep / "mm_rows_20260301-20260331.csv").write_text("Level 2,Level 3,mm,share\nSynthetic,Work,0.1,1\n", encoding="utf-8")
        self.assertEqual(ns["latest_signals"](), "")
        self.assertEqual(ns["review"]("month"), [])
        replies = []
        ns["do_GET"](SimpleNamespace(path="/api/review?g=month", _send=lambda *args: replies.append(args)))
        self.assertEqual(replies[-1][1]["tag"], "20260301-20260331")
        self.assertTrue(replies[-1][1]["missing_signals"])
        self.assertEqual(replies[-1][1]["groups"], [])
        for path in ("/api/review?g=month&tag=../invalid", "/api/extra?tag=../invalid"):
            ns["do_GET"](SimpleNamespace(path=path, _send=lambda *args: replies.append(args)))
            self.assertEqual(replies[-1][0], 400)

    def test_lm24_and_lm25_keep_raw_project_people_outputs_and_timeline(self):
        for version in ("LoadMonitor24", "LoadMonitor25"):
            with self.subTest(version=version):
                result = groups(version)
                self.assertEqual([g["key"] for g in result], ["2026-02", "2026-01"])
                january = result[1]
                self.assertEqual(january["projects"][0]["files"], ["Synthetic design.txt"])
                self.assertEqual(january["projects"][0]["meets"], ["Synthetic meeting"])
                self.assertEqual(january["projects"][0]["people"], [["Synthetic colleague", 1]])
                self.assertEqual(len(january["timeline"][0]["lines"]), 2)
                self.assertTrue(january["p_edges"] and january["a_edges"])

    def test_monthly_js_renders_story_and_raw_features_with_or_without_narrative(self):
        for version in ("LoadMonitor24", "LoadMonitor25"):
            with self.subTest(version=version):
                result = render_month(version, {"2026-01": {"summary": "Synthetic January summary", "projects": [
                    {"name": "Synthetic project", "story": "Synthetic contribution story", "worktypes": "개발"}]}})
                for text in ("Synthetic January summary", "Synthetic contribution story", "Synthetic design.txt",
                             "Synthetic colleague", "Synthetic meeting", "Synthetic request", "원문 근거 타임라인", "업무 연결성"):
                    self.assertIn(text, result["html"])
                missing = render_month(version, {})["html"]
                self.assertIn("리뷰 코멘트 재생성", missing)
                self.assertIn("Synthetic design.txt", missing)

    def test_monthly_js_shows_preserved_status_and_same_period_selector(self):
        result = render_month("LoadMonitor25", {"2026-01": {"summary": "Retained January", "projects": []},
                                              "_status": {"retained_months": ["2026-01"]}})
        self.assertIn("이전 코멘트를 보존했습니다", result["html"])
        self.assertIn('value="' + TAG + '"', result["html"])
        self.assertIn("리뷰 분석 기간", result["html"])

    def test_frozen_monthly_js_keeps_narrative_with_period_qualified_extra(self):
        result = render_month("LoadMonitor25", {"2026-01": {"summary": "Frozen January summary", "projects": []}}, frozen=True)
        self.assertIn("Frozen January summary", result["html"])

    def test_frozen_intercept_exposes_only_frozen_period_and_rejects_other_tags(self):
        intercept = load("LoadMonitor25", "freeze.py", {"INTERCEPT_JS"})["INTERCEPT_JS"]
        result = node("const T=" + json.dumps(TAG) + ";\n" + """
const D={_lm:{tag:T},'/api/review?g=month':{tag:T,groups:[{key:'Synthetic'}],available_periods:[T,'20250101-20251231']},
 '/api/extra':{tag:T,narratives:{'2026-01':{summary:'Frozen story'}}},
 '/api/review?g=week':{tag:'20250101-20251231',groups:[{key:'Wrong period'}]}};
const window=globalThis,document={getElementById:()=>({textContent:JSON.stringify(D)}),addEventListener:()=>{}};
""" + intercept + """
(async()=>{
 const urls=['/api/review?g=month','/api/review?g=month&tag='+T,'/api/extra?tag='+T,
 '/api/review?g=month&tag=20250101-20251231','/api/extra?tag=20250101-20251231',
 '/api/review?g=week','/api/extra?tag='+T+'&unexpected=1'];
 const values=[];for(const url of urls)values.push(await (await fetch(url)).json());
 values.push(await (await fetch('/api/extra?tag='+T,{method:'POST'})).json());
 process.stdout.write(JSON.stringify(values));
})().catch(e=>{console.error(e.stack);process.exitCode=1;});
""")
        for result_row in result[:2]:
            self.assertEqual(result_row["available_periods"], [TAG])
            self.assertEqual(result_row["groups"], [{"key": "Synthetic"}])
        self.assertEqual(result[2]["narratives"]["2026-01"]["summary"], "Frozen story")
        self.assertTrue(all(row.get("ok") is False for row in result[3:]))

    def test_visible_month_reload_after_completion_without_another_click(self):
        source = page()
        run_state = source.split("let timer=null;", 1)[1].split("async function poll(", 1)[0]
        code = run_state + js_function(source, "async function poll(") + "\n" + js_function(source, "async function reloadVisibleTab(")
        result = node("""
const elements={};const $=id=>elements[id]||(elements[id]={innerHTML:'old',style:{},textContent:'',scrollHeight:0});
const document={querySelector:()=>({dataset:{t:'month'}})};
let loaded={month:1},wasRunning=true,timer=null,dashReloads=0,monthReloads=0;
const esc=String,clearInterval=()=>{};
const refresh=async()=>{dashReloads++;};
const loadReview=async kind=>{if(kind==='month'){monthReloads++;$('rv-month').innerHTML='new';}};
const loadFlow=async()=>{},loadAgentic=async()=>{};
const fetch=async()=>({json:async()=>({running:false,log:[],step:'',sources:[]})});
""" + code + "\n(async()=>{await poll();process.stdout.write(JSON.stringify({dashReloads,monthReloads,html:$('rv-month').innerHTML}));})().catch(e=>{console.error(e.stack);process.exitCode=1;});")
        self.assertEqual(result, {"dashReloads": 1, "monthReloads": 1, "html": "new"})

    def test_full_frozen_report_keeps_monthly_review_summary_copy_removes_it(self):
        for full in (True, False):
            with self.subTest(full=full):
                rep = Path(tempfile.mkdtemp(prefix="lm25-monthly-frozen-"))
                payload = {"/api/dash": {"meta": {"period": ["2026-01-01", "2026-02-28"]}},
                           "/api/review?g=month": {"gran": "month", "groups": groups()},
                           "/api/extra": {"narratives": {"2026-01": {"summary": "Synthetic narrative", "projects": []}}}}
                written = []

                def write(path, text):
                    path = Path(path)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(text, encoding="utf-8")
                    written.append(text)
                    return str(path)

                env = {"_say": lambda *args: None, "bake": lambda *args: ("<html><body>synthetic</body></html>", copy.deepcopy(payload)),
                       "REPORT": str(rep), "FREEZE_DIR": str(rep / "archive"), "_owner": lambda: "Synthetic", "_host": lambda: "PC",
                       "_is_stub": lambda: False, "_esc": html.escape, "_safe_name": lambda s: s, "_size_txt": lambda p: "",
                       "_write_atomic": write, "tag_of": lambda d0, d1: d0.replace("-", "") + "-" + d1.replace("-", "")}
                ns = load("LoadMonitor25", "freeze.py", {"_freeze", "_strip_evidence", "INTERCEPT_JS"}, env)
                files = ns["_freeze"](TAG, full, "synthetic-no-network", lambda *_: None, {})
                self.assertEqual(len(files), 2)
                baked = json.loads(re.search(r'id="lm-frozen-data">(.*?)</script>', written[0], re.S)[1])
                self.assertEqual(bool(baked["/api/review?g=month"]["groups"]), full)
                self.assertEqual("narratives" in baked["/api/extra"], full)


def period_fixture(version):
    rep = Path(tempfile.mkdtemp(prefix="lm25-monthly-period-"))
    for tag, rows, stamp in ((TAG, ROWS, 20), ("20260201-20260228", ROWS[2:], 30)):
        path = rep / f"signals_{tag}.csv"
        with path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(ROWS[0]))
            writer.writeheader()
            writer.writerows(rows)
        os.utime(path, (stamp, stamp))
    ns = load(version, "ui/app.py", {"review", "review_source", "latest_signals", "_rows", "_mtime", "result_rows", "_fresh_refined"},
              {"REPORT": str(rep), "TEAM_FILES": {}}, methods={"do_GET"})
    return rep, ns


def diagnostics():
    """Compare historical period selection with the current explicit-period contract."""
    out = {}
    for version in ("LoadMonitor24", "LoadMonitor25"):
        rep, ns = period_fixture(version)
        visible = [g["key"] for g in ns["review"]("month")]
        # A normal signals rewrite (retag/judge) can disagree with latest MM rows.
        raw = rep / "mm_rows_20260201-20260228.csv"
        raw.write_text("Level 2,Level 3,mm,share\nSynthetic,Work,0.1,1\n", encoding="utf-8")
        os.utime(raw, (40, 40))
        os.utime(rep / f"signals_{TAG}.csv", (50, 50))
        out[version] = {"narrow_latest_visible_months": visible, "dashboard_file": ns["result_rows"]()[0],
                        "latest_signals": Path(ns["latest_signals"]()).name,
                        "review_months_after_other_signals_touch": [g["key"] for g in ns["review"]("month")],
                        "synthetic_directory": str(rep)}
    return out


if __name__ == "__main__":
    import sys
    if "--diagnostics" in sys.argv:
        print(json.dumps(diagnostics(), ensure_ascii=True, indent=2))
    else:
        unittest.main()
