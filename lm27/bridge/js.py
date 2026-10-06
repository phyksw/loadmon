# -*- coding: utf-8 -*-
r"""페이지에서 평가할 JS 조각(B §4.6·§4.8·§4.11·§5.3~§5.7·§12.4, LM24 ``js_*`` 이식).

  · 모든 조각은 머리에 ``/*LM27:<이름>*/`` 표식을 단다 — 가짜 CDP(``tests\bridge\fake_cdp.py``)가 이것으로 처리기를 고른다.
  · 조각은 **값만** 돌려준다(``returnByValue``). 페이지 글을 돌려주는 조각은 답 회수용 ``poll``·``chat_text`` 와
    우리 프롬프트를 확인하는 ``editor_text`` 뿐이다. 신원 확인은 URL·준비 상태·입력창 존재·aria-label 만 본다(B §4.1).
  · 범용 전송 선택자(``button[type='submit']`` 전역)는 쓰지 않는다 — 전송·중지 버튼은 입력창의 작성 영역 안에서 먼저 찾는다.
  · 웹 근거 토글(``env``)은 **읽기만** 한다(누르지 않는다, B §4.11).
"""
from __future__ import annotations

import json
import re

from lm27.bridge import settings as S

_MARK_RX = re.compile(r"^/\*LM27:([a-z_]+)\*/")

# 사용자 메시지 노드 후보(전송 확인·새 채팅 확인용 — 설정 키가 아니라 구조 추정. 못 찾으면 0)
USER_SELECTORS = ("[data-message-author-role='user']", "[data-testid*='user-message' i]",
                  "[data-content='user-message']")
CHAT_ROOTS = ("main", "[role='main']", "body")

_VIS40 = "const vis=el=>{const r=el.getBoundingClientRect();return r.width>40&&r.height>8;};"
_VIS4 = "const vis=el=>{const r=el.getBoundingClientRect();return r.width>4&&r.height>4;};"
_NRM = "const nrm=x=>String(x||'').toLowerCase().replace(/[-\\s._]/g,'');"


def _j(v) -> str:
    return json.dumps(list(v) if isinstance(v, tuple) else v, ensure_ascii=False)


def _wrap(name: str, body: str) -> str:
    return f"/*LM27:{name}*/(function(){{{body}}})()"


def marker(expr: str) -> str:
    """조각 머리 표식의 이름(없으면 '')."""
    m = _MARK_RX.match(str(expr or ""))
    return m.group(1) if m else ""


def identity(input_selectors) -> str:
    """신원 재료: ``{url, ready, input:{found, aria, sel}}``(B §4.6 — 제목·페이지 글은 돌려주지 않는다)."""
    return _wrap("identity", _VIS40 + f"""
const sels={_j(input_selectors)};let found=false,aria='',sel='';
outer:for(const s of sels){{for(const c of document.querySelectorAll(s)){{
  if(vis(c)&&!c.disabled){{found=true;sel=s;aria=(c.getAttribute('aria-label')||'').slice(0,80);break outer;}}}}}}
return {{url:location.href,ready:document.readyState,input:{{found:found,aria:aria,sel:sel}}}};""")


def aadsts() -> str:
    """로그인 화면의 AADSTS 오류 번호(숫자만 — 조건부 액세스 판별, H1). 페이지 글·계정은 돌려주지 않는다. 로그인 호스트에서만 부른다."""
    return _wrap("aadsts", """var t=(document.body&&document.body.innerText)||'';var m=t.match(/AADSTS(\\d{5,6})/);
return m?m[1]:'';""")


