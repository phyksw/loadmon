# -*- coding: utf-8 -*-
r"""test_p4_pc.py — WP4: PC 수집기 보강(외부 프로세스 최소).

  · Get-PcOnHints : 합성 History(visit_source 에 source=0 1건) → 방문 2건(동기화 1건 제외) · includeSynced 면 3건
  · Get-GitActivity: git 실행기 주입 — 저장소 20 → git 21회(전역 설정 1 + 저장소별 log) · git 없음 → rc 3 R-NOGIT
  · pc_ledger     : 잠금 선점 상태에서 ingest → append 0 · rc 3 · 관측 파일 보존 → 풀면 반영
  · 정적          : 확인 경로 BEL 없음 · 파일 새 열 · LMSTATUS
  · --ps          : tests\ps\Test-PcCollect.ps1 결과 단언(MRU 5건·Add-WorkLog 구간·Get-PcOnHistory 원장 반영 실패 rc 3)
실 Outlook·Edge·작업 스케줄러·git 은 띄우지 않는다. 임시 파일은 tempfile.TemporaryDirectory 안에만 만든다.
"""
import contextlib
import importlib.util
import io
import json
import os
import re
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta

import _boot

ROOT = _boot.ROOT
MY_PS = ["Get-PcOnHistory.ps1", "Get-RecentFiles.ps1", "Get-FileActivity.ps1", "Add-WorkLog.ps1"]


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, rel))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _lmstatus(text):
    """출력의 마지막 줄이 LMSTATUS 여야 한다 → dict"""
    lines = [ln for ln in text.strip().splitlines() if ln.strip()]
    assert lines and lines[-1].startswith("LMSTATUS "), lines[-3:]
    return json.loads(lines[-1][len("LMSTATUS "):])


def _src(rel):
    return _boot.read_text(os.path.join(ROOT, rel))


def _json(path):
    with open(path, encoding="utf-8-sig") as f:
        return json.load(f)


class PcHintsSynced(unittest.TestCase):
    """Get-PcOnHints: visit_source=0(동기화) 제외(pcHints.includeSynced=false)"""

    def _history(self, d, with_source=True):
        hints = _load("lm28_pc_hints", os.path.join("collect", "Get-PcOnHints.py"))
        db = os.path.join(d, "History")
        con = sqlite3.connect(db)
        try:
            con.execute("CREATE TABLE visits (id INTEGER PRIMARY KEY, url INTEGER, visit_time INTEGER)")
            base = datetime(2026, 3, 2, 9, 0)
            for i, m in enumerate((0, 10, 20), 1):
                con.execute("INSERT INTO visits VALUES (?, 0, ?)", (i, hints._chrome_us(base + timedelta(minutes=m))))
            if with_source:
                con.execute("CREATE TABLE visit_source (id INTEGER PRIMARY KEY, source INTEGER NOT NULL)")
                con.execute("INSERT INTO visit_source VALUES (2, 0)")     # 다른 기기에서 동기화된 방문 1건
                con.execute("INSERT INTO visit_source VALUES (3, 8)")     # source=8 은 이 PC 방문 — 센다(LM24 실측)
            con.commit()
        finally:
            con.close()
        return hints, db

    def _visits(self, hints, db, d, **kw):
        old = tempfile.tempdir
        tempfile.tempdir = d                     # 사본(lm28_hist_copy)도 이 임시 폴더 안에 — %TEMP% 에 남기지 않는다
        try:
            return hints.visit_times(db, datetime(2026, 3, 2), datetime(2026, 3, 3), **kw)
        finally:
            tempfile.tempdir = old

    def test_synced_visit_excluded(self):
        with tempfile.TemporaryDirectory(prefix="lm28_t4_") as d:
            hints, db = self._history(d)
            st = {}
            got = self._visits(hints, db, d, stats=st)
            self.assertEqual(len(got), 2)                 # 집계 2 — 동기화 1건 제외
            self.assertEqual(st.get("synced"), 1)
            self.assertEqual(len(self._visits(hints, db, d, include_synced=True)), 3)
            self.assertFalse(os.path.exists(os.path.join(d, "lm28_hist_copy")), "History 사본이 남았다")
            spans = hints.to_spans(got)
            self.assertEqual(len(spans), 1)

    def test_old_schema_without_visit_source(self):
        with tempfile.TemporaryDirectory(prefix="lm28_t4_") as d:
            hints, db = self._history(d, with_source=False)
            self.assertEqual(len(self._visits(hints, db, d, stats={})), 3)

    def test_config_default_off(self):
        c = _json(os.path.join(ROOT, "config", "config.default.json"))
        self.assertIs(c["pcHints"]["includeSynced"], False)
        src = _src(os.path.join("collect", "Get-PcOnHints.py"))
        self.assertIn('get("includeSynced", False)', src)
        self.assertIn("lm28_hist_copy", src)


