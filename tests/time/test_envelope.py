# -*- coding: utf-8 -*-
"""WP-19 근무 봉투(lm27.time.envelope) — W §3 규칙 · P-T10~T12(R-P3·R-P4·R-P5) · T-09 · 원장 정수 초 · G9 성능(봉투 몫).

입력은 W 작성기(tests.time.scenarios)로 만든 합성 세계 → 저장 행 어댑터 → normalize → build_days → build_envelope.
"""
from __future__ import annotations

import ctypes
import datetime as dt
import os
import random
import time
import unittest
from pathlib import Path

from tests.time import scenarios as X
from tests.time.scenarios import W, office_day

from lm27.time.calendar import SLOT, TAGS, d_of, day0
from lm27.time.envelope import CONF, DEDUCT_ITEMS, EXCLUDE_ITEMS, PRIO, Envelope
from lm27.time.evidence import lsec_of

D = "2026-10-14"           # 수요일(평일)
AS_OF = "2026-10-30 18:00"


def slot_of(hhmm: str, day: str = D) -> int:
    return lsec_of(f"{day} {hhmm}", 540) // SLOT


def env_of(w: W) -> Envelope:
    return X.run_env(w)[2]


def slots_between(env: Envelope, a: str, b: str, day: str = D) -> set[int]:
    return {s for s in env.slots if slot_of(a, day) <= s < slot_of(b, day)}


class BasicTest(unittest.TestCase):
    def test_office_day_is_8h_regular(self):
        n = W("B1", D, D, AS_OF)
        office_day(n, "PC1", D, [("09:00", "12:00", "office", "사양서.docx"), ("13:00", "18:00", "office", "사양서.docx")])
        n.doc(f"{D} 17:50", "save", "사양서.docx")
        env = env_of(n)
        self.assertEqual(env.minutes(), 480)
        self.assertEqual(env.tag_minutes(), {"regular": 480})
        self.assertEqual(env.day_minutes(), {dt.date(2026, 10, 14): 480})
        self.assertEqual(env.day_tag_minutes(), {dt.date(2026, 10, 14): {"regular": 480}})
        self.assertTrue(all(env.conf(s) == "high" for s in env.slots))
        self.assertEqual({env.pcs[s] for s in env.slots}, {(X.pc_id("PC1"),)})
        self.assertEqual(set(env.basis.values()), {"C1"})
        self.assertIs(env.led, env.ledger)
        self.assertIs(env.anchor_sess, env.anchor_sessions)

    def test_prio_and_conf_tables(self):
        self.assertEqual(set(PRIO), set(CONF))
        self.assertEqual(PRIO[0], "C11")
        self.assertEqual(PRIO[-1], "C5")

    def test_ledger_integer_seconds_and_components_sum(self):
        for name in ("W27", "W28", "W48", "W36", "W38", "W59"):
            with self.subTest(name=name):
                env = env_of(X.SC[name]())
                for d, c in env.ledger.items():
                    self.assertTrue(all(isinstance(v, int) for v in c.values()), d)
                    self.assertTrue(all(isinstance(v, int) and v > 0 for v in env.ledger_n.get(d, {}).values()))
                comp = sum(v for c in env.ledger.values() for k, v in c.items() if k.startswith("봉투_"))
                self.assertEqual(comp, len(env.slots) * SLOT)
                items = {k for c in env.ledger.values() for k in c}
                known = set(DEDUCT_ITEMS) | set(EXCLUDE_ITEMS) | {"봉투_" + p for p in PRIO}
                self.assertTrue(items <= known, items - known)

    def test_tags_are_contract_codes(self):
        env = env_of(X.SC["W53"]())
        self.assertTrue(set(env.tags.values()) <= set(TAGS))
        self.assertEqual(env.tag_minutes(), {"holiday": 300, "night": 60, "regular": 480})


