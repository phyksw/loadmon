/*
 * WP-36 시험 — web\app(index.html · app.js · report.js): 로컬 앱 화면 6개와 개인 보고서 화면(로컬 앱·자기완결 HTML 같은 파일).
 * 명세 시험: RPT-03(결과 선택) · RPT-04(기간 출처) · RPT-05(판 다름 → 다시 만들기 1회) · RPT-13(근무 중 미분류 행) · RPT-21(무늬)
 *            · RPT-30(악성 문자열) · RPT-33·RPT-40(금지 표현·성공 경로 문구) · KB-2(트리 키보드) · KB-9(응답 폼 오류 초점)
 *            · G-R3~G-R7 · G-R11 · L-19 · L-25 · L-27 · R §11(저장소 막힘·카드별 실패) · §2.3.3(쓰기 토큰·JSON).
 * 가짜 문서·가짜 서버·가짜 시계만 쓴다(브라우저·외부 패키지·네트워크 없음). 자료는 tests\fixtures\wp36\(합성)만. 트리는 읽기만 한다.
 * run_node_tests.js 는 시험 함수를 동기로 부르므로, 비동기 화면 시나리오는 이 파일을 자식 node 로 한 번 돌려(인자 없이 직접 실행)
 * 결과를 받아 시나리오마다 시험 하나로 보고한다.
 */
"use strict";
var fs = require("fs");
var os = require("os");
var path = require("path");
var cp = require("child_process");
var assert = require("assert");

var ROOT = path.resolve(__dirname, "..", "..");
var FIX = path.join(ROOT, "tests", "fixtures", "wp36");
var APP_FILES = ["web/app/index.html", "web/app/app.js", "web/app/report.js"];
var JS_FILES = ["web/app/app.js", "web/app/report.js"];

function readText(rel) { return fs.readFileSync(path.join(ROOT, rel), "utf8"); }
function fixture(name) { return JSON.parse(fs.readFileSync(path.join(FIX, name), "utf8")); }
function clone(x) { return JSON.parse(JSON.stringify(x)); }

function mods() {
  return {U: require(path.join(ROOT, "web", "common", "lm27ui.js")), C: require(path.join(ROOT, "web", "common", "lm27charts.js")),
    R: require(path.join(ROOT, "web", "app", "report.js")), A: require(path.join(ROOT, "web", "app", "app.js"))};
}

// ───────────── 작은 가짜 문서·창 ─────────────
var XHTML = "http://www.w3.org/1999/xhtml";

function Node(doc, type, tag, ns) {
  this.ownerDocument = doc;
  this.nodeType = type;
  this.tagName = tag;
  this.namespaceURI = ns || null;
  this.childNodes = [];
  this.parentNode = null;
  this.attrs = {};
  this.data = "";
  this.listeners = {};
  this.style = {};
  this.offsetWidth = 100;
  this.offsetHeight = 30;
}
Node.prototype = {
  get firstChild() { return this.childNodes[0] || null; },
  get isConnected() { var n = this; while (n.parentNode) { n = n.parentNode; } return n === this.ownerDocument.documentElement; },
  get textContent() {
    if (this.nodeType === 3) { return this.data; }
    return this.childNodes.map(function (c) { return c.textContent; }).join("");
  },
  set textContent(v) { this.childNodes = []; this.appendChild(this.ownerDocument.createTextNode(v)); },
  get value() {
    if (this._value !== undefined) { return this._value; }
    if (this.tagName === "textarea") { return this.textContent; }
    if (this.tagName === "select") {
      var opts = this.all().filter(function (n) { return n.tagName === "option"; });
      var s = opts.filter(function (o) { return o.hasAttribute("selected"); })[0] || opts[0];
      return s ? (s.getAttribute("value") !== null ? s.getAttribute("value") : s.textContent) : "";
    }
    return this.getAttribute("value") || "";
  },
  set value(v) { this._value = String(v); },
  get checked() { return this._checked !== undefined ? this._checked : this.hasAttribute("checked"); },
  set checked(v) { this._checked = !!v; },
  appendChild: function (c) { if (c.parentNode) { c.parentNode.removeChild(c); } c.parentNode = this; this.childNodes.push(c); return c; },
  removeChild: function (c) { var i = this.childNodes.indexOf(c); if (i >= 0) { this.childNodes.splice(i, 1); c.parentNode = null; } return c; },
  setAttribute: function (k, v) { this.attrs[k] = String(v); },
  getAttribute: function (k) { return Object.prototype.hasOwnProperty.call(this.attrs, k) ? this.attrs[k] : null; },
  hasAttribute: function (k) { return Object.prototype.hasOwnProperty.call(this.attrs, k); },
  removeAttribute: function (k) { delete this.attrs[k]; },
  contains: function (n) { while (n) { if (n === this) { return true; } n = n.parentNode; } return false; },
  addEventListener: function (ev, fn) { (this.listeners[ev] = this.listeners[ev] || []).push(fn); },
  removeEventListener: function (ev, fn) { var l = this.listeners[ev] || []; var i = l.indexOf(fn); if (i >= 0) { l.splice(i, 1); } },
  focus: function () { this.ownerDocument.activeElement = this; },
  getBoundingClientRect: function () { return {left: 10, top: 100, right: 60, bottom: 120, width: 50, height: 20}; },
  all: function (out) {
    out = out || [];
    this.childNodes.forEach(function (c) { if (c.nodeType === 1) { out.push(c); c.all(out); } });
    return out;
  },
  querySelectorAll: function (sel) {
    var m = /^\[([a-z0-9-]+)\]$/.exec(sel);
    var m2 = /^([a-z]+)\.([a-z0-9-]+)$/.exec(sel);
    return this.all().filter(function (n) {
      if (m) { return n.hasAttribute(m[1]); }
      if (m2) { return n.tagName === m2[1] && (n.getAttribute("class") || "").split(" ").indexOf(m2[2]) >= 0; }
      return false;
    });
  },
  querySelector: function (sel) {
    var m = /^([a-z]+)\[([a-z-]+)="([^"]*)"\]$/.exec(sel);
    if (!m) { return null; }
    return this.all().filter(function (n) { return n.tagName === m[1] && n.getAttribute(m[2]) === m[3]; })[0] || null;
  }
};

function Doc() {
  this.nodeType = 9;
  this.readyState = "complete";
  this.documentElement = new Node(this, 1, "html", XHTML);
  this.documentElement.clientWidth = 1280;
  this.head = new Node(this, 1, "head", XHTML);
  this.body = new Node(this, 1, "body", XHTML);
  this.documentElement.appendChild(this.head);
  this.documentElement.appendChild(this.body);
  this.activeElement = this.body;
  this.defaultView = null;
}
Doc.prototype = {
  createElement: function (tag) { return new Node(this, 1, String(tag).toLowerCase(), XHTML); },
  createElementNS: function (ns, tag) { return new Node(this, 1, tag, ns); },
  createTextNode: function (s) { var n = new Node(this, 3, "#text"); n.data = String(s); return n; },
  getElementById: function (id) {
    var a = this.documentElement.all();
    for (var i = 0; i < a.length; i++) { if (a[i].getAttribute("id") === id) { return a[i]; } }
    return null;
  },
  querySelector: function (sel) { return this.documentElement.querySelector(sel); },
  addEventListener: function () {}
};

function memStorage() {
  var d = {};
  return {getItem: function (k) { return Object.prototype.hasOwnProperty.call(d, k) ? d[k] : null; }, setItem: function (k, v) { d[k] = String(v); }, _d: d};
}

function brokenStorage() {
  return {getItem: function () { throw new Error("막힘"); }, setItem: function () { throw new Error("막힘"); }};
}

function Win(doc) {
  var self = this;
  var hash = "";
  this.document = doc;
  doc.defaultView = this;
  this.listeners = {};
  this.location = {};
  Object.defineProperty(this.location, "hash", {get: function () { return hash; }, set: function (v) {
    v = String(v);
    if (v && v.charAt(0) !== "#") { v = "#" + v; }
    if (v === hash) { return; }
    hash = v;
    (self.listeners.hashchange || []).slice().forEach(function (fn) { fn({type: "hashchange"}); });
  }});
  this.localStorage = memStorage();
  this.clip = null;
  this.navigator = {clipboard: {writeText: function (t) { self.clip = t; return Promise.resolve(); }}};
  this.opened = [];
  this.open = function (u) { self.opened.push(u); };
  this.pageXOffset = 0;
  this.pageYOffset = 0;
}
Win.prototype = {
  addEventListener: function (ev, fn) { (this.listeners[ev] = this.listeners[ev] || []).push(fn); },
  removeEventListener: function (ev, fn) { var l = this.listeners[ev] || []; var i = l.indexOf(fn); if (i >= 0) { l.splice(i, 1); } }
};

function el(doc, tag, attrs, parent) {
  var n = doc.createElement(tag);
  Object.keys(attrs || {}).forEach(function (k) { n.setAttribute(k, attrs[k]); });
  if (parent) { parent.appendChild(n); }
  return n;
}

function fire(target, type, extra) {
  var ev = {type: type, target: target, defaultPrevented: false, preventDefault: function () { this.defaultPrevented = true; }};
  Object.keys(extra || {}).forEach(function (k) { ev[k] = extra[k]; });
  for (var n = target; n; n = n.parentNode) { (n.listeners[type] || []).slice().forEach(function (fn) { fn(ev); }); }
  return ev;
}

function byAct(root, act, ref) {
  return root.all().filter(function (n) { return n.getAttribute("data-act") === act && (ref === undefined || n.getAttribute("data-ref") === String(ref)); });
}

function byTag(root, tag) { return root.all().filter(function (n) { return n.tagName === tag; }); }

function settle(n) {
  var p = Promise.resolve();
  for (var i = 0; i < (n || 40); i++) { p = p.then(function () { return new Promise(function (r) { setImmediate(r); }); }); }
  return p;
}

// 자기완결 HTML 의 데이터 섬 이스케이프(R §9.4) — 내보내기(WP-31)와 같은 규칙
function island(obj) {
  return JSON.stringify(obj).replace(/</g, "\\u003c").replace(/>/g, "\\u003e").replace(/&/g, "\\u0026")
    .replace(/\u2028/g, "\\u2028").replace(/\u2029/g, "\\u2029");
}

function fileDoc(model, drill, variant) {
  var doc = new Doc();
  doc.body.setAttribute("data-variant", variant || "full");
  el(doc, "header", {}, doc.body);
  el(doc, "main", {id: "app", tabindex: "-1"}, doc.body);
  var s = el(doc, "script", {type: "application/json", id: "lm27-data"}, doc.body);
  s.textContent = island(model);
  if (drill) {
    var s2 = el(doc, "script", {type: "application/json", id: "lm27-drill"}, doc.body);
    s2.textContent = island(drill);
  }
  var win = new Win(doc);
  return {doc: doc, win: win, main: doc.getElementById("app")};
}

// index.html 과 같은 틀(LM24 — 머리·단계 줄·기간 카드·보기 탭·띠·알림·본문·아래 상태 줄). frame=false 면 옛 틀(머리·탭·본문만)
function appDoc(token, frame) {
  var doc = new Doc();
  el(doc, "meta", {name: "lm27-ui-token", content: token}, doc.head);
  var head = el(doc, "header", {"class": "app-head", id: "lm27-head"}, doc.body);
  var h1 = el(doc, "h1", {}, head);
  h1.appendChild(doc.createTextNode("LoadMonitor27"));
  if (frame !== false) { el(doc, "small", {id: "lm27-ver"}, h1).textContent = "로컬 전용 · 외부 전송 없음"; }
  el(doc, "span", {id: "lm27-pc"}, head);
  el(doc, "button", {type: "button", id: "lm27-jobs", "data-act": "a-jobs", hidden: ""}, head);
  if (frame !== false) {
    el(doc, "nav", {"class": "steps", id: "lm27-steps"}, doc.body);
    el(doc, "section", {"class": "card period-card", id: "lm27-period"}, doc.body);
  }
  el(doc, "div", {id: "lm27-nav"}, doc.body);
  el(doc, "div", {id: "lm27-band", hidden: ""}, doc.body);
  el(doc, "div", {id: "lm27-alerts"}, doc.body);
  el(doc, "main", {id: "app", tabindex: "-1"}, doc.body);
  if (frame !== false) { el(doc, "footer", {"class": "sbar", id: "lm27-sbar"}, doc.body); }
  return {doc: doc, win: new Win(doc)};
}

function Timers() { this.q = []; this.n = 0; }
Timers.prototype = {
  set: function (fn, ms) { this.n++; this.q.push({id: this.n, fn: fn, ms: ms}); return this.n; },
  clear: function (id) { this.q = this.q.filter(function (t) { return t.id !== id; }); },
  run: function () { var q = this.q; this.q = []; q.forEach(function (t) { t.fn(); }); return q.length; }
};

// 가짜 화면 서버: routes['메서드 경로'] = 응답 본문 | {status, body} | function(call) → 그중 하나
function Server(routes) {
  var self = this;
  this.calls = [];
  this.routes = routes;
  this.fetch = function (p, init) {
    init = init || {};
    var method = init.method || "GET";
    var call = {method: method, path: p, headers: init.headers || {}, body: init.body ? JSON.parse(init.body) : null};
    self.calls.push(call);
    var key = method + " " + p.split("?")[0];
    var r = self.routes[key];
    if (typeof r === "function") { r = r(call); }
    if (r === undefined) { r = {status: 404, body: {ok: false, code: "not_found", error: "없는 경로"}}; }
    var res = r && typeof r === "object" && Object.prototype.hasOwnProperty.call(r, "status") && Object.prototype.hasOwnProperty.call(r, "body") ? r : {status: 200, body: r};
    return Promise.resolve({ok: res.status >= 200 && res.status < 300, status: res.status,
      text: function () { return Promise.resolve(res.body === null ? "" : JSON.stringify(res.body)); }});
  };
  this.count = function (method, p) { return self.calls.filter(function (c) { return c.method === method && c.path.split("?")[0] === p; }).length; };
  this.last = function (method, p) { var l = self.calls.filter(function (c) { return c.method === method && c.path.split("?")[0] === p; }); return l[l.length - 1] || null; };
}

