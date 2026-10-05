# -*- coding: utf-8 -*-
"""WP-27 schema — TEAM_SPEC_V1(L-23 · X-270)·공용 검증기(TAB §2.3.2 · 계약 §3.18)·BYTES_GUARD·active_spans·hello 판정.

합성 묶음만 쓴다(tests\\fixtures\\wp27). 정제 모듈(WP-11)은 가짜로 대신한다 — 실물 대조는 통합 창.
"""
import copy
import os
import sys
import unittest
from datetime import date

from lm27.team import schema
from tests.fixtures.wp27 import bundles as B
from tests.fixtures.wp27.helpers import fake_privacy

TREE = B.TREE


def _bundle(**kw):
    kw.setdefault("built_at", "2026-08-03T09:12:00+09:00")
    return B.make_bundle(B.person_key(1), "2026-07-01", "2026-07-31", **kw)


def _codes(errs, blocking=None):
    return sorted({e.code for e in errs if blocking is None or e.blocking == blocking})


class TestSpec(unittest.TestCase):
    def test_spec_top_equals_tab_and_privacy_tables(self):
        """L-23: TEAM_SPEC_V1 최상위 = TAB §2.3.2 표 ∪ P §14.5 표(생성 대조)."""
        sys.path.insert(0, os.path.join(str(TREE), "tools"))
        try:
            import hook_check
        finally:
            sys.path.pop(0)
        with open(os.path.join(str(TREE), "docs", "TEAM_AND_BUNDLE.md"), encoding="utf-8") as f:
            tab = f.read()
        with open(os.path.join(str(TREE), "docs", "PRIVACY.md"), encoding="utf-8") as f:
            pri = f.read()
        t, p = hook_check.parse_team_fields(tab, pri)
        self.assertTrue(t and p)
        self.assertEqual(set(schema.TEAM_SPEC_V1), t | p)

    def test_spec_table_generated(self):
        rows = dict(schema.spec_table())
        self.assertEqual(rows["person.person_key"], "PERSON_KEY")
        self.assertEqual(rows["alloc_daily.rows[]"], "[DATE, UNIT_ID, ENUM{regular,extended,night,holiday}, NUM]")
        self.assertEqual(rows["built_at"], "DATETIME_OFFSET")
        self.assertIn("units[].spans[]", rows)                    # X-272 gantt_spans → spans
        self.assertNotIn("person.function", rows)                 # 계약 §3.18 person.function → person.field

    def test_role_id_formula(self):
        """계약 §4.4 예: ("P-0007","OPT","ANALYSIS") → r_8412d7."""
        self.assertEqual(schema.role_id_of("P-0007", "OPT", "ANALYSIS"), "r_8412d7")
        self.assertEqual(schema.role_id_of(None, "A", "B"), schema.role_id_of("UNC", "A", "B"))


