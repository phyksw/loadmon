"""Real PAGE + full HTTP handler + headless browser, with synthetic files only.

The optional browser check requires Node, Playwright and a local Chromium browser.
No app.main(), collector, account, user profile, scheduler or upload is invoked.
Run this file with --serve <marked TEMP fixture> to inspect the isolated server.
"""
import csv
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


PROJECT = Path(__file__).resolve().parents[1]
APP = PROJECT / "LoadMonitor25"
TAG = "20260101-20260131"
PERIOD = ["2026-01-01", "2026-01-31"]
MARKER = ".lm25-integration-fixture"


def fixture(root):
    """Copy executable source and defaults, never personal data/config/profiles."""
    root = Path(root).resolve()
    temp = Path(tempfile.gettempdir()).resolve()
    if not root.is_relative_to(temp):
        raise ValueError("Integration fixtures must be under the system TEMP directory")
    root.mkdir(parents=True, exist_ok=True)
    (root / MARKER).write_text("synthetic only", encoding="utf-8")
    paths = list(APP.glob("*.py"))
    for directory in ("core", "ui", "tools", "collect"):
        paths.extend((APP / directory).rglob("*.py"))
    for path in paths:
        target = root / path.relative_to(APP)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    (root / "config").mkdir(exist_ok=True)
    (root / "data").mkdir(exist_ok=True)
    (root / "report").mkdir(exist_ok=True)
    cfg = json.loads((APP / "config/config.default.json").read_text(encoding="utf-8-sig"))
    cfg.update(owner="Synthetic Integration", watchFolders=[], teamServerUrl="", teamShareDir="",
               autoRestartSampler=False, teamUpload={"auto": False})
    (root / "config/config.json").write_text(json.dumps(cfg), encoding="utf-8")
    write_csv(root / "data/outlook/mail.csv", [
        {"time": "2026-01-05 10:00", "subject": "Synthetic January", "from": "synthetic@example.invalid",
         "to": "self@example.invalid", "direction": "sent"},
        {"time": "2026-09-02 10:00", "subject": "Synthetic September", "from": "synthetic@example.invalid",
         "to": "self@example.invalid", "direction": "sent"}])
    write_csv(root / "data/files/files.csv", [
        {"mtime": "2026-01-05 11:00", "name": "synthetic.docx", "ext": ".docx",
         "folder": str(root / "synthetic-documents"), "author": "Synthetic Integration"}])
    return root


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def serve(root):
    from http.server import ThreadingHTTPServer
    import secrets
    from types import SimpleNamespace
    from urllib.parse import urlsplit

    root = Path(root).resolve()
    if not root.is_relative_to(Path(tempfile.gettempdir()).resolve()) or not (root / MARKER).is_file():
        raise ValueError("Refusing to serve a non-synthetic installation")
    spec = importlib.util.spec_from_file_location("isolated_full_lm25_app", root / "ui/app.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module._sampler_task_exists = lambda: None
    module._sampler_autorestart = lambda age: "integration harness: disabled"

    def forbidden(*args, **kwargs):
        raise AssertionError("This integration fixture must not launch collectors or system tools")

    module.subprocess = SimpleNamespace(**vars(subprocess))
    module.subprocess.run = module.subprocess.Popen = forbidden
    allowed = {"/", "/index.html", "/api/dash", "/api/status", "/api/projects", "/api/teamupload",
               "/api/activity", "/favicon.ico"}

    class ReadOnlyHandler(module.H):
        def do_GET(self):
            if urlsplit(self.path).path not in allowed:
                self._send(403, {"error": "integration read-only allowlist"})
                return
            if self.path == "/api/dash" and (root / ".dash-http-503").is_file():
                # Explicit transport fault; /api/activity still uses the real handler.
                self._send(503, {"error": "synthetic analysis endpoint unavailable"})
                return
            super().do_GET()

        def do_POST(self):
            self._send(403, {"error": "integration mutations disabled"})

        do_DELETE = do_POST

    # This host can allocate low ephemeral ports rejected by Chromium (e.g. 3659).
    # Bind a high port directly; never weaken the browser's unsafe-port policy.
    for _ in range(64):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", 40000 + secrets.randbelow(20000)), ReadOnlyHandler)
            break
        except OSError:
            continue
    else:
        raise RuntimeError("Could not allocate a browser-safe loopback port")
    module.PORT[0] = server.server_port
    print(f"http://127.0.0.1:{server.server_port}", flush=True)
    server.serve_forever()


def browser_dependencies():
    node = shutil.which("node")
    candidates = [Path(os.environ["LM_PLAYWRIGHT_MODULE"])] if os.environ.get("LM_PLAYWRIGHT_MODULE") else []
    candidates.extend([
        PROJECT / "node_modules/playwright",
        Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright"])
    playwright = next((p for p in candidates if (p / "package.json").is_file()), None)
    browsers = [os.environ.get("LM_BROWSER_EXE", "")]
    for location in (os.environ.get("PROGRAMFILES(X86)", ""), os.environ.get("PROGRAMFILES", "")):
        if location:
            browsers.extend([str(Path(location) / "Microsoft/Edge/Application/msedge.exe"),
                             str(Path(location) / "Google/Chrome/Application/chrome.exe")])
    browser = next((p for p in browsers if p and Path(p).is_file()), None)
    if not node or not playwright or not browser:
        raise unittest.SkipTest("Real browser integration needs Node, Playwright and Chromium; set LM_PLAYWRIGHT_MODULE/LM_BROWSER_EXE")
    return node, str(playwright), browser


BROWSER_PROBE = r"""
const {chromium}=require(process.env.LM_PLAYWRIGHT_MODULE);
(async()=>{
 const browser=await chromium.launch({executablePath:process.env.LM_BROWSER_EXE,headless:true,
   args:['--disable-background-networking','--no-first-run']});
 try{
  const context=await browser.newContext({viewport:{width:1440,height:1000}});
  const errors=[],requests=[],blocked=[];
  const base=process.env.LM_FIXTURE_URL;
  await context.route('**/*',route=>{
   if(route.request().url().startsWith(base+'/'))return route.continue();
   blocked.push(route.request().url());return route.abort();
  });
  const page=await context.newPage();
  page.on('pageerror',error=>errors.push(String(error)));
  page.on('request',request=>requests.push(new URL(request.url()).pathname+new URL(request.url()).search));
  const failedDash=new Promise(resolve=>page.on('requestfailed',request=>{
   if(request.url()===base+'/api/dash')resolve({error:request.failure()?.errorText||'request failed'});
  }));
  const dashResponse=Promise.race([
   page.waitForResponse(response=>response.url()===base+'/api/dash',{timeout:10000})
    .then(response=>({response})).catch(error=>({error:String(error)})),failedDash]);
  const activityResponse=page.waitForResponse(response=>response.url().startsWith(base+'/api/activity'),
   {timeout:5000}).catch(()=>null);
  await page.goto(base+'/',{waitUntil:'domcontentloaded'});
  const dashResult=await dashResponse,response=dashResult.response;
  let dash;
  try{dash=response?await response.json():{parse_error:dashResult.error};}
  catch(error){dash={parse_error:String(error)};}
  // An analysis table can render before the independent initial activity response.
  // Observe its actual completion before recording the selected period and totals.
  if(await activityResponse)await page.waitForFunction(()=>{
   const status=document.querySelector('#activitystatus')?.textContent||'';
   return status.includes('조회 완료')||status.includes('조회 실패');
  },null,{timeout:5000}).catch(()=>{});
  // Wait for the actual rendered table, not an arbitrary delay after a fetch.
  // A broken page is still captured below so the assertion includes its real error.
  await page.locator('#wcounts table').waitFor({state:'attached',timeout:5000}).catch(()=>{});
  const read=()=>page.evaluate(()=>{
   const table=document.querySelector('#wcounts table');
   const headers=table?Array.from(table.querySelectorAll('tr:first-child th')).map(x=>x.textContent):[];
   const totals={};
   for(const label of ['파일','메일','집계 합계']){
    const index=headers.indexOf(label);
    totals[label]=index<0?null:Array.from(table.querySelectorAll('tr')).slice(1).reduce((sum,row)=>{
     const text=row.querySelectorAll('td')[index]?.textContent||'0';
     return sum+(Number(text.replace(/,/g,''))||0);
    },0);
   }
   return {
    tableRows:document.querySelectorAll('#wcounts tbody tr,#wcounts > table > tr').length,
    tableText:document.querySelector('#wcounts')?.textContent,
    weeklyText:document.querySelector('#weekly')?.textContent,
    chartPresent:!!document.querySelector('#weekly svg'),
    title:document.querySelector('#wtitle')?.textContent,
    period:document.querySelector('#wsub')?.textContent,
    countDetailsOpen:document.querySelector('#wcounts')?.closest('details')?.open,
    activityFrom:document.querySelector('#activityfrom')?.value,
    activityTo:document.querySelector('#activityto')?.value,
    activityStatus:document.querySelector('#activitystatus')?.textContent,
    analysisStatus:document.querySelector('#analysisstatus')?.textContent,
    kpiMm:document.querySelector('#k_mm')?.textContent,
    kpiLoad:document.querySelector('#k_load')?.textContent,
    mainFrom:document.querySelector('#from')?.value,
    mainTo:document.querySelector('#to')?.value,
    pageStatus:document.querySelector('#state')?.textContent, totals
   };
  });
  const initial=await read();
  if(process.env.LM_PROBE_MAIN_PERIOD==='1'){
   await page.locator('#from').fill('2026-09-01');await page.locator('#from').dispatchEvent('change');
   await page.locator('#to').fill('2026-09-13');await page.locator('#to').dispatchEvent('change');
   await page.waitForFunction(()=>{
    const text=document.querySelector('#wsub')?.textContent||'';
    return text.includes('2026-09-01')&&text.includes('2026-09-13');
   },null,{timeout:5000}).catch(()=>{});
  }
  if(process.env.LM_PROBE_MAIN_PERIOD==='chip'){
   await page.locator('[data-d="30"]').click();
   await page.waitForFunction(()=>{
    const text=document.querySelector('#wsub')?.textContent||'';
    return text.includes(document.querySelector('#from').value)
      &&text.includes(document.querySelector('#to').value)
      &&(document.querySelector('#activitystatus')?.textContent||'').includes('조회 완료');
   },null,{timeout:5000}).catch(()=>{});
  }
  const selected=await read();
  console.log(JSON.stringify({errors,requests,blocked,dashStatus:response?.status()||null,dash,initial,selected}));
 }finally{await browser.close();}
})().catch(error=>{console.error(error.stack);process.exit(1);});
"""


class ActivityDashboardIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.node, self.playwright, self.browser = browser_dependencies()
        self.temp = tempfile.TemporaryDirectory(prefix="lm25-page-integration-")
        self.addCleanup(self.temp.cleanup)
        self.root = fixture(Path(self.temp.name) / "app")

    def saved_result(self, meta=None, last_run=None):
        write_csv(self.root / f"report/mm_rows_{TAG}.csv", [
            {"Level 1": "Synthetic", "Level 2": "Synthetic", "Level 3": "Synthetic duty",
             "mm": "1.0", "share": "1.0", "활동": "문서"}])
        write_csv(self.root / f"report/signals_{TAG}.csv", [
            {"time": "2026-01-05 10:00", "source": "메일", "text": "Synthetic", "weight": "1"}])
        metadata = {"period": PERIOD, "total_mm": 1.0, "avail_mm": 1.0}
        metadata.update(meta or {})
        (self.root / f"report/mm_meta_{TAG}.json").write_text(json.dumps(metadata), encoding="utf-8")
        if last_run is not None:
            (self.root / "report/last_run.json").write_text(json.dumps(last_run), encoding="utf-8")

    def probe(self, main_period=False, browser_probe=BROWSER_PROBE):
        process = subprocess.Popen([sys.executable, "-B", str(Path(__file__).resolve()), "--serve", str(self.root)],
                                   cwd=self.root, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, encoding="utf-8", env=dict(os.environ, PYTHONIOENCODING="utf-8"),
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            url = process.stdout.readline().strip()
            self.assertTrue(url.startswith("http://127.0.0.1:"),
                            "Isolated server did not start: " + (url or process.stderr.read()))
            env = dict(os.environ, LM_PLAYWRIGHT_MODULE=self.playwright, LM_BROWSER_EXE=self.browser,
                       LM_FIXTURE_URL=url,
                       LM_PROBE_MAIN_PERIOD="chip" if main_period == "chip" else "1" if main_period else "0")
            result = subprocess.run([self.node, "-"], input=browser_probe, capture_output=True,
                                    text=True, encoding="utf-8", env=env, cwd=self.root, timeout=45,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout.strip().splitlines()[-1])
        finally:
            process.terminate()
            process.communicate(timeout=10)

    def assert_activity_visible(self, result):
        summary = self.evidence(result)
        self.assertEqual(result["blocked"], [], result["blocked"])
        self.assertGreater(result["initial"]["tableRows"], 1, summary)
        self.assertTrue(result["initial"]["chartPresent"], summary)
        self.assertTrue(any(url.startswith("/api/activity?") for url in result["requests"]), summary)
        self.assertIn(result["initial"]["mainFrom"], result["initial"]["period"], summary)
        self.assertIn(result["initial"]["mainTo"], result["initial"]["period"], summary)

    @staticmethod
    def evidence(result):
        def visible(state):
            return {key: value for key, value in state.items() if key not in {"tableText", "weeklyText"}}

        return json.dumps({"errors": result["errors"], "requests": result["requests"],
                           "dashStatus": result["dashStatus"],
                           "dashParseError": result["dash"].get("parse_error"),
                           "dashCounted": (result["dash"].get("trend_info") or {}).get("counted"),
                           "initial": visible(result["initial"]), "selected": visible(result["selected"])})

    def test_collected_files_without_any_analysis_render_activity(self):
        self.assert_activity_visible(self.probe())

    def test_string_mm_in_old_metadata_does_not_hide_collected_activity(self):
        self.saved_result({"total_mm": "1.0", "avail_mm": "1.0"})
        result = self.probe()
        self.assert_activity_visible(result)
        self.assertEqual(result["initial"]["kpiLoad"], "100%", self.evidence(result))

    def test_malformed_stage_list_does_not_hide_collected_activity(self):
        self.saved_result(last_run={"period": PERIOD, "stages": {"AI 판정": "failed"}})
        self.assert_activity_visible(self.probe())

    def test_nonfinite_old_metadata_does_not_hide_collected_activity(self):
        self.saved_result({"total_mm": float("nan")})
        result = self.probe()
        self.assert_activity_visible(result)
        self.assertNotIn("parse_error", result["dash"], self.evidence(result))
        self.assertIn("미확인", result["initial"]["kpiMm"], self.evidence(result))
        self.assertEqual(result["initial"]["kpiLoad"], "–", self.evidence(result))

    def test_broken_numeric_csv_does_not_hide_collected_activity(self):
        self.saved_result()
        write_csv(self.root / f"report/mm_rows_{TAG}.csv", [
            {"Level 1": "Synthetic", "Level 2": "Synthetic", "Level 3": str(index),
             "mm": value, "share": value, "활동": "문서"}
            for index, value in enumerate(["broken", "NaN", "Infinity", "-Infinity"])])
        result = self.probe()
        self.assert_activity_visible(result)
        self.assertNotIn("parse_error", result["dash"], self.evidence(result))
        self.assertEqual(result["dash"]["total"], 0)

    def test_malformed_outlook_skip_does_not_hide_existing_file_activity(self):
        (self.root / "data/outlook/mail.csv").unlink()
        (self.root / "data/outlook/outlook_skip.json").write_text("[]", encoding="utf-8")
        result = self.probe()
        self.assert_activity_visible(result)

    def test_analysis_http_failure_does_not_hide_activity_or_its_error(self):
        (self.root / ".dash-http-503").touch()
        result = self.probe()
        self.assert_activity_visible(result)
        self.assertEqual(result["dashStatus"], 503)
        self.assertIn("HTTP 503", result["initial"]["analysisStatus"], self.evidence(result))
        self.assertEqual(result["initial"]["pageStatus"].replace(" ", ""), "대기중", self.evidence(result))

    def test_selected_main_period_changes_observation_totals_without_analysis(self):
        self.saved_result()
        result = self.probe(main_period=True)
        self.assertIn("2026-09-01", result["selected"]["period"], self.evidence(result))
        self.assertIn("2026-09-13", result["selected"]["period"], self.evidence(result))
        self.assertTrue(any(url.startswith("/api/activity?") for url in result["requests"]), result["requests"])
        self.assertEqual(result["selected"]["totals"], {"파일": 0, "메일": 1, "집계 합계": 1}, self.evidence(result))
        self.assertFalse(any(url.startswith("/api/run") for url in result["requests"]), result["requests"])

    def test_observation_count_table_is_open_on_first_page_load(self):
        result = self.probe()
        self.assert_activity_visible(result)
        self.assertTrue(result["initial"]["countDetailsOpen"], self.evidence(result))

    def test_main_period_chip_changes_activity_without_analysis(self):
        self.saved_result()
        result = self.probe(main_period="chip")
        selected = result["selected"]
        self.assertNotEqual(result["initial"]["mainFrom"], selected["mainFrom"], self.evidence(result))
        self.assertIn(selected["mainFrom"], selected["period"], self.evidence(result))
        self.assertIn(selected["mainTo"], selected["period"], self.evidence(result))
        self.assertFalse(any(url.startswith("/api/run") for url in result["requests"]), result["requests"])

    def test_peak_axis_toggle_preserves_raw_counts_and_reveals_small_month(self):
        (self.root / "data/outlook/mail.csv").unlink()
        write_csv(self.root / "data/files/files.csv", [
            {"mtime": stamp, "name": f"{month}_{index:05}.docx", "ext": ".docx",
             "folder": str(self.root / "synthetic-documents"), "author": "Synthetic Integration"}
            for month, stamp, count in (("january", "2026-01-05 11:00", 13200),
                                        ("september", "2026-09-02 11:00", 100))
            for index in range(count)])
        browser_probe = r"""
const {chromium}=require(process.env.LM_PLAYWRIGHT_MODULE);
(async()=>{
 const browser=await chromium.launch({executablePath:process.env.LM_BROWSER_EXE,headless:true,
  args:['--disable-background-networking','--no-first-run']});
 try{
  const context=await browser.newContext({viewport:{width:1440,height:1000}});
  const base=process.env.LM_FIXTURE_URL,blocked=[],errors=[],requests=[];
  await context.route('**/*',route=>{
   if(route.request().url().startsWith(base+'/'))return route.continue();
   blocked.push(route.request().url());return route.abort();
  });
  const page=await context.newPage();
  page.on('pageerror',error=>errors.push(String(error)));
  page.on('request',request=>requests.push(new URL(request.url()).pathname));
  await page.goto(base+'/',{waitUntil:'domcontentloaded'});
  await page.waitForFunction(()=>(document.querySelector('#activitystatus')?.textContent||'').includes('조회 완료'));
  await page.locator('#from').fill('2026-01-01');
  await page.locator('#to').fill('2026-09-13');
  const response=page.waitForResponse(r=>r.url()===base+'/api/activity?from=2026-01-01&to=2026-09-13');
  await page.locator('#to').dispatchEvent('change');
  const raw=await (await response).json();
  await page.waitForFunction(()=>{
   const text=document.querySelector('#wsub')?.textContent||'';
   return text.includes('2026-01-01')&&text.includes('2026-09-13')
    &&(document.querySelector('#activitystatus')?.textContent||'').includes('조회 완료');
  });
  const read=()=>page.evaluate(()=>{
   const bar=count=>Array.from(document.querySelectorAll('#weekly rect')).find(element=>
    element.querySelector('title')?.textContent.endsWith('파일 '+count+'건'));
   const small=bar(100),large=bar(13200),table=document.querySelector('#wcounts table');
   const headers=Array.from(table.querySelectorAll('tr:first-child th')).map(e=>e.textContent);
   const column=label=>Array.from(table.querySelectorAll('tr')).slice(1).reduce((sum,row)=>
    sum+Number(row.querySelectorAll('td')[headers.indexOf(label)].textContent.replace(/,/g,'')),0);
   return {checked:document.querySelector('#activityscale').checked,
    smallHeight:Number(small?.getAttribute('height')),smallPixels:small?.getBoundingClientRect().height,
    largeHeight:Number(large?.getAttribute('height')),largeTitle:large?.querySelector('title').textContent,
    axisNote:document.querySelector('#wscale').textContent,
    peakLabels:Array.from(document.querySelectorAll('#weekly text')).map(e=>e.textContent).filter(t=>t.startsWith('▲')),
    tableText:table.textContent,files:column('파일'),total:column('집계 합계')};
  });
  const compressed=await read();
  await page.locator('#activityscale').uncheck();
  const linear=await read();
  console.log(JSON.stringify({blocked,errors,requests,rawCount:raw.trend_info.counted,
   rawFiles:raw.trend.reduce((sum,row)=>sum+row.counts['파일'],0),compressed,linear}));
 }finally{await browser.close();}
})().catch(error=>{console.error(error.stack);process.exit(1);});
"""
        result = self.probe(browser_probe=browser_probe)
        self.assertEqual(result["blocked"], [])
        self.assertEqual(result["errors"], [])
        self.assertEqual((result["rawCount"], result["rawFiles"]), (13300, 13300))
        compressed, linear = result["compressed"], result["linear"]
        self.assertTrue(compressed["checked"])
        self.assertGreater(compressed["smallHeight"], 40)
        self.assertGreater(compressed["smallPixels"], 20)
        self.assertTrue(any(label.startswith("▲13,200") for label in compressed["peakLabels"]))
        self.assertIn("13200건", compressed["largeTitle"])
        self.assertFalse(linear["checked"])
        self.assertEqual(linear["peakLabels"], [])
        self.assertLess(linear["smallHeight"], 2)
        self.assertGreater(compressed["smallHeight"], linear["smallHeight"] * 20)
        self.assertAlmostEqual(linear["smallHeight"] / linear["largeHeight"], 100 / 13200, delta=0.001)
        self.assertEqual(compressed["tableText"], linear["tableText"])
        for state in (compressed, linear):
            self.assertEqual((state["files"], state["total"]), (13300, 13300))
        self.assertNotIn("/api/run", result["requests"])


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--serve":
        serve(sys.argv[2])
    else:
        unittest.main()
