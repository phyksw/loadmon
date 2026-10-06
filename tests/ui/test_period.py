# -*- coding: utf-8 -*-
"""기간 빠른 선택(올해·1~4분기·상반기·하반기) — lm27\\ui\\period.py 규칙 · 화면 API 기본 기간 · CLI analyze 기본 기간.

사용자 결정(2026-10-06): 기본 = 올해 1월 1일 ~ 오늘, 필요하면 1분기·2분기·3분기·4분기·상반기·하반기.
골든 = tests\\fixtures\\wp35\\period_cases.json(손으로 쓴 기대값) — JS 판(web\\common\\lm27ui.js)은 tests\\web\\common_test.js 가
같은 표로 시험하고, 날짜 수백 개를 동봉 파이썬과 직접 대조한다. 합성 날짜만 쓴다(실제 수집·분석 없음)."""
import contextlib
import io
import json
import os
import shutil
import tempfile
import time
import unittest
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from lm27 import cli
from lm27.paths import Paths
from lm27.ui import jobs as J
from lm27.ui import period as P
from lm27.util import events
from tests.fixtures.wp35.harness import Running, Sandbox

CASES = json.loads((Path(__file__).resolve().parents[1] / "fixtures" / "wp35" / "period_cases.json").read_text(encoding="utf-8"))


def tip_of(a, b, state):
    if state == "future":
        return a + " ~ " + b + " — 아직 오지 않은 기간이라 고를 수 없습니다"
    return a + " ~ " + b + ("(진행 중 — 끝은 오늘)" if state == "partial" else "")


def rng(today):
    """{키: (from, to, 상태)} — 상태 full·partial·future."""
    out = {}
    for p in P.presets(today):
        out[p["key"]] = (p["from"], p["to"], "future" if p["disabled"] else ("partial" if p["partial"] else "full"))
    return out