var TOKEN = "0123456789abcdef0123456789abcdef";

function baseRoutes(model) {
  var api = fixture("api_responses.json");
  var r = {};
  Object.keys(api).forEach(function (k) { if (k.charAt(0) !== "_") { r[k] = clone(api[k]); } });
  r["GET /api/report"] = clone(model);
  return r;
}

function bootApp(routes, hash, opt) {
  opt = opt || {};
  var M = mods();
  var d = appDoc(opt.token === undefined ? TOKEN : opt.token, opt.frame);
  d.win.location.hash = hash || "#home";
  var srv = new Server(routes);
  var timers = new Timers();
  var at = opt.now || new Date(2026, 9, 5, 10, 0, 0);
  var app = M.A.boot({doc: d.doc, win: d.win, fetch: srv.fetch, timer: timers, storage: opt.storage || memStorage(),
    now: function () { return at; }});
  return {doc: d.doc, win: d.win, srv: srv, timers: timers, app: app, main: d.doc.getElementById("app"), M: M,
    period: d.doc.getElementById("lm27-period"), sbar: d.doc.getElementById("lm27-sbar"), steps: d.doc.getElementById("lm27-steps")};
}

function pressedChips(root) {
  return byAct(root, "a-period").filter(function (b) { return b.getAttribute("aria-pressed") === "true"; }).map(function (b) { return b.getAttribute("data-ref"); });
}

function dates(c) { return [c.doc.getElementById("an-from").value, c.doc.getElementById("an-to").value]; }

function go(ctx, hash) { ctx.win.location.hash = hash; return settle(); }
function text(n) { return n.textContent; }

// ───────────── 비동기 시나리오(자식 node 에서 돈다) ─────────────
var SCEN = [];
function scenario(name, fn) { SCEN.push({name: name, fn: fn}); }

scenario("자기완결 HTML — 섬에서 부트·11개 절 이동·드릴다운 섬 있음/없음", function () {
  var M = mods();
  var model = fixture("report_model.json");
  var drill = fixture("report_drill.json");
  var f = fileDoc(model, drill);
  var ctl = M.R.boot(f.doc, {win: f.win, storage: memStorage()});
  assert.ok(ctl, "부트");
  var t = text(f.main);
  assert.ok(t.indexOf("전체판(로컬 전용)") >= 0, "변형 배지");
  assert.ok(t.indexOf("기간 출처: 기본값(최근 3개월)") >= 0, "RPT-04 머리 띠");
  assert.ok(t.indexOf("내 PC 밖으로 보내지 마세요") >= 0, "전체판 안내");
  ["0.99 MM", "107%", "10.0h", "5%", "주의", "완료 3 · 진행 2"].forEach(function (s) { assert.ok(t.indexOf(s) >= 0, "KPI " + s); });
  var navs = byTag(f.main, "nav");
  assert.ok(navs.some(function (n) { return n.getAttribute("aria-label") === "보고서 절" && byTag(n, "a").length === 11; }), "절 메뉴 11");
  var months = navs.filter(function (n) { return n.getAttribute("aria-label") === "달 선택"; })[0];
  var cur = byTag(months, "a").filter(function (a) { return a.getAttribute("aria-current") === "page"; });
  assert.deepStrictEqual(cur.map(text), ["2026-09"], "기본 달 = 기준 시각의 달");
  var marks = {tree: "근무 중 미분류", workflow: "역할 업무", review: "끝낸 일", peers: "같이 일한 동료", graph: "연관 업무 추천",
    agentic: "매칭 격자", subagent: "판정 기준", queue: "로컬 앱에서만", hier: "분류 요약", evidence: "일별 근무", summary: "주요 단위업무"};
  Object.keys(marks).forEach(function (s) {
    f.win.location.hash = "#report/" + s;
    assert.ok(text(f.main).indexOf(marks[s]) >= 0, s + " 절");
  });
  ["r-fix", "r-export", "r-qsend", "r-need", "r-merge"].forEach(function (a) { assert.strictEqual(byAct(f.main, a).length, 0, "파일 모드 쓰기 버튼 0: " + a); });
  f.win.location.hash = "#report/evidence/2026-09-22";
  return settle().then(function () {
    var t2 = text(f.main);
    assert.ok(t2.indexOf("날짜 원장 2026-09-22") >= 0 && t2.indexOf("샘플러 9.3") >= 0 && t2.indexOf("구간 원장") >= 0, "날짜 드릴다운");
    f.win.location.hash = "#report/evidence/u_a1a1a1a1a1";
    return settle();
  }).then(function () {
    var t3 = text(f.main);
    assert.ok(t3.indexOf("의뢰 메일로 시작해") >= 0 && t3.indexOf("증거 줄") >= 0 && t3.indexOf("김철수") >= 0, "업무 원장");
    var g = fileDoc(model, null);
    M.R.boot(g.doc, {win: g.win, storage: null});
    g.win.location.hash = "#report/evidence/2026-09-22";
    return settle().then(function () { assert.ok(text(g.main).indexOf("이 파일에는 근거 상세가 없습니다 — 로컬 앱에서 보세요") >= 0, "섬 없음 안내"); });
  });
});

scenario("가림판 — 배지·근거 줄 없음·로컬 전용 안내 없음", function () {
  var M = mods();
  var model = fixture("report_model.json");
  model.variant = "redacted";
  var f = fileDoc(model, fixture("report_drill.json"), "redacted");
  M.R.boot(f.doc, {win: f.win, storage: null});
  assert.ok(text(f.main).indexOf("가림판") >= 0);
  assert.ok(text(f.main).indexOf("내 PC 밖으로 보내지 마세요") < 0);
  f.win.location.hash = "#report/evidence/u_a1a1a1a1a1";
  return settle().then(function () {
    var t = text(f.main);
    assert.ok(t.indexOf("가림판에는 근거 줄이 없습니다") >= 0, "근거 줄 없음");
    assert.ok(t.indexOf("[과제:P-0007] 전원부 검증 요청") < 0, "증거 제목 0");
  });
});

scenario("저장소 막힘(R §11) — 기본 달로 동작, 정상 저장소는 달 선택을 기억", function () {
  var M = mods();
  var model = fixture("report_model.json");
  var f = fileDoc(model, null);
  M.R.boot(f.doc, {win: f.win, storage: brokenStorage()});
  var pill = byAct(f.main, "r-month", "2026-08")[0];
  fire(pill, "click");
  var cur = byAct(f.main, "r-month").filter(function (a) { return a.getAttribute("aria-current") === "page"; });
  assert.deepStrictEqual(cur.map(function (a) { return a.getAttribute("data-ref"); }), ["2026-08"]);
  assert.ok(text(f.main).indexOf("2026-08 MM") >= 0);
  var mem = memStorage();
  var g = fileDoc(model, null);
  M.R.boot(g.doc, {win: g.win, storage: mem});
  fire(byAct(g.main, "r-month", "all")[0], "click");
  assert.strictEqual(mem._d["lm27.report.month"], "all");
  var h2 = fileDoc(model, null);
  M.R.boot(h2.doc, {win: h2.win, storage: mem});
  assert.ok(text(h2.main).indexOf("기간 MM") >= 0, "다시 열면 기억한 달");
  return Promise.resolve();
});

scenario("RPT-30 악성 문자열 — 섬에 원문자 '<' 0, 렌더는 글자로만(요소·on* 속성 0)", function () {
  var M = mods();
  var model = fixture("report_model.json");
  var bad = "</" + "script><img src=x onerror=alert(1)>";
  var peer = "<svg onload=alert(1)>";
  model.units[0].title = bad;
  model.peers.internal[0].name = peer;
  model.refs.people["3"].name = peer;
  model.projects[0].label = "과제\u2028A";
  model.ontology.nodes[3].label = bad;
  var f = fileDoc(model, null);
  var isl = f.doc.getElementById("lm27-data").textContent;
  assert.ok(isl.indexOf("<") < 0 && isl.indexOf(">") < 0 && isl.indexOf("\u2028") < 0, "섬 이스케이프");
  M.R.boot(f.doc, {win: f.win, storage: null});
  ["summary", "tree", "peers", "graph", "workflow", "review"].forEach(function (s) {
    f.win.location.hash = "#report/" + s;
    f.main.all().forEach(function (n) {
      assert.ok(["img", "script", "iframe", "object", "embed", "foreignObject", "style", "link"].indexOf(n.tagName) < 0, s + " 금지 요소 " + n.tagName);
      Object.keys(n.attrs).forEach(function (k) { assert.ok(!/^on/i.test(k) && k !== "style", s + " 금지 속성 " + k); });
    });
  });
  f.win.location.hash = "#report/summary";
  assert.ok(text(f.main).indexOf(bad) >= 0, "제목이 글자 그대로");
  f.win.location.hash = "#report/peers";
  assert.ok(text(f.main).indexOf(peer) >= 0, "이름이 글자 그대로");
  return Promise.resolve();
});

scenario("KB-2 트리 표 키보드 — ↑↓ 이동·→ 펼침/첫 자식·← 부모/접기·Enter 수준 패널", function () {
  var M = mods();
  var f = fileDoc(fixture("report_model.json"), null);
  M.R.boot(f.doc, {win: f.win, storage: null});
  f.win.location.hash = "#report/tree";
  function rows() { return f.main.all().filter(function (n) { return n.getAttribute("data-tree"); }); }
  function act() { return f.doc.activeElement.getAttribute("data-tree"); }
  var r0 = rows()[0];
  assert.strictEqual(r0.getAttribute("data-tree"), "d:DEV");
  assert.strictEqual(r0.getAttribute("tabindex"), "0", "로빙 tabindex");
  r0.focus();
  fire(r0, "keydown", {key: "ArrowDown"});
  assert.strictEqual(act(), "p:DEV/P-0007");
  fire(f.doc.activeElement, "keydown", {key: "ArrowDown"});
  assert.strictEqual(act(), "r:DEV/P-0007/r_5c0d11");
  assert.strictEqual(f.doc.activeElement.getAttribute("aria-expanded"), "false");
  var n0 = rows().length;
  fire(f.doc.activeElement, "keydown", {key: "ArrowRight"});
  assert.strictEqual(act(), "r:DEV/P-0007/r_5c0d11", "펼친 뒤 초점 유지");
  assert.strictEqual(rows().length, n0 + 3, "단위업무 3행");
  fire(f.doc.activeElement, "keydown", {key: "ArrowRight"});
  assert.ok(/^u:/.test(act()), "첫 자식");
  fire(f.doc.activeElement, "keydown", {key: "ArrowLeft"});
  assert.strictEqual(act(), "r:DEV/P-0007/r_5c0d11", "부모");
  fire(f.doc.activeElement, "keydown", {key: "ArrowLeft"});
  assert.strictEqual(rows().length, n0, "접기");
  var ev = fire(f.doc.activeElement, "keydown", {key: "Enter"});
  assert.ok(ev.defaultPrevented);
  var sel = rows().filter(function (n) { return n.getAttribute("aria-selected") === "true"; });
  assert.deepStrictEqual(sel.map(function (n) { return n.getAttribute("data-tree"); }), ["r:DEV/P-0007/r_5c0d11"]);
  var panel = f.doc.getElementById("r-panel");
  assert.ok(panel && text(panel).indexOf("회로 해석 작업이 이 역할 투입의 56%로 가장 큽니다.") >= 0, "역할 패널 규칙 문장");
  fire(f.doc.activeElement, "keydown", {key: "End"});
  assert.strictEqual(act(), "b:B_UNKNOWN", "버킷 5행은 늘 보인다(RPT-13)");
  fire(f.doc.activeElement, "keydown", {key: "ArrowLeft"});
  assert.strictEqual(act(), "x:UNATTR", "버킷 → 근무 중 미분류");
  return Promise.resolve();
});

