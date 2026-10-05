# -*- coding: utf-8 -*-
"""WP-23 Copilot 환경 판별(B §4.11) — 판별 표 6경우(시제품 proto_lm27 이식), 능력 조회, T53(웹 근거 읽기만)."""
from __future__ import annotations

import unittest

from lm27.bridge.clock import VirtualClock
from lm27.bridge.env import CopilotEnv, ProfileCaps, derive_env, detect_env, exposed, manual_env, recompute

from tests.bridge.fake_cdp import FakePage
from tests.bridge.fake_http import World

# (이름, dom, 조회 성공 이력, R-NOLIC 이력, 기대 (tier, work_mode, web_grounding, web_exposed)) — B §4.11 판별 표
ENV_CASES = [
    ("업무 탭·업무·웹 근거 끔·조회 성공", {"toggle": {"found": True, "work": True}, "wg": {"found": True, "checked": False}},
     True, False, ("premium", "work", "off", False)),
    ("위와 같은데 웹 근거 켜짐", {"toggle": {"found": True, "work": True}, "wg": {"found": True, "checked": True}},
     True, False, ("premium", "work", "on", True)),
    ("업무 선택·웹 근거 요소 없음·이력 없음", {"toggle": {"found": True, "work": True}, "wg": {"found": False}},
     False, False, ("unknown", "work", "unknown", True)),
    ("업무 탭 없음·R-NOLIC 이력", {"toggle": {"found": False}, "wg": {"found": False}},
     False, True, ("basic", "web", "unknown", True)),
    ("업무 탭 없음·이력 없음(첫 호출)", {"toggle": {"found": False}, "wg": {"found": False}},
     False, False, ("unknown", "unknown", "unknown", True)),
    ("업무 탭 있으나 전환 실패(웹 고정)", {"toggle": {"found": True, "web": True}, "wg": {"found": False}},
     False, False, ("unknown", "web", "unknown", True)),
]


class TestDeriveTable(unittest.TestCase):
    def test_six_cases(self):
        for name, dom, ok, nolic, want in ENV_CASES:
            with self.subTest(name):
                e = derive_env(dom, cap_ok_recent=ok, nolic_recent=nolic, identity_strong=True, prefer_work_mode=True)
                self.assertEqual((e.tier, e.work_mode, e.web_grounding, e.web_exposed), want)

    def test_exposed_only_when_work_and_off(self):
        for wm in ("work", "web", "unknown"):
            for wg in ("on", "off", "unknown"):
                self.assertEqual(exposed(wm, wg), not (wm == "work" and wg == "off"))

    def test_weak_identity_toggle_unknown(self):
        e = derive_env({"toggle": {"found": False}}, cap_ok_recent=False, nolic_recent=False, identity_strong=False,
                       prefer_work_mode=True)
        self.assertEqual(e.work_toggle, "unknown")
        self.assertNotIn("toggle_absent", e.evidence)

    def test_switch_failed_evidence(self):
        e = derive_env({"toggle": {"found": True, "web": True}}, cap_ok_recent=False, nolic_recent=False,
                       identity_strong=True, prefer_work_mode=True)
        self.assertIn("switch_failed", e.evidence)

    def test_dict_roundtrip(self):
        e = derive_env(ENV_CASES[0][1], cap_ok_recent=True, nolic_recent=False, identity_strong=True,
                       prefer_work_mode=True, checked_at="2026-10-05T10:15:42+09:00")
        e2 = CopilotEnv.from_dict(e.to_dict())
        self.assertEqual(e2, e)
        self.assertEqual(set(e.brief()), {"tier", "work_toggle", "work_mode", "web_grounding", "web_exposed"})
        bad = CopilotEnv.from_dict({"tier": "gold", "work_mode": "work", "web_grounding": "off", "evidence": ["x"]})
        self.assertEqual((bad.tier, bad.web_exposed, bad.evidence), ("unknown", False, []))

    def test_manual_env(self):
        e = manual_env(VirtualClock())
        self.assertEqual((e.tier, e.work_mode, e.web_grounding, e.web_exposed), ("unknown",) * 3 + (True,))


