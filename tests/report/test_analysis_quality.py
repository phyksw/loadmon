# -*- coding: utf-8 -*-
"""WP-30 측정 품질 등급(R §4.9 · RPT-26 — 팀 묶음도 같은 `quality_month()`).

- RPT-26: 합성 달 4개(정상 · 팀즈 70% · PC 40% · 봉투 0) → reliable · caution(teams_cov_low) · unreliable(pc_cov_bad) ·
  unreliable(no_envelope).
- partial 근무일은 0.5 · 커버리지 정보가 없는 축은 판정하지 않음 · 근무일 0 이면 '' · 기간 등급 = 가장 나쁜 달.
- 날짜 사실 → 입력: 오늘은 표준창 끝을 지났을 때만 · 근거 없는 근무일은 연차·확인된 부재를 뺀다.
"""
from __future__ import annotations

import unittest

from lm27.report import vocab as V
from lm27.report.analysis import quality as Q
from tests.fixtures.wp30 import world as W


def mctx(**kw):
    base = {"W": 20, "cov": dict.fromkeys(Q.AXES, (20, 0)), "sampler_days": 20, "env_min": 9600, "low_min": 0,
            "unattr_min": 200, "no_ev": 0, "coarse": False}
    base.update(kw)
    return base


class QualityMonthTest(unittest.TestCase):
    def setUp(self):
        self.cfg = W.cfg()

    def test_rpt26(self):
        normal = Q.quality_month(mctx(), self.cfg)
        self.assertEqual((normal["grade"], normal["reasons"]), ("reliable", []))
        cov = dict(mctx()["cov"], teams=(14, 0))
        teams = Q.quality_month(mctx(cov=cov), self.cfg)
        self.assertEqual((teams["grade"], teams["reasons"]), ("caution", ["teams_cov_low"]))
        self.assertEqual(teams["cov"]["teams"], 0.7)
        cov = dict(mctx()["cov"], pc=(8, 0))
        pc = Q.quality_month(mctx(cov=cov), self.cfg)
        self.assertEqual((pc["grade"], pc["reasons"]), ("unreliable", ["pc_cov_bad"]))
        empty = Q.quality_month(mctx(env_min=0, low_min=0, unattr_min=0, sampler_days=0, no_ev=20), self.cfg)
        self.assertEqual((empty["grade"], empty["reasons"]), ("unreliable", ["no_envelope"]))
        self.assertEqual(empty["est_ratio"], 1.0)

    def test_other_reasons(self):
        cov = dict(mctx()["cov"], mail_out=(8, 0), teams=(9, 0), cal=(15, 2))
        r = Q.quality_month(mctx(cov=cov, low_min=5000, unattr_min=3500, no_ev=3, sampler_days=8), self.cfg)
        self.assertEqual(r["grade"], "unreliable")
        self.assertEqual(r["reasons"], ["comms_cov_bad", "estimated_bad", "unattributed_high", "no_evidence_days",
                                        "sampler_absent"])
        self.assertEqual(r["cov"]["cal"], 0.8)                                   # (15 + 0.5 × 2) / 20 = 0.8 — 낮음 아님
        r2 = Q.quality_month(mctx(cov=dict(mctx()["cov"], cal=(15, 1)), low_min=2500), self.cfg)
        self.assertEqual(r2["reasons"], ["cal_cov_low", "estimated_high"])
        unknown = Q.quality_month(mctx(cov=dict(mctx()["cov"], teams=None)), self.cfg)
        self.assertEqual(unknown["grade"], "reliable")
        self.assertIsNone(unknown["cov"]["teams"])
        none = Q.quality_month(mctx(W=0), self.cfg)
        self.assertEqual((none["grade"], none["reasons"]), ("", []))
        coarse = Q.quality_month(mctx(coarse=True), self.cfg)
        self.assertEqual((coarse["grade"], coarse["reasons"]), ("reliable", ["mining_coarse"]))

    def test_thresholds(self):
        cov = dict(mctx()["cov"], teams=(14, 0))
        r = Q.quality_month(mctx(cov=cov), W.cfg(**{"report.quality.covLow": 0.6}))
        self.assertEqual(r["grade"], "reliable")
        r = Q.quality_month(mctx(no_ev=1), W.cfg(**{"report.quality.noEvidenceDays": 0}))
        self.assertEqual(r["reasons"], ["no_evidence_days"])

    def test_period_and_texts(self):
        months = {"2026-08": Q.quality_month(mctx(), self.cfg),
                  "2026-09": Q.quality_month(mctx(cov=dict(mctx()["cov"], teams=(14, 0))), self.cfg),
                  "2026-10": Q.quality_month(mctx(W=0), self.cfg)}
        p = Q.period_quality(months)
        self.assertEqual(p, {"grade": "caution", "reasons": ["teams_cov_low"],
                             "by_month": {"2026-08": "reliable", "2026-09": "caution", "2026-10": ""}})
        t = Q.quality_texts(months["2026-09"])
        self.assertEqual(t, [{"code": "teams_cov_low", "text": "팀즈 기록이 비어 있는 근무일이 있습니다(70%)"}])
        t = Q.quality_texts(Q.quality_month(mctx(no_ev=3), self.cfg))
        self.assertEqual(t[0]["text"], "근거가 하나도 없는 근무일이 3일 있습니다(확인 질문 Q09)")

    def test_period_texts_every_reason(self):
        """W2 검토 C09: 기간 문구는 모든 사유에 하나씩 — 그 사유를 낸 달의 숫자로(가장 나쁜 달의 사유만이 아니다)."""
        cov_aug = dict(mctx()["cov"], pc=(0, 0), mail_out=None)
        months = {"2026-07": Q.quality_month(mctx(cov=cov_aug, env_min=0, low_min=0, unattr_min=0), self.cfg),
                  "2026-08": Q.quality_month(mctx(cov=cov_aug, env_min=0, low_min=0, unattr_min=0), self.cfg),
                  "2026-09": Q.quality_month(mctx(cov=dict(mctx()["cov"], mail_out=(11, 0)), low_min=2500,
                                                  unattr_min=3500, no_ev=3), self.cfg)}
        p = Q.period_quality(months)
        self.assertEqual(p["grade"], "unreliable")
        texts = Q.period_texts(p["reasons"], months)
        self.assertEqual([t["code"] for t in texts], p["reasons"])           # 사유마다 문구 하나(빈칸 없음)
        by = {t["code"]: t["text"] for t in texts}
        self.assertEqual(by["mail_cov_low"], "메일 보냄 기록이 비어 있는 근무일이 있습니다(55%)")   # 9월 값(11/20)
        self.assertIn("26%", by["estimated_high"])                            # 2500/9600 — 9월 값
        self.assertEqual(by["no_evidence_days"], "근거가 하나도 없는 근무일이 3일 있습니다(확인 질문 Q09)")
        self.assertEqual(by["no_envelope"], V.QUALITY_PERIOD_TEXT["no_envelope"].format(n=2))   # 기간형 — '이 달은' 아님
        self.assertIn("PC 기록이 있는 근무일이 0%", by["pc_cov_bad"])

    def test_layer_texts_from_world(self):
        """분석 문맥 전체로: 수집 전 달(봉투 0) + 메일 보냄이 절반만 있는 달 → 기간 문구에 mail_cov_low 가 숫자로 있다."""
        w = W.World("2026-08-01", "2026-09-13", "2026-09-13T12:00")
        w.unit("u_q1", start=("2026-09-01", "09:00"), end=("2026-09-11", "17:00"))
        days = ("2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04", "2026-09-07", "2026-09-08", "2026-09-09",
                "2026-09-10", "2026-09-11")
        for i, d in enumerate(days):
            w.run("u_q1", "DOC_DOC", d, "09:00", "17:00")
            w.cover(d, mail_out="ok" if i % 2 == 0 else "blocked", mail_in="ok", cal="ok", teams="ok")
        q = Q.quality_layer(w.context())
        self.assertEqual([t["code"] for t in q["texts"]], q["reasons"])
        self.assertIn("mail_cov_low", q["reasons"])
        by = {t["code"]: t["text"] for t in q["texts"]}
        self.assertEqual(by["mail_cov_low"], q["months"]["2026-09"]["texts"][0]["text"])
        self.assertNotIn("이 달은", by["no_envelope"])


