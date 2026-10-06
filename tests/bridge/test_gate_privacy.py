# -*- coding: utf-8 -*-
"""WP-24 개인정보 게이트 연결(B §9) — B-T23(답의 전화·이름 → 토큰만, answer_hits) · B-T24(ai_in 카나리아 → 프롬프트·
파일 어디에도 0, gated:pii:* 규칙 커밋, 재질의 없음) · B-T25(머리말의 전화번호 → 프롬프트 게이트 실패, 전송 0, 단계 중지
gate, BR-GATE-BLOCKED) · G-B6/T-07(프롬프트·저널·저장소·ai_out·결과 봉투·감사 카나리아 0)."""
from __future__ import annotations

import unittest

from lm27.privacy.detect import SanitizeContext
from lm27.util import events

from tests.fixtures.canary import canaries, find_canaries, text_canaries
from tests.fixtures.wp24.rig import RUN2, Rig, act_rows, flow_rows, label_rows
from tests.fixtures.wp24.stages import ActStage, FlowStage, LabelStage


def setUpModule():
    events.configure(mode="off")


def _phone() -> str:
    return "-".join(("0" + "1" + "0", "7" * 4, "3" * 4))               # 합성 전화번호 — 런타임 조립


class AnswerIngest(unittest.TestCase):
    def test_T23_answer_pii_becomes_tokens(self):
        sctx = SanitizeContext(persons={"홍길동": "c0ffee" + "0" * 10})
        r = Rig(stages=[FlowStage()], script={"t_flow": ["pii_in_answer", "ok"]}, sctx=sctx)
        self.addCleanup(r.cleanup)
        r.write_ai_in("t_flow", flow_rows(3))
        res = r.run()["t_flow"]
        self.assertEqual(res["items_ai"], 3)
        self.assertGreaterEqual(res["gate"]["answer_hits"].get("phone", 0), 1)
        roles = [c["ans"]["role"] for c in r.store("t_flow")]
        self.assertTrue(any("[전화]" in x for x in roles), roles)
        for rel, data in r.tree_bytes():
            if "ai_in" in rel:
                continue
            self.assertNotIn(_phone().encode(), data, rel)
            self.assertNotIn("홍길동".encode(), data, rel)


class _PhoneHeader(LabelStage):
    def header(self, ctx, compact=False):
        return super().header(ctx, compact) + f"\nP-0012 · 문의 {_phone()} 로 연락"


class PromptGate(unittest.TestCase):
    def test_T25_header_pii_blocks_stage(self):
        r = Rig(stages=[_PhoneHeader()])
        self.addCleanup(r.cleanup)
        r.write_ai_in("t_label", label_rows(4))
        res = r.run()["t_label"]
        self.assertEqual(r.transport.sends, 0)
        self.assertEqual((res["stop_kind"], res["resumable"], res["reason"], res["state"]),
                         ("gate", False, "gate_blocked", "failed"))
        self.assertEqual(res["gate"]["prompt_blocked"], 1)
        self.assertIn("BR-GATE-BLOCKED", r.notified())
        gb = [j for j in r.journal("t_label") if j["t"] == "gate_blocked"]
        self.assertEqual(gb[0]["counts"], {"phone": 1})
        self.assertEqual({v["by"] for v in r.ai_out("t_label")["items"].values()}, {"rule_pending"})
        for rel, data in r.tree_bytes():
            self.assertNotIn(_phone().encode(), data, rel)


class Canaries(unittest.TestCase):
    def test_T24_canaries_never_leave(self):
        cs = text_canaries(canaries(groups=("pii",), weak=False))
        self.assertGreater(len(cs), 10)
        rows = act_rows(len(cs) + 5)
        for row, c in zip(rows, cs, strict=False):
            row["fields"]["text"] = c.sentence
        r = Rig(stages=[ActStage()])
        self.addCleanup(r.cleanup)
        r.write_ai_in("t_act", rows)
        res = r.run()["t_act"]
        gated = [c for c in r.store("t_act") if str(c.get("why", "")).startswith("gated:pii:")]
        self.assertGreater(len(gated), 0)
        self.assertTrue(all(c["confirm"] and c["final"] and c["by"] == "rule" for c in gated))
        self.assertEqual(res["items_gated"], len(gated))
        for t in r.transport.sent_texts:
            self.assertEqual(find_canaries(t.encode("utf-8"), cs), [])
        for rel, data in r.tree_bytes():
            if "ai_in" in rel:
                continue
            self.assertEqual(find_canaries(data, cs), [], rel)
        sends = r.transport.sends
        r.new_runtime(run_id=RUN2)
        r.run()
        self.assertEqual(r.transport.sends, sends)                    # 게이트 제외 항목은 다시 묻지 않는다
        self.assertIn("BR-GATE", r.notified())
        audit = [d for rel, d in r.tree_bytes() if "privacy_audit" in rel]
        self.assertTrue(audit)
        self.assertTrue(all(b'"stage":"copilot:t_act"' in d for d in audit))


class RawCapture(unittest.TestCase):
    def test_rawcap_only_gate_passed_text_with_ttl(self):
        """B §9.5: 원문 캡처(bridge.rawCapture — 기본 꺼짐)는 ② 통과 프롬프트 + ③ 입수 정제한 답만, UTF-8 BOM + CRLF, TTL."""
        from pathlib import Path

        from lm27.bridge import fsio
        r = Rig(stages=[FlowStage()], script={"t_flow": ["pii_in_answer"]}, overrides={"bridge.rawCapture": True})
        self.addCleanup(r.cleanup)
        r.write_ai_in("t_flow", flow_rows(2))
        r.run()
        files = list(Path(fsio.bridge_file(r.paths, "rawcap")).glob("*.txt"))
        self.assertEqual(len(files), 1)
        raw = files[0].read_bytes()
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
        text = raw.decode("utf-8-sig")
        self.assertIn("[LM27 요청 ", text)
        self.assertIn("[전화]", text)
        self.assertNotIn(_phone(), text)
        r2 = Rig(stages=[FlowStage()])
        self.addCleanup(r2.cleanup)
        r2.write_ai_in("t_flow", flow_rows(1))
        r2.run()
        self.assertFalse(Path(fsio.bridge_file(r2.paths, "rawcap")).exists())        # 기본 꺼짐


class RidGuard(unittest.TestCase):
    def test_rid_never_looks_like_pii(self):
        """우연히 통화 코드 + 숫자 모양(``RMB`` + 숫자 → 금액)인 rid 는 프롬프트 게이트를 멈추므로 뽑지 않는다."""
        from lm27.bridge import exchange as X
        r = Rig(stages=[ActStage()])
        self.addCleanup(r.cleanup)
        sg = r.gate_base().for_stage("t_act", web_exposed=False)
        self.assertFalse(sg.rid_ok("RMB85F"))
        self.assertTrue(sg.rid_ok("R7F3QK"))
        used = set()
        rids = [X.new_rid(used, sg.rid_ok) for _ in range(3000)]
        self.assertFalse([x for x in rids if x.startswith("RMB") and x[3].isdigit()])
        self.assertEqual(len(set(rids)), 3000)


if __name__ == "__main__":
    unittest.main()
