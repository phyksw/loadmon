/*
 * LM27 차트 렌더러 한 벌 — 차트 = 순수 함수(입력 명세 → 가상 노드). DOM·전역 상태·시계에 손대지 않는다.
 * 근거: REPORTS §8.3(공통 규칙) · §8.4(카탈로그 CH-*) · §8.1.4(무늬) · §8.6.1 · 부록 A(CHARTS 이름 정본) · 계약 X-281.
 * 각 차트: (spec, opt{width, mode, variant, view, id}) → {svg, table:{cols, rows}, legend:[{label, swatch}], caption:{title, summary, notes}}
 * 숫자 글자는 lm27ui.js 의 표시 함수(fmtH1·fmtRatio …)로만 만든다(§3.1). 좌표는 round1(소수 1자리).
 * 색: 토큰은 lm27.css 의 클래스(f-*·s-*), 업무 영역 색만 모델 값(domains[].color, ^#[0-9a-f]{6}$ 검사 뒤) — 16진 리터럴 0(G-R7).
 * 고전 스크립트(import/export 없음). 브라우저 = 전역 LM27Charts(lm27ui.js 는 호출 때 찾는다), node = module.exports.
 */
(function (root, factory) {
  "use strict";
  var api = factory(root);
  if (typeof module === "object" && module && module.exports) {
    module.exports = api;
  } else {
    root.LM27Charts = api;
  }
}(typeof self !== "undefined" ? self : this, function (root) {
  "use strict";

  var UIMOD = null;

  // 표시 함수 원천(lm27ui.js) — 불러오는 순서와 무관하게 호출 때 찾는다
  function ui() {
    if (UIMOD) { return UIMOD; }
    if (typeof module === "object" && module && module.exports && typeof require === "function") {
      UIMOD = require("./lm27ui.js");
    } else {
      UIMOD = root.LM27UI;
    }
    if (!UIMOD) { throw new Error("lm27ui.js 가 필요합니다"); }
    return UIMOD;
  }

  // ───────────────────────── 가상 노드 ─────────────────────────
  function flat(list, out) {
    for (var i = 0; i < list.length; i++) {
      var c = list[i];
      if (c === null || c === undefined || c === false) { continue; }
      if (Array.isArray(c)) { flat(c, out); } else { out.push(typeof c === "number" ? String(c) : c); }
    }
    return out;
  }

  function h(tag, attrs, children) {
    return {t: tag, a: attrs || {}, c: flat(children || [], [])};
  }

  function esc(s) {
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  // 시험용 직렬화(속성은 이름순, 글자·속성 값의 & < > " 이스케이프) — 같은 명세면 같은 문자열(RPT-25)
  function toString(v) {
    if (v === null || v === undefined || v === false) { return ""; }
    if (typeof v === "string" || typeof v === "number") { return esc(v); }
    var a = v.a || {};
    var s = "<" + v.t;
    Object.keys(a).sort().forEach(function (k) {
      var x = a[k];
      if (x === null || x === undefined || x === false) { return; }
      s += " " + k + (x === true ? "" : "=\"" + esc(x) + "\"");
    });
    var c = v.c || [];
    if (!c.length) { return s + "/>"; }
    return s + ">" + c.map(toString).join("") + "<" + "/" + v.t + ">";
  }

  function round1(x) {
    var r = Math.round(x * 10) / 10;
    return r === 0 ? 0 : r;
  }

  function f1(x) { return String(round1(x)); }

  // ───────────────────────── 날짜(순수 정수 산술 — Date·시계 미사용) ─────────────────────────
  function daysFromCivil(y, m, d) {
    y -= m <= 2 ? 1 : 0;
    var era = Math.floor(y / 400);
    var yoe = y - era * 400;
    var doy = Math.floor((153 * (m + (m > 2 ? -3 : 9)) + 2) / 5) + d - 1;
    var doe = yoe * 365 + Math.floor(yoe / 4) - Math.floor(yoe / 100) + doy;
    return era * 146097 + doe - 719468;
  }

  function civilFromDays(z) {
    z += 719468;
    var era = Math.floor(z / 146097);
    var doe = z - era * 146097;
    var yoe = Math.floor((doe - Math.floor(doe / 1460) + Math.floor(doe / 36524) - Math.floor(doe / 146096)) / 365);
    var doy = doe - (365 * yoe + Math.floor(yoe / 4) - Math.floor(yoe / 100));
    var mp = Math.floor((5 * doy + 2) / 153);
    var d = doy - Math.floor((153 * mp + 2) / 5) + 1;
    var m = mp + (mp < 10 ? 3 : -9);
    return [yoe + era * 400 + (m <= 2 ? 1 : 0), m, d];
  }

  function pad2(n) { return (n < 10 ? "0" : "") + n; }

  function dayNum(s) {
    if (typeof s === "number") { return s; }
    var m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(s));
    if (!m) { return NaN; }
    return daysFromCivil(+m[1], +m[2], +m[3]);
  }

  function dateOf(n) { var c = civilFromDays(n); return c[0] + "-" + pad2(c[1]) + "-" + pad2(c[2]); }

  function isoWd(n) { return (((n % 7) + 7 + 3) % 7) + 1; }      // 1 = 월 … 7 = 일 (1970-01-01 = 목)

  function isWeekend(n) { return isoWd(n) >= 6; }

  var WD_NAME = ["", "월", "화", "수", "목", "금", "토", "일"];

  function wdName(n) { return WD_NAME[isoWd(n)]; }

  function isoWeek(n) {
    var th = n - isoWd(n) + 4;
    var y = civilFromDays(th)[0];
    return y + "-W" + pad2(Math.floor((th - daysFromCivil(y, 1, 1)) / 7) + 1);
  }

  function weekStart(key) {
    var m = /^(\d{4})-W(\d{2})$/.exec(String(key));
    if (!m) { return NaN; }
    var j4 = daysFromCivil(+m[1], 1, 4);
    return j4 - (isoWd(j4) - 1) + (+m[2] - 1) * 7;
  }

  function monthStart(mk) { var m = /^(\d{4})-(\d{2})/.exec(String(mk)); return daysFromCivil(+m[1], +m[2], 1); }

  function monthEnd(mk) {
    var m = /^(\d{4})-(\d{2})/.exec(String(mk));
    var y = +m[1];
    var mo = +m[2];
    return (mo === 12 ? daysFromCivil(y + 1, 1, 1) : daysFromCivil(y, mo + 1, 1)) - 1;
  }

  function monthKey(n) { return dateOf(n).slice(0, 7); }

  function mmdd(n) { return dateOf(n).slice(5); }

  var EPOCH = daysFromCivil(2020, 1, 1);                         // 시간 코어 로컬 분 원점(계약 §9.4 · X-174)

  // 로컬 분(2020-01-01 00:00 기준) — 정수 · 'YYYY-MM-DD HH:MM' · 'YYYY-MM-DDTHH:MM' · 'HH:MM'(dayN 의 날) · 날짜
  function toMin(v, dayN) {
    if (typeof v === "number") { return v; }
    var s = String(v);
    var m = /^(\d{4}-\d{2}-\d{2})[T ](\d{2}):(\d{2})/.exec(s);
    if (m) { return (dayNum(m[1]) - EPOCH) * 1440 + (+m[2]) * 60 + (+m[3]); }
    m = /^(\d{2}):(\d{2})$/.exec(s);
    if (m) { return ((dayN === undefined ? EPOCH : dayN) - EPOCH) * 1440 + (+m[1]) * 60 + (+m[2]); }
    if (/^\d{4}-\d{2}-\d{2}$/.test(s)) { return (dayNum(s) - EPOCH) * 1440; }
    return NaN;
  }

  function minDay(t) { return EPOCH + Math.floor(t / 1440); }

  function hhmm(t) {
    var x = ((t % 1440) + 1440) % 1440;
    return pad2(Math.floor(x / 60)) + ":" + pad2(x % 60);
  }

  // ───────────────────────── 공용 산식 ─────────────────────────
  var DENSITY_STEPS = [120, 360, 720, 1200];                       // TEAM §4.6 고정 5단계 — 119→1·120→2·1199→4·1200→5

  function densityLevel(m) {
    if (!(m > 0)) { return 0; }
    var k = 1;
    for (var i = 0; i < DENSITY_STEPS.length; i++) { if (m >= DENSITY_STEPS[i]) { k++; } }
    return k;
  }

  function cmpStr(a, b) { return a < b ? -1 : (a > b ? 1 : 0); }

  // 줄 배정(시제품 lanes()): (시작, 끝, id) 순으로 놓으며 마지막 끝 < 시작 인 첫 줄, 없으면 새 줄
  function lanes(bars) {
    var list = bars.map(function (b) { return {id: b.id, f: dayNum(b.from), t: dayNum(b.to)}; });
    list.sort(function (a, b) { return (a.f - b.f) || (a.t - b.t) || cmpStr(a.id, b.id); });
    var last = [];
    var out = {};
    list.forEach(function (b) {
      for (var i = 0; i < last.length; i++) {
        if (last[i] < b.f) { last[i] = b.t; out[b.id] = i; return; }
      }
      last.push(b.t);
      out[b.id] = last.length - 1;
    });
    return out;
  }

  // 눈금 '보기 좋은 값'(1·2·2.5·5 × 10ⁿ), 4~6개
  function niceStep(raw) {
    if (!(raw > 0)) { return 1; }
    var p = Math.pow(10, Math.floor(Math.log(raw) / Math.LN10));
    var ms = [1, 2, 2.5, 5, 10];
    for (var i = 0; i < ms.length; i++) { if (ms[i] * p >= raw - 1e-12) { return ms[i] * p; } }
    return 10 * p;
  }

  function tickList(top, n) {
    var step = niceStep(top / (n || 5));
    var out = [];
    for (var k = 0; k * step <= top + 1e-9; k++) { out.push(Math.round(k * step * 1e6) / 1e6); }
    return {step: step, list: out};
  }

  function stepDigits(step) {
    var d = 0;
    while (d < 6 && Math.abs(Math.round(step * Math.pow(10, d)) - step * Math.pow(10, d)) > 1e-9) { d++; }
    return d;
  }

  function niceTop(v, n) {
    var step = niceStep(v / (n || 5));
    var top = Math.ceil(v / step - 1e-9) * step;
    return top > 0 ? Math.round(top * 1e6) / 1e6 : step;
  }

  // 글자 폭 추정(좌표 배치용 — 한글 1em, 라틴 0.58em)
  function textW(s, fs) {
    var w = 0;
    var cs = Array.from(String(s));
    for (var i = 0; i < cs.length; i++) { w += cs[i].charCodeAt(0) < 128 ? 0.58 : 1; }
    return w * fs;
  }

  function ellipsis(s, n) {
    var cs = Array.from(String(s === null || s === undefined ? "" : s));
    return cs.length > n ? cs.slice(0, n - 1).join("") + "…" : cs.join("");
  }

  function fitText(s, maxW, fs) {
    var cs = Array.from(String(s === null || s === undefined ? "" : s));
    if (textW(s, fs) <= maxW) { return cs.join(""); }
    var out = [];
    var w = textW("…", fs);
    for (var i = 0; i < cs.length; i++) {
      var cw = textW(cs[i], fs);
      if (w + cw > maxW) { break; }
      w += cw;
      out.push(cs[i]);
    }
    return out.join("") + "…";
  }

  var DOMAIN_ORDER = ["DEV", "MP", "EXT", "COM", "AX", "UNC"];      // H §1.2 고정 순서(순환 없음)
  var TAGS = ["regular", "extended", "night", "holiday"];
  var TAG_NAME = {regular: "정규", extended: "연장", night: "야간", holiday: "휴일"};
  var COLOR_RE = /^#[0-9a-f]{6}$/;

  // 업무 영역 색 — 모델 값만, 형식 검사 뒤(아니면 중립 회색 클래스)
  function domainPaint(color) {
    return COLOR_RE.test(String(color || "")) ? {fill: color} : {"class": "f-faint"};
  }

  function domainRank(code) {
    var i = DOMAIN_ORDER.indexOf(code);
    return i < 0 ? DOMAIN_ORDER.length : i;
  }

  function sum(list, fn) {
    var s = 0;
    for (var i = 0; i < list.length; i++) { s += fn ? fn(list[i]) : list[i]; }
    return s;
  }

  function tagMin(byTag) {
    var s = 0;
    byTag = byTag || {};
    TAGS.forEach(function (t) { s += byTag[t] || 0; });
    return s;
  }

  // ───────────────────────── 그리기 조각 ─────────────────────────
  // 모서리별 반지름 사각형 경로(데이터 끝만 3px — 바닥은 직각)
  function roundRect(x, y, w, hh, c) {
    var lim = Math.min(w, hh) / 2;
    var tl = Math.min(c.tl || 0, lim);
    var tr = Math.min(c.tr || 0, lim);
    var br = Math.min(c.br || 0, lim);
    var bl = Math.min(c.bl || 0, lim);
    var d = "M" + f1(x + tl) + " " + f1(y) + "H" + f1(x + w - tr);
    if (tr) { d += "A" + f1(tr) + " " + f1(tr) + " 0 0 1 " + f1(x + w) + " " + f1(y + tr); }
    d += "V" + f1(y + hh - br);
    if (br) { d += "A" + f1(br) + " " + f1(br) + " 0 0 1 " + f1(x + w - br) + " " + f1(y + hh); }
    d += "H" + f1(x + bl);
    if (bl) { d += "A" + f1(bl) + " " + f1(bl) + " 0 0 1 " + f1(x) + " " + f1(y + hh - bl); }
    d += "V" + f1(y + tl);
    if (tl) { d += "A" + f1(tl) + " " + f1(tl) + " 0 0 1 " + f1(x + tl) + " " + f1(y); }
    return d + "Z";
  }

  function rect(x, y, w, hh, attrs) {
    var a = {x: round1(x), y: round1(y), width: round1(Math.max(0, w)), height: round1(Math.max(0, hh))};
    Object.keys(attrs || {}).forEach(function (k) { a[k] = attrs[k]; });
    return h("rect", a);
  }

  function line(x1, y1, x2, y2, attrs) {
    var a = {x1: round1(x1), y1: round1(y1), x2: round1(x2), y2: round1(y2)};
    Object.keys(attrs || {}).forEach(function (k) { a[k] = attrs[k]; });
    return h("line", a);
  }

  function text(x, y, s, cls, anchor) {
    return h("text", {x: round1(x), y: round1(y), "class": cls || "t-axis", "text-anchor": anchor || null}, [s]);
  }

  function hatch(x, y, w, hh, which) {
    return rect(x, y, w, hh, {fill: "url(#hatch-" + which + ")", "class": "hatch"});
  }

  // 누르기 영역(투명) — 마크보다 크게, 최소 24×24
  function hit(x, y, w, hh) {
    var ww = Math.max(24, w);
    var hhh = Math.max(24, hh);
    return rect(x - (ww - w) / 2, y - (hhh - hh) / 2, ww, hhh, {"class": "hit"});
  }

  // 마크 속성: 툴팁 줄(첫 줄 = 대상 이름, 'a\tb' = 이름·값 쌍) = aria-label, 누를 수 있으면 role=button
  function mark(lines, act, ref, extra) {
    var a = {"class": "mk", tabindex: "0", role: act ? "button" : "img",
      "aria-label": lines.map(function (l) { return String(l).replace("\t", " "); }).join(" · "),
      "data-tip": lines.join("\n")};
    if (act) { a["data-act"] = act; a["data-ref"] = ref === undefined || ref === null ? "" : String(ref); }
    Object.keys(extra || {}).forEach(function (k) { a[k] = extra[k]; });
    return a;
  }

  function svgRoot(w, hh, id, cap, kids, cls) {
    return h("svg", {"class": "chart" + (cls ? " " + cls : ""), viewBox: "0 0 " + f1(w) + " " + f1(hh),
      width: round1(w), height: round1(hh), role: "img", focusable: "false", "aria-labelledby": id + "-t " + id + "-d"},
    [h("title", {id: id + "-t"}, [cap.title]), h("desc", {id: id + "-d"}, [cap.summary || ""])].concat(kids));
  }

  function result(svg, cols, rows, legend, caption) {
    return {svg: svg, table: {cols: cols, rows: rows}, legend: legend || [], caption: caption};
  }

  function emptyResult(id, title, why, cols) {
    var cap = {title: title, summary: why, notes: []};
    return result(h("p", {"class": "empty"}, [why]), cols || [], [], [], cap);
  }

  // 범례 견본(14×14)
  function swRect(attrs, overlay) {
    var a = {x: 1, y: 2, width: 12, height: 10, rx: 2};
    Object.keys(attrs).forEach(function (k) { a[k] = attrs[k]; });
    return [h("rect", a), overlay ? h("rect", {x: 1, y: 2, width: 12, height: 10, rx: 2, fill: "url(#hatch-" + overlay + ")"}) : null];
  }

  function swLine(cls, dash) {
    return [h("line", {x1: 0, y1: 7, x2: 14, y2: 7, "class": cls, "stroke-width": 1.5, "stroke-dasharray": dash || null})];
  }

  // §8.1.4 무늬 정의(페이지에 한 번 — lm27ui.ensureDefs 가 마운트). 색은 lm27.css 의 hp-* 클래스
  function patternDefs() {
    return h("defs", {}, [
      h("pattern", {id: "hatch-est", patternUnits: "userSpaceOnUse", width: 5, height: 5, patternTransform: "rotate(45)"},
        [h("line", {x1: 0, y1: 0, x2: 0, y2: 5, "class": "hp-est"})]),
      h("pattern", {id: "hatch-unattr", patternUnits: "userSpaceOnUse", width: 5, height: 5, patternTransform: "rotate(135)"},
        [h("rect", {x: 0, y: 0, width: 5, height: 5, "class": "hp-unattr-bg"}),
          h("line", {x1: 0, y1: 0, x2: 0, y2: 5, "class": "hp-unattr"})]),
      h("pattern", {id: "hatch-bad", patternUnits: "userSpaceOnUse", width: 6, height: 6, patternTransform: "rotate(45)"},
        [h("line", {x1: 0, y1: 0, x2: 0, y2: 6, "class": "hp-bad"})])]);
  }

  // ───────────────────────── CH-H01 수집 커버리지 히트맵 ─────────────────────────
  var AXES = ["mail_in", "mail_out", "cal", "teams", "pc"];
  var AXIS_NAME = {mail_in: "메일 받음", mail_out: "메일 보냄", cal: "일정", teams: "팀즈", pc: "PC"};
  var COV_ORDER = ["ok", "zero_ok", "partial", "out_of_horizon", "blocked", "transport_fail", "not_attempted"];
  var COV = {ok: ["정상", "cv-ok", false], zero_ok: ["0건 확인", "cv-zero", false], partial: ["일부", "cv-partial", false],
    out_of_horizon: ["보존 기간 밖", "cv-horizon", false], blocked: ["막힘", "cv-blocked", true],
    transport_fail: ["수송 실패", "cv-transport", true], not_attempted: ["시도 안 함", "cv-none", false]};

  function covName(st) { return (COV[st] || [st])[0]; }

  function coverageHeatmap(spec, opt) {
    opt = opt || {};
    var id = opt.id || "ch-h01";
    var axes = spec.axes || AXES;
    var days = (spec.days || []).slice().sort(function (a, b) { return cmpStr(a.d, b.d); });
    var title = "수집 커버리지";
    var cols = ["날짜"].concat(axes.map(function (a) { return AXIS_NAME[a] || a; })).concat(["사유"]);
    if (!days.length) { return emptyResult(id, title, "아직 수집 기록이 없습니다.", cols); }
    var LW = 96;
    var P = 16;
    var C = 14;
    var TOP = 28;
    var w = LW + days.length * P + 8;
    var hh = TOP + axes.length * P + 4;
    var bg = [];
    var marks = [];
    var rows = [];
    var gaps = 0;
    var rt = spec.reasonText || {};
    var sn = spec.srcNames || {};
    days.forEach(function (d, j) {
      var n = dayNum(d.d);
      var x = LW + j * P;
      var off = d.hol || d.wd === false || (d.wd === undefined && isWeekend(n));
      if (off) { bg.push(rect(x - 1, TOP - 2, P, axes.length * P + 2, {"class": "f-surface-2"})); }
      if (isoWd(n) === 1) { bg.push(text(x, 11, mmdd(n), "t-axis")); }
      if (spec.today && d.d === spec.today) { bg.push(text(x + C / 2, 25, "▼", "t-axis", "middle")); }
      var row = [mmdd(n) + "(" + wdName(n) + ")"];
      var whyAll = [];
      axes.forEach(function (a, i) {
        var st = (d.s && d.s[a]) || "not_attempted";
        var cv = COV[st] || COV.not_attempted;
        var y = TOP + i * P;
        var why = (d.why && d.why[a]) || [];
        var lines = [mmdd(n) + "(" + wdName(n) + ") · " + (AXIS_NAME[a] || a) + " · " + cv[0]];
        if (why.length) {
          lines.push(why.map(function (c) { return rt[c] ? rt[c] + "(" + c + ")" : c; }).join(", "));
          whyAll = whyAll.concat(why);
        }
        var src = (d.src && d.src[a]) || [];
        if (src.length) {
          lines.push(src.map(function (p) { return (sn[p[0]] || p[0]) + ": " + covName(p[1]); }).join(" / "));
        }
        lines.push("누르면 그날 행 보기");
        if (st === "blocked" || st === "transport_fail" || st === "not_attempted" || st === "out_of_horizon") { gaps++; }
        marks.push(h("g", mark(lines, "cov-day", d.d + "|" + a), [
          rect(x - 1, y - 1, P, P, {"class": "hit"}),
          rect(x, y, C, C, {rx: 2, "class": "cv " + cv[1]}),
          cv[2] ? rect(x, y, C, C, {rx: 2, fill: "url(#hatch-bad)"}) : null]));
        row.push(cv[0]);
      });
      row.push(whyAll.filter(function (c, k) { return whyAll.indexOf(c) === k; }).join(", "));
      rows.push(row);
    });
    var labels = axes.map(function (a, i) { return text(LW - 8, TOP + i * P + 11, AXIS_NAME[a] || a, "t-label", "end"); });
    var cap = {title: title, summary: days[0].d + " ~ " + days[days.length - 1].d + " · " + days.length + "일 · 근거 없는 칸 " +
      gaps + "개(막힘·수송 실패·보존 기간 밖·시도 안 함)", notes: []};
    var legend = COV_ORDER.map(function (st) {
      return {label: COV[st][0], swatch: swRect({"class": "cv " + COV[st][1]}, COV[st][2] ? "bad" : null)};
    });
    return result(svgRoot(w, hh, id, cap, bg.concat(labels, marks)), cols, rows, legend, cap);
  }

  // ───────────────────────── CH-P02 월별 투입 ─────────────────────────
  function monthlyMM(spec, opt) {
    opt = opt || {};
    var U = ui();
    var id = opt.id || "ch-p02";
    var W = opt.width || 720;
    var title = "월별 투입";
    var cols = ["월", "정규 h", "연장 h", "야간 h", "휴일 h", "합 h", "분모 h", "MM", "로드율"];
    var ms = (spec.months || []).filter(function (m) { return m.denom_min > 0; })
      .sort(function (a, b) { return cmpStr(a.m, b.m); });
    if (!ms.length) { return emptyResult(id, title, "아직 분석 결과가 없습니다.", cols); }
    var L = 48;
    var R = 64;
    var T = 28;
    var B = 40;
    var PH = 220;
    var PW = W - L - R;
    var H = T + PH + B;
    var band = PW / ms.length;
    var bw = Math.max(4, band * 0.7);
    var fifths = 6;                                                // 0 ~ max(1.2, 최대 MM 을 0.2 단위로 올림)
    ms.forEach(function (m) { fifths = Math.max(fifths, Math.ceil(m.env_min * 5 / m.denom_min)); });
    var top = fifths / 5;
    function y(v) { return T + PH * (1 - v / top); }
    var kids = [];
    var tk = tickList(top, 5);
    var dg = stepDigits(tk.step);
    tk.list.forEach(function (v) {
      kids.push(line(L, y(v), L + PW, y(v), {"class": v === 0 ? "s-border-strong" : "s-grid", "stroke-width": 1}));
      kids.push(text(L - 6, y(v) + 4, U.fmtNum(v, dg), "t-axis", "end"));
    });
    if (top >= 1) {
      kids.push(line(L, y(1), L + PW, y(1), {"class": "s-ink-muted", "stroke-width": 1, "stroke-dasharray": "4 3"}));
      kids.push(text(L + PW + 4, y(1) + 4, "1 MM", "t-axis"));
    }
    var rows = [];
    var lastSegs = [];
    ms.forEach(function (m, j) {
      var cx = L + band * (j + 0.5);
      var x = cx - bw / 2;
      var segs = TAGS.filter(function (t) { return ((m.by_tag || {})[t] || 0) > 0; })
        .map(function (t) { return [t, m.by_tag[t]]; });
      var acc = 0;
      var parts = [hit(x, T, bw, PH)];
      segs.forEach(function (s, k) {
        var y0 = y(acc / m.denom_min);
        acc += s[1];
        var y1 = y(acc / m.denom_min);
        var isTop = k === segs.length - 1;
        var yt = isTop ? y1 : Math.min(y0, y1 + 2);                // 조각 사이 2px 바탕색 틈
        parts.push(h("path", {d: roundRect(x, yt, bw, y0 - yt, isTop ? {tl: 3, tr: 3} : {}), "class": "f-tag-" + s[0]}));
        if (j === ms.length - 1) { lastSegs.push([s[0], (y0 + y1) / 2, y0 - y1]); }
      });
      var mm = U.fmtMM(m.env_min, m.denom_min);
      var yTop = y(m.env_min / m.denom_min);
      parts.push(text(cx, yTop - 6, mm, "t-value", "middle"));
      if (m.partial) {
        parts.push(rect(x - 2, yTop - 2, bw + 4, T + PH - yTop + 2,
          {"class": "o-dash", fill: "none", "stroke-dasharray": "3 2"}));
      }
      var lines = [m.m + " · " + mm + " MM(" + U.fmtH1(m.env_min) + "h ÷ " + U.fmtRatio(m.denom_min, 60, 0) + "h)"];
      TAGS.forEach(function (t) { lines.push(TAG_NAME[t] + "\t" + U.fmtH1((m.by_tag || {})[t] || 0) + "h"); });
      if (m.avail_min > 0) { lines.push("로드\t" + U.fmtPct(m.env_min, m.avail_min) + "%"); }
      if (m.partial) { lines.push("부분월(달 중간까지)"); }
      lines.push("누르면 근거 보기");
      kids.push(h("g", mark(lines, "drill-month", m.m), parts));
      kids.push(text(cx, T + PH + 16, m.m, "t-axis", "middle"));
      if (m.partial) { kids.push(text(cx, T + PH + 30, "부분", "t-axis", "middle")); }
      var bt = m.by_tag || {};
      rows.push([m.m + (m.partial ? " (부분)" : ""), U.fmtH1(bt.regular || 0), U.fmtH1(bt.extended || 0),
        U.fmtH1(bt.night || 0), U.fmtH1(bt.holiday || 0), U.fmtH1(m.env_min), U.fmtH1(m.denom_min), mm,
        m.avail_min > 0 ? U.fmtPct(m.env_min, m.avail_min) + "%" : "—"]);
    });
    // 계열 ≤ 4: 마지막 막대 오른쪽에 직접 라벨(조각 높이 14px 이상, 1 MM 글자와 겹치지 않을 때)
    var lx = L + band * (ms.length - 0.5) + bw / 2 + 4;
    lastSegs.forEach(function (s) {
      if (s[2] >= 14 && (top < 1 || Math.abs(s[1] - y(1)) > 10)) { kids.push(text(lx, s[1] + 4, TAG_NAME[s[0]], "t-axis")); }
    });
    var last = ms[ms.length - 1];
    var cap = {title: title, summary: ms[0].m + " ~ " + last.m + " · " + ms.length + "개월 · 최근 달 " +
      U.fmtMM(last.env_min, last.denom_min) + " MM", notes: []};
    var legend = TAGS.map(function (t) { return {label: TAG_NAME[t], swatch: swRect({"class": "f-tag-" + t})}; });
    legend.push({label: "1 MM 기준", swatch: swLine("s-ink-muted", "4 3")});
    if (ms.some(function (m) { return m.partial; })) {
      legend.push({label: "부분월", swatch: swRect({"class": "o-dash", fill: "none", "stroke-dasharray": "3 2"})});
    }
    return result(svgRoot(W, H, id, cap, kids), cols, rows, legend, cap);
  }

  // ───────────────────────── CH-P03 일별 근무 ─────────────────────────
  function dailyBars(spec, opt) {
    opt = opt || {};
    var U = ui();
    var id = opt.id || "ch-p03";
    var W = opt.width || 720;
    var title = "일별 근무";
    var cols = ["날짜", "정규 h", "연장 h", "야간 h", "휴일 h", "합 h", "신뢰 높음 h", "중간 h", "낮음 h", "표식"];
    var all = spec.days || [];
    var month = spec.month || (all[0] && String(all[0].d).slice(0, 7));
    if (!month) { return emptyResult(id, title, "그 달의 근무 기록이 없습니다.", cols); }
    var s = monthStart(month);
    var e = monthEnd(month);
    var byD = {};
    all.forEach(function (d) { if (String(d.d).slice(0, 7) === month) { byD[d.d] = d; } });
    var n = e - s + 1;
    var L = 40;
    var R = 28;
    var T = 24;
    var B = 44;
    var PH = 200;
    var PW = W - L - R;
    var H = T + PH + B;
    var band = PW / n;
    var bw = Math.max(4, band * 0.7);
    var maxMin = 0;
    Object.keys(byD).forEach(function (k) { maxMin = Math.max(maxMin, tagMin(byD[k].by_tag)); });
    var topH = Math.max(10, Math.ceil(maxMin / 60));
    function y(min) { return T + PH * (1 - min / (topH * 60)); }
    var bg = [];
    var kids = [];
    var rows = [];
    var tk = tickList(topH, 5);
    tk.list.forEach(function (v) {
      bg.push(line(L, y(v * 60), L + PW, y(v * 60), {"class": v === 0 ? "s-border-strong" : "s-grid", "stroke-width": 1}));
      bg.push(text(L - 6, y(v * 60) + 4, U.fmtNum(v, stepDigits(tk.step)), "t-axis", "end"));
    });
    var lowDays = 0;
    for (var k = 0; k < n; k++) {
      var dn = s + k;
      var ds = dateOf(dn);
      var d = byD[ds];
      var cx = L + band * (k + 0.5);
      var x = cx - bw / 2;
      if (isWeekend(dn) || (d && d.hol)) { bg.push(rect(L + band * k, T, band, PH, {"class": "f-surface-2"})); }
      if (band >= 16 || isoWd(dn) === 1) {
        bg.push(text(cx, T + PH + 14, band >= 16 ? String(+ds.slice(8)) : mmdd(dn), "t-axis", "middle"));
      }
      if (!d) { continue; }
      var total = tagMin(d.by_tag);
      var conf = d.conf_min || {};
      var low = total > 0 && (conf.low || 0) * 10 >= total * 3;      // low 분 / 합 ≥ 0.3
      if (low) { lowDays++; }
      var parts = [hit(x, T, bw, PH)];
      var acc = 0;
      var segs = TAGS.filter(function (t) { return ((d.by_tag || {})[t] || 0) > 0; });
      segs.forEach(function (t, i) {
        var y0 = y(acc);
        acc += d.by_tag[t];
        var y1 = y(acc);
        var isTop = i === segs.length - 1;
        var yt = isTop ? y1 : Math.min(y0, y1 + 2);
        parts.push(h("path", {d: roundRect(x, yt, bw, y0 - yt, isTop ? {tl: 3, tr: 3} : {}), "class": "f-tag-" + t}));
      });
      if (low) {
        parts.push(hatch(x, y(total), bw, y(0) - y(total), "est"));
        parts.push(text(cx, y(total) - 4, "▽", "t-axis", "middle"));
      }
      if (d.leave >= 1 && total === 0) { parts.push(text(cx, T + PH - 6, "연차", "t-small", "middle")); }
      if (d.leave > 0 && d.leave < 1) { parts.push(text(cx, T + PH + 30, "반차", "t-small", "middle")); }
      var lines = [mmdd(dn) + "(" + wdName(dn) + ") " + U.fmtH1(total) + "h"];
      segs.forEach(function (t) { lines.push(TAG_NAME[t] + "\t" + U.fmtH1(d.by_tag[t])); });
      lines.push("신뢰 높음\t" + U.fmtH1(conf.high || 0));
      lines.push("중간\t" + U.fmtH1(conf.mid || 0));
      lines.push("낮음\t" + U.fmtH1(conf.low || 0));
      if (low) { lines.push("낮은 신뢰(낮음 30% 이상)"); }
      if (d.leave >= 1) { lines.push("연차"); } else if (d.leave > 0) { lines.push("반차"); }
      var qs = (d.flags || []).filter(function (fl) { return /^Q\d+/.test(fl); });
      if (qs.length) { lines.push("확인 질문 " + qs.join(", ")); }
      lines.push("누르면 날짜 보기");
      kids.push(h("g", mark(lines, "drill-day", ds), parts));
      var bt = d.by_tag || {};
      rows.push([ds, U.fmtH1(bt.regular || 0), U.fmtH1(bt.extended || 0), U.fmtH1(bt.night || 0), U.fmtH1(bt.holiday || 0),
        U.fmtH1(total), U.fmtH1(conf.high || 0), U.fmtH1(conf.mid || 0), U.fmtH1(conf.low || 0),
        (low ? ["낮은 신뢰"] : []).concat(d.leave >= 1 ? ["연차"] : (d.leave > 0 ? ["반차"] : [])).concat(d.flags || []).join(", ")]);
    }
    bg.push(line(L, y(480), L + PW, y(480), {"class": "s-ink-muted", "stroke-width": 1, "stroke-dasharray": "4 3"}));
    bg.push(text(L + PW + 4, y(480) + 4, "8h", "t-axis"));
    var cap = {title: title + " · " + month, summary: month + " · 근무 기록 " + rows.length + "일 · 낮은 신뢰 " + lowDays + "일",
      notes: []};
    var legend = TAGS.map(function (t) { return {label: TAG_NAME[t], swatch: swRect({"class": "f-tag-" + t})}; });
    legend.push({label: "낮은 신뢰(낮음 30% 이상) — 빗금", swatch: swRect({"class": "f-tag-regular"}, "est")});
    legend.push({label: "8h 기준", swatch: swLine("s-ink-muted", "4 3")});
    return result(svgRoot(W, H, id, cap, bg.concat(kids)), cols, rows, legend, cap);
  }

  // ───────────────────────── CH-P04 업무 영역 구성 ─────────────────────────
  function domainShare(spec, opt) {
    opt = opt || {};
    var U = ui();
    var id = opt.id || "ch-p04";
    var W = opt.width || 720;
    var title = "업무 영역 구성";
    var cols = ["영역", "MM", "비중", "단위업무 수"];
    var doms = (spec.domains || []).map(function (d, i) { return {d: d, i: i}; })
      .filter(function (o) { return (o.d.min || 0) > 0; })
      .sort(function (a, b) { return (domainRank(a.d.code) - domainRank(b.d.code)) || (a.i - b.i); })
      .map(function (o) { return o.d; });
    var un = spec.unattr_min || 0;
    var total = sum(doms, function (d) { return d.min; }) + un;
    if (total <= 0) { return emptyResult(id, title, "그 기간의 투입이 없습니다.", cols); }
    var denom = spec.denom_min || 0;
    var segs = doms.map(function (d) {
      return {key: d.code, name: d.name || d.code, min: d.min, units: d.units, paint: domainPaint(d.color), un: false};
    });
    if (un > 0) { segs.push({key: "UNATTR", name: "근무 중 미분류", min: un, units: null, paint: {fill: "url(#hatch-unattr)"}, un: true}); }
    var gapTotal = 2 * (segs.length - 1);
    var x = 0;
    var kids = [];
    var rows = [];
    var legend = [];
    segs.forEach(function (sg, k) {
      var w = (W - gapTotal) * sg.min / total;
      var pct = U.pctText(sg.min, total);
      var mmT = denom > 0 ? U.mmText(sg.min, denom) : U.hText(sg.min);
      var c = {};
      if (k === 0) { c.tl = 3; c.bl = 3; }
      if (k === segs.length - 1) { c.tr = 3; c.br = 3; }
      var pa = {d: roundRect(x, 4, w, 32, c)};
      Object.keys(sg.paint).forEach(function (p) { pa[p] = sg.paint[p]; });
      var lines = [sg.name, "비중\t" + pct, "투입\t" + mmT];
      if (sg.units !== null && sg.units !== undefined) { lines.push("단위업무\t" + sg.units + "개"); }
      if (!sg.un) { lines.push("누르면 영역 보기"); }
      kids.push(h("g", mark(lines, sg.un ? null : "open-domain", sg.un ? null : sg.key), [hit(x, 4, w, 32), h("path", pa)]));
      x += w + 2;
      rows.push([sg.name, denom > 0 ? U.fmtMM(sg.min, denom) : "—", pct,
        sg.units === null || sg.units === undefined ? "—" : String(sg.units)]);
      var sw = sg.un ? swRect({fill: "url(#hatch-unattr)"}) : swRect(sg.paint);
      legend.push({label: sg.name + " " + pct + " · " + mmT, swatch: sw});
    });
    // 막대 바로 아래 범례 줄(조각 안에는 글자를 쓰지 않는다 — 영역 색 위 흰 글자는 AA 미달)
    var lx = 0;
    var ly = 58;
    legend.forEach(function (it) {
      var iw = 18 + textW(it.label, 13) + 16;
      if (lx > 0 && lx + iw > W) { lx = 0; ly += 22; }
      kids.push(h("g", {transform: "translate(" + f1(lx) + " " + f1(ly - 11) + ")"}, it.swatch));
      kids.push(text(lx + 18, ly, it.label, "t-label"));
      lx += iw;
    });
    var topSeg = segs.filter(function (sg) { return !sg.un; }).sort(function (a, b) { return b.min - a.min; })[0];
    var cap = {title: title, summary: topSeg ? "가장 큰 영역 " + topSeg.name + " " + U.pctText(topSeg.min, total) : "모두 미분류",
      notes: []};
    var res = result(svgRoot(W, ly + 10, id, cap, kids), cols, rows, [], cap);
    res.inlineLegend = legend;                                     // 막대 아래 범례 줄이 그림 안에 있다(중복 범례 없음)
    return res;
  }

  // ───────────────────────── CH-P06·P09·T08 간트 ─────────────────────────
  var STATUS_NAME = {closed: "완료", estimated: "추정 종료", open: "진행 중", not_started: "미착수"};

  function unitLead(u) {
    if (u.lead) { return [dayNum(u.lead[0]), dayNum(u.lead[1])]; }
    var sp = u.spans || u.gantt_spans || [];
    for (var i = 0; i < sp.length; i++) { if (sp[i][2] === "lead") { return [dayNum(sp[i][0]), dayNum(sp[i][1])]; } }
    if (!sp.length) { return null; }
    var a = Infinity;
    var b = -Infinity;
    sp.forEach(function (s) { a = Math.min(a, dayNum(s[0])); b = Math.max(b, dayNum(s[1])); });
    return [a, b];
  }

  function weekVal(v) {
    if (typeof v === "number") { return {obs: v, est: 0, all: v, split: false}; }
    var o = (v && v.obs) || 0;
    var e = (v && v.est) || 0;
    return {obs: o, est: e, all: o + e, split: true};
  }

  function unionDays(spans) {
    var list = spans.slice().sort(function (a, b) { return a[0] - b[0] || a[1] - b[1]; });
    var out = [];
    list.forEach(function (s) {
      if (out.length && s[0] <= out[out.length - 1][1] + 1) {
        out[out.length - 1][1] = Math.max(out[out.length - 1][1], s[1]);
      } else { out.push([s[0], s[1]]); }
    });
    return out;
  }

  function busiest(u) {
    var best = null;
    Object.keys(u.density || {}).sort().forEach(function (k) {
      var v = weekVal(u.density[k]).all;
      if (v > 0 && (!best || v > best[1])) { best = [k, v]; }
    });
    return best;
  }

  function rowStats(units, rowEnd) {
    var U = ui();
    var effort = sum(units, function (u) { return u.effort_min || 0; });
    var leads = [];
    var par = [];
    units.forEach(function (u) {
      var l = unitLead(u);
      if (l) { leads.push(l); }
      if (typeof u.parallel === "number") { par.push(u.parallel); }
    });
    var days = sum(unionDays(leads), function (s) { return s[1] - s[0] + 1; });
    var hTxt = U.fmtH1(effort) + "h";
    var pTxt = par.length ? U.fmtX(sum(par) / par.length) : "—";
    if (rowEnd) {
      if (typeof rowEnd.effort_h === "number") { hTxt = U.fmtNum(rowEnd.effort_h, 1) + "h"; }
      if (typeof rowEnd.parallel === "number") { pTxt = U.fmtX(rowEnd.parallel); }
      if (typeof rowEnd.lead_days === "number") { days = rowEnd.lead_days; }
    }
    return {text: hTxt + " · " + pTxt + " · " + days + "일", effort: effort};
  }

  function rowHidden(key, collapsed) {
    var ks = Object.keys(collapsed || {});
    for (var i = 0; i < ks.length; i++) {
      if (collapsed[ks[i]] && key.indexOf(ks[i] + "/") === 0) { return true; }
    }
    return false;
  }

  // spec {rows:[{key('a/b/c' 경로), label, level, group, units, row_end, ref, badge, path}], months?, as_of?}
  // opt {width, view:'month'|'week', mode:'personal'|'team', collapsed:{key:true}, id, title}
  function gantt(spec, opt) {
    opt = opt || {};
    var U = ui();
    var id = opt.id || "ch-gantt";
    var team = opt.mode === "team";
    var view = opt.view === "week" ? "week" : "month";
    var W = opt.width || 1100;
    var title = opt.title || (team ? "담당자별 업무 간트" : "단위업무 간트");
    var cols = ["행 경로", "단위업무", "시작", "끝", "등급", "상태", "투입 h", "병행도", "리드 일", "가장 바쁜 주"];
    var collapsed = opt.collapsed || {};
    var rowsAll = spec.rows || [];
    var rowsV = rowsAll.filter(function (r) { return !rowHidden(r.key, collapsed); });
    var asOf = spec.as_of ? dayNum(spec.as_of) : null;
    var lo = Infinity;
    var hi = -Infinity;
    rowsAll.forEach(function (r) {
      (r.units || []).forEach(function (u) {
        var l = unitLead(u);
        if (l) { lo = Math.min(lo, l[0]); hi = Math.max(hi, l[1]); }
      });
    });
    if (asOf !== null) { hi = Math.max(hi, asOf); }
    if (spec.months && spec.months.length) {
      lo = monthStart(spec.months[0]);
      hi = monthEnd(spec.months[spec.months.length - 1]);
    }
    if (!isFinite(lo) || !rowsV.length) { return emptyResult(id, title, "그릴 단위업무가 없습니다.", cols); }
    var d0 = monthStart(monthKey(lo));
    var d1 = monthEnd(monthKey(hi));
    if (team) {                                                    // 팀: 최근 24개월까지
      var c1 = civilFromDays(d1);
      var cap24 = daysFromCivil(c1[0] - 2 + (c1[1] === 12 ? 1 : 0), (c1[1] % 12) + 1, 1);
      d0 = Math.max(d0, cap24);
    }
    var nDays = d1 - d0 + 1;
    var labelW = W < 900 ? 180 : 280;
    var endW = 170;
    var avail = Math.max(120, W - labelW - endW);
    var dayW = view === "week" ? 16 : Math.max(2, avail / nDays);
    var TW = nDays * dayW;
    var HDR = 30;
    var FOOT = 20;
    function X(dn) { return (dn - d0) * dayW; }
    // 행 높이·줄 배정
    var layout = [];
    var yCur = HDR;
    rowsV.forEach(function (r, ri) {
      var units = r.units || [];
      var lm = {};
      var nl = 1;
      if (!r.group) {
        var bars = [];
        units.forEach(function (u) {
          var l = unitLead(u);
          if (!l) { return; }
          var t = (u.status === "open" && asOf !== null) ? Math.max(l[1], asOf) : l[1];
          bars.push({id: u.unit_id, from: l[0], to: t});
        });
        lm = lanes(bars);
        Object.keys(lm).forEach(function (k) { nl = Math.max(nl, lm[k] + 1); });
      }
      var hgt = r.group ? 28 : 8 + nl * 18;
      layout.push({r: r, i: ri, y: yCur, h: hgt, lanes: lm});
      yCur += hgt;
    });
    var H = yCur + FOOT;
    // 시간 축(가운데)
    var grid = [];
    var marksV = [];
    var lastMonth = null;
    for (var dn = d0; dn <= d1; dn++) {
      var mk = monthKey(dn);
      if (mk !== lastMonth) {
        lastMonth = mk;
        grid.push(line(X(dn), 0, X(dn), H - FOOT, {"class": "s-border", "stroke-width": 1}));
        grid.push(text(X(dn) + 4, 12, mk, "t-axis"));
      } else if (dayW >= 10 && isoWd(dn) === 1) {
        grid.push(line(X(dn), HDR - 6, X(dn), H - FOOT, {"class": "s-grid", "stroke-width": 1}));
        if (dayW >= 14) { grid.push(text(X(dn) + 2, 26, isoWeek(dn).slice(5), "t-axis")); }
      }
    }
    layout.forEach(function (Lr) {
      grid.push(line(0, Lr.y + Lr.h, TW, Lr.y + Lr.h, {"class": "s-grid", "stroke-width": 1}));
    });
    if (asOf !== null && asOf >= d0 && asOf <= d1) {
      grid.push(line(X(asOf + 1), HDR - 4, X(asOf + 1), H - FOOT, {"class": "s-ink-muted", "stroke-width": 1, "stroke-dasharray": "3 3"}));
      grid.push(text(X(asOf + 1), H - 6, "기준일", "t-axis", "middle"));
    }
    var tableRows = [];
    var anyHatch = false;
    var anyOpen = false;
    var anyEst = false;
    layout.forEach(function (Lr) {
      var r = Lr.r;
      var units = r.units || [];
      if (r.group) {                                              // 요약 띠: 리드 합집합 + 주 밀도 합
        var leads = [];
        var wk = {};
        units.forEach(function (u) {
          var l = unitLead(u);
          if (l) { leads.push([Math.max(l[0], d0), Math.min(l[1], d1)]); }
          Object.keys(u.density || {}).forEach(function (k) { wk[k] = (wk[k] || 0) + weekVal(u.density[k]).all; });
        });
        unionDays(leads).forEach(function (s) {
          if (s[0] > s[1]) { return; }
          grid.push(rect(X(s[0]), Lr.y + 12, X(s[1] + 1) - X(s[0]), 8, {"class": "f-lead"}));
        });
        Object.keys(wk).sort().forEach(function (k) {
          var ws = weekStart(k);
          var a = Math.max(ws, d0);
          var b = Math.min(ws + 6, d1);
          if (a > b || !(wk[k] > 0)) { return; }
          grid.push(rect(X(a), Lr.y + 13, X(b + 1) - X(a), 6, {"class": "f-seq-" + densityLevel(wk[k])}));
        });
        return;
      }
      var ordered = units.filter(function (u) { return unitLead(u); }).slice().sort(function (a, b) {
        return (Lr.lanes[a.unit_id] - Lr.lanes[b.unit_id]) || (unitLead(a)[0] - unitLead(b)[0]) || cmpStr(a.unit_id, b.unit_id);
      });
      ordered.forEach(function (u) {
        var l = unitLead(u);
        var f = l[0];
        var t = l[1];
        var open = u.status === "open";
        if (open && asOf !== null) { t = Math.max(t, asOf); }
        var lane = Lr.lanes[u.unit_id] || 0;
        var laneY = Lr.y + 4 + lane * 18;
        var fx = Math.max(f, d0);
        var tx = Math.min(t, d1);
        var x = X(fx);
        var w = Math.max(4, X(tx + 1) - x);
        var parts = [hit(x, laneY + 2, w, 14), rect(x, laneY + 2, w, 14, {rx: 3, "class": "f-lead"})];
        parts.push(line(x, laneY + 2, x + w, laneY + 2, {"class": "s-lead", "stroke-width": 1}));
        parts.push(line(x, laneY + 16, x + w, laneY + 16, {"class": "s-lead", "stroke-width": 1}));
        var startNone = u.start && u.start.precision === "none";
        parts.push(line(x, laneY + 2, x, laneY + 16, {"class": "s-lead", "stroke-width": 1, "stroke-dasharray": startNone ? "3 2" : null}));
        if (!open) {
          var est = u.status === "estimated";
          parts.push(line(x + w, laneY + 2, x + w, laneY + 16, {"class": "s-lead", "stroke-width": 1, "stroke-dasharray": est ? "3 2" : null}));
          if (est) { anyEst = true; }
        } else {
          anyOpen = true;
          parts.push(h("polygon", {points: f1(x + w) + "," + f1(laneY + 5) + " " + f1(x + w + 6) + "," + f1(laneY + 9) + " " +
            f1(x + w) + "," + f1(laneY + 13), "class": "f-ink-muted"}));
        }
        if (startNone) { anyEst = true; }
        var outside = false;
        Object.keys(u.density || {}).sort().forEach(function (k) {
          var v = weekVal(u.density[k]);
          if (!(v.all > 0)) { return; }
          var ws = weekStart(k);
          var a = Math.max(ws, d0);
          var b = Math.min(ws + 6, d1);
          if (a > b) { return; }
          if (b < f || a > t) { outside = true; }
          var cx = X(a);
          var cw = X(b + 1) - cx;
          parts.push(rect(cx, laneY + 4, cw, 10, {"class": "f-seq-" + densityLevel(v.all)}));
          if (!team && v.split && v.est * 2 >= v.all) {            // 그 주 est/(obs+est) ≥ 0.5
            parts.push(hatch(cx, laneY + 4, cw, 10, "est"));
            anyHatch = true;
          }
        });
        if (!team && view === "week") {                            // 라벨 공간 규칙: 같은 줄 다음 막대까지 120px 이상
          var nextX = TW;
          ordered.forEach(function (v2) {
            if ((Lr.lanes[v2.unit_id] || 0) === lane && v2 !== u) {
              var l2 = unitLead(v2);
              if (l2[0] > t) { nextX = Math.min(nextX, X(l2[0])); }
            }
          });
          if (nextX - (x + w) >= 124) { parts.push(text(x + w + 4, laneY + 13, fitText(u.title || "", 120, 12), "t-axis")); }
        }
        var bz = busiest(u);
        var lines = [u.title || u.unit_id];
        if (u.path || r.path) { lines.push(u.path || r.path); }
        var st = u.start && u.start.at ? u.start.at + (u.start.label ? "(" + u.start.label + ")" : "") : dateOf(l[0]).slice(5);
        var en = open ? "진행 중" : (u.end && u.end.at ? u.end.at + (u.end.label ? "(" + u.end.label + ")" : "") : dateOf(l[1]).slice(5));
        lines.push(st + " → " + en);
        lines.push("등급\t" + (u.grade || "—"));
        lines.push("상태\t" + (STATUS_NAME[u.status] || u.status || "—"));
        lines.push("투입\t" + U.fmtH1(u.effort_min || 0) + "h");
        lines.push("병행\t" + U.fmtX(u.parallel));
        if (bz) { lines.push("가장 바쁜 주\t" + bz[0].slice(5) + " " + U.fmtH1(bz[1]) + "h"); }
        if (outside) { lines.push("의뢰 전 작업 포함"); }
        lines.push(team ? "누르면 워크플로우 보기" : "누르면 업무 보기");
        var act = opt.act || (team ? "open-gantt" : "open-unit");
        var ref = team ? (r.ref || u.unit_id) : u.unit_id;
        marksV.push(h("g", mark(lines, act, ref, {"data-nav-row": String(Lr.i), "data-nav-x": f1(x), "data-unit": u.unit_id}), parts));
      });
    });
    rowsAll.forEach(function (r) {                                 // 표로 보기: 접힌 행까지 잎 행의 단위업무 전부
      if (r.group) { return; }
      (r.units || []).filter(function (u) { return unitLead(u); }).sort(function (a, b) {
        return (unitLead(a)[0] - unitLead(b)[0]) || cmpStr(a.unit_id, b.unit_id);
      }).forEach(function (u) {
        var l = unitLead(u);
        var bz = busiest(u);
        tableRows.push([r.path || r.label, u.title || u.unit_id, dateOf(l[0]), u.status === "open" ? "진행 중" : dateOf(l[1]),
          u.grade || "—", STATUS_NAME[u.status] || u.status || "—", U.fmtH1(u.effort_min || 0), U.fmtX(u.parallel),
          String(l[1] - l[0] + 1), bz ? bz[0].slice(5) + " " + U.fmtH1(bz[1]) + "h" : "—"]);
      });
    });
    var cap = {title: title, summary: monthKey(d0) + " ~ " + monthKey(d1) + " · 단위업무 " + tableRows.length +
      "개 · 막대 길이는 리드타임입니다(투입이 아님)", notes: []};
    var timeSvg = svgRoot(TW, H, id, cap, grid.concat(marksV), "gantt-time");
    // 라벨 열(고정)
    var lab = [text(8, 20, opt.labelHead || (team ? "담당자 › 영역 › 과제 › 역할" : "영역 › 과제 › 역할"), "t-axis")];
    layout.forEach(function (Lr) {
      var r = Lr.r;
      var ind = 8 + (r.level || 0) * 14;
      var cy = Lr.y + (r.group ? 18 : Math.min(Lr.h, 26) / 2 + 5);
      var maxW = labelW - ind - (r.badge ? 40 : 12) - (r.group ? 14 : 0);
      if (r.group) {
        var open2 = !collapsed[r.key];
        lab.push(h("g", {"class": "mk", tabindex: "0", role: "button", "aria-expanded": open2 ? "true" : "false",
          "aria-label": r.label + (open2 ? " 접기" : " 펼치기"), "data-act": "toggle-row", "data-ref": r.key}, [
          rect(ind - 4, Lr.y + 2, labelW - ind, Lr.h - 4, {"class": "hit"}),
          text(ind, cy, open2 ? "▾" : "▸", "t-axis"),
          text(ind + 14, cy, fitText(r.label, maxW, 14), "t-strong")]));
      } else if (r.ref && team) {
        lab.push(h("g", mark([r.label, "누르면 워크플로우 보기"], opt.act || "open-gantt", r.ref), [
          rect(ind - 4, Lr.y + 2, labelW - ind, Math.min(Lr.h - 4, 24), {"class": "hit"}),
          text(ind, cy, fitText(r.label, maxW, 13), "t-label")]));
      } else {
        lab.push(text(ind, cy, fitText(r.label, maxW, 13), "t-label"));
      }
      if (r.badge === "unreliable") {
        lab.push(h("g", {"class": "mk", tabindex: "0", role: "img", "aria-label": "측정 불충분", "data-tip": "측정 불충분 — 합계에는 들어가고 비교에서는 빠집니다"}, [
          rect(labelW - 30, cy - 10, 22, 12, {rx: 2, "class": "f-faint"}), hatch(labelW - 30, cy - 10, 22, 12, "est")]));
      }
    });
    var labelSvg = h("svg", {"class": "chart gantt-labels-svg", viewBox: "0 0 " + labelW + " " + f1(H), width: labelW,
      height: round1(H), role: "group", "aria-label": "행 이름", focusable: "false"}, lab);
    var ends = [text(endW - 8, 20, "투입 · 병행도 · 리드", "t-axis", "end")];
    layout.forEach(function (Lr) {
      var stt = rowStats(Lr.r.units || [], Lr.r.group ? null : Lr.r.row_end);
      ends.push(text(endW - 8, Lr.y + (Lr.r.group ? 18 : Math.min(Lr.h, 26) / 2 + 5), stt.text, "t-small", "end"));
    });
    var endSvg = h("svg", {"class": "chart gantt-ends-svg", viewBox: "0 0 " + endW + " " + f1(H), width: endW, height: round1(H),
      "aria-hidden": "true", focusable: "false"}, ends);
    var root2 = h("div", {"class": "gantt", "data-nav": "gantt", "data-view": view}, [
      h("div", {"class": "gantt-labels"}, [labelSvg]),
      h("div", {"class": "gantt-scroll", tabindex: "-1"}, [timeSvg]),
      h("div", {"class": "gantt-ends"}, [endSvg])]);
    var legend = [
      {label: "리드타임(의뢰~보고) — 막대 길이는 투입이 아닙니다", swatch: swRect({"class": "f-lead s-lead", "stroke-width": 1})},
      {label: "주당 투입 2h 미만", swatch: swRect({"class": "f-seq-1"})},
      {label: "2~6h", swatch: swRect({"class": "f-seq-2"})},
      {label: "6~12h", swatch: swRect({"class": "f-seq-3"})},
      {label: "12~20h", swatch: swRect({"class": "f-seq-4"})},
      {label: "20h 이상", swatch: swRect({"class": "f-seq-5"})},
      {label: "추정 경계", swatch: swLine("s-lead", "3 2")},
      {label: "진행 중", swatch: [h("polygon", {points: "3,3 11,7 3,11", "class": "f-ink-muted"})]}];
    if (!team) { legend.push({label: "추정 비중 50% 이상", swatch: swRect({"class": "f-seq-3"}, "est")}); }
    if (team) { legend.push({label: "측정 불충분(비교에서 제외)", swatch: swRect({"class": "f-faint"}, "est")}); }
    cap.notes = [];
    if (anyHatch) { cap.notes.push("빗금 칸은 그 주 투입의 절반 이상이 추정입니다."); }
    if (anyOpen || anyEst) { cap.notes.push("점선 끝은 추정 경계, ▸ 는 기준일까지 진행 중입니다."); }
    return result(root2, cols, tableRows, legend, cap);
  }

  // 행 계층 만들기(공용): items [{keys:{level: key}, units, ref, row_end}] → gantt rows
  function treeRows(items, levels, nameOf, badgeOf) {
    var out = [];
    function effortOf(list) { return sum(list, function (it) { return sum(it.units || [], function (u) { return u.effort_min || 0; }); }); }
    function walk(list, depth, prefix, pathTxt) {
      var lvl = levels[depth];
      var groups = {};
      var order = [];
      list.forEach(function (it) {
        var k = String(it.keys[lvl]);
        if (!groups[k]) { groups[k] = []; order.push(k); }
        groups[k].push(it);
      });
      order.sort(function (a, b) {
        if (lvl === "domain") { return (domainRank(a) - domainRank(b)) || cmpStr(a, b); }
        var ea = effortOf(groups[a]);
        var eb = effortOf(groups[b]);
        return (eb - ea) || cmpStr(nameOf.sortKey ? nameOf.sortKey(lvl, a) : a, nameOf.sortKey ? nameOf.sortKey(lvl, b) : b);
      });
      order.forEach(function (k) {
        var g = groups[k];
        var key = prefix ? prefix + "/" + lvl + ":" + k : lvl + ":" + k;
        var label = nameOf(lvl, k);
        var path = pathTxt ? pathTxt + " › " + label : label;
        var leaf = depth === levels.length - 1;
        var units = [];
        g.forEach(function (it) { units = units.concat(it.units || []); });
        out.push({key: key, label: label, level: depth, group: !leaf, units: units, path: path,
          ref: leaf ? (g[0].ref || null) : null, row_end: leaf && g.length === 1 ? (g[0].row_end || null) : null,
          badge: badgeOf ? badgeOf(lvl, k) : null});
        if (!leaf) { walk(g, depth + 1, key, path); }
      });
    }
    walk(items, 0, "", "");
    return out;
  }

  // 팀 데이터(team_data.gantt) → 행. 기본 담당자 → 영역 → 과제 → 역할, pivot 이면 영역 → 과제 → 역할 → 담당자
  function ganttRows(td, opt) {
    opt = opt || {};
    var people = td.people || [];
    var vn = td.vocab_names || {};
    var projById = {};
    (td.projects || []).forEach(function (p) { projById[p.project_id] = p; });
    var roleById = {};
    (td.roles || []).forEach(function (r) { roleById[r.role_id] = r; });
    var domByCode = {};
    (td.domains || []).forEach(function (d) { domByCode[d.code] = d; });
    function personOf(i) { return people[+i] || {}; }
    function nameOf(lvl, k) {
      if (lvl === "person") { return personOf(k).label || ("담당자 " + (+k + 1)); }
      if (lvl === "domain") { return (domByCode[k] && domByCode[k].name) || (opt.domainNames && opt.domainNames[k]) || k; }
      if (lvl === "project") { return (projById[k] && projById[k].label) || (k === "-" ? "과제 없음" : k); }
      var r = roleById[k];
      if (r) {
        var fn = (vn.field && vn.field[r.field]) || r.field || "";
        var un = (vn.func && vn.func[r["function"]]) || r["function"] || "";
        return fn && un ? fn + "·" + un : (fn || un || k);
      }
      return k;
    }
    nameOf.sortKey = function (lvl, k) { return lvl === "person" ? (personOf(k).person_key || pad2(+k)) : k; };
    function badgeOf(lvl, k) { return lvl === "person" && personOf(k).quality === "unreliable" ? "unreliable" : null; }
    var items = (td.gantt || []).map(function (g) {
      return {keys: {person: String(g.person), domain: g.domain || "UNC", project: g.project_id || "-", role: g.role_id},
        units: g.units || [], ref: g.person + "|" + g.role_id, row_end: g.row_end || null};
    });
    var levels = opt.pivot ? ["domain", "project", "role", "person"] : ["person", "domain", "project", "role"];
    return treeRows(items, levels, nameOf, badgeOf);
  }

  // 개인 보고서 모델 → 간트 행(영역 → 과제 → 역할, 잎 = 역할 업무)
  function modelRows(model) {
    var dn = {};
    (model.domains || []).forEach(function (d) { dn[d.code] = d.name || d.code; });
    var pn = {};
    (model.projects || []).forEach(function (p) { pn[p.key] = p.label || p.key; });
    var rn = {};
    (model.roles || []).forEach(function (r) { rn[r.role_id] = r.label || r.role_id; });
    function nameOf(lvl, k) {
      if (lvl === "domain") { return dn[k] || k; }
      if (lvl === "project") { return pn[k] || (k === "-" ? "과제 없음" : k); }
      return rn[k] || k;
    }
    var by = {};
    var order = [];
    (model.units || []).forEach(function (u) {
      var key = (u.domain || "UNC") + "|" + (u.project_key || "-") + "|" + (u.role_id || "-");
      if (!by[key]) {
        by[key] = {keys: {domain: u.domain || "UNC", project: u.project_key || "-", role: u.role_id || "-"}, units: [], ref: u.role_id || null};
        order.push(key);
      }
      by[key].units.push(u);
    });
    return treeRows(order.map(function (k) { return by[k]; }), ["domain", "project", "role"], nameOf, null);
  }

  // ───────────────────────── CH-P07 프로세스 맵 ─────────────────────────
  function processMap(spec, opt) {
    opt = opt || {};
    var U = ui();
    var id = opt.id || "ch-p07";
    var W = opt.width || 720;
    var title = opt.title || "역할 워크플로우";
    var cols = ["번호", "단계", "라벨", "출처", "n", "중앙 소요", "들어오는 대기", "작업 비중"];
    var steps = (spec.steps || []).slice().sort(function (a, b) { return a.no - b.no; });
    if (!steps.length) { return emptyResult(id, title, "단계를 만들 단위업무가 없습니다.", cols); }
    var k = steps.length;
    var unitsN = spec.units_n || spec.units || null;
    var byNo = {};
    steps.forEach(function (s) { byNo[s.no] = s; });
    var thin = spec.sample === "thin";
    var bns = thin ? [] : (spec.bottlenecks || []);
    var edges = (spec.edges || []).slice().sort(function (a, b) { return (b[2] - a[2]) || (a[0] - b[0]) || (a[1] - b[1]); });
    var drawn = edges.slice(0, opt.maxEdges || 12);
    var nmax = Math.max.apply(null, [1].concat(edges.map(function (e) { return e[2]; })));
    var horiz = W >= 560;
    var Y = 130;
    var skips = drawn.filter(function (e) { return e[1] > e[0] + 1; }).length;
    var maxSkip = 0;
    drawn.forEach(function (e) { if (e[1] > e[0] + 1) { maxSkip = Math.max(maxSkip, e[1] - e[0] - 1); } });
    var H = horiz ? 260 + 20 * Math.max(0, skips - 3) : 40 + (k - 1) * 76 + 60;
    var pos = {};
    steps.forEach(function (s, i) {
      if (horiz) {
        pos[s.no] = {x: k === 1 ? W / 2 : 70 + i * (W - 140) / (k - 1), y: Y};
      } else {
        pos[s.no] = {x: W / 2 - 30, y: 40 + i * 76};
      }
    });
    function isMs(s) { return s.kind === "M"; }
    function hw(s) { return isMs(s) ? 10 : 56; }
    function hh(s) { return isMs(s) ? 10 : 22; }
    function name(s) { return s.name || s.type || s.code || ("S" + s.no); }
    function sw(n) { return Math.round((1.5 + 4.5 * n / nmax) * 2) / 2; }
    var kids = [];
    var labelTop = {};
    drawn.slice(0, 3).forEach(function (e) { labelTop[e[0] + ">" + e[1]] = true; });
    // 대기 병목 단계로 들어오는 가장 굵은 간선
    var waitBn = bns.filter(function (b) { return b.kind === "wait"; })[0];
    var waitEdge = null;
    if (waitBn) {
      edges.forEach(function (e) { if (e[1] === waitBn.no && (!waitEdge || e[2] > waitEdge[2])) { waitEdge = e; } });
    }
    var edgeRows = [];
    drawn.forEach(function (e) {
      var a = byNo[e[0]];
      var b = byNo[e[1]];
      if (!a || !b) { return; }
      var pa = pos[e[0]];
      var pb = pos[e[1]];
      var rework = e[1] < e[0];
      var p0;
      var p1;
      var c;
      if (horiz) {
        if (e[1] === e[0] + 1) {
          p0 = {x: pa.x + hw(a), y: Y};
          p1 = {x: pb.x - hw(b), y: Y};
          c = null;
        } else if (!rework) {                                       // 앞 건너뛰기: 노드 오른쪽 반 → 다음 노드 왼쪽 반(가운데 위 배지와 겹치지 않게)
          p0 = {x: pa.x + hw(a) / 2, y: Y - hh(a)};
          p1 = {x: pb.x - hw(b) / 2, y: Y - hh(b)};
          c = {x: (p0.x + p1.x) / 2, y: Y - 22 - 24 - 14 * (e[1] - e[0] - 1)};
        } else {
          p0 = {x: pa.x, y: Y + hh(a) + (isMs(a) ? 0 : 8)};
          p1 = {x: pb.x, y: Y + hh(b) + (isMs(b) ? 0 : 8)};
          c = {x: (pa.x + pb.x) / 2, y: Y + 22 + 24 + 14 * (e[0] - e[1] - 1)};
        }
      } else {
        if (e[1] === e[0] + 1) {
          p0 = {x: pa.x, y: pa.y + hh(a) + (isMs(a) ? 0 : 8)};
          p1 = {x: pb.x, y: pb.y - hh(b)};
          c = null;
        } else if (!rework) {
          p0 = {x: pa.x + hw(a), y: pa.y};
          p1 = {x: pb.x + hw(b), y: pb.y};
          c = {x: pa.x + 56 + 24 + 14 * (e[1] - e[0] - 1), y: (pa.y + pb.y) / 2};
        } else {
          p0 = {x: pa.x - hw(a), y: pa.y};
          p1 = {x: pb.x - hw(b), y: pb.y};
          c = {x: pa.x - 56 - 24 - 14 * (e[0] - e[1] - 1), y: (pa.y + pb.y) / 2};
        }
      }
      var d = "M" + f1(p0.x) + " " + f1(p0.y) + (c ? "Q" + f1(c.x) + " " + f1(c.y) + " " : "L") + f1(p1.x) + " " + f1(p1.y);
      var from = c || p0;                                          // 화살촉 방향: 제어점(또는 시작) → 끝
      var dx = p1.x - from.x;
      var dy = p1.y - from.y;
      var len = Math.sqrt(dx * dx + dy * dy) || 1;
      var ux = dx / len;
      var uy = dy / len;
      var bx = p1.x - ux * 8;
      var by = p1.y - uy * 8;
      var head = f1(p1.x) + "," + f1(p1.y) + " " + f1(bx - uy * 4) + "," + f1(by + ux * 4) + " " + f1(bx + uy * 4) + "," + f1(by - ux * 4);
      var mid = c ? {x: 0.25 * p0.x + 0.5 * c.x + 0.25 * p1.x, y: 0.25 * p0.y + 0.5 * c.y + 0.25 * p1.y} :
        {x: (p0.x + p1.x) / 2, y: (p0.y + p1.y) / 2};
      var lines = [name(a) + " → " + name(b) + " ×" + e[2]];
      if (rework) { lines.push("되돌림(재작업)"); }
      if (typeof b.wait_in_median_min === "number" && e[1] === e[0] + 1) { lines.push("들어오는 대기 중앙\t" + U.daysText(b.wait_in_median_min)); }
      var g = [h("path", {d: d, "class": "pm-edge", fill: "none", "stroke-width": sw(e[2]), "stroke-dasharray": rework ? "5 4" : null}),
        h("polygon", {points: head, "class": "pm-arrow"})];
      if (labelTop[e[0] + ">" + e[1]]) { g.push(text(mid.x + (horiz ? 0 : 6), mid.y - 4, "×" + e[2], "t-axis", horiz ? "middle" : null)); }
      if (waitEdge && e === waitEdge && typeof waitBn.value_min === "number" && horiz) {
        var wt = "대기 " + U.fmtDays(waitBn.value_min) + "일";       // 노드 사이에 들어갈 자리가 있을 때만(값은 배지·툴팁에도 있다)
        if (c || Math.abs(p1.x - p0.x) >= textW(wt, 12) + 8) { g.push(text(mid.x, mid.y + 14, wt, "t-value", "middle")); }
      }
      kids.push(h("g", mark(lines, null, null, {"data-edge": e[0] + ">" + e[1]}), g));
      edgeRows.push([name(a), name(b), String(e[2]), rework ? "예" : "아니오"]);
    });
    var rows = [];
    steps.forEach(function (s) {
      var p = pos[s.no];
      var bn = bns.filter(function (b) { return b.no === s.no; });
      var parts = [];
      if (isMs(s)) {
        parts.push(hit(p.x - 12, p.y - 12, 24, 24));
        parts.push(h("polygon", {points: f1(p.x) + "," + f1(p.y - 10) + " " + f1(p.x + 10) + "," + f1(p.y) + " " + f1(p.x) + "," +
          f1(p.y + 10) + " " + f1(p.x - 10) + "," + f1(p.y), "class": "pm-ms" + (bn.length ? " pm-bn" : "")}));
        parts.push(horiz ? text(p.x, p.y + 26, ellipsis(s.label || name(s), 9), "t-small", "middle") :
          text(p.x - 16, p.y + 4, ellipsis(s.label || name(s), 9), "t-small", "end"));
      } else {
        parts.push(hit(p.x - 56, p.y - 22, 112, 52));
        parts.push(rect(p.x - 56, p.y - 22, 112, 44, {rx: 6, "class": "pm-node" + (bn.length ? " pm-bn" : "")}));
        parts.push(text(p.x, p.y - 3, ellipsis(s.label || name(s), 9), "t-node", "middle"));
        parts.push(text(p.x, p.y + 14, s.median_min > 0 ? "중앙 " + U.fmtH1(s.median_min) + "h" : "—", "t-small", "middle"));
        if (typeof s.work_share === "number" && s.work_share > 0) {
          parts.push(rect(p.x - 56, p.y + 25, Math.min(112, 100 * s.work_share), 4, {"class": "f-blue"}));
        }
      }
      bn.forEach(function (b, bi) {                               // 병목 배지: 가로면 노드 위(글자 끝 = 가운데 + 20), 세로면 오른쪽 호 바깥
        var t2 = b.kind === "wait" ? "대기 병목 · " + U.daysText(b.value_min) : "작업 병목 · " + U.shareText(b.share);
        var tx = horiz ? p.x + 20 - textW(t2, 12) : p.x + 56 + 24 + 7 * maxSkip + 14;
        var by0 = horiz ? p.y - hh(s) - 8 - bi * 15 : p.y - 2 + bi * 15;
        parts.push(h("g", {"class": "pm-badge"}, [
          h("polygon", {points: f1(tx - 15) + "," + f1(by0) + " " + f1(tx - 9) + "," + f1(by0 - 10) + " " + f1(tx - 3) + "," + f1(by0),
            "class": "f-st-serious"}),
          text(tx, by0, t2, "t-value")]));
      });
      var lines = ["S" + s.no + " " + name(s) + (s.label && s.label !== name(s) ? "(" + (s.label_by === "rule" ? "규칙" : "AI") + " 라벨: " + s.label + ")" : "")];
      if (unitsN) { lines.push(s.n + "/" + unitsN + " 단위업무"); } else { lines.push("단위업무\t" + s.n); }
      if (!isMs(s)) { lines.push("중앙\t" + s.median_min + "분" + (typeof s.p75_min === "number" ? "(75% " + s.p75_min + "분)" : "")); }
      if (typeof s.wait_in_median_min === "number") { lines.push("들어오는 대기 중앙\t" + U.daysText(s.wait_in_median_min)); }
      if (typeof s.obs_share === "number") { lines.push("관측\t" + U.shareText(s.obs_share)); }
      if (s.agent_grade) { lines.push("Agentic\t" + s.agent_grade); }
      if (s.subagent) { lines.push("서브에이전트\t" + s.subagent); }
      bn.forEach(function (b) { lines.push(b.kind === "wait" ? "대기 병목" : "작업 병목"); });
      lines.push("누르면 단계 표에서 보기");
      kids.push(h("g", mark(lines, "pm-step", s.no, {"data-step": s.type || s.code || ""}), parts));
      rows.push([String(s.no), name(s), s.label || name(s), {ai: "AI", manual: "AI(붙여넣기)", user: "내 지정"}[s.label_by] || "규칙",
        String(s.n), isMs(s) ? "—" : U.fmtH1(s.median_min) + "h",
        typeof s.wait_in_median_min === "number" ? U.daysText(s.wait_in_median_min) : "—",
        typeof s.work_share === "number" ? U.shareText(s.work_share) : "—"]);
    });
    var notes = [];
    var dropped = spec.dropped || [];
    if (dropped.length) {
      notes.push("드물어 뺀 단계: " + dropped.map(function (dd) {
        if (typeof dd === "string") { return dd; }
        return (dd.name || dd.code) + (unitsN && typeof dd.n === "number" ? "(" + dd.n + "/" + unitsN + ")" : "");
      }).join(", "));
    }
    if (thin) { notes.push("표본 부족(단위업무 " + (unitsN || 0) + "건) — 병목 판단 안 함"); }
    var bnTxt = bns.map(function (b) {
      var s = byNo[b.no];
      return (b.kind === "wait" ? "대기 병목 " : "작업 병목 ") + (s ? name(s) : "S" + b.no);
    }).join(" · ");
    var cap = {title: title, summary: "단계 " + k + "개 · 전이 " + edges.length + "개" + (bnTxt ? " · " + bnTxt : ""), notes: notes};
    var res = result(svgRoot(W, H, id, cap, kids, "pm"), cols, rows, [
      {label: "구간 단계(작업)", swatch: [h("rect", {x: 1, y: 3, width: 12, height: 8, rx: 2, "class": "pm-node"})]},
      {label: "점 단계(의뢰·보고)", swatch: [h("polygon", {points: "7,2 12,7 7,12 2,7", "class": "pm-ms"})]},
      {label: "되돌림(재작업)", swatch: swLine("pm-edge", "5 4")},
      {label: "병목", swatch: [h("rect", {x: 1, y: 3, width: 12, height: 8, rx: 2, "class": "pm-node pm-bn"})]}], cap);
    res.tables = [res.table, {cols: ["앞 단계", "뒤 단계", "횟수", "되돌림"], rows: edgeRows}];
    return res;
  }

  // ───────────────────────── CH-P08 단위업무 타임라인 ─────────────────────────
  var CLASSES = ["소통", "회의", "문서", "공학", "코드", "조사", "오프라인"];

  function unitTimeline(spec, opt) {
    opt = opt || {};
    var U = ui();
    var id = opt.id || "ch-p08";
    var W = opt.width || 720;
    var title = "단위업무 타임라인";
    var cols = ["시각", "단계", "묶음", "분", "관측 분", "앱·문서"];
    var runs = (spec.runs || []).map(function (r) { return {r: r, a: toMin(r.a), b: toMin(r.b)}; })
      .sort(function (x, y) { return (x.a - y.a) || cmpStr(x.r.type, y.r.type); });
    var mss = (spec.milestones || []).map(function (m) { return {m: m, t: toMin(m.t)}; });
    var bds = (spec.boundaries || []).map(function (b) { return {b: b, t: toMin(b.t)}; });
    var times = runs.map(function (o) { return o.a; }).concat(runs.map(function (o) { return o.b; }), mss.map(function (o) { return o.t; }),
      bds.map(function (o) { return o.t; })).filter(function (t) { return isFinite(t); });
    if (!times.length) { return emptyResult(id, title, "이 단위업무에는 그릴 근거가 없습니다.", cols); }
    var dA = minDay(Math.min.apply(null, times));
    var dB = minDay(Math.max.apply(null, times));
    var wdSet = null;
    if (spec.days) { wdSet = {}; spec.days.forEach(function (d) { wdSet[d.d] = d.wd !== false && !d.hol; }); }
    function isWd(n) { return wdSet && wdSet[dateOf(n)] !== undefined ? wdSet[dateOf(n)] : !isWeekend(n); }
    var unitsCount = 0;
    for (var n = dA; n <= dB; n++) { unitsCount += isWd(n) ? 3 : 1; }
    var LW = 64;
    var cw = Math.max(24, (W - LW) / (unitsCount / 3));
    var colX = {};
    var colW = {};
    var xc = LW;
    for (n = dA; n <= dB; n++) { colX[n] = xc; colW[n] = isWd(n) ? cw : cw / 3; xc += colW[n]; }
    var TW = xc;
    function X(t) { var dn = minDay(t); var m = ((t % 1440) + 1440) % 1440; return colX[dn] + colW[dn] * m / 1440; }
    var present = {};
    runs.forEach(function (o) { present[o.r["class"] || "문서"] = true; });
    var lanesL = (spec.lanes && spec.lanes.length ? spec.lanes : CLASSES).filter(function (c) { return present[c]; });
    Object.keys(present).sort().forEach(function (c) { if (lanesL.indexOf(c) < 0) { lanesL.push(c); } });   // 어휘 밖 묶음도 줄을 준다
    var HDR = 30;
    var RH = 22;
    var rowY = {"근거": HDR};
    lanesL.forEach(function (c, i) { rowY[c] = HDR + RH * (i + 1); });
    var bottom = HDR + RH * (lanesL.length + 1);
    var lw = spec.longest_wait;
    var H = bottom + (lw ? 34 : 8);
    var kids = [];
    for (n = dA; n <= dB; n++) {
      if (!isWd(n)) { kids.push(rect(colX[n], HDR, colW[n], bottom - HDR, {"class": "f-surface-2"})); }
      kids.push(line(colX[n], HDR, colX[n], bottom, {"class": "s-grid", "stroke-width": 1}));
      if (isWd(n) && (cw >= 36 || isoWd(n) === 1)) { kids.push(text(colX[n] + 2, 11, mmdd(n), "t-axis")); }
    }
    ["근거"].concat(lanesL).forEach(function (c) {
      kids.push(text(LW - 6, rowY[c] + 15, c, "t-label", "end"));
      kids.push(line(LW, rowY[c] + RH, TW, rowY[c] + RH, {"class": "s-grid", "stroke-width": 1}));
    });
    var rows = [];
    runs.forEach(function (o) {
      var r = o.r;
      var c = r["class"] || "문서";
      var y = rowY[c] + 4;
      var x = X(o.a);
      var w = Math.max(1, X(o.b) - x);
      var parts = [hit(x, y, w, 14), rect(x, y, w, 14, {rx: 2, "class": "f-blue"})];
      if (typeof r.obs_min === "number" && r.obs_min < r.min) { parts.push(hatch(x, y, w, 14, "est")); }
      var nm = r.name || r.type;
      var lines = [mmdd(minDay(o.a)) + " " + hhmm(o.a) + "~" + hhmm(o.b), nm + (r.app ? "(" + r.app + ")" : ""),
        "투입\t" + U.fmtH1(r.min || 0) + "h"];
      if (typeof r.obs_min === "number") { lines.push("관측\t" + U.fmtH1(r.obs_min) + "h"); }
      lines.push("누르면 그날 보기");
      kids.push(h("g", mark(lines, "drill-day", dateOf(minDay(o.a))), parts));
      rows.push([dateOf(minDay(o.a)) + " " + hhmm(o.a) + "~" + hhmm(o.b), nm, c, String(r.min || 0),
        typeof r.obs_min === "number" ? String(r.obs_min) : "—", r.app || ""]);
    });
    var cy = rowY["근거"] + 11;
    mss.forEach(function (o) {
      var m = o.m;
      var x = X(o.t);
      var fl = m.flags || [];
      var off = fl.indexOf("offline") >= 0;
      var small = fl.indexOf("interim") >= 0;
      var r = small ? 3 : 5;
      var pts = f1(x) + "," + f1(cy - r) + " " + f1(x + r) + "," + f1(cy) + " " + f1(x) + "," + f1(cy + r) + " " + f1(x - r) + "," + f1(cy);
      var lines = [mmdd(minDay(o.t)) + " " + hhmm(o.t) + " " + (m.name || m.type)];
      if (off) { lines.push("오프라인"); }
      if (small) { lines.push("중간 보고"); }
      kids.push(h("g", mark(lines, null, null), [hit(x - 5, cy - 5, 10, 10),
        h("polygon", {points: pts, "class": off ? "pm-ms" : "f-ink-2"})]));
      rows.push([dateOf(minDay(o.t)) + " " + hhmm(o.t), m.name || m.type, "근거", "0", "—", off ? "오프라인" : ""]);
    });
    bds.forEach(function (o) {
      var b = o.b;
      var x = X(o.t);
      kids.push(line(x, HDR, x, bottom, {"class": b.estimated ? "s-ink-muted" : "s-ink-2", "stroke-width": 1.5,
        "stroke-dasharray": b.estimated ? "4 3" : null}));
      kids.push(text(x + 2, 26, b.code || (b.side === "start" ? "시작" : "끝"), "t-axis"));
    });
    if (lw && lw.a !== undefined && lw.b !== undefined) {
      var x1 = X(toMin(lw.a));
      var x2 = X(toMin(lw.b));
      kids.push(h("path", {d: "M" + f1(x1) + " " + f1(bottom + 4) + "V" + f1(bottom + 10) + "H" + f1(x2) + "V" + f1(bottom + 4),
        "class": "s-ink-muted", fill: "none", "stroke-width": 1}));
      kids.push(text((x1 + x2) / 2, bottom + 26, "대기 " + U.daysText(lw.biz_min), "t-value", "middle"));
    }
    var cap = {title: title, summary: dateOf(dA) + " ~ " + dateOf(dB) + " · 작업 구간 " + runs.length + "개 · 근거 점 " + mss.length + "개",
      notes: []};
    var legend = [{label: "작업 구간(관측)", swatch: swRect({"class": "f-blue"})},
      {label: "추정 섞임", swatch: swRect({"class": "f-blue"}, "est")},
      {label: "정확한 경계", swatch: swLine("s-ink-2", null)},
      {label: "추정 경계", swatch: swLine("s-ink-muted", "4 3")},
      {label: "오프라인 근거", swatch: [h("polygon", {points: "7,2 12,7 7,12 2,7", "class": "pm-ms"})]}];
    return result(svgRoot(TW + 8, H, id, cap, kids), cols, rows, legend, cap);
  }

  // ───────────────────────── CH-P10 단계 묶음 구성(작은 배수) ─────────────────────────
  function classMix(spec, opt) {
    opt = opt || {};
    var U = ui();
    var id = opt.id || "ch-p10";
    var W = opt.width || 720;
    var title = "단계 묶음 구성";
    var cols = ["과제", "묶음", "분", "비중"];
    var gs = (spec.groups || []).map(function (g, i) {
      var t = sum(CLASSES, function (c) { return (g.mix || {})[c] || 0; }) + (g.none_min || 0);
      return {g: g, i: i, total: t};
    }).filter(function (o) { return o.total > 0; })
      .sort(function (a, b) { return (b.total - a.total) || cmpStr(String(a.g.key), String(b.g.key)); });
    if (!gs.length) { return emptyResult(id, title, "단계 기록이 없습니다.", cols); }
    if (gs.length > 8) {                                           // 투입 상위 8, 나머지 '그 밖'
      var rest = {key: "_other", label: "그 밖", mix: {}, none_min: 0};
      gs.slice(8).forEach(function (o) {
        CLASSES.forEach(function (c) { rest.mix[c] = (rest.mix[c] || 0) + ((o.g.mix || {})[c] || 0); });
        rest.none_min += o.g.none_min || 0;
      });
      gs = gs.slice(0, 8).concat([{g: rest, total: sum(gs.slice(8), function (o) { return o.total; })}]);
    }
    var colW = 232;
    var nc = Math.max(1, Math.floor(W / colW));
    var CL = 64;
    var BW = colW - CL - 52;
    var blockH = 22 + CLASSES.length * 16 + 16 + 10;
    var kids = [];
    var rows = [];
    gs.forEach(function (o, i) {
      var bx = (i % nc) * colW;
      var by = Math.floor(i / nc) * blockH;
      kids.push(text(bx, by + 14, fitText(o.g.label || o.g.key, colW - 8, 13), "t-strong"));
      var items = CLASSES.map(function (c) { return [c, (o.g.mix || {})[c] || 0, false]; });
      items.push(["단계 없음(추정 배분)", o.g.none_min || 0, true]);
      items.forEach(function (it, j) {
        var y = by + 22 + j * 16;
        kids.push(text(bx + CL - 4, y + 10, it[2] ? "단계 없음" : it[0], "t-axis", "end"));
        var w = BW * it[1] / o.total;
        var pct = U.pctText(it[1], o.total);
        var parts = [];
        if (it[1] > 0) {
          parts.push(h("path", {d: roundRect(bx + CL, y + 2, Math.max(1, w), 10, {tr: 3, br: 3}), "class": it[2] ? "f-lead" : "f-blue"}));
          if (it[2]) { parts.push(hatch(bx + CL, y + 2, Math.max(1, w), 10, "est")); }
        }
        parts.push(text(bx + CL + Math.max(1, w) + 4, y + 11, pct, "t-axis"));
        kids.push(h("g", mark([(o.g.label || o.g.key) + " · " + it[0], "분\t" + it[1], "비중\t" + pct]), parts));
        rows.push([o.g.label || o.g.key, it[0], String(it[1]), pct]);
      });
    });
    var nRows = Math.ceil(gs.length / nc);
    var cap = {title: title, summary: "과제 " + gs.length + "개 · 모든 작은 그림은 같은 0~100% 범위", notes: []};
    var legend = [{label: "단계 묶음 비중", swatch: swRect({"class": "f-blue"})},
      {label: "단계 없음(추정 배분)", swatch: swRect({"class": "f-lead"}, "est")}];
    return result(svgRoot(Math.min(W, nc * colW), nRows * blockH, id, cap, kids), cols, rows, legend, cap);
  }

  // ───────────────────────── CH-P11·T06 리드타임 점 그림 ─────────────────────────
  function leadDots(spec, opt) {
    opt = opt || {};
    var U = ui();
    var id = opt.id || "ch-p11";
    var W = opt.width || 720;
    var title = opt.title || "리드타임 분포";
    var cols = ["단위업무", "줄", "영업 리드", "기준", "배수", "원인"];
    var rowsS = spec.rows || [];
    var pts = spec.points || [];
    if (!rowsS.length || !pts.length) { return emptyResult(id, title, "그 기간에 끝난 단위업무가 없습니다.", cols); }
    var std = spec.std_day_min || 480;
    var ratio = typeof spec.threshold_ratio === "number" ? spec.threshold_ratio : 1.5;
    var LW = 140;
    var R = 120;
    var T = 12;
    var RH = 36;
    var PW = W - LW - R;
    var maxD = 0;
    pts.forEach(function (p) { maxD = Math.max(maxD, p.biz_lead_min / std); });
    rowsS.forEach(function (r) { if (r.baseline_biz_min) { maxD = Math.max(maxD, r.baseline_biz_min * ratio / std); } });
    var top = niceTop(Math.max(1, maxD), 5);
    var tk = tickList(top, 5);
    var dg = stepDigits(tk.step);
    function X(min) { return LW + PW * (min / std) / top; }
    var H = T + rowsS.length * RH + 40;
    var kids = [];
    tk.list.forEach(function (v) {
      kids.push(line(LW + PW * v / top, T, LW + PW * v / top, T + rowsS.length * RH, {"class": "s-grid", "stroke-width": 1}));
      kids.push(text(LW + PW * v / top, T + rowsS.length * RH + 16, U.fmtNum(v, dg), "t-axis", "middle"));
    });
    kids.push(text(LW + PW, T + rowsS.length * RH + 32, "가로축: 영업일", "t-axis", "end"));
    var tableRows = [];
    rowsS.forEach(function (r, ri) {
      var cy = T + ri * RH + RH / 2;
      kids.push(text(LW - 8, cy + 4, fitText(r.label || r.key, LW - 12, 13), "t-label", "end"));
      kids.push(line(LW, cy, LW + PW, cy, {"class": "s-grid", "stroke-width": 1}));
      if (r.baseline_biz_min) {
        kids.push(line(X(r.baseline_biz_min), cy - 6, X(r.baseline_biz_min), cy + 6, {"class": "s-ink-2", "stroke-width": 2}));
        kids.push(line(X(r.baseline_biz_min * ratio), cy - 6, X(r.baseline_biz_min * ratio), cy + 6,
          {"class": "s-ink-2", "stroke-width": 1, "stroke-dasharray": "2 2"}));
      }
      var mine = pts.filter(function (p) { return p.row === r.key; }).slice()
        .sort(function (a, b) { return (a.biz_lead_min - b.biz_lead_min) || cmpStr(a.unit_id, b.unit_id); });
      var prevX = null;
      var k = 0;
      mine.forEach(function (p) {
        var x = X(p.biz_lead_min);
        k = (prevX !== null && Math.abs(x - prevX) <= 4) ? k + 1 : 0;   // 겹치면 위아래 3px 번갈아
        if (k === 0) { prevX = x; }
        var dy = k === 0 ? 0 : (k % 2 === 1 ? -3 * Math.ceil(k / 2) : 3 * (k / 2));
        var y = cy + dy;
        var names = p.cause_names || p.causes || [];
        var parts = [hit(x - 4, y - 4, 8, 8), h("circle", {cx: round1(x), cy: round1(y), r: 4, "class": "f-blue s-surface", "stroke-width": 1})];
        if (p.overrun) {
          parts.push(h("circle", {cx: round1(x), cy: round1(y), r: 6.5, "class": "s-st-bad", fill: "none", "stroke-width": 2}));
          if (names.length) { parts.push(text(x + 10, y + 4, names.join("·"), "t-value")); }
        }
        var lines = [p.title || p.unit_id, "영업 리드\t" + U.daysText(p.biz_lead_min, std)];
        if (typeof p.effort_min === "number") { lines.push("투입\t" + U.hText(p.effort_min)); }
        if (r.baseline_biz_min) { lines.push("기준 중앙\t" + U.daysText(r.baseline_biz_min, std)); }
        if (p.overrun) { lines.push("리드 초과" + (names.length ? " — " + names.join(", ") : "")); }
        lines.push("누르면 업무 보기");
        kids.push(h("g", mark(lines, "open-unit", p.unit_id), parts));
        tableRows.push([p.title || p.unit_id, r.label || r.key, U.daysText(p.biz_lead_min, std),
          r.baseline_biz_min ? U.daysText(r.baseline_biz_min, std) : "—",
          r.baseline_biz_min ? U.fmtRatio(p.biz_lead_min, r.baseline_biz_min, 1) + "배" : "—", names.join(", ")]);
      });
    });
    var over = pts.filter(function (p) { return p.overrun; }).length;
    var cap = {title: title, summary: "단위업무 " + pts.length + "개 · 리드 초과 " + over + "개 · 가로축 영업일", notes: []};
    var legend = [{label: "단위업무", swatch: [h("circle", {cx: 7, cy: 7, r: 4, "class": "f-blue"})]},
      {label: "리드 초과", swatch: [h("circle", {cx: 7, cy: 7, r: 4, "class": "f-blue"}), h("circle", {cx: 7, cy: 7, r: 6, "class": "s-st-bad", fill: "none", "stroke-width": 2})]},
      {label: "기준 중앙", swatch: [h("line", {x1: 7, y1: 1, x2: 7, y2: 13, "class": "s-ink-2", "stroke-width": 2})]},
      {label: ratio === 1.5 ? "1.5배 문턱" : "초과 문턱", swatch: [h("line", {x1: 7, y1: 1, x2: 7, y2: 13, "class": "s-ink-2", "stroke-width": 1, "stroke-dasharray": "2 2"})]}];
    return result(svgRoot(W, H, id, cap, kids), cols, tableRows, legend, cap);
  }

  // ───────────────────────── CH-P12 동료 막대 ─────────────────────────
  function peerBars(spec, opt) {
    opt = opt || {};
    var U = ui();
    var id = opt.id || "ch-p12";
    var W = opt.width || 720;
    var metric = opt.metric === "effort" ? "effort" : "units";
    var title = "같이 일한 동료";
    var cols = ["번호", "이름", "공동 단위업무", "공유 투입 h", "의뢰", "보고", "대화", "회의"];
    var ps = (spec.peers || spec.internal || []).slice();
    if (!ps.length) { return emptyResult(id, title, "같은 단위업무에 함께 나온 동료가 없습니다.", cols); }
    var LW = 120;
    var R = 120;
    var RH = 24;
    var PW = W - LW - R;
    function val(p) { return metric === "effort" ? (p.shared_effort_min || 0) : (p.units || 0); }
    var mx = Math.max.apply(null, [1].concat(ps.map(val)));
    var kids = [];
    var rows = [];
    ps.forEach(function (p, i) {
      var y = i * RH;
      var w = PW * val(p) / mx;
      var nm = p.name || ("동료 #" + p.k);
      kids.push(text(LW - 8, y + 16, fitText(nm, LW - 12, 13), "t-label", "end"));
      var parts = [hit(LW, y + 4, Math.max(w, 1), 14)];
      if (w > 0) { parts.push(h("path", {d: roundRect(LW, y + 5, w, 14, {tr: 3, br: 3}), "class": "f-blue"})); }
      parts.push(text(LW + w + 6, y + 16, "단위 " + (p.units || 0) + " · " + U.fmtH1(p.shared_effort_min || 0) + "h", "t-value"));
      var rl = p.roles || {};
      var lines = [nm, "공동 단위업무\t" + (p.units || 0), "공유 투입\t" + U.fmtH1(p.shared_effort_min || 0) + "h",
        "의뢰·보고·대화·회의\t" + [rl.requester || 0, rl.reporter || 0, rl.thread || 0, rl.meeting || 0].join("·")];
      kids.push(h("g", mark(lines, "open-peer", p.k), parts));
      rows.push([String(p.k), nm, String(p.units || 0), U.fmtH1(p.shared_effort_min || 0), String(rl.requester || 0),
        String(rl.reporter || 0), String(rl.thread || 0), String(rl.meeting || 0)]);
    });
    var cap = {title: title, summary: "동료 " + ps.length + "명 · 막대 = " + (metric === "effort" ? "공유 투입 h" : "공동 단위업무 수"), notes: []};
    return result(svgRoot(W, ps.length * RH + 4, id, cap, kids), cols, rows, [], cap);
  }

  // ───────────────────────── CH-P13 연관 그래프(방사형) ─────────────────────────
  var NODE_TYPE = {P: "과제", R: "역할", U: "단위업무", D: "문서", A: "앱", C: "동료"};
  var GROUP_OF = {P: "work", R: "work", U: "work", D: "artifact", A: "artifact", C: "person"};
  var GROUP_NAME = {work: "업무", artifact: "산출·도구", person: "사람"};
  var OBSERVED = {"의뢰함": true, "보고함": true, "산출함": true, "사용함": true, "함께함": true};

  function nodeShape(type, x, y, r, cls) {
    if (type === "P") { return rect(x - r, y - r * 0.7, 2 * r, 1.4 * r, {rx: 6, "class": cls}); }
    if (type === "D") { return rect(x - r, y - r, 2 * r, 2 * r, {"class": cls}); }
    if (type === "A") {
      return h("polygon", {points: f1(x) + "," + f1(y - r) + " " + f1(x + r) + "," + f1(y) + " " + f1(x) + "," + f1(y + r) + " " +
        f1(x - r) + "," + f1(y), "class": cls});
    }
    if (type === "C") {
      return h("polygon", {points: f1(x) + "," + f1(y - r) + " " + f1(x + r * 0.95) + "," + f1(y + r * 0.7) + " " +
        f1(x - r * 0.95) + "," + f1(y + r * 0.7), "class": cls});
    }
    return h("circle", {cx: round1(x), cy: round1(y), r: round1(r), "class": cls});
  }

  function radial(spec, opt) {
    opt = opt || {};
    var U = ui();
    var id = opt.id || "ch-p13";
    var W = opt.width || 720;
    var title = "연관 그래프";
    var cols = ["종류", "이름", "무리", "가중 h"];
    var nodes = spec.nodes || [];
    var edges = spec.edges || [];
    if (!nodes.length) { return emptyResult(id, title, "그릴 관계가 없습니다.", cols); }
    var S = Math.min(W, 720);
    var PAD = 110;
    var cx = PAD + S / 2;
    var cy = S / 2 + 10;
    var byId = {};
    nodes.forEach(function (nd) { byId[nd.id] = nd; });
    var center = byId[spec.center] || nodes.filter(function (nd) { return nd.type === "P"; })[0];
    var roleOf = {};
    edges.forEach(function (e) {
      if (e.rel !== "소속") { return; }
      var a = byId[e.from];
      var b = byId[e.to];
      if (a && b && a.type === "U" && b.type === "R") { roleOf[a.id] = b.id; }
      if (a && b && a.type === "R" && b.type === "U") { roleOf[b.id] = a.id; }
    });
    var roles = nodes.filter(function (nd) { return nd.type === "R"; })
      .sort(function (a, b) { return ((b.weight_min || 0) - (a.weight_min || 0)) || cmpStr(a.id, b.id); });
    var rTot = sum(roles, function (r) { return r.weight_min || 0; });
    var ang = {};
    var a0 = -90;
    var segOf = {};
    roles.forEach(function (r) {
      var span = rTot > 0 ? 360 * (r.weight_min || 0) / rTot : 360 / roles.length;
      segOf[r.id] = [a0, span];
      ang[r.id] = a0 + span / 2;
      a0 += span;
    });
    roles.forEach(function (r) {
      var us = nodes.filter(function (nd) { return nd.type === "U" && roleOf[nd.id] === r.id; })
        .sort(function (a, b) { return cmpStr(String(a.start || ""), String(b.start || "")) || cmpStr(a.id, b.id); });
      us.forEach(function (u, i) { ang[u.id] = segOf[r.id][0] + segOf[r.id][1] * (i + 0.5) / us.length; });
    });
    var loose = nodes.filter(function (nd) { return nd.type === "U" && ang[nd.id] === undefined; }).sort(function (a, b) { return cmpStr(a.id, b.id); });
    loose.forEach(function (u, i) { ang[u.id] = -90 + 360 * (i + 0.5) / loose.length; });
    var outer = nodes.filter(function (nd) { return nd.type === "D" || nd.type === "A" || nd.type === "C"; });
    var oa = outer.map(function (o) {
      var sx = 0;
      var sy = 0;
      edges.forEach(function (e) {
        var other = e.from === o.id ? e.to : (e.to === o.id ? e.from : null);
        if (other === null || ang[other] === undefined || !byId[other] || byId[other].type !== "U") { return; }
        var w = e.h || e.w || 1;
        sx += w * Math.cos(ang[other] * Math.PI / 180);
        sy += w * Math.sin(ang[other] * Math.PI / 180);
      });
      var a = (sx === 0 && sy === 0) ? 270 : Math.atan2(sy, sx) * 180 / Math.PI;
      while (a < -90) { a += 360; }
      while (a >= 270) { a -= 360; }
      return {o: o, a: a};
    }).sort(function (p, q) { return (p.a - q.a) || cmpStr(p.o.id, q.o.id); });
    var delta = Math.max(360 / (Math.max(1, oa.length) * 1.2), 7);
    for (var i = 1; i < oa.length; i++) { if (oa[i].a - oa[i - 1].a < delta) { oa[i].a = oa[i - 1].a + delta; } }
    oa.forEach(function (p) { ang[p.o.id] = p.a; });
    function wmax(t) { return Math.max.apply(null, [1].concat(nodes.filter(function (nd) { return nd.type === t; }).map(function (nd) { return nd.weight_min || 0; }))); }
    var wm = {R: wmax("R"), U: wmax("U"), O: Math.max(wmax("D"), wmax("A"), wmax("C"))};
    var P = {};
    nodes.forEach(function (nd) {
      var rad;
      var r;
      if (center && nd.id === center.id) { P[nd.id] = {x: cx, y: cy, r: 22}; return; }
      if (nd.type === "R") { rad = 0.22 * S; r = 10 + 8 * Math.sqrt((nd.weight_min || 0) / wm.R); } else if (nd.type === "U") {
        rad = 0.36 * S; r = 5 + 5 * Math.sqrt((nd.weight_min || 0) / wm.U);
      } else if (nd.type === "P") { rad = 0; r = 22; } else { rad = 0.46 * S; r = 6 + 4 * Math.sqrt((nd.weight_min || 0) / wm.O); }
      var a = (ang[nd.id] === undefined ? -90 : ang[nd.id]) * Math.PI / 180;
      P[nd.id] = {x: cx + rad * Math.cos(a), y: cy + rad * Math.sin(a), r: r, a: a};
    });
    var focus = opt.focus || null;
    var near = {};
    if (focus) {
      near[focus] = true;
      edges.forEach(function (e) { if (e.from === focus) { near[e.to] = true; } if (e.to === focus) { near[e.from] = true; } });
    }
    function dim(idA, idB) { return focus && !(near[idA] && (idB === undefined || near[idB])) ? 0.15 : null; }
    var ew = Math.max.apply(null, [1].concat(edges.map(function (e) { return e.w || 0; })));
    var kids = [];
    var edgeRows = [];
    edges.forEach(function (e) {
      var a = P[e.from];
      var b = P[e.to];
      if (!a || !b) { return; }
      var ta = byId[e.from].type;
      var tb = byId[e.to].type;
      var op = dim(e.from, e.to);
      var inferred = !!e.inferred || (!OBSERVED[e.rel] && e.rel !== "소속");
      if (e.rel === "소속") {
        kids.push(line(a.x, a.y, b.x, b.y, {"class": "s-border-strong", "stroke-width": 1, opacity: op}));
      } else if (ta === "U" && tb === "U") {
        var mx = (a.x + b.x) / 2;
        var my = (a.y + b.y) / 2;
        var qx = cx + (mx - cx) * 0.5;
        var qy = cy + (my - cy) * 0.5;
        kids.push(h("path", {d: "M" + f1(a.x) + " " + f1(a.y) + "Q" + f1(qx) + " " + f1(qy) + " " + f1(b.x) + " " + f1(b.y),
          "class": "s-grp-work", fill: "none", "stroke-width": 1.5, "stroke-dasharray": inferred ? "4 3" : null, opacity: op}));
      } else {
        var og = GROUP_OF[ta === "U" ? tb : ta] || "work";
        kids.push(line(a.x, a.y, b.x, b.y, {"class": "s-grp-" + og, "stroke-width": round1(1 + 3 * (e.w || 0) / ew),
          "stroke-opacity": op === null ? 0.45 : op, "stroke-dasharray": inferred ? "4 3" : null}));
      }
      edgeRows.push([(byId[e.from].label || e.from), e.rel, (byId[e.to].label || e.to), e.h ? U.fmtH1(e.h) : "—", inferred ? "추론" : "관측"]);
    });
    var rows = [];
    var ordered = nodes.slice().sort(function (a, b) { return cmpStr("PRUDAC".indexOf(a.type) + a.id, "PRUDAC".indexOf(b.type) + b.id); });
    ordered.forEach(function (nd) {
      var p = P[nd.id];
      var g = GROUP_OF[nd.type] || "work";
      var parts = [hit(p.x - p.r, p.y - p.r, 2 * p.r, 2 * p.r), nodeShape(nd.type, p.x, p.y, p.r, "f-grp-" + g + " s-surface")];
      var showLabel = nd.type === "P" || nd.type === "R" || nd.type === "D" || nd.type === "A" || nd.type === "C" ||
        opt.selected === nd.id || focus === nd.id;
      if (showLabel) {
        if (nd.type === "P") {
          parts.push(text(p.x, p.y + p.r + 16, ellipsis(nd.label || nd.id, 14), "t-strong", "middle"));
        } else if (nd.type === "R") {
          parts.push(text(p.x, p.y - p.r - 6, ellipsis(nd.label || nd.id, 14), "t-label", "middle"));
        } else if (nd.type === "U") {
          parts.push(text(p.x, p.y - p.r - 4, ellipsis(nd.label || nd.id, 14), "t-axis", "middle"));
        } else {
          var right = Math.cos(p.a) >= 0;
          parts.push(text(p.x + (right ? p.r + 4 : -p.r - 4), p.y + 4, ellipsis(nd.label || nd.id, 14), "t-axis", right ? "start" : "end"));
        }
      }
      var lines = [nd.label || nd.id, "종류\t" + (NODE_TYPE[nd.type] || nd.type)];
      if (typeof nd.weight_min === "number") { lines.push("가중\t" + U.fmtH1(nd.weight_min) + "h"); }
      lines.push(nd.type === "U" ? "누르면 업무 보기" : "누르면 이웃 강조");
      var at = mark(lines, nd.type === "U" ? "open-unit" : "graph-node", nd.id);
      at.opacity = dim(nd.id);
      kids.push(h("g", at, parts));
      rows.push([NODE_TYPE[nd.type] || nd.type, nd.label || nd.id, GROUP_NAME[g], typeof nd.weight_min === "number" ? U.fmtH1(nd.weight_min) : "—"]);
    });
    var cap = {title: title, summary: "노드 " + nodes.length + "개 · 관계 " + edges.length + "개 · 모양 = 노드 종류, 점선 = 추론 관계", notes: []};
    var legend = [{label: "업무(과제·역할·단위업무)", swatch: [h("circle", {cx: 7, cy: 7, r: 5, "class": "f-grp-work"})]},
      {label: "산출·도구(문서 □ · 앱 ◇)", swatch: [h("rect", {x: 2, y: 2, width: 10, height: 10, "class": "f-grp-artifact"})]},
      {label: "사람(동료 △)", swatch: [h("polygon", {points: "7,1 13,12 1,12", "class": "f-grp-person"})]},
      {label: "관측된 관계", swatch: swLine("s-grp-work", null)},
      {label: "추론 관계(선행함·같은문서)", swatch: swLine("s-grp-work", "4 3")}];
    var res = result(svgRoot(S + 2 * PAD, S + 30, id, cap, kids), cols, rows, legend, cap);
    res.tables = [res.table, {cols: ["앞", "관계", "뒤", "h", "근거"], rows: edgeRows}];
    return res;
  }

  // ───────────────────────── CH-P16 하루 24시간 띠 ─────────────────────────
  function dayBand(spec, opt) {
    opt = opt || {};
    var U = ui();
    var id = opt.id || "ch-p16";
    var W = opt.width || 720;
    var title = "하루 24시간";
    var cols = ["시각", "꼬리표", "근거", "대상", "분", "등급", "비고"];
    var dn = spec.d ? dayNum(spec.d) : EPOCH;
    var ivs = spec.intervals || [];
    var labels = spec.labels || {};
    var PADX = 8;
    var PW = W - 2 * PADX;
    function X(m) { return PADX + PW * m / 1440; }
    function dm(v) { var t = toMin(v, dn); return t - (dn - EPOCH) * 1440; }
    var kids = [];
    var win = spec.window || spec.s_eff;
    kids.push(rect(X(0), 16, X(360) - X(0), 10, {"class": "f-night"}));
    kids.push(rect(X(1320), 16, X(1440) - X(1320), 10, {"class": "f-night"}));
    var winA = win ? (Array.isArray(win) ? win[0] : win.start) : null;
    var winB = win ? (Array.isArray(win) ? win[1] : win.end) : null;
    if (winA && winB) {
      var ws = dm(winA);
      var we = dm(winB);
      kids.push(rect(X(ws), 16, X(we) - X(ws), 10, {"class": "f-surface-3"}));
      var lunch = (spec.window && spec.window.lunch) || ["12:00", "13:00"];
      kids.push(rect(X(dm(lunch[0])), 16, X(dm(lunch[1])) - X(dm(lunch[0])), 10, {"class": "f-surface"}));
    }
    for (var hr = 0; hr <= 24; hr += 3) {
      kids.push(line(X(hr * 60), 30, X(hr * 60), 64, {"class": "s-grid", "stroke-width": 1}));
      kids.push(text(X(hr * 60), 80, pad2(hr), "t-axis", hr === 0 ? "start" : (hr === 24 ? "end" : "middle")));
    }
    var rows = [];
    var deduct = false;
    ivs.forEach(function (iv) {
      var a = dm(iv.a);
      var b = dm(iv.b);
      if (!(b > a)) { return; }
      var x = X(a);
      var w = X(b) - x;
      var span = hhmm(a) + "~" + hhmm(b);
      var tagN = TAG_NAME[iv.tag] || iv.tag || "";
      var targets = (iv.targets || []).slice().sort(function (p, q) { return cmpStr(String(p[0]), String(q[0])); });
      if (iv.kind === "deduct" || iv.kind === "excluded" || !targets.length) {
        deduct = true;
        kids.push(h("g", mark([span + " · " + (iv.kind === "excluded" ? "제외" : "차감"), "근거\t" + (iv.basis || "—"), iv.note || ""].filter(Boolean)), [
          rect(x, 32, w, 28, {"class": "f-surface s-st-bad-ink", "stroke-width": 1, "stroke-dasharray": "3 2"}),
          text(x + w / 2, 98, iv.kind === "excluded" ? "제외" : "차감", "t-small", "middle")]));
        rows.push([span, tagN, iv.basis || "", iv.kind === "excluded" ? "제외" : "차감", String(Math.round(b - a)), "—", iv.note || ""]);
        return;
      }
      var tot = sum(targets, function (t) { return t[1] || 0; }) || 1;
      var yy = 32;
      targets.forEach(function (t) {
        var hgt = 28 * (t[1] || 0) / tot;
        var g = t[2];
        var bucket = /^B_/.test(String(t[0])) || g === "X";
        var nm = labels[t[0]] || (bucket ? "근무 중 미분류" : t[0]);
        var parts = [rect(x, yy, w, hgt, {"class": bucket ? "f-unattr" : "f-blue"})];
        if (bucket) { parts.push(hatch(x, yy, w, hgt, "unattr")); } else if (g === "I") { parts.push(hatch(x, yy, w, hgt, "est")); }
        var lines = [span + " · " + tagN, "근거\t" + (iv.basis || "—"), nm + "\t" + (t[1] || 0) + "분 " + ({O: "관측(O)", I: "추정(I)", X: "미분류(X)"}[g] || g || "")];
        if (iv.note) { lines.push(iv.note); }
        var unit = !bucket && /^u_/.test(String(t[0]));
        if (unit) { lines.push("누르면 업무 원장 보기"); }
        kids.push(h("g", mark(lines, unit ? "open-unit" : null, unit ? t[0] : null), [hit(x, yy, w, Math.max(hgt, 4))].concat(parts)));
        rows.push([span, tagN, iv.basis || "", nm, String(t[1] || 0), g || "", iv.note || ""]);
        yy += hgt;
      });
    });
    var cap = {title: title + (spec.d ? " · " + spec.d : ""), summary: "구간 " + ivs.length + "개 · 채움 = 관측, 빗금 = 추정, 회색 빗금 = 미분류", notes: []};
    var legend = [{label: "관측(O)", swatch: swRect({"class": "f-blue"})}, {label: "추정(I)", swatch: swRect({"class": "f-blue"}, "est")},
      {label: "미분류(X)", swatch: swRect({fill: "url(#hatch-unattr)"})}, {label: "정규 구역", swatch: swRect({"class": "f-surface-3"})},
      {label: "야간(22~06)", swatch: swRect({"class": "f-night"})}];
    if (deduct) { legend.push({label: "차감·제외", swatch: swRect({"class": "f-surface s-st-bad-ink", "stroke-dasharray": "3 2"})}); }
    return result(svgRoot(W, deduct ? 106 : 88, id, cap, kids), cols, rows, legend, cap);
  }

  // ───────────────────────── CH-P17 단위업무 등급 분포 ─────────────────────────
  var GRADE_ROWS = ["A", "B", "C", "D", "E", "O", "M"];

  function gradeBars(spec, opt) {
    opt = opt || {};
    var U = ui();
    var id = opt.id || "ch-p17";
    var W = opt.width || 720;
    var title = "단위업무 등급 분포";
    var cols = ["등급", "h", "비중"];
    var g = spec.grades || {};
    var tot = sum(GRADE_ROWS, function (k) { return g[k] || 0; });
    var LW = 72;
    var R = 120;
    var RH = 24;
    var PW = W - LW - R;
    var mx = Math.max.apply(null, [1].concat(GRADE_ROWS.map(function (k) { return g[k] || 0; })));
    var kids = [];
    var rows = [];
    GRADE_ROWS.forEach(function (k, i) {
      var y = i * RH;
      var dash = k === "C" ? "4 2" : ((k === "D" || k === "E") ? "2 2" : null);
      kids.push(rect(4, y + 4, 40, 16, {rx: 4, "class": "f-surface s-ink-2", "stroke-width": 1, "stroke-dasharray": dash}));
      kids.push(text(24, y + 16, k === "O" ? "진행" : (k === "M" ? "수동" : k), "t-label", "middle"));
      var v = g[k] || 0;
      var w = PW * v / mx;
      var parts = [hit(LW, y + 4, Math.max(1, w), 14)];
      if (w > 0) { parts.push(h("path", {d: roundRect(LW, y + 5, w, 14, {tr: 3, br: 3}), "class": "f-blue"})); }
      parts.push(text(LW + w + 6, y + 16, U.fmtH1(v) + "h · " + U.pctText(v, tot), "t-value"));
      kids.push(h("g", mark(["등급 " + k, "투입\t" + U.fmtH1(v) + "h", "비중\t" + U.pctText(v, tot)]), parts));
      rows.push([k, U.fmtH1(v), U.pctText(v, tot)]);
    });
    var Hh = GRADE_ROWS.length * RH + 6;
    if (spec.not_started_n) {
      kids.push(text(4, Hh + 12, "미착수 의뢰 " + spec.not_started_n + "건(투입 0)", "t-small"));
      Hh += 20;
      rows.push(["Z", "0.0", "—"]);
    }
    var cap = {title: title, summary: "투입 " + U.fmtH1(tot) + "h · A·B 실선, C 점선, D·E 짧은 점선 테두리", notes: []};
    return result(svgRoot(W, Hh, id, cap, kids), cols, rows, [], cap);
  }

  // ───────────────────────── CH-T02 월별 업무 영역 투입(팀) ─────────────────────────
  function teamDomainBars(spec, opt) {
    opt = opt || {};
    var U = ui();
    var id = opt.id || "ch-t02";
    var W = opt.width || 900;
    var title = "월별 업무 영역 투입(팀)";
    var months = (spec.months || []).slice().sort();
    var doms = (spec.domains || []).map(function (d, i) { return {d: d, i: i}; })
      .sort(function (a, b) { return (domainRank(a.d.code) - domainRank(b.d.code)) || (a.i - b.i); }).map(function (o) { return o.d; });
    var cols = ["월"].concat(doms.map(function (d) { return d.name || d.code; }), ["미귀속", "자료 없음 인원"]);
    if (!months.length) { return emptyResult(id, title, "팀 묶음이 아직 없습니다.", cols); }
    var people = spec.people || [];
    var weak = {};
    people.forEach(function (p, i) { if (p.quality === "unreliable") { weak[p.i === undefined ? i : p.i] = true; } });
    var un = spec.unattributed || {};
    function unOf(m) {
      if (un.by_month && un.by_month[m] !== undefined) { return typeof un.by_month[m] === "number" ? un.by_month[m] : (un.by_month[m].mm || 0); }
      return typeof un[m] === "number" ? un[m] : 0;
    }
    function noData(m) {
      if (spec.no_data && typeof spec.no_data[m] === "number") { return spec.no_data[m]; }
      var c = 0;
      people.forEach(function (p) {
        if (p.months && !p.months.some(function (x) { return x.m === m; })) { c++; }
      });
      return c;
    }
    var L = 48;
    var R = 24;
    var T = 24;
    var B = 46;
    var PH = 240;
    var PW = W - L - R;
    var band = PW / months.length;
    var bw = Math.max(4, band * 0.7);
    var totals = months.map(function (m) {
      return sum(doms, function (d) { var c = (d.by_month || {})[m]; return c ? (c.mm || 0) : 0; }) + unOf(m);
    });
    var top = niceTop(Math.max(0.1, Math.max.apply(null, totals)), 5);
    var tk = tickList(top, 5);
    var dg = stepDigits(tk.step);
    function y(v) { return T + PH * (1 - v / top); }
    var kids = [];
    tk.list.forEach(function (v) {
      kids.push(line(L, y(v), L + PW, y(v), {"class": v === 0 ? "s-border-strong" : "s-grid", "stroke-width": 1}));
      kids.push(text(L - 6, y(v) + 4, U.fmtNum(v, dg), "t-axis", "end"));
    });
    var rows = [];
    var anyWeak = false;
    months.forEach(function (m, j) {
      var cx = L + band * (j + 0.5);
      var x = cx - bw / 2;
      var acc = 0;
      var parts = [hit(x, T, bw, PH)];
      var lines = [m + " · 팀 " + U.fmtNum(totals[j], 2) + " MM"];
      var row = [m];
      var segs = [];
      doms.forEach(function (d) {
        var c = (d.by_month || {})[m];
        var v = c ? (c.mm || 0) : 0;
        row.push(U.fmtNum(v, 2));
        if (v > 0) { segs.push({d: d, v: v, weak: sum((c.by_person || []).filter(function (p) { return weak[p[0]]; }), function (p) { return p[1]; })}); }
      });
      var uv = unOf(m);
      if (uv > 0) { segs.push({un: true, v: uv, weak: 0}); }
      segs.forEach(function (sg, k) {
        var y0 = y(acc);
        acc += sg.v;
        var y1 = y(acc);
        var isTop = k === segs.length - 1;
        var yt = isTop ? y1 : Math.min(y0, y1 + 2);
        var pa = {d: roundRect(x, yt, bw, y0 - yt, isTop ? {tl: 3, tr: 3} : {})};
        var paint = sg.un ? {fill: "url(#hatch-unattr)"} : domainPaint(sg.d.color);
        Object.keys(paint).forEach(function (p) { pa[p] = paint[p]; });
        parts.push(h("path", pa));
        if (sg.weak > 0) {                                        // 측정 불충분 몫: 조각 위쪽 같은 색 + 빗금
          var wy = y(acc - Math.min(sg.weak, sg.v));
          parts.push(hatch(x, yt, bw, Math.max(0, wy - yt), "est"));
          anyWeak = true;
        }
        lines.push((sg.un ? "미귀속" : (sg.d.name || sg.d.code)) + "\t" + U.fmtNum(sg.v, 2) + " MM" + (sg.weak > 0 ? "(측정 불충분 " + U.fmtNum(sg.weak, 2) + ")" : ""));
      });
      parts.push(text(cx, y(totals[j]) - 6, U.fmtNum(totals[j], 2), "t-value", "middle"));
      var nd = noData(m);
      if (nd > 0) { lines.push("자료 없음\t" + nd + "명"); }
      kids.push(h("g", mark(lines, "drill-team-month", m), parts));
      kids.push(text(cx, T + PH + 16, m, "t-axis", "middle"));
      if (nd > 0) { kids.push(text(cx, T + PH + 32, nd + "명 자료 없음", "t-small", "middle")); }
      row.push(U.fmtNum(uv, 2));
      row.push(String(nd));
      rows.push(row);
    });
    var cap = {title: title, summary: months[0] + " ~ " + months[months.length - 1] + " · 최근 달 팀 " + U.fmtNum(totals[totals.length - 1], 2) + " MM",
      notes: anyWeak ? ["빗금 몫은 측정 불충분 인원 — 합계에는 넣고 비교에서는 뺍니다."] : []};
    var legend = doms.map(function (d) { return {label: d.name || d.code, swatch: swRect(domainPaint(d.color))}; });
    legend.push({label: "미귀속(근무 중 미분류)", swatch: swRect({fill: "url(#hatch-unattr)"})});
    legend.push({label: "측정 불충분 몫", swatch: swRect({"class": "f-faint"}, "est")});
    return result(svgRoot(W, T + PH + B, id, cap, kids), cols, rows, legend, cap);
  }

  // 부록 A 이름 정본(계약 X-281). HTML 표 칸(CH-H02·P14·P15·T07·T09)은 CHARTS 밖 — lm27ui 구성 요소
  var CHARTS = {"CH-H01": coverageHeatmap, "CH-P02": monthlyMM, "CH-P03": dailyBars, "CH-P04": domainShare,
    "CH-P06": gantt, "CH-P07": processMap, "CH-P08": unitTimeline, "CH-P09": gantt, "CH-P10": classMix,
    "CH-P11": leadDots, "CH-P12": peerBars, "CH-P13": radial, "CH-P16": dayBand, "CH-P17": gradeBars,
    "CH-T02": teamDomainBars, "CH-T06": leadDots, "CH-T08": gantt};

  return {
    h: h, toString: toString, round1: round1, CHARTS: CHARTS, patternDefs: patternDefs,
    coverageHeatmap: coverageHeatmap, monthlyMM: monthlyMM, dailyBars: dailyBars, domainShare: domainShare, gantt: gantt,
    processMap: processMap, unitTimeline: unitTimeline, classMix: classMix, leadDots: leadDots, peerBars: peerBars,
    radial: radial, dayBand: dayBand, gradeBars: gradeBars, teamDomainBars: teamDomainBars,
    ganttRows: ganttRows, modelRows: modelRows, treeRows: treeRows,
    densityLevel: densityLevel, lanes: lanes, niceStep: niceStep, tickList: tickList,
    dayNum: dayNum, dateOf: dateOf, isoWeek: isoWeek, weekStart: weekStart, isoWd: isoWd, toMin: toMin, hhmm: hhmm,
    DOMAIN_ORDER: DOMAIN_ORDER, TAGS: TAGS, AXES: AXES, COV_ORDER: COV_ORDER, CLASSES: CLASSES
  };
}));
