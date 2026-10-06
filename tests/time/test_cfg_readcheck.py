# -*- coding: utf-8 -*-
"""WP-20 설정 read-check(W-G6 · T-14 · 계약 §5.1-6 '죽은 키 금지').

① 시간 코어 B 가 읽는 등록 키(owner 가 lm27.time.episodes·attribute·mm·queue 이거나 readers 에 든 키)는 분석에서 모두
   읽힌다(`run_meta.cfg_used`). 시간 코어 A(evidence·envelope)·calendar·tokens 키도 함께 확인한다.
② 수치·선택 키는 값을 바꾸면 결과(run_meta 를 뺀 결과 파일 바이트)가 바뀐다 — 시나리오 83개와 합성 세계 중 하나에서.
③ 미등록 키는 오류(UnknownKeyError).
"""
from __future__ import annotations

import json
import unittest

from lm27.config import UnknownKeyError
from tests.fixtures.wp20 import harness as H
from tests.time import scenarios as X

MINE = ("lm27.time.episodes", "lm27.time.attribute", "lm27.time.mm", "lm27.time.queue")
CORE = MINE + ("lm27.time.evidence", "lm27.time.envelope", "lm27.time.tokens", "lm27.time.calendar")
PERTURB = {   # 값은 레지스트리 범위 안 — 결과가 바뀌어야 '살아 있는 키'
    "episode.autosaveQuietWd": 30, "episode.dormantWd": 1, "episode.e2High": 0.95, "episode.e2Low": 0.95,
    "episode.e2TailMin": 0, "episode.e2Weights": {"quiet": 0.1, "export": 0.1, "final": 0.1, "result": 0.1,
                                                  "attached": 0.1},
    "episode.e3PostPadMin": 0, "episode.e3cLookaheadH": 0, "episode.giantDays": 1, "episode.giantNodes": 10,
    "episode.link.multiCloseSim": 0.99, "episode.link.reportSim": 0.99, "episode.link.sendTokenSim": 0.99,
    "episode.link.theta": 9.0, "episode.link.wProject": 0.0, "episode.link.wTime": 0.0, "episode.link.wToken": 0.5,
    "episode.linkWindowWd": 0, "episode.meetLinkMin": 20.0, "episode.preStartTolMin": 1440, "episode.preWorkH": 0,
    "episode.quietWd": 20, "episode.recurringMaxDaysPerWeek": 1, "episode.recurringMinWeeks": 20,
    "episode.reopenQuietWd": 60, "episode.requestMaxParticipants": 1, "episode.requireCommsCoverageForE3": False,
    "episode.reworkWindowWd": 0, "episode.s2MeetLookbackH": 0, "episode.s2PrePadMin": 0, "episode.selfMergeDays": 0,
    "episode.selfMergeSim": 0.0, "episode.sharedDocMinTasks": 2, "episode.splitWd": 1, "episode.supplementWd": 0,
    "episode.tokens.minSubLen": 9, "episode.unstartedWd": 120,
    "time.attrib.absorbGenericMaxMin": 0, "time.attrib.floorNearMin": 0, "time.attrib.gapSplitMaxMin": 0,
    "time.attrib.l6MaxRatio": 0.0, "time.attrib.meetAbsentCover": 0.0, "time.attrib.meetSplitMinAtt": 50,
    "time.attrib.meetSplitShare": 0.9, "time.attrib.pointWeightSec": 1, "time.attrib.postPadMin": 0,
    "time.attrib.solverAbsorbGeneric": False,
    "time.queue.bucketRunMin": 600, "time.queue.gapMin": 600, "time.queue.maxPerWeek": 1,
    "time.queue.minEffortH": 99.0, "time.queue.openLongWd": 1, "time.queue.parallelSuspect": 1.0,
    "time.queue.solverDayH": 24.0, "time.envelope.longDayH": 9.0,
    "mm.denominator": "weekdays", "mm.inferredAbsence": "exclude", "mm.overtimeBasis": "daily8h",
}


