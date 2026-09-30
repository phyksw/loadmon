# -*- coding: utf-8 -*-
"""
Get-TeamsWeb.py — 팀즈 웹(teams.microsoft.com)을 전용 Edge 프로필로 열어 채팅을 읽는다 (폴백).

Get-OutlookWeb.py 와 같은 방식이다: Copilot 에 쓰는 전용 Edge 프로필(data\\copilot_profile)에 회사 계정으로
한 번 로그인해 두면, **팀즈 앱이 꺼져 있어도** 동작한다. 앱 창 읽기(Get-TeamsWindow.ps1)는 화면에 그려진
부분만 UI 자동화로 긁으므로 창 크기·테마·팀즈 버전에 따라 PC 마다 0건이 되곤 했다(실측 제보). 웹 경로는
문서 구조(role·data-tid·aria-label)를 읽고 채팅 목록과 메시지를 스크롤한다. 로그인·웹 UI·시간 상한에 따라
도달 범위가 달라지므로 이 경로만으로 서버의 전체 채팅을 읽었다고 판정하지 않는다.

  python collect\\Get-TeamsWeb.py --from 2026-06-01 --to 2026-06-30 [--max-chats 200] [--force]

출력: data\\m365\\teams_web.csv   (time,from,chat,kind,replied_time,summary)
      — Graph·창 읽기 경로와 같은 스키마라 분석기(core\\extract.py 의 teams_*.csv)가 그대로 인제스트한다.
      기본 열과 함께 본문 문맥·출처·시각 정밀도를 저장하고 기존 teams_web.csv에 페이지마다 누적한다.
      data\\collection_status\\teams_web.json에 탐색 범위와 중단 이유를 기록한다.
종료 코드: 0 저장 / 1 아무것도 못 읽음 / 2 로그인 필요(전용 Edge 창에서 1회) / 3 드라이버 불가

LLM을 거치지 않고 브라우저에 표시된 내용을 읽는다. 웹 로그인과 화면 갱신에는 Microsoft 서비스 연결이
필요하며, replied_time은 웹에서도 측정할 수 없어 빈 값(미측정)으로 둔다.

화면 구조는 Microsoft 가 바꿀 수 있어 선택자를 여러 벌 두고 '무엇으로 몇 개를 잡았는지' 를 로그에 남긴다
(회사 PC 의 원문을 밖으로 보낼 수 없으므로 진단은 로그의 숫자로 한다).
시험용: LM_TEAMSWEB_FAKE=<json> 이면 브라우저 없이 그 파일의 화면 응답을 쓴다
        {"chats": <JS_CHATS 응답>, "msgs": {"<대화번호>": [<JS_MSGS 응답>, …(스크롤 회차)]}}
"""
import hashlib
import importlib.util
import io
import json
import os
import re
import sys
import time
from datetime import date, datetime, timedelta
from urllib.parse import quote, unquote, urlparse

if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, errors="replace", encoding=(
        (sys.stdout.encoding or "utf-8") if sys.stdout.isatty() else "utf-8"))  # 콘솔(bat)=콘솔 코드페이지 · 파이프(UI)=utf-8

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "core"))
from collection_state import merge_csv, read_csv, record_key, write_csv, write_status  # noqa: E402

OUT_DIR = os.path.join(ROOT, "data", "m365")
HDR = "time,from,chat,kind,replied_time,summary"
FIELDS = HDR.split(",") + ["context_excerpt", "context_truncated", "source_id", "source_kind",
                            "source_url", "conversation_id", "time_precision"]
SCOPE = "Teams 웹에서 탐색한 채팅 목록·메시지 DOM; 숨김 대화·채널·서버 전체 기록은 보장하지 않음"
TEAMS_URL = "https://teams.microsoft.com/v2/"
HOSTS = ("teams.microsoft.com", "teams.cloud.microsoft", "teams.office.com", "teams.live.com")
MAX_SCROLL = 200                # 시간 예산과 함께 적용하는 안전 상한; 도달하면 partial
SUMMARY_MAX = 200               # 창 읽기 경로와 같은 길이


def arg(flag, d=""):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv and sys.argv.index(flag) + 1 < len(sys.argv) else d


def log(msg):
    print(f"[teams-web] {msg}")
    sys.stdout.flush()


# ── 날짜·시각 해석은 메일 웹 수집기의 것을 그대로 쓴다 ────────────────────────
# 같은 회사 PC 의 같은 지역 설정에서 이미 검증된 해석기다. 여기서 다시 만들면 한·영·일·중 표기와
# 미국식/유럽식 순서를 또 틀리게 된다(메일 쪽 감사에서 이미 겪은 항목).
_spec = importlib.util.spec_from_file_location("_owa", os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                                    "Get-OutlookWeb.py"))
_owa = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_owa)
find_times = _owa.find_times
find_date = _owa.find_date

RE_ISO = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:[zZ]|[+-]\d{2}:?\d{2})?")
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
    return re.sub(r"[\s.·,()\[\]-]+", "", str(s or "")).lower()


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
    """<time datetime="…"> 값 → 이 PC 시간대의 datetime. 팀즈 웹은 이 속성을 UTC(끝의 Z)로 준다 —
    그대로 쓰면 한국에서 9시간 어긋나 새벽 근무로 둔갑한다. 시간대 표기가 있으면 지역 시간으로 옮긴다."""
    s = str(s or "").strip()
    m = RE_ISO.search(s)
    if not m:
        return None
    try:
        # A localized accessible label can surround an ISO value. Parse the
        # entire matched offset too: dropping it silently shifts the date.
        v = datetime.fromisoformat(m.group().replace("Z", "+00:00").replace("z", "+00:00"))
    except ValueError:
        return None
    if v.tzinfo is not None:
        v = v.astimezone().replace(tzinfo=None)
    return v.replace(second=0, microsecond=0)


# '오전 9시 12분' 처럼 콜론 없는 표기 - 팀즈의 제목 속성(title)은 이 형태로 자주 온다.
# 메일 쪽 해석기(RE_TIME)는 콜론·마침표만 받으므로 여기서 '9:12' 로 바꿔 넘긴다.
# 메일 수집기를 고치면 이미 검증된 메일 해석에 위험이 가므로 팀즈 쪽에서만 정규화한다.
RE_HM_WORD = re.compile(r"(?<!\d)(\d{1,2})\s*[시時时]\s*(\d{1,2})\s*[분分]")
RE_H_WORD = re.compile(r"(?<!\d)(\d{1,2})\s*[시時时](?!\s*\d|간)")


def hm_words(s):
    s = RE_HM_WORD.sub(lambda m: f"{m.group(1)}:{int(m.group(2)):02d}", str(s or ""))
    return RE_H_WORD.sub(lambda m: m.group(1) + ":00", s)


def screen_date(text, today):
    """The selected reporting year is not evidence of a rendered message year."""
    value = str(text or '')
    if re.search(r'(?<!\d)(?:19|20)\d{2}(?!\d)', value):
        return find_date(value)
    return rel_date(value, today)


def stamp(head, body, cur_date, d0, d1, today):
    """(날짜, 시각) 을 뽑는다 → (datetime, 'iso'|'full'|'sep'|'rel') 또는 (None, 사유).

    ★ 날짜는 **머리 조각(head)에서만** 찾는다. head = <time datetime> · 타임스탬프 · title 속성 ·
    aria-label 처럼 화면이 '이 메시지의 시각' 이라고 말해 주는 것들이고, body 는 본문이다.
    본문에는 '지난 회의(2026-06-12) 결론대로' 같은 **다른 날짜**가 흔히 적혀 있어서, 그것을 쓰면
    9월 메시지가 6월 신호가 된다 — 그러면 6월 리뷰에 하지도 않은 최근 일이 등장한다(제보).
    창 읽기 수집기는 이미 같은 이유로 헤더와 본문을 나눠 본다(Get-TeamsWindow.ps1 의 '본문의
    8/15 까지는 날짜로 보지 않는다'). 웹 쪽에도 같은 규칙을 둔다.

    날짜 구분선(cur_date)은 화면이 직접 알려 준 그 날이라 **본문 추측보다 항상 앞선다**.
    날짜를 끝내 못 짚으면 None을 반환해 별도 보류 저장한다. 시각만 있는 줄에 요청 기간이나
    오늘 날짜를 붙여 분석 입력으로 만들지 않는다."""
    head = [hm_words(x) for x in head if x]
    body = [hm_words(x) for x in body if x]
    for s in head:
        v = iso_dt(s)
        if v:
            return v, "iso"
    for s in head:                       # 제목 속성에 '2026년 6월 3일 오후 3:24' 같은 완전한 표기가 오는 경우
        d = screen_date(s, today)
        if not d:
            continue
        hm = find_times(s) or next((find_times(part) for part in head if find_times(part)), None)
        if hm:
            return datetime(d.year, d.month, d.day, hm[0][0], hm[0][1]), "full"
        return datetime(d.year, d.month, d.day, 12, 0), "date"
    # Body deadlines are not timestamps. Modern/legacy DOM timestamp nodes
    # supply header parts; body text is preserved separately if time is absent.
    hm = None
    for s in head:
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