scenario("로컬 앱 부트 — 홈 카드·pill 배지(막힘·위험)·머리 띠(RPT-04)·PC 라벨·능력 표 펼침", function () {
  var c = bootApp(baseRoutes(fixture("report_model.json")), "#home");
  return settle().then(function () {
    var t = text(c.doc.body);
    assert.ok(t.indexOf("[PC1 · 데스크톱]") >= 0, "PC 라벨");
    assert.ok(t.indexOf("기간 출처: 기본값(최근 3개월)") >= 0, "RPT-04 머리 띠");
    var items = byTag(c.doc.getElementById("card-next"), "li").map(text);
    assert.strictEqual(items.length, 3);
    assert.ok(items[0].indexOf("팀 묶음을 보내지 못했습니다") >= 0 && items[1].indexOf("사용 기록기가 멈췄습니다") >= 0, "등급 순서");
    var pills = byTag(c.doc.getElementById("lm27-nav"), "a");
    function badge(href) { var a = pills.filter(function (p) { return p.getAttribute("href") === href; })[0]; return a.all().filter(function (n) { return /pill-badge/.test(n.getAttribute("class") || ""); }).map(text)[0]; }
    assert.strictEqual(badge("#home"), "2");
    assert.strictEqual(badge("#team"), "1");
    assert.strictEqual(badge("#collect"), "1");
    assert.strictEqual(badge("#analysis"), undefined);
    assert.strictEqual(pills.filter(function (p) { return p.getAttribute("aria-current") === "page"; }).map(text)[0].indexOf("대시보드"), 0);
    assert.ok(t.indexOf("0.99 MM") >= 0 && t.indexOf("107%") >= 0, "최근 분석 KPI");
    var kc = c.doc.getElementById("card-analysis");
    assert.ok(/\bcard-bare\b/.test(kc.getAttribute("class")), "KPI 줄은 테두리 없는 카드(LM24 타일)");
    assert.strictEqual(byTag(kc, "button").filter(function (b) { return /\bkpi\b/.test(b.getAttribute("class") || ""); }).length, 5, "KPI 타일 5개 — 누르면 보고서");
    var grid = c.main.all().filter(function (n) { return n.getAttribute("class") === "grid2"; })[0];
    assert.ok(grid && grid.textContent.indexOf("다음 할 일") >= 0 && grid.textContent.indexOf("팀 업로드") >= 0, "다음 할 일 | 팀 나란히(LM24 grid2)");
    assert.ok(t.indexOf("해당 없음") >= 0, "능력 표 해당 없음");
    var cell = byAct(c.main, "a-cell", "0|teams.uia")[0];
    fire(cell, "click");
    assert.ok(text(c.doc.getElementById("card-matrix")).indexOf("팀즈 창이 최소화·숨김이라 읽지 못했습니다") >= 0, "사유 문구는 서버 표");
    assert.ok(c.srv.count("GET", "/api/collect/coverage") === 1, "히트맵 자료");
    fire(byAct(kc, "a-goto", "#report/review")[0], "click");
    assert.strictEqual(c.win.location.hash, "#report/review", "KPI → 개인 보고서 절");
  });
});

scenario("쓰기 요청 — JSON + 토큰 헤더, GET 은 토큰 없음, 409 busy 는 카드 경고", function () {
  var routes = baseRoutes(fixture("report_model.json"));
  routes["POST /api/collect/run"] = {status: 409, body: {ok: false, code: "busy", error: "지금 '분석'이 진행 중입니다 — 끝나면 다시 눌러 주세요"}};
  var c = bootApp(routes, "#collect");
  return settle().then(function () {
    fire(byAct(c.main, "a-collect", "auto")[0], "click");
    return settle();
  }).then(function () {
    var call = c.srv.last("POST", "/api/collect/run");
    assert.ok(call, "POST 함");
    assert.strictEqual(call.headers["X-LM27-UI-Token"], TOKEN);
    assert.strictEqual(call.headers["Content-Type"], "application/json");
    assert.deepStrictEqual(call.body, {mode: "auto"});
    c.srv.calls.filter(function (x) { return x.method === "GET"; }).forEach(function (x) { assert.ok(!x.headers["X-LM27-UI-Token"], "GET 토큰 0 " + x.path); });
    assert.ok(text(c.doc.getElementById("card-run")).indexOf("지금 '분석'이 진행 중입니다") >= 0, "409 문구");
    assert.strictEqual(c.app.state.jobOrder.length, 0, "작업 추적 안 함");
  });
});

scenario("작업 진행 — job_id 추적·폴링·완료 뒤 다시 읽기·알림은 [닫기]까지", function () {
  var routes = baseRoutes(fixture("report_model.json"));
  var JID = "j20261005100000abcd";
  var state = {n: 0};
  routes["POST /api/collect/run"] = {job_id: JID};
  routes["GET /api/jobs/" + JID] = function () {
    state.n++;
    if (state.n === 1) {
      return {job_id: JID, kind: "collect", lane: "bundle", state: "running", events: [{seq: 1, ev: "stage_start", stage: "probe", name_ko: "탐침"},
        {seq: 2, ev: "progress", stage: "probe", done: 1, total: 3, text_ko: "능력 탐침 중"}]};
    }
    return {job_id: JID, kind: "collect", state: "done", rc: 0, events: [{seq: 3, ev: "stage_end", stage: "probe", state: "done"}]};
  };
  var c = bootApp(routes, "#collect");
  var before;
  return settle().then(function () {
    fire(byAct(c.main, "a-collect", "auto")[0], "click");
    return settle();
  }).then(function () {
    assert.ok(c.app.state.jobs[JID], "추적");
    c.timers.run();
    return settle();
  }).then(function () {
    var jb = c.doc.getElementById("lm27-jobs");
    assert.ok(!jb.hasAttribute("hidden") && text(jb).indexOf("작업 1") === 0, "작업 버튼");
    assert.ok(text(c.doc.getElementById("card-run")).indexOf("탐침") >= 0, "단계 표");
    before = c.srv.count("GET", "/api/collect/status");
    c.timers.run();
    return settle();
  }).then(function () {
    var al = c.doc.getElementById("lm27-alerts");
    assert.ok(text(al).indexOf("'수집' 작업을 마쳤습니다.") >= 0, "완료 알림");
    assert.ok(c.srv.count("GET", "/api/collect/status") > before, "끝나면 다시 읽기");
    assert.strictEqual(c.timers.q.length, 0, "더 돌 작업이 없으면 폴링 멈춤");
    fire(byAct(al, "a-dismiss")[0], "click");
    assert.ok(text(c.doc.getElementById("lm27-alerts")).indexOf("마쳤습니다") < 0, "[닫기]");
    fire(c.doc.getElementById("lm27-jobs"), "click");
    return settle();
  }).then(function () {
    var dr = c.doc.body.all().filter(function (n) { return n.getAttribute("role") === "dialog"; })[0];
    assert.ok(dr && text(dr).indexOf("수집") >= 0 && text(dr).indexOf("완료") >= 0, "작업 서랍");
  });
});

scenario("RPT-03 결과 선택 — 없음·정리됨(조용한 교체 금지)·명시 선택", function () {
  var routes = baseRoutes(fixture("report_model.json"));
  routes["GET /api/report"] = {status: 404, body: {ok: false, code: "no_current", error: "없음"}};
  var c = bootApp(routes, "#report");
  return settle().then(function () {
    assert.ok(text(c.main).indexOf("아직 분석 결과가 없습니다") >= 0, "① 빈 상태");
    routes["GET /api/report"] = {status: 404, body: {ok: false, code: "run_missing", run_id: "20261003-080000-9a8b", error: "정리됨"}};
    c.win.location.hash = "#home";
    return settle();
  }).then(function () { return go(c, "#report"); }).then(function () {
    assert.ok(text(c.main).indexOf("정리되었습니다 — 이력에서 고르세요") >= 0, "③ 안내");
    assert.strictEqual(c.srv.count("POST", "/api/analysis/current"), 0, "조용한 교체 0");
    routes["POST /api/analysis/current"] = {ok: true};
    routes["GET /api/report"] = clone(fixture("report_model.json"));
    fire(byAct(c.main, "a-pick", "20261001-090000-1b2c")[0], "click");
    return settle();
  }).then(function () {
    assert.deepStrictEqual(c.srv.last("POST", "/api/analysis/current").body, {run_id: "20261001-090000-1b2c"}, "② 명시 선택");
    assert.ok(text(c.main).indexOf("주요 단위업무") >= 0, "선택한 결과로 보고서");
  });
});

scenario("RPT-05 보고서 판 다름 — 다시 만들기 요청 1회, 코파일럿 호출 0", function () {
  var model = fixture("report_model.json");
  model.schema_version = "2.0";
  var routes = baseRoutes(model);
  routes["POST /api/report/build"] = {job_id: "j20261005100100beef"};
  routes["GET /api/jobs/j20261005100100beef"] = {job_id: "j20261005100100beef", kind: "report_build", state: "running", events: []};
  var c = bootApp(routes, "#report");
  return settle().then(function () {
    assert.ok(text(c.main).indexOf("새 형식으로 다시 만드는 중") >= 0);
    return go(c, "#home");
  }).then(function () { return go(c, "#report/tree"); }).then(function () {
    assert.strictEqual(c.srv.count("POST", "/api/report/build"), 1, "한 번만");
    assert.strictEqual(c.srv.calls.filter(function (x) { return /bridge/.test(x.path) && x.method === "POST"; }).length, 0);
  });
});

scenario("KB-9 확인 질문 응답 — 오류는 첫 오류 칸 초점, 보내면 '응답함'", function () {
  var routes = baseRoutes(fixture("report_model.json"));
  routes["POST /api/queue/answer"] = {ok: true, reanalyze_job: "j20261005100200cafe"};
  routes["GET /api/jobs/j20261005100200cafe"] = {job_id: "j20261005100200cafe", kind: "quick_reanalyze", state: "running", events: []};
  var c = bootApp(routes, "#report/queue");
  var Q = "9f2c01ab3e4d";
  return settle().then(function () {
    fire(byAct(c.main, "r-qpick", Q + "|instr")[0], "click");
    c.doc.getElementById("q-" + Q + "-d").value = "2026-09-12";
    fire(byAct(c.main, "r-qsend", Q)[0], "click");
    return settle();
  }).then(function () {
    assert.strictEqual(c.srv.count("POST", "/api/queue/answer"), 0, "오류면 보내지 않음");
    var err = c.doc.getElementById("q-" + Q + "-t-err");
    assert.ok(err && err.getAttribute("role") === "alert" && text(err).indexOf("시각을 넣어 주세요") >= 0, "오류 낭독");
    assert.strictEqual(c.doc.activeElement.getAttribute("id"), "q-" + Q + "-t", "첫 오류 칸 초점");
    assert.strictEqual(c.doc.getElementById("q-" + Q + "-d").value, "2026-09-12", "다시 그려도 입력 보존");
    c.doc.getElementById("q-" + Q + "-t").value = "10:00";
    fire(byAct(c.main, "r-qsend", Q)[0], "click");
    return settle();
  }).then(function () {
    var call = c.srv.last("POST", "/api/queue/answer");
    assert.deepStrictEqual(call.body, {qid: Q, answer: {choice: "instr", d: "2026-09-12", at: "2026-09-12T10:00"}});
    assert.ok(text(c.main).indexOf("응답함 — 빠른 재분석을 시작했습니다") >= 0);
    assert.ok(c.app.state.jobs.j20261005100200cafe, "재분석 작업 추적");
  });
});

scenario("기간 카드 — 기본 올해(1월 1일 ~ 오늘)·분기·반기 빠른 선택·기간 출처·Copilot 역할 없으면 AI 끔", function () {
  var routes = baseRoutes(fixture("report_model.json"));
  routes["POST /api/analysis/run"] = {ok: true};                  // 작업 id 없음 — 이 시나리오는 보낸 본문만 본다
  var c = bootApp(routes, "#analysis");
  function analyze() { fire(byAct(c.period, "a-analyze")[0], "click"); return settle(); }
  function body() { return c.srv.last("POST", "/api/analysis/run").body; }
  return settle().then(function () {
    assert.deepStrictEqual(dates(c), ["2026-01-01", "2026-10-05"], "기본 = 올해 1월 1일 ~ 오늘");
    assert.deepStrictEqual(byAct(c.period, "a-period").map(text), ["올해", "1분기", "2분기", "3분기", "4분기", "상반기", "하반기"]);
    assert.deepStrictEqual(pressedChips(c.period), ["ytd"], "올해(기본)가 눌린 칩");
    assert.ok(/\bon\b/.test(byAct(c.period, "a-period", "ytd")[0].getAttribute("class")), "LM24 .chip.on");
    assert.ok(byAct(c.period, "a-period").every(function (b) { return b.getAttribute("aria-disabled") === null; }), "10월이면 모든 분기·반기를 고를 수 있다");
    assert.ok(c.doc.getElementById("an-ai").hasAttribute("disabled"), "역할 없으면 AI 끔");
    assert.ok(text(c.period).indexOf("AI 판정을 쓰지 않도록 설정돼 있습니다") >= 0, "끈 이유(서버가 ai_here 를 주지 않는 예전 판 + 역할 없음)");
    assert.strictEqual(byAct(c.main, "a-analyze").length, 0, "분석 화면에는 실행 카드가 따로 없다(기간 카드 하나)");
    return analyze();
  }).then(function () {
    var b = body();
    assert.deepStrictEqual([b.from, b.to, b.ai, b.period_source, b.period_months], ["2026-01-01", "2026-10-05", false, "default", undefined]);
    assert.ok(text(c.period).indexOf("분석을 시작했습니다(2026-01-01 ~ 2026-10-05)") >= 0, "기간 카드 알림");
    fire(byAct(c.period, "a-period", "q3")[0], "click");
    assert.deepStrictEqual(dates(c), ["2026-07-01", "2026-09-30"], "3분기 = 07-01 ~ 09-30");
    assert.deepStrictEqual(pressedChips(c.period), ["q3"]);
    fire(byAct(c.period, "a-period", "q4")[0], "click");
    assert.deepStrictEqual(dates(c), ["2026-10-01", "2026-10-05"], "진행 중인 4분기 = 10-01 ~ 오늘");
    assert.ok(byAct(c.period, "a-period", "q4")[0].getAttribute("data-tip").indexOf("진행 중") >= 0);
    fire(byAct(c.period, "a-period", "h1")[0], "click");
    assert.deepStrictEqual(dates(c), ["2026-01-01", "2026-06-30"], "상반기");
    return analyze();
  }).then(function () {
    assert.deepStrictEqual([body().from, body().to, body().period_source], ["2026-01-01", "2026-06-30", "h1"]);
    var f = c.doc.getElementById("an-from");
    f.value = "2026-02-15";
    fire(f, "change");
    assert.deepStrictEqual(pressedChips(c.period), [], "손으로 바꾸면 칩 선택이 풀린다");
    return analyze();
  }).then(function () {
    assert.deepStrictEqual([body().from, body().period_source], ["2026-02-15", "user"], "직접 지정");
    c.doc.getElementById("an-from").value = "2026-04-01";
    fire(c.doc.getElementById("an-from"), "change");
    assert.deepStrictEqual(pressedChips(c.period), ["q2"], "날짜가 2분기(04-01 ~ 06-30)와 같아지면 2분기 칩");
    c.doc.getElementById("an-to").value = "2026-03-01";
    return analyze();
  }).then(function () {
    assert.ok(text(c.period).indexOf("끝 ≥ 시작") >= 0, "끝이 시작보다 앞서면 보내지 않음");
    assert.strictEqual(c.srv.count("POST", "/api/analysis/run"), 3);
    assert.ok(text(c.main).indexOf("현재 표시") >= 0, "이력 현재 표시");
  });
});

