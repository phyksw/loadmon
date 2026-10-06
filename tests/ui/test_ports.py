# -*- coding: utf-8 -*-
"""RPT-37 포트 대체(19280 → +1…+n, ui_server.json) · 전부 실패 rc 3 + 진단 문구 · RPT-38 단일 인스턴스 · ui --check(cli 어댑터).
127.0.0.1 에만 바인드한다. 서버는 끝에 종료·스레드 합류, 잡아 둔 소켓은 닫는다."""
import contextlib
import io
import os
import sys
import threading
import unittest

from lm27.ui import server as S
from lm27.util import fsx, proc
from tests.fixtures.wp35.harness import REPO, FakeDeps, Sandbox, TPaths, fake_spawn, free_ports, hold_ports


class _Bg:
    """serve() 를 배경 스레드로(ready 콜백으로 앱을 받는다). stop() = 종료 요청 + 합류."""

    def __init__(self, sb, cfg, port=None, deps=None):
        self.box, self.ev = {}, threading.Event()
        self.deps = deps or FakeDeps(sb.paths)

        def ready(app, httpd):
            self.box["app"] = app
            self.ev.set()

        def run():
            self.box["rc"] = S.serve(cfg, port, True, paths=sb.paths, deps=self.deps, spawn=fake_spawn({}), ready=ready)
            self.ev.set()
        self.t = threading.Thread(target=run, name="wp35-serve-bg", daemon=True)
        with contextlib.redirect_stdout(io.StringIO()):
            self.t.start()
            self.ev.wait(15)

    @property
    def app(self):
        return self.box.get("app")

    def stop(self):
        a = self.box.get("app")
        if a is not None and a.shutdown_cb is not None:
            a.shutdown_cb()
        self.t.join(15)