class PrivacyRulesTest(unittest.TestCase):
    """P §12.7 R-P3·R-P4·R-P5 와 P-T10~T12."""

    def test_pt10_offhours_private_excluded_anchor_pad_kept(self):
        n = W("PT10", D, D, AS_OF)
        n.samp("PC1", f"{D} 22:00", f"{D} 23:30", "chat", priv="private", app="kakaotalk")
        n.msg(f"{D} 23:40", "out", "info", "M1", "P1", tokens=("일정",))
        env = env_of(n)
        self.assertEqual(slots_between(env, "22:00", "23:30"), set())       # 사적 전경 22:00~23:30 제외
        self.assertIn(slot_of("23:40"), env.slots)                            # 23:40 앵커 + 직전 창만
        self.assertEqual(env.minutes(), 15)
        self.assertEqual(set(env.tag_minutes()), {"night"})
        self.assertGreater(env.ledger[dt.date(2026, 10, 14)]["사적차감"], 0)

    def test_pt11_regular_private_short_neutral_long_removed(self):
        n = W("PT11", D, D, AS_OF)
        office_day(n, "PC1", D, [("09:00", "12:00", "office", "설계서.docx"), ("13:00", "14:00", "office", "설계서.docx"),
                                 ("14:20", "15:00", "office", "설계서.docx"), ("15:40", "18:00", "office", "설계서.docx")])
        n.samples = [s for s in n.samples if s["a"] not in (f"{D} 14:00", f"{D} 15:00")]
        n.samp("PC1", f"{D} 14:00", f"{D} 14:20", "browser", priv="private")      # 쇼핑 20분 → 중립
        n.samp("PC1", f"{D} 15:00", f"{D} 15:40", "other", priv="private", app="game")   # 게임 40분 → 제외
        n.doc(f"{D} 17:50", "save", "설계서.docx")
        env = env_of(n)
        self.assertEqual(len(slots_between(env, "14:00", "14:20")), 4)
        self.assertEqual(slots_between(env, "15:00", "15:40"), set())
        self.assertEqual(env.minutes(), 440)
        led = env.ledger[dt.date(2026, 10, 14)]
        self.assertEqual(led["사적차감"], 40 * 60)
        self.assertEqual(env.ledger_n[dt.date(2026, 10, 14)]["사적차감"], 1)     # '사적차감 40분(1건 판정)' — X-215
        self.assertNotIn("game", repr(dict(env.ledger)))                    # 원장에 앱 이름 없음(R-P7)

    def test_pt12_personal_calendar_absent(self):
        n = W("PT12", D, D, AS_OF)
        office_day(n, "PC1", D, [("09:00", "12:00", "office", "설계서.docx"), ("13:00", "18:00", "office", "설계서.docx")])
        n.meet(f"{D} 13:00", f"{D} 15:00", "ME", ("ME",), ("병원",), personal=True)
        env = env_of(n)
        self.assertEqual(slots_between(env, "13:00", "15:00"), set())
        self.assertEqual(env.minutes(), 360)
        self.assertEqual(env.ledger[dt.date(2026, 10, 14)]["개인일정차감"], 120 * 60)
        n.doc(f"{D} 14:00", "save", "설계서.docx")                           # 그 슬롯에 산출 앵커 → 업무 우선
        env2 = env_of(n)
        self.assertEqual(slots_between(env2, "13:00", "15:00"), {slot_of("14:00")})
        ev = X.run_env(n)[0]
        self.assertEqual(ev.meets[0].tokens, frozenset())                   # 제목 토큰 저장 안 됨

    def test_offhours_private_break_cuts_bridge(self):
        env = env_of(X.SC["W48B"]())
        self.assertGreater(env.ledger[dt.date(2026, 10, 27)]["사적단절_다리없음"], 0)

    def test_user_exclude(self):
        n = W("EX", D, D, AS_OF)
        office_day(n, "PC1", D, [("09:00", "12:00", "office", "a.docx"), ("13:00", "18:00", "office", "a.docx")])
        n.man("exclude", a=f"{D} 16:00", b=f"{D} 17:00")
        env = env_of(n)
        self.assertEqual(env.minutes(), 420)
        self.assertEqual(env.ledger[dt.date(2026, 10, 14)]["사용자제외"], 3600)