scenario("기간 카드 — 아직 오지 않은 분기·반기는 고를 수 없음(이유 툴팁)·윤년 2월 29일", function () {
  var c = bootApp(baseRoutes(fixture("report_model.json")), "#home", {now: new Date(2024, 1, 29, 9, 0, 0)});
  return settle().then(function () {
    assert.deepStrictEqual(dates(c), ["2024-01-01", "2024-02-29"], "윤년 — 오늘(2월 29일)까지");
    var dis = byAct(c.period, "a-period").filter(function (b) { return b.getAttribute("aria-disabled") === "true"; });
    assert.deepStrictEqual(dis.map(function (b) { return b.getAttribute("data-ref"); }), ["q2", "q3", "q4", "h2"]);
    assert.ok(dis[0].getAttribute("data-tip").indexOf("아직 오지 않은 기간") >= 0, "이유 툴팁");
    fire(dis[1], "click");
    assert.deepStrictEqual(dates(c), ["2024-01-01", "2024-02-29"], "눌러도 바뀌지 않음");
    assert.deepStrictEqual(pressedChips(c.period), ["ytd"]);
    fire(byAct(c.period, "a-period", "q1")[0], "click");
    assert.deepStrictEqual(dates(c), ["2024-01-01", "2024-02-29"], "1분기(진행 중) = 01-01 ~ 오늘");
    assert.deepStrictEqual(pressedChips(c.period), ["q1"], "같은 기간이어도 고른 칩이 눌림");
  });
});

scenario("기간 카드 동작 단추·진행 — [분석 실행] 중엔 잠김·[중지]·상태 줄·단계 줄·사용 안내", function () {
  var routes = baseRoutes(fixture("report_model.json"));
  var JID = "j20261005100300dead";
  var st = {n: 0};
  routes["POST /api/analysis/run"] = {job_id: JID};
  routes["GET /api/jobs/" + JID] = function () {
    st.n++;
    return st.n < 2 ? {job_id: JID, kind: "analyze", state: "running", events: [{seq: 1, ev: "progress", stage: "time", done: 3, total: 10,
      text_ko: "근무시간 계산 중"}]} : {job_id: JID, kind: "analyze", state: "done", rc: 0, events: []};
  };
  routes["POST /api/collect/run"] = {ok: true};
  routes["POST /api/report/build"] = {ok: true};
  var c = bootApp(routes, "#home");
  return settle().then(function () {
    var sb = text(c.sbar);
    assert.ok(sb.indexOf("대기") >= 0 && sb.indexOf("마지막 분석") >= 0 && sb.indexOf("v0.1.0") >= 0, "상태 줄: 대기 · 마지막 분석 · 판");
    assert.ok(sb.indexOf("마지막 수집 10-05 09:02(PC1)") >= 0, "상태 줄: 마지막 수집");
    assert.ok(text(c.doc.getElementById("lm27-ver")).indexOf("v0.1.0") === 0, "머리 작은 글자 = 판");
    var steps = byTag(c.steps, "a");
    assert.deepStrictEqual(steps.map(function (a) { return a.getAttribute("href"); }), ["#collect", "#analysis", "#report", "#team"]);
    assert.ok(text(steps[1]).indexOf("✓") === 0 && text(steps[0]).indexOf("✓") === 0, "마친 단계 ✓(분석 결과·수집 기록 있음)");
    fire(byAct(c.steps, "a-guide")[0], "click");
    var dr = c.doc.body.all().filter(function (n) { return n.getAttribute("role") === "dialog"; })[0];
    assert.ok(dr && text(dr).indexOf("기본은 올해 1월 1일 ~ 오늘") >= 0, "사용 안내 서랍");
    fire(byAct(dr, "drawer-close")[0], "click");
    fire(byAct(c.period, "a-do", "collect")[0], "click");
    fire(byAct(c.period, "a-do", "rebuild")[0], "click");
    return settle();
  }).then(function () {
    assert.deepStrictEqual(c.srv.last("POST", "/api/collect/run").body, {mode: "auto"}, "[수집]");
    assert.deepStrictEqual(c.srv.last("POST", "/api/report/build").body, {run_id: "20261005-101500-3fa2"}, "[보고서 다시 만들기] = 지금 보는 결과");
    fire(byAct(c.period, "a-analyze")[0], "click");
    return settle();
  }).then(function () {
    c.timers.run();
    return settle();
  }).then(function () {
    var run = byAct(c.period, "a-analyze")[0];
    assert.strictEqual(run.getAttribute("aria-disabled"), "true", "분석 중엔 [분석 실행] 잠김(이유 툴팁)");
    assert.strictEqual(byAct(c.period, "a-period-cancel", JID).length, 1, "[중지]");
    assert.ok(text(c.period).indexOf("근무시간 계산 중") >= 0, "진행 글");
    assert.ok(text(c.sbar).indexOf("분석 진행 중") >= 0 && byTag(c.sbar, "svg").length === 1, "상태 줄 진행 막대");
    c.timers.run();
    return settle();
  }).then(function () {
    assert.strictEqual(byAct(c.period, "a-analyze")[0].getAttribute("aria-disabled"), null, "끝나면 다시 누를 수 있다");
    assert.ok(text(c.doc.getElementById("lm27-alerts")).indexOf("'분석' 작업을 마쳤습니다.") >= 0);
    assert.ok(text(c.sbar).indexOf("대기") >= 0);
  });
});

scenario("틀 요소(단계 줄·기간 카드·상태 줄)가 없는 옛 껍데기에서도 화면은 돈다", function () {
  var c = bootApp(baseRoutes(fixture("report_model.json")), "#analysis", {frame: false});
  return settle().then(function () {
    assert.strictEqual(c.period, null);
    assert.ok(text(c.main).indexOf("분석 이력") >= 0 && text(c.main).indexOf("현재 표시") >= 0, "분석 화면 카드");
    return go(c, "#collect");
  }).then(function () {
    assert.ok(text(c.doc.getElementById("card-coverage")).indexOf("2026-01-01 ~ 2026-10-05") >= 0, "기간 카드가 없어도 기본 기간(올해)");
  });
});

scenario("수집 화면 — 커버리지 원장·기간 다시 수집은 기간 카드를 따른다(기본 올해)·셀 표 접힘", function () {
  var routes = baseRoutes(fixture("report_model.json"));
  routes["POST /api/collect/run"] = {ok: true};
  var c = bootApp(routes, "#collect");
  function covQuery() {
    var l = c.srv.calls.filter(function (x) { return x.path.indexOf("/api/collect/coverage") === 0; });
    return l[l.length - 1].path.split("?")[1];
  }
  return settle().then(function () {
    assert.strictEqual(covQuery(), "from=2026-01-01&to=2026-10-05", "커버리지 = 올해 1월 1일 ~ 오늘");
    assert.ok(text(c.doc.getElementById("card-coverage")).indexOf("2026-01-01 ~ 2026-10-05 · 278일") >= 0, "기간 표시");
    assert.deepStrictEqual([c.doc.getElementById("rc-since").value, c.doc.getElementById("rc-until").value], ["2026-01-01", "2026-10-05"]);
    assert.strictEqual(byTag(c.doc.getElementById("card-coverage"), "details").length, 1, "출처별 셀 표는 접혀 있다");
    assert.strictEqual(c.doc.getElementById("cov-from"), null, "커버리지 자체 날짜 칸 없음(기간 카드 하나)");
    fire(byAct(c.period, "a-period", "q2")[0], "click");
    return settle();
  }).then(function () {
    assert.strictEqual(covQuery(), "from=2026-04-01&to=2026-06-30", "2분기로 다시 읽음");
    assert.deepStrictEqual([c.doc.getElementById("rc-since").value, c.doc.getElementById("rc-until").value], ["2026-04-01", "2026-06-30"]);
    fire(byAct(c.main, "a-collect", "recollect")[0], "click");
    return settle();
  }).then(function () {
    assert.deepStrictEqual(c.srv.last("POST", "/api/collect/run").body, {mode: "recollect", since: "2026-04-01", until: "2026-06-30"});
    fire(byAct(c.period, "a-period", "ytd")[0], "click");
    var f = c.doc.getElementById("an-from");
    f.value = "2024-01-01";
    fire(f, "change");
    return settle();
  }).then(function () {
    assert.strictEqual(covQuery(), "from=2025-09-01&to=2026-10-05", "400일 넘으면 끝에서 400일만(서버 상한)");
    assert.ok(text(c.doc.getElementById("card-coverage")).indexOf("끝에서 400일만") >= 0);
  });
});

scenario("팀 — 포트 검사·서버 오류 칸 표시·기본값 되돌리기는 API·미리보기 보내기", function () {
  var routes = baseRoutes(fixture("report_model.json"));
  routes["PUT /api/team/settings"] = {status: 400, body: {ok: false, code: "invalid", error: "저장하지 않았습니다 — 칸 아래 이유를 확인하세요",
    errors: {server_host: "사설 IPv4·루프백만 쓸 수 있습니다"}}};
  routes["POST /api/team/settings/reset-address"] = {ok: true};
  routes["POST /api/team/send/lm27_team_bundle_2026-09_0123456789ab"] = {ok: true};
  var c = bootApp(routes, "#team");
  return settle().then(function () {
    c.doc.getElementById("tm-port").value = "70000";
    fire(byAct(c.main, "a-team-save")[0], "click");
    return settle();
  }).then(function () {
    assert.strictEqual(c.srv.count("PUT", "/api/team/settings"), 0, "포트 오류면 보내지 않음");
    assert.ok(text(c.doc.getElementById("card-addr")).indexOf("포트는 1~65535 정수입니다") >= 0);
    c.doc.getElementById("tm-port").value = "9310";
    c.doc.getElementById("tm-host").value = "203.0.113.5";
    fire(byAct(c.main, "a-team-save")[0], "click");
    return settle();
  }).then(function () {
    var body = c.srv.last("PUT", "/api/team/settings").body;
    assert.strictEqual(body.server_port, 9310);
    assert.ok(text(c.doc.getElementById("card-addr")).indexOf("사설 IPv4·루프백만 쓸 수 있습니다") >= 0, "서버 이유를 칸 아래");
    fire(byAct(c.main, "a-reset-addr")[0], "click");
    return settle();
  }).then(function () {
    assert.strictEqual(c.srv.count("POST", "/api/team/settings/reset-address"), 1);
    fire(byAct(c.main, "a-preview")[0], "click");
    return settle();
  }).then(function () {
    var dr = c.doc.body.all().filter(function (n) { return n.getAttribute("role") === "dialog"; })[0];
    assert.ok(text(dr).indexOf("금지 내용 검사: 0건(통과)") >= 0 && text(dr).indexOf("시간 수치(근무시간·업무별 분)는 가릴 수 없습니다") >= 0);
    fire(byAct(dr, "a-pv-send")[0], "click");
    return settle();
  }).then(function () {
    assert.strictEqual(c.srv.count("POST", "/api/team/send/lm27_team_bundle_2026-09_0123456789ab"), 1);
  });
});

scenario("팀 대기열 — 승인 전 묶음은 행에서 바로 보내지 않는다(미리보기·보내기만), 승인된 묶음은 [보내기]·[다시 시도](C17)", function () {
  var routes = baseRoutes(fixture("report_model.json"));
  var st = clone(routes["GET /api/team/status"]);
  var base = st.outbox[0];
  st.outbox = [Object.assign(clone(base), {item: "lm27_team_bundle_2026-09_0123456789ab", approved: false, state: "pending"}),
    Object.assign(clone(base), {item: "lm27_team_bundle_2026-08_1111111111aa", period_key: "2026-08", approved: true, state: "pending"}),
    Object.assign(clone(base), {item: "lm27_team_bundle_2026-07_2222222222bb", period_key: "2026-07", approved: true, state: "retry_wait"}),
    Object.assign(clone(base), {item: "lm27_team_bundle_2026-06_3333333333cc", period_key: "2026-06", approved: false, state: "failed"})];
  routes["GET /api/team/status"] = st;
  var c = bootApp(routes, "#team");
  return settle().then(function () {
    var sends = byAct(c.main, "a-send").map(function (b) { return b.getAttribute("data-ref"); });
    assert.deepStrictEqual(sends, ["lm27_team_bundle_2026-08_1111111111aa", "lm27_team_bundle_2026-07_2222222222bb"], "승인된 것만 행의 [보내기]");
    var pv = byAct(c.main, "a-preview", "lm27_team_bundle_2026-09_0123456789ab")[0];
    assert.strictEqual(text(pv), "미리보기·보내기");
    assert.strictEqual(c.srv.count("POST", "/api/team/send/lm27_team_bundle_2026-09_0123456789ab"), 0);
    fire(pv, "click");
    return settle();
  }).then(function () {
    assert.strictEqual(c.srv.count("GET", "/api/team/preview/lm27_team_bundle_2026-09_0123456789ab"), 1, "미리보기를 먼저 연다");
  });
});

