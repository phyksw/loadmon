# -*- coding: utf-8 -*-
"""WP-32 브리지 하위 프로세스 연결(B §2.3 — 호출 1회 = 프로세스 1개) — %TEMP% 복제 트리에서 실제
``lm27_cli.py bridge run --run-id <분석 run_id> --stages … --events jsonl`` 을 **스텁 전송**(``LM_COPILOT_STUB`` — 계약 §11.3,
코파일럿·브라우저 접속 없음)으로 띄워 분석 파이프라인이 끝까지 잇는지 본다: 감시(lm27.collect.watch) · 결과 이벤트 요약 ·
ai_out 반영(화행 다시 붙이기) · 다른 단계 스위치 꺼짐. 자식 프로세스는 복제 안 %LOCALAPPDATA%·%TEMP% 만 쓴다."""
import json
import unittest

from tests.fixtures.tree import CloneTestCase

CHILD = r'''
import json, sys
ROOT = sys.argv[1]
sys.path.insert(0, ROOT)
from pathlib import Path
from lm27.config import load_config
from lm27.util import events
from tests.fixtures.wp32 import world as W
w = W.World.__new__(W.World)
w.root, w.lad, w.runs = Path(ROOT), None, []
w.paths = W.TPaths(ROOT)
(w.root / "data").mkdir(exist_ok=True)
w.put(W.rows())
w.keyring()
events.configure("off")
from lm27.pipeline.analyze import analyze, last_result
rc = analyze(w.paths, load_config(w.paths), from_=W.D0, to=W.D1, as_of=W.AS_OF, ai=True, now=W.NOW,
             team_client=None, copilot_role=True)
lr = last_result()
st = json.loads(w.paths.run_status_file(lr["run_id"]).read_text(encoding="utf-8"))
out = json.loads(w.paths.ai_out("speech_act").read_text(encoding="utf-8")) if w.paths.ai_out("speech_act").is_file() else None
sys.stdout.write("\nRESULT " + json.dumps({"rc": rc, "status": st, "ai_out": out}, ensure_ascii=False) + "\n")
'''

ONLY_SPEECH = {"lookup_mail": False, "lookup_teams": False, "lookup_calendar": False, "speech_act": True,
               "task_label": False, "taxonomy_bootstrap": False, "taxonomy_consolidate": False,
               "workflow_label": False, "review_text": False, "agentic_match": False, "subagent_review": False}


class RealBridgeProcessTest(CloneTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        c = cls.clone
        (c.path("config") / "config.json").write_text(json.dumps({"bridge.stages": ONLY_SPEECH}), encoding="utf-8")
        stub = c.temp / "copilot_stub"
        stub.mkdir(parents=True, exist_ok=True)
        (stub / "speech_act.json").write_text(json.dumps({"mode": ["ok"], "default": {"act": "request",
                                                                                     "conf": "h"}}),
                                              encoding="utf-8")
        script = c.temp / "wp32_child.py"
        script.write_text(CHILD, encoding="utf-8")
        r = c.run_py([script, c.root], env=c.env(LM_COPILOT_STUB=str(stub), LM_NO_BROWSER="1"), timeout=900)
        cls.exit = r.returncode
        cls.err = r.stderr.decode("utf-8", "replace")[-2000:]
        line = next((x for x in r.stdout.decode("utf-8", "replace").splitlines()[::-1] if x.startswith("RESULT ")), "")
        cls.res = json.loads(line[len("RESULT "):]) if line else None

    def by(self) -> dict:
        return {s["id"]: s for s in self.res["status"]["stages"]}

    def test_child_ran(self):
        self.assertEqual(self.exit, 0, self.err)
        self.assertIsNotNone(self.res, self.err)

    def test_speech_act_round_trip(self):
        if self.res is None:
            self.skipTest("자식 실행 실패 — test_child_ran 참고")
        nz = self.by()["normalize"]
        if nz["counts"].get("speech_act_items", 0) == 0:
            self.skipTest("합성 자료에 화행 회색 지대가 없음")
        self.assertEqual((nz["state"], nz["speech_act"], nz["bridge_rc"]), ("done", "done", 0), nz)
        self.assertEqual(self.res["rc"], 0)
        out = self.res["ai_out"]
        self.assertEqual(out["run_id"], self.res["status"]["run_id"], "브리지 실행 = 분석 실행(run_id 공유)")
        self.assertGreater(out["stats"]["ai"] + out["stats"]["rule"], 0)
        if out["stats"]["ai"]:
            self.assertGreater(nz["counts"]["acts"]["act_ai"], 0, "브리지 답(by=ai, conf h)이 화행 열로 돌아왔다")

    def test_other_stages_switched_off(self):
        if self.res is None:
            self.skipTest("자식 실행 실패")
        by = self.by()
        for sid in ("ai:task_label", "ai:workflow", "ai:review_text"):
            self.assertEqual((by[sid]["state"], by[sid]["reason"]), ("skipped", "stage_off"), sid)
        self.assertEqual(by["report"]["state"], "done")
        self.assertTrue(self.res["status"]["current"])


if __name__ == "__main__":
    unittest.main()
