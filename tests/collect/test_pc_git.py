# -*- coding: utf-8 -*-
"""WP-14 pc.git 수집기 시험 — collect\\Get-GitActivity.py. %TEMP% 의 합성 git 저장소(전역·시스템 git 설정 격리)만 읽고,
정제·저장(WP-11 lm27.privacy.sanitize · lm27.store)은 계약 시그니처대로 만든 시험 안 가짜로 대체한다(계획 §4 이음매).

CP §9 · CP-14(git 신원 유사 동료명 — 정확 일치만, git 없음 → rc 3 · R-NOGIT) · 계약 §3.10(pc.git 커서 {last_ts_utc, repos}) ·
§7.3(PY 수집기는 flush 성공 뒤에만 save_raw_cursor) · §8.1 rc · L-05 · L-10 · P §10.2(작성자 신원은 원시에 넣지 않는다).
"""
import ast
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import tempfile
import unittest
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from tests.fixtures.tree import CloneTestCase
from tests.fixtures.wp14 import gitrepo

TREE = Path(__file__).resolve().parents[2]
SCRIPT = TREE / "collect" / "Get-GitActivity.py"
PC = "pc_" + "1a2b3c4d5e6f7081"
SELF = ("홍길동", "hong.gd@example.com")
KST = timezone(timedelta(hours=9))
RAW_KEYS = {"repo_root", "commit_sha", "subject", "n_commits", "n_files", "exts", "ts_utc", "ts_local_offset",
            "ts_precision", "observed_at", "confidence", "flags"}


