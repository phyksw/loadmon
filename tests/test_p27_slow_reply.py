# -*- coding: utf-8 -*-
r"""tests\test_p27_slow_reply.py — 느린 긴 답과 Copilot 채팅 도배(LM28 현장 제보: 워크플로우 단계의 긴 JSON 답).

· 드라이버 대기 — replyTimeoutSec 를 넘겨도 답이 자라는 동안은 왕복 예산 안에서 기다린다(약 1분마다 진행 줄 · 글 없음) · 예산 끝에도
  쓰는 중이면 정확한 '중지' 단추 하나만 누르고 받은 데까지 ok+cut+slow · 후보가 둘이면 누르지 않음 · 생각만 하다 끝나면 no_reply ·
  답 뒤 화면 잡음(상대 시각·추천 칩)이 바뀌어도 완료.
· slow 는 다시 보내지 않는다 — run_roundtrip 사다리·나눔 전체 재전송·judge 쉬기 사다리 없음 · flow 는 복구한 흐름을 쓰고 빠진 단위만
  작은 묶음으로 다시 묻는다(같은 묶음 전체는 다시 보내지 않음).
· 채팅 정리 — 생성 중이면 'gen'(남김 · 실패 아님) · 화면 사유로 남기면 구조 조사 한 줄(숫자만 — 제목·글·id 없음) · run.py 가 그 줄을
  실패 사유로 집지 않음 · 삭제 판정(소유 확인)은 그대로(p20 이 지킨다).
· 다음 단계 이어 쓰기(RESUME) — 상태 파일 조건 · 화면 확인 · 소유 기록(만든 수·보낸 수) 그대로 · judge 는 정제·Agentic·워크플로우의
  첫 왕복만 이어 쓰기를 요청한다(판정·월별 코멘트·실패 뒤는 예전처럼 새 채팅).
실제 Copilot·Edge·대기는 쓰지 않는다 — CDP 는 가짜, 드라이버의 시계는 가짜(Clock)로 바꾼다. 임시 폴더만 쓴다. 새 프로세스를 띄우지 않는다.
"""
import contextlib
import io
import json
import re
import tempfile
import time
import types
import unittest
from unittest import mock

import _boot  # noqa: F401  — 경로 등록
import copilot_auto as ca  # noqa: E402
import flow  # noqa: E402
import judge  # noqa: E402
import run as R  # noqa: E402
import test_p13_agentic_flow as p13  # noqa: E402
import test_p20_chat_cleanup as p20  # noqa: E402
import test_p22_throttle as p22  # noqa: E402

_REAL_TIME = time
BASE = "Copilot\n무엇을 도와드릴까요?"
PROMPT = p22.PROMPT
STOP_XY = (700, 900)                                   # 입력창의 '중지' 단추 자리
SLOW = {"ok": True, "phase": "replied", "reply": '{"j": [[0, "y", "Alpha-X", "개발", "보정', "cut": True, "slow": True,
        "stopped": True, "sentinel": False, "done_by": "slow"}


class Clock:
    """가짜 시계 — sleep 은 기다리지 않고 시각만 앞으로 민다. 그 밖(strftime·mktime …)은 진짜 time 모듈."""

    def __init__(self):
        self.t = _REAL_TIME.time()

    def time(self):
        return self.t

    def monotonic(self):
        return self.t

    def sleep(self, s):
        self.t += max(0.0, float(s or 0))

    def __getattr__(self, k):
        return getattr(_REAL_TIME, k)


def json_reply(n_rows):
    rows = [[i, "y", "Alpha-X", "개발", f"보정 데이터 검토 {i:04d}번 — 측정 로그 정리와 결과 공유"] for i in range(n_rows)]
    return json.dumps({"j": rows}, ensure_ascii=False)


def _nrm(s):
    return " ".join(str(s or "").split()).lower()


