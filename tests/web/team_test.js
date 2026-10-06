/*
 * WP-37 시험 — web\team\team.js(팀 대시보드 · 자기완결 팀 보고서 · 관리 화면).
 * 명세 시험: RPT-44(공유판 열 없음 · 피벗 전후 막대 집합 같음 · 측정 불충분 빗금·비교 제외) · RPT-45(같은 역할 2명 — A 의 막대 =
 *            A 의 워크플로우, 자기완결 details 섬·대시보드 API 둘 다) · RPT-50(관리: 동시 저장 409 → 최신 판 재적용 ·
 *            근거 없는 공휴일 저장 거부 · P-9903 reserved_id) · TAB-S06(악성 라벨은 글자로만) · G-R4(마운트만).
 * 자료: tests\fixtures\wp37\team8.json(합성 — teamdata.py 가 만든 것). DOM 은 아래 작은 가짜 문서, fetch 는 동기 가짜.
 */
"use strict";
var fs = require("fs");
var os = require("os");
var path = require("path");
var cp = require("child_process");

module.exports = function (t) {
  var ROOT = path.resolve(__dirname, "..", "..");
  var T = require(path.join(ROOT, "web", "team", "team.js"));
  var C = require(path.join(ROOT, "web", "common", "lm27charts.js"));
  var U = require(path.join(ROOT, "web", "common", "lm27ui.js"));
  var FIX = JSON.parse(fs.readFileSync(path.join(ROOT, "tests", "fixtures", "wp37", "team8.json"), "utf8"));
  var EVIL = "</" + "script><" + "!--<" + "script>";
  var RID_A = "r_3d3d8e";                                         // P-0007 · 회로 · 설계 — 팀원A(i 0)·팀원B(i 1) 공통

  function copy(v) { return JSON.parse(JSON.stringify(v)); }
  function vstr(v) { return Array.isArray(v) ? v.map(C.toString).join("") : C.toString(v); }

  // ───────────── 작은 가짜 문서 ─────────────
  function FakeNode(doc, type, tag, ns) {
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
    this.value = "";
    this.checked = false;
    this.offsetWidth = 100;
    this.offsetHeight = 40;
  }
  FakeNode.prototype = {
    get firstChild() { return this.childNodes[0] || null; },
    get isConnected() { var n = this; while (n.parentNode) { n = n.parentNode; } return n === this.ownerDocument.root; },
    get textContent() {
      if (this.nodeType === 3) { return this.data; }
      return this.childNodes.map(function (c) { return c.textContent; }).join("");
    },
    set textContent(v) { this.childNodes = []; this.appendChild(this.ownerDocument.createTextNode(v)); },
    appendChild: function (c) { if (c.parentNode) { c.parentNode.removeChild(c); } c.parentNode = this; this.childNodes.push(c); return c; },
    removeChild: function (c) { var i = this.childNodes.indexOf(c); if (i >= 0) { this.childNodes.splice(i, 1); c.parentNode = null; } return c; },
    setAttribute: function (k, v) { this.attrs[k] = String(v); if (k === "value") { this.value = String(v); } if (k === "checked") { this.checked = true; } },
    getAttribute: function (k) { return Object.prototype.hasOwnProperty.call(this.attrs, k) ? this.attrs[k] : null; },
    hasAttribute: function (k) { return Object.prototype.hasOwnProperty.call(this.attrs, k); },
    removeAttribute: function (k) { delete this.attrs[k]; },
    contains: function (n) { while (n) { if (n === this) { return true; } n = n.parentNode; } return false; },
    addEventListener: function (ev, fn) { (this.listeners[ev] = this.listeners[ev] || []).push(fn); },
    removeEventListener: function (ev, fn) { var l = this.listeners[ev] || []; var i = l.indexOf(fn); if (i >= 0) { l.splice(i, 1); } },
    focus: function () { this.ownerDocument.activeElement = this; },
    click: function () {},
    getBoundingClientRect: function () { return {left: 10, top: 100, right: 60, bottom: 120, width: 50, height: 20}; },
    all: function (out) { out = out || []; this.childNodes.forEach(function (c) { if (c.nodeType === 1) { out.push(c); c.all(out); } }); return out; },
    querySelectorAll: function (sel) {
      var m = /^\[([a-z0-9-]+)\]$/.exec(sel);
      var m2 = /^([a-z]+)\.([a-z0-9-]+)$/.exec(sel);
      return this.all().filter(function (n) {
        if (m) { return n.hasAttribute(m[1]); }
        if (m2) { return n.tagName === m2[1] && (n.getAttribute("class") || "").split(" ").indexOf(m2[2]) >= 0; }
        return n.tagName === sel;
      });
    }
  };
  function FakeDoc() {
    this.root = new FakeNode(this, 9, "#document");
    this.body = new FakeNode(this, 1, "body");
    this.root.appendChild(this.body);
    this.activeElement = this.body;
    this.documentElement = {clientWidth: 1280};
    this.defaultView = {pageXOffset: 0, pageYOffset: 0};
    this.readyState = "complete";
  }
  FakeDoc.prototype = {
    createElement: function (tag) { return new FakeNode(this, 1, tag, "http://www.w3.org/1999/xhtml"); },
    createElementNS: function (ns, tag) { return new FakeNode(this, 1, tag, ns); },
    createTextNode: function (s) { var n = new FakeNode(this, 3, "#text"); n.data = String(s); return n; },
    getElementById: function (id) { var a = this.root.all(); for (var i = 0; i < a.length; i++) { if (a[i].getAttribute("id") === id) { return a[i]; } } return null; },
    addEventListener: function () {}
  };
  function el(doc, parent, tag, attrs) {
    var n = doc.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) { n.setAttribute(k, attrs[k]); });
    parent.appendChild(n);
    return n;
  }
  // 셸(index.html·보고서 껍데기와 같은 id) + 선택적 섬
  function page(kind, variant, td, details) {
    var doc = new FakeDoc();
    doc.body.setAttribute("data-kind", kind);
    if (variant) { doc.body.setAttribute("data-variant", variant); }
    var rootEl = el(doc, doc.body, "div", {id: "team-root"});
    el(doc, rootEl, "header", {id: "team-head"});
    el(doc, rootEl, "div", {id: "team-nav"});
    el(doc, rootEl, "main", {id: "app"});
    if (td) {
      el(doc, doc.body, "script", {type: "application/json", id: "lm27-data"}).textContent = JSON.stringify(td);
      el(doc, doc.body, "script", {type: "application/json", id: "lm27-detail"}).textContent = JSON.stringify(details || {});
    }
    return doc;
  }
  function fire(target, type, extra) {
    var ev = {type: type, target: target, defaultPrevented: false, preventDefault: function () { this.defaultPrevented = true; }};
    Object.keys(extra || {}).forEach(function (k) { ev[k] = extra[k]; });
    for (var n = target; n; n = n.parentNode) { (n.listeners[type] || []).slice().forEach(function (fn) { fn(ev); }); }
    return ev;
  }
  function byAct(scope, act, ref) {
    return scope.querySelectorAll("[data-act]").filter(function (n) {
      return n.getAttribute("data-act") === act && (ref === undefined || n.getAttribute("data-ref") === ref);
    });
  }
  function textNodes(n, out) {
    out = out || [];
    n.childNodes.forEach(function (c) { if (c.nodeType === 3) { out.push(c.data); } else { textNodes(c, out); } });
    return out;
  }
  function drawerOf(doc) {
    return doc.body.all().filter(function (n) { return n.getAttribute("role") === "dialog"; })[0] || null;
  }
  // 브라우저 환경 가짜: location.hash · history.back(→ hashchange) · 창(hashchange 수신기)
  function fakeEnv(extra) {
    var env = {hashes: [""], listeners: [], backs: 0};
    env.location = {
      get hash() { return env.hashes[env.hashes.length - 1]; },
      set hash(v) { env.hashes.push(v.charAt(0) === "#" ? v : "#" + v); env.fireHash(); },
      href: "http://127.0.0.1:19390/",
      replace: function (u) { env.hashes[env.hashes.length - 1] = u.slice(u.indexOf("#")); env.fireHash(); }
    };
    env.history = {back: function () { env.backs++; if (env.hashes.length > 1) { env.hashes.pop(); } env.fireHash(); }};
    env.win = {addEventListener: function (ev, fn) { if (ev === "hashchange") { env.listeners.push(fn); } }};
    env.fireHash = function () { env.listeners.slice().forEach(function (fn) { fn(); }); };
    Object.keys(extra || {}).forEach(function (k) { env[k] = extra[k]; });
    return env;
  }
  // 동기 가짜 Promise(러너가 동기라서) — then(ok) 만
  function SP(v) { this.v = v; }
  SP.prototype.then = function (ok) { var r = ok ? ok(this.v) : this.v; return r && typeof r.then === "function" ? r : new SP(r); };
  function fakeFetch(routes, log) {
    return function (url, init) {
      log.push({url: url, method: (init && init.method) || "GET", body: init && init.body, headers: (init && init.headers) || {}});
      var hit = routes(url, init || {});
      var text = hit.body === undefined ? "" : JSON.stringify(hit.body);
      return new SP({status: hit.status, text: function () { return new SP(text); }});
    };
  }

  // ───────────── 계산(순수) ─────────────
  t.test("KPI·영역 × 사람·과제 표(작은 과제 접기)·사람별 월 — 합성 8명", function (c) {
    var A = c.assert;
    var M = T.model(FIX.td, FIX.details, {});
    var k = T.kpis(M);
    A.deepStrictEqual(k.map(function (x) { return x.id; }), ["people", "mm", "ot", "domains", "units", "quality"]);
    A.strictEqual(k[0].value, "8명");
    A.strictEqual(k[0].sub, "신뢰 6 · 주의 1 · 측정 불충분 1");
    A.strictEqual(k[1].value, U.fmtNum(T.teamTotals(M).mm, 2) + " MM");
    A.ok(/^이번 달\(2026-09\) /.test(k[1].sub), k[1].sub);
    A.strictEqual(k[5].value, "6/8 신뢰");
    var dp = T.domainPerson(M);
    A.deepStrictEqual(dp.cols.map(function (x) { return x.weak; }), [false, false, false, false, false, false, false, true]);
    A.deepStrictEqual(dp.rows.map(function (r) { return r.key; }), ["DEV", "MP", "EXT", "COM", "_un"]);
    var pt = T.projectTable(M);
    A.strictEqual(pt.small.length, 0);                              // view 가 없으면 접지 않는다(설정 없이 기본값을 만들지 않음)
    M.view = {small_project_mm: 0.3, gantt_expand_rows: 150};
    pt = T.projectTable(M);
    A.deepStrictEqual(pt.small.map(function (p) { return p.key; }), ["0|pr_1", "P-0011"]);
    var pm = T.peopleMonths(M);
    A.strictEqual(pm.full, true);
    A.strictEqual(pm.weakRows.length, 3);                            // 측정 불충분 1명 × 3개월 — 비교 표에서 빠짐
    A.ok(pm.rows.every(function (r) { return r.i !== 7; }));
  });

  t.test("표시 비율 = 파이썬 pct_share_text · 칸 농도 6구간 · 해시 해석 · 기본 펼침", function (c) {
    var A = c.assert;
    A.strictEqual(T.pctShare(0.6234, 1), "62%");
    A.strictEqual(T.pctShare(0.004, 1), "0.4%");
    A.strictEqual(T.pctShare(0, 1), "0%");
    A.strictEqual(T.pctShare(1, 0), "—");
    [[0, 10, 0], [2, 10, 1], [2.0001, 10, 2], [4, 10, 2], [6, 10, 3], [8, 10, 4], [8.1, 10, 5], [10, 10, 5]].forEach(function (x) {
      A.strictEqual(T.heatLevel(x[0], x[1]), x[2], x.join("/"));
    });
    A.deepStrictEqual(T.parseHash("#gantt/3/r_00ab12"), {section: "gantt", drawer: "3|r_00ab12"});
    A.deepStrictEqual(T.parseHash("#people"), {section: "people", drawer: null});
    A.deepStrictEqual(T.parseHash("#nope"), {section: "summary", drawer: null});
    A.deepStrictEqual(T.parseHash("#gantt/1/r_zz"), {section: "summary", drawer: null});
    var rows = T.ganttRows(T.model(FIX.td, {}, {}), false);
    A.deepStrictEqual(T.defaultCollapsed(rows, rows.length), {});
    var col = T.defaultCollapsed(rows, 10);
    A.ok(Object.keys(col).length > 0);
    rows.forEach(function (r) { A.strictEqual(!!col[r.key], !!(r.group && r.level >= 1), r.key); });
  });

  t.test("RPT-44 피벗 전후 막대 집합이 같다 · 측정 불충분 행 배지 · CH-T02 빗금", function (c) {
    var A = c.assert;
    var M = T.model(FIX.td, FIX.details, {});
    function bars(pivot) {
      var res = C.gantt({rows: T.ganttRows(M, pivot), months: M.months}, {mode: "team", width: 1100, id: "g"});
      var out = [];
      (function walk(v) {
        if (!v || typeof v !== "object") { return; }
        if (v.a && v.a["data-unit"]) { out.push(v.a["data-ref"] + "#" + v.a["data-unit"]); }
        (v.c || []).forEach(walk);
      }(res.svg));
      return out.sort();
    }
    var base = bars(false);
    var piv = bars(true);
    var all = [];
    FIX.td.gantt.forEach(function (g) { g.units.forEach(function (u) { all.push(g.person + "|" + g.role_id + "#" + u.unit_id); }); });
    A.deepStrictEqual(base, all.sort());
    A.deepStrictEqual(piv, base);
    var weakRow = T.ganttRows(M, false).filter(function (r) { return r.level === 0 && r.key === "person:7"; })[0];
    A.strictEqual(weakRow.badge, "unreliable");
    var ch = C.teamDomainBars({months: M.months, domains: M.domains, people: M.people, unattributed: FIX.td.unattributed}, {id: "x"});
    A.ok(vstr(ch.svg).indexOf("url(#hatch-est)") >= 0, "측정 불충분 몫 빗금");
  });

  t.test("RPT-45 드릴다운 순수 — A 의 상세는 A 의 단계(팀 합의 체인이 아님)", function (c) {
    var A = c.assert;
    var M = T.model(FIX.td, FIX.details, {});
    var refs = T.ganttRows(M, false).filter(function (r) { return !r.group && /\|r_3d3d8e$/.test(r.ref || ""); }).map(function (r) { return r.ref; });
    A.deepStrictEqual(refs.sort(), ["0|" + RID_A, "1|" + RID_A]);
    var a = vstr(T.detailBody(M, "0|" + RID_A, T.detailFor(M, "0|" + RID_A), {}));
    var b = vstr(T.detailBody(M, "1|" + RID_A, T.detailFor(M, "1|" + RID_A), {}));
    A.ok(a.indexOf("사양서 검토") >= 0 && a.indexOf("설계 메모") < 0);
    A.ok(b.indexOf("설계 메모") >= 0 && b.indexOf("사양서 검토") < 0);
    A.ok(a.indexOf("팀원A") >= 0 && b.indexOf("팀원B") >= 0);
    var none = vstr(T.detailBody(M, "0|r_000000", null, {}));
    A.ok(none.indexOf("이 업무의 워크플로우가 묶음에 없습니다") >= 0);
    var cut = copy(FIX.details["0|" + RID_A]);
    delete cut.units;
    cut.units_omitted = true;
    A.ok(vstr(T.detailBody(M, "0|" + RID_A, cut, {})).indexOf("단위업무 목록은 팀 대시보드에서 보세요") >= 0);
  });

  t.test("모든 절이 그려진다 — 전체판·공유판(사람별 열 없음)·빈 자료", function (c) {
    var A = c.assert;
    var share = copy(FIX.td);
    var tt = {by_month: {}, total: {regular: 0, extended: 0, night: 0, holiday: 0}};
    share.people.forEach(function (p) {
      p.months.forEach(function (e) {
        Object.keys(e[T.SHARE_KEYS.tags]).forEach(function (k) { tt.total[k] += e[T.SHARE_KEYS.tags][k]; });
        delete e[T.SHARE_KEYS.load]; delete e[T.SHARE_KEYS.avail]; delete e[T.SHARE_KEYS.tags];
      });
    });
    share.tag_totals = tt;
    share.variant = "share";
    [FIX.td, share, {}, {people: [], months: []}].forEach(function (td, n) {
      var M = T.model(td, FIX.details, {});
      T.SECTIONS.forEach(function (s) {
        var S = {section: s[0], tables: {}, open: {}, collapsed: {}, width: 900, pivot: n === 1, gview: "week", roleCell: null, live: false};
        A.ok(vstr(T.sectionView(M, S)).length > 0, s[0] + " " + n);
      });
    });
    var Mf = T.model(FIX.td, {}, {});
    var Ms = T.model(share, {}, {});
    var S = {section: "people", tables: {}, open: {}, collapsed: {}, width: 900};
    A.ok(vstr(T.sectionView(Mf, S)).indexOf(">로드율<") >= 0);
    A.ok(vstr(T.sectionView(Ms, S)).indexOf(">로드율<") < 0);
    A.ok(vstr(T.sectionView(Ms, S)).indexOf(">가용일<") < 0);
    A.ok(vstr(T.sectionView(Ms, S)).indexOf("공유판에는 사람별 로드율") >= 0);
    A.strictEqual(T.kpis(Ms)[2].value, T.kpis(Mf)[2].value);        // 초과 근무 팀 합계는 공유판에도 같다
  });

  // ───────────── 앱(가짜 문서) ─────────────
  t.test("RPT-45 자기완결 보고서 — 막대를 누르면 그 사람 서랍(details 섬) · 해시 #gantt/i/role · 닫으면 뒤로", function (c) {
    var A = c.assert;
    var doc = page("team", "full", FIX.td, FIX.details);
    var env = fakeEnv();
    var app = T.createApp(doc, env);
    app.start();
    A.ok(doc.getElementById("app").textContent.indexOf("8명") >= 0);
    env.location.hash = "gantt";
    var main = doc.getElementById("app");
    var barA = byAct(main, "open-gantt", "0|" + RID_A).filter(function (n) { return n.hasAttribute("data-unit"); })[0];
    var barB = byAct(main, "open-gantt", "1|" + RID_A).filter(function (n) { return n.hasAttribute("data-unit"); })[0];
    A.ok(barA && barB, "두 사람의 같은 역할 막대");
    fire(barA, "click");
    var dr = drawerOf(doc);
    A.ok(dr, "서랍");
    A.ok(dr.textContent.indexOf("사양서 검토") >= 0 && dr.textContent.indexOf("설계 메모") < 0);
    A.strictEqual(env.location.hash, "#gantt/0/" + RID_A);
    fire(barB, "click");                                            // 열린 채로 다른 막대 — 해시는 바꿔 끼운다
    dr = drawerOf(doc);
    A.ok(dr.textContent.indexOf("설계 메모") >= 0 && dr.textContent.indexOf("사양서 검토") < 0);
    A.strictEqual(env.location.hash, "#gantt/1/" + RID_A);
    A.strictEqual(doc.body.all().filter(function (n) { return n.getAttribute("role") === "dialog"; }).length, 1);
    fire(byAct(dr, "drawer-close")[0], "click");
    A.strictEqual(drawerOf(doc), null);
    A.strictEqual(env.backs, 1);
    A.strictEqual(env.location.hash, "#gantt");
    env.location.hash = "gantt/0/" + RID_A;                         // 주소로 바로 열기(뒤로 가기·새로 고침)
    A.ok(drawerOf(doc) && drawerOf(doc).textContent.indexOf("사양서 검토") >= 0);
    env.history.back();
    A.strictEqual(drawerOf(doc), null);
  });

  t.test("간트 조작 — 피벗·주 보기·행 접기·표로 보기(같은 막대)", function (c) {
    var A = c.assert;
    var doc = page("team", "full", FIX.td, FIX.details);
    var env = fakeEnv();
    T.createApp(doc, env).start();
    env.location.hash = "gantt";
    var main = doc.getElementById("app");
    function units() {
      return byAct(main, "open-gantt").filter(function (n) { return n.hasAttribute("data-unit"); })
        .map(function (n) { return n.getAttribute("data-unit"); }).sort();
    }
    var before = units();
    A.strictEqual(before.length, FIX.td.gantt.reduce(function (s, g) { return s + g.units.length; }, 0));
    fire(byAct(main, "pivot", "work")[0], "click");
    A.deepStrictEqual(units(), before);
    A.strictEqual(byAct(main, "pivot", "work")[0].getAttribute("aria-pressed"), "true");
    fire(byAct(main, "gview", "week")[0], "click");
    A.deepStrictEqual(units(), before);
    var grp = byAct(main, "toggle-row").filter(function (n) { return /^domain:DEV$/.test(n.getAttribute("data-ref")); })[0];
    fire(grp, "click");
    A.ok(units().length < before.length, "접힌 행의 막대는 그리지 않는다");
    fire(byAct(main, "expand-all")[0], "click");
    A.deepStrictEqual(units(), before);
    fire(byAct(main, "chart-table", "ch-t08")[0], "click");
    A.ok(main.textContent.indexOf("가장 바쁜 주") >= 0);
  });

  t.test("TAB-S06 악성 라벨은 글자 노드로만(스크립트 요소 0)", function (c) {
    var A = c.assert;
    var td = copy(FIX.td);
    td.team_label = EVIL;
    td.people[0].label = EVIL;
    td.gantt[0].units[0].title = EVIL;
    td.agentic.needs[0].label = EVIL;
    td.interpretation = [{code: "TI-01", text_ko: EVIL, refs: {}}];
    var doc = page("team", "full", td, FIX.details);
    var env = fakeEnv();
    T.createApp(doc, env).start();
    ["summary", "people", "agentic", "gantt", "domains"].forEach(function (s) {
      env.location.hash = s;
      A.strictEqual(doc.body.all().filter(function (n) { return n.tagName === "script" && !n.hasAttribute("type"); }).length, 0, s);
      A.ok(textNodes(doc.body).some(function (x) { return x.indexOf(EVIL) >= 0; }) || s === "gantt", s);
    });
    A.ok(textNodes(doc.getElementById("team-head")).indexOf(EVIL + " 팀 보고서") >= 0);
  });

  t.test("대시보드(API) — /api/team · 드릴다운은 사람 키로 /api/team/detail · 없음 404 문구 · 토큰 모드", function (c) {
    var A = c.assert;
    var log = [];
    var idx = {};
    FIX.td.people.forEach(function (p) { idx[p.person_key] = p.i; });
    var fetch = fakeFetch(function (url) {
      if (url === "/api/team") { return {status: 200, body: FIX.td}; }
      var m = /^\/api\/team\/detail\?person=(p_[0-9a-f]{12})&role=(r_[0-9a-f]{6})$/.exec(url);
      if (m) {
        var d = FIX.details[idx[m[1]] + "|" + m[2]];
        return d ? {status: 200, body: d} : {status: 404, body: {ok: false, code: "not_found", error: "없음", detail: []}};
      }
      return {status: 404, body: {ok: false}};
    }, log);
    var doc = page("team", "live", null, null);
    var env = fakeEnv({fetch: fetch});
    var app = T.createApp(doc, env);
    app.start();
    A.strictEqual(app.state.live, true);
    A.ok(doc.getElementById("team-head").textContent.indexOf("팀 대시보드") >= 0);
    env.location.hash = "gantt";
    var bar = byAct(doc.getElementById("app"), "open-gantt", "1|" + RID_A).filter(function (n) { return n.hasAttribute("data-unit"); })[0];
    fire(bar, "click");
    var call = log.filter(function (x) { return x.url.indexOf("/api/team/detail") === 0; })[0];
    A.strictEqual(call.url, "/api/team/detail?person=" + FIX.td.people[1].person_key + "&role=" + RID_A);
    A.ok(drawerOf(doc).textContent.indexOf("설계 메모") >= 0);
    app.openDetail("0|r_000000", null);
    A.ok(drawerOf(doc).textContent.indexOf("이 업무의 워크플로우가 묶음에 없습니다") >= 0);
    // 토큰 모드(401) → 토큰 입력 → 헤더로 다시 읽기
    var log2 = [];
    var fetch2 = fakeFetch(function (url, init) {
      var tok = (init.headers || {})["X-LM27-Upload-Token"];
      return tok === "t0k" ? {status: 200, body: FIX.td} : {status: 401, body: {ok: false, code: "token_required", error: "토큰이 필요합니다", detail: []}};
    }, log2);
    var doc2 = page("team", "live", null, null);
    T.createApp(doc2, fakeEnv({fetch: fetch2})).start();
    A.ok(doc2.getElementById("app").textContent.indexOf("토큰이 필요합니다") >= 0);
    doc2.getElementById("team-token").value = "t0k";
    fire(byAct(doc2.getElementById("app"), "token-save")[0], "click");
    A.ok(doc2.getElementById("app").textContent.indexOf("8명") >= 0);
    var teamCalls = log2.filter(function (x) { return x.url === "/api/team"; });
    A.strictEqual(teamCalls[teamCalls.length - 1].headers["X-LM27-Upload-Token"], "t0k");
  });

  t.test("대시보드 머리 알림 — 재취합 실패(이전 세대 계속)·방화벽 의심(/api/status)", function (c) {
    var A = c.assert;
    var fetch = fakeFetch(function (url) {
      if (url === "/api/team") { return {status: 200, body: FIX.td}; }
      if (url === "/api/status") {
        return {status: 200, body: {aggregate: {gen: 12, state: "failed", note: "실패 — 재취합 시간 초과"},
          firewall_hint: {suspect: true, level: "warn", message_ko: "다른 PC 의 접속이 없습니다 — 방화벽을 확인하세요"}}};
      }
      return {status: 404, body: {}};
    }, []);
    var doc = page("team", "live", null, null);
    T.createApp(doc, fakeEnv({fetch: fetch})).start();
    var txt = doc.getElementById("app").textContent;
    A.ok(txt.indexOf("최근 재취합이 실패해 이전 세대를 그대로 보여 줍니다 — 실패 — 재취합 시간 초과") >= 0, txt.slice(0, 200));
    A.ok(txt.indexOf("방화벽을 확인하세요") >= 0);
    A.ok(txt.indexOf("8명") >= 0);
  });

  t.test("서랍 표로 보기 · 경고 목록 · 니즈 카탈로그 올리기 주소", function (c) {
    var A = c.assert;
    var doc = page("team", "full", FIX.td, FIX.details);
    var env = fakeEnv();
    var app = T.createApp(doc, env);
    app.start();
    fire(byAct(doc.getElementById("team-head"), "show-warnings")[0], "click");
    A.ok(drawerOf(doc).textContent.indexOf("단위업무 ID 불안정 의심") >= 0);
    app.openDetail("0|" + RID_A, null);
    fire(byAct(drawerOf(doc), "chart-table", "ch-p07-team")[0], "click");
    A.ok(drawerOf(doc).textContent.indexOf("중앙 소요") >= 0);
    env.location.hash = "agentic";
    A.strictEqual(byAct(doc.getElementById("app"), "promote-need").length, 0);   // 보고서 파일에는 관리 화면이 없다
    var liveEnv = fakeEnv({fetch: fakeFetch(function () { return {status: 200, body: FIX.td}; }, [])});
    var liveDoc = page("team", "live", null, null);
    T.createApp(liveDoc, liveEnv).start();
    liveEnv.location.hash = "agentic";
    var btn = byAct(liveDoc.getElementById("app"), "promote-need", "1")[0];
    fire(btn, "click");
    A.strictEqual(liveEnv.location.href, "/admin#agent-new/DOC_XLS/" + encodeURIComponent("사양 비교표 자동 작성"));
  });

  // ───────────── 관리 화면(RPT-50) ─────────────
  function registry(v) {
    return {schema: "lm27.registry/1", version: v, team: {label: "팀A"}, pepper: "0".repeat(64), pepper_id: "9f2c01ab",
      projects: [{id: "P-0007", name: "과제A", domain: "DEV", status: "active", merged_into: null, aliases: [], keywords: [], codenames: []}],
      members: [{id: "M003", label: "홍길동"}], vocab: {}, agents: [{id: "AG003", name: "문서 초안 작성"}],
      calendar: {version: "kr-test.1", std_day_min: 480, weekdays: [0, 1, 2, 3, 4], years: [{year: 2026, holidays: [
        {date: "2026-10-09", name: "한글날", kind: "법정", source_url: "https://example.com/holiday", confirmed: "2026-10-01"}]}],
      company_off: []}, internal_domains: ["example.com"], customers: [], partners: []};
  }

  t.test("RPT-50 ② 근거 없는 공휴일 · ③ P-9903 — 검증 코드", function (c) {
    var A = c.assert;
    var reg = registry(7);
    A.deepStrictEqual(T.validateRegistry(reg), []);
    reg.calendar.years[0].holidays.push({date: "2026-12-25", name: "성탄절", kind: "법정", source_url: "", confirmed: ""});
    A.deepStrictEqual(T.validateRegistry(reg), [{path: "calendar.years[0].holidays[1]", code: "bad_holiday_source"}]);
    reg.calendar.years[0].holidays[1].source_url = "http://example.com/x";
    reg.calendar.years[0].holidays[1].confirmed = "2026-10-01";
    A.strictEqual(T.validateRegistry(reg)[0].code, "bad_holiday_source");    // https 만
    reg.calendar.years[0].holidays[1].source_url = "https://example.com/x";
    A.deepStrictEqual(T.validateRegistry(reg), []);
    reg.projects.push({id: "P-9903", name: "새 과제", domain: "EXT"});
    A.deepStrictEqual(T.validateRegistry(reg), [{path: "projects[1].id", code: "reserved_id"}]);
    reg.projects[1] = {id: "P-0008", name: "과제A", domain: "UNC", merged_into: "P-0007"};
    reg.projects[0].merged_into = "P-0008";
    var codes = T.validateRegistry(reg).map(function (e) { return e.code; }).sort();
    A.deepStrictEqual(codes, ["bad_domain", "cycle_merge", "cycle_merge", "dup_alias"]);
    A.strictEqual(T.nextProjectId({projects: [{id: "P-0007"}, {id: "P-9901"}]}), "P-0008");
    A.strictEqual(T.nextProjectId({projects: [{id: "P-9898"}]}), "P-9899");
    A.strictEqual(T.nextProjectId({projects: [{id: "P-9899"}]}), null);           // P-99xx 는 예약
    A.strictEqual(T.nextAgentId({agents: [{id: "AG003"}, {id: "AG010"}]}), "AG011");
  });

  t.test("RPT-50 ① 재적용(rebase) — 내 칸만 최신 판 위에, 같은 칸을 양쪽이 바꾸면 충돌", function (c) {
    var A = c.assert;
    var base = registry(7);
    var mine = copy(base);
    mine.projects[0].keywords = ["광모듈"];
    mine.projects.push({id: "P-0008", name: "과제B", domain: "MP"});
    mine.members[0].label = "김철수";
    var latest = copy(base);
    latest.version = 8;
    latest.projects[0].aliases = ["과제A 모듈"];
    latest.agents.push({id: "AG004", name: "회의록 정리"});
    var r = T.rebase(base, mine, latest);
    A.strictEqual(r.reg.version, 8);
    A.deepStrictEqual(r.reg.projects.map(function (p) { return p.id; }), ["P-0007", "P-0008"]);
    A.deepStrictEqual(r.reg.projects[0].aliases, ["과제A 모듈"]);
    A.deepStrictEqual(r.reg.projects[0].keywords, ["광모듈"]);
    A.deepStrictEqual(r.reg.agents.map(function (a) { return a.id; }), ["AG003", "AG004"]);
    A.strictEqual(r.reg.members[0].label, "김철수");
    A.deepStrictEqual(r.conflicts, []);
    latest.projects[0].keywords = ["양산라인"];                      // 같은 칸을 다른 곳에서도 바꿈
    latest.calendar.years[0].holidays[0].name = "한글날(대체)";
    mine.calendar.years[0].holidays[0].name = "한글날 휴무";
    r = T.rebase(base, mine, latest);
    A.deepStrictEqual(r.reg.projects[0].keywords, ["광모듈"]);
    A.deepStrictEqual(r.conflicts.sort(), ["calendar.holidays:2026-10-09", "projects:P-0007.keywords"]);
    A.strictEqual(r.reg.calendar.years[0].holidays[0].name, "한글날 휴무");
    var del = copy(base);
    del.projects = [];
    r = T.rebase(base, del, latest);                                 // 다른 곳에서 바뀐 항목은 지우지 않고 충돌로
    A.deepStrictEqual(r.reg.projects.map(function (p) { return p.id; }), ["P-0007"]);
    A.ok(r.conflicts.indexOf("projects:P-0007") >= 0);
  });

  t.test("RPT-50 관리 화면 흐름 — 오류면 저장 막힘 → 409 → 최신 판(v8) 재적용 안내 → 다시 저장 200", function (c) {
    var A = c.assert;
    var server = {reg: registry(7), puts: []};
    var log = [];
    var fetch = fakeFetch(function (url, init) {
      var m = init.method || "GET";
      if (url === "/api/registry" && m === "GET") { return {status: 200, body: server.reg}; }
      if (url === "/api/registry" && m === "PUT") {
        var body = JSON.parse(init.body);
        server.puts.push(body);
        if (body.version !== server.reg.version + 1) {
          return {status: 409, body: {ok: false, code: "registry_version_conflict", error: "충돌", detail: []}};
        }
        server.reg = body;
        return {status: 200, body: {ok: true, version: body.version}};
      }
      if (url === "/api/members") { return {status: 200, body: {members: []}}; }
      return {status: 404, body: {ok: false, code: "not_found", error: "없음", detail: []}};
    }, log);
    var doc = page("team-admin", null, null, null);
    var adm = T.createAdmin(doc, fakeEnv({fetch: fetch}));
    adm.start();
    var main = doc.getElementById("app");
    function saveBtn() { return byAct(main, "save")[0]; }
    A.strictEqual(saveBtn().getAttribute("aria-disabled"), "true");   // 바뀐 것이 없음
    fire(byAct(main, "add-project")[0], "click");
    A.strictEqual(adm.state.reg.projects[1].id, "P-0008");
    A.strictEqual(saveBtn().getAttribute("aria-disabled"), "true");   // 이름이 비어 오류
    A.ok(main.textContent.indexOf("bad_value") >= 0);
    var name = main.querySelectorAll("[data-field]").filter(function (n) { return n.getAttribute("data-field") === "projects[1].name"; })[0];
    name.value = "과제B";
    fire(name, "change");
    A.strictEqual(saveBtn().getAttribute("aria-disabled"), null);
    var idIn = main.querySelectorAll("[data-field]").filter(function (n) { return n.getAttribute("data-field") === "projects[1].id"; })[0];
    idIn.value = "P-9903";
    fire(idIn, "change");
    A.ok(main.textContent.indexOf("reserved_id — P-99xx 는 예약된 번호라 쓸 수 없습니다") >= 0);
    A.strictEqual(saveBtn().getAttribute("aria-disabled"), "true");
    idIn = main.querySelectorAll("[data-field]").filter(function (n) { return n.getAttribute("data-field") === "projects[1].id"; })[0];
    idIn.value = "P-0008";
    fire(idIn, "change");
    var other = copy(server.reg);                                     // 다른 창이 먼저 저장(v8)
    other.version = 8;
    other.members[0].label = "김철수";
    server.reg = other;
    fire(saveBtn(), "click");
    A.strictEqual(server.puts[0].version, 8);
    A.strictEqual(server.puts[0].pepper, undefined);                 // pepper 는 보내지 않는다
    A.ok(main.textContent.indexOf("다른 곳에서 레지스트리를 바꿨습니다(v8) — 최신 판을 불러와 내 변경을 다시 적용했습니다") >= 0);
    A.strictEqual(adm.state.reg.members[0].label, "김철수");
    A.deepStrictEqual(adm.state.reg.projects.map(function (p) { return p.id; }), ["P-0007", "P-0008"]);
    A.ok(saveBtn().textContent.indexOf("저장(v9)") >= 0);
    fire(saveBtn(), "click");
    A.strictEqual(server.reg.version, 9);
    A.strictEqual(server.reg.projects[1].name, "과제B");
    A.ok(main.textContent.indexOf("저장했습니다(v9)") >= 0);
    // ② 달력: 근거 없는 공휴일 → 저장 막힘(오류 문구)
    adm.state.tab = "calendar";
    adm.render();
    fire(byAct(main, "add-holiday", "0")[0], "click");
    A.ok(main.textContent.indexOf("bad_date") >= 0);
    var hd = main.querySelectorAll("[data-field]").filter(function (n) { return n.getAttribute("data-field") === "calendar.years[0].holidays[1].date"; })[0];
    hd.value = "2026-12-25";
    fire(hd, "change");
    A.strictEqual(saveBtn().getAttribute("aria-disabled"), "true");
    A.ok(main.textContent.indexOf("bad_holiday_source — 근거 링크(https 로 시작하는 주소)와 확인일이 있어야 저장할 수 있습니다") >= 0);
    // 422 → 칸 옆 서버 사유
    var adm2Doc = page("team-admin", null, null, null);
    var reg422 = registry(7);
    var adm2 = T.createAdmin(adm2Doc, fakeEnv({fetch: fakeFetch(function (url, init) {
      if ((init.method || "GET") === "PUT") { return {status: 422, body: {ok: false, code: "desc_has_codename", error: "레지스트리 검증 실패 — 칸 옆 사유를 확인하세요", detail: ["projects[0].copilot_desc: desc_has_codename"]}}; }
      if (url === "/api/registry") { return {status: 200, body: reg422}; }
      return {status: 404, body: {}};
    }, [])}));
    adm2.start();
    adm2.state.reg.projects[0].copilot_desc = "설명";
    adm2.render();
    fire(byAct(adm2Doc.getElementById("app"), "save")[0], "click");
    A.deepStrictEqual(adm2.state.serverErr, [{path: "projects[0].copilot_desc", code: "desc_has_codename"}]);
    A.ok(adm2Doc.getElementById("app").textContent.indexOf("설명에 코드네임·별칭이 들어 있습니다") >= 0);
  });

  t.test("관리 — 니즈에서 온 새 에이전트 · 제안 → 새 과제(adopted) · 업로드 탭 기간 빼기", function (c) {
    var A = c.assert;
    var log = [];
    var td = copy(FIX.td);
    var fetch = fakeFetch(function (url, init) {
      if (url === "/api/registry") { return {status: 200, body: registry(7)}; }
      if (url === "/api/members") {
        return {status: 200, body: {members: [{i: 0, person_key: td.people[0].person_key, label: "팀원A", label_source: "self", linked: [], retired: false,
          periods: [{period_key: "2026-07-01_2026-09-30", sha12: "a1b2c3d4e5f6", received_at: "2026-10-01T09:00:00+09:00", used_months: ["2026-07"], schema_version: "1.0"}],
          quality: "reliable", flags: []}]}};
      }
      if (url === "/api/team") { return {status: 200, body: td}; }
      if (/^\/api\/members\//.test(url)) { return {status: 200, body: {ok: true}}; }
      return {status: 404, body: {}};
    }, log);
    var env = fakeEnv({fetch: fetch});
    env.hashes = ["#agent-new/DOC_XLS/" + encodeURIComponent("사양 비교표 자동 작성")];
    var doc = page("team-admin", null, null, null);
    var adm = T.createAdmin(doc, env);
    adm.start();
    A.strictEqual(adm.state.tab, "agents");
    A.deepStrictEqual(adm.state.reg.agents[1], {id: "AG004", name: "사양 비교표 자동 작성", axis: "", status: "planned", desc: "",
      step_types: ["DOC_XLS"], inputs: [], outputs: [], keywords: []});
    adm.state.tab = "proposals";
    adm.render();
    var main = doc.getElementById("app");
    fire(byAct(main, "adopt-new", "0|pr_1")[0], "click");
    var np = adm.state.reg.projects[adm.state.reg.projects.length - 1];
    A.deepStrictEqual([np.id, np.name, np.domain, np.adopted], ["P-0008", "과제A 후속", "DEV",
      [{person_key: td.people[0].person_key, proposal_id: "pr_1"}]]);
    adm.state.tab = "uploads";
    adm.render();
    fire(byAct(main, "drop-period")[0], "click");
    var patch = log.filter(function (x) { return x.method === "PATCH"; })[0];
    A.strictEqual(patch.url, "/api/members/" + td.people[0].person_key);
    A.deepStrictEqual(JSON.parse(patch.body), {drop_period: "2026-07-01_2026-09-30"});
  });

  t.test("관리 — 읽기 토큰 모드(401)에서는 빈 작업본을 만들지 않는다 · 토큰을 넣고 다시 읽기", function (c) {
    var A = c.assert;
    var log = [];
    var fetch = fakeFetch(function (url, init) {
      var ok = (init.headers || {})["X-LM27-Upload-Token"] === "rt0";
      if (!ok) { return {status: 401, body: {ok: false, code: "token_required", error: "토큰이 필요합니다", detail: []}}; }
      if (url === "/api/registry") { return {status: 200, body: registry(3)}; }
      if (url === "/api/members") { return {status: 200, body: {members: []}}; }
      return {status: 404, body: {}};
    }, log);
    var doc = page("team-admin", null, null, null);
    var adm = T.createAdmin(doc, fakeEnv({fetch: fetch}));
    adm.start();
    var main = doc.getElementById("app");
    A.strictEqual(adm.state.reg, null);
    A.strictEqual(byAct(main, "save").length, 0);
    A.ok(main.textContent.indexOf("읽기 토큰이 필요합니다") >= 0);
    var tok = main.querySelectorAll("[data-field]").filter(function (n) { return n.getAttribute("data-field") === "$readToken"; })[0];
    tok.value = "rt0";
    fire(tok, "change");
    fire(byAct(main, "reload")[0], "click");
    A.strictEqual(adm.state.base.version, 3);
    A.strictEqual(adm.state.reg.pepper, undefined);                 // pepper 는 작업본·화면에 없다
    A.strictEqual(byAct(main, "save")[0].getAttribute("aria-disabled"), "true");
    A.ok(log.filter(function (x) { return x.url === "/api/registry"; }).length >= 2);
  });

  t.test("자기완결 보고서(파이썬 render_team_report) 섬으로 team.js 기동 — 영역 이름·해석·공유판", function (c) {
    if (!c.python) { c.skip("동봉 파이썬 없음"); }
    var A = c.assert;
    var code = [
      "import sys, json",
      "sys.path.insert(0, " + JSON.stringify(ROOT) + ")",
      "from tests.fixtures.wp37 import teamdata as T",
      "from lm27.team import report as R",
      "from lm27.config import load_config",
      "cfg = load_config()",
      "td, det = T.team8()",
      "td['interpretation'] = R.interpret(td, cfg)",
      "isl = dict(td)",
      "isl['details'] = det",
      "out = {'full': R.render_team_report(isl, cfg=cfg), 'share': R.render_team_report(isl, share=True, cfg=cfg)}",
      "sys.stdout.buffer.write(json.dumps(out).encode('ascii'))"].join("\n");
    var r = cp.spawnSync(c.python, ["-X", "utf8", "-B", "-c", code], {cwd: os.tmpdir(), encoding: "utf8", windowsHide: true,
      maxBuffer: 1 << 27});
    A.strictEqual(r.status, 0, r.stderr);
    var out = JSON.parse(r.stdout);
    function island(html, id) {
      var m = new RegExp("<script type=\"application/json\" id=\"" + id + "\">([^<]*)<").exec(html);
      return JSON.parse(m[1]);
    }
    [["full", "전체판"], ["share", "공유판"]].forEach(function (v) {
      var html = out[v[0]];
      A.ok(html.indexOf("<body data-kind=\"team\" data-variant=\"" + v[0] + "\">") >= 0);
      var doc = page("team", v[0], island(html, "lm27-data"), island(html, "lm27-detail"));
      var env = fakeEnv();
      T.createApp(doc, env).start();
      var head = doc.getElementById("team-head").textContent;
      A.ok(head.indexOf("팀A 팀 보고서") >= 0 && head.indexOf(v[1]) >= 0, head);
      var main = doc.getElementById("app");
      A.ok(main.textContent.indexOf("개발 프로젝트") >= 0, "영역 이름(표시 메타)");
      A.ok(main.textContent.indexOf("개발 프로젝트 비중이 전월보다 8%p 늘었습니다") >= 0, "해석 TI-02");
      env.location.hash = "people";
      var heads = main.querySelectorAll("th").map(function (n) { return n.textContent; });
      A.strictEqual(heads.indexOf("로드율") >= 0, v[0] === "full");
      env.location.hash = "gantt/0/" + RID_A;
      A.ok(drawerOf(doc).textContent.indexOf("의뢰 수신") >= 0, "단계 한글명(섬)");
    });
  });
};
