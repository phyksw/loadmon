# -*- coding: utf-8 -*-
r"""tests\fakes\fake_browser.py — Outlook 웹 화면 흉내(LM28 WP2 · WP3 이 이어 쓴다). 실제 Edge·네트워크를 쓰지 않는다.

Get-OutlookWeb 의 수집 루프(collect_mail·collect_cal)가 부르는 것만 흉내 낸다:
  br.goto(url) · br.search(query) · br.eval_json(JS) · br.cdp.eval(JS) · br.cdp.call(method, params) · br.href() · br.start() ·
  br.close(keep_tab)
JS 는 머리 표식(/*LM28:이름*/ — owa_list·owa_scroll·owa_more·owa_cal·owa_cal_prev·owa_open·owa_head)으로 알아보고 각본 응답을
돌려준다. JS 를 실행하지는 않는다 — 그 화면에서 운영 JS 가 '무엇을 보고했을지'를 낸다(운영 JS 를 바꿔도 표식이 같으면 따라온다).
기존 LM_OWA_FAKE(달별 항목 주입)는 회귀용으로 따로 남아 있다.

메일 목록 화면(LM28 현장 2026-10-08 이후 — 화면의 첫 listbox 가 메일 목록이 아니고, 메일 목록은 가상 목록이었다):
  · 후보 칸(owa_list PICK=-1 → cands) = 짧은 가짜 칸 decoys 개(listbox · 메일 행 아님 · 늘 '다 들어감') + 메일 목록 칸(맨 뒤).
    PICK=i 로 그 칸의 행을 읽고(owa_list)·내린다(owa_scroll — {r: scrolled|bottom|no-move|no-scroller|no-list|top, busy, …}).
  · 메일 목록은 가상 목록 — DOM 에는 page 개 창만 있고 내리면 step 개씩 움직인다(바닥에서 멈춤). 휠(CDP Input.dispatchMouseEvent
    mouseWheel)도 한 번 내린다.

각본(flags):
  ignore_search  — 검색을 무시한다(F-03: 검색 뒤에도 폴더 목록이 최신부터 그대로)
  syntax         — 알아듣는 검색 표기 집합('aqs'·'kql'·'iso' — 기본 전부). 모르는 표기는 낱말 검색이 되어 '결과 없음'
  ignore_url     — 일정 주 주소를 무시하고 늘 오늘이 든 주를 보인다(F-05)
  date_style     — 목록 날짜 표기 'owa'(오늘=시각만 · 6일 안=요일+시각 · 그 밖=연-월-일, 기본) · 'full'(늘 연-월-일 시각)
  empty_marker   — 목록이 비면 '결과 없음/비어 있음' 표식(기본 True)
  page · step    — 한 화면에 그려지는 항목 수(기본 20) · 한 번 스크롤에 내려가는 수(기본 10)
  decoys         — 메일 목록 앞의 짧은 다른 listbox 수(기본 0 — 현장은 4개 중 메일 목록이 첫째가 아니었다)
  no_mail_list   — 메일 목록 칸이 없다(짧은 칸만) · no_convid — 행에 data-convid 가 없다(날짜 조각으로만 메일 행)
  reach          — 검색하지 않은 폴더 목록은 이 개수까지만 불러온다(끝까지 못 내리는 화면 — '1월까지 못 감'). 바닥에
                   '불러오는 중' 표시가 남는다(reach_quiet 면 표시도 없이 조용히 멈춘다)
  lazy_batch     — 가상 목록이 이 개수씩 불러온다(바닥에 닿으면 '불러오는 중' 한 번 뒤 다음 묶음이 붙는다)
  more_page      — 검색 결과를 이 개수씩 보이고 바닥의 '더 보기' 단추로 다음 묶음(owa_more)
  wheel_only     — scrollTop 대입이 안 먹는다(no-move) — 실제 휠 입력만 내린다
  start_pos      — 폴더 목록이 맨 위가 아닌 데(이 항목 위치)서 열린다
  no_scroller    — 스크롤 영역을 못 찾는다 · no_search_box — 검색창이 없다
  stuck_clicks   — '이전 주' n번째 클릭(1부터)은 먹지 않는다(머리 그대로) · prev_dead — '이전 주'가 늘 안 먹는다
  no_prev        — '이전 주' 단추가 없다
  bad_header     — 이 주(시작 date)들은 머리 글이 2주 뒤 주를 말한다(머리·바탕 불일치)
  week_start     — 주 보기 첫 요일(0=월 기본 · 6=일)
  calid          — 일정 막대에 data-calitemid 가 있다(cal:1) · nodate — 막대 이름에 날짜 없이 요일만 · undated_calitem —
                   data-calitemid 막대인데 날짜도 요일도 없다(못 읽음)
  pivot          — 받은 편지함에 '중요' 탭이 선택돼 있다 · login — 어느 주소든 로그인 화면
"""
import re
from collections import Counter
from datetime import date, datetime, timedelta
from urllib.parse import urlparse

