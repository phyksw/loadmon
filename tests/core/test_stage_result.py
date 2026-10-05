# -*- coding: utf-8 -*-
"""WP-03 stage_result — 단계 결과 공통 스키마 lm27.stage/1 과 finally 원자 기록(계약 §8.4·§8.5, X-122·X-123, T-10).

★ 대조표: 이 파일 머리의 ``STAGE_COMMON_TABLE`` · ``STAGE_STATES`` · ``STAGE_STOP_KINDS`` · ``check_stage_common`` 은
계약 §8.5 를 구현과 따로 옮겨 적은 것이다. 브리지(WP-24)·분석(WP-32) 시험은 **이름만** import 해 같은 검사를 한다::

    from tests.core.test_stage_result import check_stage_common      # TestCase 를 끌어오지 않게 이름만
    self.assertEqual(check_stage_common(envelope), [])

합성 값만 쓴다(실명·원문 없음). 쓰기는 임시 폴더에만 한다.
"""
import contextlib
import io
import os
import re
import shutil
import tempfile
import unittest
from pathlib import Path

# ── 계약 §8.5 대조표(구현과 독립) ──────────────────────────────────────────
STAGE_SCHEMA = "lm27.stage/1"
STAGE_COMMON_TABLE = (
    ("schema", "schema"), ("run_id", "run_id"), ("stage", "str"), ("state", "state"),
    ("items_total", "count"), ("items_ok", "count"), ("items_failed", "count"), ("items_pending", "count"),
    ("stop_kind", "stop_kind"), ("resumable", "bool"), ("reason", "reason"), ("hint", "hint"),
    ("caps_hit", "caps"), ("rc", "int"), ("updated", "utc"), ("counts", "dict"),
)
STAGE_STATES = ("done", "partial", "failed", "skipped")
STAGE_STOP_KINDS = ("budget", "fatal", "circuit", "refused", "manual_wait", "header", "gate", "cancelled", "login",
                    "stall", "no_progress")
COLLECT_STAGE_NAMES = ("probe", "pc_bundle", "mail_local", "cal_local", "teams_uia_check", "backfill_owa",
                       "backfill_teams_web", "copilot_lookup", "import", "export", "derive", "upload")
STATE_TO_RC = {"done": 0, "skipped": 0, "partial": 2, "failed": 1}       # 계약 §8.4(브리지·분석)
_RUN_RX = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{4}$")
_UTC_RX = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def _int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def check_stage_common(obj) -> list:
    """계약 §8.5 공통 필드 대조 → 문제 목록(빈 목록 = 통과). 추가 필드는 보지 않는다."""
    if not isinstance(obj, dict):
        return ["dict 아님"]
    probs = [f"없음: {k}" for k, _ in STAGE_COMMON_TABLE if k not in obj]
    if probs:
        return probs
    for k, kind in STAGE_COMMON_TABLE:
        v = obj[k]
        ok = {
            "schema": v == STAGE_SCHEMA,
            "run_id": isinstance(v, str) and bool(_RUN_RX.match(v)),
            "str": isinstance(v, str) and bool(v),
            "state": v in STAGE_STATES,
            "count": _int(v) and v >= 0,
            "stop_kind": v is None or v in STAGE_STOP_KINDS,
            "bool": isinstance(v, bool),
            "reason": v is None or (isinstance(v, str) and bool(v)),
            "hint": isinstance(v, str) and "\n" not in v,
            "caps": isinstance(v, bool) or (isinstance(v, dict) and all(_int(x) and x >= 0 for x in v.values())),
            "int": _int(v),
            "utc": isinstance(v, str) and bool(_UTC_RX.match(v)),
            "dict": isinstance(v, dict),
        }[kind]
        if not ok:
            probs.append(f"형이 틀림: {k}={v!r}")
    if obj["state"] == "done" and obj["stop_kind"] is not None:
        probs.append("done 인데 stop_kind 있음")
    return probs


# ── 시험 ────────────────────────────────────────────────────────────────────
from lm27.collect import rcmap  # noqa: E402
from lm27.collect import stage_result as sr  # noqa: E402
from lm27.util import fsx  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
RUN = "20261005-101500-3fa2"
RUN2 = "20261006-080000-00ff"
T = "2026-10-05T01:02:03Z"
UNKNOWN_CODE = "R-" + "ZZUNKNOWN"    # §6.1 밖 사유 코드 — 런타임 조립(L-13)


