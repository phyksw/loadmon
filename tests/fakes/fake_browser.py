# -*- coding: utf-8 -*-
r"""tests\fakes\fake_browser.py — Outlook 웹 화면 흉내(LM28 WP2 · WP3 이 이어 쓴다). 실제 Edge·네트워크를 쓰지 않는다.

Get-OutlookWeb 의 수집 루프(collect_mail·collect_cal)가 부르는 것만 흉내 낸다:
  br.goto(url) · br.search(query) · br.eval_json(JS) · br.cdp.eval(JS) · br.href() · br.start() · br.close(keep_tab)
JS 는 머리 표식(/*LM28:이름*/ — owa_list·owa_scroll·owa_cal·owa_cal_prev·owa_open·owa_head)으로 알아보고 각본 응답을
돌려준다. 운영 JS 를 바꿔도 표식이 같으면 시험이 따라온다. 기존 LM_OWA_FAKE(달별 항목 주입)는 회귀용으로 따로 남아 있다.

각본(flags):
  ignore_search  — 검색을 무시한다(F-03: 검색 뒤에도 폴더 목록이 최신부터 그대로)
  ignore_url     — 일정 주 주소를 무시하고 늘 오늘이 든 주를 보인다(F-05)
  date_style     — 목록 날짜 표기 'owa'(오늘=시각만 · 6일 안=요일+시각 · 그 밖=연-월-일, 기본) · 'full'(늘 연-월-일 시각)
  empty_marker   — 목록이 비면 '결과 없음/비어 있음' 표식(기본 True)
  page · step    — 한 화면에 그려지는 항목 수(기본 20) · 한 번 스크롤에 내려가는 수(기본 10)
  reach          — 검색하지 않은 폴더 목록은 이 개수까지만 불러온다(끝까지 못 내리는 화면 — '1월까지 못 감')
  no_scroller    — 스크롤 영역을 못 찾는다 · no_search_box — 검색창이 없다
  stuck_clicks   — '이전 주' n번째 클릭(1부터)은 먹지 않는다(머리 그대로)
  bad_header     — 이 주(시작 date)들은 머리 글이 2주 뒤 주를 말한다(머리·바탕 불일치)
  week_start     — 주 보기 첫 요일(0=월 기본 · 6=일)
  pivot          — 받은 편지함에 '중요' 탭이 선택돼 있다 · login — 어느 주소든 로그인 화면
"""
import re
from collections import Counter
from datetime import date, datetime, timedelta
from urllib.parse import urlparse

KWD = "월화수목금토일"
FOLDER_NAME = {"inbox": "받은 편지함", "sent": "보낸 편지함"}


def ampm(dt):
    """'오후 3:12' 꼴(한국어 OWA 목록 표기)."""
    h = dt.hour % 12 or 12
    return f"{'오전' if dt.hour < 12 else '오후'} {h}:{dt.minute:02d}"


def msg(mid, when, sender="보낸이", subject="업무 협의", **kw):
    """메일 각본 한 건 — kw: dts(시각이 든 다른 속성 글) · open(읽기 창 머리 글 목록) · titles."""
    return {"id": str(mid), "when": when, "sender": sender, "subject": subject, **kw}


def make_mailbox(d_from, d_to, per_day=1, hour_in=9, hour_out=14):
    """d_from~d_to 의 날마다 받은 메일·보낸 메일 per_day 건씩(최신부터) → {'inbox': [...], 'sent': [...]}."""
    box = {"inbox": [], "sent": []}
    d, i = d_to, 0
    while d >= d_from:
        for k in range(per_day):
            i += 1
            box["inbox"].append(msg(f"i{i}", datetime(d.year, d.month, d.day, hour_in, 5 + k), f"동료{i % 7}", "주간 보고"))
            box["sent"].append(msg(f"s{i}", datetime(d.year, d.month, d.day, hour_out, 10 + k), "나", "회신 드립니다"))
        d -= timedelta(days=1)
    return box


def make_events(d_from, d_to, hour=14):
    """평일마다 한 시간짜리 회의 하나 → [ev]."""
    out, d = [], d_from
    while d <= d_to:
        if d.weekday() < 5:
            st = datetime(d.year, d.month, d.day, hour, 0)
            out.append({"start": st, "end": st + timedelta(hours=1), "subject": f"정기 회의 {d.month}{d.day:02d}"})
        d += timedelta(days=1)
    return out


class _Cdp:
    def __init__(self, br):
        self.br = br

    def eval(self, js, timeout=25):
        return self.br._eval(js)

    def call(self, method, params=None, timeout=25):
        self.br.calls["cdp:" + method] += 1
        return {}

    def reconnect(self):
        pass

    def close(self):
        pass