KWD = "월화수목금토일"
FOLDER_NAME = {"inbox": "받은 편지함", "sent": "보낸 편지함"}
ROWH = 60                                      # 행 높이(px) — 스크롤 수치 흉내


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


def query_dates(q):
    """검색 글 → (표기 'aqs'|'kql'|'iso'|'', [날짜…]) — 운영 Get-OutlookWeb.SEARCH_FORMS 의 세 꼴."""
    iso = re.findall(r"\d{4}-\d{2}-\d{2}", q or "")
    if iso:
        return ("kql" if ">=" in q else "iso"), [date.fromisoformat(x) for x in iso]
    us = re.findall(r"(\d{2})/(\d{2})/(\d{4})", q or "")
    if us:
        return "aqs", [date(int(y), int(m), int(d)) for m, d, y in us]
    return "", []


class _Cdp:
    def __init__(self, br):
        self.br = br

    def eval(self, js, timeout=25):
        return self.br._eval(js)

    def call(self, method, params=None, timeout=25):
        self.br.calls["cdp:" + method] += 1
        if method == "Input.dispatchMouseEvent" and (params or {}).get("type") == "mouseWheel":
            self.br._wheel(params or {})
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
        self.mail_shown, self.mail_loaded = 0, 0
        self.queries = []
        self.reason, self.closed = "", None

    # ── Browser 흉내 ──
    def start(self):
        self.calls["start"] += 1
        return not self.f.get("start_fail")

    def href(self):
        return self.url

    def close(self, keep_tab=False):
        self.closed = "kept" if keep_tab else "closed"

    def _reset_list(self):
        self.pos = 0
        self.mail_shown = int(self.f.get("more_page") or 0)
        self.mail_loaded = int(self.f.get("lazy_batch") or 0)

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
        self.lst, self.searched = list(self.mail.get(self.folder, [])), False
        self._reset_list()
        self.pos = int(self.f.get("start_pos") or 0)
        return "ok"

    def search(self, query):
        self.calls["search"] += 1
        self.queries.append(query)
        if self.f.get("no_search_box"):
            return False
        self._reset_list()
        if self.f.get("ignore_search"):
            return True                       # 입력은 됐지만 화면은 폴더 목록 그대로(F-03)
        kind, ds = query_dates(query)
        ok_kinds = self.f.get("syntax")
        if ok_kinds is not None and kind not in set(ok_kinds):
            self.lst, self.searched = [], True    # 모르는 표기 — 낱말 검색이 되어 '결과 없음'
            return True
        if len(ds) == 2:
            self.lst = [m for m in self.mail.get(self.folder, []) if ds[0] <= m["when"].date() <= ds[1]]
            self.searched = True
        return True

    def eval_json(self, js, timeout=40):
        r = self._eval(js)
        return r if isinstance(r, dict) else {}

    # ── 메일 목록 화면 ──
    @staticmethod
    def _arg(js, name, d):
        m = re.search(r"\b" + name + r' = ("?)(-?[\w]+)\1', str(js or ""))
        if not m:
            return d
        v = m.group(2)
        return int(v) if re.fullmatch(r"-?\d+", v) else v

    def _wstart(self, d):
        return d - timedelta(days=(d.weekday() - self.f["week_start"]) % 7)

    def _full(self):
        """불러올 수 있는 목록 — 검색 안 한 폴더 목록은 reach 개까지 · 검색 결과는 '더 보기'로 more_page 개씩."""
        lst = self.lst
        if not self.searched and self.f.get("reach"):
            lst = lst[:int(self.f["reach"])]
        if self.searched and self.f.get("more_page"):
            lst = lst[:self.mail_shown]
        return lst

    def _visible(self):
        """지금 DOM 에 '불러온' 목록(지연 로드는 lazy_batch 개씩)."""
        lst = self._full()
        if self.f.get("lazy_batch"):
            lst = lst[:self.mail_loaded]
        return lst

    def _load_more(self):
        """바닥에서 다음 묶음 불러오기(지연 로드) → 불러왔으면 True(그 화면은 '불러오는 중')."""
        if self.f.get("lazy_batch") and len(self._full()) > self.mail_loaded:
            self.mail_loaded += int(self.f["lazy_batch"])
            return True
        return False

    def _stuck_loading(self):
        """더 못 불러오는데 '불러오는 중' 표시가 남는 화면(reach — reach_quiet 면 표시 없이 조용히 멈춘다)."""
        return bool(self.f.get("reach") and not self.searched and not self.f.get("reach_quiet")
                    and len(self.lst) > int(self.f["reach"]))

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
        return {"idx": idx, "cv": 0 if self.f.get("no_convid") else 1, "key": f"{m['id']}|{m['sender']}",
                "label": f"{m['sender']}, {m['subject']}, {dl}", "titles": list(m.get("titles") or []),
                "texts": [m["sender"], m["subject"], dl], "dts": list(m.get("dts") or [])}

    def _n_dec(self):
        return int(self.f.get("decoys") or 0)

    def _mail_facts(self, win, n_vis):
        n = len(win)
        conv = 0 if self.f.get("no_convid") else n
        return {"i": self._n_dec(), "role": "listbox", "opts": n, "mailish": n, "conv": conv, "main": 1, "vis": 1, "al": 9,
                "how": "" if self.f.get("no_scroller") else "anc", "d": 3, "where": "in", "sh": n_vis * ROWH,
                "ch": int(self.f["page"]) * ROWH, "st": self.pos * ROWH, "busy": 0}

    def _decoy_facts(self, i):
        return {"i": i, "role": "listbox", "opts": 2, "mailish": 0, "conv": 0, "main": 0, "vis": 1, "al": 6,
                "how": "anc0", "d": 1, "where": "out", "sh": 2 * ROWH, "ch": 2 * ROWH, "st": 0, "busy": 0}

    def _mail_list(self, js):
        self.calls["list"] += 1
        pick, skel = self._arg(js, "PICK", -1), self._arg(js, "SKEL", 0)
        vis = self._visible()
        page, n_dec = int(self.f["page"]), self._n_dec()
        has_mail = not self.f.get("no_mail_list")
        piv = ["중요"] if (self.f.get("pivot") and self.folder == "inbox") else []
        out = {"href": self.url, "n": 0, "items": [], "cands": [], "lst": None, "lb": n_dec + (1 if has_mail else 0),
               "search": not self.f.get("no_search_box"), "empty": False, "sel": FOLDER_NAME[self.folder], "pivots": piv,
               "sec": ["MessageList"] if has_mail else []}
        if pick < 0:
            cands = [{k: v for k, v in self._decoy_facts(i).items() if k in ("i", "role", "opts", "mailish", "conv", "main",
                                                                              "vis", "al")} for i in range(n_dec)]
            if has_mail:
                win = vis[self.pos:self.pos + page]
                f = self._mail_facts(win, len(vis))
                cands.append({k: f[k] for k in ("i", "role", "opts", "mailish", "conv", "main", "vis", "al")})
            out["cands"] = cands
            out["empty"] = bool(not vis and self.f["empty_marker"])
            return out
        if pick < n_dec:                      # 짧은 다른 칸('중요'·'기타' 같은 글 — 메일 행 아님)
            self.window = []
            out.update(n=2, lst=self._decoy_facts(pick),
                       items=[{"idx": k, "cv": 0, "key": f"dec{pick}-{k}", "label": "", "titles": [], "texts": [w], "dts": []}
                              for k, w in enumerate(("중요", "기타"))])
            return out
        if pick != n_dec or not has_mail:
            return out                        # 그런 칸 없음 — lst None
        self.window = vis[self.pos:self.pos + page]
        items = [self._render(m, i) for i, m in enumerate(self.window)]
        out.update(n=len(items), items=items, lst=self._mail_facts(self.window, len(vis)),
                   empty=bool(not items and self.f["empty_marker"]))
        if skel and self.window:
            m = self.window[0]
            out["skel"] = {"t": "div", "r": "option", "al": len(items[0]["label"]), "cv": 1, "c": [
                {"t": "div", "c": [{"t": "span", "x": m["sender"]}, {"t": "span", "x": m["subject"]}]},
                {"t": "span", "x": self._label_date(m["when"])}]}
        return out

    def _mail_scroll(self, js):
        self.calls["scroll"] += 1
        pick, mode = self._arg(js, "PICK", -1), self._arg(js, "MODE", "down")
        n_dec = self._n_dec()
        if 0 <= pick < n_dec:                 # 짧은 칸은 늘 '다 들어감'(넘치지 않는다) — 예전 JS 의 'fits'
            return {"r": "bottom", "how": "anc0", "d": 1, "sh": 2 * ROWH, "ch": 2 * ROWH, "st": 0, "busy": 0, "x": 90, "y": 90}
        if pick != n_dec or self.f.get("no_mail_list"):
            return {"r": "no-list"}
        vis = self._visible()
        if not vis:
            return {"r": "no-list"}
        if self.f.get("no_scroller"):
            return {"r": "no-scroller", "n": len(vis)}
        page, step = int(self.f["page"]), int(self.f["step"])
        o = {"r": "", "how": "anc", "d": 3, "sh": len(vis) * ROWH, "ch": page * ROWH, "st": self.pos * ROWH, "busy": 0,
             "x": 400, "y": 300}
        if mode == "top":
            self.pos = 0
            o.update(r="top", st=0)
            return o
        if self.pos + page >= len(vis):       # 바닥
            o["r"] = "bottom"
            if self._load_more() or self._stuck_loading():
                o["busy"] = 1                 # 불러오는 중(지연 로드 — 다음 화면에 행이 붙는다 · reach — 끝내 안 붙는다)
            return o
        if self.f.get("wheel_only"):
            o["r"] = "no-move"
            return o
        self.pos = min(self.pos + step, max(0, len(vis) - page))
        o.update(r="scrolled", st=self.pos * ROWH)
        return o

    def _wheel(self, params):
        """실제 휠 입력 — 메일 목록을 한 번 내린다(바닥이면 다음 묶음 불러오기)."""
        self.calls["wheel"] += 1
        if self.view != "mail" or float(params.get("deltaY") or 0) <= 0:
            return
        vis = self._visible()
        page, step = int(self.f["page"]), int(self.f["step"])
        if self.pos + page >= len(vis):
            self._load_more()
        else:
            self.pos = min(self.pos + step, max(0, len(vis) - page))

    def _mail_more(self, js):
        """목록 바닥의 결과 '더 보기' 단추(검색 결과 more_page 개씩)."""
        if self.f.get("more_page") and self.searched and self.mail_shown < len(self.lst) \
                and self.pos + int(self.f["page"]) >= len(self._visible()):
            self.calls["more"] += 1
            self.mail_shown += int(self.f["more_page"])
            return "clicked"
        return "none"

    # ── 일정 화면 ──
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
        cal = 1 if (self.f.get("calid") or self.f.get("undated_calitem")) else 0
        evs = []
        for ev in self.events:
            if ev["start"].date() <= we and ev["end"].date() >= ws:
                d = ev["start"]
                if self.f.get("undated_calitem"):
                    label = f"{ev['subject']}, {ampm(d)} ~ {ampm(ev['end'])}, 바쁨"
                elif self.f.get("nodate"):
                    label = f"{ev['subject']}, {KWD[d.weekday()]}요일 {ampm(d)} ~ {ampm(ev['end'])}, 바쁨"
                else:
                    label = (f"{ev['subject']}, {d.year}년 {d.month}월 {d.day}일 {KWD[d.weekday()]}요일 "
                             f"{ampm(d)} ~ {ampm(ev['end'])}, 바쁨")
                evs.append({"label": label, "cal": cal, "texts": [ev["subject"]]})
        return {"href": self.url, "grid": True, "n": len(evs), "events": evs, "heads": [self._header(ws), "오늘"],
                "cols": [], "nc": len(evs) if cal else 0, "nb": len(evs) + 6, "nt": 0 if cal else len(evs)}

    def _prev(self):
        self.calls["prev"] += 1
        if self.f.get("no_prev"):
            return "none"
        self.clicks += 1
        if not self.f.get("prev_dead") and self.clicks not in set(self.f.get("stuck_clicks") or ()):
            self.week -= timedelta(days=7)
        return "ok"

    def _eval(self, js):
        m = re.match(r"\s*/\*LM28:(\w+)\*/", str(js or ""))
        name = m.group(1) if m else ""
        if name == "owa_list":
            return self._mail_list(js)
        if name == "owa_scroll":
            return self._mail_scroll(js)
        if name == "owa_more":
            return self._mail_more(js)
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