class GitCalls(unittest.TestCase):
    """Get-GitActivity: git 실행 = 1 + 저장소 수 · git 없음 → rc 3 R-NOGIT"""

    def setUp(self):
        self.git = _load("lm28_git_collector", os.path.join("collect", "Get-GitActivity.py"))

    def _run(self, d, repos, find_git, spawn):
        g = self.git
        cfgp = os.path.join(d, "config.json")
        with open(cfgp, "w", encoding="utf-8") as f:
            json.dump({"gitRepos": repos, "excludePathKeywords": [], "autoDiscoverFolders": False,
                       "watchFolders": []}, f)
        saved = {k: getattr(g, k) for k in ("CFG", "DATA", "OUT", "_find_git", "_spawn")}
        g.CFG, g.DATA, g.OUT = cfgp, os.path.join(d, "data"), os.path.join(d, "data", "files")
        g._find_git, g._spawn = find_git, spawn
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                rc = g.main(["--from", "2026-03-01", "--to", "2026-03-31"])
        finally:
            for k, v in saved.items():
                setattr(g, k, v)
        return rc, out.getvalue()

    def _repos(self, d, n):
        repos = []
        for i in range(n):
            r = os.path.join(d, "repos", f"r{i:02d}")
            os.makedirs(os.path.join(r, ".git"))
            with open(os.path.join(r, ".git", "config"), "w", encoding="utf-8") as f:
                f.write("[core]\n\trepositoryformatversion = 0\n")
                if i == 3:
                    f.write('[user]\n\tname = "Repo Tester"  ; 주석\n\temail = repo@example.com\n')
            repos.append(r)
        return repos

    def test_twenty_repos_twenty_one_calls(self):
        calls = []

        def spawn(cmd, timeout, env):
            calls.append(list(cmd))
            if "config" in cmd:
                return b"user.name Tester\nuser.email tester@example.com\n", 0, b""
            return b"", 0, b""

        with tempfile.TemporaryDirectory(prefix="lm28_t4_") as d:
            repos = self._repos(d, 20)
            rc, out = self._run(d, repos, lambda cfg=None: (os.path.join(d, "git.exe"), ["test"]), spawn)
            st = _lmstatus(out)
            src = _json(os.path.join(d, "data", "git_source.json"))
        self.assertEqual(rc, 0, out[-600:])
        self.assertEqual(len(calls), 21)                                   # 1 + 저장소 수
        self.assertEqual(sum(1 for c in calls if "log" in c), 20)
        self.assertEqual(sum(1 for c in calls if "--global" in c), 1)
        self.assertFalse(any("-C" in c for c in calls if "--global" in c))
        self.assertEqual((st["rc"], st["src"], st["counts"]["git_calls"]), (0, "git", 21))
        self.assertEqual(src["status"], "ok")
        self.assertEqual(src["identities"], 4)          # 전역 이름·메일 + 저장소 .git\config 의 이름·메일

    def test_no_git_rc3(self):
        calls = []
        with tempfile.TemporaryDirectory(prefix="lm28_t4_") as d:
            repos = self._repos(d, 2)
            rc, out = self._run(d, repos, lambda cfg=None: (None, ["PATH"]),
                                lambda cmd, timeout, env: calls.append(cmd) or (b"", 0, b""))
            st = _lmstatus(out)
            src = _json(os.path.join(d, "data", "git_source.json"))
        self.assertEqual(rc, 3)
        self.assertEqual((st["rc"], st["reason"]), (3, "R-NOGIT"))
        self.assertEqual(calls, [])
        self.assertEqual(src["status"], "no_git")

    def test_all_failed_rc3_and_no_repos_rc1(self):
        with tempfile.TemporaryDirectory(prefix="lm28_t4_") as d:
            repos = self._repos(d, 2)
            rc, out = self._run(d, repos, lambda cfg=None: (os.path.join(d, "git.exe"), ["test"]),
                                lambda cmd, timeout, env: (b"", 128, b"fatal: not a git repository"))
            st = _lmstatus(out)
            self.assertEqual((rc, st["rc"], st["reason"]), (3, 3, "R-GITFAIL"))
            rc, out = self._run(d, [], lambda cfg=None: (os.path.join(d, "git.exe"), ["test"]),
                                lambda cmd, timeout, env: (b"", 0, b""))
            st = _lmstatus(out)
            self.assertEqual((rc, st["rc"]), (0, 1))     # 저장소 없음 — 대상 없음(종료 코드 0)

    def test_parse_git_config_user(self):
        txt = ('[core]\n\tbare = false\n[User]\n\tName = "Kim Tester"\n\temail = t@example.com ; c\n'
               '# x\n[user "sub"]\n\tname = Nope\n[remote "origin"]\n\tname = no\n')
        self.assertEqual(self.git.parse_git_config_user(txt), ["Kim Tester", "t@example.com"])


