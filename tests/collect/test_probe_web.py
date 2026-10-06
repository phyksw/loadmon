# -*- coding: utf-8 -*-
"""파이썬 능력 탐침 연결(W2 검토 C05 · 계약 §6.7 · §2.17 · v1.2 C18) — ``probe_capabilities(web=, copilot=)`` 가 P-OWA ·
P-WEB · P-CP 를 띄우고 그 ``lm27.probe/1`` caps 를 합쳐 ``record_probes`` 가 pc.json 에 남긴다.

  · web: P-OWA → (로그인 확인되면) P-WEB. 로그인 전이면 P-WEB 은 skipped(같은 로그인 — 다시 띄우지 않는다).
  · copilot: P-CP(``--no-roundtrip --no-lookup``) — copilot_env 만 합친다(조회 능력은 조회 단계가 직접 남긴다). 웹 로그인 전이면
    skipped(브리지 세션이 로그인을 오래 기다리지 않게).
  · 파이썬 탐침 자체 실패(시간 초과·출력 없음)는 경고만 — PS 탐침 결과(rc)는 그대로.
  · 하루 한 번: 오늘 web_login ok 기록이 있으면 web_probe_due False.
  · 실제 자식(복제 트리): 진짜 probe_owa.py·probe_teamsweb.py 를 LM_OWA_FAKE·LM_TEAMSWEB_FAKE 주입으로 띄워 caps 를 얻는다.
"""
from __future__ import annotations

import json
import os
import unittest
from datetime import date

from lm27.bundle import pcreg
from lm27.collect import probe
from lm27.util.proc import ChildResult, run_child
from tests.collect.test_probe_record import GOOD
from tests.fixtures.tree import guard_write, make_clone
from tests.fixtures.wp33.helpers import PROBE_FACTS, Sandbox, cfg_of, hist, ident


def _probe_line(group, caps, **extra):
    obj = {"schema": "lm27.probe/1", "now_utc": "2026-10-05T08:00:00Z", "elapsed_ms": 10, "budget_sec": 60,
           "budget_hit": False, "synthetic": True, "groups": {group: "done"}, "warnings": [], "stub_env": [],
           "cfg_used": {}, "caps": caps}
    obj.update(extra)
    return json.dumps(obj).encode() + b"\n"


def _cap(status="ok", reasons=(), value=None, sig="cccccccccccc"):
    return {"ok": status == "ok", "status": status, "reasons": list(reasons), "value": value or {}, "sig": sig}


OWA_OK = {"web_login": _cap(value={"login": "ok"}), "mail.owa": _cap(), "cal.owa": _cap()}
OWA_LOGIN = {k: _cap("fail", ["R-LOGIN"], {"login": "login", "login_pending": True}) for k in ("web_login", "mail.owa",
                                                                                              "cal.owa")}
TW_OK = {"teams.web": _cap()}
CP_OK = {"copilot_env": _cap(value={"tier": "premium"}), "mail.copilot": _cap("unknown"),
         "copilot_connector": _cap("unknown")}


def fake_runner(calls, *, owa=OWA_OK, tw=TW_OK, cp=CP_OK, timeout=()):
    def run(argv, *, timeout_s, stdin=None, env=None):
        names = [os.path.basename(str(a)) for a in argv]
        calls.append(names)
        for script, group, caps in (("probe_owa.py", "P-OWA", owa), ("probe_teamsweb.py", "P-WEB", tw),
                                    ("probe_copilot.py", "P-CP", cp)):
            if script in names:
                if script in timeout:
                    return ChildResult(None, b"", b"", True, timeout_s, 99)
                return ChildResult(0, _probe_line(group, caps), b"", False, 0.1, 99)
        return ChildResult(0, json.dumps(GOOD).encode() + b"\n", b"", False, 0.1, 98)
    return run


