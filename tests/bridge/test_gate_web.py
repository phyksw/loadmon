# -*- coding: utf-8 -*-
"""WP-24 웹 노출 엄격 규칙(B §9.7 · G-B11) — B-T50(S1~S5: 번호 축약·금액+고객사 항목 제외·상대 도메인 미전송·잔여 0) ·
B-T51(다음 호출이 업무 모드 + 웹 근거 끔이면 web_combo 항목만 다시 묻고 번호 토큰을 그대로) · B-T52(policy=block →
모든 단계 skipped(web_exposed), 전송 0, rule_pending, BR-WEB-BLOCK)."""
from __future__ import annotations

import unittest

from lm27.util import events

from tests.fixtures.wp24.rig import RUN2, Rig, act_rows, exposed_env, work_env
from tests.fixtures.wp24.stages import ActStage, LabelStage

RESIDUE = ("[고객사:", "[협력사:", "[사람#", "[이메일@고객사:", "[이메일@협력사:")


def setUpModule():
    events.configure(mode="off")


def _rows():
    """B §11.6 시제품 입력 4개."""
    base = {"kinds": "메일발신 1", "files": [], "apps": [], "domains": [], "cands": []}
    return [
        {"key": "grp:w1", "fields": dict(base, subjects=["[고객사:C01] 2차 미팅 준비"], domains=["@partner.example"])},
        {"key": "grp:w2", "fields": dict(base, subjects=["[고객사:C01] 견적 [금액] 확인 요청"])},
        {"key": "grp:w3", "fields": dict(base, subjects=["[이메일@협력사:V02] 납기 확인"],
                                         files=["[사람#a1b2c3] 검토.xlsx"], domains=["@vendor.example"])},
        {"key": "grp:w4", "fields": dict(base, subjects=["[과제:P0012] 공차 해석 [비율] 개선"])},
    ]


class WebStrict(unittest.TestCase):
    def test_T50_T51_strict_then_relaxed(self):
        r = Rig(stages=[LabelStage()], env=exposed_env())
        self.addCleanup(r.cleanup)
        r.write_ai_in("t_label", _rows())
        res = r.run()["t_label"]
        web = res["gate"]["web"]
        self.assertEqual((web["exposed"], web["combo_drop"], web["id_strip"], web["field_drop"]),
                         (True, 1, 2, {"domains": 2}))
        combo = [c for c in r.store("t_label") if c.get("why") == "gated:web_combo"]
        self.assertEqual([(c["key"], c["confirm"], c["final"]) for c in combo], [("grp:w2", True, True)])
        self.assertEqual(res["items_gated"], 1)
        sent = "\n".join(r.transport.sent_texts)
        for bad in RESIDUE + ("@partner.example", "@vendor.example", "견적"):
            self.assertNotIn(bad, sent)
        self.assertIn("[과제:P0012]", sent)
        self.assertIn("[고객사] 2차 미팅 준비", sent)
        self.assertIn("BR-WEB-STRICT", r.notified())
        # T51: 업무 모드 + 웹 근거 끔이 확인된 다음 호출 — web_combo 항목만 다시, 번호 토큰 그대로
        sends = r.transport.sends
        r.new_runtime(run_id=RUN2, env=work_env())
        res2 = r.run()["t_label"]
        self.assertEqual(r.transport.sends - sends, 1)
        last = r.transport.sent_texts[-1]
        self.assertIn("[고객사:C01] 견적 [금액] 확인 요청", last)
        self.assertEqual(last.count("\n1 | "), 1)
        self.assertNotIn("\n2 | ", last)
        self.assertEqual(res2["counts"]["resume_skipped"], 3)
        self.assertEqual((res2["items_ai"], res2["state"]), (4, "done"))
        self.assertFalse(res2["gate"]["web"]["exposed"])

    def test_web_exposed_prompts_have_no_residue_any_stage(self):
        """G-B11: web_exposed=true 고정 입력으로 만든 모든 프롬프트에 번호 토큰 0."""
        rows = act_rows(6)
        rows[0]["fields"]["text"] = "[고객사:C01] 일정 문의 [사람#0a1b2c]"
        rows[1]["fields"]["text"] = "[이메일@고객사:C01] 회신 요청"
        r = Rig(stages=[ActStage()], env=exposed_env())
        self.addCleanup(r.cleanup)
        r.write_ai_in("t_act", rows)
        r.run()
        for t in r.transport.sent_texts:
            for bad in RESIDUE:
                self.assertNotIn(bad, t)

    def test_T52_policy_block(self):
        r = Rig(stages=[ActStage(), LabelStage()], env=exposed_env(),
                overrides={"bridge.webExposure.policy": "block"})
        self.addCleanup(r.cleanup)
        r.write_ai_in("t_act", act_rows(3))
        r.write_ai_in("t_label", _rows())
        res = r.run()
        self.assertEqual(r.transport.sends, 0)
        for sid in ("t_act", "t_label"):
            self.assertEqual((res[sid]["state"], res[sid]["reason"], res[sid]["rc"]), ("skipped", "web_exposed", 0))
            self.assertEqual({v["by"] for v in r.ai_out(sid)["items"].values()}, {"rule_pending"})
        self.assertIn("BR-WEB-BLOCK", r.notified())


if __name__ == "__main__":
    unittest.main()