scenario("팀 미리보기 [제목 가림] — 서버가 다시 만들기 작업을 띄웠을 때만 그 작업을 추적, 아니면 서버 문구 그대로(C16)", function () {
  var routes = baseRoutes(fixture("report_model.json"));
  var ITEM = "lm27_team_bundle_2026-09_0123456789ab";
  var JID = "j20261007090000beef";
  var reply = {ok: true, changed: true, stale_n: 1, text_ko: "가림을 저장했습니다. 가리기 전에 만든 대기 묶음 1개는 보내지 않습니다. 묶음은 아직 다시 만들지 못했습니다: 지금 '분석'이 진행 중입니다"};
  routes["POST /api/team/mask"] = function () { return clone(reply); };
  routes["GET /api/jobs/" + JID] = {job_id: JID, kind: "team_build", lane: "bundle", state: "running", events: []};
  var c = bootApp(routes, "#team");
  function drawer() { return c.doc.body.all().filter(function (n) { return n.getAttribute("role") === "dialog"; })[0]; }
  return settle().then(function () {
    fire(byAct(c.main, "a-preview")[0], "click");
    return settle();
  }).then(function () {
    fire(byAct(drawer(), "a-mask", "u_a1a1a1a1a1|title")[0], "click");
    return settle();
  }).then(function () {
    var b = c.srv.last("POST", "/api/team/mask").body;
    assert.deepStrictEqual([b.unit_id, b.mode, b.item], ["u_a1a1a1a1a1", "title", ITEM], "미리보기 중인 항목을 함께 보낸다");
    var al = text(c.doc.getElementById("lm27-alerts"));
    assert.ok(al.indexOf("다시 만들었습니다") < 0, "작업이 없으면 '다시 만들었다'고 하지 않는다");
    assert.ok(al.indexOf("묶음은 아직 다시 만들지 못했습니다") >= 0, "서버 문구 그대로");
    reply = {ok: true, changed: true, stale_n: 1, job_id: JID, text_ko: "가림을 바꿔 2026-09-01 ~ 2026-09-30 묶음을 다시 만듭니다 — 끝나면 미리보기를 다시 엽니다(이전 묶음은 대체됩니다)"};
    fire(byAct(c.main, "a-preview")[0], "click");
    return settle();
  }).then(function () {
    fire(byAct(drawer(), "a-mask", "u_a1a1a1a1a1|detail")[0], "click");
    return settle();
  }).then(function () {
    assert.ok(c.app.state.jobs[JID] && c.app.state.jobs[JID].kind === "team_build", "다시 만들기 작업을 추적");
    assert.ok(text(c.doc.getElementById("lm27-alerts")).indexOf("묶음을 다시 만듭니다") >= 0);
  });
});

scenario("팀 미리보기 — 가림을 바꾼 뒤의 옛 묶음은 [보내기]·[승인만]이 잠기고 이유를 보인다(C16)", function () {
  var routes = baseRoutes(fixture("report_model.json"));
  var ITEM = "lm27_team_bundle_2026-09_0123456789ab";
  var pv = clone(routes["GET /api/team/preview/" + ITEM]);
  pv.units[0].mask = "title";
  pv.units[0].mask_applied = false;
  pv.stale_mask = true;
  pv.can_send = false;
  pv.mask_gaps = ["unit:u_a1a1a1a1a1:title"];
  pv.message = "가림을 바꾼 뒤 아직 다시 만들지 않은 묶음이라 보내지 않습니다 — [팀 묶음 만들기]로 다시 만들면 바뀐 가림으로 보냅니다";
  routes["GET /api/team/preview/" + ITEM] = pv;
  var c = bootApp(routes, "#team");
  return settle().then(function () {
    fire(byAct(c.main, "a-preview")[0], "click");
    return settle();
  }).then(function () {
    var dr = c.doc.body.all().filter(function (n) { return n.getAttribute("role") === "dialog"; })[0];
    var t = text(dr);
    assert.ok(t.indexOf("보낼 수 없는 이유: 가림을 바꾼 뒤 아직 다시 만들지 않은 묶음") >= 0, t.slice(0, 400));
    assert.ok(t.indexOf("이 묶음에는 아직 — 다시 만들면 적용") >= 0, "가림 칸에 적용 안 됨 표시");
    var send = byAct(dr, "a-pv-send")[0];
    assert.ok(send.hasAttribute("aria-disabled") || send.hasAttribute("disabled"), "[보내기] 잠김");
    fire(send, "click");
    return settle();
  }).then(function () {
    assert.strictEqual(c.srv.count("POST", "/api/team/send/" + ITEM), 0, "보내지 않는다");
  });
});

scenario("기간 카드 '오늘' = 서버가 알려 준 근무 시간대(PC 벽시계가 아님) — 사람이 손대지 않은 기본 기간만 맞춘다(L06)", function () {
  function boot(off) {
    var routes = baseRoutes(fixture("report_model.json"));
    var runs = clone(routes["GET /api/analysis/runs"]);
    runs.defaults = {months: 3, period: {tz_offset_min: off}};
    routes["GET /api/analysis/runs"] = runs;
    var n = 0;
    routes["POST /api/analysis/run"] = function () { n++; return {job_id: "j2026100700000" + n + "c0de"}; };
    [1, 2, 3].forEach(function (k) {
      var id = "j2026100700000" + k + "c0de";
      routes["GET /api/jobs/" + id] = {job_id: id, kind: "analyze", state: "done", rc: 0, events: []};
    });
    return bootApp(routes, "#analysis", {now: new Date(Date.UTC(2026, 9, 6, 23, 30, 0))});    // UTC 10-06 23:30
  }
  var runsBefore = 0;
  var a = boot(840);                                        // UTC+14 → 10-07 13:30
  var b = boot(-720);                                       // UTC−12 → 10-06 11:30
  return settle().then(function () {
    assert.deepStrictEqual(dates(a), ["2026-01-01", "2026-10-07"], "근무 시간대 +14:00 의 오늘");
    assert.deepStrictEqual(dates(b), ["2026-01-01", "2026-10-06"], "근무 시간대 −12:00 의 오늘");
    assert.deepStrictEqual(pressedChips(a.period), ["ytd"]);
    fire(byAct(a.period, "a-period", "q4")[0], "click");
    assert.deepStrictEqual(dates(a), ["2026-10-01", "2026-10-07"], "분기 단추도 같은 오늘");
    fire(byAct(b.period, "a-analyze")[0], "click");
    return settle();
  }).then(function () {
    var body = b.srv.last("POST", "/api/analysis/run").body;
    assert.deepStrictEqual([body.from, body.to, body.period_source], ["2026-01-01", "2026-10-06", "default"]);
    b.timers.run();                                         // 분석 작업이 끝나면 전역 자료(분석 이력)를 다시 읽는다
    return settle();
  }).then(function () {
    var f = b.doc.getElementById("an-from");
    f.value = "2026-03-01";
    fire(f, "change");
    assert.strictEqual(b.app.state.periodAuto, false);
    runsBefore = b.srv.count("GET", "/api/analysis/runs");
    fire(byAct(b.period, "a-analyze")[0], "click");
    return settle();
  }).then(function () {
    b.timers.run();
    return settle();
  }).then(function () {
    assert.ok(b.srv.count("GET", "/api/analysis/runs") > runsBefore, "작업이 끝나 전역 자료를 다시 읽었다");
    assert.deepStrictEqual(dates(b), ["2026-03-01", "2026-10-06"], "사람이 고친 기간은 다시 맞추지 않는다");
  });
});

scenario("설정 — 묶음 이동·값 저장 오류는 그 줄에·개인정보 묶음은 감사·광고 큐를 읽음", function () {
  var routes = baseRoutes(fixture("report_model.json"));
  routes["PUT /api/settings"] = {status: 400, body: {ok: false, code: "invalid", error: "저장하지 않았습니다", errors: {"ui.jobPollMs": "200~10000 사이여야 합니다"}}};
  var c = bootApp(routes, "#settings/ui");
  return settle().then(function () {
    assert.ok(text(c.main).indexOf("작업 진행 읽기 주기(ms)") >= 0);
    c.doc.getElementById("set-ui-jobPollMs").value = "50";
    fire(byAct(c.main, "a-set-save", "ui.jobPollMs")[0], "click");
    return settle();
  }).then(function () {
    assert.deepStrictEqual(c.srv.last("PUT", "/api/settings").body, {"ui.jobPollMs": 50});
    assert.ok(text(c.main).indexOf("200~10000 사이여야 합니다") >= 0);
    return go(c, "#settings/privacy");
  }).then(function () {
    assert.ok(c.srv.count("GET", "/api/privacy/audit") >= 1 && c.srv.count("GET", "/api/privacy/ad-suspects") >= 1);
    assert.ok(text(c.main).indexOf("정제 시험대") >= 0 && text(c.main).indexOf("[광고] 할인 안내") >= 0);
  });
});

scenario("RPT-40 성공 경로 화면 글자 — '오류'·'[!]'·금지 표현 0, 카드 하나 실패는 그 카드만", function () {
  var routes = baseRoutes(fixture("report_model.json"));
  var c = bootApp(routes, "#home");
  var seen = [];
  var hashes = ["#collect", "#analysis", "#report/summary", "#report/tree", "#report/review", "#report/agentic", "#report/queue", "#report/hier",
    "#team", "#settings/ui", "#settings/calib", "#home"];
  var p = settle();
  hashes.forEach(function (hs) {
    p = p.then(function () { return go(c, hs); }).then(function () { seen.push([hs, text(c.doc.body)]); });
  });
  return p.then(function () {
    seen.forEach(function (s) {
      ["오류", "[!]", "개발자에게", "재설치", "대체 가능", "절감", "AX 가능 MM"].forEach(function (w) { assert.ok(s[1].indexOf(w) < 0, s[0] + " 에 '" + w + "'"); });
    });
    routes["GET /api/home"] = {status: 500, body: {ok: false, code: "internal", error: "읽기 실패"}};
    return go(c, "#collect").then(function () { return go(c, "#home"); });
  }).then(function () {
    var mx = text(c.doc.getElementById("card-matrix"));
    assert.ok(mx.indexOf("이 카드를 읽지 못했습니다") >= 0 && byAct(c.main, "a-reload", "matrix").length === 1, "실패 카드 + 다시 읽기");
    assert.ok(text(c.doc.getElementById("card-next")).indexOf("팀 묶음을 보내지 못했습니다") >= 0, "다른 카드는 정상");
  });
});

scenario("개인 보고서(앱) — 니즈 빼기·내보내기 요청·분류 고치기·분류 상태", function () {
  var routes = baseRoutes(fixture("report_model.json"));
  routes["POST /api/agentic/need/drop"] = {ok: true};
  routes["POST /api/report/export"] = {job_id: "j20261005100400f00d"};
  routes["GET /api/jobs/j20261005100400f00d"] = {job_id: "j20261005100400f00d", kind: "report_export", state: "running", events: []};
  routes["POST /api/hier/correction"] = {ok: true};
  var c = bootApp(routes, "#report/agentic");
  return settle().then(function () {
    fire(byAct(c.main, "r-need", "n_1a2b3c")[0], "click");
    return settle();
  }).then(function () {
    assert.deepStrictEqual(c.srv.last("POST", "/api/agentic/need/drop").body, {need_id: "n_1a2b3c", drop: true});
    assert.ok(text(c.main).indexOf("팀 묶음에서 뺍니다") >= 0);
    fire(byAct(c.main, "r-export")[0], "click");
    var json = c.doc.getElementById("r-ex-json");
    json.checked = false;
    var dr = c.doc.body.all().filter(function (n) { return n.getAttribute("role") === "dialog"; })[0];
    fire(byAct(dr, "r-form-ok")[0], "click");
    return settle();
  }).then(function () {
    var b = c.srv.last("POST", "/api/report/export").body;
    assert.deepStrictEqual([b.run_id, b.formats, b.variants], ["20261005-101500-3fa2", ["html", "csv"], ["full", "redacted"]]);
    assert.ok(c.app.state.jobs.j20261005100400f00d, "내보내기 작업 추적");
    return go(c, "#report/hier");
  }).then(function () {
    assert.ok(c.srv.count("GET", "/api/hier/state") === 1 && text(c.main).indexOf("과제C") >= 0, "분류 상태");
    return go(c, "#report/tree/u_a1a1a1a1a1");
  }).then(function () {
    fire(byAct(c.doc.getElementById("r-panel"), "r-fix", "u_a1a1a1a1a1")[0], "click");
    c.doc.getElementById("r-fix-project").value = "P-0012";
    var dr = c.doc.body.all().filter(function (n) { return n.getAttribute("role") === "dialog"; })[0];
    fire(byAct(dr, "r-form-ok")[0], "click");
    return settle();
  }).then(function () {
    assert.deepStrictEqual(c.srv.last("POST", "/api/hier/correction").body, {unit_id: "u_a1a1a1a1a1", set: {project: "P-0012"}, scope: "similar"});
  });
});