class StreamPage:
    """Copilot 채팅 탭 흉내(가짜 시계) — 보낸 뒤 delay 초 생각하고 cps 자/초로 답이 자란다. 다 쓰기 전에는 생성 중이다(show_gen=False 면
    '중지' 버튼을 못 찾는 화면). noise(시각 → 글): 다 쓴 뒤 답 아래 붙는 화면 잡음. buttons [(이름, 자리, x, y)] — 자리 'composer' 는 생성
    중에만 보이는 입력창 단추, 'nav'·'menu' 는 대화 목록·메뉴 안, 그 밖은 늘 보이는 다른 단추. 운영 js_stop_button 이 보고했을 것을
    흉내 낸다(정확한 이름 · 목록·메뉴 밖 · 하나일 때만 ok). '중지' 단추를 누르면 그 자리에서 답이 멈춘다."""

    def __init__(self, cfg, clock, reply, cps=20.0, delay=5.0, noise=None, show_gen=True,
                 buttons=(("응답 중지", "composer") + STOP_XY,)):
        self.cfg, self.clock, self.reply, self.cps, self.delay = cfg, clock, reply, cps, delay
        self.noise, self.show_gen, self.buttons = noise, show_gen, list(buttons)
        self.sent_at = self.stopped_at = None
        self.clicks, self.calls = [], []
        self.js = {"text": ca.js_chat_text(cfg), "focus": ca.js_focus(cfg), "click": ca.js_click_send(cfg),
                   "editor": ca.js_editor_text(), "gen": ca.js_is_generating(), "notes": ca.js_notices()}

    def shown(self):
        if self.sent_at is None:
            return ""
        if self.stopped_at is not None:
            return self.reply[:self.stopped_at]
        el = self.clock.t - self.sent_at - self.delay
        return self.reply[:max(0, min(len(self.reply), int(el * self.cps)))]

    def generating(self):
        return self.sent_at is not None and self.stopped_at is None and len(self.shown()) < len(self.reply)

    def _visible_buttons(self):
        return [b for b in self.buttons if b[1] != "composer" or (self.show_gen and self.generating())]

    def _stop_btn(self):
        want = {_nrm(s) for s in ca.STOP_LABELS}
        hs = [b for b in self._visible_buttons() if b[1] not in ("nav", "menu") and _nrm(b[0]) in want]
        if not hs:
            return {"r": "none"}
        if len(hs) > 1:
            return {"r": "many", "n": len(hs)}
        return {"r": "ok", "x": hs[0][2], "y": hs[0][3]}

    def eval(self, expr, timeout=25):
        js = self.js
        if expr == js["text"]:
            if self.sent_at is None:
                return BASE
            r = self.shown()
            stop = "\n응답을 중지했습니다." if self.stopped_at is not None else ""
            tail = ("\n" + self.noise(self.clock.t)) if (self.noise and r and not self.generating()) else ""
            return BASE + "\n나\n" + PROMPT + ("\nCopilot\n" + r + stop + tail if r else "")
        if expr == js["focus"]:
            return {"ok": True}
        if expr == js["click"]:
            self.sent_at = self.clock.t
            return {"ok": True}
        if expr == js["editor"]:
            return ""
        if expr == js["gen"]:
            return bool(self.show_gen and self.generating())
        if expr == js["notes"]:
            return []
        if str(expr).startswith("/*LM28:stop_btn*/"):
            return self._stop_btn()
        return None

    def call(self, method, params=None, timeout=25):
        p = params or {}
        self.calls.append(method)
        if method == "Input.dispatchMouseEvent" and p.get("type") == "mouseReleased":
            xy = (p.get("x"), p.get("y"))
            self.clicks.append(xy)
            hit = [b for b in self._visible_buttons() if (b[2], b[3]) == xy]
            if hit and hit[0][1] == "composer" and _nrm(hit[0][0]) in {_nrm(s) for s in ca.STOP_LABELS}:
                self.stopped_at = len(self.shown())
        return {}

    def reconnect(self):
        pass

    def close(self):
        pass


