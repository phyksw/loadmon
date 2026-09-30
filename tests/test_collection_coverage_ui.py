"""Coverage API and actual renderer checks; synthetic TEMP statuses, no app server."""
import ast
from datetime import date
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


APP = Path(__file__).resolve().parents[1] / "LoadMonitor25"
SOURCE = APP / "ui/app.py"
PERIOD = ["2026-09-01", "2026-09-30"]


class CollectionCoverageUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tree = ast.parse(SOURCE.read_text(encoding="utf-8-sig"))
        page = ast.literal_eval(next(n.value for n in cls.tree.body if isinstance(n, ast.Assign)
                                    and any(isinstance(t, ast.Name) and t.id == "PAGE" for t in n.targets)))
        cls.renderer = "function renderCommunicationCoverage(" + page.split(
            "function renderCommunicationCoverage(", 1)[1].split("async function browseActivity(", 1)[0]
        cls.prelude = r'''
const assert=require('node:assert/strict');
const nodes=Object.fromEntries(['communicationcoverage','weekly','wtitle','wsub','activitytotal',
 'wcounts','wnote','wclump','activityfrom','activityto','from','to'].map(id=>
 [id,{innerHTML:'',textContent:'',style:{},value:''}]));
const $=id=>nodes[id]||null;
const document={getElementById:()=>null};
const esc=s=>String(s??'').replace(/&/g,'&amp;').replace(/</g,'&lt;')
 .replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
const weekly=()=>{};
let lastActivity=null;
'''

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="lm25-coverage-ui-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        helper = self.root / "collection_state.py"
        shutil.copyfile(APP / "core/collection_state.py", helper)
        spec = importlib.util.spec_from_file_location("coverage_synthetic_state", helper)
        self.state = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.state)
        modules = mock.patch.dict(sys.modules, {"collection_state": self.state})
        modules.start()
        self.addCleanup(modules.stop)
        names = {"communication_coverage", "activity_payload"}
        body = [n for n in self.tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
        self.assertEqual({n.name for n in body}, names)
        self.namespace = {
            "ROOT": str(self.root), "_tag_period": self.tag_period,
            "dash_period": lambda *_: PERIOD,
            "trend": lambda *_: [], "_activity_read_issues": lambda: [],
            "outlook_coverage": lambda *_: None, "mtime_clumps": lambda *_: [],
        }
        exec(compile(ast.Module(body=body, type_ignores=[]), str(SOURCE), "exec"), self.namespace)

    @staticmethod
    def tag_period(tag):
        try:
            parts = tag.split("-")
            dates = [date.fromisoformat(p).isoformat() for p in parts]
            return dates if len(dates) == 2 and dates[0] <= dates[1] else []
        except (ValueError, TypeError):
            return []

    def status(self, source="teams_graph", period=PERIOD, **fields):
        return self.state.write_status(self.root, source, *period, **{
            "status": "complete", "scope": "Graph requested chats only; no Teams channels", **fields})

    def run_js(self, payload, checks):
        node = shutil.which("node")
        self.assertIsNotNone(node, "Node.js is required for coverage renderer checks")
        program = self.prelude + self.renderer + "\nconst payload=" + json.dumps(payload) + ";\n" + checks
        result = subprocess.run([node, "-"], input=program, capture_output=True, text=True,
                                encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_current_foreign_and_missing_periods_are_not_conflated(self):
        self.status()
        self.status("outlook_com", ["2026-01-01", "2026-01-31"])
        rows = self.namespace["communication_coverage"](PERIOD)
        flags = {r["source"]: r["matches_period"] for r in rows}
        self.assertEqual(flags, {"teams_graph": True, "outlook_com": False})
        for period in (None, [], [PERIOD[0]], ["", ""]):
            self.assertFalse(any(r["matches_period"] for r in self.namespace["communication_coverage"](period)))
        # View annotations do not become stored proof for the next view.
        self.assertNotIn("matches_period", self.state.load_status(self.root, "teams_graph"))

    def test_independent_activity_query_keeps_coverage_for_its_own_period(self):
        self.status()
        payload = self.namespace["activity_payload"](*PERIOD)
        self.assertTrue(payload["communication_coverage"][0]["matches_period"])
        old = self.namespace["activity_payload"]("2026-01-01", "2026-01-31")
        self.assertFalse(old["communication_coverage"][0]["matches_period"])
        self.assertEqual(old["period"], ["2026-01-01", "2026-01-31"])
        self.assertEqual(self.namespace["activity_payload"]()["communication_coverage"], payload["communication_coverage"])
        self.run_js(old, r'''
renderActivity(payload,true);
assert.match(nodes.communicationcoverage.innerHTML,/Teams Graph/);
assert.match(nodes.communicationcoverage.innerHTML,/다른 기간 기록/);
assert(!nodes.communicationcoverage.innerHTML.includes('#16704a'));
assert.match(nodes.wnote.innerHTML,/수집·AI 분석은 실행하지 않았습니다/);
''')

    def test_missing_and_invalid_statuses_leave_an_explicit_unknown_state(self):
        directory = self.root / "data/collection_status"
        directory.mkdir(parents=True)
        (directory / "teams_graph.json").write_text("not JSON", encoding="utf-8")
        rows = self.namespace["communication_coverage"](PERIOD)
        self.assertEqual(rows, [])
        self.run_js(rows, r'''
renderCommunicationCoverage(payload);
assert.match(nodes.communicationcoverage.innerHTML,/범위 기록이 없습니다/);
assert.match(nodes.communicationcoverage.innerHTML,/CSV 건수만으로 전체 수집을 확인할 수 없습니다/);
''')

    def test_scope_completion_is_bounded_and_labels_all_route_outcomes(self):
        sources = ["outlook_com", "outlook_index", "outlook_web", "outlook_copilot", "teams_app", "teams_graph"]
        states = ["complete", "partial", "failed", "blocked", "skipped", "unknown"]
        for source, status in zip(sources, states, strict=True):
            self.status(source, status=status, reasons=["synthetic diagnostic"])
        rows = self.namespace["communication_coverage"](PERIOD)
        self.run_js(rows, r'''
renderCommunicationCoverage(payload);
const html=nodes.communicationcoverage.innerHTML;
for(const label of ['명시 범위 완료','부분 수집','실패','접근 불가','생략','미확인'])assert(html.includes(label));
assert.match(html,/조직 전체 메일·Teams 전체를 뜻하지 않습니다/);
assert.match(html,/첨부파일 내용은 수집하지 않습니다/);
assert.equal((html.match(/#16704a/g)||[]).length,1);
assert.match(html,/Graph requested chats only/);
''')

    def test_collector_text_cannot_inject_html_into_scope_table(self):
        self.status("teams_web", status="partial", scope='<img src=x onerror="FAIL">',
                    reasons=['<script>FAIL</script>'])
        rows = self.namespace["communication_coverage"](PERIOD)
        self.run_js(rows, r'''
renderCommunicationCoverage(payload);
const html=nodes.communicationcoverage.innerHTML;
assert(!html.includes('<img'));
assert(!html.includes('<script>'));
assert(html.includes('&lt;img'));
assert(html.includes('&lt;script&gt;'));
''')


if __name__ == "__main__":
    unittest.main()
