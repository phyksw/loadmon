# -*- coding: utf-8 -*-
"""WP-13 설치·생존·제거 시험 — ``lm27.agent.install``(계약 §1.3 · §2.4 · §3.9 · §7.1 · X-026~X-029 · X-303 · X-305 · O-16,
TAB §1.6.1~§1.6.6 · TAB-B12 · B17 · B21 · CP-9 · CP-13 · P-T34).

작업 스케줄러·뮤텍스·프로세스는 ``FakeOps``(실등록 0). 원본(ROOT)은 %TEMP% 복제 트리(+ 동봉 파이썬 복사), LAD 는 시험마다 새
샌드박스다. bin 사본은 실제로 복사해 그 사본 파이썬으로 import 해 본다(프로그램 폴더 없이 — X-305).
"""
import ast
import json
import os
import shutil
import subprocess
import time
import unittest
from datetime import timedelta
from pathlib import Path

from lm27.agent import install as I
from lm27.bundle.ids import PcIdentity
from lm27.config import load_config
from lm27.paths import Paths
from lm27.privacy import context as C
from lm27.util import fsx
from lm27.util.proc import ChildResult
from tests.fixtures.tree import CloneTestCase, guard_write
from tests.fixtures.wp13 import helpers as H

PC = "pc_0a1b2c3d4e5f6a7b"
# 계약 §1.3 사본 목록(실행 모듈) — install.py 는 프로그램 폴더 전용이라 사본에 넣지 않는다(모듈 머리말)
CONTRACT_FILES = {"lm27/__init__.py", "lm27/paths.py", "lm27/catalog.py", "lm27/agent/__init__.py", "lm27/agent/main.py",
                  "lm27/agent/sampler.py", "lm27/agent/harvest.py", "lm27/agent/exemeta.py",
                  "lm27/normalize/__init__.py", "lm27/bundle/__init__.py", "lm27/bundle/ids.py", "lm27_pipe.py",
                  "agent_main.py", "ps/agent.ps1", "ps/harvest.ps1", "ps/Get-EventActivity.ps1", "ps/Get-FileActivity.ps1",
                  "ps/Get-OfficeMru.ps1", "ps/Get-RecentFiles.ps1", "ps/Get-TeamsWindow.ps1",
                  "py311/python.exe", "py311/pythonw.exe", "py311/python311._pth",
                  "lm27/privacy/rules.lock.json", "lm27/privacy/corpus/regress_v1.jsonl", "lm27/privacy/schemas_v1.json",
                  "lm27/store/writer.py", "lm27/store/reader.py", "lm27/store/cursor.py", "lm27/util/fsx.py"}
# 사본 모듈의 '사본 밖' 지연 import 허용(계약 X-304 — 프로그램 폴더 모드 함수 안에서만, WP-11 보고 · 계약 §1.3 문구 정리 CR)
LAZY_OUTSIDE_OK = {("lm27/privacy/context.py", "lm27.hier.registry"), ("lm27/privacy/context.py", "lm27.config")}


def ident(install_id=H.IID, pc_id=PC) -> PcIdentity:
    return PcIdentity(pc_id=pc_id, id_source="machineguid", install_id=install_id, agent_ver="0.1.0", kind_guess="desktop",
                      tz={"utc_offset_min": 540, "windows_tz": ""})