# ── 1) 드라이버 대기 — 가짜 시계로 진짜 _roundtrip_once 를 돌린다 ─────────────────────────────────────────────
class SlowWait(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="lm28_t27w_")
        self.cfg = p22._cfg(self._tmp.name, pollSec=3, stablePolls=4, minGapSec=0, replyTimeoutSec=60, firstTokenSec=30)
        self.clock = Clock()
        self.err = io.StringIO()
        st = self.stack = contextlib.ExitStack()
        st.enter_context(mock.patch.object(ca, "time", self.clock))
        st.enter_context(mock.patch.object(ca, "_sleep", self.clock.sleep))
        st.enter_context(mock.patch.object(ca, "_RT_DEADLINE", None))
        st.enter_context(mock.patch.object(ca, "trace", lambda *a, **k: None))
        st.enter_context(mock.patch.object(ca, "wait_page", lambda cdp, cfg, tries=30: (
            {"url": "https://m365.cloud.microsoft/chat", "ready": "complete"}, "chat")))
        st.enter_context(mock.patch.object(ca, "page_gate", lambda *a, **k: None))
        st.enter_context(mock.patch.object(ca, "wait_idle", lambda cdp, secs=45: 0))
        st.enter_context(mock.patch.object(ca, "select_model", lambda cdp, cfg, override=None: "GPT-5.6"))
        st.enter_context(mock.patch.object(ca, "_chat_before_send", lambda cdp, cfg, text: False))
        st.enter_context(mock.patch.object(ca, "_chat_after_send", lambda *a, **k: None))
        st.enter_context(contextlib.redirect_stderr(self.err))

    def tearDown(self):
        self.stack.close()
        self._tmp.cleanup()

    def budget(self, sec):
        ca._RT_DEADLINE = self.clock.t + sec          # 왕복 예산(roundtripMaxSec) — patch 가 끝나면 되돌린다
        return ca._RT_DEADLINE

    def notes(self):
        return [ln for ln in self.err.getvalue().splitlines() if "아직 쓰는 중" in ln]

    def test_streaming_past_reply_timeout_completes(self):
        self.budget(900)
        rep = json_reply(60)                                         # 약 3,600자 · 초당 20자 → 3분
        page = StreamPage(self.cfg, self.clock, rep)
        t0 = self.clock.t
        res = ca._roundtrip_once(page, self.cfg, PROMPT)
        self.assertTrue(res["ok"], res)
        self.assertFalse(res.get("slow") or res["cut"])
        self.assertTrue(res["reply"].endswith(rep))                  # 끝까지 다 받았다
        self.assertIn(res["done_by"], ("idle", "stable"))
        self.assertGreater(res.get("ext_sec", 0), 60)                # 기본 마감(60초) 뒤에도 기다렸다
        self.assertLess(self.clock.t - t0, 300)
        self.assertEqual(page.clicks, [])                            # 끝난 답은 아무것도 누르지 않는다
        self.assertTrue(self.notes())                                # 연장 중 진행 줄
        self.assertNotIn("Alpha-X", self.err.getvalue())             # 줄에 답 글은 없다

    def test_budget_cap_stops_exact_button_and_returns_slow_cut(self):
        dl = self.budget(300)
        rep = json_reply(2000)                                       # 끝없이 긴 답
        decoys = (("중지", "nav", 40, 300), ("중지하기", "toolbar", 500, 100), ("Stop sharing", "toolbar", 520, 100))
        page = StreamPage(self.cfg, self.clock, rep, buttons=(("응답 중지", "composer") + STOP_XY,) + decoys)
        res = ca._roundtrip_once(page, self.cfg, PROMPT)
        self.assertEqual((res["ok"], res["cut"], res.get("slow"), res.get("stopped"), res["done_by"]),
                         (True, True, True, True, "slow"))
        self.assertEqual(page.clicks, [STOP_XY])                     # 입력창의 '중지' 하나만 — 목록의 '중지'·비슷한 이름은 안 누름
        self.assertLessEqual(self.clock.t, dl)                       # 왕복 예산을 넘기지 않는다
        part = page.reply[:page.stopped_at]
        self.assertGreater(len(part), 3000)
        self.assertIn(part, res["reply"])                            # 받은 데까지(복구 재료)
        self.assertGreaterEqual(len(self.notes()), 3)                # 약 1분마다
        self.assertNotIn("Alpha-X", self.err.getvalue())

    def test_two_exact_stop_buttons_not_clicked(self):
        self.budget(200)
        page = StreamPage(self.cfg, self.clock, json_reply(2000),
                          buttons=(("응답 중지", "composer") + STOP_XY, ("Stop generating", "composer", 760, 900)))
        res = ca._roundtrip_once(page, self.cfg, PROMPT)
        self.assertEqual((res["ok"], res.get("slow"), res.get("stopped")), (True, True, False))
        self.assertEqual(page.clicks, [])

    def test_thinking_without_text_is_no_reply_and_stopped(self):
        self.budget(900)
        page = StreamPage(self.cfg, self.clock, "아직" * 50, delay=10 ** 6)   # 버튼만 보이고 글이 오지 않는다
        res = ca._roundtrip_once(page, self.cfg, PROMPT)
        self.assertEqual((res["ok"], res["phase"], res.get("stopped")), (False, "no_reply", True))
        self.assertEqual(page.clicks, [STOP_XY])                     # 뒤에서 마저 쓰지 않게 끊는다
        self.assertLess(self.clock.t - page.sent_at, ca.SLOW_ALIVE_BUSY_SEC + 10)

    def test_ui_noise_tail_still_completes(self):
        self.budget(900)
        rep = json_reply(5)
        page = StreamPage(self.cfg, self.clock, rep, cps=1000, show_gen=False,
                          noise=lambda t: f"추천 질문 · {int(t) % 97}초 전 · 피드백")
        res = ca._roundtrip_once(page, self.cfg, PROMPT)
        self.assertTrue(res["ok"])
        self.assertEqual((res["done_by"], bool(res.get("slow"))), ("stable", False))
        self.assertIn(rep, res["reply"])
        self.assertLess(self.clock.t - page.sent_at, 60)             # 기본 마감 전에 — 예전에는 잡음 때문에 시간 초과였다

    def test_stable_view(self):
        sv = ca._stable_view
        self.assertEqual(sv('{"a": 1}\n3분 전 · 추천'), '{"a": 1}')
        self.assertEqual(sv('{"a": [1, {"b": 2}'), '{"a": [1, {"b": 2}')       # 아직 쓰는 JSON — 그대로
        self.assertEqual(sv('{"a": 1}\n추천 {질문'), '{"a": 1}')
        self.assertEqual(sv("산문 답입니다"), "산문 답입니다")