def author_of(it, texts):
    """발신자 — data-tid 로 잡힌 이름이 우선, 없으면 aria-label 의 첫 토큰."""
    a = (it.get("author") or "").strip()
    if 1 < len(a) <= 40:
        return a
    m = RE_AUTHOR.match(it.get("label") or "")
    if m:
        a = m.group(1).strip()
        if 1 < len(a) <= 40 and not find_times(a):
            return a
    for s in texts[:2]:                   # 렌더 순서상 이름이 맨 앞에 오는 스킨
        s = s.strip()
        if 1 < len(s) <= 40 and not find_times(s) and not find_date(s):
            return s
    return ""


def body_of(it, texts, author, ts):
    b = (it.get("body") or "").strip()
    if b:
        return b
    drop = {_norm(author), _norm(ts)}
    out = [s for s in texts if _norm(s) not in drop and len(s.strip()) >= 2]
    return re.sub(r"\s{2,}", " ", " ".join(out)).strip()


# ── 화면 읽기 스크립트 ───────────────────────────────────────────────────────
JS_DOM = r"""
  const visible = e => !e.closest('[hidden],[aria-hidden="true"]') &&
    (!e.getClientRects || e.getClientRects().length > 0);
  const all = (s, root=document) => [...root.querySelectorAll(s)].filter(visible);
  const text = e => e ? (e.getAttribute('title') || e.textContent || '').trim() : '';
  const leafs = e => all('span,div,p,a',e).filter(x => x.childElementCount === 0)
    .map(x => (x.textContent || '').trim()).filter(Boolean);
  const headers = '[data-tid="chat-header-title"],[data-tid="chatTitle"],'
    + '[data-tid="chat-header"] [data-tid="chat-title"],[data-tid="chat-header"] [role="heading"],'
    + '[role="main"] [role="heading"][aria-level="1"],[role="main"] h1';
  const paneRoot = () => document.querySelector('[data-tid="message-pane"],[data-tid="chat-pane-list"],[role="log"]') ||
    document.querySelector('[role="main"]');
  const chatId = e => e ? (e.getAttribute('data-chat-id') ||
    (e.querySelector('[data-chat-id]') || {getAttribute:()=>''}).getAttribute('data-chat-id') || '') : '';
  const chatNodes = () => {
    const known = all('[data-tid="chat-list-item"],[data-tid="chat-list-item-row"],'
      + '[data-tid="chat-list"] [role="treeitem"],[data-tid="chat-list"] [role="option"]');
    const semantic = all('[role="treeitem"],[role="listitem"],[role="option"]').filter(e =>
      chatId(e) || e.querySelector('[data-tid="chat-list-item-title"],[data-tid="chat-title"]'));
    // Restore the earlier semantic list route. These are only candidates:
    // after clicking, the requested room must still match the message pane.
    const legacy = all('[role="tree"] [role="treeitem"],[role="listbox"] [role="option"],'
      + '[role="list"] [role="listitem"][data-tid]').filter(e =>
        (e.getAttribute('title') || e.getAttribute('aria-label')) &&
        !e.querySelector('[role="treeitem"],[role="option"],[role="listitem"]'));
    const nodes = [...new Set([...known,...semantic,...legacy])];
    // Sidebar sections can be treeitems too. Keep their leaf conversations;
    // retaining the outer section hides every child and only toggles a folder.
    return nodes.filter(e => !nodes.some(child => child !== e && e.contains(child)));
  };
  const bodySelector = '[data-tid="messageBodyContent"],[data-tid="message-body"],[data-tid="message-content"],[id^="content-"]';
  const quoteSelector = 'blockquote,[data-tid="quoted-reply"],[data-tid="quoted-message"],[data-tid="reply-preview"],[data-tid="message-quote"]';
  const quoted = e => !!e.closest(quoteSelector);
  const messageIdentity = e => e.getAttribute('data-message-id') ||
    (all('[data-message-id]',e).find(x => !quoted(x)) || {getAttribute: () => ''}).getAttribute('data-message-id') || '';
  const ownPart = (e,x) => {
    if (quoted(x)) return false;
    const owner = messageIdentity(e), nearest = x.closest('[data-message-id]');
    return !owner || !nearest || nearest.getAttribute('data-message-id') === owner;
  };
  const messageBody = e => all(bodySelector,e).find(x => ownPart(e,x));
  const timestampNodes = e => {
    const bodies = all(bodySelector,e);
    const headerPart = x => ownPart(e,x) && !bodies.some(body => body.contains(x));
    const known = all('[data-tid="message-timestamp"],[data-tid="timestamp"],[data-tid="chat-pane-message-timestamp"],time',e)
      .filter(headerPart);
    const titled = all('[title],[aria-label]',e).filter(x => headerPart(x) &&
      /\d{1,2}:\d{2}|\d{1,2}\s*[시時时]/.test((x.getAttribute('title') || '')+' '+(x.getAttribute('aria-label') || '')));
    // Older skins expose a separate clock text leaf without a data-tid.
    // Match the entire leaf; a deadline sentence in the body is not a clock.
    const clock = all('span,div,p,a',e).filter(x => x.childElementCount === 0 &&
      headerPart(x) && /^(?:(?:오전|오후|AM|PM)\s*)?\d{1,2}:\d{2}(?:\s*(?:AM|PM))?$/i.test((x.textContent || '').trim()));
    return [...new Set([...known,...titled,...clock])];
  };
  const messageSelector = '[data-tid="chat-pane-item"],[data-tid="chat-pane-message"],'
    + '[data-tid="message-pane"] [data-message-id],[data-tid="chat-pane-list"] [data-message-id],'
    + '[role="log"] [data-message-id],[role="log"] [role="listitem"],[role="log"] [role="article"],'
    + '[data-tid="message-pane"] [role="listitem"],[role="main"] [role="listitem"]';
  const messageNodes = () => {
    const nodes = all(messageSelector).filter(e => {
      if (quoted(e)) return false;
      if (!e.matches('[role="main"] [role="listitem"]') ||
          e.matches('[data-tid="chat-pane-item"],[data-tid="chat-pane-message"],[role="log"] [role="listitem"],[data-tid="message-pane"] [role="listitem"]')) return true;
      const stamps = timestampNodes(e);
      return stamps.length && (e.querySelector(bodySelector) ||
        all('span,div,p,a',e).filter(x => x.childElementCount === 0 && (x.textContent || '').trim() &&
          !stamps.some(stamp => stamp.contains(x))).length >= 2);
    });
    // A message body may itself match an older message-container selector.
    // Retain the outer message once, not an extra nested copy.
    return nodes.filter(e => !nodes.some(parent => parent !== e && parent.contains(e) &&
      (!messageIdentity(e) || !messageIdentity(parent) || messageIdentity(e) === messageIdentity(parent))));
  };
"""


def dom_script(body):
    return "(() => {\n" + JS_DOM + body + "\n})()"


