# -*- coding: utf-8 -*-
"""WP-19 단조성 퍼즈(W-G3 · T-03): 양성 증거 1건 추가 → 봉투 비감소, PC 가동(L0/L1) 기록 제거 → 비증가.

기본 세계(심사 mono_fuzz 분포) 3,000 + 확장 세계(3일·PC 2대·창 밖·점심·사적·잠금·원격·연산·반차·수동) 3,000.
세계 생성기는 참조 `design\\worktime\\gates.py`(rnd_world·add_one·rnd_world2·add_one2)를 옮긴 것이다.
환경 변수 LM27T_FUZZ_N(시드당 세계 수, 기본 1000)으로 줄여 돌릴 수 있다(완료 판정은 기본값).
"""
from __future__ import annotations

import os
import random
import unittest
from collections import Counter

from tests.time import scenarios as X
from tests.time.scenarios import W

DAY = "2026-10-14"
DOCS = ["설계서_과제A.docx", "원가표_과제B.xlsx", "도면_과제C.dwg"]
CLS = ["office", "office", "cad", "browser", "mail", "chat", "explorer", "other"]
DAYS2 = ["2026-10-16", "2026-10-17", "2026-10-19"]          # 금(평일)·토(휴일)·월(평일, 반차 가능)
N_PER_SEED = int(os.environ.get("LM27T_FUZZ_N", "1000"))
SEEDS_BASE = (7, 26, 101)
SEEDS_EXT = (7, 26, 2026)


def hm(m: int, day: str = DAY) -> str:
    m = max(0, min(m, 24 * 60 - 1))
    return f"{day} {m // 60:02d}:{m % 60:02d}"


def rnd_world(r: random.Random) -> W:
    """심사 mono_fuzz 와 같은 분포의 무작위 하루."""
    n = W("MF", DAY, DAY, "2026-10-30 18:00", "mono fuzz")
    has_sampler = r.random() < 0.6
    if r.random() < 0.85:
        a = r.choice([8 * 60 + 30, 8 * 60 + 50, 9 * 60, 13 * 60])
        b = r.choice([17 * 60, 18 * 60 + 5, 19 * 60, 23 * 60])
        n.on("PC1", hm(a), hm(b))
    if has_sampler:
        t = 9 * 60
        while t < 18 * 60 + r.choice([0, 0, 120, 240]):
            ln = r.choice([5, 10, 20, 30, 45, 60])
            st = r.choices(["active", "idle", "locked"], [0.7, 0.15, 0.15])[0]
            cls = r.choice(CLS)
            doc = r.choice(DOCS) if cls in ("office", "cad") else ""
            n.samp("PC1", hm(t), hm(t + ln), cls if st == "active" else "other", doc if st == "active" else "", state=st)
            t += ln + r.choice([0, 0, 0, 5, 15])
    for _ in range(r.randrange(0, 4)):
        n.doc(hm(r.randrange(8 * 60, 23 * 60)), "save", r.choice(DOCS))
    for _ in range(r.randrange(0, 4)):
        n.msg(hm(r.randrange(8 * 60, 23 * 60)), "out", r.choice(["info", "report", "ack"]), f"M{r.randrange(3)}",
              "P1", r.choice(["mail", "teams"]), atts=((r.choice(DOCS),) if r.random() < 0.3 else ()))
    for _ in range(r.randrange(0, 5)):
        n.msg(hm(r.randrange(8 * 60, 20 * 60)), "in", r.choice(["info", "request", "question"]), f"M{r.randrange(3)}",
              "P2", r.choice(["mail", "teams"]), direct=r.random() < 0.8)
    if r.random() < 0.3:
        a = r.choice([10 * 60, 14 * 60, 16 * 60])
        n.meet(hm(a), hm(a + 60), "P1", ("P1", "ME", "P3"), ("과제A", "리뷰"))
    return n