class TestValidate(unittest.TestCase):
    def test_valid_bundle_no_errors(self):
        o = _bundle()
        errs = schema.validate_team_bundle(o, B.registry(), "server", calendar=B.calendar(), payload_check=B.pass_check)
        self.assertEqual(errs, [])

    def test_proposal_role_and_partial_month(self):
        o = B.make_bundle(B.person_key(2), "2026-09-01", "2026-11-30", until="2026-10-05",
                          built_at="2026-10-05T09:00:00+09:00", project=None, proposal="pr_1")
        self.assertEqual(schema.blocking(schema.validate_team_bundle(o, None, "client", calendar=B.calendar())), [])

    def test_integrity_alloc_over_envelope(self):
        """A03: alloc 합 > env → integrity(조용한 재스케일 없음)."""
        o = _bundle()
        d, _u, t, _m = o["alloc_daily"]["rows"][0]
        env = next(r for r in o["envelope_daily"]["rows"] if r[0] == d)
        o["alloc_daily"]["rows"][0][3] = env[1 + B.TAGS.index(t)] + 1
        B.finalize(o)
        errs = schema.validate_team_bundle(o, None, "server", calendar=B.calendar())
        self.assertIn("integrity", _codes(errs, True))

    def test_summary_mismatch_is_integrity(self):
        o = _bundle()
        o["summary"]["months"][0]["mm"] += 0.01
        self.assertEqual(schema.first_code(schema.validate_team_bundle(o)), "integrity")
        o = _bundle()
        o["integrity"]["rows_alloc"] += 1
        self.assertIn("integrity", _codes(schema.validate_team_bundle(o), True))
        o = _bundle()
        o["units"][0]["effort_min"] += 1
        self.assertIn("integrity", _codes(schema.validate_team_bundle(o), True))

    def test_ref_missing(self):
        o = _bundle()
        o["units"][0]["role_id"] = "r_000000"
        self.assertIn("ref_missing", _codes(schema.validate_team_bundle(o), True))
        o = _bundle()
        o["alloc_daily"]["rows"][0][1] = "u_0000000000"
        B.finalize(o)
        self.assertIn("ref_missing", _codes(schema.validate_team_bundle(o), True))

    def test_role_id_recomputed(self):
        o = _bundle()
        o["roles"][0]["field"] = "MECH"
        self.assertIn("integrity", _codes(schema.validate_team_bundle(o), True))

    def test_unknown_major_and_minor(self):
        o = _bundle()
        o["schema_version"] = "2.0"
        self.assertEqual(_codes(schema.validate_team_bundle(o)), ["unknown_major"])
        o = _bundle()
        o["newer_field"] = 1
        self.assertEqual(_codes(schema.validate_team_bundle(o), True), ["schema"])        # 같은 MINOR → 422
        o["schema_version"] = "1.3"
        errs = schema.validate_team_bundle(o)
        self.assertEqual(schema.blocking(errs), [])
        self.assertIn("unknown_key", _codes(errs, False))                                 # 높은 MINOR → 경고

    def test_type_and_control_chars(self):
        o = _bundle(self_label="팀원\u200bA")
        self.assertIn("schema", _codes(schema.validate_team_bundle(o), True))
        o = _bundle()
        o["person"]["person_key"] = "p_XYZ"
        self.assertIn("schema", _codes(schema.validate_team_bundle(o), True))
        o = _bundle()
        o["built_at"] = "2026-08-03T09:12:00"                                             # 오프셋 없음
        self.assertIn("schema", _codes(schema.validate_team_bundle(o), True))
        o = _bundle()
        o["envelope_daily"]["rows"][0][1] = 1.5
        self.assertIn("schema", _codes(schema.validate_team_bundle(o), True))
        o = _bundle()
        del o["integrity"]
        self.assertIn("schema", _codes(schema.validate_team_bundle(o), True))
        self.assertEqual(_codes(schema.validate_team_bundle([1, 2])), ["schema"])

    def test_spans_rules(self):
        o = _bundle()
        o["units"][0]["spans"] = [s for s in o["units"][0]["spans"] if s[2] != "lead"]
        self.assertIn("schema", _codes(schema.validate_team_bundle(o), True))
        o = _bundle()
        acts = [s for s in o["units"][0]["spans"] if s[2] == "active"]
        o["units"][0]["spans"] = [s for s in o["units"][0]["spans"] if s[2] == "lead"] + [[acts[0][0], acts[-1][1],
                                                                                        "active"]]
        errs = schema.validate_team_bundle(o)
        if len(acts) > 1:
            self.assertIn("gantt_mismatch", _codes(errs, False))
        self.assertEqual(schema.blocking(errs), [])

    def test_calendar_and_registry_warnings(self):
        o = _bundle(workdays_override={"2026-07": 23}, member_id="M999")
        errs = schema.validate_team_bundle(o, B.registry(), "server", calendar=B.calendar(), pepper_id="00000000")
        self.assertEqual(schema.blocking(errs), [])
        self.assertIn("calendar_mismatch", _codes(errs, False))
        self.assertIn("unknown_member", _codes(errs, False))
        o = _bundle(pepper_id="9f2c01ab", project="P-0042")
        errs = schema.validate_team_bundle(o, B.registry(), "server", calendar=B.calendar(), pepper_id="00000000")
        self.assertIn("pepper_mismatch", _codes(errs, False))
        self.assertIn("unknown_project", _codes(errs, False))

    def test_period_rules(self):
        o = _bundle()
        o["period"]["months"] = ["2026-07", "2026-08"]
        self.assertIn("schema", _codes(schema.validate_team_bundle(o), True))
        o = B.make_bundle(B.person_key(1), "2025-01-01", "2026-03-01", built_at="2026-03-02T09:00:00+09:00")
        self.assertIn("schema", _codes(schema.validate_team_bundle(o), True))             # 400일 초과

    def test_payload_check_forbidden_content(self):
        o = _bundle()
        errs = schema.validate_team_bundle(o, None, "server", payload_check=lambda _o: [("units[0].title", "label:x")])
        self.assertEqual(schema.first_code(errs), "forbidden_content")
        self.assertEqual(errs[-1].as_detail(), "units[0].title: forbidden_content")

    def test_depth_guard(self):
        o = _bundle()
        deep = cur = {}
        for _ in range(40):
            cur["x"] = {}
            cur = cur["x"]
        o["quality"]["copilot"] = deep
        self.assertEqual(_codes(schema.validate_team_bundle(o)), ["schema"])

    def test_errors_carry_no_values(self):
        o = _bundle(self_label="비밀값ZQ7\u0007")
        for e in schema.validate_team_bundle(o):
            self.assertNotIn("ZQ7", e.msg + e.path)


