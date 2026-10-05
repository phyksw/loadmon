# -*- coding: utf-8 -*-
"""WP-04 관문 실행기 시험 — hook_check.py 의 훅 모드·파일 모드·저장소 모드, tools\\lint.ps1 단계 실행기,
저장소 설정 파일(.gitattributes · .gitignore · ruff.toml · .claude\\settings.json).

훅 모드는 실제 훅처럼 hook_check.py 를 자식 프로세스로 띄우고 stdin 에 UTF-8 JSON 바이트를 준다.
한글 경로가 로케일(CP949)로 읽혀 조용히 통과하던 이전 결함을 막는지 보려고 자식은 -X utf8 없이 띄운다.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from tests.core.test_lint_rules import HC, HC_PATH, ROOT, WORDS, Tree, errs

NO_WINDOW = 0x08000000 if os.name == "nt" else 0
BOM = b"\xef\xbb\xbf"


def _env(aux):
    env = dict(os.environ)
    env["LOCALAPPDATA"] = aux
    env["PYTHONUTF8"] = "0"
    env.pop("PYTHONIOENCODING", None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


class HookTree(Tree):
    """hook_check.py·lint.ps1 사본을 품은 트리(한글 경로) — 훅 모드는 자기 루트 밖 파일을 보지 않는다."""

    def __init__(self):
        super().__init__(prefix="lm27t_훅검사_")
        self.copy(HC_PATH, "tools/hook_check.py")
        self.copy(ROOT / "tools" / "lint.ps1", "tools/lint.ps1")
        self.hc = os.path.join(self.root, "tools", "hook_check.py")
        # LOCALAPPDATA 를 aux 로 바꿔 띄우므로 금지어 목록은 aux\LoadMonitor27\dev\ 에 이미 있다(Tree)

    def run_hc(self, args, stdin=b"", utf8=False):
        cmd = [sys.executable] + (["-X", "utf8"] if utf8 else []) + ["-B", self.hc] + list(args)
        return subprocess.run(cmd, input=stdin, capture_output=True, timeout=120, cwd=tempfile.gettempdir(),
                              env=_env(self.aux), creationflags=NO_WINDOW)

    def lint(self, *args):
        ps = shutil.which("powershell") or shutil.which("powershell.exe")
        if not ps:
            raise unittest.SkipTest("powershell 없음")
        cmd = [ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", os.path.join(self.root, "tools", "lint.ps1"),
               "-Python", sys.executable] + list(args)
        p = subprocess.run(cmd, capture_output=True, timeout=600, cwd=tempfile.gettempdir(), env=_env(self.aux),
                           creationflags=NO_WINDOW)
        return p.returncode, (p.stdout + p.stderr).decode("utf-8", errors="replace")


def _hook_json(path, ascii_only=False):
    obj = {"session_id": "t", "hook_event_name": "PostToolUse", "tool_name": "Write",
           "tool_input": {"file_path": path, "content": "x"}, "tool_response": {"filePath": path, "success": True}}
    return json.dumps(obj, ensure_ascii=ascii_only).encode("utf-8")


class TestHookMode(unittest.TestCase):
    def setUp(self):
        self.t = HookTree()
        self.bad = self.t.write("collect/한글수집기.ps1", "Write-Output '한글'\n")          # BOM·CRLF 없음
        self.good = self.t.write("collect/정상.ps1", BOM + "Write-Output '한글'\r\n".encode())

    def tearDown(self):
        self.t.close()

    def test_korean_path_from_stdin_bytes_is_checked(self):
        for ascii_only in (False, True):
            p = self.t.run_hc([], stdin=_hook_json(self.bad, ascii_only))
            self.assertEqual(p.returncode, 2, p.stderr.decode("utf-8", "replace"))
            self.assertIn("L-02", p.stderr.decode("utf-8", "replace"))

    def test_clean_file_and_outside_path_pass(self):
        p = self.t.run_hc([], stdin=_hook_json(self.good))
        self.assertEqual(p.returncode, 0, p.stderr.decode("utf-8", "replace"))
        outside = os.path.join(self.t.aux, "밖.ps1")
        with open(outside, "wb") as fh:
            fh.write(b"no bom\n")
        p = self.t.run_hc([], stdin=_hook_json(outside))
        self.assertEqual((p.returncode, p.stderr), (0, b""))

    def test_excluded_areas_are_ignored(self):
        for rel in (".wf/x.ps1", "data/pcs/x.ps1", "lm27/__pycache__/x.ps1"):
            p = self.t.write(rel, "no bom\n")
            self.assertEqual(self.t.run_hc([], stdin=_hook_json(p)).returncode, 0, rel)

    def test_garbage_stdin_is_ignored(self):
        for data in (b"", b"not json", b'{"tool_input": 3}', b"\xff\xfe\x00"):
            self.assertEqual(self.t.run_hc([], stdin=data).returncode, 0)

    def test_file_mode_exit_codes(self):
        self.assertEqual(self.t.run_hc([self.bad]).returncode, 2)
        self.assertEqual(self.t.run_hc([self.good]).returncode, 0)
        self.assertEqual(self.t.run_hc(["--rules", "L-99", self.good]).returncode, 2)

    def test_forbidden_word_never_printed(self):
        f = self.t.write("lm27/x.py", "A = '" + WORDS[1] + "'\n")
        p = self.t.run_hc([], stdin=_hook_json(f))
        out = (p.stdout + p.stderr).decode("utf-8", "replace").lower()
        self.assertEqual(p.returncode, 2)
        self.assertIn("l-26", out)
        self.assertNotIn(WORDS[1], out)

    def test_hook_rules_are_the_planned_file_set(self):
        self.assertEqual(set(HC.HOOK_RULES), {f"L-{n:02d}" for n in (1, 2, 3, 4, 5, 6, 7, 9, 10, 11, 16, 18, 19, 20, 26)})

    def test_single_file_under_two_seconds(self):
        body = "".join(f"def f{i}(x):\n    return x + {i}\n\n\n" for i in range(150))
        p = self.t.write("lm27/big.py", '"""큰 파일."""\n\n\n' + body)
        ctx = self.t.ctx()
        ctx.ruff_cmd()                                    # 도구 탐색은 실행마다 한 번 — 측정에서 뺀다
        t0 = time.monotonic()
        found = HC.check_file(p, ctx=ctx)
        dt = time.monotonic() - t0
        self.assertEqual(errs(found), [], found)
        self.assertLess(dt, 2.0, f"파일 단위 검사 {dt:.2f}초")


class TestForbiddenListLocation(unittest.TestCase):
    """CR-06 목록 위치 — 기본은 %LOCALAPPDATA%. 시험 복제(LM27T_CLONE) 안에서 그 목록이 없을 때만
    tree.py 가 넘긴 LM27T_FORBIDDEN_WORDS 를 읽는다(샌드박스 %LOCALAPPDATA% 때문에 fail-closed 로 막히지 않게)."""

    def setUp(self):
        self.t = Tree()
        self.empty = tempfile.mkdtemp(prefix="lm27t_aux_")

    def tearDown(self):
        self.t.close()
        shutil.rmtree(self.empty, ignore_errors=True)

    def load(self, **env):
        with mock.patch.dict(os.environ):
            for k in ("LM27T_CLONE", "LM27T_FORBIDDEN_WORDS"):
                os.environ.pop(k, None)
            os.environ.update(env)
            return HC.Ctx(self.t.root).forbidden()

    def test_override_ignored_outside_clone(self):
        words, err = self.load(LOCALAPPDATA=self.empty, LM27T_FORBIDDEN_WORDS=self.t.forbidden)
        self.assertIsNone(words)
        self.assertIn("fail-closed", err)

    def test_clone_falls_back_to_passed_location(self):
        words, err = self.load(LOCALAPPDATA=self.empty, LM27T_CLONE=self.empty, LM27T_FORBIDDEN_WORDS=self.t.forbidden)
        self.assertIsNone(err)
        self.assertEqual(words, list(WORDS))

    def test_localappdata_list_wins_in_clone(self):
        words, err = self.load(LOCALAPPDATA=self.t.aux, LM27T_CLONE=self.empty,
                               LM27T_FORBIDDEN_WORDS=os.path.join(self.empty, "없음.txt"))
        self.assertIsNone(err)
        self.assertEqual(words, list(WORDS))

    def test_clone_without_any_list_still_fails_closed(self):
        words, err = self.load(LOCALAPPDATA=self.empty, LM27T_CLONE=self.empty)
        self.assertIsNone(words)
        self.assertIn("fail-closed", err)


class TestRepoMode(unittest.TestCase):
    def setUp(self):
        self.t = HookTree()

    def tearDown(self):
        self.t.close()

    def test_repo_cli_clean_then_dirty(self):
        self.t.write("lm27/ok.py", '"""정상."""\n\nX = 1\n')
        p = self.t.run_hc(["--repo", "--root", self.t.root], utf8=True)
        out = p.stdout.decode("utf-8", "replace")
        self.assertEqual(p.returncode, 0, out)
        self.assertIn("[lint]", out)
        self.assertFalse(os.path.exists(os.path.join(self.t.root, ".ruff_cache")))
        self.t.write("collect/x.ps1", "Write-Output 1\n")
        p = self.t.run_hc(["--repo", "--root", self.t.root], utf8=True)
        self.assertEqual(p.returncode, 1)
        self.assertIn("L-02", p.stdout.decode("utf-8", "replace"))
        p = self.t.run_hc(["--repo", "L-13", "--root", self.t.root], utf8=True)
        self.assertEqual(p.returncode, 0, p.stdout.decode("utf-8", "replace"))

    def test_list_and_bad_args(self):
        p = self.t.run_hc(["--list"], utf8=True)
        lines = [ln for ln in p.stdout.decode("utf-8").splitlines() if ln.startswith("L-")]
        self.assertEqual(len(lines), 30)
        self.assertEqual(self.t.run_hc(["--bogus"]).returncode, 2)
        self.assertEqual(self.t.run_hc(["--repo", "L-77", "--root", self.t.root]).returncode, 2)

    def test_rule_crash_is_reported_not_raised(self):
        def boom():
            raise ValueError("x")

        def gone():
            raise FileNotFoundError("x")
        crash = HC._safe("L-01", "a.py", boom)
        self.assertEqual(len(crash), 1)
        self.assertFalse(crash[0].warn, "관문 도구 결함은 통과로 치지 않는다")
        self.assertTrue(HC._safe("L-01", "a.py", gone)[0].warn)

    def test_norm_rules(self):
        self.assertEqual(HC._norm_rules(["l-2,L-13", "7"], HC.ALL_RULES), ("L-02", "L-13", "L-07"))
        with self.assertRaises(ValueError):
            HC._norm_rules(["L-31"], HC.ALL_RULES)

    def test_skips_absent_targets_as_warnings(self):
        found = self.t.repo(None)
        self.assertEqual(errs(found), [], found)
        w = {f.rule for f in found if f.warn}
        self.assertTrue({"L-23", "L-24", "L-30"} <= w, w)


class TestLintPs1(unittest.TestCase):
    def setUp(self):
        self.t = HookTree()
        self.t.write("lm27/ok.py", '"""정상."""\n\nX = 1\n')

    def tearDown(self):
        self.t.close()

    def test_static_pass_and_fail(self):
        rc, out = self.t.lint()
        self.assertEqual(rc, 0, out)
        self.assertIn("[static] PASS", out)
        self.t.write("collect/x.ps1", "Write-Output 1\n")
        rc, out = self.t.lint("-Stage", "static")
        self.assertEqual(rc, 1, out)
        self.assertIn("L-02", out)
        self.assertIn("[static] FAIL", out)

    def test_failed_stage_stops_the_chain(self):
        self.t.write("collect/x.ps1", "Write-Output 1\n")
        rc, out = self.t.lint("-Stage", "unit")
        self.assertEqual(rc, 1, out)
        self.assertIn("NOT-RUN", out)
        self.assertNotIn("clone:", out)

    def test_unit_stage_runs_in_temp_clone(self):
        self.t.write("tests/__init__.py", '"""시험."""\n')
        self.t.write("tests/core/__init__.py", '"""core."""\n')
        # 복제는 WP-05 하네스(tree.py)로만 만든다(계획 §3.2) — 복제 안 %LOCALAPPDATA% 는 샌드박스여야 한다
        self.t.copy(ROOT / "tests" / "fixtures" / "tree.py", "tests/fixtures/tree.py")
        self.t.write("tests/core/test_ok.py", "import os\nimport unittest\n\n\nclass T(unittest.TestCase):\n"
                                              "    def test_ok(self):\n"
                                              "        root = os.environ['LM27T_CLONE']\n"
                                              "        self.assertTrue(os.environ['LOCALAPPDATA'].lower()"
                                              ".startswith(root.lower()))\n")
        rc, out = self.t.lint("-Stage", "unit", "-Area", "core")
        self.assertEqual(rc, 0, out)
        self.assertIn("[unit] PASS", out)
        clone = [ln.split("clone:", 1)[1].split()[0] for ln in out.splitlines() if "clone:" in ln]
        self.assertTrue(clone, out)
        self.assertNotEqual(os.path.normcase(clone[0]), os.path.normcase(self.t.root))
        self.assertFalse(os.path.exists(clone[0]), "복제 트리를 지우지 않음")
        self.t.write("tests/core/test_bad.py", "import unittest\n\n\nclass T(unittest.TestCase):\n"
                                               "    def test_bad(self):\n        self.assertTrue(False)\n")
        rc, out = self.t.lint("-Stage", "unit", "-Only", "-Area", "core")
        self.assertEqual(rc, 1, out)
        self.assertIn("[unit] FAIL", out)

    def test_unit_stage_without_harness_fails(self):
        self.t.write("tests/__init__.py", '"""시험."""\n')
        self.t.write("tests/core/__init__.py", '"""core."""\n')
        rc, out = self.t.lint("-Stage", "unit", "-Only", "-Area", "core")
        self.assertEqual(rc, 1, out)                      # 복제 하네스 없이 원본에서 돌리지 않는다
        self.assertIn("tree.py", out)
        self.assertNotIn("clone:", out)

    def test_absent_stage_tools_are_skipped(self):
        rc, out = self.t.lint("-Stage", "package", "-Only")
        self.assertEqual(rc, 0, out)
        rc, out = self.t.lint("-Stage", "nope")
        self.assertNotEqual(rc, 0, out)


class TestRepoConfigFiles(unittest.TestCase):
    """WP-04 소유 저장소 설정(.gitattributes · .gitignore · ruff.toml · .claude\\settings.json)."""

    def lines(self, rel):
        with open(os.path.join(str(ROOT), *rel.split("/")), "rb") as fh:
            raw = fh.read()
        self.assertNotIn(b"\r", raw, f"{rel} 은 LF")
        return [ln.strip() for ln in raw.decode("utf-8").splitlines()]

    def test_gitattributes_binary_safe(self):
        self.assertIn("* -text", self.lines(".gitattributes"))

    def test_gitignore(self):
        ls = self.lines(".gitignore")
        for need in ("data/", "out/", "config/config.json", ".wf/", "__pycache__/", "*.zip", "!python/python311.zip"):
            self.assertIn(need, ls)
        for gone in ("teamdata/", "config/settings.local.json"):
            self.assertNotIn(gone, ls)

    def test_ruff_toml(self):
        text = "\n".join(self.lines("ruff.toml"))
        self.assertNotIn("analyze/", text)
        self.assertIn('"tools/*.py" = ["E402"]', text)
        self.assertIn('"lm27_cli.py" = ["E402"]', text)

    def test_claude_hook_settings(self):
        with open(os.path.join(str(ROOT), ".claude", "settings.json"), "rb") as fh:
            cfg = json.loads(fh.read().decode("utf-8"))
        hooks = cfg["hooks"]["PostToolUse"]
        cmds = [h["command"] for blk in hooks if "Write" in blk["matcher"] and "Edit" in blk["matcher"]
                for h in blk["hooks"]]
        self.assertTrue(any("tools/hook_check.py" in c.replace("\\", "/") for c in cmds), cmds)

    def test_gate_files_pass_their_own_gate(self):
        t = Tree()
        try:
            ctx = HC.Ctx(str(ROOT), forbidden_path=t.forbidden)
            for rel in ("tools/hook_check.py", "tools/lint.ps1", "ruff.toml", ".gitattributes", ".gitignore",
                        ".claude/settings.json", "tests/core/test_hook_check.py", "tests/core/test_lint_rules.py"):
                found = HC.check_file(os.path.join(str(ROOT), *rel.split("/")), ctx=ctx, rules=HC.ALL_RULES)
                self.assertEqual(errs(found), [], f"{rel}: {errs(found)}")
        finally:
            t.close()


if __name__ == "__main__":
    unittest.main()
