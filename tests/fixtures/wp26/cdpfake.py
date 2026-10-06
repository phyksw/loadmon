# -*- coding: utf-8 -*-
r"""WP-26 시험용 EdgeSession 대역 — 실제 화면 코드(``CdpOwaScreen`` · ``CdpTeamsScreen``)를 브라우저 없이 돌린다.

``start`` · ``close`` · ``goto`` · ``wait_page`` · ``eval`` · ``call`` · ``tick`` · ``page_state`` · ``state`` · ``error`` · ``cfg``
만 흉내 낸다(계약 §2.12 ``EdgeSession`` 의 웹 수집 역할이 쓰는 부분). 페이지에서 평가할 JS 는 머리 표식 ``/*LM27:<이름>*/``
으로 처리기를 고른다(브리지 ``tests\bridge\fake_cdp.py`` 와 같은 방식 — 이 파일은 WP-26 자기 대역).
화면 모형은 합성 dict: OWA ``{"inbox": [[항목…], …(스크롤 회차)], "sent": [...], "cal": {날짜: [일정…]}}`` ·
Teams ``{"chats": [[항목…], …], "msgs": {tid: [[메시지…], …]}, "gone": [tid…]}``.
"""
from __future__ import annotations

import json
import re
import types
from datetime import date, timedelta
from urllib.parse import urlsplit

_MARK = re.compile(r"^/\*LM27:([a-z_]+)\*/")
_JSON_STR = r'("(?:[^"\\]|\\.)*")'


