# -*- coding: utf-8 -*-
"""WP-23 스텁 전송(B §11.4) — ``StubTransport``·``LM_COPILOT_STUB`` 파일 응답기(단계 ID 로 고르기)·모드 13종."""
from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import unittest
from pathlib import Path

from lm27.bridge import transport_stub as T
from lm27.bridge.transport import SendRequest, envelope_state, pledge_rx

from tests.bridge.fake_cdp import make_prompt

RID = "R7F3QK"
FIXT = Path(__file__).resolve().parents[1] / "fixtures" / "wp23" / "stub"


def req(prompt, stage="speech_act", rid=RID, keys=(), fresh=False):
    return SendRequest(rid, prompt, fresh, "빠른 응답", 480, 180, 900, stage, True, tuple(keys))


def env_of(body):
    m = re.search(r"```json\n(.*)\n```", body, re.S)
    return json.loads(m.group(1)) if m else None


class TestBuildReply(unittest.TestCase):
    def test_item_ids(self):
        self.assertEqual(T.item_ids(make_prompt(RID, 4)), [1, 2, 3, 4])
        self.assertEqual(T.item_ids("[LM27 요청 R7F3QK · 메일 조회]\n규칙\n[답 형식]"), [])

    def test_ok_partial_truncate(self):
        ids = [1, 2, 3, 4]
        ph, body = T.build_reply("ok", RID, ids, {1: {"act": "info"}})
        self.assertEqual(ph, "stub")
        e = env_of(body)
        self.assertEqual((e["rid"], e["n"], [x["id"] for x in e["items"]]), (RID, 4, ids))
        self.assertEqual(e["items"][0]["act"], "info")
        self.assertTrue(pledge_rx(RID).search(body))
        e2 = env_of(T.build_reply("partial:0.5", RID, ids)[1])
        self.assertEqual((e2["n"], len(e2["items"])), (4, 2))
        _ph, cut = T.build_reply("truncate:0.6", RID, ids)
        self.assertFalse(pledge_rx(RID).search(cut))
        self.assertEqual(envelope_state(cut, RID), (True, False))

    def test_echo_stale_and_texts(self):
        p = make_prompt(RID, 2)
        _ph, echo = T.build_reply("echo", RID, [1, 2], prompt=p)
        self.assertIn("<요청번호>", echo)
        _ph, stale = T.build_reply("stale", RID, [1, 2])
        e = env_of(stale)
        self.assertNotEqual(e["rid"], RID)
        self.assertTrue(T.RID_RX.match(e["rid"]))
        self.assertEqual(T.build_reply("empty", RID, [1]), ("stub", ""))
        self.assertIn("도와드릴 수 없", T.build_reply("refusal", RID, [1])[1])
        self.assertIn("조회 도구가 없", T.build_reply("unavailable", RID, [])[1])
        self.assertIn("업무 데이터에 액세스할 수 없", T.build_reply("nolic", RID, [])[1])
        self.assertIn("응답할 수 없습니다", T.build_reply("service_error", RID, [1])[1])
        self.assertIsNone(env_of(T.build_reply("format", RID, [1])[1]))

    def test_invalid_answer_modes(self):
        ans = {1: {"project": "P0001", "conf": "h"}, 2: {"project": "P0002", "conf": "m"}}
        e = env_of(T.build_reply("forbidden_time", RID, [1, 2], ans)[1])
        self.assertEqual(e["items"][0]["start"], "09:00")
        e = env_of(T.build_reply("unknown_code", RID, [1, 2], ans)[1])
        self.assertEqual(e["items"][0]["project"], T.UNKNOWN_CODE)
        e = env_of(T.build_reply("pii_in_answer", RID, [1, 2], ans)[1])
        self.assertRegex(e["items"][0]["project"], r"\d{3}-\d{4}-\d{4}")
        with self.assertRaises(ValueError):
            T.build_reply("weird", RID, [1])

    def test_lookup_rows(self):
        rows = [{"t": "2026-09-02", "d": "in"}, {"t": "2026-09-03", "d": "out"}]
        e = env_of(T.build_reply("ok", RID, [], rows=rows, more=True)[1])
        self.assertEqual((e["n"], e["more"], [r["id"] for r in e["items"]]), (2, True, [1, 2]))


