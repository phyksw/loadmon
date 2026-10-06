# -*- coding: utf-8 -*-
"""코파일럿 브리지 누수 관문(W1 통합 창): 항목 저장소 커밋(``journal.Store.commit`` — fsync 덧붙이기)과 스텁 전송 왕복
(``StubTransport.roundtrip``)을 반복해도 핸들·스레드·메모리·임시 파일이 반복 수에 비례해 늘지 않는다. 실 Edge·Copilot 0,
가상 시계. 30초 이내."""
from __future__ import annotations

import shutil
import tempfile
import unittest

from lm27.bridge import journal as J
from lm27.bridge import transport_stub as T
from lm27.bridge.clock import VirtualClock
from lm27.bridge.transport import SendRequest
from lm27.paths import Paths
from lm27.util import events
from tests.bridge.fake_cdp import make_prompt
from tests.fixtures.leak import assert_bounded


def setUpModule():
    events.configure(mode="off")


def tearDownModule():
    events.configure(mode="text")


class BridgeLeak(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="lm27t_leakbr_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.paths = Paths(self.tmp + "/root", lad=self.tmp + "/lad")
        self.clk = VirtualClock()

    def test_journal_commits_bounded(self):
        s = J.Store(self.paths, "t_act", self.clk).load()

        def step(i):
            self.clk.advance(1)
            s.commit({"ck": f"{i % 50:024x}", "key": f"k{i % 50}", "by": "ai", "ans": {"x": i}, "final": True,
                      "rid": "R7F3QK"})
        # 같은 ck 50개를 되풀이 — 마지막 커밋 사전(_last)은 50개로 머문다(커밋 수에 비례해 자라면 누수)
        assert_bounded(self, step, warm=60, n=200, mem_per_iter=1024, handle_slack=8)
        self.assertEqual(len(J.Store(self.paths, "t_act", self.clk).load().all_last()), 50)

    def test_stub_roundtrips_bounded(self):
        t = T.StubTransport(lambda prompt, rid, stage: T.build_reply("ok", rid, T.item_ids(prompt),
                                                                     {1: {"act": "info"}}))
        p = make_prompt("R7F3QK", 3)

        def step(_i):
            r = t.roundtrip(SendRequest("R7F3QK", p, False, "빠른 응답", 480, 180, 900, "speech_act", True, ()))
            self.assertTrue(r.body)
            t.sent_texts.clear()                              # 시험용 기록(메모리만) — 실행기가 비우는 것과 같게
            t.requests.clear()
        assert_bounded(self, step, warm=20, n=300, mem_per_iter=512)


if __name__ == "__main__":
    unittest.main()
