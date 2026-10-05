# -*- coding: utf-8 -*-
r"""L1 전송(B §5) — 주입 검증·전송 확인·회수(DOM 1차, 앵커 폴백)·**fail-closed 완료 판정**.

    t = CdpTransport(sess)                    # sess = EdgeSession(L0)
    r = t.roundtrip(SendRequest(rid, text, fresh, model, reply_timeout_s, first_token_s, deadline, stage, want_work_mode))
    r.phase  → B §5.8 표(replied·no_reply·empty_reply·input_overflow·inject_mismatch·busy_before_send·send_failed·
               cdp_error·login_required·…)

완료 판정(B §5.6, 시제품 proto_l1 으로 확인한 규칙):
  ① 서약 ``[[END <rid>]]``(``<<END rid>>`` 도 인식) — 닫힘(서약이 없으면 완료 아님)
  ② idle_json — 이 전송에서 중지 버튼을 본 적이 있고, 지금 2폴 연속 사라졌고, 몸통이 그대로이며, 봉투가 엄격 파싱 + rid 일치
  ③ stable — 몸통이 N폴 연속 같고 그 동안 gen 이 True 인 적이 없음(봉투가 시작됐는데 파싱이 안 되면 N × incompleteJsonFactor)
  중지 버튼(gen)은 **fail-open** 이라 단독으로 완료를 정하지 않는다. 괄호 개수 근사(LM24 ``_looks_closed``)는 폐기.

프롬프트·답 원문은 메모리에만 있다(디스크에 쓰지 않는다 — B9).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Protocol

from lm27.bridge import cdp as C
from lm27.bridge import js
from lm27.bridge import settings as S
from lm27.bridge.clock import Deadline, iso_now
from lm27.bridge.session import PhaseError

RID_RX = re.compile(r"^R[2-9A-HJ-NP-TV-Z]{5}$")
ANY_PLEDGE_RX = re.compile(r"(?:\[\[|<<)\s*END\s+R[2-9A-HJ-NP-TV-Z]{5}\s*(?:\]\]|>>)")
_ENV_START_RX = re.compile(r'\{\s*"rid"\s*:')
_NBSP = " "
_ZW = ("​", "‌", "‍", "﻿")


def pledge_rx(rid: str) -> re.Pattern:
    """이번 rid 의 서약 정규식(``[[END rid]]`` · ``<<END rid>>``)."""
    return re.compile(r"(?:\[\[|<<)\s*END\s+" + re.escape(rid) + r"\s*(?:\]\]|>>)")


# ───────────────────────── 자료구조(B §5.1) ─────────────────────────
@dataclass(frozen=True)
class SendRequest:
    rid: str
    text: str                  # 게이트 통과 프롬프트(원문 저장 금지 — 메모리에만)
    fresh: bool                # 보내기 전에 새 채팅
    model: str                 # "" = 건드리지 않음
    reply_timeout_s: float
    first_token_s: float
    deadline: float            # clock.mono() 기준 절대 마감(질의 예산과 단계 예산의 작은 값)
    stage: str
    want_work_mode: bool
    item_keys: tuple = ()      # 스텁 전용 — 항목 번호 1..n 의 key(가짜 답 고르기). CDP 전송은 쓰지 않는다


@dataclass
class SendResult:
    phase: str                 # B §5.8 표
    body: str = ""             # 회수한 답(에코 제거). 실패여도 있는 만큼(복구 재료)
    done_by: str = ""          # "pledge" | "idle_json" | "stable" | ""
    pick: str = ""             # "dom" | "anchor" | "offset" | "fulltext" | "stub" | "manual"
    busy_seen: bool | None = None
    gen_sec: float = 0.0       # 전송 확인 ~ 완료
    first_token_sec: float | None = None
    in_chars: int = 0          # 보내려던 글자 수(정규화 후)
    injected_chars: int = 0    # 편집기에서 확인한 글자 수(정규화 후)
    resent: bool = False
    waited_idle_sec: float = 0.0
    model_note: str = ""
    model_used: str = ""
    work_mode: str = "unknown"
    chat_seq: int = 0
    error: str = ""            # 짧은 코드·예외 이름(페이지 원문 금지, 120자)


class Transport(Protocol):
    kind: str                                  # "cdp" | "stub" | "manual"

    def open(self) -> str: ...                 # "ready" 또는 L1 단계 문자열

    def roundtrip(self, req: SendRequest) -> SendResult: ...

    def new_chat(self) -> bool: ...

    def close(self) -> None: ...


# ───────────────────────── 순수 도구 ─────────────────────────
def norm(s: str) -> str:
    """비교용 정규화(저장하지 않음): CRLF → LF, NBSP·폭 없는 공백 제거, 공백 뭉치 → 1칸, 앞뒤 공백 제거."""
    s = str(s or "").replace("\r\n", "\n").replace(_NBSP, " ")
    for z in _ZW:
        s = s.replace(z, "")
    return re.sub(r"\s+", " ", s).strip()


def match(got: str, want: str) -> bool:
    """주입 검증: 길이 차 ≤ 2 이고 꼬리 32자가 같다(B §5.3 — LM24 의 앞 15자 확인은 폐기)."""
    return abs(len(got) - len(want)) <= S.MATCH_LEN_TOL and got[-S.MATCH_TAIL:] == want[-S.MATCH_TAIL:]


def envelope_state(body: str, rid: str) -> tuple[bool, bool]:
    """(봉투가 시작됐는가 ``{"rid"``, 엄격 JSON 파싱 + rid 일치인가)."""
    dec = json.JSONDecoder()
    started = False
    for m in _ENV_START_RX.finditer(body or ""):
        started = True
        try:
            obj, _end = dec.raw_decode(body, m.start())
        except ValueError:
            continue
        if isinstance(obj, dict) and str(obj.get("rid", "")).strip().upper() == rid:
            return True, True
    return started, False


def build_anchor(prompt: str) -> str:
    """에코 앵커 — 프롬프트 마지막 8줄 중 가장 긴 줄의 끝 100자(한 줄, LM24 ``build_anchor``)."""
    cands = [ln.strip() for ln in str(prompt or "").strip().splitlines() if ln.strip()][-S.ANCHOR_LINES:]
    if not cands:
        return ""
    best = max(cands, key=len)
    return best[-S.ANCHOR_MAX:] if len(best) >= S.ANCHOR_MIN else ""


def pick_reply(txt: str, base: int, anchor: str) -> tuple[str, str]:
    """페이지 전체 글에서 이번 답만 — ① 앵커 뒤 ② 오프셋 뒤 ③ 전문(LM24 ``pick_reply``)."""
    if anchor:
        pos = txt.rfind(anchor)
        if pos >= 0 and pos >= base - S.ANCHOR_SLACK:
            return txt[pos + len(anchor):], "anchor"
    if base and base <= len(txt):
        return txt[base:], "offset"
    return txt, "fulltext"


def strip_echo(reply: str, prompt: str, anchor: str, how: str) -> str:
    """답 앞에 붙은 프롬프트 에코를 걷어낸다(공백 무시 접두 일치일 때만, LM24 ``strip_echo``)."""
    reply, prompt = str(reply or ""), str(prompt or "")
    if how == "fulltext" or not prompt:
        return reply
    echo = prompt
    if how == "anchor" and anchor:
        pos = prompt.rfind(anchor)
        if pos < 0:
            return reply
        echo = prompt[pos + len(anchor):]
    want = re.sub(r"\s+", "", echo)
    if not want:
        return reply
    i = j = 0
    n = len(reply)
    while i < n and j < len(want):
        c = reply[i]
        if c.isspace():
            i += 1
            continue
        if c != want[j]:
            return reply
        i += 1
        j += 1
    return reply[i:] if j == len(want) else reply


def echo_pledges(prompt: str, anchor: str, how: str, rid: str) -> int:
    """폴백 회수 조각에 섞이는 프롬프트 에코 몫의 이번 rid 서약 수(LM24 ``echo_sentinels`` 일반화)."""
    rx = pledge_rx(rid)
    prompt = str(prompt or "")
    if how == "anchor" and anchor:
        pos = prompt.rfind(anchor)
        if pos >= 0:
            return len(rx.findall(prompt[pos + len(anchor):]))
    return len(rx.findall(prompt))


@dataclass
class _Base:
    n_user: int = 0
    n_asst: int = -1
    page_len: int = 0
    measured: bool = False


@dataclass
class _Inj:
    phase: str
    want: int = 0
    got: int = 0


@dataclass
class _Snap:
    gen: bool | None = None
    n_user: int = 0
    n_asst: int = -1
    last: str = ""
    sel: str = ""
    extra: dict = field(default_factory=dict)


# ───────────────────────── CdpTransport ─────────────────────────
class CdpTransport:
    """L1 CDP 전송. 의존: ``EdgeSession``(L0). 모든 대기는 주입된 시계(``session.clock``)와 ``Deadline`` 으로 자른다."""

    kind = "cdp"

    def __init__(self, session):
        self.s = session
        self.cfg = session.cfg
        self.clock = session.clock
        self._learned = ""
        self._learned_src = ""

    # ── 수명 ───────────────────────────────────────────────────────────
    def open(self) -> str:
        return self.s.start()

    def close(self) -> None:
        self.s.close()

    # ── 공용 조각 ──────────────────────────────────────────────────────
    def _ev(self, expr, timeout=S.CDP_CALL_TIMEOUT_S):
        return self.s.eval(expr, timeout=timeout)

    def _sleep(self, sec: float) -> None:
        if sec > 0:
            self.clock.sleep(sec)
        self.s.tick()

    def _editor(self) -> str:
        try:
            return norm(self._ev(js.editor_text()) or "")
        except C.CdpError:
            return ""

    def clear_editor(self) -> int:
        try:
            r = self._ev(js.clear_editor()) or {}
        except C.CdpError:
            return -1
        return int(r.get("len", -1)) if isinstance(r, dict) else -1

    def _counts(self) -> tuple[int, int]:
        try:
            r = self._ev(js.counts(self.cfg.dom.assistant_selectors, self._learned)) or {}
        except C.CdpError:
            return 0, -1
        return int(r.get("n_user") or 0), int(r.get("n_asst", -1))

    def generating(self) -> bool | None:
        try:
            g = self._ev(js.generating(self.cfg.dom.stop_labels))
        except (C.CdpError, OSError, PhaseError):
            return None
        return g if isinstance(g, bool) else None

    def press_enter(self) -> None:
        """Enter 키(LM24 유지): rawKeyDown / char / keyUp."""
        for t, key in (("rawKeyDown", None), ("char", "\r"), ("keyUp", None)):
            params = {"type": t, "key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13,
                      "nativeVirtualKeyCode": 13}
            if key:
                params["text"] = key
            self.s.call("Input.dispatchKeyEvent", params)

    def wait_idle(self, secs: float) -> tuple[float, bool]:
        """앞 답 생성이 끝나기를 최대 secs 초(LM24 ``wait_idle``). 반환: (기다린 초, 아직 생성 중인가)."""
        t0 = self.clock.mono()
        while True:
            if self.generating() is not True:
                return round(self.clock.mono() - t0, 1), False
            if self.clock.mono() - t0 >= secs:
                return round(self.clock.mono() - t0, 1), True
            self._sleep(min(S.WAIT_IDLE_POLL_S, max(0.1, secs - (self.clock.mono() - t0))))

    # ── 새 채팅(B §5.7) ────────────────────────────────────────────────
    def new_chat(self) -> bool:
        """새 채팅 버튼 → 사용자 메시지 수 0 확인. 안 되면 같은 탭에서 채팅 URL 재진입. chat_seq += 1."""
        self.s.activate()
        ok = False
        try:
            r = self._ev(js.new_chat(self.cfg.dom.new_chat_labels)) or {}
            if isinstance(r, dict) and r.get("ok"):
                dl = Deadline.after(self.clock, S.NEW_CHAT_WAIT_S)
                while not dl.expired():
                    self._sleep(S.NEW_CHAT_POLL_S)
                    if self._counts()[0] <= 0:
                        ok = True
                        break
        except C.CdpError:
            ok = False
        if not ok:
            self.s.navigate()
            self.s.poll_identity(S.IDENTITY_SETTLE_S)
        self.s.info.chat_seq += 1
        self.s.activate()
        return ok

    # ── 주입(B §5.3) ───────────────────────────────────────────────────
    def inject(self, text: str, dl: Deadline) -> _Inj:
        want = norm(text)
        up_to = dl.cap(self.cfg.ready_wait_sec)
        t0 = self.clock.mono()
        d = self.cfg.dom
        while True:
            try:
                ins = self._ev(js.focus_input(d.input_selectors, d.input_aria_labels)) or {}
            except C.CdpError:
                ins = {}
            if isinstance(ins, dict) and ins.get("ok"):
                break
            if self.clock.mono() - t0 >= up_to:
                return _Inj("input_not_found", len(want), 0)
            self._sleep(S.FOCUS_POLL_S)
        self.clear_editor()
        self.s.call("Input.insertText", {"text": text})
        self._sleep(S.INJECT_SETTLE_S)
        got = self._editor()
        if not match(got, want):
            self.clear_editor()
            try:
                self._ev(js.insert_fallback(text))
            except C.CdpError:
                pass
            self._sleep(S.INJECT_SETTLE_S)
            got = self._editor()
        if match(got, want):
            return _Inj("ok", len(want), len(got))
        self.clear_editor()                                   # 어긋난 글은 절대 보내지 않는다
        if len(got) < len(want) - S.MATCH_LEN_TOL and want.startswith(got[:S.OVERFLOW_HEAD]):
            return _Inj("input_overflow", len(want), len(got))
        return _Inj("inject_mismatch", len(want), len(got))

    # ── 전송·전송 확인(B §5.4) ─────────────────────────────────────────
    def _click_send(self) -> None:
        try:
            r = self._ev(js.click_send(self.cfg.dom.send_labels)) or {}
        except C.CdpError:
            r = {}
        if not (isinstance(r, dict) and r.get("ok")):
            self.press_enter()

    def _sent_within(self, sec: float, base: _Base) -> bool:
        t0 = self.clock.mono()
        while self.clock.mono() - t0 < sec:
            self._sleep(S.SEND_CONFIRM_POLL_S)
            if len(self._editor()) < S.SENT_EMPTY_LEN or self._counts()[0] > base.n_user:
                return True
        return False

    def send_and_confirm(self, base: _Base, dl: Deadline) -> tuple[str, bool]:
        """(phase, resent). 클릭이 '중지'에 먹혔으면 생성이 멎기를 기다렸다 한 번만 다시 보낸다."""
        self._click_send()
        if self._sent_within(S.SEND_CONFIRM_S, base):
            return "sent", False
        self.wait_idle(dl.cap(S.SEND_RETRY_IDLE_S))
        self._click_send()
        if self._sent_within(S.SEND_CONFIRM_S, base):
            return "sent", True
        self.clear_editor()
        return "send_failed", True

    # ── 회수(B §5.5) ───────────────────────────────────────────────────
    def _snapshot(self) -> _Snap:
        r = self._ev(js.poll(self.cfg.dom.stop_labels, self.cfg.dom.assistant_selectors, self._learned)) or {}
        r = r if isinstance(r, dict) else {}
        g = r.get("gen")
        return _Snap(gen=g if isinstance(g, bool) else None, n_user=int(r.get("n_user") or 0),
                     n_asst=int(r.get("n_asst", -1)), last=str(r.get("last") or ""), sel=str(r.get("sel") or ""))

    def _chat_text(self) -> str:
        try:
            return str(self._ev(js.chat_text(), timeout=S.CDP_SLOW_EVAL_S) or "")
        except C.CdpError:
            return ""

    def _fallback(self, req: SendRequest, base: _Base, anchor: str) -> tuple[str, str, int]:
        """앵커 폴백: (에코 뗀 몸통, pick, 이번 rid 서약 수 − 에코 몫)."""
        txt = self._chat_text()
        new, how = pick_reply(txt, base.page_len if base.measured else 0, anchor)
        pledges = len(pledge_rx(req.rid).findall(new)) - echo_pledges(req.text, anchor, how, req.rid)
        return strip_echo(new, req.text, anchor, how), how, pledges

    def _body(self, snap: _Snap, req: SendRequest, base: _Base, anchor: str) -> tuple[str, str, bool]:
        """(몸통, pick, 서약 있음). DOM 경로: 답 노드가 새로 생겼을 때 마지막 노드 글, 아니면 ''."""
        if snap.n_asst >= 0:
            body = snap.last if snap.n_asst > max(base.n_asst, 0) else ""
            return body, "dom", bool(pledge_rx(req.rid).search(body))
        body, how, pledges = self._fallback(req, base, anchor)
        return body, how, pledges > 0

    def _learn(self, req: SendRequest, body: str) -> None:
        """서약 답에서 답 노드 선택자 학습(설정 선택자도 학습값도 없을 때). 구조(속성 이름)만 저장한다."""
        if self.cfg.dom.assistant_selectors or self._learned:
            return
        m = pledge_rx(req.rid).search(body or "")
        if not m:
            return
        try:
            r = self._ev(js.learn_asst(m.group(0), req.text.strip()[:S.LEARN_HEAD])) or {}
        except C.CdpError:
            return
        if isinstance(r, dict) and r.get("ok") and isinstance(r.get("selector"), str):
            sel = r["selector"][:200]
            now = iso_now(self.clock)

            def put(d):
                d["dom"] = {"assistant_sel": sel, "learned_at": now, "verified": 1, "failures": 0}
            self.s.profile.update(put)
            self._learned, self._learned_src = sel, "learned"

    def _dom_verdict(self, ok: bool) -> None:
        """학습 선택자 검증 기록: 서약 회수 성공 → verified+1, 폴백에서만 서약 → failures+1(2회면 지우고 다시 학습)."""
        if self._learned_src != "learned":
            return

        def put(d):
            dom = d.setdefault("dom", {})
            if ok:
                dom["verified"] = int(dom.get("verified") or 0) + 1
                return
            dom["failures"] = int(dom.get("failures") or 0) + 1
            if dom["failures"] >= S.DOM_FAIL_LIMIT:
                d["dom"] = {}
        d = self.s.profile.update(put)
        if not (d.get("dom") or {}).get("assistant_sel"):
            self._learned, self._learned_src = "", ""

    # ── 완료 판정(B §5.6) ──────────────────────────────────────────────
    def wait_complete(self, req: SendRequest, base: _Base, dl: Deadline, extra: dict) -> SendResult:
        c = self.cfg
        anchor = build_anchor(req.text)
        t0 = self.clock.mono()
        last, same, idle, busy_seen, gens, first_tok = None, 0, 0, False, [], None
        end = min(t0 + req.reply_timeout_s, dl.at)
        pick = ""

        def result(phase, body, done_by=""):
            return SendResult(phase=phase, body=body or "", done_by=done_by, pick=pick, busy_seen=busy_seen,
                              gen_sec=round(self.clock.mono() - t0, 1), first_token_sec=first_tok, **extra)

        while self.clock.mono() < end:
            self._sleep(c.poll_sec)
            try:
                snap = self._snapshot()
                body, pick, has_pledge = self._body(snap, req, base, anchor)
            except (C.CdpTimeout, ConnectionError):
                self.s.reconnect()                             # 큰 DOM 평가 지연 — 다시 연결하고 계속 기다린다
                continue
            gen = snap.gen
            if gen:
                busy_seen = True
            gens.append(gen)
            el = self.clock.mono() - t0
            if body.strip() and first_tok is None:
                first_tok = round(el, 1)
            if has_pledge:                                     # ① 서약
                self._sleep(S.PLEDGE_TAIL_S)
                try:
                    b2, p2, h2 = self._body(self._snapshot(), req, base, anchor)
                    if h2:
                        body, pick = b2, p2
                except (C.CdpTimeout, ConnectionError, C.CdpError):
                    pass
                if pick == "dom":
                    self._dom_verdict(True)
                elif self._learned_src == "learned":
                    self._dom_verdict(False)                   # 학습 선택자로는 못 찾고 폴백에서만 서약을 봄
                else:
                    self._learn(req, body)
                return result("replied", body, "pledge")
            b = body.strip()
            if not b:
                same = idle = 0
                if el >= req.first_token_s and gen is not True:  # 생각 구간 유예가 지나고 생성 중도 아니면 빈 답
                    return result("empty_reply", "")
                last = body
                continue
            same = same + 1 if body == last else 0
            started, parsed = envelope_state(body, req.rid)
            idle = idle + 1 if (busy_seen and gen is False and same >= 1) else 0
            if idle >= 2 and parsed:                           # ② idle_json
                return self._finish(req, base, anchor, result, body, pick, "idle_json")
            need = c.stable_polls * (c.incomplete_json_factor if (started and not parsed) else 1)
            if same >= need and all(g is not True for g in gens[-(same + 1):]):   # ③ stable
                return self._finish(req, base, anchor, result, body, pick, "stable")
            last = body
        return result("no_reply", last or "")

    def _finish(self, req, base, anchor, result, body, pick, done_by) -> SendResult:
        """서약 없이 끝난 DOM 회수 — 폴백에서는 서약이 보이면 학습 선택자가 틀린 것(failures+1)이고 폴백 몸통을 쓴다."""
        if pick == "dom":
            try:
                fb, how, pledges = self._fallback(req, base, anchor)
            except (C.CdpTimeout, ConnectionError, C.CdpError):
                pledges = 0
            if pledges > 0:
                self._dom_verdict(False)
                r = result("replied", fb, "pledge")
                r.pick = how
                return r
        return result("replied", body, done_by)

    # ── 전송 1회(B §5.2) ───────────────────────────────────────────────
    def roundtrip(self, req: SendRequest) -> SendResult:
        try:
            return self._roundtrip(req)
        except PhaseError as e:
            return SendResult(phase=e.phase, error=e.phase, chat_seq=self.s.info.chat_seq)
        except (C.CdpError, OSError) as e:                       # CdpTimeout·ConnectionError 포함
            phase = "cdp_error"
            try:
                if not self.s.tab_alive():
                    phase = "tab_lost"
            except OSError:
                phase = "tab_lost"
            return SendResult(phase=phase, error=type(e).__name__[:S.ERROR_CODE_MAX], chat_seq=self.s.info.chat_seq)

    def _roundtrip(self, req: SendRequest) -> SendResult:
        dl = Deadline(self.clock, req.deadline)
        st = self.s.ensure_ready(dl)
        if st != "ready":
            return SendResult(phase=st, error=st, chat_seq=self.s.info.chat_seq)
        dom = self.s.profile.load().get("dom") or {}
        self._learned = str(dom.get("assistant_sel") or "") if not self.cfg.dom.assistant_selectors else ""
        self._learned_src = "learned" if self._learned else ""
        self.s.activate()
        if req.fresh:
            self.new_chat()
        if req.want_work_mode:
            self.s.ensure_work_mode()
        note = self.s.select_model(req.model)
        extra = {"model_note": f"{note.note}:{note.picked}"[:S.MODEL_NOTE_MAX],
                 "model_used": note.picked or self.s.info.model_current, "work_mode": self.s.info.work_mode,
                 "chat_seq": self.s.info.chat_seq}
        waited, still = self.wait_idle(dl.cap(self.cfg.wait_idle_sec))
        extra["waited_idle_sec"] = waited
        if still:
            return SendResult(phase="busy_before_send", **extra)
        n_user, n_asst = self._counts()
        base = _Base(n_user=n_user, n_asst=n_asst)
        if n_asst < 0:
            base.page_len, base.measured = len(self._chat_text()), True
        inj = self.inject(req.text, dl)
        extra.update(in_chars=inj.want, injected_chars=inj.got)
        if inj.phase != "ok":
            return SendResult(phase=inj.phase, **extra)
        phase, resent = self.send_and_confirm(base, dl)
        extra["resent"] = resent
        if phase != "sent":
            return SendResult(phase=phase, **extra)
        if base.measured:                                     # 새 채팅 인사말이 전송 순간 사라진다 — 기준을 다시 잰다
            base.page_len = min(base.page_len, len(self._chat_text()))
        return self.wait_complete(req, base, dl, extra)