# ── 2) slow 는 다시 보내지 않는다 ──────────────────────────────────────────────────────────────────────
class _Cdp:
    def __init__(self):
        self.calls = []

    def eval(self, expr, timeout=25):
        return {"url": "https://m365.cloud.microsoft/chat", "ready": "complete"} if "location.href" in str(expr) else None

    def call(self, method, params=None, timeout=25):
        self.calls.append(method)
        return {}

    def reconnect(self):
        pass

    def close(self):
        pass


class NoResend(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="lm28_t27n_")
        self.cfg = p22._cfg(self._tmp.name)
        self.once, self.newchat, self.tabs = [], [], []
        st = self.stack = contextlib.ExitStack()
        st.enter_context(mock.patch.object(ca, "_RT_DEADLINE", None))
        st.enter_context(mock.patch.object(ca, "trace", lambda *a, **k: None))
        st.enter_context(mock.patch.object(ca, "_sleep", lambda s: None))
        st.enter_context(mock.patch.object(ca, "ensure_edge", lambda cfg: "reuse"))
        st.enter_context(mock.patch.object(ca, "find_tab", lambda cfg: self.tabs.append(1) or "ws://127.0.0.1:9533/x"))
        st.enter_context(mock.patch.object(ca, "CDP", lambda ws: _Cdp()))
        st.enter_context(mock.patch.object(ca, "new_chat", lambda cdp, cfg: self.newchat.append(1) or "새 채팅 버튼"))
        st.enter_context(mock.patch.object(ca, "_roundtrip_once", self._once))
        st.enter_context(mock.patch.object(ca, "_wait_rest", self._no_wait))
        st.enter_context(contextlib.redirect_stderr(io.StringIO()))

    def tearDown(self):
        self.stack.close()
        self._tmp.cleanup()

    def _once(self, cdp, cfg, prompt, model_override=None):
        self.once.append(model_override)
        return dict(SLOW)

    @staticmethod
    def _no_wait(*a, **k):
        raise AssertionError("slow 답에 _wait_rest 로 더 기다리면 안 된다")

    def test_run_roundtrip_no_ladder(self):
        res = ca.run_roundtrip(self.cfg, "판정 요청", fresh=True)
        self.assertTrue(res["ok"] and res["slow"])
        self.assertEqual((self.once, self.newchat), ([None], [1]))   # 처음 연 새 채팅 하나뿐 — 사다리(새 채팅·자동 모델) 없음
        self.assertFalse(ca._rt_good(res))                          # 다음 단계가 이 채팅을 이어 쓰지 않는다

    def test_split_no_full_resend(self):
        prompt = "판정 요청 줄입니다 — 시험용 긴 자료 한 줄\n" * 600
        self.assertGreater(len(ca.make_parts(prompt, reserve=len(ca.PLEDGE_TAIL))), 1)
        res = ca.run_roundtrip_split(self.cfg, prompt)
        self.assertTrue(res["ok"] and res["slow"])
        self.assertEqual((len(self.once), len(self.tabs), self.newchat), (1, 1, []))   # 새 채팅 전체 재전송 없음
        self.assertIn("다시 보내지 않음", res["note"])


