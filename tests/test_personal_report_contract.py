"""Personal HTML/Word reports preserve the same workload meanings as the UI."""
import csv
import importlib.util
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest import mock


APP = Path(__file__).resolve().parents[1] / "LoadMonitor25"
TAG = "20260901-20260930"


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, APP / file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class PersonalReportTests(unittest.TestCase):
    def test_both_static_reports_use_allocations_and_keep_unallocated_gap(self):
        with tempfile.TemporaryDirectory(prefix="lm25-personal-report-") as directory:
            root = Path(directory)
            report = root / "report"
            report.mkdir()
            (root / "config").mkdir()
            (root / "config/config.json").write_text('{"owner":"Synthetic"}')
            meta = {"total_mm": 1.0, "avail_mm": 1.0, "load_pct": 100,
                    "owner": "Synthetic", "period": ["2026-09-01", "2026-09-30"], "mm_basis": {}}
            (report / f"mm_meta_{TAG}.json").write_text(json.dumps(meta), encoding="utf-8")
            row = {"Level 1": "일반업무", "Level 2": "Synthetic", "Level 3": "Work", "유형": "개발", "mm": 0.2}
            source_id = "work_" + "a" * 24
            row["source_work_mm"] = json.dumps({source_id: 0.4})
            with open(report / f"mm_rows_{TAG}.csv", "w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=list(row))
                writer.writeheader()
                writer.writerow(row)
            workflow = {"ok": True, "tag": TAG, "flows": [
                {"model": "Synthetic", "project": "Synthetic", "detail": "Work",
                 "source_work_ids": [source_id], "mm": {"mm": 0.4, "details": {"Old": 0.4}},
                 "steps": [{"order": 1, "name": "Review", "agent": None}]},
                {"model": "Synthetic", "detail": "Excluded", "source_work_ids": ["work_" + "b" * 24],
                 "mm": {"mm": 0.8}, "steps": []},
            ]}
            (report / f"workflow_{TAG}.json").write_text(json.dumps(workflow), encoding="utf-8")
            candidate = {"fit": 50, "load_mm": 0.2, "related_work_mm": 0.2, "allocated_candidate_mm": 0.1,
                         "work_ids": ["work_" + "a" * 24], "work": ["Synthetic / Work"]}
            agentic = {"tag": TAG, "identity_schema": 1, "unique_related_work_mm": 0.2,
                       "match": [dict(candidate, task="A")], "new": [dict(candidate, name="New")], "misassigned": []}
            (report / f"agentic_{TAG}.json").write_text(json.dumps(agentic), encoding="utf-8")
            freeze = load("personal_contract_freeze", "freeze.py")
            word = load("personal_contract_word", "report_out.py")
            with mock.patch.multiple(freeze, ROOT=str(root), REPORT=str(report), FREEZE_DIR=str(report / "frozen")), \
                    mock.patch.object(freeze, "_apply_details", side_effect=lambda rows, log: (rows, 0)), \
                    mock.patch.object(freeze, "_is_stub", return_value=False), \
                    mock.patch.multiple(word, ROOT=str(root), REP=str(report)):
                files = freeze.report_island(TAG, log=lambda message: None)
                island_html = Path(files[0]).read_text(encoding="utf-8-sig")
                word_html = word.build(TAG)
                for html in (island_html, word_html):
                    self.assertIn("분류 업무 0.20 MM", html)
                    self.assertIn("미배분 0.80 MM", html)
                    self.assertIn("미검증", html)
                    self.assertIn("0.10", html)
                    self.assertNotIn("대체 가능 로드", html)
                    self.assertNotIn("대체 가능 ≈", html)
                data = json.loads(re.search(r'id="lm-report-data">(.*?)</script>', island_html, re.S)[1])
                self.assertEqual(data["total_mm"], 1.0)
                self.assertAlmostEqual(sum(float(r["mm"]) for r in data["rows"]), 0.2)
                self.assertEqual(data["workflow"]["flows"][0]["mm"]["mm"], 0.2)
                self.assertIsNone(data["workflow"]["flows"][1]["mm"]["mm"])
                self.assertTrue(data["workflow"]["flows"][1]["needs_review"])
                self.assertIn("Agent 확인 필요", island_html)
                self.assertIn("관련 MM 확인 필요", island_html)
                agentic.pop("identity_schema")
                (report / f"agentic_{TAG}.json").write_text(json.dumps(agentic), encoding="utf-8")
                self.assertIn("미확인", word.build(TAG))


if __name__ == "__main__":
    unittest.main()