class PrecisionTest(unittest.TestCase):
    """T-09 · T-03: date·summary·unknown 은 시간 기여 0, 양성 증거는 봉투를 줄이지 않는다."""

    def base(self) -> W:
        n = W("P", D, D, AS_OF)
        n.samp("PC1", f"{D} 09:00", f"{D} 11:00", "office", "a.docx")
        n.on("PC1", f"{D} 08:50", f"{D} 11:05")
        return n

    def test_non_time_precisions_contribute_zero(self):
        ref = env_of(self.base())
        n = self.base()
        for t in ("13:00", "15:00", "21:00"):
            n.msg(f"{D} {t}", "out", "report", "D1", "P1", prec="date")
            n.msg(f"{D} {t}", "in", "request", "D2", "P1", prec="summary")
            n.msg(f"{D} {t}", "out", "info", "D3", "P1", prec="unknown")
        env = env_of(n)
        self.assertEqual(env.slots, ref.slots)
        self.assertEqual(env.basis, ref.basis)

    def test_date_only_day_zero_unless_gate(self):
        n = W("DO", D, D, AS_OF)
        n.on("PC1", f"{D} 09:00", f"{D} 18:00")
        for k in range(5):
            n.msg(f"{D} 12:00", "out", "info", f"D{k}", "P1", prec="date")
        self.assertEqual(env_of(n).minutes(), 0)
        n.cfg = {"time.envelope.dateOnlyGate": True}
        env = env_of(n)
        self.assertEqual(env.minutes(), 460)
        self.assertEqual(set(env.basis.values()), {"C8d"})
        self.assertTrue(all(env.conf(s) == "low" for s in env.slots))
        self.assertIn("date-only 게이트 하한(낮은 신뢰)", env.flags[dt.date(2026, 10, 14)])

    def test_receive_credit_and_day_cap(self):
        n = W("RC", D, D, AS_OF)
        for k in range(8):
            mm = 9 * 60 + 10 + k * 40
            mm += 60 if 12 * 60 <= mm < 13 * 60 else 0
            n.msg(f"{D} {mm // 60:02d}:{mm % 60:02d}", "in", "info", f"R{k}", "P1")
        env = env_of(n)
        self.assertEqual(env.minutes(), 40)
        self.assertEqual(set(env.basis.values()), {"C5"})
        for k in range(8, 20):
            n.msg(f"{D} {9 + k // 3:02d}:{(k % 3) * 20 + 5:02d}", "in", "info", f"R{k}", "P1")
        env2 = env_of(n)
        self.assertEqual(env2.minutes(), 60)                                  # 하루 상한 60분
        self.assertGreater(env2.ledger[dt.date(2026, 10, 14)]["수신상한_제외"], 0)
        n.msg(f"{D} 10:00", "in", "info", "CC", "P1", direct=False)            # 직접 수신 아님 → 크레딧 없음
        self.assertEqual(env_of(n).minutes(), 60)


class LeaveManualTest(unittest.TestCase):
    def test_on_leave_slots_and_extended(self):
        env = env_of(X.SC["W52B"]())
        self.assertEqual(env.tag_minutes(), {"extended": 60, "regular": 240})
        self.assertEqual(len(env.on_leave), 12)
        self.assertTrue(all(env.tags[s] == "extended" for s in env.on_leave))

    def test_untimed_manual_placed_in_regular_zone(self):
        n = W("MU", D, D, AS_OF)
        n.samp("PC1", f"{D} 09:00", f"{D} 10:00", "office", "a.docx")
        n.man("work", hours=2.0, day=D)
        ev, _days, env, _c = X.run_env(n)
        self.assertEqual(env.minutes(), 60 + 120)
        man = ev.manual[0]
        placed = env.manual_slots[man.id]
        self.assertEqual(len(placed), 24)
        self.assertTrue(all(env.basis[s] == "C11u" and env.tags[s] == "regular" for s in placed))
        self.assertEqual(min(placed), slot_of("10:00"))                       # 정규 구역의 빈 슬롯부터

    def test_timed_manual_and_offsite(self):
        n = W("MT", D, "2026-10-15", AS_OF)
        n.man("work", a=f"{D} 19:00", b=f"{D} 20:00")
        n.man("offsite", day="2026-10-15")
        env = env_of(n)
        self.assertEqual(env.day_minutes(), {dt.date(2026, 10, 14): 60, dt.date(2026, 10, 15): 540})
        self.assertEqual({env.basis[s] for s in env.slots}, {"C11"})


