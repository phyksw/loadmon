"""Actual team report rendering: reference readability never changes numeric eligibility."""
import contextlib
import copy
import csv
import io
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile
from types import ModuleType
import unittest
from unittest import mock


SOURCE = Path(__file__).resolve().parents[1] / "LoadMonitor25"
TAG = "20260901-20260930"
OLD = "20260801-20260831"


def module(name, path, dependencies=None):
    result = ModuleType(name)
    result.__file__ = str(path)
    previous = list(sys.path)
    try:
        with mock.patch.dict(sys.modules, dependencies or {}):
            exec(compile(path.read_text(encoding="utf-8-sig"), str(path), "exec"), result.__dict__)
    finally:
        sys.path[:] = previous
    return result


class TeamReferenceReviewTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="lm25-reference-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.share = self.root / "share"
        self.share.mkdir()
        (self.root / "core").mkdir()
        (self.root / "config").mkdir()
        self.html = self.share / "personal"
        self.html.mkdir()
        for name in ("aggregate.py", "team_report.py", "core/details.py", "core/bundles.py"):
            shutil.copyfile(SOURCE / name, self.root / name)
        details = module("synthetic_reference_details", self.root / "core/details.py")
        bundles = module("synthetic_reference_bundles", self.root / "core/bundles.py")
        self.ag = module("synthetic_reference_aggregate", self.root / "aggregate.py",
                         {"details": details, "bundles": bundles})
        self.report = module("synthetic_reference_report", self.root / "team_report.py")
        patch = mock.patch.object(self.report, "_agg", return_value=self.ag)
        patch.start()
        self.addCleanup(patch.stop)
        self.write(self.root / "config/agentic_tasks.json", {"tasks": []})

    @staticmethod
    def write(path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    @staticmethod
    def flow(label="Synthetic duty", **updates):
        return {"model": "Synthetic project / " + label, "project": "Synthetic project",
                "detail": label, "role": "Synthetic role " + label, "summary": "Synthetic summary " + label,
                "mm": {"mm": 987654.32}, "identity_schema": 1, "kpi_eligible": True,
                "steps": [{"name": "Synthetic step " + label, "desc": "Synthetic action " + label,
                           "evidence": "Synthetic evidence " + label, "evidence_status": "verified",
                           "agent": "상", "agent_how": "Synthetic proposal " + label}], **updates}

    def member(self, folder, tag=TAG, owner=None, **updates):
        directory = self.share / folder
        data = {"owner": owner or folder, "member_id": folder, "tag": tag,
                "period": [tag[:4] + "-" + tag[4:6] + "-" + tag[6:8],
                           tag[9:13] + "-" + tag[13:15] + "-" + tag[15:17]],
                "total_mm": 10, "avail_mm": 10, "coverage": {"grade": "reliable"},
                "cfg_used": {"standardDayHours": 8}, **updates}
        self.write(directory / "member.json", data)
        with (directory / f"mm_rows_{tag}.csv").open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=["Level 2", "Level 3", "유형", "mm"])
            writer.writeheader()
            writer.writerow({"Level 2": "Synthetic project", "Level 3": "Synthetic duty", "유형": "개발", "mm": 10})
        return directory

    def render(self):
        with contextlib.redirect_stdout(io.StringIO()):
            return self.report.render_full(str(self.share), str(self.html), log=lambda _: None)

    @staticmethod
    def embedded(body):
        text = re.search(r'<script type="application/json" id="lm-team-data">(.*?)</script>', body, re.S).group(1)
        return json.loads(text)

    def test_all_ineligible_members_keep_own_period_partial_and_review_text(self):
        a = self.member("Old", tag=OLD, coverage=None)
        b = self.member("Partial", coverage=None, partial=True)
        self.write(a / f"workflow_{OLD}.json", {"tag": OLD, "flows": [self.flow("Old duty")]})
        self.write(b / f"workflow_{TAG}.json", {"tag": TAG, "partial": True,
                   "flows": [self.flow("Saved duty")], "review_flows": [self.flow("Review duty",
                   needs_review=True, review_reason="Synthetic unresolved evidence")]})
        before = {p: p.read_bytes() for folder in (a, b) for p in folder.iterdir()}
        with mock.patch.object(self.ag, "load_members", wraps=self.ag.load_members) as loads:
            body, shared, info = self.render()
        self.assertEqual(loads.call_count, 1)
        self.assertEqual((info["reference_flows"], info["clusters"], info["wf_owners"], info["agentic"]), (3, 0, 0, 0))
        data = self.embedded(body)
        self.assertTrue(all(not m["kpi_eligible"] for m in data["members"]))
        for label in ("Old duty", "Saved duty", "Review duty"):
            for prefix in ("Synthetic role ", "Synthetic step ", "Synthetic action ", "Synthetic evidence "):
                self.assertIn(prefix + label, body)
                self.assertIn(prefix + label, shared)
        self.assertIn(OLD, body)
        self.assertIn("워크플로우 분석 일부 완료", body)
        self.assertIn("Synthetic unresolved evidence", body)
        refs = data["reference_workflows"]["items"]
        self.assertTrue(all(r["reference_readable"] and not r["kpi_eligible"] for r in refs))
        self.assertNotIn("987654", json.dumps(refs))
        self.assertEqual({p: p.read_bytes() for p in before}, before)

    def test_reference_does_not_change_confirmed_matrix_flows_or_candidate_counts(self):
        a = self.member("Confirmed")
        self.write(a / f"workflow_{TAG}.json", {"tag": TAG, "flows": [self.flow()]})
        numeric_before = self.ag.collect_team_data(str(self.share))
        _, _, before = self.render()
        b = self.member("Unknown", tag=OLD, coverage=None, cfg_used={"standardDayHours": 7})
        self.write(b / f"workflow_{OLD}.json", {"tag": OLD, "flows": [self.flow()]})
        numeric_after = self.ag.collect_team_data(str(self.share))
        body, _, after = self.render()
        for key in ("matrix", "details", "wt", "common", "agentic"):
            self.assertEqual(numeric_before[key], numeric_after[key])
        for key in ("clusters", "wf_owners", "flows", "agentic"):
            self.assertEqual(before[key], after[key])
        self.assertEqual(after["reference_flows"], 1)
        self.assertEqual([r["owner"] for r in self.embedded(body)["reference_workflows"]["items"]], ["Unknown"])

    def test_same_display_name_and_member_id_keep_separate_source_identities(self):
        for folder in ("Folder A", "Folder B"):
            directory = self.member(folder, owner="Same name", member_id="same-id")
            self.write(directory / f"workflow_{TAG}.json", {"tag": TAG, "flows": [self.flow(folder)]})
        body, _, info = self.render()
        items = self.embedded(body)["reference_workflows"]["items"]
        self.assertEqual((info["reference_flows"], info["clusters"]), (2, 0))
        self.assertEqual(len({r["member_key"] for r in items}), 2)
        self.assertEqual({r["source_folder"] for r in items}, {"Folder A", "Folder B"})
        self.assertNotIn(str(self.share), json.dumps(items, ensure_ascii=False))
        self.assertTrue(all(re.fullmatch(r"[0-9a-f]{64}", r["member_key"]) for r in items))

    def test_wrong_period_stub_and_invalid_json_are_explained_without_showing_false_content(self):
        payloads = [("Wrong period", {"tag": OLD, "flows": [self.flow("Forbidden period content")]}),
                    ("Stub", {"tag": TAG, "stub": True, "flows": [self.flow("Forbidden stub content")]}),
                    ("Malformed", None)]
        for folder, payload in payloads:
            directory = self.member(folder, coverage=None)
            self.write(directory / f"workflow_{TAG}.json", payload)
        body, _, info = self.render()
        reference = self.embedded(body)["reference_workflows"]
        self.assertEqual(info["reference_flows"], 0)
        self.assertEqual({n["status"] for n in reference["notices"]}, {"period_mismatch", "stub", "invalid_format"})
        self.assertNotIn("Forbidden period content", body)
        self.assertNotIn("Forbidden stub content", body)
        self.assertIn("JSON 내부 기간", body)
        self.assertIn("시험용 스텁", body)

    def test_malicious_text_is_escaped_in_visible_cards_and_embedded_json(self):
        evil = '</script><img src=x onerror="synthetic">'
        directory = self.member("Safe folder", owner=evil, coverage=None)
        flow = self.flow(evil, role=evil, review_reason=evil, needs_review=True)
        self.write(directory / f"workflow_{TAG}.json", {"tag": TAG, "review_flows": [flow]})
        body, _, _ = self.render()
        self.assertNotIn(evil, body)
        self.assertIn("&lt;/script&gt;&lt;img", body)
        self.assertEqual(self.embedded(body)["reference_workflows"]["items"][0]["owner"], evil)

    def test_partial_artifact_on_eligible_member_is_readable_without_changing_member_status(self):
        directory = self.member("Eligible")
        self.write(directory / f"workflow_{TAG}.json", {"tag": TAG, "partial": True, "flows": [self.flow()]})
        members = self.ag.load_members(str(self.share))
        before = copy.deepcopy(members)
        reference = self.report.collect_reference_workflows(members)
        self.assertEqual(members, before)
        self.assertTrue(members[0]["comparison_eligible"])
        self.assertEqual(members[0]["measurement_confidence"], "reliable")
        self.assertEqual(len(reference["items"]), 1)
        body, _, info = self.render()
        self.assertEqual((info["reference_flows"], info["clusters"]), (1, 0))
        self.assertTrue(self.embedded(body)["members"][0]["kpi_eligible"])

    def test_completion_states_are_visible_separately_and_private_status_text_is_not_forwarded(self):
        self.member("Legacy")
        for state in ("complete", "partial", "rule_only", "unknown"):
            status = {"state": state, "judged": 1 if state == "partial" else 400,
                      "total": 400, "ai_requested": state != "rule_only",
                      "warnings": ["PRIVATE_STATUS_LOG"], "basis": ["PRIVATE_SOURCE_PATH"]}
            if state == "unknown":
                status["judged"] = 10 ** 500
            self.member(state, partial=state == "partial", analysis_status=status)
        data = self.ag.collect_team_data(str(self.share))
        self.assertEqual(data["matrix"]["Synthetic project"],
                         dict.fromkeys(("Legacy", "complete", "rule_only", "unknown"), 10))
        body, shared, _ = self.render()
        for document in (body, shared):
            for label in ("분석 완료 여부 미확인", "분석 일부 완료", "규칙 분류 · AI 미요청", "분석 완료", "1 / 400건"):
                self.assertIn(label, document)
            self.assertNotIn("PRIVATE_STATUS_LOG", document)
            self.assertNotIn("PRIVATE_SOURCE_PATH", document)
            members = {m["owner"]: m for m in self.embedded(document)["members"]}
            self.assertEqual(members["Legacy"]["analysis_status"]["state"], "unknown")
            self.assertTrue(members["Legacy"]["kpi_eligible"])
            self.assertFalse(members["partial"]["kpi_eligible"])
            self.assertIsNone(members["unknown"]["analysis_status"]["judged"])


if __name__ == "__main__":
    unittest.main()