JS_CHATS = dom_script(r"""
  const out = {href: location.href, how: "", n: 0, items: []};
  const els = chatNodes();
  out.how = els.length ? 'chat identity/title in list or legacy chat-list-item' : '';
  window.__lm_chats = els;
  out.n = els.length;
  out.items = els.map((e, i) => {
    const key = chatId(e) || e.getAttribute('data-item-id') ||
      (e.querySelector('a[href]') || {}).href || e.getAttribute('title') ||
      e.getAttribute('aria-label') || (e.textContent || '').trim();
    e.__lm_chat_key = key;
    e.__lm_chat_name = (e.getAttribute('title') ||
      (e.querySelector('[data-tid="chat-list-item-title"],[data-tid="chat-title"]') || {}).textContent ||
      leafs(e)[0] || e.getAttribute('aria-label') || '').trim();
    return {
    idx: i,
    key: key,
    conversation_id: chatId(e),
    name: (e.getAttribute("title") || (e.querySelector('[data-tid="chat-list-item-title"],[data-tid="chat-title"]') || {}).textContent || "").trim(),
    label: (e.getAttribute("aria-label") || e.getAttribute("title") || "").slice(0, 300),
    texts: leafs(e).slice(0, 8)
  }; });
  return JSON.stringify(out);
""")
# 팀즈 목록은 pointerdown 으로 라우팅하는 스킨이 있어 click() 만으로는 열리지 않는다 — 전체 순서를 보낸다.
JS_OPEN = r"""
(() => {
  const key = %s;
  const e = (window.__lm_chats || []).find(e => e.__lm_chat_key === key);
  if (!e) return "gone";
  try { e.scrollIntoView({block: "center"}); } catch (x) {}
  // The first button may be a More options menu, not the conversation.
  const norm = value => (value || '').replace(/\s+/g,' ').trim().toLowerCase();
  const target = [...e.querySelectorAll('[role="button"],button,a')].find(x =>
    !x.getAttribute('aria-haspopup') && norm(x.getAttribute('aria-label') || x.getAttribute('title') || x.textContent) === norm(e.__lm_chat_name));
  const t = e.querySelector('a[href*="/chat/"],a[href*="/l/chat/"]') || target || e;
  for (const ev of ["pointerdown", "mousedown", "pointerup", "mouseup", "click"]) {
    t.dispatchEvent(new MouseEvent(ev, {bubbles: true, cancelable: true, view: window}));
  }
  return "ok";
})()
"""
JS_MSGS = dom_script(r"""
  const out = {href: location.href, how: "", chat: "", n: 0, items: []};
  const messages = messageNodes(), root = paneRoot();
  if (!messages.length) return JSON.stringify(out);
  out.how = 'message identity / log semantics / legacy pane';
  out.chat = text(all(headers)[0]).slice(0, 120);
  const SEP = '[role="separator"],[data-tid*="divider"],[data-tid="date-separator"],[data-tid="message-date"]';
  for (const e of all(messageSelector + ',' + SEP)) {
    if (!messages.includes(e)) {
      if (!e.matches(SEP) || !root || !root.contains(e)) continue;
      const s = (e.textContent || "").trim();
      if (s && s.length <= 60) out.items.push({t: "sep", text: s});
      continue;
    }
    const au = all('[data-tid="message-author-name"],[data-tid="messageAuthorName"],[data-tid="message-author"]',e).find(x => ownPart(e,x));
    const stamps = timestampNodes(e);
    const ts = stamps[0];
    const bd = messageBody(e);
    out.items.push({t: "msg",
      id: messageIdentity(e) || e.getAttribute("data-item-id") || "",
      url: (e.querySelector('a[href*="/message/"]') || {}).href || "",
      label: (e.getAttribute("aria-label") || "").slice(0, 400),
      author: au ? (au.textContent || "").trim() : "",
      ts: ts ? ((ts.getAttribute("title") || ts.getAttribute("datetime") || ts.textContent || "").trim()) : "",
      iso: stamps.filter(x => x.matches('time[datetime]')).map(x => x.getAttribute("datetime")).filter(Boolean).slice(0, 3),
      titles: stamps.flatMap(x => [x.getAttribute('title'),x.getAttribute('aria-label')]).filter(Boolean).slice(0, 6),
      body: bd ? (bd.textContent || "").trim().slice(0, 20000) : "",
      texts: leafs(e).slice(0, 20)});
  }
  out.n = out.items.filter(x => x.t === "msg").length;
  return JSON.stringify(out);
""")
JS_SCROLL_UP = dom_script(r"""
  const CAND = ['[data-tid="message-pane-list-viewport"]', '[data-tid="message-pane"]', '[data-tid="chat-pane-list"]', '[role="log"]'];
  let el = null;
  for (const s of CAND) { const e = document.querySelector(s); if (e && e.scrollHeight > e.clientHeight + 20) { el = e; break; } }
  if (!el) {
    let m = messageNodes()[0];
    while (m && m !== document.body) {
      if (m.scrollHeight > m.clientHeight + 20 && getComputedStyle(m).overflowY !== "visible") { el = m; break; }
      m = m.parentElement;
    }
  }
  if (!el) return "no-scroller";
  const before = el.scrollTop;
  const minimum = getComputedStyle(el).flexDirection === 'column-reverse' ? -(el.scrollHeight-el.clientHeight) : 0;
  el.scrollTop = Math.max(minimum, el.scrollTop - Math.max(400, el.clientHeight - 60));
  el.dispatchEvent(new Event("scroll", {bubbles: true}));
  return el.scrollTop < before ? "scrolled" : "top";
""")

JS_SCROLL_CHATS = dom_script(r"""
  let el = (window.__lm_chats || [])[0] || document.querySelector('[data-tid="chat-list"],[role="tree"],[role="listbox"]');
  while (el && el !== document.body && el.scrollHeight <= el.clientHeight + 20) el = el.parentElement;
  if (!el || el === document.body) return "no-scroller";
  const before = el.scrollTop;
  el.scrollTop += Math.max(200, el.clientHeight - 40);
  el.dispatchEvent(new Event("scroll", {bubbles:true}));
  return el.scrollTop > before ? "scrolled" : "end";
""")


JS_PANE = dom_script(r"""
  const pane = paneRoot(), messages = messageNodes();
  const key = e => e ? (e.getAttribute('data-message-id') || e.getAttribute('data-item-id') ||
    (e.textContent || '').slice(0,120)) : '';
  return JSON.stringify({n: messages.length, conversation_id: chatId(pane) || chatId(document.querySelector('[role="main"][data-chat-id]')),
      busy: !!(pane && pane.querySelector('[aria-busy="true"],[role="progressbar"]')),
      fingerprint: key(messages[0])+'|'+key(messages[messages.length-1]),
      chat: text(all(headers)[0]).slice(0, 120)});
""")

JS_READY = dom_script(r"""
  const signin = all('input[type="password"],input[autocomplete="username"]');
  const busy = all('[role="progressbar"],[aria-busy="true"]').length > 0;
  const chatList = chatNodes();
  const empty = all('[role="status"],[data-tid*="empty"]').some(e =>
    /no (?:chats|conversations)|채팅이 없|대화가 없/i.test(e.textContent || ''));
  const web = all('a,button').find(e => /^(Use the web app instead|Continue on this browser|Use Teams on the web|웹 앱 사용|이 브라우저에서 계속)$/i.test(text(e)));
  const chatNav = all('[role="navigation"] button,[role="navigation"] [role="tab"],[role="tablist"] [role="tab"]').find(e =>
    /^(Chat|Chats|Chat and channels|Chats and channels|채팅|채팅 및 채널)$/i.test(e.getAttribute('aria-label') || text(e)));
  return JSON.stringify({login:signin.length > 0, busy:busy, chats:chatList.length,
    messages:messageNodes().length, empty:empty, web:!!web, chat_nav:!!chatNav});
""")

JS_OPEN_CHAT_AREA = dom_script(r"""
  const web = all('a,button').find(e => /^(Use the web app instead|Continue on this browser|Use Teams on the web|웹 앱 사용|이 브라우저에서 계속)$/i.test(text(e)));
  const nav = all('[role="navigation"] button,[role="navigation"] [role="tab"],[role="tablist"] [role="tab"]').find(e =>
    /^(Chat|Chats|Chat and channels|Chats and channels|채팅|채팅 및 채널)$/i.test(e.getAttribute('aria-label') || text(e)));
  const e = web || nav;
  if (!e) return 'unavailable'; e.click(); return 'opened';
""")


