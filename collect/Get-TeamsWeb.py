# -*- coding: utf-8 -*-
"""
Get-TeamsWeb.py — 팀즈 웹(teams.microsoft.com)을 전용 Edge 프로필로 열어 채팅을 읽는다 (폴백).

Get-OutlookWeb.py 와 같은 방식이다: Copilot 에 쓰는 전용 Edge 프로필(data\\lm28_edge)에 회사 계정으로
한 번 로그인해 두면, **팀즈 앱이 꺼져 있어도** 동작한다. 앱 창 읽기(Get-TeamsWindow.ps1)는 화면에 그려진
부분만 UI 자동화로 긁으므로 창 크기·테마·팀즈 버전에 따라 PC 마다 0건이 되곤 했다(실측 제보). 웹 경로는
화면 렌더가 아니라 문서 구조(role·data-tid·aria-label)를 읽으므로 그 편차가 없고, 스크롤로 지난 날짜까지
거슬러 올라간다.

  python collect\\Get-TeamsWeb.py --from 2026-06-01 --to 2026-06-30 [--max-chats 200] [--budget 900] [--force]

출력: data\\m365\\teams_web.csv   (time,from,chat,kind,replied_time,summary)
      — Graph·창 읽기 경로와 같은 스키마라 분석기(core\\extract.py 의 teams_*.csv)가 그대로 인제스트한다.
      이미 있는 teams_*.csv 전부와 대조해 같은 메시지는 다시 적지 않는다(경로가 겹쳐도 중복 계상 없음).
      data\\m365\\teams_web_rooms.json — 방 커서 {ver: '<판>|<collect.cursorEpoch>', rooms: {sha1(방)[:12]:
      {status, oldest, newest_read, …}}} (메시지 원문 없음 — newest_read 는 해시). ver 가 다르면 버리고 처음부터 읽는다.
종료 코드(= LMSTATUS rc, LM28): 0 새 행 저장 / 1 기간에 활동한 방 없음 / 2 로그인 필요(전용 Edge 창에서 1회 · R-LOGIN·R-PERSONAL)
          / 3 불가·불완전(R-WEBSEL 목록·스크롤 영역 못 찾음 · R-ROOMGONE · R-TIMEOUT · R-EDGEBUSY · Edge 기동 사유) / 4 새 행 0
          (LM24 의 '기존 누적이 있으면 0' 은 없앴다 — 이번 실행이 읽은 것으로만 정한다.)
마지막 줄: LMSTATUS {v,src:'teams_web',rc,reason,counts,ranges[{axis:'teams',from,to,st}]}
          counts: rooms_listed·list_end·opened·complete·incremental_ok·cut_budget·cut_no_scroller·roomgone·rows_new·teams_present(+진단)

LM28 '읽음' 규칙(F-06·F-07·F-30·C-21·W1-05 — 검증된 방만 읽음으로 적는다):
  · 목록은 가상 스크롤을 끝까지 내린다(새 이름 0 화면 3번 또는 끝). 상한 teamsWebMaxChats(기본 200, 0 = 무제한).
    마지막 활동이 기간 시작 전인 방은 열지 않는다. 지난 실행에서 잘린 방(cut·roomgone)을 먼저 연다.
  · 방 전환은 확인한다: 목록 항목이 aria-selected 거나, 머리 제목(정규화)이 그 방 이름과 같고 화면이 바뀌었을 때만 읽는다.
    아니면 R-ROOMGONE — 그 방 행은 0(앞 방 메시지를 이 방으로 적지 않는다).
  · 위로 되감기: 'top' 이면 6초까지 지난 메시지 로드를 기다린다(3번 연속 높이 증가가 없을 때만 맨 위 확인 = complete).
    'no-scroller' 면 스크롤되는 조상을 다시 찾고, 그래도 없으면 cut_no_scroller('처음까지 읽음'이 아니다).
    되감기 상한 teamsWebMaxScroll(기본 60). 기간 시작 전 날짜에 닿으면 complete.
  · 다음 실행: complete·incremental_ok 방은 최신부터 읽다가 지난 newest_read 와 같은 메시지가 나오면 멈춘다(incremental_ok —
    겹침으로 검증). 목록의 마지막 활동 날짜·미리보기가 지난 확인 때와 같고 오늘이 아니면 열지 않는다(새 메시지 없음).
    newest_read 는 complete·incremental_ok 일 때만 앞으로 옮긴다.
  · 날짜는 <time datetime> 를 우선하고, 머리 조각(시각·title·aria-label)과 날짜 구분선에서만 찾는다(본문 날짜 금지).
    날짜를 못 짚은 메시지는 버린다. 작성자가 없는 연속 메시지는 직전 작성자를 잇는다(내 말풍선은 '나').
  · 방마다 저장한다(예산에 끊겨도 앞 방은 남는다). 중복 키는 teams_parse.key_of(날짜 포함 · 정제된 글).
  · 일자 판정(teams 축): teams_parse.day_ranges — 목록 끝(또는 마지막 방이 d 보다 오래됨) + 마지막 활동 ≥d 인 모든 방을
    d 이하까지 읽음이면 ok, 그 밖은 partial. 오늘은 ok 대신 partial.
  · 전용 Edge 는 copilot_auto.edge_lock 안에서만 쓰고(다른 작업과 직렬), 이 수집기가 연 탭만 닫는다(로그인 대기면 둔다).

Copilot 과 달리 LLM 을 거치지 않으므로 지어낸 행이 없고, 데이터는 PC 밖으로 나가지 않는다(브라우저가 내
채팅을 보여주는 것을 읽을 뿐이다). replied_time 은 웹에서도 측정할 수 없어 빈 값(미측정)으로 둔다.

화면 구조는 Microsoft 가 바꿀 수 있어 선택자를 여러 벌 두고 '무엇으로 몇 개를 잡았는지' 를 로그·counts.selector_diag 에
남긴다(회사 PC 의 원문을 밖으로 보낼 수 없으므로 진단은 숫자로 한다).
시험: tests\\fakes\\fake_teams.py(FakeTeams — 이 모듈 JS 상수의 머리 표식 /*LM28:tw_…*/ 에 각본 응답). LM24 의
      LM_TEAMSWEB_FAKE(화면 응답 JSON) 주입은 방 확인·되감기 판정을 흉내 낼 수 없어 없앴다.
"""
import csv
import glob
import hashlib
import importlib.util
import io
import json
import os
import re
import sys
import time
from datetime import date, datetime, timedelta
from urllib.parse import quote

if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, errors="replace", encoding=(
        (sys.stdout.encoding or "utf-8") if sys.stdout.isatty() else "utf-8"))  # 콘솔(bat)=콘솔 코드페이지 · 파이프(UI)=utf-8

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
import owa_parse  # noqa: E402  — 목록 날짜 조각(오늘·요일·어제·M/D) 해석
import teams_parse  # noqa: E402  — LM28 순수 판정(키·방 판정·일자 판정)

OUT_DIR = os.path.join(ROOT, "data", "m365")
HDR = "time,from,chat,kind,replied_time,summary"
COLLECTOR_VER = "LM28-TW-1"            # 방 커서 판 — teams_web_rooms.json 의 ver '판|collect.cursorEpoch'
STATE_NAME = "teams_web_rooms.json"
TEAMS_URL = "https://teams.microsoft.com/"          # LM28: 문서에 없는 /v2/ 경로 대신 시작 주소(도착 호스트는 cloud.microsoft 일 수 있다)
HOSTS = ("teams.microsoft.com", "teams.cloud.microsoft", "teams.office.com")
PERSONAL_HOSTS = ("teams.live.com",)                # 개인용 Teams — 업무 채팅이 아니다(R-PERSONAL)
SUMMARY_MAX = 200               # 창 읽기 경로와 같은 길이
MAX_CHATS = 200                 # teamsWebMaxChats 기본(0 = 무제한)
MAX_SCROLL = 60                 # teamsWebMaxScroll 기본 — 방 하나를 위로 되감는 횟수 상한
LIST_STALL = 3                  # 목록: 새 이름 0 화면이 이만큼 이어지면 끝
LIST_SCREENS = 400              # 목록 화면 상한(안전)
SEEK_SCREENS = 80               # 열 방을 목록에서 다시 찾을 때 내리는 화면 상한
ROOM_STALL = 3                  # 방: 되감아도 새 항목이 없는 화면이 이만큼 이어지면 그 방은 여기까지(cut)
TOP_CONFIRM = 3                 # 'top' 뒤 높이 증가 없는 확인 횟수(× TOP_WAIT = 6초)
TOP_WAIT = 2.0
SCROLL_WAIT = 1.8               # 되감기 뒤 지난 메시지가 붙기를 기다리는 상한
OPEN_WAIT = 2.5                 # 방 전환 확인 대기(2번까지)
CUT_STATES = ("cut_budget", "cut_no_scroller", "roomgone")
_sleep = time.sleep             # 시험(FakeTeams)이 대기를 가짜 시계로 바꿀 수 있게
_mono = time.monotonic


def arg(flag, d=""):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv and sys.argv.index(flag) + 1 < len(sys.argv) else d


