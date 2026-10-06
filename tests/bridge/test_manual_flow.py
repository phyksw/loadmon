# -*- coding: utf-8 -*-
"""WP-24 수동 붙여넣기 경로(B §10) — 내보내기(프롬프트 파일 UTF-8 BOM + CRLF·목록) · B-T43(묶음 3개, 답 2개를 순서 바꿔
한꺼번에 → 2개 반입·1개 열림·파일 2개 삭제) · B-T44(다른 rid → 반입 거부, BR-MANUAL-RID, 저장소 변화 없음) · B-T45(반입한 답이
partial → 빠진 항목으로 새 묶음 자동 생성) · 같은 항목 재수출 → 앞 묶음 superseded · 열린 묶음 대기 · 형식 실패 1회 재수출 ·
TTL 만료 · inbox 반입 · maxOpenBatches."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from lm27.bridge import runner
from lm27.bridge.env import manual_env
from lm27.bridge.manual import Manifest, ManualTransport, manual_dir
from lm27.bridge.transport_stub import envelope_text
from lm27.util import events

from tests.fixtures.wp24.rig import RUN2, Rig, act_rows
from tests.fixtures.wp24.stages import ActStage


def setUpModule():
    events.configure(mode="off")


class _One(ActStage):
    max_items = 1


def _answer(batch, n=None, **over):
    items = [dict({"id": i["n"], "act": "report", "conf": "h"}, **over) for i in batch["items"]][:n]
    return envelope_text(batch["rid"], items, n=len(batch["items"]))


class Base(unittest.TestCase):
    def rig(self, spec, rows, **kw):
        r = Rig(stages=[spec], **kw)
        self.addCleanup(r.cleanup)
        mt = ManualTransport(r.paths, r.cfg, r.clock, run_id=r.run_id)
        mt.open()
        r.new_runtime(transport=mt, env=manual_env(r.clock))
        r.write_ai_in(spec.id, rows)
        return r

    def batches(self, r):
        return json.loads(Path(manual_dir(r.paths), "manifest.json").read_text("utf-8"))["batches"]

    def imp(self, r, text, spec):
        return runner.manual_import(text, rt=r.rt, specs={spec.id: spec})


class Export(Base):
    def test_export_files_and_manual_wait(self):
        spec = _One()
        r = self.rig(spec, act_rows(3))
        res = r.run()["t_act"]
        self.assertEqual((res["stop_kind"], res["state"], res["rc"], res["transport"]), ("manual_wait", "partial", 2,
                                                                                         "manual"))
        bs = self.batches(r)
        self.assertEqual([b["state"] for b in bs], ["open"] * 3)
        self.assertEqual([b["seq"] for b in bs], [1, 2, 3])
        f = Path(manual_dir(r.paths), bs[0]["file"])
        self.assertRegex(f.name, r"^001_t_act_R[2-9A-HJ-NP-TV-Z]{5}\.prompt\.txt$")
        raw = f.read_bytes()
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
        self.assertIn(b"\r\n", raw)
        self.assertNotIn(b"\n", raw.replace(b"\r\n", b""))
        self.assertIn(f"[[END {bs[0]['rid']}]]", raw.decode("utf-8-sig"))
        self.assertTrue(res["gate"]["web"]["exposed"])                  # 수동 경로 = 웹 노출 가정(엄격 규칙)
        # 다시 내보내도 열린 묶음의 항목은 대기(awaiting) — 새 묶음 0
        r.new_runtime(run_id=RUN2, transport=ManualTransport(r.paths, r.cfg, r.clock, run_id=RUN2))
        res2 = r.run()["t_act"]
        self.assertEqual(len(self.batches(r)), 3)
        self.assertEqual(res2["counts"]["awaiting"], 3)

    def test_max_open_batches(self):
        r = self.rig(_One(), act_rows(5), overrides={"bridge.manual.maxOpenBatches": 2})
        res = r.run()["t_act"]
        self.assertEqual((res["stop_kind"], len(self.batches(r))), ("manual_wait", 2))


class Import(Base):
    def test_T43_two_answers_reordered(self):
        spec = _One()
        r = self.rig(spec, act_rows(3))
        r.run()
        b1, b2, b3 = self.batches(r)
        rep = self.imp(r, _answer(b3) + "\n\n잡담 한 줄\n\n" + _answer(b1), spec)
        self.assertEqual(sorted(x["rid"] for x in rep["results"]), sorted([b1["rid"], b3["rid"]]))
        self.assertEqual((rep["committed"], rep["open"], rep["rc"]), (2, 1, 2))
        states = {b["rid"]: b["state"] for b in self.batches(r)}
        self.assertEqual(states, {b1["rid"]: "answered", b2["rid"]: "open", b3["rid"]: "answered"})
        files = sorted(p.name for p in manual_dir(r.paths).glob("*.prompt.txt"))
        self.assertEqual(files, [b2["file"]])
        self.assertEqual({c["by"] for c in r.store("t_act")}, {"manual"})
        self.assertIn("BR-MANUAL-DONE", r.notified())

    def test_T44_other_rid_rejected(self):
        spec = _One()
        r = self.rig(spec, act_rows(2))
        r.run()
        before = list(r.store("t_act"))
        rep = self.imp(r, envelope_text("R2Z2Z2", [{"id": 1, "act": "report", "conf": "h"}]), spec)
        self.assertEqual((rep["rc"], rep["rejected"]), (1, [{"rid": "R2Z2Z2", "why": "BR-MANUAL-RID"}]))
        self.assertEqual(r.store("t_act"), before)
        self.assertIn("BR-MANUAL-RID", r.notified())
        self.assertEqual(self.imp(r, "봉투가 없는 글", spec)["error"], "BR-MANUAL-NOENV")
        # 이미 반입한 rid 를 또 붙여넣음 → already
        b = self.batches(r)[0]
        self.imp(r, _answer(b), spec)
        rep2 = self.imp(r, _answer(b), spec)
        self.assertEqual(rep2["rejected"], [{"rid": b["rid"], "why": "already"}])

    def test_T45_partial_creates_next_batch(self):
        spec = ActStage()
        r = self.rig(spec, act_rows(5))
        r.run()
        (b,) = self.batches(r)
        rep = self.imp(r, _answer(b, n=3), spec)
        self.assertEqual((rep["committed"], rep["retry"]), (3, 2))
        bs = self.batches(r)
        self.assertEqual([x["state"] for x in bs], ["answered", "open"])
        self.assertEqual([i["key"] for i in bs[1]["items"]], ["msg:00003", "msg:00004"])
        self.assertEqual(rep["rc"], 2)
        rep2 = self.imp(r, _answer(bs[1]), spec)
        self.assertEqual((rep2["committed"], rep2["open"], rep2["rc"]), (2, 0, 0))
        self.assertEqual(rep2["stages"]["t_act"]["state"], "done")

    def test_requeued_items_regated(self):
        """반입 뒤 다시 나가는 항목도 ① 게이트를 거친다(재가림 값만 프롬프트 파일에)."""
        spec = ActStage()
        rows = act_rows(3)
        rows[2]["fields"]["text"] = "견적 금액 1,200만원 확인 부탁드립니다"
        r = self.rig(spec, rows)
        r.run()
        (b,) = self.batches(r)
        first = Path(manual_dir(r.paths), b["file"]).read_bytes().decode("utf-8-sig")
        self.assertIn("[금액]", first)
        self.imp(r, _answer(b, n=2), spec)
        nb = self.batches(r)[-1]
        txt = Path(manual_dir(r.paths), nb["file"]).read_bytes().decode("utf-8-sig")
        self.assertIn("[금액]", txt)
        self.assertNotIn("1,200만원", txt)

    def test_format_answer_reexported_once_with_new_rid(self):
        spec = ActStage()
        r = self.rig(spec, act_rows(4))
        r.run()
        (b,) = self.batches(r)
        self.imp(r, envelope_text(b["rid"], [{"id": i, "act": "지시", "conf": "h"} for i in (1, 2, 3, 4)]), spec)
        bs = self.batches(r)
        self.assertEqual([x["state"] for x in bs], ["answered", "open"])
        self.assertEqual((bs[1]["resent"], len(bs[1]["items"])), (1, 4))
        self.assertNotEqual(bs[1]["rid"], b["rid"])

    def test_inbox_import(self):
        spec = _One()
        r = self.rig(spec, act_rows(1))
        r.run()
        (b,) = self.batches(r)
        inbox = Path(manual_dir(r.paths), "inbox")
        inbox.mkdir(parents=True, exist_ok=True)
        (inbox / "답.txt").write_bytes(_answer(b).encode("utf-8"))
        reps = runner.inbox_import(r.rt, {spec.id: spec})
        self.assertEqual(reps[0]["committed"], 1)
        self.assertFalse((inbox / "답.txt").exists())


class Manifests(unittest.TestCase):
    def test_superseded_and_expire(self):
        r = Rig(stages=[ActStage()])
        self.addCleanup(r.cleanup)
        mf = Manifest(r.paths, r.clock)
        mf.add(seq=1, stage="t_act", rid="R2AAAA", file="001_t_act_R2AAAA.prompt.txt",
               items=[{"n": 1, "key": "a", "ck": "c1"}], in_chars=10, run="x")
        mf.add(seq=2, stage="t_act", rid="R2BBBB", file="002_t_act_R2BBBB.prompt.txt",
               items=[{"n": 1, "key": "a", "ck": "c1"}], in_chars=10, run="x")
        self.assertEqual([b["state"] for b in mf.batches], ["superseded", "open"])
        self.assertEqual(mf.awaiting_cks("t_act"), {"c1"})
        r.clock.advance(86400 * (r.cfg.manual.ttl_days + 1))
        self.assertEqual(mf.expire(r.cfg.manual.ttl_days), 1)
        self.assertEqual(mf.open_count(), 0)


if __name__ == "__main__":
    unittest.main()
