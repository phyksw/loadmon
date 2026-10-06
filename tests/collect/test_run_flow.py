# -*- coding: utf-8 -*-
"""WP-33 [수집] 흐름(lm27.collect.run.collect_here) — 계약 §2.5 순서 · §8.1 · §8.3 · §8.5 · TAB §1.7 · C §8 · D-6.

  · 업무 PC: 번들·키링 생성 → 에이전트 확인 → 탐침 기록 → 수확(에이전트) → 로컬 메일·일정·팀즈 확인·반입 → 내보내기 →
    원장·빈칸 → 업로드. 단계마다 stage_result(계약 §8.5 공통 필드 — validate) · 명령 rc = collect_rc(계약 §8.3).
  · 번들 읽기 전용 → rc 3 + R-BUNDLE-READONLY, 쓰기 0. probe-only · --only · 예산 소진 → partial + budget(T-10).
  · 실행 차단(impl none + 전경도 R-CLM) → pc_bundle failed → rc 3(§8.1 (e)). 단계 예외 → failed, 흐름은 계속 → rc 1.
  · 클라우드PC(백필): 원장 빈칸 → blanks_mail.owa.json(X-315) → OWA(--blanks-file·--run-id)·팀즈 웹 → 내보내기·원장 다시,
    로그인 필요(rc 2 · R-LOGIN) → partial login + 안내 이벤트, 코파일럿 어댑터가 아직 없으면 돌지 않음.
수집기·파이프·탐침·에이전트는 가짜 — 실제 메일·팀즈·PC 수집·작업 등록·네트워크 0.
"""
from __future__ import annotations

import io
import itertools
import json
import threading
import unittest

from lm27.bundle import pcreg
from lm27.bundle.lock import BundleLock
from lm27.collect import ledger, rcmap
from lm27.collect import run as R
from lm27.collect import stage_result as sr
from lm27.util import events, fsx
from tests.fixtures.wp33.helpers import FakeDeps, Sandbox, ident, probe_result

REC = [{"subject": "과제A 회의", "ts_utc": "2026-10-01T01:00:00Z"}, {"subject": "과제A 보고", "ts_utc": "2026-10-01T02:00:00Z"}]
OKST = {"rc": 0, "reasons": []}
CAPS = {"env": {"status": "ok"}, "mail.com": {"status": "ok", "value": {"omg": False, "attach": "ok"}},
        "cal.com": {"status": "ok"}, "mail.index": {"status": "ok"}, "cal.index": {"status": "ok"},
        "edge_cdp_policy": {"status": "ok"}, "teams.uia": {"status": "ok"},
        "pc.sampler": {"status": "ok", "value": {"ps": True, "py": True}}, "pc.events": {"status": "ok"},
        "pc.git": {"status": "ok"}}
HARVEST_DONE = {"rc": 0, "done": True, "result": {"schema": "lm27.harvest_done/1", "streams": {
    s: {"src": s, "rc": 4, "pipe": 0, "stored": 0, "reasons": [], "timed_out": False, "skipped": ""}
    for s in ("pc.events", "pc.files", "pc.mru", "pc.recent")}}}


def specs(**over):
    base = {s: {"rc": 0, "records": REC, "status": OKST} for s in ("mail.com", "mail.index", "cal.com", "cal.index")}
    base.update({"pc.git": {"rc": 1, "status": {"rc": 1, "reasons": []}},
                 "mail.import": {"rc": 1, "status": {"rc": 1, "reasons": []}},
                 "cal.import": {"rc": 1, "status": {"rc": 1, "reasons": []}}})
    base.update(over)
    return base


class CfgOver:
    def __init__(self, base, **over):
        self.base, self.over = base, over

    def __getitem__(self, k):
        return self.over[k] if k in self.over else self.base[k]


class FlowBase(unittest.TestCase):
    def setUp(self):
        self.out = io.StringIO()
        events.configure("jsonl", stream=self.out, reset_seq=True)
        self.addCleanup(events.configure, "text")
        self.sb = Sandbox()
        self.addCleanup(self.sb.cleanup)
        self.cfg = self.sb.cfg(**{"collect.lookbackDays": 10, "collect.webEverywhere": False, "collect.sinceYearStart": False})   # 예전 의미 — 새 기본값은 test_plan

    def deps(self, **kw):
        kw.setdefault("specs", specs())
        kw.setdefault("probe", probe_result(CAPS))
        kw.setdefault("harvest", HARVEST_DONE)
        return FakeDeps(self.sb, kw.pop("cfg", self.cfg), **kw)

    def collect(self, d, **kw):
        return R.collect_here(self.sb.paths, kw.pop("cfg", self.cfg), deps=d, **kw)

    def stage(self, res, name):
        return sr.read_stage_result(self.sb.paths, res.run_id, name)

    def events(self):
        return [json.loads(x) for x in self.out.getvalue().splitlines() if x.strip()]

    def assert_valid(self, res):
        for st in res.stages:
            self.assertEqual(sr.validate_stage_result(st, collect=True), [], st.get("stage"))
            self.assertEqual(st.get("pc_id"), res.pc_id)
        self.assertEqual(res.rc, rcmap.collect_rc(res.stages))


