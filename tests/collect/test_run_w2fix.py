# -*- coding: utf-8 -*-
"""W2 검토 확정 지적 회귀(수정 묶음 A — 수집 흐름 ``lm27.collect.run.collect_here``):

  · C03(V6): 기본 [수집]이 관측 창(기본 시작일 ~ 오늘)을 수집기에 **늘** 넘긴다(-Since/-Until · --from/--to). 수집기가 상태 줄
    ``range`` 로 맡은 창을 알리면 원장 관측은 그 창으로 잘린다 — 안 읽은 날이 zero_ok 가 되지 않는다(T-09). 상태 줄에 창이
    없는 에이전트 수확은 ``collect.lookbackDays`` 기본 창으로 자른다.
  · C04·C11(V17): ``--no-agent`` 인데 예전 설치의 agent.json(impl py)이 남아 있어도 샘플러는 ``agent_skipped``(R-TRANSPORT 아님).
  · C05: 웹 경로를 도는 PC 는 탐침 단계에서 P-OWA·P-WEB 를 부탁한다(오늘 로그인 ok 기록이 있으면 하루 한 번만).
  · N1(V18): 로그인 보류 — 탐침이 짧게 확인하고 R-LOGIN(login_pending)이면 웹 수집기를 띄우지 않고 R-LOGIN ·
    skipped=login_pending, 수집기 상태 줄의 login_pending·login_account=personal 도 같은 길 + 안내 문구.
  · L13: 수집기가 stdout·stderr 를 물려받은 손주를 남기고 끝나도 연결자가 스트림 닫기에서 멈추지 않는다.
수집기·파이프·탐침·에이전트는 가짜(합성) — 실제 메일·팀즈·PC 수집·Edge·작업 등록·네트워크 0.
"""
from __future__ import annotations

import os
import time
import unittest
from datetime import date

from lm27.bridge.session import LOGIN_PERSONAL_TEXT
from lm27.collect import ledger, rcmap
from lm27.collect import run as R
from lm27.util import fsx, proc
from tests.collect.test_run_flow import CAPS, HARVEST_DONE, FlowBase, specs
from tests.fixtures.wp33.helpers import TODAY, hist, ident, pc_json, probe_result


def _arg(argv, flag):
    return argv[argv.index(flag) + 1] if flag in argv else None


class SinceWindowTest(FlowBase):
    """C03 — V6 기본 시작일이 수집기에 전달되고, 원장은 수집기가 맡은 창만 '읽었다'고 적는다."""

    def setUp(self):
        super().setUp()
        self.cfg = self.sb.cfg(**{"collect.webEverywhere": False})        # 기본: lookbackDays 120 · sinceYearStart 켜짐

    def test_default_run_passes_default_since_to_collectors(self):
        d = self.deps()
        res = self.collect(d, only=["mail.index", "cal.com", "pc.git"])
        self.assert_valid(res)
        since = ledger.default_since(self.cfg, date.fromisoformat(TODAY)).isoformat()
        self.assertEqual(since, "2026-01-01")
        for src in ("mail.index", "cal.com"):
            a = d.collector_calls(src)[0][2]
            self.assertEqual((_arg(a, "-Since"), _arg(a, "-Until")), (since, TODAY), src)
        g = d.collector_calls("pc.git")[0][2]
        self.assertEqual((_arg(g, "--from"), _arg(g, "--to")), (since, TODAY))

    def test_status_range_clips_observation_and_unread_days_stay_unobserved(self):
        # 색인이 2월·6월에 메일을 갖고 있어도 수집기가 맡은 창(7월 8일~)만 '읽었다' — 그 앞날은 zero_ok 가 아니다(T-09)
        st = {"rc": 0, "reasons": [], "range": ["2026-07-08", TODAY], "horizon_oldest": "2026-02-02"}
        d = self.deps(specs=specs(**{"mail.index": {"rc": 0, "records": [], "status": st}}))
        res = self.collect(d, only=["mail.index"])
        self.assert_valid(res)
        ml = self.stage(res, "mail_local")
        self.assertEqual(ml["srcs"]["mail.index"]["ranges"], [["2026-07-08", TODAY]])
        cells = {(c["date"], c["kind_axis"]): c["status"] for c in ledger.load_cells(self.sb.paths)
                 if c["src"] == "mail.index"}
        for day in ("2026-02-02", "2026-06-02"):
            self.assertEqual(cells[(day, "mail_in")], "not_attempted", day)
            self.assertIn(cells[(day, "mail_in")], rcmap.UNOBSERVED)
        self.assertEqual(cells[("2026-08-03", "mail_in")], "zero_ok")

    def test_agent_harvest_without_range_clipped_to_lookback(self):
        d = self.deps()                                             # HARVEST_DONE 흐름은 상태 줄이 없다(이전 판)
        res = self.collect(d, only=["pc.events", "pc.files"])
        self.assert_valid(res)
        pb = self.stage(res, "pc_bundle")
        self.assertEqual(pb["harvest"], "agent")
        self.assertEqual(pb["srcs"]["pc.events"]["ranges"], [["2026-06-07", TODAY]])   # 오늘 − 120일
        cells = {c["date"]: c["status"] for c in ledger.load_cells(self.sb.paths) if c["src"] == "pc.events"}
        self.assertEqual(cells["2026-03-02"], "not_attempted")
        self.assertEqual(cells["2026-09-01"], "zero_ok")

    def test_agent_harvest_status_range_used(self):
        streams = {s: dict(v) for s, v in HARVEST_DONE["result"]["streams"].items()}
        streams["pc.events"]["status"] = {"rc": 4, "reasons": [], "range": ["2026-05-01", TODAY]}
        hv = {"rc": 0, "done": True, "result": {"schema": "lm27.harvest_done/1", "streams": streams}}
        res = self.collect(self.deps(harvest=hv), only=["pc.events"])
        self.assertEqual(self.stage(res, "pc_bundle")["srcs"]["pc.events"]["ranges"], [["2026-05-01", TODAY]])


