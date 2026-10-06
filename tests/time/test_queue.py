# -*- coding: utf-8 -*-
"""WP-20 확인 큐(W §7.3 · 계약 §3.14 confirm_queue.json · §4.1 qid · §6.3 · W-G12 · T-23).

qid = sha1('코드|대상|핵심 근거')[:12] · 같은 입력(행 순서를 섞어도) → 같은 qid 집합 · ISO 주당 노출(open) ≤
`time.queue.maxPerWeek` · 파일 행은 계약 열 그대로, 대상·근거는 키·날짜만.
"""
from __future__ import annotations

import hashlib
import re
import unittest
from collections import Counter
from datetime import date

from lm27.time.queue import QW, make_item, prioritize, qid_of
from tests.fixtures.wp20 import harness as H
from tests.time import scenarios as X

TARGET_RX = re.compile(r"^(u_[0-9a-f]{10}|\d{4}-\d{2}-\d{2}|[medhtrfs][0-9a-f]{16,24}(@[0-9a-zs+]+)?|B_GENERIC|-)$")


def week(it):
    if not it.day:
        return "-"
    y, w, _ = date.fromisoformat(it.day).isocalendar()
    return (y, w)


class QueueTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = X.base_cfg()
        cls.res = {name: H.run(fn(), cls.cfg, ref_ids=False)[0] for name, fn in X.SC.items()}

    def test_qid_formula(self):
        it = make_item("Q01", "u_0123456789", "S2p>E3i")
        self.assertEqual(it.qid, hashlib.sha1(b"Q01|u_0123456789|S2p>E3i").hexdigest()[:12])
        self.assertEqual(it.qid, qid_of("Q01", "u_0123456789", "S2p>E3i"))
        with self.assertRaises(ValueError):
            make_item("Q99", "x")
        self.assertEqual(len(QW), 18)

    def test_same_input_same_qids(self):
        for name, fn in X.SC.items():
            with self.subTest(name=name):
                a = {q.qid for q in self.res[name].queue}
                b = {q.qid for q in H.run(fn(), self.cfg, ref_ids=False, shuffle=99)[0].queue}
                self.assertEqual(a, b)
                shown_a = {q.qid for q in self.res[name].queue if q.status == "open"}
                shown_b = {q.qid for q in H.run(fn(), self.cfg, ref_ids=False, shuffle=7)[0].queue
                           if q.status == "open"}
                self.assertEqual(shown_a, shown_b)

    def test_weekly_cap(self):
        cap = int(self.cfg["time.queue.maxPerWeek"])
        for name, r in self.res.items():
            per = Counter(week(q) for q in r.queue if q.status == "open")
            self.assertTrue(all(v <= cap for v in per.values()), name)
        tight = self.cfg.derive({"time.queue.maxPerWeek": 1})
        for name in ("W20", "W38", "W50", "W65A"):
            r, _ = H.run(X.SC[name](), tight, ref_ids=False)
            per = Counter(week(q) for q in r.queue if q.status == "open")
            self.assertTrue(all(v <= 1 for v in per.values()), name)
            self.assertTrue(any(q.status == "deferred" for q in r.queue) or len(r.queue) <= len(per), name)

    def test_rows_contract_columns_keys_only(self):
        for name, r in self.res.items():
            for q in r.queue:
                row = q.to_row()
                self.assertEqual(set(row), {"qid", "code", "target", "impact_min", "evidence_keys", "proposal",
                                            "status"})
                self.assertRegex(row["code"], r"^Q(0[1-9]|1[0-8])$")
                self.assertRegex(row["target"], TARGET_RX, (name, row["code"]))
                self.assertIsInstance(row["impact_min"], int)
                self.assertIn(row["status"], ("open", "deferred"))
                self.assertTrue(set(row["proposal"]) <= {"title", "options", "answer_kinds", "date", "note"})

    def test_prioritize_dedupe_and_order(self):
        a = make_item("Q11", "u_aaaaaaaaaa", "solver", impact_min=600, day="2026-10-14")
        b = make_item("Q01", "u_bbbbbbbbbb", "S2p>E3i", impact_min=60, day="2026-10-14")
        c = make_item("Q01", "u_bbbbbbbbbb", "S2p>E3i", impact_min=60, day="2026-10-14")   # 같은 qid
        out = prioritize([a, b, c], self.cfg.derive({"time.queue.maxPerWeek": 1}))
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0].code, "Q01")                                 # (1.01 × 1.0) > (10.01 × 0.1)
        self.assertEqual([q.status for q in out], ["open", "deferred"])

    def test_codes_of_note(self):
        self.assertIn("Q13", {q.code for q in self.res["W50"].queue})        # UTC 의심
        self.assertIn("Q16", {q.code for q in self.res["W52"].queue})        # 휴가 중 근무
        self.assertIn("Q15", {q.code for q in self.res["W58A"].queue})       # 미정 회의
        self.assertIn("Q11", {q.code for q in self.res["W42"].queue})        # 솔버 대량
        self.assertIn("Q18", {q.code for q in self.res["W45"].queue})        # 공용 문서
        q17 = [q for q in self.res["W01"].queue if q.code == "Q17"]
        self.assertTrue(q17 and all(q.impact_min >= 60 for q in q17))


if __name__ == "__main__":
    unittest.main()
