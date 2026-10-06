/*
 * LM27 로컬 앱 화면 — 껍데기(머리·pill 메뉴·머리 띠·알림)·해시 라우터·작업(job) 진행·화면 6개(홈·수집·분석·개인 보고서·팀·설정).
 * 근거: REPORTS §5(전부) · §2.3.3(토큰)·§2.3.5(작업)·§2.3.6(API 목록) · §5.7 · §5.8 · §8.2 · §8.5 · §11 · 계약 §9.5 · D-12.
 * 개인 보고서 절은 web\app\report.js 가 그린다(자기완결 HTML 과 같은 파일 — 이 파일은 API 에서 모델을 읽어 넘길 뿐).
 * 원칙: ① DOM 은 lm27ui.js 마운트로만(문자열을 HTML 로 해석하는 API 0 — G-R4) ② 숫자 글자는 lm27ui 표시 함수만(G-R11)
 *       ③ 버튼을 누르는 순간 서버가 파일을 다시 읽는다 — 화면 메모리의 옛 판단으로 말하지 않는다(§5.0.1)
 *       ④ 카드마다 따로 읽고 따로 실패한다(R §11 — 한 카드 오류가 다른 카드를 막지 않음)
 *       ⑤ 쓰기 요청은 JSON + 헤더 X-LM27-UI-Token(§2.3.3) ⑥ 사유 코드 문구는 서버가 준 것만(단일원 lm27\report\vocab.py)
 *       ⑦ 사람에게 시키는 일은 로그인·붙여넣기·응답·버튼 누르기뿐(§5.0.4 — 다른 사람에게 수동 조작을 요구하지 않는다).
 * 고전 스크립트(import·export 문 없음 — L-27). 브라우저 = 전역 LM27App(자동 부트), node = module.exports(시험 전용).
 */
