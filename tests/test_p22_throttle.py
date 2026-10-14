# -*- coding: utf-8 -*-
r"""tests\test_p22_throttle.py — Copilot 사용량 제한(「요청이 너무 많음」)에서 오래 멈추지 않기(LM28 현장 제보).

· 드라이버: 제한 문구 판정(현장 문구·영문·JSON/긴 글 제외) · 답을 기다리는 동안 답 머리·새 알림에서 바로 알아채기(사다리 없음) ·
  정상 답의 산문 머리는 집지 않기 · 보내기 간격(minGapSec) · 실행 표식(LM_RUN_ID) 기록과 성공 왕복의 지우기.
· judge.copilot_send: 사용량 제한은 throttleWaitSec 한 번 쉬고 다시 → 그래도 막히면 hard · 다른 일시 오류는 예전 사다리 ·
  같은 실행의 뒤 단계(다른 프로세스 흉내)는 보내지도 쉬지도 않음 · 지난 실행의 기록은 예전처럼 남은 시간만 쉬고 한 번.
· run.py: 한 줄 알림(실행에 1회)과 단계 기록(멈춘 단계 = 알림 문구 · 뒤 단계 = 건너뜀) · 자동 보고 보류는 판정이 빈손일 때만.
실제 Copilot·Edge·대기는 쓰지 않는다 — CDP 는 가짜, time.sleep·_sleep·_cooldown 은 가짜로 바꾼다. 임시 폴더만 쓴다.
"""
import contextlib
import io
import json
import os
import sys
import tempfile
import time
import types
import unittest
from unittest import mock

import _boot  # noqa: F401  — 경로 등록
import copilot_auto as ca  # noqa: E402
import details  # noqa: E402
import judge  # noqa: E402
import run as R  # noqa: E402
import test_p10_judge_scale as p10  # noqa: E402

FIELD = "현재 요청이 너무 많아 일시적으로 응답할 수 없습니다. 나중에 다시 시도하세요."     # 현장 문구(사진)
THROTTLED = {"ok": False, "phase": "throttled", "reason": "R-THROTTLE", "error": "Copilot 사용량 제한(일시)"}
COPILOT_ERR = {"ok": False, "phase": "copilot_error", "error": "Copilot 일시 오류 — 3단계 재시도 모두 실패"}
OK_REPLY = {"ok": True, "phase": "replied", "reply": '{"j": [[0, "y", "Orion-X", "개발", "보정 검토"]]}'}


def _cfg(tmp, **kw):
    c = dict(ca.DEFAULTS, profileDir=os.path.join(tmp, "data", "lm29_edge"), port=9543)
    c.update(kw)
    os.makedirs(os.path.dirname(c["profileDir"]), exist_ok=True)
    return c


# ── 1) 문구 판정 ────────────────────────────────────────────────────────────────
class Marks(unittest.TestCase):
    def test_field_and_english(self):
        self.assertTrue(ca.is_throttle_reply(FIELD))
        self.assertTrue(ca.is_throttle_reply("Copilot\n" + FIELD + "\n다시 시도"))
        self.assertTrue(ca.is_error_reply(FIELD))                      # 오류 문구이기도 하다 — 제한 판정이 먼저여야 한다
        for s in ("We're receiving too many requests right now. Please try again later.",
                  "You've hit the rate limit. Try again in a few minutes.",
                  "Copilot is temporarily unable to respond. Please try again in a little while.",
                  "잠시 후에 다시 시도해 주세요.", "요청이 너무 많습니다"):
            self.assertTrue(ca.is_throttle_reply(s), s)

    def test_not_matched(self):
        self.assertFalse(ca.is_throttle_reply('{"j":[[0,"y","Orion-X","개발","' + FIELD + '"]]}'))   # JSON 안의 인용
        self.assertFalse(ca.is_throttle_reply("분석 결과 " * 130 + FIELD))                          # 긴 글
        self.assertFalse(ca.is_throttle_reply("판정 결과입니다. " * 60 + "rate limit"))             # 머리(400자) 밖
        self.assertFalse(ca.is_throttle_reply("죄송합니다. 지금은 응답할 수 없습니다."))           # 일반 오류 — 사다리 대상
        self.assertFalse(ca.is_throttle_reply(""))

    def test_settled_rule(self):
        st = ca._throttle_settled
        self.assertFalse(st(0, False, False, 3))                     # 처음 본 글 — 아직(정상 답의 머리일 수 있다)
        self.assertFalse(st(1, False, False, 3))
        self.assertTrue(st(2, False, False, 3))                      # 6초 그대로
        self.assertTrue(st(1, False, True, 3))                       # '중지' 버튼을 본 뒤 사라짐 — 한 폴 확인
        self.assertFalse(st(5, True, True, 3))                       # 아직 생성 중
        self.assertTrue(st(10, True, True, 3))                       # 버튼이 30초 그대로 — 끝없이 기다리지 않는다


