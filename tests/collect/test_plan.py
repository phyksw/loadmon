# -*- coding: utf-8 -*-
"""WP-33 계획(lm27.collect.plan) — 단계 순서·역할·백필 PC·탐침 건너뜀·--only·readProtected(계약 §2.5 · C §1 · §8.2 · D-6)."""
from __future__ import annotations

import unittest

from lm27.collect import plan
from tests.fixtures.wp33.helpers import Sandbox

PC1 = {"pc_id": "pc_" + "1" * 16, "kind": "desktop", "label_auto": "PC1", "first_seen": "2026-09-01T00:00:00Z"}
PC2 = {"pc_id": "pc_" + "2" * 16, "kind": "laptop", "label_auto": "PC2", "label_user": "홍길동 노트북",
       "first_seen": "2026-09-02T00:00:00Z"}
CLOUD = {"pc_id": "pc_" + "c" * 16, "kind": "cloud", "label_auto": "클라우드PC", "first_seen": "2026-09-03T00:00:00Z"}


def names(stages):
    return [s.name for s in stages]


class PlanCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sb = Sandbox(scripts=False)
        cls.cfg = cls.sb.cfg(**{"collect.webEverywhere": False, "collect.sinceYearStart": False})   # 예전 의미(백필 PC 한 대) — 새 기본값은 WebEverywherePlan

    @classmethod
    def tearDownClass(cls):
        cls.sb.cleanup()

    def test_order_and_local_stages_on_work_pc(self):
        roles = plan.pc_roles(PC1, pcs=[PC1, CLOUD], cfg=self.cfg)
        self.assertEqual(roles, ("mail_local", "pc_usage", "teams_window"))
        st = plan.stage_plan(roles, {}, None, cfg=self.cfg)
        self.assertEqual(names(st), ["probe", "pc_bundle", "mail_local", "cal_local", "teams_uia_check", "import",
                                     "export", "derive", "upload"])
        by = {s.name: s for s in st}
        self.assertEqual(by["mail_local"].srcs, ("mail.com", "mail.index"))      # COM → 색인(교차검증, 항상)
        self.assertEqual(by["pc_bundle"].srcs, ("pc.sampler", "pc.events", "pc.files", "pc.mru", "pc.recent",
                                                "pc.git"))                    # 라이선스는 옵트인(꺼짐)
        for s in st:                                                          # 계약 §8.5 단계 이름만
            self.assertIn(s.name, plan.RUN_ORDER)

    def test_backfill_and_copilot_only_on_cloud(self):
        roles = plan.pc_roles(CLOUD, pcs=[PC1, CLOUD], cfg=self.cfg)
        self.assertIn("account_backfill", roles)
        self.assertIn("copilot", roles)
        st = {s.name: s for s in plan.stage_plan(roles, {}, None, cfg=self.cfg)}
        self.assertEqual(st["backfill_owa"].srcs, ("mail.owa", "cal.owa"))
        self.assertEqual(st["backfill_teams_web"].srcs, ("teams.web",))
        # bridge.stages 기본: lookup_mail·lookup_teams 켜짐, lookup_calendar 꺼짐(X-138)
        self.assertEqual(st["copilot_lookup"].srcs, ("mail.copilot", "teams.copilot"))
        # 업무 PC 에는 백필·코파일럿 없음(C §1 — '첫 성공에서 멈추는 사슬' 아님, 역할 분담)
        st1 = names(plan.stage_plan(plan.pc_roles(PC1, pcs=[PC1, CLOUD], cfg=self.cfg), {}, None, cfg=self.cfg))
        self.assertNotIn("backfill_owa", st1)
        self.assertNotIn("copilot_lookup", st1)

    def test_backfill_pc_designated_by_label(self):
        cfg = self.sb.cfg(**{"collect.backfillPc": "홍길동 노트북", "collect.webEverywhere": False})
        self.assertEqual(plan.backfill_pc_id([PC1, PC2, CLOUD], cfg), PC2["pc_id"])
        roles = plan.pc_roles(PC2, pcs=[PC1, PC2, CLOUD], cfg=cfg)
        self.assertIn("account_backfill", roles)
        self.assertNotIn("copilot", roles)                                  # 코파일럿은 클라우드PC 에서만
        self.assertNotIn("account_backfill", plan.pc_roles(CLOUD, pcs=[PC1, PC2, CLOUD], cfg=cfg))
        # 기본(cloud) 인데 클라우드PC 가 없으면 백필 PC 없음(배정 대기)
        self.assertIsNone(plan.backfill_pc_id([PC1, PC2], self.cfg))

    def test_pc_role_flag(self):
        self.assertIn("account_backfill", plan.pc_roles(PC1, pcs=[PC1], cfg=self.cfg, pc_role="cloud"))
        self.assertNotIn("copilot", plan.pc_roles(CLOUD, pcs=[CLOUD], cfg=self.cfg, pc_role="pc1"))
        with self.assertRaises(ValueError):
            plan.pc_roles(PC1, pcs=[PC1], cfg=self.cfg, pc_role="pc9")

    def test_probe_blocked_com_is_planned_skip_but_index_still_runs(self):
        caps = {"mail.com": {"status": "fail", "reasons": ["R-NEWOL"]},
                "cal.com": {"status": "fail", "reasons": ["R-NEWOL"]},
                "mail.index": {"status": "fail", "reasons": ["R-NEWOL"]}}
        st = {s.name: s for s in plan.stage_plan(plan.ROLES_PC, caps, None, cfg=self.cfg)}
        self.assertEqual(st["mail_local"].srcs, ("mail.index",))            # X-124 — 색인은 시도
        self.assertEqual(st["mail_local"].skip["mail.com"], {"rc": 3, "reasons": ["R-NEWOL"], "why": "probe"})
        self.assertEqual(st["cal_local"].skip["cal.com"]["reasons"], ["R-NEWOL"])

    def test_transient_or_warning_probe_does_not_skip(self):
        caps = {"mail.com": {"status": "transport_fail", "reasons": ["R-COM-BUSY"]},
                "cal.com": {"status": "ok", "reasons": ["R-OMG", "R-SUBFOLDER"]}}
        st = {s.name: s for s in plan.stage_plan(plan.ROLES_PC, caps, None, cfg=self.cfg)}
        self.assertIn("mail.com", st["mail_local"].srcs)
        self.assertIn("cal.com", st["cal_local"].srcs)
        self.assertFalse(st["mail_local"].skip)

    def test_confirmed_blocked_capability_is_skipped(self):
        caps = {"mail.owa": {"verdict": "불가(확정)", "reasons": ["R-EDGEPOL"]},
                "edge_cdp_policy": {"status": "ok", "reasons": []}}
        roles = plan.pc_roles(CLOUD, pcs=[CLOUD], cfg=self.cfg)
        st = {s.name: s for s in plan.stage_plan(roles, caps, None, cfg=self.cfg)}
        self.assertEqual(st["backfill_owa"].srcs, ("cal.owa",))
        self.assertEqual(st["backfill_owa"].skip["mail.owa"], {"rc": 3, "reasons": ["R-EDGEPOL"], "why": "confirmed"})
        # Edge 정책이 막혔으면(탐침 fail) 웹 백필 전부 계획 건너뜀
        caps2 = {"edge_cdp_policy": {"status": "fail", "reasons": ["R-EDGEPOL"]}}
        st2 = {s.name: s for s in plan.stage_plan(roles, caps2, None, cfg=self.cfg)}
        self.assertEqual(st2["backfill_owa"].srcs, ())
        self.assertEqual(sorted(st2["backfill_owa"].skip), ["cal.owa", "mail.owa"])
        self.assertEqual(st2["backfill_teams_web"].skip["teams.web"]["reasons"], ["R-EDGEPOL"])

    def test_only_filter_and_no_upload(self):
        st = plan.stage_plan(plan.ROLES_PC, {}, ["mail.index", "pc.git"], cfg=self.cfg)
        self.assertEqual(names(st), ["probe", "pc_bundle", "mail_local", "export", "derive"])
        self.assertEqual({s.name: s.srcs for s in st}["pc_bundle"], ("pc.git",))
        with self.assertRaises(ValueError):
            plan.stage_plan(plan.ROLES_PC, {}, ["mail.nope"], cfg=self.cfg)

    def test_license_and_calendar_lookup_opt_in(self):
        cfg = self.sb.cfg(**{"pc.license.enabled": True,
                             "bridge.stages": {"lookup_calendar": True, "lookup_mail": False}})
        roles = plan.pc_roles(CLOUD, pcs=[CLOUD], cfg=cfg)
        st = {s.name: s for s in plan.stage_plan(roles, {}, None, cfg=cfg)}
        self.assertIn("pc.compute", st["pc_bundle"].srcs)
        self.assertEqual(st["copilot_lookup"].srcs, ("teams.copilot", "cal.copilot"))

    def test_read_protected(self):
        ok = {"mail.com": {"value": {"omg": False, "attach": "ok"}}}
        self.assertEqual(plan.read_protected(self.cfg, ok), "1")
        self.assertEqual(plan.read_protected(self.cfg, {"mail.com": {"value": {"omg": True, "attach": "ok"}}}), "0")
        self.assertEqual(plan.read_protected(self.cfg, {"mail.com": {"value": {"omg": None}}}), "0")
        self.assertEqual(plan.read_protected(self.cfg, {}), "0")
        self.assertEqual(plan.read_protected(self.sb.cfg(**{"mail.com.readProtected": "1"}), {}), "1")

    def test_spec_limits_and_stage_of(self):
        self.assertEqual(plan.stage_of("mail.com"), "mail_local")
        self.assertEqual(plan.COLLECTORS["mail.com"].limit_s(self.cfg), 360 + plan.PS_SLACK_S)
        self.assertEqual(plan.COLLECTORS["pc.events"].limit_s(self.cfg), 90.0)
        self.assertIsNone(plan.COLLECTORS["mail.import"].limit_s(self.cfg))
        self.assertEqual(plan.parallel_max(self.cfg), 2)
        with self.assertRaises(ValueError):
            plan.stage_of("nope")