(function (root, factory) {
  "use strict";
  var api = factory(root);
  if (typeof module === "object" && module && module.exports) {
    module.exports = api;
  } else {
    root.LM27App = api;
    api.autoBoot(root);
  }
}(typeof self !== "undefined" ? self : this, function (root) {
  "use strict";

  // ───────────────────────── 0. 의존 ─────────────────────────
  var DEPS = null;

  function deps() {
    if (DEPS) { return DEPS; }
    var u;
    var c;
    var r;
    if (typeof module === "object" && module && module.exports && typeof require === "function") {
      u = require("../common/lm27ui.js");
      c = require("../common/lm27charts.js");
      r = require("./report.js");
    } else {
      u = root.LM27UI;
      c = root.LM27Charts;
      r = root.LM27Report;
    }
    if (!u || !c || !r) { throw new Error("lm27ui.js · lm27charts.js · report.js 를 먼저 불러야 합니다"); }
    DEPS = {U: u, C: c, R: r, K: r.kit};
    return DEPS;
  }

  function U() { return deps().U; }
  function K() { return deps().K; }
  function h(t, a, c) { return deps().U.h(t, a, c); }
  function arr(x) { return Array.isArray(x) ? x : []; }
  function obj(x) { return x && typeof x === "object" && !Array.isArray(x) ? x : {}; }
  function isNum(x) { return typeof x === "number" && isFinite(x); }
  function num(x) { return isNum(x) ? x : 0; }
  function str(x) { return x === null || x === undefined ? "" : String(x); }

  // ───────────────────────── 1. 상수(화면 문구 — R §5) ─────────────────────────
  var SCREENS = [["home", "홈"], ["collect", "수집"], ["analysis", "분석"], ["report", "개인 보고서"], ["team", "팀"], ["settings", "설정"]];
  var JOB_NAME = {collect: "수집", move_prepare: "이동 준비", bundle_merge: "번들 합치기", analyze: "분석", report_build: "보고서 만들기",
    report_export: "보고서 내보내기", quick_reanalyze: "빠른 재분석", team_build: "팀 묶음 만들기", team_send: "팀 묶음 보내기",
    registry_fetch: "레지스트리 받기", team_server: "팀 서버", agent_repair: "에이전트 복구"};
  var JOB_STATE = {queued: ["run", "대기"], running: ["run", "진행 중"], done: ["good", "완료"], partial: ["warn", "일부"],
    failed: ["bad", "실패"], cancelled: ["unknown", "중지됨"]};
  var FINISHED = {done: true, partial: true, failed: true, cancelled: true};
  var LEVEL_ORDER = {block: 0, risk: 1, improve: 2, info: 3};
  var LEVEL_UI = {block: ["bad", "막힘"], risk: ["serious", "위험"], improve: ["info", "향상"], info: ["info", "정보"]};
  var PC_KIND = {desktop: "데스크톱", laptop: "노트북", vdi: "VDI", cloud: "클라우드PC"};
  var AXES = [["mail_in", "메일 받음"], ["mail_out", "메일 보냄"], ["cal", "일정"], ["teams", "팀즈"], ["pc", "PC"]];
  var ROLE_NAME = {pc_usage: "PC 사용 기록", mail_local: "메일(이 PC)", teams_window: "팀즈 창", account_backfill: "계정 백필",
    copilot: "Copilot"};
  var WORK_KINDS = [["work", "업무"], ["offsite", "외근·출장·현장"], ["instr", "오프라인 지시 받음"], ["report", "오프라인 보고함"],
    ["absence", "부재"], ["exclude", "업무 아님"]];
  var OUTBOX_STATE = {pending: "승인 대기", sending: "보내는 중", retry_wait: "다시 시도 대기", sent: "보냄", failed: "실패",
    auth_needed: "인증 필요", wrong_server: "다른 서버", exported: "내보냄", delivered: "전달 확인", dropped: "대체됨"};
  var COLLECT_RC = {
    0: ["good", "수집을 마쳤습니다", "새 기록 {n}건. 남은 할 일 {k}건은 해당 PC 에서 [수집]하면 이어 받습니다"],
    2: ["warn", "일부를 수집했습니다", "끝내지 못한 단계: {stages}. 다음 [수집]이 이어 읽습니다(커서 보존)"],
    1: ["bad", "수집을 끝내지 못했습니다", "{why}. 이미 받은 기록은 저장했습니다. 다시 [수집]을 누르면 남은 것부터 합니다"],
    3: ["bad", "수집을 끝내지 못했습니다", "{why}. 이미 받은 기록은 저장했습니다. 다시 [수집]을 누르면 남은 것부터 합니다"],
    4: ["good", "수집을 마쳤습니다", "새로 받을 기록이 없었습니다"]
  };
  var SET_GROUPS = [["work", "근무 프로필", ["time.window.", "time.tzOffsetMin"]], ["mm", "MM·초과", ["mm."]],
    ["time_adv", "시간 추론(고급)", ["time.envelope.", "time.attrib.", "time.queue.", "episode."]],
    ["collect", "수집", ["collect.", "probe.", "agent.", "bundle.", "move.", "mail.", "teams.", "ledger.", "pc."]],
    ["privacy", "개인정보", ["privacy."]], ["bridge", "Copilot", ["bridge."]], ["team", "팀", ["team.", "teamServer."]],
    ["report", "보고서", ["report.", "teamReport."]], ["ui", "화면", ["ui."]], ["calib", "보정", []]];
  var TOKEN_RX = /^[0-9A-Za-z_-]{16,256}$/;       // 서버가 채운 값(token_hex) — 자리표시자 '…'·빈 값이면 거짓

  // ───────────────────────── 2. 작은 도우미 ─────────────────────────
  function pad2(n) { return (n < 10 ? "0" : "") + n; }

  function ymd(d) { return d.getFullYear() + "-" + pad2(d.getMonth() + 1) + "-" + pad2(d.getDate()); }

  function addMonths(y, m, k) {                   // (y, m 1~12) + k 달 → [y, m]
    var t = y * 12 + (m - 1) + k;
    return [Math.floor(t / 12), (t % 12 + 12) % 12 + 1];
  }

  function monthFirst(ym) { return ym[0] + "-" + pad2(ym[1]) + "-01"; }

  function monthLast(ym) {
    var n = addMonths(ym[0], ym[1], 1);
    var d = new Date(n[0], n[1] - 1, 1);
    d.setDate(0);
    return ymd(d);
  }

  function daysBetween(a, b) {                    // 'YYYY-MM-DD' 두 날의 일수 차(b − a)
    var C = deps().C;
    return C.dayNum(b) - C.dayNum(a);
  }

  function md(s) { return K().mdhm(s); }

  function parseApi(s) {                          // 'POST /api/…' → {method, path} — /api/ 밖은 받지 않는다
    var m = /^(GET|POST|PUT)\s+(\/api\/[\w\-/.%?=&]*)$/.exec(str(s).trim());
    return m ? {method: m[1], path: m[2]} : null;
  }

  function listOf(d, key) {
    if (Array.isArray(d)) { return d; }
    return arr(obj(d)[key]);
  }

  // ───────────────────────── 3. API 의뢰자(§2.3.3 — 쓰기는 JSON + 토큰) ─────────────────────────
  var HTTP_TEXT = {403: "화면 보안 확인값이 맞지 않습니다 — 화면을 새로 고치면 이어서 합니다",
    404: "찾는 자료가 없습니다", 409: "다른 작업이 진행 중입니다 — 끝나면 다시 눌러 주세요", 413: "보낼 내용이 너무 큽니다",
    415: "요청 형식이 맞지 않습니다", 421: "이 주소로는 화면을 열 수 없습니다 — 127.0.0.1 주소로 여세요"};

  function makeApi(fetchFn, getToken) {
    function call(method, path, body) {
      var init = {method: method, headers: {"Accept": "application/json"}, cache: "no-store", credentials: "same-origin"};
      if (method !== "GET") {
        init.headers["Content-Type"] = "application/json";
        init.headers["X-LM27-UI-Token"] = getToken();
        init.body = JSON.stringify(body === undefined ? {} : body);
      }
      var p;
      try {
        p = fetchFn(path, init);
      } catch (e) {
        p = Promise.reject(e);
      }
      return Promise.resolve(p).then(function (r) {
        return Promise.resolve(r.text()).then(function (t) {
          var data = null;
          if (t) {
            try {
              data = JSON.parse(t);
            } catch (e) {
              data = null;
            }
          }
          if (r.ok) { return {ok: true, status: r.status, data: data}; }
          var d = obj(data);
          return {ok: false, status: r.status, code: d.code || "http_" + r.status, data: d, detail: arr(d.detail),
            error: d.error || HTTP_TEXT[r.status] || (r.status >= 500 ? "화면 서버가 이 요청을 처리하지 못했습니다 — 다시 누르면 이어서 합니다" : "요청을 처리하지 못했습니다")};
        });
      }, function () {
        return {ok: false, status: 0, code: "network", data: {},
          error: "화면 서버에 닿지 못했습니다 — LoadMonitor27-UI 를 다시 누르면 이어서 합니다"};
      });
    }
    return {
      get: function (p) { return call("GET", p); },
      post: function (p, b) { return call("POST", p, b); },
      put: function (p, b) { return call("PUT", p, b); }
    };
  }

  function readToken(doc) {
    var el = null;
    if (doc.querySelector) {
      try {
        el = doc.querySelector("meta[name=\"lm27-ui-token\"]");
      } catch (e) {
        el = null;
      }
    }
    if (!el) {
      K().walk(doc.documentElement || doc.body || doc, function (n) {
        if (!el && (n.tagName || "").toLowerCase() === "meta" && n.getAttribute("name") === "lm27-ui-token") { el = n; }
      });
    }
    return el ? str(el.getAttribute("content")) : "";
  }

  // ───────────────────────── 4. 앱(boot) ─────────────────────────
  // opts: {doc, win, fetch, storage, timer:{set(fn, ms), clear(id)}, now: () => Date}
  function boot(opts) {
    opts = opts || {};
    var doc = opts.doc;
    var win = opts.win || doc.defaultView || root;
    var fetchFn = opts.fetch || (win.fetch ? win.fetch.bind(win) : null);
    var timer = opts.timer || {set: function (fn, ms) { return win.setTimeout(fn, ms); }, clear: function (id) { win.clearTimeout(id); }};
    var now = opts.now || function () { return new Date(); };
    var storage = opts.storage;
    if (storage === undefined) {
      try {
        storage = win.localStorage;
      } catch (e) {
        storage = null;
      }
    }
    var U0 = U();
    var Kt = K();
    var R = deps().R;
    var token = readToken(doc);
    var api = makeApi(fetchFn, function () { return token; });
    var el = {nav: doc.getElementById("lm27-nav"), band: doc.getElementById("lm27-band"), alerts: doc.getElementById("lm27-alerts"),
      main: doc.getElementById("app"), pc: doc.getElementById("lm27-pc"), jobs: doc.getElementById("lm27-jobs"),
      head: doc.getElementById("lm27-head")};
    var S = {hello: null, runs: null, current: null, next: [], jobs: {}, jobOrder: [], notices: [], noticeSeq: 0, pollMs: 1000,
      pollTimer: null, scr: null, report: null, defaults: {}, rebuildAsked: {}, tokenOk: TOKEN_RX.test(token)};

    // ── 4.1 머리·메뉴·띠·알림 ──
    function renderNav() {
      if (!el.nav) { return; }
      var cur = S.scr ? S.scr.name : "home";
      var counts = {};
      var total = 0;
      S.next.forEach(function (a) {
        if (a.level !== "block" && a.level !== "risk") { return; }
        total++;
        var g = str(obj(a.action).goto).replace(/^#/, "").split("/")[0];
        if (g) { counts[g] = num(counts[g]) + 1; }
      });
      counts.home = total;
      var act = doc.activeElement;
      var keepHref = act && el.nav.contains && el.nav.contains(act) && act.getAttribute ? act.getAttribute("href") : null;
      U0.render(U0.pills(SCREENS.map(function (s) {
        return {href: "#" + s[0], label: s[1], current: s[0] === cur, badge: counts[s[0]] || null,
          badgeLabel: counts[s[0]] ? "막힘·위험 할 일 " + counts[s[0]] + "건" : null};
      }), {label: "주 메뉴"}), el.nav);
      if (keepHref) {                                 // 배경 갱신이 메뉴의 키보드 초점을 빼앗지 않게
        Kt.walk(el.nav, function (n) { if (n.getAttribute("href") === keepHref && n.focus) { n.focus(); } });
      }
    }

    function renderBand() {
      if (!el.band) { return; }
      var c = S.current;
      if (!c) { U0.clear(el.band); el.band.setAttribute("hidden", ""); return; }
      el.band.removeAttribute("hidden");
      U0.render(R.bandView({from: c.from, to: c.to, as_of: c.as_of, built_at: c.built_at || c.ended, chosen: c.chosen,
        period_source: c.period_source, period_months: c.period_months, label_sources: c.label_sources || c.labels}), el.band);
    }

    function renderAlerts() {
      if (!el.alerts) { return; }
      var list = [];
      if (!S.tokenOk) {
        list.push(U0.alertLine("warn", "이 화면의 보안 확인값이 비어 있어 저장·실행 버튼이 거절될 수 있습니다 — 화면 서버가 연 주소(127.0.0.1)에서 새로 고치면 맞춰집니다"));
      }
      arr(obj(S.current).warnings).forEach(function (w) { list.push(U0.alertLine("warn", obj(w).text_ko || str(w))); });
      S.notices.forEach(function (n) {
        list.push(h("div", {"class": "alert alert-" + n.kind, role: n.kind === "bad" ? "alert" : "status"}, [U0.icon(n.kind === "bad" ? "bad" : (n.kind === "warn" ? "warn" : "info")),
          h("span", {}, [n.text]), Kt.btn("닫기", "a-dismiss", n.id, {kind: "ghost"})]));
      });
      U0.render(h("div", {}, list), el.alerts);
    }

    function notice(kind, text) {
      S.noticeSeq++;
      S.notices.push({id: "n" + S.noticeSeq, kind: kind, text: text});
      if (S.notices.length > 6) { S.notices.shift(); }
      renderAlerts();
    }

    function renderHead() {
      var hp = obj(obj(S.hello).pc);
      if (el.pc) {
        var t = hp.label_user || hp.label_auto || hp.label;
        U0.render(t ? ["[" + t + (PC_KIND[hp.kind] ? " · " + PC_KIND[hp.kind] : "") + "]"] : [], el.pc);
      }
      updateJobsButton();
    }

    function runningJobs() {
      return S.jobOrder.filter(function (id) { return !FINISHED[S.jobs[id].state]; });
    }

    function updateJobsButton() {
      if (!el.jobs) { return; }
      var n = runningJobs().length;
      if (!n && !S.jobOrder.length) { el.jobs.setAttribute("hidden", ""); return; }
      el.jobs.removeAttribute("hidden");
      U0.render(n ? ["작업 " + n + " ", U0.icon("run")] : ["최근 작업"], el.jobs);
      el.jobs.setAttribute("aria-label", n ? "진행 중인 작업 " + n + "건 — 누르면 목록" : "최근 작업 목록");
    }

    // ── 4.2 작업(job) — §2.3.5 ──
    function jobLabel(j) { return JOB_NAME[j.kind] || j.name_ko || "작업"; }

    function lastText(j) {
      for (var i = j.events.length - 1; i >= 0; i--) { if (j.events[i].text_ko) { return j.events[i].text_ko; } }
      return "";
    }

    function lastProgress(j) {
      for (var i = j.events.length - 1; i >= 0; i--) {
        var e = j.events[i];
        if (isNum(e.done) && isNum(e.total) && e.total > 0) { return e; }
      }
      return null;
    }

    function track(id, kind, ctx) {
      if (!id) { return; }
      if (!S.jobs[id]) {
        S.jobs[id] = {job_id: id, kind: kind || "", state: "queued", events: [], seq: 0, ctx: ctx || {}};
        S.jobOrder.push(id);
      } else if (ctx) {
        S.jobs[id].ctx = ctx;
      }
      updateJobsButton();
      schedulePoll(true);
    }

    function trackFrom(res, kind, ctx) {
      var d = obj(res && res.data);
      if (res && res.ok) {
        if (d.job_id) { track(d.job_id, kind, ctx); }
        if (d.reanalyze_job) { track(d.reanalyze_job, "quick_reanalyze", ctx); }
      }
      return res;
    }

    function schedulePoll(soon) {
      if (S.pollTimer !== null) { return; }
      S.pollTimer = timer.set(pollOnce, soon ? 50 : S.pollMs);
    }

    function applyJob(id, res) {
      var j = S.jobs[id];
      if (!j) { return; }
      if (!res.ok) {
        if (res.status === 404) { j.state = "failed"; j.lost = true; }
        return;
      }
      var d = obj(res.data);
      ["state", "kind", "lane", "rc", "started", "ended", "name_ko"].forEach(function (k) { if (d[k] !== undefined && d[k] !== null) { j[k] = d[k]; } });
      if (d.result !== undefined) { j.result = d.result; }
      arr(d.events).forEach(function (ev) {
        if (isNum(ev.seq) && ev.seq <= j.seq) { return; }
        if (isNum(ev.seq)) { j.seq = ev.seq; }
        j.events.push(ev);
        if (ev.ev === "result" && j.result === undefined) { j.result = ev; }
      });
      if (j.events.length > 200) { j.events = j.events.slice(-200); }
      if (FINISHED[j.state] && !j.done) {
        j.done = true;
        onJobDone(j);
      }
    }

    function pollOnce() {
      S.pollTimer = null;
      var ids = runningJobs();
      if (!ids.length) { updateJobsButton(); return Promise.resolve(); }
      return Promise.all(ids.map(function (id) {
        return api.get("/api/jobs/" + encodeURIComponent(id) + "?since=" + S.jobs[id].seq).then(function (res) { applyJob(id, res); });
      })).then(function () {
        updateJobsButton();
        if (S.scr && S.scr.onJobs) { S.scr.onJobs(); }
        if (runningJobs().length) { schedulePoll(false); }
      });
    }

    var RELOAD = {collect: ["home", "collect"], bundle_merge: ["collect"], move_prepare: ["collect"], analyze: ["analysis", "home", "report"],
      report_build: ["report", "analysis"], quick_reanalyze: ["report", "analysis", "home"], team_build: ["team"], team_send: ["team", "home"],
      registry_fetch: ["team", "home"], agent_repair: ["collect", "home"], report_export: []};

    function onJobDone(j) {
      var name = jobLabel(j);
      var st = j.state;
      var text = st === "done" ? "'" + name + "' 작업을 마쳤습니다." : (st === "partial" ? "'" + name + "' 작업을 일부 마쳤습니다 — 다음에 남은 것부터 이어 합니다." :
        (st === "cancelled" ? "'" + name + "' 작업을 중지했습니다 — 다시 누르면 남은 것부터 이어 합니다." :
          "'" + name + "' 작업을 끝내지 못했습니다" + (lastText(j) ? " — " + lastText(j) : "") + "."));
      if (j.kind === "move_prepare" && st === "done") { text = "이동 시험 창을 열었습니다. 창에 '[완료]'가 나오면 폴더를 옮기세요."; }
      notice(st === "done" ? "info" : (st === "partial" || st === "cancelled" ? "warn" : "bad"), text);
      refreshGlobal();
      var scr = S.scr;
      if (scr && arr(RELOAD[j.kind]).indexOf(scr.name) >= 0) {
        if (scr.name === "report") { openScreen("report", scr.arg, true); } else { reloadAll(scr); }
      }
      if (j.kind === "team_build" && (st === "done" || st === "partial")) {
        var item = obj(j.result).item || obj(obj(j.result).data).item;
        if (item) { openPreview(item); }
      }
      if (j.kind === "report_export" && st !== "failed" && st !== "cancelled") { showExportResult(j); }
    }

    function jobsDrawer() {
      var rows = S.jobOrder.slice().reverse().map(function (id) {
        var j = S.jobs[id];
        var s = JOB_STATE[j.state] || ["unknown", str(j.state)];
        var pg = lastProgress(j);
        return h("li", {}, [h("strong", {}, [jobLabel(j)]), " ", U0.statusText(s[0], s[1]),
          pg ? U0.progressBar(pg.done, pg.total, jobLabel(j) + " 진행") : null,
          lastText(j) ? h("p", {"class": "muted small"}, [lastText(j)]) : null,
          !FINISHED[j.state] ? Kt.btn("중지", "a-job-cancel", id, {kind: "danger", icon: "stop"}) : null]);
      });
      U0.openDrawer(rows.length ? h("ul", {}, rows) : Kt.emptyP("진행 중이거나 최근에 끝난 작업이 없습니다."), {doc: doc, title: "작업",
        handlers: {"a-job-cancel": function (n, id) {
          api.post("/api/jobs/" + encodeURIComponent(id) + "/cancel", {}).then(function (res) {
            notice(res.ok ? "info" : "bad", res.ok ? "중지를 요청했습니다 — 5초 안에 멈춥니다. 다음에 다시 누르면 남은 것부터 합니다." : res.error);
            schedulePoll(true);
          });
          U0.closeDrawer();
        }}});
    }

    // ── 4.3 전역 자료(다음 할 일·분석 이력·작업 목록) ──
    function refreshGlobal() {
      return Promise.all([
        api.get("/api/next-actions").then(function (res) {
          if (res.ok) {
            S.next = listOf(res.data, "items").slice().sort(function (a, b) {
              return (num(LEVEL_ORDER[a.level]) - num(LEVEL_ORDER[b.level])) || (str(a.code) < str(b.code) ? -1 : (str(a.code) > str(b.code) ? 1 : 0)) ||
                (str(a.target) < str(b.target) ? -1 : (str(a.target) > str(b.target) ? 1 : 0));
            });
          }
        }),
        api.get("/api/analysis/runs").then(function (res) {
          if (!res.ok) { return; }
          S.runs = listOf(res.data, "runs");
          var d = obj(res.data);
          S.defaults = obj(d.defaults);
          S.current = d.current && typeof d.current === "object" ? d.current : (S.runs.filter(function (r) { return r.current; })[0] || null);
        })
      ]).then(function () {
        renderNav();
        renderBand();
        renderAlerts();
        if (S.scr && S.scr.onGlobal) { S.scr.onGlobal(); }
      });
    }

    // ── 4.4 화면 틀: 자료원·카드(카드마다 따로 읽고 따로 실패 — R §11) ──
    function source(scr, key, force) {
      var s = scr.src[key];
      if (s && s.p && !force) { return s.p; }
      var fn = scr.def.sources[key];
      s = scr.src[key] = s || {state: "idle", data: null, err: null};
      s.state = "loading";
      renderUsing(scr, key);
      s.p = Promise.resolve(fn(scr)).then(function (res) {
        if (!scr.alive) { return res; }
        if (res && res.ok) { s.state = "ok"; s.data = res.data; s.err = null; } else { s.state = "err"; s.err = res || {error: "읽지 못했습니다"}; }
        renderUsing(scr, key);
        return res;
      });
      return s.p;
    }

    function renderUsing(scr, key) {
      scr.cards.forEach(function (c) { if (arr(c.def.uses).indexOf(key) >= 0) { renderCard(scr, c); } });
    }

    function renderCard(scr, c) {
      if (!scr.alive) { return; }
      var d = c.def;
      if (d.when && !d.when(scr)) { U0.clear(c.el); return; }
      var data = {};
      var body = null;
      var waiting = false;
      var failed = null;
      arr(d.uses).forEach(function (k) {
        var s = scr.src[k];
        if (!s || s.state === "idle" || (s.state === "loading" && s.data === null)) { waiting = true; } else if (s.state === "err" && s.data === null) {
          failed = s.err;
        } else { data[k] = s.data; }
      });
      var tools = null;
      if (failed) {
        body = h("div", {}, [U0.alertLine("bad", "이 카드를 읽지 못했습니다 — " + (failed.error || "다시 읽으면 이어서 보입니다")),
          Kt.btn("다시 읽기", "a-reload", d.id, {kind: "ghost"})]);
      } else if (waiting) {
        body = Kt.para("불러오는 중입니다…", "muted");
      } else {
        try {                                         // 자료 형이 예상과 달라도 이 카드만 멈춘다(R §11)
          body = d.view(scr, data, c);
          tools = d.tools ? d.tools(scr, data, c) : null;
        } catch (e) {
          body = h("div", {}, [U0.alertLine("bad", "이 카드를 그리지 못했습니다(받은 자료의 형식이 예상과 다릅니다) — 다시 읽으면 이어서 보입니다"),
            Kt.btn("다시 읽기", "a-reload", d.id, {kind: "ghost"})]);
        }
      }
      var title = typeof d.title === "function" ? d.title(scr, data) : d.title;
      var vals = Kt.collectValues(c.el);
      var fk = Kt.focusKeyOf(doc.activeElement, c.el);
      U0.render(Kt.card(title, h("div", {}, [c.msg ? U0.alertLine(c.msg.kind, c.msg.text) : null, body]),
        {id: "card-" + d.id, tools: tools || null, state: d.state ? d.state(scr, data) : null}), c.el);
      if (!c.reset) { Kt.restoreValues(c.el, vals); }
      c.reset = false;
      Kt.restoreFocus(c.el, fk);
    }

    function cardOf(scr, id) { return scr.cards.filter(function (c) { return c.def.id === id; })[0] || null; }

    function rerender(scr, id) {
      scr.cards.forEach(function (c) { if (!id || c.def.id === id) { renderCard(scr, c); } });
    }

    function reloadAll(scr) {
      Object.keys(scr.src).forEach(function (k) { source(scr, k, true); });
      rerender(scr);
    }

    // 쓰기 요청 → 카드 알림 줄. o: {ok: 글자|함수, job: kind, after(res), reload: [자료원], reset: true(입력 비우기)}
    function send(scr, cardId, method, path, body, o) {
      o = o || {};
      var c = cardOf(scr, cardId);
      return api[method](path, body).then(function (res) {
        trackFrom(res, o.job, o.ctx);
        if (c) {
          if (res.ok) {
            var t = typeof o.ok === "function" ? o.ok(res.data) : o.ok;
            c.msg = t ? {kind: "info", text: t} : null;
            if (o.reset) { c.reset = true; }
          } else {
            c.msg = {kind: res.status === 409 ? "warn" : "bad", text: res.error};
            if (res.status === 403) { S.tokenOk = false; renderAlerts(); }
          }
        }
        if (res.ok && o.after) { o.after(res.data, res); }
        if (res.ok) { arr(o.reload).forEach(function (k) { source(scr, k, true); }); }
        if (c) { renderCard(scr, c); }
        return res;
      });
    }

    function val(id) { var n = doc.getElementById(id); return n ? n.value : ""; }
    function checked(id) { var n = doc.getElementById(id); return !!(n && n.checked); }

    function closeScreen() {
      var scr = S.scr;
      if (!scr) { return; }
      scr.alive = false;
      if (scr.off) { scr.off(); }
      if (S.report) { S.report.destroy(); S.report = null; }
      if (scr.el && scr.el.parentNode) { scr.el.parentNode.removeChild(scr.el); }
      S.scr = null;
    }

    function openScreen(name, arg, force) {
      var def = SCREEN_DEF[name] || SCREEN_DEF.home;
      if (!force && S.scr && S.scr.name === name) {
        S.scr.arg = arg;
        if (S.scr.onArg) { S.scr.onArg(arg); }
        return;
      }
      closeScreen();
      var host = U0.mount(h("div", {id: "screen-" + name}), el.main);
      var scr = {name: name, arg: arg, el: host, def: def, src: {}, cards: [], st: {}, alive: true, off: null};
      S.scr = scr;
      renderNav();
      if (def.custom) { def.custom(scr); return; }
      var hd = {};
      Object.keys(COMMON).forEach(function (k) { hd[k] = COMMON[k].bind(null, scr); });
      Object.keys(obj(def.handlers)).forEach(function (k) { hd[k] = def.handlers[k].bind(null, scr); });
      scr.off = U0.delegate(host, hd);
      if (def.init) { def.init(scr); }
      def.cards.forEach(function (cd) {
        var slot = U0.mount(h("div", {"class": "slot"}), host);
        scr.cards.push({def: cd, el: slot, msg: null, reset: false});
      });
      rerender(scr);
      Object.keys(def.sources || {}).forEach(function (k) { if (!def.lazy || !def.lazy[k]) { source(scr, k); } });
    }

    var COMMON = {
      "a-reload": function (scr, n, id) {
        var c = cardOf(scr, id);
        if (c) { arr(c.def.uses).forEach(function (k) { source(scr, k, true); }); }
      },
      "chart-table": function (scr, n, id) { scr.st["tbl:" + id] = !scr.st["tbl:" + id]; rerender(scr); },
      "table-sort": function (scr, n, ref) {
        var f = Kt.closestAttr(n, "data-chart", scr.el);
        if (!f) { return; }
        var id = f.getAttribute("data-chart");
        var prev = scr.st["sort:" + id];
        scr.st["sort:" + id] = {col: +ref, desc: prev && prev.col === +ref ? !prev.desc : false};
        rerender(scr);
      },
      "table-unsort": function (scr, n) {
        var f = Kt.closestAttr(n, "data-chart", scr.el);
        if (f) { delete scr.st["sort:" + f.getAttribute("data-chart")]; rerender(scr); }
      },
      "table-more": function (scr, n) {
        var f = Kt.closestAttr(n, "data-chart", scr.el);
        if (f) { var k = "lim:" + f.getAttribute("data-chart"); scr.st[k] = (scr.st[k] || 500) + 500; rerender(scr); }
      },
      "a-open": function (scr, n, ref) { scr.st["open:" + ref] = !scr.st["open:" + ref]; rerender(scr); },
      "a-next": function (scr, n, ref) { runNextAction(scr, +ref); },
      "cov-day": function (scr, n, ref) {
        var d = str(ref).split("|")[0];
        if (scr.name === "collect") { scr.st.covDay = d; rerender(scr, "coverage"); } else { win.location.hash = "#collect/" + d; }
      }
    };

    function runNextAction(scr, i) {
      var a = S.next[i];
      if (!a) { return; }
      var act = obj(a.action);
      var call = parseApi(act.api);
      if (call && call.method !== "GET") {
        api[call.method.toLowerCase()](call.path, obj(act.body)).then(function (res) {
          trackFrom(res, "", {});
          notice(res.ok ? "info" : (res.status === 409 ? "warn" : "bad"), res.ok ? "'" + str(a.title_ko) + "' — 요청했습니다" : res.error);
          refreshGlobal();
        });
        return;
      }
      if (act.goto && /^#[a-z]/.test(act.goto)) { win.location.hash = act.goto; }
    }

    function nextActionRow(a, i) {
      var lv = LEVEL_UI[a.level] || ["info", "정보"];
      var act = obj(a.action);
      var call = parseApi(act.api);
      var ctl = null;
      if (call && call.method !== "GET") {
        ctl = Kt.btn(str(act.label || "실행").replace(/^\[|\]$/g, ""), "a-next", i, {kind: "ghost"});
      } else if (act.goto && /^#[a-z]/.test(act.goto)) {
        ctl = Kt.link(str(act.label || "열기").replace(/^\[|\]$/g, ""), act.goto);
      }
      return h("li", {}, [lv[0] === "info" ? h("span", {"class": "st st-run"}, [U0.icon("info"), h("span", {"class": "st-text"}, [lv[1]])]) :
        U0.statusText(lv[0], lv[1]), " ", h("strong", {}, [str(a.title_ko)]), a.why_ko ? " — " + a.why_ko : "", " ", ctl]);
    }

    // ── 4.5 홈(§5.1) ──
    function covSpec(cov) {
      var d = obj(cov);
      return {axes: arr(d.axes).length ? d.axes : null, days: arr(d.days), reasonText: obj(d.reasonText || d.reason_text),
        srcNames: obj(d.srcNames || d.src_names), today: ymd(now())};
    }

    function coverageChart(scr, cov, id) {
      var C = deps().C;
      var res = C.coverageHeatmap(covSpec(cov), {id: id});
      var srt = scr.st["sort:" + id];
      return U0.chartView(res, {id: id, table: !!scr.st["tbl:" + id], tableOpt: {sortCol: srt ? srt.col : null, desc: srt ? srt.desc : false,
        limit: scr.st["lim:" + id] || 500, id: "t-" + id}});
    }

    function matrixView(scr, m, rtTop) {
      m = obj(m);
      var cols = arr(m.cols);
      var rows = arr(m.rows);
      var rt = obj(m.reason_text || m.reasonText || rtTop);
      if (!rows.length) { return Kt.emptyP("이 번들에는 아직 PC 기록이 없습니다. [수집]을 누르면 이 PC 부터 기록합니다."); }
      var groups = [];
      cols.forEach(function (c) {
        var g = groups[groups.length - 1];
        if (g && g.name === c.group) { g.n++; } else { groups.push({name: c.group, n: 1}); }
      });
      var narrow = num(obj(scr.st).width) > 0 && scr.st.width < 900;
      var head1 = h("tr", {}, [h("th", {scope: "col", rowspan: "2"}, ["PC"])].concat(groups.map(function (g) {
        return h("th", {scope: "colgroup", colspan: String(g.n)}, [g.name || ""]);
      })));
      var head2 = h("tr", {}, cols.map(function (c) { return h("th", {scope: "col"}, [c.label || c.key]); }));
      var body = [];
      rows.forEach(function (r, ri) {
        var head = h("th", {scope: "row"}, [h("strong", {}, [r.pc || r.label || "PC"]), r.kind ? " · " + (PC_KIND[r.kind] || r.kind) : "",
          r["this"] ? " " : null, r["this"] ? U0.badge("이 PC") : null,
          Kt.chips(arr(r.roles).map(function (x) { return ROLE_NAME[x] || x; }))]);
        var sel = scr.st.cell && scr.st.cell.r === ri ? scr.st.cell.k : null;
        body.push(h("tr", {}, [head].concat(cols.map(function (c) {
          var cell = obj(obj(r.cells)[c.key]);
          var verdict = cell.applies === false ? "해당 없음" : (cell.verdict || "미확인");
          return h("td", {}, [h("button", {type: "button", "class": "exp", "aria-expanded": sel === c.key ? "true" : "false",
            "data-act": "a-cell", "data-ref": ri + "|" + c.key, "aria-label": (r.pc || "PC") + " " + (c.label || c.key) + " " + verdict + " — 자세히"},
          [U0.verdictCell(verdict, narrow)])]);
        }))));
        if (sel) {
          var cell = obj(obj(r.cells)[sel]);
          var hist = arr(cell.hist).slice(-10);
          var col = cols.filter(function (c) { return c.key === sel; })[0] || {};
          body.push(h("tr", {"class": "detail"}, [h("td", {colspan: String(cols.length + 1)}, [
            h("strong", {}, [(r.pc || "PC") + " · " + (col.label || sel)]),
            arr(cell.reasons).length ? h("ul", {}, arr(cell.reasons).map(function (code) {
              return h("li", {}, [(rt[code] || "다음 수집에서 다시 확인합니다") + " (" + code + ")"]);
            })) : null,
            cell.summary ? Kt.para("측정값: " + cell.summary) : null,
            hist.length ? h("p", {}, ["최근 " + hist.length + "회: ", h("svg", {viewBox: "0 0 " + (hist.length * 14) + " 12", width: hist.length * 14, height: 12,
              role: "img", "aria-label": hist.join(", ")}, hist.map(function (s, i) {
              var cls = s === "ok" ? "f-st-good" : (s === "fail" ? "f-st-bad" : (s === "transport_fail" ? "f-st-warn" : "f-surface-2"));
              return h("rect", {x: i * 14, y: 0, width: 12, height: 12, rx: 2, "class": cls}, [h("title", {}, [s])]);
            }))]) : null,
            cell.last ? Kt.muted("마지막 측정 " + cell.last) : null])]));
        }
      });
      var acc = arr(m.account).map(function (a) {
        var ax = AXES.filter(function (x) { return x[0] === a.axis; })[0];
        return h("li", {}, [(ax ? ax[1] : a.axis) + " " + U0.shareText(a.ratio30) + (arr(a.best).length ? " — " + arr(a.best).join(" · ") : "")]);
      });
      return h("div", {}, [h("div", {"class": "table-wrap"}, [h("table", {"class": "tbl", "aria-label": "PC × 출처 능력 표"},
        [h("thead", {}, [head1, head2]), h("tbody", {}, body)])]),
      acc.length ? h("div", {}, [h("h3", {}, ["계정 합성(최근 30근무일)"]), h("ul", {}, acc)]) : null,
      arr(m.explain).length ? h("ul", {}, arr(m.explain).map(function (t) { return h("li", {}, [t]); })) : null]);
    }

    function collectLine(home) {
      var c = obj(home.collect);
      var last = obj(c.last);
      var pcs = obj(c.pcs);
      var cov = obj(home.coverage);
      var r30 = obj(cov.ratio30);
      var parts = [];
      if (last.at) { parts.push("마지막 수집 " + md(last.at) + (last.pc ? "(" + last.pc + ")" : "")); }
      if (isNum(pcs.total)) { parts.push("PC " + pcs.total + "대(정상 " + num(pcs.ok) + " · 기록 끊김 " + num(pcs.stale) + ")"); }
      var rs = AXES.filter(function (a) { return isNum(r30[a[0]]); }).map(function (a) { return a[1] + " " + U0.shareText(r30[a[0]]); });
      if (rs.length) { parts.push("최근 30근무일 커버리지 " + rs.join(" · ")); }
      var gap = obj(cov.last_gap);
      if (gap.d) {
        var ax = AXES.filter(function (a) { return a[0] === gap.axis; })[0];
        var why = arr(gap.reasons).map(function (code) { return obj(cov.reason_text || home.reason_text)[code] || code; }).join(", ");
        parts.push("가장 최근 빈 날 " + str(gap.d).slice(5) + "(" + (ax ? ax[1] : gap.axis) + (why ? " — " + why : "") + ")");
      }
      return parts.join(" · ");
    }

    function axisBars(home) {
      var r30 = obj(obj(home.coverage).ratio30);
      return Kt.table(["축", {label: "최근 30근무일", num: true}, ""], AXES.map(function (a) {
        return [a[1], isNum(r30[a[0]]) ? U0.shareText(r30[a[0]]) : "—", isNum(r30[a[0]]) ? Kt.shareBar(r30[a[0]]) : null];
      }), {label: "축별 근무일 커버리지"});
    }

    var HOME = {
      sources: {
        home: function () { return api.get("/api/home"); },
        cov: function (scr) {
          return source(scr, "home").then(function (res) {
            var cv = obj(obj(res && res.data).coverage);
            var to = cv.to || ymd(now());
            var days = num(obj(obj(res && res.data).ui).home_coverage_days) || 35;
            var from = cv.from && daysBetween(cv.from, to) <= 400 ? cv.from : ymd(new Date(now().getTime() - (days - 1) * 86400000));
            return api.get("/api/collect/coverage?from=" + encodeURIComponent(from) + "&to=" + encodeURIComponent(to));
          });
        }
      },
      cards: [
        {id: "next", title: "다음 할 일", uses: [], view: function (scr) {
          var top = S.next.slice(0, 8);
          if (!top.length) { return Kt.emptyP("지금 할 일이 없습니다. 수집과 분석이 제때 돌고 있습니다."); }
          return h("ul", {}, top.map(function (a) { return nextActionRow(a, S.next.indexOf(a)); }));
        }, tools: function () {
          return S.next.length > 8 ? [Kt.btn("모두 보기", "a-next-all", "", {kind: "ghost"})] : null;
        }},
        {id: "collect", title: "수집 현황", uses: ["home", "cov"], view: function (scr, d) {
          return h("div", {}, [Kt.para(collectLine(d.home) || "수집 기록이 아직 없습니다. [수집]을 누르면 이 PC 부터 기록합니다."),
            coverageChart(scr, d.cov, "ch-h01-home"), axisBars(d.home)]);
        }},
        {id: "matrix", title: "PC × 출처 능력 표", uses: ["home"], view: function (scr, d) { return matrixView(scr, obj(d.home).matrix, obj(d.home).reason_text); }},
        {id: "analysis", title: "최근 분석", uses: ["home"], view: function (scr, d) {
          var a = obj(obj(d.home).analysis);
          var k = obj(a.kpi);
          if (!a.run_id) { return Kt.emptyP("아직 분석 결과가 없습니다. [분석] 화면에서 기간을 정해 실행하세요."); }
          var q = {reliable: ["good", "신뢰"], caution: ["warn", "주의"], unreliable: ["bad", "측정 불충분"]}[k.quality] || ["unknown", "판단 안 함"];
          return h("div", {}, [h("div", {"class": "kpis"}, [
            U0.kpiCard({label: (a.month || "이번 달") + " MM", value: k.mm ? k.mm + " MM" : null}),
            U0.kpiCard({label: "로드율", value: k.load_pct ? k.load_pct + "%" : null}),
            U0.kpiCard({label: "초과 근무", value: k.ot_h ? k.ot_h + "h" : null}),
            U0.kpiCard({label: "미귀속", value: k.unattr_pct ? k.unattr_pct + "%" : null}),
            U0.kpiCard({label: "측정 품질", value: U0.statusText(q[0], q[1])})]),
          Kt.link("개인 보고서 열기", "#report/summary")]);
        }},
        {id: "team", title: "팀", uses: ["home"], view: function (scr, d) {
          var t = obj(obj(d.home).team);
          var reg = obj(t.registry);
          var ob = obj(t.outbox);
          var reach = obj(t.reach);
          return h("div", {}, [
            Kt.para(isNum(reg.version) ? "레지스트리 v" + reg.version + (reg.fetched_at ? "(" + md(reg.fetched_at) + " 받음)" : "") : "팀 레지스트리를 아직 받지 못했습니다."),
            Kt.para("대기열: 승인 대기 " + num(ob.pending) + " · 승인됨 " + num(ob.approved) + " · 실패 " + num(ob.failed) + " · 보냄 " + num(ob.sent)),
            reach.text_ko ? Kt.para("마지막 팀 서버 도달: " + reach.text_ko) : null,
            Kt.link("팀 화면", "#team")]);
        }}],
      handlers: {
        "a-next-all": function () {
          U0.openDrawer(h("ul", {}, S.next.map(nextActionRow)), {doc: doc, title: "다음 할 일 — 모두", handlers: {
            "a-next": function (n, ref) { U0.closeDrawer(); runNextAction(S.scr, +ref); }}});
        },
        "a-cell": function (scr, n, ref) {
          var p = str(ref).split("|");
          var cur = scr.st.cell;
          scr.st.cell = cur && cur.r === +p[0] && cur.k === p[1] ? null : {r: +p[0], k: p[1]};
          rerender(scr, "matrix");
        }
      },
      init: function (scr) {
        scr.st.width = num(el.main.clientWidth);
        scr.onGlobal = function () { rerender(scr, "next"); };
      }
    };

    // ── 4.6 수집(§5.2) ──
    function stageList(j) {
      var by = {};
      var order = [];
      j.events.forEach(function (e) {
        if (!e.stage) { return; }
        if (!by[e.stage]) { by[e.stage] = {stage: e.stage, name: e.name_ko || e.stage, state: "running", n: null, why: ""}; order.push(e.stage); }
        var s = by[e.stage];
        if (e.name_ko) { s.name = e.name_ko; }
        if (e.ev === "stage_end") { s.state = e.state || "done"; }
        if (isNum(e.done)) { s.n = e.done + (isNum(e.total) ? "/" + e.total : ""); }
        if (e.text_ko) { s.why = e.text_ko; }
      });
      return order.map(function (k) { return by[k]; });
    }

    function jobOfKind(kinds) {
      for (var i = S.jobOrder.length - 1; i >= 0; i--) {
        var j = S.jobs[S.jobOrder[i]];
        if (kinds.indexOf(j.kind) >= 0) { return j; }
      }
      return null;
    }

    function stageTable(j) {
      var rows = stageList(j).map(function (s) {
        var stt = JOB_STATE[s.state] || ["unknown", str(s.state)];
        return [s.name, U0.statusText(stt[0], stt[1]), s.n || "—", s.why || ""];
      });
      return rows.length ? Kt.table(["단계", "상태", {label: "처리", num: true}, "알림"], rows, {label: jobLabel(j) + " 단계"}) : null;
    }

    function collectResult(last) {
      last = obj(last);
      if (!isNum(last.rc) && !last.state) { return null; }
      var p = COLLECT_RC[last.rc] || COLLECT_RC[1];
      var newN = 0;
      Object.keys(obj(last["new"])).forEach(function (k) { newN += num(last["new"][k]); });
      var body = p[2].replace("{n}", String(newN)).replace("{k}", String(num(last.todo_left)))
        .replace("{stages}", arr(last.unfinished).map(function (s) { return str(obj(s).name_ko || s) + (obj(s).why ? "(" + s.why + ")" : ""); }).join(", ") || "—")
        .replace("{why}", str(last.why_ko || "다음 [수집]에서 다시 시도합니다"));
      return h("div", {}, [U0.alertLine(p[0] === "good" ? "info" : (p[0] === "warn" ? "warn" : "bad"), p[1] + " — " + body),
        Object.keys(obj(last["new"])).length ? Kt.para("새 레코드: " + Object.keys(last["new"]).sort().map(function (k) { return k + " " + last["new"][k]; }).join(" · ")) : null,
        isNum(last.quarantined) && last.quarantined > 0 ? Kt.para("격리한 세그먼트 " + last.quarantined + "개") : null,
        arr(last.verdict_changes).length ? h("ul", {}, arr(last.verdict_changes).map(function (v) { return h("li", {}, [str(obj(v).text_ko || v)]); })) : null,
        last.outbox_text ? Kt.para(last.outbox_text) : null]);
    }

    function worklogForm(scr, d) {
      var o = obj(obj(d.status).worklog_options);
      var e = obj(scr.st.wlErr);
      var projs = [["", "모름"]].concat(arr(o.projects).map(function (p) { return [p.key, p.label || p.key]; }));
      function vopts(list) { return [["", "고르지 않음"]].concat(arr(list).map(function (v) { return [v.code, v.name || v.code]; })); }
      return h("div", {}, [
        Kt.field("wl-date", "날짜", Kt.input("wl-date", "date", ymd(now()), {required: true, "aria-invalid": e.date ? "true" : null}), {error: e.date}),
        Kt.field("wl-a", "시작(선택)", Kt.input("wl-a", "time", null, {"aria-invalid": e.a ? "true" : null}), {error: e.a}),
        Kt.field("wl-b", "끝(선택)", Kt.input("wl-b", "time", null, {"aria-invalid": e.b ? "true" : null}), {error: e.b,
          help: "둘 다 넣으면 구간입니다(자정을 넘기면 둘로 나눠 넣어 주세요)"}),
        Kt.field("wl-hours", "시간(h)", Kt.input("wl-hours", "number", null, {min: "0.25", max: "16", step: "0.25", "aria-invalid": e.hours ? "true" : null}),
          {error: e.hours, help: "구간이 없을 때 필수 — 0.25~16, 0.25 단위"}),
        Kt.field("wl-kind", "종류", Kt.select("wl-kind", WORK_KINDS, "work")),
        Kt.field("wl-project", "과제", Kt.select("wl-project", projs, "")),
        Kt.field("wl-field", "분야(선택)", Kt.select("wl-field", vopts(o.fields), "")),
        Kt.field("wl-func", "기능(선택)", Kt.select("wl-func", vopts(o.functions), "")),
        Kt.field("wl-ref", "관련 문서·대화(선택)", Kt.select("wl-ref", [["", "고르지 않음"]].concat(arr(o.refs).map(function (r) {
          return [r.ref || r.key, r.label || r.ref || r.key];
        })), "")),
        Kt.field("wl-memo", "메모(200자 이하)", Kt.textarea("wl-memo", "", {maxlength: "200", rows: "2", "aria-invalid": e.memo ? "true" : null}),
          {error: e.memo, help: "저장할 때 개인정보·금액은 자동으로 가려집니다"}),
        h("div", {"class": "table-tools"}, [Kt.btn("기록하기", "a-wl-save", "", {kind: "primary"})])]);
    }

    function readWorklog() {
      var body = {date: val("wl-date"), kind: val("wl-kind") || "work"};
      var errs = {};
      if (!/^\d{4}-\d{2}-\d{2}$/.test(body.date)) { errs.date = "날짜를 넣어 주세요"; }
      var a = val("wl-a");
      var b = val("wl-b");
      var hv = str(val("wl-hours"));
      if (a || b) {
        if (!/^\d{2}:\d{2}$/.test(a)) { errs.a = "시작 시각을 넣어 주세요"; }
        if (!/^\d{2}:\d{2}$/.test(b)) { errs.b = "끝 시각을 넣어 주세요"; } else if (/^\d{2}:\d{2}$/.test(a) && b <= a) {
          errs.b = "끝은 시작보다 늦어야 합니다(자정을 넘기면 둘로 나눠 넣어 주세요)";
        }
        body.a = a;
        body.b = b;
      } else {
        var x = Number(hv);
        if (hv === "" || !(x >= 0.25 && x <= 16) || Math.round(x * 4) !== x * 4) { errs.hours = "구간이 없으면 0.25~16 사이 시간을 0.25 단위로 넣어 주세요"; } else {
          body.hours = x;
        }
      }
      ["project", "field", "func", "ref"].forEach(function (k) { var v = val("wl-" + k); if (v) { body[k] = v; } });
      var memo = str(val("wl-memo"));
      if (Array.from(memo).length > 200) { errs.memo = "메모는 200자 이하로 줄여 주세요"; } else if (memo.trim()) { body.memo = memo; }
      return {body: body, errs: errs};
    }

    function covDefaults(scr) {
      var to = scr.st.covTo || ymd(now());
      var from = scr.st.covFrom || ymd(new Date(now().getTime() - 34 * 86400000));
      return {from: from, to: to};
    }

    var COLLECT = {
      sources: {
        status: function () { return api.get("/api/collect/status"); },
        cov: function (scr) {
          var p = covDefaults(scr);
          return api.get("/api/collect/coverage?from=" + encodeURIComponent(p.from) + "&to=" + encodeURIComponent(p.to));
        }
      },
      cards: [
        {id: "run", title: "수집 실행", uses: ["status"], view: function (scr, d) {
          var j = jobOfKind(["collect"]);
          var running = j && !FINISHED[j.state];
          return h("div", {}, [
            h("div", {"class": "table-tools"}, [Kt.btn("수집", "a-collect", "auto", {kind: "primary", icon: "play", why: running ? "수집이 진행 중입니다" : null}),
              Kt.btn("탐침만", "a-collect", "probe-only", {kind: "ghost", why: running ? "수집이 진행 중입니다" : null})]),
            h("div", {"class": "table-tools", role: "group", "aria-label": "기간 다시 수집"}, [
              Kt.field("rc-since", "시작 날짜", Kt.input("rc-since", "date", null)), Kt.field("rc-until", "끝 날짜", Kt.input("rc-until", "date", null)),
              Kt.btn("기간 다시 수집", "a-collect", "recollect", {kind: "ghost", why: running ? "수집이 진행 중입니다" : null})]),
            running ? h("div", {}, [U0.statusText("run", "진행 중"), stageTable(j), Kt.btn("중지", "a-cancel", j.job_id, {kind: "danger", icon: "stop"})]) :
              (j ? stageTable(j) : null),
            collectResult(obj(d.status).last)]);
        }},
        {id: "pc", title: "이 PC", uses: ["status"], view: function (scr, d) {
          var pc = obj(obj(d.status).pc);
          var ag = obj(pc.agent);
          var bl = obj(pc.bundle_location);
          var roles = arr(pc.roles);
          var all = arr(pc.roles_all).length ? arr(pc.roles_all) : Object.keys(ROLE_NAME);
          return h("div", {}, [
            Kt.field("pc-label", "이 PC 이름(20자 이하, 이 PC 에만 저장)", Kt.input("pc-label", "text", pc.label_user || "", {maxlength: "20",
              placeholder: pc.label_auto || ""})),
            h("div", {"class": "table-tools"}, [Kt.btn("이름 저장", "a-pc-label", "", {kind: "ghost"})]),
            h("p", {}, ["종류: " + (PC_KIND[pc.kind] || pc.kind || "미확인") + (pc.kind_confirmed ? "" : "(추정) "),
              pc.kind && !pc.kind_confirmed ? Kt.btn("맞음", "a-pc-kind", pc.kind, {kind: "ghost"}) : null]),
            h("div", {"class": "table-tools", role: "group", "aria-label": "수집 역할"}, all.map(function (r) {
              var on = roles.indexOf(r) >= 0;
              return Kt.btn((on ? "✓ " : "") + (ROLE_NAME[r] || r), "a-pc-role", r, {kind: "ghost", pressed: on});
            })),
            Kt.para("에이전트: " + (ag.impl ? "구현 " + ag.impl + " · " : "") + (ag.last_tick ? "마지막 틱 " + md(ag.last_tick) + " · " : "") +
              (ag.task ? "작업 " + ag.task + " · " : "") + (ag.state_ko || ag.state || "미확인")),
            h("div", {"class": "table-tools"}, [Kt.btn("에이전트 복구", "a-agent-repair", "", {kind: "ghost"})]),
            bl.text_ko || bl.verdict ? Kt.para("번들 위치: " + str(bl.verdict) + (bl.text_ko ? " — " + bl.text_ko : "")) : null]);
        }},
        {id: "bundle", title: "번들 현황", uses: ["status"], view: function (scr, d) {
          var s = obj(d.status);
          var rows = arr(s.pcs).map(function (p) {
            return [p.label || p.pc_id || "PC", PC_KIND[p.kind] || str(p.kind), str(p.first_visit) + " ~ " + str(p.last_visit), str(p.last_export),
              isNum(p.segments) ? String(p.segments) : "—", isNum(p.mb) ? U0.fmtNum(p.mb, 1) : "—", str(p.agent_ko || p.agent), str(p.move_ready_ko || p.move_ready)];
          });
          var ar = obj(s.arrival);
          return h("div", {}, [
            rows.length ? Kt.table(["PC", "종류", "처음 ~ 마지막 방문", "마지막 내보내기", {label: "세그먼트", num: true}, {label: "MB", num: true}, "에이전트", "이동 준비"], rows,
              {label: "번들 PC 현황"}) : Kt.emptyP("이 번들에는 아직 PC 기록이 없습니다."),
            ar.text_ko ? U0.alertLine(arr(ar.missing).length ? "warn" : "info", ar.text_ko) : null,
            arr(ar.missing).length ? Kt.table(["PC", "세그먼트"], arr(ar.missing).map(function (m) { return [str(obj(m).pc), str(obj(m).seg || m)]; })) : null,
            arr(obj(s.space).top).length ? Kt.para("용량을 많이 쓰는 곳: " + arr(s.space.top).map(function (t) { return str(obj(t).name || t) + (isNum(obj(t).mb) ? " " + U0.fmtNum(t.mb, 1) + "MB" : ""); }).join(" · ")) : null,
            h("div", {"class": "table-tools"}, [Kt.btn("이동 준비", "a-move", "", {kind: "ghost"})]),
            h("div", {"class": "table-tools", role: "group", "aria-label": "다른 번들 합치기"}, [Kt.field("merge-dir", "합칠 번들 폴더", Kt.input("merge-dir", "text", null)),
              Kt.btn("다른 번들 합치기", "a-merge", "", {kind: "ghost"})])]);
        }},
        {id: "coverage", title: "커버리지 원장", uses: ["cov", "status"], view: function (scr, d) {
          var p = covDefaults(scr);
          var todo = arr(obj(d.status).todo).map(function (t) {
            var row = [str(t.from) + " ~ " + str(t.to), str(t.axis_ko || t.axis), str(t.want_src) + "@" + str(t.want_pc), arr(t.reasons).map(function (c) {
              return obj(obj(d.status).reason_text)[c] || c;
            }).join(", "), String(num(t.tries)), str(t.state_ko || t.state)];
            return t.mine ? row.map(function (x) { return h("strong", {}, [x]); }) : row;
          });
          var cells = arr(obj(d.cov).cells).map(function (c) { return [str(c.week), str(c.src), String(num(c.n)), String(num(c.n_minute)), String(num(c.n_date)), str(c.status_ko || c.status)]; });
          return h("div", {}, [
            h("div", {"class": "table-tools", role: "group", "aria-label": "커버리지 기간(최대 92일)"}, [
              Kt.field("cov-from", "시작", Kt.input("cov-from", "date", p.from)), Kt.field("cov-to", "끝", Kt.input("cov-to", "date", p.to)),
              Kt.btn("기간 바꾸기", "a-cov", "", {kind: "ghost"})]),
            scr.st.covErr ? Kt.errLine("cov-from", scr.st.covErr) : null,
            scr.st.covDay ? Kt.para("고른 날: " + scr.st.covDay) : null,
            coverageChart(scr, d.cov, "ch-h01"),
            cells.length ? Kt.table(["주", "출처", {label: "n", num: true}, {label: "분 단위", num: true}, {label: "날짜만", num: true}, "상태"], cells, {label: "출처별 셀"}) : null,
            h("h3", {}, ["할 일(todo)"]),
            todo.length ? Kt.table(["대상 기간", "축", "원하는 출처@PC", "사유", {label: "시도", num: true}, "상태"], todo, {label: "할 일 — 이 PC 에 배정된 것은 굵게"}) :
              Kt.emptyP("남은 할 일이 없습니다.")]);
        }},
        {id: "worklog", title: "수동 업무 기록", uses: ["status"], view: function (scr, d) {
          var list = arr(obj(d.status).worklog).slice(0, 30).map(function (w) {
            return [str(w.date), str(w.kind_ko || w.kind), isNum(w.minutes) ? U0.hText(w.minutes) : (w.a && w.b ? w.a + "~" + w.b : "—"),
              str(w.project_label || w.project), str(w.memo), w.retracted ? "취소됨" : Kt.btn("취소 기록", "a-wl-retract", w.id, {kind: "ghost"})];
          });
          return h("div", {}, [worklogForm(scr, d),
            scr.st.wlSaved ? h("div", {"class": "table-tools"}, [Kt.btn("빠른 재분석", "a-quick", "", {kind: "ghost", icon: "play"})]) : null,
            h("h3", {}, ["최근 기록"]), list.length ? Kt.table(["날짜", "종류", {label: "시간", num: true}, "과제", "메모(정제본)", ""], list) : Kt.emptyP("수동 기록이 아직 없습니다."),
            Kt.muted("기록은 지우지 않고 [취소 기록]을 덧붙입니다(번들 세그먼트는 바뀌지 않습니다).")]);
        }},
        {id: "import", title: "반입 폴더", uses: ["status"], view: function (scr, d) {
          var im = obj(obj(d.status)["import"]);
          var w = obj(im.waiting);
          return h("div", {}, [Kt.para("위치: " + (im.dir || "data\\import")),
            Kt.para("대기 파일: EML " + num(w.eml) + " · CSV " + num(w.csv) + " · ICS " + num(w.ics)),
            im.last_text ? Kt.para("마지막 반입: " + im.last_text) : null,
            Kt.muted("웹·앱 어디서도 못 읽는 기간은 Outlook 에서 내보낸 파일을 이 폴더에 넣으면 다음 [수집]에서 읽습니다")]);
        }}],
      handlers: {
        "a-collect": function (scr, n, mode) {
          var body = {mode: mode};
          if (mode === "recollect") {
            body.since = val("rc-since");
            body.until = val("rc-until");
            if (!/^\d{4}-\d{2}-\d{2}$/.test(body.since) || !/^\d{4}-\d{2}-\d{2}$/.test(body.until) || body.until < body.since) {
              cardOf(scr, "run").msg = {kind: "warn", text: "다시 수집할 시작·끝 날짜를 넣어 주세요(끝 ≥ 시작)"};
              rerender(scr, "run");
              return;
            }
          }
          send(scr, "run", "post", "/api/collect/run", body, {job: "collect", ok: "수집을 시작했습니다 — 단계가 끝나는 대로 여기에 보입니다"});
        },
        "a-cancel": function (scr, n, id) {
          api.post("/api/jobs/" + encodeURIComponent(id) + "/cancel", {}).then(function (res) {
            notice(res.ok ? "info" : "bad", res.ok ? "중지를 요청했습니다 — 다음 [수집]이 남은 것부터 이어 합니다." : res.error);
            schedulePoll(true);
          });
        },
        "a-pc-label": function (scr) {
          send(scr, "pc", "post", "/api/pc/label", {label_user: Array.from(str(val("pc-label")).trim()).slice(0, 20).join("")},
            {ok: "이 PC 이름을 저장했습니다(이 PC 에만)", reload: ["status"]});
        },
        "a-pc-role": function (scr, n, role) {
          var roles = arr(obj(obj(obj(scr.src.status).data).pc).roles).slice();
          var i = roles.indexOf(role);
          if (i >= 0) { roles.splice(i, 1); } else { roles.push(role); }
          send(scr, "pc", "post", "/api/pc/roles", {roles: roles.sort()}, {ok: "수집 역할을 바꿨습니다", reload: ["status"]});
        },
        "a-pc-kind": function (scr, n, kind) {
          send(scr, "pc", "post", "/api/pc/kind", {kind: kind, confirmed: true}, {ok: "이 PC 종류를 확정했습니다", reload: ["status"]});
        },
        "a-agent-repair": function (scr) { send(scr, "pc", "post", "/api/agent/repair", {}, {job: "agent_repair", ok: "에이전트 복구를 시작했습니다"}); },
        "a-quick": function (scr) {
          var cur = S.current;
          if (!cur || !cur.run_id) { cardOf(scr, "worklog").msg = {kind: "info", text: "아직 분석 결과가 없습니다 — 분석 화면에서 기간을 정해 실행하면 반영됩니다"}; rerender(scr, "worklog"); return; }
          send(scr, "worklog", "post", "/api/analysis/run", {rerun: cur.run_id, stages: ["classify", "time", "mining", "report"], ai: false},
            {job: "quick_reanalyze", ok: "빠른 재분석을 시작했습니다 — 끝나면 개인 보고서에 반영됩니다"});
        },
        "a-move": function (scr) {
          U0.openDrawer(h("div", {}, [Kt.para("이 화면을 닫고 이동 시험 창을 엽니다. 창에 '[완료]'가 나오면 폴더를 옮기세요."),
            h("div", {"class": "table-tools"}, [Kt.btn("이동 준비 시작", "a-move-ok", "", {kind: "primary"}), Kt.btn("취소", "drawer-close", "", {kind: "ghost"})])]),
          {doc: doc, title: "이동 준비", handlers: {"a-move-ok": function () {
            U0.closeDrawer();
            send(scr, "bundle", "post", "/api/move/prepare", {}, {job: "move_prepare", ok: "이동 준비를 시작했습니다"});
          }}});
        },
        "a-merge": function (scr) {
          var dir = str(val("merge-dir")).trim();
          if (!dir) { cardOf(scr, "bundle").msg = {kind: "warn", text: "합칠 번들 폴더를 넣어 주세요"}; rerender(scr, "bundle"); return; }
          send(scr, "bundle", "post", "/api/bundle/merge", {dir: dir}, {job: "bundle_merge", ok: "번들 합치기를 시작했습니다"});
        },
        "a-cov": function (scr) {
          var f = val("cov-from");
          var t = val("cov-to");
          if (!/^\d{4}-\d{2}-\d{2}$/.test(f) || !/^\d{4}-\d{2}-\d{2}$/.test(t) || t < f || daysBetween(f, t) > 91) {
            scr.st.covErr = "기간은 최대 92일입니다(끝 ≥ 시작)";
            rerender(scr, "coverage");
            return;
          }
          scr.st.covErr = null;
          scr.st.covFrom = f;
          scr.st.covTo = t;
          source(scr, "cov", true);
        },
        "a-wl-save": function (scr) {
          var r = readWorklog();
          scr.st.wlErr = Object.keys(r.errs).length ? r.errs : null;
          if (scr.st.wlErr) {
            rerender(scr, "worklog");
            var first = ["date", "a", "b", "hours", "memo"].filter(function (k) { return r.errs[k]; })[0];
            var fe = first && doc.getElementById("wl-" + first);
            if (fe && fe.focus) { fe.focus(); }
            return;
          }
          send(scr, "worklog", "post", "/api/worklog", r.body, {reset: true, reload: ["status"],
            ok: "기록했습니다 — 다시 분석하면 반영됩니다", after: function () { scr.st.wlSaved = true; }});
        },
        "a-wl-retract": function (scr, n, id) {
          send(scr, "worklog", "post", "/api/worklog", {retract: id}, {reload: ["status"], ok: "취소 기록을 덧붙였습니다 — 다시 분석하면 반영됩니다"});
        }
      },
      init: function (scr) {
        if (/^\d{4}-\d{2}-\d{2}$/.test(str(scr.arg))) { scr.st.covDay = scr.arg; }
        scr.onJobs = function () { rerender(scr, "run"); };
      }
    };

    // ── 4.7 분석(§5.3) ──
    function rangeOf(kind, months) {
      var d = now();
      var y = d.getFullYear();
      var m = d.getMonth() + 1;
      var today = ymd(d);
      if (kind === "this_month") { return {from: monthFirst([y, m]), to: today}; }
      if (kind === "last_month") { var p = addMonths(y, m, -1); return {from: monthFirst(p), to: monthLast(p)}; }
      if (kind === "this_year") { return {from: y + "-01-01", to: today}; }
      var n = months > 0 ? months : 3;
      return {from: monthFirst(addMonths(y, m, -(n - 1))), to: today};
    }

    function hasRole(r) { return arr(obj(obj(S.hello).pc).roles).indexOf(r) >= 0; }

    function runRow(r) {
      var ls = obj(r.label_sources || r.labels);
      var tot = {ai: 0, rule: 0};
      Object.keys(ls).forEach(function (k) { tot.ai += num(obj(ls[k]).ai) + num(obj(ls[k]).manual); tot.rule += num(obj(ls[k]).rule); });
      var cur = S.current && S.current.run_id === r.run_id;
      var stt = JOB_STATE[r.state] || ["unknown", str(r.state)];
      return [h("span", {"class": "mono"}, [str(r.run_id).slice(0, 8)]), str(r.from) + " ~ " + str(r.to), md(r.as_of), md(r.built_at || r.ended),
        U0.statusText(stt[0], stt[1]), tot.ai + tot.rule > 0 ? U0.pctText(tot.ai, tot.ai + tot.rule) : "—", str(r.report_version || "—"),
        cur ? U0.badge("현재 표시") : "",
        h("span", {}, [cur ? null : Kt.btn("이 결과 보기", "a-choose", r.run_id, {kind: "ghost"}),
          Kt.btn("보고서 다시 만들기", "a-rebuild", r.run_id, {kind: "ghost"}), Kt.btn("내보내기", "a-export", r.run_id, {kind: "ghost"})])];
    }

    function analysisRc(st) {
      st = obj(st);
      var stages = arr(st.stages);
      var bad = stages.filter(function (s) { return s.state === "failed"; })[0];
      var reason = str(obj(bad).reason || st.reason);
      if (st.state === "done") { return ["info", "분석을 마쳤습니다. 개인 보고서를 이 결과로 바꿨습니다."]; }
      if (st.state === "partial") {
        var pend = stages.filter(function (s) { return /^ai:/.test(str(s.id)) && s.state !== "done"; }).length;
        return ["warn", "분석을 마쳤습니다. AI 이름 붙이기 " + (isNum(st.ai_pending) ? st.ai_pending : pend) + "건은 규칙 이름으로 임시 표시했고, 다음 분석에서 이어 묻습니다."];
      }
      if (/calendar/.test(reason)) {
        return ["bad", (st.year || obj(bad).year || "그") + "년 공휴일 달력이 확인되지 않아 분석하지 않았습니다(MM 분모가 틀어질 수 있음). 팀 레지스트리를 받으면 다시 시도합니다 — 팀 화면의 [지금 받기]"];
      }
      if (/conserv|preserv/.test(reason)) {
        return ["bad", "계산 검사(근무시간 보존)에 실패해 결과를 만들지 않았습니다. 이전 결과를 그대로 보여 줍니다. 오류 기록은 이 PC 의 data\\logs\\ 에 남았습니다."];
      }
      if (st.state === "failed") { return ["bad", "분석을 끝내지 못했습니다(" + str(obj(bad).name_ko || obj(bad).id || "단계") + ": " + (obj(bad).reason_ko || reason || "사유 미상") + "). 이전 결과를 그대로 보여 줍니다."]; }
      return null;
    }

    var ANALYSIS = {
      sources: {
        runs: function () { return api.get("/api/analysis/runs"); },
        cur: function (scr) {
          return source(scr, "runs").then(function (res) {
            var d = obj(res && res.data);
            var cur = d.current && typeof d.current === "object" ? d.current : listOf(d, "runs").filter(function (r) { return r.current; })[0];
            if (!cur || !cur.run_id) { return {ok: true, data: null}; }
            return api.get("/api/analysis/run/" + encodeURIComponent(cur.run_id));
          });
        },
        bridge: function () { return api.get("/api/bridge/status"); },
        manual: function () { return api.get("/api/bridge/manual"); }
      },
      cards: [
        {id: "run", title: "분석 실행", uses: [], view: function (scr) {
          var months = num(S.defaults.months) || 3;
          var src = scr.st.src || "default";
          var rg = scr.st.range || rangeOf(src === "default" ? "recent" : src, months);
          var copilot = hasRole("copilot");
          return h("div", {}, [
            h("div", {"class": "table-tools", role: "group", "aria-label": "빠른 선택"}, [["this_month", "이번 달"], ["last_month", "지난달"],
              ["default", "최근 " + months + "개월(기본)"], ["this_year", "올해"]].map(function (q) {
              return Kt.btn((src === q[0] ? "✓ " : "") + q[1], "a-range", q[0], {kind: "ghost", pressed: src === q[0]});
            })),
            Kt.field("an-from", "시작 날짜", Kt.input("an-from", "date", rg.from)),
            Kt.field("an-to", "끝 날짜", Kt.input("an-to", "date", rg.to)),
            Kt.field("an-asof", "기준 시각(비우면 지금 — 미래는 고를 수 없음)", Kt.input("an-asof", "datetime-local", null)),
            copilot ? Kt.checkbox("an-ai", "AI 분석 사용", true) :
              h("p", {}, [Kt.checkbox("an-ai", "AI 분석 사용", false, {disabled: true}),
                Kt.muted("이 PC 는 Copilot 역할이 아닙니다 — 규칙 분류로 분석합니다. 클라우드PC 에서 분석하면 AI 라벨이 붙습니다")]),
            scr.st.runErr ? Kt.errLine("an-from", scr.st.runErr) : null,
            h("div", {"class": "table-tools"}, [Kt.btn("분석 실행", "a-analyze", "", {kind: "primary", icon: "play"})])]);
        }},
        {id: "progress", title: "진행", uses: [], when: function () { var j = jobOfKind(["analyze", "quick_reanalyze"]); return !!(j && !FINISHED[j.state]); },
          view: function () {
            var j = jobOfKind(["analyze", "quick_reanalyze"]);
            var seen = {};
            var notes = j.events.filter(function (e) {
              if (e.ev !== "notice" || !e.text_ko) { return false; }
              var k = e.code || e.text_ko;
              if (seen[k]) { return false; }
              seen[k] = true;
              return true;
            }).map(function (e) { return U0.alertLine("info", e.text_ko); });
            var pg = lastProgress(j);
            return h("div", {}, notes.concat([pg ? U0.progressBar(pg.done, pg.total, "분석 진행") : null, stageTable(j),
              Kt.btn("중지", "a-cancel", j.job_id, {kind: "danger", icon: "stop"})]));
          }},
        {id: "copilot", title: "Copilot 상태", uses: ["bridge"], when: function () { return hasRole("copilot"); }, view: function (scr, d) {
          var b = obj(d.bridge);
          return h("div", {}, [
            Kt.para("방식: " + str(b.mode_ko || b.mode || "미확인") + " · 계정 등급: " + str(b.tier || "unknown") + " · 웹 노출: " +
              (b.web_exposed === true ? "있음(엄격 규칙 적용 중)" : (b.web_exposed === false ? "없음" : "미확인"))),
            b.last_probe ? Kt.para("마지막 탐침: " + str(obj(b.last_probe).text_ko || md(obj(b.last_probe).at))) : null,
            isNum(obj(b.limits)["in"]) ? Kt.para("보정 한도: 입력 " + b.limits["in"] + "자 · 답 " + num(b.limits.out) + "자") : null,
            h("div", {"class": "table-tools"}, [Kt.btn("분석용 Edge 창 앞으로", "a-front", "", {kind: "ghost"})])]);
        }},
        {id: "manual", title: "직접 붙여넣기", uses: ["manual"], when: function (scr) {
          var m = obj(obj(scr.src.manual).data);
          return hasRole("copilot") && listOf(m, "batches").some(function (b) { return b.state === "open"; });
        }, view: function (scr, d) {
          var bs = listOf(d.manual, "batches");
          var open = bs.filter(function (b) { return b.state === "open"; }).length;
          var rows = bs.map(function (b) {
            return [String(b.seq), str(b.stage_ko || b.stage), String(arr(b.items).length || num(b.items_n)), String(num(b.in_chars || b.chars)),
              str(b.state_ko || b.state), b.state === "open" ? Kt.btn("복사", "a-copy", b.seq, {kind: "ghost"}) : "",
              b.state === "open" ? Kt.btn("답 붙여넣기", "a-paste-focus", b.seq, {kind: "ghost"}) : ""];
          });
          var res = obj(scr.st.importRes);
          return h("div", {}, [h("p", {}, [U0.badge("Copilot: 직접 붙여넣기 방식 · 남은 묶음 " + open + "개(약 " + open + "번 붙여넣기)")]),
            Kt.table(["순번", "단계", {label: "항목", num: true}, {label: "글자", num: true}, "상태", "", ""], rows),
            scr.st.copyText ? Kt.field("mp-copytext", "복사할 글(클립보드가 막혀 직접 선택·복사)", Kt.textarea("mp-copytext", scr.st.copyText, {rows: "6", readonly: true})) : null,
            Kt.field("mp-answer", "Copilot 답(여러 답을 한꺼번에 붙여넣어도 됩니다)", Kt.textarea("mp-answer", "", {rows: "6"})),
            h("div", {"class": "table-tools"}, [Kt.btn("답 반입", "a-import", "", {kind: "primary"})]),
            arr(res.results).length ? Kt.table(["요청 번호", "결과", "건수"], arr(res.results).map(function (r) {
              return [str(obj(r).rid), str(obj(r).status_ko || obj(r).status), str(obj(r).counts_ko || "")];
            })) : null,
            res.text_ko ? Kt.para(res.text_ko) : null]);
        }},
        {id: "history", title: "분석 이력", uses: ["runs"], view: function (scr, d) {
          var runs = listOf(d.runs, "runs");
          if (!runs.length) { return Kt.emptyP("아직 분석 결과가 없습니다. 위에서 기간을 정해 [분석 실행]을 누르세요."); }
          return h("div", {}, [Kt.table(["실행", "기간", "기준 시각", "분석 시각", "상태", {label: "AI 비율", num: true}, "보고서 판", "", "동작"], runs.map(runRow),
            {label: "분석 이력"}), Kt.muted("분석 결과는 설정한 개수까지 두고 오래된 것부터 정리합니다(지금 보는 결과는 지우지 않음).")]);
        }},
        {id: "result", title: "결과 요약", uses: ["cur"], view: function (scr, d) {
          var r = obj(d.cur);
          if (!d.cur) { return Kt.emptyP("아직 분석 결과가 없습니다. [분석] 화면에서 기간을 정해 실행하세요."); }
          var rc = analysisRc(r.status);
          var labels = obj(r.labels);
          var lrows = Object.keys(labels).sort().map(function (k) {
            var x = obj(labels[k]);
            return [k, String(num(x.ai)), String(num(x.manual)), String(num(x.rule)), String(num(x.pending))];
          });
          var au = obj(r.time_audit);
          var q = obj(r.queue);
          return h("div", {}, [rc ? U0.alertLine(rc[0], rc[1]) : null,
            lrows.length ? Kt.table(["단계", {label: "AI", num: true}, {label: "붙여넣기", num: true}, {label: "규칙", num: true}, {label: "다시 물음", num: true}], lrows,
              {label: "단계별 라벨 출처"}) : null,
            Object.keys(au).length ? Kt.para("시간 코어 감사(버린 건수): " + Object.keys(au).sort().map(function (k) { return k + " " + au[k]; }).join(" · ")) : null,
            arr(r.warnings).map(function (w) { return U0.alertLine("warn", obj(w).text_ko || str(w)); }),
            Kt.para("확인 질문: 열림 " + num(q.open) + " · 응답 " + num(q.answered)),
            Kt.link("개인 보고서 열기", "#report/summary")]);
        }}],
      handlers: {
        "a-range": function (scr, n, kind) {
          scr.st.src = kind;
          scr.st.range = rangeOf(kind === "default" ? "recent" : kind, num(S.defaults.months) || 3);
          var c = cardOf(scr, "run");
          c.reset = true;
          rerender(scr, "run");
        },
        "a-analyze": function (scr) {
          var from = val("an-from");
          var to = val("an-to");
          var asOf = str(val("an-asof"));
          var months = num(S.defaults.months) || 3;
          var src = scr.st.src || "default";
          var exp = scr.st.range || rangeOf(src === "default" ? "recent" : src, months);
          if (!/^\d{4}-\d{2}-\d{2}$/.test(from) || !/^\d{4}-\d{2}-\d{2}$/.test(to) || to < from) {
            scr.st.runErr = "시작·끝 날짜를 넣어 주세요(끝 ≥ 시작)";
            rerender(scr, "run");
            return;
          }
          if (asOf && asOf.replace("T", " ") > ymd(now()) + " " + pad2(now().getHours()) + ":" + pad2(now().getMinutes())) {
            scr.st.runErr = "기준 시각은 지금보다 늦을 수 없습니다";
            rerender(scr, "run");
            return;
          }
          scr.st.runErr = null;
          var body = {from: from, to: to, ai: hasRole("copilot") && checked("an-ai"),
            period_source: from === exp.from && to === exp.to ? src : "user", period_months: src === "default" ? months : null};
          if (asOf) { body.as_of = asOf; }
          send(scr, "run", "post", "/api/analysis/run", body, {job: "analyze", ok: "분석을 시작했습니다 — 진행은 아래 카드와 오른쪽 위 [작업]에서 보입니다"});
        },
        "a-cancel": function (scr, n, id) {
          api.post("/api/jobs/" + encodeURIComponent(id) + "/cancel", {}).then(function (res) {
            notice(res.ok ? "info" : "bad", res.ok ? "중지를 요청했습니다 — 다음 분석이 남은 것부터 이어 합니다." : res.error);
            schedulePoll(true);
          });
        },
        "a-choose": function (scr, n, id) {
          send(scr, "history", "post", "/api/analysis/current", {run_id: id}, {ok: "이 결과를 개인 보고서에 보이도록 바꿨습니다", reload: ["runs", "cur"],
            after: function () { refreshGlobal(); }});
        },
        "a-rebuild": function (scr, n, id) { send(scr, "history", "post", "/api/report/build", {run_id: id}, {job: "report_build", ok: "보고서를 다시 만듭니다"}); },
        "a-export": function (scr, n, id) {
          send(scr, "history", "post", "/api/report/export", {run_id: id}, {job: "report_export", ok: "내보내기를 시작했습니다 — 끝나면 만든 파일 목록을 보여 드립니다"});
        },
        "a-front": function (scr) { send(scr, "copilot", "post", "/api/bridge/front", {}, {ok: "분석용 Edge 창을 앞으로 띄웠습니다 — 로그인이 필요하면 그 창에서 한 번 로그인해 주세요"}); },
        "a-copy": function (scr, n, seq) {
          api.post("/api/bridge/manual/copy", {seq: +seq}).then(function (res) {
            var text = str(obj(res.data).text);
            if (!res.ok || !text) { cardOf(scr, "manual").msg = {kind: "bad", text: res.error || "복사할 글을 받지 못했습니다"}; rerender(scr, "manual"); return; }
            var clip = win.navigator && win.navigator.clipboard;
            var done = function () { scr.st.copyText = null; cardOf(scr, "manual").msg = {kind: "info", text: "복사했습니다 — Copilot 창에 붙여넣고, 답 전체를 복사해 아래 상자에 넣어 주세요"}; rerender(scr, "manual"); };
            var fail = function () { scr.st.copyText = text; cardOf(scr, "manual").msg = {kind: "warn", text: "클립보드에 넣지 못했습니다 — 아래 글 상자에서 직접 선택해 복사해 주세요"}; rerender(scr, "manual"); };
            if (clip && clip.writeText) { Promise.resolve(clip.writeText(text)).then(done, fail); } else { fail(); }
          });
        },
        "a-paste-focus": function () { var t = doc.getElementById("mp-answer"); if (t && t.focus) { t.focus(); } },
        "a-import": function (scr) {
          var text = str(val("mp-answer"));
          if (!text.trim()) { cardOf(scr, "manual").msg = {kind: "warn", text: "붙여넣은 답이 없습니다"}; rerender(scr, "manual"); return; }
          send(scr, "manual", "post", "/api/bridge/manual/import", {text: text}, {reset: true, reload: ["manual"],
            ok: function (d) { return obj(d).text_ko || "답을 반영했습니다"; }, after: function (d) { scr.st.importRes = obj(d); }});
        }
      },
      init: function (scr) {
        scr.onJobs = function () { rerender(scr, "progress"); };
        scr.onGlobal = function () { rerender(scr, "run"); rerender(scr, "history"); };
      },
      lazy: {}
    };

    // ── 4.8 개인 보고서(§5.4) — report.js 에 맡긴다 ──
    function reportActions() {
      function jobbed(kind) { return function (res) { return trackFrom(res, kind, {}); }; }
      return {
        answer: function (qid, answer) { return api.post("/api/queue/answer", {qid: qid, answer: answer}).then(jobbed("quick_reanalyze")); },
        correction: function (body) { return api.post("/api/hier/correction", body).then(jobbed("quick_reanalyze")); },
        proposal: function (body) { return api.post("/api/hier/proposal", body).then(jobbed("quick_reanalyze")); },
        codename: function (body) { return api.post("/api/hier/codename", body); },
        rule: function (body) { return api.post("/api/hier/rule", body); },
        needDrop: function (id, drop) { return api.post("/api/agentic/need/drop", {need_id: id, drop: drop}); },
        mergeQuestion: function (a, b) { return api.post("/api/queue/answer", {qid: null, code: "Q12", answer: {choice: "must_link", units: [a, b]}}); },
        exportReport: function (body) { return api.post("/api/report/export", body).then(jobbed("report_export")); },
        hierState: function () { return api.get("/api/hier/state"); }
      };
    }

    function reportScreen(scr) {
      var host = scr.el;
      U0.render(Kt.card("개인 보고서", Kt.para("보고서를 읽는 중입니다…", "muted"), {id: "rp-loading"}), host);
      api.get("/api/report?variant=full").then(function (res) {
        if (!scr.alive) { return; }
        var d = obj(res.data);
        if (!res.ok) {
          var code = res.code;
          if (code === "rebuilding" && d.job_id) {
            track(d.job_id, "report_build", {});
            U0.render(Kt.card("개인 보고서", U0.alertLine("info", "보고서를 새 형식으로 다시 만드는 중입니다"), {id: "rp-msg"}), host);
            return;
          }
          if (code === "run_missing") {
            var runs = S.runs || [];
            U0.render(Kt.card("개인 보고서", h("div", {}, [U0.alertLine("warn", "보던 결과(" + str(d.run_id).slice(-8) + ")가 정리되었습니다 — 이력에서 고르세요"),
              runs.length ? Kt.table(["실행", "기간", ""], runs.map(function (r) {
                return [str(r.run_id).slice(0, 8), str(r.from) + " ~ " + str(r.to), Kt.btn("이 결과 보기", "a-pick", r.run_id, {kind: "ghost"})];
              })) : null, Kt.link("분석 화면", "#analysis")]), {id: "rp-msg"}), host);
            scr.off = U0.delegate(host, {"a-pick": function (n, id) {
              api.post("/api/analysis/current", {run_id: id}).then(function (r2) {
                if (r2.ok) { refreshGlobal(); openScreen("report", scr.arg, true); } else { notice("bad", r2.error); }
              });
            }});
            return;
          }
          if (code === "no_current" || res.status === 404) {
            U0.render(Kt.card("개인 보고서", h("div", {}, [Kt.emptyP("아직 분석 결과가 없습니다. [분석] 화면에서 기간을 정해 실행하세요."),
              Kt.link("분석 화면", "#analysis")]), {id: "rp-msg"}), host);
            return;
          }
          U0.render(Kt.card("개인 보고서", h("div", {}, [U0.alertLine("bad", "보고서를 읽지 못했습니다 — " + res.error),
            Kt.btn("다시 읽기", "a-again", "", {kind: "ghost"})]), {id: "rp-msg"}), host);
          scr.off = U0.delegate(host, {"a-again": function () { openScreen("report", scr.arg, true); }});
          return;
        }
        var model = res.data;
        var runId = str(obj(obj(model).run).run_id);
        if (!deps().R.majorOk(model)) {
          if (!S.rebuildAsked[runId]) {
            S.rebuildAsked[runId] = true;
            api.post("/api/report/build", {run_id: runId}).then(function (r3) { trackFrom(r3, "report_build", {}); });
          }
          U0.render(Kt.card("개인 보고서", U0.alertLine("info", "보고서를 새 형식으로 다시 만드는 중입니다"), {id: "rp-msg"}), host);
          return;
        }
        U0.clear(host);
        var box = U0.mount(h("div", {id: "report-root"}), host);
        var ctl = deps().R.create(box, {model: model, mode: "app", variant: "full", storage: storage, doc: doc, win: win,
          actions: reportActions(), exportDefaults: obj(d.export_defaults),
          drill: {
            unit: function (id) {
              return api.get("/api/report/unit/" + encodeURIComponent(id) + "?run=" + encodeURIComponent(runId)).then(function (r4) {
                if (r4.ok) { return r4.data; }
                if (r4.status === 404) { return null; }
                return Promise.reject({text_ko: r4.error});
              });
            },
            day: function (dd) {
              return api.get("/api/report/day/" + encodeURIComponent(dd) + "?run=" + encodeURIComponent(runId)).then(function (r5) {
                if (r5.ok) { return r5.data; }
                if (r5.status === 404) { return null; }
                return Promise.reject({text_ko: r5.error});
              });
            }
          }});
        S.report = ctl;
        var p = deps().R.parseRoute("#report/" + str(scr.arg));
        ctl.go(p.section || "summary", p.arg);
      });
      scr.onArg = function (arg) {
        if (S.report) {
          var p = deps().R.parseRoute("#report/" + str(arg));
          S.report.go(p.section || "summary", p.arg);
        }
      };
    }

    function showExportResult(j) {
      var r = obj(j.result);
      var data = obj(r.data).files ? obj(r.data) : r;
      var files = arr(data.files);
      U0.openDrawer(h("div", {}, [files.length ? Kt.table(["파일", "변형", {label: "크기", num: true}], files.map(function (f) {
        return [str(f.path), h("span", {}, [str(f.variant), f.variant === "full" ? " " : null, f.variant === "full" ? U0.badge("로컬 전용") : null]),
          isNum(f.bytes) ? U0.fmtNum(f.bytes / 1024, 1) + "KB" : "—"];
      })) : Kt.para("만든 파일 목록을 받지 못했습니다 — out\\personal\\ 폴더에 있습니다."),
      U0.alertLine("info", "전체판에는 동료 이름·문서 이름이 들어 있습니다 — 내 PC 밖으로 보내지 마세요(공유는 가림판)"),
      h("div", {"class": "table-tools"}, [Kt.btn("폴더 열기", "a-open-folder", "", {kind: "ghost"})])]),
      {doc: doc, title: "내보낸 파일", handlers: {"a-open-folder": function () {
        api.post("/api/report/export/open", {dir: data.dir || null, run_id: data.run_id || null}).then(function (res) {
          if (!res.ok) { notice("bad", res.error); }
        });
      }}});
    }

    // ── 4.9 팀(§5.5) ──
    function teamSettingsBody(scr, d) {
      var s = obj(obj(d.status).settings);
      var e = obj(scr.st.teamErr);
      var members = arr(obj(d.status).members);
      return h("div", {}, [
        Kt.field("tm-host", "IP", Kt.input("tm-host", "text", s.server_host, {"aria-invalid": e.server_host ? "true" : null, autocomplete: "off"}),
          {error: e.server_host}),
        Kt.field("tm-port", "포트", Kt.input("tm-port", "number", s.server_port, {min: "1", max: "65535", "aria-invalid": e.server_port ? "true" : null}),
          {error: e.server_port}),
        h("div", {"class": "table-tools"}, [Kt.btn("연결 확인", "a-ping", "", {kind: "ghost"}), Kt.btn("기본값으로", "a-reset-addr", "", {kind: "ghost"})]),
        scr.st.ping ? U0.alertLine(scr.st.ping.ok ? "info" : "warn", scr.st.ping.text) : null,
        Kt.field("tm-alt", "대체 주소(한 줄에 host:port, 최대 5줄 — 순서 = 시도 순서)", Kt.textarea("tm-alt", arr(s.server_alternates).join("\n"),
          {rows: "3", "aria-invalid": e.server_alternates ? "true" : null}), {error: e.server_alternates}),
        h("p", {}, ["업로드 토큰: ", U0.badge(s.token_set ? "설정됨" : "없음"), " ",
          Kt.btn("변경", "a-open", "token", {kind: "ghost", expanded: !!scr.st["open:token"]})]),
        scr.st["open:token"] ? h("div", {"class": "table-tools"}, [Kt.field("tm-token", "새 업로드 토큰", Kt.input("tm-token", "password", null, {autocomplete: "off"})),
          Kt.btn("토큰 저장", "a-token", "", {kind: "ghost"})]) : null,
        Kt.field("tm-label", "내 표시 라벨(20자 이하)", Kt.input("tm-label", "text", s.self_label, {maxlength: "20", "aria-invalid": e.self_label ? "true" : null}),
          {error: e.self_label}),
        Kt.field("tm-member", "구성원 ID", Kt.select("tm-member", [["", "고르지 않음"]].concat(members.map(function (m) {
          return [m.member_id || m.id, m.label || m.member_id || m.id];
        })), s.member_id || "")),
        Kt.field("tm-title", "단위업무 제목", Kt.select("tm-title", [["label", "label — 분류 제목 그대로(기본)"], ["generic", "generic — '<분야>·<기능> 단위업무 #n'"]],
          s.unit_title_mode || "label"), {help: "generic 은 모든 제목을 '<분야>·<기능> 단위업무 #n' 으로 바꿔 보냅니다"}),
        Kt.checkbox("tm-unknown", "미상 프로그램 이름 제안 보내기", !!s.share_unknown_apps),
        Kt.checkbox("tm-auto", "자동 전송", !!s.auto_send),
        Kt.muted("자동 전송을 끄면 기간마다 처음 한 번 미리보기에서 [보내기]를 눌러야 합니다"),
        h("div", {"class": "table-tools"}, [Kt.btn("저장", "a-team-save", "", {kind: "primary"})])]);
    }

    function outboxRows(list) {
      return list.map(function (it) {
        var id = it.item || it.name;
        var stt = str(it.state);
        var acts = [Kt.btn("미리보기", "a-preview", id, {kind: "ghost"})];
        if (stt === "pending" || stt === "failed" || stt === "retry_wait") { acts.push(Kt.btn(stt === "pending" ? "보내기" : "다시 시도", "a-send", id, {kind: "ghost"})); }
        if (stt !== "sent" && stt !== "delivered" && stt !== "dropped") {
          acts.push(Kt.btn("파일로 내보내기", "a-export-item", id, {kind: "ghost"}));
          acts.push(Kt.btn("치우기", "a-drop", id, {kind: "ghost"}));
        }
        return [str(it.period_key || it.period), str(it.built_on_label || it.built_on), md(it.built_at), isNum(it.bytes) ? U0.fmtNum(it.bytes / 1024, 1) + "KB" : "—",
          h("span", {"class": "mono"}, [str(it.sha12 || str(it.sha256).slice(0, 12))]), (OUTBOX_STATE[stt] || stt) + (stt === "retry_wait" && it.next_at ? "(" + md(it.next_at) + ")" : ""),
          str(it.last_error_ko || it.last_error), h("span", {}, acts)];
      });
    }

    function openPreview(item) {
      api.get("/api/team/preview/" + encodeURIComponent(item)).then(function (res) {
        if (!res.ok) { notice("bad", res.error); return; }
        var p = obj(res.data);
        var sum = obj(p.summary);
        var blockers = arr(p.blockers);
        var why = blockers.length ? blockers.map(function (b) { return str(obj(b).text_ko || b); }).join(" · ") : null;
        var units = arr(p.units).map(function (u) {
          return [str(u.title), str(u.role_label || u.role), U0.hText(u.effort_min), str(u.grade), str(u.mask_ko || u.mask || ""),
            h("span", {}, [Kt.btn("제목 가림", "a-mask", u.unit_id + "|title", {kind: "ghost"}), Kt.btn("세부 가림", "a-mask", u.unit_id + "|detail", {kind: "ghost"}),
              Kt.btn("되돌리기", "a-mask", u.unit_id + "|none", {kind: "ghost"})])];
        });
        var needs = arr(p.needs).map(function (n) { return [str(n.label || n.name), str(n.step_type), str(n.grade), Kt.btn("빼기", "a-drop-need", n.need_id, {kind: "ghost"})]; });
        var fb = obj(p.forbidden);
        var openJson = !!S.previewJson;
        var body = h("div", {}, [
          Kt.para("월별 MM: " + arr(sum.months).map(function (m) { return str(obj(m).m) + " " + str(obj(m).mm_text || U0.fmtNum(obj(m).mm, 2)); }).join(" · ") +
            " · 단위업무 " + num(sum.units_n) + " · 동료 키 " + num(sum.peers_n) + " · 니즈 " + num(sum.needs_n)),
          Kt.para("시간 수치(근무시간·업무별 분)는 가릴 수 없습니다 — 빼면 개인과 팀 합계가 달라집니다. 업무를 통째로 숨기려면 [세부 가림]을 쓰세요."),
          units.length ? Kt.table(["제목(보낼 값)", "역할", {label: "투입", num: true}, "등급", "가림", "처리"], units, {label: "가림 표"}) : null,
          needs.length ? Kt.table(["니즈", "단계 유형", "등급", ""], needs) : null,
          Kt.para("금지 내용 검사: " + (num(fb.n) === 0 ? "0건(통과)" : num(fb.n) + "건 — " + arr(fb.paths).join(", "))),
          Kt.para("sha256 앞 12자 " + str(p.sha12) + " · 크기 " + (isNum(p.bytes) ? U0.fmtNum(p.bytes / 1024, 1) + "KB" : "—")),
          why ? U0.alertLine("warn", "보낼 수 없는 이유: " + why) : null,
          h("div", {"class": "table-tools"}, [Kt.btn("보내기", "a-pv-send", item, {kind: "primary", why: why}),
            Kt.btn("승인만(다음 [수집] 때 자동 전송)", "a-pv-approve", item, {kind: "ghost", why: why}),
            Kt.btn(openJson ? "원문 JSON 접기" : "원문 JSON 보기", "a-pv-json", item, {kind: "ghost", expanded: openJson})]),
          openJson ? h("pre", {"class": "mono"}, [str(p.json_text)]) : null]);
        var scr = S.scr;
        U0.openDrawer(body, {doc: doc, title: "팀 묶음 미리보기", wide: true, handlers: {
          "a-pv-send": function (n, it) {
            api.post("/api/team/send/" + encodeURIComponent(it), {}).then(function (r) {
              trackFrom(r, "team_send", {});
              notice(r.ok ? "info" : (r.status === 409 ? "warn" : "bad"), r.ok ? "팀 묶음을 보냈습니다(또는 보내는 중입니다)" : r.error);
              U0.closeDrawer();
              if (scr && scr.name === "team") { source(scr, "status", true); }
            });
          },
          "a-pv-approve": function (n, it) {
            api.post("/api/team/approve/" + encodeURIComponent(it), {}).then(function (r) {
              notice(r.ok ? "info" : "bad", r.ok ? "승인했습니다 — 팀 서버에 닿는 PC 의 다음 [수집] 때 자동으로 보냅니다" : r.error);
              U0.closeDrawer();
              if (scr && scr.name === "team") { source(scr, "status", true); }
            });
          },
          "a-pv-json": function (n, it) { S.previewJson = !S.previewJson; openPreview(it); },
          "a-mask": function (n, ref) {
            var q = str(ref).split("|");
            api.post("/api/team/mask", {unit_id: q[0], mode: q[1]}).then(function (r) {
              trackFrom(r, "team_build", {});
              notice(r.ok ? "info" : "bad", r.ok ? "가림을 바꿔 묶음을 다시 만들었습니다(이전 묶음은 대체됨)" : r.error);
              U0.closeDrawer();
            });
          },
          "a-drop-need": function (n, id) {
            api.post("/api/agentic/need/drop", {need_id: id, drop: true}).then(function (r) {
              notice(r.ok ? "info" : "bad", r.ok ? "그 니즈를 팀 묶음에서 뺍니다 — 묶음을 다시 만들면 반영됩니다" : r.error);
            });
          }
        }});
      });
    }

    var TEAM = {
      sources: {
        status: function () { return api.get("/api/team/status"); },
        local: function () { return api.get("/api/teamserver/local"); }
      },
      lazy: {local: true},
      cards: [
        {id: "addr", title: "팀 서버 주소", uses: ["status"], view: teamSettingsBody},
        {id: "outbox", title: "팀 묶음 대기열", uses: ["status"], view: function (scr, d) {
          var list = listOf(obj(d.status).outbox, "items");
          return h("div", {}, [h("div", {"class": "table-tools"}, [Kt.btn("팀 묶음 만들기", "a-team-build", "", {kind: "primary",
            why: S.current ? null : "분석 결과가 있어야 묶음을 만들 수 있습니다"})]),
          list.length ? Kt.table(["기간", "만든 곳", "만든 시각", {label: "크기", num: true}, "sha", "상태", "마지막 실패 사유", "행동"], outboxRows(list), {label: "팀 묶음 대기열"}) :
            Kt.emptyP("보낼 묶음이 없습니다. 분석을 마친 뒤 [팀 묶음 만들기]를 누르세요.")]);
        }},
        {id: "registry", title: "레지스트리", uses: ["status"], view: function (scr, d) {
          var r = obj(obj(d.status).registry);
          return h("div", {}, [Kt.para(isNum(r.version) ? "판 v" + r.version + (r.fetched_at ? " · " + md(r.fetched_at) + " 받음" : "") +
            (r.source ? " · 출처 " + (r.source_ko || r.source) : "") : "레지스트리를 아직 받지 못했습니다."),
          isNum(r.projects_n) ? Kt.para("과제 " + r.projects_n + " · 에이전트 " + num(r.agents_n) + (r.calendar_version ? " · 달력 " + r.calendar_version : "")) : null,
          r.note_ko ? Kt.para(r.note_ko) : null,
          h("div", {"class": "table-tools"}, [Kt.btn("지금 받기", "a-reg-fetch", "", {kind: "ghost"})])]);
        }},
        {id: "server", title: "이 PC 를 팀 서버로 쓰기", uses: [], view: function (scr) {
          var open = !!scr.st["open:server"];
          if (!open) { return Kt.muted("팀장 PC(또는 팀 공용 PC)에서만 씁니다. 펼치면 이 PC 의 팀 서버 상태를 읽습니다."); }
          var s = scr.src.local;
          if (!s || s.state === "loading" || s.state === "idle") { return Kt.para("상태를 읽는 중입니다…", "muted"); }
          if (s.state === "err") { return h("div", {}, [U0.alertLine("bad", "팀 서버 상태를 읽지 못했습니다 — " + str(obj(s.err).error)), Kt.btn("다시 읽기", "a-local-reload", "", {kind: "ghost"})]); }
          var L = obj(s.data);
          var ifs = [["0.0.0.0", "모든 인터페이스(0.0.0.0)"]].concat(arr(L.interfaces).map(function (ip) { return [ip, ip]; }));
          return h("div", {}, [
            L.warn_root_ko ? U0.alertLine("warn", L.warn_root_ko) : null,
            L.running ? Kt.para("가동 중" + (L.mine ? "(이 화면이 띄운 서버)" : "") + " · " + arr(L.urls).join(" · ") + " (팀원에게 알릴 주소)") : Kt.para("이 PC 에서 팀 서버가 돌고 있지 않습니다."),
            L.running ? Kt.para("오늘 업로드 " + num(L.uploads_today) + " · 마지막 취합 세대 " + str(L.gen) + " " + str(L.gen_state_ko || L.gen_state) + " · 외부 요청 " + num(L.ext_requests)) : null,
            Kt.field("ts-host", "받는 주소", Kt.select("ts-host", ifs, L.bind_host || "0.0.0.0")),
            Kt.field("ts-port", "포트", Kt.input("ts-port", "number", L.bind_port, {min: "1", max: "65535"})),
            Kt.field("ts-store", "저장소 위치(비우면 기본 위치)", Kt.input("ts-store", "text", L.store_dir || "")),
            Kt.field("ts-name", "서버 이름", Kt.input("ts-name", "text", L.display_name || "")),
            h("div", {"class": "table-tools"}, [Kt.btn("시작", "a-ts-start", "", {kind: "primary", why: L.running ? "이미 가동 중입니다" : null}),
              Kt.btn("중지", "a-ts-stop", "", {kind: "danger", why: L.running && L.mine ? null : "이 화면이 띄운 서버가 아닙니다"}),
              Kt.btn("방화벽 진단", "a-ts-diag", "firewall", {kind: "ghost"}), Kt.btn("포트 진단", "a-ts-diag", "port", {kind: "ghost"}),
              Kt.btn("대시보드 열기", "a-ts-open", "", {kind: "ghost", why: L.running ? null : "서버가 가동 중이 아닙니다"})]),
            scr.st.tsDiag ? U0.alertLine("info", scr.st.tsDiag) : null]);
        }, tools: function (scr) {
          var open = !!scr.st["open:server"];
          return [Kt.btn(open ? "접기" : "펼치기", "a-ts-toggle", "", {kind: "ghost", expanded: open})];
        }}],
      handlers: {
        "a-ping": function (scr) {
          api.post("/api/team/ping", {host: str(val("tm-host")).trim(), port: Number(val("tm-port"))}).then(function (res) {
            var d = obj(res.data);
            scr.st.ping = {ok: res.ok && d.result === "ok", text: res.ok ? str(d.text_ko || d.result) + (isNum(d.ms) ? " (" + d.ms + "ms)" : "") +
              (d.server ? " · " + str(obj(d.server).name) + " 판 " + str(obj(d.server).version) + (obj(d.server).pepper_match === false ? " · pepper 불일치" : "") : "") : res.error};
            rerender(scr, "addr");
          });
        },
        "a-reset-addr": function (scr) {
          send(scr, "addr", "post", "/api/team/settings/reset-address", {}, {reset: true, reload: ["status"], ok: "팀 서버 주소를 기본값으로 되돌렸습니다"});
        },
        "a-token": function (scr) {
          var t = str(val("tm-token"));
          if (!t) { return; }
          scr.st["open:token"] = false;
          send(scr, "addr", "post", "/api/team/token", {token: t}, {reset: true, reload: ["status"], ok: "업로드 토큰을 저장했습니다(화면에 다시 보이지 않습니다)"});
        },
        "a-team-save": function (scr) {
          var alt = str(val("tm-alt")).split(/\r?\n/).map(function (x) { return x.trim(); }).filter(Boolean);
          var errs = {};
          var port = Number(val("tm-port"));
          if (!(port >= 1 && port <= 65535) || Math.floor(port) !== port) { errs.server_port = "포트는 1~65535 정수입니다"; }
          if (!str(val("tm-host")).trim()) { errs.server_host = "IP 를 넣어 주세요"; }
          if (alt.length > 5) { errs.server_alternates = "대체 주소는 5줄까지입니다"; }
          if (Array.from(str(val("tm-label"))).length > 20) { errs.self_label = "라벨은 20자 이하입니다"; }
          scr.st.teamErr = Object.keys(errs).length ? errs : null;
          if (scr.st.teamErr) { rerender(scr, "addr"); return; }
          var body = {server_host: str(val("tm-host")).trim(), server_port: port, server_alternates: alt, self_label: str(val("tm-label")).trim(),
            member_id: val("tm-member") || null, unit_title_mode: val("tm-title") || "label", share_unknown_apps: checked("tm-unknown"), auto_send: checked("tm-auto")};
          api.put("/api/team/settings", body).then(function (res) {
            var c = cardOf(scr, "addr");
            var d = obj(res.data);
            if (res.ok && d.ok !== false) {
              c.msg = {kind: "info", text: "팀 설정을 저장했습니다"};
              scr.st.teamErr = null;
              source(scr, "status", true);
            } else {
              scr.st.teamErr = obj(d.errors);
              c.msg = {kind: "bad", text: res.error || "저장하지 않았습니다 — 칸 아래 이유를 확인하세요"};
            }
            rerender(scr, "addr");
          });
        },
        "a-team-build": function (scr) {
          var c = S.current || {};
          send(scr, "outbox", "post", "/api/team/build", {from: c.from, to: c.to}, {job: "team_build", ok: "팀 묶음을 만듭니다 — 끝나면 미리보기를 엽니다"});
        },
        "a-preview": function (scr, n, id) { openPreview(id); },
        "a-send": function (scr, n, id) { send(scr, "outbox", "post", "/api/team/send/" + encodeURIComponent(id), {}, {job: "team_send", reload: ["status"], ok: "보내기를 요청했습니다"}); },
        "a-drop": function (scr, n, id) { send(scr, "outbox", "post", "/api/team/drop/" + encodeURIComponent(id), {}, {reload: ["status"], ok: "대기열에서 치웠습니다"}); },
        "a-export-item": function (scr, n, id) {
          U0.openDrawer(h("div", {}, [Kt.field("tx-dir", "내보낼 폴더(USB·공유 폴더)", Kt.input("tx-dir", "text", null)),
            h("div", {"class": "table-tools"}, [Kt.btn("내보내기", "a-tx-ok", id, {kind: "primary"}), Kt.btn("취소", "drawer-close", "", {kind: "ghost"})])]),
          {doc: doc, title: "파일로 내보내기", handlers: {"a-tx-ok": function (n2, it) {
            var dir = str(val("tx-dir")).trim();
            U0.closeDrawer();
            send(scr, "outbox", "post", "/api/team/export/" + encodeURIComponent(it), {dir: dir || null}, {reload: ["status"], ok: "파일로 내보냈습니다 — 팀 서버 PC 에서 반입하면 들어갑니다"});
          }}});
        },
        "a-reg-fetch": function (scr) { send(scr, "registry", "post", "/api/team/registry/fetch", {}, {job: "registry_fetch", ok: "레지스트리를 받는 중입니다"}); },
        "a-ts-toggle": function (scr) {
          scr.st["open:server"] = !scr.st["open:server"];
          if (scr.st["open:server"]) { source(scr, "local", true); }
          rerender(scr, "server");
        },
        "a-local-reload": function (scr) { source(scr, "local", true); },
        "a-ts-start": function (scr) {
          var body = {bind_host: val("ts-host"), bind_port: Number(val("ts-port"))};
          if (str(val("ts-store")).trim()) { body.store_dir = str(val("ts-store")).trim(); }
          if (str(val("ts-name")).trim()) { body.display_name = str(val("ts-name")).trim(); }
          send(scr, "server", "post", "/api/teamserver/start", body, {ok: function (d) { return obj(d).text_ko || "팀 서버를 시작했습니다"; },
            after: function () { source(scr, "local", true); }}).then(function (res) {
            if (!res.ok && obj(res.data).diag) { scr.st.tsDiag = str(obj(res.data.diag).text_ko); rerender(scr, "server"); }
          });
        },
        "a-ts-stop": function (scr) { send(scr, "server", "post", "/api/teamserver/stop", {}, {ok: "팀 서버를 멈췄습니다", after: function () { source(scr, "local", true); }}); },
        "a-ts-diag": function (scr, n, kind) {
          api.post("/api/teamserver/diagnose", {kind: kind}).then(function (res) {
            scr.st.tsDiag = res.ok ? str(obj(res.data).text_ko || "진단을 마쳤습니다") : res.error;
            rerender(scr, "server");
          });
        },
        "a-ts-open": function (scr) {
          var L = obj(obj(scr.src.local).data);
          var port = Number(L.bind_port);
          if (port >= 1 && port <= 65535 && win.open) { win.open("http://127.0.0.1:" + port + "/", "_blank", "noopener"); }
        }
      },
      init: function (scr) { if (scr.arg && /^preview\//.test(scr.arg)) { openPreview(scr.arg.slice(8)); } }
    };

    // ── 4.10 설정(§5.6) ──
    function groupOf(item) {
      if (item.group) { return item.group; }
      var k = str(item.key);
      for (var i = 0; i < SET_GROUPS.length; i++) {
        if (SET_GROUPS[i][2].some(function (p) { return k === p || k.indexOf(p) === 0; })) { return SET_GROUPS[i][0]; }
      }
      return "collect";
    }

    function controlFor(item, id) {
      var t = str(item.type);
      var v = item.value;
      var rg = obj(item.range);
      if (item.secret) { return Kt.input(id, "password", null, {autocomplete: "off", placeholder: item.has_value ? "설정됨" : "없음"}); }
      if (t === "bool") { return Kt.checkbox(id, "켜기", !!v); }
      if (t === "int" || t === "float") {
        return Kt.input(id, "number", isNum(v) ? v : "", {min: isNum(rg.min) ? String(rg.min) : null, max: isNum(rg.max) ? String(rg.max) : null,
          step: isNum(rg.step) ? String(rg.step) : (t === "int" ? "1" : "any")});
      }
      if (t === "enum") { return Kt.select(id, arr(item.choices).map(function (c) { return [c, String(c)]; }), v); }
      if (/^list/.test(t)) { return Kt.textarea(id, arr(v).map(function (x) { return typeof x === "object" ? JSON.stringify(x) : String(x); }).join("\n"), {rows: "3"}); }
      if (t === "obj") { return Kt.textarea(id, JSON.stringify(v === undefined ? null : v), {rows: "3", "class": "mono"}); }
      if (t === "timerange") {
        var p = Array.isArray(v) ? v : str(v).split("-");
        return h("span", {}, [Kt.input(id + "-a", "time", p[0] || "", {"aria-label": "시작"}), " ~ ", Kt.input(id + "-b", "time", p[1] || "", {"aria-label": "끝"})]);
      }
      return Kt.input(id, "text", v === null || v === undefined ? "" : String(v));
    }

    function readControl(item, id) {
      var t = str(item.type);
      if (t === "bool") { return {v: checked(id)}; }
      if (t === "int" || t === "float") {
        var x = Number(val(id));
        if (str(val(id)) === "" || !isFinite(x)) { return {err: "수를 넣어 주세요"}; }
        if (t === "int" && Math.floor(x) !== x) { return {err: "정수를 넣어 주세요"}; }
        return {v: x};
      }
      if (/^list/.test(t)) {
        return {v: str(val(id)).split(/\r?\n/).map(function (s) { return s.trim(); }).filter(Boolean).map(function (s) {
          if (/^[{[]/.test(s)) {
            try {
              return JSON.parse(s);
            } catch (e) {
              return s;
            }
          }
          return s;
        })};
      }
      if (t === "obj") {
        try {
          return {v: JSON.parse(str(val(id)))};
        } catch (e) {
          return {err: "JSON 형식이 아닙니다"};
        }
      }
      if (t === "timerange") { return {v: [val(id + "-a"), val(id + "-b")]}; }
      if (item.secret) { var s = str(val(id)); return s ? {v: s} : {skip: true}; }
      return {v: str(val(id))};
    }

    function settingRow(scr, item) {
      var id = "set-" + str(item.key).replace(/[^A-Za-z0-9]/g, "-");
      var err = obj(scr.st.setErr)[item.key];
      var dv = item.secret ? "—" : (typeof item["default"] === "object" ? JSON.stringify(item["default"]) : str(item["default"]));
      return h("tr", {}, [
        h("th", {scope: "row"}, [h("label", {"for": item.type === "timerange" ? id + "-a" : id}, [item.label_ko || item.key]),
          item.help_ko ? h("small", {"class": "muted"}, [" " + item.help_ko]) : null, h("br", {}), h("code", {}, [item.key])]),
        h("td", {}, [controlFor(item, id), err ? Kt.errLine(id, err) : null]),
        h("td", {}, [dv]),
        h("td", {}, [item.uncalibrated ? U0.badge("★ 미보정", null, "실측 근거가 없는 정책값 — 내 자료로 조정 대상") : null,
          item.restart && item.restart !== "none" ? U0.badge("다시 띄워야 반영") : null, item.scope === "team_server" ? U0.badge("팀 서버 PC") : null]),
        h("td", {}, [Kt.btn("저장", "a-set-save", item.key, {kind: "ghost"}), Kt.btn("기본값", "a-set-reset", item.key, {kind: "ghost"})])]);
    }

    function settingsTable(scr, items) {
      if (!items.length) { return Kt.emptyP("이 묶음에는 화면에서 바꿀 설정이 없습니다."); }
      return h("div", {"class": "table-wrap"}, [h("table", {"class": "tbl", "aria-label": "설정"}, [h("thead", {}, [h("tr", {}, ["이름·키", "값", "기본값", "표식", ""].map(function (c) {
        return h("th", {scope: "col"}, [c]);
      }))]), h("tbody", {}, items.map(function (it) { return settingRow(scr, it); }))])]);
    }

    var SETTINGS = {
      sources: {
        settings: function () { return api.get("/api/settings"); },
        audit: function () { return api.get("/api/privacy/audit"); },
        ads: function () { return api.get("/api/privacy/ad-suspects"); },
        calib: function () { return api.get("/api/calibration"); }
      },
      lazy: {audit: true, ads: true, calib: true},
      cards: [
        {id: "groups", title: null, uses: [], view: function (scr) {
          return h("nav", {"class": "pills pills-sm", "aria-label": "설정 묶음"}, SET_GROUPS.map(function (g) {
            return h("a", {"class": "pill", href: "#settings/" + g[0], "aria-current": scr.st.group === g[0] ? "page" : null}, [g[1]]);
          }));
        }},
        {id: "list", title: function (scr) { var g = SET_GROUPS.filter(function (x) { return x[0] === scr.st.group; })[0]; return g ? g[1] : "설정"; },
          uses: ["settings"], when: function (scr) { return scr.st.group !== "calib"; }, view: function (scr, d) {
            var items = listOf(d.settings, "items").filter(function (it) { return groupOf(it) === scr.st.group; });
            var warns = arr(obj(d.settings).config_warnings);
            return h("div", {}, [warns.length ? h("div", {}, warns.map(function (w) { return U0.alertLine("warn", str(obj(w).text_ko || w) + " — 기본값으로 동작 중"); })) : null,
              scr.st.group === "bridge" ? Kt.muted("Copilot 설정은 클라우드PC 에서만 의미가 있습니다.") : null,
              scr.st.group === "team" ? Kt.muted("팀 서버 주소는 팀 화면에서 바꿉니다.") : null,
              settingsTable(scr, items)]);
          }},
        {id: "audit", title: "정제 감사", uses: ["audit"], when: function (scr) { return scr.st.group === "privacy"; }, view: function (scr, d) {
          var rows = listOf(d.audit, "rows").map(function (r) {
            return [str(r.period || r.date), str(r.src), str(r.category_ko || r.category), String(num(r.n))];
          });
          return rows.length ? Kt.table(["기간", "출처", "범주", {label: "건수", num: true}], rows, {label: "정제 감사"}) : Kt.emptyP("정제 감사 기록이 아직 없습니다.");
        }},
        {id: "testbench", title: "정제 시험대", uses: [], when: function (scr) { return scr.st.group === "privacy"; }, view: function (scr) {
          var r = obj(scr.st.bench);
          return h("div", {}, [Kt.field("tb-text", "시험할 글(저장·기록하지 않고 메모리에서만 정제합니다)", Kt.textarea("tb-text", "", {rows: "3"})),
            h("div", {"class": "table-tools"}, [Kt.btn("정제해 보기", "a-bench", "", {kind: "ghost"})]),
            r.after !== undefined ? Kt.field("tb-after", "정제 뒤", Kt.textarea("tb-after", str(r.after), {rows: "3", readonly: true})) : null,
            arr(r.hits).length ? Kt.para("걸린 범주: " + arr(r.hits).map(function (x) { return str(obj(x).cat_ko || obj(x).cat || x) + (isNum(obj(x).n) ? " " + x.n : ""); }).join(" · ")) : null]);
        }},
        {id: "ads", title: "광고 의심 큐", uses: ["ads"], when: function (scr) { return scr.st.group === "privacy"; }, view: function (scr, d) {
          var rows = listOf(d.ads, "items").map(function (a) {
            return [str(a.title), String(num(a.n)), h("span", {}, [Kt.btn("차단", "a-ad", a.id + "|block", {kind: "ghost"}), Kt.btn("허용", "a-ad", a.id + "|allow", {kind: "ghost"})])];
          });
          return rows.length ? Kt.table(["정제 제목", {label: "건수", num: true}, "처리"], rows) : Kt.emptyP("판단을 기다리는 광고 의심이 없습니다.");
        }},
        {id: "calib", title: "보정", uses: ["calib"], when: function (scr) { return scr.st.group === "calib"; }, view: function (scr, d) {
          var rows = listOf(d.calib, "rows").map(function (r) {
            var ap = obj(obj(d.calib).applied)[r.key];
            return [h("code", {}, [str(r.key)]), str(r.current), str(r.candidate), isNum(r.J) ? U0.fmtNum(r.J, 3) : str(r.J), str(r.env_h_delta_text || r.env_h_delta),
              str(r.grade_shift_text || r.grade_shift), String(num(r.days)),
              ap ? U0.badge("보정됨(" + str(obj(ap).date) + ")") : Kt.btn("적용", "a-calib", r.key, {kind: "ghost"})];
          });
          return rows.length ? h("div", {}, [Kt.table(["키", "현재값", "후보값", {label: "J", num: true}, "봉투 h 변화", "등급 분포 변화", {label: "표본 날", num: true}, ""], rows),
            Kt.muted("[적용]을 누를 때만 바뀝니다(자동 적용 없음).")]) : Kt.emptyP("보정 보고가 아직 없습니다.");
        }},
        {id: "shutdown", title: "화면 서버", uses: [], view: function () {
          return h("div", {}, [Kt.para("화면 서버는 [서버 종료]를 누르거나 [이동 준비]를 할 때까지 켜져 있습니다."),
            h("div", {"class": "table-tools"}, [Kt.btn("서버 종료", "a-shutdown", "", {kind: "danger"})])]);
        }}],
      handlers: {
        "a-set-save": function (scr, n, key) {
          var items = listOf(obj(obj(scr.src.settings).data), "items");
          var it = items.filter(function (x) { return x.key === key; })[0];
          if (!it) { return; }
          var id = "set-" + str(key).replace(/[^A-Za-z0-9]/g, "-");
          var r = readControl(it, id);
          scr.st.setErr = obj(scr.st.setErr);
          if (r.skip) { return; }
          if (r.err) { scr.st.setErr[key] = r.err; rerender(scr, "list"); return; }
          var body = {};
          body[key] = r.v;
          api.put("/api/settings", body).then(function (res) {
            var c = cardOf(scr, "list");
            var d = obj(res.data);
            var errs = obj(d.errors);
            if (res.ok && !errs[key] && d.ok !== false) {
              delete scr.st.setErr[key];
              c.msg = {kind: "info", text: (it.label_ko || key) + " 를 저장했습니다" + (it.restart && it.restart !== "none" ? " — 다시 띄우면 반영됩니다" : "")};
              source(scr, "settings", true);
            } else {
              scr.st.setErr[key] = str(errs[key] || res.error || "저장하지 않았습니다");
              c.msg = null;
            }
            rerender(scr, "list");
          });
        },
        "a-set-reset": function (scr, n, key) {
          send(scr, "list", "post", "/api/settings/reset", {key: key}, {reload: ["settings"], ok: "기본값으로 되돌렸습니다"});
        },
        "a-bench": function (scr) {
          var text = str(val("tb-text"));
          if (!text) { return; }
          api.post("/api/privacy/testbench", {text: text}).then(function (res) {
            scr.st.bench = res.ok ? obj(res.data) : {after: "", hits: []};
            cardOf(scr, "testbench").msg = res.ok ? null : {kind: "bad", text: res.error};
            rerender(scr, "testbench");
          });
        },
        "a-ad": function (scr, n, ref) {
          var p = str(ref).split("|");
          send(scr, "ads", "post", "/api/privacy/ad-decision", {id: p[0], decision: p[1]}, {reload: ["ads"], ok: p[1] === "block" ? "차단 목록에 넣었습니다" : "허용했습니다"});
        },
        "a-calib": function (scr, n, key) { send(scr, "calib", "post", "/api/calibration/apply", {key: key}, {reload: ["calib", "settings"], ok: "보정값을 적용했습니다 — 다음 분석부터 반영됩니다"}); },
        "a-shutdown": function (scr) {
          U0.openDrawer(h("div", {}, [Kt.para("화면 서버를 끝냅니다. 다시 열려면 LoadMonitor27-UI 를 누르세요."),
            h("div", {"class": "table-tools"}, [Kt.btn("서버 종료", "a-shutdown-ok", "", {kind: "danger"}), Kt.btn("취소", "drawer-close", "", {kind: "ghost"})])]),
          {doc: doc, title: "서버 종료", handlers: {"a-shutdown-ok": function () {
            U0.closeDrawer();
            send(scr, "shutdown", "post", "/api/shutdown", {}, {ok: "화면 서버를 끝냈습니다 — 다시 열려면 LoadMonitor27-UI 를 누르세요"});
          }}});
        }
      },
      init: function (scr) {
        var g = str(scr.arg).split("/")[0];
        scr.st.group = SET_GROUPS.some(function (x) { return x[0] === g; }) ? g : "work";
        scr.onArg = function (arg) {
          var g2 = str(arg).split("/")[0];
          scr.st.group = SET_GROUPS.some(function (x) { return x[0] === g2; }) ? g2 : "work";
          if (scr.st.group === "privacy") { source(scr, "audit"); source(scr, "ads"); }
          if (scr.st.group === "calib") { source(scr, "calib"); }
          rerender(scr);
        };
        if (scr.st.group === "privacy") { scr.st.lazyLoad = ["audit", "ads"]; }
        if (scr.st.group === "calib") { scr.st.lazyLoad = ["calib"]; }
      }
    };

    var SCREEN_DEF = {home: HOME, collect: COLLECT, analysis: ANALYSIS, report: {custom: reportScreen}, team: TEAM, settings: SETTINGS};

    // ── 4.11 라우터 ──
    function route() {
      var hs = str(win.location ? win.location.hash : "").replace(/^#/, "");
      var name = hs.split("/")[0] || "home";
      var arg = hs.indexOf("/") >= 0 ? hs.slice(hs.indexOf("/") + 1) : null;
      if (!SCREEN_DEF[name]) { name = "home"; arg = null; }
      var changed = !S.scr || S.scr.name !== name;
      openScreen(name, arg, false);
      if (S.scr && S.scr.st.lazyLoad) {
        S.scr.st.lazyLoad.forEach(function (k) { source(S.scr, k); });
        S.scr.st.lazyLoad = null;
      }
      renderNav();
      if (changed && S.booted && el.main.focus) { el.main.focus(); }
    }

    // ── 4.12 머리 위임 ──
    var headOff = null;
    var headHandlers = {
      "a-jobs": function () {
        api.get("/api/jobs").then(function (res) {
          listOf(res.data, "jobs").forEach(function (j) {
            if (!j.job_id) { return; }
            if (!S.jobs[j.job_id]) {
              S.jobs[j.job_id] = {job_id: j.job_id, kind: j.kind, state: j.state, events: arr(j.events), seq: 0, ctx: {}, done: !!FINISHED[j.state]};
              S.jobOrder.unshift(j.job_id);
            }
          });
          jobsDrawer();
        });
      },
      "a-dismiss": function (n, id) {
        S.notices = S.notices.filter(function (x) { return x.id !== id; });
        renderAlerts();
      }
    };
    var headRoot = el.head || (el.jobs && el.jobs.parentNode) || null;
    if (headRoot) { headOff = U0.delegate(headRoot, headHandlers); }
    var alertOff = el.alerts && el.alerts !== headRoot ? U0.delegate(el.alerts, {"a-dismiss": headHandlers["a-dismiss"]}) : null;

    // ── 4.13 시작 ──
    U0.ensureDefs(doc, deps().C);
    renderNav();
    renderAlerts();
    if (win.addEventListener) { win.addEventListener("hashchange", route); }
    var ready = Promise.all([
      api.get("/api/hello").then(function (res) {
        if (res.ok) {
          S.hello = obj(res.data);
          if (isNum(S.hello.job_poll_ms) && S.hello.job_poll_ms >= 200) { S.pollMs = S.hello.job_poll_ms; }
        }
        renderHead();
      }),
      api.get("/api/jobs").then(function (res) {
        listOf(res.data, "jobs").forEach(function (j) {
          if (j.job_id && !FINISHED[j.state]) { track(j.job_id, j.kind, {}); }
        });
      }),
      refreshGlobal()
    ]).then(function () {
      if (S.scr && S.scr.onGlobal) { S.scr.onGlobal(); }
    });
    route();
    S.booted = true;

    return {
      state: S,
      api: api,
      route: route,
      ready: ready,
      poll: pollOnce,
      track: track,
      open: openScreen,
      destroy: function () {
        closeScreen();
        if (headOff) { headOff(); }
        if (alertOff) { alertOff(); }
        if (win.removeEventListener) { win.removeEventListener("hashchange", route); }
        if (S.pollTimer !== null) { timer.clear(S.pollTimer); S.pollTimer = null; }
      }
    };
  }

  function autoBoot(win) {
    var doc = win && win.document;
    if (!doc || !doc.getElementById) { return; }
    function run() { if (doc.getElementById("app") && doc.getElementById("lm27-nav")) { boot({doc: doc, win: win}); } }
    if (doc.readyState === "loading" && doc.addEventListener) { doc.addEventListener("DOMContentLoaded", run); } else { run(); }
  }

  return {boot: boot, autoBoot: autoBoot, makeApi: makeApi, readToken: readToken, parseApi: parseApi, SCREENS: SCREENS, JOB_NAME: JOB_NAME};
}));