def load_module():
    spec = importlib.util.spec_from_file_location("lm27t_get_git_activity", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


G = load_module()


# ── WP-11 계약 시그니처대로 만든 가짜(정제·저장) ────────────────────────────
class FakeRow:
    def __init__(self, data):
        self.data = data


class FakeOutcome:
    def __init__(self, status, row=None, reason=None):
        self.status, self.row, self.reason, self.hits = status, row, reason, {}


class FakeAudit:
    def __init__(self):
        self.flushes = []

    def flush(self, **numbers):
        self.flushes.append(numbers)


class FakeCtx:
    def __init__(self, args):
        self.args = args
        self.audit = FakeAudit()


class FakeApi:
    def __init__(self, *, cursor=None, drop=None, fail_flush=False):
        self.cursor = cursor
        self.drop = drop or (lambda raw: False)
        self.fail_flush = fail_flush
        self.raws, self.appended, self.saved, self.ctx = [], [], [], None
        api = self

        class Writer:
            def __init__(self, paths, pc_id, kind, src):
                api.writer_args = (pc_id, kind, src)
                self.rows = []

            def append(self, row):
                self.rows.append(row)

            def flush(self):
                if api.fail_flush:
                    raise OSError("disk")
                api.appended += self.rows
                return len(self.rows)

            def close(self):
                api.closed = True

        self.Writer = Writer

    def make_record_context(self, root, src, pc_id, **kw):
        self.ctx = FakeCtx((root, src, pc_id, kw))
        return self.ctx

    def sanitize_record(self, kind, raw, rc):
        assert kind == "pc_git" and rc is self.ctx
        self.raws.append(dict(raw))
        if self.drop(raw):
            return FakeOutcome("dropped", None, "private_folder")
        data = {"kind": kind, "src": "pc.git", "ts_utc": raw["ts_utc"],
                "doc_key": "r" + hashlib.sha1(raw["repo_root"].lower().encode()).hexdigest()[:16],
                "commit_key": "g" + hashlib.sha1(raw["commit_sha"].encode()).hexdigest()[:16]}
        return FakeOutcome("stored", FakeRow(data))

    def load_raw_cursor(self, paths, pc_id):
        return {"pc.git": self.cursor} if self.cursor is not None else {}

    def save_raw_cursor(self, paths, pc_id, src, value):
        self.saved.append((pc_id, src, value))

    def api(self):
        return {"make_record_context": self.make_record_context, "sanitize_record": self.sanitize_record,
                "SegmentWriter": self.Writer, "load_raw_cursor": self.load_raw_cursor,
                "save_raw_cursor": self.save_raw_cursor}


class _Paths:
    def __init__(self, root):
        self.root = Path(root)


@unittest.skipUnless(gitrepo.git_exe(), "git 실행 파일이 없는 PC")
class GitCollectTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="lm27t_wp14git_"))
        cls.env = gitrepo.isolated_env(cls.tmp / "cfg")
        r = gitrepo.make_repo(cls.tmp / "src" / "자동화도구", *SELF, env=cls.env)
        cls.repo = r
        c = gitrepo.commit
        cls.shas = {}
        cls.shas["d2"] = c(r, *SELF, datetime(2026, 9, 2, 10, 0, tzinfo=KST), "변환 스크립트 수정", {"a.py": "1", "b.md": "1"},
                           env=cls.env)
        cls.shas["d3"] = c(r, *SELF, datetime(2026, 9, 3, 11, 0, tzinfo=KST), "시험 추가", {"a.py": "2"}, env=cls.env)
        c(r, "홍길동A", "hong.gda@example.com", datetime(2026, 9, 3, 12, 0, tzinfo=KST), "동료 커밋", {"c.py": "1"}, env=cls.env)
        c(r, "김철수", "kim.cs@example.com", datetime(2026, 9, 3, 13, 0, tzinfo=KST), "동료 커밋 2", {"d.py": "1"}, env=cls.env)
        cls.shas["d4"] = c(r, *SELF, datetime(2026, 9, 4, 9, 30, tzinfo=KST), "로그 정리", {"e.txt": "1"}, env=cls.env)
        gitrepo.branch(r, "feature", env=cls.env)
        cls.shas["d5"] = c(r, *SELF, datetime(2026, 9, 5, 15, 0, tzinfo=KST), "기능 분리", {"f.py": "1"}, env=cls.env)
        gitrepo.checkout(r, "main", env=cls.env)
        c(r, *SELF, datetime(2026, 9, 5, 16, 0, tzinfo=KST), "본선 변경", {"g.py": "1"}, env=cls.env)
        gitrepo.merge(r, "feature", datetime(2026, 9, 6, 9, 0, tzinfo=KST), env=cls.env)        # 병합 커밋 → 제외
        c(r, *SELF, datetime(2026, 8, 1, 9, 0, tzinfo=KST), "옛 작성(재배치)", {"h.py": "1"}, env=cls.env,
          committer_when=datetime(2026, 9, 6, 10, 0, tzinfo=KST))                               # 작성일이 기간 밖
        cls.shas["utc"] = c(r, *SELF, datetime(2026, 9, 7, 1, 0, tzinfo=UTC), "UTC 환경 커밋", {"i.py": "1"}, env=cls.env)
        cls.shas["mail"] = c(r, "hong", SELF[1], datetime(2026, 9, 8, 9, 0, tzinfo=KST), "메일만 같은 신원", {"j.py": "1"},
                             env=cls.env)
        cls.expected = 7                                                                       # d2 d3 d4 d5 본선 utc mail
        cls.not_repo = cls.tmp / "src" / "그냥폴더"
        cls.not_repo.mkdir(parents=True)

    @classmethod
    def tearDownClass(cls):
        gitrepo.remove_tree(cls.tmp)

    def cfg(self, **kw):
        c = {"pc.git.exe": "", "pc.git.repos": [str(self.repo)], "pc.git.scanRoots": [], "collect.lookbackDays": 120,
             "pc.watchFolders": [], "pc.autoDiscoverFolders": False, "pc.excludePackageDirs": True}
        c.update(kw)
        return c

    def run_collect(self, fake=None, *, cfg=None, now=datetime(2026, 9, 30, 3, 0, tzinfo=UTC), env=None, **kw):
        fake = fake or FakeApi()
        with mock.patch.dict(os.environ, {**self.env, **(env or {})}):
            st = G.collect(_Paths(self.tmp), cfg or self.cfg(), PC, d0=date(2026, 9, 1), d1=date(2026, 9, 30), now=now,
                           api=fake.api(), **kw)
        return st, fake

    def test_exact_identity_all_branches_no_merges(self):
        st, f = self.run_collect()
        self.assertEqual(st["rc"], 0, st)
        self.assertEqual(st["n"], self.expected)
        subjects = sorted(r["subject"] for r in f.raws)
        self.assertNotIn("동료 커밋", subjects)
        self.assertNotIn("동료 커밋 2", subjects)
        self.assertNotIn("옛 작성(재배치)", subjects)
        self.assertFalse(any(s.startswith("merge") for s in subjects))
        self.assertIn("기능 분리", subjects)                                   # 피처 브랜치
        self.assertIn("메일만 같은 신원", subjects)                              # 메일 정확 일치
        for raw in f.raws:
            self.assertEqual(set(raw), RAW_KEYS)                               # 작성자 신원 없음
            self.assertEqual(raw["n_commits"], 1)
            self.assertEqual(raw["repo_root"], str(self.repo))
        self.assertEqual(f.ctx.args[:3], (self.tmp, "pc.git", PC))
        self.assertEqual(f.writer_args, (PC, "pc_git", "pc.git"))
        self.assertEqual(len(f.appended), self.expected)
        self.assertEqual(st["stored"], self.expected)
        self.assertEqual(f.ctx.audit.flushes[0]["rows_out"], self.expected)

    def test_fields_time_exts(self):
        _st, f = self.run_collect()
        by = {r["commit_sha"]: r for r in f.raws}
        d2 = by[self.shas["d2"]]
        self.assertEqual(d2["ts_utc"], "2026-09-02T01:00:00Z")
        self.assertEqual(d2["exts"], [".md", ".py"])
        self.assertEqual(d2["n_files"], 2)
        self.assertEqual(d2["ts_precision"], "minute")
        self.assertRegex(d2["ts_local_offset"], r"^[+-]\d{2}:\d{2}$")
        self.assertEqual(by[self.shas["utc"]]["ts_utc"], "2026-09-07T01:00:00Z")    # 작성 시각 오프셋과 무관한 같은 순간
        self.assertEqual(d2["observed_at"], "2026-09-30T03:00:00Z")
        ts = [r["ts_utc"] for r in f.raws]
        self.assertEqual(ts, sorted(ts))

    def test_python_gate_exact_even_without_author_regex(self):
        """--author 1차 관문이 없어도(정규식 우회) 파이썬 정확 일치가 동료 커밋을 막는다 — 이전 판 C2 회귀."""
        with mock.patch.object(G, "author_patterns", lambda authors: []):
            st, f = self.run_collect()
        self.assertEqual(st["n"], self.expected)
        self.assertEqual(st["others_excluded"], 2)
        self.assertNotIn("동료 커밋", [r["subject"] for r in f.raws])

    def test_username_not_used_when_git_identity_exists(self):
        st, f = self.run_collect(env={"USERNAME": "hong"})
        self.assertEqual(st["identity_fallback"], 0)
        self.assertEqual(st["n"], self.expected)

    def test_cursor_saved_after_flush_and_incremental(self):
        st1, f1 = self.run_collect()
        self.assertEqual(len(f1.saved), 1)
        pc, src, cur = f1.saved[0]
        self.assertEqual((pc, src), (PC, "pc.git"))
        self.assertEqual(cur["last_ts_utc"], "2026-09-08T00:00:00Z")
        dk = "r" + hashlib.sha1(str(self.repo).lower().encode()).hexdigest()[:16]
        self.assertEqual(cur["repos"], {dk: "g" + hashlib.sha1(self.shas["mail"].encode()).hexdigest()[:16]})
        st2, f2 = self.run_collect(FakeApi(cursor=cur))
        self.assertEqual((st2["rc"], st2["n"]), (4, 0))                          # 읽었지만 새 커밋 0
        self.assertEqual(f2.saved[0][2]["last_ts_utc"], cur["last_ts_utc"])

    def test_dropped_rows_not_written(self):
        fake = FakeApi(drop=lambda raw: "UTC" in raw["subject"])
        st, f = self.run_collect(fake)
        self.assertEqual(st["dropped"], {"private_folder": 1})
        self.assertEqual(len(f.appended), self.expected - 1)
        self.assertEqual(st["rows_in"], self.expected)

    def test_writer_failure_no_cursor(self):
        st, f = self.run_collect(FakeApi(fail_flush=True))
        self.assertEqual((st["rc"], st["reasons"]), (3, ["R-TRANSPORT"]))
        self.assertEqual(f.saved, [])

    def test_all_repos_failed_is_nogit(self):
        st, f = self.run_collect(cfg=self.cfg(**{"pc.git.repos": [str(self.not_repo)]}))
        self.assertEqual((st["rc"], st["reasons"]), (3, ["R-NOGIT"]))
        self.assertEqual(st["repos_failed"], 1)
        self.assertEqual(f.raws, [])

    def test_no_repos_rc1_and_missing_count(self):
        st, f = self.run_collect(cfg=self.cfg(**{"pc.git.repos": [str(self.tmp / "없는저장소")]}))
        self.assertEqual(st["rc"], 1)
        self.assertEqual(st["repos_missing"], 1)
        self.assertEqual(f.saved, [])

    def test_scan_roots_find_repo_skip_package_dirs(self):
        nm = self.tmp / "scan" / "node_modules" / "lib"
        gitrepo.make_repo(nm, *SELF, env=self.env)
        rel = self.tmp / "scan" / "Release" / "fw"                             # 표식 없는 release 아래 저장소는 찾는다
        gitrepo.make_repo(rel, *SELF, env=self.env)
        found = G.find_repos([str(self.tmp / "scan")])
        self.assertEqual([Path(p) for p in found], [rel])
        st, _f = self.run_collect(cfg=self.cfg(**{"pc.git.repos": [], "pc.git.scanRoots": [str(self.tmp / "src")]}))
        self.assertEqual(st["repos"], 1)

    def test_git_not_found_nogit(self):
        empty = self.tmp / "nogit"
        empty.mkdir(exist_ok=True)
        env = {"PATH": str(empty), "ProgramFiles": str(empty), "ProgramFiles(x86)": str(empty), "LOCALAPPDATA": str(empty)}
        st, f = self.run_collect(cfg=self.cfg(**{"pc.git.exe": str(empty / "git.exe")}), env=env)
        self.assertEqual((st["rc"], st["reasons"], st["git"]), (3, ["R-NOGIT"], "missing"))
        self.assertEqual(f.raws, [])

    def test_no_repos_and_no_git_is_rc1(self):
        empty = self.tmp / "nogit2"
        empty.mkdir(exist_ok=True)
        env = {"PATH": str(empty), "ProgramFiles": str(empty), "ProgramFiles(x86)": str(empty), "LOCALAPPDATA": str(empty)}
        st, _f = self.run_collect(cfg=self.cfg(**{"pc.git.exe": "", "pc.git.repos": []}), env=env)
        self.assertEqual((st["rc"], st["reasons"], st["repos"]), (1, [], 0))

    def test_author_patterns_escape(self):
        pats = G.author_patterns(["a.b*c", "x@example.com"])
        self.assertIn("^a\\.b\\*c <", pats)
        self.assertIn("<x@example\\.com>$", pats)