class FakeSession:
    def __init__(self, *, start_state: str = "ready", error=None, login: bool = False, aadsts: str = "",
                 host: str | None = None, owa=None, teams=None, login_paths=()):
        self.start_state = start_state
        self.error = dict(error or {})
        self.login = login
        self.login_paths = tuple(login_paths)          # 이 경로 조각이 든 주소로 가면 로그인 화면(중간 만료 흉내)
        self.aadsts = aadsts
        self.host_override = host
        self.owa = owa or {}
        self.teams = teams or {}
        self.cfg = types.SimpleNamespace(login_wait_min=1)
        self.state = ""
        self.url = "about:blank"
        self.gotos: list = []
        self.calls: list = []
        self.evals: list = []
        self.opened: list = []
        self.closed = False
        self.pos: dict = {}
        self.window: list = []
        self.head = None
        self.room = None
        self.rpos = 0

    # ── 세션 ──
    def start(self) -> str:
        self.state = self.start_state
        return self.state

    def close(self) -> None:
        self.closed = True

    def tick(self) -> None:
        return None

    def _login_now(self) -> bool:
        return self.login or any(p in self.url for p in self.login_paths)

    def goto(self, url: str, dl=None) -> str:
        self.url = url
        self.gotos.append(url)
        return "login_required" if self._login_now() else "ready"

    def wait_page(self, dl=None) -> str:
        return "login_required" if self._login_now() else "ready"

    def page_state(self) -> dict:
        host = self.host_override if self.host_override is not None else (urlsplit(self.url).hostname or "")
        return {"host": host, "ready": "complete", "url": self.url}

    def call(self, method: str, params: dict) -> None:
        self.calls.append((method, dict(params)))

    def eval(self, expr: str, timeout=None):
        m = _MARK.match(expr or "")
        name = m.group(1) if m else ""
        self.evals.append(name)
        fn = getattr(self, "_js_" + name, None)
        return fn(expr) if fn else None

    # ── OWA ──
    def _folder(self) -> str:
        p = urlsplit(self.url).path
        return "sent" if p.endswith("/sentitems") else "inbox"

    def _js_owa_list(self, expr):
        f = self._folder()
        pages = self.owa.get(f) or [[]]
        i = min(self.pos.get(f, 0), len(pages) - 1)
        items = [dict(it, idx=k) for k, it in enumerate(pages[i])]
        self.window = items
        return {"how": '[role="listbox"] [role="option"]', "n": len(items), "items": items, "listboxes": 1,
                "search": True}

    def _js_owa_scroll(self, expr):
        f = self._folder()
        pages = self.owa.get(f) or [[]]
        if self.pos.get(f, 0) + 1 < len(pages):
            self.pos[f] = self.pos.get(f, 0) + 1
            return "scrolled"
        return "end"

    def _js_owa_focus_search(self, expr):
        return "ok"

    def _js_owa_clear_search(self, expr):
        self.pos = {}
        return "cleared"

    def _js_owa_open(self, expr):
        m = re.search(r"\[\]\)\[(\d+)\]", expr)
        idx = int(m.group(1)) if m else -1
        if not 0 <= idx < len(self.window):
            return "gone"
        it = self.window[idx]
        self.opened.append((self._folder(), idx))
        op = it.get("open") if isinstance(it.get("open"), dict) else {}
        self.head = list(op.get("head") or [])
        return "ok"

    def _js_owa_head(self, expr):
        return {"found": bool(self.head), "head": list(self.head or [])}

    def _js_owa_cal(self, expr):
        m = re.search(r"/calendar/view/week/(\d{4})/(\d{1,2})/(\d{1,2})", self.url)
        if not m:
            return {"grid": False, "n": 0, "events": []}
        wk = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        evs = []
        for i in range(7):
            evs += list((self.owa.get("cal") or {}).get((wk + timedelta(days=i)).isoformat()) or [])
        return {"grid": True, "n": len(evs), "events": evs}

    def _js_web_aadsts(self, expr):
        return self.aadsts

    # ── Teams ──
    def _which(self, expr, rx):
        m = re.search(rx, expr)
        return json.loads(m.group(1)) if m else "chats"

    def _js_tw_nav(self, expr):
        return "ok"

    def _js_tw_list(self, expr):
        w = self._which(expr, r"var which=" + _JSON_STR)
        pages = self.teams.get(w) or [[]]
        i = min(self.pos.get(w, 0), len(pages) - 1)
        items = [dict(it, idx=k) for k, it in enumerate(pages[i])]
        return {"how": '[data-tid="chat-list-item"]' if pages != [[]] else "", "n": len(items), "items": items}

    def _js_tw_list_scroll(self, expr):
        w = self._which(expr, r"\+" + _JSON_STR + r"\]")
        pages = self.teams.get(w) or [[]]
        if self.pos.get(w, 0) + 1 < len(pages):
            self.pos[w] = self.pos.get(w, 0) + 1
            return "scrolled"
        return "end"

    def _js_tw_open(self, expr):
        t = self._which(expr, r"tid=" + _JSON_STR)
        if t in (self.teams.get("gone") or []) or t not in (self.teams.get("msgs") or {}):
            return "gone"
        self.room, self.rpos = t, 0
        self.opened.append(("room", t))
        return "ok"

    def _rounds(self):
        return (self.teams.get("msgs") or {}).get(self.room) or [[]]

    def _js_tw_msgs(self, expr):
        items = list(self._rounds()[min(self.rpos, len(self._rounds()) - 1)])
        return {"how": '[data-tid="chat-pane-item"]', "chat": "", "n": len(items), "items": items, "ctype": "",
                "n_part": None}

    def _js_tw_scroll_up(self, expr):
        if self.rpos + 1 < len(self._rounds()):
            self.rpos += 1
            return "scrolled"
        return "top"

    def _js_tw_pane(self, expr):
        return {"n": len(self._rounds()[min(self.rpos, len(self._rounds()) - 1)]), "chat": f"{self.room}|{self.rpos}"}


def factory(session: FakeSession):
    """수집기의 ``session_factory`` 자리 — (역할, run_id, paths=, clock=, environ=) 를 받아 대역을 돌려준다."""
    def make(role, run_id, *, paths=None, clock=None, environ=None):
        session.role, session.run_id = role, run_id
        return session
    return make
