"""Independent improvement checks: actual page JS with synthetic data, no server or AI."""
import ast
import calendar
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import shutil
import subprocess
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "LoadMonitor25/ui/app.py"


class _Elements(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.items = []
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        self.items.append({"tag": tag, **dict(attrs)})


class ImprovementAuditTests(unittest.TestCase):
    def render_page(self, payload, action):
        tree = ast.parse(SOURCE.read_text(encoding="utf-8-sig"))
        page = ast.literal_eval(next(n.value for n in tree.body if isinstance(n, ast.Assign)
                                     and any(isinstance(t, ast.Name) and t.id == "PAGE" for t in n.targets)))
        script = page.split("<script>", 1)[1].split("</script>", 1)[0]
        program = ("const source=" + json.dumps(script) + ";\nconst elements="
                   + json.dumps(_Elements(page).items) + ";\nconst payload="
                   + json.dumps(payload, ensure_ascii=False) + ";\n" + r'''
const vm=require('node:vm');
const nodes=elements.map(e=>({...e,value:'',checked:false,disabled:false,style:{},dataset:{},
 innerHTML:'',classList:{toggle(){}},addEventListener(){},querySelectorAll(){return []}}));
const byId=Object.fromEntries(nodes.filter(n=>n.id).map(n=>[n.id,n]));
const context={console,AbortController,
 document:{getElementById:id=>byId[id]||null,
  querySelectorAll:selector=>selector==='details'?nodes.filter(n=>n.tag==='details'):[],querySelector:()=>null},
 fetch:()=>new Promise(()=>{}),setInterval:()=>1,clearInterval(){},
 setTimeout:()=>1,clearTimeout(){},
 confirm:()=>{throw Error('Read-only workflow view must not ask for a modal')},
 alert:()=>{throw Error('Unexpected modal')},window:{}};
vm.createContext(context);
vm.runInContext(source,context);
context.fetch=async url=>{
 if(!['/api/workflow','/api/dash'].includes(url))throw Error('Unexpected request: '+url);
 return {status:200,ok:true,json:async()=>payload};
};
''' + "\n(async()=>{\n" + action
                   + "\n})().catch(error=>{console.error(error);process.exitCode=1});")
        node = shutil.which("node")
        self.assertIsNotNone(node, "Node.js is required to verify the rendered page")
        proc = subprocess.run([node, "-"], input=program, capture_output=True,
                              text=True, encoding="utf-8", timeout=20)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        return json.loads(proc.stdout)

    def render_workflows(self, payload):
        return self.render_page(payload, "await context.loadFlow();"
                                "process.stdout.write(JSON.stringify({html:byId['rv-flow'].innerHTML,payload}));")

    @staticmethod
    def review_flow():
        return {"unit_id": "unit_synthetic_review", "model": "Synthetic project / Review duty",
                "project": "Synthetic project", "detail": "Review duty", "level1": "신제품개발",
                "role": "Synthetic review role", "summary": "Synthetic review summary",
                "needs_review": True, "kpi_eligible": False,
                "review_reason": "Synthetic review reason", "mm": {"mm": None, "details": {}},
                "steps": [{"order": 1, "name": "Synthetic review step",
                           "desc": "Synthetic review description", "agent": "",
                           "evidence": "Synthetic unresolved evidence", "evidence_status": "invalid",
                           "needs_review": True, "agent_how": "Synthetic proposed action"}]}

    def test_review_only_results_are_visible_without_a_false_empty_state(self):
        payload = {"ok": True, "tag": "20260801-20260831", "partial": True,
                   "missing_count": 1, "resumable": False, "rows_units": 1,
                   "flows": [], "review_flows": [self.review_flow()]}
        result = self.render_workflows(payload)
        for content in ("Review duty", "Synthetic review role", "Synthetic review description",
                        "Synthetic unresolved evidence", "Synthetic review reason"):
            self.assertIn(content, result["html"])
        self.assertIn("확인 필요", result["html"])
        self.assertNotIn("워크플로우 분석이 없습니다", result["html"])
        self.assertEqual(result["payload"], payload)

    def test_review_and_completed_results_both_render_and_escape_untrusted_text(self):
        pending = self.review_flow()
        pending["detail"] = '<img src=x onerror="audit">'
        complete = {"model": "Synthetic project / Completed duty", "project": "Synthetic project",
                    "detail": "Completed duty", "level1": "신제품개발", "role": "Completed role",
                    "needs_review": False, "kpi_eligible": True, "mm": {"mm": 0.25},
                    "steps": [{"name": "Completed step", "agent": "중", "evidence": "Verified evidence"}]}
        payload = {"ok": True, "tag": "20260801-20260831", "flows": [complete],
                   "review_flows": [pending], "rows_units": 2}
        result = self.render_workflows(payload)
        for content in ("Completed duty", "Completed step", "Verified evidence", "Synthetic review step"):
            self.assertIn(content, result["html"])
        self.assertIn("&lt;img", result["html"])
        self.assertNotIn('<img src=x onerror="audit">', result["html"])
        self.assertEqual(result["payload"], payload)

    def test_pc_missing_band_does_not_hide_existing_mail_and_file_activity(self):
        payload = [{"label": "2026-01", "pc_h": 0, "pc_wd": 22, "pc_days": 0,
                    "파일": 1, "작업창": 0, "메일": 2, "회의": 0, "커밋": 0, "팀즈": 0}]
        result = self.render_page(payload, "context.weekly(byId.weekly,payload);"
                                  "process.stdout.write(JSON.stringify({html:byId.weekly.innerHTML}));")
        nodes = _Elements(result["html"]).items
        bands = [i for i, n in enumerate(nodes) if n["tag"] == "rect" and n.get("fill") == "#f2f3f5"]
        activity = [i for i, n in enumerate(nodes) if n["tag"] == "rect"
                    and n.get("fill") in ("#2a78d6", "#0e8c7a")]
        self.assertEqual(len(activity), 2, "Both positive signal series must have visible bars")
        self.assertTrue(bands, "The missing PC observation must remain marked")
        self.assertLess(max(bands), min(activity), "Opaque PC gap band must be behind existing activity")
        self.assertNotIn("NaN", result["html"])

    def test_refresh_displays_all_nine_months_raw_counts_and_separate_sampler_observations(self):
        period = ["2026-01-01", "2026-09-13"]
        keys = ["파일", "메일", "회의", "커밋", "팀즈", "수동"]
        trend = []
        for month in range(1, 10):
            counts = dict.fromkeys(keys, 0)
            counts.update({"파일": 12 if month == 1 else 0, "메일": month,
                           "수동": 1 if month == 9 else 0})
            trend.append({"label": f"2026-{month:02d}", "from": f"2026-{month:02d}-01",
                          "to": f"2026-{month:02d}-{13 if month == 9 else calendar.monthrange(2026, month)[1]}",
                          "counts": counts, **counts, "window_samples": month * 10,
                          "pc_h": 0 if month == 1 else 7.5, "pc_days": 0 if month == 1 else 1,
                          "pc_record_days": 0 if month == 1 else 1, "pc_wd": 20})
        payload = {"version": "Synthetic", "port": 0, "rows": [], "sources": [], "total": 0,
                   "period": period, "meta": {"period": period, "signals": 3}, "trend": trend,
                   "trend_src": "raw", "trend_info": {"period": period, "gran": "month",
                   "counted": 58, "displayed": 58, "raw_n": 82, "duplicates": 24, "capped": 0,
                   "signals_n": 3, "window_samples": 450,
                   "pc_buckets_all": 9, "pc_buckets": 8}}
        result = self.render_page(payload, r'''
byId.from.value='2026-08-01';byId.to.value='2026-08-31';
await context.refresh();
process.stdout.write(JSON.stringify({title:byId.wtitle.textContent,sub:byId.wsub.textContent,
 table:byId.wcounts.innerHTML,note:byId.wnote.innerHTML,chart:byId.weekly.innerHTML,
 metaper:byId.metaper.textContent,selection:[byId.from.value,byId.to.value],payload}));
''')
        self.assertEqual(result["title"], "월간 활동 추이")
        self.assertIn("2026-01-01 ~ 2026-09-13", result["sub"])
        self.assertIn("막대 하나 = 한 달", result["sub"])
        self.assertIn("2026-01-01 ~ 2026-09-13", result["metaper"])
        rows = [re.findall(r"<td>(.*?)</td>", row) for row in result["table"].split("<tr>")[2:]]
        self.assertEqual(len(rows), 9)
        for month, row in enumerate(rows, 1):
            bucket = trend[month - 1]
            self.assertEqual(row[0], bucket["from"] + " ~ " + bucket["to"])
            self.assertEqual([int(x) for x in row[1:7]], [bucket["counts"][k] for k in keys])
            self.assertEqual([int(x) for x in row[7:9]],
                             [sum(bucket["counts"].values()), sum(bucket[k] for k in keys)])
            self.assertEqual(row[9], "기록 없음" if month == 1 else "7.5h")
            self.assertEqual(int(row[10]), month * 10)
            self.assertIn(f"2026-{month:02d}", result["chart"])
        for message in ("58건", "중복 제외 24건", "3건", "450개",
                        "추가 PC", "파일 이력", "9개월 중 8개월", "상단 날짜는 다음 수집·분석"):
            self.assertIn(message, result["note"])
        self.assertNotIn("하루 8건", result["note"])
        self.assertNotIn("<th>작업창</th>", result["table"])
        self.assertNotIn("<th>기타</th>", result["table"])
        self.assertEqual(result["selection"], ["2026-08-01", "2026-08-31"])
        self.assertEqual(result["payload"], payload)
        self.assertNotIn("NaN", result["chart"])

    def test_refresh_preserves_old_frozen_window_and_other_series_when_present(self):
        payload = {"version": "Synthetic old report", "port": 0, "rows": [], "sources": [],
                   "total": 0, "period": ["2026-01-01", "2026-01-07"],
                   "trend": [{"label": "01/01", "파일": 0, "작업창": 3, "메일": 0, "회의": 0,
                              "커밋": 0, "팀즈": 0, "수동": 0, "기타": 2,
                              "pc_h": 0, "pc_wd": 5, "pc_days": 0}]}
        result = self.render_page(payload, "await context.refresh();"
                                  "process.stdout.write(JSON.stringify({table:byId.wcounts.innerHTML,"
                                  "chart:byId.weekly.innerHTML,legend:byId.wleg.innerHTML,payload}));")
        self.assertIn("<th>작업창</th>", result["table"])
        self.assertIn("<th>기타</th>", result["table"])
        self.assertIn("<td>3</td>", result["table"])
        self.assertIn("<td>2</td>", result["table"])
        self.assertEqual(result["table"].count("<td>5</td>"), 2)
        nodes = _Elements(result["chart"]).items
        activity = [n for n in nodes if n["tag"] == "rect" and n.get("fill") in ("#7a8a99", "#989280")]
        self.assertEqual(len(activity), 2)
        self.assertIn("작업창", result["legend"])
        self.assertIn("기타", result["legend"])
        self.assertNotIn("NaN", result["chart"])
        self.assertEqual(result["payload"], payload)

    def test_one_mail_remains_visible_beside_a_four_thousand_file_peak(self):
        payload = [{"label": "1월", "파일": 4000, "메일": 0, "pc_h": 0, "pc_wd": 20,
                    "pc_days": 0, "pc_record_days": 0},
                   {"label": "2월", "파일": 0, "메일": 1, "pc_h": 0, "pc_wd": 20,
                    "pc_days": 0, "pc_record_days": 0}]
        result = self.render_page(payload, "context.weekly(byId.weekly,payload);"
                                  "process.stdout.write(JSON.stringify({html:byId.weekly.innerHTML,"
                                  "legend:byId.wleg.innerHTML,payload}));")
        nodes = _Elements(result["html"]).items
        mail = [n for n in nodes if n["tag"] == "rect" and n.get("fill") == "#0e8c7a"]
        files = [n for n in nodes if n["tag"] == "rect" and n.get("fill") == "#2a78d6"]
        self.assertEqual(len(mail), 1, "A positive low-activity month must retain a visible mark")
        self.assertEqual(len(files), 1)
        self.assertGreaterEqual(float(mail[0]["height"]), 0.5)
        self.assertIn("2월 메일 1건", result["html"])
        self.assertIn("1월 파일 4000건", result["html"])
        gaps = [i for i, n in enumerate(nodes) if n["tag"] == "rect" and n.get("fill") == "#f2f3f5"]
        bars = [i for i, n in enumerate(nodes) if n in mail + files]
        self.assertEqual(len(gaps), 2)
        self.assertLess(max(gaps), min(bars))
        self.assertNotIn("작업창", result["legend"])
        self.assertNotIn("기타", result["legend"])
        self.assertEqual(result["payload"], payload)


if __name__ == "__main__":
    unittest.main()