def wait_pane(br, want_change, limit):
    """화면이 준비될 때까지 '확인하며' 기다린다 — 무조건 자는 대기를 대신한다.
    want_change 는 (이전 대화방 이름, 이전 메시지 수). 둘 중 하나라도 달라지면 바로 돌아온다.
    → (메시지 수, 대화방 이름). 팀즈가 느린 PC 에서는 limit 까지 기다리므로 안전은 그대로다."""
    t0 = time.monotonic()
    last = (want_change or ("", -1))
    got = last
    while time.monotonic() - t0 < limit:
        time.sleep(0.25)
        try:
            st = br.eval_json(JS_PANE, timeout=15)
        except Exception:
            continue
        got = (str(st.get("chat") or ""), int(st.get("n") or 0), str(st.get('fingerprint') or ''))
        if got[1] > 0 and got != last and not st.get('busy'):
            return got
    return got


class DeadlineCDP:
    """Bound direct CDP calls too; bypassing eval_json must not reset the budget."""
    def __init__(self, driver, deadline):
        self.driver, self.deadline = driver, deadline

    def seconds(self, requested=5):
        end = self.deadline()
        if end is None:
            return requested
        remaining = end-time.monotonic()
        if remaining <= 0:
            raise TimeoutError('teams_web_time_budget')
        return min(requested, remaining)

    def call(self, method, params=None, timeout=5):
        return self.driver.call(method, params, timeout=self.seconds(timeout))

    def eval(self, script, timeout=5):
        return self.driver.eval(script, timeout=self.seconds(timeout))

    def reconnect(self):
        return self.driver.reconnect(timeout=self.seconds())

    def close(self):
        self.driver.close()


class Browser:
    def __init__(self):
        spec = importlib.util.spec_from_file_location("_ca", os.path.join(ROOT, "tools", "copilot_auto.py"))
        self.ca = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.ca)
        self.cfg = self.ca.load_cfg()
        self.cfg['url'] = TEAMS_URL
        self.port = self.cfg["port"]
        self.cdp = None
        self.deadline = None

    def start(self):
        if not self.ca.ensure_edge(self.cfg):
            return False
        self.port = self.cfg["port"]
        ws = None
        def remaining():
            seconds = (self.deadline or float('inf'))-time.monotonic()
            if seconds <= 0:
                raise TimeoutError('teams_web_time_budget')
            return min(5, seconds)
        for t in [t for t in self.ca.http_json(self.port, "/json", timeout=remaining()) if t.get("type") == "page"]:
            if urlparse(t.get("url") or "").hostname in HOSTS:
                ws = t["webSocketDebuggerUrl"]
                break
        if not ws:
            # 새 탭에서 연다 — Copilot 탭(판정에 쓰는 대화 맥락)을 건드리지 않기 위해서다
            for method in ("PUT", "GET"):
                try:
                    ws = self.ca.http_json(self.port, "/json/new?" + quote(TEAMS_URL, safe=""),
                                           method=method, timeout=remaining())["webSocketDebuggerUrl"]
                    break
                except Exception:
                    continue
        if not ws:
            return False
        if self.deadline and time.monotonic() >= self.deadline:
            raise TimeoutError('teams_web_time_budget')
        self.cdp = DeadlineCDP(self.ca.CDP(ws, timeout=remaining()), lambda: self.deadline)
        try:
            self.cdp.call("Page.enable")
        except Exception:
            pass
        return True

    def href(self, timeout=5):
        try:
            return str(self.cdp.eval("location.href", timeout=timeout))
        except Exception:
            return ""

    def goto(self, url, wait=6.0):
        try:
            self.cdp.call("Page.navigate", {"url": url})
        except Exception:
            self.cdp.reconnect()
            self.cdp.call("Page.navigate", {"url": url})
        return self.wait_ready(wait)

    def wait_ready(self, settle=6.0, limit=45):
        """팀즈 웹은 첫 로드가 느리다(워크로드 셸 → 채팅). → 'login' | 'ok' | 'timeout'"""
        until = min(self.deadline or float('inf'), time.monotonic() + limit)
        opened, stable, waiting_login, login_announced = False, 0, False, False
        while time.monotonic() < until:
            h = self.href(timeout=min(5, max(0.1, until-time.monotonic())))
            host = urlparse(h).hostname or ''
            if host in ('login.microsoftonline.com', 'login.live.com', 'login.microsoft.com'):
                waiting_login, stable = True, 0
                if not login_announced:
                    log('로그인 화면 확인 - 전용 Edge에서 로그인하면 이번 수집을 이어갑니다. 자동 SSO 완료도 기다립니다.')
                    login_announced = True
                time.sleep(min(0.5, max(0, until-time.monotonic())))
                continue
            try:
                state = self.eval_json(JS_READY, timeout=min(5, max(0.1, until-time.monotonic())))
            except Exception:
                state = {}
            if state.get('login'):
                waiting_login, stable = True, 0
                if not login_announced:
                    log('로그인 화면 확인 - 전용 Edge에서 로그인하면 이번 수집을 이어갑니다. 자동 SSO 완료도 기다립니다.')
                    login_announced = True
                time.sleep(min(0.5, max(0, until-time.monotonic())))
                continue
            waiting_login = False
            if state.get('chats') or state.get('messages') or (state.get('empty') and not state.get('busy')):
                stable += 1
                if stable >= 2:
                    return 'ok'
            else:
                stable = 0
                if host in HOSTS and not opened and (state.get('web') or state.get('chat_nav')):
                    self.cdp.eval(JS_OPEN_CHAT_AREA, timeout=min(5, max(0.1, until-time.monotonic())))
                    opened = True
            time.sleep(min(0.5, max(0, until-time.monotonic())))
        return 'login' if waiting_login else 'timeout'

    def eval_json(self, js, timeout=40):
        if self.deadline:
            remaining = self.deadline-time.monotonic()
            if remaining <= 0:
                raise TimeoutError('teams_web_time_budget')
            timeout = min(timeout, remaining)
        r = self.cdp.eval(js, timeout=timeout)
        if isinstance(r, str):
            try:
                return json.loads(r)
            except ValueError:
                return {}
        return r or {}

    def close(self):
        try:
            if self.cdp:
                self.cdp.close()
        except Exception:
            pass


# ── 수집 ─────────────────────────────────────────────────────────────────────
def chat_name(item):
    """대화방 이름 — aria-label 의 첫 조각이 대개 상대/팀 이름이다. 시각·미리보기 조각은 버린다."""
    if item.get("name"):
        return str(item["name"]).strip()
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


def pane_matches(item, name, pane):
    """A changing message count does not prove that the requested chat opened."""
    requested_id = str(item.get("conversation_id") or "")
    actual_id = str(pane.get("conversation_id") or "")
    if requested_id and actual_id:
        return requested_id == actual_id
    # Prefer the complete item title/name leaf. The label-derived name may be
    # only the first participant in a comma-separated group title.
    names = [item["name"]] if item.get("name") else (item.get("texts") or [])[:1]
    if not any(names) and not re.search(r"[,|·]", str(item.get("label") or "")):
        names = [name]
    actual = _norm(pane.get("chat"))
    return bool(actual and any(_norm(candidate) == actual for candidate in names if candidate))


def wait_chat(br, item, name, limit=5):
    """Wait for identity, not just a changing count in the previous chat."""
    until = time.monotonic() + limit
    while time.monotonic() < until:
        try:
            pane = br.eval_json(JS_PANE)
            if pane_matches(item, name, pane) and pane.get('n', 1) > 0 and not pane.get('busy'):
                return True
        except Exception:
            pass  # A pane being replaced can be temporarily unreadable.
        time.sleep(0.25)
    return False


