# -*- coding: utf-8 -*-
"""WP-30 같이 일한 동료(R §4.5 · RPT-27).

- RPT-27: 참조(cc)만 받은 사람 · 30명 회의 참석자 · 대화 1건 사람 제외, 의뢰자는 동료. 대화 2건 이상 · 10명 이하 회의는 동료.
- 본인 제외, 외부는 도메인 계급 사람 수로만, 정렬 = 공유 투입 ↓ → 공동 단위업무 수 ↓ → who_key.
- 증거가 없으면 시간 코어 관계 그대로 + 경고 peers_unverified.
"""
from __future__ import annotations

import unittest

from lm27.report.analysis import peers as P
from tests.fixtures.wp30 import world as W

PERSON_DIR = {"format": "lm27-persondir/1", "people": {
    "w_req": {"names": ["김철수"], "smtp": ["user01@corp.example"], "internal": True, "self": False},
    "w_two": {"names": ["동료 둘"], "smtp": ["user02@corp.example"], "internal": True, "self": False},
    "w_small": {"names": ["동료 셋"], "smtp": ["user03@corp.example"], "internal": True, "self": False},
    "w_cc": {"names": ["참조인"], "smtp": ["user04@corp.example"], "internal": True, "self": False},
    "w_me": {"names": ["홍길동"], "smtp": ["me@corp.example"], "internal": True, "self": True},
    "w_cust": {"names": ["고객 담당"], "smtp": ["buyer@customer-a.example"], "internal": False, "self": False},
    "w_vend": {"names": ["협력 담당"], "smtp": ["sales@vendor.example"], "internal": False, "self": False},
}}
REGISTRY = {"customers": [{"id": "C01", "names": ["고객사A"], "domains": ["customer-a.example"]}],
            "partners": [{"id": "V01", "names": ["협력사"], "domains": ["vendor.example"]}]}
EVIDENCE = {
    "msgs": [{"conv": "conv1", "peer": "w_cc", "flags": ["cc"], "dir": "in"} for _ in range(3)]
    + [{"conv": "conv1", "peer": "w_one", "flags": [], "dir": "in"}]
    + [{"conv": "conv1", "peer": "w_two", "flags": [], "dir": d} for d in ("in", "out")]
    + [{"conv": "conv1", "peer": "w_req", "flags": [], "dir": "in"}],
    "meets": [{"id": "mt_big", "attendees": ["w_big", "w_small"], "n_att": 30},
              {"id": "mt_small", "attendees": ["w_small"], "n_att": 4}],
}


def world():
    w = W.World("2026-09-01", "2026-09-30", "2026-09-30T18:00")
    w.unit("u_p1", start=("2026-09-01", "09:00"), end=("2026-09-03", "17:00"), conv="conv1",
           flags=["회의연결 mt_big", "회의연결 mt_small"],
           peers=[("w_req", "requester"), ("w_cc", "thread"), ("w_big", "meeting"), ("w_one", "thread"),
                  ("w_two", "thread"), ("w_small", "meeting"), ("w_me", "thread")])
    w.run("u_p1", "DOC_DOC", "2026-09-01", "10:00", "12:00")
    w.unit("u_p2", start=("2026-09-07", "09:00"), end=("2026-09-08", "17:00"), conv="conv2",
           peers=[("w_req", "reporter"), ("w_cust", "requester"), ("w_vend", "reporter")])
    w.run("u_p2", "DOC_XLS", "2026-09-07", "10:00", "11:00")
    w.unit("u_p3", start=("2026-09-09", "09:00"), end=("2026-09-09", "17:00"), conv="conv3",
           peers=[("w_unknown", "requester")])
    w.run("u_p3", "DOC_PPT", "2026-09-09", "10:00", "13:00")
    return w


class PeersTest(unittest.TestCase):
    def test_rpt27_filters(self):
        ctx = world().context(person_dir=PERSON_DIR, evidence=EVIDENCE, registry=REGISTRY)
        idx = P.peer_index(ctx.units.values(), ctx.evidence, ctx.person_dir, ctx.cfg, registry=ctx.registry)
        self.assertEqual(set(idx.by_unit["u_p1"]), {"w_req", "w_two", "w_small"})
        self.assertEqual(idx.by_unit["u_p1"]["w_req"], frozenset({"requester"}))
        self.assertTrue(idx.verified)
        self.assertEqual(idx.weight[("u_p1", "w_two", "thread")], 2)
        self.assertEqual(idx.cls["w_cust"], "customer")
        self.assertEqual(idx.cls["w_vend"], "partner")
        self.assertEqual(idx.cls["w_unknown"], "unknown")

    def test_section(self):
        ctx = world().context(person_dir=PERSON_DIR, evidence=EVIDENCE, registry=REGISTRY)
        sec = P.peers_layer(ctx.units, ctx.evidence, ctx.person_dir, ctx.cfg, registry=ctx.registry,
                            as_of_min=ctx.as_of_min)
        keys = [r["key"] for r in sec["internal"]]
        # u_p3 180분 > w_req(u_p1 120 + u_p2 60 = 180, 2건) — 공유 투입 같으면 공동 단위업무 수 ↓
        self.assertEqual(keys, ["w_req", "w_unknown", "w_small", "w_two"])
        req = sec["internal"][0]
        self.assertEqual((req["k"], req["units"], req["shared_effort_min"]), (1, 2, 180))
        self.assertEqual(req["roles"], {"requester": 1, "reporter": 1, "thread": 0, "meeting": 0})
        self.assertEqual((req["first"], req["last"]), ("2026-09-01", "2026-09-08"))
        self.assertEqual(req["projects"], ["P-0007"])
        self.assertIsNone(sec["internal"][1]["internal"])                 # 사람 사전에 없음 — 미확인
        self.assertEqual(sec["external"], {"customer": 1, "partner": 1, "other": 0})
        self.assertEqual(sec["unresolved"], 1)
        self.assertNotIn("w_me", keys)
        self.assertNotIn("warnings", sec)

    def test_top_n_and_unverified(self):
        ctx = world().context(person_dir=PERSON_DIR, cfg=W.cfg(**{"report.peers.topN": 2}))
        sec = P.peers_layer(ctx.units, None, ctx.person_dir, ctx.cfg, as_of_min=ctx.as_of_min)
        self.assertEqual(len(sec["internal"]), 2)
        self.assertGreater(sec["others"]["n"], 0)
        self.assertFalse(sec["verified"])
        self.assertEqual(sec["warnings"][0]["code"], "peers_unverified")
        keys = {r["key"] for r in sec["internal"]} | {"w_cc", "w_big", "w_one"}
        self.assertIn("w_req", keys)

    def test_thresholds(self):
        ctx = world().context(person_dir=PERSON_DIR, evidence=EVIDENCE, cfg=W.cfg(**{"report.peers.minMsgs": 1,
                                                                                         "report.peers.maxMeetingSize": 40}))
        idx = P.peer_index(ctx.units.values(), ctx.evidence, ctx.person_dir, ctx.cfg)
        self.assertEqual(set(idx.by_unit["u_p1"]), {"w_req", "w_two", "w_small", "w_one", "w_big"})


if __name__ == "__main__":
    unittest.main()
