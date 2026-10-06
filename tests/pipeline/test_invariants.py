# -*- coding: utf-8 -*-
"""WP-32 불변식 — T-01(실분석 보존 위반 → 중단·rc 1, 이전 결과 유지) · T-02(결정성: 같은 입력·기준 시각·설정 = 같은 결과
바이트, 세그먼트 순서·분할을 바꿔도 같음) · T-06(분류는 시간 값을 바꾸지 않음) · 중단(KeyboardInterrupt·취소 → partial, rc 2) ·
재분석(--rerun: 빠른 재분석·결과 다시 쓰기·새 수동 행 반영)."""
import json
import unittest
from unittest import mock

import lm27.time as TC
from lm27.hier import HierResult
from lm27.pipeline import stages as S
from lm27.time.attribute import ConservationError
from lm27.util import events
from tests.core.test_stage_result import check_stage_common
from tests.fixtures.wp32 import world as W

REAL_ANALYZE_TIME = TC.analyze_time


class _Base(unittest.TestCase):
    def setUp(self):
        events.configure(mode="off")
        self.addCleanup(events.configure, mode="text")
        self.w = W.World()
        self.addCleanup(self.w.remove)
        self.w.put(W.rows())
        self.w.keyring()


class ConservationTest(_Base):
    def test_core_raises(self):
        """T-01: 시간 코어의 보존 assert 위반 → 분석 중단 · rc 1 · 결과 파일·current.json 교체 없음."""
        self.assertEqual(self.w.analyze(), 0)
        good = self.w.last

        def boom(*a, **k):
            raise ConservationError("보존 위반(시험)")
        with mock.patch.object(TC, "analyze_time", boom):
            rc = self.w.analyze()
        self.assertEqual(rc, 1)
        st = self.w.status()
        self.assertEqual((st["state"], st["reason"]), ("failed", "conservation"))
        cl = self.w.stage("classify")
        self.assertEqual((cl["state"], cl["reason"], cl["error_type"]), ("failed", "conservation", "ConservationError"))
        self.assertEqual(check_stage_common(cl), [])
        for sid in ("time", "mining", "report"):
            self.assertEqual(self.w.stage(sid)["reason"], "upstream_failed")
        self.assertEqual(self.w.current()["run_id"], good, "성공 전 무효화 금지")
        self.assertFalse(self.w.paths.analysis_time_file(self.w.last, "team_tables.json").exists())

    def test_pipeline_recheck(self):
        """T-01 재검사: 코어가 놓친 보존 위반(귀속 초 1초 모자람)도 파이프라인이 잡는다 — 날짜·차이를 남긴다."""
        def corrupt(*a, **k):
            res = REAL_ANALYZE_TIME(*a, **k)
            s = min(res.assign)
            dist = res.assign[s]
            k0 = sorted(dist)[0]
            dist[k0] -= 1
            return res
        with mock.patch.object(TC, "analyze_time", corrupt):
            rc = self.w.analyze()
        self.assertEqual(rc, 1)
        cl = self.w.stage("classify")
        self.assertEqual((cl["state"], cl["reason"]), ("failed", "conservation"))
        self.assertEqual(cl["violation_days"], 1)
        d, env_s, att_s = cl["violations"][0]
        self.assertEqual(env_s - att_s, 1)
        self.assertRegex(d, r"^2026-09-\d{2}$")
        self.assertIsNone(self.w.current())


class DeterminismTest(unittest.TestCase):
    def test_t02_layout_independent(self):
        """T-02: 같은 행을 다른 세그먼트 순서·분할로 쓴 두 번들 → 시간·분류·보고서 결과 바이트가 같다."""
        events.configure(mode="off")
        self.addCleanup(events.configure, mode="text")
        rws = W.rows()
        out = []
        for split, rev in ((1, False), (3, True)):
            w = W.World()
            self.addCleanup(w.remove)
            w.put(rws if not rev else list(reversed(rws)), split=split, reverse=rev)
            w.keyring(same_as=out[0] if out else None)              # 같은 입력 = 같은 키(단위업무 id 재료)
            self.assertEqual(w.analyze(run_id="20260914-090000-c0de"), 0)
            out.append(w)
        a, b = out
        for name in W.TIME_FILES:
            if name == "run_meta.json":
                ma, mb = json.loads(a.time_bytes(name)), json.loads(b.time_bytes(name))
                self.assertEqual(ma, mb)
                continue
            self.assertEqual(a.time_bytes(name), b.time_bytes(name), name)
        for name in ("labels.json", "groups.json", "evidence_tags.jsonl", "queue.json"):
            self.assertEqual(a.hier_bytes(name), b.hier_bytes(name), name)
        self.assertEqual(a.model_bytes(), b.model_bytes(), "report_model.json")