class CalendarGateTest(unittest.TestCase):
    def test_unknown_year_refused(self):                                   # W §2.8 '달력 미확인 연도' — fail-closed
        from lm27.time.calendar import UnknownYearError
        n = W("UY", "2030-03-04", "2030-03-04", "2030-03-05 18:00")
        n.samp("PC1", "2030-03-04 09:00", "2030-03-04 10:00", "office", "a.docx")
        with self.assertRaises(UnknownYearError):
            X.run_env(n)


class StaticTest(unittest.TestCase):
    def test_no_zoneinfo_in_time_core(self):                                  # L-04 · W-G10
        root = Path(__file__).resolve().parents[2] / "lm27" / "time"
        for name in ("intervals.py", "tokens.py", "evidence.py", "envelope.py"):
            src = (root / name).read_text(encoding="utf-8")
            self.assertNotIn("zone" + "info", src, name)


# ───────────────────────────── G9 성능(봉투 몫): 1명 × 3개월 ≈ 4.3만 신호 ─────────────────────────────
DOCS_TOK = ["원가", "회로", "도면", "시험", "해석", "센서", "하네스", "모터", "브라켓", "사양", "일정", "품질", "양산", "보정"]


def gen_months(months: float = 3, seed: int = 26, per_day=(300, 250, 150, 4, 6)) -> tuple[W, int]:
    """참조 gates.gen 과 같은 합성 분포(근무일당 샘플 300·메시지 250·저장 150·회의 4·커밋 6, 의뢰 6건)."""
    n_seg, n_msg, n_save, n_meet, n_commit = per_day
    r = random.Random(seed)
    d0 = dt.date(2026, 9, 1)
    d1 = d0 + dt.timedelta(days=int(30 * months) - 1)
    cal = X.calendar()
    n = W("PERF", d0.isoformat(), d1.isoformat(), f"{(d1 + dt.timedelta(days=1)).isoformat()} 09:00")
    fam_pool, threads = [], []
    req_id = 0
    d = d0
    while d <= d1:
        s = d.isoformat()
        if cal.is_holiday(d):
            d += dt.timedelta(days=1)
            continue
        for _k in range(6):
            req_id += 1
            th = f"R{req_id}"
            tk = tuple(r.sample(DOCS_TOK, 2))
            fam_pool.append(f"{tk[0]}_{tk[1]}_과제{req_id % 37}.xlsx")
            threads.append(th)
            mm = r.randrange(9 * 60, 17 * 60)
            n.msg(f"{s} {mm // 60:02d}:{mm % 60:02d}", "in", "request", th, f"P{r.randrange(20)}",
                  r.choice(["mail", "teams"]), tokens=tk)
        active = fam_pool[-25:]
        n.on("PC1", f"{s} 08:50", f"{s} 18:10")
        step = (8 * 60) / n_seg
        for k in range(n_seg):
            a = int(9 * 60 + k * step)
            if 12 * 60 <= a < 13 * 60:
                a += 60
            a = min(a, 18 * 60 - 2)
            b = min(a + max(1, int(step)), 18 * 60)
            if b <= a:
                continue
            cls = r.choice(["office", "office", "office", "cad", "browser", "mail", "chat", "explorer"])
            doc = r.choice(active) if cls in ("office", "cad") else ""
            n.samp("PC1", f"{s} {a // 60:02d}:{a % 60:02d}", f"{s} {b // 60:02d}:{b % 60:02d}", cls, doc)
        n.samp("PC1", f"{s} 12:00", f"{s} 13:00", "other", state="locked")
        if r.random() < 0.2:
            n.samp("PC1", f"{s} 20:00", f"{s} 21:30", "office", r.choice(active))
            n.doc(f"{s} 21:20", "save", r.choice(active))
        for _k in range(n_save):
            mm = r.randrange(9 * 60, 18 * 60)
            n.doc(f"{s} {mm // 60:02d}:{mm % 60:02d}", r.choice(["save", "save", "save", "export"]), r.choice(active))
        for _k in range(n_msg):
            mm = r.randrange(8 * 60, 19 * 60)
            dirn = "in" if r.random() < 0.65 else "out"
            th = r.choice(threads[-60:])
            act = r.choice(["info", "info", "question", "ack", "notice"]) if dirn == "in" else \
                r.choice(["info", "ack", "report", "question"])
            atts = (r.choice(active),) if (dirn == "out" and act == "report" and r.random() < 0.7) else ()
            n.msg(f"{s} {mm // 60:02d}:{mm % 60:02d}", dirn, act, th, f"P{r.randrange(20)}",
                  r.choice(["mail", "teams"]), direct=r.random() < 0.7, atts=atts, tokens=tuple(r.sample(DOCS_TOK, 2)))
        for _k in range(n_meet):
            mm = r.choice([9 * 60 + 30, 10 * 60 + 30, 14 * 60, 15 * 60 + 30, 16 * 60 + 30])
            n.meet(f"{s} {mm // 60:02d}:{mm % 60:02d}", f"{s} {(mm + 60) // 60:02d}:{(mm + 60) % 60:02d}",
                   f"P{r.randrange(20)}", ("P1", "ME"), tuple(r.sample(DOCS_TOK, 2)))
        for _k in range(n_commit):
            mm = r.randrange(9 * 60, 18 * 60)
            n.commit(f"{s} {mm // 60:02d}:{mm % 60:02d}", "repoA")
        d += dt.timedelta(days=1)
    total = len(n.samples) + len(n.msgs) + len(n.docs) + len(n.meets) + len(n.commits) + len(n.pcon)
    return n, total