def focus_input(input_selectors, aria_labels) -> str:
    """입력창 찾기·포커스(B §5.3.1): 보이는 후보 중 aria-label 일치를 우선. ``window.__lm_input``·``__lm_composer`` 기록."""
    return _wrap("focus_input", _VIS40 + f"""
const sels={_j(input_selectors)},arias={_j(aria_labels)}.map(x=>x.toLowerCase());
const cands=[];
for(const s of sels){{for(const c of document.querySelectorAll(s)){{if(vis(c)&&!c.disabled)cands.push([c,s]);}}}}
if(!cands.length)return {{ok:false,err:'input_not_found'}};
const am=c=>{{const a=(c.getAttribute('aria-label')||'').toLowerCase();return a&&arias.some(x=>a.includes(x));}};
let pick=cands.find(p=>am(p[0]))||cands[0];const el=pick[0];
el.focus();window.__lm_input=el;
let comp=el.closest('form');
if(!comp){{let n=el.parentElement;for(let i=0;i<6&&n;i++){{if(n.querySelector('button')){{comp=n;break;}}n=n.parentElement;}}}}
window.__lm_composer=comp||null;
return {{ok:true,tag:el.tagName,sel:pick[1],aria_match:am(el),composer:!!comp}};""")


def editor_text() -> str:
    return _wrap("editor_text", """const el=window.__lm_input;if(!el)return '';
return el.value!==undefined&&el.tagName!=='DIV'?el.value:(el.innerText||el.textContent||'');""")


def clear_editor() -> str:
    """편집기 비우기 → 남은 글자 수(정리 뒤 확인)."""
    return _wrap("clear_editor", """const el=window.__lm_input;if(!el)return {ok:false,len:-1};el.focus();
if(el.tagName==='TEXTAREA'||el.tagName==='INPUT'){const d=Object.getOwnPropertyDescriptor(el.__proto__,'value');
  if(d&&d.set){d.set.call(el,'');}else{el.value='';}el.dispatchEvent(new Event('input',{bubbles:true}));}
else{try{document.execCommand('selectAll',false,null);document.execCommand('delete',false,null);}catch(e){}
  if((el.innerText||'').trim().length>0){el.textContent='';
    el.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'deleteContentBackward'}));}}
const t=el.value!==undefined&&el.tagName!=='DIV'?el.value:(el.innerText||el.textContent||'');
return {ok:true,len:String(t).trim().length};""")


def insert_fallback(text: str) -> str:
    """``Input.insertText`` 가 안 먹었을 때의 예비: execCommand → 값 직접 설정 + input 이벤트(LM24)."""
    return _wrap("insert_fallback", f"""const el=window.__lm_input;if(!el)return {{ok:false}};el.focus();
const p={_j(text)};
if(el.tagName==='TEXTAREA'||el.tagName==='INPUT'){{const d=Object.getOwnPropertyDescriptor(el.__proto__,'value');
  if(d&&d.set){{d.set.call(el,p);}}else{{el.value=p;}}el.dispatchEvent(new Event('input',{{bubbles:true}}));}}
else{{let done=false;try{{done=document.execCommand('insertText',false,p);}}catch(e){{}}
  if(!done){{el.textContent=p;el.dispatchEvent(new InputEvent('input',{{bubbles:true,inputType:'insertText',data:p}}));}}}}
return {{ok:true}};""")


def click_send(send_labels) -> str:
    """작성 영역 **안에서만** sendLabels aria-label 일치 + 보임 + 사용 가능 버튼을 누른다(B §5.4)."""
    return _wrap("click_send", _VIS4 + f"""
const labels={_j(send_labels)}.map(x=>x.toLowerCase());const comp=window.__lm_composer;
if(!comp)return {{ok:false,why:'no_composer'}};
const b=[...comp.querySelectorAll('button')].filter(vis).find(e=>{{
  const a=(e.getAttribute('aria-label')||'').toLowerCase();return !e.disabled&&a&&labels.some(x=>a.includes(x));}});
if(!b)return {{ok:false,why:'no_button'}};
b.click();return {{ok:true}};""")


def _stop_fn(stop_labels) -> str:
    labels = list(stop_labels)
    partial, exact = (labels[:-2], labels[-2:]) if len(labels) > 2 else (labels, [])
    return (f"const sp={_j(partial)}.map(x=>x.toLowerCase()),se={_j(exact)}.map(x=>x.toLowerCase());"
            "const isStop=e=>{const t=((e.getAttribute('aria-label')||'')+' '+(e.getAttribute('title')||''))"
            ".toLowerCase().trim();return !!t&&(sp.some(x=>t.includes(x))||se.some(x=>t===x));};")


