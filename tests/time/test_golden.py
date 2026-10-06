# -*- coding: utf-8 -*-
"""WP-20 골든(W-G4 · T-04): W §9 시나리오 83개의 단위업무·버킷·확인 큐·월 MM = 참조 골든(tests\\fixtures\\wp19\\golden.json).

골든은 참조 구현(`design\\worktime\\golden.json`, 읽기만)이다. 대조는 참조 표기로 한다(`tests.fixtures.wp20.harness` 가
제품 표지 — 키로만 만든 `S1:<대화 키>#n` 등 — 를 시나리오 이름으로 되돌린다). 계약이 참조와 다르게 정한 두 곳은
계약 값으로 기대값을 바꿔 대조한다(이유를 함께 적는다):

1. 봉투가 0 인 달(W35·W49): 참조는 봉투 슬롯이 있는 달만 월 결과를 냈다. 제품은 분석 기간의 달을 모두 낸다(팀 묶음
   `summary.months` 가 기간의 달과 1:1 — TAB §2.3.2). 그 달은 봉투 0·MM 0 이어야 한다.
2. 가용일의 '오늘'(W64): 참조는 오늘 표준창 경과 비율(`mm.todayFraction`)을 가용에 넣었다. 계약 X-210 은 그 키를 폐지하고
   'as_of 가 그날 표준창 끝을 지났을 때만 covered' 로 정했다(개인 = 팀 한 식). 그래서 가용 = 골든 − 오늘 비율,
   로드 = 봉투 ÷ (8h × 가용).
"""
from __future__ import annotations

import unittest

from tests.fixtures.wp20 import harness as H
from tests.time import scenarios as X

X210_TODAY = {"W64": {"2026-10": 0.5}}          # 참조가 가용에 넣은 오늘 경과 비율(계약 X-210 으로 뺀다)


def expected_mm(name: str, golden: dict) -> dict:
    out = {}
    for m, v in golden["mm"].items():
        v = dict(v)
        frac = X210_TODAY.get(name, {}).get(m)
        if frac:                                      # 한 달짜리 시나리오 — 봉투 h = 골든 env
            v["avail"] = round(v["avail"] - frac, 2)
            v["load"] = round(golden["env"] / (8 * v["avail"]), 4) if v["avail"] > 0 else None
        out[m] = v
    return out


class GoldenTimeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.golden = X.load_golden()
        cls.cfg = X.base_cfg()
        cls.got = {}
        for name, fn in X.SC.items():
            res, names = H.run(fn(), cls.cfg)
            cls.got[name] = (H.summarize(res, names), res)

    def test_83_scenarios(self):
        self.assertEqual(len(X.SC), 83)
        self.assertEqual(set(self.got), set(self.golden))

    def test_tasks_buckets_queue(self):
        bad = []
        for name, (got, _res) in sorted(self.got.items()):
            want = self.golden[name]
            with self.subTest(name=name):
                self.assertEqual(got["env"], want["env"], name)
                self.assertEqual(got["tags"], want["tags"], name)
                self.assertEqual(got["buckets"], want["buckets"], name)
                self.assertEqual(got["queue"], want["queue"], name)
                gt = sorted(map(tuple, got["tasks"]), key=str)
                wt = sorted(map(tuple, want["tasks"]), key=str)
                if gt != wt:
                    bad.append(name)
                self.assertEqual(gt, wt, name)
        self.assertEqual(bad, [])

    def test_month_mm(self):
        for name, (got, _res) in sorted(self.got.items()):
            with self.subTest(name=name):
                want = expected_mm(name, self.golden[name])
                for m, v in got["mm"].items():
                    if m in want:
                        self.assertEqual(v, want[m], (name, m))
                    else:                               # 계약 1: 봉투 0 인 달도 낸다 — 0 이어야 한다
                        self.assertEqual((v["mm"], v["ot"]), (0.0, 0.0), (name, m))
                for m in want:
                    self.assertIn(m, got["mm"], (name, m))

    def test_rows_of_note(self):
        """W §9.1 해설 행."""
        def tasks(name):
            return {t[0]: t for t in self.got[name][0]["tasks"]}
        w17 = tasks("W17")
        self.assertEqual((w17["S1:chat_p31#1"][2], w17["S1:chat_p31#2"][2]), (3.17, 2.92))
        w18 = tasks("W18")
        self.assertEqual({w18["S1:M1#1"][5], w18["S1:M2#1"][5]}, {"E1"})          # 다대다: 둘 다 E1
        self.assertEqual(len([t for t in self.got["W20"][0]["tasks"] if t[0].startswith("SELF:주간보고@")]), 8)
        w21 = tasks("W21")
        self.assertEqual((w21["S1:M1#1"][2], w21["S1:M2#1"][2]), (2.5, 11.5))
        self.assertEqual(self.got["W45"][0]["buckets"].get("B_GENERIC"), 8.92)
        w47a, w47b = tasks("W47A"), tasks("W47B")
        self.assertEqual(tuple(w47a["SELF:점검표_과제h@09-14"][3:6]), ("B", "S2M", "E3M"))
        self.assertEqual(tuple(w47b["S1:M47#1"][3:6]), ("B", "S1", "E3M"))                # 업무 ID 가 바뀌어도 응답 유지
        self.assertEqual(self.got["W51"][0]["mm"]["2026-09"]["mm"], 0.9875)
        w54 = self.got["W54"][1]
        eff = w54.effort()
        self.assertEqual(sum(v for k, v in eff.items() if k.startswith("u_")), 8 * 3600)   # 병행 3업무 = 그날 봉투
        w56 = tasks("W56")
        self.assertEqual((w56["S1:M56a#1"][2], w56["S1:M56b#1"][2]), (6.0, 2.0))


if __name__ == "__main__":
    unittest.main()
