"""Visible OWA DOM contracts in Node/TEMP; no browser, profile or service access."""
import importlib.util
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1] / "LoadMonitor25"

# Minimal DOM implementation for executing the actual collector JavaScript.
# CSS matching uses the tree, rather than returning expected results per selector.
DOM = r'''
const pieces=s=>s.match(/(?:\[[^\]]+\]|[^\s])+/g)||[];
function simple(e,s){
 const tag=s.match(/^[a-zA-Z][\w-]*/);if(tag && e.tagName!==tag[0].toUpperCase())return false;
 const id=s.match(/#([\w-]+)/);if(id && e.id!==id[1])return false;
 for(const m of s.matchAll(/\[([\w-]+)(?:(\*=|=)"([^"]*)"\s*(i)?)?\]/g)){
  let v=e.getAttribute(m[1]),w=m[3];if(v===null)return false;
  if(m[4]){v=v.toLowerCase();w=w.toLowerCase();}
  if(m[2]==='=' && v!==w)return false;if(m[2]==='*=' && !v.includes(w))return false;
 }return true;
}
function matches(e,s){const p=pieces(s);let i=p.length-1;if(!simple(e,p[i]))return false;
 for(i--;i>=0;i--){e=e.parentElement;while(e&&!simple(e,p[i]))e=e.parentElement;if(!e)return false;}return true;}
class Element {
 constructor(d,parent=null){this.tagName=(d.tag||'div').toUpperCase();this.attrs=d.attrs||{};this.id=this.attrs.id||'';
  this.parentElement=parent;this.children=(d.children||[]).map(x=>new Element(x,this));this.own=d.text||'';
  this.width=d.hidden?0:600;this.height=d.hidden?0:40;this.clientHeight=d.clientHeight||100;
  this.scrollHeight=d.scrollHeight||100;this.scrollTop=0;this.overflow=d.overflow||'visible';this.value=d.value||'';}
 get textContent(){return this.own+this.children.map(x=>x.textContent).join(' ');}get innerText(){return this.textContent;}
 get childElementCount(){return this.children.length;}
 getAttribute(n){return Object.hasOwn(this.attrs,n)?String(this.attrs[n]):null;}
 getBoundingClientRect(){return {width:this.width,height:this.height};}
 contains(e){return e===this||this.children.some(c=>c.contains(e));}
 all(){return this.children.flatMap(c=>[c,...c.all()]);}
 querySelectorAll(s){return this.all().filter(e=>s.split(',').some(p=>matches(e,p.trim())));}
 querySelector(s){return this.querySelectorAll(s)[0]||null;}
 closest(s){for(let e=this;e;e=e.parentElement)if(s.split(',').some(p=>matches(e,p.trim())))return e;return null;}
 focus(){document.activeElement=this;}click(){this.attrs['aria-selected']='true';}dispatchEvent(){}select(){}
}
const document=new Element(FIXTURE),window={},location={href:'https://outlook.office.com/mail/search'};
const getComputedStyle=e=>({overflowY:e.overflow,visibility:'visible',display:'block'});
const Event=class{constructor(name,options){this.name=name;this.options=options;}};
'''


def node(tag="div", attrs=None, text="", children=None, **extra):
    return dict(tag=tag, attrs=attrs or {}, text=text, children=children or [], **extra)