def generating(stop_labels) -> str:
    """생성 중(중지 버튼 보임) — 작성 영역 안 → 없으면 문서 전체. 작성 영역을 못 찾으면 null.
    **fail-open** 이다(못 찾으면 false) — 완료 쪽 판정에 단독으로 쓰지 않는다(B §5.5·§5.6)."""
    return _wrap("generating", _VIS4 + _stop_fn(stop_labels) + """
const comp=window.__lm_composer;if(!comp||!comp.isConnected)return null;
if([...comp.querySelectorAll('button')].filter(vis).some(isStop))return true;
return [...document.querySelectorAll('button')].filter(vis).some(isStop);""")


def poll(stop_labels, assistant_selectors, learned: str = "") -> str:
    """스냅샷 한 번에 ``{gen, n_user, n_asst, last, sel}``(B §5.5). 답 노드 선택자 = 설정 → 학습값 순.
    선택자가 없거나 맞는 노드가 없으면 ``n_asst=-1``·``last=''`` (앵커 폴백)."""
    sels = [s for s in assistant_selectors if s]
    srcs = ["config"] * len(sels)
    if learned:
        sels.append(learned)
        srcs.append("learned")
    return _wrap("poll", _VIS4 + _stop_fn(stop_labels) + f"""
let gen=null;const comp=window.__lm_composer;
if(comp&&comp.isConnected){{gen=[...comp.querySelectorAll('button')].filter(vis).some(isStop)||
  [...document.querySelectorAll('button')].filter(vis).some(isStop);}}
let nu=0;for(const s of {_j(USER_SELECTORS)}){{const n=document.querySelectorAll(s).length;if(n){{nu=n;break;}}}}
const sels={_j(sels)},srcs={_j(srcs)};let na=-1,last='',sel='';
for(let i=0;i<sels.length;i++){{let ns;try{{ns=document.querySelectorAll(sels[i]);}}catch(e){{continue;}}
  if(ns.length){{na=ns.length;last=(ns[ns.length-1].innerText||'').slice(0,{S.LAST_TEXT_CAP});sel=srcs[i];break;}}}}
return {{gen:gen,n_user:nu,n_asst:na,last:last,sel:sel}};""")


def counts(assistant_selectors, learned: str = "") -> str:
    """가벼운 스냅샷 ``{n_user, n_asst}``(전송 확인·새 채팅 확인용 — 글은 돌려주지 않는다)."""
    sels = [s for s in assistant_selectors if s] + ([learned] if learned else [])
    return _wrap("counts", f"""
let nu=0;for(const s of {_j(USER_SELECTORS)}){{const n=document.querySelectorAll(s).length;if(n){{nu=n;break;}}}}
let na=-1;for(const s of {_j(sels)}){{let ns;try{{ns=document.querySelectorAll(s);}}catch(e){{continue;}}
  if(ns.length){{na=ns.length;break;}}}}
return {{n_user:nu,n_asst:na}};""")


def chat_text() -> str:
    """앵커 폴백 전용: 대화 영역 innerText(LM24 ``js_chat_text``)."""
    return _wrap("chat_text", f"""for(const s of {_j(CHAT_ROOTS)}){{const el=document.querySelector(s);
  if(el&&el.innerText&&el.innerText.length>0)return el.innerText;}}
return document.body?document.body.innerText:'';""")


