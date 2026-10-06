# -*- coding: utf-8 -*-
"""WP-26 능력 탐침 시험 — probe_owa.py(P-OWA → mail.owa · cal.owa · web_login) · probe_teamsweb.py(P-WEB → teams.web).

계약 §6.7 · v1.2 C18 출력 ``lm27.probe/1``(Invoke-CapabilityProbe.ps1 과 같은 모양) · 내용 0바이트(숫자·열거·사유 코드만 —
카나리아 0) · sig = 구조 사실만(건수가 바뀌어도 같고 로그인 상태가 바뀌면 달라진다) · LM_NO_BROWSER → skipped ·
Edge 미설치 R-NOAPP · 정책 R-EDGEPOL · 로그인 R-LOGIN · 화면 구조 R-WEBSEL · 세션 잠금 등 수송 실패 → transport_fail."""
import contextlib
import io
import json
import re
import unittest
from datetime import date

from lm27.bridge.clock import VirtualClock
from lm27.bridge.session import EdgeInfo
from tests.fixtures.canary import canaries, find_canaries
from tests.fixtures.wp26 import webkit as K
from tests.fixtures.wp26.cdpfake import FakeSession, factory

P, PT = K.POWA, K.PTW
R_ = "R-"


def owa_fake(n_extra: int = 0, **extra) -> dict:
    inbox = [K.owa_item(K.KIM, "오늘 메일", "오전 9:05", key="t1"), K.owa_item(K.PEER, "어제 메일", "어제 오후 3:00", key="t2"),
             K.owa_item(K.KIM, "지난 메일", "2026-09-28", key="t3")]
    inbox += [K.owa_item(K.KIM, f"더 지난 메일 {i}", "2026-09-01", key=f"x{i}") for i in range(n_extra)]
    out = {"login": False, "mail": {"2026-10": {"inbox": inbox}},
           "cal": {"2026-09-29": [K.owa_event("과제A 점검", date(2026, 9, 29), (9, 0), (10, 0), "3층 회의실")]}}
    out.update(extra)
    return out


class _Base(unittest.TestCase):
    def setUp(self):
        self.sb = K.Sandbox()
        self.addCleanup(self.sb.cleanup)

    def probe(self, mod, environ, *argv, **kw):
        out, err = io.StringIO(), io.StringIO()
        rc = mod.main(list(argv), environ=environ, paths=self.sb.paths, cfg=self.sb.cfg, clock=VirtualClock(),
                      now=K.NOW, out=out, err=err, **kw)
        lines = [x for x in out.getvalue().splitlines() if x.strip()]
        self.assertEqual(len(lines), 1)                                                 # stdout 한 줄 JSON
        return rc, json.loads(lines[0]), err.getvalue()

    def fake_env(self, name, obj):
        return {name: str(self.sb.write_json(name.lower() + ".json", obj))}


def _check_shape(tc, res, group, keys):
    tc.assertEqual(res["schema"], "lm27.probe/1")
    for k in ("now_utc", "elapsed_ms", "budget_sec", "budget_hit", "synthetic", "groups", "warnings", "stub_env",
              "cfg_used", "caps"):
        tc.assertIn(k, res)
    tc.assertIn(group, res["groups"])
    tc.assertEqual(set(res["caps"]), set(keys))
    for c in res["caps"].values():
        tc.assertEqual(set(c), {"ok", "status", "reasons", "value", "sig"})
        tc.assertIn(c["status"], ("ok", "fail", "transport_fail", "unknown"))
        tc.assertRegex(c["sig"], r"^[0-9a-f]{12}$")
        for v in c["value"].values():
            tc.assertTrue(v is None or isinstance(v, (bool, int, float)) or (isinstance(v, str) and len(v) <= 16), v)


