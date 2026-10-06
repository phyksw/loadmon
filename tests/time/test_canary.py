# -*- coding: utf-8 -*-
"""WP-20 PII 카나리아(W-G8 · T-07): 시간 산출물(원장·attrib·team_tables·tasks·큐·run_meta)에 카나리아 0건.

시간 코어는 정제된 행만 받지만, 이 시험은 일부러 정제 열(제목·본문·문서 이름·첨부 이름·창 제목·토큰)에 카나리아
원값을 심어 넣는다 — 시간 코어가 토큰·이름을 로컬 분석에만 쓰고 결과 파일에는 키와 숫자만 싣는지 확인한다.
카나리아 값은 런타임에 조립한다(`tests.fixtures.canary` — 저장소 텍스트에 원값 없음). 가명 키 모양(key 묶음)은 로컬
원장에 정상적으로 있을 수 있어(pc_id·who_key) 대상에서 뺀다.
"""
from __future__ import annotations

import unittest

from lm27.time import analyze_time
from lm27.time.ledger import day_ledger, interval_ledger, task_ledger
from tests.fixtures.canary import canaries, find_canaries
from tests.fixtures.wp20 import harness as H
from tests.time import scenarios as X

TEXT_COLS = ("subject_masked", "body_masked", "text_masked", "msg_masked", "title_masked", "name_masked",
             "chat_title_masked")
LIST_COLS = ("attach_names_masked", "file_names_masked", "categories_masked")


def plant(records: list[dict], cs) -> int:
    """정제 열에 카나리아를 심는다(행마다 돌아가며). 반환 = 심은 칸 수."""
    vals = [c.value for c in cs]
    n = 0
    for i, r in enumerate(records):
        v = vals[i % len(vals)]
        for col in TEXT_COLS:
            if isinstance(r.get(col), str) and r[col]:
                r[col] = f"{r[col]} {v}"
                n += 1
        for col in LIST_COLS:
            if isinstance(r.get(col), list) and r[col]:
                r[col] = [f"{x}_{v}" for x in r[col]]
                n += 1
        if isinstance(r.get("subject_tokens"), list):
            r["subject_tokens"] = list(r["subject_tokens"]) + [v]
            n += 1
    return n


class CanaryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = X.base_cfg()
        cls.cs = canaries(0, ("pii", "ctx", "env"), weak=False)

    def check(self, w):
        recs, profile, as_of, tags, over = X.to_inputs(w, self.cfg)
        self.assertGreater(plant(recs, self.cs), 0)
        c = self.cfg.derive(over) if over else self.cfg
        r = analyze_time(H.TEST_KEY, recs, profile, X.calendar(), as_of, cfg=c, tags=tags)
        for name, data in sorted(r.files().items()):
            self.assertEqual(find_canaries(data, self.cs), [], (w.name, name))
        text = "\n".join([day_ledger(r, d) for d in sorted(r.days) if r.days[d]["in_range"]] +
                         [x for d in sorted(r.days) for x in interval_ledger(r, d)] +
                         [task_ledger(r, t.id) for t in r.tasks])
        self.assertEqual(find_canaries(text.encode("utf-8"), self.cs), [], w.name)
        return r

    def test_scenarios(self):
        for name in ("W01", "W08", "W17", "W18", "W19", "W21", "W38", "W45", "W47B", "W61", "W67B"):
            with self.subTest(name=name):
                self.check(X.SC[name]())

    def test_synthetic_week(self):
        w, _n = H.gen_months(0.25, 11)
        r = self.check(w)
        self.assertGreater(len(r.tasks), 10)

    def test_planting_is_effective(self):
        """심은 값이 실제로 시간 코어의 로컬 구조(메시지 토큰)까지 들어갔는지 — 시험이 헛돌지 않게.
        구분자가 없는 이름 카나리아는 토큰으로 살아남는다(나머지는 토큰 분리에서 조각난다)."""
        names = [c for c in self.cs if c.slot == "name"]
        self.assertTrue(names)
        w = X.SC["W01"]()
        recs, profile, as_of, tags, _over = X.to_inputs(w, self.cfg)
        plant(recs, names)
        r = analyze_time(H.TEST_KEY, recs, profile, X.calendar(), as_of, cfg=self.cfg, tags=tags)
        local = " ".join(t for m in r.ev.msgs for t in sorted(m.tokens))
        self.assertTrue(find_canaries(local.encode("utf-8"), names))
        for name, data in sorted(r.files().items()):
            self.assertEqual(find_canaries(data, names), [], name)


if __name__ == "__main__":
    unittest.main()
