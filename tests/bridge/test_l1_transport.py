# -*- coding: utf-8 -*-
"""WP-23 L1 전송(B §5) — 가짜 CDP·가상 시계로 B-T01~T09 와 회수·주입·전송 확인·새 채팅·오류 경로.

시각 기대값은 시제품 proto_l1 표(B §11.6: 폴 3초, stable 8폴, 첫 글자 유예 180초)를 따른다.
"""
from __future__ import annotations

import os
import unittest

from lm27.bridge.transport import (CdpTransport, SendRequest, build_anchor, echo_pledges, envelope_state, match, norm,
                                   pick_reply, pledge_rx, strip_echo)

from tests.bridge.fake_cdp import ASST_SELECTOR, FakePage, FakeReply, envelope, make_prompt
from tests.bridge.fake_http import World

RID = "R7F3QK"


class L1(unittest.TestCase):
    def rig(self, page=None, overrides=None):
        page = page or {}
        w = World(page_factory=lambda url: FakePage(w.clock, **{"url": url, **page}), overrides=overrides)
        self.addCleanup(w.cleanup)
        s = w.session()
        self.assertEqual(s.start(), "ready")
        self.addCleanup(s.close)
        return w, s, CdpTransport(s), w.net.our_pages()[0]

    def req(self, w, rid=RID, text=None, *, fresh=False, model="", reply=480.0, first=180.0, budget=900.0,
            work=False):
        return SendRequest(rid, text if text is not None else make_prompt(rid, 3), fresh, model, reply, first,
                           w.clock.mono() + budget, "speech_act", work)


