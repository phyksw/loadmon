# -*- coding: utf-8 -*-
"""WP-25 실제 단계 × L3 실행기(스텁 전송·가상 시계·정제 게이트 — 실 Edge 0): 단계별 ai_out 모양(하류 WP-22·30 이 읽는 형) ·
재개(두 번째 실행 전송 0) · task_label 커밋의 reg_set(H §6.6) · review_text 의 peers_map · consolidate 의 same_as_key ·
workflow_label 같은 과제 묶음 · 답에 섞인 개인정보는 저장소·ai_out 에 토큰만(입수 정제 ③ · B-T23) · 부트스트랩 항목형 차단."""
from __future__ import annotations

import unittest

from lm27.bridge.stages import REGISTRY
from lm27.util import events

from tests.core.test_stage_result import check_stage_common
from tests.fixtures.wp24.rig import Rig
from tests.fixtures.wp25 import kit as K


def setUpModule():
    events.configure(mode="off")


def rows_of(stage_id: str, n: int) -> list:
    if stage_id == "task_label":
        return [{"key": f"grp:{i:012x}", "group": "P-0007",
                 "fields": {"kinds": "메일발신 3·문서 1", "subjects": [f"[과제:P-0007] 공차 해석 결과 공유 {i}"],
                            "files": [f"공차해석_{i}.xlsx"], "apps": ["해석 프로그램"], "domains": ["사내"],
                            "cands": [["P-0007", 0.62]], "hint": "OPT/ANALYSIS/DEV", "regv": ""},
                 "rule": {"project": "P-0007", "score": 0.62, "source": "rule_probable", "field": "OPT",
                          "func": "ANALYSIS", "wtype": "DEV", "title": "공차해석", "reg_set": "ab12cd34"}}
                for i in range(n)]
    if stage_id == "workflow_label":
        return [{"key": f"ws:r_{i:06x}", "group": "P-0012" if i % 2 else "P-0007",
                 "fields": {"project": "P-0012" if i % 2 else "P-0007", "field": "OPT", "func": "ANALYSIS",
                            "steps": [["S1", "REQ_IN", 4], ["S2", "APP_CAE", 9]], "trans": [["S1", "S2", 3]],
                            "tasks": [f"공차 해석 {i}"]},
                 "rule": {"func_name": "해석·분석"}} for i in range(n)]
    if stage_id == "review_text":
        return [{"key": f"review:week:2026-W{40 + i}", "fields": {
            "kind": "week", "period": f"2026-W{40 + i}", "facts": [["F1", "완료", "공차 해석", "P-0012", "해석·분석"]],
            "peers": [["동료1", 2]]}, "rule": {"peers_map": {"동료1": "w" + "2" * 16}}} for i in range(n)]
    raise KeyError(stage_id)