class JudgeSlow(p22._Send):
    def test_slow_not_resent(self):
        self.replies = [dict(SLOW)]
        res = self.send()
        self.assertTrue(res["ok"] and res["slow"])
        self.assertEqual((len(self.sent), self.cool), (1, []))
        self.assertTrue(judge._NEED_FRESH[0])                        # 끊긴 답이 남은 채팅 — 다음 묶음은 새 채팅

    def test_is_transient(self):
        self.assertFalse(judge._is_transient({"ok": False, "phase": "no_reply", "slow": True}))
        self.assertTrue(judge._is_transient({"ok": False, "phase": "no_reply"}))


class FlowSalvage(p13._Env):
    UNITS = ("회로시뮬레이션", "내구 시험", "열 해석", "부품 선정", "도면 검토")

    def test_cut_reply_salvaged_then_missing_in_small_chunks(self):
        rows = [p13._mm_row("모듈 설계", u, 1.0 + i / 10) for i, u in enumerate(self.UNITS)]
        sigs = [s for i, u in enumerate(self.UNITS) for s in p13._sigs("모듈 설계", u, n=4, day0=2 + i * 5)]
        self.data(rows, sigs)

        def reply(prompt, name):
            keys = re.findall(r"^## (.+?)  \(신호 \d+건\)", prompt, re.M)
            if name.endswith("-wf1"):
                full = json.dumps({"flows": [{"key": k, "role": "실무", "summary": "요약", "steps": p13.STEP3} for k in keys]},
                                  ensure_ascii=False)
                return dict(SLOW, reply=full[:full.index(keys[1]) + 5])   # 둘째 흐름 중간에서 끊긴 느린 답
            return p13.FlowRuns._flows(prompt)
        self.reply = reply
        rc, js, _out = self.run_main(flow, "--no-merge")
        self.assertEqual(rc, 0, js)
        names = [n for n, _p in self.calls]
        self.assertEqual(names, [f"{self.TAG}-wf1", f"{self.TAG}-wf1-r1", f"{self.TAG}-wf1-r2"])
        units = [re.findall(r"^## (.+?)  \(신호", p, re.M) for _n, p in self.calls]
        self.assertEqual([len(u) for u in units], [5, 3, 1])         # 빠진 4개만 ≤3개 묶음으로 — 같은 묶음 전체는 다시 안 보냄
        self.assertNotIn(units[0][0], units[1] + units[2])           # 복구한 흐름은 다시 묻지 않는다
        w = self.rjson(f"workflow_{self.TAG}.json")
        self.assertEqual((len(w["flows"]), w["salvaged_chunks"], w["missing_count"]), (5, 1, 0))


# ── 3) 채팅 정리 — 생성 중이면 남김 · 화면 사유면 구조 조사(숫자만) ──────────────────────────────────────────────
class CensusPage(p20.Page):
    """p20.Page + 구조 조사 JS(js_chat_census) 응답 · 생성 중 여부(js_is_generating)."""

    def __init__(self, census=None, generating=False, **f):
        super().__init__(**f)
        self.census, self.gen, self.census_calls = census, generating, 0

    def eval(self, js, timeout=25):
        s = str(js)
        if s.startswith("/*LM28:chat_census*/"):
            self.census_calls += 1
            return self.census
        if s == ca.js_is_generating():
            return self.gen
        return super().eval(js, timeout)


CENSUS = {"nnav": 1, "navw": 48, "nreg": 3, "nrow": 0, "nlink": 0, "nid": 2, "nhc": 0, "nhcv": 0, "ncur": 1, "ncurv": 0,
          "nsel": 0, "nselv": 0, "ntgc": 1, "ntgo": 0, "nmore": 0, "nmenu": 0, "ndlg": 0,
          "title": "비밀제목QX", "href": "https://m365.cloud.microsoft/chat/conversation/x", "nrow2": "글자"}