class PresetRuleTest(unittest.TestCase):
    def test_golden_table(self):
        for d, exp in CASES["presets"].items():
            want = [{"key": k, "label": CASES["labels"][k], "from": exp[k][0], "to": exp[k][1], "disabled": exp[k][2] == "future",
                     "partial": exp[k][2] == "partial", "tip": tip_of(*exp[k])} for k in CASES["order"]]
            self.assertEqual(P.presets(d), want, d)
            self.assertEqual(P.presets(date.fromisoformat(d)), want, d + " (date)")
            self.assertEqual(P.presets(datetime.fromisoformat(d + "T23:59:00")), want, d + " (datetime)")

    def test_default_is_jan1_to_today(self):
        for d, (f, t) in CASES["default"].items():
            self.assertEqual(P.default_range(d), (f, t), d)
        self.assertEqual(P.default_range("2026-10-06"), ("2026-01-01", "2026-10-06"))
        self.assertEqual([p["key"] for p in P.presets("2026-10-06")], ["ytd", "q1", "q2", "q3", "q4", "h1", "h2"])
        self.assertEqual(P.DEFAULT_KEY, "ytd")

    def test_quarter_boundaries(self):
        r = rng("2026-10-06")
        self.assertEqual(r["q1"], ("2026-01-01", "2026-03-31", "full"))
        self.assertEqual(r["q2"], ("2026-04-01", "2026-06-30", "full"))
        self.assertEqual(r["q3"], ("2026-07-01", "2026-09-30", "full"))
        self.assertEqual(r["q4"], ("2026-10-01", "2026-10-06", "partial"), "4분기 = 10-01 ~ 12-31 을 오늘로 줄임")
        self.assertEqual(rng("2026-09-30")["q3"], ("2026-07-01", "2026-09-30", "partial"), "분기 마지막 날 = 진행 중(끝 = 오늘)")
        self.assertEqual(rng("2026-09-30")["q4"], ("2026-10-01", "2026-12-31", "future"))
        self.assertEqual(rng("2026-10-01")["q4"], ("2026-10-01", "2026-10-01", "partial"), "분기 첫날 = 하루짜리 기간")
        self.assertEqual(rng("2026-10-01")["q3"], ("2026-07-01", "2026-09-30", "full"))
        self.assertEqual(rng("2026-12-31")["q4"], ("2026-10-01", "2026-12-31", "partial"))

    def test_halves(self):
        r = rng("2026-10-06")
        self.assertEqual(r["h1"], ("2026-01-01", "2026-06-30", "full"))
        self.assertEqual(r["h2"], ("2026-07-01", "2026-10-06", "partial"))
        r = rng("2026-06-30")
        self.assertEqual((r["h1"], r["h2"]), (("2026-01-01", "2026-06-30", "partial"), ("2026-07-01", "2026-12-31", "future")))

    def test_future_ranges_disabled(self):
        r = rng("2026-05-20")
        self.assertEqual({k for k, v in r.items() if v[2] == "future"}, {"q3", "q4", "h2"})
        for p in P.presets("2026-05-20"):
            if p["disabled"]:
                self.assertIn("아직 오지 않은 기간", p["tip"])
                self.assertIsNone(P.preset_range(p["key"], "2026-05-20"))
        self.assertEqual(P.preset_range("q2", "2026-05-20"), ("2026-04-01", "2026-05-20"))
        self.assertTrue(all(not p["disabled"] for p in P.presets("2026-12-31")), "12월 31일이면 모두 고를 수 있다")
        self.assertEqual({p["key"] for p in P.presets("2026-01-01") if p["disabled"]}, {"q2", "q3", "q4", "h2"})

    def test_leap_years(self):
        self.assertEqual(rng("2024-02-29")["q1"], ("2024-01-01", "2024-02-29", "partial"))
        self.assertEqual(P.default_range("2024-02-29"), ("2024-01-01", "2024-02-29"))
        self.assertEqual(rng("2024-12-31")["ytd"], ("2024-01-01", "2024-12-31", "partial"))    # 윤년 366일 — 끝 = 오늘
        self.assertEqual(rng("2028-03-01")["q1"], ("2028-01-01", "2028-03-01", "partial"))
        self.assertEqual(rng("2000-02-29")["q1"], ("2000-01-01", "2000-02-29", "partial"))     # 400의 배수 = 윤년
        for bad in ("2025-02-29", "2100-02-29", "2026-02-30"):                                     # 평년 2월 29일·없는 날
            with self.assertRaises(ValueError):
                P.presets(bad)
        self.assertEqual(rng("2100-03-01")["q1"], ("2100-01-01", "2100-03-01", "partial"))

    def test_key_of_and_source(self):
        for f, t, today, k in CASES["key_of"]:
            self.assertEqual(P.key_of(f, t, today), k, (f, t, today))
        for k, s in CASES["period_source"]:
            self.assertEqual(P.period_source(k), s, k)

    def test_range_for_source(self):
        today = "2026-05-20"
        self.assertEqual(P.range_for_source(None, today), ("2026-01-01", "2026-05-20"))
        self.assertEqual(P.range_for_source("default", today), ("2026-01-01", "2026-05-20"))
        self.assertEqual(P.range_for_source("q1", today), ("2026-01-01", "2026-03-31"))
        self.assertEqual(P.range_for_source("h1", today), ("2026-01-01", "2026-05-20"))
        self.assertIsNone(P.range_for_source("q3", today), "아직 오지 않은 분기")
        for src in ("this_month", "last_month", "this_year", "user", "ytd", "q5"):
            self.assertIsNone(P.range_for_source(src, today), src)

    def test_bad_today(self):
        for d in CASES["bad_today"] + [None, 20261006, "2026-10-06\n", "２０２６-10-06"]:
            with self.assertRaises(ValueError, msg=repr(d)):
                P.presets(d)

    def test_today_local_uses_work_offset(self):
        now = datetime(2026, 10, 5, 16, 30, tzinfo=UTC)
        self.assertEqual(P.today_local(540, now), date(2026, 10, 6), "+09:00 이면 이미 다음 날")
        self.assertEqual(P.today_local(0, now), date(2026, 10, 5))
        self.assertEqual(P.today_local(-300, now), date(2026, 10, 5))
        self.assertEqual(P.today_local(540, datetime(2026, 12, 31, 15, 0)), date(2027, 1, 1), "naive = UTC · 해 넘김")
        self.assertEqual(P.default_range(P.today_local(540, datetime(2026, 12, 31, 15, 0, tzinfo=UTC))), ("2027-01-01", "2027-01-01"))
        kst = datetime(2026, 10, 6, 1, 30, tzinfo=timezone(timedelta(hours=9)))
        self.assertEqual(P.today_local(540, kst), date(2026, 10, 6))
        self.assertIsInstance(P.today_local(540), date)

    def test_period_sources_copy_in_cli(self):
        """cli 의 PERIOD_SOURCES 는 이 모듈 튜플의 사본(--help 가 import 하지 않게) — 같아야 한다. 'rerun' 은 받지 않는다."""
        self.assertEqual(cli.PERIOD_SOURCES, P.PERIOD_SOURCES)
        self.assertNotIn("rerun", P.PERIOD_SOURCES)
        for k, _label in P.PRESETS:
            self.assertIn(P.period_source(k), P.PERIOD_SOURCES)
        p = cli.build_parser()
        for src in P.PERIOD_SOURCES:
            a = p.parse_args(["analyze", "--from", "2026-07-01", "--to", "2026-09-30", "--period-source", src])
            self.assertEqual(a.period_source, src)


