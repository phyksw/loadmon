# -*- coding: utf-8 -*-
"""WP-19 골든(W-G4 의 봉투 몫): W §9 83개 시나리오의 봉투 분·꼬리표 분 = 참조 골든(tests\\fixtures\\wp19\\golden.json).

골든은 참조 구현(`design\\worktime\\golden.json`)의 사본이다(h 소수 2자리 → 5분 슬롯 정수 분으로 비교).
단위업무·버킷·MM·큐 열은 시간 코어 B(WP-20 `test_golden.py`)가 같은 파일을 읽어 대조한다.
"""
from __future__ import annotations

import unittest

from tests.time import scenarios as X


class GoldenEnvelopeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.golden = X.load_golden()
        cls.cfg = X.base_cfg()

    def test_scenario_set_matches_golden(self):
        self.assertEqual(len(X.SC), 83)
        self.assertEqual(set(X.SC), set(self.golden))

    def test_envelope_and_tag_minutes(self):
        bad = []
        for name, fn in X.SC.items():
            with self.subTest(name=name):
                _ev, _days, env, _c = X.run_env(fn(), self.cfg)
                want_env, want_tags = X.golden_minutes(self.golden[name])
                got = (env.minutes(), env.tag_minutes())
                if got != (want_env, want_tags):
                    bad.append(name)
                self.assertEqual(got, (want_env, want_tags), name)
        self.assertEqual(bad, [])

    def test_known_rows(self):
        """W §9.1 해설 행: W27 9.17h · W28 11.83h / W28b 12.00h · W29a = W29b · W30a = W30b · W31a ≥ W31b · W65a = W65b."""
        m = {k: X.run_env(X.SC[k](), self.cfg)[2].minutes() for k in
             ("W27", "W28", "W28B", "W29A", "W29B", "W30A", "W30B", "W31A", "W31B", "W65A", "W65B", "W35", "W35B")}
        self.assertEqual(m["W27"], 550)
        self.assertEqual((m["W28"], m["W28B"]), (710, 720))
        self.assertEqual(m["W29A"], m["W29B"])
        self.assertEqual(m["W30A"], m["W30B"])
        self.assertGreaterEqual(m["W31A"], m["W31B"])
        self.assertEqual(m["W65A"], m["W65B"])
        self.assertEqual((m["W35"], m["W35B"]), (0, 460))


if __name__ == "__main__":
    unittest.main()