def log(msg):
    print(f"[teams-web] {msg}")
    sys.stdout.flush()


def _load_cfg():
    try:
        with open(os.path.join(ROOT, "config", "config.json"), encoding="utf-8-sig") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


# ── 날짜·시각 해석은 메일 웹 수집기의 것을 그대로 쓴다 ────────────────────────
# 같은 회사 PC 의 같은 지역 설정에서 이미 검증된 해석기다. 여기서 다시 만들면 한·영·일·중 표기와
# 미국식/유럽식 순서를 또 틀리게 된다(메일 쪽 감사에서 이미 겪은 항목).
_spec = importlib.util.spec_from_file_location("_owa", os.path.join(_HERE, "Get-OutlookWeb.py"))
_owa = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_owa)
find_times = _owa.find_times
find_date = _owa.find_date

TODAY_W = ("오늘", "today", "今日", "今天")
YDAY_W = ("어제", "yesterday", "昨日", "昨天")
# 요일 이름 → 월=0. 한 글자('월')는 '8월' 과 섞이므로 두 글자 이상만 본다.
WDAY = {}
for _i, _ws in enumerate((("월요일", "monday", "mon"), ("화요일", "tuesday", "tue"), ("수요일", "wednesday", "wed"),
                          ("목요일", "thursday", "thu"), ("금요일", "friday", "fri"), ("토요일", "saturday", "sat"),
                          ("일요일", "sunday", "sun"))):
    for _w in _ws:
        WDAY[_w] = _i


def _norm(s):
    return teams_parse.norm_name(s)


def self_names(cfg):
    """'나' 로 볼 표시 이름 — config.owner · teamsSelfNames · Windows 계정 · 팀즈가 쓰는 '나/You'."""
    out = {"나", "you", "본인", "me", "자신"}
    vals = [cfg.get("owner"), os.environ.get("USERNAME")]
    vals += list(cfg.get("teamsSelfNames") or [])
    for v in vals:
        v = _norm(v)
        if v:
            out.add(v)
    return out


def rel_date(text, today):
    """'오늘'·'어제'·요일 이름 → date. 요일은 오늘 이전의 가장 가까운 그 요일(팀즈는 최근 6일을 요일로 보여준다)."""
    t = str(text or "").lower()
    if any(w in t for w in TODAY_W):
        return today
    if any(w in t for w in YDAY_W):
        return today - timedelta(days=1)
    for w, wd in WDAY.items():
        if w in t:
            back = (today.weekday() - wd) % 7
            return today - timedelta(days=back or 7)
    return None


def iso_dt(s):
    """<time datetime="…"> 값 → 이 PC 시간대의 datetime(분까지). 팀즈 웹은 이 속성을 UTC(끝의 Z)로 준다 —
    그대로 쓰면 한국에서 9시간 어긋나 새벽 근무로 둔갑한다. LM28: owa_parse.iso_local 로(두 웹 수집기가 같은 해석)."""
    r = teams_parse.iso_local(s)
    if not r:
        return None
    d, (hh, mi) = r
    return datetime(d.year, d.month, d.day, hh, mi)


# '오전 9시 12분' 처럼 콜론 없는 표기 - 팀즈의 제목 속성(title)은 이 형태로 자주 온다.
# 메일 쪽 해석기(RE_TIME)는 콜론·마침표만 받으므로 여기서 '9:12' 로 바꿔 넘긴다.
# 메일 수집기를 고치면 이미 검증된 메일 해석에 위험이 가므로 팀즈 쪽에서만 정규화한다.
RE_HM_WORD = re.compile(r"(?<!\d)(\d{1,2})\s*[시時时]\s*(\d{1,2})\s*[분分]")
RE_H_WORD = re.compile(r"(?<!\d)(\d{1,2})\s*[시時时](?!\s*\d|간)")


def hm_words(s):
    s = RE_HM_WORD.sub(lambda m: f"{m.group(1)}:{int(m.group(2)):02d}", str(s or ""))
    return RE_H_WORD.sub(lambda m: m.group(1) + ":00", s)


def stamp(head, body, cur_date, d0, d1, today):
    """(날짜, 시각) 을 뽑는다 → (datetime, 'iso'|'full'|'sep'|'rel') 또는 (None, 사유).

    ★ 날짜는 **머리 조각(head)에서만** 찾는다. head = <time datetime> · 타임스탬프 · title 속성 ·
    aria-label 처럼 화면이 '이 메시지의 시각' 이라고 말해 주는 것들이고, body 는 본문이다.
    본문에는 '지난 회의(2026-06-12) 결론대로' 같은 **다른 날짜**가 흔히 적혀 있어서, 그것을 쓰면
    9월 메시지가 6월 신호가 된다 — 그러면 6월 리뷰에 하지도 않은 최근 일이 등장한다(제보).
    창 읽기 수집기는 이미 같은 이유로 헤더와 본문을 나눠 본다(Get-TeamsWindow.ps1 의 '본문의
    8/15 까지는 날짜로 보지 않는다'). 웹 쪽에도 같은 규칙을 둔다.

    날짜 구분선(cur_date)은 화면이 직접 알려 준 그 날이라 **본문 추측보다 항상 앞선다**.
    날짜를 끝내 못 짚으면 그 메시지는 버린다 — 시각만 있는 줄에 오늘 날짜를 붙이면 지난 달
    대화가 전부 오늘로 몰린다(창 읽기에서 겪은 실측 결함)."""
    head = [hm_words(x) for x in head if x]
    body = [hm_words(x) for x in body if x]
    for s in head:                       # <time datetime> 가 맨 앞 — 지역 표기보다 우선(C-21)
        v = iso_dt(s)
        if v:
            return v, "iso"
    for s in head:                       # 제목 속성에 '2026년 6월 3일 오후 3:24' 같은 완전한 표기가 오는 경우
        d = find_date(s, d0, d1)
        if not d:
            continue
        hm = find_times(s)
        if hm:
            return datetime(d.year, d.month, d.day, hm[0][0], hm[0][1]), "full"
        return datetime(d.year, d.month, d.day, 12, 0), "full"
    # 시각은 본문 앞머리에서 와도 된다(화면이 '홍길동 오후 3:24' 를 한 덩어리로 그리는 스킨) —
    # 날짜만 본문에서 오면 안 된다.
    hm = None
    for s in head + body:
        hm = find_times(s)
        if hm:
            break
    if not hm:
        return None, "시각 없음"
    if cur_date:                          # 날짜 구분선이 알려준 그 날 (팀즈 웹은 날짜마다 구분선을 그린다)
        return datetime(cur_date.year, cur_date.month, cur_date.day, hm[0][0], hm[0][1]), "sep"
    for s in head:
        d = rel_date(s, today)
        if d:
            return datetime(d.year, d.month, d.day, hm[0][0], hm[0][1]), "rel"
    return None, "날짜 없음"


RE_AUTHOR = re.compile(r"^\s*([^\d,|]{2,20}?)\s*(?:님이|님|씨)?\s*(?:,|said|says|wrote|은|는)\b")


def explicit_author(it):
    """화면이 '이 메시지의 작성자' 라고 말한 이름 — data-tid 로 잡힌 이름, 없으면 aria-label 의 첫 토큰. 없으면 ""."""
    a = (it.get("author") or "").strip()
    if 1 < len(a) <= 40:
        return a
    m = RE_AUTHOR.match(it.get("label") or "")
    if m:
        a = m.group(1).strip()
        if 1 < len(a) <= 40 and not find_times(a):
            return a
    return ""


def author_of(it, texts):
    """발신자 — data-tid 로 잡힌 이름이 우선, 없으면 aria-label 의 첫 토큰, 그래도 없으면 첫 잎 글자(이름이 맨 앞인 스킨)."""
    a = explicit_author(it)
    if a:
        return a
    for s in texts[:2]:                   # 렌더 순서상 이름이 맨 앞에 오는 스킨
        s = s.strip()
        if 1 < len(s) <= 40 and not find_times(s) and not find_date(s):
            return s
    return ""


def body_of(it, texts, author, ts):
    b = (it.get("body") or "").strip()
    if len(b) >= 3:
        return b
    drop = {_norm(author), _norm(ts)}
    out = [s for s in texts if _norm(s) not in drop and len(s.strip()) >= 2]
    return re.sub(r"\s{2,}", " ", " ".join(out)).strip()


# ── 화면 읽기 스크립트(머리 표식 /*LM28:이름*/ — 시험의 FakeTeams 가 이 표식으로 응답을 고른다) ──────────
_LIST_SELS = ['[data-tid="chat-list"] [data-tid="chat-list-item"]', '[data-tid="chat-list-item"]',
              '[data-tid="chat-list"] [role="treeitem"]', '[role="tree"] [role="treeitem"]',
              '[role="list"] [role="listitem"][data-tid]', '[role="listbox"] [role="option"]']
_MSG_SELS = ['[data-tid="chat-pane-item"]', '[data-tid="chat-pane-message"]',
             '[data-tid="message-pane"] [role="listitem"]', '[role="log"] [role="listitem"]',
             '[role="main"] [role="listitem"]']
