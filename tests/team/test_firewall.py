# -*- coding: utf-8 -*-
"""WP-27 방화벽 차단 진단 — 출력 모사(Public · BlockInbound · 실행 파일 인바운드 Block 규칙)로 의심 문구·수준·경로 비노출
(TAB §3.14, TAB-S16). 실제 방화벽 설정을 읽거나 바꾸지 않는다.
"""
import contextlib
import io
import json
import os
import unittest

from lm27.team import firewall as F
from tests.fixtures.wp27 import bundles as B
from tests.fixtures.wp27.helpers import running_server

NETSH_KO = ("\r\n도메인 프로필 설정:\r\n----------------------------------------------------------------------\r\n"
            "상태                                  켜기\r\n방화벽 정책                           BlockInbound,AllowOutbound\r\n")
NETSH_EN = "\r\nPublic Profile Settings:\r\nState                                 ON\r\nFirewall Policy                       AllowInbound,AllowOutbound\r\n"
NETSH_OFF = "\r\n상태                                  사용 안 함\r\n방화벽 정책                           BlockInbound,AllowOutbound\r\n"


def fake(category=("Public",), rules=(), netsh=NETSH_KO, ps_ok=True):
    seen = []

    def run(argv, timeout):
        seen.append(argv)
        cmd = " ".join(argv).lower()
        if "powershell" in cmd:
            if not ps_ok:
                return None
            return 0, json.dumps({"category": list(category), "rules": list(rules)}).encode()
        if "advfirewall" in cmd:
            return None if netsh is None else (0, netsh.encode("cp949"))
        return None
    run.seen = seen
    return run


EXE = os.path.join("X", "LoadMonitor27", "python", "python.exe")
BLOCK = {"action": "Block", "direction": "Inbound", "enabled": "True", "profile": "Public"}


class TestFirewall(unittest.TestCase):
    def test_s16_strong_suspect_no_path(self):
        r = fake(rules=[BLOCK, {"action": "Allow", "direction": "Outbound", "enabled": "True", "profile": "Any"}])
        d = F.firewall_diag(EXE, run=r, port=9310, quiet_min=30)
        self.assertEqual((d["level"], d["suspect"], d["rc"]), ("strong", True, 2))
        self.assertIn("python.exe", d["message_ko"])
        self.assertIn("TCP 9310 인바운드 허용", d["message_ko"])
        self.assertIn("30분 동안 0건", d["message_ko"])
        self.assertIn("공유폴더", d["message_ko"])
        self.assertNotIn("LoadMonitor27", json.dumps(d, ensure_ascii=False))      # 경로는 결과·API·로그에 없다
        self.assertEqual(d["network_category"], ["Public"])
        self.assertTrue(any(EXE in " ".join(a) for a in r.seen))                     # 조회에는 실행 파일 경로를 쓴다

    def test_weak_public_block_inbound(self):
        d = F.firewall_diag(EXE, run=fake())
        self.assertEqual((d["level"], d["profile_on"], d["block_inbound"]), ("weak", True, True))

    def test_none_and_failure(self):
        d = F.firewall_diag(EXE, run=fake(category=("DomainAuthenticated",), netsh=NETSH_EN))
        self.assertEqual((d["level"], d["rc"], d["block_inbound"]), ("none", 0, False))
        d = F.firewall_diag(EXE, run=fake(ps_ok=False, netsh=None))
        self.assertEqual((d["rc"], d["suspect"]), (3, False))
        self.assertIn("읽지 못했습니다", d["message_ko"])

    def test_parse_profile(self):
        self.assertEqual(F.parse_profile(NETSH_KO), (True, True))
        self.assertEqual(F.parse_profile(NETSH_EN), (True, False))
        self.assertEqual(F.parse_profile(NETSH_OFF), (False, True))
        self.assertEqual(F.parse_profile(""), (None, None))

    def test_quote_and_hint_due(self):
        self.assertEqual(F._ps_quote("a'b"), "'a''b'")
        cfg = B.test_cfg(B.TREE / "_unused_")
        self.assertFalse(F.hint_due(29 * 60, 0, cfg))
        self.assertTrue(F.hint_due(30 * 60, 0, cfg))
        self.assertFalse(F.hint_due(31 * 60, 2, cfg))
        self.assertFalse(F.hint_due(31 * 60, 0, cfg, done=True))

    def test_server_writes_diag_and_status(self):
        """서버 진단 → run\\firewall_diag.json · /api/status.firewall_hint(경로 없음)."""
        with B.temp_dir() as d, running_server(d, firewall_run=fake(rules=[BLOCK])) as ts:
            with contextlib.redirect_stdout(io.StringIO()) as con:
                out = ts.srv.run_firewall_diag(quiet_min=30)
            self.assertIn("python.exe", con.getvalue())                                 # 경로는 콘솔에만
            self.assertEqual(out["level"], "strong")
            code, st, _ = ts.call("GET", "/api/status")
            self.assertEqual((code, st["firewall_hint"]["suspect"]), (200, True))
            saved = json.loads(ts.store.run_file("firewall_diag.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["level"], "strong")
            self.assertNotIn(str(d), json.dumps(st, ensure_ascii=False))