def read_chat(br, idx, name, d0, d1, today, fake=None, diag=None, deadline=None,
              max_scroll=MAX_SCROLL, context_chars=4000, on_page=None, conversation_id="", on_undated=None):
    """대화 하나 — 위로 되감으며 화면을 여러 번 읽어 합친다. → (rows, 화면항목수)

    기간보다 오래된 날짜, 스크롤 상한, 연속된 동일 화면, 전체 시간 예산에서 멈춘다.
    기간 밖 메시지도 탐색 진행으로 세고, 화면 상단에서는 지연 로딩을 기다린다."""
    rounds = (fake or {}).get(str(idx)) if fake else None
    rows, seen, observed, screen = {}, set(), set(), 0
    oldest = None
    stall = 0
    pane = ("", -1)
    reason = "scroll_limit"
    for r in range(max_scroll + 1):
        if deadline and time.monotonic() > deadline:
            reason = "time_budget"
            break
        before = len(observed)
        batch, pending = [], []
        if rounds is not None:
            if r >= len(rounds):
                reason = "history_end"
                break
            page = rounds[r]
        else:
            page = br.eval_json(JS_MSGS)
        if diag is not None and page.get("how"):
            diag["how_msg"] = page["how"]
        items = page.get("items") or []
        screen += int(page.get("n") or 0)
        chat = (page.get("chat") or "").strip() or name
        cur = None
        for it in items:
            if it.get("t") == "sep":
                # Reset at every separator. An unread/date divider with an
                # unknown year must not inherit a different known day's date.
                cur = screen_date(it.get("text"), today)
                continue
            # 탐색 진행에는 기간 밖 메시지도 센다. 과거 기간에 닿기 전에 최근 화면에서 멈추지 않는다.
            observed.add(json.dumps(it, ensure_ascii=False, sort_keys=True))
            texts = it.get("texts") or []
            # 머리 조각(화면이 '이 메시지의 시각' 이라 말하는 것)과 본문을 나눠 넘긴다 —
            # 본문에 적힌 날짜를 시각으로 삼으면 최근 메시지가 과거 달로 들어간다.
            head = [str(x) for x in ((it.get("iso") or []) + [it.get("ts") or ""]
                                     + list(it.get("titles") or []) + [it.get("label") or ""])]
            dt, how = stamp(head, [str(x) for x in texts[:3]], cur, d0, d1, today)
            au = author_of(it, texts)
            bd = body_of(it, texts, au, it.get("ts") or "")
            if not bd:
                if diag is not None:
                    diag["no_body"] += 1
                continue
            if dt and how in ('iso', 'full', 'date', 'rel'):
                cur = dt.date()  # Proven only in this rendered page, never carried across scrolls.
            sid = str(it.get("id") or "")
            row = {"time": dt.strftime("%Y-%m-%d %H:%M") if dt else '', "from": au, "chat": chat,
                   "summary": bd[:SUMMARY_MAX], "how": how, "context_excerpt": bd[:context_chars],
                   "context_truncated": str(len(bd) > context_chars or len(str(it.get('body') or '')) >= 20000).lower(),
                   "source_id": "teams-dom:" + conversation_id + "/" + sid if sid else "", "source_kind": "teams_web",
                   "source_url": str(it.get("url") or ""), "conversation_id": conversation_id,
                   "time_precision": "unknown" if not dt else "date" if how == "date" else "minute", "replied_time": ""}
            if not dt:
                if diag is not None:
                    diag["no_time"] += 1
                row.update(timestamp_text=' | '.join(head)[:1000], requested_from=str(d0), requested_to=str(d1))
                pending.append(row)
                continue
            oldest = dt.date() if oldest is None else min(oldest, dt.date())
            if not (d0 <= dt.date() <= d1):
                continue
            k = (conversation_id, sid) if sid else (au, dt.isoformat(), chat, hashlib.sha1(bd.encode("utf-8")).hexdigest())
            if k in seen:
                continue
            seen.add(k)
            rows[k] = row
            batch.append(row)
        if pending and on_undated:
            on_undated(pending)
        if diag is not None:
            diag['observed_messages'] = diag.get('observed_messages', 0) + len(observed) - before
            diag['dated_messages'] = diag.get('dated_messages', 0) + len(batch)
        if batch and on_page:
            on_page(batch)
        if oldest and oldest < d0:          # 기간보다 오래된 데까지 왔다 — 더 되감을 이유가 없다
            reason = "requested_start_reached"
            break
        if len(observed) > before:
            stall = 0
        else:
            stall += 1
            if stall >= 2:                  # 두 번 되감아도 새 것이 없다 — 이 대화는 여기까지다
                reason = "messages_stalled"
                break
        if rounds is None:
            movement = str(br.cdp.eval(JS_SCROLL_UP))
            if movement not in ("scrolled", "top"):
                reason = "history_end_or_unavailable"
                break
            # 지난 메시지가 실제로 붙을 때까지만 기다린다 — 예전에는 무조건 1.6초를 잤다.
            pane = wait_pane(br, pane, 1.8)
    if diag is not None:
        diag.setdefault("chat_reasons", []).append(reason)
    return list(rows.values()), screen


# ── 저장 ─────────────────────────────────────────────────────────────────────
def _sum40(s):
    return hashlib.sha1(re.sub(r"\s+", " ", str(s or "")).strip()[:120].encode("utf-8")).hexdigest()[:10]


def key_of(time_s, frm, chat, summary):
    """원본 ID가 없는 화면 관측을 위한 날짜 포함 비교 키."""
    return "|".join((_norm(frm), str(time_s or "")[:16], _norm(chat), _sum40(summary)))


def save(rows, force):
    """부분 화면 수집으로 지난 기록을 잃지 않는다. --force도 기존 기간을 지우지 않는다."""
    dst = os.path.join(OUT_DIR, "teams_web.csv")
    before = len(read_csv(dst))
    total = merge_csv(dst, rows, FIELDS, kind="teams")
    resolved = {record_key(row, 'teams') for row in rows if row.get('source_id') and row.get('time')}
    if resolved:
        pending_path = os.path.join(ROOT, 'data', 'collection_pending', 'teams_web_undated.csv')
        pending = read_csv(pending_path)
        remaining = [row for row in pending if record_key(row, 'teams') not in resolved]
        if len(remaining) != len(pending):
            write_csv(pending_path, remaining, FIELDS + ['timestamp_text', 'requested_from', 'requested_to'])
    return dst, max(0, total - before), 0, total


def save_undated(rows):
    """Quarantine observed originals without inventing a reporting date or MM."""
    path = os.path.join(ROOT, 'data', 'collection_pending', 'teams_web_undated.csv')
    known = {record_key(row, 'teams') for row in read_csv(os.path.join(OUT_DIR, 'teams_web.csv')) if row.get('source_id')}
    pending = [row for row in rows if not row.get('source_id') or record_key(row, 'teams') not in known]
    return merge_csv(path, pending, FIELDS + ['timestamp_text', 'requested_from', 'requested_to'], kind='teams')


def walk_chats(br, fake, max_chats, max_pages, deadline, visit, skip=()):
    """가상 목록을 페이지마다 다시 읽는다. DOM 인덱스는 다음 페이지로 가지고 가지 않는다."""
    seen, done, stall = set(), [], 0
    skip = set(skip)
    pages = ((fake or {}).get("chat_pages") or [(fake or {}).get("chats") or {}]) if fake is not None else None
    for p in range(max_pages):
        if time.monotonic() >= deadline:
            return done, p, "time_budget"
        if pages is not None and p >= len(pages):
            return done, p, "list_end"
        page = pages[p] if pages is not None else br.eval_json(JS_CHATS)
        fresh = 0
        for item in page.get("items") or []:
            key = str(item.get("key") or item.get("conversation_id") or chat_name(item) or item.get("idx"))
            if key in seen:
                continue
            seen.add(key)
            fresh += 1
            if key in skip:
                continue
            if len(done) >= max_chats:
                return done, p + 1, "chat_limit"
            if time.monotonic() >= deadline:
                return done, p + 1, "time_budget"
            visit(item, key)
            done.append(key)
        stall = 0 if fresh else stall + 1
        if stall >= 2:
            return done, p + 1, "list_stalled"
        if pages is None:
            if str(br.cdp.eval(JS_SCROLL_CHATS)) != "scrolled":
                return done, p + 1, "list_end_or_unavailable"
            time.sleep(0.8)
    return done, max_pages, "list_page_limit"


