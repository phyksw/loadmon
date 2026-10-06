# -*- coding: utf-8 -*-
"""WP-32 analyze — 전체 흐름(단계 10종 → run_status.json · current.json · 결과 파일), 인자 검사, 기록 없음(rc 4),
달력 미확인 연도 거부, 키링 없음, 보관 정리, 결과 선택(choose_current). 합성 번들(WP-05 생성기)만 쓴다."""
import io
import json
import re
import unittest
from collections import Counter
from datetime import UTC, datetime

from lm27.paths import Paths
from lm27.pipeline import analyze as A
from lm27.pipeline import stages as S
from lm27.time.calendar import SLOT, d_of
from lm27.util import events
from tests.core.test_stage_result import check_stage_common
from tests.fixtures.wp32 import world as W

UTC_RX = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
OFF_RX = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$")


def quiet():
    events.configure(mode="off")


def loud():
    events.configure(mode="text")


def jsonl(buf: io.StringIO) -> list[dict]:
    return [json.loads(x) for x in buf.getvalue().splitlines() if x.strip()]


class FullRunTest(unittest.TestCase):
    """한 번 돌린 결과를 여러 면에서 본다(--no-ai — 규칙 라벨로 완주)."""

    @classmethod
    def setUpClass(cls):
        cls.w = W.World()
        cls.rows = W.rows()
        cls.w.put(cls.rows)
        cls.w.keyring()
        buf = io.StringIO()
        events.configure(mode="jsonl", stream=buf, reset_seq=True)
        try:
            cls.rc = cls.w.analyze()
        finally:
            quiet()
        cls.events = jsonl(buf)
        cls.st = cls.w.status()

    @classmethod
    def tearDownClass(cls):
        loud()
        cls.w.remove()

    def test_rc_state_current(self):
        self.assertEqual(self.rc, 0)
        st = self.st
        self.assertEqual((st["schema"], st["state"], st["rc"], st["reason"]), (A.SCHEMA, "done", 0, None))
        self.assertEqual((st["from"], st["to"]), (W.D0, W.D1))
        self.assertEqual(st["as_of"], W.AS_OF)
        self.assertTrue(UTC_RX.match(st["started"]) and UTC_RX.match(st["ended"]))
        self.assertIs(st["current"], True)
        self.assertIs(st["ai"], False)
        self.assertEqual(st["period_source"], "user")
        self.assertIsNone(st["rerun_of"])
        self.assertIsInstance(st["pid"], int)
        self.assertEqual(st["calendar"]["source"], "file")
        self.assertTrue(st["calendar"]["version"])
        self.assertEqual(st["registry"]["source"], "builtin")
        cur = self.w.current()
        self.assertEqual(cur["schema"], A.CURRENT_SCHEMA)
        self.assertEqual((cur["run_id"], cur["chosen"], cur["from"], cur["to"], cur["as_of"]),
                         (self.w.last, "auto", W.D0, W.D1, W.AS_OF))
        self.assertEqual(cur["report_version"], "report/1")
        self.assertTrue(OFF_RX.match(cur["built_at"]) and OFF_RX.match(cur["chosen_at"]))
        self.assertEqual(A.read_current(self.w.paths)["run_id"], self.w.last)
        self.assertEqual(A.read_run_status(self.w.paths, self.w.last)["run_id"], self.w.last)

    def test_stage_rows_common_fields(self):
        """계약 §8.5 분석 행 = lm27.stage/1 공통 필드 + id·name_ko(check_stage_common 대조)."""
        stages = self.st["stages"]
        self.assertEqual([s["id"] for s in stages], list(S.STAGE_IDS))
        for s in stages:
            self.assertEqual(check_stage_common(s), [], s["id"])
            self.assertEqual(s["stage"], s["id"])
            self.assertEqual(s["run_id"], self.w.last)
            self.assertEqual(s["name_ko"], S.name_ko(s["id"]))
            self.assertLessEqual(len(s["hint"]), 200)
        by = {s["id"]: s for s in stages}
        for sid in S.AI_STAGES:
            self.assertEqual((by[sid]["state"], by[sid]["reason"]), ("skipped", "ai_off"), sid)
            self.assertEqual(by[sid]["reason_ko"], "AI 끔")
        for sid in ("load", "normalize", "classify", "time", "mining", "review", "report"):
            self.assertEqual(by[sid]["state"], "done", sid)
            self.assertEqual(by[sid]["rc"], 0)

    def test_counts(self):
        by = {s["id"]: s for s in self.st["stages"]}
        load = by["load"]["counts"]
        self.assertEqual(load["records"], len(self.rows))
        self.assertEqual(load["in_period"], len(self.rows))
        self.assertEqual(sum(load["by_kind"].values()), len(self.rows))
        self.assertGreater(by["classify"]["counts"]["units"], 0)
        self.assertEqual(by["classify"]["counts"]["task_label_items"], 0, "--no-ai: task_label ai_in 없음")
        tc = by["time"]["counts"]
        self.assertGreater(tc["env_min"], 0)
        self.assertEqual(tc["files"], len(W.TIME_FILES) + len(W.HIER_FILES))
        self.assertEqual(by["mining"]["counts"]["written"], 0, "AI 끔이면 ai_in 을 쓰지 않는다")
        self.assertFalse(self.w.paths.ai_in("workflow_label").exists())
        self.assertFalse(self.w.paths.ai_in("task_label").exists())

    def test_result_files(self):
        for name in W.TIME_FILES:
            self.assertTrue(self.w.paths.analysis_time_file(self.w.last, name).is_file(), name)
        for name in W.HIER_FILES:
            self.assertTrue(self.w.paths.analysis_hier_file(self.w.last, name).is_file(), name)
        meta = json.loads(self.w.time_bytes("run_meta.json"))
        self.assertEqual(meta["core_version"], "timecore/1.1")
        self.assertTrue(meta["as_of"].startswith("2026-09-12T09:00:00"))
        model = json.loads(self.w.model_bytes())
        self.assertIsInstance(model, dict)
        labels = json.loads(self.w.hier_bytes("labels.json"))
        tasks = json.loads(self.w.time_bytes("tasks.json"))
        self.assertEqual(set(labels), {t["unit_id"] for t in tasks}, "H-I1: 단위업무마다 라벨 하나")
        for lb in labels.values():
            self.assertFalse(any(str(v).startswith("ai") for v in (lb.get("src") or {}).values()),
                             "--no-ai = 규칙 라벨(T-H16)")

    def test_conservation_in_files(self):
        """T-01(실분석 결과 파일): 날마다 Σ귀속 초 = 300 × 봉투 슬롯."""
        env = Counter()
        for ln in self.w.time_bytes("env_slots.jsonl").decode("utf-8").splitlines():
            env[json.loads(ln)["date"]] += SLOT
        att = Counter()
        for ln in self.w.time_bytes("attrib.jsonl").decode("utf-8").splitlines():
            r = json.loads(ln)
            att[d_of(r["slot"] * SLOT).isoformat()] += r["sec"]
        self.assertTrue(env)
        self.assertEqual(env, att)

    def test_events(self):
        evs = self.events
        self.assertEqual([e["ev"] for e in evs][-1], "result")
        starts = [e["stage"] for e in evs if e["ev"] == "stage_start"]
        ends = [e for e in evs if e["ev"] == "stage_end"]
        self.assertEqual(starts, ["load", "normalize", "classify", "time", "mining", "review", "report"])
        self.assertEqual([e["stage"] for e in ends], starts)
        self.assertTrue(all(e["state"] == "done" and e["name_ko"] for e in ends))
        res = evs[-1]
        self.assertEqual((res["run_id"], res["rc"], res["state"], res["current"]), (self.w.last, 0, "done", True))
        self.assertEqual(sorted(e["seq"] for e in evs), [e["seq"] for e in evs])
        self.assertTrue(any(e["ev"] == "notice" for e in evs))

    def test_last_result(self):
        lr = A.last_result()
        self.assertEqual(lr["run_id"], self.w.last)
        self.assertEqual(lr["stages"]["report"], "done")