def add_one(n: W, r: random.Random) -> tuple[str, str]:
    """양성 증거 1건(능동 표본·저장·발신·수신·회의·커밋) — 부정 증거(잠금·유휴·사적)는 넣지 않는다."""
    k = r.choice(["samp", "save", "out", "in", "meet", "commit"])
    t = r.randrange(7 * 60, 23 * 60)
    if k == "samp":
        cls = r.choice(CLS)
        n.samp(r.choice(["PC1", "PC2"]), hm(t), hm(t + r.choice([2, 5, 10, 30])), cls,
               r.choice(DOCS) if cls in ("office", "cad") else "")
    elif k == "save":
        n.doc(hm(t), "save", r.choice(DOCS))
    elif k == "out":
        n.msg(hm(t), "out", r.choice(["info", "report"]), f"M{r.randrange(3)}", "P1", r.choice(["mail", "teams"]))
    elif k == "in":
        n.msg(hm(t), "in", "info", f"M{r.randrange(3)}", "P2", "mail")
    elif k == "meet":
        n.meet(hm(t), hm(t + 30), "P1", ("P1", "ME"), ("주간",))
    else:
        n.commit(hm(t), "repoA")
    return k, hm(t)


def rnd_world2(r: random.Random) -> W:
    """확장 세계: 3일(평일·주말·평일), PC 2대, 퇴근 후·점심·새벽, 사적 표본, 잠금, 원격 발신, 연산, 반차."""
    n = W("MF2", DAYS2[0], DAYS2[-1], "2026-10-30 18:00", "mono fuzz 2")
    if r.random() < 0.3:
        n.leave(DAYS2[2], r.choice(["am", "pm", "full"]))
    for day in DAYS2:
        for pc in ("PC1", "PC2"):
            if r.random() < 0.5:
                a = r.choice([7 * 60, 8 * 60 + 50, 12 * 60, 20 * 60])
                n.on(pc, hm(a, day), hm(min(a + r.choice([60, 240, 600, 900]), 24 * 60 - 1), day))
            if r.random() < 0.6:
                t = r.choice([8 * 60, 9 * 60, 13 * 60, 19 * 60])
                end = t + r.choice([120, 300, 600])
                while t < min(end, 24 * 60 - 5):
                    ln = r.choice([5, 10, 20, 30, 45, 60])
                    st = r.choices(["active", "idle", "locked"], [0.65, 0.15, 0.2])[0]
                    cls = r.choice(CLS + ["remote", "ide"])
                    pv = "private" if (st == "active" and r.random() < 0.08) else ("media" if r.random() < 0.03 else "work")
                    doc = r.choice(DOCS) if cls in ("office", "cad") else ""
                    n.samp(pc, hm(t, day), hm(min(t + ln, 24 * 60 - 1), day), cls if st == "active" else "other",
                           doc if st == "active" else "", state=st, priv=pv if st == "active" else "work")
                    t += ln + r.choice([0, 0, 5, 15, 40])
        for _ in range(r.randrange(0, 4)):
            n.doc(hm(r.randrange(6 * 60, 24 * 60), day), r.choice(["save", "save", "export"]), r.choice(DOCS),
                  pc=r.choice(["PC1", "PC2"]))
        for _ in range(r.randrange(0, 4)):
            n.msg(hm(r.randrange(6 * 60, 24 * 60), day), "out", r.choice(["info", "report", "ack", "request"]),
                  f"M{r.randrange(4)}", r.choice(["P1", "P2"]), r.choice(["mail", "teams"]),
                  atts=((r.choice(DOCS),) if r.random() < 0.3 else ()), tokens=r.choice([(), ("과제A",), ("원가표",)]))
        for _ in range(r.randrange(0, 6)):
            n.msg(hm(r.randrange(7 * 60, 21 * 60), day), "in", r.choice(["info", "request", "report"]),
                  f"M{r.randrange(4)}", r.choice(["P1", "P2"]), r.choice(["mail", "teams"]), direct=r.random() < 0.8,
                  tokens=r.choice([(), ("과제A", "설계서"), ("원가표",)]))
        if r.random() < 0.4:
            a = r.choice([10 * 60, 12 * 60 + 30, 14 * 60, 19 * 60])
            n.meet(hm(a, day), hm(a + r.choice([30, 60, 90]), day), "P1", ("P1", "ME", "P3"),
                   ("과제A", "리뷰"), status=r.choice(["accepted", "accepted", "tentative"]), n_att=r.choice([3, 8]))
        if r.random() < 0.15:
            a = r.choice([15 * 60, 17 * 60])
            n.comp("PC1", hm(a, day), hm(min(a + 300, 24 * 60 - 1), day), "cae", "도면_과제C.dwg")
    return n