# Search is an additional, explicitly partial route. These UI selectors are
# capability probes, not a Microsoft API contract. Never substitute '*' when
# date-only Sent: search is unsupported, and never treat an unknown UI as empty.
JS_SEARCH_FOCUS = r"""
(() => {
  const e = document.querySelector('input[data-tid="search-box"],[data-tid="search-box"] input,'
      + 'input[data-tid="search-box-input"],input[data-tid="search-input"],input[role="searchbox"],'
      + 'input[aria-label*="Search"],input[aria-label*="검색"]');
  if (!e || !e.matches('input,textarea,[contenteditable="true"]')) return 'unsupported';
  e.focus(); if(e.select) e.select(); return 'focused';
})()
"""
JS_SEARCH_PAGE = r"""
(() => {
  const input = document.querySelector('input[data-tid="search-box"],[data-tid="search-box"] input,'
      + 'input[data-tid="search-box-input"],input[data-tid="search-input"],input[role="searchbox"],'
      + 'input[aria-label*="Search"],input[aria-label*="검색"]');
  const root = document.querySelector('[data-tid="search-results"],[data-tid="search-results-container"],'
      + '[data-tid="search-page"],[data-tid="search-results-page"]');
  if (!root) return JSON.stringify({query:input ? (input.value || input.textContent || '') : '', state:'unsupported',items:[]});
  const busy = !!root.querySelector('[aria-busy="true"],[role="progressbar"]');
  const tab = [...document.querySelectorAll('[role="tab"]')].find(e => /^(Messages|메시지)$/i.test((e.textContent || '').trim()));
  const selected = !!tab && tab.getAttribute('aria-selected') === 'true';
  const els = [...root.querySelectorAll('[data-tid="search-result-message"],[data-tid="message-search-result"],'
      + '[data-tid="search-result"][data-message-id],[data-message-id][data-chat-id]')];
  window.__lm_search_results = els;
  const items = els.map((e,idx) => {
    const link = [...e.querySelectorAll('a[href]')].find(a => /\/(?:l\/)?message\//.test(a.pathname));
    const title = e.querySelector('[data-tid="chat-title"],[data-tid="search-result-chat-name"],[data-tid="chat-name"]');
    return {idx, id:e.getAttribute('data-message-id') || '', conversation_id:e.getAttribute('data-chat-id') || '',
      name:title ? (title.textContent || '').trim() : '', url:link ? link.href : '',
      key:e.getAttribute('data-message-id') || (link ? link.href : '')};
  });
  const empty = [...root.querySelectorAll('[role="status"],[data-tid*="empty"],[data-tid*="no-result"]')]
      .some(e => /no (?:results|messages)|결과가 없|메시지가 없|결과 없음/i.test(e.textContent || ''));
  return JSON.stringify({query:input ? (input.value || input.textContent || '') : '',
    state:busy ? 'loading' : !selected ? 'wrong_tab' : items.length ? 'results' : empty ? 'empty' : 'unknown', items});
})()
"""
JS_SEARCH_MESSAGES = r"""
(() => { const e = [...document.querySelectorAll('[role="tab"]')].find(e => /^(Messages|메시지)$/i.test((e.textContent || '').trim()));
  if(!e) return 'unsupported'; if(e.getAttribute('aria-selected') !== 'true') e.click(); return 'ok'; })()
"""
JS_SEARCH_SCROLL = r"""
(() => {
  const root = document.querySelector('[data-tid="search-results"],[data-tid="search-results-container"],'
      + '[data-tid="search-page"],[data-tid="search-results-page"]');
  if(!root) return 'unsupported';
  const next = [...root.querySelectorAll('button')].find(e => !e.disabled && /^(Load more|Show more|Next|더 보기|더 로드|다음)$/i.test((e.textContent || e.getAttribute('aria-label') || '').trim()));
  if(next) { next.click(); return 'next'; }
  const el = [root,...root.querySelectorAll('*')].find(e => e.scrollHeight > e.clientHeight + 30 && /auto|scroll/.test(getComputedStyle(e).overflowY));
  if(!el) return 'end_or_unavailable';
  const before=el.scrollTop; el.scrollTop += Math.max(200,el.clientHeight-50); el.dispatchEvent(new Event('scroll',{bubbles:true}));
  return el.scrollTop>before ? 'scrolled' : 'end_or_unavailable';
})()
"""


def message_link(value):
    """Only a Teams message permalink can supply conversation/message identity."""
    try:
        parsed = urlparse(str(value or ''))
        if parsed.scheme != 'https' or parsed.hostname not in HOSTS:
            return '', ''
        match = re.search(r'/(?:l/)?message/([^/]+)/([^/?]+)', parsed.path)
        return (unquote(match[1]), unquote(match[2])) if match else ('', '')
    except ValueError:
        return '', ''


def search_identity(item):
    conv, mid = message_link(item.get('url'))
    if item.get('conversation_id') and conv and str(item['conversation_id']) != conv:
        return None
    if item.get('id') and mid and str(item['id']) != mid:
        return None
    conv, mid = str(item.get('conversation_id') or conv), str(item.get('id') or mid)
    if not conv or not mid:
        return None
    return dict(item, conversation_id=conv, id=mid)


def search_page(br, query, deadline):
    if str(br.cdp.eval(JS_SEARCH_FOCUS)) != 'focused':
        return {'state': 'unsupported', 'reason': 'search_input_unsupported'}
    br.cdp.call('Input.insertText', {'text': query})
    br.ca.press_enter(br.cdp)
    end = min(deadline, time.monotonic() + 12)
    last = {'state': 'unknown'}
    while time.monotonic() < end:
        time.sleep(0.4)
        br.cdp.eval(JS_SEARCH_MESSAGES)
        last = br.eval_json(JS_SEARCH_PAGE)
        if last.get('query', '').strip().lower() == query.lower() and last.get('state') in ('results', 'empty'):
            return last
    return dict(last, state='unsupported', reason='search_ui_or_query_unconfirmed')


def search_context(br, item, day, d0, d1, today, context_chars, fixture=None, deadline=None, on_undated=None):
    """Read nearby rendered originals only after verifying room AND anchor ID.

    A search preview is never saved as an original. A search date is never used
    to invent a timestamp. Context outside the requested interval is excluded.
    """
    item = search_identity(item)
    if not item:
        return [], 'search_identity_missing'
    if fixture is not None:
        pane, page = fixture.get('pane') or {}, fixture.get('page') or {}
    else:
        url = item.get('url') or ''
        if message_link(url) != (item['conversation_id'], item['id']):
            return [], 'search_permalink_missing'
        br.cdp.call('Page.navigate', {'url': url})
        end = min(deadline or time.monotonic() + 8, time.monotonic() + 8)
        pane, page = {}, {}
        while time.monotonic() < end:
            time.sleep(0.3)
            pane, page = br.eval_json(JS_PANE), br.eval_json(JS_MSGS)
            if pane_matches(item, item.get('name', ''), pane) and any(
                    str(m.get('id') or '') == item['id'] for m in page.get('items', [])):
                break
    if not pane_matches(item, item.get('name', ''), pane):
        return [], 'search_room_unconfirmed'
    items = page.get('items') or []
    anchor = next((i for i, entry in enumerate(items) if entry.get('t') == 'msg'
                   and str(entry.get('id') or '') == item['id']), None)
    if anchor is None:
        return [], 'search_anchor_unconfirmed'
    # Keep date dividers in document order while bounding the neighbor count.
    positions = [i for i, entry in enumerate(items) if entry.get('t') == 'msg']
    pos = positions.index(anchor)
    lo, hi = positions[max(0, pos-6)], positions[min(len(positions)-1, pos+6)]
    prior_sep = [entry for entry in items[:lo] if entry.get('t') == 'sep'][-1:]
    context = dict(page, items=prior_sep + items[lo:hi+1])
    rows, _ = read_chat(None, 0, item.get('name', ''), d0, d1, today,
                        fake={'0': [context]}, max_scroll=0, context_chars=context_chars,
                        conversation_id=item['conversation_id'], on_undated=on_undated)
    anchor_id = 'teams-dom:' + item['conversation_id'] + '/' + item['id']
    anchor_row = next((row for row in rows if row.get('source_id') == anchor_id), None)
    if not anchor_row:
        return [], 'search_anchor_date_or_body_missing'
    if anchor_row['time'][:10] != day.isoformat():
        return [], 'search_date_filter_unconfirmed'
    anchor_row['source_url'] = item.get('url') or anchor_row['source_url']
    return rows, ''


