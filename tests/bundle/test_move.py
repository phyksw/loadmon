# -*- coding: utf-8 -*-
"""WP-12 move — 이동 준비(TAB §1.11)·도착 점검(§1.12): move_ready.json(파이썬이 씀) · 마지막 내보내기 · sha 검증·격리 ·
도우미 명령줄(move.renameRetries·move.stopWaitSec) · B20 도착 점검 · Prepare-Move.ps1(UTF-8 BOM+CRLF, 디스크 쓰기 0) ·
B13(우리 프로그램 종료 후 이름 바꾸기 성공) · B14(파일을 쥔 프로세스 → 실패 + Restart Manager pid) · B15(팀 서버 동거 → 중단)."""
import os
import re
import subprocess
import sys
import time
import unittest
from pathlib import Path

from lm27.bundle import manifest as mf
from lm27.bundle import move as mv
from lm27.bundle import pcreg
from lm27.bundle import segment as seg
from lm27.util import fsx
from tests.fixtures.tree import python_home
from tests.fixtures.wp12 import builders as B
from tests.fixtures.wp12 import fake_store as fs

TREE = Path(__file__).resolve().parents[2]
HELPER = TREE / "collect" / "move" / "Prepare-Move.ps1"
PS = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "WindowsPowerShell", "v1.0",
                  "powershell.exe")
CREATE_NO_WINDOW = 0x08000000


def put(paths, ident, kind, rows, created="2026-10-05T09:00:00Z"):
    d = paths.pc_dir(ident.pc_id)
    pcreg.ensure_pc_dir(paths, ident, host="", anchor_since="2026-01-01T00:00:00Z", now="2026-09-01T00:00:00Z")
    m = mf.load_manifest(d)
    info = seg.write_segment(d, kind, ident, rows, rules_ver=B.RULES_VER, kid=B.KID, created=created, manifest=m)
    m["segments"].append(info)
    mf.save_manifest(d, m)
    return info


