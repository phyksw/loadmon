# -*- coding: utf-8 -*-
"""WP-30 실물 시간 코어 결과로 분석층 돌리기(통합 — WP-19 시나리오 · WP-20 `analyze_time` · 계약 §3.14 `timecore/1.1`).

시간 코어가 쓰는 결과 파일 바이트(`TimeResult.files()`)를 그대로 읽어 분석 문맥을 만들고 분석층을 돌린다:
- W 시나리오 83개 모두 예외 없이 끝나고, 단위업무마다 관측 + 추정 = 투입 = Σ alloc(모델 등식 — G-R2),
  달마다 정수 분 표 봉투 합 = `mm_month.env_min`(개인 = 팀 숫자의 출처 하나 — RP1), 기간 리뷰 등식.
- 결과는 결정적(같은 입력이면 같은 바이트).
"""
from __future__ import annotations

import json
import unittest

from lm27.report.analysis import analyze
from lm27.report.analysis.activity import make_context
from lm27.util.fsx import canon_bytes
from tests.fixtures.wp20 import harness as H
from tests.time import scenarios as X


def files_of(res) -> dict:
    fs = res.files()

    def jl(b):
        return [json.loads(x) for x in b.decode("utf-8").splitlines() if x.strip()]
    return {"tasks": json.loads(fs["tasks.json"]), "attrib": jl(fs["attrib.jsonl"]),
            "tables": json.loads(fs["team_tables.json"]), "env_slots": jl(fs["env_slots.jsonl"]),
            "day_ledger": jl(fs["day_ledger.jsonl"]), "run_meta": json.loads(fs["run_meta.json"]),
            "mm_month": json.loads(fs["mm_month.json"])}


def context(f, cfg):
    return make_context(tasks=f["tasks"], attrib=f["attrib"], tables=f["tables"], cal=X.calendar(), cfg=cfg,
                        env_slots=f["env_slots"], day_ledger=f["day_ledger"], run_meta=f["run_meta"])


class TimeCoreScenariosTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = X.base_cfg()

    def test_all_scenarios(self):
        bad = []
        for name in sorted(X.SC):
            res, _names = H.run(X.SC[name](), self.cfg, ref_ids=False)
            f = files_of(res)
            ctx = context(f, self.cfg)
            sec = analyze(ctx)
            for u in ctx.units.values():
                if not (u.obs_min + u.est_min == u.effort_min == sum(u.by_date.values())):
                    bad.append((name, u.unit_id, "unit"))
            env_month: dict[str, int] = {}
            for d, e in ctx.env.items():
                env_month[d[:7]] = env_month.get(d[:7], 0) + sum(e.values())
            for row in f["mm_month"]:
                if env_month.get(row["month"], 0) != row["env_min"]:
                    bad.append((name, row["month"], "env"))
            for r in sec["reviews"]["weeks"] + sec["reviews"]["months"]:
                if r["attributed_min"] + r["unattr_min"] != r["env_min"] or \
                        r["obs_min"] + r["est_min"] != r["attributed_min"]:
                    bad.append((name, r["key"], "review"))
            for m, q in sec["quality"]["months"].items():
                if q["grade"] not in ("reliable", "caution", "unreliable", ""):
                    bad.append((name, m, "quality"))
        self.assertEqual(bad, [])

    def test_deterministic_on_core_output(self):
        res, _names = H.run(X.SC["W51"](), self.cfg, ref_ids=False)
        f = files_of(res)
        a = canon_bytes(analyze(context(f, self.cfg)))
        b = canon_bytes(analyze(context(files_of(res), self.cfg)))
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