class _NoticeCdp:
    def __init__(self, result):
        self.result = result

    def eval(self, expr, timeout=25):
        assert expr.startswith("/*LM28:notices*/")
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class NoticePath(unittest.TestCase):
    def test_new_notice_only(self):
        prompt = "판정 요청\n#1 | 메일 | 보정 검토"
        self.assertEqual(ca._new_notice(_NoticeCdp(["저장됨", FIELD]), ["저장됨"], prompt), FIELD)
        self.assertEqual(ca._new_notice(_NoticeCdp([FIELD]), [FIELD], prompt), "")         # 보내기 전부터 떠 있던 것
        self.assertEqual(ca._new_notice(_NoticeCdp([FIELD]), [], prompt + "\n" + FIELD), "")  # 우리가 보낸 글의 일부
        self.assertEqual(ca._new_notice(_NoticeCdp(['{"j": "rate limit"}']), [], prompt), "")
        self.assertEqual(ca._new_notice(_NoticeCdp("페이지 전체 글 " + FIELD), [], prompt), "")  # 목록이 아니면 없음
        self.assertEqual(ca._new_notice(_NoticeCdp(TimeoutError("느림")), [], prompt), "")
        self.assertIsNone(ca._notices(_NoticeCdp(OSError("끊김"))))


# ── 2) 답을 기다리는 동안 바로 알아채기 — 가짜 CDP 로 진짜 _roundtrip_once 를 돌린다 ─────────────────
BASE = "Copilot\n무엇을 도와드릴까요?"
PROMPT = ("다음 신호를 판정하세요.\n#1 | 2026-03-02 09:00 | 메일(수신) | Orion-X 보정 데이터 검토 요청 | 업무\n"
          "형식: {\"j\": [[번호, y/n, 과제, 유형, 세부]]}")


class _Hang(Exception):
    """가짜 화면이 폴 상한을 넘었다 — 대기 루프가 끝나지 않았다는 뜻."""


class _Page:
    """채팅 탭 흉내 — 보낸 뒤 폴마다 replies[i]·gens[i]·notices 를 돌려준다(마지막 값 반복)."""

    def __init__(self, cfg, prompt=PROMPT, replies=("",), gens=(False,), before=(), after=(), max_polls=40):
        self.cfg, self.prompt, self.replies, self.gens = cfg, prompt, list(replies), list(gens)
        self.before, self.after, self.max_polls = list(before), list(after), max_polls
        self.sent, self.after_send, self.polls, self.clicks, self.calls = False, 0, 0, 0, []
        self.js = {"text": ca.js_chat_text(cfg), "focus": ca.js_focus(cfg), "click": ca.js_click_send(cfg),
                   "editor": ca.js_editor_text(), "gen": ca.js_is_generating(), "notes": ca.js_notices()}

    def _at(self, seq):
        return seq[min(max(self.polls, 1) - 1, len(seq) - 1)]

    def eval(self, expr, timeout=25):
        js = self.js
        if expr == js["text"]:
            if not self.sent:
                return BASE
            self.after_send += 1
            self.polls = self.after_send - 1          # 보낸 직후 한 번은 기준선 다시 재기
            if self.polls > self.max_polls:
                raise _Hang()
            r = self._at(self.replies) if self.polls else ""
            return BASE + "\n나\n" + self.prompt + ("\nCopilot\n" + r if r else "")
        if expr == js["focus"]:
            return {"ok": True}
        if expr == js["click"]:
            self.sent = True
            self.clicks += 1
            return {"ok": True}
        if expr == js["editor"]:
            return ""
        if expr == js["gen"]:
            return bool(self._at(self.gens)) if self.polls else False
        if expr == js["notes"]:
            return list(self.after if self.sent else self.before)
        return None

    def call(self, method, params=None, timeout=25):
        self.calls.append(method)
        return {}

    def reconnect(self):
        pass

    def close(self):
        pass