class OwaProbeTest(_Base):
    KEYS = ("mail.owa", "cal.owa", "web_login")

    def test_fake_ok_values_and_stub_warning(self):
        rc, res, _ = self.probe(P, self.fake_env("LM_OWA_FAKE", owa_fake()))
        self.assertEqual(rc, 0)
        _check_shape(self, res, "P-OWA", self.KEYS)
        self.assertEqual((res["synthetic"], res["groups"]["P-OWA"], res["stub_env"], res["warnings"]),
                         (True, "done", ["LM_OWA_FAKE"], ["stub_env_set"]))
        m = res["caps"]["mail.owa"]
        self.assertEqual((m["ok"], m["status"], m["reasons"]), (True, "ok", []))
        self.assertEqual((m["value"]["sample_7d"], m["value"]["minute_ratio_7d"]), (3, 0.667))
        self.assertEqual(res["caps"]["cal.owa"]["value"], {"login": "ok", "grid": True, "events": 1})
        self.assertEqual(res["caps"]["web_login"]["value"]["login"], "ok")
        self.assertEqual(res["cfg_used"], {"probe.budgetSec": 60})

    def test_sig_ignores_counts_but_not_login(self):
        _, a, _ = self.probe(P, self.fake_env("LM_OWA_FAKE", owa_fake()))
        _, b, _ = self.probe(P, self.fake_env("LM_OWA_FAKE", owa_fake(n_extra=5)))
        self.assertEqual(a["caps"]["mail.owa"]["sig"], b["caps"]["mail.owa"]["sig"])
        self.assertNotEqual(a["caps"]["mail.owa"]["value"]["items"], b["caps"]["mail.owa"]["value"]["items"])
        _, c, _ = self.probe(P, self.fake_env("LM_OWA_FAKE", owa_fake(login=True)))
        self.assertNotEqual(a["caps"]["web_login"]["sig"], c["caps"]["web_login"]["sig"])
        self.assertEqual({k: v["reasons"] for k, v in c["caps"].items()}, dict.fromkeys(self.KEYS, [R_ + "LOGIN"]))
        self.assertEqual({v["status"] for v in c["caps"].values()}, {"fail"})

    def test_no_browser_edge_missing_policy_session(self):
        rc, res, _ = self.probe(P, {"LM_NO_BROWSER": "1"})
        self.assertEqual((rc, res["groups"]["P-OWA"]), (0, "skipped"))
        self.assertEqual({v["status"] for v in res["caps"].values()}, {"unknown"})
        self.assertEqual({v["ok"] for v in res["caps"].values()}, {None})
        _, res, _ = self.probe(P, {}, edge_info=lambda: EdgeInfo(path=""))
        self.assertEqual({v["reasons"][0] for v in res["caps"].values()}, {R_ + "NOAPP"})
        blocked = EdgeInfo(path="C:/edge/msedge.exe", version="129.0.1.2", policy_debug="blocked")
        _, res, _ = self.probe(P, {}, edge_info=lambda: blocked)
        self.assertEqual({v["reasons"][0] for v in res["caps"].values()}, {R_ + "EDGEPOL"})
        ok = EdgeInfo(path="C:/edge/msedge.exe", version="129.0.1.2", policy_debug="allowed")
        _, res, _ = self.probe(P, {}, edge_info=lambda: ok,
                               session_factory=factory(FakeSession(start_state="lock_busy")))
        self.assertEqual({(v["status"], v["reasons"][0]) for v in res["caps"].values()},
                         {("transport_fail", R_ + "TRANSPORT")})
        s = FakeSession(owa={"inbox": [[K.owa_item(K.KIM, "오늘", "오전 9:05", key="c1")]],
                             "cal": {"2026-09-30": [K.owa_event("회의", date(2026, 9, 30), (9, 0), (10, 0))]}})
        _, res, _ = self.probe(P, {}, edge_info=lambda: ok, session_factory=factory(s))
        self.assertEqual({v["status"] for v in res["caps"].values()}, {"ok"})
        self.assertFalse(res["synthetic"])
        self.assertTrue(s.closed)
        s2 = FakeSession(owa={"inbox": [[K.owa_item(K.KIM, "오늘", "오전 9:05", key="c1")]]}, login_paths=("/calendar/",))
        _, res, _ = self.probe(P, {}, edge_info=lambda: ok, session_factory=factory(s2))
        self.assertEqual((res["caps"]["mail.owa"]["status"], res["caps"]["cal.owa"]["status"],
                          res["caps"]["cal.owa"]["reasons"]), ("ok", "fail", [R_ + "LOGIN"]))   # 주 보기 이동 중 만료 ≠ R-WEBSEL

    def test_bad_fake_args_and_no_content(self):
        bad = self.sb.dir / "bad.json"
        bad.write_bytes(b"[")
        rc, res, _ = self.probe(P, {"LM_OWA_FAKE": str(bad)})
        self.assertEqual((rc, res["groups"]["P-OWA"], res["warnings"][-1]), (0, "error", "fake_unreadable"))
        rc, res, _ = self.probe(P, {}, "--pc", "PC-1")
        self.assertEqual((rc, res["fatal"]), (3, "BadArguments"))
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(P.main(["--help"], out=io.StringIO(), err=io.StringIO()), 0)
        cs = [c for c in canaries(groups=["pii"], weak=False) if c.sentence]
        fake = owa_fake()
        fake["mail"]["2026-10"]["inbox"] += [K.owa_item(c.sentence, c.sentence, "오전 9:05", key=f"c{i}")
                                             for i, c in enumerate(cs)]
        _, res, err = self.probe(P, self.fake_env("LM_OWA_FAKE", fake))
        self.assertEqual(find_canaries(json.dumps(res, ensure_ascii=False).encode("utf-8"), cs), [])
        self.assertEqual(find_canaries(err.encode("utf-8"), cs), [])


