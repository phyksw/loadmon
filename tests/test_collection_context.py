"""Collection evidence contracts: code copies and synthetic TEMP data only."""

import contextlib
import copy
import csv
from datetime import date, datetime
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


APP = Path(__file__).resolve().parents[1] / "LoadMonitor25"
DAY = date(2026, 9, 7)
TAG = "20260907-20260907"


class CollectionContextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="lm25-collection-context-")
        cls.root = Path(cls.temp.name) / "LoadMonitor25"
        (cls.root / "core").mkdir(parents=True)
        (cls.root / "config").mkdir()
        (cls.root / "report").mkdir()
        for source in (APP / "core").glob("*.py"):
            shutil.copyfile(source, cls.root / "core" / source.name)
        for name in ("mine.py", "judge.py", "refine.py"):
            shutil.copyfile(APP / name, cls.root / name)
        cls.defaults = json.loads((APP / "config/config.default.json").read_text(encoding="utf-8-sig"))
        cls.old_path = list(sys.path)
        cls.old_modules = {name: sys.modules.get(name) for name in ("extract", "details", "judge", "progress", "projmap")}
        sys.path[:0] = [str(cls.root / "core"), str(cls.root)]
        for name, relative in (("extract", "core/extract.py"), ("details", "core/details.py"),
                               ("judge", "judge.py"), ("context_refine", "refine.py")):
            spec = importlib.util.spec_from_file_location(name, cls.root / relative)
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
            setattr(cls, "refine" if name == "context_refine" else name, module)

    @classmethod
    def tearDownClass(cls):
        sys.path[:] = cls.old_path
        for name, previous in cls.old_modules.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous
        sys.modules.pop("context_refine", None)
        cls.temp.cleanup()

    def setUp(self):
        self.data = Path(tempfile.mkdtemp(prefix="case-", dir=self.temp.name))
        self.cfg = copy.deepcopy(self.defaults)
        self.cfg.update(owner="Synthetic", teamsSelfNames=["Synthetic"],
                        collection={"aiContextChars": 800}, projects=[])
        (self.root / "config/config.json").write_text(json.dumps(self.cfg), encoding="utf-8")

    def write(self, relative, rows, base=None):
        path = (base or self.data) / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        fields = list(dict.fromkeys(key for row in rows for key in row))
        with path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        return path

    @staticmethod
    def teams(**values):
        return {"time": "2026-09-07 10:00", "from": "Synthetic", "chat": "Design room",
                "kind": "sent", "summary": "Synthetic design review", **values}

    @staticmethod
    def mail(**values):
        return {"box": "sent", "time": "2026-09-07 09:00", "sender": "Synthetic",
                "subject": "Synthetic review", "conversation": "Synthetic review", "rcv": "",
                "time_precision": "minute", **values}

    def signals(self, end=DAY):
        return self.extract.load_signals(str(self.data), DAY, end,
                                         exclude=self.cfg["excludePathKeywords"], cfg=self.cfg)

    def test_different_chat_day_and_source_id_never_collapse(self):
        rows = [self.teams(source_id="message-1", conversation_id="chat-1"),
                self.teams(source_id="message-2", conversation_id="chat-1"),
                self.teams(source_id="message-1", conversation_id="chat-2"),
                self.teams(chat="Legacy room one"), self.teams(chat="Legacy room two"),
                self.teams(chat="Legacy room one", time="2026-09-08 10:00")]
        self.write("m365/teams_web.csv", rows)
        signals, meta = self.signals(date(2026, 9, 8))
        self.assertEqual(len(signals), 6)
        self.assertEqual(len(meta["signal_contexts"]), 6)

    def test_same_prefix_different_body_is_preserved_without_id(self):
        prefix = "identical beginning " * 10
        self.write("m365/teams_web.csv", [self.teams(summary=prefix + "decision A"),
                                           self.teams(summary=prefix + "decision B")])
        self.assertEqual(len(self.signals()[0]), 2)

    def test_same_identity_merges_cross_pc_and_keeps_richer_context_in_any_order(self):
        for rich_first in (True, False):
            rich = self.teams(source_id="chat-1/message-1", conversation_id="chat-1",
                              context_excerpt="Retained detailed evidence", source_url="https://example.invalid/message")
            sparse = self.teams(source_id="chat-1/message-1", conversation_id="chat-1")
            self.write("m365/teams_chats.csv", [rich if rich_first else sparse])
            self.write("추가PC/PC-B/m365/teams_web.csv", [sparse if rich_first else rich])
            signals, meta = self.signals()
            self.assertEqual(len(signals), 1)
            self.assertEqual(meta["signal_contexts"][0]["context_excerpt"], rich["context_excerpt"])
            self.assertEqual(meta["signal_contexts"][0]["source_url"], rich["source_url"])

    def test_context_stays_aligned_after_sort_and_preserves_legacy_tuple_shape(self):
        self.write("m365/teams_web.csv", [self.teams(time="2026-09-07 11:00", source_id="later", context_excerpt="Later"),
                                           self.teams(time="2026-09-07 08:00", source_id="earlier", context_excerpt="Earlier")])
        signals, meta = self.signals()
        self.assertEqual([len(signal) for signal in signals], [5, 5])
        self.assertEqual([x["source_id"] for x in meta["signal_contexts"]], ["earlier", "later"])
        self.assertEqual([x[0].hour for x in signals], [8, 11])

    def test_uncertain_teams_times_keep_content_but_cannot_create_work_hours(self):
        rows = [self.teams(source_id="uncertain-" + str(i), kind=kind, time_precision=precision,
                           time="2026-09-07 " + clock, context_excerpt="Keep classification evidence")
                for i, (kind, precision, clock) in enumerate([
                    ("sent", "estimated", "09:00"), ("order", "ai_reported", "12:10"),
                    ("msg", "date", "18:15"), ("sent", "ai_reported", "21:00")])]
        self.write("m365/teams_web.csv", rows)
        self.write("pc/pc_on.csv", [{"date": DAY.isoformat(), "on_hours": 10, "first_on": "09:00",
                                     "last_off": "20:00", "night_hours": 1, "weekend": 0}])
        signals, meta = self.signals()
        self.assertEqual(len(signals), 4)
        self.assertTrue(all(s[1] in self.extract.CONTEXT_ONLY_TIME_SOURCES and s[3] > 0 for s in signals))
        self.assertTrue(all(c["context_excerpt"] == "Keep classification evidence" for c in meta["signal_contexts"]))
        now = datetime(2026, 9, 30, 23, 59)
        baseline, _ = self.extract.day_work_hours(str(self.data), [], DAY, DAY, self.cfg, now, {})
        hours, info = self.extract.day_work_hours(str(self.data), signals, DAY, DAY, self.cfg, now, {})
        self.assertEqual(hours, baseline)
        self.assertEqual(info["unverified_time_signals"], 4)
        # Even a custom per-source duration cannot turn an unverified time into a session.
        spans, _ = self.extract._signal_spans(signals, DAY, DAY,
                                              {s[1]: 120 for s in signals}, now=now)
        self.assertEqual(spans, {})
        precise = [(datetime(2026, 9, 7, 10), "팀즈(발신)", "Verified message", 1, "Synthetic")]
        expected, _ = self.extract.day_work_hours(str(self.data), precise, DAY, DAY, self.cfg, now, {})
        mixed, _ = self.extract.day_work_hours(str(self.data), precise + signals, DAY, DAY, self.cfg, now, {})
        self.assertEqual(mixed, expected)  # No invented lunch trace, evening or night extension.

    def test_exact_same_message_can_upgrade_uncertain_time_in_either_file_order(self):
        for exact_first, precision in ((False, "minute"), (True, "minute"), (False, ""), (True, "")):
            exact = self.teams(source_id="same-message", conversation_id="room", time_precision=precision)
            uncertain = self.teams(source_id="same-message", conversation_id="room", time_precision="estimated",
                                   time="2026-09-07 02:00", context_excerpt="Richer classification evidence")
            self.write("m365/teams_chats.csv", [exact if exact_first else uncertain])
            self.write("추가PC/PC-B/m365/teams_web.csv", [uncertain if exact_first else exact])
            signals, meta = self.signals()
            self.assertEqual(len(signals), 1)
            self.assertEqual((signals[0][0].hour, signals[0][1]), (10, "팀즈(발신)"))
            self.assertEqual(meta["signal_contexts"][0]["time_precision"], precision)
            self.assertEqual(meta["signal_contexts"][0]["context_excerpt"], uncertain["context_excerpt"])

    def test_unverified_times_do_not_trigger_timezone_warning_or_rejudge_hours(self):
        rows = [self.teams(source_id=str(i), time=f"2026-09-07 02:0{i}", time_precision="ai_reported")
                for i in range(5)]
        self.write("m365/teams_copilot.csv", rows)
        self.assertFalse(self.extract._utc_suspect(str(self.data), DAY, DAY))
        # Older saved signal labels may lack the new suffix; rejudging must still
        # honor the stored precision rather than creating a night session.
        kept = [{"time": row["time"], "source": "팀즈(발신)", "text": row["summary"],
                 "weight": 1, "who": "Synthetic", "time_precision": row["time_precision"]}
                for row in rows]
        result = self.extract.rehours_after_judge(str(self.data), kept, [], DAY, DAY, self.cfg)
        self.assertEqual(result["total_mm"], 0)
        self.assertEqual(result["info"]["unverified_time_signals"], 5)
        for row in rows:
            row["time_precision"] = "minute"
        self.write("m365/teams_copilot.csv", rows)
        self.assertTrue(self.extract._utc_suspect(str(self.data), DAY, DAY))

    def test_guessed_outside_date_cannot_hide_valid_copy_or_move_signal_outside_query(self):
        exact = self.teams(source_id="same-message", conversation_id="room", time_precision="minute")
        uncertain = self.teams(source_id="same-message", conversation_id="room", time_precision="estimated",
                               time="2026-09-08 10:00")
        for outside_first in (True, False):
            self.write("m365/teams_chats.csv", [uncertain if outside_first else exact])
            self.write("추가PC/PC-B/m365/teams_web.csv", [exact if outside_first else uncertain])
            signals, _ = self.signals()
            self.assertEqual(len(signals), 1)
            self.assertEqual((signals[0][0].date(), signals[0][1]), (DAY, "팀즈(발신)"))
        exact["time"], uncertain["time"] = uncertain["time"], exact["time"]
        self.write("m365/teams_chats.csv", [uncertain])
        self.write("추가PC/PC-B/m365/teams_web.csv", [exact])
        signals, _ = self.signals()
        self.assertEqual(signals[0][0].date(), DAY)
        self.assertIn(signals[0][1], self.extract.CONTEXT_ONLY_TIME_SOURCES)

    def test_legacy_mail_cross_pc_and_date_precision_dedup_is_preserved(self):
        self.write("outlook/mail.csv", [self.mail()])
        self.write("추가PC/PC-B/outlook/mail.csv", [self.mail(), self.mail(time_precision="date", time="2026-09-07")])
        signals, meta = self.signals()
        self.assertEqual(len(signals), 1)
        self.assertEqual(meta["excluded"]["중복(같은 메일의 정확한 시각 사본 있음)"], 1)

    def test_date_only_duplicate_can_enrich_precise_copy_without_changing_time(self):
        self.write("outlook/mail.csv", [self.mail(time_precision="date", time="2026-09-07", source_id="known-message",
                                                  context_excerpt="Recovered rich evidence")])
        self.write("추가PC/PC-B/outlook/mail.csv", [self.mail(source_id="known-message")])
        signals, meta = self.signals()
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0][0].hour, 9)
        self.assertEqual(meta["signal_contexts"][0]["context_excerpt"], "Recovered rich evidence")

    def test_mail_source_ids_and_long_context_fallback_separate_same_minute_subject(self):
        self.write("outlook/mail.csv", [self.mail(source_id="one"), self.mail(source_id="two"),
                                       self.mail(context_excerpt="Prefix " * 30 + "result A"),
                                       self.mail(context_excerpt="Prefix " * 30 + "result B")])
        self.assertEqual(len(self.signals()[0]), 4)

    def test_context_limit_and_private_supplement_never_leaks_through_duplicate(self):
        self.write("m365/teams_web.csv", [self.teams(source_id="long", context_excerpt="x" * 4500),
                                           self.teams(source_id="private"),
                                           self.teams(source_id="private", context_excerpt="PRIVATE_TOKEN in supplement")])
        signals, meta = self.extract.load_signals(str(self.data), DAY, DAY, exclude=["PRIVATE_TOKEN"], cfg=self.cfg)
        self.assertEqual(len(signals), 2)
        contexts = {x["source_id"]: x for x in meta["signal_contexts"]}
        self.assertEqual(len(contexts["long"]["context_excerpt"]), 4000)
        self.assertEqual(contexts["long"]["context_truncated"], "true")
        self.assertEqual(contexts["private"]["context_excerpt"], "")

    def test_default_privacy_filter_withholds_footer_without_dropping_safe_signals(self):
        private_body = "Design review. PRIVATE_BODY_MARKER 개인정보 처리 안내"
        self.assertIn("개인", self.cfg["excludePathKeywords"])
        self.write("outlook/mail.csv", [self.mail(source_id="safe-mail", context_excerpt=private_body),
                                        self.mail(source_id="private-mail", subject="개인 일정", context_excerpt="Safe body")])
        self.write("m365/teams_web.csv", [self.teams(source_id="safe-chat", context_excerpt=private_body),
                                           self.teams(source_id="private-chat", summary="개인 일정", context_excerpt="Safe body")])
        signals, meta = self.signals()
        self.assertEqual(len(signals), 2)
        self.assertEqual(meta["excluded"]["개인정보필터"], 2)
        self.assertEqual(dict(meta["context_filtered"]), {"메일": 1, "팀즈": 1})
        self.assertTrue(all(c["context_excerpt"] == "" and c["context_filtered"] == "true"
                            and c["context_truncated"] == "false" for c in meta["signal_contexts"]))
        for context in meta["signal_contexts"]:
            preview = self.extract.context_preview(context)
            self.assertIn("문맥 제외(보호 필터)", preview)
            self.assertNotIn("PRIVATE_BODY_MARKER", preview)
        poisoned = {"context_excerpt": private_body, "context_filtered": "true"}
        self.assertNotIn("PRIVATE_BODY_MARKER", self.extract.context_preview(poisoned))

    def test_filtered_duplicate_never_overwrites_safe_context_or_bypasses_private_title(self):
        private_body = "PRIVATE_BODY_MARKER 개인정보 처리 안내"
        for safe_body in ("Verified design decision", ""):
            for private_first in (True, False):
                safe = self.teams(source_id="same-chat", context_excerpt=safe_body)
                filtered = self.teams(source_id="same-chat", context_excerpt=private_body)
                self.write("m365/teams_web.csv", [filtered if private_first else safe])
                self.write("추가PC/PC-B/m365/teams_web.csv", [safe if private_first else filtered,
                    self.teams(source_id="same-chat", summary="개인 일정", kind="order", context_excerpt="MUST_NOT_MERGE")])
                signals, meta = self.signals()
                self.assertEqual(len(signals), 1)
                self.assertEqual(signals[0][1], "팀즈(발신)")
                context = meta["signal_contexts"][0]
                self.assertEqual(context["context_excerpt"], safe_body)
                self.assertEqual(context["context_filtered"], "" if safe_body else "true")
                self.assertEqual(meta["excluded"]["개인정보필터"], 1)
                self.assertNotIn("PRIVATE_BODY_MARKER", self.extract.context_preview(context))
                self.assertNotIn("MUST_NOT_MERGE", self.extract.context_preview(context))
        self.write("outlook/mail.csv", [self.mail(source_id="same-mail", time_precision="date",
                    time="2026-09-07", context_excerpt=private_body)])
        self.write("추가PC/PC-B/outlook/mail.csv", [self.mail(source_id="same-mail", context_excerpt="Verified design decision")])
        signals, meta = self.signals()
        mail = next(c for c in meta["signal_contexts"] if c["source_id"] == "same-mail")
        self.assertEqual(mail["context_excerpt"], "Verified design decision")
        self.assertNotEqual(mail["context_filtered"], "true")
        self.write("outlook/mail.csv", [self.mail(source_id="same-mail", time_precision="date",
                    time="2026-09-07", subject="개인 일정", context_excerpt="MUST_NOT_MERGE")])
        self.write("추가PC/PC-B/outlook/mail.csv", [self.mail(source_id="same-mail")])
        _signals, meta = self.signals()
        mail = next(c for c in meta["signal_contexts"] if c["source_id"] == "same-mail")
        self.assertEqual(mail["context_excerpt"], "")

    def test_production_mine_judge_refine_keep_safe_signal_and_do_not_send_filtered_body(self):
        private_body = "Design evidence. PRIVATE_BODY_MARKER 개인정보 처리 안내"
        self.write("outlook/mail.csv", [self.mail(source_id="mail", context_excerpt=private_body)])
        self.write("m365/teams_web.csv", [self.teams(source_id="chat", context_excerpt=private_body)])
        result = subprocess.run([sys.executable, "-B", str(self.root / "mine.py"), str(self.data),
                                 "--from", DAY.isoformat(), "--to", DAY.isoformat()],
                                cwd=self.root, capture_output=True, text=True, encoding="utf-8",
                                env={**os.environ, "PYTHONUTF8": "1"}, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("안전한 제목·요약 신호는 유지", result.stdout)
        meta = json.loads((self.root / "report" / f"mm_meta_{TAG}.json").read_text("utf-8"))
        self.assertEqual(meta["signals"], 2)
        self.assertEqual(meta["context_filtered"], {"메일": 1, "팀즈": 1})
        prompts = []
        def sender(prompt, _tag, name, **_kwargs):
            prompts.append(prompt)
            if name in ("taxonomy", "consolidate"):
                return {"ok": True, "reply": json.dumps({"models": [{"name": "Demo", "match": ["demo"], "obs": "Synthetic"}]})}
            ids = [int(x) for x in re.findall(r"^#(\d+) \|", prompt, re.M)]
            return {"ok": True, "reply": json.dumps({"j": [[i, "y", "Demo", "협업", "Review"] for i in ids]})}
        with mock.patch.object(self.judge, "copilot_send", sender), mock.patch.object(sys, "argv", [
                "judge.py", "--from", DAY.isoformat(), "--to", DAY.isoformat(), "--no-narrate"]), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.judge.main(), 0)
        self.assertTrue(prompts)
        self.assertNotIn("PRIVATE_BODY_MARKER", "\n".join(prompts))
        with (self.root / "report" / f"signals_{TAG}.csv").open(encoding="utf-8-sig") as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r["context_filtered"] == "true" and r["context_excerpt"] == "" for r in rows))
        evidence, judged = self.refine.load_signal_evidence(str(self.root / "report"), TAG)
        self.assertTrue(judged)
        evidence_text = "\n".join(line for lines in evidence.values() for line in lines)
        self.assertNotIn("PRIVATE_BODY_MARKER", evidence_text)
        self.assertIn("문맥 제외(보호 필터)", evidence_text)
        _cleaned, dropped, _hits = self.refine.sanitize_evidence(evidence_text, self.cfg["excludePathKeywords"])
        self.assertEqual(dropped, 0)

    def test_new_evidence_ids_are_scoped_and_old_ids_remain_byte_identical(self):
        row = {"time": "2026-09-07 10:00", "source": "팀즈(발신)", "text": "identical", "who": "Synthetic"}
        legacy = self.details.stable_id("sig", TAG, *(row.get(k) for k in
                   ("time", "source", "text", "who", "weight", "model", "project", "detail", "activity")))
        self.assertEqual(self.details.stable_signal_id(row, TAG), legacy)
        self.assertEqual(self.details.stable_signal_id({**row, "source_id": "", "context_excerpt": ""}, TAG), legacy)
        self.assertNotEqual(self.details.stable_signal_id({**row, "source_id": "one"}, TAG),
                            self.details.stable_signal_id({**row, "source_id": "two"}, TAG))
        self.assertNotEqual(self.details.stable_signal_id({**row, "context_excerpt": "shared start decision A"}, TAG),
                            self.details.stable_signal_id({**row, "context_excerpt": "shared start decision B"}, TAG))

    def test_prompt_samples_beginning_middle_and_end_and_marks_missing_context(self):
        text = "START_EVIDENCE " + "a" * 1950 + " MIDDLE_EVIDENCE " + "b" * 1950 + " END_DECISION"
        row = {"context_excerpt": text, "context_truncated": "true", "source_kind": "teams-web"}
        preview = self.extract.context_preview(row, 800)
        for marker in ("START_EVIDENCE", "MIDDLE_EVIDENCE", "END_DECISION", "생략"):
            self.assertIn(marker, preview)
        self.assertEqual(row["context_excerpt"], text)
        self.assertIn("본문 미수집", self.extract.context_preview({"source_kind": "mail-com"}))
        self.assertEqual(self.extract.collection_ai_chars({"collection": {"aiContextChars": "bad"}}), 800)

    def test_judge_context_changes_chunk_sizes_and_actual_oversized_prompt_splits(self):
        row = {"time": "2026-09-07 10:00", "source": "팀즈(발신)", "text": "Snippet", "who": "Synthetic",
               "context_excerpt": "Evidence " * 400, "source_id": "one", "_ai_context_chars": 800}
        rows = [dict(row, source_id=str(i)) for i in range(30)]
        models = [{"name": "Demo"}]
        head_len = len(self.judge.judge_prompt([], 0, models)) + self.judge.SEEN_MAX_CHARS + 160
        plan = self.judge.pack_chunks(rows, 40, head_len)
        self.assertGreater(len(plan), 1)
        self.assertEqual(sum(n for _start, n in plan), 30)
        for start, n in plan:
            self.assertLessEqual(len(self.judge.judge_prompt(rows[start:start + n], start, models)), self.judge.PROMPT_BUDGET)
        calls = []
        def sender(prompt, *_args):
            calls.append(prompt)
            ids = [int(x) for x in re.findall(r"^#(\d+) \|", prompt, re.M)]
            return {"ok": True, "reply": json.dumps({"j": [[i, "y", "Demo", "협업", "Review"] for i in ids]})}
        stats = {"roundtrips": 0, "repaired": 0, "retries": 0, "failed_rows": 0,
                 "omitted_rows": 0, "notes": [], "last_err": "", "soft": False}
        with mock.patch.object(self.judge, "copilot_send", sender):
            judged = self.judge.judge_rows(range(30), rows, models, [], TAG, "test", 0, stats)
        self.assertEqual(len(judged), 30)
        self.assertGreater(len(calls), 1)
        self.assertTrue(all(len(prompt) <= self.judge.PROMPT_BUDGET for prompt in calls))

    def test_refine_distributes_evidence_budget_and_uses_rich_context(self):
        rows = [{"time": "2026-09-07 10:00", "source": "팀즈(발신)", "text": "Short",
                 "model": f"Task{i}", "detail": "Review", "context_excerpt": "Start " + "x" * 3500 + " Decision at end",
                 "source_id": str(i), "source_kind": "teams-web"} for i in range(10)]
        report = self.data / "report"
        self.write(f"report/signals_{TAG}.csv", rows)
        evidence, judged = self.refine.load_signal_evidence(str(report), TAG)
        self.assertTrue(judged)
        self.assertIn("Decision at end", evidence[("Task0", "Review")][0])
        chunks = [(i, {"Level 2": f"Task{i}", "Level 3": "Review"}) for i in range(10)]
        excerpt, hits = self.refine.slice_for_chunk(evidence, chunks, cap=2500)
        self.assertEqual(hits, 10)
        self.assertLessEqual(len(excerpt), 2500)
        for i in range(10):
            self.assertIn(f"## #{i} Task{i}", excerpt)
        self.assertIn("생략", excerpt)

    def test_refine_splits_real_prompts_before_discarding_context_for_later_tasks(self):
        evidence = {(f"Task{i}", "Review"): ["- Synthetic evidence " + "x" * 800 + " tail decision"] for i in range(20)}
        chunks = [(i, {"Level 2": f"Task{i}", "Level 3": "Review", "share": .05}) for i in range(20)]
        calls = []
        def sender(prompt, *_args, **_kwargs):
            calls.append(prompt)
            ids = [int(x) for x in re.findall(r"^  #(\d+)", prompt, re.M)]
            return {"ok": True, "reply": json.dumps({"items": [
                {"m": [i], "l1": "기술 내재화", "l2": f"Task{i}", "l3": "Review", "a": "회의·협업",
                 "d": "Synthetic evidence review", "w": True} for i in ids]})}
        refiner = self.refine.Refiner(TAG, str(self.root / "report"), evidence, "", [], say=lambda *_args: None)
        with mock.patch.object(self.refine, "copilot_send", sender):
            refiner.run(chunks, set(), "case")
        self.assertGreater(len(calls), 1)
        self.assertTrue(all(len(prompt) <= self.refine.PROMPT_BUDGET for prompt in calls))
        self.assertEqual(len(refiner.items), 20)
        self.assertTrue(all("tail decision" in prompt for prompt in calls))

    def test_mine_and_judge_roundtrip_preserves_context_while_display_stays_short(self):
        context = "START_EVIDENCE " + "x" * 3000 + " END_DECISION"
        self.write("m365/teams_web.csv", [self.teams(summary="s" * 200, context_excerpt=context,
                   context_truncated="true", source_id="chat/msg", conversation_id="chat", source_kind="teams-web")])
        result = subprocess.run([sys.executable, "-B", str(self.root / "mine.py"), str(self.data),
                                 "--from", DAY.isoformat(), "--to", DAY.isoformat()],
                                cwd=self.root, capture_output=True, text=True, encoding="utf-8",
                                env={**os.environ, "PYTHONUTF8": "1"}, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        path = self.root / "report" / f"signals_{TAG}.csv"
        with path.open(encoding="utf-8-sig") as stream:
            before = list(csv.DictReader(stream))
        self.assertEqual(len(before), 1)
        self.assertEqual(len(before[0]["text"]), 100)
        self.assertEqual(before[0]["context_excerpt"], context)
        def sender(prompt, _tag, name, **_kwargs):
            if name in ("taxonomy", "consolidate"):
                return {"ok": True, "reply": json.dumps({"models": [{"name": "Demo", "match": ["demo"], "obs": "Synthetic"}]})}
            ids = [int(x) for x in re.findall(r"^#(\d+) \|", prompt, re.M)]
            return {"ok": True, "reply": json.dumps({"j": [[i, "y", "Demo", "협업", "Review"] for i in ids]})}
        with mock.patch.object(self.judge, "copilot_send", sender), mock.patch.object(sys, "argv", [
                "judge.py", "--from", DAY.isoformat(), "--to", DAY.isoformat(), "--no-narrate"]), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.judge.main(), 0)
        with path.open(encoding="utf-8-sig") as stream:
            after = list(csv.DictReader(stream))
        for field in self.extract.COLLECTION_CONTEXT_FIELDS:
            self.assertEqual(after[0][field], before[0][field], field)
        self.assertEqual(len(after[0]["text"]), 100)


if __name__ == "__main__":
    unittest.main()