class TestScenarios(L1):
    def full(self, n=40, pledge=True):
        return lambda prompt, rid: envelope(rid, n, pledge=pledge)

    def test_T01_stream_with_pledge(self):
        w, s, t, page = self.rig()
        page.replies.append(FakeReply(text=self.full()))
        r = t.roundtrip(self.req(w))
        self.assertEqual((r.phase, r.done_by), ("replied", "pledge"))
        self.assertEqual(len(page.sent_texts), 1)
        self.assertEqual(r.body.strip(), envelope(RID, 40))
        self.assertTrue(25 <= r.gen_sec <= 40, r.gen_sec)
        self.assertTrue(r.busy_seen)
        self.assertIsNotNone(r.first_token_sec)

    def test_T02_long_think_button_mismatch(self):
        w, s, t, page = self.rig()
        page.replies.append(FakeReply(text=self.full(), think_s=150, button=False))
        r = t.roundtrip(self.req(w))
        self.assertEqual((r.phase, r.done_by), ("replied", "pledge"))
        self.assertTrue(170 <= r.gen_sec <= 185, r.gen_sec)
        self.assertFalse(r.busy_seen)

    def test_T03_think_without_output(self):
        w, s, t, page = self.rig()
        page.replies.append(FakeReply(text=self.full(), think_s=600, button=False))
        r = t.roundtrip(self.req(w))
        self.assertEqual(r.phase, "empty_reply")
        self.assertTrue(180 <= r.gen_sec <= 184, r.gen_sec)
        r1 = w.cfg.rung_timeouts(1)                           # 사다리 1단의 첫 글자 유예 = 90초(L2 몫, 공식은 한 벌)
        page.replies.append(FakeReply(text=self.full(), think_s=600, button=False))
        r2 = t.roundtrip(self.req(w, "R7F3QM", reply=r1[0], first=r1[1]))
        self.assertEqual(r2.phase, "empty_reply")
        self.assertTrue(90 <= r2.gen_sec <= 94, r2.gen_sec)

    def test_T04_no_pledge_complete_json_idle(self):
        w, s, t, page = self.rig()
        page.replies.append(FakeReply(text=self.full(pledge=False), think_s=10))
        r = t.roundtrip(self.req(w))
        self.assertEqual((r.phase, r.done_by), ("replied", "idle_json"))
        self.assertLess(r.gen_sec, 50)
        self.assertEqual(r.body.strip(), envelope(RID, 40, pledge=False))

    def test_T05_pause_30s_button_hidden_waits_pledge(self):
        w, s, t, page = self.rig()
        full = envelope(RID, 40)
        page.replies.append(FakeReply(text=full, pauses=((len(full) // 2, 30, False),)))
        r = t.roundtrip(self.req(w))
        self.assertEqual((r.phase, r.done_by), ("replied", "pledge"))
        self.assertEqual(r.body.strip(), full)
        self.assertTrue(55 <= r.gen_sec <= 70, r.gen_sec)

    def test_T05b_pause_30s_button_visible(self):
        w, s, t, page = self.rig()
        full = envelope(RID, 40)
        page.replies.append(FakeReply(text=full, pauses=((len(full) // 2, 30, True),)))
        r = t.roundtrip(self.req(w))
        self.assertEqual((r.phase, r.done_by), ("replied", "pledge"))

    def test_T06_pause_60s_hidden_stable_early(self):
        w, s, t, page = self.rig()
        full = envelope(RID, 40)
        page.replies.append(FakeReply(text=full, pauses=((len(full) // 2, 60, False),)))
        r = t.roundtrip(self.req(w))
        self.assertEqual((r.phase, r.done_by), ("replied", "stable"))
        b = r.body.strip()
        self.assertTrue(0 < len(b) < len(full))
        self.assertTrue(full.startswith(b))
        self.assertEqual(envelope_state(b, RID), (True, False))   # L2 가 truncated 로 분류할 재료

    def test_T07_no_pledge_button_mismatch_stable(self):
        w, s, t, page = self.rig()
        page.replies.append(FakeReply(text=self.full(pledge=False), think_s=10, button=False))
        r = t.roundtrip(self.req(w))
        self.assertEqual((r.phase, r.done_by), ("replied", "stable"))
        self.assertEqual(r.body.strip(), envelope(RID, 40, pledge=False))
        self.assertTrue(50 <= r.gen_sec <= 70, r.gen_sec)

    def test_T08_input_overflow_not_sent(self):
        w, s, t, page = self.rig({"input_limit": 9000})
        text = make_prompt(RID, 3, filler=10500)
        self.assertGreater(len(text), 10000)
        r = t.roundtrip(self.req(w, text=text))
        self.assertEqual(r.phase, "input_overflow")
        self.assertTrue(8990 <= r.injected_chars <= 9000, r.injected_chars)
        self.assertEqual(r.in_chars, len(norm(text)))
        self.assertEqual(page.sent_texts, [])
        self.assertEqual(page.editor, "")

    def test_T09_first_click_swallowed_resend(self):
        w, s, t, page = self.rig({"swallow_sends": 1})
        page.replies.append(FakeReply(text=self.full(10)))
        r = t.roundtrip(self.req(w))
        self.assertEqual((r.phase, r.done_by, r.resent), ("replied", "pledge", True))
        self.assertEqual(page.clicks.count("send_swallowed"), 1)
        self.assertEqual(len(page.sent_texts), 1)


class TestRetrieval(L1):
    def test_dom_path_with_configured_selector(self):
        w, s, t, page = self.rig(overrides={"bridge.dom.assistantSelectors": [ASST_SELECTOR]})
        page.replies.append(FakeReply(text=lambda p, rid: envelope(rid, 5)))
        r = t.roundtrip(self.req(w))
        self.assertEqual((r.phase, r.pick, r.done_by), ("replied", "dom", "pledge"))
        self.assertEqual(r.body, envelope(RID, 5))

    def test_learn_selector_then_dom(self):
        w, s, t, page = self.rig()
        page.replies.append(FakeReply(text=lambda p, rid: envelope(rid, 5)))
        r1 = t.roundtrip(self.req(w))
        self.assertEqual(r1.pick, "anchor")
        dom = s.profile.load()["dom"]
        self.assertEqual((dom["assistant_sel"], dom["verified"]), (ASST_SELECTOR, 1))
        page.replies.append(FakeReply(text=lambda p, rid: envelope(rid, 5)))
        r2 = t.roundtrip(self.req(w, "R7F3QM", make_prompt("R7F3QM")))
        self.assertEqual((r2.pick, r2.done_by), ("dom", "pledge"))
        self.assertEqual(s.profile.load()["dom"]["verified"], 2)

    def test_learned_selector_failures_cleared(self):
        w, s, t, page = self.rig({"assistant_dom": False})
        s.profile.update(lambda d: d.__setitem__("dom", {"assistant_sel": "div.wrong", "verified": 3, "failures": 0}))
        for i, rid in enumerate(("R7F3QA", "R7F3QB")):
            page.replies.append(FakeReply(text=lambda p, r: envelope(r, 3)))
            res = t.roundtrip(self.req(w, rid, make_prompt(rid)))
            self.assertEqual((res.phase, res.done_by), ("replied", "pledge"))
            self.assertNotEqual(res.pick, "dom")
            if i == 0:
                self.assertEqual(s.profile.load()["dom"]["failures"], 1)
        self.assertEqual(s.profile.load()["dom"], {})            # 2회 누적 → 지우고 다시 학습

    def test_anchor_excludes_echo_pledge(self):
        w, s, t, page = self.rig()
        page.replies.append(FakeReply(text="", think_s=10 ** 6, button=False))
        r = t.roundtrip(self.req(w, reply=60.0, first=180.0))
        self.assertEqual(r.phase, "no_reply")                    # 프롬프트 에코의 서약을 답으로 오인하지 않는다
        self.assertEqual(r.done_by, "")

    def test_no_reply_keeps_partial_body(self):
        w, s, t, page = self.rig()
        page.replies.append(FakeReply(text=lambda p, rid: envelope(rid, 40), cps=1))
        r = t.roundtrip(self.req(w))
        self.assertEqual(r.phase, "no_reply")
        self.assertTrue(r.body.strip())
        self.assertTrue(478 <= r.gen_sec <= 483, r.gen_sec)

    def test_deadline_caps_wait(self):
        w, s, t, page = self.rig()
        page.replies.append(FakeReply(text="", think_s=10 ** 6))
        t0 = w.clock.mono()
        r = t.roundtrip(self.req(w, budget=60.0))
        self.assertEqual(r.phase, "no_reply")
        self.assertLessEqual(w.clock.mono() - t0, 66)

    def test_cut_reply_returned_as_is(self):
        w, s, t, page = self.rig()
        page.replies.append(FakeReply(text=lambda p, rid: envelope(rid, 40), cut_at=300))
        r = t.roundtrip(self.req(w))
        self.assertEqual(r.phase, "replied")
        self.assertIn("stopped generating", r.body)


class TestInjectAndSend(L1):
    def test_inject_mismatch_not_sent(self):
        w, s, t, page = self.rig({"editor_filter": lambda x: x[:-40] + "#" * 40 if len(x) > 40 else x})
        r = t.roundtrip(self.req(w))
        self.assertEqual(r.phase, "inject_mismatch")
        self.assertEqual((page.sent_texts, page.editor), ([], ""))

    def test_insert_fallback(self):
        w, s, t, page = self.rig({"insert_text_works": False})
        page.replies.append(FakeReply(text=lambda p, rid: envelope(rid, 3)))
        r = t.roundtrip(self.req(w))
        self.assertEqual(r.phase, "replied")
        self.assertIn("insert_fallback", page.evals)

    def test_enter_when_no_send_button(self):
        w, s, t, page = self.rig({"send_button": False})
        page.replies.append(FakeReply(text=lambda p, rid: envelope(rid, 3)))
        r = t.roundtrip(self.req(w))
        self.assertEqual(r.phase, "replied")
        self.assertIn("enter", page.clicks)

    def test_send_failed(self):
        w, s, t, page = self.rig({"swallow_sends": 5})
        r = t.roundtrip(self.req(w))
        self.assertEqual((r.phase, r.resent), ("send_failed", True))
        self.assertEqual((page.sent_texts, page.editor), ([], ""))

    def test_busy_before_send(self):
        w, s, t, page = self.rig()
        page.replies.append(FakeReply(text="x", think_s=10 ** 6, button=True))
        r1 = t.roundtrip(self.req(w))
        self.assertEqual(r1.phase, "no_reply")
        r2 = t.roundtrip(self.req(w, "R7F3QM", make_prompt("R7F3QM")))
        self.assertEqual(r2.phase, "busy_before_send")
        self.assertTrue(44 <= r2.waited_idle_sec <= 47, r2.waited_idle_sec)
        self.assertEqual(len(page.sent_texts), 1)


class TestChatModelMode(L1):
    def test_fresh_new_chat(self):
        w, s, t, page = self.rig()
        page.replies.append(FakeReply(text=lambda p, rid: envelope(rid, 3)))
        r = t.roundtrip(self.req(w, fresh=True))
        self.assertEqual((r.phase, r.chat_seq), ("replied", 1))
        self.assertIn("new_chat", page.clicks)

    def test_new_chat_url_fallback(self):
        w, s, t, page = self.rig({"new_chat_button": False})
        self.assertFalse(t.new_chat())
        self.assertEqual(s.info.chat_seq, 1)
        self.assertIn("Page.navigate", page.calls)

    def test_model_and_work_mode(self):
        w, s, t, page = self.rig({"work_mode": "web", "work_switch_ok": False})
        page.work_switch_ok = True
        page.work_mode = "web"
        page.replies.append(FakeReply(text=lambda p, rid: envelope(rid, 3)))
        r = t.roundtrip(self.req(w, model="깊이 생각하기", work=True))
        self.assertEqual((r.phase, r.model_used, r.work_mode), ("replied", "깊이 생각하기", "work"))
        self.assertEqual(page.model_current, "깊이 생각하기")


class TestSessionFailures(L1):
    def test_reconnect_on_poll_timeout(self):
        w, s, t, page = self.rig()
        s.cdp.timeout_on.add("poll")
        page.replies.append(FakeReply(text=lambda p, rid: envelope(rid, 3)))
        r = t.roundtrip(self.req(w))
        self.assertEqual(r.phase, "replied")
        self.assertEqual(s.cdp.reconnects, 1)

    def test_tab_lost(self):
        w, s, t, page = self.rig()
        w.net.json(s.info.port, f"/json/close/{s.info.target_id}")
        r = t.roundtrip(self.req(w))
        self.assertEqual(r.phase, "tab_lost")

    def test_login_expired_midrun(self):
        w, s, t, page = self.rig()
        page.login_until_s = w.clock.mono() + 10 ** 6
        r = t.roundtrip(self.req(w, budget=10 ** 5))
        self.assertEqual(r.phase, "login_required")
        self.assertEqual(page.sent_texts, [])

    def test_open_returns_session_state(self):
        w, s, t, page = self.rig()
        self.assertEqual(t.open(), "ready")
        self.assertEqual(t.kind, "cdp")

    def test_no_raw_text_on_disk(self):
        w, s, t, page = self.rig()
        marker = "카나리아원문표식ZQ"
        page.replies.append(FakeReply(text=lambda p, rid: envelope(rid, 3, note=marker)))
        text = make_prompt(RID, 3).replace("각 메시지", marker + " 각 메시지")
        r = t.roundtrip(self.req(w, text=text))
        self.assertEqual(r.phase, "replied")
        s.close()
        for dp, _dn, fns in os.walk(w.tmp):
            for fn in fns:
                with open(os.path.join(dp, fn), "rb") as fh:
                    self.assertNotIn(marker.encode("utf-8"), fh.read(), fn)


class TestPureTools(unittest.TestCase):
    def test_norm_and_match(self):
        self.assertEqual(norm(" a\r\n b  c​ "), "a b c")
        want = "가" * 100
        self.assertTrue(match(want[:-1] + "가", want))
        self.assertTrue(match(want[:-2], want))                 # 길이 차 2 까지는 허용
        self.assertFalse(match(want[:-3], want))
        self.assertFalse(match(want[:50], want))
        self.assertFalse(match(want[:-1] + "나", want))

    def test_envelope_state(self):
        self.assertEqual(envelope_state('```json\n{"rid":"R7F3QK","n":1,"items":[]}\n```', RID), (True, True))
        self.assertEqual(envelope_state('{"rid":"R7F3QK","n":1,"items":[{"id":1', RID), (True, False))
        self.assertEqual(envelope_state('{"rid":"R2AAAA","n":0,"items":[]}', RID), (True, False))
        self.assertEqual(envelope_state("그냥 글", RID), (False, False))

    def test_pledge_forms(self):
        rx = pledge_rx(RID)
        self.assertTrue(rx.search("x\n[[END R7F3QK]]"))
        self.assertTrue(rx.search("<< END R7F3QK >>"))
        self.assertFalse(rx.search("[[END R7F3QM]]"))

    def test_anchor_pick_strip(self):
        prompt = make_prompt(RID, 3)
        anchor = build_anchor(prompt)
        self.assertTrue(anchor and "\n" not in anchor and len(anchor) <= 100)
        page = "인사말\n" + prompt + "\n" + "답글"
        new, how = pick_reply(page, 0, anchor)
        self.assertEqual(how, "anchor")
        self.assertEqual(strip_echo(new, prompt, anchor, how).strip(), "답글")
        self.assertEqual(echo_pledges(prompt, anchor, how, RID) + 0, len(pledge_rx(RID).findall(new)))
        self.assertEqual(pick_reply("짧은 글", 100, ""), ("짧은 글", "fulltext"))
        self.assertEqual(pick_reply("0123456789", 4, ""), ("456789", "offset"))
        self.assertEqual(build_anchor("짧음"), "")


if __name__ == "__main__":
    unittest.main()