class OutlookWebCompatibility(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temporary = tempfile.TemporaryDirectory(prefix='lm25-owa-dom-code-')
        cls.addClassCleanup(temporary.cleanup)
        root = Path(temporary.name)
        for folder, filename in [('collect', 'Get-OutlookWeb.py'), ('core', 'collection_state.py'),
                                 ('core', 'communication_archive.py'), ('core', 'communication_context.py')]:
            (root / folder).mkdir(exist_ok=True)
            shutil.copyfile(ROOT / folder / filename, root / folder / filename)
        spec = importlib.util.spec_from_file_location("owa_compat", root / "collect/Get-OutlookWeb.py")
        cls.mod = importlib.util.module_from_spec(spec)
        with patch.object(sys, "path", list(sys.path)):
            spec.loader.exec_module(cls.mod)

    def javascript(self, fixture, expressions):
        self.assertTrue(shutil.which("node"), "Node is required to exercise collector JS")
        source = "const FIXTURE=" + json.dumps(fixture, ensure_ascii=False) + ";\n" + DOM
        source += "\nconst out=[];\n"
        for expression in expressions:
            source += "out.push(eval(" + json.dumps(expression, ensure_ascii=False) + "));\n"
        source += "process.stdout.write(JSON.stringify(out));"
        result = subprocess.run(["node", "-"], input=source, text=True, encoding="utf-8", capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        return [json.loads(value) if isinstance(value, str) and value.startswith("{") else value
                for value in json.loads(result.stdout)]

    def row(self, identity="m1", **extra):
        return node(attrs={"role": "row", "data-itemid": identity, "aria-selected": "true"}, children=[
            node("span", {"data-testid": "sender"}, "Synthetic sender"),
            node("span", {"data-testid": "subject"}, "Synthetic subject"),
            node("time", {"datetime": "2026-09-03T10:00:00"}, "Sep 3"),
        ], **extra)

    def test_modern_grid_scrolls_mail_rows_instead_of_sidebar_listbox(self):
        fixture = node(children=[
            node(attrs={"role": "listbox"}, overflow="auto", scrollHeight=3000,
                 children=[node(attrs={"role": "option"}, text="Folder "+str(i)) for i in range(20)]),
            node(attrs={"role": "grid"}, overflow="auto", scrollHeight=900,
                 children=[self.row("m"+str(i)) for i in range(7)]),
        ])
        page, moved, top = self.javascript(fixture, [self.mod.JS_MAIL, self.mod.JS_SCROLL,
                                                   "document.querySelector('[role=\"grid\"]').scrollTop"])
        self.assertEqual(page["state"], "results")
        self.assertEqual(page["n"], 7)
        self.assertEqual(len([r for r in page["items"] if r["item_id"]]), 7)
        self.assertEqual((moved, top), ("scrolled", 100))
        parsed = self.mod.parse_mail_item(page["items"][-1], date(2026, 9, 1), date(2026, 9, 30), "unknown")
        self.assertEqual(parsed[1:4], ["2026-09-03 10:00", "Synthetic sender", "Synthetic subject"])

    def test_search_combobox_readback_uses_same_selector_and_hidden_rows_are_excluded(self):
        fixture = node(children=[node("input", {"role": "combobox", "aria-label": "검색"}, value="received:09/03/2026"),
                                 node(attrs={"role": "grid"}, children=[self.row(), self.row("hidden", hidden=True)])])
        focused, page = self.javascript(fixture, [self.mod.JS_FOCUS_SEARCH, self.mod.JS_MAIL])
        self.assertEqual(focused, "ok")
        self.assertEqual(page["query"], "received:09/03/2026")
        self.assertEqual([r["item_id"] for r in page["items"]], ["m1"])

    def test_semantic_document_body_requires_matching_message_not_whole_page(self):
        fixture = node(children=[node(attrs={"role": "grid"}, children=[self.row()]),
                                 node("article", {"data-itemid": "m1"}, children=[
                                     node("h2", {"role": "heading"}, "Synthetic subject"),
                                     node(attrs={"role": "document", "aria-label": "Message body"}, text="Original body"),
                                 ]),
                                 node("article", {"data-itemid": "other"}, children=[
                                     node("h2", {"role": "heading"}, "Synthetic subject"),
                                     node(attrs={"role": "document", "aria-label": "Message body"}, text="DO NOT READ THIS"),
                                 ])])
        expected = {"key": "item:m1", "item_id": "m1", "subject": "Synthetic subject", "limit": 4000}
        detail, = self.javascript(fixture, [self.mod.JS_MAIL_DETAIL % json.dumps(expected)])
        self.assertEqual(detail["body"], "Original body")
        self.assertEqual(detail["proof"], "message-id")

    def test_matching_header_without_message_identity_does_not_accept_stale_body(self):
        item = {"key": "visible:synthetic", "texts": ["Synthetic sender", "Synthetic subject"], "label": "2026-09-03 10:00"}
        row = self.mod.parse_mail_item(item, date(2026, 9, 1), date(2026, 9, 30), "unknown")
        detail = {"proof": "selected-header", "container": "message-body", "selected_key": item["key"],
                  "sender": row[2], "subject": row[3], "date_texts": ["2026-09-03T10:00:00"], "body": "Verified body"}
        self.assertEqual(self.mod.detail_context(item, row, detail, 4000)[0], "")
        for field, value in (("sender", "Different sender"), ("date_texts", ["2026-09-04 10:00"]),
                             ("date_texts", ["10:00"]), ("subject", "Other subject"), ("selected_key", "other")):
            with self.subTest(field=field, value=value):
                self.assertEqual(self.mod.detail_context(item, row, dict(detail, **{field: value}), 4000)[0], "")

    def test_preview_time_cannot_upgrade_date_only_header(self):
        row = self.mod.parse_mail_item({"label": "2026-09-03", "texts": ["Sender", "Subject", "Previously sent 23:59"]},
                                       date(2026, 9, 1), date(2026, 9, 30))
        self.assertEqual((row[1], row[6]), ("2026-09-03 12:00", "date"))

    def test_seven_visible_rows_then_virtual_page_retains_all_nine(self):
        def item(i):
            return {"key": "item:"+str(i), "item_id": str(i), "label": "2026-09-03 10:00",
                    "texts": ["Sender", "Subject "+str(i)]}
        class Browser:
            def __init__(self):
                self.cdp = self
                self.page = 0
                self.navigation = 0
            def goto(self, _):
                self.navigation += 1
                return "ok" if self.navigation == 1 else "login"
            def search(self, _):
                return True
            def eval_json(self, _):
                return {"state": "results", "items": [item(i) for i in (range(7) if self.page == 0 else range(6, 9))]}
            def eval(self, _):
                self.page += 1
                return "scrolled" if self.page == 1 else "end"
        retained = []
        with patch.object(self.mod.time, "sleep"):
            rows, state, _ = self.mod.collect_mail(Browser(), date(2026, 9, 1), date(2026, 9, 7), checkpoint=lambda r: retained.extend(r))
        self.assertEqual((len(rows), state), (9, "login"))
        self.assertEqual({row[9] for row in rows}, set(map(str, range(9))))

    def test_unsupported_surface_remains_pending_and_unattempted_ranges_get_next_turn(self):
        class Browser:
            last_diagnostic = "search_result_not_ready_or_stale"
            def __init__(self):
                self.queries = []
            def goto(self, _):
                return "ok"
            def search(self, query):
                self.queries.append(query)
                return False
        with tempfile.TemporaryDirectory(prefix="lm25-owa-compat-") as directory:
            path = str(Path(directory)/"progress.json")
            one, two = Browser(), Browser()
            self.mod.collect_mail(one, date(2026, 9, 1), date(2026, 9, 30), state_path=path)
            self.mod.collect_mail(two, date(2026, 9, 1), date(2026, 9, 30), state_path=path)
            self.assertEqual(len(one.queries), 3)
            self.assertTrue(set(two.queries).isdisjoint(one.queries))
            saved = json.loads(Path(path).read_text())
            self.assertFalse(any(unit["traversed"] for unit in saved["units"].values()))

    def test_readiness_is_bounded_and_login_is_not_empty_mail(self):
        clock = [0.0]
        browser = self.mod.Browser.__new__(self.mod.Browser)
        browser.deadline = 2.0
        browser.last_diagnostic = ""
        browser.cdp = SimpleNamespace(eval=lambda js, **kw: "https://outlook.office.com/mail/" if js == "location.href" else "{}")
        with patch.object(self.mod.time, "monotonic", side_effect=lambda: clock[0]), \
                patch.object(self.mod.time, "sleep", side_effect=lambda seconds: clock.__setitem__(0, clock[0]+seconds)):
            self.assertEqual(browser.wait_ready(), "timeout")
        self.assertLessEqual(clock[0], 2.001)
        self.assertTrue(self.mod.is_login_url("https://login.microsoftonline.com/tenant"))
        self.assertFalse(self.mod.is_login_url("https://login.microsoftonline.com.attacker.invalid/"))

    def test_search_distinguishes_transition_visible_observations_and_failed_input(self):
        for changed in (False, True, None):
            with self.subTest(changed=changed):
                clock = [0.0]
                state = {"query": "old-query", "entered": False}
                def evaluate(script, **kwargs):
                    if script == self.mod.JS_FOCUS_SEARCH:
                        return "ok"
                    if script == self.mod.JS_CLEAR_SEARCH:
                        return "cleared"
                    return json.dumps({"href": "https://outlook.office.com/mail/search", "state": "results", "searching": True,
                                       "query": state["query"], "items": [{"key": "new" if changed and state["entered"] else "old"}]})
                def call(method, params=None, **kwargs):
                    if method == "Input.insertText" and changed is not None:
                        state.update(query=params["text"], entered=True)
                browser = self.mod.Browser.__new__(self.mod.Browser)
                browser.deadline = 20
                browser.last_diagnostic = ""
                browser.cdp = SimpleNamespace(eval=evaluate, call=call)
                with patch.object(self.mod.time, "monotonic", side_effect=lambda: clock[0]), \
                        patch.object(self.mod.time, "sleep", side_effect=lambda seconds: clock.__setitem__(0, clock[0]+seconds)):
                    result = browser.search("received:09/03/2026")
                self.assertEqual(result, "query_entered_unverified" if changed else "visible_unverified" if changed is False else False)
                self.assertLessEqual(clock[0], 12.21)
                if changed:
                    self.assertLess(clock[0], 1)

    def test_existing_csv_does_not_skip_requested_period_and_status_has_counts(self):
        with tempfile.TemporaryDirectory(prefix="lm25-owa-existing-") as directory:
            root = Path(directory)
            out = root / "data/outlook"
            out.mkdir(parents=True)
            (out / "mail.csv").write_text("box,time,sender,subject,conversation,rcv\ninbox,2025-01-01 10:00,S,Old,Old,to\n", encoding="utf-8")
            fixture = root / "fixture.json"
            fixture.write_text(json.dumps({"mail": {"2026-09": [{"key": "new", "item_id": "new", "label": "2026-09-03 10:00", "texts": ["Sender", "Current"]},
                                                                      {"key": "undated", "texts": ["Sender", "No date"]}]}}), encoding="utf-8")
            with patch.object(self.mod, "ROOT", str(root)), patch.object(self.mod, "OUT_DIR", str(out)), \
                    patch.object(sys, "argv", ["collector", "--from", "2026-09-01", "--to", "2026-09-30", "--only", "mail", "--time-budget", "4"]), \
                    patch.dict(os.environ, {"LM_OWA_FAKE": str(fixture)}), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(self.mod.main(), 0)
            text = (out / "mail.csv").read_text(encoding="utf-8-sig")
            self.assertIn("Current", text)
            self.assertIn("Old", text)
            status = json.loads((root / "data/collection_status/outlook_web.json").read_text())
            self.assertEqual((status["status"], status["time_budget_sec"]), ("partial", 4))
            self.assertEqual((status["diagnostics"]["mail"]["parsed"], status["diagnostics"]["mail"]["undated"]), (1, 1))

    def test_legacy_attribute_rows_and_parseable_date_only_options_are_not_lost(self):
        fixtures = [
            node(children=[node(attrs={"data-item-id": "legacy", "aria-label": "2026-09-03 10:00"},
                                children=[node("span", text="Sender"), node("span", text="Subject")])]),
            node(attrs={"role": "listbox"}, children=[node(attrs={"role": "option", "aria-label": "Sep 3, 2026"},
                                children=[node("span", text="Sender"), node("span", text="Subject")])]),
            node(attrs={"role": "listbox"}, children=[node(attrs={"role": "option", "aria-label": "03.09.2026"},
                                children=[node("span", text="Sender"), node("span", text="Subject")])]),
        ]
        for fixture in fixtures:
            with self.subTest(fixture=fixture):
                page, = self.javascript(fixture, [self.mod.JS_MAIL])
                self.assertEqual(page["n"], 1)
                row = self.mod.parse_mail_item(page["items"][0], date(2026, 9, 1), date(2026, 9, 30), "unknown")
                self.assertEqual(row[1][:10], "2026-09-03")

    def test_real_browser_main_flow_survives_transient_sso_and_saves_observations(self):
        """Exercise actual Browser/main/collect/save, faking only CDP transport."""
        module = self.mod
        page, = self.javascript(node(children=[node("input", {"id": "topSearchInput"}),
            node(attrs={"data-item-id": "legacy", "aria-label": "2026-09-03 10:00"},
                 children=[node("span", text="Sender"), node("span", text="Subject")])]), [module.JS_MAIL])
        clock = [0.0]
        calls = []
        class Connection:
            def __init__(self, ws_url, timeout):
                self.url = module.MAIL_URL
                self.query = ""
                self.navigations = 0
                self.login_until = 0
            def charge(self, kind, timeout):
                calls.append((kind, timeout))
                if timeout < 0.01:
                    raise TimeoutError("synthetic elapsed command")
                clock[0] += 0.01
            def current_url(self):
                return "https://login.microsoftonline.com/tenant/oauth2/authorize" if clock[0] < self.login_until else self.url
            def call(self, method, params=None, timeout=25):
                self.charge(method, timeout)
                if method == "Page.navigate":
                    self.navigations += 1
                    self.url, self.query = params["url"], ""
                    if self.navigations == 1:
                        self.login_until = clock[0]+0.7
                elif method == "Input.insertText":
                    self.query = params["text"]
                elif method == "Input.dispatchKeyEvent":
                    self.url = module.MAIL_URL+"search"
                return {}
            def eval(self, script, timeout=25):
                self.charge("eval", timeout)
                if script == "location.href":
                    return self.current_url()
                if script == module.JS_MAIL:
                    return json.dumps(dict(page, href=self.current_url(), query=self.query, searching="/search" in self.url))
                if script == module.JS_FOCUS_SEARCH:
                    return "ok"
                if script == module.JS_CLEAR_SEARCH:
                    return "cleared"
                if script == module.JS_SCROLL:
                    return "end"
                raise AssertionError("Unexpected CDP expression")
            def close(self):
                pass
        class Bootstrap(module.Browser):
            def __init__(self):
                self.cfg = {"port": 9999, "url": module.MAIL_URL}
                self.port, self.deadline, self.cdp = 9999, None, None
                self.last_diagnostic = ""
                self.ca = SimpleNamespace(ensure_edge=lambda cfg: True, CDP=Connection,
                    http_json=lambda *a, **kw: [{"type": "page", "url": module.MAIL_URL, "webSocketDebuggerUrl": "ws://fixture/"}])
        with tempfile.TemporaryDirectory(prefix="lm25-owa-main-cdp-") as directory:
            root = Path(directory)
            with patch.object(module, "ROOT", str(root)), patch.object(module, "OUT_DIR", str(root/"data/outlook")), \
                    patch.object(module, "Browser", Bootstrap), patch.dict(os.environ, {"LM_OWA_FAKE": "", "LM_NO_BROWSER": ""}), \
                    patch.object(sys, "argv", ["collector", "--from", "2026-09-01", "--to", "2026-09-07", "--only", "mail", "--exclude-body", "--time-budget", "20"]), \
                    patch.object(module.time, "monotonic", side_effect=lambda: clock[0]), \
                    patch.object(module.time, "sleep", side_effect=lambda seconds: clock.__setitem__(0, clock[0]+seconds)), \
                    contextlib.redirect_stdout(io.StringIO()):
                result = module.main()
            self.assertEqual(result, 0)
            self.assertIn("Subject", (root/"data/outlook/mail.csv").read_text(encoding="utf-8-sig"))
            status = json.loads((root/"data/collection_status/outlook_web.json").read_text())
            self.assertEqual((status["mail_rows"], status["mail_status"]), (1, "partial"))
        self.assertGreaterEqual(clock[0], 0.7)
        self.assertLess(clock[0], 20)
        self.assertTrue(all(0 < timeout <= 20 for _, timeout in calls))

    def test_persistent_login_wait_is_shorter_after_ready_and_respects_route_budget(self):
        for ready, budget, expected_limit in ((False, 30, 8.3), (True, 30, 2.3), (False, 0.5, 0.501)):
            with self.subTest(ready=ready, budget=budget):
                clock = [0.0]
                browser = self.mod.Browser.__new__(self.mod.Browser)
                browser.deadline = budget
                browser._ready_once = ready
                browser.last_diagnostic = ""
                browser.cdp = SimpleNamespace(eval=lambda *a, **kw: "https://login.microsoftonline.com/tenant/")
                with patch.object(self.mod.time, "monotonic", side_effect=lambda: clock[0]), \
                        patch.object(self.mod.time, "sleep", side_effect=lambda seconds: clock.__setitem__(0, clock[0]+seconds)), \
                        contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(browser.wait_ready(), "login")
                self.assertEqual(browser.last_diagnostic, "login_required")
                self.assertGreater(clock[0], 0)
                self.assertLessEqual(clock[0], expected_limit)

    def test_unchanged_visible_list_retains_only_explicit_period_dates_without_completing_search(self):
        module = self.mod
        class Browser:
            def __init__(self):
                self.query = ""
                self.nav = 0
            def goto(self, _):
                self.nav += 1
                return "ok" if self.nav == 1 else "login"
            def search(self, query):
                self.query = query
                return "visible_unverified"
            def eval_json(self, _):
                return {"state": "results", "query": self.query, "items": [
                    {"key": "within", "item_id": "within", "label": "2026-09-03 10:00", "subject": "Sent Items", "texts": ["Sender", "Sent Items"]},
                    {"key": "header", "item_id": "header", "date_texts": ["2026-09-03T10:00:00"],
                     "label": "Synthetic sender, Project Alpha, Sep 3 10:00", "texts": []},
                    {"key": "outside", "item_id": "outside", "label": "2025-09-03 10:00", "texts": ["Sender", "Outside"]},
                    {"key": "inferred", "item_id": "inferred", "label": "Sep 3 10:00", "texts": ["Sender", "Do not infer year"]},
                    {"key": "ambiguous", "item_id": "ambiguous", "label": "03/09/2026 10:00", "texts": ["Sender", "Do not infer date order"]},
                ]}
        with tempfile.TemporaryDirectory(prefix="lm25-owa-visible-only-") as directory:
            checkpoint = Path(directory)/"jobs.json"
            stored = []
            rows, state, diag = module.collect_mail(Browser(), date(2026, 9, 1), date(2026, 9, 7),
                                                    checkpoint=lambda values: stored.extend(values), state_path=str(checkpoint))
            self.assertEqual((len(rows), state, rows[0][0], rows[0][3], rows[0][5]), (2, "login", "unknown", "Sent Items", ""))
            self.assertEqual(rows[1][2:4], ["Synthetic sender", "Project Alpha"])
            self.assertEqual((rows[1][0], rows[1][5]), ("unknown", ""))
            self.assertEqual((diag["search"], diag["completed_units"], diag["visible_unverified"]), (0, 0, 1))
            self.assertEqual((diag["undated"], diag["period_filtered"]), (2, 1))
            unit = json.loads(checkpoint.read_text())["units"]["inbox:2026-09-01:2026-09-07"]
            self.assertFalse(unit["traversed"])
            self.assertEqual(unit["seen_hashes"], [])
            self.assertTrue(stored)
        for month in (3, 9):
            self.assertIsNone(module.parse_mail_item({"label": "03/09/2026 10:00", "texts": ["Sender", "Subject"]},
                                                     date(2026, month, 1), date(2026, month, 28), "unknown", explicit_dates=True))

    def test_slow_cdp_poll_does_not_shrink_last_call_below_normal_response_latency(self):
        clock = [0.0]
        entered = [False]
        browser = self.mod.Browser.__new__(self.mod.Browser)
        browser.deadline = 30
        browser.last_diagnostic = ""
        def evaluate(script, timeout=25):
            if timeout < 0.37:
                clock[0] += timeout
                raise TimeoutError("normal synthetic CDP latency exceeds tiny poll timeout")
            clock[0] += 0.37
            if script == self.mod.JS_FOCUS_SEARCH:
                return "ok"
            if script == self.mod.JS_CLEAR_SEARCH:
                return "cleared"
            return json.dumps({"href": "https://outlook.office.com/mail/search", "state": "results", "searching": True,
                               "query": "received:09/03/2026" if entered[0] else "old", "items": [{"key": "same"}]})
        def call(method, params=None, timeout=25):
            if method == "Input.insertText":
                entered[0] = True
        browser.cdp = SimpleNamespace(eval=evaluate, call=call)
        with patch.object(self.mod.time, "monotonic", side_effect=lambda: clock[0]), \
                patch.object(self.mod.time, "sleep", side_effect=lambda seconds: clock.__setitem__(0, clock[0]+seconds)):
            self.assertEqual(browser.search("received:09/03/2026"), "visible_unverified")
            browser.wait_list_change(("same",), limit=1.5)
        self.assertLess(clock[0], 30)


if __name__ == "__main__":
    unittest.main()
