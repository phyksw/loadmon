# -*- coding: utf-8 -*-
"""WP-25 probe_copilot.py(P-CP) 시험 — ``lm27.bridge.probe`` 결과(확인 항목·env)와 조회 능력 상태 → ``lm27.probe/1``
(v1.2 C18) caps 5종(copilot_env · copilot_connector · mail/teams/cal.copilot)·사유(R-NOAPP · R-EDGEPOL · R-LOGIN · R-NOLIC ·
R-NOCONN · R-TRANSPORT)·sig(구조 사실만) · bridge.mode=off 면 skipped · stdout 한 줄 JSON · rc 0/3. 실제 Edge·Copilot 0 —
브리지 탐침 함수와 능력 상태를 주입한다(계약 §11.3 의 스텁 대신 결과 모양 주입)."""
from __future__ import annotations

import io
import json
import unittest

from tests.fixtures.wp25 import kit as K

P = K.probe_module()
R_ = "R-"


def checks(**over) -> list:
    base = {"stub_env": True, "edge": True, "policy": True, "lock": True, "port": True, "launch": True, "origin": True,
            "tab": True, "identity": True, "login": True, "work_mode": True, "tier": True, "web_grounding": True,
            "web_exposed": True, "roundtrip": True, "calib": True, "lookup_mail": True, "lookup_teams": True}
    codes = {}
    for k, v in over.items():
        if isinstance(v, tuple):
            base[k], codes[k] = v
        elif v is None:
            base.pop(k, None)
        else:
            base[k] = v
    out = []
    for cid, ok in base.items():
        c = {"id": cid, "ok": bool(ok), "value": "2026-09-30" if cid == "calib" else "", "code": codes.get(cid, ""),
             "hint": ""}
        out.append(c)
    return out


ENV = {"tier": "premium", "work_toggle": "present", "work_mode": "work", "web_grounding": "off", "web_exposed": False}


def probe_res(**over):
    return {"ok": True, "recommend": "auto", "sec": 12.0, "env": dict(ENV), "checks": checks(**over), "rc": 0}


def states(mail="ok", teams="ok", cal="unknown", reasons=(), today=False):
    return {"lookup_mail": {"state": mail, "reasons": list(reasons), "today": today},
            "lookup_teams": {"state": teams, "reasons": list(reasons), "today": today},
            "lookup_calendar": {"state": cal, "reasons": list(reasons), "today": today}}


class BuildCaps(unittest.TestCase):
    def test_ready_and_lookups_ok(self):
        caps, warn = P.build_caps(probe_res(), states())
        self.assertEqual(sorted(caps), sorted(P.CAP_KEYS))
        self.assertEqual((caps["copilot_env"]["status"], caps["copilot_env"]["ok"]), ("ok", True))
        self.assertEqual(caps["copilot_env"]["value"]["tier"], "premium")
        self.assertEqual(caps["copilot_env"]["value"]["calib_date"], "2026-09-30")
        self.assertEqual((caps["mail.copilot"]["status"], caps["teams.copilot"]["status"], caps["cal.copilot"]["status"]),
                         ("ok", "ok", "unknown"))
        self.assertEqual(caps["copilot_connector"]["status"], "ok")
        self.assertEqual(caps["copilot_connector"]["value"], {"mail": "가능", "teams": "가능", "calendar": "미확인"})
        self.assertEqual(warn, [])
        for c in caps.values():
            self.assertRegex(c["sig"], r"^[0-9a-f]{12}$")

    def test_nolic_account_level(self):
        res = probe_res(lookup_mail=(False, "unavailable"), lookup_teams=(False, "unavailable"))
        res["env"] = dict(ENV, tier="basic", work_mode="web", web_exposed=True)
        caps, _w = P.build_caps(res, states("suspect", "suspect", "suspect", [R_ + "NOLIC"], today=True))
        for key in ("mail.copilot", "teams.copilot", "cal.copilot"):
            self.assertEqual((caps[key]["status"], caps[key]["reasons"]), ("fail", [R_ + "NOLIC"]), key)
        self.assertEqual((caps["copilot_connector"]["status"], caps["copilot_connector"]["reasons"]),
                         ("fail", [R_ + "NOLIC"]))
        self.assertEqual(caps["copilot_env"]["reasons"], [R_ + "NOLIC"])

    def test_noconn_teams_only(self):
        caps, _w = P.build_caps(probe_res(lookup_teams=(False, "unavailable")),
                                {**states(), "lookup_teams": {"state": "suspect", "reasons": [R_ + "NOCONN"], "today": True}})
        self.assertEqual((caps["mail.copilot"]["status"], caps["teams.copilot"]["reasons"]), ("ok", [R_ + "NOCONN"]))
        self.assertEqual(caps["copilot_connector"]["status"], "ok")

    def test_session_failures(self):
        cases = {
            "edge": (probe_res(edge=(False, "edge_not_found"), login=(False, "edge_not_found"), lookup_mail=None,
                               lookup_teams=None), "fail", [R_ + "NOAPP"]),
            "policy": (probe_res(launch=(False, "policy_blocked"), login=(False, "policy_blocked"), lookup_mail=None,
                                 lookup_teams=None), "fail", [R_ + "EDGEPOL"]),
            "login": (probe_res(login=(False, "login_required"), lookup_mail=None, lookup_teams=None), "fail",
                      [R_ + "LOGIN"]),
            "dead": (probe_res(login=(False, "dead_session"), lookup_mail=None, lookup_teams=None), "transport_fail",
                     [R_ + "TRANSPORT"]),
        }
        sigs = set()
        for name, (res, status, reasons) in cases.items():
            with self.subTest(name):
                caps, warn = P.build_caps(res, states("unknown", "unknown"))
                self.assertEqual((caps["copilot_env"]["status"], caps["copilot_env"]["reasons"]), (status, reasons))
                self.assertEqual(caps["copilot_connector"]["status"], "unknown")
                self.assertEqual(caps["mail.copilot"]["status"], "unknown")
                self.assertTrue(warn)
                sigs.add(caps["copilot_env"]["sig"])
        self.assertEqual(len(sigs), 4)                                   # 환경이 다르면 sig 도 다르다

    def test_sig_ignores_counts(self):
        a, _ = P.build_caps(probe_res(), states())
        res = probe_res()
        res["sec"] = 99.0
        b, _ = P.build_caps(res, states())
        self.assertEqual({k: v["sig"] for k, v in a.items()}, {k: v["sig"] for k, v in b.items()})