_HEAD_SEL = ('[data-tid="chat-header-title"],[data-tid="chatTitle"],'
             '[data-tid="chat-header"] [role="heading"],[role="main"] h1')
# 공통 조각: 목록 선택자 · 대화 ID(19:…@thread / 48:notes — LM27 idOf 이식) · 목록 항목 이름 · 이름 정규화(teams_parse.norm_name 과 같은 규칙)
_JS_COMMON = ("const SELS = " + json.dumps(_LIST_SELS) + ";\n"
              "const MSG = " + json.dumps(",".join(_MSG_SELS)) + ";\n" + r"""
const idOf = e => { const c = [e.getAttribute("data-item-key"), e.getAttribute("data-conversation-id"), e.getAttribute("data-chat-id"), e.id];
  const a = e.querySelector('a[href*="/l/"]'); if (a) c.push(a.getAttribute("href"));
  for (let v of c) { v = v || ""; try { v = decodeURIComponent(v); } catch (x) {}
    const m = v.match(/(19:[^\s\/?#"']+@[A-Za-z0-9.\-]+|48:notes)/); if (m) return m[1]; }
  return ""; };
const leafs = (e, n) => [...e.querySelectorAll("span,div,p,a")].filter(x => x.childElementCount === 0)
  .map(x => (x.textContent || "").trim()).filter(Boolean).slice(0, n);
const nameOf = e => { const l = ((e.getAttribute("aria-label") || e.getAttribute("title") || "").split(/[,|·]| - /)[0] || "").trim();
  return l || (leafs(e, 1)[0] || ""); };
const nm = s => (s || "").replace(/[\s.·,()\[\]\-]+/g, "").toLowerCase();
const listEls = () => { for (const s of SELS) { const els = [...document.querySelectorAll(s)]; if (els.length) return [els, s]; } return [[], ""]; };
const findItem = (key, name) => { const els = listEls()[0];
  return (key && els.find(e => idOf(e) === key)) || (name && els.find(e => nm(nameOf(e)) === name)) || null; };
const selOf = e => { if (!e) return null; const a = e.getAttribute("aria-selected"), c = e.getAttribute("aria-current");
  if (a === "true" || (c !== null && c !== "false") || e.querySelector('[aria-selected="true"],[aria-current="page"],[aria-current="true"]')) return true;
  return (a !== null || c !== null || e.querySelector("[aria-selected],[aria-current]")) ? false : null; };
""")
JS_CHATS = r"""/*LM28:tw_list*/
(() => {
""" + _JS_COMMON + r"""
  const out = {href: location.href, how: "", n: 0, items: []};
  const [els, how] = listEls();
  out.how = how;
  window.__lm_chats = els;
  out.n = els.length;
  out.items = els.slice(0, 400).map((e, i) => ({
    idx: i, key: idOf(e),
    label: (e.getAttribute("aria-label") || e.getAttribute("title") || "").slice(0, 300),
    hdr: e.getAttribute("aria-expanded") !== null && !idOf(e),
    texts: leafs(e, 8)
  }));
  return JSON.stringify(out);
})()
"""
# 목록 한 화면 아래로 — 'end' 끝 · 'fits' 스크롤 영역 없이 전체가 보임 · 'no-scroller' 스크롤 영역 못 찾음(끝을 모른다)
JS_LIST_SCROLL = r"""/*LM28:tw_list_scroll*/
(() => {
""" + _JS_COMMON + r"""
  let el = window.__lm_listsc;
  if (!el || !el.isConnected) {
    el = null;
    let els = (window.__lm_chats || []).filter(e => e.isConnected);   // 가상 목록은 내린 뒤 앞 항목이 문서에서 빠진다 — 다시 찾는다
    if (!els.length) els = listEls()[0];
    let c = els.length ? els[0] : null;
    for (let i = 0; i < 14 && c; i++) {
      if (c.scrollHeight > c.clientHeight + 20 && getComputedStyle(c).overflowY !== "visible") { el = c; break; }
      c = c.parentElement;
    }
    if (!el) {
      if (!els.length) return "no-list";
      const r = els[els.length - 1].getBoundingClientRect();
      return (r.bottom <= window.innerHeight + 2) ? "fits" : "no-scroller";
    }
    window.__lm_listsc = el;
  }
  const before = el.scrollTop;
  el.scrollTop = el.scrollTop + Math.max(200, el.clientHeight - 60);
  el.dispatchEvent(new Event("scroll", {bubbles: true}));
  return el.scrollTop > before ? "scrolled" : "end";
})()
"""
JS_LIST_TOP = r"""/*LM28:tw_list_top*/
(() => { const el = window.__lm_listsc; if (!el || !el.isConnected) return "none";
  el.scrollTop = 0; el.dispatchEvent(new Event("scroll", {bubbles: true})); return "ok"; })()
"""
# 방 열기 — 대화 ID(없으면 이름)로 지금 화면의 목록에서 다시 찾는다(순번이 아니다 — 재렌더 'gone' 대응).
# 팀즈 목록은 pointerdown 으로 라우팅하는 스킨이 있어 click() 만으로는 열리지 않는다 — 전체 순서를 보낸다.
JS_OPEN = r"""/*LM28:tw_open*/
(() => {
  const KEY = __KEY__, NAME = __NAME__;
""" + _JS_COMMON + r"""
  const t = findItem(KEY, NAME);
  if (!t || !t.isConnected) return "gone";
  try { t.scrollIntoView({block: "center"}); } catch (x) {}
  const b = t.querySelector('[role="button"],a,button') || t;
  for (const ev of ["pointerdown", "mousedown", "pointerup", "mouseup", "click"]) {
    b.dispatchEvent(new MouseEvent(ev, {bubbles: true, cancelable: true, view: window}));
  }
  window.__lm_target = t;
  return "ok";
})()
"""
# 대화 화면 상태(숫자·짧은 제목만): 메시지 수 · 머리 제목 · 연 목록 항목의 선택 상태(aria-selected·aria-current — 없으면 null)
JS_PANE = r"""/*LM28:tw_pane*/
(() => {
  const KEY = __KEY__, NAME = __NAME__;
""" + _JS_COMMON + r"""
  const n = document.querySelectorAll(MSG).length;
  const head = document.querySelector('__HEAD__');
  let t = window.__lm_target;
  if (!t || !t.isConnected) t = findItem(KEY, NAME);
  return JSON.stringify({n: n, chat: head ? ((head.getAttribute("title") || head.textContent || "").trim()).slice(0, 120) : "",
                         sel: selOf(t)});
})()
""".replace("__HEAD__", _HEAD_SEL)
JS_MSGS = r"""/*LM28:tw_msgs*/
(() => {
""" + _JS_COMMON + r"""
  const out = {href: location.href, how: "", chat: "", n: 0, items: []};
  const SEP = '[role="separator"],[data-tid*="divider"]';
  let msel = "";
  for (const s of MSG.split(",")) { if (document.querySelector(s)) { msel = s; break; } }
  if (!msel) return JSON.stringify(out);
  out.how = msel;
  const head = document.querySelector('__HEAD__');
  out.chat = head ? ((head.getAttribute("title") || head.textContent || "").trim()).slice(0, 120) : "";
  for (const e of document.querySelectorAll(msel + "," + SEP)) {   // 문서 순서 — 구분선이 제자리에 온다
    if (!e.matches(msel)) {
      const s = (e.textContent || "").trim();
      if (s && s.length <= 60) out.items.push({t: "sep", text: s});
      continue;
    }
    const au = e.querySelector('[data-tid="message-author-name"],[data-tid="messageAuthorName"]');
    const ts = e.querySelector('[data-tid="message-timestamp"],time');
    const bd = e.querySelector('[data-tid="messageBodyContent"],[id^="content-"]');
    const cls = (typeof e.className === "string") ? e.className : ((e.className && e.className.baseVal) || "");
    const mine = /ChatMyMessage|message-mine|myMessage/i.test(cls) || !!e.querySelector('[class*="ChatMyMessage"],[class*="myMessage"]');
    const other = !mine && (/ChatMessage/i.test(cls) || !!e.querySelector('[class*="ChatMessage"]'));
    out.items.push({t: "msg", mid: e.getAttribute("data-mid") || (bd && bd.id) || "",
      label: (e.getAttribute("aria-label") || "").slice(0, 400),
      author: au ? (au.textContent || "").trim() : "",
      ts: ts ? ((ts.getAttribute("title") || ts.getAttribute("datetime") || ts.textContent || "").trim()) : "",
      iso: [...e.querySelectorAll("time[datetime]")].map(x => x.getAttribute("datetime")).filter(Boolean).slice(0, 3),
      titles: [...e.querySelectorAll("[title]")].map(x => (x.getAttribute("title") || "").trim()).filter(Boolean).slice(0, 6),
      body: bd ? (bd.textContent || "").trim().slice(0, 600) : "",
      texts: leafs(e, 20), mine: mine ? true : (other ? false : null)});
  }
  out.n = out.items.filter(x => x.t === "msg").length;
  return JSON.stringify(out);
})()
""".replace("__HEAD__", _HEAD_SEL)
# 위로 한 화면 — {r: scrolled|top|no-scroller, how, h·n·f: 되감기 **전** 높이·메시지 수·맨 위 메시지(로드 확인의 기준)}.
# 스크롤 영역은 '실제로 움직이는' 요소만(scrollTop 을 1 바꿔 보고 되돌린다) — overflow:visible 조상을 맨 위로 오판하지 않게(F-06).
# __DEEP__=1 이면 다시 찾기: 메시지의 모든 조상(overflow 표기 무관)과 문서 스크롤까지 본다. 찾은 요소는 표식을 달아 다음에 먼저 쓴다.
JS_SCROLL_UP = r"""/*LM28:tw_scroll_up*/
(() => {
  const DEEP = __DEEP__;
""" + _JS_COMMON + r"""
  const moves = e => { if (!e || !e.isConnected || e.scrollHeight <= e.clientHeight + 20) return false;
    const t = e.scrollTop; e.scrollTop = t - 1; let ok = e.scrollTop !== t;
    if (!ok) { e.scrollTop = t + 1; ok = e.scrollTop !== t; }
    e.scrollTop = t; return ok; };
  const first = () => { const m = document.querySelector(MSG); return m ? ((m.getAttribute("data-mid") || "") + "|" + (m.textContent || "").trim().slice(0, 60)) : ""; };
  let el = document.querySelector("[data-lm28-scroller]"), how = "marked";
  if (!moves(el)) { el = null; how = ""; }
  if (!el) {
    for (const s of ['[data-tid="message-pane-list-viewport"]', '[data-tid="message-pane"]', '[role="log"]']) {
      const e = document.querySelector(s); if (moves(e)) { el = e; how = s; break; } }
  }
  if (!el) {
    let m = document.querySelector(MSG);
    while (m && m !== document.body) {
      if (getComputedStyle(m).overflowY !== "visible" && moves(m)) { el = m; how = "ancestor"; break; }
      m = m.parentElement;
    }
  }
  if (!el && DEEP) {
    let m = document.querySelector(MSG);
    while (m && m !== document.documentElement) { if (moves(m)) { el = m; how = "deep-ancestor"; break; } m = m.parentElement; }
    if (!el && moves(document.scrollingElement)) { el = document.scrollingElement; how = "document"; }
  }
  if (!el) return JSON.stringify({r: "no-scroller", how: "", h: 0, n: document.querySelectorAll(MSG).length, f: first()});
  document.querySelectorAll("[data-lm28-scroller]").forEach(x => { if (x !== el) x.removeAttribute("data-lm28-scroller"); });
  try { el.setAttribute("data-lm28-scroller", "1"); } catch (x) {}
  const base = {h: el.scrollHeight, n: document.querySelectorAll(MSG).length, f: first()};
  const before = el.scrollTop;
  // 0 으로 자르지 않는다 — 아래에서 쌓는(column-reverse) 목록은 맨 아래가 0 이고 위로 갈수록 음수다(브라우저가 범위를 알아서 자른다)
  el.scrollTop = el.scrollTop - Math.max(400, el.clientHeight - 60);
  el.dispatchEvent(new Event("scroll", {bubbles: true}));
  if (el.scrollTop >= before) { try { el.dispatchEvent(new WheelEvent("wheel", {deltaY: -400, bubbles: true})); } catch (x) {} }
  return JSON.stringify({r: el.scrollTop < before ? "scrolled" : "top", how: how, h: base.h, n: base.n, f: base.f});
})()
"""
# 지난 메시지가 붙었는지 — 표식 단 스크롤 영역의 높이 · 메시지 수 · 맨 위 메시지
JS_HEIGHT = r"""/*LM28:tw_height*/
(() => {
""" + _JS_COMMON + r"""
  const el = document.querySelector("[data-lm28-scroller]");
  const m = document.querySelector(MSG);
  return JSON.stringify({h: el ? el.scrollHeight : 0, n: document.querySelectorAll(MSG).length,
                         f: m ? ((m.getAttribute("data-mid") || "") + "|" + (m.textContent || "").trim().slice(0, 60)) : ""});
})()
"""