class WaitLoop(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="lm28_t22w_")
        self.cfg = _cfg(self._tmp.name, pollSec=3, stablePolls=8, minGapSec=0)
        self.fresh = []
        st = self.stack = contextlib.ExitStack()
        st.enter_context(mock.patch.object(ca, "_RT_DEADLINE", None))
        st.enter_context(mock.patch.object(ca.time, "sleep", lambda s: None))
        st.enter_context(mock.patch.object(ca, "_sleep", lambda s: None))
        st.enter_context(mock.patch.object(ca, "trace", lambda *a, **k: None))
        st.enter_context(mock.patch.object(ca, "wait_page", lambda cdp, cfg, tries=30: (
            {"url": "https://m365.cloud.microsoft/chat", "ready": "complete"}, "chat")))
        st.enter_context(mock.patch.object(ca, "page_gate", lambda *a, **k: None))
        st.enter_context(mock.patch.object(ca, "wait_idle", lambda cdp, secs=45: 0))
        st.enter_context(mock.patch.object(ca, "select_model", lambda cdp, cfg, override=None: "GPT-5.6"))
        st.enter_context(mock.patch.object(ca, "_chat_before_send", lambda cdp, cfg, text: False))
        st.enter_context(mock.patch.object(ca, "_chat_after_send", lambda *a, **k: None))
        st.enter_context(mock.patch.object(ca, "_chat_seen", lambda *a, **k: None))
        st.enter_context(mock.patch.object(ca, "_fresh_chat", lambda cdp, cfg, why="", reload=False:
                                           self.fresh.append(why) or "새 채팅"))
        st.enter_context(mock.patch.object(ca, "ensure_edge", lambda cfg: "reuse"))
        st.enter_context(mock.patch.object(ca, "find_tab", lambda cfg: "ws://127.0.0.1:9543/devtools/page/x"))
        st.enter_context(contextlib.redirect_stderr(io.StringIO()))

    def tearDown(self):
        self.stack.close()
        self._tmp.cleanup()

    def once(self, page):
        return ca._roundtrip_once(page, self.cfg, page.prompt)

    def test_reply_throttle_fast_and_no_ladder(self):
        page = _Page(self.cfg, replies=(FIELD,))
        with mock.patch.object(ca, "CDP", lambda ws: page):
            res = ca.run_roundtrip(self.cfg, PROMPT)
        self.assertEqual((res["ok"], res["phase"], res["reason"]), (False, "throttled", "R-THROTTLE"))
        self.assertEqual((res["done_by"], res["via"]), ("throttle", "reply"))
        self.assertEqual(page.polls, 3)                              # ~6초 — 안정 폴링 8회(24초)·replyTimeoutSec 를 기다리지 않는다
        self.assertEqual((page.clicks, self.fresh), (1, []))         # 보낸 것은 한 번 — 새 채팅 사다리 없음
        self.assertFalse(ca.throttle_state(self.cfg)[1])            # 약한 관찰로 기록(다음 단계가 안다)

    def test_notice_throttle(self):
        page = _Page(self.cfg, replies=("",), before=["저장됨"], after=["저장됨", FIELD])
        res = self.once(page)
        self.assertEqual((res["phase"], res["via"]), ("throttled", "notice"))
        self.assertEqual(page.polls, 3)                              # 첫 글자 유예(firstTokenSec)를 다 기다리지 않는다
        self.assertEqual(page.clicks, 1)

    def test_old_notice_or_own_text_ignored(self):
        with self.assertRaises(_Hang):                               # 보내기 전부터 떠 있던 알림은 근거가 아니다
            self.once(_Page(self.cfg, replies=("",), before=[FIELD], after=[FIELD], max_polls=12))
        with self.assertRaises(_Hang):                               # 우리가 보낸 글(대화 영역이 aria-live 인 화면)
            self.once(_Page(self.cfg, prompt=PROMPT + "\n" + FIELD, replies=("",), after=[FIELD], max_polls=12))

    def test_busy_then_done(self):
        page = _Page(self.cfg, replies=(FIELD,), gens=(True, True, True, True, False))
        res = self.once(page)
        self.assertEqual((res["phase"], page.polls, res["busy_seen"]), ("throttled", 5, True))

    def test_stuck_stop_button(self):
        page = _Page(self.cfg, replies=("",), gens=(True,), after=[FIELD])
        res = self.once(page)
        self.assertEqual((res["phase"], res["via"]), ("throttled", "notice"))
        self.assertEqual(page.polls, 11)                             # 버튼이 30초 그대로면 더 기다리지 않는다
        page = _Page(self.cfg, replies=(FIELD,), gens=(True,))       # 답 자리의 제한 문구는 예전 안정 폴링(8회)이 먼저 집는다
        with mock.patch.object(ca, "CDP", lambda ws: page):
            res = ca.run_roundtrip(self.cfg, PROMPT)
        self.assertEqual((res["phase"], page.polls, page.clicks, self.fresh), ("throttled", 9, 1, []))

    def test_prose_head_of_real_answer_not_taken(self):
        head = "rate limit 관련 메일은 업무로 봤습니다."
        body = head + '\n{"j": [[1, "y", "Orion-X", "개발", "보정 검토"]]}'
        page = _Page(self.cfg, replies=(head, body, body + "\n" + ca.SENTINEL))
        res = self.once(page)
        self.assertTrue(res["ok"])
        self.assertEqual((res["phase"], res["done_by"]), ("replied", "pledge"))
        self.assertIn('"j"', res["reply"])


