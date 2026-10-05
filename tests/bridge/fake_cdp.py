# -*- coding: utf-8 -*-
r"""가짜 CDP(B §11.3) — JS 를 실행하지 않고 조각 머리 표식 ``/*LM27:<이름>*/`` 로 처리기를 골라 페이지 모형 상태를 돌려준다.

    clk = VirtualClock()
    page = FakePage(clk)                              # Copilot 채팅 화면 모형(로그인됨·입력창 있음)
    page.replies.append(FakeReply(text=answer_fn))    # 전송마다 하나씩 꺼낸다
    cdp = FakeTabCDP(page)                            # EdgeSession 의 연결 자리에 끼운다(fake_http.FakeNet 이 만든다)

답 생성 모형(시제품 proto_l1 일반화): 전송 순간부터 ``think_s`` 동안 생각 → 초당 ``cps`` 글자로 쓰기 →
``pauses``((글자 위치, 멈춤 초, 멈춤 중 중지 버튼 보임), …) → 끝. ``button=False`` 면 생성 중 중지 버튼이 선택자에
잡히지 않는다(gen=False). ``cut_at`` 이면 그 위치에서 끊고 '생성 중단' 문구를 덧붙인다. 모든 시각은 주입된 시계 기준.
받은 프롬프트는 ``sent_texts``(메모리)에만 남는다 — 카나리아 검사용.
"""
from __future__ import annotations

import json
import re
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field

from lm27.bridge import js
from lm27.bridge.cdp import ALLOWED_METHODS, CdpError

CHAT_URL = "https://m365.cloud.microsoft/chat"
LOGIN_URL = "https://login.microsoftonline.com/common/oauth2/authorize"
CUT_TAIL = "\nOK, I've stopped generating the response."
GREETING = "무엇을 도와드릴까요?"
ASST_SELECTOR = "[data-testid='copilot-message-reply']"
_RID_RX = re.compile(r"(?:\[LM27 요청 |\[\[END )(R[2-9A-HJ-NP-TV-Z]{5})")


@dataclass
class FakeReply:
    text: str | Callable[[str, str], str] = ""     # (프롬프트, rid) → 답 원문, 또는 '{rid}' 자리가 있는 문자열
    think_s: float = 5
    cps: float = 60
    pauses: tuple = ()                             # ((글자 위치, 멈춤 초, 멈춤 중 중지 버튼 보임), …)
    button: bool = True
    cut_at: int | None = None
    error: str = ""


def rid_of(prompt: str) -> str:
    m = _RID_RX.search(prompt or "")
    return m.group(1) if m else ""


def progress(r: FakeReply, full: str, t: float) -> tuple[int, object]:
    """전송 뒤 t 초의 (쓴 글자 수, 상태). 상태: 'think' | 'write' | ('pause', 버튼) | 'done'."""
    tw = t - r.think_s
    if tw <= 0:
        return 0, "think"
    pos, rem = 0.0, tw
    for at, dur, btn in sorted(r.pauses):
        if at > len(full):
            break
        need = (at - pos) / r.cps
        if rem <= need:
            return int(pos + rem * r.cps), "write"
        rem -= need
        pos = float(at)
        if rem <= dur:
            return int(pos), ("pause", btn)
        rem -= dur
    p = pos + rem * r.cps
    if p >= len(full):
        return len(full), "done"
    return int(p), "write"


@dataclass
class _Msg:
    role: str                    # user | asst
    text: str = ""
    reply: FakeReply | None = None
    full: str = ""
    t0: float = 0.0


