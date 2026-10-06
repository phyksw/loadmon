# -*- coding: utf-8 -*-
r"""teams.web — Teams 웹 백필 수집기(CT §8 · §11 · §12 · §14.3 · §15, 계약 §2.17 · §3.10 · §6.5 · §7.3 · X-023 · X-140 ·
X-148 · X-184). 백필 PC(기본 클라우드PC)에서만, 기간 전체를 읽는다. 본인 전용 Edge 프로필은 ``lm27.bridge.session.
EdgeSession.open(role="teams_web")`` 하나로만 연다(Edge 인자·프로필·포트 설정 없음 — G-B12 · L-16). 사용자 대신 로그인하지
않는다(로그인 필요 → rc 2 + R-LOGIN, 로그인 전 '불가' 확정 0).

    "<PY>" -X utf8 -I -B collect\Get-TeamsWeb.py --pc <pc_id> [--from D --to D] [--max-chats N] [--budget-sec N]
           [--no-channels] [--no-activity] [--force] [--run-id <run_id>] [--events jsonl|text|off]

설정(계약 §5.2 — owner 이 스크립트): ``teams.web.maxChats``(0 = 예산 안 무제한) · ``teams.web.budgetSec``(900) ·
``teams.web.maxScroll``(대화당 되감기 12) · ``teams.web.includeChannels`` · ``teams.web.includeActivity``. 명령줄
``--max-chats``·``--budget-sec`` 가 설정보다 앞서고 ``--no-channels``·``--no-activity`` 는 끈다. ``--force`` = 체크포인트를 무시하고
기간 전체(X-140). 기간 기본값 = 오늘 − ``collect.lookbackDays`` ~ 오늘(로컬).

읽는 방법(CT §8.2 · §8.3 · §14.3 이전 판 수정표):
  · 채팅 목록을 **가상 스크롤로 끝까지** 순회한다(렌더된 항목·상한 40 의 이전 판 결함 수정). 끝에 못 닿으면 R-LISTVIRT(partial).
    ``--include-channels``(기본 켬)이면 채널 글타래, ``--include-activity``(기본 켬)이면 활동(멘션) 피드도 — 활동 항목은
    읽을 대화방을 알려 주는 표지로만 쓴다(미리보기를 레코드로 만들지 않는다 — 잘린 미리보기가 같은 메시지를 두 번 세지 않게).
  · 대화방은 **대화 ID 로 다시 찾아** 연다(요소 핸들·순번이 아님 — 재렌더 'gone' 대응). 못 찾은 방만 R-ROOMGONE(그 방만 건너뜀,
    경로 전체 실패 아님). 선택자를 여러 벌 두고 '무엇으로 몇 개를 잡았는지' 숫자만 남긴다. 화면 구조를 하나도 못 알아보면
    R-WEBSEL(rc 3).
  · 메시지마다 ``data-mid``(메시지 ID)와 ``<time datetime>``(UTC)을 1순위로 — 있으면 ts_precision exact. 없으면 머리 조각
    (시각 표시·title·aria-label)과 날짜 구분선에서 minute, 날짜만이면 date, 날짜를 끝내 못 짚으면 unknown 으로 **격리해 넘긴다**
    (ts_utc = 수집일 00:00 로컬의 자리값 — 계약 v1.2 C7, 시간 근거 아님). 본문에 적힌 날짜는 쓰지 않는다.
  · 작성자 없는 연속 메시지는 직전 작성자를 상속(flags.author_inherited · confidence 0.3), 끝내 불명이면 is_me = null(수신 단정
    금지). 방향은 구조 단서(내 말풍선) → 본인 표시명 집합(``lm27.privacy.sanitize.make_record_context`` 의 레코드 문맥 —
    ``self_name_set`` 단일원, X-306) 순. 대화 유형은 대화 ID 모양·구조 단서로만(쉼표 수·방 이름 금지), 미상이면 정제기가
    group + n_part_est. 1:1 방 이름(= 상대 이름)은 넘기지 않는다.
  · 같은 방 화면 회차 사이 중복은 메시지 ID, 없으면 **날짜를 넣은** 키(날짜·시각·작성자·본문 해시)로 흡수한다 — 매일 같은
    시각의 정형 메시지가 하루치로 뭉개지지 않게(CT-6, 이전 판 결함). 저장 행의 msg_key 는 정제기가 정제 전 원문으로 만든다
    (``tid:<메시지 ID>`` 우선, 없으면 날짜 포함 대체 재료 — P §9.3).
  · 시간 예산(``--budget-sec``) 안에 **반드시 저장까지** 끝낸다: 방마다 정제·저장(gzip 멤버 1개)·체크포인트를 남기고,
    예산이 다 되면 남은 방을 다음 실행으로 미룬다(partial + budget_hit + R-BUDGET).

체크포인트(계약 §3.10 · X-023): ``raw_cursor.json`` 의 ``teams.web`` = ``{"rooms": {<chat_key>: {"last_msg_key", "oldest_done",
"newest_done"}}}`` — 원 대화 ID 를 키로 쓰지 않고 정제기가 만든 chat_key(HMAC)를 쓴다. [oldest_done, newest_done] = 그 방을
끝까지 읽은 로컬 날짜 구간. 다음 실행은 방마다 그 구간 **밖만** 읽는다: 맨 아래(최신)부터 newest_done 날까지 새 메시지를 읽고,
oldest_done 이 기간 시작보다 늦으면 읽은 구간을 건너 더 오래된 쪽을 마저 읽는다(건너는 회차는 ``teams.web.maxScroll`` 에
세지 않는다). 커서는 그 방의 ``SegmentWriter.flush()`` 성공 뒤에만 저장한다.

rc(계약 §8.1): 0 새 메시지 저장 · 1 대화·메시지 0건 · 2 로그인 필요(R-LOGIN · R-CA) · 3 드라이버 불가·불완전(R-EDGEPOL ·
R-NOAPP · R-WEBSEL · R-TRANSPORT) · 4 읽었지만 새 메시지 0. ``--max-chats`` 상한에 닿으면 partial + cap_hit + R-CAP.
상태(계약 v1.2 C1): stderr 마지막 줄 ``{"_status": {schema, src, rc, reasons[], partial, cap_hit, budget_hit, n, counts{}}}``.

시험 주입(계약 §11.3 — 형식은 ``tests\fixtures\synth\inject.py`` 머리 표): ``LM_TEAMSWEB_FAKE=<json>`` =
``{"login": bool|"ca", "chats": {how, n, items:[{idx, label, texts, tid}]}, "msgs": {"<idx>": [{how, chat, n,
items:[{t:"sep", text} | {t:"msg", label, author, ts, iso[], titles[], body, texts[], mid}]}, …(스크롤 회차)]}}``.
이 수집기가 더 받는 선택 키: ``chats`` 를 화면 목록(가상 스크롤 회차)으로 · ``"chats_end": false``(목록 끝에 못 닿음) ·
``channels``·``activity``(같은 목록 모양, 활동 항목은 ``tid``·``mid``·``mention``) · 방 항목 ``gone: true``(재탐색 실패) ·
메시지 ``me``(구조상 내 말풍선)·``files``·``mentions``. ``LM_NO_BROWSER=1`` 이면 Edge 를 띄우지 않는다(rc 3).
날짜·시각 해석·상태 줄·정제·저장·커서 묶음은 같은 폴더의 ``Get-OutlookWeb.py`` 를 경로로 불러 쓴다.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)   # L-05 · 계약 §9.1 — collect\*.py 는 첫 실행문에서 자기 루트를 넣는다

import argparse
import importlib.util
import json
import re
from datetime import UTC, date, datetime, timedelta
from urllib.parse import quote

from lm27.bridge.clock import default_clock
from lm27.util import events, tz


def _sibling(fname: str, modname: str):
    """같은 폴더의 수집기 스크립트를 모듈로 불러온다(파일 이름에 '-' 가 있어 import 문을 쓸 수 없다)."""
    m = sys.modules.get(modname)
    if m is not None:
        return m
    spec = importlib.util.spec_from_file_location(modname, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                                        fname))
    m = importlib.util.module_from_spec(spec)
    sys.modules[modname] = m
    spec.loader.exec_module(m)
    return m


W = _sibling("Get-OutlookWeb.py", "lm27_collect_owa_web")

# ───────────────────────────── 상수 ─────────────────────────────
KIND = "teams"
SRC = "teams.web"
STAGE = "backfill_teams_web"
ROLE = "teams_web"
FAKE_ENV = "LM_TEAMSWEB_FAKE"
TEAMS_URL = "https://teams.microsoft.com/v2/"
DEEP_LINK = "https://teams.microsoft.com/l/message/{tid}/{mid}"
TEAMS_HOST_RX = re.compile(r"^teams\.microsoft\.com$|^teams\.cloud\.microsoft$|^teams\.live\.com$")
LISTS = ("chats", "channels", "activity")
NAV_LABELS = {"chats": ("채팅", "chat"), "channels": ("팀", "teams"), "activity": ("활동", "activity")}
LIST_ROUNDS_MAX = 300        # 목록 가상 스크롤 회차 상한(정지 판정이 먼저 끊는다)
LIST_STALL = 3               # 스크롤은 되는데 새 항목이 안 나오는 회차 — 가상 목록 정체(R-LISTVIRT)
ROOM_STALL = 2               # 두 번 되감아 새 메시지 0 이면 그 방은 여기까지(CT §8.3)
SKIP_ROUNDS_MAX = 200        # 읽은 구간을 건너는 회차 상한(예산이 먼저 끊는다)
PANE_WAIT_S = 2.5            # 대화 열기·되감기 뒤 화면 바뀜 대기(고정 sleep 금지 — 바뀌면 바로)
PANE_POLL_S = 0.25
ROOMS_MAX = 5000             # 체크포인트 방 수 상한(오래 안 본 방부터 뺀다)
CONF_EXACT, CONF_INHERITED, CONF_DATE, CONF_UNKNOWN = 0.8, 0.3, 0.4, 0.3   # 계약 §3.4
SELF_FIXED = ("나", "본인", "you", "me")
FILE_RX = re.compile(r"\.[A-Za-z0-9]{1,5}$")
AUTHOR_RX = re.compile(r"^\s*([^\d,|]{2,20}?)\s*(?:님이|님|씨)?\s*(?:,|said|says|wrote|은|는)\b")
SELF_ROOM_RX = re.compile(r"\((?:나|you|me)\)\s*$", re.I)
ISO_RX = re.compile(r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.\d{1,9})?)?\s*(Z|[+-]\d{2}:?\d{2})?$")


def chat_type_of(tid: str, label: str = "", ctype: str = "") -> str:
    """대화 유형 — 구조로만(대화 ID 모양 · 화면 구조 단서). 쉼표 수·방 이름으로 판정하지 않는다(CT §4.2)."""
    if ctype in ("1:1", "group", "channel", "meeting", "self"):
        return ctype
    t = str(tid or "")
    if t.startswith("48:notes") or SELF_ROOM_RX.search(str(label or "")):
        return "self"
    if t.startswith("19:meeting_"):
        return "meeting"
    if t.endswith(("@thread.tacv2", "@thread.skype")):
        return "channel"
    if t.endswith("@unq.gbl.spaces"):
        return "1:1"
    if t.endswith("@thread.v2"):
        return "group"
    return "unknown"


def norm_name(n) -> str:
    """본인 이름 비교용 정규화(메모리): NFKC · 소문자 · 괄호 안 · '/' 뒤 부서 · 공백·구분자 · 님/씨 꼬리 제거."""
    x = W.nfkc(n).lower()
    x = re.sub(r"\(.*?\)|\[.*?\]", "", x).split("/", 1)[0]
    x = re.sub(r"[\s.\-_·]", "", x)
    return re.sub(r"(?:님|씨)$", "", x)


def parse_iso(v):
    """``<time datetime>`` 값 → aware UTC(초 단위) 또는 None. 시간대 표기가 없으면 UTC 로 본다(웹은 Z 로 준다)."""
    m = ISO_RX.match(str(v or "").strip())
    if not m:
        return None
    y, mo, d, hh, mi, ss, z = m.groups()
    try:
        dt = datetime(int(y), int(mo), int(d), int(hh), int(mi), int(ss or 0), tzinfo=UTC)
    except ValueError:
        return None
    if z and z != "Z":
        t = z.replace(":", "")
        off = (1 if t[0] == "+" else -1) * (int(t[1:3]) * 60 + int(t[3:5]))
        dt -= timedelta(minutes=off)
    return dt


def _looks_file(x: str) -> bool:
    s = str(x or "").strip()
    return bool(FILE_RX.search(s)) and not W.is_datetime_text(s) and 1 < len(s) <= 160


def author_of(it: dict, texts: list) -> str:
    """작성자 — 구조(작성자 요소)가 먼저, 없으면 aria-label 의 첫 토큰, 그다음 맨 앞 짧은 글자(이전 판 이식)."""
    a = str(it.get("author") or "").strip()
    if 1 < len(a) <= 40:
        return a
    m = AUTHOR_RX.match(str(it.get("label") or ""))
    if m:
        a = m.group(1).strip()
        if 1 < len(a) <= 40 and not W.find_times(a):
            return a
    return ""


def body_of(it: dict, texts: list, author: str, ts: str) -> str:
    """본문 — 구조(본문 요소)가 먼저('넵' 한 글자도 본문이다), 없으면 작성자·시각 표시를 뺀 잎 글자."""
    b = str(it.get("body") or "").strip()
    if b:
        return b
    drop = {norm_name(author), norm_name(ts)}
    out = [s for s in texts if s.strip() and norm_name(s) not in drop and not W.is_datetime_text(s)]
    return re.sub(r"\s{2,}", " ", " ".join(out)).strip()


# ───────────────────────────── 메시지 화면 해석 ─────────────────────────────
def parse_pages(pages: list, *, today: date, d0: date, d1: date, off_fn) -> list:
    """방 하나의 화면 회차들(읽은 순서 = 최신 먼저) → 메시지 목록(오래된 것 먼저, 같은 방 안 중복 제거).
    날짜 구분선·직전 작성자는 회차 안에서 이어 가고, 앞 회차와 겹치는 첫 메시지가 있으면 그 문맥을 이어받는다."""
    out, seen = [], set()
    ctx_of = {}                                         # 날짜 없는 식별자 → (구분선 날짜, 작성자) — 회차 이음용
    for page in reversed(pages):
        items = [x for x in (page or {}).get("items") or [] if isinstance(x, dict)]
        cur, last_author = None, ""
        first = next((x for x in items if x.get("t") == "msg"), None)
        if first is not None:
            got = ctx_of.get(_ident(first))
            if got is not None:
                cur, last_author = got
        for it in items:
            if it.get("t") == "sep":
                txt = str(it.get("text") or "")
                d = W.date_in(txt, d0, d1, today, weak=W.is_datetime_text(txt)) or W.rel_date(txt, today)
                if d:
                    cur = d
                continue
            if it.get("t") != "msg":
                continue
            m = parse_msg(it, cur=cur, last_author=last_author, today=today, d0=d0, d1=d1, off_fn=off_fn)
            ctx_of[m["ident"]] = (cur, m["author"] or last_author)
            if m["author"]:
                last_author = m["author"]
            if m["key"] in seen:
                continue
            seen.add(m["key"])
            out.append(m)
    return out


def _ident(it: dict) -> str:
    """날짜 없는 식별자(회차 이음·정지 판정용) — 메시지 ID, 없으면 시각 표시·작성자·본문·라벨 해시."""
    mid = str(it.get("mid") or "").strip()
    if mid:
        return "mid:" + mid
    return "h:" + W.sha16([str(it.get("ts") or ""), str(it.get("author") or ""), str(it.get("body") or "")[:120],
                           str(it.get("label") or "")[:80]])


def parse_msg(it: dict, *, cur, last_author: str, today: date, d0: date, d1: date, off_fn) -> dict:
    """메시지 하나 → 해석 dict(메모리). 시각: ``<time datetime>`` → exact, 머리 조각·구분선 → minute, 날짜만 → date, 없음 → unknown."""
    texts = [str(x) for x in it.get("texts") or [] if x]
    ts_text = str(it.get("ts") or "")
    titles_all = [str(x) for x in it.get("titles") or [] if x]
    files = [str(x) for x in it.get("files") or [] if x] or [x for x in titles_all if _looks_file(x)]
    titles = [x for x in titles_all if x not in files]
    # 머리 조각: 시각 표시 + (날짜·시각만인) title·aria-label 조각 — aria-label·링크 title 에는 본문이 섞이므로
    # 날짜·시각만인 조각만 쓴다(본문 속 '9월 3일 오전 10시까지'를 메시지 시각으로 읽지 않게)
    head = [ts_text] + [x for x in titles + W.frags_of(it.get("label") or "") if W.is_datetime_text(x)]
    when = None
    for v in it.get("iso") or []:
        when = parse_iso(v)
        if when:
            break
    precision, day, hm = "unknown", None, None
    if when is not None:
        precision, day, hm = "exact", W.local_date_of(when, off_fn), None
    else:
        w = W.parse_when(head, d0, d1, today, bare_today=False)
        if w and w[1]:
            precision, day, hm = "minute", w[0], w[1]
        else:
            hm = next((W.find_times(x)[0] for x in [ts_text] + texts[:3] if W.is_datetime_text(x) and W.find_times(x)),
                      None)
            day = w[0] if w else cur
            if day and hm:
                precision = "minute"
            elif day:
                precision = "date"
    author = author_of(it, texts)
    inherited = False
    if not author and last_author:
        author, inherited = last_author, True
    body = body_of(it, texts, author, ts_text)
    ident = _ident(it)
    mid = str(it.get("mid") or "").strip()
    key = ("mid:" + mid) if mid else W.sha16([day.isoformat() if day else "?", list(hm) if hm else "?",
                                             norm_name(author), body[:400]])
    me = it.get("me") if isinstance(it.get("me"), bool) else None
    return {"ident": ident, "key": key, "mid": mid, "when": when, "day": day, "hm": hm, "precision": precision,
            "author": author, "inherited": inherited, "body": body, "files": files[:10],
            "mentions": [str(x) for x in it.get("mentions") or [] if x][:5], "me": me,
            "reply_to": str(it.get("reply_to") or "") or None}


def page_dates(page: dict, *, today: date, d0: date, d1: date, off_fn) -> tuple:
    """화면 한 장의 (식별자 집합, 가장 오래된 날짜) — 되감기 판단용(회차 안 문맥만)."""
    msgs = parse_pages([page], today=today, d0=d0, d1=d1, off_fn=off_fn)
    days = [m["day"] for m in msgs if m["day"]]
    return {m["ident"] for m in msgs}, (min(days) if days else None)


# ───────────────────────────── 화면 읽기 JS ─────────────────────────────
_SELS = {
    "chats": ['[data-tid="chat-list"] [data-tid="chat-list-item"]', '[data-tid="chat-list-item"]',
              '[data-tid="chat-list"] [role="treeitem"]', '[role="tree"] [role="treeitem"]',
              '[role="list"] [role="listitem"][data-tid]', '[role="listbox"] [role="option"]'],
    "channels": ['[data-tid="team-channel-list"] [role="treeitem"]', '[data-tid*="channel-list-item"]',
                 '[role="tree"] [role="treeitem"][aria-level="2"]'],
    "activity": ['[data-tid="activity-feed"] [role="listitem"]', '[data-tid*="activity-feed-item"]',
                 '[role="feed"] [role="article"]'],
}
_ID_FN = ("var idOf=function(e){var c=[e.getAttribute('data-item-key'),e.getAttribute('data-conversation-id'),"
          "e.getAttribute('data-chat-id'),e.getAttribute('data-tid'),e.id];var a=e.querySelector('a[href*=\"/l/\"]');"
          "if(a)c.push(a.getAttribute('href'));for(var i=0;i<c.length;i++){var v=c[i]||'';try{v=decodeURIComponent(v);}"
          "catch(x){}var m=v.match(/(19:[^\\s\\/?#\"']+@[A-Za-z0-9.\\-]+|48:notes)/);if(m)return m[1];}return '';};"
          "var midOf=function(e){var a=e.querySelector('a[href*=\"/l/message/\"]');var h=a?(a.getAttribute('href')||''):'';"
          "var m=h.match(/\\/l\\/message\\/[^\\/]+\\/(\\d{6,})/);return m?m[1]:(e.getAttribute('data-mid')||'');};")


def _sel_js(which: str) -> str:
    return "var SELS=" + json.dumps(_SELS.get(which, []), ensure_ascii=False) + ";"


def js_tw_list(which: str) -> str:
    return W._js("tw_list", W._LEAF + _ID_FN + _sel_js(which) + f"""