def learn_asst(pledge: str, prompt_head: str) -> str:
    """답 노드 선택자 학습(B §5.5): 서약을 품고 프롬프트 앞부분은 품지 않는 가장 짧은 요소 → 안정 속성 선택자.
    돌려주는 것은 선택자(구조)뿐이다 — 글을 돌려주지 않는다."""
    return _wrap("learn_asst", f"""const pledge={_j(pledge)},head={_j(prompt_head)};
let best=null,bl=Infinity;
for(const el of document.querySelectorAll('body *')){{const t=el.innerText||'';
  if(t.includes(pledge)&&!(head&&t.includes(head))&&t.length<bl){{best=el;bl=t.length;}}}}
if(!best)return {{ok:false}};
const q=v=>"'"+String(v).replace(/'/g,"\\\\'")+"'";let node=best,sel='';
for(let i=0;i<7&&node&&node!==document.body;i++){{
  const tid=node.getAttribute('data-testid');if(tid){{sel='[data-testid='+q(tid)+']';break;}}
  const ar=node.getAttribute('data-message-author-role');if(ar){{sel='[data-message-author-role='+q(ar)+']';break;}}
  const rd=node.getAttribute('aria-roledescription');
  if(node.getAttribute('role')==='article'&&rd){{sel="[role='article'][aria-roledescription="+q(rd)+"]";break;}}
  node=node.parentElement;}}
if(!sel){{const cls=[...best.classList].filter(c=>!/\\d/.test(c)).slice(0,2);
  if(cls.length)sel=best.tagName.toLowerCase()+'.'+cls.map(c=>CSS.escape(c)).join('.');}}
if(!sel)return {{ok:false}};
let ns;try{{ns=document.querySelectorAll(sel);}}catch(e){{return {{ok:false}};}}
const last=ns[ns.length-1];if(!last||!(last.innerText||'').includes(pledge))return {{ok:false}};
return {{ok:true,selector:sel}};""")


def new_chat(labels) -> str:
    """새 채팅 버튼(보이는 첫 것) 클릭(LM24 ``js_new_chat``)."""
    return _wrap("new_chat", _VIS4 + f"""const ls={_j(labels)}.map(x=>x.toLowerCase());
const c=[...document.querySelectorAll('button,a')].filter(vis).filter(e=>{{
  const t=((e.getAttribute('aria-label')||'')+' '+(e.innerText||'')).toLowerCase();return ls.some(x=>t.includes(x));}});
if(!c.length)return {{ok:false}};c[0].click();return {{ok:true}};""")


def _wants(model) -> list:
    """모델 이름 하나 또는 별칭 목록(``settings.model_names``) → 비지 않은 표기 목록."""
    if isinstance(model, list | tuple):
        return [str(m) for m in model if str(m or "").strip()]
    return [str(model)] if str(model or "").strip() else []


def pick_model(model, button_labels) -> str:
    """모델 선택 버튼(aria-label 부분 일치)을 열거나, 이미 그 모델(별칭 중 하나)이면 건너뜀(LM24 ``js_pick_model`` · L11)."""
    return _wrap("pick_model", _VIS4 + _NRM + f"""const want={_j(_wants(model))},bl={_j(button_labels)}.map(x=>x.toLowerCase());
const btns=[...document.querySelectorAll('button')].filter(b=>vis(b)&&bl.some(x=>(b.getAttribute('aria-label')||'').toLowerCase().includes(x)));
if(!btns.length)return {{ok:false,err:'selector_not_found'}};
const btn=btns[0];const cur=((btn.getAttribute('aria-label')||'')+' '+(btn.innerText||'')).trim();
if(want.some(w=>nrm(cur).includes(nrm(w))))return {{ok:true,already:true,cur:cur.slice(0,60)}};
const open=[...document.querySelectorAll("[role='menuitem'],[role='menuitemradio']")].filter(vis).length;
if(open>0)return {{ok:true,opened:true,alreadyOpen:true,cur:cur.slice(0,60)}};
btn.click();return {{ok:true,opened:true,cur:cur.slice(0,60)}};""")


def menu_open() -> str:
    return _wrap("menu_open", _VIS4 + """return {open:[...document.querySelectorAll("[role='menuitem'],[role='menuitemradio']")]
  .filter(vis).length};""")