def _open_js(js, room):
    return js.replace("__KEY__", json.dumps(room.get("key") or "")).replace("__NAME__", json.dumps(room.get("nname") or ""))


class Browser:
    def __init__(self):
        spec = importlib.util.spec_from_file_location("_ca", os.path.join(ROOT, "tools", "copilot_auto.py"))
        self.ca = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.ca)
        self.cfg = self.ca.load_cfg()
        self.port = self.cfg["port"]
        self.cdp = None
        self.own_tab = ""          # LM28: 이 수집기가 /json/new 로 연 탭 id — 끝에 이것만 닫는다(사람·다른 작업의 탭은 두기)
        self.reason = ""           # LM28: 로그인·기동 실패 사유 코드(LMSTATUS reason)

    def start(self):
        if not self.ca.ensure_edge(self.cfg):
            self.reason = self.ca.LAST.get("reason") or "R-EDGELAUNCH"     # R-EDGEPOL·R-EDGEFOREIGN·R-EDGELAUNCH(WP5)
            return False
        ws = None
        for t in [t for t in self.ca.http_json(self.port, "/json") if t.get("type") == "page"]:
            # LM28: 호스트 정확 일치(부분 문자열 금지 — C-36). 개인용 Teams 탭은 쓰지 않는다.
            if self.ca.host_in(self.ca._host(t.get("url")), HOSTS):
                ws = t["webSocketDebuggerUrl"]
                break
        if not ws:
            # 새 탭에서 연다 — Copilot 탭(판정에 쓰는 대화 맥락)을 건드리지 않기 위해서다
            for method in ("PUT", "GET"):
                try:
                    t = self.ca.http_json(self.port, "/json/new?" + quote(TEAMS_URL, safe=""), method=method)
                    ws = t["webSocketDebuggerUrl"]
                    self.own_tab = str(t.get("id") or "")
                    break
                except Exception:
                    continue
        if not ws:
            self.reason = "R-EDGELAUNCH"
            return False
        self.cdp = self.ca.CDP(ws)
        try:
            self.cdp.call("Page.enable")
        except Exception:
            pass
        return True

    def href(self):
        try:
            return str(self.cdp.eval("location.href"))
        except Exception:
            return ""

    def goto(self, url, wait=6.0):
        try:
            self.cdp.call("Page.navigate", {"url": url})
        except Exception:
            self.cdp.reconnect()
            self.cdp.call("Page.navigate", {"url": url})
        return self.wait_ready(wait)

    def kind(self, url):
        """탭 주소 → 'work'(팀즈 업무 호스트) · 'personal'(teams.live.com) · 그 밖은 copilot_auto.page_kind(WP5)."""
        h = self.ca._host(url)
        if self.ca.host_in(h, PERSONAL_HOSTS):
            k = "personal"
        elif self.ca.host_in(h, HOSTS):
            k = "work"
        else:
            k = self.ca.page_kind(url, self.cfg)
        if k == "personal" and not self.ca._truthy(self.cfg.get("requireWorkAccount"), True):
            return "work" if self.ca.host_in(h, HOSTS + PERSONAL_HOSTS) else "login"     # LM24 처럼(개인 계정 허용 설정)
        return k

    def _login(self, kind):
        """로그인 화면 → 'login' | 'personal'. 사유를 남기고 owner.json 에 로그인 대기를 적는다(close_own_edge 가 창을 두게 — WP5)."""
        if kind == "personal":
            self.reason = "R-PERSONAL"
        else:
            code = ""
            if kind in ("login", "adfs"):
                try:
                    code = str(self.cdp.eval(self.ca.js_aadsts(), timeout=10) or "")
                except Exception:
                    code = ""
            self.reason = self.ca.aadsts_reason(code) if code else "R-LOGIN"
        try:
            self.ca._update_owner(self.cfg, login_pending=time.strftime("%Y-%m-%d %H:%M:%S"))
        except Exception:
            pass
        return "personal" if kind == "personal" else "login"

    def wait_ready(self, settle=6.0, limit=90):
        """팀즈 웹은 첫 로드가 느리다(워크로드 셸 → 채팅). → 'login' | 'personal' | 'ok' | 'timeout'
        LM28: 로그인 판정은 주소의 부분 문자열이 아니라 호스트 판정(page_kind)으로. 팀즈가 아닌 호스트(회사 IdP 등)에서 끝까지
        머물면 로그인 대기로 본다."""
        t0 = time.time()
        kind = ""
        while time.time() - t0 < limit:
            time.sleep(1.0)
            h = self.href()
            kind = self.kind(h)
            if kind in ("login", "adfs", "personal"):
                return self._login(kind)
            if not self.ca.host_in(self.ca._host(h), HOSTS + PERSONAL_HOSTS):
                continue
            try:
                rs = self.cdp.eval("document.readyState")
                n = int(self.cdp.eval('document.querySelectorAll(\'[data-tid="chat-list-item"],'
                                      '[role="treeitem"],[role="main"]\').length') or 0)
            except Exception:
                rs, n = "", 0
            if rs == "complete" and n > 0:
                time.sleep(settle)
                kind = self.kind(self.href())
                if kind in ("login", "adfs", "personal"):
                    return self._login(kind)
                try:
                    self.ca._update_owner(self.cfg, login_pending="")
                except Exception:
                    pass
                return "ok"
        if kind in ("other", "mixed"):
            return self._login(kind)
        self.reason = "R-TIMEOUT"
        return "timeout"

    def eval_json(self, js, timeout=40):
        r = self.cdp.eval(js, timeout=timeout)
        if isinstance(r, str):
            try:
                return json.loads(r)
            except ValueError:
                return {}
        return r or {}

    def close(self, keep_tab=False):
        """CDP 연결을 닫고, 이 수집기가 연 탭만 닫는다(keep_tab — 로그인 대기면 사람이 그 탭에서 로그인한다)."""
        try:
            if self.cdp:
                self.cdp.close()
        except Exception:
            pass
        if self.own_tab and not keep_tab:
            try:
                self.ca._close_tab(self.port, self.own_tab)
            except Exception:
                pass
            self.own_tab = ""