class ClassifyInvarianceTest(_Base):
    def test_t06_labels_do_not_move_time(self):
        """T-06: 분류(라벨)가 달라도 정수 분 표(team_tables.json) 바이트는 같다 — 롤업만 달라진다."""
        self.assertEqual(self.w.analyze(), 0)
        base_tables = self.w.time_bytes("team_tables.json")
        base_mm = json.loads(self.w.time_bytes("mm_month.json"))
        real = HierResult.rollup_labels

        def other(self_):
            return {u: {"domain": "AX", "project": "P-9905", "role": "r_000000", "wtype": "EDU", "ax_link": True}
                    for u in real(self_)}
        with mock.patch.object(HierResult, "rollup_labels", other):
            self.assertEqual(self.w.analyze(), 0)
        self.assertEqual(self.w.time_bytes("team_tables.json"), base_tables)
        mm = json.loads(self.w.time_bytes("mm_month.json"))
        self.assertNotEqual([m["rollup"] for m in mm], [m["rollup"] for m in base_mm])
        strip = [{k: v for k, v in m.items() if k != "rollup"} for m in mm]
        self.assertEqual(strip, [{k: v for k, v in m.items() if k != "rollup"} for m in base_mm])

    def test_guard_when_time_values_move(self):
        """분류 뒤 정수 분 표가 바뀌면(결함) 결과를 쓰지 않는다 — classify_changed_time, rc 1."""
        held = {}

        def keep(*a, **k):
            held["res"] = REAL_ANALYZE_TIME(*a, **k)
            return held["res"]
        import lm27.time.mm as MM
        real_rollup = MM.rollup

        def mutating(month, labels):
            if "res" in held:                          # 시간 코어 안의 롤업(결과를 돌려주기 전)은 그대로
                tb = held["res"].tables
                key = sorted(tb.env)[0]
                tb.env[key] += 5
            return real_rollup(month, labels)
        with mock.patch.object(TC, "analyze_time", keep), mock.patch.object(MM, "rollup", mutating):
            rc = self.w.analyze()
        self.assertEqual(rc, 1)
        tm = self.w.stage("time")
        self.assertEqual((tm["state"], tm["reason"]), ("failed", "classify_changed_time"))
        self.assertFalse(self.w.paths.analysis_time_file(self.w.last, "team_tables.json").exists())


class CancelTest(_Base):
    def test_cancel_callable(self):
        calls = {"n": 0}

        def cancel():
            calls["n"] += 1
            return calls["n"] > 3                      # load·normalize·classify 뒤
        rc = self.w.analyze(cancel=cancel)
        self.assertEqual(rc, 2)
        st = self.w.status()
        self.assertEqual((st["state"], st["reason"], st["current"]), ("partial", "cancelled", False))
        by = {s["id"]: s for s in st["stages"]}
        self.assertEqual([by[s]["state"] for s in ("load", "normalize", "classify")], ["done"] * 3)
        self.assertEqual({by[s]["reason"] for s in S.STAGE_IDS[3:]}, {"cancelled"})
        self.assertIsNone(self.w.current())

    def test_keyboard_interrupt(self):
        import lm27.normalize.load as L

        def stop(*a, **k):
            raise KeyboardInterrupt
        with mock.patch.object(L, "load_evidence", stop), self.assertRaises(KeyboardInterrupt):
            self.w.analyze()
        from lm27.pipeline.retention import list_runs
        rid = list_runs(self.w.paths)[-1]
        st = self.w.status(rid)
        self.assertEqual((st["state"], st["rc"], st["reason"]), ("partial", 2, "cancelled"))
        load = next(s for s in st["stages"] if s["id"] == "load")
        self.assertEqual((load["state"], load["stop_kind"], load["resumable"]), ("partial", "cancelled", True))
        self.assertEqual(check_stage_common(load), [])
        self.assertIsNone(self.w.current())