class NoAgentTest(FlowBase):
    """C04·C11 — V17: --no-agent 인데 예전 agent.json 이 남아 있어도 수송 실패가 아니다."""

    def _agent_json(self, impl):
        who = ident()
        p = self.sb.paths.agent_json()
        fsx.ensure_dir(os.path.dirname(p))
        fsx.atomic_write(p, fsx.canon_bytes({"schema": "lm27.agent/1", "install_id": who.install_id,
                                              "pc_id": who.pc_id, "impl": impl, "impl_reasons": []}))

    def test_no_agent_with_old_agent_json_is_skipped_not_transport(self):
        self._agent_json("py")
        d = self.deps()
        res = self.collect(d, no_agent=True)
        self.assert_valid(res)
        self.assertEqual(d.agent_calls, 0)
        pb = self.stage(res, "pc_bundle")
        sm = pb["srcs"]["pc.sampler"]
        self.assertEqual((sm["rc"], sm["skipped"]), (None, "agent_skipped"))
        self.assertNotIn("R-TRANSPORT", pb["reasons"])
        self.assertEqual(pb["state"], "done")
        self.assertIn(res.rc, (0, 4))
        cell = [c for c in ledger.load_cells(self.sb.paths) if c["src"] == "pc.sampler" and c["date"] == TODAY]
        self.assertEqual(cell[0]["status"], "not_attempted")              # transport_fail 아님

    def test_no_agent_impl_none_still_reports_clm(self):
        self._agent_json("none")
        res = self.collect(self.deps(), no_agent=True, only=["pc.sampler"])
        sm = self.stage(res, "pc_bundle")["srcs"]["pc.sampler"]
        self.assertEqual((sm["rc"], sm["reasons"]), (3, ["R-CLM"]))       # 실행 차단은 구조 사실 그대로


class WebProbeTest(FlowBase):
    """C05 — 웹 경로를 도는 PC 는 P-OWA·P-WEB 를 부탁하고, 그 caps 가 pc.json 에 남는다."""

    def setUp(self):
        super().setUp()
        self.cfg = self.sb.cfg(**{"collect.lookbackDays": 10, "collect.sinceYearStart": False})   # 웹 경로 모든 PC(기본)

    def test_web_role_asks_web_probes_and_records_caps(self):
        caps = dict(CAPS, **{"web_login": {"status": "ok", "value": {"login": "ok"}},
                             "mail.owa": {"status": "ok"}, "cal.owa": {"status": "ok"}, "teams.web": {"status": "ok"}})
        d = self.deps(probe=probe_result(caps))
        res = self.collect(d, only=["mail.index", "cal.owa"])
        self.assert_valid(res)
        self.assertEqual(d.probe_calls[0], {"web": True, "copilot": False})
        pc = self.sb.paths.pc_dir(res.pc_id)
        from lm27.bundle import pcreg
        got = pcreg.load_pc(pc)["capabilities"]
        for k in ("web_login", "mail.owa", "cal.owa", "teams.web"):
            self.assertIn(k, got)

    def test_web_probe_once_a_day_when_logged_in(self):
        who = ident()
        pc_json(self.sb.paths, who, caps={"web_login": hist((TODAY, "ok", [], "aaaaaaaaaaaa"))})
        d = self.deps()
        self.collect(d, only=["cal.owa"])
        self.assertEqual(d.probe_calls[0], {})                             # 오늘 이미 로그인 ok — 다시 띄우지 않는다
        d2 = self.deps()
        self.collect(d2, mode="probe-only")
        self.assertEqual(d2.probe_calls[0], {"web": True, "copilot": False})   # 탐침만 돌리는 실행은 언제나

    def test_no_web_role_no_web_probe(self):
        cfg = self.sb.cfg(**{"collect.lookbackDays": 10, "collect.webEverywhere": False})
        d = self.deps(cfg=cfg)
        self.collect(d, cfg=cfg, only=["mail.index"])
        self.assertEqual(d.probe_calls[0], {})


