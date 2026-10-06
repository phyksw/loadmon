# -*- coding: utf-8 -*-
"""WP-20 결과 파일·설명 원장·analyze_time(계약 §2.9 · §3.14 `timecore/1.1` · T-02 · W-G2 · W §7.4).

파일 9종의 열이 계약 그대로 · 같은 입력(행 순서를 섞어도) → 같은 바이트 · 시간량 정수 · 날짜 원장 합 = 봉투 · 구간 원장
분 합 = 구간 길이 · tasks.json 열 · run_meta · analyze_time 인자 형(키·달력·설정) · 달력 미확인 연도 거부 ·
write_time_files(경로 메서드 하나로만).
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from lm27.time import CORE_VERSION, analyze_time, write_time_files
from lm27.time.calendar import SLOT, Calendar, UnknownYearError
from lm27.time.ledger import FILES, day_ledger, interval_ledger, task_ledger
from tests.fixtures.wp20 import harness as H
from tests.time import scenarios as X

COLS = {
    "env_slots.jsonl": {"date", "slot", "tag", "basis", "conf", "on_leave", "pcs"},
    "day_ledger.jsonl": {"date", "total_min", "components", "deductions", "excluded", "by_tag_min", "conf_min",
                         "coverage", "flags"},
    "interval_ledger.jsonl": {"date", "a", "b", "tag", "basis", "targets", "note"},
    "attrib.jsonl": {"slot", "target", "sec", "level", "obs", "app", "fam"},
}
TASK_COLS = {"unit_id", "kind", "label", "conv", "peer", "peers", "docs", "cycles", "grade", "status", "lead_s",
             "biz_lead_s", "effort_s", "levels_s", "parallel", "machine_s", "pre_request_s", "flags", "proj",
             "first_key", "follow_of"}
MONTH_COLS = {"month", "workdays", "covered_workdays", "absence_days", "avail_days", "env_min", "by_tag_min",
              "attributed_min", "unattributed_min", "buckets_min", "overtime_window_min", "overtime_daily8h_min",
              "holiday_night_min", "on_leave_min", "machine_min", "mm", "load_pct", "units_mm", "rollup"}
META_COLS = {"core_version", "calendar_version", "cfg_used", "cfg_hash", "as_of", "input_digest", "audit", "warnings"}


def jl(b: bytes) -> list[dict]:
    return [json.loads(x) for x in b.decode("utf-8").splitlines()]


class LedgerFilesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = X.base_cfg()
        cls.res = {name: H.run(fn(), cls.cfg, ref_ids=False) for name, fn in X.SC.items()}

    def test_file_set_and_columns(self):
        self.assertEqual(CORE_VERSION, "timecore/1.1")
        for name, (r, _n) in sorted(self.res.items()):
            with self.subTest(name=name):
                f = r.files()
                self.assertEqual(tuple(sorted(f)), tuple(sorted(FILES)))
                for fn, cols in COLS.items():
                    for row in jl(f[fn]):
                        self.assertEqual(set(row), cols, fn)
                tasks = json.loads(f["tasks.json"])
                for t in tasks:
                    self.assertEqual(set(t), TASK_COLS)
                    self.assertTrue(all(isinstance(v, int) for v in t["levels_s"].values()))
                    self.assertEqual(set(t["levels_s"]), {"L1", "L2", "L3", "L4", "L5", "L6", "L7"})
                    self.assertEqual(sum(t["levels_s"].values()), t["effort_s"])
                    for c in t["cycles"]:
                        self.assertEqual(set(c), {"s", "sb", "e", "eb", "s_ref", "e_ref", "interim", "unstarted"})
                    for p in t["peers"]:
                        self.assertEqual(set(p), {"who_key", "rel"})
                        self.assertIn(p["rel"], ("requester", "reporter", "thread", "meeting"))
                    for d in t["docs"].values():
                        self.assertEqual(set(d), {"n", "ops"})
                        self.assertEqual(d["n"], sum(d["ops"].values()))
                months = json.loads(f["mm_month.json"])
                for m in months:
                    self.assertLessEqual(MONTH_COLS, set(m))
                    self.assertTrue(all(isinstance(m[k], int) for k in ("env_min", "attributed_min",
                                                                          "unattributed_min", "machine_min")))
                meta = json.loads(f["run_meta.json"])
                self.assertEqual(set(meta), META_COLS)
                self.assertEqual(meta["core_version"], "timecore/1.1")
                self.assertTrue(all(k.startswith(("time.", "episode.", "mm.", "privacy.time.", "pc.files."))
                                    for k in meta["cfg_used"]), sorted(meta["cfg_used"]))
                self.assertRegex(meta["as_of"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d$")

    def test_bytes_deterministic_under_shuffle(self):
        """T-02 · W-G2: 같은 입력 → 같은 바이트, 입력 행 순서를 섞어도 같다(정준 정렬)."""
        bad = []
        for name, fn in X.SC.items():
            a = self.res[name][0].files()
            for seed in (1000, 1001):
                b = H.run(fn(), self.cfg, ref_ids=False, shuffle=seed)[0].files()
                if a != b:
                    bad.append((name, seed, sorted(k for k in a if a[k] != b[k])))
        self.assertEqual(bad, [])

    def test_day_ledger_sums(self):
        for name, (r, _n) in sorted(self.res.items()):
            rows = jl(r.files()["day_ledger.jsonl"])
            self.assertEqual(sum(x["total_min"] for x in rows), len(r.env.slots) * SLOT // 60, name)
            for x in rows:
                self.assertEqual(sum(v for _k, v in x["components"]), x["total_min"], (name, x["date"]))
                self.assertEqual(sum(x["by_tag_min"].values()), x["total_min"])
                self.assertEqual(sum(x["conf_min"].values()), x["total_min"])
        w48 = jl(self.res["W48"][0].files()["day_ledger.jsonl"])
        self.assertIn(["사적차감", 30, 1], [d for x in w48 for d in x["deductions"]])

    def test_interval_ledger_minutes(self):
        for name, (r, _n) in sorted(self.res.items()):
            for x in jl(r.files()["interval_ledger.jsonl"]):
                self.assertEqual(sum(m for _k, m, _g in x["targets"]), x["b"] - x["a"], name)
                self.assertTrue(all(g in ("O", "I", "X") for _k, _m, g in x["targets"]))

    def test_text_ledgers(self):
        r, _n = self.res["W41"]
        line = day_ledger(r, "2026-10-14")
        self.assertTrue(line.startswith("2026-10-14 8:00 = C2 2:00 + C1 6:00"), line)
        lines = interval_ledger(r, "2026-10-14")
        self.assertTrue(any("L2회의(대형분할)" in x and "B_MEET" in x for x in lines))
        t = r.tasks[0]
        self.assertTrue(task_ledger(r, t.id).startswith(t.label))

    def test_analyze_time_arguments(self):
        w = X.SC["W01"]()
        recs, profile, as_of, tags, _over = X.to_inputs(w, self.cfg)
        cal = X.calendar()
        a = analyze_time(H.TEST_KEY, recs, profile, cal, as_of, cfg=self.cfg)
        b = analyze_time(H.TEST_KEY, recs, profile, X.CAL_PATH, as_of, overrides=self.cfg)
        self.assertEqual(a.files(), b.files())
        c = analyze_time(H.TEST_KEY, recs, profile, cal, as_of, overrides={"episode.e3PostPadMin": 0}, cfg=self.cfg)
        self.assertNotEqual(a.files()["tasks.json"], c.files()["tasks.json"])
        self.assertEqual(c.cfg_used["episode.e3PostPadMin"], 0)
        with self.assertRaises(TypeError):
            analyze_time("p_0123456789ab", recs, profile, cal, as_of, cfg=self.cfg)
        with self.assertRaises(TypeError):                                    # 설정 두 벌은 모호하다
            analyze_time(H.TEST_KEY, recs, profile, cal, as_of, overrides=self.cfg, cfg=self.cfg)

    def test_unknown_year_refused(self):
        w = X.W("Y2030", "2030-03-04", "2030-03-04", "2030-03-05 09:00")
        X.office_day(w, "PC1", "2030-03-04")
        recs, profile, as_of, tags, _over = X.to_inputs(w, self.cfg)
        with self.assertRaises(UnknownYearError):
            analyze_time(H.TEST_KEY, recs, profile, X.calendar(), as_of, cfg=self.cfg)

    def test_write_time_files(self):
        r, _n = self.res["W17"]
        with tempfile.TemporaryDirectory(prefix="lm27t_wp20_") as td:
            class FakePaths:
                def analysis_time_file(self, run_id, name):
                    return Path(td, run_id, "time", name)
            out = write_time_files(FakePaths(), "20261030-180000-abcd", r)
            self.assertEqual(len(out), 9)
            for p in out:
                self.assertEqual(Path(p).read_bytes(), r.files()[Path(p).name])
            self.assertFalse([x for x in os.listdir(Path(td, "20261030-180000-abcd", "time")) if x.endswith(".part")])
        with self.assertRaises(AttributeError):          # Paths.analysis_time_file 하나로만(W1 통합 창에서 생김 — 대체 경로 없음)
            write_time_files(object(), "20261030-180000-abcd", r)

    def test_period_clip(self):
        """분석 기간 밖 날짜(앞뒤 여유일)의 슬롯은 결과에 싣지 않는다 — 팀 묶음 envelope_daily 는 '기간 안' 행만."""
        w = X.SC["W46"]()
        w.d0 = "2026-10-01"                                                   # 9/30 근거는 기간 밖
        r, _n = H.run(w, self.cfg, ref_ids=False)
        dates = {row[0] for row in r.tables.as_json()["envelope_daily"]["rows"]}
        self.assertEqual(dates, {"2026-10-01"})
        self.assertEqual({x["date"] for x in jl(r.files()["day_ledger.jsonl"])}, {"2026-10-01"})
        self.assertEqual(set(r.months), {(2026, 10)})
        self.assertTrue(any("기간 밖" in x for x in r.warnings))
        self.assertEqual(sum(sum(d.values()) for d in r.assign.values()), len(r.env.slots) * SLOT)

    def test_calendar_object_from_obj(self):
        obj = json.loads(X.CAL_PATH.read_text(encoding="utf-8"))
        cal = Calendar.from_obj(obj, source="registry")
        r, _n = H.run(X.SC["W46"](), self.cfg, ref_ids=False)
        w = X.SC["W46"]()
        recs, profile, as_of, tags, _over = X.to_inputs(w, self.cfg)
        r2 = analyze_time(H.TEST_KEY, recs, profile, cal, as_of, cfg=self.cfg, tags=tags)
        self.assertEqual(r.files()["team_tables.json"], r2.files()["team_tables.json"])


if __name__ == "__main__":
    unittest.main()