class PortTest(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()
        self.addCleanup(self.sb.cleanup)
        self.socks = []
        self.addCleanup(lambda: [s.close() for s in self.socks])

    def _cfg(self, base, n):
        return self.sb.cfg(**{"ui.port": base, "ui.portFallbackCount": n})

    def test_candidates_skip_avoid(self):
        c = self.sb.cfg(**{"ui.port": 19280, "ui.portFallbackCount": 9})
        self.assertEqual(S.candidates(c), list(range(19280, 19290)))
        c2 = self.sb.cfg(**{"ui.port": 9305, "ui.portFallbackCount": 9})
        self.assertNotIn(9310, S.candidates(c2)[1:])                     # 팀 서버 포트는 대체 후보에서 뺀다
        self.assertEqual(S.candidates(c2)[0], 9305)

    def test_rpt37_fallback_next_port_and_server_json(self):
        p = free_ports(4)
        self.socks += hold_ports(p, 1)
        bg = _Bg(self.sb, self._cfg(p, 3))
        self.addCleanup(bg.stop)
        self.assertIsNotNone(bg.app, "서버가 뜨지 않음")
        self.assertEqual(bg.app.port, p + 1)
        info = fsx.read_json(self.sb.paths.ui_server_json(), None)
        self.assertEqual(info["port"], p + 1)
        self.assertEqual(info["pid"], os.getpid())
        self.assertEqual(info["instance_id"], bg.app.instance_id)
        self.assertEqual(info["root_id"], S.root_id_of(self.sb.paths))
        self.assertEqual(set(info), {"pid", "port", "started_at", "instance_id", "root_id"})
        self.assertEqual(bg.deps.opened, [f"http://127.0.0.1:{p + 1}/"])
        bg.stop()
        self.assertEqual(bg.box.get("rc"), 0)
        self.assertFalse(os.path.exists(self.sb.paths.ui_server_json()))   # 자기 기록은 끝날 때 지운다

    def test_rpt37_all_ports_fail_rc3_with_diag(self):
        p = free_ports(3)
        self.socks += hold_ports(p, 3)
        deps = FakeDeps(self.sb.paths)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = S.serve(self._cfg(p, 2), None, True, paths=self.sb.paths, deps=deps, spawn=fake_spawn({}))
        self.assertEqual(rc, 3)
        self.assertEqual(deps.diags[0][0], p)
        self.assertIn("포트", out.getvalue())
        self.assertIn("다른 프로그램", out.getvalue())
        txt = fsx.read_bytes(self.sb.paths.ui_start_error()).decode("utf-8")
        self.assertIn("화면 서버를 열 포트를 찾지 못했습니다", txt)
        self.assertEqual(deps.opened, [])
        self.assertFalse(os.path.exists(self.sb.paths.ui_server_json()))

    def test_rpt38_same_root_second_start_opens_browser_only(self):
        p = free_ports(3)
        a = _Bg(self.sb, self._cfg(p, 2))
        self.addCleanup(a.stop)
        self.assertEqual(a.app.port, p)
        deps2 = FakeDeps(self.sb.paths)
        with contextlib.redirect_stdout(io.StringIO()):
            rc = S.serve(self._cfg(p, 2), None, True, paths=self.sb.paths, deps=deps2, spawn=fake_spawn({}))
        self.assertEqual(rc, 0)
        self.assertEqual(deps2.opened, [f"http://127.0.0.1:{p}/"])
        info = fsx.read_json(self.sb.paths.ui_server_json(), None)
        self.assertEqual(info["instance_id"], a.app.instance_id)       # 두 번째는 서버를 띄우지 않았다
        self.assertTrue(a.t.is_alive())
        h = S._get_hello(p)
        self.assertEqual(h["instance_id"], a.app.instance_id)

    def test_rpt38_other_root_uses_next_port(self):
        p = free_ports(3)
        a = _Bg(self.sb, self._cfg(p, 2))
        self.addCleanup(a.stop)
        sb2 = Sandbox()
        self.addCleanup(sb2.cleanup)
        b = _Bg(sb2, sb2.cfg(**{"ui.port": p, "ui.portFallbackCount": 2}))
        self.addCleanup(b.stop)
        self.assertEqual(b.app.port, p + 1)                            # 두 설치본 공존(R §2.3.1)
        self.assertNotEqual(b.app.root_id, a.app.root_id)

    def test_find_existing_via_server_json(self):
        p = free_ports(2)
        a = _Bg(self.sb, self._cfg(p, 1))
        self.addCleanup(a.stop)
        other = proc.spawn([sys.executable, "-c", "import time; time.sleep(60)"], stdout=proc.DEVNULL,
                           stderr=proc.DEVNULL)
        self.addCleanup(other.close)
        self.addCleanup(other.kill_tree)
        info = fsx.read_json(self.sb.paths.ui_server_json(), None)
        info["pid"] = other.pid                                         # 다른 프로세스가 띄운 것처럼
        fsx.atomic_write(self.sb.paths.ui_server_json(), fsx.canon_bytes(info))
        hit = S.find_existing(self.sb.paths, self._cfg(p, 1))
        self.assertIsNotNone(hit)
        self.assertEqual(hit[0], p)
        info["instance_id"] = "i_" + "0" * 16
        fsx.atomic_write(self.sb.paths.ui_server_json(), fsx.canon_bytes(info))
        self.assertIsNone(S.find_existing(self.sb.paths, self._cfg(p, 1)))


class CheckTest(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()
        self.addCleanup(self.sb.cleanup)
        self.socks = []
        self.addCleanup(lambda: [s.close() for s in self.socks])

    def test_check_ok(self):
        p = free_ports(2)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = S.check(self.sb.cfg(**{"ui.port": p, "ui.portFallbackCount": 1}), None, paths=self.sb.paths,
                         deps=FakeDeps(self.sb.paths))
        self.assertEqual(rc, 0)
        self.assertIn(f"통과 — 127.0.0.1:{p}", out.getvalue())

    def test_check_ports_busy_rc3_korean(self):
        p = free_ports(2)
        self.socks += hold_ports(p, 2)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = S.check(self.sb.cfg(**{"ui.port": p, "ui.portFallbackCount": 1}), None, paths=self.sb.paths,
                         deps=FakeDeps(self.sb.paths))
        self.assertEqual(rc, 3)
        self.assertIn("화면 서버를 열 포트를 찾지 못했습니다", out.getvalue())

    def test_check_missing_static_rc3(self):
        class NoWeb(TPaths):
            def web_file(self, rel):
                return self.root.joinpath("web", *rel.split("/"))
        paths = NoWeb(self.sb.root, lad=self.sb.lad)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = S.check(self.sb.cfg(), None, paths=paths, deps=FakeDeps(paths))
        self.assertEqual(rc, 3)
        self.assertIn("화면 파일 web\\app\\index.html", out.getvalue())

    def test_cli_ui_check_adapter(self):
        """lm27_cli.py ui --check(LoadMonitor27-UI.bat 의 첫 단계) — 실제 cli 어댑터 → server.check → rc 0 · 한국어."""
        p = free_ports(10)
        lad = self.sb.dir / "cli_lad"
        lad.mkdir()
        env = {"LOCALAPPDATA": os.fspath(lad), "PYTHONDONTWRITEBYTECODE": "1"}
        r = proc.run_child([sys.executable, "-X", "utf8", "-B", os.fspath(REPO / "lm27_cli.py"), "ui", "--check",
                            "--port", str(p)], timeout_s=120, env=env, cwd=os.fspath(self.sb.dir))
        self.assertEqual(r.rc, 0, r.out_text() + r.err_text())
        self.assertIn("[화면 점검] 통과", r.out_text())
        self.assertTrue((lad / "LoadMonitor27" / "ui").is_dir())


if __name__ == "__main__":
    unittest.main()