class GitScriptTest(CloneTestCase):
    """스크립트 진입(복제 트리, 동봉 파이썬 -X utf8 -I -B — 계약 §7.3). 정제·저장 전 갈래만(WP-11 없이도 결정적)."""

    def test_bad_pc_rc3(self):
        cp = self.clone.run_py([self.clone.path("collect", "Get-GitActivity.py"), "--pc", "PC1"],
                               flags=("-X", "utf8", "-I", "-B"), timeout=120)
        self.assertEqual(cp.returncode, 3)
        self.assertIn('"BadPcId"', cp.stderr.decode("utf-8"))
        self.assertEqual(cp.stdout, b"")

    def test_no_git_rc3_status_line(self):
        empty = self.clone.temp / "nogit"
        empty.mkdir(parents=True, exist_ok=True)
        # 복제 트리의 개인 설정으로 자동 탐색(홈 폴더)을 끈다 — 시험이 실제 사용자 폴더를 훑지 않게
        repo_dir = self.clone.temp / "some_repo_dir"                    # 저장소 목록은 있게(없으면 git 유무와 무관하게 rc 1)
        repo_dir.mkdir(parents=True, exist_ok=True)
        cfg = {"pc.autoDiscoverFolders": False, "pc.git.repos": [str(repo_dir)]}
        self.clone.path("config", "config.json").write_bytes(json.dumps(cfg, ensure_ascii=False).encode("utf-8"))
        # Windows 환경 변수는 대소문자를 가리지 않지만 os.environ 사본의 키는 대문자다 — 같은 대문자 키로 덮는다.
        # 64비트 자식의 ProgramFiles 는 ProgramW6432 에서 다시 정해지므로 그것도 덮는다.
        env = self.clone.env({"PATH": str(empty), "PROGRAMFILES": str(empty), "PROGRAMFILES(X86)": str(empty),
                              "PROGRAMW6432": str(empty), "USERPROFILE": str(empty)})
        cp = self.clone.run_py([self.clone.path("collect", "Get-GitActivity.py"), "--pc", PC, "--from", "2026-09-01",
                                "--to", "2026-09-30"], flags=("-X", "utf8", "-I", "-B"), env=env, timeout=120)
        self.assertEqual(cp.returncode, 3, cp.stderr.decode("utf-8", "replace"))
        last = cp.stderr.decode("utf-8").strip().splitlines()[-1]
        self.assertTrue(last.startswith('{"_status"'))
        self.assertIn('"R-NOGIT"', last)
        self.assertFalse(list(Path(self.clone.root).rglob("__pycache__")))

    def test_bad_date_rc3(self):
        cp = self.clone.run_py([self.clone.path("collect", "Get-GitActivity.py"), "--pc", PC, "--from", "9/1"],
                               flags=("-X", "utf8", "-I", "-B"), timeout=120)
        self.assertEqual(cp.returncode, 3)