class PrepareMoveTest(B.BundleTestCase):
    def setUp(self):
        super().setUp()
        self.cfg = self.b.cfg()
        self.i1, self.i2 = B.ident("PC1"), B.ident("PC2")
        self.a = put(self.paths, self.i1, "mail", B.rows("mail", self.i1.pc_id, 3))
        put(self.paths, self.i2, "mail", B.rows("mail", self.i2.pc_id, 2))
        put(self.paths, self.i2, "teams", B.rows("teams", self.i2.pc_id, 2))
        self.tmp = self.b.root / "_tmp"
        self.tmp.mkdir()
        # 복제 트리처럼 도우미를 둔다(collect\move\Prepare-Move.ps1)
        dst = self.b.root / "collect" / "move" / "Prepare-Move.ps1"
        dst.parent.mkdir(parents=True)
        dst.write_bytes(HELPER.read_bytes())

    def prepare(self, **kw):
        kw.setdefault("ident", self.i1)
        kw.setdefault("launch", False)
        kw.setdefault("reader", fs.read_store_since)
        kw.setdefault("temp_dir", self.tmp)
        kw.setdefault("now", "2026-10-05T10:00:00Z")
        return mv.prepare_move(self.paths, self.cfg, **kw)

    def test_move_ready_and_helper_argv(self):
        fs.append_member(self.paths, self.i1.pc_id, "pc_session", "pc.sampler", "2026-10-05",
                         B.rows("pc_session", self.i1.pc_id, 4, start="2026-10-05T00:00:00Z"))
        r = self.prepare(wait_pid=4242)
        self.assertEqual(r.rc, 0, r.notes)
        mr = fsx.read_json(self.paths.move_ready(self.i1.pc_id))
        self.assertEqual(mr["schema"], "lm27.moveready/1")
        self.assertEqual(set(mr), {"schema", "at", "pc_id", "label_auto", "manifest_gen", "bundle_mb", "derived_mb",
                                   "sha_ok", "segments", "other_pcs_seen"})
        self.assertEqual((mr["pc_id"], mr["label_auto"], mr["sha_ok"]), (self.i1.pc_id, "PC1", True))
        files = [x[0] for x in mr["segments"]]
        self.assertIn(self.a["file"], files)
        self.assertTrue(any(f.startswith("seg/pc_session/") for f in files), "마지막 내보내기분 포함")
        self.assertEqual(mr["other_pcs_seen"], {self.i2.pc_id: 2})
        self.assertEqual(mr["manifest_gen"], mf.load_manifest(self.paths.pc_dir(self.i1.pc_id))["gen"])
        self.assertTrue(re.match(r"^lm27_move_[0-9a-f]{8}\.ps1$", os.path.basename(r.helper)))
        self.assertEqual(Path(r.helper).read_bytes(), HELPER.read_bytes(), "사본은 바이트 그대로")
        a = r.argv
        self.assertTrue(a[0].lower().endswith("powershell.exe"))
        self.assertEqual(a[1:6], ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", r.helper])
        self.assertEqual(a[a.index("-Root") + 1], str(self.paths.root))
        self.assertEqual(a[a.index("-WaitPid") + 1], "4242")
        self.assertEqual(a[a.index("-Gen") + 1], str(mr["manifest_gen"]))
        self.assertEqual((a[a.index("-RenameRetries") + 1], a[a.index("-StopWaitSec") + 1]), ("4", "15"))
        cfg = self.b.cfg(**{"move.renameRetries": 2, "move.stopWaitSec": 5})
        r2 = mv.prepare_move(self.paths, cfg, ident=self.i1, launch=False, reader=fs.read_store_since,
                             temp_dir=self.tmp)
        self.assertEqual((r2.argv[r2.argv.index("-RenameRetries") + 1], r2.argv[r2.argv.index("-StopWaitSec") + 1]),
                         ("2", "5"))

    def test_spawn_injection_and_export_failure_not_blocking(self):
        def boom(*a, **k):
            raise OSError("가짜 원장 오류")
        seen = []
        r = self.prepare(reader=boom, launch=True, spawn=lambda argv: seen.append(argv) or 777)
        self.assertEqual(r.rc, 2)
        self.assertEqual(r.pid, 777)
        self.assertEqual(seen[0], r.argv)
        self.assertEqual(r.notes[0], {"code": "final_export_failed", "error": "OSError"})
        self.assertTrue(self.paths.move_ready(self.i1.pc_id).is_file(), "이동은 막지 않는다")

    def test_sha_mismatch_quarantined(self):
        p = self.paths.pc_dir(self.i1.pc_id) / self.a["file"]
        data = bytearray(p.read_bytes())
        data[20] ^= 0x01
        p.write_bytes(bytes(data))
        r = self.prepare()
        self.assertEqual((r.rc, r.sha_ok), (2, False))
        self.assertFalse(p.exists())
        self.assertTrue((self.paths.pc_dir(self.i1.pc_id) / "quarantine" / p.name).exists())
        mr = fsx.read_json(self.paths.move_ready(self.i1.pc_id))
        self.assertFalse(mr["sha_ok"])
        self.assertNotIn(self.a["file"], [x[0] for x in mr["segments"]])

    def test_helper_missing_rc3(self):
        (self.b.root / "collect" / "move" / "Prepare-Move.ps1").unlink()
        r = self.prepare()
        self.assertEqual(r.rc, 3)
        self.assertEqual(r.notes[-1]["code"], "helper_missing")

    def test_profile_trace_warning(self):
        (self.b.root / "data" / "leftover" / "User Data").mkdir(parents=True)
        r = self.prepare()
        self.assertIn({"code": "browser_profile_trace", "n": 1}, r.notes)

    def test_b20_arrival_check(self):
        self.prepare()
        put(self.paths, self.i2, "teams", B.rows("teams", self.i2.pc_id, 1, start="2026-09-09T00:00:00Z"))
        mv.prepare_move(self.paths, self.cfg, ident=self.i2, launch=False, reader=fs.read_store_since,
                        temp_dir=self.tmp)
        self.assertEqual(mv.arrival_check(self.paths), [])
        mr2 = fsx.read_json(self.paths.move_ready(self.i2.pc_id))
        gone = [x[0] for x in mr2["segments"]][:2]
        saved = {}
        for rel in gone:
            p = self.paths.pc_dir(self.i2.pc_id).joinpath(*rel.split("/"))
            saved[p] = p.read_bytes()
            p.unlink()
        miss = mv.arrival_check(self.paths)
        self.assertEqual(sorted((m.file, m.state) for m in miss), sorted((g, "없음") for g in gone))
        self.assertTrue(all(m.label == "PC2" and m.pc_id == self.i2.pc_id for m in miss))
        self.assertEqual({m.kind for m in miss}, {g.split("/")[1] for g in gone})
        for p, data in saved.items():
            p.write_bytes(data)
        self.assertEqual(mv.arrival_check(self.paths), [], "다시 넣으면 표가 사라진다")
        p = next(iter(saved))
        p.write_bytes(next(iter(saved.values()))[:-1] + b"\x01")
        self.assertEqual([m.state for m in mv.arrival_check(self.paths, deep=True)], ["sha 다름"])


class HelperScriptStaticTest(unittest.TestCase):
    def test_encoding_bom_crlf(self):
        raw = HELPER.read_bytes()
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
        self.assertEqual(raw.count(b"\n"), raw.count(b"\r\n"))
        self.assertNotRegex(raw.decode("utf-8-sig"), r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

    def test_no_disk_writes(self):
        text = HELPER.read_bytes().decode("utf-8-sig")
        for pat in (r"(?i)\bOut-File\b", r"(?i)\bSet-Content\b", r"(?i)\bAdd-Content\b", r"(?i)\bExport-Csv\b",
                    r"(?i)WriteAll", r"(?i)StreamWriter", r"(?i)\bNew-Item\b", r"(?i)\bRemove-Item\b",
                    r"(?i)\btaskkill\b"):
            self.assertNotRegex(text, pat)

    def test_hook_check_clean(self):
        cp = subprocess.run([sys.executable, "-X", "utf8", "-B", str(TREE / "tools" / "hook_check.py"),
                             str(HELPER)], capture_output=True, timeout=120, creationflags=CREATE_NO_WINDOW)
        self.assertEqual(cp.returncode, 0, cp.stdout.decode("utf-8", "replace") + cp.stderr.decode("utf-8", "replace"))


@unittest.skipUnless(os.name == "nt" and os.path.isfile(PS), "Windows PowerShell 5.1 필요")
class HelperScriptRunTest(B.BundleTestCase):
    """실 Windows·%TEMP% 안 가짜 ROOT 에서 도우미를 돌린다(실데이터 없음)."""

    def setUp(self):
        super().setUp()
        self.root = self.b.root / "LoadMonitor27"
        (self.root / "data").mkdir(parents=True)
        (self.root / "data" / "bundle.json").write_text("{}", encoding="utf-8")
        (self.root / "lm27_cli.py").write_text("import time\ntime.sleep(60)\n", encoding="utf-8")
        self.helper = self.b.root / "lm27_move_test.ps1"
        self.helper.write_bytes(HELPER.read_bytes())

    def spawn(self, args, env=None, cwd=None):
        p = subprocess.Popen([sys.executable, "-X", "utf8", "-B", *args], cwd=cwd or str(self.b.root),
                             env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=CREATE_NO_WINDOW)

        def stop():
            if p.poll() is None:
                p.kill()
            p.communicate(timeout=10)
        self.addCleanup(stop)
        return p

    def run_helper(self, *extra):
        cp = subprocess.run([PS, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(self.helper),
                             "-Root", str(self.root), "-NoWait", "-StopWaitSec", "1", "-RenameRetries", "2", *extra],
                            capture_output=True, timeout=180, cwd=str(self.b.root), creationflags=CREATE_NO_WINDOW)
        return cp.returncode, cp.stdout.decode("utf-8", "replace") + cp.stderr.decode("utf-8", "replace")

    def test_b13_closes_our_program_then_movable(self):
        p = self.spawn([str(self.root / "lm27_cli.py"), "ui"], cwd=str(self.root))
        time.sleep(0.5)
        rc, out = self.run_helper("-WaitPid", str(p.pid))
        self.assertEqual(rc, 0, out)
        self.assertIn("[완료]", out)
        self.assertNotIn("[!]", out)
        self.assertIsNotNone(p.poll(), "ROOT 아래를 가리키는 우리 프로그램은 닫는다")
        self.assertTrue(self.root.is_dir(), "이름은 원래대로")
        self.assertEqual([x.name for x in self.b.root.iterdir() if "__mvtest_" in x.name], [])

    def test_b14_open_file_blocks_and_rm_names_holder(self):
        held = self.root / "data" / "held.txt"
        held.write_text("x", encoding="utf-8")
        env = dict(os.environ, LM27T_HOLD=str(held))
        p = self.spawn(["-c", "import os,sys,time;f=open(os.environ['LM27T_HOLD'],'rb');print('ok',flush=True);"
                              "time.sleep(60)"], env=env)
        self.assertEqual(p.stdout.readline().strip(), b"ok")
        rc, out = self.run_helper()
        self.assertEqual(rc, 1, out)
        self.assertIn("[실패]", out)
        self.assertIn(f"pid {p.pid}", out, "Restart Manager 가 파일을 쥔 프로세스를 보인다")
        self.assertIsNone(p.poll(), "ROOT 밖 프로세스는 종료하지 않는다")
        self.assertTrue(self.root.is_dir(), "폴더 이름 원상")

    def test_b15_team_server_stops_without_killing(self):
        p = self.spawn([str(self.root / "lm27_cli.py"), "team-server"], cwd=str(self.b.root))
        time.sleep(0.5)
        rc, out = self.run_helper()
        self.assertEqual(rc, 2, out)
        self.assertIn("팀 서버", out)
        self.assertIsNone(p.poll(), "[그래도 진행] 전에는 아무것도 종료하지 않는다")
        self.assertTrue(self.root.is_dir())

    def test_x332_bat_path_runs_move_prepare_first(self):
        """-WaitPid 없이(bat 경로) 시작하면 ROOT 의 파이썬으로 `lm27_cli.py move-prepare` 를 먼저 부르고, 그것이 새 도우미를
        띄웠으면(rc 0·2) 이 창은 이름 바꾸기 없이 끝난다."""
        src = python_home()            # 복제 트리에는 python\ 이 없다 — 하네스가 원본 동봉 파이썬을 찾는다(W1a 통합)
        dst = self.root / "python"
        dst.mkdir()
        for n in ("python.exe", "python311.dll", "python311.zip", "python311._pth", "python3.dll", "vcruntime140.dll",
                  "vcruntime140_1.dll"):
            if (src / n).is_file():
                (dst / n).write_bytes((src / n).read_bytes())
        mark = self.b.root / "called.txt"
        (self.root / "lm27_cli.py").write_text(
            "import os, sys\nwith open(os.environ['LM27T_MARK'], 'w', encoding='utf-8') as f:\n"
            "    f.write(' '.join(sys.argv[1:]))\nsys.exit(int(os.environ.get('LM27T_RC', '0')))\n", encoding="utf-8")
        env = dict(os.environ, LM27T_MARK=str(mark), LM27T_RC="0")
        cp = subprocess.run([PS, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(self.helper),
                             "-Root", str(self.root), "-NoWait", "-RenameRetries", "1"], capture_output=True,
                            timeout=180, cwd=str(self.b.root), env=env, creationflags=CREATE_NO_WINDOW)
        out = cp.stdout.decode("utf-8", "replace")
        self.assertEqual(cp.returncode, 0, out)
        self.assertEqual(mark.read_text(encoding="utf-8"), "move-prepare")
        self.assertNotIn("[완료]", out, "이름 바꾸기 시험은 새 도우미가 한다")
        mark.unlink()
        env["LM27T_RC"] = "3"                                   # 도우미를 띄우지 못함 → 이 창에서 시험을 이어 간다
        cp = subprocess.run([PS, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(self.helper),
                             "-Root", str(self.root), "-NoWait", "-RenameRetries", "1"], capture_output=True,
                            timeout=180, cwd=str(self.b.root), env=env, creationflags=CREATE_NO_WINDOW)
        out = cp.stdout.decode("utf-8", "replace")
        self.assertTrue(mark.is_file())
        self.assertEqual(cp.returncode, 0, out)
        self.assertIn("[완료]", out)

    def test_bad_root(self):
        rc, _out = self.run_helper_root(str(self.b.root / "nope"))
        self.assertEqual(rc, 3)

    def run_helper_root(self, root):
        cp = subprocess.run([PS, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(self.helper),
                             "-Root", root, "-NoWait"], capture_output=True, timeout=60, cwd=str(self.b.root),
                            creationflags=CREATE_NO_WINDOW)
        return cp.returncode, cp.stdout.decode("utf-8", "replace")


if __name__ == "__main__":
    unittest.main()