def search_checkpoint(root, payload):
    folder = os.path.join(root, 'data', 'collection_status')
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, 'teams_search_jobs.json')
    tmp = path + '.' + str(os.getpid()) + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
    for retry in range(5):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if retry == 4:
                raise
            time.sleep(0.05 * (retry + 1))


def collect_search(br, fake, root, d0, d1, today, deadline, context_chars, persist,
                   max_days=30, max_pages=40, on_progress=None, on_undated=None):
    """Date shards resume oldest-unattempted first; recent days refresh each run.

    completed_partial means the observed UI query ended, never server coverage.
    Checkpoints contain counters/IDs, not message bodies. No Graph or AI calls.
    """
    path = os.path.join(root, 'data', 'collection_status', 'teams_search_jobs.json')
    try:
        with open(path, encoding='utf-8-sig') as stream:
            prior = json.load(stream)
    except (OSError, ValueError):
        prior = {}
    if not isinstance(prior, dict):
        prior = {}
    jobs = prior.get('jobs', {}) if prior.get('requested_from') == str(d0) and prior.get('requested_to') == str(d1) else {}
    if not isinstance(jobs, dict):
        jobs = {}
    days = [d0 + timedelta(days=i) for i in range((d1-d0).days+1)]
    # Prior completed days are periodically retried; unknown/blocked days cannot
    # permanently monopolize a budget. Last-attempt scheduling also advances on
    # changed login profiles without trusting an earlier completion as coverage.
    queue = sorted(days, key=lambda day: float(jobs.get(str(day), {}).get('finished_at', 0)))
    latest = min(d1, today)
    if latest in queue:
        queue.remove(latest)
        queue.append(latest)  # process a fresh/old shard before reserving latest refresh
    selected = queue[:max(1, max_days-1)]
    if latest in days and latest not in selected and max_days > 1:
        selected.insert(1, latest)
    reasons, attempted, consecutive_empty = ['search_scope_unverified'], 0, 0

    def snapshot():
        counts = {state: sum(jobs.get(str(day), {}).get('state', 'pending') == state for day in days)
                  for state in ('attempted', 'completed_partial', 'blocked', 'pending')}
        payload = {'requested_from': str(d0), 'requested_to': str(d1), 'status': 'partial',
                   'scope': 'Observed Sent: date search results and verified nearby original messages; not exhaustive',
                   'reasons': list(dict.fromkeys(reasons)), 'jobs': jobs, 'counts': counts,
                   'attempted_this_run': attempted, 'total_days': len(days), 'finished_at': time.time()}
        search_checkpoint(root, payload)
        if on_progress:
            on_progress({key: value for key, value in payload.items() if key != 'jobs'})
        return payload

    snapshot()
    for day in selected:
        if time.monotonic() >= deadline:
            reasons.append('search_time_budget')
            break
        key, query = str(day), day.strftime('Sent:%m/%d/%Y')
        log(f'기간 검색 {key} - 날짜 검색 지원 여부와 원문을 확인합니다')
        attempted += 1
        job = {'query': query, 'state': 'attempted', 'pages': 0, 'results': 0, 'rows': 0,
               'reasons': [], 'finished_at': time.time()}
        jobs[key] = job
        snapshot()
        fixture = (fake or {}).get('search', {}).get(key) if fake is not None else None
        try:
            if fake is not None:
                pages = (fixture or {}).get('pages') or []
                page = pages[0] if pages else {'state': 'unsupported', 'reason': 'search_fixture_unavailable'}
            else:
                page = search_page(br, query, deadline)
            seen, saved, stalled, exhausted = set(), set(), 0, False
            for page_no in range(max_pages):
                if time.monotonic() >= deadline:
                    job['reasons'].append('search_time_budget')
                    break
                state = page.get('state')
                if state not in ('results', 'empty'):
                    job['state'] = 'blocked'
                    job['reasons'].append(page.get('reason') or 'search_ui_unsupported')
                    break
                job['pages'] += 1
                if state == 'empty':
                    exhausted = True
                    job['reasons'].append('search_ui_empty_scope_unverified')
                    break
                new = 0
                for raw in page.get('items') or []:
                    item = search_identity(raw)
                    ident = (item['conversation_id'], item['id']) if item else str(raw)
                    if ident in seen:
                        continue
                    seen.add(ident)
                    new += 1
                    job['results'] += 1
                    if time.monotonic() >= deadline:
                        job['reasons'].append('search_time_budget')
                        break
                    detail = ((fixture or {}).get('details') or {}).get(raw.get('key') or raw.get('id') or raw.get('url'), {}) if fake is not None else None
                    rows, reason = search_context(br, raw, day, d0, d1, today, context_chars, detail, deadline, on_undated)
                    if rows:
                        persist(rows)
                        saved.update(row.get('source_id') or key_of(row['time'], row['from'], row['chat'], row['summary']) for row in rows)
                        job['rows'] = len(saved)
                    if reason:
                        job['reasons'].append(reason)
                    snapshot()
                if 'search_time_budget' in job['reasons']:
                    break
                stalled = stalled + 1 if not new else 0
                if stalled >= 2:
                    job['reasons'].append('search_results_stalled')
                    break
                if fake is not None:
                    if page_no + 1 >= len(pages):
                        exhausted = True
                        break
                    page = pages[page_no+1]
                else:
                    # Opening the original changes the route. Return to the same
                    # query and replay result pages; never retain stale DOM nodes.
                    page = search_page(br, query, deadline)
                    if page.get('state') not in ('results', 'empty'):
                        job['state'] = 'blocked'
                        job['reasons'].append('search_return_unconfirmed')
                        break
                    for _ in range(page_no+1):
                        movement = str(br.cdp.eval(JS_SEARCH_SCROLL))
                        if movement not in ('scrolled', 'next'):
                            exhausted = True
                            break
                        time.sleep(0.7)
                        page = br.eval_json(JS_SEARCH_PAGE)
                    if exhausted:
                        break
            else:
                job['reasons'].append('search_page_limit')
            if exhausted and job['state'] != 'blocked':
                job['state'] = 'completed_partial'
            if job['state'] == 'attempted' and not job['reasons']:
                job['reasons'].append('search_incomplete')
        except Exception as error:
            job['state'] = 'blocked'
            job['reasons'].append('search_error:' + type(error).__name__)
        job['reasons'] = list(dict.fromkeys(job['reasons']))
        job['finished_at'] = time.time()
        snapshot()
        consecutive_empty = consecutive_empty + 1 if 'search_ui_empty_scope_unverified' in job['reasons'] else 0
        if consecutive_empty >= 2:
            reasons.append('search_empty_yield_to_chat_list')
            break  # Date-only search may be unsupported; the chat list is independent.
        # One unsupported global UI probe is enough; preserve budget for legacy.
        if 'search_ui_or_query_unconfirmed' in job['reasons'] or 'search_input_unsupported' in job['reasons']:
            reasons.append('search_unsupported')
            break
    return snapshot()