@dataclass
class FakePage:
    clock: object
    url: str = CHAT_URL
    ready: str = "complete"
    login_until_s: float | None = None
    input_appear_s: float = 0
    input_limit: int = 9000
    input_aria: str = "Copilot에 메시지 보내기"
    swallow_sends: int = 0
    assistant_dom: bool = True
    user_dom: bool = True
    send_button: bool = True
    new_chat_button: bool = True
    insert_text_works: bool = True
    work_mode: str = "work"
    work_toggle: bool = True
    work_switch_ok: bool = True
    web_grounding: str | None = None
    model_menu: tuple = ("자동", "빠른 응답", "깊이 생각하기")
    model_current: str = "자동"
    replies: deque = field(default_factory=deque)
    sent_texts: list = field(default_factory=list)
    clicks: list = field(default_factory=list)
    evals: list = field(default_factory=list)
    calls: list = field(default_factory=list)
    editor_filter: Callable | None = None          # 편집기에 들어간 글을 바꾼다(주입 불일치 흉내)
    editor: str = ""
    focused: bool = False
    menu_open: bool = False
    conv: list = field(default_factory=list)
    greeting: bool = True
    alive: bool = True

    # ── 상태 계산 ───────────────────────────────────────────────────────
    def now(self) -> float:
        return self.clock.mono()

    def current_url(self) -> str:
        if self.login_until_s is not None and self.now() < self.login_until_s and self.url.startswith(CHAT_URL):
            return LOGIN_URL
        return self.url

    def on_chat(self) -> bool:
        return self.current_url().startswith(CHAT_URL)

    def input_present(self) -> bool:
        return self.on_chat() and self.now() >= self.input_appear_s

    def _asst_state(self, m: _Msg) -> tuple[str, bool]:
        """(지금까지 보이는 글, 생성 중 버튼 보임)."""
        pos, st = progress(m.reply, m.full, self.now() - m.t0)
        txt = m.full[:pos]
        if st == "think":
            gen = m.reply.button
        elif st == "done":
            gen = False
        elif isinstance(st, tuple):
            gen = m.reply.button and bool(st[1])
        else:
            gen = m.reply.button
        return txt, gen

    def last_asst(self) -> _Msg | None:
        return next((m for m in reversed(self.conv) if m.role == "asst"), None)

    def generating(self) -> bool:
        m = self.last_asst()
        return bool(m and self._asst_state(m)[1])

    def n_user(self) -> int:
        return sum(1 for m in self.conv if m.role == "user") if self.user_dom else 0

    def n_asst(self) -> int:
        return sum(1 for m in self.conv if m.role == "asst")

    def chat_text(self) -> str:
        parts = [GREETING] if self.greeting else []
        for m in self.conv:
            parts.append(m.text if m.role == "user" else self._asst_state(m)[0])
        return "\n".join(parts)

    # ── 동작 ───────────────────────────────────────────────────────────
    def do_send(self) -> None:
        text = self.editor
        if not text.strip():
            return
        self.editor = ""
        self.sent_texts.append(text)
        self.greeting = False
        self.conv.append(_Msg("user", text=text))
        r = self.replies.popleft() if self.replies else FakeReply(text="")
        rid = rid_of(text)
        if r.error:
            full = r.error
        elif callable(r.text):
            full = r.text(text, rid)
        else:
            full = str(r.text).replace("{rid}", rid)
        if r.cut_at is not None:
            full = full[:r.cut_at] + CUT_TAIL
        self.conv.append(_Msg("asst", reply=r, full=full, t0=self.now()))

    def reset_chat(self) -> None:
        self.conv = []
        self.greeting = True
        self.editor = ""

    def navigate(self, url: str) -> None:
        self.url = url
        self.reset_chat()
        self.focused = False

    # ── JS 처리기 ──────────────────────────────────────────────────────
    def evaluate(self, expr: str):
        name = js.marker(expr)
        self.evals.append(name)
        fn = getattr(self, "js_" + name, None)
        if fn is None:
            raise CdpError(f"JS: fake 처리기 없음 {name}")
        return fn(expr)

    def js_identity(self, expr):
        found = self.input_present()
        return {"url": self.current_url(), "ready": self.ready,
                "input": {"found": found, "aria": self.input_aria if found else "", "sel": "x" if found else ""}}

    def js_focus_input(self, expr):
        if not self.input_present():
            return {"ok": False, "err": "input_not_found"}
        self.focused = True
        return {"ok": True, "tag": "SPAN", "sel": "x", "aria_match": True, "composer": True}

    def js_editor_text(self, expr):
        return self.editor if self.focused else ""

    def js_clear_editor(self, expr):
        if not self.focused:
            return {"ok": False, "len": -1}
        self.editor = ""
        return {"ok": True, "len": 0}

    def js_insert_fallback(self, expr):
        i = expr.index("const p=") + len("const p=")
        p, _ = json.JSONDecoder().raw_decode(expr, i)
        if self.focused:
            self.editor = (self.editor + p)[:self.input_limit]
            if self.editor_filter is not None:
                self.editor = self.editor_filter(self.editor)
        return {"ok": self.focused}

    def js_click_send(self, expr):
        if not self.focused:
            return {"ok": False, "why": "no_composer"}
        if not self.send_button:
            return {"ok": False, "why": "no_button"}
        if self.swallow_sends > 0:
            self.swallow_sends -= 1
            self.clicks.append("send_swallowed")
            return {"ok": True}
        self.clicks.append("send")
        self.do_send()
        return {"ok": True}

    def js_generating(self, expr):
        if not self.focused:
            return None
        return self.generating()

    def _sels(self, expr) -> list:
        m = re.search(r"const sels=(\[.*?\]),srcs=", expr) or re.search(r"for\(const s of (\[.*?\])\)\{let ns", expr)
        return json.loads(m.group(1)) if m else []

    def js_poll(self, expr):
        sels = self._sels(expr)
        gen = self.generating() if self.focused else None
        na, last = -1, ""
        if sels and self.assistant_dom and self.n_asst() > 0:
            na = self.n_asst()
            last = self._asst_state(self.last_asst())[0]
        srcs = re.search(r"srcs=(\[.*?\]);", expr)
        sel = (json.loads(srcs.group(1)) or [""])[0] if (srcs and na >= 0) else ""
        return {"gen": gen, "n_user": self.n_user(), "n_asst": na, "last": last, "sel": sel}

    def js_counts(self, expr):
        sels = self._sels(expr)
        na = self.n_asst() if (sels and self.assistant_dom and self.n_asst() > 0) else -1
        return {"n_user": self.n_user(), "n_asst": na}

    def js_chat_text(self, expr):
        return self.chat_text()

    def js_learn_asst(self, expr):
        m = self.last_asst()
        i = expr.index("const pledge=") + len("const pledge=")
        pledge, _ = json.JSONDecoder().raw_decode(expr, i)
        if self.assistant_dom and m is not None and pledge in self._asst_state(m)[0]:
            return {"ok": True, "selector": ASST_SELECTOR}
        return {"ok": False}

    def js_new_chat(self, expr):
        if not self.new_chat_button or not self.on_chat():
            return {"ok": False}
        self.clicks.append("new_chat")
        self.reset_chat()
        return {"ok": True}

    def _norm(self, s):
        return re.sub(r"[-\s._]", "", str(s or "").lower())

    def js_pick_model(self, expr):
        want = json.JSONDecoder().raw_decode(expr, expr.index("const want=") + len("const want="))[0]
        if not self.model_menu:
            return {"ok": False, "err": "selector_not_found"}
        if self._norm(want) in self._norm(self.model_current):
            return {"ok": True, "already": True, "cur": self.model_current}
        if self.menu_open:
            return {"ok": True, "opened": True, "alreadyOpen": True}
        self.menu_open = True
        self.clicks.append("model_menu")
        return {"ok": True, "opened": True}

    def js_menu_open(self, expr):
        return {"open": len(self.model_menu) if self.menu_open else 0}

    def js_pick_model_item(self, expr):
        want = json.JSONDecoder().raw_decode(expr, expr.index("const want=") + len("const want="))[0]
        if not self.menu_open:
            return {"ok": False, "err": "item_not_found", "seen": []}
        for item in self.model_menu:
            if self._norm(want) in self._norm(item):
                self.model_current = item
                self.menu_open = False
                self.clicks.append("model_item")
                return {"ok": True, "picked": item}
        return {"ok": False, "err": "item_not_found", "seen": list(self.model_menu)}

    def js_close_menu(self, expr):
        self.menu_open = False
        return 1

    def _mode(self):
        if not self.work_toggle:
            return {"found": False, "mode": "unknown", "work": False, "web": False}
        return {"found": True, "mode": self.work_mode, "work": self.work_mode == "work", "web": self.work_mode == "web"}

    def js_work_mode(self, expr):
        if "if(true&&fw" in expr and self.work_toggle and self.work_mode != "work":
            self.clicks.append("work_toggle")
            if self.work_switch_ok:
                self.work_mode = "work"
        return {**self._mode(), "clicked": False}

    def js_env(self, expr):
        m = self._mode()
        wg = self.web_grounding
        return {"toggle": {"found": m["found"], "work": m["work"], "web": m["web"]},
                "wg": {"found": wg is not None, "checked": True if wg == "on" else (False if wg == "off" else None)}}

    def js_diagnose(self, expr):
        return {"url_host": "m365.cloud.microsoft", "url_path": "/chat/0123456789abcdef", "ready": self.ready,
                "editors": [], "composer_buttons": [], "stop_candidates": [],
                "message_candidates": [{"tag": "DIV", "text_mask": "가나다 abc 123"}], "model_menu": list(self.model_menu)}

    # ── CDP 메서드 ─────────────────────────────────────────────────────
    def cdp_call(self, method: str, params: dict):
        self.calls.append(method)
        if method == "Input.insertText":
            if self.focused and self.insert_text_works:
                self.editor = (self.editor + params.get("text", ""))[:self.input_limit]
                if self.editor_filter is not None:
                    self.editor = self.editor_filter(self.editor)
            return {}
        if method == "Input.dispatchKeyEvent":
            if params.get("type") == "rawKeyDown" and params.get("key") == "Enter" and self.focused:
                self.clicks.append("enter")
                self.do_send()
            return {}
        if method == "Page.navigate":
            self.navigate(params.get("url", ""))
            return {}
        if method == "Page.reload":
            self.focused = False
            return {}
        if method == "Page.bringToFront":
            return {}
        raise CdpError(f"CDP {method}: fake 미지원")