class FakeBrowser:
    def __init__(self, today, mail=None, events=None, **flags):
        self.today = today
        self.mail = {k: sorted(v, key=lambda m: m["when"], reverse=True) for k, v in (mail or {}).items()}
        self.events = list(events or [])
        self.f = dict({"date_style": "owa", "empty_marker": True, "page": 20, "step": 10, "week_start": 0}, **flags)
        self.cdp = _Cdp(self)
        self.calls = Counter()
        self.url = "about:blank"
        self.view, self.folder, self.lst, self.pos, self.searched = "", "inbox", [], 0, False
        self.window, self.pane, self.week, self.clicks = [], None, None, 0
        self.reason, self.closed = "", None

    # ── Browser 흉내 ──
    def start(self):
        self.calls["start"] += 1
        return not self.f.get("start_fail")

    def href(self):
        return self.url

    def close(self, keep_tab=False):
        self.closed = "kept" if keep_tab else "closed"

    def goto(self, url, wait=6.0):
        self.calls["goto"] += 1
        self.url = url
        if self.f.get("login"):
            self.reason = "R-LOGIN"
            return "login"
        p = urlparse(url).path
        if "/calendar/" in p:
            self.view = "cal"
            m = re.search(r"/week/(\d+)/(\d+)/(\d+)", p)
            d = date(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m and not self.f.get("ignore_url") else self.today
            self.week = self._wstart(d)
            return "ok"
        self.view = "mail"
        self.folder = "sent" if "sentitems" in p else "inbox"
        self.lst, self.pos, self.searched = list(self.mail.get(self.folder, [])), 0, False
        return "ok"

    def search(self, query):
        self.calls["search"] += 1
        if self.f.get("no_search_box"):
            return False
        self.pos = 0
        if self.f.get("ignore_search"):
            return True                       # 입력은 됐지만 화면은 폴더 목록 그대로(F-03)
        ds = [date.fromisoformat(x) for x in re.findall(r"\d{4}-\d{2}-\d{2}", query)]
        if len(ds) == 2:
            self.lst = [m for m in self.mail.get(self.folder, []) if ds[0] <= m["when"].date() <= ds[1]]
            self.searched = True
        return True

    def eval_json(self, js, timeout=40):
        r = self._eval(js)
        return r if isinstance(r, dict) else {}

    # ── 화면 ──
    def _wstart(self, d):
        return d - timedelta(days=(d.weekday() - self.f["week_start"]) % 7)

    def _visible(self):
        if self.searched or not self.f.get("reach"):
            return self.lst
        return self.lst[:int(self.f["reach"])]

    def _label_date(self, when):
        if self.f["date_style"] == "full":
            return f"{when:%Y-%m-%d} {ampm(when)}"
        d = when.date()
        if d == self.today:
            return ampm(when)
        if 0 < (self.today - d).days < 7:
            return f"{KWD[d.weekday()]} {ampm(when)}"
        return d.isoformat()

    def _render(self, m, idx):
        dl = self._label_date(m["when"])
        return {"idx": idx, "key": f"{m['id']}|{m['sender']}", "label": f"{m['sender']}, {m['subject']}, {dl}",
                "titles": list(m.get("titles") or []), "texts": [m["sender"], m["subject"], dl],
                "dts": list(m.get("dts") or [])}

    def _list(self):
        vis = self._visible()
        self.window = vis[self.pos:self.pos + int(self.f["page"])]
        items = [self._render(m, i) for i, m in enumerate(self.window)]
        piv = ["중요"] if (self.f.get("pivot") and self.folder == "inbox") else []
        return {"href": self.url, "n": len(items), "items": items, "listboxes": 1 if items else 0, "search": True,
                "empty": bool(not items and self.f["empty_marker"]), "sel": FOLDER_NAME[self.folder], "pivots": piv}

    def _scroll(self):
        self.calls["scroll"] += 1
        vis = self._visible()
        if not vis:
            return "no-list"
        if self.f.get("no_scroller"):
            return "no-scroller"
        page = int(self.f["page"])
        if len(vis) <= page:
            return "fits"
        if self.pos + page >= len(vis):
            return "end"
        self.pos += int(self.f["step"])
        return "scrolled"

    def _header(self, ws):
        we = ws + timedelta(days=6)
        if ws in set(self.f.get("bad_header") or ()):
            ws, we = ws + timedelta(days=14), we + timedelta(days=14)
        if we.year != ws.year:
            tail = f"{we.year}년 {we.month}월 {we.day}일"
        elif we.month != ws.month:
            tail = f"{we.month}월 {we.day}일"
        else:
            tail = f"{we.day}일"
        return f"{ws.year}년 {ws.month}월 {ws.day}일–{tail}"

    def _cal(self):
        ws = self.week
        we = ws + timedelta(days=6)
        evs = []
        for ev in self.events:
            if ev["start"].date() <= we and ev["end"].date() >= ws:
                d = ev["start"]
                evs.append({"label": f"{ev['subject']}, {d.year}년 {d.month}월 {d.day}일 {KWD[d.weekday()]}요일 "
                                     f"{ampm(d)} ~ {ampm(ev['end'])}, 바쁨", "texts": [ev["subject"]]})
        return {"href": self.url, "grid": True, "n": len(evs), "events": evs, "heads": [self._header(ws), "오늘"],
                "cols": []}

    def _prev(self):
        self.calls["prev"] += 1
        if self.f.get("no_prev"):
            return "none"
        self.clicks += 1
        if self.clicks not in set(self.f.get("stuck_clicks") or ()):
            self.week -= timedelta(days=7)
        return "ok"

    def _eval(self, js):
        m = re.match(r"\s*/\*LM28:(\w+)\*/", str(js or ""))
        name = m.group(1) if m else ""
        if name == "owa_list":
            return self._list()
        if name == "owa_scroll":
            return self._scroll()
        if name == "owa_cal":
            return self._cal()
        if name == "owa_cal_prev":
            return self._prev()
        if name == "owa_open":
            self.calls["open"] += 1
            i = int(re.search(r"\[(\d+)\]", js).group(1))
            if i >= len(self.window):
                return "gone"
            self.pane = self.window[i].get("open")
            return "ok"
        if name == "owa_head":
            return {"found": bool(self.pane), "head": list(self.pane or [])}
        if "location.href" in str(js):
            return self.url
        if "readyState" in str(js):
            return "complete"
        return None
