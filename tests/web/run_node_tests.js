/*
 * LM27 웹 시험 러너(개발 PC 전용 — 실행 환경에는 node 가 필요 없다, REPORTS §2.2 · 계약 §2.19).
 *   node tests\web\run_node_tests.js [--update-golden] [이름 거르개]
 * tests\web\*_test.js 를 이름순으로 모두 불러 각 파일의 등록 함수 module.exports(t) 를 부르고, 등록된 시험을 차례로 돌린다.
 * 시험 파일 형식: module.exports = function (t) { t.test("이름", function (ctx) { ... }); };
 *   ctx = {assert, root, fixtures(이 WP 자료 폴더 경로 함수), python(동봉 파이썬 경로 또는 null), update(골든 갱신), tmpdir(), skip(이유)}
 * 시험 함수가 Promise(thenable)를 돌려주면 끝날 때까지 기다린다(시험 하나 상한 TEST_TIMEOUT_MS).
 * 한 파일을 불러오다(문법 오류 등) 실패하면 그 파일만 실패 1건으로 세고 다른 파일은 계속 돈다(W2 통합 — WP-36 CR).
 * 시험은 트리를 읽기만 한다. 쓰기는 os.tmpdir() 아래 lm27w_* 폴더에만(끝나면 지운다). 종료 코드 = 실패가 있으면 1.
 */
"use strict";
var fs = require("fs");
var os = require("os");
var path = require("path");
var assert = require("assert");

var ROOT = path.resolve(__dirname, "..", "..");
var argv = process.argv.slice(2);
var UPDATE = argv.indexOf("--update-golden") >= 0;
var FILTER = argv.filter(function (a) { return a.charAt(0) !== "-"; })[0] || null;
var TEST_TIMEOUT_MS = 60000;
var made = [];

// 동봉 파이썬: 트리 안 python\ → 복제 표지(.lm27t_clone 의 src=)가 가리키는 원본의 python\ → LM27T_PY_HOME → 없음
function findPython() {
  var cands = [path.join(ROOT, "python", "python.exe")];
  try {
    var mark = fs.readFileSync(path.join(ROOT, ".lm27t_clone"), "utf8");
    var m = /^src=(.+)$/m.exec(mark);
    if (m) { cands.push(path.join(m[1].trim(), "python", "python.exe")); }
  } catch (e) {
    if (e.code !== "ENOENT") { throw e; }
  }
  if (process.env.LM27T_PY_HOME) { cands.push(path.join(process.env.LM27T_PY_HOME, "python.exe")); }
  for (var i = 0; i < cands.length; i++) { if (fs.existsSync(cands[i])) { return cands[i]; } }
  return null;
}

function SkipError(why) { this.why = why; }

var ctx = {
  assert: assert,
  root: ROOT,
  update: UPDATE,
  python: findPython(),
  fixtures: function () { return path.join.apply(path, [ROOT, "tests", "fixtures", "wp28"].concat([].slice.call(arguments))); },
  tmpdir: function () {
    var d = fs.mkdtempSync(path.join(os.tmpdir(), "lm27w_"));
    made.push(d);
    return d;
  },
  skip: function (why) { throw new SkipError(why); }
};

var pass = 0;
var fail = 0;
var skip = 0;

function report(e, label) {
  if (e instanceof SkipError) {
    skip++;
    console.log("ok - " + label + " # 건너뜀: " + e.why);
    return;
  }
  fail++;
  console.log("not ok - " + label);
  console.log("  " + String((e && e.stack) || e).split("\n").slice(0, 6).join("\n  "));
}

var tests = [];
var files = fs.readdirSync(__dirname).filter(function (n) { return /_test\.js$/.test(n); }).sort();
files.forEach(function (f) {
  try {
    var reg = require(path.join(__dirname, f));
    if (typeof reg !== "function") { throw new Error(f + ": module.exports 가 등록 함수가 아닙니다"); }
    reg({test: function (name, fn) { tests.push({file: f, name: name, fn: fn}); }});
  } catch (e) {
    report(e, f + " › (불러오기)");            // 그 파일만 실패 — 나머지 파일은 계속 돈다
  }
});

function withTimeout(p, label) {
  var timer = null;
  var limit = new Promise(function (_res, rej) {
    timer = setTimeout(function () { rej(new Error(label + ": " + TEST_TIMEOUT_MS + "ms 안에 끝나지 않았습니다")); },
      TEST_TIMEOUT_MS);
  });
  return Promise.race([p, limit]).then(function (v) { clearTimeout(timer); return v; },
    function (e) { clearTimeout(timer); throw e; });
}

function runOne(t) {
  var label = t.file + " › " + t.name;
  if (FILTER && label.indexOf(FILTER) < 0) { return Promise.resolve(); }
  var r;
  try {
    r = t.fn(ctx);
  } catch (e) {
    report(e, label);
    return Promise.resolve();
  }
  if (!r || typeof r.then !== "function") {
    pass++;
    console.log("ok - " + label);
    return Promise.resolve();
  }
  return withTimeout(Promise.resolve(r), label).then(function () {
    pass++;
    console.log("ok - " + label);
  }, function (e) { report(e, label); });
}

function cleanup() {
  made.forEach(function (d) {
    if (path.basename(d).indexOf("lm27w_") === 0 && path.dirname(d) === os.tmpdir()) {
      try { fs.rmSync(d, {recursive: true, force: true}); } catch (e) { console.log("# 임시 폴더를 지우지 못함: " + d); }
    }
  });
}

tests.reduce(function (chain, t) { return chain.then(function () { return runOne(t); }); }, Promise.resolve())
  .then(function () {
    cleanup();
    console.log("# 웹 시험: 통과 " + pass + " · 실패 " + fail + " · 건너뜀 " + skip + (UPDATE ? " (골든 갱신)" : ""));
    process.exitCode = fail ? 1 : 0;
  }, function (e) {
    cleanup();
    console.log("not ok - 러너 내부 오류: " + String((e && e.stack) || e).split("\n")[0]);
    process.exitCode = 1;
  });
