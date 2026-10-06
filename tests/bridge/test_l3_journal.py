# -*- coding: utf-8 -*-
"""WP-24 저널·항목 저장소(B §7.8~§7.9) — 마지막 커밋(ts → rid → 순서) · 끊긴 줄 건너뛰기 · 64KB 줄 상한 · 저장소 정리 ·
저널·저장소에 프롬프트·답 원문 0(B9) · 실행 폴더 파일 경로(Paths 메서드 우선)."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from lm27.bridge import journal as J
from lm27.bridge.clock import VirtualClock
from lm27.bundle.lock import BundleBusy
from lm27.paths import Paths
from lm27.util import events

from tests.fixtures.wp24.rig import Rig, act_rows
from tests.fixtures.wp24.stages import ActStage


def setUpModule():
    events.configure(mode="off")


class StoreTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.mkdtemp(prefix="lm27t_wp24_")
        self.paths = Paths(tmp + "/root", lad=tmp + "/lad")
        self.clk = VirtualClock()

    def test_last_commit_wins_and_torn_lines(self):
        s = J.Store(self.paths, "t_act", self.clk).load()
        s.commit({"ck": "a" * 24, "key": "k1", "by": "rule", "ans": {"x": 1}, "final": False, "rid": None})
        self.clk.advance(5)
        s.commit({"ck": "a" * 24, "key": "k1", "by": "ai", "ans": {"x": 2}, "final": True, "rid": "R22222"})
        with open(s.path, "ab") as fh:                       # 시험 전용: 끊긴 마지막 줄 흉내
            fh.write(b'{"t":"commit","ck":"bbbb')
        s2 = J.Store(self.paths, "t_act", self.clk).load()
        self.assertEqual(s2.last("a" * 24)["ans"], {"x": 2})
        self.assertEqual(s2.torn_lines, 1)
        self.assertIsNone(s2.last("b" * 24))

    def test_same_ts_tie_rid_then_order(self):
        s = J.Store(self.paths, "t_act", self.clk).load()
        s.commit({"ck": "c" * 24, "key": "k", "by": "ai", "rid": "R33333", "ans": {"v": "b"}, "final": True})
        s.commit({"ck": "c" * 24, "key": "k", "by": "ai", "rid": "R22222", "ans": {"v": "a"}, "final": True})
        self.assertEqual(J.Store(self.paths, "t_act", self.clk).load().last("c" * 24)["ans"], {"v": "b"})

    def test_line_cap(self):
        s = J.Store(self.paths, "t_act", self.clk).load()
        rec = s.commit({"ck": "d" * 24, "key": "k", "by": "ai", "ans": {"t": "가" * 70000}, "final": True})
        self.assertTrue(rec["trunc"])
        raw = Path(s.path).read_bytes().splitlines()[-1]
        self.assertLessEqual(len(raw), J.LINE_MAX)

    def test_compact(self):
        s = J.Store(self.paths, "t_act", self.clk).load()
        for i in range(30):
            s.commit({"ck": f"{i % 3:024d}", "key": f"k{i % 3}", "by": "ai", "ans": {"i": i}, "final": True})
        old = J.COMPACT_BYTES
        J.COMPACT_BYTES = 100
        try:
            def busy():
                raise BundleBusy("fg-write", 0)
            self.assertFalse(s.compact(lock_factory=busy))
            self.assertTrue(s.compact())
        finally:
            J.COMPACT_BYTES = old
        rows = [json.loads(x) for x in Path(s.path).read_text("utf-8").splitlines()]
        self.assertEqual(len(rows), 3)
        self.assertEqual(sorted(r["ans"]["i"] for r in rows), [27, 28, 29])

    def test_run_file_prefers_paths_method(self):
        class P2(Paths):
            def ai_result(self, run_id, stage):
                return Path(self.data()) / "x" / f"{stage}.r.json"
        p = P2(self.paths.root, lad=self.paths.lad())
        self.assertTrue(str(J.run_file(p, "20261005-101500-3fa2", "result", "t_act")).endswith("t_act.r.json"))
        self.assertTrue(str(J.run_file(self.paths, "20261005-101500-3fa2", "journal", "t_act")).endswith(
            "20261005-101500-3fa2\\t_act.jsonl".replace("\\", __import__("os").sep)))


class NoRawText(unittest.TestCase):
    def test_journal_and_store_have_no_prompt_text(self):
        marker = "고유표식문장스물셋"
        rows = act_rows(4, text=marker)
        r = Rig(stages=[ActStage()], script={"t_act": ["partial:0.5", "ok"]})
        self.addCleanup(r.cleanup)
        r.write_ai_in("t_act", rows)
        r.run()
        self.assertIn(marker, r.transport.sent_texts[0])             # 보낸 것은 메모리에만
        for rel, data in r.tree_bytes():
            if "ai_in" in rel:
                continue
            self.assertNotIn(marker.encode("utf-8"), data, rel)
        req = [j for j in r.journal("t_act") if j["t"] == "req"]
        self.assertTrue(all(len(q["prompt_sha256"]) == 64 for q in req))
        self.assertEqual({j["t"] for j in r.journal("t_act")}, {"req", "resp"})


if __name__ == "__main__":
    unittest.main()