def _wait_job(app, jid, timeout=20.0):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        v = app.jobs.get(jid)
        if v and v["state"] in J.FINISHED:
            return v
        time.sleep(0.05)
    return app.jobs.get(jid)


class ApiDefaultPeriodTest(unittest.TestCase):
    """화면 API — 날짜를 주지 않으면 같은 규칙의 기본 기간(근무 시간대의 오늘), GET runs 의 defaults.period 는 규칙 그대로."""

    def setUp(self):
        self.sb = Sandbox()
        self.addCleanup(self.sb.cleanup)
        self.app = self.sb.app(behaviour={"analyze": {"sleep": 0}})
        self.app.deps.now = lambda: datetime(2026, 10, 5, 16, 30, tzinfo=UTC)      # 근무 시간대(+09:00)로는 10-06 01:30
        self.srv = Running(self.app).__enter__()
        self.addCleanup(self.srv.close)

    def _argv(self, body):
        st, b, _ = self.srv.req("POST", "/api/analysis/run", body)
        self.assertEqual(st, 200, b)
        return _wait_job(self.app, b["job_id"])["result"]["argv"]

    def test_runs_defaults_period(self):
        st, runs, _ = self.srv.req("GET", "/api/analysis/runs")
        self.assertEqual(st, 200, runs)
        per = runs["defaults"]["period"]
        self.assertEqual((per["today"], per["key"], per["from"], per["to"]), ("2026-10-06", "ytd", "2026-01-01", "2026-10-06"))
        self.assertEqual(per["presets"], P.presets("2026-10-06"))
        self.assertEqual(runs["defaults"]["months"], 3)                               # 옛 키(설정은 레지스트리에 남음)

    def test_post_without_dates_uses_default(self):
        self.assertEqual(self._argv({"ai": False}),
                         ["analyze", "--from", "2026-01-01", "--to", "2026-10-06", "--period-source", "default", "--no-ai"])
        self.assertEqual(self._argv({"ai": False, "from": "", "to": "", "period_source": "q3"}),
                         ["analyze", "--from", "2026-07-01", "--to", "2026-09-30", "--period-source", "q3", "--no-ai"])
        self.assertEqual(self._argv({"ai": False, "period_source": "h2"}),
                         ["analyze", "--from", "2026-07-01", "--to", "2026-10-06", "--period-source", "h2", "--no-ai"])

    def test_explicit_dates_and_sources_kept(self):
        self.assertEqual(self._argv({"from": "2026-04-01", "to": "2026-06-30", "ai": False, "period_source": "q2"}),
                         ["analyze", "--from", "2026-04-01", "--to", "2026-06-30", "--period-source", "q2", "--no-ai"])
        self.assertEqual(self._argv({"from": "2026-02-15", "to": "2026-06-30", "ai": False, "period_source": "user"})[-3:],
                         ["--period-source", "user", "--no-ai"])

    def test_rejects(self):
        for bad in ({"from": "2026-07-01"}, {"to": "2026-07-01"}, {"period_source": "this_month"},
                    {"from": "2026-07-01", "to": "2026-09-30", "period_source": "q5"}):
            st, b, _ = self.srv.req("POST", "/api/analysis/run", bad)
            self.assertEqual(st, 400, bad)
        self.app.deps.now = lambda: datetime(2026, 5, 20, 3, 0, tzinfo=UTC)
        st, b, _ = self.srv.req("POST", "/api/analysis/run", {"period_source": "q4"})
        self.assertEqual((st, b["code"]), (400, "bad_period"), "아직 오지 않은 분기")


