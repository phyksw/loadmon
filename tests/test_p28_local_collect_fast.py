# -*- coding: utf-8 -*-
r"""tests\test_p28_local_collect_fast.py — [로컬PC 자료수집]은 메일·일정·팀즈(계정 자료)를 읽지 않는다(2026-10-16).

  사용자: "로컬수집은 좀 빠르게 하기위해 웹이나 앱 수집은 뺄까요? 계정이 같다면 클라우드에서 분석실행을 하면 금방 끝날것 같네요"
  · run.collect_account_data — [분석 실행]은 늘 읽음 · 로컬PC 자료수집은 기본 안 읽음 · collectOnlyMailTeams=true 면 읽음
  · run._main --collect-only(임시 ROOT · 가짜 수집기) — PC·파일 수집기만 돌고 Outlook·팀즈 수집기는 하나도 안 돈다 ·
    last_run.json 에 account_data=skipped · 건너뜀 단계 한 줄 · 설정으로 다시 켜면 Copilot 만 빼고 돈다
  · [분석 실행](--collect-only 없음)은 예전처럼 메일·팀즈 사슬을 부른다
  · 화면 — 수집 데이터 현황의 메일·일정·팀즈 0건은 빨강이 아니라 회색 '로컬PC 자료수집은 읽지 않습니다' · 확인 창·안내 줄 문구
  · 배포 설정 두 벌에 collectOnlyMailTeams=false
새 프로세스를 띄우지 않는다(_RUN_STEP·subprocess 대체). 임시 폴더만 쓴다."""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

import _boot

import app  # noqa: E402  — ui\app.py (임포트 부작용 없음)
import run as R  # noqa: E402

ROOT = _boot.ROOT
D0, D1 = "2026-01-01", "2026-09-30"
ACCOUNT = {"Get-OutlookData.ps1", "Get-OutlookIndex.ps1", "Get-OutlookWeb.py", "Get-MailViaCopilot.py", "Import-MailCal.py",
           "Get-TeamsChats.py", "Get-TeamsWindow.ps1", "Get-TeamsWeb.py", "Get-TeamsViaCopilot.py"}
LOCAL = {"Get-PcOnHistory.ps1", "Get-PcOnHints.py", "Get-FileActivity.ps1", "Get-RecentFiles.ps1", "Get-GitActivity.py",
         "Get-ProgramUsage.py"}
SKIP_HINT = "로컬PC 자료수집은 읽지 않습니다 — 같은 계정이면 폴더를 받은 PC 의 [분석 실행]이 읽습니다"


def _quiet():
    return contextlib.redirect_stdout(io.StringIO())


def _lm(src, counts=None):
    return "LMSTATUS " + json.dumps({"v": 1, "src": src, "rc": 0, "reason": "", "counts": counts or {}, "ranges": []})


class _Steps:
    """_RUN_STEP 자리 — 스크립트 이름만 적고 정상 종료로 답한다(프로세스 0개)."""

    def __init__(self):
        self.names = []

    def __call__(self, cmd, timeout, name=""):
        base = next((os.path.basename(str(x)) for x in cmd if str(x).lower().endswith((".ps1", ".py"))), "")
        self.names.append(base)
        return 0, ["끝", _lm(base, {"teams_present": 1} if base == "Get-TeamsWindow.ps1" else None)], "ok"


class _Stop(Exception):
    """[분석 실행] 시험에서 메일 사슬에 닿으면 멈춘다 — 그 뒤(분석·보고)는 이 시험의 몫이 아니다."""