class Main(unittest.TestCase):
    def setUp(self):
        self.sb = K.Sandbox()
        self.addCleanup(self.sb.cleanup)

    def run_main(self, argv, **kw):
        out, err = io.StringIO(), io.StringIO()
        rc = P.main(argv, environ=kw.pop("environ", {}), paths=self.sb.paths, cfg=kw.pop("cfg", self.sb.cfg), now=K.NOW,
                    out=out, err=err, **kw)
        lines = out.getvalue().splitlines()
        self.assertEqual(len(lines), 1)                                  # stdout 은 결과 한 줄만
        return rc, json.loads(lines[0]), err.getvalue()

    def test_output_shape(self):
        seen = {}

        def fake_probe(**kw):
            seen.update(kw)
            return probe_res()
        rc, res, err = self.run_main(["--pc", K.PC], probe_fn=fake_probe, states_fn=lambda p, s: states(),
                                     environ={"LM_COPILOT_STUB": "x"})
        self.assertEqual(rc, 0)
        self.assertEqual(set(res), {"schema", "now_utc", "elapsed_ms", "budget_sec", "budget_hit", "synthetic", "groups",
                                    "warnings", "stub_env", "cfg_used", "caps", "probe_rc"})
        self.assertEqual((res["schema"], res["groups"], res["synthetic"], res["stub_env"], res["budget_sec"]),
                         ("lm27.probe/1", {"P-CP": "done"}, True, ["LM_COPILOT_STUB"], 60))
        self.assertEqual((seen["roundtrip"], seen["lookup"], seen["rt_kw"]["pc_id"]), (True, True, K.PC))
        self.assertIn("[P-CP]", err)

    def test_no_roundtrip_no_lookup_flags(self):
        seen = {}

        def fake_probe(**kw):
            seen.update(kw)
            return probe_res(lookup_mail=None, lookup_teams=None)
        rc, res, _e = self.run_main(["--no-roundtrip", "--no-lookup"], probe_fn=fake_probe,
                                    states_fn=lambda p, s: states("unknown", "unknown"))
        self.assertEqual((rc, seen["roundtrip"], seen["lookup"]), (0, False, False))
        self.assertEqual(res["caps"]["copilot_connector"]["status"], "unknown")

    def test_bridge_off_skipped(self):
        def must_not_run(**_kw):
            raise AssertionError("브리지가 꺼졌는데 탐침함")
        rc, res, _e = self.run_main([], cfg=self.sb.cfg.derive({"bridge.mode": "off"}), probe_fn=must_not_run)
        self.assertEqual((rc, res["groups"], res["caps"]), (0, {"P-CP": "skipped"}, {}))

    def test_errors_rc3(self):
        rc, res, _e = self.run_main(["--pc", "bad"])
        self.assertEqual((rc, res["fatal"], res["groups"]), (3, "BadArguments", {"P-CP": "error"}))

        def broken(**_kw):
            raise OSError("디버그 포트")
        rc, res, _e = self.run_main([], probe_fn=broken, states_fn=lambda p, s: states())
        self.assertEqual((rc, res["fatal"]), (3, "OSError"))


if __name__ == "__main__":
    unittest.main()
