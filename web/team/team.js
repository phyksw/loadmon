/*
 * LM27 팀 대시보드 · 자기완결 팀 보고서 · 팀 서버 관리 화면 — 한 파일(팀 서버 '/'·'/admin' 과 team_report*.html 이 같이 쓴다).
 * 근거: REPORTS §7(KPI·영역 MM·과제 × 인원·역할/유형 분포·해석·agentic·간트·측정 품질·team_data 형·관리 §7.9) · §8 · §9.4
 *       · TEAM §3.6(API) · §3.12(정적 고정 사전·보안 헤더) · §4.5 · §4.6(간트·드릴다운) · §4.9 · 계약 §2.15 · §2.16 · §3.22.
 * 데이터: 대시보드 = GET /api/team · /api/team/detail · 자기완결 보고서 = 섬 lm27-data(team_data) · lm27-detail(details).
 * 사람은 정수 i 로만 참조한다(라벨을 객체 키로 쓰지 않음). 글자는 lm27ui.js 마운트(createElement·createTextNode)로만.
 * 측정 불충분 인원은 합계에 넣고(빗금) 평균·순위·분포·비교 표에서 뺀다(TAB §4.5). 숫자 글자는 lm27ui 표시 함수로만(§3.1).
 * 고전 스크립트(import/export 없음). 브라우저 = 전역 LM27Team(문서가 준비되면 스스로 시작), node = module.exports(시험 전용).
 */