class Switch(unittest.TestCase):
    def test_collect_account_data(self):
        with mock.patch.object(sys, "argv", ["run.py", "--from", D0, "--to", D1]):
            self.assertTrue(R.collect_account_data({}))
            self.assertTrue(R.collect_account_data({"collectOnlyMailTeams": False}))     # [분석 실행]은 늘 읽는다
        with mock.patch.object(sys, "argv", ["run.py", "--from", D0, "--to", D1, "--collect-only"]):
            for c in ({}, {"collectOnlyMailTeams": False}, {"collectOnlyMailTeams": "false"},
                      {"collectOnlyMailTeams": None}, {"collectOnlyMailTeams": 0}):
                self.assertFalse(R.collect_account_data(c), c)
            for c in ({"collectOnlyMailTeams": True}, {"collectOnlyMailTeams": "true"}, {"collectOnlyMailTeams": 1}):
                self.assertTrue(R.collect_account_data(c), c)

    def test_shipped_configs(self):
        for fn in ("config.json", "config.default.json"):
            with open(os.path.join(ROOT, "config", fn), encoding="utf-8-sig") as f:
                c = json.load(f)
            self.assertIs(c.get("collectOnlyMailTeams"), False, fn)
            self.assertIn("_수집만계정자료_설명", c, fn)
            self.assertTrue(c.get("collectOnlyHeadless"), fn)