# ── 3) 보내기 간격(minGapSec) ─────────────────────────────────────────────────────
class Pacing(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="lm28_t22p_")
        self.cfg = _cfg(self._tmp.name)
        self.slept = []
        self.err = io.StringIO()
        st = self.stack = contextlib.ExitStack()
        st.enter_context(mock.patch.object(ca, "_RT_DEADLINE", None))
        st.enter_context(mock.patch.object(ca, "_sleep", lambda s: self.slept.append(s)))
        st.enter_context(contextlib.redirect_stderr(self.err))

    def tearDown(self):
        self.stack.close()
        self._tmp.cleanup()

    def write_t(self, t):
        with open(ca._side_path(self.cfg, ca.PACE_FILE), "w", encoding="utf-8") as f:
            json.dump({"t": t}, f)

    def test_first_send_no_wait(self):
        self.assertEqual(ca.pace_wait(self.cfg), 0.0)
        self.assertEqual(self.slept, [])

    def test_waits_only_remainder(self):
        ca.mark_sent(self.cfg)
        w = ca.pace_wait(self.cfg)
        self.assertAlmostEqual(w, 15.0, delta=1.0)
        self.assertIn("minGapSec", self.err.getvalue())             # 5초 넘게 기다리면 한 줄
        self.write_t(time.time() - 12)
        self.slept.clear()
        self.err.truncate(0)
        self.err.seek(0)
        w = ca.pace_wait(self.cfg)
        self.assertTrue(0 < w <= 3.5, w)
        self.assertEqual(self.err.getvalue(), "")                    # 짧은 맞춤은 조용히

    def test_off_corrupt_future_deadline(self):
        ca.mark_sent(self.cfg)
        self.assertEqual(ca.pace_wait(dict(self.cfg, minGapSec=0)), 0.0)
        with open(ca._side_path(self.cfg, ca.PACE_FILE), "w", encoding="utf-8") as f:
            f.write("{깨짐")
        self.assertEqual(ca.pace_wait(self.cfg), 0.0)
        self.write_t(time.time() + 3600)                            # 시계가 뒤로 갔다 — gap 을 넘겨 기다리지 않는다
        self.assertLessEqual(ca.pace_wait(self.cfg), 15.0)
        ca.mark_sent(self.cfg)
        with mock.patch.object(ca, "_RT_DEADLINE", time.time() + 30):
            self.assertEqual(ca.pace_wait(self.cfg), 0.0)            # 왕복 마감이 가깝다 — 기다리지 않고 보낸다
        with mock.patch.object(ca, "_RT_DEADLINE", time.time() + 70):
            self.assertLessEqual(ca.pace_wait(self.cfg), 10.5)
        self.assertEqual(self.slept and min(self.slept) > 0, True)

    def test_zero_kept_by_load_cfg(self):
        p = os.path.join(self._tmp.name, "config.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"copilotAuto": {"minGapSec": 0}}, f)
        self.assertEqual(ca.load_cfg(p)["minGapSec"], 0)
        self.assertEqual(ca.load_cfg(os.path.join(self._tmp.name, "없음.json"))["minGapSec"], 15)


# ── 4) 기록 — 실행 표식 · 옛 판 기록 · 성공 왕복이 지운다 · 드라이버도 같은 실행이면 보내지 않는다 ─────────
class RunRecord(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="lm28_t22r_")
        self.cfg = _cfg(self._tmp.name)
        st = self.stack = contextlib.ExitStack()
        st.enter_context(mock.patch.dict(os.environ))
        os.environ["LM_RUN_ID"] = "run-A"

    def tearDown(self):
        self.stack.close()
        self._tmp.cleanup()

    def test_record_and_clear(self):
        self.assertFalse(ca.run_stopped(self.cfg))
        ca.note_throttle(self.cfg, hard=True, run="run-A", kind="throttle")
        self.assertEqual(ca.throttle_state(self.cfg, run=True)[1:], (True, "run-A", "throttle"))
        self.assertEqual(len(ca.throttle_state(self.cfg)), 2)                  # 옛 꼴 그대로
        self.assertTrue(ca.run_stopped(self.cfg))
        ca.note_throttle(self.cfg)                                             # 약한 관찰은 표식을 둔다
        self.assertTrue(ca.run_stopped(self.cfg))
        os.environ["LM_RUN_ID"] = "run-B"
        self.assertFalse(ca.run_stopped(self.cfg))                             # 다른 실행
        os.environ.pop("LM_RUN_ID")
        self.assertFalse(ca.run_stopped(self.cfg))                             # 표식 없는 실행(단계를 따로 돌림)
        os.environ["LM_RUN_ID"] = "run-A"
        ca._after(self.cfg, {"ok": True, "phase": "replied"})                  # 성공 왕복이 지운다
        self.assertIsNone(ca.throttle_state(self.cfg))
        self.assertFalse(ca.run_stopped(self.cfg))

    def test_ladder_hard_clears_mark_and_old_format(self):
        ca.note_throttle(self.cfg, hard=True, run="run-A", kind="throttle")
        ca.note_throttle(self.cfg, hard=True)                                  # 일시 오류 사다리 끝의 hard — 표식 없음
        self.assertEqual(ca.throttle_state(self.cfg, run=True)[1:], (True, "", ""))
        with open(ca._side_path(self.cfg, ca.THROTTLE_FILE), "w", encoding="utf-8") as f:
            json.dump({"t": time.time(), "n": 1, "hard": True, "hard_t": time.time()}, f)   # 옛 판 기록
        self.assertEqual(ca.throttle_state(self.cfg, run=True)[1:], (True, "", ""))
        self.assertFalse(ca.run_stopped(self.cfg))

    def test_driver_send_skips_in_same_run(self):
        ca.note_throttle(self.cfg, hard=True, run="run-A", kind="throttle")

        def boom(*a, **k):
            raise AssertionError("보내지 않아야 한다")
        with mock.patch.object(ca, "edge_lock", boom), mock.patch.object(ca, "gate_ok", boom):
            res = ca._send(self.cfg, "메일 확인 요청")
            res2 = ca.send_inproc("팀즈 확인 요청", cfg=self.cfg, stage="teams_copilot")
        for r in (res, res2):
            self.assertEqual((r["ok"], r["phase"], r["hard"], r["run_stop"]), (False, "throttled", True, True))
            self.assertTrue(details.explain_failure(r)[2])                     # 호출자가 남은 묶음을 접는다


# ── 5) judge.copilot_send — 한 번 쉬고 다시 → hard · 다른 일시 오류는 예전 사다리 · 같은 실행의 뒤 단계 ─────────
class _Send(unittest.TestCase):
    GLOBALS = (("_FIRST_SEND", [True]), ("_NEED_FRESH", [False]), ("_TURNS", [0]), ("_CHAT_TURNS", [None]),
               ("_HARD", [False]), ("_COOLED", [0.0]), ("_COOLDOWNS", [0]), ("_MODEL_FALLBACK", [""]),
               ("_THR_CHECKED", [False]), ("_WAIT_TICKS", [0]), ("_LAST_PROMPT", [None]), ("_STUB_NOTED", [True]),
               ("_RUN_STOP_SAID", [False]), ("_BUDGET_SAID", [False]))

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="lm28_t22s_")
        self.tmp = self._tmp.name
        self.cfg = _cfg(self.tmp)
        self.sent, self.cool, self.ccfg, self.replies = [], [], {}, []
        st = self.stack = contextlib.ExitStack()
        st.enter_context(mock.patch.dict(os.environ))
        for k in ("LM_AI_DEADLINE", "LM_COPILOT_STUB", "LM_RUN_ID"):
            os.environ.pop(k, None)
        st.enter_context(mock.patch.object(judge, "ROOT", self.tmp))
        for name, val in self.GLOBALS:
            st.enter_context(mock.patch.object(judge, name, list(val)))
        st.enter_context(mock.patch.object(judge, "g3_prompt", lambda text: True))
        st.enter_context(mock.patch.object(judge, "_transport", self._transport))
        st.enter_context(mock.patch.object(judge, "_cooldown", lambda sec: self.cool.append(sec)))
        st.enter_context(mock.patch.object(judge, "_copilot_cfg", lambda: self.ccfg))
        st.enter_context(mock.patch.object(ca, "load_cfg", lambda *a, **k: dict(self.cfg)))   # 기록 파일은 임시 폴더
        self.out = io.StringIO()
        st.enter_context(contextlib.redirect_stdout(self.out))

    def tearDown(self):
        self.stack.close()
        self._tmp.cleanup()

    def _transport(self, prompt_text, pf, name, want_fresh, lim, reload=False, model=None):
        self.sent.append({"name": name, "fresh": bool(want_fresh), "reload": bool(reload), "model": model or ""})
        r = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        return dict(r)

    def new_process(self):
        """뒤 단계 프로세스 흉내 — 판정 모듈의 프로세스 전역을 처음 상태로(기록 파일·LM_RUN_ID 는 그대로 물려받는다)."""
        for name, val in self.GLOBALS:
            getattr(judge, name)[:] = list(val)

    def send(self, name="chunk1"):
        return judge.copilot_send("판정 요청 본문", "t", name)


