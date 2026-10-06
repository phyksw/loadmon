/*
 * LM27 개인 보고서 화면 — 로컬 앱과 자기완결 HTML 이 같은 파일이다(데이터 출처만 API ↔ 데이터 섬).
 * 근거: REPORTS §6(구성 전부) · §5.4 · §3.1(표시 함수) · §3.4~§3.6(관측·추정·출처·이름) · §8.2 · §8.5 · §9.4(섬)
 *       · §11(예외) · 계약 §9.5 · D-12.
 * 구조: ① kit — 작은 구성 요소(app.js 도 이것을 쓴다) ② 모델 색인(순수) ③ 절 보기(순수: 모델·상태·환경 → 가상 노드)
 *       ④ create(el, opts) — 상태·위임 이벤트·드릴다운·쓰기(로컬 앱만) ⑤ boot(doc) — 자기완결 HTML(섬이 있으면 자동).
 * DOM 은 lm27ui.js 의 mount·render 로만 만든다(문자열을 HTML 로 해석하는 API 0 — G-R4). 숫자 글자는 lm27ui 표시 함수로만(G-R11).
 * 색은 lm27.css 클래스와 모델 domains[].color 뿐(16진 리터럴 0 — G-R7). 영역 이름은 모델 domains[] 에서만(L-25).
 * 고전 스크립트(import·export 문 없음 — L-27). 브라우저 = 전역 LM27Report, node = module.exports(시험 전용).
 */