def pick_model_item(model) -> str:
    """열린 메뉴에서 목표 모델(별칭 중 앞의 것부터) 클릭, 없으면 하위 메뉴 후보를 연다(LM24 ``js_pick_model_item`` · L11)."""
    return _wrap("pick_model_item", _VIS4 + _NRM + f"""const want={_j(_wants(model))};
const nodes=[...document.querySelectorAll("[role='menuitemradio'],[role='menuitem'],[role='option']")].filter(vis);
const txt=e=>(e.innerText||e.getAttribute('aria-label')||'').trim();const wns=want.map(nrm).filter(Boolean);
let hit=null;for(const wn of wns){{hit=nodes.find(e=>nrm(txt(e)).includes(wn));if(hit)break;}}
if(hit){{hit.click();return {{ok:true,picked:txt(hit).slice(0,60)}};}}
const heads=wns.map(wn=>wn.replace(/[0-9].*$/,'')||wn);
const sub=nodes.find(e=>{{const t=nrm(txt(e));if(!t||t.length>40)return false;
  const par=e.getAttribute('aria-haspopup')||e.getAttribute('aria-expanded')!==null||/[›>❯»]/.test(txt(e));
  return par&&heads.some(h=>t.includes(h));}});
if(sub){{sub.click();return {{ok:false,submenu:txt(sub).slice(0,40)}};}}
return {{ok:false,err:'item_not_found',seen:nodes.slice(0,12).map(txt).filter(Boolean).slice(0,8).map(x=>x.slice(0,40))}};""")


def close_menu() -> str:
    return _wrap("close_menu", "document.body.click();return 1;")


def _mode_fn(work_labels, web_labels, toggle_labels=()) -> str:
    """업무 모드 판별 함수 ``modeState(click)`` 정의. ① 업무·웹 버튼 한 쌍(이름표 정확 일치 — 옛 화면) ② 없으면 단일 토글
    'Work IQ'(이름표 부분 일치 — 2026-08 개편, H13): 누름 상태 aria-pressed·aria-checked·aria-selected(또는 체크 상자)가 true 면
    work, false 면 web, 속성이 없으면 unknown. ``click`` 이면 꺼진 쪽만 한 번 누른다(상태를 모르면 누르지 않는다)."""
    return (_VIS4 + f"const wl={_j(work_labels)}.map(x=>x.toLowerCase()),bl={_j(web_labels)}.map(x=>x.toLowerCase()),"
            f"tl={_j(toggle_labels)}.map(x=>x.toLowerCase());"
            "const lab=e=>[(e.getAttribute('aria-label')||'').trim().toLowerCase(),(e.innerText||'').trim().toLowerCase()];"
            "const q=\"button,[role='tab'],[role='radio'],[role='switch'],[role='menuitemradio']\";"
            "const els=[...document.querySelectorAll(q)].filter(vis);"
            "const fw=els.find(e=>lab(e).some(t=>wl.includes(t)));const fb=els.find(e=>lab(e).some(t=>bl.includes(t)));"
            "const ATTRS=['aria-pressed','aria-checked','aria-selected'];"
            "const on=e=>!!e&&ATTRS.some(a=>e.getAttribute(a)==='true');"
            "const has=e=>!!e&&ATTRS.some(a=>e.getAttribute(a)!==null);"
            "const tq=\"button,[role='switch'],[role='checkbox'],[role='menuitemcheckbox'],input[type='checkbox']\";"
            "const ft=(fw||fb||!tl.length)?null:[...document.querySelectorAll(tq)].filter(vis).find(e=>{"
            "const t=((e.getAttribute('aria-label')||'')+' '+(e.innerText||'')+' '+(e.getAttribute('title')||''))"
            ".toLowerCase();return tl.some(x=>t.includes(x));});"
            "const tst=e=>{if(!e)return null;for(const a of ATTRS){const v=e.getAttribute(a);if(v==='true')return true;"
            "if(v==='false')return false;}if(e.tagName==='INPUT'&&typeof e.checked==='boolean')return e.checked;return null;};"
            "const modeState=click=>{let clicked=false;"
            "if(fw||fb){if(click&&fw&&!on(fw)){fw.click();clicked=true;}"
            "return {found:true,kind:'pair',stateful:has(fw)||has(fb),mode:on(fw)?'work':(on(fb)?'web':'unknown'),"
            "work:on(fw),web:on(fb),clicked:clicked};}"
            "if(ft){const s=tst(ft);if(click&&s===false){ft.click();clicked=true;}"
            "return {found:true,kind:'toggle',stateful:s!==null,mode:s===true?'work':(s===false?'web':'unknown'),"
            "work:s===true,web:s===false,clicked:clicked};}"
            "return {found:false,kind:'',stateful:false,mode:'unknown',work:false,web:false,clicked:false};};")