# ── 수집 ─────────────────────────────────────────────────────────────────────
class Run:
    """한 번의 수집 — 기간·오늘·시간 예산·상한·계수(LMSTATUS counts)·화면 진단(selector_diag). 시험은 today·deadline 을 넘긴다."""

    def __init__(self, d0, d1, today=None, deadline=None, max_chats=MAX_CHATS, max_scroll=MAX_SCROLL, selfs=None,
                 ctx=None):
        self.d0, self.d1 = d0, d1
        self.today = today or date.today()
        self.deadline = deadline
        self.max_chats = max(0, int(max_chats))
        self.max_scroll = max(1, int(max_scroll))
        self.selfs = selfs or {"나", "you", "본인", "me", "자신"}
        self.ctx = ctx
        self.timed_out = False
        self.c = {"rooms_listed": 0, "list_end": False, "opened": 0, "complete": 0, "incremental_ok": 0,
                  "cut_budget": 0, "cut_no_scroller": 0, "roomgone": 0, "rows_new": 0, "teams_present": False,
                  "skipped_old": 0, "not_opened": 0, "unchanged_skip": 0, "pages": 0, "scrolls": 0, "dup_other": 0,
                  "no_time": 0, "no_body": 0, "no_author": 0}
        self.sd = {}

    def out_of_time(self):
        if self.deadline is not None and _mono() > self.deadline:
            self.timed_out = True
            return True
        return False

    def bump(self, k, n=1):
        self.c[k] = self.c.get(k, 0) + n


def chat_name(item):
    """대화방 이름 — aria-label 의 첫 조각이 대개 상대/팀 이름이다. 시각·미리보기 조각은 버린다."""
    lb = (item.get("label") or "").strip()
    if lb:
        head = re.split(r"[,|·]| - ", lb)[0].strip()
        if 1 < len(head) <= 60 and not find_times(head):
            return head
    for s in (item.get("texts") or []):
        s = s.strip()
        if 1 < len(s) <= 60 and not find_times(s) and not find_date(s):
            return s
    return ""


def last_activity(item, today):
    """목록 항목의 마지막 활동 → (date, (시, 분)|None) | None — 날짜·시각뿐인 잎 글자('오후 3:12'·'어제'·'화요일'·'10/5')만 본다
    (미리보기 속 '3/5 보고' 는 날짜가 아니다 — owa_parse.list_when)."""
    texts = [str(x) for x in (item.get("texts") or []) if owa_parse.is_datetime_text(x)]
    r = owa_parse.list_when(texts, today) if texts else None
    if not r:
        r = owa_parse.list_when(owa_parse.frags_of(item.get("label")), today)
    return r


def _preview(item, name):
    """미리보기 해시 — 이름·날짜 조각을 뺀 잎 글자(없으면 aria-label 조각). 원문은 남기지 않는다."""
    parts = [str(x).strip() for x in (item.get("texts") or [])]
    if not parts:
        parts = owa_parse.frags_of(item.get("label"))
    keep = [p for p in parts if p and _norm(p) != _norm(name) and not owa_parse.is_datetime_text(p)]
    if not keep:
        return ""
    return hashlib.sha1(teams_parse.clean(" ".join(keep)).encode("utf-8")).hexdigest()[:12]


def _room_of(item, run):
    name = chat_name(item)
    key = str(item.get("key") or "")
    ident = key or ("n:" + _norm(name))
    la = last_activity(item, run.today)
    return {"rid": teams_parse.room_id(ident), "ident": ident, "key": key, "name": name, "nname": _norm(name),
            "label": str(item.get("label") or ""), "last": la[0] if la else None, "preview": _preview(item, name),
            "verdict": None, "read_to": None}


def list_all(br, run):
    """목록을 가상 스크롤로 끝까지 → (방 목록, 끝에 닿았나, 선택자). 새 이름 0 화면 LIST_STALL 번 · 'end'·'fits' 면 끝.
    상한(max_chats, 0 = 무제한)에 닿거나 스크롤 영역을 못 찾으면 끝이 아니다(F-07)."""
    rooms, seen, stall, how = [], set(), 0, ""
    for _ in range(LIST_SCREENS):
        if run.out_of_time():
            return rooms, False, how
        pg = br.eval_json(JS_CHATS) or {}
        how = how or str(pg.get("how") or "")
        items = [it for it in (pg.get("items") or []) if isinstance(it, dict)]
        new = 0
        for it in items:
            if it.get("hdr"):
                run.bump("list_headers")          # 구역 머리(즐겨찾기·최근 — 펼침 단추)는 방이 아니다
                continue
            r = _room_of(it, run)
            if r["ident"] == "n:":
                run.bump("list_noname")
                continue
            if r["ident"] in seen:
                continue
            seen.add(r["ident"])
            rooms.append(r)
            new += 1
            if run.max_chats and len(rooms) >= run.max_chats:
                run.bump("list_capped")
                return rooms, False, how
        if not items:
            return rooms, False, how
        stall = 0 if new else stall + 1
        if stall >= LIST_STALL:
            return rooms, True, how
        r = str(br.cdp.eval(JS_LIST_SCROLL) or "")
        if r in ("end", "fits"):
            return rooms, True, how
        if r != "scrolled":
            run.bump("list_" + re.sub(r"\W", "_", r or "none"))
            return rooms, False, how
        _sleep(0.6 if new else 1.5)              # 새 이름이 없던 화면 뒤에는 목록이 채워질 시간을 더 준다(자리표시자만 보인 화면)
    return rooms, False, how


def _pane(br, room):
    p = br.eval_json(_open_js(JS_PANE, room)) or {}
    sel = p.get("sel")
    return {"n": int(p.get("n") or 0), "chat": str(p.get("chat") or "").strip(),
            "sel": sel if isinstance(sel, bool) else None}


def _title_names(room):
    """방 이름 후보(정규화) — 목록 이름, 그리고 aria-label 앞 조각 1~4개를 이은 것(단체방 머리 'A, B, C' 와 맞춘다)."""
    out = {room.get("nname") or ""}
    parts = [x.strip() for x in re.split(r"[,|·]", room.get("label") or "") if x.strip()]
    for k in range(1, min(4, len(parts)) + 1):
        out.add(_norm(",".join(parts[:k])))
    return {x for x in out if len(x) >= 2}


def _title_ok(room, chat):
    c = _norm(chat)
    return len(c) >= 2 and c in _title_names(room)


def _seek_open(br, run, room):
    """목록에서 그 방 항목을 찾아 누른다 — 지금 화면 → 아래로 내리며 → 맨 위부터 다시. 못 찾으면 False."""
    js = _open_js(JS_OPEN, room)
    if str(br.cdp.eval(js) or "") == "ok":
        return True
    for phase in ("down", "top"):
        if phase == "top":
            br.cdp.eval(JS_LIST_TOP)
            run.bump("list_rewind")
            _sleep(0.4)
            if str(br.cdp.eval(js) or "") == "ok":
                return True
        for _ in range(SEEK_SCREENS):
            if run.out_of_time():
                return False
            s = str(br.cdp.eval(JS_LIST_SCROLL) or "")
            if s == "scrolled":
                _sleep(0.4)
            if str(br.cdp.eval(js) or "") == "ok":
                return True
            if s != "scrolled":
                break
    return False