def main():
    d0s = arg("--from") or (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
    d1s = arg("--to") or datetime.now().strftime("%Y-%m-%d")
    d0, d1 = date.fromisoformat(d0s), date.fromisoformat(d1s)
    today = date.today()
    force = "--force" in sys.argv
    try:
        with open(os.path.join(ROOT, "config", "config.json"), encoding="utf-8-sig") as stream:
            cfg = json.load(stream)
    except (OSError, ValueError):
        cfg = {}
    try:
        max_chats = max(1, int(arg("--max-chats") or cfg.get("teamsWebMaxChats") or 200))
    except ValueError:
        max_chats = 200
    try:
        # Coordinator passes the route's remaining budget; standalone defaults to five minutes.
        budget = max(5.0, float(arg("--budget") or cfg.get("teamsWebBudgetSec") or 300))
    except ValueError:
        budget = 300.0
    deadline = time.monotonic() + budget  # Includes browser startup and login readiness.
    selfs = self_names(cfg)
    ccfg = cfg.get("collection") or {}
    context_chars = max(200, min(20000, int(ccfg.get("contextChars") or 4000)))
    max_scroll = max(1, min(2000, int(cfg.get("teamsWebMaxScrolls") or MAX_SCROLL)))
    max_pages = max(1, min(1000, int(cfg.get("teamsWebListPages") or 100)))
    reasons, processed = ["web_scope_not_exhaustive"], []
    search_summary = {}
    rows_seen = set()
    diag = {"no_time": 0, "no_body": 0, "how_msg": "", "observed_messages": 0, "dated_messages": 0}
    undated_rows = 0
    prior = {}
    try:
        with open(os.path.join(ROOT, "data", "collection_status", "teams_web.json"), encoding="utf-8-sig") as f:
            prior = json.load(f)
    except (OSError, ValueError):
        pass
    resume = (prior.get("processed_chat_keys") or []) if (
        prior.get("requested_from") == d0s and prior.get("requested_to") == d1s
        and set(prior.get("reasons") or []) & {"chat_limit", "time_budget", "list_page_limit", "interrupted"}) else []

    def status(state="partial", extra_reason="", **extra):
        return write_status(ROOT, "teams_web", d0s, d1s, status=state, rows=len(rows_seen), scope=SCOPE,
                            reasons=list(dict.fromkeys(reasons + ([extra_reason] if extra_reason else []))),
                            completed_units=len(processed), total_units=None,
                            processed_chat_keys=list(dict.fromkeys(resume + processed))[-2000:],
                            search=search_summary, undated_rows=undated_rows,
                            observed_messages=diag['observed_messages'], dated_messages=diag['dated_messages'], **extra)

    status(extra_reason="interrupted")  # 강제 종료되어도 완주로 남지 않는다.

    fake = None
    fk = os.environ.get("LM_TEAMSWEB_FAKE", "")
    if fk:
        try:
            with open(fk, encoding="utf-8-sig") as stream:
                fake = json.load(stream)
        except (OSError, ValueError):
            fake = {}
        if fake.get("login"):
            log("로그인 필요(시험용 가짜)")
            status("blocked", "login_required")
            return 2
    br = None
    log(f'웹 채팅 시작 - 요청 {d0s} ~ {d1s}, 전체 예산 {budget:g}초')
    if fake is None:
        if os.environ.get("LM_NO_BROWSER"):
            log("LM_NO_BROWSER 설정 — 브라우저를 띄우지 않습니다(시험용)")
            status("blocked", "browser_disabled")
            return 3
        try:
            br = Browser()
            br.deadline = deadline
            if hasattr(br, 'cfg'):
                br.cfg['_collection_deadline'] = deadline
            started = br.start()
        except Exception as e:              # 드라이버 부재·포트 충돌 — 사슬의 다음 경로(창 읽기)로 넘긴다
            log(f"드라이버를 쓸 수 없습니다({type(e).__name__}: {str(e)[:80]}) — 다음 대체 경로로")
            status("failed", "driver_error")
            return 3
        if not started:
            log("전용 Edge(디버그 포트)를 띄우지 못했습니다 — Edge 설치·config.copilotAuto.port 확인")
            reason = getattr(br, 'cfg', {}).get('_edge_reason', 'driver_unavailable')
            status("blocked", reason)
            return 3
        log('Teams 웹 로그인 및 실제 대화 목록 로딩을 확인합니다')
        try:
            st = br.goto(TEAMS_URL)
        except Exception:
            br.close()
            status('failed', 'page_load_error')
            return 1
        if st == "login":
            log("로그인 필요 — 지금 열린 전용 Edge 창의 팀즈 탭에서 회사 계정을 한 번 선택/로그인하세요 (Copilot 과 같은 창, 1회).")
            log("           로그인 뒤 [분석 실행]을 다시 누르면 이어서 읽습니다.")
            status("blocked", "login_required")
            br.close()
            return 2
        if st == "timeout":
            log("팀즈 웹 화면이 뜨지 않았습니다(네트워크·차단?) — 전용 Edge 창에서 teams.microsoft.com 이 열리는지 확인하세요.")
            status("failed", "page_timeout")
            br.close()
            return 1

    # Commit each visible page; interruption retains earlier pages and pending originals.
    def persist(batch):
        nonlocal undated_rows
        for row in batch:
            row["kind"] = "sent" if _norm(row["from"]) in selfs else "msg"
            rows_seen.add(row.get("source_id") or key_of(row["time"], row["from"], row["chat"], row["summary"]))
        save(batch, force)
        if undated_rows:
            undated_rows = len(read_csv(os.path.join(ROOT, 'data', 'collection_pending', 'teams_web_undated.csv')))
        status(extra_reason="interrupted")

    def preserve_undated(batch):
        nonlocal undated_rows
        for row in batch:
            row['kind'] = 'sent' if _norm(row['from']) in selfs else 'msg'
        undated_rows = save_undated(batch)
        if 'date_unknown_preserved_separately' not in reasons:
            reasons.append('date_unknown_preserved_separately')
        status(extra_reason='interrupted')

    def visit(it, key):
        idx = int(it.get("idx") or 0)
        name = chat_name(it)
        if br:
            br.eval_json(JS_CHATS)  # 가상 목록의 오래된 DOM 참조를 버린다.
            if str(br.cdp.eval(JS_OPEN % json.dumps(key))) != "ok":
                reasons.append("chat_open_failed")
                return
            if not wait_chat(br, it, name, limit=min(5, max(0, deadline-time.monotonic()))):
                reasons.append("chat_switch_unconfirmed")
                return
        fm = fake.get("msgs") if fake else None
        fake_idx = key if fm and key in fm else idx
        got, screen = read_chat(br, fake_idx, name, d0, d1, today, fm, diag, deadline,
                                max_scroll, context_chars, persist, str(it.get("conversation_id") or ""), preserve_undated)
        if (diag.get("chat_reasons") or [""])[-1] not in ("time_budget", "scroll_limit", "messages_stalled"):
            processed.append(key)
        status(extra_reason="interrupted")
        log(f"  · {name or '(이름 없음)'} — 화면 {screen}개 → {len(got)}건")
    try:
        if fake is None or 'search' in fake:
            def search_progress(summary):
                nonlocal search_summary
                search_summary = summary
                status(extra_reason='interrupted')
            try:
                collect_search(br, fake, ROOT, d0, d1, today,
                               min(deadline, time.monotonic() + min(60, budget * 0.25)),
                               context_chars, persist, on_progress=search_progress, on_undated=preserve_undated)
                reasons += search_summary.get('reasons', [])
            except Exception as error:
                reasons.append('search_failed:' + type(error).__name__)
            # Search failure must not disable the established chat-list route.
            if br:
                try:
                    if br.goto(TEAMS_URL, wait=1) != 'ok':
                        reasons.append('search_chat_list_restore_unconfirmed')
                except Exception:
                    reasons.append('search_chat_list_restore_failed')
        log('채팅 목록을 순회하며 페이지마다 저장합니다')
        _done, pages, stop = walk_chats(br, fake, max_chats, max_pages, deadline, visit, resume)
        reasons += [stop] + (diag.get("chat_reasons") or [])
        status(list_pages=pages, no_time=diag["no_time"], no_body=diag["no_body"])
    except Exception as e:
        status("partial" if rows_seen else "failed", "collection_error:" + type(e).__name__)
        log("탐색 중단 — 저장된 페이지는 보존됩니다")
        return 1
    finally:
        if br:
            br.close()
    log(f"진단: 화면 해석 선택자 {diag['how_msg'] or '못 찾음'} · 시각 못 짚음 {diag['no_time']} · 본문 없음 {diag['no_body']}")
    if not rows_seen:
        log("읽은 것이 없습니다 — 화면 항목은 보이는데 0건이면 표기 형식 문제입니다(위 진단 숫자 참고).")
        return 1
    dst, added, dup, total = save([], force)
    try:
        shown = os.path.relpath(dst, ROOT)
    except ValueError:              # 다른 드라이브(시험용으로 출력을 돌린 경우) - 표시일 뿐이니 죽지 않는다
        shown = dst
    log(f"{shown} — 이번 실행 관측 {len(rows_seen)}건 / 누적 {total}건")
    return 0 if (added or total) else 1


if __name__ == "__main__":
    sys.exit(main())
