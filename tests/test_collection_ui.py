"""Run the actual rendered page and collection click path without an app server."""
import ast
from html.parser import HTMLParser
import json
from pathlib import Path
import shutil
import subprocess
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "LoadMonitor25/ui/app.py"


class Elements(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.elements = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.elements.append({"tag": tag, **dict(attrs)})


class CollectionUiTests(unittest.TestCase):
    def test_web_body_default_and_incomplete_capture_are_visible(self):
        self.run_js(r'''
assert.equal(byId.communicationbody.checked,true);
context.renderCommunicationEvidence({families:{teams:{unique_rows:4,context_rows:3,
 web_body_observed_rows:3,web_body_partial_rows:1}}});
assert.match(byId.communicationevidence.innerHTML,/웹 본문 3건 · 이 중 미펼침\/부분 1건/);
assert.match(byId.communicationevidence.innerHTML,/전체 원본 대비 확보율 미확인/);
''')

    def test_graph_connection_requires_explicit_app_and_logs_device_login(self):
        self.run_js(r'''
await byId.communicationconnect.onclick();assert.equal(requests.length,0);
assert.match(byId.communicationfeedback.textContent,/클라이언트 ID/);
byId.communicationclient.value='00000000-0000-4000-8000-000000000001';
byId.communicationtenant.value='example.invalid';byId.communicationchannels.checked=true;
fetchWith(async()=>reply(202,{ok:true}));await byId.communicationconnect.onclick();
assert.equal(requests[0].url,'/api/communication/connect');
assert.deepEqual(JSON.parse(requests[0].options.body),{from:'2026-09-01',to:'2026-09-13',client_id:'00000000-0000-4000-8000-000000000001',tenant_id:'example.invalid',include_channels:true});
assert.match(byId.communicationfeedback.textContent,/Microsoft 로그인/);
assert.equal(byId.communicationconnect.disabled,true);assert.equal(byId.communicationmsg.disabled,true);
''')

    def test_import_counts_and_addresses_are_explicit_and_msg_has_separate_route(self):
        self.run_js(r'''
byId.communicationpaths.value='D:\\synthetic\\mail.msg';
byId.communicationown.value='one@example.invalid, two@example.invalid';byId.communicationexpected.value='0';
fetchWith(async()=>reply(202,{ok:true}));await byId.communicationmsg.onclick();
assert.equal(requests[0].url,'/api/communication/msg');const body=JSON.parse(requests[0].options.body);
assert.deepEqual(body.own_addresses,['one@example.invalid','two@example.invalid']);assert.equal(body.expected_count,0);
assert(!body.ai);assert(!body.include_channels);
''')

    def test_new_communication_job_rejects_old_poll_and_shows_current_failure(self):
        self.run_js(r'''
context.refresh=async()=>{};context.reloadVisibleTab=async()=>{};
let oldReply;context.fetch=()=>new Promise(resolve=>oldReply=resolve);
const oldPoll=actualPoll();
fetchWith(async()=>reply(202,{ok:true}));await byId.communicationcollect.onclick();
oldReply(reply(200,{running:false,log:[],run_result:{message:'OLD DONE'}}));await oldPoll;
assert.equal(byId.communicationcollect.disabled,true);
assert.match(byId.communicationfeedback.textContent,/요청 접수/);
context.fetch=async()=>reply(200,{running:false,log:[],run_result:{message:'CURRENT IMPORT FAILED'}});
await actualPoll();assert.equal(byId.communicationfeedback.textContent,'CURRENT IMPORT FAILED');
assert.equal(byId.communicationcollect.disabled,false);
''')

    def test_interactive_communication_collection_uses_period_and_explicit_body_choice(self):
        self.run_js(r'''
fetchWith(()=>Promise.resolve(reply(202,{ok:true})));
byId.communicationbody.checked=true;
await byId.communicationcollect.onclick();
assert.equal(requests[0].url,'/api/communication/collect');
assert.deepEqual(JSON.parse(requests[0].options.body),{from:'2026-09-01',to:'2026-09-13',mail_body:true});
assert.equal(byId.communicationcollect.disabled,true);
assert.match(byId.communicationfeedback.textContent,/요청 접수/);
''')

    def test_mail_import_requires_explicit_paths_and_does_not_start_ai(self):
        self.run_js(r'''
byId.communicationpaths.value='';await byId.communicationimport.onclick();
assert.equal(requests.length,0);assert.match(byId.communicationfeedback.textContent,/경로/);
byId.communicationpaths.value='"D:\\synthetic\\first.eml"\nD:\\synthetic\\second.mbox';
fetchWith(()=>Promise.resolve(reply(202,{ok:true})));
await byId.communicationimport.onclick();
assert.equal(requests[0].url,'/api/communication/import');
assert.deepEqual(JSON.parse(requests[0].options.body),{from:'2026-09-01',to:'2026-09-13',paths:['D:\\synthetic\\first.eml','D:\\synthetic\\second.mbox']});
assert(!JSON.parse(requests[0].options.body).ai);
''')

    @classmethod
    def setUpClass(cls):
        tree = ast.parse(SOURCE.read_text(encoding="utf-8-sig"))
        page = ast.literal_eval(next(node.value for node in tree.body if isinstance(node, ast.Assign)
                                    and any(isinstance(t, ast.Name) and t.id == "PAGE" for t in node.targets)))
        script = page.split("<script>", 1)[1].split("</script>", 1)[0]
        cls.prelude = "const source=" + json.dumps(script) + ";\nconst elements=" + json.dumps(Elements(page).elements) + ";\n" + r'''
const assert=require('node:assert/strict'),vm=require('node:vm');
const nodes=elements.map(e=>({...e,value:'',checked:('checked' in e),disabled:false,style:{},dataset:{},
 classList:{toggle(){}},addEventListener(){},querySelectorAll(){return []}}));
const byId=Object.fromEntries(nodes.filter(n=>n.id).map(n=>[n.id,n]));
let requests=[],polls=0,intervals=0,timeouts=[];
const context={console,AbortController,
 document:{getElementById:id=>byId[id]||null,
  querySelectorAll:s=>s==='details'?nodes.filter(n=>n.tag==='details'):[],querySelector:()=>null},
 fetch:()=>new Promise(()=>{}),setInterval:()=>++intervals,clearInterval(){},
 setTimeout:f=>{timeouts.push(f);return timeouts.length},clearTimeout(){},
 confirm:()=>{throw Error('Collection must not depend on a modal dialog')},
 alert:()=>{throw Error('Unexpected modal')},window:{}};
vm.createContext(context);
vm.runInContext(source,context); // All top-level bindings use real IDs from the rendered HTML.
assert.equal(typeof byId.collect2.onclick,'function');
const actualPoll=context.poll;
context.poll=()=>{polls++};
byId.from.value='2026-09-01';byId.to.value='2026-09-13';
const reply=(status,data)=>({status,ok:status>=200&&status<300,json:async()=>data});
function fetchWith(fn){context.fetch=(url,options)=>{requests.push({url,options});return fn(url,options)}}
'''

    def run_js(self, body):
        node = shutil.which("node")
        self.assertIsNotNone(node, "Node.js is required for browser interaction checks")
        program = self.prelude + "\n(async()=>{\n" + body + "\n})().catch(e=>{console.error(e);process.exitCode=1});"
        result = subprocess.run([node, "-"], input=program, capture_output=True, text=True,
                                encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_collection_starts_without_dialog_and_blocks_duplicate_pending_clicks(self):
        self.run_js(r'''
let finish;fetchWith(()=>new Promise(resolve=>finish=resolve));
const click=byId.collect2.onclick();
assert.match(byId.run_feedback.textContent,/추가 PC 수집 요청 중/);
assert.equal(byId.dlog.open,true);
assert(['go','analyzecollected','collect2','prepmove'].every(id=>byId[id].disabled));
await byId.collect2.onclick();assert.equal(requests.length,1);
assert.equal(requests[0].url,'/api/run');
assert.deepEqual(JSON.parse(requests[0].options.body),{from:'2026-09-01',to:'2026-09-13',collect_only:true,mail_body:true});
finish(reply(200,{ok:true}));await click;
assert.match(byId.run_feedback.textContent,/요청 접수/);assert.equal(polls,1);
assert.equal(byId.collect2.disabled,true);
''')

    def test_additional_pc_web_body_can_be_explicitly_disabled(self):
        self.run_js(r'''
assert.equal(byId.collect2body.checked,true);
byId.collect2body.checked=false;fetchWith(async()=>reply(200,{ok:true}));await byId.collect2.onclick();
assert.equal(JSON.parse(requests[0].options.body).mail_body,false);
assert.equal(byId.communicationbody.checked,true); // Its independent default must not be changed by collect2.
''')

    def test_api_errors_are_visible_and_reenable_controls(self):
        self.run_js(r'''
for(const [status,data,expected] of [[400,{error:'잘못된 날짜'},'잘못된 날짜'],
 [503,{error:'worker unavailable'},'worker unavailable'],[409,{hint:'보고서 생성 중'},'보고서 생성 중'],
 [500,{},'서버 오류 (500)'],[200,{ok:false,error:'거절'},'거절']]){
 fetchWith(async()=>reply(status,data));await byId.collect2.onclick();
 assert(byId.run_feedback.textContent.includes(expected),byId.run_feedback.textContent);
 assert.equal(byId.collect2.disabled,false);
}
''')

    def test_disconnected_malformed_and_timed_out_responses_are_visible_without_retry(self):
        self.run_js(r'''
fetchWith(async()=>{throw new Error('network offline')});await byId.collect2.onclick();
assert.match(byId.run_feedback.textContent,/network offline/);
fetchWith(async()=>({ok:true,status:200,json:async()=>{throw new Error('not JSON')}}));
await byId.collect2.onclick();assert.match(byId.run_feedback.textContent,/응답 형식/);
fetchWith((url,options)=>new Promise((resolve,reject)=>options.signal.addEventListener('abort',()=>{
 const e=new Error('aborted');e.name='AbortError';reject(e)})));
const click=byId.collect2.onclick();timeouts.at(-1)();await click;
assert.match(byId.run_feedback.textContent,/응답 시간 초과/);assert.equal(requests.length,3);
assert.equal(byId.collect2.disabled,false);
''')

    def test_invalid_period_never_sends_collection_request(self):
        self.run_js(r'''
byId.from.value='';await byId.collect2.onclick();assert.match(byId.run_feedback.textContent,/기간/);
byId.from.value='2026-10-01';await byId.collect2.onclick();assert.match(byId.run_feedback.textContent,/시작일/);
assert.equal(requests.length,0);
''')

    def test_poll_preserves_request_error_and_displays_worker_failure(self):
        self.run_js(r'''
const status={running:false,log:[],run_result:{ok:false,message:'추가 PC 수집 시작/실행 실패: access denied'}};
fetchWith(async()=>reply(400,{error:'날짜 오류'}));await byId.collect2.onclick();
context.fetch=async()=>reply(200,status);
await actualPoll();assert.match(byId.run_feedback.textContent,/날짜 오류/);
fetchWith(async()=>reply(200,{ok:true}));await byId.collect2.onclick();
context.fetch=async()=>reply(200,status);context.refresh=async()=>{};context.reloadVisibleTab=async()=>{};
await actualPoll();assert.match(byId.run_feedback.textContent,/access denied/);
assert.equal(byId.collect2.disabled,false);
''')

    def test_old_status_cannot_replace_a_new_collection_result(self):
        self.run_js(r'''
context.refresh=async()=>{};context.reloadVisibleTab=async()=>{};
let oldReply;context.fetch=()=>new Promise(resolve=>oldReply=resolve);
const oldPoll=actualPoll();
fetchWith(async()=>reply(200,{ok:true}));await byId.collect2.onclick();
context.fetch=async()=>reply(200,{running:true,log:[]});await actualPoll();
oldReply(reply(200,{running:false,log:[],run_result:{message:'OLD RUN COMPLETED'}}));await oldPoll;
assert.match(byId.run_feedback.textContent,/요청 접수/);assert.equal(byId.collect2.disabled,true);
context.fetch=async()=>reply(200,{running:false,log:[],run_result:{message:'NEW COLLECTION FAILED'}});
await actualPoll();assert.equal(byId.run_feedback.textContent,'NEW COLLECTION FAILED');
''')

    def test_out_of_order_status_and_old_errors_do_not_revert_current_state(self):
        self.run_js(r'''
context.refresh=async()=>{};context.reloadVisibleTab=async()=>{};
fetchWith(async()=>reply(200,{ok:true}));await byId.collect2.onclick();
let oldReply;context.fetch=()=>new Promise(resolve=>oldReply=resolve);
const oldPoll=actualPoll();
context.fetch=async()=>reply(200,{running:false,log:[],run_result:{message:'COLLECTION COMPLETE'}});
await actualPoll();oldReply(reply(200,{running:true,log:[]}));await oldPoll;
assert.equal(byId.collect2.disabled,false);assert.equal(byId.run_feedback.textContent,'COLLECTION COMPLETE');
let oldReject;context.fetch=()=>new Promise((resolve,reject)=>oldReject=reject);
const oldError=actualPoll();
fetchWith(async()=>reply(200,{ok:true}));await byId.collect2.onclick();
context.fetch=async()=>reply(200,{running:true,log:[]});await actualPoll();
oldReject(new Error('old disconnected request'));await oldError;
assert.equal(byId.state.textContent,'실행 중…');
''')


if __name__ == "__main__":
    unittest.main()
