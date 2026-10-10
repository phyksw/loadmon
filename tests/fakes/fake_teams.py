# -*- coding: utf-8 -*-
r"""tests\fakes\fake_teams.py — 팀즈 웹 화면 흉내(LM28 WP3). WP2 FakeBrowser 를 이어 쓴다(goto·href·close·calls·cdp.eval).
실제 Edge·Teams·네트워크를 쓰지 않는다. Get-TeamsWeb 의 JS 머리 표식(tw_list·tw_list_scroll·tw_list_top·tw_open·tw_pane·
tw_msgs·tw_scroll_up·tw_height·tw_census)으로 알아보고 각본 응답을 돌려준다(운영 JS 를 바꿔도 표식이 같으면 시험이 따라온다).

방 각본: room(이름, [msg(…)…], key="", **flags) — 메시지는 오래된 것 → 최신 순.
  stuck       — 눌러도 화면이 안 바뀐다(앞 방 그대로 — F-30 방 전환 실패)
  sel_only    — 누르면 목록 선택 표시만 이 방으로 옮고 대화 화면은 앞 방 그대로(선택 표시만 믿으면 앞 방 메시지를 이 방으로 적는다)
  no_scroller — 메시지 창의 스크롤 영역을 못 찾는다(다시 찾기도 실패 — F-06)
  deep        — 첫 찾기는 실패, 다시 찾기(조상 전체)는 성공
  lazy        — 맨 앞 lazy 개는 맨 위에서 기다려야 붙는다(지연 로드 — W1-05)
  broken      — 되감기 스크립트가 빈 응답(스크립트 오류)을 낸다
  head        — 대화 머리에 그려지는 제목(없으면 이름) — '홍길동 (외부)'·'이영희, 김철수' 처럼 목록 이름과 표기만 다른 머리
FakeTeams 각본: list_page(20)·list_step(10) — 목록 한 화면·한 번 내림 · msg_page(15)·msg_step(10) — 대화 첫 화면·되감기 한 번 ·
  no_sel(선택 표식 없음 — 제목으로만 확인) · no_head(머리 제목 없음) · list_no_scroller · cost(화면 하나당 가짜 시계 초) · login
  dom="v2"   — 새 Teams 웹(2026-10 회사 PC 실측) 흉내: 메시지는 V2_MSG, 머리는 V2_HEAD 로만 잡히고(운영 JS 의 후보표
               MSGS·HEADS 에 그 선택자가 있어야 맞는다 — 지난 판 후보로는 메시지 0·머리 없음), 목록에 선택 표시가 없다.
  click_modes — 화면을 실제로 바꾸는 누르기 방법 모음(None = 모두) · inner(False 면 항목 안에 누를 요소가 없다 → 'noinner')
  conv="nav" — 탭 세션 기록(mainWindowNavHistory)에 지금 대화 ID 가 있다(운영 JS 가 그것을 읽을 때만)
  start_open — 처음부터 열려 있는 방(rooms 의 위치 — 팀즈가 지난번 본 대화를 열어 둔 화면)
시계: self.clock(초) — 시험은 Get-TeamsWeb 의 _mono 를 br.mono, _sleep 을 br.sleep(시계를 민다)으로 바꾼다.
기록: self.calls Counter(open·open_<방법>·list·msgs·scroll_up·height·list_scroll·list_top·census) — 열기·되감기 횟수 비교용.
"""
import json
import os
import re
import sys
from datetime import datetime, timedelta

_FAKES = os.path.dirname(os.path.abspath(__file__))
if _FAKES not in sys.path:
    sys.path.insert(0, _FAKES)
import fake_browser as fb  # noqa: E402
import teams_parse  # noqa: E402  — 이름 정규화(운영과 같은 규칙)

V2_MSG = '[data-tid="chat-message-list"] [role="listitem"]'     # 새 Teams 웹 흉내의 메시지 항목(지난 판 후보에 없음)
V2_HEAD = '[id^="chat-header-"] h2'                              # 새 Teams 웹 흉내의 대화 머리(지난 판 후보에 없음)


def msg(when, author="동료", body="업무 협의 드립니다", mine=False, mid=""):
    return {"when": when, "author": author, "body": body, "mine": bool(mine), "id": mid}


def room(name, msgs, key="", **flags):
    return {"name": name, "msgs": list(msgs), "key": key, **flags}


def daily(name, d_from, d_to, hour=10, author=None, key="", every=1, **flags):
    """d_from~d_to 의 날마다(every 일 간격) 메시지 하나 — 본문에 날짜를 넣어 서로 다른 글로."""
    out, d, i = [], d_from, 0
    while d <= d_to:
        out.append(msg(datetime(d.year, d.month, d.day, hour, 5 + i % 50), author or f"{name}님",
                       f"{name} 업무 진행 공유 {d.month}월 {d.day}일 건"))
        d += timedelta(days=every)
        i += 1
    return room(name, out, key=key, **flags)


