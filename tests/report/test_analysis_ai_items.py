# -*- coding: utf-8 -*-
"""WP-30 코파일럿 단계 입력·반영·폴백(R §4.10 · §2.4.1 · RPT-28 · RPT-29 · 계약 §7.1 `write_ai_items`).

- `write_ai_items(run_id, stage)` → `data\\derived\\ai_in\\<stage>.jsonl`(정규 JSON 한 줄 한 항목) + {stage: 건수}.
- 키: `ws:<role_id>` · `ag:<type>` · `sa:<role_id>` · `review:week:YYYY-Www` · `review:month:YYYY-MM`.
- 시간·MM 은 보내지 않는다(RPT-28): fields 안 `\\d+(\\.\\d+)?\\s*(MM|시간|h|분)` 0건.
- 폴백 한 벌(RPT-29): ai_out 이 없으면 브리지 단계 `fallback()` 결과가 그대로 라벨이 되고 by = rule.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import tempfile
import unittest
from types import SimpleNamespace

from lm27.paths import Paths
from lm27.report.analysis import ai_items as AI
from lm27.report.analysis import analyze
from tests.fixtures.wp30 import world as W

TIME_RX = re.compile(r"\d+(\.\d+)?\s*(MM|시간|h|분)")
RUN_ID = "20261005-101500-3fa2"


def inputs(w):
    f = w.files()
    t = SimpleNamespace(tasks=f["tasks"], attrib=f["attrib"], team_tables=f["tables"], env_slots=f["env_slots"],
                        day_ledger=f["day_ledger"], run_meta=f["run_meta"])
    return SimpleNamespace(run_id=RUN_ID, time=t, labels={"labels": f["labels"]}, ai={}, registry=None,
                           person_dir=None, evidence=None, period=(w.d0, w.d1))


def world():
    w = W.golden_role_a()
    w.labels["u_a1"]["title"] = "전원부 해석 3시간 검토"
    return w


class WriteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="lm27t_wp30_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.paths = Paths(self.tmp, lad=os.path.join(self.tmp, "lad"))

    def read(self, stage):
        with open(self.paths.ai_in(stage), "rb") as f:
            raw = f.read()
        self.assertNotIn(b"\r\n", raw)
        return [json.loads(x) for x in raw.decode("utf-8").splitlines()]

    def test_all_stages(self):
        cnt = AI.write_ai_items(RUN_ID, None, paths=self.paths, cfg=W.cfg(), inputs=inputs(world()), cal=W.calendar())
        self.assertEqual(set(cnt), set(AI.STAGES))
        self.assertEqual(cnt["workflow_label"], 1)
        self.assertEqual(cnt["subagent_review"], 1)
        self.assertEqual(cnt["agentic_match"], 5)
        self.assertEqual(cnt["review_text"], len(self.read("review_text")))
        wl = self.read("workflow_label")[0]
        rid = W.role_id("P-0007", "ELEC", "ANALYSIS")
        self.assertEqual(wl["key"], "ws:" + rid)
        self.assertEqual(wl["group"], "P-0007")
        f = wl["fields"]
        self.assertEqual((f["project"], f["field"], f["func"]), ("P-0007", "ELEC", "ANALYSIS"))
        self.assertEqual(f["steps"], [["S1", "REQ_IN", 4], ["S2", "APP_CAE", 4], ["S3", "DOC_XLS", 4], ["S4", "MEET", 2],
                                      ["S5", "REPORT_OUT", 4]])
        self.assertEqual(f["trans"], [["S2", "S3", 5], ["S1", "S2", 4], ["S3", "S4", 2], ["S3", "S5", 2],
                                      ["S4", "S5", 2], ["S3", "S2", 1]])
        self.assertLessEqual(len(f["tasks"]), 5)
        self.assertIn("전원부 해석 검토", f["tasks"])                          # 시간 숫자 표현을 지운 제목
        self.assertEqual(set(wl), {"key", "group", "fields", "rule", "src_ver", "meta"})
        self.assertEqual(wl["meta"]["priv_class"], "work")
        sa = self.read("subagent_review")[0]
        self.assertEqual(sa["key"], "sa:" + rid)
        for s in sa["fields"]["steps"]:
            self.assertRegex(s[3], r"^D[01] R[01] B[01] L[01] S[01] T[01]$")
        self.assertEqual(sa["fields"]["role"], "회로·해석·분석")
        ag = {x["key"]: x for x in self.read("agentic_match")}
        self.assertIn("ag:DOC_XLS", ag)
        self.assertEqual(set(ag["ag:DOC_XLS"]["fields"]), {"type", "label", "freq", "io", "apps", "ws"})
        rv = self.read("review_text")
        self.assertTrue(any(x["key"] == "review:month:2026-09" for x in rv))
        self.assertTrue(any(x["key"].startswith("review:week:2026-W") for x in rv))
        blob = json.dumps([x["fields"] for st in AI.STAGES for x in self.read(st)], ensure_ascii=False)
        self.assertIsNone(TIME_RX.search(blob), TIME_RX.search(blob))
        cnt2 = AI.write_ai_items(RUN_ID, None, paths=self.paths, cfg=W.cfg(), inputs=inputs(world()),
                                 cal=W.calendar())
        self.assertEqual(cnt, cnt2)

    def test_one_stage(self):
        cnt = AI.write_ai_items(RUN_ID, "review_text", paths=self.paths, cfg=W.cfg(), inputs=inputs(world()),
                                cal=W.calendar())
        self.assertEqual(list(cnt), ["review_text"])
        self.assertFalse(os.path.exists(self.paths.ai_in("workflow_label")))
        with self.assertRaises(ValueError):
            AI.write_ai_items(RUN_ID, "task_label", paths=self.paths, cfg=W.cfg(), inputs=inputs(world()),
                              cal=W.calendar())

    def test_empty(self):
        w = W.World("2026-09-01", "2026-09-30", "2026-09-30T18:00")
        cnt = AI.write_ai_items(RUN_ID, None, paths=self.paths, cfg=W.cfg(), inputs=inputs(w), cal=W.calendar())
        self.assertEqual(sum(cnt.values()), 0)                                 # cli rc 4(할 일 없음)


class FallbackTest(unittest.TestCase):
    """RPT-29 — ai_out 이 없으면 브리지 단계 폴백 한 벌, by = rule. ai_out 이 있으면 그 답."""

    def fake(self, stage, item, ns):
        self.calls.append((stage, item["key"]))
        if stage == "workflow_label":
            return {"role": "판단 보류", "summary": "",
                    "steps": [{"s": s[0], "type": s[1], "label": f"{s[1]}*", "desc": ""} for s in item["fields"]["steps"]]}
        if stage == "review_text":
            return {"summary": "규칙 요약", "highlights": [{"text": "완료", "refs": ["F1"]}], "next": []}
        if stage == "subagent_review":
            return {"verdict": "부분", "orch": "", "subs": [], "risk": ""}
        return None

    def test_fallback_and_ai(self):
        self.calls = []
        ctx = world().context(fallback=self.fake)
        sec = analyze(ctx)
        rw = next(iter(sec["workflows"]["roles"].values()))
        self.assertTrue(all(s["label"] == s["code"] + "*" and s["label_by"] == "rule" for s in rw["steps"]))
        self.assertEqual(rw["ai_role"], "판단 보류")
        self.assertEqual({c[0] for c in self.calls}, {"workflow_label", "subagent_review", "agentic_match",
                                                      "review_text"})
        m = sec["reviews"]["months"][0]
        self.assertEqual((m["ai"]["summary"], m["ai"]["by"]), ("규칙 요약", "rule"))
        self.assertEqual(m["ai"]["highlights"][0]["units"], [m["fact_units"]["F1"]])
        role = sec["subagent"]["roles"][0]
        self.assertEqual((role["ai"]["by"], role["ai"]["verdict"]), ("rule", "부분"))
        self.assertEqual(role["final"], role["rule"])                       # 규칙 답은 최종 판정에 들지 않는다
        self.assertEqual(sec["flags"]["copilot"], "rule_only")
        rid = W.role_id("P-0007", "ELEC", "ANALYSIS")
        ai = {"workflow_label": {"schema": 1, "items": {"ws:" + rid: {"ans": {
            "role": "해석 담당", "summary": "요약", "steps": [{"s": f"S{i}", "type": c, "label": f"L{i}", "desc": "d"}
                                                         for i, c in enumerate(["REQ_IN", "APP_CAE", "DOC_XLS", "MEET",
                                                                                "REPORT_OUT"], 1)]}, "by": "ai"}}}}
        self.calls = []
        sec = analyze(world().context(fallback=self.fake, ai=ai))
        rw = next(iter(sec["workflows"]["roles"].values()))
        self.assertEqual([s["label"] for s in rw["steps"]], ["L1", "L2", "L3", "L4", "L5"])
        self.assertNotIn(("workflow_label", "ws:" + rid), self.calls)
        self.assertEqual(sec["flags"]["copilot"], "partial")

    def test_bridge_fallback_presence(self):
        item = {"key": "ws:r_000000", "fields": {"steps": [["S1", "REQ_IN", 1]]}}
        ans = AI.bridge_fallback("workflow_label", item, SimpleNamespace(registry=None))
        if importlib.util.find_spec("lm27.bridge.stages") is None:
            self.assertIsNone(ans)                       # 브리지 단계 모듈 전(W1b) — 답 없음(단계 한글명 라벨)
        else:
            self.assertTrue(ans is None or isinstance(ans, dict))
        sec = analyze(world().context())
        if importlib.util.find_spec("lm27.bridge.stages") is None:
            self.assertIn("fallback_unavailable", [w["code"] for w in sec["flags"]["warnings"]])


if __name__ == "__main__":
    unittest.main()