class _Root(CloneTestCase):
    """복제 트리 하나(+ 동봉 파이썬 복사)를 원본으로, 시험마다 새 LAD."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        shutil.copytree(cls.clone.py_home, cls.clone.path("python"),
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "Lib", "Scripts"))
        cls.cfg = load_config(registry_path=cls.clone.path("config", "settings_registry.json"),
                              config_path=cls.clone.path("no_config.json"))

    def setUp(self):
        self.sb = H.Sandbox()
        self.addCleanup(self.sb.cleanup)
        self.paths = Paths(self.clone.root, lad=self.sb.lad)
        self.sb.paths = self.paths                                        # FakeOps·도우미가 같은 LAD 를 쓰게

    def ensure(self, ops, **kw):
        kw.setdefault("selftest", lambda: 0)
        kw.setdefault("os_names", H.OS_NAMES)
        kw.setdefault("cfg", self.cfg)
        return I.ensure_agent(ops.ident, paths=self.paths, ops=ops, **kw)


class BinCopyTest(_Root):
    def test_contract_list_and_build(self):
        files, missing = I.bin_files(self.paths)
        self.assertEqual(missing, [])
        rels = {r for r, _p in files}
        self.assertTrue(CONTRACT_FILES <= rels, sorted(CONTRACT_FILES - rels))
        self.assertNotIn("lm27/agent/install.py", rels)
        if self.clone.path("lm27", "normalize", "cues.py").is_file():
            self.assertIn("lm27/normalize/cues.py", rels)               # 정제 훅(X-305)
        self.assertFalse(any("__pycache__" in r or r.startswith(("lm27/config", "lm27/hier", "lm27/team", "lm27/time",
                                                                  "lm27/collect", "lm27/bridge")) for r in rels))
        h = I._hashed(files)
        v1 = I.build_ver(h)
        self.assertRegex(v1, r"^0\.1\.0-[0-9a-f]{8}$")
        self.assertEqual(v1, I.build_ver(I._hashed(files)))              # 같은 내용 = 같은 판
        h2 = [(r, p, ("0" * 64 if r == "lm27/catalog.py" else s)) for r, p, s in h]
        self.assertNotEqual(v1, I.build_ver(h2))

    def test_copy_verify_and_isolated_import(self):
        """TAB-B12 · X-305 — 사본이 프로그램 폴더 없이 import 된다(사본 파이썬 -I, 사본 밖 모듈 0)."""
        files, _m = I.bin_files(self.paths)
        h = I._hashed(files)
        ver = I.build_ver(h)
        bdir = self.paths.agent_bin(ver)
        self.assertEqual(len(I.install_bin(self.paths, h, ver)), len(h))
        self.assertEqual(I.bin_diff(bdir, h), [])
        (bdir / "lm27" / "privacy" / "rules.py").write_bytes(b"# tampered\n")
        self.assertEqual(I.bin_diff(bdir, h), ["lm27/privacy/rules.py"])
        I.install_bin(self.paths, h, ver, only={"lm27/privacy/rules.py"})
        self.assertEqual(I.bin_diff(bdir, h), [])
        code = ("import sys, os, json\n"
                f"b = {str(bdir)!r}\n"
                "sys.path.insert(0, b)\n"
                "import importlib.util\n"
                "mods = ['lm27.privacy', 'lm27.privacy.sanitize', 'lm27.bundle.ids', 'lm27.store', 'lm27.catalog',\n"
                "        'lm27.agent.main', 'lm27.agent.sampler', 'lm27.agent.harvest', 'lm27.agent.exemeta', 'lm27.normalize']\n"
                "if importlib.util.find_spec('lm27.normalize.cues') is not None: mods.append('lm27.normalize.cues')\n"
                "for m in mods: __import__(m)\n"
                "from lm27.agent.main import bin_paths\n"
                "p = bin_paths()\n"
                "out = [m for m, mod in sys.modules.items() if m.startswith('lm27') and getattr(mod, '__file__', None)\n"
                "       and not os.path.abspath(mod.__file__).lower().startswith(b.lower())]\n"
                "print(json.dumps({'outside': out, 'mode': p.mode(), 'agent': str(p.agent_dir()), 'mods': len(mods),\n"
                "                  'cues': 'lm27.normalize.cues' in sys.modules}))\n")
        cp = subprocess.run([str(bdir / "py311" / "python.exe"), "-X", "utf8", "-I", "-B", "-c", code], capture_output=True,
                            timeout=120, cwd=str(self.sb.dir), creationflags=H.CREATE_NO_WINDOW)
        self.assertEqual(cp.returncode, 0, cp.stderr.decode("utf-8", "replace"))
        r = json.loads(cp.stdout.decode("utf-8").strip().splitlines()[-1])
        self.assertEqual(r["outside"], [])
        self.assertEqual((r["mode"], os.path.normcase(r["agent"])), ("agent", os.path.normcase(str(self.paths.agent_dir()))))
        self.assertEqual(r["cues"], self.clone.path("lm27", "normalize", "cues.py").is_file())
        self.assertFalse(any(Path(dp).name == "__pycache__" for dp, _d, _f in os.walk(bdir)))   # -B

    def test_copy_imports_stay_inside(self):
        """사본의 모든 .py 의 import(최상위·지연)가 표준 라이브러리 또는 사본 안 모듈(계약 §1.3). 허용: X-304 지연 import 2개."""
        files, _m = I.bin_files(self.paths)
        rels = {r for r, _p in files}
        mods = {r[:-3].replace("/", ".").removesuffix(".__init__") for r in rels if r.startswith("lm27/") and r.endswith(".py")}
        bad, seen_ok = [], set()
        for rel, p in files:
            if not rel.endswith(".py") or rel.startswith("py311/"):
                continue
            tree = ast.parse(p.read_text(encoding="utf-8"))
            pkg = rel[:-3].replace("/", ".")
            pkg = pkg.removesuffix(".__init__") if rel.endswith("__init__.py") else pkg.rpartition(".")[0]
            for n in ast.walk(tree):
                names = []
                if isinstance(n, ast.Import):
                    names = [a.name for a in n.names]
                elif isinstance(n, ast.ImportFrom):
                    if n.level:
                        base = pkg.split(".")
                        base = base[:len(base) - (n.level - 1)] if n.level > 1 else base
                        names = [".".join(base + ([n.module] if n.module else []))]
                    else:
                        names = [n.module or ""]
                for nm in names:                                       # 모듈 자체가 사본에 있어야 한다(속성 import 는 그 모듈 안)
                    if not nm.startswith("lm27") or nm in mods or any(m.startswith(nm + ".") for m in mods):
                        continue
                    if (rel, nm) not in LAZY_OUTSIDE_OK:
                        bad.append((rel, nm))
                    seen_ok.add((rel, nm))
        self.assertEqual(sorted(set(bad)), [])
        self.assertTrue(seen_ok <= LAZY_OUTSIDE_OK)
        self.assertIn(("lm27/privacy/context.py", "lm27.config"), seen_ok)     # 검사가 실제로 '사본 밖'을 알아본다

    def test_entry_and_action(self):
        e = I.agent_entry(self.paths, "0.1.0-abcdef12", "py", H.IID)
        agent = os.path.normcase(str(self.paths.agent_dir()))
        self.assertEqual(os.path.normcase(e["workdir"]), agent)            # L-15 — 작업 폴더 = agent\(ROOT 아님)
        self.assertTrue(os.path.normcase(e["command"]).startswith(agent))
        self.assertTrue(e["command"].lower().endswith("py311\\pythonw.exe"))
        self.assertIn(f"--install-id {H.IID}", e["arguments"])
        self.assertNotIn(os.path.normcase(str(self.clone.root)), os.path.normcase(json.dumps(e)))
        ps = I.agent_entry(self.paths, "0.1.0-abcdef12", "ps", H.IID)
        self.assertTrue(ps["command"].lower().endswith("powershell.exe"))
        self.assertIn(f"-InstallId {H.IID}", ps["arguments"])
        task = {"command": e["command"].upper(), "arguments": e["arguments"].replace('"', ""), "workdir": e["workdir"] + "\\"}
        self.assertTrue(I.same_action(task, e, H.IID))
        self.assertFalse(I.same_action(dict(task, workdir=str(self.clone.root)), e, H.IID))
        self.assertFalse(I.same_action(task, e, H.IID2))
        self.assertFalse(I.same_action(None, e, H.IID))


class EnsureTest(_Root):
    def test_first_install_b21(self):
        """TAB-B21 — 설치 전용: 몇 초 안, 번들에는 아무것도(세그먼트) 쓰지 않음, 작업 등록됨, 생존."""
        ops = H.FakeOps(self.sb, ident())
        t0 = time.monotonic()
        res = self.ensure(ops)
        self.assertLess(time.monotonic() - t0, 5.0)
        self.assertEqual(res["rc"], 0, res)
        self.assertEqual(set(res["changed"]), {"bin", "config", "impl", "task", "started"})
        self.assertTrue(res["health"]["healthy"], res["health"])
        aj = H.read_json(self.paths.agent_json())
        self.assertEqual(set(aj), {"schema", "install_id", "pc_id", "agent_ver", "installed_at", "impl", "impl_reasons",
                                   "task_name", "mutex", "bin", "keep_bins", "rules_hash", "subkeys_kid", "prior_install_ids"})
        self.assertEqual((aj["schema"], aj["install_id"], aj["pc_id"], aj["impl"], aj["task_name"], aj["mutex"]),
                         ("lm27.agent/1", H.IID, PC, "py", "LM27-" + H.IID, "Local\\LM27-" + H.IID + "-agent"))
        self.assertEqual(aj["keep_bins"], [aj["agent_ver"]])
        self.assertNotIn("root", aj)                                     # X-026 — root 필드 없음
        self.assertTrue(self.paths.agent_bin(aj["agent_ver"]).joinpath("agent_main.py").is_file())
        sub = H.read_json(self.paths.agent_subkeys())
        self.assertEqual(sub["kid"], aj["subkeys_kid"])
        self.assertEqual(set(sub["purposes"]), {"person", "msg", "thread", "chat", "doc", "path", "dir"})
        self.assertEqual([c[0] for c in ops.calls].count("register"), 1)
        self.assertEqual([c[0] for c in ops.calls].count("run_task"), 1)
        self.assertFalse(self.paths.pcs().exists())                       # 번들에 세그먼트 0(pc.json 은 cli 가 따로)

    def test_agent_config_and_context_cache_fields_x303(self):
        ops = H.FakeOps(self.sb, ident())
        self.ensure(ops)
        ac = H.read_json(self.paths.agent_config())
        want = set(self.cfg.agent_subset()) | {"schema", "config_hash"}
        self.assertEqual(set(ac), want)
        self.assertEqual(ac["schema"], "lm27.agentcfg/1")
        for k in ("agent.sampleIntervalSec", "pc.watchExtensions", "teams.uia.intervalSec", "teams.timeRegex",
                  "time.tzOffsetMin", "collect.lookbackDays", "privacy.pipe.waitSec", "privacy.audit.retentionMonths"):
            self.assertIn(k, ac)
        cc = C.read_context_cache(self.paths.agent_dir())
        self.assertEqual(ac["config_hash"], cc["hash"])                   # 해시 = 에이전트 config_hash
        for k in ("sanitize", "self_names", "window", "path_exclude", "work_window", "final_words"):
            self.assertIn(k, cc)
        self.assertNotIn("key", cc["sanitize"])

    def test_second_call_is_noop_rc4(self):
        ops = H.FakeOps(self.sb, ident())
        self.ensure(ops)
        n = len(ops.calls)
        res = self.ensure(ops)
        self.assertEqual(res["rc"], 4, res)
        self.assertEqual([c for c in ops.calls[n:] if c[0] in ("register", "run_task", "selftest")], [])

    def test_stale_heartbeat_restarts_b17(self):
        ops = H.FakeOps(self.sb, ident())
        self.ensure(ops)
        ops.alive = False
        ops.heartbeat(age_s=20 * 60)
        self.assertFalse(I.agent_health(ops.ident, paths=self.paths, cfg=self.cfg, ops=ops)["hb_fresh"])
        res = self.ensure(ops)
        self.assertEqual(res["rc"], 0, res)
        self.assertIn("started", res["changed"])
        self.assertTrue(res["health"]["hb_fresh"])

    def test_zombie_restarts_cp13(self):
        ops = H.FakeOps(self.sb, ident())
        self.ensure(ops)
        old = time.time() - 3 * 3600
        from lm27.store import store_files
        for _rel, f, _d in store_files(self.paths, PC, "pc_session", "pc.sampler"):
            os.utime(f, (old, old))
        ops.heartbeat(started_age_s=2 * 3600)
        h = I.agent_health(ops.ident, paths=self.paths, cfg=self.cfg, ops=ops)
        self.assertEqual((h["hb_fresh"], h["store_fresh"], h["healthy"]), (True, False, False))
        self.assertIn("R-SAMPLER-ZOMBIE", h["reasons"])
        res = self.ensure(ops)
        self.assertEqual(res["rc"], 0, res)
        self.assertIn("started", res["changed"])
        self.assertTrue(res["health"]["store_fresh"])

    def test_both_impls_fail_cp9(self):
        ops = H.FakeOps(self.sb, ident(), selftest_ok=())
        res = self.ensure(ops)
        self.assertEqual((res["rc"], res["impl"]), (3, "none"))
        self.assertEqual(res["reasons"], ["R-APPLOCKER", "R-CLM"])
        self.assertEqual([c for c in ops.calls if c[0] == "register"], [])
        self.assertEqual([c[1] for c in ops.calls if c[0] == "selftest"], ["py", "ps"])     # X-029 순서 py → ps
        h = I.agent_health(ops.ident, paths=self.paths, cfg=self.cfg, ops=ops)
        self.assertFalse(h["healthy"])
        self.assertEqual(h["reasons"], ["R-APPLOCKER", "R-CLM"])

    def test_ps_fallback_and_forced_ps(self):
        ops = H.FakeOps(self.sb, ident(), selftest_ok=("ps",))
        res = self.ensure(ops)
        self.assertEqual((res["rc"], res["impl"]), (0, "ps"))
        task = ops.tasks["LM27-" + H.IID]
        self.assertTrue(task["command"].lower().endswith("powershell.exe"))
        self.assertIn("agent.ps1", task["arguments"])
        sb2 = H.Sandbox()
        self.addCleanup(sb2.cleanup)
        self.paths = self.sb.paths = Paths(self.clone.root, lad=sb2.lad)
        ops2 = H.FakeOps(self.sb, ident(), selftest_ok=("py", "ps"))
        res2 = self.ensure(ops2, cfg=self.cfg.derive({"agent.impl": "ps"}))
        self.assertEqual(res2["impl"], "ps")
        self.assertEqual([c[1] for c in ops2.calls if c[0] == "selftest"], ["ps"])

    def test_selftest_failure_refuses_install(self):
        ops = H.FakeOps(self.sb, ident())
        res = self.ensure(ops, selftest=lambda: 1)
        self.assertEqual((res["rc"], res["notes"]), (1, ["selftest_failed"]))
        self.assertFalse(self.paths.agent_bin_root().exists())
        self.assertEqual(ops.calls, [])

    def test_register_failure_rc2(self):
        ops = H.FakeOps(self.sb, ident(), register_rc=1)
        res = self.ensure(ops)
        self.assertEqual(res["rc"], 2)
        self.assertIn("register_failed", res["notes"])

    def test_tampered_bin_rules_recopied_p_t34(self):
        """P-T34 — 사본 rules.py 가 바뀌면 다음 [수집](ensure)이 사본을 바로잡고 에이전트를 다시 띄운다."""
        ops = H.FakeOps(self.sb, ident())
        self.ensure(ops)
        ver = H.read_json(self.paths.agent_json())["agent_ver"]
        rp = self.paths.agent_bin(ver) / "lm27" / "privacy" / "rules.py"
        good = rp.read_bytes()
        rp.write_bytes(good + b"\n# x\n")
        ops.heartbeat(last_error="R-RULESMISMATCH")
        res = self.ensure(ops)
        self.assertEqual(rp.read_bytes(), good)
        self.assertEqual(res["rc"], 0)
        self.assertIn("bin", res["changed"])
        self.assertIn("started", res["changed"])

    def test_new_build_keeps_two_bins(self):
        ops = H.FakeOps(self.sb, ident())
        self.ensure(ops)
        src = self.clone.path("lm27", "agent", "exemeta.py")
        orig = src.read_bytes()
        self.addCleanup(src.write_bytes, orig)
        vers = [H.read_json(self.paths.agent_json())["agent_ver"]]
        for i in range(2):
            src.write_bytes(orig + f"\n# build {i}\n".encode())
            res = self.ensure(ops)
            self.assertEqual(res["rc"], 0, res)
            vers.append(res["agent_ver"])
        aj = H.read_json(self.paths.agent_json())
        self.assertEqual(aj["keep_bins"], [vers[2], vers[1]])
        self.assertEqual(sorted(d.name for d in self.paths.agent_bin_root().iterdir()), sorted(vers[1:]))
        self.assertEqual(ops.tasks["LM27-" + H.IID]["command"], I.agent_entry(self.paths, vers[2], "py", H.IID)["command"])

    def test_prior_install_ids(self):
        guard_write(self.paths.agent_json())
        self.paths.agent_json().parent.mkdir(parents=True, exist_ok=True)
        fsx.atomic_write(self.paths.agent_json(), json.dumps({"install_id": H.IID2, "pc_id": PC}).encode())
        ops = H.FakeOps(self.sb, ident())
        self.ensure(ops)
        aj = H.read_json(self.paths.agent_json())
        self.assertEqual((aj["install_id"], aj["prior_install_ids"]), (H.IID, [H.IID2]))


class HarvestRequestTest(_Root):
    def test_timeout_without_agent(self):
        ops = H.FakeOps(self.sb, ident())
        res = I.request_harvest_now(ops.ident, 3, paths=self.paths, ops=ops)
        self.assertEqual((res["rc"], res["done"]), (2, False))
        self.assertTrue(self.paths.harvest_now_flag().is_file())

    def test_done_after_request(self):
        ops = H.FakeOps(self.sb, ident())
        orig = ops.sleep

        def sleep(s):
            orig(s)
            st = (ops.t - timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
            self.sb.write_json(self.paths.harvest_done(), {"schema": "lm27.harvest_done/1", "install_id": H.IID,
                                                            "started_at": st, "finished_at": st, "rc": 0, "streams": {}})
        ops.sleep = sleep
        self.sb.write_json(self.paths.harvest_done(), {"install_id": H.IID, "started_at": "2026-01-01T00:00:00Z", "rc": 0})
        res = I.request_harvest_now(ops.ident, 30, paths=self.paths, ops=ops)
        self.assertEqual((res["rc"], res["done"]), (0, True))


class UninstallTest(_Root):
    def install(self):
        ops = H.FakeOps(self.sb, ident())
        self.ensure(ops)
        from lm27.privacy.audit import AuditSink
        a = AuditSink.open(None, PC, "agent", "pc.sampler", agent_dir=self.paths.agent_dir())
        a.add("err", "x")
        a.flush()
        return ops

    def test_uninstall_keeps_store(self):
        ops = self.install()
        res = I.uninstall(ops.ident, False, paths=self.paths, ops=ops)
        self.assertEqual((res["rc"], res["task_removed"], res["stopped"]), (0, True, True))
        self.assertEqual(ops.tasks, {})
        self.assertFalse(self.paths.agent_subkeys().exists())             # P §9.4 — 하위 키는 제거 때 지운다
        self.assertFalse(self.paths.context_cache().exists())
        self.assertFalse(any(self.paths.agent_bin_root().iterdir()) if self.paths.agent_bin_root().exists() else False)
        self.assertTrue(self.paths.agent_json().is_file())                # install_id 유지(재설치)
        from lm27.store import store_files
        self.assertTrue(store_files(self.paths, PC, "pc_session", "pc.sampler"))

    def test_task_remove_failure_reported(self):
        ops = self.install()
        ops.remove = lambda install_id: 1                                   # 작업 삭제 실패(권한 등) — 성공으로 덮지 않는다
        res = I.uninstall(ops.ident, False, paths=self.paths, ops=ops)
        self.assertEqual((res["rc"], res["task_removed"]), (2, False))
        self.assertIn("task_remove_failed", res["notes"])

    def test_purge(self):
        ops = self.install()
        res = I.uninstall(ops.ident, True, paths=self.paths, ops=ops)
        self.assertEqual(res["rc"], 0, res)
        self.assertGreater(res["purged"], 0)
        from lm27.store import store_files
        self.assertEqual(store_files(self.paths, PC, "pc_session", "pc.sampler"), [])
        left = sorted(p.relative_to(self.paths.agent_dir()).as_posix() for p in self.paths.agent_dir().rglob("*"))
        self.assertEqual(left, [], left)


class StopAndOpsTest(_Root):
    def test_stop_kills_only_own_process(self):
        ops = H.FakeOps(self.sb, ident(), stubborn=True)
        ops.alive = True
        ops.heartbeat()
        self.assertTrue(I.stop_agent(self.paths, H.IID, ops, wait_s=2))
        self.assertEqual(ops.killed, [424242])
        self.assertFalse(self.paths.stop_flag().exists())
        ops2 = H.FakeOps(self.sb, ident(), stubborn=True)
        ops2.alive = True
        ops2.image_path = lambda pid: r"C:\Windows\System32\notepad.exe"
        self.assertFalse(I.stop_agent(self.paths, H.IID, ops2, wait_s=1))
        self.assertEqual(ops2.killed, [])

    def test_health_when_nothing_installed(self):
        ops = H.FakeOps(self.sb, ident())
        h = I.agent_health(ops.ident, paths=self.paths, cfg=self.cfg, ops=ops)
        self.assertEqual({k: h[k] for k in ("registered", "action_ok", "hb_fresh", "store_fresh", "healthy")},
                         dict.fromkeys(("registered", "action_ok", "hb_fresh", "store_fresh", "healthy"), False))

    def test_register_task_reads_agent_json(self):
        ops = H.FakeOps(self.sb, ident())
        self.assertEqual(I.register_task(ops.ident, paths=self.paths, ops=ops), 1)          # agent.json 없음
        self.ensure(ops)
        self.assertEqual(I.register_task(ops.ident, paths=self.paths, ops=ops), 0)

    def test_systemops_query_parses_task_xml(self):
        so = I.SystemOps(self.paths)
        xml = ('<?xml version="1.0" encoding="UTF-16"?>\r\n<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/'
               '2004/02/mit/task"><Actions Context="Author"><Exec><Command>C:\\A\\py311\\pythonw.exe</Command>'
               '<Arguments>-X utf8 "C:\\A\\agent_main.py" --install-id x</Arguments><WorkingDirectory>C:\\A</WorkingDirectory>'
               '</Exec></Actions></Task>\r\n')
        so.run = lambda argv, t, cwd=None: ChildResult(0, xml.encode("ascii"), b"", False, 0.1, 1)
        self.assertEqual(so.query_task("LM27T-x"), {"command": "C:\\A\\py311\\pythonw.exe",
                                                     "arguments": '-X utf8 "C:\\A\\agent_main.py" --install-id x',
                                                     "workdir": "C:\\A"})
        so.run = lambda argv, t, cwd=None: ChildResult(1, b"", b"err", False, 0.1, 1)
        self.assertIsNone(so.query_task("LM27T-x"))

    def test_systemops_real_query_of_missing_task(self):
        """읽기 전용 실조회 — 없는 시험 이름(LM27T-<무작위>)은 None."""
        self.assertIsNone(I.SystemOps(self.paths).query_task("LM27T-" + os.urandom(16).hex()))

    def test_systemops_register_argv(self):
        so = I.SystemOps(self.paths)
        seen = []
        so.run = lambda argv, t, cwd=None: seen.append(argv) or ChildResult(0, b"", b"", False, 0.1, 1)
        self.assertEqual(so.register(H.IID, "0.1.0-abcdef12", "py", no_start=True), 0)
        self.assertEqual(so.remove(H.IID), 0)
        a, b = seen
        self.assertTrue(a[a.index("-File") + 1].lower().endswith("register-agent.ps1"))
        self.assertEqual(a[a.index("-InstallId") + 1:], [H.IID, "-AgentVer", "0.1.0-abcdef12", "-Impl", "py", "-NoStart"])
        self.assertEqual(b[-3:], ["-InstallId", H.IID, "-Remove"])


if __name__ == "__main__":
    unittest.main()
