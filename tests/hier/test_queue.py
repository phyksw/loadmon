# -*- coding: utf-8 -*-
r"""WP-22 분류 확인 질문 시험 — H §11.2(H01~H06 조건·선택지) · 계약 §6.3(주간 상한 따로) · T-23(같은 입력 → 같은 qid,
주당 노출 ≤ 상한) · 행 모양 = 시간 큐(confirm_queue.json)."""
import random
import unittest
from datetime import date

from lm27.hier.apply import UnitLabel
from lm27.hier.groups import Group
from lm27.hier.queue import hier_queue, make_q, qid_of
from lm27.time.calendar import day0
from tests.fixtures.wp22 import hierkit as K


def g(i, effort, d=date(2026, 9, 7)):
    return Group(f"grp:{i:012d}", f"a{i}", f"u{i}", (f"u{i}",), effort, day0(d) + 9 * 3600, day0(d) + 10 * 3600)


def lab(i, level, project=None, wconf="m", flags=(), cands=()):
    return UnitLabel(unit_id=f"u{i}", group=f"grp:{i:012d}", project=project, level=level, flags=list(flags),
                     conf={"wtype": wconf}, src={"wtype": "rule"}, cands=list(cands), wtype="OFFICE")


def inputs():
    groups = [g(1, 180), g(2, 60), g(3, 300), g(4, 300), g(5, 600), g(6, 200, date(2026, 9, 14))]
    labels = {"u1": lab(1, "unclassified", cands=[("P-0007", 0.3)]),     # H01
              "u2": lab(2, "unclassified"),                              # 투입 1h < 2h — 묻지 않음
              "u3": lab(3, "low", "P-9904"),                             # H01(예약 + low)
              "u4": lab(4, "medium", "P-0007", wconf="l"),               # H05(유형 l, 5h ≥ 4h)
              "u5": lab(5, "high", "P-0040", flags=["retired_project"]),  # H06
              "u6": lab(6, "high", "P-0007")}
    props = [{"proposal_id": "pr_1", "status": "pending", "n_units": 2, "effort_min": 100, "ukey": "방열모듈",
              "label": "방열 모듈", "domain_guess": "DEV", "groups": ["grp:000000000006"], "last_at": "2026-09-14"},
             {"proposal_id": "pr_2", "status": "pending", "n_units": 1, "effort_min": 60, "ukey": "작은일"},
             {"proposal_id": "pr_3", "status": "accepted_local", "n_units": 5, "effort_min": 999, "ukey": "받음"}]
    conflicts = [{"group": "grp:000000000006", "unit_id": "u6", "rule": "P-0007", "ai": "P-0008", "conf": "h"}]
    asks = [{"a": "pr_1", "b": "pr_4", "names": ["방열 모듈", "방열모듈 개발"], "score": 0.5, "effort_min": 240}]
    return labels, groups, props, conflicts, asks


class QueueTest(unittest.TestCase):
    def test_codes(self):
        labels, groups, props, conflicts, asks = inputs()
        q = hier_queue(labels, groups, props, conflicts, asks, K.cfg(), as_of=date(2026, 9, 30))
        codes = sorted((it["code"], it["target"]) for it in q)
        self.assertEqual(codes, sorted([("H01", "grp:000000000001"), ("H01", "grp:000000000003"),
                                        ("H05", "grp:000000000004"), ("H06", "grp:000000000005"),
                                        ("H02", "grp:000000000006"), ("H03", "pr_1"),
                                        ("H04", "방열모듈|방열모듈개발")]))
        for it in q:
            self.assertEqual(set(it), {"qid", "code", "target", "impact_min", "evidence_keys", "proposal", "status"})
            self.assertRegex(it["qid"], r"^[0-9a-f]{12}$")
            self.assertEqual(it["status"], "open")
            self.assertEqual(it["proposal"]["area"], "분류")
        h01 = next(it for it in q if it["target"] == "grp:000000000001")
        self.assertEqual(h01["proposal"]["cands"], ["P-0007"])
        self.assertEqual(h01["proposal"]["week"], "2026-W37")
        prio = [(it["impact_min"] / 60 + 0.01) * K.cfg()["hier.queue.weights"][it["code"]] for it in q]
        self.assertEqual(prio, sorted(prio, reverse=True))                       # 우선순위 순

    def test_stable_and_cap(self):
        labels, groups, props, conflicts, asks = inputs()
        a = hier_queue(labels, groups, props, conflicts, asks, K.cfg())
        r = random.Random(1)
        g2 = list(groups)
        r.shuffle(g2)
        b = hier_queue(dict(reversed(list(labels.items()))), g2, list(reversed(props)), conflicts, asks, K.cfg())
        self.assertEqual([x["qid"] for x in a], [x["qid"] for x in b])            # T-23 같은 입력 → 같은 qid
        capped = hier_queue(labels, groups, props, conflicts, asks, K.cfg({"hier.queue.maxPerWeek": 1}))
        weeks = {}
        for it in capped:
            weeks[it["proposal"]["week"]] = weeks.get(it["proposal"]["week"], 0) + 1
        self.assertTrue(all(v <= 1 for v in weeks.values()))
        none = hier_queue(labels, groups, props, conflicts, asks, K.cfg({"hier.queue.minEffortH": 100.0,
                                                                          "hier.queue.wtypeMinEffortH": 100.0,
                                                                          "hier.queue.proposalMinEffortH": 100.0}))
        self.assertEqual(sorted(it["code"] for it in none), ["H02", "H03", "H04"])   # 효과 문턱(H03 은 n_units ≥ 2)

    def test_make_q(self):
        it = make_q("H05", "grp:x", "", 300, evidence_keys=["b", "a", "a"], day=date(2026, 9, 1))
        self.assertEqual(it["evidence_keys"], ["a", "b"])
        self.assertEqual(it["qid"], qid_of("H05", "grp:x", ""))
        with self.assertRaises(ValueError):
            make_q("Q01", "x", "", 1)


if __name__ == "__main__":
    unittest.main()