class ContentStages(unittest.TestCase):
    def test_task_label_commit_reg_set_and_resume(self):
        spec = REGISTRY["task_label"]
        ans = {"project": "P-0007", "field": "OPT", "func": "ANALYSIS", "wtype": "DEV", "title": "광학 모듈 공차 해석",
               "new": "", "dom": "", "conf": "h"}
        r = Rig(stages=[spec], registry=K.reg(), env=K.work_env(), answer_fn=lambda s, k: dict(ans))
        self.addCleanup(r.cleanup)
        r.write_ai_in("task_label", rows_of("task_label", 5))
        res = r.run()["task_label"]
        self.assertEqual((res["state"], res["items_ai"]), ("done", 5))
        self.assertEqual(check_stage_common(res), [])
        store = r.store("task_label")
        self.assertEqual({c["reg_set"] for c in store}, {"ab12cd34"})          # 과제 목록 해시(H §6.6 · X5)
        self.assertEqual({c["reg"] for c in store}, {"r3"})
        out = r.ai_out("task_label")
        self.assertEqual(out["stage_ver"], "task_label/1.1")
        first = out["items"]["grp:000000000000"]
        self.assertEqual((first["by"], first["ans"]["title"], first["reg_set"]), ("ai", "광학 모듈 공차 해석", "ab12cd34"))
        sends = r.sends()
        r.new_runtime(run_id=K.RUN2)
        res2 = r.run()["task_label"]
        self.assertEqual((r.sends(), res2["state"], res2["counts"]["resume_skipped"]), (sends, "done", 5))

    def test_workflow_groups_and_fill(self):
        spec = REGISTRY["workflow_label"]
        r = Rig(stages=[spec], registry=K.reg(),
                answer_fn=lambda s, k: {"role": "해석 담당", "summary": "의뢰를 받아 해석합니다.",
                                        "steps": [{"s": "S2", "label": "해석 수행", "desc": "해석 프로그램 작업"}]})
        self.addCleanup(r.cleanup)
        r.write_ai_in("workflow_label", rows_of("workflow_label", 4))
        res = r.run()["workflow_label"]
        self.assertEqual(res["state"], "done")
        a = r.ai_out("workflow_label")["items"]["ws:r_000001"]["ans"]
        self.assertEqual([(s["s"], s["type"], s["label"]) for s in a["steps"]],
                         [("S1", "REQ_IN", "의뢰 수신"), ("S2", "APP_CAE", "해석 수행")])
        first = r.transport.sent_texts[0]
        groups = [ln.split(" | ")[1] for ln in first.splitlines() if ln[:2] in ("1 ", "2 ", "3 ", "4 ")]
        self.assertEqual(groups, sorted(groups, key=lambda g: "P-0012" in g))   # 같은 과제끼리 이어서(group_strict)

    def test_review_peers_map_kept(self):
        spec = REGISTRY["review_text"]
        r = Rig(stages=[spec], registry=K.reg(),
                answer_fn=lambda s, k: {"summary": "공차 해석을 마쳤습니다.", "highlights": [{"text": "완료", "refs": ["F1"]}],
                                        "relations": [], "next": []})
        self.addCleanup(r.cleanup)
        r.write_ai_in("review_text", rows_of("review_text", 2))
        res = r.run()["review_text"]
        self.assertEqual((res["state"], res["sends"]), ("done", 2))              # 기간마다 질의 1건(단건형)
        a = r.ai_out("review_text")["items"]["review:week:2026-W40"]["ans"]
        self.assertEqual(a["peers_map"], {"동료1": "w" + "2" * 16})

    def test_consolidate_same_as_key_via_runner(self):
        spec = REGISTRY["taxonomy_consolidate"]
        rows = [{"key": "cs:aaa", "fields": {"name": "방열 모듈", "dom": "DEV", "match": ["방열"]}},
                {"key": "cs:bbb", "fields": {"name": "방열모듈 개발", "dom": "DEV", "match": ["방열"]}}]
        r = Rig(stages=[spec], answer_fn=lambda s, k: {"same_as": 2 if k == "cs:aaa" else 0, "conf": "h"})
        self.addCleanup(r.cleanup)
        r.write_ai_in("taxonomy_consolidate", rows)
        r.run()
        items = r.ai_out("taxonomy_consolidate")["items"]
        self.assertEqual(items["cs:aaa"]["ans"], {"same_as": 2, "conf": "h", "same_as_key": "cs:bbb"})
        self.assertEqual(items["cs:bbb"]["ans"], {"same_as": 0, "conf": "h"})

    def test_answer_pii_sanitized_in_store(self):
        """B-T23: 가짜 Copilot 이 답에 전화번호를 섞어도 저장소·ai_out·저널에는 토큰만(입수 정제 ③)."""
        spec = REGISTRY["review_text"]
        r = Rig(stages=[spec], registry=K.reg(), script={"review_text": ["pii_in_answer"]},
                answer_fn=lambda s, k: {"summary": "공차 해석을 마쳤습니다.", "highlights": [], "relations": [],
                                        "next": []})
        self.addCleanup(r.cleanup)
        r.write_ai_in("review_text", rows_of("review_text", 1))
        r.run()
        raw = b"\n".join(b for _p, b in r.tree_bytes())
        phone = "-".join(("0" + "1" + "0", "7" * 4, "3" * 4)).encode()
        self.assertNotIn(phone, raw)
        self.assertIn("[전화]", r.ai_out("review_text")["items"]["review:week:2026-W40"]["ans"]["summary"])

    def test_bootstrap_item_mode_blocked_not_misassigned(self):
        """단건형 행 봉투를 모르는 L2 에서는 행이 표본에 잘못 커밋되지 않고 규칙 커밋(빈 제안)으로 끝난다."""
        spec = REGISTRY["taxonomy_bootstrap"]
        rows = [{"key": f"grp:{i}", "fields": {"dom": "DEV", "title": f"해석 {i}", "files": [], "subject": "",
                                               "peer": ""}} for i in range(1, 4)]
        model = {"name": "방열 모듈", "code": "", "dom": "DEV", "kind": "project", "match": ["방열"], "obs": [1, 2]}
        r = Rig(stages=[spec], registry=K.reg(), answer_fn=lambda s, k: dict(model))
        self.addCleanup(r.cleanup)
        r.write_ai_in("taxonomy_bootstrap", rows)
        res = r.run()["taxonomy_bootstrap"]
        self.assertEqual(res["items_ai"], 0)
        items = r.ai_out("taxonomy_bootstrap")["items"]
        self.assertTrue(all(v["by"] in ("rule", "rule_pending") for v in items.values()))
        self.assertTrue(all((v["ans"] or {}).get("rows", []) == [] for v in items.values()))


if __name__ == "__main__":
    unittest.main()