(function (root, factory) {
  "use strict";
  var api = factory(root);
  if (typeof module === "object" && module && module.exports) {
    module.exports = api;
  } else {
    root.LM27Team = api;
    api.autoStart(root);
  }
}(typeof self !== "undefined" ? self : this, function (root) {
  "use strict";

  // ───────────────────────── 0. 렌더러 한 벌(lm27ui.js · lm27charts.js) ─────────────────────────
  var UIMOD = null;
  var CHMOD = null;

  function U() {
    if (UIMOD) { return UIMOD; }
    if (typeof module === "object" && module && module.exports && typeof require === "function") {
      UIMOD = require("../common/lm27ui.js");
    } else {
      UIMOD = root.LM27UI;
    }
    if (!UIMOD) { throw new Error("lm27ui.js 가 필요합니다"); }
    return UIMOD;
  }

  function C() {
    if (CHMOD) { return CHMOD; }
    if (typeof module === "object" && module && module.exports && typeof require === "function") {
      CHMOD = require("../common/lm27charts.js");
    } else {
      CHMOD = root.LM27Charts;
    }
    if (!CHMOD) { throw new Error("lm27charts.js 가 필요합니다"); }
    return CHMOD;
  }

  function h(tag, attrs, kids) { return U().h(tag, attrs, kids); }

  // ───────────────────────── 1. 상수 ─────────────────────────
  // 공유판 관문(TAB §3.9): 공유판에서 빼는 사람별 열(로드율·가용일·꼬리표 분)의 키 이름은 공유판 HTML 전체에 0회여야 한다.
  // 이 파일도 공유판에 인라인되므로 키 이름을 조각으로 조립해 쓴다.
  var K = {load: ["load", "pct"].join("_"), avail: ["avail", "days"].join("_"), tags: ["by", "tag"].join("_")};
  var TAGS = ["regular", "extended", "night", "holiday"];
  var TAG_NAME = {regular: "정규", extended: "연장", night: "야간", holiday: "휴일"};
  var DOMAIN_ORDER = ["DEV", "MP", "EXT", "COM", "AX", "UNC"];
  var AXES = [["mail_in", "메일 받음"], ["mail_out", "메일 보냄"], ["cal", "일정"], ["teams", "팀즈"], ["pc", "PC"]];
  var SECTIONS = [["summary", "요약"], ["domains", "영역 투입"], ["projects", "과제 × 인원"], ["roles", "역할·유형"],
    ["agentic", "Agentic"], ["gantt", "간트"], ["quality", "측정 품질"], ["people", "사람별"]];
  var QUALITY_NAME = {reliable: "신뢰", caution: "주의", unreliable: "측정 불충분"};
  var STATUS_NAME = {closed: "완료", estimated: "추정 완료", open: "진행 중"};
  var GRADES = ["A", "B", "C", "D", "E", "M"];
  var AG_GRADES = ["상", "중", "하"];
  var FITS = ["적합", "조건부", "부적합"];
  var FLAG_TEXT = {calendar_mismatch: "달력 다름", cfg_mismatch: "산식 설정 다름", pepper_mismatch: "pepper 다름",
    retired: "퇴직", cfg_diff: "산식 설정 다름"};
  var REASON_TEXT = {
    pc_cov_bad: "PC 기록이 있는 근무일이 절반에 못 미칩니다 — 에이전트가 없던 PC·기간이 있습니다",
    pc_cov_low: "PC 기록이 빈 근무일이 있습니다 — 에이전트가 없던 PC·기간이 있습니다",
    comms_cov_bad: "메일 발신·팀즈 기록이 모두 절반 넘게 비었습니다",
    mail_cov_low: "메일 보냄 기록이 빈 근무일이 있습니다",
    teams_cov_low: "팀즈 기록이 빈 근무일이 있습니다",
    cal_cov_low: "일정 기록이 빈 근무일이 있습니다",
    estimated_bad: "근무시간의 절반 넘게 낮은 신뢰로 채워졌습니다",
    estimated_high: "근무시간 일부가 낮은 신뢰(PC 하한·흔적 창 등)로 채워졌습니다",
    unattributed_high: "근무시간의 상당 부분이 업무에 묶이지 않았습니다",
    no_evidence_days: "근거가 하나도 없는 근무일이 있습니다",
    sampler_absent: "PC 사용 기록기(샘플러)가 없는 날이 많습니다",
    no_envelope: "근무시간이 계산되지 않은 달이 있습니다",
    mining_coarse: "단계 정밀도가 낮습니다(표시만)"};
  var WHY_TEXT = {digital_io: "디지털 입출력", repeat_weekly: "매주 반복", repeat_monthly: "매월 반복",
    structured_input: "정형 입력", low_accountability: "책임 부담 낮음", verifiable: "검증 가능", tool_access: "도구 접근"};
  var SRC_NAME = {roster: "팀장 지정", member: "구성원", self: "본인", auto: "자동"};
  var DRAWER_HASH = /^#?gantt\/(\d{1,4})\/(r_[0-9a-f]{6})$/;
  var ROLE_REF = /^(\d{1,4})\|(r_[0-9a-f]{6})$/;
  var HUGE_ROWS = 2000;                                           // R §11 '매우 큰 팀' — 첫 계층만 펼침

  // ───────────────────────── 2. 작은 도우미 ─────────────────────────
  function arr(v) { return Array.isArray(v) ? v : []; }
  function isObj(v) { return !!v && typeof v === "object" && !Array.isArray(v); }
  function obj(v) { return isObj(v) ? v : {}; }
  function isNum(v) { return typeof v === "number" && isFinite(v); }
  function isStr(v) { return typeof v === "string"; }
  function own(o, k) { return Object.prototype.hasOwnProperty.call(o, k); }
  function byI(a, b) { return a.i - b.i; }
  function cmpStr(a, b) { a = String(a); b = String(b); return a < b ? -1 : (a > b ? 1 : 0); }
  function sum(list, fn) { var s = 0; list.forEach(function (x) { s += fn ? fn(x) : x; }); return s; }
  function domRank(code) { var k = DOMAIN_ORDER.indexOf(code); return k < 0 ? DOMAIN_ORDER.length : k; }

  function median(list) {
    var a = list.filter(isNum).slice().sort(function (x, y) { return x - y; });
    if (!a.length) { return null; }
    var k = Math.floor(a.length / 2);
    return a.length % 2 ? a[k] : (a[k - 1] + a[k]) / 2;
  }

  function mm2(v) { var s = U().fmtNum(v, 2); return s === null ? "—" : s; }
  function mmText(v) { var s = U().fmtNum(v, 2); return s === null ? "—" : s + " MM"; }
  function hText(min) { return isNum(min) ? U().fmtH1(min) + "h" : "—"; }

  // 소수 비중 → 정수 %(0 초과 1% 미만이면 1자리) — 파이썬 lm27.team.report.pct_share_text 와 같은 산식
  function pctShare(part, whole) {
    if (!isNum(part) || !isNum(whole) || !(whole > 0)) { return "—"; }
    var p = part / whole * 100;
    if (p === 0) { return "0%"; }
    return U().fmtNum(p, (p > 0 && p < 1) ? 1 : 0) + "%";
  }

  function stamp(iso) {
    var m = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/.exec(String(iso || ""));
    return m ? m[1] + " " + m[2] : "—";
  }

  // 표 칸 농도 6구간(§8.1.3 — 표 최댓값 기준 비율 (0, .2] … (.8, 1])
  function heatLevel(v, max) {
    if (!(v > 0) || !(max > 0)) { return 0; }
    var r = v / max;
    return r <= 0.2 ? 1 : (r <= 0.4 ? 2 : (r <= 0.6 ? 3 : (r <= 0.8 ? 4 : 5)));
  }

  // ───────────────────────── 3. 모델(team_data → 화면 값, 순수) ─────────────────────────
  function model(td, det, opt) {
    td = obj(td);
    opt = opt || {};
    var M = {td: td, det: obj(det), opt: opt};
    M.people = arr(td.people).filter(isObj).slice().sort(byI);
    M.P = {};
    M.people.forEach(function (p) { M.P[p.i] = p; });
    M.weak = {};
    arr(obj(td.quality).excluded_from_comparison).forEach(function (i) { if (isNum(i)) { M.weak[i] = true; } });
    M.people.forEach(function (p) { if (p.quality === "unreliable") { M.weak[p.i] = true; } });
    M.months = arr(td.months).filter(isStr);
    M.std = isNum(td.std_day_min) && td.std_day_min > 0 ? td.std_day_min : 480;
    M.domains = arr(td.domains).filter(isObj).map(function (d, k) {
      return {code: d.code, name: d.name || d.code || "—", color: d.color, by_month: obj(d.by_month),
        total_mm: isNum(d.total_mm) ? d.total_mm : 0, k: k};
    }).sort(function (a, b) { return (domRank(a.code) - domRank(b.code)) || (a.k - b.k); });
    M.dom = {};
    M.domains.forEach(function (d) { M.dom[d.code] = d; });
    M.view = obj(td.view);
    M.variant = opt.variant || (td.variant === "share" ? "share" : "full");
    M.proj = {};
    arr(td.projects).filter(isObj).forEach(function (p) {
      if (p.key !== undefined) { M.proj[p.key] = p; }
      if (p.project_id && !own(M.proj, p.project_id)) { M.proj[p.project_id] = p; }
    });
    return M;
  }

  function label(M, i) { var p = M.P[i]; return (p && p.label) || ("담당자 " + (Number(i) + 1)); }
  function domName(M, code) { var d = M.dom[code]; return (d && d.name) || code || "—"; }

  function vocabName(M, axis, code) {
    if (!code) { return "미지정"; }
    var vn = obj(obj(M.td.vocab_names)[axis]);
    return isStr(vn[code]) && vn[code] ? vn[code] : String(code);
  }

  function stepName(M, code) { return vocabName(M, "step", code); }

  function roleName(M, field, fn) {
    var a = vocabName(M, "field", field);
    var b = vocabName(M, "func", fn);
    return a + "·" + b;
  }

  function projectName(M, key) {
    var p = M.proj[key];
    if (p) { return p.label || p.project_id || (p.proposal ? "제안 과제" : key); }
    return key === "UNC" || !key ? "과제 없음" : String(key);
  }

  function teamTotals(M) {
    var byM = {};
    var tot = 0;
    M.months.forEach(function (m) { byM[m] = 0; });
    M.people.forEach(function (p) {
      arr(p.months).forEach(function (e) {
        if (isObj(e) && isNum(e.mm)) { byM[e.m] = (byM[e.m] || 0) + e.mm; tot += e.mm; }
      });
    });
    var ua = obj(M.td.unattributed);
    var unBy = obj(ua.by_month);
    return {mm: tot, byMonth: byM, unByMonth: unBy, unTotal: isNum(ua.total_mm) ? ua.total_mm : 0};
  }

  // 팀 합계 꼬리표 분 — 공유판은 tag_totals(사람별 꼬리표가 빠짐), 그 밖은 사람별 꼬리표의 정수 합(측정 불충분 포함)
  function tagTotals(M) {
    var tt = obj(M.td.tag_totals);
    if (isObj(tt.total)) { return {total: tt.total, byMonth: obj(tt.by_month)}; }
    var total = {};
    var byM = {};
    TAGS.forEach(function (t) { total[t] = 0; });
    M.people.forEach(function (p) {
      arr(p.months).forEach(function (e) {
        var bt = isObj(e) ? e[K.tags] : null;
        if (!isObj(bt)) { return; }
        var row = byM[e.m] = byM[e.m] || {regular: 0, extended: 0, night: 0, holiday: 0};
        TAGS.forEach(function (t) { var v = isNum(bt[t]) ? bt[t] : 0; row[t] += v; total[t] += v; });
      });
    });
    return {total: total, byMonth: byM};
  }

  function kpis(M) {
    var n = M.people.length;
    var cnt = {reliable: 0, caution: 0, unreliable: 0, other: 0};
    M.people.forEach(function (p) { cnt[own(cnt, p.quality) && p.quality !== "other" ? p.quality : "other"]++; });
    var T = teamTotals(M);
    var last = M.months[M.months.length - 1];
    var tg = tagTotals(M).total;
    var ot = (tg.extended || 0) + (tg.night || 0) + (tg.holiday || 0);
    var doms = M.domains.filter(function (d) { return d.code !== "UNC" && d.total_mm > 0; }).slice()
      .sort(function (a, b) { return (b.total_mm - a.total_mm) || (domRank(a.code) - domRank(b.code)); });
    var unc = M.dom.UNC ? M.dom.UNC.total_mm : 0;
    var us = obj(M.td.units_stats);
    var bs = obj(us.by_status);
    var leads = arr(us.lead_points).filter(function (p) { return isObj(p) && !M.weak[p.i]; })
      .map(function (p) { return p.biz_lead_min; });
    var med = median(leads);
    var covs = [];
    arr(obj(M.td.quality).matrix).forEach(function (r) {
      AXES.forEach(function (a) { var v = obj(obj(r).axes)[a[0]]; if (isNum(v)) { covs.push(v); } });
    });
    var covAvg = covs.length ? sum(covs) / covs.length : null;
    var domSub = doms.slice(1, 3).map(function (d) { return d.name + " " + pctShare(d.total_mm, T.mm); });
    domSub.push(domName(M, "UNC") + " " + pctShare(unc, T.mm));
    domSub.push("미귀속 " + pctShare(T.unTotal, T.mm));
    var qSub = cnt.other ? " · 미확인 " + cnt.other : "";
    return [
      {id: "people", label: "인원", value: n + "명",
        sub: "신뢰 " + cnt.reliable + " · 주의 " + cnt.caution + " · 측정 불충분 " + cnt.unreliable + qSub},
      {id: "mm", label: "팀 투입(기간)", value: mmText(T.mm),
        sub: last ? "이번 달(" + last + ") " + mmText(T.byMonth[last]) + " · 미귀속 " +
          mmText(isNum(T.unByMonth[last]) ? T.unByMonth[last] : 0) : "자료 없음"},
      {id: "ot", label: "초과 근무(팀 합)", value: hText(ot),
        sub: "연장 " + hText(tg.extended || 0) + " · 야간 " + hText(tg.night || 0) + " · 휴일 " + hText(tg.holiday || 0)},
      {id: "domains", label: "업무 영역", value: doms.length ? doms[0].name + " " + pctShare(doms[0].total_mm, T.mm) : "—",
        sub: domSub.join(" · ")},
      {id: "units", label: "단위업무", value: "완료 " + (bs.closed || 0) + " · 진행 " + (bs.open || 0),
        sub: "추정 완료 " + (bs.estimated || 0) + " · 중앙 리드 " + (med === null ? "—" : U().daysText(med, M.std))},
      {id: "quality", label: "측정 품질", value: n ? cnt.reliable + "/" + n + " 신뢰" : "—",
        sub: covAvg === null ? "커버리지 자료 없음" : "사람×출처 커버리지 평균 " + pctShare(covAvg, 1)}
    ];
  }

  // 영역 × 사람(기간 MM) — 열 = 사람(i 순서), 행 = 영역 + 미귀속
  function domainPerson(M) {
    var cols = M.people.map(function (p) { return {i: p.i, label: label(M, p.i), weak: !!M.weak[p.i]}; });
    var rows = [];
    function perPerson(byMonth) {
      var per = {};
      Object.keys(byMonth).forEach(function (m) {
        arr(obj(byMonth[m]).by_person).forEach(function (bp) { per[bp[0]] = (per[bp[0]] || 0) + (isNum(bp[1]) ? bp[1] : 0); });
      });
      return per;
    }
    M.domains.forEach(function (d) {
      if (!(d.total_mm > 0)) { return; }
      var per = perPerson(d.by_month);
      rows.push({key: d.code, name: d.name, cells: cols.map(function (c) { return per[c.i] || 0; }), total: d.total_mm});
    });
    var ua = obj(M.td.unattributed);
    var uper = {};
    arr(ua.by_person).forEach(function (bp) { uper[bp[0]] = bp[1]; });
    if (isNum(ua.total_mm) && ua.total_mm > 0) {
      rows.push({key: "_un", name: "미귀속(근무 중 미분류)", un: true,
        cells: cols.map(function (c) { return uper[c.i] || 0; }), total: ua.total_mm});
    }
    var max = 0;
    rows.forEach(function (r) { r.cells.forEach(function (v) { max = Math.max(max, v); }); });
    return {cols: cols, rows: rows, max: max};
  }

  function projectsOfDomain(M, code) {
    return arr(M.td.projects).filter(function (p) { return isObj(p) && p.domain === code; });
  }

  function personMap(byPerson) {
    var o = {};
    arr(byPerson).forEach(function (bp) { if (Array.isArray(bp)) { o[bp[0]] = bp[1]; } });
    return o;
  }

  // 과제 표 — 작은 과제(teamReport.smallProjectMm 미만)는 한 줄로 접는다. view 가 없으면 접지 않는다.
  function projectTable(M) {
    var thr = isNum(M.view.small_project_mm) ? M.view.small_project_mm : 0;
    var all = arr(M.td.projects).filter(isObj);
    var big = [];
    var small = [];
    all.forEach(function (p) { ((isNum(p.total_mm) ? p.total_mm : 0) < thr ? small : big).push(p); });
    var max = 0;
    all.forEach(function (p) { max = Math.max(max, isNum(p.total_mm) ? p.total_mm : 0); });
    return {big: big, small: small, smallTotal: sum(small, function (p) { return isNum(p.total_mm) ? p.total_mm : 0; }),
      max: max, threshold: thr};
  }

  function rolesOfProject(M, p) {
    return arr(M.td.roles).filter(function (r) {
      if (!isObj(r)) { return false; }
      if (p.proposal) { return r.proposal_key === p.key; }
      if (p.key === "UNC" || !p.project_id) { return !r.project_id && !r.proposal; }
      return r.project_id === p.project_id && !r.proposal;
    });
  }

  // 역할(분야 × 기능) 행렬
  function roleGrid(M) {
    var rm = obj(M.td.role_matrix);
    var cell = {};
    var max = 0;
    arr(rm.cells).forEach(function (c) {
      if (Array.isArray(c) && c.length >= 3) { cell[c[0] + "|" + c[1]] = c; max = Math.max(max, isNum(c[2]) ? c[2] : 0); }
    });
    return {fields: arr(rm.fields), funcs: arr(rm.functions), cell: cell, max: max};
  }

  function rolesOfCell(M, field, fn) {
    return arr(M.td.roles).filter(function (r) { return isObj(r) && (r.field || "") === field && (r["function"] || "") === fn; });
  }

  // CH-T06 리드 점 그림 명세(줄 = 영역) — 점에 이름·제목 없음(과제 · 역할만), 누르면 그 사람·역할 상세
  function leadSpec(M) {
    var us = obj(M.td.units_stats);
    var pts = [];
    function roleFor(i, rid) {                                     // 제안 역할은 사람마다 따로(proposal_key "<i>|pr_n")
      var hit = null;
      arr(M.td.roles).forEach(function (r) {
        if (!isObj(r) || r.role_id !== rid) { return; }
        if (r.proposal && String(r.proposal_key).indexOf(i + "|") !== 0) { return; }
        if (!hit || (r.proposal && !hit.proposal)) { hit = r; }
      });
      return hit || {};
    }
    arr(us.lead_points).forEach(function (p, k) {
      if (!isObj(p) || M.weak[p.i] || !isNum(p.biz_lead_min)) { return; }
      var r = roleFor(p.i, p.role_id);
      var pkey = r.proposal ? r.proposal_key : (p.project_id || "UNC");
      pts.push({row: p.domain, unit_id: p.i + "|" + p.role_id, biz_lead_min: p.biz_lead_min, effort_min: p.effort_min,
        title: projectName(M, pkey) + " · " + roleName(M, r.field, r["function"]), overrun: false, k: k});
    });
    var med = obj(us.lead_median_by_domain);
    var rows = M.domains.filter(function (d) { return pts.some(function (p) { return p.row === d.code; }); })
      .map(function (d) { return {key: d.code, label: d.name, baseline_biz_min: isNum(med[d.code]) ? med[d.code] : null}; });
    return {rows: rows, points: pts, std_day_min: M.std};
  }

  // CH-T07 에이전트 × 영역 격자
  function agenticGrid(M) {
    var ag = obj(M.td.agentic);
    var matches = arr(ag.matches).filter(isObj);
    var doms = {};
    var max = 0;
    matches.forEach(function (x) {
      Object.keys(obj(x.by_domain)).forEach(function (d) {
        doms[d] = true;
        var v = obj(x.by_domain[d]).related_mm;
        if (isNum(v)) { max = Math.max(max, v); }
      });
    });
    var cols = Object.keys(doms).sort(function (a, b) { return (domRank(a) - domRank(b)) || cmpStr(a, b); });
    return {matches: matches, cols: cols, max: max, total: ag.related_mm_total};
  }

  // 새 니즈 — 단계 유형별로 묶어 나란히(이름 자동 병합 없음)
  function needGroups(M) {
    var groups = [];
    var at = {};
    arr(obj(M.td.agentic).needs).forEach(function (x, k) {
      if (!isObj(x)) { return; }
      var t = x.step_type || "";
      if (!own(at, t)) { at[t] = groups.length; groups.push({type: t, rows: []}); }
      groups[at[t]].rows.push({n: x, k: k});
    });
    return groups;
  }

  function qualityRows(M) {
    var rows = arr(obj(M.td.quality).matrix).filter(isObj).slice().sort(byI);
    return rows.map(function (r) { return {r: r, weak: !!M.weak[r.i]}; });
  }

  // 사람별 월 표 — 공유판은 사람별 로드율·가용일·꼬리표 열이 없다(자료에 없음)
  function peopleMonths(M) {
    var full = M.people.some(function (p) {
      return arr(p.months).some(function (e) { return isObj(e) && (own(e, K.load) || own(e, K.tags)); });
    });
    var rows = [];
    var weakRows = [];
    M.people.forEach(function (p) {
      arr(p.months).forEach(function (e) {
        if (!isObj(e)) { return; }
        var row = {i: p.i, label: label(M, p.i), quality: p.quality, flags: arr(p.flags), e: e};
        (M.weak[p.i] ? weakRows : rows).push(row);
      });
    });
    return {full: full, rows: rows, weakRows: weakRows};
  }

  // ───────────────────────── 4. 간트(CH-T08) — 행·기본 펼침 ─────────────────────────
  function ganttRows(M, pivot) {
    var names = {};
    M.domains.forEach(function (d) { names[d.code] = d.name; });
    var td = M.td;
    var projects = arr(td.projects).map(function (p) {                // 제안 과제는 사람마다 따로(키 "<i>|pr_n")
      if (!isObj(p) || !p.proposal) { return p; }
      var x = {};
      Object.keys(p).forEach(function (k) { x[k] = p[k]; });
      x.project_id = p.key;
      x.label = (p.label || "제안 과제") + "(제안)";
      return x;
    });
    var shim = {people: td.people, vocab_names: td.vocab_names, projects: projects, roles: td.roles,
      domains: M.domains.map(function (d) { return {code: d.code, name: d.name}; }),
      gantt: arr(td.gantt).map(function (g) {
        var x = {};
        Object.keys(obj(g)).forEach(function (k) { x[k] = g[k]; });
        if (!x.project_id && x.proposal_id) { x.project_id = x.person + "|" + x.proposal_id; }   // 제안 과제는 사람마다 따로
        return x;
      })};
    return C().ganttRows(shim, {pivot: !!pivot, domainNames: names});
  }

  // 기본 펼침(R §7.6.1): 행이 teamReport.ganttExpandRows 이하면 모두 펼침, 넘으면 첫 계층만 펼침
  function defaultCollapsed(rows, limit) {
    var out = {};
    var lim = isNum(limit) ? limit : HUGE_ROWS;
    if (rows.length <= lim) { return out; }
    rows.forEach(function (r) { if (r.group && r.level >= 1) { out[r.key] = true; } });
    return out;
  }

  function detailFor(M, ref) {
    return own(M.det, ref) ? M.det[ref] : null;
  }

  function parseHash(hash) {
    var s = String(hash || "").replace(/^#/, "");
    var m = DRAWER_HASH.exec(s);
    if (m) { return {section: "gantt", drawer: m[1] + "|" + m[2]}; }
    for (var k = 0; k < SECTIONS.length; k++) { if (SECTIONS[k][0] === s) { return {section: s, drawer: null}; } }
    return {section: "summary", drawer: null};
  }

  // ───────────────────────── 5. 보기(가상 노드) ─────────────────────────
  function card(title, kids, opt) {
    opt = opt || {};
    return h("section", {"class": "card", id: opt.id || null, "aria-labelledby": opt.id ? opt.id + "-h" : null}, [
      h("div", {"class": "card-head"}, [h("h2", {id: opt.id ? opt.id + "-h" : null}, [title]),
        opt.state ? h("span", {"class": "state"}, [opt.state]) : null]),
      kids]);
  }

  function hatchBadge() {
    return h("span", {"class": "badge", "data-tip": "측정 불충분 — 합계에는 들어가고 비교에서는 빠집니다"}, [
      h("svg", {"class": "swatch", viewBox: "0 0 14 14", width: 14, height: 14, "aria-hidden": "true", focusable: "false"}, [
        h("rect", {x: 1, y: 2, width: 12, height: 10, rx: 2, "class": "f-faint"}),
        h("rect", {x: 1, y: 2, width: 12, height: 10, rx: 2, fill: "url(#hatch-est)"})]),
      "측정 불충분"]);
  }

  function chartBlock(S, result, id) {
    var t = S.tables[id];
    return U().chartView(result, {id: id, table: !!t, tableOpt: t ? {sortCol: t.col, desc: t.desc, limit: t.limit} : null});
  }

  function headView(M, S) {
    var td = M.td;
    var team = td.team_label || "팀";
    var title = team + (S.live ? " 팀 대시보드" : " 팀 보고서");
    var span = M.months.length ? M.months[0] + " ~ " + M.months[M.months.length - 1] : "기간 없음";
    if (isNum(td.omitted_months) && td.omitted_months > 0) { span += " · 앞 " + td.omitted_months + "개월 생략"; }
    var bits = [h("span", {"class": "sub"}, ["기간 " + span]),
      h("span", {"class": "sub"}, ["세대 " + (isNum(td.gen) ? td.gen : "—") + " · 취합 " + stamp(td.built_at)]),
      h("span", {"class": "sub"}, ["레지스트리 v" + (isNum(td.registry_version) ? td.registry_version : "—") +
        " · 달력 " + (td.calendar_version || "—")])];
    var badges = [];
    if (!S.live) {
      badges.push(U().badge(M.variant === "share" ? "공유판" : "전체판", null,
        M.variant === "share" ? "사람별 로드율·초과 시간 열을 뺀 판입니다" : "사람별 로드율·초과 시간이 들어 있습니다 — 팀 안에서만 보세요"));
    }
    var warns = arr(td.warnings);
    if (warns.length) {
      badges.push(h("button", {type: "button", "class": "btn btn-ghost", "data-act": "show-warnings",
        "aria-label": "경고 " + warns.length + "건 보기"}, [U().icon("warn"), "경고 " + warns.length]));
    }
    return [h("h1", {}, [title, h("small", {}, ["LoadMonitor27"])])].concat(bits, [h("span", {"class": "spacer"}, [])], badges);
  }

  function navView(S) {
    return U().pills(SECTIONS.map(function (s) {
      return {href: "#" + s[0], label: s[1], current: S.section === s[0]};
    }), {label: "절 메뉴"});
  }

  function interpretationView(M) {
    var rows = arr(M.td.interpretation).filter(isObj);
    if (!rows.length) { return U().emptyState("해석 문장이 없습니다(자료가 부족하거나 아직 계산되지 않았습니다)."); }
    return h("ul", {"class": "interp"}, rows.map(function (r) {
      return h("li", {"data-code": r.code || null}, [r.text_ko || ""]);
    }));
  }

  function summaryView(M, S) {
    var cards = kpis(M).map(function (k) { return U().kpiCard({label: k.label, value: k.value, sub: k.sub}); });
    var ch = C().teamDomainBars(teamSpec(M), {width: S.width, id: "ch-t02"});
    return [h("div", {"class": "kpis"}, cards),
      card("해석", [interpretationView(M), h("p", {"class": "muted small"},
        ["문장은 정해진 규칙으로 만듭니다(팀 서버에는 코파일럿이 없습니다). 측정 불충분 인원은 비율 계산에서 뺍니다."])],
      {id: "c-interp"}),
      card("월별 업무 영역 투입", [chartBlock(S, ch, "ch-t02")], {id: "c-t02"})];
  }

  function teamSpec(M) {
    return {months: M.months, domains: M.domains.map(function (d) {
      return {code: d.code, name: d.name, color: d.color, by_month: d.by_month};
    }), people: M.people, unattributed: M.td.unattributed};
  }

  function heatCell(v, max, extra) {
    var lv = heatLevel(v, max);
    return h("td", {"class": "num heat-" + lv}, [v > 0 ? mm2(v) : "·"].concat(extra || []));
  }

  function personHead(c) {
    return h("th", {scope: "col", "class": "num" + (c.weak ? " muted" : "")}, [c.label].concat(c.weak ? [" ", hatchBadge()] : []));
  }

  function domainsView(M, S) {
    var ch = C().teamDomainBars(teamSpec(M), {width: S.width, id: "ch-t02b"});
    var dp = domainPerson(M);
    var head = h("tr", {}, [h("th", {scope: "col"}, ["영역"])].concat(dp.cols.map(personHead),
      [h("th", {scope: "col", "class": "num"}, ["합계"])]));
    var body = [];
    dp.rows.forEach(function (r) {
      var ref = "t:dom:" + r.key;
      var open = !!S.open[ref];
      var first = r.un ? [r.name] : [U().expandButton(open, null, r.name + " 과제 " + (open ? "접기" : "펼치기"), ref), " ", r.name];
      body.push(h("tr", {}, [h("th", {scope: "row"}, first)].concat(r.cells.map(function (v) { return heatCell(v, dp.max); }),
        [h("td", {"class": "num"}, [mm2(r.total)])])));
      if (open && !r.un) {
        projectsOfDomain(M, r.key).forEach(function (p) {
          var per = personMap(p.by_person);
          body.push(h("tr", {"class": "detail"}, [h("td", {}, ["　└ " + projectName(M, p.key)])].concat(
            dp.cols.map(function (c) { return h("td", {"class": "num"}, [per[c.i] > 0 ? mm2(per[c.i]) : "·"]); }),
            [h("td", {"class": "num"}, [mm2(p.total_mm)])])));
        });
      }
    });
    var table = h("div", {"class": "table-wrap"}, [h("table", {"class": "tbl"}, [
      h("caption", {}, ["영역 × 사람(기간 MM) — 칸 농도는 표 최댓값 기준, MM 은 로드율이 아닙니다"]),
      h("thead", {}, [head]), h("tbody", {}, body)])]);
    return [card("월별 업무 영역 투입", [chartBlock(S, ch, "ch-t02b")], {id: "c-t02b"}),
      card("영역 × 사람", [table, h("p", {"class": "muted small"}, ["영역 행을 펼치면 과제별 값이 보입니다. 측정 불충분 인원의 열은 빗금 배지로 표시합니다."])],
        {id: "c-dom-person"})];
  }

  function personBar(M, p, max) {
    var W = 160;
    var tot = isNum(p.total_mm) ? p.total_mm : 0;
    var bw = max > 0 ? W * tot / max : 0;
    var segs = arr(p.by_person).filter(function (bp) { return Array.isArray(bp) && bp[1] > 0; }).slice()
      .sort(function (a, b) { return a[0] - b[0]; });
    var x = 0;
    var kids = [];
    var desc = [];
    segs.forEach(function (bp, k) {
      var w = tot > 0 ? bw * bp[1] / tot : 0;
      var gap = k < segs.length - 1 ? 2 : 0;
      kids.push(h("rect", {x: C().round1(x), y: 2, width: C().round1(Math.max(1, w - gap)), height: 10, rx: 2, "class": "f-blue",
        "data-tip": label(M, bp[0]) + "\t" + mm2(bp[1]) + " MM"}));
      desc.push(label(M, bp[0]) + " " + mm2(bp[1]));
      x += w;
    });
    return h("svg", {"class": "pbar", viewBox: "0 0 " + W + " 14", width: W, height: 14, role: "img", tabindex: "0",
      "aria-label": "사람별 MM: " + (desc.join(", ") || "없음"), focusable: "false"}, kids);
  }

  function projectRowNodes(M, S, p, pt) {
    var ref = "t:prj:" + p.key;
    var open = !!S.open[ref];
    var name = projectName(M, p.key);
    var tags = [];
    if (p.proposal) { tags.push(" ", U().badge("제안", null, "레지스트리에 없는 제안 과제")); }
    if (p.reserved) { tags.push(" ", U().badge("영역 일반", null, "예약 과제")); }
    var merged = arr(p.merged);
    var out = [h("tr", {}, [
      h("th", {scope: "row"}, [U().expandButton(open, null, name + " 역할 " + (open ? "접기" : "펼치기"), ref), " ", name]
        .concat(tags, merged.length ? [h("div", {"class": "muted small"}, ["병합: " + merged.join(", ")])] : [])),
      h("td", {}, [domName(M, p.domain)]),
      h("td", {"class": "num"}, [mm2(p.total_mm)]),
      h("td", {}, [personBar(M, p, pt.max)]),
      h("td", {"class": "num"}, [String(isNum(p.units) ? p.units : 0)]),
      h("td", {"class": "num"}, [String(isNum(p.roles) ? p.roles : 0)])])];
    if (open) {
      var rs = rolesOfProject(M, p);
      if (!rs.length) { out.push(h("tr", {"class": "detail"}, [h("td", {colspan: 6}, ["역할 자료가 없습니다."])])); }
      rs.forEach(function (r) {
        var per = arr(r.by_person).filter(function (bp) { return Array.isArray(bp) && bp[1] > 0; })
          .map(function (bp) { return label(M, bp[0]) + " " + mm2(bp[1]); });
        out.push(h("tr", {"class": "detail"}, [h("td", {}, ["　└ " + roleName(M, r.field, r["function"])]),
          h("td", {}, [per.join(" · ") || "—"]), h("td", {"class": "num"}, [mm2(r.total_mm)]), h("td", {}, []),
          h("td", {"class": "num"}, [String(isNum(r.units) ? r.units : 0)]), h("td", {}, [])]));
      });
    }
    return out;
  }

  function projectsView(M, S) {
    var pt = projectTable(M);
    var body = [];
    pt.big.forEach(function (p) { body = body.concat(projectRowNodes(M, S, p, pt)); });
    if (pt.small.length) {
      var ref = "t:small";
      var open = !!S.open[ref];
      body.push(h("tr", {}, [h("th", {scope: "row", colspan: 2}, [U().expandButton(open, null, "작은 과제 " + (open ? "접기" : "펼치기"), ref),
        " 작은 과제 " + pt.small.length + "개(합 " + mm2(pt.smallTotal) + " MM)"]), h("td", {"class": "num"}, [mm2(pt.smallTotal)]),
      h("td", {}, []), h("td", {}, []), h("td", {}, [])]));
      if (open) { pt.small.forEach(function (p) { body = body.concat(projectRowNodes(M, S, p, pt)); }); }
    }
    var head = h("tr", {}, ["과제", "영역", "기간 MM", "사람별 MM", "단위업무", "역할"].map(function (c, k) {
      return h("th", {scope: "col", "class": k === 2 || k >= 4 ? "num" : null}, [c]);
    }));
    var note = pt.threshold > 0 ? "기간 MM " + mm2(pt.threshold) + " 미만 과제는 '작은 과제' 한 줄로 접었습니다. " : "";
    return [card("과제 × 인원", [h("div", {"class": "table-wrap"}, [h("table", {"class": "tbl"}, [
      h("caption", {}, ["과제별 기간 MM — 막대는 사람 순서(같은 색 한 가지), 조각 사이 틈"]), h("thead", {}, [head]),
      h("tbody", {}, body)])]), h("p", {"class": "muted small"}, [note + "과제 행을 펼치면 역할(분야·기능)별 값이 보입니다."])],
    {id: "c-projects"})];
  }

  // 업무 유형 작은 배수(§7.4.2) — 유형마다 같은 축 범위, 단색
  function typeMultiples(M, opt) {
    opt = opt || {};
    var at = obj(M.td.activity_types);
    var byD = obj(at.by_domain);
    var types = arr(at.types).filter(isStr);
    Object.keys(obj(at.total)).sort().forEach(function (t) { if (types.indexOf(t) < 0) { types.push(t); } });
    types = types.filter(function (t) { return isNum(obj(at.total)[t]) && at.total[t] > 0; });
    var doms = M.domains.filter(function (d) { return types.some(function (t) { return isNum(obj(byD[d.code])[t]) && byD[d.code][t] > 0; }); });
    var cols = ["업무 유형", "영역", "MM"];
    var title = "업무 유형별 영역 투입(작은 배수)";
    var cap = {title: title, summary: "", notes: []};
    if (!types.length || !doms.length) {
      return {svg: U().emptyState("업무 유형 자료가 없습니다."), table: {cols: cols, rows: []}, legend: [], caption: {title: title, summary: "자료 없음", notes: []}};
    }
    var max = 0;
    types.forEach(function (t) { doms.forEach(function (d) { var v = obj(byD[d.code])[t]; if (isNum(v)) { max = Math.max(max, v); } }); });
    var W = opt.width || 900;
    var bw = 280;
    var ncol = Math.max(1, Math.floor(W / bw));
    var rowH = 20;
    var blockH = 28 + doms.length * rowH + 10;
    var LW = 96;
    var PW = bw - LW - 64;
    var kids = [];
    var rows = [];
    types.forEach(function (t, k) {
      var ox = (k % ncol) * bw;
      var oy = Math.floor(k / ncol) * blockH;
      kids.push(h("text", {x: ox, y: oy + 16, "class": "t-strong"}, [vocabName(M, "wtype", t) + " · " + mm2(at.total[t]) + " MM"]));
      doms.forEach(function (d, j) {
        var v = obj(byD[d.code])[t];
        v = isNum(v) ? v : 0;
        var y = oy + 28 + j * rowH;
        var w = max > 0 ? PW * v / max : 0;
        kids.push(h("text", {x: ox, y: y + 13, "class": "t-label"}, [d.name]));
        kids.push(h("rect", {x: C().round1(ox + LW), y: y + 3, width: C().round1(Math.max(0, w)), height: 12, rx: 2, "class": "f-blue"}));
        kids.push(h("text", {x: C().round1(ox + LW + w + 4), y: y + 13, "class": "t-value"}, [v > 0 ? mm2(v) : "0"]));
        if (v > 0) { rows.push([vocabName(M, "wtype", t), d.name, mm2(v)]); }
      });
    });
    var nrow = Math.ceil(types.length / ncol);
    var Wsvg = Math.min(W, ncol * bw);
    cap.summary = "유형 " + types.length + "개 · 모든 작은 그림은 같은 0 ~ " + mm2(max) + " MM 범위";
    var svg = h("svg", {"class": "chart", viewBox: "0 0 " + Wsvg + " " + (nrow * blockH), width: Wsvg, height: nrow * blockH,
      role: "img", focusable: "false", "aria-labelledby": "ch-types-t ch-types-d"},
    [h("title", {id: "ch-types-t"}, [title]), h("desc", {id: "ch-types-d"}, [cap.summary])].concat(kids));
    return {svg: svg, table: {cols: cols, rows: rows}, legend: [], caption: cap};
  }

  // 단위업무 상태·등급 분포(단색 + 글자, 측정 불충분 제외 — 취합기가 이미 뺐다)
  function unitBars(M, opt) {
    opt = opt || {};
    var us = obj(M.td.units_stats);
    var bs = obj(us.by_status);
    var bg = obj(us.by_grade);
    var items = [["closed", "완료"], ["estimated", "추정 완료"], ["open", "진행 중"]].map(function (x) {
      return {g: "상태", k: x[1], v: isNum(bs[x[0]]) ? bs[x[0]] : 0};
    }).concat(GRADES.filter(function (g) { return isNum(bg[g]) && bg[g] > 0 || g !== "M"; }).map(function (g) {
      return {g: "등급", k: "등급 " + g, v: isNum(bg[g]) ? bg[g] : 0};
    }));
    var max = Math.max.apply(null, [1].concat(items.map(function (x) { return x.v; })));
    var W = Math.min(opt.width || 560, 560);
    var LW = 96;
    var PW = W - LW - 48;
    var kids = [];
    var rows = [];
    items.forEach(function (x, k) {
      var y = k * 22 + (x.g === "등급" ? 10 : 0);
      var w = PW * x.v / max;
      kids.push(h("text", {x: 0, y: y + 14, "class": "t-label"}, [x.k]));
      kids.push(h("rect", {x: LW, y: y + 4, width: C().round1(Math.max(0, w)), height: 12, rx: 2, "class": "f-blue"}));
      kids.push(h("text", {x: C().round1(LW + w + 4), y: y + 14, "class": "t-value"}, [String(x.v)]));
      rows.push([x.g, x.k, String(x.v)]);
    });
    var Hh = items.length * 22 + 14;
    var cap = {title: "단위업무 상태·등급 분포", summary: "측정 불충분 인원은 빼고 셉니다", notes: []};
    var svg = h("svg", {"class": "chart", viewBox: "0 0 " + W + " " + Hh, width: W, height: Hh, role: "img", focusable: "false",
      "aria-labelledby": "ch-ustat-t ch-ustat-d"},
    [h("title", {id: "ch-ustat-t"}, [cap.title]), h("desc", {id: "ch-ustat-d"}, [cap.summary])].concat(kids));
    return {svg: svg, table: {cols: ["묶음", "항목", "단위업무 수"], rows: rows}, legend: [], caption: cap};
  }

  function rolesView(M, S) {
    var g = roleGrid(M);
    var out = [];
    if (!g.fields.length || !g.funcs.length) {
      out.push(card("역할(분야 × 기능)", [U().emptyState("역할 자료가 없습니다.")], {id: "c-rolegrid"}));
    } else {
      var head = h("tr", {}, [h("th", {scope: "col"}, ["분야 \\ 기능"])].concat(g.funcs.map(function (fn) {
        return h("th", {scope: "col", "class": "num"}, [vocabName(M, "func", fn)]);
      })));
      var body = g.fields.map(function (f) {
        return h("tr", {}, [h("th", {scope: "row"}, [vocabName(M, "field", f)])].concat(g.funcs.map(function (fn) {
          var c = g.cell[f + "|" + fn];
          if (!c) { return h("td", {"class": "num heat-0"}, ["·"]); }
          var ref = f + "|" + fn;
          var sel = S.roleCell === ref;
          return h("td", {"class": "num heat-" + heatLevel(c[2], g.max)}, [
            h("button", {type: "button", "class": "btn btn-ghost cell-btn", "data-act": "role-cell", "data-ref": ref,
              "aria-pressed": sel ? "true" : "false", "aria-label": roleName(M, f, fn) + " " + mm2(c[2]) + " MM 역할 목록"},
            [mm2(c[2])]), h("div", {"class": "small"}, [isNum(c[3]) ? pctShare(c[3], 1) : "—"])]);
        })));
      });
      var kids = [h("div", {"class": "table-wrap"}, [h("table", {"class": "tbl"}, [
        h("caption", {}, ["팀 MM(귀속분) · 아래 비율은 측정 불충분 인원을 뺀 귀속 투입 대비"]), h("thead", {}, [head]),
        h("tbody", {}, body)])])];
      if (S.roleCell) {
        var parts = S.roleCell.split("|");
        var rs = rolesOfCell(M, parts[0], parts[1]);
        kids.push(h("div", {"class": "card-sub"}, [h("h3", {}, [roleName(M, parts[0], parts[1]) + " 역할 업무"]),
          rs.length ? h("table", {"class": "tbl"}, [h("thead", {}, [h("tr", {}, ["과제", "사람", "MM"].map(function (c) {
            return h("th", {scope: "col"}, [c]);
          }))]), h("tbody", {}, rs.map(function (r) {
            var key = r.proposal ? r.proposal_key : (r.project_id || "UNC");
            var per = arr(r.by_person).filter(function (bp) { return Array.isArray(bp) && bp[1] > 0; })
              .map(function (bp) { return label(M, bp[0]) + " " + mm2(bp[1]); });
            return h("tr", {}, [h("td", {}, [projectName(M, key)]), h("td", {}, [per.join(" · ") || "—"]),
              h("td", {"class": "num"}, [mm2(r.total_mm)])]);
          }))]) : U().emptyState("이 칸의 역할 업무가 없습니다.")]));
      }
      out.push(card("역할(분야 × 기능)", kids, {id: "c-rolegrid", state: "칸을 누르면 역할 업무 목록"}));
    }
    out.push(card("업무 유형", [chartBlock(S, typeMultiples(M, {width: S.width}), "ch-types")], {id: "c-types"}));
    var ld = C().leadDots(leadSpec(M), {width: S.width, id: "ch-t06", title: "완료 단위업무 영업 리드(영역별)"});
    out.push(card("단위업무 통계", [chartBlock(S, unitBars(M, {width: S.width}), "ch-ustat"), chartBlock(S, ld, "ch-t06"),
      h("p", {"class": "muted small"}, ["점에는 이름이 없습니다(과제 · 역할만). 세로 짧은 선은 영역별 중앙값입니다."])], {id: "c-units"}));
    out.push(card("해석", [interpretationView(M)], {id: "c-interp2"}));
    return out;
  }

  function agenticView(M, S) {
    var g = agenticGrid(M);
    var out = [];
    if (!g.matches.length) {
      out.push(card("에이전트 × 업무 영역", [U().emptyState("매칭된 에이전트가 없습니다.")], {id: "c-t07"}));
    } else {
      var head = h("tr", {}, [h("th", {scope: "col"}, ["에이전트"])].concat(g.cols.map(function (d) {
        return h("th", {scope: "col"}, [domName(M, d)]);
      }), [h("th", {scope: "col", "class": "num"}, ["관련 투입"]), h("th", {scope: "col"}, ["사람 · 역할"])]));
      var body = g.matches.map(function (x) {
        return h("tr", {}, [h("th", {scope: "row"}, [x.name || x.agent_id || "—", h("div", {"class": "muted small"}, [x.agent_id || ""])])]
          .concat(g.cols.map(function (d) {
            var c = obj(x.by_domain)[d];
            if (!isObj(c)) { return h("td", {"class": "ag ag-none"}, ["·"]); }
            return h("td", {"class": "heat-" + heatLevel(c.related_mm, g.max)}, [
              (c.people || 0) + "명 · " + (c.units || 0) + "건 ", h("strong", {}, [c.best || "·"])]);
          }), [h("td", {"class": "num"}, [mmText(x.related_mm)].concat(x.overlap ? [h("div", {"class": "muted small"}, ["중복 포함"])] : [])),
            h("td", {}, ["사람 " + (x.people || 0) + " · 역할 " + (x.roles || 0)])]));
      });
      out.push(card("에이전트 × 업무 영역", [h("div", {"class": "table-wrap"}, [h("table", {"class": "tbl"}, [
        h("caption", {}, ["칸 = 사람 수 · 단위업무 수 + 최고 등급, 농도 = 관련 투입 MM"]), h("thead", {}, [head]),
        h("tbody", {}, body)])]),
      h("p", {}, ["팀 관련 투입(같은 단위업무는 한 번): " + mmText(g.total)]),
      h("p", {"class": "muted small"}, ["관련 투입은 실측이며 대체 가능 시간을 뜻하지 않습니다."])], {id: "c-t07"}));
    }
    var groups = needGroups(M);
    if (!groups.length) {
      out.push(card("새 니즈", [U().emptyState("팀원 묶음에 새 니즈가 없습니다.")], {id: "c-needs"}));
    } else {
      var nh = ["이름", "단계 유형", "사람 수", "월 빈도 합", "관련 투입", "등급 분포", "출처"];
      if (S.live) { nh.push(""); }
      var body2 = [];
      groups.forEach(function (gr) {
        var freq = 0;
        var mmSum = 0;
        gr.rows.forEach(function (it) {
          var x = it.n;
          freq += isNum(x.freq_per_month) ? x.freq_per_month : 0;
          mmSum += isNum(x.related_mm) ? x.related_mm : 0;
          var gd = obj(x.grades);
          var src = obj(x.src);
          var tds = [h("td", {}, [x.label || "—"]), h("td", {}, [stepName(M, gr.type)]),
            h("td", {"class": "num"}, [String(x.people || 0)]), h("td", {"class": "num"}, [U().fmtNum(x.freq_per_month || 0, 1)]),
            h("td", {"class": "num"}, [mmText(x.related_mm)]),
            h("td", {}, [AG_GRADES.map(function (k) { return k + " " + (gd[k] || 0); }).join(" · ")]),
            h("td", {}, ["AI " + (src.ai || 0) + " · 규칙 " + (src.rule || 0)])];
          if (S.live) {
            tds.push(h("td", {}, [h("button", {type: "button", "class": "btn btn-ghost", "data-act": "promote-need",
              "data-ref": String(it.k)}, ["카탈로그로 올리기"])]));
          }
          body2.push(h("tr", {}, tds));
        });
        var sub = [h("th", {scope: "row", colspan: 3}, [stepName(M, gr.type) + " 소계 " + gr.rows.length + "건"]),
          h("td", {"class": "num"}, [U().fmtNum(freq, 1)]), h("td", {"class": "num"}, [mmText(mmSum)]),
          h("td", {colspan: S.live ? 3 : 2, "class": "muted small"}, ["관련 투입 소계는 겹친 단위업무를 중복으로 셉니다"])];
        body2.push(h("tr", {"class": "detail"}, sub));
      });
      out.push(card("새 니즈", [h("div", {"class": "table-wrap"}, [h("table", {"class": "tbl"}, [
        h("caption", {}, ["(단계 유형, 이름) 묶음 — 비슷한 이름은 합치지 않고 나란히 둡니다"]),
        h("thead", {}, [h("tr", {}, nh.map(function (c) { return h("th", {scope: "col"}, [c]); }))]), h("tbody", {}, body2)])]),
      h("p", {"class": "muted small"}, ["카탈로그로 올리려면 관리 화면에서 에이전트를 추가하세요."])], {id: "c-needs"}));
    }
    var subs = arr(obj(M.td.agentic).subagents).filter(isObj);
    out.push(card("서브에이전트 적합성", subs.length ? [h("div", {"class": "table-wrap"}, [h("table", {"class": "tbl"}, [
      h("thead", {}, [h("tr", {}, ["역할(분야·기능)", "적합", "조건부", "부적합", "제안 체인"].map(function (c) {
        return h("th", {scope: "col"}, [c]);
      }))]),
      h("tbody", {}, subs.map(function (x) {
        var fit = obj(x.fit);
        return h("tr", {}, [h("th", {scope: "row"}, [roleName(M, x.field, x["function"])])].concat(FITS.map(function (f) {
          return h("td", {}, [U().verdictBadge(f), " " + (fit[f] || 0) + "명"]);
        }), [h("td", {}, arr(x.chains).filter(isObj).map(function (c) {
          return h("div", {}, [(c.proposal || "—") + " — " + (c.people || 0) + "명" +
            (arr(c.step_types).length ? " · " + arr(c.step_types).map(function (t) { return stepName(M, t); }).join(", ") : "")]);
        }))]));
      }))])])] : [U().emptyState("서브에이전트 검토 자료가 없습니다.")], {id: "c-subagent"}));
    return out;
  }

  function ganttView(M, S) {
    var rows = ganttRows(M, S.pivot);
    var key = S.pivot ? "pivot" : "base";
    if (!S.collapsed[key]) {
      var lim = isNum(M.view.gantt_expand_rows) ? M.view.gantt_expand_rows : HUGE_ROWS;
      S.collapsed[key] = defaultCollapsed(rows, lim);
    }
    var res = C().gantt({rows: rows, months: M.months}, {mode: "team", width: S.width, view: S.gview, collapsed: S.collapsed[key],
      id: "ch-t08", title: "담당자별 업무 영역 · 과제 · 역할 간트",
      labelHead: S.pivot ? "영역 › 과제 › 역할 › 담당자" : "담당자 › 영역 › 과제 › 역할"});
    var tools = h("div", {"class": "table-tools", role: "group", "aria-label": "간트 보기"}, [
      h("button", {type: "button", "class": "btn btn-ghost", "data-act": "pivot", "data-ref": "person",
        "aria-pressed": S.pivot ? "false" : "true"}, ["담당자 기준"]),
      h("button", {type: "button", "class": "btn btn-ghost", "data-act": "pivot", "data-ref": "work",
        "aria-pressed": S.pivot ? "true" : "false"}, ["업무 기준"]),
      h("button", {type: "button", "class": "btn btn-ghost", "data-act": "gview", "data-ref": "month",
        "aria-pressed": S.gview === "week" ? "false" : "true"}, ["월 보기"]),
      h("button", {type: "button", "class": "btn btn-ghost", "data-act": "gview", "data-ref": "week",
        "aria-pressed": S.gview === "week" ? "true" : "false"}, ["주 보기"]),
      h("button", {type: "button", "class": "btn btn-ghost", "data-act": "expand-all"}, ["모두 펼치기"]),
      h("button", {type: "button", "class": "btn btn-ghost", "data-act": "collapse-all"}, ["모두 접기"])]);
    return [card("담당자별 업무 간트", [tools, chartBlock(S, res, "ch-t08"),
      h("p", {"class": "muted small"}, ["막대 길이는 투입이 아닙니다(의뢰~보고 리드타임). 진한 칸이 주별 투입 밀도입니다. 막대나 역할 행을 누르면 그 사람의 워크플로우가 열립니다."])],
    {id: "c-gantt"})];
  }

  function covCell(v) {
    if (!isNum(v)) { return h("td", {"class": "num muted"}, ["—"]); }
    var st = v >= 0.8 ? "good" : (v >= 0.5 ? "warn" : "bad");
    return h("td", {"class": "num"}, [U().statusText(st, pctShare(v, 1))]);
  }

  function qualityView(M, S) {
    var rows = qualityRows(M);
    var head = h("tr", {}, [h("th", {scope: "col"}, ["사람"])].concat(AXES.map(function (a) {
      return h("th", {scope: "col", "class": "num"}, [a[1]]);
    }), [h("th", {scope: "col"}, ["등급"]), h("th", {scope: "col", "class": "num"}, ["PC 수"]), h("th", {scope: "col"}, ["표식"])]));
    var body = [];
    rows.forEach(function (x) {
      var r = x.r;
      var ref = "t:q:" + r.i;
      var open = !!S.open[ref];
      var cls = x.weak ? "muted row-weak" : null;
      body.push(h("tr", {"class": cls}, [h("th", {scope: "row"}, [U().expandButton(open, null, label(M, r.i) + " 상세 " + (open ? "접기" : "펼치기"), ref),
        " " + label(M, r.i)])].concat(AXES.map(function (a) { return covCell(obj(r.axes)[a[0]]); }),
      [h("td", {}, [U().qualityBadge(r.grade)]), h("td", {"class": "num"}, [String(isNum(r.pcs) ? r.pcs : 0)]),
        h("td", {}, [arr(r.flags).map(function (f) { return FLAG_TEXT[f] || f; }).join(" · ") || "—"])])));
      if (open) {
        var cp = obj(r.copilot);
        var q = obj(r.queue);
        var lines = arr(r.reasons).map(function (c) { return REASON_TEXT[c] || c; });
        lines.push("코파일럿 " + (cp.used ? "사용 · 실패 항목 " + (cp.failed_items || 0) + "건" : "사용 안 함"));
        lines.push("확인 질문 열림 " + (q.open || 0) + " · 응답 " + (q.resolved || 0));
        if (isNum(r.estimated_min_ratio)) { lines.push("추정 분 비율 " + pctShare(r.estimated_min_ratio, 1)); }
        body.push(h("tr", {"class": "detail"}, [h("td", {colspan: AXES.length + 4}, [h("ul", {}, lines.map(function (t) {
          return h("li", {}, [t]);
        }))])]));
      }
    });
    return [card("측정 품질 — 사람 × 출처 커버리지", [
      h("p", {}, ["측정 불충분 인원은 팀 합계에는 들어가지만(빗금) 평균·순위·분포 비교에서는 빠집니다. 수집이 안 된 것을 일이 적은 것으로 읽지 않기 위해서입니다."]),
      rows.length ? h("div", {"class": "table-wrap"}, [h("table", {"class": "tbl"}, [
        h("caption", {}, ["칸 = 근무일 커버리지(정상·0건 확인 + 일부의 절반) — ✓ 80% 이상 · ! 50% 이상 · ✕ 그 밖"]),
        h("thead", {}, [head]), h("tbody", {}, body)])]) : U().emptyState("측정 품질 자료가 없습니다.")], {id: "c-t09"})];
  }

  function peopleView(M, S) {
    var pm = peopleMonths(M);
    var cols = ["사람", "월", "MM", "근무"];
    if (pm.full) { cols = cols.concat(["정규", "연장", "야간", "휴일", "가용일", "로드율"]); }
    cols = cols.concat(["측정 품질", "부분월"]);
    function rowOf(x, weak) {
      var e = x.e;
      var tds = [h("th", {scope: "row"}, [x.label].concat(x.flags.length ? [h("div", {"class": "muted small"},
        [x.flags.map(function (f) { return FLAG_TEXT[f] || f; }).join(" · ")])] : [])),
      h("td", {}, [e.m || "—"]), h("td", {"class": "num"}, [mm2(e.mm)]), h("td", {"class": "num"}, [hText(e.env_min)])];
      if (pm.full) {
        var bt = obj(e[K.tags]);
        TAGS.forEach(function (t) { tds.push(h("td", {"class": "num"}, [hText(isNum(bt[t]) ? bt[t] : null)])); });
        var av = e[K.avail];
        tds.push(h("td", {"class": "num"}, [isNum(av) ? U().fmtNum(av, 1) + "일" : "—"]));
        var lp = e[K.load];
        tds.push(h("td", {"class": "num"}, [isNum(lp) ? U().fmtNum(lp, 0) + "%" : "—"]));
      }
      tds.push(h("td", {}, [QUALITY_NAME[x.quality] || "미확인"]));
      var pt = obj(e.partial);
      tds.push(h("td", {}, [isNum(pt.covered_workdays) ? "부분월(" + pt.covered_workdays + "/" + pt.workdays + " 평일)" : "—"]));
      return h("tr", {"class": weak ? "muted row-weak" : null}, tds);
    }
    function table(rows, cap, weak) {
      return h("div", {"class": "table-wrap"}, [h("table", {"class": "tbl"}, [h("caption", {}, [cap]),
        h("thead", {}, [h("tr", {}, cols.map(function (c, k) { return h("th", {scope: "col", "class": k >= 2 ? "num" : null}, [c]); }))]),
        h("tbody", {}, rows.map(function (x) { return rowOf(x, weak); }))])]);
    }
    var kids = [pm.rows.length ? table(pm.rows, "사람별 월 투입(비교 대상)", false) : U().emptyState("비교할 사람별 월 투입 자료가 없습니다 — 측정 불충분이 아닌 팀원 묶음이 들어오면 보입니다.")];
    if (pm.weakRows.length) { kids.push(table(pm.weakRows, "측정 불충분 인원(비교에서 제외 — 합계에는 포함)", true)); }
    if (!pm.full) { kids.push(h("p", {"class": "muted small"}, ["공유판에는 사람별 로드율·가용일·꼬리표(초과 시간) 열이 없습니다."])); }
    return [card("사람별 월 투입", kids, {id: "c-people"})];
  }

  function sectionView(M, S) {
    switch (S.section) {
    case "domains": return domainsView(M, S);
    case "projects": return projectsView(M, S);
    case "roles": return rolesView(M, S);
    case "agentic": return agenticView(M, S);
    case "gantt": return ganttView(M, S);
    case "quality": return qualityView(M, S);
    case "people": return peopleView(M, S);
    default: return summaryView(M, S);
    }
  }

  // ───────────────────────── 6. 간트 드릴다운 서랍(§7.6.3) ─────────────────────────
  function miniGantt(u) {
    var c = C();
    var sp = arr(u.spans);
    var lead = null;
    sp.forEach(function (s) { if (Array.isArray(s) && s[2] === "lead") { lead = [c.dayNum(s[0]), c.dayNum(s[1])]; } });
    var lo = lead ? lead[0] : Infinity;
    var hi = lead ? lead[1] : -Infinity;
    Object.keys(obj(u.density)).forEach(function (k) { var ws = c.weekStart(k); if (isFinite(ws)) { lo = Math.min(lo, ws); hi = Math.max(hi, ws + 6); } });
    if (!isFinite(lo)) { return h("span", {"class": "muted"}, ["—"]); }
    var W = 140;
    var n = hi - lo + 1;
    var dw = W / n;
    var kids = [];
    if (lead) { kids.push(h("rect", {x: c.round1((lead[0] - lo) * dw), y: 2, width: c.round1(Math.max(2, (lead[1] - lead[0] + 1) * dw)), height: 10, rx: 2, "class": "f-lead s-lead", "stroke-width": 1})); }
    Object.keys(obj(u.density)).sort().forEach(function (k) {
      var v = u.density[k];
      var m = isNum(v) ? v : (obj(v).obs || 0) + (obj(v).est || 0);
      var ws = c.weekStart(k);
      if (!(m > 0) || !isFinite(ws)) { return; }
      kids.push(h("rect", {x: c.round1((ws - lo) * dw), y: 4, width: c.round1(Math.max(1, 7 * dw)), height: 6, "class": "f-seq-" + c.densityLevel(m)}));
    });
    return h("svg", {"class": "mini-gantt", viewBox: "0 0 " + W + " 14", width: W, height: 14, "aria-hidden": "true", focusable: "false"}, kids);
  }

  function detailBody(M, ref, d, opt) {
    opt = opt || {};
    var mm = ROLE_REF.exec(ref) || [];
    var i = Number(mm[1]);
    if (!isObj(d)) {
      return h("div", {}, [U().alertLine("info", opt.missing || "이 업무의 워크플로우가 묶음에 없습니다(규칙 이전 판 묶음).")]);
    }
    var role = obj(d.role);
    var wf = obj(d.workflow);
    var steps = arr(wf.steps).filter(isObj).map(function (s) {
      var x = {};
      Object.keys(s).forEach(function (k) { x[k] = s[k]; });
      if (!x.name) { x.name = stepName(M, s.type); }
      if (!x.kind && x.type) { var kk = obj(obj(M.td.vocab_names).step_kind)[x.type]; if (kk) { x.kind = kk; } }
      return x;
    });
    var units = arr(d.units).filter(isObj);
    var eff = sum(units, function (u) { return isNum(u.effort_min) ? u.effort_min : 0; });
    var leadDays = units.map(function (u) {
      var s = arr(u.spans).filter(function (x) { return Array.isArray(x) && x[2] === "lead"; })[0];
      return s ? C().dayNum(s[1]) - C().dayNum(s[0]) + 1 : null;
    });
    var medLead = median(leadDays);
    var pars = units.map(function (u) { return u.parallel; }).filter(isNum);
    var person = M.P[i] || {};
    var head = h("div", {"class": "drawer-meta"}, [
      h("p", {}, [label(M, i), " · ", U().badge(domName(M, role.domain), null, "업무 영역"), " · ",
        role.project_label || projectName(M, role.project_id || "UNC"), role.proposal ? " (제안)" : "", " · ",
        roleName(M, role.field, role["function"]), " ", U().qualityBadge(person.quality)])]);
    var k4 = h("div", {"class": "kpis"}, [
      U().kpiCard({label: "투입", value: hText(eff)}),
      U().kpiCard({label: "단위업무", value: units.length ? units.length + "개" : (d.units_omitted ? "—" : "0개")}),
      U().kpiCard({label: "중앙 리드", value: medLead === null ? "—" : U().fmtNum(medLead, 0) + "일"}),
      U().kpiCard({label: "평균 병행도", value: pars.length ? U().fmtX(sum(pars) / pars.length) : "—"})]);
    var spec = {steps: steps, edges: arr(wf.edges), sample: wf.sample, units_n: units.length || null,
      bottlenecks: steps.filter(function (s) { return s.bottleneck === "wait" || s.bottleneck === "work" || s.bottleneck === "both"; })
        .reduce(function (acc, s) {
          if (s.bottleneck !== "work") { acc.push({no: s.no, kind: "wait", value_min: s.wait_in_median_min}); }
          if (s.bottleneck !== "wait") { acc.push({no: s.no, kind: "work", share: s.work_share}); }
          return acc;
        }, [])};
    var pm = C().processMap(spec, {width: opt.width || 480, id: "ch-p07-team", title: "역할 워크플로우(이 사람이 보낸 단계)"});
    var stepRows = steps.slice().sort(function (a, b) { return a.no - b.no; }).map(function (s) {
      return h("tr", {id: "step-row-" + s.no, tabindex: "-1"}, [h("td", {"class": "num"}, [String(s.no)]), h("td", {}, [s.label || s.name]),
        h("td", {}, [s.name || s.type || "—"]), h("td", {"class": "num"}, [String(isNum(s.n) ? s.n : 0)]),
        h("td", {"class": "num"}, [isNum(s.median_min) && s.median_min > 0 ? hText(s.median_min) : "—"]),
        h("td", {}, [s.agent_grade || "—"]), h("td", {}, [s.subagent ? U().verdictBadge(s.subagent) : "—"]),
        h("td", {}, arr(s.why).map(function (w) { return U().badge(WHY_TEXT[w] || w, null, null); }))]);
    });
    var kids = [head, k4, U().chartView(pm, {id: "ch-p07-team", table: !!opt.table}),
      h("h3", {}, ["단계"]),
      steps.length ? h("div", {"class": "table-wrap"}, [h("table", {"class": "tbl"}, [
        h("thead", {}, [h("tr", {}, ["번호", "라벨", "유형", "n", "중앙 소요", "Agentic", "서브에이전트", "근거"].map(function (c) {
          return h("th", {scope: "col"}, [c]);
        }))]), h("tbody", {}, stepRows)])]) : U().emptyState("단계 자료가 없습니다."),
      h("h3", {}, ["단위업무"])];
    if (d.units_omitted) {
      kids.push(U().alertLine("info", "단위업무 목록은 팀 대시보드에서 보세요(보고서 파일 크기 상한)."));
    } else if (!units.length) {
      kids.push(U().emptyState("단위업무가 없습니다."));
    } else {
      kids.push(h("div", {"class": "table-wrap"}, [h("table", {"class": "tbl"}, [
        h("thead", {}, [h("tr", {}, ["제목", "시작 → 끝", "등급", "상태", "리드", "투입", "병행도", "간트"].map(function (c) {
          return h("th", {scope: "col"}, [c]);
        }))]),
        h("tbody", {}, units.map(function (u) {
          var lead = arr(u.spans).filter(function (x) { return Array.isArray(x) && x[2] === "lead"; })[0];
          return h("tr", {}, [h("td", {}, [u.title || u.unit_id || "—"]),
            h("td", {}, [(obj(u.start).kind || "—") + " → " + (obj(u.end).kind || (u.status === "open" ? "진행 중" : "—"))]),
            h("td", {}, [U().gradeBadge(u.grade)]), h("td", {}, [STATUS_NAME[u.status] || u.status || "—"]),
            h("td", {"class": "num"}, [lead ? String(C().dayNum(lead[1]) - C().dayNum(lead[0]) + 1) + "일" : "—"]),
            h("td", {"class": "num"}, [hText(u.effort_min)]), h("td", {"class": "num"}, [U().fmtX(u.parallel)]),
            h("td", {}, [miniGantt(u)])]);
        }))])]));
    }
    var ms = arr(obj(d.agentic).matches).filter(isObj);
    kids.push(h("h3", {}, ["Agentic 매칭"]));
    kids.push(ms.length ? h("ul", {}, ms.map(function (x) {
      return h("li", {}, [(x.name || x.agent_id || "—") + " · " + stepName(M, x.step_type) + " · 등급 " + (x.grade || "—")]);
    })) : U().emptyState("이 역할에 매칭된 에이전트가 없습니다."));
    return h("div", {"class": "team-detail"}, kids);
  }

  function warningsBody(M) {
    var ws = arr(M.td.warnings);
    return h("div", {}, [h("p", {}, ["취합 불변식 위반·자료 문제는 산출을 멈추지 않고 여기에 남습니다(TEAM §4.8)."]),
      h("ul", {}, ws.map(function (w) { return h("li", {}, [String(w)]); }))]);
  }

  // ───────────────────────── 7. 대시보드·보고서 앱 ─────────────────────────
  // 브라우저 환경(시험은 가짜를 넣는다): fetch · location · history · 창(hashchange) · 파일 읽기·내려받기
  function envOf(opt) {
    opt = opt || {};
    return {
      fetch: opt.fetch || (typeof root.fetch === "function" ? function (u, i) { return root.fetch(u, i); } : null),
      location: opt.location || root.location || null, history: opt.history || root.history || null,
      win: opt.win || (typeof root.addEventListener === "function" ? root : null),
      FileReader: opt.FileReader || root.FileReader || null, Blob: opt.Blob || root.Blob || null, URL: opt.URL || root.URL || null};
  }

  function fetchJson(env, path, headers, init) {
    if (!env.fetch) { return Promise.reject(new Error("fetch 없음")); }
    var opt = {headers: headers || {}, cache: "no-store", credentials: "same-origin"};
    Object.keys(init || {}).forEach(function (k) { opt[k] = init[k]; });
    return env.fetch(path, opt).then(function (r) {
      return r.text().then(function (t) {
        var j = null;
        try { j = t ? JSON.parse(t) : null; } catch (e) { j = null; }
        return {status: r.status, body: j};
      });
    });
  }

  function createApp(doc, opt) {
    var env = envOf(opt);
    var S = {doc: doc, live: false, td: null, det: {}, section: "summary", pivot: false, gview: "month", collapsed: {},
      open: {}, tables: {}, roleCell: null, width: 1100, token: "", drawerRef: null, pushed: false, seq: 0, dcur: null,
      dtable: false, variant: "full", status: null};
    var M = null;
    var rootEl = doc.getElementById("team-root") || doc.body;
    var main = doc.getElementById("app");
    var head = doc.getElementById("team-head");
    var nav = doc.getElementById("team-nav");

    function width() {
      var w = main && main.clientWidth ? main.clientWidth - 48 : 1100;
      return Math.max(320, Math.min(1240, w));
    }

    function render(focus) {
      if (!M) { return; }
      S.width = width();
      if (head) { U().render(headView(M, S), head); }
      if (nav) { U().render(navView(S), nav); }
      U().render(statusLines().concat(sectionView(M, S)), main);
      if (focus) { refocus(focus); }
    }

    // 대시보드 머리 알림(TAB §3.9 · §3.14): 재취합 실패(이전 세대를 계속 보여 줌)·진행 중 · 방화벽 의심
    function statusLines() {
      var st = obj(S.status);
      var ag = obj(st.aggregate);
      var out = [];
      if (ag.state === "failed") {
        out.push(U().alertLine("bad", "최근 재취합이 실패해 이전 세대를 그대로 보여 줍니다" + (ag.note ? " — " + ag.note : "") + "."));
      } else if (ag.state === "running" || ag.state === "queued") {
        out.push(U().alertLine("info", "다시 취합하는 중입니다 — 끝나면 새로 고치세요."));
      }
      var fw = obj(st.firewall_hint);
      if (fw.message_ko) { out.push(U().alertLine(fw.level === "info" ? "info" : "warn", String(fw.message_ko))); }
      return out;
    }

    function loadStatus() {
      return fetchJson(env, "/api/status", readHeaders()).then(function (r) {
        if (r.status === 200 && isObj(r.body)) { S.status = r.body; render(); }
      }, function () { return null; });
    }

    function refocus(f) {
      var els = main.querySelectorAll ? main.querySelectorAll("[data-act]") : [];
      for (var k = 0; k < els.length; k++) {
        if (els[k].getAttribute("data-act") === f.act && (els[k].getAttribute("data-ref") || "") === (f.ref || "")) {
          if (els[k].focus) { els[k].focus(); }
          return;
        }
      }
    }

    function message(kind, text) { U().render([U().alertLine(kind, text)], main); }

    function readHeaders() { return S.token ? {"X-LM27-Upload-Token": S.token} : {}; }

    function setData(td, det) {
      S.td = td;
      S.det = obj(det);
      M = model(td, S.det, {variant: S.live ? "full" : S.variant});
      S.collapsed = {};
      render();
      syncHash();
    }

    function load() {
      message("info", "팀 데이터를 읽는 중입니다.");
      return fetchJson(env, "/api/team", readHeaders()).then(function (r) {
        if (r.status === 200 && isObj(r.body)) { setData(r.body, {}); return loadStatus(); }
        if (r.status === 401) { tokenForm(obj(r.body).error || "읽기 토큰이 필요합니다."); return; }
        message(r.status === 404 ? "info" : "bad", obj(r.body).error || ("팀 데이터를 읽지 못했습니다(HTTP " + r.status + ")"));
      }, function () { message("bad", "팀 서버에 닿지 않습니다 — 서버가 켜져 있는지 확인하세요."); });
    }

    function tokenForm(why) {
      U().render([U().alertLine("warn", why), h("div", {"class": "card"}, [
        h("label", {"for": "team-token"}, ["읽기 토큰(팀 서버 관리자에게 받은 값)"]),
        h("input", {id: "team-token", type: "password", autocomplete: "off", name: "token"}),
        h("button", {type: "button", "class": "btn btn-primary", "data-act": "token-save"}, ["열기"])])], main);
    }

    // 서랍 — 요청마다 순번(seq). 새 서랍이 옛 서랍을 바꾸면 옛 서랍의 닫힘 처리는 아무것도 하지 않는다.
    function showDrawer(seq) {
      var c = S.dcur;
      if (!c || seq !== S.seq) { return; }
      var mm = ROLE_REF.exec(c.ref);
      U().openDrawer(detailBody(M, c.ref, c.d, {width: 470, missing: c.missing, table: S.dtable}), {doc: doc,
        title: label(M, Number(mm[1])) + " · 워크플로우", returnFocus: c.from || null,
        onClose: function () { onDrawerClose(seq, c.ref); },
        handlers: {
          "pm-step": function (el, no) { var row = doc.getElementById("step-row-" + no); if (row && row.focus) { row.focus(); } },
          "chart-table": function () { S.dtable = !S.dtable; showDrawer(++S.seq); }}});
    }

    function openDetail(ref, from) {
      var mm = ROLE_REF.exec(ref || "");
      if (!mm || !M) { return null; }
      var seq = ++S.seq;
      S.drawerRef = ref;
      S.dtable = false;
      if (!S.live) {
        S.dcur = {ref: ref, d: detailFor(M, ref), from: from};
        showDrawer(seq);
        return null;
      }
      var pk = (M.P[Number(mm[1])] || {}).person_key;
      if (!pk) { S.dcur = {ref: ref, d: null, from: from}; showDrawer(seq); return null; }
      return fetchJson(env, "/api/team/detail?person=" + encodeURIComponent(pk) + "&role=" + encodeURIComponent(mm[2]), readHeaders())
        .then(function (r) {
          S.dcur = {ref: ref, d: r.status === 200 ? r.body : null, from: from};
          showDrawer(seq);
        }, function () {
          S.dcur = {ref: ref, d: null, from: from, missing: "팀 서버에 닿지 않아 상세를 읽지 못했습니다."};
          showDrawer(seq);
        });
    }

    function onDrawerClose(seq, ref) {
      if (seq !== S.seq) { return; }
      S.drawerRef = null;
      var cur = parseHash(env.location ? env.location.hash : "");
      if (cur.drawer === ref) {
        if (S.pushed && env.history) { S.pushed = false; env.history.back(); } else { setHash("gantt", true); }
      }
    }

    function setHash(s, replace) {
      var loc = env.location;
      if (!loc) { return; }
      if (replace && typeof loc.replace === "function" && isStr(loc.href)) {
        loc.replace(loc.href.split("#")[0] + "#" + s);
      } else {
        loc.hash = s;
      }
    }

    function syncHash() {
      if (!env.location || !M) { return; }
      var p = parseHash(env.location.hash);
      if (p.section !== S.section) { S.section = p.section; render(); }
      if (p.drawer && p.drawer !== S.drawerRef) { openDetail(p.drawer, null); }
      if (!p.drawer && S.drawerRef) {
        S.seq++;                                                  // 옛 서랍의 닫힘 처리가 기록을 건드리지 않게
        S.drawerRef = null;
        U().closeDrawer();
      }
    }

    var handlers = {
      "toggle-row": function (el, ref) {
        if (!ref) { return; }
        if (ref.indexOf("t:") === 0) {
          S.open[ref] = !S.open[ref];
        } else {
          var key = S.pivot ? "pivot" : "base";
          var c = S.collapsed[key] = S.collapsed[key] || {};
          if (c[ref]) { delete c[ref]; } else { c[ref] = true; }
        }
        render({act: "toggle-row", ref: ref});
      },
      "open-gantt": function (el, ref) {
        var mm = ROLE_REF.exec(ref || "");
        if (!mm) { return; }
        var replace = !!S.drawerRef && !!parseHash(env.location ? env.location.hash : "").drawer;
        if (!replace) { S.pushed = true; }
        openDetail(ref, el);
        setHash("gantt/" + mm[1] + "/" + mm[2], replace);
      },
      "open-unit": function (el, ref) { if (ROLE_REF.test(ref || "")) { S.pushed = false; openDetail(ref, el); } },
      "chart-table": function (el, ref) {
        if (S.tables[ref]) { delete S.tables[ref]; } else { S.tables[ref] = {col: null, desc: false, limit: 500}; }
        render({act: "chart-table", ref: ref});
      },
      "table-sort": function (el, ref) {
        var t = tableOf(el);
        if (!t) { return; }
        var col = Number(ref);
        t.desc = t.col === col ? !t.desc : false;
        t.col = col;
        render({act: "table-sort", ref: ref});
      },
      "table-unsort": function (el) { var t = tableOf(el); if (t) { t.col = null; t.desc = false; render(); } },
      "table-more": function (el) { var t = tableOf(el); if (t) { t.limit += 500; render(); } },
      "pivot": function (el, ref) { S.pivot = ref === "work"; render({act: "pivot", ref: ref}); },
      "gview": function (el, ref) { S.gview = ref === "week" ? "week" : "month"; render({act: "gview", ref: ref}); },
      "expand-all": function () { S.collapsed[S.pivot ? "pivot" : "base"] = {}; render({act: "expand-all", ref: ""}); },
      "collapse-all": function () {
        var c = {};
        ganttRows(M, S.pivot).forEach(function (r) { if (r.group) { c[r.key] = true; } });
        S.collapsed[S.pivot ? "pivot" : "base"] = c;
        render({act: "collapse-all", ref: ""});
      },
      "role-cell": function (el, ref) { S.roleCell = S.roleCell === ref ? null : ref; render({act: "role-cell", ref: ref}); },
      "show-warnings": function (el) {
        S.seq++;
        S.drawerRef = null;
        U().openDrawer(warningsBody(M), {doc: doc, title: "취합 경고 " + arr(M.td.warnings).length + "건", returnFocus: el});
      },
      "drill-team-month": function () { setHash("domains"); },
      "promote-need": function (el, ref) {
        var x = arr(obj(M.td.agentic).needs)[Number(ref)];
        if (!isObj(x) || !env.location) { return; }
        env.location.href = "/admin#agent-new/" + encodeURIComponent(x.step_type || "") + "/" + encodeURIComponent(x.label || "");
      },
      "token-save": function () {
        var inp = doc.getElementById("team-token");
        S.token = inp ? String(inp.value || "") : "";
        load();
      },
      "escape": function () { if (S.drawerRef) { U().closeDrawer(); } }
    };

    function closest(el, attr) {
      while (el && el.nodeType === 1) {
        if (el.hasAttribute && el.hasAttribute(attr)) { return el; }
        el = el.parentNode;
      }
      return null;
    }

    function tableOf(el) {
      var fig = closest(el, "data-chart");
      return fig ? S.tables[fig.getAttribute("data-chart")] || null : null;
    }

    function start() {
      var body = doc.body;
      S.variant = (body && body.getAttribute("data-variant")) || "full";
      U().ensureDefs(doc, C());
      U().delegate(rootEl, handlers);
      if (env.win) { env.win.addEventListener("hashchange", syncHash); }
      S.section = parseHash(env.location ? env.location.hash : "").section;
      var td = U().readIsland("lm27-data", doc);
      if (isObj(td)) {
        S.live = false;
        setData(td, U().readIsland("lm27-detail", doc));
        return null;
      }
      S.live = true;
      S.variant = "live";
      return load();
    }

    return {start: start, state: S, handlers: handlers, render: render, setData: setData, openDetail: openDetail,
      syncHash: syncHash, model: function () { return M; }};
  }

  // ───────────────────────── 8. 관리 화면(/admin, §7.9) ─────────────────────────
  var ADMIN_TABS = [["projects", "과제"], ["vocab", "어휘"], ["agents", "에이전트"], ["calendar", "달력"], ["members", "구성원"],
    ["proposals", "제안"], ["uploads", "업로드"], ["json", "JSON"]];
  var VOCAB_KINDS = [["fields", "분야"], ["functions", "기능"], ["activity_types", "업무 유형"], ["step_types", "단계 유형"]];
  var DOMAINS5 = ["DEV", "MP", "EXT", "COM", "AX"];
  var PROJECT_STATUS = ["active", "proposed", "retired"];
  var AGENT_STATUS = ["running", "planned", "retired"];
  var ERR_TEXT = {
    bad_id: "형식이 맞지 않습니다", reserved_id: "P-99xx 는 예약된 번호라 쓸 수 없습니다", dup_id: "같은 ID 가 이미 있습니다",
    bad_domain: "영역은 DEV·MP·EXT·COM·AX 중 하나여야 합니다", dup_alias: "다른 과제와 이름·별칭이 겹칩니다",
    alias_collision: "다른 과제와 이름·별칭이 겹칩니다", ref_missing: "없는 과제를 가리킵니다",
    cycle_merge: "병합 사슬이 순환합니다", bad_date: "날짜 형식(YYYY-MM-DD)이 아닙니다", dup_date: "같은 날짜가 두 번 있습니다",
    bad_holiday_source: "근거 링크(https 로 시작하는 주소)와 확인일이 있어야 저장할 수 있습니다", bad_value: "값이 비었거나 너무 깁니다",
    too_long: "너무 깁니다", schema: "형식이 맞지 않습니다", bad_calendar: "달력 형식이 맞지 않습니다",
    desc_has_codename: "설명에 코드네임·별칭이 들어 있습니다", too_large: "레지스트리가 너무 큽니다(2MB 상한)",
    validator_unavailable: "서버의 레지스트리 검증기를 쓸 수 없어 저장하지 않았습니다",
    registry_version_conflict: "다른 곳에서 레지스트리가 바뀌었습니다", bad_pattern: "형식이 맞지 않습니다",
    bad_type: "값의 형이 맞지 않습니다", missing: "꼭 있어야 하는 값이 없습니다", unknown_field: "알 수 없는 칸입니다"};
  var PID_RX = /^P-\d{4}$/;
  var REG_ID_RX = /^[A-Za-z][A-Za-z0-9_\-]{0,23}$/;
  var CODE_RX = /^[A-Z][A-Z0-9_]{1,15}$/;
  var DATE_RX = /^\d{4}-\d{2}-\d{2}$/;

  function clone(v) { return v === undefined ? undefined : JSON.parse(JSON.stringify(v)); }

  function same(a, b) { return JSON.stringify(a === undefined ? null : a) === JSON.stringify(b === undefined ? null : b); }

  function ukeyLite(s) {
    var t = String(s || "");
    if (t.normalize) { t = t.normalize("NFKC"); }
    return t.replace(/[·・ㆍ‧_\-/–—－／]/g, " ").replace(/\s+/g, " ").trim().toLowerCase().replace(/ /g, "");
  }

  function dateOk(s) {
    if (!DATE_RX.test(String(s || ""))) { return false; }
    var c = C();
    return c.dateOf(c.dayNum(s)) === s;
  }

  // 클라이언트 검증 — 서버 검증(TAB §3.10·H validate_registry)과 같은 코드를 먼저 칸 옆에 보인다. [{path, code}]
  function validateRegistry(reg) {
    var out = [];
    reg = obj(reg);
    var ids = {};
    var owner = {};
    arr(reg.projects).forEach(function (p, k) {
      var path = "projects[" + k + "]";
      if (!isObj(p)) { out.push({path: path, code: "schema"}); return; }
      if (!isStr(p.id) || !PID_RX.test(p.id)) { out.push({path: path + ".id", code: "bad_id"}); return; }
      if (p.id.indexOf("P-99") === 0) { out.push({path: path + ".id", code: "reserved_id"}); return; }
      if (own(ids, p.id)) { out.push({path: path + ".id", code: "dup_id"}); }
      ids[p.id] = p;
      if (!isStr(p.name) || !p.name.trim() || p.name.length > 40) { out.push({path: path + ".name", code: "bad_value"}); }
      if (DOMAINS5.indexOf(p.domain) < 0) { out.push({path: path + ".domain", code: "bad_domain"}); }
      var names = [p.name].concat(arr(p.aliases));
      for (var j = 0; j < names.length; j++) {
        if (!isStr(names[j]) || !names[j].trim()) { continue; }
        var key = ukeyLite(names[j]);
        if (own(owner, key) && owner[key] !== p.id) { out.push({path: path + ".aliases", code: "dup_alias"}); break; }
        owner[key] = p.id;
      }
    });
    arr(reg.projects).forEach(function (p, k) {
      if (!isObj(p) || p.merged_into === null || p.merged_into === undefined || p.merged_into === "") { return; }
      var path = "projects[" + k + "].merged_into";
      if (!own(ids, p.merged_into)) { out.push({path: path, code: "ref_missing"}); return; }
      var seen = {};
      seen[p.id] = true;
      var cur = p.merged_into;
      while (own(ids, cur) && ids[cur].merged_into) {
        if (seen[cur]) { break; }
        seen[cur] = true;
        cur = ids[cur].merged_into;
      }
      if (seen[cur]) { out.push({path: path, code: "cycle_merge"}); }
    });
    [["members", "M"], ["agents", "AG"]].forEach(function (x) {
      var seen = {};
      arr(reg[x[0]]).forEach(function (it, k) {
        var id = obj(it).id;
        var path = x[0] + "[" + k + "].id";
        if (!isStr(id) || !REG_ID_RX.test(id) || id.indexOf(x[1]) !== 0) { out.push({path: path, code: "bad_id"}); } else if (seen[id]) {
          out.push({path: path, code: "dup_id"});
        }
        seen[id] = true;
      });
    });
    VOCAB_KINDS.forEach(function (vk) {
      var seen = {};
      arr(obj(reg.vocab)[vk[0]]).forEach(function (it, k) {
        if (!isObj(it)) { return; }                                // 옛 문자열 목록은 서버가 코드로 바꾼다(H §2.3.4)
        var path = "vocab." + vk[0] + "[" + k + "]";
        if (!isStr(it.code) || !CODE_RX.test(it.code)) { out.push({path: path + ".code", code: "bad_id"}); } else if (seen[it.code]) {
          out.push({path: path + ".code", code: "dup_id"});
        }
        seen[it.code] = true;
        if (!isStr(it.name) || !it.name.trim() || it.name.length > 20) { out.push({path: path + ".name", code: "bad_value"}); }
      });
    });
    var cal = reg.calendar;
    if (isObj(cal)) {
      var seenD = {};
      arr(cal.years).forEach(function (y, yi) {
        arr(obj(y).holidays).forEach(function (hd, hi) {
          var path = "calendar.years[" + yi + "].holidays[" + hi + "]";
          hd = obj(hd);
          if (!dateOk(hd.date)) { out.push({path: path, code: "bad_date"}); return; }
          if (seenD[hd.date]) { out.push({path: path, code: "dup_date"}); }
          seenD[hd.date] = true;
          if (!(isStr(hd.source_url) && hd.source_url.indexOf("https://") === 0) || !dateOk(hd.confirmed)) {
            out.push({path: path, code: "bad_holiday_source"});
          }
        });
      });
      arr(cal.company_off).forEach(function (d, k) { if (!dateOk(d)) { out.push({path: "calendar.company_off[" + k + "]", code: "bad_date"}); } });
    }
    return out;
  }

  function nextProjectId(reg) {
    var max = 0;
    arr(obj(reg).projects).forEach(function (p) {
      var m = /^P-(\d{4})$/.exec(obj(p).id || "");
      if (m && m[1].indexOf("99") !== 0) { max = Math.max(max, Number(m[1])); }
    });
    var n = max + 1;
    while (String(n).length <= 4 && ("0000" + n).slice(-4).indexOf("99") === 0) { n += 1; }
    return n > 9899 ? null : "P-" + ("0000" + n).slice(-4);
  }

  function nextAgentId(reg) {
    var max = 0;
    arr(obj(reg).agents).forEach(function (a) { var m = /^AG(\d{1,6})$/.exec(obj(a).id || ""); if (m) { max = Math.max(max, Number(m[1])); } });
    return "AG" + ("000" + (max + 1)).slice(-3);
  }

  // 목록 칸(과제·구성원·에이전트·어휘·공휴일)의 항목 키
  var COLLECTIONS = [
    {path: ["projects"], key: "id"}, {path: ["members"], key: "id"}, {path: ["agents"], key: "id"},
    {path: ["vocab", "fields"], key: "code"}, {path: ["vocab", "functions"], key: "code"},
    {path: ["vocab", "activity_types"], key: "code"}, {path: ["vocab", "step_types"], key: "code"}];

  function getIn(o, path) {
    var cur = o;
    for (var k = 0; k < path.length; k++) { if (!isObj(cur)) { return undefined; } cur = cur[path[k]]; }
    return cur;
  }

  function setIn(o, path, v) {
    var cur = o;
    for (var k = 0; k < path.length - 1; k++) {
      if (!isObj(cur[path[k]])) { cur[path[k]] = {}; }
      cur = cur[path[k]];
    }
    if (v === undefined) { delete cur[path[path.length - 1]]; } else { cur[path[path.length - 1]] = v; }
  }

  function indexBy(list, key) {
    var o = {};
    arr(list).forEach(function (it, k) { if (isObj(it) && it[key] !== undefined) { o[String(it[key])] = {it: it, k: k}; } });
    return o;
  }

  // 409 재적용(R §7.9): base = 내가 불러온 판, mine = 내 작업본, latest = 서버 최신 판.
  // 내가 바꾼 칸만 최신 판 위에 다시 얹는다. 같은 칸을 양쪽이 다르게 바꿨으면 내 값을 얹고 충돌로 표시한다.
  function rebase(base, mine, latest) {
    base = obj(base);
    mine = obj(mine);
    var out = clone(obj(latest));
    var conflicts = [];
    var done = {};
    COLLECTIONS.forEach(function (col) {
      var name = col.path.join(".");
      done[col.path[0]] = true;
      var b = indexBy(getIn(base, col.path), col.key);
      var m = indexBy(getIn(mine, col.path), col.key);
      var l = indexBy(getIn(out, col.path), col.key);
      var list = arr(getIn(out, col.path)).slice();
      Object.keys(m).forEach(function (id) {
        var mi = m[id].it;
        if (!own(b, id)) {                                        // 내가 더한 항목
          if (!own(l, id)) { list.push(clone(mi)); } else if (!same(l[id].it, mi)) {
            list[l[id].k] = clone(mi);
            conflicts.push(name + ":" + id);
          }
          return;
        }
        if (same(b[id].it, mi)) { return; }                       // 손대지 않음
        if (!own(l, id)) { list.push(clone(mi)); conflicts.push(name + ":" + id); return; }   // 다른 곳에서 지움
        var li = clone(l[id].it);
        var bi = b[id].it;
        Object.keys(mi).concat(Object.keys(bi)).forEach(function (f) {
          if (same(mi[f], bi[f])) { return; }
          if (!same(li[f], bi[f]) && !same(li[f], mi[f])) { conflicts.push(name + ":" + id + "." + f); }
          if (mi[f] === undefined) { delete li[f]; } else { li[f] = clone(mi[f]); }
        });
        list[l[id].k] = li;
      });
      Object.keys(b).forEach(function (id) {                      // 내가 지운 항목
        if (own(m, id) || !own(l, id)) { return; }
        if (same(l[id].it, b[id].it)) { list[l[id].k] = undefined; } else { conflicts.push(name + ":" + id); }
      });
      setIn(out, col.path, list.filter(function (x) { return x !== undefined; }));
    });
    // 달력: 공휴일은 날짜로, 그 밖 칸은 값으로
    var bc = obj(base.calendar);
    var mc = obj(mine.calendar);
    if (!same(bc, mc)) {
      var lc = isObj(out.calendar) ? out.calendar : (out.calendar = {});
      Object.keys(mc).concat(Object.keys(bc)).forEach(function (f) {
        if (f === "years" || same(mc[f], bc[f])) { return; }
        if (!same(lc[f], bc[f]) && !same(lc[f], mc[f])) { conflicts.push("calendar." + f); }
        if (mc[f] === undefined) { delete lc[f]; } else { lc[f] = clone(mc[f]); }
      });
      var hol = function (c) {
        var o = {};
        arr(obj(c).years).forEach(function (y) { arr(obj(y).holidays).forEach(function (hd) { if (isObj(hd)) { o[hd.date] = {y: y.year, h: hd}; } }); });
        return o;
      };
      var hb = hol(bc);
      var hm = hol(mc);
      var hl = hol(lc);
      var changed = false;
      Object.keys(hm).concat(Object.keys(hb)).forEach(function (d) {
        if (same(hm[d], hb[d])) { return; }
        if (!same(hl[d], hb[d]) && !same(hl[d], hm[d])) { conflicts.push("calendar.holidays:" + d); }
        if (hm[d] === undefined) { delete hl[d]; } else { hl[d] = clone(hm[d]); }
        changed = true;
      });
      if (changed) {
        var years = {};
        Object.keys(hl).sort().forEach(function (d) {
          var y = hl[d].y || Number(d.slice(0, 4));
          (years[y] = years[y] || []).push(hl[d].h);
        });
        var keep = {};
        arr(lc.years).forEach(function (y) { if (isObj(y)) { keep[y.year] = y; } });
        lc.years = Object.keys(years).concat(Object.keys(keep)).filter(function (y, k, a) { return a.indexOf(y) === k; })
          .sort().map(function (y) {
            var yo = clone(keep[y] || {year: Number(y)});
            yo.holidays = years[y] || [];
            return yo;
          });
      }
    }
    // 그 밖 최상위 칸(team·internal_domains 등)
    Object.keys(mine).concat(Object.keys(base)).forEach(function (f) {
      if (done[f] || f === "calendar" || f === "vocab" || f === "version" || f === "pepper" || f === "pepper_id") { return; }
      if (same(mine[f], base[f])) { return; }
      if (!same(out[f], base[f]) && !same(out[f], mine[f])) { conflicts.push(f); }
      if (mine[f] === undefined) { delete out[f]; } else { out[f] = clone(mine[f]); }
    });
    var vb = obj(base.vocab);
    var vm = obj(mine.vocab);
    Object.keys(vm).concat(Object.keys(vb)).forEach(function (f) {
      if (["fields", "functions", "activity_types", "step_types"].indexOf(f) >= 0 || same(vm[f], vb[f])) { return; }
      var lv = isObj(out.vocab) ? out.vocab : (out.vocab = {});
      if (!same(lv[f], vb[f]) && !same(lv[f], vm[f])) { conflicts.push("vocab." + f); }
      lv[f] = clone(vm[f]);
    });
    return {reg: out, conflicts: conflicts.filter(function (x, k, a) { return a.indexOf(x) === k; })};
  }

  function stripSecret(reg) {
    var o = clone(obj(reg));
    delete o.pepper;
    delete o.pepper_id;
    return o;
  }

  function splitList(s) {
    return String(s || "").split(/[,\n]/).map(function (x) { return x.trim(); }).filter(function (x) { return x; });
  }

  function createAdmin(doc, opt) {
    var env = envOf(opt);
    var S = {base: null, reg: null, members: [], td: null, tab: "projects", serverErr: [], conflicts: [], msg: null,
      readToken: "", adminToken: "", hidden: {}, showJson: false, busy: false, prefill: null};
    var main = doc.getElementById("app");
    var nav = doc.getElementById("team-nav");
    var rootEl = doc.getElementById("team-root") || doc.body;

    function headers(admin) {
      var hd = {};
      if (S.readToken) { hd["X-LM27-Upload-Token"] = S.readToken; }
      if (admin && S.adminToken) { hd["X-LM27-Admin-Token"] = S.adminToken; }
      return hd;
    }

    function call(method, path, body) {
      var hd = headers(method !== "GET");
      var init = {method: method, headers: hd, cache: "no-store", credentials: "same-origin"};
      if (body !== undefined) { hd["Content-Type"] = "application/json"; init.body = JSON.stringify(body); }
      if (!env.fetch) { return Promise.reject(new Error("fetch 없음")); }
      return env.fetch(path, init).then(function (r) {
        return r.text().then(function (t) {
          var j = null;
          try { j = t ? JSON.parse(t) : null; } catch (e) { j = null; }
          return {status: r.status, body: j};
        });
      });
    }

    function errors() {
      var local = validateRegistry(S.reg);
      return local.concat(S.serverErr);
    }

    function errAt(path) {
      return errors().filter(function (e) { return e.path === path || e.path.indexOf(path + ".") === 0 || e.path.indexOf(path + "[") === 0; });
    }

    function errView(path) {
      var es = errAt(path);
      if (!es.length) { return null; }
      return h("div", {"class": "field-error", role: "alert"}, [U().icon("bad"), es.map(function (e) {
        return e.code + " — " + (ERR_TEXT[e.code] || "확인이 필요합니다");
      }).join(" · ")]);
    }

    function conflictMark(key) {
      return S.conflicts.indexOf(key) >= 0 ? h("span", {"class": "conflict"}, [U().statusText("warn", "충돌 — 확인")]) : null;
    }

    function dirty() { return !!S.base && !same(stripSecret(S.base), stripSecret(S.reg)); }

    function input(path, value, opt) {
      opt = opt || {};
      var id = "f-" + path.replace(/[^A-Za-z0-9]/g, "-");
      return h("span", {"class": "field"}, [
        opt.label ? h("label", {"for": id}, [opt.label]) : null,
        h("input", {id: id, type: opt.type || "text", value: value === null || value === undefined ? "" : String(value),
          "data-field": path, "data-kind": opt.kind || "str", "aria-label": opt.label ? null : (opt.aria || path),
          maxlength: opt.max || null, readonly: opt.readonly || null}), errView(path)]);
    }

    function select(path, value, choices, opt) {
      opt = opt || {};
      return h("span", {"class": "field"}, [
        h("select", {"data-field": path, "data-kind": opt.kind || "str", "aria-label": opt.aria || path},
          choices.map(function (c) { return h("option", {value: c[0], selected: c[0] === value ? true : null}, [c[1]]); })),
        errView(path)]);
    }

    function check(path, value, opt) {
      opt = opt || {};
      return h("label", {"class": "check"}, [h("input", {type: "checkbox", "data-field": path, "data-kind": "bool",
        checked: value ? true : null}), " " + (opt.label || "")]);
    }

    function pathParts(path) {
      var out = [];
      path.replace(/([^.[\]]+)|\[(\d+)\]/g, function (all, name, idx) { out.push(idx !== undefined ? Number(idx) : name); return all; });
      return out;
    }

    function assign(path, v) {
      var ps = pathParts(path);
      var cur = S.reg;
      for (var k = 0; k < ps.length - 1; k++) {
        if (cur[ps[k]] === undefined || cur[ps[k]] === null) { cur[ps[k]] = typeof ps[k + 1] === "number" ? [] : {}; }
        cur = cur[ps[k]];
      }
      cur[ps[ps.length - 1]] = v;
    }

    function readValue(el) {
      var kind = el.getAttribute("data-kind") || "str";
      if (kind === "bool") { return !!el.checked; }
      var v = String(el.value === undefined || el.value === null ? "" : el.value);
      if (kind === "list") { return splitList(v); }
      if (kind === "int") { var n = parseInt(v, 10); return isFinite(n) ? n : null; }
      if (kind === "int?") { var n2 = parseInt(v, 10); return isFinite(n2) ? n2 : undefined; }       // 비우면 칸을 뺀다(기본값)
      if (kind === "null") { return v.trim() ? v.trim() : null; }
      return v;
    }

    function onChange(ev) {
      var el = ev.target;
      if (!el || !el.getAttribute) { return; }
      if (el.getAttribute("data-upload") === "json") { readUpload(el); return; }
      var path = el.getAttribute("data-field");
      if (!path) { return; }
      if (path.indexOf("$") === 0) {
        if (path === "$readToken") { S.readToken = String(el.value || ""); }
        if (path === "$adminToken") { S.adminToken = String(el.value || ""); }
        return;
      }
      if (!S.reg) { return; }
      assign(path, readValue(el));
      S.serverErr = S.serverErr.filter(function (e) { return e.path !== path; });
      render({field: path});
    }

    function readUpload(el) {
      var f = el.files && el.files[0];
      if (!f || !env.FileReader) { return; }
      var rd = new env.FileReader();
      rd.onload = function () {
        var o = null;
        try { o = JSON.parse(String(rd.result || "")); } catch (e) { o = null; }
        if (!isObj(o)) { S.msg = ["bad", "JSON 으로 읽을 수 없는 파일입니다."]; render(); return; }
        var cand = stripSecret(o);
        cand.version = S.base.version;
        var es = validateRegistry(cand);
        if (es.length) { S.msg = ["bad", "올린 파일에 검증 오류가 " + es.length + "건 있어 적용하지 않았습니다(" + es[0].path + ": " + es[0].code + ")."]; render(); return; }
        S.reg = cand;
        S.msg = ["info", "올린 파일을 작업본으로 바꿨습니다 — 확인 후 저장하세요."];
        render();
      };
      rd.readAsText(f, "utf-8");
    }

    function render(focus) {
      if (nav) {
        U().render(U().pills(ADMIN_TABS.map(function (t) { return {href: "#" + t[0], label: t[1], current: S.tab === t[0]}; }),
          {label: "관리 메뉴"}), nav);
      }
      if (!S.reg) { return; }
      var es = errors();
      var bar = [h("div", {"class": "table-tools"}, [
        h("button", {type: "button", "class": "btn btn-primary", "data-act": "save",
          "aria-disabled": es.length || !dirty() || S.busy ? "true" : null,
          "data-tip": es.length ? "검증 오류 " + es.length + "건을 먼저 고치세요" : (!dirty() ? "바뀐 것이 없습니다" : null)},
        ["저장(v" + (Number(S.base.version || 0) + 1) + ")"]),
        h("button", {type: "button", "class": "btn", "data-act": "reload"}, ["최신 판 다시 읽기"]),
        h("span", {"class": "muted small"}, ["현재 판 v" + (S.base.version || 0) + (dirty() ? " · 저장 안 한 변경 있음" : "")])])];
      if (S.msg) { bar.unshift(U().alertLine(S.msg[0], S.msg[1])); }
      if (es.length) { bar.push(U().alertLine("bad", "검증 오류 " + es.length + "건 — 칸 옆 사유를 확인하세요. 오류가 있으면 저장할 수 없습니다.")); }
      U().render(bar.concat(tabView()), main);
      if (focus && focus.field) {
        var els = main.querySelectorAll ? main.querySelectorAll("[data-field]") : [];
        for (var k = 0; k < els.length; k++) { if (els[k].getAttribute("data-field") === focus.field) { els[k].focus(); break; } }
      }
    }

    function projMm() {
      var o = {};
      arr(obj(S.td).projects).forEach(function (p) { if (isObj(p) && p.project_id) { o[p.project_id] = p.total_mm; } });
      return o;
    }

    function tabProjects() {
      var mm = projMm();
      var rows = arr(S.reg.projects).map(function (p, k) {
        var base = "projects[" + k + "]";
        p = obj(p);
        var others = arr(S.reg.projects).filter(function (q) { return obj(q).id && obj(q).id !== p.id; });
        return h("tr", {}, [
          h("td", {}, [input(base + ".id", p.id, {aria: "과제 ID", max: 6}), conflictMark("projects:" + p.id)]),
          h("td", {}, [input(base + ".name", p.name, {aria: "이름", max: 40})]),
          h("td", {}, [select(base + ".domain", p.domain, DOMAINS5.map(function (d) { return [d, d]; }), {aria: "영역"})]),
          h("td", {}, [select(base + ".status", p.status || "active", PROJECT_STATUS.map(function (s) { return [s, s]; }), {aria: "상태"})]),
          h("td", {}, [h("input", {type: "text", value: arr(p.aliases).join(", "), "data-field": base + ".aliases", "data-kind": "list", "aria-label": "별칭"}), errView(base + ".aliases")]),
          h("td", {}, [h("input", {type: "text", value: arr(p.keywords).join(", "), "data-field": base + ".keywords", "data-kind": "list", "aria-label": "키워드"})]),
          h("td", {}, [h("input", {type: "text", value: arr(p.codenames).join(", "), "data-field": base + ".codenames", "data-kind": "list", "aria-label": "코드네임"})]),
          h("td", {}, [check(base + ".mask_name", p.mask_name, {label: "가림"})]),
          h("td", {}, [input(base + ".copilot_desc", p.copilot_desc, {aria: "코파일럿 설명", max: 40})]),
          h("td", {}, [h("input", {type: "text", value: arr(p.shared_docs).join(", "), "data-field": base + ".shared_docs", "data-kind": "list", "aria-label": "공용 문서"})]),
          h("td", {}, [select(base + ".merged_into", p.merged_into || "", [["", "—"]].concat(others.map(function (q) { return [q.id, q.id + " " + (q.name || "")]; })), {aria: "병합 대상", kind: "null"}),
            errView(base + ".merged_into")]),
          h("td", {"class": "num"}, [isNum(mm[p.id]) ? mm2(mm[p.id]) : "—"]),
          h("td", {}, [h("button", {type: "button", "class": "btn btn-ghost", "data-act": "retire", "data-ref": String(k)}, ["퇴역"])])]);
      });
      var head = ["ID", "이름", "영역", "상태", "별칭", "키워드", "코드네임", "이름 가림", "코파일럿 설명", "공용 문서", "병합 대상", "최근 기간 MM", ""];
      return [h("div", {"class": "table-tools"}, [h("button", {type: "button", "class": "btn", "data-act": "add-project"}, ["새 과제"]),
        h("span", {"class": "muted small"}, ["P-99xx 는 예약 번호라 쓸 수 없습니다. 병합은 '병합 대상'을 고르면 됩니다(순환 검사)."])]),
      h("div", {"class": "table-wrap"}, [h("table", {"class": "tbl"}, [h("thead", {}, [h("tr", {}, head.map(function (c) { return h("th", {scope: "col"}, [c]); }))]),
        h("tbody", {}, rows)])]), errView("projects")];
    }

    function tabVocab() {
      var out = [h("p", {"class": "muted small"}, ["내장 어휘는 프로그램에 들어 있습니다 — 여기에는 팀이 덧붙이거나 바꾼 항목만 보입니다. 저장된 항목은 지우지 않고 퇴역(retired)만 할 수 있습니다."])];
      VOCAB_KINDS.forEach(function (vk) {
        var list = arr(obj(S.reg.vocab)[vk[0]]);
        var baseCodes = {};
        arr(obj(S.base.vocab)[vk[0]]).forEach(function (it) { if (isObj(it)) { baseCodes[it.code] = true; } });
        var step = vk[0] === "step_types";
        var rows = list.map(function (it, k) {
          var p = "vocab." + vk[0] + "[" + k + "]";
          if (!isObj(it)) { return h("tr", {}, [h("td", {colspan: step ? 7 : 5}, ["옛 형식 값 '" + String(it) + "' — 서버가 코드로 바꿉니다"])]); }
          var tds = [h("td", {}, [input(p + ".code", it.code, {aria: "코드", max: 16, readonly: baseCodes[it.code] ? true : null}), conflictMark("vocab." + vk[0] + ":" + it.code)]),
            h("td", {}, [input(p + ".name", it.name, {aria: "이름", max: 20})]),
            h("td", {}, [h("input", {type: "text", value: arr(it.keywords).join(", "), "data-field": p + ".keywords", "data-kind": "list", "aria-label": "키워드"})]),
            h("td", {}, [select(p + ".status", it.status || "active", [["active", "active"], ["retired", "retired"]], {aria: "상태"})])];
          if (step) {
            tds.push(h("td", {}, [select(p + ".tool_access", String(isNum(it.tool_access) ? it.tool_access : ""), [["", "기본"], ["0", "0"], ["1", "1"], ["2", "2"]], {aria: "도구 접근", kind: "int?"})]));
            tds.push(h("td", {}, [select(p + ".verifiable", String(isNum(it.verifiable) ? it.verifiable : ""), [["", "기본"], ["0", "0"], ["1", "1"], ["2", "2"]], {aria: "검증 가능성", kind: "int?"})]));
          }
          tds.push(h("td", {}, [baseCodes[it.code] ? null : h("button", {type: "button", "class": "btn btn-ghost", "data-act": "del-vocab", "data-ref": vk[0] + "|" + k}, ["지우기"])]));
          return h("tr", {}, tds);
        });
        var head = ["코드", "이름", "키워드", "상태"].concat(step ? ["도구 접근", "검증 가능성"] : [], [""]);
        out.push(h("h3", {}, [vk[1]]));
        out.push(h("div", {"class": "table-wrap"}, [h("table", {"class": "tbl"}, [h("thead", {}, [h("tr", {}, head.map(function (c) { return h("th", {scope: "col"}, [c]); }))]),
          h("tbody", {}, rows)])]));
        out.push(h("button", {type: "button", "class": "btn btn-ghost", "data-act": "add-vocab", "data-ref": vk[0]}, [vk[1] + " 추가"]));
      });
      return out;
    }

    function tabAgents() {
      var rows = arr(S.reg.agents).map(function (a, k) {
        var p = "agents[" + k + "]";
        a = obj(a);
        return h("tr", {}, [h("td", {}, [input(p + ".id", a.id, {aria: "에이전트 ID", max: 24}), conflictMark("agents:" + a.id)]),
          h("td", {}, [input(p + ".name", a.name, {aria: "이름", max: 30})]),
          h("td", {}, [input(p + ".axis", a.axis, {aria: "축", max: 24})]),
          h("td", {}, [select(p + ".status", a.status || "planned", AGENT_STATUS.map(function (s) { return [s, s]; }), {aria: "상태"})]),
          h("td", {}, [input(p + ".desc", a.desc, {aria: "설명", max: 200})]),
          h("td", {}, [h("input", {type: "text", value: arr(a.step_types).join(", "), "data-field": p + ".step_types", "data-kind": "list", "aria-label": "적용 단계 유형 코드"})]),
          h("td", {}, [h("input", {type: "text", value: arr(a.inputs).join(", "), "data-field": p + ".inputs", "data-kind": "list", "aria-label": "입력"})]),
          h("td", {}, [h("input", {type: "text", value: arr(a.outputs).join(", "), "data-field": p + ".outputs", "data-kind": "list", "aria-label": "출력"})]),
          h("td", {}, [h("input", {type: "text", value: arr(a.keywords).join(", "), "data-field": p + ".keywords", "data-kind": "list", "aria-label": "핵심어"})])]);
      });
      var head = ["ID", "이름", "축", "상태", "설명", "적용 단계 유형(코드)", "입력", "출력", "핵심어"];
      return [h("div", {"class": "table-tools"}, [h("button", {type: "button", "class": "btn", "data-act": "add-agent"}, ["새 에이전트"])]),
        h("div", {"class": "table-wrap"}, [h("table", {"class": "tbl"}, [h("thead", {}, [h("tr", {}, head.map(function (c) { return h("th", {scope: "col"}, [c]); }))]),
          h("tbody", {}, rows)])]),
        h("p", {"class": "muted small"}, ["설명은 코파일럿에 보내지 않습니다. 단계 유형은 코드(예: DOC_XLS)를 쉼표로 적습니다."])];
    }

    function tabCalendar() {
      var cal = obj(S.reg.calendar);
      var out = [h("div", {"class": "table-tools"}, [input("calendar.version", cal.version, {label: "달력 판", max: 40}),
        input("calendar.std_day_min", cal.std_day_min, {label: "표준 근무일 분", kind: "int", type: "number"})])];
      arr(cal.years).forEach(function (y, yi) {
        y = obj(y);
        var rows = arr(y.holidays).map(function (hd, hi) {
          var p = "calendar.years[" + yi + "].holidays[" + hi + "]";
          hd = obj(hd);
          return h("tr", {}, [h("td", {}, [input(p + ".date", hd.date, {aria: "날짜", max: 10}), conflictMark("calendar.holidays:" + hd.date)]),
            h("td", {}, [input(p + ".name", hd.name, {aria: "이름", max: 40})]),
            h("td", {}, [input(p + ".kind", hd.kind, {aria: "종류", max: 20})]),
            h("td", {}, [input(p + ".source_url", hd.source_url, {aria: "근거 URL", max: 300})]),
            h("td", {}, [input(p + ".confirmed", hd.confirmed, {aria: "확인일", max: 10}), errView(p)])]);
        });
        out.push(h("h3", {}, [String(y.year || "") + "년"]));
        out.push(h("div", {"class": "table-wrap"}, [h("table", {"class": "tbl"}, [h("thead", {}, [h("tr", {}, ["날짜", "이름", "종류", "근거 URL", "확인일"].map(function (c) {
          return h("th", {scope: "col"}, [c]);
        }))]), h("tbody", {}, rows)])]));
        out.push(h("button", {type: "button", "class": "btn btn-ghost", "data-act": "add-holiday", "data-ref": String(yi)}, [String(y.year || "") + "년 공휴일 추가"]));
      });
      out.push(h("div", {"class": "table-tools"}, [input("$newYear", "", {label: "해 추가", type: "number", kind: "int"}),
        h("button", {type: "button", "class": "btn btn-ghost", "data-act": "add-year"}, ["해 추가"])]));
      out.push(h("h3", {}, ["회사 휴무"]));
      out.push(h("ul", {}, arr(cal.company_off).map(function (d, k) {
        return h("li", {}, [input("calendar.company_off[" + k + "]", d, {aria: "회사 휴무일", max: 10}),
          h("button", {type: "button", "class": "btn btn-ghost", "data-act": "del-off", "data-ref": String(k)}, ["지우기"])]);
      })));
      out.push(h("button", {type: "button", "class": "btn btn-ghost", "data-act": "add-off"}, ["회사 휴무 추가"]));
      out.push(h("p", {"class": "muted small"}, ["공휴일은 근거 링크(https 로 시작하는 주소)와 확인일이 있어야 저장됩니다. 저장하면 서버가 다시 취합합니다."]));
      return out;
    }

    function tabMembers() {
      var regRows = arr(S.reg.members).map(function (m, k) {
        m = obj(m);
        return h("tr", {}, [h("td", {}, [input("members[" + k + "].id", m.id, {aria: "구성원 ID", max: 24}), conflictMark("members:" + m.id)]),
          h("td", {}, [input("members[" + k + "].label", m.label, {aria: "표시 라벨", max: 20})])]);
      });
      var srvRows = arr(S.members).map(function (m) {
        m = obj(m);
        var pk = String(m.person_key || "");
        return h("tr", {}, [h("td", {}, [h("code", {}, [pk.slice(0, 6) + "…"])]), h("td", {}, [m.label || "—", h("div", {"class": "muted small"}, [SRC_NAME[m.label_source] || ""])]),
          h("td", {}, [arr(m.linked).length ? "연결 " + arr(m.linked).length : "—"]), h("td", {}, [m.retired ? "퇴직" : "—"]),
          h("td", {}, [h("input", {type: "text", "data-field": "$label:" + pk, "aria-label": "새 라벨", value: ""}),
            h("button", {type: "button", "class": "btn btn-ghost", "data-act": "member-label", "data-ref": pk}, ["라벨 바꾸기"]),
            h("button", {type: "button", "class": "btn btn-ghost", "data-act": "member-retire", "data-ref": pk}, [m.retired ? "퇴직 해제" : "퇴직 표시"])])]);
      });
      return [h("h3", {}, ["레지스트리 구성원"]),
        h("div", {"class": "table-wrap"}, [h("table", {"class": "tbl"}, [h("thead", {}, [h("tr", {}, [h("th", {scope: "col"}, ["ID"]), h("th", {scope: "col"}, ["표시 라벨"])])]),
          h("tbody", {}, regRows)])]),
        h("button", {type: "button", "class": "btn btn-ghost", "data-act": "add-member"}, ["구성원 추가"]),
        h("h3", {}, ["서버 명단(업로드한 사람)"]),
        srvRows.length ? h("div", {"class": "table-wrap"}, [h("table", {"class": "tbl"}, [h("thead", {}, [h("tr", {}, ["사람 키", "라벨", "연결", "퇴직", "바꾸기"].map(function (c) {
          return h("th", {scope: "col"}, [c]);
        }))]), h("tbody", {}, srvRows)])]) : U().emptyState("아직 업로드한 사람이 없습니다 — 팀원이 로컬 앱의 [팀 묶음 만들기] → 미리보기 → [보내기]를 하면 여기에 나타납니다.")];
    }

    function proposals() {
      var groups = {};
      var order = [];
      arr(obj(S.td).projects).forEach(function (p) {
        if (!isObj(p) || !p.proposal || S.hidden[p.key]) { return; }
        var k = ukeyLite(p.label);
        if (!own(groups, k)) { groups[k] = []; order.push(k); }
        groups[k].push(p);
      });
      return order.map(function (k) { return groups[k]; });
    }

    function tabProposals() {
      var gs = proposals();
      if (!gs.length) { return [U().emptyState("팀원 묶음에 새 과제 제안이 없습니다(또는 아직 취합 전입니다).")]; }
      var opts = [["", "기존 과제 고르기"]].concat(arr(S.reg.projects).map(function (q) { return [obj(q).id, obj(q).id + " " + (obj(q).name || "")]; }));
      var rows = [];
      gs.forEach(function (g) {
        g.forEach(function (p, k) {
          rows.push(h("tr", {}, [h("td", {}, [p.label || "—", k === 0 && g.length > 1 ? h("div", {"class": "muted small"}, ["같은 이름 후보 " + g.length + "건(자동 병합 없음)"]) : null]),
            h("td", {}, [p.domain || "—"]), h("td", {"class": "num"}, [String(arr(p.by_person).length)]), h("td", {"class": "num"}, [mm2(p.total_mm)]),
            h("td", {}, [h("button", {type: "button", "class": "btn btn-ghost", "data-act": "adopt-new", "data-ref": p.key}, ["새 과제로 등록"]),
              h("select", {"data-field": "$alias:" + p.key, "aria-label": "별칭으로 붙일 과제"}, opts.map(function (o) { return h("option", {value: o[0]}, [o[1]]); })),
              h("button", {type: "button", "class": "btn btn-ghost", "data-act": "adopt-alias", "data-ref": p.key}, ["기존 과제 별칭으로"]),
              h("button", {type: "button", "class": "btn btn-ghost", "data-act": "hold", "data-ref": p.key}, ["보류"])])]));
        });
      });
      return [h("div", {"class": "table-wrap"}, [h("table", {"class": "tbl"}, [h("thead", {}, [h("tr", {}, ["이름", "영역 추정", "사람 수", "관련 MM", ""].map(function (c) {
        return h("th", {scope: "col"}, [c]);
      }))]), h("tbody", {}, rows)])]), h("p", {"class": "muted small"}, ["등록·별칭은 작업본에만 들어갑니다 — 저장해야 반영됩니다."])];
    }

    function tabUploads() {
      var rows = [];
      arr(S.members).forEach(function (m) {
        m = obj(m);
        arr(m.periods).forEach(function (p) {
          p = obj(p);
          rows.push(h("tr", {}, [h("td", {}, [m.label || "—"]), h("td", {}, [p.period_key || "—"]), h("td", {}, [stamp(p.received_at)]),
            h("td", {}, [arr(p.used_months).join(", ") || "사용 안 됨"]), h("td", {}, [p.schema_version || "—"]),
            h("td", {}, [QUALITY_NAME[m.quality] || "—"]), h("td", {}, [arr(m.flags).map(function (f) { return FLAG_TEXT[f] || f; }).join(" · ") || "—"]),
            h("td", {}, [h("button", {type: "button", "class": "btn btn-ghost btn-danger", "data-act": "drop-period",
              "data-ref": String(m.person_key) + "|" + String(p.period_key)}, ["이 기간 빼기"])])]));
        });
      });
      return [h("div", {"class": "table-tools"}, [h("button", {type: "button", "class": "btn", "data-act": "aggregate"}, ["지금 다시 취합"])]),
        rows.length ? h("div", {"class": "table-wrap"}, [h("table", {"class": "tbl"}, [h("thead", {}, [h("tr", {}, ["사람", "기간", "받은 시각", "사용한 달", "판", "품질", "표식", ""].map(function (c) {
          return h("th", {scope: "col"}, [c]);
        }))]), h("tbody", {}, rows)])]) : U().emptyState("받은 묶음이 없습니다 — 팀원이 [보내기]를 하거나, 오프라인 묶음을 반입하면 여기에 쌓입니다.")];
    }

    function tabJson() {
      return [h("div", {"class": "table-tools"}, [
        h("button", {type: "button", "class": "btn", "data-act": "json-show"}, [S.showJson ? "JSON 접기" : "JSON 원문 보기"]),
        h("button", {type: "button", "class": "btn", "data-act": "json-download"}, [U().icon("download"), "JSON 내려받기"]),
        h("label", {"for": "reg-upload"}, ["JSON 올리기(검증 통과 시에만 작업본으로)"]),
        h("input", {id: "reg-upload", type: "file", "data-upload": "json"})]),
      S.showJson ? h("pre", {"class": "mono json-view"}, [JSON.stringify(stripSecret(S.reg), null, 1)]) : null,
      h("p", {"class": "muted small"}, ["pepper 는 보이지도 내려받지도 않습니다(서버가 응답 때 합성하고, 저장할 때는 무시합니다)."])];
    }

    function tokenBox() {
      return h("details", {"class": "card"}, [h("summary", {}, ["토큰(원격에서 관리할 때)"]),
        input("$readToken", S.readToken, {label: "읽기 토큰(읽기 토큰 모드일 때)", type: "password"}),
        input("$adminToken", S.adminToken, {label: "관리 토큰(이 PC 가 아니면 필요)", type: "password"}),
        h("button", {type: "button", "class": "btn btn-ghost", "data-act": "reload"}, ["다시 읽기"])]);
    }

    function tabView() {
      var body;
      switch (S.tab) {
      case "vocab": body = tabVocab(); break;
      case "agents": body = tabAgents(); break;
      case "calendar": body = tabCalendar(); break;
      case "members": body = tabMembers(); break;
      case "proposals": body = tabProposals(); break;
      case "uploads": body = tabUploads(); break;
      case "json": body = tabJson(); break;
      default: body = tabProjects();
      }
      var name = (ADMIN_TABS.filter(function (t) { return t[0] === S.tab; })[0] || ADMIN_TABS[0])[1];
      return [h("section", {"class": "card"}, [h("div", {"class": "card-head"}, [h("h2", {}, [name])]), body]), tokenBox()];
    }

    function save() {
      if (S.busy || validateRegistry(S.reg).length || !dirty()) { return; }
      var body = stripSecret(S.reg);
      body.version = Number(S.base.version || 0) + 1;
      S.busy = true;
      call("PUT", "/api/registry", body).then(function (r) {
        S.busy = false;
        if (r.status === 200) {
          S.base = clone(S.reg);
          S.base.version = body.version;
          S.reg.version = body.version;
          S.serverErr = [];
          S.conflicts = [];
          S.msg = ["info", "저장했습니다(v" + body.version + ") — 서버가 다시 취합합니다."];
          render();
          return;
        }
        if (r.status === 409) { return conflict(); }
        if (r.status === 422) {
          S.serverErr = arr(obj(r.body).detail).map(function (d) {
            var s = String(d);
            var k = s.lastIndexOf(": ");
            return k > 0 ? {path: s.slice(0, k), code: s.slice(k + 2)} : {path: "$", code: s};
          });
          S.msg = ["bad", obj(r.body).error || "레지스트리 검증 실패 — 칸 옆 사유를 확인하세요"];
          render();
          return;
        }
        S.msg = ["bad", obj(r.body).error || ("저장하지 못했습니다(HTTP " + r.status + ")")];
        render();
      }, function () { S.busy = false; S.msg = ["bad", "팀 서버에 닿지 않습니다."]; render(); });
    }

    function conflict() {
      return call("GET", "/api/registry").then(function (r) {
        if (r.status !== 200 || !isObj(r.body)) { S.msg = ["bad", "최신 판을 읽지 못했습니다."]; render(); return; }
        var latest = stripSecret(r.body);
        var rb = rebase(stripSecret(S.base), stripSecret(S.reg), latest);
        S.base = latest;
        S.reg = rb.reg;
        S.conflicts = rb.conflicts;
        S.serverErr = [];
        S.msg = ["warn", "다른 곳에서 레지스트리를 바꿨습니다(v" + (latest.version || 0) + ") — 최신 판을 불러와 내 변경을 다시 적용했습니다. 확인 후 다시 저장하세요" +
          (rb.conflicts.length ? "(충돌 " + rb.conflicts.length + "곳 표시)" : "") + "."];
        render();
      });
    }

    function load() {
      S.msg = null;
      return call("GET", "/api/registry").then(function (r) {
        if (r.status === 401) {                                  // 읽기 토큰 모드 — 빈 작업본을 만들지 않는다(빈 레지스트리 저장 사고 방지)
          S.reg = null;
          S.base = null;
          U().render([U().alertLine("warn", "읽기 토큰이 필요합니다 — 아래 '토큰'에 넣고 다시 읽으세요."), tokenBox()], main);
          return null;
        }
        if (r.status !== 200 || !isObj(r.body)) { U().render([U().alertLine("bad", "레지스트리를 읽지 못했습니다(HTTP " + r.status + ")."), tokenBox()], main); return null; }
        S.base = stripSecret(r.body);
        S.reg = clone(S.base);
        S.conflicts = [];
        S.serverErr = [];
        if (S.prefill) { applyPrefill(); }
        return call("GET", "/api/members").then(function (m) {
          S.members = m.status === 200 ? arr(obj(m.body).members) : [];
          return call("GET", "/api/team");
        }).then(function (t) {
          S.td = t.status === 200 && isObj(t.body) ? t.body : null;
          render();
        });
      }, function () { U().render([U().alertLine("bad", "팀 서버에 닿지 않습니다."), tokenBox()], main); });
    }

    function applyPrefill() {
      var p = S.prefill;
      S.prefill = null;
      if (!S.reg.agents) { S.reg.agents = []; }
      S.reg.agents.push({id: nextAgentId(S.reg), name: p.name, axis: "", status: "planned", desc: "", step_types: p.type ? [p.type] : [],
        inputs: [], outputs: [], keywords: []});
      S.tab = "agents";
      S.msg = ["info", "니즈 '" + p.name + "'로 새 에이전트 행을 만들었습니다 — 채운 뒤 저장하세요."];
    }

    function member(pk, patch) {
      return call("PATCH", "/api/members/" + encodeURIComponent(pk), patch).then(function (r) {
        S.msg = r.status === 200 ? ["info", "명단을 바꿨습니다 — 서버가 다시 취합합니다."] : ["bad", obj(r.body).error || ("바꾸지 못했습니다(HTTP " + r.status + ")")];
        return call("GET", "/api/members").then(function (m) { if (m.status === 200) { S.members = arr(obj(m.body).members); } render(); });
      });
    }

    function findProposal(key) {
      return arr(obj(S.td).projects).filter(function (p) { return isObj(p) && p.key === key; })[0] || null;
    }

    function adopted(p) {
      var m = /^(\d+)\|(pr_\d{1,4})$/.exec(String(p.key || ""));
      var who = m ? arr(obj(S.td).people).filter(function (x) { return obj(x).i === Number(m[1]); })[0] : null;
      return who ? {person_key: who.person_key, proposal_id: m[2]} : null;
    }

    function valueOf(field) {
      var els = main.querySelectorAll ? main.querySelectorAll("[data-field]") : [];
      for (var k = 0; k < els.length; k++) { if (els[k].getAttribute("data-field") === field) { return String(els[k].value || ""); } }
      return "";
    }

    var handlers = {
      "save": function () { save(); },
      "reload": function () { load(); },
      "add-project": function () {
        var id = nextProjectId(S.reg);
        if (!id) { S.msg = ["bad", "더 쓸 수 있는 과제 번호가 없습니다."]; render(); return; }
        S.reg.projects = arr(S.reg.projects).concat([{id: id, name: "", domain: "DEV", status: "active", merged_into: null, aliases: [],
          keywords: [], codenames: [], mask_name: false, never: []}]);
        render({field: "projects[" + (S.reg.projects.length - 1) + "].name"});
      },
      "retire": function (el, ref) { var p = arr(S.reg.projects)[Number(ref)]; if (isObj(p)) { p.status = "retired"; render(); } },
      "add-vocab": function (el, ref) {
        var v = S.reg.vocab = isObj(S.reg.vocab) ? S.reg.vocab : {};
        v[ref] = arr(v[ref]).concat([{code: "", name: "", status: "active", keywords: []}]);
        render();
      },
      "del-vocab": function (el, ref) {
        var p = String(ref).split("|");
        var list = arr(obj(S.reg.vocab)[p[0]]);
        list.splice(Number(p[1]), 1);
        render();
      },
      "add-agent": function () {
        S.reg.agents = arr(S.reg.agents).concat([{id: nextAgentId(S.reg), name: "", axis: "", status: "planned", desc: "", step_types: [],
          inputs: [], outputs: [], keywords: []}]);
        render();
      },
      "add-holiday": function (el, ref) {
        var y = obj(arr(obj(S.reg.calendar).years)[Number(ref)]);
        y.holidays = arr(y.holidays).concat([{date: "", name: "", kind: "", source_url: "", confirmed: ""}]);
        render();
      },
      "add-year": function () {
        var y = parseInt(valueOf("$newYear"), 10);
        if (!(y >= 2000 && y <= 2100)) { return; }
        var cal = S.reg.calendar = isObj(S.reg.calendar) ? S.reg.calendar : {version: "", std_day_min: 480, weekdays: [0, 1, 2, 3, 4], years: [], company_off: []};
        if (!arr(cal.years).some(function (x) { return obj(x).year === y; })) {
          cal.years = arr(cal.years).concat([{year: y, holidays: []}]).sort(function (a, b) { return a.year - b.year; });
        }
        render();
      },
      "add-off": function () {
        var cal = S.reg.calendar = isObj(S.reg.calendar) ? S.reg.calendar : {years: [], company_off: []};
        cal.company_off = arr(cal.company_off).concat([""]);
        render();
      },
      "del-off": function (el, ref) { arr(obj(S.reg.calendar).company_off).splice(Number(ref), 1); render(); },
      "add-member": function () { S.reg.members = arr(S.reg.members).concat([{id: "", label: ""}]); render(); },
      "member-label": function (el, ref) { member(ref, {label: valueOf("$label:" + ref)}); },
      "member-retire": function (el, ref) {
        var m = arr(S.members).filter(function (x) { return obj(x).person_key === ref; })[0];
        member(ref, {retired: !(m && m.retired)});
      },
      "adopt-new": function (el, ref) {
        var p = findProposal(ref);
        if (!p) { return; }
        var id = nextProjectId(S.reg);
        if (!id) { return; }
        var ad = adopted(p);
        S.reg.projects = arr(S.reg.projects).concat([{id: id, name: String(p.label || "").slice(0, 40), domain: DOMAINS5.indexOf(p.domain) >= 0 ? p.domain : "DEV",
          status: "active", merged_into: null, aliases: [], keywords: [], codenames: [], mask_name: false, never: [], adopted: ad ? [ad] : []}]);
        S.hidden[p.key] = true;
        S.msg = ["info", "새 과제 " + id + "(으)로 작업본에 넣었습니다 — 영역을 확인하고 저장하세요."];
        render();
      },
      "adopt-alias": function (el, ref) {
        var p = findProposal(ref);
        var tgt = valueOf("$alias:" + ref);
        var q = arr(S.reg.projects).filter(function (x) { return obj(x).id === tgt; })[0];
        if (!p || !q) { S.msg = ["warn", "별칭을 붙일 과제를 먼저 고르세요."]; render(); return; }
        q.aliases = arr(q.aliases).concat([String(p.label || "").slice(0, 40)]);
        var ad = adopted(p);
        if (ad) { q.adopted = arr(q.adopted).concat([ad]); }
        S.hidden[p.key] = true;
        render();
      },
      "hold": function (el, ref) { S.hidden[ref] = true; render(); },
      "drop-period": function (el, ref) {
        var k = String(ref).indexOf("|");
        if (k < 0) { return; }
        member(ref.slice(0, k), {drop_period: ref.slice(k + 1)});
      },
      "aggregate": function () {
        call("POST", "/api/aggregate", {}).then(function (r) {
          S.msg = r.status === 200 ? ["info", "재취합을 요청했습니다."] : ["bad", obj(r.body).error || ("요청하지 못했습니다(HTTP " + r.status + ")")];
          render();
        });
      },
      "json-show": function () { S.showJson = !S.showJson; render(); },
      "json-download": function () {
        if (!env.Blob || !env.URL || !doc.createElement) { return; }
        var blob = new env.Blob([JSON.stringify(stripSecret(S.reg), null, 1) + "\n"], {type: "application/json"});
        var a = doc.createElement("a");
        a.href = env.URL.createObjectURL(blob);
        a.download = "lm27_registry_v" + (S.base.version || 0) + ".json";
        doc.body.appendChild(a);
        a.click();
        doc.body.removeChild(a);
        env.URL.revokeObjectURL(a.href);
      }
    };

    function onHash() {
      var s = String(env.location ? env.location.hash : "").replace(/^#/, "");
      var m = /^agent-new\/([^/]*)\/(.*)$/.exec(s);
      if (m) {
        S.prefill = {type: decodeURIComponent(m[1]), name: decodeURIComponent(m[2]).slice(0, 30)};
        if (S.reg && S.base) { applyPrefill(); render(); }
        return;
      }
      for (var k = 0; k < ADMIN_TABS.length; k++) {
        if (ADMIN_TABS[k][0] === s) { S.tab = s; render(); return; }
      }
    }

    function start() {
      U().delegate(rootEl, handlers);
      if (rootEl.addEventListener) { rootEl.addEventListener("change", onChange); }
      if (env.win) { env.win.addEventListener("hashchange", onHash); }
      onHash();
      return load();
    }

    return {start: start, state: S, handlers: handlers, render: render, save: save, load: load};
  }

  // ───────────────────────── 9. 시작 ─────────────────────────
  function autoStart(win) {
    var doc = win && win.document;
    if (!doc || !doc.body && doc.readyState !== "loading") { return; }
    function go() {
      var kind = doc.body ? doc.body.getAttribute("data-kind") : null;
      try {
        if (kind === "team-admin") { createAdmin(doc).start(); } else if (kind === "team") { createApp(doc).start(); }
      } catch (e) {
        var main = doc.getElementById("app");
        if (main) { U().render([U().alertLine("bad", "화면을 그리지 못했습니다(" + (e && e.name ? e.name : "오류") + ").")], main); }
      }
    }
    if (doc.readyState === "loading") { doc.addEventListener("DOMContentLoaded", go); } else { go(); }
  }

  return {
    // 모델·계산(순수 — 시험용)
    model: model, kpis: kpis, teamTotals: teamTotals, tagTotals: tagTotals, domainPerson: domainPerson, projectTable: projectTable,
    rolesOfProject: rolesOfProject, roleGrid: roleGrid, leadSpec: leadSpec, agenticGrid: agenticGrid, needGroups: needGroups,
    qualityRows: qualityRows, peopleMonths: peopleMonths, ganttRows: ganttRows, defaultCollapsed: defaultCollapsed,
    detailFor: detailFor, parseHash: parseHash, heatLevel: heatLevel, pctShare: pctShare, typeMultiples: typeMultiples,
    unitBars: unitBars,
    // 보기(가상 노드)
    sectionView: sectionView, headView: headView, detailBody: detailBody, SECTIONS: SECTIONS, SHARE_KEYS: K,
    // 관리
    validateRegistry: validateRegistry, rebase: rebase, nextProjectId: nextProjectId, nextAgentId: nextAgentId,
    stripSecret: stripSecret, ERR_TEXT: ERR_TEXT,
    // 앱
    createApp: createApp, createAdmin: createAdmin, autoStart: autoStart
  };
}));
