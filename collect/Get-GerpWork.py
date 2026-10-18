# -*- coding: utf-8 -*-
r"""
Get-GerpWork.py — GERP 근무 기록 읽기(LM30v1 시험 기능 · 기본 꺼짐): 사람이 전용 Edge 에서 로그인해 둔 GERP 근무시간 현황 화면을 읽는다.

  python collect\Get-GerpWork.py            # 읽기 — 설정 config\config.json 의 attendance.gerp(꺼져 있으면 Edge 를 띄우지 않고 끝)
  python collect\Get-GerpWork.py --open     # [GERP 열기(직접 로그인)] — 전용 Edge 에 그 화면을 열어 둔다(사람이 그 창에서 로그인)

LM30(2026-10-19) 사용자 요청 — "GERP 에서 근무일 불러오는 건 기능만 해 두고 디폴트 off(시험용) · 로그인은 개인이 GERP 에 해 둔 것으로 ·
로그아웃되면 안 가져오게 · HR 근무는 참고용이자 확실히 일한 부분이고 +@ 를 보기 위함 · 근태를 못 읽어도 +@ 는 봐야 한다".
 · 로그인하지 않는다 — 아이디·비밀번호를 넣지 않고 로그인 단추도 누르지 않는다. 쿠키를 읽거나 저장하지 않는다. 로그아웃 화면이면
   (core\gerp.login_state — 어느 프레임이든 input#userid·보이는 비밀번호 칸 · SSO 호스트로 넘어감) 아무것도 누르지 않고 우리 탭을 닫는다.
 · 전용 Edge 는 다른 웹 수집기(Get-OutlookWeb·Get-TeamsWeb)처럼 tools\copilot_auto 로 띄우거나 다시 쓰고(ensure_edge · 프로필
   data\lm30v1_edge · edge_lock 안에서만), 우리가 새로 연 탭 하나만 쓰고 닫는다(사람의 GERP 탭·다른 탭은 건드리지 않는다).
 · 프레임 — 같은 출처 프레임은 맨 위 문서에서 window.frames 를 걸어(JS_WALK·JS_AT), 다른 출처 프레임은 CDP 프레임 나무
   (Page.getFrameTree)와 프레임마다 격리 세계(Page.createIsolatedWorld — JS_DOC)로 읽는다.
 · 표 — 모든 프레임의 table 중 4번째 칸에 날짜(YYYY-MM-DD)가 있고 칸이 13개 이상인 행이 있는 표. 점수 = 보임×10000 + 날짜 행×100 +
   출근·퇴근·근무 머리글×1000 + 최대 칸 수. 칸 글이 비면 칸 안 입력 상자(input·textarea·select)의 값. 표가 처음 보인 뒤 SETTLE 초 기다렸다
   다시 찾는다(화면이 XHR 로 다시 그린다). '목록높이+' 단추를 날짜 행이 더 늘지 않을 때까지(MORE_MAX 번) 누른다 — 합성 마우스 사건이
   먹지 않으면 CDP 신뢰 입력(Input.dispatchMouseEvent) 한 번.
 · 기간 통계(선택) — 그 프레임의 ds_summary(getFields·getValue)에서 core\gerp.STAT_MAP 의 6개 값만.
 · 태깅(입실·퇴실 · readGate) — 날짜 칸 하나를 눌러 화면이 보내는 태깅 조회 요청(주소에 RetrieveGateInOutHist)을 CDP
   Network.requestWillBeSent 로 잡고, 읽을 날마다(core\gerp.gate_dates — maxGateDays) 그 주소의 IN_SEARCH.TNA_DATE 값만 바꿔 페이지 안에서
   fetch(쿠키 포함·X-Requested-With·참조 = 그 화면) 한다(GATE_GAP 간격). 잡은 주소(회사 코드·사번이 들어 있다)는 메모리에만 두고 파일·
   로그·상태에 쓰지 않는다. 응답은 페이지 안에서 [시각, IN|OUT, 입실|퇴실] 셋만 남겨 넘긴다.
출력: data\근태\gerp.csv(지난 날만 — core\gerp.upsert) · data\근태\gerp_status.json(core\gerp.make_status) ·
      마지막 줄 LMSTATUS {v, src:'gerp', rc, reason, counts{kind, rows, gate_days, …숫자}, ranges:[]}
종료 코드(= rc): 0 읽음 · 1 할 일 없음(꺼짐·주소 없음·로그아웃·표 없음 — 알림이 아니다) · 3 오류(Edge·화면·저장)
시험: tests\test_p38_gerp_reader.py — 가짜 탭(Tab 과 같은 꼴: start·goto·top_url·scan·run·click_trusted·net·pump·gate_url·close)으로
      read_gerp·collect 를 돈다(Edge·네트워크 없음).
"""
import io
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timedelta
from urllib.parse import quote