class WorkPcFlow(FlowBase):
    def test_full_auto_flow(self):
        d = self.deps()
        res = self.collect(d)
        self.assert_valid(res)
        names = [s["stage"] for s in res.stages]
        self.assertEqual(names, ["probe", "pc_bundle", "mail_local", "cal_local", "teams_uia_check", "import", "export",
                                 "derive", "upload"])
        self.assertEqual(res.rc, 0)                                          # 새 레코드 있음
        self.assertEqual(d.agent_calls, 1)
        self.assertEqual(self.stage(res, "pc_bundle")["harvest"], "agent")
        self.assertEqual(self.stage(res, "mail_local")["items_ok"], 4)       # COM 2 + 색인 2(가짜 파이프 저장 수)
        t = self.stage(res, "teams_uia_check")
        self.assertEqual((t["state"], t["hint"]), ("skipped", R.HINT_AGENT_ALIVE))
        self.assertFalse(d.collector_calls("teams.uia"))                     # 에이전트가 살아 있으면 확인만
        up = self.stage(res, "upload")
        self.assertEqual((up["state"], up["reason"]), ("skipped", "team_queue_missing"))
        # 번들·키링·pc.json·파생물
        p = self.sb.paths
        bj = fsx.read_json(p.bundle_json())
        self.assertRegex(bj["person_key"], r"^p_[0-9a-f]{12}$")
        self.assertTrue(p.keyring().is_file())
        pc = pcreg.load_pc(p.pc_dir(res.pc_id))
        self.assertEqual(len(pc["visits"]), 1)
        self.assertEqual(pc["capabilities"]["mail.com"]["history"][-1]["probe_sig"], "aaaaaaaaaaaa")
        self.assertTrue(p.coverage_ledger().is_file() and p.todo().is_file())
        cells = {(c["date"], c["kind_axis"], c["src"]) for c in ledger.load_cells(p)}
        self.assertIn(("2026-10-05", "mail_in", "mail.index"), cells)
        ev = [e["ev"] for e in self.events()]
        self.assertIn("stage_start", ev)
        self.assertIn("stage_end", ev)
        # 두 번째 [수집]: person_key 불변, 방문 2
        res2 = self.collect(self.deps(), only=["mail.index"])
        self.assertEqual(fsx.read_json(p.bundle_json())["person_key"], bj["person_key"])
        self.assertEqual(len(pcreg.load_pc(p.pc_dir(res2.pc_id))["visits"]), 2)

    def test_no_new_records_is_rc4(self):
        sp = {s: {"rc": 4, "records": [], "status": {"rc": 4}} for s in ("mail.com", "mail.index", "cal.com", "cal.index")}
        res = self.collect(self.deps(specs=specs(**sp)), only=["mail.index", "cal.index"])
        self.assert_valid(res)
        self.assertEqual(res.rc, 4)                                          # 정제 감사 줄은 '새 레코드'가 아니다

    def test_readonly_bundle_writes_nothing(self):
        loc = {"ok": False, "status": "fail", "value": {"writable": False}, "reasons": ["R-BUNDLE-READONLY"]}
        d = self.deps(location=loc)
        res = self.collect(d)
        self.assertEqual((res.rc, res.reasons, res.stages), (3, ["R-BUNDLE-READONLY"], []))
        self.assertEqual(list(self.sb.paths.data().iterdir()), [])
        self.assertEqual((d.agent_calls, d.calls), (0, []))

    def test_probe_only(self):
        d = self.deps()
        res = self.collect(d, mode="probe-only")
        self.assert_valid(res)
        self.assertEqual([s["stage"] for s in res.stages], ["probe", "derive"])
        self.assertEqual((d.agent_calls, d.collector_calls()), (0, []))

    def test_only_filter(self):
        d = self.deps()
        res = self.collect(d, only=["mail.index"])
        self.assert_valid(res)
        self.assertEqual([s["stage"] for s in res.stages], ["probe", "mail_local", "export", "derive"])
        self.assertEqual([c[1] for c in d.collector_calls()], ["mail.index"])
        self.assertEqual(d.agent_calls, 0)
        bad = self.collect(self.deps(), only=["mail.nope"])
        self.assertEqual((bad.rc, bad.notes), (1, ["only_unknown"]))

    def test_probe_blocked_com_is_not_spawned_and_ledger_blocked(self):
        caps = dict(CAPS, **{"mail.com": {"status": "fail", "reasons": ["R-NEWOL"]},
                             "cal.com": {"status": "fail", "reasons": ["R-NEWOL"]}})
        d = self.deps(probe=probe_result(caps))
        res = self.collect(d, only=["mail.com", "mail.index"])
        self.assert_valid(res)
        self.assertFalse(d.collector_calls("mail.com"))
        self.assertTrue(d.collector_calls("mail.index"))                      # X-124 — 색인은 시도
        ml = self.stage(res, "mail_local")
        self.assertEqual(ml["srcs"]["mail.com"]["rc"], 3)
        self.assertEqual(ml["srcs"]["mail.com"]["reasons"], ["R-NEWOL"])
        self.assertEqual(ml["skipped_srcs"]["mail.com"], "planned_probe")
        cells = [c for c in ledger.load_cells(self.sb.paths) if c["src"] == "mail.com"]
        self.assertTrue(cells and all(c["status"] == "blocked" for c in cells))

    def test_execution_blocked_is_rc3(self):
        clm = {"rc": 3, "records": [], "status": {"rc": 3, "reasons": ["R-CLM"]}}
        sp = specs(**dict.fromkeys(("pc.events", "pc.files", "pc.mru", "pc.recent"), clm))
        d = self.deps(specs=sp, agent={"rc": 3, "impl": "none", "reasons": ["R-CLM"]})
        res = self.collect(d, only=["pc.sampler", "pc.events", "pc.files"])
        self.assert_valid(res)
        pb = self.stage(res, "pc_bundle")
        self.assertEqual((pb["state"], pb["reason"], pb["harvest"]), ("failed", "R-CLM", "foreground"))
        self.assertEqual(res.rc, 3)                                          # 계약 §8.1 (e)
        self.assertEqual(pb["srcs"]["pc.sampler"]["reasons"], ["R-CLM"])

    def test_stage_exception_is_failed_but_flow_continues(self):
        class Boom(FakeDeps):
            def spawn(self, argv, **kw):
                if self._src_of(argv) == "cal.com":
                    raise RuntimeError("synthetic")
                return super().spawn(argv, **kw)
        d = Boom(self.sb, self.cfg, specs=specs(), probe=probe_result(CAPS), harvest=HARVEST_DONE)
        res = self.collect(d, only=["mail.index", "cal.com"])
        self.assert_valid(res)
        cl = self.stage(res, "cal_local")
        self.assertEqual((cl["state"], cl["error_type"]), ("failed", "RuntimeError"))
        self.assertIn("export", [s["stage"] for s in res.stages])
        self.assertEqual(res.rc, 1)
        self.assertIn("cal_local_RuntimeError", res.notes)

    def test_budget_exhausted_marks_partial(self):
        clock = itertools.count(0, 50)
        d = self.deps(mono=lambda: float(next(clock)))
        res = self.collect(d, budget_sec=60)
        self.assert_valid(res)
        bud = [s for s in res.stages if s["stop_kind"] == "budget"]
        self.assertTrue(bud)
        for s in bud:
            self.assertEqual((s["state"], s["reason"], s["rc"]), ("partial", "R-BUDGET", rcmap.RC_NOT_RUN))
        self.assertEqual(res.rc, 2)
        cells = ledger.load_cells(self.sb.paths)
        skipped = {s for st in bud for s in st.get("srcs") or {}}
        for c in cells:
            if c["src"] in skipped and c["n"] == 0:
                self.assertIn(c["status"], rcmap.UNOBSERVED)               # 못 돈 것은 0h 가 아니다(T-09)

    def test_bundle_busy(self):
        cfg = CfgOver(self.cfg, **{"bundle.lockTimeoutSec": 0})
        held, release = threading.Event(), threading.Event()

        def hold():
            with BundleLock(self.sb.paths, "move", 5):
                held.set()
                release.wait(20)
        t = threading.Thread(target=hold)
        t.start()
        held.wait(10)
        try:
            res = self.collect(self.deps(cfg=cfg), cfg=cfg)
        finally:
            release.set()
            t.join(10)
        self.assertEqual((res.rc, res.notes), (2, ["bundle_busy"]))

    def test_corrupt_bundle_json(self):
        fsx.atomic_write(self.sb.paths.bundle_json(), b"{broken")
        res = self.collect(self.deps())
        self.assertEqual((res.rc, res.notes), (1, ["bundle_json_corrupt"]))

    def test_person_dir_delta_merged(self):
        wk = "w" + "1" * 16
        fsx.atomic_write(self.sb.paths.person_dir_delta(), fsx.canon_bytes(
            {"format": "lm27-persondir/1", "people": {wk: {"names": ["김철수"], "smtp": ["kim@corp.example"],
                                                         "self": False, "internal": True, "first": "2026-10-01",
                                                         "last": "2026-10-04"}}}))
        res = self.collect(self.deps(), only=["mail.index"])
        pd = fsx.read_json(self.sb.paths.local_only_file("person_dir.json"))
        self.assertEqual(pd["people"][wk]["names"], ["김철수"])
        self.assertEqual(self.stage(res, "export")["counts"]["people"], 1)

    def test_agent_failure_does_not_stop_collect(self):
        d = self.deps(agent=OSError("synthetic"))
        res = self.collect(d, only=["pc.sampler", "pc.events", "mail.index"])
        self.assert_valid(res)
        self.assertIn("agent_OSError", res.notes)
        pb = self.stage(res, "pc_bundle")
        self.assertEqual(pb["harvest"], "foreground")
        self.assertEqual(pb["srcs"]["pc.sampler"]["reasons"], ["R-TRANSPORT"])    # 다음 수집에서 다시('불가' 아님)
        self.assertIn("mail_local", [s["stage"] for s in res.stages])