class LedgerLockBusy(unittest.TestCase):
    """pc_ledger: 잠금을 못 얻으면 append 0 · rc 3 · 관측 보존"""

    def test_busy_no_append_rc3(self):
        import msvcrt

        import pc_ledger
        with tempfile.TemporaryDirectory(prefix="lm28_t4_") as d:
            ev = os.path.join(d, "pc_events_new.csv")
            with open(ev, "w", encoding="utf-8", newline="") as f:
                f.write("start,end,src\r\n2026-03-02 08:00:00,2026-03-02 18:00:00,event\r\n"
                        "2026-03-03 08:30:00,2026-03-03 17:30:00,event\r\n")
            lk = open(os.path.join(d, ".ledger.lock"), "a+")
            old = pc_ledger.LOCK_WAIT_S
            pc_ledger.LOCK_WAIT_S = 0.3
            try:
                msvcrt.locking(lk.fileno(), msvcrt.LK_NBLCK, 1)       # 다른 수집이 쓰는 중
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    rc = pc_ledger.main(["--ingest", d])
                self.assertEqual(rc, 3, out.getvalue())
                self.assertIn("보류", out.getvalue())
                self.assertFalse(os.path.exists(os.path.join(d, "pc_spans.csv")), "잠금 없이 append 했다")
                self.assertTrue(os.path.exists(ev), "관측 파일을 지웠다(다음 실행이 회수할 수 없다)")
                a = datetime(2026, 3, 4, 9, 0)
                with self.assertRaises(pc_ledger.LedgerBusy):
                    pc_ledger.append_spans(d, [(a, a + timedelta(hours=1), "hint")])
                with self.assertRaises(OSError):                    # 기존 except OSError 호출자는 '보류' 로 처리한다
                    pc_ledger.regen_pc_on(d)
                lk.seek(0)
                msvcrt.locking(lk.fileno(), msvcrt.LK_UNLCK, 1)
                with contextlib.redirect_stdout(io.StringIO()):
                    rc2 = pc_ledger.main(["--ingest", d])
                self.assertEqual(rc2, 0)
                rows, _bad = pc_ledger.read_spans(d)
                self.assertEqual(len(rows), 2)
                self.assertFalse(os.path.exists(ev))
            finally:
                pc_ledger.LOCK_WAIT_S = old
                lk.close()