class ChatCleanup(p20._Base):
    def test_generating_chat_kept_not_failed(self):
        page = CensusPage(generating=True)
        a = self.own(page)
        page.events.clear()
        self.assertEqual(ca.retire_chat(page, self.cfg, "t"), "gen")
        self.assertEqual((page.events, page.deleted, a in page.order), ([], [], True))   # 아무것도 누르지 않았다
        t = self.totals()
        self.assertEqual((t["kept"], t["failed"], t["why"], t["last_fail"]), (1, 0, {"gen": 1}, "gen"))
        self.assertEqual(ca.CHAT_WHY["gen"], "답을 쓰는 중이라 남김")
        line = ca.chat_line()
        self.assertIn("답을 쓰는 중이라 남김 1", line)
        self.assertNotIn(ca.CHAT_CENSUS_HEAD, line)                  # 화면 사유가 아니다 — 구조 조사 없음
        self.assertEqual(page.census_calls, 0)

    def test_screen_reason_census_numbers_only(self):
        page = CensusPage(census=dict(CENSUS), links=False, current=False)
        a = self.own(page)
        self.assertEqual(ca.retire_chat(page, self.cfg, "t"), "noitem")
        self.assertEqual((page.deleted, page.clicks()), ([], []))    # 판정은 그대로 — 조사는 읽기만
        line = ca.chat_line()
        l1, l2 = line.split("\n")
        self.assertTrue(l1.startswith(ca.CHAT_LINE_HEAD) and l2.startswith(ca.CHAT_CENSUS_HEAD))
        self.assertIn("대화 목록에서 못 찾음 — 탐색 창 1 · 탐색 창 너비 48 · 탐색 창 접힘 추정 1", l2)
        self.assertIn("현재 표시 1", l2)
        self.assertIn("주소에 대화 id 1", l2)
        for bad in ("비밀제목QX", a, "conversation", "http", "글자"):
            self.assertNotIn(bad, line)
        cz = self.state()["totals"]["census"]
        self.assertEqual(set(cz) - {k for k, _l in ca.CENSUS_TEXT} - {"ok", "code", "t"}, set())
        self.assertTrue(all(isinstance(v, int) for k, v in cz.items() if k not in ("code", "t")))
        self.assertNotIn("비밀제목QX", json.dumps(self.traces, ensure_ascii=False))
        self.assertTrue(any(r.get("census") for r in self.traces if r.get("act") == "retire"))
        self.assertIn("구조: 탐색 창 1", ca.chat_status(self.cfg))
        self.assertTrue(l2.startswith(R.CHAT_LINE_HEAD))            # run.py 가 실패 사유 줄로 집지 않는다

    def test_census_unreadable_and_not_for_owner_reasons(self):
        page = CensusPage(census=None, links=False, current=False)
        self.own(page)
        self.assertEqual(ca.retire_chat(page, self.cfg, "t"), "noitem")
        self.assertIn("대화 목록에서 못 찾음 — 화면 구조를 읽지 못했습니다", ca.chat_line())
        page = CensusPage(census=dict(CENSUS))
        b = page.new_conv(["사람이 연 대화", "그 대화의 질문과 답이 여기 있습니다 — 시험용 다른 대화"])
        self.own(page)
        page.cur = b
        self.assertEqual(ca.retire_chat(page, self.cfg, "t"), "lost")   # 소유 사유 — 조사하지 않는다
        self.assertEqual(page.census_calls, 0)

    def test_js_markers_and_labels(self):
        cz, stop = ca.js_chat_census("a-b"), ca.js_stop_button()
        self.assertTrue(cz.startswith("/*LM28:chat_census*/") and stop.startswith("/*LM28:stop_btn*/"))
        for s in (cz, stop):                                         # p20 의 가짜 화면이 다른 JS 로 오인하지 않게
            self.assertNotIn("innerText", s)
            self.assertNotIn("location.href", s)
        self.assertIn("const WANT=" + json.dumps(list(ca.STOP_LABELS), ensure_ascii=False) + ";", stop)
        self.assertIn("nav,aside,[role='navigation']", stop)         # 대화 목록 안의 단추는 보지 않는다
        for lab in ca.STOP_LABELS:                                   # js_is_generating 의 후보 문구만
            self.assertTrue(lab in ("stop", "중지") or any(c in lab for c in ("생성 중지", "응답 중지", "stop generating",
                                                                             "stop responding")), lab)


class RunCaptureCensus(unittest.TestCase):
    def test_run_capture_skips_census_line(self):
        lines = ["[flow] 진짜 사유 줄", ca.CHAT_LINE_HEAD + "만든 1 · 지운 0 · 남긴 1 (사유: 대화 목록에서 못 찾음 1)",
                 ca.CHAT_CENSUS_HEAD + "대화 목록에서 못 찾음 — 탐색 창 0", '{"ok": false, "stop_kind": ""}']

        class FP:
            pid = 1

            def wait(self):
                return 1

        def watch(p, on, label):
            for x in lines:
                on(x)
            return ""
        with mock.patch.object(R.subprocess, "Popen", lambda *a, **k: FP()), \
                mock.patch.object(R.proc, "attach", lambda p: None), \
                mock.patch.object(R.proc, "release", lambda j, pid: None), \
                mock.patch.object(R, "watch_child", watch), contextlib.redirect_stdout(io.StringIO()):
            rc, why = R._run_capture(["python", "flow.py"], {})
        self.assertEqual((rc, why), (1, "[flow] 진짜 사유 줄"))


