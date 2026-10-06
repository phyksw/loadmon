# -*- coding: utf-8 -*-
"""WP-33 탐침 실행·기록(lm27.collect.probe) — lm27.probe/1 해석·원문 차단·P-TEAM·pc.json 기록·pc.sampler 합치기·
verdict 확정·TTL·자동 해제(계약 §6.4 · §6.7 · §3.8 · C18, C §4 · TAB §1.5).

실제 Outlook·색인·Teams·이벤트 로그를 읽지 않는다: 단위 시험은 가짜 실행기(run=)로, 통합 시험 1건은 %TEMP% 복제 트리에서
진짜 탐침 스크립트를 LM_PROBE_FAKE(합성 사실)로 돌린다.
"""
from __future__ import annotations

import json
import unittest
from datetime import date

from lm27.bundle import pcreg
from lm27.collect import probe
from lm27.util.proc import ChildResult, run_child
from tests.fixtures.canary import canaries
from tests.fixtures.tree import guard_write, make_clone
from tests.fixtures.wp33.helpers import PROBE_FACTS, Sandbox, cfg_of, ident

GOOD = {"schema": "lm27.probe/1", "now_utc": "2026-10-05T08:00:00Z", "elapsed_ms": 4200, "budget_sec": 60,
        "budget_hit": False, "synthetic": True, "groups": {"P-ENV": "done", "P-OL-COM": "done"}, "warnings": [],
        "stub_env": [], "cfg_used": {"probe.budgetSec": 60},
        "caps": {"env": {"ok": True, "status": "ok", "reasons": [], "value": {"language_mode": "FullLanguage"},
                         "sig": "0123456789ab"},
                 "mail.com": {"ok": False, "status": "fail", "reasons": ["R-NEWOL"],
                              "value": {"classic": False, "attach": "not_attempted"}, "sig": "aaaaaaaaaaaa"},
                 "pc.sampler": {"ok": True, "status": "ok", "reasons": [], "value": {"ps": True, "py": True},
                                "sig": "bbbbbbbbbbbb"}}}


def runner(stdout: bytes, *, rc=0, timed_out=False, calls=None):
    def run(argv, *, timeout_s, stdin=None, env=None):
        if calls is not None:
            calls.append({"argv": argv, "timeout_s": timeout_s, "stdin": stdin, "env": env})
        return ChildResult(None if timed_out else rc, stdout, b"", timed_out, 0.1, 1234)
    return run