def open_room(br, run, room, cur):
    """방을 열고 전환을 확인한다 → True(읽어도 됨) | False(R-ROOMGONE — 그 방 행 0).
    확인 규칙(F-30 · LM27 V29): 목록 항목 선택 상태(aria-selected·aria-current)가 있으면 그것이 결정한다. 없으면 머리 제목이
    그 방 이름과 같아야 하고, 화면이 앞서 확인한 다른 방 그대로가 아니어야 한다(제목만 남고 메시지가 그대로인 화면 차단).
    cur = 앞서 확인한 방 {rid, chat, n} — 첫 방이면 None."""
    if not _seek_open(br, run, room):
        run.bump("open_notfound")
        return False
    for _attempt in range(2):                     # 큰 대화·느린 회사 PC — 한 번 더 기다린다
        t_end = _mono() + OPEN_WAIT
        while True:
            _sleep(0.25)
            p = _pane(br, room)
            ok = False
            if p["n"] > 0:
                if p["sel"] is not None:
                    ok = p["sel"]
                    run.bump("open_by_sel")
                elif _title_ok(room, p["chat"]):
                    # 앞 방 화면 그대로(머리·메시지 수)면 아니다 — 단체방 'A, B, C' 를 눌렀는데 1:1 'A' 화면이 남은 경우
                    ok = not (cur is not None and cur.get("rid") != room["rid"]
                              and _norm(p["chat"]) == _norm(cur.get("chat")) and p["n"] == cur.get("n"))
                    run.bump("open_by_title" if ok else "open_same_pane")
            if ok:
                _sleep(0.4)                       # 머리가 먼저 바뀌고 메시지가 늦게 붙는 화면 — 한 번 더 숨을 고른다
                return True
            if _mono() >= t_end:
                break
    run.bump("pane_stuck")
    return False


def parse_page(page, run, chat):
    """대화 화면 한 장 → [{ident, dt?, au?, bd?, me?}] (문서 순서). 날짜를 못 짚은 메시지는 dt 없이(정체 판정용 ident 만).
    작성자: 화면이 말한 이름 → 내 말풍선이면 '나' → 직전 작성자를 잇는다(남의 말풍선이 내 말풍선 뒤면 잇지 않는다) →
    화면 전체에 작성자 표식이 없는 스킨이면 첫 잎 글자(LM24)."""
    items = [it for it in (page.get("items") or []) if isinstance(it, dict)]
    has_author = any(it.get("t") != "sep" and explicit_author(it) for it in items)
    out, cur, last_au, last_me = [], None, "", False
    for it in items:
        if it.get("t") == "sep":
            d = find_date(it.get("text"), run.d0, run.d1) or rel_date(it.get("text"), run.today)
            if d:
                cur = d
            continue
        texts = [str(x) for x in (it.get("texts") or [])]
        idsrc = str(it.get("mid") or "") or "|".join((str(it.get("label") or "")[:200], str(it.get("ts") or ""),
                                                       str(it.get("body") or "")[:200], " ".join(texts[:4])[:200]))
        m = {"ident": hashlib.sha1(idsrc.encode("utf-8")).hexdigest()[:16]}
        # 머리 조각(화면이 '이 메시지의 시각' 이라 말하는 것)과 본문을 나눠 넘긴다 — 본문 날짜를 시각으로 삼지 않는다.
        head = [str(x) for x in ((it.get("iso") or []) + [it.get("ts") or ""]
                                 + list(it.get("titles") or []) + [it.get("label") or ""])]
        dt, how = stamp(head, texts[:3], cur, run.d0, run.d1, run.today)
        mine = it.get("mine")
        au = explicit_author(it)
        if mine is True:
            au = au or "나"
        elif not au:
            if has_author:
                if last_au and not (mine is False and last_me):
                    au = last_au
            else:
                au = author_of(it, texts)
        if au:
            last_au, last_me = au, (mine is True or _norm(au) in run.selfs)
        if not dt:
            run.bump("no_time")
            out.append(m)
            continue
        if not au:
            run.bump("no_author")                  # 작성자 머리가 화면 위에 있다 — 더 되감으면 그때 읽힌다
            out.append(m)
            continue
        bd = body_of(it, texts, au, it.get("ts") or "")
        if len(bd) < 3:
            run.bump("no_body")
            out.append(m)
            continue
        m.update(dt=dt, au=au, bd=bd, how=how, me=(mine is True or _norm(au) in run.selfs), chat=chat)
        out.append(m)
    return out


def _height(br):
    p = br.eval_json(JS_HEIGHT) or {}
    return {"h": int(p.get("h") or 0), "n": int(p.get("n") or 0), "f": str(p.get("f") or "")}


def _wait_growth(br, base, limit):
    """지난 메시지가 붙을 때까지(높이·메시지 수·맨 위 메시지가 바뀜) 확인하며 기다린다 → True | False(limit 초 동안 그대로)."""
    t_end = _mono() + limit
    while True:
        _sleep(0.4)
        p = _height(br)
        if p["h"] > base.get("h", 0) or p["n"] != base.get("n", 0) or p["f"] != base.get("f", ""):
            return True
        if _mono() >= t_end:
            return False


def _scroll_js(deep):
    return JS_SCROLL_UP.replace("__DEEP__", "1" if deep else "0")


def scroll_up(br, run):
    """위로 한 화면 → 'scrolled'(또는 맨 위에서 지난 메시지가 더 붙음) | 'top_confirmed' | 'no_scroller'.
    'top' 이면 TOP_WAIT 초씩 TOP_CONFIRM 번 로드를 기다린다 — 그동안 한 번도 늘지 않아야 맨 위 확인(W1-05).
    'no-scroller' 면 스크롤되는 조상을 다시 찾는다(F-06) — 그래도 없으면 no_scroller('처음까지 읽음'이 아니다)."""
    r = br.eval_json(_scroll_js(False)) or {}
    if r.get("r") not in ("scrolled", "top"):    # 'no-scroller' — 또는 스크립트 오류로 빈 응답: 맨 위로 보면 안 된다(F-06)
        run.bump("scroll_refind")
        r = br.eval_json(_scroll_js(True)) or {}
        if r.get("r") not in ("scrolled", "top"):
            return "no_scroller"
        run.bump("scroll_refound")
    if r.get("how"):
        run.sd["how_scroll"] = str(r["how"])
    base = {"h": int(r.get("h") or 0), "n": int(r.get("n") or 0), "f": str(r.get("f") or "")}
    if r.get("r") == "scrolled":
        _wait_growth(br, base, SCROLL_WAIT)
        return "scrolled"
    for _ in range(TOP_CONFIRM):
        if _wait_growth(br, base, TOP_WAIT):
            run.bump("top_loaded")             # 맨 위에서 기다렸더니 지난 메시지가 붙었다 — 맨 위가 아니었다
            return "scrolled"
        r2 = br.eval_json(_scroll_js(False)) or {}
        if r2.get("r") == "scrolled":
            return "scrolled"
    return "top_confirmed"


def _usable(st, run):
    """지난 확인(newest_read)으로 증분을 해도 되는가 — 확인한 구간이 이번 기간 시작을 덮을 때만."""
    return bool(st.get("newest_read")) and bool(st.get("oldest")) and str(st["oldest"]) <= run.d0.isoformat()


def read_room(br, run, room, st):
    """한 방을 맨 아래(최신)부터 위로 되감으며 읽는다 → (rows, events, newest(해시, 날짜)|None, pages).
    멈춤: 지난 newest_read 와 겹침(overlap) · 기간 시작 전 날짜(reached_d0) · 맨 위 확인 · 스크롤 영역 없음 · 정체 · 되감기 상한 ·
    예산 · 머리 제목이 다른 방으로 바뀜(gone — 그 방 행 0)."""
    prev = st.get("newest_read") if _usable(st, run) else ""
    rows, seen, events = {}, set(), set()
    stall = scrolls = pages = 0
    newest, oldest = None, None
    chat, head0 = room["name"], ""
    while True:
        if run.out_of_time():
            events.add("budget")
            break
        page = br.eval_json(JS_MSGS) or {}
        pages += 1
        run.bump("pages")
        if page.get("how"):
            run.sd["how_msg"] = str(page["how"])
        head = _norm(page.get("chat"))
        if head and head0 and head != head0:
            events.add("gone")                   # 읽는 사이 다른 방이 열렸다 — 이 방 것으로 적지 않는다
            rows = {}
            break
        head0 = head0 or head
        if page.get("chat") and _title_ok(room, page.get("chat")):
            chat = str(page["chat"]).strip()
        new = 0
        for m in parse_page(page, run, chat):
            if m["ident"] in seen:
                continue
            seen.add(m["ident"])
            new += 1
            if "dt" not in m:
                continue
            dt = m["dt"]
            day, hm = dt.date(), dt.strftime("%H:%M")
            h = teams_parse.msg_hash(day, hm, m["au"], m["bd"], run.ctx)
            if newest is None or dt >= newest[0]:
                newest = (dt, h)
            oldest = day if oldest is None else min(oldest, day)
            if prev and h == prev:
                events.add("overlap")
            if run.d0 <= day <= run.d1:
                k = teams_parse.key_of(day, hm, m["au"], m["chat"], m["bd"], run.ctx)
                rows.setdefault(k, {"time": dt.strftime("%Y-%m-%d %H:%M"), "from": m["au"], "chat": m["chat"],
                                    "kind": "sent" if m["me"] else "msg", "summary": m["bd"][:SUMMARY_MAX]})
        if "overlap" in events:                  # 지난 실행이 읽은 데까지 이어졌다(겹침으로 검증) — 더 되감을 이유가 없다
            break
        if oldest is not None and oldest < run.d0:
            events.add("reached_d0")             # 기간보다 오래된 데까지 왔다
            break
        stall = 0 if new else stall + 1
        if stall >= ROOM_STALL:
            events.add("stall")
            break
        if scrolls >= run.max_scroll:
            events.add("max_scroll")
            break
        r = scroll_up(br, run)
        if r == "no_scroller":
            events.add("no_scroller")            # 첫 실측: 이걸 top 으로 보아 방마다 한 화면만 읽고 1월부터 다 읽은 것으로 적었다
            break
        if r == "top_confirmed":
            events.add("top_confirmed")
            break
        scrolls += 1
        run.bump("scrolls")
    nw = (newest[1], newest[0].date().isoformat()) if newest else None
    return list(rows.values()), events, nw, pages