class ArgsTest(unittest.TestCase):
    """인자 오류는 실행 폴더를 만들지 않고 rc 1(한국어 한 줄)."""

    def setUp(self):
        quiet()
        self.addCleanup(loud)
        self.w = W.World()
        self.addCleanup(self.w.remove)

    def no_runs(self):
        self.assertFalse(self.w.paths.analysis_current().parent.exists(), "실행 폴더를 만들지 않는다")

    def check(self, **kw):
        rc = A.analyze(self.w.paths, self.w.cfg(), **{"now": W.NOW, "team_client": None, "copilot_role": True, **kw})
        self.assertEqual(rc, 1, kw)
        self.no_runs()
        return A.last_result()

    def test_bad_args(self):
        self.check(to=W.D1)
        self.check(from_=W.D1, to=W.D0)
        self.check(from_="2026-9-1", to=W.D1)
        self.check(from_=W.D0, to=W.D1, as_of="2026-09-20T09:00:00+09:00")          # 지금(09-14)보다 늦음
        self.check(from_=W.D0, to=W.D1, as_of="2026-08-01T09:00:00+09:00")          # 시작일보다 앞섬
        self.check(from_=W.D0, to=W.D1, as_of="어제")
        self.check(from_=W.D0, to=W.D1, stages=["nope"])
        self.check(from_=W.D0, to=W.D1, stages=["report"])                           # --rerun 없이 사슬 밖만
        self.check(rerun="20260901-090000-abcd", stages=["report"])                  # 없는 실행
        self.assertEqual(A.last_result()["reason"], "rerun_missing")
        self.check(from_=W.D0, to=W.D1, run_id="bad")
        self.w.paths.analysis("20260914-090000-0001").mkdir(parents=True)
        rc = A.analyze(self.w.paths, self.w.cfg(), from_=W.D0, to=W.D1, now=W.NOW, team_client=None,
                       copilot_role=True, run_id="20260914-090000-0001")
        self.assertEqual(rc, 1, "이전 실행 폴더를 덮지 않는다")

    def test_paths_method_missing(self):
        """분석 폴더 하위 경로 메서드(CR)가 없는 Paths 면 실행을 만들지 않고 rc 1."""
        plain = Paths(self.w.root, lad=self.w.lad)
        rc = A.analyze(plain, self.w.cfg(), from_=W.D0, to=W.D1, now=W.NOW, team_client=None, copilot_role=True)
        self.assertEqual(rc, 1)
        self.assertEqual(A.last_result()["reason"], "paths_method_missing")
        self.no_runs()

    def test_as_of_forms(self):
        now = datetime(2026, 9, 14, 0, 0, tzinfo=UTC)
        self.assertEqual(A._parse_as_of(None, now, 540), now)
        self.assertEqual(A._parse_as_of("2026-09-12", now, 540), datetime(2026, 9, 12, 14, 59, 59, tzinfo=UTC))
        self.assertEqual(A._parse_as_of("2026-09-14", now, 540), now, "그날 끝이 지금보다 늦으면 지금")
        self.assertEqual(A._parse_as_of("2026-09-12T18:00:00", now, 540), datetime(2026, 9, 12, 9, 0, tzinfo=UTC))
        self.assertEqual(A._parse_as_of("2026-09-12T09:00:00Z", now, 540), datetime(2026, 9, 12, 9, 0, tzinfo=UTC))
        with self.assertRaises(ValueError):
            A._parse_as_of("2026-09-14T09:10:00+09:00", now, 540)