class FakeTabCDP:
    """탭 대상 가짜 CDP 연결(``lm27.bridge.cdp.CDP`` 와 같은 메서드)."""

    def __init__(self, page: FakePage, *, origin=None, timeout_on: set | None = None):
        self.page = page
        self.origin = origin
        self.broken = False
        self.closed = False
        self.reconnects = 0
        self.timeout_on = timeout_on or set()       # 이 JS 표식 이름에서 한 번 시간 초과를 낸다(재연결 시험)

    def call(self, method, params=None, timeout=25.0):
        if method not in ALLOWED_METHODS:
            raise ValueError(f"허용하지 않는 CDP 메서드 {method}")
        if method == "Runtime.evaluate":
            return {"result": {"type": "object", "value": self.eval((params or {}).get("expression", ""))}}
        return self.page.cdp_call(method, params or {})

    def eval(self, expr, timeout=25.0):
        if not self.page.alive:
            raise ConnectionError("fake: 탭이 닫혔습니다")
        name = js.marker(expr)
        if name in self.timeout_on:
            self.timeout_on.discard(name)
            self.broken = True
            from lm27.bridge.cdp import CdpTimeout
            raise CdpTimeout(f"fake timeout {name}")
        return self.page.evaluate(expr)

    def reconnect(self):
        self.reconnects += 1
        self.broken = False

    def close(self):
        self.closed = True


