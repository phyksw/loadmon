# -*- coding: utf-8 -*-
r"""test_p6_chain.py — WP6: 수집 사슬·일자×축 원장·메일 병합·G1·프로세스 규율(run.py).

  · collect_status : LMSTATUS 해석 · 옛 종료 코드(OWA 1 → 3 R-LEGACY) · 시간 초과 → partial
  · coverage       : 색인 0건 ≠ zero_ok · COM zero_ok + 색인 3 → suspect · Copilot 은 zero_ok 를 못 만든다 ·
                     색인 반복 마스터 → cal 공백 · teams 무흔적 → na
  · 사슬(run_step 주입 — 실제 수집기를 띄우지 않는다): (a) COM 전 기간 ok → 색인 1·OWA 0·Copilot 0 · (b) COM R-NEWOL·색인 0 →
    OWA 1 · (c) OWA 전 기간 확인 → Copilot 0 · (d) OWA 3·4월만 미검증 → Copilot --ranges 3·4월 · 색인 반복 마스터 → OWA --only cal ·
    COM zero_ok+색인 3 → OWA 그날만 · (e) 창 rc 0 → 웹 1회 · (f) OWA rc 2 → 팀즈 웹·Copilot 0회·Edge 닫기 0회
  · mailmerge      : com/owa 같은 메일 → 1행 src=com · Copilot 행은 다른 출처 행이 있는 날 0 · mail_source.json LM24 키 ·
                     COM→색인 순 실행 뒤 coverage_com.json 이 남음
  · G1             : 같은 팀즈 메시지 2회 수집 + G1 2회 → 1행
  · proc           : 잠드는 자식+손자 → 시간 초과 뒤 둘 다 끝남 · Job 이탈 손자는 산다(시험이 PID 로 정리) · 시계 주입 진행 줄
                     (만드는 프로세스 3개)
  · ensure_sampler : 등록 흔적 없음 → 분리 실행 0회
임시 파일은 tempfile.TemporaryDirectory 안에만 만든다. 실제 Outlook·Edge·Teams·schtasks 는 띄우지 않는다.
"""
import contextlib
import io
import json
import os
import signal
import sys
import tempfile
import time
import unittest
from datetime import date

import _boot

import collect_status
import coverage
import mailmerge
import proc

ROOT = _boot.ROOT
import run as R  # noqa: E402 - _boot 이 ROOT 를 sys.path 에 넣는다

D0, D1 = "2026-01-01", "2026-09-30"
PS = ["powershell", "-File"]
COL = os.path.join(ROOT, "collect")
ALL = ("mail_in", "mail_out", "cal")


def LM(src, rc=0, reason="", ranges=(), counts=None):
    return "LMSTATUS " + json.dumps({"v": 1, "src": src, "rc": rc, "reason": reason, "counts": counts or {},
                                     "ranges": list(ranges)}, ensure_ascii=False)


def rng(axis, a, b, st):
    return {"axis": axis, "from": a, "to": b, "st": st}


def rngs(axes, a, b, st):
    return [rng(ax, a, b, st) for ax in axes]


class FakeSteps:
    """run.py 의 _RUN_STEP 자리 — 스크립트 이름으로 각본 응답을 고른다(프로세스 0개)."""

    def __init__(self, script):
        self.script, self.calls = dict(script), []

    def __call__(self, cmd, timeout, name=""):
        base = next((os.path.basename(str(x)) for x in cmd if str(x).lower().endswith((".ps1", ".py"))), "")
        self.calls.append((base, [str(x) for x in cmd]))
        fn = self.script.get(base)
        if fn is None:
            return 0, ["끝", LM(base, 0)], "ok"
        out = fn([str(x) for x in cmd])
        return out if len(out) == 3 else (out[0], out[1], "ok")

    def n(self, base):
        return sum(1 for b, _c in self.calls if b == base)

    def args(self, base):
        return [c for b, c in self.calls if b == base]


def _arg(cmd, flag):
    return cmd[cmd.index(flag) + 1] if flag in cmd else None