class NoRecordsTest(unittest.TestCase):
    def setUp(self):
        quiet()
        self.addCleanup(loud)
        self.w = W.World()
        self.addCleanup(self.w.remove)
        self.w.keyring()

    def test_empty_bundle_rc4(self):
        rc = self.w.analyze()
        self.assertEqual(rc, 4)
        st = self.w.status()
        self.assertEqual((st["state"], st["rc"], st["reason"], st["current"]), ("done", 4, "no_records", False))
        load = self.w.stage("load")
        self.assertEqual((load["state"], load["reason"], load["counts"]["records"]), ("done", "no_records", 0))
        for s in st["stages"][1:]:
            want = "ai_off" if s["id"] in S.AI_STAGES else "no_records"       # 계획상 건너뜀이 먼저
            self.assertEqual((s["state"], s["reason"]), ("skipped", want), s["id"])
            self.assertEqual(check_stage_common(s), [])
        self.assertIsNone(self.w.current())

    def test_records_outside_period(self):
        self.w.put(W.rows("2026-09-21", "2026-09-25"))
        self.assertEqual(self.w.analyze(), 4)
        self.assertEqual(self.w.stage("load")["counts"]["in_period"], 0)


class RefusalTest(unittest.TestCase):
    def setUp(self):
        quiet()
        self.addCleanup(loud)
        self.w = W.World()
        self.addCleanup(self.w.remove)
        self.w.put(W.rows())

    def test_calendar_unknown_year_keeps_previous(self):
        """T-13 · 계약 §3.21: 달력에 없는 해가 섞이면 분석 거부(rc 1) — 이전 결과(current.json)는 그대로."""
        self.w.keyring()
        self.assertEqual(self.w.analyze(), 0)
        good = self.w.last
        rc = self.w.analyze(from_="2028-01-03", to="2028-01-14", as_of="2028-01-15T09:00:00+09:00",
                            now=datetime(2028, 1, 16, tzinfo=UTC))
        self.assertEqual(rc, 1)
        st = self.w.status()
        self.assertEqual((st["state"], st["reason"], st["year"], st["years"]), ("failed", "calendar_unknown_year",
                                                                                  2028, [2028]))
        self.assertIn("2028년", st["hint"])
        self.assertEqual(st["reason_ko"], "달력 미확인 연도")
        for s in st["stages"]:
            self.assertEqual((s["state"], s["reason"]), ("skipped", "calendar_unknown_year"), s["id"])
            self.assertEqual(check_stage_common(s), [])
        self.assertEqual(self.w.current()["run_id"], good, "성공 전 무효화 금지")
        self.assertFalse(self.w.paths.analysis_time_file(self.w.last, "team_tables.json").exists())
        with self.assertRaises(ValueError):
            A.choose_current(self.w.paths, self.w.cfg(), self.w.last)        # 보고서까지 끝나지 않은 실행

    def test_no_keyring(self):
        rc = self.w.analyze()
        self.assertEqual(rc, 1)
        st = self.w.status()
        self.assertEqual((st["state"], st["reason"]), ("failed", "no_keyring"))
        by = {s["id"]: s for s in st["stages"]}
        self.assertEqual((by["load"]["state"], by["normalize"]["state"]), ("done", "done"))
        self.assertEqual((by["classify"]["state"], by["classify"]["reason"]), ("failed", "no_keyring"))
        self.assertEqual((by["time"]["state"], by["time"]["reason"]), ("skipped", "upstream_failed"))
        self.assertEqual(by["report"]["reason"], "upstream_failed")
        self.assertIsNone(self.w.current())


