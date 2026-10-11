# -*- coding: utf-8 -*-
r"""tests\fakes\fake_teams.py — 팀즈 웹 화면 흉내(LM28 WP3 · LM28-TW-2). WP2 FakeBrowser 를 이어 쓴다(goto·href·close·calls·cdp).
실제 Edge·Teams·네트워크를 쓰지 않는다. Get-TeamsWeb 의 JS 머리 표식(tw_list·tw_list_scroll·tw_list_top·tw_aim·tw_pane·
tw_msgs·tw_scroll_up·tw_height·tw_census)으로 알아보고, 그 화면에서 운영 JS 가 '무엇을 보고했을지'를 각본으로 돌려준다
(JS 를 실행하지 않는다 — 운영 JS 를 바꿔도 표식과 응답 꼴이 같으면 시험이 따라온다). CDP 신뢰 입력(Input.dispatchMouseEvent ·
Input.dispatchKeyEvent)은 _TeamsCdp 가 받아 그 점의 목록 행을 누른다.

방 각본: room(이름, [msg(…)…], key="", **flags) — 메시지는 오래된 것 → 최신 순.
  stuck       — 눌러도 화면이 안 바뀐다(앞 방 그대로 — F-30 방 전환 실패)
  sel_only    — 누르면 목록 선택 표시만 이 방으로 옮고 대화 화면은 앞 방 그대로(선택 표시만 믿으면 앞 방 메시지를 이 방으로 적는다)
  doc_only    — 누르면 창 제목(document.title)만 이 방으로 바뀌고 대화 화면은 앞 방 그대로(창 제목만 믿으면 안 된다)
  no_scroller — 메시지 창의 스크롤 영역을 못 찾는다(다시 찾기도 실패 — F-06)
  deep        — 첫 찾기는 실패, 다시 찾기(조상 전체)는 성공
  lazy        — 맨 앞 lazy 개는 맨 위에서 기다려야 붙는다(지연 로드 — W1-05)
  broken      — 되감기 스크립트가 빈 응답(스크립트 오류)을 낸다
  head        — 대화 머리에 그려지는 제목(없으면 이름) — '홍길동 (외부)'·'이영희, 김철수' 처럼 목록 이름과 표기만 다른 머리
  doc         — v3 창 제목의 방 조각(없으면 이름) — '김철수, 이영희 + 1' 처럼 '+ n' 이 붙은 제목
  unread      — v3 목록의 안 읽음 배지 수(이름 잎이 굵어진다)
FakeTeams 각본: list_page(20)·list_step(10) — 목록 한 화면 행 수·한 번 내림 · msg_page(15)·msg_step(10) — 대화 첫 화면·되감기 한 번 ·
  no_sel(선택 표식 없음 — 제목으로만 확인) · no_head(머리 제목 없음) · list_no_scroller · cost(화면 하나당 가짜 시계 초) · login
  dom="v2"   — 새 Teams 웹(2026-10-08 회사 PC 실측) 흉내: 메시지는 V2_MSG, 머리는 V2_HEAD 로만 잡히고(운영 JS 의 후보표
               MSGS·HEADS 에 그 선택자가 있어야 맞는다), 목록에 선택 표시가 없다.
  dom="v3"   — 2026-10-11 회사 PC 실측('목록 61 · 열기 못찾음 10 · 화면멈춤 2(빈2)') 흉내: 목록은 중첩 트리(맨 위에 구역 머리
               '최근 채팅' — aria-expanded·안에 방들을 품음, 누르면 접힌다) · 방 항목에 aria-label 이 없고 첫 잎이 시각인데 목록을
               내리면 다른 표기로, 마우스를 올리면 '옵션 더 보기' 단추 글로 바뀐다 · 합성 사건(isTrusted=false)은 무시하고 CDP 신뢰
               마우스(그 점의 행 — 오른쪽 30% 는 '…' 메뉴)·포커스 + CDP Enter 로만 방이 열린다 · 대화 화면에 후보 data-tid·머리가
               하나도 없고 time[datetime] 단위(일반 읽기)만 있다 · 창 제목 '채팅 | <방> | Microsoft Teams' 가 열린 방을 따라 바뀐다.
  collapsed  — v3 구역 머리가 처음에 접혀 있다(방이 목록에 없다 — 펼쳐야 보인다) · expand_dead — 눌러도 안 펼쳐진다
  doc_plain  — v3 창 제목이 방을 말하지 않는다('Microsoft Teams' 뿐) · aim_error — 겨누기 스크립트가 JS 오류를 낸다
  click_modes — 화면을 실제로 바꾸는 누르기 방법 모음('mouse'·'synth'·'key' · None = 모두 — v3 의 synth 는 늘 무시)
  conv="nav" — 탭 세션 기록(mainWindowNavHistory)에 지금 대화 ID 가 있다(운영 JS 가 그것을 읽을 때만)
  start_open — 처음부터 열려 있는 방(rooms 의 위치 — 팀즈가 지난번 본 대화를 열어 둔 화면)
시계: self.clock(초) — 시험은 Get-TeamsWeb 의 _mono 를 br.mono, _sleep 을 br.sleep(시계를 민다)으로 바꾼다.
기록: self.calls Counter(open·open_<방법>·hdr_<방법>·menu·escape·aim·list·msgs·scroll_up·height·list_scroll·list_top·census·
  hovered(마우스가 올라간 행을 그림)·restamped(내린 목록에서 시각을 다른 표기로 그림)·cdp:<메서드>) · self.click_log [(방 위치, 방법)] ·
  self.opened_log [실제로 화면이 바뀐 방 위치].
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

V2_MSG = '[data-tid="chat-message-list"] [role="listitem"]'     # 새 Teams 웹 흉내의 메시지 항목(지난 판 후보에 없음)
V2_HEAD = '[id^="chat-header-"] h2'                              # 새 Teams 웹 흉내의 대화 머리(지난 판 후보에 없음)
GEN = -2                                                         # 운영 JS 의 '일반 읽기' 순번
TOP, ROW, LEFT, WIDTH = 56, 40, 68, 320                          # 목록 행 사각형(뷰포트 1150×900 — 20행이 다 보인다)
HOVER_TEXT = "옵션 더 보기"


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


class _TeamsCdp(fb._Cdp):
    """CDP 흉내 — 신뢰 입력(마우스 옮김·누름·뗌, 키)을 화면 흉내로 넘긴다(호출 수는 calls['cdp:<메서드>'])."""

    def call(self, method, params=None, timeout=25):
        r = super().call(method, params, timeout)
        p = params or {}
        if method == "Input.dispatchMouseEvent" and p.get("type") != "mouseWheel":
            self.br._mouse(p)
        elif method == "Input.dispatchKeyEvent":
            self.br._keyev(p)
        return r


class FakeTeams(fb.FakeBrowser):
    def __init__(self, today, rooms, **flags):
        f = dict({"list_page": 20, "list_step": 10, "msg_page": 15, "msg_step": 10, "cost": 0.05}, **flags)
        super().__init__(today, **f)
        self.cdp = _TeamsCdp(self)
        self.rooms = rooms
        self.lpos = 0
        self.cur = None            # 열린 방(rooms 의 위치) — 대화 화면이 보여 주는 방
        self.doc_i = None          # 창 제목이 말하는 방(보통 cur — doc_only 방은 제목만 바뀐다)
        self.target = None         # 마지막으로 겨눈·누른 목록 항목
        self.loaded = {}           # 방 위치 → DOM 에 붙은 메시지 수(최신부터)
        self.lazy = {}             # 방 위치 → 아직 숨은 맨 앞 메시지 수
        self.top_wait = set()      # 맨 위('top')를 알린 방 — 다음 높이 확인 때 숨은 메시지를 붙인다
        self.marked = set()        # 다시 찾기로 스크롤 영역에 표식을 단 방
        self.selected = None       # 목록에서 선택 표시가 붙은 항목(rooms 의 위치) — 보통 열린 방과 같다(sel_only 방은 다르다)
        self.hover = None          # 마우스가 올라간 목록 행 ('room', i) | ('hdr', None)
        self.press = None          # 누른(아직 떼지 않은) 행
        self.focused = None        # 포커스를 받은 행(키 Enter 의 대상)
        self.menu_open = False     # '…' 메뉴가 열렸다(오른쪽 30% 를 누름)
        self.expanded = not self.f.get("collapsed")
        self.click_log = []        # [(방 위치, 방법)] — 방 항목을 누른 시도
        self.opened_log = []       # [방 위치] — 실제로 대화 화면이 바뀐 방
        self.clock = 0.0
        if self.f.get("start_open") is not None:
            i = int(self.f["start_open"])
            self.cur = self.selected = self.doc_i = i
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

    @property
    def v3(self):
        return self.f.get("dom") == "v3"

    def _vis(self, i):
        r = self.rooms[i]
        if i not in self.lazy:
            self.lazy[i] = int(r.get("lazy") or 0)
        return r["msgs"][self.lazy[i]:]

    def _title(self, i):
        return str(self.rooms[i].get("head") or self.rooms[i]["name"])

    def _doc(self):
        """창 제목 — v1·v2 는 방을 말하지 않는다(지난 판 화면) · v3 는 '채팅 | <방> | Microsoft Teams'."""
        if not self.v3 or self.f.get("doc_plain"):
            return "Microsoft Teams"
        if self.doc_i is None:
            return "채팅 | Microsoft Teams"
        r = self.rooms[self.doc_i]
        return f"채팅 | {r.get('doc') or r['name']} | Microsoft Teams"

    def _profile(self, js):
        """(메시지 후보 순번, 머리 후보 순번) — v2 화면은 운영 JS 의 후보표에 그 화면의 표지가 있을 때만 맞는다 · v3 는 후보가
        하나도 맞지 않고 일반 읽기(GEN)만."""
        if self.v3:
            return (GEN if self.cur is not None else -1), -1
        if self.v2:
            msgs, heads = js_list(js, "MSGS"), js_list(js, "HEADS")
            mi = msgs.index(V2_MSG) if V2_MSG in msgs else -1
            hi = heads.index(V2_HEAD) if (V2_HEAD in heads and not self.f.get("no_head")) else -1
            return mi, hi
        return 0, (-1 if self.f.get("no_head") else 0)

    def _sel(self, js=""):
        """스크립트가 가리키는 방(KEY·SIG) 항목의 선택 표시 — 그 방이 열린 방이면 예. 목록 화면에 없으면 표시 없음(None)."""
        if self.v2 or self.v3 or self.f.get("no_sel"):
            return None
        i = self._find(js) if js else self.target
        return None if i is None else (i == self.selected)

    def _mid(self, k):
        """방 self.cur 의 보이는 k 번째 메시지 ID(맨 앞이 지연 로드로 숨어도 같은 메시지는 같은 ID)."""
        vis = self._vis(self.cur)
        return vis[k].get("id") or f"r{self.cur}-{k + self.lazy.get(self.cur, 0)}"

    def _fid(self, k):
        """메시지 지문 — v3(일반 읽기)는 메시지 ID 가 없어 '<time datetime>+글 해시'('t:'), 그 밖은 메시지 ID('m:')."""
        if self.v3:
            m = self._vis(self.cur)[k]
            return "t:" + m["when"].strftime("%Y-%m-%dT%H:%M:00") + ":" + self._mid(k)
        return "m:" + self._mid(k)

    def _fp(self):
        if self.cur is None:
            return []
        vis, k0 = self._dom()
        ids = [self._fid(k) for k in range(k0, len(vis))]
        return list(dict.fromkeys(ids[:4] + ids[-4:]))

    def _conv(self, js):
        if self.f.get("conv") and self.cur is not None and "mainWindowNavHistory" in str(js or ""):
            return str(self.rooms[self.cur].get("key") or ""), "nav"
        return "", ""

    # ── 목록 ──
    def _rows(self):
        """목록 DOM 행 — v3 는 맨 위에 구역 머리, 접혀 있으면 방이 없다."""
        rows = [("hdr", None)] if self.v3 else []
        if not self.v3 or self.expanded:
            rows += [("room", i) for i in range(len(self.rooms))]
        return rows

    def _window(self):
        page = int(self.f["list_page"])
        return self._rows()[self.lpos:self.lpos + page]

    def _item(self, j, row):
        """운영 JS_CHATS 가 그 행에서 보고했을 항목(순번·대화 ID·aria-label·단계·펼침·품은 수·행 사각형·잎 묘사)."""
        kind, i = row
        rect = [LEFT, TOP + j * ROW, WIDTH, ROW]
        if kind == "hdr":
            return {"idx": j, "key": "", "label": "", "lby": "", "lv": 1, "ex": "true" if self.expanded else "false",
                    "nest": len(self.rooms) if self.expanded else 0, "r": rect, "lf": [["최근 채팅", 0, 1, ""]]}
        r = self.rooms[i]
        last = r["msgs"][-1] if r["msgs"] else None
        st = list_stamp(last["when"], self.today) if last else ""
        prev = str(last["body"])[:24] if last else ""
        if self.v3:
            stamp = st
            if self.lpos and last and re.match(r"(오전|오후) \d", st):
                stamp = f"{last['when']:%H:%M}"          # 목록을 내리면 같은 시각을 다른 표기로 다시 그린다
                self.calls["restamped"] += 1
            if self.hover == ("room", i):
                first = [HOVER_TEXT, 0, 0, "B"]          # 마우스를 올리면 시각 자리에 '…' 단추가 뜬다
                self.calls["hovered"] += 1
            else:
                first = [stamp, 0, 0, ""]
            lf = [first, [r["name"], 0, 1 if r.get("unread") else 0, ""], [prev, 1, 0, ""]]
            if r.get("unread"):
                lf.append([str(r["unread"]), 0, 1, ""])
            return {"idx": j, "key": r.get("key") or "", "label": "", "lby": "", "lv": 2, "ex": "", "nest": 0, "r": rect,
                    "lf": lf}
        return {"idx": j, "key": r.get("key") or "", "label": f"{r['name']}, {prev}, {st}", "lby": "", "lv": 0, "ex": "",
                "nest": 0, "r": rect, "lf": [[r["name"], 0, 1, ""], [st, 0, 0, ""], [prev, 1, 0, ""]]}

    def _list(self):
        self.calls["list"] += 1
        win = self._window()
        items = [self._item(j, row) for j, row in enumerate(win)]
        rooms = [it for it in items if not (it["ex"] or it["nest"])]
        on = [row[1] for row in win if row[0] == "room"]
        marks = not (self.v2 or self.v3 or self.f.get("no_sel"))
        cen = {"role": "treeitem", "tag": "div", "tid": "" if (self.v2 or self.v3) else "chat-list-item",
               "rooms": len(rooms), "keyed": sum(1 for it in rooms if it["key"]), "lbl": sum(1 for it in rooms if it["label"]),
               "lby": 0, "exp": sum(1 for it in items if it["ex"]),
               "selT": 1 if (marks and self.selected in on) else 0, "selA": len(rooms) if marks else 0,
               "lv": (["1:1", f"2:{len(rooms)}"] if self.v3 else [f"-:{len(rooms)}"]),
               "ex": [sum(1 for it in items if it["ex"] == "true"), sum(1 for it in items if it["ex"] == "false"),
                      sum(1 for it in items if it["nest"])]}
        return {"href": "", "how": "fake-list", "n": len(items), "items": items, "cen": cen, "vw": 1150, "vh": 900}

    def _list_scroll(self):
        self.calls["list_scroll"] += 1
        if self.f.get("list_no_scroller"):
            return "no-scroller"
        n, page = len(self._rows()), int(self.f["list_page"])
        if n <= page:
            return "fits"
        if self.lpos + page >= n:
            return "end"
        self.lpos = min(self.lpos + int(self.f["list_step"]), n - page)
        return "scrolled"

    @staticmethod
    def _arg(js, name):
        m = re.search(r"\b" + name + r' = ("(?:[^"\\]|\\.)*")', str(js or ""))
        return json.loads(m.group(1)) if m else ""

    @staticmethod
    def _num(js, name, d=-1):
        m = re.search(r"\b" + name + r" = (-?\d+)", str(js or ""))
        return int(m.group(1)) if m else d

    @staticmethod
    def _hit(it, key, sig, hdr):
        """운영 JS 의 겨누기 맞춤 흉내 — 구역 머리 여부가 같고, 대화 ID 가 있으면 그것, 없으면 안정 이름(aria-label 첫 조각 또는
        제 잎 글 하나 — 지금 그려진 글: 마우스가 올라가 바뀐 잎은 바뀐 글)."""
        if bool(it["ex"] or it["nest"]) != hdr:
            return False
        if key:
            return it["key"] == key
        if not sig:
            return False
        lb = re.split(r"[,|·]| - ", it["label"])[0].strip() if it["label"] else ""
        return (bool(lb) and lb == sig) or any(str(x[0]).strip() == sig for x in it["lf"])

    def _pick(self, js):
        """스크립트의 IDX·KEY·SIG·HDR 로 지금 목록 화면의 행을 고른다(맞는 것 중 순번이 가장 가까운 것) → (순번, 행) | None."""
        idx, key, sig = self._num(js, "IDX"), self._arg(js, "KEY"), self._arg(js, "SIG")
        hdr = bool(re.search(r"\bHDR = true\b", str(js or "")))
        win = self._window()
        cands = [(j, row) for j, row in enumerate(win) if self._hit(self._item(j, row), key, sig, hdr)]
        if not cands:
            return None
        return min(cands, key=lambda c: abs(c[0] - idx))

    def _find(self, js):
        hit = self._pick(js)
        return hit[1][1] if (hit and hit[1][0] == "room") else None

    def _aim(self, js):
        """JS_AIM 흉내 — 겨눈 행의 왼쪽~가운데 점(폭의 30%)을 돌려준다 · ACT synth 는 그 자리에서 합성 사건 · focus 는 포커스."""
        self.calls["aim"] += 1
        if self.f.get("aim_error"):
            raise RuntimeError("JS: TypeError: Cannot read properties of null (reading 'matches')")
        hit = self._pick(js)
        if hit is None:
            return {"r": "gone"}
        j, row = hit
        out = {"r": "ok", "x": LEFT + int(WIDTH * 0.3), "y": TOP + j * ROW + ROW // 2, "hit": 1, "why": "", "vis": 1, "i": j,
               "menu": 1 if self.menu_open else 0}
        if row[0] == "room":
            self.target = row[1]
        act = self._arg(js, "ACT") or "aim"
        if act == "synth":
            out["r"] = "fired"
            self._activate(row, "synth")
        elif act == "focus":
            self.focused = row
            out["focus"] = 1
        return out

    def _activate(self, row, mode):
        """행을 '누름' — 구역 머리는 접힘/펼침이 바뀐다 · 방은 각본대로 화면이 바뀐다(v3 의 합성 사건은 무시)."""
        kind, i = row
        if kind == "hdr":
            self.calls["hdr_" + mode] += 1
            if (self.v3 and mode == "synth") or self.f.get("expand_dead"):
                return
            self.expanded = not self.expanded
            self.lpos = max(0, min(self.lpos, len(self._rows()) - int(self.f["list_page"])))
            return
        self.calls["open"] += 1
        self.calls["open_" + mode] += 1
        self.click_log.append((i, mode))
        self.target = i
        if self.v3 and mode == "synth":
            return                                       # isTrusted=false 사건은 받지 않는 화면
        modes = self.f.get("click_modes")
        r = self.rooms[i]
        if r.get("stuck") or (modes is not None and mode not in modes):
            return
        self.selected = i
        if r.get("sel_only"):
            return
        self.doc_i = i
        if r.get("doc_only"):
            return
        self.cur = i
        self.loaded[i] = min(int(self.f["msg_page"]), len(self._vis(i)))
        self.opened_log.append(i)

    def _row_at(self, x, y):
        if not (LEFT <= x <= LEFT + WIDTH) or y < TOP:
            return None
        j = int((y - TOP) // ROW)
        win = self._window()
        return win[j] if 0 <= j < len(win) else None

    def _mouse(self, p):
        """CDP Input.dispatchMouseEvent 흉내 — 옮김은 그 행에 마우스를 올리고, 누름·뗌이 같은 행이면 그 행을 누른다(오른쪽 30% 는
        '…' 메뉴가 열린다)."""
        t = p.get("type")
        x, y = float(p.get("x") or 0), float(p.get("y") or 0)
        row = self._row_at(x, y)
        if t == "mouseMoved":
            self.hover = row
        elif t == "mousePressed":
            self.press = row
        elif t == "mouseReleased":
            row0, self.press = self.press, None
            if row is None or row != row0:
                return
            if x > LEFT + WIDTH * 0.7:
                self.calls["menu"] += 1
                self.menu_open = True
                return
            self._activate(row, "mouse")

    def _keyev(self, p):
        """CDP Input.dispatchKeyEvent 흉내 — Escape 는 메뉴를 닫고, Enter 는 포커스 받은 행을 누른다."""
        if p.get("type") not in ("rawKeyDown", "keyDown"):
            return
        if p.get("key") == "Escape":
            self.calls["escape"] += 1
            self.menu_open = False
        elif p.get("key") == "Enter" and self.focused is not None:
            self._activate(self.focused, "key")

    # ── 대화 화면 ──
    def _pane(self, js=""):
        mi, hi = self._profile(js)
        doc = self._doc()
        if self.cur is None:
            return {"n": 0, "chat": "", "sel": None, "fp": [], "conv": "", "cv": "", "mi": mi, "hi": hi, "doc": doc,
                    "url": self.url}
        conv, cv = self._conv(js)
        has = mi >= 0 or mi == GEN
        return {"n": self.loaded.get(self.cur, 0) if has else 0, "chat": self._title(self.cur) if hi >= 0 else "",
                "sel": self._sel(js), "fp": self._fp() if has else [], "conv": conv, "cv": cv, "mi": mi, "hi": hi,
                "doc": doc, "url": self.url}

    def _dom(self):
        vis = self._vis(self.cur)
        return vis, len(vis) - self.loaded.get(self.cur, 0)

    def _first(self):
        vis, k0 = self._dom()
        return f"{self.cur}|{k0}" if vis else ""

    def _msgs(self, js=""):
        self.calls["msgs"] += 1
        mi, hi = self._profile(js)
        if self.cur is None or not (mi >= 0 or mi == GEN):
            return {"href": "", "how": "", "mi": -1, "chat": "", "hi": hi, "n": 0, "items": [], "doc": self._doc()}
        vis, k0 = self._dom()
        items, day = [], None
        for k in range(k0, len(vis)):
            m = vis[k]
            p = vis[k - 1] if k > 0 else None
            # 작성자 머리는 무리의 첫 말풍선만(같은 사람이 10분 안에 이어 쓴 말풍선은 이름이 없다)
            head = (not m["mine"]) and (p is None or p["mine"] or p["author"] != m["author"]
                                        or m["when"] - p["when"] > timedelta(minutes=10))
            iso = m["when"].strftime("%Y-%m-%dT%H:%M:00")
            if self.v3:
                if m["when"].date() != day:              # 날짜 구분선(일반 읽기 화면도 메시지 목록 안에서 찾는다)
                    day = m["when"].date()
                    items.append({"t": "sep", "text": f"{day.year}년 {day.month}월 {day.day}일", "iso": ""})
                ts = f"{m['when']:%m-%d} {fb.ampm(m['when'])}"
                items.append({"t": "msg", "gen": 1, "mid": "", "fid": self._fid(k), "label": "",
                              "author": m["author"] if head else "", "ts": ts, "iso": [iso], "titles": [], "body": m["body"],
                              "texts": ([m["author"]] if head else []) + [ts, m["body"]], "mine": bool(m["mine"])})
                continue
            mid = self._mid(k)
            items.append({"t": "msg", "mid": mid, "fid": "m:" + mid, "label": "",
                          "author": m["author"] if head else "", "ts": fb.ampm(m["when"]),
                          "iso": [] if self.f.get("no_iso") else [iso],
                          "titles": [], "body": m["body"], "texts": [m["body"]], "mine": bool(m["mine"])})
        return {"href": "", "how": "gen" if self.v3 else "fake-msgs", "mi": mi,
                "chat": self._title(self.cur) if hi >= 0 else "", "hi": hi, "n": sum(1 for x in items if x["t"] == "msg"),
                "items": items, "doc": self._doc()}

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
        """JS_CENSUS 흉내 — 후보별 개수·머리 글자 수·선택 표시·대화 ID 출처·대화 영역 data-tid·일반 읽기 단위·시각 수·창 제목(원문 —
        운영 파이썬이 가린다)·문서 보임·가린 골격(이름·본문 없음)."""
        self.calls["census"] += 1
        mi, hi = self._profile(js)
        msgs, heads = js_list(js, "MSGS"), js_list(js, "HEADS")
        n = self.loaded.get(self.cur, 0) if self.cur is not None else 0
        win = self._window()
        page = sum(1 for row in win if row[0] == "room")
        marks = not (self.v2 or self.v3 or self.f.get("no_sel"))
        out = {"loc": "teams.cloud.microsoft/v2/" if (self.v2 or self.v3) else "teams.microsoft.com/v2/",
               "list": [0, 0, 0, len(win), 0, 0] if (self.v2 or self.v3) else [page, page, 0, 0, 0, 0],
               "msg": [n if k == mi else 0 for k in range(len(msgs))],
               "head": [len(self._title(self.cur)) if (k == hi and self.cur is not None) else -1 for k in range(len(heads))],
               "vp": [[n * 100, 600, 0] if (k == 1 and not self.v3) else 0 for k in range(7)],
               "sel": {"n": len(win), "ast": 1 if marks else 0, "asa": page if marks else 0, "ac": 0, "ds": 0, "cls": 0},
               "conv": "nav" if self.f.get("conv") else "",
               "tids": (["chat-message-list:1", f"message-body:{n}", "chat-header:1"] if self.v2
                        else ([f"msg-renderer:{n}", "app-bar:1"] if self.v3 else [f"chat-pane-item:{n}", "message-author-name:3"])),
               "tids2": ([f"msg-renderer:{n}", "conversation-header-x:1", "compose-box:1"] if self.v3
                         else ["chat-message-list:1", f"message-body:{n}"]),
               "gen": n if self.v3 else 0, "times": n, "tall": n + (page if self.v3 else 0), "doc": self._doc(),
               "vis": "visible", "foc": 1, "ifr": [0, 0, 0], "sh": 0,
               "skel": {"item": ["0 div r=treeitem label#31 ti=-1 +2", "1 div +3", "2 span ~#3", "2 span ~#18",
                                 '2 span ~"오후 3:12"'],
                        "head": ["0 div#chat-header- +2", "1 h2 ~#5"],
                        "msg": ["0 div r=listitem +3", "1 div#author- ~#3", '1 time datetime#20 ~"오전 9:05"',
                                "1 div#content- ~#24"],
                        "hdr": ["0 div r=treeitem expanded=true level=1 +2", "1 div +1", "1 div r=group +3"] if self.v3 else []},
               "mi": mi}
        return out

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
        if name == "tw_aim":
            return self._aim(js)
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
