"""Identity, evidence and completion contracts, using copied code and TEMP data only."""
import ast
from collections import Counter
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from types import ModuleType
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1] / "LoadMonitor25"
TAG = "20260101-20260131"


def module(name, path, dependencies=None):
    result = ModuleType(name)
    result.__file__ = str(path)
    paths = list(sys.path)
    try:
        with mock.patch.dict(sys.modules, dependencies or {}):
            exec(compile(path.read_text(encoding="utf-8-sig"), str(path), "exec"), result.__dict__)
    finally:
        sys.path[:] = paths
    return result


class WorkflowIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="lm25-workflow-integrity-"))
        for directory in ("core", "config", "report"):
            (self.root / directory).mkdir()
        for name in ("agentic.py", "flow.py", "core/details.py"):
            (self.root / name).write_bytes((ROOT / name).read_bytes())
        self.details = module("synthetic_details", self.root / "core/details.py")
        progress = ModuleType("progress")
        progress.progress = lambda *args, **kwargs: None
        dependencies = {"details": self.details, "progress": progress}
        self.agentic = module("synthetic_agentic", self.root / "agentic.py", dependencies)
        self.flow = module("synthetic_flow", self.root / "flow.py", dependencies)
        self.rows = [{"Level 2": "Alpha", "Level 3": "design review", "유형": "개발", "mm": "0.2", "상세설명": "First"},
                     {"Level 2": "Beta", "Level 3": "design review", "유형": "개발", "mm": "0.8", "상세설명": "Second"}]
        self.tasks = {"T-1": {"id": "T-1", "name": "Synthetic task"}}
        (self.root / "config/agentic_tasks.json").write_text(json.dumps({"tasks": list(self.tasks.values())}), encoding="utf-8")

    def reply(self, **updates):
        return {"match": [], "new": [], "misassigned": [],
                "processed_ids": [self.agentic.row_sig(r) for r in self.rows], **updates}

    def mat(self, project="Alpha", detail="design review", tag=TAG):
        signal = {"time": "2026-01-05 09:00", "source": "파일", "text": "Actual synthetic review",
                  "model": project, "detail": detail}
        eid = self.details.stable_signal_id(signal, tag)
        return {"key": f"{project} / {detail}", "model": project, "detail": detail, "signals": 3, "mm": 0.2,
                "unit_id": self.details.stable_id("unit", tag, project, detail),
                "source_work_ids": [self.details.stable_work_id({"Level 2": project, "Level 3": detail, "유형": "개발"})],
                "evidence_by_id": {eid: signal}, "evidence": [f"- [{eid}] Actual synthetic review"]}

    def flow_reply(self, mat, **step_updates):
        step = {"name": "Review", "desc": "Inspect the artifact", "agent": "상", "agent_how": "Draft checks",
                "evidence_ids": list(mat["evidence_by_id"]), "evidence": "Invented unsupported quotation", **step_updates}
        return {"unit_id": mat["unit_id"], "key": mat["key"], "steps": [copy.deepcopy(step) for _ in range(3)]}

    def test_stable_ids_are_scope_sensitive_but_not_mm_or_order_sensitive(self):
        a, b = [self.agentic.row_sig(r) for r in self.rows]
        self.assertNotEqual(a, b)
        self.assertEqual(a, self.agentic.row_sig(dict(self.rows[0], mm="0.200001", 상세설명="Changed")))
        self.assertNotEqual(a, self.agentic.row_sig(dict(self.rows[0], **{"Level 3": "renamed"})))
        self.assertNotEqual(a, self.agentic.row_sig(dict(self.rows[0], 유형="협업")))
        self.assertNotEqual(a, self.agentic.row_sig(dict(self.rows[0], **{"Level 2": "Ａｌｐｈａ"})))

    def test_same_name_legacy_is_ambiguous_and_explicit_id_only_claims_its_project(self):
        for work in ("design review", "design", "review"):
            out = {"match": [{"task": "T-1", "fit": 80, "work": [work]}]}
            self.agentic.recalc_mm(out, self.rows)
            self.assertEqual(out["match"][0]["load_mm"], 0)
        out = {"match": [{"task": "T-1", "fit": 80, "work": ["design review"],
                           "work_ids": [self.agentic.row_sig(self.rows[0])]}]}
        self.agentic.recalc_mm(out, self.rows)
        self.assertEqual(out["match"][0]["load_mm"], 0.2)
        out["match"][0]["work_ids"] = ["work_absent"]
        self.agentic.recalc_mm(out, self.rows)
        self.assertEqual(out["match"][0]["load_mm"], 0)

    def test_qualified_legacy_match_is_unique_and_alias_does_not_change_id(self):
        out = {"match": [{"task": "T-1", "fit": 50, "work": ["Alpha / design review"]}]}
        self.agentic.recalc_mm(out, self.rows)
        self.assertEqual(out["match"][0]["load_mm"], 0.2)
        wid = self.agentic.row_sig(self.rows[0])
        out["match"][0]["work_ids"] = [wid]
        self.agentic.recalc_mm(out, self.rows, {("Alpha", "design review"): "design checks"})
        self.assertEqual(out["match"][0]["resolved_work_ids"], [wid])

    def test_match_and_new_candidates_share_allocation_but_never_claim_savings(self):
        wid = self.agentic.row_sig(self.rows[0])
        out = {"match": [{"task": "T-1", "fit": 80, "work_ids": [wid]}],
               "new": [{"name": "New A", "work_ids": [wid]}, {"name": "New B", "work_ids": [wid]}]}
        self.agentic.recalc_mm(out, self.rows)
        candidates = out["match"] + out["new"]
        self.assertAlmostEqual(sum(c["allocated_candidate_mm"] for c in candidates), 0.2, places=5)
        self.assertEqual(out["unique_related_work_mm"], 0.2)
        self.assertTrue(all(c["related_work_mm"] == 0.2 and c["expected_saved_mm"] is None for c in candidates))
        self.assertEqual(len({c["candidate_id"] for c in candidates}), 3)

    def test_agentic_requires_complete_explicit_ack_and_valid_references(self):
        good = self.reply()
        self.assertEqual(self.agentic.validate_response(good, self.rows, self.tasks, {}), good)
        wid = self.agentic.row_sig(self.rows[0])
        item = {"task": "T-1", "fit": 80, "work_ids": [wid], "reason": "Synthetic reason"}
        valid = self.agentic.validate_response(self.reply(match=[item]), self.rows, self.tasks, {})
        self.assertEqual(valid["match"][0]["work"], ["Alpha / design review"])
        for bad in (self.reply(processed_ids=[wid]), self.reply(match=[123]),
                    self.reply(match=[dict(item, task="UNKNOWN")]), self.reply(match=[dict(item, fit=True)]),
                    self.reply(match=[dict(item, fit=0.5)]),
                    self.reply(match=[dict(item, fit=float("nan"))]), self.reply(match=[dict(item, work_ids=["missing"])])):
            with self.assertRaises(ValueError):
                self.agentic.validate_response(bad, self.rows, self.tasks, {})
        for info in ({"how": "salvaged"}, {"cut": True}):
            with self.assertRaises(ValueError):
                self.agentic.validate_response(good, self.rows, self.tasks, info)

    def test_agentic_main_never_marks_salvaged_batch_done_and_keeps_prior_file(self):
        dst = self.root / f"report/agentic_{TAG}.json"
        old = b'{"previous_valid_result":true}'
        dst.write_bytes(old)
        self.details.read_rows = lambda *args, **kwargs: (copy.deepcopy(self.rows), f"mm_rows_{TAG}.csv")
        self.details.read_signals = lambda *args: []
        self.details.load_detail_aliases = lambda: {}
        judge = ModuleType("judge")
        judge.copilot_send = lambda *args, **kwargs: None
        judge.chat_turns = lambda: 0
        self.details.ask_json = lambda *args, **kwargs: (self.reply(), {"ok": True, "how": "salvaged", "model": "synthetic"})
        with mock.patch.dict(sys.modules, {"judge": judge}), mock.patch.object(sys, "argv", ["agentic.py", "--from", "2026-01-01", "--to", "2026-01-31"]), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.agentic.main(), 1)
        self.assertEqual(dst.read_bytes(), old)
        self.details.ask_json = lambda *args, **kwargs: (self.reply(), {"ok": True, "how": "json", "model": "synthetic"})
        with mock.patch.dict(sys.modules, {"judge": judge}), mock.patch.object(sys, "argv", ["agentic.py", "--from", "2026-01-01", "--to", "2026-01-31"]), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.agentic.main(), 0)
        saved = json.loads(dst.read_text(encoding="utf-8"))
        self.assertEqual(saved["rows_analyzed"], 2)
        self.assertFalse(saved["partial"])
        self.assertEqual(saved["processed_ids"], sorted(self.reply()["processed_ids"]))

    def test_input_fingerprint_changes_for_content_settings_tasks_and_sources(self):
        payload = {"rows": self.rows, "tasks": list(self.tasks.values())}
        before = self.details.analysis_fingerprint(str(self.root), TAG, payload)
        self.assertTrue(before)
        self.assertEqual(before, self.details.analysis_fingerprint(str(self.root), TAG, payload))
        for relative in (f"report/signals_{TAG}.csv", f"report/evidence_{TAG}.md", "config/detail_aliases.json",
                         "config/agentic_tasks.json", "flow.py"):
            path = self.root / relative
            previous = path.read_bytes() if path.exists() else None
            stamp = path.stat().st_mtime_ns if path.exists() else None
            path.write_bytes((previous or b"") + b"synthetic content change")
            if stamp is not None:
                os.utime(path, ns=(stamp, stamp))
            self.assertNotEqual(before, self.details.analysis_fingerprint(str(self.root), TAG, payload), relative)
            if previous is None:
                path.unlink()
            else:
                path.write_bytes(previous)
        altered = copy.deepcopy(payload)
        altered["rows"][0]["상세설명"] = "Different evidence"
        self.assertNotEqual(before, self.details.analysis_fingerprint(str(self.root), TAG, altered))
        (self.root / f"report/evidence_{TAG}.md").write_text("<missing>", encoding="utf-8")
        self.assertNotEqual(before, self.details.analysis_fingerprint(str(self.root), TAG, payload))

    def test_agentic_main_resumes_only_matching_input_content(self):
        self.details.read_rows = lambda *args, **kwargs: (copy.deepcopy(self.rows), f"mm_rows_{TAG}.csv")
        self.details.read_signals = lambda *args: []
        self.details.load_detail_aliases = lambda: {}
        self.agentic.split_rows = lambda tasks, rows, **kwargs: [([r], 1) for r in rows]
        seen = []

        def answer(_sender, prompt, *args, **kwargs):
            ids = re.findall(r"^· \[(work_[a-f0-9]+)\]", prompt, re.M)
            seen.extend(ids)
            return self.reply(processed_ids=ids), {"ok": True, "how": "json", "model": "synthetic"}

        self.details.ask_json = answer
        judge = ModuleType("judge")
        judge.copilot_send, judge.chat_turns = lambda *args, **kwargs: None, lambda: 0
        argv = ["agentic.py", "--from", "2026-01-01", "--to", "2026-01-31", "--max-chunks", "1"]
        dst = self.root / f"report/agentic_{TAG}.json"
        with mock.patch.dict(sys.modules, {"judge": judge}), mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.agentic.main(), 0)
            partial = dst.read_bytes()
            self.assertTrue(json.loads(partial)["partial"])
            seen.clear()
            self.assertEqual(self.agentic.main(), 0)
            self.assertEqual(seen, [self.agentic.row_sig(self.rows[1])])
            dst.write_bytes(partial)
            (self.root / f"report/evidence_{TAG}.md").write_text("Changed underlying evidence", encoding="utf-8")
            seen.clear()
            self.assertEqual(self.agentic.main(), 0)
            self.assertEqual(seen, [self.agentic.row_sig(self.rows[0])])

    def test_flow_main_truncation_is_partial_and_evidence_changes_invalidate_resume(self):
        mats = [self.mat(), self.mat(project="Beta")]
        self.flow.gather = lambda *args: (copy.deepcopy(mats), "판정", "")
        self.flow.load_l1_pin = lambda *args: {}
        self.flow._refine_orig = lambda *args: {}
        self.flow._seed_from_refine = lambda *args: 0
        self.details.read_rows = lambda *args, **kwargs: (copy.deepcopy(self.rows), f"mm_rows_{TAG}.csv")
        self.details.read_signals = lambda *args: []
        self.details.project_merge_map = lambda *args, **kwargs: ({}, 0, 0, {})
        self.details.detail_merge_map = lambda *args, **kwargs: ({}, 0, 0)
        state = {"first": True}
        seen = []

        def answer(_sender, prompt, *args, **kwargs):
            ids = re.findall(r"\[unit_id=(unit_[a-f0-9]+)\]", prompt)
            seen.append(ids)
            selected = [m for m in mats if m["unit_id"] in ids]
            obj = {"processed_ids": ids, "flows": [self.flow_reply(m) for m in selected]}
            if state["first"] and len(ids) > 1:
                return obj, {"ok": True, "how": "salvaged"}
            if state["first"] and mats[1]["unit_id"] in ids:
                return {}, {"ok": False, "fatal": True, "error": "synthetic stop"}
            return obj, {"ok": True, "how": "json", "model": "synthetic"}

        self.details.ask_json = answer
        judge = ModuleType("judge")
        judge.copilot_send, judge.chat_turns = lambda *args, **kwargs: None, lambda: 0
        projmap = ModuleType("projmap")
        projmap.load_user_projects = lambda *_: []
        argv = ["flow.py", "--from", "2026-01-01", "--to", "2026-01-31", "--no-merge"]
        dst = self.root / f"report/workflow_{TAG}.json"
        with mock.patch.dict(sys.modules, {"judge": judge, "projmap": projmap}), mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.flow.main(), 0)
            partial = dst.read_bytes()
            self.assertTrue(json.loads(partial)["partial"])
            self.assertEqual(json.loads(partial)["processed_ids"], [mats[0]["unit_id"]])
            state["first"] = False
            seen.clear()
            self.assertEqual(self.flow.main(), 0)
            self.assertEqual(seen, [[mats[1]["unit_id"]]])
            dst.write_bytes(partial)
            (self.root / f"report/evidence_{TAG}.md").write_text("Changed evidence", encoding="utf-8")
            seen.clear()
            self.assertEqual(self.flow.main(), 0)
            self.assertEqual(set(seen[0]), {m["unit_id"] for m in mats})

    def test_flow_evidence_is_resolved_from_same_period_and_unit_not_ai_quote(self):
        mat = self.mat()
        good = self.flow.sanitize_flows([self.flow_reply(mat)], {mat["key"]: mat})[0]
        self.assertFalse(good["needs_review"])
        self.assertEqual(good["steps"][0]["evidence"], "Actual synthetic review")
        for wrong in ("sig_missing", next(iter(self.mat(project="Beta")["evidence_by_id"])),
                      next(iter(self.mat(detail="Other work")["evidence_by_id"])),
                      next(iter(self.mat(tag="20260201-20260228")["evidence_by_id"]))):
            got = self.flow.sanitize_flows([self.flow_reply(mat, evidence_ids=[wrong])], {mat["key"]: mat})[0]
            self.assertTrue(got["needs_review"])
            self.assertFalse(got["kpi_eligible"])
            self.assertEqual(got["steps"][0]["agent"], "")
        bad_enum = self.flow.sanitize_flows([self.flow_reply(mat, agent="UNSURE")], {mat["key"]: mat})[0]
        self.assertTrue(bad_enum["needs_review"])
        self.assertEqual(bad_enum["steps"][0]["agent"], "")

    def test_flow_batch_needs_every_unit_and_never_accepts_truncated_branches(self):
        mat = self.mat()
        obj = {"processed_ids": [mat["unit_id"]], "flows": [self.flow_reply(mat)]}
        self.flow.validate_flow_batch(obj, [mat], {})
        for bad, info in ((obj, {"how": "salvaged"}), (obj, {"cut": True}),
                          (dict(obj, processed_ids=[]), {}), (dict(obj, flows=[]), {})):
            with self.assertRaises(ValueError):
                self.flow.validate_flow_batch(bad, [mat], info)

    def test_flow_gather_and_dedupe_keep_explicitly_distinct_project_spellings(self):
        rows = [dict(self.rows[0], **{"Level 2": "Alpha-Beta", "_mm": 0.2}),
                dict(self.rows[1], **{"Level 2": "Alpha Beta", "_mm": 0.8})]
        signals = [{"model": row["Level 2"], "detail": row["Level 3"], "source": "파일",
                    "time": f"2026-01-05 09:0{i}", "text": f"Synthetic artifact {i}"}
                   for row in rows for i in range(3)]
        self.details.read_rows = lambda *args, **kwargs: (copy.deepcopy(rows), "mm_rows.csv")
        self.details.read_signals = lambda *args: copy.deepcopy(signals)
        mats, _, error = self.flow.gather(str(self.root / "report"), TAG)
        self.assertFalse(error)
        self.assertEqual({m["model"]: m["mm"] for m in mats}, {"Alpha-Beta": 0.2, "Alpha Beta": 0.8})
        keys = {m["key"]: m for m in mats}
        flows = self.flow.sanitize_flows([self.flow_reply(m) for m in mats], keys)
        kept, _ = self.flow._dedupe_flows(flows, "과제/담당업무")
        self.assertEqual(len(kept), 2)
        self.assertEqual(len({f["project_id"] for f in kept}), 2)

    def test_real_gather_preserves_source_ids_through_aliases_and_report_current_rows(self):
        for name in ("aggregate.py", "team_report.py", "core/bundles.py"):
            (self.root / name).write_bytes((ROOT / name).read_bytes())
        bundles = module("synthetic_bundles", self.root / "core/bundles.py")
        aggregate = module("synthetic_aggregate", self.root / "aggregate.py",
                           {"details": self.details, "bundles": bundles})
        report = module("synthetic_team_report", self.root / "team_report.py")
        report._agg = lambda: aggregate
        rows = [dict(r, _mm=float(r["mm"])) for r in self.rows]
        source_ids = sorted(self.details.stable_work_id(row) for row in rows)
        signals = [{"model": row["Level 2"], "detail": row["Level 3"], "source": "파일",
                    "time": f"2026-01-05 09:0{i}", "text": f"Synthetic artifact {i}"}
                   for row in rows for i in range(3)]
        self.details.read_rows = lambda *args, **kwargs: (copy.deepcopy(rows), "mm_rows.csv")
        self.details.read_signals = lambda *args: copy.deepcopy(signals)
        for unit in ("과제/담당업무", "과제"):
            with self.subTest(unit=unit), mock.patch.object(self.flow, "workflow_unit", return_value=unit):
                mats, _, error = self.flow.gather(str(self.root / "report"), TAG,
                                                pmap={"Alpha": "Beta"},
                                                amap={("Beta", "design review"): "design checks"})
                self.assertFalse(error)
                self.assertEqual(len(mats), 1)
                material = mats[0]
                self.assertEqual(material["source_work_ids"], source_ids)
                self.assertEqual(material["mm"], 1.0)
                raw = self.flow_reply(material)
                raw["source_work_ids"] = ["work_invented"]  # AI cannot replace source lineage.
                flow = self.flow.sanitize_flows([raw], {material["key"]: material})[0]
                self.assertEqual(flow["source_work_ids"], source_ids)
                normalized = report.norm_flow(flow)
                self.assertEqual(report._flow_mm(normalized, rows), 1.0)
                changed = [dict(rows[0], _mm=0.1), dict(rows[1], _mm=0.4)]
                self.assertEqual(report._flow_mm(normalized, changed), 0.5)
                self.assertIsNone(report._flow_mm(normalized, rows[:1]))
                self.assertIsNone(report._flow_mm(normalized, rows + [dict(rows[0])]))
                if unit == "과제/담당업무":
                    item = {"owner": "Synthetic", "fl": normalized}
                    clusters, pending = report.cluster_flows([item], str(self.root), {"Synthetic": rows})
                    self.assertFalse(pending)
                    self.assertEqual(clusters[0]["related_work_mm"], 1.0)
                    clusters, pending = report.cluster_flows([item], str(self.root), {"Synthetic": rows[:1]})
                    self.assertFalse(clusters)
                    self.assertIn("KPI", pending[0]["review_reason"])

    def test_cached_alias_constraints_apply_to_direct_indirect_invisible_and_oversized_groups(self):
        d = self.details
        ctx = {"pinned": set(), "l3": {}, "span": {}}
        for mapping in ({"Alpha": "Beta"}, {"Alpha": "Hidden", "Beta": "Hidden"},
                        {"Alpha": "Hidden", "Hidden": "Beta"}):
            result, rejected = d.validate_project_aliases(mapping, {d._pair2("Alpha", "Beta")}, ctx)
            self.assertEqual(result, {})
            self.assertTrue(rejected)
        mapping = {chr(66 + i): "A" for i in range(5)}
        self.assertEqual(d.validate_project_aliases(mapping, set(), ctx)[0], {})
        pinned = dict(ctx, pinned={d.ukey2("Alpha"), d.ukey2("Beta")})
        self.assertEqual(d.validate_project_aliases({"Alpha": "Beta"}, set(), pinned)[0], {})
        with mock.patch.object(d, "load_project_aliases", return_value=({"Alpha": "Beta"}, {d._pair2("Alpha", "Beta")}, [["Alpha", "Beta"]])), mock.patch.object(d, "save_project_aliases"):
            result = d.project_merge_map(self.rows, log=lambda *_: None)[0]
        self.assertNotEqual(d._final2(result, "Alpha"), d._final2(result, "Beta"))

    def test_judge_unknown_enum_does_not_become_non_work(self):
        source = ast.parse((ROOT / "judge.py").read_text(encoding="utf-8-sig"))
        body = [n for n in source.body if isinstance(n, ast.FunctionDef) and n.name in {"parse_judgments_ex", "_as_list"}]
        env = {"JUDGE_EXAMPLES": [], "WORKTYPES": {"개발", "사무", "현장", "협업"},
               "rfind_json": lambda text, *args, **kwargs: json.loads(text), "Counter": Counter, "re": re}
        exec(compile(ast.Module(body=body, type_ignores=[]), "synthetic_judge", "exec"), env)
        for value in ("UNSURE", None, "yes", True, ""):
            result, info = env["parse_judgments_ex"](json.dumps({"j": [[0, value, "Alpha", "개발", "Review"]]}), [0])
            self.assertEqual(result, {})
            self.assertEqual(info["invalid_rows"], 1)
        result, _ = env["parse_judgments_ex"](json.dumps({"j": [[0, "n", "", "", ""], [1, "y", "Alpha", "개발", "Review"]]}), [0, 1])
        self.assertFalse(result[0]["work"])
        self.assertTrue(result[1]["work"])


if __name__ == "__main__":
    unittest.main()