class CloudFlow(FlowBase):
    def setUp(self):
        super().setUp()
        self.who = ident("CLOUD", kind="cloud")

    def test_backfill_from_blanks_and_login_wait(self):
        sp = specs(**{"mail.index": {"rc": 3, "records": [], "status": {"rc": 3, "reasons": ["R-NOIDX"]}},
                      "cal.index": {"rc": 4, "records": [], "status": {"rc": 4}},
                      "mail.owa": {"rc": 2, "status": {"rc": 2, "reasons": ["R-LOGIN"]}},
                      "cal.owa": {"rc": 0, "status": {"rc": 0, "reasons": [], "n": 3, "items_ok": 3}},
                      "teams.web": {"rc": 4, "status": {"rc": 4, "reasons": []}},
                      "mail.copilot": {"rc": 0, "status": {"rc": 0, "reasons": [], "n": 2, "items_ok": 2}}})
        caps = dict(CAPS, **{"mail.com": {"status": "fail", "reasons": ["R-NOPROF"]}})
        (self.sb.root / "collect" / "Get-MailViaCopilot.py").write_bytes(b"# placeholder")   # 코파일럿 어댑터 자리
        d = self.deps(ident_=self.who, specs=sp, probe=probe_result(caps))
        res = self.collect(d)
        self.assert_valid(res)
        names = [s["stage"] for s in res.stages]
        for n in ("backfill_owa", "backfill_teams_web", "copilot_lookup"):
            self.assertIn(n, names)
        p = self.sb.paths
        blanks = p.blanks_file(res.run_id, "mail.owa")
        rows = json.loads(fsx.read_bytes(blanks))
        self.assertTrue(rows and all(set(r) == {"todo_id", "date_range", "kind_axis"} for r in rows))
        self.assertTrue(all(r["todo_id"].startswith("mail.owa:") for r in rows))
        owa = d.collector_calls("mail.owa")[0][2]
        self.assertEqual(owa[owa.index("--blanks-file") + 1], str(blanks))
        self.assertEqual(owa[owa.index("--run-id") + 1], res.run_id)
        # 로그인 대기는 실행마다 한 번(v1.3 §0.8 V10) — 같은 전용 Edge 프로필의 일정·팀즈 웹은 다시 기다리지 않는다
        self.assertEqual(d.collector_calls("cal.owa"), [])
        self.assertEqual(d.collector_calls("teams.web"), [])
        bo = self.stage(res, "backfill_owa")
        self.assertEqual((bo["state"], bo["stop_kind"], bo["reason"]), ("partial", "login", "R-LOGIN"))
        self.assertEqual(bo["srcs"]["mail.owa"]["ranges"], [r["date_range"] for r in rows])
        self.assertEqual(bo["srcs"]["cal.owa"]["skipped"], "login_pending")
        self.assertEqual(bo["srcs"]["cal.owa"]["rc"], 2)
        bt = self.stage(res, "backfill_teams_web")
        self.assertEqual((bt["state"], bt["reason"]), ("partial", "R-LOGIN"))
        self.assertEqual(res.rc, 2)
        notices = [e for e in self.events() if e["ev"] == "notice"]
        self.assertEqual(notices[0]["text_ko"], R.NOTICE_LOGIN)
        # OWA 가 읽었는데도 빈 날 → 코파일럿 증인(C §6.1 '그래도 비면') — 그 실행 폴더의 빈칸 파일을 넘긴다(X-315)
        cblanks = p.blanks_file(res.run_id, "mail.copilot")
        crow = json.loads(fsx.read_bytes(cblanks))
        self.assertTrue(crow and all(r["todo_id"].startswith("mail.copilot:") for r in crow))
        cpa = d.collector_calls("mail.copilot")[0][2]
        self.assertEqual(cpa[cpa.index("--blanks-file") + 1], str(cblanks))
        self.assertEqual(cpa[cpa.index("--run-id") + 1], res.run_id)
        cp = self.stage(res, "copilot_lookup")
        self.assertEqual((cp["state"], cp["items_ok"]), ("done", 2))
        # 팀즈 웹이 로그인 대기로 못 읽어 빈칸이 남았다 — 이 시험에는 팀즈 코파일럿 어댑터가 없어 돌지 않음
        self.assertEqual(cp["skipped_srcs"], {"teams.copilot": "script_missing"})
        ex = self.stage(res, "export")
        self.assertGreaterEqual(ex["counts"]["passes"], 2)                   # 백필 뒤 내보내기 다시
        # 로그인 필요는 '불가' 근거가 아니다 — 확정되지 않는다(R-LOGIN = 사람 사유)
        self.assertFalse(rcmap.confirmable("R-LOGIN"))

    def test_logged_in_web_paths_all_run_in_order(self):
        """로그인돼 있으면 웹 경로가 차례로 다 돈다(v1.3 §0.8 V9) — 일정은 기간 전체라 빈칸 파일을 넘기지 않는다(CM §2)."""
        sp = specs(**{"mail.index": {"rc": 3, "records": [], "status": {"rc": 3, "reasons": ["R-NOIDX"]}},
                      "mail.owa": {"rc": 0, "status": {"rc": 0, "reasons": [], "n": 1, "items_ok": 1}},
                      "cal.owa": {"rc": 0, "status": {"rc": 0, "reasons": [], "n": 3, "items_ok": 3}},
                      "teams.web": {"rc": 4, "status": {"rc": 4, "reasons": []}}})
        caps = dict(CAPS, **{"mail.com": {"status": "fail", "reasons": ["R-NOPROF"]}})   # 메일 빈칸이 남게(앱 경로 없음)
        d = self.deps(ident_=self.who, specs=sp, probe=probe_result(caps))
        res = self.collect(d)
        self.assert_valid(res)
        cal = d.collector_calls("cal.owa")[0][2]
        self.assertNotIn("--blanks-file", cal)
        self.assertEqual(len(d.collector_calls("mail.owa")), 1)
        self.assertEqual(len(d.collector_calls("teams.web")), 1)
        bo = self.stage(res, "backfill_owa")
        self.assertNotIn("R-LOGIN", bo["reasons"])
        self.assertEqual(bo["srcs"]["cal.owa"]["skipped"], "")

    def test_recollect_owa_reads_requested_range(self):
        sp = specs(**{"mail.owa": {"rc": 0, "status": {"rc": 0, "reasons": [], "n": 2, "items_ok": 2}}})
        d = self.deps(ident_=self.who, specs=sp)
        res = self.collect(d, mode="recollect", since="2026-09-01", until="2026-09-30", only=["mail.owa"],
                           budget_sec=900)
        self.assert_valid(res)
        a = d.collector_calls("mail.owa")[0][2]
        self.assertEqual((a[a.index("--from") + 1], a[a.index("--to") + 1]), ("2026-09-01", "2026-09-30"))
        self.assertIn("--force", a)
        self.assertNotIn("--blanks-file", a)
        self.assertLessEqual(int(a[a.index("--budget-sec") + 1]), 900)
        bo = self.stage(res, "backfill_owa")
        self.assertEqual(bo["srcs"]["mail.owa"]["ranges"], [["2026-09-01", "2026-09-30"]])
        self.assertEqual(res.rc, 0)


if __name__ == "__main__":
    unittest.main()