class MonthCtxTest(unittest.TestCase):
    def test_from_world(self):
        w = W.World("2026-09-01", "2026-09-30", "2026-09-30T12:00")
        w.unit("u_q1", start=("2026-09-01", "09:00"), end=("2026-09-29", "17:00"))
        for d in ("2026-09-01", "2026-09-02", "2026-09-03"):
            w.run("u_q1", "DOC_DOC", d, "09:00", "12:00")
            w.cover(d, mail_out="ok", mail_in="ok", cal="zero_ok", teams="partial")
        w.cover("2026-09-04", mail_out="blocked", teams="ok")
        w.leave("2026-09-07", "full")
        ctx = w.context()
        m = Q.month_ctx(ctx, "2026-09")
        # 9월 근무일 20 — 30일(오늘)은 12:00 이라 표준창 끝(18:00) 전 → 빼서 19
        self.assertEqual(m["W"], 19)
        self.assertEqual(m["cov"]["mail_out"], (3, 0))
        self.assertEqual(m["cov"]["teams"], (1, 3))
        self.assertEqual(m["cov"]["pc"], (3, 0))                               # 샘플러 근거 슬롯이 있는 날
        self.assertEqual(m["sampler_days"], 3)
        self.assertEqual(m["env_min"], 540)
        self.assertEqual(m["no_ev"], 19 - 3 - 1)                               # 연차 1일 제외
        q = Q.quality_layer(ctx)
        self.assertEqual(q["by_month"], {"2026-09": q["months"]["2026-09"]["grade"]})
        self.assertEqual(q["grade"], "unreliable")
        self.assertIn("pc_cov_bad", q["reasons"])


if __name__ == "__main__":
    unittest.main()