class ProgressStatusTest(unittest.TestCase):
    def setUp(self):
        quiet()
        self.addCleanup(loud)
        self.w = W.World()
        self.addCleanup(self.w.remove)
        self.w.put(W.rows())
        self.w.keyring()

    def test_running_state_visible(self):
        """실행 중에는 run_status.json 이 state=running · 그 단계 running · 뒤 단계 pending(화면 진행 카드)."""
        from unittest import mock

        import lm27.normalize.load as L
        from lm27.pipeline.retention import list_runs
        real = L.load_evidence
        seen = {}

        def peek(*a, **k):
            if "st" not in seen:                            # 첫 호출 = 적재 단계(뒤 단계·보고서도 증거를 읽는다)
                seen["st"] = self.w.status(list_runs(self.w.paths)[-1])
            return real(*a, **k)
        with mock.patch.object(L, "load_evidence", peek):
            self.assertEqual(self.w.analyze(), 0)
        st = seen["st"]
        self.assertEqual((st["state"], st["rc"], st["ended"]), ("running", None, None))
        by = {s["id"]: s for s in st["stages"]}
        self.assertEqual(by["load"]["state"], "running")
        self.assertTrue(UTC_RX.match(by["load"]["started"]))
        self.assertEqual({by[s]["state"] for s in S.STAGE_IDS[1:]}, {"pending"})
        self.assertEqual(self.w.status()["state"], "done")


