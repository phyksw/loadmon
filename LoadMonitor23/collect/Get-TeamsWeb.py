# -*- coding: utf-8 -*-
"""
Get-TeamsWeb.py — 팀즈 웹(teams.microsoft.com)을 전용 Edge 프로필로 열어 채팅을 읽는다 (폴백).

Get-OutlookWeb.py 와 같은 방식이다: Copilot 에 쓰는 전용 Edge 프로필(data\\copilot_profile)에 회사 계정으로
한 번 로그인해 두면, **팀즈 앱이 꺼져 있어도** 동작한다. 앱 창 읽기(Get-TeamsWindow.ps1)는 화면에 그려진
부분만 UI 자동화로 긁으므로 창 크기·테마·팀즈 버전에 따라 PC 마다 0건이 되곤 했다(실측 제보). 웹 경로는
화면 렌더가 아니라 문서 구조(role·data-tid·aria-label)를 읽으므로 그 편차가 없고, 스크롤로 지난 날짜까지
거슬러 올라간다.

  python collect\\Get-TeamsWeb.py --from 2026-06-01 --to 2026-06-30 [--max-chats 40] [--force]

출력: data\\m365\\teams_web.csv   (time,from,chat,kind,replied_time,summary)
      — Graph·창 읽기 경로와 같은 스키마라 분석기(core\\extract.py 의 teams_*.csv)가 그대로 인제스트한다.
      이미 있는 teams_*.csv 전부와 대조해 같은 메시지는 다시 적지 않는다(경로가 겹쳐도 중복 계상 없음).
종료 코드: 0 저장 / 1 아무것도 못 읽음 / 2 로그인 필요(전용 Edge 창에서 1회) / 3 드라이버 불가

Copilot 과 달리 LLM 을 거치지 않으므로 지어낸 행이 없고, 데이터는 PC 밖으로 나가지 않는다(브라우저가 내
채팅을 보여주는 것을 읽을 뿐이다). replied_time 은 웹에서도 측정할 수 없어 빈 값(미측정)으로 둔다.

화면 구조는 Microsoft 가 바꿀 수 있어 선택자를 여러 벌 두고 '무엇으로 몇 개를 잡았는지' 를 로그에 남긴다
(회사 PC 의 원문을 밖으로 보낼 수 없으므로 진단은 로그의 숫자로 한다).
시험용: LM_TEAMSWEB_FAKE=<json> 이면 브라우저 없이 그 파일의 화면 응답을 쓴다
        {"chats": <JS_CHATS 응답>, "msgs": {"<대화번호>": [<JS_MSGS 응답>, …(스크롤 회차)]}}
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
OUT_DIR = os.path.join(ROOT, "data", "m365")
HDR = "time,from,chat,kind,replied_time,summary"
TEAMS_URL = "https://teams.microsoft.com/v2/"
HOSTS = ("teams.microsoft.com", "teams.cloud.microsoft", "teams.office.com", "teams.live.com")
MAX_SCROLL = 12                 # 대화 하나당 위로 되감는 횟수 상한 — 오래된 대화도 몇 달은 덮는다
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

RE_ISO = re.compile(r"(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})")
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
        v = datetime.fromisoformat(s.replace("Z", "+00:00").replace("z", "+00:00"))
    except ValueError:
        try:
            y, mo, dd, hh, mi = (int(x) for x in m.groups())
            return datetime(y, mo, dd, hh, mi)
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
    for s in head:
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
    if len(b) >= 3:
        return b
    drop = {_norm(author), _norm(ts)}
    out = [s for s in texts if _norm(s) not in drop and len(s.strip()) >= 2]
    return re.sub(r"\s{2,}", " ", " ".join(out)).strip()


# ── 화면 읽기 스크립트 ───────────────────────────────────────────────────────
JS_CHATS = r"""
(() => {
  const out = {href: location.href, how: "", n: 0, items: []};
  const SELS = ['[data-tid="chat-list"] [data-tid="chat-list-item"]',
                '[data-tid="chat-list-item"]',
                '[data-tid="chat-list"] [role="treeitem"]',
                '[role="tree"] [role="treeitem"]',
                '[role="list"] [role="listitem"][data-tid]',
                '[role="listbox"] [role="option"]'];
  let els = [];
  for (const s of SELS) { els = [...document.querySelectorAll(s)]; if (els.length) { out.how = s; break; } }
  window.__lm_chats = els;
  out.n = els.length;
  out.items = els.slice(0, 300).map((e, i) => ({
    idx: i,
    label: (e.getAttribute("aria-label") || e.getAttribute("title") || "").slice(0, 300),
    texts: [...e.querySelectorAll("span,div,a")].filter(x => x.childElementCount === 0)
             .map(x => (x.textContent || "").trim()).filter(Boolean).slice(0, 8)
  }));
  return JSON.stringify(out);
})()
"""
# 팀즈 목록은 pointerdown 으로 라우팅하는 스킨이 있어 click() 만으로는 열리지 않는다 — 전체 순서를 보낸다.
JS_OPEN = r"""
(() => {
  const e = (window.__lm_chats || [])[%d];
  if (!e) return "gone";
  try { e.scrollIntoView({block: "center"}); } catch (x) {}
  const t = e.querySelector('[role="button"],a,button') || e;
  for (const ev of ["pointerdown", "mousedown", "pointerup", "mouseup", "click"]) {
    t.dispatchEvent(new MouseEvent(ev, {bubbles: true, cancelable: true, view: window}));
  }
  return "ok";
})()
"""
JS_MSGS = r"""
(() => {
  const out = {href: location.href, how: "", chat: "", n: 0, items: []};
  const MSG = ['[data-tid="chat-pane-item"]', '[data-tid="chat-pane-message"]',
               '[data-tid="message-pane"] [role="listitem"]', '[role="log"] [role="listitem"]',
               '[role="main"] [role="listitem"]'];
  const SEP = '[role="separator"],[data-tid*="divider"]';
  let msel = "";
  for (const s of MSG) { if (document.querySelector(s)) { msel = s; break; } }
  if (!msel) return JSON.stringify(out);
  out.how = msel;
  const head = document.querySelector('[data-tid="chat-header-title"],[data-tid="chatTitle"],'
             + '[data-tid="chat-header"] [role="heading"],[role="main"] h1');
  out.chat = head ? ((head.getAttribute("title") || head.textContent || "").trim()).slice(0, 120) : "";
  const leafs = e => [...e.querySelectorAll("span,div,p,a")].filter(x => x.childElementCount === 0)
      .map(x => (x.textContent || "").trim()).filter(Boolean);
  for (const e of document.querySelectorAll(msel + "," + SEP)) {   // querySelectorAll 은 문서 순서 — 구분선이 제자리에 온다
    if (!e.matches(msel)) {
      const s = (e.textContent || "").trim();
      if (s && s.length <= 60) out.items.push({t: "sep", text: s});
      continue;
    }
    const au = e.querySelector('[data-tid="message-author-name"],[data-tid="messageAuthorName"]');
    const ts = e.querySelector('[data-tid="message-timestamp"],time');
    const bd = e.querySelector('[data-tid="messageBodyContent"],[id^="content-"]');
    out.items.push({t: "msg",
      label: (e.getAttribute("aria-label") || "").slice(0, 400),
      author: au ? (au.textContent || "").trim() : "",
      ts: ts ? ((ts.getAttribute("title") || ts.getAttribute("datetime") || ts.textContent || "").trim()) : "",
      iso: [...e.querySelectorAll("time[datetime]")].map(x => x.getAttribute("datetime")).filter(Boolean).slice(0, 3),
      titles: [...e.querySelectorAll("[title]")].map(x => (x.getAttribute("title") || "").trim()).filter(Boolean).slice(0, 6),
      body: bd ? (bd.textContent || "").trim().slice(0, 600) : "",
      texts: leafs(e).slice(0, 20)});
  }
  out.n = out.items.filter(x => x.t === "msg").length;
  return JSON.stringify(out);
})()
"""
JS_SCROLL_UP = r"""
(() => {
  const CAND = ['[data-tid="message-pane-list-viewport"]', '[data-tid="message-pane"]', '[role="log"]'];
  let el = null;
  for (const s of CAND) { const e = document.querySelector(s); if (e && e.scrollHeight > e.clientHeight + 20) { el = e; break; } }
  if (!el) {
    let m = document.querySelector('[data-tid="chat-pane-item"],[role="log"] [role="listitem"],[role="main"] [role="listitem"]');
    while (m && m !== document.body) {
      if (m.scrollHeight > m.clientHeight + 20 && getComputedStyle(m).overflowY !== "visible") { el = m; break; }
      m = m.parentElement;
    }
  }
  if (!el) return "no-scroller";
  const before = el.scrollTop;
  el.scrollTop = Math.max(0, el.scrollTop - Math.max(400, el.clientHeight - 60));
  el.dispatchEvent(new Event("scroll", {bubbles: true}));
  return el.scrollTop < before ? "scrolled" : "top";
})()
"""


JS_PANE = r"""
(() => {
  const MSG = ['[data-tid="chat-pane-item"]', '[data-tid="chat-pane-message"]',
               '[data-tid="message-pane"] [role="listitem"]', '[role="log"] [role="listitem"]',
               '[role="main"] [role="listitem"]'];
  let n = 0;
  for (const s of MSG) { const k = document.querySelectorAll(s).length; if (k) { n = k; break; } }
  const head = document.querySelector('[data-tid="chat-header-title"],[data-tid="chatTitle"],'
             + '[data-tid="chat-header"] [role="heading"],[role="main"] h1');
  return JSON.stringify({n: n, chat: head ? ((head.getAttribute("title") || head.textContent || "").trim()).slice(0, 120) : ""});
})()
"""


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
        got = (str(st.get("chat") or ""), int(st.get("n") or 0))
        if got[1] > 0 and (got[0] != last[0] or got[1] != last[1]):
            return got
    return got


class Browser:
    def __init__(self):
        spec = importlib.util.spec_from_file_location("_ca", os.path.join(ROOT, "tools", "copilot_auto.py"))
        self.ca = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.ca)
        self.cfg = self.ca.load_cfg()
        self.port = self.cfg["port"]
        self.cdp = None

    def start(self):
        if not self.ca.ensure_edge(self.cfg):
            return False
        ws = None
        for t in [t for t in self.ca.http_json(self.port, "/json") if t.get("type") == "page"]:
            if any(h in (t.get("url") or "") for h in HOSTS):
                ws = t["webSocketDebuggerUrl"]
                break
        if not ws:
            # 새 탭에서 연다 — Copilot 탭(판정에 쓰는 대화 맥락)을 건드리지 않기 위해서다
            for method in ("PUT", "GET"):
                try:
                    ws = self.ca.http_json(self.port, "/json/new?" + quote(TEAMS_URL, safe=""),
                                           method=method)["webSocketDebuggerUrl"]
                    break
                except Exception:
                    continue
        if not ws:
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

    def wait_ready(self, settle=6.0, limit=90):
        """팀즈 웹은 첫 로드가 느리다(워크로드 셸 → 채팅). → 'login' | 'ok' | 'timeout'"""
        t0 = time.time()
        while time.time() - t0 < limit:
            time.sleep(1.0)
            h = self.href()
            if "login.microsoftonline" in h or "login.live.com" in h or "login.microsoft" in h:
                return "login"
            try:
                rs = self.cdp.eval("document.readyState")
                n = int(self.cdp.eval('document.querySelectorAll(\'[data-tid="chat-list-item"],'
                                      '[role="treeitem"],[role="main"]\').length') or 0)
            except Exception:
                rs, n = "", 0
            if rs == "complete" and n > 0:
                time.sleep(settle)
                if "login.microsoftonline" in self.href():
                    return "login"
                return "ok"
        return "timeout"

    def eval_json(self, js, timeout=40):
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


def read_chat(br, idx, name, d0, d1, today, fake=None, diag=None, deadline=None):
    """대화 하나 — 위로 되감으며 화면을 여러 번 읽어 합친다. → (rows, 화면항목수)

    되감기를 멈추는 조건은 넷이다: 기간보다 오래된 날짜에 닿음 · 더 스크롤되지 않음 ·
    두 번 연속 새 메시지가 안 나옴(정지) · 전체 시간 예산 소진. 정지 판정이 없으면 해석이
    전부 실패하는 대화방에서 13회를 끝까지 돌아 시간만 태운다(감사 지적)."""
    rounds = (fake or {}).get(str(idx)) if fake else None
    rows, seen, screen = {}, set(), 0
    oldest = None
    stall = 0
    pane = ("", -1)
    for r in range(MAX_SCROLL + 1):
        if deadline and time.monotonic() > deadline:
            break
        before = len(rows)
        if rounds is not None:
            if r >= len(rounds):
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
                d = find_date(it.get("text"), d0, d1) or rel_date(it.get("text"), today)
                if d:
                    cur = d
                continue
            texts = it.get("texts") or []
            # 머리 조각(화면이 '이 메시지의 시각' 이라 말하는 것)과 본문을 나눠 넘긴다 —
            # 본문에 적힌 날짜를 시각으로 삼으면 최근 메시지가 과거 달로 들어간다.
            head = [str(x) for x in ((it.get("iso") or []) + [it.get("ts") or ""]
                                     + list(it.get("titles") or []) + [it.get("label") or ""])]
            dt, how = stamp(head, [str(x) for x in texts[:3]], cur, d0, d1, today)
            if not dt:
                if diag is not None:
                    diag["no_time"] += 1
                continue
            au = author_of(it, texts)
            bd = body_of(it, texts, au, it.get("ts") or "")
            if len(bd) < 3:
                if diag is not None:
                    diag["no_body"] += 1
                continue
            oldest = dt.date() if oldest is None else min(oldest, dt.date())
            if not (d0 <= dt.date() <= d1):
                continue
            k = (au, dt.strftime("%H:%M"), chat, hashlib.sha1(bd[:120].encode("utf-8")).hexdigest()[:10])
            if k in seen:
                continue
            seen.add(k)
            rows[k] = {"time": dt.strftime("%Y-%m-%d %H:%M"), "from": au, "chat": chat,
                       "summary": bd[:SUMMARY_MAX], "how": how}
        if oldest and oldest < d0:          # 기간보다 오래된 데까지 왔다 — 더 되감을 이유가 없다
            break
        if len(rows) > before:
            stall = 0
        else:
            stall += 1
            if stall >= 2:                  # 두 번 되감아도 새 것이 없다 — 이 대화는 여기까지다
                break
        if rounds is None:
            if str(br.cdp.eval(JS_SCROLL_UP)) != "scrolled":
                break
            # 지난 메시지가 실제로 붙을 때까지만 기다린다 — 예전에는 무조건 1.6초를 잤다.
            pane = wait_pane(br, pane, 1.8)
    return list(rows.values()), screen


# ── 저장 ─────────────────────────────────────────────────────────────────────
def _sum40(s):
    return hashlib.sha1(re.sub(r"\s+", " ", str(s or "")).strip()[:120].encode("utf-8")).hexdigest()[:10]


def key_of(time_s, frm, chat, summary):
    """창 읽기 경로와 같은 모양의 열쇠 — 같은 메시지를 두 경로가 잡아도 한 번만 센다."""
    return "|".join((_norm(frm), str(time_s or "")[11:16], _norm(chat), _sum40(summary)))


def existing_keys(skip):
    """이미 모아 둔 teams_*.csv 전부의 열쇠 — Graph·창 읽기와 겹치는 메시지를 다시 적지 않는다."""
    keys = set()
    for p in glob.glob(os.path.join(OUT_DIR, "teams_*.csv")):
        if os.path.abspath(p) == os.path.abspath(skip):
            continue
        try:
            with open(p, encoding="utf-8-sig", errors="replace") as f:
                for r in csv.DictReader(f):
                    if r.get("time"):
                        keys.add(key_of(r.get("time"), r.get("from"), r.get("chat"), r.get("summary")))
        except OSError:
            continue
    return keys


def _esc(s):
    s = re.sub(r"[\r\n]+", " ", str(s or ""))
    return '"' + s.replace('"', '""') + '"' if ("," in s or '"' in s) else s


def save(rows, force):
    """덮어쓰지 않고 누적한다 — 이 파일은 실행할 때마다 그 시점에 보이는 대화만 담기 때문이다."""
    os.makedirs(OUT_DIR, exist_ok=True)
    dst = os.path.join(OUT_DIR, "teams_web.csv")
    out, keys = [], set()
    if os.path.exists(dst) and not force:
        try:
            with open(dst, encoding="utf-8-sig", errors="replace") as f:
                for r in csv.DictReader(f):
                    if not r.get("time") or None in r.values():
                        continue
                    k = key_of(r.get("time"), r.get("from"), r.get("chat"), r.get("summary"))
                    if k in keys:
                        continue
                    keys.add(k)
                    out.append([r.get("time") or "", r.get("from") or "", r.get("chat") or "",
                                r.get("kind") or "", r.get("replied_time") or "", r.get("summary") or ""])
        except OSError:
            pass
    other = existing_keys(dst)
    added = dup = 0
    for r in rows:
        k = key_of(r["time"], r["from"], r["chat"], r["summary"])
        if k in keys:
            continue
        if k in other:                      # Graph·창 읽기가 이미 잡은 메시지
            dup += 1
            keys.add(k)
            continue
        keys.add(k)
        out.append([r["time"], r["from"], r["chat"], r["kind"], "", r["summary"]])
        added += 1
    out.sort(key=lambda x: x[0])
    with open(dst, "w", encoding="utf-8-sig", newline="") as f:
        f.write(HDR + "\n")
        for r in out:
            f.write(",".join(_esc(c) for c in r) + "\n")
    return dst, added, dup, len(out)


def main():
    d0s = arg("--from") or (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
    d1s = arg("--to") or datetime.now().strftime("%Y-%m-%d")
    d0, d1 = date.fromisoformat(d0s), date.fromisoformat(d1s)
    today = date.today()
    force = "--force" in sys.argv
    try:
        cfg = json.load(open(os.path.join(ROOT, "config", "config.json"), encoding="utf-8-sig"))
    except (OSError, ValueError):
        cfg = {}
    try:
        max_chats = int(arg("--max-chats") or cfg.get("teamsWebMaxChats") or 40)
    except ValueError:
        max_chats = 40
    try:
        # run.py 가 준 상한(1200초)보다 넉넉히 짧게 — 저장·정리 시간을 남긴다
        budget = float(arg("--budget") or cfg.get("teamsWebBudgetSec") or 900)
    except ValueError:
        budget = 900.0
    selfs = self_names(cfg)

    fake = None
    fk = os.environ.get("LM_TEAMSWEB_FAKE", "")
    if fk:
        try:
            fake = json.load(open(fk, encoding="utf-8-sig"))
        except (OSError, ValueError):
            fake = {}
        if fake.get("login"):
            log("로그인 필요(시험용 가짜)")
            return 2
    br = None
    if fake is None:
        if os.environ.get("LM_NO_BROWSER"):
            log("LM_NO_BROWSER 설정 — 브라우저를 띄우지 않습니다(시험용)")
            return 3
        try:
            br = Browser()
            started = br.start()
        except Exception as e:              # 드라이버 부재·포트 충돌 — 사슬의 다음 경로(창 읽기)로 넘긴다
            log(f"드라이버를 쓸 수 없습니다({type(e).__name__}: {str(e)[:80]}) — 다음 대체 경로로")
            return 3
        if not started:
            log("전용 Edge(디버그 포트)를 띄우지 못했습니다 — Edge 설치·config.copilotAuto.port 확인")
            return 3
        st = br.goto(TEAMS_URL)
        if st == "login":
            log("로그인 필요 — 지금 열린 전용 Edge 창의 팀즈 탭에서 회사 계정을 한 번 선택/로그인하세요 (Copilot 과 같은 창, 1회).")
            log("           로그인 뒤 [분석 실행]을 다시 누르면 이어서 읽습니다.")
            return 2
        if st == "timeout":
            log("팀즈 웹 화면이 뜨지 않았습니다(네트워크·차단?) — 전용 Edge 창에서 teams.microsoft.com 이 열리는지 확인하세요.")
            return 1

    page = json.loads(json.dumps(fake.get("chats") or {})) if fake is not None else br.eval_json(JS_CHATS)
    chats = page.get("items") or []
    log(f"대화 목록 {page.get('n') or 0}개 (선택자 {page.get('how') or '못 찾음'})")
    if not chats:
        log("채팅 목록을 찾지 못했습니다 — 전용 Edge 창의 팀즈에서 [채팅] 탭이 열려 있는지 확인하세요.")
        if br:
            br.close()
        return 1

    rows = []
    diag = {"no_time": 0, "no_body": 0, "how_msg": ""}
    # 전체 시간 예산 — 이 안에 반드시 저장까지 끝낸다. run.py 가 준 상한에 걸려 강제 종료되면
    # 그때까지 읽은 것이 통째로 사라진다(감사 실측: 최악 920초 > 상한 900초 → 15분 쓰고 0건).
    # 예산이 다 되면 남은 대화방을 포기하고 지금까지 읽은 것을 저장한다 — 다음 실행이 이어서 채운다.
    deadline = time.monotonic() + budget
    pane = ("", -1)
    done = cut = 0
    for it in chats[:max_chats]:
        if time.monotonic() > deadline:
            cut = max_chats - done
            break
        idx = int(it.get("idx") or 0)
        name = chat_name(it)
        if br:
            if str(br.cdp.eval(JS_OPEN % idx)) != "ok":
                continue
            # 대화가 실제로 바뀔 때까지만 기다린다 — 예전에는 무조건 2.2초를 잤다.
            pane = wait_pane(br, pane, 2.5)
        got, screen = read_chat(br, idx, name, d0, d1, today,
                                fake.get("msgs") if fake else None, diag, deadline)
        for g in got:
            g["kind"] = "sent" if _norm(g["from"]) in selfs else "msg"
        rows += got
        done += 1
        log(f"  · {name or '(이름 없음)'} — 화면 {screen}개 → {len(got)}건")
    if br:
        br.close()
    if cut > 0:
        log(f"시간 예산({budget:.0f}초)에 닿아 남은 대화방 {cut}개는 다음 실행으로 미룹니다 — 지금까지 읽은 것은 저장합니다.")

    log(f"진단: 화면 해석 선택자 {diag['how_msg'] or '못 찾음'} · 시각 못 짚음 {diag['no_time']} · 본문 없음 {diag['no_body']}")
    if not rows:
        log("읽은 것이 없습니다 — 화면 항목은 보이는데 0건이면 표기 형식 문제입니다(위 진단 숫자 참고).")
        return 1
    dst, added, dup, total = save(rows, force)
    try:
        shown = os.path.relpath(dst, ROOT)
    except ValueError:              # 다른 드라이브(시험용으로 출력을 돌린 경우) - 표시일 뿐이니 죽지 않는다
        shown = dst
    log(f"{shown} — 신규 {added}건 (다른 경로와 겹쳐 제외 {dup}건) / 누적 {total}건")
    return 0 if (added or total) else 1


if __name__ == "__main__":
    sys.exit(main())