if __name__ == "__main__":
    unittest.main()


class WebEverywherePlan(unittest.TestCase):
    """계약 v1.3 §0.8 V5: 기본값이면 업무 PC 에도 Outlook 웹·팀즈 웹 단계가 있다(LM24 와 같음). 코파일럿은 그대로 클라우드PC."""

    @classmethod
    def setUpClass(cls):
        cls.sb = Sandbox(scripts=False)
        cls.cfg = cls.sb.cfg()

    @classmethod
    def tearDownClass(cls):
        cls.sb.cleanup()

    def test_default_is_on(self):
        self.assertTrue(plan.web_everywhere(self.cfg))

    def test_work_pc_gets_web_paths(self):
        roles = plan.pc_roles(PC1, pcs=[PC1], cfg=self.cfg)
        self.assertIn(plan.ROLE_BACKFILL, roles)
        self.assertNotIn(plan.ROLE_COPILOT, roles)
        st = {s.name: s for s in plan.stage_plan(roles, {}, None, cfg=self.cfg)}
        self.assertIn("mail.owa", st["backfill_owa"].srcs)
        self.assertIn("cal.owa", st["backfill_owa"].srcs)
        self.assertIn("teams.web", st["backfill_teams_web"].srcs)
        self.assertNotIn("copilot_lookup", st)

    def test_work_pc_with_cloud_still_gets_web_paths(self):
        roles = plan.pc_roles(PC1, pcs=[PC1, CLOUD], cfg=self.cfg)
        self.assertIn(plan.ROLE_BACKFILL, roles)