var which={json.dumps(which)};var els=[],how='';
for(var i=0;i<SELS.length;i++){{els=Array.prototype.slice.call(document.querySelectorAll(SELS[i]));if(els.length){{how=SELS[i];break;}}}}
window['__lm_'+which]=els;
return {{how:how,n:els.length,items:els.slice(0,400).map(function(e,i){{
 var l=cut(e.getAttribute('aria-label')||e.getAttribute('title'),300);
 return {{idx:i,tid:idOf(e),mid:which==='activity'?midOf(e):'',label:l,texts:leafs(e,8),mention:/멘션|mention|@/i.test(l)}};}})}};""")


def js_tw_list_scroll(which: str) -> str:
    return W._js("tw_list_scroll", f"""
var els=window['__lm_'+{json.dumps(which)}]||[];var el=els.length?els[0]:null;
for(var i=0;i<14&&el;i++){{if(el.scrollHeight>el.clientHeight+20&&getComputedStyle(el).overflowY!=='visible')break;el=el.parentElement;}}
if(!el)return 'no-scroller';
var before=el.scrollTop;el.scrollTop=el.scrollTop+Math.max(200,el.clientHeight-60);
el.dispatchEvent(new Event('scroll',{{bubbles:true}}));return el.scrollTop>before?'scrolled':'end';""")


def js_tw_open(which: str, tid: str, idx: int) -> str:
    """대화 ID 로 목록 항목을 다시 찾아 연다(없으면 'gone'). ID 가 없을 때만 순번."""
    return W._js("tw_open", _ID_FN + _sel_js(which) + f"""
