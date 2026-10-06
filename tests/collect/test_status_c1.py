# -*- coding: utf-8 -*-
"""수집기 상태 줄 한 모양 공용 시험(계약 v1.2 §0.7 C1 · C4 — W1 통합 창, W1a 반증 검토 #12).

모든 파이썬 수집기의 오류 경로(인자 오류 · pc_id 형식 오류)도 stderr 마지막 상태 줄이 C1 필수 집합
(schema·src·rc·reasons[]·partial·cap_hit·budget_hit·n·counts{})을 갖고, src 는 경로 ID, 실패(rc 3)에는 사유가 붙는다.
PS 수집기의 정상·CLM 경로는 test_pc_clm(WP-14 6종) · test_teams_uia_contract(WP-16) · test_mail_com·test_mail_index
(WP-15)가 같은 집합을 본다. 실제 메일·팀즈·Edge 는 건드리지 않는다(인자 단계에서 끝나는 경로만).
"""
import json
import re
import unittest

from lm27.collect import rcmap
from tests.fixtures.tree import CloneTestCase

C1_KEYS = frozenset({"schema", "src", "rc", "reasons", "partial", "cap_hit", "budget_hit", "n", "counts"})
SRC_RX = re.compile(r"^(?:(?:mail|cal|teams|pc)\.[a-z]{2,10}|manual)$")
CASES = [
    ("Get-GitActivity.py", ["--pc", "BAD"], "pc.git"),
    ("Get-GitActivity.py", ["--no-such-arg"], "pc.git"),
    ("Import-MailCal.py", ["--kind", "mail", "--pc", "BAD"], "mail.import"),
    ("Import-MailCal.py", ["--kind", "cal", "--pc", "BAD"], "cal.import"),
    ("Import-MailCal.py", ["--no-such-arg"], "mail.import"),
    ("Get-MailViaCopilot.py", ["--pc", "BAD"], "mail.copilot"),
    ("Get-CalViaCopilot.py", ["--pc", "BAD"], "cal.copilot"),
    ("Get-TeamsViaCopilot.py", ["--pc", "BAD"], "teams.copilot"),
    ("Get-OutlookWeb.py", ["--kind", "mail", "--pc", "BAD"], "mail.owa"),
    ("Get-OutlookWeb.py", ["--no-such-arg"], "mail.owa"),
    ("Get-TeamsWeb.py", ["--pc", "BAD"], "teams.web"),
]


class StatusLineC1(CloneTestCase):
    def test_error_paths_have_c1_fields_src_and_reason(self):
        for script, args, src in CASES:
            with self.subTest(script=script, args=args):
                cp = self.clone.run_py([self.clone.path("collect", script), *args], flags=("-X", "utf8", "-I", "-B"),
                                       input=b"", timeout=180)
                lines = [ln for ln in cp.stderr.decode("utf-8", "replace").splitlines() if ln.startswith('{"_status"')]
                self.assertEqual(len(lines), 1, cp.stderr.decode("utf-8", "replace")[-400:])
                st = json.loads(lines[0])["_status"]
                self.assertLessEqual(C1_KEYS, set(st), sorted(C1_KEYS - set(st)))
                self.assertEqual((st["schema"], st["src"], st["rc"], cp.returncode),
                                 ("lm27.collector_status/1", src, 3, 3))
                self.assertRegex(st["src"], SRC_RX)
                self.assertTrue(st["reasons"], "C4 — 실패에는 사유를 단다")
                self.assertIsInstance(st["counts"], dict)
                self.assertNotIn("_result", cp.stderr.decode("utf-8", "replace"))
                self.assertEqual(rcmap.translate_cell(st["rc"], st["reasons"], st["counts"])["status"], "transport_fail")


if __name__ == "__main__":
    unittest.main()
