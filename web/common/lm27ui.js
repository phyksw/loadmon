/*
 * LM27 화면 공용 — 숫자 표시 함수 · 가상 노드 마운트 · 구성 요소 · 상호(위임·툴팁·서랍·표로 보기·키보드).
 * 근거: REPORTS §3.1(표시 반올림 — 파이썬 fmt.py 와 글자 단위로 같음) · §8.2(구성 요소) · §8.5(접근성) · §8.6.2(마운트)
 *       · 부록 A(JS) · 계약 §2.16 · §9.5 · D-12 · L-19 · L-27.
 * 고전 스크립트(import/export 없음). 브라우저 = 전역 LM27UI, node = module.exports(시험 전용).
 * 금지(G-R4): 문자열을 HTML 로 해석하는 모든 API. DOM 은 createElement(NS)·setAttribute·createTextNode 로만 만든다.
 * 16진 색 없음(G-R7) — 색은 lm27.css 의 클래스·토큰으로만.
 */
(function (root, factory) {
  "use strict";
  var api = factory(root);
  if (typeof module === "object" && module && module.exports) {
    module.exports = api;
  } else {
    root.LM27UI = api;
  }
}(typeof self !== "undefined" ? self : this, function (root) {
  "use strict";

  // ───────────────────────── 1. 숫자 표시(정수 half-up — §3.1, 파이썬 = JS) ─────────────────────────
  // 입력은 정수 분(또는 정수 분자·분모). 사람 1명 10년 ≈ 5.3e6 분이라 2^53 안에서 정확하다.
  function fmtH1(min) {
    var q = Math.floor((min * 10 * 2 + 60) / 120);
    return Math.floor(q / 10) + "." + (q % 10);
  }

  function fmtRatio(num, den, digits) {
    if (den <= 0) { return null; }
    var s = Math.pow(10, digits);
    var q = Math.floor((num * s * 2 + den) / (2 * den));
    return digits ? Math.floor(q / s) + "." + String(q % s).padStart(digits, "0") : String(q);
  }

  function fmtMM(envMin, denomMin) { return fmtRatio(envMin, denomMin, 2); }

  function fmtPct(num, den, digits) { return fmtRatio(num * 100, den, digits || 0); }

  function fmtDays(bizMin, stdDayMin) { return fmtRatio(bizMin, stdDayMin || 480, 1); }

  // 부호 있는 값: 절댓값을 같은 함수로 → '+'·'−'(U+2212), 0 은 '±0'
  function fmtSigned(fn, num) {
    var rest = Array.prototype.slice.call(arguments, 2);
    if (num === 0) { return "±0"; }
    var body = fn.apply(null, [Math.abs(num)].concat(rest));
    return (num > 0 ? "+" : "−") + body;
  }

  // JSON 의 소수 값(팀 MM·병행도 등 — 서버가 정수 분에서 계산해 마지막에 나눈 값)을 표시할 때:
  // 1e-6 단위 정수로 바꾼 뒤(Math.round = floor(x + 0.5)) 같은 정수 half-up. 파이썬 대응은 CR(fmt_num).
  function fmtNum(v, digits) {
    if (v === null || v === undefined || typeof v !== "number" || !isFinite(v)) { return null; }
    var n = Math.round(Math.abs(v) * 1000000);
    var s = fmtRatio(n, 1000000, digits);
    return (v < 0 && /[1-9]/.test(s)) ? "−" + s : s;             // 0 으로 반올림되면 부호 없음
  }

  function fmtX(parallel) { var s = fmtNum(parallel, 1); return s === null ? "—" : "×" + s; }

  // 표시 단위 규칙(§3.1 끝): 시간 1자리 h · MM 2자리 · 비율 정수 %(1% 미만이면 1자리) · 자료 없음 '—'
  function hText(min) { return (min === null || min === undefined) ? "—" : fmtH1(min) + "h"; }

  function mmText(envMin, denomMin) { var s = fmtMM(envMin, denomMin); return s === null ? "—" : s + " MM"; }

  function pctText(num, den) {
    if (den === null || den === undefined || den <= 0 || num === null || num === undefined) { return "—"; }
    if (num === 0) { return "0%"; }
    return (num * 100 < den ? fmtPct(num, den, 1) : fmtPct(num, den, 0)) + "%";
  }

  function daysText(bizMin, stdDayMin) {
    return (bizMin === null || bizMin === undefined) ? "—" : fmtDays(bizMin, stdDayMin) + "영업일";
  }

  // 0~1 소수 비중(work_share 등) → 정수 % 글자
  function shareText(share) {
    if (share === null || share === undefined || !isFinite(share)) { return "—"; }
    return fmtRatio(Math.round(share * 1000), 10, 0) + "%";
  }

  // ───────────────────────── 2. 가상 노드와 마운트(§8.6.2) ─────────────────────────
  var SVG_NS = "http://www.w3.org/2000/svg";

  function flat(list, out) {
    for (var i = 0; i < list.length; i++) {
      var c = list[i];
      if (c === null || c === undefined || c === false) { continue; }
      if (Array.isArray(c)) { flat(c, out); } else { out.push(typeof c === "number" ? String(c) : c); }
    }
    return out;
  }

  // 가상 노드 {t, a, c} — lm27charts.js 의 h 와 같은 형(글자 = 문자열 자식)
  function h(tag, attrs, children) {
    return {t: tag, a: attrs || {}, c: flat(children || [], [])};
  }

  var HTML_TAGS = toSet("div span p a button nav header main section article aside footer h1 h2 h3 h4 ul ol li " +
    "table thead tbody tfoot tr th td caption colgroup col small strong b em i code pre label input select option " +
    "textarea form fieldset legend details summary figure figcaption br hr dl dt dd time abbr mark svg");
  var SVG_TAGS = toSet("svg g rect circle ellipse line polyline polygon path text tspan title desc defs pattern use " +
    "symbol clipPath marker");
  // 명세 ATTR_OK + 폼·표 최소 속성. on*·style·src·xlink:href 등은 이름에서 걸러진다.
  var ATTR_OK = new RegExp("^(class|id|x|y|x1|x2|y1|y2|cx|cy|r|rx|ry|width|height|d|points|transform|fill|stroke|" +
    "stroke-width|stroke-dasharray|stroke-linecap|stroke-linejoin|opacity|fill-opacity|stroke-opacity|text-anchor|" +
    "dominant-baseline|font-size|font-weight|viewBox|role|tabindex|aria-[a-z]+|data-[a-z0-9-]+|href|marker-end|" +
    "clip-path|pattern[A-Za-z]*|preserveAspectRatio|focusable|hidden|type|colspan|rowspan|scope|lang|for|name|" +
    "value|placeholder|maxlength|min|max|step|checked|selected|required|readonly|disabled|autocomplete|multiple|" +
    "dx|dy)$");
  var PAINT_OK = /^(?:#[0-9a-fA-F]{6}|url\(#[A-Za-z][A-Za-z0-9_-]*\)|none|currentColor|transparent)$/;

  function toSet(words) {
    var o = Object.create(null);
    words.split(/\s+/).forEach(function (w) { if (w) { o[w] = true; } });
    return o;
  }

  // 속성 하나를 거른다 — 허용 이름만, href 는 '#' 으로 시작할 때만, fill·stroke 는 색·로컬 무늬만
  function attrValue(name, v) {
    if (v === null || v === undefined || v === false) { return null; }
    if (!ATTR_OK.test(name)) { return null; }
    var s = v === true ? "" : String(v);
    if (name === "href") { return s.charAt(0) === "#" ? s : null; }
    if (name === "fill" || name === "stroke") { return PAINT_OK.test(s) ? s : null; }
    return s;
  }

  function tagAllowed(tag, inSvg) {
    return inSvg ? SVG_TAGS[tag] === true : HTML_TAGS[tag] === true;
  }

  function build(v, doc, inSvg) {
    if (v === null || v === undefined || v === false) { return null; }
    if (typeof v === "string" || typeof v === "number") { return doc.createTextNode(String(v)); }
    if (typeof v !== "object" || typeof v.t !== "string") { return null; }
    var svg = inSvg || v.t === "svg";
    if (!tagAllowed(v.t, svg)) { return null; }        // 허용 밖 태그는 자식째 버린다
    var el = svg ? doc.createElementNS(SVG_NS, v.t) : doc.createElement(v.t);
    var a = v.a || {};
    var keys = Object.keys(a).sort();
    for (var i = 0; i < keys.length; i++) {
      var val = attrValue(keys[i], a[keys[i]]);
      if (val !== null) { el.setAttribute(keys[i], val); }
    }
    var kids = v.c || [];
    for (var j = 0; j < kids.length; j++) {
      var ch = build(kids[j], doc, svg);
      if (ch) { el.appendChild(ch); }
    }
    return el;
  }

  function inSvgParent(parent) {
    return !!parent && parent.namespaceURI === SVG_NS;
  }

  // 가상 노드를 parent 아래에 붙인다(마운트 유일원). 만든 노드를 돌려준다.
  function mount(v, parent, inSvg) {
    var doc = parent.ownerDocument || root.document;
    var node = build(v, doc, !!inSvg || inSvgParent(parent));
    if (node) { parent.appendChild(node); }
    return node;
  }

  function clear(el) {
    while (el && el.firstChild) { el.removeChild(el.firstChild); }
    return el;
  }

  // parent 의 자식을 비우고 v 로 바꾼다
  function render(v, parent) {
    clear(parent);
    var list = Array.isArray(v) ? v : [v];
    var out = null;
    for (var i = 0; i < list.length; i++) { out = mount(list[i], parent) || out; }
    return out;
  }

  // ───────────────────────── 3. 구성 요소(§8.2 — 모두 가상 노드를 돌려준다) ─────────────────────────
  function icon(name, label) {
    return h("svg", {"class": "icon", viewBox: "0 0 20 20", focusable: "false",
      "aria-hidden": label ? null : "true", role: label ? "img" : null, "aria-label": label || null},
    [h("use", {href: "#i-" + name})]);
  }

  // 상태 어휘(§5.0.2) — 색은 늘 아이콘·글자와 함께
  var STATES = {
    good: {icon: "ok", text: "정상"}, warn: {icon: "warn", text: "주의"}, serious: {icon: "serious", text: "위험"},
    bad: {icon: "bad", text: "실패"}, unknown: {icon: "unknown", text: "미확인"}, na: {icon: null, text: "해당 없음"},
    run: {icon: "run", text: "진행 중"}
  };
  var VERDICT_STATE = {"가능": "good", "불가(잠정)": "warn", "불가(확정)": "bad", "미확인": "unknown", "해당 없음": "na"};

  function statusText(state, text, iconOnly) {
    var s = STATES[state] || STATES.unknown;
    var label = text || s.text;
    var kids = [s.icon ? icon(s.icon) : h("span", {"class": "st-dash", "aria-hidden": "true"}, ["–"])];
    if (iconOnly) {
      return h("span", {"class": "st st-" + state, role: "img", "aria-label": label, "data-tip": label}, kids);
    }
    kids.push(h("span", {"class": "st-text"}, [label]));
    return h("span", {"class": "st st-" + state}, kids);
  }

  function verdictCell(verdict, iconOnly) {
    return statusText(VERDICT_STATE[verdict] || "unknown", verdict || "미확인", iconOnly);
  }

  function badge(text, kind, tip) {
    return h("span", {"class": "badge" + (kind ? " badge-" + kind : ""), "data-tip": tip || null}, [text]);
  }

  // 단위업무 등급 배지(§8.2.6): A·B 실선 · C 점선(툴팁) · D·E 짧은 점선 + '추정' · O·Z·M 글자
  function gradeBadge(g) {
    if (g === "A" || g === "B") { return badge(g, "grade-solid", "등급 " + g); }
    if (g === "C") { return badge("C", "grade-dash", "한 경계가 추정"); }
    if (g === "D" || g === "E") { return badge(g + " 추정", "grade-dot", "추정 경계"); }
    if (g === "O") { return badge("진행 중 ▸", "grade-open", "진행 중"); }
    if (g === "Z") { return badge("미착수", "grade-none", "미착수"); }
    if (g === "M") { return badge("수동", "grade-manual", "수동 기록"); }
    return badge(g || "—", "grade-none", null);
  }

  // 라벨 출처(§3.5)
  var SOURCE_TEXT = {ai: "AI", manual: "AI(붙여넣기)", rule: "규칙", rule_pending: "규칙", user: "내 지정"};

  function sourceBadge(by) {
    var t = SOURCE_TEXT[by] || "규칙";
    var kind = (by === "ai" || by === "manual") ? "src-ai" : (by === "user" ? "src-user" : "src-rule");
    return badge(t, kind, null);
  }

  // 측정 품질(§4.9·§8.2.6)
  var QUALITY = {reliable: ["good", "신뢰"], caution: ["warn", "주의"], unreliable: ["bad", "측정 불충분"]};

  function qualityBadge(grade) {
    var q = QUALITY[grade] || ["unknown", "미확인"];
    return h("span", {"class": "badge badge-state"}, [statusText(q[0], q[1])]);
  }

  // 판정(서브에이전트) 배지
  var VERDICT = {"적합": "good", "조건부": "warn", "부적합": "bad"};

  function verdictBadge(v) {
    return h("span", {"class": "badge badge-state"}, [statusText(VERDICT[v] || "unknown", v || "미확인")]);
  }

  // CH-P14 칸(HTML 표 칸 — CHARTS 밖, 계약 X-281): 상·중·하·없음 + 규칙 출처 + 불일치 ◇
  function agenticCell(grade, opt) {
    opt = opt || {};
    var cls = {"상": "ag-hi", "중": "ag-mid", "하": "ag-lo"}[grade] || "ag-none";
    var kids = [h("span", {"class": "ag-g"}, [grade || "·"])];
    if (grade && opt.rule) { kids.push(h("small", {"class": "ag-src"}, ["규칙"])); }
    if (grade && opt.disagree) { kids.push(h("span", {"class": "ag-dis", "aria-label": "규칙과 다름", "data-tip": "규칙과 다름"}, ["◇"])); }
    return h("td", {"class": "ag " + cls}, kids);
  }

  // CH-P15 점수 점 3개(0~2). risk 면 '높을수록 나쁨' — 점을 위험 글자색으로, 글자 낮음·중간·높음
  function scoreDots(score, risk) {
    var dots = [];
    for (var i = 0; i < 2; i++) {
      dots.push(h("circle", {cx: 6 + i * 14, cy: 6, r: 5, "class": i < score ? (risk ? "dot-risk" : "dot-on") : "dot-off"}));
    }
    var text = risk ? (["낮음", "중간", "높음"][score] || "—") : String(score);
    return h("span", {"class": "dots"}, [
      h("svg", {"class": "dots-svg", viewBox: "0 0 26 12", width: 26, height: 12, "aria-hidden": "true", focusable: "false"}, dots),
      h("span", {"class": "dots-n"}, [text])]);
  }

  // 알림 줄(§8.2.8): info·warn·bad — role status(정보)·alert(막힘)만
  function alertLine(kind, text) {
    var ic = {info: "info", warn: "warn", bad: "bad"}[kind] || "info";
    return h("div", {"class": "alert alert-" + ic, role: kind === "bad" ? "alert" : "status"},
      [icon(ic), h("span", {}, [text])]);
  }

  // KPI 카드(§8.2.2) — act 가 있으면 버튼(드릴다운)
  function kpiCard(o) {
    var kids = [h("span", {"class": "kpi-label"}, [o.label]),
      h("span", {"class": "kpi-value"}, [o.value === null || o.value === undefined || o.value === "" ? "—" : o.value]),
      o.sub ? h("span", {"class": "kpi-sub", "data-tip": o.sub}, [o.sub]) : null,
      o.badge || null];
    if (o.act) {
      return h("button", {type: "button", "class": "kpi kpi-btn", "data-act": o.act, "data-ref": o.ref || null}, kids);
    }
    return h("div", {"class": "kpi"}, kids);
  }

  // pill 메뉴(§8.2.1). items: [{href:'#home', label, badge, badgeLabel, current, disabled, reason}]
  function pills(items, opt) {
    opt = opt || {};
    var kids = items.map(function (it) {
      var a = {"class": "pill", href: it.href};
      if (it.current) { a["aria-current"] = "page"; }
      if (it.disabled) { a["aria-disabled"] = "true"; a["data-tip"] = it.reason || "지금은 쓸 수 없습니다"; }
      var c = [it.label];
      if (it.badge) { c.push(h("span", {"class": "pill-badge", "aria-label": it.badgeLabel || ("할 일 " + it.badge + "건")}, [String(it.badge)])); }
      return h("a", a, c);
    });
    return h("nav", {"class": "pills" + (opt.small ? " pills-sm" : ""), "aria-label": opt.label || "주 메뉴"}, kids);
  }

  function emptyState(text) { return h("p", {"class": "empty"}, [text]); }

  // 진행 막대 — 폭을 style 로 주지 않고 SVG 좌표로(style 속성은 마운트가 버린다)
  function progressBar(done, total, label) {
    var w = total > 0 ? Math.min(100, Math.round(done * 1000 / total) / 10) : 0;
    return h("div", {"class": "progress", role: "progressbar", "aria-valuemin": "0", "aria-valuemax": String(total),
      "aria-valuenow": String(done), "aria-label": label || "진행"}, [
      h("svg", {viewBox: "0 0 100 8", preserveAspectRatio: "none", "aria-hidden": "true", focusable: "false"}, [
        h("rect", {x: 0, y: 0, width: 100, height: 8, "class": "pg-track"}),
        h("rect", {x: 0, y: 0, width: w, height: 8, "class": "pg-bar"})])]);
  }

  // 펼침 버튼(표 + 펼침, §8.2.4)
  function expandButton(expanded, controls, label, ref) {
    return h("button", {type: "button", "class": "exp", "aria-expanded": expanded ? "true" : "false",
      "aria-controls": controls || null, "aria-label": label || "펼치기", "data-act": "toggle-row", "data-ref": ref || null},
    [expanded ? "▾" : "▸"]);
  }

  // 범례(§8.3 규칙 4) — 견본은 차트와 같은 모양(무늬까지)
  function legendView(legend) {
    if (!legend || !legend.length) { return null; }
    return h("ul", {"class": "legend"}, legend.map(function (it) {
      return h("li", {}, [
        h("svg", {"class": "swatch", viewBox: "0 0 14 14", width: 14, height: 14, "aria-hidden": "true", focusable: "false"},
          it.swatch || []),
        h("span", {}, [it.label])]);
    }));
  }

  // ───────────────────────── 4. 표로 보기(§8.3 규칙 8 — 정렬은 여기서만) ─────────────────────────
  var NUMISH = /^[−+-]?[×]?\d+(?:[.,]\d+)?(?:h|%|일|영업일|MM| MM|분|건|명|배)?$/;

  function sortValue(s) {
    var t = String(s === null || s === undefined ? "" : s).trim();
    if (NUMISH.test(t)) {
      var n = parseFloat(t.replace("−", "-").replace("×", "").replace(",", ""));
      if (isFinite(n)) { return {num: true, v: n}; }
    }
    return {num: false, v: t};
  }

  // 결정적 정렬: 숫자끼리는 값, 그 밖은 글자 비교, 동률은 원래 순번
  function sortRows(rows, col, desc) {
    var idx = rows.map(function (r, i) { return {r: r, i: i, k: sortValue(r[col])}; });
    idx.sort(function (x, y) {
      var c;
      if (x.k.num && y.k.num) { c = x.k.v - y.k.v; } else if (x.k.num !== y.k.num) { c = x.k.num ? -1 : 1; } else {
        c = x.k.v < y.k.v ? -1 : (x.k.v > y.k.v ? 1 : 0);
      }
      if (desc) { c = -c; }
      return c !== 0 ? c : x.i - y.i;
    });
    return idx.map(function (o) { return o.r; });
  }

  // chartResult.table {cols, rows} → <table>. opt {sortCol, desc, limit(500), id}
  function tableView(chartResult, opt) {
    opt = opt || {};
    var t = (chartResult && chartResult.table) || {cols: [], rows: []};
    var rows = (opt.sortCol === null || opt.sortCol === undefined) ? t.rows : sortRows(t.rows, opt.sortCol, !!opt.desc);
    var limit = opt.limit || 500;
    var shown = rows.slice(0, limit);
    var title = (chartResult && chartResult.caption && chartResult.caption.title) || "";
    var head = h("tr", {}, t.cols.map(function (c, i) {
      var sorted = opt.sortCol === i;
      return h("th", {scope: "col", "aria-sort": sorted ? (opt.desc ? "descending" : "ascending") : null}, [
        h("button", {type: "button", "class": "th-sort", "data-act": "table-sort", "data-ref": String(i)}, [c, sorted ? (opt.desc ? " ▾" : " ▴") : ""])]);
    }));
    var body = shown.map(function (r) {
      return h("tr", {}, r.map(function (v, i) {
        return h("td", {"class": sortValue(v).num ? "num" : null, "data-col": String(i)}, [v === null || v === undefined ? "—" : String(v)]);
      }));
    });
    var tools = [];
    if (opt.sortCol !== null && opt.sortCol !== undefined) {
      tools.push(h("button", {type: "button", "class": "btn btn-ghost", "data-act": "table-unsort"}, ["원래 순서"]));
    }
    if (rows.length > shown.length) {
      tools.push(h("button", {type: "button", "class": "btn btn-ghost", "data-act": "table-more"}, ["더 보기(" + limit + ")"]));
    }
    return h("div", {"class": "table-wrap", id: opt.id || null}, [
      h("table", {"class": "tbl"}, [h("caption", {}, [title]), h("thead", {}, [head]), h("tbody", {}, body)]),
      tools.length ? h("div", {"class": "table-tools"}, tools) : null]);
  }

  // 차트 카드 본문: 제목·한 줄 요약·[표로 보기]·그림 또는 표·범례·캡션 줄
  function chartView(result, opt) {
    opt = opt || {};
    var cap = result.caption || {};
    var id = opt.id || "chart";
    var showTable = !!opt.table;
    return h("figure", {"class": "chart-fig", "data-chart": id}, [
      h("div", {"class": "chart-head"}, [
        h("h2", {"class": "chart-title"}, [cap.title || ""]),
        h("button", {type: "button", "class": "btn btn-icon", "data-act": "chart-table", "data-ref": id,
          "aria-pressed": showTable ? "true" : "false", "aria-label": "표로 보기", "data-tip": "표로 보기"}, [icon("table")])]),
      cap.summary ? h("p", {"class": "chart-summary"}, [cap.summary]) : null,
      showTable ? tableView(result, opt.tableOpt) : h("div", {"class": "chart-body"}, [result.svg]),
      legendView(result.legend),
      (cap.notes && cap.notes.length) ? h("figcaption", {"class": "chart-notes"}, cap.notes.map(function (n) {
        return h("p", {}, [n]);
      })) : null]);
  }

  // ───────────────────────── 5. 상호 — 위임·툴팁·서랍·키보드 ─────────────────────────
  function closestAttr(el, attr, stop) {
    while (el && el !== stop && el.nodeType === 1) {
      if (el.hasAttribute && el.hasAttribute(attr)) { return el; }
      el = el.parentNode;
    }
    return null;
  }

  function isNativeButton(el) {
    var t = (el.tagName || "").toLowerCase();
    return t === "button" || t === "a" || t === "input" || t === "select" || t === "textarea";
  }

  // 방향키 이동 대상 고르기(순수): marks [{row, x}], cur {row, x}, key → 인덱스 또는 -1
  // ←/→ 같은 행 앞뒤 마크, ↑/↓ 이웃 행에서 x 가 가장 가까운 마크(동률은 왼쪽)
  function navPick(marks, cur, key) {
    var best = -1;
    var i;
    if (key === "ArrowLeft" || key === "ArrowRight") {
      var right = key === "ArrowRight";
      for (i = 0; i < marks.length; i++) {
        var m = marks[i];
        if (m.row !== cur.row || m === cur) { continue; }
        if (right ? m.x > cur.x : m.x < cur.x) {
          if (best < 0 || (right ? m.x < marks[best].x : m.x > marks[best].x)) { best = i; }
        }
      }
      return best;
    }
    if (key === "ArrowUp" || key === "ArrowDown") {
      var down = key === "ArrowDown";
      var target = null;
      for (i = 0; i < marks.length; i++) {
        var r = marks[i].row;
        if (down ? r > cur.row : r < cur.row) {
          if (target === null || (down ? r < target : r > target)) { target = r; }
        }
      }
      if (target === null) { return -1; }
      for (i = 0; i < marks.length; i++) {
        if (marks[i].row !== target) { continue; }
        var d = Math.abs(marks[i].x - cur.x);
        var bd = best < 0 ? Infinity : Math.abs(marks[best].x - cur.x);
        if (d < bd || (d === bd && marks[i].x < marks[best].x)) { best = i; }
      }
      return best;
    }
    return -1;
  }

  function navMove(box, curEl, key) {
    var els = box.querySelectorAll("[data-nav-row]");
    var marks = [];
    var cur = null;
    for (var i = 0; i < els.length; i++) {
      var m = {row: +els[i].getAttribute("data-nav-row"), x: +els[i].getAttribute("data-nav-x"), el: els[i]};
      marks.push(m);
      if (els[i] === curEl) { cur = m; }
    }
    if (!cur) { return null; }
    var k = navPick(marks, cur, key);
    return k < 0 ? null : marks[k].el;
  }

  var tip = {el: null, target: null};

  function hideTip() {
    if (tip.el) { tip.el.setAttribute("hidden", ""); }
    tip.target = null;
  }

  // 툴팁(§8.2.10): 첫 줄 굵게, 'a\tb' 줄은 이름·값 쌍, 글자로만(textContent)
  function tooltip(target, lines) {
    var doc = target.ownerDocument || root.document;
    if (!tip.el || !tip.el.isConnected || tip.el.ownerDocument !== doc) {
      tip.el = mount(h("div", {"class": "lm27-tip", role: "tooltip", id: "lm27-tip", hidden: true}), doc.body);
    }
    var kids = lines.map(function (ln, i) {
      if (i === 0) { return h("strong", {"class": "tip-head"}, [ln]); }
      var p = String(ln).split("\t");
      if (p.length === 2) { return h("div", {"class": "tip-row"}, [h("span", {}, [p[0]]), h("span", {"class": "num"}, [p[1]])]); }
      return h("div", {"class": "tip-line"}, [ln]);
    });
    render(h("div", {}, kids), tip.el);
    tip.el.removeAttribute("hidden");
    tip.target = target;
    var r = target.getBoundingClientRect();
    var tw = tip.el.offsetWidth;
    var th = tip.el.offsetHeight;
    var vw = (doc.documentElement && doc.documentElement.clientWidth) || 1024;
    var sx = (doc.defaultView && doc.defaultView.pageXOffset) || 0;
    var sy = (doc.defaultView && doc.defaultView.pageYOffset) || 0;
    var left = Math.max(4, Math.min(vw - tw - 4, r.left + r.width / 2 - tw / 2));
    var top = r.top - th - 8;
    if (top < 4) { top = r.bottom + 8; }                    // 위로 넘치면 아래로 뒤집는다
    // 위치는 CSSOM 숫자로만 준다(style 속성 문자열을 만들지 않음)
    tip.el.style.left = Math.round(left + sx) + "px";
    tip.el.style.top = Math.round(top + sy) + "px";
    return tip.el;
  }

  function tipFromEvent(ev, rootEl) {
    var el = closestAttr(ev.target, "data-tip", rootEl === undefined ? null : rootEl.parentNode);
    if (!el) { return; }
    if (tip.target === el) { return; }
    var text = el.getAttribute("data-tip");
    if (text) { tooltip(el, text.split("\n")); }
  }

  // 위임 하나(§8.6.2): click·keydown·mouseover·focusin. handlers[data-act](el, data-ref, ev)
  // 특수 이름: handlers.escape(ev), handlers.nav(el, nextEl) — 방향키 이동 뒤
  function delegate(rootEl, handlers) {
    function act(ev) {
      var el = closestAttr(ev.target, "data-act", rootEl.parentNode);
      if (!el || !rootEl.contains(el)) { return false; }
      if (el.getAttribute("aria-disabled") === "true") { return true; }
      var fn = handlers[el.getAttribute("data-act")];
      if (!fn) { return false; }
      ev.preventDefault();
      fn(el, el.getAttribute("data-ref"), ev);
      return true;
    }
    function onClick(ev) { act(ev); }
    function onKey(ev) {
      if (ev.key === "Escape") {
        hideTip();
        if (handlers.escape) { handlers.escape(ev); }
        return;
      }
      if ((ev.key === "Enter" || ev.key === " ") && !isNativeButton(ev.target)) {
        if (act(ev)) { return; }
      }
      if (/^Arrow/.test(ev.key) && ev.target && ev.target.hasAttribute && ev.target.hasAttribute("data-nav-row")) {
        var box = closestAttr(ev.target, "data-nav", rootEl.parentNode);
        var nx = box ? navMove(box, ev.target, ev.key) : null;
        if (nx) {
          ev.preventDefault();
          nx.focus();
          if (handlers.nav) { handlers.nav(ev.target, nx); }
        }
      }
    }
    function onOver(ev) { tipFromEvent(ev, rootEl); }
    function onOut(ev) {
      var to = ev.relatedTarget;
      if (tip.target && (!to || !tip.target.contains(to))) { hideTip(); }
    }
    rootEl.addEventListener("click", onClick);
    rootEl.addEventListener("keydown", onKey);
    rootEl.addEventListener("mouseover", onOver);
    rootEl.addEventListener("focusin", onOver);
    rootEl.addEventListener("mouseout", onOut);
    rootEl.addEventListener("focusout", onOut);
    return function off() {
      rootEl.removeEventListener("click", onClick);
      rootEl.removeEventListener("keydown", onKey);
      rootEl.removeEventListener("mouseover", onOver);
      rootEl.removeEventListener("focusin", onOver);
      rootEl.removeEventListener("mouseout", onOut);
      rootEl.removeEventListener("focusout", onOut);
    };
  }

  // 서랍(§8.2.7): role=dialog · aria-modal=false · 열면 제목에 초점 · Esc·[닫기]로 닫고 연 요소로 초점 복귀
  var drawer = {el: null, prev: null, onClose: null, off: null};

  function closeDrawer() {
    if (!drawer.el) { return; }
    var el = drawer.el;
    var prev = drawer.prev;
    var cb = drawer.onClose;
    if (drawer.off) { drawer.off(); }
    drawer.el = drawer.prev = drawer.onClose = drawer.off = null;
    if (el.parentNode) { el.parentNode.removeChild(el); }
    if (prev && prev.focus && prev.isConnected) { prev.focus(); }
    if (cb) { cb(); }
  }

  function openDrawer(contentVnode, opts) {
    opts = opts || {};
    var doc = opts.doc || root.document;
    var prev = opts.returnFocus || doc.activeElement;
    closeDrawer();
    var tid = "lm27-drawer-title";
    var v = h("div", {"class": "drawer" + (opts.wide ? " drawer-wide" : ""), role: "dialog", "aria-modal": "false",
      "aria-labelledby": tid}, [
      h("div", {"class": "drawer-head"}, [
        h("h2", {id: tid, tabindex: "-1"}, [opts.title || ""]),
        h("button", {type: "button", "class": "btn btn-ghost", "data-act": "drawer-close"}, [icon("close"), "닫기"])]),
      h("div", {"class": "drawer-body"}, [contentVnode])]);
    var el = mount(v, doc.body);
    drawer.el = el;
    drawer.prev = prev;
    drawer.onClose = opts.onClose || null;
    var handlers = {"drawer-close": function () { closeDrawer(); }, escape: function () { closeDrawer(); }};
    if (opts.handlers) {
      Object.keys(opts.handlers).forEach(function (k) { handlers[k] = opts.handlers[k]; });
    }
    drawer.off = delegate(el, handlers);
    var t = doc.getElementById(tid);
    if (t) { t.focus(); }
    return {el: el, close: closeDrawer};
  }

  // pill 메뉴 현재 표시 바꾸기
  function setCurrent(nav, hash) {
    var as = nav.querySelectorAll("a.pill");
    for (var i = 0; i < as.length; i++) {
      if (as[i].getAttribute("href") === hash) { as[i].setAttribute("aria-current", "page"); } else {
        as[i].removeAttribute("aria-current");
      }
    }
  }

  // ───────────────────────── 6. 데이터 섬·무늬 정의 ─────────────────────────
  // 데이터 섬(<script type="application/json">)은 글자로 읽어 JSON 으로만 해석한다(§9.4). 없거나 깨지면 null.
  function readIsland(id, doc) {
    var d = doc || root.document;
    var el = d && d.getElementById(id);
    if (!el) { return null; }
    try {
      return JSON.parse(el.textContent || "null");
    } catch (e) {
      return null;
    }
  }

  // §8.1.4 무늬 <defs> 를 페이지에 한 번. display:none 인 SVG 안의 무늬는 Chromium 이 그리지 않으므로
  // 크기 0 클래스(lm27-defs)의 SVG 에 둔다. 무늬 정의 원천은 lm27charts.js patternDefs() 하나.
  function ensureDefs(doc, chartsApi) {
    var d = doc || root.document;
    if (!d || d.getElementById("hatch-est")) { return true; }
    var charts = chartsApi || root.LM27Charts;
    if (!charts || !charts.patternDefs) { return false; }
    mount(h("svg", {"class": "lm27-defs", width: 0, height: 0, "aria-hidden": "true", focusable: "false"},
      [charts.patternDefs()]), d.body);
    return true;
  }

  return {
    // 숫자(§3.1)
    fmtH1: fmtH1, fmtRatio: fmtRatio, fmtMM: fmtMM, fmtPct: fmtPct, fmtDays: fmtDays, fmtSigned: fmtSigned,
    fmtNum: fmtNum, fmtX: fmtX, hText: hText, mmText: mmText, pctText: pctText, daysText: daysText, shareText: shareText,
    // 가상 노드·마운트
    h: h, mount: mount, render: render, clear: clear, attrValue: attrValue, tagAllowed: tagAllowed, ATTR_OK: ATTR_OK,
    SVG_NS: SVG_NS,
    // 구성 요소
    icon: icon, statusText: statusText, verdictCell: verdictCell, badge: badge, gradeBadge: gradeBadge,
    sourceBadge: sourceBadge, qualityBadge: qualityBadge, verdictBadge: verdictBadge, agenticCell: agenticCell,
    scoreDots: scoreDots, alertLine: alertLine, kpiCard: kpiCard, pills: pills, emptyState: emptyState,
    progressBar: progressBar, expandButton: expandButton, legendView: legendView, tableView: tableView,
    chartView: chartView, sortRows: sortRows, STATES: STATES,
    // 상호
    delegate: delegate, tooltip: tooltip, hideTip: hideTip, openDrawer: openDrawer, closeDrawer: closeDrawer,
    navPick: navPick, navMove: navMove, setCurrent: setCurrent,
    // 섬·무늬
    readIsland: readIsland, ensureDefs: ensureDefs
  };
}));