class CliDefaultPeriodTest(unittest.TestCase):
    """lm27 analyze — --from/--to 를 둘 다 빼면 기본 기간(올해 1월 1일 ~ 오늘), 하나만 주면 오류(옛 동작), 둘 다 주면 그대로."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="lm27t_period_cli_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.paths = Paths(self.tmp, lad=os.path.join(self.tmp, "lad"))
        self.addCleanup(events.configure, "text")

    def run_cli(self, argv, today=date(2026, 10, 6)):
        got = {}
        real = cli.resolve

        def res(mod, attr):
            if (mod, attr) == ("lm27.pipeline.analyze", "analyze"):
                def analyze(*a, **k):
                    got.update(k)
                    return 0
                return analyze
            if (mod, attr) == ("lm27.ui.period", "today_local"):
                def today_local(off_min, now=None):
                    got["off"] = off_min
                    return today
                return today_local
            return real(mod, attr)

        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(cli, "resolve", res), \
                mock.patch.object(cli.Ctx, "cfg", lambda s, overrides=None: {"time.tzOffsetMin": 540}), \
                mock.patch.object(cli.Ctx, "paths", self.paths), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = cli.main(list(argv))
        return rc, got, err.getvalue()

    def test_no_dates_default_year_to_today(self):
        rc, got, err = self.run_cli(["analyze", "--no-ai"])
        self.assertEqual(rc, 0, err)
        self.assertEqual((got["from_"], got["to"], got["period_source"], got["off"]), ("2026-01-01", "2026-10-06", "default", 540))
        self.assertFalse(got["ai"])
        self.assertIn("기본(올해 1월 1일 ~ 오늘)", err)
        rc, got, _ = self.run_cli(["analyze"], today=date(2024, 2, 29))
        self.assertEqual((got["from_"], got["to"]), ("2024-01-01", "2024-02-29"), "윤년")

    def test_no_dates_with_preset_source(self):
        rc, got, err = self.run_cli(["analyze", "--period-source", "q4"])
        self.assertEqual(rc, 0, err)
        self.assertEqual((got["from_"], got["to"], got["period_source"]), ("2026-10-01", "2026-10-06", "q4"))
        self.assertIn("4분기", err)
        rc, got, err = self.run_cli(["analyze", "--period-source", "q4"], today=date(2026, 5, 20))
        self.assertEqual(rc, 1, "아직 오지 않은 분기")
        self.assertNotIn("from_", got)
        rc, got, err = self.run_cli(["analyze", "--period-source", "this_month"])
        self.assertEqual(rc, 1, "날짜와 함께 쓰는 출처")

    def test_explicit_dates_kept(self):
        rc, got, err = self.run_cli(["analyze", "--from", "2026-07-01", "--to", "2026-09-30"])
        self.assertEqual(rc, 0, err)
        self.assertEqual((got["from_"], got["to"]), ("2026-07-01", "2026-09-30"))
        self.assertNotIn("period_source", got, "명시한 날짜면 기간 출처를 덧붙이지 않는다(파이프라인 기본 user)")
        self.assertNotIn("off", got, "명시한 날짜면 오늘을 계산하지 않는다")

    def test_one_date_only_is_error(self):
        for argv in (["analyze", "--from", "2026-10-01"], ["analyze", "--to", "2026-10-01"]):
            rc, got, err = self.run_cli(argv)
            self.assertEqual(rc, 1, argv)
            self.assertIn("--to", err)
            self.assertNotIn("from_", got)
        rc, got, err = self.run_cli(["analyze", "--stages", "time"])
        self.assertEqual(rc, 1, "--stages 는 --rerun 과 함께만")


if __name__ == "__main__":
    unittest.main()
