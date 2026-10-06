# -*- coding: utf-8 -*-
"""개인 보고서 API — RPT-03 결과 선택(없음·정리됨·조용한 대체 금지) · RPT-05 판 다름 자동 report_build 1회 ·
RPT-48 확인 질문 응답 → 증거 키 수동 기록 + 디바운스 빠른 재분석 · RPT-49 분류 고치기 → corrections.jsonl 증거 키 + 재분석."""
import json
import os
import re
import time
import unittest

from lm27.hier.learn import load_corrections, match_units
from lm27.ui import jobs as J
from lm27.util import fsx
from tests.fixtures.wp35.harness import PC_ID, RUN_ID, Running, Sandbox, sample_tasks, seed_analysis

REF_RX = re.compile(r"^(?:[me][0-9a-f]{24}|[dh][0-9a-f]{16})$")


def _wait(fn, timeout=20.0):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        v = fn()
        if v:
            return v
        time.sleep(0.05)
    return fn()


class ReportSelectTest(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()
        self.addCleanup(self.sb.cleanup)

    def _srv(self, **kw):
        app = self.sb.app(**kw)
        srv = Running(app).__enter__()
        self.addCleanup(srv.close)
        return app, srv

    def test_rpt03_no_current(self):
        _app, srv = self._srv()
        st, b, _ = srv.req("GET", "/api/report?variant=full")
        self.assertEqual(st, 404)
        self.assertEqual(b["code"], "no_current")

    def test_rpt03_run_missing_no_silent_switch(self):
        seed_analysis(self.sb)
        other = "20261001-090000-1b2c"
        self.sb.write_json(self.sb.paths.analysis_current(), {"schema": "lm27.current/1", "run_id": other,
                                                               "chosen": "explicit"})
        _app, srv = self._srv()
        st, b, _ = srv.req("GET", "/api/report?variant=full")
        self.assertEqual(st, 404)
        self.assertEqual(b["code"], "run_missing")
        self.assertEqual(b["run_id"], other)                            # 남은 실행으로 조용히 바꾸지 않는다

    def test_model_served_with_defaults(self):
        seed_analysis(self.sb)
        _app, srv = self._srv()
        st, b, _ = srv.req("GET", "/api/report?variant=full")
        self.assertEqual(st, 200, b)
        self.assertEqual(b["run"]["run_id"], RUN_ID)
        self.assertEqual(b["export_defaults"], {"formats": ["html", "csv", "json"], "variants": ["full", "redacted"]})
        st, b2, _ = srv.req("GET", f"/api/report?run={RUN_ID}&variant=nope")
        self.assertEqual(st, 400)

    def test_rpt05_missing_model_rebuilds_once(self):
        seed_analysis(self.sb, model=False)
        app, srv = self._srv(behaviour={"report": {"sleep": 0.2}})
        st, b, _ = srv.req("GET", "/api/report?variant=full")
        self.assertEqual(st, 409)
        self.assertEqual(b["code"], "rebuilding")
        jid = b["job_id"]
        st, b2, _ = srv.req("GET", "/api/report?variant=full")
        if st == 409:
            self.assertEqual(b2.get("job_id"), jid)                     # 같은 작업(두 번 띄우지 않는다)
        v = _wait(lambda: (app.jobs.get(jid) or {}).get("state") in J.FINISHED and app.jobs.get(jid))
        self.assertEqual(v["kind"], "report_build")
        kinds = [j["kind"] for j in app.jobs.list()]
        self.assertEqual(kinds.count("report_build"), 1)


class AnswerTest(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()
        self.addCleanup(self.sb.cleanup)
        seed_analysis(self.sb)

    def _srv(self, **kw):
        app = self.sb.app(**kw)
        srv = Running(app).__enter__()
        self.addCleanup(srv.close)
        return app, srv

    def test_rpt48_q01_answer_instr_with_evidence_keys(self):
        app, srv = self._srv()
        st, b, _ = srv.req("POST", "/api/queue/answer",
                           {"qid": "9f2c01ab3e4d", "answer": {"choice": "instr", "d": "2026-09-03",
                                                              "at": "2026-09-03T10:30"}})
        self.assertEqual(st, 200, b)
        self.assertEqual(b["stored"], 1)
        call = app.deps.pipe_calls[0]
        self.assertEqual((call["kind"], call["src"], call["pc_id"]), ("manual", "manual", PC_ID))
        raw = call["raws"][0]
        self.assertEqual(raw["man_kind"], "instr")
        self.assertEqual((raw["date"], raw["start"]), ("2026-09-03", "10:30"))
        self.assertIn("m" + "4" * 24, raw["ref_keys"])                   # 질문의 증거 키
        self.assertIn("m" + "1" * 24, raw["ref_keys"])                   # 단위업무 첫 근거 키
        self.assertTrue(all(REF_RX.match(k) for k in raw["ref_keys"]))
        self.assertLessEqual(len(raw["ref_keys"]), 5)
        self.assertNotIn("u_a1a1a1a1a1", json.dumps(raw))                # 업무 ID 가 아니라 증거 키로(재분석에도 유지)
        self.assertTrue(re.fullmatch(r"[0-9A-Za-z가-힣_ \-]{1,20}", raw["category"]))
        jid = b["reanalyze_job"]
        self.assertEqual(app.jobs.get(jid)["state"], "queued")           # 디바운스(ui.reanalyzeDebounceSec)
        st, b2, _ = srv.req("POST", "/api/queue/answer",
                            {"qid": "aa11bb22cc33", "answer": {"choice": "absence"}})
        self.assertEqual(st, 200, b2)
        self.assertEqual(b2["reanalyze_job"], jid)                       # 여러 응답을 한 번의 재분석으로
        self.assertEqual(app.deps.pipe_calls[1]["raws"][0]["man_kind"], "absence")
        self.assertEqual(app.deps.pipe_calls[1]["raws"][0]["date"], "2026-09-23")

    def test_rpt48_reanalyze_argv_after_debounce(self):
        app, srv = self._srv(behaviour={"analyze": {"sleep": 0.1}}, **{"ui.reanalyzeDebounceSec": 0})
        st, b, _ = srv.req("POST", "/api/queue/answer",
                           {"qid": "9f2c01ab3e4d", "answer": {"choice": "report", "at": "2026-09-05T17:00"}})
        self.assertEqual(st, 200, b)
        jid = b["reanalyze_job"]
        v = _wait(lambda: (app.jobs.get(jid) or {}).get("state") in J.FINISHED and app.jobs.get(jid))
        self.assertEqual(v["state"], "done")
        self.assertEqual(v["kind"], "quick_reanalyze")
        self.assertEqual(v["result"]["argv"], ["analyze", "--rerun", RUN_ID, "--stages", "classify,time,mining,report",
                                               "--no-ai"])

    def test_answer_validation(self):
        app, srv = self._srv()
        st, b, _ = srv.req("POST", "/api/queue/answer", {"qid": "9f2c01ab3e4d", "answer": {"choice": "bogus"}})
        self.assertEqual(st, 400)
        st, b, _ = srv.req("POST", "/api/queue/answer", {"qid": "000000000000", "answer": {"choice": "instr"}})
        self.assertEqual(st, 404)
        st, b, _ = srv.req("POST", "/api/queue/answer",
                           {"qid": "9f2c01ab3e4d", "answer": {"choice": "instr", "at": "2026-09-03 10:30"}})
        self.assertEqual(st, 400)
        self.assertEqual(app.deps.pipe_calls, [])

    def test_merge_question_must_link(self):
        app, srv = self._srv()
        st, b, _ = srv.req("POST", "/api/queue/answer", {"qid": None, "code": "Q12",
                                                         "answer": {"choice": "must_link",
                                                                    "units": ["u_a1a1a1a1a1", "u_b2b2b2b2b2"]}})
        self.assertEqual(st, 200, b)
        raw = app.deps.pipe_calls[0]["raws"][0]
        self.assertEqual(raw["man_kind"], "must_link")
        self.assertIn("m" + "3" * 24, raw["ref_keys"])

    def test_approve_choice_writes_nothing(self):
        app, srv = self._srv()
        st, b, _ = srv.req("POST", "/api/queue/answer", {"qid": "9f2c01ab3e4d", "answer": {"choice": "approve"}})
        self.assertEqual(st, 200)
        self.assertEqual(b["stored"], 0)
        self.assertEqual(app.deps.pipe_calls, [])


class CorrectionTest(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()
        self.addCleanup(self.sb.cleanup)
        seed_analysis(self.sb)
        self.app = self.sb.app()
        self.srv = Running(self.app).__enter__()
        self.addCleanup(self.srv.close)

    def test_rpt49_correction_evidence_keys(self):
        st, b, _ = self.srv.req("POST", "/api/hier/correction", {"unit_id": "u_a1a1a1a1a1",
                                                                   "set": {"project": "P-0007"}, "scope": "similar",
                                                                   "from_queue": "H01:4f2a9c1d0e3b"})
        self.assertEqual(st, 200, b)
        self.assertTrue(b["reanalyze_job"])
        cs = load_corrections(self.sb.paths)
        self.assertEqual(len(cs), 1)
        c = cs[0]
        self.assertEqual(c["set"], {"project": "P-0007"})
        self.assertEqual(c["scope"], "similar")
        self.assertEqual(c["target"]["anchor"], "m" + "1" * 24)
        self.assertEqual(c["target"]["conv_keys"], ["h" + "5" * 16])
        self.assertEqual(c["target"]["fam_keys"], ["d" + "6" * 16])
        self.assertIn("m" + "2" * 24, c["target"]["unit_keys"])
        self.assertNotIn("u_a1a1a1a1a1", json.dumps(c))                  # 증거 키로 저장(H §11.3)
        units = {t["unit_id"]: t for t in sample_tasks()}
        self.assertEqual(match_units(c, units), ["u_a1a1a1a1a1"])
        self.assertTrue(re.fullmatch(r"c_[0-9a-f]{8}", c["id"]))
        raw = fsx.read_bytes(self.sb.paths.hier_local_file("corrections.jsonl"))
        self.assertTrue(raw.endswith(b"\n"))
        self.assertNotIn(b"\r", raw)

    def test_correction_validation(self):
        for body, code in (({"unit_id": "u_a1a1a1a1a1", "set": {"project": "__new__"}}, 409),
                           ({"unit_id": "u_a1a1a1a1a1", "set": {"bogus": 1}}, 400),
                           ({"unit_id": "u_a1a1a1a1a1", "set": {"project": "P-0007"}, "scope": "all"}, 400),
                           ({"unit_id": "u_zzzzzzzzzz", "set": {"project": "P-0007"}}, 404),
                           ({"unit_id": "u_a1a1a1a1a1", "set": {"wtype": "dev"}}, 400)):
            st, b, _ = self.srv.req("POST", "/api/hier/correction", body)
            self.assertEqual(st, code, (body, b))
        self.assertFalse(os.path.exists(self.sb.paths.hier_local_file("corrections.jsonl")))

    def test_h02_pick_with_group_target(self):
        from tests.fixtures.wp35.harness import sample_model
        m = sample_model()
        m["queue"].append({"qid": "bb22cc33dd44", "code": "H02", "target": "grp:0123456789ab", "status": "open",
                           "evidence_keys": [], "proposal": {"rule": "P-0007", "ai": "P-0012"}})
        self.sb.write_json(self.sb.paths.analysis_report_file(RUN_ID, "report_model.json"), m)
        st, b, _ = self.srv.req("POST", "/api/hier/correction", {"unit_id": "grp:0123456789ab", "set": {"pick": "ai"},
                                                                   "scope": "this", "from_queue": "bb22cc33dd44"})
        self.assertEqual(st, 200, b)
        c = load_corrections(self.sb.paths)[0]
        self.assertEqual(c["set"], {"project": "P-0012"})
        self.assertEqual(c["target"]["group"], "grp:0123456789ab")
        self.assertEqual(c["from_queue"], "bb22cc33dd44")
        st, b, _ = self.srv.req("POST", "/api/hier/correction", {"unit_id": "grp:0123456789ab", "set": {"pick": "ai"},
                                                                   "from_queue": "000000000000"})
        self.assertEqual(st, 409)

    def test_not_work_maps_to_none(self):
        st, b, _ = self.srv.req("POST", "/api/hier/correction", {"unit_id": "u_b2b2b2b2b2",
                                                                   "set": {"project": "__not_work__"}, "scope": "this"})
        self.assertEqual(st, 200, b)
        self.assertEqual(load_corrections(self.sb.paths)[0]["set"]["project"], "NONE")

    def test_hier_state_shape(self):
        st, b, _ = self.srv.req("GET", "/api/hier/state")
        self.assertEqual(st, 200, b)
        for k in ("registry", "ai_share", "codename", "proposals", "rules", "unapplied", "projects", "vocab"):
            self.assertIn(k, b)
        self.assertEqual(b["ai_share"], 0.5)


if __name__ == "__main__":
    unittest.main()