def list_stamp(when, today):
    """팀즈 목록의 마지막 활동 표기 — 오늘 '오후 3:12' · 어제 '어제' · 6일 안 '화요일' · 올해 '10/5' · 그 전 '2025-12-30'."""
    d = when.date()
    gap = (today - d).days
    if gap <= 0:
        return fb.ampm(when)
    if gap == 1:
        return "어제"
    if gap < 7:
        return fb.KWD[d.weekday()] + "요일"
    if d.year == today.year:
        return f"{d.month}/{d.day}"
    return d.isoformat()


def js_list(js, name):
    """운영 JS 의 후보표(const MSGS = [...]; 한 줄) → 목록. 없으면 []."""
    m = re.search(r"const " + name + r" = (\[.*\]);\n", str(js or ""))
    try:
        return json.loads(m.group(1)) if m else []
    except ValueError:
        return []


class FakeTeams(fb.FakeBrowser):
    def __init__(self, today, rooms, **flags):
        f = dict({"list_page": 20, "list_step": 10, "msg_page": 15, "msg_step": 10, "cost": 0.05}, **flags)
        super().__init__(today, **f)
        self.rooms = rooms
        self.lpos = 0
        self.cur = None            # 열린 방(rooms 의 위치)
        self.target = None         # 마지막으로 누른 목록 항목
        self.loaded = {}           # 방 위치 → DOM 에 붙은 메시지 수(최신부터)
        self.lazy = {}             # 방 위치 → 아직 숨은 맨 앞 메시지 수
        self.top_wait = set()      # 맨 위('top')를 알린 방 — 다음 높이 확인 때 숨은 메시지를 붙인다
        self.marked = set()        # 다시 찾기로 스크롤 영역에 표식을 단 방
        self.selected = None       # 목록에서 선택 표시가 붙은 항목(rooms 의 위치) — 보통 열린 방과 같다(sel_only 방은 다르다)
        self.clock = 0.0
        if self.f.get("start_open") is not None:
            i = int(self.f["start_open"])
            self.cur = self.selected = i
            self.loaded[i] = min(int(self.f["msg_page"]), len(self._vis(i)))

    # ── 가짜 시계 ──
    def mono(self):
        return self.clock

    def sleep(self, s):
        self.clock += float(s or 0)

    def goto(self, url, wait=6.0):
        self.calls["goto"] += 1
        self.url = url
        if self.f.get("login"):
            self.reason = "R-LOGIN"
            return "login"
        self.view = "teams"
        return "ok"

    # ── 화면 ──
    @property
    def v2(self):
        return self.f.get("dom") == "v2"

    def _vis(self, i):
        r = self.rooms[i]
        if i not in self.lazy:
            self.lazy[i] = int(r.get("lazy") or 0)
        return r["msgs"][self.lazy[i]:]

    def _jn(self, r):
        """화면(JS nameOf)이 만드는 이름 열쇠 — aria-label 첫 조각을 정규화."""
        return teams_parse.norm_name(re.split(r"[,|·]| - ", str(r["name"]))[0])

    def _title(self, i):
        return str(self.rooms[i].get("head") or self.rooms[i]["name"])

    def _profile(self, js):
        """(메시지 후보 순번, 머리 후보 순번) — v2 화면은 운영 JS 의 후보표에 그 화면의 표지가 있을 때만 맞는다."""
        if self.v2:
            msgs, heads = js_list(js, "MSGS"), js_list(js, "HEADS")
            mi = msgs.index(V2_MSG) if V2_MSG in msgs else -1
            hi = heads.index(V2_HEAD) if (V2_HEAD in heads and not self.f.get("no_head")) else -1
            return mi, hi
        return 0, (-1 if self.f.get("no_head") else 0)

    def _sel(self, js=""):
        """스크립트가 가리키는 방(KEY·NAME) 항목의 선택 표시 — 그 방이 열린 방이면 예. 목록 화면에 없으면 표시 없음(None)."""
        if self.v2 or self.f.get("no_sel"):
            return None
        i = self._find(js) if js else self.target
        return None if i is None else (i == self.selected)

    def _mid(self, k):
        """방 self.cur 의 보이는 k 번째 메시지 ID(맨 앞이 지연 로드로 숨어도 같은 메시지는 같은 ID)."""
        vis = self._vis(self.cur)
        return vis[k].get("id") or f"r{self.cur}-{k + self.lazy.get(self.cur, 0)}"

    def _fp(self):
        if self.cur is None:
            return []
        vis, k0 = self._dom()
        ids = ["m:" + self._mid(k) for k in range(k0, len(vis))]
        return list(dict.fromkeys(ids[:4] + ids[-4:]))

    def _conv(self, js):
        if self.f.get("conv") and self.cur is not None and "mainWindowNavHistory" in str(js or ""):
            return str(self.rooms[self.cur].get("key") or ""), "nav"
        return "", ""

    def _list(self):
        self.calls["list"] += 1
        page = int(self.f["list_page"])
        items = []
        for j, r in enumerate(self.rooms[self.lpos:self.lpos + page]):
            last = r["msgs"][-1] if r["msgs"] else None
            st = list_stamp(last["when"], self.today) if last else ""
            prev = str(last["body"])[:24] if last else ""
            items.append({"idx": j, "key": r.get("key") or "", "jn": self._jn(r), "label": f"{r['name']}, {prev}, {st}",
                          "hdr": False, "texts": [r["name"], prev, st]})
        marks = not (self.v2 or self.f.get("no_sel"))
        cen = {"role": "treeitem", "tag": "div", "tid": "" if self.v2 else "chat-list-item",
               "keyed": sum(1 for it in items if it["key"]), "exp": 0,
               "selT": (1 if (marks and self.selected is not None and self.lpos <= self.selected < self.lpos + page) else 0),
               "selA": len(items) if marks else 0}
        return {"href": self.url, "how": "fake-list", "n": len(items), "items": items, "cen": cen}

    def _list_scroll(self):
        self.calls["list_scroll"] += 1
        if self.f.get("list_no_scroller"):
            return "no-scroller"
        n, page = len(self.rooms), int(self.f["list_page"])
        if n <= page:
            return "fits"
        if self.lpos + page >= n:
            return "end"
        self.lpos = min(self.lpos + int(self.f["list_step"]), n - page)
        return "scrolled"

    def _arg(self, js, name):
        m = re.search(name + r' = ("(?:[^"\\]|\\.)*")', js)
        return json.loads(m.group(1)) if m else ""

    def _find(self, js):
        key, name = self._arg(js, "KEY"), self._arg(js, "NAME")
        page = int(self.f["list_page"])
        for i in range(self.lpos, min(len(self.rooms), self.lpos + page)):
            r = self.rooms[i]
            if (key and r.get("key") == key) or (not key and name and self._jn(r) == name):
                return i
        return None

    def _open(self, js):
        i = self._find(js)
        if i is None:
            return "gone"
        mode = self._arg(js, "MODE") or "item"
        if mode == "inner" and not self.f.get("inner", True):
            return "noinner"
        self.calls["open"] += 1
        self.calls["open_" + mode] += 1
        self.target = i
        modes = self.f.get("click_modes")
        if not self.rooms[i].get("stuck") and (modes is None or mode in modes):
            self.selected = i
            if not self.rooms[i].get("sel_only"):
                self.cur = i
                self.loaded[i] = min(int(self.f["msg_page"]), len(self._vis(i)))
        return "ok"

    def _pane(self, js=""):
        mi, hi = self._profile(js)
        if self.cur is None:
            return {"n": 0, "chat": "", "sel": None, "fp": [], "conv": "", "cv": "", "mi": mi, "hi": hi}
        conv, cv = self._conv(js)
        return {"n": self.loaded.get(self.cur, 0) if mi >= 0 else 0, "chat": self._title(self.cur) if hi >= 0 else "",
                "sel": self._sel(js), "fp": self._fp() if mi >= 0 else [], "conv": conv, "cv": cv, "mi": mi, "hi": hi}

    def _dom(self):
        vis = self._vis(self.cur)
        return vis, len(vis) - self.loaded.get(self.cur, 0)

    def _first(self):
        vis, k0 = self._dom()
        return f"{self.cur}|{k0}" if vis else ""

    def _msgs(self, js=""):
        self.calls["msgs"] += 1
        mi, hi = self._profile(js)
        if self.cur is None or mi < 0:
            return {"href": self.url, "how": "", "mi": -1, "chat": "", "hi": hi, "n": 0, "items": []}
        vis, k0 = self._dom()
        items = []
        for k in range(k0, len(vis)):
            m = vis[k]
            p = vis[k - 1] if k > 0 else None
            # 작성자 머리는 무리의 첫 말풍선만(같은 사람이 10분 안에 이어 쓴 말풍선은 이름이 없다)
            head = (not m["mine"]) and (p is None or p["mine"] or p["author"] != m["author"]
                                        or m["when"] - p["when"] > timedelta(minutes=10))
            mid = self._mid(k)
            items.append({"t": "msg", "mid": mid, "fid": "m:" + mid, "label": "",
                          "author": m["author"] if head else "", "ts": fb.ampm(m["when"]),
                          "iso": [] if self.f.get("no_iso") else [m["when"].strftime("%Y-%m-%dT%H:%M:00")],
                          "titles": [], "body": m["body"], "texts": [m["body"]], "mine": bool(m["mine"])})
        return {"href": self.url, "how": "fake-msgs", "mi": mi, "chat": self._title(self.cur) if hi >= 0 else "",
                "hi": hi, "n": len(items), "items": items}

    def _scroll_up(self, js):
        self.calls["scroll_up"] += 1
        if self.cur is None:
            return {"r": "no-scroller", "how": "", "h": 0, "n": 0, "f": ""}
        r = self.rooms[self.cur]
        if r.get("broken"):
            return None                            # 스크립트 오류(빈 응답) 흉내
        deep = "const DEEP = 1" in js
        n = self.loaded.get(self.cur, 0)
        base = {"h": n * 100, "n": n, "f": self._first()}
        if r.get("no_scroller") or (r.get("deep") and not deep and self.cur not in self.marked):
            return dict(base, r="no-scroller", how="")
        if r.get("deep"):
            self.marked.add(self.cur)
        vis = self._vis(self.cur)
        if n < len(vis):
            self.loaded[self.cur] = min(len(vis), n + int(self.f["msg_step"]))
            return dict(base, r="scrolled", how="fake-scroller")
        self.top_wait.add(self.cur)
        return dict(base, r="top", how="fake-scroller")

    def _height(self):
        self.calls["height"] += 1
        if self.cur is None:
            return {"h": 0, "n": 0, "f": ""}
        if self.cur in self.top_wait and self.lazy.get(self.cur, 0) > 0:
            k = self.lazy[self.cur]               # 맨 위에서 기다리니 지난 메시지가 위에 붙는다
            self.lazy[self.cur] = 0
            self.loaded[self.cur] = self.loaded.get(self.cur, 0) + k
        self.top_wait.discard(self.cur)
        n = self.loaded.get(self.cur, 0)
        return {"h": n * 100, "n": n, "f": self._first()}

    def _census(self, js):
        """JS_CENSUS 흉내 — 후보별 개수·머리 글자 수·선택 표시·대화 ID 출처·가린 골격(이름·본문 없음)."""
        self.calls["census"] += 1
        mi, hi = self._profile(js)
        msgs, heads = js_list(js, "MSGS"), js_list(js, "HEADS")
        n = self.loaded.get(self.cur, 0) if self.cur is not None else 0
        page = len(self.rooms[self.lpos:self.lpos + int(self.f["list_page"])])
        marks = not (self.v2 or self.f.get("no_sel"))
        return {"loc": "teams.cloud.microsoft/v2/" if self.v2 else "teams.microsoft.com/v2/",
                "list": [0, 0, 0, page, 0, 0] if self.v2 else [page, page, 0, 0, 0, 0],
                "msg": [n if k == mi else 0 for k in range(len(msgs))],
                "head": [len(self._title(self.cur)) if (k == hi and self.cur is not None) else -1 for k in range(len(heads))],
                "vp": [[n * 100, 600, 0] if k == 1 else 0 for k in range(7)],
                "sel": {"n": page, "ast": 1 if marks else 0, "asa": page if marks else 0, "ac": 0, "ds": 0, "cls": 0},
                "conv": "nav" if self.f.get("conv") else "",
                "tids": (["chat-message-list:1", f"message-body:{n}", "chat-header:1"] if self.v2
                         else [f"chat-pane-item:{n}", "message-author-name:3"]),
                "skel": {"item": ["0 div r=treeitem label#31 ti=-1 +2", "1 div +3", "2 span ~#3", "2 span ~#18",
                                  '2 span ~"오후 3:12"'],
                         "head": ["0 div#chat-header- +2", "1 h2 ~#5"],
                         "msg": ["0 div r=listitem +3", "1 div#author- ~#3", '1 time datetime#20 ~"오전 9:05"',
                                 "1 div#content- ~#24"]},
                "mi": mi}

    def _eval(self, js):
        self.clock += float(self.f.get("cost") or 0)
        m = re.match(r"\s*/\*LM28:(\w+)\*/", str(js or ""))
        name = m.group(1) if m else ""
        if name == "tw_list":
            return self._list()
        if name == "tw_list_scroll":
            return self._list_scroll()
        if name == "tw_list_top":
            self.calls["list_top"] += 1
            self.lpos = 0
            return "ok"
        if name == "tw_open":
            return self._open(js)
        if name == "tw_pane":
            return self._pane(js)
        if name == "tw_msgs":
            return self._msgs(js)
        if name == "tw_scroll_up":
            return self._scroll_up(js)
        if name == "tw_height":
            return self._height()
        if name == "tw_census":
            return self._census(js)
        return super()._eval(js)
