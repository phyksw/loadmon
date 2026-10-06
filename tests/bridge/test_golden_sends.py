# -*- coding: utf-8 -*-
"""WP-24 골든 전송 수(B §11.7 · G-B5 · T-04·T-15) — 합성 고정 입력(화행 400 · 이름 300 · 워크플로우 30 · 리뷰 6 · 매칭 40 ·
검토 30)을 무결점 가짜 Copilot 으로 돌린 단계별 전송 수가 ``golden_sends.json`` 대비 +10% 이내. 잡음 시나리오(질의별
partial 10%·truncated 5%·empty 3%·service_error 2%, 결정적 난수)는 합계 ≤ 골든 × 1.35, 2단 전송 비율 ≤ 3%, 모든 항목 커밋
(ai 또는 rule — 남은 rule_pending 0). 잡음 상한은 시드 5개 합계로 본다."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from lm27.util import events

from tests.fixtures.wp24.rig import Rig, act_rows, agent_rows, flow_rows, label_rows, review_rows, sub_rows
from tests.fixtures.wp24.stages import ActStage, AgentStage, FlowStage, LabelStage, ReviewStage, SubStage

GOLDEN = json.loads((Path(__file__).resolve().parent / "golden_sends.json").read_text(encoding="utf-8"))
ROWS = {"t_act": act_rows, "t_label": label_rows, "t_flow": flow_rows, "t_review": review_rows, "t_agent": agent_rows,
        "t_sub": sub_rows}
STAGES = (ActStage, LabelStage, FlowStage, ReviewStage, AgentStage, SubStage)
SEEDS = (11, 23, 37, 41, 53)


def setUpModule():
    events.configure(mode="off")


def _run(spec, *, noise=None, seed=0):
    r = Rig(stages=[spec], noise=noise, seed=seed)
    try:
        r.write_ai_in(spec.id, ROWS[spec.id](GOLDEN["inputs"][spec.id]))
        res = r.run()[spec.id]
        return r.transport.sends, res
    finally:
        r.cleanup()


class Golden(unittest.TestCase):
    def test_clean_sends_within_10pct(self):
        lim = GOLDEN["limits"]["clean_ratio"]
        for cls in STAGES:
            spec = cls()
            sends, res = _run(spec)
            gold = GOLDEN["sends"][spec.id]
            self.assertLessEqual(sends, int(gold * lim), (spec.id, sends, gold))
            self.assertEqual((res["state"], res["items_ai"]), ("done", GOLDEN["inputs"][spec.id]), spec.id)
            self.assertEqual(res["rungs"]["1"] + res["rungs"]["2"], 0, spec.id)

    def test_noise_scenario(self):
        """잡음은 질의마다 결정적 난수로 섞는다 — 전송 수 상한은 시드 5개의 평균(합계)으로 본다(한 시드의 우연한 몰림 제외)."""
        lim = GOLDEN["limits"]
        gold_total = sum(GOLDEN["sends"].values())
        total = rung2 = 0
        for seed in SEEDS:
            for cls in STAGES:
                spec = cls()
                sends, res = _run(spec, noise=GOLDEN["noise"], seed=seed + len(spec.id))
                total += sends
                rung2 += res["rungs"]["2"]
                self.assertEqual(res["items_pending"], 0, (seed, spec.id))
                self.assertEqual(res["items_ai"] + res["items_rule"], GOLDEN["inputs"][spec.id], (seed, spec.id))
        self.assertLessEqual(total, gold_total * lim["noise_ratio"] * len(SEEDS), total)
        self.assertLessEqual(rung2 / total, lim["rung2_ratio"], (rung2, total))


if __name__ == "__main__":
    unittest.main()