class FakePaths:
    """계약 Paths 의 이 WP 가 쓰는 메서드 하나만 — 실제 배치와 무관한 임시 폴더."""

    def __init__(self, base):
        self.base = Path(base)

    def collect_stage_results(self, run_id):
        return self.base / "stage_results" / run_id

    def stage_result_file(self, run_id, stage):
        return self.collect_stage_results(run_id) / f"stage_result_{stage}.json"


class _Tmp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="lm27t_wp03_")
        self.paths = FakePaths(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class ContractTable(unittest.TestCase):
    def test_module_constants_match_contract(self):
        self.assertEqual(sr.SCHEMA, STAGE_SCHEMA)
        self.assertEqual(sr.COMMON_FIELDS, tuple(k for k, _ in STAGE_COMMON_TABLE))
        self.assertEqual(sr.STATES, STAGE_STATES)
        self.assertEqual(sr.STOP_KINDS, STAGE_STOP_KINDS)
        self.assertEqual(sr.COLLECT_STAGES, COLLECT_STAGE_NAMES)
        self.assertEqual(sr.STATE_RC, STATE_TO_RC)

    def test_checker_catches(self):
        self.assertTrue(check_stage_common({}))
        good = sr.build_stage_result(RUN, "mail_local", state="done", rc=0, updated=T)
        self.assertEqual(check_stage_common(good), [])
        self.assertTrue(check_stage_common(dict(good, stop_kind="budget")))
        self.assertTrue(check_stage_common(dict(good, rc=True)))


class Build(unittest.TestCase):
    def test_defaults_fill_all_common_fields(self):
        o = sr.build_stage_result(RUN, "probe", state="done", rc=0, updated=T)
        self.assertEqual(check_stage_common(o), [])
        self.assertEqual(sr.validate_stage_result(o, collect=True), [])
        self.assertEqual({k: o[k] for k in sr.ITEM_FIELDS}, dict.fromkeys(sr.ITEM_FIELDS, 0))
        self.assertEqual((o["stop_kind"], o["reason"], o["hint"], o["caps_hit"], o["counts"], o["resumable"]),
                         (None, None, "", False, {}, False))
        self.assertEqual(sr.build_stage_result(RUN, "probe", state="partial", rc=0, updated=T)["resumable"], True)

    def test_updated_default_is_utc_now(self):
        o = sr.build_stage_result(RUN, "probe", state="done", rc=0)
        self.assertRegex(o["updated"], _UTC_RX)

    def test_state_required_and_rc_default_by_state(self):
        with self.assertRaises(ValueError):
            sr.build_stage_result(RUN, "probe", rc=0)
        for st, rc in STATE_TO_RC.items():
            o = sr.build_stage_result(RUN, "task_label", state=st, updated=T,
                                      stop_kind=None if st == "done" else "budget")
            self.assertEqual(o["rc"], rc)

    def test_analysis_and_bridge_stage_ids(self):
        o = sr.build_stage_result(RUN, "ai:task_label", state="skipped", reason="web_exposed", updated=T)
        self.assertEqual(check_stage_common(o), [])
        self.assertTrue(sr.validate_stage_result(o, collect=True))      # 수집 단계 이름은 아니다

    def test_extra_fields(self):
        o = sr.build_stage_result(RUN, "mail_local", state="partial", rc=0, updated=T, stop_kind="budget",
                                  reason="R-BUDGET", src="mail.com", subfolder_ratio=0.12,
                                  recurrence_incomplete=False, skipped_msg=0, reasons=["R-BUDGET"],
                                  counts={"stored": 790, "dropped": {"ad": 3}}, caps_hit={"rows": 1})
        self.assertEqual(check_stage_common(o), [])
        self.assertEqual((o["src"], o["subfolder_ratio"]), ("mail.com", 0.12))

    def test_validate_rejections(self):
        good = {"state": "done", "rc": 0, "updated": T}
        bad_cases = [
            dict(good, state="ok"),                       # 셀 상태는 단계 state 가 아니다(X-123)
            dict(good, stop_kind="timeout"),
            dict(good, stop_kind="budget"),               # done 인데 stop_kind
            dict(good, items_ok=-1),
            dict(good, items_total=True),
            dict(good, rc=True),
            dict(good, rc="0"),
            dict(good, resumable="yes"),
            dict(good, reason=UNKNOWN_CODE),        # §6.1 밖 사유 코드(L-13)
            dict(good, reason="Bad Reason"),
            dict(good, hint="두 줄\n안내"),
            dict(good, hint="가" * (sr.HINT_MAX + 1)),
            dict(good, caps_hit={"rows": -1}),
            dict(good, caps_hit="yes"),
            dict(good, updated="2026-10-05 01:02:03"),
            dict(good, counts={"subject": "원문 제목"}),   # counts 에 글 금지(원문 0)
            dict(good, counts={"x": float("nan")}),
            dict(good, counts=[1, 2]),
            dict(good, src="가" * (sr.EXTRA_STR_MAX + 1)),  # 추가 필드 긴 글 금지
            dict(good, note="줄\x07바꿈"),
            dict(good, reasons=[UNKNOWN_CODE]),
            dict(good, **{"Bad-Key": 1}),
            dict(good, schema="lm27.stage/2"),
        ]
        for f in bad_cases:
            with self.assertRaises(ValueError, msg=repr(f)):
                sr.build_stage_result(RUN, "probe", **f)
        with self.assertRaises(ValueError):
            sr.build_stage_result("../x", "probe", **good)
        with self.assertRaises(ValueError):
            sr.build_stage_result(RUN, "Probe/../x", **good)

    def test_reason_forms(self):
        for r in ("R-NEWOL", "web_exposed", "capability_unavailable", "gated:web_combo", "stage_result_invalid"):
            o = sr.build_stage_result(RUN, "probe", state="skipped", rc=0, reason=r, updated=T)
            self.assertEqual(o["reason"], r)
        self.assertIsNone(sr.build_stage_result(RUN, "probe", state="done", rc=0, reason="", updated=T)["reason"])


class WriteRead(_Tmp):
    def test_write_atomic_canon_and_read_back(self):
        o = sr.write_stage_result(self.paths, RUN, "mail_local", state="done", rc=0, updated=T, src="mail.com",
                                  items_total=5, items_ok=5)
        p = Path(sr.stage_result_path(self.paths, RUN, "mail_local"))
        self.assertEqual(p, self.paths.collect_stage_results(RUN) / "stage_result_mail_local.json")
        self.assertEqual(p.read_bytes(), fsx.canon_bytes(o))
        self.assertEqual(sr.read_stage_result(self.paths, RUN, "mail_local"), o)
        self.assertEqual([x.name for x in p.parent.iterdir()], [p.name])          # .part 조각 0
        self.assertEqual(check_stage_common(o), [])

    def test_rewrite_replaces_whole_file(self):
        sr.write_stage_result(self.paths, RUN, "probe", state="partial", rc=0, stop_kind="budget", updated=T,
                              counts={"a": 1})
        o = sr.write_stage_result(self.paths, RUN, "probe", state="done", rc=0, updated=T)
        self.assertEqual(sr.read_stage_result(self.paths, RUN, "probe"), o)
        self.assertEqual(o["counts"], {})

    def test_requirements(self):
        with self.assertRaises(ValueError):
            sr.write_stage_result(self.paths, RUN, "probe", state="done")           # 수집기 rc 필수
        with self.assertRaises(ValueError):
            sr.write_stage_result(self.paths, RUN, "probe", rc=0)
        with self.assertRaises(ValueError):
            sr.write_stage_result(self.paths, RUN, "ai:task_label", state="done", rc=0)
        for bad_run in ("..", "20261005-101500-3FA2", "x/../20261005-101500-3fa2", None):
            with self.assertRaises(ValueError):
                sr.write_stage_result(self.paths, bad_run, "probe", state="done", rc=0)
        self.assertFalse(Path(self.tmp, "stage_results").exists())

    def test_read_missing_and_corrupt(self):
        self.assertIsNone(sr.read_stage_result(self.paths, RUN, "probe"))
        fsx.atomic_write(sr.stage_result_path(self.paths, RUN, "derive"), b"{bad")
        fsx.atomic_write(sr.stage_result_path(self.paths, RUN, "export"), fsx.canon_bytes({"schema": 1}))
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertIsNone(sr.read_stage_result(self.paths, RUN, "derive"))
        self.assertIsNone(sr.read_stage_result(self.paths, RUN, "export"))

    def test_read_all_of_run(self):
        sr.write_stage_result(self.paths, RUN, "upload", state="skipped", rc=rcmap.RC_NOT_RUN, updated=T)
        sr.write_stage_result(self.paths, RUN, "probe", state="done", rc=0, updated=T)
        sr.write_stage_result(self.paths, RUN2, "derive", state="done", rc=0, updated=T)
        got = sr.read_stage_results(self.paths, RUN)
        self.assertEqual(list(got), ["probe", "upload"])
        self.assertEqual(sr.read_stage_results(self.paths, "20200101-000000-0000"), {})

    def test_real_paths_if_present(self):
        if not (ROOT / "lm27" / "paths.py").is_file():
            self.skipTest("lm27.paths 아직 없음(WP-00)")
        from lm27.paths import Paths
        rp = Paths(Path(self.tmp))
        o = sr.write_stage_result(rp, RUN, "probe", state="done", rc=0, updated=T)
        p = Path(sr.stage_result_path(rp, RUN, "probe"))
        self.assertEqual(p, rp.collect_stage_results(RUN) / "stage_result_probe.json")      # 계약 §8.5 위치
        self.assertTrue(str(p).startswith(str(Path(self.tmp))))
        self.assertEqual(sr.read_stage_result(rp, RUN, "probe"), o)


class Scope(_Tmp):
    def read(self, stage, run=RUN):
        return sr.read_stage_result(self.paths, run, stage)

    def test_normal_exit(self):
        with sr.stage_scope(self.paths, RUN, "mail_local", src="mail.com", updated=T) as st:
            st.outcome(0, [], {"n": 3}).set(items_total=4, items_ok=3, items_failed=1)
        o = self.read("mail_local")
        self.assertEqual((o["state"], o["rc"], o["items_ok"], o["src"]), ("done", 0, 3, "mail.com"))
        self.assertEqual(st.result, o)
        self.assertEqual(check_stage_common(o), [])

    def test_untouched_body_is_not_run(self):
        with sr.stage_scope(self.paths, RUN, "backfill_owa"):
            pass
        o = self.read("backfill_owa")
        self.assertEqual((o["state"], o["rc"]), ("skipped", rcmap.RC_NOT_RUN))
        self.assertEqual(rcmap.cell_status(o["rc"], o.get("reasons"), o), "not_attempted")

    def test_exception_leaves_file_and_propagates(self):
        with self.assertRaises(RuntimeError):
            with sr.stage_scope(self.paths, RUN, "cal_local", src="cal.com") as st:
                st.outcome(0, [], {"cap_hit": True}).set(items_ok=2)
                raise RuntimeError("합성 오류")
        o = self.read("cal_local")
        self.assertEqual(check_stage_common(o), [])
        self.assertEqual((o["state"], o["stop_kind"], o["rc"], o["reason"], o["error_type"], o["resumable"]),
                         ("failed", "fatal", 3, "R-TRANSPORT", "RuntimeError", True))
        self.assertIn("R-TRANSPORT", o["reasons"])
        self.assertIn("R-CAP", o["reasons"])                                   # 앞서 정한 사유 보존
        self.assertEqual(o["items_ok"], 2)
        self.assertNotIn("합성 오류", fsx.read_bytes(sr.stage_result_path(self.paths, RUN, "cal_local")).decode())
        self.assertEqual(rcmap.cell_status(o["rc"], o["reasons"], o), "transport_fail")
        self.assertEqual(rcmap.collect_rc([o]), 1)

    def test_keyboard_interrupt_is_cancelled(self):
        with self.assertRaises(KeyboardInterrupt):
            with sr.stage_scope(self.paths, RUN, "export"):
                raise KeyboardInterrupt
        o = self.read("export")
        self.assertEqual((o["state"], o["stop_kind"], o["resumable"]), ("partial", "cancelled", True))

    def test_write_failure_does_not_mask_original(self):
        blocker = Path(self.tmp, "blocker")
        fsx.atomic_write(blocker, b"x")

        class BlockedPaths:
            def stage_result_file(self, run_id, stage):
                return blocker / run_id / stage               # 파일 아래 폴더 → 쓰기 실패(OSError)

        with self.assertRaises(LookupError):
            with sr.stage_scope(BlockedPaths(), RUN, "probe") as st:
                raise LookupError("합성")
        self.assertIsNotNone(st.write_error)
        with self.assertRaises(OSError):
            with sr.stage_scope(BlockedPaths(), RUN, "probe") as st2:
                st2.outcome(0)

    def test_invalid_fields_still_leave_file_then_raise(self):
        with self.assertRaises(ValueError):
            with sr.stage_scope(self.paths, RUN, "derive") as st:
                st.outcome(0).set(items_total=7, counts={"subject": "원문이 들어가면 안 됨"})
        o = self.read("derive")
        self.assertEqual((o["state"], o["reason"], o["items_total"]), ("failed", sr.INVALID_REASON, 7))
        self.assertNotIn("원문이", fsx.read_bytes(sr.stage_result_path(self.paths, RUN, "derive")).decode())

    def test_bad_ids_fail_before_body(self):
        ran = []
        with self.assertRaises(ValueError):
            with sr.stage_scope(self.paths, RUN, "mail"):
                ran.append(1)
        with self.assertRaises(ValueError):
            with sr.stage_scope(self.paths, "nope", "probe"):
                ran.append(1)
        self.assertEqual(ran, [])

    def test_bump(self):
        with sr.stage_scope(self.paths, RUN, "pc_bundle") as st:
            st.outcome(4)
            st.bump(items_total=3, files=2).bump(items_total=2, files=1, events=5)
            with self.assertRaises(TypeError):
                st.bump(items_ok=1.5)
        o = self.read("pc_bundle")
        self.assertEqual((o["items_total"], o["counts"]), (5, {"events": 5, "files": 3}))

    def test_unknown_collector_reason_does_not_fail_stage(self):
        """바깥 수집기가 §6.1 밖 코드를 내도 ValueError·'stage_result_invalid' failed(collect rc 1)가 되지 않는다."""
        new, dep = "R-" + "NEWCODE", "R-" + "SAMPLER-CLM"
        with sr.stage_scope(self.paths, RUN, "mail_local") as st:
            st.outcome(3, [new], {"n": 0})
        o = self.read("mail_local")
        self.assertEqual((o["state"], o["stop_kind"], o["reason"], o["reasons"], o["unknown_reasons"]),
                         ("partial", "fatal", "R-TRANSPORT", ["R-TRANSPORT"], 1))
        self.assertEqual(sr.validate_stage_result(o, collect=True), [])
        with sr.stage_scope(self.paths, RUN, "pc_bundle") as st:
            st.outcome(0, [dep], {"n": 5})
            st.outcome(0, [], {"n": 5})                    # 다시 정하면 앞의 unknown_reasons 는 남지 않는다
        o = self.read("pc_bundle")
        self.assertEqual((o["state"], o["reason"], o["reasons"]), ("done", None, []))
        self.assertNotIn("unknown_reasons", o)
        self.assertEqual(rcmap.collect_rc([self.read("mail_local"), o]), 2)

    def test_T10_budget_and_cap_through_scope(self):
        with sr.stage_scope(self.paths, RUN, "mail_local") as st:
            st.outcome(0, [], {"budget_hit": True})
        o = self.read("mail_local")
        self.assertEqual((o["state"], o["rc"], o["stop_kind"], o["reason"]), ("partial", 0, "budget", "R-BUDGET"))
        cell = rcmap.translate_cell(o["rc"], o["reasons"], o)
        self.assertEqual((cell["status"], cell["budget_hit"]), ("partial", True))
        with sr.stage_scope(self.paths, RUN, "cal_local") as st:
            st.outcome(0, ["R-CAP"])
        o = self.read("cal_local")
        self.assertEqual((o["state"], o["rc"], o["caps_hit"]), ("partial", 0, True))
        self.assertEqual(rcmap.translate_cell(o["rc"], o["reasons"], o)["cap_hit"], True)


class RcTools(unittest.TestCase):
    def test_state_rc(self):
        for st, rc in STATE_TO_RC.items():
            self.assertEqual(sr.state_rc(st), rc)
        with self.assertRaises(ValueError):
            sr.state_rc("ok")

    def test_worst_rc(self):
        self.assertEqual(sr.worst_rc([]), 0)
        self.assertEqual(sr.worst_rc([0, 0]), 0)
        self.assertEqual(sr.worst_rc([0, 2, 0]), 2)
        self.assertEqual(sr.worst_rc([2, 1, 0]), 1)
        self.assertEqual(sr.worst_rc([1, 2]), 1)
        for bad in ([3], [True], ["1"]):
            with self.assertRaises(ValueError):
                sr.worst_rc(bad)


class ResumeRules(unittest.TestCase):
    def test_input_sig(self):
        a = sr.input_sig({"from": "2026-09-01", "to": "2026-09-30", "srcs": ["mail.com"]})
        b = sr.input_sig({"srcs": ["mail.com"], "to": "2026-09-30", "from": "2026-09-01"})
        c = sr.input_sig({"from": "2026-09-01", "to": "2026-10-01", "srcs": ["mail.com"]})
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)
        self.assertRegex(a, r"^[0-9a-f]{16}$")

    def test_resume_decision(self):
        sig = "0123456789abcdef"
        done = sr.build_stage_result(RUN, "probe", state="done", rc=0, updated=T, input_sig=sig)
        part = sr.build_stage_result(RUN, "probe", state="partial", rc=0, stop_kind="budget", updated=T,
                                     input_sig=sig)
        failed = sr.build_stage_result(RUN, "probe", state="failed", rc=3, stop_kind="fatal", updated=T,
                                       input_sig=sig)
        self.assertEqual(sr.resume_decision(done, sig), "skip")
        self.assertEqual(sr.resume_decision(part, sig), "resume")
        self.assertEqual(sr.resume_decision(dict(part, resumable=False), sig), "fresh")
        self.assertEqual(sr.resume_decision(failed, sig), "fresh")
        self.assertEqual(sr.resume_decision(done, "fedcba9876543210"), "fresh")   # 입력이 바뀌면 처음부터
        self.assertEqual(sr.resume_decision(None, sig), "fresh")
        self.assertEqual(sr.resume_decision(dict(done, schema=1), sig), "fresh")
        self.assertEqual(sr.resume_decision(done, ""), "fresh")

    def test_may_replace(self):
        prev = {"state": "done", "rows": 10}
        self.assertTrue(sr.may_replace(None, {"state": "partial"}))
        self.assertTrue(sr.may_replace({}, {"state": "failed"}))
        self.assertTrue(sr.may_replace(prev, {"state": "done"}))
        for st in ("partial", "failed", "skipped"):
            self.assertFalse(sr.may_replace(prev, {"state": st}), st)               # 성공 전 무효화 금지

    def test_keep_nonempty(self):
        prev = {"a": 1, "b": [1], "c": "x", "d": {"k": 1}}
        new = {"a": None, "b": [], "c": "", "d": {}, "e": None, "f": 2}
        self.assertEqual(sr.keep_nonempty(prev, new), {"a": 1, "b": [1], "c": "x", "d": {"k": 1}, "e": None, "f": 2})
        self.assertEqual(sr.keep_nonempty(prev, {"a": 0}), dict(prev, a=0))          # 0 은 빈 값이 아니다
        self.assertEqual(sr.keep_nonempty(None, {"a": 1}), {"a": 1})
        self.assertEqual(prev, {"a": 1, "b": [1], "c": "x", "d": {"k": 1}})        # 입력은 그대로


class Encoding(unittest.TestCase):
    def test_module_files_utf8_lf(self):
        for n in ("stage_result.py", "rcmap.py", "watch.py"):
            raw = (ROOT / "lm27" / "collect" / n).read_bytes()
            self.assertFalse(raw.startswith(b"\xef\xbb\xbf"), n)
            self.assertNotIn(b"\r\n", raw, n)
            raw.decode("utf-8")
            self.assertIsNone(re.search(rb"[\x00-\x08\x0b\x0c\x0e-\x1f]", raw), n)
            self.assertNotIn(b"zoneinfo", raw, n)
            self.assertNotIn(b"os.kill(", raw, n)
            self.assertNotIn(b'open(', raw.replace(b"OpenProcess", b""), n)        # 쓰기는 fsx 만(L-07)
        self.assertTrue(os.path.isfile(ROOT / "lm27" / "collect" / "__init__.py"))


if __name__ == "__main__":
    unittest.main()
