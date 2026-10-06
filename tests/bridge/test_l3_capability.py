# -*- coding: utf-8 -*-
"""WP-24 조회 능력 기록(B §7.13) — B-T41(같은 날 2회 → suspect 유지, 다른 날 → unavailable 14일, 수송 실패는 무변화) ·
R-NOLIC 계정 단위 · TTL 해제 · 계정 등급 판별 메서드 · 내보내기 형 · PC 능력 기록(record_probe 만) ·
B-T49(무라이선스: 세 조회 함께 기록, 같은 호출의 다른 조회는 전송 0, 분석 단계는 엄격 규칙으로 진행)."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from lm27.bridge import capability as CP
from lm27.bridge.clock import VirtualClock
from lm27.bridge.env import CopilotEnv
from lm27.bridge.session import BridgeProfile
from lm27.bundle import pcreg
from lm27.paths import Paths
from lm27.util import events

from tests.fixtures.wp24.rig import Rig, act_rows, settings, window_rows
from tests.fixtures.wp24.stages import ActStage, LookupStage, LookupTeams

DAY = 86400.0
PC = "pc_0123456789abcdef"


def setUpModule():
    events.configure(mode="off")


class Machine(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="lm27t_wp24_")
        self.paths = Paths(self.tmp + "/root", lad=self.tmp + "/lad")
        self.cfg, self.raw = settings(self.tmp)
        self.clk = VirtualClock()
        self.prof = BridgeProfile(self.paths)

    def caps(self):
        return CP.Capabilities(self.prof, self.cfg, self.clk)

    def test_T41_two_dates_confirm(self):
        c = self.caps()
        c.observe_unavailable("lookup_teams", "R-NOCONN")
        c.observe_unavailable("lookup_teams", "R-NOCONN")              # 같은 날 두 번
        self.assertEqual((c.state("lookup_teams"), c.confirmed_days("lookup_teams")), ("suspect", 1))
        self.assertTrue(c.checked_today("lookup_teams"))
        self.clk.advance(DAY)
        c2 = self.caps()                                                # 다음 호출(파일에서 다시 읽음)
        self.assertFalse(c2.checked_today("lookup_teams"))
        c2.observe_unavailable("lookup_teams", "R-NOCONN")
        self.assertEqual(c2.state("lookup_teams"), "unavailable")
        self.assertEqual(c2.caps["lookup_teams"]["until"],
                         (__import__("datetime").date.fromisoformat(c2.today) +
                          __import__("datetime").timedelta(days=self.cfg.confirm_ttl_days)).isoformat())
        self.assertEqual(c2.state("lookup_mail"), "unknown")             # R-NOCONN 은 단계별
        self.clk.advance(DAY * (self.cfg.confirm_ttl_days + 1))
        c3 = self.caps()
        self.assertEqual(c3.state("lookup_teams"), "unknown")
        self.assertTrue(c3.recheck_pending("lookup_teams"))

    def test_ok_resets_and_env_methods(self):
        c = self.caps()
        c.observe_unavailable("lookup_mail", "R-NOCONN")
        c.observe_ok("lookup_mail")
        self.assertEqual((c.state("lookup_mail"), c.confirmed_days("lookup_mail")), ("ok", 0))
        self.assertTrue(c.any_ok_within(self.cfg.confirm_ttl_days))
        self.assertFalse(c.any_reason_within("R-NOLIC", self.cfg.confirm_ttl_days))

    def test_nolic_account_level(self):
        c = self.caps()
        c.observe_unavailable("lookup_mail", "R-NOLIC")
        self.assertEqual({c.state(s) for s in CP.LOOKUP_STAGES}, {"suspect"})
        self.assertTrue(c.any_reason_within("R-NOLIC", self.cfg.confirm_ttl_days))
        self.assertIn(("BR-NOLIC", "lookup_mail"), c.events)
        ex = c.export()
        self.assertEqual(set(ex), {"mail.copilot", "teams.copilot", "cal.copilot"})
        self.assertEqual((ex["mail.copilot"]["verdict"], ex["mail.copilot"]["reasons"]), ("불가(잠정)", ["R-NOLIC"]))

    def test_record_pc_via_record_probe(self):
        pcdir = self.paths.pc_dir(PC)
        pcreg.update_pc(pcdir, changes={})
        c = self.caps()
        c.observe_ok("lookup_mail")
        c.observe_unavailable("lookup_teams", "R-NOCONN")
        self.assertEqual(c.record_pc(self.paths, PC, self.raw), 3)
        caps = pcreg.load_pc(pcdir)["capabilities"]
        self.assertEqual(caps["mail.copilot"]["verdict"], "가능")
        self.assertEqual(caps["teams.copilot"]["verdict"], "불가(잠정)")
        self.assertEqual(caps["copilot_connector"]["value"], {"calendar": "미확인", "mail": "가능",
                                                              "teams": "불가(잠정)"})
        self.assertEqual(c.record_pc(self.paths, "pc_ffffffffffffffff", self.raw), 0)     # pc.json 없으면 건너뜀


class RunnerLookup(unittest.TestCase):
    def test_T49_nolic_skips_other_lookup_and_analysis_goes_strict(self):
        env = CopilotEnv(tier="unknown", work_toggle="absent", work_mode="unknown", web_grounding="unknown",
                         web_exposed=True)
        stages = [LookupStage(), LookupTeams(), ActStage()]
        r = Rig(stages=stages, env=env, script={"lookup_mail": ["nolic", "nolic"]})
        self.addCleanup(r.cleanup)
        r.write_ai_in("lookup_mail", window_rows("lookup_mail", [("2026-09-01", "2026-09-07")]))
        r.write_ai_in("lookup_teams", window_rows("lookup_teams", [("2026-09-01", "2026-09-07")]))
        r.write_ai_in("t_act", act_rows(3))
        res = r.run()
        self.assertEqual((res["lookup_mail"]["stop_kind"], res["lookup_mail"]["reason"]), ("refused", "R-NOLIC"))
        self.assertEqual((res["lookup_teams"]["state"], res["lookup_teams"]["reason"]),
                         ("skipped", "capability_unavailable"))
        self.assertEqual(r.responder.count["lookup_teams"], 0)
        self.assertEqual((r.rt.env.tier, r.rt.env.work_mode, r.rt.env.web_exposed), ("basic", "web", True))
        self.assertEqual(res["t_act"]["state"], "done")
        self.assertTrue(res["t_act"]["gate"]["web"]["exposed"])
        self.assertIn("BR-NOLIC", r.notified())
        caps = json.loads(Path(r.paths.ai_run(r.run_id), "capabilities.json").read_text("utf-8"))
        self.assertEqual({v["state"] for v in caps.values()}, {"suspect"})
        self.assertEqual({tuple(v["reasons"]) for v in caps.values()}, {("R-NOLIC",)})

    def test_noconn_suspect_notice_uses_korean_label(self):
        """R-NOCONN 은 단계별(다른 조회 무변화) · 알림 자리 값은 단계 ID 가 아니라 한국어 출처 이름."""
        r = Rig(stages=[LookupStage(), LookupTeams()], script={"lookup_mail": ["unavailable"]})
        self.addCleanup(r.cleanup)
        r.write_ai_in("lookup_mail", window_rows("lookup_mail", [("2026-09-01", "2026-09-02")]))
        r.write_ai_in("lookup_teams", window_rows("lookup_teams", [("2026-09-01", "2026-09-02")]))
        res = r.run()
        self.assertEqual((res["lookup_mail"]["stop_kind"], res["lookup_mail"]["reason"]), ("refused", "R-NOCONN"))
        self.assertEqual(res["lookup_teams"]["state"], "done")
        self.assertEqual((r.rt.caps.state("lookup_mail"), r.rt.caps.state("lookup_teams")), ("suspect", "ok"))
        body = [f["body"] for ev, f in r.events if ev == "notice" and f.get("code") == "BR-LOOKUP-SUSPECT"]
        self.assertEqual(len(body), 1)
        self.assertIn("메일 조회", body[0])
        self.assertNotIn("lookup_", body[0])

    def test_transport_failure_does_not_touch_capability(self):
        r = Rig(stages=[LookupStage()], script={"lookup_mail": ["phase:login_required"]})
        self.addCleanup(r.cleanup)
        r.write_ai_in("lookup_mail", window_rows("lookup_mail", [("2026-09-01", "2026-09-02")]))
        res = r.run()["lookup_mail"]
        self.assertEqual((res["stop_kind"], res["reason"]), ("fatal", "login_required"))
        self.assertEqual(r.rt.caps.state("lookup_mail"), "unknown")
        self.assertIn("BR-LOGIN-TIMEOUT", r.notified())

    def test_mode_web_skips_lookup(self):
        r = Rig(stages=[LookupStage()], env=CopilotEnv(tier="premium", work_toggle="present", work_mode="web",
                                                         web_grounding="off", web_exposed=True))
        self.addCleanup(r.cleanup)
        r.write_ai_in("lookup_mail", window_rows("lookup_mail", [("2026-09-01", "2026-09-02")]))
        res = r.run()["lookup_mail"]
        self.assertEqual((res["state"], res["reason"], r.transport.sends), ("skipped", "mode_web", 0))
        self.assertIn("BR-WEB-MODE", r.notified())


if __name__ == "__main__":
    unittest.main()