class TestStubTransport(unittest.TestCase):
    def test_responder_and_memory_only(self):
        calls = []

        def responder(prompt, rid, stage):
            calls.append((rid, stage))
            return T.build_reply("ok", rid, T.item_ids(prompt))
        t = T.StubTransport(responder, work_mode="work")
        self.assertEqual((t.open(), t.kind), ("ready", "stub"))
        r = t.roundtrip(req(make_prompt(RID, 3), fresh=True))
        self.assertEqual((r.phase, r.done_by, r.pick, r.model_used, r.work_mode, r.chat_seq),
                         ("stub", "pledge", "stub", "빠른 응답", "work", 1))
        self.assertEqual(calls, [(RID, "speech_act")])
        self.assertEqual((t.sends, len(t.sent_texts)), (1, 1))
        t.close()
        self.assertTrue(t.closed)
        with self.assertRaises(ValueError):
            T.StubTransport()

    def test_file_responder_by_stage_and_key(self):
        t = T.StubTransport(stub_dir=FIXT)
        p = make_prompt(RID, 3)
        r1 = t.roundtrip(req(p, keys=("msg:4c1d01", "msg:x2", "msg:x3")))
        self.assertEqual(envelope_state(r1.body, RID), (True, False))       # 첫 질의 truncate:0.6
        r2 = t.roundtrip(req(p, rid="R7F3QM", keys=("msg:4c1d01", "msg:x2", "msg:x3")))
        e = env_of(r2.body)
        self.assertEqual([x["act"] for x in e["items"]], ["request", "info", "info"])
        self.assertEqual(e["rid"], "R7F3QM")
        r3 = t.roundtrip(req(p, rid="R7F3QN"))                              # 마지막 모드 반복
        self.assertEqual(len(env_of(r3.body)["items"]), 3)

    def test_file_responder_lookup_and_missing_stage(self):
        t = T.StubTransport(stub_dir=FIXT)
        r = t.roundtrip(req("[LM27 요청 R7F3QK · 메일 조회 · 구간 2026-09-01~2026-09-07]\n[답 형식]", "lookup_mail"))
        e = env_of(r.body)
        self.assertEqual((e["n"], e["more"]), (2, False))
        r2 = t.roundtrip(req(make_prompt(RID, 2), "review_text"))            # 단계 파일 없음 → ok + 등록부 스텁 답
        self.assertEqual(len(env_of(r2.body)["items"]), 2)
        with self.assertRaises(ValueError):
            t.roundtrip(req(make_prompt(RID, 2), "../evil"))

    def test_file_responder_registry_stub_default(self):
        """W1 통합 창(WP-25 CR): 단계 파일에 기본 답이 없으면 등록부(REGISTRY) 스텁 답 — 필수 필드가 있는 단계도
        LM_COPILOT_STUB 종단 시험에서 유효한 AI 답을 본다. 조회형은 행 하나."""
        from lm27.bridge.stages import REGISTRY
        with tempfile.TemporaryDirectory(prefix="lm27t_stub_") as d:
            Path(d, "task_label.json").write_text(json.dumps({"mode": ["ok"], "default": {}}), encoding="utf-8")
            t = T.StubTransport(stub_dir=d)
            e = env_of(t.roundtrip(req(make_prompt(RID, 2), "task_label")).body)
            want = REGISTRY["task_label"].stub_answer()
            self.assertEqual([{k: x[k] for k in want} for x in e["items"]], [want, want])
            e2 = env_of(t.roundtrip(req("[LM27 요청 R7F3QK · 일정 조회 · 구간 2026-09-01~2026-09-07]\n[답 형식]",
                                        "lookup_calendar", rid="R7F3QM")).body)
            self.assertEqual((len(e2["items"]), e2["more"]), (1, False))        # 조회 봉투의 행 = items
            self.assertEqual({k: e2["items"][0][k] for k in REGISTRY["lookup_calendar"].stub_answer()},
                             REGISTRY["lookup_calendar"].stub_answer())

    def test_from_env(self):
        self.assertIsNone(T.from_env({}))
        self.assertIsInstance(T.from_env({T.ENV_VAR: str(FIXT)}), T.StubTransport)
        with self.assertRaises(ValueError):
            T.from_env({T.ENV_VAR: str(FIXT / "nope")})

    def test_stub_writes_nothing(self):
        d = tempfile.mkdtemp(prefix="lm27t_stub_")
        self.addCleanup(shutil.rmtree, d, True)
        shutil.copy(FIXT / "speech_act.json", d)
        before = sorted(os.listdir(d))
        t = T.from_env({T.ENV_VAR: d})
        t.roundtrip(req(make_prompt(RID, 3)))
        self.assertEqual(sorted(os.listdir(d)), before)


if __name__ == "__main__":
    unittest.main()