# ── 4) 다음 단계 이어 쓰기(RESUME) ─────────────────────────────────────────────────────────────────────
class Resume(p20._Base):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(mock.patch.object(ca, "_RESUMED", [None]))
        self.stack.enter_context(mock.patch.object(ca, "_RT_DEADLINE", None))

    def ok(self, page):
        ca._chat_seen(page, self.cfg, ok=True)

    def test_state_conditions(self):
        page = p20.Page()
        self.own(page)
        self.assertEqual(ca.chat_resumable(self.cfg, turns=12), (False, 0))          # 온전한 왕복 기록이 없다
        self.ok(page)
        self.assertEqual(ca.chat_resumable(self.cfg, turns=12), (True, 1))
        self.assertFalse(ca.chat_resumable(self.cfg, turns=1)[0])                    # chatTurns 를 다 썼다
        self.assertFalse(ca.chat_resumable(self.cfg, turns=0)[0])                    # chatTurns 0 = 늘 새 채팅
        st = self.state()
        st["t_ok"] = "2000-01-01 00:00:00"
        ca._chats_save(self.cfg, st)
        self.assertFalse(ca.chat_resumable(self.cfg, turns=12)[0])                   # 20분이 지났다
        self.ok(page)
        with mock.patch.object(judge, "_NEED_FRESH", [False]), mock.patch.object(judge, "_LAST_PROMPT", [None]):
            judge.note_bad_reply()                                                   # 답을 해석하지 못했다
        self.assertFalse(ca.chat_resumable(self.cfg, turns=12)[0])
        self.ok(page)
        ca._chats_save(self.cfg, ca._chat_reset(self.state()))
        self.assertFalse(ca.chat_resumable(self.cfg, turns=12)[0])                   # 우리 것이 아니다

    def test_screen_check(self):
        page = CensusPage()
        a = self.own(page)
        self.ok(page)
        self.assertTrue(ca._resume_ok(page, self.cfg))
        page.gen = True
        self.assertFalse(ca._resume_ok(page, self.cfg))                              # 아직 쓰는 중
        page.gen = False
        b = page.new_conv(list(page.convs[a]))                                       # 같은 글을 담은 다른 대화
        page.cur = b
        self.assertFalse(ca._resume_ok(page, self.cfg))
        page.cur = page.new_conv(["사람이 연 대화", "그 대화의 질문과 답이 여기 있습니다 — 시험용 다른 대화"])
        self.assertFalse(ca._resume_ok(page, self.cfg))

    def test_roundtrip_resume_keeps_bookkeeping(self):
        page = p20.Page()
        a = self.own(page)
        self.ok(page)
        page.events.clear()
        p20.Ladder.drive(self, page, [dict(p20.Ladder.OK)])
        res = ca.run_roundtrip(self.cfg, p20.PROMPT2, fresh=ca.RESUME)
        self.assertTrue(res["ok"])
        self.assertIs(ca._RESUMED[0], True)
        self.assertNotIn(("newchat",), page.events)                                  # 새 채팅을 열지 않았다
        st, t = self.state(), self.totals()
        self.assertEqual((st["sent"], st["anchor_sha"], page.cur), (2, ca.anchor_key(p20.PROMPT2)[0], a))
        self.assertEqual((t["made"], t["deleted"], t["kept"]), (1, 0, 0))           # 만든 채팅 수는 그대로
        self.assertTrue(st["last_ok"])
        self.assertEqual(ca.retire_chat(page, self.cfg, "t"), "deleted")             # 나중 정리도 그대로
        self.assertEqual(page.deleted, [a])

    def test_resume_falls_back_when_screen_differs(self):
        page = p20.Page()
        a = self.own(page)
        self.ok(page)
        b = page.new_conv(["사람이 연 대화", "그 대화의 질문과 답이 여기 있습니다 — 시험용 다른 대화"])
        page.cur = b
        page.events.clear()
        p20.Ladder.drive(self, page, [dict(p20.Ladder.OK)])
        res = ca.run_roundtrip(self.cfg, p20.PROMPT2, fresh=ca.RESUME)
        self.assertTrue(res["ok"])
        self.assertIs(ca._RESUMED[0], False)
        self.assertIn(("newchat",), page.events)                                     # 예전처럼 새 채팅
        self.assertNotIn(page.cur, (a, b))
        self.assertEqual(page.deleted, [])                                           # 남의 대화도 우리 대화도 지우지 않았다(화면이 다름)
        self.assertEqual(self.totals()["made"], 2)

    def test_slow_marks_not_resumable(self):
        page = p20.Page()
        self.own(page)
        self.ok(page)
        p20.Ladder.drive(self, page, [dict(SLOW)])
        res = ca.run_roundtrip(self.cfg, p20.PROMPT2)
        self.assertTrue(res["slow"])
        self.assertFalse(self.state()["last_ok"])
        self.assertFalse(ca.chat_resumable(self.cfg, turns=12)[0])

    def test_send_passes_resume_and_reports(self):
        seen = []

        def split(cfg, prompt, fresh=False, reload=False):
            seen.append(fresh)
            ca._RESUMED[0] = True
            return {"ok": True, "phase": "replied", "reply": "{}"}
        with mock.patch.object(ca, "run_stopped", lambda cfg=None: False), mock.patch.object(ca, "gate_ok", lambda p: True), \
                mock.patch.object(ca, "stub_dir", lambda: ""), mock.patch.object(ca, "run_roundtrip_split", split):
            res = ca._send(self.cfg, "정제 요청", fresh=ca.RESUME)
            res2 = ca._send(self.cfg, "정제 요청", fresh=True)
        self.assertEqual(seen, [ca.RESUME, True])
        self.assertIs(res["resumed"], True)
        self.assertNotIn("resumed", res2)