if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, errors="replace", encoding=(
        (sys.stdout.encoding or "utf-8") if sys.stdout.isatty() else "utf-8"))  # 콘솔(bat)=콘솔 코드페이지 · 파이프(UI)=utf-8

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (os.path.join(ROOT, "tools"), os.path.join(ROOT, "core")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import attendance  # noqa: E402  — 설정 검증(norm_gerp)
import gerp  # noqa: E402  — 판정·해석·저장·문구(순수)

POLL = 0.5             # 화면 상태를 보는 간격(초)
SETTLE = 3.0           # 표가 처음 보인 뒤 다시 찾기 전 기다림(초 — 화면이 XHR 로 다시 그린다)
SSO_CONFIRM = 2        # 'SSO 호스트' 판정은 이만큼 이어 볼 때만 믿는다(로그인된 세션도 SSO 를 잠깐 거친다)
NET_GRACE = 6.0        # 브라우저 오류 화면(네트워크)이 이 초 뒤에도 그대로면 오류
MORE_MAX = 10          # '목록높이+' 누르기 상한
MORE_WAIT = 0.4        # 누른 뒤 다시 세기 전 기다림(초)
READ_TRIES = 3         # 행 읽기 — 다시 그리는 순간이면 1초 쉬고 다시
CAPTURE_SEC = 8.0      # 날짜 칸을 누른 뒤 태깅 조회 요청을 기다리는 상한(초)
GATE_GAP = 0.3         # 태깅 조회 사이 간격(초)
GATE_FAIL_MAX = 3      # 태깅 조회가 이만큼 잇달아 실패하면 그만
LOCK_SEC = 120         # 전용 Edge 잠금 대기(초) — 넘으면 다른 작업이 쓰는 중
OPEN_LOCK_SEC = 5      # [GERP 열기]는 오래 기다리지 않는다(화면 요청 안)

# ── 화면 JS — 프레임 하나(D = document, W = window, A = 인자)에서 도는 함수들. 머리 표식(/*LM30:gerp_…*/)으로 시험이 알아본다 ──
JS_PRE = r"""const DRX=/(\d{4})-(\d{2})-(\d{2})/;
const vis=e=>{try{const r=e.getBoundingClientRect();if(!(r.width>0&&r.height>0))return false;const s=W.getComputedStyle(e);return s.visibility!=="hidden"&&s.display!=="none";}catch(x){return false;}};
const txt=c=>{let t="";try{t=String(c.innerText||"").trim();}catch(x){t="";}if(t)return t;const cs=Array.from(c.querySelectorAll("input, textarea, select"));const v=cs.find(x=>typeof x.value==="string"&&x.offsetParent!==null)||cs.find(x=>typeof x.value==="string");return String((v?v.value:c.textContent)||"").trim();};
const look=(t,i)=>{let dr=0,mc=0;for(const r of t.querySelectorAll("tr")){const cs=r.querySelectorAll("td");if(cs.length>mc)mc=cs.length;if(cs.length>3&&DRX.test(txt(cs[3])))dr++;}if(!(dr>0&&mc>=13))return null;const s=String(t.innerText||"").replace(/\s+/g," ");const lab=/출근/.test(s)&&/퇴근/.test(s)&&/근무/.test(s);const v=vis(t);return {i:i,dr:dr,mc:mc,v:v?1:0,lab:lab?1:0,score:(v?10000:0)+dr*100+(lab?1000:0)+mc};};
const best=()=>{const ts=D.querySelectorAll("table");let b=null,el=null;for(let i=0;i<ts.length&&i<800;i++){const c=look(ts[i],i);if(c&&(!b||c.score>b.score)){b=c;el=ts[i];}}return [b,el];};
const fire=el=>{try{el.scrollIntoView({block:"center",inline:"center"});}catch(x){}const r=el.getBoundingClientRect();const o={bubbles:true,cancelable:true,view:W,clientX:r.left+r.width/2,clientY:r.top+r.height/2,button:0};for(const k of ["mouseover","mousedown","mouseup","click"]){try{el.dispatchEvent(new W.MouseEvent(k,o));}catch(x){}}return 1;};
"""
FN = {
    # 로그인 표식(input#userid·보이는 비밀번호 칸)·문서 준비 상태·이 문서의 가장 나은 표 후보(점수) — 글자는 싣지 않는다
    "snap": "/*LM30:gerp_snap*/(D,W,A)=>{" + JS_PRE + r"""let uid=0,pw=0;try{uid=D.querySelector("input#userid")?1:0;for(const e of D.querySelectorAll("input[type=password]"))if(vis(e))pw++;}catch(x){}let t=null;try{t=best()[0];}catch(x){t=null;}return {uid:uid,pw:pw,rs:String(D.readyState||""),t:t};}""",
    "best": "/*LM30:gerp_best*/(D,W,A)=>{" + JS_PRE + "return best()[0];}",
    # 가장 나은 표의 날짜 행 — 4~13번째 칸 글(칸마다 80자)
    "read": "/*LM30:gerp_read*/(D,W,A)=>{" + JS_PRE + r"""const bt=best();const t=bt[1];if(!t)return null;const rows=[];for(const r of t.querySelectorAll("tr")){const cs=r.querySelectorAll("td");if(cs.length<13)continue;if(!DRX.test(txt(cs[3])))continue;const row=[];for(let k=3;k<=12;k++)row.push(txt(cs[k]).slice(0,80));rows.push(row);if(rows.length>=400)break;}return {b:bt[0],rows:rows};}""",
    # '목록높이+' 단추 — 가장 안쪽 요소를 누른다(A.el 이면 누르지 않고 그 요소를 돌려준다 — 신뢰 입력용)
    "more": "/*LM30:gerp_more*/(D,W,A)=>{" + JS_PRE + r"""const want="목록높이+";let el=null;for(const e of D.querySelectorAll("button, a, span, div, td, li, label, input[type=button], input[type=submit], [role=button]")){const raw=String((e.tagName==="INPUT")?(e.value||""):(e.textContent||""));if(!raw||raw.length>80)continue;const s=raw.replace(/\s+/g,"");if(s&&s.length<=want.length+4&&s.indexOf(want)>=0)el=e;}if(A&&A.el)return el;if(!el)return 0;return fire(el);}""",
    # 날짜 칸 하나(A.want yyyymmdd 가 있으면 그 날, 없으면 A.max 이하의 첫 날)를 누른다 — 화면이 태깅 조회 요청을 보내게(A.el 이면 요소)
    "cell": "/*LM30:gerp_cell*/(D,W,A)=>{" + JS_PRE + r"""const t=best()[1];if(!t)return (A&&A.el)?null:0;let cell=null;for(const r of t.querySelectorAll("tr")){const cs=r.querySelectorAll("td");if(cs.length<=3)continue;const m=txt(cs[3]).match(DRX);if(!m)continue;const d=m[1]+m[2]+m[3];if(d===A.want){cell=cs[3];break;}if(!cell&&d<=A.max)cell=cs[3];}if(A&&A.el)return cell;if(!cell)return 0;return fire(cell);}""",
    # 기간 통계 — ds_summary 에서 정해 둔 6개 값만(다른 칸은 넘기지 않는다)
    "ds": r"""/*LM30:gerp_ds*/(D,W,A)=>{const K=["TNA_YM","WORK_DAYS","FIXED_WORK_DAYS","MON_BASE_WRK_HOURS","MON_MAX_WRK_HOURS","MON_MAX_OT_HOUR"];let ds=null;try{ds=W.ds_summary;}catch(x){ds=null;}if(!ds){try{ds=W.eval("ds_summary");}catch(x){ds=null;}}if(!ds||typeof ds.getFields!=="function"||typeof ds.getValue!=="function")return null;const out={};try{const f=ds.getFields();for(let i=0;i<f.length&&i<300;i++){const id=String((f[i]&&(f[i].id||f[i].name))||f[i]||"");if(K.indexOf(id)<0)continue;const v=ds.getValue(0,i);if(v===null||v===undefined||v==="")continue;out[id]=(typeof v==="number")?v:String(v).slice(0,20);}}catch(x){return null;}return out;}""",
    # 태깅 조회 — 페이지 안에서 fetch(쿠키 포함). 응답은 [시각, IN|OUT, 입실|퇴실] 셋만 남긴다(사번·회사 코드는 넘기지 않는다)
    "fetch": r"""/*LM30:gerp_fetch*/(D,W,A)=>(async()=>{try{const r=await W.fetch(A.u,{credentials:"include",cache:"no-store",headers:{"X-Requested-With":"XMLHttpRequest","Accept":"application/json, text/javascript, */*; q=0.01"}});const t=await r.text();let j=null;try{j=JSON.parse(t);}catch(x){j=null;}const L=j?j.OUT_INOUT_HIST:null;const arr=Array.isArray(L)?L:((L&&typeof L==="object")?[L]:null);if(!arr)return {s:r.status,bad:1,login:/userid|password|비밀번호|로그인/i.test(t.slice(0,20000))?1:0};return {s:r.status,h:arr.slice(0,500).map(x=>[String((x&&x.INOUT_DT)||""),String((x&&x.INOUT_FLAG)||""),String((x&&x.INOUT_FLAG_NM)||"")])};}catch(e){return {s:-1,e:String((e&&e.name)||"error").slice(0,40)};}})()""",
}
# 같은 출처 프레임 — 맨 위 문서에서 window.frames 를 건다(다른 출처 프레임은 x:1 로 세고 그 안쪽으로는 계속 건다 — frames 는 다른 출처에서도 보인다)
JS_WALK = r"""/*LM30:gerp_walk*/(()=>{const FN=(__FN__);const A=__ARG__;const out=[];const go=(w,p,depth)=>{let d=null;try{d=w.document;void d.documentElement;}catch(e){d=null;}if(d){let r=null;try{r=FN(d,w,A);}catch(e){r={err:String((e&&e.name)||"error").slice(0,40)};}out.push({p:p.join("."),r:r});}else{out.push({p:p.join("."),x:1});}if(depth>=6||out.length>=60)return;let n=0;try{n=w.frames.length;}catch(e){n=0;}for(let i=0;i<n&&i<30;i++){let c=null;try{c=w.frames[i];}catch(e){c=null;}if(c)go(c,p.concat([i]),depth+1);}};go(window,[],0);return out;})()"""
# 같은 출처 프레임 하나(경로 — window.frames 번호들)에서 함수 하나
JS_AT = r"""/*LM30:gerp_at*/(()=>{let w=window;const P=__PATH__;for(let k=0;k<P.length;k++){let c=null;try{c=w.frames[P[k]];}catch(e){c=null;}if(!c)return null;w=c;}let d=null;try{d=w.document;void d.documentElement;}catch(e){return null;}return (__FN__)(d,w,__ARG__);})()"""
# 다른 출처 프레임 — 그 프레임의 격리 세계에서
JS_DOC = r"""/*LM30:gerp_doc*/(__FN__)(document,window,__ARG__)"""


def _fill(tpl, fn, arg=None, path=None):
    """JS 틀에 함수·경로·인자를 넣는다 — 인자(잡은 주소일 수 있다)는 맨 나중에(그 글이 다른 자리표로 바뀌지 않게)."""
    return (tpl.replace("__FN__", fn).replace("__PATH__", json.dumps(list(path or [])))
            .replace("__ARG__", json.dumps(arg, ensure_ascii=False)))


def log(msg):
    try:
        print(msg, flush=True)
    except (OSError, ValueError):
        pass


def emit_status(rc, counts=None, reason=""):
    """마지막 줄 — 'LMSTATUS ' + JSON 한 줄(수집기 계약 · core\\collect_status). 주소·사번은 싣지 않는다."""
    log("LMSTATUS " + json.dumps({"v": 1, "src": "gerp", "rc": int(rc), "reason": str(reason or ""),
                                  "counts": counts or {}, "ranges": []}, ensure_ascii=False))


def _ca():
    """tools\\copilot_auto(같은 프로세스에 이미 올라와 있으면 그것 — 화면이 [GERP 열기]를 같은 프로세스에서 부른다)"""
    import copilot_auto
    return copilot_auto


# ════════════════════════════════ CDP — 우리 탭 하나 ════════════════════════════════
class TabCDP:
    """우리 탭 하나의 CDP 연결 — copilot_auto.CDP 와 같은 왕복에 둘을 더했다: ① 답을 기다리는 동안 온 사건 중 태깅 조회 요청
    (Network.requestWillBeSent — 주소에 RetrieveGateInOutHist)만 메모리에 잡는다(파일·로그에 쓰지 않는다) ② 실행 문맥(contextId — 다른
    출처 프레임의 격리 세계)·약속 기다림(awaitPromise — 페이지 안 fetch)·객체로 받기(신뢰 입력용 요소)."""

    def __init__(self, ws):
        self.ws = ws
        self.n = 0
        self.watch = False
        self.gate = []

    def call(self, method, params=None, timeout=25):
        self.n += 1
        mid = self.n
        self.ws.send_text(json.dumps({"id": mid, "method": method, "params": params or {}}))
        end = time.time() + timeout
        while True:
            remain = end - time.time()
            if remain <= 0:
                raise TimeoutError(f"CDP {method}: {timeout}초 안에 답 없음")
            self.ws.sock.settimeout(max(0.5, min(remain, 30.0)))
            msg = json.loads(self.ws.recv_text())
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(f"CDP {method}: {str((msg.get('error') or {}).get('message') or '')[:120]}")
                return msg.get("result") or {}
            if self.watch and msg.get("method") == "Network.requestWillBeSent":
                u = str((((msg.get("params") or {}).get("request")) or {}).get("url") or "")
                if gerp.GATE_KEY in u.lower() and len(self.gate) < 4:
                    self.gate.append(u)

    def eval(self, expr, ctx=None, wait=False, by_value=True, timeout=25):
        p = {"expression": expr, "returnByValue": bool(by_value), "awaitPromise": bool(wait)}
        if ctx:
            p["contextId"] = int(ctx)
        r = self.call("Runtime.evaluate", p, timeout=timeout)
        ex = r.get("exceptionDetails")
        if ex:
            d = str((ex.get("exception") or {}).get("description") or ex.get("text") or "오류")
            raise RuntimeError("JS: " + (d.splitlines() or ["오류"])[0][:120])
        res = r.get("result") or {}
        return res.get("value") if by_value else res

    def close(self):
        try:
            self.ws.close()
        except Exception:  # noqa: BLE001 - 닫기 실패는 무시
            pass


class Tab:
    """전용 Edge 의 우리 탭 하나 — 읽기 흐름(read_gerp)이 쓰는 꼴: start·goto·top_url·scan·run·click_trusted·net·pump·gate_url·close.
    프레임 열쇠: 'p:<번호.번호>'(같은 출처 — 맨 위에서 window.frames 경로) · 'f:<frameId>'(다른 출처 — 격리 세계)."""

    def __init__(self, ca, cfg):
        self.ca, self.cfg = ca, cfg
        self.port = int(cfg.get("port") or 0)
        self.tid, self.cdp, self.reason = "", None, ""
        self.worlds = {}
        self.diag = {"walk": 0, "blocked": 0, "iso": 0, "iso_fail": 0}

    def start(self):
        if not self.ca.ensure_edge(self.cfg):
            self.reason = str(self.ca.LAST.get("reason") or "R-EDGELAUNCH")
            return False
        t = None
        for method in ("PUT", "GET"):
            try:
                t = self.ca.http_json(self.port, "/json/new?about:blank", method=method)
                break
            except Exception:  # noqa: BLE001 - 판마다 PUT·GET 중 하나만 받는다
                t = None
        if not isinstance(t, dict) or not t.get("webSocketDebuggerUrl"):
            self.reason = "R-EDGELAUNCH"
            return False
        self.tid = str(t.get("id") or "")
        self.cdp = TabCDP(self.ca.ws_open(t["webSocketDebuggerUrl"]))
        self.cdp.call("Page.enable")
        return True

    def goto(self, url):
        r = self.cdp.call("Page.navigate", {"url": url}, timeout=30)
        return str(r.get("errorText") or "")

    def top_url(self):
        return str(self.cdp.eval("location.href", timeout=10) or "")

    def _foreign(self):
        """맨 위 문서와 출처(securityOrigin)가 다른 프레임의 id 목록(Page.getFrameTree · 40개까지)"""
        tree = (self.cdp.call("Page.getFrameTree", timeout=15) or {}).get("frameTree") or {}
        top = str((tree.get("frame") or {}).get("securityOrigin") or "")
        out, todo = [], list(tree.get("childFrames") or [])
        while todo and len(out) < 40:
            n = todo.pop(0) or {}
            f = n.get("frame") or {}
            if f.get("id") and str(f.get("securityOrigin") or "") != top:
                out.append(str(f["id"]))
            todo.extend(n.get("childFrames") or [])
        return out

    def _world(self, fid, fresh=False):
        if fresh or fid not in self.worlds:
            r = self.cdp.call("Page.createIsolatedWorld", {"frameId": fid, "worldName": "lm30v1_gerp"}, timeout=15)
            self.worlds[fid] = int(r.get("executionContextId") or 0)
        return self.worlds[fid]

    def _in_world(self, fid, expr, wait=False, by_value=True, timeout=30):
        try:
            return self.cdp.eval(expr, ctx=self._world(fid), wait=wait, by_value=by_value, timeout=timeout)
        except RuntimeError as e:
            if "context" not in str(e).lower():
                raise
            return self.cdp.eval(expr, ctx=self._world(fid, fresh=True), wait=wait, by_value=by_value, timeout=timeout)

    def scan(self, name, arg=None):
        """모든 프레임에서 함수 하나 → [(열쇠, 결과)]. 같은 출처는 걷기 한 번, 다른 출처가 있으면 프레임마다 격리 세계."""
        res = self.cdp.eval(_fill(JS_WALK, FN[name], arg), timeout=30)
        out, blocked = [], 0
        for it in res if isinstance(res, list) else []:
            if not isinstance(it, dict):
                continue
            if it.get("x"):
                blocked += 1
                continue
            out.append(("p:" + str(it.get("p") or ""), it.get("r")))
        self.diag["walk"] = max(self.diag["walk"], len(out))
        self.diag["blocked"] = max(self.diag["blocked"], blocked)
        if blocked:
            n = 0
            for fid in self._foreign():
                try:
                    r = self._in_world(fid, _fill(JS_DOC, FN[name], arg))
                except RuntimeError:
                    self.diag["iso_fail"] += 1
                    continue
                out.append(("f:" + fid, r))
                n += 1
            self.diag["iso"] = max(self.diag["iso"], n)
        return out

    def _expr(self, key, name, arg):
        if key.startswith("p:"):
            return None, _fill(JS_AT, FN[name], arg, [int(x) for x in key[2:].split(".") if x.isdigit()])
        return key[2:], _fill(JS_DOC, FN[name], arg)

    def run(self, key, name, arg=None, wait=False, timeout=30):
        """프레임 하나(열쇠)에서 함수 하나 → 결과(wait = 약속을 기다린다 — fetch)"""
        fid, expr = self._expr(key, name, arg)
        if fid is None:
            return self.cdp.eval(expr, wait=wait, timeout=timeout)
        return self._in_world(fid, expr, wait=wait, timeout=timeout)

    def click_trusted(self, key, name, arg=None):
        """그 함수가 돌려준 요소를 CDP 신뢰 입력으로 누른다(합성 사건을 받지 않는 화면 — 한 번씩만 쓴다) → 눌렀나"""
        a = dict(arg or {})
        a["el"] = 1
        fid, expr = self._expr(key, name, a)
        res = (self.cdp.eval(expr, by_value=False, timeout=20) if fid is None
               else self._in_world(fid, expr, by_value=False, timeout=20))
        oid = (res or {}).get("objectId")
        if not oid:
            return False
        try:
            try:
                self.cdp.call("DOM.scrollIntoViewIfNeeded", {"objectId": oid}, timeout=10)
            except RuntimeError:
                pass
            try:
                quads = (self.cdp.call("DOM.getContentQuads", {"objectId": oid}, timeout=10) or {}).get("quads") or []
                q = quads[0] if quads else []
            except RuntimeError:
                q = ((self.cdp.call("DOM.getBoxModel", {"objectId": oid}, timeout=10) or {}).get("model") or {}).get("content") or []
            if len(q) < 8:
                return False
            x, y = sum(q[0::2][:4]) / 4.0, sum(q[1::2][:4]) / 4.0
            for t in ("mouseMoved", "mousePressed", "mouseReleased"):
                p = {"type": t, "x": x, "y": y}
                if t != "mouseMoved":
                    p.update(button="left", clickCount=1)
                self.cdp.call("Input.dispatchMouseEvent", p, timeout=10)
            return True
        except RuntimeError:
            return False
        finally:
            try:
                self.cdp.call("Runtime.releaseObject", {"objectId": oid}, timeout=5)
            except (RuntimeError, OSError):
                pass

    def net(self, on):
        """태깅 조회 요청 잡기 켜기·끄기(Network.enable/disable — 끄면 잡은 것은 그대로 둔다)"""
        self.cdp.watch = bool(on)
        try:
            self.cdp.call("Network.enable" if on else "Network.disable", timeout=10)
        except RuntimeError:
            pass

    def pump(self):
        """밀린 사건을 읽는다(가벼운 왕복 한 번)"""
        self.cdp.eval("1", timeout=10)

    def gate_url(self):
        return self.cdp.gate[0] if (self.cdp is not None and self.cdp.gate) else ""

    def close(self):
        """우리 탭만 닫는다(잡은 주소도 버린다)."""
        if self.cdp is not None:
            self.cdp.watch = False
            self.cdp.gate.clear()
            self.cdp.close()
            self.cdp = None
        if self.tid:
            try:
                self.ca._close_tab(self.port, self.tid)
            except Exception:  # noqa: BLE001 - 닫기 실패는 무시(사람이 닫을 수 있다)
                pass
            self.tid = ""


# ════════════════════════════════ 읽기 흐름 ════════════════════════════════
def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _snap(tab):
    """화면 한 장 → (login_state 의 snap, 가장 나은 표 (열쇠, 후보) | None)"""
    try:
        top = tab.top_url()
    except RuntimeError:
        top = ""
    docs = tab.scan("snap")
    ready = next((str((r or {}).get("rs") or "") for k, r in docs if k == "p:" and isinstance(r, dict)), "")
    best = None
    for k, r in docs:
        t = r.get("t") if isinstance(r, dict) else None
        if isinstance(t, dict) and _f(t.get("score")) > 0 and (best is None or _f(t.get("score")) > _f(best[1].get("score"))):
            best = (k, t)
    return {"top": top, "docs": [r for _k, r in docs if isinstance(r, dict)], "ready": ready}, best


def _gate_wait(tab, sec, sleep, mono):
    end = mono() + sec
    while True:
        tab.pump()
        u = tab.gate_url()
        if u or mono() >= end:
            return u
        sleep(0.25)


def _gates(tab, key, rows, g, today, tagged, sleep, mono, dg):
    """태깅(입실·퇴실) — 읽을 날을 고르고, 날짜 칸을 눌러 화면의 태깅 조회 주소를 잡은 뒤 날마다 그 날짜만 바꿔 읽는다 → {date: 요약}"""
    want = gerp.gate_dates([r["date"] for r in rows], tagged, today, g["maxGateDays"])
    dg["gate_want"] = len(want)
    if not want:
        return {}
    tab.net(True)
    try:
        arg = {"want": (today - timedelta(days=1)).strftime("%Y%m%d"), "max": today.strftime("%Y%m%d")}
        if not tab.run(key, "cell", arg):
            dg["gate"] = "no_cell"
            return {}
        url = _gate_wait(tab, CAPTURE_SEC, sleep, mono)
        if not url and tab.click_trusted(key, "cell", arg):
            dg["gate_click"] = "trusted"
            url = _gate_wait(tab, CAPTURE_SEC, sleep, mono)
    finally:
        tab.net(False)
    if not url:
        dg["gate"] = "no_request"
        return {}
    out, fails, keys = {}, 0, [key] + (["p:"] if key != "p:" else [])
    for i, d in enumerate(want):
        u = gerp.with_tna_date(url, d)
        if not u:
            dg["gate"] = "no_param"
            break
        if i:
            sleep(GATE_GAP)
        r = {}
        for k in list(keys):
            r = tab.run(k, "fetch", {"u": u}, wait=True, timeout=30) or {}
            if _f(r.get("s")) >= 0 or len(keys) == 1:
                keys = [k]                                # 이 프레임에서 된다(다른 출처 막힘이면 맨 위 문서로 한 번)
                break
        if isinstance(r.get("h"), list) and 200 <= _f(r.get("s")) < 300:
            out[d] = gerp.gate_summary(d, r["h"])
            fails = 0
            continue
        if r.get("login"):
            dg["gate"] = "login"                          # 읽는 사이 로그인이 풀렸다 — 더 묻지 않는다
            break
        fails += 1
        dg["gate_fail"] = dg.get("gate_fail", 0) + 1
        if fails >= GATE_FAIL_MAX:
            dg["gate"] = "fail"
            break
    return out


def read_gerp(tab, g, today, tagged=(), sleep=time.sleep, mono=time.monotonic):
    """열린 우리 탭에서 GERP 근무 현황을 읽는다 → {kind, why, rows[hr_row], gates{date: 요약}, stats, period, diag}.
    kind = ok | logged_out | no_table | error. 로그아웃이면 아무것도 누르지 않고 바로 돌아온다. 탭은 호출측이 닫는다."""
    out = {"kind": "error", "why": "", "rows": [], "gates": {}, "stats": {}, "period": [], "diag": {}}
    dg = out["diag"]
    t0 = mono()
    end = t0 + float(g.get("timeoutSec") or 60)
    if tab.goto(g["url"]):
        dg["nav_err"] = 1
    first, sso, state, why, best = None, 0, "", "", None
    while True:
        sleep(POLL)
        snap, cand = _snap(tab)
        state, why = gerp.login_state(snap, g["url"])
        dg["polls"] = dg.get("polls", 0) + 1
        if state == "logged_out":
            if why == "form":
                break
            sso += 1
            if sso >= SSO_CONFIRM and snap.get("ready") == "complete":
                break
        else:
            sso = 0
        if state == "error" and mono() - t0 >= NET_GRACE:
            break
        if cand is not None and state == "logged_in":
            best = cand
            first = mono() if first is None else first
            if mono() - first >= SETTLE:
                break
        if mono() >= end:
            break
    dg["wait_s"] = round(mono() - t0, 1)
    if state == "logged_out":
        out.update(kind="logged_out", why="GERP 에 로그인되어 있지 않아 읽지 않았습니다 — 대시보드 '출퇴근·시간외 근무' 카드의 "
                                            "[GERP 열기(직접 로그인)]로 전용 Edge 창에서 로그인한 뒤 다시 읽으세요")
        return out
    if state == "error":
        out.update(kind="error", why="GERP 화면을 열지 못했습니다(사내망·VPN 연결을 확인하세요)")
        return out
    if best is None:
        out.update(kind="no_table", why="근무 현황 표를 찾지 못했습니다 — attendance.gerp.url 이 근무시간 현황 화면 주소인지 확인하세요")
        return out
    key = best[0]
    dg["frame"] = "same" if key.startswith("p:") else "cross"
    prev = int(_f(best[1].get("dr")))
    dg["dr0"] = prev
    trusted = False
    clicks = 0
    for i in range(MORE_MAX):
        ok = tab.click_trusted(key, "more") if trusted else bool(tab.run(key, "more"))
        if not ok:
            break
        clicks += 1
        sleep(MORE_WAIT)
        n = int(_f((tab.run(key, "best") or {}).get("dr")))
        if n <= prev and i == 0 and tab.click_trusted(key, "more"):
            clicks += 1                                   # 첫 누름이 먹지 않았다 — 합성 사건을 받지 않는 화면일 수 있어 신뢰 입력으로 한 번
            sleep(MORE_WAIT)
            n = int(_f((tab.run(key, "best") or {}).get("dr")))
            trusted = n > prev                            # 늘었으면 남은 누름도 신뢰 입력으로
        if n <= prev:
            break
        prev = n
    dg.update(more=clicks, dr=prev, more_how="trusted" if trusted else "synth")
    rows = []
    for k in range(READ_TRIES):
        rd = tab.run(key, "read") or {}
        rows = [r for r in (gerp.hr_row(c) for c in (rd.get("rows") or []) if isinstance(c, list)) if r]
        if rows:
            break
        if k + 1 < READ_TRIES:
            sleep(1.0)
    if not rows:
        out.update(kind="no_table", why="근무 현황 표에서 날짜 행을 읽지 못했습니다 — 화면을 직접 열어 표가 보이는지 확인하세요")
        return out
    by = {r["date"]: r for r in rows}
    rows = [by[d] for d in sorted(by)]
    out["rows"] = rows
    out["period"] = [rows[0]["date"].isoformat(), rows[-1]["date"].isoformat()]
    try:
        out["stats"] = gerp.period_stats(tab.run(key, "ds"))
    except RuntimeError:
        dg["ds"] = 0
    if g.get("readGate") and int(g.get("maxGateDays") or 0) > 0:
        try:
            out["gates"] = _gates(tab, key, rows, g, today, tagged, sleep, mono, dg)
        except (RuntimeError, TimeoutError, OSError) as e:
            dg["gate"] = "err"
            dg["gate_err"] = type(e).__name__[:24]
    out["kind"] = "ok"
    return out


def _edge_why(reason, act="GERP 를 읽지"):
    """전용 Edge 사유 코드 → 쉬운 말 한 줄(코드는 싣지 않는다). act = 'GERP 를 읽지' | 'GERP 화면을 열지'"""
    return {"R-EDGEPOL": f"회사 Edge 정책이 전용 Edge 를 막아 {act} 못했습니다",
            "R-EDGEFOREIGN": f"디버그 포트를 다른 프로그램의 Edge 가 쓰고 있어 {act} 못했습니다",
            "R-EDGEBUSY": f"다른 작업이 전용 Edge 를 쓰고 있어 {act} 못했습니다 — 끝난 뒤 다시 하세요",
            }.get(str(reason or ""), f"전용 Edge 를 띄우지 못해 {act} 못했습니다")


def _opener():
    """전용 Edge 의 우리 탭 + 잠금(copilot_auto.edge_lock — 다른 작업과 직렬)"""
    ca = _ca()
    cfg = ca.load_cfg()
    return Tab(ca, cfg), ca.edge_lock(cfg, timeout=LOCK_SEC)


def collect(g, data_dir, opener=None, now=None, sleep=time.sleep, mono=time.monotonic):
    r"""GERP 읽기 한 번 — 꺼짐·주소 없음이면 Edge 를 띄우지 않는다. 읽은 것을 data\근태\gerp.csv 에 모으고(지난 날만) 상태 파일을 쓴다.
    → 상태 dict(core\gerp.make_status — why 가 사람용 한 줄). opener() → (탭, 잠금) — 시험이 가짜 탭을 넣는다."""
    now = now or datetime.now()
    today = now.date()
    prev = gerp.read_status(data_dir)
    res = {"rows": [], "gates": {}, "stats": {}, "period": [], "diag": {}}
    n_hr = n_gate = 0
    if not g.get("enabled"):
        kind, why = "disabled", "GERP 근무 기록 읽기가 꺼져 있습니다(attendance.gerp.enabled)"
    elif not g.get("url"):
        kind, why = "no_url", "GERP 근무 현황 화면 주소(attendance.gerp.url)가 비어 있거나 http(s) 주소가 아닙니다"
    else:
        csvp = gerp.csv_path(data_dir)
        tagged = gerp.tagged_dates(gerp.read_rows(csvp))
        try:
            tab, lock = (opener or _opener)()
        except Exception as e:  # noqa: BLE001 - 드라이버를 못 불러도 실행은 계속(오류 한 줄)
            tab, lock = None, None
            kind, why = "error", f"전용 Edge 를 쓸 준비를 하지 못했습니다({type(e).__name__})"
        if tab is not None:
            try:
                with lock:
                    try:
                        if not tab.start():
                            kind, why = "error", _edge_why(tab.reason)
                        else:
                            log("   GERP 근무 현황 화면을 우리 탭 하나로 엽니다(로그인은 하지 않습니다) …")
                            res = read_gerp(tab, g, today, tagged, sleep, mono)
                            kind, why = res["kind"], res.get("why") or ""
                    finally:
                        res.setdefault("diag", {}).update({k: v for k, v in (getattr(tab, "diag", None) or {}).items()
                                                           if isinstance(v, (int, float))})
                        tab.close()
            except Exception as e:  # noqa: BLE001 - 오류여도 상태 파일을 남기고 실행은 계속
                kind = "error"
                why = _edge_why("R-EDGEBUSY") if str(getattr(e, "reason", "")) == "R-EDGEBUSY" \
                    else f"GERP 를 읽는 중 문제가 생겼습니다({type(e).__name__})"
        if kind == "ok":
            try:
                n_hr, n_gate, _n = gerp.upsert(csvp, res["rows"], res["gates"], now.strftime("%Y-%m-%d %H:%M"), today)
                why = ((f"근무 기록 {n_hr}일을 읽어 data\\근태\\gerp.csv 에 모았습니다(지난 날만 — 오늘은 끝난 뒤에 적습니다)" if n_hr
                        else "근무 현황을 읽었지만 화면에 지난 날이 없어 적지 않았습니다(오늘·앞날은 끝난 뒤에 적습니다)")
                       + (f" · 태깅(입실·퇴실) {n_gate}일" if n_gate else "")
                       + (" · 태깅 기록은 이번에 읽지 못했습니다" if res["diag"].get("gate") else ""))
            except OSError:
                kind, why = "error", "gerp.csv 를 저장하지 못했습니다 — 엑셀 등에서 열려 있으면 닫고 다시 읽으세요"
    st = gerp.make_status(kind, now, rows=n_hr, gate_days=n_gate, period=res.get("period"), why=why,
                          stats=res.get("stats"), diag=res.get("diag"), prev=prev)
    gerp.write_status(data_dir, st)
    return st


# ════════════════════════════════ [GERP 열기(직접 로그인)] ════════════════════════════════
def _activate(port, tid):
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{int(port)}/json/activate/{tid}", timeout=5).read()
    except Exception:  # noqa: BLE001 - 앞으로 가져오지 못해도 탭은 열렸다
        pass


def open_login(g, ca=None):
    """전용 Edge 에 GERP 근무 현황 화면을 연다(띄울 때는 첫 탭으로, 떠 있으면 새 탭으로 — 앞으로 가져온다). 사람이 그 탭에서 직접
    로그인한다 — 이 프로그램은 아이디·비밀번호를 넣지 않고 로그인 단추도 누르지 않는다. 다른 작업이 전용 Edge 를 쓰는 중이면 열지 않는다.
    → {"ok", "why"(쉬운 말), "skip"(꺼짐·주소 없음)}"""
    if not g.get("enabled"):
        return {"ok": False, "skip": True, "why": "GERP 근무 기록 읽기가 꺼져 있습니다(attendance.gerp.enabled)"}
    if not g.get("url"):
        return {"ok": False, "skip": True, "why": "GERP 근무 현황 화면 주소(attendance.gerp.url)가 비어 있습니다"}
    ca = ca or _ca()
    cfg = ca.load_cfg()
    port = int(cfg.get("port") or 0)
    try:
        with ca.edge_lock(cfg, timeout=OPEN_LOCK_SEC):
            how = ca.ensure_edge(dict(cfg, url=g["url"]))
            if not how:
                return {"ok": False, "why": _edge_why(ca.LAST.get("reason"), "GERP 화면을 열지")}
            tid = ""
            if how == "launched":                          # 방금 띄운 창의 첫 탭이 GERP 화면이다(SSO 로 넘어갔을 수 있다)
                try:
                    tabs = [t for t in ca.http_json(port, "/json") if t.get("type") == "page"]
                    host = gerp.host_of(g["url"])
                    hit = [t for t in tabs if gerp.host_of(t.get("url")) == host or gerp.looks_sso(t.get("url"))]
                    pick = hit[0] if hit else (tabs[0] if len(tabs) == 1 else None)
                    tid = str((pick or {}).get("id") or "")
                except Exception:  # noqa: BLE001
                    tid = ""
            if not tid:
                for method in ("PUT", "GET"):
                    try:
                        t = ca.http_json(port, "/json/new?" + quote(g["url"], safe=""), method=method)
                        tid = str(t.get("id") or "")
                        break
                    except Exception:  # noqa: BLE001
                        continue
            if not tid:
                return {"ok": False, "why": "전용 Edge 에 GERP 화면을 열지 못했습니다"}
            _activate(port, tid)
            return {"ok": True, "why": "전용 Edge 창에 GERP 화면을 열었습니다 — 그 창에서 직접 로그인한 뒤 [GERP 근무 기록 읽기]를 "
                                       "누르세요(이 프로그램은 아이디·비밀번호를 넣거나 저장하지 않습니다)"}
    except Exception as e:  # noqa: BLE001
        if str(getattr(e, "reason", "")) == "R-EDGEBUSY":
            return {"ok": False, "why": "다른 작업이 전용 Edge 를 쓰고 있습니다 — 끝난 뒤 다시 누르세요"}
        return {"ok": False, "why": f"전용 Edge 를 열지 못했습니다({type(e).__name__})"}


# ════════════════════════════════ 명령줄 ════════════════════════════════
def _arg(argv, flag):
    return argv[argv.index(flag) + 1] if flag in argv and argv.index(flag) + 1 < len(argv) else ""


def _load(path):
    try:
        with open(path, encoding="utf-8-sig") as f:
            c = json.load(f)
        return c if isinstance(c, dict) else {}
    except (OSError, ValueError):
        return {}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    cfg_path = _arg(argv, "--config") or os.path.join(ROOT, "config", "config.json")
    data_dir = _arg(argv, "--data-dir") or os.path.join(ROOT, "data")
    g, warns = attendance.norm_gerp(_load(cfg_path))
    for w in warns:
        log("   설정: " + w)
    if "--open" in argv:
        r = open_login(g)
        log("   " + r["why"])
        rc = 0 if r["ok"] else (1 if r.get("skip") else 3)
        emit_status(rc, {"kind": "open" if r["ok"] else ("off" if r.get("skip") else "error")})
        return rc
    st = collect(g, data_dir)
    log("   " + (st.get("why") or ""))
    rc = 0 if st["kind"] == "ok" else (3 if st["kind"] == "error" else 1)
    counts = {"kind": st["kind"], "rows": st["rows"], "gate_days": st["gate_days"]}
    counts.update({k: v for k, v in (st.get("diag") or {}).items() if isinstance(v, (int, float)) and not isinstance(v, bool)})
    emit_status(rc, counts)
    return rc


if __name__ == "__main__":
    sys.exit(main())