class LoginPendingFlowTest(FlowBase):
    """N1(V18) — 회사 계정이 없는 PC: 로그인 보류면 [수집]이 웹 경로에서 10분을 쓰지 않는다."""

    def setUp(self):
        super().setUp()
        self.cfg = self.sb.cfg(**{"collect.lookbackDays": 10, "collect.sinceYearStart": False})

    def notices(self):
        return [e.get("text_ko") for e in self.events() if e["ev"] == "notice"]

    def test_probe_short_check_pending_skips_web_collectors(self):
        wl = {"status": "fail", "reasons": ["R-LOGIN"], "value": {"login": "login", "login_pending": True,
                                                                  "account": "personal"}}
        d = self.deps(probe=probe_result(dict(CAPS, web_login=wl)))
        res = self.collect(d)
        self.assert_valid(res)
        for src in ("mail.owa", "cal.owa", "teams.web"):
            self.assertEqual(d.collector_calls(src), [], src)              # Edge 를 다시 띄우지 않는다
        bo = self.stage(res, "backfill_owa")
        self.assertEqual((bo["srcs"]["cal.owa"]["rc"], bo["srcs"]["cal.owa"]["reasons"], bo["srcs"]["cal.owa"]["skipped"]),
                         (2, ["R-LOGIN"], "login_pending"))
        bt = self.stage(res, "backfill_teams_web")
        self.assertEqual(bt["srcs"]["teams.web"]["skipped"], "login_pending")
        self.assertIn("web_login_pending", res.notes)
        n = self.notices()
        self.assertIn(R.NOTICE_LOGIN_PENDING, n)
        self.assertIn(LOGIN_PERSONAL_TEXT, n)
        self.assertNotIn(R.NOTICE_LOGIN, n)
        self.assertEqual(n.count(R.NOTICE_LOGIN_PENDING), 1)               # 단계가 둘이어도 한 번
        self.assertFalse(rcmap.confirmable("R-LOGIN"))                     # 로그인 필요는 '불가' 확정 근거가 아니다

    def test_collector_status_login_pending_marks_skipped(self):
        st = {"rc": 2, "reasons": ["R-LOGIN"], "login_pending": True, "login_account": "personal"}
        d = self.deps(specs=specs(**{"cal.owa": {"rc": 2, "status": st}}))
        res = self.collect(d)
        self.assert_valid(res)
        self.assertEqual(len(d.collector_calls("cal.owa")), 1)             # 짧은 확인 한 번(세션이 30초만)
        self.assertEqual(d.collector_calls("teams.web"), [])               # 같은 프로필 — 다시 띄우지 않는다(V10)
        bo = self.stage(res, "backfill_owa")
        self.assertEqual(bo["srcs"]["cal.owa"]["skipped"], "login_pending")
        n = self.notices()
        self.assertIn(R.NOTICE_LOGIN_PENDING, n)
        self.assertIn(LOGIN_PERSONAL_TEXT, n)

    def test_first_login_required_waits_normally(self):
        st = {"rc": 2, "reasons": ["R-LOGIN"]}                             # 처음 보는 로그인 필요(보류 아님)
        d = self.deps(specs=specs(**{"cal.owa": {"rc": 2, "status": st}}))
        res = self.collect(d)
        bo = self.stage(res, "backfill_owa")
        self.assertEqual(bo["srcs"]["cal.owa"]["skipped"], "")
        self.assertIn(R.NOTICE_LOGIN, self.notices())


class OrphanStreamTest(FlowBase):
    """L13 — 손주가 수집기의 stdout·stderr 를 쥐고 남아도 연결자가 스트림 닫기에서 멈추지 않는다."""

    def test_grandchild_holding_pipes_does_not_block_collect(self):
        pid_file = self.sb.work / "orphan.pid"
        sp = specs(**{"pc.git": {"rc": 1, "status": {"rc": 1, "reasons": []}, "orphan_s": 40,
                                 "orphan_pid_file": str(pid_file)}})
        d = self.deps(specs=sp)

        def reap():
            if pid_file.is_file():
                pid = int(pid_file.read_text(encoding="utf-8").strip() or 0)
                if pid > 0 and proc.pid_alive(pid):
                    proc.kill_tree(pid)
        self.addCleanup(reap)
        t0 = time.monotonic()
        res = self.collect(d, only=["pc.git"])
        took = time.monotonic() - t0
        self.assertTrue(pid_file.is_file())
        pid = int(pid_file.read_text(encoding="utf-8"))
        self.assertTrue(proc.pid_alive(pid), "손주가 살아 있어야 재현된다")
        self.assertLess(took, 25.0)                                        # 손주(40초)를 기다리지 않는다
        pb = self.stage(res, "pc_bundle")
        self.assertEqual(pb["srcs"]["pc.git"]["rc"], 1)


if __name__ == "__main__":
    unittest.main()
