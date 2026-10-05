/*
 * WP-28 시험 — web\common(lm27charts.js · lm27ui.js · lm27.css · icons.svg) + tools\check_contrast.py.
 * 명세 시험: RPT-11(표시 함수 = 파이썬, 11,530 사례) · RPT-21(색 외 부호) · RPT-25(CH-P02·P07·T08 vnode 골든·밀도 단계)
 *            · RPT-30(악성 문자열) · RPT-33·40(금지 표현) · G-R3~G-R7 · G-R11 · L-19 · L-27(ES 모듈 문법 0).
 * DOM 이 필요한 시험은 아래 작은 가짜 문서로 돈다(브라우저·외부 패키지 없음). 자료는 tests\fixtures\wp28\(합성)만.
 */
"use strict";
var fs = require("fs");
var path = require("path");
var cp = require("child_process");

module.exports = function (t) {
  var ROOT = path.resolve(__dirname, "..", "..");
  var C = require(path.join(ROOT, "web", "common", "lm27charts.js"));
  var U = require(path.join(ROOT, "web", "common", "lm27ui.js"));
  var FIX = path.join(ROOT, "tests", "fixtures", "wp28");
  var SPECS = JSON.parse(fs.readFileSync(path.join(FIX, "chart_specs.json"), "utf8"));
  var GOLDEN_FILE = path.join(FIX, "golden_vnodes.json");

  function readText(rel) { return fs.readFileSync(path.join(ROOT, rel), "utf8"); }

  // vnode 안의 노드를 거르개로 모은다
  function collect(v, pred, out) {
    out = out || [];
    if (!v || typeof v !== "object") { return out; }
    if (pred(v)) { out.push(v); }
    (v.c || []).forEach(function (c) { collect(c, pred, out); });
    return out;
  }
  function texts(v) { return collect(v, function () { return true; }).reduce(function (acc, n) {
    return acc.concat((n.c || []).filter(function (c) { return typeof c === "string"; }));
  }, []); }
  function byAttr(v, k, val) { return collect(v, function (n) { return n.a && n.a[k] === val; }); }
  function hasFill(v, fill) { return collect(v, function (n) { return n.a && n.a.fill === fill; }).length > 0; }

  function teamGantt(spec) {
    return C.gantt({rows: C.ganttRows(spec.team), months: spec.months, as_of: spec.as_of}, {mode: "team", width: 1100, id: "ch-t08"});
  }
  var GOLDEN_BUILD = {
    "CH-P02": function () { return C.monthlyMM(SPECS["CH-P02"], {width: 720, id: "ch-p02"}); },
    "CH-P07": function () { return C.processMap(SPECS["CH-P07"], {width: 720, id: "ch-p07"}); },
    "CH-T08": function () { return teamGantt(SPECS["CH-T08"]); }
  };

  // ───────────── 작은 가짜 문서(마운트·위임·서랍·섬 시험용) ─────────────
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
    setAttribute: function (k, v) { this.attrs[k] = String(v); },
    getAttribute: function (k) { return Object.prototype.hasOwnProperty.call(this.attrs, k) ? this.attrs[k] : null; },
    hasAttribute: function (k) { return Object.prototype.hasOwnProperty.call(this.attrs, k); },
    removeAttribute: function (k) { delete this.attrs[k]; },
    contains: function (n) { while (n) { if (n === this) { return true; } n = n.parentNode; } return false; },
    addEventListener: function (ev, fn) { (this.listeners[ev] = this.listeners[ev] || []).push(fn); },
    removeEventListener: function (ev, fn) { var l = this.listeners[ev] || []; var i = l.indexOf(fn); if (i >= 0) { l.splice(i, 1); } },
    focus: function () { this.ownerDocument.activeElement = this; },
    getBoundingClientRect: function () { return {left: 10, top: 100, right: 60, bottom: 120, width: 50, height: 20}; },
    all: function (out) { out = out || []; this.childNodes.forEach(function (c) { if (c.nodeType === 1) { out.push(c); c.all(out); } }); return out; },
    querySelectorAll: function (sel) {
      var m = /^\[([a-z0-9-]+)\]$/.exec(sel);
      var m2 = /^([a-z]+)\.([a-z0-9-]+)$/.exec(sel);
      return this.all().filter(function (n) {
        if (m) { return n.hasAttribute(m[1]); }
        if (m2) { return n.tagName === m2[1] && (n.getAttribute("class") || "").split(" ").indexOf(m2[2]) >= 0; }
        return false;
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
  }
  FakeDoc.prototype = {
    createElement: function (tag) { return new FakeNode(this, 1, tag, "http://www.w3.org/1999/xhtml"); },
    createElementNS: function (ns, tag) { return new FakeNode(this, 1, tag, ns); },
    createTextNode: function (s) { var n = new FakeNode(this, 3, "#text"); n.data = String(s); return n; },
    getElementById: function (id) { var a = this.root.all(); for (var i = 0; i < a.length; i++) { if (a[i].getAttribute("id") === id) { return a[i]; } } return null; }
  };
  // 이벤트 거품: target 에서 위로 올라가며 수신기 호출
  function fire(target, type, extra) {
    var ev = {type: type, target: target, defaultPrevented: false, preventDefault: function () { this.defaultPrevented = true; }};
    Object.keys(extra || {}).forEach(function (k) { ev[k] = extra[k]; });
    for (var n = target; n; n = n.parentNode) { (n.listeners[type] || []).slice().forEach(function (fn) { fn(ev); }); }
    return ev;
  }

  // ───────────── RPT-11 표시 함수 ─────────────
  t.test("RPT-11 §3.1 골든 표 · 시제품 golden_report.fmt", function (c) {
    var A = c.assert;
    [[3, "0.1"], [87, "1.5"], [2, "0.0"], [9483, "158.1"], [0, "0.0"], [1, "0.0"], [59, "1.0"], [60, "1.0"], [61, "1.0"],
      [90, "1.5"], [1260, "21.0"]].forEach(function (p) { A.strictEqual(U.fmtH1(p[0]), p[1], "fmtH1 " + p[0]); });
    [[9480, 9600, "0.99"], [11520, 10560, "1.09"], [4799, 9600, "0.50"], [0, 9600, "0.00"], [5956, 9600, "0.62"],
      [9000, 9600, "0.94"]].forEach(function (p) { A.strictEqual(U.fmtMM(p[0], p[1]), p[2], "fmtMM " + p[0] + "/" + p[1]); });
    [[9480, 8880, "107"], [1, 200, "1"], [1, 199, "1"], [540, 11520, "5"]].forEach(function (p) {
      A.strictEqual(U.fmtPct(p[0], p[1]), p[2], "fmtPct " + p[0] + "/" + p[1]);
    });
    A.strictEqual(U.fmtRatio(5, 0, 2), null);
    A.strictEqual(U.fmtDays(720), "1.5");
    A.strictEqual(U.fmtSigned(U.fmtH1, 90), "+1.5");
    A.strictEqual(U.fmtSigned(U.fmtH1, -90), "−1.5");
    A.strictEqual(U.fmtSigned(U.fmtH1, 0), "±0");
  });

  t.test("RPT-11 교차 11,530 사례 — fmt_js.json(JS 시제품 출력)과 불일치 0", function (c) {
    var js = JSON.parse(fs.readFileSync(path.join(FIX, "fmt_js.json"), "utf8"));
    var n = 0;
    var bad = [];
    Object.keys(js.h1).forEach(function (m) { n++; if (U.fmtH1(+m) !== js.h1[m]) { bad.push("h1 " + m); } });
    Object.keys(js.mm2).forEach(function (k) { var p = k.split("/"); n++; if (U.fmtRatio(+p[0], +p[1], 2) !== js.mm2[k]) { bad.push("mm2 " + k); } });
    Object.keys(js.pct0).forEach(function (k) { var p = k.split("/"); n++; if (U.fmtRatio(+p[0] * 100, +p[1], 0) !== js.pct0[k]) { bad.push("pct0 " + k); } });
    c.assert.strictEqual(n, 11530);
    c.assert.deepStrictEqual(bad.slice(0, 5), []);
  });

  t.test("RPT-11 교차 — 파이썬 판(동봉 파이썬으로 실행) = JS 판", function (c) {
    if (!c.python) { c.skip("동봉 파이썬 없음"); }
    var r = cp.spawnSync(c.python, ["-X", "utf8", "-B", "-I", path.join(FIX, "gen_fmt_cases.py")],
      {cwd: require("os").tmpdir(), encoding: "utf8", windowsHide: true, maxBuffer: 1 << 24});
    c.assert.strictEqual(r.status, 0, r.stderr);
    var py = JSON.parse(r.stdout);
    var n = 0;
    var bad = 0;
    Object.keys(py.h1).forEach(function (m) { n++; bad += U.fmtH1(+m) !== py.h1[m] ? 1 : 0; });
    Object.keys(py.mm2).forEach(function (k) { var p = k.split("/"); n++; bad += U.fmtRatio(+p[0], +p[1], 2) !== py.mm2[k] ? 1 : 0; });
    Object.keys(py.pct0).forEach(function (k) { var p = k.split("/"); n++; bad += U.fmtRatio(+p[0] * 100, +p[1], 0) !== py.pct0[k] ? 1 : 0; });
    c.assert.strictEqual(n, 11530);
    c.assert.strictEqual(bad, 0, "불일치(" + py.source + ")");
  });

  t.test("표시 보조 — 소수 값 half-up · 비율 글자 · 병행도", function (c) {
    var A = c.assert;
    A.strictEqual(U.fmtNum(1.15, 1), "1.2");                     // 1.15*10 의 이진 오차에도 half-up
    A.strictEqual(U.fmtNum(2.25, 1), "2.3");
    A.strictEqual(U.fmtNum(13.3, 2), "13.30");
    A.strictEqual(U.fmtNum(-0.04, 1), "0.0");
    A.strictEqual(U.fmtNum(-0.06, 1), "−0.1");
    A.strictEqual(U.fmtNum(null, 1), null);
    A.strictEqual(U.fmtX(1.85), "×1.9");
    A.strictEqual(U.fmtX(undefined), "—");
    A.strictEqual(U.pctText(1, 300), "0.3%");
    A.strictEqual(U.pctText(0, 300), "0%");
    A.strictEqual(U.pctText(9480, 8880), "107%");
    A.strictEqual(U.pctText(5, 0), "—");
    A.strictEqual(U.shareText(0.56), "56%");
    A.strictEqual(U.hText(9483), "158.1h");
    A.strictEqual(U.mmText(9480, 9600), "0.99 MM");
    A.strictEqual(U.daysText(720), "1.5영업일");
  });

  // ───────────── 공용 산식 ─────────────
  t.test("밀도 단계(TEAM §4.6 고정) · 줄 배정(시제품 lanes 골든)", function (c) {
    var A = c.assert;
    var want = {0: 0, 1: 1, 119: 1, 120: 2, 359: 2, 360: 3, 719: 3, 720: 4, 1199: 4, 1200: 5, 5000: 5};
    Object.keys(want).forEach(function (m) { A.strictEqual(C.densityLevel(+m), want[m], "밀도 " + m); });
    var L = C.lanes([{id: "u4", from: "2026-07-21", to: "2026-07-30"}, {id: "u2", from: "2026-07-08", to: "2026-07-20"},
      {id: "u1", from: "2026-07-03", to: "2026-07-09"}, {id: "u3", from: "2026-07-10", to: "2026-07-15"}]);
    A.deepStrictEqual(L, {u1: 0, u2: 1, u3: 0, u4: 0});
  });

  t.test("날짜 산술 — ISO 주·주 시작·로컬 분(2020-01-01 원점)", function (c) {
    var A = c.assert;
    A.strictEqual(C.isoWeek(C.dayNum("2026-07-03")), "2026-W27");
    A.strictEqual(C.isoWeek(C.dayNum("2021-01-03")), "2020-W53");
    A.strictEqual(C.isoWeek(C.dayNum("2026-12-31")), "2026-W53");
    A.strictEqual(C.isoWeek(C.dayNum("2025-12-29")), "2026-W01");
    A.strictEqual(C.dateOf(C.weekStart("2026-W27")), "2026-06-29");
    A.strictEqual(C.dateOf(C.weekStart("2026-W01")), "2025-12-29");
    A.strictEqual(C.isoWd(C.dayNum("2026-10-05")), 1);
    for (var n = C.dayNum("2019-12-25"); n < C.dayNum("2031-01-10"); n += 3) {
      A.strictEqual(C.dayNum(C.dateOf(n)), n);
      var wk = C.isoWeek(n);
      A.ok(n >= C.weekStart(wk) && n < C.weekStart(wk) + 7, wk);
    }
    A.strictEqual(C.toMin("2020-01-01 00:00"), 0);
    A.strictEqual(C.toMin("2020-01-02T01:30"), 1440 + 90);
    A.strictEqual(C.toMin("13:00", C.dayNum("2020-01-03")), 2 * 1440 + 780);
    A.strictEqual(C.hhmm(C.toMin("2026-09-22 13:05")), "13:05");
  });

  // ───────────── RPT-25 vnode 골든 ─────────────
  t.test("RPT-25 CH-P02·CH-P07·CH-T08 toString(vnode) = 골든", function (c) {
    var got = {};
    Object.keys(GOLDEN_BUILD).forEach(function (k) { got[k] = C.toString(GOLDEN_BUILD[k]().svg); });
    if (c.update) {
      fs.writeFileSync(GOLDEN_FILE, JSON.stringify(got, null, 1) + "\n", "utf8");
      return;
    }
    if (!fs.existsSync(GOLDEN_FILE)) { throw new Error("골든 파일 없음 — --update-golden 으로 만든 뒤 검토"); }
    var want = JSON.parse(fs.readFileSync(GOLDEN_FILE, "utf8"));
    Object.keys(GOLDEN_BUILD).forEach(function (k) { c.assert.strictEqual(got[k], want[k], k + " 골든 불일치"); });
  });

  t.test("RPT-25 CH-T08 — 줄·밀도 단계·경계 표시·피벗 전후 막대 집합", function (c) {
    var A = c.assert;
    var r = teamGantt(SPECS["CH-T08"]);
    var bars = byAttr(r.svg, "data-act", "open-gantt").filter(function (g) { return g.a["data-unit"]; });
    var laneY = {};
    bars.forEach(function (g) {
      var lead = g.c.filter(function (n) { return n.t === "rect" && n.a["class"] === "f-lead"; })[0];
      laneY[g.a["data-unit"]] = lead.a.y;
    });
    A.strictEqual(laneY.u_00000000a1, laneY.u_00000000a3);
    A.strictEqual(laneY.u_00000000a1, laneY.u_00000000a4);
    A.strictEqual(laneY.u_00000000a2 - laneY.u_00000000a1, 18);     // u2 만 둘째 줄
    function seqOf(unit) {
      var g = bars.filter(function (b) { return b.a["data-unit"] === unit; })[0];
      return g.c.filter(function (n) { return /^f-seq-/.test(n.a["class"] || ""); }).map(function (n) { return n.a["class"]; });
    }
    A.deepStrictEqual(seqOf("u_00000000a1"), ["f-seq-1", "f-seq-2"]);   // 119 → 1, 120 → 2
    A.deepStrictEqual(seqOf("u_00000000a2"), ["f-seq-4", "f-seq-5"]);   // 1199 → 4, 1200 → 5
    var a2 = bars.filter(function (b) { return b.a["data-unit"] === "u_00000000a2"; })[0];
    A.ok(a2.c.some(function (n) { return n.t === "line" && n.a["stroke-dasharray"] === "3 2"; }), "추정 시작·끝 점선");
    var a4 = bars.filter(function (b) { return b.a["data-unit"] === "u_00000000a4"; })[0];
    A.ok(a4.c.some(function (n) { return n.t === "polygon"; }), "진행 중 ▸");
    A.ok(a4.a["data-tip"].indexOf("진행 중") >= 0);
    A.strictEqual(bars[0].a["data-ref"].split("|").length, 2);         // 드릴다운 = (사람 i, 역할) — RPT-45 키
    var piv = C.gantt({rows: C.ganttRows(SPECS["CH-T08"].team, {pivot: true}), months: SPECS["CH-T08"].months,
      as_of: SPECS["CH-T08"].as_of}, {mode: "team", width: 1100});
    function units(res) { return byAttr(res.svg, "data-act", "open-gantt").map(function (g) { return g.a["data-unit"]; }).filter(Boolean).sort(); }
    A.deepStrictEqual(units(piv), units(r));
    A.deepStrictEqual(piv.table.rows.map(function (x) { return x[1]; }).sort(), r.table.rows.map(function (x) { return x[1]; }).sort());
    A.ok(r.legend.some(function (l) { return l.label.indexOf("막대 길이는 투입이 아닙니다") >= 0; }));
  });

  t.test("간트 행 — 기본 계층·피벗·정렬·접기(표는 접힌 행까지)", function (c) {
    var A = c.assert;
    var rows = C.ganttRows(SPECS["CH-T08"].team);
    A.deepStrictEqual(rows.map(function (r) { return r.level; }), [0, 1, 2, 3, 0, 1, 2, 3]);
    A.strictEqual(rows[0].label, "팀원A");                          // 투입이 큰 사람 먼저
    A.strictEqual(rows[3].label, "회로·설계");
    A.strictEqual(rows[3].ref, "0|r_5c0d11");
    A.strictEqual(rows[4].badge, "unreliable");
    var piv = C.ganttRows(SPECS["CH-T08"].team, {pivot: true});
    A.deepStrictEqual(piv.filter(function (r) { return r.level === 0; }).map(function (r) { return r.label; }), ["개발 프로젝트", "양산 프로젝트"]);
    A.strictEqual(piv[3].label, "팀원A");
    var full = C.gantt({rows: rows, months: ["2026-07", "2026-08"]}, {mode: "team"});
    var col = C.gantt({rows: rows, months: ["2026-07", "2026-08"]}, {mode: "team", collapsed: {"person:0": true}});
    A.ok(byAttr(col.svg, "data-unit", "u_00000000a1").length === 0, "접힌 사람의 막대는 그리지 않음");
    A.strictEqual(col.table.rows.length, full.table.rows.length);
    var mrows = C.modelRows({domains: [{code: "DEV", name: "개발 프로젝트"}], projects: [{key: "P-0007", label: "과제A"}],
      roles: [{role_id: "r_1", label: "회로 · 해석·분석"}], units: [{unit_id: "u_0000000001", domain: "DEV", project_key: "P-0007", role_id: "r_1", effort_min: 60, spans: [["2026-09-01", "2026-09-03", "lead"]]}]});
    A.deepStrictEqual(mrows.map(function (r) { return r.label; }), ["개발 프로젝트", "과제A", "회로 · 해석·분석"]);
  });

  t.test("RPT-25 CH-P07 — 단계·전이·병목·되돌림(§4.2.3 골든)", function (c) {
    var A = c.assert;
    var r = C.processMap(SPECS["CH-P07"], {width: 720});
    A.strictEqual(byAttr(r.svg, "data-act", "pm-step").length, 5);
    var edges = collect(r.svg, function (n) { return n.a && n.a["data-edge"]; });
    A.strictEqual(edges.length, 6);
    var back = edges.filter(function (g) { return g.a["data-edge"] === "3>2"; })[0];
    A.strictEqual(back.c[0].a["stroke-dasharray"], "5 4");
    var all = texts(r.svg).join("|");
    A.ok(all.indexOf("대기 병목 · 1.5영업일") >= 0);
    A.ok(all.indexOf("작업 병목 · 56%") >= 0);
    A.ok(all.indexOf("×5") >= 0 && all.indexOf("×4") >= 0);
    var s3 = byAttr(r.svg, "data-ref", "3")[0];
    A.ok(/pm-bn/.test(collect(s3, function (n) { return n.t === "rect" && /pm-node/.test(n.a["class"] || ""); })[0].a["class"]));
    A.ok(s3.a["aria-label"].indexOf("4/4 단위업무") >= 0 && s3.a["aria-label"].indexOf("관측 92%") >= 0);
    A.strictEqual(r.tables.length, 2);
    A.deepStrictEqual(r.table.rows[1].slice(0, 2), ["2", "해석 프로그램"]);
    var thin = JSON.parse(JSON.stringify(SPECS["CH-P07"]));
    thin.sample = "thin";
    thin.units_n = 2;
    var rt = C.processMap(thin, {width: 720});
    A.ok(texts(rt.svg).join("|").indexOf("병목") < 0, "표본 부족이면 병목 없음");
    A.ok(rt.caption.notes.join(" ").indexOf("표본 부족(단위업무 2건)") >= 0);
    var narrow = C.processMap(SPECS["CH-P07"], {width: 400});
    A.ok(narrow.svg.a.height > 300, "좁으면 세로 배치");
    var shuffled = JSON.parse(JSON.stringify(SPECS["CH-P07"]));
    shuffled.edges.reverse();
    shuffled.steps.reverse();
    A.strictEqual(C.toString(C.processMap(shuffled, {width: 720, id: "ch-p07"}).svg), C.toString(GOLDEN_BUILD["CH-P07"]().svg));
  });

  t.test("CH-P02 — 툴팁·로드율·1MM 기준선·부분월", function (c) {
    var A = c.assert;
    var r = C.monthlyMM(SPECS["CH-P02"]);
    var sep = byAttr(r.svg, "data-ref", "2026-09")[0];
    var tip = sep.a["data-tip"].split("\n");
    A.strictEqual(tip[0], "2026-09 · 0.99 MM(158.0h ÷ 160h)");
    A.ok(tip.indexOf("로드\t107%") >= 0);
    A.ok(texts(r.svg).indexOf("1 MM") >= 0);
    A.ok(texts(r.svg).indexOf("1.09") >= 0);
    A.ok(texts(r.svg).indexOf("부분") >= 0);
    A.deepStrictEqual(r.table.rows[2], ["2026-09", "148.0", "4.0", "2.0", "4.0", "158.0", "160.0", "0.99", "107%"]);
  });

  // ───────────── RPT-21 색 외 부호 ─────────────
  t.test("RPT-21 추정 = hatch-est · 미귀속 = hatch-unattr · 막힘 = hatch-bad · 노드 종류 = 모양", function (c) {
    var A = c.assert;
    var p03 = C.dailyBars(SPECS["CH-P03"]);
    var low = byAttr(p03.svg, "data-ref", "2026-09-23")[0];
    A.ok(hasFill(low, "url(#hatch-est)"), "낮은 신뢰 날 빗금");
    A.ok(!hasFill(byAttr(p03.svg, "data-ref", "2026-09-22")[0], "url(#hatch-est)"));
    A.ok(texts(p03.svg).indexOf("연차") >= 0 && texts(p03.svg).indexOf("반차") >= 0);
    var p16 = C.dayBand(SPECS["CH-P16"]);
    var tips = collect(p16.svg, function (n) { return n.a && n.a["data-tip"]; });
    var est = tips.filter(function (g) { return g.a["data-tip"].indexOf("추정") >= 0; })[0];
    var unat = tips.filter(function (g) { return g.a["data-tip"].indexOf("미분류") >= 0; })[0];
    A.ok(hasFill(est, "url(#hatch-est)"));
    A.ok(hasFill(unat, "url(#hatch-unattr)"));
    A.ok(texts(p16.svg).indexOf("차감") >= 0);
    var t02 = C.teamDomainBars(SPECS["CH-T02"]);
    var aug = byAttr(t02.svg, "data-ref", "2026-08")[0];
    var sep = byAttr(t02.svg, "data-ref", "2026-09")[0];
    A.ok(hasFill(aug, "url(#hatch-est)"), "측정 불충분 몫 빗금");
    A.ok(hasFill(sep, "url(#hatch-unattr)"), "미귀속 빗금");
    A.ok(texts(t02.svg).indexOf("1명 자료 없음") >= 0);
    var h01 = C.coverageHeatmap(SPECS["CH-H01"]);
    A.ok(hasFill(byAttr(h01.svg, "data-ref", "2026-10-02|teams")[0], "url(#hatch-bad)"));
    A.ok(hasFill(byAttr(h01.svg, "data-ref", "2026-09-28|teams")[0], "url(#hatch-bad)"));
    A.ok(!hasFill(byAttr(h01.svg, "data-ref", "2026-09-28|cal")[0], "url(#hatch-bad)"));
    A.ok(byAttr(h01.svg, "data-ref", "2026-10-02|teams")[0].a["data-tip"].indexOf("팀즈 창 숨김(R-UIAEMPTY)") >= 0);
    A.strictEqual(h01.legend.length, 7);
    var p13 = C.radial(SPECS["CH-P13"]);
    function shapeOf(id) {
      var g = byAttr(p13.svg, "data-ref", id)[0];
      var s = g.c[1];
      return s.t + (s.t === "polygon" ? String(s.a.points.split(" ").length) : "");
    }
    var shapes = {P: shapeOf("P-0007"), R: shapeOf("r_1"), D: shapeOf("d_1"), A: shapeOf("a_1"), C: shapeOf("c_1")};
    A.deepStrictEqual(shapes, {P: "rect", R: "circle", D: "rect", A: "polygon4", C: "polygon3"});
    A.ok(byAttr(p13.svg, "data-ref", "P-0007")[0].c[1].a.rx === 6, "과제는 둥근 사각형");
    A.ok(collect(p13.svg, function (n) { return n.a && n.a["stroke-dasharray"] === "4 3"; }).length >= 1, "추론 관계 점선");
    var st = C.toString(U.statusText("bad", "불가(확정)"));
    A.ok(st.indexOf("<use href=\"#i-bad\"/>") >= 0 && st.indexOf("불가(확정)") >= 0, "상태 = 아이콘 + 글자");
    A.ok(C.toString(U.gradeBadge("C")).indexOf("badge-grade-dash") >= 0);
    A.ok(C.toString(U.gradeBadge("D")).indexOf("D 추정") >= 0);
  });

  // ───────────── 모든 차트 공통 계약 ─────────────
  t.test("CHARTS 이름 정본(부록 A) · 반환 형 · 결정성 · 빈 자료", function (c) {
    var A = c.assert;
    var want = {"CH-H01": "coverageHeatmap", "CH-P02": "monthlyMM", "CH-P03": "dailyBars", "CH-P04": "domainShare",
      "CH-P06": "gantt", "CH-P07": "processMap", "CH-P08": "unitTimeline", "CH-P09": "gantt", "CH-P10": "classMix",
      "CH-P11": "leadDots", "CH-P12": "peerBars", "CH-P13": "radial", "CH-P16": "dayBand", "CH-P17": "gradeBars",
      "CH-T02": "teamDomainBars", "CH-T06": "leadDots", "CH-T08": "gantt"};
    A.deepStrictEqual(Object.keys(C.CHARTS).sort(), Object.keys(want).sort());
    Object.keys(want).forEach(function (k) { A.strictEqual(C.CHARTS[k], C[want[k]], k); });
    var samples = {
      "CH-H01": SPECS["CH-H01"], "CH-P02": SPECS["CH-P02"], "CH-P03": SPECS["CH-P03"],
      "CH-P04": {domains: [{code: "MP", name: "양산 프로젝트", color: "#c47400", min: 1200, units: 3}, {code: "DEV", name: "개발 프로젝트", color: "#2a78d6", min: 6100, units: 9}], unattr_min: 480, denom_min: 9600},
      "CH-P06": {rows: C.ganttRows(SPECS["CH-T08"].team), as_of: "2026-08-20"}, "CH-P07": SPECS["CH-P07"],
      "CH-P08": {runs: [{type: "APP_SIM", "class": "공학", a: "2026-07-03 13:00", b: "2026-07-03 17:00", min: 240, obs_min: 240},
        {type: "DOC_XLS", "class": "문서", a: "2026-07-06 09:00", b: "2026-07-06 10:00", min: 60, obs_min: 30}],
      milestones: [{type: "REQ_IN", t: "2026-07-03 10:12", flags: []}, {type: "REPORT_OUT", t: "2026-07-07 16:40", flags: ["offline"]}],
      boundaries: [{side: "start", code: "S1", t: "2026-07-03 10:12", estimated: false}, {side: "end", code: "E2h", t: "2026-07-07 16:40", estimated: true}],
      longest_wait: {a: "2026-07-03 17:00", b: "2026-07-06 09:00", biz_min: 960}},
      "CH-P09": {rows: C.ganttRows(SPECS["CH-T08"].team)},
      "CH-P10": {groups: [{key: "P-0007", label: "과제A", mix: {"문서": 300, "공학": 900}, none_min: 60}]},
      "CH-P11": {rows: [{key: "r1", label: "회로·설계", baseline_biz_min: 2360}], points: [{unit_id: "u_a4", row: "r1", biz_lead_min: 3300},
        {unit_id: "u_a5", row: "r1", biz_lead_min: 5520, overrun: true, causes: ["WAIT", "REWORK"], cause_names: ["대기", "재작업"]}]},
      "CH-P12": {peers: [{k: 1, name: "김철수", units: 6, shared_effort_min: 750}]}, "CH-P13": SPECS["CH-P13"], "CH-P16": SPECS["CH-P16"],
      "CH-P17": {grades: {A: 600, B: 1200, C: 300}, not_started_n: 1}, "CH-T02": SPECS["CH-T02"],
      "CH-T06": {rows: [{key: "DEV", label: "개발 프로젝트", baseline_biz_min: 1960}], points: [{unit_id: "u_1", row: "DEV", biz_lead_min: 900}]},
      "CH-T08": {rows: C.ganttRows(SPECS["CH-T08"].team)}
    };
    Object.keys(want).forEach(function (k) {
      var r1 = C.CHARTS[k](samples[k], {width: 800, id: "x"});
      var r2 = C.CHARTS[k](JSON.parse(JSON.stringify(samples[k])), {width: 800, id: "x"});
      A.ok(r1.svg && r1.table && Array.isArray(r1.table.cols) && Array.isArray(r1.table.rows) && Array.isArray(r1.legend), k + " 형");
      A.ok(r1.caption && typeof r1.caption.title === "string" && r1.caption.title.length > 0, k + " 제목");
      A.ok(typeof r1.caption.summary === "string" && r1.caption.summary.length > 0, k + " 한 줄 요약");
      r1.table.rows.forEach(function (row) { A.strictEqual(row.length, r1.table.cols.length, k + " 표 열 수"); });
      A.strictEqual(C.toString(r1.svg), C.toString(r2.svg), k + " 결정성");
      A.ok(r1.table.rows.length > 0, k + " 표로 보기 행");
      var e = C.CHARTS[k]({}, {id: "e"});
      A.ok(e.svg && e.caption.summary, k + " 빈 자료");
      if (r1.svg.t === "svg") {
        A.strictEqual(r1.svg.a.role, "img", k + " role=img");
        A.ok(r1.svg.c[0].t === "title" && r1.svg.c[1].t === "desc", k + " 제목·요약(title·desc)");
      }
    });
  });

  // ───────────── RPT-30 악성 문자열 · 마운트 거르개 ─────────────
  t.test("RPT-30 악성 문자열은 글자로만 — 데이터에서 온 요소·on* 속성 0", function (c) {
    var A = c.assert;
    var M = SPECS.malicious;
    var team = JSON.parse(JSON.stringify(SPECS["CH-T08"].team));
    team.gantt[0].units[0].title = M.title;
    team.projects[0].label = M.project;
    team.people[0].label = M.peer;
    var g = C.gantt({rows: C.ganttRows(team), months: ["2026-07", "2026-08"]}, {mode: "team"});
    var p = C.peerBars({peers: [{k: 1, name: M.peer, units: 2, shared_effort_min: 60}]});
    var s = C.toString(g.svg) + C.toString(p.svg);
    A.ok(s.indexOf("<img") < 0 && s.indexOf("<svg onload") < 0 && s.indexOf("</script") < 0, "직렬화에 원문자 태그 0");
    var doc = new FakeDoc();
    var host = doc.createElement("div");
    doc.body.appendChild(host);
    U.mount(g.svg, host);
    U.mount(p.svg, host);
    U.mount(U.tableView(g), host);
    var els = host.all();
    A.ok(els.length > 50);
    els.forEach(function (n) {
      A.ok(["img", "script", "foreignObject", "iframe", "object", "embed", "style", "link"].indexOf(n.tagName) < 0, "금지 요소 " + n.tagName);
      Object.keys(n.attrs).forEach(function (k) { A.ok(!/^on/i.test(k) && k !== "style", "금지 속성 " + k); });
    });
    var txt = host.textContent;
    A.ok(txt.indexOf(M.peer) >= 0, "이름이 글자 그대로 보임");
    A.ok(txt.indexOf("과제") >= 0);
    A.ok(host.all().some(function (n) { return (n.getAttribute("data-tip") || "").indexOf(M.title) >= 0; }), "툴팁도 글자");
  });

  t.test("마운트 거르개 — 허용 태그·속성·href·칠", function (c) {
    var A = c.assert;
    var doc = new FakeDoc();
    var host = doc.createElement("div");
    var v = U.h("div", {"class": "x", onclick: "alert(1)", style: "color:red", "data-act": "go", "aria-label": "가"}, [
      U.h("script", {}, ["alert(1)"]), U.h("img", {src: "x"}), U.h("a", {href: "javascript:alert(1)"}, ["링크"]),
      U.h("a", {href: "#home"}, ["홈"]),
      U.h("svg", {viewBox: "0 0 10 10"}, [U.h("rect", {fill: "url(http://example.com/a)", stroke: "#123456", width: 3}),
        U.h("rect", {fill: "url(#hatch-est)", "xlink:href": "#x"}), U.h("foreignObject", {}, [U.h("div", {}, ["숨은"])])]),
      "글자 <b>그대로</b>"]);
    var el = U.mount(v, host);
    A.strictEqual(el.getAttribute("onclick"), null);
    A.strictEqual(el.getAttribute("style"), null);
    A.strictEqual(el.getAttribute("data-act"), "go");
    var tags = el.all().map(function (n) { return n.tagName; });
    A.ok(tags.indexOf("script") < 0 && tags.indexOf("img") < 0 && tags.indexOf("foreignObject") < 0);
    var as = el.all().filter(function (n) { return n.tagName === "a"; });
    A.strictEqual(as[0].getAttribute("href"), null);
    A.strictEqual(as[1].getAttribute("href"), "#home");
    var rects = el.all().filter(function (n) { return n.tagName === "rect"; });
    A.strictEqual(rects[0].getAttribute("fill"), null);
    A.strictEqual(rects[0].getAttribute("stroke"), "#123456");
    A.strictEqual(rects[1].getAttribute("fill"), "url(#hatch-est)");
    A.strictEqual(rects[1].getAttribute("xlink:href"), null);
    A.strictEqual(rects[0].namespaceURI, U.SVG_NS);
    A.ok(el.textContent.indexOf("글자 <b>그대로</b>") >= 0);
    A.strictEqual(U.render(U.h("p", {}, ["새"]), host).tagName, "p");
    A.strictEqual(host.childNodes.length, 1);
  });

  // ───────────── 상호(가짜 문서) ─────────────
  t.test("위임·키보드·방향키 이동·서랍 초점·데이터 섬·무늬 정의", function (c) {
    var A = c.assert;
    var doc = new FakeDoc();
    var host = doc.createElement("main");
    doc.body.appendChild(host);
    var r = teamGantt(SPECS["CH-T08"]);
    U.mount(r.svg, host);
    var got = [];
    var off = U.delegate(host, {"open-gantt": function (el, ref) { got.push(ref); }, escape: function () { got.push("esc"); }});
    var bars = host.querySelectorAll("[data-nav-row]");
    A.ok(bars.length >= 5);
    fire(bars[0].childNodes[1], "click");
    A.strictEqual(got[0], bars[0].getAttribute("data-ref"));
    var ev = fire(bars[1], "keydown", {key: "Enter"});
    A.ok(ev.defaultPrevented && got.length === 2, "Enter = 누르기");
    fire(bars[1], "keydown", {key: "Escape"});
    A.strictEqual(got[2], "esc");
    // 방향키: 같은 행 → 오른쪽 막대, 아래 → 이웃 행의 가장 가까운 막대
    var first = bars.filter(function (b) { return b.getAttribute("data-unit") === "u_00000000a1"; })[0];
    first.focus();
    fire(first, "keydown", {key: "ArrowRight"});
    A.strictEqual(doc.activeElement.getAttribute("data-unit"), "u_00000000a2");   // 같은 행에서 x 가 다음인 막대
    fire(doc.activeElement, "keydown", {key: "ArrowDown"});
    A.strictEqual(doc.activeElement.getAttribute("data-unit"), "u_00000000b1");
    A.strictEqual(U.navPick([{row: 0, x: 0}, {row: 0, x: 50}, {row: 1, x: 40}, {row: 1, x: 60}], {row: 0, x: 50}, "ArrowDown"), 2);
    A.strictEqual(U.navPick([{row: 0, x: 0}], {row: 0, x: 0}, "ArrowUp"), -1);
    // 툴팁: 마우스 올림 → 글자로만, Esc 로 숨김
    fire(first, "mouseover");
    var tip = doc.getElementById("lm27-tip");
    A.ok(tip && !tip.hasAttribute("hidden"));
    A.strictEqual(tip.childNodes[0].childNodes[0].tagName, "strong");
    fire(first, "keydown", {key: "Escape"});
    A.ok(tip.hasAttribute("hidden"));
    off();
    // 서랍: 열면 제목에 초점, 닫으면 연 요소로 초점 복귀
    first.focus();
    var closed = [];
    var d = U.openDrawer(U.h("p", {}, ["내용"]), {title: "팀원A · 회로·설계", doc: doc, onClose: function () { closed.push(1); }});
    A.strictEqual(d.el.getAttribute("role"), "dialog");
    A.strictEqual(d.el.getAttribute("aria-modal"), "false");
    A.strictEqual(doc.activeElement.getAttribute("id"), "lm27-drawer-title");
    fire(d.el.querySelectorAll("[data-act]")[0], "click");
    A.strictEqual(doc.activeElement, first);
    A.deepStrictEqual(closed, [1]);
    A.ok(!d.el.isConnected);
    // 데이터 섬: \u003c 로 바뀐 글자는 JSON 으로만 해석된다
    var isl = doc.createElement("script");
    isl.setAttribute("id", "lm27-data");
    isl.textContent = "{\"title\":\"\\u003c/script\\u003e\\u003cimg\\u003e\",\"n\":3}";
    doc.body.appendChild(isl);
    A.deepStrictEqual(U.readIsland("lm27-data", doc), {title: "</script><img>", n: 3});
    isl.textContent = "{깨짐";
    A.strictEqual(U.readIsland("lm27-data", doc), null);
    A.strictEqual(U.readIsland("없음", doc), null);
    // 무늬 정의는 한 번만, 크기 0 SVG(display:none 아님)
    A.ok(U.ensureDefs(doc, C));
    A.ok(U.ensureDefs(doc, C));
    var defs = doc.body.querySelectorAll("[id]").filter(function (n) { return /^hatch-/.test(n.getAttribute("id")); });
    A.deepStrictEqual(defs.map(function (n) { return n.getAttribute("id"); }).sort(), ["hatch-bad", "hatch-est", "hatch-unattr"]);
    var holder = defs[0].parentNode.parentNode;
    A.strictEqual(holder.getAttribute("class"), "lm27-defs");
    A.ok(!holder.hasAttribute("hidden"));
  });

  t.test("표로 보기 — 정렬은 표에서만·원래 순서·500행 상한", function (c) {
    var A = c.assert;
    A.deepStrictEqual(U.sortRows([["b", "10.5h"], ["a", "9.0h"], ["c", "—"]], 1, false).map(function (r) { return r[0]; }), ["a", "b", "c"]);
    A.deepStrictEqual(U.sortRows([["가"], ["다"], ["나"]], 0, true).map(function (r) { return r[0]; }), ["다", "나", "가"]);
    var big = {table: {cols: ["n"], rows: []}, caption: {title: "큰 표"}};
    for (var i = 0; i < 620; i++) { big.table.rows.push([String(i)]); }
    var s = C.toString(U.tableView(big, {sortCol: 0, desc: true}));
    A.ok(s.indexOf("더 보기(500)") >= 0 && s.indexOf("원래 순서") >= 0 && s.indexOf("aria-sort=\"descending\"") >= 0);
    A.strictEqual((s.match(/<tr>/g) || []).length, 501);
    var cv = C.toString(U.chartView(C.monthlyMM(SPECS["CH-P02"]), {id: "m", table: true}));
    A.ok(cv.indexOf("<table") >= 0 && cv.indexOf("aria-pressed=\"true\"") >= 0);
  });

  // ───────────── 정적 관문(G-R3~G-R6 · G-R11 · L-19 · L-27) ─────────────
  var WEB_JS = ["web/common/lm27charts.js", "web/common/lm27ui.js"];

  t.test("G-R4·G-R11 위험 API·toFixed 0 · G-R6 </script·</style 0 · ES 모듈 문법 0", function (c) {
    var banned = [/\binnerHTML\b/, /\bouterHTML\b/, /\binsertAdjacentHTML\b/, /\bdocument\.write/, /(^|[^\w.])eval\s*\(/,
      /\bnew\s+Function\b/, /\bset(Timeout|Interval)\s*\(\s*['"`]/, /\bDOMParser\b/, /\.toFixed\s*\(/];
    WEB_JS.forEach(function (f) {
      var s = readText(f);
      banned.forEach(function (re) { c.assert.ok(!re.test(s), f + " " + re); });
      c.assert.ok(!/<\/(script|style)/i.test(s), f + " </script");
      c.assert.ok(!/^\s*(import|export)\s/m.test(s), f + " ES 모듈 문법(L-27 은 CommonJS 로 검사)");
    });
    c.assert.ok(!/<\/(script|style)/i.test(readText("web/common/lm27.css")));
  });

  t.test("G-R5 외부 참조 0 · G-R7 16진 색은 lm27.css 에만", function (c) {
    var hex = /(^|[^&\w])#([0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})(?![\w-])/;
    WEB_JS.concat(["web/common/icons.svg"]).forEach(function (f) {
      var s = readText(f);
      c.assert.ok(!hex.test(s), f + " 16진 색");
      var urls = s.match(/https?:\/\/[^\s"')]+/g) || [];
      urls.forEach(function (u) { c.assert.ok(/^http:\/\/www\.w3\.org\//.test(u), f + " 외부 참조 " + u); });
    });
    var css = readText("web/common/lm27.css");
    c.assert.ok(!/@import|@font-face|url\(\s*['"]?(https?:)?\/\//i.test(css), "CSS 외부 참조·웹 글꼴");
    c.assert.ok(/color-scheme:\s*light/.test(css));
    c.assert.ok(/--fs-body:\s*16px/.test(css) && /--fs-table:\s*14px/.test(css));
    c.assert.ok(!/--dom-[a-z-]*\s*:/.test(css), "--dom-* 토큰 선언 없음(계약 X-281)");
  });

  t.test("icons.svg — 25개 symbol · 20×20 · currentColor · 스크립트·이벤트 속성 0", function (c) {
    var s = readText("web/common/icons.svg");
    var want = ["i-ok", "i-warn", "i-serious", "i-bad", "i-unknown", "i-run", "i-info", "i-pc", "i-cloud", "i-mail", "i-cal",
      "i-chat", "i-doc", "i-app", "i-person", "i-link", "i-table", "i-download", "i-upload", "i-play", "i-stop", "i-lock",
      "i-expand", "i-collapse", "i-close"];
    var ids = (s.match(/<symbol id="([a-z-]+)" viewBox="0 0 20 20">/g) || []).map(function (m) { return /id="([a-z-]+)"/.exec(m)[1]; });
    c.assert.deepStrictEqual(ids.slice().sort(), want.slice().sort());
    c.assert.ok(!/<script|foreignObject|\son[a-z]+=|xlink:href|<image/i.test(s));
    var fills = s.match(/(fill|stroke)="([^"]+)"/g) || [];
    fills.forEach(function (f) { c.assert.ok(/="(none|currentColor)"$/.test(f), f); });
  });

  t.test("RPT-33·RPT-40 금지 표현 0(대체 가능·절감·AX 가능 MM·개발자에게·재설치)", function (c) {
    WEB_JS.concat(["web/common/lm27.css", "web/common/icons.svg"]).forEach(function (f) {
      var s = readText(f);
      ["대체 가능", "절감", "AX 가능 MM", "개발자에게", "재설치", "[!]"].forEach(function (w) { c.assert.ok(s.indexOf(w) < 0, f + " " + w); });
    });
  });

  // ───────────── tools\check_contrast.py(G-R7) ─────────────
  function runContrast(c, root) {
    var r = cp.spawnSync(c.python, ["-X", "utf8", "-B", "-I", path.join(ROOT, "tools", "check_contrast.py"), "--root", root, "--json"],
      {cwd: require("os").tmpdir(), encoding: "utf8", windowsHide: true});
    return {rc: r.status, out: r.stdout ? JSON.parse(r.stdout) : null, err: r.stderr};
  }
  function miniRoot(c, cssEdit, vocab, extra) {
    var d = c.tmpdir();
    fs.mkdirSync(path.join(d, "web", "common"), {recursive: true});
    var css = readText("web/common/lm27.css");
    fs.writeFileSync(path.join(d, "web", "common", "lm27.css"), cssEdit ? cssEdit(css) : css, "utf8");
    if (vocab) {
      fs.mkdirSync(path.join(d, "lm27", "hier"), {recursive: true});
      fs.writeFileSync(path.join(d, "lm27", "hier", "vocab.py"), vocab, "utf8");
    }
    Object.keys(extra || {}).forEach(function (rel) {
      fs.mkdirSync(path.dirname(path.join(d, rel)), {recursive: true});
      fs.writeFileSync(path.join(d, rel), extra[rel], "utf8");
    });
    return d;
  }
  var GOOD_VOCAB = "DOMAIN_META = {\n" + [["DEV", "2a78d6"], ["MP", "c47400"], ["EXT", "0e8c7a"], ["COM", "a61b4a"], ["AX", "6c4fb8"], ["UNC", "8b929b"]]
    .map(function (p) { return "    \"" + p[0] + "\": {\"name\": \"" + p[0] + "\", \"color\": \"#" + p[1] + "\"},"; }).join("\n") + "\n}\n";

  t.test("G-R7 check_contrast — 트리 통과 · 토큰 변조·영역 색 불일치·16진 위치 실패", function (c) {
    if (!c.python) { c.skip("동봉 파이썬 없음"); }
    var A = c.assert;
    var ok = runContrast(c, ROOT);
    A.strictEqual(ok.rc, 0, JSON.stringify(ok.out && ok.out.errors));
    A.ok(ok.out.ok.length >= 30, "대비 쌍을 모두 다시 계산");
    var good = runContrast(c, miniRoot(c, null, GOOD_VOCAB));
    A.strictEqual(good.rc, 0, JSON.stringify(good.out && good.out.errors));
    A.strictEqual(good.out.warnings.length, 0);
    var noVocab = runContrast(c, miniRoot(c, null, null));
    A.strictEqual(noVocab.rc, 0);
    A.ok(noVocab.out.warnings.some(function (w) { return w.check === "C3"; }), "DOMAIN_META 없으면 경고만");
    var light = runContrast(c, miniRoot(c, function (s) { return s.replace("--ink-muted: #646b75;", "--ink-muted: #8b929b;"); }, GOOD_VOCAB));
    A.strictEqual(light.rc, 1);
    A.ok(light.out.errors.some(function (e) { return e.check === "C2" && e.msg.indexOf("--ink-muted") >= 0; }));
    var orange = runContrast(c, miniRoot(c, null, GOOD_VOCAB.replace("c47400", "e08a00")));
    A.strictEqual(orange.rc, 1);
    A.ok(orange.out.errors.some(function (e) { return e.check === "C3"; }), "MP 원안 주황 = 대비·같은 자리 실패");
    var seq = runContrast(c, miniRoot(c, function (s) { return s.replace("--seq-2: #5598e7;", "--seq-2: #80b4ee;"); }, GOOD_VOCAB));
    A.ok(seq.out.errors.some(function (e) { return e.check === "C4"; }), "순차 이웃 명도 차");
    var place = runContrast(c, miniRoot(c, null, GOOD_VOCAB, {"web/app/app.js": "var c = \"#2a78d6\";\n"}));
    A.ok(place.out.errors.some(function (e) { return e.check === "C6"; }), "lm27.css 밖 16진 색");
    var noScheme = runContrast(c, miniRoot(c, function (s) { return s.replace("color-scheme: light;", ""); }, GOOD_VOCAB));
    A.ok(noScheme.out.errors.some(function (e) { return e.check === "C1"; }));
  });
};
