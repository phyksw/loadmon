# -*- coding: utf-8 -*-
"""WP-24 예산 한 벌(B §7.2 · §7.12) — 호출·단계 마감(최소 몫·마지막 몫) · 패킹 예산 범위(레지스트리 원천) · 실행 중 적응 ·
truncated(input) 재패킹(B-T08 의 L3 몫: 입력 예산 = 확인 글자 × calibSafety)."""
from __future__ import annotations

import tempfile
import unittest

from lm27.bridge import budget as BG
from lm27.bridge.clock import VirtualClock
from lm27.bridge.session import BridgeProfile
from lm27.bridge.transport import SendResult
from lm27.bridge.transport_stub import StubTransport
from lm27.config import registry_meta
from lm27.paths import Paths
from lm27.util import events

from tests.fixtures.wp24.rig import Rig, act_rows, settings
from tests.fixtures.wp24.stages import ActStage

MIN = 60.0


def setUpModule():
    events.configure(mode="off")


class Deadlines(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="lm27t_wp24_")
        self.cfg, _ = settings(self.tmp)
        self.clk = VirtualClock()

    def test_plan_reserve_and_floor(self):
        plan = BG.call_plan(self.cfg, self.clk, 3)
        self.assertEqual(plan.total_dl, self.cfg.total_budget_min * MIN)
        self.assertEqual(plan.reserve_last, self.cfg.final_reserve_min * MIN)
        dl0 = BG.stage_deadline(plan, 0, 3, self.cfg, self.clk)
        self.assertEqual(dl0, self.cfg.stage_budget_min * MIN)
        self.clk.advance((self.cfg.total_budget_min - 20) * MIN)            # 앞 단계가 거의 다 씀
        dl1 = BG.stage_deadline(plan, 1, 3, self.cfg, self.clk)
        self.assertEqual(dl1, self.clk.mono() + self.cfg.stage_floor_min * MIN)   # 최소 몫 보장
        dl2 = BG.stage_deadline(plan, 2, 3, self.cfg, self.clk)
        self.assertEqual(dl2, max(plan.total_dl, self.clk.mono() + self.cfg.stage_floor_min * MIN))

    def test_single_stage_no_reserve_and_off(self):
        self.assertEqual(BG.call_plan(self.cfg, self.clk, 1).reserve_last, 0.0)
        cfg = self.cfg.replace(total_budget_min=0, stage_budget_min=0)
        plan = BG.call_plan(cfg, self.clk, 2)
        self.assertEqual(BG.stage_deadline(plan, 0, 2, cfg, self.clk), float("inf"))

    def test_can_ask(self):
        dl = self.clk.mono() + self.cfg.min_ask_sec
        self.assertTrue(BG.can_ask(dl, self.cfg, self.clk))
        self.clk.advance(1)
        self.assertFalse(BG.can_ask(dl, self.cfg, self.clk))


class Packing(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="lm27t_wp24_")
        self.cfg, _ = settings(self.tmp)

    def test_bounds_from_registry(self):
        (ilo, ihi), (olo, ohi) = BG.pack_bounds()
        self.assertEqual((ilo, ihi), (registry_meta("bridge.inputMaxChars").range["min"],
                                      registry_meta("bridge.inputMaxChars").range["max"]))
        self.assertEqual((olo, ohi), (registry_meta("bridge.answerMaxChars").range["min"],
                                      registry_meta("bridge.answerMaxChars").range["max"]))

    def test_initial_pack(self):
        self.assertEqual(BG.initial_pack(self.cfg), (self.cfg.input_max_chars, self.cfg.answer_max_chars))
        (ilo, ihi), (olo, ohi) = BG.pack_bounds()
        self.assertEqual(BG.initial_pack(self.cfg, {"pack_in": ihi * 3, "pack_out": 1}), (ihi, olo))
        self.assertEqual(BG.initial_pack(self.cfg, None, 0.8)[1], int(self.cfg.answer_max_chars * 0.8))

    def test_shrinks(self):
        self.assertEqual(BG.shrink_in(9000, self.cfg), int(9000 * self.cfg.calib_safety))    # B-T08 → 7,650
        (ilo, _), (olo, _) = BG.pack_bounds()
        self.assertEqual(BG.shrink_in(100, self.cfg), ilo)
        self.assertEqual(BG.shrink_out(self.cfg.answer_max_chars), int(self.cfg.answer_max_chars * 0.8))
        self.assertEqual(BG.shrink_out(olo + 1), olo)

    def test_adjust_profile(self):
        p = Paths(self.tmp + "/root", lad=self.tmp + "/lad")
        a = BG.Adjust(BridgeProfile(p), VirtualClock())
        self.assertEqual(a.factor("t_act"), 1.0)
        self.assertEqual(a.shrink("t_act"), 0.8)
        self.assertEqual(a.shrink("t_act"), 0.64)
        self.assertEqual(a.recover("t_act"), 0.74)
        self.assertEqual(BridgeProfile(p).load()["runtime_adjust"]["t_act"]["pack_out_factor"], 0.74)


class _Overflow(StubTransport):
    """첫 전송은 입력 한도에서 꼬리가 잘림(9,000자 확인) — 보내지 않음."""

    def roundtrip(self, req):
        if not self.requests:
            self.requests.append(req)
            self.sends += 1
            return SendResult(phase="input_overflow", in_chars=len(req.text), injected_chars=9000)
        return super().roundtrip(req)


class InputOverflow(unittest.TestCase):
    def test_T08_repack_with_lower_input_budget(self):
        r = Rig(stages=[ActStage()])
        self.addCleanup(r.cleanup)
        r.new_runtime(transport=_Overflow(r.responder))
        r.write_ai_in("t_act", act_rows(30))
        res = r.run()["t_act"]
        self.assertEqual(res["pack"]["in"], int(9000 * r.cfg.calib_safety))
        self.assertEqual(res["statuses"].get("truncated"), 1)
        self.assertEqual(res["counts"].get("rung_skipped", 0), 0)
        self.assertEqual((res["items_ai"], res["state"]), (30, "done"))
        self.assertTrue(all(len(t) <= res["pack"]["in"] for t in r.transport.sent_texts))
        stored = {c["key"]: c["asks"] for c in r.store("t_act")}
        self.assertEqual(set(stored.values()), {1})                       # 입력 잘림은 질문 횟수에 넣지 않는다


if __name__ == "__main__":
    unittest.main()
