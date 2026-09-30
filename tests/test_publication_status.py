"""Completion evidence must survive local analysis -> immutable team publication."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock


APP = Path(__file__).resolve().parents[1] / "LoadMonitor25"
PERIOD = ["2026-01-01", "2026-01-31"]
TAG = "20260101-20260131"
STAGES = ("업무 로드 추출", "AI 판정", "AI 정제", "Agentic 매칭", "워크플로우 분석", "보고서 생성")


class PublicationStatusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="lm25-status-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        spec = importlib.util.spec_from_file_location("teamup_status_test", APP / "teamup.py")
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.module.REPORT = str(self.root)
        self.json(f"mm_meta_{TAG}.json", {
            "period": PERIOD, "total_mm": 1, "avail_mm": 1, "worked_h": 168, "signals": 400,
            "coverage": {"grade": "reliable", "reasons": []}, "cfg_used": {"standardDayHours": 8}})
        (self.root / f"mm_rows_{TAG}.csv").write_text("Level 2,mm,share\nA,1,1\n", encoding="utf-8")
        (self.root / f"signals_{TAG}.csv").write_text("time,project,judge\n2026-01-05 10:00,A,ai\n", encoding="utf-8")

    def json(self, name, value):
        (self.root / name).write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")

    def run_status(self, **changes):
        value = {"period": PERIOD, "ai_requested": True, "status": "complete",
                 "stages": [{"name": name, "ok": True, "note": ""} for name in STAGES]}
        value.update(changes)
        self.json("last_run.json", value)

    def judgments(self, judged=400, total=400, **extra):
        self.json(f"ai_judgments_{TAG}.json", dict(judged=judged, total=total, **extra))

    def payload(self):
        return self.module.make_payload({"owner": "Synthetic Person"}, *PERIOD)

    def test_partial_coverage_without_global_run_is_not_complete(self):
        for judged in (0, 1, 399):
            with self.subTest(judged=judged):
                self.judgments(judged, aborted=True)
                result = self.payload()
                self.assertTrue(result["member"]["partial"])
                status = result["member"]["analysis_status"]
                self.assertEqual((status["state"], status["judged"], status["total"]), ("partial", judged, 400))
                self.assertEqual(result["blocked"], [])  # preserved for review; receiver excludes comparisons

    def test_full_coverage_with_repaired_history_can_complete(self):
        self.run_status()
        self.judgments(repaired=3, partial_chunks=2, failed_rows=9)
        member = self.payload()["member"]
        self.assertEqual(member["analysis_status"]["state"], "complete")
        self.assertFalse(member["partial"])

    def test_stages_confirm_pending_bundle_before_finish_run(self):
        self.run_status(status=None)
        self.judgments()
        self.assertEqual(self.payload()["member"]["analysis_status"]["state"], "complete")

    def test_failed_downstream_stage_survives_full_judgment(self):
        self.run_status(status=None, stages=[{"name": "AI 판정", "ok": True},
                                           {"name": "워크플로우 분석", "ok": False}])
        self.judgments()
        member = self.payload()["member"]
        self.assertTrue(member["partial"])
        self.assertIn("워크플로우 분석", " ".join(member["analysis_status"]["warnings"]))

    def test_matching_final_partial_status_is_preserved(self):
        self.run_status(status="partial")
        self.judgments()
        self.assertTrue(self.payload()["member"]["partial"])

    def test_completed_rule_only_is_not_ai_partial(self):
        self.run_status(ai_requested=False, stages=[{"name": "업무 로드 추출", "ok": True},
                                                  {"name": "AI 판정", "ok": False,
                                                   "note": "AI 판정을 켜지 않고 실행했습니다(--ai 없음)"}])
        self.judgments(1)  # an old AI receipt does not override an intentional rule-only run
        member = self.payload()["member"]
        self.assertFalse(member["partial"])
        self.assertEqual(member["analysis_status"]["state"], "rule_only")
        self.assertIsNone(member["analysis_status"]["judged"])
        self.assertEqual(member["analysis_status"]["basis"], ["last_run.json"])

    def test_foreign_period_failure_and_stub_do_not_contaminate(self):
        self.run_status(period=["2026-09-01", "2026-09-30"], status="partial",
                        stages=[{"name": "AI 판정", "ok": False, "note": "LM_COPILOT_STUB"}])
        self.judgments()
        member = self.payload()["member"]
        self.assertFalse(member["partial"])
        self.assertFalse(member["stub"])
        self.assertEqual(member["analysis_status"]["state"], "unknown")
        self.assertNotIn("last_run.json", member["status_source_artifacts"])

    def test_matching_stub_note_is_preserved(self):
        self.run_status(stages=[{"name": "AI 판정", "ok": True, "note": "스텁 판정(LM_COPILOT_STUB)"}])
        self.judgments()
        self.assertTrue(self.payload()["member"]["stub"])

    def test_legacy_without_status_is_explicitly_unknown(self):
        member = self.payload()["member"]
        self.assertEqual(member["analysis_status"]["state"], "unknown")
        self.assertFalse(member["partial"])
        self.assertEqual(member["status_source_artifacts"], {})
        self.assertTrue(member["analysis_status"]["warnings"])

    def test_invalid_counts_are_unknown_not_success(self):
        self.run_status()
        for judged, total in ((-1, 400), (401, 400), (float("nan"), 400), (1, float("inf")),
                              (True, 400), (1.5, 400), ("400", 400), (0, 0)):
            with self.subTest(judged=judged, total=total):
                self.judgments(judged, total)
                status = self.payload()["member"]["analysis_status"]
                self.assertEqual(status["state"], "unknown")
                self.assertIsNone(status["judged"])

    def test_malformed_or_wrong_tag_judgment_is_unknown(self):
        self.run_status()
        for body in ("{broken", "[]", json.dumps({"judged": 400, "total": 400, "tag": "20260901-20260930"})):
            with self.subTest(body=body):
                (self.root / f"ai_judgments_{TAG}.json").write_text(body, encoding="utf-8")
                self.assertEqual(self.payload()["member"]["analysis_status"]["state"], "unknown")

    def test_in_progress_run_is_not_claimed_complete(self):
        self.run_status(status=None, stages=[{"name": "업무 로드 추출", "ok": True}])
        self.judgments()
        self.assertEqual(self.payload()["member"]["analysis_status"]["state"], "unknown")

    def test_status_logs_are_not_added_to_transmitted_files(self):
        self.run_status()
        self.judgments()
        result = self.payload()
        self.assertEqual(set(result["member"]["source_artifacts"]), set(result["files"]))
        self.assertEqual(set(result["member"]["status_source_artifacts"]), {"last_run.json", f"ai_judgments_{TAG}.json"})
        self.assertNotIn("last_run.json", result["files"])
        self.assertNotIn(f"ai_judgments_{TAG}.json", result["files"])

    def test_status_change_with_restored_mtime_aborts_capture(self):
        self.run_status()
        self.judgments()
        for name in ("last_run.json", f"ai_judgments_{TAG}.json"):
            with self.subTest(name=name):
                target = self.root / name
                stamp = target.stat()
                original_open = open
                calls = []

                def changing_open(path, *args, **kwargs):
                    if os.path.normcase(os.path.abspath(path)) == os.path.normcase(str(target)) and args == ("rb",):
                        calls.append(path)
                        if len(calls) == 2:
                            target.write_text("{}", encoding="utf-8")
                            os.utime(target, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
                    return original_open(path, *args, **kwargs)

                with mock.patch("builtins.open", side_effect=changing_open), self.assertRaises(ValueError):
                    self.payload()
                self.run_status()
                self.judgments()

    def test_status_added_during_capture_aborts(self):
        snapshot = self.module._source_snapshot
        calls = []

        def changing_snapshot(tag):
            calls.append(tag)
            if len(calls) == 2:
                self.judgments(1)
            return snapshot(tag)

        with mock.patch.object(self.module, "_source_snapshot", side_effect=changing_snapshot), self.assertRaises(ValueError):
            self.payload()

    def test_immutable_bundle_and_consumer_keep_partial_excluded(self):
        self.run_status(status="partial")
        self.judgments(1)
        result = self.payload()
        from bundles import write_bundle, resolve_member_dir
        spec = importlib.util.spec_from_file_location("aggregate_status_test", APP / "aggregate.py")
        aggregate = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(aggregate)
        share = self.root / "synthetic-team"
        dst = share / result["member"]["owner"]
        write_bundle(dst, result["member"], result["files"])
        published = json.loads((Path(resolve_member_dir(dst)) / "member.json").read_text(encoding="utf-8"))
        self.assertTrue(published["partial"])
        members = aggregate.load_members(str(share))
        self.assertEqual(len(members), 1)
        self.assertTrue(members[0]["unreliable"])
        self.assertIn("미완료 분석", members[0]["exclusion_reasons"])


if __name__ == "__main__":
    unittest.main()
