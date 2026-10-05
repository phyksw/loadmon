# -*- coding: utf-8 -*-
"""WP-19 결정성·순서 무관(W-G2 · T-02 의 봉투 몫): 83개 시나리오 × 입력 행 순서 섞기 4회 → 정규화·봉투 서명 동일."""
from __future__ import annotations

import hashlib
import unittest

from tests.time import scenarios as X


def signature(ev, env) -> str:
    """정규화 목록(정렬 결과 그대로) + 봉투(슬롯·근거·꼬리표·원장·표식·앵커 순서)의 해시."""
    parts = [repr(ev.samples), repr(ev.pcon), repr(ev.msgs), repr(ev.meets), repr(ev.docs), repr(ev.comps),
             repr(ev.commits), repr(ev.manual), repr(sorted(ev.audit.items())), repr(sorted(ev.common_tokens)),
             repr(sorted(ev.fam_tokens.items(), key=lambda x: x[0])), repr(ev.utc_suspect), repr((ev.d0, ev.d1)),
             repr(sorted(env.slots)), repr(sorted(env.basis.items())), repr(sorted(env.tags.items())),
             repr(sorted((d, sorted(c.items())) for d, c in env.ledger.items())),
             repr(sorted((d, list(v)) for d, v in env.flags.items())),
             repr([(a.t, a.kind, a.pre_s, a.pc, getattr(a.ref, "id", "")) for a in env.anchors]),
             repr(sorted(env.on_leave)), repr(sorted(env.pcs.items())), repr(sorted(env.manual_slots.items()))]
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


class OrderTest(unittest.TestCase):
    REPS = 4

    @classmethod
    def setUpClass(cls):
        cls.cfg = X.base_cfg()

    def test_shuffled_records_same_signature(self):
        bad = []
        for name, fn in X.SC.items():
            ev, _d, env, _c = X.run_env(fn(), self.cfg)
            ref = signature(ev, env)
            for rep in range(self.REPS):
                ev2, _d2, env2, _c2 = X.run_env(fn(), self.cfg, shuffle=1000 + rep)
                if signature(ev2, env2) != ref:
                    bad.append((name, rep))
        self.assertEqual(bad, [], "순서 의존")

    def test_generic_and_mixed_names_shuffle(self):
        n = X.W("G", "2026-10-14", "2026-10-15", "2026-10-30 18:00")
        for day in ("2026-10-14", "2026-10-15"):
            X.office_day(n, "PC1", day, [("09:00", "10:00", "office", "보고서.pptx"), ("10:00", "11:00", "office", "자료.xlsx"),
                                         ("13:00", "14:00", "office", "보고서_v2.pptx"), ("14:00", "15:00", "cad", "도면.dwg")])
            for t, d, f in (("09:50", "보고서.pptx", "과제A"), ("10:50", "자료.xlsx", ""), ("13:50", "보고서_v2.pptx", "과제B"),
                            ("14:50", "도면.dwg", "")):
                n.doc(f"{day} {t}", "save", d, folder=f)
            n.msg(f"{day} 16:00", "out", "report", "R", "P1", atts=("보고서.pptx", "자료.xlsx"))
        ev, _d, env, _c = X.run_env(n, self.cfg)
        ref = signature(ev, env)
        self.assertNotIn("B_GENERIC", ev.fam_names)
        for rep in range(10):
            ev2, _d2, env2, _c2 = X.run_env(n, self.cfg, shuffle=rep)
            self.assertEqual(signature(ev2, env2), ref, rep)

    def test_repeat_run_identical(self):
        for name in ("W01", "W28", "W45", "W51", "W61"):
            a = signature(*X.run_env(X.SC[name](), self.cfg)[::2][:2])
            b = signature(*X.run_env(X.SC[name](), self.cfg)[::2][:2])
            self.assertEqual(a, b, name)


if __name__ == "__main__":
    unittest.main()