class StaticChecks(unittest.TestCase):
    """파일 규칙 — 프로세스 없이"""

    def test_no_bel_in_my_scripts(self):
        for f in MY_PS:
            with open(os.path.join(ROOT, "collect", f), "rb") as fh:
                self.assertNotIn(b"\x07", fh.read(), f)

    def test_file_activity_new_columns(self):
        s = _src(os.path.join("collect", "Get-FileActivity.ps1"))
        m = re.search(r"\$header = @\(([^)]*)\)", s)
        cols = [c.strip().strip("'") for c in m.group(1).split(",")]
        self.assertEqual(cols, ["mtime", "ext", "size_kb", "folder", "name", "author", "total_time", "revision"])
        fmt = re.search(r"\$rows\.Add\(\('(\{0\}(?:,\{\d\})+)' -f", s).group(1)
        self.assertEqual(fmt.count("{"), len(cols))
        self.assertIn("docProps/app.xml", s)
        self.assertIn("<TotalTime>", s)

    def test_pc_history_ts_and_lmstatus(self):
        s = _src(os.path.join("collect", "Get-PcOnHistory.ps1"))
        self.assertIn("Microsoft-Windows-TerminalServices-LocalSessionManager/Operational", s)
        self.assertIn("Id=@(21,23,24,25)", s)
        self.assertIn("Write-LmStatus 3 'R-INGEST'", s)
        self.assertIn("$ingRc = $LASTEXITCODE", s)
        self.assertIn("channels = $channels", s)

    def test_recent_versions(self):
        s = _src(os.path.join("collect", "Get-RecentFiles.ps1"))
        self.assertIn("$OfficeMruVersions = @('14.0', '15.0', '16.0')", s)
        self.assertNotIn("Office\\16.0\\$app", s)
        for r in ("R-RECENTPOLICY", "R-MRUEMPTY"):
            self.assertIn(r, s)

    def test_worklog_args(self):
        s = _src(os.path.join("collect", "Add-WorkLog.ps1"))
        self.assertIn("[string]$Start = ''", s)
        self.assertIn("[string]$End = ''", s)
        self.assertIn("$header = 'date,category,hours,entity,note,user,start,end'", s)


class PsPcCollect(unittest.TestCase):
    """--ps: tests\\ps\\Test-PcCollect.ps1"""

    def setUp(self):
        self.r = _boot.ps_result("PcCollect")
        if self.r is None:
            self.skipTest("PowerShell 결과 없음 — tests\\run_tests.py --ps 로 실행")
        self.assertNotIn("error", self.r, self.r)

    def test_files_clean(self):
        self.assertEqual(self.r["bel_files"], [])
        self.assertEqual(self.r["parse_errors"], [])
        self.assertTrue(self.r["tmp_removed"])

    def test_mru_fake_hash(self):
        r = self.r
        self.assertEqual(r["mru_items"], 5)
        self.assertEqual(r["mru_keys"], 4)
        self.assertEqual(r["mru_versions"], ["14.0", "15.0", "16.0"])
        self.assertEqual(sorted(r["mru_paths"]), sorted(["C:\\work\\a.docx", "C:\\work\\b.doc", "D:\\proj\\c.xlsx",
                                                 "\\\\server\\share\\d.pptx", "C:\\work\\e.pptx"]))

    def test_worklog_span(self):
        r = self.r
        self.assertEqual(r["wl_header"], "date,category,hours,entity,note,user,start,end")
        self.assertEqual(r["wl_rows"], ["2026-03-01|trip|8||", "2026-03-02|site|2.5|09:30|12:00",
                                        "2026-03-02|night|3.5|22:00|01:30", "2026-03-03|fixed|2|13:00|17:00"])
        self.assertTrue(r["wl_half_span_rejected"])

    def test_pc_history_ingest_rc(self):
        r = self.r
        if "pc_skipped" in r:
            self.skipTest(r["pc_skipped"])
        self.assertEqual(r["pc_busy_rc"], 3)
        self.assertTrue(r["pc_busy_last_is_status"])
        st = json.loads(r["pc_busy_status"][len("LMSTATUS "):])
        self.assertEqual((st["rc"], st["reason"], st["src"]), (3, "R-INGEST", "pc_events"))
        self.assertTrue(r["pc_busy_kept"])
        self.assertFalse(r["pc_busy_spans"])
        self.assertEqual(r["pc_ok_rc"], 0)
        st = json.loads(r["pc_ok_status"][len("LMSTATUS "):])
        self.assertEqual(st["rc"], 0)
        self.assertEqual([(x["from"], x["to"], x["st"]) for x in st["ranges"]],
                         [("2026-03-01", "2026-03-01", "unverified"), ("2026-03-02", "2026-03-03", "ok")])
        self.assertEqual(r["pc_ok_merged_note"], 1)
        self.assertFalse(r["pc_ok_kept"])
        self.assertEqual(r["pc_ok_span_rows"], 2)
        self.assertEqual(r["pc_channels"], "synthetic=ok")


if __name__ == "__main__":
    unittest.main()