def next_state(st, verdict, events, newest, room, run):
    """방 커서 갱신 — newest_read 는 complete·incremental_ok 일 때만 앞으로 옮긴다. 잘린 방은 상태만 바꾸고 지난 확인 구간
    (oldest·newest_read)을 그대로 둔다(다음 실행이 그 구간과 겹치면 incremental_ok)."""
    st = dict(st or {})
    st["status"] = verdict
    st["t"] = run.today.isoformat()
    if verdict in teams_parse.VERIFIED:
        if verdict == "complete":
            st["oldest"] = (teams_parse.TOP_DATE.isoformat() if "top_confirmed" in events and "reached_d0" not in events
                            else run.d0.isoformat())
        if newest:
            st["newest_read"], st["newest_day"] = newest
        st["read_day"] = run.today.isoformat()
        if room.get("last") is not None:
            st["list_day"] = room["last"].isoformat()
            st["list_prev"] = room.get("preview") or ""
    return st


def _unchanged(room, st, run):
    """목록의 마지막 활동 날짜·미리보기가 지난 확인 때와 같고, 그 확인이 마지막 활동 날 **다음 날 이후**였다 → 새 메시지 없음
    (열지 않는다). 확인한 날과 마지막 활동 날이 같으면 그 뒤 같은 날 온 메시지가 미리보기를 안 바꿨을 수 있어 연다.
    오늘 활동한 방은 늘 연다."""
    if not _usable(st, run) or room.get("last") is None or room["last"] >= run.today or not room.get("preview"):
        return False
    last = room["last"].isoformat()
    return (st.get("list_day") == last and st.get("list_prev") == room["preview"]
            and str(st.get("read_day") or "") > last)


# ── 저장 ─────────────────────────────────────────────────────────────────────
def _esc(s):
    s = re.sub(r"[\r\n]+", " ", str(s or ""))
    return '"' + s.replace('"', '""') + '"' if ("," in s or '"' in s) else s


class Store:
    """teams_web.csv 누적 저장 — 덮어쓰지 않는다(이 파일은 실행할 때마다 그 시점에 보이는 대화만 담는다). 방마다 add → flush.
    중복은 teams_parse.key_of(날짜·시각·보낸이·정제 방·정제 요지 40자)로 — 다른 teams_*.csv(Graph·창 읽기)와 겹치는 메시지도
    다시 적지 않는다."""

    def __init__(self, path, force=False, ctx=None):
        self.path, self.ctx = path, ctx
        self.rows, self.keys, self._other = [], set(), None
        if os.path.exists(path) and not force:
            try:
                with open(path, encoding="utf-8-sig", errors="replace", newline="") as f:
                    for r in csv.DictReader(f):
                        if not r.get("time") or None in r.values():
                            continue
                        k = teams_parse.row_key(r.get("time"), r.get("from"), r.get("chat"), r.get("summary"), ctx)
                        if k in self.keys:
                            continue
                        self.keys.add(k)
                        self.rows.append([r.get("time") or "", r.get("from") or "", r.get("chat") or "",
                                          r.get("kind") or "", r.get("replied_time") or "", r.get("summary") or ""])
            except OSError:
                pass

    def other_keys(self):
        """이미 모아 둔 다른 teams_*.csv 전부의 열쇠 — Graph·창 읽기와 겹치는 메시지를 다시 적지 않는다."""
        if self._other is None:
            self._other = set()
            for p in glob.glob(os.path.join(os.path.dirname(self.path), "teams_*.csv")):
                if os.path.abspath(p) == os.path.abspath(self.path):
                    continue
                try:
                    with open(p, encoding="utf-8-sig", errors="replace", newline="") as f:
                        for r in csv.DictReader(f):
                            if r.get("time"):
                                self._other.add(teams_parse.row_key(r.get("time"), r.get("from"), r.get("chat"),
                                                                    r.get("summary"), self.ctx))
                except OSError:
                    continue
        return self._other

    def add(self, rows):
        added = dup = 0
        other = self.other_keys()
        for r in rows:
            k = teams_parse.row_key(r["time"], r["from"], r["chat"], r["summary"], self.ctx)
            if k in self.keys:
                continue
            self.keys.add(k)
            if k in other:                      # Graph·창 읽기가 이미 잡은 메시지
                dup += 1
                continue
            self.rows.append([r["time"], r["from"], r["chat"], r["kind"], "", r["summary"]])
            added += 1
        return added, dup

    def flush(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.rows.sort(key=lambda x: x[0])
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
            f.write(HDR + "\n")
            for r in self.rows:
                f.write(",".join(_esc(c) for c in r) + "\n")
        os.replace(tmp, self.path)
        return len(self.rows)


def state_ver(cfg):
    try:
        ep = int(((cfg.get("collect") or {}).get("cursorEpoch")) or 1)
    except (TypeError, ValueError, AttributeError):
        ep = 1
    return f"{COLLECTOR_VER}|{ep}"


def state_load(path, ver):
    """→ (rooms 상태 dict, 폐기했나). 판·cursorEpoch(ver)가 다르면 버리고 처음부터 읽는다."""
    try:
        with open(path, encoding="utf-8-sig") as f:
            o = json.load(f)
    except (OSError, ValueError):
        return {}, False
    if not isinstance(o, dict) or o.get("ver") != ver or not isinstance(o.get("rooms"), dict):
        return {}, True
    return {k: v for k, v in o["rooms"].items() if isinstance(v, dict)}, False


def state_save(path, ver, rooms):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"ver": ver, "rooms": rooms}, f, ensure_ascii=False, indent=0)
        os.replace(tmp, path)
    except OSError:
        pass


def collect(br, run, state, store, save_state=None):
    """목록 → 방 순서(잘린 방 먼저) → 방마다 열기·확인·되감기·저장. → (방 목록, 목록 끝, 목록 선택자)
    state: 방 커서 dict(rid → 상태, 제자리에서 갱신) · save_state(): 방마다 커서를 파일에 남기는 함수(없으면 생략)."""
    rooms, list_end, how = list_all(br, run)
    run.c["rooms_listed"] = len(rooms)
    run.c["list_end"] = bool(list_end)
    run.c["teams_present"] = bool(rooms)
    run.sd["how_list"] = how
    log(f"대화 목록 {len(rooms)}개 (선택자 {how or '못 찾음'}{' · 끝까지' if list_end else ' · 끝 미확인'})")
    todo = []
    for r in rooms:
        if r["last"] is not None and r["last"] < run.d0:
            run.bump("skipped_old")              # 마지막 활동이 기간 시작 전 — 열지 않는다
        else:
            todo.append(r)
    first = [r for r in todo if (state.get(r["rid"]) or {}).get("status") in CUT_STATES]
    order = first + [r for r in todo if r not in first]
    cur = None
    for i, room in enumerate(order):
        if run.out_of_time():
            run.bump("not_opened", len(order) - i)
            break
        st = state.get(room["rid"]) or {}
        if _unchanged(room, st, run):
            room["verdict"], room["read_to"] = "incremental_ok", teams_parse._as_date(st.get("oldest"))
            run.bump("unchanged_skip")
            run.bump("incremental_ok")
            continue
        run.bump("opened")
        events, rows, newest, pages = set(), [], None, 0
        try:
            if open_room(br, run, room, cur):
                p = _pane(br, room)
                cur = {"rid": room["rid"], "chat": p["chat"], "n": p["n"]}
                rows, events, newest, pages = read_room(br, run, room, st)
            else:
                events.add("gone")
        except Exception as e:  # noqa: BLE001 — 화면 연결 오류(CDP 시간 초과 등)는 이 방만 '잘림'으로 — 읽음으로 적지 않는다
            run.bump("room_error")
            run.sd["room_error"] = type(e).__name__
            events, rows, newest = {"error"}, [], None
        v = teams_parse.room_verdict(events)
        room["verdict"] = v
        if v == "complete":
            room["read_to"] = (teams_parse.TOP_DATE if "top_confirmed" in events and "reached_d0" not in events
                               else run.d0)
        elif v == "incremental_ok":
            room["read_to"] = teams_parse._as_date(st.get("oldest"))
        run.bump(v)
        added = 0
        if rows and v != "roomgone":
            added, dup = store.add(rows)
            run.bump("dup_other", dup)
            if added:
                store.flush()                    # 방마다 저장 — 예산에 끊기거나 강제 종료돼도 앞 방은 남는다
            run.bump("rows_new", added)
        state[room["rid"]] = next_state(st, v, events, newest, room, run)
        if save_state:
            save_state()
        log(f"  · {room['name'] or '(이름 없음)'} — {v} · 화면 {pages} → {len(rows)}건(새 {added})")
    return rooms, list_end, how