scenario("수동 업무 기록(§5.2.4) — 검사·첫 오류 칸 초점·보낼 형·[빠른 재분석]", function () {
  var routes = baseRoutes(fixture("report_model.json"));
  routes["POST /api/worklog"] = {ok: true, id: "m_0002"};
  routes["POST /api/analysis/run"] = {job_id: "j20261005100500aaaa"};
  routes["GET /api/jobs/j20261005100500aaaa"] = {job_id: "j20261005100500aaaa", kind: "quick_reanalyze", state: "running", events: []};
  var c = bootApp(routes, "#collect");
  return settle().then(function () {
    assert.strictEqual(c.doc.getElementById("wl-date").value, "2026-10-05", "기본 오늘");
    fire(byAct(c.main, "a-wl-save")[0], "click");
    return settle();
  }).then(function () {
    assert.strictEqual(c.srv.count("POST", "/api/worklog"), 0);
    assert.strictEqual(c.doc.activeElement.getAttribute("id"), "wl-hours", "구간도 시간도 없으면 시간 칸");
    c.doc.getElementById("wl-hours").value = "1.5";
    c.doc.getElementById("wl-memo").value = "시험 지그 점검";
    c.doc.getElementById("wl-project").value = "P-0007";
    fire(byAct(c.main, "a-wl-save")[0], "click");
    return settle();
  }).then(function () {
    assert.deepStrictEqual(c.srv.last("POST", "/api/worklog").body, {date: "2026-10-05", kind: "work", hours: 1.5, project: "P-0007", memo: "시험 지그 점검"});
    assert.ok(text(c.doc.getElementById("card-worklog")).indexOf("기록했습니다 — 다시 분석하면 반영됩니다") >= 0);
    assert.strictEqual(c.doc.getElementById("wl-hours").value, "", "저장 뒤 입력 비움");
    fire(byAct(c.main, "a-quick")[0], "click");
    return settle();
  }).then(function () {
    assert.deepStrictEqual(c.srv.last("POST", "/api/analysis/run").body, {rerun: "20261005-101500-3fa2", stages: ["classify", "time", "mining", "report"], ai: false});
    assert.ok(c.app.state.jobs.j20261005100500aaaa, "빠른 재분석 작업 추적");
    fire(byAct(c.main, "a-wl-retract", "m_0001")[0], "click");
    return settle();
  }).then(function () {
    assert.deepStrictEqual(c.srv.last("POST", "/api/worklog").body, {retract: "m_0001"}, "삭제 대신 취소 기록");
  });
});

scenario("R §11 자료 형이 다르면 그 카드·그 절만 멈춘다 — 다른 카드·절은 정상", function () {
  var routes = baseRoutes(fixture("report_model.json"));
  routes["GET /api/home"].matrix = {cols: [null], rows: [{pc: "PC1", cells: {}}]};
  var c = bootApp(routes, "#home");
  return settle().then(function () {
    assert.ok(text(c.doc.getElementById("card-matrix")).indexOf("이 카드를 그리지 못했습니다") >= 0, "형이 다른 카드");
    assert.ok(text(c.doc.getElementById("card-analysis")).indexOf("0.99 MM") >= 0, "다른 카드 정상");
    var M = mods();
    var model = fixture("report_model.json");
    model.reviews.months[0].lead_table = [null];
    var f = fileDoc(model, null);
    M.R.boot(f.doc, {win: f.win, storage: null});
    f.win.location.hash = "#report/review";
    assert.ok(text(f.main).indexOf("이 절을 그리지 못했습니다") >= 0, "형이 다른 절");
    assert.ok(byTag(f.main, "nav").some(function (n) { return n.getAttribute("aria-label") === "보고서 절"; }), "절 메뉴는 남음");
    f.win.location.hash = "#report/summary";
    assert.ok(text(f.main).indexOf("0.99 MM") >= 0, "다른 절 정상");
  });
});

scenario("분석 화면 Copilot 카드·직접 붙여넣기 — 마지막 탐침·보정 한도·[분석용 Edge 창 앞으로] 서버 문구·항목 수·반입 결과(B14·B15)", function () {
  var routes = baseRoutes(fixture("report_model.json"));
  routes["GET /api/hello"].pc.ai_here = true;
  routes["GET /api/bridge/status"] = {mode: "auto", mode_ko: "자동", tier: "premium", web_exposed: false, copilot_role: true,
    last_probe: {at: "2026-10-05T09:12:00+09:00", ok: true, recommend: "auto", text_ko: "10-05 09:12 · 정상 — 자동으로 물을 수 있습니다"},
    limits: {"in": 8200, out: 6100, date: "2026-10-01", stale: false}};
  routes["GET /api/bridge/manual"] = {open: 1, batches: [{seq: 3, stage: "task_label", stage_ko: "단위업무 이름·과제/역할 고르기", items: 12, items_n: 12,
    in_chars: 8150, state: "open", state_ko: "답 기다림"}]};
  routes["POST /api/bridge/front"] = {ok: true, state: "launched", text_ko: "분석용 Edge 창을 새로 열었습니다 — 그 창에서 회사 계정으로 한 번 로그인해 주세요"};
  routes["POST /api/bridge/manual/import"] = {ok: true, rc: 0, open: 0, committed: 12, retry: 0, rejected: 0,
    results: [{rid: "R2ABCD", stage: "task_label", stage_ko: "단위업무 이름·과제/역할 고르기", status: "ok", status_ko: "반영", ok: 12, retry: 0,
      counts_ko: "반영 12 · 다시 물음 0"}], text_ko: "답 1묶음을 반입했습니다(반영 12 · 다시 물음 0) — 남은 묶음 0개"};
  var c = bootApp(routes, "#analysis");
  return settle().then(function () {
    var cp = text(c.doc.getElementById("card-copilot"));
    assert.ok(cp.indexOf("마지막 탐침: 10-05 09:12 · 정상") >= 0, "마지막 탐침");
    assert.ok(cp.indexOf("보정 한도: 입력 8200자 · 답 6100자(2026-10-01 측정)") >= 0, "보정 한도");
    var mp = text(c.doc.getElementById("card-manual"));
    assert.ok(mp.indexOf("단위업무 이름·과제/역할 고르기") >= 0 && mp.indexOf("답 기다림") >= 0, "단계·상태 이름(코드 아님)");
    var cells = byTag(c.doc.getElementById("card-manual"), "td").map(text);
    assert.ok(cells.indexOf("12") >= 0 && cells.indexOf("8150") >= 0, "항목 수 12(정수 items)·글자 수");
    fire(byAct(c.main, "a-front")[0], "click");
    return settle();
  }).then(function () {
    assert.deepStrictEqual(c.srv.last("POST", "/api/bridge/front").body, {});
    assert.ok(text(c.doc.getElementById("card-copilot")).indexOf("분석용 Edge 창을 새로 열었습니다") >= 0, "서버 문구");
    c.doc.getElementById("mp-answer").value = "```json\n{}\n```";
    fire(byAct(c.main, "a-import")[0], "click");
    return settle();
  }).then(function () {
    var mp = text(c.doc.getElementById("card-manual"));
    assert.ok(mp.indexOf("R2ABCD") >= 0 && mp.indexOf("반영 12 · 다시 물음 0") >= 0, "반입 결과 요청 번호·건수");
  });
});

scenario("머리 띠·홈 타일 — current.json 에 없는 라벨 출처는 이력 줄에서·AI 비어 있음 안내·초과 근무 기준(B7·B16)", function () {
  var routes = baseRoutes(fixture("report_model.json"));
  var runs = routes["GET /api/analysis/runs"];
  runs.current = {run_id: "20261005-101500-3fa2", from: "2026-08-01", to: "2026-09-30", as_of: "2026-09-30T18:00", built_at: "2026-10-05T10:15:00+09:00",
    chosen: "auto", period_source: "default", period_months: 3};
  routes["GET /api/home"].analysis.kpi.ot_basis = "daily8h";
  var c = bootApp(routes, "#home");
  var c2 = null;
  return settle().then(function () {
    var band = text(c.doc.getElementById("lm27-band"));
    assert.ok(band.indexOf("분석 10-05 10:15(자동 선택)") >= 0 && band.indexOf("AI 6 · 규칙 2") >= 0, "띠: 분석 시각 + AI·규칙 수 " + band);
    assert.ok(text(c.doc.getElementById("card-analysis")).indexOf("일 8시간 초과 기준") >= 0, "초과 근무 타일 기준 = mm.overtimeBasis");
    var r2 = baseRoutes(fixture("report_model.json"));
    r2["GET /api/analysis/runs"].current = {run_id: "20261005-101500-3fa2", from: "2026-08-01", to: "2026-09-30", as_of: "2026-09-30T18:00",
      built_at: "2026-10-05T10:15:00+09:00", chosen: "auto", label_sources: {task_label: {ai: 0, manual: 0, rule: 9, user: 0},
        workflow_label: {ai: 0, manual: 0, rule: 3}}};
    c2 = bootApp(r2, "#home");
    return settle();
  }).then(function () {
    var band = text(c2.doc.getElementById("lm27-band"));
    assert.ok(band.indexOf("AI 0 · 규칙 12") >= 0, "서버가 준 라벨 출처(모델 flags.label_sources)");
    assert.ok(band.indexOf("AI 라벨이 절반 넘게 비어 있습니다") >= 0, "AI 비어 있음 안내");
    assert.ok(text(c2.doc.getElementById("card-analysis")).indexOf("근무창 밖 기준") >= 0, "기본 기준 window");
  });
});

scenario("분류 절(앱)·니즈 — 제안 이름표·규칙 조건/결과·미적용 수정·알림·[내 과제로 받기] 폼·[팀에 올리기] 되돌리기(B10·B11·B13)", function () {
  var model = fixture("report_model.json");
  model.agentic.needs[0].dropped = true;
  var routes = baseRoutes(model);
  var hs = routes["GET /api/hier/state"];
  hs.proposals = [{proposal_id: "pr_3", name: "과제C", domain_guess: "MP", units: 2, effort_min: 300, first: "2026-09-01", last: "2026-09-20",
    src: "task_label", src_ko: "AI", state: "pending", state_ko: "검토 대기"},
    {proposal_id: "pr_4", name: "과제D", domain_guess: "DEV", units: 1, effort_min: 60, src: "bootstrap", src_ko: "부트스트랩", state: "mapped",
      state_ko: "팀 과제로 연결됨", mapped_to: "P-0021"}];
  hs.rules = [{rule_id: "LT-0a1b2c3d", kind: "token", kind_ko: "낱말", cond: "'방열' 낱말", result: "과제A", state: "active", state_ko: "켜짐",
    hits: 4, agree: 3, disagree: 1}];
  hs.unapplied = [{id: "c_01", date: "2026-09-02", set_ko: "과제 → 과제A", n_keys: 3}];
  hs.notices = [{text_ko: "제안 '과제D' → 팀 과제 P-0021 로 연결됨"}];
  routes["POST /api/hier/proposal"] = {ok: true, project: "L-0001"};
  routes["POST /api/agentic/need/drop"] = {ok: true, dropped: false, changed: true};
  var c = bootApp(routes, "#report/hier");
  return settle().then(function () {
    var t = text(c.main);
    ["검토 대기", "부트스트랩", "5.0h", "'방열' 낱말", "켜짐", "4 · 3 · 1", "과제 → 과제A", "제안 '과제D' → 팀 과제 P-0021 로 연결됨"].forEach(function (w) {
      assert.ok(t.indexOf(w) >= 0, "분류 절 " + w);
    });
    assert.strictEqual(byAct(c.main, "r-prop", "pr_4|accept").length, 0, "연결된 제안은 처리 버튼 없음");
    fire(byAct(c.main, "r-prop", "pr_3|accept")[0], "click");
    var dr = c.doc.body.all().filter(function (n) { return n.getAttribute("role") === "dialog"; })[0];
    assert.strictEqual(c.doc.getElementById("r-pr-domain").value, "MP", "영역 = 제안의 추정 영역");
    c.doc.getElementById("r-pr-words").value = "방열, 열해석";
    fire(byAct(dr, "r-form-ok")[0], "click");
    return settle();
  }).then(function () {
    assert.deepStrictEqual(c.srv.last("POST", "/api/hier/proposal").body, {proposal_id: "pr_3", action: "accept", domain: "MP", keywords: ["방열", "열해석"]});
    return go(c, "#report/agentic");
  }).then(function () {
    var b = byAct(c.main, "r-need", "n_1a2b3c")[0];
    assert.ok(text(b).indexOf("팀에 올리기") >= 0, "뺀 니즈는 [팀에 올리기]");
    fire(b, "click");
    return settle();
  }).then(function () {
    assert.deepStrictEqual(c.srv.last("POST", "/api/agentic/need/drop").body, {need_id: "n_1a2b3c", drop: false});
    assert.ok(text(c.main).indexOf("이 니즈를 다시 팀에 올립니다") >= 0);
    assert.ok(text(byAct(c.main, "r-need", "n_1a2b3c")[0]).indexOf("팀에 올리지 않기") >= 0, "되돌린 뒤 버튼");
    routes["POST /api/hier/correction"] = {ok: true};
    return go(c, "#report/tree/u_a1a1a1a1a1");
  }).then(function () {
    fire(byAct(c.doc.getElementById("r-panel"), "r-fix", "u_a1a1a1a1a1")[0], "click");
    c.doc.getElementById("r-fix-project").value = "P-0012";
    c.doc.getElementById("r-fix-scope").value = "this";
    var dr = c.doc.body.all().filter(function (n) { return n.getAttribute("role") === "dialog"; })[0];
    fire(byAct(dr, "r-form-ok")[0], "click");
    return settle();
  }).then(function () {
    assert.deepStrictEqual(c.srv.last("POST", "/api/hier/correction").body, {unit_id: "u_a1a1a1a1a1", set: {project: "P-0012"}, scope: "this"},
      "범위 '이 업무만'(서랍을 닫기 전에 읽음)");
  });
});

function runScenarios() {
  var out = {};
  var p = Promise.resolve();
  SCEN.forEach(function (s) {
    p = p.then(function () {
      return Promise.resolve().then(s.fn).then(function () { out[s.name] = {ok: true}; }, function (e) {
        out[s.name] = {ok: false, err: String((e && e.stack) || e).split("\n").slice(0, 6).join("\n")};
      });
    });
  });
  return p.then(function () { return out; });
}

