"""Team reporting period/measurement/MM contracts; synthetic TEMP files only."""
import contextlib
import copy
import csv
import importlib.util
import io
import json
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
from unittest import mock


SOURCE = Path(__file__).resolve().parents[1] / "LoadMonitor25"
TAG = "20260901-20260930"
OLD = "20260801-20260831"


def module(name, relative):
    spec = importlib.util.spec_from_file_location(name, SOURCE / relative)
    out = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(out)
    return out


AG = module("lm25_reporting_aggregate", "aggregate.py")
REPORT = module("lm25_reporting_full", "team_report.py")
BUNDLES = module("lm25_reporting_bundles", "core/bundles.py")


class ReportingContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="lm25-report-contract-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.share = self.root / "share"
        self.share.mkdir()
        self.html = self.share / "personal"
        self.html.mkdir()
        config = self.root / "config"
        config.mkdir()
        (config / "agentic_tasks.json").write_text(json.dumps({"tasks": [
            {"id": "A", "name": "Synthetic A"}, {"id": "B", "name": "Synthetic B"}]}))
        for patch in (mock.patch.object(AG, "ROOT", str(self.root)),
                      mock.patch.object(REPORT, "ROOT", str(self.root)),
                      mock.patch.object(REPORT, "_agg", return_value=AG)):
            patch.start()
            self.addCleanup(patch.stop)

    def write_json(self, path, obj):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")

    def member(self, name="Synthetic", **changes):
        member = {"owner": name, "tag": TAG, "period": ["2026-09-01", "2026-09-30"],
                  "total_mm": 10.0, "avail_mm": 10.0, "load_pct": 100.0,
                  "coverage": {"grade": "reliable"}, "cfg_used": {"standardDayHours": 8}}
        member.update(changes)
        directory = self.share / name
        self.write_json(directory / "member.json", member)
        return directory, member

    def rows(self, directory, tag=TAG, mm=10.0, project="Synthetic project"):
        path = directory / f"mm_rows_{tag}.csv"
        with path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=["Level 1", "Level 2", "Level 3", "유형", "mm"])
            writer.writeheader()
            writer.writerow({"Level 1": "개발", "Level 2": project,
                             "Level 3": "Synthetic duty", "유형": "개발", "mm": mm})
        return path

    def flow(self, high=1):
        return {"project": "Synthetic project", "detail": "Synthetic duty",
                "model": "Synthetic project / Synthetic duty", "mm": {"mm": 10},
                "identity_schema": 1, "kpi_eligible": True,
                "steps": [{"name": f"Synthetic step {n}", "agent": "상", "evidence_status": "verified"}
                          for n in range(high)] + [{"name": "Synthetic judgment", "agent": "하",
                                                   "evidence_status": "verified"}]}

    def flow_rows(self):
        return {"Synthetic": [{"Level 2": "Synthetic project", "Level 3": "Synthetic duty",
                               "유형": "개발", "mm": 10}]}

    def agentic(self):
        candidate = {"work_ids": ["work_" + "a" * 24], "related_work_mm": 10,
                     "allocated_candidate_mm": 10 / 3, "load_mm": 10, "fit": 50}
        return {"tag": TAG, "identity_schema": 1, "unique_related_work_mm": 10,
                "match": [dict(candidate, task="A"), dict(candidate, task="B")],
                "new": [dict(candidate, name="Synthetic candidate")], "misassigned": []}

    def personal(self, name="current.html", tag=TAG, stub=False, flow=None):
        data = {"owner": "Synthetic", "tag": tag, "stub": stub,
                "workflow": {"tag": tag, "flows": [flow or self.flow()]}}
        (self.html / name).write_text('<script type="application/json" id="lm-report-data">'
                                      + json.dumps(data) + "</script>", encoding="utf-8")

    def test_no_previous_period_rows_agentic_meta_or_workflow_fallback(self):
        directory, member = self.member()
        self.rows(directory, OLD)
        for prefix in ("agentic", "workflow", "mm_meta"):
            self.write_json(directory / f"{prefix}_{OLD}.json", {"tag": OLD, "flows": [self.flow()]})
            self.assertEqual(REPORT.find_member_file(str(directory), prefix, TAG), "")
            self.assertEqual(REPORT.find_member_any(str(directory), prefix, TAG), "")
        self.assertEqual(REPORT._member_rows(str(directory), TAG, 10), ([], ""))
        self.assertEqual(REPORT.collect_agentic_all([dict(member, dir=str(directory))]), [])
        self.assertIsNone(REPORT.member_report(str(directory), member, str(self.html)))

    def test_current_named_files_reject_other_tag_stub_and_partial(self):
        directory, _ = self.member()
        for change in ({"tag": OLD}, {"stub": True}, {"partial": True}, {"ok": False}):
            data = dict(self.agentic(), **change)
            self.write_json(directory / f"agentic_{TAG}.json", data)
            member = AG.load_members(str(self.share))[0]
            self.assertIsNone(AG.load_agentic(member))
            self.assertEqual(REPORT.collect_agentic_all([member]), [])

    def test_html_old_stub_and_same_period_server_precedence(self):
        directory, _ = self.member()
        self.rows(directory)
        self.personal("old.html", tag=OLD)
        self.personal("stub.html", stub=True)
        self.assertEqual(REPORT.gather_flows(str(self.share), str(self.html))[0], [])
        self.personal("valid.html", flow=self.flow(4))
        self.assertEqual(len(REPORT.gather_flows(str(self.share), str(self.html))[0][0]["fl"]["steps"]), 5)
        self.write_json(directory / f"workflow_{TAG}.json", {"tag": TAG, "flows": [self.flow()]})
        items, src, _ = REPORT.gather_flows(str(self.share), str(self.html))
        self.assertEqual(len(items[0]["fl"]["steps"]), 2)
        self.assertEqual((src["server"], src["html"]), (1, 0))
        self.write_json(directory / f"workflow_{TAG}.json", {"tag": TAG, "partial": True, "flows": []})
        self.assertEqual(REPORT.gather_flows(str(self.share), str(self.html))[0], [])

    def test_step_description_split_never_creates_saved_mm(self):
        clusters = []
        for count in (1, 3):
            grouped, _ = REPORT.cluster_flows([{"owner": "Synthetic", "fl": self.flow(count)}],
                                             str(self.share), self.flow_rows())
            clusters.append(grouped[0])
        self.assertEqual([c["related_work_mm"] for c in clusters], [10, 10])
        self.assertEqual([c["expected_saved_mm"] for c in clusters], [None, None])
        self.assertTrue(all("ax_mm" not in c and "ax_ratio" not in c for c in clusters))

    def test_allocation_and_unique_contract_includes_new_candidates(self):
        normalized = AG.norm_agentic(self.agentic())
        self.assertTrue(normalized["allocation_verified"])
        self.assertAlmostEqual(sum(x["allocated_candidate_mm"] for x in normalized["match"] + normalized["new"]), 10)
        self.assertEqual(normalized["unique_related_work_mm"], 10)
        self.assertIsNone(normalized["expected_saved_mm"])
        legacy = AG.norm_agentic({"match": [{"task": "A", "fit": 50, "load_mm": 10, "load_mm_split": 5}]})
        self.assertIsNone(legacy["match"][0]["allocated_candidate_mm"])
        self.assertEqual(legacy["match"][0]["related_work_mm"], 10)
        broken = self.agentic()
        broken["new"][0]["allocated_candidate_mm"] = 9
        self.assertFalse(AG.norm_agentic(broken)["allocation_verified"])

    def test_comparison_uses_current_period_known_coverage_and_config(self):
        good_dir, _ = self.member()
        self.rows(good_dir)
        self.write_json(good_dir / f"agentic_{TAG}.json", self.agentic())
        self.write_json(good_dir / f"workflow_{TAG}.json", {"tag": TAG, "flows": [self.flow()]})
        cases = {"NoCoverage": {"coverage": None}, "UnknownGrade": {"coverage": {"grade": "other"}},
                 "Unreliable": {"coverage": {"grade": "unreliable"}}, "NoCapacity": {"avail_mm": 0},
                 "NoConfig": {"cfg_used": None}, "Earlier": {"tag": OLD, "period": ["2026-08-01", "2026-08-31"]}}
        for name, change in cases.items():
            directory, _ = self.member(name, **change)
            self.rows(directory)
            self.write_json(directory / f"agentic_{TAG}.json", self.agentic())
            self.write_json(directory / f"workflow_{TAG}.json", {"tag": TAG, "flows": [self.flow()]})
        data = AG.collect_team_data(str(self.share))
        self.assertEqual(data["comparison_tag"], TAG)
        self.assertEqual([m["owner"] for m in data["members"] if m["kpi_eligible"]], ["Synthetic"])
        self.assertEqual(set(data["excluded"]), set(cases))
        self.assertEqual([a["owner"] for a in data["agentic"]], ["Synthetic"])
        items, _, _ = REPORT.gather_flows(str(self.share), str(self.html))
        self.assertEqual([item["owner"] for item in items], ["Synthetic"])

    def test_tied_configs_and_duplicate_identity_are_excluded(self):
        self.member("One")
        self.member("Two", cfg_used={"standardDayHours": 6})
        members = AG.load_members(str(self.share))
        self.assertTrue(all(not m["kpi_eligible"] for m in members))
        same = [dict(m, cfg_used={"standardDayHours": 8}, member_id="same") for m in members]
        self.assertTrue(all(not m["kpi_eligible"] for m in AG.mark_members(same)))

    def test_zero_total_stays_zero_across_row_flow_and_personal_report(self):
        directory, member = self.member(total_mm=0)
        self.rows(directory, mm=10)
        self.write_json(directory / f"workflow_{TAG}.json", {"tag": TAG, "flows": [self.flow()]})
        self.assertEqual(AG.mm_scale(0, 10), 0)
        items, _, rows = REPORT.gather_flows(str(self.share), str(self.html))
        clusters, _ = REPORT.cluster_flows(items, str(self.share), rows)
        self.assertEqual(clusters[0]["related_work_mm"], 0)
        report = REPORT.member_report(str(directory), member, str(self.html))
        body = Path(report).read_text(encoding="utf-8")
        self.assertEqual(REPORT._island(body, "lm-report-data")["total_mm"], 0)

    def test_immutable_bundle_read_and_corrupt_pointer_never_legacy_fallback(self):
        directory, member = self.member()
        old_rows = self.rows(directory)
        run = BUNDLES.write_bundle(directory, member, {old_rows.name: old_rows.read_text(encoding="utf-8")})
        members = AG.load_members(str(self.share))
        self.assertEqual(members[0]["dir"], run)
        self.personal(flow=self.flow())
        self.assertEqual(REPORT.gather_flows(str(self.share), str(self.html))[0], [])
        self.write_json(directory / "current.json", {"schema": 1, "run_id": "broken"})
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(AG.load_members(str(self.share)), [])

    def test_render_pins_members_once_and_javascript_uses_allocation(self):
        directory, _ = self.member()
        self.rows(directory)
        self.write_json(directory / f"agentic_{TAG}.json", self.agentic())
        self.write_json(directory / f"workflow_{TAG}.json", {"tag": TAG, "flows": [self.flow()]})
        with mock.patch.object(AG, "load_members", wraps=AG.load_members) as load:
            body, _, info = REPORT.render_full(str(self.share), str(self.html), log=lambda _: None)
        self.assertEqual(load.call_count, 1)
        self.assertEqual(info["wf_owners"], 1)
        self.assertIn("예상 절감 미검증", body)
        self.assertNotIn("AX 가능 MM", body)
        self.assertIn("hit.allocated_candidate_mm", body)
        self.assertNotIn("hit.load_mm_split", body)
        scripts = re.findall(r"<script>(.*?)</script>", body, re.S)
        script = self.root / "generated.js"
        script.write_text("\n".join(scripts), encoding="utf-8")
        check = subprocess.run(["node", "--check", str(script)], capture_output=True, text=True)
        self.assertEqual(check.returncode, 0, check.stderr)

    def test_bad_flow_evidence_never_enters_automation_priority(self):
        flow = self.flow()
        flow["steps"][0]["evidence_status"] = "invalid"
        normalized = REPORT.norm_flow(flow)
        clusters, _ = REPORT.cluster_flows([{"owner": "Synthetic", "fl": normalized}],
                                          str(self.share), self.flow_rows())
        self.assertEqual(clusters[0]["agent_hi"], 0)
        self.assertIsNone(REPORT.norm_flow(dict(flow, needs_review=True)))
        legacy = copy.deepcopy(flow)
        legacy.pop("identity_schema")
        legacy["steps"][0]["evidence_status"] = "verified"
        clusters, _ = REPORT.cluster_flows([{"owner": "Synthetic", "fl": legacy}],
                                          str(self.share), self.flow_rows())
        self.assertEqual(clusters[0]["agent_hi"], 0)

    def test_incomplete_source_ids_remain_visible_without_workflow_kpi(self):
        directory, _ = self.member(total_mm=1)
        self.rows(directory, mm=0.2)
        present = AG.stable_work_id(self.flow_rows()["Synthetic"][0])
        absent = AG.stable_work_id({"Level 2": "Excluded", "Level 3": "Prior duty", "유형": "개발"})
        flow = dict(self.flow(), source_work_ids=[present, absent], mm={"mm": 1})
        self.write_json(directory / f"workflow_{TAG}.json", {"tag": TAG, "flows": [flow]})
        items, _, rows = REPORT.gather_flows(str(self.share), str(self.html))
        clusters, review = REPORT.cluster_flows(items, str(self.share), rows)
        self.assertEqual(clusters, [])
        self.assertEqual(len(review), 1)
        self.assertIn("KPI 제외", review[0]["review_reason"])
        body, _, info = REPORT.render_full(str(self.share), str(self.html), log=lambda _: None)
        self.assertEqual(info["wf_owners"], 0)
        self.assertEqual(info["review_flows"], 1)
        self.assertIn("워크플로우 연결 확인 필요", body)
        self.assertIn("Synthetic project / Synthetic duty", body)

    def test_source_id_contract_never_falls_back_to_saved_mm_or_alias_name(self):
        rows = [{"Level 2": "Alpha", "Level 3": "Synthetic duty", "유형": "개발", "mm": 0.2},
                {"Level 2": "Beta", "Level 3": "Synthetic duty", "유형": "개발", "mm": 0.8}]
        ids = [AG.stable_work_id(row) for row in rows]
        flow = dict(self.flow(), project="Beta", source_work_ids=ids, mm={"mm": 999})
        self.assertEqual(REPORT._flow_mm(REPORT.norm_flow(flow), rows), 1)
        self.assertIsNone(REPORT._flow_mm(flow, rows[1:]))
        self.assertIsNone(REPORT._flow_mm(flow, rows + [dict(rows[0])]))
        for source_ids in ([], [ids[0], ids[0]], [ids[0], "unknown"], "invalid", None):
            self.assertIsNone(REPORT._flow_mm(dict(flow, source_work_ids=source_ids), rows))
        self.assertEqual(REPORT._flow_mm(dict(flow, source_work_ids=[ids[0]]), rows[:1]), 0.2)
        legacy = dict(flow)
        legacy.pop("source_work_ids")
        self.assertEqual(REPORT._flow_mm(legacy, rows), 0.8)
        self.assertIsNone(REPORT._flow_mm(legacy, rows + [dict(rows[1], 유형="협업")]))

    def test_refined_lineage_preserves_renames_merges_and_current_mm(self):
        original = [{"Level 2": "Alpha", "Level 3": "design", "유형": "개발", "mm": 0.2},
                    {"Level 2": "Beta", "Level 3": "review", "유형": "협업", "mm": 0.8}]
        ids = [AG.stable_work_id(row) for row in original]
        lineage = json.dumps(dict(zip(ids, (0.2, 0.8), strict=True)))
        merged = {"Level 2": "Combined", "Level 3": "Design review", "유형": "사무",
                  "mm": 1, "source_work_mm": lineage}
        flows = [dict(self.flow(), source_work_ids=source_ids, mm={"mm": 999})
                 for source_ids in ([ids[0]], [ids[1]], ids)]
        self.assertEqual([REPORT._flow_mm(flow, [merged]) for flow in flows], [0.2, 0.8, 1])
        reduced = dict(merged, _mm=0.5)
        self.assertEqual([REPORT._flow_mm(flow, [reduced]) for flow in flows], [0.1, 0.4, 0.5])
        # A renamed row is not evidence that an unrelated old work ID with that name survived.
        renamed_id = AG.stable_work_id(merged)
        self.assertIsNone(REPORT._flow_mm(dict(self.flow(), source_work_ids=[renamed_id]), [merged]))
        representative = dict(merged, **{key: original[1][key] for key in ("Level 2", "Level 3", "유형")})
        self.assertEqual(REPORT._flow_mm(flows[1], [representative]), 0.8)
        for bad in (dict(merged, mm=1.2), dict(merged, source_work_mm="{}"),
                    dict(merged, source_work_mm=json.dumps({ids[0]: -0.2, ids[1]: 1.2})),
                    dict(merged, source_work_mm='{"' + ids[0] + '":0.2,"' + ids[0] + '":0.8}')):
            self.assertIsNone(REPORT._flow_mm(flows[0], [bad]))
        self.assertIsNone(REPORT._flow_mm(flows[0], [merged, dict(original[0])]))
        self.assertIsNone(REPORT._flow_mm(flows[2], [dict(merged, mm=0.2,
                                                        source_work_mm=json.dumps({ids[0]: 0.2}))]))

    def test_project_branches_preserve_steps_and_do_not_duplicate_workload(self):
        directory, _ = self.member(total_mm=1)
        self.rows(directory, mm=1)
        first = dict(self.flow(), model="Synthetic project", detail="", branch="Design branch")
        second = copy.deepcopy(first)
        second.update(branch="Review branch", role="Distinct role")
        second["steps"][0]["name"] = "Independent review step"
        self.write_json(directory / f"workflow_{TAG}.json", {"tag": TAG, "flows": [first, second, first]})
        items, src, rows = REPORT.gather_flows(str(self.share), str(self.html))
        self.assertEqual(len(items), 2)
        self.assertEqual(src["server"], 2)
        clusters, coarse = REPORT.cluster_flows(items, str(self.share), rows)
        self.assertEqual(clusters, [])
        self.assertEqual(len(coarse), 2)
        body, _, info = REPORT.render_full(str(self.share), str(self.html), log=lambda _: None)
        self.assertEqual(info["wf_owners"], 0)
        self.assertEqual(info["coarse"], 2)
        for text in ("Design branch", "Review branch", "Independent review step", "Distinct role"):
            self.assertIn(text, body)

    def test_personal_flow_uses_current_lineage_and_keeps_unknown_rating_unknown(self):
        directory, member = self.member(total_mm=1)
        row = dict(self.flow_rows()["Synthetic"][0], mm=0.2)
        source_id = AG.stable_work_id(row)
        renamed = dict(row, **{"Level 3": "Renamed duty", "유형": "협업"},
                       source_work_mm=json.dumps({source_id: 0.2}))
        with (directory / f"mm_rows_{TAG}_refined.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(renamed))
            writer.writeheader()
            writer.writerow(renamed)
        flow = dict(self.flow(), branch="Preserved branch", source_work_ids=[source_id], mm={"mm": 999})
        flow["steps"][0]["evidence_status"] = "invalid"
        for ids, expected in (([source_id], 0.2), (["work_" + "f" * 24], None)):
            self.write_json(directory / f"workflow_{TAG}.json", {"tag": TAG, "flows": [dict(flow, source_work_ids=ids)]})
            path = REPORT.member_report(str(directory), member, str(self.html))
            body = Path(path).read_text(encoding="utf-8")
            data = REPORT._island(body, "lm-report-data")
            self.assertEqual(data["workflow"]["flows"][0]["mm"]["mm"], expected)
            self.assertEqual(data["workflow"]["flows"][0]["related_work_mm"], expected)
            self.assertIsNone(data["workflow"]["flows"][0]["expected_saved_mm"])
            self.assertIn("Agent 확인 필요", body)
            self.assertIn("Preserved branch", body)
            self.assertNotIn("999 MM", body)
            self.assertIn("관련 업무 0.2 MM" if expected is not None else "업무 MM 미확인", body)

    def test_shared_current_amounts_copy_refreshes_detail_numbers_and_retains_review_content(self):
        rows = self.flow_rows()["Synthetic"]
        source_id = AG.stable_work_id(rows[0])
        flow = dict(self.flow(), source_work_ids=[source_id], branch="Preserved branch",
                    mm={"mm": 10, "details": {"Synthetic duty": 10}})
        workflow = {"tag": TAG, "flows": [flow]}
        original = copy.deepcopy(workflow)
        current = REPORT.apply_current_flow_amounts(workflow, rows)
        self.assertEqual(current["flows"][0]["mm"], {"mm": 10, "details": {"Synthetic duty": 10}})
        reduced = dict(rows[0], _mm=0.2)
        current = REPORT.apply_current_flow_amounts(workflow, [reduced])
        self.assertEqual(current["flows"][0]["mm"], {"mm": 0.2, "details": {"Synthetic duty": 0.2}})
        missing = REPORT.apply_current_flow_amounts(workflow, [])
        self.assertEqual(missing["flows"][0]["mm"], {"mm": None, "details": {}})
        self.assertTrue(missing["flows"][0]["needs_review"])
        self.assertFalse(missing["flows"][0]["kpi_eligible"])
        self.assertEqual(missing["flows"][0]["steps"], flow["steps"])
        self.assertEqual(missing["flows"][0]["branch"], "Preserved branch")
        self.assertEqual(workflow, original)
        invalid = dict(flow, needs_review=True, kpi_eligible=False)
        current = REPORT.apply_current_flow_amounts({"review_flows": [invalid]}, rows)
        self.assertTrue(current["review_flows"][0]["needs_review"])
        self.assertFalse(current["review_flows"][0]["kpi_eligible"])

    def test_refine_excluded_mm_is_not_reallocated_in_any_team_output(self):
        directory, member = self.member(total_mm=1)
        self.rows(directory, mm=1)
        refined = self.rows(directory, mm=0.2)
        refined.rename(directory / f"mm_rows_{TAG}_refined.csv")
        self.write_json(directory / f"workflow_{TAG}.json", {"tag": TAG, "flows": [self.flow()]})
        data = AG.collect_team_data(str(self.share))
        self.assertEqual(sum(sum(row.values()) for row in data["matrix"].values()), 0.2)
        self.assertEqual(data["members"][0]["total_mm"], 1)
        self.assertEqual(data["members"][0]["classified_work_mm"], 0.2)
        self.assertEqual(data["members"][0]["unallocated_work_mm"], 0.8)
        members = AG.load_members(str(self.share))
        matrix, *_ = REPORT.team_rows_matrix(members, str(self.share))
        self.assertEqual(sum(sum(row.values()) for row in matrix.values()), 0.2)
        items, _, rows = REPORT.gather_flows(str(self.share), str(self.html))
        clusters, _ = REPORT.cluster_flows(items, str(self.share), rows)
        self.assertEqual(clusters[0]["related_work_mm"], 0.2)
        path = REPORT.member_report(str(directory), member, str(self.html))
        personal = REPORT._island(Path(path).read_text(encoding="utf-8"), "lm-report-data")
        self.assertEqual(sum(row["mm"] for row in personal["rows"]), 0.2)
        self.assertEqual(personal["total_mm"], 1)
        self.assertEqual(personal["unallocated_work_mm"], 0.8)
        body, _, _ = REPORT.render_full(str(self.share), str(self.html), log=lambda _: None)
        self.assertIn("분류된 업무 0.20 MM", body)
        self.assertIn("차이 0.80 MM", body)


if __name__ == "__main__":
    unittest.main()