def emit_status(rc, reasons=(), counts=None, ranges=None, src="teams_web"):
    """수집기 마지막 줄(LM28 P3) — 'LMSTATUS ' + JSON 한 줄. reason 은 사유 코드를 쉼표로(첫 코드가 주 사유)."""
    rs = ",".join(dict.fromkeys(r for r in reasons if r))
    print("LMSTATUS " + json.dumps({"v": 1, "src": src, "rc": int(rc), "reason": rs, "counts": counts or {},
                                    "ranges": ranges or []}, ensure_ascii=False))
    sys.stdout.flush()


def _web(br, run, state, store, save_state):
    """전용 Edge(잠금 안)에서 읽기 → (None | (rc, 사유), 결과). 이 수집기가 연 탭만 닫는다(로그인 대기면 둔다)."""
    try:
        started = br.start()
    except Exception as e:                  # 드라이버 부재·포트 충돌 — 사슬의 다음 경로(창 읽기)로 넘긴다
        log(f"드라이버를 쓸 수 없습니다({type(e).__name__}: {str(e)[:80]}) — 다음 대체 경로로")
        return (3, "R-DRIVER"), None
    if not started:
        log("전용 Edge(디버그 포트)를 띄우지 못했습니다 — Edge 설치·config.copilotAuto.port 확인"
            + (f" ({br.reason})" if br.reason else ""))
        return (3, br.reason or "R-EDGELAUNCH"), None
    keep = False
    try:
        st = br.goto(TEAMS_URL)
        if st in ("login", "personal"):
            keep = True
            if st == "personal":
                log("전용 Edge 가 개인용 Teams(개인 Microsoft 계정) 화면입니다 — 업무 채팅이 아니므로 읽지 않습니다. 회사 계정으로 로그인하세요.")
            else:
                log("로그인 필요 — 지금 열린 전용 Edge 창의 팀즈 탭에서 회사 계정을 한 번 선택/로그인하세요 (Copilot 과 같은 창, 1회).")
            log("           로그인 뒤 [분석 실행]을 다시 누르면 이어서 읽습니다.")
            return (2, br.reason or ("R-PERSONAL" if st == "personal" else "R-LOGIN")), None
        if st != "ok":
            log("팀즈 웹 화면이 뜨지 않았습니다(네트워크·차단?) — 전용 Edge 창에서 teams.microsoft.com 이 열리는지 확인하세요.")
            return (3, "R-TIMEOUT"), None
        try:
            return None, collect(br, run, state, store, save_state)
        except Exception as e:  # noqa: BLE001 — 목록 단계의 화면 연결 오류 — 방마다 이미 저장한 것은 남는다
            log(f"팀즈 웹 읽기 중 오류({type(e).__name__}: {str(e)[:80]}) — 지금까지 읽은 방은 저장했습니다")
            return (3, "R-WEBERROR"), None
    finally:
        br.close(keep_tab=keep)


def main():
    t0 = _mono()
    d0s = arg("--from") or (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
    d1s = arg("--to") or datetime.now().strftime("%Y-%m-%d")
    d0, d1 = date.fromisoformat(d0s), date.fromisoformat(d1s)
    today = date.today()
    force = "--force" in sys.argv
    cfg = _load_cfg()
    try:
        max_chats = int(arg("--max-chats") or cfg.get("teamsWebMaxChats", MAX_CHATS))
        if max_chats < 0:
            max_chats = MAX_CHATS
    except (TypeError, ValueError):
        max_chats = MAX_CHATS
    try:
        max_scroll = int(cfg.get("teamsWebMaxScroll") or MAX_SCROLL)
        if max_scroll <= 0:
            max_scroll = MAX_SCROLL
    except (TypeError, ValueError):
        max_scroll = MAX_SCROLL
    try:
        # run.py 가 준 상한(1200초)보다 넉넉히 짧게 — 저장·정리 시간을 남긴다
        budget = float(arg("--budget") or arg("--budget-sec") or cfg.get("teamsWebBudgetSec") or 900)
    except ValueError:
        budget = 900.0
    try:                                # 키 정제 문맥 — G1(scrub_csv)과 같은 사전(고객사·협력사·본인)이어야 G1 뒤에도 키가 같다
        ctx = teams_parse.privacy.make_ctx(cfg, os.path.dirname(OUT_DIR))
    except Exception:  # noqa: BLE001 — 문맥을 못 만들면 기본 규칙으로(키가 조금 덜 맞을 뿐)
        ctx = None
    run = Run(d0, d1, today, deadline=t0 + budget, max_chats=max_chats, max_scroll=max_scroll, selfs=self_names(cfg),
              ctx=ctx)
    ver = state_ver(cfg)
    sp = os.path.join(OUT_DIR, STATE_NAME)
    state, reset = state_load(sp, ver)
    if reset:
        run.c["cursor_reset"] = 1
        log("방 커서의 판·cursorEpoch 가 달라 처음부터 읽습니다")

    if os.environ.get("LM_NO_BROWSER"):
        log("LM_NO_BROWSER 설정 — 브라우저를 띄우지 않습니다(시험용)")
        emit_status(3, ["R-NOBROWSER"], dict(run.c))
        return 3
    try:
        br = Browser()
    except Exception as e:              # 드라이버 모듈 부재 등 — 사슬의 다음 경로로 넘긴다
        log(f"드라이버를 쓸 수 없습니다({type(e).__name__}: {str(e)[:80]}) — 다음 대체 경로로")
        emit_status(3, ["R-DRIVER"], dict(run.c))
        return 3
    store = Store(os.path.join(OUT_DIR, "teams_web.csv"), force=force, ctx=run.ctx)
    try:
        with br.ca.edge_lock(br.cfg):   # 같은 전용 Edge 를 쓰는 작업(Copilot·Outlook 웹·진단)과 직렬(F-16)
            fail, res = _web(br, run, state, store, lambda: state_save(sp, ver, state))
    except br.ca.EdgeBusy as e:
        log(f"{e} — 다른 작업이 끝난 뒤 다시 실행하세요")
        emit_status(3, ["R-EDGEBUSY"], dict(run.c))
        return 3
    return finish(run, fail, res, store)


def finish(run, fail, res, store):
    """판정 → 로그·LMSTATUS. 방마다 이미 저장했으므로 여기서는 쓰지 않는다."""
    c = run.c
    c["selector_diag"] = dict(run.sd)
    ranges, reasons = [], []
    if fail:
        rc, why = fail
        reasons.append(why)
        emit_status(rc, reasons, dict(c), ranges)
        return rc
    rooms, list_end, how = res
    log(f"진단: 목록 {how or '못 찾음'} · 메시지 {run.sd.get('how_msg') or '못 찾음'} · 스크롤 {run.sd.get('how_scroll') or '-'}"
        f" · 시각 못 짚음 {c['no_time']} · 작성자 미상 {c['no_author']} · 본문 없음 {c['no_body']}")
    if not rooms:
        log("채팅 목록을 찾지 못했습니다 — 전용 Edge 창의 팀즈에서 [채팅] 탭이 열려 있는지 확인하세요.")
        reasons.append("R-WEBSEL")
        emit_status(3, reasons, dict(c), ranges)
        return 3
    ranges = teams_parse.day_ranges(rooms, list_end, run.d0, run.d1, cap=run.today)
    opened = c["opened"]
    if c["not_opened"]:
        log(f"시간 예산에 닿아 남은 대화방 {c['not_opened']}개는 다음 실행이 먼저 읽습니다 — 지금까지 읽은 것은 방마다 저장했습니다.")
    if run.timed_out:
        reasons.append("R-TIMEOUT")
    log(f"방: 읽음 {c['complete']} · 증분 {c['incremental_ok']}(그대로 {c['unchanged_skip']}) · 예산·상한에 잘림 {c['cut_budget']}"
        f" · 스크롤 영역 없음 {c['cut_no_scroller']} · 전환 실패 {c['roomgone']} · 기간 전 {c['skipped_old']}")
    try:
        shown = os.path.relpath(store.path, ROOT)
    except ValueError:              # 다른 드라이브(시험용으로 출력을 돌린 경우) - 표시일 뿐이니 죽지 않는다
        shown = store.path
    log(f"{shown} — 신규 {c['rows_new']}건 (다른 경로와 겹쳐 제외 {c['dup_other']}건) / 누적 {len(store.rows)}건")
    if opened and c["cut_no_scroller"] and c["cut_no_scroller"] + c["roomgone"] >= opened:
        reasons.insert(0, "R-WEBSEL")            # 연 방이 모두 스크롤 영역을 못 찾음 — 화면 구조가 바뀌었다
        rc = 3
    elif opened and c["roomgone"] >= opened:
        reasons.insert(0, "R-ROOMGONE")          # 어느 방도 전환을 확인하지 못함
        rc = 3
    elif c["rows_new"]:
        rc = 0
    elif not opened and not c["incremental_ok"]:
        rc = 1                                   # 기간에 활동한 방이 없다
    else:
        rc = 4
    emit_status(rc, reasons, dict(c), ranges)
    return rc


if __name__ == "__main__":
    sys.exit(main())