if (require.main === module) {
  process.on("unhandledRejection", function (e) { process.stderr.write("unhandled: " + String(e && e.stack || e) + "\n"); });
  runScenarios().then(function (out) { process.stdout.write(JSON.stringify(out)); });
} else {
  module.exports = function (t) {
    // ───────────── 정적 관문(G-R3~G-R7 · G-R11 · L-19 · L-25 · L-27 · RPT-33·40) ─────────────
    t.test("G-R4·G-R11·G-R6·L-27 — 위험 API·toFixed·</script·ES 모듈 문법 0, node --check 통과", function (c) {
      var banned = [/\binnerHTML\b/, /\bouterHTML\b/, /\binsertAdjacentHTML\b/, /\bdocument\.write/, /(^|[^\w.])eval\s*\(/,
        /\bnew\s+Function\b/, /\bset(Timeout|Interval)\s*\(\s*['"`]/, /\bDOMParser\b/, /\.toFixed\s*\(/];
      APP_FILES.forEach(function (f) {
        var s = readText(f);
        banned.forEach(function (re) { c.assert.ok(!re.test(s), f + " " + re); });
      });
      JS_FILES.forEach(function (f) {
        var s = readText(f);
        c.assert.ok(!/\b(createElement|createElementNS|appendChild|insertBefore|replaceChild|cloneNode)\s*\(/.test(s),
          f + " DOM 은 lm27ui 마운트로만 만든다(WP-36 주의)");
        c.assert.ok(!/<\/(script|style)/i.test(s), f + " </script·</style(인라인 대상)");
        c.assert.ok(!/^\s*(import|export)\s/m.test(s), f + " ES 모듈 문법");
        var r = cp.spawnSync(process.execPath, ["--check", path.join(ROOT, f)], {encoding: "utf8", windowsHide: true, cwd: os.tmpdir()});
        c.assert.strictEqual(r.status, 0, f + " node --check: " + r.stderr);
      });
    });

    t.test("G-R5·G-R7·L-21·L-15·L-13·L-25 — 외부 참조·16진 색·사설 IP·작업 이름·사유 코드·영역 이름 리터럴", function (c) {
      var contract = readText("docs/CONTRACT.md");
      var codes = {};
      (contract.match(/R-[A-Z]{2,}(?:-[A-Z0-9]+)*/g) || []).forEach(function (x) { codes[x] = true; });
      var domLine = (contract.split("\n").filter(function (l) { return l.indexOf("| 업무 영역 |") === 0; })[0]) || "";
      var names = [];
      domLine.replace(/`[A-Z]{2,3}` ([^·|`]+)/g, function (m, nm) { names.push(nm.replace(/\(.*?\)/g, "").trim()); });
      c.assert.ok(names.length >= 6, "계약 §6.6 영역 이름");
      APP_FILES.forEach(function (f) {
        var s = readText(f);
        var hex = /(^|[^&\w])#([0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})(?![\w-])/;
        c.assert.ok(!hex.test(s), f + " 16진 색");
        (s.match(/https?:\/\/[^\s"')]+/g) || []).forEach(function (u) {
          c.assert.ok(/^http:\/\/www\.w3\.org\//.test(u) || /^http:\/\/127\.0\.0\.1:/.test(u), f + " 외부 참조 " + u);
        });
        c.assert.ok(!/(src|href)\s*=\s*["'](https?:)?\/\//i.test(s), f + " 원격 src·href");
        c.assert.ok(!/(?<![\d.])(10\.\d{1,3}\.\d{1,3}\.\d{1,3}|172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3})(?!\d)/.test(s), f + " 사설 IP");
        c.assert.ok(!/(?<![\w-])LM27-(?![$({<[`'"\s]|$)[A-Za-z0-9]/.test(s), f + " 고정 작업·앱 이름");
        (s.match(/(?<![A-Za-z0-9_-])R-[A-Z]{2,}(?:-[A-Z0-9]+)*(?![A-Za-z0-9_])/g) || []).forEach(function (x) { c.assert.ok(codes[x], f + " 계약 §6.1 밖 사유 코드 " + x); });
        if (/\.js$/.test(f)) {
          (s.match(/["']([^"'\n]{1,20})["']/g) || []).forEach(function (q) {
            c.assert.ok(names.indexOf(q.slice(1, -1).trim()) < 0, f + " 영역 이름 리터럴 " + q);
          });
        }
      });
    });

    t.test("RPT-33·RPT-40 — 금지 표현·[!] 0(정적 — 성공 경로의 '오류'는 아래 화면 시나리오가 그린 글자로 본다)", function (c) {
      APP_FILES.forEach(function (f) {
        var s = readText(f);
        ["대체 가능", "절감", "AX 가능 MM", "개발자에게", "재설치", "[!]"].forEach(function (w) { c.assert.ok(s.indexOf(w) < 0, f + " '" + w + "'"); });
      });
    });

    t.test("index.html — 정적 고정 사전·CSP(인라인 스크립트·스타일·on* 0)·랜드마크·토큰 자리·아이콘 = icons.svg", function (c) {
      var A = c.assert;
      var s = readText("web/app/index.html");
      A.ok(/^<!doctype html>\n<html lang="ko">/.test(s), "doctype·lang");
      A.ok(s.indexOf("<meta name=\"color-scheme\" content=\"light\">") >= 0);
      A.ok(s.indexOf("<meta name=\"lm27-ui-token\" content=\"…\">") >= 0, "토큰 자리표시자(R §2.3.3 형 그대로)");
      var scripts = s.match(/<script\b[^>]*>/g) || [];
      A.deepStrictEqual(scripts, ["<script src=\"/static/lm27ui.js\">", "<script src=\"/static/lm27charts.js\">", "<script src=\"/static/report.js\">",
        "<script src=\"/static/app.js\">"], "스크립트 = 고정 사전, 인라인 0");
      A.ok(/<link rel="stylesheet" href="\/static\/lm27\.css">/.test(s));
      A.ok(!/<style\b|\sstyle=|\son[a-z]+=/i.test(s), "인라인 스타일·이벤트 속성 0");
      A.ok(/<header class="app-head" id="lm27-head">/.test(s) && /<main id="app" tabindex="-1">/.test(s), "랜드마크");
      var nav = /<nav class="pills" aria-label="주 메뉴">([\s\S]*?)<\/nav>/.exec(s);
      A.ok(nav, "주 메뉴");
      A.deepStrictEqual((nav[1].match(/href="#[a-z]+"/g) || []), ["href=\"#home\"", "href=\"#collect\"", "href=\"#analysis\"", "href=\"#report\"",
        "href=\"#team\"", "href=\"#settings\""]);
      // LM24 틀: 머리(제품 이름 + 작은 글자) → 단계 줄 → 한 줄 설명 → 기간 카드 → 보기 탭 → 본문 → 아래 상태 줄(순서 그대로)
      A.ok(/<h1>LoadMonitor27<small id="lm27-ver">/.test(s), "머리 작은 글자(판·주소·로컬 전용)");
      var steps = /<nav class="steps" id="lm27-steps" aria-label="진행 단계">([\s\S]*?)<\/nav>/.exec(s);
      A.ok(steps, "단계 줄");
      A.deepStrictEqual(steps[1].match(/href="#[a-z]+"/g), ["href=\"#collect\"", "href=\"#analysis\"", "href=\"#report\"", "href=\"#team\""]);
      var order = ["id=\"lm27-head\"", "id=\"lm27-steps\"", "id=\"lm27-intro\"", "id=\"lm27-period\"", "id=\"lm27-nav\"", "id=\"lm27-band\"",
        "id=\"lm27-alerts\"", "<main id=\"app\"", "id=\"lm27-sbar\""].map(function (k) { return s.indexOf(k); });
      A.ok(order.every(function (v, i) { return v > 0 && (i === 0 || v > order[i - 1]); }), "틀 순서 " + order.join(","));
      A.ok(/<section class="card period-card" id="lm27-period" aria-label="[^"]+"><\/section>/.test(s), "기간 카드 자리(app.js 가 채움)");
      A.ok(/<footer class="sbar" id="lm27-sbar" aria-label="상태 표시줄">/.test(s), "아래 상태 줄");
      var icons = readText("web/common/icons.svg").match(/<symbol id="i-[a-z-]+"[^\n]*?<\/symbol>/g);
      var inl = s.match(/<symbol id="i-[a-z-]+"[^\n]*?<\/symbol>/g);
      A.strictEqual(icons.length, 25);
      A.deepStrictEqual(inl, icons, "인라인 아이콘이 icons.svg 와 같은 바이트");
      var raw = fs.readFileSync(path.join(ROOT, "web/app/index.html"));
      A.ok(raw[0] !== 0xEF && raw.indexOf(13) < 0, "UTF-8 BOM 없음 · LF");
    });

    // ───────────── 순수 함수 ─────────────
    t.test("RPT-04 머리 띠·기간 출처·해시 경로·조사·응답 선택지 표(계약 §6.3)", function (c) {
      var A = c.assert;
      var R = mods().R;
      var b = R.bandParts({from: "2026-07-01", to: "2026-09-30", as_of: "2026-09-30T18:00", built_at: "2026-10-05T10:15:00+09:00", chosen: "auto",
        period_source: "default", period_months: 3, label_sources: {task_label: {ai: 112, manual: 0, rule: 8}}});
      A.strictEqual(b.text, "기간 2026-07-01 ~ 2026-09-30 · 기준 09-30 18:00 · 분석 10-05 10:15(자동 선택) · 기간 출처: 기본값(최근 3개월) · AI 112 · 규칙 8");
      A.strictEqual(b.ruleHeavy, false);
      A.strictEqual(R.bandParts({label_sources: {x: {ai: 1, rule: 3}}}).ruleHeavy, true, "규칙 50% 초과 안내");
      // 자동/직접 선택은 현재 결과일 때만 온다 — 없으면 괄호를 달지 않는다(통합 — W2 C01)
      A.strictEqual(R.bandParts({built_at: "2026-10-05T10:15:00+09:00"}).text, "분석 10-05 10:15");
      A.strictEqual(R.bandParts({built_at: "2026-10-05T10:15:00+09:00", chosen: "explicit"}).text, "분석 10-05 10:15(직접 선택)");
      A.strictEqual(R.periodSourceText("this_month"), "이번 달");
      A.strictEqual(R.periodSourceText("nope"), null);
      A.deepStrictEqual(R.parseRoute("#report/evidence/2026-09-22"), {section: "evidence", arg: "2026-09-22"});
      A.deepStrictEqual(R.parseRoute("#report"), {section: "summary", arg: null});
      A.deepStrictEqual(R.parseRoute("#report/tree/u%3Au_a1a1a1a1a1"), {section: "tree", arg: "u:u_a1a1a1a1a1"});
      A.deepStrictEqual(R.parseRoute("#home"), {section: null, arg: null});
      A.strictEqual(R.josa("표 계산", "을", "를"), "표 계산을");
      A.strictEqual(R.josa("회의", "을", "를"), "회의를");
      var sec63 = readText("docs/CONTRACT.md").split("### 6.3")[1].split("### 6.4")[0];
      var codes = (sec63.match(/\b[QH]\d\d\b/g) || []).filter(function (x, i, a) { return a.indexOf(x) === i; }).sort();
      A.strictEqual(codes.length, 24);
      A.deepStrictEqual(Object.keys(R.QA).sort(), codes, "응답 선택지 = Q01~Q18·H01~H06");
      A.deepStrictEqual(Object.keys(R.Q_NAME).sort(), codes);
    });

    t.test("KB-9 응답 폼 검사(readAnswer) — 칸별 오류·정상 응답 형", function (c) {
      var A = c.assert;
      var R = mods().R;
      var X = R.idx(fixture("report_model.json"));
      function get(vals) { return function (id) { return vals[id] === undefined ? "" : vals[id]; }; }
      var q1 = {qid: "q1", code: "Q01", target: "u_d4d4d4d4d4"};
      A.deepStrictEqual(R.readAnswer(X, q1, null, get({})), {errs: {choice: "응답을 고르세요"}});
      A.deepStrictEqual(Object.keys(R.readAnswer(X, q1, "instr", get({})).errs).sort(), ["d", "t"]);
      A.deepStrictEqual(R.readAnswer(X, q1, "instr", get({"q-q1-d": "2026-09-12", "q-q1-t": "10:00"})), {answer: {choice: "instr", d: "2026-09-12", at: "2026-09-12T10:00"}});
      A.ok(R.readAnswer(X, q1, "must_link", get({"q-q1-unit": "u_zzzzzzzzzz"})).errs.unit, "없는 업무 거부");
      A.deepStrictEqual(R.readAnswer(X, q1, "must_link", get({"q-q1-unit": "u_a1a1a1a1a1"})), {answer: {choice: "must_link", unit: "u_a1a1a1a1a1"}});
      var q9 = {qid: "q9", code: "Q09"};
      A.ok(R.readAnswer(X, q9, "work", get({"q-q9-hours": "0.3"})).errs.hours, "0.25 단위");
      A.deepStrictEqual(R.readAnswer(X, q9, "work", get({"q-q9-hours": "1.25"})), {answer: {choice: "work", hours: 1.25}});
      A.deepStrictEqual(R.readAnswer(X, q9, "absence", get({})), {answer: {choice: "absence"}});
      var q5 = {qid: "q5", code: "Q05"};
      A.ok(R.readAnswer(X, q5, "offsite", get({"q-q5-d": "2026-09-01", "q-q5-a": "13:00", "q-q5-b": "12:00"})).errs.b, "끝 ≤ 시작 거부");
      var q11 = {qid: "q11", code: "Q11"};
      A.deepStrictEqual(R.readAnswer(X, q11, "work", get({})), {answer: {choice: "work"}}, "선택 사항 시간");
    });

    t.test("결정성·RPT-13·RPT-21 — 같은 모델 = 같은 가상 노드, 근무 중 미분류 행 5개, 추정·미분류 무늬", function (c) {
      var A = c.assert;
      var M = mods();
      var model = fixture("report_model.json");
      function st(sec) {
        var s = {section: sec, arg: null, month: "2026-09", ui: {}, open: {}, tables: {}, sort: {}, limit: {}, treeOpen: {}, treeSel: null, treeFocus: null,
          gcol: {}, rels: {}, drill: {}, q: {}, qerr: {}, answered: {}, needDrop: {}, hier: null, msg: null, ev: null};
        return s;
      }
      var env = {mode: "file", variant: "full", canWrite: false, width: 1000};
      M.R.SECTIONS.forEach(function (s) {
        var a = M.C.toString({t: "div", a: {}, c: M.R.view(model, st(s[0]), env)});
        var b = M.C.toString({t: "div", a: {}, c: M.R.view(clone(model), st(s[0]), env)});
        A.strictEqual(a, b, s[0] + " 결정성");
      });
      var tree = M.C.toString({t: "div", a: {}, c: M.R.view(model, st("tree"), env)});
      ["근무 중 미분류", "일반 앱", "소통", "회의", "PC 밖", "미상"].forEach(function (w) { A.ok(tree.indexOf(w) >= 0, "트리 " + w); });
      A.ok(tree.indexOf("url(#hatch-est)") >= 0, "관측/추정 막대 빗금");
      A.ok(tree.indexOf("stroke-dasharray=\"2 2\"") >= 0, "미분류 칸 점선 테두리");
      A.ok(tree.indexOf("관련 미귀속 회의 1.5h(MM 미포함)") >= 0, "RPT-13 B_MEET 주석만");
      var sum = M.C.toString({t: "div", a: {}, c: M.R.view(model, st("summary"), env)});
      A.ok(sum.indexOf("2026-09 투입의 55%가 개발 프로젝트였습니다.") >= 0, "한 줄 요약");
      A.ok(sum.indexOf("팀즈 기록이 비어 있는 근무일이 있습니다(80%).") >= 0, "품질 사유 문구");
    });

    t.test("역할 워크플로우 규칙 문장(§6.3.3)·연관 그래프 범위(§4.6.4)", function (c) {
      var A = c.assert;
      var R = mods().R;
      var model = fixture("report_model.json");
      A.deepStrictEqual(R.roleSentences(model.workflows.roles.r_5c0d11), ["회로 해석 작업이 이 역할 투입의 56%로 가장 큽니다.",
        "회로 해석을 마치고 결과 정리를 시작하기까지 보통 1.5영업일을 기다립니다.", "1건의 단위업무에서 결과 정리를 하다가 회로 해석으로 되돌아갔습니다."]);
      A.deepStrictEqual(R.roleSentences(model.workflows.roles.r_7a2b33), ["단위업무가 1건뿐이라 병목은 판단하지 않았습니다."]);
      var g = R.graphSpec(model.ontology, "P-0007", {}, 12);
      A.strictEqual(g.spec.nodes.length, 10);
      var off = R.graphSpec(model.ontology, "P-0007", {"사용함": true}, 12);
      A.ok(off.spec.edges.every(function (e) { return e.rel !== "사용함"; }), "관계 거르개");
      A.ok(off.spec.nodes.every(function (n) { return n.id !== "a_1"; }), "끊긴 바깥 노드 제외");
      A.strictEqual(R.graphSpec(model.ontology, "P-0007", {}, 1).hidden, 2, "바깥 노드 상위 n");
      A.strictEqual(R.graphSpec(model.ontology, "P-9999", {}, 12), null);
    });

    // ───────────── 실제 보고서 모델 모양(lm27\report\model.py 가 내는 형) ─────────────
    function realState(sec, extra) {
      var s = {section: sec, arg: null, month: "2026-09", ui: {}, open: {}, tables: {}, sort: {}, limit: {}, treeOpen: {}, treeSel: null,
        treeFocus: null, gcol: {}, rels: {}, drill: {}, q: {}, qerr: {}, answered: {}, needDrop: {}, hier: null, msg: null, ev: null};
      Object.keys(extra || {}).forEach(function (k) { s[k] = extra[k]; });
      return s;
    }

    function realModel() {
      var m = fixture("report_model.json");
      var rv = m.reviews.months.filter(function (r) { return r.key === "2026-09"; })[0];
      rv.facts = [["F1", "완료", "전원부 검증", "P-0007", "해석·분석"]];          // 모델: 사실 행 = 배열 + fact_units
      rv.fact_units = {F1: "u_a1a1a1a1a1"};
      rv.edges = [["E1", "동료1", "의뢰함", "전원부 검증"], ["E2", "전원부 검증", "산출함", "표 계산 문서"]];
      rv.edge_refs = {E1: {from: "c:3", to: "u_a1a1a1a1a1", rel: "의뢰함"}, E2: {from: "u_a1a1a1a1a1", to: "d:9", rel: "산출함"}};
      rv.ai = {summary: "동료1 의뢰로 전원부 검증을 끝냈습니다.", by: "ai", peers_map: {"동료1": 3},
        highlights: [{text: "동료1 의뢰 건을 마쳤습니다.", refs: ["F1"], units: ["u_a1a1a1a1a1"], effort_min: 390, biz_lead_min: 1440}],
        relations: [{text: "동료1 의 의뢰가 보고로 이어졌습니다.", refs: ["E1"]}], next: ["동료1 과 다음 단계를 맞춥니다."]};
      rv.ot_units = {basis: "window", total_min: 150, units: [{unit_id: "u_d4d4d4d4d4", min: 120}], unattributed_min: 30};
      delete rv.ot_unattr_min;
      m.refs.docs = {"9": {key: "d" + "9".repeat(16), name: "검증결과.xlsx"}};
      return m;
    }

    t.test("실제 모델 모양 — 관계 간선·하이라이트 숫자·동료 번호표(전체판만)·초과 근무 원인(B1·B2·B3)", function (c) {
      var A = c.assert;
      var M = mods();
      var m = realModel();
      var st = realState("review", {open: {"rv:2026-09": true}});
      var full = M.C.toString({t: "div", a: {}, c: M.R.view(m, st, {mode: "file", variant: "full", canWrite: false, width: 1000})});
      A.ok(full.indexOf("[object Object]") < 0, "관계가 [object Object] 로 나오지 않는다");
      A.ok(full.indexOf("김철수 의뢰로 전원부 검증을 끝냈습니다.") >= 0, "요약의 동료1 → 사람 이름");
      A.ok(full.indexOf("김철수 의뢰 건을 마쳤습니다. (투입 6.5h · 리드 3.0영업일)") >= 0, "하이라이트 끝 숫자(모델 effort_min·biz_lead_min)");
      A.ok(full.indexOf("김철수 의 의뢰가 보고로 이어졌습니다.") >= 0 && full.indexOf("김철수 → 의뢰함 → 전원부 검증") >= 0, "관계 문장 + 근거 간선");
      A.ok(full.indexOf("김철수 과 다음 단계를 맞춥니다.") >= 0, "다음 문장도 이름");
      A.ok(full.indexOf("회로 해석 보고") >= 0 && full.indexOf("업무에 묶이지 않은 초과 0.5h") >= 0, "초과 근무 원인(모델 객체 모양)");
      var red = M.C.toString({t: "div", a: {}, c: M.R.view(m, realState("review", {open: {"rv:2026-09": true}}), {mode: "file", variant: "redacted", canWrite: false, width: 1000})});
      A.ok(red.indexOf("동료1 의뢰로 전원부 검증을 끝냈습니다.") >= 0 && red.indexOf("김철수 의뢰로") < 0, "가림판은 번호표를 이름으로 바꾸지 않는다");
      m.reviews.months.filter(function (r) { return r.key === "2026-09"; })[0].ai.relations = [];
      var rule = M.C.toString({t: "div", a: {}, c: M.R.view(m, realState("review", {open: {"rv:2026-09": true}}), {mode: "file", variant: "full", canWrite: false, width: 1000})});
      A.ok(rule.indexOf("전원부 검증 → 산출함 → 검증결과.xlsx") >= 0, "AI 관계 문장이 없으면 그 달 관계 목록(전체판 문서 이름)");
    });

    t.test("실제 모델 모양 — 신뢰도 사유(기간 전체 texts)·[왜?] 과제 후보·니즈 입출력·미확인 동료·AI 분류 비율·과제 패널(B4·B5·B8·B9·B17)", function (c) {
      var A = c.assert;
      var M = mods();
      var env = {mode: "file", variant: "full", canWrite: false, width: 1000};
      function txt(m, st) { return M.C.toString({t: "div", a: {}, c: M.R.view(m, st, env)}); }
      var m = realModel();
      delete m.quality.cov;                                            // 기간 전체 quality 에는 cov·est_ratio 가 없다 — texts 만
      delete m.quality.est_ratio;
      m.quality.texts = [{code: "teams_cov_low", text: "팀즈 기록이 비어 있는 근무일이 있습니다(80%)"}];
      var sum = txt(m, realState("summary", {month: "all", ui: {quality: "1"}}));
      A.ok(sum.indexOf("팀즈 기록이 비어 있는 근무일이 있습니다(80%)") >= 0 && sum.indexOf("(—)") < 0, "기간 전체 사유 숫자");
      m.units[0].cands = [["P-0007", 0.82], ["P-0012", 0.4]];
      var why = txt(m, realState("tree", {treeSel: "u:u_a1a1a1a1a1", treeOpen: {"r:DEV/P-0007/r_5c0d11": true}, ui: {why: "u_a1a1a1a1a1"}}));
      A.ok(why.indexOf("과제 후보: 과제A 0.82 · 과제B 0.40") >= 0, "[왜?] 과제 후보([과제, 점수] 배열)");
      m.agentic.needs = [{need_id: "n_1a2b3c", name: "해석 결과 정리 자동화", logic: "표로 정리", "in": "디지털 입력", out: "정형 출력",
        step_type: "APP_CAE", freq_per_month: 4.3, grade: "중", by: "rule", units: ["u_a1a1a1a1a1"], dropped: false}];
      A.ok(txt(m, realState("agentic")).indexOf("디지털 입력 → 정형 출력") >= 0, "니즈 입력 → 출력(in·out)");
      // 로컬 카탈로그(V13)를 못 썼거나 고쳐 읽은 까닭 — 있으면 그 문구(통합 — W2 L04)
      var agNote = "config\\agentic_tasks.json 의 JSON 형식이 깨졌습니다";
      m.agentic.catalog_note = agNote;
      A.ok(txt(m, realState("agentic")).indexOf(agNote) >= 0, "카탈로그가 있을 때도 로컬 카탈로그 경고");
      var m0 = realModel();
      m0.agentic.catalog_n = 0; m0.agentic.matches = []; m0.agentic.catalog = [];
      A.ok(txt(m0, realState("agentic")).indexOf("팀 레지스트리를 받으면 채워집니다") >= 0, "카탈로그 없음 기본 안내");
      m0.agentic.catalog_note = agNote;
      var t0 = txt(m0, realState("agentic"));
      A.ok(t0.indexOf("에이전트 목록이 없습니다 — " + agNote) >= 0 && t0.indexOf("팀 레지스트리를 받으면") < 0, "로컬 카탈로그 문제면 그 까닭");
      delete m.agentic.catalog_note;
      m.peers.internal[1].internal = null;                            // 모델: 사람 사전에서 사내로 확인 = true, 모름 = null
      m.refs.people["7"].internal = null;
      m.peers.internal[0].internal = true;
      var peers = txt(m, realState("peers"));
      A.ok(peers.indexOf("미확인") >= 0 && peers.indexOf("사내") >= 0, "사람 사전에 없는 동료는 미확인");
      m.flags.hier = {ai_share: 0.4};
      A.ok(txt(m, realState("hier")).indexOf("AI 분류 비율 40%") >= 0, "분류 절 AI 비율(flags.hier.ai_share)");
      m.workflows.projects["P-0007"] = {key: "P-0007", handoffs: [{from_role: "r_5c0d11", to_role: "r_7a2b33", n: 2, gap_biz_median_min: 480,
        via: {doc: 1, peer: 0}}], roles: [{role_id: "r_5c0d11", effort_min: 600, share: 0.8}, {role_id: "r_7a2b33", effort_min: 150, share: 0.2}]};
      var pn = txt(m, realState("tree", {treeSel: "p:DEV/P-0007"}));
      A.ok(pn.indexOf("회로 · 해석·분석 → 기구 · 설계") >= 0 && pn.indexOf("2회") >= 0, "역할 간 인계(from_role·to_role)");
      A.ok(pn.indexOf("역할 구성 자료가 없습니다") < 0 && pn.indexOf("10.0h") >= 0, "역할 구성(roles[].effort_min)");
    });

    // ───────────── 비동기 화면 시나리오(자식 node) ─────────────
    var cache = null;
    function results() {
      if (cache) { return cache; }
      var r = cp.spawnSync(process.execPath, [__filename], {encoding: "utf8", windowsHide: true, cwd: os.tmpdir(), timeout: 180000,
        maxBuffer: 1 << 24});
      try {
        cache = JSON.parse(r.stdout);
      } catch (e) {
        cache = {_error: "자식 node 실패(rc " + r.status + "): " + String(r.stderr).slice(0, 2000)};
      }
      return cache;
    }
    SCEN.forEach(function (s) {
      t.test(s.name, function () {
        var res = results();
        if (res._error) { throw new Error(res._error); }
        var x = res[s.name];
        if (!x) { throw new Error("시나리오 결과 없음"); }
        if (!x.ok) { throw new Error(x.err); }
      });
    });
  };
}