class FakeBrowserCDP:
    """브라우저 대상 가짜 CDP(``Browser.close`` 만)."""

    def __init__(self, browser):
        self.browser = browser
        self.closed = False

    def call(self, method, params=None, timeout=25.0):
        if method == "Browser.close":
            self.browser.close_by_cdp()
            return {}
        if method == "Browser.getVersion":
            return {"product": "Edg/129.0.2792.65"}
        raise CdpError(f"CDP {method}: fake 미지원")

    def eval(self, expr, timeout=25.0):
        raise CdpError("JS: 브라우저 대상")

    def reconnect(self):
        pass

    def close(self):
        self.closed = True


def envelope(rid: str, n: int, *, act: str = "request", pledge: bool = True, note: str = "") -> str:
    """speech_act 꼴 정상 봉투 답(코드 블록 + 서약) — 시험 재료."""
    extra = f',"note":"{note}"' if note else ""
    items = ",".join(f'{{"id":{i},"act":"{act}","conf":"h"{extra}}}' for i in range(1, n + 1))
    env = f'{{"rid":"{rid}","n":{n},"items":[{items}]}}'
    return "```json\n" + env + "\n```" + (f"\n[[END {rid}]]" if pledge else "")


def make_prompt(rid: str, n: int = 3, *, filler: int = 0) -> str:
    """B §6.2 골격을 흉내 낸 합성 프롬프트(개인정보 없음). 서약 지시는 마지막 줄 1번."""
    lines = [f"[LM27 요청 {rid} · 화행 분류 · 항목 {n}개]", "각 메시지의 화행을 고르세요.", "[항목] 번호 | 요지"]
    lines += [f"{i} | 회의 자료 검토 요청 {i:04d}" for i in range(1, n + 1)]
    if filler:
        row = "검증용 문장 가나다라마바사아자차카타파하 abcdefghij 0123"
        lines += [row] * (filler // (len(row) + 1) + 1)
    lines += ["[답 형식]", "- 아래 형식의 JSON 하나를 코드 블록 하나에 담아 답합니다.",
              '- 형식(<…> 자리에 실제 값): {"rid": <요청번호>, "n": <항목 수>, "items": [ {"id": <번호>, "act": <request|ack>} ]}',
              f"- 코드 블록이 끝나면 맨 마지막 줄에 [[END {rid}]] 만 씁니다."]
    return "\n".join(lines)