class TestProfileCaps(unittest.TestCase):
    def test_ttl_window(self):
        caps = {"lookup_mail": {"state": "ok", "checks": [{"date": "2026-10-01", "result": "ok"}]},
                "lookup_teams": {"state": "suspect",
                                 "checks": [{"date": "2026-09-01", "result": "unavailable", "reason": "R-NOLIC"}]}}
        pc = ProfileCaps(caps, "2026-10-05")
        self.assertTrue(pc.any_ok_within(14))
        self.assertFalse(pc.any_ok_within(2))
        self.assertFalse(pc.any_reason_within("R-NOLIC", 14))
        self.assertTrue(pc.any_reason_within("R-NOLIC", 40))
        self.assertFalse(ProfileCaps(None, "2026-10-05").any_ok_within(14))
        self.assertTrue(ProfileCaps({"lookup_calendar": {"checks": [{"date": "2026-10-04", "reasons": ["R-NOLIC"]}]}},
                                    "2026-10-05").any_reason_within("R-NOLIC", 14))


class _Caps:
    def __init__(self, ok=False, nolic=False):
        self.ok, self.nolic = ok, nolic

    def any_ok_within(self, days):
        return self.ok

    def any_reason_within(self, code, days):
        return self.nolic and code == "R-NOLIC"


class TestDetectOnSession(unittest.TestCase):
    def world(self, **page):
        w = World(page_factory=lambda url: FakePage(w.clock, url=url, **page))
        self.addCleanup(w.cleanup)
        return w

    def test_T53_web_grounding_on_is_read_only(self):
        w = self.world(web_grounding="on")
        s = w.session()
        self.assertEqual(s.start(), "ready")
        self.addCleanup(s.close)
        self.assertEqual(s.env.web_grounding, "on")
        self.assertTrue(s.env.web_exposed)
        page = w.net.our_pages()[0]
        self.assertFalse([c for c in page.clicks if "ground" in c or c.startswith("wg")])
        self.assertEqual(s.profile.load()["env"]["web_grounding"], "on")

    def test_premium_work_off_not_exposed(self):
        w = self.world(web_grounding="off")
        s = w.session()
        s.start()
        self.addCleanup(s.close)
        e = detect_env(s, _Caps(ok=True))
        self.assertEqual((e.tier, e.work_mode, e.web_grounding, e.web_exposed), ("premium", "work", "off", False))

    def test_basic_no_toggle(self):
        w = self.world(work_toggle=False)
        s = w.session()
        s.start()
        self.addCleanup(s.close)
        e = detect_env(s, _Caps(nolic=True))
        self.assertEqual((e.tier, e.work_toggle, e.work_mode, e.web_exposed), ("basic", "absent", "web", True))

    def test_recompute_without_screen(self):
        w = self.world(web_grounding="off")
        s = w.session()
        s.start()
        self.addCleanup(s.close)
        e0 = detect_env(s, _Caps())
        self.assertEqual((e0.tier, e0.web_exposed), ("unknown", False))
        page = w.net.our_pages()[0]
        n_evals = len(page.evals)
        e1 = recompute(e0, _Caps(ok=True), w.cfg, w.clock)
        self.assertEqual((e1.tier, e1.work_mode, e1.web_grounding, e1.web_exposed), ("premium", "work", "off", False))
        self.assertEqual(len(page.evals), n_evals)                # 화면은 다시 읽지 않는다
        e2 = recompute(e1, _Caps(nolic=True), w.cfg, w.clock)
        self.assertEqual(e2.tier, "basic")

    def test_prefer_work_mode_switch(self):
        w = self.world(work_mode="web")
        s = w.session()
        s.start()
        self.addCleanup(s.close)
        page = w.net.our_pages()[0]
        self.assertIn("work_toggle", page.clicks)
        self.assertEqual(s.info.work_mode, "work")
        self.assertEqual(s.env.work_mode, "work")

    def test_switch_failed_stays_web(self):
        w = self.world(work_mode="web", work_switch_ok=False)
        s = w.session()
        s.start()
        self.addCleanup(s.close)
        self.assertEqual(s.env.work_mode, "web")
        self.assertIn("switch_failed", s.env.evidence)


if __name__ == "__main__":
    unittest.main()