class RerunTest(_Base):
    def test_quick_rerun(self):
        """빠른 재분석(classify,time,mining,report --no-ai): 원본의 기간·기준 시각, 새 실행, load·normalize 함께(auto)."""
        self.assertEqual(self.w.analyze(), 0)
        r1 = self.w.last
        rc = self.w.analyze(rerun=r1, stages=list(S.QUICK_RERUN))
        self.assertEqual(rc, 0)
        r2 = self.w.last
        self.assertNotEqual(r1, r2)
        st = self.w.status()
        self.assertEqual((st["rerun_of"], st["period_source"], st["from"], st["to"], st["as_of"]),
                         (r1, "rerun", W.D0, W.D1, W.AS_OF))
        self.assertEqual(st["stages_selected"], list(S.QUICK_RERUN))
        by = {s["id"]: s for s in st["stages"]}
        self.assertTrue(by["load"]["auto"] and by["normalize"]["auto"])
        self.assertNotIn("auto", by["classify"])
        self.assertEqual((by["review"]["state"], by["review"]["reason"]), ("skipped", "not_selected"))
        for name in W.TIME_FILES:
            if name != "run_meta.json":
                self.assertEqual(self.w.time_bytes(name, r1), self.w.time_bytes(name, r2), name)
        self.assertEqual(self.w.current()["run_id"], r2)
        self.assertEqual(self.w.current()["period_source"], "rerun")

    def test_reuse_report_only(self):
        self.assertEqual(self.w.analyze(), 0)
        r1 = self.w.last
        self.assertEqual(self.w.analyze(rerun=r1, stages=["report"]), 0)
        r2 = self.w.last
        tm = self.w.stage("time")
        self.assertEqual((tm["state"], tm["reason"], tm["reused_from"]), ("skipped", "reused", r1))
        self.assertEqual(self.w.stage("load")["reason"], "reused")
        for name in W.TIME_FILES:
            self.assertEqual(self.w.time_bytes(name, r1), self.w.time_bytes(name, r2), name)
        self.assertEqual(self.w.hier_bytes("labels.json", r1), self.w.hier_bytes("labels.json", r2))
        self.assertEqual(self.w.stage("report")["state"], "done")
        self.assertEqual(self.w.current()["run_id"], r2)

    def test_reuse_missing(self):
        """원본에 시간 결과가 없으면(거부된 실행) 다시 쓸 수 없다 — rc 1, 이전 결과 유지."""
        self.assertEqual(self.w.analyze(), 0)
        good = self.w.last
        bad = self.w.analyze(cancel=lambda: True)
        self.assertEqual(bad, 2)
        r_bad = self.w.last
        self.assertEqual(self.w.analyze(rerun=r_bad, stages=["report"]), 1)
        tm = self.w.stage("time")
        self.assertEqual((tm["state"], tm["reason"]), ("failed", "reuse_missing"))
        self.assertEqual(self.w.current()["run_id"], good)

    def test_rerun_reads_new_manual_rows(self):
        """확인 질문 응답(수동 행)이 번들에 더해진 뒤 빠른 재분석은 그 행을 다시 읽는다."""
        self.assertEqual(self.w.analyze(), 0)
        r1 = self.w.last
        extra = [r for r in W.rows(kinds=("manual",), seed=7) if r["kind"] == "manual"]
        self.assertTrue(extra)
        self.w.put(extra)
        self.assertEqual(self.w.analyze(rerun=r1, stages=list(S.QUICK_RERUN)), 0)
        n1 = self.w.stage("load", r1)["counts"]["records"]
        n2 = self.w.stage("load")["counts"]["records"]
        self.assertGreater(n2, n1)


if __name__ == "__main__":
    unittest.main()