def work_mode(work_labels, web_labels, click_work: bool = False, toggle_labels=()) -> str:
    """업무 모드 상태 ``{found, kind(pair|toggle|''), stateful, mode, work, web, clicked}``. ``click_work`` 면 업무 쪽(쌍)·꺼진
    토글을 1회 누른다(B §4.8 · H13)."""
    return _wrap("work_mode", _mode_fn(work_labels, web_labels, toggle_labels) + f"""
const CLICK={'true' if click_work else 'false'};
return modeState(CLICK);""")


def env(work_labels, web_labels, wg_labels, toggle_labels=(), account_labels=(), shield_labels=()) -> str:
    """계정 등급·업무 모드·웹 근거·회사 계정 표시 판별 재료(B §4.11 · H4·H13·L11) —
    ``{toggle:{found, kind, stateful, work, web}, wg:{found, checked}, acct:{label, shield}, tier}``. **읽기만** 한다(누르지
    않고 설정 메뉴도 열지 않는다). 회사(Entra) 계정 표시 = 탐색 창·머리 영역의 짧은 'Work' 표시(정확 일치) 또는 데이터 보호
    방패의 aria-label·title(부분 일치). 등급 = 'copilot' 이 든 짧은 글의 '(Premium)'·'(Basic)'. 글은 돌려주지 않는다(참·거짓만)."""
    tiers = {k: list(v) for k, v in S.TIER_LABELS.items()}
    return _wrap("env", _mode_fn(work_labels, web_labels, toggle_labels) + f"""
const gl={_j(wg_labels)}.map(x=>x.toLowerCase());
const wq="[role='switch'],[role='menuitemcheckbox'],[role='checkbox'],input[type='checkbox']";
const wg=[...document.querySelectorAll(wq)].filter(vis).find(e=>{{
  const t=((e.getAttribute('aria-label')||'')+' '+(e.innerText||'')).toLowerCase();return gl.some(x=>t.includes(x));}});
let checked=null;
if(wg){{const a=wg.getAttribute('aria-checked');if(a==='true')checked=true;else if(a==='false')checked=false;
  else if(typeof wg.checked==='boolean')checked=wg.checked;}}
const al={_j(account_labels)}.map(x=>x.toLowerCase().trim()),sl={_j(shield_labels)}.map(x=>x.toLowerCase());
let acct=false;
if(al.length){{outer:for(const r of document.querySelectorAll("nav,aside,header,[role='navigation'],[role='banner'],[role='complementary']")){{
  for(const e of r.querySelectorAll('*')){{if(e.children.length)continue;
    const t=(e.innerText||e.textContent||'').trim().toLowerCase(),a=(e.getAttribute('aria-label')||'').trim().toLowerCase();
    if((t&&t.length<=20&&al.includes(t))||(a&&al.includes(a))){{acct=true;break outer;}}}}}}}}
let shield=false;
if(sl.length){{for(const e of document.querySelectorAll('[aria-label],[title]')){{
  const t=((e.getAttribute('aria-label')||'')+' '+(e.getAttribute('title')||'')).toLowerCase();
  if(sl.some(x=>t.includes(x))){{shield=true;break;}}}}}}
const tp={_j(tiers)};let tier='';
for(const e of document.querySelectorAll('span,div,p,a,button,h1,h2,h3,h4')){{if(e.children.length)continue;
  const t=(e.innerText||'').trim().toLowerCase();if(!t||t.length>40||!t.includes('copilot'))continue;
  if(tp.premium.some(x=>t.includes(x))){{tier='premium';break;}}if(tp.basic.some(x=>t.includes(x))){{tier='basic';break;}}}}
const m=modeState(false);
return {{toggle:{{found:m.found,kind:m.kind,stateful:m.stateful,work:m.work,web:m.web}},wg:{{found:!!wg,checked:checked}},
  acct:{{label:acct,shield:shield}},tier:tier}};""")