class GitArgsTest(unittest.TestCase):
    """--help 는 수집이 아니다 — rc 0, 상태 줄 없음(인자 오류만 rc 3 + BadArguments). W1a 통합 관문(Import-MailCal.py 와 같게)."""

    def test_help_rc0_without_status_line(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = G.main(["--help"])
        self.assertEqual(rc, 0)
        self.assertIn("usage", out.getvalue())
        self.assertNotIn("_status", err.getvalue())

    def test_unknown_argument_still_rc3(self):
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            rc = G.main(["--no-such-flag"])
        self.assertEqual(rc, 3)
        self.assertIn('"BadArguments"', err.getvalue())


class GitStaticTest(unittest.TestCase):
    def test_entry_inserts_root_first_and_import_allowlist(self):
        tree = ast.parse(SCRIPT.read_bytes().decode("utf-8"))
        body = [s for s in tree.body if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))]
        first_lm27 = next(i for i, s in enumerate(body) if isinstance(s, (ast.Import, ast.ImportFrom))
                          and "lm27" in ast.dump(s))
        ins = next(i for i, s in enumerate(body) if "sys.path" in ast.unparse(s) and "insert" in ast.unparse(s))
        self.assertLess(ins, first_lm27)
        allowed = ("lm27.privacy.sanitize", "lm27.store", "lm27.paths", "lm27.config", "lm27.util", "lm27.catalog")
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom) and n.module and n.module.startswith("lm27"):
                self.assertTrue(any(n.module == a or n.module.startswith(a + ".") for a in allowed), n.module)
            if isinstance(n, ast.Import):
                for a in n.names:
                    self.assertFalse(a.name.startswith("lm27"), a.name)

    def test_no_disk_write_calls(self):
        src = SCRIPT.read_bytes().decode("utf-8")
        for bad in ("open(", "write_text(", "write_bytes(", "json.dump(", "git_commits", "git_source"):
            self.assertNotIn(bad, src)


if __name__ == "__main__":
    unittest.main()