class CopilotSendThrottle(_Send):
    def test_wait_once_then_hard_and_run_stop(self):
        os.environ["LM_RUN_ID"] = "run-A"
        self.replies = [dict(THROTTLED)]
        res = self.send()
        self.assertEqual(self.cool, [120.0])                         # 1·2·2분 사다리가 아니라 2분 한 번
        self.assertEqual(len(self.sent), 2)
        self.assertEqual([(s["fresh"], s["reload"]) for s in self.sent[1:]], [(True, True)])
        self.assertTrue(res.get("hard"))
        self.assertEqual((res.get("cooldowns"), judge._abort_kind_of(res)), (1, "throttle"))
        self.assertTrue(details.explain_failure(res)[2])
        self.assertEqual(ca.throttle_state(run=True)[1:], (True, "run-A", "throttle"))
        out = self.out.getvalue()
        self.assertIn("2분(120초) 쉬고 새로 고친 뒤 같은 묶음을 한 번만 다시 보냅니다", out)
        self.assertIn("이번 실행의 AI 단계는 더 보내지 않고", out)
        # 같은 실행의 뒤 단계(정제·워크플로우·월별 코멘트 — 다른 프로세스) — 보내지도, 남은 시간을 쉬지도 않는다
        self.new_process()
        n_sent = len(self.sent)
        for nm in ("refine1", "wf1", "narr_2026-03"):
            r = self.send(nm)
            self.assertEqual((r["ok"], r["phase"], r["hard"], r.get("run_stop")), (False, "throttled", True, True))
            self.assertTrue(details.explain_failure(r)[2])
        self.assertEqual((len(self.sent), self.cool), (n_sent, [120.0]))
        self.assertEqual(self.out.getvalue().count("이번 실행은 Copilot 사용량 제한(요청이 너무 많음)으로"), 1)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "report", "judge_refine1_t.md")))   # 보내지 않은 프롬프트

    def test_throttle_then_ok(self):
        self.replies = [dict(THROTTLED), dict(OK_REPLY)]
        res = self.send()
        self.assertTrue(res["ok"])
        self.assertEqual((self.cool, len(self.sent), res.get("cooldowns")), ([120.0], 2, 1))
        self.assertIsNone(ca.throttle_state())

    def test_wait_setting(self):
        self.ccfg = {"throttleWaitSec": 45}
        self.replies = [dict(THROTTLED)]
        self.assertTrue(self.send().get("hard"))
        self.assertEqual(self.cool, [45.0])

    def test_wait_zero_stops_at_once(self):
        os.environ["LM_RUN_ID"] = "run-A"
        self.ccfg = {"throttleWaitSec": 0}
        self.replies = [dict(THROTTLED)]
        res = self.send()
        self.assertTrue(res.get("hard"))
        self.assertEqual((self.cool, len(self.sent)), ([], 1))
        self.assertTrue(ca.run_stopped())

    def test_other_transient_keeps_ladder(self):
        os.environ["LM_RUN_ID"] = "run-A"
        self.replies = [dict(COPILOT_ERR)]
        res = self.send()
        self.assertEqual(self.cool, [60.0, 120.0, 120.0])             # 1·2·2분(LM28 — 예전 2·5·10분)
        self.assertEqual(len(self.sent), 4)
        self.assertEqual([s["model"] for s in self.sent], ["", "", "", "자동"])
        self.assertTrue(res.get("hard"))
        self.assertEqual(ca.throttle_state(run=True)[1:], (True, "", ""))      # 실행 표식 없음 — 뒤 단계는 예전처럼
        self.assertFalse(ca.run_stopped())

    def test_throttle_after_transient_waits_once(self):
        self.replies = [dict(COPILOT_ERR), dict(THROTTLED), dict(THROTTLED)]
        res = self.send()
        self.assertEqual(self.cool, [60.0, 120.0])                   # 사다리 1단(1분) + 사용량 제한 한 번(2분)
        self.assertEqual((len(self.sent), res.get("cooldowns")), (3, 2))
        self.assertTrue(res.get("hard"))

    def test_earlier_run_record_keeps_prewait(self):
        os.environ["LM_RUN_ID"] = "run-B"
        now = time.time()
        with open(ca._side_path(self.cfg, ca.THROTTLE_FILE), "w", encoding="utf-8") as f:
            json.dump({"t": now - 120, "n": 3, "hard": True, "hard_t": now - 120, "run": "run-A", "kind": "throttle"}, f)
        self.replies = [dict(THROTTLED)]
        res = self.send()
        self.assertEqual(len(self.cool), 1)
        self.assertAlmostEqual(self.cool[0], 180.0, delta=3.0)       # 5분 중 남은 3분만 한 번 쉬고
        self.assertEqual(len(self.sent), 1)                          # 한 번 보내 막히면 바로 hard(사용량 제한 대기 없음)
        self.assertTrue(res.get("hard"))
        self.assertIn("지난 실행이 Copilot 사용량 제한(요청이 너무 많음)으로 멈췄습니다", self.out.getvalue())
        self.assertEqual(ca.throttle_state(run=True)[2], "run-B")   # 이번 실행도 멈춤으로 기록

    def test_earlier_run_record_then_ok(self):
        os.environ["LM_RUN_ID"] = "run-B"
        ca.note_throttle(hard=True, run="run-A", kind="throttle")
        self.replies = [dict(OK_REPLY)]
        self.assertTrue(self.send()["ok"])
        self.assertEqual(len(self.sent), 1)

    def test_real_cooldown_prints_progress(self):
        clock = types.SimpleNamespace(t=0.0)
        fake = types.SimpleNamespace(monotonic=lambda: clock.t, time=time.time,
                                     sleep=lambda s: setattr(clock, "t", clock.t + s))
        self.stack.enter_context(mock.patch.object(judge, "time", fake))     # 판정 모듈의 시계만 — 실제로 기다리지 않는다
        _REAL_COOLDOWN(120)
        self.assertEqual(self.out.getvalue().count("[progress] Copilot 대기|"), 4)   # 30초마다 — 감시기가 멈춘 것으로 보지 않게
        self.assertEqual(clock.t, 120.0)