def recur2_world():
    """주 2일씩 4주 손대는 문서(반복 판정 경계 — recurringMaxDaysPerWeek 섭동용)."""
    w = X.W("RECUR2", "2026-09-01", "2026-09-30", "2026-10-30 18:00")
    for day in ("2026-09-01", "2026-09-03", "2026-09-08", "2026-09-10", "2026-09-15", "2026-09-17",
                "2026-09-22", "2026-09-29"):
        w.on("PC1", f"{day} 15:55", f"{day} 17:05")
        w.samp("PC1", f"{day} 16:00", f"{day} 17:00", "office", "점검일지_과제E.xlsx")
        w.doc(f"{day} 16:55", "save", "점검일지_과제E.xlsx")
    return w


def multi_world():
    """보고 1통에 다른 의뢰의 산출로 보이는 첨부(토큰 유사 0.67) — 다대다 종료 문턱(multiCloseSim) 섭동용."""
    w = X.W("MULTI", "2026-10-12", "2026-10-13", "2026-10-30 18:00")
    w.msg("2026-10-12 09:30", "in", "request", "M1", "P1", tokens=("원가분석", "과제F"))
    w.msg("2026-10-12 10:00", "in", "request", "M2", "P1", tokens=("일정", "과제G"))
    X.office_day(w, "PC1", "2026-10-12", [("10:10", "12:00", "office", "원가분석_과제F.xlsx")])
    X.office_day(w, "PC1", "2026-10-13")
    w.doc("2026-10-12 11:50", "save", "원가분석_과제F.xlsx")
    w.msg("2026-10-13 16:30", "out", "report", "M1", "P1", atts=("원가분석_과제F.xlsx", "일정표.xlsx"),
          tokens=("원가분석",))
    return w


def worlds():
    out = dict(X.SC)
    out["RECUR2"] = recur2_world
    out["MULTI"] = multi_world
    out["GEN1W"] = lambda: H.gen_months(0.25, 26)[0]           # 참조 gates.cfg 의 1주 합성 세계
    return out


def signature(res) -> bytes:
    f = res.files()
    return b"\x00".join(v for k, v in sorted(f.items()) if k != "run_meta.json")


class CfgReadCheckTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = X.base_cfg()
        cls.worlds = worlds()
        cls.base = {}
        cls.read = set()
        for name, fn in cls.worlds.items():
            r, _n = H.run(fn(), cls.cfg, ref_ids=False)
            cls.base[name] = signature(r)
            cls.read |= set(json.loads(r.files()["run_meta.json"])["cfg_used"])

    def registry_keys(self, owners, *, readers=True):
        out = []
        for k in self.cfg.keys():
            meta = self.cfg.meta(k)
            if meta.owner in owners or (readers and any(x in owners for x in (meta.readers or ()))):
                out.append(k)
        return sorted(out)

    def test_all_time_core_keys_read(self):
        mine = self.registry_keys(MINE)
        self.assertTrue(mine)
        self.assertEqual(sorted(set(mine) - self.read), [], "읽히지 않은 시간 코어 B 키")
        core = self.registry_keys(CORE)
        self.assertEqual(sorted(set(core) - self.read), [], "읽히지 않은 시간 코어 키")

    def test_perturbation_changes_results(self):
        mine = [k for k in self.registry_keys(MINE, readers=False)                 # 이 작업 패키지가 owner 인 키
                if self.cfg.meta(k).type in ("int", "float", "bool", "enum", "obj")]
        self.assertEqual(sorted(set(mine) - set(PERTURB)), [], "섭동 표에 없는 수치·선택 키")
        unchanged = []
        for k, v in sorted(PERTURB.items()):
            c = self.cfg.derive({k: v})
            self.assertFalse([w for w in c.config_warnings if w["key"] == k], (k, v))   # 섭동값이 범위 안
            changed = False
            for name, fn in self.worlds.items():
                r, _n = H.run(fn(), c, ref_ids=False)
                if signature(r) != self.base[name]:
                    changed = True
                    break
            if not changed:
                unchanged.append(k)
        self.assertEqual(unchanged, [], "값을 바꿔도 결과가 그대로인 키(죽은 키)")

    def test_unknown_key_is_error(self):
        with self.assertRaises(UnknownKeyError):
            self.cfg["episode.noSuchKey"]
        with self.assertRaises(UnknownKeyError):
            self.cfg.derive({"time.queue.noSuchKey": 1})


if __name__ == "__main__":
    unittest.main()