class WebProbeUnit(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()
        self.addCleanup(self.sb.cleanup)
        self.cfg = self.sb.cfg()
        self.who = ident()

    def run_probe(self, **kw):
        calls = []
        runner_kw = {k: kw.pop(k) for k in ("owa", "tw", "cp", "timeout") if k in kw}
        pr = probe.probe_capabilities(self.sb.paths, self.who, self.cfg, run=fake_runner(calls, **runner_kw),
                                      team=False, python="py.exe", **kw)
        return pr, calls

    def test_default_runs_ps_probe_only(self):
        pr, calls = self.run_probe()
        self.assertEqual(len(calls), 1)
        self.assertNotIn("web_login", pr.caps)

    def test_web_runs_owa_then_teams_and_merges(self):
        pr, calls = self.run_probe(web=True)
        self.assertEqual(pr.rc, 0)
        self.assertEqual([c[5] for c in calls[1:]], ["probe_owa.py", "probe_teamsweb.py"])   # PS 탐침 뒤 차례로(V9)
        owa = calls[1]
        self.assertEqual(owa[:5], ["py.exe", "-X", "utf8", "-I", "-B"])
        self.assertIn("--budget-sec", owa)
        for k in ("web_login", "mail.owa", "cal.owa", "teams.web", "env", "mail.com"):
            self.assertIn(k, pr.caps)
        self.assertEqual((pr.groups["P-OWA"], pr.groups["P-WEB"]), ("done", "done"))

    def test_login_required_skips_teams_and_copilot(self):
        pr, calls = self.run_probe(web=True, copilot=True, owa=OWA_LOGIN)
        self.assertEqual(sum(1 for c in calls if "probe_teamsweb.py" in c or "probe_copilot.py" in c), 0)
        self.assertEqual((pr.groups["P-WEB"], pr.groups["P-CP"]), ("skipped", "skipped"))
        self.assertEqual(pr.caps["web_login"]["value"]["login_pending"], True)

    def test_copilot_merges_env_only(self):
        pr, calls = self.run_probe(web=True, copilot=True)
        cp = [c for c in calls if "probe_copilot.py" in c][0]
        self.assertIn("--no-roundtrip", cp)
        self.assertIn("--no-lookup", cp)
        self.assertIn("copilot_env", pr.caps)
        self.assertNotIn("mail.copilot", pr.caps)                  # 조회 능력은 조회 단계가 남긴다
        self.assertNotIn("copilot_connector", pr.caps)

    def test_py_probe_timeout_is_warning_only(self):
        pr, _ = self.run_probe(web=True, timeout=("probe_owa.py",))
        self.assertEqual(pr.rc, 0)
        self.assertIn("P-OWA:timeout", pr.warnings)
        self.assertEqual(pr.groups["P-OWA"], "error")
        self.assertNotIn("web_login", pr.caps)

    def test_record_probes_writes_web_caps(self):
        pr, _ = self.run_probe(web=True)
        pcdir = pcreg.ensure_pc_dir(self.sb.paths, self.who, host="", now="2026-10-05T00:00:00Z")
        ents = probe.record_probes(pcdir, pr, None, cfg=self.cfg, today=date(2026, 10, 5))
        for k in ("web_login", "mail.owa", "cal.owa", "teams.web"):
            self.assertEqual(ents[k]["history"][-1]["status"], "ok", k)

    def test_web_probe_due_once_a_day(self):
        today = date(2026, 10, 5)
        self.assertTrue(probe.web_probe_due({}, today))
        pc = {"capabilities": {"web_login": hist(("2026-10-05", "ok", [], "a"))}}
        self.assertFalse(probe.web_probe_due(pc, today))
        pc = {"capabilities": {"web_login": hist(("2026-10-04", "ok", [], "a"))}}
        self.assertTrue(probe.web_probe_due(pc, today))            # 어제 기록 — 오늘 다시
        pc = {"capabilities": {"web_login": hist(("2026-10-05", "fail", ["R-LOGIN"], "a"))}}
        self.assertTrue(probe.web_probe_due(pc, today))            # 로그인 전 — [수집]마다 짧게 확인
        pc = {"capabilities": {"copilot_env": hist(("2026-10-05", "ok", [], "a"))}}
        self.assertFalse(probe.copilot_probe_due(pc, today))


class WebProbeReal(unittest.TestCase):
    """진짜 탐침 자식(복제 트리) — 주입 파일로만(브라우저·네트워크 0)."""

    @classmethod
    def setUpClass(cls):
        cls.clone = make_clone(parts=("lm27", "collect", "config"))
        (cls.clone.root / "data").mkdir(exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        cls.clone.remove()

    def test_real_web_probes_merge(self):
        from lm27.paths import Paths
        c = self.clone
        paths = Paths(c.root, lad=c.lad)
        cfg = cfg_of(c.sandbox)
        facts = guard_write(c.sandbox / "probe_facts.json")
        facts.write_bytes(PROBE_FACTS.read_bytes())
        owa = guard_write(c.sandbox / "owa_fake.json")
        owa.write_bytes(json.dumps({"login": False, "mail": {"2026-10": {"inbox": []}}, "cal": {}}).encode())
        tw = guard_write(c.sandbox / "tw_fake.json")
        tw.write_bytes(json.dumps({"login": False, "chats": {"how": "fake", "items": []}}).encode())
        child_env = c.env({"LM_PROBE_FAKE": str(facts), "LM_OWA_FAKE": str(owa), "LM_TEAMSWEB_FAKE": str(tw)})

        def run(argv, *, timeout_s, stdin=None, env=None):            # 복제 샌드박스 환경으로만(주입점 포함)
            return run_child(argv, timeout_s=timeout_s, stdin=stdin, env=child_env, cwd=str(c.temp))
        pr = probe.probe_capabilities(paths, ident(), cfg, run=run, test_now="2026-10-05T17:00:00+09:00", team=False,
                                      web=True)
        self.assertEqual(pr.rc, 0, pr.error)
        self.assertEqual(pr.caps["web_login"]["status"], "ok", pr.warnings)
        self.assertIn("teams.web", pr.caps)
        self.assertEqual((pr.groups.get("P-OWA"), pr.groups.get("P-WEB")), ("done", "done"))


if __name__ == "__main__":
    unittest.main()