var which={json.dumps(which)},tid={json.dumps(tid or "")},idx={int(idx)};
var pick=function(els){{for(var i=0;i<els.length;i++){{if(tid&&idOf(els[i])===tid)return els[i];}}return null;}};
var t=null;var els=window['__lm_'+which]||[];
if(tid){{t=pick(els);if(!t||!t.isConnected){{for(var k=0;k<SELS.length&&!t;k++){{t=pick(document.querySelectorAll(SELS[k]));}}}}}}
else{{t=els[idx]||null;}}
if(!t||!t.isConnected)return 'gone';
try{{t.scrollIntoView({{block:'center'}});}}catch(x){{}}
var b=t.querySelector('[role="button"],a,button')||t;
var evs=['pointerdown','mousedown','pointerup','mouseup','click'];
for(var j=0;j<evs.length;j++){{b.dispatchEvent(new MouseEvent(evs[j],{{bubbles:true,cancelable:true,view:window}}));}}
return 'ok';""")


def js_tw_msgs() -> str:
    """대화 화면 한 장: 구분선·메시지(작성자·시각 표시·<time datetime>·title·본문·잎 글자·메시지 ID·내 말풍선·파일·멘션)."""
    return W._js("tw_msgs", W._LEAF + """
var out={how:'',chat:'',n:0,items:[],ctype:'',n_part:null};
var MSG=['[data-tid="chat-pane-item"]','[data-tid="chat-pane-message"]','[data-tid="message-pane"] [role="listitem"]','[role="log"] [role="listitem"]','[role="main"] [role="listitem"]'];
var SEP='[role="separator"],[data-tid*="divider"]';
var msel='';for(var i=0;i<MSG.length;i++){if(document.querySelector(MSG[i])){msel=MSG[i];break;}}
if(!msel)return out;out.how=msel;
var head=document.querySelector('[data-tid="chat-header-title"],[data-tid="chatTitle"],[data-tid="chat-header"] [role="heading"],[role="main"] h1');
out.chat=head?cut((head.getAttribute('title')||head.textContent||'').trim(),120):'';
var href=location.href||'';
if(/thread\\.tacv2|\\/channel\\//i.test(href))out.ctype='channel';else if(/meeting_/i.test(href))out.ctype='meeting';
var r=document.querySelector('[data-tid*="roster"],[data-tid*="participant"]');
if(r){var m=((r.getAttribute('aria-label')||'')+' '+(r.textContent||'')).match(/(\\d{1,5})/);if(m)out.n_part=parseInt(m[1],10);}
var all=document.querySelectorAll(msel+','+SEP);
for(var j=0;j<all.length;j++){var e=all[j];
 if(!e.matches(msel)){var s=(e.textContent||'').trim();if(s&&s.length<=60)out.items.push({t:'sep',text:s});continue;}
 var au=e.querySelector('[data-tid="message-author-name"],[data-tid="messageAuthorName"]');
 var ts=e.querySelector('[data-tid="message-timestamp"],time');
 var bd=e.querySelector('[data-tid="messageBodyContent"],[id^="content-"]');
 var mid=e.getAttribute('data-mid')||'';if(!mid&&bd&&bd.id){var mm=/^content-(\\d+)/.exec(bd.id);if(mm)mid=mm[1];}
 var cls=(e.className&&e.className.baseVal!==undefined)?e.className.baseVal:(e.className||'');
 var mine=/ChatMyMessage|message-mine/i.test(cls)||!!e.querySelector('[class*="ChatMyMessage"]');
 var other=!mine&&(/ChatMessage/i.test(cls)||!!e.querySelector('[class*="ChatMessage"]'));
 out.items.push({t:'msg',label:cut(e.getAttribute('aria-label'),400),author:au?(au.textContent||'').trim():'',
  ts:ts?((ts.getAttribute('title')||ts.getAttribute('datetime')||ts.textContent||'').trim()):'',
  iso:Array.prototype.slice.call(e.querySelectorAll('time[datetime]')).map(function(x){return x.getAttribute('datetime');}).filter(function(x){return x;}).slice(0,3),
  titles:titles(e,6),body:bd?cut((bd.textContent||'').trim(),1200):'',texts:leafs(e,20),mid:mid,
  me:mine?true:(other?false:null),
  files:Array.prototype.slice.call(e.querySelectorAll('[data-tid*="file"] [title],[data-tid*="attachment"] [title]')).map(function(x){return (x.getAttribute('title')||'').trim();}).filter(function(x){return x;}).slice(0,10),
  mentions:Array.prototype.slice.call(e.querySelectorAll('[itemtype*="Mention"],[data-tid*="mention"]')).map(function(x){return (x.textContent||'').trim();}).filter(function(x){return x;}).slice(0,5)});}
out.n=out.items.filter(function(x){return x.t==='msg';}).length;
return out;""")


def js_tw_scroll_up() -> str:
    return W._js("tw_scroll_up", """
var CAND=['[data-tid="message-pane-list-viewport"]','[data-tid="message-pane"]','[role="log"]'];var el=null;
for(var i=0;i<CAND.length;i++){var e=document.querySelector(CAND[i]);if(e&&e.scrollHeight>e.clientHeight+20){el=e;break;}}
if(!el){var m=document.querySelector('[data-tid="chat-pane-item"],[role="log"] [role="listitem"],[role="main"] [role="listitem"]');
 while(m&&m!==document.body){if(m.scrollHeight>m.clientHeight+20&&getComputedStyle(m).overflowY!=='visible'){el=m;break;}m=m.parentElement;}}
if(!el)return 'no-scroller';
var before=el.scrollTop;el.scrollTop=Math.max(0,el.scrollTop-Math.max(400,el.clientHeight-60));
el.dispatchEvent(new Event('scroll',{bubbles:true}));return el.scrollTop<before?'scrolled':'top';""")


def js_tw_pane() -> str:
    return W._js("tw_pane", W._CUT + """
var MSG=['[data-tid="chat-pane-item"]','[data-tid="chat-pane-message"]','[data-tid="message-pane"] [role="listitem"]','[role="log"] [role="listitem"]','[role="main"] [role="listitem"]'];
var n=0;for(var i=0;i<MSG.length;i++){var k=document.querySelectorAll(MSG[i]).length;if(k){n=k;break;}}
var head=document.querySelector('[data-tid="chat-header-title"],[data-tid="chatTitle"],[data-tid="chat-header"] [role="heading"],[role="main"] h1');
return {n:n,chat:head?cut((head.getAttribute('title')||head.textContent||'').trim(),120):''};""")


def js_tw_nav(which: str) -> str:
    """왼쪽 앱 막대에서 채팅·팀·활동 단추를 누른다(그 보기로 이동)."""
    labels = json.dumps(list(NAV_LABELS.get(which, ())), ensure_ascii=False)
    return W._js("tw_nav", f"""
var labels={labels};var bs=document.querySelectorAll('[data-tid*="app-bar"] button,[role="navigation"] button,nav button,[role="tablist"] [role="tab"]');
for(var i=0;i<bs.length;i++){{var a=((bs[i].getAttribute('aria-label')||bs[i].textContent||'')+'').trim().toLowerCase();
 for(var j=0;j<labels.length;j++){{if(a===labels[j]||a.indexOf(labels[j])===0){{bs[i].click();return 'ok';}}}}}}
return 'none';""")


# ───────────────────────────── 화면(가짜 · 실제 CDP) ─────────────────────────────
class FakeTeamsScreen:
    """``LM_TEAMSWEB_FAKE`` 화면 — 브라우저 없이 주입 파일의 목록·대화 화면 응답을 낸다. ``cost_s`` = 화면 한 장마다 시계를 미는 초."""

    synthetic = True

    def __init__(self, fake: dict, clock, *, cost_s: float = 0.0):
        self.fake = fake if isinstance(fake, dict) else {}
        self.clock = clock
        self.cost_s = float(cost_s)
        self.lpos = dict.fromkeys(LISTS, 0)
        self.rpos: dict = {}

    def _cost(self) -> None:
        if self.cost_s > 0:
            self.clock.sleep(self.cost_s)

    def open(self, dl) -> str:
        lg = self.fake.get("login")
        if lg == "ca":
            return "ca"
        return "login_required" if lg else "ready"

    def _pages(self, which: str) -> list:
        v = self.fake.get(which)
        if isinstance(v, dict):
            return [v]
        if isinstance(v, list):
            return [p for p in v if isinstance(p, dict)]
        return [] if which == "chats" else [{"how": "fake", "n": 0, "items": []}]

    def list_page(self, which: str, dl) -> dict:
        self._cost()
        pages = self._pages(which)
        if not pages:
            return {"how": "", "n": 0, "items": []}
        p = pages[min(self.lpos[which], len(pages) - 1)]
        items = [dict(x) for x in p.get("items") or [] if isinstance(x, dict)]
        return {"how": str(p.get("how", "fake")), "n": len(items), "items": items}

    def list_scroll(self, which: str, dl) -> str:
        pages = self._pages(which)
        if self.lpos[which] + 1 < len(pages):
            self.lpos[which] += 1
            return "scrolled"
        return "end" if self.fake.get(which + "_end", True) is not False else "scrolled"

    def _rounds(self, room: dict) -> list:
        msgs = self.fake.get("msgs") or {}
        v = msgs.get(str(room.get("idx"))) if isinstance(msgs, dict) else None
        return [p for p in v if isinstance(p, dict)] if isinstance(v, list) else []

    def open_room(self, room: dict, dl) -> str:
        self._cost()
        if room.get("gone"):
            return "gone"
        self.rpos[room["rid"]] = 0
        return "ok"

    def room_page(self, room: dict, dl) -> dict:
        self._cost()
        rounds = self._rounds(room)
        pos = self.rpos.get(room["rid"], 0)
        if pos >= len(rounds):
            return {"how": "fake", "n": 0, "items": []}
        p = rounds[pos]
        return {"how": str(p.get("how", "fake")), "chat": str(p.get("chat") or ""), "ctype": str(p.get("ctype") or ""),
                "n_part": p.get("n_part"), "items": [dict(x) for x in p.get("items") or [] if isinstance(x, dict)]}

    def room_scroll(self, room: dict, dl) -> str:
        rounds = self._rounds(room)
        pos = self.rpos.get(room["rid"], 0)
        if pos + 1 < len(rounds):
            self.rpos[room["rid"]] = pos + 1
            return "scrolled"
        return "top"

    def close(self) -> None:
        return None


class CdpTeamsScreen(W.CdpBase):
    """Teams 웹 실제 화면: 채팅·팀·활동 보기, 목록 가상 스크롤, 대화 ID 로 다시 찾아 열기, 위로 되감기."""

    def __init__(self, session, clock, counts: dict):
        super().__init__(session, clock, counts)
        self.view = ""
        self.pane = ("", -1)

    def open(self, dl) -> str:
        st = super().open(dl)
        if st != "ready":
            return st
        st = self.goto(TEAMS_URL, dl, TEAMS_HOST_RX)
        if st == "ready":
            self.view = "chats"
            self._wait_list("chats", dl)
        return st

    def _wait_list(self, which: str, dl) -> dict:
        end = dl.sub(W.READY_WAIT_S)
        while True:
            pg = self.eval(js_tw_list(which), dl) or {}
            if pg.get("n") or end.expired():
                return pg
            self._sleep(W.READY_POLL_S)

    def ensure_view(self, which: str, dl) -> None:
        if self.view == which or which not in NAV_LABELS:
            return
        if str(self.eval(js_tw_nav(which), dl) or "") == "ok":
            self._sleep(1.0)
            self._wait_list(which, dl)
        self.view = which

    def list_page(self, which: str, dl) -> dict:
        self.ensure_view(which, dl)
        return self.eval(js_tw_list(which), dl) or {"how": "", "n": 0, "items": []}

    def list_scroll(self, which: str, dl) -> str:
        r = str(self.eval(js_tw_list_scroll(which), dl) or "no-scroller")
        if r == "scrolled":
            self._sleep(0.8)
        return r

    def _wait_pane(self, dl) -> None:
        """화면이 바뀔 때까지(대화방 이름 또는 메시지 수) 확인하며 기다린다 — 무조건 자는 대기를 대신한다."""
        end = dl.sub(PANE_WAIT_S)
        last = self.pane
        while not end.expired():
            self._sleep(PANE_POLL_S)
            p = self.eval(js_tw_pane(), dl) or {}
            got = (str(p.get("chat") or ""), int(p.get("n") or 0))
            if got[1] > 0 and got != last:
                self.pane = got
                return

    def open_room(self, room: dict, dl) -> str:
        if room.get("source") == "activity":
            tid, mid = room.get("tid") or "", room.get("mid") or ""
            if not (tid and mid):
                return "gone"
            st = self.goto(DEEP_LINK.format(tid=quote(tid, safe=""), mid=quote(mid, safe="")), dl, TEAMS_HOST_RX)
            if st != "ready":
                raise W.ScreenStop(st)
            self.view = "deeplink"
            self._wait_pane(dl)
            return "ok"
        self.ensure_view(room.get("source") or "chats", dl)
        r = str(self.eval(js_tw_open(room.get("source") or "chats", room.get("tid") or "", int(room.get("idx") or 0)),
                          dl) or "gone")
        if r != "ok":
            return "gone"
        self._wait_pane(dl)
        return "ok"

    def room_page(self, room: dict, dl) -> dict:
        return self.eval(js_tw_msgs(), dl) or {"how": "", "n": 0, "items": []}

    def room_scroll(self, room: dict, dl) -> str:
        r = str(self.eval(js_tw_scroll_up(), dl) or "no-scroller")
        if r == "scrolled":
            self._wait_pane(dl)
        return r


def make_screen(environ, *, paths, clock, run_id, counts, session_factory=None, fake_cost_s: float = 0.0):
    fake = W.load_fake(environ, FAKE_ENV)
    if fake is not None:
        return FakeTeamsScreen(fake, clock, cost_s=fake_cost_s)
    factory = session_factory or W.edge_session
    return CdpTeamsScreen(factory(ROLE, run_id, paths=paths, clock=clock, environ=environ), clock, counts)


# ───────────────────────────── 수집 ─────────────────────────────
class Opts:
    def __init__(self, *, pc: str, d0=None, d1=None, max_chats=None, budget_sec=None, channels=None, activity=None,
                 force: bool = False, run_id: str = ""):
        self.pc = pc
        self.d0, self.d1 = d0, d1
        self.max_chats, self.budget_sec = max_chats, budget_sec
        self.channels, self.activity = channels, activity
        self.force = force
        self.run_id = run_id


def _list_all(run, screen, which: str) -> tuple:
    """목록 하나(채팅·채널·활동)를 가상 스크롤로 끝까지 → (항목들, 끝에 닿았나, 선택자)."""
    items, seen, stall, how, complete = [], set(), 0, "", False
    for _ in range(LIST_ROUNDS_MAX):
        if run.out_of_time():
            break
        pg = screen.list_page(which, run.dl) or {}
        how = how or str(pg.get("how") or "")
        new = 0
        for it in pg.get("items") or []:
            if not isinstance(it, dict):
                continue
            tid = str(it.get("tid") or "")
            ident = ("tid:" + tid + "|" + str(it.get("mid") or "")) if tid else ("label:" + norm_name(it.get("label")))
            if ident in seen:
                continue
            seen.add(ident)
            items.append(it)
            new += 1
        stall = 0 if new else stall + 1
        if not pg.get("items") and not pg.get("how"):
            break                                          # 선택자 실패 — 내릴 목록이 없다
        r = screen.list_scroll(which, run.dl)
        if r in ("end", "no-scroller"):
            complete = True
            break
        if stall >= LIST_STALL:
            break
    return items, complete, how


def _rooms(run, screen, opts) -> tuple:
    """읽을 대화방 목록(채팅 → 채널 → 활동이 알려 준 방, 대화 ID 로 중복 제거)과 목록 상태."""
    c = run.c
    rooms, by_tid = [], {}
    chats, done, how = _list_all(run, screen, "chats")
    c["chats_listed"], c["chats_how"] = len(chats), how
    listvirt = bool(chats) and not done
    sel_ok = bool(how)
    for it in chats:
        _add_room(rooms, by_tid, it, "chats")
    if opts.channels:
        chans, cdone, chow = _list_all(run, screen, "channels")
        c["channels_listed"], c["channels_how"] = len(chans), chow
        sel_ok = sel_ok or bool(chow)
        listvirt = listvirt or (bool(chans) and not cdone)
        for it in chans:
            _add_room(rooms, by_tid, it, "channels")
    mentions = set()
    if opts.activity:
        acts, _adone, ahow = _list_all(run, screen, "activity")
        c["activity_listed"], c["activity_how"] = len(acts), ahow
        sel_ok = sel_ok or bool(ahow)
        for it in acts:
            tid, mid = str(it.get("tid") or ""), str(it.get("mid") or "")
            if tid and mid and it.get("mention"):
                mentions.add((tid, mid))
            if tid and mid and tid not in by_tid:          # 바로가기(대화 ID + 메시지 ID)가 있어야 그 방을 연다
                _add_room(rooms, by_tid, it, "activity")
                run.bump("activity_rooms")
            elif not (tid and mid):
                run.bump("activity_no_link")
    return rooms, listvirt, sel_ok, mentions


def _add_room(rooms: list, by_tid: dict, it: dict, source: str) -> None:
    tid = str(it.get("tid") or "")
    if tid and tid in by_tid:
        return
    room = {"rid": f"{source}:{it.get('idx', len(rooms))}", "idx": it.get("idx", len(rooms)), "tid": tid,
            "mid": str(it.get("mid") or ""), "label": str(it.get("label") or ""), "source": source,
            "gone": bool(it.get("gone"))}
    if tid:
        by_tid[tid] = room
    rooms.append(room)


class Checkpoint:
    def __init__(self, d: dict | None):
        d = d if isinstance(d, dict) else {}
        self.last = str(d.get("last_msg_key") or "") or None
        self.oldest = _day(d.get("oldest_done"))
        self.newest = _day(d.get("newest_done"))
        if not (self.oldest and self.newest and self.oldest <= self.newest):
            self.oldest = self.newest = None

    @property
    def valid(self) -> bool:
        return self.newest is not None


def _day(v):
    if isinstance(v, str) and W.DATE_RX.match(v):
        try:
            return date.fromisoformat(v)
        except ValueError:
            return None
    return None


def _read_room(run, screen, room: dict, cp: Checkpoint, d0: date, d1: date, max_scroll: int) -> dict:
    """한 방을 맨 아래(최신)부터 위로 되감으며 읽는다. 체크포인트 구간은 건너고(세지 않음), 기간 시작·대화 처음·정지·
    되감기 상한·예산에서 멈춘다."""
    res = {"pages": [], "top": False, "start": False, "done_stop": False, "cut": None, "mode": "new", "gone": False}
    if screen.open_room(room, run.dl) != "ok":
        res["gone"] = True
        return res
    seen, stall, scrolls, skips, mode = set(), 0, 0, 0, "new"
    while True:
        if run.out_of_time():
            res["cut"] = "budget"
            break
        page = screen.room_page(room, run.dl) or {}
        res["pages"].append(page)
        run.bump("pages")
        idents, oldest = page_dates(page, today=run.today, d0=d0, d1=d1, off_fn=run.off_fn)
        new = idents - seen
        seen |= new
        if oldest is not None and oldest < d0:
            res["start"] = True
            break
        if mode == "new" and cp.valid and oldest is not None and oldest < cp.newest:
            if cp.oldest <= d0:
                res["done_stop"] = True                    # 더 오래된 쪽은 이미 다 읽었다
                break
            mode = "skip"
        if mode == "skip" and oldest is not None and oldest < cp.oldest:
            mode, stall = "older", 0
        if mode == "skip":
            stall = 0 if new else stall + 1               # 건너는 중에도 화면이 더 안 바뀌면(되감기 정체) 멈춘다
            if skips >= SKIP_ROUNDS_MAX or stall > ROOM_STALL:
                res["cut"] = "skipcap" if skips >= SKIP_ROUNDS_MAX else "stall"
                break
        else:
            stall = 0 if new else stall + 1
            if stall >= ROOM_STALL:
                res["cut"] = "stall"
                break
            if scrolls >= max_scroll:
                res["cut"] = "maxscroll"
                break
        r = screen.room_scroll(room, run.dl)
        if r != "scrolled":
            res["top"] = True
            break
        if mode == "skip":
            skips += 1
            run.bump("skip_scrolls")
        else:
            scrolls += 1
    res["mode"] = mode
    return res


def _new_checkpoint(cp: Checkpoint, res: dict, msgs: list, d0: date, newest_new: date):
    """읽은 결과 → 새 [oldest_done, newest_done](이어진 구간만). 이을 수 없으면 None(앞 체크포인트 유지)."""
    if cp.valid and cp.newest > newest_new:
        newest_new = cp.newest
    days = [m["day"] for m in msgs if m["day"]]
    if res["start"] or res["top"]:
        oldest = min(d0, cp.oldest) if cp.valid else d0
    elif res["done_stop"]:
        oldest = cp.oldest
    elif res["mode"] == "skip":
        oldest = cp.oldest
    elif res["mode"] == "older":
        older = [d for d in days if cp.valid and d < cp.oldest]
        oldest = (min(older) + timedelta(days=1)) if older else cp.oldest
    else:                                                  # new 에서 끊김 — 앞 구간과 이어지면 합친다
        if not days:
            return None
        lo = min(days)
        oldest = cp.oldest if (cp.valid and lo <= cp.newest) else lo + timedelta(days=1)
    if oldest is None or oldest > newest_new:
        return None
    return oldest, newest_new


def _keep(m: dict, cp: Checkpoint, d0: date, d1: date, force: bool) -> str:
    """'keep' · 'out' · 'done' · 'unknown_skip' — 저장할 메시지 고르기."""
    if m["precision"] == "unknown":
        return "keep" if (force or not cp.valid) else "unknown_skip"
    if not (d0 <= m["day"] <= d1):
        return "out"
    if not force and cp.valid and cp.oldest <= m["day"] < cp.newest:
        return "done"
    return "keep"


def _raw(m: dict, room: dict, *, run, ctype: str, n_part, title: str, participants: list, self_norms, mention_ids,
         self_texts) -> dict:
    """해석 dict → 원시 레코드(P §10.2 teams 원시 이름 — 계약 §3.5 · C7). 원문은 메모리에만."""
    if m["when"] is not None:
        ts, precision = m["when"], "exact"
    elif m["precision"] in ("minute", "date"):
        hm = m["hm"] or (12, 0)
        d = m["day"]
        ts, precision = W.local_to_utc(datetime(d.year, d.month, d.day, hm[0], hm[1]), run.off_fn), m["precision"]
    else:                                                  # 날짜 미상 — 수집일 00:00 로컬의 자리값(C7)
        t = run.today
        ts, precision = W.local_to_utc(datetime(t.year, t.month, t.day), run.off_fn), "unknown"
    author = m["author"]
    if m["me"] is not None:
        is_me = m["me"]
    elif author:
        is_me = norm_name(author) in self_norms
    else:
        is_me = None
    flags = run.flag_set(precision)
    if m["inherited"]:
        flags["author_inherited"] = True
    if precision in ("exact", "minute"):
        conf = CONF_INHERITED if m["inherited"] else CONF_EXACT
    else:
        conf = CONF_DATE if precision == "date" else CONF_UNKNOWN
    mentions_me = any(norm_name(x).lstrip("@") in self_norms for x in m["mentions"])
    if not mentions_me and m["mid"] and (room.get("tid"), m["mid"]) in mention_ids:
        mentions_me = True
    if not mentions_me and m["body"]:
        mentions_me = any(("@" + n) in m["body"] for n in self_texts)
    raw = {"message_id": m["mid"] or None, "chat_id": room["chat_id"], "chat_type": ctype,
           "n_participants": n_part, "reply_to_id": m["reply_to"], "author_addr": None, "author_name": author or None,
           "is_me": is_me, "participants": participants, "mentions_me": bool(mentions_me), "file_names": m["files"],
           "body_text": m["body"], "chat_title": title or None, "ts_utc": W.utc_iso(ts),
           "ts_local_offset": W.off_text(ts, run.off_fn), "ts_precision": precision, "observed_at": run.now_iso,
           "confidence": conf, "flags": flags}
    return {k: v for k, v in raw.items() if v is not None}


def _room_meta(room: dict, msgs: list, pages: list, self_norms) -> tuple:
    """(대화 유형, 참여 인원, 방 제목, 참여자) — 구조 단서만."""
    tid = room.get("tid") or ""
    ctype = next((str(p.get("ctype")) for p in pages if p.get("ctype")), "")
    ctype = chat_type_of(tid, room.get("label") or "", ctype)
    n_part = next((p.get("n_part") for p in pages if isinstance(p.get("n_part"), int) and p.get("n_part") > 0), None)
    if ctype == "1:1":
        n_part = 2
    elif ctype == "self":
        n_part = 1
    title = next((str(p.get("chat")) for p in pages if p.get("chat")), "") or room.get("label") or ""
    if ctype not in ("group", "channel", "meeting"):
        title = ""                                         # 1:1 방 이름 = 상대 이름 — 넘기지 않는다(구조 미상도 같다)
    others = []
    for m in msgs:
        a = m["author"]
        if a and norm_name(a) not in self_norms and a not in others:
            others.append(a)
    return ctype, n_part, title, [{"name": a} for a in others[:20]]


def collect(opts: Opts, *, paths, cfg, api, clock, now, off_fn, environ, session_factory=None, err=None,
            fake_cost_s: float = 0.0) -> dict:
    """teams.web 한 번 → 상태 dict."""
    max_chats = opts.max_chats if opts.max_chats is not None else int(W.cfg_get(cfg, "teams.web.maxChats", 0) or 0)
    budget = opts.budget_sec if opts.budget_sec is not None else int(W.cfg_get(cfg, "teams.web.budgetSec", 900) or 900)
    max_scroll = int(W.cfg_get(cfg, "teams.web.maxScroll", 12) or 0)
    if opts.channels is None:
        opts.channels = bool(W.cfg_get(cfg, "teams.web.includeChannels", True))
    if opts.activity is None:
        opts.activity = bool(W.cfg_get(cfg, "teams.web.includeActivity", True))
    run = W.WebRun(kind=KIND, src=SRC, pc_id=opts.pc, paths=paths, cfg=cfg, api=api, clock=clock, now=now,
                   off_fn=off_fn, budget_sec=budget, err=err)
    st, c = run.st, run.c
    lookback = int(run.cfg_get("collect.lookbackDays", 120) or 120)
    d0 = opts.d0 or (run.today - timedelta(days=lookback))
    d1 = opts.d1 or run.today
    newest_new = min(run.today, d1)
    c.update(max_chats=max_chats, budget_sec=budget, max_scroll=max_scroll, channels=bool(opts.channels),
             activity=bool(opts.activity))
    try:
        screen = make_screen(environ, paths=paths, clock=clock, run_id=opts.run_id, counts=c,
                             session_factory=session_factory, fake_cost_s=fake_cost_s)
    except W.FakeError as e:
        c["fake_error"] = str(e)
        W.add_reason(st, "R-TRANSPORT")
        st["rc"] = W.RC_DRIVER
        return st
    c["synthetic"] = bool(screen.synthetic)
    hb, stop, n_new, n_read = None, None, 0, 0
    try:
        state = screen.open(run.dl)
        if state != "ready":
            rc, why = W.session_failure(state, getattr(getattr(screen, "s", None), "error", None))
            c["session"] = state
            W.add_reason(st, why)
            st["rc"] = rc
            W.human(f"[Teams 웹] {'로그인이 필요합니다(전용 Edge 창에서 1회)' if rc == W.RC_LOGIN else 'Edge 세션을 쓸 수 없습니다'}"
                    f" — {state}", err)
            return st
        rctx = run.context()
        self_texts = [n for n in (getattr(getattr(rctx, "sctx", None), "self_names", None) or []) if len(n) >= 2]
        self_norms = {norm_name(n) for n in self_texts} | set(SELF_FIXED)
        if not self_texts:
            W.add_reason(st, "R-NOADDR")                   # 본인 표시명 미확정 → 방향은 구조 단서로만
        try:
            rooms, listvirt, sel_ok, mention_ids = _rooms(run, screen, opts)
        except W.ScreenStop as x:
            rooms, listvirt, sel_ok, mention_ids, stop = [], False, True, set(), x
        if listvirt:
            st["partial"] = True
            W.add_reason(st, "R-LISTVIRT")
        if stop is None and not rooms and not sel_ok:
            W.add_reason(st, "R-WEBSEL")
            st["rc"] = W.RC_DRIVER
            W.human("[Teams 웹] 화면 구조를 알아보지 못했습니다(선택자 전부 실패) — 대화 목록 0", err)
            return st
        c["rooms_listed"] = len(rooms)
        if max_chats > 0 and len(rooms) > max_chats:
            c["rooms_capped"] = len(rooms) - max_chats
            rooms = rooms[:max_chats]
            st["partial"] = st["cap_hit"] = True
            W.add_reason(st, "R-CAP")
        cursor = run.load_cursor()
        cps = dict(cursor.get("rooms") or {}) if isinstance(cursor.get("rooms"), dict) else {}
        hb = W.heartbeat(STAGE, total=len(rooms))
        msg_sel_ok = msg_sel_fail = 0
        for i, room in enumerate(rooms):
            if stop is not None:
                break
            if run.out_of_time():
                run.budget_cut()
                c["rooms_deferred"] = len(rooms) - i
                break
            try:
                got = _process_room(run, screen, room, cps, d0, d1, newest_new, max_scroll, opts, self_norms,
                                    self_texts, mention_ids)
            except W.ScreenStop as x:
                stop = x
                break
            n_new += got["new"]
            n_read += got["seen"]
            msg_sel_ok += got["sel_ok"]
            msg_sel_fail += got["sel_fail"]
            if hb is not None:
                hb.update(done=i + 1)
        if stop is None and rooms and msg_sel_fail and not msg_sel_ok and not n_read:
            W.add_reason(st, "R-WEBSEL")                   # 방은 열리는데 메시지 화면을 하나도 못 알아봄
            st["rc"] = W.RC_DRIVER
            return st
    except W.StoreError as e:
        c["store_error"] = f"{e.what}:{e.etype}"
        W.add_reason(st, "R-TRANSPORT")
        st["rc"] = W.RC_DRIVER
        run.finish_audit()
        run.fill_counts()
        st["n"] = n_new
        W.human(f"[Teams 웹] 정제·저장 실패({e.etype}) — 체크포인트를 그대로 두고 다음 실행에서 다시 읽습니다", err)
        return st
    finally:
        W.stop_heartbeat(hb)
        screen.close()
    run.finish_audit()
    run.fill_counts()
    st["n"] = n_new
    if c.get("rooms_gone"):
        st["partial"] = True
        W.add_reason(st, "R-ROOMGONE")
    row_err = run.flag_row_errors()                        # 정제 오류 행이 든 방은 체크포인트를 남기지 않았다
    if stop is not None:
        rc, why = W.session_failure(stop.state, stop.info)
        c["session"] = stop.state
        W.add_reason(st, why)
        st["rc"] = rc
        st["partial"] = True
    elif n_new > 0:
        st["rc"] = W.RC_SAVED
    elif row_err:                                          # 새로 남길 행이 전부 정제 오류 — '새것 0'(rc 4)이 아니다
        st["rc"] = W.RC_DRIVER
    elif n_read > 0:
        st["rc"] = W.RC_NONEW
    else:
        st["rc"] = W.RC_NONE
    W.human(f"[Teams 웹] 대화 {c.get('rooms_done', 0)}/{c.get('rooms_listed', 0)} · 화면 {c.get('pages', 0)} · 메시지 "
            f"{c.get('msgs', 0)} · 저장 {run.stored}(새 {n_new}) · 날짜 미상 {c.get('unknown', 0)} · 방 못 찾음 "
            f"{c.get('rooms_gone', 0)}" + (" · 예산 소진(다음 실행이 이어 읽음)" if st["budget_hit"] else ""), err)
    return st


def _chat_key(run, tid: str):
    """대화 ID → chat_key(정제기가 만드는 HMAC — 체크포인트 키)."""
    probe = _probe_row(run, {"chat_id": tid, "chat_type": "group", "n_participants": 2, "ts_utc": run.now_iso,
                             "ts_local_offset": "+00:00", "ts_precision": "unknown", "observed_at": run.now_iso,
                             "confidence": 0.3, "body_text": ""}) if tid else None
    return probe.data.get("chat_key") if probe is not None else None


def _probe_row(run, raw: dict):
    """키 확인용 정제(저장하지 않음): **따로 만든 레코드 문맥**에서 정제해 본 봉인 행 또는 None. 그 문맥의 감사는 기록하지
    않으므로 본 수집의 감사·방 성향 계수에 섞이지 않는다(정제 전 원문으로 만든 키는 두 문맥에서 같다 — 같은 키링)."""
    if getattr(run, "krctx", None) is None:
        run.krctx = run.api["make_record_context"](run.paths.root, run.src, run.pc_id, paths=run.paths, cfg=run.cfg)
    o = run.api["sanitize_record"](KIND, raw, run.krctx)
    return o.row if o.status == "stored" else None


def _drop_rereads(run, kept: list, raws: list, cp: Checkpoint) -> tuple:
    """앞 실행이 저장한 마지막 메시지(표지 last_msg_key)까지의 newest_done 날 메시지는 다시 저장하지 않는다.
    표지를 못 찾으면(지워진 메시지 등) 그날 메시지를 모두 남긴다(중복은 적재 때 id 로 흡수)."""
    if not (cp.valid and cp.last):
        return kept, raws
    idx = [i for i, m in enumerate(kept) if m["precision"] != "unknown" and m["day"] == cp.newest]
    keys = []
    for i in idx:
        probe = _probe_row(run, raws[i])
        keys.append(probe.data.get("msg_key") if probe is not None else None)
    if cp.last not in keys:
        return kept, raws
    drop = set(idx[:keys.index(cp.last) + 1])
    run.bump("reread", len(drop))
    return ([m for i, m in enumerate(kept) if i not in drop], [r for i, r in enumerate(raws) if i not in drop])


def _process_room(run, screen, room: dict, cps: dict, d0, d1, newest_new, max_scroll, opts, self_norms, self_texts,
                  mention_ids) -> dict:
    """방 하나: 체크포인트 → 읽기 → 해석 → 정제·저장(gzip 멤버 1개) → 체크포인트 저장."""
    out = {"new": 0, "kept": 0, "seen": 0, "sel_ok": 0, "sel_fail": 0}
    label = room.get("label") or ""
    room["chat_id"] = room.get("tid") or (("web:" + norm_name(label)) if norm_name(label) else "")
    if not room["chat_id"]:
        run.bump("rooms_no_id")
        return out
    ck = _chat_key(run, room["chat_id"])
    cp = Checkpoint(None if (opts.force or ck is None) else cps.get(ck))
    res = _read_room(run, screen, room, cp, d0, d1, max_scroll)
    if res["gone"]:
        run.bump("rooms_gone")
        return out
    for p in res["pages"]:
        if p.get("how") or p.get("items"):
            out["sel_ok"] += 1
        else:
            out["sel_fail"] += 1
    msgs = parse_pages(res["pages"], today=run.today, d0=d0, d1=d1, off_fn=run.off_fn)
    run.bump("msgs", len(msgs))
    ctype, n_part, title, participants = _room_meta(room, msgs, res["pages"], self_norms)
    kept = []
    for m in msgs:
        why = _keep(m, cp, d0, d1, opts.force)
        if why != "out":
            out["seen"] += 1                               # 기간 안에서 읽은 것(새것이 아니어도) — rc 4 판정
        if why == "keep":
            kept.append(m)
        else:
            run.bump({"out": "out_of_range", "done": "done_region", "unknown_skip": "unknown_skipped"}[why])
    raws = [_raw(m, room, run=run, ctype=ctype, n_part=n_part, title=title, participants=participants,
                 self_norms=self_norms, mention_ids=mention_ids, self_texts=self_texts) for m in kept]
    kept, raws = _drop_rereads(run, kept, raws, cp)
    for m in kept:
        run.bump(m["precision"])
        if m["inherited"]:
            run.bump("inherited")
    rows = run.commit_aligned(raws)
    row_errors = run.batch_errors
    raws = None
    out["kept"] = len(kept)
    new_last = cp.last
    for m, stored in zip(kept, rows, strict=True):
        if stored is None:
            continue
        out["new"] += 1                                    # 남긴 것은 모두 새것(읽은 구간·표지까지는 위에서 뺐다)
        if m["precision"] != "unknown":
            new_last = stored.data.get("msg_key")
        if ck is None:
            ck = stored.data.get("chat_key")
    if row_errors:                                         # 정제 오류 행이 있으면 체크포인트를 옮기지 않는다 — 다음 실행이
        run.bump("rooms_row_errors")                       # 그 방을 다시 읽는다(저장된 행은 id 로 흡수, 영구 누락 금지)
        return out
    if not res["pages"] or ck is None:
        return out
    rng = _new_checkpoint(cp, res, msgs, d0, newest_new)
    val = {"last_msg_key": new_last, "oldest_done": rng[0].isoformat(), "newest_done": rng[1].isoformat()} if rng else None
    if val is not None and cps.get(ck) != val:            # 바뀐 것이 없으면 다시 쓰지 않는다
        cps[ck] = val
        if len(cps) > ROOMS_MAX:
            for k, _v in sorted(cps.items(), key=lambda kv: str(kv[1].get("newest_done") or ""))[:len(cps) - ROOMS_MAX]:
                cps.pop(k, None)
        run.save_cursor({"rooms": dict(sorted(cps.items()))})
    if res["cut"] in ("maxscroll", "stall", "skipcap"):
        run.bump("rooms_cut_" + res["cut"])
    if res["cut"] == "budget":
        run.budget_cut()
    else:
        run.bump("rooms_done")
    return out


# ───────────────────────────── 진입점 ─────────────────────────────
class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise W.ArgError(message)


def build_parser() -> argparse.ArgumentParser:
    ap = _Parser(prog="Get-TeamsWeb.py", description="Teams 웹 백필(teams.web) → 정제 → 로컬 원장")
    ap.add_argument("--pc", required=True, help="pc_id")
    ap.add_argument("--from", dest="from_", default="", help="YYYY-MM-DD(로컬)")
    ap.add_argument("--to", default="", help="YYYY-MM-DD(로컬, 포함)")
    ap.add_argument("--max-chats", type=int, default=None, help="대화 수 상한(0 = 예산 안 무제한)")
    ap.add_argument("--budget-sec", type=int, default=None, help="전체 시간 예산(초)")
    ap.add_argument("--no-channels", action="store_true", help="채널 글타래를 읽지 않음")
    ap.add_argument("--no-activity", action="store_true", help="활동(멘션) 피드를 읽지 않음")
    ap.add_argument("--force", action="store_true", help="체크포인트를 무시하고 기간 전체")
    ap.add_argument("--run-id", default="", help="수집 실행 run_id(세션 잠금·건강 기록용, 없으면 새로)")
    ap.add_argument("--events", default="jsonl", choices=("jsonl", "text", "off"))
    return ap


def parse_opts(argv) -> tuple:
    a = build_parser().parse_args(argv)
    if not W.PC_ID_RX.match(a.pc or ""):
        raise W.ArgError("pc_id 형식이 아닙니다")
    d0, d1 = W.parse_day(a.from_), W.parse_day(a.to)
    if d0 and d1 and d1 < d0:
        raise W.ArgError("--to 가 --from 보다 앞섭니다")
    if a.max_chats is not None and a.max_chats < 0:
        raise W.ArgError("--max-chats 는 0 이상")
    if a.budget_sec is not None and a.budget_sec <= 0:
        raise W.ArgError("--budget-sec 는 1 이상")
    if a.run_id and not W.RUN_ID_RX.match(a.run_id):
        raise W.ArgError("run_id 형식이 아닙니다")
    return Opts(pc=a.pc, d0=d0, d1=d1, max_chats=a.max_chats, budget_sec=a.budget_sec,
                channels=False if a.no_channels else None, activity=False if a.no_activity else None, force=a.force,
                run_id=a.run_id or tz.new_run_id()), a.events


def run(argv=None, *, paths=None, cfg=None, api=None, now=None, clock=None, off_fn=None, session_factory=None,
        environ=None, err=None, fake_cost_s: float = 0.0) -> int:
    err = err if err is not None else sys.stderr
    environ = os.environ if environ is None else environ
    try:
        opts, ev_mode = parse_opts(argv)
    except SystemExit as e:
        if e.code in (0, None):
            return 0
        raise
    except W.ArgError as e:
        st = W.new_status(SRC)
        st["counts"]["error"] = "BadArguments"
        W.add_reason(st, "R-TRANSPORT")
        W.human(f"[Teams 웹] 인자 오류: {e}", err)
        W.status_line(st, err)
        return W.RC_DRIVER
    events.configure(ev_mode)
    clk = clock or default_clock()
    t0 = clk.mono()
    try:
        if paths is None:
            from lm27.paths import Paths
            paths = Paths(ROOT)
        if cfg is None:
            from lm27.config import load_config
            cfg = load_config(paths)
        st = collect(opts, paths=paths, cfg=cfg, api=api or W.store_api(), clock=clk, now=now or datetime.now(UTC),
                     off_fn=off_fn or W.default_off, environ=environ, session_factory=session_factory, err=err,
                     fake_cost_s=fake_cost_s)
    except Exception as e:                                 # noqa: BLE001 — 내부 오류는 rc 3 + 수송 사유(유형만, 원문 없음)
        st = W.new_status(SRC)
        st["counts"]["error"] = type(e).__name__
        W.add_reason(st, "R-TRANSPORT")
        W.human(f"[Teams 웹] 내부 오류({type(e).__name__}) — 다음 실행에서 다시 시도합니다", err)
    st["elapsed_ms"] = int((clk.mono() - t0) * 1000)
    W.status_line(st, err)
    return int(st.get("rc", W.RC_DRIVER))


def main() -> int:
    for s in (sys.stdout, sys.stderr):
        r = getattr(s, "reconfigure", None)
        if r is not None:
            r(encoding="utf-8", errors="replace")
    return run()


if __name__ == "__main__":
    sys.exit(main())