(function (root, factory) {
  "use strict";
  var api = factory(root);
  if (typeof module === "object" && module && module.exports) {
    module.exports = api;
  } else {
    root.LM27Report = api;
    api.autoBoot(root.document);
  }
}(typeof self !== "undefined" ? self : this, function (root) {
  "use strict";

  // ───────────────────────── 0. 의존(lm27ui · lm27charts) ─────────────────────────
  var DEPS = null;

  function deps() {
    if (DEPS) { return DEPS; }
    var u;
    var c;
    if (typeof module === "object" && module && module.exports && typeof require === "function") {
      u = require("../common/lm27ui.js");
      c = require("../common/lm27charts.js");
    } else {
      u = root.LM27UI;
      c = root.LM27Charts;
    }
    if (!u || !c) { throw new Error("lm27ui.js 와 lm27charts.js 를 먼저 불러야 합니다"); }
    DEPS = {U: u, C: c};
    return DEPS;
  }

  function U() { return deps().U; }
  function C() { return deps().C; }
  function h(t, a, c) { return deps().U.h(t, a, c); }

  // ───────────────────────── 1. 작은 도우미 ─────────────────────────
  function arr(x) { return Array.isArray(x) ? x : []; }
  function obj(x) { return x && typeof x === "object" && !Array.isArray(x) ? x : {}; }
  function isNum(x) { return typeof x === "number" && isFinite(x); }
  function num(x) { return isNum(x) ? x : 0; }
  function str(x) { return x === null || x === undefined ? "" : String(x); }
  function cmp(a, b) { return a < b ? -1 : (a > b ? 1 : 0); }
  function sumBy(list, fn) { var s = 0; arr(list).forEach(function (x) { s += num(fn(x)); }); return s; }

  function uniq(list) {
    var seen = Object.create(null);
    return arr(list).filter(function (x) {
      var k = String(x);
      if (seen[k]) { return false; }
      seen[k] = true;
      return true;
    });
  }

  // 'YYYY-MM-DDTHH:MM…' → 'MM-DD HH:MM'(시각이 없으면 'MM-DD')
  function mdhm(s) {
    s = str(s);
    if (s.length >= 16 && (s.charAt(10) === "T" || s.charAt(10) === " ")) { return s.slice(5, 10) + " " + s.slice(11, 16); }
    return s.length >= 10 ? s.slice(5, 10) : s;
  }

  // 받침 유무로 조사 고르기(한글이 아니면 받침 없음으로 본다)
  function josa(word, withB, withoutB) {
    var s = str(word);
    var c = s.charCodeAt(s.length - 1);
    var has = c >= 0xAC00 && c <= 0xD7A3 && (c - 0xAC00) % 28 !== 0;
    return s + (has ? withB : withoutB);
  }

  function toRo(word) {                      // '으로'·'로'(ㄹ 받침은 '로')
    var s = str(word);
    var c = s.charCodeAt(s.length - 1);
    var jong = c >= 0xAC00 && c <= 0xD7A3 ? (c - 0xAC00) % 28 : 0;
    return s + (jong && jong !== 8 ? "으로" : "로");
  }

  function walk(node, fn) {
    var kids = node && node.childNodes ? node.childNodes : [];
    for (var i = 0; i < kids.length; i++) {
      if (kids[i].nodeType === 1) {
        fn(kids[i]);
        walk(kids[i], fn);
      }
    }
  }

  function closestAttr(el, attr, stop) {
    while (el && el !== stop && el.nodeType === 1) {
      if (el.hasAttribute && el.hasAttribute(attr)) { return el; }
      el = el.parentNode;
    }
    return null;
  }

  // 다시 그리기 전후로 입력값·초점을 보존한다(배경 갱신이 사용자가 쓰던 글을 지우지 않게)
  function collectValues(rootEl) {
    var out = {};
    walk(rootEl, function (n) {
      var t = (n.tagName || "").toLowerCase();
      var id = n.getAttribute && n.getAttribute("id");
      if (!id || (t !== "input" && t !== "select" && t !== "textarea")) { return; }
      var type = (n.getAttribute("type") || "").toLowerCase();
      out[id] = (type === "checkbox" || type === "radio") ? {checked: !!n.checked} : {value: n.value};
    });
    return out;
  }

  function restoreValues(rootEl, vals, skip) {
    if (!vals) { return; }
    walk(rootEl, function (n) {
      var id = n.getAttribute && n.getAttribute("id");
      if (!id || !Object.prototype.hasOwnProperty.call(vals, id) || (skip && skip[id])) { return; }
      var v = vals[id];
      if (Object.prototype.hasOwnProperty.call(v, "checked")) { n.checked = v.checked; } else if (v.value !== undefined) {
        n.value = v.value;
      }
    });
  }

  function focusKeyOf(active, rootEl) {
    if (!active || !rootEl || active === rootEl || !rootEl.contains || !rootEl.contains(active) || !active.getAttribute) { return null; }
    var id = active.getAttribute("id");
    if (id) { return {id: id}; }
    var tr = active.getAttribute("data-tree");
    if (tr) { return {tree: tr}; }
    var a = active.getAttribute("data-act");
    if (a) { return {act: a, ref: active.getAttribute("data-ref")}; }
    return null;
  }

  function restoreFocus(rootEl, k) {
    if (!k) { return; }
    var found = null;
    walk(rootEl, function (n) {
      if (found || !n.getAttribute) { return; }
      if (k.id && n.getAttribute("id") === k.id) { found = n; } else if (k.tree && n.getAttribute("data-tree") === k.tree) {
        found = n;
      } else if (k.act && n.getAttribute("data-act") === k.act && n.getAttribute("data-ref") === k.ref) { found = n; }
    });
    if (found && found.focus) { found.focus(); }
  }

  function storeGet(storage, k) {
    try {
      return storage ? storage.getItem(k) : null;
    } catch (e) {
      return null;                                   // 저장소 막힘 — 기본값으로 동작(R §11)
    }
  }

  function storeSet(storage, k, v) {
    try {
      if (storage) { storage.setItem(k, v); }
      return true;
    } catch (e) {
      return false;
    }
  }

  // ───────────────────────── 2. kit — 구성 요소(가상 노드, §8.2) ─────────────────────────
  function emptyP(text) { return U().emptyState(text); }
  function para(text, cls) { return h("p", {"class": cls || null}, [text]); }
  function muted(text) { return h("p", {"class": "muted small"}, [text]); }
  function link(text, href) { return h("a", {href: href}, [text]); }

  // 카드(§8.2.3 — LM24 .card): 제목 h2 + 오른쪽 상태 글자 + 도구. o.cls = 덧붙일 클래스(예 card-bare — 테두리 없는 KPI 줄)
  function card(title, body, o) {
    o = o || {};
    var hid = o.id ? o.id + "-h" : null;
    return h("section", {"class": "card" + (o.cls ? " " + o.cls : ""), id: o.id || null, "aria-labelledby": title && hid ? hid : null}, [
      title ? h("div", {"class": "card-head"}, [h("h2", {id: hid}, [title]),
        o.state ? h("span", {"class": "state"}, [o.state]) : null,
        o.tools && o.tools.length ? h("div", {"class": "tools"}, o.tools) : null]) : null,
      body]);
  }

  // 버튼(§8.2.5): kind = primary·ghost·danger·icon. why 가 있으면 aria-disabled + 이유 툴팁(이유 없는 회색 버튼 금지)
  function btn(label, act, ref, o) {
    o = o || {};
    return h("button", {type: "button", "class": "btn" + (o.kind ? " btn-" + o.kind : ""), id: o.id || null,
      "data-act": act, "data-ref": ref === undefined || ref === null ? null : String(ref),
      "aria-disabled": o.why ? "true" : null, "data-tip": o.why || o.tip || null, "aria-label": o.aria || null,
      "aria-pressed": o.pressed === undefined ? null : (o.pressed ? "true" : "false"),
      "aria-expanded": o.expanded === undefined ? null : (o.expanded ? "true" : "false"), tabindex: o.tabindex || null},
    [o.icon ? U().icon(o.icon) : null, label]);
  }

  function cellVal(v) { return v === null || v === undefined || v === "" ? "—" : v; }

  // 표(§8.2.4) — cols: 글자 또는 {label, num}. rows: 칸 배열 또는 {cells, attrs, detail, detailId}.
  // 500행(설정 ui.tableMaxRows 를 서버가 주면 그 값)을 넘으면 앞부분 + [더 보기] — 화면은 행 순서를 바꾸지 않는다
  function table(cols, rows, o) {
    o = o || {};
    var limit = o.limit || 500;
    var shown = rows.length > limit ? rows.slice(0, limit) : rows;
    var head = h("tr", {}, cols.map(function (c) {
      var t = typeof c === "string" ? {label: c} : c;
      return h("th", {scope: "col", "class": t.num ? "num" : null}, [t.label]);
    }));
    var body = [];
    shown.forEach(function (r) {
      var row = Array.isArray(r) ? {cells: r} : r;
      body.push(h("tr", row.attrs || {}, row.cells.map(function (v, i) {
        var t = typeof cols[i] === "string" ? {} : (cols[i] || {});
        return h("td", {"class": t.num ? "num" : null}, [cellVal(v)]);
      })));
      if (row.detail) {
        body.push(h("tr", {"class": "detail", id: row.detailId || null}, [h("td", {colspan: String(cols.length)}, [row.detail])]));
      }
    });
    var more = rows.length > shown.length && o.moreAct ?
      h("div", {"class": "table-tools"}, [btn("더 보기(" + limit + ")", o.moreAct, o.id || "")]) : null;
    return h("div", {"class": "table-wrap", id: o.id || null}, [
      h("table", {"class": "tbl", "aria-label": o.label || null}, [o.caption ? h("caption", {}, [o.caption]) : null,
        h("thead", {}, [head]), h("tbody", {}, body)]), more]);
  }

  function errLine(id, text) {
    return text ? h("p", {"class": "field-error", id: id + "-err", role: "alert"}, [U().icon("bad"), h("span", {}, [text])]) : null;
  }

  // 입력 칸(§8.2.5): 라벨은 위, 오류 글자는 아래(✕ 아이콘 + 글자) — KB-9 낭독
  function field(id, label, control, o) {
    o = o || {};
    return h("div", {"class": "field"}, [h("label", {"for": id}, [label]), control,
      o.help ? h("p", {"class": "muted small", id: id + "-help"}, [o.help]) : null, errLine(id, o.error)]);
  }

  function input(id, type, value, attrs) {
    var a = {id: id, name: id, type: type || "text", value: value === null || value === undefined ? null : String(value)};
    Object.keys(attrs || {}).forEach(function (k) { a[k] = attrs[k]; });
    return h("input", a);
  }

  function checkbox(id, label, checked, attrs) {
    var a = {id: id, name: id, type: "checkbox", checked: checked ? true : null};
    Object.keys(attrs || {}).forEach(function (k) { a[k] = attrs[k]; });
    return h("label", {"for": id, "class": "check"}, [h("input", a), label]);
  }

  function select(id, options, value, attrs) {
    var a = {id: id, name: id};
    Object.keys(attrs || {}).forEach(function (k) { a[k] = attrs[k]; });
    return h("select", a, options.map(function (op) {
      return h("option", {value: String(op[0]), selected: String(op[0]) === String(value) ? true : null}, [op[1]]);
    }));
  }

  function textarea(id, value, attrs) {
    var a = {id: id, name: id};
    Object.keys(attrs || {}).forEach(function (k) { a[k] = attrs[k]; });
    return h("textarea", a, [value === null || value === undefined ? "" : String(value)]);
  }

  // 카드 안 토글 묶음(aria-pressed + 글자 표식 ✓ — 색만으로 구분하지 않음)
  function toggles(label, items, cur, act) {
    return h("div", {"class": "table-tools", role: "group", "aria-label": label}, items.map(function (it) {
      var on = String(it[0]) === String(cur);
      return h("button", {type: "button", "class": "btn btn-ghost", "aria-pressed": on ? "true" : "false",
        "data-act": act, "data-ref": String(it[0])}, [on ? "✓ " + it[1] : it[1]]);
    }));
  }

  function chips(list) {
    var items = arr(list).filter(function (x) { return x !== null && x !== undefined && x !== ""; });
    return items.length ? h("ul", {"class": "legend"}, items.map(function (x) { return h("li", {}, [x]); })) : null;
  }

  function dl(pairs) {
    var kids = [];
    arr(pairs).forEach(function (p) {
      if (!p) { return; }
      kids.push(h("dt", {}, [p[0]]));
      kids.push(h("dd", {}, [cellVal(p[1])]));
    });
    return h("dl", {}, kids);
  }

  // 관측/추정 비율 막대(60px — 채움 = 관측, 빗금 = 추정 · §3.4)
  function oiBar(obs, est) {
    obs = num(obs);
    est = num(est);
    var tot = obs + est;
    if (!(tot > 0)) { return null; }
    var w = C().round1(60 * obs / tot);
    return h("svg", {"class": "oi-bar", viewBox: "0 0 60 10", width: 60, height: 10, role: "img", focusable: "false",
      "aria-label": "관측 " + U().pctText(obs, tot) + " · 추정 " + U().pctText(est, tot)}, [
      h("rect", {x: 0, y: 0, width: 60, height: 10, "class": "f-blue"}),
      est > 0 ? h("rect", {x: w, y: 0, width: C().round1(60 - w), height: 10, fill: "url(#hatch-est)"}) : null]);
  }

  // 0~1 비중 막대(60px, 단색)
  function shareBar(share) {
    var w = C().round1(60 * Math.max(0, Math.min(1, num(share))));
    return h("svg", {viewBox: "0 0 60 10", width: 60, height: 10, "aria-hidden": "true", focusable: "false"}, [
      h("rect", {x: 0, y: 0, width: 60, height: 10, "class": "f-surface-2"}),
      h("rect", {x: 0, y: 0, width: w, height: 10, "class": "f-blue"})]);
  }

  // 업무 영역 색 칩 — 모델 값만(^#[0-9a-f]{6}$ 검사 뒤, 아니면 중립)
  function domChip(color) {
    var ok = /^#[0-9a-f]{6}$/.test(str(color));
    return h("svg", {"class": "swatch", viewBox: "0 0 12 12", width: 12, height: 12, "aria-hidden": "true", focusable: "false"}, [
      h("rect", ok ? {x: 0, y: 0, width: 12, height: 12, rx: 2, fill: color} : {x: 0, y: 0, width: 12, height: 12, rx: 2, "class": "f-faint"})]);
  }

  // 분류 신뢰 분포(서열 5칸 — 확인됨 seq-5 · 높음 seq-4 · 보통 seq-2 · 낮음 seq-1 · 미분류 흰 칸 + 점선 테두리)
  function levelBar(dist, uncText) {
    var tot = 0;
    LEVELS.forEach(function (l) { tot += num(obj(dist)[l[0]]); });
    if (!(tot > 0)) { return null; }
    var x = 0;
    var parts = [];
    var tip = [];
    LEVELS.forEach(function (l) {
      var v = num(obj(dist)[l[0]]);
      var name = l[1] || uncText;
      tip.push(name + " " + U().pctText(v, tot));
      if (!(v > 0)) { return; }
      var w = 80 * v / tot;
      parts.push(l[0] === "unclassified" ?
        h("rect", {x: C().round1(x + 0.5), y: 0.5, width: C().round1(Math.max(0, w - 1)), height: 9, "class": "f-surface s-border-strong",
          "stroke-width": 1, "stroke-dasharray": "2 2"}) :
        h("rect", {x: C().round1(x), y: 0, width: C().round1(w), height: 10, "class": l[2]}));
      x += w;
    });
    return h("span", {"class": "lvl", role: "img", "aria-label": tip.join(" · "), "data-tip": tip.join("\n"), tabindex: "0"}, [
      h("svg", {viewBox: "0 0 80 10", width: 80, height: 10, "aria-hidden": "true", focusable: "false"}, parts)]);
  }

  // ───────────────────────── 3. 상수(화면 문구 — R §5·§6) ─────────────────────────
  var ALL = "all";
  var STORE_KEY = "lm27.report.month";
  var SECTIONS = [["summary", "요약"], ["tree", "업무 트리"], ["workflow", "워크플로우"], ["review", "리뷰"], ["peers", "동료"],
    ["graph", "연관 그래프"], ["agentic", "Agentic"], ["subagent", "서브에이전트"], ["queue", "확인 질문"], ["hier", "분류"],
    ["evidence", "근거"]];
  var MONTH_SECTIONS = {summary: true, tree: true, workflow: true, agentic: true, subagent: true};
  var TAG_KEYS = ["regular", "extended", "night", "holiday"];
  var TAG_NAME = {regular: "정규", extended: "연장", night: "야간", holiday: "휴일"};
  var BUCKETS = ["B_GENERIC", "B_COMM", "B_MEET", "B_OFFPC", "B_UNKNOWN"];
  var BUCKET_NAME = {B_GENERIC: "일반 앱", B_COMM: "소통", B_MEET: "회의", B_OFFPC: "PC 밖", B_UNKNOWN: "미상"};
  var STATUS_NAME = {closed: "완료", estimated: "추정 종료", open: "진행 중", not_started: "미착수"};
  var LEVELS = [["confirmed", "확인됨", "f-seq-5"], ["high", "높음", "f-seq-4"], ["medium", "보통", "f-seq-2"],
    ["low", "낮음", "f-seq-1"], ["unclassified", "", "f-surface"]];
  var GRADE_NAME = {reliable: ["good", "신뢰"], caution: ["warn", "주의"], unreliable: ["bad", "측정 불충분"]};
  var REC_KIND = {same: ["같은 일 의심", "같은 일이 둘로 나뉘었을 수 있습니다"], same_work: ["같은 일 의심", "같은 일이 둘로 나뉘었을 수 있습니다"],
    chain: ["이어진 일", "앞뒤로 이어진 일입니다(인계)"], reference: ["참고할 일", "다른 과제에서 같은 문서를 썼습니다"],
    ref: ["참고할 일", "다른 과제에서 같은 문서를 썼습니다"], related: ["관련 일", "같은 사람·도구를 공유합니다"]};
  var RELS = ["의뢰함", "보고함", "산출함", "사용함", "함께함", "선행함", "같은문서"];
  // 판정 근거 코드 → 이름(lm27\report\vocab.py SUB_WHY·RULE_WHY 와 같은 표 — CSV 와 화면이 같은 말을 쓴다)
  var SUB_WHY = {digital_io: "입출력 디지털", repeat_weekly: "주 1회 이상 반복", repeat_monthly: "월 1회 이상 반복",
    structured_input: "정형 입력", low_accountability: "책임 낮음", verifiable: "검증 가능", tool_access: "도구 접근 가능"};
  var RULE_WHY = {type: "단계 유형 일치", input: "입력 일치", output: "출력 일치", keyword: "핵심어 일치"};
  var AXIS_SHORT = {mail_out: "메일 발신", mail_in: "메일 받음", cal: "일정", teams: "팀즈", pc: "PC"};
  // 봉투 근거 코드(WORKTIME §4 봉투 표) → 이름 — 날짜 원장 구성 줄에 코드 대신
  var BASIS_NAME = {C1: "샘플러 활동", C1b: "샘플러 다리", C2: "회의", C3: "앵커 세션", C4: "원격 발신", C4L: "원격 연결 다리",
    C5: "수신 크레딧", C6: "사슬 다리", C7: "PC 다리", C8: "PC 하한", C8d: "date-only 하한", C9: "수신 사슬 하한", C10: "흔적 창",
    C10r: "원격 흔적 창", C11: "수동·종일 외근", C12: "솔버 cap"};
  var LEVEL_KEYS = ["L1", "L2", "L3", "L4", "L5", "L6", "L7"];
  var LEVEL_NOTE = {L1: "수동 기록(관측)", L2: "회의(관측, 분할은 추정)", L3: "PC 맥락(관측)", L4: "앵커 직전 창(추정)",
    L5: "흡수·공백(추정)", L6: "비례(추정)", L7: "버킷(미귀속)"};
  var MAJOR = "1";                                    // 화면이 읽는 보고서 모델 주판(lm27.report 1.x)

  // 측정 품질 사유 → 화면 문구(R §4.9 표 — 모델이 reason_text 를 주면 그것을 쓴다)
  var QUALITY_TEXT = {
    pc_cov_bad: "PC 기록이 있는 근무일이 {pc} 입니다 — 에이전트가 없던 PC·기간이 있습니다",
    pc_cov_low: "PC 기록이 있는 근무일이 {pc} 입니다 — 에이전트가 없던 PC·기간이 있습니다",
    comms_cov_bad: "메일 발신·팀즈 기록이 모두 절반 넘게 비었습니다 — 홈의 능력 표에서 막힌 출처를 확인하세요",
    mail_cov_low: "메일 발신 기록이 비어 있는 근무일이 있습니다({mail_out})",
    teams_cov_low: "팀즈 기록이 비어 있는 근무일이 있습니다({teams})",
    cal_cov_low: "일정 기록이 비어 있는 근무일이 있습니다({cal})",
    estimated_bad: "근무시간의 {est} 가 낮은 신뢰(PC 하한·흔적 창 등)로 채워졌습니다",
    estimated_high: "근무시간의 {est} 가 낮은 신뢰(PC 하한·흔적 창 등)로 채워졌습니다",
    unattributed_high: "근무시간의 {unattr} 가 업무에 묶이지 않았습니다",
    no_evidence_days: "근거가 하나도 없는 근무일이 {no_ev}일 있습니다(확인 질문 Q09)",
    sampler_absent: "PC 사용 기록기(샘플러)가 없는 날이 많습니다 — 시간이 낮은 신뢰로 계산됩니다",
    no_envelope: "이 달은 근무시간이 계산되지 않았습니다",
    mining_coarse: "단계 정밀도가 낮습니다 — 등급에는 영향 없음, 표시만"
  };

  // 확인 질문 이름(계약 §6.3)
  var Q_NAME = {Q01: "경계 확인", Q02: "미착수 의뢰", Q03: "오래 열림·보류", Q04: "원격 발신", Q05: "흔적 창·미등록 외근",
    Q06: "date-only 게이트", Q07: "요약 근거", Q08: "근무창 공백", Q09: "추정 부재", Q10: "장시간일", Q11: "솔버 대량",
    Q12: "분할 제안·분할 과다", Q13: "UTC 저장 의심", Q14: "회의 불참 의심", Q15: "미정 회의", Q16: "휴가 중 근무",
    Q17: "미귀속 블록", Q18: "공용 문서 의심", H01: "과제 미정", H02: "규칙·AI 충돌", H03: "새 과제 확인", H04: "이름 병합 애매",
    H05: "유형 애매", H06: "퇴역 과제"};

  // 확인 질문 응답 선택지(R §6.9) — [choice, 글자, 더 받을 칸(at·hours·hours_opt·unit·span·project·wtype)]
  var QA = {
    Q01: [["instr", "지시받은 때", "at"], ["report", "보고한 때", "at"], ["must_link", "다른 업무와 같은 일", "unit"]],
    Q02: [["not_started", "착수 안 함"], ["must_link", "다른 업무에 포함", "unit"], ["work", "오프라인으로 처리함", "at_hours"]],
    Q03: [["report", "끝남", "at"], ["open", "진행 중"]],
    Q04: [["approve", "업무"], ["exclude", "사적"]],
    Q05: [["offsite", "외근·출장·현장", "span"], ["exclude", "정정(업무 아님)"]],
    Q06: [["work", "근무함", "hours"], ["exclude", "근무 아님"]],
    Q07: [["instr", "의뢰 시각", "at"], ["report", "보고 시각", "at"]],
    Q08: [["work", "오프라인 업무", "span_unit"], ["exclude", "업무 아님"]],
    Q09: [["absence", "부재"], ["work", "근무", "hours"]],
    Q10: [["approve", "맞음"], ["exclude", "업무 아님"]],
    Q11: [["work", "결과 확인 시간 기록", "hours_opt"]],
    Q12: [["cannot_link", "나누기"], ["must_link", "합치기"]],
    Q13: [["utc", "그 경로가 UTC 저장(시간 오프셋 설정)"]],
    Q14: [["attended", "참석함"], ["absent", "불참"]],
    Q15: [["attended", "참석함"], ["absent", "불참"]],
    Q16: [["approve", "맞음"], ["exclude", "업무 아님"]],
    Q17: [["work", "업무 고르기", "unit"], ["exclude", "개인 시간"]],
    Q18: [["shared_doc", "공용 문서"], ["must_link", "특정 업무 것", "unit"]],
    H01: [["project", "과제 고르기", "project"], ["not_work", "업무 아님"]],
    H02: [["rule", "규칙 과제"], ["ai", "AI 과제"], ["other", "그 밖", "project"]],
    H03: [["accept", "내 과제로 받기"], ["map", "기존 과제와 같음", "project"], ["reject", "거절"]],
    H04: [["same", "같다"], ["different", "다르다"]],
    H05: [["wtype", "유형 고르기", "wtype"]],
    H06: [["project", "옮길 과제", "project"]]
  };
  var WTYPES = ["DEV", "OFFICE", "FIELD", "PM", "PL", "SUPPORT", "EDU"];

  // ───────────────────────── 4. 모델 색인(순수) ─────────────────────────
  var IDXCACHE = typeof WeakMap === "function" ? new WeakMap() : null;

  function domainRank(X, code) {
    var i = C().DOMAIN_ORDER.indexOf(code);
    var d = X.domains[code];
    return (i < 0 ? 100 : i) * 1000 + (d && isNum(d.order) ? d.order : 0);
  }

  function periodRow(ms) {
    var p = {m: ALL, env_min: 0, denom_min: 0, workdays: 0, covered_workdays: 0, attributed_min: 0, unattr_min: 0, obs_min: 0,
      est_min: 0, avail_min: 0, avail_days: 0, absence_days: 0, overtime_window_min: 0, overtime_daily8h_min: 0,
      on_leave_min: 0, by_tag: {}, buckets: {}, conf_min: {}, units: {}, partial: null};
    var sums = ["env_min", "denom_min", "workdays", "covered_workdays", "attributed_min", "unattr_min", "obs_min", "est_min",
      "avail_min", "avail_days", "absence_days", "overtime_window_min", "overtime_daily8h_min", "on_leave_min"];
    ms.forEach(function (r) {
      sums.forEach(function (k) { p[k] += num(r[k]); });
      TAG_KEYS.forEach(function (t) { p.by_tag[t] = num(p.by_tag[t]) + num(obj(r.by_tag)[t]); });
      BUCKETS.forEach(function (b) { p.buckets[b] = num(p.buckets[b]) + num(obj(r.buckets)[b]); });
      ["high", "mid", "low"].forEach(function (c) { p.conf_min[c] = num(p.conf_min[c]) + num(obj(r.conf_min)[c]); });
      ["started", "finished", "continuing", "unstarted"].forEach(function (k) { p.units[k] = num(p.units[k]) + num(obj(r.units)[k]); });
    });
    return p;
  }

  function buildIdx(m) {
    var X = {units: {}, unitList: [], projects: {}, roles: {}, domains: {}, domainList: [], months: [], monthBy: {}, days: {},
      people: obj(obj(m.refs).people), docs: obj(obj(m.refs).docs), apps: obj(obj(m.refs).apps)};
    arr(m.domains).forEach(function (d) { if (d && d.code) { X.domains[d.code] = d; } });
    X.domainList = arr(m.domains).filter(function (d) { return d && d.code; }).slice()
      .sort(function (a, b) { return (domainRank(X, a.code) - domainRank(X, b.code)) || cmp(a.code, b.code); });
    arr(m.projects).forEach(function (p) { if (p && p.key) { X.projects[p.key] = p; } });
    arr(m.roles).forEach(function (r) { if (r && r.role_id) { X.roles[r.role_id] = r; } });
    X.unitList = arr(m.units).filter(function (u) { return u && u.unit_id; });
    X.unitList.forEach(function (u) { X.units[u.unit_id] = u; });
    X.months = arr(m.months).filter(function (r) { return r && r.m; }).slice().sort(function (a, b) { return cmp(a.m, b.m); });
    X.months.forEach(function (r) { X.monthBy[r.m] = r; });
    arr(m.days).forEach(function (d) { if (d && d.d) { X.days[d.d] = d; } });
    X.period = periodRow(X.months);
    var mm = 0;
    var any = false;
    X.months.forEach(function (r) { if (num(r.denom_min) > 0) { mm += num(r.env_min) / r.denom_min; any = true; } });
    X.periodMM = any ? U().fmtNum(mm, 2) : null;
    return X;
  }

  function idx(model) {
    if (IDXCACHE && IDXCACHE.has(model)) { return IDXCACHE.get(model); }
    var X = buildIdx(model);
    if (IDXCACHE) { IDXCACHE.set(model, X); }
    return X;
  }

  function uMin(u, mk) { return mk === ALL ? num(u.effort_min) : num(obj(u.by_month)[mk]); }
  function domName(X, code) { var d = X.domains[code]; return (d && d.name) || str(code); }
  function uncText(X) { var d = X.domains.UNC; return (d && d.name) || "분류 없음"; }

  function projLabel(X, key) {
    if (!key || key === "-") { return "과제 없음"; }
    var p = X.projects[key];
    if (/^P-99\d\d$/.test(key)) {
      var dc = p && p.domain;
      return (dc ? domName(X, dc) + " — " : "") + "과제 미지정";
    }
    return (p && p.label) || key;
  }

  function roleLabel(X, id) {
    var r = X.roles[id];
    if (!r) { return id && id !== "-" ? id : "역할 없음"; }
    return r.label || [r.field_name || r.field, r.function_name || r["function"]].filter(Boolean).join(" · ") || id;
  }

  function unitTitle(X, id) { var u = X.units[id]; return (u && u.title) || str(id); }
  function peerName(X, ref) { var p = X.people[String(ref)]; return (p && p.name) || "동료"; }
  function docName(X, ref) { var d = X.docs[String(ref)]; return (d && d.name) || "문서"; }
  function appName(X, id) { var a = X.apps[String(id)]; return (a && a.name) || str(id); }
  function monthLabel(mk) { return mk === ALL ? "기간 전체" : mk; }

  function asOfMonth(X, model) {
    var a = str(obj(model.run).as_of).slice(0, 7);
    if (X.monthBy[a]) { return a; }
    return X.months.length ? X.months[X.months.length - 1].m : ALL;
  }

  function partialText(row) {
    return row && row.partial ? "부분월(" + num(row.covered_workdays) + "/" + num(row.workdays) + " 근무일)" : "";
  }

  function stepName(s) { return str(s && (s.label || s.name || s.code || s.type)) || "단계"; }

  function idOf(x) { return typeof x === "string" ? x : str(obj(x).unit_id); }

  // ───────────────────────── 5. 머리 띠(§2.4.3 · §3.5 · RPT-04) — app.js 도 쓴다 ─────────────────────────
  // 기간 출처 → 글자. default = 기본 기간(올해 1월 1일 ~ 오늘 — 2026-10-06 사용자 결정). 개월 수가 실린 default 는 그 전 규칙
  // (최근 n개월)으로 분석한 옛 실행이라 그대로 보인다. q1~q4·h1·h2 = 빠른 선택(lm27ui.js periodPresets).
  var PERIOD_SRC = {this_month: "이번 달", last_month: "지난달", this_year: "올해", user: "직접 지정", manual: "직접 지정",
    rerun: "이전 분석과 같음", q1: "1분기", q2: "2분기", q3: "3분기", q4: "4분기", h1: "상반기", h2: "하반기"};

  function periodSourceText(src, n) {
    if (!src) { return null; }
    if (src === "default") { return isNum(n) && n > 0 ? "기본값(최근 " + n + "개월)" : "기본값(올해 1월 1일 ~ 오늘)"; }
    if (src === "recent") { return "최근 " + (isNum(n) && n > 0 ? n : 3) + "개월"; }
    return PERIOD_SRC[src] || null;
  }

  function labelTotals(ls) {
    var t = {ai: 0, manual: 0, rule: 0, total: 0};
    Object.keys(obj(ls)).sort().forEach(function (k) {
      var s = obj(ls[k]);
      t.ai += num(s.ai);
      t.manual += num(s.manual);
      t.rule += num(s.rule) + num(s.pending) + num(s.rule_pending);
    });
    t.total = t.ai + t.manual + t.rule;
    return t;
  }

  function bandParts(info) {
    info = obj(info);
    var p = [];
    if (info.from && info.to) { p.push("기간 " + info.from + " ~ " + info.to); }
    if (info.as_of) { p.push("기준 " + mdhm(info.as_of)); }
    if (info.built_at) { p.push("분석 " + mdhm(info.built_at) + "(" + (info.chosen === "explicit" ? "직접 선택" : "자동 선택") + ")"); }
    var src = periodSourceText(info.period_source, info.period_months);
    if (src) { p.push("기간 출처: " + src); }
    var ls = labelTotals(info.label_sources);
    if (ls.total > 0) { p.push("AI " + ls.ai + (ls.manual ? " · 붙여넣기 " + ls.manual : "") + " · 규칙 " + ls.rule); }
    return {text: p.join(" · "), ruleHeavy: ls.total > 0 && ls.rule * 2 > ls.total};
  }

  function bandView(info) {
    var b = bandParts(info);
    if (!b.text) { return []; }
    return [h("p", {"class": "head-band", role: "status"}, [b.text]),
      b.ruleHeavy ? U().alertLine("info", "AI 라벨이 절반 넘게 비어 있습니다 — 분석용 Edge 창에서 회사 계정으로 한 번 로그인한 뒤 [분석 실행]하면 채워집니다") : null];
  }

  function bandInfoOfModel(model) {
    var r = obj(model.run);
    return {from: r.from, to: r.to, as_of: r.as_of, built_at: r.built_at, chosen: r.chosen, period_source: r.period_source,
      period_months: r.period_months, label_sources: obj(model.flags).label_sources};
  }

  function majorOk(model) {
    var v = str(obj(model).schema_version);
    return obj(model).schema === "lm27.report" && v.split(".")[0] === MAJOR;
  }

  // ───────────────────────── 6. 공용 조각 ─────────────────────────
  function chart(res, id, st) {
    var srt = st.sort[id];
    return U().chartView(res, {id: id, table: !!st.tables[id],
      tableOpt: {sortCol: srt ? srt.col : null, desc: srt ? srt.desc : false, limit: st.limit[id] || 500, id: "t-" + id}});
  }

  function kpi(o) {
    var v = U().kpiCard(o);
    if (o.tip) {
      v.c.forEach(function (c) { if (c && c.a && c.a["class"] === "kpi-sub") { c.a["data-tip"] = o.tip; } });
    }
    return v;
  }

  // 사유 문구: 모델이 숫자까지 채운 문구(quality.texts — 달은 그 달 값, 기간 전체는 가장 나쁜 달 값)가 있으면 그것,
  // 없으면 아래 틀에 cov·est_ratio 를 채운다(옛 모델).
  function qualityText(code, q, model) {
    var custom = obj(obj(model).quality).reason_text;
    if (custom && custom[code]) { return custom[code]; }
    var pre = arr(obj(q).texts).filter(function (x) { return obj(x).code === code && obj(x).text; })[0];
    if (pre) { return str(pre.text); }
    var t = QUALITY_TEXT[code];
    if (!t) { return code; }
    var cov = obj(q.cov);
    return t.replace(/\{(\w+)\}/g, function (all, k) {
      if (k === "est") { return U().shareText(q.est_ratio); }
      if (k === "unattr") { return U().shareText(q.unattr_ratio); }
      if (k === "no_ev") { return String(num(q.no_ev)); }
      return isNum(cov[k]) ? U().shareText(cov[k]) : "—";
    });
  }

  function warningsView(model, env) {
    var out = [];
    arr(obj(model.flags).warnings).forEach(function (w) {
      var t = obj(w).text_ko || obj(w).code;
      if (t) { out.push(U().alertLine("warn", t)); }
    });
    if (env.trimmed && env.trimmed.length) {
      out.push(U().alertLine("info", "파일 크기 상한 때문에 뺀 것: " + env.trimmed.join(", ") + " — 로컬 앱에서는 모두 보입니다"));
    }
    return out;
  }

  function sectionNav(st) {
    return U().pills(SECTIONS.map(function (s) {
      return {href: "#report/" + s[0], label: s[1], current: st.section === s[0]};
    }), {small: true, label: "보고서 절"});
  }

  function monthNav(X, st) {
    var list = X.months.map(function (r) { return [r.m, r.m + (r.partial ? " (부분)" : "")]; }).concat([[ALL, "기간 전체"]]);
    return h("nav", {"class": "pills pills-sm", "aria-label": "달 선택"}, list.map(function (it) {
      var on = it[0] === st.month;
      return h("a", {"class": "pill", href: "#report/" + st.section, "aria-current": on ? "page" : null,
        "data-act": "r-month", "data-ref": it[0]}, [it[1]]);
    }));
  }

  function periodNote(X, st) {
    if (st.month === ALL) {
      var ms = X.months;
      return muted(ms.length ? "기간 전체: " + ms[0].m + " ~ " + ms[ms.length - 1].m + " · 기간 MM 은 달별 MM 의 합입니다" : "기간 전체");
    }
    var row = X.monthBy[st.month];
    return muted("기간: " + st.month + (row && row.partial ? " · " + partialText(row) : ""));
  }

  function srcBadge(by) { return by ? U().sourceBadge(by) : null; }

  // ───────────────────────── 7. 요약(§6.2) ─────────────────────────
  function viewSummary(model, X, st, env) {
    var mk = st.month;
    var row = mk === ALL ? X.period : X.monthBy[mk];
    if (!row || (!X.months.length)) { return [card(null, emptyP("이 기간의 분석 결과가 없습니다 — 로컬 앱 위쪽 기간 카드에서 기간을 정해 [분석 실행]을 누르세요."))]; }
    var u = U();
    var out = [];
    var std = num(obj(model.denominator).std_day_min) || 480;
    var kp = [];
    // ① MM
    if (mk === ALL) {
      kp.push(kpi({label: "기간 MM", value: X.periodMM === null ? null : X.periodMM + " MM",
        sub: X.months.length + "개월 · 달별 MM 의 합 · 근무 " + u.hText(row.env_min), act: "r-goto", ref: "evidence"}));
    } else {
      var mmSub = u.fmtH1(num(row.env_min)) + "h ÷ " + (u.fmtRatio(num(row.denom_min), 60, 0) || "0") + "h(근무일 " + num(row.workdays) +
        "일 × " + u.fmtRatio(std, 60, 0) + "h)" + (row.partial ? " · " + partialText(row) : "");
      kp.push(kpi({label: mk + " MM", value: num(row.denom_min) > 0 ? u.fmtMM(num(row.env_min), row.denom_min) + " MM" : null,
        sub: mmSub, tip: obj(model.denominator).text_ko || mmSub, act: "r-goto", ref: "evidence/" + mk}));
    }
    // ② 로드율
    var avail = num(row.avail_min);
    kp.push(kpi({label: "로드율", value: avail > 0 ? u.fmtPct(num(row.env_min), avail) + "%" : null,
      sub: avail > 0 ? "가용 " + u.fmtNum(num(row.avail_days), 1) + "일 기준" + (num(row.absence_days) > 0 ? "(부재 " +
        u.fmtNum(num(row.absence_days), 1) + "일)" : "") : "가용 0", act: "r-goto", ref: mk === ALL ? "evidence" : "evidence/" + mk}));
    // ③ 초과 근무
    var basis = obj(model.denominator).overtime_basis || obj(model.run).overtime_basis || "window";
    var bt = obj(row.by_tag);
    var ot = basis === "daily8h" ? row.overtime_daily8h_min : row.overtime_window_min;
    kp.push(kpi({label: "초과 근무", value: isNum(ot) ? u.hText(ot) : null,
      sub: "연장 " + u.fmtH1(num(bt.extended)) + " · 야간 " + u.fmtH1(num(bt.night)) + " · 휴일 " + u.fmtH1(num(bt.holiday)) +
        (num(row.on_leave_min) > 0 ? " · 휴가 중 근무 " + u.fmtH1(row.on_leave_min) : "") + " · " +
        (basis === "daily8h" ? "일 8시간 초과 기준" : "근무창 밖 기준"),
      act: "r-goto", ref: mk === ALL ? "review" : "review/" + mk}));
    // ④ 미귀속 비율
    var bk = obj(row.buckets);
    var bparts = BUCKETS.filter(function (b) { return num(bk[b]) > 0; }).map(function (b) { return BUCKET_NAME[b] + " " + u.fmtH1(bk[b]); });
    kp.push(kpi({label: "미귀속 비율", value: num(row.env_min) > 0 ? u.pctText(num(row.unattr_min), row.env_min) : null,
      sub: "근무 중 미분류 " + u.hText(num(row.unattr_min)) + (bparts.length ? " — " + bparts.join(" · ") : ""), act: "r-goto", ref: "tree/x:UNATTR"}));
    // ⑤ 신뢰도
    var q = mk === ALL ? obj(model.quality) : obj(row.quality);
    var g = GRADE_NAME[q.grade] || ["unknown", "판단 안 함"];
    var sh = unitShares(X, mk);
    var env0 = num(row.env_min);
    kp.push(kpi({label: "신뢰도", value: u.statusText(g[0], g[1]),
      sub: "관측 " + u.pctText(num(row.obs_min), env0) + " · 추정 " + u.pctText(num(row.est_min), env0) + " · 미귀속 " +
        u.pctText(num(row.unattr_min), env0) + " · A·B 업무 " + u.pctText(sh.ab, num(row.attributed_min)) + " · 분류 신뢰 " +
        u.pctText(sh.conf, sh.all), act: "r-ui", ref: "quality=" + (st.ui.quality === "1" ? "0" : "1")}));
    // ⑥ 단위업무
    var cnt = mk === ALL ? statusCounts(X) : obj(row.units);
    var med = medianLead(model, X, mk);
    kp.push(kpi({label: "단위업무", value: "완료 " + num(cnt.finished) + " · 진행 " + num(cnt.continuing),
      sub: "새로 시작 " + num(cnt.started) + " · 미착수 의뢰 " + num(cnt.unstarted) + (med !== null ? " · 중앙 리드 " + u.daysText(med, std) : ""),
      act: "r-goto", ref: mk === ALL ? "review" : "review/" + mk}));
    out.push(h("div", {"class": "kpis"}, kp));
    if (st.ui.quality === "1") {
      var reasons = arr(q.reasons);
      var unc = sh.all > 0 ? u.pctText(sh.unc, sh.all) : "—";
      out.push(card("신뢰도 사유", h("div", {}, [
        reasons.length ? h("ul", {}, reasons.map(function (c) { return h("li", {}, [qualityText(c, q, model)]); })) :
          para("측정 품질에 걸린 사유가 없습니다."),
        muted("분류 미정 비중(낮음·미분류 투입) " + unc)]), {id: "r-quality"}));
    }
    var W = env.width;
    out.push(card(null, chart(C().monthlyMM({months: X.months}, {width: W, id: "ch-p02"}), "ch-p02", st), {id: "r-p02"}));
    out.push(card(null, chart(C().domainShare(domainSpec(X, mk, row), {width: W, id: "ch-p04"}), "ch-p04", st), {id: "r-p04"}));
    out.push(card(null, chart(C().gradeBars(gradeSpec(X, mk, row), {width: W, id: "ch-p17"}), "ch-p17", st), {id: "r-p17"}));
    out.push(topUnitsCard(model, X, mk));
    var sent = summarySentences(model, X, mk, row);
    if (sent.length) { out.push(card("한 줄 요약", h("ul", {}, sent.map(function (s) { return h("li", {}, [s]); })), {id: "r-sent"})); }
    return out;
  }

  function unitShares(X, mk) {
    var r = {ab: 0, conf: 0, unc: 0, all: 0};
    X.unitList.forEach(function (u) {
      var m = uMin(u, mk);
      if (!(m > 0)) { return; }
      r.all += m;
      if (u.grade === "A" || u.grade === "B") { r.ab += m; }
      if (u.label_level === "confirmed" || u.label_level === "high") { r.conf += m; }
      if (u.label_level === "low" || u.label_level === "unclassified" || !u.label_level) { r.unc += m; }
    });
    return r;
  }

  function statusCounts(X) {
    var c = {finished: 0, continuing: 0, started: 0, unstarted: 0};
    X.unitList.forEach(function (u) {
      if (u.status === "closed" || u.status === "estimated") { c.finished++; } else if (u.status === "open") { c.continuing++; } else if (u.status === "not_started") {
        c.unstarted++;
      }
      if (u.status !== "not_started") { c.started++; }
    });
    return c;
  }

  function median(list) {
    var a = list.filter(isNum).slice().sort(function (x, y) { return x - y; });
    if (!a.length) { return null; }
    var mid = Math.floor(a.length / 2);
    return a.length % 2 ? a[mid] : Math.floor((a[mid - 1] + a[mid] + 1) / 2);
  }

  function medianLead(model, X, mk) {
    var vals = [];
    if (mk !== ALL) {
      var rv = arr(obj(model.reviews).months).filter(function (r) { return r.key === mk; })[0];
      arr(obj(rv).lead_table).forEach(function (r) { vals.push(obj(r).biz_lead_min); });
      return median(vals);
    }
    X.unitList.forEach(function (u) { if (u.status === "closed" || u.status === "estimated") { vals.push(u.biz_lead_min); } });
    return median(vals);
  }

  function domMin(X, code, mk) {
    return sumBy(X.unitList.filter(function (u) { return (u.domain || "UNC") === code; }), function (u) { return uMin(u, mk); });
  }

  function domainSpec(X, mk, row) {
    var doms = X.domainList.map(function (d) {
      var units = X.unitList.filter(function (u) { return (u.domain || "UNC") === d.code && uMin(u, mk) > 0; }).length;
      return {code: d.code, name: d.name, color: d.color, min: domMin(X, d.code, mk), units: units};
    });
    return {domains: doms, unattr_min: num(row.unattr_min), denom_min: mk === ALL ? 0 : num(row.denom_min)};
  }

  function gradeSpec(X, mk, row) {
    var g = {};
    var z = 0;
    X.unitList.forEach(function (u) {
      var k = u.grade || "";
      if (k === "Z" || u.status === "not_started") { z++; return; }
      g[k] = num(g[k]) + uMin(u, mk);
    });
    return {grades: g, not_started_n: mk === ALL ? z : num(obj(row.units).unstarted)};
  }

  function topUnitsCard(model, X, mk) {
    var list = X.unitList.filter(function (u) { return uMin(u, mk) > 0; }).slice()
      .sort(function (a, b) { return (uMin(b, mk) - uMin(a, mk)) || cmp(a.unit_id, b.unit_id); }).slice(0, 10);
    if (!list.length) { return card("주요 단위업무", emptyP("이 기간에 만들어진 단위업무가 없습니다."), {id: "r-top"}); }
    var rows = list.map(function (u) {
      return [h("span", {}, [link(u.title || u.unit_id, "#report/tree/u:" + u.unit_id), " ", srcBadge(u.title_by)]),
        projLabel(X, u.project_key), roleLabel(X, u.role_id),
        h("span", {}, [U().hText(uMin(u, mk)), " ", oiBar(u.obs_min, u.est_min)]),
        isNum(u.biz_lead_min) ? U().daysText(u.biz_lead_min) : "—", U().gradeBadge(u.grade), STATUS_NAME[u.status] || u.status];
    });
    return card("주요 단위업무", table([{label: "제목"}, {label: "과제"}, {label: "역할"}, {label: "투입", num: true},
      {label: "리드", num: true}, {label: "등급"}, {label: "상태"}], rows, {label: "주요 단위업무 상위 10"}), {id: "r-top", state: monthLabel(mk) + " 투입 상위 10"});
  }

  function summarySentences(model, X, mk, row) {
    var out = [];
    var tot = num(row.env_min);
    var doms = X.domainList.map(function (d) { return [d, domMin(X, d.code, mk)]; }).filter(function (p) { return p[1] > 0; })
      .sort(function (a, b) { return (b[1] - a[1]) || cmp(a[0].code, b[0].code); });
    if (doms.length && tot > 0) {
      out.push((mk === ALL ? "기간 전체" : mk) + " 투입의 " + U().pctText(doms[0][1], tot) + "가 " +
        josa(doms[0][0].name || doms[0][0].code, "이었습니다.", "였습니다."));
    }
    if (mk !== ALL) {
      var rv = arr(obj(model.reviews).months).filter(function (r) { return r.key === mk; })[0];
      var top = otOf(rv).units[0];
      var basis = obj(model.denominator).overtime_basis || "window";
      var otAll = basis === "daily8h" ? row.overtime_daily8h_min : row.overtime_window_min;
      if (top && num(top.min) > 0 && num(otAll) > 0) {
        out.push("초과 근무 " + U().hText(otAll) + " 중 " + U().hText(top.min) + " 가 '" + unitTitle(X, idOf(top)) + "' 에 쓰였습니다.");
      }
    }
    var q = mk === ALL ? obj(model.quality) : obj(row.quality);
    var r0 = arr(q.reasons)[0];
    if (r0) { out.push(qualityText(r0, q, model) + "."); }
    return out.slice(0, 3);
  }

  // 리뷰 기간의 초과 근무 원인(R §4.4.4) — 모델은 {basis, total_min, units[{unit_id, min}], unattributed_min}.
  // 옛 모양(배열 + ot_unattr_min)도 읽는다.
  function otOf(rv) {
    var r = obj(rv);
    if (Array.isArray(r.ot_units)) { return {units: r.ot_units, unattr: num(r.ot_unattr_min)}; }
    var o = obj(r.ot_units);
    return {units: arr(o.units).filter(function (x) { return x && typeof x === "object"; }), unattr: num(o.unattributed_min)};
  }

  // ───────────────────────── 8. 업무 트리(§6.3.1) ─────────────────────────
  function newNode(key, kind, level, label, parent) {
    return {key: key, kind: kind, level: level, label: label, parent: parent, kids: [], units: [], byMonth: {}, min: 0, minAll: 0,
      obs: 0, est: 0, done: 0, open: 0, unstarted: 0, dist: {}, info: {}};
  }

  function addUnit(n, u, mk) {
    n.units.push(u);
    n.min += uMin(u, mk);
    n.minAll += num(u.effort_min);
    n.obs += num(u.obs_min);
    n.est += num(u.est_min);
    Object.keys(obj(u.by_month)).forEach(function (m) { n.byMonth[m] = num(n.byMonth[m]) + num(u.by_month[m]); });
    if (u.status === "closed" || u.status === "estimated") { n.done++; } else if (u.status === "not_started") { n.unstarted++; } else {
      n.open++;
    }
    var lv = u.label_level || "unclassified";
    n.dist[lv] = num(n.dist[lv]) + num(u.effort_min);
  }

  function treeData(model, X, mk) {
    var byKey = {};
    var tops = [];
    function get(key, kind, level, label, parent) {
      if (!byKey[key]) {
        byKey[key] = newNode(key, kind, level, label, parent);
        if (parent) { byKey[parent].kids.push(key); } else { tops.push(key); }
      }
      return byKey[key];
    }
    X.unitList.forEach(function (u) {
      var d = u.domain || "UNC";
      var p = u.project_key || "-";
      var r = u.role_id || "-";
      var dn = get("d:" + d, "domain", 1, domName(X, d), null);
      dn.code = d;
      var pn = get("p:" + d + "/" + p, "project", 2, projLabel(X, p), dn.key);
      pn.pkey = p;
      var rn = get("r:" + d + "/" + p + "/" + r, "role", 3, roleLabel(X, r), pn.key);
      rn.rid = r;
      var un = get("u:" + u.unit_id, "unit", 4, u.title || u.unit_id, rn.key);
      un.unit = u;
      [dn, pn, rn, un].forEach(function (n) { addUnit(n, u, mk); });
    });
    var treeNodes = obj(obj(model.tree).nodes);
    Object.keys(byKey).forEach(function (k) {
      var n = byKey[k];
      // 모델 tree.nodes: 과제 없음 자리는 '-'(영역 노드 'UNC' 와 겹치지 않게) — 단위업무의 project_key 는 'UNC'
      var pk = n.pkey === "UNC" ? "-" : n.pkey;
      var src = n.kind === "domain" ? treeNodes[n.code] : (n.kind === "project" ? treeNodes[pk] : (n.kind === "role" ? treeNodes[n.rid] : null));
      n.info = obj(src);
      n.kids.sort(function (a, b) {
        var x = byKey[a];
        var y = byKey[b];
        return (y.minAll - x.minAll) || cmp(a, b);
      });
    });
    tops.sort(function (a, b) { return (domainRank(X, byKey[a].code) - domainRank(X, byKey[b].code)) || cmp(a, b); });
    // 근무 중 미분류(버킷 5종) — 숨기지 않는다(RP16)
    var row = mk === ALL ? X.period : (X.monthBy[mk] || {});
    var un = newNode("x:UNATTR", "unattr", 1, "근무 중 미분류", null);
    BUCKETS.forEach(function (b) {
      var bn = newNode("b:" + b, "bucket", 2, BUCKET_NAME[b], un.key);
      bn.bucket = b;
      bn.min = num(obj(row.buckets)[b]);
      bn.minAll = num(obj(X.period.buckets)[b]);
      X.months.forEach(function (r) { bn.byMonth[r.m] = num(obj(r.buckets)[b]); });
      byKey[bn.key] = bn;
      un.kids.push(bn.key);
      un.min += bn.min;
      un.minAll += bn.minAll;
      Object.keys(bn.byMonth).forEach(function (m) { un.byMonth[m] = num(un.byMonth[m]) + bn.byMonth[m]; });
    });
    byKey[un.key] = un;
    tops.push(un.key);
    return {byKey: byKey, tops: tops};
  }

  // 기본 펼침: 영역·과제·근무 중 미분류(버킷 5행은 늘 보인다 — RP16·RPT-13), 역할은 접음
  function isOpen(st, n) {
    var v = st.treeOpen[n.key];
    return v === undefined ? (n.kind === "domain" || n.kind === "project" || n.kind === "unattr") : !!v;
  }

  function visibleRows(T, st) {
    var out = [];
    function add(key) {
      var n = T.byKey[key];
      out.push(n);
      if (n.kids.length && isOpen(st, n)) { n.kids.forEach(add); }
    }
    T.tops.forEach(add);
    return out;
  }

  function periodMMOf(X, n) {
    var s = 0;
    var any = false;
    X.months.forEach(function (r) { if (num(r.denom_min) > 0) { s += num(n.byMonth[r.m]) / r.denom_min; any = true; } });
    return any ? U().fmtNum(s, 2) : "—";
  }

  function nodeMM(X, n, mk) {
    if (mk === ALL) { return periodMMOf(X, n); }
    var row = X.monthBy[mk];
    return row && num(row.denom_min) > 0 ? U().fmtMM(n.min, row.denom_min) : "—";
  }

  function bottleneckText(model, rid) {
    var rw = obj(obj(obj(model.workflows).roles)[rid]);
    if (rw.sample === "thin") { return "표본 부족"; }
    var by = {};
    arr(rw.steps).forEach(function (s) { by[s.no] = s; });
    return arr(rw.bottlenecks).map(function (b) {
      return (b.kind === "wait" ? "대기 " : "작업 ") + stepName(by[b.no]);
    }).join(" · ");
  }

  function treeRowV(model, X, st, env, n, focusKey, mk) {
    var u = U();
    var open = isOpen(st, n);
    var sel = st.treeSel === n.key;
    var name = [h("span", {"aria-hidden": "true"}, [new Array(n.level).join("   ")])];
    if (n.kids.length) {
      name.push(h("button", {type: "button", "class": "exp", tabindex: "-1", "data-act": "r-exp", "data-ref": n.key,
        "aria-label": open ? "접기" : "펼치기"}, [open ? "▾" : "▸"]));
    }
    name.push(" ");
    if (n.kind === "domain") { name.push(domChip(obj(X.domains[n.code]).color)); name.push(" "); }
    name.push(h("strong", {}, [n.label]));
    if (n.kind === "project") {
      var p = X.projects[n.pkey] || {};
      if (p.proposal_id || /^prop/.test(str(n.pkey))) { name.push(" ", u.badge("제안", "grade-dash", "제안 과제")); }
      if (/^L-\d{4}$/.test(str(n.pkey))) { name.push(" ", u.badge("내 과제")); }
      if (n.units.some(function (x) { return x.ax_link; })) { name.push(" ", u.badge("AX 연계")); }
      if (isNum(n.info.unattr_meet_min) && n.info.unattr_meet_min > 0) {
        name.push(h("small", {"class": "muted"}, [" 관련 미귀속 회의 " + u.hText(n.info.unattr_meet_min) + "(MM 미포함)"]));
      }
    }
    if (n.kind === "role") {
      var rw = obj(obj(obj(model.workflows).roles)[n.rid]);
      if (rw.ai_role) { name.push(h("small", {"class": "muted"}, [" " + rw.ai_role + " "]), srcBadge(rw.ai_by)); }
    }
    if (n.kind === "unit") { name.push(" ", srcBadge(n.unit.title_by), " ", u.gradeBadge(n.unit.grade)); }
    var counts = n.kind === "unit" ? (STATUS_NAME[n.unit.status] || str(n.unit.status)) :
      (n.kind === "unattr" || n.kind === "bucket" ? "—" : "완료 " + n.done + " · 진행 " + n.open + " · 미착수 " + n.unstarted);
    var lead = n.kind === "unit" ? n.unit.biz_lead_min : n.info.lead_biz_median_min;
    var cls;
    if (n.kind === "unit") {
      var lvn = n.unit.label_level || "unclassified";
      var lvName = (LEVELS.filter(function (l) { return l[0] === lvn; })[0] || [0, ""])[1] || uncText(X);
      cls = [u.badge(lvName, null, "분류 신뢰"), env.canWrite ? btn("분류 고치기", "r-fix", n.unit.unit_id, {kind: "ghost", tabindex: "-1"}) : null,
        btn("왜?", "r-why", n.unit.unit_id, {kind: "ghost", tabindex: "-1"})];
    } else if (n.kind !== "unattr" && n.kind !== "bucket") {
      cls = levelBar(n.dist, uncText(X));
    }
    var cells = [name, nodeMM(X, n, mk), periodMMOf(X, n), [u.hText(n.kind === "bucket" || n.kind === "unattr" ? n.min : n.min), " ",
      n.kind === "bucket" || n.kind === "unattr" ? null : oiBar(n.obs, n.est)], counts, isNum(lead) ? u.daysText(lead) : "—",
      n.kind === "role" ? bottleneckText(model, n.rid) : "", cls];
    return h("tr", {role: "row", "aria-level": String(n.level), "aria-expanded": n.kids.length ? (open ? "true" : "false") : null,
      "aria-selected": sel ? "true" : "false", tabindex: focusKey === n.key ? "0" : "-1", "data-act": "r-tree", "data-ref": n.key,
      "data-tree": n.key, "data-parent": n.parent || null}, cells.map(function (c, i) {
      return h("td", {role: "gridcell", "class": i >= 1 && i <= 3 ? "num" : null}, [cellVal(c)]);
    }));
  }

  function viewTree(model, X, st, env) {
    var mk = st.month;
    var T = treeData(model, X, mk);
    var out = [];
    var view = st.ui.tree === "gantt" ? "gantt" : "table";
    var tools = toggles("보기", [["table", "표"], ["gantt", "간트"]], view, "r-ui-tree");
    if (!X.unitList.length) {
      var un = num((mk === ALL ? X.period : obj(X.monthBy[mk])).unattr_min);
      out.push(card("업무 트리", h("div", {}, [tools, emptyP("이 기간에 만들어진 단위업무가 없습니다(근무 중 미분류 " + U().hText(un) + ").")]), {id: "r-tree-card"}));
      return out;
    }
    var panel = st.treeSel && T.byKey[st.treeSel] ? panelFor(model, X, st, env, T.byKey[st.treeSel], mk) :
      card("수준 패널", para("행을 고르면 그 수준의 워크플로우가 여기에 열립니다."), {id: "r-panel"});
    if (view === "gantt") {
      var gv = st.ui.gview === "week" ? "week" : "month";
      var g = C().gantt({rows: C().modelRows(model), as_of: str(obj(model.run).as_of).slice(0, 10), months: X.months.map(function (r) { return r.m; })},
        {width: env.width, view: gv, mode: "personal", collapsed: st.gcol, id: "ch-p06", title: "단위업무 간트"});
      out.push(card("업무 트리", h("div", {}, [tools, toggles("간트 척도", [["month", "월 보기"], ["week", "주 보기"]], gv, "r-ui-gview"),
        chart(g, "ch-p06", st)]), {id: "r-tree-card"}));
      out.push(panel);
      return out;
    }
    var rows = visibleRows(T, st);
    var focusKey = st.treeFocus && T.byKey[st.treeFocus] ? st.treeFocus : (st.treeSel && T.byKey[st.treeSel] ? st.treeSel : rows[0].key);
    if (!rows.some(function (r) { return r.key === focusKey; })) { focusKey = rows[0].key; }
    var head = h("tr", {role: "row"}, ["이름", "선택 달 MM", "기간 MM", "투입", "단위업무", "중앙 리드", "병목", "분류"].map(function (c, i) {
      return h("th", {scope: "col", role: "columnheader", "class": i >= 1 && i <= 3 ? "num" : null}, [i === 1 ? monthLabel(mk) + " MM" : c]);
    }));
    var tbl = h("div", {"class": "table-wrap"}, [h("table", {"class": "tbl", role: "treegrid", "aria-label": "업무 트리 — 방향키로 이동·펼침, Enter 로 패널",
      id: "r-treegrid"}, [h("thead", {}, [head]), h("tbody", {}, rows.map(function (n) { return treeRowV(model, X, st, env, n, focusKey, mk); }))])]);
    // 트리(넓게) | 수준 패널(오른쪽에 붙어 따라옴) — 좁으면 아래로(§6.3.2 나란한 칸)
    out.push(h("div", {"class": "tree-layout"}, [card("업무 트리", h("div", {}, [tools, tbl]), {id: "r-tree-card",
      state: "영역 → 과제 → 역할 → 단위업무"}), panel]));
    return out;
  }

  // ───────────────────────── 9. 수준 패널(§6.3.2) ─────────────────────────
  function panelFor(model, X, st, env, n, mk) {
    if (n.kind === "domain") { return panelDomain(model, X, st, env, n); }
    if (n.kind === "project") { return panelProject(model, X, st, env, n); }
    if (n.kind === "role") { return card(n.label, rolePanelBody(model, X, st, env, n.rid), {id: "r-panel", state: "역할 업무"}); }
    if (n.kind === "unit") { return card(n.label, unitPanelBody(model, X, st, env, n.unit), {id: "r-panel", state: "단위업무"}); }
    var brow = mk === ALL ? X.period : obj(X.monthBy[mk]);
    return card("근무 중 미분류", h("div", {}, [para("단위업무에 묶이지 않은 근무입니다. 버킷 분은 과제에 나눠 주지 않고 이 행으로 늘 보입니다."),
      table(["버킷", {label: monthLabel(mk), num: true}, {label: "기간", num: true}], BUCKETS.map(function (b) {
        return [(n.bucket === b ? "▶ " : "") + BUCKET_NAME[b], U().hText(num(obj(brow.buckets)[b])), U().hText(num(obj(X.period.buckets)[b]))];
      }))]), {id: "r-panel"});
  }

  function panelDomain(model, X, st, env, n) {
    var u = U();
    var wd = obj(obj(obj(model.workflows).domains)[n.code]);
    var std = num(obj(model.denominator).std_day_min) || 480;
    var kp = h("div", {"class": "kpis"}, [kpi({label: "기간 MM", value: periodMMOf(X, n)}),
      kpi({label: "단위업무 수", value: String(isNum(wd.units_n) ? wd.units_n : n.units.length), sub: "완료 " + n.done + " · 진행 " + n.open}),
      kpi({label: "중앙 리드", value: isNum(wd.lead_biz_median_min) ? u.daysText(wd.lead_biz_median_min, std) : null})]);
    var groups = [];
    var projs = arr(wd.projects).length ? arr(wd.projects) : n.kids.map(function (k) { return k.split("/").slice(1).join("/"); });
    projs.forEach(function (p) {
      var key = typeof p === "string" ? p : str(obj(p).key);
      var wp = obj(obj(obj(model.workflows).projects)[key]);
      var mix = obj(obj(p).class_mix || wp.class_mix);
      if (Object.keys(mix).length) { groups.push({key: key, label: projLabel(X, key), mix: mix, none_min: num(obj(p).none_min || wp.none_min)}); }
    });
    if (!groups.length && Object.keys(obj(wd.class_mix)).length) {
      groups.push({key: n.code, label: n.label, mix: wd.class_mix, none_min: num(wd.none_min)});
    }
    var mix = groups.length ? chart(C().classMix({groups: groups}, {width: env.width, id: "ch-p10"}), "ch-p10", st) : muted("단계 묶음 자료가 없습니다.");
    var bns = arr(wd.top_bottlenecks).slice(0, 3).map(function (b) {
      var rw = obj(obj(obj(model.workflows).roles)[b.role_id]);
      var s = arr(rw.steps).filter(function (x) { return x.no === b.no; })[0];
      return h("li", {}, [link(roleLabel(X, b.role_id), "#report/workflow/" + encodeURIComponent(b.role_id)), " · ",
        (b.kind === "wait" ? "대기 병목 " : "작업 병목 ") + stepName(s), " · ",
        b.kind === "wait" ? u.daysText(b.value_min, std) : u.shareText(b.share)]);
    });
    var T = treeData(model, X, ALL);
    var prow = n.kids.map(function (k) {
      var pnode = T.byKey[k];
      return pnode ? [link(pnode.label, "#report/tree/" + encodeURIComponent(k)), periodMMOf(X, pnode), u.pctText(pnode.minAll, n.minAll),
        shareBar(n.minAll > 0 ? pnode.minAll / n.minAll : 0)] : null;
    }).filter(Boolean);
    return card(n.label, h("div", {}, [kp, mix, bns.length ? h("div", {}, [h("h3", {}, ["상위 병목"]), h("ul", {}, bns)]) : null,
      h("h3", {}, ["과제"]), table(["과제", {label: "기간 MM", num: true}, {label: "비중", num: true}, "투입 비중"], prow)]),
    {id: "r-panel", state: "업무 영역"});
  }

  function panelProject(model, X, st, env, n) {
    var u = U();
    var wp = obj(obj(obj(model.workflows).projects)[n.pkey]);
    var sub = {domains: model.domains, projects: model.projects, roles: model.roles,
      units: n.units.filter(function (x) { return (x.project_key || "-") === n.pkey; })};
    var rows = C().modelRows(sub).filter(function (r) { return !r.group; }).map(function (r) {
      var c = {};
      Object.keys(r).forEach(function (k) { c[k] = r[k]; });
      c.level = 0;
      c.key = "lane:" + r.key;
      return c;
    });
    var g = C().gantt({rows: rows, as_of: str(obj(model.run).as_of).slice(0, 10)}, {width: env.width, mode: "personal", id: "ch-p09",
      title: "역할 레인", labelHead: "역할 업무"});
    // 모델 workflows.projects[key]: handoffs[{from_role, to_role, n, gap_biz_median_min, via}] · roles[{role_id, effort_min,
    // share}](옛 모양 from·to · role_mix[{min}] 도 읽는다)
    var hand = arr(wp.handoffs).map(function (x) {
      var via = obj(x.via);
      return [roleLabel(X, x.from_role || x.from) + " → " + roleLabel(X, x.to_role || x.to), (num(x.n)) + "회",
        isNum(x.gap_biz_median_min) ? u.daysText(x.gap_biz_median_min) : "—", String(num(via.doc)), String(num(via.peer))];
    });
    var mixSrc = arr(wp.roles).length ? arr(wp.roles) : arr(wp.role_mix);
    var mixRows = mixSrc.filter(function (x) { return x && x.role_id; }).map(function (x) {
      return [link(roleLabel(X, x.role_id), "#report/workflow/" + encodeURIComponent(x.role_id)), u.hText(isNum(x.effort_min) ? x.effort_min : num(x.min)),
        h("span", {}, [u.shareText(x.share), " ", shareBar(x.share)]), bottleneckText(model, x.role_id)];
    });
    return card(n.label, h("div", {}, [chart(g, "ch-p09", st),
      h("h3", {}, ["역할 간 인계"]), hand.length ? table(["인계", {label: "횟수", num: true}, {label: "중앙 대기", num: true},
        {label: "문서 공유", num: true}, {label: "동료 공유", num: true}], hand) : muted("이 과제에는 역할 사이 인계가 없습니다."),
      h("h3", {}, ["역할 구성"]), mixRows.length ? table(["역할", {label: "투입", num: true}, "비중", "병목"], mixRows) : muted("역할 구성 자료가 없습니다.")]),
    {id: "r-panel", state: "과제"});
  }

  function roleSentences(rw) {
    var out = [];
    var by = {};
    arr(rw.steps).forEach(function (s) { by[s.no] = s; });
    var N = isNum(rw.units_n) ? rw.units_n : arr(rw.units).length;
    var bn = rw.sample === "thin" ? [] : arr(rw.bottlenecks);
    var work = bn.filter(function (b) { return b.kind === "work"; })[0];
    if (work && by[work.no]) { out.push(stepName(by[work.no]) + " 작업이 이 역할 투입의 " + U().shareText(work.share) + "로 가장 큽니다."); }
    var wait = bn.filter(function (b) { return b.kind === "wait"; })[0];
    if (wait && by[wait.no]) {
      var best = null;
      arr(rw.edges).forEach(function (e) {
        if (e[1] === wait.no && e[0] !== wait.no && (!best || e[2] > best[2] || (e[2] === best[2] && e[0] < best[0]))) { best = e; }
      });
      var prev = best && by[best[0]];
      out.push((prev ? josa(stepName(prev), "을", "를") + " 마치고 " : "") + josa(stepName(by[wait.no]), "을", "를") +
        " 시작하기까지 보통 " + U().fmtDays(num(wait.value_min)) + "영업일을 기다립니다.");
    }
    var rw0 = arr(rw.rework)[0];
    if (rw0 && by[rw0[0]] && by[rw0[1]]) {
      out.push(num(rw0[2] || 1) + "건의 단위업무에서 " + josa(stepName(by[rw0[0]]), "을", "를") + " 하다가 " + toRo(stepName(by[rw0[1]])) + " 되돌아갔습니다.");
    }
    if (rw.sample === "thin" || N < 3) { out.push("단위업무가 " + N + "건뿐이라 병목은 판단하지 않았습니다."); }
    return out.slice(0, 4);
  }

  function rolePanelBody(model, X, st, env, rid) {
    var u = U();
    var rw = obj(obj(obj(model.workflows).roles)[rid]);
    if (!arr(rw.steps).length) { return emptyP("이 역할 업무에는 단계를 만들 단위업무가 없습니다."); }
    var spec = {};
    Object.keys(rw).forEach(function (k) { spec[k] = rw[k]; });
    spec.units_n = isNum(rw.units_n) ? rw.units_n : arr(rw.units).length;
    var pm = C().processMap(spec, {width: env.width, id: "ch-p07", title: "역할 워크플로우 — " + roleLabel(X, rid)});
    var sel = st.ui.step ? +st.ui.step : null;
    var stepRows = arr(rw.steps).slice().sort(function (a, b) { return a.no - b.no; }).map(function (s) {
      var pt = s.kind === "M";
      return {cells: [(sel === s.no ? "▶ " : "") + "S" + s.no, h("span", {}, [stepName(s), " ", srcBadge(s.label_by)]), s.name || s.code, String(num(s.n)),
        isNum(s.freq_month) ? u.fmtNum(s.freq_month, 1) : "—", pt ? "—" : u.hText(s.median_min), pt ? "—" : u.hText(s.p75_min),
        isNum(s.wait_in_median_min) ? u.daysText(s.wait_in_median_min) : "—", isNum(s.work_share) ? u.shareText(s.work_share) : "—",
        isNum(s.obs_share) ? u.shareText(s.obs_share) : "—", s.agent_grade || "—", s.subagent || "—"],
      attrs: {"aria-selected": sel === s.no ? "true" : null}};
    });
    var byCode = {};
    arr(rw.steps).forEach(function (s) { byCode[s.code] = stepName(s); });
    var selCode = sel ? str(obj(arr(rw.steps).filter(function (s) { return s.no === sel; })[0]).code) : "";
    var unitRows = arr(rw.units).map(idOf).filter(function (id) {
      return !selCode || arr(obj(rw.traces)[id]).indexOf(selCode) >= 0;
    }).map(function (id) {
      var x = X.units[id] || {unit_id: id};
      var cy = arr(x.cycles);
      var c0 = obj(cy[0]);
      var c1 = obj(cy[cy.length - 1]);
      return [link(x.title || id, "#report/tree/u:" + id), (c0.sb || "?") + " " + mdhm(c0.s) + " → " + (c1.eb || "…") + " " + mdhm(c1.e),
        u.gradeBadge(x.grade), isNum(x.biz_lead_min) ? u.daysText(x.biz_lead_min) : "—", u.hText(x.effort_min), u.fmtX(x.parallel),
        arr(obj(rw.traces)[id]).map(function (c) { return byCode[c] || c; }).join(" → ")];
    });
    var edgeRows = arr(rw.edges).map(function (e) {
      var by = {};
      arr(rw.steps).forEach(function (s) { by[s.no] = s; });
      var w = obj(by[e[1]]);
      return ["S" + e[0] + " " + stepName(by[e[0]]), "S" + e[1] + " " + stepName(by[e[1]]), String(num(e[2])),
        isNum(w.wait_in_median_min) ? u.daysText(w.wait_in_median_min) : "—", e[1] < e[0] ? "예" : "아니오"];
    });
    var dropped = arr(rw.dropped).map(function (d) { return typeof d === "string" ? d : stepName(d) + (isNum(obj(d).n) ? "(" + d.n + "/" + spec.units_n + ")" : ""); });
    return h("div", {}, [
      rw.ai_role || rw.ai_summary ? h("div", {}, [para((rw.ai_role || "") + " "), rw.ai_summary ? para(rw.ai_summary) : null, srcBadge(rw.ai_by)]) : null,
      chart(pm, "ch-p07", st),
      h("ul", {}, roleSentences(rw).map(function (s) { return h("li", {}, [s]); })),
      h("h3", {}, ["단계"]),
      table(["번호", "단계 라벨", "유형", {label: "n", num: true}, {label: "월 빈도", num: true}, {label: "중앙 소요", num: true},
        {label: "75% 소요", num: true}, {label: "들어오는 대기", num: true}, {label: "작업 비중", num: true}, {label: "관측", num: true},
        "Agentic", "서브에이전트"], stepRows, {label: "역할 단계 표"}),
      h("h3", {}, ["전이"]), table(["앞 단계", "뒤 단계", {label: "횟수", num: true}, {label: "대기 중앙", num: true}, "되돌림"], edgeRows),
      h("h3", {}, [selCode ? "단위업무 — " + (byCode[selCode] || selCode) + " 단계가 나온 것" : "단위업무"]),
      selCode ? btn("단계 거르개 풀기", "r-ui", "step=", {kind: "ghost"}) : null,
      table(["제목", "시작 → 끝", "등급", {label: "리드", num: true}, {label: "투입", num: true}, {label: "병행도", num: true}, "정리된 흔적"], unitRows),
      dropped.length ? muted("드물어 뺀 단계: " + dropped.join(", ")) : null]);
  }

  function unitPanelBody(model, X, st, env, x) {
    var u = U();
    var uw = obj(obj(obj(model.workflows).units)[x.unit_id]);
    var tl = Object.keys(uw).length ? chart(C().unitTimeline(uw, {width: env.width, id: "ch-p08"}), "ch-p08", st) : muted("이 단위업무의 단계 기록이 없습니다.");
    var bnd = arr(uw.boundaries).length ? arr(uw.boundaries).map(function (b) {
      return (b.side === "start" ? "시작 " : "끝 ") + (b.code || "") + " " + mdhm(b.t) + (b.estimated ? "(추정 경계)" : "");
    }) : arr(x.cycles).map(function (c, i) { return "차수 " + (i + 1) + ": " + (c.sb || "?") + " " + mdhm(c.s) + " → " + (c.eb || "…") + " " + mdhm(c.e); });
    var lv = obj(x.levels_min);
    var lvRows = LEVEL_KEYS.filter(function (k) { return num(lv[k]) > 0; }).map(function (k) { return [k, LEVEL_NOTE[k], u.hText(lv[k])]; });
    var recs = arr(obj(obj(model.ontology).recs)[x.unit_id]).map(function (r) {
      var kd = REC_KIND[r.kind] || [str(r.kind), ""];
      return h("li", {}, [link(unitTitle(X, r.unit_id), "#report/tree/u:" + r.unit_id), " · 연관도 " + (u.fmtNum(r.rel, 2) || "—") + " · " + kd[0]]);
    });
    var lw = obj(uw.longest_wait);
    return h("div", {}, [
      h("p", {}, [projLabel(X, x.project_key), " › ", roleLabel(X, x.role_id), " ", srcBadge(x.title_by), " ", u.gradeBadge(x.grade), " ",
        STATUS_NAME[x.status] || str(x.status)]),
      tl,
      h("h3", {}, ["경계 근거"]), h("ul", {}, bnd.map(function (s) { return h("li", {}, [s]); })),
      h("h3", {}, ["투입 내역"]),
      para("투입 " + u.hText(x.effort_min) + " = 관측 " + u.hText(num(x.obs_min)) + " + 추정 " + u.hText(num(x.est_min)) +
        (isNum(uw.explained_ratio) ? " · 단계로 설명된 투입 " + u.shareText(uw.explained_ratio) : "")),
      lvRows.length ? table(["단계", "뜻", {label: "투입", num: true}], lvRows) : null,
      isNum(lw.biz_min) ? para("가장 긴 대기 " + u.daysText(lw.biz_min) + (lw.after || lw.before ? "(" + str(lw.after_name || lw.after) + " → " +
        str(lw.before_name || lw.before) + ")" : "")) : null,
      recs.length ? h("div", {}, [h("h3", {}, ["연관 업무 추천"]), h("ul", {}, recs)]) : null,
      arr(x.peers).length ? para("동료: " + arr(x.peers).map(function (r) { return peerName(X, r); }).join(", ")) : null,
      arr(x.docs).length ? para("문서: " + arr(x.docs).map(function (r) { return docName(X, r); }).join(", ")) : null,
      arr(x.apps).length ? para("앱: " + arr(x.apps).map(function (a) { return appName(X, a[0]) + " " + u.hText(num(a[1])); }).join(", ")) : null,
      h("div", {"class": "table-tools"}, [link("근거 보기", "#report/evidence/" + x.unit_id),
        env.canWrite ? btn("분류 고치기", "r-fix", x.unit_id, {kind: "ghost"}) : null, btn("왜?", "r-why", x.unit_id, {kind: "ghost"})]),
      st.ui.why === x.unit_id ? whyView(X, x) : null]);
  }

  function whyView(X, x) {
    var lines = arr(x.why).length ? arr(x.why) : (x.why ? [str(x.why)] : []);
    var src = obj(x.label_src);
    var conf = obj(x.label_conf);
    var rows = Object.keys(src).sort().map(function (k) { return [k, str(src[k]), isNum(conf[k]) ? U().fmtNum(conf[k], 2) : "—"]; });
    // 과제 후보(분류 규칙 점수 상위 3 — labels.json cands [[과제, 점수]], 옛 모양 {project, score} 도 읽는다)
    var cands = arr(x.cands).slice(0, 3).map(function (c) {
      var p = Array.isArray(c) ? c[0] : (obj(c).project || c);
      var sc0 = Array.isArray(c) ? c[1] : obj(c).score;
      return projLabel(X, str(p)) + (isNum(sc0) ? " " + U().fmtNum(sc0, 2) : "");
    }).filter(Boolean);
    return h("div", {"class": "card"}, [h("h3", {}, ["왜 이렇게 분류했나"]),
      lines.length ? h("ul", {}, lines.map(function (s) { return h("li", {}, [s]); })) : muted("분류 근거 줄이 이 결과에 없습니다(가림판·팀에는 싣지 않습니다)."),
      rows.length ? table(["필드", "출처", {label: "신뢰", num: true}], rows) : null,
      cands.length ? para("과제 후보: " + cands.join(" · ")) : null]);
  }

  // ───────────────────────── 10. 워크플로우(역할 목록 + 패널) ─────────────────────────
  function viewWorkflow(model, X, st, env) {
    var mk = st.month;
    var roles = obj(obj(model.workflows).roles);
    var ids = Object.keys(roles);
    if (!ids.length) { return [card("워크플로우", emptyP("이 기간에 만들어진 단위업무가 없습니다."), {id: "r-wf"})]; }
    var eff = {};
    ids.forEach(function (id) {
      eff[id] = sumBy(X.unitList.filter(function (u) { return u.role_id === id; }), function (u) { return uMin(u, mk); });
    });
    ids.sort(function (a, b) { return (eff[b] - eff[a]) || cmp(a, b); });
    var cur = st.ui.wfRole && roles[st.ui.wfRole] ? st.ui.wfRole : ids[0];
    var rows = ids.map(function (id) {
      var rw = obj(roles[id]);
      var r = X.roles[id] || {};
      return {cells: [h("span", {}, [cur === id ? "▶ " : "", link(roleLabel(X, id), "#report/workflow/" + encodeURIComponent(id))]),
        projLabel(X, r.project_key), String(isNum(rw.units_n) ? rw.units_n : arr(rw.units).length), U().hText(eff[id]),
        bottleneckText(model, id), rw.sample === "thin" ? "표본 부족" : "충분"], attrs: {"aria-current": cur === id ? "true" : null}};
    });
    var person = obj(obj(model.workflows).person);
    var groups = [];
    X.domainList.forEach(function (d) {
      var wd = obj(obj(obj(model.workflows).domains)[d.code]);
      if (Object.keys(obj(wd.class_mix)).length) { groups.push({key: d.code, label: d.name || d.code, mix: wd.class_mix, none_min: num(wd.none_min)}); }
    });
    if (!groups.length && Object.keys(obj(person.class_mix)).length) { groups.push({key: "person", label: "나 전체", mix: person.class_mix, none_min: num(person.none_min)}); }
    return [card("역할 업무", table(["역할", "과제", {label: "단위업무", num: true}, {label: monthLabel(mk) + " 투입", num: true}, "병목", "표본"], rows,
      {label: "역할 업무 목록"}), {id: "r-wf", state: "투입 순"}),
    card(roleLabel(X, cur), rolePanelBody(model, X, st, env, cur), {id: "r-wf-role", state: "역할 워크플로우"}),
    groups.length ? card(null, chart(C().classMix({groups: groups}, {width: env.width, id: "ch-p10"}), "ch-p10", st), {id: "r-wf-mix"}) : null];
  }

  // ───────────────────────── 11. 리뷰(§6.4) ─────────────────────────
  function causeChips(X, row, env, st) {
    var codes = arr(row.causes);
    var names = arr(row.cause_names);
    var texts = arr(row.cause_texts);
    return h("span", {}, codes.map(function (c, i) {
      var key = idOf(row) + "|" + c;
      var open = st.open["cause:" + key];
      return h("span", {}, [btn(names[i] || c, "r-open", "cause:" + key, {kind: "ghost", expanded: !!open}),
        open ? h("small", {}, [" " + (texts[i] || names[i] || c)]) : null, " "]);
    }));
  }

  function reviewBody(model, X, rv, kind, st, env) {
    var u = U();
    var bt = obj(rv.by_tag);
    var envm = num(rv.env_min);
    var n = function (k) { return arr(rv[k]).length; };
    var out = [];
    out.push(para("근무 " + u.hText(envm) + "(" + TAG_KEYS.map(function (t) { return TAG_NAME[t] + " " + u.fmtH1(num(bt[t])); }).join(" · ") +
      ") · 귀속 " + u.pctText(num(rv.attributed_min), envm) + " · 관측 " + u.pctText(num(rv.obs_min), envm) + " · 새로 시작 " + n("started") +
      " · 끝냄 " + n("finished") + " · 미착수 의뢰 " + n("unstarted")));
    var ai = obj(rv.ai);
    var pt = peerText(X, ai, env);
    if (ai.summary || arr(ai.highlights).length) {
      out.push(h("div", {}, [h("h3", {}, ["요약 ", srcBadge(ai.by || "rule")]), ai.summary ? para(pt(ai.summary)) : null,
        arr(ai.highlights).length ? h("ul", {}, arr(ai.highlights).map(function (hl) {
          var t = typeof hl === "string" ? hl : str(obj(hl).text);
          var nums = highlightNums(X, rv, hl);
          return h("li", {}, [pt(t) + (nums ? " " + nums : "")]);
        })) : null]));
    }
    var lt = arr(rv.lead_table);
    var finRows = (lt.length ? lt : arr(rv.finished).map(function (x) { return {unit_id: idOf(x)}; })).map(function (r) {
      var x = X.units[idOf(r)] || {};
      var cy = arr(x.cycles);
      var c0 = obj(cy[0]);
      var c1 = obj(cy[cy.length - 1]);
      var lead = isNum(r.biz_lead_min) ? r.biz_lead_min : x.biz_lead_min;
      return [link(x.title || idOf(r), "#report/tree/u:" + idOf(r)), projLabel(X, x.project_key), roleLabel(X, x.role_id),
        (c0.sb || "?") + " " + mdhm(c0.s) + " → " + (c1.eb || "…") + " " + mdhm(c1.e), isNum(lead) ? u.daysText(lead) : "—",
        u.hText(isNum(r.effort_min) ? r.effort_min : x.effort_min), u.fmtX(isNum(r.parallel) ? r.parallel : x.parallel), u.gradeBadge(r.grade || x.grade),
        r.overrun ? h("span", {}, [u.badge("초과", "grade-dash", "리드타임이 기준의 문턱을 넘었습니다"), " ", causeChips(X, r, env, st)]) :
          (arr(r.causes).indexOf("NO_BASELINE") >= 0 ? causeChips(X, r, env, st) : "아님")];
    });
    out.push(h("h3", {}, ["끝낸 일"]));
    out.push(finRows.length ? table(["제목", "과제", "역할", "시작 → 끝", {label: "리드", num: true}, {label: "투입", num: true},
      {label: "병행도", num: true}, "등급", "초과 판정"], finRows) : muted("이 기간에 끝낸 일이 없습니다."));
    function unitList(k, title, note) {
      var ids = arr(rv[k]).map(idOf);
      if (!ids.length) { return null; }
      return h("div", {}, [h("h3", {}, [title]), h("ul", {}, ids.map(function (id) {
        var x = X.units[id] || {};
        return h("li", {}, [link(x.title || id, "#report/tree/u:" + id), note ? " · " + note(x) : ""]);
      }))]);
    }
    out.push(unitList("started", "새로 시작한 일", function (x) { return mdhm(obj(arr(x.cycles)[0]).s); }));
    out.push(unitList("continuing", "계속한 일", function (x) { return "투입 " + u.hText(x.effort_min); }));
    out.push(unitList("unstarted", "미착수 의뢰", function (x) { return "의뢰 " + mdhm(obj(arr(x.cycles)[0]).s) + " · 확인 질문 Q02"; }));
    if (kind === "month" && lt.length) {
      var roles = {};
      var pts = [];
      lt.forEach(function (r) {
        var x = X.units[idOf(r)] || {};
        var rid = x.role_id || "-";
        if (!roles[rid]) { roles[rid] = {key: rid, label: roleLabel(X, rid), baseline_biz_min: null}; }
        if (isNum(r.baseline_biz_min) && roles[rid].baseline_biz_min === null) { roles[rid].baseline_biz_min = r.baseline_biz_min; }
        if (isNum(r.biz_lead_min)) {
          pts.push({unit_id: idOf(r), row: rid, biz_lead_min: r.biz_lead_min, overrun: !!r.overrun, causes: arr(r.causes),
            cause_names: arr(r.cause_names), title: x.title, effort_min: isNum(r.effort_min) ? r.effort_min : x.effort_min});
        }
      });
      var rowsS = Object.keys(roles).sort().map(function (k) { return roles[k]; });
      out.push(chart(C().leadDots({rows: rowsS, points: pts, std_day_min: num(obj(model.denominator).std_day_min) || 480},
        {width: env.width, id: "ch-p11-" + rv.key, title: "리드타임 점 그림 · " + rv.key}), "ch-p11-" + rv.key, st));
    }
    var otx = otOf(rv);
    var ot = otx.units.slice(0, 5);
    if (ot.length || otx.unattr > 0) {
      out.push(h("div", {}, [h("h3", {}, ["초과 근무 원인"]), h("ul", {}, ot.map(function (o) {
        var tg = obj(o.by_tag);
        var parts = ["extended", "night", "holiday"].filter(function (t) { return num(tg[t]) > 0; }).map(function (t) { return TAG_NAME[t] + " " + u.fmtH1(tg[t]); });
        return h("li", {}, [link(unitTitle(X, idOf(o)), "#report/tree/u:" + idOf(o)), " " + u.hText(num(o.min)) + (parts.length ? "(" + parts.join(" · ") + ")" : "")]);
      }).concat(otx.unattr > 0 ? [h("li", {}, ["업무에 묶이지 않은 초과 " + u.hText(otx.unattr)])] : []))]));
    }
    var ptop = arr(rv.peers_top).slice(0, 5);
    if (ptop.length) {
      out.push(para("함께한 동료: " + ptop.map(function (p) {
        return (obj(p).name || (isNum(obj(p).ref) ? peerName(X, p.ref) : "동료 #" + str(obj(p).k))) + (isNum(obj(p).units) ? " " + p.units + "건" : "");
      }).join(" · ")));
    }
    if (kind === "month") {
      var rel = relationsView(X, rv, ai, pt);
      if (rel) { out.push(rel); }
    }
    var aiNext = typeof ai.next === "string" ? [ai.next] : arr(ai.next).filter(function (s) { return typeof s === "string" && s; });
    var next = aiNext.length ? aiNext.map(pt) :
      arr(rv.continuing).concat(arr(rv.started)).slice(0, 2).map(function (x) { return "'" + unitTitle(X, idOf(x)) + "' 를 이어서 진행합니다."; });
    if (next.length) { out.push(h("div", {}, [h("h3", {}, ["다음"]), h("ul", {}, next.map(function (s) { return h("li", {}, [s]); }))])); }
    return h("div", {}, out);
  }

  // AI 문장 속 번호표 '동료k'(그 질의 안 번호 — COPILOT §8.5) → 사람 사전 이름(R §3.6). 전체판에서만 바꾼다 — 가림판은 모델이
  // 이미 '동료 #k' 로 바꿔 두었고 peers_map 도 싣지 않는다. 대응이 없으면 글자 그대로.
  function peerText(X, ai, env) {
    var pm = obj(obj(ai).peers_map);
    if (env.variant === "redacted" || !Object.keys(pm).length) { return function (s) { return str(s); }; }
    return function (s) {
      return str(s).replace(/동료(\d+)(?![\d#])/g, function (all, k) {
        var ref = pm["동료" + k];
        var p = ref === null || ref === undefined ? null : X.people[String(ref)];
        return p && p.name ? str(p.name) : all;
      });
    };
  }

  // 관계 간선 끝점(모델 edge_refs — 'c:<k>' 동료 · 'd:<k>' 문서 · 'a:<앱>' · 단위업무 ID · 과제·역할 키) → 글자. 모르면 모델 라벨.
  function edgeEnd(X, nid, label, pt) {
    var id = str(nid);
    var m = /^([cd]):(\d+)$/.exec(id);
    if (m) {
      var ref = (m[1] === "c" ? X.people : X.docs)[m[2]];
      if (ref && ref.name) { return str(ref.name); }
    } else if (/^a:/.test(id) && X.apps[id.slice(2)]) {
      return appName(X, id.slice(2));
    } else if (X.units[id]) {
      return unitTitle(X, id);
    } else if (X.projects[id]) {
      return projLabel(X, id);
    } else if (X.roles[id]) {
      return roleLabel(X, id);
    }
    return pt(label) || id || "—";
  }

  function edgeText(X, rv, e, pt) {
    var ref = obj(obj(rv.edge_refs)[e[0]]);
    return edgeEnd(X, ref.from, e[1], pt) + " → " + str(e[2] || ref.rel) + " → " + edgeEnd(X, ref.to, e[3], pt);
  }

  // (월간) 관계(R §6.4 ⑧): AI relations 문장마다 근거 관계(E 번호 → '출발 → 관계 → 도착'). AI 문장이 없으면 그 달 관계 목록.
  function relationsView(X, rv, ai, pt) {
    var edges = arr(rv.edges).filter(function (e) { return Array.isArray(e) && e.length >= 4; });
    var byE = {};
    edges.forEach(function (e) { byE[e[0]] = e; });
    var rels = typeof ai.relations === "string" ? [{text: ai.relations}] : arr(ai.relations);
    var items = [];
    rels.forEach(function (r) {
      var t = typeof r === "string" ? r : str(obj(r).text);
      var refs = arr(obj(r).refs).map(function (n) { return byE[n]; }).filter(Boolean);
      if (!t && !refs.length) { return; }
      items.push(h("li", {}, [pt(t), refs.length ? h("small", {"class": "muted"}, [(t ? " — " : "") + refs.map(function (e) {
        return edgeText(X, rv, e, pt);
      }).join(" · ")]) : null]));
    });
    if (!items.length) {
      edges.slice(0, 12).forEach(function (e) { items.push(h("li", {}, [edgeText(X, rv, e, pt)])); });
    }
    if (!items.length) { return null; }
    return h("div", {}, [h("h3", {}, ["관계"]), h("ul", {}, items), link("연관 그래프에서 보기", "#report/graph")]);
  }

  // 하이라이트 끝 숫자(R §6.4 ②): 모델이 하이라이트마다 싣는 그 기간 투입(effort_min)·리드(biz_lead_min).
  // 옛 모델(숫자 없음)은 refs 의 사실 행 → 단위업무 전체 투입·리드.
  function highlightNums(X, rv, hl) {
    var o = obj(hl);
    var u = U();
    if (isNum(o.effort_min) || isNum(o.biz_lead_min)) {
      var parts = [];
      if (num(o.effort_min) > 0) { parts.push("투입 " + u.hText(o.effort_min)); }
      if (isNum(o.biz_lead_min)) { parts.push("리드 " + u.daysText(o.biz_lead_min)); }
      return parts.length ? "(" + parts.join(" · ") + ")" : "";
    }
    var fu = obj(rv.fact_units);
    var facts = arr(rv.facts);
    var segs = [];
    arr(o.refs).forEach(function (ref) {
      var id = fu[ref];
      if (!id) {
        var f = facts.filter(function (x) { return (Array.isArray(x) ? x[0] : obj(x).id) === ref; })[0];
        id = f && !Array.isArray(f) ? obj(f).unit_id : null;
      }
      var x = id ? X.units[id] : null;
      if (x) { segs.push("투입 " + u.hText(x.effort_min) + (isNum(x.biz_lead_min) ? " · 리드 " + u.daysText(x.biz_lead_min) : "")); }
    });
    return segs.length ? "(" + uniq(segs).join(" / ") + ")" : "";
  }

  function viewReview(model, X, st, env) {
    var kind = st.ui.review === "week" ? "week" : "month";
    var R = obj(model.reviews);
    var list = arr(kind === "week" ? R.weeks : R.months).filter(function (r) { return r && r.key; }).slice()
      .sort(function (a, b) { return cmp(b.key, a.key); });
    var out = [toggles("리뷰 단위", [["week", "주간"], ["month", "월간"]], kind, "r-ui-review")];
    if (!list.length) { out.push(card("리뷰", emptyP("이 기간의 리뷰 사실이 없습니다."), {id: "r-review"})); return out; }
    list.forEach(function (rv, i) {
      var k = "rv:" + rv.key;
      var def = kind === "week" ? i < 2 : (rv.key === st.month || (st.month === ALL && i === 0) || (!X.monthBy[st.month] && i === 0));
      var open = st.open[k] === undefined ? def : st.open[k];
      var title = (kind === "week" ? "주간 " : "월간 ") + rv.key + (rv.from && rv.to ? " (" + rv.from + " ~ " + rv.to + ")" : "") +
        (rv.partial ? " · 부분" : "");
      out.push(card(title, open ? reviewBody(model, X, rv, kind, st, env) : null, {id: "r-rv-" + rv.key.replace(/[^0-9A-Za-z-]/g, ""),
        tools: [btn(open ? "접기" : "펼치기", "r-open", k, {kind: "ghost", expanded: open})]}));
    });
    return out;
  }

  // ───────────────────────── 12. 동료(§6.5) ─────────────────────────
  function viewPeers(model, X, st, env) {
    var u = U();
    var P = obj(model.peers);
    var list = arr(P.internal);
    var metric = st.ui.peers === "effort" ? "effort" : "units";
    var out = [para("같은 단위업무에 함께 등장한 사람입니다(요청·보고·대화 2건 이상·10명 이하 회의). 이름은 이 PC 에서만 보입니다. 팀에는 가명 키로만 갑니다.")];
    if (!list.length) { out.push(card("같이 일한 동료", emptyP("같은 단위업무에 함께 나온 동료가 없습니다."), {id: "r-peers"})); }
    else {
      var top = list.slice(0, 20);
      var res = C().peerBars({peers: top}, {width: env.width, metric: metric, id: "ch-p12"});
      out.push(card(null, h("div", {}, [toggles("막대 기준", [["units", "공동 단위업무 수"], ["effort", "공유 투입 h"]], metric, "r-ui-peers"),
        chart(res, "ch-p12", st), list.length > 20 ? muted("그 밖 " + (list.length - 20) + "명") : null]), {id: "r-peers-chart"}));
      var rows = list.map(function (p) {
        var k = "peer:" + p.k;
        var open = !!st.open[k];
        var rl = obj(p.roles);
        var shared = X.unitList.filter(function (x) { return arr(x.peers).indexOf(p.ref) >= 0; });
        return {cells: [h("span", {}, [btn(open ? "▾" : "▸", "r-open", k, {kind: "ghost", expanded: open, aria: (open ? "접기 " : "펼치기 ") + (p.name || "")}),
          " ", p.name || ("동료 #" + p.k)]), peerClass(p, X), String(num(p.units)),
          u.hText(num(p.shared_effort_min)), "의뢰 " + num(rl.requester) + " · 보고 " + num(rl.reporter) + " · 대화 " + num(rl.thread) +
          " · 회의 " + num(rl.meeting), arr(p.projects).slice(0, 3).map(function (k2) { return projLabel(X, k2); }).join(", "),
          str(p.first) + " ~ " + str(p.last)],
        detail: open ? (shared.length ? table(["단위업무", "역할", "기간", {label: "투입", num: true}], shared.map(function (x) {
          return [link(x.title || x.unit_id, "#report/tree/u:" + x.unit_id), roleLabel(X, x.role_id),
            str(x.first_evidence) + " ~ " + str(x.last_evidence), u.hText(x.effort_min)];
        })) : muted("공동 단위업무 목록이 이 결과에 없습니다.")) : null};
      });
      out.push(card("동료 표", table(["이름", "사내/외부", {label: "공동 단위업무", num: true}, {label: "공유 투입", num: true}, "관계",
        "함께한 과제", "처음 ~ 마지막"], rows, {label: "같이 일한 동료"}), {id: "r-peers-table"}));
    }
    var ex = obj(P.external);
    out.push(para("외부 상대: 고객사 " + num(ex.customer) + "명 · 협력사 " + num(ex.partner) + "명 · 그 밖 " + num(ex.other) + "명(외부는 사람이 아니라 도메인 계급으로 묶습니다)"));
    out.push(muted("팀 보고서에서는 이 사람이 팀원이면 팀원 라벨, 아니면 '동료-xxxx' 로 보입니다."));
    return out;
  }

  // 사내/외부 칸: 사람 사전에서 사내로 확인한 사람만 '사내', 외부로 확인했으면 '외부', 사전에 없거나 모르면 '미확인'
  // (모델 peers.internal[].internal · refs.people[k].internal 은 true 또는 null — 외부 상대는 사람 목록에 들지 않는다)
  function peerClass(p, X) {
    var a = obj(p).internal;
    var b = obj(X.people[String(obj(p).ref)]).internal;
    if (a === true || b === true) { return "사내"; }
    if (a === false || b === false) { return "외부"; }
    return "미확인";
  }

  // ───────────────────────── 13. 연관 그래프(§6.6) ─────────────────────────
  function graphSpec(O, center, offRels, topN) {
    var nodes = arr(O.nodes);
    var edges = arr(O.edges);
    var byId = {};
    nodes.forEach(function (nd) { byId[nd.id] = nd; });
    if (!byId[center]) { return null; }
    var keep = {};
    keep[center] = true;
    function memb(a, b) {
      return edges.filter(function (e) { return e.rel === "소속" && ((e.from === a && e.to === b) || (e.from === b && e.to === a)); }).length > 0;
    }
    var roles = nodes.filter(function (nd) { return nd.type === "R" && memb(nd.id, center); });
    roles.forEach(function (r) { keep[r.id] = true; });
    var units = nodes.filter(function (nd) { return nd.type === "U" && roles.some(function (r) { return memb(nd.id, r.id); }); });
    units.forEach(function (x) { keep[x.id] = true; });
    var wt = {};
    edges.forEach(function (e) {
      if (e.rel === "소속" || offRels[e.rel]) { return; }
      var o = keep[e.from] && byId[e.from].type === "U" ? e.to : (keep[e.to] && byId[e.to].type === "U" ? e.from : null);
      if (!o || !byId[o] || "DAC".indexOf(byId[o].type) < 0) { return; }
      if (!wt[o]) { wt[o] = [0, 0]; }
      wt[o][0] += num(e.h);
      wt[o][1] += num(e.w);
    });
    var outer = Object.keys(wt).sort(function (a, b) { return (wt[b][0] - wt[a][0]) || (wt[b][1] - wt[a][1]) || cmp(a, b); });
    outer.slice(0, topN).forEach(function (id) { keep[id] = true; });
    return {spec: {center: center, nodes: nodes.filter(function (nd) { return keep[nd.id]; }),
      edges: edges.filter(function (e) { return keep[e.from] && keep[e.to] && (e.rel === "소속" || !offRels[e.rel]); })},
    hidden: Math.max(0, outer.length - topN), units: units};
  }

  function viewGraph(model, X, st, env) {
    var u = U();
    var O = obj(model.ontology);
    if (!arr(O.nodes).length) { return [card("연관 그래프", emptyP("그릴 관계가 없습니다."), {id: "r-graph"})]; }
    var centers = arr(O.nodes).filter(function (nd) { return nd.type === "P"; }).map(function (nd) { return nd.id; });
    var pm = {};
    X.unitList.forEach(function (x) { pm[x.project_key || "UNC"] = num(pm[x.project_key || "UNC"]) + num(x.effort_min); });
    centers.sort(function (a, b) { return (num(pm[b]) - num(pm[a])) || cmp(a, b); });
    var center = st.ui.center && centers.indexOf(st.ui.center) >= 0 ? st.ui.center : (centers.indexOf(O.center) >= 0 ? O.center : centers[0]);
    var off = {};
    Object.keys(st.rels).forEach(function (k) { if (st.rels[k]) { off[k] = true; } });
    var topN = [8, 12, 20].indexOf(+st.ui.topn) >= 0 ? +st.ui.topn : 12;
    var gs = center ? graphSpec(O, center, off, topN) : null;
    var tools = h("div", {}, [
      h("div", {"class": "table-tools", role: "group", "aria-label": "중심 과제"}, centers.map(function (c) {
        return btn((c === center ? "✓ " : "") + projLabel(X, c), "r-ui", "center=" + c, {kind: "ghost", pressed: c === center});
      })),
      h("div", {"class": "table-tools", role: "group", "aria-label": "관계 종류"}, RELS.map(function (r) {
        return btn((off[r] ? "" : "✓ ") + r, "r-rel", r, {kind: "ghost", pressed: !off[r]});
      })),
      toggles("바깥 노드 수", [["8", "8"], ["12", "12"], ["20", "20"]], String(topN), "r-ui-topn")]);
    var out = [];
    if (!gs || !gs.spec.nodes.length) {
      out.push(card("연관 그래프", h("div", {}, [tools, emptyP("이 과제의 연관 그래프 자료가 없습니다.")]), {id: "r-graph"}));
      return out;
    }
    var gunit = st.ui.gunit && X.units[st.ui.gunit] ? st.ui.gunit : null;
    var res = C().radial(gs.spec, {width: env.width, id: "ch-p13", focus: st.ui.focus || null, selected: gunit});
    out.push(card(null, h("div", {}, [tools, chart(res, "ch-p13", st), gs.hidden ? muted("바깥 노드 상위 " + topN + "개만 그렸습니다(그 밖 " + gs.hidden + "개).") : null]),
      {id: "r-graph"}));
    var base = gunit || (gs.units.slice().sort(function (a, b) { return (num(b.weight_min) - num(a.weight_min)) || cmp(a.id, b.id); })[0] || {}).id;
    var recs = arr(obj(O.recs)[base]);
    var recRows = recs.map(function (r) {
      var kd = REC_KIND[r.kind] || [str(r.kind), ""];
      var ev = [];
      if (isNum(r.docs)) { ev.push("공유 문서 " + r.docs); }
      if (isNum(r.peers)) { ev.push("공유 동료 " + r.peers); }
      if (isNum(r.apps)) { ev.push("공유 앱 " + r.apps); }
      if (r.handoff) { ev.push("인계"); }
      var same = r.kind === "same" || r.kind === "same_work";
      return [link(unitTitle(X, r.unit_id), "#report/tree/u:" + r.unit_id), u.fmtNum(r.rel, 2) || "—", h("span", {"data-tip": kd[1]}, [kd[0]]),
        ev.join(" · ") || kd[1], same && st.canWriteFlag ? btn("합치기 질문 만들기", "r-merge", base + "|" + r.unit_id, {kind: "ghost"}) : ""];
    });
    out.push(card("연관 업무 추천 — " + unitTitle(X, base), recRows.length ? table(["대상", {label: "연관도", num: true}, "종류", "근거", "행동"], recRows) :
      emptyP("연관도 문턱을 넘는 업무가 없습니다."), {id: "r-recs"}));
    var rp = arr(O.related_projects).slice(0, 3);
    if (rp.length) {
      out.push(card("연관 과제", chips(rp.map(function (p) { return projLabel(X, p.key) + " " + (u.fmtNum(p.rel, 2) || ""); })), {id: "r-relproj"}));
    }
    return out;
  }

  // ───────────────────────── 14. Agentic(§6.7) ─────────────────────────
  function viewAgentic(model, X, st, env) {
    var u = U();
    var A = obj(model.agentic);
    var out = [];
    if (st.month !== ALL) { out.push(muted("Agentic 값은 분석 기간 전체의 실측 투입입니다(달 선택과 무관).")); }
    var names = {};
    arr(A.catalog).forEach(function (a) { names[a.id] = a.name; });
    arr(A.matches).forEach(function (m) { if (m.name && !names[m.agent_id]) { names[m.agent_id] = m.name; } });
    var matches = arr(A.matches);
    if (!num(A.catalog_n) && !matches.length) {
      out.push(u.alertLine("info", "에이전트 목록이 없습니다 — 팀 레지스트리를 받으면 채워집니다"));
    } else {
      var items = arr(A.items).slice().sort(function (a, b) { return (num(b.occ_week) - num(a.occ_week)) || cmp(a.type, b.type); });
      var agentIds = uniq(arr(A.catalog).map(function (a) { return a.id; }).concat(matches.map(function (m) { return m.agent_id; })));
      var showAll = st.ui.agentsAll === "1";
      var withMatch = agentIds.filter(function (id) { return matches.some(function (m) { return m.agent_id === id; }); });
      var rowsIds = showAll ? agentIds : withMatch;
      var head = h("tr", {}, [h("th", {scope: "col"}, ["에이전트"])].concat(items.map(function (it) {
        return h("th", {scope: "col"}, [it.label || it.type, h("small", {"class": "muted"}, [" " + str(it.freq)])]);
      }), [h("th", {scope: "col", "class": "num"}, ["관련 투입"]), h("th", {scope: "col", "class": "num"}, ["단위업무"])]));
      var body = rowsIds.map(function (id) {
        var mine = matches.filter(function (m) { return m.agent_id === id; });
        var rel = sumBy(mine, function (m) { return m.related_min; });
        var unitsN = uniq([].concat.apply([], mine.map(function (m) { return arr(m.units); }))).length;
        return h("tr", {}, [h("th", {scope: "row"}, [names[id] || id])].concat(items.map(function (it) {
          var m = mine.filter(function (x) { return x.step_type === it.type; })[0];
          return u.agenticCell(m ? m.grade : null, {rule: m && m.by === "rule", disagree: m && m.disagree});
        }), [h("td", {"class": "num"}, [u.hText(rel)]), h("td", {"class": "num"}, [String(unitsN)])]));
      });
      out.push(card("매칭 격자", h("div", {}, [h("div", {"class": "table-wrap"}, [h("table", {"class": "tbl", "aria-label": "Agentic 매칭 격자"},
        [h("thead", {}, [head]), h("tbody", {}, body)])]),
      agentIds.length > withMatch.length ? btn(showAll ? "매칭 있는 것만" : "모두 보기", "r-ui", "agentsAll=" + (showAll ? "0" : "1"), {kind: "ghost"}) : null,
      muted("칸 글자: 상·중·하 · '규칙' = 규칙 판정 · ◇ = 규칙 판정과 다름")]), {id: "r-ag-grid", state: "AI·규칙 매칭"}));
      var mrows = matches.map(function (m) {
        return [m.agent_id, names[m.agent_id] || m.agent_id, m.step_type, h("span", {}, [m.grade || "—", " ", srcBadge(m.by)]),
          h("span", {}, [m.why_ai ? m.why_ai + " " : "", chips(arr(m.why_rule).map(function (w) { return RULE_WHY[w] || w; }))]),
          arr(m.roles).map(function (r) { return roleLabel(X, r); }).join(", "),
          String(arr(m.units).length), u.hText(num(m.related_min))];
      });
      out.push(card("매칭 표", h("div", {}, [table(["에이전트", "이름", "단계 유형", "등급", "근거", "쓰이는 역할", {label: "단위업무", num: true},
        {label: "관련 투입", num: true}], mrows), muted("관련 투입은 그 단계에 실제로 쓴 시간입니다. 에이전트가 대신할 수 있는 시간을 뜻하지 않습니다(중복 포함 — 같은 시간이 여러 에이전트에 걸릴 수 있음).")]),
      {id: "r-ag-table"}));
    }
    var needs = arr(A.needs);
    var nrows = needs.map(function (nd) {
      var dropped = st.needDrop[nd.need_id] !== undefined ? st.needDrop[nd.need_id] : !!nd.dropped;
      // 입력 → 출력: 모델 needs[].in·out(옛 모양 input·output 도 읽는다)
      var nin = str(nd.input || nd["in"]);
      var nout = str(nd.output || nd["out"]);
      return [nd.name || nd.label || nd.need_id, nd.logic || "—", nin || nout ? (nin || "—") + " → " + (nout || "—") : "—", nd.step_type || "—",
        isNum(nd.freq_month) ? u.fmtNum(nd.freq_month, 1) : (isNum(nd.freq_per_month) ? u.fmtNum(nd.freq_per_month, 1) : "—"), nd.grade || "—",
        srcBadge(nd.by || nd.src), String(arr(nd.units).length),
        st.canWriteFlag ? btn(dropped ? "팀에 올리기" : "팀에 올리지 않기", "r-need", nd.need_id, {kind: "ghost", pressed: dropped}) : (dropped ? "팀 제외" : "—")];
    });
    out.push(card("새 니즈", nrows.length ? table(["이름", "무엇을", "입력 → 출력", "단계 유형", {label: "월 빈도", num: true}, "등급", "출처",
      {label: "관련 단위업무", num: true}, "팀"], nrows) : emptyP("새 니즈 후보가 없습니다."), {id: "r-needs"}));
    return out;
  }

  // ───────────────────────── 15. 서브에이전트(§6.8) ─────────────────────────
  function sc(s, k) {
    var low = k.toLowerCase();
    if (isNum(s[low])) { return s[low]; }
    if (isNum(s[k])) { return s[k]; }
    var o = obj(s.scores);
    return isNum(o[k]) ? o[k] : (isNum(o[low]) ? o[low] : 0);
  }

  function viewSubagent(model, X, st, env) {
    var u = U();
    var roles = arr(obj(model.subagent).roles);
    var out = [];
    if (st.month !== ALL) { out.push(muted("서브에이전트 검토는 분석 기간 전체의 단계 통계로 계산합니다(달 선택과 무관).")); }
    if (!roles.length) { out.push(card("서브에이전트 검토표", emptyP("이 기간에 만들어진 단위업무가 없습니다."), {id: "r-sa"})); return out; }
    var eff = {};
    roles.forEach(function (r) { eff[r.role_id] = sumBy(X.unitList.filter(function (x) { return x.role_id === r.role_id; }), function (x) { return x.effort_min; }); });
    roles.slice().sort(function (a, b) { return (eff[b.role_id] - eff[a.role_id]) || cmp(a.role_id, b.role_id); }).forEach(function (r) {
      var ai = obj(r.ai);
      var rows = arr(r.steps).map(function (s) {
        var tot = sc(s, "REP") + sc(s, "IO") + sc(s, "TOOL") + sc(s, "VER") + (2 - sc(s, "RISK"));
        var score = isNum(s.score) ? s.score : tot;
        return [String(s.no), stepName(s), s.code || s.type || "—", u.scoreDots(sc(s, "REP")), u.scoreDots(sc(s, "IO")), u.scoreDots(sc(s, "TOOL")),
          u.scoreDots(sc(s, "VER")), u.scoreDots(sc(s, "RISK"), true), score + "/10", s.rule ? u.verdictBadge(s.rule) : "—",
          h("span", {"data-tip": s.final && s.rule && s.final !== s.rule ? "AI 의견보다 보수적" : null}, [s.final ? u.verdictBadge(s.final) : "—"]),
          chips(arr(s.why).map(function (w) { return SUB_WHY[w] || w; })),
          s.check || (arr(ai.subs).some(function (x) { return arr(x.steps).indexOf("S" + s.no) >= 0; }) && s.rule === "부적합" ? "사람 확인 필요" : "—")];
      });
      var subs = arr(ai.subs).map(function (x) {
        var bad = arr(x.steps).some(function (sn) {
          var st0 = arr(r.steps).filter(function (s) { return "S" + s.no === sn || s.no === sn; })[0];
          return st0 && st0.rule === "부적합";
        });
        return h("li", {}, [arr(x.steps).join("·") + " → " + str(x.role) + (x.io ? " · " + x.io : "") + (x.check ? " · 확인 지점 " + x.check : ""),
          bad ? " " : null, bad ? u.badge("사람 확인 필요", "grade-dash") : null]);
      });
      var body = h("div", {}, [
        para("규칙 판정 " + str(r.rule || "—") + " · AI 의견 " + str(ai.verdict || "없음") + (isNum(r.fit_share) ? " · 적합 단계 분 비율 " + u.shareText(r.fit_share) : "")),
        r.basis ? muted("판정 근거: " + str(r.basis)) : null,
        table(["번호", "단계 라벨", "유형", "반복성", "입출력 정형성", "도구 접근", "검증 가능성", "위험", {label: "점수", num: true}, "규칙 판정", "최종", "근거", "사람 확인 지점"], rows,
          {label: "서브에이전트 점수 표 " + roleLabel(X, r.role_id)}),
        ai.orch || subs.length ? h("div", {}, [h("h3", {}, ["AI 구성안 ", srcBadge(ai.by)]), ai.orch ? para("오케스트레이터: " + ai.orch) : null,
          subs.length ? h("ul", {}, subs) : null, ai.risk ? para("주의점: " + ai.risk) : null]) : null]);
      out.push(card(roleLabel(X, r.role_id), body, {id: "r-sa-" + str(r.role_id).replace(/[^0-9A-Za-z_-]/g, ""),
        tools: [r.final ? u.verdictBadge(r.final) : u.badge("판정 없음")]}));
    });
    var openC = !!st.open["sa-crit"];
    out.push(card("판정 기준", openC ? h("ul", {}, [
      h("li", {}, ["반복성: 주 1회 이상 2 · 월 1회 이상 1"]), h("li", {}, ["입출력 정형성: 디지털 입력 1 + 정형 입력 1"]),
      h("li", {}, ["도구 접근: 열린 형식·자동화 인터페이스 2 · 상용 GUI 도구 1 · 사람의 자리 0"]),
      h("li", {}, ["검증 가능성: 규칙·재실행으로 확인 2 · 사람이 빠르게 검토 1 · 판단·합의 0"]),
      h("li", {}, ["위험(높을수록 나쁨): 외부 상대 · 금액 · 대외 발신 단계"]),
      h("li", {}, ["점수 = 반복성 + 입출력 + 도구 + 검증 + (2 − 위험), 최종은 규칙과 AI 의견 중 더 보수적인 쪽"])]) : null,
    {id: "r-sa-crit", tools: [btn(openC ? "접기" : "펼치기", "r-open", "sa-crit", {kind: "ghost", expanded: openC})]}));
    return out;
  }

  // ───────────────────────── 16. 확인 질문(§6.9) ─────────────────────────
  function qControls(model, X, st, item) {
    var qid = item.qid;
    var opts = QA[item.code] || [["approve", "맞음"]];
    var pick = st.q[qid];
    var err = st.qerr[qid] || {};
    var kids = [h("div", {"class": "table-tools", role: "group", "aria-label": "응답 고르기"}, opts.map(function (o) {
      return btn((pick === o[0] ? "✓ " : "") + o[1], "r-qpick", qid + "|" + o[0], {kind: "ghost", pressed: pick === o[0]});
    }))];
    var chosen = opts.filter(function (o) { return o[0] === pick; })[0];
    var need = chosen ? (chosen[2] || "") : "";
    var p = "q-" + qid;
    var d0 = str(obj(item).date || str(obj(item).d)).slice(0, 10);
    if (/at|span/.test(need)) {
      kids.push(field(p + "-d", "날짜", input(p + "-d", "date", d0 || null, {"aria-invalid": err.d ? "true" : null, required: true}), {error: err.d}));
    }
    if (need === "at" || need === "at_hours") {
      kids.push(field(p + "-t", "시각", input(p + "-t", "time", null, {"aria-invalid": err.t ? "true" : null, required: true}), {error: err.t}));
    }
    if (/span/.test(need)) {
      kids.push(field(p + "-a", "시작 시각", input(p + "-a", "time", null, {"aria-invalid": err.a ? "true" : null}), {error: err.a}));
      kids.push(field(p + "-b", "끝 시각", input(p + "-b", "time", null, {"aria-invalid": err.b ? "true" : null}), {error: err.b}));
    }
    if (/hours/.test(need)) {
      kids.push(field(p + "-hours", "시간(h)", input(p + "-hours", "number", null, {min: "0.25", max: "16", step: "0.25",
        "aria-invalid": err.hours ? "true" : null}), {error: err.hours, help: need === "hours_opt" ? "선택 사항 — 0.25 단위" : "0.25~16, 0.25 단위"}));
    }
    if (/unit/.test(need)) {
      var cands = arr(obj(item.proposal).cands).concat(arr(item.cands)).map(idOf).filter(function (id) { return X.units[id]; });
      if (!cands.length) {
        var tu = X.units[str(item.target)];
        cands = X.unitList.filter(function (x) { return tu && x.role_id === tu.role_id && x.unit_id !== tu.unit_id; }).slice(0, 30).map(function (x) { return x.unit_id; });
      }
      kids.push(field(p + "-unit", "업무", select(p + "-unit", [["", "고르세요"]].concat(uniq(cands).map(function (id) { return [id, unitTitle(X, id)]; })), "",
        {"aria-invalid": err.unit ? "true" : null}), {error: err.unit}));
    }
    if (need === "project") {
      var projs = arr(model.projects).map(function (pr) { return [pr.key, projLabel(X, pr.key)]; });
      kids.push(field(p + "-project", "과제", select(p + "-project", [["", "고르세요"]].concat(projs), "", {"aria-invalid": err.project ? "true" : null}),
        {error: err.project}));
    }
    if (need === "wtype") {
      kids.push(field(p + "-wtype", "업무 유형", select(p + "-wtype", [["", "고르세요"]].concat(WTYPES.map(function (w) { return [w, w]; })), "",
        {"aria-invalid": err.wtype ? "true" : null}), {error: err.wtype}));
    }
    if (pick) { kids.push(h("div", {"class": "table-tools"}, [btn("응답 보내기", "r-qsend", qid, {kind: "primary"})])); }
    return h("div", {role: "group", "aria-label": "응답"}, kids);
  }

  function viewQueue(model, X, st, env) {
    var u = U();
    var items = arr(model.queue).filter(function (q) { return q && q.qid; });
    var out = [];
    if (!items.length) { return [card("확인 질문", emptyP("이번 주에 확인할 질문이 없습니다."), {id: "r-queue"})]; }
    if (!st.canWriteFlag) { out.push(u.alertLine("info", "확인 질문 응답은 로컬 앱에서만 할 수 있습니다 — 이 파일은 읽기 전용입니다")); }
    items.forEach(function (q) {
      var code = str(q.code);
      var tag = code.charAt(0) === "H" ? "분류" : "시간";
      var tu = X.units[str(q.target)];
      var target = tu ? tu.title || tu.unit_id : (/^\d{4}-\d{2}-\d{2}/.test(str(q.target)) ? str(q.target) : (q.date || q.target || "—"));
      var answered = st.answered[q.qid] || q.status === "answered";
      var why = q.why_ko || q.why || "";
      var body = h("div", {}, [
        para("대상: " + target + " · 영향 " + u.hText(num(q.impact_min)) + (q.week ? " · " + q.week : "")),
        why ? para("왜 묻나: " + (typeof why === "string" ? why : arr(why).join(" · "))) : null,
        answered ? u.alertLine("info", typeof st.answered[q.qid] === "string" ? st.answered[q.qid] : "응답함 — 다시 분석하면 반영됩니다") :
          (st.canWriteFlag ? qControls(model, X, st, q) : null)]);
      out.push(card(code + " " + (q.name || Q_NAME[code] || "확인 질문"), body, {id: "q-card-" + q.qid,
        tools: [u.badge(tag), u.badge(answered ? "응답함" : "열림")]}));
    });
    return out;
  }

  // 응답 폼 읽기·검사(제어기가 부른다) — 오류면 {errs}, 아니면 {answer}
  function readAnswer(X, item, pick, getVal) {
    var opts = QA[item.code] || [["approve", "맞음"]];
    var chosen = opts.filter(function (o) { return o[0] === pick; })[0];
    if (!chosen) { return {errs: {choice: "응답을 고르세요"}}; }
    var need = chosen[2] || "";
    var p = "q-" + item.qid;
    var ans = {choice: pick};
    var errs = {};
    var d = str(getVal(p + "-d"));
    if (/at|span/.test(need)) {
      if (!/^\d{4}-\d{2}-\d{2}$/.test(d)) { errs.d = "날짜를 넣어 주세요"; } else { ans.d = d; }
    }
    if (need === "at" || need === "at_hours") {
      var t = str(getVal(p + "-t"));
      if (!/^\d{2}:\d{2}$/.test(t)) { errs.t = "시각을 넣어 주세요"; } else if (ans.d) { ans.at = ans.d + "T" + t; }
    }
    if (/span/.test(need)) {
      var a = str(getVal(p + "-a"));
      var b = str(getVal(p + "-b"));
      if (a || b) {
        if (!/^\d{2}:\d{2}$/.test(a)) { errs.a = "시작 시각을 넣어 주세요"; }
        if (!/^\d{2}:\d{2}$/.test(b)) { errs.b = "끝 시각을 넣어 주세요"; } else if (/^\d{2}:\d{2}$/.test(a) && b <= a) {
          errs.b = "끝은 시작보다 늦어야 합니다(자정을 넘기면 둘로 나눠 넣어 주세요)";
        }
        if (!errs.a && !errs.b) { ans.a = a; ans.b = b; }
      }
    }
    if (/hours/.test(need)) {
      var hv = str(getVal(p + "-hours"));
      if (hv === "" && need === "hours_opt") { /* 선택 사항 */ } else {
        var x = Number(hv);
        if (!(x >= 0.25 && x <= 16) || Math.round(x * 4) !== x * 4) { errs.hours = "0.25~16 사이 시간을 0.25 단위로 넣어 주세요"; } else { ans.hours = x; }
      }
    }
    if (/unit/.test(need)) {
      var uu = str(getVal(p + "-unit"));
      if (!uu || !X.units[uu]) { errs.unit = "업무를 골라 주세요"; } else { ans.unit = uu; }
    }
    if (need === "project") {
      var pj = str(getVal(p + "-project"));
      if (!pj) { errs.project = "과제를 골라 주세요"; } else { ans.project = pj; }
    }
    if (need === "wtype") {
      var wt = str(getVal(p + "-wtype"));
      if (WTYPES.indexOf(wt) < 0) { errs.wtype = "유형을 골라 주세요"; } else { ans.wtype = wt; }
    }
    return Object.keys(errs).length ? {errs: errs} : {answer: ans};
  }

  // ───────────────────────── 17. 분류(§6.11) ─────────────────────────
  function viewHier(model, X, st, env) {
    var u = U();
    var dist = {};
    X.unitList.forEach(function (x) { var lv = x.label_level || "unclassified"; dist[lv] = num(dist[lv]) + num(x.effort_min); });
    var hs = st.hier && st.hier.data ? obj(st.hier.data) : {};
    var reg = obj(hs.registry);
    var fr = obj(obj(model.flags).registry);
    var regText = reg.status_text || ("레지스트리 " + (isNum(reg.version) ? "v" + reg.version : (isNum(fr.version) ? "v" + fr.version : "없음")) +
      (reg.fetched_at || fr.fetched_at ? "(" + mdhm(reg.fetched_at || fr.fetched_at) + " 받음)" : "") +
      (isNum(reg.team_projects) ? " · 팀 과제 " + reg.team_projects : "") + (isNum(reg.my_projects) ? " · 내 과제 " + reg.my_projects : "") +
      (isNum(reg.reserved) ? " · 예약 " + reg.reserved : ""));
    // AI 분류 비율(hier_meta.ai_share) — 로컬 앱은 분류 상태 API, 파일은 모델 flags.hier.ai_share(옛 이름 hier_ai_share 도 읽는다)
    var fh = obj(obj(model.flags).hier);
    var aiShare = isNum(hs.ai_share) ? hs.ai_share : (isNum(fh.ai_share) ? fh.ai_share : obj(model.flags).hier_ai_share);
    var out = [card("분류 요약", h("div", {}, [para(regText), h("p", {}, ["단위업무 투입의 분류 신뢰: ", levelBar(dist, uncText(X)) || "—", " ",
      LEVELS.map(function (l) { return (l[1] || uncText(X)) + " " + U().pctText(num(dist[l[0]]), sumBy(LEVELS, function (x) { return dist[x[0]]; })); }).join(" · ")]),
    isNum(aiShare) ? para("AI 분류 비율 " + u.shareText(aiShare)) : null]), {id: "r-hier-head"})];
    if (!st.canWriteFlag) {
      out.push(u.alertLine("info", "분류 고치기·제안 처리는 로컬 앱에서만 할 수 있습니다."));
      return out;
    }
    if (!st.hier || st.hier.state === "loading") { out.push(card("분류 상태", para("분류 상태를 읽는 중입니다…"), {id: "r-hier"})); return out; }
    if (st.hier.state === "err") {
      out.push(card("분류 상태", h("div", {}, [u.alertLine("bad", "분류 상태를 읽지 못했습니다. 다시 읽으면 이어서 보입니다."),
        btn("다시 읽기", "r-hier-reload", "", {kind: "ghost"})]), {id: "r-hier"}));
      return out;
    }
    arr(hs.notices).forEach(function (t) { out.push(u.alertLine("info", str(obj(t).text_ko || t))); });
    var cn = obj(hs.codename);
    if (cn.show) {
      var crows = arr(cn.cands).map(function (c) {
        return [c.word, String(num(c.groups)), String(num(c.weeks)), arr(c.examples).slice(0, 3).join(" / "),
          h("span", {}, [btn("과제 이름(코드네임)", "r-codename", c.word + "|project", {kind: "ghost"}), btn("고객사 이름", "r-codename", c.word + "|customer", {kind: "ghost"}),
            btn("무시", "r-codename", c.word + "|ignore", {kind: "ghost"})])];
      });
      out.push(card("초기 설정 — 코드네임 검토", h("div", {}, [table(["낱말", {label: "묶음 수", num: true}, {label: "주 수", num: true}, "예시 제목", "처리"], crows),
        h("div", {"class": "table-tools"}, [btn("이대로 진행(나머지 무시)", "r-codename", "|proceed", {kind: "primary"}), btn("건너뛰기", "r-codename", "|skip", {kind: "ghost"})])]),
      {id: "r-codename"}));
    } else if (cn.skipped) {
      out.push(u.alertLine("warn", "레지스트리 없이 코파일럿을 쓰면 제목 속 과제 이름이 그대로 갈 수 있습니다"));
    }
    var prows = arr(hs.proposals).map(function (p) {
      var id = p.proposal_id;
      var rej = p.state === "rejected";
      var done = p.state === "mapped" || p.state === "merged";        // 팀 과제로 연결됨·다른 제안에 합쳐짐 — 처리할 것이 없다
      var acts = rej ? [btn("거절 취소", "r-prop", id + "|unreject", {kind: "ghost"})] : (done ? [str(p.mapped_to || p.merged_into || "—")] : [
        p.state === "accepted_local" ? null : btn("내 과제로 받기", "r-prop", id + "|accept", {kind: "ghost"}),
        btn("기존 과제와 같음", "r-prop", id + "|map", {kind: "ghost"}), btn("이름 바꾸기", "r-prop", id + "|rename", {kind: "ghost"}),
        btn("다른 제안과 합치기", "r-prop", id + "|merge", {kind: "ghost"}), btn("거절", "r-prop", id + "|reject", {kind: "ghost"})]);
      return [p.name || id, h("span", {}, [domChip(obj(X.domains[p.domain_guess]).color), " ", domName(X, p.domain_guess)]), String(num(p.units)),
        u.hText(num(p.effort_min)), p.first || p.last ? str(p.first) + " ~ " + str(p.last) : "—", str(p.src_ko || p.src) || "—",
        str(p.state_ko || p.state), h("span", {}, acts)];
    });
    out.push(card("새 과제 제안", prows.length ? table(["이름", "영역 추정", {label: "단위업무", num: true}, {label: "투입", num: true}, "처음 ~ 마지막", "출처", "상태", "처리"], prows) :
      emptyP("새 과제 제안이 없습니다."), {id: "r-props"}));
    var rrows = arr(hs.rules).map(function (r) {
      var on = r.state === "active" || r.state === "candidate";
      var old = r.state === "superseded";                              // 나중 수정이 대신한 옛 규칙(기록만 — 켜고 끌 수 없음)
      return [str(r.kind_ko || r.kind), str(r.cond) || "—", str(r.result) || "—", str(r.state_ko || r.state),
        num(r.hits) + " · " + num(r.agree) + " · " + num(r.disagree),
        h("span", {}, old ? ["—"] : [btn(on ? "끄기" : "다시 켜기", "r-rule", r.rule_id + "|" + (on ? "off" : "on"), {kind: "ghost"}),
          btn("팀 규칙으로 제안", "r-rule", r.rule_id + "|copy_team", {kind: "ghost"})])];
    });
    out.push(card("학습한 규칙", rrows.length ? table(["종류", "조건", "결과", "상태", "적중 · 일치 · 불일치", "처리"], rrows) : emptyP("학습한 규칙이 아직 없습니다."), {id: "r-rules"}));
    var un = arr(hs.unapplied);
    out.push(card("미적용 수정", un.length ? h("div", {}, [table(["날짜", "바꾼 값", {label: "대상 근거 수", num: true}], un.map(function (c) {
      return [str(c.date), str(c.set_ko || (c.set && JSON.stringify(c.set))), String(num(c.n_keys))];
    })), muted("다시 수집·분석해서 대상이 돌아오면 자동으로 적용됩니다.")]) : emptyP("적용하지 못한 수정이 없습니다."), {id: "r-unapplied"}));
    return out;
  }

  // ───────────────────────── 18. 근거 드릴다운(§6.10) ─────────────────────────
  function crumbs(parts) {
    var kids = [];
    parts.forEach(function (p, i) {
      if (i) { kids.push(" › "); }
      kids.push(p[1] ? link(p[0], p[1]) : h("strong", {}, [p[0]]));
    });
    return h("nav", {"aria-label": "어디서 왔는지", "class": "head-band"}, kids);
  }

  function drillMsg(dr, what) {
    if (!dr || dr.state === "loading") { return para(what + "을 읽는 중입니다…"); }
    if (dr.state === "none") { return U().alertLine("info", "이 파일에는 근거 상세가 없습니다 — 로컬 앱에서 보세요"); }
    if (dr.state === "missing") { return U().alertLine("info", "이 " + what + "의 근거 상세가 이 결과에 없습니다."); }
    return U().alertLine("bad", (dr.text || what + "을 읽지 못했습니다") + " — 다시 열면 이어서 읽습니다.");
  }

  function viewEvidence(model, X, st, env) {
    var arg = str(st.ev);
    if (/^u_[0-9a-f]+$/.test(arg)) { return evidenceUnit(model, X, st, env, arg); }
    if (/^\d{4}-\d{2}-\d{2}$/.test(arg)) { return evidenceDay(model, X, st, env, arg); }
    var mk = /^\d{4}-\d{2}$/.test(arg) ? arg : (st.month !== ALL ? st.month : asOfMonth(X, model));
    var res = C().dailyBars({days: arr(model.days), month: mk}, {width: env.width, id: "ch-p03"});
    var nav = h("div", {"class": "table-tools", role: "group", "aria-label": "달"}, X.months.map(function (r) {
      return h("a", {href: "#report/evidence/" + r.m, "class": "btn btn-ghost", "aria-current": r.m === mk ? "page" : null}, [(r.m === mk ? "✓ " : "") + r.m]);
    }));
    var row = X.monthBy[mk];
    return [crumbs([[mk, null]]), card(null, h("div", {}, [nav, row ? para(mk + " · 근무 " + U().hText(row.env_min) + " · " +
      (num(row.denom_min) > 0 ? U().fmtMM(num(row.env_min), row.denom_min) + " MM" : "—") + (row.partial ? " · " + partialText(row) : "")) : null,
    chart(res, "ch-p03", st), muted("막대를 누르면 그날의 날짜 원장과 구간 원장으로 내려갑니다.")]), {id: "r-ev-month"})];
  }

  function ledgerLine(d) {
    var u = U();
    var L = obj(d.ledger);
    var comp = arr(L.components).map(function (c) { return (BASIS_NAME[c[0]] || str(c[0])) + " " + u.fmtH1(num(c[1])); }).join(" + ");
    var ded = arr(L.deductions).map(function (c) { return str(c[0]) + " " + u.fmtSigned(u.fmtH1, num(c[1])); }).join(" ");
    var exc = arr(L.excluded).map(function (c) { return Array.isArray(c) ? str(c[0]) + " " + u.fmtSigned(u.fmtH1, num(c[1])) : str(c); }).join(" ");
    var tags = TAG_KEYS.filter(function (t) { return num(obj(L.by_tag)[t]) > 0; }).map(function (t) { return TAG_NAME[t] + " " + u.fmtH1(L.by_tag[t]); }).join(" · ");
    return d.d + " " + u.hText(num(L.total_min)) + " = " + (comp || "—") + " | " + (ded || exc || "-") + " | " + (tags || "—");
  }

  function evidenceDay(model, X, st, env, d) {
    var u = U();
    var dr = st.drill["day:" + d];
    var mk = d.slice(0, 7);
    var out = [crumbs([[mk, "#report/evidence/" + mk], [d.slice(5), null]])];
    if (!dr || dr.state !== "ok") { out.push(card("날짜 원장 " + d, drillMsg(dr, "날짜"), {id: "r-ev-day"})); return out; }
    var D = obj(dr.data);
    var L = obj(D.ledger);
    var conf = obj(L.conf_min);
    var cov = obj(L.coverage);
    var band = C().dayBand({d: d, intervals: arr(D.intervals), labels: obj(D.labels), s_eff: D.s_eff}, {width: env.width, id: "ch-p16"});
    out.push(card("날짜 원장 " + d + (D.hol ? " · 휴일" : ""), h("div", {}, [para(ledgerLine(D)),
      para("신뢰: 높음 " + u.fmtH1(num(conf.high)) + " · 중간 " + u.fmtH1(num(conf.mid)) + " · 낮음 " + u.fmtH1(num(conf.low)) +
        (num(D.leave) > 0 ? " · 휴가 " + u.fmtNum(num(D.leave), 1) + "일" : "")),
      Object.keys(cov).length ? chips(Object.keys(cov).sort().map(function (k) { return (AXIS_SHORT[k] || k) + ": " + str(cov[k]); })) : null,
      arr(L.flags).length ? para("표식: " + arr(L.flags).join(", ")) : null]), {id: "r-ev-day"}));
    // 24시간 띠 위에 구간 원장 표(빼거나 버린 시간도 줄로 — §6.10.2)
    out.push(card(null, chart(band, "ch-p16", st), {id: "r-ev-band"}));
    out.push(card("구간 원장", table(band.table.cols, band.table.rows, {label: "구간 원장 " + d}), {id: "r-ev-iv"}));
    return out;
  }

  function evidenceUnit(model, X, st, env, id) {
    var u = U();
    var x = X.units[id] || {};
    var dr = st.drill["unit:" + id];
    var cy = arr(x.cycles);
    var mk = str(obj(cy[0]).s).slice(0, 7);
    var day = str(obj(cy[0]).s).slice(0, 10);
    var out = [crumbs([[mk || "근거", mk ? "#report/evidence/" + mk : "#report/evidence"], [day ? day.slice(5) : "—", day ? "#report/evidence/" + day : null],
      [x.title || id, null]])];
    if (!dr || dr.state !== "ok") {
      out.push(card(x.title || id, h("div", {}, [drillMsg(dr, "업무 원장"), x.unit_id ? para("등급 " + str(x.grade) + " · 투입 " + u.hText(x.effort_min) +
        " = 관측 " + u.hText(num(x.obs_min)) + " + 추정 " + u.hText(num(x.est_min))) : null]), {id: "r-ev-unit"}));
      return out;
    }
    var D = obj(dr.data);
    var lv = obj(D.levels_min);
    var est = arr(D.cycles).some(function (c) { return obj(c.start).estimated || obj(c.end).estimated; });
    var cycRows = arr(D.cycles).map(function (c) {
      var s = obj(c.start);
      var e = obj(c.end);
      return [String(num(c.no) + 1), str(s.code) + " " + mdhm(s.t) + (s.estimated ? "(추정)" : ""), str(e.code) + " " + mdhm(e.t) + (e.estimated ? "(추정)" : "") +
        (isNum(e.score) ? " · 점수 " + u.fmtNum(e.score, 1) : "")];
    });
    var evRows = arr(D.evidence).map(function (e) {
      return [str(e.t), str(e.kind) + (e.op ? "·" + e.op : ""), str(e.dir), str(e.who), str(e.title || e.doc), str(e.role)];
    });
    var q01 = arr(model.queue).filter(function (q) { return q.code === "Q01" && q.target === id; })[0];
    out.push(card((D.title || x.title || id), h("div", {}, [
      h("p", {}, [srcBadge(D.title_by), " ", u.gradeBadge(D.grade || x.grade), " ", STATUS_NAME[D.status] || str(D.status)]),
      D.explain ? para(D.explain) : null,
      est && q01 && st.canWriteFlag ? link("확인 질문으로 바로잡기", "#report/queue/" + q01.qid) : null,
      h("h3", {}, ["경계"]), table(["차수", "시작", "끝"], cycRows),
      h("h3", {}, ["투입 내역"]), para("관측 " + u.hText(num(D.obs_min)) + " · 추정 " + u.hText(num(D.est_min))),
      table(["단계", "뜻", {label: "분", num: true}], LEVEL_KEYS.filter(function (k) { return isNum(lv[k]); }).map(function (k) { return [k, LEVEL_NOTE[k], String(lv[k])]; })),
      h("h3", {}, ["증거 줄"]),
      env.variant === "redacted" ? muted("가림판에는 근거 줄이 없습니다(경계 코드·투입 내역만).") :
        (evRows.length ? table(["시각", "종류", "방향", "상대", "제목·문서", "역할"], evRows) : muted("증거 줄이 없습니다.")),
      isNum(D.evidence_more) && D.evidence_more > 0 ? muted("그 밖 " + D.evidence_more + "건") : null]), {id: "r-ev-unit"}));
    if (arr(D.runs).length) {
      out.push(card(null, chart(C().unitTimeline({runs: D.runs.map(function (r) {
        return {type: r.type, "class": r["class"], a: r.a, b: r.b, min: r.min, obs_min: r.obs_min,
          app: arr(r.apps).map(function (a) { return appName(X, a[0]); }).join(", ") || null};
      }), boundaries: arr(D.cycles).reduce(function (acc, c) {
        var s = obj(c.start);
        var e = obj(c.end);
        if (s.t) { acc.push({side: "start", code: s.code, t: s.t, estimated: !!s.estimated}); }
        if (e.t) { acc.push({side: "end", code: e.code, t: e.t, estimated: !!e.estimated}); }
        return acc;
      }, [])}, {width: env.width, id: "ch-p08e"}), "ch-p08e", st), {id: "r-ev-runs"}));
    }
    return out;
  }

  var SECTION_VIEW = {summary: viewSummary, tree: viewTree, workflow: viewWorkflow, review: viewReview, peers: viewPeers,
    graph: viewGraph, agentic: viewAgentic, subagent: viewSubagent, queue: viewQueue, hier: viewHier, evidence: viewEvidence};

  function newState(X, model, storage) {
    var saved = storeGet(storage, STORE_KEY);
    var month = saved && (saved === ALL || X.monthBy[saved]) ? saved : asOfMonth(X, model);
    return {section: "summary", arg: null, month: month, ui: {}, open: {}, tables: {}, sort: {}, limit: {}, treeOpen: {}, treeSel: null,
      treeFocus: null, gcol: {}, rels: {}, drill: {}, q: {}, qerr: {}, answered: {}, needDrop: {}, hier: null, msg: null, ev: null,
      canWriteFlag: false};
  }

  // 모델·상태·환경 → 화면 전체(순수) — 시험은 이것을 직렬화해 대조한다
  function view(model, st, env) {
    var X = idx(model);
    st.canWriteFlag = !!env.canWrite;
    var out = [];
    if (env.mode === "file") {
      var full = env.variant !== "redacted";
      out.push(h("div", {"class": "card-head"}, [h("h2", {}, ["개인 보고서"]), U().badge(full ? "전체판(로컬 전용)" : "가림판", null,
        full ? "동료 이름·문서 이름이 들어 있는 로컬 전용 파일" : "이름·문서명·근거 줄을 뺀 공유용 파일")]));
      out = out.concat(bandView(bandInfoOfModel(model)));
      if (full) { out.push(U().alertLine("info", "이 파일에는 동료 이름·문서 이름이 들어 있습니다 — 내 PC 밖으로 보내지 마세요(공유는 가림판)")); }
    }
    if (!majorOk(model)) {
      out.push(U().alertLine("warn", "이 보고서는 화면이 읽는 형식과 판이 다릅니다 — 로컬 앱에서 보고서를 다시 만들면 맞춰집니다."));
    }
    out = out.concat(warningsView(model, env));
    if (st.msg) { out.push(U().alertLine(st.msg.kind || "info", st.msg.text)); }
    out.push(sectionNav(st));
    if (env.mode === "app" && env.canWrite) {
      out.push(h("div", {"class": "table-tools"}, [btn("내보내기", "r-export", "", {kind: "ghost", icon: "download"})]));
    }
    if (MONTH_SECTIONS[st.section]) {
      out.push(monthNav(X, st));
      out.push(periodNote(X, st));
    }
    var body;
    try {                                             // 모델 형이 예상과 달라도 이 절만 멈추고 다른 절은 본다(R §11)
      body = arr((SECTION_VIEW[st.section] || viewSummary)(model, X, st, env));
    } catch (e) {
      body = [card(null, U().alertLine("bad", "이 절을 그리지 못했습니다(보고서 자료의 형식이 예상과 다릅니다) — 다른 절은 볼 수 있고, " +
        "보고서를 다시 만들면 맞춰집니다."), {id: "r-section-err"})];
    }
    return out.concat(body);
  }

  // ───────────────────────── 19. 제어기 ─────────────────────────
  // opts: {model, mode:'app'|'file', variant, storage, doc, win, drill:{unit(id), day(d)} → Promise<자료|null>,
  //        actions: 로컬 앱 쓰기(answer·correction·proposal·codename·rule·needDrop·mergeQuestion·exportReport·hierState) — 파일 모드는 없음,
  //        trimmed: [뺀 것], width}
  function create(el, opts) {
    opts = opts || {};
    var doc = opts.doc || el.ownerDocument || root.document;
    var win = opts.win || (doc && doc.defaultView) || null;
    var model = opts.model || {};
    var X = idx(model);
    var actions = opts.actions || null;
    var env = {mode: opts.mode === "app" ? "app" : "file", variant: opts.variant || model.variant || "full",
      canWrite: !!(actions && opts.mode === "app"), width: 720, trimmed: arr(opts.trimmed)};
    var st = newState(X, model, opts.storage);
    var alive = true;

    function widthOf() {
      var w = num(el.clientWidth);
      return w > 0 ? Math.max(320, Math.min(1240, w - 44)) : (opts.width || 1100);
    }

    function render() {
      if (!alive) { return; }
      env.width = widthOf();
      var vals = collectValues(el);
      var fk = focusKeyOf(doc && doc.activeElement, el);
      U().render(view(model, st, env), el);
      restoreValues(el, vals, st.clear);
      st.clear = null;
      restoreFocus(el, fk);
    }

    function setHash(route) {
      var hsh = "#report/" + route;
      if (win && win.location && win.location.hash !== hsh) {
        win.location.hash = hsh;                     // 라우터(hashchange)가 go 를 부른다
      } else {
        var p = parseRoute(hsh);
        go(p.section, p.arg);
      }
    }

    function ensureDrill(kind, key) {
      var ck = kind + ":" + key;
      if (st.drill[ck] && st.drill[ck].state !== "err") { return; }
      var src = opts.drill && typeof opts.drill[kind] === "function" ? opts.drill[kind] : null;
      if (!src) { st.drill[ck] = {state: "none"}; return; }
      st.drill[ck] = {state: "loading"};
      var p;
      try {
        p = Promise.resolve(src(key));
      } catch (e) {
        p = Promise.reject(e);
      }
      p.then(function (res) {
        st.drill[ck] = res === null || res === undefined ? {state: "missing"} : {state: "ok", data: res};
        if (st.section === "evidence" && st.ev === key) { render(); }
      }, function (e) {
        st.drill[ck] = {state: "err", text: e && e.text_ko ? e.text_ko : null};
        if (st.section === "evidence" && st.ev === key) { render(); }
      });
    }

    function loadHier(force) {
      if (!actions || typeof actions.hierState !== "function") { return; }
      if (st.hier && st.hier.state !== "err" && !force) { return; }
      st.hier = {state: "loading"};
      Promise.resolve(actions.hierState()).then(function (r) {
        st.hier = r && r.ok !== false ? {state: "ok", data: r && r.data !== undefined ? r.data : r} : {state: "err"};
        if (st.section === "hier") { render(); }
      }, function () {
        st.hier = {state: "err"};
        if (st.section === "hier") { render(); }
      });
    }

    function treeKeyOf(arg) {
      if (!arg) { return null; }
      if (/^[dprubx]:/.test(arg)) { return arg; }
      if (/^u_/.test(arg)) { return "u:" + arg; }
      return null;
    }

    function openAncestors(key) {
      var T = treeData(model, X, st.month);
      var n = T.byKey[key];
      while (n && n.parent) { st.treeOpen[n.parent] = true; n = T.byKey[n.parent]; }
      return !!T.byKey[key];
    }

    function go(section, arg) {
      if (!SECTION_VIEW[section]) { section = "summary"; }
      st.section = section;
      st.arg = arg || null;
      st.msg = null;
      if (section === "tree" && arg) {
        var key = treeKeyOf(arg);
        if (key && openAncestors(key)) { st.treeSel = key; st.treeFocus = key; }
      } else if (section === "workflow" && arg) {
        st.ui.wfRole = arg;
      } else if (section === "review" && arg) {
        st.ui.review = /W\d\d$/.test(arg) ? "week" : "month";
        st.open["rv:" + arg] = true;
      } else if (section === "graph" && arg) {
        if (/^u_/.test(arg)) { st.ui.gunit = arg; } else { st.ui.center = arg; }
      } else if (section === "evidence") {
        st.ev = arg || null;
        if (/^u_[0-9a-f]+$/.test(str(arg))) { ensureDrill("unit", arg); } else if (/^\d{4}-\d{2}-\d{2}$/.test(str(arg))) { ensureDrill("day", arg); }
      } else if (section === "hier") {
        loadHier(false);
      }
      render();
    }

    function result(r, okText, after) {
      Promise.resolve(r).then(function (res) {
        if (res && res.ok === false) {
          st.msg = {kind: res.code === "busy" ? "warn" : "bad", text: res.error || "요청을 처리하지 못했습니다 — 다시 누르면 이어서 합니다"};
        } else {
          st.msg = {kind: "info", text: typeof okText === "function" ? okText(res) : okText};
          if (after) { after(res); }
        }
        render();
      }, function () {
        st.msg = {kind: "bad", text: "화면 서버에 닿지 못했습니다 — 화면을 다시 열면 이어서 합니다"};
        render();
      });
    }

    function getVal(id) {
      var n = doc && doc.getElementById(id);
      return n ? n.value : "";
    }

    function chartIdOf(node) {
      var f = closestAttr(node, "data-chart", el);
      return f ? f.getAttribute("data-chart") : null;
    }

    function formDrawer(title, fields, submitLabel, onSubmit) {
      var U0 = U();
      var body = h("div", {}, fields.concat([h("div", {"class": "table-tools"}, [btn(submitLabel, "r-form-ok", "", {kind: "primary"}),
        btn("취소", "drawer-close", "", {kind: "ghost"})])]));
      U0.openDrawer(body, {doc: doc, title: title, handlers: {"r-form-ok": function () { onSubmit(); }}});
    }

    function exportDialog() {
      var d = obj(opts.exportDefaults);
      var fm = arr(d.formats).length ? arr(d.formats) : ["html", "csv", "json"];
      var vr = arr(d.variants).length ? arr(d.variants) : ["full", "redacted"];
      formDrawer("보고서 내보내기", [
        h("fieldset", {}, [h("legend", {}, ["형식"]), checkbox("r-ex-html", "자기완결 HTML", fm.indexOf("html") >= 0),
          checkbox("r-ex-csv", "CSV(엑셀)", fm.indexOf("csv") >= 0), checkbox("r-ex-json", "JSON", fm.indexOf("json") >= 0)]),
        h("fieldset", {}, [h("legend", {}, ["변형"]), checkbox("r-ex-full", "전체판(로컬 전용)", vr.indexOf("full") >= 0),
          checkbox("r-ex-redacted", "가림판(공유용)", vr.indexOf("redacted") >= 0)]),
        U().alertLine("info", "전체판에는 동료 이름·문서 이름이 들어 있습니다 — 내 PC 밖으로 보내지 마세요(공유는 가림판)")],
      "내보내기 시작", function () {
        function on(id) { var n = doc.getElementById(id); return !!(n && n.checked); }
        var formats = ["html", "csv", "json"].filter(function (f) { return on("r-ex-" + f); });
        var variants = ["full", "redacted"].filter(function (v) { return on("r-ex-" + v); });
        if (!formats.length || !variants.length) {
          st.msg = {kind: "warn", text: "형식과 변형을 하나 이상 고르세요"};
          U().closeDrawer();
          render();
          return;
        }
        U().closeDrawer();
        result(actions.exportReport({run_id: obj(model.run).run_id, formats: formats, variants: variants}),
          "내보내기를 시작했습니다 — 끝나면 만든 파일 목록을 보여 드립니다");
      });
    }

    function fixDialog(unitId) {
      var x = X.units[unitId] || {};
      var hs = st.hier && st.hier.data ? obj(st.hier.data) : {};
      var projOpts = [["", "그대로"]].concat((arr(hs.projects).length ? arr(hs.projects) : arr(model.projects)).map(function (p) {
        return [p.key, projLabel(X, p.key)];
      })).concat([["__new__", "새 과제 만들기"], ["__not_work__", "업무 아님"]]);
      var vb = obj(hs.vocab);
      function vopts(list) { return [["", "그대로"]].concat(arr(list).map(function (v) { return [v.code, v.name || v.code]; })); }
      formDrawer("분류 고치기 — " + (x.title || unitId), [
        field("r-fix-project", "과제", select("r-fix-project", projOpts, "")),
        field("r-fix-field", "분야", select("r-fix-field", vopts(vb.fields), "")),
        field("r-fix-func", "기능", select("r-fix-func", vopts(vb.functions), "")),
        field("r-fix-wtype", "업무 유형", select("r-fix-wtype", arr(vb.activity_types).length ? vopts(vb.activity_types) :
          [["", "그대로"]].concat(WTYPES.map(function (w) { return [w, w]; })), "")),
        field("r-fix-title", "제목(25자 이하)", input("r-fix-title", "text", null, {maxlength: "25"})),
        field("r-fix-scope", "범위", select("r-fix-scope", [["similar", "비슷한 업무도"], ["this", "이 업무만"]], "similar"))],
      "저장", function () {
        var set = {};
        var pj = getVal("r-fix-project");
        if (pj) { set.project = pj; }
        ["field", "func", "wtype"].forEach(function (k) { var v = getVal("r-fix-" + k); if (v) { set[k] = v; } });
        var t = str(getVal("r-fix-title")).trim();
        if (t) { set.title = Array.from(t).slice(0, 25).join(""); }
        var scope = getVal("r-fix-scope") === "this" ? "this" : "similar";   // 서랍을 닫기 전에 읽는다
        U().closeDrawer();
        if (!Object.keys(set).length) { st.msg = {kind: "info", text: "바꾼 값이 없어 저장하지 않았습니다"}; render(); return; }
        result(actions.correction({unit_id: unitId, set: set, scope: scope}),
          function (res) { return obj(res).reanalyze_job || obj(obj(res).data).reanalyze_job ? "고친 분류를 저장했습니다 — 빠른 재분석을 시작했습니다" : "고친 분류를 저장했습니다 — 다시 분석하면 반영됩니다"; },
          function () { st.hier = null; });
      });
    }

    var handlers = {
      "r-month": function (n, ref) {
        if (ref !== ALL && !X.monthBy[ref]) { return; }
        st.month = ref;
        storeSet(opts.storage, STORE_KEY, ref);
        render();
      },
      "r-goto": function (n, ref) { setHash(ref); },
      "r-ui": function (n, ref) {
        var i = str(ref).indexOf("=");
        if (i > 0) { st.ui[ref.slice(0, i)] = ref.slice(i + 1); }
        render();
      },
      "r-ui-tree": function (n, ref) { st.ui.tree = ref; render(); },
      "r-ui-gview": function (n, ref) { st.ui.gview = ref; render(); },
      "r-ui-review": function (n, ref) { st.ui.review = ref; render(); },
      "r-ui-peers": function (n, ref) { st.ui.peers = ref; render(); },
      "r-ui-topn": function (n, ref) { st.ui.topn = ref; render(); },
      "r-open": function (n, ref) {
        var cur = st.open[ref];
        if (cur === undefined) { cur = n.getAttribute("aria-expanded") === "true"; }
        st.open[ref] = !cur;
        render();
      },
      "r-rel": function (n, ref) { st.rels[ref] = !st.rels[ref]; render(); },
      "r-tree": function (n, ref) { st.treeSel = ref; st.treeFocus = ref; render(); },
      "r-exp": function (n, ref) {
        var T = treeData(model, X, st.month);
        var node = T.byKey[ref];
        if (node) { st.treeOpen[ref] = !isOpen(st, node); st.treeFocus = ref; }
        render();
      },
      "r-why": function (n, ref) {
        st.ui.why = st.ui.why === ref ? "" : ref;
        if (st.section === "tree") { st.treeSel = "u:" + ref; } else { setHash("tree/u:" + ref); return; }
        render();
      },
      "r-fix": function (n, ref) { if (env.canWrite) { fixDialog(ref); } },
      "chart-table": function (n, ref) { st.tables[ref] = !st.tables[ref]; render(); },
      "table-sort": function (n, ref) {
        var id = chartIdOf(n);
        if (!id) { return; }
        var prev = st.sort[id];
        st.sort[id] = {col: +ref, desc: prev && prev.col === +ref ? !prev.desc : false};
        render();
      },
      "table-unsort": function (n) { var id = chartIdOf(n); if (id) { delete st.sort[id]; render(); } },
      "table-more": function (n) { var id = chartIdOf(n); if (id) { st.limit[id] = (st.limit[id] || 500) + 500; render(); } },
      "toggle-row": function (n, ref) { st.gcol[ref] = !st.gcol[ref]; render(); },
      "drill-month": function (n, ref) { setHash("evidence/" + ref); },
      "drill-day": function (n, ref) { setHash("evidence/" + ref); },
      "open-domain": function (n, ref) { setHash("tree/d:" + ref); },
      "open-unit": function (n, ref) {
        if (st.section === "graph") { st.ui.gunit = ref; render(); return; }
        if (st.section === "tree") { var k = "u:" + ref; openAncestors(k); st.treeSel = k; st.treeFocus = k; render(); return; }
        setHash(st.section === "evidence" ? "evidence/" + ref : "tree/u:" + ref);
      },
      "pm-step": function (n, ref) { st.ui.step = st.ui.step === str(ref) ? "" : str(ref); render(); },
      "open-peer": function (n, ref) { st.open["peer:" + ref] = !st.open["peer:" + ref]; render(); },
      "graph-node": function (n, ref) { st.ui.focus = st.ui.focus === ref ? "" : ref; render(); },
      "r-qpick": function (n, ref) {
        var i = str(ref).indexOf("|");
        st.q[ref.slice(0, i)] = ref.slice(i + 1);
        st.qerr[ref.slice(0, i)] = null;
        render();
      },
      "r-qsend": function (n, qid) {
        if (!env.canWrite) { return; }
        var item = arr(model.queue).filter(function (q) { return q.qid === qid; })[0];
        if (!item) { return; }
        var r = readAnswer(X, item, st.q[qid], getVal);
        if (r.errs) {
          st.qerr[qid] = r.errs;
          render();
          var first = ["d", "t", "a", "b", "hours", "unit", "project", "wtype"].filter(function (k) { return r.errs[k]; })[0];
          var fe = first && doc.getElementById("q-" + qid + "-" + first);
          if (fe && fe.focus) { fe.focus(); }
          return;
        }
        st.qerr[qid] = null;
        var code = str(item.code);
        var call;
        if (code === "H03") {
          call = actions.proposal({proposal_id: item.target, action: r.answer.choice, project: r.answer.project || null, from_queue: qid});
        } else if (/^H0[1256]$/.test(code)) {
          var set = {};
          if (r.answer.project) { set.project = r.answer.project; }
          if (r.answer.wtype) { set.wtype = r.answer.wtype; }
          if (r.answer.choice === "not_work") { set.project = "__not_work__"; }
          if (r.answer.choice === "rule" || r.answer.choice === "ai") { set.pick = r.answer.choice; }
          call = actions.correction({unit_id: item.target, set: set, scope: "this", from_queue: qid});
        } else {
          call = actions.answer(qid, r.answer);
        }
        result(call, function (res) {
          var job = obj(res).reanalyze_job || obj(obj(res).data).reanalyze_job;
          st.answered[qid] = job ? "응답함 — 빠른 재분석을 시작했습니다" : "응답함 — 다시 분석하면 반영됩니다";
          return st.answered[qid];
        });
      },
      "r-need": function (n, id) {
        if (!env.canWrite) { return; }
        var nd = arr(obj(model.agentic).needs).filter(function (x) { return x.need_id === id; })[0] || {};
        var cur = st.needDrop[id] !== undefined ? st.needDrop[id] : !!nd.dropped;
        result(actions.needDrop(id, !cur), cur ? "이 니즈를 다시 팀에 올립니다" : "이 니즈는 팀 묶음에서 뺍니다", function () { st.needDrop[id] = !cur; });
      },
      "r-merge": function (n, ref) {
        if (!env.canWrite) { return; }
        var p = str(ref).split("|");
        result(actions.mergeQuestion(p[0], p[1]), "합치기 질문을 만들었습니다 — 응답은 다음 분석에 반영됩니다");
      },
      "r-export": function () { if (env.canWrite) { exportDialog(); } },
      "r-hier-reload": function () { loadHier(true); render(); },
      "r-codename": function (n, ref) {
        if (!env.canWrite) { return; }
        var p = str(ref).split("|");
        result(actions.codename({cand: p[0] || null, action: p[1]}), function (res) {
          return obj(res).text_ko || obj(obj(res).data).text_ko || "코드네임 검토를 저장했습니다";
        }, function () { st.hier = null; loadHier(true); });
      },
      "r-rule": function (n, ref) {
        if (!env.canWrite) { return; }
        var p = str(ref).split("|");
        result(actions.rule({rule_id: p[0], action: p[1]}), function (res) {
          var text = obj(res).text_ko || obj(obj(res).data).text_ko;
          return p[1] === "copy_team" ? (text ? "팀장에게 전할 문구: " + text : "팀 규칙 제안 문구를 만들었습니다") : "학습 규칙 상태를 바꿨습니다";
        }, function () { st.hier = null; loadHier(true); });
      },
      "r-prop": function (n, ref) {
        if (!env.canWrite) { return; }
        var p = str(ref).split("|");
        var id = p[0];
        var action = p[1];
        var hs = st.hier && st.hier.data ? obj(st.hier.data) : {};
        function send(extra) {
          var body = {proposal_id: id, action: action};
          Object.keys(extra || {}).forEach(function (k) { body[k] = extra[k]; });
          result(actions.proposal(body), "제안 처리를 저장했습니다", function () { st.hier = null; loadHier(true); });
        }
        if (action === "accept") {
          var guess = str(obj(arr(hs.proposals).filter(function (pp) { return pp.proposal_id === id; })[0]).domain_guess);
          formDrawer("내 과제로 받기", [field("r-pr-domain", "업무 영역", select("r-pr-domain", X.domainList.filter(function (d) { return d.code !== "UNC"; })
            .map(function (d) { return [d.code, d.name || d.code]; }), guess)), field("r-pr-words", "알아볼 낱말(쉼표로 나눔)", input("r-pr-words", "text", null))],
          "받기", function () {
            var words = str(getVal("r-pr-words")).split(",").map(function (w) { return w.trim(); }).filter(Boolean);
            var dom = str(getVal("r-pr-domain"));                       // 서랍을 닫기 전에 읽는다(닫으면 칸이 사라진다)
            U().closeDrawer();
            send({domain: dom, keywords: words});
          });
        } else if (action === "map") {
          formDrawer("기존 과제와 같음", [field("r-pr-project", "과제", select("r-pr-project", (arr(hs.projects).length ? arr(hs.projects) : arr(model.projects))
            .map(function (pp) { return [pp.key, projLabel(X, pp.key)]; }), ""))], "연결", function () {
            var v = getVal("r-pr-project");
            U().closeDrawer();
            send({project: v});
          });
        } else if (action === "rename") {
          formDrawer("이름 바꾸기", [field("r-pr-name", "새 이름", input("r-pr-name", "text", null, {maxlength: "40"}))], "바꾸기", function () {
            var v = str(getVal("r-pr-name")).trim();
            U().closeDrawer();
            if (v) { send({name: v}); }
          });
        } else if (action === "merge") {
          formDrawer("다른 제안과 합치기", [field("r-pr-into", "합칠 제안", select("r-pr-into", arr(hs.proposals).filter(function (pp) {
            return pp.proposal_id !== id;
          }).map(function (pp) { return [pp.proposal_id, pp.name || pp.proposal_id]; }), ""))], "합치기", function () {
            var v = getVal("r-pr-into");
            U().closeDrawer();
            if (v) { send({into: v}); }
          });
        } else {
          send({});
        }
      }
    };

    // 트리 표 키보드(WAI-ARIA treegrid — KB-2): ↑↓ 이동, → 펼침/첫 자식, ← 접기/부모, Enter 패널(위임이 처리)
    function onKey(ev) {
      var t = ev.target;
      var key = t && t.getAttribute ? t.getAttribute("data-tree") : null;
      if (!key) { return; }
      var rows = [];
      walk(el, function (n) { if (n.getAttribute && n.getAttribute("data-tree")) { rows.push(n); } });
      var i = rows.indexOf(t);
      var exp = t.getAttribute("aria-expanded");
      var target = null;
      if (ev.key === "ArrowDown") { target = rows[i + 1]; } else if (ev.key === "ArrowUp") { target = rows[i - 1]; } else if (ev.key === "Home") {
        target = rows[0];
      } else if (ev.key === "End") { target = rows[rows.length - 1]; } else if (ev.key === "ArrowRight") {
        if (exp === "false") {
          st.treeOpen[key] = true;
          st.treeFocus = key;
          ev.preventDefault();
          render();
          return;
        }
        if (exp === "true") { target = rows[i + 1]; }
      } else if (ev.key === "ArrowLeft") {
        if (exp === "true") {
          st.treeOpen[key] = false;
          st.treeFocus = key;
          ev.preventDefault();
          render();
          return;
        }
        var par = t.getAttribute("data-parent");
        target = rows.filter(function (r) { return r.getAttribute("data-tree") === par; })[0];
      } else {
        return;
      }
      ev.preventDefault();
      if (target) {
        rows.forEach(function (r) { r.setAttribute("tabindex", r === target ? "0" : "-1"); });
        st.treeFocus = target.getAttribute("data-tree");
        target.focus();
      }
    }

    var off = U().delegate(el, handlers);
    el.addEventListener("keydown", onKey);

    return {
      go: go,
      render: render,
      state: st,
      env: env,
      model: model,
      handlers: handlers,
      destroy: function () {
        alive = false;
        off();
        el.removeEventListener("keydown", onKey);
      }
    };
  }

  // '#report/<절>[/<인자>]' → {section, arg}
  function parseRoute(hash) {
    var s = str(hash).replace(/^#/, "");
    var m = /^report(?:\/([a-z]+))?(?:\/(.+))?$/.exec(s);
    if (!m) { return {section: null, arg: null}; }
    var arg = null;
    if (m[2]) {
      try {
        arg = decodeURIComponent(m[2]);
      } catch (e) {
        arg = m[2];
      }
    }
    return {section: m[1] || "summary", arg: arg};
  }

  // ───────────────────────── 20. 자기완결 HTML 부트(§9.4) ─────────────────────────
  function boot(doc, o) {
    o = o || {};
    var U0 = U();
    var model = U0.readIsland("lm27-data", doc);
    var host = doc.getElementById("app") || doc.body;
    U0.ensureDefs(doc, C());
    if (!model || typeof model !== "object") {
      U0.render(card("개인 보고서", U0.alertLine("bad", "이 파일의 보고서 자료를 읽지 못했습니다 — 로컬 앱에서 다시 내보내면 맞춰집니다.")), host);
      return null;
    }
    var island = U0.readIsland("lm27-drill", doc);
    var drill = island && typeof island === "object" ? {
      unit: function (id) { return Promise.resolve(obj(island.units)[id] || null); },
      day: function (d) { return Promise.resolve(obj(island.days)[d] || null); }
    } : null;
    var win = o.win || doc.defaultView || null;
    var storage = o.storage;
    if (storage === undefined) {
      try {
        storage = win ? win.localStorage : null;
      } catch (e) {
        storage = null;
      }
    }
    var variant = model.variant || (doc.body && doc.body.getAttribute && doc.body.getAttribute("data-variant")) || "full";
    var ctl = create(host, {model: model, mode: "file", variant: variant, storage: storage, doc: doc, win: win, drill: drill,
      trimmed: arr(obj(island).trimmed).concat(arr(obj(model.flags).trimmed))});
    function route() {
      var p = parseRoute(win && win.location ? win.location.hash : "");
      ctl.go(p.section || "summary", p.arg);
    }
    if (win && win.addEventListener) { win.addEventListener("hashchange", route); }
    route();
    return ctl;
  }

  function autoBoot(doc) {
    if (!doc || !doc.getElementById) { return; }
    function run() { if (doc.getElementById("lm27-data")) { boot(doc); } }
    if (doc.readyState === "loading" && doc.addEventListener) { doc.addEventListener("DOMContentLoaded", run); } else { run(); }
  }

  return {
    // 화면
    create: create, boot: boot, autoBoot: autoBoot, view: view, parseRoute: parseRoute, readAnswer: readAnswer,
    SECTIONS: SECTIONS, QA: QA, Q_NAME: Q_NAME, ALL: ALL, STORE_KEY: STORE_KEY, majorOk: majorOk,
    // 머리 띠(app.js 도 쓴다)
    bandParts: bandParts, bandView: bandView, periodSourceText: periodSourceText,
    // 순수 계산(시험)
    idx: idx, treeData: treeData, roleSentences: roleSentences, qualityText: qualityText, summarySentences: summarySentences,
    graphSpec: graphSpec, josa: josa,
    // kit(app.js 가 쓴다)
    kit: {h: h, card: card, btn: btn, link: link, table: table, field: field, input: input, checkbox: checkbox, select: select,
      textarea: textarea, toggles: toggles, chips: chips, dl: dl, para: para, muted: muted, emptyP: emptyP, errLine: errLine,
      oiBar: oiBar, shareBar: shareBar, domChip: domChip, levelBar: levelBar, mdhm: mdhm, arr: arr, obj: obj, num: num, str: str,
      isNum: isNum, cmp: cmp, uniq: uniq, walk: walk, closestAttr: closestAttr, collectValues: collectValues,
      restoreValues: restoreValues, focusKeyOf: focusKeyOf, restoreFocus: restoreFocus, storeGet: storeGet, storeSet: storeSet}
  };
}));