_REAL_COOLDOWN = judge._cooldown              # 임포트 때의 진짜 함수(시험마다 _cooldown 은 가짜로 바뀐다)


# ── 6) judge.main — 판정이 사용량 제한으로 멈추면 남은 묶음·월별 코멘트는 보내지 않는다 ───────────────────────
class JudgeMainThrottle(p10._Base):
    def setUp(self):
        super().setUp()
        self.rec = {}
        self.stack.enter_context(mock.patch.object(ca, "note_throttle", self._note))
        self.stack.enter_context(mock.patch.object(ca, "throttle_state", self._state))
        self.stack.enter_context(mock.patch.object(judge, "_RUN_STOP_SAID", [False]))
        # 실행 표식이 있으면 쉬는 시간 합계(<프로필>.wait.json)를 적는다 — 운영 프로필이 아니라 임시 폴더에
        self.stack.enter_context(mock.patch.object(ca, "load_cfg", lambda *a, **k: _cfg(self.tmp)))
        os.environ["LM_RUN_ID"] = "run-A"

    def _note(self, cfg=None, hard=False, run=None, kind=None):
        self.notes.append({"hard": hard, "run": run, "kind": kind})
        if hard:
            self.rec = {"t": time.time(), "run": run or "", "kind": kind or ""}
        return True

    def _state(self, cfg=None, run=False):
        if not self.rec:
            return None
        age = time.time() - self.rec["t"]
        return (age, True, self.rec["run"], self.rec["kind"]) if run else (age, True)

    def reply(self, name, prompt):
        if name.startswith(("chunk", "narr_")):
            return dict(THROTTLED)
        return super().reply(name, prompt)

    def test_stops_after_one_wait(self):
        self.write_signals([p10._row(p10._t(13, i * 3), f"Orion-X 측정 로그 {i}번 분석") for i in range(20)])
        rc = self.run_main(5, narrate=True)
        names = [s["name"] for s in self.sent]
        self.assertEqual(names.count("chunk1"), 2)                   # 처음 + 2분 쉬고 한 번
        self.assertFalse([n for n in names if n.startswith(("narr_", "chunk2"))])
        self.assertEqual(self.cool, [120.0])
        aj = self.aj()
        self.assertEqual((aj["aborted"], aj["abort_kind"], aj["cooldowns"]), (True, "throttle", 1))
        self.assertEqual(rc, 3)
        self.assertEqual(self.notes[-1], {"hard": True, "run": "run-A", "kind": "throttle"})

    def test_narrate_skips_when_run_stopped(self):
        self.rec = {"t": time.time() - 3000, "run": "run-A", "kind": "throttle"}   # 50분 전 — 같은 실행이면 나이와 무관
        kept = [{"time": f"2026-{mon:02d}-{1 + i:02d} 10:00", "source": "메일(수신)", "who": "", "model": "Orion-X",
                 "worktype": "개발", "detail": "보정 검토", "judge": "AI", "text": f"Orion-X 보정 {mon}월 {i}번"}
                for mon in (7, 8, 9) for i in range(12)]
        self.assertEqual(judge.narrate(kept, 1.0, p10.TAG), {})
        self.assertEqual([s for s in self.sent if s["name"].startswith("narr_")], [])   # 예전에는 한 번은 보냈다
        self.assertEqual(self.cool, [])


