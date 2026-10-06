# -*- coding: utf-8 -*-
"""WP-25 Get-TeamsViaCopilot.py(teams.copilot) · Get-CalViaCopilot.py(cal.copilot) 시험 — 얇은 스크립트가 어댑터 한 벌
(Get-MailViaCopilot.run)을 자기 경로로 부른다. 팀즈 증인 행(kind teams · 셀 축 teams · 메시지 행과 병합 제외 — CT §9 ·
X-138 스위치 하나) · 일정 증인 행(kind cal · 하루 구간 · 기본 꺼짐 X-084) · 스크립트 진입(--help rc 0 · 잘못된 인자 rc 3 +
상태 줄 — 동봉 파이썬 자식 프로세스, 쓰기 0)."""
from __future__ import annotations

import json
import subprocess
import unittest

from lm27.util import events

from tests.fixtures.tree import python_home
from tests.fixtures.wp25 import kit as K

R_ = "R-"


def setUpModule():
    events.configure(mode="off")


class Teams(unittest.TestCase):
    def setUp(self):
        self.sb = K.Sandbox()
        self.addCleanup(self.sb.cleanup)

    def test_teams_witness_rows(self):
        def rows(key):
            d0 = key.split(":")[1]
            return [{"t": d0, "d": "in", "chat": "group", "act": "request", "s": "도면 검토 요청"},
                    {"t": d0, "d": "out", "chat": "1:1", "act": "report", "s": "검토 결과 공유"}]
        b = self.sb.blanks("2026-09-07", "2026-09-08", axes=("teams",), src="teams.copilot")
        rc, st, _n, resp = K.run_adapter(self.sb, "teams.copilot", ["--run-id", K.RUN, "--blanks-file", b], rows=rows)
        self.assertEqual((rc, st["src"], st["stage"], st["n"]), (0, "teams.copilot", "lookup_teams", 2))
        self.assertEqual(resp.count["lookup_teams"], 1)
        self.assertEqual([(c["date"], c["axis"], c["status"], c["n"]) for c in st["cells"]],
                         [("2026-09-07", "teams", "ok", 2), ("2026-09-08", "teams", "zero_ok", 0)])
        rows_ = self.sb.rows("teams", "teams.copilot")
        self.assertEqual(len(rows_), 2)
        for r in rows_:
            self.assertEqual((r["src"], r["ts_precision"], r["confidence"]), ("teams.copilot", "summary", 0.3))
            self.assertRegex(r["chat_key"], r"^h[0-9a-f]{16}$")
            self.assertRegex(r["msg_key"], r"^m[0-9a-f]{24}$")
        self.assertEqual(self.sb.cursor("teams.copilot"), {"witnessed_days": ["2026-09-07", "2026-09-08"]})
        self.assertIn("팀즈 조회 · 구간 2026-09-07~2026-09-08", resp.prompts[0].splitlines()[0])

    def test_thin_script_uses_engine(self):
        mod = K.teams_adapter()
        self.assertEqual(mod.SRC, "teams.copilot")
        self.assertIs(mod.engine(), K.adapter())


class Calendar(unittest.TestCase):
    def setUp(self):
        self.sb = K.Sandbox()
        self.addCleanup(self.sb.cleanup)

    def test_default_off(self):
        b = self.sb.blanks("2026-09-07", "2026-09-07", axes=("cal",), src="cal.copilot")
        rc, st, _n, resp = K.run_adapter(self.sb, "cal.copilot", ["--run-id", K.RUN, "--blanks-file", b],
                                         rows=lambda key: [])
        self.assertEqual((rc, st["skipped"], resp.count["lookup_calendar"]), (1, "disabled", 0))

    def test_enabled_rows(self):
        self.sb.cfg = self.sb.cfg.derive({"bridge.stages": {"lookup_calendar": True}})
        b = self.sb.blanks("2026-09-07", "2026-09-07", axes=("cal",), src="cal.copilot")
        rows = [{"t": "2026-09-07", "allday": False, "busy": 2, "s": "주간 회의", "loc": "teams"}]
        rc, st, _n, _r = K.run_adapter(self.sb, "cal.copilot", ["--run-id", K.RUN, "--blanks-file", b],
                                       rows=lambda key: rows)
        self.assertEqual((rc, st["n"], st["cells"][0]["axis"]), (0, 1, "cal"))
        r = self.sb.rows("cal", "cal.copilot")[0]
        self.assertEqual((r["ts_utc"], r["ts_end"], r["ts_precision"], r["text_masked"]),
                         ("2026-09-06T15:00:00Z", "2026-09-07T15:00:00Z", "summary", "주간 회의"))
        self.assertRegex(r["msg_key"], r"^e[0-9a-f]{24}$")


class ScriptEntry(unittest.TestCase):
    """동봉 파이썬 자식 프로세스 — 도움말·인자 오류만(세션·쓰기 없음)."""

    def _run(self, script, *args):
        exe = python_home() / "python.exe"
        return subprocess.run([str(exe), "-X", "utf8", "-B", str(K.TREE / "collect" / script), *args],
                              capture_output=True, timeout=120)

    def test_help_and_bad_args(self):
        for script, src in (("Get-TeamsViaCopilot.py", "teams.copilot"), ("Get-CalViaCopilot.py", "cal.copilot"),
                            ("Get-MailViaCopilot.py", "mail.copilot")):
            with self.subTest(script=script):
                r = self._run(script, "--help")
                self.assertEqual(r.returncode, 0, r.stderr[-300:])
                self.assertIn("--run-id", r.stdout.decode("utf-8", "replace"))
                r = self._run(script, "--pc", "nope", "--events", "off")
                self.assertEqual(r.returncode, 3)
                last = r.stderr.decode("utf-8").strip().splitlines()[-1]
                st = json.loads(last)["_status"]
                self.assertEqual((st["src"], st["rc"], st["reasons"], st["error"]), (src, 3, [R_ + "TRANSPORT"], "BadPcId"))


if __name__ == "__main__":
    unittest.main()
