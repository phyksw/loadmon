# -*- coding: utf-8 -*-
"""WP-03 rcmap — 수집기 rc·파이프 종료 코드 → 셀 상태·단계 결과·collect rc(계약 §8.1·§8.2·§8.3·§6.1, T-09·T-10, L-13).

실데이터 없음: 입력은 rc·사유 코드·건수뿐이다.
"""
import itertools
import re
import unittest
from pathlib import Path

from lm27.collect import rcmap

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "docs" / "CONTRACT.md"
MODULES = [ROOT / "lm27" / "collect" / n for n in ("rcmap.py", "stage_result.py", "watch.py")]
MODULES += [ROOT / "tests" / "core" / n for n in ("test_rcmap.py", "test_stage_result.py", "test_watch.py")]
KO_CLASS = {"구조": rcmap.STRUCTURAL, "사람": rcmap.HUMAN, "일시": rcmap.TRANSIENT, "수송": rcmap.TRANSPORT,
            "품질": rcmap.QUALITY, "경고": rcmap.WARNING}

# 시험에서 쓰는 사유 대표값(분류별)
STRUCT = "R-NEWOL"        # 구조 ✔
TRANSP = "R-TRANSPORT"    # 수송
TRANSI = "R-IDXPAUSED"    # 일시
WARN = "R-MRUEMPTY"       # 경고
UNKNOWN = "R-" + "ZZUNKNOWN"  # 표 밖 코드 — 런타임 조립(저장소 텍스트에 §6.1 밖 코드를 두지 않는다, L-13)