class JudgeResume(p22._Send):
    def setUp(self):
        super().setUp()
        self.raw, self.can = [], (True, 3)
        self.stack.enter_context(mock.patch.object(judge, "_inproc", lambda: True))
        self.stack.enter_context(mock.patch.object(ca, "chat_resumable", lambda cfg=None, turns=0: self.can))
        self.stack.enter_context(mock.patch.object(judge, "_transport", self._raw))

    def _raw(self, prompt_text, pf, name, want_fresh, lim, reload=False, model=None):
        self.raw.append(want_fresh)
        return dict(self.replies.pop(0) if len(self.replies) > 1 else self.replies[0])

    def test_first_send_of_later_stage_resumes(self):
        self.assertEqual(judge._RESUME, ca.RESUME)
        self.replies = [dict(p22.OK_REPLY, resumed=True)]
        self.assertTrue(judge.copilot_send("정제 요청", "t", "refine1")["ok"])
        self.assertEqual((self.raw, judge._TURNS[0]), (["resume"], 4))              # 앞 단계 채팅의 3번째 왕복 뒤
        judge.copilot_send("정제 요청 둘", "t", "refine2")
        self.assertEqual(self.raw[-1], False)                                        # 그다음은 예전처럼 같은 채팅에서 이어서

    def test_fallback_counts_new_chat(self):
        self.replies = [dict(p22.OK_REPLY, resumed=False)]
        judge.copilot_send("Agentic 요청", "t", "agentic")
        self.assertEqual((self.raw, judge._TURNS[0]), (["resume"], 1))               # 화면이 달라 새 채팅을 열었다

    def test_not_for_judge_explicit_or_after_failure(self):
        self.replies = [dict(p22.OK_REPLY)]
        cases = (("chunk1", None, None), ("narr_2026-03", True, None), ("flow", None, "need_fresh"),
                 ("flow", None, "cannot"), ("flow", None, "child"))
        for name, fresh, why in cases:
            self.new_process()
            self.can = (False, 0) if why == "cannot" else (True, 3)
            if why == "need_fresh":
                judge._NEED_FRESH[0] = True
            with mock.patch.object(judge, "_inproc", lambda: why != "child"):
                judge.copilot_send("요청 본문", "t", name, fresh=fresh)
            self.assertEqual(self.raw[-1], True, (name, why))                         # 예전처럼 새 채팅

    def test_transport_passes_resume(self):
        seen = []
        fake = types.SimpleNamespace(load_cfg=lambda: {},
                                     send_inproc=lambda p, fresh=False, deadline=None, stage="", **kw:
                                     seen.append(fresh) or {"ok": True})
        self.stack.enter_context(mock.patch.object(judge, "_transport", _REAL_TRANSPORT))
        with mock.patch.object(judge, "_ca", lambda: fake):
            judge._transport("p", "pf", "flow", judge._RESUME, 60)
            judge._transport("p", "pf", "flow", 1, 60)
        self.assertEqual(seen, ["resume", True])


_REAL_TRANSPORT = judge._transport            # 임포트 때의 진짜 함수(시험마다 _transport 는 가짜로 바뀐다)


if __name__ == "__main__":
    unittest.main()