class ProbeParseCase(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()
        self.addCleanup(self.sb.cleanup)
        self.cfg = self.sb.cfg()
        self.who = ident()

    def test_runs_script_with_in_line_and_parses(self):
        calls = []
        out = b"[noise]\n" + json.dumps(GOOD).encode() + b"\n"
        pr = probe.probe_capabilities(self.sb.paths, self.who, self.cfg, run=runner(out, calls=calls), team=False)
        self.assertEqual(pr.rc, 0)
        self.assertEqual(sorted(pr.caps), ["env", "mail.com", "pc.sampler"])
        self.assertEqual(pr.caps["mail.com"]["reasons"], ["R-NEWOL"])
        self.assertEqual(pr.caps["mail.com"]["sig"], "aaaaaaaaaaaa")
        c = calls[0]
        self.assertIn("-File", c["argv"])
        self.assertTrue(str(c["argv"][c["argv"].index("-File") + 1]).endswith("Invoke-CapabilityProbe.ps1"))
        self.assertEqual(c["argv"][c["argv"].index("-Pc") + 1], self.who.pc_id)
        # 설정은 명령줄이 아니라 stdin 제어 줄(계약 §7.3)
        line = json.loads(c["stdin"].decode())
        self.assertEqual(sorted(line["_in"]["cfg"]), sorted(probe.CFG_KEYS))
        self.assertIsNone(line["_in"]["cursor"])
        self.assertNotIn("probe.budgetSec", " ".join(map(str, c["argv"])))
        self.assertGreaterEqual(c["timeout_s"], self.cfg["probe.budgetSec"] + 10)     # C18 — 기동 몫 여유

    def test_failures_are_rc3_without_caps(self):
        pr = probe.probe_capabilities(self.sb.paths, self.who, self.cfg, run=runner(b"", timed_out=True), team=False)
        self.assertEqual((pr.rc, pr.error, pr.caps), (3, "timeout", {}))
        pr = probe.probe_capabilities(self.sb.paths, self.who, self.cfg, run=runner(b"garbage\n"), team=False)
        self.assertEqual((pr.rc, pr.error), (3, "no_output"))
        fatal = json.dumps({"schema": "lm27.probe/1", "fatal": "NullReferenceException"}).encode()
        pr = probe.probe_capabilities(self.sb.paths, self.who, self.cfg, run=runner(fatal, rc=3), team=False)
        self.assertEqual((pr.rc, pr.error), (3, "NullReferenceException"))

        def boom(*a, **k):
            raise OSError("blocked")
        pr = probe.probe_capabilities(self.sb.paths, self.who, self.cfg, run=boom, team=False)
        self.assertEqual((pr.rc, pr.error), (3, "spawn_OSError"))

    def test_values_are_cleaned_and_unknown_reasons_dropped(self):
        cs = [c.value for c in canaries(groups=("pii",), weak=False) if c.value][:3]
        bad = json.loads(json.dumps(GOOD))
        bad["caps"]["env"]["value"] = {"tz_id": "Korea Standard Time", "path": "C:\\Users\\" + cs[0],
                                       "addr": cs[1] + "@corp.example", "long": "x" * 300, "n": 3}
        bad["caps"]["env"]["reasons"] = ["R-NEWOL", "R-" + "ZZNOTACODE", "garbage"]
        bad["caps"]["Bad Key!"] = {"status": "ok"}
        pr = probe.probe_capabilities(self.sb.paths, self.who, self.cfg, run=runner(json.dumps(bad).encode()),
                                      team=False)
        v = pr.caps["env"]["value"]
        self.assertEqual(v["tz_id"], "Korea Standard Time")
        self.assertIsNone(v["path"])                       # 경로 모양 버림
        self.assertIsNone(v["addr"])                       # 주소 모양 버림
        self.assertIsNone(v["long"])
        self.assertEqual(v["n"], 3)
        self.assertEqual(pr.caps["env"]["reasons"], ["R-NEWOL"])
        self.assertEqual(pr.unknown_reasons, 1)
        self.assertNotIn("Bad Key!", pr.caps)
        blob = json.dumps(pr.caps, ensure_ascii=False)
        for c in cs:
            self.assertNotIn(c, blob)

    def test_team_reach_mapping(self):
        def hello(result, ms=12):
            return lambda base, timeout: {"result": result, "ms": ms}
        r = probe.team_reach(self.cfg, hello=hello("ok"))
        self.assertEqual((r["ok"], r["status"], r["reasons"]), (True, "ok", []))
        self.assertEqual(r["value"], {"target": "primary", "result": "ok", "ms": 12})   # URL·IP 를 싣지 않는다
        r = probe.team_reach(self.cfg, hello=hello("timeout"))
        self.assertEqual((r["status"], r["reasons"]), ("transport_fail", ["R-TEAM-TIMEOUT"]))
        r = probe.team_reach(self.cfg, hello=hello("lm24"))
        self.assertEqual((r["status"], r["reasons"]), ("fail", ["R-TEAM-LM24"]))
        r = probe.team_reach(self.cfg, hello=hello("other_lm"))
        self.assertEqual(r["reasons"], ["R-TEAM-OTHERAPP"])
        seen = []

        def capture(base, timeout):
            seen.append((base, timeout))
            return {"result": "wrong_major"}
        r = probe.team_reach(self.cfg, hello=capture)
        self.assertEqual(r["reasons"], ["R-TEAM-VERSION"])
        self.assertEqual(seen[0][1], self.cfg["team.connectTimeoutSec"])
        self.assertNotIn(seen[0][0], json.dumps(r))


class RecordCase(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()
        self.addCleanup(self.sb.cleanup)
        self.cfg = self.sb.cfg()
        self.who = ident()
        self.pcdir = pcreg.ensure_pc_dir(self.sb.paths, self.who, host="", now="2026-10-01T00:00:00Z")

    def pr(self, status="fail", reasons=("R-NEWOL",), sig="aaaaaaaaaaaa"):
        g = json.loads(json.dumps(GOOD))
        g["caps"]["mail.com"].update(status=status, reasons=list(reasons), sig=sig, ok=status == "ok")
        return probe.probe_capabilities(self.sb.paths, self.who, self.cfg, run=runner(json.dumps(g).encode()),
                                        team=False)

    def test_record_writes_history_with_probe_sig(self):
        loc = {"ok": True, "status": "ok", "value": {"drive_type": "fixed", "writable": True, "free_mb": 9000},
               "reasons": ["R-BUNDLE-ONEDRIVE"]}
        ents = probe.record_probes(self.pcdir, self.pr(), loc, cfg=self.cfg, today=date(2026, 10, 5))
        self.assertIn("bundle_location", ents)
        pc = pcreg.load_pc(self.pcdir)
        h = pc["capabilities"]["mail.com"]["history"][-1]
        self.assertEqual(h, {"date": "2026-10-05", "status": "fail", "reasons": ["R-NEWOL"], "probe_sig": "aaaaaaaaaaaa"})
        self.assertEqual(pc["capabilities"]["bundle_location"]["reasons"], ["R-BUNDLE-ONEDRIVE"])
        self.assertEqual(pc["capabilities"]["mail.com"]["verdict"], "불가(잠정)")

    def test_confirmed_after_two_days_ttl_and_auto_release(self):
        for d in (date(2026, 10, 1), date(2026, 10, 2)):
            ents = probe.record_probes(self.pcdir, self.pr(), None, cfg=self.cfg, today=d)
        self.assertEqual(ents["mail.com"]["verdict"], "불가(확정)")          # 같은 확정 사유 · 서로 다른 날 2회
        # 수송 실패는 확정 근거가 아니고(같은 날 다시 와도) 판정을 바꾸지 않는다
        e = probe.record_probes(self.pcdir, self.pr("transport_fail", ("R-TRANSPORT",)), None, cfg=self.cfg,
                                today=date(2026, 10, 3))
        self.assertEqual(e["mail.com"]["verdict"], "불가(확정)")
        # TTL(collect.confirmTtlDays=14) 이 지나면 잠정으로 내려가 한 번 다시 시도
        v = pcreg.verdict(pcreg.load_pc(self.pcdir)["capabilities"]["mail.com"]["history"], self.cfg,
                          today=date(2026, 10, 20))
        self.assertEqual(v, "불가(잠정)")
        # 탐침 값이 바뀌면(sig 변화) 그 전 실패는 세지 않는다 = 자동 해제
        e = probe.record_probes(self.pcdir, self.pr(sig="cccccccccccc"), None, cfg=self.cfg, today=date(2026, 10, 4))
        self.assertEqual(e["mail.com"]["verdict"], "불가(잠정)")
        e = probe.record_probes(self.pcdir, self.pr("ok", ()), None, cfg=self.cfg, today=date(2026, 10, 5))
        self.assertEqual(e["mail.com"]["verdict"], "가능")

    def test_copilot_nolic_confirm_and_release(self):
        """CM-17 원장 측 — mail.copilot R-NOLIC: 다른 날 2회 전엔 미확정, 2회면 확정, 탐침 값이 바뀌면 해제(브리지 capability 도
        같은 record_probe 를 쓴다 — 계약 §3.8)."""
        def rec(d, sig="cp0000000001", ok=False):
            return pcreg.record_probe(self.pcdir, "mail.copilot", ok, {}, [] if ok else ["R-NOLIC"],
                                      probe_sig=sig, date=date(2026, 10, d), cfg=self.cfg, today=date(2026, 10, d))
        self.assertEqual(rec(1)["verdict"], "불가(잠정)")
        self.assertEqual(rec(1)["verdict"], "불가(잠정)")                    # 같은 날 두 번은 1회
        self.assertEqual(rec(2)["verdict"], "불가(확정)")
        self.assertEqual(rec(3, sig="cp0000000002")["verdict"], "불가(잠정)")  # 계정 등급·커넥터가 바뀜 → 해제
        self.assertEqual(rec(4, sig="cp0000000002", ok=True)["verdict"], "가능")

    def test_non_confirmable_reason_never_confirms(self):
        for d in (1, 2, 3):
            e = probe.record_probes(self.pcdir, self.pr("fail", ("R-LOGIN",)), None, cfg=self.cfg,
                                    today=date(2026, 10, d))
        self.assertEqual(e["mail.com"]["verdict"], "불가(잠정)")             # R-LOGIN = 사람 사유(확정 ✘)

    def test_sampler_merges_agent_impl(self):
        e = probe.record_probes(self.pcdir, self.pr(), None, cfg=self.cfg, today=date(2026, 10, 5),
                                agent={"impl": "py", "impl_reasons": []})
        self.assertEqual(e["pc.sampler"]["value"], {"ps": True, "py": True, "impl": "py"})
        self.assertEqual(e["pc.sampler"]["verdict"], "가능")
        e = probe.record_probes(self.pcdir, self.pr(), None, cfg=self.cfg, today=date(2026, 10, 6),
                                agent={"impl": "none", "impl_reasons": ["R-APPLOCKER"]})
        self.assertEqual((e["pc.sampler"]["ok"], e["pc.sampler"]["reasons"]), (False, ["R-APPLOCKER"]))
        self.assertEqual(e["pc.sampler"]["value"]["impl"], "none")
        self.assertEqual(probe.sampler_cap({"status": "ok", "value": {"ps": True}}, None)["value"], {"ps": True})

    def test_team_reach_recorded(self):
        g = self.pr()
        g.team = probe.team_reach(self.cfg, hello=lambda base, t: {"result": "refused", "ms": 3})
        e = probe.record_probes(self.pcdir, g, None, cfg=self.cfg, today=date(2026, 10, 5))
        self.assertEqual(e["team_server_reach"]["reasons"], ["R-TEAM-REFUSED"])
        self.assertEqual(e["team_server_reach"]["history"][-1]["status"], "transport_fail")


class RealProbeCase(unittest.TestCase):
    """진짜 Invoke-CapabilityProbe.ps1 을 %TEMP% 복제 트리에서 LM_PROBE_FAKE(합성 사실 — 새 Outlook 전용 PC)로."""

    @classmethod
    def setUpClass(cls):
        cls.clone = make_clone(parts=("lm27", "collect", "config"))
        (cls.clone.root / "data").mkdir(exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        cls.clone.remove()

    def test_real_script_new_outlook(self):
        from lm27.paths import Paths
        c = self.clone
        paths = Paths(c.root, lad=c.lad)
        cfg = cfg_of(c.sandbox)
        fake = guard_write(c.sandbox / "probe_facts.json")
        fake.write_bytes(PROBE_FACTS.read_bytes())

        def run(argv, *, timeout_s, stdin=None, env=None):
            return run_child(argv, timeout_s=timeout_s, stdin=stdin, env=c.env({"LM_PROBE_FAKE": str(fake)}),
                             cwd=str(c.temp))
        pr = probe.probe_capabilities(paths, ident(), cfg, run=run, test_now="2026-10-05T17:00:00+09:00",
                                      team=False)
        self.assertEqual(pr.rc, 0, pr.error)
        self.assertTrue(pr.synthetic)
        self.assertEqual(pr.caps["mail.com"]["status"], "fail")
        self.assertIn("R-NEWOL", pr.caps["mail.com"]["reasons"])
        self.assertRegex(pr.caps["mail.com"]["sig"], r"^[0-9a-f]{12}$")
        self.assertEqual(pr.caps["env"]["status"], "ok")
        pcdir = pcreg.ensure_pc_dir(paths, ident(), host="", now="2026-10-05T00:00:00Z")
        ents = probe.record_probes(pcdir, pr, None, cfg=cfg, today=date(2026, 10, 5))
        self.assertEqual(ents["mail.com"]["history"][-1]["probe_sig"], pr.caps["mail.com"]["sig"])


if __name__ == "__main__":
    unittest.main()