def diagnose(input_selectors, keep_labels) -> str:
    """화면 구조 진단(B §12.4) — 페이지 글은 형식 보존 마스킹(한글→가·영문→x·숫자→0, 앞 40자).
    aria-label 은 입력창·작성 영역 버튼·설정 라벨 목록에 있는 문구·모델 메뉴 항목만 원문, 나머지는 마스킹."""
    return _wrap("diagnose", _VIS4 + f"""
const mask=s=>String(s||'').slice(0,40).replace(/[가-힣]/g,'가').replace(/[A-Za-z]/g,'x').replace(/[0-9]/g,'0');
const keep={_j(keep_labels)}.map(x=>x.toLowerCase());
const kept=a=>keep.some(x=>String(a||'').toLowerCase().includes(x));
const cls=e=>[...(e.classList||[])].filter(c=>!/\\d/.test(c)).slice(0,4);
const r=e=>e.getBoundingClientRect();
const editors=[];for(const s of {_j(input_selectors)}){{for(const e of document.querySelectorAll(s)){{
  if(editors.length>=10)break;editors.push({{tag:e.tagName,role:e.getAttribute('role')||'',aria:(e.getAttribute('aria-label')||'').slice(0,80),
  testid:e.getAttribute('data-testid')||'',visible:r(e).width>0&&r(e).height>0,w:Math.round(r(e).width)}});}}}}
const comp=window.__lm_composer;
const cb=comp?[...comp.querySelectorAll('button')].slice(0,20).map(b=>({{aria:(b.getAttribute('aria-label')||'').slice(0,60),
  testid:b.getAttribute('data-testid')||'',disabled:!!b.disabled}})):[];
const stop=[...document.querySelectorAll('button')].filter(vis).filter(b=>kept(b.getAttribute('aria-label'))).slice(0,10)
  .map(b=>({{aria:(b.getAttribute('aria-label')||'').slice(0,60)}}));
const msgs=[...document.querySelectorAll("[role='article'],[data-testid],[data-message-author-role]")].slice(-{S.DIAG_MAX_NODES}).map(e=>({{
  tag:e.tagName,role:e.getAttribute('role')||'',testid:e.getAttribute('data-testid')||'',cls:cls(e),
  children:e.children.length,text_len:(e.innerText||'').length,text_mask:mask(e.innerText)}}));
const menu=[...document.querySelectorAll("[role='menuitem'],[role='menuitemradio']")].filter(vis).slice(0,12)
  .map(e=>(e.innerText||e.getAttribute('aria-label')||'').trim().slice(0,40));
const others=[...document.querySelectorAll('button')].filter(vis).slice(0,40).map(b=>{{const a=b.getAttribute('aria-label')||'';
  return {{aria:kept(a)?a.slice(0,60):mask(a),testid:b.getAttribute('data-testid')||''}};}});
return {{url_host:location.hostname,url_path:location.pathname,ready:document.readyState,editors:editors,
  composer_buttons:cb,stop_candidates:stop,message_candidates:msgs,model_menu:menu,buttons:others}};""")


ALL = ("identity", "focus_input", "editor_text", "clear_editor", "insert_fallback", "click_send", "generating", "poll",
       "counts", "chat_text", "learn_asst", "new_chat", "pick_model", "menu_open", "pick_model_item", "close_menu",
       "work_mode", "env", "diagnose", "aadsts")