# ── 7) run.py — 한 줄 알림 · 단계 기록 · 재시도 없음 · 자동 보고 보류 ───────────────────────────────────
class _FakePopen:
    pid = 1

    def __init__(self, *a, **k):
        self.stdout = None

    def wait(self, timeout=None):
        return 0


class RunPy(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="lm28_t22u_")
        self.tmp = self._tmp.name
        os.makedirs(os.path.join(self.tmp, "report"))
        self.state = {"stopped": False}
        self.calls, self.held = [], {}
        self._saved_run = dict(R.RUN)
        R.RUN.clear()
        R.RUN.update(stages=[], host="")
        st = self.stack = contextlib.ExitStack()
        st.enter_context(mock.patch.dict(os.environ))
        os.environ.pop("LM_COPILOT_STUB", None)
        st.enter_context(mock.patch.dict(R.REPORT_DIR, {"p": os.path.join(self.tmp, "report")}))
        st.enter_context(mock.patch.dict(R.THR, {"said": False}))
        st.enter_context(mock.patch.object(R, "_RUN_STOPPED", lambda: self.state["stopped"]))
        self.out = io.StringIO()
        st.enter_context(contextlib.redirect_stdout(self.out))

    def tearDown(self):
        self.stack.close()
        R.RUN.clear()
        R.RUN.update(self._saved_run)
        self._tmp.cleanup()

    def stages(self):
        return {s["name"]: s for s in R.RUN["stages"]}

    def test_run_id_and_notes(self):
        rid = R.start_run_id()
        self.assertEqual((os.environ["LM_RUN_ID"], R.RUN["run_id"]), (rid, rid))
        self.assertEqual(R.ai_note(False, "부분 완료"), "부분 완료")
        self.assertEqual(R.ai_note(True, "재시도에도 실패"), R.THR_SKIP)          # 멈춘 뒤에 돈 단계 — 일반 실패 문구가 아니다
        self.state["stopped"] = True
        n1 = R.ai_note(False, "정제 0건")
        self.assertTrue(n1.startswith(R.THR_LINE) and n1.endswith("정제 0건"))
        R.ai_note(False, "")
        self.assertEqual(self.out.getvalue().count(R.THR_LINE), 1)                  # 실행에 한 번
        self.assertIn("1~2시간 뒤 [재분석만]", R.THR_LINE)

    def test_no_retry_when_run_stopped(self):
        self.state["stopped"] = True

        def no_sleep(s):
            raise AssertionError("재시도 대기를 하면 안 된다")
        with mock.patch.object(R, "_run_capture", lambda cmd, env: self.calls.append(cmd) or (1, "실패")), \
                mock.patch.object(R.time, "sleep", no_sleep):
            rc, why = R.run_ai_stage("flow.py", "2026-01-01", "2026-01-31")
        self.assertEqual((rc, len(self.calls)), (1, 1))

    def run_main(self, judge_rc, stop_in):
        """[재분석만]+AI 실행 — 자식 단계는 가짜. stop_in 단계가 끝날 때 '이번 실행은 사용량 제한으로 멈춤' 이 된다."""
        def capture(cmd, env):
            base = os.path.basename(str(cmd[1]))
            self.calls.append(base)
            if base == stop_in:
                self.state["stopped"] = True
            return {"judge.py": (judge_rc, ""), "refine.py": (1, "정제 0건"), "freeze.py": (0, "")}.get(base, (0, ""))

        def ai_stage(script, d0, d1, retry_wait=None, extra=()):
            self.calls.append(script)
            if script == stop_in:
                self.state["stopped"] = True
            return (1, "Copilot 사용량 제한 — 이번 실행은 더 보내지 않음") if self.state["stopped"] else (0, "")

        def team_report(c, d0, d1, built=True, on=None, hold=""):
            self.held["hold"] = hold
            return {"ok": None}
        argv = ["run.py", "--from", "2026-01-01", "--to", "2026-01-31", "--skip-collect", "--ai"]
        with contextlib.ExitStack() as st:
            st.enter_context(mock.patch.object(sys, "argv", argv))
            st.enter_context(mock.patch.object(R, "ROOT", self.tmp))
            st.enter_context(mock.patch.object(R, "cfg", lambda: {"aiTotalBudgetMin": 0, "owner": "시험"}))
            st.enter_context(mock.patch.object(R, "_CHAT_TOTALS", lambda c: None))
            st.enter_context(mock.patch.object(R, "pc_history_gap", lambda *a, **k: (False, "")))
            st.enter_context(mock.patch.object(R, "own_data_empty", lambda d: False))
            st.enter_context(mock.patch.object(R.subprocess, "Popen", _FakePopen))
            st.enter_context(mock.patch.object(R.subprocess, "run", lambda *a, **k: types.SimpleNamespace(
                returncode=0, stdout=b"", stderr=b"")))
            st.enter_context(mock.patch.object(R, "watch_child", lambda *a, **k: ""))
            st.enter_context(mock.patch.object(R.proc, "attach", lambda p: None))
            st.enter_context(mock.patch.object(R.proc, "release", lambda job, pid: None))
            st.enter_context(mock.patch.object(R, "invalidate_ai_outputs", lambda d0, d1: ([], [])))
            st.enter_context(mock.patch.object(R, "_run_capture", capture))
            st.enter_context(mock.patch.object(R, "run_ai_stage", ai_stage))
            st.enter_context(mock.patch.object(R, "_pending_count", lambda: 0))
            st.enter_context(mock.patch.object(R, "team_report_wanted", lambda c: False))
            st.enter_context(mock.patch.object(R, "team_report", team_report))
            return R._main()

    def test_judge_partial_then_later_stages_skipped(self):
        rc = self.run_main(2, "judge.py")
        self.assertEqual(rc, 0)
        sg = self.stages()
        self.assertTrue(sg["AI 판정"]["ok"])
        self.assertIn(R.THR_LINE, sg["AI 판정"]["note"])
        for name in ("AI 정제", "워크플로우 분석"):
            self.assertEqual(sg[name]["note"], R.THR_SKIP, name)       # 일반 실패('정제 0건'·'재시도에도 실패')가 아니다
        self.assertNotIn("Agentic 매칭", sg)                          # LM29 — Agentic 단계 기록이 없다(가짜 성공도 없다)
        self.assertEqual(self.out.getvalue().count(R.THR_LINE), 1)
        self.assertEqual(self.held["hold"], "")                       # 부분 판정 결과는 그대로 자동 보고한다
        self.assertIn("보고서 생성", sg)
        self.assertNotIn("Agentic", self.out.getvalue())
        self.assertNotIn("agentic.py", self.calls)

    def test_judge_empty_holds_report(self):
        rc = self.run_main(3, "judge.py")
        self.assertEqual(rc, 0)
        sg = self.stages()
        self.assertFalse(sg["AI 판정"]["ok"])
        self.assertTrue(sg["AI 판정"]["note"].startswith(R.THR_LINE))
        for name in ("AI 정제", "워크플로우 분석"):
            self.assertEqual(sg[name]["note"], R.THR_SKIP, name)
        self.assertNotIn("Agentic 매칭", sg)
        self.assertEqual(self.calls.count("refine.py"), 0)            # 판정이 빈손이면 예전처럼 뒤 단계는 띄우지 않는다
        self.assertEqual(self.held["hold"], "AI 판정 실패")
        self.assertNotIn("흔한 원인", self.out.getvalue())

    def test_refine_hits_limit(self):
        self.run_main(0, "refine.py")
        sg = self.stages()
        self.assertNotIn(R.THR_LINE, sg["AI 판정"]["note"])
        self.assertTrue(sg["AI 정제"]["note"].startswith(R.THR_LINE))
        self.assertEqual(sg["워크플로우 분석"]["note"], R.THR_SKIP)
        self.assertEqual((self.calls.count("flow.py"), "agentic.py" in self.calls), (1, False))   # 판정 뒤 AI 단계는 워크플로우 하나
        self.assertEqual(self.out.getvalue().count(R.THR_LINE), 1)

    def test_no_throttle_unchanged(self):
        self.run_main(0, "")
        sg = self.stages()
        self.assertTrue(all(R.THR_LINE not in s["note"] and s["note"] != R.THR_SKIP for s in sg.values()))
        self.assertNotIn(R.THR_LINE, self.out.getvalue())


# ── 8) 설정 — 두 설정 파일에 키와 설명 ─────────────────────────────────────────────────
class ConfigKeys(unittest.TestCase):
    def test_both_files(self):
        for fn in ("config.default.json", "config.json"):
            with open(os.path.join(_boot.ROOT, "config", fn), encoding="utf-8-sig") as f:
                o = json.load(f)
            ca_ = o["copilotAuto"]
            self.assertEqual((ca_["throttleWaitSec"], ca_["minGapSec"]), (120, 15), fn)
            desc = o["_copilotAuto_옵션_설명"]
            self.assertIn("요청이 너무 많", desc["throttleWaitSec"])
            self.assertIn("0 이면", desc["minGapSec"])
        self.assertEqual((judge.THROTTLE_WAIT_SEC, ca.DEFAULTS["minGapSec"]), (120, 15))
        self.assertIn("minGapSec", ca.KEEP_FALSY)


if __name__ == "__main__":
    unittest.main()