class TeamsProbeTest(_Base):

    def fake(self, **extra):
        d = date(2026, 9, 30)
        rooms = [K.tw_room(0, K.tid(1, "group"), "과제A 설계"), K.tw_room(1, K.tid(2), "방")]
        msgs = {0: [{"how": "x", "items": [K.tw_sep(d), K.tw_msg(K.KIM, "a", d=d, iso=True, mid="1759000000000"),
                                           K.tw_msg(K.KIM, "b", d=d, mid="1759000000001"), K.tw_msg(K.KIM, "c", d=d)]}]}
        return K.tw_fake(rooms, msgs, **extra)

    def test_fake_ratios_and_virtualization(self):
        rc, res, _ = self.probe(PT, self.fake_env("LM_TEAMSWEB_FAKE", self.fake()))
        self.assertEqual(rc, 0)
        _check_shape(self, res, "P-WEB", ("teams.web",))
        v = res["caps"]["teams.web"]["value"]
        self.assertEqual((v["chats_n"], v["sample_n"], v["mid_ratio"], v["time_ratio"], v["list_virtualized"]),
                         (2, 3, 0.667, 0.333, False))
        self.assertEqual(res["caps"]["teams.web"]["status"], "ok")
        f = self.fake()
        f["chats"] = [{"how": "[role=treeitem]", "items": f["chats"]["items"][:1]},
                      {"how": "[role=treeitem]", "items": f["chats"]["items"][1:]}]
        _, res2, _ = self.probe(PT, self.fake_env("LM_TEAMSWEB_FAKE", f))
        self.assertTrue(res2["caps"]["teams.web"]["value"]["list_virtualized"])
        self.assertNotEqual(res["caps"]["teams.web"]["sig"], res2["caps"]["teams.web"]["sig"])

    def test_login_websel_no_browser(self):
        _, res, _ = self.probe(PT, self.fake_env("LM_TEAMSWEB_FAKE", self.fake(login=True)))
        self.assertEqual((res["caps"]["teams.web"]["status"], res["caps"]["teams.web"]["reasons"]), ("fail", [R_ + "LOGIN"]))
        _, res, _ = self.probe(PT, self.fake_env("LM_TEAMSWEB_FAKE", {"chats": {"how": "", "items": []}}))
        self.assertEqual(res["caps"]["teams.web"]["reasons"], [R_ + "WEBSEL"])
        _, res, _ = self.probe(PT, {"LM_NO_BROWSER": "1"})
        self.assertEqual((res["groups"]["P-WEB"], res["caps"]["teams.web"]["status"]), ("skipped", "unknown"))
        _, res, _ = self.probe(PT, {}, edge_info=lambda: EdgeInfo(path=""))
        self.assertEqual(res["caps"]["teams.web"]["reasons"], [R_ + "NOAPP"])
        blocked = EdgeInfo(path="C:/edge/msedge.exe", version="129.0.1.2", policy_devtools="blocked")
        _, res, _ = self.probe(PT, {}, edge_info=lambda: blocked)                     # CT-11 탐침 R-EDGEPOL
        self.assertEqual((res["caps"]["teams.web"]["status"], res["caps"]["teams.web"]["reasons"]),
                         ("fail", [R_ + "EDGEPOL"]))
        self.assertTrue(re.fullmatch(r"[0-9a-f]{12}", res["caps"]["teams.web"]["sig"]))


if __name__ == "__main__":
    unittest.main()