def _write_csv(path, header, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        f.write(header + "\r\n")
        for r in rows:
            f.write(",".join(r) + "\r\n")


def _rows(path):
    import csv
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


class _RunEnv(unittest.TestCase):
    """run.py 를 임시 data·report 로 돌린다(last_run.json 도 임시 폴더) — 주입은 tearDown 에서 되돌린다."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory(prefix="lm28_p6_")
        self.tmp = self._td.name
        self.data = os.path.join(self.tmp, "data")
        os.makedirs(self.data)
        self._saved = (R._RUN_STEP, R._CLOSE_EDGE, R._START_PROCESS, dict(R.REPORT_DIR), list(R.RUN["stages"]),
                       dict(R.EDGE), R._mutex_exists)
        R.REPORT_DIR["p"] = os.path.join(self.tmp, "report")
        R.RUN["stages"] = []
        R.EDGE["closed"] = False
        self.closed = []
        R._CLOSE_EDGE = lambda cfg, why: self.closed.append(why) or {"closed": True, "why": why}

    def tearDown(self):
        (R._RUN_STEP, R._CLOSE_EDGE, R._START_PROCESS, rep, stages, edge, mx) = self._saved
        R.REPORT_DIR.clear()
        R.REPORT_DIR.update(rep)
        R.RUN["stages"] = stages
        R.EDGE.clear()
        R.EDGE.update(edge)
        R._mutex_exists = mx
        self._td.cleanup()

    def quiet(self):
        return contextlib.redirect_stdout(io.StringIO())

    def chain(self, script, c=None, teams=False, mail=True):
        fake = FakeSteps(script)
        R._RUN_STEP = fake
        c = dict(c or {})
        state = {"login_pending": False}
        with self.quiet():
            led = R.open_ledger(c, self.data)
            if mail:
                R.collect_outlook(c, D0, D1, self.data, PS, COL, led)
                R.mail_fallbacks(c, D0, D1, self.data, PS, COL, None, led, state)
            if teams:
                R.collect_teams(c, D0, D1, self.data, PS, COL, led, state)
            R.close_edge_once(state, "run_end")
        return fake, led, state

    def stage(self, prefix):
        return [x for x in R.RUN["stages"] if x["name"].startswith(prefix)]


# ── collect_status ──────────────────────────────────────────────────────────
class StatusTests(unittest.TestCase):
    def test_lmstatus(self):
        st = collect_status.parse(["[owa] 메일 12건", LM("owa", 3, "R-WEBSEL,R-TIMEOUT", [rng("cal", D0, D0, "ok")],
                                                       {"rows": 12, "big": "x" * 200})], 3, src="owa")
        self.assertTrue(st["has_status"])
        self.assertEqual((st["rc"], st["reasons"]), (3, ["R-WEBSEL", "R-TIMEOUT"]))
        self.assertEqual(st["human"], "[owa] 메일 12건")
        self.assertFalse(st["ok"])
        self.assertIn("의심(실측 전)", collect_status.describe(st))
        self.assertEqual(collect_status.compact(st["counts"]), {"rows": 12})       # 긴 값은 싣지 않는다

    def test_ps_single_range_dict(self):
        line = "LMSTATUS " + json.dumps({"v": 1, "src": "index", "rc": 3, "reason": "R-RECURINC",
                                         "ranges": rng("cal", D0, D1, "partial")})
        st = collect_status.parse([line], 3, src="index")
        self.assertEqual(len(st["ranges"]), 1)
        self.assertTrue(st["ok"])                     # 저장은 했다(반복 회의 미전개) — 단계 실패로 칠하지 않는다

    def test_legacy_rc(self):
        self.assertEqual(collect_status.parse(["시간 초과"], 1, src="owa")["reason"], "R-LEGACY")
        self.assertEqual(collect_status.parse(["시간 초과"], 1, src="owa")["rc"], 3)
        self.assertEqual(collect_status.parse(["대상 없음"], 1, src="git")["rc"], 1)
        st4 = collect_status.parse(["새 줄 0"], 4, src="teams_window")
        self.assertEqual((st4["rc"], st4["ok"]), (4, True))
        crash = collect_status.parse(["Traceback (most recent call last):", "ValueError"], 1, src="pc_hints")
        self.assertEqual((crash["rc"], crash["reason"]), (3, "R-CRASH"))

    def test_timeout_makes_partial(self):
        st = collect_status.parse([LM("owa", 0, "", [rng("mail_in", D0, D1, "ok")])], -1, src="owa", how="timeout")
        self.assertEqual((st["rc"], st["reasons"][0]), (3, "R-TIMEOUT"))
        self.assertEqual(st["ranges"][0]["st"], "partial")


# ── coverage ────────────────────────────────────────────────────────────────
class CoverageTests(unittest.TestCase):
    def led(self):
        return coverage.Ledger(None, "v|1", "h")

    def test_index_zero_is_not_zero_ok(self):
        L = self.led()
        L.apply({"src": "index", "rc": 0, "ranges": rngs(("mail_in",), "2026-02-01", "2026-02-03", "zero_ok")})
        self.assertFalse(L.is_verified("2026-02-02", "mail_in"))
        self.assertEqual(L.gaps(("mail_in",), "2026-02-01", "2026-02-03")["mail_in"], [("2026-02-01", "2026-02-03")])

    def test_com_zero_ok_with_index_rows_is_suspect(self):
        L = self.led()
        L.apply({"src": "com", "rc": 0, "ranges": rngs(ALL, "2026-02-01", "2026-02-28", "zero_ok")})
        L.apply({"src": "index", "rc": 0, "ranges": rngs(("mail_in",), "2026-02-03", "2026-02-03", "ok")})
        hits = L.comgap({}, {("2026-02-03", "mail_in"): 3}, "2026-02-01", "2026-02-28")
        self.assertEqual(hits, [("2026-02-03", "mail_in")])
        self.assertTrue(L.is_suspect("2026-02-03", "mail_in"))
        self.assertEqual(L.gaps(("mail_in",), "2026-02-01", "2026-02-28")["mail_in"], [("2026-02-03", "2026-02-03")])
        # 비율 규칙: COM 10 · 색인 14(>1.3, 차이 4) → 의심 / COM 2 · 색인 3(차이 1) → 의심 아님
        L.apply({"src": "com", "rc": 0, "ranges": rngs(("mail_out",), "2026-02-04", "2026-02-05", "ok")})
        h2 = L.comgap({("2026-02-04", "mail_out"): 10, ("2026-02-05", "mail_out"): 2},
                      {("2026-02-04", "mail_out"): 14, ("2026-02-05", "mail_out"): 3}, "2026-02-01", "2026-02-28")
        self.assertIn(("2026-02-04", "mail_out"), h2)
        self.assertNotIn(("2026-02-05", "mail_out"), h2)

    def test_copilot_never_verifies(self):
        L = self.led()
        L.apply({"src": "copilot", "rc": 0, "ranges": rngs(ALL, "2026-03-01", "2026-03-02", "zero_ok")
                 + rngs(ALL, "2026-03-03", "2026-03-03", "unverified")})
        self.assertEqual(L.src_status("2026-03-01", "mail_in", "copilot"), "partial")
        self.assertEqual(L.src_status("2026-03-03", "mail_in", "copilot"), "asked")
        self.assertEqual(L.composite("2026-03-01", "mail_in"), "not_attempted")   # 증인은 다른 출처의 미관측을 덮지 않는다
        self.assertEqual(L.gaps(("mail_in",), "2026-03-01", "2026-03-03")["mail_in"], [("2026-03-01", "2026-03-03")])
        self.assertEqual(L.gaps(("mail_in",), "2026-03-01", "2026-03-03", witness="copilot")["mail_in"], [])

    def test_index_recurring_master_keeps_cal_gap(self):
        L = self.led()
        L.apply({"src": "index", "rc": 3, "counts": {"recurring_masters": 1},
                 "ranges": rngs(("cal",), "2026-04-01", "2026-04-30", "ok")})
        self.assertEqual(L.src_status("2026-04-10", "cal", "index"), "partial")
        self.assertTrue(L.gaps(("cal",), "2026-04-01", "2026-04-30")["cal"])

    def test_teams_na(self):
        L = self.led()
        L.set_na("teams", True)
        self.assertEqual(L.gaps(("teams",), D0, D1)["teams"], [])
        self.assertEqual(L.composite("2026-02-02", "teams"), "na")

    def test_verified_kept_and_reset_and_version(self):
        with tempfile.TemporaryDirectory(prefix="lm28_p6c_") as td:
            p = os.path.join(td, coverage.FILE_NAME)
            L = coverage.Ledger(p, "v|1", "h")
            L.apply({"src": "com", "rc": 0, "ranges": rngs(("mail_in",), "2026-01-05", "2026-01-05", "ok")})
            L.apply({"src": "com", "rc": 3, "ranges": rngs(("mail_in",), "2026-01-05", "2026-01-05", "blocked")})
            self.assertTrue(L.is_verified("2026-01-05", "mail_in"))      # 지난 날의 확인을 이번 막힘이 지우지 않는다
            L.save()
            self.assertTrue(coverage.Ledger.load(p, "v|1", "h").is_verified("2026-01-05", "mail_in"))
            self.assertEqual(coverage.Ledger.load(p, "v|2", "h").dropped, "ver")      # cursorEpoch 가 바뀌면 처음부터
            self.assertEqual(coverage.Ledger.load(p, "v|1", "other").dropped, "host")
            L.reset()
            self.assertEqual(L.composite("2026-01-05", "mail_in"), "not_attempted")


# ── 사슬(run_step 주입) ─────────────────────────────────────────────────────
def com_ok(cmd):
    return 0, ["[outlook] done.", LM("com", 0, "", rngs(ALL, D0, D1, "ok"))]


def com_newol(cmd):
    return 3, ["[outlook] 건너뜀: 새 Outlook", LM("com", 3, "R-NEWOL", rngs(ALL, D0, D1, "blocked"))]


def idx_empty(cmd):
    return 3, ["[outlook-index] 0건", LM("index", 3, "R-IDXEMPTY")]


def owa_all_ok(cmd):
    a, b = _arg(cmd, "--from"), _arg(cmd, "--to")
    return 0, ["[owa] 확인", LM("owa", 0, "", rngs(ALL, a, b, "ok"))]


class ChainTests(_RunEnv):
    def test_a_com_full_ok(self):
        src = os.path.join(self.data, "outlook", "src")
        os.makedirs(src)
        with open(os.path.join(src, "coverage_com.json"), "w", encoding="utf-8") as f:
            f.write('{"version":3}')
        fake, led, _st = self.chain({"Get-OutlookData.ps1": com_ok,
                                     "Get-OutlookIndex.ps1": lambda c: (0, ["ok", LM("index", 0, "",
                                                                                     rngs(("mail_in",), D0, D0, "ok"))])},
                                    c={"mailViaCopilot": True})
        self.assertEqual((fake.n("Get-OutlookData.ps1"), fake.n("Get-OutlookIndex.ps1")), (1, 1))
        self.assertEqual((fake.n("Get-OutlookWeb.py"), fake.n("Get-MailViaCopilot.py")), (0, 0))
        com = fake.args("Get-OutlookData.ps1")[0]
        self.assertEqual((_arg(com, "-Tag"), _arg(com, "-OutDir")), ("com", src))
        idx = fake.args("Get-OutlookIndex.ps1")[0]
        self.assertEqual((_arg(idx, "-From"), _arg(idx, "-To"), _arg(idx, "-Tag")), (D0, D1, "index"))
        self.assertTrue(os.path.exists(os.path.join(src, "coverage_com.json")))     # COM→색인 순 실행 뒤에도 COM 표가 남는다
        self.assertEqual(self.closed, ["run_end"])
        st = self.stage("Outlook 메일·일정")[0]
        self.assertEqual((st["rc"], st["ok"]), (0, True))

    def test_mail_all_paths_runs_owa_anyway(self):
        fake, led, _st = self.chain({"Get-OutlookData.ps1": com_ok, "Get-OutlookWeb.py": owa_all_ok},
                                    c={"mailViaCopilot": True, "collect": {"mailAllPaths": True}})
        self.assertEqual(fake.n("Get-OutlookWeb.py"), 1)
        owa = fake.args("Get-OutlookWeb.py")[0]
        self.assertEqual((_arg(owa, "--from"), _arg(owa, "--to")), (D0, D1))
        self.assertEqual(fake.n("Get-MailViaCopilot.py"), 0)

    def test_b_com_newol_index_zero_runs_owa(self):
        fake, led, _st = self.chain({"Get-OutlookData.ps1": com_newol, "Get-OutlookIndex.ps1": idx_empty,
                                     "Get-OutlookWeb.py": owa_all_ok}, c={"mailViaCopilot": False})
        self.assertEqual(fake.n("Get-OutlookWeb.py"), 1)
        owa = fake.args("Get-OutlookWeb.py")[0]
        self.assertEqual((_arg(owa, "--from"), _arg(owa, "--to"), _arg(owa, "--tag")), (D0, D1, "owa"))
        self.assertNotIn("--only", owa)
        self.assertNotIn("--force", owa)
        com = self.stage("Outlook 메일·일정")[0]
        self.assertEqual((com["rc"], com["reason"], com["ok"]), (3, "R-NEWOL", False))
        self.assertIn("의심(실측 전)", com["note"])

    def test_c_owa_verified_no_copilot(self):
        fake, led, _st = self.chain({"Get-OutlookData.ps1": com_newol, "Get-OutlookIndex.ps1": idx_empty,
                                     "Get-OutlookWeb.py": owa_all_ok}, c={"mailViaCopilot": True})
        self.assertEqual(fake.n("Get-MailViaCopilot.py"), 0)
        self.assertTrue(led.is_verified("2026-05-05", "mail_out"))

    def test_d_copilot_only_unverified_months(self):
        def owa(cmd):
            r = rngs(ALL, D0, "2026-02-28", "ok") + rngs(ALL, "2026-03-01", "2026-04-30", "unverified") \
                + rngs(ALL, "2026-05-01", D1, "ok")
            return 0, ["[owa] 일부", LM("owa", 0, "", r)]

        fake, led, _st = self.chain({"Get-OutlookData.ps1": com_newol, "Get-OutlookIndex.ps1": idx_empty,
                                     "Get-OutlookWeb.py": owa,
                                     "Get-MailViaCopilot.py": lambda c: (0, ["표", LM("copilot", 0)])},
                                    c={"mailViaCopilot": True})
        self.assertEqual(fake.n("Get-MailViaCopilot.py"), 1)
        cp = fake.args("Get-MailViaCopilot.py")[0]
        self.assertEqual(_arg(cp, "--ranges"), "2026-03-01:2026-04-30")
        self.assertEqual(_arg(cp, "--tag"), "copilot")
        self.assertNotIn("--only", cp)

    def test_index_recurring_master_calls_owa_cal(self):
        def idx(cmd):
            return 3, ["[outlook-index] 일정 불완전", LM("index", 3, "R-RECURINC",
                                                    rngs(("mail_in", "mail_out"), D0, D1, "ok")
                                                    + rngs(("cal",), D0, D1, "ok"), {"recurring_masters": 1})]

        fake, led, _st = self.chain({"Get-OutlookData.ps1": com_newol, "Get-OutlookIndex.ps1": idx,
                                     "Get-OutlookWeb.py": owa_all_ok}, c={"mailViaCopilot": False})
        self.assertEqual(fake.n("Get-OutlookWeb.py"), 1)
        self.assertEqual(_arg(fake.args("Get-OutlookWeb.py")[0], "--only"), "cal")
        self.assertTrue(self.stage("Outlook 대체① ")[0]["ok"])          # R-RECURINC — 저장은 했다

    def test_com_zero_ok_vs_index_rows_runs_owa_that_day(self):
        day = "2026-02-03"

        def com(cmd):
            r = rngs(ALL, D0, D1, "ok")
            r[0] = rng("mail_in", D0, "2026-02-02", "ok")
            r += [rng("mail_in", day, day, "zero_ok"), rng("mail_in", "2026-02-04", D1, "ok")]
            return 0, ["[outlook] done.", LM("com", 0, "", r)]

        def idx(cmd):
            _write_csv(os.path.join(_arg(cmd, "-OutDir"), "mail_index.csv"), "box,time,sender,subject,conversation,rcv",
                       [["inbox", f"{day} 09:0{i}", "a@x.com", f"제목{i}", f"제목{i}", "to"] for i in range(3)])
            return 0, ["ok", LM("index", 0, "", rngs(("mail_in",), day, day, "ok"))]

        fake, led, _st = self.chain({"Get-OutlookData.ps1": com, "Get-OutlookIndex.ps1": idx,
                                     "Get-OutlookWeb.py": owa_all_ok}, c={"mailViaCopilot": False})
        self.assertTrue(led.is_suspect(day, "mail_in"))
        self.assertEqual(fake.n("Get-OutlookWeb.py"), 1)
        owa = fake.args("Get-OutlookWeb.py")[0]
        self.assertEqual((_arg(owa, "--from"), _arg(owa, "--to"), _arg(owa, "--only")), (day, day, "mail"))
        self.assertTrue(led.is_verified(day, "mail_in"))                     # 웹이 확인했다
        self.assertEqual(len(_rows(os.path.join(self.data, "outlook", "mail.csv"))), 3)   # 병합은 색인 행을 살린다

    def test_e_window_rc0_still_runs_web(self):
        fake, led, _st = self.chain({
            "Get-TeamsWindow.ps1": lambda c: (0, ["새 3건", LM("teams_window", 0, "", [rng("teams", D1, D1, "partial")],
                                                            {"teams_present": True})]),
            "Get-TeamsWeb.py": lambda c: (0, ["방 10", LM("teams_web", 0, "", [rng("teams", D0, D1, "ok")],
                                                       {"teams_present": True})])}, teams=True, mail=False)
        self.assertEqual((fake.n("Get-TeamsWindow.ps1"), fake.n("Get-TeamsWeb.py")), (1, 1))
        web = fake.args("Get-TeamsWeb.py")[0]
        self.assertEqual((_arg(web, "--from"), _arg(web, "--to")), (D0, D1))
        self.assertFalse(led.na.get("teams"))

    def test_teams_no_trace_is_na(self):
        fake, led, _st = self.chain({
            "Get-TeamsWindow.ps1": lambda c: (1, ["팀즈 없음", LM("teams_window", 1, "R-NOTEAMS", [],
                                                             {"teams_present": False})]),
            "Get-TeamsWeb.py": lambda c: (1, ["방 0", LM("teams_web", 1, "", [], {"teams_present": False})])},
            c={"teamsViaCopilot": True}, teams=True, mail=False)
        self.assertTrue(led.na.get("teams"))
        self.assertEqual(led.gaps(("teams",), D0, D1)["teams"], [])
        self.assertEqual(fake.n("Get-TeamsViaCopilot.py"), 0)                 # na — 물을 공백이 없다

    def test_f_owa_login_skips_web_paths_and_keeps_edge(self):
        fake, led, state = self.chain({
            "Get-OutlookData.ps1": com_newol, "Get-OutlookIndex.ps1": idx_empty,
            "Get-OutlookWeb.py": lambda c: (2, ["로그인 필요", LM("owa", 2, "R-LOGIN", rngs(ALL, D0, D1, "unverified"))]),
            "Get-TeamsWindow.ps1": lambda c: (4, ["새 0", LM("teams_window", 4, "", [], {"teams_present": True})])},
            c={"mailViaCopilot": True, "teamsViaCopilot": True}, teams=True)
        self.assertTrue(state["login_pending"])
        self.assertEqual((fake.n("Get-TeamsWeb.py"), fake.n("Get-TeamsViaCopilot.py"),
                          fake.n("Get-MailViaCopilot.py")), (0, 0, 0))
        self.assertEqual(self.closed, [])                                     # 로그인 대기 중 — Edge 를 닫지 않는다
        owa = self.stage("Outlook 대체② ")[0]
        self.assertIn("로그인 필요", owa["note"])

    def test_edge_closed_once(self):
        state = {}
        with self.quiet():
            R.close_edge_once(state, "collect_end")
            R.close_edge_once(state, "run_end")
        self.assertEqual(self.closed, ["collect_end"])

    def test_web_only_mail_period_and_close(self):
        fake = FakeSteps({"Get-OutlookWeb.py": owa_all_ok})
        R._RUN_STEP = fake
        with self.quiet():
            rc = R.web_only({}, "mail", "2026-03-01", "2026-03-31", self.data, COL)
        self.assertEqual(rc, 0)
        owa = fake.args("Get-OutlookWeb.py")[0]
        self.assertEqual((_arg(owa, "--from"), _arg(owa, "--to")), ("2026-03-01", "2026-03-31"))
        self.assertEqual(self.closed, ["web_only"])

    def test_reset_cursors(self):
        for rel in (("outlook", "src", "coverage_com.json"), ("outlook", "coverage.json"), ("m365", "teams_web_rooms.json")):
            p = os.path.join(self.data, *rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                f.write("{}")
        led = R.open_ledger({}, self.data)
        led.apply({"src": "com", "rc": 0, "ranges": rngs(ALL, D0, D0, "ok")})
        led.save()
        with self.quiet():
            led2 = R.reset_cursors({}, self.data)
        self.assertFalse(any(os.path.exists(os.path.join(self.data, *r)) for r in (
            ("outlook", "src", "coverage_com.json"), ("outlook", "coverage.json"), ("m365", "teams_web_rooms.json"))))
        self.assertEqual(led2.composite(D0, "mail_in"), "not_attempted")
        self.assertEqual(R.open_ledger({}, self.data).composite(D0, "mail_in"), "not_attempted")


# ── mailmerge ──────────────────────────────────────────────────────────────
MAIL_H = "box,time,sender,subject,conversation,rcv,time_precision"


class MergeTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(prefix="lm28_p6m_")
        self.out = os.path.join(self._td.name, "data", "outlook")
        self.src = os.path.join(self.out, "src")
        os.makedirs(self.src)

    def tearDown(self):
        self._td.cleanup()

    def js(self, name, o):
        with open(os.path.join(self.src, name), "w", encoding="utf-8") as f:
            json.dump(o, f)

    def test_merge_rules(self):
        _write_csv(os.path.join(self.src, "mail_com.csv"), MAIL_H,
                   [["inbox", "2026-03-02 09:00", "a@x.com", "주간 회의 자료", "주간 회의 자료", "to", "minute"],
                    ["inbox", "2026-03-02 09:00", "a@x.com", "알림", "알림", "to", "minute"],
                    ["inbox", "2026-03-02 09:00", "a@x.com", "알림", "알림", "to", "minute"]])     # 같은 출처 2통은 그대로
        _write_csv(os.path.join(self.src, "mail_owa.csv"), MAIL_H,
                   [["inbox", "2026-03-02 09:01", "A", "주간 회의 자료", "주간 회의 자료", "to", "minute"],
                    ["sent", "2026-03-03", "나", "보고서 송부", "보고서 송부", "", "date"]])
        _write_csv(os.path.join(self.src, "mail_index.csv"), MAIL_H,
                   [["sent", "2026-03-03 17:20", "me@x.com", "보고서 송부", "보고서 송부", "", "minute"]])
        _write_csv(os.path.join(self.src, "mail_copilot.csv"), MAIL_H,
                   [["inbox", "2026-03-02", "B", "다른 메일", "다른 메일", "to", "date"],      # 그날 다른 출처 행 있음 → 0
                    ["inbox", "2026-03-05", "C", "증인 메일", "증인 메일", "to", "date"],      # 다른 출처 0 · 미확인 → 넣는다
                    ["inbox", "2026-03-06", "D", "확인된 날", "확인된 날", "to", "date"]])     # 원장이 확인한 날 → 0
        _write_csv(os.path.join(self.src, "cal_com.csv"), "start,end,all_day,busy_status,subject,categories,location",
                   [["2026-03-02 10:00", "2026-03-02 11:00", "False", "2", "설계 검토", "", "회의실"]])
        _write_csv(os.path.join(self.src, "cal_index.csv"), "start,end,all_day,busy_status,subject,categories,location",
                   [["2026-03-02 10:00", "2026-03-02 11:00", "False", "2", "설계 검토", "", ""]])
        self.js("mail_source_com.json", {"source": "com", "me": ["me@x.com"], "selftest": False})
        self.js("mail_source_index.json", {"source": "index", "me": ["me@x.com", "나"]})
        info = mailmerge.merge(self.src, self.out, verified=lambda d, ax: d == "2026-03-06", period=("2026-03-01", "2026-03-10"),
                               norm=lambda s: s, today=date(2026, 10, 7))
        self.assertTrue(info["ok"])
        mail = _rows(os.path.join(self.out, "mail.csv"))
        weekly = [r for r in mail if r["subject"] == "주간 회의 자료"]
        self.assertEqual([r["src"] for r in weekly], ["com"])                   # com/owa 같은 메일 → 1행 src=com
        self.assertEqual(sum(1 for r in mail if r["subject"] == "알림"), 2)
        rep = [r for r in mail if r["subject"] == "보고서 송부"]
        self.assertEqual(len(rep), 1)                                           # owa '날짜만' + 색인 분 단위 → 1행
        self.assertEqual((rep[0]["time"], rep[0]["time_precision"]), ("2026-03-03 17:20", "minute"))
        cps = [r for r in mail if r["src"] == "copilot"]
        self.assertEqual([r["time"] for r in cps], ["2026-03-05"])
        self.assertEqual(len(_rows(os.path.join(self.out, "calendar.csv"))), 1)
        with open(os.path.join(self.out, "mail_source.json"), encoding="utf-8") as f:
            ms = json.load(f)
        for k in ("source", "mail_rows", "date_only", "selftest", "uncovered_months", "me"):
            self.assertIn(k, ms)
        self.assertEqual(ms["source"], "com")
        self.assertEqual(sorted(ms["me"]), ["me@x.com", "나"])
        self.assertEqual(ms["mail_rows"], len(mail))
        self.assertEqual(ms["uncovered_months"], ["2026-03"])

    def test_no_sources_keeps_files(self):
        with open(os.path.join(self.out, "mail.csv"), "w", encoding="utf-8") as f:
            f.write("box,time\n")
        info = mailmerge.merge(self.src, self.out)
        self.assertEqual(info["error"], "no_sources")
        with open(os.path.join(self.out, "mail.csv"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "box,time\n")


# ── G1 ─────────────────────────────────────────────────────────────────────
class G1Tests(_RunEnv):
    def test_same_teams_message_twice_is_one_row(self):
        p = os.path.join(self.data, "m365", "teams_window.csv")
        raw = ["2026-03-04 10:15", "김철수", "설계팀", "msg", "", "연락처 010-1234-5678 로 회신 부탁드립니다"]
        _write_csv(p, "time,from,chat,kind,replied_time,summary", [raw])
        with self.quiet():
            R.g1_teams({}, self.data)
        with open(p, "a", encoding="utf-8", newline="") as f:     # 창 읽기(원문 키)가 같은 메시지를 다시 붙인다
            f.write(",".join(raw) + "\r\n")
        with self.quiet():
            R.g1_teams({}, self.data)
        rows = _rows(p)
        self.assertEqual(len(rows), 1)
        self.assertNotIn("010-1234-5678", rows[0]["summary"])
        self.assertTrue(os.path.exists(os.path.join(self.data, "privacy_audit.json")))


# ── proc ───────────────────────────────────────────────────────────────────
CHILD = r'''
import os, subprocess, sys, time
NO_WIN = 0x08000000
pf = sys.argv[1]
g1 = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"], creationflags=NO_WIN)
try:
    g2 = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"], creationflags=NO_WIN | 0x01000000)
    g2p = g2.pid
except OSError:
    g2p = 0
with open(pf + ".tmp", "w") as f:
    f.write(f"{os.getpid()} {g1.pid} {g2p}")
os.replace(pf + ".tmp", pf)
print("ready", flush=True)
time.sleep(120)
'''


def _alive(pid, wait_ms=0):
    """pid 가 (wait_ms 안에 끝나지 않고) 살아 있나 — OpenProcess + WaitForSingleObject(프로세스 없음)"""
    import ctypes
    from ctypes import wintypes
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k.OpenProcess.restype = wintypes.HANDLE
    k.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    k.WaitForSingleObject.restype = wintypes.DWORD
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    h = k.OpenProcess(0x00100000 | 0x1000, False, int(pid))
    if not h:
        return False
    try:
        return k.WaitForSingleObject(h, int(wait_ms)) == 0x102
    finally:
        k.CloseHandle(h)


@unittest.skipUnless(os.name == "nt", "Job Object 는 윈도 전용")
class ProcTests(unittest.TestCase):
    def test_timeout_kills_tree_but_breakaway_survives(self):
        with tempfile.TemporaryDirectory(prefix="lm28_p6p_") as td:
            script, pf = os.path.join(td, "child.py"), os.path.join(td, "pids.txt")
            with open(script, "w", encoding="utf-8") as f:
                f.write(CHILD)
            t0 = time.monotonic()

            def clk():                     # PID 파일이 생기면 100배 빠른 시계 — 시간 초과 300초 ≈ 실제 3초
                return (time.monotonic() - t0) * (100 if os.path.exists(pf) else 1)

            lines, pids = [], []
            try:
                rc, tail, how = proc.run_step([sys.executable, "-B", script, pf], 300, "시험 단계", clk,
                                              on_line=lines.append, poll=0.05)
                with open(pf, encoding="utf-8") as f:
                    pids = [int(x) for x in f.read().split()]
                child, g1, g2 = pids
                self.assertEqual((rc, how), (-1, "timeout"))
                self.assertIn("ready", tail)
                self.assertGreaterEqual(sum(1 for x in lines if "진행 중" in x), 2)       # 시계 주입 진행 줄
                self.assertFalse(_alive(child, 5000))
                self.assertFalse(_alive(g1, 5000))                                       # 손자도 Job 째 끝났다
                self.assertLessEqual(len([p for p in pids if p]), 3)
                if g2:
                    self.assertTrue(_alive(g2))                                         # Job 에서 이탈한 손자(Edge 자리)는 산다
                else:
                    print("\n   [p6] 이 실행 환경은 Job 이탈(CREATE_BREAKAWAY_FROM_JOB)을 막습니다 — 생존 단언 생략")
            finally:
                for p in pids:
                    if p and _alive(p):
                        try:
                            os.kill(p, signal.SIGTERM)
                        except OSError:
                            pass
                for p in pids:
                    if p:
                        self.assertFalse(_alive(p, 5000))


# ── 샘플러·등록 ─────────────────────────────────────────────────────────────
class SamplerTests(_RunEnv):
    def _stale(self, status):
        act = os.path.join(self.data, "activity")
        os.makedirs(act)
        p = os.path.join(act, "activity_2026-10-01.csv")
        with open(p, "w", encoding="utf-8") as f:
            f.write("time,process\n")
        old = time.time() - 3600
        os.utime(p, (old, old))
        with open(os.path.join(act, "sampler_status.json"), "w", encoding="utf-8-sig") as f:
            json.dump(status, f)
        self.spawned = []
        R._START_PROCESS = lambda cmd: self.spawned.append(cmd) or True
        R._mutex_exists = lambda name: False

    def test_no_registered_no_spawn(self):
        self._stale({"ok": True, "heartbeat": "2026-10-01 10:00:00", "interval_s": 60})
        with self.quiet():
            R.ensure_sampler({"autoRestartSampler": True}, self.data, COL)
        self.assertEqual(self.spawned, [])
        self.assertIn("등록 흔적", self.stage("창 샘플러 점검")[0]["note"])

    def test_default_off_no_spawn(self):
        self._stale({"ok": True, "heartbeat": "2026-10-01 10:00:00", "interval_s": 60, "registered": True})
        with self.quiet():
            R.ensure_sampler({}, self.data, COL)                    # autoRestartSampler 키 없음 = false
        self.assertEqual(self.spawned, [])

    def test_registered_and_on_spawns_once(self):
        self._stale({"ok": True, "heartbeat": "2026-10-01 10:00:00", "interval_s": 60, "registered": True})
        with self.quiet():
            R.ensure_sampler({"autoRestartSampler": True}, self.data, COL)
        self.assertEqual(len(self.spawned), 1)
        self.assertTrue(self.spawned[0][-1].endswith("Start-ActivitySampler.ps1"))

    def test_clm_not_restarted(self):
        self._stale({"ok": False, "reason": "R-CLM", "registered": True})
        with self.quiet():
            R.ensure_sampler({"autoRestartSampler": True}, self.data, COL)
        self.assertEqual(self.spawned, [])
        self.assertEqual(self.stage("창 샘플러 점검")[0]["reason"], "R-CLM")

    def test_register_off_no_schtasks(self):
        calls = []
        saved = R.subprocess.run
        R._RUN_STEP = lambda *a, **k: calls.append(a) or (0, [], "ok")
        R.subprocess.run = lambda *a, **k: calls.append(a)
        try:
            with self.quiet():
                R.register_sampler_once(PS, COL, {"autoRegisterSampler": False})
        finally:
            R.subprocess.run = saved
        self.assertEqual(calls, [])


class StaticTests(unittest.TestCase):
    def test_run_py_rules(self):
        src = _boot.read_text(os.path.join(ROOT, "run.py"))
        self.assertNotIn('"taskkill"', src)                       # taskkill 을 띄우지 않는다(주석의 낱말은 괜찮다)
        self.assertNotIn('get("autoRestartSampler", True)', src)
        self.assertNotIn('get("autoRegisterSampler", True)', src)
        self.assertNotIn("from mine import EXCLUDE", src)
        self.assertNotIn("os.remove(cov_p)", src)                 # COM 달별 완료 표 삭제 없음
        self.assertNotIn('c.get("preferApp", True)', src)         # 앱 창 단락 없음(W1-01)