class CopilotRoleTest(unittest.TestCase):
    """Copilot 역할 판정 = pc.json roles(TAB §1.5), pc.json 이 없으면 PC 종류가 클라우드PC 인지(identify_pc 대역)."""

    def setUp(self):
        self.w = W.World()
        self.addCleanup(self.w.remove)

    def role(self, ident):
        from unittest import mock

        import lm27.bundle.ids as IDS
        with mock.patch.object(IDS, "identify_pc", lambda paths=None, **k: ident):
            return A._detect_copilot_role(self.w.paths)

    def test_roles(self):
        rws = W.rows()
        pc = rws[0]["pc_id"]
        self.w.put(rws)                                     # 데스크톱 PC — 기본 역할에 copilot 없음
        self.assertFalse(self.role(W.ident(pc)))
        cloud = "pcx_" + "a" * 16
        self.assertTrue(self.role(W.ident(cloud)), "pc.json 없음 + 클라우드PC 추정 = copilot")
        from lm27.bundle import pcreg
        pcreg.ensure_pc_dir(self.w.paths, W.ident(cloud), host="", now="2026-09-01T00:00:00Z")
        self.assertTrue(self.role(W.ident(cloud)), "클라우드PC 기본 역할에 copilot")
        pcreg.update_pc(self.w.paths.pc_dir(cloud), {"roles": ["pc_usage"]})
        self.assertFalse(self.role(W.ident(cloud)), "사용자가 고친 역할을 따른다")


class KeepAndChooseTest(unittest.TestCase):
    def setUp(self):
        quiet()
        self.addCleanup(loud)
        self.w = W.World()
        self.addCleanup(self.w.remove)
        self.w.put(W.rows())
        self.w.keyring()

    def test_prune_and_choose(self):
        """report.analysisKeep: 끝날 때마다 새것 N 개 + 현재 결과만 남긴다. [이 결과 보기] = chosen explicit."""
        cfg = self.w.cfg({"report.analysisKeep": 2})
        for _ in range(3):
            self.assertEqual(self.w.analyze(cfg), 0)
        r1, r2, r3 = self.w.runs
        self.assertLess(r1, r2)
        self.assertLess(r2, r3)
        from lm27.pipeline.retention import list_runs
        self.assertEqual(list_runs(self.w.paths), [r2, r3])
        self.assertEqual(self.w.status(r3)["pruned"], 1)
        cur = A.choose_current(self.w.paths, cfg, r2, now=W.NOW)
        self.assertEqual((cur["run_id"], cur["chosen"]), (r2, "explicit"))
        self.assertEqual(self.w.current()["chosen"], "explicit")
        with self.assertRaises(ValueError):
            A.choose_current(self.w.paths, cfg, r1)                          # 지워진 실행
        self.assertEqual(self.w.analyze(cfg), 0)                              # 새 분석은 다시 auto 로
        r4 = self.w.last
        self.assertEqual((self.w.current()["run_id"], self.w.current()["chosen"]), (r4, "auto"))
        self.assertEqual(list_runs(self.w.paths), [r3, r4])


if __name__ == "__main__":
    unittest.main()