class MainChain(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(prefix="lm29_p28_")
        self.tmp = self._td.name
        self.root = os.path.join(self.tmp, "root")
        os.makedirs(os.path.join(self.root, "data"))
        self._saved = (R._RUN_STEP, R._CLOSE_EDGE, dict(R.REPORT_DIR), list(R.RUN["stages"]), dict(R.RUN),
                       dict(R.EDGE), dict(R.STATE))
        R.REPORT_DIR["p"] = os.path.join(self.tmp, "report")
        R.RUN["stages"] = []
        R.RUN.pop("account_data", None)
        R.EDGE["closed"] = False
        R.STATE["login_pending"] = False
        R._CLOSE_EDGE = lambda cfg, why: {"closed": True, "why": why}

    def tearDown(self):
        R._RUN_STEP, R._CLOSE_EDGE, rep, stages, run, edge, state = self._saved
        R.REPORT_DIR.clear()
        R.REPORT_DIR.update(rep)
        R.RUN.clear()
        R.RUN.update(run)
        R.RUN["stages"] = stages
        R.EDGE.clear()
        R.EDGE.update(edge)
        R.STATE.clear()
        R.STATE.update(state)
        self._td.cleanup()

    def _cfg(self, c):
        os.makedirs(os.path.join(self.root, "config"), exist_ok=True)
        with open(os.path.join(self.root, "config", "config.json"), "w", encoding="utf-8") as f:
            json.dump(c, f)

    def _collect_only(self):
        steps = _Steps()
        R._RUN_STEP = steps

        def no_spawn(*a, **k):
            raise OSError("시험 — 프로세스를 띄우지 않는다")

        with mock.patch.object(R, "ROOT", self.root), \
                mock.patch.object(sys, "argv", ["run.py", "--from", D0, "--to", D1, "--collect-only"]), \
                mock.patch.object(R.subprocess, "run", no_spawn), mock.patch.object(R.subprocess, "Popen", no_spawn), \
                _quiet() as out:
            rc = R._main()
        self.assertEqual(rc, 0)
        return steps.names, out.getvalue()

    def test_local_collect_skips_mail_and_teams(self):
        names, out = self._collect_only()
        self.assertEqual(set(names) & ACCOUNT, set())
        self.assertEqual(set(names), LOCAL)
        self.assertEqual(R.RUN.get("account_data"), "skipped")
        stages = {x["name"]: x for x in R.RUN["stages"]}
        self.assertIn(R.ACCOUNT_SKIP, stages)
        self.assertTrue(stages[R.ACCOUNT_SKIP]["ok"])
        self.assertIn("collectOnlyMailTeams", stages[R.ACCOUNT_SKIP]["note"])
        self.assertIn("완료(로컬PC 자료수집)", stages)
        self.assertIn("메일·일정·팀즈 — 이 버튼에서는 읽지 않습니다", out)
        with open(os.path.join(R.REPORT_DIR["p"], "last_run.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f).get("account_data"), "skipped")

    def test_setting_brings_mail_teams_back_without_copilot(self):
        self._cfg({"collectOnlyMailTeams": True, "teamsViaCopilot": True})
        names, _out = self._collect_only()
        for must in ("Get-OutlookData.ps1", "Get-OutlookIndex.ps1", "Get-OutlookWeb.py", "Get-TeamsWindow.ps1",
                     "Get-TeamsWeb.py"):
            self.assertIn(must, names)
        self.assertNotIn("Get-MailViaCopilot.py", names)
        self.assertNotIn("Get-TeamsViaCopilot.py", names)
        self.assertNotIn("account_data", R.RUN)
        self.assertNotIn(R.ACCOUNT_SKIP, [x["name"] for x in R.RUN["stages"]])

    def test_full_run_still_reads_mail(self):
        R._RUN_STEP = _Steps()
        called = []

        def stop(*a, **k):
            called.append("outlook")
            raise _Stop()

        with mock.patch.object(R, "ROOT", self.root), mock.patch.object(R, "collect_outlook", stop), \
                mock.patch.object(sys, "argv", ["run.py", "--from", D0, "--to", D1]), _quiet():
            with self.assertRaises(_Stop):
                R._main()
        self.assertEqual(called, ["outlook"])
        self.assertNotIn("account_data", R.RUN)


class Screen(unittest.TestCase):
    def _sources(self, last_run):
        with tempfile.TemporaryDirectory(prefix="lm29_p28_") as td:
            rep, data = os.path.join(td, "report"), os.path.join(td, "data")
            os.makedirs(rep)
            os.makedirs(os.path.join(data, "pc"))
            with open(os.path.join(data, "pc", "pc_on.csv"), "w", encoding="utf-8") as f:
                f.write("date,first,last\n2026-09-01,09:00,18:00\n")
            if last_run is not None:
                with open(os.path.join(rep, "last_run.json"), "w", encoding="utf-8") as f:
                    json.dump(last_run, f, ensure_ascii=False)
            with mock.patch.object(app, "REPORT", rep), mock.patch.object(app, "DATA", data):
                return {s["name"]: s for s in app.sources([D0, D1])}

    def test_skipped_mail_teams_are_grey(self):
        s = self._sources({"stages": [], "account_data": "skipped"})
        for nm in ("메일·일정", "팀즈 채팅"):
            self.assertEqual(s[nm]["status"], "off", nm)
            self.assertIn(SKIP_HINT, s[nm]["hint"], nm)
        self.assertNotIn(SKIP_HINT, s["파일·Recent"]["hint"])

    def test_full_run_mail_zero_is_still_red(self):
        for lr in (None, {"stages": []}, {"stages": [], "account_data": ""}):
            s = self._sources(lr)
            self.assertEqual(s["메일·일정"]["status"], "bad", lr)
            self.assertNotIn(SKIP_HINT, s["메일·일정"]["hint"], lr)

    def test_page_texts(self):
        p = app.PAGE
        self.assertIn("· 이 PC 에만 있는 자료(PC 가동 기록·파일·최근 문서·git·프로그램 기록)만 모아 빨리 끝납니다", p)
        self.assertIn("· 메일·일정·팀즈는 회사 계정 자료라 읽지 않습니다 — 같은 계정이면 폴더를 받은 PC 의 [분석 실행]이 읽습니다", p)
        self.assertNotIn("메일·일정·팀즈(Outlook 웹·팀즈 웹 포함)·파일·PC 가동 기록을 [분석 실행]과 같은 방법으로 모읍니다", p)
        self.assertIn('noticeRun.account_data==="skipped"', p)
        self.assertIn("메일·일정·팀즈는 회사 계정 자료라 이 버튼에서 읽지 않았습니다", p)


if __name__ == "__main__":
    unittest.main()
