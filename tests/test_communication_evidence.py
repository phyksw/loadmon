"""Saved communication evidence and downstream restraint; synthetic TEMP only."""
import contextlib
import copy
import csv
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
from types import ModuleType
import unittest
from unittest import mock

APP = Path(__file__).resolve().parents[1] / "LoadMonitor25"
with mock.patch.object(sys, "path", [str(APP / "core"), *sys.path]):
    SPEC = importlib.util.spec_from_file_location("synthetic_communication_evidence", APP / "core/communication_evidence.py")
    E = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(E)


class CommunicationEvidenceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="lm25-communication-evidence-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.period = ("2026-01-01", "2026-01-31")

    def csv(self, relative, rows, encoding="utf-8-sig"):
        path = self.root / "data" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        fields = list(dict.fromkeys(k for row in rows for k in row))
        with path.open("w", encoding=encoding, newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        return path

    def report(self, config=None):
        return E.build_report(self.root, *self.period, config)

    def test_seven_titles_zero_mail_never_implies_sufficiency_or_zero_work(self):
        self.csv("m365/teams_window.csv", [{"time": f"2026-01-0{i + 1} 09:00", "summary": "SENSITIVE_TITLE",
                                         "chat": "SENSITIVE_ROOM", "source_id": str(i)} for i in range(7)])
        result = self.report()
        self.assertEqual(result["status"], "limited")
        self.assertEqual(result["families"]["teams"]["unique_rows"], 7)
        self.assertEqual(result["families"]["teams"]["context_rows"], 0)
        self.assertEqual(result["families"]["mail"]["unique_rows"], 0)
        self.assertIsNone(result["families"]["teams"]["source_coverage_ratio"])
        self.assertEqual(result["mm_effect"], "none")
        self.assertNotIn("SENSITIVE", json.dumps(result))

    def test_counts_scope_period_and_cross_pc_identity_are_separate(self):
        row = {"time": "2026-01-05 09:00", "box": "sent", "subject": "SENSITIVE_TITLE", "source_id": "id-1",
               "conversation_id": "SENSITIVE_THREAD", "account": "SENSITIVE_ACCOUNT", "source_kind": "outlook_com"}
        self.csv("outlook/mail.csv", [row, dict(row, source_id="outside", time="2025-12-31 09:00"),
                                     dict(row, source_id="bad-date", time="bad")])
        self.csv("추가PC/PC-B/outlook/mail.csv", [dict(row, context_excerpt="SENSITIVE_BODY"),
                                                  dict(row, account="different-account")])
        family = self.report()["families"]["mail"]
        self.assertEqual((family["raw_rows"], family["in_period_rows"], family["unique_rows"]), (5, 3, 2))
        self.assertEqual((family["context_rows"], family["context_ratio"], family["conversation_count"]), (1, 0.5, 2))
        self.assertEqual(family["unknown_date_rows"], 1)
        self.assertEqual(family["scope_status"], "unknown")
        self.assertNotIn("SENSITIVE", json.dumps(family))

    def test_legacy_encodings_long_body_and_filtered_body(self):
        for encoding in ("cp949", "utf-16"):
            with self.subTest(encoding=encoding):
                self.csv("outlook/mail.csv", [{"time": "2026-01-05 09:00", "subject": "설계 검토",
                                             "context_excerpt": "긴 원문 " * 30000}], encoding)
                family = self.report()["families"]["mail"]
                self.assertEqual((family["unique_rows"], family["context_rows"], family["unreadable_files"]), (1, 1, 0))
        self.csv("outlook/mail.csv", [{"time": "2026-01-05 09:00", "subject": "Design", "context_excerpt": "private body"}])
        family = self.report({"excludePathKeywords": ["private"]})["families"]["mail"]
        self.assertEqual((family["unique_rows"], family["context_rows"], family["context_filtered_rows"]), (1, 0, 1))

    def test_fallback_identity_does_not_merge_different_senders_or_sources(self):
        row = {"time": "2026-01-05 09:00", "box": "inbox", "subject": "Same subject", "sender": "Person A"}
        self.csv("outlook/mail.csv", [row, dict(row, sender="Person B"), dict(row, source_kind="outlook_web")])
        self.assertEqual(self.report()["families"]["mail"]["unique_rows"], 3)

    def test_unreadable_file_is_reported_and_not_complete_zero(self):
        path = self.root / "data/outlook/mail.csv"
        path.parent.mkdir(parents=True)
        path.write_text("time,subject\n2026-01-05,one,extra\n", encoding="utf-8")
        family = self.report()["families"]["mail"]
        self.assertEqual(family["unreadable_files"], 1)
        self.assertNotEqual(family["scope_status"], "scoped_complete")

    def test_import_completion_and_other_period_status_do_not_prove_full_scope(self):
        directory = self.root / "data/collection_status"
        directory.mkdir(parents=True)
        status = {"source": "communication_import", "requested_from": self.period[0], "requested_to": self.period[1],
                  "status": "complete", "scope": "selected files only"}
        (directory / "communication_import.json").write_text(json.dumps(status), encoding="utf-8")
        (directory / "outlook_com.json").write_text(json.dumps({**status, "source": "outlook_com", "requested_from": "2025-01-01"}), encoding="utf-8")
        self.assertEqual(self.report()["families"]["mail"]["scope_status"], "partial")
        self.assertEqual(self.report()["families"]["teams"]["source_statuses"], [])
        report = E.write_report(self.root, *self.period)
        self.assertEqual(json.loads((self.root / "report/communication_evidence_20260101-20260131.json").read_text("utf-8")), report)
        with self.assertRaises(ValueError):
            E.write_report(self.root, "2026-02-01", "2026-02-28", report=report)

    def test_unit_readiness_uses_context_not_count_and_does_not_promote_ai_report(self):
        titles = [{"source": "팀즈(발신)", "text": "Acknowledged"} for _ in range(100)]
        self.assertFalse(E.unit_readiness(titles)["allows_interpretation"])
        direct = dict(titles[0], context_excerpt="Compare two design revisions", source_kind="teams_web")
        self.assertTrue(E.unit_readiness([direct])["allows_interpretation"])
        self.assertFalse(E.unit_readiness([dict(direct, context_filtered="true")])["allows_interpretation"])
        self.assertFalse(E.unit_readiness([dict(direct, source_kind="teams_copilot")])["allows_interpretation"])
        self.assertTrue(E.unit_readiness([{"source": "커밋", "text": "Correct parser boundary"}])["allows_interpretation"])
        self.assertTrue(E.unit_readiness([{"source": "수동기록", "text": "Review the assembled board"}])["allows_interpretation"])
        self.assertFalse(E.unit_readiness([direct])["fact_verified"])
        self.assertNotIn("Compare", E.evidence_line(dict(direct, context_filtered="true")))
        excerpt = E.evidence_line(dict(direct, context_excerpt="BEGIN " + "x" * 600 + " MIDDLE " + "y" * 600 + " DECISION_END"), 280)
        self.assertLessEqual(len(excerpt), 280)
        self.assertIn("BEGIN", excerpt)
        self.assertIn("DECISION_END", excerpt)

    def fixture(self):
        from test_workflow_integrity import WorkflowIntegrityTests
        case = WorkflowIntegrityTests()
        case.setUp()
        self.addCleanup(case.doCleanups)
        return case

    def test_flow_and_agentic_receive_bounded_context_without_fact_verification(self):
        case = self.fixture()
        rows = [dict(case.rows[0], _mm=0.2)]
        signals = [{"source": "메일(발신)", "text": "Design discussion", "time": "2026-01-05 09:00",
                    "model": "Alpha", "detail": "design review", "context_excerpt": "DECISION_CONTEXT " * 1000}]
        case.details.read_rows = lambda *a, **k: (copy.deepcopy(rows), "rows.csv")
        case.details.read_signals = lambda *a: copy.deepcopy(signals)
        mats, _, error = case.flow.gather(str(case.root / "report"), "20260101-20260131")
        self.assertFalse(error)
        self.assertEqual(len(mats), 1)  # A single observed step is allowed.
        prompt = case.flow.build_prompt(mats)
        self.assertIn("DECISION_CONTEXT", prompt)
        self.assertLess(len(prompt), case.flow.PROMPT_BUDGET)
        reply = case.flow_reply(mats[0])
        reply["steps"] = reply["steps"][:1]
        case.flow.validate_flow_batch({"processed_ids": [mats[0]["unit_id"]], "flows": [reply]}, mats, {})
        got = case.flow.sanitize_flows([reply], {mats[0]["key"]: mats[0]})[0]
        self.assertEqual(got["steps"][0]["evidence_status"], "source_linked")
        self.assertFalse(got["fact_verified"])
        case.agentic.attach_evidence(rows, signals)
        self.assertIn("DECISION_CONTEXT", case.agentic.ag_prompt(list(case.tasks.values()), rows))
        candidate = {"match": [{"task": "T-1", "fit": 80, "work_ids": [case.agentic.row_sig(rows[0])]}]}
        case.agentic.recalc_mm(candidate, rows)
        self.assertTrue(candidate["match"][0]["kpi_eligible"])
        self.assertFalse(candidate["match"][0]["fact_verified"])
        self.assertEqual(candidate["match"][0]["related_work_mm"], 0.2)
        case.agentic.attach_evidence(rows, [dict(signals[0], context_excerpt="")])
        case.agentic.recalc_mm(candidate, rows)
        self.assertFalse(candidate["match"][0]["kpi_eligible"])
        self.assertEqual(candidate["match"][0]["related_work_mm"], 0.2)

    def test_flow_main_defers_titles_without_ai_retry_and_keeps_file_work(self):
        case = self.fixture()
        mats = [case.mat(), case.mat(project="Beta")]
        for signal in mats[0]["evidence_by_id"].values():
            signal.update(source="팀즈(수신)", text="Acknowledged", context_excerpt="")
        case.flow.gather = lambda *a: (copy.deepcopy(mats), "판정", "")
        case.flow.load_l1_pin = lambda *a: {}
        case.flow._refine_orig = lambda *a: {}
        case.flow._seed_from_refine = lambda *a: 0
        case.details.read_rows = lambda *a, **k: (copy.deepcopy(case.rows), "rows.csv")
        case.details.read_signals = lambda *a: []
        case.details.project_merge_map = lambda *a, **k: ({}, 0, 0, {})
        case.details.detail_merge_map = lambda *a, **k: ({}, 0, 0)
        calls = []

        def answer(sender, prompt, *a, **k):
            calls.append(prompt)
            self.assertNotIn(mats[0]["unit_id"], prompt)
            return {"processed_ids": [mats[1]["unit_id"]], "flows": [case.flow_reply(mats[1])]}, {"ok": True, "model": "synthetic"}

        case.details.ask_json = answer
        judge, projmap = ModuleType("judge"), ModuleType("projmap")
        judge.copilot_send, judge.chat_turns = lambda *a, **k: None, lambda: 0
        projmap.load_user_projects = lambda *a: []
        with mock.patch.dict(sys.modules, {"judge": judge, "projmap": projmap}), \
                mock.patch.object(sys, "argv", ["flow.py", "--from", *self.period[:1], "--to", self.period[1], "--no-merge"]), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(case.flow.main(), 0)
        result = json.loads((case.root / "report/workflow_20260101-20260131.json").read_text("utf-8"))
        self.assertEqual(len(calls), 1)
        self.assertEqual(result["evidence_limited_count"], 1)
        self.assertEqual(result["missing_count"], 0)
        self.assertEqual(result["flows"][0]["mm"]["mm"], 0.2)
        self.assertFalse(result["review_flows"][0]["kpi_eligible"])

    def test_flow_step_must_use_its_own_context_not_another_message_in_the_unit(self):
        case = self.fixture()
        mat = case.mat()
        first = next(iter(mat["evidence_by_id"]))
        mat["evidence_by_id"][first].update(source="팀즈(발신)", context_excerpt="Discussed the design revision and requested a revised drawing")
        mat["evidence_by_id"]["sig_title_only"] = {"source": "팀즈(수신)", "text": "Acknowledged"}
        got = case.flow.sanitize_flows([case.flow_reply(mat, evidence_ids=["sig_title_only"])], {mat["key"]: mat})[0]
        self.assertFalse(got["kpi_eligible"])
        self.assertTrue(got["insufficient_evidence"])
        self.assertTrue(got["steps"][0]["needs_review"])
        self.assertEqual(got["steps"][0]["evidence_status"], "source_linked")

    def test_agentic_refined_names_keep_original_work_id_lineage(self):
        case = self.fixture()
        original = case.rows[0]
        refined = dict(original, **{"Level 2": "Renamed project", "Level 3": "Merged design responsibility",
                                   "source_work_mm": json.dumps({case.details.stable_work_id(original): 0.2})})
        signals = [{"model": "Alpha", "detail": "design review", "source": "메일(발신)", "text": "Review",
                    "context_excerpt": "RIGHT_CONTEXT requested a drawing revision"},
                   {"model": "Beta", "detail": "design review", "source": "메일(발신)", "text": "Review",
                    "context_excerpt": "WRONG_CONTEXT belongs to another project"}]
        case.agentic.attach_evidence([refined], signals, case.rows)
        self.assertTrue(refined["_evidence_readiness"]["allows_interpretation"])
        self.assertIn("RIGHT_CONTEXT", refined["_evidence_excerpt"])
        self.assertNotIn("WRONG_CONTEXT", refined["_evidence_excerpt"])
        refined["source_work_mm"] = json.dumps({"work_missing": 0.2})
        case.agentic.attach_evidence([refined], signals, case.rows)
        self.assertFalse(refined["_evidence_readiness"]["allows_interpretation"])

    def test_gather_keeps_rich_context_between_time_spread_positions(self):
        case = self.fixture()
        rows = [dict(case.rows[0], _mm=0.2)]
        signals = [{"source": "팀즈(발신)", "text": "Acknowledged", "time": f"2026-01-05 09:{i:02}",
                    "model": "Alpha", "detail": "design review"} for i in range(40)]
        sampled = case.flow._spread(signals, case.flow.SAMPLE_N)
        rich = next(s for s in signals if s not in sampled)
        rich["context_excerpt"] = "ONLY_RICH_CONTEXT between evenly spread positions"
        case.details.read_rows = lambda *a, **k: (copy.deepcopy(rows), "rows.csv")
        case.details.read_signals = lambda *a: copy.deepcopy(signals)
        mats, _, error = case.flow.gather(str(case.root / "report"), "20260101-20260131")
        self.assertFalse(error)
        self.assertIn("ONLY_RICH_CONTEXT", case.flow.build_prompt(mats))
        self.assertEqual(len(mats[0]["evidence"]), case.flow.SAMPLE_N)


if __name__ == "__main__":
    unittest.main()