def _peak_working_set_mb() -> float | None:
    if os.name != "nt":
        return None

    class PMC(ctypes.Structure):
        _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong),
                    ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.GetCurrentProcess.restype = ctypes.c_void_p
    k32.K32GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(PMC), ctypes.c_ulong]
    pmc = PMC()
    pmc.cb = ctypes.sizeof(PMC)
    if not k32.K32GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb):
        return None
    return pmc.PeakWorkingSetSize / (1024 * 1024)


class PerfTest(unittest.TestCase):
    """W-G9 봉투 몫: 1명 × 3개월 ≤ 60초 · ≤ 500MB(개발 PC). 시간 코어 B(단위업무·귀속)는 WP-20 시험."""

    def test_three_months(self):
        w, total = gen_months(3, 26)
        self.assertGreater(total, 40000)
        cfg = X.base_cfg()
        recs, profile, as_of, tags, _over = X.to_inputs(w, cfg)
        t0 = time.perf_counter()
        ev, _audit = X.normalize(recs, profile, cfg, as_of, tags)
        days = X.build_days(ev, cfg, X.calendar())
        env = X.build_envelope(ev, cfg, days)
        el = time.perf_counter() - t0
        self.assertLessEqual(el, 60.0, f"봉투 {el:.1f}s")
        self.assertGreater(env.minutes(), 0)
        peak = _peak_working_set_mb()
        if peak is not None:
            self.assertLessEqual(peak, 500.0, f"최대 작업 집합 {peak:.0f}MB")
        months = {(d_of(s * SLOT).year, d_of(s * SLOT).month) for s in env.slots}
        self.assertEqual(months, {(2026, 9), (2026, 10), (2026, 11)})
        self.assertEqual(min(env.slots) * SLOT >= day0(dt.date(2026, 9, 1)), True)


if __name__ == "__main__":
    unittest.main()