def add_one2(n: W, r: random.Random) -> tuple[str, str]:
    k = r.choice(["samp", "save", "out", "in", "meet", "commit", "work"])
    day = r.choice(DAYS2)
    t = r.randrange(5 * 60, 24 * 60 - 31)
    if k == "samp":
        cls = r.choice(CLS + ["ide"])
        n.samp(r.choice(["PC1", "PC2", "PC3"]), hm(t, day), hm(t + r.choice([2, 5, 10, 30, 60]), day), cls,
               r.choice(DOCS) if cls in ("office", "cad") else "")
    elif k == "save":
        n.doc(hm(t, day), "save", r.choice(DOCS), pc=r.choice(["PC1", "PC2", "PC3"]))
    elif k == "out":
        n.msg(hm(t, day), "out", r.choice(["info", "report", "ack"]), f"M{r.randrange(4)}", "P1",
              r.choice(["mail", "teams"]), atts=((r.choice(DOCS),) if r.random() < 0.3 else ()))
    elif k == "in":
        n.msg(hm(t, day), "in", r.choice(["info", "request"]), f"M{r.randrange(4)}", "P2", "mail")
    elif k == "meet":
        n.meet(hm(t, day), hm(t + 30, day), "P1", ("P1", "ME"), ("주간",))
    elif k == "commit":
        n.commit(hm(t, day), "repoA", pc=r.choice(["PC1", "PC2"]))
    else:
        n.man("work", a=hm(t, day), b=hm(t + 30, day), ref="현장지원")
    return k, hm(t, day)


def mono(gen, add, n_worlds: int, seed: int, cfg) -> tuple[list, list, Counter]:
    r = random.Random(seed)
    viol, rm_viol, kinds = [], [], Counter()
    for i in range(n_worlds):
        w = gen(r)
        base = X.run_env(w, cfg)[2].minutes()
        w2 = w.copy()
        what = add(w2, r)
        kinds[what[0]] += 1
        after = X.run_env(w2, cfg)[2].minutes()
        if after < base:
            viol.append((seed, i, what, base, after))
        if w.pcon:
            w3 = w.copy()
            w3.pcon = []
            rem = X.run_env(w3, cfg)[2].minutes()
            if rem > base:
                rm_viol.append((seed, i, base, rem))
    return viol, rm_viol, kinds


class MonotoneFuzzTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = X.base_cfg()

    def run_family(self, gen, add, seeds):
        tot_v, tot_r, kinds = [], [], Counter()
        for seed in seeds:
            v, rv, k = mono(gen, add, N_PER_SEED, seed, self.cfg)
            tot_v += v
            tot_r += rv
            kinds += k
        self.assertEqual(tot_v[:5], [], f"양성 증거 추가 → 봉투 감소 {len(tot_v)}건")
        self.assertEqual(tot_r[:5], [], f"PC 가동 기록 제거 → 봉투 증가 {len(tot_r)}건")
        self.assertEqual(sum(kinds.values()), N_PER_SEED * len(seeds))
        self.assertTrue(set(kinds) >= {"samp", "save", "out", "in", "meet", "commit"})

    def test_base_worlds(self):
        self.run_family(rnd_world, add_one, SEEDS_BASE)

    def test_extended_worlds(self):
        self.run_family(rnd_world2, add_one2, SEEDS_EXT)


if __name__ == "__main__":
    unittest.main()