def contract_reason_table():
    """CONTRACT.md §6.1 표 → {code: (class, confirm)}. docs 가 없는 복제 트리면 None."""
    if not CONTRACT.is_file():
        return None
    text = CONTRACT.read_bytes().decode("utf-8")
    sec = text[text.index("### 6.1 사유 코드"):]
    sec = sec[:sec.index("\n### ", 10)]
    out = {}
    for line in sec.splitlines():
        if not line.startswith("| R-"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        for code in (x.strip() for x in cells[0].split("·")):
            out[code] = (KO_CLASS[cells[2]], cells[3].startswith("✔"))
    return out


class ReasonTable(unittest.TestCase):
    def test_codes_match_regex(self):
        for code in rcmap.REASONS:
            self.assertRegex(code, rcmap.REASON_RX)
        self.assertEqual(rcmap.REASON_RX.pattern, r"^R-[A-Z]{2,}(-[A-Z0-9]+)*$")

    def test_table_equals_contract_6_1(self):
        table = contract_reason_table()
        if table is None:
            self.skipTest("docs 없음(복제 트리)")
        self.assertEqual(set(rcmap.REASONS), set(table), "계약 §6.1 과 코드 집합이 다릅니다")
        for code, (cls, ok) in table.items():
            self.assertEqual(rcmap.REASONS[code], (cls, ok), code)

    def test_snapshot_counts(self):
        # 계약 v1.2 §6.1: 57개(v1.0.1 의 55 + §0.7 C4 R-RECURINC·R-NOAPP), 확정 ✔ 21개 — 표가 바뀌면 이 숫자와 함께 고친다
        self.assertEqual(len(rcmap.REASONS), 57)
        self.assertEqual(len(rcmap.CONFIRMABLE), 21)
        self.assertNotIn("R-RECURINC", rcmap.CONFIRMABLE)        # 품질 — '불가' 근거가 아니다
        self.assertNotIn("R-NOAPP", rcmap.CONFIRMABLE)
        self.assertNotIn("R-TRANSPORT", rcmap.CONFIRMABLE)       # 수송 실패는 '불가' 근거가 아니다
        self.assertNotIn("R-STUCK", rcmap.CONFIRMABLE)
        self.assertNotIn("R-SAMPLER-ZOMBIE", rcmap.CONFIRMABLE)  # X-127
        self.assertIn("R-NEWOL", rcmap.CONFIRMABLE)

    def test_L13_module_codes_subset(self):
        """L-13: 이 WP 모듈·시험 텍스트의 R-<영문> ⊂ 계약 §6.1."""
        rx = re.compile(r"\bR-[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*")
        for p in MODULES:
            text = p.read_bytes().decode("utf-8")
            used = set(rx.findall(text))
            self.assertLessEqual(used, set(rcmap.REASONS), f"{p.name}: {sorted(used - set(rcmap.REASONS))}")

    def test_helpers(self):
        self.assertTrue(rcmap.is_reason("R-CA"))
        self.assertFalse(rcmap.is_reason(UNKNOWN))
        self.assertEqual(rcmap.reason_class(UNKNOWN), rcmap.TRANSPORT)      # 모르는 코드 = 수송(확정 불가)
        self.assertFalse(rcmap.confirmable(UNKNOWN))
        self.assertEqual(rcmap.norm_reasons("R-CA"), ["R-CA"])
        self.assertEqual(rcmap.norm_reasons(["R-CA", "x", "R-CA", None, "R-LOGIN"]), ["R-CA", "R-LOGIN"])


# ── 셀 상태 전 조합(계약 §8.1) ─────────────────────────────────────────────
RCS = (None, rcmap.RC_NOT_RUN, 0, 1, 2, 3, 4, "timeout_stall", "timeout_noprog")
NS = (None, 0, 5)
HORIZONS = (True, False)
BLOCKS = (None, STRUCT, TRANSP, TRANSI, WARN)
FLAGS = (False, True)


def oracle(rc, n, in_h, block, cap, budget):
    """계약 §8.1 표(+ X-120: 막힌 사유가 있으면 rc 3 과 같다)를 그대로 옮긴 기대 상태."""
    if rc is None or rc == rcmap.RC_NOT_RUN:
        return "not_attempted"
    if isinstance(rc, str):                                  # 시간 초과·kill
        return "transport_fail"
    if rc == 2:
        return "blocked"
    if rc == 3:
        return "blocked" if block == STRUCT else "transport_fail"
    if cap or budget:                                        # T-10
        return "partial"
    if (n is not None and n > 0) or (n is None and rc in (0, 4)):
        return "ok"
    if block == STRUCT:
        return "blocked"
    if block in (TRANSP, TRANSI):
        return "transport_fail"
    return "zero_ok" if in_h else "out_of_horizon"


def call(rc, n, in_h, block, cap, budget):
    counts = {"in_horizon": in_h}
    if n is not None:
        counts["n"] = n
    if cap:
        counts["cap_hit"] = True
    if budget:
        counts["budget_hit"] = True
    real_rc = rc
    if rc == "timeout_stall":
        counts["stop_kind"], real_rc = "stall", 3
    elif rc == "timeout_noprog":
        counts["stop_kind"], real_rc = "no_progress", 1          # 끊긴 프로세스의 rc 가 무엇이든
    reasons = [block] if block else []
    return rcmap.translate_cell(real_rc, reasons, counts)


class CellStatusMatrix(unittest.TestCase):
    def test_all_combinations(self):
        n_cases = 0
        for rc, n, in_h, block, cap, budget in itertools.product(RCS, NS, HORIZONS, BLOCKS, FLAGS, FLAGS):
            got = call(rc, n, in_h, block, cap, budget)
            want = oracle(rc, n, in_h, block, cap, budget)
            self.assertEqual(got["status"], want, (rc, n, in_h, block, cap, budget))
            self.assertIn(got["status"], rcmap.CELL_STATUSES)
            self.assertEqual(got["reasons"], sorted(set(got["reasons"])))
            if got["status"] == "partial":
                self.assertEqual(got["cap_hit"], cap)
                self.assertEqual(got["budget_hit"], budget)
                self.assertEqual("R-CAP" in got["reasons"], cap)
                self.assertEqual("R-BUDGET" in got["reasons"], budget)
            else:
                self.assertFalse(got["cap_hit"] or got["budget_hit"])
            if got["status"] == "transport_fail":
                self.assertTrue(any(rcmap.reason_class(r) in (rcmap.TRANSPORT, rcmap.TRANSIENT)
                                    for r in got["reasons"]), got)
            if got["status"] == "out_of_horizon":
                self.assertIn("R-HORIZON", got["reasons"])
            if rc == 2:
                self.assertIn("R-LOGIN", got["reasons"])
            n_cases += 1
        self.assertEqual(n_cases, len(RCS) * len(NS) * 2 * len(BLOCKS) * 4)

    def test_cell_status_is_translate_status(self):
        self.assertEqual(rcmap.cell_status(0, [], {"n": 3}), "ok")
        self.assertEqual(rcmap.cell_status(1, [], {}), "zero_ok")
        self.assertEqual(rcmap.cell_status(None, ["R-NEWOL"], {"n": 9}), "not_attempted")

    def test_rc1_with_structural_reason_is_blocked(self):
        # C 페르소나 12: 팀즈 창 숨김 → 그 날 blocked(0건을 '성공'으로 숨기지 않음)
        self.assertEqual(rcmap.cell_status(1, ["R-UIAEMPTY"], {"n": 0}), "blocked")
        self.assertEqual(rcmap.cell_status(3, ["R-UIAEMPTY"]), "blocked")
        self.assertEqual(rcmap.cell_status(3, ["R-NOIDX"]), "blocked")      # C 페르소나 5

    def test_rc2_login_and_ca(self):
        t = rcmap.translate_cell(2, ["R-CA"])
        self.assertEqual((t["status"], t["reasons"]), ("blocked", ["R-CA"]))
        t = rcmap.translate_cell(2, [])
        self.assertEqual((t["status"], t["reasons"]), ("blocked", ["R-LOGIN"]))

    def test_rc3_reason_required_and_horizon(self):
        self.assertEqual(rcmap.translate_cell(3, [])["reasons"], ["R-TRANSPORT"])
        t = rcmap.translate_cell(3, ["R-NOKEY"])                          # 일시 사유면 R-TRANSPORT 를 덧붙이지 않는다
        self.assertEqual((t["status"], t["reasons"]), ("transport_fail", ["R-NOKEY"]))
        self.assertEqual(rcmap.cell_status(3, ["R-HORIZON"]), "out_of_horizon")
        self.assertEqual(rcmap.cell_status(3, ["R-HORIZON", "R-TRANSPORT"]), "transport_fail")
        self.assertEqual(rcmap.cell_status(3, ["R-HORIZON", "R-NEWOL"]), "blocked")
        self.assertEqual(rcmap.cell_status(3, ["R-LOGIN"]), "blocked")     # 사람 사유도 막힘

    def test_zero_trust_exceptions(self):
        self.assertEqual(rcmap.cell_status(1, ["R-OMG"], {"n": 0}), "zero_ok")       # B단만 막힘 — A단 0건은 믿는다
        self.assertEqual(rcmap.cell_status(1, ["R-NOADDR"], {"n": 0}), "zero_ok")    # 품질
        self.assertEqual(rcmap.cell_status(1, ["R-SUBFOLDER"], {"n": 0}), "zero_ok")  # 경고
        self.assertEqual(rcmap.cell_status(1, [UNKNOWN], {"n": 0}), "transport_fail")  # 모르는 코드는 믿지 않음

    def test_horizon_from_dates(self):
        base = {"n": 0, "horizon_oldest": "2025-09-01", "horizon_newest": "2026-09-02T01:00:00Z"}
        self.assertEqual(rcmap.cell_status(1, [], dict(base, date="2025-08-31")), "out_of_horizon")
        self.assertEqual(rcmap.cell_status(1, [], dict(base, date="2025-09-01")), "zero_ok")
        self.assertEqual(rcmap.cell_status(1, [], dict(base, date="2026-09-02")), "zero_ok")
        self.assertEqual(rcmap.cell_status(1, [], dict(base, date="2026-09-03")), "out_of_horizon")
        self.assertEqual(rcmap.cell_status(1, [], {"n": 0, "date": "2026-01-01", "horizon_oldest": None}), "zero_ok")
        # 셀 지평선 정보가 없으면 실행 사유 R-HORIZON 으로 판단
        self.assertEqual(rcmap.cell_status(1, ["R-HORIZON"], {"n": 0}), "out_of_horizon")
        self.assertEqual(rcmap.cell_status(4, ["R-HORIZON"], {"n": 2}), "ok")

    def test_flags_from_stage_result_fields(self):
        # 단계 결과 dict 를 그대로 counts 로 넘겨도 된다: caps_hit · stop_kind=budget
        self.assertEqual(rcmap.translate_cell(0, [], {"caps_hit": {"rows": 3}})["cap_hit"], True)
        self.assertEqual(rcmap.translate_cell(0, [], {"stop_kind": "budget"})["budget_hit"], True)
        self.assertEqual(rcmap.cell_status(0, ["R-CAP"]), "partial")
        self.assertEqual(rcmap.cell_status(4, ["R-BUDGET"]), "partial")

    def test_bad_rc_values(self):
        for bad in (5, 99, -7, 255, True, False, "3", 3.0):
            self.assertEqual(rcmap.cell_status(bad), "transport_fail", bad)

    def test_unobserved_never_zero_hours(self):
        """T-09 의 수집 측: 미관측 4종은 zero_ok 와 다르다."""
        self.assertEqual(rcmap.UNOBSERVED, {"not_attempted", "blocked", "transport_fail", "out_of_horizon"})
        self.assertNotIn("zero_ok", rcmap.UNOBSERVED)


# ── 정제 파이프(계약 §8.2) ─────────────────────────────────────────────────
class PipeFailure(unittest.TestCase):
    def test_table(self):
        self.assertEqual(rcmap.pipe_failure(0), (None, None))
        self.assertEqual(rcmap.pipe_failure(2), (None, None))
        self.assertEqual(rcmap.pipe_failure(3), (3, "R-TRANSPORT"))
        self.assertEqual(rcmap.pipe_failure(5), (3, "R-TRANSPORT"))
        self.assertEqual(rcmap.pipe_failure(6), (3, "R-NOKEY"))
        self.assertEqual(rcmap.pipe_failure(99), (3, "R-TRANSPORT"))
        for odd in (1, 4, -1, 120, None, "0", True):
            self.assertEqual(rcmap.pipe_failure(odd), (3, "R-TRANSPORT"), odd)

    def test_cursor_only_after_successful_write(self):
        self.assertTrue(rcmap.pipe_cursor_ok(0))
        self.assertTrue(rcmap.pipe_cursor_ok(2))
        for c in (3, 5, 6, 99, 1, None):
            self.assertFalse(rcmap.pipe_cursor_ok(c))

    def test_hints(self):
        self.assertEqual(rcmap.pipe_hint(0), "")
        self.assertIn("정제기 실패", rcmap.pipe_hint(3))
        self.assertIn("정제기 호출 오류", rcmap.pipe_hint(5))
        for c in (6, 99, 77):
            h = rcmap.pipe_hint(c)
            self.assertTrue(h and "\n" not in h)

    def test_apply_pipe(self):
        self.assertEqual(rcmap.apply_pipe(0, [], 0), (0, []))
        self.assertEqual(rcmap.apply_pipe(4, ["R-NOADDR"], 2), (4, ["R-NOADDR"]))
        self.assertEqual(rcmap.apply_pipe(0, [], 3), (3, ["R-TRANSPORT"]))
        self.assertEqual(rcmap.apply_pipe(0, ["R-CAP"], 6), (3, ["R-CAP", "R-NOKEY"]))
        rc, rs = rcmap.apply_pipe(0, [], 99)
        self.assertEqual(rcmap.cell_status(rc, rs), "transport_fail")


# ── 단계 결과 번역 ─────────────────────────────────────────────────────────
class StageOutcome(unittest.TestCase):
    def test_cases(self):
        so = rcmap.stage_outcome
        o = so(None)
        self.assertEqual((o["state"], o["rc"], o["stop_kind"]), ("skipped", rcmap.RC_NOT_RUN, None))
        o = so(0, [], {"n": 12})
        self.assertEqual((o["state"], o["rc"], o["reason"], o["resumable"]), ("done", 0, None, False))
        o = so(1)
        self.assertEqual((o["state"], o["rc"]), ("done", 1))
        o = so(4)
        self.assertEqual((o["state"], o["rc"]), ("done", 4))
        o = so(2)
        self.assertEqual((o["state"], o["stop_kind"], o["reason"], o["resumable"]), ("partial", "login", "R-LOGIN", True))
        self.assertEqual(so(2, ["R-CA"])["reason"], "R-CA")
        o = so(3, ["R-NEWOL"])
        self.assertEqual((o["state"], o["reason"], o["rc"], o["stop_kind"]), ("skipped", "R-NEWOL", 3, None))
        o = so(3, [])
        self.assertEqual((o["state"], o["stop_kind"], o["reason"], o["rc"]), ("partial", "fatal", "R-TRANSPORT", 3))
        self.assertEqual(so(3, ["R-NOKEY"])["reason"], "R-NOKEY")
        o = so(3, ["R-HORIZON"])
        self.assertEqual((o["state"], o["reason"]), ("skipped", "R-HORIZON"))
        o = so(1, ["R-UIAEMPTY"], {"n": 0})
        self.assertEqual((o["state"], o["reason"], o["rc"]), ("skipped", "R-UIAEMPTY", 1))
        o = so(7)
        self.assertEqual((o["state"], o["stop_kind"], o["rc"], o["reason"]), ("partial", "fatal", 7, "R-TRANSPORT"))
        for stop in ("stall", "no_progress"):
            o = so(1, [], {"stop_kind": stop})
            self.assertEqual((o["state"], o["stop_kind"], o["rc"], o["reason"]), ("partial", stop, 3, "R-TRANSPORT"))
        o = so(0, [], {"stop_kind": "cancelled"})
        self.assertEqual((o["state"], o["stop_kind"], o["rc"], o["resumable"]), ("partial", "cancelled", 0, True))

    def test_unknown_reason_codes_fold_to_transport(self):
        """수집기 사유는 바깥 입력 — §6.1 에 없는 코드(새·폐지)는 판정에서 '수송'으로 세고, 결과에는 싣지 않는다."""
        new = "R-" + "NEWCODE"                            # 계약 밖 코드(L-13 — 저장소 문자열로 두지 않는다)
        dep = "R-" + "SAMPLER-CLM"                        # 폐지 코드
        self.assertEqual(rcmap.cell_status(3, [new], {"n": 0}), "transport_fail")
        o = rcmap.stage_outcome(3, [new], {"n": 0})
        self.assertEqual((o["state"], o["stop_kind"], o["reason"], o["reasons"], o["unknown_reasons"]),
                         ("partial", "fatal", "R-TRANSPORT", ["R-TRANSPORT"], 1))
        o = rcmap.stage_outcome(0, [dep], {"n": 5})
        self.assertEqual((o["state"], o["reason"], o["reasons"], o["unknown_reasons"]), ("done", None, [], 1))
        o = rcmap.stage_outcome(3, ["R-NEWOL", new])                      # 아는 구조 사유가 주 원인이면 그대로
        self.assertEqual((o["state"], o["reason"], o["reasons"], o["unknown_reasons"]), ("skipped", "R-NEWOL", ["R-NEWOL"], 1))
        o = rcmap.stage_outcome(None, [new])
        self.assertEqual((o["state"], o["reason"]), ("skipped", "R-TRANSPORT"))
        self.assertNotIn("unknown_reasons", rcmap.stage_outcome(0, ["R-OMG"], {"n": 1}))
        for args in ((3, [new]), (0, [dep], {"n": 5}), (2, [new]), (0, [new], {"stop_kind": "cancelled"})):
            o = rcmap.stage_outcome(*args)
            self.assertTrue(all(rcmap.is_reason(r) for r in o["reasons"]), o)
            self.assertTrue(o["reason"] is None or rcmap.is_reason(o["reason"]), o)

    def test_T10_cap_budget_keep_rc0(self):
        o = rcmap.stage_outcome(0, [], {"cap_hit": True})
        self.assertEqual((o["state"], o["rc"], o["caps_hit"], o["reason"], o["stop_kind"]),
                         ("partial", 0, True, "R-CAP", None))
        o = rcmap.stage_outcome(0, [], {"budget_hit": True})
        self.assertEqual((o["state"], o["rc"], o["stop_kind"], o["reason"], o["resumable"]),
                         ("partial", 0, "budget", "R-BUDGET", True))
        o = rcmap.stage_outcome(0, ["R-CAP", "R-BUDGET"])
        self.assertEqual((o["state"], o["rc"], o["stop_kind"], o["caps_hit"]), ("partial", 0, "budget", True))
        self.assertEqual(o["reasons"], ["R-BUDGET", "R-CAP"])
        cell = rcmap.translate_cell(o["rc"], o["reasons"], o)              # 단계 결과를 그대로 넘겨도 같은 판정
        self.assertEqual((cell["status"], cell["cap_hit"], cell["budget_hit"]), ("partial", True, True))

    def test_stage_and_cell_agree(self):
        stage_of = {"not_attempted": {"skipped"}, "blocked": {"skipped", "partial"}, "transport_fail": {"partial"},
                    "partial": {"partial"}, "ok": {"done"}, "zero_ok": {"done"},
                    "out_of_horizon": {"done", "skipped"}}
        for rc, n, in_h, block, cap, budget in itertools.product(RCS, NS, HORIZONS, BLOCKS, FLAGS, FLAGS):
            cell = call(rc, n, in_h, block, cap, budget)
            counts = {"in_horizon": in_h, "cap_hit": cap, "budget_hit": budget}
            if n is not None:
                counts["n"] = n
            real_rc = rc
            if rc == "timeout_stall":
                counts["stop_kind"], real_rc = "stall", 3
            elif rc == "timeout_noprog":
                counts["stop_kind"], real_rc = "no_progress", 1
            o = rcmap.stage_outcome(real_rc, [block] if block else [], counts)
            self.assertIn(o["state"], stage_of[cell["status"]], (rc, n, in_h, block, cap, budget, o))
            if cell["status"] == "blocked" and o["state"] == "partial":
                self.assertEqual(o["stop_kind"], "login")                  # rc 2 만 partial
            self.assertEqual(sorted(set(o["reasons"])), o["reasons"])
            self.assertTrue(o["reason"] is None or rcmap.is_reason(o["reason"]), o)
            self.assertTrue(isinstance(o["hint"], str) and "\n" not in o["hint"])


# ── collect 명령 rc(계약 §8.3) ─────────────────────────────────────────────
def res(state, items_ok=0, reason=None, reasons=()):
    return {"state": state, "items_ok": items_ok, "reason": reason, "reasons": list(reasons)}


class CollectRc(unittest.TestCase):
    def test_table(self):
        self.assertEqual(rcmap.collect_rc([res("done", 3), res("done", 0)]), 0)
        self.assertEqual(rcmap.collect_rc([res("done", 0), res("skipped")]), 4)
        self.assertEqual(rcmap.collect_rc([]), 4)
        self.assertEqual(rcmap.collect_rc([res("done", 5), res("partial", 1, "R-BUDGET")]), 2)
        self.assertEqual(rcmap.collect_rc([res("partial"), res("failed", 0, "R-TRANSPORT")]), 1)
        self.assertEqual(rcmap.collect_rc([res("done", 9), res("failed", 0, "R-CLM")]), 3)
        self.assertEqual(rcmap.collect_rc([res("done", 9), res("partial", 0, None, ["R-BUNDLE-READONLY"])]), 3)
        # 구조적 막힘은 skipped 로 끝나 0/4 로 흡수(C §8.4)
        self.assertEqual(rcmap.collect_rc([res("done", 2), res("skipped", 0, "R-NEWOL", ["R-NEWOL"])]), 0)
        self.assertEqual(rcmap.collect_rc([res("skipped", 0, "R-CLM")]), 4)

    def test_from_outcomes(self):
        rows = [dict(rcmap.stage_outcome(0), items_ok=10), rcmap.stage_outcome(3, ["R-NEWOL"]),
                rcmap.stage_outcome(None)]
        self.assertEqual(rcmap.collect_rc(rows), 0)
        rows.append(rcmap.stage_outcome(0, [], {"budget_hit": True}))
        self.assertEqual(rcmap.collect_rc(rows), 2)

    def test_new_records(self):
        self.assertEqual(rcmap.new_records({"items_ok": 7}), 7)
        self.assertEqual(rcmap.new_records({"items_ok": True}), 0)
        self.assertEqual(rcmap.new_records({}), 0)
        self.assertEqual(rcmap.new_records(None), 0)


if __name__ == "__main__":
    unittest.main()