class TestGuards(unittest.TestCase):
    def test_bytes_guard(self):
        at = "@"
        cases = {"email": f'"x":"a{at}team.example.com"', "who_key": '"w0123456789abcdef"',
                 "pc_id": '"pc_0123456789abcdef"', "guid": '"0123ABCD-0123-0123-0123-0123456789AB"',
                 "url": '"htt' + 'p://x"'}
        for name, frag in cases.items():
            self.assertEqual(schema.bytes_guard_hits(frag.encode()), [name], name)
        self.assertEqual(schema.bytes_guard_hits(B.canon(_bundle())), [])

    def test_active_spans(self):
        d = [date(2026, 7, x) for x in (1, 2, 4, 8, 9, 13)]
        self.assertEqual(schema.active_spans(d, 2), [(date(2026, 7, 1), date(2026, 7, 4)),
                                                     (date(2026, 7, 8), date(2026, 7, 9)),
                                                     (date(2026, 7, 13), date(2026, 7, 13))])
        self.assertEqual(schema.active_spans(d, 0)[0], (date(2026, 7, 1), date(2026, 7, 2)))
        self.assertEqual(schema.active_spans(list(reversed(d)), 2), schema.active_spans(d, 2))   # 결정적

    def test_judge_hello_table(self):
        ok = {"app": schema.APP_ID, "proto": "lm27-team/1", "accepts": {"team_bundle": {"1": 0}}}
        self.assertEqual(schema.judge_hello(200, ok), "ok")
        self.assertEqual(schema.judge_hello(200, dict(ok, accepts={"team_bundle": {"2": 0}})), "wrong_major")
        self.assertEqual(schema.judge_hello(200, {"app": "LM28-team"}), "other_lm")
        self.assertEqual(schema.judge_hello(200, {"app": "Other"}), "other_app")
        self.assertEqual(schema.judge_hello(404, None, whoami={"root": 1}), "lm24")
        self.assertEqual(schema.judge_hello(404, None, team={"members": [], "agg_note": ""}), "lm24")
        self.assertEqual(schema.judge_hello(404, None), "other_app")
        self.assertEqual(schema.judge_hello(500, None), "http_error")
        self.assertEqual(schema.judge_hello(None, error="timeout"), "timeout")
        self.assertEqual(schema.judge_hello(None, error="refused"), "refused")
        self.assertEqual(schema.judge_hello(200, {"app": "x"}, proxy=True), "proxy")
        self.assertEqual(set(schema.HELLO_REASON.values()) <= {"R-TEAM-TIMEOUT", "R-TEAM-REFUSED", "R-TEAM-DNS",
                                                                "R-TEAM-PROXY", "R-TEAM-LM24", "R-TEAM-OTHERAPP",
                                                                "R-TEAM-VERSION"}, True)

    def test_team_text(self):
        """TAB §2.4 team_text — NFKC·제어 문자 제거·자르기 + P 검사(가짜) + 로컬 사전."""
        class Ctx:
            gctx = None
            audit = {}
            audit_fields = {}

            @staticmethod
            def local_dict_hit(s):
                return "로컬이름" in s
        with fake_privacy(bad_words=("BAD",)):
            c = Ctx()
            self.assertEqual(schema.team_text("  전원부\u200b   검증\u0007 ", 40, "units.title", c), "전원부 검증")
            self.assertEqual(schema.team_text("가" * 50, 40, "units.title", c), "가" * 40)
            self.assertIsNone(schema.team_text("BAD 제목", 40, "units.title", c))
            self.assertIsNone(schema.team_text("로컬이름 회의", 40, "units.title", c))
            self.assertEqual(schema.team_text("", 40, "units.title", c), "")
            self.assertEqual(c.audit["team_text_rejected"], 2)
            self.assertEqual(c.audit_fields["units.title"], 2)

    def test_privacy_payload_check_passes_spec(self):
        with fake_privacy() as m:
            chk = schema.privacy_payload_check({})
            o = _bundle(self_label="BAD")
            self.assertEqual(chk(o), [("person.self_label", "label:not_clean")])
            self.assertEqual(m.calls["payload"], 1)

    def test_deterministic_bytes(self):
        """U02 성질: 같은 입력(built_at 고정) → 같은 정규 바이트."""
        a, b = _bundle(), _bundle()
        self.assertEqual(B.canon(a), B.canon(b))
        self.assertEqual(B.canon(copy.deepcopy(a)), B.canon(a))
