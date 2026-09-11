"""Execute the rendered workflow JavaScript with synthetic data only."""
import ast
from html.parser import HTMLParser
import json
from pathlib import Path
import shutil
import subprocess
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "LoadMonitor25/ui/app.py"


def page():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8-sig"))
    node = next(node for node in tree.body if isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == "PAGE" for target in node.targets))
    return ast.literal_eval(node.value)


class Details(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.nodes, self.stack = [], []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if tag == "details":
            node = dict(attrs)
            node["parent"] = self.stack[-1] if self.stack else None
            self.nodes.append(node)
            self.stack.append(node)

    def handle_endtag(self, tag):
        if tag == "details":
            self.stack.pop()


class WorkflowUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rendered = page()
        functions = rendered.split("const flowOpen = new Map();", 1)[1].split("async function loadFlow(){", 1)[0]
        fixture = {"tag": "20260801-20260831", "flows": [
            {"level1": "신제품개발", "project": "과제 <A>", "pjkey": "a", "detail": "설계", "role": "검토 책임",
             "mm": {"mm": 0.2}, "steps": [{"order": 1, "name": "검토", "desc": "설계 확인", "agent": "중", "evidence": "근거 A"}]},
            {"level1": "일반업무", "project": "운영", "detail": "정리", "role": "운영 책임", "steps": []},
            {"level1": "신제품개발", "project": "과제 A", "pjkey": "a", "detail": "평가", "role": "평가 책임", "steps": []},
            {"level1": "신제품개발", "project": "과제 B", "detail": "측정", "steps": []},
            {"model": "미분류 과제", "detail": "확인", "steps": []},
            {"model": "혼재 과제", "level1_mix": ["개발", "일반"], "detail": "협의", "steps": []},
        ], "thin": [{"project": "a", "detail": "얕은 기록", "signals": 1}]}
        program = '''const assert=require('node:assert/strict');
const flowOpen=new Map();
const PAL=['blue'],AGENT_C={'중':'orange'};
const esc=s=>String(s??'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/"/g,'&quot;');
const fold2=s=>String(s).toLowerCase();
const buttons={flowexpand:{},flowcollapse:{}};
const $=id=>buttons[id];
''' + functions + "\nconst d=" + json.dumps(fixture, ensure_ascii=False) + ''';
const html=flowGroups(d);
const key=JSON.stringify([d.tag,'level','신제품개발']);
const nodes=[{dataset:{flowKey:key},open:true},
 {dataset:{flowKey:JSON.stringify([d.tag,'project','신제품개발','a'])},open:true}];
bindFlowGroups({querySelectorAll:()=>nodes});
buttons.flowcollapse.onclick();
assert(nodes.every(n=>n.open===false));
assert(nodes.every(n=>flowOpen.get(n.dataset.flowKey)===false));
const collapsed=flowGroups(d);
buttons.flowexpand.onclick();
assert(nodes.every(n=>n.open===true));
nodes[0].open=false;nodes[0].ontoggle();
assert.equal(flowOpen.get(key),false);
process.stdout.write(JSON.stringify({html,collapsed}));
'''
        node = shutil.which("node")
        if not node:
            raise AssertionError("Node.js is required to verify workflow interaction")
        result = subprocess.run([node, "-e", program], capture_output=True, text=True, encoding="utf-8", timeout=20)
        if result.returncode:
            raise AssertionError(result.stderr)
        cls.result = json.loads(result.stdout)

    def test_parent_and_project_groups_contain_all_workflows(self):
        nodes = Details(self.result["html"]).nodes
        levels = [n for n in nodes if "flow-level" in n.get("class", "")]
        projects = [n for n in nodes if "flow-project" in n.get("class", "")]
        tasks = [n for n in nodes if "flow-task" in n.get("class", "")]
        self.assertEqual((len(levels), len(projects), len(tasks)), (4, 5, 6))
        self.assertTrue(all(n["parent"] in levels for n in projects))
        self.assertTrue(all(n["parent"] in projects for n in tasks))
        self.assertEqual(sum("open" in n for n in tasks), 1)

    def test_group_collapse_state_and_underlying_details_are_preserved(self):
        nodes = Details(self.result["collapsed"]).nodes
        target = next(n for n in nodes if json.loads(n.get("data-flow-key", "[]")) ==
                      ["20260801-20260831", "level", "신제품개발"])
        self.assertNotIn("open", target)
        for content in ("검토 책임", "근거 A", "설계 확인", "얕은 기록", "상위 혼재", "상위 미분류"):
            self.assertIn(content, self.result["html"])
        self.assertIn("과제 &lt;A>", self.result["html"])
        self.assertNotIn("과제 <A>", self.result["html"])

    def test_only_one_visible_move_preparation_entry(self):
        rendered = page()
        self.assertIn('id="prepmove"', rendered)
        self.assertNotIn('id="movezip"', rendered)
        self.assertNotIn('$("movezip")', rendered)
        self.assertIn('fetch("/api/prepmove"', rendered)
        self.assertIn("전용 창에서 정리와 ZIP 생성을 진행합니다", rendered)


if __name__ == "__main__":
    unittest.main()
